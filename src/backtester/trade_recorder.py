from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from trading_signal_bot.models import Direction, Signal


class ExitReason(str, Enum):
    """Why a trade was closed."""

    SL = "SL"
    TP1 = "TP1"
    STOCH = "STOCH"  # v2b
    TIME = "TIME"
    MAX_HOLD = "MAX_HOLD"  # v2b
    DATA_END = "DATA_END"


@dataclass(frozen=True)
class RecordedTrade:
    signal_id: str
    symbol: str
    direction: Direction
    scenario: str
    entry_price: float
    entry_time_utc: datetime
    exit_price: float
    exit_time_utc: datetime
    pnl: float
    exit_reason: ExitReason = ExitReason.TIME
    sl_price: float | None = None
    tp1_price: float | None = None
    tp2_price: float | None = None


def _entry_time(signal: Signal) -> datetime:
    return signal.m1_bar_time_utc if signal.m1_bar_time_utc is not None else signal.created_at_utc


def make_trade(
    signal: Signal,
    exit_price: float,
    exit_time_utc: datetime,
    exit_reason: ExitReason,
    sl_price: float | None = None,
    tp1_price: float | None = None,
    tp2_price: float | None = None,
) -> RecordedTrade:
    """Factory to build a RecordedTrade from a signal and exit details."""
    pnl = exit_price - signal.price
    if signal.direction is Direction.SELL:
        pnl = -pnl
    return RecordedTrade(
        signal_id=signal.id,
        symbol=signal.symbol,
        direction=signal.direction,
        scenario=signal.scenario.value,
        entry_price=signal.price,
        entry_time_utc=_entry_time(signal),
        exit_price=exit_price,
        exit_time_utc=exit_time_utc,
        pnl=pnl,
        exit_reason=exit_reason,
        sl_price=sl_price,
        tp1_price=tp1_price,
        tp2_price=tp2_price,
    )


def time_based_outcome(
    signal: Signal,
    future_close_price: float,
    future_time_utc: datetime,
) -> RecordedTrade:
    """V1 backward-compat: create a TIME-exit trade."""
    pnl = future_close_price - signal.price
    if signal.direction is Direction.SELL:
        pnl = -pnl
    return RecordedTrade(
        signal_id=signal.id,
        symbol=signal.symbol,
        direction=signal.direction,
        scenario=signal.scenario.value,
        entry_price=signal.price,
        entry_time_utc=_entry_time(signal),
        exit_price=future_close_price,
        exit_time_utc=future_time_utc,
        pnl=pnl,
        exit_reason=ExitReason.TIME,
    )
