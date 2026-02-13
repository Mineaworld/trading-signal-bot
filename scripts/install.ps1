param(
  [string]$PythonExe = "python"
)

$ErrorActionPreference = "Stop"

Write-Host "Creating virtual environment..."
& $PythonExe -m venv .venv

Write-Host "Activating virtual environment..."
. .\.venv\Scripts\Activate.ps1

Write-Host "Installing Poetry..."
python -m pip install --upgrade pip
python -m pip install poetry

Write-Host "Installing dependencies..."
python -m poetry install

if (-not (Test-Path ".env")) {
  Write-Host "Creating .env from .env.example"
  Copy-Item .env.example .env
}

Write-Host "Installation complete."
