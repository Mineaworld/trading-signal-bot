from __future__ import annotations

from typing import Protocol

import pandas as pd

from trading_signal_bot.models import Signal, Timeframe


class CandleDataProvider(Protocol):
    def fetch_candles(
        self, symbol: str, timeframe: Timeframe, count: int = 450
    ) -> pd.DataFrame: ...


class SignalPublisher(Protocol):
    def send_signal(self, signal: Signal) -> bool: ...


class StateStore(Protocol):
    def should_emit(self, signal: Signal) -> bool: ...

    def record(self, signal: Signal) -> None: ...
