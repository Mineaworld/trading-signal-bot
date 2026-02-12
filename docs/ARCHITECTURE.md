# Architecture Document
# Trading Signal Bot - MT5 + Telegram

## 1. System Architecture

### 1.1 High-Level Architecture

```
+-------------------------------------------------------------------+
|                        Trading Signal Bot                          |
|                    (Single Python Process)                         |
|                                                                   |
|  +------------------+    +------------------+    +-------------+  |
|  |   Presentation   |    |   Application    |    |    Data     |  |
|  |     Layer         |    |     Layer         |    |    Layer    |  |
|  |                  |    |                  |    |             |  |
|  | telegram_notifier|    | main.py (loop)   |    | mt5_client  |  |
|  | (alerts OUT)     |    | strategy.py      |    | (candles IN)|  |
|  |                  |    | indicators/      |    | dedup_store |  |
|  |                  |    |                  |    | utils.py    |  |
|  +------------------+    +------------------+    +-------------+  |
+-------------------------------------------------------------------+
         |                        |                       |
         v                        v                       v
   +-----------+          +---------------+        +-----------+
   | Telegram  |          | Config Files  |        |    MT5    |
   | Bot API   |          | (.yaml, .env) |        | Terminal  |
   +-----------+          +---------------+        +-----------+
```

### 1.2 Layer Responsibilities

| Layer | Components | Responsibility |
|---|---|---|
| **Presentation** | `telegram_notifier.py` | Format signals as HTML, deliver to Telegram, manage retry queue |
| **Application** | `main.py`, `strategy.py`, `indicators/` | Main loop orchestration, strategy evaluation, indicator math |
| **Data** | `mt5_client.py`, `dedup_store.py`, `utils.py` | MT5 connection, candle fetching, dedup persistence, config loading |

### 1.3 Design Principles
- **Single-process synchronous** - no threads, no async. Predictable, debuggable.
- **Closed-bar only** - never use forming candle data. Eliminates look-ahead bias.
- **Fail-safe** - every external call (MT5, Telegram) has retry + fallback. Bot never crashes.
- **Stateless evaluation** - each M15 cycle is self-contained. Only dedup state persists.
- **Lazy fetching** - M1 data fetched only when M15 conditions pass. Minimizes API calls.

---

## 2. Component Architecture

### 2.1 Component Diagram

```
+---------------------------------------------------------------------+
|                            main.py                                   |
|  +------------------+                                                |
|  | Startup Sequence |                                                |
|  | 1. Self-check    |--> mt5_client.connect()                        |
|  | 2. Replay        |--> mt5_client.validate_symbol_aliases()        |
|  | 3. Retry queue   |--> telegram_notifier.send_startup_message()    |
|  | 4. Enter loop    |                                                |
|  +------------------+                                                |
|                                                                      |
|  +------------------+    +----------------+    +-----------------+   |
|  |   Main Loop      |    |                |    |                 |   |
|  |                  |--->| strategy.py    |--->| indicators/     |   |
|  | For each symbol: |    |                |    | lwma.py         |   |
|  | - tradable?      |    | evaluate()     |    | stochastic.py   |   |
|  | - new M15 bar?   |    | _check_buy_s1  |    |                 |   |
|  | - evaluate       |    | _check_buy_s2  |    | calculate_lwma  |   |
|  | - dedup check    |    | _check_sell_s1 |    | lwma_cross      |   |
|  | - send alert     |    | _check_sell_s2 |    | lwma_order      |   |
|  +------------------+    +----------------+    | calc_stochastic |   |
|         |                       ^              | stoch_cross     |   |
|         v                       |              | stoch_in_zone   |   |
|  +------------------+    +------+------+       +-----------------+   |
|  | dedup_store.py   |    | mt5_client  |                             |
|  | should_emit()    |    | fetch_candles|                            |
|  | record()         |    | reconnect() |                             |
|  +------------------+    +-------------+                             |
|         |                                                            |
|         v                                                            |
|  +---------------------+                                             |
|  | telegram_notifier   |                                             |
|  | send_signal()       |                                             |
|  | [retry queue]       |                                             |
|  +---------------------+                                             |
+---------------------------------------------------------------------+
```

### 2.2 Module Dependency Graph

```
main.py
  +-- mt5_client.py
  |     +-- models.py (Timeframe)
  +-- strategy.py
  |     +-- indicators/lwma.py
  |     +-- indicators/stochastic.py
  |     |     +-- indicators/lwma.py (for LWMA smoothing)
  |     +-- models.py (Signal, Direction, Scenario)
  +-- telegram_notifier.py
  |     +-- models.py (Signal)
  +-- repositories/dedup_store.py
  |     +-- models.py (Signal)
  +-- utils.py
        +-- (no internal dependencies)
```

No circular dependencies. All arrows point downward.

---

## 3. Sequence Diagrams

### 3.1 Normal Signal Flow (Happy Path)

```
main.py          mt5_client     strategy      indicators     dedup_store   telegram
  |                  |              |              |              |            |
  |--sleep until---->|              |              |              |            |
  |  M15 close       |              |              |              |            |
  |                  |              |              |              |            |
  |--is_tradable?--->|              |              |              |            |
  |<---true----------|              |              |              |            |
  |                  |              |              |              |            |
  |--fetch M15------>|              |              |              |            |
  |<---DataFrame-----|              |              |              |            |
  |                  |              |              |              |            |
  |--evaluate(m15)------------------>|              |              |            |
  |                  |              |--calc LWMA--->|              |            |
  |                  |              |<--values------|              |            |
  |                  |              |--calc Stoch-->|              |            |
  |                  |              |<--K,D---------|              |            |
  |                  |              |              |              |            |
  |                  |              |--M15 pass?   |              |            |
  |                  |              |  (yes)       |              |            |
  |                  |              |              |              |            |
  |--fetch M1------->|              |              |              |            |
  |<---DataFrame-----|              |              |              |            |
  |                  |              |              |              |            |
  |--evaluate(m15,m1)--------------->|              |              |            |
  |                  |              |--check M1--->|              |            |
  |                  |              |<--confirmed--|              |            |
  |<---Signal--------|--------------|              |              |            |
  |                  |              |              |              |            |
  |--should_emit?--->|              |              |-->check----->|            |
  |<---true----------|              |              |<--true-------|            |
  |                  |              |              |              |            |
  |--record--------->|              |              |-->persist--->|            |
  |                  |              |              |              |            |
  |--send_signal---->|              |              |              |-->send---->|
  |<---success-------|              |              |              |<--200 OK---|
  |                  |              |              |              |            |
```

### 3.2 MT5 Reconnection Flow

```
main.py          mt5_client
  |                  |
  |--fetch_candles-->|
  |                  |--mt5.copy_rates_from_pos()
  |                  |<--ERROR (disconnected)
  |                  |
  |                  |--reconnect()
  |                  |  attempt 1: wait 1s + jitter
  |                  |  mt5.initialize() -> FAIL
  |                  |  attempt 2: wait 2s + jitter
  |                  |  mt5.initialize() -> FAIL
  |                  |  attempt 3: wait 4s + jitter
  |                  |  mt5.initialize() -> SUCCESS
  |                  |
  |<---DataFrame-----|  (retry original fetch)
  |                  |
```

### 3.3 Startup Replay Flow

```
main.py          mt5_client     strategy      dedup_store     telegram
  |                  |              |              |              |
  |--fetch last 3--->|              |              |              |
  |  M15 bars        |              |              |              |
  |<---bars 1,2,3----|              |              |              |
  |                  |              |              |              |
  |  FOR bar_1:      |              |              |              |
  |--slice data----->|              |              |              |
  |  (up to bar_1)   |              |              |              |
  |--evaluate------->|------------->|              |              |
  |<---None----------|              |              |              |
  |                  |              |              |              |
  |  FOR bar_2:      |              |              |              |
  |--slice data----->|              |              |              |
  |  (up to bar_2)   |              |              |              |
  |--evaluate------->|------------->|              |              |
  |<---Signal--------|              |              |              |
  |--should_emit?--->|              |              |-->check----->|
  |<---true----------|              |              |              |
  |--send_signal---->|              |              |              |-->send-->
  |                  |              |              |              |
  |  FOR bar_3:      |              |              |              |
  |  (same flow)     |              |              |              |
  |                  |              |              |              |
  |--ENTER LOOP----->|              |              |              |
```

---

## 4. Error Handling Architecture

```
+------------------------------------------------------------------+
|                    Error Handling Layers                           |
|                                                                  |
|  Layer 1: Per-Call Retry                                          |
|  +------------------------------------------------------------+  |
|  | MT5 fetch_candles  -> RuntimeError -> reconnect (5x backoff)|  |
|  | Telegram send      -> NetworkError -> retry (3x)            |  |
|  | Telegram send      -> RetryAfter   -> wait + retry          |  |
|  +------------------------------------------------------------+  |
|                                                                  |
|  Layer 2: Per-Symbol Skip                                         |
|  +------------------------------------------------------------+  |
|  | Symbol not tradable    -> skip, log info                    |  |
|  | Insufficient bars      -> skip, log warning                 |  |
|  | NaN in decision bars   -> skip, log warning                 |  |
|  | Exception in evaluate  -> skip, log error                   |  |
|  +------------------------------------------------------------+  |
|                                                                  |
|  Layer 3: Persistent Fallback                                     |
|  +------------------------------------------------------------+  |
|  | Telegram fail after 3x -> queue to failed_signals.json      |  |
|  | Dedup state corrupt    -> restore backup, reset, log warning|  |
|  +------------------------------------------------------------+  |
|                                                                  |
|  Layer 4: Process-Level Recovery                                  |
|  +------------------------------------------------------------+  |
|  | MT5 reconnect fails 5x -> sleep 60s, retry entire cycle    |  |
|  | Unhandled exception     -> log critical, continue loop      |  |
|  | Bot never exits on its own (except startup hard-fail)       |  |
|  +------------------------------------------------------------+  |
+------------------------------------------------------------------+
```

---

## 5. Deployment Architecture

```
+--------------------------------------------------+
|              Windows Machine / VPS                 |
|                                                  |
|  +--------------------+  +--------------------+  |
|  |   MetaTrader 5     |  |   Python 3.10+     |  |
|  |   Terminal          |  |   trading-signal-  |  |
|  |   (logged in)      |  |   bot/             |  |
|  |                    |  |   poetry run       |  |
|  |                    |  |   trading-signal-  |  |
|  |                    |  |   bot              |  |
|  +--------------------+  +--------------------+  |
|         ^                        |                |
|         |  localhost IPC         |                |
|         +------------------------+                |
|                                                  |
|  +--------------------+  +--------------------+  |
|  |   config/          |  |   data/             |  |
|  |   settings.yaml    |  |   dedup_state.json  |  |
|  |   .env             |  |   failed_signals.json|  |
|  +--------------------+  +--------------------+  |
|                                                  |
|  +--------------------+                           |
|  |   logs/            |                           |
|  |   bot.log          |                           |
|  +--------------------+                           |
+--------------------------------------------------+
         |
         | HTTPS (outbound only)
         v
+--------------------------------------------------+
|              Telegram Cloud                        |
|              api.telegram.org                      |
+--------------------------------------------------+
```

### 5.1 Deployment Options
| Option | Cost | Reliability | Setup |
|---|---|---|---|
| AWS Lightsail (Windows) | Credit-dependent | High - 24/5 | Low |
| AWS EC2 (Windows) | Credit-dependent | High - 24/5 | Medium |
| Local PC | $0/mo | Low - must stay on | None |
| Contabo VPS | ~$7/mo | High - 24/7 | 1 hour |
| ForexVPS | ~$25/mo | High - MT5 optimized | Minimal |

When AWS credits are available, prefer AWS Windows VPS first. See `docs/AWS_VPS_SETUP.md`.

---

## 6. Technology Stack

| Component | Technology | Version | Purpose |
|---|---|---|---|
| Language | Python | 3.10+ | Core runtime |
| Broker API | MetaTrader5 | >= 5.0.45 | OHLC data, symbol info |
| Indicators | pandas + numpy | >= 2.0, >= 1.24 | LWMA, Stochastic calculation |
| Alerts | requests | >= 2.32 | Telegram Bot API |
| Config | PyYAML | >= 6.0 | Settings file parsing |
| Secrets | python-dotenv | >= 1.0 | .env file loading |
| Testing | pytest | >= 7.0 | Unit + integration tests |
| Charting (v2) | matplotlib | >= 3.7 | Backtest equity curves |
