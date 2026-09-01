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
    bright = (
        min(255, sand_c[0] + 30),
        min(255, sand_c[1] + 20),
        min(255, sand_c[2] + 10),
        245,
    )

    sand_layer = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    d = ImageDraw.Draw(sand_layer)
    cx = nw // 2
    top = int(nh * 0.24)
    mid = int(nh * 0.50)
    bot = int(nh * 0.76)
    hw = max(5, int(nw * 0.20))
    neck = max(2, int(nw * 0.04))

    # 上仓：漏斗形液面，往颈部凹一点，看起来像在往下漏
    if ratio > 0.001:
        fill_h = max(2, int((mid - top) * ratio))
        y_flat = mid - fill_h
        dip = 0
        if running and ratio < 0.98:
            dip = max(2, int(min(fill_h * 0.35, nh * 0.06)))
            dip += int(math.sin(phase * 3.2) * 0.8)
        _draw_top_sand(d, cx, top, mid, hw, neck, y_flat, dip, sand_c, bright)

    # 下仓：中间鼓起的沙堆
    bottom_ratio = 1.0 - ratio
    if bottom_ratio > 0.001:
        fill_h = max(2, int((bot - mid) * bottom_ratio))
        peak = 0
        if running:
            peak = max(1, int(min(fill_h * 0.28, nh * 0.05)))
        _draw_bottom_sand(d, cx, mid, bot, neck, hw, bot - fill_h, peak, sand_c, bright)

    vessel_r = vessel.resize((nw, nh), Image.Resampling.LANCZOS)
    vessel_r = _scale_alpha(vessel_r, 0.88)
    out = Image.alpha_composite(sand_layer, vessel_r)

    # 流沙画在玻璃前面，否则被器皿挡住看不见
    if running and 0.01 < ratio < 0.995:
        flow = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
        fd = ImageDraw.Draw(flow)
        _draw_sand_stream(fd, cx, mid, nh, nw, sand_c, bright, phase)
        out = Image.alpha_composite(out, flow)

    img.paste(out, (px, py), out)


def _draw_top_sand(
    d: ImageDraw.ImageDraw,
    cx: int,
    top: int,
    mid: int,
    hw: int,
    neck: int,
    y_flat: int,
    dip: int,
    sand: tuple[int, int, int, int],
    bright: tuple[int, int, int, int],
) -> None:
    y_flat = max(top + 1, min(mid - 1, y_flat))
    y_dip = min(mid - 1, y_flat + max(0, dip))
    left = int(cx - _half_at(y_flat, top, mid, hw, neck))
    right = int(cx + _half_at(y_flat, top, mid, hw, neck))
    # 漏斗口：两边高、中间低
    pts = [
        (left, y_flat),
        (cx - max(1, neck), y_dip),
        (cx + max(1, neck), y_dip),
        (right, y_flat),
        (int(cx + _half_at(mid, top, mid, hw, neck)), mid),
        (int(cx - _half_at(mid, top, mid, hw, neck)), mid),
    ]
    d.polygon(pts, fill=sand)
    # 表面高光
    if right - left > 4:
        d.line((left + 1, y_flat, cx - 2, y_dip), fill=bright, width=1)
        d.line((cx + 2, y_dip, right - 1, y_flat), fill=bright, width=1)


def _draw_bottom_sand(
    d: ImageDraw.ImageDraw,
    cx: int,
    mid: int,
    bot: int,
    neck: int,
    hw: int,
    y_base: int,
    peak: int,
    sand: tuple[int, int, int, int],
    bright: tuple[int, int, int, int],
) -> None:
    y_base = max(mid + 1, min(bot - 1, y_base))
    y_peak = max(mid + 1, y_base - max(0, peak))
    left = int(cx - _half_at_up(y_base, mid, bot, neck, hw))
    right = int(cx + _half_at_up(y_base, mid, bot, neck, hw))
    pts = [
        (int(cx - neck), mid),
        (int(cx + neck), mid),
        (right, y_base),
        (cx, min(bot - 1, y_base + 1)),
        (left, y_base),
    ]
    # 堆尖
    if peak > 0:
        pts = [
            (int(cx - neck), mid),
            (int(cx + neck), mid),
            (right, y_base),
            (cx + 1, y_peak),
            (cx - 1, y_peak),
            (left, y_base),
        ]
    d.polygon(pts, fill=sand)
    if peak > 0:
        d.line((cx - 2, y_peak + 1, cx + 2, y_peak + 1), fill=bright, width=1)


def _draw_sand_stream(
    d: ImageDraw.ImageDraw,
    cx: int,
    mid: int,
    nh: int,
    nw: int,
    sand: tuple[int, int, int, int],
    bright: tuple[int, int, int, int],
    phase: float,
) -> None:
    """颈部可见的连续沙柱 + 下落颗粒。"""
    span = max(14, int(nh * 0.16))
    y0 = mid - span // 2
    y1 = mid + span // 2
    # 主沙柱（带一点左右晃）
    sway = math.sin(phase * 5.5) * max(0.6, nw * 0.012)
    for y in range(y0, y1 + 1):
        t = (y - y0) / max(1, y1 - y0)
        # 上细下略宽
        half = 0.8 + t * 1.2
        pulse = 0.65 + 0.35 * abs(math.sin(phase * 8 + t * 6))
        aa = int(210 * pulse)
        x = cx + sway * (0.3 + t)
        d.line(
            (int(x - half), y, int(x + half), y),
            fill=(bright[0], bright[1], bright[2], aa),
            width=1,
        )
    # 下落颗粒
    n = 10
    for i in range(n):
        t = (phase * 2.8 + i / n) % 1.0
        # 加速下落：ease-in
        ease = t * t
        gy = y0 + int(ease * (y1 - y0 + 4))
        gx = cx + int(math.sin(phase * 9 + i * 2.1) * max(1.2, nw * 0.03))
        sz = 1 if i % 3 else 2
        aa = int(230 * (1.0 - t * 0.55))
        d.ellipse(
            (gx - sz, gy - sz, gx + sz, gy + sz),
            fill=(bright[0], bright[1], bright[2], aa),
        )


def _half_at(y: int, top: int, mid: int, hw: int, neck: int) -> float:
    t = (y - top) / max(1, mid - top)
    return hw + (neck - hw) * t


def _half_at_up(y: int, mid: int, bot: int, neck: int, hw: int) -> float:
    t = (y - mid) / max(1, bot - mid)
    return neck + (hw - neck) * t


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
    bright = (
        min(255, sand_c[0] + 30),
        min(255, sand_c[1] + 20),
        min(255, sand_c[2] + 10),
        245,
    )
    d = ImageDraw.Draw(img)
    d.line((cx - hw, top, cx - neck, mid), fill=glass, width=1)
    d.line((cx + hw, top, cx + neck, mid), fill=glass, width=1)
    d.line((cx - neck, mid, cx - hw, bot), fill=glass, width=1)
    d.line((cx + neck, mid, cx + hw, bot), fill=glass, width=1)
    if ratio > 0.001:
        fill_h = max(2, int((mid - top) * ratio))
        dip = max(2, int(fill_h * 0.3)) if running else 0
        _draw_top_sand(d, cx, top, mid, hw, neck, mid - fill_h, dip, sand_c, bright)
    if ratio < 0.999:
        fill_h = max(2, int((bot - mid) * (1.0 - ratio)))
        peak = max(1, int(fill_h * 0.25)) if running else 0
        _draw_bottom_sand(d, cx, mid, bot, neck, hw, bot - fill_h, peak, sand_c, bright)
    if running and 0.01 < ratio < 0.995:
        _draw_sand_stream(d, cx, mid, th, tw, sand_c, bright, phase)
