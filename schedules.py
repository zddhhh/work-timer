"""日程与优先显示：今日下班 + 到点/时长自建项。"""
from __future__ import annotations

import uuid
from datetime import datetime, timedelta
from typing import Any

OFFWORK_ID = "offwork"
MAX_PINS = 3


def ensure_fields(cfg: dict) -> None:
    if not isinstance(cfg.get("schedules"), list):
        cfg["schedules"] = []
    pins = cfg.get("pin_order")
    if not isinstance(pins, list):
        cfg["pin_order"] = [OFFWORK_ID]
    else:
        cfg["pin_order"] = [str(x) for x in pins if isinstance(x, str)][:MAX_PINS]
    if not isinstance(cfg.get("active_pin_id"), str):
        cfg["active_pin_id"] = None
    cfg["auto_rotate_pins"] = bool(cfg.get("auto_rotate_pins"))
    try:
        cfg["rotate_sec"] = max(3, min(60, int(cfg.get("rotate_sec") or 5)))
    except (TypeError, ValueError):
        cfg["rotate_sec"] = 5
    # 清理无效 pin
    valid = {OFFWORK_ID} | {str(s.get("id")) for s in cfg["schedules"] if isinstance(s, dict) and s.get("id")}
    cfg["pin_order"] = [p for p in cfg["pin_order"] if p in valid][:MAX_PINS]
    if cfg["active_pin_id"] not in cfg["pin_order"]:
        cfg["active_pin_id"] = cfg["pin_order"][0] if cfg["pin_order"] else None


def _parse_started(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw)
    except ValueError:
        return None


def schedule_remaining(item: dict, now: datetime) -> tuple[int, bool]:
    """返回 (剩余秒, 是否到点)。"""
    kind = str(item.get("kind") or "")
    if kind == "clock":
        hm = item.get("hm")
        if not isinstance(hm, (list, tuple)) or len(hm) != 2:
            return 0, True
        try:
            h, m = int(hm[0]), int(hm[1])
        except (TypeError, ValueError):
            return 0, True
        target = now.replace(hour=h, minute=m, second=0, microsecond=0)
        sec = int((target - now).total_seconds())
        return abs(sec), sec <= 0
    if kind == "duration":
        try:
            span = max(1, int(item.get("duration_sec") or 0))
        except (TypeError, ValueError):
            return 0, True
        started = _parse_started(item.get("started_at"))
        if started is None:
            return span, False
        left = span - int((now - started).total_seconds())
        return abs(left), left <= 0
    return 0, True


def new_clock(title: str, h: int, m: int) -> dict[str, Any]:
    return {
        "id": uuid.uuid4().hex[:12],
        "title": title.strip() or "日程",
        "kind": "clock",
        "hm": [int(h), int(m)],
        "duration_sec": None,
        "started_at": None,
    }


def new_duration(title: str, minutes: int, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    sec = max(60, int(minutes) * 60)
    return {
        "id": uuid.uuid4().hex[:12],
        "title": title.strip() or "倒计时",
        "kind": "duration",
        "hm": None,
        "duration_sec": sec,
        "started_at": now.isoformat(timespec="seconds"),
    }


def find_schedule(cfg: dict, sid: str) -> dict | None:
    for s in cfg.get("schedules") or []:
        if isinstance(s, dict) and str(s.get("id")) == sid:
            return s
    return None


def add_schedule(cfg: dict, item: dict) -> None:
    ensure_fields(cfg)
    cfg["schedules"].append(item)


def remove_schedule(cfg: dict, sid: str) -> None:
    ensure_fields(cfg)
    if sid == OFFWORK_ID:
        return
    cfg["schedules"] = [s for s in cfg["schedules"] if not (isinstance(s, dict) and str(s.get("id")) == sid)]
    cfg["pin_order"] = [p for p in cfg["pin_order"] if p != sid]
    if cfg.get("active_pin_id") == sid:
        cfg["active_pin_id"] = cfg["pin_order"][0] if cfg["pin_order"] else None


def is_pinned(cfg: dict, sid: str) -> bool:
    ensure_fields(cfg)
    return sid in cfg["pin_order"]


def set_pinned(cfg: dict, sid: str, pinned: bool) -> tuple[bool, str]:
    """返回 (ok, message)。"""
    ensure_fields(cfg)
    if pinned:
        if sid in cfg["pin_order"]:
            return True, ""
        if len(cfg["pin_order"]) >= MAX_PINS:
            return False, f"最多优先显示 {MAX_PINS} 项"
        cfg["pin_order"].append(sid)
        if not cfg.get("active_pin_id"):
            cfg["active_pin_id"] = sid
        return True, ""
    cfg["pin_order"] = [p for p in cfg["pin_order"] if p != sid]
    if cfg.get("active_pin_id") == sid:
        cfg["active_pin_id"] = cfg["pin_order"][0] if cfg["pin_order"] else None
    return True, ""


def cycle_active(cfg: dict) -> bool:
    """切换到下一个优先项；不足 2 个返回 False。"""
    ensure_fields(cfg)
    pins = cfg["pin_order"]
    if len(pins) < 2:
        return False
    cur = cfg.get("active_pin_id") or pins[0]
    try:
        i = pins.index(cur)
    except ValueError:
        i = 0
    cfg["active_pin_id"] = pins[(i + 1) % len(pins)]
    return True


def rotate_tick(cfg: dict, last_rotate: float, now_mono: float) -> bool:
    """若应轮播则切换并返回 True。"""
    ensure_fields(cfg)
    if not cfg.get("auto_rotate_pins"):
        return False
    if len(cfg["pin_order"]) < 2:
        return False
    if now_mono - last_rotate < float(cfg.get("rotate_sec") or 5):
        return False
    return cycle_active(cfg)


def active_id(cfg: dict) -> str | None:
    ensure_fields(cfg)
    if cfg["pin_order"]:
        aid = cfg.get("active_pin_id")
        if aid in cfg["pin_order"]:
            return aid
        return cfg["pin_order"][0]
    return None


def pin_index(cfg: dict) -> tuple[int, int]:
    """(当前序号从1, 总数)。"""
    ensure_fields(cfg)
    pins = cfg["pin_order"]
    if not pins:
        return 0, 0
    aid = active_id(cfg)
    try:
        return pins.index(aid) + 1, len(pins)
    except ValueError:
        return 1, len(pins)
