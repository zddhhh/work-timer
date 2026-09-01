"""沙漏动画、极光贴图等装饰。"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageDraw

import store

_ASSET_CACHE: dict[str, Image.Image] = {}


def asset_path(name: str) -> Path:
    return store.app_dir() / "assets" / name


def load_asset(name: str) -> Image.Image | None:
    got = _ASSET_CACHE.get(name)
    if got is not None:
        return got
    path = asset_path(name)
    if not path.exists():
        return None
    try:
        im = Image.open(path).convert("RGBA")
    except OSError:
        return None
    _ASSET_CACHE[name] = im
    return im


def layout_for(w: int, h: int) -> tuple[int, int, int, int]:
    """按窗口尺寸算字体与右侧沙漏宽度。"""
    scale = min(max(w, 1) / 248.0, max(h, 1) / 92.0)
    ft = max(12, min(26, int(round(15 * scale))))
    fb = max(18, min(44, int(round(28 * scale))))
    fs = max(10, min(18, int(round(12 * scale))))
    hg = max(36, min(96, int(round(min(h * 0.78, w * 0.24)))))
    return ft, fb, fs, hg


def _scale_alpha(im: Image.Image, factor: float) -> Image.Image:
    out = im.copy()
    a = out.getchannel("A").point(lambda v: max(0, min(255, int(v * factor))))
    out.putalpha(a)
    return out


def paste_aurora(img: Image.Image, box: tuple[int, int, int, int], *, light: bool = False) -> None:
    """把生图极光贴到卡片圆角区域。"""
    x0, y0, x1, y1 = box
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    drape = load_asset("aurora_drape.png")
    glow = load_asset("aurora_glow.png")
    if drape is None and glow is None:
        return
    phase = time.monotonic()
    layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    if drape is not None:
        tw = max(bw + 80, drape.width)
        th = max(bh, drape.height)
        src = drape.resize((tw, th), Image.Resampling.LANCZOS)
        ox = int((phase * 12) % max(1, src.width - bw))
        oy = max(0, (src.height - bh) // 2)
        crop = src.crop((ox, oy, ox + bw, oy + bh))
        layer = Image.alpha_composite(layer, _scale_alpha(crop, 0.78 if not light else 0.48))
    if glow is not None:
        tw = max(bw + 60, glow.width)
        th = max(bh, glow.height)
        src = glow.resize((tw, th), Image.Resampling.LANCZOS)
        ox = int((phase * -9) % max(1, src.width - bw))
        oy = max(0, (src.height - bh) // 2)
        crop = src.crop((ox, oy, ox + bw, oy + bh))
        layer = Image.alpha_composite(layer, _scale_alpha(crop, 0.55 if not light else 0.32))

    mask = Image.new("L", (bw, bh), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=max(8, min(bw, bh) // 6), fill=255)
    img.paste(layer, (x0, y0), mask)


def paint_hourglass(
    img: Image.Image,
    rect: tuple[int, int, int, int],
    *,
    remain_ratio: float,
    running: bool,
    done: bool,
    sand: tuple[int, int, int, int],
    glass: tuple[int, int, int, int],
    phase: float,
) -> None:
    """右侧沙漏：干净玻璃轮廓 + 上下沙堆 + 颈部细沙粒（参考常见 SVG/CSS 沙漏）。"""
    x0, y0, x1, y1 = rect
    tw, th = x1 - x0, y1 - y0
    if tw < 18 or th < 28:
        return
    ratio = 0.0 if done else max(0.0, min(1.0, float(remain_ratio)))
    _paint_clean_hourglass(
        img, x0, y0, tw, th, ratio=ratio, running=running, sand=sand, glass=glass, phase=phase
    )


def _sand_color(sand: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    """偏米色的沙子，轻微带上主题色，避免发成火光。"""
    r, g, b, a = sand
    return (
        min(255, (r + 226 * 2) // 3),
        min(255, (g + 190 * 2) // 3),
        min(255, (b + 96 * 2) // 3),
        min(235, max(200, a)),
    )


def _half_top(y: int, top: int, mid: int, hw: int, neck: int) -> float:
    t = (y - top) / max(1, mid - top)
    return hw + (neck - hw) * max(0.0, min(1.0, t))


def _half_bot(y: int, mid: int, bot: int, neck: int, hw: int) -> float:
    t = (y - mid) / max(1, bot - mid)
    return neck + (hw - neck) * max(0.0, min(1.0, t))


def _paint_clean_hourglass(
    img: Image.Image,
    x0: int,
    y0: int,
    tw: int,
    th: int,
    *,
    ratio: float,
    running: bool,
    sand: tuple[int, int, int, int],
    glass: tuple[int, int, int, int],
    phase: float,
) -> None:
    d = ImageDraw.Draw(img)
    cx = x0 + tw // 2
    # 上下小盖 + 玻璃仓
    cap_h = max(2, th // 18)
    top = y0 + cap_h + 1
    bot = y0 + th - cap_h - 2
    mid = (top + bot) // 2
    hw = max(7, int(tw * 0.36))
    neck = max(1, int(tw * 0.045))
    sand_c = _sand_color(sand)
    grain = (sand_c[0], sand_c[1], sand_c[2], 220)
    # 玻璃描边：亮一点的描边，像常见 loader
    gstroke = glass if glass[3] > 40 else (210, 220, 235, 160)
    gfill = (gstroke[0], gstroke[1], gstroke[2], 28)

    # 上下盖
    d.rounded_rectangle((cx - hw - 1, y0, cx + hw + 1, y0 + cap_h), radius=1, fill=gstroke)
    d.rounded_rectangle(
        (cx - hw - 1, y0 + th - cap_h - 1, cx + hw + 1, y0 + th - 1), radius=1, fill=gstroke
    )

    # 玻璃仓淡底
    top_bulb = [(cx - hw, top), (cx + hw, top), (cx + neck, mid), (cx - neck, mid)]
    bot_bulb = [(cx - neck, mid), (cx + neck, mid), (cx + hw, bot), (cx - hw, bot)]
    d.polygon(top_bulb, fill=gfill)
    d.polygon(bot_bulb, fill=gfill)

    # —— 上仓沙子：从颈部往上堆，顶面略凹 ——
    if ratio > 0.004:
        bulb_h = mid - top
        fill_h = max(2, int(bulb_h * ratio))
        y_surface = mid - fill_h
        dip = max(1, min(3, fill_h // 5)) if running and ratio < 0.97 else 0
        y_dip = min(mid - 1, y_surface + dip)
        left = int(cx - _half_top(y_surface, top, mid, hw, neck))
        right = int(cx + _half_top(y_surface, top, mid, hw, neck))
        pts = [
            (left, y_surface),
            (cx - max(1, neck), y_dip),
            (cx + max(1, neck), y_dip),
            (right, y_surface),
            (cx + neck, mid),
            (cx - neck, mid),
        ]
        d.polygon(pts, fill=sand_c)
        # 沙面细线，不用高亮光带
        if right - left > 6:
            d.line((left + 1, y_surface, right - 1, y_surface), fill=(grain[0], grain[1], grain[2], 90), width=1)

    # —— 下仓沙子：底部沙堆，中间略鼓 ——
    bottom_ratio = 1.0 - ratio
    pile_top = mid + 2
    if bottom_ratio > 0.004:
        bulb_h = bot - mid
        fill_h = max(2, int(bulb_h * bottom_ratio))
        y_base = bot - fill_h
        peak = max(1, min(4, fill_h // 4)) if running else max(0, fill_h // 8)
        y_peak = max(mid + 1, y_base - peak)
        left = int(cx - _half_bot(y_base, mid, bot, neck, hw))
        right = int(cx + _half_bot(y_base, mid, bot, neck, hw))
        pts = [
            (cx - neck, mid),
            (cx + neck, mid),
            (right, y_base),
            (cx, y_peak),
            (left, y_base),
        ]
        d.polygon(pts, fill=sand_c)
        pile_top = y_peak

    # —— 颈部细沙粒下落（离散颗粒，不是光柱）——
    if running and 0.02 < ratio < 0.98:
        y0 = mid - 1
        y1 = max(mid + 2, pile_top - 1)
        span = max(6, y1 - y0)
        n = max(6, min(12, th // 8))
        for i in range(n):
            t = (phase * 1.8 + i / n) % 1.0
            # 匀速略带加速，像沙粒
            ease = t * 0.55 + t * t * 0.45
            gy = y0 + int(ease * span)
            # 落在 1～2 像素宽的竖直细缝里
            gx = cx + ((i * 3) % 3) - 1
            aa = 200 if i % 2 == 0 else 160
            d.point((gx, gy), fill=(grain[0], grain[1], grain[2], aa))
            if i % 2 == 0:
                d.point((gx, gy + 1), fill=(grain[0], grain[1], grain[2], aa // 2))

    # 玻璃轮廓压在最上
    d.line((cx - hw, top, cx - neck, mid), fill=gstroke, width=1)
    d.line((cx + hw, top, cx + neck, mid), fill=gstroke, width=1)
    d.line((cx - neck, mid, cx - hw, bot), fill=gstroke, width=1)
    d.line((cx + neck, mid, cx + hw, bot), fill=gstroke, width=1)
    d.line((cx - hw, top, cx + hw, top), fill=gstroke, width=1)
    d.line((cx - hw, bot, cx + hw, bot), fill=gstroke, width=1)
