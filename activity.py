"""键鼠次数：只记敲了多少下、点了多少次，不记按了哪个键。"""
from __future__ import annotations

from datetime import date, datetime, timedelta

KEEP_PRESETS = (7, 30, 60, 90)
DEFAULT_KEEP = 60
_KEY = "activity"


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
        }
        days[k] = item
    for key in ("hours", "keys_h", "clicks_h", "wheels_h"):
        if not isinstance(item.get(key), list) or len(item[key]) != 24:
            item[key] = [0] * 24
    return item


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
        elif kind == "click":
            item["clicks_h"][h] = _n(item["clicks_h"][h]) + 1
        elif kind == "wheel":
            item["wheels_h"][h] = _n(item["wheels_h"][h]) + 1
    return True


def counts(cfg: dict, d: date) -> dict:
    item = _book(cfg).get("days", {}).get(d.strftime("%Y-%m-%d"))
    if not isinstance(item, dict):
        return {
            "keys": 0,
            "clicks": 0,
            "wheels": 0,
            "hours": [0] * 24,
            "keys_h": [0] * 24,
            "clicks_h": [0] * 24,
            "wheels_h": [0] * 24,
        }
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
