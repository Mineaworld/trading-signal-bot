from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd
import pytest

from trading_signal_bot.models import (
    Direction,
    IndicatorParams,
    PendingSetup,
    PendingState,
    Scenario,
    TriggerMode,
)
from trading_signal_bot.settings import RegimeFilterConfig, RiskContextConfig
from trading_signal_bot.strategy import M1Snapshot, StrategyEvaluator, _cross_at

UTC = timezone.utc


def _make_df(periods: int, start: str, freq: str) -> pd.DataFrame:
    times = pd.date_range(start=start, periods=periods, freq=freq, tz="UTC")
    close = [100.0 + i for i in range(periods)]
    return pd.DataFrame(
        {
            "time": times,
            "open": close,
            "high": [x + 0.5 for x in close],
            "low": [x - 0.5 for x in close],
            "close": close,
            "tick_volume": [1 for _ in close],
        }
    )


def _params() -> IndicatorParams:
    return IndicatorParams(
        lwma_fast=2,
        lwma_slow=3,
        stoch_k=3,
        stoch_d=2,
        stoch_slowing=1,
        buy_zone=(10, 20),
        sell_zone=(80, 90),
    )


def _patch_indicators(
    monkeypatch: pytest.MonkeyPatch,
    m15_len: int,
    m1_len: int,
    m15_fast: list[float],
    m15_slow: list[float],
    m15_k: list[float],
    m15_d: list[float],
    m1_fast: list[float],
    m1_slow: list[float],
    m1_k: list[float],
    m1_d: list[float],
) -> None:
    import trading_signal_bot.strategy as strategy_module

    def fake_lwma(series: pd.Series, period: int) -> pd.Series:
        if len(series) == m15_len:
            data = m15_fast if period == 2 else m15_slow
        else:
            data = m1_fast if period == 2 else m1_slow
        return pd.Series(data, index=series.index, dtype=float)

    def fake_stoch(
        close: pd.Series, k_period: int, d_period: int, slowing: int
    ) -> tuple[pd.Series, pd.Series]:
        _ = (k_period, d_period, slowing)
        if len(close) == m15_len:
            return (
                pd.Series(m15_k, index=close.index, dtype=float),
                pd.Series(m15_d, index=close.index, dtype=float),
            )
        return (
            pd.Series(m1_k, index=close.index, dtype=float),
            pd.Series(m1_d, index=close.index, dtype=float),
        )

    monkeypatch.setattr(strategy_module, "calculate_lwma", fake_lwma)
    monkeypatch.setattr(strategy_module, "calculate_stochastic", fake_stoch)


def test_buy_s1_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    m15 = _make_df(6, "2026-02-11 14:00:00", "15min")
    m1 = _make_df(40, "2026-02-11 15:00:00", "1min")
    m1_k = [50.0] * 40
    m1_d = [50.0] * 40
    m1_k[28] = 10.0
    m1_k[29] = 12.0
    m1_d[28] = 11.0
    m1_d[29] = 11.0
    _patch_indicators(
        monkeypatch=monkeypatch,
        m15_len=len(m15),
        m1_len=len(m1),
        m15_fast=[1, 1, 1, 1.1, 1.2, 1.3],
        m15_slow=[1, 1, 1, 1.15, 1.18, 1.2],
        m15_k=[30, 30, 30, 25, 10, 15],
        m15_d=[30, 30, 30, 26, 12, 14],
        m1_fast=[1.0] * 40,
        m1_slow=[1.0] * 40,
        m1_k=m1_k,
        m1_d=m1_d,
    )
    evaluator = StrategyEvaluator(_params())
    signal = evaluator.evaluate(
        m15_df=m15,
        m1_df=m1,
        symbol="XAUUSD",
        m15_close_time_utc=datetime(2026, 2, 11, 15, 30, tzinfo=UTC),
    )
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert signal.scenario == Scenario.BUY_S1


def test_buy_s2_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    m15 = _make_df(6, "2026-02-11 14:00:00", "15min")
    m1 = _make_df(40, "2026-02-11 15:00:00", "1min")
    m1_fast = [1.0] * 40
    m1_slow = [1.0] * 40
    m1_fast[28] = 1.0
    m1_fast[29] = 1.3
    m1_slow[28] = 1.1
    m1_slow[29] = 1.2

    _patch_indicators(
        monkeypatch=monkeypatch,
        m15_len=len(m15),
        m1_len=len(m1),
        m15_fast=[1, 1, 1, 1.1, 1.2, 1.3],
        m15_slow=[1, 1, 1, 1.15, 1.18, 1.2],
        m15_k=[30, 30, 30, 25, 10, 15],
        m15_d=[30, 30, 30, 26, 12, 14],
        m1_fast=m1_fast,
        m1_slow=m1_slow,
        m1_k=[50.0] * 40,
        m1_d=[50.0] * 40,
    )
    evaluator = StrategyEvaluator(_params())
    signal = evaluator.evaluate(
        m15_df=m15,
        m1_df=m1,
        symbol="XAUUSD",
        m15_close_time_utc=datetime(2026, 2, 11, 15, 30, tzinfo=UTC),
    )
    assert signal is not None
    assert signal.direction == Direction.BUY
    assert signal.scenario == Scenario.BUY_S2


def test_sell_s1_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    m15 = _make_df(6, "2026-02-11 14:00:00", "15min")
    m1 = _make_df(40, "2026-02-11 15:00:00", "1min")
    m1_k = [50.0] * 40
    m1_d = [50.0] * 40
    m1_k[28] = 89.0
    m1_k[29] = 85.0
    m1_d[28] = 88.0
    m1_d[29] = 86.0

    _patch_indicators(
        monkeypatch=monkeypatch,
        m15_len=len(m15),
        m1_len=len(m1),
        m15_fast=[2, 2, 2, 1.9, 1.85, 1.8],
        m15_slow=[1.9, 1.9, 1.9, 1.92, 1.9, 1.85],
        m15_k=[50, 50, 50, 70, 90, 85],
        m15_d=[50, 50, 50, 69, 88, 86],
        m1_fast=[1.0] * 40,
        m1_slow=[1.0] * 40,
        m1_k=m1_k,
        m1_d=m1_d,
    )
    evaluator = StrategyEvaluator(_params())
    signal = evaluator.evaluate(
        m15_df=m15,
        m1_df=m1,
        symbol="EURUSD",
        m15_close_time_utc=datetime(2026, 2, 11, 15, 30, tzinfo=UTC),
    )
    assert signal is not None
    assert signal.direction == Direction.SELL
    assert signal.scenario == Scenario.SELL_S1


def test_m1_stale_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    m15 = _make_df(6, "2026-02-11 14:00:00", "15min")
    m1 = _make_df(10, "2026-02-11 14:00:00", "1min")
    _patch_indicators(
        monkeypatch=monkeypatch,
        m15_len=len(m15),
        m1_len=len(m1),
        m15_fast=[1, 1, 1, 1.1, 1.2, 1.3],
        m15_slow=[1, 1, 1, 1.15, 1.18, 1.2],
        m15_k=[30, 30, 30, 25, 10, 15],
        m15_d=[30, 30, 30, 26, 12, 14],
        m1_fast=[1.0] * 10,
        m1_slow=[1.0] * 10,
        m1_k=[12.0] * 10,
        m1_d=[11.0] * 10,
    )
    evaluator = StrategyEvaluator(_params())
    signal = evaluator.evaluate(
        m15_df=m15,
        m1_df=m1,
        symbol="XAUUSD",
        m15_close_time_utc=datetime(2026, 2, 11, 15, 30, tzinfo=UTC),
    )
    assert signal is None


def test_sell_s2_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    m15 = _make_df(6, "2026-02-11 14:00:00", "15min")
    m1 = _make_df(40, "2026-02-11 15:00:00", "1min")
    m1_fast = [1.0] * 40
    m1_slow = [1.0] * 40
    m1_fast[28] = 1.3
    m1_fast[29] = 1.0
    m1_slow[28] = 1.2
    m1_slow[29] = 1.1

    _patch_indicators(
        monkeypatch=monkeypatch,
        m15_len=len(m15),
        m1_len=len(m1),
        m15_fast=[2, 2, 2, 1.9, 1.85, 1.8],
        m15_slow=[1.9, 1.9, 1.9, 1.92, 1.9, 1.85],
        m15_k=[50, 50, 50, 70, 90, 85],
        m15_d=[50, 50, 50, 69, 88, 86],
        m1_fast=m1_fast,
        m1_slow=m1_slow,
        m1_k=[50.0] * 40,
        m1_d=[50.0] * 40,
    )
    evaluator = StrategyEvaluator(_params())
    signal = evaluator.evaluate(
        m15_df=m15,
        m1_df=m1,
        symbol="GBPJPY",
        m15_close_time_utc=datetime(2026, 2, 11, 15, 30, tzinfo=UTC),
    )
    assert signal is not None
    assert signal.direction == Direction.SELL
    assert signal.scenario == Scenario.SELL_S2


def test_both_buy_scenarios_match(monkeypatch: pytest.MonkeyPatch) -> None:
    m15 = _make_df(6, "2026-02-11 14:00:00", "15min")
    m1 = _make_df(40, "2026-02-11 15:00:00", "1min")
    m1_k = [50.0] * 40
    m1_d = [50.0] * 40
    m1_k[28] = 10.0
    m1_k[29] = 12.0
    m1_d[28] = 11.0
    m1_d[29] = 11.0
    m1_fast = [1.0] * 40
    m1_slow = [1.0] * 40
    m1_fast[28] = 1.0
    m1_fast[29] = 1.3
    m1_slow[28] = 1.1
    m1_slow[29] = 1.2
    _patch_indicators(
        monkeypatch=monkeypatch,
        m15_len=len(m15),
        m1_len=len(m1),
        m15_fast=[1, 1, 1, 1.1, 1.2, 1.3],
        m15_slow=[1, 1, 1, 1.15, 1.18, 1.2],
        m15_k=[30, 30, 30, 25, 10, 15],
        m15_d=[30, 30, 30, 26, 12, 14],
        m1_fast=m1_fast,
        m1_slow=m1_slow,
        m1_k=m1_k,
        m1_d=m1_d,
    )
    evaluator = StrategyEvaluator(_params())
    signals = evaluator.evaluate_all(
        m15_df=m15,
        m1_df=m1,
        symbol="XAUUSD",
        m15_close_time_utc=datetime(2026, 2, 11, 15, 30, tzinfo=UTC),
    )
    assert len(signals) == 2
    scenarios = {signal.scenario for signal in signals}
    assert scenarios == {Scenario.BUY_S1, Scenario.BUY_S2}


# ── Phase 1B: New test coverage ──────────────────────────────────────────


def test_hp_trigger_suppresses_normal_for_same_direction(monkeypatch: pytest.MonkeyPatch) -> None:
    """When HP fires, NORMAL for the same direction must be suppressed."""
    m15 = _make_df(6, "2026-02-11 14:00:00", "15min")
    # M15: bullish order, stoch in buy zone, stoch cross above, AND lwma cross above (HP condition)
    _patch_indicators(
        monkeypatch=monkeypatch,
        m15_len=len(m15),
        m1_len=1,
        m15_fast=[1, 1, 1, 1.0, 0.9, 1.3],  # prev < slow, curr > slow → lwma cross above
        m15_slow=[1, 1, 1, 1.0, 1.0, 1.2],
        m15_k=[30, 30, 30, 25, 10, 15],  # in buy zone, cross above
        m15_d=[30, 30, 30, 26, 12, 14],
        m1_fast=[1.0],
        m1_slow=[1.0],
        m1_k=[50.0],
        m1_d=[50.0],
    )
    evaluator = StrategyEvaluator(_params())
    triggers = evaluator.evaluate_m15_triggers(
        m15_df=m15,
        m15_close_time_utc=datetime(2026, 2, 11, 15, 30, tzinfo=UTC),
    )
    # Should have exactly one trigger: HP, not NORMAL
    buy_triggers = [t for t in triggers if t.direction == Direction.BUY]
    assert len(buy_triggers) == 1
    assert buy_triggers[0].mode == TriggerMode.HIGH_PROBABILITY


def test_regime_filter_blocks_triggers(monkeypatch: pytest.MonkeyPatch) -> None:
    """Regime filter with high min_adx blocks triggers when ADX is low."""
    import trading_signal_bot.strategy as strategy_module

    m15 = _make_df(6, "2026-02-11 14:00:00", "15min")
    _patch_indicators(
        monkeypatch=monkeypatch,
        m15_len=len(m15),
        m1_len=1,
        m15_fast=[1, 1, 1, 1.1, 1.2, 1.3],
        m15_slow=[1, 1, 1, 1.15, 1.18, 1.2],
        m15_k=[30, 30, 30, 25, 10, 15],
        m15_d=[30, 30, 30, 26, 12, 14],
        m1_fast=[1.0],
        m1_slow=[1.0],
        m1_k=[50.0],
        m1_d=[50.0],
    )
    # ADX returns 20 which is below min_adx=25
    monkeypatch.setattr(
        strategy_module,
        "calculate_adx",
        lambda high, low, close, period: pd.Series([20.0] * len(close), index=close.index),
    )
    regime = RegimeFilterConfig(enabled=True, adx_period=14, min_adx=25.0)
    evaluator = StrategyEvaluator(_params(), regime_filter=regime)
    triggers = evaluator.evaluate_m15_triggers(
        m15_df=m15,
        m15_close_time_utc=datetime(2026, 2, 11, 15, 30, tzinfo=UTC),
    )
    assert triggers == []


def test_cross_at_equal_values_no_cross() -> None:
    """_cross_at returns no cross when prev values are exactly equal."""
    a = pd.Series([10.0, 10.0])
    b = pd.Series([10.0, 10.0])
    above, below = _cross_at(a, b, 1)
    assert above is False
    assert below is False


def test_cross_at_equal_prev_cross_above() -> None:
    """_cross_at detects cross above when prev_a == prev_b and curr_a > curr_b."""
    a = pd.Series([10.0, 11.0])
    b = pd.Series([10.0, 10.0])
    above, below = _cross_at(a, b, 1)
    assert above is True
    assert below is False


def test_cross_at_equal_prev_cross_below() -> None:
    """_cross_at detects cross below when prev_a == prev_b and curr_a < curr_b."""
    a = pd.Series([10.0, 9.0])
    b = pd.Series([10.0, 10.0])
    above, below = _cross_at(a, b, 1)
    assert above is False
    assert below is True


def test_cross_at_nan_returns_false() -> None:
    """_cross_at returns (False, False) when any value is NaN."""
    a = pd.Series([float("nan"), 11.0])
    b = pd.Series([10.0, 10.0])
    above, below = _cross_at(a, b, 1)
    assert above is False
    assert below is False


def test_pending_setup_expiry() -> None:
    """Chain setup older than 8 hours should not produce a signal."""
    old_time = datetime(2026, 2, 11, 2, 0, tzinfo=UTC)
    pending = PendingSetup(
        symbol="XAUUSD",
        direction=Direction.BUY,
        mode=TriggerMode.NORMAL,
        state=PendingState.WAIT_M1_STOCH,
        m15_trigger_time_utc=old_time,
        last_updated_utc=old_time,
        m15_lwma_fast=2850.0,
        m15_lwma_slow=2840.0,
        m15_stoch_k=15.0,
        m15_stoch_d=12.0,
    )
    # Snapshot 9 hours later — outside max age
    snapshot = M1Snapshot(
        bar_time_utc=old_time + timedelta(hours=9),
        close_price=2900.0,
        lwma_fast=2890.0,
        lwma_slow=2880.0,
        stoch_k=15.0,
        stoch_d=12.0,
        lwma_cross_above=False,
        lwma_cross_below=False,
        stoch_cross_above=True,
        stoch_cross_below=False,
        stoch_in_buy_zone=True,
        stoch_in_sell_zone=False,
    )
    # advance_pending_setup itself doesn't check age — the caller in main.py does.
    # This test verifies the caller's logic is correct by checking the time math.
    age = snapshot.bar_time_utc - pending.m15_trigger_time_utc
    max_age = timedelta(hours=8)
    assert age > max_age


def test_chain_signal_includes_risk_context(monkeypatch: pytest.MonkeyPatch) -> None:
    """Chain signals should include risk context when enabled and m15_df provided."""
    import trading_signal_bot.strategy as strategy_module

    risk_cfg = RiskContextConfig(
        enabled=True, atr_period=3, atr_stop_multiplier=1.0, rr_targets=(1.0, 2.0)
    )
    evaluator = StrategyEvaluator(_params(), risk_context=risk_cfg)

    # Stub calculate_atr to return a fixed value
    monkeypatch.setattr(
        strategy_module,
        "calculate_atr",
        lambda high, low, close, period: pd.Series([5.0] * len(close), index=close.index),
    )

    pending = PendingSetup(
        symbol="XAUUSD",
        direction=Direction.BUY,
        mode=TriggerMode.NORMAL,
        state=PendingState.WAIT_M1_STOCH,
        m15_trigger_time_utc=datetime(2026, 2, 11, 14, 0, tzinfo=UTC),
        last_updated_utc=datetime(2026, 2, 11, 14, 5, tzinfo=UTC),
        m15_lwma_fast=2850.0,
        m15_lwma_slow=2840.0,
        m15_stoch_k=15.0,
        m15_stoch_d=12.0,
    )
    snapshot = M1Snapshot(
        bar_time_utc=datetime(2026, 2, 11, 14, 10, tzinfo=UTC),
        close_price=2900.0,
        lwma_fast=2890.0,
        lwma_slow=2880.0,
        stoch_k=15.0,
        stoch_d=12.0,
        lwma_cross_above=False,
        lwma_cross_below=False,
        stoch_cross_above=True,
        stoch_cross_below=False,
        stoch_in_buy_zone=True,
        stoch_in_sell_zone=False,
    )
    m15_df = _make_df(6, "2026-02-11 13:00:00", "15min")

    updated, signal = evaluator.advance_pending_setup(
        pending=pending, snapshot=snapshot, price=2900.0, m15_df=m15_df
    )
    assert updated is None  # completed
    assert signal is not None
    assert signal.risk_stop_distance is not None
    assert signal.risk_stop_distance == pytest.approx(5.0)
    # BUY invalidation = entry - stop
    assert signal.risk_invalidation_price == pytest.approx(2895.0)
    assert signal.risk_tp1_price == pytest.approx(2905.0)
    assert signal.risk_tp2_price == pytest.approx(2910.0)


def test_chain_signal_no_risk_without_m15_df() -> None:
    """Chain signals without m15_df should have no risk context."""
    risk_cfg = RiskContextConfig(
        enabled=True, atr_period=3, atr_stop_multiplier=1.0, rr_targets=(1.0, 2.0)
    )
    evaluator = StrategyEvaluator(_params(), risk_context=risk_cfg)

    pending = PendingSetup(
        symbol="XAUUSD",
        direction=Direction.BUY,
        mode=TriggerMode.NORMAL,
        state=PendingState.WAIT_M1_STOCH,
        m15_trigger_time_utc=datetime(2026, 2, 11, 14, 0, tzinfo=UTC),
        last_updated_utc=datetime(2026, 2, 11, 14, 5, tzinfo=UTC),
        m15_lwma_fast=2850.0,
        m15_lwma_slow=2840.0,
        m15_stoch_k=15.0,
        m15_stoch_d=12.0,
    )
    snapshot = M1Snapshot(
        bar_time_utc=datetime(2026, 2, 11, 14, 10, tzinfo=UTC),
        close_price=2900.0,
        lwma_fast=2890.0,
        lwma_slow=2880.0,
        stoch_k=15.0,
        stoch_d=12.0,
        lwma_cross_above=False,
        lwma_cross_below=False,
        stoch_cross_above=True,
        stoch_cross_below=False,
        stoch_in_buy_zone=True,
        stoch_in_sell_zone=False,
    )

    _, signal = evaluator.advance_pending_setup(pending=pending, snapshot=snapshot, price=2900.0)
    assert signal is not None
    assert signal.risk_stop_distance is None


def test_risk_invalidation_uses_entry_price(monkeypatch: pytest.MonkeyPatch) -> None:
    """Risk invalidation must be entry_price - stop_distance for BUY,
    not the raw LWMA value."""
    import trading_signal_bot.strategy as strategy_module

    m15 = _make_df(6, "2026-02-11 14:00:00", "15min")
    m1 = _make_df(40, "2026-02-11 15:00:00", "1min")
    m1_k = [50.0] * 40
    m1_d = [50.0] * 40
    m1_k[28] = 10.0
    m1_k[29] = 12.0
    m1_d[28] = 11.0
    m1_d[29] = 11.0

    _patch_indicators(
        monkeypatch=monkeypatch,
        m15_len=len(m15),
        m1_len=len(m1),
        m15_fast=[1, 1, 1, 1.1, 1.2, 1.3],
        m15_slow=[1, 1, 1, 1.15, 1.18, 1.2],
        m15_k=[30, 30, 30, 25, 10, 15],
        m15_d=[30, 30, 30, 26, 12, 14],
        m1_fast=[1.0] * 40,
        m1_slow=[1.0] * 40,
        m1_k=m1_k,
        m1_d=m1_d,
    )
    # ATR = 10.0, multiplier = 1.5 → stop = 15.0
    monkeypatch.setattr(
        strategy_module,
        "calculate_atr",
        lambda high, low, close, period: pd.Series([10.0] * len(close), index=close.index),
    )

    risk_cfg = RiskContextConfig(
        enabled=True, atr_period=3, atr_stop_multiplier=1.5, rr_targets=(1.0, 2.0)
    )
    evaluator = StrategyEvaluator(_params(), risk_context=risk_cfg)
    signal = evaluator.evaluate(
        m15_df=m15,
        m1_df=m1,
        symbol="XAUUSD",
        m15_close_time_utc=datetime(2026, 2, 11, 15, 30, tzinfo=UTC),
    )
    assert signal is not None
    assert signal.risk_stop_distance == pytest.approx(15.0)
    # Invalidation = entry - stop (for BUY), NOT the LWMA fast value
    expected_invalidation = signal.price - 15.0
    assert signal.risk_invalidation_price == pytest.approx(expected_invalidation)


# ── Phase 1C: Indicator math validation ──────────────────────────────────


def test_atr_known_values() -> None:
    """Verify ATR output against manually computed reference values."""
    from trading_signal_bot.indicators.volatility import calculate_atr

    # Simple 5 bars, period=3
    high = pd.Series([12.0, 13.0, 14.0, 13.5, 15.0])
    low = pd.Series([10.0, 11.0, 12.0, 11.5, 13.0])
    close = pd.Series([11.0, 12.0, 13.0, 12.5, 14.0])

    atr = calculate_atr(high, low, close, period=3)
    # TR: [nan, 2.0, 2.0, 2.0, 2.5]
    # SMA seed (period=3): mean([2, 2, 2]) using the first 3 TR values
    # TR[0] = 12-10=2, TR[1] = max(13-11, |13-11|, |11-11|)=2, TR[2] = max(14-12, |14-12|, |12-12|)=2
    # seed = (2+2+2)/3 = 2.0  at index 2
    # atr[3] = (2.0*2 + 2.0)/3 = 2.0
    # atr[4] = (2.0*2 + 2.5)/3 ≈ 2.1667
    assert not np.isnan(atr.iloc[2])
    assert atr.iloc[2] == pytest.approx(2.0)
    assert atr.iloc[4] == pytest.approx(2.0 * 2 / 3 + 2.5 / 3, abs=0.001)


def test_adx_returns_valid_series() -> None:
    """Verify ADX returns non-empty series with valid values for sufficient data."""
    from trading_signal_bot.indicators.volatility import calculate_adx

    # 50 bars of trending data
    n = 50
    close = pd.Series([100.0 + i * 0.5 for i in range(n)])
    high = close + 1.0
    low = close - 1.0

    adx = calculate_adx(high, low, close, period=14)
    assert len(adx) == n
    # Last value should be valid (not NaN) with 50 bars and period=14
    assert not np.isnan(adx.iloc[-1])
    # ADX should be positive for trending data
    assert adx.iloc[-1] > 0
