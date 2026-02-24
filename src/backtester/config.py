"""Backtester configuration: enums and run-level settings."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from pathlib import Path


class SignalMode(str, Enum):
    """Which signal evaluation pipeline to run."""

    LEGACY = "legacy"  # evaluate_all S1/S2
    CHAIN = "chain"  # evaluate_m15_triggers + advance_pending_setup
    M1 = "m1"  # evaluate_m1_only
    ALL = "all"  # union of all three, deduped


class ExitMode(str, Enum):
    """How to simulate trade exits."""

    SLTP = "sltp"  # SL/TP1 whichever first
    STOCH = "stoch"  # M15 stoch opposite zone (v2b)
    COMBINED = "combined"  # SL/TP + stoch + max_hold (v2b)
    TIME = "time"  # v1 legacy hold-and-close


@dataclass(frozen=True)
class BacktestConfig:
    """Run-level configuration for a single backtest."""

    symbol: str
    mode: SignalMode = SignalMode.LEGACY
    exit_mode: ExitMode = ExitMode.TIME
    hold_minutes: int = 240
    sl_mult: float | None = None
    rr1: float | None = 2.0  # backtester default 1:2 RR (does NOT touch global config)
    rr2: float | None = None
    output_dir: Path | None = None
