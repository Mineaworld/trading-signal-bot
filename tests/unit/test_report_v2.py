"""Tests for report.py v2 analytics."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from backtester.report import (
    build_report,
    export_equity_curve,
    export_trade_log,
    format_report,
)
from backtester.trade_recorder import ExitReason, RecordedTrade
from trading_signal_bot.models import Direction

UTC = timezone.utc


def _trade(
    pnl: float,
    direction: Direction = Direction.BUY,
    scenario: str = "BUY_S1",
    exit_reason: ExitReason = ExitReason.TIME,
    sl: float | None = None,
    tp1: float | None = None,
    tp2: float | None = None,
) -> RecordedTrade:
    """Helper to build a RecordedTrade with minimal fields."""
    entry = 100.0
    exit_price = entry + pnl if direction is Direction.BUY else entry - pnl
    return RecordedTrade(
        signal_id="sig-test",
        symbol="XAUUSD",
        direction=direction,
        scenario=scenario,
        entry_price=entry,
        entry_time_utc=datetime(2026, 2, 11, 14, 0, tzinfo=UTC),
        exit_price=exit_price,
        exit_time_utc=datetime(2026, 2, 11, 14, 15, tzinfo=UTC),
        pnl=pnl,
        exit_reason=exit_reason,
        sl_price=sl,
        tp1_price=tp1,
        tp2_price=tp2,
    )


class TestBuildReportEmpty:
    """Empty trades returns zero-state report."""

    def test_empty_trades(self) -> None:
        report = build_report([])
        assert report.total_trades == 0
        assert report.wins == 0
        assert report.losses == 0
        assert report.win_rate == 0.0
        assert report.total_pnl == 0.0
        assert report.profit_factor == 0.0
        assert report.max_drawdown == 0.0


class TestProfitFactor:
    """Profit factor with mixed wins/losses."""

    def test_mixed_wins_losses(self) -> None:
        trades = [
            _trade(pnl=10.0),  # win
            _trade(pnl=-5.0),  # loss
            _trade(pnl=8.0),  # win
            _trade(pnl=-3.0),  # loss
        ]
        report = build_report(trades)
        # gross_profit = 18, gross_loss = 8, PF = 18/8 = 2.25
        assert report.profit_factor == pytest.approx(2.25)
        assert report.total_trades == 4
        assert report.wins == 2
        assert report.losses == 2

    def test_all_wins(self) -> None:
        trades = [_trade(pnl=5.0), _trade(pnl=3.0)]
        report = build_report(trades)
        assert report.profit_factor == float("inf")
        assert report.avg_win_loss_ratio == float("inf")

    def test_all_losses(self) -> None:
        trades = [_trade(pnl=-5.0), _trade(pnl=-3.0)]
        report = build_report(trades)
        assert report.profit_factor == 0.0
        assert report.avg_win_loss_ratio == 0.0


class TestBreakevenTrades:
    """Breakeven trades (pnl=0) handling."""

    def test_breakeven_counted(self) -> None:
        trades = [_trade(pnl=5.0), _trade(pnl=0.0), _trade(pnl=-2.0)]
        report = build_report(trades)
        assert report.breakeven == 1
        assert report.wins == 1
        assert report.losses == 1
        assert report.win_rate == pytest.approx(33.333, rel=1e-3)

    def test_all_breakeven(self) -> None:
        trades = [_trade(pnl=0.0), _trade(pnl=0.0)]
        report = build_report(trades)
        assert report.breakeven == 2
        assert report.wins == 0
        assert report.losses == 0
        assert report.profit_factor == 0.0
        assert report.avg_win_loss_ratio == 0.0


class TestMaxDrawdown:
    """Peak-to-trough on cumulative PnL."""

    def test_drawdown_calculation(self) -> None:
        # Cumulative: 10, 20, 15, 12, 18 → peak=20, trough=12, dd=8
        trades = [
            _trade(pnl=10.0),
            _trade(pnl=10.0),
            _trade(pnl=-5.0),
            _trade(pnl=-3.0),
            _trade(pnl=6.0),
        ]
        report = build_report(trades)
        assert report.max_drawdown == pytest.approx(8.0)

    def test_no_drawdown(self) -> None:
        trades = [_trade(pnl=5.0), _trade(pnl=3.0), _trade(pnl=1.0)]
        report = build_report(trades)
        assert report.max_drawdown == pytest.approx(0.0)


class TestConsecutiveStreaks:
    """Max consecutive win/loss streaks."""

    def test_streaks(self) -> None:
        # W W W L L W L L L L
        trades = [
            _trade(pnl=1.0),
            _trade(pnl=2.0),
            _trade(pnl=3.0),
            _trade(pnl=-1.0),
            _trade(pnl=-2.0),
            _trade(pnl=1.0),
            _trade(pnl=-1.0),
            _trade(pnl=-2.0),
            _trade(pnl=-3.0),
            _trade(pnl=-4.0),
        ]
        report = build_report(trades)
        assert report.max_consecutive_wins == 3
        assert report.max_consecutive_losses == 4


class TestPerScenarioGrouping:
    """Per-scenario grouping correctness."""

    def test_by_scenario(self) -> None:
        trades = [
            _trade(pnl=5.0, scenario="BUY_S1"),
            _trade(pnl=-2.0, scenario="BUY_S1"),
            _trade(pnl=3.0, scenario="SELL_S1"),
        ]
        report = build_report(trades)
        assert "BUY_S1" in report.by_scenario
        assert "SELL_S1" in report.by_scenario
        assert report.by_scenario["BUY_S1"].total == 2
        assert report.by_scenario["BUY_S1"].wins == 1
        assert report.by_scenario["BUY_S1"].losses == 1
        assert report.by_scenario["SELL_S1"].total == 1
        assert report.by_scenario["SELL_S1"].wins == 1

    def test_by_direction(self) -> None:
        trades = [
            _trade(pnl=5.0, direction=Direction.BUY),
            _trade(pnl=-2.0, direction=Direction.SELL),
            _trade(pnl=3.0, direction=Direction.SELL),
        ]
        report = build_report(trades)
        assert report.by_direction["BUY"].total == 1
        assert report.by_direction["SELL"].total == 2


class TestExitReasonCounts:
    """Exit reason counts."""

    def test_counts(self) -> None:
        trades = [
            _trade(pnl=5.0, exit_reason=ExitReason.TP1),
            _trade(pnl=-2.0, exit_reason=ExitReason.SL),
            _trade(pnl=3.0, exit_reason=ExitReason.STOCH),
            _trade(pnl=-1.0, exit_reason=ExitReason.SL),
            _trade(pnl=0.0, exit_reason=ExitReason.MAX_HOLD),
        ]
        report = build_report(trades)
        assert report.exit_reason_counts["SL"] == 2
        assert report.exit_reason_counts["TP1"] == 1
        assert report.exit_reason_counts["STOCH"] == 1
        assert report.exit_reason_counts["MAX_HOLD"] == 1


class TestFormatReport:
    """format_report produces readable output."""

    def test_format_no_trades(self) -> None:
        report = build_report([])
        text = format_report(report)
        assert "No trades" in text

    def test_format_with_trades(self) -> None:
        trades = [_trade(pnl=5.0), _trade(pnl=-2.0)]
        report = build_report(trades)
        text = format_report(report)
        assert "Backtest Report" in text
        assert "Win Rate" in text
        assert "Profit Factor" in text


class TestCsvExport:
    """CSV export writes valid files."""

    def test_equity_curve_csv(self, tmp_path: Path) -> None:
        trades = [_trade(pnl=5.0), _trade(pnl=-2.0), _trade(pnl=3.0)]
        csv_path = tmp_path / "equity.csv"
        export_equity_curve(trades, csv_path)

        lines = csv_path.read_text().strip().split("\n")
        assert lines[0] == "trade_num,exit_time,pnl,cumulative_pnl"
        assert len(lines) == 4  # header + 3 trades
        # Check cumulative PnL on last row
        last_row = lines[-1].split(",")
        assert float(last_row[3]) == pytest.approx(6.0)  # 5 - 2 + 3

    def test_trade_log_csv(self, tmp_path: Path) -> None:
        trades = [
            _trade(pnl=5.0, exit_reason=ExitReason.TP1, sl=98.0, tp1=105.0),
            _trade(pnl=-2.0, exit_reason=ExitReason.SL, sl=98.0, tp1=105.0),
        ]
        csv_path = tmp_path / "trades.csv"
        export_trade_log(trades, csv_path)

        lines = csv_path.read_text().strip().split("\n")
        assert "signal_id" in lines[0]
        assert "exit_reason" in lines[0]
        assert len(lines) == 3  # header + 2 trades
