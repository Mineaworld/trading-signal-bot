from __future__ import annotations

import math

import pandas as pd

from trading_signal_bot.indicators.lwma import calculate_lwma, lwma_cross, lwma_order


def test_calculate_lwma_known_values_period_3() -> None:
    series = pd.Series([1, 2, 3, 4, 5], dtype=float)
    result = calculate_lwma(series, period=3)
    assert math.isnan(float(result.iloc[0]))
    assert math.isnan(float(result.iloc[1]))
    assert result.iloc[2] == 14 / 6
    assert result.iloc[3] == 20 / 6
    assert result.iloc[4] == 26 / 6


def test_calculate_lwma_constant_series() -> None:
    series = pd.Series([100.0] * 10)
    result = calculate_lwma(series, period=3)
    assert all((value == 100.0) or math.isnan(float(value)) for value in result)


def test_lwma_cross_above() -> None:
    fast = pd.Series([1.0, 2.0])
    slow = pd.Series([1.5, 1.8])
    above, below = lwma_cross(fast, slow)
    assert above is True
    assert below is False


def test_lwma_cross_below() -> None:
    fast = pd.Series([2.0, 1.0])
    slow = pd.Series([1.8, 1.2])
    above, below = lwma_cross(fast, slow)
    assert above is False
    assert below is True


def test_lwma_order_variants() -> None:
    assert lwma_order(pd.Series([2.0]), pd.Series([1.0])) == "bullish"
    assert lwma_order(pd.Series([1.0]), pd.Series([2.0])) == "bearish"
    assert lwma_order(pd.Series([1.0]), pd.Series([1.0])) == "neutral"
