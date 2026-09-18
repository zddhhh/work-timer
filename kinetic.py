"""动能字幕：拆字错峰弹出，过冲回弹，多句串播后淡出。"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

STAGGER = 0.13
CHAR_DUR = 0.72
HOLD = 1.45
FADE = 0.5
MIDAUTUMN_PHRASES: tuple[str, ...] = (
    "月圆人圆",
    "花好月圆",
    "但愿人长久",
    "千里共婵娟",
    "中秋快乐",
)
NATIONAL_PHRASES: tuple[str, ...] = (
    "欢度国庆",
    "金秋十月",
    "山河无恙",
)

_GLYPH_CACHE: OrderedDict[tuple, Image.Image] = OrderedDict()


@dataclass
class Show:
    phrases: tuple[str, ...]
    started: float
    skipped: bool = False

    def skip(self) -> None:
        self.skipped = True

    @property
    def text(self) -> str:
        """字号按最长一句来，避免中途换句撑破卡片。"""
        return max(self.phrases, key=len) if self.phrases else ""

    def current_text(self, now: float) -> str:
        t = now - self.started
        acc = 0.0
        last = self.phrases[-1] if self.phrases else ""
        for p in self.phrases:
            d = duration(p)
            if t < acc + d:
                return p
            acc += d
        return last

    def phrase_elapsed(self, now: float) -> float:
        t = now - self.started
        acc = 0.0
        last_d = duration(self.phrases[-1]) if self.phrases else 0.0
        for p in self.phrases:
            d = duration(p)
            if t < acc + d:
                return t - acc
            acc += d
        return last_d + 1.0


def duration(text: str) -> float:
    n = max(1, len(text))
    return (n - 1) * STAGGER + CHAR_DUR + HOLD + FADE


def total_duration(phrases: tuple[str, ...]) -> float:
    return sum(duration(p) for p in phrases) if phrases else 0.0


def playing(show: Show | None, now: float) -> bool:
    if show is None or show.skipped:
        return False
    return (now - show.started) < total_duration(show.phrases)


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
        _GLYPH_CACHE.move_to_end(key)
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
    # LRU：一句话的字形在弹出期间反复命中，整表清空会让正在播的字重新光栅化
    while len(_GLYPH_CACHE) >= 96:
        _GLYPH_CACHE.popitem(last=False)
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
    chars = list(show.current_text(now))
    n = len(chars)
    if n == 0:
        return
    elapsed = show.phrase_elapsed(now)
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
