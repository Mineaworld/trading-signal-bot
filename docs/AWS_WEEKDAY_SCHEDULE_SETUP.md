# AWS Weekday Schedule Setup (Windows EC2 + MT5)

This guide configures your bot to run only on weekdays from `07:00` to `23:00`.

It uses two layers:
1. Windows service on EC2 to keep the bot running in the background while the instance is on.
2. AWS EventBridge Scheduler to start and stop the EC2 instance on a fixed weekly schedule.

## Prerequisites

- Windows EC2 instance is already created and reachable by RDP.
- Bot code is deployed on the instance (example path: `C:\trading-signal-bot`).
- MT5 is installed, configured, and can log in successfully.
- You can run the bot manually first (`poetry run trading-signal-bot`).
- You have IAM permissions to create roles and EventBridge schedules.
- NSSM is installed on the instance (example path: `C:\tools\nssm\nssm.exe`).

## Step 1: Install Bot as Windows Service (One Time)

Open PowerShell as Administrator on the EC2 instance:

```powershell
cd C:\trading-signal-bot
.\scripts\install_service.ps1 -WorkDir "C:\trading-signal-bot"
Start-Service TradingSignalBot
Get-Service TradingSignalBot
```

Expected: service status should be `Running`.

If NSSM is installed in a different location, pass `-NssmPath`:

```powershell
cd C:\trading-signal-bot
.\scripts\install_service.ps1 -WorkDir "C:\trading-signal-bot" -NssmPath "D:\tools\nssm\nssm.exe"
Start-Service TradingSignalBot
Get-Service TradingSignalBot
```

Optional dry-run service:

```powershell
.\scripts\install_service.ps1 -WorkDir "C:\trading-signal-bot" -ServiceName "TradingSignalBotDryRun" -DryRun
```

## Step 2: Create IAM Role for EventBridge Scheduler (One Time)

Create an IAM role with:
- Trusted service: `scheduler.amazonaws.com`
- Permissions:
  - `ec2:StartInstances`
  - `ec2:StopInstances`
- Scope permissions to your specific instance ARN when possible.

### Trust policy example

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "scheduler.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### Permissions policy example

Replace `<REGION>`, `<ACCOUNT_ID>`, and `<INSTANCE_ID>`.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "ec2:StartInstances",
        "ec2:StopInstances"
      ],
      "Resource": "arn:aws:ec2:<REGION>:<ACCOUNT_ID>:instance/<INSTANCE_ID>"
    }
  ]
}
```

## Step 3: Create Weekday Start Schedule

AWS Console -> EventBridge -> Scheduler -> Create schedule:

- Name: `tradingbot-start-weekdays`
- Schedule pattern: Recurring
- Cron expression: `0 7 ? * MON-FRI *`
- Time zone: your trading time zone (example: `America/New_York`)
- Flexible time window: `OFF`
- Target: `AWS API`
- API: `EC2 StartInstances`
- Input payload:

```json
{"InstanceIds":["<INSTANCE_ID>"]}
```

- Execution role: role from Step 2.

## Step 4: Create Weekday Stop Schedule

Create another schedule:

- Name: `tradingbot-stop-weekdays`
- Schedule pattern: Recurring
- Cron expression: `0 23 ? * MON-FRI *`
- Time zone: same as start schedule
- Flexible time window: `OFF`
- Target: `AWS API`
- API: `EC2 StopInstances`
- Input payload:

```json
{"InstanceIds":["<INSTANCE_ID>"]}
```

- Execution role: role from Step 2.

## Step 5: Verify End-to-End

1. Confirm both schedules are `Enabled`.
2. Manually run a one-time test:
   - Stop instance, then run start schedule now.
   - Verify instance enters `running` state.
3. RDP into instance and check:

```powershell
Get-Service TradingSignalBot
```

4. Confirm bot logs are updating:
   - `logs\bot.log`
   - `logs\service.stdout.log`
   - `logs\service.stderr.log`
5. Confirm startup message appears in Telegram.

## Recommended Production Values

- Start time: `06:55` instead of `07:00`
- Stop time: `23:05` instead of `23:00`

This adds a small buffer around your operating window.

## Important Notes

- If the instance is stopped, compute charges stop. EBS storage charges continue.
- Keep MT5 configured to auto-login on boot.
- Keep Windows time synchronized and scheduler time zone explicit.
- If you manually start/stop the instance, schedules continue to apply at the next scheduled trigger.

## Troubleshooting

### Instance did not start/stop

- Check EventBridge Scheduler execution history.
- Check that the schedule role has `ec2:StartInstances` and `ec2:StopInstances`.
- Check that the instance ID in schedule payload is correct.

### Instance started but bot is not running

- Check service state:

```powershell
Get-Service TradingSignalBot
```

- Start service manually:

```powershell
Start-Service TradingSignalBot
```

- Review logs:
  - `logs\service.stdout.log`
  - `logs\service.stderr.log`
  - `logs\bot.log`

### Bot running but no signals

- Confirm MT5 is logged in and symbols are tradable.
- Run dry-run manually to validate runtime:

```powershell
cd C:\trading-signal-bot
poetry run trading-signal-bot --dry-run
```

## Related Project Docs

- `docs/AWS_VPS_SETUP.md`
- `scripts/install_service.ps1`
- `scripts/run.ps1`
