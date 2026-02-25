from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

from trading_signal_bot.models import Timeframe
from trading_signal_bot.mt5_client import MT5Client

# MT5 brokers limit how much data copy_rates_range can return in one call.
# Chunk large requests into smaller windows to avoid "Invalid params" errors.
_CHUNK_DAYS = {
    Timeframe.M1: 30,
    Timeframe.M15: 180,
}


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

    df = _fetch_chunked(mt5_client, symbol, timeframe, start_utc, end_utc)

    if df.empty:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume"])

    df = df.drop_duplicates(subset=["time"]).sort_values("time")
    windowed = df[(df["time"] >= start_utc) & (df["time"] <= end_utc)]

    # Only cache non-empty results to prevent poisoning
    if not windowed.empty:
        windowed.to_csv(cache_file, index=False)
    return windowed.reset_index(drop=True)


def _fetch_chunked(
    mt5_client: MT5Client,
    symbol: str,
    timeframe: Timeframe,
    start_utc: datetime,
    end_utc: datetime,
) -> pd.DataFrame:
    """Fetch data in chunks to avoid MT5 broker limits on copy_rates_range."""
    chunk_days = _CHUNK_DAYS.get(timeframe, 180)
    chunk_delta = timedelta(days=chunk_days)

    chunks: list[pd.DataFrame] = []
    chunk_start = start_utc
    chunk_num = 0

    while chunk_start < end_utc:
        chunk_end = min(chunk_start + chunk_delta, end_utc)
        chunk_num += 1
        print(
            f"[backtest] loading {symbol} {timeframe.value} "
            f"chunk {chunk_num}: {chunk_start.date()}..{chunk_end.date()}",
            flush=True,
        )
        try:
            chunk_df = mt5_client.fetch_candles_range(
                symbol=symbol,
                timeframe=timeframe,
                start_utc=chunk_start,
                end_utc=chunk_end,
            )
            chunks.append(chunk_df)
        except RuntimeError as exc:
            print(
                f"[backtest] warning: chunk failed for {symbol} {timeframe.value} "
                f"{chunk_start.date()}..{chunk_end.date()}: {exc}",
                flush=True,
            )
        chunk_start = chunk_end + timedelta(seconds=1)

    if not chunks:
        return pd.DataFrame(columns=["time", "open", "high", "low", "close", "tick_volume"])
    return pd.concat(chunks, ignore_index=True)


def _to_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
