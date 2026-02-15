# Data Flow Diagram (DFD)
# Trading Signal Bot

## Level 0 - Context Diagram

```
+------------------+         OHLC Candles          +---------------------+
|                  | <---------------------------- |                     |
|   MetaTrader 5   |         Price Ticks           |                     |
|   (Broker API)   | <---------------------------- |                     |
|                  |         Symbol Info            |   Trading Signal    |
+------------------+ ----------------------------> |       Bot           |
                                                   |                     |
                                                   |                     |
+------------------+         Trade Alerts          |                     |
|                  | <---------------------------- |                     |
|    Telegram      |         Startup Msg           |                     |
|    (Bot API)     | <---------------------------- |                     |
|                  |                               +---------------------+
+------------------+                                        |
                                                           |
+------------------+                                        |
|   Config Files   | -------------------------------------->|
| (YAML + .env)    |       Settings, Credentials
+------------------+

+------------------+
|   Local Files    | <------------------------------------->|
| (JSON state)     |       Dedup State, Failed Queue
+------------------+
```

### External Entities
| Entity | Type | Direction | Data |
|---|---|---|---|
| MetaTrader 5 | Broker API | IN | M15/M1 OHLC candles, price ticks, symbol info |
| Telegram | Messaging API | OUT | Plain-text trade alerts, startup message |
| Config Files | Local filesystem | IN | settings.yaml, .env credentials |
| Local State Files | Local filesystem | IN/OUT | dedup_state.json, failed_signals.json |

---

## Level 1 - Major Processes

```
+-------------+     M15 Candles (450 bars)     +-----------------+
|             | -----------------------------> |                 |
|  1.0 MT5    |     M1 Candles (450 bars)      |  2.0 Indicator  |
|  Data       | -----------------------------> |  Calculator     |
|  Fetcher    |                                |                 |
|             |     Symbol Tradability         +-----------------+
|             | ------+                              |
+-------------+       |                              | LWMA values
      ^               |                              | Stoch %K, %D
      |               v                              v
      |         +-------------+              +-----------------+
  Reconnect     | 5.0 Market  |              |                 |
  on failure    | Gate        |              |  3.0 Strategy   |
      |         | (tradable?) |              |  Evaluator      |
      |         +-------------+              |                 |
      |                                      +-----------------+
+-------------+                                    |
|             |     Signal or None                 |
|  4.0 Dedup  | <----------------------------------+
|  Filter     |
|             |
+-------------+
      |
      | Approved Signal
      v
+-------------+      Plain-text Alert        +-------------+
|             | ---------------------------> |             |
|  6.0 Alert  |         Failed Signal        |  Telegram   |
|  Dispatcher | -------> [retry queue] ----> |  Bot API    |
|             |                              |             |
+-------------+                              +-------------+
```

### Process Descriptions
| Process | Name | Input | Output | Description |
|---|---|---|---|---|
| 1.0 | MT5 Data Fetcher | Symbol alias, timeframe | DataFrame (OHLC, UTC) | Connects to MT5, resolves alias to broker symbol, fetches 450 bars, normalizes timestamps to UTC |
| 2.0 | Indicator Calculator | DataFrame (OHLC) | LWMA(200), LWMA(350), Stoch(%K, %D) | Computes LWMA and Stochastic on closed bars only. Division-by-zero guard for flat markets |
| 3.0 | Strategy Evaluator | M15 indicators, M1 indicators, symbol | Signal list or None | Evaluates scenarios symmetrically and can emit multiple valid scenarios. Enforces M1 time window constraint |
| 4.0 | Dedup Filter | Signal | Approved Signal or blocked | Dual-key check: idempotency + cooldown. Loads/persists state from JSON. Atomic file writes |
| 5.0 | Market Gate | Symbol | Tradable (bool) | Checks `mt5.symbol_info().trade_mode`. Blocks evaluation for closed/non-tradable symbols |
| 6.0 | Alert Dispatcher | Approved Signal | Telegram message sent | Formats plain text, sends via Bot API, retries 3x, queues failures to file for next-loop retry |

---

## Level 2 - Strategy Evaluator Detail

```
                    M15 DataFrame
                         |
                         v
              +---------------------+
              | 3.1 Compute M15     |
              | Indicators          |
              | - LWMA(200, 350)    |
              | - Stoch(%K, %D)     |
              +---------------------+
                         |
                         v
              +---------------------+
              | 3.2 Check M15       |     FAIL -> return None
              | Preconditions       |----------->
              | - LWMA trend?       |
              | - Stoch in zone?    |
              | - Stoch cross?      |
              +---------------------+
                         |
                         | PASS
                         v
              +---------------------+
              | 3.3 Fetch M1 Data   |     (lazy - only if M15 passed)
              | via MT5 Client      |
              +---------------------+
                         |
                         v
              +---------------------+
              | 3.4 Validate M1     |     FAIL -> return None
              | Time Window         |----------->
              | m15_prev < m1 <=    |
              |   m15_current       |
              +---------------------+
                         |
                         | PASS
                         v
              +---------------------+
              | 3.5 Check M1        |     FAIL -> return None
              | Confirmation        |----------->
              | S1: Stoch cross +   |
              |     zone            |
              | S2: LWMA cross      |
              +---------------------+
                         |
                         | PASS
                         v
                  Signal produced
```

---

## Level 2 - Main Loop Detail

```
                  +------------------+
                  |   BOT STARTUP    |
                  +------------------+
                         |
                         v
              +---------------------+
              | S.1 Self-Check      |     FAIL -> exit with error
              | - MT5 connect       |----------->
              | - Validate symbols  |
              | - Telegram test msg |
              +---------------------+
                         |
                         v
              +---------------------+
              | S.2 Restart Replay  |
              | - Last 3 M15 bars   |
              | - Slice data (no    |
              |   look-ahead)       |
              | - Evaluate + dedup  |
              +---------------------+
                         |
                         v
              +---------------------+
              | S.3 Retry Failed    |
              | Signals Queue       |
              +---------------------+
                         |
                         v
        +-------> MAIN LOOP <-------+
        |              |            |
        |              v            |
        |   +------------------+    |
        |   | L.1 Smart Sleep  |    |
        |   | until M15 close  |    |
        |   +------------------+    |
        |              |            |
        |              v            |
        |   +------------------+    |
        |   | L.2 For each     |    |
        |   | symbol:          |    |
        |   | - Check tradable |    |
        |   | - New M15 bar?   |    |
        |   | - Evaluate       |    |
        |   | - Dedup check    |    |
        |   | - Send alert     |    |
        |   +------------------+    |
        |              |            |
        +---< next cycle >----------+
```

---

## Data Stores

| Store | File | Format | Content |
|---|---|---|---|
| D1 - Dedup State | `data/dedup_state.json` | JSON | Idempotency keys + cooldown timestamps. Atomic write (temp + rename). Backup on corruption. |
| D2 - Failed Queue | `data/failed_signals.json` | JSON | Serialized Signal objects that failed Telegram delivery. Max 50 entries. FIFO eviction. |
| D3 - Config | `config/settings.yaml` | YAML | Symbol aliases, indicator params, timeframes, execution settings, logging config |
| D4 - Secrets | `config/.env` | Dotenv | MT5 credentials, Telegram bot token + chat ID |
| D5 - Logs | `logs/bot.log` | Text | Rotating log file (5MB, 3 backups). All evaluations, signals, errors, skips. |
