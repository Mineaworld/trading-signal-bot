# Project Instructions

- Mark TODO.md items complete when committed

## EC2 Deployment

- Bot runs via **Windows Task Scheduler** (task name: `TradingSignalBot`), NOT NSSM
- `deploy.ps1` uses `nssm` commands — do NOT use it; run manual steps instead
- Deploy steps: `Stop-ScheduledTask` → `git pull` → `poetry install` → `pytest` → `Start-ScheduledTask`
- Check status: `Get-ScheduledTask -TaskName "TradingSignalBot" | Select-Object State`
- Tail logs: `Get-Content C:\trading-signal-bot\logs\bot.log -Tail 50 -Wait`
