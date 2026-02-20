from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

import requests

from trading_signal_bot.utils import utc_now


class HealthAlerter:
    """Sends throttled health alerts via Telegram.

    Events are throttled per event type to prevent spam.
    Uses a separate method from signal delivery so health messages
    can be prefixed with [HEALTH].
    """

    def __init__(
        self,
        token: str,
        chat_id: str,
        throttle_minutes: int = 15,
        timeout_seconds: int = 15,
        enabled: bool = True,
        dry_run: bool = False,
        session: requests.Session | None = None,
    ) -> None:
        self._token = token
        self._chat_id = chat_id
        self._throttle = timedelta(minutes=throttle_minutes)
        self._timeout = timeout_seconds
        self._enabled = enabled
        self._dry_run = dry_run
        self._session = session or requests.Session()
        self._logger = logging.getLogger(self.__class__.__name__)
        self._last_sent: dict[str, datetime] = {}
        self._startup_time = utc_now()
        self._signals_sent: int = 0
        self._errors_count: int = 0

    def alert(self, event_type: str, message: str) -> bool:
        """Send a health alert if not throttled.

        Args:
            event_type: Category key for throttling (e.g. "mt5_disconnect").
            message: Human-readable message body.

        Returns:
            True if the alert was sent or throttled (no error).
        """
        if not self._enabled:
            return True

        now = utc_now()
        last = self._last_sent.get(event_type)
        if last is not None and (now - last) < self._throttle:
            self._logger.debug("health alert throttled: %s", event_type)
            return True

        text = f"[HEALTH] {message}"
        ok = self._send(text)
        if ok:
            self._last_sent[event_type] = now
        return ok

    def on_startup(self) -> bool:
        """Alert that the bot has started."""
        return self.alert("startup", "Bot started")

    def on_shutdown(self, reason: str) -> bool:
        """Alert that the bot is shutting down."""
        return self.alert("shutdown", f"Bot shutting down: {reason}")

    def on_mt5_disconnect(self, reconnect_ok: bool) -> bool:
        """Alert on MT5 disconnect event."""
        status = "reconnected" if reconnect_ok else "reconnect FAILED"
        return self.alert("mt5_disconnect", f"MT5 disconnected — {status}")

    def on_consecutive_failures(self, count: int) -> bool:
        """Alert when consecutive loop failures exceed threshold."""
        return self.alert(
            "consecutive_failures",
            f"{count} consecutive loop failures",
        )

    def on_heartbeat_missed(self, last_eval_utc: datetime | None) -> bool:
        """Alert when no signal evaluation occurred for >30 min during session."""
        if last_eval_utc is not None:
            gap = utc_now() - last_eval_utc
            msg = f"No signal evaluation for {int(gap.total_seconds() // 60)} min"
        else:
            msg = "No signal evaluation recorded yet"
        return self.alert("heartbeat_missed", msg)

    def record_signal_sent(self) -> None:
        """Increment daily signal counter."""
        self._signals_sent += 1

    def record_error(self) -> None:
        """Increment daily error counter."""
        self._errors_count += 1

    def send_daily_summary(self) -> bool:
        """Send a daily summary of signals, errors, and uptime."""
        now = utc_now()
        uptime = now - self._startup_time
        hours = uptime.total_seconds() / 3600
        msg = (
            f"Daily summary\n"
            f"Signals sent: {self._signals_sent}\n"
            f"Errors: {self._errors_count}\n"
            f"Uptime: {hours:.1f}h"
        )
        ok = self.alert("daily_summary", msg)
        # Reset counters after summary
        self._signals_sent = 0
        self._errors_count = 0
        return ok

    def _send(self, text: str) -> bool:
        if self._dry_run:
            self._logger.info("DRY RUN health alert: %s", text)
            return True

        url = f"https://api.telegram.org/bot{self._token}/sendMessage"
        payload = {
            "chat_id": self._chat_id,
            "text": text,
            "disable_web_page_preview": True,
        }
        try:
            response = self._session.post(url, json=payload, timeout=self._timeout)
            if response.status_code == 200:
                body: dict[str, Any] = {}
                try:
                    body = response.json()
                except Exception:
                    pass
                if body.get("ok") is True:
                    return True
            self._logger.warning("health alert send failed: status=%s", response.status_code)
            return False
        except requests.RequestException as exc:
            self._logger.warning("health alert send error: %s", exc)
            return False
