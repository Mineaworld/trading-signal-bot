# AWS EC2 Setup Guide

Your bot needs a Windows server running 24/5 so it never misses a signal.
This guide walks you through setting it up on AWS EC2 step by step.

## What You Need Before Starting

- Your AWS EC2 instance already created and running (Windows Server 2022, t3.medium, 40GB)
- Your MT5 account: login number, password, server name
- Your Telegram bot token and chat ID (from BotFather)

---

## Step 1: Connect to Your Server

1. Go to **AWS Console > EC2 > Instances**
2. Click your instance, copy the **Public IPv4 address**
3. Open **Remote Desktop** on your PC
4. Paste the IP, click Connect
5. Enter your EC2 username (`Administrator`) and password

> **Can't connect?** Your IP probably changed. Go to your instance's
> **Security Group > Inbound Rules**, update the RDP source to your current IP.
> Google "what is my ip" to find it.

---

## Step 2: Install Python

1. Open a browser on the server, go to [python.org/downloads](https://www.python.org/downloads/)
2. Download Python 3.12 (or any 3.10+)
3. Run the installer
   - **Check "Add Python to PATH"** (important!)
   - Click "Install Now"
4. Open PowerShell and verify:

```powershell
python --version
# Should show: Python 3.12.x
```

---

## Step 3: Install Git

1. Go to [git-scm.com](https://git-scm.com/download/win)
2. Download and install (default options are fine)
3. Verify in PowerShell:

```powershell
git --version
```

---

## Step 4: Clone the Bot

```powershell
git clone https://github.com/Mineaworld/trading-signal-bot.git C:\trading-signal-bot
cd C:\trading-signal-bot
```

---

## Step 5: Install Poetry and Dependencies

```powershell
python -m pip install poetry
poetry install
```

Wait for it to finish. This installs all the Python packages the bot needs.

---

## Step 6: Install MetaTrader 5

1. Open browser on the server, download MT5 from your broker's website
2. Install it (default location is fine)
3. Open MT5 and **log in** with your trading account
4. In MT5, go to **View > Market Watch** and make sure your symbols show up:
   - XAUUSD, NAS100, EURUSD, GBPJPY
   - If your broker uses different names (like `XAUUSDm` or `USTEC`), note them down
5. Go to **Tools > Options > Expert Advisors** and check **"Allow algorithmic trading"**
6. Note the MT5 install path (usually `C:\Program Files\MetaTrader 5\terminal64.exe`)

---

## Step 7: Configure the Bot

```powershell
cd C:\trading-signal-bot
Copy-Item .env.example .env
notepad .env
```

Fill in your credentials:

```
MT5_LOGIN=12345678
MT5_PASSWORD=your_mt5_password
MT5_SERVER=YourBroker-Server
MT5_TERMINAL_PATH=C:\Program Files\MetaTrader 5\terminal64.exe
TELEGRAM_BOT_TOKEN=123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11
TELEGRAM_CHAT_ID=987654321
```

> **Important:** `MT5_LOGIN` and `MT5_SERVER` must match the account
> currently logged in inside MT5. If they don't match, the bot can't connect.

If your broker uses different symbol names, edit `config/settings.yaml`:

```powershell
notepad config\settings.yaml
```

Update the `symbols:` section to map your aliases to broker names.

### Optional: Live-Bar Evaluation

By default, the bot waits for candles to close before evaluating. To get alerts the moment indicator criteria are met (on the forming bar), enable live-bar mode:

```powershell
notepad config\settings.yaml
```

Set:

```yaml
live_bar:
  enabled: true
  poll_interval_seconds: 15
```

Signals from forming bars are prefixed with `[LIVE]` in Telegram so you know the candle hasn't closed yet. The bot polls every 15 seconds instead of waiting for candle close.

> **Note:** Risk-context ATR and startup replay always use closed bars for stability, regardless of this setting.

---

## Step 8: Test Everything

Run these one by one. Don't skip any.

**8a. Check MT5 connection:**

```powershell
cd C:\trading-signal-bot
poetry run python .\scripts\mt5_preflight.py
```

You should see all checks pass (`initialized=True`, `login=True`, etc).

**8b. Check server readiness:**

```powershell
.\scripts\preflight_prod.ps1
```

All checks should show `PASS`.

**8c. Dry run (no real messages sent):**

```powershell
poetry run trading-signal-bot --dry-run
```

Should start without errors. Press `Ctrl+C` to stop after a few seconds.

**8d. Live run (sends real Telegram messages):**

```powershell
poetry run trading-signal-bot
```

Check your Telegram - you should get a startup message. Press `Ctrl+C` to stop.

---

## Step 9: Set Up Task Scheduler (Keeps Bot Running)

Task Scheduler runs the bot in your user session so it can talk to MT5.
Without this, the bot stops when you close RDP.

> **Why not a Windows Service?** MT5 uses local IPC that only works within
> the same user session. Services run in Session 0 (background) and can't
> reach MT5 in your RDP session. Task Scheduler solves this.

---

## Step 10: Register the Bot Task

Run this in PowerShell **as Administrator**:

```powershell
$action  = New-ScheduledTaskAction `
  -Execute "powershell.exe" `
  -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\trading-signal-bot\scripts\run.ps1" `
  -WorkingDirectory "C:\trading-signal-bot"

$trigger = New-ScheduledTaskTrigger -AtLogon

$settings = New-ScheduledTaskSettingsSet `
  -AllowStartIfOnBatteries `
  -DontStopIfGoingOnBatteries `
  -RestartCount 3 `
  -RestartInterval (New-TimeSpan -Minutes 1) `
  -ExecutionTimeLimit (New-TimeSpan -Days 365)

Register-ScheduledTask `
  -TaskName "TradingSignalBot" `
  -Action $action `
  -Trigger $trigger `
  -Settings $settings `
  -User "Administrator" `
  -RunLevel Highest `
  -Description "Trading Signal Bot"
```

Start it now:

```powershell
Start-ScheduledTask -TaskName "TradingSignalBot"
```

Verify it's running:

```powershell
Get-ScheduledTask -TaskName "TradingSignalBot" | Select-Object State
# State should show: Running
```

Now you can **close RDP** and the bot keeps running.

---

## Step 11: Verify After Closing RDP

After you close Remote Desktop:

1. Wait 15 minutes during market hours
2. Check your Telegram - you should see signals (if market conditions are met)
3. Reconnect via RDP and check logs:

```powershell
Get-Content C:\trading-signal-bot\logs\bot.log -Tail 30
```

---

## Daily Operations

| Task | How Often |
|------|-----------|
| Check Telegram for signals | Daily |
| Check `logs/bot.log` for errors | Daily (first week), then weekly |
| Verify bot task is running | After any server restart |
| Update RDP security group IP | When your WiFi/IP changes |

---

## Managing the Bot

All commands run in PowerShell on the EC2 instance.

### Basic Controls

```powershell
# Check if the bot is running
Get-ScheduledTask -TaskName "TradingSignalBot" | Select-Object State

# Start the bot
Start-ScheduledTask -TaskName "TradingSignalBot"

# Stop the bot
Stop-ScheduledTask -TaskName "TradingSignalBot"

# Restart the bot (use after config changes)
Stop-ScheduledTask -TaskName "TradingSignalBot"
Start-ScheduledTask -TaskName "TradingSignalBot"
```

### Checking Logs

```powershell
# Bot activity log (signals, heartbeats, errors)
Get-Content C:\trading-signal-bot\logs\bot.log -Tail 50

# Follow logs in real-time (like tail -f)
Get-Content C:\trading-signal-bot\logs\bot.log -Tail 20 -Wait
```

### Config Changes

After editing `.env` or `config/settings.yaml`:

```powershell
Stop-ScheduledTask -TaskName "TradingSignalBot"
Start-ScheduledTask -TaskName "TradingSignalBot"
```

### Remove the Bot Task

```powershell
Stop-ScheduledTask -TaskName "TradingSignalBot"
Unregister-ScheduledTask -TaskName "TradingSignalBot" -Confirm:$false
```

---

## Updating the Bot

When there's a new version:

```powershell
cd C:\trading-signal-bot
.\scripts\deploy.ps1
```

This pulls the latest code, runs tests, and restarts the service. If anything fails, it automatically rolls back.

---

## Troubleshooting

### Can't connect via RDP

| Cause | Fix |
|-------|-----|
| Your IP changed | Update Security Group inbound rule with your new IP |
| Instance IP changed | Copy new Public IPv4 from AWS Console |
| Instance not ready | Wait for `2/2 status checks passed` in AWS Console |

### MT5 won't connect

| Cause | Fix |
|-------|-----|
| Wrong path | Check `MT5_TERMINAL_PATH` in `.env` points to `terminal64.exe` |
| Wrong credentials | Make sure `.env` login/server matches what's logged in inside MT5 |
| API disabled | MT5 > Tools > Options > Expert Advisors > Enable algorithmic trading |
| After reboot | Open MT5 manually once so it reconnects |

### No Telegram messages

| Cause | Fix |
|-------|-----|
| Wrong token | Double-check `TELEGRAM_BOT_TOKEN` in `.env` |
| Wrong chat ID | Double-check `TELEGRAM_CHAT_ID` in `.env` |
| No internet | Check EC2 security group has outbound access (default: yes) |

### Bot running but no signals

| Cause | Fix |
|-------|-----|
| Market closed | Forex closes Friday night, reopens Sunday night |
| Outside session window | Check `session_filter` times in `config/settings.yaml` |
| Symbols wrong | Verify symbol names match your broker in `settings.yaml` |
| Check logs | `Get-Content C:\trading-signal-bot\logs\bot.log -Tail 50` |

### Bot not running after reboot

```powershell
# Check status
Get-ScheduledTask -TaskName "TradingSignalBot" | Select-Object State

# Start it
Start-ScheduledTask -TaskName "TradingSignalBot"

# Check logs for errors
Get-Content C:\trading-signal-bot\logs\bot.log -Tail 30
```

---

## Next Step

Once the bot is running stable for a few days, set up the **weekday auto start/stop schedule**
to save money. See `docs/AWS_WEEKDAY_SCHEDULE_SETUP.md`.
