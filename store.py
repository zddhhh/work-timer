"""本机配置：上班时间、窗口位置、GitCode 更新地址。"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def app_dir() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)
    return Path(__file__).resolve().parent


def user_data_dir() -> Path:
    base = Path.home() / "AppData" / "Roaming" / "WorkTimer"
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    return user_data_dir() / "config.json"


def load_config() -> dict:
    defaults = {
        "start_h": None,
        "start_m": None,
        "start_date": "",
        "display_mode": "hms",
        "theme": "ghost",
        "win_x": None,
        "win_y": None,
        "gitcode_repo": "",
        "gitcode_token": "",
        "asset_name": "WorkTimer.exe",
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
        return merged
    except json.JSONDecodeError:
        return dict(defaults)


def save_config(cfg: dict) -> None:
    config_path().write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
