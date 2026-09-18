"""程序化皮肤特效：国旗星组（国庆皮）与霓虹流光 HUD。全部按帧绘制，不依赖生图。"""
from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter

FLAG_RED = (222, 41, 16)
FLAG_GOLD = (255, 222, 0)

_CANTON_CACHE: dict[int, tuple[Image.Image, Image.Image, Image.Image]] = {}
_SCAN_CACHE: dict[tuple, Image.Image] = {}


# ---------------------------------------------------------------- 国旗星组

def _star_points(cx: float, cy: float, r: float, point_deg: float) -> list[tuple[float, float]]:
    """五角星顶点；point_deg 为第一个角的指向（屏幕坐标，-90 为正上）。"""
    inner = r * 0.382
    pts: list[tuple[float, float]] = []
    for i in range(10):
        ang = math.radians(point_deg + i * 36.0)
        rr = r if i % 2 == 0 else inner
        pts.append((cx + math.cos(ang) * rr, cy + math.sin(ang) * rr))
    return pts


def canton(unit: float) -> tuple[Image.Image, Image.Image, Image.Image]:
    """国旗左上角「一大四小」星组，按《国旗法》附图几何：大星心 (5,5) 半径 3，
    小星心 (10,2)(12,4)(12,7)(10,9) 半径 1、各有一角指向大星心。unit = 像素/格，
    画布覆盖格坐标 x∈[0,15]、y∈[0,11]，4 倍超采样。返回 (星, 泛光, 星 alpha 蒙版)。"""
    key = int(round(unit * 10))
    got = _CANTON_CACHE.get(key)
    if got is not None:
        return got
    ss = 4
    u = unit * ss
    w, h = max(ss, int(round(15 * u))), max(ss, int(round(11 * u)))
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    bx, by = 5 * u, 5 * u
    d.polygon(_star_points(bx, by, 3 * u, -90.0), fill=(*FLAG_GOLD, 255))
    for gx, gy in ((10, 2), (12, 4), (12, 7), (10, 9)):
        cx, cy = gx * u, gy * u
        ang = math.degrees(math.atan2(by - cy, bx - cx))
        d.polygon(_star_points(cx, cy, 1 * u, ang), fill=(*FLAG_GOLD, 255))
    stars = im.resize((max(1, w // ss), max(1, h // ss)), Image.Resampling.LANCZOS)
    mask = stars.getchannel("A")
    glow = Image.new("RGBA", stars.size, (0, 0, 0, 0))
    glow.paste((255, 214, 120, 255), (0, 0, *stars.size), mask)
    glow = glow.filter(ImageFilter.GaussianBlur(radius=max(2.0, unit * 0.9)))
    out = (stars, glow, mask)
    if len(_CANTON_CACHE) > 8:
        _CANTON_CACHE.clear()
    _CANTON_CACHE[key] = out
    return out


def flag_image(width: int) -> Image.Image:
    """完整 3:2 国旗（测试/预览用）。"""
    width = max(12, int(width))
    unit = width / 30.0
    im = Image.new("RGBA", (width, int(round(width * 2 / 3))), (*FLAG_RED, 255))
    stars, _, _ = canton(unit)
    im.alpha_composite(stars, (0, 0))
    return im


def paint_canton(
    layer: Image.Image,
    phase: float,
    *,
    unit: float,
    ox: int,
    oy: int,
    slow: bool = False,
) -> None:
    """把星组直接画进红底：暖金泛光呼吸 + 暗红压边（像绣在绸上）+ 定期掠过大星的高光。"""
    stars, glow, mask = canton(unit)
    sw, sh = stars.size
    breath = 0.72 + 0.28 * math.sin(phase * (0.8 if slow else 1.3))
    g = glow.copy()
    g.putalpha(g.getchannel("A").point(lambda v: int(v * 0.55 * breath)))
    layer.alpha_composite(g, (ox, oy))
    shadow = Image.new("RGBA", stars.size, (0, 0, 0, 0))
    shadow.paste((70, 4, 8, 120), (0, 0, sw, sh), mask)
    layer.alpha_composite(shadow, (ox + 1, oy + 1))
    layer.alpha_composite(stars, (ox, oy))
    # 高光：每隔几秒一道斜向亮带自左向右扫过大星
    period = 9.0 if slow else 5.5
    t = (phase % period) / period
    if t < 0.28:
        k = t / 0.28
        bx = 5 * unit + (k * 2 - 1) * 4.2 * unit
        streak = Image.new("RGBA", stars.size, (0, 0, 0, 0))
        hw = max(1.2, unit * 0.55)
        a = int(190 * math.sin(k * math.pi))
        ImageDraw.Draw(streak).polygon(
            [(bx - hw, sh), (bx + hw, sh), (bx + hw + sh * 0.7, 0), (bx - hw + sh * 0.7, 0)],
            fill=(255, 255, 240, a),
        )
        streak.putalpha(ImageChops.multiply(streak.getchannel("A"), mask))
        layer.alpha_composite(streak, (ox, oy))


_TIANANMEN_CACHE: dict[tuple[int, bool], Image.Image] = {}


def _tiananmen(height: int, light: bool) -> Image.Image:
    """天安门剪影（金色，自上而下渐淡）：城台五门洞 + 重檐歇山顶。按国庆海报常见画法简化。"""
    key = (int(height), bool(light))
    got = _TIANANMEN_CACHE.get(key)
    if got is not None:
        return got
    ss = 3
    H = max(12, int(height)) * ss
    W = int(H * 1.55)
    mask = Image.new("L", (W + 2 * ss, H + 2 * ss), 0)
    d = ImageDraw.Draw(mask)
    ox, oy = ss, ss
    cx = ox + W / 2

    def rect(x0, y0, x1, y1, v=255):
        d.rectangle((ox + x0 * W, oy + y0 * H, ox + x1 * W, oy + y1 * H), fill=v)

    def poly(pts, v=255):
        d.polygon([(cx + px * W, oy + py * H) for px, py in pts], fill=v)

    # 城台 + 女儿墙
    rect(0.0, 0.60, 1.0, 1.0)
    rect(-0.01, 0.565, 1.01, 0.60)
    # 五个门洞：中间最大
    for k, (pos, aw, ah) in enumerate(((0.0, 0.11, 0.30), (-0.2, 0.085, 0.24), (0.2, 0.085, 0.24), (-0.37, 0.075, 0.20), (0.37, 0.075, 0.20))):
        x0, x1 = cx + (pos - aw / 2) * W, cx + (pos + aw / 2) * W
        y1 = oy + H
        y0 = y1 - ah * H
        d.rectangle((x0, y0 + aw * W / 2, x1, y1), fill=0)
        d.ellipse((x0, y0, x1, y0 + aw * W), fill=0)
    # 一层殿身 + 下层檐（翼角上翘）
    poly([(-0.33, 0.40), (0.33, 0.40), (0.33, 0.565), (-0.33, 0.565)])
    poly([(-0.47, 0.335), (-0.37, 0.395), (0.37, 0.395), (0.47, 0.335), (0.30, 0.295), (-0.30, 0.295)])
    # 二层殿身 + 上层檐 + 正脊
    poly([(-0.25, 0.20), (0.25, 0.20), (0.25, 0.295), (-0.25, 0.295)])
    poly([(-0.37, 0.19), (-0.28, 0.235), (0.28, 0.235), (0.37, 0.19), (0.19, 0.11), (-0.19, 0.11)])
    poly([(-0.20, 0.085), (0.20, 0.085), (0.19, 0.115), (-0.19, 0.115)])
    poly([(-0.205, 0.06), (-0.175, 0.06), (-0.175, 0.10), (-0.205, 0.10)])
    poly([(0.175, 0.06), (0.205, 0.06), (0.205, 0.10), (0.175, 0.10)])
    # 檩条：檐下两道细横线，增加层次
    rect(-0.31, 0.415, 0.31, 0.43, 0)
    rect(-0.23, 0.245, 0.23, 0.258, 0)

    small = (mask.width // ss, mask.height // ss)
    mask = mask.resize(small, Image.Resampling.LANCZOS)
    # 自上而下：金亮 → 橙金，alpha 也渐弱，像被底下的光托起
    top_c = (255, 222, 140) if not light else (214, 96, 60)
    bot_c = (255, 168, 80) if not light else (190, 60, 40)
    grad = Image.linear_gradient("L").resize(small)
    col = Image.composite(Image.new("RGBA", small, (*bot_c, 255)), Image.new("RGBA", small, (*top_c, 255)), grad)
    fade = grad.point(lambda v: int(190 - 90 * v / 255))
    col.putalpha(ImageChops.multiply(mask, fade))
    if len(_TIANANMEN_CACHE) > 6:
        _TIANANMEN_CACHE.clear()
    _TIANANMEN_CACHE[key] = col
    return col


def _hash01(n: int, salt: int) -> float:
    v = (n * 1103515245 + salt * 12345 + 2531011) & 0x7FFFFFFF
    return ((v >> 8) & 0xFFFF) / 65535.0


def paint_national(layer: Image.Image, phase: float, *, stage: str, light: bool = False) -> None:
    """国庆海报式构图：金色光芒 + 底部飘带 + 右下天安门剪影 + 烟花 + 右上五星。"""
    bw, bh = layer.size
    if bw < 40 or bh < 20:
        return
    slow = stage in ("idle", "done")
    fxl = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(fxl)

    # 光芒：从右下天安门后方向左上放射，整体缓慢摆动；画完再模糊，像海报光晕
    ta_h = int(round(bh * 0.42))
    ta = _tiananmen(ta_h, light)
    # 再压一层透明度，融进红绸，避免剪影「贴上去」
    ta = ta.copy()
    ta.putalpha(ta.getchannel("A").point(lambda v: int(v * 0.72)))
    ta_x = bw - ta.width - int(round(bw * 0.02))
    ta_y = bh - ta.height + 3
    acx, acy = ta_x + ta.width * 0.55, bh + bh * 0.02
    wob = math.sin(phase * (0.25 if slow else 0.45)) * 4.0
    ray_len = bw * 1.7
    ray_c = (255, 214, 130) if not light else (255, 150, 90)
    rays = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    rd = ImageDraw.Draw(rays)
    for i in range(9):
        ang = math.radians(-165 + i * 14.5 + wob)
        hw = math.radians(1.0 if i % 2 else 0.65)
        a = 28 if i % 2 else 16
        rd.polygon(
            [
                (acx, acy),
                (acx + math.cos(ang - hw) * ray_len, acy + math.sin(ang - hw) * ray_len),
                (acx + math.cos(ang + hw) * ray_len, acy + math.sin(ang + hw) * ray_len),
            ],
            fill=(*ray_c, a),
        )
    fxl.alpha_composite(rays.filter(ImageFilter.GaussianBlur(radius=max(1.5, bh / 55))))

    # 飘带：两条丝带沿中下流动，避开大数字区
    def ribbon(y_base: float, amp: float, thick: float, freq: float, sp: float, fill, edge) -> None:
        step = max(4, bw // 40)
        xs = list(range(-step, bw + step * 2, step))
        tops = []
        for x in xs:
            y = y_base + math.sin(x / bw * math.pi * 2 * freq + phase * sp) * amp
            tops.append((x, y))
        bots = [(x, y + thick) for x, y in reversed(tops)]
        d.polygon(tops + bots, fill=fill)
        d.line(tops, fill=edge, width=1)

    rsp = 0.35 if slow else 0.7
    ribbon(bh * 0.82, bh * 0.04, bh * 0.09, 1.05, rsp * 0.8, (150, 14, 26, 100), (200, 70, 70, 80))
    ribbon(bh * 0.88, bh * 0.045, bh * 0.07, 1.3, rsp, (232, 56, 48, 110), (255, 214, 130, 160))

    # 天安门剪影（右下，略模糊边缘）
    fxl.alpha_composite(ta.filter(ImageFilter.GaussianBlur(radius=0.6)), (ta_x, ta_y))

    # 烟花：每 3.2s 在右上偏中绽放一朵，金红交替
    cyc = 3.2 if not slow else 6.0
    n = int(phase / cyc)
    p = (phase % cyc) / 1.5
    if p < 1.0:
        fxx = bw * (0.55 + 0.35 * _hash01(n, 1))
        fyy = bh * (0.10 + 0.32 * _hash01(n, 2))
        rad = (p ** 0.55) * bh * 0.22
        fade = (1.0 - p) ** 1.3
        gold = _hash01(n, 3) < 0.6
        c = (255, 224, 130) if gold else (255, 128, 90)
        spokes = 12
        for k in range(spokes):
            ang = k / spokes * math.pi * 2 + n * 0.37
            for rr, sz, aa in ((1.0, 1.4, 220), (0.78, 1.0, 140), (0.56, 0.8, 85)):
                x = fxx + math.cos(ang) * rad * rr
                y = fyy + math.sin(ang) * rad * rr + (p * p) * bh * 0.05 * rr
                a = int(aa * fade)
                if a > 4:
                    d.ellipse((x - sz, y - sz, x + sz, y + sz), fill=(*c, a))
        if p < 0.18:
            fa = int(190 * (1 - p / 0.18))
            r0 = 2.5 + p * 12
            d.ellipse((fxx - r0, fyy - r0, fxx + r0, fyy + r0), fill=(255, 250, 220, fa))

    layer.alpha_composite(fxl)

    # 右上五星：略缩小，明确落在右上角，不压天安门
    unit = max(2.2, bh * 0.042)
    paint_canton(
        layer, phase,
        unit=unit,
        ox=int(round(bw - 13 * unit - bw * 0.03)),
        oy=max(1, int(round(bh * 0.05))),
        slow=slow,
    )


# ---------------------------------------------------------------- 霓虹流光 HUD

def _stage_palette(stage: str, *, light: bool = False) -> tuple[tuple[int, int, int], tuple[int, int, int], float, float]:
    """(主色, 副色, 绕行周期秒, 亮度)"""
    if light:
        if stage == "warn":
            return (210, 110, 20), (200, 50, 60), 3.6, 0.95
        if stage == "done":
            return (20, 150, 110), (40, 160, 130), 14.0, 0.85
        if stage == "idle":
            return (0, 150, 180), (180, 40, 140), 16.0, 0.55
        return (0, 170, 200), (180, 40, 150), 9.0, 0.9
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


def _scanlines(bw: int, bh: int, *, light: bool = False) -> Image.Image:
    key = (bw, bh, int(light))
    got = _SCAN_CACHE.get(key)
    if got is not None:
        return got
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    if light:
        for y in range(0, bh, 3):
            d.line((0, y, bw, y), fill=(120, 160, 180, 22))
        for x in range(0, bw, 24):
            d.line((x, 0, x, bh), fill=(80, 140, 170, 10))
    else:
        for y in range(0, bh, 3):
            d.line((0, y, bw, y), fill=(0, 0, 0, 46))
        for x in range(0, bw, 24):
            d.line((x, 0, x, bh), fill=(120, 200, 255, 9))
    if len(_SCAN_CACHE) > 8:
        _SCAN_CACHE.clear()
    _SCAN_CACHE[key] = im
    return im


def paint_neonflow(layer: Image.Image, phase: float, *, stage: str, radius: int, light: bool = False) -> None:
    """霓虹 HUD：扫描线 + 角标 + 绕边流光（双头、拖尾、泛光）+ 偶发故障错位。"""
    bw, bh = layer.size
    if bw < 40 or bh < 20:
        return
    c1, c2, period, gain = _stage_palette(stage, light=light)
    scale = max(0.7, min(2.4, bh / 92.0))
    layer.alpha_composite(_scanlines(bw, bh, light=light))

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
