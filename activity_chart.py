"""工时账本里的键鼠图。

键盘、鼠标、滚轮按次数画在一起。鼠标滑行距离单位不同，单独按自己的高低来画，不跟次数挤在一根轴上。
今天按小时，这周按天。不和账本左边的「待了多久」混在一起。
"""
from __future__ import annotations

import math
import os
from datetime import date
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageTk

import activity

W, H = 492, 236
GAP = 12
IDLE_READOUT = ""
WEEK_IDLE = ""
_WD = "一二三四五六日"
READOUT = (16, 258, 568, 280)
_FONT: dict[tuple, ImageFont.ImageFont] = {}

_PAGE = (22, 26, 34, 255)
_PANEL = (26, 32, 44, 255)
_CLICK = (240, 176, 88, 255)
_CLICK_PEAK = (255, 214, 140, 255)
_KEY = (110, 186, 232, 255)
_WHEEL = (125, 206, 160, 255)
_TRAVEL = (198, 160, 255, 255)
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
        "travel": c["travel"],
        "travel_h": c["travel_h"],
        "peak": activity.peak_hours(c["hours"]),
    }


def week_pack(cfg: dict, days: list[date], today: date) -> list[dict]:
    out = []
    for d in days:
        c = activity.counts(cfg, d)
        mode, _, _, _ = hourly_series(c)
        out.append(
            {
                "date": d,
                "mode": mode,
                "keys": c["keys"],
                "clicks": c["clicks"],
                "wheels": c["wheels"],
                "travel": c["travel"],
                "combined": sum(c["hours"]) if mode == "combined" else 0,
                "today": d == today,
                "weekend": d.weekday() >= 5,
                "future": d > today,
            }
        )
    return out


def week_totals(days: list[dict]) -> tuple[int, int, int]:
    """这周三项合计。只加已经分开记的天，旧的「只记了总数」不混进来。"""
    keys = clicks = wheels = 0
    for row in days:
        if row.get("future") or row.get("mode") == "combined":
            continue
        keys += int(row.get("keys") or 0)
        clicks += int(row.get("clicks") or 0)
        wheels += int(row.get("wheels") or 0)
    return keys, clicks, wheels


def signature(today: dict, days: list[dict], *, enabled: bool, this_week: bool, view: str = "today", style: str = "line") -> tuple:
    return (
        enabled,
        this_week,
        view,
        style,
        today["mode"],
        today["keys"],
        today["clicks"],
        today["wheels"],
        today.get("travel", 0),
        tuple(today["keys_h"]),
        tuple(today["clicks_h"]),
        tuple(today["wheels_h"]),
        tuple(today.get("travel_h") or ()),
        tuple(today["hours"]),
        tuple(
            (row["keys"], row["clicks"], row["wheels"], row.get("travel", 0), row.get("combined", 0), row["today"], row.get("mode"))
            for row in days
        ),
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


def _with_travel(text: str, counts: int) -> str:
    if activity.travel_meters(counts) < 0.001:
        return text
    bit = "鼠标" + activity.fmt_travel(counts)
    return f"{text}    {bit}" if text else bit


def _hour_text(hour: int, today: dict) -> str:
    if today["mode"] == "combined":
        text = f"{hour}点    操作 {activity.fmt_count(today['hours'][hour])}"
    else:
        text = (
            f"{hour}点    键盘 {activity.fmt_count(today['keys_h'][hour])}"
            f"    鼠标 {activity.fmt_count(today['clicks_h'][hour])}"
            f"    滚轮 {activity.fmt_count(today['wheels_h'][hour])}"
        )
    return _with_travel(text, (today.get("travel_h") or [0] * 24)[hour])


def _totals(keys: int, clicks: int, wheels: int, travel: int) -> tuple:
    items = [
        ("键盘", activity.fmt_count(keys), _KEY),
        ("鼠标", activity.fmt_count(clicks), _CLICK),
        ("滚轮", activity.fmt_count(wheels), _WHEEL),
    ]
    if activity.travel_meters(int(travel or 0)) >= 0.001:
        items.append(("距离", activity.fmt_travel(int(travel)), _TRAVEL))
    return tuple(items)


def _paint_totals(dr: ImageDraw.ImageDraw, w: int, items: tuple) -> None:
    inset = 14
    col_w = (w - inset * 2) / max(1, len(items))
    size = 20 if len(items) <= 3 else 16
    for i, (name, text, color) in enumerate(items):
        cx = inset + (i + 0.5) * col_w
        if i:
            x = int(inset + i * col_w)
            dr.line((x, 12, x, 46), fill=_GRID, width=1)
        _text(dr, (cx, 8), name, size=11, fill=color, anchor="mt")
        _text(dr, (cx, 44), text, size=size, fill=_WHITE, anchor="ms", bold=True)


def _paint_readout(im: Image.Image, text: str, *, active: bool = False) -> None:
    if not text:
        return
    w, h = im.size
    x0, y0, x1, y1 = 12, h - 30, w - 12, h - 8
    dr = ImageDraw.Draw(im)
    dr.rectangle((x0, y0, x1, y1), fill=_PANEL)
    _round(dr, (x0, y0, x1, y1), (36, 44, 58, 255), radius=8)
    _text(dr, ((x0 + x1) / 2, (y0 + y1) / 2), text, size=12, fill=_WHITE if active else _MUTED, anchor="mm")


def _day_text(row: dict) -> str:
    d = row["date"]
    head = f"周{_WD[d.weekday()]} {d.month}/{d.day}"
    if row.get("future"):
        return f"{head}    还没到"
    if row.get("mode") == "combined":
        text = f"{head}    {activity.fmt_count(row.get('combined') or 0)}"
    elif row.get("mode") == "empty":
        text = f"{head}    还没记下"
    else:
        text = (
            f"{head}    键盘 {activity.fmt_count(row['keys'])}"
            f"    鼠标 {activity.fmt_count(row['clicks'])}"
            f"    滚轮 {activity.fmt_count(row['wheels'])}"
        )
    return _with_travel(text, int(row.get("travel") or 0))


def _busiest_caption(days: list[dict]) -> str:
    best = None
    best_n = 0
    for row in days:
        if row.get("future"):
            continue
        if row.get("mode") == "combined":
            n = int(row.get("combined") or 0)
        elif row.get("mode") == "empty":
            n = 0
        else:
            n = int(row["keys"]) + int(row["clicks"]) + int(row["wheels"])
        if n > best_n:
            best_n = n
            best = row
    if best is None:
        return "这周还没记到次数"
    d = best["date"]
    return f"最勤 周{_WD[d.weekday()]}"


def _stroke(dr: ImageDraw.ImageDraw, pts: list[tuple[float, float]], color) -> None:
    if not pts:
        return
    if len(pts) == 1:
        x, y = pts[0]
        dr.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)
        return
    dr.line([(int(x), int(y)) for x, y in pts], fill=color, width=2)
    for x, y in pts:
        dr.ellipse((x - 2, y - 2, x + 2, y + 2), fill=color)


def _plot_lines(dr: ImageDraw.ImageDraw, xs: list[float], series: list[tuple[list[int], tuple]], top: int, base: int) -> int:
    """几条线共用一根纵轴。全是 0 的不画。返回纵轴上限，方便标数字。"""
    live = [(vals, color) for vals, color in series if any(vals)]
    if not xs or not live:
        return 0
    vmax = max(max(vals) for vals, _ in live)
    if vmax <= 0:
        return 0
    span = max(1, base - top)
    for vals, color in live:
        pts = [(x, base - (v / vmax) * span) for x, v in zip(xs, vals)]
        _stroke(dr, pts, color)
    return vmax


def _plot_own(dr: ImageDraw.ImageDraw, xs: list[float], vals: list[int], color, top: int, base: int) -> int:
    """单独一根纵轴。距离和次数不是同一个单位，跟次数挤在一起会把次数压成一条底线。"""
    if not xs or not any(vals):
        return 0
    vmax = max(vals)
    if vmax <= 0:
        return 0
    span = max(1, base - top)
    pts = [(x, base - (v / vmax) * span) for x, v in zip(xs, vals)]
    _stroke(dr, pts, color)
    return vmax


def _legend(dr: ImageDraw.ImageDraw, x: int, y: int, items: tuple) -> None:
    cx = x
    for name, color in items:
        dr.line((cx, y, cx + 14, y), fill=color, width=2)
        _text(dr, (cx + 18, y), name, size=11, fill=color, anchor="lm")
        cx += 18 + int(dr.textlength(name, font=_font(11))) + 14


def _render_week(
    days: list[dict],
    *,
    enabled: bool,
    w: int,
    h: int,
    style: str = "line",
) -> tuple[Image.Image, list[dict]]:
    im = Image.new("RGBA", (w, h), _PAGE)
    dr = ImageDraw.Draw(im)
    _round(dr, (0, 0, w - 1, h - 1), _PANEL, radius=12)
    hits: list[dict] = []
    if not enabled:
        _text(dr, (w / 2, h / 2), "还没开始记", size=13, fill=_WHITE, anchor="mm")
        return im, hits

    inset = 14
    keys, clicks, wheels = week_totals(days)
    travel = sum(int(r.get("travel") or 0) for r in days if not r.get("future"))
    _paint_totals(dr, w, _totals(keys, clicks, wheels, travel))
    _text(dr, (inset, 54), _busiest_caption(days), size=11, fill=_MUTED, anchor="lm")

    plot_l, plot_r = 16, w - inset
    plot_top, base = 68, h - 52
    bar_room = base - plot_top
    group_w = (plot_r - plot_l) / max(1, len(days))
    dr.line((plot_l + 8, base, plot_r - 8, base), fill=_LINE, width=1)
    values = []
    for row in days:
        if row.get("future") or row.get("mode") == "empty":
            continue
        if row.get("mode") == "combined":
            values.append(int(row.get("combined") or 0))
        else:
            values.extend((int(row["keys"]), int(row["clicks"]), int(row["wheels"])))
    vmax = max(values or [0])
    travel_max = max((int(r.get("travel") or 0) for r in days if not r.get("future")), default=0)
    for i, row in enumerate(days):
        gx0 = plot_l + i * group_w
        gx1 = gx0 + group_w
        if style != "line" and not row.get("future") and row.get("mode") != "empty" and (vmax > 0 or travel_max > 0):
            if row.get("mode") == "combined":
                series = [(int(row.get("combined") or 0), _COMBINED, vmax)]
            else:
                series = [
                    (int(row["keys"]), _KEY, vmax),
                    (int(row["clicks"]), _CLICK, vmax),
                    (int(row["wheels"]), _WHEEL, vmax),
                ]
            if travel_max > 0:
                series.append((int(row.get("travel") or 0), _TRAVEL, travel_max))
            bar_w = max(4, int((group_w - 18) / max(1, len(series))) - 2)
            span = len(series) * bar_w + (len(series) - 1) * 3
            left = gx0 + (group_w - span) / 2
            for j, (v, color, scale) in enumerate(series):
                if not v or scale <= 0:
                    continue
                x0 = int(left + j * (bar_w + 3))
                y0 = int(base - (v / scale) * (bar_room - 8))
                _bar(dr, (x0, y0, x0 + bar_w, base), color, radius=2)
        label_fill = _TODAY if row.get("today") else (_DIM if row.get("weekend") else _MUTED)
        d = row["date"]
        mid = (gx0 + gx1) / 2
        if row.get("today"):
            _round(dr, (mid - 12, base + 4, mid + 12, base + 24), (48, 58, 76, 255), radius=8)
        _text(dr, (mid, base + 8), _WD[d.weekday()], size=11, fill=label_fill, anchor="mt", bold=bool(row.get("today")))
        hits.append(
            {
                "x0": int(gx0),
                "x1": int(gx1),
                "y0": plot_top - 6,
                "y1": base + 26,
                "text": _day_text(row),
                "date": row["date"].isoformat(),
            }
        )
    if style == "line":
        xs: list[float] = []
        ks: list[int] = []
        cs: list[int] = []
        ws: list[int] = []
        combos: list[int] = []
        for i, row in enumerate(days):
            if row.get("future"):
                continue
            gx0 = plot_l + i * group_w
            xs.append(gx0 + group_w / 2)
            if row.get("mode") == "combined":
                ks.append(0)
                cs.append(0)
                ws.append(0)
                combos.append(int(row.get("combined") or 0))
            elif row.get("mode") == "empty":
                ks.append(0)
                cs.append(0)
                ws.append(0)
                combos.append(0)
            else:
                ks.append(int(row["keys"]))
                cs.append(int(row["clicks"]))
                ws.append(int(row["wheels"]))
                combos.append(0)
        ts: list[int] = []
        for row in days:
            if row.get("future"):
                continue
            ts.append(int(row.get("travel") or 0))
        top = plot_top + 4
        ymax = _plot_lines(
            dr, xs,
            [(ks, _KEY), (cs, _CLICK), (ws, _WHEEL), (combos, _COMBINED)],
            top, base - 2,
        )
        if ymax:
            _text(dr, (plot_l + 8, top), activity.fmt_count(ymax), size=10, fill=_DIM, anchor="lt")
        tscale = _plot_own(dr, xs, ts, _TRAVEL, top, base - 2)
        if tscale:
            _text(dr, (plot_r - 8, top), activity.fmt_travel(tscale), size=10, fill=_TRAVEL, anchor="rt")
    _paint_readout(im, WEEK_IDLE)
    return im, hits


def render(
    today: dict,
    days: list[dict],
    *,
    enabled: bool,
    this_week: bool,
    view: str = "today",
    style: str = "line",
    w: int = W,
    h: int = H,
) -> tuple[Image.Image, list[dict]]:
    if view == "week":
        return _render_week(days, enabled=enabled, w=w, h=h, style=style)
    im = Image.new("RGBA", (w, h), _PAGE)
    dr = ImageDraw.Draw(im)
    _round(dr, (0, 0, w - 1, h - 1), _PANEL, radius=12)
    hits: list[dict] = []
    if not enabled:
        _text(dr, (w / 2, h / 2), "还没开始记", size=13, fill=_WHITE, anchor="mm")
        return im, hits

    inset = 14
    plot_l, plot_r = 36, w - inset
    _paint_totals(dr, w, _totals(today["keys"], today["clicks"], today["wheels"], int(today.get("travel") or 0)))

    cap = "这天还没记到次数" if today["mode"] == "empty" else _peak_caption(today)
    _text(dr, (inset, 54), cap, size=11, fill=_MUTED, anchor="lm")

    travel_h = list(today.get("travel_h") or [0] * 24)
    lo, hi = visible_span(today["hours"], today["keys_h"], today["clicks_h"], today["wheels_h"], travel_h)
    n = hi - lo + 1
    slot = (plot_r - plot_l) / n

    def x_center(hour: int) -> float:
        return plot_l + (hour - lo + 0.5) * slot

    if today["mode"] == "combined":
        count_rows = (("操作", today["hours"], _COMBINED),)
    else:
        count_rows = (
            ("键盘", today["keys_h"], _KEY),
            ("鼠标", today["clicks_h"], _CLICK),
            ("滚轮", today["wheels_h"], _WHEEL),
        )
    rows = count_rows + ((("距离", travel_h, _TRAVEL),) if any(travel_h) else ())
    if style == "line":
        rows_top = 86
        _legend(dr, inset, 72, tuple((name, color) for name, _series, color in count_rows) + (("距离", _TRAVEL),))
        base = h - 46
        dr.line((plot_l, base, plot_r, base), fill=_LINE, width=1)
        xs = [x_center(hour) for hour in range(lo, hi + 1)]
        series = [([row[hour] for hour in range(lo, hi + 1)], color) for _name, row, color in count_rows]
        ymax = _plot_lines(dr, xs, series, rows_top, base)
        if ymax:
            _text(dr, (4, rows_top), activity.fmt_count(ymax), size=10, fill=_DIM, anchor="lt")
        tscale = _plot_own(dr, xs, [travel_h[hour] for hour in range(lo, hi + 1)], _TRAVEL, rows_top, base)
        if tscale:
            _text(dr, (plot_r, rows_top), activity.fmt_travel(tscale), size=10, fill=_TRAVEL, anchor="rt")
        axis_y = base + 4
    else:
        plot_l = 46
        slot = (plot_r - plot_l) / n

        def x_center_bar(hour: int) -> float:
            return plot_l + (hour - lo + 0.5) * slot

        bar_w = max(6, int(slot * 0.46))
        rows_top = 68
        room = max(24, (h - 30 - 14 - rows_top) // max(1, len(rows)))
        bar_room = max(16, room - 8)
        for i, (name, series_row, color) in enumerate(rows):
            top = rows_top + i * room
            base = top + bar_room
            vmax = max(series_row[lo : hi + 1] or [0])
            _text(dr, (inset, (top + base) / 2), name, size=11, fill=color, anchor="lm")
            dr.line((plot_l, base, plot_r, base), fill=_LINE, width=1)
            if vmax <= 0:
                continue
            for hour in range(lo, hi + 1):
                v = series_row[hour]
                if not v:
                    continue
                cx = x_center_bar(hour)
                x0 = int(cx - bar_w / 2)
                y0 = int(base - (v / vmax) * bar_room)
                _bar(dr, (x0, y0, x0 + bar_w, base), color, radius=2)
        x_center = x_center_bar
        axis_y = rows_top + len(rows) * room + 2
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


def paint_into(
    ui: dict,
    cfg: dict,
    *,
    today: date,
    days: list[date],
    enabled: bool,
    this_week: bool,
    focus: date | None = None,
    style: str = "line",
) -> None:
    """左边看 focus 这一天，右边看这一周。尺寸相同。数据没变就跳过。"""
    pack = today_pack(cfg, focus or today)
    week = week_pack(cfg, days, today)
    sig = signature(pack, week, enabled=enabled, this_week=this_week, view="both", style=style)
    if ui.get("chart_sig") == sig and ui.get("today_base") is not None and ui.get("week_base") is not None:
        return
    today_im, today_hits = render(pack, week, enabled=enabled, this_week=this_week, view="today", style=style)
    week_im, week_hits = render(pack, week, enabled=enabled, this_week=this_week, view="week", style=style)
    ui["today_base"] = today_im
    ui["today_hits"] = today_hits
    ui["week_base"] = week_im
    ui["week_hits"] = week_hits
    ui["chart_sig"] = sig
    for panel in ("today", "week"):
        ui[f"{panel}_hover"] = None
        apply_hover(ui, panel, *remembered_hover(ui, panel))


def remembered_hover(ui: dict, panel: str) -> tuple[int, int]:
    """鼠标还停在图上时，重画不能把底部数字收掉。"""
    ptr = ui.get(f"{panel}_ptr")
    if isinstance(ptr, tuple) and len(ptr) == 2:
        return int(ptr[0]), int(ptr[1])
    return -1, -1


def apply_hover(ui: dict, panel: str, x: int, y: int) -> None:
    base = ui.get(f"{panel}_base")
    if base is None:
        return
    idle = WEEK_IDLE if panel == "week" else IDLE_READOUT
    text = hover_text(ui.get(f"{panel}_hits") or [], x, y) or idle
    if text == ui.get(f"{panel}_hover") and ui.get(f"{panel}_photo") is not None:
        return
    im = base.copy()
    _paint_readout(im, text, active=text != idle)
    photo = ImageTk.PhotoImage(im)
    lbl = ui.get(f"{panel}_lbl")
    if lbl is not None:
        lbl.configure(image=photo)
    ui[f"{panel}_photo"] = photo
    ui[f"{panel}_hover"] = text


def hit_at(hits: list[dict], x: int, y: int) -> dict | None:
    for hit in reversed(hits):
        if hit["x0"] <= x < hit["x1"] and hit["y0"] <= y <= hit["y1"]:
            return hit
    return None


def hover_text(hits: list[dict], x: int, y: int) -> str:
    hit = hit_at(hits, x, y)
    return str(hit["text"]) if hit else ""
