@echo off
setlocal EnableExtensions

cd /d "%~dp0"
title Trading Signal Bot - Live Launcher

set "PYTHON=python"
set "ENV_FILE=.env"
set "CONFIG_FILE=config\settings.m1_only.yaml"

echo ====================================================
echo Trading Signal Bot one-click live launcher
echo Repo: %CD%
echo Time: %DATE% %TIME%
echo ====================================================
echo.

if not exist "%ENV_FILE%" (
  echo [ERROR] Missing %ENV_FILE%
  echo Create it first, then run this file again.
  echo.
  pause
  exit /b 1
)

if not exist "%CONFIG_FILE%" (
  echo [ERROR] Missing %CONFIG_FILE%
  echo.
  pause
  exit /b 1
)

"%PYTHON%" --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Python is not available in PATH.
  echo.
  pause
  exit /b 1
)

"%PYTHON%" -m poetry --version >nul 2>&1
if errorlevel 1 (
  echo [ERROR] Poetry is unavailable via python -m poetry.
  echo Install Poetry and dependencies first.
  echo.
  pause
  exit /b 1
)

echo [1/2] Running MT5 preflight...
"%PYTHON%" -m poetry run python "scripts\mt5_preflight.py" --env "%ENV_FILE%"
if errorlevel 1 (
  echo.
  echo [ERROR] MT5 preflight failed. Fix MT5/.env and run again.
  echo.
  pause
  exit /b 1
)

echo.
echo [2/2] Starting live bot with %CONFIG_FILE%
echo Keep this window open.
echo Press Ctrl+C to stop the bot.
echo.

"%PYTHON%" -m poetry run trading-signal-bot --config "%CONFIG_FILE%"
set "EXIT_CODE=%ERRORLEVEL%"

echo.
echo Bot exited with code %EXIT_CODE%.
pause
exit /b %EXIT_CODE%
