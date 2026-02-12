from __future__ import annotations

import pandas as pd

from trading_signal_bot.indicators.stochastic import (
    calculate_stochastic,
    stoch_cross,
    stoch_in_zone,
)


def test_stochastic_flat_market_division_guard() -> None:
    close = pd.Series([100.0] * 50)
    k, d = calculate_stochastic(close, k_period=3, d_period=2, slowing=2)
    assert float(k.dropna().iloc[-1]) == 50.0
    assert float(d.dropna().iloc[-1]) == 50.0


def test_stochastic_zone_boundaries() -> None:
    assert stoch_in_zone(10.0, (10, 20)) is True
    assert stoch_in_zone(20.0, (10, 20)) is True
    assert stoch_in_zone(21.0, (10, 20)) is False
    assert stoch_in_zone(80.0, (80, 90)) is True
    assert stoch_in_zone(90.0, (80, 90)) is True


def test_stochastic_cross() -> None:
    k = pd.Series([10.0, 20.0])
    d = pd.Series([12.0, 15.0])
    above, below = stoch_cross(k, d)
    assert above is True
    assert below is False
