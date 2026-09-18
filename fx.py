"""程序化皮肤特效：国旗（国庆皮）与霓虹流光 HUD。全部按帧绘制，不依赖生图。"""
from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter

FLAG_RED = (222, 41, 16)
FLAG_GOLD = (255, 222, 0)

_FLAG_CACHE: dict[int, Image.Image] = {}
_SCAN_CACHE: dict[tuple[int, int], Image.Image] = {}


# ---------------------------------------------------------------- 国旗

def _star_points(cx: float, cy: float, r: float, point_deg: float) -> list[tuple[float, float]]:
    """五角星顶点；point_deg 为第一个角的指向（屏幕坐标，-90 为正上）。"""
    inner = r * 0.382
    pts: list[tuple[float, float]] = []
    for i in range(10):
        ang = math.radians(point_deg + i * 36.0)
        rr = r if i % 2 == 0 else inner
        pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
    return pts


def flag_image(width: int) -> Image.Image:
    """按《国旗法》附图几何生成 3:2 国旗（4 倍超采样再缩小抗锯齿）。"""
    width = max(12, int(width))
    got = _FLAG_CACHE.get(width)
    if got is not None:
        return got
    ss = 4
    w = width * ss
    h = int(round(w * 2 / 3))
    u = w / 30.0
    im = Image.new("RGBA", (w, h), (*FLAG_RED, 255))
    d = ImageDraw.Draw(im)
    bx, by = 5 * u, 5 * u
    d.polygon(_star_points(bx, by, 3 * u, -90.0), fill=(*FLAG_GOLD, 255))
    for gx, gy in ((10, 2), (12, 4), (12, 7), (10, 9)):
        cx, cy = gx * u, gy * u
        ang = math.degrees(math.atan2(by - cy, bx - cx))
        d.polygon(_star_points(cx, cy, 1 * u, ang), fill=(*FLAG_GOLD, 255))
    out = im.resize((width, int(round(width * 2 / 3))), Image.Resampling.LANCZOS)
    if len(_FLAG_CACHE) > 8:
        _FLAG_CACHE.clear()
    _FLAG_CACHE[width] = out
    return out


def paint_flag(
    layer: Image.Image,
    phase: float,
    *,
    x: int,
    y: int,
    width: int,
    slow: bool = False,
) -> None:
    """在 (x, y) 处画一面飘动的国旗，左侧带旗杆。宽 width，高自动 2/3。"""
    flag = flag_image(width)
    fw, fh = flag.size
    amp = max(1.0, fh * 0.075)
    speed = 1.6 if slow else 3.2
    strip = 2
    canvas_h = fh + int(amp * 2) + 2
    out = Image.new("RGBA", (fw, canvas_h), (0, 0, 0, 0))
    # 逐列条带上下错位 → 波浪；旗杆一侧振幅小、外沿大
    for sx in range(0, fw, strip):
        k = sx / max(1.0, fw)
        dy = math.sin(k * 6.9 - phase * speed) * amp * (0.25 + 0.75 * k)
        col = flag.crop((sx, 0, min(fw, sx + strip), fh))
        out.paste(col, (sx, int(round(amp + 1 + dy))))
    # 光影：沿波形明暗，模拟布面褶皱
    shade = Image.new("L", (fw, 1))
    vals = []
    for sx in range(fw):
        k = sx / max(1.0, fw)
        s = math.cos(k * 6.9 - phase * speed + 0.6) * (0.25 + 0.75 * k)
        vals.append(int(max(0, min(255, 214 + 41 * s))))
    shade.putdata(vals)
    shade = shade.resize((fw, canvas_h), Image.Resampling.NEAREST)
    r, g, b, a = out.split()
    out = Image.merge(
        "RGBA",
        (
            ImageChops.multiply(r, shade).point(lambda v: min(255, int(v * 1.19))),
            ImageChops.multiply(g, shade).point(lambda v: min(255, int(v * 1.19))),
            ImageChops.multiply(b, shade).point(lambda v: min(255, int(v * 1.19))),
            a,
        ),
    )
    # 投影 + 旗杆
    fxl = Image.new("RGBA", layer.size, (0, 0, 0, 0))
    d = ImageDraw.Draw(fxl)
    shadow = Image.new("RGBA", out.size, (0, 0, 0, 0))
    shadow.paste((40, 0, 0, 110), (0, 0, out.width, out.height), out.getchannel("A"))
    fxl.alpha_composite(shadow, (x + 1, y + 2 - int(amp)))
    pole_x = x - 2
    d.line((pole_x, y - 3, pole_x, y + fh + int(fh * 0.35)), fill=(232, 196, 96, 235), width=2)
    d.ellipse((pole_x - 2, y - 6, pole_x + 2, y - 2), fill=(255, 226, 120, 255))
    fxl.alpha_composite(out, (x, y - int(amp) - 1))
    layer.alpha_composite(fxl)


# ---------------------------------------------------------------- 霓虹流光 HUD

def _stage_palette(stage: str) -> tuple[tuple[int, int, int], tuple[int, int, int], float, float]:
    """(主色, 副色, 绕行周期秒, 亮度)"""
    if stage == "warn":
        return (255, 150, 40), (255, 64, 72), 3.6, 1.0
    if stage == "done":
        return (90, 255, 170), (120, 255, 210), 14.0, 0.9
    if stage == "idle":
        return (0, 220, 255), (255, 60, 200), 16.0, 0.6
    return (0, 232, 255), (255, 60, 200), 9.0, 1.0


def _perimeter(bw: int, bh: int, r: float, inset: float):
    """圆角矩形周长参数化：返回 (总长, point(u) 函数)。"""
    x0, y0, x1, y1 = inset, inset, bw - 1 - inset, bh - 1 - inset
    r = max(1.0, min(r - inset, (x1 - x0) / 2, (y1 - y0) / 2))
    sw, sh = (x1 - x0) - 2 * r, (y1 - y0) - 2 * r
    arc = math.pi * r / 2
    segs = [
        ("line", sw, (x0 + r, y0), (1, 0)),
        ("arc", arc, (x1 - r, y0 + r), -90.0),
        ("line", sh, (x1, y0 + r), (0, 1)),
        ("arc", arc, (x1 - r, y1 - r), 0.0),
        ("line", sw, (x1 - r, y1), (-1, 0)),
        ("arc", arc, (x0 + r, y1 - r), 90.0),
        ("line", sh, (x0, y1 - r), (0, -1)),
        ("arc", arc, (x0 + r, y0 + r), 180.0),
    ]
    total = sum(s[1] for s in segs)

    def point(u: float) -> tuple[float, float]:
        dist = (u % 1.0) * total
        for idx, (kind, ln, a, b) in enumerate(segs):
            if dist <= ln or idx == len(segs) - 1:
                if kind == "line":
                    return a[0] + b[0] * min(dist, ln), a[1] + b[1] * min(dist, ln)
                ang = math.radians(b) + (min(dist, ln) / max(1e-6, ln)) * (math.pi / 2)
                return a[0] + math.cos(ang) * r, a[1] + math.sin(ang) * r
            dist -= ln
        return segs[0][2]

    return total, point


def _scanlines(bw: int, bh: int) -> Image.Image:
    key = (bw, bh)
    got = _SCAN_CACHE.get(key)
    if got is not None:
        return got
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for y in range(0, bh, 3):
        d.line((0, y, bw, y), fill=(0, 0, 0, 46))
    for x in range(0, bw, 24):
        d.line((x, 0, x, bh), fill=(120, 200, 255, 9))
    if len(_SCAN_CACHE) > 8:
        _SCAN_CACHE.clear()
    _SCAN_CACHE[key] = im
    return im


def paint_neonflow(layer: Image.Image, phase: float, *, stage: str, radius: int) -> None:
    """霓虹 HUD：扫描线 + 角标 + 绕边流光（双头、拖尾、泛光）+ 偶发故障错位。"""
    bw, bh = layer.size
    if bw < 40 or bh < 20:
        return
    c1, c2, period, gain = _stage_palette(stage)
    scale = max(0.7, min(2.4, bh / 92.0))
    layer.alpha_composite(_scanlines(bw, bh))

    d = ImageDraw.Draw(layer)
    # 四角 HUD 角标
    ln = int(max(8, bw * 0.07))
    inset = int(6 * scale)
    wdt = max(1, int(round(1.6 * scale)))
    ca = int(200 * gain)
    for (cx, cy, sx, sy) in ((inset, inset, 1, 1), (bw - 1 - inset, inset, -1, 1), (inset, bh - 1 - inset, 1, -1), (bw - 1 - inset, bh - 1 - inset, -1, -1)):
        col = (*c1, ca) if (sx == sy) else (*c2, ca)
        d.line((cx, cy, cx + sx * ln, cy), fill=col, width=wdt)
        d.line((cx, cy, cx, cy + sy * ln), fill=col, width=wdt)

    # 绕边流光
    total, point = _perimeter(bw, bh, float(radius), 1.5)
    glow = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    core = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    kd = ImageDraw.Draw(core)
    head = (phase / period) % 1.0
    n_tail = 22
    spacing = (0.11 if stage != "warn" else 0.14) / n_tail
    heads = ((head, c1), ((head + 0.5) % 1.0, c2)) if stage != "done" else ((head, c1),)
    for hu, col in heads:
        for k in range(n_tail):
            u = hu - k * spacing
            f = 1.0 - k / n_tail
            px, py = point(u)
            ga = int(150 * gain * f * f)
            gr = (3.2 + 4.5 * f) * scale
            if ga > 3:
                gd.ellipse((px - gr, py - gr, px + gr, py + gr), fill=(*col, ga))
            cr = (0.7 + 1.5 * f) * scale
            ka = int(255 * gain * (0.35 + 0.65 * f))
            kc = (255, 255, 255) if k == 0 else col
            kd.ellipse((px - cr, py - cr, px + cr, py + cr), fill=(*kc, ka))
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(2.0, 3.0 * scale)))
    layer.alpha_composite(glow)
    layer.alpha_composite(core)

    # 故障：每 ~7s 闯入 2~3 帧，几条横带错位 + 通道分离
    cyc = 7.3 if stage != "warn" else 3.1
    g = phase % cyc
    if g < 0.09 and stage != "done":
        seed = int(phase / cyc) * 7919
        for i in range(3):
            s = (seed + i * 104729) & 0xFFFF
            y = int((s % 97) / 97.0 * (bh - 8))
            h = 3 + (s >> 5) % max(3, int(bh * 0.1))
            dx = ((s >> 9) % 13 - 6) * max(1, int(scale))
            if dx == 0:
                dx = 4
            band = layer.crop((0, y, bw, y + h))
            layer.paste(band, (dx, y), band)
            tint = Image.new("RGBA", band.size, (*c2, 70))
            layer.paste(tint, (dx + 2, y), band)
