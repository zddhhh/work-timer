"""动能字幕：拆字错峰弹出，过冲回弹，播完淡出。"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

STAGGER = 0.16
CHAR_DUR = 0.85
HOLD = 2.2
FADE = 0.7
TEXT = "中秋快乐"
_SWITCH_DELAY = (1.4, 2.6)
_OCCASIONAL = (8 * 60, 16 * 60)

_GLYPH_CACHE: dict[tuple, Image.Image] = {}


@dataclass
class Show:
    text: str
    started: float
    skipped: bool = False

    def skip(self) -> None:
        self.skipped = True


def intro_text() -> str:
    return TEXT


def next_delay(*, soon: bool) -> float:
    lo, hi = _SWITCH_DELAY if soon else _OCCASIONAL
    return random.uniform(lo, hi)


def duration(text: str) -> float:
    n = max(1, len(text))
    return (n - 1) * STAGGER + CHAR_DUR + HOLD + FADE


def playing(show: Show | None, now: float) -> bool:
    if show is None or show.skipped:
        return False
    return (now - show.started) < duration(show.text)


def _ease_out_cubic(t: float) -> float:
    u = 1.0 - t
    return 1.0 - u * u * u


def _ease_out_back(t: float, s: float = 1.75) -> float:
    u = t - 1.0
    return 1.0 + u * u * ((s + 1.0) * u + s)


def _ease_out_quad(t: float) -> float:
    return 1.0 - (1.0 - t) * (1.0 - t)


def _advance(font: ImageFont.ImageFont, ch: str) -> int:
    try:
        return max(1, int(round(font.getlength(ch))))
    except (AttributeError, OSError):
        box = font.getbbox(ch)
        return max(1, int(box[2] - box[0]))


def _glyph(
    font: ImageFont.ImageFont,
    ch: str,
    fill: tuple[int, int, int, int],
    scale: float,
    ghost: bool,
) -> Image.Image:
    q = max(20, min(160, int(round(scale * 50))))
    key = (ch, id(font), fill, q, ghost)
    got = _GLYPH_CACHE.get(key)
    if got is not None:
        return got
    pad = 8
    box = font.getbbox(ch)
    gw = max(1, int(box[2] - box[0])) + pad * 2
    gh = max(1, int(box[3] - box[1])) + pad * 2
    g = Image.new("RGBA", (gw, gh), (0, 0, 0, 0))
    d = ImageDraw.Draw(g)
    x, y = pad - box[0], pad - box[1]
    if ghost:
        d.text((x + 1, y + 1), ch, font=font, fill=(0, 0, 0, 80))
        d.text((x, y + 1), ch, font=font, fill=(0, 0, 0, 45))
    else:
        d.text((x + 1, y + 1), ch, font=font, fill=(0, 0, 0, 90))
    d.text((x, y), ch, font=font, fill=fill)
    s = q / 50.0
    if abs(s - 1.0) > 0.02:
        nw = max(1, int(round(gw * s)))
        nh = max(1, int(round(gh * s)))
        g = g.resize((nw, nh), Image.Resampling.BILINEAR)
    if len(_GLYPH_CACHE) > 96:
        _GLYPH_CACHE.clear()
    _GLYPH_CACHE[key] = g
    return g


def paint(
    img: Image.Image,
    show: Show,
    font: ImageFont.ImageFont,
    fill: tuple[int, int, int, int],
    now: float,
    *,
    ghost: bool = False,
) -> None:
    if show.skipped:
        return
    chars = list(show.text)
    n = len(chars)
    if n == 0:
        return
    elapsed = now - show.started
    end_in = (n - 1) * STAGGER + CHAR_DUR
    fade = 1.0
    if elapsed > end_in + HOLD:
        fade = max(0.0, 1.0 - (elapsed - end_in - HOLD) / FADE)
    if fade <= 0.01:
        return

    w, h = img.size
    advances = [_advance(font, ch) for ch in chars]
    gap = max(2, int(round(max(advances) * 0.08)))
    total = sum(advances) + gap * (n - 1)
    x0 = (w - total) / 2.0
    cy = h * 0.52
    drop = h * 0.28

    slots: list[float] = []
    x = x0
    for adv in advances:
        slots.append(x + adv / 2.0)
        x += adv + gap

    for i, ch in enumerate(chars):
        local = (elapsed - i * STAGGER) / CHAR_DUR
        if local <= 0.0:
            continue
        t = min(1.0, local)
        scale = 0.18 + 0.92 * _ease_out_back(t)
        oy = (1.0 - _ease_out_cubic(t)) * drop
        a = fade * _ease_out_quad(min(1.0, t * 1.35))
        if a <= 0.01:
            continue
        glyph = _glyph(font, ch, fill, scale, ghost)
        if a < 0.995:
            glyph = glyph.copy()
            ga = glyph.getchannel("A").point(lambda p, k=a: int(p * k))
            glyph.putalpha(ga)
        gx = int(round(slots[i] - glyph.width / 2.0))
        gy = int(round(cy - glyph.height / 2.0 + oy))
        img.alpha_composite(glyph, (gx, gy))
