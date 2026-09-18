"""本机配置：上班时间、窗口位置、GitCode 更新地址。"""
from __future__ import annotations

import json
import os
import sys
import time
import traceback
from datetime import datetime
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def user_data_dir() -> Path:
    base = Path.home() / "AppData" / "Roaming" / "WorkTimer"
    base.mkdir(parents=True, exist_ok=True)
    return base


def install_dir() -> Path:
    """稳定安装目录：不放微信/QQ 接收文件夹，OTA 才能换文件。"""
    base = Path.home() / "AppData" / "Local" / "WorkTimer"
    base.mkdir(parents=True, exist_ok=True)
    return base


def install_exe_path() -> Path:
    return install_dir() / "WorkTimer.exe"


def is_protected_exe_location(path: Path | str) -> bool:
    """微信/QQ 默认接收目录名。用户改过保存路径时可能对不上。"""
    s = "\\" + str(Path(path)).replace("/", "\\").lower().strip("\\") + "\\"
    markers = (
        "\\wechat files\\",
        "\\xwechat_files\\",
        "\\tencent files\\",
        "\\weixin files\\",
    )
    return any(m in s for m in markers)


def exe_dir_writable(exe: Path | str) -> bool:
    """在 exe 同目录试写一个小文件。微信自定义接收目录通常会拦。"""
    d = Path(exe).parent
    probe = d / "WorkTimer.write_test.tmp"
    try:
        probe.write_bytes(b"ok")
    except OSError:
        return False
    try:
        probe.unlink()
    except OSError:
        pass
    return True


def should_relocate_exe(path: Path | str) -> bool:
    """默认微信路径，或当前目录写不进文件，则搬到 LocalAppData。"""
    p = Path(path)
    try:
        if p.resolve() == install_exe_path().resolve():
            return False
    except OSError:
        pass
    if is_protected_exe_location(p):
        return True
    return not exe_dir_writable(p)


def config_path() -> Path:
    return user_data_dir() / "config.json"


def load_config() -> dict:
    defaults = {
        "start_h": None,
        "start_m": None,
        "off_h": None,
        "off_m": None,
        "time_mode": "flex",
        "start_date": "",
        "remember_offwork": True,
        "display_mode": "hms",
        "theme": "ghost",
        "win_w": 248,
        "win_h": 92,
        "ctrl_hide": False,
        "session_stale": False,
        "last_wall": "",
        "auto_start": False,
        "win_x": None,
        "win_y": None,
        "gitcode_repo": "",
        "gitcode_token": "",
        "asset_name": "WorkTimer.exe",
        "schedules": [],
        "memos": [],
        "pin_order": ["offwork"],
        "active_pin_id": "offwork",
        "auto_rotate_pins": False,
        "rotate_sec": 5,
    }
    bundled = app_dir() / "update_defaults.json"
    if bundled.exists():
        try:
            b = json.loads(bundled.read_text(encoding="utf-8"))
            if isinstance(b, dict):
                for k, v in b.items():
                    if v not in ("", None):
                        defaults[k] = v
        except json.JSONDecodeError:
            pass
    path = config_path()
    if not path.exists():
        return dict(defaults)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return dict(defaults)
        merged = dict(defaults)
        merged.update(data)
        if not (merged.get("gitcode_repo") or "").strip():
            merged["gitcode_repo"] = defaults.get("gitcode_repo", "")
        # 旧键 esc_disguise → ctrl_hide（功能早就是「单击 Ctrl 隐藏」，键名跟着改）
        if "ctrl_hide" not in data and "esc_disguise" in data:
            merged["ctrl_hide"] = bool(data.get("esc_disguise"))
        merged.pop("esc_disguise", None)
        return merged
    except json.JSONDecodeError:
        return dict(defaults)


_SAVE_MIN_GAP = 1.0  # 两次落盘最小间隔（秒）；期间的改动合并成一次
_pending: dict | None = None
_last_write = 0.0


def _write_config(cfg: dict) -> None:
    global _last_write
    out = dict(cfg)
    # 两个 token 都只从 update_defaults(.secret).json / 环境变量进内存，不落用户配置
    out.pop("feedback_token", None)
    out.pop("gitcode_token", None)
    path = config_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)
    _last_write = time.monotonic()


def save_config(cfg: dict, *, now: bool = False) -> None:
    """脏标记 + 节流落盘：距上次写入不足 1s 时先挂起，由主循环 flush_pending 收尾。

    cfg 始终是同一个 dict 引用，挂起期间的后续改动会一起写出去。
    """
    global _pending
    _pending = cfg
    if now or time.monotonic() - _last_write >= _SAVE_MIN_GAP:
        flush_pending(force=True)


def flush_pending(*, force: bool = False) -> bool:
    """主循环每帧调用；到期或 force 时把挂起的配置写盘。"""
    global _pending
    if _pending is None:
        return False
    if not force and time.monotonic() - _last_write < _SAVE_MIN_GAP:
        return False
    cfg, _pending = _pending, None
    try:
        _write_config(cfg)
    except OSError:
        pass
    return True


def append_log(message: str) -> None:
    try:
        path = user_data_dir() / "error.log"
        line = f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] {message}\n"
        if path.exists() and path.stat().st_size > 80_000:
            # 超限只砍掉前半，保留最近 40KB，别把上下文全丢了
            tail = path.read_bytes()[-40_000:]
            nl = tail.find(b"\n")
            if nl >= 0:
                tail = tail[nl + 1:]
            path.write_bytes(tail + line.encode("utf-8"))
        else:
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
    except OSError:
        pass


def log_exception(where: str, exc: BaseException) -> None:
    append_log(f"{where}: {exc}\n{traceback.format_exc()}")
