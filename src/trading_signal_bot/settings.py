from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

from trading_signal_bot.models import IndicatorParams, Timeframe


@dataclass(frozen=True)
class TimeframeConfig:
    primary: Timeframe
    confirmation: Timeframe


@dataclass(frozen=True)
class DataConfig:
    candle_buffer: int
    min_valid_closed_bars: int


@dataclass(frozen=True)
class ExecutionConfig:
    reconnect_max_retries: int
    reconnect_base_delay_seconds: int
    reconnect_max_delay_seconds: int
    loop_failure_sleep_seconds: int


@dataclass(frozen=True)
class SignalDedupConfig:
    cooldown_minutes: int
    retention_days: int
    state_file: Path


@dataclass(frozen=True)
class LoggingConfig:
    level: str
    file: Path
    max_bytes: int
    backup_count: int


@dataclass(frozen=True)
class TelegramConfig:
    failed_queue_file: Path
    max_queue_size: int
    max_retries: int
    max_failed_retry_count: int
    request_timeout_seconds: int


@dataclass(frozen=True)
class M1OnlyConfig:
    enabled: bool


@dataclass(frozen=True)
class AppConfig:
    symbols: dict[str, str]
    timeframe: TimeframeConfig
    indicators: IndicatorParams
    data: DataConfig
    execution: ExecutionConfig
    signal_dedup: SignalDedupConfig
    logging: LoggingConfig
    telegram: TelegramConfig
    m1_only: M1OnlyConfig


@dataclass(frozen=True)
class SecretsConfig:
    mt5_login: int
    mt5_password: str
    mt5_server: str
    mt5_terminal_path: str | None
    telegram_bot_token: str
    telegram_chat_id: str


def load_yaml_config(config_path: Path) -> AppConfig:
    if not config_path.exists():
        raise FileNotFoundError(f"settings file not found: {config_path}")

    with config_path.open("r", encoding="utf-8") as handle:
        raw = yaml.safe_load(handle)

    if not isinstance(raw, dict):
        raise ValueError("settings.yaml must contain a root object")

    symbols = _require_dict(raw, "symbols")
    timeframes = _require_dict(raw, "timeframes")
    indicators = _require_dict(raw, "indicators")
    lwma_cfg = _require_dict(indicators, "lwma")
    stoch_cfg = _require_dict(indicators, "stochastic")
    data_cfg = _require_dict(raw, "data")
    execution_cfg = _require_dict(raw, "execution")
    dedup_cfg = _require_dict(raw, "signal_dedup")
    logging_cfg = _require_dict(raw, "logging")
    telegram_cfg = _require_dict(raw, "telegram")

    m1_only_cfg = raw.get("m1_only", {"enabled": False})
    if not isinstance(m1_only_cfg, dict):
        m1_only_cfg = {"enabled": False}

    parsed_symbols = {str(k): str(v) for k, v in symbols.items()}
    if not parsed_symbols:
        raise ValueError("symbols cannot be empty")

    return AppConfig(
        symbols=parsed_symbols,
        timeframe=TimeframeConfig(
            primary=Timeframe(str(timeframes["primary"])),
            confirmation=Timeframe(str(timeframes["confirmation"])),
        ),
        indicators=IndicatorParams(
            lwma_fast=_to_int_min(lwma_cfg["fast"], "indicators.lwma.fast", 1),
            lwma_slow=_to_int_min(lwma_cfg["slow"], "indicators.lwma.slow", 1),
            stoch_k=_to_int_min(stoch_cfg["k"], "indicators.stochastic.k", 1),
            stoch_d=_to_int_min(stoch_cfg["d"], "indicators.stochastic.d", 1),
            stoch_slowing=_to_int_min(stoch_cfg["slowing"], "indicators.stochastic.slowing", 1),
            buy_zone=_to_zone_tuple(stoch_cfg["buy_zone"]),
            sell_zone=_to_zone_tuple(stoch_cfg["sell_zone"]),
        ),
        data=DataConfig(
            candle_buffer=_to_int_min(data_cfg["candle_buffer"], "data.candle_buffer", 3),
            min_valid_closed_bars=_to_int_min(
                data_cfg["min_valid_closed_bars"], "data.min_valid_closed_bars", 2
            ),
        ),
        execution=ExecutionConfig(
            reconnect_max_retries=_to_int_min(
                execution_cfg["reconnect_max_retries"], "execution.reconnect_max_retries", 1
            ),
            reconnect_base_delay_seconds=_to_int_min(
                execution_cfg["reconnect_base_delay_seconds"],
                "execution.reconnect_base_delay_seconds",
                0,
            ),
            reconnect_max_delay_seconds=_to_int_min(
                execution_cfg["reconnect_max_delay_seconds"],
                "execution.reconnect_max_delay_seconds",
                1,
            ),
            loop_failure_sleep_seconds=_to_int_min(
                execution_cfg["loop_failure_sleep_seconds"],
                "execution.loop_failure_sleep_seconds",
                1,
            ),
        ),
        signal_dedup=SignalDedupConfig(
            cooldown_minutes=_to_int_min(
                dedup_cfg["cooldown_minutes"], "signal_dedup.cooldown_minutes", 1
            ),
            retention_days=_to_int_min(
                dedup_cfg["retention_days"], "signal_dedup.retention_days", 1
            ),
            state_file=Path(str(dedup_cfg["state_file"])),
        ),
        logging=LoggingConfig(
            level=str(logging_cfg["level"]),
            file=Path(str(logging_cfg["file"])),
            max_bytes=_to_int_min(logging_cfg["max_bytes"], "logging.max_bytes", 1024),
            backup_count=_to_int_min(logging_cfg["backup_count"], "logging.backup_count", 1),
        ),
        telegram=TelegramConfig(
            failed_queue_file=Path(str(telegram_cfg["failed_queue_file"])),
            max_queue_size=_to_int_min(
                telegram_cfg["max_queue_size"], "telegram.max_queue_size", 1
            ),
            max_retries=_to_int_min(telegram_cfg["max_retries"], "telegram.max_retries", 1),
            max_failed_retry_count=_to_int_min(
                telegram_cfg.get("max_failed_retry_count", 12),
                "telegram.max_failed_retry_count",
                1,
            ),
            request_timeout_seconds=_to_int_min(
                telegram_cfg["request_timeout_seconds"], "telegram.request_timeout_seconds", 1
            ),
        ),
        m1_only=M1OnlyConfig(
            enabled=bool(m1_only_cfg.get("enabled", False)),
        ),
    )


def load_secrets(env_path: Path | None = None) -> SecretsConfig:
    if env_path is not None and env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()

    import os

    required = [
        "MT5_LOGIN",
        "MT5_PASSWORD",
        "MT5_SERVER",
        "TELEGRAM_BOT_TOKEN",
        "TELEGRAM_CHAT_ID",
    ]
    missing = [key for key in required if not os.getenv(key)]
    if missing:
        raise ValueError(f"missing required environment variables: {', '.join(missing)}")

    return SecretsConfig(
        mt5_login=int(str(os.getenv("MT5_LOGIN"))),
        mt5_password=str(os.getenv("MT5_PASSWORD")),
        mt5_server=str(os.getenv("MT5_SERVER")),
        mt5_terminal_path=os.getenv("MT5_TERMINAL_PATH"),
        telegram_bot_token=str(os.getenv("TELEGRAM_BOT_TOKEN")),
        telegram_chat_id=str(os.getenv("TELEGRAM_CHAT_ID")),
    )


def _require_dict(payload: dict[str, Any], key: str) -> dict[str, Any]:
    if key not in payload:
        raise ValueError(f"missing required config section: {key}")
    value = payload[key]
    if not isinstance(value, dict):
        raise ValueError(f"config section must be a mapping: {key}")
    return value


def _to_zone_tuple(value: Any) -> tuple[int, int]:
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("stochastic zones must be two-element lists")
    low = int(value[0])
    high = int(value[1])
    if low > high:
        raise ValueError("zone lower bound cannot be greater than upper bound")
    return (low, high)


def _to_int_min(value: Any, name: str, minimum: int) -> int:
    parsed = int(value)
    if parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed
