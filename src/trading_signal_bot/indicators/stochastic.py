from __future__ import annotations

import numpy as np
import pandas as pd

from trading_signal_bot.indicators.lwma import calculate_lwma


def calculate_stochastic(
    close: pd.Series,
    k_period: int = 30,
    d_period: int = 10,
    slowing: int = 10,
) -> tuple[pd.Series, pd.Series]:
    if k_period <= 0 or d_period <= 0 or slowing <= 0:
        raise ValueError("all stochastic periods must be positive")

    close_float = close.astype(float)
    lowest = close_float.rolling(k_period).min()
    highest = close_float.rolling(k_period).max()
    spread = highest - lowest

    raw_k = pd.Series(np.nan, index=close_float.index, dtype=float)
    valid = spread.notna()
    non_zero = valid & (spread != 0)
    flat = valid & (spread == 0)

    raw_k.loc[non_zero] = (
        (close_float.loc[non_zero] - lowest.loc[non_zero]) / spread.loc[non_zero]
    ) * 100.0
    raw_k.loc[flat] = 50.0

    percent_k = calculate_lwma(raw_k, slowing)
    percent_d = calculate_lwma(percent_k, d_period)
    return (percent_k, percent_d)


def stoch_cross(k: pd.Series, d: pd.Series) -> tuple[bool, bool]:
    if len(k) < 2 or len(d) < 2:
        return (False, False)
    prev_k = float(k.iloc[-2])
    curr_k = float(k.iloc[-1])
    prev_d = float(d.iloc[-2])
    curr_d = float(d.iloc[-1])
    if np.isnan([prev_k, curr_k, prev_d, curr_d]).any():
        return (False, False)
    crossed_above = prev_k <= prev_d and curr_k > curr_d
    crossed_below = prev_k >= prev_d and curr_k < curr_d
    return (crossed_above, crossed_below)


def stoch_in_zone(k_value: float, zone: tuple[int, int]) -> bool:
    return zone[0] <= k_value <= zone[1]
