"""定时喝水提醒：后台间隔，不占日程、不抢下班倒计时。"""
from __future__ import annotations

from datetime import datetime, timedelta

DEFAULT_INTERVAL = 45
MIN_INTERVAL = 15
MAX_INTERVAL = 180
PRESETS = (30, 45, 60, 90)


def defaults() -> dict:
    return {
        "enabled": False,
        "interval_min": DEFAULT_INTERVAL,
        "anchor": "",
        "pending": False,
    }


def clamp_interval(raw) -> int:
    try:
        n = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_INTERVAL
    return max(MIN_INTERVAL, min(MAX_INTERVAL, n))


def _parse_anchor(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        return datetime.fromisoformat(raw.strip())
    except ValueError:
        return None


def merge(raw) -> dict:
    base = defaults()
    if not isinstance(raw, dict):
        return base
    base["enabled"] = bool(raw.get("enabled"))
    base["interval_min"] = clamp_interval(raw.get("interval_min"))
    anc = raw.get("anchor")
    base["anchor"] = anc.strip() if isinstance(anc, str) else ""
    if _parse_anchor(base["anchor"]) is None:
        base["anchor"] = ""
    base["pending"] = bool(raw.get("pending"))
    return base


def ensure_fields(cfg: dict) -> dict:
    cfg["hydrate"] = merge(cfg.get("hydrate"))
    return cfg["hydrate"]


def read(cfg: dict) -> dict:
    return merge(cfg.get("hydrate"))


def enabled(cfg: dict) -> bool:
    return bool(read(cfg)["enabled"])


def interval_min(cfg: dict) -> int:
    return int(read(cfg)["interval_min"])


def set_enabled(cfg: dict, on: bool, *, now: datetime | None = None) -> bool:
    ensure_fields(cfg)
    cfg["hydrate"]["enabled"] = bool(on)
    if on:
        reset_anchor(cfg, now or datetime.now())
    else:
        cfg["hydrate"]["anchor"] = ""
        cfg["hydrate"]["pending"] = False
    return cfg["hydrate"]["enabled"]


def set_interval(cfg: dict, minutes: int, *, now: datetime | None = None) -> int:
    ensure_fields(cfg)
    cfg["hydrate"]["interval_min"] = clamp_interval(minutes)
    if cfg["hydrate"]["enabled"]:
        reset_anchor(cfg, now or datetime.now())
    return cfg["hydrate"]["interval_min"]


def arm(cfg: dict) -> None:
    """到点后停住，等用户点一下。不重开计时。"""
    ensure_fields(cfg)
    cfg["hydrate"]["pending"] = True


def reset_anchor(cfg: dict, now: datetime) -> None:
    ensure_fields(cfg)
    cfg["hydrate"]["anchor"] = now.replace(microsecond=0).isoformat(timespec="seconds")
    cfg["hydrate"]["pending"] = False


def shift_anchor(cfg: dict, delta: timedelta) -> None:
    """把本轮起点往后挪，剩余时间不变（离开座位暂停用）。"""
    ensure_fields(cfg)
    anc = _parse_anchor(cfg["hydrate"]["anchor"])
    if anc is None or delta.total_seconds() <= 0:
        return
    cfg["hydrate"]["anchor"] = (anc + delta).replace(microsecond=0).isoformat(timespec="seconds")


def elapsed_sec(cfg: dict, now: datetime) -> float | None:
    anc = _parse_anchor(read(cfg)["anchor"])
    if anc is None:
        return None
    return (now - anc).total_seconds()


def interval_sec(cfg: dict) -> int:
    return interval_min(cfg) * 60


def is_due(cfg: dict, now: datetime) -> bool:
    e = elapsed_sec(cfg, now)
    if e is None:
        return False
    return e >= interval_sec(cfg)


def is_stale(cfg: dict, now: datetime) -> bool:
    """没起点或跨日：重开一轮，不补催。同一天只积压一次（隐藏开会回来仍提醒）。"""
    anc = _parse_anchor(read(cfg)["anchor"])
    if anc is None:
        return True
    return anc.date() != now.date()


def decide(cfg: dict, now: datetime, *, hidden: bool = False, after_offwork: bool = False) -> str:
    """返回 `fire` / `none`。会改 pending；过期的 anchor 会重开。真正播完后由调用方 reset_anchor。"""
    ensure_fields(cfg)
    if not cfg["hydrate"]["enabled"]:
        return "none"
    if is_stale(cfg, now):
        reset_anchor(cfg, now)
        return "none"
    if after_offwork:
        cfg["hydrate"]["pending"] = False
        return "none"
    due = is_due(cfg, now)
    if hidden:
        if due:
            cfg["hydrate"]["pending"] = True
        return "none"
    if cfg["hydrate"]["pending"] or due:
        return "fire"
    return "none"


def menu_caption(cfg: dict) -> str:
    h = read(cfg)
    if not h["enabled"]:
        return "设置喝水间隔…"
    return f"设置喝水间隔…  （{h['interval_min']} 分钟）"
