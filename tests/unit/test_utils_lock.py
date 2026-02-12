from __future__ import annotations

import pytest

from trading_signal_bot.utils import single_instance_lock


def test_single_instance_lock_replaces_stale_lock(tmp_path) -> None:
    lock_file = tmp_path / "bot.lock"
    lock_file.write_text("-1", encoding="utf-8")
    with single_instance_lock(lock_file):
        assert lock_file.exists()
    assert not lock_file.exists()


def test_single_instance_lock_blocks_active_lock(tmp_path) -> None:
    lock_file = tmp_path / "bot.lock"
    with single_instance_lock(lock_file):
        with pytest.raises(RuntimeError):
            with single_instance_lock(lock_file):
                pass
