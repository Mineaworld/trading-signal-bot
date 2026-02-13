param(
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

if (Test-Path ".\.venv\Scripts\Activate.ps1") {
  . .\.venv\Scripts\Activate.ps1
}

$args = @("-m", "poetry", "run", "trading-signal-bot")
if ($DryRun) {
  $args += "--dry-run"
}

python @args
