from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pandas as pd
import pytest

from trading_signal_bot.models import Timeframe
from trading_signal_bot.mt5_client import MT5Client, ReconnectConfig


@dataclass
class _FakeTick:
    last: float | None = 100.5
    bid: float | None = 100.4
    ask: float | None = 100.6


class FakeMT5:
    TIMEFRAME_M1 = 1
    TIMEFRAME_M15 = 15

    def __init__(self, initialize_failures: int = 0) -> None:
        self.initialize_failures = initialize_failures
        self.initialize_calls = 0
        self.connected = False
        self.last_symbol_used: str | None = None

    def initialize(self, path: str | None = None) -> bool:
        _ = path
        self.initialize_calls += 1
        if self.initialize_calls <= self.initialize_failures:
            self.connected = False
            return False
        self.connected = True
        return True

    def login(self, login: int, password: str, server: str) -> bool:
        _ = (login, password, server)
        return self.connected

    def shutdown(self) -> None:
        self.connected = False

    def terminal_info(self):
        return object() if self.connected else None

    def account_info(self):
        return object() if self.connected else None

    def last_error(self):
        return (500, "simulated")

    def symbol_info(self, symbol: str):
        if symbol == "BAD":
            return None
        return SimpleNamespace(trade_mode=4)

    def symbol_select(self, symbol: str, enable: bool) -> bool:
        _ = enable
        self.last_symbol_used = symbol
        return True

    def copy_rates_from_pos(self, symbol: str, timeframe: int, start_pos: int, count: int):
        _ = (timeframe, start_pos)
        self.last_symbol_used = symbol
        rows = []
        for i in range(count):
            rows.append(
                {
                    "time": 1730000000 + i * 60,
                    "open": 1.0 + i,
                    "high": 1.5 + i,
                    "low": 0.5 + i,
                    "close": 1.2 + i,
                    "tick_volume": 100,
                }
            )
        return rows

    def symbol_info_tick(self, symbol: str):
        _ = symbol
        return _FakeTick()


def test_reconnect_after_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeMT5(initialize_failures=2)
    client = MT5Client(
        login=1,
        password="x",
        server="srv",
        path=None,
        alias_map={"XAUUSD": "XAUUSDm"},
        reconnect=ReconnectConfig(max_retries=5, base_delay_seconds=0, max_delay_seconds=0),
        mt5_module=fake,
    )
    monkeypatch.setattr("trading_signal_bot.mt5_client.time.sleep", lambda _: None)
    assert client.reconnect() is True


def test_reconnect_exhausted(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = FakeMT5(initialize_failures=10)
    client = MT5Client(
        login=1,
        password="x",
        server="srv",
        path=None,
        alias_map={},
        reconnect=ReconnectConfig(max_retries=3, base_delay_seconds=0, max_delay_seconds=0),
        mt5_module=fake,
    )
    monkeypatch.setattr("trading_signal_bot.mt5_client.time.sleep", lambda _: None)
    assert client.reconnect() is False


def test_symbol_alias_resolution_and_fetch() -> None:
    fake = FakeMT5()
    client = MT5Client(
        login=1,
        password="x",
        server="srv",
        path=None,
        alias_map={"XAUUSD": "XAUUSDm"},
        reconnect=ReconnectConfig(max_retries=1, base_delay_seconds=0, max_delay_seconds=0),
        mt5_module=fake,
    )
    assert client.connect() is True
    df = client.fetch_candles("XAUUSD", Timeframe.M1, count=5)
    assert isinstance(df, pd.DataFrame)
    assert len(df) == 5
    assert fake.last_symbol_used == "XAUUSDm"


def test_invalid_symbol_validation() -> None:
    fake = FakeMT5()
    client = MT5Client(
        login=1,
        password="x",
        server="srv",
        path=None,
        alias_map={"XAUUSD": "BAD"},
        reconnect=ReconnectConfig(max_retries=1, base_delay_seconds=0, max_delay_seconds=0),
        mt5_module=fake,
    )
    assert client.connect() is True
    validation = client.validate_symbol_aliases({"XAUUSD": "BAD"})
    assert validation["XAUUSD"] is False
