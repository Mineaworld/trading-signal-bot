from __future__ import annotations

import argparse
import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description="Update signal outcome in SQLite journal")
    parser.add_argument("--db", type=Path, default=Path("data/signals.db"))
    parser.add_argument("--signal-id", required=True)
    parser.add_argument("--status", default="closed")
    parser.add_argument("--taken", choices=["0", "1"], default=None)
    parser.add_argument("--exit-price", type=float, default=None)
    parser.add_argument("--pnl", type=float, default=None)
    parser.add_argument("--rr", type=float, default=None)
    parser.add_argument("--note", default="")
    args = parser.parse_args()

    if not args.db.exists():
        print(f"db not found: {args.db}")
        return

    taken_val = int(args.taken) if args.taken is not None else None
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(args.db) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO outcomes(
                signal_id, status, taken, exit_price, pnl, rr, note, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                args.signal_id,
                args.status,
                taken_val,
                args.exit_price,
                args.pnl,
                args.rr,
                args.note,
                now,
            ),
        )
        conn.commit()
    print(f"outcome updated for {args.signal_id}")


if __name__ == "__main__":
    main()
