from __future__ import annotations

import logging
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
    max_m15_backfill_bars: int


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
class ChainStrategyConfig:
    enabled: bool
    require_opposite_zone_on_lwma_cross: bool


@dataclass(frozen=True)
class SummarySignalConfig:
    enabled: bool


@dataclass(frozen=True)
class StrategyConfig:
    enable_legacy_scenarios: bool
    chain: ChainStrategyConfig
    summary: SummarySignalConfig


@dataclass(frozen=True)
class SessionWindowConfig:
    start: str
    end: str


@dataclass(frozen=True)
class SessionFilterConfig:
    enabled: bool
    timezone: str
    windows: tuple[SessionWindowConfig, ...]


@dataclass(frozen=True)
class RegimeFilterConfig:
    enabled: bool
    adx_period: int
    min_adx: float


@dataclass(frozen=True)
class RiskContextConfig:
    enabled: bool
    atr_period: int
    atr_stop_multiplier: float
    rr_targets: tuple[float, float]


@dataclass(frozen=True)
class MonitoringConfig:
    heartbeat_enabled: bool
    heartbeat_interval_seconds: int
    heartbeat_ping_url: str
    heartbeat_file: Path


@dataclass(frozen=True)
class HealthAlertsConfig:
    enabled: bool
    chat_id: str
    throttle_minutes: int


@dataclass(frozen=True)
class JournalConfig:
    enabled: bool
    sqlite_path: Path


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
    strategy: StrategyConfig
    session_filter: SessionFilterConfig
    regime_filter: RegimeFilterConfig
    risk_context: RiskContextConfig
    monitoring: MonitoringConfig
    journal: JournalConfig
    health_alerts: HealthAlertsConfig


@dataclass(frozen=True)
class SecretsConfig:
    mt5_login: int
    mt5_password: str
    mt5_server: str
    mt5_terminal_path: str | None
    telegram_bot_token: str
    telegram_chat_id: str
    heartbeat_ping_url: str


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
    session_filter_cfg = raw.get("session_filter", {})
    regime_filter_cfg = raw.get("regime_filter", {})
    risk_context_cfg = raw.get("risk_context", {})
    monitoring_cfg = raw.get("monitoring", {})
    journal_cfg = raw.get("journal", {})
    strategy_cfg = raw.get("strategy", {})
    health_alerts_cfg = raw.get("health_alerts", {})

    m1_only_cfg = raw.get("m1_only", {"enabled": False})
    if not isinstance(m1_only_cfg, dict):
        m1_only_cfg = {"enabled": False}
    if not isinstance(session_filter_cfg, dict):
        session_filter_cfg = {}
    if not isinstance(regime_filter_cfg, dict):
        regime_filter_cfg = {}
    if not isinstance(risk_context_cfg, dict):
        risk_context_cfg = {}
    if not isinstance(monitoring_cfg, dict):
        monitoring_cfg = {}
    if not isinstance(journal_cfg, dict):
        journal_cfg = {}
    if not isinstance(health_alerts_cfg, dict):
        health_alerts_cfg = {}
    if not isinstance(strategy_cfg, dict):
        strategy_cfg = {}
    chain_cfg = strategy_cfg.get("chain", {})
    if not isinstance(chain_cfg, dict):
        chain_cfg = {}
    summary_cfg = strategy_cfg.get("summary", {})
    if not isinstance(summary_cfg, dict):
        summary_cfg = {}

    session_windows_raw = session_filter_cfg.get(
        "windows",
        [
            {"start": "07:00", "end": "23:00"},
        ],
    )
    parsed_windows: list[SessionWindowConfig] = []
    if isinstance(session_windows_raw, list):
        for item in session_windows_raw:
            if not isinstance(item, dict):
                continue
            start = str(item.get("start", "07:00"))
            end = str(item.get("end", "23:00"))
            parsed_windows.append(SessionWindowConfig(start=start, end=end))
    if not parsed_windows:
        parsed_windows = [SessionWindowConfig(start="07:00", end="23:00")]

    rr_targets_raw = risk_context_cfg.get("rr_targets", [1.0, 2.0])
    parsed_rr_targets: tuple[float, float]
    if isinstance(rr_targets_raw, list) and len(rr_targets_raw) >= 2:
        parsed_rr_targets = (float(rr_targets_raw[0]), float(rr_targets_raw[1]))
    else:
        parsed_rr_targets = (1.0, 2.0)

    parsed_symbols = {str(k): str(v) for k, v in symbols.items()}
    if not parsed_symbols:
        raise ValueError("symbols cannot be empty")

    config = AppConfig(
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
            max_m15_backfill_bars=_to_int_min(
                execution_cfg.get("max_m15_backfill_bars", 16),
                "execution.max_m15_backfill_bars",
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
        strategy=StrategyConfig(
            enable_legacy_scenarios=bool(strategy_cfg.get("enable_legacy_scenarios", True)),
            chain=ChainStrategyConfig(
                enabled=bool(chain_cfg.get("enabled", True)),
                require_opposite_zone_on_lwma_cross=bool(
                    chain_cfg.get("require_opposite_zone_on_lwma_cross", True)
                ),
            ),
            summary=SummarySignalConfig(
                enabled=bool(summary_cfg.get("enabled", True)),
            ),
        ),
        session_filter=SessionFilterConfig(
            enabled=bool(session_filter_cfg.get("enabled", True)),
            timezone=str(session_filter_cfg.get("timezone", "Asia/Phnom_Penh")),
            windows=tuple(parsed_windows),
        ),
        regime_filter=RegimeFilterConfig(
            enabled=bool(regime_filter_cfg.get("enabled", False)),
            adx_period=_to_int_min(
                regime_filter_cfg.get("adx_period", 14), "regime_filter.adx_period", 1
            ),
            min_adx=float(regime_filter_cfg.get("min_adx", 25.0)),
        ),
        risk_context=RiskContextConfig(
            enabled=bool(risk_context_cfg.get("enabled", False)),
            atr_period=_to_int_min(
                risk_context_cfg.get("atr_period", 14), "risk_context.atr_period", 1
            ),
            atr_stop_multiplier=float(risk_context_cfg.get("atr_stop_multiplier", 1.0)),
            rr_targets=parsed_rr_targets,
        ),
        monitoring=MonitoringConfig(
            heartbeat_enabled=bool(monitoring_cfg.get("heartbeat_enabled", False)),
            heartbeat_interval_seconds=_to_int_min(
                monitoring_cfg.get("heartbeat_interval_seconds", 300),
                "monitoring.heartbeat_interval_seconds",
                1,
            ),
            heartbeat_ping_url=str(monitoring_cfg.get("heartbeat_ping_url", "")),
            heartbeat_file=Path(str(monitoring_cfg.get("heartbeat_file", "data/heartbeat.json"))),
        ),
        journal=JournalConfig(
            enabled=bool(journal_cfg.get("enabled", False)),
            sqlite_path=Path(str(journal_cfg.get("sqlite_path", "data/signals.db"))),
        ),
        health_alerts=HealthAlertsConfig(
            enabled=bool(health_alerts_cfg.get("enabled", False)),
            chat_id=str(health_alerts_cfg.get("chat_id", "")),
            throttle_minutes=_to_int_min(
                health_alerts_cfg.get("throttle_minutes", 15),
                "health_alerts.throttle_minutes",
                1,
            ),
        ),
    )

    _validate_config(config)
    return config


def _validate_config(config: AppConfig) -> None:
    """Cross-field validation for configuration consistency."""
    logger = logging.getLogger("settings")

    # lwma_fast must be less than lwma_slow
    if config.indicators.lwma_fast >= config.indicators.lwma_slow:
        raise ValueError(
            f"indicators.lwma.fast ({config.indicators.lwma_fast}) "
            f"must be less than indicators.lwma.slow ({config.indicators.lwma_slow})"
        )

    # buy_zone upper must be below sell_zone lower (zones must not overlap)
    if config.indicators.buy_zone[1] >= config.indicators.sell_zone[0]:
        raise ValueError(
            f"buy_zone upper ({config.indicators.buy_zone[1]}) "
            f"must be less than sell_zone lower ({config.indicators.sell_zone[0]})"
        )

    # candle_buffer must be enough for indicator warmup
    min_required = (
        max(
            config.indicators.lwma_slow,
            config.indicators.stoch_k,
        )
        + config.indicators.stoch_slowing
        + 2
    )
    if config.data.candle_buffer < min_required:
        raise ValueError(
            f"data.candle_buffer ({config.data.candle_buffer}) "
            f"must be >= {min_required} for indicator warmup "
            f"(lwma_slow={config.indicators.lwma_slow}, stoch_k={config.indicators.stoch_k}, "
            f"stoch_slowing={config.indicators.stoch_slowing})"
        )

    # atr_stop_multiplier sanity check (warning only)
    if config.risk_context.enabled:
        mult = config.risk_context.atr_stop_multiplier
        if mult < 0.5 or mult > 3.0:
            logger.warning(
                "risk_context.atr_stop_multiplier=%.2f is outside typical range [0.5, 3.0]",
                mult,
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
        heartbeat_ping_url=os.getenv("HEARTBEAT_PING_URL", ""),
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
    low = _parse_int_value(value[0], "stochastic zone lower bound")
    high = _parse_int_value(value[1], "stochastic zone upper bound")
    if low > high:
        raise ValueError("zone lower bound cannot be greater than upper bound")
    return (low, high)


def _to_int_min(value: Any, name: str, minimum: int) -> int:
    parsed = _parse_int_value(value, name)
    if parsed < minimum:
        raise ValueError(f"{name} must be >= {minimum}")
    return parsed


def _parse_int_value(value: object, name: str) -> int:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError as exc:
            raise ValueError(f"{name} must be an integer") from exc
    raise ValueError(f"{name} must be an integer")
