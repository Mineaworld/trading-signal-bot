"""Tests for v2 engine integration (run_backtest + backward compat)."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import patch

import pandas as pd

from backtester.config import BacktestConfig, ExitMode, SignalMode
from backtester.engine import BacktestResult, run_backtest, run_time_based_backtest
from trading_signal_bot.models import Direction, IndicatorParams, Scenario, Signal
from trading_signal_bot.settings import RiskContextConfig
from trading_signal_bot.strategy import StrategyEvaluator

UTC = timezone.utc

PARAMS = IndicatorParams(
    lwma_fast=5,
    lwma_slow=10,
    stoch_k=8,
    stoch_d=3,
    stoch_slowing=3,
    buy_zone=(0, 20),
    sell_zone=(80, 100),
)

RISK_CONFIG = RiskContextConfig(
    enabled=True,
    atr_period=14,
    atr_stop_multiplier=1.0,
    rr_targets=(2.0, 3.0),
)


def _make_ohlc(closes: list[float], start: str, freq: str) -> pd.DataFrame:
    times = pd.date_range(start=start, periods=len(closes), freq=freq, tz="UTC")
    return pd.DataFrame(
        {
            "time": times,
            "open": closes,
            "high": [c + 0.5 for c in closes],
            "low": [c - 0.5 for c in closes],
            "close": closes,
            "tick_volume": [100] * len(closes),
        }
    )


def _make_signal(bar_time: datetime | None = None) -> Signal:
    bt = bar_time or datetime(2026, 2, 11, 14, 29, tzinfo=UTC)
    return Signal(
        id="sig-test",
        symbol="XAUUSD",
        direction=Direction.BUY,
        scenario=Scenario.BUY_S1,
        price=100.0,
        created_at_utc=bt,
        m1_bar_time_utc=bt,
        m15_bar_time_utc=datetime(2026, 2, 11, 14, 30, tzinfo=UTC),
        risk_invalidation_price=98.0,
        risk_tp1_price=104.0,
        risk_tp2_price=106.0,
    )


class TestRunBacktest:
    """V2 run_backtest integration."""

    def test_legacy_scan_sltp_exit(self) -> None:
        """Full pipeline: legacy scan -> sltp exit -> result."""
        sig = _make_signal()
        strategy = StrategyEvaluator(params=PARAMS)
        m15 = _make_ohlc([100.0] * 20, "2026-02-11T10:00", "15min")
        m1 = _make_ohlc([100.0] * 300, "2026-02-11T10:00", "1min")

        config = BacktestConfig(
            symbol="XAUUSD",
            mode=SignalMode.LEGACY,
            exit_mode=ExitMode.SLTP,
            rr1=2.0,
        )

        with patch("backtester.engine.scan_signals", return_value=[sig]):
            result = run_backtest(
                strategy=strategy,
                symbol="XAUUSD",
                m15_df=m15,
                m1_df=m1,
                config=config,
                indicator_params=PARAMS,
                risk_config=RISK_CONFIG,
            )

        assert isinstance(result, BacktestResult)
        assert result.config is config
        assert len(result.signals) == 1

    def test_empty_data_returns_empty(self) -> None:
        strategy = StrategyEvaluator(params=PARAMS)
        config = BacktestConfig(symbol="XAUUSD")
        result = run_backtest(
            strategy=strategy,
            symbol="XAUUSD",
            m15_df=pd.DataFrame(),
            m1_df=pd.DataFrame(),
            config=config,
            indicator_params=PARAMS,
        )
        assert result.signals == []
        assert result.trades == []
        assert result.config is config


class TestRunTimeBasedBacktestCompat:
    """V1 backward compat remains unchanged."""

    def test_backward_compat_empty(self) -> None:
        strategy = StrategyEvaluator(params=PARAMS)
        result = run_time_based_backtest(
            strategy=strategy,
            symbol="XAUUSD",
            m15_df=pd.DataFrame(),
            m1_df=pd.DataFrame(),
        )
        assert result.signals == []
        assert result.trades == []

    def test_backward_compat_returns_backtest_result(self) -> None:
        strategy = StrategyEvaluator(params=PARAMS)
        m15 = _make_ohlc([100.0] * 20, "2026-02-11T10:00", "15min")
        m1 = _make_ohlc([100.0] * 300, "2026-02-11T10:00", "1min")
        result = run_time_based_backtest(
            strategy=strategy,
            symbol="XAUUSD",
            m15_df=m15,
            m1_df=m1,
            hold_minutes=15,
        )
        assert isinstance(result, BacktestResult)
        # config should be None for v1 path
        assert result.config is None
