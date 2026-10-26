"""工时账本里的键鼠图。

键盘、鼠标、滚轮按次数画在一起。鼠标滑行距离单位不同，单独按自己的高低来画，不跟次数挤在一根轴上。
今天按小时，这周按天。不和账本左边的「待了多久」混在一起。
"""
from __future__ import annotations

import math
import os
from datetime import date, datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont, ImageTk

import activity

W, H = 492, 258
GAP = 12
_SS = 3
_BOX = getattr(Image, "Resampling", Image).BOX
_CAP_Y = 58
_TOP = 76
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


def _speed_line_from(src: dict, hour: int | None = None) -> str:
    def take(key: str) -> int:
        vals = src.get(key) or [0] * 24
        if hour is None:
            return sum(int(v) for v in vals)
        if hour < 0 or hour >= len(vals):
            return 0
        return int(vals[hour])

    return activity.fmt_speed_line(
        take("keys_h"), take("keys_ms"),
        take("travel_h"), take("travel_ms"),
        take("wheels_h"), take("wheels_ms"),
    )


def today_pack(cfg: dict, d: date, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    c = activity.counts(cfg, d)
    pace = activity.pace_of(cfg, d, now)
    mode, keys_h, clicks_h, wheels_h = hourly_series(c)
    live = activity.speed_snapshot(cfg, now) if now.date() == d else {"key": (0, 0), "move": (0, 0), "wheel": (0, 0)}
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
        "keys_pace": pace["keys_pace"],
        "wheels_pace": pace["wheels_pace"],
        "travel_pace": pace["travel_pace"],
        "keys_ms": pace["keys_ms"],
        "wheels_ms": pace["wheels_ms"],
        "travel_ms": pace["travel_ms"],
        "inst_live": live,
        "now_sec": now.hour * 3600 + now.minute * 60 + now.second if now.date() == d else None,
        **activity.inst_rows(cfg, d, now),
    }


def week_pack(cfg: dict, days: list[date], today: date, now: datetime | None = None) -> list[dict]:
    out = []
    for d in days:
        c = activity.counts(cfg, d)
        pace = activity.pace_of(cfg, d, now)
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
                "keys_pace": sum(pace["keys_pace"]),
                "keys_ms": sum(pace["keys_ms"]),
                "wheels_pace": sum(pace["wheels_pace"]),
                "wheels_ms": sum(pace["wheels_ms"]),
                "travel_pace": sum(pace["travel_pace"]),
                "travel_ms": sum(pace["travel_ms"]),
                **activity.inst_rows(cfg, d, now),
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


def _inst_sig(src: dict) -> tuple:
    bits = []
    for key in ("inst_key", "inst_wheel", "inst_move"):
        rows = src.get(key) or []
        if not rows:
            bits.append((0,))
            continue
        last = rows[-1]
        bits.append((len(rows), int(last[0]), int(last[1]), int(last[2])))
    return tuple(bits)


def signature(
    today: dict,
    days: list[dict],
    *,
    enabled: bool,
    this_week: bool,
    view: str = "today",
    style: str = "line",
    mode: str = "counts",
) -> tuple:
    return (
        enabled,
        this_week,
        view,
        style,
        mode,
        _inst_sig(today),
        tuple(_inst_sig(row) for row in days),
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
        tuple(today.get("keys_pace") or ()),
        tuple(today.get("keys_ms") or ()),
        tuple(today.get("wheels_pace") or ()),
        tuple(today.get("wheels_ms") or ()),
        tuple(today.get("travel_pace") or ()),
        tuple(today.get("travel_ms") or ()),
        tuple(today.get("inst_live", {}).get(k) or (0, 0) for k in ("key", "move", "wheel")),
        tuple(
            (
                row["keys"], row["clicks"], row["wheels"], row.get("travel", 0), row.get("combined", 0),
                row.get("keys_pace", 0), row.get("keys_ms", 0),
                row.get("wheels_pace", 0), row.get("wheels_ms", 0),
                row.get("travel_pace", 0), row.get("travel_ms", 0),
                row["today"], row.get("mode"),
            )
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


def _paint_readout(im: Image.Image, text: str, speed: str = "", *, active: bool = False) -> None:
    if not text and not speed:
        return
    w, h = im.size
    x0, y0, x1, y1 = 12, h - 46, w - 12, h - 6
    dr = ImageDraw.Draw(im)
    dr.rectangle((x0, y0, x1, y1), fill=_PANEL)
    _round(dr, (x0, y0, x1, y1), (36, 44, 58, 255), radius=8)
    fill = _WHITE if active else _MUTED
    mid = (x0 + x1) / 2
    if text and speed:
        _text(dr, (mid, y0 + 11), text, size=12, fill=fill, anchor="mm")
        _text(dr, (mid, y0 + 29), speed, size=11, fill=fill, anchor="mm")
    else:
        _text(dr, (mid, (y0 + y1) / 2), text or speed, size=12, fill=fill, anchor="mm")


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


class _Ink:
    """曲线和面积画在 3 倍大的透明层上再缩回来，斜线边缘才不发毛。"""

    def __init__(self, size: tuple[int, int]):
        self.size = size
        self.im = Image.new("RGBA", (size[0] * _SS, size[1] * _SS), (0, 0, 0, 0))
        self.dr = ImageDraw.Draw(self.im)

    @staticmethod
    def _up(pts):
        return [(x * _SS, y * _SS) for x, y in pts]

    def area(self, pts: list[tuple[float, float]], top: float, base: float, color, alpha: int = 60) -> None:
        """渐隐从图顶算到底线，同一条线断成几段时，各段深浅才对得上。"""
        if len(pts) < 2:
            return
        x0 = int(min(x for x, _y in pts) * _SS)
        x1 = int(math.ceil(max(x for x, _y in pts) * _SS)) + 1
        y0 = int(top * _SS)
        y1 = int(math.ceil(base * _SS)) + 1
        bw, bh = x1 - x0, y1 - y0
        if bw < 2 or bh < 2:
            return
        mask = Image.new("L", (bw, bh), 0)
        poly = [(x - x0, y - y0) for x, y in self._up([(pts[0][0], base), *pts, (pts[-1][0], base)])]
        ImageDraw.Draw(mask).polygon(poly, fill=255)
        fade = Image.linear_gradient("L").resize((bw, bh)).point(lambda v: (255 - v) * alpha // 255)
        layer = Image.new("RGBA", (bw, bh), tuple(color[:3]) + (0,))
        layer.putalpha(ImageChops.multiply(mask, fade))
        self.im.alpha_composite(layer, (x0, y0))

    def line(self, pts: list[tuple[float, float]], color, width: float = 2.0) -> None:
        if len(pts) < 2:
            return
        w = max(1, round(width * _SS))
        r = w / 2
        up = self._up(pts)
        self.dr.line(up, fill=color, width=w, joint="curve")
        for x, y in (up[0], up[-1]):
            self.dr.ellipse((x - r, y - r, x + r, y + r), fill=color)

    def dot(self, x: float, y: float, color, r: float = 3.0) -> None:
        cx, cy = x * _SS, y * _SS
        for rr, fill in ((r + 1.5, _PANEL), (r, color)):
            rr *= _SS
            self.dr.ellipse((cx - rr, cy - rr, cx + rr, cy + rr), fill=fill)

    def onto(self, im: Image.Image) -> None:
        im.alpha_composite(self.im.convert("RGBa").resize(self.size, _BOX).convert("RGBA"))


def _disc(im: Image.Image, x: float, y: float, r: float, color) -> None:
    d = int(math.ceil(r * 2)) + 2
    big = Image.new("RGBA", (d * _SS, d * _SS), (0, 0, 0, 0))
    lo, hi = (d / 2 - r) * _SS, (d / 2 + r) * _SS
    ImageDraw.Draw(big).ellipse((lo, lo, hi, hi), fill=color)
    small = big.convert("RGBa").resize((d, d), _BOX).convert("RGBA")
    im.alpha_composite(small, (int(round(x - d / 2)), int(round(y - d / 2))))


def _smooth(pts: list[tuple[float, float]], steps: int = 8) -> list[tuple[float, float]]:
    """单调三次插值：曲线过每个点，两点之间不会冲得比两端更高或更低。"""
    n = len(pts)
    if n < 3:
        return list(pts)
    xs = [p[0] for p in pts]
    ys = [p[1] for p in pts]
    d = [(ys[i + 1] - ys[i]) / max(1e-9, xs[i + 1] - xs[i]) for i in range(n - 1)]
    m = [d[0]] + [0.0 if d[i - 1] * d[i] <= 0 else (d[i - 1] + d[i]) / 2 for i in range(1, n - 1)] + [d[-1]]
    for i in range(n - 1):
        if d[i] == 0:
            m[i] = m[i + 1] = 0.0
            continue
        a, b = m[i] / d[i], m[i + 1] / d[i]
        s = a * a + b * b
        if s > 9:
            t = 3 / math.sqrt(s)
            m[i], m[i + 1] = t * a * d[i], t * b * d[i]
    out = []
    for i in range(n - 1):
        hx = xs[i + 1] - xs[i]
        for k in range(steps):
            t = k / steps
            t2, t3 = t * t, t * t * t
            y = (
                (2 * t3 - 3 * t2 + 1) * ys[i] + (t3 - 2 * t2 + t) * hx * m[i]
                + (-2 * t3 + 3 * t2) * ys[i + 1] + (t3 - t2) * hx * m[i + 1]
            )
            out.append((xs[i] + t * hx, y))
    out.append(pts[-1])
    return out


def _runs(xs: list[float], vals: list[int], *, skip_zero: bool) -> list[list[tuple[float, float]]]:
    """速度为 0 是那一段没数据，不是慢，所以断开；次数为 0 就是 0，照常连着。"""
    runs: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []
    for x, v in zip(xs, vals):
        if skip_zero and not v:
            if cur:
                runs.append(cur)
                cur = []
            continue
        cur.append((x, v))
    if cur:
        runs.append(cur)
    return runs


def _inst_runs(pts: list[tuple[int, int]], x_of, gap: int) -> list[list[tuple[float, float]]]:
    """瞬时点按 2 像素一格取平均，再和相邻一格揉一下。

    停得比 gap 秒久、并且在图上隔开超过 8 像素才断开；一周的图一像素就是几十分钟，不能按 5 分钟断。
    """
    raw: list[list[tuple[float, int]]] = []
    prev = None
    for sec, rate in pts:
        x = x_of(sec)
        if prev is None or (sec - prev[0] > gap and x - prev[1] > 8):
            raw.append([])
        raw[-1].append((x, rate))
        prev = (sec, x)
    out = []
    for run in raw:
        cells: dict[int, list[float]] = {}
        for x, v in run:
            acc = cells.setdefault(int(x // 2), [0.0, 0.0, 0])
            acc[0] += x
            acc[1] += v
            acc[2] += 1
        keys = sorted(cells)
        xs = [cells[k][0] / cells[k][2] for k in keys]
        vs = [cells[k][1] / cells[k][2] for k in keys]
        sm = []
        for i, k in enumerate(keys):
            tot = wt = 0.0
            for j in range(max(0, i - 1), min(len(keys), i + 2)):
                dist = abs(keys[j] - k)
                if dist <= 1:
                    tot += vs[j] * (2 - dist)
                    wt += 2 - dist
            sm.append(tot / wt)
        drawn = list(zip(xs, sm))
        # 最右端用最新那一下的速度，不被前面几分钟的平均拖住。
        drawn.append((run[-1][0], run[-1][1]))
        out.append(drawn)
    return out


def _headroom(vals, *, robust: bool = False) -> float:
    """纵轴上限：最高点上面留一截。瞬时速度偶尔一个尖峰，按 95% 分位截住，尖峰贴顶。"""
    got = sorted(v for v in vals if v > 0)
    if not got:
        return 0.0
    top = float(got[-1])
    if robust and len(got) >= 12:
        top = min(top, got[int(len(got) * 0.95)] * 1.3)
    return top * 1.12


def _paint_series(im: Image.Image, items: list[tuple], top: float, base: float, *, smooth: bool = True) -> None:
    """items：(若干段 [(x, 值)], 颜色, 纵轴上限)。先铺面积，再画线，最后在每条的最高点打一个点。"""
    ink = _Ink(im.size)
    span = max(1.0, base - top)
    drawn = []
    for runs, color, vmax in items:
        if vmax <= 0:
            continue
        best = None
        paths = []
        for run in runs:
            pts = [(x, base - min(v, vmax) / vmax * span) for x, v in run]
            for (x, v), (_x, y) in zip(run, pts):
                if v > 0 and (best is None or v > best[2]):
                    best = (x, y, v)
            paths.append(_smooth(pts) if smooth else pts)
        drawn.append((paths, color, best))
    for paths, color, _best in drawn:
        for path in paths:
            ink.area(path, top, base, color, alpha=60 if smooth else 40)
    for paths, color, _best in drawn:
        for path in paths:
            if len(path) == 1:
                ink.dot(path[0][0], path[0][1], color, r=2)
            else:
                ink.line(path, color, width=2.0 if smooth else 1.6)
    for _paths, color, best in drawn:
        if best is not None:
            ink.dot(best[0], best[1], color)
    ink.onto(im)


def _dash(dr: ImageDraw.ImageDraw, x0: float, x1: float, y: float, fill=_GRID) -> None:
    x = x0
    while x < x1:
        dr.line((int(x), int(y), int(min(x + 3, x1)), int(y)), fill=fill, width=1)
        x += 7


def _grid(dr: ImageDraw.ImageDraw, l: float, r: float, top: float, base: float) -> None:
    _dash(dr, l, r, top)
    _dash(dr, l, r, (top + base) / 2)
    dr.line((int(l), int(base), int(r), int(base)), fill=_LINE, width=1)


def _y_labels(dr: ImageDraw.ImageDraw, plot_l: float, top: float, base: float, vmax: int) -> None:
    if vmax <= 0:
        return
    x = plot_l - 6
    _text(dr, (x, top), activity.fmt_count(vmax), size=10, fill=_DIM, anchor="rm")
    _text(dr, (x, (top + base) / 2), activity.fmt_count(vmax // 2), size=10, fill=_DIM, anchor="rm")
    _text(dr, (x, base), "0", size=10, fill=_DIM, anchor="rm")


def _travel_label(im: Image.Image, plot_r: float, top: float, peak: int) -> None:
    """距离用自己的纵轴，右上角注明最高那一格有多远。"""
    dr = ImageDraw.Draw(im)
    _text(dr, (plot_r, top + 3), "距离最高 " + activity.fmt_travel(int(peak)), size=10, fill=_TRAVEL, anchor="rt")


def _caption(im: Image.Image, w: int, text: str, legend: tuple = ()) -> None:
    """说明靠左，图例靠右，同一行。"""
    dr = ImageDraw.Draw(im)
    _text(dr, (14, _CAP_Y), text, size=11, fill=_MUTED, anchor="lm")
    x = w - 14
    for name, color in reversed(legend):
        tw = dr.textlength(name, font=_font(11))
        _text(dr, (x, _CAP_Y), name, size=11, fill=_MUTED, anchor="rm")
        _disc(im, x - tw - 7, _CAP_Y, 3.5, color)
        x -= tw + 7 + 4 + 12


def _paint_focus(im: Image.Image, band) -> None:
    x0, y0, x1, y1 = (int(v) for v in band)
    if x1 - x0 < 2 or y1 - y0 < 2:
        return
    layer = Image.new("RGBA", im.size, (0, 0, 0, 0))
    dr = ImageDraw.Draw(layer)
    _round(dr, (x0 + 1, y0, x1 - 1, y1), (255, 255, 255, 14), radius=4)
    mid = (x0 + x1) // 2
    y = y0
    while y < y1:
        dr.line((mid, y, mid, min(y + 3, y1)), fill=(255, 255, 255, 60), width=1)
        y += 6
    im.alpha_composite(layer)


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
    split = any(r.get("mode") == "split" and not r.get("future") for r in days)
    combined = any(r.get("mode") == "combined" and not r.get("future") for r in days)
    legend = ((("键盘", _KEY), ("鼠标", _CLICK), ("滚轮", _WHEEL)) if split or not combined else ()) + (
        (("操作", _COMBINED),) if combined else ()
    ) + ((("距离", _TRAVEL),) if activity.travel_meters(travel) >= 0.001 else ())
    _caption(im, w, _busiest_caption(days), legend)

    plot_l, plot_r = 40, w - inset
    plot_top, base = _TOP, h - 74
    bar_room = base - plot_top
    group_w = (plot_r - plot_l) / max(1, len(days))
    _grid(dr, plot_l, plot_r, plot_top, base)
    values = []
    for row in days:
        if row.get("future") or row.get("mode") == "empty":
            continue
        if row.get("mode") == "combined":
            values.append(int(row.get("combined") or 0))
        else:
            values.extend((int(row["keys"]), int(row["clicks"]), int(row["wheels"])))
    peak = max(values or [0])
    vmax = nice_max(peak) if peak else 0
    _y_labels(dr, plot_l, plot_top, base, vmax)
    travel_max = _headroom(int(r.get("travel") or 0) for r in days if not r.get("future"))
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
                y0 = int(base - min(1.0, v / scale) * bar_room)
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
                "band": (gx0, plot_top - 4, gx1, base),
                "text": _day_text(row),
                "speed": activity.fmt_speed_line(
                    int(row.get("keys_pace") or 0), int(row.get("keys_ms") or 0),
                    int(row.get("travel_pace") or 0), int(row.get("travel_ms") or 0),
                    int(row.get("wheels_pace") or 0), int(row.get("wheels_ms") or 0),
                ),
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
        items = [
            (_runs(xs, vals, skip_zero=False), color, vmax)
            for vals, color in ((ks, _KEY), (cs, _CLICK), (ws, _WHEEL), (combos, _COMBINED))
            if any(vals)
        ]
        if any(ts):
            items.append((_runs(xs, ts, skip_zero=False), _TRAVEL, travel_max))
        _paint_series(im, items, plot_top, base)
        if any(ts):
            _travel_label(im, plot_r, plot_top, max(ts))
    return im, hits


def _speed_head(keys: int, key_ms: int, travel: int, travel_ms: int, wheels: int, wheel_ms: int) -> tuple:
    return (
        ("打字", activity.fmt_key_rate(keys, key_ms), _KEY),
        ("鼠标", activity.fmt_move_rate(travel, travel_ms), _TRAVEL),
        ("滚轮", activity.fmt_wheel_rate(wheels, wheel_ms), _WHEEL),
    )


def _hour_rates(ns, mss, kind: str) -> list[int]:
    ns = list(ns or [0] * 24)
    mss = list(mss or [0] * 24)
    return [activity.rate_value(kind, int(n or 0), int(ms or 0)) for n, ms in zip(ns, mss)]


def _same_stretch(prev: tuple[int, int, int], sec: int, ms: int) -> bool:
    """上一个点的时长还在往上加，才是同一段。新的一段时长会重新变小。"""
    psec, _pn, pms = prev
    if sec < psec:
        return False
    expected = pms + (sec - psec) * 1000
    return ms + 1500 >= pms and ms >= expected * 0.5


def _interval_points(rows, kind: str, *, tail_sec: int | None = None) -> list[tuple[int, int]]:
    """每个采样点是这一小段的速度。一段结束就落到 0，停着的时候右端也是 0。"""
    out = []
    prev: tuple[int, int, int] | None = None
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 3:
            continue
        sec, n, ms = int(row[0]), int(row[1]), int(row[2])
        if n <= 0 or ms <= 0:
            continue
        if prev is not None and _same_stretch(prev, sec, ms):
            dn, dms = n - prev[1], ms - prev[2]
            if dn <= 0 or dms <= 0:
                dn, dms = n, ms
        else:
            if prev is not None and sec > prev[0]:
                out.append((prev[0] + 1, 0))
            dn, dms = n, ms
        rate = activity.rate_value(kind, dn, dms)
        if rate > 0:
            out.append((sec, rate))
        prev = (sec, n, ms)
    if tail_sec is not None and out and out[-1][1] > 0 and tail_sec > out[-1][0]:
        out.append((tail_sec, 0))
    return out


def _live_tail(src: dict, kind: str) -> int | None:
    """还在操作就不补 0。已经停了，就把线收到当前这一秒。"""
    live = (src.get("inst_live") or {}).get(kind) or (0, 0)
    if int(live[0] or 0) > 0 and int(live[1] or 0) > 0:
        return None
    sec = src.get("now_sec")
    return int(sec) if sec is not None else None


def _recent_pair(rows) -> tuple[int, int]:
    """最后一小段的次数和时长。只有一个点时，用这个点自己的累计。"""
    cleaned = []
    for row in rows or []:
        if isinstance(row, (list, tuple)) and len(row) >= 3:
            cleaned.append((int(row[0]), int(row[1]), int(row[2])))
    if not cleaned:
        return 0, 0
    sec, n, ms = cleaned[-1]
    if len(cleaned) >= 2 and _same_stretch(cleaned[-2], sec, ms):
        dn, dms = n - cleaned[-2][1], ms - cleaned[-2][2]
        if dn > 0 and dms > 0:
            return dn, dms
    return n, ms


def _inst_line_at(src: dict, hour: int | None) -> str:
    def take(key: str) -> tuple[int, int]:
        found = (0, 0)
        prev = None
        for row in src.get(key) or []:
            if not isinstance(row, (list, tuple)) or len(row) < 3:
                continue
            sec, n, ms = int(row[0]), int(row[1]), int(row[2])
            if hour is None or sec // 3600 == hour:
                if prev is not None and _same_stretch(prev, sec, ms):
                    dn, dms = n - prev[1], ms - prev[2]
                    found = (dn, dms) if dn > 0 and dms > 0 else (n, ms)
                else:
                    found = (n, ms)
            prev = (sec, n, ms)
        return found

    k, km = take("inst_key")
    v, vm = take("inst_move")
    w, wm = take("inst_wheel")
    return activity.fmt_speed_line(k, km, v, vm, w, wm)


def _render_speed(
    today: dict,
    days: list[dict],
    *,
    enabled: bool,
    view: str,
    style: str,
    mode: str,
    w: int,
    h: int,
) -> tuple[Image.Image, list[dict]]:
    im = Image.new("RGBA", (w, h), _PAGE)
    dr = ImageDraw.Draw(im)
    _round(dr, (0, 0, w - 1, h - 1), _PANEL, radius=12)
    hits: list[dict] = []
    if not enabled:
        _text(dr, (w / 2, h / 2), "还没开始记", size=13, fill=_WHITE, anchor="mm")
        return im, hits

    inset = 14
    plot_l, plot_r = 24, w - inset
    rows_top, base = _TOP, h - 68
    if view == "week":
        base = h - 74
        if mode == "inst":
            live = today.get("inst_live") or {}
            kn, km = live.get("key") or (0, 0)
            vn, vm = live.get("move") or (0, 0)
            wn, wm = live.get("wheel") or (0, 0)
        else:
            kn = sum(int(r.get("keys") or 0) for r in days)
            km = sum(int(r.get("keys_ms") or 0) for r in days)
            vn = sum(int(r.get("travel") or 0) for r in days)
            vm = sum(int(r.get("travel_ms") or 0) for r in days)
            wn = sum(int(r.get("wheels") or 0) for r in days)
            wm = sum(int(r.get("wheels_ms") or 0) for r in days)
        cap = "当前速度，停手就是 0" if mode == "inst" else "每天的平均速度"
    elif mode == "inst":
        live = today.get("inst_live") or {}
        kn, km = live.get("key") or (0, 0)
        vn, vm = live.get("move") or (0, 0)
        wn, wm = live.get("wheel") or (0, 0)
        cap = "当前速度，停手就是 0"
    else:
        kn, km = sum(today.get("keys_h") or []), sum(today.get("keys_ms") or [])
        vn, vm = sum(today.get("travel_h") or []), sum(today.get("travel_ms") or [])
        wn, wm = sum(today.get("wheels_h") or []), sum(today.get("wheels_ms") or [])
        cap = "各小时平均速度" if any((km, vm, wm)) else "这天还没有速度"
    if mode == "inst":
        _paint_totals(dr, w, (
            ("打字", activity.fmt_instant("key", kn, km), _KEY),
            ("鼠标", activity.fmt_instant("move", vn, vm), _TRAVEL),
            ("滚轮", activity.fmt_instant("wheel", wn, wm), _WHEEL),
        ))
    else:
        _paint_totals(dr, w, _speed_head(kn, km, vn, vm, wn, wm))
    _caption(im, w, cap, (("打字", _KEY), ("鼠标", _TRAVEL), ("滚轮", _WHEEL)))
    _grid(dr, plot_l, plot_r, rows_top, base)

    if view == "week":
        group_w = (plot_r - plot_l) / max(1, len(days))
        if mode == "avg":
            cols = (
                ("key", [activity.rate_value("key", int(r.get("keys") or 0), int(r.get("keys_ms") or 0)) for r in days], _KEY),
                ("move", [activity.rate_value("move", int(r.get("travel") or 0), int(r.get("travel_ms") or 0)) for r in days], _TRAVEL),
                ("wheel", [activity.rate_value("wheel", int(r.get("wheels") or 0), int(r.get("wheels_ms") or 0)) for r in days], _WHEEL),
            )
            xs = [plot_l + (i + 0.5) * group_w for i in range(len(days))]
            if style == "line":
                _paint_series(
                    im,
                    [(_runs(xs, vals, skip_zero=True), color, _headroom(vals)) for _n, vals, color in cols],
                    rows_top, base,
                )
            else:
                maxes = [_headroom(vals) for _n, vals, _c in cols]
                bar_w = max(4, int(group_w / 4))
                room = max(16, base - rows_top)
                for i in range(len(days)):
                    for j, ((_n, vals, color), scale) in enumerate(zip(cols, maxes)):
                        if not vals[i] or scale <= 0:
                            continue
                        cx = xs[i] + (j - 1) * (bar_w + 2)
                        y0 = int(base - vals[i] / scale * room)
                        _bar(dr, (int(cx - bar_w / 2), y0, int(cx + bar_w / 2), base), color, radius=2)
        else:
            width = max(1, len(days)) * 86400
            gathered = {"key": [], "move": [], "wheel": []}
            for i, row in enumerate(days):
                for key, kind in (("inst_key", "key"), ("inst_move", "move"), ("inst_wheel", "wheel")):
                    gathered[kind].extend(
                        (i * 86400 + sec, rate)
                        for sec, rate in _interval_points(
                            row.get(key), kind,
                            tail_sec=(i * 86400 + _live_tail(today, kind)) if row.get("today") and _live_tail(today, kind) is not None else None,
                        )
                    )

            def x_of(sec: int, _width=width) -> float:
                return plot_l + sec / _width * (plot_r - plot_l)

            _paint_series(
                im,
                [
                    (_inst_runs(gathered[kind], x_of, 300), color, _headroom((r for _s, r in gathered[kind]), robust=True))
                    for kind, color in (("key", _KEY), ("move", _TRAVEL), ("wheel", _WHEEL))
                ],
                rows_top, base, smooth=False,
            )
        for i, row in enumerate(days):
            gx0 = plot_l + i * group_w
            mid = gx0 + group_w / 2
            d = row["date"]
            label_fill = _TODAY if row.get("today") else (_DIM if row.get("weekend") else _MUTED)
            if row.get("today"):
                _round(dr, (mid - 12, base + 4, mid + 12, base + 24), (48, 58, 76, 255), radius=8)
            _text(dr, (mid, base + 8), _WD[d.weekday()], size=11, fill=label_fill, anchor="mt", bold=bool(row.get("today")))
            if mode == "inst":
                speed = _inst_line_at(row, None)
            else:
                speed = activity.fmt_speed_line(
                    int(row.get("keys_pace") or 0), int(row.get("keys_ms") or 0),
                    int(row.get("travel_pace") or 0), int(row.get("travel_ms") or 0),
                    int(row.get("wheels_pace") or 0), int(row.get("wheels_ms") or 0),
                )
            hits.append({
                "x0": int(gx0), "x1": int(gx0 + group_w), "y0": rows_top, "y1": base + 26,
                "band": (gx0, rows_top - 4, gx0 + group_w, base),
                "text": f"周{_WD[d.weekday()]} {d.month}/{d.day}",
                "speed": speed,
                "date": d.isoformat(),
            })
        return im, hits

    if mode == "avg":
        cols = (
            _hour_rates(today.get("keys_h"), today.get("keys_ms"), "key"),
            _hour_rates(today.get("travel_h"), today.get("travel_ms"), "move"),
            _hour_rates(today.get("wheels_h"), today.get("wheels_ms"), "wheel"),
        )
        colors = (_KEY, _TRAVEL, _WHEEL)
        lo, hi = visible_span(*cols)
        n = hi - lo + 1
        slot = (plot_r - plot_l) / n

        def x_center(hour: int) -> float:
            return plot_l + (hour - lo + 0.5) * slot

        xs = [x_center(hour) for hour in range(lo, hi + 1)]
        window = [vals[lo:hi + 1] for vals in cols]
        if style == "line":
            _paint_series(
                im,
                [(_runs(xs, vals, skip_zero=True), color, _headroom(vals)) for vals, color in zip(window, colors)],
                rows_top, base,
            )
        else:
            maxes = [_headroom(vals) for vals in window]
            bar_w = max(3, int(slot / 4))
            room = max(16, base - rows_top)
            for i, hour in enumerate(range(lo, hi + 1)):
                for j, (vals, color, scale) in enumerate(zip(window, colors, maxes)):
                    if not vals[i] or scale <= 0:
                        continue
                    cx = xs[i] + (j - 1) * (bar_w + 2)
                    y0 = int(base - vals[i] / scale * room)
                    _bar(dr, (int(cx - bar_w / 2), y0, int(cx + bar_w / 2), base), color, radius=2)
        for hour in range(lo, hi + 1):
            cx = x_center(hour)
            if hour % 2 == 0:
                _text(dr, (cx, base + 5), str(hour), size=10, fill=_DIM, anchor="mt")
            hits.append({
                "x0": int(cx - slot / 2), "x1": int(cx + slot / 2),
                "y0": rows_top, "y1": base + 16,
                "band": (cx - slot / 2, rows_top - 4, cx + slot / 2, base),
                "text": f"{hour}点",
                "speed": _speed_line_from(today, hour),
            })
        return im, hits

    pieces = (
        (_interval_points(today.get("inst_key"), "key", tail_sec=_live_tail(today, "key")), _KEY),
        (_interval_points(today.get("inst_move"), "move", tail_sec=_live_tail(today, "move")), _TRAVEL),
        (_interval_points(today.get("inst_wheel"), "wheel", tail_sec=_live_tail(today, "wheel")), _WHEEL),
    )
    marks = [0] * 24
    for pts, _color in pieces:
        for sec, _rate in pts:
            hour = sec // 3600
            if 0 <= hour < 24:
                marks[hour] = 1
    lo, hi = visible_span(marks)
    span_h = max(1, hi - lo + 1)

    def x_of(sec: int) -> float:
        return plot_l + (sec / 3600 - lo) / span_h * (plot_r - plot_l)

    _paint_series(
        im,
        [
            (_inst_runs(pts, x_of, 300), color, _headroom((r for _s, r in pts), robust=True))
            for pts, color in pieces
        ],
        rows_top, base, smooth=False,
    )
    slot = (plot_r - plot_l) / span_h
    for hour in range(lo, hi + 1):
        cx = plot_l + (hour - lo + 0.5) * slot
        if hour % 2 == 0:
            _text(dr, (x_of(hour * 3600), base + 5), str(hour), size=10, fill=_DIM, anchor="mt")
        hits.append({
            "x0": int(cx - slot / 2), "x1": int(cx + slot / 2),
            "y0": rows_top, "y1": base + 16,
            "band": (cx - slot / 2, rows_top - 4, cx + slot / 2, base),
            "text": f"{hour}点",
            "speed": _inst_line_at(today, hour),
        })
    return im, hits


def render(
    today: dict,
    days: list[dict],
    *,
    enabled: bool,
    this_week: bool,
    view: str = "today",
    style: str = "line",
    mode: str = "counts",
    w: int = W,
    h: int = H,
) -> tuple[Image.Image, list[dict]]:
    if mode in ("avg", "inst"):
        return _render_speed(
            today, days, enabled=enabled, view=view, style=style, mode=mode, w=w, h=h,
        )
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
    plot_l, plot_r = 40, w - inset
    _paint_totals(dr, w, _totals(today["keys"], today["clicks"], today["wheels"], int(today.get("travel") or 0)))

    cap = "这天还没记到次数" if today["mode"] == "empty" else _peak_caption(today)

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
        rows_top = _TOP
        _caption(im, w, cap, tuple((name, color) for name, _series, color in rows))
        base = h - 68
        _grid(dr, plot_l, plot_r, rows_top, base)
        xs = [x_center(hour) for hour in range(lo, hi + 1)]
        series = [([row[hour] for hour in range(lo, hi + 1)], color) for _name, row, color in count_rows]
        peak = max((max(vals) for vals, _c in series), default=0)
        ymax = nice_max(peak) if peak else 0
        _y_labels(dr, plot_l, rows_top, base, ymax)
        items = [(_runs(xs, vals, skip_zero=False), color, ymax) for vals, color in series if any(vals)]
        tvals = [travel_h[hour] for hour in range(lo, hi + 1)]
        if any(tvals):
            items.append((_runs(xs, tvals, skip_zero=False), _TRAVEL, _headroom(tvals)))
        _paint_series(im, items, rows_top, base)
        if any(tvals):
            _travel_label(im, plot_r, rows_top, max(tvals))
        axis_y = base + 5
    else:
        _caption(im, w, cap)
        plot_l = 46
        slot = (plot_r - plot_l) / n

        def x_center_bar(hour: int) -> float:
            return plot_l + (hour - lo + 0.5) * slot

        bar_w = max(6, int(slot * 0.46))
        rows_top = 68
        room = max(24, (h - 50 - 14 - rows_top) // max(1, len(rows)))
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
        if hour % 2 == 0:
            _text(dr, (x_center(hour), axis_y), str(hour), size=10, fill=_DIM, anchor="mt")
    for hour in range(lo, hi + 1):
        cx = x_center(hour)
        hits.append(
            {
                "x0": int(cx - slot / 2),
                "x1": int(cx + slot / 2),
                "y0": rows_top,
                "y1": axis_y + 12,
                "band": (cx - slot / 2, rows_top - 4, cx + slot / 2, axis_y - 5),
                "text": _hour_text(hour, today),
                "speed": _speed_line_from(today, hour),
            }
        )

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
    mode: str = "counts",
) -> None:
    """左边看 focus 这一天，右边看这一周。尺寸相同。数据没变就跳过。"""
    now = datetime.now()
    pack = today_pack(cfg, focus or today, now)
    week = week_pack(cfg, days, today, now)
    if mode == "inst":
        live = pack.get("inst_live") or {}
        line = "    ".join((
            "打字 " + activity.fmt_instant("key", *(live.get("key") or (0, 0))),
            "鼠标 " + activity.fmt_instant("move", *(live.get("move") or (0, 0))),
            "滚轮 " + activity.fmt_instant("wheel", *(live.get("wheel") or (0, 0))),
        ))
        ui["today_idle_speed"] = line
        ui["week_idle_speed"] = line
    else:
        ui["today_idle_speed"] = _speed_line_from(pack)
        ui["week_idle_speed"] = activity.fmt_speed_line(
            sum(int(r.get("keys") or 0) for r in week),
            sum(int(r.get("keys_ms") or 0) for r in week),
            sum(int(r.get("travel") or 0) for r in week),
            sum(int(r.get("travel_ms") or 0) for r in week),
            sum(int(r.get("wheels") or 0) for r in week),
            sum(int(r.get("wheels_ms") or 0) for r in week),
        )
    sig = signature(pack, week, enabled=enabled, this_week=this_week, view="both", style=style, mode=mode)
    if ui.get("chart_sig") == sig and ui.get("today_base") is not None and ui.get("week_base") is not None:
        return
    today_im, today_hits = render(
        pack, week, enabled=enabled, this_week=this_week, view="today", style=style, mode=mode,
    )
    week_im, week_hits = render(
        pack, week, enabled=enabled, this_week=this_week, view="week", style=style, mode=mode,
    )
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
    hit = hit_at(ui.get(f"{panel}_hits") or [], x, y)
    idle_speed = str(ui.get(f"{panel}_idle_speed") or "")
    if hit:
        text, speed, active = str(hit.get("text") or ""), str(hit.get("speed") or ""), True
    else:
        text, speed, active = "", idle_speed, False
    shown = (text, speed)
    if shown == ui.get(f"{panel}_hover") and ui.get(f"{panel}_photo") is not None:
        return
    im = base.copy()
    if hit and hit.get("band"):
        _paint_focus(im, hit["band"])
    _paint_readout(im, text, speed, active=active)
    photo = ImageTk.PhotoImage(im)
    lbl = ui.get(f"{panel}_lbl")
    if lbl is not None:
        lbl.configure(image=photo)
    ui[f"{panel}_photo"] = photo
    ui[f"{panel}_hover"] = shown


def hit_at(hits: list[dict], x: int, y: int) -> dict | None:
    for hit in reversed(hits):
        if hit["x0"] <= x < hit["x1"] and hit["y0"] <= y <= hit["y1"]:
            return hit
    return None


def hover_text(hits: list[dict], x: int, y: int) -> str:
    hit = hit_at(hits, x, y)
    return str(hit["text"]) if hit else ""
