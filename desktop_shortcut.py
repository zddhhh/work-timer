"""桌面快捷方式：没有安装向导，首次落到本机时建一次。"""
from __future__ import annotations

import ctypes
import subprocess
import sys
from pathlib import Path

_LNK_NAME = "下班倒计时.lnk"
_CSIDL_DESKTOPDIRECTORY = 0x0010
_CREATE_NO_WINDOW = 0x08000000


def _desktop_dir() -> Path | None:
    buf = ctypes.create_unicode_buffer(260)
    try:
        hr = ctypes.windll.shell32.SHGetFolderPathW(None, _CSIDL_DESKTOPDIRECTORY, None, 0, buf)
    except OSError:
        hr = -1
    if hr == 0 and buf.value:
        p = Path(buf.value)
        if p.is_dir():
            return p
    fallback = Path.home() / "Desktop"
    return fallback if fallback.is_dir() else None


def _ps_quote(s: str) -> str:
    return "'" + str(s).replace("'", "''") + "'"


def _current_exe() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    try:
        return Path(sys.executable).resolve()
    except OSError:
        return None


def _run_ps(command: str) -> str:
    try:
        proc = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-WindowStyle",
                "Hidden",
                "-Command",
                command,
            ],
            capture_output=True,
            text=True,
            timeout=20,
            creationflags=_CREATE_NO_WINDOW,
            stdin=subprocess.DEVNULL,
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    out = (proc.stdout or "").strip()
    return out


def _read_target(lnk: Path) -> str:
    if not lnk.exists():
        return ""
    cmd = (
        "$w = New-Object -ComObject WScript.Shell; "
        f"$w.CreateShortcut({_ps_quote(str(lnk))}).TargetPath"
    )
    return _run_ps(cmd)


def _write_shortcut(lnk: Path, exe: Path) -> bool:
    cmd = (
        "$w = New-Object -ComObject WScript.Shell; "
        f"$s = $w.CreateShortcut({_ps_quote(str(lnk))}); "
        f"$s.TargetPath = {_ps_quote(str(exe))}; "
        f"$s.WorkingDirectory = {_ps_quote(str(exe.parent))}; "
        f"$s.IconLocation = {_ps_quote(str(exe) + ',0')}; "
        "$s.Description = '弹性下班计时器'; "
        "$s.Save()"
    )
    _run_ps(cmd)
    return lnk.exists()


def ensure(cfg: dict) -> bool:
    """首次运行建桌面快捷方式；用户删掉后不再建。目标路径变了则改现有 lnk。"""
    exe = _current_exe()
    if exe is None:
        return False
    desktop = _desktop_dir()
    if desktop is None:
        return False
    lnk = desktop / _LNK_NAME
    already = bool(cfg.get("desktop_shortcut_done"))
    if already and not lnk.exists():
        return False
    if lnk.exists():
        got = _read_target(lnk)
        try:
            same = Path(got).resolve() == exe if got else False
        except OSError:
            same = False
        if same:
            if not already:
                cfg["desktop_shortcut_done"] = True
                return True
            return False
    if not _write_shortcut(lnk, exe):
        return False
    cfg["desktop_shortcut_done"] = True
    return True
