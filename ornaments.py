"""极光贴图等装饰。"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

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


def layout_for(w: int, h: int) -> tuple[int, int, int]:
    """按窗口尺寸算字体。"""
    scale = min(max(w, 1) / 248.0, max(h, 1) / 92.0)
    ft = max(10, min(26, int(round(15 * scale))))
    fb = max(16, min(44, int(round(28 * scale))))
    fs = max(8, min(18, int(round(12 * scale))))
    return ft, fb, fs


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
        # 底板已尽量淡，极光贴图略提亮一点
        layer = Image.alpha_composite(layer, _scale_alpha(crop, 0.92 if not light else 0.58))
    if glow is not None:
        tw = max(bw + 60, glow.width)
        th = max(bh, glow.height)
        src = glow.resize((tw, th), Image.Resampling.LANCZOS)
        ox = int((phase * -9) % max(1, src.width - bw))
        oy = max(0, (src.height - bh) // 2)
        crop = src.crop((ox, oy, ox + bw, oy + bh))
        layer = Image.alpha_composite(layer, _scale_alpha(crop, 0.72 if not light else 0.42))

    mask = Image.new("L", (bw, bh), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=max(8, min(bw, bh) // 6), fill=255)
    # 用圆角乘进 alpha 再合成，避免 paste+L 遮罩把透明区糊成黑底板
    r, g, b, a = layer.split()
    layer = Image.merge("RGBA", (r, g, b, ImageChops.multiply(a, mask)))
    img.alpha_composite(layer, (x0, y0))
