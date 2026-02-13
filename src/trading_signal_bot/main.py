from __future__ import annotations

import argparse
import logging
import time
from collections.abc import Iterable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pandas as pd

from trading_signal_bot.models import Signal
from trading_signal_bot.mt5_client import MT5Client, ReconnectConfig
from trading_signal_bot.repositories.dedup_store import DedupStore
from trading_signal_bot.settings import AppConfig, SecretsConfig, load_secrets, load_yaml_config
from trading_signal_bot.strategy import StrategyEvaluator
from trading_signal_bot.telegram_notifier import TelegramNotifier
from trading_signal_bot.utils import (
    seconds_until_next_m1_close,
    seconds_until_next_m15_close,
    setup_logging,
    single_instance_lock,
)


class TradingSignalBotApp:
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

        self._strategy = strategy or StrategyEvaluator(config.indicators)
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
        if self._config.m1_only.enabled:
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
                self._evaluate_m1_only_signal(symbol)
            except Exception:
                self._logger.exception("M1-only processing error: %s", symbol)

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

        m15_open = _as_utc(m15_closed.iloc[-1]["time"])
        m15_close = m15_open + timedelta(minutes=15)
        if self._last_processed_m15_close.get(symbol) == m15_close:
            self._logger.debug("already processed M15 close for %s at %s", symbol, m15_close)
            return

        if not self._strategy.m15_requires_m1(m15_closed, m15_close):
            self._logger.info("M15 preconditions not met for %s at %s", symbol, m15_close)
            self._last_processed_m15_close[symbol] = m15_close
            return

        m1 = self._mt5.fetch_candles(
            symbol, self._config.timeframe.confirmation, self._config.data.candle_buffer
        )
        m1_closed = _closed_bars_only(m1)
        current_price = self._mt5.get_current_price(symbol)
        signals = self._evaluate_signals(
            m15_df=m15_closed,
            m1_df=m1_closed,
            symbol=symbol,
            m15_close_time_utc=m15_close,
            price=current_price,
        )
        self._last_processed_m15_close[symbol] = m15_close

        if not signals:
            self._logger.info("no signal for %s at %s", symbol, m15_close)
            return

        for signal in signals:
            if not self._dedup.should_emit(signal):
                self._logger.info("signal blocked by dedup: %s", signal.idempotency_key)
                continue

            self._dedup.record(signal)
            sent = self._telegram.send_signal(signal)
            if sent:
                self._logger.info(
                    "signal sent: symbol=%s dir=%s scenario=%s",
                    signal.symbol,
                    signal.direction.value,
                    signal.scenario.value,
                )
            else:
                self._logger.warning("signal queued after failed send: %s", signal.id)

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
            m1_slice = m1_closed.iloc[: pos + 1].reset_index(drop=True)
            signal = self._strategy.evaluate_m1_only(
                m1_df=m1_slice,
                symbol=symbol,
                price=current_price if pos == latest_pending else None,
            )
            if signal is None:
                self._last_processed_m1_close[symbol] = m1_close
                continue

            if not self._dedup.should_emit(signal):
                self._logger.info("M1-only signal blocked by dedup: %s", signal.idempotency_key)
                self._last_processed_m1_close[symbol] = m1_close
                continue

            self._dedup.record(signal)
            sent = self._telegram.send_signal(signal)
            if sent:
                self._logger.info(
                    "M1-only signal sent: symbol=%s dir=%s scenario=%s",
                    signal.symbol,
                    signal.direction.value,
                    signal.scenario.value,
                )
            else:
                self._logger.warning("M1-only signal queued after failed send: %s", signal.id)
            self._last_processed_m1_close[symbol] = m1_close

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
                    for signal in signals:
                        if not self._dedup.should_emit(signal):
                            continue
                        self._dedup.record(signal)
                        self._telegram.send_signal(signal)

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
                return [signal for signal in signals if isinstance(signal, Signal)]
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


if __name__ == "__main__":
    main()
