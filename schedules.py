"""日程与优先显示：今日下班 + 到点(可跨日)/时长自建项。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import attachments

OFFWORK_ID = "offwork"
MAX_PINS = 3


def ensure_fields(cfg: dict) -> None:
    if not isinstance(cfg.get("schedules"), list):
        cfg["schedules"] = []
    # 旧数据补 date
    for s in cfg["schedules"]:
        if not isinstance(s, dict):
            continue
        if s.get("kind") == "clock" and not s.get("date"):
            s["date"] = datetime.now().strftime("%Y-%m-%d")
        s["images"] = attachments.normalize(s.get("images"))
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


def _parse_date(raw: object) -> tuple[int, int, int] | None:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        d = datetime.strptime(raw.strip()[:10], "%Y-%m-%d")
        return d.year, d.month, d.day
    except ValueError:
        return None


def schedule_target(item: dict) -> datetime | None:
    if str(item.get("kind") or "") != "clock":
        return None
    hm = item.get("hm")
    if not isinstance(hm, (list, tuple)) or len(hm) != 2:
        return None
    try:
        h, m = int(hm[0]), int(hm[1])
    except (TypeError, ValueError):
        return None
    ymd = _parse_date(item.get("date"))
    if ymd is None:
        now = datetime.now()
        ymd = (now.year, now.month, now.day)
    y, mo, d = ymd
    try:
        return datetime(y, mo, d, h, m, 0)
    except ValueError:
        return None


def schedule_remaining(item: dict, now: datetime) -> tuple[int, bool]:
    """返回 (剩余秒绝对值, 是否到点)。"""
    kind = str(item.get("kind") or "")
    if kind == "clock":
        target = schedule_target(item)
        if target is None:
            return 0, True
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


def format_schedule_when(item: dict) -> str:
    """列表副标题用的时间描述。"""
    kind = str(item.get("kind") or "")
    if kind == "clock":
        target = schedule_target(item)
        if target is None:
            return ""
        return target.strftime("%m-%d %H:%M")
    if kind == "duration":
        try:
            mins = max(1, int(item.get("duration_sec") or 0) // 60)
        except (TypeError, ValueError):
            mins = 0
        return f"{mins}分钟"
    return ""


def new_clock(title: str, h: int, m: int, *, date: str | None = None) -> dict[str, Any]:
    day = date or datetime.now().strftime("%Y-%m-%d")
    return {
        "id": uuid.uuid4().hex[:12],
        "title": title.strip() or "日程",
        "kind": "clock",
        "date": day,
        "hm": [int(h), int(m)],
        "duration_sec": None,
        "started_at": None,
        "images": [],
    }


def new_duration(title: str, minutes: int, *, now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    sec = max(60, int(minutes) * 60)
    return {
        "id": uuid.uuid4().hex[:12],
        "title": title.strip() or "倒计时",
        "kind": "duration",
        "date": None,
        "hm": None,
        "duration_sec": sec,
        "started_at": now.isoformat(timespec="seconds"),
        "images": [],
    }


def find_schedule(cfg: dict, sid: str) -> dict | None:
    for s in cfg.get("schedules") or []:
        if isinstance(s, dict) and str(s.get("id")) == sid:
            return s
    return None


def add_schedule(cfg: dict, item: dict) -> None:
    ensure_fields(cfg)
    cfg["schedules"].append(item)


def replace_schedule(cfg: dict, item: dict) -> bool:
    sid = str(item.get("id") or "")
    if not sid:
        return False
    ensure_fields(cfg)
    for i, s in enumerate(cfg["schedules"]):
        if isinstance(s, dict) and str(s.get("id")) == sid:
            cfg["schedules"][i] = item
            return True
    return False


def matches(item: dict, query: str) -> bool:
    return attachments.matches(
        [str(item.get("title") or ""), format_schedule_when(item)],
        item.get("images"),
        query,
    )


def set_images(cfg: dict, sid: str, images: list[dict]) -> bool:
    item = find_schedule(cfg, sid)
    if item is None:
        return False
    item["images"] = attachments.normalize(images)
    return True


def remove_schedule(cfg: dict, sid: str) -> None:
    ensure_fields(cfg)
    if sid == OFFWORK_ID:
        return
    attachments.remove_owner("schedule", sid)
    cfg["schedules"] = [s for s in cfg["schedules"] if not (isinstance(s, dict) and str(s.get("id")) == sid)]
    cfg["pin_order"] = [p for p in cfg["pin_order"] if p != sid]
    if cfg.get("active_pin_id") == sid:
        cfg["active_pin_id"] = cfg["pin_order"][0] if cfg["pin_order"] else None


def is_pinned(cfg: dict, sid: str) -> bool:
    ensure_fields(cfg)
    return sid in cfg["pin_order"]


def set_pinned(cfg: dict, sid: str, pinned: bool) -> tuple[bool, str]:
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
    ensure_fields(cfg)
    pins = cfg["pin_order"]
    if not pins:
        return 0, 0
    aid = active_id(cfg)
    try:
        return pins.index(aid) + 1, len(pins)
    except ValueError:
        return 1, len(pins)
