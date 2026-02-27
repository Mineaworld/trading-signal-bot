"""Signal grading: classifies signals by confluence level."""

from __future__ import annotations

from enum import Enum

from trading_signal_bot.models import Scenario


class SignalGrade(str, Enum):
    A_PLUS = "A+"
    A = "A"
    B = "B"


_SCENARIO_GRADE: dict[Scenario, SignalGrade] = {
    Scenario.BUY_CHAIN: SignalGrade.A_PLUS,
    Scenario.SELL_CHAIN: SignalGrade.A_PLUS,
    Scenario.BUY_CHAIN_HP: SignalGrade.A_PLUS,
    Scenario.SELL_CHAIN_HP: SignalGrade.A_PLUS,
    Scenario.BUY_S1: SignalGrade.A,
    Scenario.SELL_S1: SignalGrade.A,
    Scenario.BUY_S2: SignalGrade.A,
    Scenario.SELL_S2: SignalGrade.A,
    Scenario.BUY_M1: SignalGrade.B,
    Scenario.SELL_M1: SignalGrade.B,
}


def compute_grade(scenario: Scenario | str) -> SignalGrade:
    """Compute signal grade from scenario.

    A+ = full confluence (M15 LWMA + M15 stoch cross + M1 stoch cross + M1 LWMA cross)
    A  = M15 gate + M1 partial confirm (stoch or LWMA, not both)
    B  = M1 only, no M15 context
    """
    if isinstance(scenario, str):
        try:
            scenario = Scenario(scenario)
        except ValueError:
            return SignalGrade.B
    return _SCENARIO_GRADE.get(scenario, SignalGrade.B)
