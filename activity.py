"""键鼠次数：记敲了多少下、点了多少次，以及每个键各按了多少下。不记按键顺序。"""
from __future__ import annotations

import ctypes
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
_CLICK_GAP_S = 2.0
_CLICK_MIN_S = 1.0
_WHEEL_GAP_S = 1.0
_WHEEL_MIN_S = 1.0
_MOVE_GAP_S = 0.3
_MOVE_MIN_S = 0.05
# 瞬时是此刻这一秒。这一秒里没有操作就是 0，不沿用刚才那一段。
_INST_WINDOW_S = 1.0
_INST_GAP_S = _INST_WINDOW_S
_INST_CAP = 20000
# 过了当天的瞬时点，同一段里大约这么多秒留一个。图上一格两像素就是几分钟，看不出差别。
_THIN_STEP_S = 20
_PACE_KEYS = (
    "keys_pace", "clicks_pace", "wheels_pace", "travel_pace",
    "keys_ms", "clicks_ms", "wheels_ms", "travel_ms",
)
_LAST_KEYS = (
    "keys_last", "clicks_last", "wheels_last", "travel_last",
    "keys_last_ms", "clicks_last_ms", "wheels_last_ms", "travel_last_ms",
)
_INST_FIELDS = ("inst_key", "inst_click", "inst_wheel", "inst_move")
# 曲线采样、小时平均、最近一段，四种操作各走同一行。
_SPEED_KINDS = (
    ("key", _KEY_GAP_S, _KEY_MIN_S, "keys_pace", "keys_ms", "keys_last", "keys_last_ms", "inst_key"),
    ("click", _CLICK_GAP_S, _CLICK_MIN_S, "clicks_pace", "clicks_ms", "clicks_last", "clicks_last_ms", "inst_click"),
    ("wheel", _WHEEL_GAP_S, _WHEEL_MIN_S, "wheels_pace", "wheels_ms", "wheels_last", "wheels_last_ms", "inst_wheel"),
    ("move", _MOVE_GAP_S, _MOVE_MIN_S, "travel_pace", "travel_ms", "travel_last", "travel_last_ms", "inst_move"),
)
CARD_CHOICES = (
    ("keys", "键盘次数"),
    ("clicks", "点击次数"),
    ("wheels", "滚轮次数"),
    ("travel", "移动距离"),
    ("key_now", "打字瞬时"),
    ("click_now", "点击瞬时"),
    ("move_now", "移动瞬时"),
    ("wheel_now", "滚轮瞬时"),
    ("key_hour", "打字均速"),
    ("click_hour", "点击均速"),
    ("move_hour", "移动均速"),
    ("wheel_hour", "滚轮均速"),
)
_CARD_LABEL = dict(CARD_CHOICES)
_CARD_ID = {label: key for key, label in CARD_CHOICES}
CHART_VIEWS = ("counts", "avg", "inst")
# 还没停手的那一段。只放内存，换一段或退出时才写进账。
_OPEN: dict[int, dict] = {}
_KEY = "activity"
# 64 位头 24 字节，32 位头 16 字节。RAWMOUSE 里 usFlags 后面对齐到 4，位移在其后 12、16 字节。
_HDR = 16 if sys.maxsize <= 2**32 else 24
_DEVICE_AT = 8
_DEVICE_SIZE = 4 if sys.maxsize <= 2**32 else 8
_FLAG_AT = _HDR
_KEY_FLAGS_AT = _HDR + 2
_KEY_VK_AT = _HDR + 6
_BUTTON_FLAGS_AT = _HDR + 4
_DX_AT = _HDR + 12
_DY_AT = _HDR + 16
_MOUSE_ABS = 0x01
# Set 1 扫描码 → 图上的键号。按物理键记，不跟 NumLock、输入法走。
# 小键盘 4 永远是 64，不会在关 NumLock 时记成左方向。
_SCAN = {
    0x01: "1B",
    0x02: "31", 0x03: "32", 0x04: "33", 0x05: "34", 0x06: "35",
    0x07: "36", 0x08: "37", 0x09: "38", 0x0A: "39", 0x0B: "30",
    0x0C: "BD", 0x0D: "BB", 0x0E: "08", 0x0F: "09",
    0x10: "51", 0x11: "57", 0x12: "45", 0x13: "52", 0x14: "54",
    0x15: "59", 0x16: "55", 0x17: "49", 0x18: "4F", 0x19: "50",
    0x1A: "DB", 0x1B: "DD", 0x1C: "0D", 0x1D: "A2",
    0x1E: "41", 0x1F: "53", 0x20: "44", 0x21: "46", 0x22: "47",
    0x23: "48", 0x24: "4A", 0x25: "4B", 0x26: "4C",
    0x27: "BA", 0x28: "DE", 0x29: "C0", 0x2A: "A0", 0x2B: "DC",
    0x2C: "5A", 0x2D: "58", 0x2E: "43", 0x2F: "56", 0x30: "42",
    0x31: "4E", 0x32: "4D", 0x33: "BC", 0x34: "BE", 0x35: "BF",
    0x36: "A1", 0x37: "6A", 0x38: "A4", 0x39: "20", 0x3A: "14",
    0x3B: "70", 0x3C: "71", 0x3D: "72", 0x3E: "73", 0x3F: "74",
    0x40: "75", 0x41: "76", 0x42: "77", 0x43: "78", 0x44: "79",
    0x45: "90", 0x46: "91",
    0x47: "67", 0x48: "68", 0x49: "69", 0x4A: "6D",
    0x4B: "64", 0x4C: "65", 0x4D: "66", 0x4E: "6B",
    0x4F: "61", 0x50: "62", 0x51: "63", 0x52: "60", 0x53: "6E",
    0x57: "7A", 0x58: "7B",
}
_SCAN_E0 = {
    0x1C: "numenter",
    0x1D: "A3",
    0x35: "6F",
    0x37: "2C",
    0x38: "A5",
    0x47: "24", 0x48: "26", 0x49: "21",
    0x4B: "25", 0x4D: "27",
    0x4F: "23", 0x50: "28", 0x51: "22",
    0x52: "2D", 0x53: "2E",
    0x5B: "5B", 0x5C: "5C", 0x5D: "5D",
}
# PrintScreen / 小键盘会夹带的假 Shift，不是人按的。
_FAKE_E0 = frozenset({0x2A, 0x36})
_down: set[int] = set()
_e1 = False


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


def total_travel(cfg: dict, d: date) -> int:
    """只取移动总计，不整理每小时数组，供主卡高频刷新。"""
    raw = cfg.get(_KEY)
    days = raw.get("days") if isinstance(raw, dict) else None
    item = days.get(d.strftime("%Y-%m-%d")) if isinstance(days, dict) else None
    return _n(item.get("travel")) if isinstance(item, dict) else 0


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
        item = _clean_day(v)
        if d < (today or date.today()):
            _thin_day(item)
        cleaned[k] = item
    book["days"] = cleaned
    book["on"] = bool(book.get("on"))
    book["on_card"] = bool(book.get("on")) and bool(book.get("on_card"))
    zones = set(z for z in (book.get("heat_zones") or []) if z in ("nav", "num", "extra"))
    for item in cleaned.values():
        for ident in item.get("keymap") or {}:
            z = key_zone(str(ident))
            if z != "main":
                zones.add(z)
    book["heat_zones"] = sorted(zones)


def _hours24(v) -> list[int]:
    if type(v) is not list or len(v) != 24:
        return [0] * 24
    return [x if type(x) is int and x > 0 else 0 for x in v]


def _clean_inst(v) -> list:
    if not isinstance(v, list):
        return []
    out: list[list[int]] = []
    last = 0
    # 启动时整本过一遍，几万行。type(...) is int 顺带排除了 bool。
    for row in v[-_INST_CAP:]:
        kind = type(row)
        if (kind is not list and kind is not tuple) or len(row) != 3:
            continue
        sec, n, ms = row
        if type(sec) is not int or type(n) is not int or type(ms) is not int:
            continue
        if sec < last or sec > 86399 or n <= 0 or ms <= 0:
            continue
        out.append(row if kind is list else [sec, n, ms])
        last = sec
    return out


def same_stretch(prev, sec: int, ms: int) -> bool:
    """上一个点的时长还在往上加，才是同一段。新的一段时长会重新变小。"""
    psec, _pn, pms = prev[0], prev[1], prev[2]
    if sec < psec:
        return False
    expected = pms + (sec - psec) * 1000
    return ms + 1500 >= pms and ms >= expected * 0.5


def thin_inst(rows: list, step: int = _THIN_STEP_S) -> list:
    """同一段里隔 step 秒左右留一个点。段头段尾都留着，读的人按原样分段。"""
    if len(rows) <= 2:
        return rows
    out = [rows[0]]
    kept = rows[0]
    prev = rows[0]
    cand = None
    for row in rows[1:]:
        if not same_stretch(prev, row[0], row[2]):
            if cand is not None:
                out.append(cand)
            out.append(row)
            kept, cand = row, None
        else:
            if cand is not None and (row[0] - kept[0] > step or not same_stretch(kept, row[0], row[2])):
                out.append(cand)
                kept = cand
            cand = row
        prev = row
    if cand is not None:
        out.append(cand)
    return out


def _thin_day(item: dict) -> bool:
    if item.get("inst_thin"):
        return False
    for key in _INST_FIELDS:
        item[key] = thin_inst(item.get(key) or [])
    item["inst_thin"] = True
    return True


_THINNED: dict[int, date] = {}


def thin_past(cfg: dict, today: date) -> bool:
    """跨天后把前几天的瞬时点压稀一次。配置文件不会越攒越大。"""
    if _THINNED.get(id(cfg)) == today:
        return False
    _THINNED[id(cfg)] = today
    wrote = False
    for k, item in (_book(cfg).get("days") or {}).items():
        if not isinstance(item, dict) or item.get("inst_thin"):
            continue
        try:
            d = datetime.strptime(k, "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < today and _thin_day(item):
            wrote = True
    return wrote


def _view_day(v: dict) -> dict:
    """读用。小时数组照样整理，瞬时点直接给原列表，调用方不许改。"""
    item = _clean_day(v, inst=False)
    for key in _INST_FIELDS:
        rows = v.get(key)
        item[key] = rows if isinstance(rows, list) else []
    return item


def _clean_day(v: dict, *, inst: bool = True) -> dict:
    item = {
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
        "clicks_pace": _hours24(v.get("clicks_pace")),
        "wheels_pace": _hours24(v.get("wheels_pace")),
        "travel_pace": _hours24(v.get("travel_pace")),
        "keys_ms": _hours24(v.get("keys_ms")),
        "clicks_ms": _hours24(v.get("clicks_ms")),
        "wheels_ms": _hours24(v.get("wheels_ms")),
        "travel_ms": _hours24(v.get("travel_ms")),
        "keymap": _clean_keymap(v.get("keymap")),
    }
    for key in _LAST_KEYS:
        item[key] = _hours24(v.get(key))
    if inst:
        for key in _INST_FIELDS:
            item[key] = _clean_inst(v.get(key))
        if v.get("inst_thin"):
            item["inst_thin"] = True
    return item


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
    for key in ("hours", "keys_h", "clicks_h", "wheels_h", "travel_h", *_PACE_KEYS, *_LAST_KEYS):
        if not isinstance(item.get(key), list) or len(item[key]) != 24:
            item[key] = [0] * 24
    for key in _INST_FIELDS:
        if not isinstance(item.get(key), list):
            item[key] = []
    return item


def _slot(cfg: dict) -> dict:
    found = _OPEN.get(id(cfg))
    if found is None:
        found = {"key": None, "click": None, "wheel": None, "move": None}
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
    _trail_add(burst, when, int(n))
    slot[kind] = burst
    return wrote


def _trail_add(burst: dict, when: datetime, n: int) -> None:
    """最近几秒的每一下。同一小段里的下数并在一起，避免鼠标移动把列表撑满。"""
    trail = burst.get("trail")
    if not isinstance(trail, list):
        trail = []
        burst["trail"] = trail
    if trail and (when - trail[-1][1]).total_seconds() < 0.25:
        trail[-1][1] = when
        trail[-1][2] = int(trail[-1][2]) + n
    else:
        trail.append([when, when, n])
    limit = when - timedelta(seconds=_INST_WINDOW_S + 1.0)
    while len(trail) > 1 and trail[0][1] < limit:
        del trail[0]


def _window_pair(burst: dict, now: datetime | None = None) -> tuple[int, int]:
    """此刻往前 1 秒里的次数。这一秒是空的就返回 0，不用更早的记录顶上。"""
    end = now or burst["t1"]
    limit = end - timedelta(seconds=_INST_WINDOW_S)
    n = 0
    for row in burst.get("trail") or []:
        if row[1] < limit or row[0] > end:
            continue
        n += int(row[2])
    if n <= 0:
        return 0, 0
    return n, int(_INST_WINDOW_S * 1000)


def _burst_point(burst: dict) -> tuple[int, int, int]:
    n = sum(int(v) for v in burst["by"].values() if isinstance(v, int) and not isinstance(v, bool) and v > 0)
    ms = int(round((burst["t1"] - burst["t0"]).total_seconds() * 1000))
    end = burst["t1"]
    return end.hour * 3600 + end.minute * 60 + end.second, n, ms


def _remember_last(cfg: dict, burst: dict, *, min_s: float, n_key: str, ms_key: str) -> bool:
    if (burst["t1"] - burst["t0"]).total_seconds() < min_s:
        return False
    n, ms = _window_pair(burst)
    if ms < int(min_s * 1000) or n <= 0:
        _sec, n, ms = _burst_point(burst)
    if n <= 0 or ms <= 0:
        return False
    hour = burst["t1"].hour
    if not 0 <= hour < 24:
        return False
    item = _day(cfg, burst["t1"].date())
    item[n_key][hour] = n
    item[ms_key][hour] = ms
    return True


def _sample_inst(cfg: dict, burst: dict, *, min_s: float, inst_key: str, force: bool) -> bool:
    """同一段里大约每秒留一个点。段结束时把最后一个点改成这段的最终累计。"""
    if (burst["t1"] - burst["t0"]).total_seconds() < min_s:
        return False
    sec, n, ms = _burst_point(burst)
    if n <= 0 or ms <= 0:
        return False
    item = _day(cfg, burst["t1"].date())
    rows = item.get(inst_key)
    if not isinstance(rows, list):
        rows = []
        item[inst_key] = rows
    t0 = burst["t0"]
    t0_sec = t0.hour * 3600 + t0.minute * 60 + t0.second
    if t0.date() != burst["t1"].date():
        t0_sec = 0
    same = bool(rows) and int(rows[-1][0]) >= t0_sec
    if same and sec - int(rows[-1][0]) < _INST_GAP_S:
        if not force:
            return False
        rows[-1] = [sec, n, ms]
        return True
    if rows and sec < int(rows[-1][0]):
        return False
    rows.append([sec, n, ms])
    if len(rows) > _INST_CAP:
        # 一次多砍一截：开头一变，图表的增量缓存就得从头算。
        del rows[: len(rows) - _INST_CAP + 500]
    return True


def settle(cfg: dict, now: datetime | None = None) -> bool:
    """停手超过间隔的那一段，写进平均速度。够长的段同时留下瞬时曲线的点。"""
    now = now or datetime.now()
    wrote = thin_past(cfg, now.date())
    slot = _OPEN.get(id(cfg))
    if not slot:
        return wrote
    for kind, gap, min_s, pace_key, ms_key, last_n, last_ms, inst_key in _SPEED_KINDS:
        burst = slot.get(kind)
        if burst is None:
            continue
        if (now - burst["t1"]).total_seconds() <= gap:
            if _sample_inst(cfg, burst, min_s=min_s, inst_key=inst_key, force=False):
                wrote = True
            continue
        if _commit(cfg, burst, min_s=min_s, pace_key=pace_key, ms_key=ms_key):
            wrote = True
        if _remember_last(cfg, burst, min_s=min_s, n_key=last_n, ms_key=last_ms):
            wrote = True
        if _sample_inst(cfg, burst, min_s=min_s, inst_key=inst_key, force=True):
            wrote = True
        slot[kind] = None
    return wrote


def _pending(cfg: dict, day: date, now: datetime) -> dict:
    """还没停手、但已经够长的那段，先算进显示。"""
    extra = {key: [0] * 24 for key in _PACE_KEYS}
    slot = _OPEN.get(id(cfg)) or {}
    specs = (
        ("key", _KEY_MIN_S, "keys_pace", "keys_ms"),
        ("click", _CLICK_MIN_S, "clicks_pace", "clicks_ms"),
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


def pace_of(cfg: dict, d: date, now: datetime | None = None, *, c: dict | None = None) -> dict:
    """这一天各小时的速度材料，含还没写盘的当前这一段。

    传了 c（counts 的结果）就当调用方已经 settle 过，不再重取。
    """
    now = now or datetime.now()
    if c is None:
        settle(cfg, now)
        c = counts(cfg, d)
    extra = _pending(cfg, d, now)
    out = {}
    for key in _PACE_KEYS:
        out[key] = [_n(a) + _n(b) for a, b in zip(c[key], extra[key])]
    return out


def inst_rows(cfg: dict, d: date, now: datetime | None = None, *, c: dict | None = None) -> dict:
    """这一天的瞬时采样。正在进行、已经够长的那段补在最后，不写盘。"""
    now = now or datetime.now()
    if c is None:
        c = counts(cfg, d)
    if now.date() != d:
        return {key: c[key] for key in _INST_FIELDS}
    # 只复制列表外壳：下面补的点不能写回账里。
    out = {key: list(c[key]) for key in _INST_FIELDS}
    slot = _OPEN.get(id(cfg)) or {}
    for kind, _gap, min_s, _pace, _ms, _ln, _lm, inst_key in _SPEED_KINDS:
        burst = slot.get(kind)
        if not burst or burst["t1"].date() != d:
            continue
        if (burst["t1"] - burst["t0"]).total_seconds() < min_s:
            continue
        sec, n, ms = _burst_point(burst)
        if n <= 0 or ms <= 0:
            continue
        rows = out[inst_key]
        if rows and sec <= int(rows[-1][0]):
            continue
        rows.append([sec, n, ms])
    return out


def _live_pair(cfg: dict, kind: str, now: datetime) -> tuple[int, int]:
    """正在做就是这一秒的速度，停了就是 0。不退回上一段。"""
    burst = (_OPEN.get(id(cfg)) or {}).get(kind)
    if not burst or burst["t1"].date() != now.date():
        return 0, 0
    if (now - burst["t1"]).total_seconds() > _INST_WINDOW_S:
        return 0, 0
    return _window_pair(burst, now)


def live_intensity(cfg: dict, now: datetime | None = None) -> float:
    """这一秒键+点+滚的合计次数/秒。停手是 0。给盘口 K 线用。"""
    now = now or datetime.now()
    total = 0.0
    for kind in ("key", "click", "wheel"):
        n, ms = _live_pair(cfg, kind, now)
        if n > 0 and ms > 0:
            total += n * 1000.0 / ms
    return total


def speed_snapshot(cfg: dict, now: datetime | None = None) -> dict:
    """主界面用的瞬时和当前小时平均。调用前应先 settle。"""
    now = now or datetime.now()
    c = counts(cfg, now.date())
    extra = _pending(cfg, now.date(), now)
    hour = now.hour if 0 <= now.hour < 24 else 0

    count_of = {
        "key": "keys_h", "click": "clicks_h", "wheel": "wheels_h", "move": "travel_h",
    }
    out = {}
    for kind, _gap, _min_s, _pace, ms_key, _last_n, _last_ms, _inst in _SPEED_KINDS:
        out[kind] = _live_pair(cfg, kind, now)
        # 均速的分子用这一小时的总次数，分母用实际操作的毫秒。总次数 / 均速 = 操作时长。
        n = _n(c[count_of[kind]][hour])
        ms = _n(c[ms_key][hour]) + _n(extra[ms_key][hour])
        out[f"{kind}_hour"] = (n, ms)
    return out


def fmt_key_rate(count: int, ms: int) -> str:
    if ms < int(_KEY_MIN_S * 1000) or count <= 0:
        return "—"
    return f"{round(count * 60000 / ms)}下/分"


def fmt_click_rate(count: int, ms: int) -> str:
    if ms < int(_CLICK_MIN_S * 1000) or count <= 0:
        return "—"
    return f"{round(count * 60000 / ms)}次/分"


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


def rate_value(kind: str, n: int, ms: int) -> int:
    """画图用的整数。打字/点击/滚轮是每分钟次数，移动是大约厘米每秒。"""
    if ms <= 0 or n <= 0:
        return 0
    if kind == "move":
        return max(0, int(round(travel_meters(n) * 100000 / ms)))
    return max(0, int(round(n * 60000 / ms)))


def fmt_instant(kind: str, n: int, ms: int) -> str:
    """瞬时。停手是 0，不是「—」。"""
    if n <= 0 or ms <= 0:
        if kind == "move":
            return "0"
        if kind == "click":
            return "0次/分"
        if kind == "wheel":
            return "0格/分"
        return "0下/分"
    if kind == "move":
        return fmt_move_rate(n, ms)
    if kind == "click":
        return fmt_click_rate(n, ms)
    if kind == "wheel":
        return fmt_wheel_rate(n, ms)
    return fmt_key_rate(n, ms)


def fmt_card_speed(kind: str, n: int, ms: int, *, avg: bool = False) -> str:
    if not avg:
        return (
            fmt_instant(kind, n, ms)
            .replace("下", "").replace("次", "").replace("格", "")
            .replace("约 ", "").replace(" ", "")
        )
    if kind == "key":
        text = fmt_key_rate(n, ms).replace("下", "")
    elif kind == "click":
        text = fmt_click_rate(n, ms).replace("次", "")
    elif kind == "wheel":
        text = fmt_wheel_rate(n, ms).replace("格", "")
    else:
        text = fmt_move_rate(n, ms).replace("约 ", "").replace(" ", "")
    return "均—" if text == "—" else f"均{text}"


def fmt_speed_line(
    keys: int,
    key_ms: int,
    travel: int,
    travel_ms: int,
    wheels: int,
    wheel_ms: int,
    clicks: int = 0,
    click_ms: int = 0,
) -> str:
    return (
        f"打字 {fmt_key_rate(keys, key_ms)}"
        f"    点击 {fmt_click_rate(clicks, click_ms)}"
        f"    移动 {fmt_move_rate(travel, travel_ms)}"
        f"    滚轮 {fmt_wheel_rate(wheels, wheel_ms)}"
    )


def reset_key_state() -> None:
    """测试或重开监听时清掉按住状态。"""
    global _down, _e1
    _down = set()
    _e1 = False


def _scan_token(make: int, flags: int) -> int:
    scan = int(make) & 0xFF
    return (0xE000 | scan) if flags & 2 else scan


def track_key(buf: bytes) -> None:
    """松开时清掉按住。连发、Pause 的半截包都靠这个认。"""
    global _e1
    if len(buf) < _KEY_VK_AT + 2 or int.from_bytes(buf[0:4], "little") != 1:
        return
    flags = int.from_bytes(buf[_KEY_FLAGS_AT:_KEY_FLAGS_AT + 2], "little")
    make = int.from_bytes(buf[_HDR:_HDR + 2], "little")
    token = _scan_token(make, flags)
    if flags & 4:
        _e1 = True
        return
    if flags & 1:
        _down.discard(token)
        if _e1:
            _e1 = False


def _id_from_scan(token: int) -> str | None:
    if token & 0xE000:
        scan = token & 0xFF
        if scan in _FAKE_E0:
            return None
        got = _SCAN_E0.get(scan)
        return str(got) if got else None
    got = _SCAN.get(token)
    return str(got) if got else None


def _vk_from_make(make: int, flags: int) -> int:
    """扫描码换成左右能分开的虚拟键。输入法占住时，原始键号会变成「正在处理」。"""
    scan = int(make) & 0xFF
    if flags & 2:
        scan |= 0xE000
    try:
        return int(ctypes.windll.user32.MapVirtualKeyW(scan, 3) or 0) & 0xFF
    except Exception:
        return 0


def key_id(buf: bytes) -> str | None:
    """键盘按下时的键号。按物理扫描码记，不跟 NumLock。松开、连发、假 Shift 不记。"""
    global _e1
    if len(buf) < _KEY_VK_AT + 2 or int.from_bytes(buf[0:4], "little") != 1:
        return None
    flags = int.from_bytes(buf[_KEY_FLAGS_AT:_KEY_FLAGS_AT + 2], "little")
    vk = int.from_bytes(buf[_KEY_VK_AT:_KEY_VK_AT + 2], "little")
    make = int.from_bytes(buf[_HDR:_HDR + 2], "little")
    token = _scan_token(make, flags)
    if flags & 1:
        return None
    if flags & 4:
        return None
    if _e1:
        _e1 = False
        if token in _down:
            return None
        _down.add(token)
        return "13"
    if flags & 2 and (make & 0xFF) in _FAKE_E0:
        return None
    if token and token in _down:
        return None
    if token:
        _down.add(token)
    mapped = _id_from_scan(token)
    if mapped:
        return mapped
    # 0 / 0xFF 没有键；0xE5 是输入法占位；0xE7 是直接塞进来的字符。
    # 0x10 / 0x11 / 0x12 分不出左右，隐藏键设成 Ctrl 时就会对不上图上的键。
    if vk in (0, 0xFF, 0xE5, 0xE7, 0x10, 0x11, 0x12):
        mapped_vk = _vk_from_make(make, flags)
        if mapped_vk and mapped_vk not in (0, 0xFF, 0xE5, 0xE7):
            vk = mapped_vk
    if vk <= 0 or vk >= 256 or vk in (0xE5, 0xE7):
        return None
    if vk == 0x0D and flags & 2:
        return "numenter"
    if vk == 0x10:
        return "A0"
    if vk == 0x11:
        return "A2"
    if vk == 0x12:
        return "A4"
    return f"{vk:02X}"


def _clean_keymap(raw) -> dict:
    """只留键号和次数。顺序、时间都不在这里。"""
    if not isinstance(raw, dict):
        return {}
    out: dict[str, int] = {}
    for name, count in raw.items():
        ident = str(name)
        if ident != "numenter" and (len(ident) != 2 or any(c not in "0123456789ABCDEF" for c in ident)):
            continue
        n = _n(count)
        if n:
            out[ident] = n
    return out


# 键盘图按这台电脑实际按过的区域来画。没小键盘的笔记本，右边那一块就不画。
_NAV_IDS = {"2D", "24", "21", "2E", "23", "22", "26", "25", "28", "27"}
_EXTRA_IDS = {"2C", "91", "13"}


def key_zone(ident: str) -> str:
    """main 是字母数字；nav 是 Ins/方向；num 是小键盘；extra 是屏/滚/停。"""
    ident = str(ident)
    if ident in ("10", "11", "12"):
        ident = {"10": "A0", "11": "A2", "12": "A4"}[ident]
    if ident == "numenter":
        return "num"
    if ident in _NAV_IDS:
        return "nav"
    if ident in _EXTRA_IDS:
        return "extra"
    try:
        vk = int(ident, 16)
    except ValueError:
        return "main"
    if 0x60 <= vk <= 0x6F or vk == 0x90:
        return "num"
    return "main"


def _note_zone(cfg: dict, ident: str) -> None:
    zone = key_zone(ident)
    if zone == "main":
        return
    book = _book(cfg)
    got = book.get("heat_zones")
    zones = set(got) if isinstance(got, list) else set()
    if zone not in zones:
        zones.add(zone)
        book["heat_zones"] = sorted(zones)


def heat_zones(cfg: dict) -> list[str]:
    raw = cfg.get(_KEY)
    got = raw.get("heat_zones") if isinstance(raw, dict) else None
    if not isinstance(got, list):
        return []
    return [z for z in got if z in ("nav", "num", "extra")]


def note(cfg: dict, kind: str, now: datetime | None = None, key: str | None = None) -> bool:
    """记一次。kind 是 key / click / wheel。没开开关则什么都不做。

    key 是键号。只累加这个键按了多少下，不记下先按了谁。
    """
    if not enabled(cfg):
        return False
    if kind not in ("key", "click", "wheel"):
        return False
    now = now or datetime.now()
    item = _day(cfg, now.date())
    field = {"key": "keys", "click": "clicks", "wheel": "wheels"}[kind]
    item[field] = _n(item.get(field)) + 1
    if kind == "key" and key:
        board = item.get("keymap")
        if not isinstance(board, dict):
            board = {}
            item["keymap"] = board
        ident = str(key)
        if ident == "numenter" or (len(ident) == 2 and all(c in "0123456789ABCDEF" for c in ident)):
            board[ident] = _n(board.get(ident)) + 1
            _note_zone(cfg, ident)
    h = now.hour
    if 0 <= h < 24:
        item["hours"][h] = _n(item["hours"][h]) + 1
        if kind == "key":
            item["keys_h"][h] = _n(item["keys_h"][h]) + 1
            _touch(cfg, "key", now, 1, gap=_KEY_GAP_S, min_s=_KEY_MIN_S, pace_key="keys_pace", ms_key="keys_ms")
        elif kind == "click":
            item["clicks_h"][h] = _n(item["clicks_h"][h]) + 1
            _touch(
                cfg, "click", now, 1,
                gap=_CLICK_GAP_S, min_s=_CLICK_MIN_S,
                pace_key="clicks_pace", ms_key="clicks_ms",
            )
        elif kind == "wheel":
            item["wheels_h"][h] = _n(item["wheels_h"][h]) + 1
            _touch(cfg, "wheel", now, 1, gap=_WHEEL_GAP_S, min_s=_WHEEL_MIN_S, pace_key="wheels_pace", ms_key="wheels_ms")
    return True


def counts(cfg: dict, d: date) -> dict:
    item = _book(cfg).get("days", {}).get(d.strftime("%Y-%m-%d"))
    if not isinstance(item, dict):
        return _clean_day({})
    return _view_day(item)


def parse_raw(buf: bytes) -> str | None:
    """从 WM_INPUT 的原始缓冲里认出是键盘按下、鼠标点还是滚轮。键号由 key_id 读。"""
    if len(buf) < _HDR + 8:
        return None
    dw_type = int.from_bytes(buf[0:4], "little")
    if dw_type == 1:
        flags = int.from_bytes(buf[_KEY_FLAGS_AT:_KEY_FLAGS_AT + 2], "little")
        if flags & 1:
            return None
        return "key"
    if dw_type == 0:
        buttons = int.from_bytes(buf[_BUTTON_FLAGS_AT:_BUTTON_FLAGS_AT + 2], "little")
        if buttons & 0x0C00:
            return "wheel"
        if buttons & 0x0155:
            return "click"
        return None
    return None


def physical_input(buf: bytes) -> str | None:
    """认出一次有意义的硬件输入；不读键码，也不把 SendInput 当成人在操作。"""
    if len(buf) < _DEVICE_AT + _DEVICE_SIZE:
        return None
    # RAWINPUTHEADER.hDevice 为 0 时没有可确认的硬件来源，常见于 SendInput 注入。
    device = int.from_bytes(buf[_DEVICE_AT:_DEVICE_AT + _DEVICE_SIZE], "little")
    if device == 0:
        return None
    kind = parse_raw(buf)
    if kind is not None:
        return kind
    if int.from_bytes(buf[0:4], "little") != 0 or len(buf) < _DY_AT + 4:
        return None
    dx = int.from_bytes(buf[_DX_AT:_DX_AT + 4], "little", signed=True)
    dy = int.from_bytes(buf[_DY_AT:_DY_AT + 4], "little", signed=True)
    # 相对鼠标的 0,0 包是噪声。绝对坐标设备（部分触控板）只有坐标变化才会发包；
    # 0,0 无法和空包可靠区分，交给 LastInput 变化兜底。
    return "move" if dx != 0 or dy != 0 else None


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


def card_slots(cfg: dict) -> tuple[str, str, str]:
    raw = _book(cfg).get("card_slots")
    if (
        isinstance(raw, list)
        and len(raw) == 3
        and len(set(raw)) == 3
        and all(isinstance(x, str) and x in _CARD_LABEL for x in raw)
    ):
        return raw[0], raw[1], raw[2]
    return "keys", "clicks", "wheels"


def set_card_slot(cfg: dict, index: int, choice: str) -> tuple[str, str, str]:
    """三个位置各选一个。选了已经在用的，就和那个位置对调。"""
    slots = list(card_slots(cfg))
    if choice not in _CARD_LABEL or not 0 <= index < 3:
        return slots[0], slots[1], slots[2]
    if choice in slots:
        other = slots.index(choice)
        slots[other], slots[index] = slots[index], slots[other]
    else:
        slots[index] = choice
    _book(cfg)["card_slots"] = slots
    return slots[0], slots[1], slots[2]


def card_label(slot: str) -> str:
    return _CARD_LABEL.get(slot, "键盘次数")


def card_id(label: str) -> str:
    return _CARD_ID.get(label, "keys")


def card_parts(cfg: dict, now: datetime | None = None, speed: dict | None = None) -> tuple[tuple[str, str], ...]:
    """主界面三项。(图标, 文字)。图标是 key / mouse / wheel。"""
    now = now or datetime.now()
    if speed is None:
        settle(cfg, now)
        speed = speed_snapshot(cfg, now)
    counted = totals(cfg, now.date())
    count_text = {
        "keys": ("key", fmt_count(counted[0])),
        "clicks": ("mouse", fmt_count(counted[1])),
        "wheels": ("wheel", fmt_count(counted[2])),
        "travel": ("mouse", fmt_travel(total_travel(cfg, now.date()))),
    }
    speed_spec = {
        "key_now": ("key", "key", False),
        "click_now": ("mouse", "click", False),
        "move_now": ("mouse", "move", False),
        "wheel_now": ("wheel", "wheel", False),
        "key_hour": ("key", "key_hour", True),
        "click_hour": ("mouse", "click_hour", True),
        "move_hour": ("mouse", "move_hour", True),
        "wheel_hour": ("wheel", "wheel_hour", True),
    }
    kind_of = {
        "key": "key", "click": "click", "move": "move", "wheel": "wheel",
        "key_hour": "key", "click_hour": "click", "move_hour": "move", "wheel_hour": "wheel",
    }
    parts = []
    for slot in card_slots(cfg):
        if slot in count_text:
            parts.append(count_text[slot])
            continue
        icon, snap_key, avg = speed_spec[slot]
        n, ms = speed.get(snap_key) or (0, 0)
        parts.append((icon, fmt_card_speed(kind_of[snap_key], int(n), int(ms), avg=avg)))
    return tuple(parts)


def chart_view(cfg: dict) -> str:
    raw = cfg.get(_KEY)
    view = raw.get("chart_view") if isinstance(raw, dict) else None
    return view if view in CHART_VIEWS else "counts"


def set_chart_view(cfg: dict, view: str) -> str:
    book = _book(cfg)
    book["chart_view"] = view if view in CHART_VIEWS else "counts"
    return str(book["chart_view"])


def chart_style(cfg: dict) -> str:
    raw = cfg.get(_KEY)
    style = raw.get("chart") if isinstance(raw, dict) else None
    return style if style in ("line", "bar") else "line"


def set_chart_style(cfg: dict, style: str) -> str:
    book = _book(cfg)
    book["chart"] = style if style in ("line", "bar") else "line"
    return str(book["chart"])


def chart_open(cfg: dict) -> bool:
    """键鼠图默认收着。展开过一次，下次还开着。"""
    raw = cfg.get(_KEY)
    return bool(isinstance(raw, dict) and raw.get("chart_open"))


def set_chart_open(cfg: dict, on: bool) -> bool:
    book = _book(cfg)
    book["chart_open"] = bool(on)
    return bool(book["chart_open"])


def heat_open(cfg: dict) -> bool:
    """键盘默认收着，打开账本先看工时。"""
    raw = cfg.get(_KEY)
    return bool(isinstance(raw, dict) and raw.get("heat_open"))


def set_heat_open(cfg: dict, on: bool) -> bool:
    book = _book(cfg)
    book["heat_open"] = bool(on)
    return bool(book["heat_open"])


def heat_view(cfg: dict) -> str:
    raw = cfg.get(_KEY)
    view = raw.get("heat_view") if isinstance(raw, dict) else None
    return view if view in ("map", "rank") else "map"


def set_heat_view(cfg: dict, view: str) -> str:
    book = _book(cfg)
    book["heat_view"] = view if view in ("map", "rank") else "map"
    return str(book["heat_view"])


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
