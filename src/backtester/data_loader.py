from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from trading_signal_bot.models import Timeframe
from trading_signal_bot.mt5_client import MT5Client


@dataclass(frozen=True)
class BacktestRange:
    start: datetime
    end: datetime


def load_historical(
    mt5_client: MT5Client,
    symbol: str,
    timeframe: Timeframe,
    date_range: BacktestRange,
    cache_dir: Path,
) -> pd.DataFrame:
    cache_dir.mkdir(parents=True, exist_ok=True)
    start_utc = _to_utc(date_range.start)
    end_utc = _to_utc(date_range.end)
    cache_key = (
        f"{symbol}_{timeframe.value}_"
        f"{start_utc.strftime('%Y%m%dT%H%M%SZ')}_"
        f"{end_utc.strftime('%Y%m%dT%H%M%SZ')}.csv"
    )
    cache_file = cache_dir / cache_key
    if cache_file.exists():
        df = pd.read_csv(cache_file, parse_dates=["time"])
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], utc=True)
        cached_windowed = df[(df["time"] >= start_utc) & (df["time"] <= end_utc)]
        if not cached_windowed.empty:
            return cached_windowed.reset_index(drop=True)

    print(
        f"[backtest] loading {symbol} {timeframe.value} from MT5 " f"range={start_utc}..{end_utc}",
        flush=True,
    )
    try:
        df = mt5_client.fetch_candles_range(
            symbol=symbol,
            timeframe=timeframe,
            start_utc=start_utc,
            end_utc=end_utc,
        )
    except RuntimeError as exc:
        print(f"[backtest] warning: fetch failed for {symbol} {timeframe.value}: {exc}", flush=True)
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume"])

    df = df.drop_duplicates(subset=["time"]).sort_values("time")
    windowed = df[(df["time"] >= start_utc) & (df["time"] <= end_utc)]
    if windowed.empty and not df.empty:
        loaded_oldest = pd.to_datetime(df["time"].min(), utc=True)
        loaded_newest = pd.to_datetime(df["time"].max(), utc=True)
        print(
            f"[backtest] warning: {symbol} {timeframe.value} window is empty. "
            f"loaded_range={loaded_oldest}..{loaded_newest} requested={start_utc}..{end_utc}",
            flush=True,
        )

    # Only cache non-empty results to prevent poisoning
    if not windowed.empty:
        windowed.to_csv(cache_file, index=False)
    return windowed.reset_index(drop=True)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
