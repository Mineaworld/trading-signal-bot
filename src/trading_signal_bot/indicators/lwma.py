from __future__ import annotations

import numpy as np
import numpy.typing as npt
import pandas as pd


def calculate_lwma(series: pd.Series, period: int) -> pd.Series:
    if period <= 0:
        raise ValueError("period must be positive")
    if len(series) == 0:
        return pd.Series(dtype=float)

    weights = np.arange(1, period + 1, dtype=float)
    denominator = float(weights.sum())

    def weighted(window: npt.NDArray[np.float64]) -> float:
        return float(np.dot(window, weights) / denominator)

    return series.astype(float).rolling(period).apply(weighted, raw=True)


def lwma_cross(fast: pd.Series, slow: pd.Series) -> tuple[bool, bool]:
    if len(fast) < 2 or len(slow) < 2:
        return (False, False)
    prev_fast = float(fast.iloc[-2])
    curr_fast = float(fast.iloc[-1])
    prev_slow = float(slow.iloc[-2])
    curr_slow = float(slow.iloc[-1])

    if np.isnan([prev_fast, curr_fast, prev_slow, curr_slow]).any():
        return (False, False)

    crossed_above = prev_fast <= prev_slow and curr_fast > curr_slow
    crossed_below = prev_fast >= prev_slow and curr_fast < curr_slow
    return (crossed_above, crossed_below)


def lwma_order(fast: pd.Series, slow: pd.Series) -> str:
    if len(fast) == 0 or len(slow) == 0:
        return "neutral"
    curr_fast = float(fast.iloc[-1])
    curr_slow = float(slow.iloc[-1])
    if np.isnan([curr_fast, curr_slow]).any():
        return "neutral"
    if curr_fast > curr_slow:
        return "bullish"
    if curr_fast < curr_slow:
        return "bearish"
    return "neutral"
