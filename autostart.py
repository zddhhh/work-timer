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


def is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            return bool(str(val or "").strip())
    except OSError:
        return False


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
    """按配置对齐注册表（OTA 后也会刷新路径）。"""
    set_enabled(bool(on))
