# Trading Signal Bot - MT5 + Telegram

## Summary
A synchronous single-process Python bot that monitors XAUUSD, NAS100, EURUSD, GBPJPY on M15+M1 timeframes, applies a dual-timeframe LWMA + Stochastic strategy using only closed bars, and sends buy/sell alerts to Telegram. Optimized for production reliability: strict bar alignment, dual-key dedup, restart replay, symbol alias mapping, and hardened failure handling.

## Architecture Decisions (Locked)
- Primary goal: reliability over speed.
- Runtime model: synchronous single-process loop.
- Evaluation policy: evaluate only on each new closed M15 candle. On M15 close, check M15 conditions; if pass, check M1 once using latest closed M1 bar at that moment. No M1 polling loop.
- Indicator and cross policy: use only fully closed bars (`iloc[-2]` current closed, `iloc[-3]` previous closed for cross checks).
- M1 confirmation alignment: M1 bar must fall within triggering M15 window (`m15_prev_close < m1_bar_time <= m15_current_close`). Stale M1 from earlier M15 periods rejected.
- All timestamps normalized to UTC immediately after MT5 fetch.
- Market tradability: determined by MT5 `symbol_info().trade_mode`, not weekend-only logic. Single source of truth.
- Alert-only - no auto-trading orders placed.

---

## v1 - Signal Bot

### Project Structure
```text
trading-signal-bot/
+-- config/
|   +-- settings.yaml
|   +-- .env.example
+-- data/                            # runtime state (gitignored)
|   +-- dedup_state.json             # dual-key dedup persistence
|   +-- failed_signals.json          # Telegram retry queue
+-- logs/                            # rotating logs (gitignored)
+-- src/
|   +-- main.py
|   +-- mt5_client.py
|   +-- strategy.py
|   +-- telegram_notifier.py
|   +-- models.py
|   +-- utils.py
|   +-- indicators/
|   |   +-- __init__.py
|   |   +-- lwma.py
|   |   +-- stochastic.py
|   +-- repositories/
|       +-- dedup_store.py
+-- tests/
|   +-- unit/
|   |   +-- test_lwma.py
|   |   +-- test_stochastic.py
|   |   +-- test_strategy.py
|   |   +-- test_dedup_store.py
|   |   +-- test_replay.py
|   +-- integration/
|       +-- test_mt5_client_resilience.py
|       +-- test_notifier_retry.py
+-- .gitignore                       # data/, logs/, .env, __pycache__/
+-- requirements.txt
+-- README.md
```

### Public Interfaces and Types

#### `models.py`
- `Direction`: `BUY | SELL`
- `Scenario`: `BUY_S1 | BUY_S2 | SELL_S1 | SELL_S2 | BUY_M1 | SELL_M1`
- `Signal` dataclass:
  - `id: str` (UUIDv4 hex)
  - `symbol`, `direction`, `scenario`, `price`, `created_at_utc`
  - `m15_bar_time_utc`, `m1_bar_time_utc`
  - `m15_lwma_fast`, `m15_lwma_slow`, `m15_stoch_k`, `m15_stoch_d`
  - `m1_lwma_fast`, `m1_lwma_slow`, `m1_stoch_k`, `m1_stoch_d` (Optional - populated based on scenario)

#### `mt5_client.py`
- `connect() -> bool`, `disconnect()`, `is_connected() -> bool`
- `reconnect()` - exponential backoff with jitter, up to configured retries per cycle; returns failure to caller if still down.
- `fetch_candles(symbol, timeframe, count) -> pd.DataFrame` - **UTC normalization** immediately after `mt5.copy_rates_from_pos()`: `df['time'] = pd.to_datetime(df['time'], unit='s', utc=True)`
- `get_current_price(symbol) -> float | None`
- `validate_symbol_aliases(alias_map: dict[str, str]) -> dict[str, bool]` - accepts alias-to-broker mapping from config, returns validation result per alias.
- `is_symbol_tradable(symbol) -> bool` - checks `mt5.symbol_info(symbol).trade_mode`. Single source of truth for market open/closed.
- **Symbol resolution**: accepts alias (e.g. `XAUUSD`), maps to broker symbol (e.g. `XAUUSDm`) via config. All logs/alerts use alias, all MT5 calls use broker symbol.

#### `strategy.py`
- `m15_requires_m1(m15_df, m15_close_time_utc) -> bool`
- `evaluate(m15_df, m1_df, symbol, m15_close_time_utc, price=None) -> Signal | None`
- `evaluate_m1_only(m1_df, symbol, price=None) -> Signal | None`
- Deterministic priority: `BUY_S1 > BUY_S2 > SELL_S1 > SELL_S2`
- **M1 time window constraint**: `m15_prev_close < m1_bar_time <= m15_current_close`

#### `repositories/dedup_store.py`
- `load_state() -> dict`
- `should_emit(signal) -> bool` - checks BOTH keys
- `record(signal) -> None`
- Atomic persistence (temp file + replace)
- State corruption fallback: backup file + reset with warning log

#### `telegram_notifier.py`
- `send_signal(signal) -> bool` - HTML-formatted, retry max 3, respect `RetryAfter`
- **Failed signal retry queue**: signals that fail all 3 retries queued to `data/failed_signals.json`. Retried on next loop iteration. Max 50 entries, oldest dropped.
- `send_startup_message() -> bool` - test message on boot to validate token + chat_id

#### `utils.py`
- `setup_logging()` - log to **both console and rotating file** (`logs/bot.log`, 5MB max, 3 backups)
- `load_yaml_config()` - load YAML config
- `seconds_until_next_m15_close()` - for smart sleep

### Strategy Rules
- Preconditions:
  - Sufficient bars for all indicators and cross checks (`max(350, stoch windows) + safety buffer`).
  - No NaN on bars used for decision.
- Bar indexing:
  - Decision bar = last fully closed bar.
  - Cross uses two fully closed bars only.
- **BUY S1** (M15 Stoch -> M1 Stoch):
  1. M15 `LWMA200 > LWMA350` (bullish order flow)
  2. M15 `%K in [10,20]`
  3. M15 `%K` crosses above `%D`
  4. M1 `%K` crosses above `%D` - must be within current M15 window
  5. M1 `%K in [10,20]`
- **BUY S2** (M15 Stoch -> M1 LWMA):
  1. M15 `LWMA200 > LWMA350` (bullish order flow)
  2. M15 `%K in [10,20]`
  3. M15 `%K` crosses above `%D`
  4. M1 `LWMA200` crosses above `LWMA350` - must be within current M15 window
- **SELL S1** (M15 Stoch -> M1 Stoch):
  1. M15 `LWMA200 < LWMA350` (bearish order flow)
  2. M15 `%K in [80,90]`
  3. M15 `%K` crosses below `%D`
  4. M1 `%K` crosses below `%D` - must be within current M15 window
  5. M1 `%K in [80,90]`
- **SELL S2** (M15 Stoch -> M1 LWMA):
  1. M15 `LWMA200 < LWMA350` (bearish order flow)
  2. M15 `%K in [80,90]`
  3. M15 `%K` crosses below `%D`
  4. M1 `LWMA200` crosses below `LWMA350` - must be within current M15 window

### Indicator Specs
- **LWMA**: periods 200 (fast) and 350 (slow), method: Linear Weighted, apply to: Close
- **Stochastic**: %K period: 30, %D period: 10, Slowing: 10, Price field: **Close/Close** (`raw_k = (close - lowest_close) / (highest_close - lowest_close) * 100`), smoothing method: LWMA. Buy zone: [10,20], Sell zone: [80,90].
- Division-by-zero guard: flat market -> raw_k = 50.0 (neutral)

### Scheduling and Main Loop
- **Smart sleep**: calculate seconds until next M15 candle close, sleep until then.
- On M15 close: check M15 conditions -> if pass -> fetch M1 -> check latest closed M1 bar **once**. No M1 polling loop.
- M1 candles fetched only after M15 preconditions pass (lazy evaluation).
- Candle count default: 450 (350 LWMA + stochastic warmup + cross safety).
- Sequential symbol processing for predictable behavior and easier recovery.
- **`--dry-run` flag**: print signals to console only, no Telegram. For testing.

### Dual-Key Signal Dedup
Persisted to `data/dedup_state.json`. Signal blocked if EITHER key matches:
- `idempotency_key = (symbol, direction, scenario, bar_time)` where `bar_time = m15_bar_time_utc` (primary flow) or fallback `m1_bar_time_utc` (M1-only flow)
- `cooldown_key = (symbol, direction)` - suppresses same direction for 15 min regardless of scenario/bar

### Startup Sequence
1. **Self-check**: verify MT5 connection, resolve all symbol aliases to broker symbols via `validate_symbol_aliases()` (hard-fail if any missing), validate Telegram token (send test message). Fail fast with clear error.
2. **Restart replay**: fetch last 3 closed M15 bars per symbol. For each replayed bar, **slice data up to and including that bar only** - no future data visible. Run strategy on each slice. Any signal found -> send alert (dedup still applies). Catches signals missed during downtime (~45 min lookback max).
3. Retry any failed signals from `data/failed_signals.json`.
4. Enter normal loop.

### Edge Cases Handled
| Case | Handling |
|---|---|
| Market closed / not tradable | `mt5.symbol_info().trade_mode` check per symbol. Single source of truth. |
| MT5 connection drop | Reconnect w/ exponential backoff + jitter, max configured retries; if still down, current symbol is skipped and loop continues |
| Insufficient bars (<350) | Skip symbol, log warning (expected first ~6hrs Monday) |
| NaN in decision bars | Skip evaluation, log warning |
| Division by zero (stoch) | raw_k = 50.0 (neutral) |
| Duplicate signals | Dual-key dedup: idempotency + cooldown, persisted to JSON |
| Stale M1 confirmation | Rejected - M1 bar must fall within current M15 window |
| Telegram down | 3 retries -> queue to failed_signals.json -> retry next loop |
| Telegram rate limit | Retry with `retry_after` delay |
| Conflicting buy/sell | First-match-wins priority order |
| Bot restart / missed candles | Replay last 3 closed M15 bars (data sliced to prevent look-ahead) |
| Broker symbol mismatch | Alias mapping in config, hard-fail if symbol not found |
| Timezone / DST issues | All MT5 timestamps normalized to UTC immediately after fetch |
| Dedup state corruption | Backup file + reset with warning log |

### Config Contract (`settings.yaml`)
```yaml
symbols:
  XAUUSD: "XAUUSD"        # alias: broker_symbol
  NAS100: "NAS100"         # change broker_symbol to match your broker
  EURUSD: "EURUSD"
  GBPJPY: "GBPJPY"

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
    buy_zone: [10, 20]
    sell_zone: [80, 90]

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
  max_failed_retry_count: 12
  request_timeout_seconds: 15

m1_only:
  enabled: false
```

### Environment Contract (`.env.example`)
```
MT5_LOGIN=
MT5_PASSWORD=
MT5_SERVER=
MT5_TERMINAL_PATH=
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
```

### Test Plan and Acceptance Criteria
- **Unit tests**:
  - LWMA known values, warmup NaN behavior, cross detection on closed bars.
  - Stochastic flat-market (`raw_k=50`), Close/Close mode, boundary zones.
  - Strategy scenario triggering, strict priority ordering, stale M1 rejection.
  - Time alignment tests preventing M1 look-ahead past M15 close.
  - Dedup store: dual-key checks, atomic write/read, corruption recovery.
- **Replay tests** (`test_replay.py`):
  - Replay 3 bars with sliced data: verify no future data visible during each replayed bar evaluation.
  - Replay produces signal -> dedup prevents duplicate send for already-alerted bar.
  - Replay with no missed signals -> no alerts sent (dedup blocks all).
- **Integration tests** (mock MT5 and Telegram):
  - Reconnect after disconnect, no crash, processing resumes.
  - Rate-limit retry honors delay and eventually sends or fails predictably.
  - Failed signal queue: persist, reload, retry on next loop.
- **Acceptance**:
  - No duplicate alert for same scenario and M15 bar across restart.
  - No signal emitted with incomplete or NaN decision bars.
  - Bot survives MT5 outage and recovers automatically.
  - Restart replay catches missed signals within 45-min window without look-ahead.
  - Stale M1 confirmations rejected (verified in logs).
  - Both BUY and SELL scenarios enforce LWMA trend filter symmetrically.

### Verification Checklist
1. `pytest tests/` - all unit + integration + replay tests pass
2. Run with `--dry-run` - verify signal detection prints to console
3. Connect to MT5 demo account, verify candle fetching + UTC normalization
4. Verify symbol alias resolution (change a broker symbol in config)
5. Verify `symbol_info().trade_mode` correctly gates evaluation
6. Create Telegram bot via BotFather, set token + chat_id
7. Run bot live, observe `logs/bot.log` for signal detection
8. Verify Telegram message format and delivery
9. Kill and restart bot - verify dedup persists AND restart replay triggers without look-ahead
10. Verify stale M1 confirmations rejected (check logs)
11. Validate first 50 alerts manually against chart candles

### Rollout Plan
1. Local dry run with `--dry-run` flag.
2. Demo account run during active market session.
3. Validate first 50 alerts manually against chart candles.
4. Enable continuous run with log monitoring.

---

## v2 - Backtester (after v1 is complete)

### Context
Validate the strategy on historical data before trusting it with real capital. Reuses ~70% of v1 code (indicators, strategy, models). No live connections needed - just loop through historical bars. **Cost: $0** - MT5 historical data is free. **Difficulty: 5/10** (v1 is 7/10).

Recommended workflow:
- First run a **time-based P&L backtest** to quickly rank signal quality.
- Then run an **SL/TP backtest** for realistic go/no-go decisions.

### New Files
```text
src/
+-- backtester/
|   +-- __init__.py
|   +-- engine.py              # main backtest loop
|   +-- data_loader.py         # fetch historical candles from MT5
|   +-- trade_recorder.py      # record simulated trades + results
|   +-- report.py              # generate stats + charts
tests/
+-- unit/
    +-- test_backtester.py
```

### Reused from v1 (no changes needed)
- `src/indicators/lwma.py` - same LWMA calculation
- `src/indicators/stochastic.py` - same Stochastic calculation
- `src/strategy.py` - same dual-timeframe signal logic
- `src/models.py` - same Signal, Direction, Scenario classes
- `src/mt5_client.py` - same fetch_candles (just fetching more bars)
- `config/settings.yaml` - same indicator params

### Implementation Steps

#### Step 1: `data_loader.py` - Historical data fetch
- `load_historical(symbol, timeframe, start_date, end_date)` -> DataFrame
- Fetch from MT5 via `mt5.copy_rates_range()` - free historical data
- UTC normalize (same as v1), symbol alias resolution (same as v1)
- Cache fetched data to CSV in `data/backtest/` to avoid re-fetching

#### Step 2: `engine.py` - Backtest loop
- Walk through M15 bars chronologically (oldest -> newest)
- For each M15 bar: slice corresponding M1 bars within that M15 window
- Run `strategy.evaluate()` - exact same v1 logic
- If signal -> pass to trade_recorder
- No dedup in backtest - record every signal for analysis
- CLI: `--symbol XAUUSD --start 2025-01-01 --end 2025-12-31` or `--all`

#### Step 3: `trade_recorder.py` - Trade simulation
- Record each signal: symbol, direction, scenario, entry price, timestamp
- **Phase A (time-based P&L):** measure price movement N bars after signal (configurable: 5, 15, 30, 60 M1 bars)
- **Phase B (SL/TP model):** simulate fixed or ATR-based stop-loss/take-profit exits and record which level is hit first
- Track: entry price, exit price, pips gained/lost
- Store results in DataFrame

#### Step 4: `report.py` - Stats & charts
- **Console output**: total signals, win rate, avg pips, per-pair breakdown, per-scenario (S1 vs S2), per-session (London/NY/Asia), best/worst day
- **Charts** (saved to `data/backtest/charts/`): equity curve, signal heatmap (hour x day), win rate by pair, S1 vs S2 comparison

#### Step 5: CLI entry point
- `python -m src.backtester --symbol XAUUSD --start 2025-06-01 --end 2025-12-31`
- `python -m src.backtester --all --start 2025-01-01 --end 2025-12-31`

### Additional dependency
```
matplotlib>=3.7.0
```

### Verification
1. Run **time-based** backtest on 1 month XAUUSD - verify signals match chart visually
2. Run **time-based** backtest on 6 months - rank symbols/scenarios by quality
3. Run **SL/TP** backtest on the best candidates from phase A
4. Compare S1 vs S2 performance and pair-level performance under SL/TP
5. Spot-check 5 random signals/trades against MT5 chart

---

## Future (v3+ ideas, not in scope)
- Parameter optimization (test different LWMA/Stoch values via backtest)
- Health-check ping to uptime monitor
- Auto-execution via MT5 (risky, needs careful design)
- Multi-chat Telegram support (different groups per symbol)
- Numeric SLOs (learn real numbers from v1 runtime first)
- Dedicated 1-minute polling loop for M1-only signals (currently tied to M15 cycle)

### M1-Only Signals (Implemented - Low-Confidence, Experimental)
M1-only signals without M15 confirmation. Lower confidence than the dual-timeframe
M15+M1 strategy — use for awareness only, not primary trade decisions.
Gated by `m1_only.enabled` config (default: `false`).

**Currently runs on the M15 cycle** (every 15 minutes), checking the last closed M1
bar. A dedicated 1-minute loop would catch more crosses but requires architectural
changes (separate thread/scheduler) — planned for future iteration.

**SELL (M1-only):**
1. M1 LWMA200 crosses below LWMA350 (bearish LWMA cross)
2. M1 Stochastic %K in sell zone [80,90]

**BUY (M1-only):**
1. M1 LWMA200 crosses above LWMA350 (bullish LWMA cross)
2. M1 Stochastic %K in buy zone [10,20]

**Implementation notes:**
- New scenarios: `BUY_M1` / `SELL_M1` (separate from existing S1/S2)
- Tag alerts clearly as "M1-only (Low Confidence)" in Telegram message
- Uses same dedup pipeline (idempotency key falls back to `m1_bar_time_utc`)
- No M15 precondition check needed — evaluates M1 LWMA cross + stoch zone independently
- **Risk:** much higher noise/false signal rate since no higher-timeframe filter
