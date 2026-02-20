param(
  [string]$WorkDir = "C:\trading-signal-bot"
)

$ErrorActionPreference = "Continue"
$passed = 0
$failed = 0

function Check {
  param([string]$Name, [scriptblock]$Test)
  try {
    $result = & $Test
    if ($result) {
      Write-Host "  PASS: $Name" -ForegroundColor Green
      $script:passed++
    } else {
      Write-Host "  FAIL: $Name" -ForegroundColor Red
      $script:failed++
    }
  } catch {
    Write-Host "  FAIL: $Name ($_)" -ForegroundColor Red
    $script:failed++
  }
}

Write-Host "=== Production Preflight Checks ===" -ForegroundColor Cyan
Write-Host ""

Check "MT5 terminal running" {
  (Get-Process -Name "terminal64" -ErrorAction SilentlyContinue) -ne $null
}

Check "Python available" {
  $v = python --version 2>&1
  $v -match "Python 3\."
}

Check "Python >= 3.10" {
  $v = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>&1
  [version]$v -ge [version]"3.10"
}

Check "Disk space > 1GB free" {
  $drive = (Resolve-Path $WorkDir).Drive
  $free = (Get-PSDrive $drive.Name).Free
  $free -gt 1GB
}

Check ".env file exists" {
  Test-Path (Join-Path $WorkDir ".env")
}

Check ".env has MT5_LOGIN" {
  $content = Get-Content (Join-Path $WorkDir ".env") -Raw
  $content -match "MT5_LOGIN="
}

Check ".env has TELEGRAM_BOT_TOKEN" {
  $content = Get-Content (Join-Path $WorkDir ".env") -Raw
  $content -match "TELEGRAM_BOT_TOKEN="
}

Check "settings.yaml exists" {
  Test-Path (Join-Path $WorkDir "config\settings.yaml")
}

Check "settings.yaml is valid YAML" {
  Push-Location $WorkDir
  $result = python -c "import yaml; yaml.safe_load(open('config/settings.yaml'))" 2>&1
  Pop-Location
  $LASTEXITCODE -eq 0
}

Check "Telegram API reachable" {
  try {
    $response = Invoke-WebRequest -Uri "https://api.telegram.org" -TimeoutSec 10 -UseBasicParsing
    $response.StatusCode -eq 200
  } catch {
    $false
  }
}

Check "Poetry installed" {
  $v = poetry --version 2>&1
  $v -match "Poetry"
}

Check "Dependencies installed" {
  Push-Location $WorkDir
  $result = poetry check 2>&1
  Pop-Location
  $LASTEXITCODE -eq 0
}

Write-Host ""
Write-Host "=== Results: $passed passed, $failed failed ===" -ForegroundColor $(if ($failed -eq 0) { "Green" } else { "Red" })

if ($failed -gt 0) { exit 1 }
