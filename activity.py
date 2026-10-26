"""键鼠次数：只记敲了多少下、点了多少次，不记按了哪个键。"""
from __future__ import annotations

import math
import sys
from datetime import date, datetime, timedelta

KEEP_PRESETS = (7, 30, 60, 90)
DEFAULT_KEEP = 60
# 停这么久才在卡片上说一声。中间停一下去看屏幕，不该闪出来。
STILL_AFTER_S = 180
# 鼠标传感器每英寸大概多少计数。系统不报这只鼠标的真实档位，米数按这一档估算。
TRAVEL_CPI = 1600
# 连续操作的间隔。超过就换一段。不足最短时长的零星一下不进速度。
_KEY_GAP_S = 2.0
_KEY_MIN_S = 1.0
_WHEEL_GAP_S = 1.0
_WHEEL_MIN_S = 1.0
_MOVE_GAP_S = 0.3
_MOVE_MIN_S = 0.05
_PACE_KEYS = ("keys_pace", "wheels_pace", "travel_pace", "keys_ms", "wheels_ms", "travel_ms")
# 还没停手的那一段。只放内存，换一段或退出时才写进账。
_OPEN: dict[int, dict] = {}
_KEY = "activity"
# 64 位头 24 字节，32 位头 16 字节。RAWMOUSE 里 usFlags 后面对齐到 4，位移在其后 12、16 字节。
_HDR = 16 if sys.maxsize <= 2**32 else 24
_FLAG_AT = _HDR
_DX_AT = _HDR + 12
_DY_AT = _HDR + 16
_MOUSE_ABS = 0x01


def enabled(cfg: dict) -> bool:
    raw = cfg.get(_KEY)
    return bool(isinstance(raw, dict) and raw.get("on"))


def set_enabled(cfg: dict, on: bool) -> None:
    book = _book(cfg)
    book["on"] = bool(on)
    if not on:
        book["on_card"] = False


def show_on_card(cfg: dict) -> bool:
    """计时器上方显示今天的键盘、鼠标、滚轮次数。开着就一定在记。"""
    raw = cfg.get(_KEY)
    return bool(isinstance(raw, dict) and raw.get("on") and raw.get("on_card"))


def set_show_on_card(cfg: dict, on: bool) -> None:
    book = _book(cfg)
    book["on_card"] = bool(on)
    if on:
        book["on"] = True


def totals(cfg: dict, d: date) -> tuple[int, int, int]:
    """只取三个总数，不整理每小时的数组。主循环里常调，要便宜。"""
    raw = cfg.get(_KEY)
    days = raw.get("days") if isinstance(raw, dict) else None
    item = days.get(d.strftime("%Y-%m-%d")) if isinstance(days, dict) else None
    if not isinstance(item, dict):
        return 0, 0, 0
    return _n(item.get("keys")), _n(item.get("clicks")), _n(item.get("wheels"))


def _book(cfg: dict) -> dict:
    raw = cfg.get(_KEY)
    if not isinstance(raw, dict):
        raw = {"on": False, "days": {}}
        cfg[_KEY] = raw
    days = raw.get("days")
    if not isinstance(days, dict):
        raw["days"] = {}
    return raw


def keep_days(cfg: dict) -> int:
    raw = _book(cfg).get("keep_days")
    if raw in KEEP_PRESETS:
        return int(raw)
    return DEFAULT_KEEP


def set_keep_days(cfg: dict, days: int, *, today: date | None = None) -> int:
    book = _book(cfg)
    book["keep_days"] = days if days in KEEP_PRESETS else DEFAULT_KEEP
    kept = int(book["keep_days"])
    ensure_fields(cfg, today=today)
    import worklog

    worklog.ensure_fields(cfg, today=today, keep_days=kept)
    return kept


def ensure_fields(cfg: dict, *, today: date | None = None) -> None:
    book = _book(cfg)
    if book.get("keep_days") not in KEEP_PRESETS:
        book["keep_days"] = DEFAULT_KEEP
    cutoff = (today or date.today()) - timedelta(days=int(book["keep_days"]))
    cleaned: dict[str, dict] = {}
    days = book.get("days")
    if not isinstance(days, dict):
        days = {}
    for k, v in days.items():
        if not isinstance(k, str) or not isinstance(v, dict):
            continue
        try:
            d = datetime.strptime(k, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < cutoff:
            continue
        cleaned[k] = _clean_day(v)
    book["days"] = cleaned
    book["on"] = bool(book.get("on"))
    book["on_card"] = bool(book.get("on")) and bool(book.get("on_card"))


def _hours24(v) -> list[int]:
    if not isinstance(v, list) or len(v) != 24:
        return [0] * 24
    return [max(0, int(x)) if isinstance(x, int) and not isinstance(x, bool) else 0 for x in v]


def _clean_day(v: dict) -> dict:
    return {
        "keys": _n(v.get("keys")),
        "clicks": _n(v.get("clicks")),
        "wheels": _n(v.get("wheels")),
        "hours": _hours24(v.get("hours")),
        "keys_h": _hours24(v.get("keys_h")),
        "clicks_h": _hours24(v.get("clicks_h")),
        "wheels_h": _hours24(v.get("wheels_h")),
        "travel": _n(v.get("travel")),
        "travel_h": _hours24(v.get("travel_h")),
        "keys_pace": _hours24(v.get("keys_pace")),
        "wheels_pace": _hours24(v.get("wheels_pace")),
        "travel_pace": _hours24(v.get("travel_pace")),
        "keys_ms": _hours24(v.get("keys_ms")),
        "wheels_ms": _hours24(v.get("wheels_ms")),
        "travel_ms": _hours24(v.get("travel_ms")),
    }


def _n(v) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def _day(cfg: dict, d: date) -> dict:
    book = _book(cfg)
    days = book.setdefault("days", {})
    k = d.strftime("%Y-%m-%d")
    item = days.get(k)
    if not isinstance(item, dict):
        item = {
            "keys": 0,
            "clicks": 0,
            "wheels": 0,
            "hours": [0] * 24,
            "keys_h": [0] * 24,
            "clicks_h": [0] * 24,
            "wheels_h": [0] * 24,
            "travel": 0,
            "travel_h": [0] * 24,
        }
        days[k] = item
    for key in ("hours", "keys_h", "clicks_h", "wheels_h", "travel_h", *_PACE_KEYS):
        if not isinstance(item.get(key), list) or len(item[key]) != 24:
            item[key] = [0] * 24
    return item


def _slot(cfg: dict) -> dict:
    found = _OPEN.get(id(cfg))
    if found is None:
        found = {"key": None, "wheel": None, "move": None}
        _OPEN[id(cfg)] = found
    return found


def _slices(t0: datetime, t1: datetime):
    """一段时长按整点切开，得到 (日期, 小时, 毫秒)。"""
    cur = t0
    while cur < t1:
        nxt = min(t1, cur.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1))
        ms = int(round((nxt - cur).total_seconds() * 1000))
        if ms > 0 and 0 <= cur.hour < 24:
            yield cur.date(), cur.hour, ms
        cur = nxt


def _commit(cfg: dict, burst: dict, *, min_s: float, pace_key: str, ms_key: str) -> bool:
    dur = (burst["t1"] - burst["t0"]).total_seconds()
    if dur < min_s:
        return False
    wrote = False
    for day, hour, ms in _slices(burst["t0"], burst["t1"]):
        item = _day(cfg, day)
        item[ms_key][hour] = _n(item[ms_key][hour]) + ms
        wrote = True
    for (day, hour), n in burst["by"].items():
        if n <= 0 or not (0 <= hour < 24):
            continue
        item = _day(cfg, day)
        item[pace_key][hour] = _n(item[pace_key][hour]) + int(n)
        wrote = True
    return wrote


def _touch(cfg: dict, kind: str, when: datetime, n: int, *, gap: float, min_s: float, pace_key: str, ms_key: str) -> bool:
    slot = _slot(cfg)
    burst = slot.get(kind)
    wrote = False
    if burst is not None and (when - burst["t1"]).total_seconds() > gap:
        wrote = _commit(cfg, burst, min_s=min_s, pace_key=pace_key, ms_key=ms_key)
        burst = None
    if burst is None:
        burst = {"t0": when, "t1": when, "by": {}}
    key = (when.date(), when.hour)
    burst["by"][key] = int(burst["by"].get(key, 0)) + int(n)
    burst["t1"] = when
    slot[kind] = burst
    return wrote


def settle(cfg: dict, now: datetime | None = None) -> bool:
    """停手超过间隔的那一段，写进速度。还在连续操作的先留着。"""
    slot = _OPEN.get(id(cfg))
    if not slot:
        return False
    now = now or datetime.now()
    wrote = False
    for kind, gap, min_s, pace_key, ms_key in (
        ("key", _KEY_GAP_S, _KEY_MIN_S, "keys_pace", "keys_ms"),
        ("wheel", _WHEEL_GAP_S, _WHEEL_MIN_S, "wheels_pace", "wheels_ms"),
        ("move", _MOVE_GAP_S, _MOVE_MIN_S, "travel_pace", "travel_ms"),
    ):
        burst = slot.get(kind)
        if burst is None or (now - burst["t1"]).total_seconds() <= gap:
            continue
        if _commit(cfg, burst, min_s=min_s, pace_key=pace_key, ms_key=ms_key):
            wrote = True
        slot[kind] = None
    return wrote


def _pending(cfg: dict, day: date, now: datetime) -> dict:
    """还没停手、但已经够长的那段，先算进显示。"""
    extra = {key: [0] * 24 for key in _PACE_KEYS}
    slot = _OPEN.get(id(cfg)) or {}
    specs = (
        ("key", _KEY_MIN_S, "keys_pace", "keys_ms"),
        ("wheel", _WHEEL_MIN_S, "wheels_pace", "wheels_ms"),
        ("move", _MOVE_MIN_S, "travel_pace", "travel_ms"),
    )
    for kind, min_s, pace_key, ms_key in specs:
        burst = slot.get(kind)
        if not burst or (burst["t1"] - burst["t0"]).total_seconds() < min_s:
            continue
        end = burst["t1"] if burst["t1"] <= now else now
        if end <= burst["t0"]:
            continue
        for part_day, hour, ms in _slices(burst["t0"], end):
            if part_day == day:
                extra[ms_key][hour] += ms
        for (part_day, hour), n in burst["by"].items():
            if part_day == day and 0 <= hour < 24 and n > 0:
                extra[pace_key][hour] += int(n)
    return extra


def pace_of(cfg: dict, d: date, now: datetime | None = None) -> dict:
    """这一天各小时的速度材料，含还没写盘的当前这一段。"""
    now = now or datetime.now()
    settle(cfg, now)
    c = counts(cfg, d)
    extra = _pending(cfg, d, now)
    out = {}
    for key in _PACE_KEYS:
        out[key] = [_n(a) + _n(b) for a, b in zip(c[key], extra[key])]
    return out


def fmt_key_rate(count: int, ms: int) -> str:
    if ms < int(_KEY_MIN_S * 1000) or count <= 0:
        return "—"
    return f"{round(count * 60000 / ms)}下/分"


def fmt_wheel_rate(count: int, ms: int) -> str:
    if ms < int(_WHEEL_MIN_S * 1000) or count <= 0:
        return "—"
    return f"{round(count * 60000 / ms)}格/分"


def fmt_move_rate(steps: int, ms: int) -> str:
    if ms < int(_MOVE_MIN_S * 1000) or steps <= 0:
        return "—"
    cm_s = travel_meters(steps) * 100000 / ms
    if cm_s < 0.05:
        return "—"
    if cm_s < 10:
        return f"约 {cm_s:.1f} 厘米/秒"
    return f"约 {round(cm_s)} 厘米/秒"


def fmt_speed_line(keys: int, key_ms: int, travel: int, travel_ms: int, wheels: int, wheel_ms: int) -> str:
    return (
        f"打字 {fmt_key_rate(keys, key_ms)}"
        f"    鼠标 {fmt_move_rate(travel, travel_ms)}"
        f"    滚轮 {fmt_wheel_rate(wheels, wheel_ms)}"
    )


def note(cfg: dict, kind: str, now: datetime | None = None) -> bool:
    """记一次。kind 是 key / click / wheel。没开开关则什么都不做。"""
    if not enabled(cfg):
        return False
    if kind not in ("key", "click", "wheel"):
        return False
    now = now or datetime.now()
    item = _day(cfg, now.date())
    field = {"key": "keys", "click": "clicks", "wheel": "wheels"}[kind]
    item[field] = _n(item.get(field)) + 1
    h = now.hour
    if 0 <= h < 24:
        item["hours"][h] = _n(item["hours"][h]) + 1
        if kind == "key":
            item["keys_h"][h] = _n(item["keys_h"][h]) + 1
            _touch(cfg, "key", now, 1, gap=_KEY_GAP_S, min_s=_KEY_MIN_S, pace_key="keys_pace", ms_key="keys_ms")
        elif kind == "click":
            item["clicks_h"][h] = _n(item["clicks_h"][h]) + 1
        elif kind == "wheel":
            item["wheels_h"][h] = _n(item["wheels_h"][h]) + 1
            _touch(cfg, "wheel", now, 1, gap=_WHEEL_GAP_S, min_s=_WHEEL_MIN_S, pace_key="wheels_pace", ms_key="wheels_ms")
    return True


def counts(cfg: dict, d: date) -> dict:
    item = _book(cfg).get("days", {}).get(d.strftime("%Y-%m-%d"))
    if not isinstance(item, dict):
        return _clean_day({})
    return _clean_day(item)


def parse_raw(buf: bytes) -> str | None:
    """从 WM_INPUT 的原始缓冲里认出是键盘按下、鼠标点还是滚轮。不读键码。"""
    if len(buf) < 32:
        return None
    dw_type = int.from_bytes(buf[0:4], "little")
    if dw_type == 1:
        flags = int.from_bytes(buf[26:28], "little")
        if flags & 1:
            return None
        return "key"
    if dw_type == 0:
        buttons = int.from_bytes(buf[28:30], "little")
        if buttons & 0x0C00:
            return "wheel"
        if buttons & 0x0155:
            return "click"
        return None
    return None


def mouse_delta(buf: bytes) -> tuple[int, int] | None:
    """相对位移。绝对坐标（触摸板）和原地的包不算。"""
    if len(buf) < _DY_AT + 4 or int.from_bytes(buf[0:4], "little") != 0:
        return None
    flags = int.from_bytes(buf[_FLAG_AT:_FLAG_AT + 2], "little")
    if flags & _MOUSE_ABS:
        return None
    dx = int.from_bytes(buf[_DX_AT:_DX_AT + 4], "little", signed=True)
    dy = int.from_bytes(buf[_DY_AT:_DY_AT + 4], "little", signed=True)
    if dx == 0 and dy == 0:
        return None
    return dx, dy


def add_travel(cfg: dict, dx: int, dy: int, now: datetime | None = None) -> bool:
    """把这一小段滑行加进当天。单位是传感器计数，不是厘米。"""
    if not enabled(cfg):
        return False
    steps = int(round(math.hypot(dx, dy)))
    if steps <= 0:
        return False
    now = now or datetime.now()
    item = _day(cfg, now.date())
    item["travel"] = _n(item.get("travel")) + steps
    h = now.hour
    if 0 <= h < 24:
        item["travel_h"][h] = _n(item["travel_h"][h]) + steps
        _touch(
            cfg, "move", now, steps,
            gap=_MOVE_GAP_S, min_s=_MOVE_MIN_S, pace_key="travel_pace", ms_key="travel_ms",
        )
    return True


def travel_meters(counts: int) -> float:
    return _n(counts) * 0.0254 / TRAVEL_CPI


def fmt_travel(counts: int) -> str:
    """按 1600 计数/英寸估成一句长度。"""
    meters = travel_meters(counts)
    if counts <= 0 or meters < 0.001:
        return "约 0"
    if meters < 1:
        cm = meters * 100
        if cm < 10:
            return f"约 {cm:.1f} 厘米"
        return f"约 {round(cm)} 厘米"
    if meters < 10:
        return f"约 {meters:.1f} 米"
    if meters < 1000:
        return f"约 {round(meters)} 米"
    return f"约 {meters / 1000:.1f} 公里"


def chart_style(cfg: dict) -> str:
    raw = cfg.get(_KEY)
    style = raw.get("chart") if isinstance(raw, dict) else None
    return style if style in ("line", "bar") else "line"


def set_chart_style(cfg: dict, style: str) -> str:
    book = _book(cfg)
    book["chart"] = style if style in ("line", "bar") else "line"
    return str(book["chart"])


def still_phrase(idle_s: float) -> str | None:
    """手停够久才有一句。不到门槛、或还在动，就什么都不说。"""
    if idle_s < STILL_AFTER_S:
        return None
    minutes = int(idle_s // 60)
    if minutes < 60:
        return f"手停了 {minutes} 分钟"
    hours, rest = divmod(minutes, 60)
    if rest == 0:
        return f"手停了 {hours} 小时"
    return f"手停了 {hours} 小时 {rest} 分"


def fmt_count(n: int) -> str:
    n = max(0, int(n))
    if n >= 10000:
        t = f"{n / 10000:.1f}"
        if t.endswith(".0"):
            t = t[:-2]
        return t + " 万"
    return str(n)


def peak_hours(hours: list[int]) -> tuple[int, int] | None:
    """最勤的连续一到两小时。都是 0 则没有。"""
    if len(hours) != 24 or not any(hours):
        return None
    best_i, best = 0, -1
    for i, v in enumerate(hours):
        if v > best:
            best_i, best = i, v
    nxt = hours[best_i + 1] if best_i < 23 else 0
    prev = hours[best_i - 1] if best_i > 0 else 0
    if nxt >= prev and nxt * 2 >= best:
        return best_i, best_i + 2
    if prev * 2 >= best:
        return best_i - 1, best_i + 1
    return best_i, best_i + 1


def report_text(cfg: dict, d: date) -> str:
    if not enabled(cfg):
        return "还没开始记。"
    c = counts(cfg, d)
    keys, clicks, wheels = c["keys"], c["clicks"], c["wheels"]
    if keys == 0 and clicks == 0 and wheels == 0:
        return "已经在记了，这天还没有次数。"
    parts = [f"今天敲了 {fmt_count(keys)} 下键盘，点了 {fmt_count(clicks)} 次鼠标"]
    if wheels:
        parts[0] += f"，滚轮 {fmt_count(wheels)} 下"
    parts[0] += "。"
    peak = peak_hours(c["hours"])
    if peak is not None:
        a, b = peak
        if b - a == 1:
            parts.append(f"最勤的是 {a} 点这一小时。")
        else:
            parts.append(f"最勤的是 {a}–{b} 点。")
    return "".join(parts)
