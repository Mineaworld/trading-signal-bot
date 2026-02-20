from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd

from backtester.data_loader import BacktestRange, load_historical
from trading_signal_bot.models import Timeframe


class _FakeMT5Client:
    def __init__(self, candles: pd.DataFrame) -> None:
        self._candles = candles
        self.calls = 0

    def fetch_candles(self, symbol: str, timeframe: Timeframe, count: int) -> pd.DataFrame:
        _ = (symbol, timeframe, count)
        self.calls += 1
        return self._candles.copy()


def test_load_historical_uses_distinct_cache_per_intraday_range(tmp_path) -> None:
    times = pd.date_range("2026-02-11 00:00:00", periods=24 * 60, freq="1min", tz="UTC")
    candles = pd.DataFrame(
        {
            "time": times,
            "open": 1.0,
            "high": 1.1,
            "low": 0.9,
            "close": 1.0,
            "tick_volume": 1,
        }
    )
    client = _FakeMT5Client(candles)

    morning = BacktestRange(
        start=datetime(2026, 2, 11, 9, 0, tzinfo=timezone.utc),
        end=datetime(2026, 2, 11, 10, 0, tzinfo=timezone.utc),
    )
    afternoon = BacktestRange(
        start=datetime(2026, 2, 11, 14, 0, tzinfo=timezone.utc),
        end=datetime(2026, 2, 11, 15, 0, tzinfo=timezone.utc),
    )

    morning_df = load_historical(client, "XAUUSD", Timeframe.M1, morning, tmp_path)
    afternoon_df = load_historical(client, "XAUUSD", Timeframe.M1, afternoon, tmp_path)

    assert client.calls == 2
    assert morning_df["time"].min() >= morning.start
    assert morning_df["time"].max() <= morning.end
    assert afternoon_df["time"].min() >= afternoon.start
    assert afternoon_df["time"].max() <= afternoon.end
    assert morning_df["time"].max() < afternoon_df["time"].min()
