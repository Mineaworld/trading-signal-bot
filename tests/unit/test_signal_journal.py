from __future__ import annotations

import sqlite3

from trading_signal_bot.repositories.signal_journal import SignalJournal


def test_record_and_query(tmp_path, sample_signal) -> None:
    db_path = tmp_path / "test_journal.db"
    journal = SignalJournal(db_path)

    journal.record_sent_signal(sample_signal, sent_success=True)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM signals WHERE signal_id = ?", (sample_signal.id,)).fetchall()
    conn.close()

    assert len(rows) == 1
    row = rows[0]
    assert row["symbol"] == sample_signal.symbol
    assert row["direction"] == sample_signal.direction.value
    assert row["scenario"] == sample_signal.scenario.value
    assert row["sent_success"] == 1
    assert row["entry_price"] == sample_signal.price

    journal.close()


def test_record_failed_signal(tmp_path, sample_signal) -> None:
    db_path = tmp_path / "test_journal.db"
    journal = SignalJournal(db_path)

    journal.record_sent_signal(sample_signal, sent_success=False)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT sent_success FROM signals WHERE signal_id = ?", (sample_signal.id,)
    ).fetchone()
    conn.close()

    assert row["sent_success"] == 0

    journal.close()


def test_upsert_replaces(tmp_path, sample_signal) -> None:
    db_path = tmp_path / "test_journal.db"
    journal = SignalJournal(db_path)

    journal.record_sent_signal(sample_signal, sent_success=False)
    journal.record_sent_signal(sample_signal, sent_success=True)

    conn = sqlite3.connect(db_path)
    count = conn.execute(
        "SELECT COUNT(*) FROM signals WHERE signal_id = ?", (sample_signal.id,)
    ).fetchone()[0]
    sent = conn.execute(
        "SELECT sent_success FROM signals WHERE signal_id = ?", (sample_signal.id,)
    ).fetchone()[0]
    conn.close()

    assert count == 1
    assert sent == 1

    journal.close()


def test_close_is_safe(tmp_path) -> None:
    db_path = tmp_path / "test_journal.db"
    journal = SignalJournal(db_path)
    journal.close()
    # Second close should not raise
    journal.close()
