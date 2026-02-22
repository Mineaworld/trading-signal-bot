param(
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Find the Poetry virtualenv python.exe directly.
# The SYSTEM account cannot use `poetry run`, so we call the venv python directly.
$venvRoots = @(
  "$env:LOCALAPPDATA\pypoetry\Cache\virtualenvs",
  "C:\Users\Administrator\AppData\Local\pypoetry\Cache\virtualenvs"
)

$venvPython = $null
foreach ($root in $venvRoots) {
  if (Test-Path $root) {
    $match = Get-ChildItem $root -Directory -Filter "trading-signal-bot-*" | Select-Object -First 1
    if ($match) {
      $candidate = Join-Path $match.FullName "Scripts\python.exe"
      if (Test-Path $candidate) {
        $venvPython = $candidate
        break
      }
    }
  }
}

if (-not $venvPython) {
  Write-Error "Poetry virtualenv not found. Run 'poetry install' as Administrator first."
  exit 1
}

$runArgs = @("-m", "trading_signal_bot")
if ($DryRun) {
  $runArgs += "--dry-run"
}

& $venvPython @runArgs
