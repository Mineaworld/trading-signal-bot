# AWS EC2 Setup Guide (Windows Server 2022)

This guide assumes your EC2 instance is already created and reachable by RDP.

## Current Baseline (Already Done)
- OS: `Windows Server 2022`
- Instance type: `t3.medium`
- Storage: `40 GB`
- Access: RDP (`3389`) restricted to your IP

From here, you only need to install MT5 and deploy the bot.

## Prerequisites
- MT5 account credentials: login, password, server
- Telegram bot token and chat id
- This repository source code

## 1. Connect and Prepare Workspace
1. Connect to EC2 with RDP.
2. Create working folder: `C:\trading-signal-bot`.
3. Clone/copy this repository into `C:\trading-signal-bot`.
4. Set Windows timezone (UTC recommended for logs and ops).

## 2. Install Runtime on EC2
1. Install Python `3.10+`.
2. Install Git (optional but recommended).
3. Install Poetry:

```powershell
python -m pip install poetry
```

4. Install project dependencies:

```powershell
cd C:\trading-signal-bot
poetry install
Copy-Item .env.example .env
```

## 3. Install and Prepare MetaTrader 5
1. Download and install MT5 terminal from your broker.
2. Open MT5 and log in using your trading account.
3. Keep MT5 set to stay logged in.
4. In MT5, open all symbols/timeframes your strategy uses so history is loaded.
5. Confirm terminal path, usually:
   - `C:\Program Files\MetaTrader 5\terminal64.exe`

## 4. Configure Bot Environment
Edit `.env` in `C:\trading-signal-bot` and set:

- `MT5_LOGIN`
- `MT5_PASSWORD`
- `MT5_SERVER`
- `MT5_TERMINAL_PATH`
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`

Then verify `config/settings.yaml` symbol names match your broker.

## 5. Verify MT5 Connection First
From project folder:

```powershell
python -m poetry run python .\tmp_mt5_check.py
```

Expected result:
- `initialized = True`
- `last_error = (1, 'Success')`

## 6. Validate Bot Before Live
Run dry-run:

```powershell
poetry run trading-signal-bot --dry-run
```

Then run live:

```powershell
poetry run trading-signal-bot
```

Validate:
1. Telegram startup message arrives.
2. Logs appear in `logs/bot.log`.
3. Symbols resolve and no MT5 auth error appears.

## 7. Run as Windows Service (Recommended)
Use service mode so bot survives RDP disconnect/reboot.

1. Install NSSM (example: `C:\tools\nssm\nssm.exe`).
2. Run:

```powershell
cd C:\trading-signal-bot
.\scripts\install_service.ps1 -WorkDir "C:\trading-signal-bot"
```

3. Start service from Services UI or PowerShell.
4. Verify logs:
   - `logs\service.stdout.log`
   - `logs\service.stderr.log`

## 8. Operations Checklist
- EC2 remains running during trading sessions.
- MT5 terminal is installed and account stays logged in.
- Bot service is running automatically after reboot.
- RDP is still restricted to your current IP.
- Logs are checked daily.
- Snapshot/AMI backup exists before major changes.

## 9. Troubleshooting
- MT5 initialize fails:
  - Verify `MT5_TERMINAL_PATH` points to `terminal64.exe`.
  - Confirm MT5 account is logged in and server is correct.
  - Reopen MT5 once manually after Windows restart.
- No Telegram notifications:
  - Recheck `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`.
  - Verify outbound internet from EC2.
- Bot runs but no signals:
  - Confirm market is open and symbols in `settings.yaml` are valid.
  - Check `logs/bot.log` for strategy precondition skips.
