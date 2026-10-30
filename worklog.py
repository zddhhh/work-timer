"""工时账本：每天到岗 / 离开时刻，周、月统计与 CSV 导出。

cfg["worklog"] = {"YYYY-MM-DD": {"in": 分钟, "out": 分钟, "target": 分钟,
                                 "note_in": 分钟, "note_out": 分钟, "src": "flex|seen"}}
分钟 = 当天 0 点起的分钟数。in / out 只由软件按实际上机写入，不能手改。
note_in / note_out 是用户自己填的到岗和下班，只用来对照。
开着记录时，来和走按 30 秒里凑满 3 个不同的秒才算，含周末。
和上一段隔了半小时、只有鼠标或滚轮、自己不到两分钟的那一下，先不改走了。
停手也满半小时，才在卡片上标出来，等用户决定算不算。
"""
from __future__ import annotations

import ctypes
import csv
import io
from datetime import date, datetime, timedelta

import activity
import flex_time

IDLE_LIMIT_SEC = 300
# 连续这么多秒里，有这么多个不同的秒出现过键鼠，才算一段真实上机。碰一下通常只有 1 秒。
BURST_WINDOW_SEC = 30
BURST_NEED = 3
# 离开上一段至少这么久，才可能是另起的一下，而不是还在连续操作。
DOUBT_GAP_MIN = 30
# 这一下自己要短过这么久，并且里面没有按键、没有点击，才标成存疑。
DOUBT_SPAN_SEC = 120
DOUBT_IDLE_SEC = 30 * 60
# 现代待机醒来时，系统会把「最后一次输入」刷成现在，空闲读数变成 0。
# 醒来后这段时间里只屏蔽 LastInput 兜底；真实 Raw Input 仍立即参与来和走。
WAKE_QUIET_SEC = 15
WEEKDAY_CN = "一二三四五六日"
_TRACK_KEY = "worklog_tracking"


def tracking_enabled(cfg: dict) -> bool:
    """旧配置没有开关，升级后保持原来的记录行为。"""
    return bool(cfg.get(_TRACK_KEY, True))


def set_tracking_enabled(cfg: dict, on: bool) -> bool:
    cfg[_TRACK_KEY] = bool(on)
    return bool(cfg[_TRACK_KEY])


def _key(d: date) -> str:
    return d.strftime("%Y-%m-%d")


def _as_min(v) -> int | None:
    if isinstance(v, bool) or not isinstance(v, int):
        return None
    return v if 0 <= v < 24 * 60 else None


def fmt_clock(minutes: int | None) -> str:
    if minutes is None:
        return ""
    return f"{minutes // 60}:{minutes % 60:02d}"


def fmt_elapsed(seconds: int) -> str:
    """当天已过多久，给还在记的那一行用。"""
    h, rem = divmod(max(0, int(seconds)), 3600)
    m, s = divmod(rem, 60)
    parts = []
    if h:
        parts.append(f"{h}小时")
    if m:
        parts.append(f"{m}分")
    if s or not parts:
        parts.append(f"{s}秒")
    return "".join(parts)


def fmt_span(minutes: int | None, *, signed: bool = False) -> str:
    """待了多久。9小时30分，不要写成 9:30，免得看成钟点。"""
    if minutes is None:
        return ""
    if signed:
        return fmt_diff(minutes)
    total = abs(int(minutes))
    h, m = divmod(total, 60)
    if h and m:
        return f"{h}小时{m}分"
    if h:
        return f"{h}小时"
    return f"{m}分"


def fmt_diff(minutes: int | None) -> str:
    """比该走的点早了还是晚了。"""
    if minutes is None:
        return ""
    if minutes == 0:
        return "正点"
    label = "晚走" if minutes > 0 else "早走"
    return label + fmt_span(abs(int(minutes)))


def fmt_note_gap(kind: str, minutes: int | None) -> str:
    """自填钟点和软件记录的差别。正数是软件更晚。"""
    if minutes is None:
        return ""
    if minutes == 0:
        return "到岗一致" if kind == "in" else "离开一致"
    if kind == "in":
        label = "晚到" if minutes > 0 else "早到"
    else:
        label = "晚走" if minutes > 0 else "早走"
    return label + fmt_span(abs(int(minutes)))


def fmt_note_compare(arrive: int | None, leave: int | None) -> str:
    parts = [fmt_note_gap("in", arrive), fmt_note_gap("out", leave)]
    return "，".join(part for part in parts if part)


def company_span(note_in: int | None, note_out: int | None) -> str:
    """公司正常上下班这一段有多长。缺一边或下班早于到岗就不写。"""
    if note_in is None or note_out is None or note_out < note_in:
        return ""
    return fmt_span(note_out - note_in)


def _longest_quiet(active: list[int]) -> tuple[int, int] | None:
    """两段操作中间最长的空档，返回空着的起止小时（含）。不足两小时不算。"""
    if len(active) < 2:
        return None
    best = None
    best_n = 1
    for left, right in zip(active, active[1:]):
        n = right - left - 1
        if n > best_n:
            best_n = n
            best = (left + 1, right - 1)
    return best


def _pace_line(cfg: dict, d: date) -> str:
    """这一天一句。中间空了两小时以上就说空档，否则说最忙的那一截。"""
    if not activity.enabled(cfg):
        return ""
    c = activity.counts(cfg, d)
    keys, clicks, wheels = c.get("keys_h") or [], c.get("clicks_h") or [], c.get("wheels_h") or []
    if len(keys) == 24 and len(clicks) == 24 and len(wheels) == 24:
        series = [int(a) + int(b) + int(w) for a, b, w in zip(keys, clicks, wheels)]
    else:
        series = []
    if not any(series):
        hours = c.get("hours") or []
        series = [int(v) for v in hours] if len(hours) == 24 else []
    if not any(series):
        return ""
    quiet = _longest_quiet([i for i, v in enumerate(series) if v > 0])
    if quiet is not None:
        a, b = quiet
        return f"{a}点空着" if a == b else f"{a}点到{b}点空着"
    peak = activity.peak_hours(series)
    if peak is None:
        return ""
    a, b = peak
    if b - a <= 1:
        return f"{a}点最忙"
    return f"{a}点到{b}点最忙"


def day_summary(cfg: dict, d: date, r: dict) -> str:
    """两段。第一段是和公司时间差多少，第二段是这一天哪里忙、哪里空。"""
    lines = []
    arrive, leave = r.get("arrive_gap"), r.get("leave_gap")
    if arrive is not None or leave is not None:
        if arrive == 0 and leave == 0:
            lines.append("和公司时间一致")
        else:
            text = fmt_note_compare(arrive, leave)
            if text:
                lines.append(text)
    pace = _pace_line(cfg, d)
    if pace:
        lines.append(pace)
    return "\n".join(lines)


def fmt_hms(total_seconds: int) -> str:
    total = max(0, int(total_seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def live_elapsed(r: dict, now: datetime, idle_sec: float) -> str | None:
    """进行中的时长，精确到秒。已经封账或不是今天则返回 None。"""
    if r.get("held") or not r.get("live") or r.get("in") is None:
        return None
    start = datetime.combine(r["date"], datetime.min.time()) + timedelta(minutes=int(r["in"]))
    if idle_sec < IDLE_LIMIT_SEC:
        end = now - timedelta(seconds=max(0.0, float(idle_sec)))
    elif r.get("out") is not None:
        end = datetime.combine(r["date"], datetime.min.time()) + timedelta(minutes=int(r["out"]))
    else:
        end = start
    if end < start:
        end = start
    return fmt_elapsed(int((end - start).total_seconds())) + " · 还在记"


def ensure_fields(cfg: dict, *, today: date | None = None, keep_days: int | None = None) -> None:
    """来了、走了和键鼠次数留同样久。早于这个范围的天删掉。"""
    raw = cfg.get("worklog")
    if not isinstance(raw, dict):
        cfg["worklog"] = {}
        return
    if keep_days is None:
        import activity

        keep_days = activity.keep_days(cfg)
    cutoff = _key((today or date.today()) - timedelta(days=int(keep_days)))
    cleaned: dict[str, dict] = {}
    for k, v in raw.items():
        if not isinstance(v, dict) or not isinstance(k, str) or k < cutoff:
            continue
        try:
            datetime.strptime(k, "%Y-%m-%d")
        except ValueError:
            continue
        item: dict = {}
        for f in ("in", "out", "target", "note_in", "note_out"):
            m = _as_min(v.get(f))
            if m is not None:
                item[f] = m
        # 旧的手改覆盖过软件时间，原记录已经找不回。那些钟点改记成自填，软件从下次真实操作重新记。
        if v.get("manual"):
            if "note_in" not in item and "in" in item:
                item["note_in"] = item.pop("in")
            if "note_out" not in item and "out" in item:
                item["note_out"] = item.pop("out")
            item["note_custom"] = True
        elif v.get("note_custom") and ("note_in" in item or "note_out" in item):
            item["note_custom"] = True
        if not any(f in item for f in ("in", "out", "target", "note_in", "note_out")):
            continue
        hold = _clean_hold(v.get("hold"))
        if hold and ("in" in item or "out" in item):
            item["hold"] = hold
        item["src"] = "flex" if v.get("src") == "flex" else "seen"
        cleaned[k] = item
    cfg["worklog"] = cleaned


def _days(cfg: dict) -> dict[str, dict]:
    book = cfg.get("worklog")
    if not isinstance(book, dict):
        book = {}
        cfg["worklog"] = book
    return book


def get_day(cfg: dict, d: date) -> dict | None:
    item = _days(cfg).get(_key(d))
    return item if isinstance(item, dict) else None


def should_track(now: datetime, *, has_target: bool = True, set_today: bool = False) -> bool:
    """每天都记，含周末。倒计时有没有设下班，不影响账本。"""
    return True


def _sod(when: datetime) -> int:
    return when.hour * 3600 + when.minute * 60 + when.second


def note_second(state: dict | None, when: datetime) -> tuple[dict, datetime | None]:
    """记下这一秒有过键鼠。换天就另起。

    最近 BURST_WINDOW_SEC 秒里凑满 BURST_NEED 个不同的秒，返回这段最早的那一秒。
    凑不满返回 None。同一秒重复出现只算一次。
    """
    key = when.date().isoformat()
    sec = _sod(when)
    if state is None or state.get("day") != key or not isinstance(state.get("secs"), list):
        state = {"day": key, "secs": []}
    secs = [s for s in state["secs"] if isinstance(s, int) and 0 <= sec - s <= BURST_WINDOW_SEC]
    if sec not in secs:
        secs.append(sec)
    secs.sort()
    state["secs"] = secs
    if len(secs) < BURST_NEED:
        return state, None
    start = datetime.combine(when.date(), datetime.min.time()) + timedelta(seconds=secs[0])
    return state, start


def _remember_hot(state: dict, when: datetime, kind: str | None) -> None:
    """这一秒里有过按键、点击，或分不清种类的输入。纯移动和滚轮不记。"""
    sec = _sod(when)
    hot = [
        s for s in state.get("hot") or []
        if isinstance(s, int) and 0 <= sec - s <= BURST_WINDOW_SEC
    ]
    if kind not in ("move", "wheel") and sec not in hot:
        hot.append(sec)
    state["hot"] = hot


def _burst_hot(state: dict, start: datetime, end: datetime) -> bool:
    a, b = _sod(start), _sod(end)
    return any(isinstance(s, int) and a <= s <= b for s in state.get("hot") or [])


def note_input(
    cfg: dict,
    state: dict | None,
    when: datetime,
    *,
    target_hm: tuple[int, int] | None = None,
    kind: str | None = None,
) -> tuple[dict | None, bool]:
    """一条可信输入进入工时账本；次数统计开关不影响这里。

    kind 是 key / click / wheel / move。不传表示分不清种类，按动手算，不标存疑。
    """
    if not tracking_enabled(cfg):
        return None, False
    state, start = note_second(state, when)
    if state is not None:
        _remember_hot(state, when, kind)
    if start is None:
        return state, False
    return state, _take_burst(
        cfg, start, when, hot=_burst_hot(state, start, when), target_hm=target_hm,
    )


def touch_target(cfg: dict, day: date, target_hm: tuple[int, int] | None) -> bool:
    """已有的一天跟上应下班。还没记下上机的日子不动。自填时间不挡住它。"""
    if target_hm is None:
        return False
    item = get_day(cfg, day)
    if not isinstance(item, dict):
        return False
    target = int(target_hm[0]) * 60 + int(target_hm[1])
    if item.get("target") == target:
        return False
    item["target"] = target
    return True


def mark_span(
    cfg: dict,
    start: datetime,
    end: datetime,
    *,
    target_hm: tuple[int, int] | None = None,
) -> bool:
    """一段已凑满的上机。来只写第一次的起点，走改到这次的最后一秒。"""
    if start.date() != end.date():
        return False
    book = _days(cfg)
    key = _key(end.date())
    item = book.get(key)
    in_min = start.hour * 60 + start.minute
    out_min = end.hour * 60 + end.minute
    if not (0 <= in_min < 24 * 60 and 0 <= out_min < 24 * 60) or out_min < in_min:
        return False
    changed = False
    if not isinstance(item, dict):
        item = {"in": in_min, "out": out_min, "src": "seen"}
        book[key] = item
        changed = True
    else:
        if _as_min(item.get("in")) is None:
            item["in"] = in_min
            item["src"] = "seen"
            changed = True
        if _as_min(item.get("out")) is None or out_min > item["out"]:
            item["out"] = out_min
            changed = True
    if target_hm is not None:
        target = int(target_hm[0]) * 60 + int(target_hm[1])
        if item.get("target") != target:
            item["target"] = target
            changed = True
    return changed


def _clean_hold(v) -> dict | None:
    if not isinstance(v, dict):
        return None
    start, end = v.get("start"), v.get("end")
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    if not isinstance(start, int) or not isinstance(end, int):
        return None
    if not (0 <= start <= end <= 86399):
        return None
    return {
        "start": start,
        "end": end,
        "active": bool(v.get("active")),
        "asked": bool(v.get("asked")),
        "drop": bool(v.get("drop")),
    }


def _park(item: dict, hold: dict) -> None:
    item["hold"] = _clean_hold(hold)


def _commit_hold(
    cfg: dict,
    day: date,
    hold: dict,
    *,
    target_hm: tuple[int, int] | None = None,
) -> None:
    base = datetime.combine(day, datetime.min.time())
    mark_span(
        cfg,
        base + timedelta(seconds=int(hold["start"])),
        base + timedelta(seconds=int(hold["end"])),
        target_hm=target_hm,
    )


def _take_burst(
    cfg: dict,
    start: datetime,
    end: datetime,
    *,
    hot: bool,
    target_hm: tuple[int, int] | None,
) -> bool:
    """凑满的一段。紧挨着上一段就直接改走了；隔得远的短移动先挂着。"""
    if start.date() != end.date():
        return False
    item = get_day(cfg, end.date())
    out = _as_min(item.get("out")) if item else None
    start_min = start.hour * 60 + start.minute
    if out is None or start_min - out < DOUBT_GAP_MIN:
        if item and "hold" in item:
            item.pop("hold", None)
        return mark_span(cfg, start, end, target_hm=target_hm)
    hold = _clean_hold(item.get("hold"))
    end_sec = _sod(end)
    if hold and start_min - hold["end"] // 60 < DOUBT_GAP_MIN:
        hold["end"] = max(hold["end"], end_sec)
        hold["active"] = bool(hold["active"] or hot)
    else:
        hold = {
            "start": _sod(start),
            "end": end_sec,
            "active": bool(hot),
            "asked": False,
            "drop": False,
        }
    if hold["active"] or hold["end"] - hold["start"] >= DOUBT_SPAN_SEC:
        _commit_hold(cfg, end.date(), hold, target_hm=target_hm)
        got = get_day(cfg, end.date())
        if got is not None:
            got.pop("hold", None)
        return True
    hold["asked"] = False
    _park(item, hold)
    return True


def note_kind(cfg: dict, when: datetime, kind: str | None) -> bool:
    """同一秒里后到的按键或点击。这段就不再是纯移动，直接记进走了。"""
    if not tracking_enabled(cfg) or kind in ("move", "wheel", None):
        return False
    item = get_day(cfg, when.date())
    hold = _clean_hold(item.get("hold")) if item else None
    if hold is None:
        return False
    sec = _sod(when)
    if sec < hold["start"] or sec - hold["end"] > DOUBT_GAP_MIN * 60:
        return False
    hold["active"] = True
    hold["end"] = max(hold["end"], sec)
    _commit_hold(cfg, when.date(), hold)
    got = get_day(cfg, when.date())
    if got is not None:
        got.pop("hold", None)
    return True


def settle_doubt(cfg: dict, now: datetime, idle_sec: float) -> bool:
    """停手够久，短的纯移动才变成卡片上的那一行。昨天没来得及问的也补上。"""
    if idle_sec < DOUBT_IDLE_SEC:
        return False
    changed = False
    for day in (now.date() - timedelta(days=1), now.date()):
        item = get_day(cfg, day)
        hold = _clean_hold(item.get("hold")) if item else None
        if hold is None or hold["drop"] or hold["asked"]:
            continue
        if hold["active"] or hold["end"] - hold["start"] >= DOUBT_SPAN_SEC:
            _commit_hold(cfg, day, hold)
            item.pop("hold", None)
        else:
            hold["asked"] = True
            _park(item, hold)
        changed = True
    return changed


def doubt_line(prev: int | None, at: int | None) -> str:
    if prev is None or at is None or at <= prev:
        return ""
    return f"{fmt_clock(prev)} 之后只有 {fmt_clock(at)} 这一下"


def decide_doubt(cfg: dict, day: date, *, keep: bool) -> bool:
    """算上就把走了改到这一下；不算就留着原来的走了，同一次不再问。"""
    item = get_day(cfg, day)
    hold = _clean_hold(item.get("hold")) if item else None
    if hold is None or not hold["asked"] or hold["drop"]:
        return False
    if keep:
        _commit_hold(cfg, day, hold)
        got = get_day(cfg, day)
        if got is not None:
            got.pop("hold", None)
        return True
    hold["drop"] = True
    hold["asked"] = False
    _park(item, hold)
    return True


def last_active_minute(now: datetime, idle_sec: float) -> int | None:
    """最后一次键鼠落在哪一分钟。跨过零点则不算今天。"""
    if idle_sec < 0:
        idle_sec = 0.0
    last = now - timedelta(seconds=float(idle_sec))
    if last.date() != now.date():
        return None
    return last.hour * 60 + last.minute


def set_note(cfg: dict, d: date, in_text: str, out_text: str) -> str | None:
    """改用户自己填的到岗和下班。两个都留空 = 清掉自填，软件记录保留。"""
    in_text = (in_text or "").strip()
    out_text = (out_text or "").strip()
    book = _days(cfg)
    k = _key(d)
    if not in_text and not out_text:
        item = book.get(k)
        if isinstance(item, dict):
            item.pop("note_in", None)
            item.pop("note_out", None)
            item.pop("note_custom", None)
            item.pop("manual", None)
            if not any(f in item for f in ("in", "out", "target")):
                book.pop(k, None)
        return None
    pin = flex_time.parse_clock(in_text) if in_text else None
    pout = flex_time.parse_clock(out_text) if out_text else None
    if in_text and pin is None:
        return f"{d.month}/{d.day} 自填到岗看不懂：{in_text}"
    if out_text and pout is None:
        return f"{d.month}/{d.day} 自填下班看不懂：{out_text}"
    mi = None if pin is None else pin[0] * 60 + pin[1]
    mo = None if pout is None else pout[0] * 60 + pout[1]
    if mi is not None and mo is not None and mo < mi:
        return f"{d.month}/{d.day} 自填下班早于到岗"
    item = book.setdefault(k, {"src": "seen"})
    for f, v in (("note_in", mi), ("note_out", mo)):
        if v is None:
            item.pop(f, None)
        else:
            item[f] = v
    item["note_custom"] = True
    item.pop("manual", None)
    return None


def _put_note(item: dict, key: str, minutes: int | None) -> bool:
    if minutes is None:
        if key not in item:
            return False
        item.pop(key, None)
        return True
    if item.get(key) == minutes:
        return False
    item[key] = minutes
    return True


def sync_declared(
    cfg: dict,
    d: date,
    *,
    mode: str,
    start: tuple[int, int] | None = None,
    off: tuple[int, int] | None = None,
    force: bool = False,
) -> bool:
    """自填默认跟着倒计时。用户改过之后保持原样，除非刚在设置里重填。"""
    item = get_day(cfg, d)
    if not force and isinstance(item, dict) and item.get("note_custom"):
        return False
    if mode == "flex":
        if start is None:
            return False
        arrived = int(start[0]) * 60 + int(start[1])
        left_hm = off if off is not None else flex_time.offwork_hm(*start)
        left = int(left_hm[0]) * 60 + int(left_hm[1])
    elif mode == "direct":
        if off is None:
            return False
        left = int(off[0]) * 60 + int(off[1])
        first = _as_min(item.get("in")) if isinstance(item, dict) else None
        current = _as_min(item.get("note_in")) if isinstance(item, dict) else None
        arrived = first if first is not None else (None if force else current)
    else:
        return False
    book = _days(cfg)
    stored = book.setdefault(_key(d), {"src": "seen"})
    changed = _put_note(stored, "note_in", arrived)
    changed = _put_note(stored, "note_out", left) or changed
    if stored.pop("note_custom", None):
        changed = True
    stored.pop("manual", None)
    return changed


def row(cfg: dict, d: date, *, today: date | None = None) -> dict:
    item = get_day(cfg, d) or {}
    mi, mo, mt = _as_min(item.get("in")), _as_min(item.get("out")), _as_min(item.get("target"))
    note_in, note_out = _as_min(item.get("note_in")), _as_min(item.get("note_out"))
    hold = _clean_hold(item.get("hold"))
    doubt_at = hold["end"] // 60 if hold and hold["asked"] and not hold["drop"] else None
    dur = mo - mi if mi is not None and mo is not None else None
    # 还没到应下班就用「离开-应下班」，下午会显示成大段早退。过了应下班再显示差额。
    live = d == (today or date.today()) and mo is not None
    show_diff = mo is not None and mt is not None and (not live or mo >= mt)
    diff = (mo - mt) if show_diff else None
    arrive_gap = mi - note_in if mi is not None and note_in is not None else None
    leave_gap = mo - note_out if mo is not None and note_out is not None else None
    return {
        "date": d,
        "in": mi,
        "out": mo,
        "target": mt,
        "note_in": note_in,
        "note_out": note_out,
        "dur": dur,
        "diff": diff,
        "arrive_gap": arrive_gap,
        "leave_gap": leave_gap,
        "note_custom": bool(item.get("note_custom")),
        "src": item.get("src", ""),
        "closed": bool(item.get("closed")),
        "live": live,
        "held": hold is not None,
        "doubt": doubt_line(mo, doubt_at),
    }


def week_dates(anchor: date) -> list[date]:
    monday = anchor - timedelta(days=anchor.weekday())
    return [monday + timedelta(days=i) for i in range(7)]


def month_dates(year: int, month: int) -> list[date]:
    d = date(year, month, 1)
    out: list[date] = []
    while d.month == month:
        out.append(d)
        d += timedelta(days=1)
    return out


def summarize(rows: list[dict]) -> dict:
    """只统计已结束的天；今天还在记录中不计入。"""
    worked = [r for r in rows if r["dur"] is not None and not r.get("live")]
    total = sum(r["dur"] for r in worked)
    diffs = [r["diff"] for r in worked if r["diff"] is not None]
    n = len(worked)
    return {
        "days": n,
        "total": total,
        "avg": (total // n) if n else None,
        "diff": sum(diffs) if diffs else None,
    }


# 上午 8–12 点，下午 12–18 点，傍晚 18–22 点。只跟这个人自己的前几周比。
_BANDS = ((8, 12, "上午"), (12, 18, "下午"), (18, 22, "傍晚"))


def _median(values: list[int]) -> int:
    xs = sorted(int(v) for v in values)
    n = len(xs)
    if n % 2:
        return xs[n // 2]
    return (xs[n // 2 - 1] + xs[n // 2]) // 2


def _hours_of(cfg: dict, d: date) -> list[int]:
    c = activity.counts(cfg, d)
    if any(c["hours"]):
        return list(c["hours"])
    return [k + cl + w for k, cl, w in zip(c["keys_h"], c["clicks_h"], c["wheels_h"])]


def _sum_hours(cfg: dict, dates: list[date], today: date) -> list[int]:
    total = [0] * 24
    for d in dates:
        if d > today:
            continue
        for i, v in enumerate(_hours_of(cfg, d)):
            total[i] += v
    return total


def _dominant_band(hours: list[int]) -> str | None:
    scores = [(sum(hours[lo:hi]), name) for lo, hi, name in _BANDS]
    scores.sort(reverse=True)
    top, second = scores[0], scores[1]
    whole = top[0] + second[0] + scores[2][0]
    if top[0] < 12 or whole <= 0:
        return None
    if top[0] < second[0] * 1.5:
        return None
    if top[0] * 100 < whole * 45:
        return None
    return top[1]


def _majority(names: list[str]) -> str | None:
    if len(names) < 2:
        return None
    best, n = max(((name, names.count(name)) for name in set(names)), key=lambda item: item[1])
    if n < 2 or n * 2 < len(names):
        return None
    return best


def _peak_phrase(hours: list[int]) -> str:
    peak = activity.peak_hours(hours)
    if peak is None:
        return ""
    a, b = peak
    if b - a == 1:
        return f"最勤在 {a} 点"
    return f"最勤在 {a}–{b} 点"


def _finished(cfg: dict, dates: list[date], today: date) -> list[dict]:
    rows = []
    for d in dates:
        if d > today:
            continue
        item = row(cfg, d, today=today)
        if item["in"] is None or item["out"] is None or item.get("live"):
            continue
        rows.append(item)
    return rows


def _about_minutes(minutes: int) -> str:
    m = max(1, abs(int(minutes)))
    if m >= 60:
        h, rem = divmod(m, 60)
        if rem >= 40:
            return f"大约 {h + 1} 小时"
        if rem < 15 or h >= 3:
            return f"大约 {h} 小时"
        return f"大约 {h} 小时 {round(rem / 10) * 10} 分钟"
    step = 10 if m >= 20 else 5
    return f"大约 {max(step, round(m / step) * step)} 分钟"


def _weekday_winner(cfg: dict, dates: list[date], today: date, *, min_seen: int) -> int | None:
    totals = [0] * 7
    seen = [0] * 7
    for d in dates:
        if d > today:
            continue
        n = sum(_hours_of(cfg, d))
        if n <= 0:
            continue
        totals[d.weekday()] += n
        seen[d.weekday()] += 1
    ranked = [(totals[i], i) for i in range(7) if seen[i] >= min_seen and totals[i] > 0]
    if not ranked:
        return None
    ranked.sort()
    best, idx = ranked[-1]
    second = ranked[-2][0] if len(ranked) > 1 else 0
    if best < max(second * 1.5, 1):
        return None
    return idx


def habit_text(cfg: dict, days: list[date], today: date, *, this_week: bool = True) -> str:
    """周合计下面的一句习惯。样本不够就什么都不说。"""
    if not days:
        return ""
    head = "本周" if this_week else "这周"
    past = [d for d in days if d <= today]
    hours = _sum_hours(cfg, past, today)
    active_days = sum(1 for d in past if sum(_hours_of(cfg, d)) > 0)
    finished = _finished(cfg, past, today)
    if active_days < 3 and len(finished) < 3:
        return ""

    prior_days: list[date] = []
    prior_bands: list[str] = []
    monday = days[0]
    for i in range(1, 5):
        start = monday - timedelta(days=7 * i)
        week = [start + timedelta(days=k) for k in range(7)]
        prior_days.extend(week)
        band = _dominant_band(_sum_hours(cfg, week, today))
        if band:
            prior_bands.append(band)
    usual = _majority(prior_bands)
    band = _dominant_band(hours)

    sentences: list[str] = []
    if band and usual and band != usual:
        sentences.append(f"{head}{band}更忙，前几周都是{usual}。")
    elif band:
        morning = sum(hours[8:12])
        afternoon = sum(hours[12:18])
        peak = _peak_phrase(hours)
        if usual == band:
            body = f"这几周都是{band}更忙"
        elif band == "下午" and afternoon > morning * 8 and morning < 12:
            body = "上午几乎不动，忙集中在下午"
        else:
            body = f"{head}{band}更忙"
        sentences.append(body + (f"，{peak}。" if peak else "。"))

    this_in = [item["in"] for item in finished]
    prior_in = [item["in"] for item in _finished(cfg, prior_days, today)]
    if len(sentences) < 2 and len(this_in) >= 3 and len(prior_in) >= 4:
        gap = _median(this_in) - _median(prior_in)
        if abs(gap) >= 30:
            way = "晚" if gap > 0 else "早"
            sentences.append(f"{head}到岗比前几周{way}了{_about_minutes(gap)}。")

    if len(sentences) < 2 and active_days >= 3:
        now_day = _weekday_winner(cfg, past, today, min_seen=1)
        old_day = _weekday_winner(cfg, prior_days, today, min_seen=2)
        if now_day is not None and old_day is not None and now_day != old_day:
            sentences.append(f"周{WEEKDAY_CN[old_day]}通常最忙，{head}换成了周{WEEKDAY_CN[now_day]}。")

    if len(sentences) < 2 and len(this_in) >= 3 and not any("到岗" in line for line in sentences):
        spread = max(this_in) - min(this_in)
        clock = fmt_clock(_median(this_in))
        if spread <= 30:
            sentences.append(f"到岗多在 {clock} 前后，前后差不到半小时。")
        elif spread >= 75:
            sentences.append("到岗时间前后差了一个多小时。")
        else:
            sentences.append(f"到岗多在 {clock} 前后。")

    if len(sentences) < 2:
        late = sum(1 for item in finished if item["diff"] is not None and item["diff"] >= 20)
        if late >= 3 and late * 2 >= len(finished):
            sentences.append(f"{head}有 {late} 天晚走。")

    if len(sentences) < 2 and len(finished) >= 3:
        before, after = [], []
        for item in finished:
            slot = _hours_of(cfg, item["date"])
            h = min(23, item["out"] // 60)
            before.append(slot[h] + (slot[h - 1] if h else 0))
            after.append(sum(slot[h + 1 :]))
        if _median(before) >= 6 and _median(after) <= 2:
            sentences.append("离开之后几乎没有操作。")

    if len(sentences) < 2:
        wheels = [0] * 24
        other = [0] * 24
        for d in past:
            c = activity.counts(cfg, d)
            for i in range(24):
                wheels[i] += c["wheels_h"][i]
                other[i] += c["keys_h"][i] + c["clicks_h"][i]
        total = sum(wheels)
        if total >= 20:
            hot = [
                i for i in range(24)
                if wheels[i] >= 8 and wheels[i] >= other[i] and wheels[i] * 5 >= total
            ]
            hot.sort(key=lambda i: wheels[i], reverse=True)
            hot = sorted(hot[:2])
            if len(hot) == 1:
                sentences.append(f"{hot[0]} 点滚轮明显多。")
            elif len(hot) == 2:
                sentences.append(f"{hot[0]} 点和 {hot[1]} 点滚轮明显多。")

    return "".join(sentences[:2])


def summary_text(label: str, s: dict) -> str:
    if not s["days"]:
        return f"{label}还没有记下的天数"
    parts = [f"{label}记了 {s['days']} 天", f"一共 {fmt_span(s['total'])}", f"平均每天 {fmt_span(s['avg'])}"]
    if s["diff"] is not None:
        if s["diff"] == 0:
            parts.append("都正点走")
        elif s["diff"] > 0:
            parts.append(f"一共晚走 {fmt_span(s['diff'])}")
        else:
            parts.append(f"一共早走 {fmt_span(abs(s['diff']))}")
    return "，".join(parts)


def to_csv(cfg: dict, dates: list[date]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["日期", "星期", "来了", "走了", "待了多久", "该走", "比该走", "自填到岗", "自填下班", "到岗差", "离开差", "来源"])
    for d in dates:
        r = row(cfg, d)
        if r["in"] is None and r["out"] is None and r["note_in"] is None and r["note_out"] is None:
            continue
        src = "弹性打卡" if r["src"] == "flex" else "自动"
        w.writerow(
            [
                _key(d),
                "周" + WEEKDAY_CN[d.weekday()],
                fmt_clock(r["in"]),
                fmt_clock(r["out"]),
                fmt_span(r["dur"]),
                fmt_clock(r["target"]),
                fmt_diff(r["diff"]),
                fmt_clock(r["note_in"]),
                fmt_clock(r["note_out"]),
                fmt_note_gap("in", r["arrive_gap"]),
                fmt_note_gap("out", r["leave_gap"]),
                src,
            ]
        )
    return buf.getvalue()


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def last_input_snapshot() -> tuple[int, float] | None:
    """同一次调用取得最后输入 tick 和空闲秒数；失败时不伪装成一次新输入。"""
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return int(info.dwTime), ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:  # noqa: BLE001
        return None


def last_input_tick() -> int | None:
    """最后一次键鼠输入的系统 tick（GetTickCount 口径）；拿不到时 None。"""
    got = last_input_snapshot()
    return got[0] if got is not None else None


def idle_seconds() -> float:
    """距最后一次键鼠输入的秒数；拿不到时当作正在用。"""
    got = last_input_snapshot()
    return got[1] if got is not None else 0.0


def fallback_input(
    previous_tick: int | None,
    snapshot: tuple[int, float] | None,
    now: datetime,
) -> tuple[int | None, datetime | None]:
    """LastInput 仅在事件 tick 改变时补一条；相同值和失败都不算操作。"""
    if snapshot is None:
        return previous_tick, None
    tick, idle = snapshot
    if previous_tick is None:
        return tick, None
    if tick == previous_tick:
        return tick, None
    return tick, now - timedelta(seconds=max(0.0, idle))


class _WakeWatch:
    """墙上时钟在走、待机时钟停着，就是刚从睡眠里出来。"""

    def __init__(self) -> None:
        self.prev_wall: float | None = None
        self.prev_unbiased: int | None = None
        self.quiet_until: datetime | None = None

    def reset(self) -> None:
        self.prev_wall = None
        self.prev_unbiased = None
        self.quiet_until = None

    def observe(self, now: datetime, wall: float, unbiased_100ns: int) -> str:
        gap = False
        if self.prev_wall is not None and self.prev_unbiased is not None:
            wall_delta = wall - self.prev_wall
            unbiased_sec = (unbiased_100ns - self.prev_unbiased) / 10_000_000
            # 待机时墙上的时间继续走，QueryUnbiasedInterruptTime 停住。
            gap = wall_delta >= 5 and unbiased_sec >= 0 and wall_delta > unbiased_sec + 2
        self.prev_wall = wall
        self.prev_unbiased = unbiased_100ns
        if gap:
            self.quiet_until = now + timedelta(seconds=WAKE_QUIET_SEC)
            return "wake"
        if self.quiet_until is not None and now < self.quiet_until:
            return "quiet"
        return "ok"


_wake_watch = _WakeWatch()


def reset_wake_watch() -> None:
    _wake_watch.reset()


def _unbiased_100ns() -> int | None:
    """不含睡眠的中断时间，单位 100 纳秒。Win7 起就有这个接口。"""
    try:
        fn = ctypes.windll.kernel32.QueryUnbiasedInterruptTime
        fn.argtypes = [ctypes.POINTER(ctypes.c_ulonglong)]
        fn.restype = ctypes.c_int
        value = ctypes.c_ulonglong()
        if not fn(ctypes.byref(value)):
            return None
        return int(value.value)
    except Exception:  # noqa: BLE001
        return None


def observe_clock(now: datetime, *, wall: float | None = None, unbiased_100ns: int | None = None) -> str:
    """刚醒来返回 wake，安静窗口里返回 quiet，平时返回 ok。读不到待机时钟就当 ok。"""
    if wall is None:
        wall = now.timestamp()
    if unbiased_100ns is None:
        unbiased_100ns = _unbiased_100ns()
    if unbiased_100ns is None:
        return "ok"
    return _wake_watch.observe(now, wall, unbiased_100ns)
