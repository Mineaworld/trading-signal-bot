"""Signal scanner: generates signals from historical data per mode."""

from __future__ import annotations

from datetime import timedelta, timezone

import numpy as np
import pandas as pd

from trading_signal_bot.indicators.lwma import calculate_lwma
from trading_signal_bot.indicators.stochastic import calculate_stochastic, stoch_in_zone
from trading_signal_bot.models import (
    Direction,
    IndicatorParams,
    PendingSetup,
    PendingState,
    Signal,
    TriggerMode,
)
from trading_signal_bot.strategy import M1Snapshot, StrategyEvaluator

from .config import SignalMode

# Key for pending setup dict: (direction, trigger_mode)
_PendingKey = tuple[Direction, TriggerMode]

_CHAIN_EXPIRY = timedelta(hours=8)


def scan_signals(
    strategy: StrategyEvaluator,
    symbol: str,
    m15_df: pd.DataFrame,
    m1_df: pd.DataFrame,
    mode: SignalMode,
    params: IndicatorParams,
) -> list[Signal]:
    """Scan historical data and return signals for the given mode."""
    if m15_df.empty or m1_df.empty:
        return []

    m15_all = m15_df.sort_values("time").reset_index(drop=True)
    m1_all = m1_df.sort_values("time").reset_index(drop=True)

    if mode is SignalMode.LEGACY:
        return _scan_legacy(strategy, symbol, m15_all, m1_all)
    if mode is SignalMode.CHAIN:
        return _scan_chain(strategy, symbol, m15_all, m1_all, params)
    if mode is SignalMode.M1:
        return _scan_m1(strategy, symbol, m1_all, params)
    # ALL mode
    return _scan_all(strategy, symbol, m15_all, m1_all, params)


def _scan_legacy(
    strategy: StrategyEvaluator,
    symbol: str,
    m15_all: pd.DataFrame,
    m1_all: pd.DataFrame,
) -> list[Signal]:
    """Walk M15 bars and call evaluate_all per bar. Same as v1."""
    m15_close_times = pd.to_datetime(m15_all["time"], utc=True) + timedelta(minutes=15)
    signals: list[Signal] = []

    for m15_idx, m15_close in enumerate(m15_close_times.tolist()):
        m15_close_dt = pd.to_datetime(m15_close, utc=True).to_pydatetime()
        m15_slice = m15_all.iloc[: m15_idx + 1].reset_index(drop=True)
        m1_slice = m1_all[m1_all["time"] <= m15_close_dt].reset_index(drop=True)
        if m1_slice.empty:
            continue
        emitted = strategy.evaluate_all(
            m15_df=m15_slice,
            m1_df=m1_slice,
            symbol=symbol,
            m15_close_time_utc=m15_close_dt,
            price=None,
        )
        signals.extend(emitted)

    return signals


def _scan_chain(
    strategy: StrategyEvaluator,
    symbol: str,
    m15_all: pd.DataFrame,
    m1_all: pd.DataFrame,
    params: IndicatorParams,
) -> list[Signal]:
    """Replicate live chain state machine on historical data."""
    signals: list[Signal] = []
    pending: dict[_PendingKey, PendingSetup] = {}

    # Pre-compute M15 close times
    m15_times = pd.to_datetime(m15_all["time"], utc=True)
    m15_close_times = m15_times + timedelta(minutes=15)

    # Pre-compute M1 indicators once over full series
    m1_close = m1_all["close"].astype(float)
    min_bars = max(params.lwma_slow, params.stoch_k) + 2
    if len(m1_all) < min_bars:
        return []

    m1_lwma_fast = calculate_lwma(m1_close, params.lwma_fast)
    m1_lwma_slow = calculate_lwma(m1_close, params.lwma_slow)
    m1_stoch_k, m1_stoch_d = calculate_stochastic(
        close=m1_close,
        k_period=params.stoch_k,
        d_period=params.stoch_d,
        slowing=params.stoch_slowing,
    )
    m1_times = pd.to_datetime(m1_all["time"], utc=True)
    m1_close_times = m1_times + timedelta(minutes=1)

    m15_ptr = 0  # next M15 close to process

    for m1_idx in range(1, len(m1_all)):
        m1_bar_close = m1_close_times.iloc[m1_idx]

        # Check M15 boundaries: is this M1 bar closing at/after the next M15 close?
        while m15_ptr < len(m15_close_times) and m1_bar_close >= m15_close_times.iloc[m15_ptr]:
            m15_close_dt = m15_close_times.iloc[m15_ptr].to_pydatetime()
            m15_slice = m15_all.iloc[: m15_ptr + 1].reset_index(drop=True)

            triggers = strategy.evaluate_m15_triggers(m15_slice, m15_close_dt)
            trigger_directions = {trigger.direction for trigger in triggers}
            if Direction.BUY in trigger_directions:
                pending = {
                    key: value for key, value in pending.items() if value.direction is not Direction.SELL
                }
            if Direction.SELL in trigger_directions:
                pending = {
                    key: value for key, value in pending.items() if value.direction is not Direction.BUY
                }
            for trigger in triggers:
                key: _PendingKey = (trigger.direction, trigger.mode)
                # HP suppresses NORMAL for same direction
                normal_key = (trigger.direction, TriggerMode.NORMAL)
                if trigger.mode is TriggerMode.HIGH_PROBABILITY and normal_key in pending:
                    del pending[normal_key]

                # New trigger replaces existing for same key
                pending[key] = PendingSetup(
                    symbol=symbol,
                    direction=trigger.direction,
                    mode=trigger.mode,
                    state=PendingState.WAIT_M1_LWMA,
                    m15_trigger_time_utc=m15_close_dt,
                    last_updated_utc=m15_close_dt,
                    m15_lwma_fast=trigger.m15_lwma_fast,
                    m15_lwma_slow=trigger.m15_lwma_slow,
                    m15_stoch_k=trigger.m15_stoch_k,
                    m15_stoch_d=trigger.m15_stoch_d,
                )
            m15_ptr += 1

        # Expire stale pending setups
        current_m1_time = m1_bar_close.to_pydatetime()
        expired_keys = [
            k
            for k, p in pending.items()
            if current_m1_time - p.m15_trigger_time_utc > _CHAIN_EXPIRY
        ]
        for k in expired_keys:
            del pending[k]

        # Build M1Snapshot from pre-computed indicators
        snapshot = _build_snapshot_at(
            m1_idx,
            m1_bar_close,
            m1_all,
            m1_lwma_fast,
            m1_lwma_slow,
            m1_stoch_k,
            m1_stoch_d,
            params,
        )
        if snapshot is None:
            continue

        # Advance each pending setup
        completed_keys: list[_PendingKey] = []
        for key, setup in list(pending.items()):
            m15_slice_for_risk = (
                m15_all.iloc[:m15_ptr].reset_index(drop=True) if m15_ptr > 0 else pd.DataFrame()
            )
            updated, signal = strategy.advance_pending_setup(
                setup,
                snapshot,
                price=None,
                m15_df=m15_slice_for_risk,
            )
            if signal is not None:
                signals.append(signal)
                completed_keys.append(key)
            elif updated is not None and updated is not setup:
                pending[key] = updated

        for k in completed_keys:
            pending.pop(k, None)

    return signals


def _build_snapshot_at(
    idx: int,
    bar_close_time: pd.Timestamp,
    m1_all: pd.DataFrame,
    lwma_fast: pd.Series,
    lwma_slow: pd.Series,
    stoch_k: pd.Series,
    stoch_d: pd.Series,
    params: IndicatorParams,
) -> M1Snapshot | None:
    """Build an M1Snapshot from pre-computed indicator arrays at index."""
    if idx < 1:
        return None

    fast_val = float(lwma_fast.iloc[idx])
    slow_val = float(lwma_slow.iloc[idx])
    k_val = float(stoch_k.iloc[idx])
    d_val = float(stoch_d.iloc[idx])
    if np.isnan([fast_val, slow_val, k_val, d_val]).any():
        return None

    prev_fast = float(lwma_fast.iloc[idx - 1])
    prev_slow = float(lwma_slow.iloc[idx - 1])
    prev_k = float(stoch_k.iloc[idx - 1])
    prev_d = float(stoch_d.iloc[idx - 1])
    if np.isnan([prev_fast, prev_slow, prev_k, prev_d]).any():
        return None

    lwma_cross_above = prev_fast <= prev_slow and fast_val > slow_val
    lwma_cross_below = prev_fast >= prev_slow and fast_val < slow_val
    stoch_cross_above = prev_k <= prev_d and k_val > d_val
    stoch_cross_below = prev_k >= prev_d and k_val < d_val

    close_price = float(m1_all.iloc[idx]["close"])
    bar_close_dt = bar_close_time.to_pydatetime().replace(tzinfo=timezone.utc)

    return M1Snapshot(
        bar_time_utc=bar_close_dt,
        close_price=close_price,
        lwma_fast=fast_val,
        lwma_slow=slow_val,
        stoch_k=k_val,
        stoch_d=d_val,
        lwma_cross_above=lwma_cross_above,
        lwma_cross_below=lwma_cross_below,
        stoch_cross_above=stoch_cross_above,
        stoch_cross_below=stoch_cross_below,
        stoch_in_buy_zone=stoch_in_zone(k_val, params.buy_zone),
        stoch_in_sell_zone=stoch_in_zone(k_val, params.sell_zone),
    )


def _scan_m1(
    strategy: StrategyEvaluator,
    symbol: str,
    m1_all: pd.DataFrame,
    params: IndicatorParams,
) -> list[Signal]:
    """Walk M1 bars and call evaluate_m1_only per bar."""
    min_bars = max(params.lwma_slow, params.stoch_k) + 2
    signals: list[Signal] = []

    for i in range(min_bars, len(m1_all) + 1):
        m1_slice = m1_all.iloc[:i].reset_index(drop=True)
        signal = strategy.evaluate_m1_only(m1_slice, symbol, price=None)
        if signal is not None:
            signals.append(signal)

    return signals


def _scan_all(
    strategy: StrategyEvaluator,
    symbol: str,
    m15_all: pd.DataFrame,
    m1_all: pd.DataFrame,
    params: IndicatorParams,
) -> list[Signal]:
    """Union of all three scanners, deduped by idempotency_key."""
    # Run scanners in fixed order
    legacy = _scan_legacy(strategy, symbol, m15_all, m1_all)
    chain = _scan_chain(strategy, symbol, m15_all, m1_all, params)
    m1 = _scan_m1(strategy, symbol, m1_all, params)

    # Collect all, sort by m1_bar_time_utc (stable sort preserves scanner order)
    all_signals = legacy + chain + m1
    all_signals.sort(key=lambda s: s.m1_bar_time_utc)

    # Dedup by idempotency_key, keeping first occurrence
    seen: set[str] = set()
    deduped: list[Signal] = []
    for sig in all_signals:
        key = sig.idempotency_key
        if key not in seen:
            seen.add(key)
            deduped.append(sig)

    return deduped
