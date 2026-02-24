"""Backtester reporting: analytics, formatting, and CSV exports."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

from .trade_recorder import RecordedTrade


@dataclass(frozen=True)
class ScenarioStats:
    """Stats for a single grouping (scenario or direction)."""

    total: int = 0
    wins: int = 0
    losses: int = 0
    total_pnl: float = 0.0


@dataclass(frozen=True)
class BacktestReport:
    """Full analytics for a backtest run."""

    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    breakeven: int = 0
    win_rate: float = 0.0
    avg_pnl: float = 0.0
    total_pnl: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    avg_win_loss_ratio: float = 0.0
    max_drawdown: float = 0.0
    max_consecutive_wins: int = 0
    max_consecutive_losses: int = 0
    by_scenario: dict[str, ScenarioStats] = field(default_factory=dict)
    by_direction: dict[str, ScenarioStats] = field(default_factory=dict)
    exit_reason_counts: dict[str, int] = field(default_factory=dict)


def build_report(trades: list[RecordedTrade]) -> BacktestReport:
    """Build full analytics from a list of trades."""
    if not trades:
        return BacktestReport()

    total = len(trades)
    wins = sum(1 for t in trades if t.pnl > 0)
    losses = sum(1 for t in trades if t.pnl < 0)
    breakeven = total - wins - losses
    total_pnl = sum(t.pnl for t in trades)
    avg_pnl = total_pnl / total

    win_rate = (wins / total) * 100.0 if total > 0 else 0.0

    # Profit factor
    gross_profit = sum(t.pnl for t in trades if t.pnl > 0)
    gross_loss = abs(sum(t.pnl for t in trades if t.pnl < 0))
    profit_factor = (
        gross_profit / gross_loss if gross_loss > 0 else float("inf") if gross_profit > 0 else 0.0
    )

    # Avg win / avg loss
    win_pnls = [t.pnl for t in trades if t.pnl > 0]
    loss_pnls = [t.pnl for t in trades if t.pnl < 0]
    avg_win = sum(win_pnls) / len(win_pnls) if win_pnls else 0.0
    avg_loss = sum(loss_pnls) / len(loss_pnls) if loss_pnls else 0.0
    avg_win_loss_ratio = (
        avg_win / abs(avg_loss) if avg_loss != 0 else float("inf") if avg_win > 0 else 0.0
    )

    # Max drawdown (peak-to-trough on cumulative PnL)
    max_drawdown = _compute_max_drawdown(trades)

    # Consecutive streaks
    max_consecutive_wins, max_consecutive_losses = _compute_streaks(trades)

    # By scenario
    by_scenario = _group_stats(trades, key_fn=lambda t: t.scenario)

    # By direction
    by_direction = _group_stats(trades, key_fn=lambda t: t.direction.value)

    # Exit reason counts
    exit_reason_counts: dict[str, int] = defaultdict(int)
    for t in trades:
        exit_reason_counts[t.exit_reason.value] += 1

    return BacktestReport(
        total_trades=total,
        wins=wins,
        losses=losses,
        breakeven=breakeven,
        win_rate=win_rate,
        avg_pnl=avg_pnl,
        total_pnl=total_pnl,
        profit_factor=profit_factor,
        avg_win=avg_win,
        avg_loss=avg_loss,
        avg_win_loss_ratio=avg_win_loss_ratio,
        max_drawdown=max_drawdown,
        max_consecutive_wins=max_consecutive_wins,
        max_consecutive_losses=max_consecutive_losses,
        by_scenario=dict(by_scenario),
        by_direction=dict(by_direction),
        exit_reason_counts=dict(exit_reason_counts),
    )


def format_report(report: BacktestReport, config: object | None = None) -> str:
    """Format a BacktestReport as terminal-friendly text."""
    if report.total_trades == 0:
        return "No trades recorded."

    lines = [
        "=== Backtest Report ===",
        f"Total Trades: {report.total_trades}",
        f"Wins: {report.wins}  |  Losses: {report.losses}  |  Breakeven: {report.breakeven}",
        f"Win Rate: {report.win_rate:.2f}%",
        f"Total PnL: {report.total_pnl:.5f}",
        f"Avg PnL: {report.avg_pnl:.5f}",
        f"Profit Factor: {report.profit_factor:.2f}",
        f"Avg Win: {report.avg_win:.5f}  |  Avg Loss: {report.avg_loss:.5f}",
        f"Win/Loss Ratio: {report.avg_win_loss_ratio:.2f}",
        f"Max Drawdown: {report.max_drawdown:.5f}",
        f"Max Consecutive Wins: {report.max_consecutive_wins}",
        f"Max Consecutive Losses: {report.max_consecutive_losses}",
        "",
        "--- By Scenario ---",
    ]
    for scenario, stats in sorted(report.by_scenario.items()):
        wr = (stats.wins / stats.total) * 100.0 if stats.total > 0 else 0.0
        lines.append(
            f"  {scenario}: {stats.total} trades, {wr:.1f}% win, PnL={stats.total_pnl:.5f}"
        )

    lines.append("")
    lines.append("--- By Direction ---")
    for direction, stats in sorted(report.by_direction.items()):
        wr = (stats.wins / stats.total) * 100.0 if stats.total > 0 else 0.0
        lines.append(
            f"  {direction}: {stats.total} trades, {wr:.1f}% win, PnL={stats.total_pnl:.5f}"
        )

    lines.append("")
    lines.append("--- Exit Reasons ---")
    for reason, count in sorted(report.exit_reason_counts.items()):
        lines.append(f"  {reason}: {count}")

    return "\n".join(lines)


def export_equity_curve(trades: list[RecordedTrade], path: Path) -> None:
    """Write CSV: trade_num, exit_time, pnl, cumulative_pnl."""
    path.parent.mkdir(parents=True, exist_ok=True)
    cumulative = 0.0
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["trade_num", "exit_time", "pnl", "cumulative_pnl"])
        for i, trade in enumerate(trades, 1):
            cumulative += trade.pnl
            writer.writerow(
                [i, trade.exit_time_utc.isoformat(), f"{trade.pnl:.5f}", f"{cumulative:.5f}"]
            )


def export_trade_log(trades: list[RecordedTrade], path: Path) -> None:
    """Write CSV with all RecordedTrade fields."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "signal_id",
                "symbol",
                "direction",
                "scenario",
                "entry_price",
                "entry_time_utc",
                "exit_price",
                "exit_time_utc",
                "pnl",
                "exit_reason",
                "sl_price",
                "tp1_price",
                "tp2_price",
            ]
        )
        for trade in trades:
            writer.writerow(
                [
                    trade.signal_id,
                    trade.symbol,
                    trade.direction.value,
                    trade.scenario,
                    f"{trade.entry_price:.5f}",
                    trade.entry_time_utc.isoformat(),
                    f"{trade.exit_price:.5f}",
                    trade.exit_time_utc.isoformat(),
                    f"{trade.pnl:.5f}",
                    trade.exit_reason.value,
                    f"{trade.sl_price:.5f}" if trade.sl_price is not None else "",
                    f"{trade.tp1_price:.5f}" if trade.tp1_price is not None else "",
                    f"{trade.tp2_price:.5f}" if trade.tp2_price is not None else "",
                ]
            )


def summarize(trades: list[RecordedTrade]) -> str:
    """V1 backward-compat summary."""
    if not trades:
        return "No trades recorded."

    total = len(trades)
    wins = sum(1 for trade in trades if trade.pnl > 0)
    losses = sum(1 for trade in trades if trade.pnl < 0)
    avg_pnl = sum(trade.pnl for trade in trades) / total
    by_symbol: dict[str, int] = defaultdict(int)
    for trade in trades:
        by_symbol[trade.symbol] += 1

    lines = [
        f"Total Trades: {total}",
        f"Wins: {wins}",
        f"Losses: {losses}",
        f"Win Rate: {(wins / total) * 100:.2f}%",
        f"Average PnL: {avg_pnl:.5f}",
        "By Symbol:",
    ]
    for symbol, count in sorted(by_symbol.items(), key=lambda item: item[1], reverse=True):
        lines.append(f"- {symbol}: {count}")
    return "\n".join(lines)


def _compute_max_drawdown(trades: list[RecordedTrade]) -> float:
    """Peak-to-trough on cumulative PnL."""
    peak = 0.0
    cumulative = 0.0
    max_dd = 0.0
    for t in trades:
        cumulative += t.pnl
        if cumulative > peak:
            peak = cumulative
        dd = peak - cumulative
        if dd > max_dd:
            max_dd = dd
    return max_dd


def _compute_streaks(trades: list[RecordedTrade]) -> tuple[int, int]:
    """Return (max_consecutive_wins, max_consecutive_losses)."""
    max_wins = 0
    max_losses = 0
    current_wins = 0
    current_losses = 0
    for t in trades:
        if t.pnl > 0:
            current_wins += 1
            current_losses = 0
            if current_wins > max_wins:
                max_wins = current_wins
        elif t.pnl < 0:
            current_losses += 1
            current_wins = 0
            if current_losses > max_losses:
                max_losses = current_losses
        else:
            current_wins = 0
            current_losses = 0
    return (max_wins, max_losses)


def _group_stats(
    trades: list[RecordedTrade],
    key_fn: object,
) -> dict[str, ScenarioStats]:
    """Group trades by key_fn and compute stats per group."""
    groups: dict[str, list[RecordedTrade]] = defaultdict(list)
    for t in trades:
        groups[key_fn(t)].append(t)  # type: ignore[operator]

    result: dict[str, ScenarioStats] = {}
    for key, group in groups.items():
        result[key] = ScenarioStats(
            total=len(group),
            wins=sum(1 for t in group if t.pnl > 0),
            losses=sum(1 for t in group if t.pnl < 0),
            total_pnl=sum(t.pnl for t in group),
        )
    return result
