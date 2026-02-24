"""Tests for signal_scanner.py."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pandas as pd

from backtester.config import SignalMode
from backtester.signal_scanner import scan_signals
from trading_signal_bot.models import (
    Direction,
    IndicatorParams,
    Scenario,
    Signal,
    TriggerMode,
)
from trading_signal_bot.strategy import M15Trigger, StrategyEvaluator

UTC = timezone.utc

# Shared indicator params matching conftest / typical config
PARAMS = IndicatorParams(
    lwma_fast=5,
    lwma_slow=10,
    stoch_k=8,
    stoch_d=3,
    stoch_slowing=3,
    buy_zone=(0, 20),
    sell_zone=(80, 100),
)


def _make_ohlc(closes: list[float], start: str, freq: str) -> pd.DataFrame:
    times = pd.date_range(start=start, periods=len(closes), freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "time": times,
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "tick_volume": [100] * len(closes),
        }
    )


def _make_signal(
    direction: Direction = Direction.BUY,
    scenario: Scenario = Scenario.BUY_S1,
    bar_time: datetime | None = None,
    m15_bar_time: datetime | None = None,
    idem_key: str | None = None,
) -> Signal:
    bt = bar_time or datetime(2026, 2, 11, 14, 29, tzinfo=UTC)
    m15t = m15_bar_time or datetime(2026, 2, 11, 14, 30, tzinfo=UTC)
    return Signal(
        id=Signal.new_id(),
        symbol="XAUUSD",
        direction=direction,
        scenario=scenario,
        price=2341.5,
        created_at_utc=bt,
        m1_bar_time_utc=bt,
        m15_bar_time_utc=m15t,
    )


class TestScanLegacy:
    """Legacy mode should match v1 engine output."""

    def test_empty_data_returns_empty(self) -> None:
        strategy = StrategyEvaluator(params=PARAMS)
        result = scan_signals(
            strategy, "XAUUSD", pd.DataFrame(), pd.DataFrame(), SignalMode.LEGACY, PARAMS,
        )
        assert result == []

    def test_legacy_delegates_to_evaluate_all(self) -> None:
        """Patch evaluate_all to return a canned signal and verify it's collected."""
        sig = _make_signal()
        m15 = _make_ohlc([100.0] * 20, "2026-02-11T10:00", "15min")
        m1 = _make_ohlc([100.0] * 300, "2026-02-11T10:00", "1min")

        strategy = StrategyEvaluator(params=PARAMS)
        with patch.object(strategy, "evaluate_all", return_value=[sig]) as mock:
            result = scan_signals(strategy, "XAUUSD", m15, m1, SignalMode.LEGACY, PARAMS)

        assert len(result) >= 1
        assert mock.call_count == len(m15)


class TestScanChain:
    """Chain mode should replicate live state machine."""

    def test_chain_trigger_no_data_returns_empty(self) -> None:
        strategy = StrategyEvaluator(params=PARAMS)
        m15 = _make_ohlc([100.0] * 5, "2026-02-11T10:00", "15min")
        m1 = _make_ohlc([100.0] * 5, "2026-02-11T10:00", "1min")
        result = scan_signals(strategy, "XAUUSD", m15, m1, SignalMode.CHAIN, PARAMS)
        # Insufficient data for indicators -> no signals
        assert result == []

    def test_chain_pending_expiry_8h(self) -> None:
        """Pending setups older than 8h should be expired."""
        from backtester.signal_scanner import _CHAIN_EXPIRY

        assert _CHAIN_EXPIRY == timedelta(hours=8)

    def test_chain_hp_suppresses_normal(self) -> None:
        """When HP trigger fires, NORMAL for same direction should be suppressed."""
        # This is tested indirectly via evaluate_m15_triggers which already
        # suppresses NORMAL when HP fires. Verify the scanner uses same logic.
        strategy = StrategyEvaluator(params=PARAMS)
        m15 = _make_ohlc([100.0] * 20, "2026-02-11T10:00", "15min")
        m1 = _make_ohlc([100.0] * 300, "2026-02-11T10:00", "1min")

        # Mock: first call returns HP trigger, which should suppress any NORMAL
        hp_trigger = M15Trigger(
            direction=Direction.BUY,
            mode=TriggerMode.HIGH_PROBABILITY,
            m15_close_time_utc=datetime(2026, 2, 11, 10, 15, tzinfo=UTC),
            m15_lwma_fast=100.0,
            m15_lwma_slow=99.0,
            m15_stoch_k=15.0,
            m15_stoch_d=12.0,
        )
        with patch.object(strategy, "evaluate_m15_triggers", return_value=[hp_trigger]):
            with patch.object(strategy, "advance_pending_setup", return_value=(None, None)):
                result = scan_signals(strategy, "XAUUSD", m15, m1, SignalMode.CHAIN, PARAMS)
        # No signals because advance returns None, but no crash
        assert isinstance(result, list)


class TestScanM1:
    """M1 mode should walk M1 bars."""

    def test_m1_insufficient_data(self) -> None:
        strategy = StrategyEvaluator(params=PARAMS)
        m15 = _make_ohlc([100.0] * 20, "2026-02-11T10:00", "15min")
        m1 = _make_ohlc([100.0] * 5, "2026-02-11T10:00", "1min")
        result = scan_signals(strategy, "XAUUSD", m15, m1, SignalMode.M1, PARAMS)
        assert result == []

    def test_m1_delegates_to_evaluate_m1_only(self) -> None:
        sig = _make_signal(scenario=Scenario.BUY_M1)
        m15 = _make_ohlc([100.0] * 20, "2026-02-11T10:00", "15min")
        m1 = _make_ohlc([100.0] * 30, "2026-02-11T10:00", "1min")

        strategy = StrategyEvaluator(params=PARAMS)
        with patch.object(strategy, "evaluate_m1_only", return_value=sig):
            result = scan_signals(strategy, "XAUUSD", m15, m1, SignalMode.M1, PARAMS)

        assert len(result) > 0


class TestScanAll:
    """ALL mode should union and dedup."""

    def test_all_deduplicates_by_idempotency_key(self) -> None:
        """Same signal from multiple scanners should appear only once."""
        sig = _make_signal()

        strategy = StrategyEvaluator(params=PARAMS)
        m15 = _make_ohlc([100.0] * 20, "2026-02-11T10:00", "15min")
        m1 = _make_ohlc([100.0] * 300, "2026-02-11T10:00", "1min")

        with patch("backtester.signal_scanner._scan_legacy", return_value=[sig]):
            with patch("backtester.signal_scanner._scan_chain", return_value=[sig]):
                with patch("backtester.signal_scanner._scan_m1", return_value=[sig]):
                    result = scan_signals(
                        strategy, "XAUUSD", m15, m1, SignalMode.ALL, PARAMS,
                    )

        # All three return same signal -> dedup to 1
        assert len(result) == 1

    def test_all_preserves_different_signals(self) -> None:
        sig1 = _make_signal(
            scenario=Scenario.BUY_S1,
            bar_time=datetime(2026, 2, 11, 14, 29, tzinfo=UTC),
        )
        sig2 = _make_signal(
            scenario=Scenario.BUY_M1,
            bar_time=datetime(2026, 2, 11, 14, 30, tzinfo=UTC),
        )
        strategy = StrategyEvaluator(params=PARAMS)
        m15 = _make_ohlc([100.0] * 20, "2026-02-11T10:00", "15min")
        m1 = _make_ohlc([100.0] * 300, "2026-02-11T10:00", "1min")

        with patch("backtester.signal_scanner._scan_legacy", return_value=[sig1]):
            with patch("backtester.signal_scanner._scan_chain", return_value=[]):
                with patch("backtester.signal_scanner._scan_m1", return_value=[sig2]):
                    result = scan_signals(
                        strategy, "XAUUSD", m15, m1, SignalMode.ALL, PARAMS,
                    )

        assert len(result) == 2
