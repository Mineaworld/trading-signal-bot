# Product Requirements Document (PRD)

# Trading Signal Bot - MT5 + Telegram

## 1. Overview

### 1.1 Product Name

Trading Signal Bot

### 1.2 Version

v1.0

### 1.3 Author

Minea-Trading Bot

### 1.4 Last Updated

2026-02-13

### 1.5 Problem Statement

Manual forex/indices trading requires constant chart monitoring across multiple pairs and timeframes. Traders miss high-probability setups when away from screens, leading to lost opportunities. There is no affordable, customizable alert system that implements a specific dual-timeframe LWMA + Stochastic strategy.

### 1.6 Solution

A Python bot that runs 24/5 during market hours, automatically monitors 4 trading instruments on M15 and M1 timeframes, evaluates a custom technical strategy, and delivers real-time alerts to Telegram when trade setups are detected.

### 1.7 Goals

- Eliminate missed trade setups due to screen absence
- Provide reliable, timely alerts with zero false duplicates
- Survive failures (broker disconnect, Telegram outage, bot restart) gracefully
- Cost $0 to operate (excluding optional VPS)

### 1.8 Non-Goals

- Auto-execution of trades (alert-only in v1)
- Backtesting (deferred to v2)
- Multi-user support
- Web dashboard or GUI

---

## 2. Users and Stakeholders

### 2.1 Primary User

- **Solo forex/indices trader** who trades XAUUSD, NAS100, EURUSD, GBPJPY
- Uses MetaTrader 5 as their trading platform
- Has a defined technical strategy but cannot watch charts 24/5
- Technical enough to run a Python script and configure a Telegram bot

### 2.2 User Persona

| Attribute       | Detail                                       |
| --------------- | -------------------------------------------- |
| Role            | Part-time trader / developer                 |
| Platform        | MetaTrader 5                                 |
| Instruments     | XAUUSD, NAS100, EURUSD, GBPJPY               |
| Trading style   | Intraday, dual-timeframe (M15 + M1)          |
| Pain point      | Missing setups when away from screen         |
| Technical skill | Can run Python scripts, configure .env files |

---

## 3. Functional Requirements

### FR-01: Market Data Ingestion

- **SHALL** connect to MetaTrader 5 via the official Python API
- **SHALL** fetch M15 and M1 OHLC candle data for configured symbols
- **SHALL** normalize all timestamps to UTC immediately after fetch
- **SHALL** resolve symbol aliases to broker-specific symbol names
- **SHALL** fetch 450 bars per request (350 LWMA period + warmup buffer)

### FR-02: Indicator Calculation

- **SHALL** calculate Linear Weighted Moving Average (LWMA) with periods 200 and 350
- **SHALL** calculate Stochastic Oscillator (%K: 30, %D: 10, Slowing: 10) using Close/Close price field and LWMA smoothing
- **SHALL** use only fully closed bars for all calculations (no forming bar data)
- **SHALL** handle division-by-zero in Stochastic by returning neutral value (50.0)

### FR-03: Strategy Evaluation

- **SHALL** evaluate strategy only on new M15 candle close
- **SHALL** check M15 conditions first, fetch M1 only if M15 passes (lazy evaluation)
- **SHALL** check M1 confirmation using the selected M1 candidate inside the active M15 window
- **SHALL** enforce M1 time window: `m15_prev_close < m1_bar_time <= m15_current_close`
- **SHALL** reject stale M1 confirmations from earlier M15 periods
- **SHALL** evaluate BUY and SELL symmetrically (no side prioritization)
- **SHALL** emit all scenarios that pass validation on the selected M1 candidate bar
- **SHALL** require LWMA trend filter on ALL scenarios (both S1 and S2)

### FR-04: Signal Deduplication

- **SHALL** implement dual-key dedup:
  - Idempotency key: (symbol, direction, scenario, m15_bar_time_utc)
  - Cooldown key: (symbol, direction) with 15-minute suppression
- **SHALL** persist dedup state to JSON file (survives restarts)
- **SHALL** handle corrupt dedup state gracefully (backup + reset)

### FR-05: Alert Delivery

- **SHALL** send plain-text alerts to Telegram via Bot API (no HTML tags)
- **SHALL** include: symbol, direction, scenario, price, time, M15 indicators, M1 confirmation
- **SHALL** display alert timestamp in UTC+7
- **SHALL NOT** include hashtags in alert body
- **SHALL** retry failed sends up to 3 times with `RetryAfter` respect
- **SHALL** queue failed signals to file for retry on next loop iteration
- **SHALL** cap failed queue at 50 entries (oldest dropped)

### FR-06: Startup and Recovery

- **SHALL** validate MT5 connection, symbol aliases, and Telegram token on boot
- **SHALL** hard-fail with clear error if any startup check fails
- **SHALL** replay last 3 closed M15 bars on startup (data sliced to prevent look-ahead)
- **SHALL** retry queued failed signals from previous session

### FR-07: Dry Run Mode

- **SHALL** support `--dry-run` CLI flag
- **SHALL** print signals to console without sending Telegram in dry-run mode

### FR-08: Monitoring and Validation (Priority Scope)

- **SHALL** define a heartbeat/uptime monitoring mechanism for production runtime
- **SHALL** define a signal outcome journal model for post-signal performance tracking
- **SHALL** define backtest gate criteria before promoting strategy changes to live alerts

---

## 4. Non-Functional Requirements

### NFR-01: Reliability

- Bot must not crash on MT5 disconnection (auto-reconnect with backoff)
- Bot must not lose signals on Telegram downtime (retry queue)
- Bot must not send duplicate alerts (dual-key dedup)

### NFR-02: Performance

- Smart sleep until next M15 close (no wasteful polling)
- Single M1 check per M15 trigger (no polling loop)
- Sequential symbol processing (predictable, debuggable)

### NFR-03: Observability

- Log to both console and rotating file (5MB, 3 backups)
- Log all signal evaluations, skips, rejections, and errors
- Startup test message to Telegram confirms connectivity

### NFR-04: Configurability

- All parameters in `settings.yaml` (no code changes for tuning)
- Secrets in `.env` file (gitignored)
- Symbol alias mapping for broker portability

### NFR-05: Security

- No credentials in source code or version control
- `.env` and `data/` directories gitignored
- No external network calls except MT5 API and Telegram API

---

## 5. Strategy Specification

### 5.1 Indicators

| Indicator          | Type           | Period | Method          | Apply To    |
| ------------------ | -------------- | ------ | --------------- | ----------- |
| LWMA Fast          | Moving Average | 200    | Linear Weighted | Close       |
| LWMA Slow          | Moving Average | 350    | Linear Weighted | Close       |
| Stochastic %K      | Oscillator     | 30     | LWMA-smoothed   | Close/Close |
| Stochastic %D      | Signal line    | 10     | LWMA of %K      | -           |
| Stochastic Slowing | Smoothing      | 10     | LWMA            | -           |

### 5.2 Zones

| Zone      | Range | Meaning                    |
| --------- | ----- | -------------------------- |
| Buy zone  | 10-20 | Oversold, potential buy    |
| Sell zone | 80-90 | Overbought, potential sell |

### 5.3 Signal Scenarios

**BUY S1** (Stoch -> Stoch confirmation):

1. M15: LWMA200 > LWMA350
2. M15: Stochastic %K in [10,20]
3. M15: %K crosses above %D
4. M1: %K crosses above %D (within M15 window)
5. M1: %K in [10,20]

**BUY S2** (Stoch -> LWMA confirmation):

1. M15: LWMA200 > LWMA350
2. M15: Stochastic %K in [10,20]
3. M15: %K crosses above %D
4. M1: LWMA200 crosses above LWMA350 (within M15 window)

**SELL S1/S2**: Mirror with sell zone [80,90], bearish flow, downward crosses.

---

## 6. Constraints

- Requires Windows OS (MT5 Python API is Windows-only)
- Requires MT5 terminal installed and logged in
- Requires internet connection for MT5 data and Telegram delivery
- M1 LWMA-based signals (S2) unavailable first ~6 hours after Monday market open (insufficient bars)

---

## 7. Success Metrics

| Metric                       | Target                             |
| ---------------------------- | ---------------------------------- |
| Signal delivery latency      | < 10 seconds after M15 close       |
| Duplicate alert rate         | 0%                                 |
| Uptime during market hours   | > 99% (with auto-reconnect)        |
| False signal rate (stale M1) | 0%                                 |
| Manual validation accuracy   | First 50 alerts match chart setups |

---

## 8. Release Plan

| Phase   | Description                                    |
| ------- | ---------------------------------------------- |
| Phase 1 | Local dry-run with `--dry-run` flag            |
| Phase 2 | Demo account run during active market session  |
| Phase 3 | Validate first 50 alerts against chart candles |
| Phase 4 | Continuous run with log monitoring             |

---

## 9. Future Scope (v2+)

- v2: Backtester - validate strategy on historical data using a two-step flow:
  1) time-based P&L ranking, then 2) SL/TP simulation for go/no-go
- v2.1: Signal outcome journal and rolling KPI tracker (win rate, RR, drawdown)
- v2.2: Session filter + market regime filter (e.g., ADX/volatility gate)
- v3: Parameter optimization using backtest results
- v3+: Auto-execution, multi-chat Telegram
