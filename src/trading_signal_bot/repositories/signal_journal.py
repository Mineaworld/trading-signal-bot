from __future__ import annotations

import json
import logging
import sqlite3
from pathlib import Path

from trading_signal_bot.models import Signal


class SignalJournal:
    """SQLite-backed journal for recording sent signals and outcomes."""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._logger = logging.getLogger(self.__class__.__name__)
        self._conn: sqlite3.Connection = self._open_connection()
        self._initialize()

    def _open_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        result = conn.execute("PRAGMA journal_mode=WAL").fetchone()
        if result is None or result[0].upper() != "WAL":
            self._logger.warning("WAL mode not confirmed, got: %s", result[0] if result else None)
        return conn

    def _initialize(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS signals (
                signal_id TEXT PRIMARY KEY,
                symbol TEXT NOT NULL,
                direction TEXT NOT NULL,
                scenario TEXT NOT NULL,
                matched_scenarios_json TEXT,
                created_at_utc TEXT NOT NULL,
                m15_bar_time_utc TEXT,
                m1_bar_time_utc TEXT NOT NULL,
                entry_price REAL NOT NULL,
                risk_stop_distance REAL,
                risk_invalidation_price REAL,
                risk_tp1_price REAL,
                risk_tp2_price REAL,
                sent_success INTEGER NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS outcomes (
                signal_id TEXT PRIMARY KEY,
                status TEXT NOT NULL,
                taken INTEGER,
                exit_price REAL,
                pnl REAL,
                rr REAL,
                note TEXT,
                updated_at_utc TEXT NOT NULL,
                FOREIGN KEY(signal_id) REFERENCES signals(signal_id)
            )
            """
        )
        self._conn.commit()

    def record_sent_signal(self, signal: Signal, sent_success: bool) -> None:
        matched_json = None
        if signal.matched_scenarios:
            matched_json = json.dumps([item.value for item in signal.matched_scenarios])
        self._conn.execute(
            """
            INSERT OR REPLACE INTO signals(
                signal_id, symbol, direction, scenario, matched_scenarios_json,
                created_at_utc, m15_bar_time_utc, m1_bar_time_utc, entry_price,
                risk_stop_distance, risk_invalidation_price, risk_tp1_price, risk_tp2_price,
                sent_success
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                signal.id,
                signal.symbol,
                signal.direction.value,
                signal.scenario.value,
                matched_json,
                signal.created_at_utc.isoformat(),
                signal.m15_bar_time_utc.isoformat() if signal.m15_bar_time_utc else None,
                signal.m1_bar_time_utc.isoformat(),
                signal.price,
                signal.risk_stop_distance,
                signal.risk_invalidation_price,
                signal.risk_tp1_price,
                signal.risk_tp2_price,
                1 if sent_success else 0,
            ),
        )
        self._conn.commit()

    def close(self) -> None:
        """Close the persistent connection. Safe to call during shutdown."""
        try:
            self._conn.close()
        except Exception:
            self._logger.exception("error closing signal journal connection")
