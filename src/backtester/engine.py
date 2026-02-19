from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

import pandas as pd

from trading_signal_bot.models import Signal
from trading_signal_bot.strategy import StrategyEvaluator

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

    trades = _evaluate_trades(signals=signals, m1_all=m1_all, hold_minutes=hold_minutes)
    return BacktestResult(signals=signals, trades=trades)


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
