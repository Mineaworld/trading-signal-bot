from __future__ import annotations

import argparse
import logging
import time
from collections import defaultdict
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import pandas as pd
import requests

from trading_signal_bot.models import (
    Direction,
    PendingSetup,
    PendingState,
    Scenario,
    Signal,
    TriggerMode,
)
from trading_signal_bot.mt5_client import MT5Client, ReconnectConfig
from trading_signal_bot.repositories.dedup_store import DedupStore
from trading_signal_bot.repositories.signal_journal import SignalJournal
from trading_signal_bot.settings import AppConfig, SecretsConfig, load_secrets, load_yaml_config
from trading_signal_bot.strategy import M15Trigger, StrategyEvaluator
from trading_signal_bot.telegram_notifier import TelegramNotifier
from trading_signal_bot.utils import (
    atomic_write_json,
    seconds_until_next_m1_close,
    seconds_until_next_m15_close,
    setup_logging,
    single_instance_lock,
    utc_now,
)


class TradingSignalBotApp:
    _PENDING_SETUP_MAX_AGE = timedelta(hours=8)

    def __init__(
        self,
        config: AppConfig,
        secrets: SecretsConfig,
        dry_run: bool = False,
        mt5_module: Any | None = None,
        mt5_client: MT5Client | None = None,
        strategy: StrategyEvaluator | None = None,
        dedup_store: DedupStore | None = None,
        telegram_notifier: TelegramNotifier | None = None,
    ) -> None:
        self._config = config
        self._dry_run = dry_run
        self._logger = logging.getLogger(self.__class__.__name__)
        self._last_processed_m15_close: dict[str, datetime] = {}
        self._last_processed_m1_close: dict[str, datetime] = {}
        self._last_m15_cycle_close: datetime | None = None
        self._pending_setups: dict[str, dict[tuple[Direction, TriggerMode], PendingSetup]] = (
            defaultdict(dict)
        )
        self._last_heartbeat_at: datetime | None = None
        self._session_tz = ZoneInfo(config.session_filter.timezone)
        self._session_windows: list[tuple[int, int]] = [
            _parse_hhmm_window(window.start, window.end) for window in config.session_filter.windows
        ]
        self._journal: SignalJournal | None = (
            SignalJournal(config.journal.sqlite_path) if config.journal.enabled else None
        )
        self._http_session = requests.Session()

        self._mt5 = mt5_client or MT5Client(
            login=secrets.mt5_login,
            password=secrets.mt5_password,
            server=secrets.mt5_server,
            path=secrets.mt5_terminal_path,
            alias_map=config.symbols,
            reconnect=ReconnectConfig(
                max_retries=config.execution.reconnect_max_retries,
                base_delay_seconds=config.execution.reconnect_base_delay_seconds,
                max_delay_seconds=config.execution.reconnect_max_delay_seconds,
            ),
            mt5_module=mt5_module,
        )

        self._strategy = strategy or StrategyEvaluator(
            config.indicators,
            require_opposite_zone_on_lwma_cross=(
                config.strategy.chain.require_opposite_zone_on_lwma_cross
            ),
            regime_filter=config.regime_filter,
            risk_context=config.risk_context,
        )
        self._dedup = dedup_store or DedupStore(
            state_file=config.signal_dedup.state_file,
            cooldown_minutes=config.signal_dedup.cooldown_minutes,
            retention_days=config.signal_dedup.retention_days,
        )
        self._telegram = telegram_notifier or TelegramNotifier(
            token=secrets.telegram_bot_token,
            chat_id=secrets.telegram_chat_id,
            failed_queue_file=config.telegram.failed_queue_file,
            max_queue=config.telegram.max_queue_size,
            max_retries=config.telegram.max_retries,
            max_failed_retry_count=config.telegram.max_failed_retry_count,
            timeout_seconds=config.telegram.request_timeout_seconds,
            dry_run=dry_run,
        )

    def startup(self) -> None:
        preflight = self._startup_preflight()
        self._logger.info(
            "mt5 startup preflight path=%s terminal_running=%s",
            preflight["terminal_path"],
            preflight["terminal_running"],
        )
        if not self._mt5.connect():
            raise RuntimeError("startup failed: cannot connect/login MT5")

        alias_status = self._mt5.validate_symbol_aliases(self._config.symbols)
        missing = [alias for alias, exists in alias_status.items() if not exists]
        if missing:
            raise RuntimeError(f"startup failed: unresolved symbol aliases: {', '.join(missing)}")

        if not self._telegram.send_startup_message():
            raise RuntimeError("startup failed: telegram startup check failed")

        self._replay_startup_window()
        if self._last_processed_m15_close:
            self._last_m15_cycle_close = max(self._last_processed_m15_close.values())
        self._telegram.retry_failed_queue()
        self._logger.info("startup completed")

    def _startup_preflight(self) -> dict[str, str]:
        preflight_fn = getattr(self._mt5, "startup_preflight", None)
        if callable(preflight_fn):
            result = preflight_fn()
            if isinstance(result, dict):
                return {
                    "terminal_path": str(result.get("terminal_path", "<unknown>")),
                    "terminal_running": str(result.get("terminal_running", "unknown")),
                }
        return {"terminal_path": "<unknown>", "terminal_running": "unknown"}

    def run_forever(self) -> None:
        if self._config.m1_only.enabled or self._config.strategy.chain.enabled:
            self._run_forever_with_m1_only()
            return

        self._run_forever_m15_only()

    def _run_forever_m15_only(self) -> None:
        while True:
            try:
                wait_seconds = seconds_until_next_m15_close()
                self._logger.info("sleeping %.2fs until next M15 close", wait_seconds)
                time.sleep(wait_seconds)

                self._run_m15_cycle()
                self._telegram.retry_failed_queue()
                self._emit_heartbeat()
            except KeyboardInterrupt:
                self._logger.info("received interrupt, shutting down")
                break
            except Exception:
                self._logger.exception("loop error, sleeping before retry")
                time.sleep(self._config.execution.loop_failure_sleep_seconds)

    def _run_forever_with_m1_only(self) -> None:
        while True:
            try:
                wait_seconds = seconds_until_next_m1_close()
                self._logger.info("sleeping %.2fs until next M1 close", wait_seconds)
                time.sleep(wait_seconds)

                if self._should_run_m15_cycle():
                    self._run_m15_cycle()
                self._run_m1_only_cycle()

                self._telegram.retry_failed_queue()
                self._emit_heartbeat()
            except KeyboardInterrupt:
                self._logger.info("received interrupt, shutting down")
                break
            except Exception:
                self._logger.exception("loop error, sleeping before retry")
                time.sleep(self._config.execution.loop_failure_sleep_seconds)

    def _run_m15_cycle(self) -> None:
        for symbol in self._config.symbols:
            try:
                self._process_symbol(symbol)
            except Exception:
                self._logger.exception("symbol processing error: %s", symbol)

    def _run_m1_only_cycle(self) -> None:
        for symbol in self._config.symbols:
            try:
                if self._config.strategy.chain.enabled:
                    self._evaluate_pending_chain_signal(symbol)
                self._evaluate_m1_only_signal(symbol)
            except Exception:
                self._logger.exception("M1 processing error: %s", symbol)

    def _should_run_m15_cycle(self, now: datetime | None = None) -> bool:
        current = now or datetime.now(timezone.utc)
        rounded_minute = (current.minute // 15) * 15
        latest_m15_close = current.replace(minute=rounded_minute, second=0, microsecond=0)
        if self._last_m15_cycle_close is None:
            self._last_m15_cycle_close = latest_m15_close
            return True
        if latest_m15_close > self._last_m15_cycle_close:
            self._last_m15_cycle_close = latest_m15_close
            return True
        return False

    def _process_symbol(self, symbol: str) -> None:
        if not self._mt5.is_symbol_tradable(symbol):
            self._logger.info("symbol not tradable, skipping: %s", symbol)
            return

        m15 = self._mt5.fetch_candles(
            symbol, self._config.timeframe.primary, self._config.data.candle_buffer
        )
        m15_closed = _closed_bars_only(m15)
        if (
            len(m15_closed)
            < max(self._config.indicators.lwma_slow, self._config.indicators.stoch_k) + 2
        ):
            self._logger.warning("insufficient M15 bars for %s", symbol)
            return

        m15_close_times = pd.to_datetime(m15_closed["time"], utc=True) + timedelta(minutes=15)
        pending_positions = self._pending_m15_positions(symbol, m15_close_times)
        if not pending_positions:
            return

        m1_closed = pd.DataFrame()
        if self._config.strategy.enable_legacy_scenarios or self._config.strategy.chain.enabled:
            m1 = self._mt5.fetch_candles(
                symbol, self._config.timeframe.confirmation, self._config.data.candle_buffer
            )
            m1_closed = _closed_bars_only(m1)
        current_price = self._mt5.get_current_price(symbol)
        latest_pending_pos = pending_positions[-1]

        for pos in pending_positions:
            m15_close = _as_utc(m15_close_times.iloc[pos])
            if self._config.session_filter.enabled and not self._is_session_active(m15_close):
                self._logger.info("outside session window for %s at %s", symbol, m15_close)
                self._last_processed_m15_close[symbol] = m15_close
                continue

            m15_slice = m15_closed.iloc[: pos + 1].reset_index(drop=True)
            cycle_signals: list[Signal] = []

            if self._config.strategy.enable_legacy_scenarios and not m1_closed.empty:
                m1_slice = m1_closed[m1_closed["time"] <= m15_close].reset_index(drop=True)
                cycle_signals.extend(
                    self._evaluate_signals(
                        m15_df=m15_slice,
                        m1_df=m1_slice,
                        symbol=symbol,
                        m15_close_time_utc=m15_close,
                        price=current_price if pos == latest_pending_pos else None,
                    )
                )

            if self._config.strategy.chain.enabled:
                triggers = self._strategy.evaluate_m15_triggers(m15_slice, m15_close)
                if triggers:
                    self._register_m15_triggers(symbol, triggers)
                    self._logger.info(
                        "registered chain triggers for %s at %s count=%s",
                        symbol,
                        m15_close,
                        len(triggers),
                    )

            self._last_processed_m15_close[symbol] = m15_close

            if not cycle_signals:
                self._logger.info("no signal for %s at %s", symbol, m15_close)
                continue

            self._emit_signals(cycle_signals, context="M15")

    def _evaluate_m1_only_signal(self, symbol: str) -> None:
        """Evaluate M1-only signals on a 1-minute cycle, including missed bars."""
        if not self._config.m1_only.enabled:
            return

        if not self._mt5.is_symbol_tradable(symbol):
            return

        m1 = self._mt5.fetch_candles(
            symbol, self._config.timeframe.confirmation, self._config.data.candle_buffer
        )
        m1_closed = _closed_bars_only(m1)
        if m1_closed.empty:
            return

        m1_close_times = pd.to_datetime(m1_closed["time"], utc=True) + timedelta(minutes=1)
        latest_m1_close = _as_utc(m1_close_times.iloc[-1])
        last_processed = self._last_processed_m1_close.get(symbol)
        if last_processed is None:
            self._last_processed_m1_close[symbol] = latest_m1_close
            self._logger.info(
                "initialized M1-only cursor for %s at %s",
                symbol,
                latest_m1_close,
            )
            return

        pending_positions = [
            idx
            for idx, m1_close in enumerate(m1_close_times.tolist())
            if _as_utc(m1_close) > last_processed
        ]
        if not pending_positions:
            return

        current_price = self._mt5.get_current_price(symbol)
        latest_pending = pending_positions[-1]
        for pos in pending_positions:
            m1_close = _as_utc(m1_close_times.iloc[pos])
            if self._config.session_filter.enabled and not self._is_session_active(m1_close):
                self._last_processed_m1_close[symbol] = m1_close
                continue
            m1_slice = m1_closed.iloc[: pos + 1].reset_index(drop=True)
            signal = self._strategy.evaluate_m1_only(
                m1_df=m1_slice,
                symbol=symbol,
                price=current_price if pos == latest_pending else None,
            )
            if signal is None:
                self._last_processed_m1_close[symbol] = m1_close
                continue

            self._emit_signals([signal], context="M1-only")
            self._last_processed_m1_close[symbol] = m1_close

    def _evaluate_pending_chain_signal(self, symbol: str) -> None:
        pending_map = self._pending_setups.get(symbol)
        if not pending_map:
            return
        if not self._mt5.is_symbol_tradable(symbol):
            return

        m1 = self._mt5.fetch_candles(
            symbol, self._config.timeframe.confirmation, self._config.data.candle_buffer
        )
        m1_closed = _closed_bars_only(m1)
        if m1_closed.empty:
            return
        snapshot = self._strategy.latest_m1_snapshot(m1_closed)
        if snapshot is None:
            return

        m15 = self._mt5.fetch_candles(
            symbol, self._config.timeframe.primary, self._config.data.candle_buffer
        )
        m15_closed = _closed_bars_only(m15)
        m15_df = None if m15_closed.empty else m15_closed

        current_price = self._mt5.get_current_price(symbol)
        updated_map: dict[tuple[Direction, TriggerMode], PendingSetup] = {}
        chain_signals: list[Signal] = []
        for key, pending in pending_map.items():
            if (snapshot.bar_time_utc - pending.m15_trigger_time_utc) > self._PENDING_SETUP_MAX_AGE:
                self._logger.info(
                    "expired stale pending setup for %s dir=%s mode=%s",
                    symbol,
                    pending.direction.value,
                    pending.mode.value,
                )
                continue
            updated_pending, signal = self._strategy.advance_pending_setup(
                pending=pending,
                snapshot=snapshot,
                price=current_price,
                m15_df=m15_df,
            )
            if updated_pending is not None:
                updated_map[key] = updated_pending
            if signal is not None:
                chain_signals.append(signal)

        self._pending_setups[symbol] = updated_map
        if chain_signals:
            self._emit_signals(chain_signals, context="M1-chain")

    def _register_m15_triggers(self, symbol: str, triggers: list[M15Trigger]) -> None:
        if not triggers:
            return
        pending_map = self._pending_setups[symbol]
        trigger_directions = {trigger.direction for trigger in triggers}
        if Direction.BUY in trigger_directions:
            pending_map = {
                key: value
                for key, value in pending_map.items()
                if value.direction is not Direction.SELL
            }
        if Direction.SELL in trigger_directions:
            pending_map = {
                key: value
                for key, value in pending_map.items()
                if value.direction is not Direction.BUY
            }

        for trigger in triggers:
            key = (trigger.direction, trigger.mode)
            pending_map[key] = PendingSetup(
                symbol=symbol,
                direction=trigger.direction,
                mode=trigger.mode,
                state=PendingState.WAIT_M1_LWMA,
                m15_trigger_time_utc=trigger.m15_close_time_utc,
                last_updated_utc=utc_now(),
                m15_lwma_fast=trigger.m15_lwma_fast,
                m15_lwma_slow=trigger.m15_lwma_slow,
                m15_stoch_k=trigger.m15_stoch_k,
                m15_stoch_d=trigger.m15_stoch_d,
            )
        self._pending_setups[symbol] = pending_map

    def _replay_startup_window(self) -> None:
        self._logger.info("starting replay of last 3 closed M15 bars")
        for symbol in self._config.symbols:
            try:
                m15 = self._mt5.fetch_candles(
                    symbol, self._config.timeframe.primary, self._config.data.candle_buffer
                )
                m15_closed = _closed_bars_only(m15)
                if len(m15_closed) < 4:
                    continue
                m1 = self._mt5.fetch_candles(
                    symbol, self._config.timeframe.confirmation, self._config.data.candle_buffer
                )
                m1_closed = _closed_bars_only(m1)
                replay_rows = m15_closed.tail(3)
                for _, row in replay_rows.iterrows():
                    row_open = _as_utc(row["time"])
                    row_close = row_open + timedelta(minutes=15)
                    if self._config.session_filter.enabled and not self._is_session_active(
                        row_close
                    ):
                        continue

                    m15_slice = m15_closed[m15_closed["time"] <= row["time"]].reset_index(drop=True)
                    if not self._strategy.m15_requires_m1(m15_slice, row_close):
                        continue

                    m1_slice = m1_closed[m1_closed["time"] <= row_close].reset_index(drop=True)
                    signals = self._evaluate_signals(
                        m15_df=m15_slice,
                        m1_df=m1_slice,
                        symbol=symbol,
                        m15_close_time_utc=row_close,
                        price=None,
                    )
                    self._emit_signals(signals, context="replay")

                latest_open = _as_utc(m15_closed.iloc[-1]["time"])
                self._last_processed_m15_close[symbol] = latest_open + timedelta(minutes=15)
            except Exception:
                self._logger.exception("startup replay failed for symbol=%s", symbol)

    def _evaluate_signals(
        self,
        m15_df: pd.DataFrame,
        m1_df: pd.DataFrame,
        symbol: str,
        m15_close_time_utc: datetime,
        price: float | None = None,
    ) -> list[Signal]:
        evaluate_all = getattr(self._strategy, "evaluate_all", None)
        if callable(evaluate_all):
            signals = evaluate_all(
                m15_df=m15_df,
                m1_df=m1_df,
                symbol=symbol,
                m15_close_time_utc=m15_close_time_utc,
                price=price,
            )
            if isinstance(signals, list):
                return signals
            if isinstance(signals, Iterable):
                parsed_signals: list[Signal] = []
                for item in signals:
                    if isinstance(item, Signal):
                        parsed_signals.append(item)
                return parsed_signals
            return []

        fallback_signal = self._strategy.evaluate(
            m15_df=m15_df,
            m1_df=m1_df,
            symbol=symbol,
            m15_close_time_utc=m15_close_time_utc,
            price=price,
        )
        if fallback_signal is None:
            return []
        return [fallback_signal]

    def _pending_m15_positions(
        self,
        symbol: str,
        m15_close_times: pd.Series,
    ) -> list[int]:
        last_processed = self._last_processed_m15_close.get(symbol)
        if last_processed is None:
            return [len(m15_close_times) - 1]
        pending = [
            idx
            for idx, close_time in enumerate(m15_close_times.tolist())
            if _as_utc(close_time) > last_processed
        ]
        if len(pending) <= self._config.execution.max_m15_backfill_bars:
            return pending
        dropped = len(pending) - self._config.execution.max_m15_backfill_bars
        self._logger.warning(
            "backfill cap hit for %s, dropped_old_bars=%s cap=%s",
            symbol,
            dropped,
            self._config.execution.max_m15_backfill_bars,
        )
        return pending[-self._config.execution.max_m15_backfill_bars :]

    def _is_session_active(self, time_utc: datetime) -> bool:
        local = time_utc.astimezone(self._session_tz)
        minute_of_day = local.hour * 60 + local.minute
        for start_minute, end_minute in self._session_windows:
            if start_minute <= end_minute:
                if start_minute <= minute_of_day < end_minute:
                    return True
                continue
            if minute_of_day >= start_minute or minute_of_day < end_minute:
                return True
        return False

    def _emit_signals(self, signals: list[Signal], context: str) -> None:
        if not signals:
            return

        grouped: dict[tuple[str, Direction], list[Signal]] = defaultdict(list)
        for signal in signals:
            grouped[(signal.symbol, signal.direction)].append(signal)

        for _, grouped_signals in grouped.items():
            to_send = grouped_signals
            summarized = False
            if self._config.strategy.summary.enabled and len(grouped_signals) > 1:
                summary_signal = self._build_summary_signal(grouped_signals)
                to_send = [summary_signal]
                summarized = True

            for signal in to_send:
                if not self._dedup.should_emit(signal):
                    self._logger.info(
                        "%s signal blocked by dedup: %s", context, signal.idempotency_key
                    )
                    continue
                sent = self._send_with_record(signal, context=context)
                if sent and summarized:
                    for suppressed_signal in grouped_signals:
                        self._dedup.record_idempotency_only(suppressed_signal)

    def _build_summary_signal(self, grouped_signals: list[Signal]) -> Signal:
        base = max(grouped_signals, key=lambda signal: signal.m1_bar_time_utc)
        matched = sorted(
            {signal.scenario for signal in grouped_signals}, key=lambda item: item.value
        )
        scenario = (
            Scenario.BUY_SUMMARY if base.direction is Direction.BUY else Scenario.SELL_SUMMARY
        )
        return Signal(
            id=Signal.new_id(),
            symbol=base.symbol,
            direction=base.direction,
            scenario=scenario,
            price=base.price,
            created_at_utc=utc_now(),
            m15_bar_time_utc=base.m15_bar_time_utc,
            m1_bar_time_utc=base.m1_bar_time_utc,
            m15_lwma_fast=base.m15_lwma_fast,
            m15_lwma_slow=base.m15_lwma_slow,
            m15_stoch_k=base.m15_stoch_k,
            m15_stoch_d=base.m15_stoch_d,
            m1_lwma_fast=base.m1_lwma_fast,
            m1_lwma_slow=base.m1_lwma_slow,
            m1_stoch_k=base.m1_stoch_k,
            m1_stoch_d=base.m1_stoch_d,
            matched_scenarios=matched,
            risk_stop_distance=base.risk_stop_distance,
            risk_invalidation_price=base.risk_invalidation_price,
            risk_tp1_price=base.risk_tp1_price,
            risk_tp2_price=base.risk_tp2_price,
        )

    def _send_with_record(self, signal: Signal, context: str) -> bool:
        sent = self._telegram.send_signal(signal)
        if sent:
            self._dedup.record(signal)
            if self._journal is not None:
                self._journal.record_sent_signal(signal, sent_success=True)
            self._logger.info(
                "%s signal sent: symbol=%s dir=%s scenario=%s",
                context,
                signal.symbol,
                signal.direction.value,
                signal.scenario.value,
            )
            return True
        if self._journal is not None:
            self._journal.record_sent_signal(signal, sent_success=False)
        self._logger.warning("%s signal queued after failed send: %s", context, signal.id)
        return False

    def _emit_heartbeat(self) -> None:
        if not self._config.monitoring.heartbeat_enabled:
            return
        now = utc_now()
        if (
            self._last_heartbeat_at is not None
            and (now - self._last_heartbeat_at).total_seconds()
            < self._config.monitoring.heartbeat_interval_seconds
        ):
            return

        queue_size_fn = getattr(self._telegram, "queue_size", None)
        queue_size_raw: object = queue_size_fn() if callable(queue_size_fn) else 0
        queue_size = _to_int_or_default(queue_size_raw, default=0)
        try:
            mt5_connected = bool(self._mt5.is_connected())
        except Exception:
            mt5_connected = False

        last_m15_processed: dict[str, str] = {
            k: v.isoformat() for k, v in self._last_processed_m15_close.items()
        }
        payload = {
            "timestamp_utc": now.isoformat(),
            "last_m15_processed": last_m15_processed,
            "queue_size": queue_size,
            "mt5_connected": mt5_connected,
            "m1_only_enabled": self._config.m1_only.enabled,
        }
        atomic_write_json(self._config.monitoring.heartbeat_file, payload)
        self._logger.info(
            "heartbeat ok queue_size=%s symbols=%s", queue_size, len(last_m15_processed)
        )

        ping_url = self._config.monitoring.heartbeat_ping_url.strip()
        if ping_url:
            try:
                self._http_session.post(ping_url, json=payload, timeout=10)
            except requests.RequestException as exc:
                self._logger.warning("heartbeat ping failed: %s", exc)
        self._last_heartbeat_at = now


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Trading Signal Bot")
    parser.add_argument("--config", type=Path, default=Path("config/settings.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--lock-file", type=Path, default=Path("data/bot.lock"))
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_yaml_config(args.config)
    secrets = load_secrets(args.env)
    setup_logging(
        level=config.logging.level,
        file_path=config.logging.file,
        max_bytes=config.logging.max_bytes,
        backup_count=config.logging.backup_count,
    )
    logger = logging.getLogger("main")
    logger.info("starting trading signal bot dry_run=%s", args.dry_run)

    with single_instance_lock(args.lock_file):
        app = TradingSignalBotApp(config=config, secrets=secrets, dry_run=args.dry_run)
        app.startup()
        app.run_forever()


def _closed_bars_only(df: pd.DataFrame) -> pd.DataFrame:
    if len(df) <= 1:
        return df.iloc[0:0].copy()
    return df.iloc[:-1].reset_index(drop=True)


def _as_utc(value: int | float | str | date | datetime | pd.Timestamp) -> datetime:
    ts = pd.Timestamp(value)
    if ts.tzinfo is None:
        return ts.to_pydatetime().replace(tzinfo=timezone.utc)
    return ts.tz_convert(timezone.utc).to_pydatetime()


def _parse_hhmm_window(start: str, end: str) -> tuple[int, int]:
    start_parts = start.split(":")
    end_parts = end.split(":")
    if len(start_parts) != 2 or len(end_parts) != 2:
        raise ValueError("session window must be HH:MM")
    start_minute = int(start_parts[0]) * 60 + int(start_parts[1])
    end_minute = int(end_parts[0]) * 60 + int(end_parts[1])
    if not (0 <= start_minute < 1440 and 0 <= end_minute < 1440):
        raise ValueError("session window minutes must be in [00:00, 23:59]")
    return (start_minute, end_minute)


def _to_int_or_default(value: object, default: int = 0) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return default
    return default


if __name__ == "__main__":
    main()
