from __future__ import annotations

import json
import logging
import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
from pathlib import Path


def utc_now() -> datetime:
    return datetime.now(tz=timezone.utc)


def seconds_until_next_m15_close(now: datetime | None = None) -> float:
    current = now or utc_now()
    rounded_minute = (current.minute // 15) * 15
    boundary = current.replace(minute=rounded_minute, second=0, microsecond=0) + timedelta(
        minutes=15
    )
    wait = (boundary - current).total_seconds()
    return 1.0 if wait <= 0 else wait


def seconds_until_next_m1_close(now: datetime | None = None) -> float:
    current = now or utc_now()
    boundary = current.replace(second=0, microsecond=0) + timedelta(minutes=1)
    wait = (boundary - current).total_seconds()
    return 1.0 if wait <= 0 else wait


def setup_logging(level: str, file_path: Path, max_bytes: int, backup_count: int) -> logging.Logger:
    file_path.parent.mkdir(parents=True, exist_ok=True)
    formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    root.handlers.clear()

    stream_handler = logging.StreamHandler()
    stream_handler.setFormatter(formatter)
    root.addHandler(stream_handler)

    file_handler = RotatingFileHandler(
        filename=str(file_path),
        maxBytes=max_bytes,
        backupCount=backup_count,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    return root


def atomic_write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    with temp_path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=True, indent=2)
    os.replace(temp_path, path)


def read_json(path: Path) -> object:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


@contextmanager
def single_instance_lock(lock_file: Path) -> Iterator[None]:
    pid = os.getpid()
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_CREAT | os.O_EXCL | os.O_WRONLY
    fd: int | None = None
    for _ in range(2):
        try:
            fd = os.open(str(lock_file), flags)
            break
        except FileExistsError as exc:
            existing_pid = _read_lock_pid(lock_file)
            if existing_pid is not None and not _is_pid_running(existing_pid):
                lock_file.unlink(missing_ok=True)
                continue
            raise RuntimeError(f"lock file already exists: {lock_file}") from exc
    if fd is None:
        raise RuntimeError(f"failed to acquire lock: {lock_file}")

    os.write(fd, str(pid).encode("ascii"))
    try:
        yield
    finally:
        os.close(fd)
        existing_pid = _read_lock_pid(lock_file)
        if existing_pid == pid:
            lock_file.unlink(missing_ok=True)


def _read_lock_pid(lock_file: Path) -> int | None:
    try:
        raw = lock_file.read_text(encoding="utf-8").strip()
    except FileNotFoundError:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


def _is_pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False
    return True
