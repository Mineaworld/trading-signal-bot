# Entity Relationship Diagram (ERD)
# Trading Signal Bot

## Overview
This system has no traditional database. All data is either in-memory (runtime) or persisted to JSON/YAML files. This ERD documents the logical data entities, their attributes, and relationships as they exist in code and state files.

---

## Entity Diagram

```
+---------------------------+       +---------------------------+
|         Symbol            |       |       Timeframe           |
+---------------------------+       +---------------------------+
| alias: str [PK]           |       | name: str [PK]            |
| broker_symbol: str [UK]   |       | mt5_constant: int         |
| is_tradable: bool          |       | minutes: int              |
+---------------------------+       +---------------------------+
        |                                    |
        | 1                                  | 1
        |                                    |
        | *                                  | *
+-------------------------------------------------------+
|                    CandleBar                           |
+-------------------------------------------------------+
| symbol_alias: str [FK -> Symbol]                       |
| timeframe: str [FK -> Timeframe]                       |
| time_utc: datetime [PK]                                |
| open: float                                            |
| high: float                                            |
| low: float                                             |
| close: float                                           |
| tick_volume: int                                       |
+-------------------------------------------------------+
        |
        | * (computed from)
        |
        v 1
+-------------------------------------------------------+
|                 IndicatorSnapshot                       |
+-------------------------------------------------------+
| symbol_alias: str                                      |
| timeframe: str                                         |
| bar_time_utc: datetime                                 |
| lwma_fast: float (period 200)                          |
| lwma_slow: float (period 350)                          |
| stoch_k: float (%K main/red)                           |
| stoch_d: float (%D signal/black)                       |
+-------------------------------------------------------+
        |
        | * (evaluated into)
        |
        v 1
+-------------------------------------------------------+
|                      Signal                            |
+-------------------------------------------------------+
| id: str [PK] (hash)                                   |
| symbol: str [FK -> Symbol.alias]                       |
| direction: enum (BUY | SELL)                           |
| scenario: enum (BUY_S1|BUY_S2|SELL_S1|SELL_S2)        |
| price: float                                           |
| created_at_utc: datetime                               |
| m15_bar_time_utc: datetime                             |
| m1_bar_time_utc: datetime                              |
| m15_lwma_fast: float                                   |
| m15_lwma_slow: float                                   |
| m15_stoch_k: float                                     |
| m15_stoch_d: float                                     |
| m1_lwma_fast: float [nullable]                         |
| m1_lwma_slow: float [nullable]                         |
| m1_stoch_k: float [nullable]                           |
| m1_stoch_d: float [nullable]                           |
+-------------------------------------------------------+
        |                          |
        | 1                        | 1
        |                          |
        v *                        v *
+-----------------------+  +-----------------------+
|   DedupIdempotency    |  |    DedupCooldown      |
+-----------------------+  +-----------------------+
| key: str [PK]          |  | key: str [PK]          |
|   (symbol+direction+   |  |   (symbol+direction)   |
|    scenario+m15_bar)   |  |                        |
| signal_id: str [FK]    |  | last_emitted_utc:      |
| recorded_at_utc:       |  |   datetime             |
|   datetime             |  | cooldown_minutes: int  |
+-----------------------+  +-----------------------+

+-----------------------+
|   FailedSignalQueue   |
+-----------------------+
| index: int [PK]        |
| signal: Signal [FK]    |
| failed_at_utc:         |
|   datetime             |
| retry_count: int       |
| last_error: str        |
+-----------------------+
```

---

## Relationships

| Relationship | Type | Description |
|---|---|---|
| Symbol -> CandleBar | 1:N | One symbol has many candle bars across timeframes |
| Timeframe -> CandleBar | 1:N | One timeframe contains many bars per symbol |
| CandleBar -> IndicatorSnapshot | N:1 | Many bars are used to compute one indicator snapshot (rolling window) |
| IndicatorSnapshot -> Signal | N:1 | M15 + M1 indicator snapshots produce one signal (or none) |
| Signal -> DedupIdempotency | 1:N | One signal creates one idempotency record. Prevents exact re-fire. |
| Signal -> DedupCooldown | 1:N | One signal updates one cooldown record. Prevents same-direction spam. |
| Signal -> FailedSignalQueue | 1:1 | A signal enters the queue only if Telegram delivery fails all retries |

---

## Persistence Model

| Entity | Storage | Lifecycle |
|---|---|---|
| Symbol | `config/settings.yaml` | Static - loaded at startup, immutable during runtime |
| Timeframe | Hardcoded in code | Static - M15 and M1 only |
| CandleBar | In-memory (pd.DataFrame) | Transient - fetched fresh each evaluation cycle from MT5 |
| IndicatorSnapshot | In-memory | Transient - computed per evaluation, attached to Signal if emitted |
| Signal | In-memory -> Telegram | Transient - created, sent, then discarded. Only persisted via dedup records. |
| DedupIdempotency | `data/dedup_state.json` | Persistent - survives restarts. Atomic file writes. |
| DedupCooldown | `data/dedup_state.json` | Persistent - entries expire after cooldown_minutes. Pruned on load. |
| FailedSignalQueue | `data/failed_signals.json` | Persistent - entries removed after successful retry. Max 50 entries. |

---

## Data Volume Estimates

| Entity | Volume per cycle | Notes |
|---|---|---|
| CandleBar (M15) | 4 symbols x 450 bars = 1,800 rows | Fetched every M15 close (~96 cycles/day) |
| CandleBar (M1) | 0-4 symbols x 450 bars = 0-1,800 rows | Only fetched when M15 conditions pass |
| Signal | 0-4 per cycle | Most cycles produce 0 signals |
| DedupIdempotency | ~50-200 entries | Grows slowly, can be pruned weekly |
| DedupCooldown | 4-8 entries max | One per (symbol, direction) combination |
| FailedSignalQueue | 0-50 entries | Usually 0 unless Telegram is down |
