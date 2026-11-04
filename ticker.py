"""工时盘口：等宽毫秒倒计时，底下跟手的迷你 K 线。

指数从 100 开盘。键鼠次数往上累，像长牛；停手、放慢只回一小截，不是归零。
涨跌幅对比开盘。红涨绿跌按 A 股习惯。毫秒位是真的；不是微秒。
"""
from __future__ import annotations

import math
import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

KIND = "ticker"
CANDLE_S = 5.0
MAX_BARS = 36
FPS = 36
INDEX0 = 100.0
TREND_GAIN = 9.0
TREND_TAU = 380.0
FAST_TAU = 0.55
SLOW_TAU = 16.0
OSC_AMP = 0.014
DT_MAX = 0.28
# A 股：红涨绿跌
RED = (236, 64, 64, 255)
GREEN = (40, 186, 128, 255)
FLAT = (168, 176, 184, 230)
PAPER = (8, 10, 14, 255)
GRID = (28, 36, 44, 70)
WICK = {
    True: (236, 64, 64, 220),
    False: (40, 186, 128, 220),
}

@dataclass
class Candle:
    o: float
    h: float
    l: float
    c: float
    v: float

    @property
    def up(self) -> bool:
        return self.c >= self.o


_FONTS: dict[tuple[str, int], ImageFont.ImageFont] = {}
_bars: list[Candle] = []
_forming: Candle | None = None
_t0 = 0.0
_last_now = 0.0
_last_px = INDEX0
_cum = 0.0
_fast = 0.0
_slow = 0.0
_px = INDEX0
_chg = 0.0
_poke_until = 0.0
_flash_until = 0.0
_flash_up = True


def reset() -> None:
    global _bars, _forming, _t0, _last_now, _last_px, _cum, _fast, _slow, _px
    global _chg, _poke_until, _flash_until
    _bars = []
    _forming = None
    _t0 = 0.0
    _last_now = 0.0
    _last_px = INDEX0
    _cum = 0.0
    _fast = 0.0
    _slow = 0.0
    _px = INDEX0
    _chg = 0.0
    _poke_until = 0.0
    _flash_until = 0.0


def fps(_stage: str, _now: float) -> int:
    return FPS


def poke(now: float) -> None:
    """点卡片：当下一笔买单，指数抬一截。"""
    global _poke_until, _flash_until, _flash_up, _cum, _fast
    _poke_until = now + 0.45
    _flash_until = now + 0.28
    _flash_up = True
    _cum += 28.0
    _fast += 8.0


def header_title(stage: str, *, idle: bool) -> str:
    if idle:
        return "未开盘"
    if stage == "done":
        return "收盘"
    if stage == "warn":
        return "临近收盘"
    return "距离下班"


def format_clock(seconds: float, *, idle: bool = False) -> str:
    if idle:
        return "--:--:--.---"
    sec = float(seconds)
    sign = ""
    if sec < 0:
        sign = "+"
        sec = -sec
    ms = int(round((sec - math.floor(sec)) * 1000.0))
    if ms >= 1000:
        sec += 1.0
        ms = 0
    total = int(math.floor(sec))
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    if h >= 100:
        d, h = divmod(h, 24)
        return f"{sign}{d}d {h:02d}:{m:02d}:{s:02d}.{ms:03d}"
    return f"{sign}{h:02d}:{m:02d}:{s:02d}.{ms:03d}"


def _ema(prev: float, x: float, dt: float, tau: float) -> float:
    if tau <= 0:
        return x
    a = 1.0 - math.exp(-max(0.0, dt) / tau)
    return prev + (x - prev) * a


def _quote(rate: float, dt: float) -> float:
    """工时累进做趋势，快慢均线差做回撤。停手不会把指数打回 0。"""
    global _cum, _fast, _slow, _px
    live = max(0.0, float(rate))
    _cum += live * dt
    _fast = _ema(_fast, live, dt, FAST_TAU)
    _slow = _ema(_slow, live, dt, SLOW_TAU)
    trend = INDEX0 + TREND_GAIN * math.log1p(_cum / TREND_TAU)
    osc = OSC_AMP * math.tanh((_fast - _slow) / 3.5)
    _px = max(INDEX0 * 0.92, trend * (1.0 + osc))
    return _px


def observe(now: float, rate: float) -> None:
    """每帧喂一次瞬时强度。rate = 这一秒键+点+滚 的每秒次数。"""
    global _bars, _forming, _t0, _last_now, _last_px, _px, _chg, _flash_until, _flash_up
    live = max(0.0, float(rate))
    if now < _poke_until:
        live += 8.0
    if _forming is None:
        _px = INDEX0
        _forming = Candle(INDEX0, INDEX0, INDEX0, INDEX0, 0.0)
        _t0 = now
        _last_now = now
        _last_px = INDEX0
        if live <= 0:
            return
        dt = 1.0 / FPS
    else:
        dt = now - _last_now
        if dt <= 0:
            return
        dt = min(dt, DT_MAX)
    _last_now = now
    px = _quote(live, dt)
    _forming.h = max(_forming.h, px)
    _forming.l = min(_forming.l, px)
    _forming.c = px
    _forming.v += live * dt
    if px > _last_px + 0.08:
        _flash_until = now + 0.18
        _flash_up = True
    elif px + 0.08 < _last_px:
        _flash_until = now + 0.18
        _flash_up = False
    _last_px = px
    _chg = (px - INDEX0) / INDEX0 * 100.0
    if now - _t0 < CANDLE_S:
        return
    _bars.append(_forming)
    if len(_bars) > MAX_BARS:
        _bars = _bars[-MAX_BARS:]
    _forming = Candle(px, px, px, px, 0.0)
    _t0 = now


def paint(layer: Image.Image, phase: float, *, stage: str, radius: int) -> None:
    """卡片底：深色盘面、细网格、底边一抹涨跌光。"""
    w, h = layer.size
    d = ImageDraw.Draw(layer)
    d.rectangle((0, 0, w, h), fill=PAPER)
    step = max(6, h // 8)
    gy = 4
    while gy < h - 2:
        d.line((4, gy, w - 5, gy), fill=GRID, width=1)
        gy += step
    for y in range(2, h, 4):
        d.line((0, y, w, y), fill=(255, 255, 255, 5), width=1)
    up = _forming.up if _forming is not None else True
    glow = RED if (stage == "done" or up) else GREEN
    if stage == "idle":
        glow = (70, 78, 88, 255)
    band = Image.new("RGBA", (w, max(8, h // 4)), (0, 0, 0, 0))
    bd = ImageDraw.Draw(band)
    bh = band.size[1]
    for i in range(bh):
        a = int(36 * (i / max(1, bh - 1)))
        bd.line((0, i, w, i), fill=(*glow[:3], a), width=1)
    layer.alpha_composite(band, (0, h - band.size[1]))
    rad = max(4, int(radius))
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=rad, outline=(48, 58, 66, 90), width=1)


def paint_face(
    img: Image.Image,
    box: tuple[int, int, int, int],
    *,
    title: str,
    clock: str,
    stage: str,
    now: float,
    top: int,
    nudge: str = "",
) -> None:
    """标题行、毫秒读数、底部 K 线。top 是 tally 让开之后的起点。nudge 是喝水这类短提示。"""
    x0, y0, x1, y1 = (int(v) for v in box)
    w = max(8, x1 - x0)
    h = max(8, y1 - top)
    if h < 12 or w < 40:
        return
    d = ImageDraw.Draw(img)
    compact = h < 52 or (y1 - y0) < 72
    kline_h = 0 if compact else max(16, min(max(36, int((y1 - y0) * 0.30)), int(h * 0.42)))
    head_h = max(10, min(16, 11 if compact else int(h * 0.22)))
    clock_top = top + head_h
    clock_bot = y1 - kline_h - (2 if compact else 3)
    if clock_bot < clock_top + 12:
        kline_h = 0
        clock_bot = y1 - 2

    up = _change_up(now, stage)
    pct = _chg
    pct_text = f"{pct:+.1f}%" if abs(pct) < 1000 else f"{pct:+.0f}%"
    if stage == "idle":
        pct_text = "0.00%"
        up = None
    pct_fill = FLAT if up is None else (RED if up else GREEN)

    title_font = _font("ui", max(9, min(12, head_h - 1)))
    code_font = _font("label", max(8, min(11, head_h - 2)))
    pct_font = _font("mono", max(8, min(12, head_h)))
    title_fill = (198, 206, 200, 240)
    if stage == "done":
        title_fill = (255, 150, 140, 255)
    elif stage == "warn":
        title_fill = (255, 186, 130, 250)
    if nudge:
        title_fill = RED if int(now * 2) % 2 == 0 else (255, 186, 130, 250)
    d.text((x0 + 5, top), "OFF", font=code_font, fill=(168, 186, 178, 230))
    tx = x0 + max(28, int(w * 0.14))
    d.text((tx, top), title, font=title_font, fill=title_fill)
    right = (nudge or pct_text).strip()
    right_font = title_font if nudge else pct_font
    right_fill = title_fill if nudge else pct_fill
    pw = int(d.textlength(right, font=right_font)) if right else 0
    title_w = int(d.textlength(title, font=title_font)) if title else 0
    if right and x1 - 6 - pw > tx + title_w + 6:
        d.text((x1 - 6 - pw, top), right, font=right_font, fill=right_fill)

    clock_h = max(14, clock_bot - clock_top)
    clock_font = (
        _mono_fit(d, clock, max(40, w - 16), clock_h)
        if _is_clock_text(clock)
        else _ui_fit(d, clock, max(40, w - 16), clock_h)
    )
    bb = d.textbbox((0, 0), clock, font=clock_font)
    cw, ch = bb[2] - bb[0], bb[3] - bb[1]
    cx = x0 + max(0, (w - cw) // 2) - bb[0]
    cy = clock_top + max(0, (clock_h - ch) // 2) - bb[1]
    body, frac = _split_clock(clock) if _is_clock_text(clock) else (clock, "")
    if frac:
        body_w = int(d.textlength(body, font=clock_font))
        fill_body = (248, 250, 252, 255)
        fill_frac = pct_fill if stage != "idle" else FLAT
        if stage == "done":
            fill_body = RED
            fill_frac = RED
        elif now < _flash_until:
            flash = RED if _flash_up else GREEN
            fill_body = flash
            fill_frac = flash
        d.text((cx, cy), body, font=clock_font, fill=fill_body)
        d.text((cx + body_w, cy), frac, font=clock_font, fill=fill_frac)
    else:
        fill = RED if stage == "done" else (248, 250, 252, 255)
        d.text((cx, cy), clock, font=clock_font, fill=fill)

    if kline_h >= 14:
        _paint_kline(d, (x0 + 6, y1 - kline_h, x1 - 6, y1 - 3), stage)


def bars() -> list[Candle]:
    return list(_bars)


def forming() -> Candle | None:
    return _forming


def change_pct() -> float:
    return _chg


def _change_up(now: float, stage: str) -> bool | None:
    if stage == "idle":
        return None
    if now < _flash_until:
        return _flash_up
    if abs(_chg) < 0.05:
        return None
    return _chg >= 0


def _split_clock(clock: str) -> tuple[str, str]:
    if "." in clock:
        a, b = clock.rsplit(".", 1)
        return a, "." + b
    return clock, ""


def _paint_kline(
    d: ImageDraw.ImageDraw,
    box: tuple[int, int, int, int],
    stage: str,
) -> None:
    x0, y0, x1, y1 = box
    width = x1 - x0
    height = y1 - y0
    if width < 20 or height < 10:
        return
    seq = list(_bars)
    if _forming is not None:
        seq.append(_forming)
    if not seq:
        mid = (y0 + y1) // 2
        d.line((x0, mid, x1, mid), fill=(60, 70, 80, 120), width=1)
        return
    n = MAX_BARS
    slot = width / float(n)
    body_w = max(2, int(slot * 0.62))
    if body_w % 2 == 0:
        body_w += 1
    hi = max(c.h for c in seq)
    lo = min(c.l for c in seq)
    if hi - lo < 0.8:
        mid = 0.5 * (hi + lo)
        hi = mid + 0.5
        lo = mid - 0.5
    pad = (hi - lo) * 0.12
    hi += pad
    lo -= pad
    span = hi - lo if hi > lo else 1.0

    def yy(v: float) -> int:
        u = (v - lo) / span
        return int(round(y1 - 1 - u * (height - 2)))

    d.line((x0, y1 - 1, x1, y1 - 1), fill=(46, 54, 64, 90), width=1)
    start = n - len(seq)
    for i, c in enumerate(seq):
        cx = int(x0 + (start + i + 0.5) * slot)
        up = c.up
        col = RED if up else GREEN
        if stage == "idle":
            col = FLAT
        wick = WICK[up]
        y_h, y_l = yy(c.h), yy(c.l)
        y_o, y_c = yy(c.o), yy(c.c)
        d.line((cx, y_h, cx, y_l), fill=wick, width=1)
        top, bot = (y_c, y_o) if y_c < y_o else (y_o, y_c)
        if bot - top < 1:
            bot = top + 1
        x_l = cx - body_w // 2
        x_r = x_l + body_w
        if up:
            d.rectangle((x_l, top, x_r, bot), outline=col, width=1)
        else:
            d.rectangle((x_l, top, x_r, bot), fill=col)


def _is_clock_text(text: str) -> bool:
    """倒计时才走等宽字。中文提醒不能塞进 Consolas，否则变成方框。"""
    return bool(text) and all(ch in "0123456789:+- .d" for ch in text)


def _ui_fit(d: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int) -> ImageFont.ImageFont:
    lo, hi = 10, max(12, min(28, int(max_h * 0.86)))
    best = _font("ui", lo)
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _font("ui", mid)
        bb = d.textbbox((0, 0), text, font=font)
        if bb[2] - bb[0] <= max_w and bb[3] - bb[1] <= max_h:
            best = font
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _mono_fit(d: ImageDraw.ImageDraw, text: str, max_w: int, max_h: int) -> ImageFont.ImageFont:
    lo, hi = 10, max(12, min(34, int(max_h * 0.92)))
    best = _font("mono", lo)
    while lo <= hi:
        mid = (lo + hi) // 2
        font = _font("mono", mid)
        bb = d.textbbox((0, 0), text, font=font)
        if bb[2] - bb[0] <= max_w and bb[3] - bb[1] <= max_h:
            best = font
            lo = mid + 1
        else:
            hi = mid - 1
    return best


def _font(kind: str, size: int) -> ImageFont.ImageFont:
    size = max(8, int(size))
    key = (kind, size)
    got = _FONTS.get(key)
    if got is not None:
        return got
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    names = {
        "mono": ("consola.ttf", "CascadiaMono.ttf", "cascadiamono.ttf", "cour.ttf", "msyh.ttc"),
        "label": ("consola.ttf", "msyhbd.ttc", "msyh.ttc"),
        "ui": ("msyhbd.ttc", "msyh.ttc", "msyh.ttf", "simhei.ttf"),
    }[kind]
    font: ImageFont.ImageFont | None = None
    for name in names:
        path = windir / name
        try:
            if path.suffix.lower() == ".ttc":
                font = ImageFont.truetype(str(path), size, index=0)
            else:
                font = ImageFont.truetype(str(path), size)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default()
    _FONTS[key] = font
    return font


def intensity_from_activity(cfg: dict, now: datetime | None = None) -> float:
    import activity

    return float(activity.live_intensity(cfg, now))
