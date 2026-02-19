from __future__ import annotations

import numpy as np
import pandas as pd


def _wilders_smoothing(series: pd.Series, period: int) -> pd.Series:
    """Wilder's smoothing (MT5-compatible).

    1. Seed = SMA of the first ``period`` values.
    2. Subsequent = (prev * (period - 1) + current) / period.
    """
    result = pd.Series(np.nan, index=series.index, dtype=float)
    sma_seed = series.iloc[:period].mean()
    if np.isnan(sma_seed):
        return result
    result.iloc[period - 1] = sma_seed
    for i in range(period, len(series)):
        result.iloc[i] = (result.iloc[i - 1] * (period - 1) + series.iloc[i]) / period
    return result


def calculate_atr(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    prev_close = close.shift(1)
    tr_1 = high - low
    tr_2 = (high - prev_close).abs()
    tr_3 = (low - prev_close).abs()
    tr = pd.concat([tr_1, tr_2, tr_3], axis=1).max(axis=1)
    return _wilders_smoothing(tr, period)


def calculate_adx(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    period: int = 14,
) -> pd.Series:
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(
        np.where((up_move > down_move) & (up_move > 0), up_move, 0.0),
        index=high.index,
        dtype=float,
    )
    minus_dm = pd.Series(
        np.where((down_move > up_move) & (down_move > 0), down_move, 0.0),
        index=high.index,
        dtype=float,
    )

    atr = calculate_atr(high=high, low=low, close=close, period=period)
    plus_di = 100.0 * (_wilders_smoothing(plus_dm, period) / atr)
    minus_di = 100.0 * (_wilders_smoothing(minus_dm, period) / atr)

    di_sum = plus_di + minus_di
    dx = 100.0 * (plus_di - minus_di).abs() / di_sum.replace(0, np.nan)
    adx = _wilders_smoothing(dx, period)
    return adx
