from __future__ import annotations

from datetime import UTC, datetime

import pandas as pd
import pytest

from trading_signal_bot.models import Direction, Scenario, Signal


def make_ohlc_df(closes: list[float], start: str, freq: str) -> pd.DataFrame:
    times = pd.date_range(start=start, periods=len(closes), freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "time": times,
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "tick_volume": [100 for _ in closes],
        }
    )


@pytest.fixture
def sample_signal() -> Signal:
    now = datetime(2026, 2, 11, 14, 30, 5, tzinfo=UTC)
    return Signal(
        id="sig-123",
        symbol="XAUUSD",
        direction=Direction.BUY,
        scenario=Scenario.BUY_S1,
        price=2341.5,
        created_at_utc=now,
        m15_bar_time_utc=datetime(2026, 2, 11, 14, 30, 0, tzinfo=UTC),
        m1_bar_time_utc=datetime(2026, 2, 11, 14, 29, 0, tzinfo=UTC),
        m15_lwma_fast=2338.2,
        m15_lwma_slow=2335.1,
        m15_stoch_k=15.4,
        m15_stoch_d=12.8,
        m1_stoch_k=18.2,
        m1_stoch_d=14.5,
    )


@pytest.fixture
def m1_only_signal() -> Signal:
    """M1-only signal with no M15 confirmation."""
    now = datetime(2026, 2, 11, 14, 30, 5, tzinfo=UTC)
    return Signal(
        id="sig-m1-only",
        symbol="XAUUSD",
        direction=Direction.BUY,
        scenario=Scenario.BUY_M1,
        price=2341.5,
        created_at_utc=now,
        m1_bar_time_utc=datetime(2026, 2, 11, 14, 29, 0, tzinfo=UTC),
        m1_lwma_fast=2338.2,
        m1_lwma_slow=2335.1,
        m1_stoch_k=15.4,
        m1_stoch_d=12.8,
    )
