from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from trading_signal_bot.models import Direction, IndicatorParams, Scenario
from trading_signal_bot.strategy import StrategyEvaluator

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
