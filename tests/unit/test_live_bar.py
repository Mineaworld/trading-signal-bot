"""Tests for live-bar evaluation feature."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from textwrap import dedent

import pandas as pd

from trading_signal_bot.main import _closed_bars_only, _filter_bars
from trading_signal_bot.models import Direction, Scenario, Signal
from trading_signal_bot.settings import load_yaml_config
from trading_signal_bot.telegram_notifier import TelegramNotifier

UTC = timezone.utc


def _make_df(n: int = 5) -> pd.DataFrame:
    """Create a minimal OHLC dataframe with *n* rows."""
    times = pd.date_range("2026-01-01", periods=n, freq="15min", tz="UTC")
    return pd.DataFrame(
        {
            "time": times,
            "open": range(n),
            "high": range(n),
            "low": range(n),
            "close": range(n),
            "tick_volume": [100] * n,
        }
    )


# --- _filter_bars -----------------------------------------------------------


class TestFilterBars:
    def test_include_forming_returns_full_df(self) -> None:
        df = _make_df(5)
        result = _filter_bars(df, include_forming=True)
        assert len(result) == 5

    def test_exclude_forming_strips_last_row(self) -> None:
        df = _make_df(5)
        result = _filter_bars(df, include_forming=False)
        assert len(result) == 4
        # Should match _closed_bars_only behaviour
        expected = _closed_bars_only(df)
        pd.testing.assert_frame_equal(result, expected)


# --- LiveBarConfig parsing ---------------------------------------------------


class TestLiveBarConfig:
    def test_parsed_from_yaml_with_defaults(self, tmp_path: Path) -> None:
        """LiveBarConfig defaults to enabled=False, poll_interval_seconds=15."""
        yaml_content = dedent(
            """\
            symbols:
              XAUUSD: "XAUUSD"
            timeframes:
              primary: M15
              confirmation: M1
            indicators:
              lwma:
                fast: 200
                slow: 350
              stochastic:
                k: 30
                d: 10
                slowing: 10
                buy_zone: [0, 20]
                sell_zone: [80, 100]
            data:
              candle_buffer: 450
              min_valid_closed_bars: 2
            execution:
              reconnect_max_retries: 5
              reconnect_base_delay_seconds: 1
              reconnect_max_delay_seconds: 30
              loop_failure_sleep_seconds: 60
            signal_dedup:
              cooldown_minutes: 15
              retention_days: 14
              state_file: data/dedup_state.json
            logging:
              level: INFO
              file: logs/bot.log
              max_bytes: 5242880
              backup_count: 3
            telegram:
              failed_queue_file: data/failed_signals.json
              max_queue_size: 50
              max_retries: 3
              request_timeout_seconds: 15
        """
        )
        cfg_file = tmp_path / "settings.yaml"
        cfg_file.write_text(yaml_content, encoding="utf-8")
        config = load_yaml_config(cfg_file)

        assert config.live_bar.enabled is False
        assert config.live_bar.poll_interval_seconds == 15


# --- [LIVE] prefix -----------------------------------------------------------


def _make_signal(is_live: bool) -> Signal:
    now = datetime(2026, 2, 11, 14, 30, 5, tzinfo=UTC)
    return Signal(
        id="sig-live-test",
        symbol="XAUUSD",
        direction=Direction.BUY,
        scenario=Scenario.BUY_S1,
        price=2341.5,
        created_at_utc=now,
        m15_bar_time_utc=datetime(2026, 2, 11, 14, 30, 0, tzinfo=UTC),
        m1_bar_time_utc=datetime(2026, 2, 11, 14, 29, 0, tzinfo=UTC),
        m15_lwma_fast=2338.2,
        m15_lwma_slow=2335.1,
        m15_stoch_k=15.4,
        m15_stoch_d=12.8,
        m1_stoch_k=18.2,
        m1_stoch_d=14.5,
        is_live_bar=is_live,
    )


class TestLiveTag:
    def test_live_prefix_present(self) -> None:
        signal = _make_signal(is_live=True)
        text = TelegramNotifier._format_signal_text(None, signal)  # type: ignore[arg-type]
        assert text.startswith("[LIVE] BUY XAUUSD")

    def test_no_live_prefix(self) -> None:
        signal = _make_signal(is_live=False)
        text = TelegramNotifier._format_signal_text(None, signal)  # type: ignore[arg-type]
        assert text.startswith("BUY XAUUSD")


# --- Signal round-trip -------------------------------------------------------


class TestSignalRoundTrip:
    def test_is_live_bar_round_trip(self) -> None:
        signal = _make_signal(is_live=True)
        payload = signal.to_dict()
        assert payload["is_live_bar"] is True

        restored = Signal.from_dict(payload)
        assert restored.is_live_bar is True

        # False case
        signal_off = _make_signal(is_live=False)
        payload_off = signal_off.to_dict()
        assert payload_off["is_live_bar"] is False
        restored_off = Signal.from_dict(payload_off)
        assert restored_off.is_live_bar is False
