# Trading Signal Bot

Lightweight Python bot for MetaTrader 5 that watches market conditions and sends trading signals to Telegram.

## What It Does

- Reads live market data from MT5
- Evaluates strategy rules on closed candles
- Sends BUY/SELL signal alerts to Telegram
- Supports:
  - M15 + M1 strategy flow
  - Optional M1-only mode
  - Chained signal mode (M15 trigger -> M1 confirmations)
  - Signal deduplication and retry queue

## Current Status

- Core bot flow is implemented
- Chained BUY/SELL strategy is implemented
- Summary signals for multiple matches are implemented
- Active validation focus is real-time signal behavior (missed/expected signals)

## Requirements

- Windows machine (MT5 Python integration)
- Python 3.10+
- MetaTrader 5 terminal installed and logged in
- Telegram bot token and target chat ID

## Setup

1. Install Poetry and dependencies:

```powershell
python -m pip install poetry
python -m poetry install
```

2. Create `.env` from template:

```powershell
Copy-Item .env.example .env
```

3. Fill `.env` values:
- `MT5_LOGIN`
- `MT5_PASSWORD`
- `MT5_SERVER`
- `MT5_TERMINAL_PATH` (optional)
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

4. Check config:
- `config/settings.yaml` (default)
- `config/settings.m1_only.yaml` (M1-only enabled)

## Run

Dry run:

```powershell
python -m poetry run trading-signal-bot --dry-run
```

Live:

```powershell
python -m poetry run trading-signal-bot
```

M1-only config:

```powershell
python -m poetry run trading-signal-bot --config config/settings.m1_only.yaml
```

## One-Click Local Launch

If included in your branch/workspace:

```powershell
run_bot_live.bat
```

This runs MT5 preflight checks and then starts the bot with your configured settings.

## Troubleshooting

- If `poetry` is not recognized, use `python -m poetry ...`
- If MT5 initialize fails (`IPC timeout`):
  - keep MT5 open and connected
  - confirm `.env` login/server matches active MT5 account
  - enable MT5 API in `Tools -> Options -> Expert Advisors`
- If only startup message appears in Telegram:
  - bot is running, but strategy conditions are not met yet

## Project Layout

```text
src/trading_signal_bot/
  main.py
  strategy.py
  mt5_client.py
  telegram_notifier.py
  settings.py
  models.py
  indicators/
  repositories/
config/
tests/
docs/
```

## Documentation

- `docs/Planning.md` - implementation roadmap and branch status
- `docs/TECHNICAL_SPEC.md` - technical behavior and config contracts

