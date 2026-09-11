"""开机自启动：用户「启动」文件夹里的快捷方式，避免写 Run 注册表触发安全软件。"""
from __future__ import annotations

import ctypes
import sys
import winreg
from pathlib import Path

import desktop_shortcut

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_VALUE_NAME = "WorkTimer"
_LNK_NAME = "WorkTimer.lnk"
_CSIDL_STARTUP = 0x0007


def _startup_dir() -> Path | None:
    buf = ctypes.create_unicode_buffer(260)
    try:
        hr = ctypes.windll.shell32.SHGetFolderPathW(None, _CSIDL_STARTUP, None, 0, buf)
    except OSError:
        hr = -1
    if hr == 0 and buf.value:
        p = Path(buf.value)
        if p.is_dir():
            return p
    fallback = Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup"
    return fallback if fallback.is_dir() else None


def _lnk_path() -> Path | None:
    d = _startup_dir()
    return (d / _LNK_NAME) if d is not None else None


def _wanted() -> tuple[Path, str]:
    if getattr(sys, "frozen", False):
        exe = Path(sys.executable).resolve()
        return exe, ""
    main = Path(__file__).resolve().parent / "main.py"
    py = Path(sys.executable).resolve()
    pythonw = py.with_name("pythonw.exe")
    exe = pythonw if pythonw.exists() else py
    return exe, f'"{main}"'


def _run_command() -> str | None:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, _VALUE_NAME)
            got = str(val or "").strip()
            return got or None
    except OSError:
        return None


def _clear_run_key() -> None:
    if _run_command() is None:
        return
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0, winreg.KEY_SET_VALUE) as key:
            winreg.DeleteValue(key, _VALUE_NAME)
    except FileNotFoundError:
        pass
    except OSError:
        err = sys.exc_info()[1]
        if getattr(err, "winerror", None) != 2:
            raise


def _lnk_matches(lnk: Path, exe: Path) -> bool:
    got = desktop_shortcut._read_target(lnk)
    if not got:
        return False
    try:
        return Path(got).resolve() == exe.resolve()
    except OSError:
        return False


def is_enabled() -> bool:
    lnk = _lnk_path()
    if lnk is not None and lnk.exists():
        return True
    return _run_command() is not None


def set_enabled(on: bool) -> None:
    _clear_run_key()
    lnk = _lnk_path()
    if lnk is None:
        raise OSError("找不到系统启动文件夹")
    if not on:
        try:
            lnk.unlink(missing_ok=True)
        except OSError:
            pass
        return
    exe, arguments = _wanted()
    lnk.parent.mkdir(parents=True, exist_ok=True)
    if not desktop_shortcut._write_shortcut(lnk, exe, arguments=arguments):
        raise OSError("写入启动快捷方式失败")


def sync(on: bool) -> None:
    """只在开关或 exe 路径真的变了时改启动项；并清掉旧的 Run 注册表。"""
    has_run = _run_command() is not None
    lnk = _lnk_path()
    exe, _arguments = _wanted()
    if on:
        already = lnk is not None and lnk.exists() and _lnk_matches(lnk, exe)
        if already and not has_run:
            return
        set_enabled(True)
        return
    if (lnk is None or not lnk.exists()) and not has_run:
        return
    set_enabled(False)
