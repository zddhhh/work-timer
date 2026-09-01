"""弹性工时：8:30–9:30 到岗，对应 18:00–19:00 下班。"""
from __future__ import annotations

from datetime import datetime, timedelta

START_EARLIEST = (8, 30)
START_LATEST = (9, 30)
OFF_EARLIEST = (18, 0)
WORK_MINUTES = 9 * 60 + 30  # 固定 9.5 小时


def _hm_to_minutes(h: int, m: int) -> int:
    return int(h) * 60 + int(m)


def _minutes_to_hm(total: int) -> tuple[int, int]:
    total = int(total) % (24 * 60)
    return total // 60, total % 60


def clamp_start(h: int, m: int) -> tuple[int, int]:
    t = min(max(_hm_to_minutes(h, m), _hm_to_minutes(*START_EARLIEST)), _hm_to_minutes(*START_LATEST))
    return _minutes_to_hm(t)


def parse_clock(text: str) -> tuple[int, int] | None:
    """任意时刻：8.30 / 8:30 / 0830 / 8点30 / 18:00。"""
    raw = (text or "").strip().replace("：", ":").replace("．", ".").replace("点", ":")
    raw = raw.replace(" ", "")
    if not raw:
        return None
    h: str | None = None
    m: str | None = None
    if ":" in raw:
        a, b = raw.split(":", 1)
        h, m = a, b
    elif "." in raw:
        a, b = raw.split(".", 1)
        h, m = a, b
    elif raw.isdigit() and len(raw) in (3, 4):
        h, m = raw[:-2], raw[-2:]
    else:
        return None
    try:
        hh, mm = int(h), int(m)
    except ValueError:
        return None
    if mm < 0 or mm > 59 or hh < 0 or hh > 23:
        return None
    return hh, mm


def parse_start(text: str) -> tuple[int, int] | None:
    """到岗时间，夹到 8:30–9:30。"""
    parsed = parse_clock(text)
    if parsed is None:
        return None
    return clamp_start(*parsed)


def offwork_hm(start_h: int, start_m: int) -> tuple[int, int]:
    sh, sm = clamp_start(start_h, start_m)
    return _minutes_to_hm(_hm_to_minutes(sh, sm) + WORK_MINUTES)


def format_hm(h: int, m: int) -> str:
    return f"{int(h)}:{int(m):02d}"


def remaining_to(now: datetime, off_h: int, off_m: int) -> timedelta:
    """距今天下班时刻的剩余时间；已过则为负数。"""
    target = now.replace(hour=off_h, minute=off_m, second=0, microsecond=0)
    return target - now


def split_min_sec(td: timedelta) -> tuple[int, int, bool]:
    """返回 (分, 秒, 是否已到点)。分可以超过 60。"""
    total = int(td.total_seconds())
    done = total <= 0
    total = abs(total)
    return total // 60, total % 60, done


DISPLAY_MODES = ("hms", "min", "sec")
DISPLAY_LABELS = {
    "hms": "时分秒",
    "min": "分钟",
    "sec": "秒",
}


def next_display_mode(mode: str) -> str:
    modes = DISPLAY_MODES
    if mode not in modes:
        return modes[0]
    return modes[(modes.index(mode) + 1) % len(modes)]


def remaining_parts(td: timedelta) -> tuple[int, bool]:
    """返回 (总秒数绝对值, 是否已到点)。"""
    total = int(td.total_seconds())
    return abs(total), total <= 0


def format_remaining(total_seconds: int, mode: str) -> str:
    total = max(0, int(total_seconds))
    if mode == "sec":
        return f"{total}秒"
    if mode == "min":
        return f"{total // 60}分钟"
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}时{m}分{s:02d}秒"
