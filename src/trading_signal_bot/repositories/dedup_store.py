from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from trading_signal_bot.models import Signal
from trading_signal_bot.utils import atomic_write_json, read_json, utc_now


class DedupStore:
    def __init__(self, state_file: Path, cooldown_minutes: int, retention_days: int) -> None:
        self._state_file = state_file
        self._cooldown_minutes = cooldown_minutes
        self._retention_days = retention_days
        self._logger = logging.getLogger(self.__class__.__name__)
        self._lock = threading.Lock()
        self._state = self.load_state()

    def load_state(self) -> dict[str, Any]:
        default: dict[str, dict[str, dict[str, str]]] = {
            "idempotency_keys": {},
            "cooldown_keys": {},
        }
        if not self._state_file.exists():
            self._persist(default)
            return default

        try:
            raw = read_json(self._state_file)
            if not isinstance(raw, dict):
                raise ValueError("state json root must be object")
            idempotency = raw.get("idempotency_keys")
            cooldown = raw.get("cooldown_keys")
            if not isinstance(idempotency, dict) or not isinstance(cooldown, dict):
                raise ValueError("state json missing required key maps")
            state = {"idempotency_keys": idempotency, "cooldown_keys": cooldown}
            self._prune_in_memory(state)
            self._persist(state)
            return state
        except Exception as exc:
            backup = self._state_file.with_suffix(self._state_file.suffix + ".corrupt")
            self._state_file.replace(backup)
            self._logger.warning("dedup state corrupt, backed up to %s: %s", backup, exc)
            self._persist(default)
            return default

    def should_emit(self, signal: Signal) -> bool:
        now = utc_now()
        with self._lock:
            self._prune_in_memory(self._state, now=now)
            if signal.idempotency_key in self._state["idempotency_keys"]:
                return False

            cooldown_entry = self._state["cooldown_keys"].get(signal.cooldown_key)
            if isinstance(cooldown_entry, dict):
                last_emitted = cooldown_entry.get("last_emitted")
                if isinstance(last_emitted, str):
                    ts = datetime.fromisoformat(last_emitted)
                    if (now - ts) < timedelta(minutes=self._cooldown_minutes):
                        return False
            return True

    def record(self, signal: Signal) -> None:
        now = utc_now().isoformat()
        with self._lock:
            self._state["idempotency_keys"][signal.idempotency_key] = {
                "signal_id": signal.id,
                "recorded_at": now,
            }
            self._state["cooldown_keys"][signal.cooldown_key] = {"last_emitted": now}
            self._prune_in_memory(self._state)
            self._persist(self._state)

    def _persist(self, payload: dict[str, Any]) -> None:
        atomic_write_json(self._state_file, payload)

    def _prune_in_memory(self, state: dict[str, Any], now: datetime | None = None) -> None:
        current = now or utc_now()
        expiry = current - timedelta(days=self._retention_days)
        idempotency = state.get("idempotency_keys", {})
        if isinstance(idempotency, dict):
            expired_keys: list[str] = []
            for key, value in idempotency.items():
                if not isinstance(value, dict):
                    expired_keys.append(key)
                    continue
                recorded_at = value.get("recorded_at")
                if not isinstance(recorded_at, str):
                    expired_keys.append(key)
                    continue
                try:
                    ts = datetime.fromisoformat(recorded_at)
                except ValueError:
                    expired_keys.append(key)
                    continue
                if ts < expiry:
                    expired_keys.append(key)
            for key in expired_keys:
                idempotency.pop(key, None)

        cooldown = state.get("cooldown_keys", {})
        if isinstance(cooldown, dict):
            remove: list[str] = []
            for key, value in cooldown.items():
                if not isinstance(value, dict):
                    remove.append(key)
                    continue
                last_emitted = value.get("last_emitted")
                if not isinstance(last_emitted, str):
                    remove.append(key)
                    continue
                try:
                    ts = datetime.fromisoformat(last_emitted)
                except ValueError:
                    remove.append(key)
                    continue
                if (current - ts) >= timedelta(minutes=self._cooldown_minutes):
                    remove.append(key)
            for key in remove:
                cooldown.pop(key, None)
