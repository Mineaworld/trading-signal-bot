from __future__ import annotations

import argparse
import configparser
import subprocess
import sys
from pathlib import Path

from dotenv import dotenv_values


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="MT5 connectivity preflight")
    parser.add_argument("--env", type=Path, default=Path(".env"))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        env = _load_env(args.env)
    except Exception as exc:
        _print_result("env_load_error", str(exc))
        return 1

    required = ["MT5_LOGIN", "MT5_PASSWORD", "MT5_SERVER"]
    missing = [key for key in required if not env.get(key)]
    if missing:
        _print_result("missing_env", ",".join(missing))
        return 1

    try:
        import MetaTrader5 as mt5
    except Exception as exc:  # pragma: no cover - runtime dependency
        _print_result("metatrader5_import_error", str(exc))
        return 1

    terminal_path = env.get("MT5_TERMINAL_PATH") or ""
    initialized = False
    try:
        _print_result("terminal_process_running", _is_terminal_running())
        _print_result("configured_terminal_path", terminal_path or "<auto>")

        if terminal_path:
            initialized = bool(mt5.initialize(path=terminal_path))
        else:
            initialized = bool(mt5.initialize())
        _print_result("initialized", initialized)
        _print_result("last_error", mt5.last_error())
        if not initialized:
            _print_result(
                "hint",
                "if last_error is (-10005, 'IPC timeout'), keep MT5 open/connected and "
                "verify .env account/server plus MT5 API setting",
            )
            return 1

        login_ok = bool(
            mt5.login(
                login=int(env["MT5_LOGIN"]),
                password=env["MT5_PASSWORD"],
                server=env["MT5_SERVER"],
            )
        )
        _print_result("login", login_ok)
        _print_result("last_error", mt5.last_error())

        terminal_info = mt5.terminal_info()
        account_info = mt5.account_info()
        _print_result("terminal_info_present", terminal_info is not None)
        _print_result("account_info_present", account_info is not None)
        api_flag = _read_terminal_api_flag(terminal_info)
        _print_result("terminal_api_flag", api_flag)

        if account_info is None:
            _print_result("env_login_matches_active_account", False)
            _print_result("env_server_matches_active_server", False)
            return 1

        active_login = str(getattr(account_info, "login", ""))
        active_server = str(getattr(account_info, "server", ""))
        _print_result("active_account_login", active_login or "<unknown>")
        _print_result("active_account_server", active_server or "<unknown>")

        login_match = active_login == env["MT5_LOGIN"]
        server_match = active_server == env["MT5_SERVER"]
        _print_result("env_login_matches_active_account", login_match)
        _print_result("env_server_matches_active_server", server_match)

        api_enabled = api_flag == "1"
        _print_result("terminal_api_enabled", api_enabled)
        if not api_enabled:
            _print_result(
                "hint",
                "enable MT5 Tools > Options > Expert Advisors > API before running the bot",
            )
        return 0 if login_ok and login_match and server_match and api_enabled else 1
    finally:
        if initialized:
            try:
                mt5.shutdown()
            except Exception:
                pass


def _load_env(path: Path) -> dict[str, str]:
    if not path.exists():
        raise FileNotFoundError(f"env file not found: {path}")
    values = dotenv_values(path)
    result: dict[str, str] = {}
    for key, value in values.items():
        if key is None or value is None:
            continue
        result[str(key)] = str(value).strip()
    return result


def _is_terminal_running() -> bool:
    try:
        process = subprocess.run(
            ["tasklist", "/FI", "IMAGENAME eq terminal64.exe"],
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return False
    return "terminal64.exe" in process.stdout.lower()


def _read_terminal_api_flag(terminal_info: object) -> str:
    data_path = str(getattr(terminal_info, "data_path", "")).strip()
    if not data_path:
        return "unknown"
    common_ini = Path(data_path) / "config" / "common.ini"
    if not common_ini.exists():
        return "unknown"

    parser = configparser.ConfigParser()
    try:
        parser.read(common_ini, encoding="utf-8")
    except Exception:
        return "unknown"
    return parser.get("Experts", "Api", fallback="unknown")


def _print_result(name: str, value: object) -> None:
    print(f"{name}={value}")


if __name__ == "__main__":
    raise SystemExit(main())
