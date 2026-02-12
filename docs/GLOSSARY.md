# Glossary
# Trading Signal Bot

## Trading Terms

| Term | Definition |
|---|---|
| **XAUUSD** | Gold vs US Dollar. Commodity pair. |
| **NAS100** | Nasdaq 100 index. US tech stock index. |
| **EURUSD** | Euro vs US Dollar. Major forex pair. |
| **GBPJPY** | British Pound vs Japanese Yen. Cross pair. |
| **M15** | 15-minute chart timeframe. Each candle = 15 minutes of price data. |
| **M1** | 1-minute chart timeframe. Each candle = 1 minute of price data. |
| **OHLC** | Open, High, Low, Close. The four price points of a candle bar. |
| **Candle / Bar** | A single unit of price data for a timeframe (e.g., one M15 bar = 15 min of trading). |
| **Closed bar** | A candle whose timeframe has completed. Safe to use for decisions (no more data changes). |
| **Forming bar** | The current, incomplete candle still receiving new price data. Not used in this system. |
| **Bullish** | Price trending upward. In this system: LWMA 200 > LWMA 350. |
| **Bearish** | Price trending downward. In this system: LWMA 200 < LWMA 350. |
| **Order flow** | The prevailing market direction as determined by LWMA alignment. |
| **Oversold** | Stochastic in buy zone (10-20). Price may reverse upward. |
| **Overbought** | Stochastic in sell zone (80-90). Price may reverse downward. |
| **Cross (crossover)** | When one line crosses above or below another line. E.g., %K crosses above %D. |
| **Pip** | Smallest price movement unit. For EURUSD: 0.0001. For XAUUSD: 0.01. |
| **Lot size** | Trade volume unit in forex. Not used in this system (alert-only). |
| **Session** | Trading time zones: London (08:00-16:00 UTC), New York (13:00-21:00 UTC), Asia (00:00-08:00 UTC). |

## Technical Indicator Terms

| Term | Definition |
|---|---|
| **LWMA** | Linear Weighted Moving Average. Weights recent prices more heavily. Weights = [1, 2, 3, ..., period]. |
| **LWMA 200 (fast)** | LWMA with period 200. Responds faster to price changes. |
| **LWMA 350 (slow)** | LWMA with period 350. Responds slower, shows longer-term trend. |
| **Stochastic Oscillator** | Momentum indicator comparing close price to its range over a period. Ranges 0-100. |
| **%K (main line / red)** | The primary stochastic line. Calculated from raw stochastic smoothed with LWMA. |
| **%D (signal line / black)** | The signal line. LWMA of %K. Used for cross detection. |
| **Slowing** | Smoothing applied to raw %K before it becomes the main %K line. Period = 10 in this system. |
| **Close/Close** | Stochastic price field mode. Uses close prices for both range calculation and current value (not high/low). |
| **Buy zone** | Stochastic range [10, 20]. Indicates oversold conditions. |
| **Sell zone** | Stochastic range [80, 90]. Indicates overbought conditions. |

## System / Architecture Terms

| Term | Definition |
|---|---|
| **MT5** | MetaTrader 5. Trading platform with Python API for fetching market data. |
| **Telegram Bot API** | Messaging API used to send trade alerts to a Telegram chat. |
| **Signal** | A trade alert generated when strategy conditions are met: either dual-timeframe M15+M1 scenarios (S1/S2) or optional M1-only scenarios (`BUY_M1`/`SELL_M1`) when enabled. |
| **Scenario S1** | Signal confirmed by M15 stochastic cross + M1 stochastic cross (both stochastic). |
| **Scenario S2** | Signal confirmed by M15 stochastic cross + M1 LWMA cross (stochastic + LWMA). |
| **Lazy evaluation** | M1 data is only fetched when M15 conditions pass. Saves unnecessary API calls. |
| **Smart sleep** | Bot calculates time until next M15 close and sleeps until then, instead of constant polling. |
| **Dual-key dedup** | Two-layer duplicate prevention: idempotency key (exact match) + cooldown key (time-based). |
| **Idempotency key** | (symbol, direction, scenario, m15_bar_time). Prevents exact same signal from firing twice. |
| **Cooldown key** | (symbol, direction). Suppresses same-direction alerts for 15 minutes regardless of scenario. |
| **Restart replay** | On startup, bot replays last 3 closed M15 bars to catch signals missed during downtime. |
| **Look-ahead bias** | Using future data in decisions. Prevented by slicing data up to the evaluation bar only. |
| **Atomic write** | Writing to a temp file then renaming. Prevents corrupt state if process crashes mid-write. |
| **Symbol alias** | User-friendly name (e.g., XAUUSD) mapped to broker-specific name (e.g., XAUUSDm). |
| **Dry-run mode** | `--dry-run` flag that prints signals to console without sending Telegram alerts. |
| **Failed signal queue** | JSON file storing signals that failed Telegram delivery. Retried on next loop iteration. |
| **Exponential backoff** | Retry delay doubles each attempt (1s, 2s, 4s, 8s...). Used for MT5 reconnection. |
| **Jitter** | Random delay (0-500ms) added to backoff to avoid synchronized retries. |

## File Terms

| Term | Definition |
|---|---|
| **settings.yaml** | Main config file. Contains symbols, indicator params, timeframes, execution settings. |
| **.env** | Environment file with secrets (MT5 credentials, Telegram token). Gitignored. |
| **dedup_state.json** | Persisted dedup keys and cooldown timestamps. Survives bot restarts. |
| **failed_signals.json** | Queue of signals that failed Telegram delivery. Max 50 entries. |
| **bot.log** | Rotating log file (5MB, 3 backups). Records all evaluations, signals, errors. |

## Acronyms

| Acronym | Full Form |
|---|---|
| DFD | Data Flow Diagram |
| ERD | Entity Relationship Diagram |
| PRD | Product Requirements Document |
| LWMA | Linear Weighted Moving Average |
| OHLC | Open, High, Low, Close |
| UTC | Coordinated Universal Time |
| API | Application Programming Interface |
| VPS | Virtual Private Server |
| SLO | Service Level Objective |
| FIFO | First In, First Out |
| DST | Daylight Saving Time |
