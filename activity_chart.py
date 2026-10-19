"""工时账本里的键鼠次数图：三个总数，下面按小时分成三行。"""
from __future__ import annotations

import math
import os
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageTk

import activity

W, H = 584, 292
IDLE_READOUT = "移到柱上，看这一小时各是多少"
READOUT = (16, 258, 568, 280)
_FONT: dict[tuple, ImageFont.ImageFont] = {}

_PAGE = (22, 26, 34, 255)
_PANEL = (26, 32, 44, 255)
_CLICK = (240, 176, 88, 255)
_CLICK_PEAK = (255, 214, 140, 255)
_KEY = (110, 186, 232, 255)
_WHEEL = (125, 206, 160, 255)
_COMBINED = (154, 176, 214, 255)
_MUTED = (132, 140, 156, 255)
_DIM = (90, 98, 114, 255)
_GRID = (48, 56, 72, 255)
_LINE = (58, 66, 82, 255)
_WHITE = (240, 243, 248, 255)
_TODAY = (240, 243, 248, 255)


def _font(size: float, *, bold: bool = False) -> ImageFont.ImageFont:
    key = (round(float(size) * 4.0) / 4.0, bold)
    got = _FONT.get(key)
    if got is not None:
        return got
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    names = ("msyhbd.ttc", "msyhbd.ttf", "msyh.ttc") if bold else ("msyh.ttc", "msyh.ttf", "msyhbd.ttc", "simhei.ttf")
    for name in names:
        try:
            got = ImageFont.truetype(str(windir / name), key[0])
            break
        except OSError:
            continue
    if got is None:
        got = ImageFont.load_default()
    _FONT[key] = got
    return got


def nice_max(n: int) -> int:
    n = max(0, int(n))
    if n <= 10:
        return 10
    exp = 10 ** int(math.floor(math.log10(n)))
    for m in (1, 1.5, 2, 3, 5, 10):
        if m * exp >= n:
            return int(m * exp)
    return int(10 * exp)


def visible_span(*cols: list[int], work_lo: int = 8, work_hi: int = 19) -> tuple[int, int]:
    """默认画出上班时段；若更早或更晚有次数，把轴拉开。"""
    lo, hi = work_lo, work_hi
    for col in cols:
        for i, v in enumerate(col[:24]):
            if v:
                lo = min(lo, i)
                hi = max(hi, i)
    return max(0, lo), min(23, hi)


def hourly_series(c: dict) -> tuple[str, list[int], list[int], list[int]]:
    """键盘、鼠标、滚轮按小时分开。旧数据只有合计时，滚轮用合计减去前两项。"""
    keys = list(c["keys_h"])
    clicks = list(c["clicks_h"])
    wheels = list(c["wheels_h"])
    if any(wheels) or any(keys) or any(clicks):
        if not any(wheels):
            wheels = [max(0, h - k - cl) for h, k, cl in zip(c["hours"], keys, clicks)]
        return "split", keys, clicks, wheels
    if any(c["hours"]):
        return "combined", list(c["hours"]), [0] * 24, [0] * 24
    return "empty", keys, clicks, wheels


def today_pack(cfg: dict, d: date) -> dict:
    c = activity.counts(cfg, d)
    mode, keys_h, clicks_h, wheels_h = hourly_series(c)
    return {
        "mode": mode,
        "keys": c["keys"],
        "clicks": c["clicks"],
        "wheels": c["wheels"],
        "keys_h": keys_h,
        "clicks_h": clicks_h,
        "wheels_h": wheels_h,
        "hours": c["hours"],
        "peak": activity.peak_hours(c["hours"]),
    }


def week_pack(cfg: dict, days: list[date], today: date) -> list[dict]:
    out = []
    for d in days:
        c = activity.counts(cfg, d)
        out.append(
            {
                "date": d,
                "keys": c["keys"],
                "clicks": c["clicks"],
                "wheels": c["wheels"],
                "total": c["keys"] + c["clicks"] + c["wheels"],
                "today": d == today,
                "weekend": d.weekday() >= 5,
            }
        )
    return out


def signature(today: dict, days: list[dict], *, enabled: bool, this_week: bool) -> tuple:
    return (
        enabled,
        this_week,
        today["mode"],
        today["keys"],
        today["clicks"],
        today["wheels"],
        tuple(today["keys_h"]),
        tuple(today["clicks_h"]),
        tuple(today["wheels_h"]),
        tuple(today["hours"]),
        tuple((row["keys"], row["clicks"], row["wheels"], row["today"]) for row in days),
    )


def _round(dr: ImageDraw.ImageDraw, box, fill, radius: int = 4, outline=None) -> None:
    x0, y0, x1, y1 = (int(v) for v in box)
    if x1 <= x0 or y1 <= y0:
        return
    r = max(1, min(radius, (x1 - x0) // 2, (y1 - y0) // 2))
    try:
        dr.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=fill, outline=outline)
    except Exception:
        dr.rectangle((x0, y0, x1, y1), fill=fill, outline=outline)


def _bar(dr: ImageDraw.ImageDraw, box, fill, radius: int = 3) -> None:
    x0, y0, x1, y1 = (int(v) for v in box)
    if y1 - y0 < 2:
        y0 = y1 - 2
    _round(dr, (x0, y0, x1, y1), fill, radius=radius)


def _text(dr: ImageDraw.ImageDraw, xy, text: str, *, fill=_MUTED, size: float = 11, anchor: str = "lt", bold: bool = False) -> None:
    dr.text(xy, text, font=_font(size, bold=bold), fill=fill, anchor=anchor)


def _peak_caption(today: dict) -> str:
    peak = today.get("peak")
    if not peak:
        return ""
    a, b = peak
    if b - a == 1:
        return f"最勤 {a} 点这一小时"
    return f"最勤 {a}–{b} 点"


def _hour_text(hour: int, today: dict) -> str:
    if today["mode"] == "combined":
        return f"{hour}点    操作 {activity.fmt_count(today['hours'][hour])}"
    return (
        f"{hour}点    键盘 {activity.fmt_count(today['keys_h'][hour])}"
        f"    鼠标 {activity.fmt_count(today['clicks_h'][hour])}"
        f"    滚轮 {activity.fmt_count(today['wheels_h'][hour])}"
    )


def _paint_readout(im: Image.Image, text: str, *, active: bool = False) -> None:
    x0, y0, x1, y1 = READOUT
    dr = ImageDraw.Draw(im)
    dr.rectangle((x0, y0, x1, y1), fill=_PANEL)
    _round(dr, (x0, y0, x1, y1), (36, 44, 58, 255), radius=8)
    _text(dr, ((x0 + x1) / 2, (y0 + y1) / 2), text, size=12, fill=_WHITE if active else _MUTED, anchor="mm")


def render(
    today: dict,
    days: list[dict],
    *,
    enabled: bool,
    this_week: bool,
    w: int = W,
    h: int = H,
) -> tuple[Image.Image, list[dict]]:
    im = Image.new("RGBA", (w, h), _PAGE)
    dr = ImageDraw.Draw(im)
    _round(dr, (0, 0, w - 1, h - 1), _PANEL, radius=12)
    hits: list[dict] = []
    if not enabled:
        _text(dr, (w / 2, h / 2 - 10), "打开开关，开始数今天敲了多少、点了多少", size=13, fill=_WHITE, anchor="mm")
        _text(dr, (w / 2, h / 2 + 12), "只记次数，不记按了哪个键，也不上传", size=11, fill=_MUTED, anchor="mm")
        return im, hits

    inset = 18
    plot_l, plot_r = 62, w - inset
    stats_y = 16
    items = (("键盘", today["keys"], _KEY), ("鼠标", today["clicks"], _CLICK), ("滚轮", today["wheels"], _WHEEL))
    col_w = (w - inset * 2) / 3
    for i, (name, val, color) in enumerate(items):
        cx = inset + (i + 0.5) * col_w
        if i:
            x = int(inset + i * col_w)
            dr.line((x, stats_y + 4, x, stats_y + 44), fill=_GRID, width=1)
        _text(dr, (cx, stats_y + 2), name, size=11, fill=color, anchor="mt")
        _text(dr, (cx, stats_y + 42), activity.fmt_count(val), size=22, fill=_WHITE, anchor="ms", bold=True)

    cap = "今天还没记下次数" if today["mode"] == "empty" else _peak_caption(today)
    _text(dr, (inset, 78), cap, size=11, fill=_MUTED, anchor="lm")

    lo, hi = visible_span(today["hours"], today["keys_h"], today["clicks_h"], today["wheels_h"])
    n = hi - lo + 1
    slot = (plot_r - plot_l) / n
    bar_w = max(6, int(slot * 0.46))
    if today["mode"] == "combined":
        rows = (("操作", today["hours"], _COMBINED),)
    else:
        rows = (
            ("鼠标", today["clicks_h"], _CLICK),
            ("键盘", today["keys_h"], _KEY),
            ("滚轮", today["wheels_h"], _WHEEL),
        )
    row_h = 42
    rows_top = 96
    bar_room = 30

    def x_center(hour: int) -> float:
        return plot_l + (hour - lo + 0.5) * slot

    for i, (name, series, color) in enumerate(rows):
        top = rows_top + i * row_h
        base = top + bar_room
        vmax = max(series[lo : hi + 1] or [0])
        _text(dr, (inset, (top + base) / 2), name, size=11, fill=color, anchor="lm")
        dr.line((plot_l, base, plot_r, base), fill=_LINE, width=1)
        if vmax <= 0:
            continue
        for hour in range(lo, hi + 1):
            v = series[hour]
            if not v:
                continue
            cx = x_center(hour)
            x0 = int(cx - bar_w / 2)
            y0 = int(base - (v / vmax) * bar_room)
            _bar(dr, (x0, y0, x0 + bar_w, base), color, radius=2)

    axis_y = rows_top + len(rows) * row_h + 2
    for hour in range(lo, hi + 1):
        if hour in (8, 10, 12, 14, 16, 18):
            _text(dr, (x_center(hour), axis_y), str(hour), size=10, fill=_DIM, anchor="mt")
    for hour in range(lo, hi + 1):
        cx = x_center(hour)
        hits.append(
            {
                "x0": int(cx - slot / 2),
                "x1": int(cx + slot / 2),
                "y0": rows_top,
                "y1": axis_y + 12,
                "text": _hour_text(hour, today),
            }
        )

    _paint_readout(im, IDLE_READOUT)
    return im, hits


def paint_into(ui: dict, cfg: dict, *, today: date, days: list[date], enabled: bool, this_week: bool) -> None:
    """账本开着时重画。数据没变就跳过，避免每秒重建图片。"""
    pack = today_pack(cfg, today)
    week = week_pack(cfg, days, today)
    sig = signature(pack, week, enabled=enabled, this_week=this_week)
    if ui.get("chart_sig") == sig and ui.get("chart_base") is not None:
        return
    im, hits = render(pack, week, enabled=enabled, this_week=this_week)
    ui["chart_base"] = im
    ui["chart_hits"] = hits
    ui["chart_sig"] = sig
    ui["chart_hover"] = None
    apply_hover(ui, -1, -1)


def apply_hover(ui: dict, x: int, y: int) -> None:
    base = ui.get("chart_base")
    if base is None:
        return
    text = hover_text(ui.get("chart_hits") or [], x, y) or IDLE_READOUT
    if text == ui.get("chart_hover") and ui.get("chart_photo") is not None:
        return
    im = base.copy()
    _paint_readout(im, text, active=text != IDLE_READOUT)
    photo = ImageTk.PhotoImage(im)
    lbl = ui.get("chart_lbl")
    if lbl is not None:
        lbl.configure(image=photo)
    ui["chart_photo"] = photo
    ui["chart_hover"] = text


def hover_text(hits: list[dict], x: int, y: int) -> str:
    for hit in reversed(hits):
        if hit["x0"] <= x < hit["x1"] and hit["y0"] <= y <= hit["y1"]:
            return str(hit["text"])
    return ""
