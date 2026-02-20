from __future__ import annotations

import argparse
from datetime import datetime, timedelta
from pathlib import Path

from trading_signal_bot.models import Timeframe
from trading_signal_bot.mt5_client import MT5Client, ReconnectConfig
from trading_signal_bot.settings import load_secrets, load_yaml_config
from trading_signal_bot.strategy import StrategyEvaluator

from .data_loader import BacktestRange, load_historical
from .engine import run_time_based_backtest
from .report import summarize


def main() -> None:
    parser = argparse.ArgumentParser(description="Trading bot backtester")
    parser.add_argument("--config", type=Path, default=Path("config/settings.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--hold-minutes", type=int, default=15)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/backtest"))
    args = parser.parse_args()

    config = load_yaml_config(args.config)
    secrets = load_secrets(args.env)
    mt5_client = MT5Client(
        login=secrets.mt5_login,
        password=secrets.mt5_password,
        server=secrets.mt5_server,
        path=secrets.mt5_terminal_path,
        alias_map=config.symbols,
        reconnect=ReconnectConfig(
            max_retries=config.execution.reconnect_max_retries,
            base_delay_seconds=config.execution.reconnect_base_delay_seconds,
            max_delay_seconds=config.execution.reconnect_max_delay_seconds,
        ),
    )
    if not mt5_client.connect():
        raise RuntimeError("cannot connect to MT5")

    date_range = BacktestRange(
        start=_parse_start_bound(args.start),
        end=_parse_end_bound(args.end),
    )
    m15_df = load_historical(
        mt5_client=mt5_client,
        symbol=args.symbol,
        timeframe=Timeframe.M15,
        date_range=date_range,
        cache_dir=args.cache_dir,
    )
    print("[backtest] M15 load complete", flush=True)
    m1_df = load_historical(
        mt5_client=mt5_client,
        symbol=args.symbol,
        timeframe=Timeframe.M1,
        date_range=date_range,
        cache_dir=args.cache_dir,
    )
    print("[backtest] M1 load complete", flush=True)
    strategy = StrategyEvaluator(
        params=config.indicators,
    )
    result = run_time_based_backtest(
        strategy=strategy,
        symbol=args.symbol,
        m15_df=m15_df,
        m1_df=m1_df,
        hold_minutes=args.hold_minutes,
    )
    print(f"Loaded bars: M15={len(m15_df)} M1={len(m1_df)}")
    print(f"Signals detected: {len(result.signals)}")
    print(f"Trades evaluated: {len(result.trades)}")
    print(summarize(result.trades))


def _parse_start_bound(value: str) -> datetime:
    return datetime.fromisoformat(value)


def _parse_end_bound(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    # If only date is provided, include whole day up to 23:59:59.
    if "T" not in value and " " not in value:
        return parsed + timedelta(days=1) - timedelta(seconds=1)
    return parsed


if __name__ == "__main__":
    main()
