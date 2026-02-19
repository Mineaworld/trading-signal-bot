param(
  [string]$WorkDir = "C:\trading-signal-bot",
  [string]$ServiceName = "TradingSignalBot",
  [string]$LogFile = "logs\deploy.log"
)

$ErrorActionPreference = "Stop"

function Log {
  param([string]$Message)
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $line = "$ts | $Message"
  Write-Host $line
  $logPath = Join-Path $WorkDir $LogFile
  $logDir = Split-Path $logPath -Parent
  if (-not (Test-Path $logDir)) { New-Item -ItemType Directory -Path $logDir -Force | Out-Null }
  Add-Content -Path $logPath -Value $line
}

function Main {
  if (-not (Test-Path $WorkDir)) {
    Write-Error "WorkDir does not exist: $WorkDir"
    exit 1
  }

  Push-Location $WorkDir
  try {
    # Save current commit for rollback
    $prevCommit = git rev-parse HEAD
    Log "deploy started from commit $prevCommit"

    # Pull latest
    Log "git pull..."
    git pull --ff-only
    if ($LASTEXITCODE -ne 0) {
      Log "ERROR: git pull failed"
      exit 1
    }
    $newCommit = git rev-parse HEAD
    Log "updated to commit $newCommit"

    # Install dependencies
    Log "poetry install..."
    poetry install --no-interaction
    if ($LASTEXITCODE -ne 0) {
      Log "ERROR: poetry install failed, rolling back"
      git checkout $prevCommit
      exit 1
    }

    # Run tests
    Log "running tests..."
    poetry run pytest -q
    if ($LASTEXITCODE -ne 0) {
      Log "ERROR: tests failed, rolling back to $prevCommit"
      git checkout $prevCommit
      poetry install --no-interaction
      exit 1
    }
    Log "tests passed"

    # Restart NSSM service
    Log "restarting service $ServiceName..."
    nssm restart $ServiceName
    if ($LASTEXITCODE -ne 0) {
      Log "WARNING: nssm restart returned non-zero, checking status..."
    }

    # Wait and verify
    Start-Sleep -Seconds 5
    $status = nssm status $ServiceName
    if ($status -match "SERVICE_RUNNING") {
      Log "service is running"
    } else {
      Log "ERROR: service not running after restart, status=$status"
      Log "rolling back to $prevCommit"
      git checkout $prevCommit
      poetry install --no-interaction
      nssm restart $ServiceName
      exit 1
    }

    # Verify startup message in logs
    $botLog = Join-Path $WorkDir "logs\bot.log"
    if (Test-Path $botLog) {
      $recentLines = Get-Content $botLog -Tail 20
      $startupFound = $recentLines | Where-Object { $_ -match "startup completed" }
      if ($startupFound) {
        Log "startup message confirmed in logs"
      } else {
        Log "WARNING: startup message not found in recent log lines"
      }
    }

    Log "deploy completed successfully: $prevCommit -> $newCommit"
  } finally {
    Pop-Location
  }
}

Main
