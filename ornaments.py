"""沙漏动画、极光贴图等装饰。"""
from __future__ import annotations

import math
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
    """右侧沙漏：生图玻璃器皿 + 仓内沙子随剩余时间变化。"""
    x0, y0, x1, y1 = rect
    tw, th = x1 - x0, y1 - y0
    if tw < 18 or th < 28:
        return
    ratio = 0.0 if done else max(0.0, min(1.0, float(remain_ratio)))
    vessel = load_asset("hourglass_vessel.png")
    if vessel is not None:
        _paint_vessel_hourglass(
            img, x0, y0, tw, th, vessel, ratio=ratio, running=running, sand=sand, phase=phase
        )
        return
    _paint_geom_hourglass(
        img, x0, y0, tw, th, ratio=ratio, running=running, sand=sand, glass=glass, phase=phase
    )


def _warm_sand(sand: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    r, g, b, a = sand
    return (
        min(255, (r + 210) // 2),
        min(255, (g + 160) // 2),
        min(255, (b + 60) // 2),
        min(230, max(170, a)),
    )


def _paint_vessel_hourglass(
    img: Image.Image,
    x0: int,
    y0: int,
    tw: int,
    th: int,
    vessel: Image.Image,
    *,
    ratio: float,
    running: bool,
    sand: tuple[int, int, int, int],
    phase: float,
) -> None:
    vw, vh = vessel.size
    scale = min(tw / vw, th / vh)
    nw, nh = max(1, int(vw * scale)), max(1, int(vh * scale))
    px = x0 + (tw - nw) // 2
    py = y0 + (th - nh) // 2
    sand_c = _warm_sand(sand)

    sand_layer = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    d = ImageDraw.Draw(sand_layer)
    cx = nw // 2
    top = int(nh * 0.24)
    mid = int(nh * 0.50)
    bot = int(nh * 0.76)
    hw = max(5, int(nw * 0.20))
    neck = max(2, int(nw * 0.035))

    if ratio > 0.001:
        fill_h = max(1, int((mid - top) * ratio))
        y_sand = mid - fill_h
        pts = _trap_in_triangle(cx, top, mid, hw, neck, y_sand, mid)
        if len(pts) >= 3:
            d.polygon(pts, fill=sand_c)
    bottom_ratio = 1.0 - ratio
    if bottom_ratio > 0.001:
        fill_h = max(1, int((bot - mid) * bottom_ratio))
        y_sand = bot - fill_h
        pts = _trap_in_triangle_up(cx, mid, bot, neck, hw, y_sand, bot)
        if len(pts) >= 3:
            d.polygon(pts, fill=sand_c)

    if running and 0.02 < ratio < 0.98:
        for i in range(4):
            t = (phase * 2.2 + i * 0.25) % 1.0
            gy = mid - 3 + int(t * 10)
            gx = cx + int(math.sin(phase * 7 + i * 1.7) * max(1, nw * 0.02))
            aa = int(200 * (1.0 - abs(t - 0.45) * 1.5))
            if aa > 24:
                d.ellipse((gx - 1, gy - 1, gx + 1, gy + 1), fill=(sand_c[0], sand_c[1], sand_c[2], aa))

    vessel_r = vessel.resize((nw, nh), Image.Resampling.LANCZOS)
    # 器皿略提亮透明度，避免发黑
    vessel_r = _scale_alpha(vessel_r, 0.92)
    out = Image.alpha_composite(sand_layer, vessel_r)
    img.paste(out, (px, py), out)


def _paint_geom_hourglass(
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
    cx = x0 + tw // 2
    top = y0 + 2
    bot = y0 + th - 2
    mid = (top + bot) // 2
    hw = max(6, tw // 2 - 3)
    neck = max(2, tw // 10)
    sand_c = _warm_sand(sand)
    d = ImageDraw.Draw(img)
    d.line((cx - hw, top, cx - neck, mid), fill=glass, width=1)
    d.line((cx + hw, top, cx + neck, mid), fill=glass, width=1)
    d.line((cx - neck, mid, cx - hw, bot), fill=glass, width=1)
    d.line((cx + neck, mid, cx + hw, bot), fill=glass, width=1)
    if ratio > 0.001:
        fill_h = max(1, int((mid - top) * ratio))
        pts = _trap_in_triangle(cx, top, mid, hw, neck, mid - fill_h, mid)
        if len(pts) >= 3:
            d.polygon(pts, fill=sand_c)
    if ratio < 0.999:
        fill_h = max(1, int((bot - mid) * (1.0 - ratio)))
        pts = _trap_in_triangle_up(cx, mid, bot, neck, hw, bot - fill_h, bot)
        if len(pts) >= 3:
            d.polygon(pts, fill=sand_c)
    if running and 0.02 < ratio < 0.98:
        for i in range(3):
            t = (phase * 2.4 + i * 0.33) % 1.0
            gy = mid - 4 + int(t * 12)
            gx = cx + int(math.sin(phase * 6 + i) * 1.2)
            aa = int(160 * (1.0 - abs(t - 0.5) * 1.6))
            if aa > 20:
                d.point((gx, gy), fill=(sand_c[0], sand_c[1], sand_c[2], aa))


def _trap_in_triangle(
    cx: int, top: int, mid: int, hw: int, neck: int, y0: int, y1: int
) -> list[tuple[int, int]]:
    y0 = max(top, min(mid, y0))
    y1 = max(top, min(mid, y1))
    if y1 <= y0:
        return []

    def half_at(y: int) -> float:
        t = (y - top) / max(1, mid - top)
        return hw + (neck - hw) * t

    return [
        (int(cx - half_at(y0)), y0),
        (int(cx + half_at(y0)), y0),
        (int(cx + half_at(y1)), y1),
        (int(cx - half_at(y1)), y1),
    ]


def _trap_in_triangle_up(
    cx: int, mid: int, bot: int, neck: int, hw: int, y0: int, y1: int
) -> list[tuple[int, int]]:
    y0 = max(mid, min(bot, y0))
    y1 = max(mid, min(bot, y1))
    if y1 <= y0:
        return []

    def half_at(y: int) -> float:
        t = (y - mid) / max(1, bot - mid)
        return neck + (hw - neck) * t

    return [
        (int(cx - half_at(y0)), y0),
        (int(cx + half_at(y0)), y0),
        (int(cx + half_at(y1)), y1),
        (int(cx - half_at(y1)), y1),
    ]
