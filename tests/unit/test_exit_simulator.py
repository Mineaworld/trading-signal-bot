"""Tests for exit_simulator.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from trading_signal_bot.models import Direction, IndicatorParams, Scenario, Signal
from trading_signal_bot.settings import RiskContextConfig

from backtester.config import ExitMode
from backtester.exit_simulator import simulate_exit
from backtester.trade_recorder import ExitReason

UTC = timezone.utc

PARAMS = IndicatorParams(
    lwma_fast=5,
    lwma_slow=10,
    stoch_k=8,
    stoch_d=3,
    stoch_slowing=3,
    buy_zone=(0, 20),
    sell_zone=(80, 100),
)

RISK_CONFIG = RiskContextConfig(
    enabled=True,
    atr_period=14,
    atr_stop_multiplier=1.0,
    rr_targets=(2.0, 3.0),
)


def _make_signal(
    direction: Direction = Direction.BUY,
    price: float = 100.0,
    bar_time: datetime | None = None,
    sl: float | None = None,
    tp1: float | None = None,
    tp2: float | None = None,
) -> Signal:
    bt = bar_time or datetime(2026, 2, 11, 14, 0, tzinfo=UTC)
    return Signal(
        id="test-sig",
        symbol="XAUUSD",
        direction=direction,
        scenario=Scenario.BUY_S1 if direction is Direction.BUY else Scenario.SELL_S1,
        price=price,
        created_at_utc=bt,
        m1_bar_time_utc=bt,
        m15_bar_time_utc=bt,
        risk_invalidation_price=sl,
        risk_tp1_price=tp1,
        risk_tp2_price=tp2,
    )


def _make_m1(
    bars: list[tuple[float, float, float, float]],
    start: datetime,
) -> pd.DataFrame:
    """Create M1 OHLC df. Each bar = (open, high, low, close)."""
    times = [start + timedelta(minutes=i) for i in range(len(bars))]
    return pd.DataFrame(
        {
            "time": pd.to_datetime(times, utc=True),
            "open": [b[0] for b in bars],
            "high": [b[1] for b in bars],
            "low": [b[2] for b in bars],
            "close": [b[3] for b in bars],
            "tick_volume": [100] * len(bars),
        }
    )


def _make_m15(count: int = 20, start: str = "2026-02-11T10:00") -> pd.DataFrame:
    """Create enough M15 bars for ATR computation."""
    times = pd.date_range(start=start, periods=count, freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "time": times,
            "open": [100.0] * count,
            "high": [101.0] * count,
            "low": [99.0] * count,
            "close": [100.0] * count,
            "tick_volume": [100] * count,
        }
    )


class TestSLTPBuy:
    """BUY direction SL/TP exit tests."""

    def test_sl_hit_on_low(self) -> None:
        """BUY SL triggers when bar low <= SL price."""
        sig = _make_signal(direction=Direction.BUY, price=100.0, sl=98.0, tp1=104.0, tp2=106.0)
        entry_time = sig.m1_bar_time_utc
        m1 = _make_m1(
            [
                (100, 101, 99.5, 100),   # entry bar (idx 0, at entry_time)
                (100, 100.5, 99, 100.2),  # bar 1: low=99 > 98 -> no hit
                (100, 100.5, 97.5, 99),   # bar 2: low=97.5 <= 98 -> SL hit
            ],
            start=entry_time,
        )
        m15 = _make_m15()
        trade = simulate_exit(sig, m1, m15, ExitMode.SLTP, PARAMS)
        assert trade is not None
        assert trade.exit_reason is ExitReason.SL
        assert trade.exit_price == 98.0

    def test_tp1_hit_on_high(self) -> None:
        """BUY TP1 triggers when bar high >= TP1 price."""
        sig = _make_signal(direction=Direction.BUY, price=100.0, sl=98.0, tp1=104.0)
        entry_time = sig.m1_bar_time_utc
        m1 = _make_m1(
            [
                (100, 101, 99.5, 100),    # entry bar
                (100, 103, 99, 100.2),    # bar 1: high=103 < 104
                (100, 105, 99, 104.5),    # bar 2: high=105 >= 104 -> TP1
            ],
            start=entry_time,
        )
        m15 = _make_m15()
        trade = simulate_exit(sig, m1, m15, ExitMode.SLTP, PARAMS)
        assert trade is not None
        assert trade.exit_reason is ExitReason.TP1
        assert trade.exit_price == 104.0


class TestSLTPSell:
    """SELL direction SL/TP exit tests."""

    def test_sell_sl_hit_on_high(self) -> None:
        """SELL SL triggers when bar high >= SL price."""
        sig = _make_signal(direction=Direction.SELL, price=100.0, sl=102.0, tp1=96.0)
        entry_time = sig.m1_bar_time_utc
        m1 = _make_m1(
            [
                (100, 101, 99, 100),      # entry bar
                (100, 101.5, 99, 100.2),  # bar 1: high=101.5 < 102
                (100, 103, 99, 101),      # bar 2: high=103 >= 102 -> SL
            ],
            start=entry_time,
        )
        m15 = _make_m15()
        trade = simulate_exit(sig, m1, m15, ExitMode.SLTP, PARAMS)
        assert trade is not None
        assert trade.exit_reason is ExitReason.SL
        assert trade.exit_price == 102.0

    def test_sell_tp1_hit_on_low(self) -> None:
        """SELL TP1 triggers when bar low <= TP1 price."""
        sig = _make_signal(direction=Direction.SELL, price=100.0, sl=102.0, tp1=96.0)
        entry_time = sig.m1_bar_time_utc
        m1 = _make_m1(
            [
                (100, 101, 99, 100),      # entry bar
                (100, 101, 97, 98),       # bar 1: low=97 > 96
                (100, 101, 95, 97),       # bar 2: low=95 <= 96 -> TP1
            ],
            start=entry_time,
        )
        m15 = _make_m15()
        trade = simulate_exit(sig, m1, m15, ExitMode.SLTP, PARAMS)
        assert trade is not None
        assert trade.exit_reason is ExitReason.TP1
        assert trade.exit_price == 96.0


class TestSameBarAmbiguity:
    """When both SL and TP hit on same bar, SL wins (conservative)."""

    def test_same_bar_sl_wins(self) -> None:
        sig = _make_signal(direction=Direction.BUY, price=100.0, sl=98.0, tp1=104.0)
        entry_time = sig.m1_bar_time_utc
        m1 = _make_m1(
            [
                (100, 101, 99, 100),      # entry bar
                (100, 105, 97, 100),      # bar 1: low=97<=98 AND high=105>=104 -> SL wins
            ],
            start=entry_time,
        )
        m15 = _make_m15()
        trade = simulate_exit(sig, m1, m15, ExitMode.SLTP, PARAMS)
        assert trade is not None
        assert trade.exit_reason is ExitReason.SL


class TestDataEnd:
    """DATA_END when no SL/TP hit before data runs out."""

    def test_sltp_data_end(self) -> None:
        sig = _make_signal(direction=Direction.BUY, price=100.0, sl=90.0, tp1=120.0)
        entry_time = sig.m1_bar_time_utc
        m1 = _make_m1(
            [
                (100, 101, 99, 100),      # entry bar
                (100, 101, 99, 100.5),    # bar 1: no hit
                (100, 101, 99, 100.3),    # bar 2: no hit
            ],
            start=entry_time,
        )
        m15 = _make_m15()
        trade = simulate_exit(sig, m1, m15, ExitMode.SLTP, PARAMS)
        assert trade is not None
        assert trade.exit_reason is ExitReason.DATA_END
        assert trade.exit_price == 100.3  # last bar close


class TestEntryBarExcluded:
    """Entry bar should NOT be checked for SL/TP."""

    def test_entry_bar_not_checked(self) -> None:
        # SL would trigger on entry bar but should be skipped
        sig = _make_signal(direction=Direction.BUY, price=100.0, sl=99.8, tp1=104.0)
        entry_time = sig.m1_bar_time_utc
        m1 = _make_m1(
            [
                (100, 101, 99, 100),      # entry bar: low=99 < 99.8, but excluded
                (100, 101, 99.9, 100.5),  # bar 1: low=99.9 > 99.8 -> no hit
            ],
            start=entry_time,
        )
        m15 = _make_m15()
        trade = simulate_exit(sig, m1, m15, ExitMode.SLTP, PARAMS)
        assert trade is not None
        # Should be DATA_END, not SL (entry bar excluded)
        assert trade.exit_reason is ExitReason.DATA_END


class TestTimeExit:
    """Time-based exit backward compat."""

    def test_time_exit_basic(self) -> None:
        sig = _make_signal(direction=Direction.BUY, price=100.0)
        entry_time = sig.m1_bar_time_utc
        bars = [(100, 101, 99, 100 + i * 0.1) for i in range(20)]
        m1 = _make_m1(bars, start=entry_time)
        m15 = _make_m15()
        trade = simulate_exit(
            sig, m1, m15, ExitMode.TIME, PARAMS, hold_minutes=15,
        )
        assert trade is not None
        assert trade.exit_reason is ExitReason.TIME

    def test_time_exit_data_end(self) -> None:
        """Time exit when hold_minutes exceeds available data."""
        sig = _make_signal(direction=Direction.BUY, price=100.0)
        entry_time = sig.m1_bar_time_utc
        bars = [(100, 101, 99, 100.5)] * 3
        m1 = _make_m1(bars, start=entry_time)
        m15 = _make_m15()
        trade = simulate_exit(
            sig, m1, m15, ExitMode.TIME, PARAMS, hold_minutes=60,
        )
        assert trade is not None
        assert trade.exit_reason is ExitReason.DATA_END


class TestNoRiskLevels:
    """SLTP mode with no risk levels returns None."""

    def test_none_when_no_levels(self) -> None:
        sig = _make_signal(direction=Direction.BUY, price=100.0)  # no SL/TP set
        entry_time = sig.m1_bar_time_utc
        m1 = _make_m1(
            [(100, 101, 99, 100)] * 5,
            start=entry_time,
        )
        m15 = _make_m15()
        # No risk config, no signal levels, no overrides
        trade = simulate_exit(
            sig, m1, m15, ExitMode.SLTP, PARAMS,
            risk_config=None,
        )
        assert trade is None


class TestNotImplementedModes:
    """STOCH and COMBINED should raise NotImplementedError."""

    def test_stoch_not_implemented(self) -> None:
        sig = _make_signal()
        m1 = _make_m1([(100, 101, 99, 100)] * 5, start=sig.m1_bar_time_utc)
        m15 = _make_m15()
        with pytest.raises(NotImplementedError, match="v2b"):
            simulate_exit(sig, m1, m15, ExitMode.STOCH, PARAMS)

    def test_combined_not_implemented(self) -> None:
        sig = _make_signal()
        m1 = _make_m1([(100, 101, 99, 100)] * 5, start=sig.m1_bar_time_utc)
        m15 = _make_m15()
        with pytest.raises(NotImplementedError, match="v2b"):
            simulate_exit(sig, m1, m15, ExitMode.COMBINED, PARAMS)
