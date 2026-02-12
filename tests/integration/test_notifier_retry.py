from __future__ import annotations

import requests

from trading_signal_bot.telegram_notifier import TelegramNotifier


class FakeResponse:
    def __init__(self, status_code: int, body: dict | None = None, text: str = "") -> None:
        self.status_code = status_code
        self._body = body or {}
        self.text = text or str(self._body)

    def json(self):
        return self._body


class FakeSession:
    def __init__(self, sequence: list[object]) -> None:
        self._sequence = sequence[:]
        self.calls = 0

    def post(self, url: str, json: dict, timeout: int):
        _ = (url, json, timeout)
        self.calls += 1
        if not self._sequence:
            return FakeResponse(200, {"ok": True})
        item = self._sequence.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def test_send_succeeds_first_try(tmp_path, sample_signal, monkeypatch) -> None:
    monkeypatch.setattr("trading_signal_bot.telegram_notifier.time.sleep", lambda _: None)
    session = FakeSession([FakeResponse(200, {"ok": True})])
    notifier = TelegramNotifier(
        token="x",
        chat_id="1",
        failed_queue_file=tmp_path / "failed.json",
        session=session,
    )
    assert notifier.send_signal(sample_signal) is True
    assert session.calls == 1


def test_send_succeeds_on_retry(tmp_path, sample_signal, monkeypatch) -> None:
    monkeypatch.setattr("trading_signal_bot.telegram_notifier.time.sleep", lambda _: None)
    session = FakeSession([requests.ConnectionError("down"), FakeResponse(200, {"ok": True})])
    notifier = TelegramNotifier(
        token="x",
        chat_id="1",
        failed_queue_file=tmp_path / "failed.json",
        session=session,
    )
    assert notifier.send_signal(sample_signal) is True
    assert session.calls == 2


def test_all_retries_fail_queues_signal(tmp_path, sample_signal, monkeypatch) -> None:
    monkeypatch.setattr("trading_signal_bot.telegram_notifier.time.sleep", lambda _: None)
    session = FakeSession(
        [
            requests.ConnectionError("x"),
            requests.ConnectionError("x"),
            requests.ConnectionError("x"),
        ]
    )
    notifier = TelegramNotifier(
        token="x",
        chat_id="1",
        failed_queue_file=tmp_path / "failed.json",
        max_retries=3,
        session=session,
    )
    assert notifier.send_signal(sample_signal) is False
    queue = notifier._load_queue()
    assert len(queue) == 1


def test_retry_after_respected(tmp_path, sample_signal, monkeypatch) -> None:
    sleeps: list[int] = []
    monkeypatch.setattr(
        "trading_signal_bot.telegram_notifier.time.sleep", lambda s: sleeps.append(int(s))
    )
    session = FakeSession(
        [
            FakeResponse(429, {"ok": False, "parameters": {"retry_after": 5}}),
            FakeResponse(200, {"ok": True}),
        ]
    )
    notifier = TelegramNotifier(
        token="x",
        chat_id="1",
        failed_queue_file=tmp_path / "failed.json",
        session=session,
    )
    assert notifier.send_signal(sample_signal) is True
    assert 5 in sleeps


def test_queue_retry_succeeds(tmp_path, sample_signal, monkeypatch) -> None:
    monkeypatch.setattr("trading_signal_bot.telegram_notifier.time.sleep", lambda _: None)
    session = FakeSession([FakeResponse(200, {"ok": True})])
    notifier = TelegramNotifier(
        token="x",
        chat_id="1",
        failed_queue_file=tmp_path / "failed.json",
        session=session,
    )
    notifier._persist_queue(
        [
            {
                "signal": sample_signal.to_dict(),
                "failed_at": "2026-01-01T00:00:00+00:00",
                "retry_count": 3,
                "last_error": "x",
            }
        ]
    )
    sent = notifier.retry_failed_queue()
    assert sent == 1
    assert notifier._load_queue() == []


def test_queue_max_size_enforced(tmp_path, sample_signal, monkeypatch) -> None:
    monkeypatch.setattr("trading_signal_bot.telegram_notifier.time.sleep", lambda _: None)
    session = FakeSession([requests.ConnectionError("x")] * 20)
    notifier = TelegramNotifier(
        token="x",
        chat_id="1",
        failed_queue_file=tmp_path / "failed.json",
        max_queue=2,
        max_retries=1,
        session=session,
    )
    notifier.send_signal(sample_signal)
    notifier.send_signal(sample_signal)
    notifier.send_signal(sample_signal)
    assert len(notifier._load_queue()) == 2


def test_failed_queue_drops_after_max_retry_count(tmp_path, sample_signal, monkeypatch) -> None:
    monkeypatch.setattr("trading_signal_bot.telegram_notifier.time.sleep", lambda _: None)
    session = FakeSession([requests.ConnectionError("x")] * 10)
    notifier = TelegramNotifier(
        token="x",
        chat_id="1",
        failed_queue_file=tmp_path / "failed.json",
        max_retries=1,
        max_failed_retry_count=2,
        session=session,
    )
    notifier._persist_queue(
        [
            {
                "signal": sample_signal.to_dict(),
                "failed_at": "2026-01-01T00:00:00+00:00",
                "retry_count": 1,
                "last_error": "x",
            }
        ]
    )
    notifier.retry_failed_queue()
    assert notifier._load_queue() == []
