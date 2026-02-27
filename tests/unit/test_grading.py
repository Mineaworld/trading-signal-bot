"""Tests for signal grading."""

from __future__ import annotations

from backtester.grading import SignalGrade, compute_grade
from trading_signal_bot.models import Scenario


class TestComputeGrade:
    def test_chain_scenarios_grade_a_plus(self) -> None:
        assert compute_grade(Scenario.BUY_CHAIN) is SignalGrade.A_PLUS
        assert compute_grade(Scenario.SELL_CHAIN) is SignalGrade.A_PLUS
        assert compute_grade(Scenario.BUY_CHAIN_HP) is SignalGrade.A_PLUS
        assert compute_grade(Scenario.SELL_CHAIN_HP) is SignalGrade.A_PLUS

    def test_s1_scenarios_grade_a(self) -> None:
        assert compute_grade(Scenario.BUY_S1) is SignalGrade.A
        assert compute_grade(Scenario.SELL_S1) is SignalGrade.A

    def test_s2_scenarios_grade_a(self) -> None:
        assert compute_grade(Scenario.BUY_S2) is SignalGrade.A
        assert compute_grade(Scenario.SELL_S2) is SignalGrade.A

    def test_m1_scenarios_grade_b(self) -> None:
        assert compute_grade(Scenario.BUY_M1) is SignalGrade.B
        assert compute_grade(Scenario.SELL_M1) is SignalGrade.B

    def test_summary_scenarios_default_b(self) -> None:
        assert compute_grade(Scenario.BUY_SUMMARY) is SignalGrade.B
        assert compute_grade(Scenario.SELL_SUMMARY) is SignalGrade.B

    def test_string_scenario_lookup(self) -> None:
        assert compute_grade("BUY_CHAIN") is SignalGrade.A_PLUS
        assert compute_grade("BUY_S1") is SignalGrade.A
        assert compute_grade("BUY_M1") is SignalGrade.B

    def test_unknown_string_defaults_b(self) -> None:
        assert compute_grade("UNKNOWN_SCENARIO") is SignalGrade.B
