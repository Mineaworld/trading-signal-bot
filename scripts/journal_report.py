from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Signal journal KPI report")
    parser.add_argument("--db", type=Path, default=Path("data/signals.db"))
    args = parser.parse_args()

    if not args.db.exists():
        print(f"db not found: {args.db}")
        return

    with sqlite3.connect(args.db) as conn:
        total = _scalar(conn, "SELECT COUNT(*) FROM signals")
        sent = _scalar(conn, "SELECT COUNT(*) FROM signals WHERE sent_success = 1")
        outcomes = _scalar(conn, "SELECT COUNT(*) FROM outcomes")
        wins = _scalar(conn, "SELECT COUNT(*) FROM outcomes WHERE pnl > 0")
        losses = _scalar(conn, "SELECT COUNT(*) FROM outcomes WHERE pnl < 0")
        avg_rr = _scalar(conn, "SELECT AVG(rr) FROM outcomes WHERE rr IS NOT NULL")

        print(f"Total Signals: {total}")
        print(f"Sent Success: {sent}")
        print(f"Outcomes Logged: {outcomes}")
        print(f"Wins: {wins}")
        print(f"Losses: {losses}")
        if outcomes > 0:
            win_rate = (wins / outcomes) * 100.0
            print(f"Win Rate: {win_rate:.2f}%")
        if avg_rr is not None:
            print(f"Avg RR: {float(avg_rr):.3f}")

        print("\nBy Symbol:")
        rows = conn.execute("""
            SELECT symbol, COUNT(*) AS cnt
            FROM signals
            GROUP BY symbol
            ORDER BY cnt DESC
            """).fetchall()
        for symbol, cnt in rows:
            print(f"- {symbol}: {cnt}")

        print("\nBy Scenario:")
        rows = conn.execute("""
            SELECT scenario, COUNT(*) AS cnt
            FROM signals
            GROUP BY scenario
            ORDER BY cnt DESC
            """).fetchall()
        for scenario, cnt in rows:
            print(f"- {scenario}: {cnt}")


def _scalar(conn: sqlite3.Connection, sql: str) -> int | float | None:
    row = conn.execute(sql).fetchone()
    if row is None:
        return None
    return row[0]


if __name__ == "__main__":
    main()
