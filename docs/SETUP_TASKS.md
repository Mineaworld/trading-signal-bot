# Setup Tasks - Trading Signal Bot

Manual tasks to complete before running the bot in production.
Mark each task with `[x]` when done.

---

## 1. MetaTrader 5 Setup

- [ ] Install MetaTrader 5 terminal from your broker's website
- [ ] Login to MT5 with your broker account (demo or live)
- [ ] Open Market Watch and verify these 4 symbols exist:
  - [ ] XAUUSD (Gold)
  - [ ] NAS100 (Nasdaq)
  - [ ] EURUSD
  - [ ] GBPJPY
- [ ] If your broker uses different symbol names (e.g. `XAUUSDm`, `USTEC`, `NAS100.`), update `config/settings.yaml` under `symbols:` to map alias -> broker symbol
- [ ] Note your MT5 account number, password, and server name (shown in MT5 login dialog)
- [ ] (Optional) Note the path to `terminal64.exe` if MT5 is not in the default install location

---

## 2. Telegram Bot Setup

- [x] Open Telegram, search for `@BotFather`
- [x] Send `/newbot` to BotFather
- [x] Choose a display name (e.g. "Trading Signal Bot")
- [x] Choose a username (e.g. `my_trading_signal_bot`)
- [x] Copy the **bot token** BotFather gives you (looks like `123456:ABC-DEF1234...`)
- [x] Send any message to your new bot in Telegram
- [x] Get your **chat ID** by visiting: `https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates` - find the `"chat":{"id": 123456789}` number
- [ ] (Optional) For group alerts: add the bot to a Telegram group, send a message in the group, then check the same `/getUpdates` URL for the group chat ID (will be negative, e.g. `-100123456789`)

---

## 3. Environment Configuration

- [ ] Copy `.env.example` to `.env`:
  ```powershell
  Copy-Item .env.example .env
  ```
- [ ] Fill in `.env` with your credentials:
  ```
  MT5_LOGIN=12345678
  MT5_PASSWORD=your_password
  MT5_SERVER=YourBroker-Server
  MT5_TERMINAL_PATH=
  TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
  TELEGRAM_CHAT_ID=987654321
  ```
- [ ] Verify `config/settings.yaml` symbol mappings match your broker

---

## 4. Install & First Run

- [ ] Install Python 3.10+ (if not already installed)
- [ ] Install Poetry:
  ```powershell
  python -m pip install poetry
  ```
- [ ] Install project dependencies:
  ```powershell
  poetry install
  ```
- [ ] Run tests to verify everything works:
  ```powershell
  poetry run pytest
  ```
- [ ] Run in dry-run mode (no Telegram, console only):
  ```powershell
  poetry run trading-signal-bot --dry-run
  ```
- [ ] Verify dry-run starts without errors and logs show "startup completed"

---

## 5. Live Validation (Demo Account)

- [ ] Run live against demo account during market hours:
  ```powershell
  poetry run trading-signal-bot
  ```
- [ ] Confirm startup test message arrives in Telegram
- [ ] Watch `logs/bot.log` for signal evaluation logs
- [ ] When first signal fires, verify it matches your MT5 chart manually
- [ ] Test resilience: briefly disconnect MT5, verify bot reconnects (check logs)
- [ ] Test restart replay: kill bot, restart, verify no duplicate alerts sent
- [ ] Validate first 50 alerts against chart candles for accuracy

---

## 6. Production Run (Optional)

- [ ] Decide deployment target: local PC or VPS (**AWS first if you have credits**)
- [ ] Read AWS setup guide: `docs/AWS_VPS_SETUP.md`
- [ ] Provision Windows VPS on AWS (Lightsail recommended, EC2 optional)
- [ ] Restrict RDP (`3389`) access to your public IP only
- [ ] Install MT5 + Python + bot on VPS
- [ ] Configure MT5 auto-login on VPS
- [ ] Run dry-run, then live validation on VPS
- [ ] Install bot as Windows service (`scripts/install_service.ps1`) so it survives RDP disconnect
- [ ] Start bot and monitor logs for first 24 hours
- [ ] Set up remote health checks and AWS budget alerts
- [ ] (Alternative if not using AWS) use another Windows VPS provider

