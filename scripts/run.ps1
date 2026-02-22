param(
  [switch]$DryRun
)

$ErrorActionPreference = "Stop"

# Find Python - check common locations since SYSTEM account may not have PATH
$pythonCandidates = @(
  "python",
  "$env:LOCALAPPDATA\Programs\Python\Python312\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python311\python.exe",
  "$env:LOCALAPPDATA\Programs\Python\Python310\python.exe",
  "C:\Users\Administrator\AppData\Local\Programs\Python\Python312\python.exe",
  "C:\Users\Administrator\AppData\Local\Programs\Python\Python311\python.exe",
  "C:\Users\Administrator\AppData\Local\Programs\Python\Python310\python.exe",
  "C:\Python312\python.exe",
  "C:\Python311\python.exe",
  "C:\Python310\python.exe"
)

$pythonPath = $null
foreach ($candidate in $pythonCandidates) {
  try {
    $resolved = Get-Command $candidate -ErrorAction SilentlyContinue
    if ($resolved) {
      $pythonPath = $resolved.Source
      break
    }
    if (Test-Path $candidate) {
      $pythonPath = $candidate
      break
    }
  } catch {}
}

if (-not $pythonPath) {
  Write-Error "Python not found. Install Python 3.10+ and ensure it is in PATH or a standard location."
  exit 1
}

$runArgs = @("-m", "poetry", "run", "trading-signal-bot")
if ($DryRun) {
  $runArgs += "--dry-run"
}

& $pythonPath @runArgs
