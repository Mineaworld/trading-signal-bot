from __future__ import annotations

from datetime import datetime, timezone

import pandas as pd
import pytest

from trading_signal_bot.models import Direction, IndicatorParams, Scenario, Signal
from trading_signal_bot.strategy import StrategyEvaluator

UTC = timezone.utc


def _make_m1_df(periods: int, start: str) -> pd.DataFrame:
    times = pd.date_range(start=start, periods=periods, freq="1min", tz="UTC")
    close = [100.0 + i for i in range(periods)]
    return pd.DataFrame(
        {
            "time": times,
            "open": close,
            "high": [x + 0.5 for x in close],
            "low": [x - 0.5 for x in close],
            "close": close,
            "tick_volume": [1 for _ in close],
        }
    )


def _params() -> IndicatorParams:
    return IndicatorParams(
        lwma_fast=2,
        lwma_slow=3,
        stoch_k=3,
        stoch_d=2,
        stoch_slowing=1,
        buy_zone=(10, 20),
        sell_zone=(80, 90),
    )


def _patch_m1_indicators(
    monkeypatch: pytest.MonkeyPatch,
    m1_fast: list[float],
    m1_slow: list[float],
    m1_k: list[float],
    m1_d: list[float],
) -> None:
    import trading_signal_bot.strategy as strategy_module

    def fake_lwma(series: pd.Series, period: int) -> pd.Series:
        data = m1_fast if period == 2 else m1_slow
        return pd.Series(data, index=series.index, dtype=float)

    def fake_stoch(
        close: pd.Series, k_period: int, d_period: int, slowing: int
    ) -> tuple[pd.Series, pd.Series]:
        _ = (k_period, d_period, slowing)
        return (
            pd.Series(m1_k, index=close.index, dtype=float),
            pd.Series(m1_d, index=close.index, dtype=float),
        )

    monkeypatch.setattr(strategy_module, "calculate_lwma", fake_lwma)
    monkeypatch.setattr(strategy_module, "calculate_stochastic", fake_stoch)


def test_buy_m1_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    """BUY_M1 fires when M1 LWMA crosses above and stoch in buy zone."""
    m1 = _make_m1_df(10, "2026-02-11 15:00:00")
    # LWMA fast crosses above slow at last bar
    m1_fast = [1.0] * 10
    m1_slow = [1.0] * 10
    m1_fast[8] = 1.0  # prev: fast <= slow
    m1_fast[9] = 1.3  # curr: fast > slow  -> crossed above
    m1_slow[8] = 1.1
    m1_slow[9] = 1.2
    # Stoch K in buy zone at last bar
    m1_k = [50.0] * 10
    m1_d = [50.0] * 10
    m1_k[9] = 15.0
    m1_d[9] = 12.0

    _patch_m1_indicators(monkeypatch, m1_fast, m1_slow, m1_k, m1_d)
    evaluator = StrategyEvaluator(_params())
    signal = evaluator.evaluate_m1_only(m1_df=m1, symbol="XAUUSD")

    assert signal is not None
    assert signal.direction == Direction.BUY
    assert signal.scenario == Scenario.BUY_M1
    assert signal.m15_bar_time_utc is None
    assert signal.m15_lwma_fast is None
    assert signal.m1_lwma_fast is not None
    assert signal.m1_stoch_k is not None


def test_sell_m1_signal(monkeypatch: pytest.MonkeyPatch) -> None:
    """SELL_M1 fires when M1 LWMA crosses below and stoch in sell zone."""
    m1 = _make_m1_df(10, "2026-02-11 15:00:00")
    m1_fast = [1.0] * 10
    m1_slow = [1.0] * 10
    m1_fast[8] = 1.3  # prev: fast >= slow
    m1_fast[9] = 1.0  # curr: fast < slow  -> crossed below
    m1_slow[8] = 1.2
    m1_slow[9] = 1.1
    m1_k = [50.0] * 10
    m1_d = [50.0] * 10
    m1_k[9] = 85.0
    m1_d[9] = 88.0

    _patch_m1_indicators(monkeypatch, m1_fast, m1_slow, m1_k, m1_d)
    evaluator = StrategyEvaluator(_params())
    signal = evaluator.evaluate_m1_only(m1_df=m1, symbol="EURUSD")

    assert signal is not None
    assert signal.direction == Direction.SELL
    assert signal.scenario == Scenario.SELL_M1
    assert signal.m15_bar_time_utc is None


def test_m1_only_no_signal_without_cross(monkeypatch: pytest.MonkeyPatch) -> None:
    """No signal when stoch is in zone but LWMA doesn't cross."""
    m1 = _make_m1_df(10, "2026-02-11 15:00:00")
    # LWMA parallel - no cross
    m1_fast = [1.2] * 10
    m1_slow = [1.0] * 10
    m1_k = [15.0] * 10
    m1_d = [12.0] * 10

    _patch_m1_indicators(monkeypatch, m1_fast, m1_slow, m1_k, m1_d)
    evaluator = StrategyEvaluator(_params())
    signal = evaluator.evaluate_m1_only(m1_df=m1, symbol="XAUUSD")

    assert signal is None


def test_m1_only_no_signal_without_zone(monkeypatch: pytest.MonkeyPatch) -> None:
    """No signal when LWMA crosses but stoch not in zone."""
    m1 = _make_m1_df(10, "2026-02-11 15:00:00")
    m1_fast = [1.0] * 10
    m1_slow = [1.0] * 10
    m1_fast[8] = 1.0
    m1_fast[9] = 1.3
    m1_slow[8] = 1.1
    m1_slow[9] = 1.2
    # Stoch at 50 - not in any zone
    m1_k = [50.0] * 10
    m1_d = [50.0] * 10

    _patch_m1_indicators(monkeypatch, m1_fast, m1_slow, m1_k, m1_d)
    evaluator = StrategyEvaluator(_params())
    signal = evaluator.evaluate_m1_only(m1_df=m1, symbol="XAUUSD")

    assert signal is None


def test_m1_only_insufficient_bars(monkeypatch: pytest.MonkeyPatch) -> None:
    """No signal when insufficient bars for indicator calculation."""
    m1 = _make_m1_df(3, "2026-02-11 15:00:00")
    m1_fast = [1.0, 1.0, 1.3]
    m1_slow = [1.0, 1.1, 1.2]
    m1_k = [15.0, 15.0, 15.0]
    m1_d = [12.0, 12.0, 12.0]

    _patch_m1_indicators(monkeypatch, m1_fast, m1_slow, m1_k, m1_d)
    evaluator = StrategyEvaluator(_params())
    signal = evaluator.evaluate_m1_only(m1_df=m1, symbol="XAUUSD")

    # With lwma_slow=3 and stoch_k=3, need at least max(3,3)+2=5 bars
    assert signal is None


def test_m1_only_signal_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    """Verify M1-only signal has correct field values."""
    m1 = _make_m1_df(10, "2026-02-11 15:00:00")
    m1_fast = [1.0] * 10
    m1_slow = [1.0] * 10
    m1_fast[8] = 1.0
    m1_fast[9] = 1.3
    m1_slow[8] = 1.1
    m1_slow[9] = 1.2
    m1_k = [50.0] * 10
    m1_d = [50.0] * 10
    m1_k[9] = 15.0
    m1_d[9] = 12.0

    _patch_m1_indicators(monkeypatch, m1_fast, m1_slow, m1_k, m1_d)
    evaluator = StrategyEvaluator(_params())
    signal = evaluator.evaluate_m1_only(m1_df=m1, symbol="XAUUSD", price=2345.50)

    assert signal is not None
    assert signal.symbol == "XAUUSD"
    assert signal.price == 2345.50
    assert signal.m15_bar_time_utc is None
    assert signal.m15_lwma_fast is None
    assert signal.m15_lwma_slow is None
    assert signal.m15_stoch_k is None
    assert signal.m15_stoch_d is None
    assert signal.m1_lwma_fast == 1.3
    assert signal.m1_lwma_slow == 1.2
    assert signal.m1_stoch_k == 15.0
    assert signal.m1_stoch_d == 12.0
    assert signal.m1_bar_time_utc is not None
    assert isinstance(signal.m1_bar_time_utc, datetime)
    assert signal.id != ""
    assert isinstance(signal.created_at_utc, datetime)
    # Idempotency key falls back to m1_bar_time_utc when m15 is None
    assert signal.symbol in signal.idempotency_key
    assert signal.scenario.value in signal.idempotency_key


def test_m1_only_idempotency_key_uses_m1_bar_time() -> None:
    """M1-only idempotency key uses m1_bar_time_utc when m15_bar_time_utc is None."""
    signal = Signal(
        id="sig-m1-1",
        symbol="XAUUSD",
        direction=Direction.BUY,
        scenario=Scenario.BUY_M1,
        price=2345.50,
        created_at_utc=datetime(2026, 2, 11, 14, 30, 5, tzinfo=UTC),
        m1_bar_time_utc=datetime(2026, 2, 11, 14, 29, 0, tzinfo=UTC),
        m1_lwma_fast=1.3,
        m1_lwma_slow=1.2,
        m1_stoch_k=15.0,
        m1_stoch_d=12.0,
    )

    assert signal.idempotency_key == "XAUUSD|BUY|BUY_M1|2026-02-11T14:29:00Z"

    # Different m1 bar times produce different keys
    signal2 = Signal(
        id="sig-m1-2",
        symbol="XAUUSD",
        direction=Direction.BUY,
        scenario=Scenario.BUY_M1,
        price=2346.00,
        created_at_utc=datetime(2026, 2, 11, 14, 31, 0, tzinfo=UTC),
        m1_bar_time_utc=datetime(2026, 2, 11, 14, 30, 0, tzinfo=UTC),
        m1_lwma_fast=1.3,
        m1_lwma_slow=1.2,
        m1_stoch_k=15.0,
        m1_stoch_d=12.0,
    )

    assert signal.idempotency_key != signal2.idempotency_key


def test_m1_only_telegram_formatting(m1_only_signal: Signal) -> None:
    """M1-only Telegram message excludes M15 section and uses correct titles."""
    from pathlib import Path

    from trading_signal_bot.telegram_notifier import TelegramNotifier

    notifier = TelegramNotifier(
        token="fake",
        chat_id="fake",
        failed_queue_file=Path("/tmp/test_queue.json"),
        dry_run=True,
    )
    text = notifier._format_signal_text(m1_only_signal)

    assert "M1-Only (Low Confidence)" in text
    assert "M15 Indicators:" not in text
    assert "M1 Confirmation:" not in text
    assert "M1 Indicators:" in text
    assert "2026-02-11 21:29 UTC+7" in text
    assert "XAUUSD" in text
    assert "#BUY_M1" not in text
