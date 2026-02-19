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
    cache_key = f"{symbol}_{timeframe.value}_{date_range.start.date()}_{date_range.end.date()}.csv"
    cache_file = cache_dir / cache_key
    if cache_file.exists():
        df = pd.read_csv(cache_file, parse_dates=["time"])
        if "time" in df.columns:
            df["time"] = pd.to_datetime(df["time"], utc=True)
        if not df.empty:
            return df

    # Pull a wide recent window, then trim to requested bounds.
    start_utc = _to_utc(date_range.start)
    end_utc = _to_utc(date_range.end)
    lookback_minutes = max(1, int((datetime.now(timezone.utc) - start_utc).total_seconds() // 60))
    tf_minutes = 1 if timeframe is Timeframe.M1 else 15
    needed_bars = max(450, (lookback_minutes // tf_minutes) + 2000)
    print(f"[backtest] loading {symbol} {timeframe.value} from MT5 count={needed_bars}", flush=True)
    try:
        df = mt5_client.fetch_candles(symbol=symbol, timeframe=timeframe, count=needed_bars)
    except RuntimeError:
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
    windowed.to_csv(cache_file, index=False)
    return windowed.reset_index(drop=True)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
