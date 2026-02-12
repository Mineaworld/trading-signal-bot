from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from enum import Enum
from typing import Any
from uuid import uuid4


class Timeframe(str, Enum):
    M1 = "M1"
    M15 = "M15"


class Direction(str, Enum):
    BUY = "BUY"
    SELL = "SELL"


class Scenario(str, Enum):
    BUY_S1 = "BUY_S1"
    BUY_S2 = "BUY_S2"
    SELL_S1 = "SELL_S1"
    SELL_S2 = "SELL_S2"
    BUY_M1 = "BUY_M1"
    SELL_M1 = "SELL_M1"


@dataclass(frozen=True)
class IndicatorParams:
    lwma_fast: int
    lwma_slow: int
    stoch_k: int
    stoch_d: int
    stoch_slowing: int
    buy_zone: tuple[int, int]
    sell_zone: tuple[int, int]


@dataclass(frozen=True)
class Signal:
    id: str
    symbol: str
    direction: Direction
    scenario: Scenario
    price: float
    created_at_utc: datetime
    m1_bar_time_utc: datetime
    m15_bar_time_utc: datetime | None = None
    m15_lwma_fast: float | None = None
    m15_lwma_slow: float | None = None
    m15_stoch_k: float | None = None
    m15_stoch_d: float | None = None
    m1_lwma_fast: float | None = None
    m1_lwma_slow: float | None = None
    m1_stoch_k: float | None = None
    m1_stoch_d: float | None = None

    @staticmethod
    def new_id() -> str:
        return uuid4().hex

    @property
    def idempotency_key(self) -> str:
        bar_time = self.m15_bar_time_utc or self.m1_bar_time_utc
        bar = bar_time.strftime("%Y-%m-%dT%H:%M:%SZ")
        return f"{self.symbol}|{self.direction.value}|{self.scenario.value}|{bar}"

    @property
    def cooldown_key(self) -> str:
        return f"{self.symbol}|{self.direction.value}"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["direction"] = self.direction.value
        payload["scenario"] = self.scenario.value
        payload["created_at_utc"] = self.created_at_utc.isoformat()
        payload["m15_bar_time_utc"] = (
            self.m15_bar_time_utc.isoformat() if self.m15_bar_time_utc else None
        )
        payload["m1_bar_time_utc"] = self.m1_bar_time_utc.isoformat()
        return payload

    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> Signal:
        return cls(
            id=str(payload["id"]),
            symbol=str(payload["symbol"]),
            direction=Direction(str(payload["direction"])),
            scenario=Scenario(str(payload["scenario"])),
            price=float(payload["price"]),
            created_at_utc=datetime.fromisoformat(str(payload["created_at_utc"])),
            m1_bar_time_utc=datetime.fromisoformat(str(payload["m1_bar_time_utc"])),
            m15_bar_time_utc=(
                datetime.fromisoformat(str(payload["m15_bar_time_utc"]))
                if payload.get("m15_bar_time_utc") is not None
                else None
            ),
            m15_lwma_fast=(
                float(payload["m15_lwma_fast"])
                if payload.get("m15_lwma_fast") is not None
                else None
            ),
            m15_lwma_slow=(
                float(payload["m15_lwma_slow"])
                if payload.get("m15_lwma_slow") is not None
                else None
            ),
            m15_stoch_k=(
                float(payload["m15_stoch_k"]) if payload.get("m15_stoch_k") is not None else None
            ),
            m15_stoch_d=(
                float(payload["m15_stoch_d"]) if payload.get("m15_stoch_d") is not None else None
            ),
            m1_lwma_fast=(
                float(payload["m1_lwma_fast"]) if payload.get("m1_lwma_fast") is not None else None
            ),
            m1_lwma_slow=(
                float(payload["m1_lwma_slow"]) if payload.get("m1_lwma_slow") is not None else None
            ),
            m1_stoch_k=(
                float(payload["m1_stoch_k"]) if payload.get("m1_stoch_k") is not None else None
            ),
            m1_stoch_d=(
                float(payload["m1_stoch_d"]) if payload.get("m1_stoch_d") is not None else None
            ),
        )
