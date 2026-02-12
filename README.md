# Trading Signal Bot

Python signal bot for MetaTrader 5 that evaluates a dual-timeframe LWMA + Stochastic strategy and publishes alerts to Telegram.

## Features

- Closed-bar strategy evaluation on M15 with M1 confirmation
- Strict M1 time-window validation to prevent stale confirmations
- Dual-key deduplication persisted to disk
- Telegram retry + failed signal queue persistence
- Startup replay for the last 3 closed M15 candles
- `--dry-run` mode for safe validation

## Project Layout

```text
src/trading_signal_bot/
  main.py
  mt5_client.py
  strategy.py
  telegram_notifier.py
  settings.py
  models.py
  ports.py
  indicators/
  repositories/
tests/
config/settings.yaml
.env.example
```

## Prerequisites

- Windows machine (MT5 Python bridge requirement)
- Python 3.10+
- MetaTrader 5 terminal installed and logged in
- Telegram bot token and chat id

## Setup

1. Install dependencies with Poetry:

```powershell
python -m pip install poetry
python -m poetry install
```

If `poetry` is not on PATH in your shell, use `python -m poetry ...` commands.

2. Create local env file:

```powershell
Copy-Item .env.example .env
```

3. Fill `.env` with MT5 and Telegram credentials.

4. Verify configuration in `config/settings.yaml`.

## Deployment (AWS First)

If you have AWS credits, deploy on AWS Windows VPS first instead of keeping your laptop on 24/5.

- Recommended: `Amazon Lightsail (Windows)` for simpler setup.
- Alternative: `Amazon EC2 (Windows)` for more control.
- Full guide: `docs/AWS_VPS_SETUP.md`.
- Milestone tracking: `docs/MILESTONES.md`.

## Run

Dry-run mode:

```powershell
python -m poetry run trading-signal-bot --dry-run
```

Live mode:

```powershell
python -m poetry run trading-signal-bot
```

## Test

```powershell
python -m poetry run pytest
```

## Lint + Type Check

```powershell
python -m poetry run ruff check .
python -m poetry run black --check .
python -m poetry run mypy src
```
