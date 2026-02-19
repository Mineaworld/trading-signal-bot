from __future__ import annotations

import json
import sqlite3
from pathlib import Path

from trading_signal_bot.models import Signal


class SignalJournal:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    def _initialize(self) -> None:
        with self._connect() as conn:
            conn.execute(
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
            conn.execute(
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
            conn.commit()

    def record_sent_signal(self, signal: Signal, sent_success: bool) -> None:
        matched_json = None
        if signal.matched_scenarios:
            matched_json = json.dumps([item.value for item in signal.matched_scenarios])
        with self._connect() as conn:
            conn.execute(
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
            conn.commit()
