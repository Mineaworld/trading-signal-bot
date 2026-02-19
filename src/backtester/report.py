from __future__ import annotations

from collections import defaultdict

from .trade_recorder import RecordedTrade


def summarize(trades: list[RecordedTrade]) -> str:
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
