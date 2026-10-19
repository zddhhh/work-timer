"""工时账本里的键鼠次数图：大数字 + 今天按小时 + 这周每天。"""
from __future__ import annotations

import math
import os
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageTk

import activity
import worklog

W, H = 584, 288
_FONT: dict[tuple, ImageFont.ImageFont] = {}

_PAGE = (22, 26, 34, 255)
_PANEL = (26, 32, 44, 255)
_CLICK = (240, 176, 88, 255)
_CLICK_PEAK = (255, 214, 140, 255)
_KEY = (110, 186, 232, 255)
_KEY_FILL = (110, 186, 232, 36)
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


def today_pack(cfg: dict, d: date) -> dict:
    c = activity.counts(cfg, d)
    split = any(c["keys_h"]) or any(c["clicks_h"])
    combined = any(c["hours"])
    if split:
        mode = "split"
    elif combined:
        mode = "combined"
    else:
        mode = "empty"
    return {
        "mode": mode,
        "keys": c["keys"],
        "clicks": c["clicks"],
        "wheels": c["wheels"],
        "keys_h": c["keys_h"],
        "clicks_h": c["clicks_h"],
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
        tuple(today["hours"]),
        tuple((row["keys"], row["clicks"], row["total"], row["today"]) for row in days),
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

    inset = 20
    plot_l, plot_r = inset, w - inset
    stats_y = 16
    plot_top, plot_bot = 104, 184
    week_top, week_bot = 230, 262

    items = [("键盘", today["keys"], _KEY), ("鼠标", today["clicks"], _CLICK)]
    col_w = (plot_r - plot_l) / len(items)
    for i, (name, val, color) in enumerate(items):
        cx = plot_l + (i + 0.5) * col_w
        if i:
            x = int(plot_l + i * col_w)
            dr.line((x, stats_y + 2, x, stats_y + 42), fill=_GRID, width=1)
        _text(dr, (cx, stats_y + 2), name, size=11, fill=color, anchor="mt")
        _text(dr, (cx, stats_y + 40), activity.fmt_count(val), size=22, fill=_WHITE, anchor="ms", bold=True)

    bits = []
    if today["mode"] == "empty":
        bits.append("今天还没记下次数")
    else:
        cap = _peak_caption(today)
        if cap:
            bits.append(cap)
        if today["wheels"]:
            bits.append(f"滚轮 {activity.fmt_count(today['wheels'])}")
    dr.line((plot_l, 66, plot_r, 66), fill=_GRID, width=1)
    _text(dr, (plot_l, 82), "  ·  ".join(bits), size=11, fill=_MUTED, anchor="lm")

    lo, hi = visible_span(today["hours"], today["keys_h"], today["clicks_h"])
    n = hi - lo + 1
    slot = (plot_r - plot_l) / n
    bar_w = max(7, int(slot * 0.46))
    plot_h = plot_bot - plot_top

    def x_center(hour: int) -> float:
        return plot_l + (hour - lo + 0.5) * slot

    def y_of(v: int, vmax: int) -> int:
        if vmax <= 0 or v <= 0:
            return plot_bot
        return int(plot_bot - min(1.0, v / vmax) * plot_h)

    if today["mode"] == "split":
        cmax = max(today["clicks_h"][lo : hi + 1] or [0])
        kmax = max(today["keys_h"][lo : hi + 1] or [0])
        hmax = max(
            today["hours"][i] if today["clicks_h"][i] == 0 and today["keys_h"][i] == 0 else 0
            for i in range(lo, hi + 1)
        )
    else:
        cmax = kmax = 0
        hmax = max(today["hours"][lo : hi + 1] or [0])

    dr.line((plot_l, plot_bot, plot_r, plot_bot), fill=_LINE, width=1)
    mid_y = (plot_top + plot_bot) // 2
    dr.line((plot_l, plot_top, plot_r, plot_top), fill=_GRID, width=1)
    dr.line((plot_l, mid_y, plot_r, mid_y), fill=_GRID, width=1)

    peak = today["peak"]
    peak_h = peak[0] if peak else None
    for hour in range(lo, hi + 1):
        cx = x_center(hour)
        x0 = int(cx - bar_w / 2)
        x1 = x0 + bar_w
        if today["mode"] == "split":
            clicks = today["clicks_h"][hour]
            keys = today["keys_h"][hour]
            legacy = today["hours"][hour] if clicks == 0 and keys == 0 else 0
            if clicks:
                fill = _CLICK_PEAK if hour == peak_h else _CLICK
                _bar(dr, (x0, y_of(clicks, cmax), x1, plot_bot), fill)
            elif legacy:
                _bar(dr, (x0, y_of(legacy, hmax), x1, plot_bot), _COMBINED)
            hits.append(
                {
                    "x0": int(cx - slot / 2),
                    "x1": int(cx + slot / 2),
                    "y0": plot_top,
                    "y1": plot_bot + 16,
                    "text": (
                        f"{hour}点  操作 {activity.fmt_count(legacy)} 次"
                        if legacy
                        else f"{hour}点  点了 {activity.fmt_count(clicks)} 次  敲了 {activity.fmt_count(keys)} 下"
                    ),
                }
            )
        else:
            v = today["hours"][hour]
            if v:
                fill = _CLICK_PEAK if hour == peak_h else _COMBINED
                _bar(dr, (x0, y_of(v, hmax), x1, plot_bot), fill)
            hits.append(
                {
                    "x0": int(cx - slot / 2),
                    "x1": int(cx + slot / 2),
                    "y0": plot_top,
                    "y1": plot_bot + 16,
                    "text": f"{hour}点  操作 {activity.fmt_count(v)} 次",
                }
            )
        if hour in (8, 10, 12, 14, 16, 18):
            _text(dr, (cx, plot_bot + 8), str(hour), size=10, fill=_DIM, anchor="mt")

    if today["mode"] == "split" and kmax:
        pts = [(x_center(hour), y_of(today["keys_h"][hour], kmax)) for hour in range(lo, hi + 1)]
        if len(pts) >= 2:
            wash = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            ImageDraw.Draw(wash).polygon(
                [(pts[0][0], plot_bot)] + pts + [(pts[-1][0], plot_bot)],
                fill=_KEY_FILL,
            )
            im.paste(Image.alpha_composite(im, wash), (0, 0))
            dr = ImageDraw.Draw(im)
            dr.line(pts, fill=_KEY, width=2)

    week_word = "本周点击" if this_week else "这周点击"
    use_clicks = any(row["clicks"] for row in days)
    if not use_clicks:
        week_word = "本周键盘" if this_week else "这周键盘"
    _text(dr, (plot_l, week_top - 18), week_word, size=11, fill=_MUTED, anchor="lm")
    week_vals = [row["clicks"] if use_clicks else row["keys"] for row in days]
    week_max = max(week_vals, default=0)
    col = (plot_r - plot_l) / max(1, len(days))
    bar_dw = max(8, int(col * 0.28))
    bar_h = week_bot - week_top
    for i, row in enumerate(days):
        cx = plot_l + (i + 0.5) * col
        x0 = int(cx - bar_dw / 2)
        x1 = x0 + bar_dw
        keys, clicks = row["keys"], row["clicks"]
        v = clicks if use_clicks else keys
        h_px = int((v / week_max) * bar_h) if week_max and v else 0
        y0 = week_bot - max(h_px, 3 if v else 0)
        if v:
            if row["weekend"]:
                fill = _DIM
            elif row["today"]:
                fill = _CLICK_PEAK if use_clicks else _KEY
            else:
                fill = _CLICK if use_clicks else _KEY
            _bar(dr, (x0, y0, x1, week_bot), fill, radius=3)
        wd = worklog.WEEKDAY_CN[row["date"].weekday()]
        if row["today"]:
            _round(dr, (cx - 10, week_bot + 4, cx + 10, week_bot + 18), (48, 56, 72, 255), radius=8)
            fill = _TODAY
        else:
            fill = _DIM if row["weekend"] else _MUTED
        _text(dr, (cx, week_bot + 11), wd, size=10, fill=fill, anchor="mm")
        d = row["date"]
        hits.append(
            {
                "x0": int(cx - col / 2),
                "x1": int(cx + col / 2),
                "y0": week_top - 8,
                "y1": h - 8,
                "text": (
                    f"周{wd} {d.month}/{d.day}  点了 {activity.fmt_count(clicks)} 次  "
                    f"敲了 {activity.fmt_count(keys)} 下"
                ),
            }
        )
    return im, hits


def paint_into(ui: dict, cfg: dict, *, today: date, days: list[date], enabled: bool, this_week: bool) -> None:
    """账本开着时重画。数据没变就跳过，避免每秒重建图片。"""
    pack = today_pack(cfg, today)
    week = week_pack(cfg, days, today)
    sig = signature(pack, week, enabled=enabled, this_week=this_week)
    if ui.get("chart_sig") == sig and ui.get("chart_photo") is not None:
        return
    im, hits = render(pack, week, enabled=enabled, this_week=this_week)
    photo = ImageTk.PhotoImage(im)
    lbl = ui.get("chart_lbl")
    if lbl is not None:
        lbl.configure(image=photo)
    ui["chart_photo"] = photo
    ui["chart_hits"] = hits
    ui["chart_sig"] = sig


def hover_text(hits: list[dict], x: int, y: int) -> str:
    for hit in hits:
        if hit["x0"] <= x < hit["x1"] and hit["y0"] <= y <= hit["y1"]:
            return str(hit["text"])
    return ""
