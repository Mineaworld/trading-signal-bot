"""Tests for log timezone formatter."""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from trading_signal_bot.utils import _TzFormatter


class TestTzFormatter:
    def test_renders_utc_plus_7(self) -> None:
        """Timestamps should render in Asia/Phnom_Penh (UTC+7)."""
        tz = ZoneInfo("Asia/Phnom_Penh")
        fmt = _TzFormatter(
            fmt="%(asctime)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            tz=tz,
        )
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        # LogRecord.created is a Unix timestamp (float).
        # 2026-02-23 00:00:00 UTC = 2026-02-23 07:00:00 UTC+7
        record.created = 1771804800.0  # 2026-02-23T00:00:00Z
        formatted = fmt.formatTime(record, "%Y-%m-%d %H:%M:%S")
        assert formatted == "2026-02-23 07:00:00"

    def test_renders_utc_by_default(self) -> None:
        """UTC timezone should render unchanged."""
        tz = ZoneInfo("UTC")
        fmt = _TzFormatter(
            fmt="%(asctime)s | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
            tz=tz,
        )
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello",
            args=(),
            exc_info=None,
        )
        record.created = 1771804800.0  # 2026-02-23T00:00:00Z
        formatted = fmt.formatTime(record, "%Y-%m-%d %H:%M:%S")
        assert formatted == "2026-02-23 00:00:00"
