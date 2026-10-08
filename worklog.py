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

KEEP_DAYS = 400
IDLE_LIMIT_SEC = 300
# 已过应下班点、且距上次活动超过这么久，视为已下班；之后的键鼠活动（如晚上在家用电脑）不再算进当天。
# 只有最后活动落在应下班前 CLOSE_LEAD_MIN 内（或之后）才封账，下午开长会回来继续干不会被截断。
CLOSE_GAP_MIN = 90
CLOSE_LEAD_MIN = 60
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


def fmt_span(minutes: int | None, *, signed: bool = False) -> str:
    if minutes is None:
        return ""
    sign = ""
    if signed:
        sign = "+" if minutes > 0 else ("-" if minutes < 0 else "±")
    m = abs(int(minutes))
    return f"{sign}{m // 60}:{m % 60:02d}"


def ensure_fields(cfg: dict, *, today: date | None = None) -> None:
    raw = cfg.get("worklog")
    if not isinstance(raw, dict):
        cfg["worklog"] = {}
        return
    cutoff = _key((today or date.today()) - timedelta(days=KEEP_DAYS))
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


def heartbeat(
    cfg: dict,
    now: datetime,
    *,
    active: bool,
    target_hm: tuple[int, int] | None,
) -> bool:
    """有键鼠活动时把当天离开时刻推到现在。返回是否改了账本。"""
    if not active:
        return False
    book = _days(cfg)
    k = _key(now.date())
    item = book.get(k)
    if isinstance(item, dict) and (item.get("manual") or item.get("closed")):
        return False
    cur = now.hour * 60 + now.minute
    changed = False
    if not isinstance(item, dict):
        item = {"in": cur, "src": "seen"}
        book[k] = item
        changed = True
    target = None if target_hm is None else int(target_hm[0]) * 60 + int(target_hm[1])
    if target is not None and item.get("target") != target:
        item["target"] = target
        changed = True
    last = _as_min(item.get("out"))
    tgt = _as_min(item.get("target"))
    if (
        last is not None
        and tgt is not None
        and cur >= tgt
        and last >= tgt - CLOSE_LEAD_MIN
        and cur - last > CLOSE_GAP_MIN
    ):
        item["closed"] = True
        return True
    if "in" not in item:
        item["in"] = cur
        item["src"] = "seen"
        changed = True
    if (last is None or cur > last) and cur >= item["in"]:
        item["out"] = cur
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
    # 今天还在记录中：离开时刻只是「最后一次活动」，算差额会显示成大段早退
    live = d == (today or date.today()) and mo is not None and not (item.get("closed") or item.get("manual"))
    diff = mo - mt if mo is not None and mt is not None and not live else None
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
        return f"{label}：暂无记录"
    parts = [f"{label} {s['days']} 天", f"共 {fmt_span(s['total'])}", f"日均 {fmt_span(s['avg'])}"]
    if s["diff"] is not None:
        parts.append(f"比应下班 {fmt_span(s['diff'], signed=True)}")
    return " · ".join(parts)


def to_csv(cfg: dict, dates: list[date]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["日期", "星期", "到岗", "离开", "时长", "应下班", "比应下班(分钟)", "来源"])
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
                "" if r["diff"] is None else r["diff"],
                src,
            ]
        )
    return buf.getvalue()


class _LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]


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
