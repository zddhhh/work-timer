"""皮肤生图贴图等装饰。"""
from __future__ import annotations

import math
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


def _orbit_xy(
    phase: float,
    span_x: int,
    span_y: int,
    *,
    speed: float,
    twist: float = 0.0,
) -> tuple[int, int]:
    """在大图上缓缓绕圈，避免 ping-pong 走到头急刹。"""
    sx, sy = max(0, int(span_x)), max(0, int(span_y))
    t = float(phase) * speed + twist
    ox = int((math.sin(t) * 0.5 + 0.5) * sx)
    oy = int((math.cos(t * 0.91 + 0.8) * 0.5 + 0.5) * sy)
    return max(0, min(sx, ox)), max(0, min(sy, oy))


def _breathe(phase: float, alpha: float, *, amp: float = 0.06, speed: float = 0.55) -> float:
    k = 1.0 + amp * math.sin(float(phase) * speed)
    return max(0.0, min(1.0, float(alpha) * k))


def _mood_rgba(stage: str, light: bool) -> tuple[int, int, int, int]:
    a = 24 if light else 32
    if stage == "warn":
        return (255, 168, 72, a + 8)
    if stage == "done":
        return (255, 214, 140, a + 12)
    if stage == "idle":
        return (168, 176, 186, max(14, a - 8))
    return (148, 186, 224, a)


def _mix_env(
    mood: tuple[int, int, int, int],
    env: tuple[int, int, int] | None,
    *,
    weight: float = 0.32,
) -> tuple[int, int, int, int]:
    if env is None:
        return mood
    w = max(0.0, min(0.5, float(weight)))
    r = int(mood[0] * (1 - w) + env[0] * w)
    g = int(mood[1] * (1 - w) + env[1] * w)
    b = int(mood[2] * (1 - w) + env[2] * w)
    return (max(0, min(255, r)), max(0, min(255, g)), max(0, min(255, b)), mood[3])


def _paint_sweep(layer: Image.Image, phase: float, *, light: bool, stage: str) -> None:
    period = 11.0 if stage == "warn" else (20.0 if stage == "done" else 15.5)
    dur = 1.65
    t = float(phase) % period
    if t > dur:
        return
    u = t / dur
    fade = min(u, 1.0 - u) * 2.4
    fade = max(0.0, min(1.0, fade))
    bw, bh = layer.size
    sw = max(10, bw // 7)
    travel = bw + sw * 2 + bh // 3
    x = int(-sw + u * travel)
    stripe = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(stripe)
    alpha = int((36 if light else 30) * fade)
    col = (255, 252, 244, alpha)
    shear = max(10, bh // 3)
    d.polygon(
        [(x, 0), (x + sw, 0), (x + sw - shear, bh), (x - shear, bh)],
        fill=col,
    )
    layer.alpha_composite(stripe)


def paste_skin(
    img: Image.Image,
    box: tuple[int, int, int, int],
    kind: str,
    *,
    light: bool = False,
    stage: str = "run",
    env_rgb: tuple[int, int, int] | None = None,
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
    freeze = stage in ("idle", "done")
    extra = 0 if freeze else 22

    glow_kinds = {"neon", "terminal", "aurora"}
    if kind in glow_kinds:
        a0 = 0.90 if not light else 0.55
        a1 = 0.72 if not light else 0.40
    elif kind == "warmglow":
        a0 = 0.88 if not light else 0.92
        a1 = 0.60 if not light else 0.70
    else:
        a0 = 0.82 if not light else 0.62
        a1 = 0.55 if not light else 0.38
    bamp = 0.0 if freeze else (0.04 if stage == "warn" else 0.03)

    def _place(src_im: Image.Image, name: str, alpha: float, *, speed: float, twist: float) -> None:
        nonlocal layer
        tw = max(bw + extra, src_im.width)
        th = max(bh + extra, src_im.height)
        src = _resized(name, src_im, tw, th)
        sx, sy = max(0, src.width - bw), max(0, src.height - bh)
        if freeze or extra <= 0:
            ox, oy = sx // 2, sy // 2
        else:
            ox, oy = _orbit_xy(phase, sx, sy, speed=speed, twist=twist)
        crop = src.crop((ox, oy, ox + bw, oy + bh))
        layer = Image.alpha_composite(layer, _scale_alpha(crop, _breathe(phase, alpha, amp=bamp)))

    if drape is not None:
        _place(drape, name_a, a0, speed=0.05, twist=0.0)
    if glow is not None:
        _place(glow, name_b or "glow", a1, speed=0.04, twist=1.7)

    tint = Image.new("RGBA", (bw, bh), _mix_env(_mood_rgba(stage, light), env_rgb))
    layer = Image.alpha_composite(layer, tint)
    _paint_sweep(layer, phase, light=light, stage=stage)

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


def chevron_hit(lx: int, ly: int, w: int, h: int) -> bool:
    """仅倒三角附近可点，不是整条底边。"""
    cx = w // 2
    return abs(lx - cx) <= 12 and h - 18 <= ly <= h - 4


def paint_chevron(
    img: Image.Image,
    w: int,
    h: int,
    *,
    color: tuple[int, int, int, int] = (255, 255, 255, 90),
    pin_dots: tuple[int, int] = (0, 0),
    opened: bool = False,
) -> None:
    """主卡片底部只画淡倒三角；列表打开时朝上表示可收回。"""
    d = ImageDraw.Draw(img)
    cx = w // 2
    y0 = h - 13
    arrow = (color[0], color[1], color[2], min(130, max(70, color[3])))
    if opened:
        d.polygon([(cx - 7, y0 + 6), (cx + 7, y0 + 6), (cx, y0)], fill=arrow)
    else:
        d.polygon([(cx - 7, y0), (cx + 7, y0), (cx, y0 + 6)], fill=arrow)
    idx, total = pin_dots
    if total >= 2 and idx >= 1:
        span = (total - 1) * 7
        x0 = w - 12 - span
        for i in range(total):
            x = x0 + i * 7
            fill = (color[0], color[1], color[2], 150 if i + 1 == idx else 45)
            d.ellipse((x - 1, h - 10, x + 2, h - 7), fill=fill)
