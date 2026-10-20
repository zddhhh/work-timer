"""工时账本：每天到岗 / 离开时刻，周、月统计与 CSV 导出。

cfg["worklog"] = {"YYYY-MM-DD": {"in": 分钟, "out": 分钟, "target": 分钟, "src": "flex|seen",
                                 "closed": bool, "manual": bool}}
分钟 = 当天 0 点起的分钟数。
"""
from __future__ import annotations

import ctypes
import csv
import io
from datetime import date, datetime, timedelta

import flex_time

IDLE_LIMIT_SEC = 300
# 已过应下班点、且距上次活动超过这么久，视为已下班；之后的键鼠活动（如晚上在家用电脑）不再算进当天。
# 只有最后活动落在应下班前 CLOSE_LEAD_MIN 内（或之后）才封账，下午开长会回来继续干不会被截断。
CLOSE_GAP_MIN = 90
CLOSE_LEAD_MIN = 60
# 采样把「离开」写成轮询时刻时，最多偏这么多分钟，下一笔用真实最后输入收回来。
SNAP_MIN = IDLE_LIMIT_SEC // 60
WEEKDAY_CN = "一二三四五六日"


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


def fmt_hms(total_seconds: int) -> str:
    total = max(0, int(total_seconds))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}"


def live_elapsed(r: dict, now: datetime, idle_sec: float) -> str | None:
    """进行中的时长，精确到秒。已经封账或不是今天则返回 None。"""
    if not r.get("live") or r.get("in") is None:
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
        for f in ("in", "out", "target"):
            m = _as_min(v.get(f))
            if m is not None:
                item[f] = m
        if not item:
            continue
        item["src"] = "flex" if v.get("src") == "flex" else "seen"
        if v.get("closed"):
            item["closed"] = True
        if v.get("manual"):
            item["manual"] = True
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


def should_track(now: datetime, *, has_target: bool, set_today: bool) -> bool:
    """周末默认不记（固定下班「记住」会让周末也有倒计时）；当天手动设过下班则照记。"""
    if not has_target:
        return False
    return now.weekday() < 5 or set_today


def record_arrival(cfg: dict, now: datetime, hm: tuple[int, int]) -> None:
    """弹性打卡：到岗以用户填的时刻为准，覆盖首次使用时刻。"""
    item = _days(cfg).setdefault(_key(now.date()), {})
    item["in"] = int(hm[0]) * 60 + int(hm[1])
    item["src"] = "flex"
    item.pop("manual", None)
    item.pop("closed", None)
    out = item.get("out")
    if isinstance(out, int) and out < item["in"]:
        item.pop("out", None)


def last_active_minute(now: datetime, idle_sec: float) -> int | None:
    """最后一次键鼠落在哪一分钟。跨过零点则不算今天。"""
    if idle_sec < 0:
        idle_sec = 0.0
    last = now - timedelta(seconds=float(idle_sec))
    if last.date() != now.date():
        return None
    return last.hour * 60 + last.minute


def heartbeat(
    cfg: dict,
    now: datetime,
    *,
    active: bool,
    target_hm: tuple[int, int] | None,
    activity_min: int | None = None,
) -> bool:
    """离开时刻记最后一次键鼠所在的分钟，不记轮询时刻。

    空闲时只更新应下班、必要时封账，不把「现在」写成离开。
    activity_min 缺省时用 now 的分钟（测试）。返回是否改了账本。
    """
    book = _days(cfg)
    item = book.get(_key(now.date()))
    if isinstance(item, dict) and (item.get("manual") or item.get("closed")):
        return False
    now_min = now.hour * 60 + now.minute
    mark = now_min if activity_min is None else activity_min
    if isinstance(mark, bool) or not isinstance(mark, int) or not (0 <= mark < 24 * 60):
        mark = now_min
    target = None if target_hm is None else int(target_hm[0]) * 60 + int(target_hm[1])
    changed = False
    if not isinstance(item, dict):
        if not active:
            return False
        item = {"in": mark, "src": "seen"}
        book[_key(now.date())] = item
        changed = True
    if target is not None and item.get("target") != target:
        item["target"] = target
        changed = True
    last = _as_min(item.get("out"))
    tgt = _as_min(item.get("target"))
    if (
        last is not None
        and tgt is not None
        and now_min >= tgt
        and last >= tgt - CLOSE_LEAD_MIN
        and now_min - last > CLOSE_GAP_MIN
    ):
        item["closed"] = True
        return True
    if not active:
        return changed
    if "in" not in item:
        item["in"] = mark
        item["src"] = "seen"
        changed = True
    arrived = _as_min(item.get("in"))
    if arrived is None or mark < arrived:
        return changed
    if last is None or mark > last:
        item["out"] = mark
        changed = True
    elif 0 < last - mark <= SNAP_MIN:
        # 上一笔把离开写成了采样时刻，收回真实最后输入
        item["out"] = mark
        changed = True
    return changed


def set_manual(cfg: dict, d: date, in_text: str, out_text: str) -> str | None:
    """手改某天。两个都留空 = 删除这天。返回错误文案，成功返回 None。"""
    in_text = (in_text or "").strip()
    out_text = (out_text or "").strip()
    book = _days(cfg)
    k = _key(d)
    if not in_text and not out_text:
        book.pop(k, None)
        return None
    pin = flex_time.parse_clock(in_text) if in_text else None
    pout = flex_time.parse_clock(out_text) if out_text else None
    if in_text and pin is None:
        return f"{d.month}/{d.day} 到岗时间看不懂：{in_text}"
    if out_text and pout is None:
        return f"{d.month}/{d.day} 离开时间看不懂：{out_text}"
    mi = None if pin is None else pin[0] * 60 + pin[1]
    mo = None if pout is None else pout[0] * 60 + pout[1]
    if mi is not None and mo is not None and mo < mi:
        return f"{d.month}/{d.day} 离开早于到岗"
    item = book.setdefault(k, {"src": "seen"})
    for f, v in (("in", mi), ("out", mo)):
        if v is None:
            item.pop(f, None)
        else:
            item[f] = v
    item["manual"] = True
    item.pop("closed", None)
    return None


def row(cfg: dict, d: date, *, today: date | None = None) -> dict:
    item = get_day(cfg, d) or {}
    mi, mo, mt = _as_min(item.get("in")), _as_min(item.get("out")), _as_min(item.get("target"))
    dur = mo - mi if mi is not None and mo is not None else None
    # 还没到应下班就用「离开-应下班」，下午会显示成大段早退。过了应下班再显示差额。
    live = d == (today or date.today()) and mo is not None and not (item.get("closed") or item.get("manual"))
    show_diff = mo is not None and mt is not None and (not live or mo >= mt)
    diff = (mo - mt) if show_diff else None
    return {
        "date": d,
        "in": mi,
        "out": mo,
        "target": mt,
        "dur": dur,
        "diff": diff,
        "src": item.get("src", ""),
        "manual": bool(item.get("manual")),
        "closed": bool(item.get("closed")),
        "live": live,
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
    w.writerow(["日期", "星期", "来了", "走了", "待了多久", "该走", "比该走", "来源"])
    for d in dates:
        r = row(cfg, d)
        if r["in"] is None and r["out"] is None:
            continue
        src = "手改" if r["manual"] else ("弹性打卡" if r["src"] == "flex" else "首次使用")
        w.writerow(
            [
                _key(d),
                "周" + WEEKDAY_CN[d.weekday()],
                fmt_clock(r["in"]),
                fmt_clock(r["out"]),
                fmt_span(r["dur"]),
                fmt_clock(r["target"]),
                fmt_diff(r["diff"]),
                src,
            ]
        )
    return buf.getvalue()


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


def last_input_tick() -> int | None:
    """最后一次键鼠输入的系统 tick（GetTickCount 口径）；拿不到时 None。"""
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return None
        return int(info.dwTime)
    except Exception:  # noqa: BLE001
        return None


def idle_seconds() -> float:
    """距最后一次键鼠输入的秒数；拿不到时当作正在用。"""
    try:
        info = _LASTINPUTINFO()
        info.cbSize = ctypes.sizeof(info)
        if not ctypes.windll.user32.GetLastInputInfo(ctypes.byref(info)):
            return 0.0
        tick = ctypes.windll.kernel32.GetTickCount() & 0xFFFFFFFF
        return ((tick - info.dwTime) & 0xFFFFFFFF) / 1000.0
    except Exception:  # noqa: BLE001
        return 0.0
