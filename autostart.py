"""开机自启动：写入当前用户 Run 注册表。"""
from __future__ import annotations

import sys
import winreg
from pathlib import Path

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "WorkTimer"


def launch_command() -> str:
    if getattr(sys, "frozen", False):
        return f'"{Path(sys.executable).resolve()}"'
    main = Path(__file__).resolve().parent / "main.py"
    py = Path(sys.executable).resolve()
    pythonw = py.with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else py
    return f'"{exe}" "{main}"'


def current_command() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            got = str(val or "").strip()
            return got or None
    except OSError:
        return None


def is_enabled() -> bool:
    return current_command() is not None


def set_enabled(on: bool) -> None:
    if on:
        cmd = launch_command()
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.SetValueEx(key, _VALUE_NAME, 0, winreg.REG_SZ, cmd)
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
    except FileNotFoundError:
        pass
    except OSError:
        # 值本就不存在
        err = sys.exc_info()[1]
        if getattr(err, "winerror", None) != 2:
            raise


def sync(on: bool) -> None:
    """只在开关或 exe 路径真的变了时写注册表。"""
    want = launch_command() if on else None
    if current_command() == want:
        return
    set_enabled(bool(on))
