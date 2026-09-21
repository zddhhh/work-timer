"""皮肤生图贴图等装饰。"""
from __future__ import annotations

import math
import time
from collections import OrderedDict
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

import fx
import store

_ASSET_CACHE: dict[str, Image.Image] = {}
# (asset_name, tw, th) -> resized RGBA，LRU
_RESIZE_CACHE: OrderedDict[tuple[str, int, int], Image.Image] = OrderedDict()
_MASK_CACHE: dict[tuple[int, int, int], Image.Image] = {}
_ALPHA_LUT: dict[int, list[int]] = {}
# 贴图只在画面中心附近漂移，避免整张 640×360 慢扫导致「停一下跳一格」
_DRIFT_PX = 16

# kind -> (主贴图, 可选第二层)；淡影(ghost)不用生图
_SKIN_LAYERS: dict[str, tuple[str, str | None]] = {
    "glass": ("skin_glass.png", None),
    "frost": ("skin_frost.png", None),
    "neon": ("skin_neon.png", None),
    "terminal": ("skin_terminal.png", None),
    "aurora": ("aurora_drape.png", "aurora_glow.png"),
    "inkgold": ("skin_inkgold.png", None),
    "warmglow": ("skin_warmglow.png", None),
    "midautumn": ("skin_midautumn.png", "skin_midautumn_glow.png"),
    "nationalday": ("skin_nationalday.png", "skin_nationalday_glow.png"),
}
# 不用生图、逐帧程序化绘制的皮
_PROC_KINDS = frozenset({"neonflow", "inkpulse", "thunder"})


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
        _RESIZE_CACHE.move_to_end(key)
        return got
    out = src.resize((tw, th), Image.Resampling.LANCZOS)
    # LRU 只留最近几档，避免拖放缩放时缓存膨胀；不整表清空，免得当前皮的两层贴图被一起丢掉
    while len(_RESIZE_CACHE) >= 24:
        _RESIZE_CACHE.popitem(last=False)
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
    f = max(0.0, min(1.0, float(factor)))
    if f >= 0.998:
        return im
    key = int(round(f * 256))
    lut = _ALPHA_LUT.get(key)
    if lut is None:
        lut = [min(255, (i * key) >> 8) for i in range(256)]
        _ALPHA_LUT[key] = lut
    out = im.copy()
    out.putalpha(out.getchannel("A").point(lut))
    return out


def has_skin(kind: str) -> bool:
    return kind in _SKIN_LAYERS or kind in _PROC_KINDS


def _orbit_xy(
    phase: float,
    span_x: float,
    span_y: float,
    *,
    speed: float,
    twist: float = 0.0,
) -> tuple[float, float]:
    """中心附近缓绕；返回浮点偏移，交给亚像素采样。"""
    sx, sy = max(0.0, float(span_x)), max(0.0, float(span_y))
    t = float(phase) * speed + twist
    ox = (math.sin(t) * 0.5 + 0.5) * sx
    oy = (math.cos(t * 0.91 + 0.8) * 0.5 + 0.5) * sy
    return ox, oy


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
    dur = 1.9
    t = float(phase) % period
    if t > dur:
        return
    u = t / dur
    u = u * u * (3.0 - 2.0 * u)
    fade = math.sin(u * math.pi)
    fade = max(0.0, min(1.0, fade))
    bw, bh = layer.size
    sw = max(12, bw // 6)
    travel = bw + sw * 2 + bh // 3
    x = -sw + u * travel
    stripe = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(stripe)
    shear = max(10, bh // 3)
    peak = 34 if light else 28
    for k, mul in ((0, 1.0), (sw * 0.28, 0.45), (sw * 0.55, 0.18)):
        a = int(peak * fade * mul)
        if a < 2:
            continue
        x0 = x - k
        ww = sw + k * 2
        d.polygon(
            [(x0, 0), (x0 + ww, 0), (x0 + ww - shear, bh), (x0 - shear, bh)],
            fill=(255, 252, 244, a),
        )
    layer.alpha_composite(stripe)


def _ember_seed(i: int) -> tuple[float, float, float, float, float]:
    """按序号生成稳定的火星参数：x、y、闪烁速度、相位、上升速度。"""
    s = (i * 2654435761) & 0xFFFFFFFF
    vals: list[float] = []
    for _ in range(5):
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        vals.append((s >> 8) / float(1 << 23))
    x, y, sp, ph, rise = vals
    return 0.34 + x * 0.64, y, 0.9 + sp * 1.6, ph * 6.2832, 0.010 + rise * 0.022


def _burst(phase: float, period: float = 9.0, width: float = 0.9) -> float:
    """周期性的一下「炸开」亮度包络，0~1。"""
    t = float(phase) % period
    return math.exp(-(t / width) ** 2)


def _paint_embers(layer: Image.Image, phase: float, *, light: bool, stage: str, count: int = 16) -> None:
    """国庆皮：金红火星在右侧缓缓上浮、忽明忽暗，让静态花火活起来。

    画在独立透明层再合成：ImageDraw 直接画 RGBA 是覆盖像素，会把底图抠出洞。
    """
    bw, bh = layer.size
    if bw < 60 or bh < 30:
        return
    slow = stage in ("idle", "done")
    spark = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(spark)
    burst = _burst(phase)
    gain = 0.7 if light else 1.0
    scale = max(0.8, min(2.2, bh / 92.0))
    for i in range(count):
        x0, y0, sp, ph, rise = _ember_seed(i)
        if slow:
            sp *= 0.55
            rise *= 0.4
        tw = math.sin(float(phase) * sp + ph)
        tw = max(0.0, tw) ** 2.4
        a = (0.15 + 0.85 * tw) * (0.65 + 0.55 * burst) * gain
        if a < 0.06:
            continue
        y = (y0 - float(phase) * rise) % 1.0
        px = x0 * bw
        py = 0.04 * bh + y * bh * 0.92
        gold = i % 3 != 1
        rgb = (255, 222, 140) if gold else (255, 132, 84)
        r = (0.6 + 0.8 * tw + (0.4 if i % 5 == 0 else 0.0)) * scale
        halo = r * 3.0
        ha = int(min(255, 44 * a))
        if ha > 2:
            d.ellipse((px - halo, py - halo, px + halo, py + halo), fill=(*rgb, ha))
        ca = int(min(255, 210 * a))
        d.ellipse((px - r, py - r, px + r, py + r), fill=(*rgb, ca))
    layer.alpha_composite(spark)


BITE_SEC = fx.BITE_SEC
MAX_THUNDER_HITS = fx.MAX_THUNDER_HITS
register_thunder_hit = fx.register_thunder_hit
thunder_fps = fx.thunder_fps


def paint_bite(
    img: Image.Image,
    box: tuple[int, int, int, int],
    t: float,
    *,
    stage: str = "run",
    light: bool = False,
    radius: int = 0,
    cx: int | None = None,
    cy: int | None = None,
    power: float = 1.0,
) -> None:
    """点一下：劈雷→沿边电涌绕一圈。画在文字之上，吃圆角蒙版。"""
    x0, y0, x1, y1 = box
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    fx.paint_thunder_click(
        layer,
        t,
        cx if cx is not None else bw // 2,
        cy if cy is not None else bh // 2,
        stage=stage,
        light=light,
        radius=int(radius),
        power=power,
    )
    img.alpha_composite(_round_mask(layer, radius), (x0, y0))


def paint_thunder_quote(
    img: Image.Image,
    box: tuple[int, int, int, int],
    t: float,
    quote_idx: int,
    font,
    *,
    stage: str = "run",
    light: bool = False,
    radius: int = 0,
) -> None:
    """霹雳狂潮点击台词，画在雷效之上。"""
    x0, y0, x1, y1 = box
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    fx.paint_thunder_quote(layer, t, quote_idx, font, stage=stage, light=light)
    img.alpha_composite(_round_mask(layer, radius), (x0, y0))


def paste_skin(
    img: Image.Image,
    box: tuple[int, int, int, int],
    kind: str,
    *,
    light: bool = False,
    stage: str = "run",
    env_rgb: tuple[int, int, int] | None = None,
    radius: int = 0,
) -> bool:
    """把对应皮肤的生图贴进圆角卡片（含四个圆角弧）；程序化皮直接按帧画。"""
    x0, y0, x1, y1 = box
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    phase = time.monotonic()

    if kind in _PROC_KINDS:
        layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        if kind == "neonflow":
            fx.paint_neonflow(layer, phase, stage=stage, radius=int(radius), light=light)
        elif kind == "inkpulse":
            fx.paint_inkpulse(layer, phase, stage=stage, radius=int(radius), light=light)
        elif kind == "thunder":
            fx.paint_thunder(layer, phase, stage=stage, radius=int(radius), light=light)
        img.alpha_composite(_round_mask(layer, radius), (x0, y0))
        return True

    layers = _SKIN_LAYERS.get(kind)
    if layers is None:
        return False
    name_a, name_b = layers
    drape = load_asset(name_a)
    glow = load_asset(name_b) if name_b else None
    if drape is None and glow is None:
        return False

    layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    freeze = stage in ("idle", "done")
    drift = 0 if freeze else _DRIFT_PX
    if kind == "midautumn" and not freeze:
        drift = 8
    elif kind == "nationalday" and not freeze:
        drift = 12

    # 每皮单独调叠层：深底要透桌面；浅底托住深色字；夜景/红绸保持氛围并加浓 scrim
    if kind == "neon":
        a0, a1 = (0.68, 0.55) if not light else (0.36, 0.28)
    elif kind == "terminal":
        a0, a1 = (0.74, 0.58) if not light else (0.40, 0.30)
    elif kind == "aurora":
        a0, a1 = (0.72, 0.58) if not light else (0.38, 0.32)
    elif kind == "warmglow":
        # 暖光要实：奶油底托住暖色纹理，浅墙纸也不要透得太狠
        a0, a1 = (0.92, 0.65) if not light else (0.90, 0.72)
    elif kind == "midautumn":
        a0, a1 = (0.82, 0.42) if not light else (0.70, 0.34)
    elif kind == "nationalday":
        burst = 1.0 + 0.55 * _burst(phase)
        a0 = 0.62 if not light else 0.55
        a1 = (0.40 if not light else 0.32) * burst
    elif kind == "frost":
        a0, a1 = (0.76, 0.50) if not light else (0.48, 0.32)
    elif kind == "inkgold":
        a0, a1 = (0.78, 0.52) if not light else (0.46, 0.34)
    else:  # glass 等
        a0, a1 = (0.74, 0.48) if not light else (0.50, 0.34)
    bamp = 0.0 if freeze else (0.035 if stage == "warn" else 0.025)
    if kind == "nationalday" and not freeze:
        bamp = 0.05
    base_speed = 0.26 if stage == "warn" else 0.20

    def _place(src_im: Image.Image, name: str, alpha: float, *, speed: float, twist: float) -> None:
        nonlocal layer
        tw = max(bw + _DRIFT_PX * 2, src_im.width)
        th = max(bh + _DRIFT_PX * 2, src_im.height)
        src = _resized(name, src_im, tw, th)
        max_x = max(0.0, float(src.width - bw))
        max_y = max(0.0, float(src.height - bh))
        span_x = min(max_x, float(drift * 2)) if drift else 0.0
        span_y = min(max_y, float(drift * 2)) if drift else 0.0
        cx = max_x * 0.5
        cy = max_y * 0.5
        if span_x <= 0.0 and span_y <= 0.0:
            ox, oy = cx, cy
        else:
            fx, fy = _orbit_xy(phase, span_x, span_y, speed=speed, twist=twist)
            ox = cx - span_x * 0.5 + fx
            oy = cy - span_y * 0.5 + fy
        ox = max(0.0, min(max_x, ox))
        oy = max(0.0, min(max_y, oy))
        crop = src.transform(
            (bw, bh),
            Image.Transform.AFFINE,
            (1.0, 0.0, ox, 0.0, 1.0, oy),
            resample=Image.Resampling.BILINEAR,
        )
        layer = Image.alpha_composite(layer, _scale_alpha(crop, _breathe(phase, alpha, amp=bamp)))

    if drape is not None:
        _place(drape, name_a, a0, speed=base_speed, twist=0.0)
    if glow is not None:
        _place(glow, name_b or "glow", a1, speed=base_speed * 0.78, twist=1.7)

    if kind == "nationalday":
        # 海报式构图：光芒 / 飘带 / 天安门剪影 / 烟花 / 五星，全程序化画在红绸纹理上
        fx.paint_national(layer, phase, stage=stage, light=light)
        _paint_embers(layer, phase, light=light, stage=stage, count=6)
        # 红底不叠蓝灰情绪色，只留环境光
        mood = _mix_env((255, 176, 96, 18 if light else 22), env_rgb)
    else:
        mood = _mix_env(_mood_rgba(stage, light), env_rgb)
    tint = Image.new("RGBA", (bw, bh), mood)
    layer = Image.alpha_composite(layer, tint)
    _paint_sweep(layer, phase, light=light, stage=stage)
    img.alpha_composite(_round_mask(layer, radius), (x0, y0))
    return True


def _round_mask(layer: Image.Image, radius: int) -> Image.Image:
    """把图层的 alpha 裁成圆角矩形。"""
    rad = max(0, int(radius))
    if rad <= 0:
        return layer
    bw, bh = layer.size
    mk = (bw, bh, rad)
    mask = _MASK_CACHE.get(mk)
    if mask is None:
        mask = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, bw - 1, bh - 1), radius=rad, fill=255)
        if len(_MASK_CACHE) > 16:
            _MASK_CACHE.clear()
        _MASK_CACHE[mk] = mask
    r, g, b, a = layer.split()
    return Image.merge("RGBA", (r, g, b, ImageChops.multiply(a, mask)))


CONFETTI_SEC = 2.8
_CONFETTI_COLORS = (
    (255, 92, 108),
    (255, 200, 64),
    (72, 214, 190),
    (96, 160, 255),
    (255, 140, 200),
    (250, 250, 250),
)


def is_animated(kind: str) -> bool:
    """需要按帧重绘的皮。"""
    return has_skin(kind)


def _confetti_seed(i: int) -> tuple[float, ...]:
    s = (i * 3266489917 + 7) & 0xFFFFFFFF
    out: list[float] = []
    for _ in range(6):
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        out.append((s >> 8) / float(1 << 23))
    return tuple(out)


def paint_confetti(img: Image.Image, w: int, h: int, t: float, *, count: int = 42) -> None:
    """到点庆祝：左右两角各一炮纸屑向内上抛，受重力落下、边翻边淡出。t 为开始后秒数。"""
    if t < 0.0 or t > CONFETTI_SEC or w < 60 or h < 30:
        return
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(layer)
    scale = max(0.7, min(2.4, h / 92.0))
    g = 150.0 * scale
    fade = 1.0 if t < CONFETTI_SEC - 0.7 else max(0.0, (CONFETTI_SEC - t) / 0.7)
    for i in range(count):
        r_side, r_ang, r_speed, r_spin, r_size, r_delay = _confetti_seed(i)
        delay = r_delay * 0.35
        tt = t - delay
        if tt <= 0.0:
            continue
        left = r_side < 0.5
        sx = (0.08 if left else 0.92) * w
        sy = h * 0.96
        ang = math.radians((62 + r_ang * 40) if left else (118 - r_ang * 40))
        sp = (150 + r_speed * 130) * scale
        vx, vy = math.cos(ang) * sp, -math.sin(ang) * sp
        x = sx + vx * tt * (1.0 - 0.18 * tt)
        y = sy + vy * tt + 0.5 * g * tt * tt
        if y > h + 8 or x < -8 or x > w + 8:
            continue
        rot = r_spin * 6.283 + tt * (4.0 + r_spin * 6.0) * (1 if i % 2 else -1)
        lw = (1.7 + r_size * 1.9) * scale
        lh = lw * (1.6 + r_size)
        # 「翻转」：宽随余弦变化，像一片纸在转
        flip = abs(math.cos(tt * (5.0 + r_spin * 4.0) + r_ang * 3.0))
        lw2 = max(0.6, lw * (0.25 + 0.75 * flip))
        c, s = math.cos(rot), math.sin(rot)
        pts = []
        for px, py in ((-lw2, -lh), (lw2, -lh), (lw2, lh), (-lw2, lh)):
            pts.append((x + px * c - py * s, y + px * s + py * c))
        rgb = _CONFETTI_COLORS[i % len(_CONFETTI_COLORS)]
        d.polygon(pts, fill=(*rgb, int(235 * fade)))
    img.alpha_composite(layer)


def paste_aurora(img: Image.Image, box: tuple[int, int, int, int], *, light: bool = False) -> None:
    """兼容旧调用。"""
    paste_skin(img, box, "aurora", light=light)


def paint_pin_dots(
    img: Image.Image,
    w: int,
    h: int,
    *,
    color: tuple[int, int, int, int] = (255, 255, 255, 90),
    pin_dots: tuple[int, int] = (0, 0),
) -> None:
    """多条优先日程时，右下角画当前是第几条。"""
    idx, total = pin_dots
    if total < 2 or idx < 1:
        return
    d = ImageDraw.Draw(img)
    span = (total - 1) * 7
    x0 = w - 12 - span
    for i in range(total):
        x = x0 + i * 7
        fill = (color[0], color[1], color[2], 150 if i + 1 == idx else 45)
        d.ellipse((x - 1, h - 10, x + 2, h - 7), fill=fill)
