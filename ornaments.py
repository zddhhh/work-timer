"""皮肤生图贴图等装饰。"""
from __future__ import annotations

import time
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

import store

_ASSET_CACHE: dict[str, Image.Image] = {}
# (asset_name, tw, th) -> resized RGBA
_RESIZE_CACHE: dict[tuple[str, int, int], Image.Image] = {}

# kind -> (主贴图, 可选第二层)；淡影(ghost)不用生图
_SKIN_LAYERS: dict[str, tuple[str, str | None]] = {
    "glass": ("skin_glass.png", None),
    "frost": ("skin_frost.png", None),
    "neon": ("skin_neon.png", None),
    "terminal": ("skin_terminal.png", None),
    "aurora": ("aurora_drape.png", "aurora_glow.png"),
    "inkgold": ("skin_inkgold.png", None),
    "warmglow": ("skin_warmglow.png", None),
}


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


def _resized(name: str, src: Image.Image, tw: int, th: int) -> Image.Image:
    key = (name, tw, th)
    got = _RESIZE_CACHE.get(key)
    if got is not None:
        return got
    out = src.resize((tw, th), Image.Resampling.LANCZOS)
    # 只留最近几档，避免拖放缩放时缓存膨胀
    if len(_RESIZE_CACHE) > 24:
        _RESIZE_CACHE.clear()
    _RESIZE_CACHE[key] = out
    return out


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


def has_skin(kind: str) -> bool:
    return kind in _SKIN_LAYERS


def paste_skin(
    img: Image.Image,
    box: tuple[int, int, int, int],
    kind: str,
    *,
    light: bool = False,
) -> bool:
    """把对应皮肤的生图贴进圆角区域；成功返回 True。"""
    layers = _SKIN_LAYERS.get(kind)
    if layers is None:
        return False
    name_a, name_b = layers
    drape = load_asset(name_a)
    glow = load_asset(name_b) if name_b else None
    if drape is None and glow is None:
        return False

    x0, y0, x1, y1 = box
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    phase = time.monotonic()
    layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))

    # 整块纹理皮略淡一点，避免压字；霓虹/终端/极光提亮一点
    glow_kinds = {"neon", "terminal", "aurora"}
    if kind in glow_kinds:
        a0 = 0.90 if not light else 0.55
        a1 = 0.72 if not light else 0.40
    else:
        a0 = 0.82 if not light else 0.62
        a1 = 0.55 if not light else 0.38

    if drape is not None:
        tw = max(bw + 80, drape.width)
        th = max(bh, drape.height)
        src = _resized(name_a, drape, tw, th)
        ox = int((phase * 28) % max(1, src.width - bw))
        oy = max(0, (src.height - bh) // 2)
        crop = src.crop((ox, oy, ox + bw, oy + bh))
        layer = Image.alpha_composite(layer, _scale_alpha(crop, a0))
    if glow is not None:
        tw = max(bw + 60, glow.width)
        th = max(bh, glow.height)
        src = _resized(name_b or "glow", glow, tw, th)
        ox = int((phase * -22) % max(1, src.width - bw))
        oy = max(0, (src.height - bh) // 2)
        crop = src.crop((ox, oy, ox + bw, oy + bh))
        layer = Image.alpha_composite(layer, _scale_alpha(crop, a1))

    mask = Image.new("L", (bw, bh), 0)
    md = ImageDraw.Draw(mask)
    md.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=max(8, min(bw, bh) // 6), fill=255)
    r, g, b, a = layer.split()
    layer = Image.merge("RGBA", (r, g, b, ImageChops.multiply(a, mask)))
    img.alpha_composite(layer, (x0, y0))
    return True


def paste_aurora(img: Image.Image, box: tuple[int, int, int, int], *, light: bool = False) -> None:
    """兼容旧调用。"""
    paste_skin(img, box, "aurora", light=light)


def paint_chevron(
    img: Image.Image,
    w: int,
    h: int,
    *,
    color: tuple[int, int, int, int] = (255, 255, 255, 70),
    pin_dots: tuple[int, int] = (0, 0),
) -> None:
    """主卡片底部淡淡下拉箭头；可选轮播小点。"""
    d = ImageDraw.Draw(img)
    cx = w // 2
    y0 = h - 14
    d.line((cx - 6, y0, cx, y0 + 5), fill=color, width=1)
    d.line((cx, y0 + 5, cx + 6, y0), fill=color, width=1)
    idx, total = pin_dots
    if total >= 2 and idx >= 1:
        span = (total - 1) * 8
        x0 = cx - span // 2
        for i in range(total):
            x = x0 + i * 8
            fill = (color[0], color[1], color[2], 160 if i + 1 == idx else 50)
            d.ellipse((x - 2, h - 8, x + 2, h - 4), fill=fill)
