from __future__ import annotations

from datetime import datetime, timedelta, timezone

from trading_signal_bot.repositories.dedup_store import DedupStore
from trading_signal_bot.utils import atomic_write_json

UTC = timezone.utc


def test_new_signal_passes(tmp_path, sample_signal) -> None:
    store = DedupStore(tmp_path / "dedup.json", cooldown_minutes=15, retention_days=14)
    assert store.should_emit(sample_signal) is True


def test_idempotency_blocks_repeat(tmp_path, sample_signal) -> None:
    store = DedupStore(tmp_path / "dedup.json", cooldown_minutes=15, retention_days=14)
    store.record(sample_signal)
    assert store.should_emit(sample_signal) is False


def test_cooldown_expires(tmp_path, sample_signal) -> None:
    path = tmp_path / "dedup.json"
    store = DedupStore(path, cooldown_minutes=15, retention_days=14)
    store.record(sample_signal)
    raw = {
        "idempotency_keys": {},
        "cooldown_keys": {
            sample_signal.cooldown_key: {
                "last_emitted": (datetime.now(tz=UTC) - timedelta(minutes=20)).isoformat()
            }
        },
    }
    atomic_write_json(path, raw)
    reloaded = DedupStore(path, cooldown_minutes=15, retention_days=14)
    assert reloaded.should_emit(sample_signal) is True


def test_corrupt_state_recovery(tmp_path) -> None:
    path = tmp_path / "dedup.json"
    path.write_text("{bad json", encoding="utf-8")
    store = DedupStore(path, cooldown_minutes=15, retention_days=14)
    state = store.load_state()
    assert "idempotency_keys" in state
    assert "cooldown_keys" in state
    assert path.exists()
