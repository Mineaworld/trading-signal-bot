from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from trading_signal_bot.models import Direction, Signal


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


def time_based_outcome(
    signal: Signal,
    future_close_price: float,
    future_time_utc: datetime,
) -> RecordedTrade:
    pnl = future_close_price - signal.price
    if signal.direction is Direction.SELL:
        pnl = -pnl
    return RecordedTrade(
        signal_id=signal.id,
        symbol=signal.symbol,
        direction=signal.direction,
        scenario=signal.scenario.value,
        entry_price=signal.price,
        entry_time_utc=signal.created_at_utc,
        exit_price=future_close_price,
        exit_time_utc=future_time_utc,
        pnl=pnl,
    )
