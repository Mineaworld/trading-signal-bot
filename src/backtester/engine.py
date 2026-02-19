from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from trading_signal_bot.models import Direction, PendingSetup, PendingState, Signal
from trading_signal_bot.strategy import M1Snapshot, M15Trigger, StrategyEvaluator
from trading_signal_bot.utils import utc_now

from .trade_recorder import RecordedTrade, time_based_outcome


@dataclass(frozen=True)
class BacktestResult:
    signals: list[Signal]
    trades: list[RecordedTrade]


def run_time_based_backtest(
    strategy: StrategyEvaluator,
    symbol: str,
    m15_df: pd.DataFrame,
    m1_df: pd.DataFrame,
    hold_minutes: int = 15,
) -> BacktestResult:
    if m15_df.empty or m1_df.empty:
        return BacktestResult(signals=[], trades=[])

    m15_all = m15_df.sort_values("time").reset_index(drop=True)
    m1_all = m1_df.sort_values("time").reset_index(drop=True)
    m15_close_times = pd.to_datetime(m15_all["time"], utc=True) + timedelta(minutes=15)
    m1_close_times = pd.to_datetime(m1_all["time"], utc=True) + timedelta(minutes=1)

    pending_map: dict[tuple[Direction, str], PendingSetup] = {}
    signals: list[Signal] = []
    m15_idx = 0

    for m1_pos, m1_close in enumerate(m1_close_times.tolist()):
        m1_close_dt = pd.to_datetime(m1_close, utc=True).to_pydatetime()

        # Process every M15 close reached by this M1 bar.
        while (
            m15_idx < len(m15_all) and m15_close_times.iloc[m15_idx].to_pydatetime() <= m1_close_dt
        ):
            m15_slice = m15_all.iloc[: m15_idx + 1].reset_index(drop=True)
            m15_close_dt = m15_close_times.iloc[m15_idx].to_pydatetime()
            m1_slice_at_m15 = m1_all[m1_all["time"] <= m15_close_dt].reset_index(drop=True)

            # Legacy scenarios (S1/S2).
            legacy = strategy.evaluate_all(
                m15_df=m15_slice,
                m1_df=m1_slice_at_m15,
                symbol=symbol,
                m15_close_time_utc=m15_close_dt,
                price=None,
            )
            signals.extend(legacy)

            # Chain trigger registration for runtime parity.
            triggers = strategy.evaluate_m15_triggers(m15_slice, m15_close_dt)
            if triggers:
                pending_map = _register_triggers(
                    symbol=symbol, pending_map=pending_map, triggers=triggers
                )

            m15_idx += 1

        if not pending_map:
            continue

        # Advance pending chain setups by current M1 snapshot.
        m1_slice = m1_all.iloc[: m1_pos + 1].reset_index(drop=True)
        snapshot = strategy.latest_m1_snapshot(m1_slice)
        if snapshot is None:
            continue
        pending_map, emitted = _advance_pending(strategy, pending_map, snapshot)
        signals.extend(emitted)

    trades = _evaluate_trades(signals=signals, m1_all=m1_all, hold_minutes=hold_minutes)
    return BacktestResult(signals=signals, trades=trades)


def _register_triggers(
    symbol: str,
    pending_map: dict[tuple[Direction, str], PendingSetup],
    triggers: list[M15Trigger],
) -> dict[tuple[Direction, str], PendingSetup]:
    updated = dict(pending_map)
    trigger_directions = {trigger.direction for trigger in triggers}
    if Direction.BUY in trigger_directions:
        updated = {
            key: value for key, value in updated.items() if value.direction is not Direction.SELL
        }
    if Direction.SELL in trigger_directions:
        updated = {
            key: value for key, value in updated.items() if value.direction is not Direction.BUY
        }
    for trigger in triggers:
        key = (trigger.direction, trigger.mode.value)
        updated[key] = PendingSetup(
            symbol=symbol,
            direction=trigger.direction,
            mode=trigger.mode,
            state=PendingState.WAIT_M1_LWMA,
            m15_trigger_time_utc=trigger.m15_close_time_utc,
            last_updated_utc=utc_now(),
            m15_lwma_fast=trigger.m15_lwma_fast,
            m15_lwma_slow=trigger.m15_lwma_slow,
            m15_stoch_k=trigger.m15_stoch_k,
            m15_stoch_d=trigger.m15_stoch_d,
        )
    return updated


def _advance_pending(
    strategy: StrategyEvaluator,
    pending_map: dict[tuple[Direction, str], PendingSetup],
    snapshot: M1Snapshot,
) -> tuple[dict[tuple[Direction, str], PendingSetup], list[Signal]]:
    updated: dict[tuple[Direction, str], PendingSetup] = {}
    emitted: list[Signal] = []
    for key, pending in pending_map.items():
        next_pending, signal = strategy.advance_pending_setup(
            pending=pending,
            snapshot=snapshot,
            price=snapshot.close_price,
        )
        if next_pending is not None:
            updated[key] = next_pending
        if signal is not None:
            emitted.append(signal)
    return (updated, emitted)


def _evaluate_trades(
    signals: list[Signal],
    m1_all: pd.DataFrame,
    hold_minutes: int,
) -> list[RecordedTrade]:
    trades: list[RecordedTrade] = []
    for signal in signals:
        target_time = signal.m1_bar_time_utc + timedelta(minutes=hold_minutes)
        future_rows = m1_all[m1_all["time"] >= target_time]
        if future_rows.empty:
            continue
        exit_row = future_rows.iloc[0]
        trades.append(
            time_based_outcome(
                signal=signal,
                future_close_price=float(exit_row["close"]),
                future_time_utc=pd.to_datetime(exit_row["time"], utc=True).to_pydatetime(),
            )
        )
    return trades
