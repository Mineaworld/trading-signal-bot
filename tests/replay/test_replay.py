from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
import pytest

from trading_signal_bot.main import TradingSignalBotApp
from trading_signal_bot.models import Direction, Scenario, Signal
from trading_signal_bot.settings import load_yaml_config

UTC = timezone.utc


def _m15_df() -> pd.DataFrame:
    # 7 bars where last bar is treated as forming and removed by app._closed_bars_only.
    times = pd.date_range("2026-02-11 10:00:00", periods=7, freq="15min", tz="UTC")
    closes = [100.0 + i for i in range(7)]
    return pd.DataFrame(
        {
            "time": times,
            "open": closes,
            "high": [x + 0.1 for x in closes],
            "low": [x - 0.1 for x in closes],
            "close": closes,
            "tick_volume": [1 for _ in closes],
        }
    )


def _m1_df() -> pd.DataFrame:
    times = pd.date_range("2026-02-11 10:00:00", periods=200, freq="1min", tz="UTC")
    closes = [200.0 + i for i in range(200)]
    return pd.DataFrame(
        {
            "time": times,
            "open": closes,
            "high": [x + 0.1 for x in closes],
            "low": [x - 0.1 for x in closes],
            "close": closes,
            "tick_volume": [1 for _ in closes],
        }
    )


class FakeMT5Client:
    def __init__(self, *args, **kwargs) -> None:
        _ = (args, kwargs)

    def connect(self) -> bool:
        return True

    def validate_symbol_aliases(self, alias_map):
        return {k: True for k in alias_map}

    def fetch_candles(self, symbol, timeframe, count=450):
        _ = (symbol, count)
        if str(timeframe).endswith("M15"):
            return _m15_df()
        return _m1_df()

    def is_symbol_tradable(self, symbol):
        _ = symbol
        return True

    def get_current_price(self, symbol):
        _ = symbol
        return 123.45

    def disconnect(self):
        pass

    def is_connected(self):
        return True


class FakeDedupStore:
    def __init__(self, *args, **kwargs):
        _ = (args, kwargs)
        self.records = []
        self.block = False

    def should_emit(self, signal):
        _ = signal
        return not self.block

    def record(self, signal):
        self.records.append(signal.id)

    def record_idempotency_only(self, signal):
        self.records.append(signal.id)

    def flush(self):
        pass


class FakeNotifier:
    def __init__(self, *args, **kwargs):
        _ = (args, kwargs)
        self.sent = []

    def send_startup_message(self):
        return True

    def retry_failed_queue(self):
        return 0

    def send_signal(self, signal):
        self.sent.append(signal.id)
        return True


class FakeStrategy:
    def __init__(self, *args, **kwargs):
        _ = (args, kwargs)
        self.slice_lengths = []

    def m15_requires_m1(self, m15_df, m15_close_time_utc):
        _ = m15_close_time_utc
        return len(m15_df) >= 4

    def evaluate(self, m15_df, m1_df, symbol, m15_close_time_utc, price=None):
        _ = (m1_df, symbol, price)
        self.slice_lengths.append(len(m15_df))
        if len(m15_df) != 5:
            return None
        return Signal(
            id=f"sig-{len(m15_df)}",
            symbol="XAUUSD",
            direction=Direction.BUY,
            scenario=Scenario.BUY_S1,
            price=1.0,
            created_at_utc=datetime.now(tz=UTC),
            m15_bar_time_utc=m15_close_time_utc,
            m1_bar_time_utc=m15_close_time_utc - timedelta(minutes=1),
            m15_lwma_fast=1.0,
            m15_lwma_slow=0.9,
            m15_stoch_k=12.0,
            m15_stoch_d=10.0,
            m1_stoch_k=14.0,
            m1_stoch_d=11.0,
        )


class FakeSecrets:
    mt5_login = 1
    mt5_password = "x"
    mt5_server = "srv"
    mt5_terminal_path = None
    telegram_bot_token = "t"
    telegram_chat_id = "c"
    heartbeat_ping_url = ""


def test_replay_slices_without_lookahead(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _ = tmp_path
    config = load_yaml_config(Path("config/settings.yaml"))
    config = replace(config, symbols={"XAUUSD": "XAUUSD"})

    monkeypatch.setattr("trading_signal_bot.main.MT5Client", FakeMT5Client)
    monkeypatch.setattr("trading_signal_bot.main.DedupStore", FakeDedupStore)
    monkeypatch.setattr("trading_signal_bot.main.TelegramNotifier", FakeNotifier)
    monkeypatch.setattr("trading_signal_bot.main.StrategyEvaluator", FakeStrategy)

    app = TradingSignalBotApp(config=config, secrets=FakeSecrets(), dry_run=True)
    app.startup()

    assert app._strategy.slice_lengths == [4, 5, 6]
    assert app._telegram.sent == ["sig-5"]


def test_replay_respects_dedup(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _ = tmp_path
    config = load_yaml_config(Path("config/settings.yaml"))
    config = replace(config, symbols={"XAUUSD": "XAUUSD"})

    monkeypatch.setattr("trading_signal_bot.main.MT5Client", FakeMT5Client)
    monkeypatch.setattr("trading_signal_bot.main.TelegramNotifier", FakeNotifier)
    monkeypatch.setattr("trading_signal_bot.main.StrategyEvaluator", FakeStrategy)

    class BlockingDedup(FakeDedupStore):
        def should_emit(self, signal):
            _ = signal
            return False

    monkeypatch.setattr("trading_signal_bot.main.DedupStore", BlockingDedup)

    app = TradingSignalBotApp(config=config, secrets=FakeSecrets(), dry_run=True)
    app.startup()
    assert app._telegram.sent == []


def test_run_forever_isolates_symbol_errors(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    _ = tmp_path
    config = load_yaml_config(Path("config/settings.yaml"))
    config = replace(config, symbols={"XAUUSD": "XAUUSD", "EURUSD": "EURUSD"})

    app = TradingSignalBotApp(
        config=config,
        secrets=FakeSecrets(),
        dry_run=True,
        mt5_client=FakeMT5Client(),
        strategy=FakeStrategy(),
        dedup_store=FakeDedupStore(),
        telegram_notifier=FakeNotifier(),
    )

    processed: list[str] = []

    def fake_process(symbol: str) -> None:
        if symbol == "XAUUSD":
            raise RuntimeError("simulated failure")
        processed.append(symbol)

    monkeypatch.setattr(app, "_process_symbol", fake_process)
    monkeypatch.setattr("trading_signal_bot.main.seconds_until_next_m15_close", lambda: 0.0)

    cycle_count = {"n": 0}
    original_run_m15 = app._run_m15_cycle

    def counting_m15_cycle() -> None:
        original_run_m15()
        cycle_count["n"] += 1
        if cycle_count["n"] >= 1:
            raise KeyboardInterrupt

    monkeypatch.setattr(app, "_run_m15_cycle", counting_m15_cycle)
    app.run_forever()
    assert processed == ["EURUSD"]
