from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import requests

from trading_signal_bot.models import Scenario, Signal
from trading_signal_bot.utils import atomic_write_json, read_json, utc_now

PHNOM_PENH_TZ = ZoneInfo("Asia/Phnom_Penh")


class TelegramNotifier:
    def __init__(
        self,
        token: str,
        chat_id: str,
        failed_queue_file: Path,
        max_queue: int = 50,
        max_retries: int = 3,
        max_failed_retry_count: int = 12,
        timeout_seconds: int = 15,
        dry_run: bool = False,
        session: requests.Session | None = None,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._queue_file = failed_queue_file
        self._max_queue = max_queue
        self._max_retries = max_retries
        self._max_failed_retry_count = max_failed_retry_count
        self._timeout = timeout_seconds
        self._dry_run = dry_run
        self._session = session or requests.Session()
        self._logger = logging.getLogger(self.__class__.__name__)

        self._queue_file.parent.mkdir(parents=True, exist_ok=True)
        if not self._queue_file.exists():
            atomic_write_json(self._queue_file, [])

    def send_signal(self, signal: Signal) -> bool:
        if self._dry_run:
            self._logger.info(
                "DRY RUN signal: %s %s %s",
                signal.symbol,
                signal.direction.value,
                signal.scenario.value,
            )
            return True

        message = self._format_signal_html(signal)
        ok, error = self._send_message_with_retry(message)
        if ok:
            return True

        self._logger.error(
            "telegram send failed, queueing signal %s: %s",
            signal.id,
            error,
        )
        self._enqueue_failed(signal, error or "unknown")
        return False

    def send_startup_message(self) -> bool:
        if self._dry_run:
            self._logger.info("DRY RUN startup check")
            return True
        content = "Trading Signal Bot\nstartup check passed"
        ok, _ = self._send_message_with_retry(content)
        return ok

    def retry_failed_queue(self) -> int:
        items = self._load_queue()
        if not items:
            return 0

        sent_count = 0
        new_queue: list[dict[str, Any]] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            current_retry_count = int(item.get("retry_count", 0))
            if current_retry_count >= self._max_failed_retry_count:
                self._logger.error(
                    "dropping failed signal after max retries=%s",
                    self._max_failed_retry_count,
                )
                continue
            payload = item.get("signal")
            if not isinstance(payload, dict):
                continue
            try:
                signal = Signal.from_dict(payload)
            except Exception:
                continue

            if self._dry_run:
                sent_count += 1
                continue

            ok, error = self._send_message_with_retry(self._format_signal_html(signal))
            if ok:
                sent_count += 1
                continue

            retry_count = int(item.get("retry_count", 0)) + 1
            if retry_count >= self._max_failed_retry_count:
                self._logger.error(
                    "dropping failed signal after max retries=%s",
                    self._max_failed_retry_count,
                )
                continue
            item["retry_count"] = retry_count
            item["failed_at"] = utc_now().isoformat()
            item["last_error"] = error or "unknown"
            new_queue.append(item)

        self._persist_queue(new_queue)
        if sent_count > 0:
            self._logger.info(
                "retried failed queue, sent=%s remaining=%s", sent_count, len(new_queue)
            )
        return sent_count

    def _send_message_with_retry(self, html_message: str) -> tuple[bool, str | None]:
        error: str | None = None
        for attempt in range(1, self._max_retries + 1):
            ok, retry_after, error = self._send_message_once(html_message)
            if ok:
                return (True, None)
            if retry_after is not None:
                time.sleep(retry_after)
                continue
            backoff = min(8, 2 ** (attempt - 1))
            time.sleep(backoff)
        return (False, error)

    def _send_message_once(
        self,
        html_message: str,
    ) -> tuple[bool, int | None, str | None]:
        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": html_message,
            "disable_web_page_preview": True,
        }
        try:
            response = self._session.post(url, json=payload, timeout=self._timeout)
        except requests.RequestException as exc:
            return (False, None, str(exc))

        if response.status_code == 200:
            try:
                parsed = response.json()
            except Exception:
                parsed = {}
            if parsed.get("ok") is True:
                return (True, None, None)
            return (False, None, str(parsed))

        if response.status_code == 429:
            retry_after = _parse_retry_after(response)
            return (
                False,
                retry_after,
                f"rate_limited status=429 retry_after={retry_after}",
            )

        return (
            False,
            None,
            f"status={response.status_code} body={response.text[:200]}",
        )

    def _enqueue_failed(self, signal: Signal, last_error: str) -> None:
        items = self._load_queue()
        items.append(
            {
                "signal": signal.to_dict(),
                "failed_at": utc_now().isoformat(),
                "retry_count": self._max_retries,
                "last_error": last_error,
            }
        )
        if len(items) > self._max_queue:
            items = items[-self._max_queue :]
        self._persist_queue(items)

    def _load_queue(self) -> list[dict[str, Any]]:
        if not self._queue_file.exists():
            return []
        try:
            data = read_json(self._queue_file)
            if not isinstance(data, list):
                raise ValueError("queue root must be list")
            return [x for x in data if isinstance(x, dict)]
        except Exception as exc:
            backup = self._queue_file.with_suffix(self._queue_file.suffix + ".corrupt")
            self._queue_file.replace(backup)
            self._logger.warning(
                "failed queue corrupt, reset file and backed up to %s: %s", backup, exc
            )
            self._persist_queue([])
            return []

    def _persist_queue(self, payload: list[dict[str, Any]]) -> None:
        atomic_write_json(self._queue_file, payload)

    def _format_signal_html(self, signal: Signal) -> str:
        scenario_title = {
            Scenario.BUY_S1: "Scenario 1 (Stoch -> Stoch)",
            Scenario.BUY_S2: "Scenario 2 (Stoch -> LWMA)",
            Scenario.SELL_S1: "Scenario 1 (Stoch -> Stoch)",
            Scenario.SELL_S2: "Scenario 2 (Stoch -> LWMA)",
            Scenario.BUY_M1: "M1-Only (Low Confidence)",
            Scenario.SELL_M1: "M1-Only (Low Confidence)",
        }[signal.scenario]

        display_time = signal.m15_bar_time_utc or signal.m1_bar_time_utc
        local_time = display_time.astimezone(PHNOM_PENH_TZ)
        lines = [
            f"{signal.direction.value} {signal.symbol}",
            scenario_title,
            "",
            f"Price: {signal.price:,.5f}",
            f"Time: {local_time.strftime('%Y-%m-%d %H:%M')} UTC+7",
        ]

        if signal.m15_lwma_fast is not None:
            lines.extend(
                [
                    "",
                    "M15 Indicators:",
                    f"|- LWMA 200: {signal.m15_lwma_fast:,.5f}",
                    f"|- LWMA 350: {signal.m15_lwma_slow:,.5f}",
                    f"|- Stoch %K: {signal.m15_stoch_k:,.2f}",
                    f"|- Stoch %D: {signal.m15_stoch_d:,.2f}",
                ]
            )

        m1_header = (
            "M1 Confirmation:"
            if signal.m15_lwma_fast is not None
            else "M1 Indicators:"
        )
        lines.extend(["", m1_header])

        if signal.m1_stoch_k is not None and signal.m1_stoch_d is not None:
            lines.append(f"|- Stoch %K: {signal.m1_stoch_k:,.2f}")
            lines.append(f"|- Stoch %D: {signal.m1_stoch_d:,.2f}")
        if signal.m1_lwma_fast is not None and signal.m1_lwma_slow is not None:
            lines.append(f"|- LWMA 200: {signal.m1_lwma_fast:,.5f}")
            lines.append(f"|- LWMA 350: {signal.m1_lwma_slow:,.5f}")

        return "\n".join(lines)


def _parse_retry_after(response: requests.Response) -> int:
    fallback = 1
    try:
        body = response.json()
    except Exception:
        return fallback
    params = body.get("parameters")
    if not isinstance(params, dict):
        return fallback
    value = params.get("retry_after")
    if not isinstance(value, int | str):
        return fallback
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return fallback
    return max(1, parsed)
