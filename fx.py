"""程序化皮肤特效：国旗星组（国庆皮）、霓虹流光 HUD、宣纸山水（墨水涟漪）。全部按帧绘制，不依赖生图。"""
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


_GAUGE_CACHE: dict[tuple, Image.Image] = {}


def _gauge_plate(bw: int, bh: int, c1: tuple[int, int, int], c2: tuple[int, int, int], *, light: bool, gain: float) -> Image.Image:
    """静态仪表底：同心弧 + 刻度 + 淡十字准星，缓存按尺寸/色相。"""
    key = (bw, bh, c1, c2, int(light), int(gain * 20))
    got = _GAUGE_CACHE.get(key)
    if got is not None:
        return got
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    cx, cy = bw * 0.52, bh * 0.48
    # 同心弧（开口朝右上，避开左下标题区）
    a0, a1 = -55, 125
    for i, (rr, col, aa) in enumerate(
        (
            (bh * 0.58, c1, int(38 * gain)),
            (bh * 0.42, c2, int(28 * gain)),
            (bh * 0.28, c1, int(22 * gain)),
        )
    ):
        box = (cx - rr, cy - rr, cx + rr, cy + rr)
        w = 1 if i else max(1, int(round(bh / 70)))
        d.arc(box, a0, a1, fill=(*col, aa), width=w)
    # 外弧刻度
    r_tick = bh * 0.58
    for i in range(9):
        t = i / 8.0
        ang = math.radians(a0 + (a1 - a0) * t)
        cos, sin = math.cos(ang), math.sin(ang)
        long = i % 2 == 0
        r0 = r_tick - (5.5 if long else 3.0)
        r1 = r_tick + (1.5 if long else 0.5)
        aa = int((55 if long else 32) * gain)
        col = c1 if long else c2
        d.line(
            (cx + cos * r0, cy + sin * r0, cx + cos * r1, cy + sin * r1),
            fill=(*col, aa),
            width=1,
        )
    # 十字准星（短、淡，不穿过整卡）
    span_x, span_y = bw * 0.16, bh * 0.22
    gap = max(4.0, bh * 0.06)
    cross_a = int(26 * gain)
    d.line((cx - span_x, cy, cx - gap, cy), fill=(*c1, cross_a), width=1)
    d.line((cx + gap, cy, cx + span_x, cy), fill=(*c1, cross_a), width=1)
    d.line((cx, cy - span_y, cx, cy - gap), fill=(*c2, cross_a), width=1)
    d.line((cx, cy + gap, cx, cy + span_y), fill=(*c2, cross_a), width=1)
    # 中心小环
    cr = max(2.5, bh * 0.035)
    d.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), outline=(*c1, int(40 * gain)), width=1)
    if len(_GAUGE_CACHE) > 12:
        _GAUGE_CACHE.clear()
    _GAUGE_CACHE[key] = im
    return im


def _paint_fog(
    layer: Image.Image,
    phase: float,
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
    *,
    gain: float,
    scale: float,
    light: bool,
) -> None:
    """内场双色呼吸雾：周期约 2× 流光，极低透明、高斯软边。"""
    bw, bh = layer.size
    fog = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    fd = ImageDraw.Draw(fog)
    breath = 0.55 + 0.45 * (0.5 + 0.5 * math.sin(phase * (math.pi * 2 / 18.0)))
    a_base = int((48 if light else 62) * gain * breath)
    # 主色：偏左下缓慢漂移；副色：偏右上对向
    drift = 0.5 + 0.5 * math.sin(phase * (math.pi * 2 / 22.0) + 1.2)
    blobs = (
        (bw * (0.28 + 0.06 * drift), bh * (0.62 - 0.05 * drift), bh * 0.55, c1, a_base),
        (bw * (0.72 - 0.05 * drift), bh * (0.32 + 0.04 * drift), bh * 0.48, c2, int(a_base * 0.85)),
    )
    for bx, by, rr, col, aa in blobs:
        if aa < 4:
            continue
        fd.ellipse((bx - rr, by - rr, bx + rr, by + rr), fill=(*col, aa))
    blur = max(6.0, 10.0 * scale)
    layer.alpha_composite(fog.filter(ImageFilter.GaussianBlur(radius=blur)))


def _paint_gauge_needle(
    layer: Image.Image,
    phase: float,
    c1: tuple[int, int, int],
    *,
    gain: float,
    stage: str,
) -> None:
    """外弧上一颗极淡的游标光点，随 phase 缓移。"""
    bw, bh = layer.size
    cx, cy = bw * 0.52, bh * 0.48
    a0, a1 = -55.0, 125.0
    # warn 走得快一点
    period = 5.5 if stage == "warn" else (14.0 if stage == "done" else 11.0)
    t = (phase / period) % 1.0
    if stage == "done":
        t = 1.0  # 到点停在终点
    ang = math.radians(a0 + (a1 - a0) * t)
    r = bh * 0.58
    px, py = cx + math.cos(ang) * r, cy + math.sin(ang) * r
    d = ImageDraw.Draw(layer)
    gr = max(2.2, bh * 0.028)
    d.ellipse((px - gr, py - gr, px + gr, py + gr), fill=(*c1, int(90 * gain)))
    d.ellipse((px - gr * 0.4, py - gr * 0.4, px + gr * 0.4, py + gr * 0.4), fill=(255, 255, 255, int(140 * gain)))


def paint_neonflow(layer: Image.Image, phase: float, *, stage: str, radius: int, light: bool = False) -> None:
    """霓虹 HUD：色雾 + 仪表底 + 扫描线 + 角标 + 绕边流光 + 偶发故障错位。"""
    bw, bh = layer.size
    if bw < 40 or bh < 20:
        return
    c1, c2, period, gain = _stage_palette(stage, light=light)
    scale = max(0.7, min(2.4, bh / 92.0))

    # 内场：先雾、再仪表，再扫描线（网格压在上面，HUD 感更干净）
    _paint_fog(layer, phase, c1, c2, gain=gain, scale=scale, light=light)
    layer.alpha_composite(_gauge_plate(bw, bh, c1, c2, light=light, gain=gain))
    _paint_gauge_needle(layer, phase, c1, gain=gain, stage=stage)
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


# ---------------------------------------------------------------- 墨水涟漪

_PAPER_CACHE: dict[tuple, Image.Image] = {}
_SCENE_CACHE: dict[tuple, tuple[Image.Image, float]] = {}
_SEAL_CACHE: dict[tuple, Image.Image] = {}
_WATER_Y = 0.665


def _cache_put(cache: dict, key, val, cap: int = 6):
    if len(cache) > cap:
        cache.clear()
    cache[key] = val
    return val


def _rnd(seed: int):
    """确定性伪随机：同一尺寸每次都画出同一张纸、同一道山。"""
    s = seed & 0x7FFFFFFF

    def nxt(n: int) -> int:
        nonlocal s
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        return s % max(1, n)

    return nxt


def _ink_palette(stage: str, *, light: bool = False) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], float]:
    """(浓墨, 淡墨, 印色, 增益)。纸永远浅底深墨；深墙纸下纸更透，墨要相应加浓。"""
    g = 1.0 if light else 1.16
    if stage == "warn":
        return (104, 44, 20), (152, 88, 46), (198, 52, 36), g
    if stage == "done":
        return (40, 46, 46), (88, 98, 94), (206, 64, 44), g * 0.95
    if stage == "idle":
        return (58, 54, 48), (112, 104, 92), (170, 84, 70), g * 0.78
    return (30, 28, 24), (88, 80, 68), (190, 52, 38), g


def _paper(bw: int, bh: int, *, light: bool) -> Image.Image:
    """宣纸：横帘纹 + 长纤维 + 左上天光 + 四边吃色。整张缓存。"""
    key = (bw, bh, int(light))
    got = _PAPER_CACHE.get(key)
    if got is not None:
        return got
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fiber = (120, 106, 84) if light else (108, 96, 76)
    for y in range(1, bh, 3 if light else 4):
        d.line((0, y, bw, y), fill=(*fiber, 9 + (y * 13 + bw) % 10))
    nxt = _rnd((bw * 73856093) ^ (bh * 19349663))
    for _i in range(max(12, bw // 12)):
        x0, y0 = nxt(bw), nxt(bh)
        d.line((x0, y0, x0 + 16 + nxt(38), y0 + nxt(5) - 2), fill=(*fiber, 11 + nxt(13)), width=1)
    px = im.load()
    for _i in range(max(40, (bw * bh) // 80)):
        px[nxt(bw), nxt(bh)] = (*fiber, 12 + nxt(14))

    light_layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    ImageDraw.Draw(light_layer).ellipse(
        (-bw * 0.8, -bh * 1.9, bw * 1.05, bh * 0.85), fill=(255, 252, 240, 34)
    )
    im.alpha_composite(light_layer.filter(ImageFilter.GaussianBlur(radius=max(8.0, bh * 0.30))))

    # 四边只吃一点色：压太狠纸就发脏
    n = max(2, int(min(bw, bh) * 0.09))
    mask = Image.new("L", (bw, bh), 0)
    md = ImageDraw.Draw(mask)
    for i in range(n):
        md.rectangle((i, i, bw - 1 - i, bh - 1 - i), outline=int(22 * (1.0 - i / n) ** 1.6))
    edge = Image.new("RGBA", (bw, bh), (150, 124, 84, 0))
    edge.putalpha(mask.filter(ImageFilter.GaussianBlur(radius=max(1.0, n * 0.2))))
    im.alpha_composite(edge)
    return _cache_put(_PAPER_CACHE, key, im)


def _wobble(r: float, ang: float, phase: float, amount: float) -> float:
    return r * (
        1.0
        + amount * math.sin(2.0 * ang + phase)
        + amount * 0.62 * math.sin(5.0 * ang - phase * 0.7)
        + amount * 0.4 * math.sin(3.0 * ang + 1.15)
    )


def _blob_pts(cx: float, cy: float, rx: float, ry: float, phase: float, n: int = 22) -> list[tuple[float, float]]:
    """不规则墨团轮廓：正圆太假，得让边缘自己乱一点。"""
    pts: list[tuple[float, float]] = []
    for i in range(n):
        a = (i / n) * math.pi * 2.0
        rr = _wobble(1.0, a, phase, 0.18)
        pts.append((cx + math.cos(a) * rx * rr, cy + math.sin(a) * ry * rr))
    return pts


def _draw_closed(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], *, fill=None, outline=None, width: int = 1) -> None:
    if len(pts) < 3:
        return
    if fill is not None:
        d.polygon(pts, fill=fill)
    if outline is not None and width > 0:
        d.line(pts + [pts[0]], fill=outline, width=width)


def _ridge_poly(
    x0: float, x1: float, base: float, amp: float, k: float, *, fade_l: float = 0.3, fade_r: float = 0.0
) -> list[tuple[float, float]]:
    """一道山脊：三组正弦叠出峰谷，两端按 fade 收回水线。不收的那端会留下一块平板。"""
    pts: list[tuple[float, float]] = []
    n = 30
    for i in range(n + 1):
        t = i / n
        e = (
            0.52
            + 0.40 * math.sin(t * 4.3 + k)
            + 0.20 * math.sin(t * 9.7 + k * 1.9)
            + 0.10 * math.sin(t * 17.1 + k * 2.7)
        )
        e = max(0.04, min(1.2, e))
        if fade_l > 0.0 and t < fade_l:
            e *= (t / fade_l) ** 0.75
        if fade_r > 0.0 and t > 1.0 - fade_r:
            e *= ((1.0 - t) / fade_r) ** 0.75
        pts.append((x0 + (x1 - x0) * t, base - amp * e))
    pts.append((x1, base + 2.0))
    pts.append((x0, base + 2.0))
    return pts


def _scene(
    bw: int, bh: int, c1: tuple[int, int, int], c2: tuple[int, int, int], *, gain: float
) -> tuple[Image.Image, float]:
    """一角山水：远山一抹淡影 + 近山勾骨带湿笔。各有各的山脚高度，之间留白。
    返回 (山影, 近山峰的 x)，峰 x 给水面倒影用。"""
    key = (bw, bh, c1, c2, int(gain * 20))
    got = _SCENE_CACHE.get(key)
    if got is not None:
        return got
    base = bh * _WATER_Y
    scale = max(0.7, min(2.4, bh / 92.0))
    # 墨往纸下渗：山头浓、山脚淡，靠一条竖向渐变压出来
    ramp = Image.linear_gradient("L").resize((bw, bh)).point(lambda v: 255 - int(v * 0.62))
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))

    far = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    far_pts = _ridge_poly(bw * 0.27, bw * 1.03, base - bh * 0.13, bh * 0.27, 1.6, fade_l=0.40, fade_r=0.22)
    ImageDraw.Draw(far).polygon(far_pts, fill=(*c2, int(36 * gain)))
    far.putalpha(ImageChops.multiply(far.getchannel("A"), ramp))
    im.alpha_composite(far.filter(ImageFilter.GaussianBlur(radius=2.6 * scale)))

    near_pts = _ridge_poly(bw * 0.50, bw * 1.03, base, bh * 0.44, 5.3, fade_l=0.26)
    wash = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    ImageDraw.Draw(wash).polygon(near_pts, fill=(*c2, int(50 * gain)))
    wash.putalpha(ImageChops.multiply(wash.getchannel("A"), ramp))
    im.alpha_composite(wash.filter(ImageFilter.GaussianBlur(radius=1.1 * scale)))

    # 山骨：一条稍重的脊线压在湿笔上，山才立得住
    bone = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    bd = ImageDraw.Draw(bone)
    ridge = near_pts[:-2]
    bd.line(ridge, fill=(*c1, int(96 * gain)), width=max(2, int(round(2.2 * scale))))
    bd.line([(x, y - 0.6 * scale) for x, y in ridge], fill=(*c1, int(150 * gain)), width=1)
    im.alpha_composite(bone.filter(ImageFilter.GaussianBlur(radius=max(0.5, 0.6 * scale))))

    peak_x = min(ridge, key=lambda p: p[1])[0]
    return _cache_put(_SCENE_CACHE, key, (im, peak_x))


def _seal(size: int, col: tuple[int, int, int], *, gain: float) -> Image.Image:
    """白文朱印：朱底刻白痕，边角略残。"""
    key = (size, col, int(gain * 20))
    got = _SEAL_CACHE.get(key)
    if got is not None:
        return got
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, size - 1, size - 1), radius=max(1, size // 9), fill=(*col, int(158 * gain)))
    cut = (0, 0, 0, 0)
    m = max(1, int(size * 0.17))
    w = max(1, size // 13)
    mid = size // 2
    d.line((mid, m, mid, size - 1 - m), fill=cut, width=w)
    for i in range(3):
        y = m + int((size - 2 * m) * (0.14 + i * 0.36))
        d.line((m, y, mid - w, y), fill=cut, width=w)
    d.line((mid + 2 * w, m, mid + 2 * w, size - 1 - m), fill=cut, width=w)
    for i in range(2):
        y = m + int((size - 2 * m) * (0.28 + i * 0.44))
        d.line((mid + 2 * w, y, size - 1 - m, y), fill=cut, width=w)
    nxt = _rnd(size * 2654435761)
    px = im.load()
    rim = max(1, size // 8)
    for _i in range(max(6, size)):
        x, y = nxt(size), nxt(size)
        if min(x, y, size - 1 - x, size - 1 - y) <= rim:
            px[x, y] = cut
    return _cache_put(_SEAL_CACHE, key, im)


def _water_surface(
    layer: Image.Image, phase: float, base: int, peak_x: float, c1, c2, *, gain: float, scale: float
) -> None:
    """水面就是留白：一条断续水线 + 几笔横向水纹 + 峰影三两道，全靠笔不靠雾。"""
    bw, bh = layer.size
    d = ImageDraw.Draw(layer)
    w1 = max(1, int(round(scale * 0.9)))
    # 水线断三截，两处留白，才不像一条 UI 分割线
    for x0, x1, aa in ((0.05, 0.34, 46), (0.40, 0.72, 74), (0.77, 1.0, 54)):
        d.line((bw * x0, base, bw * x1, base), fill=(*c1, int(aa * gain)), width=w1)
    # 峰影：倒影只取山头那几道，随水微微左右挪
    depth = max(3.0, (bh - base) * 0.72)
    for i in range(3):
        t = (i + 1) / 4.0
        ln = bw * (0.15 - i * 0.035)
        off = math.sin(phase * 1.25 + i * 1.1) * max(1.0, bw * 0.011) * (0.5 + t)
        x = peak_x - ln * 0.5 + off
        aa = int((40 - i * 10) * gain)
        if aa > 5:
            d.line((x, base + depth * t, x + ln, base + depth * t), fill=(*c2, aa), width=w1)
    # 远处水纹
    for i in range(3):
        ry = base + (bh - base) * (0.26 + i * 0.26)
        ln = bw * (0.16 + 0.1 * ((i * 7) % 3))
        x = bw * 0.10 + math.sin(phase * 0.31 + i * 1.7) * bw * 0.045
        aa = int((32 - i * 8) * gain)
        if aa > 5:
            d.line((x, ry, x + ln, ry), fill=(*c2, aa), width=1)


def paint_inkpulse(layer: Image.Image, phase: float, *, stage: str, radius: int, light: bool = False) -> None:
    """墨水涟漪：宣纸上一角山水。远山淡墨、水面倒影摇晃，一滴墨落水漾开扁圆涟漪，右上盖朱印。"""
    bw, bh = layer.size
    if bw < 40 or bh < 20:
        return
    c1, c2, cs, gain = _ink_palette(stage, light=light)
    scale = max(0.7, min(2.4, bh / 92.0))
    base = int(bh * _WATER_Y)

    layer.alpha_composite(_paper(bw, bh, light=light))
    scene, peak_x = _scene(bw, bh, c1, c2, gain=gain)
    layer.alpha_composite(scene)
    _water_surface(layer, phase, base, peak_x, c1, c2, gain=gain, scale=scale)

    cyc = 3.6 if stage == "warn" else (12.0 if stage == "idle" else (0.0 if stage == "done" else 6.8))
    ink = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    fd = ImageDraw.Draw(ink)
    dx = bw * 0.72
    if cyc > 0.0:
        g = phase % cyc
        seed = int(phase / cyc) * 9973
        # 落点必须躲开左边的大数字：128:00:00 在窄窗上右缘能吃到 0.65 bw，
        # 右边留出朱印的位置（印在 0.90 bw 往右）
        dx = bw * (0.70 + ((seed >> 3) % 14) / 100.0)
        fall = 0.34
        if g < fall:
            # 一滴墨从上边缘加速落下
            u = g / fall
            y = base - bh * 0.62 * (1.0 - u * u)
            rr = (1.5 + 0.9 * u) * scale
            fd.ellipse((dx - rr, y - rr * 1.5, dx + rr, y + rr), fill=(*c1, int(224 * gain)))
            fd.line((dx, y - rr * 3.4, dx, y - rr * 1.4), fill=(*c1, int(86 * gain)), width=max(1, int(scale)))
        else:
            u = (g - fall) / (cyc - fall)
            # 墨在水里化开：沉在水面之下的一团，别填进涟漪圈里去当碟子
            cloud_a = int(64 * gain * max(0.0, 1.0 - u * 1.15))
            if cloud_a > 4:
                cloud = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
                _draw_closed(
                    ImageDraw.Draw(cloud),
                    _blob_pts(
                        dx,
                        base + (bh - base) * (0.18 + 0.34 * u),
                        bw * 0.07 * (0.6 + u * 2.2),
                        (bh - base) * 0.13 * (0.6 + u * 1.4),
                        phase * 0.5,
                    ),
                    fill=(*c2, cloud_a),
                )
                layer.alpha_composite(cloud.filter(ImageFilter.GaussianBlur(radius=max(1.8, 2.6 * scale))))
            # 涟漪：贴着水面一圈圈扁环，近侧实、远侧虚，越外越细
            for k, delay in enumerate((0.0, 0.13, 0.28, 0.45)):
                v = (u - delay) / max(0.05, 1.0 - delay)
                if not 0.0 < v < 1.0:
                    continue
                fade = (1.0 - v) ** 1.1
                rx = 5.0 * scale + v * bw * 0.40
                ry = max(1.0, rx * 0.16)
                box = (dx - rx, base - ry, dx + rx, base + ry)
                aa = int((150 - k * 26) * gain * fade)
                if aa > 6:
                    w = 1 if k else max(1, int(round(1.6 * scale * (0.4 + fade))))
                    fd.arc(box, 12, 168, fill=(*c1, aa), width=w)
                    fd.arc(box, 196, 344, fill=(*c2, int(aa * 0.45)), width=1)
            # 入水溅起的几点
            if u < 0.2:
                fu = u / 0.2
                for i in range(4):
                    s = (seed + i * 104729) & 0xFFFF
                    sx = dx + ((s % 31) - 15) * 0.9 * scale * (0.4 + fu * 1.8)
                    sy = base - (4 + (s >> 5) % 7) * scale * (1.0 - fu)
                    pr = (1.0 + (s >> 9) % 2) * scale * (1.0 - fu)
                    if pr > 0.5:
                        fd.ellipse((sx - pr, sy - pr, sx + pr, sy + pr), fill=(*c1, int(172 * gain * (1.0 - fu))))
    else:
        # 到点：水静墨干，只剩一道残痕
        rx = bw * 0.26
        ry = max(1.5, rx * 0.16)
        fd.arc(
            (dx - rx, base - ry, dx + rx, base + ry),
            0,
            180,
            fill=(*c2, int(72 * gain)),
            width=max(1, int(round(1.4 * scale))),
        )
    layer.alpha_composite(ink.filter(ImageFilter.GaussianBlur(radius=max(0.4, 0.55 * scale))))

    # 右上闲章：到点时朱色透出一圈，像刚按下去
    ss = max(11, int(bh * 0.2))
    sx0, sy0 = bw - ss - int(7 * scale), int(6 * scale)
    if stage == "done":
        halo = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        ImageDraw.Draw(halo).rounded_rectangle(
            (sx0 - 3, sy0 - 3, sx0 + ss + 3, sy0 + ss + 3), radius=max(1, ss // 5), fill=(*cs, 92)
        )
        layer.alpha_composite(halo.filter(ImageFilter.GaussianBlur(radius=max(2.0, 3.0 * scale))))
    layer.alpha_composite(_seal(ss, cs, gain=min(1.1, gain)), (max(0, sx0), sy0))

    _ = radius  # 圆角由 ornaments 蒙版处理；保留参数与 neonflow 签名一致


# ---------------------------------------------------------------- 雷霆恶狼

_STORM_CACHE: dict[tuple, Image.Image] = {}
_WOLF_CACHE: dict[tuple, Image.Image] = {}

BITE_SEC = 2.85  # 点一下：蓄力→劈到底边→沿边传导一圈→狼钻出→咬一口→退回
WOLF_AT = 1.48  # 余电将灭时狼才从边上钻出来
CHARGE_END = 0.30
STRIKE_START = 0.20
STRIKE_END = 0.62
CONDUCT_START = 0.52
CONDUCT_END = 1.52


def _thunder_palette(stage: str, *, light: bool = False) -> tuple[tuple[int, int, int], tuple[int, int, int], float, float]:
    """(电弧色, 雷云色, 落雷周期秒, 增益)"""
    gain = 0.86 if light else 1.0
    if stage == "warn":
        return (255, 128, 214), (92, 34, 82), 1.7, gain
    if stage == "done":
        return (130, 255, 205), (30, 72, 66), 5.5, gain * 0.8
    if stage == "idle":
        return (158, 194, 255), (40, 48, 78), 6.5, gain * 0.66
    return (176, 228, 255), (48, 60, 96), 2.9, gain


def _storm(bw: int, bh: int, cloud: tuple[int, int, int], *, gain: float) -> Image.Image:
    """雷云：上重下轻的一片翻卷暗团，宽 2bw。

    画成横向周期为 bw 的图再裁窗口平移，比 offset 环绕靠谱——环绕会在左右
    边界之间留一道对不上的硬缝，模糊也盖不住。"""
    key = (bw, bh, cloud, int(gain * 20))
    got = _STORM_CACHE.get(key)
    if got is not None:
        return got
    im = Image.new("RGBA", (bw * 2, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    nxt = _rnd((bw * 2654435761) ^ (bh * 40503))
    for _i in range(18):
        cx, cy = nxt(bw), nxt(max(2, int(bh * 0.9)))
        rx = bh * (0.24 + nxt(50) / 100.0)
        ry = rx * (0.34 + nxt(32) / 100.0)
        # 越往下越淡，云才像压在头顶，底下也给大数字留出暗底
        fade = (1.0 - min(1.0, cy / max(1.0, bh))) ** 1.3
        a = int((30 + nxt(38)) * fade * gain)
        if a <= 2:
            continue
        for rep in (0, bw):  # 同一团画两遍，裁窗口跨过 bw 时接得上
            d.ellipse((cx + rep - rx, cy - ry, cx + rep + rx, cy + ry), fill=(*cloud, a))
    im = im.filter(ImageFilter.GaussianBlur(radius=max(3.0, bh * 0.085)))
    return _cache_put(_STORM_CACHE, key, im)


def _rain(
    layer: Image.Image, phase: float, arc: tuple[int, int, int], *, n: int, gain: float, scale: float
) -> None:
    """斜雨：定种子的一把雨丝各自循环下落。落雷之间靠它撑住「暴雨」的动感。"""
    bw, bh = layer.size
    d = ImageDraw.Draw(layer)
    nxt = _rnd(90210)
    slant = 0.30
    for _i in range(n):
        x0 = nxt(1000) / 1000.0
        off = nxt(1000) / 1000.0
        spd = 1.5 + nxt(120) / 100.0
        ln = bh * (0.10 + nxt(13) / 100.0)
        bright = nxt(6) == 0
        y = ((phase * spd * 0.75 + off) % 1.25) * (bh + ln) - ln
        x = ((x0 + phase * spd * 0.02) % 1.0) * bw - y * slant
        # 单根太显眼就成了划痕，得靠密度成雨
        a = int((54 if bright else 26) * gain)
        d.line((x, y, x + ln * slant, y + ln), fill=(*arc, a), width=1 if not bright else max(1, int(round(1.4 * scale))))


def _bolt_pts(
    seed: int, x0: float, y0: float, x1: float, y1: float, *, depth: int = 5, jitter: float = 0.30
) -> list[tuple[float, float]]:
    """中点位移生成折线：每次把线段中点往垂线方向random 推开，抖动逐层减半。"""
    nxt = _rnd(seed)
    pts = [(x0, y0), (x1, y1)]
    for _ in range(depth):
        out: list[tuple[float, float]] = [pts[0]]
        for a, b in zip(pts, pts[1:]):
            dx, dy = b[0] - a[0], b[1] - a[1]
            ln = math.hypot(dx, dy)
            mx, my = (a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5
            if ln > 1.0:
                off = (nxt(2001) / 1000.0 - 1.0) * ln * jitter
                mx -= dy / ln * off
                my += dx / ln * off
            out.append((mx, my))
            out.append(b)
        pts = out
        jitter *= 0.55
    return pts


def _flash_env(g: float) -> float:
    """真闪电是先一下虚闪、暗一瞬、再来主放电，然后拖尾。平滑上升会假。"""
    if g < 0.05:
        return 0.70
    if g < 0.09:
        return 0.12
    if g < 0.15:
        return 1.0
    if g < 0.34:
        return max(0.0, 1.0 - (g - 0.15) / 0.19) * 0.85
    return 0.0


def _draw_bolt(
    bloom: ImageDraw.ImageDraw,
    glow: ImageDraw.ImageDraw,
    core: ImageDraw.ImageDraw,
    pts: list[tuple[float, float]],
    arc: tuple[int, int, int],
    *,
    env: float,
    gain: float,
    scale: float,
    thick: float = 1.0,
) -> None:
    """三层画一道雷：宽泛光（后面重模糊）+ 紧边光 + 近白的芯。逐段收细，上粗下尖。"""
    n = max(1, len(pts) - 1)
    ba = int(86 * env * gain * thick)
    ga = int(205 * env * gain * thick)
    ca = int(255 * min(1.0, env * 1.25) * gain)
    for i in range(n):
        seg = (pts[i], pts[i + 1])
        w = (1.0 - 0.58 * (i / n)) * thick
        if ba > 2:
            bloom.line(seg, fill=(*arc, ba), width=max(3, int(round(14.0 * scale * w))))
        if ga > 3:
            glow.line(seg, fill=(*arc, ga), width=max(2, int(round(4.4 * scale * w))))
        if ca > 6:
            core.line(seg, fill=(242, 250, 255, ca), width=max(1, int(round(2.0 * scale * w))))


def paint_thunder(layer: Image.Image, phase: float, *, stage: str, radius: int, light: bool = False) -> None:
    """雷霆：暗雷云 + 沿边游走的电弧 + 周期落雷（虚闪—主放电—余晖）+ 全卡爆闪。"""
    bw, bh = layer.size
    if bw < 40 or bh < 20:
        return
    arc, cloud, period, gain = _thunder_palette(stage, light=light)
    scale = max(0.7, min(2.4, bh / 92.0))
    env = _flash_env(phase % period)
    # 两次落雷之间来一记远处闷雷：只照亮云，不下电
    far = _flash_env((phase + period * 0.55) % period) * 0.32
    lit_k = max(env, far)

    dx = int(phase * 5) % bw
    drift = _storm(bw, bh, cloud, gain=gain).crop((dx, 0, dx + bw, bh))
    layer.alpha_composite(drift)
    # 云被自己肚子里的电照亮：拿云的 alpha 当蒙版上电弧色，比盖一层白纱可信
    if lit_k > 0.02:
        lit = Image.new("RGBA", (bw, bh), (*arc, 0))
        lit.putalpha(drift.getchannel("A").point(lambda v: int(v * 0.85 * lit_k)))
        layer.alpha_composite(lit)

    # 雷一亮，雨丝跟着被照亮——这一下比单纯加白纱更像暴雨
    _rain(
        layer,
        phase,
        arc,
        n=(46 if stage == "warn" else (18 if stage == "idle" else 34)),
        gain=gain * (1.0 + 1.5 * env),
        scale=scale,
    )

    bloom_im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    glow_im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    core_im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    bd, gd, cd = ImageDraw.Draw(bloom_im), ImageDraw.Draw(glow_im), ImageDraw.Draw(core_im)

    # 余电沿边爬：只在落雷那一下和余晖里出现。常驻的话就是几段乱窜的白虚线
    if env > 0.06:
        _total, point = _perimeter(bw, bh, float(radius), 2.0)
        for k in range(2):
            head = (phase / (3.4 + k * 1.9) + k * 0.5) % 1.0
            n_pt = 9
            jig: list[tuple[float, float]] = []
            for i in range(n_pt):
                u = (head + i * 0.006) % 1.0
                px, py = point(u)
                ax, ay = point((u + 0.002) % 1.0)
                tx, ty = ax - px, ay - py
                ln = math.hypot(tx, ty) or 1.0
                # 沿边法线抖开才是锯齿电弧；顺切线抖只会得到一段歪线
                amp = 0.0 if i in (0, n_pt - 1) else ((int(phase * 26) + i * 7 + k * 31) % 7 - 3) * 0.75 * scale
                jig.append((px - ty / ln * amp, py + tx / ln * amp))
            e = min(1.0, env * 1.2)
            bd.line(jig, fill=(*arc, int(62 * gain * e)), width=max(3, int(round(5.0 * scale))), joint="curve")
            gd.line(jig, fill=(*arc, int(140 * gain * e)), width=max(2, int(round(2.2 * scale))), joint="curve")
            cd.line(jig, fill=(236, 250, 255, int(190 * gain * e)), width=1, joint="curve")

    if env > (0.35 if stage == "idle" else 0.01):
        seed = int(phase / period) * 7919 + 13
        nxt = _rnd(seed)
        # 主雷落在右侧，别糊住左边的大数字
        x0 = bw * (0.50 + nxt(36) / 100.0)
        x1 = x0 + (nxt(240) / 1000.0 - 0.12) * bw
        y1 = bh * (0.82 + nxt(28) / 100.0)  # 多半穿出下边缘，别在半空断掉
        main_pts = _bolt_pts(seed, x0, -2.0, x1, y1)
        _draw_bolt(bd, gd, cd, main_pts, arc, env=env, gain=gain, scale=scale)
        if y1 < bh:  # 落在卡内就砸出一团着地光
            gr = bh * 0.3
            bd.ellipse((x1 - gr, y1 - gr * 0.5, x1 + gr, y1 + gr * 0.5), fill=(*arc, int(80 * env * gain)))
        for b in range(2):
            i = int(len(main_pts) * (0.34 + 0.26 * b))
            bx, by = main_pts[i]
            ang = math.radians(-46 + nxt(92)) + (math.pi if b else 0.0)
            ln = bh * (0.24 + nxt(22) / 100.0)
            _draw_bolt(
                bd, gd, cd,
                _bolt_pts(seed + 977 * (b + 1), bx, by, bx + math.cos(ang) * ln, by + abs(math.sin(ang)) * ln, depth=3),
                arc, env=env * 0.72, gain=gain, scale=scale, thick=0.5,
            )

    layer.alpha_composite(bloom_im.filter(ImageFilter.GaussianBlur(radius=max(4.0, 7.0 * scale))))
    layer.alpha_composite(glow_im.filter(ImageFilter.GaussianBlur(radius=max(1.4, 2.0 * scale))))
    layer.alpha_composite(core_im)

    # 爆闪：亮那几帧整张卡提一下，且上重下轻——光是从云里打下来的
    if env > 0.02:
        top = int(140 * env * gain)
        if top > 3:
            ramp = Image.linear_gradient("L").resize((bw, bh)).point(lambda v: int((255 - v) * top / 255))
            flash = Image.new("RGBA", (bw, bh), (*arc, 0))
            flash.putalpha(ramp)
            layer.alpha_composite(flash)


# ---- 点一下：劈到边框 → 沿边传导 → 狼从余电里钻出来 ----

def thunder_fps(stage: str, phase: float) -> int:
    """落雷那半秒要 60Hz 才看得出虚闪—主放电的节奏；其余时间只有边缘电弧在爬，十几帧够了。"""
    _arc, _cloud, period, _gain = _thunder_palette(stage)
    if _flash_env(phase % period) > 0.01:
        return 60
    return 14 if stage in ("idle", "done") else 18


def _perim_u_at(bw: int, bh: int, r: float, x: float, y: float) -> tuple[float, float, float]:
    """周长上离 (x,y) 最近的一点：返回 (u, px, py)。"""
    _total, point = _perimeter(bw, bh, r, 2.0)
    best_u, best_d, best_p = 0.0, 1e18, (0.0, 0.0)
    for i in range(80):
        u = i / 80.0
        px, py = point(u)
        d = (px - x) ** 2 + (py - y) ** 2
        if d < best_d:
            best_d, best_u, best_p = d, u, (px, py)
    return best_u, best_p[0], best_p[1]


def _bottom_hit(bw: int, bh: int, r: float, cx: float) -> tuple[float, float, float]:
    """落点正下方砸到**底边**上的点（不是最近边框）。"""
    inset = 2.0
    x0, _y0, x1, y1 = inset, inset, bw - 1 - inset, bh - 1 - inset
    rr = max(1.0, min(float(r) - inset, (x1 - x0) / 2, (y1 - inset) / 2))
    hx = max(x0 + rr, min(x1 - rr, cx))
    hy = y1
    hit_u, _, _ = _perim_u_at(bw, bh, r, hx, hy)
    return hit_u, hx, hy


def _charge_env(t: float) -> float:
    """卡片蓄力：边框变亮变粗，给用户一个「要劈了」的信号。"""
    if t < 0.10:
        return t / 0.10
    if t < CHARGE_END:
        return 1.0
    if t < STRIKE_END:
        return max(0.45, 1.0 - (t - CHARGE_END) / (STRIKE_END - CHARGE_END) * 0.4)
    return max(0.0, 0.45 - (t - STRIKE_END) / 0.35)


def _strike_env(t: float) -> float:
    if t < STRIKE_START:
        return 0.0
    g = t - STRIKE_START
    if g < 0.04:
        return 0.55 * g / 0.04
    if g < 0.08:
        return 0.10
    if g < 0.16:
        return 1.0
    if t < STRIKE_END:
        return max(0.0, 1.0 - (t - STRIKE_START - 0.16) / (STRIKE_END - STRIKE_START - 0.16)) * 0.92
    return 0.0


def _conduct_progress(t: float) -> tuple[float, float]:
    """(沿边走了多少圈 0~1, 亮度)。慢速绕满四周。"""
    if t < CONDUCT_START:
        return 0.0, 0.0
    tc = t - CONDUCT_START
    dur = CONDUCT_END - CONDUCT_START
    spread = min(1.0, (tc / dur) ** 0.78)
    if tc < 0.08:
        env = tc / 0.08
    elif tc < dur * 0.42:
        env = 1.0
    elif tc < dur + 0.25:
        env = max(0.0, 1.0 - (tc - dur * 0.42) / (dur * 0.58 + 0.25)) ** 0.88
    else:
        env = max(0.0, 0.18 - (tc - dur - 0.25) / 0.4)
    return spread, env


def _paint_charge(
    layer: Image.Image,
    t: float,
    radius: int,
    arc: tuple[int, int, int],
    *,
    gain: float,
    scale: float,
) -> None:
    cenv = _charge_env(t)
    if cenv < 0.03:
        return
    bw, bh = layer.size
    inset = 2.0
    rr = min(radius, max(8, bh // 5))
    box = (inset, inset, bw - 1 - inset, bh - 1 - inset)
    w = max(1, int(round(1.0 + 4.2 * cenv * scale)))
    glow = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    ImageDraw.Draw(glow).rounded_rectangle(
        box, radius=rr, outline=(*arc, int(130 * cenv * gain)), width=w + 3
    )
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius=max(2.5, 3.5 * scale))))
    ImageDraw.Draw(layer).rounded_rectangle(
        box, radius=rr, outline=(244, 252, 255, int(220 * cenv * gain)), width=w
    )
    inner = Image.new("RGBA", (bw, bh), (*arc, 0))
    mask = Image.new("L", (bw, bh), 0)
    ImageDraw.Draw(mask).rounded_rectangle(box, radius=rr, fill=int(95 * cenv))
    inner.putalpha(mask)
    layer.alpha_composite(inner)


def paint_strike_conduct(
    layer: Image.Image,
    t: float,
    cx: float,
    cy: float,
    *,
    radius: int,
    stage: str = "run",
    light: bool = False,
) -> None:
    """点击：蓄力→劈到底边→沿四边慢速传导一圈。"""
    bw, bh = layer.size
    if bw < 40 or bh < 20 or t < 0.0 or t > CONDUCT_END + 0.35:
        return
    arc, _cloud, _period, gain = _thunder_palette(stage, light=light)
    scale = max(0.7, min(2.4, bh / 92.0))
    hit_u, hx, hy = _bottom_hit(bw, bh, float(radius), cx)
    env = _strike_env(t)
    spread, cenv = _conduct_progress(t)

    _paint_charge(layer, t, radius, arc, gain=gain, scale=scale)

    bloom = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    glow = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    core = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    bd, gd, cd = ImageDraw.Draw(bloom), ImageDraw.Draw(glow), ImageDraw.Draw(core)

    if env > 0.02:
        seed = 8800 + int(cx) * 3 + int(cy)
        bolt = _bolt_pts(seed, cx, cy, hx, hy, depth=5, jitter=0.24)
        _draw_bolt(bd, gd, cd, bolt, arc, env=env, gain=gain * 1.22, scale=scale, thick=1.25)
        gr = bh * 0.26
        bd.ellipse((hx - gr, hy - gr * 0.55, hx + gr, hy + gr * 0.55), fill=(*arc, int(110 * env * gain)))

    if cenv > 0.02 and spread > 0.01:
        _total, point = _perimeter(bw, bh, float(radius), 2.0)
        arc_len = spread * _total
        n_seg = max(24, int(arc_len / 2.8))
        for direction in (1, -1):
            pts: list[tuple[float, float]] = []
            half = spread * 0.5
            for i in range(n_seg + 1):
                u = (hit_u + direction * (i / n_seg) * half) % 1.0
                px, py = point(u)
                ax, ay = point((u + 0.0025 * direction) % 1.0)
                tx, ty = ax - px, ay - py
                ln = math.hypot(tx, ty) or 1.0
                tail = 1.0 - abs(i / n_seg - 0.5) * 1.15
                amp = ((int(t * 22) + i * 5) % 7 - 3) * 0.9 * scale * max(0.0, tail)
                pts.append((px - ty / ln * amp, py + tx / ln * amp))
            e = cenv * (0.95 if direction == 1 else 0.72)
            bd.line(pts, fill=(*arc, int(82 * gain * e)), width=max(3, int(round(7.0 * scale))), joint="curve")
            gd.line(pts, fill=(*arc, int(185 * gain * e)), width=max(2, int(round(3.0 * scale))), joint="curve")
            cd.line(pts, fill=(244, 252, 255, int(230 * gain * e)), width=1, joint="curve")
        for direction in (1, -1):
            head_u = (hit_u + direction * spread * 0.5) % 1.0
            hx2, hy2 = point(head_u)
            hr = max(3.0, 5.0 * scale)
            gd.ellipse((hx2 - hr, hy2 - hr, hx2 + hr, hy2 + hr), fill=(*arc, int(210 * cenv * gain)))
            cd.ellipse(
                (hx2 - hr * 0.45, hy2 - hr * 0.45, hx2 + hr * 0.45, hy2 + hr * 0.45),
                fill=(255, 255, 255, int(245 * cenv * gain)),
            )

    layer.alpha_composite(bloom.filter(ImageFilter.GaussianBlur(radius=max(3.5, 7.0 * scale))))
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius=max(1.8, 2.6 * scale))))
    layer.alpha_composite(core)
    flash = max(_charge_env(t) * 0.35, env, cenv * 0.8)
    if flash > 0.03:
        top = int(175 * flash * gain)
        ramp = Image.linear_gradient("L").resize((bw, bh)).point(lambda v: int((255 - v) * top / 255))
        veil = Image.new("RGBA", (bw, bh), (*arc, 0))
        veil.putalpha(ramp)
        layer.alpha_composite(veil)


def paint_thunder_click(
    layer: Image.Image,
    t: float,
    cx: float,
    cy: float,
    *,
    radius: int,
    stage: str = "run",
    light: bool = False,
) -> None:
    """整段点击互动：先劈雷传导，余电将灭时狼才钻出来。"""
    if t < 0.0 or t > BITE_SEC:
        return
    paint_strike_conduct(layer, t, cx, cy, radius=radius, stage=stage, light=light)
    if t >= WOLF_AT - 0.04:
        paint_wolf_bite(layer, t - WOLF_AT, stage=stage, light=light)


def _wolf_head(size: int, jaw: int, arc: tuple[int, int, int], *, gain: float) -> Image.Image:
    """侧面狼头，朝左。jaw 是下颌张开度数（按档缓存）。

    画布 (2·size)×size：头在左、颈背拖到右外，贴卡时身子连着卡片外。
    背深腹浅、吻部折角、口内暗红，小尺寸也比纯剪影多几分「狼相」。"""
    key = (size, jaw, arc, int(gain * 20))
    got = _WOLF_CACHE.get(key)
    if got is not None:
        return got
    im = Image.new("RGBA", (size * 2, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    u = size / 100.0
    lw = max(1, int(round(2.0 * u)))

    def P(pts):
        return [(x * u, y * u) for x, y in pts]

    dark = (16, 18, 28, 252)
    mid = (28, 32, 46, 250)
    cheek = (38, 42, 58, 248)
    rim = (*arc, int(228 * gain))
    tooth = (248, 252, 255, 255)
    mouth_in = (72, 28, 32, 210)
    hinge = (73.0, 53.0)

    def ear(pts):
        d.polygon(P(pts), fill=mid)
        d.line(P(pts + (pts[0],)), fill=rim, width=lw, joint="curve")

    back: list[tuple[float, float]] = []
    bx, by = 92.0, 34.0
    for i in range(10):
        back.append((bx, by))
        back.append((bx + 2.8, by - (2.2 + (i * 5 % 4) * 0.45)))
        bx, by = bx + 9.6, by + 1.7
    back.append((200.0, 52.0))

    top = [
        (2, 44), (8, 37), (18, 32), (30, 28), (42, 25),
        (54, 21), (66, 18), (78, 22), (90, 32),
    ] + back
    lip = [(hinge[0], hinge[1] + 1), (54, 51), (34, 50), (12, 47), (8, 44)]
    d.polygon(P(top + [(200, 100), (74, 100), (68, 76)] + lip), fill=dark)
    # 颊部浅一层，头才立体
    cheek_pts = [(18, 32), (30, 28), (42, 25), (54, 21), (66, 18), (78, 22), (68, 76), (34, 50), (12, 47)]
    d.polygon(P(cheek_pts), fill=cheek)
    d.line(P(top), fill=rim, width=lw, joint="curve")
    d.line(P(lip), fill=(*arc, int(140 * gain)), width=max(1, lw - 1), joint="curve")
    # 吻脊
    d.line(P([(8, 37), (18, 32), (30, 28), (42, 25)]), fill=(*arc, int(90 * gain)), width=1, joint="curve")
    ear(((61, 21), (70, 1), (84, 24)))

    # 颈毛：短笔触，别画成剑龙
    for i in range(8):
        sx = 96 + i * 11
        sy = 34 + i * 1.5
        d.line(P(((sx, sy), (sx + 4, sy - 3), (sx + 7, sy + 1))), fill=(*arc, int(70 * gain)), width=1)

    for fx0, fw, fl in ((10, 4.8, 15), (22, 4.0, 10), (34, 3.4, 7), (46, 3.0, 5)):
        d.polygon(P(((fx0, 48), (fx0 + fw, 48.5), (fx0 + fw * 0.5, 48 + fl))), fill=tooth)

    rad = math.radians(-jaw)
    cos, sin = math.cos(rad), math.sin(rad)

    def rot(p):
        dx, dy = p[0] - hinge[0], p[1] - hinge[1]
        return (hinge[0] + dx * cos - dy * sin, hinge[1] + dx * sin + dy * cos)

    jaw_top = [(71, 54), (54, 55), (32, 53), (12, 50)]
    lower = jaw_top + [(14, 60), (34, 65), (58, 66), (72, 62)]
    d.polygon(P([rot(p) for p in lower]), fill=mid)
    if jaw > 8:
        inner = [(rot(p)[0], rot(p)[1]) for p in jaw_top] + [(rot(p)[0], rot(p)[1]) for p in reversed(jaw_top[:2])]
        d.polygon(P(inner), fill=mouth_in)
    d.line(P([rot(p) for p in lower[3:]]), fill=rim, width=max(1, lw - 1), joint="curve")
    for fx0, fw, fl in ((15, 4.4, 13), (27, 3.6, 9), (39, 3.0, 6)):
        tri = ((fx0, 53), (fx0 + fw, 53.5), (fx0 + fw * 0.5, 53 - fl))
        d.polygon(P([rot(p) for p in tri]), fill=tooth)

    # 眼 + 眉骨：细长斜眼，尖头朝吻
    ex, ey = 56.0, 30.0
    d.polygon(P(((ex - 7, ey + 2), (ex + 5, ey - 2), (ex + 5.5, ey + 2.5))), fill=(12, 14, 20, 255))
    d.polygon(P(((ex - 4, ey + 0.5), (ex + 3, ey - 1.2), (ex + 3.2, ey + 1.2))), fill=(*arc, 255))
    d.ellipse(((ex - 0.3) * u, (ey - 0.4) * u, (ex + 1.2) * u, (ey + 1.0) * u), fill=(255, 255, 255, 255))
    d.line(P(((ex - 8, ey - 3), (ex + 7, ey - 5.5))), fill=rim, width=max(1, lw - 1))
    # 鼻尖
    d.ellipse(((8.5) * u, (44.5) * u, (12.5) * u, (47.5) * u), fill=(22, 24, 34, 230))
    return _cache_put(_WOLF_CACHE, key, im, cap=28)


WOLF_SEC = BITE_SEC - WOLF_AT  # 狼段时长，供 paint_wolf_bite 归一化


def paint_wolf_bite(layer: Image.Image, t: float, *, stage: str = "run", light: bool = False) -> None:
    """余电将灭时从右边钻出：先电光轮廓凝实，再扑入—咬合—退回。t 从 WOLF_AT 起算。"""
    bw, bh = layer.size
    if bw < 40 or bh < 20 or t < -0.04 or t > WOLF_SEC + 0.05:
        return
    arc, _cloud, _period, gain = _thunder_palette(stage, light=light)
    size = int(bh * 1.12)
    if size < 24:
        return
    u = max(0.0, t) / WOLF_SEC

    # 0~0.28 电光凝形，0.28~0.52 扑入，0.52~0.65 咬合，0.65~0.78 咬住，0.78~1 慢慢退回
    if u < 0.28:
        k = u / 0.28
        travel = 0.0
        jaw = int(30 * k)
        alpha = int(35 + 220 * k)
        electric = True
    elif u < 0.52:
        k = (u - 0.28) / 0.24
        travel = 1.0 - (1.0 - k) ** 2.6
        jaw = 34
        alpha = 255
        electric = k < 0.38
    elif u < 0.65:
        travel = 1.0
        jaw = int(34 * (1.0 - (u - 0.52) / 0.13))
        alpha = 255
        electric = False
    elif u < 0.78:
        travel = 1.0
        jaw = 2
        alpha = 255
        electric = False
    else:
        k = (u - 0.78) / 0.22
        travel = 1.0 - k ** 1.35
        jaw = int(8 + 26 * k)
        alpha = int(255 * (1.0 - k * 0.38))
        electric = False

    x_out, x_in = bw * 1.04, bw - size * 1.82
    x = x_out + (x_in - x_out) * travel
    y = bh * 0.5 - size * 0.48 + bh * 0.08 * (1.0 - travel)
    jaw_q = max(0, min(36, int(round(jaw / 4.0)) * 4))
    head_im = _wolf_head(size, jaw_q, arc, gain=gain)
    if alpha < 255:
        head_im = head_im.copy()
        a = head_im.getchannel("A").point(lambda v: int(v * alpha / 255))
        head_im.putalpha(a)
    head = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    head.paste(head_im, (int(x), int(y)))
    if electric:
        glow = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        glow.paste(head_im, (int(x), int(y)))
        glow = glow.filter(ImageFilter.GaussianBlur(radius=max(2.0, bh / 28)))
        layer.alpha_composite(glow)
    layer.alpha_composite(head)

    if 0.50 < u < 0.72:
        k = (u - 0.50) / 0.22
        bite_x, bite_y = x + size * 0.15, y + size * 0.51
        halo = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        core = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        hd, cd = ImageDraw.Draw(halo), ImageDraw.Draw(core)
        nxt = _rnd(7717)
        for _i in range(12):
            ang = math.radians(nxt(360))
            dist = (8 + nxt(18)) * (0.4 + k * 2.2)
            px, py = bite_x + math.cos(ang) * dist, bite_y + math.sin(ang) * dist
            pr = max(1.0, (3.2 - k * 2.0) * (bh / 92.0))
            hd.ellipse((px - pr * 2.4, py - pr * 2.4, px + pr * 2.4, py + pr * 2.4), fill=(*arc, int(170 * (1.0 - k))))
            cd.ellipse((px - pr, py - pr, px + pr, py + pr), fill=(255, 255, 255, int(255 * (1.0 - k))))
        layer.alpha_composite(halo.filter(ImageFilter.GaussianBlur(radius=max(1.8, bh / 32))))
        layer.alpha_composite(core)
        veil = int(62 * (1.0 - k) * gain)
        if veil > 2:
            layer.alpha_composite(Image.new("RGBA", (bw, bh), (255, 255, 255, veil)))
