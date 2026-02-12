param(
  [string]$ServiceName = "TradingSignalBot",
  [string]$NssmPath = "C:\tools\nssm\nssm.exe",
  [string]$WorkDir = "C:\trading-signal-bot",
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (-not (Test-Path $NssmPath)) {
  throw "NSSM executable not found at $NssmPath"
}

$runScript = Join-Path $WorkDir "scripts\run.ps1"
if (-not (Test-Path $runScript)) {
  throw "Run script not found at $runScript"
}

$arguments = "-ExecutionPolicy Bypass -File `"$runScript`""
if ($DryRun) {
  $arguments += " -DryRun"
}

& $NssmPath install $ServiceName "powershell.exe" $arguments
& $NssmPath set $ServiceName AppDirectory $WorkDir
& $NssmPath set $ServiceName Start SERVICE_AUTO_START
& $NssmPath set $ServiceName AppStdout (Join-Path $WorkDir "logs\service.stdout.log")
& $NssmPath set $ServiceName AppStderr (Join-Path $WorkDir "logs\service.stderr.log")

Write-Host "Service installed: $ServiceName"
