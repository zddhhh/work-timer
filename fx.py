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

def _ink_palette(stage: str, *, light: bool = False) -> tuple[tuple[int, int, int], tuple[int, int, int], float]:
    """(浓墨, 淡墨, 增益)。永远深墨；宣纸深浅只改纸色，不把墨反成白雾。"""
    g = 1.0 if light else 0.92
    if stage == "warn":
        return (96, 40, 18), (138, 72, 36), g
    if stage == "done":
        return (36, 40, 42), (70, 78, 76), g * 0.9
    if stage == "idle":
        return (48, 44, 40), (96, 88, 78), g * 0.75
    return (28, 26, 24), (72, 64, 54), g


_PAPER_CACHE: dict[tuple, Image.Image] = {}


def _paper_grain(bw: int, bh: int, *, light: bool) -> Image.Image:
    """宣纸帘纹：横丝为主，点很少。不是电视机雪花。"""
    key = (bw, bh, int(light))
    got = _PAPER_CACHE.get(key)
    if got is not None:
        return got
    im = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    fiber = (118, 104, 82) if light else (96, 86, 70)
    step = 3 if light else 4
    for y in range(1, bh, step):
        aa = 10 + (y * 13 + bw) % (12 if light else 10)
        d.line((0, y, bw, y), fill=(*fiber, aa), width=1)
    seed = (bw * 73856093) ^ (bh * 19349663)
    for _i in range(max(10, bw // 14)):
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        x0 = seed % bw
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        y0 = seed % bh
        ln = 18 + (seed >> 8) % 36
        aa = 12 + (seed >> 16) % 14
        d.line((x0, y0, x0 + ln, y0 + (seed % 5) - 2), fill=(*fiber, aa), width=1)
    px = im.load()
    for _i in range(max(40, (bw * bh) // 70)):
        seed = (seed * 1103515245 + 12345) & 0x7FFFFFFF
        x, y = seed % bw, (seed >> 10) % bh
        px[x, y] = (*fiber, 14 + (seed >> 20) % 16)
    if len(_PAPER_CACHE) > 8:
        _PAPER_CACHE.clear()
    _PAPER_CACHE[key] = im
    return im


def _wobble(r: float, ang: float, phase: float, amount: float) -> float:
    return r * (
        1.0
        + amount * math.sin(2.0 * ang + phase)
        + amount * 0.62 * math.sin(5.0 * ang - phase * 0.7)
        + amount * 0.4 * math.sin(3.0 * ang + 1.15)
    )


def _blob_pts(cx: float, cy: float, rx: float, ry: float, phase: float, n: int = 22) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(n):
        a = (i / n) * math.pi * 2.0
        rr = _wobble(1.0, a, phase, 0.18)
        pts.append((cx + math.cos(a) * rx * rr, cy + math.sin(a) * ry * rr))
    return pts


def _ring_pts(cx: float, cy: float, r: float, phase: float, n: int = 40) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(n):
        a = (i / n) * math.pi * 2.0
        rr = _wobble(r, a, phase, 0.11)
        pts.append((cx + math.cos(a) * rr, cy + math.sin(a) * rr * 0.78))
    return pts


def _draw_closed(d: ImageDraw.ImageDraw, pts: list[tuple[float, float]], *, fill=None, outline=None, width: int = 1) -> None:
    if len(pts) < 3:
        return
    if fill is not None:
        d.polygon(pts, fill=fill)
    if outline is not None and width > 0:
        d.line(pts + [pts[0]], fill=outline, width=width)


def paint_inkpulse(layer: Image.Image, phase: float, *, stage: str, radius: int, light: bool = False) -> None:
    """墨水涟漪：宣纸 + 字左墨右。一滴落在右侧，不规则墨渍洇开，再漾一两圈歪环。"""
    bw, bh = layer.size
    if bw < 40 or bh < 20:
        return
    c1, c2, gain = _ink_palette(stage, light=light)
    scale = max(0.7, min(2.4, bh / 92.0))
    # 落点在右侧空白，避开左边大数字
    cx = bw * 0.74
    cy = bh * 0.54
    layer.alpha_composite(_paper_grain(bw, bh, light=light))

    cyc = 4.8 if stage == "warn" else (11.0 if stage == "idle" else 7.4)
    g = 0.0 if stage == "done" else (phase % cyc)
    seed = int(phase / cyc) * 9973 if stage != "done" else 4242
    jx = ((seed % 11) - 5) * 0.7 * scale
    jy = (((seed >> 4) % 9) - 4) * 0.5 * scale
    dx, dy = cx + jx, cy + jy
    drop_u = 1.0 if stage == "done" else min(1.0, g / 2.35)

    # 残留墨渍：大晕要糊、墨心要实，不然只是一摊脏污
    wash = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    core = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    wd, cd = ImageDraw.Draw(wash), ImageDraw.Draw(core)
    settle = 0.72 + 0.28 * min(1.0, drop_u / 0.35) if stage != "idle" else 0.7
    if stage == "idle":
        settle *= 0.85
    breath = 1.0 if stage == "done" else (0.97 + 0.03 * math.sin(phase * 0.55))
    _draw_closed(
        wd,
        _blob_pts(dx, dy, bh * 0.36 * settle * breath, bh * 0.26 * settle * breath, phase * 0.35 + 0.4),
        fill=(*c2, int(70 * gain)),
    )
    _draw_closed(
        wd,
        _blob_pts(dx, dy, bh * 0.22 * settle * breath, bh * 0.16 * settle * breath, phase * 0.35 + 1.1),
        fill=(*c1, int(88 * gain)),
    )
    _draw_closed(
        cd,
        _blob_pts(dx, dy, bh * 0.10 * settle * breath, bh * 0.078 * settle * breath, phase * 0.35 + 2.0),
        fill=(*c1, int(200 * gain)),
    )
    layer.alpha_composite(wash.filter(ImageFilter.GaussianBlur(radius=max(2.8, 4.2 * scale))))
    layer.alpha_composite(core.filter(ImageFilter.GaussianBlur(radius=max(0.7, 1.05 * scale))))

    # 沿帘纹的短洇：墨顺着纸纹走一点
    if settle > 0.4:
        bleed = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        bd = ImageDraw.Draw(bleed)
        for i in range(5):
            ang = -0.35 + i * 0.22
            ln = (10 + i * 3) * scale * settle
            aa = int(36 * gain * settle)
            bd.line(
                (dx, dy, dx + math.cos(ang) * ln, dy + math.sin(ang) * ln * 0.25),
                fill=(*c2, aa),
                width=1,
            )
        layer.alpha_composite(bleed.filter(ImageFilter.GaussianBlur(radius=max(1.2, 1.8 * scale))))

    if stage != "done" and g < 2.35:
        splash = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        pd = ImageDraw.Draw(splash)
        # 落墨点：前 0.18 周期里一滴砸下去
        if g < 0.22:
            k = 1.0 - g / 0.22
            pr = (6.5 * k + 2.2) * scale
            pd.ellipse((dx - pr, dy - pr * 1.15, dx + pr, dy + pr * 0.7), fill=(*c1, int(220 * gain * k)))
        # 两圈歪环，第二圈晚半拍
        max_r = bh * 0.70
        for delay, col, thick in ((0.0, c1, 3.2), (0.18, c2, 2.2)):
            u = (drop_u - delay) / max(0.01, 1.0 - delay)
            if u <= 0.0 or u >= 1.0:
                continue
            fade = max(0.0, 1.0 - (u ** 1.35))
            rr = (7.0 + u * max_r) * scale
            aa = int((210 if light else 190) * gain * fade)
            w = max(2, int(round((thick - u * 1.2) * scale)))
            if aa > 12:
                pts = _ring_pts(dx, dy, rr, phase * 1.4 + delay * 4.0)
                _draw_closed(pd, pts, outline=(*col, aa), width=w)
        # 几点飞白/溅墨
        if 0.05 < g < 0.9:
            fu = (g - 0.05) / 0.85
            for i in range(5):
                s = (seed + i * 104729) & 0xFFFF
                ang = (s % 360) * math.pi / 180.0
                dist = (10 + (s >> 4) % 18) * (0.4 + fu) * scale
                px = dx + math.cos(ang) * dist
                py = dy + math.sin(ang) * dist * 0.7
                pr = (1.4 + (s >> 9) % 3) * scale * (1.0 - fu)
                aa = int(160 * gain * (1.0 - fu))
                if aa > 8 and pr > 0.6:
                    pd.ellipse((px - pr, py - pr, px + pr, py + pr), fill=(*c1, aa))
        layer.alpha_composite(splash.filter(ImageFilter.GaussianBlur(radius=max(0.55, 0.8 * scale))))
    elif stage == "done":
        dry = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        _draw_closed(
            ImageDraw.Draw(dry),
            _ring_pts(dx, dy, bh * 0.38, 1.7),
            outline=(*c2, int(70 * gain)),
            width=max(1, int(round(1.6 * scale))),
        )
        layer.alpha_composite(dry.filter(ImageFilter.GaussianBlur(radius=max(0.8, 1.1 * scale))))

    _ = radius  # 圆角由 ornaments 蒙版处理；保留参数与 neonflow 签名一致
