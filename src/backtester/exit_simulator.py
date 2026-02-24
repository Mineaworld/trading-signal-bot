"""Exit simulator: simulate trade exits using SL/TP, time, stoch, or combined logic."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pandas as pd

from trading_signal_bot.indicators.volatility import calculate_atr
from trading_signal_bot.models import Direction, IndicatorParams, Signal
from trading_signal_bot.settings import RiskContextConfig

from .config import ExitMode
from .trade_recorder import ExitReason, RecordedTrade, make_trade


def simulate_exit(
    signal: Signal,
    m1_bars: pd.DataFrame,
    m15_bars: pd.DataFrame,
    exit_mode: ExitMode,
    indicator_params: IndicatorParams,
    hold_minutes: int = 240,
    risk_config: RiskContextConfig | None = None,
    sl_mult_override: float | None = None,
    rr1_override: float | None = None,
    rr2_override: float | None = None,
) -> RecordedTrade | None:
    """Simulate the exit for a single signal.

    Returns RecordedTrade always (DATA_END if data exhausted).
    Returns None only for invalid input (e.g. SLTP mode but no risk levels).
    """
    if exit_mode is ExitMode.STOCH:
        raise NotImplementedError("STOCH exit mode available in v2b")
    if exit_mode is ExitMode.COMBINED:
        raise NotImplementedError("COMBINED exit mode available in v2b")

    if exit_mode is ExitMode.TIME:
        return _simulate_time(signal, m1_bars, hold_minutes)

    # SLTP mode
    return _simulate_sltp(
        signal, m1_bars, m15_bars, risk_config,
        sl_mult_override, rr1_override, rr2_override,
    )


def _simulate_time(
    signal: Signal,
    m1_bars: pd.DataFrame,
    hold_minutes: int,
) -> RecordedTrade | None:
    """V1-compatible time-based exit."""
    if m1_bars.empty:
        return None

    m1_sorted = m1_bars.sort_values("time").reset_index(drop=True)
    target_time = signal.m1_bar_time_utc + timedelta(minutes=hold_minutes)
    future_rows = m1_sorted[m1_sorted["time"] >= target_time]

    if future_rows.empty:
        # DATA_END: exit at last bar
        last = m1_sorted.iloc[-1]
        exit_price = float(last["close"])
        exit_time = pd.to_datetime(last["time"], utc=True).to_pydatetime()
        return make_trade(
            signal=signal,
            exit_price=exit_price,
            exit_time_utc=exit_time,
            exit_reason=ExitReason.DATA_END,
        )

    exit_row = future_rows.iloc[0]
    exit_price = float(exit_row["close"])
    exit_time = pd.to_datetime(exit_row["time"], utc=True).to_pydatetime()
    return make_trade(
        signal=signal,
        exit_price=exit_price,
        exit_time_utc=exit_time,
        exit_reason=ExitReason.TIME,
    )


def _simulate_sltp(
    signal: Signal,
    m1_bars: pd.DataFrame,
    m15_bars: pd.DataFrame,
    risk_config: RiskContextConfig | None,
    sl_mult_override: float | None,
    rr1_override: float | None,
    rr2_override: float | None,
) -> RecordedTrade | None:
    """Walk M1 bars after entry, check SL/TP1 (SL checked first for same-bar ambiguity)."""
    sl_price, tp1_price, tp2_price = _resolve_risk_levels(
        signal, m15_bars, risk_config, sl_mult_override, rr1_override, rr2_override,
    )
    if sl_price is None or tp1_price is None:
        return None

    m1_sorted = m1_bars.sort_values("time").reset_index(drop=True)
    # Bars strictly AFTER entry
    future = m1_sorted[m1_sorted["time"] > signal.m1_bar_time_utc].reset_index(drop=True)

    if future.empty:
        return None

    is_buy = signal.direction is Direction.BUY

    for i in range(len(future)):
        bar = future.iloc[i]
        bar_low = float(bar["low"])
        bar_high = float(bar["high"])
        bar_time = pd.to_datetime(bar["time"], utc=True).to_pydatetime()

        if is_buy:
            # SL checked first (conservative)
            if bar_low <= sl_price:
                return make_trade(
                    signal=signal, exit_price=sl_price, exit_time_utc=bar_time,
                    exit_reason=ExitReason.SL, sl_price=sl_price,
                    tp1_price=tp1_price, tp2_price=tp2_price,
                )
            if bar_high >= tp1_price:
                return make_trade(
                    signal=signal, exit_price=tp1_price, exit_time_utc=bar_time,
                    exit_reason=ExitReason.TP1, sl_price=sl_price,
                    tp1_price=tp1_price, tp2_price=tp2_price,
                )
        else:
            # SELL: SL on high, TP on low
            if bar_high >= sl_price:
                return make_trade(
                    signal=signal, exit_price=sl_price, exit_time_utc=bar_time,
                    exit_reason=ExitReason.SL, sl_price=sl_price,
                    tp1_price=tp1_price, tp2_price=tp2_price,
                )
            if bar_low <= tp1_price:
                return make_trade(
                    signal=signal, exit_price=tp1_price, exit_time_utc=bar_time,
                    exit_reason=ExitReason.TP1, sl_price=sl_price,
                    tp1_price=tp1_price, tp2_price=tp2_price,
                )

    # No SL/TP hit — exit at last bar close
    last = future.iloc[-1]
    return make_trade(
        signal=signal,
        exit_price=float(last["close"]),
        exit_time_utc=pd.to_datetime(last["time"], utc=True).to_pydatetime(),
        exit_reason=ExitReason.DATA_END,
        sl_price=sl_price,
        tp1_price=tp1_price,
        tp2_price=tp2_price,
    )


def _resolve_risk_levels(
    signal: Signal,
    m15_bars: pd.DataFrame,
    risk_config: RiskContextConfig | None,
    sl_mult_override: float | None,
    rr1_override: float | None,
    rr2_override: float | None,
) -> tuple[float | None, float | None, float | None]:
    """Resolve SL/TP1/TP2 prices.

    Priority: CLI overrides -> signal built-in levels -> None.
    Returns (sl_price, tp1_price, tp2_price).
    """
    if sl_mult_override is not None or rr1_override is not None or rr2_override is not None:
        # Recompute from ATR at entry time
        return _recompute_from_atr(
            signal, m15_bars, risk_config,
            sl_mult_override, rr1_override, rr2_override,
        )

    # Use signal's built-in levels
    if signal.risk_invalidation_price is not None and signal.risk_tp1_price is not None:
        return (
            signal.risk_invalidation_price,
            signal.risk_tp1_price,
            signal.risk_tp2_price,
        )

    # Try computing from risk_config defaults
    if risk_config is not None and risk_config.enabled:
        return _recompute_from_atr(signal, m15_bars, risk_config, None, None, None)

    return (None, None, None)


def _recompute_from_atr(
    signal: Signal,
    m15_bars: pd.DataFrame,
    risk_config: RiskContextConfig | None,
    sl_mult_override: float | None,
    rr1_override: float | None,
    rr2_override: float | None,
) -> tuple[float | None, float | None, float | None]:
    """Recompute SL/TP from ATR at entry time (no lookahead)."""
    atr_period = risk_config.atr_period if risk_config else 14
    sl_mult = sl_mult_override if sl_mult_override is not None else (
        risk_config.atr_stop_multiplier if risk_config else 1.0
    )
    rr1 = rr1_override if rr1_override is not None else (
        risk_config.rr_targets[0] if risk_config else 2.0
    )
    rr2 = rr2_override if rr2_override is not None else (
        risk_config.rr_targets[1] if risk_config else 3.0
    )

    # Slice M15 bars up to entry time (no lookahead)
    m15_sorted = m15_bars.sort_values("time").reset_index(drop=True)
    m15_before = m15_sorted[m15_sorted["time"] <= signal.m1_bar_time_utc]
    if len(m15_before) < atr_period:
        return (None, None, None)

    atr = calculate_atr(
        high=m15_before["high"].astype(float),
        low=m15_before["low"].astype(float),
        close=m15_before["close"].astype(float),
        period=atr_period,
    )
    if atr.empty:
        return (None, None, None)
    atr_val = float(atr.iloc[-1])
    if np.isnan(atr_val):
        return (None, None, None)

    stop_distance = atr_val * sl_mult
    entry = signal.price

    if signal.direction is Direction.BUY:
        sl_price = entry - stop_distance
        tp1_price = entry + stop_distance * rr1
        tp2_price = entry + stop_distance * rr2
    else:
        sl_price = entry + stop_distance
        tp1_price = entry - stop_distance * rr1
        tp2_price = entry - stop_distance * rr2

    return (sl_price, tp1_price, tp2_price)
