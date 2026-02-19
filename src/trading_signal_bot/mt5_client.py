from __future__ import annotations

import importlib
import logging
import random
import subprocess
import time
from dataclasses import dataclass
from typing import Any, cast

import pandas as pd

from trading_signal_bot.models import Timeframe


def _load_mt5_module() -> Any | None:
    """Load the optional MT5 runtime dependency only when needed."""
    try:
        return importlib.import_module("MetaTrader5")
    except Exception:  # pragma: no cover - runtime dependency on Windows MT5
        return None


@dataclass(frozen=True)
class ReconnectConfig:
    max_retries: int
    base_delay_seconds: int
    max_delay_seconds: int


class MT5Client:
    def __init__(
        self,
        login: int,
        password: str,
        server: str,
        path: str | None,
        alias_map: dict[str, str],
        reconnect: ReconnectConfig,
        mt5_module: Any | None = None,
    ) -> None:
        self._login = login
        self._password = password
        self._server = server
        self._path = path
        self._alias_map = alias_map
        self._reconnect = reconnect
        self._logger = logging.getLogger(self.__class__.__name__)
        mt5 = mt5_module if mt5_module is not None else _load_mt5_module()
        if mt5 is None:
            raise RuntimeError("MetaTrader5 package is unavailable in this environment.")
        self._mt5 = cast(Any, mt5)

    def startup_preflight(self) -> dict[str, str]:
        return {
            "terminal_path": self._path or "<auto>",
            "terminal_running": str(_is_process_running("terminal64.exe")),
        }

    def connect(self) -> bool:
        if self._path:
            initialized = bool(self._mt5.initialize(path=self._path))
        else:
            initialized = bool(self._mt5.initialize())
        if not initialized:
            last_error = self._mt5.last_error()
            self._logger.error(
                "mt5 initialize failed: path=%s terminal_running=%s error=%s",
                self._path or "<auto>",
                _is_process_running("terminal64.exe"),
                last_error,
            )
            if _extract_mt5_error_code(last_error) == -10005:
                self._logger.error(
                    "mt5 initialize IPC timeout (-10005). verify MT5 is open and connected, "
                    ".env MT5_LOGIN/MT5_SERVER match the active terminal account, and "
                    "MT5 Tools > Options > Expert Advisors > API is enabled."
                )
            return False

        logged_in = bool(
            self._mt5.login(
                login=self._login,
                password=self._password,
                server=self._server,
            )
        )
        if not logged_in:
            self._logger.error(
                "mt5 login failed: env_login=%s env_server=%s error=%s",
                self._login,
                self._server,
                self._last_error(),
            )
            self._mt5.shutdown()
            return False
        self._log_active_account()
        return True

    def disconnect(self) -> None:
        self._mt5.shutdown()

    def is_connected(self) -> bool:
        terminal = self._mt5.terminal_info()
        account = self._mt5.account_info()
        return terminal is not None and account is not None

    def reconnect(self) -> bool:
        for attempt in range(self._reconnect.max_retries):
            delay = min(
                self._reconnect.max_delay_seconds,
                self._reconnect.base_delay_seconds * (2**attempt),
            ) + random.uniform(0, 0.5)
            time.sleep(delay)
            try:
                self.disconnect()
            except Exception:
                pass
            if self.connect():
                self._logger.info("mt5 reconnected on attempt %s", attempt + 1)
                return True
            self._logger.warning("mt5 reconnect attempt %s failed", attempt + 1)
        return False

    def fetch_candles(self, symbol: str, timeframe: Timeframe, count: int = 450) -> pd.DataFrame:
        broker_symbol = self._resolve_symbol(symbol)
        if not self.is_connected() and not self.reconnect():
            raise RuntimeError("mt5 disconnected and reconnect failed")

        if self._mt5.symbol_info(broker_symbol) is None:
            raise RuntimeError(f"symbol unavailable in MT5: {broker_symbol}")
        self._mt5.symbol_select(broker_symbol, True)

        rates = self._mt5.copy_rates_from_pos(
            broker_symbol, self._to_mt5_timeframe(timeframe), 0, int(count)
        )
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"failed to fetch candles for {broker_symbol}: {self._last_error()}")

        df = pd.DataFrame(rates)
        if "time" not in df.columns:
            raise RuntimeError("MT5 response missing 'time' field")
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        expected = ["time", "open", "high", "low", "close", "tick_volume"]
        missing = [col for col in expected if col not in df.columns]
        if missing:
            raise RuntimeError(f"MT5 response missing required columns: {', '.join(missing)}")
        normalized = df[expected].sort_values("time").reset_index(drop=True)
        return cast(pd.DataFrame, normalized)

    def fetch_candles_from_pos(
        self,
        symbol: str,
        timeframe: Timeframe,
        start_pos: int,
        count: int,
    ) -> pd.DataFrame:
        broker_symbol = self._resolve_symbol(symbol)
        if not self.is_connected() and not self.reconnect():
            raise RuntimeError("mt5 disconnected and reconnect failed")

        if self._mt5.symbol_info(broker_symbol) is None:
            raise RuntimeError(f"symbol unavailable in MT5: {broker_symbol}")
        self._mt5.symbol_select(broker_symbol, True)

        rates = self._mt5.copy_rates_from_pos(
            broker_symbol,
            self._to_mt5_timeframe(timeframe),
            int(start_pos),
            int(count),
        )
        if rates is None or len(rates) == 0:
            raise RuntimeError(f"failed to fetch candles for {broker_symbol}: {self._last_error()}")

        df = pd.DataFrame(rates)
        if "time" not in df.columns:
            raise RuntimeError("MT5 response missing 'time' field")
        df["time"] = pd.to_datetime(df["time"], unit="s", utc=True)
        expected = ["time", "open", "high", "low", "close", "tick_volume"]
        missing = [col for col in expected if col not in df.columns]
        if missing:
            raise RuntimeError(f"MT5 response missing required columns: {', '.join(missing)}")
        normalized = df[expected].sort_values("time").reset_index(drop=True)
        return cast(pd.DataFrame, normalized)

    def get_current_price(self, symbol: str) -> float | None:
        broker_symbol = self._resolve_symbol(symbol)
        tick = self._mt5.symbol_info_tick(broker_symbol)
        if tick is None:
            return None
        for key in ("last", "bid", "ask"):
            value = getattr(tick, key, None)
            if value is not None:
                return float(value)
        return None

    def validate_symbol_aliases(self, alias_map: dict[str, str] | None = None) -> dict[str, bool]:
        mapping = alias_map if alias_map is not None else self._alias_map
        result: dict[str, bool] = {}
        for alias, broker_symbol in mapping.items():
            result[alias] = self._mt5.symbol_info(broker_symbol) is not None
        return result

    def is_symbol_tradable(self, symbol: str) -> bool:
        broker_symbol = self._resolve_symbol(symbol)
        info = self._mt5.symbol_info(broker_symbol)
        if info is None:
            return False
        trade_mode = getattr(info, "trade_mode", None)
        trade_mode_int = _to_int_or_none(trade_mode)
        if trade_mode_int is None:
            return False
        return trade_mode_int > 0

    def _resolve_symbol(self, alias_or_symbol: str) -> str:
        return self._alias_map.get(alias_or_symbol, alias_or_symbol)

    def _to_mt5_timeframe(self, timeframe: Timeframe) -> int:
        if timeframe == Timeframe.M1:
            value = _to_int_or_none(getattr(self._mt5, "TIMEFRAME_M1", None))
            if value is None:
                raise RuntimeError("MT5 TIMEFRAME_M1 constant is unavailable")
            return value
        if timeframe == Timeframe.M15:
            value = _to_int_or_none(getattr(self._mt5, "TIMEFRAME_M15", None))
            if value is None:
                raise RuntimeError("MT5 TIMEFRAME_M15 constant is unavailable")
            return value
        raise ValueError(f"unsupported timeframe: {timeframe}")

    def _last_error(self) -> str:
        err = self._mt5.last_error()
        return str(err)

    def _log_active_account(self) -> None:
        account = self._mt5.account_info()
        if account is None:
            self._logger.warning("mt5 login succeeded but account_info is unavailable")
            return
        active_login = getattr(account, "login", None)
        active_server = getattr(account, "server", None)
        self._logger.info(
            "mt5 active account login=%s server=%s env_match_login=%s env_match_server=%s",
            active_login,
            active_server,
            str(active_login) == str(self._login),
            str(active_server) == str(self._server),
        )


def _is_process_running(process_name: str) -> bool:
    if not process_name:
        return False
    try:
        result = subprocess.run(
            ["tasklist", "/FI", f"IMAGENAME eq {process_name}"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return process_name.lower() in result.stdout.lower()


def _extract_mt5_error_code(error: object) -> int | None:
    if isinstance(error, tuple) and error:
        code = error[0]
        parsed = _to_int_or_none(code)
        if parsed is not None:
            return parsed
    return None


def _to_int_or_none(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        try:
            return int(value)
        except ValueError:
            return None
    return None
