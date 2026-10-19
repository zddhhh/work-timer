"""工时账本里的键鼠次数图：今天按小时柱+折线，这周每天一根柱。"""
from __future__ import annotations

import math
import os
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageTk

import activity
import worklog

W, H = 600, 216
_FONT: dict[float, ImageFont.ImageFont] = {}

_BG = (30, 36, 48, 255)
_CLICK = (255, 196, 107, 255)
_CLICK_PEAK = (255, 224, 168, 255)
_KEY = (126, 200, 255, 255)
_COMBINED = (154, 176, 214, 255)
_MUTED = (139, 147, 165, 255)
_GRID = (42, 49, 64, 255)
_AXIS = (70, 78, 94, 255)
_TODAY_RING = (240, 243, 248, 220)
_WEEKEND = (90, 98, 112, 255)
_WHITE = (240, 243, 248, 255)


def _font(size: float) -> ImageFont.ImageFont:
    key = round(float(size) * 4.0) / 4.0
    got = _FONT.get(key)
    if got is not None:
        return got
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyh.ttf", "msyhbd.ttc", "simhei.ttf"):
        try:
            got = ImageFont.truetype(str(windir / name), key)
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


def _round_bar(dr: ImageDraw.ImageDraw, box: tuple[int, int, int, int], fill, radius: int = 4) -> None:
    x0, y0, x1, y1 = box
    if y1 - y0 < 2:
        y0 = y1 - 2
    r = max(1, min(radius, (x1 - x0) // 2, (y1 - y0) // 2))
    try:
        dr.rounded_rectangle((x0, y0, x1, y1), radius=r, fill=fill)
    except Exception:
        dr.rectangle((x0, y0, x1, y1), fill=fill)


def _text(dr: ImageDraw.ImageDraw, xy, text: str, *, fill=_MUTED, size: float = 11, anchor: str = "lt") -> None:
    dr.text(xy, text, font=_font(size), fill=fill, anchor=anchor)


def render(
    today: dict,
    days: list[dict],
    *,
    enabled: bool,
    this_week: bool,
    w: int = W,
    h: int = H,
) -> tuple[Image.Image, list[dict]]:
    im = Image.new("RGBA", (w, h), _BG)
    dr = ImageDraw.Draw(im)
    hits: list[dict] = []
    if not enabled:
        _text(dr, (w // 2, h // 2), "打开开关后，这里会画出今天每小时点了多少、敲了多少。", size=12, fill=_MUTED, anchor="mm")
        return im, hits

    pad_l, pad_r = 44, 14
    top, today_bot = 28, 124
    week_top, week_bot = 152, 210
    plot_w = w - pad_l - pad_r

    lo, hi = visible_span(today["hours"], today["keys_h"], today["clicks_h"])
    n = hi - lo + 1
    slot = plot_w / n
    bar_w = max(6, int(slot * 0.5))

    if today["mode"] == "split":
        y_src = [
            c if a == 0 and b == 0 else max(a, b)
            for a, b, c in zip(today["keys_h"], today["clicks_h"], today["hours"])
        ]
    else:
        y_src = list(today["hours"])
    ymax = nice_max(max(y_src[lo : hi + 1] + [0]))
    plot_h = today_bot - top

    def x_center(hour: int) -> float:
        return pad_l + (hour - lo + 0.5) * slot

    def y_at(v: int) -> int:
        return int(today_bot - (v / ymax) * plot_h) if ymax else today_bot

    for frac, label in ((1.0, activity.fmt_count(ymax)), (0.5, activity.fmt_count(ymax // 2)), (0.0, "0")):
        y = int(today_bot - frac * plot_h)
        dr.line((pad_l, y, w - pad_r, y), fill=_GRID, width=1)
        _text(dr, (pad_l - 6, y), label, size=10, fill=_MUTED, anchor="rm")
    dr.line((pad_l, today_bot, w - pad_r, today_bot), fill=_AXIS, width=1)

    week_word = "本周" if this_week else "这周"
    _text(dr, (pad_l, 8), "今天按小时", size=12, fill=_WHITE, anchor="lm")
    if today["mode"] == "combined":
        dr.rectangle((w - pad_r - 46, 4, w - pad_r - 34, 14), fill=_COMBINED)
        _text(dr, (w - pad_r - 30, 8), "操作", size=11, fill=_COMBINED, anchor="lm")
    else:
        dr.rectangle((w - pad_r - 102, 4, w - pad_r - 90, 14), fill=_CLICK)
        _text(dr, (w - pad_r - 86, 8), "鼠标", size=11, fill=_CLICK, anchor="lm")
        dr.line((w - pad_r - 48, 9, w - pad_r - 32, 9), fill=_KEY, width=2)
        _text(dr, (w - pad_r - 28, 8), "键盘", size=11, fill=_KEY, anchor="lm")

    peak = today["peak"]
    peak_h = peak[0] if peak else None
    step = 2 if n > 12 else 1
    for hour in range(lo, hi + 1):
        cx = x_center(hour)
        x0 = int(cx - bar_w / 2)
        x1 = x0 + bar_w
        if today["mode"] == "split":
            clicks = today["clicks_h"][hour]
            keys = today["keys_h"][hour]
            legacy = today["hours"][hour] if clicks == 0 and keys == 0 else 0
            fill = _CLICK_PEAK if hour == peak_h and clicks else _CLICK
            if clicks:
                _round_bar(dr, (x0, y_at(clicks), x1, today_bot), fill, radius=2)
            elif legacy:
                _round_bar(dr, (x0, y_at(legacy), x1, today_bot), _COMBINED, radius=2)
            hits.append(
                {
                    "x0": int(cx - slot / 2),
                    "x1": int(cx + slot / 2),
                    "y0": top,
                    "y1": today_bot,
                    "text": (
                        f"{hour}点  操作 {activity.fmt_count(legacy)} 次"
                        if legacy
                        else f"{hour}点  点了 {activity.fmt_count(clicks)} 次  敲了 {activity.fmt_count(keys)} 下"
                    ),
                }
            )
        else:
            v = today["hours"][hour]
            fill = _CLICK_PEAK if hour == peak_h and v else _COMBINED
            if v:
                _round_bar(dr, (x0, y_at(v), x1, today_bot), fill, radius=2)
            hits.append(
                {
                    "x0": int(cx - slot / 2),
                    "x1": int(cx + slot / 2),
                    "y0": top,
                    "y1": today_bot,
                    "text": f"{hour}点  操作 {activity.fmt_count(v)} 次",
                }
            )
        if hour % step == 0 or hour in (8, 12, 18) or hour == lo or hour == hi:
            _text(dr, (cx, today_bot + 4), str(hour), size=10, fill=_MUTED, anchor="mt")

    if today["mode"] == "split" and any(today["keys_h"][lo : hi + 1]):
        pts = [(x_center(hour), y_at(today["keys_h"][hour])) for hour in range(lo, hi + 1)]
        if len(pts) >= 2:
            wash = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            wd = ImageDraw.Draw(wash)
            area = [(pts[0][0], today_bot)] + pts + [(pts[-1][0], today_bot)]
            wd.polygon(area, fill=(126, 200, 255, 32))
            im.paste(Image.alpha_composite(im, wash), (0, 0))
            dr = ImageDraw.Draw(im)
            dr.line(pts, fill=_KEY, width=2)
        for x, y in pts:
            dr.ellipse((x - 2.5, y - 2.5, x + 2.5, y + 2.5), fill=_BG)
            dr.ellipse((x - 2, y - 2, x + 2, y + 2), fill=_KEY)

    if today["mode"] == "empty":
        _text(dr, ((pad_l + w - pad_r) / 2, (top + today_bot) / 2), "今天还没记下次数", size=12, fill=_MUTED, anchor="mm")

    dr.line((pad_l, week_top - 8, w - pad_r, week_top - 8), fill=_GRID, width=1)
    _text(dr, (pad_l, (week_top + week_bot) / 2 - 6), week_word, size=11, fill=_MUTED, anchor="lm")
    week_left = pad_l + 36
    week_w = w - pad_r - week_left
    use_clicks = any(row["clicks"] for row in days)
    week_vals = [row["clicks"] if use_clicks else row["keys"] for row in days]
    week_max = max(week_vals, default=0)
    col_w = week_w / max(1, len(days))
    bar_dw = max(6, int(col_w * 0.22))
    bar_h = week_bot - week_top - 16
    y1 = week_bot - 16
    for i, row in enumerate(days):
        cx = week_left + (i + 0.5) * col_w
        x0 = int(cx - bar_dw / 2)
        x1 = x0 + bar_dw
        keys, clicks = row["keys"], row["clicks"]
        v = clicks if use_clicks else keys
        h_px = int((v / week_max) * bar_h) if week_max and v else 0
        y0 = y1 - max(h_px, 3 if v else 0)
        if v:
            fill = _WEEKEND if row["weekend"] else (_CLICK if use_clicks else _KEY)
            _round_bar(dr, (x0, y0, x1, y1), fill, radius=2)
        if row["today"]:
            dr.line((x0 - 1, week_bot - 3, x1 + 1, week_bot - 3), fill=_WHITE, width=2)
        wd = worklog.WEEKDAY_CN[row["date"].weekday()]
        fill = _WHITE if row["today"] else (_WEEKEND if row["weekend"] else _MUTED)
        _text(dr, (cx, week_bot - 2), wd, size=10, fill=fill, anchor="ms")
        d = row["date"]
        hits.append(
            {
                "x0": int(cx - col_w / 2),
                "x1": int(cx + col_w / 2),
                "y0": week_top,
                "y1": week_bot,
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
