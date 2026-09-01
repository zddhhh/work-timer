"""沙漏动画、极光贴图等装饰。"""
from __future__ import annotations

import math
import time
from functools import lru_cache
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
        # 横向缓慢漂移
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

    # 圆角遮罩，避免贴图溢出
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
    """右侧小沙漏：上仓沙子随剩余时间变少。"""
    x0, y0, x1, y1 = rect
    w, h = x1 - x0, y1 - y0
    if w < 16 or h < 24:
        return
    cx = x0 + w // 2
    top = y0 + 2
    bot = y1 - 2
    mid = (top + bot) // 2
    hw = max(6, w // 2 - 3)
    neck = max(2, w // 10)
    ratio = max(0.0, min(1.0, float(remain_ratio)))
    if done:
        ratio = 0.0

    d = ImageDraw.Draw(img)
    # 木色细框（极轻），玻璃轮廓
    frame = (120, 100, 80, 90) if glass[0] + glass[1] + glass[2] > 400 else (200, 180, 140, 70)
    d.line((cx - hw, top, cx + hw, top), fill=frame, width=1)
    d.line((cx - hw, bot, cx + hw, bot), fill=frame, width=1)
    d.line((cx - hw, top, cx - neck, mid), fill=glass, width=1)
    d.line((cx + hw, top, cx + neck, mid), fill=glass, width=1)
    d.line((cx - neck, mid, cx - hw, bot), fill=glass, width=1)
    d.line((cx + neck, mid, cx + hw, bot), fill=glass, width=1)

    # 上仓沙子：从颈部往上堆，高度随 ratio
    top_h = mid - top
    if ratio > 0.001 and top_h > 2:
        fill_h = max(1, int(top_h * ratio))
        y_sand = mid - fill_h
        # 三角形截面宽度随高度变化
        pts = _trap_in_triangle(cx, top, mid, hw, neck, y_sand, mid)
        if len(pts) >= 3:
            d.polygon(pts, fill=sand)

    # 下仓沙子
    bottom_ratio = 1.0 - ratio
    bot_h = bot - mid
    if bottom_ratio > 0.001 and bot_h > 2:
        fill_h = max(1, int(bot_h * bottom_ratio))
        y_sand = bot - fill_h
        pts = _trap_in_triangle_up(cx, mid, bot, neck, hw, y_sand, bot)
        if len(pts) >= 3:
            d.polygon(pts, fill=sand)

    # 下落沙粒
    if running and 0.02 < ratio < 0.98:
        for i in range(3):
            t = (phase * 2.4 + i * 0.33) % 1.0
            gy = mid - 4 + int(t * 12)
            gx = cx + int(math.sin(phase * 6 + i) * 1.2)
            aa = int(160 * (1.0 - abs(t - 0.5) * 1.6))
            if aa > 20:
                d.point((gx, gy), fill=(sand[0], sand[1], sand[2], aa))
                d.point((gx, gy + 1), fill=(sand[0], sand[1], sand[2], aa // 2))


def _trap_in_triangle(
    cx: int, top: int, mid: int, hw: int, neck: int, y0: int, y1: int
) -> list[tuple[int, int]]:
    """上仓倒三角内，取 y0..y1 水平带。"""
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
    """下仓正三角内，取 y0..y1 水平带。"""
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


@lru_cache(maxsize=8)
def size_preset(size_id: str) -> tuple[int, int, int, int, int, int]:
    """返回 (w, h, font_title, font_big, font_sub, hourglass_w)。"""
    table = {
        "s": (248, 92, 15, 28, 12, 52),
        "m": (320, 118, 17, 34, 13, 68),
        "l": (400, 148, 20, 42, 15, 86),
    }
    return table.get(size_id, table["s"])
