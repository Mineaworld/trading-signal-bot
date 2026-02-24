from __future__ import annotations

import argparse
import sys
import warnings
from datetime import datetime, timedelta
from pathlib import Path

from trading_signal_bot.models import Timeframe
from trading_signal_bot.mt5_client import MT5Client, ReconnectConfig
from trading_signal_bot.settings import load_secrets, load_yaml_config
from trading_signal_bot.strategy import StrategyEvaluator

from .config import BacktestConfig, ExitMode, SignalMode
from .data_loader import BacktestRange, load_historical
from .engine import run_backtest, run_time_based_backtest
from .report import build_report, export_equity_curve, export_trade_log, format_report, summarize


def main() -> None:
    parser = argparse.ArgumentParser(description="Trading bot backtester")
    parser.add_argument("--config", type=Path, default=Path("config/settings.yaml"))
    parser.add_argument("--env", type=Path, default=Path(".env"))
    parser.add_argument("--symbol", required=True)
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    parser.add_argument("--hold-minutes", type=int, default=15)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/backtest"))

    # v2 flags
    parser.add_argument(
        "--mode",
        type=str,
        choices=[m.value for m in SignalMode],
        default=None,
        help="Signal scan mode (default: legacy)",
    )
    parser.add_argument(
        "--exit-mode",
        type=str,
        choices=[e.value for e in ExitMode],
        default=None,
        help="Exit simulation mode (default: time)",
    )
    parser.add_argument("--sl-mult", type=float, default=None, help="Override ATR stop multiplier")
    parser.add_argument(
        "--rr1", type=float, default=None, help="Override RR1 target (default: 2.0)"
    )
    parser.add_argument(
        "--rr2", type=float, default=None, help="Override RR2 target (analytics only)"
    )
    parser.add_argument("--output-dir", type=Path, default=None, help="CSV export directory (v2b)")

    args = parser.parse_args()

    # Determine if v2 mode is requested
    use_v2 = args.mode is not None or args.exit_mode is not None

    app_config = load_yaml_config(args.config)
    secrets = load_secrets(args.env)
    mt5_client = MT5Client(
        login=secrets.mt5_login,
        password=secrets.mt5_password,
        server=secrets.mt5_server,
        path=secrets.mt5_terminal_path,
        alias_map=app_config.symbols,
        reconnect=ReconnectConfig(
            max_retries=app_config.execution.reconnect_max_retries,
            base_delay_seconds=app_config.execution.reconnect_base_delay_seconds,
            max_delay_seconds=app_config.execution.reconnect_max_delay_seconds,
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

    if use_v2:
        _run_v2(args, app_config, m15_df, m1_df)
    else:
        _run_v1(args, app_config, m15_df, m1_df)


def _run_v1(args: argparse.Namespace, app_config: object, m15_df: object, m1_df: object) -> None:
    """V1 legacy path: legacy scan + time exit."""
    strategy = StrategyEvaluator(
        params=app_config.indicators,  # type: ignore[attr-defined]
    )
    result = run_time_based_backtest(
        strategy=strategy,
        symbol=args.symbol,
        m15_df=m15_df,  # type: ignore[arg-type]
        m1_df=m1_df,  # type: ignore[arg-type]
        hold_minutes=args.hold_minutes,
    )
    print(f"Loaded bars: M15={len(m15_df)} M1={len(m1_df)}")  # type: ignore[arg-type]
    print(f"Signals detected: {len(result.signals)}")
    print(f"Trades evaluated: {len(result.trades)}")
    print(summarize(result.trades))


def _run_v2(args: argparse.Namespace, app_config: object, m15_df: object, m1_df: object) -> None:
    """V2 path: configurable scan mode + exit mode."""
    signal_mode = SignalMode(args.mode) if args.mode else SignalMode.LEGACY
    exit_mode = ExitMode(args.exit_mode) if args.exit_mode else ExitMode.TIME

    risk_config = app_config.risk_context  # type: ignore[attr-defined]

    # Validate exit mode requirements
    if exit_mode in (ExitMode.SLTP, ExitMode.COMBINED):
        if not risk_config.enabled and args.sl_mult is None:
            print(
                f"[backtest] error: --exit-mode {exit_mode.value} requires "
                "risk_context.enabled=True or --sl-mult"
            )
            sys.exit(1)

    if exit_mode is ExitMode.SLTP and args.hold_minutes != 15:
        warnings.warn("--hold-minutes is ignored for SLTP exit mode", stacklevel=2)

    bt_config = BacktestConfig(
        symbol=args.symbol,
        mode=signal_mode,
        exit_mode=exit_mode,
        hold_minutes=args.hold_minutes,
        sl_mult=args.sl_mult,
        rr1=args.rr1,
        rr2=args.rr2,
        output_dir=args.output_dir,
    )

    strategy = StrategyEvaluator(
        params=app_config.indicators,  # type: ignore[attr-defined]
        regime_filter=app_config.regime_filter,  # type: ignore[attr-defined]
        risk_context=risk_config,
    )

    result = run_backtest(
        strategy=strategy,
        symbol=args.symbol,
        m15_df=m15_df,  # type: ignore[arg-type]
        m1_df=m1_df,  # type: ignore[arg-type]
        config=bt_config,
        indicator_params=app_config.indicators,  # type: ignore[attr-defined]
        risk_config=risk_config,
    )

    print(f"Loaded bars: M15={len(m15_df)} M1={len(m1_df)}")  # type: ignore[arg-type]
    print(f"Mode: {signal_mode.value} | Exit: {exit_mode.value}")
    print(f"Signals detected: {len(result.signals)}")
    print(f"Trades evaluated: {len(result.trades)}")

    report = build_report(result.trades)
    print(format_report(report, bt_config))

    if bt_config.output_dir and result.trades:
        out = bt_config.output_dir
        export_equity_curve(result.trades, out / "equity_curve.csv")
        export_trade_log(result.trades, out / "trade_log.csv")
        print(f"CSV exports written to {out}")


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
