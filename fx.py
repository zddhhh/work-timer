"""程序化皮肤特效：国旗星组（国庆皮）、霓虹流光 HUD、宣纸山水（墨水涟漪）、翻牌时钟。全部按帧绘制，不依赖生图。"""
from __future__ import annotations

import math

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

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


# ---- 霓虹四弹：四色绕边流光 → 点击缺一颗、中心射出同色弹 → 沿边补回

NEON_BULLETS = 4
NEON_FIRE_SEC = 0.34
NEON_REPLENISH_SEC = 1.18
NEON_SHOT_SEC = NEON_FIRE_SEC + NEON_REPLENISH_SEC
NEON_CLICK_SEC = NEON_SHOT_SEC
NEON_RECOIL_SEC = 0.14
NEON_CLICK_COOLDOWN = 0.16
NEON_SLOT_OFFSET = tuple(i * 0.25 + _hash01(i + 11, 53) * 0.065 for i in range(NEON_BULLETS))


class NeonAmmo:
    """四颗边框子弹的弹药状态。"""

    __slots__ = ("present", "shots", "last_click", "_pick")

    def __init__(self) -> None:
        self.present = [1.0] * NEON_BULLETS
        self.shots: list[tuple[float, int, float, float, bool]] = []  # start, slot, tx, ty, hit_done
        self.last_click = 0.0
        self._pick = 0


def create_neon_ammo() -> NeonAmmo:
    return NeonAmmo()


def _perim_lerp(u0: float, u1: float, t: float) -> float:
    d = (u1 - u0) % 1.0
    if d > 0.5:
        d -= 1.0
    return (u0 + d * t) % 1.0


def _neon_bullet_colors(
    c1: tuple[int, int, int], c2: tuple[int, int, int], *, light: bool
) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    if light:
        return c1, c2, (255, 138, 48), (168, 92, 255)
    return c1, c2, (255, 228, 96), (196, 72, 255)


def _slot_u(head: float, slot: int) -> float:
    return (head + NEON_SLOT_OFFSET[slot]) % 1.0


def _slot_firing(ammo: NeonAmmo, slot: int, now: float) -> bool:
    for s, sl, _tx, _ty, _done in ammo.shots:
        if sl != slot:
            continue
        if 0.0 <= now - s < NEON_FIRE_SEC:
            return True
    return False


def neon_tick(ammo: NeonAmmo, now: float) -> None:
    """按时间推进补弹进度并清理过期射击。"""
    for s, slot, _tx, _ty, _done in ammo.shots:
        age = now - s
        if age > NEON_FIRE_SEC:
            rep = min(1.0, (age - NEON_FIRE_SEC) / NEON_REPLENISH_SEC)
            ammo.present[slot] = max(ammo.present[slot], rep)
    ammo.shots = [
        (s, sl, tx, ty, done) for s, sl, tx, ty, done in ammo.shots if now - s < NEON_SHOT_SEC
    ]


def neon_try_fire(
    ammo: NeonAmmo,
    now: float,
    tx: float,
    ty: float,
    *,
    bw: int,
    bh: int,
    radius: int,
    phase: float,
    stage: str = "run",
    light: bool = False,
) -> bool:
    """选一颗绕边流光：边框即时缺位，中心立刻射出同色弹。无弹或冷却中则忽略。"""
    if now - ammo.last_click < NEON_CLICK_COOLDOWN:
        return False
    neon_tick(ammo, now)
    ready: list[int] = []
    for i in range(NEON_BULLETS):
        if ammo.present[i] >= 0.97 and not _slot_firing(ammo, i, now):
            ready.append(i)
    if not ready:
        return False
    _total, point = _perimeter(bw, bh, float(radius), 1.5)
    _c1, _c2, period, _gain = _stage_palette(stage, light=light)
    head = (phase / period) % 1.0
    best = ready[0]
    best_d = 1e18
    for i in ready:
        hx, hy = point(_slot_u(head, i))
        d = (hx - tx) ** 2 + (hy - ty) ** 2
        if d < best_d:
            best_d, best = d, i
    ammo.present[best] = 0.0
    ammo.shots.append((now, best, tx, ty, False))
    ammo.last_click = now
    ammo._pick = (best + 1) % NEON_BULLETS
    return True


def neon_ammo_signature(ammo: NeonAmmo, now: float) -> str:
    neon_tick(ammo, now)
    pres = ",".join(str(int(p * 24)) for p in ammo.present)
    shots = ",".join(f"{sl}:{int((now - s) * 48)}" for s, sl, _x, _y, _d in ammo.shots)
    return f"{pres}|{shots}"


def neon_recoil(now: float, ammo: NeonAmmo) -> tuple[float, float]:
    dx = dy = 0.0
    for s, _sl, _tx, _ty, _done in ammo.shots:
        age = now - s
        if age < NEON_RECOIL_SEC + 0.06:
            k = 1.0 - age / (NEON_RECOIL_SEC + 0.06)
            dx += math.sin(s * 17.3) * 2.4 * k
            dy -= 3.2 * k
    return dx, dy


# ---- 霓虹星球：漂浮小行星，命中爆炸，不足时自动补刷

NEON_PLANET_MIN = 3
NEON_PLANET_MAX = 7
NEON_PLANET_SPAWN_GAP = 1.65
NEON_EXPLODE_SEC = 0.62
NEON_PLANET_HIT_PAD = 11.0


class NeonPlanets:
    """卡片内漂浮的霓虹小星球。"""

    __slots__ = ("planets", "explosions", "last_spawn", "_nid", "_bw", "_bh")

    def __init__(self) -> None:
        self.planets: list[tuple[int, float, float, float, int, float]] = []
        # id, bx, by, br, color_i, drift_off
        self.explosions: list[tuple[float, float, float, float, int]] = []
        # start, x, y, br, color_i
        self.last_spawn = 0.0
        self._nid = 1
        self._bw = 0
        self._bh = 0


def create_neon_planets() -> NeonPlanets:
    return NeonPlanets()


def _neon_planet_target(bw: int, bh: int) -> int:
    area = max(1, bw * bh)
    base = NEON_PLANET_MIN + area // 14000
    return max(NEON_PLANET_MIN, min(NEON_PLANET_MAX, base))


def _neon_planet_pos(
    planet: tuple[int, float, float, float, int, float],
    phase: float,
    bw: int,
    bh: int,
) -> tuple[float, float, float]:
    _pid, bx, by, br, _ci, off = planet
    scale = max(0.7, min(2.4, bh / 92.0))
    dx = math.sin(phase * 0.38 + off) * 5.5 * scale
    dy = math.cos(phase * 0.31 + off * 1.17) * 4.2 * scale
    return bx + dx, by + dy, br * scale


def _neon_spawn_planet(
    field: NeonPlanets,
    bw: int,
    bh: int,
    *,
    colors_n: int,
) -> bool:
    margin = max(12.0, bh * 0.12)
    cx_avoid, cy_avoid = bw * 0.52, bh * 0.44
    avoid_w, avoid_h = bw * 0.34, bh * 0.38
    pid = field._nid
    field._nid += 1
    scale = max(0.7, min(2.4, bh / 92.0))
    for attempt in range(28):
        h1 = _hash01(pid * 19 + attempt, field._bw + field._bh)
        h2 = _hash01(pid * 37 + attempt, field._bw * 3 + field._bh)
        x = margin + h1 * (bw - 2 * margin)
        y = margin + h2 * (bh - 2 * margin)
        if abs(x - cx_avoid) < avoid_w * 0.5 and abs(y - cy_avoid) < avoid_h * 0.5:
            continue
        br = (4.8 + _hash01(pid, 91) * 4.2) * scale
        ok = True
        for other in field.planets:
            ox, oy, orad = _neon_planet_pos(other, 0.0, bw, bh)
            if (x - ox) ** 2 + (y - oy) ** 2 < (br + orad + 14.0) ** 2:
                ok = False
                break
        if not ok:
            continue
        ci = int(_hash01(pid, 53) * colors_n) % colors_n
        drift = _hash01(pid, 71) * math.pi * 2.0
        field.planets.append((pid, x, y, br / scale, ci, drift))
        return True
    return False


def _neon_refill_planets(field: NeonPlanets, bw: int, bh: int, now: float, colors_n: int) -> None:
    target = _neon_planet_target(bw, bh)
    while len(field.planets) < target:
        if not _neon_spawn_planet(field, bw, bh, colors_n=colors_n):
            break
        field.last_spawn = now


def neon_planets_resize(field: NeonPlanets, bw: int, bh: int, now: float, colors_n: int = 4) -> None:
    if field._bw == bw and field._bh == bh:
        return
    if field._bw > 0 and field._bh > 0 and field.planets:
        sx, sy = bw / field._bw, bh / field._bh
        scaled: list[tuple[int, float, float, float, int, float]] = []
        for pid, bx, by, br, ci, off in field.planets:
            scaled.append((pid, bx * sx, by * sy, br * (sx + sy) * 0.5, ci, off))
        field.planets = scaled
    else:
        field.planets.clear()
        _neon_refill_planets(field, bw, bh, now, colors_n)
    field._bw, field._bh = bw, bh


def neon_planets_tick(
    field: NeonPlanets,
    ammo: NeonAmmo,
    now: float,
    bw: int,
    bh: int,
    phase: float,
    *,
    colors_n: int = 4,
) -> None:
    """推进爆炸、解析命中、数量不足时补刷星球。"""
    neon_planets_resize(field, bw, bh, now, colors_n)
    field.explosions = [
        (s, x, y, br, ci) for s, x, y, br, ci in field.explosions if now - s < NEON_EXPLODE_SEC
    ]
    ox, oy = bw * 0.52, bh * 0.48
    new_shots: list[tuple[float, int, float, float, bool]] = []
    for s, sl, tx, ty, done in ammo.shots:
        if done:
            new_shots.append((s, sl, tx, ty, True))
            continue
        age = now - s
        if age < NEON_FIRE_SEC * 0.55:
            new_shots.append((s, sl, tx, ty, False))
            continue
        prog = min(1.0, age / (NEON_FIRE_SEC * 0.9))
        ease = 1.0 - (1.0 - prog) ** 2.2
        bx = ox + (tx - ox) * ease
        by = oy + (ty - oy) * ease
        hit = False
        remain: list[tuple[int, float, float, float, int, float]] = []
        for planet in field.planets:
            px, py, pr = _neon_planet_pos(planet, phase, bw, bh)
            if not hit and (bx - px) ** 2 + (by - py) ** 2 <= (pr + NEON_PLANET_HIT_PAD) ** 2:
                field.explosions.append((now, px, py, pr, planet[4]))
                hit = True
                continue
            remain.append(planet)
        if hit:
            field.planets = remain
            field.last_spawn = now - NEON_PLANET_SPAWN_GAP * 0.35
        new_shots.append((s, sl, tx, ty, hit or age >= NEON_FIRE_SEC * 0.92))
    ammo.shots = new_shots

    target = _neon_planet_target(bw, bh)
    if len(field.planets) < target and now - field.last_spawn >= NEON_PLANET_SPAWN_GAP:
        if _neon_spawn_planet(field, bw, bh, colors_n=colors_n):
            field.last_spawn = now


def neon_planets_animating(field: NeonPlanets, now: float) -> bool:
    return bool(field.explosions)


def neon_planets_signature(field: NeonPlanets, now: float) -> str:
    ps = ",".join(f"{p[0]}:{int(p[1])}:{int(p[2])}" for p in field.planets)
    ex = ",".join(f"{int((now - s) * 40)}" for s, _x, _y, _br, _ci in field.explosions)
    return f"p{len(field.planets)}-{ps}|x{ex}"


def paint_neon_planets(
    layer: Image.Image,
    field: NeonPlanets,
    phase: float,
    *,
    colors: tuple[tuple[int, int, int], ...],
    stage: str = "run",
    light: bool = False,
    gain: float = 1.0,
) -> None:
    bw, bh = layer.size
    if bw < 40 or bh < 20 or not field.planets:
        return
    scale = max(0.7, min(2.4, bh / 92.0))
    glow = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    core = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    gd, cd = ImageDraw.Draw(glow), ImageDraw.Draw(core)
    for planet in field.planets:
        px, py, pr = _neon_planet_pos(planet, phase, bw, bh)
        col = colors[planet[4] % len(colors)]
        pulse = 0.82 + 0.18 * math.sin(phase * 2.6 + planet[5])
        gr = pr * (2.8 + 0.35 * pulse)
        ga = int(72 * gain * pulse)
        if ga > 2:
            gd.ellipse((px - gr, py - gr, px + gr, py + gr), fill=(*col, ga))
        ring_r = pr * (1.55 + 0.12 * math.sin(phase * 3.1 + planet[0]))
        cd.ellipse(
            (px - ring_r, py - ring_r, px + ring_r, py + ring_r),
            outline=(*col, int(150 * gain * pulse)),
            width=max(1, int(round(1.4 * scale))),
        )
        cd.ellipse((px - pr, py - pr, px + pr, py + pr), fill=(*col, int(200 * gain * pulse)))
        cd.ellipse(
            (px - pr * 0.35, py - pr * 0.35, px + pr * 0.35, py + pr * 0.35),
            fill=(255, 255, 255, int(230 * gain)),
        )
        sat = pr * 1.85
        ang = phase * 0.9 + planet[5]
        sx = px + math.cos(ang) * sat
        sy = py + math.sin(ang) * sat * 0.72
        cd.ellipse((sx - 1.8 * scale, sy - 1.8 * scale, sx + 1.8 * scale, sy + 1.8 * scale), fill=(*col, int(180 * gain)))
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius=max(1.6, 2.4 * scale))))
    layer.alpha_composite(core)


def paint_neon_explosions(
    layer: Image.Image,
    field: NeonPlanets,
    now: float,
    *,
    stage: str = "run",
    light: bool = False,
) -> None:
    bw, bh = layer.size
    if not field.explosions:
        return
    c1, c2, _period, gain = _stage_palette(stage, light=light)
    colors = _neon_bullet_colors(c1, c2, light=light)
    scale = max(0.7, min(2.4, bh / 92.0))
    fx_layer = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(fx_layer)
    for s, x, y, br, ci in field.explosions:
        t = (now - s) / NEON_EXPLODE_SEC
        if t < 0.0 or t > 1.0:
            continue
        col = colors[ci % len(colors)]
        fade = (1.0 - t) ** 1.35
        ring = br * (1.0 + t * 3.8)
        ra = int(190 * gain * fade)
        if ra > 3:
            d.ellipse((x - ring, y - ring, x + ring, y + ring), outline=(*col, ra), width=max(1, int(round(2.2 * scale))))
        flash = br * (1.6 - t * 1.1)
        fa = int(220 * gain * max(0.0, 1.0 - t * 1.8))
        if fa > 3:
            d.ellipse((x - flash, y - flash, x + flash, y + flash), fill=(*col, fa))
        n_sp = 10
        for i in range(n_sp):
            ang = (i / n_sp) * math.pi * 2.0 + s * 0.7
            dist = br * (0.8 + t * 4.5) + math.sin(i * 2.1 + s) * 2.0
            spx = x + math.cos(ang) * dist
            spy = y + math.sin(ang) * dist
            sr = max(1.2, (2.8 - t * 2.0) * scale)
            sa = int(200 * gain * fade * fade)
            if sa > 4:
                d.ellipse((spx - sr, spy - sr, spx + sr, spy + sr), fill=(255, 255, 255, sa))
    layer.alpha_composite(fx_layer.filter(ImageFilter.GaussianBlur(radius=max(0.8, 1.4 * scale))))
    layer.alpha_composite(fx_layer)


def _draw_neon_comet(
    gd: ImageDraw.ImageDraw,
    kd: ImageDraw.ImageDraw,
    point,
    head_u: float,
    col: tuple[int, int, int],
    *,
    spacing: float,
    n_tail: int,
    gain: float,
    scale: float,
    alpha: float = 1.0,
) -> None:
    if alpha < 0.04:
        return
    for k in range(n_tail):
        u = head_u - k * spacing
        f = (1.0 - k / n_tail) * alpha
        px, py = point(u)
        ga = int(150 * gain * f * f)
        gr = (3.2 + 4.5 * f) * scale
        if ga > 3:
            gd.ellipse((px - gr, py - gr, px + gr, py + gr), fill=(*col, ga))
        cr = (0.7 + 1.5 * f) * scale
        ka = int(255 * gain * (0.35 + 0.65 * f))
        kc = (255, 255, 255) if k == 0 else col
        kd.ellipse((px - cr, py - cr, px + cr, py + cr), fill=(*kc, ka))


def _paint_neon_border_bullets(
    layer: Image.Image,
    ammo: NeonAmmo,
    now: float,
    phase: float,
    point,
    colors: tuple[tuple[int, int, int], ...],
    *,
    gain: float,
    scale: float,
    stage: str,
    period: float,
) -> None:
    bw, bh = layer.size
    glow = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    core = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    gd, kd = ImageDraw.Draw(glow), ImageDraw.Draw(core)
    head = (phase / period) % 1.0
    n_tail = 22
    spacing = (0.11 if stage != "warn" else 0.14) / n_tail

    for i in range(NEON_BULLETS):
        col = colors[i]
        hu = _slot_u(head, i)
        if _slot_firing(ammo, i, now):
            continue
        if ammo.present[i] < 0.97:
            goal = hu
            start_u = (goal - 0.24) % 1.0
            cu = _perim_lerp(start_u, goal, _ease_out(ammo.present[i]))
            rep_a = 0.55 + 0.45 * ammo.present[i]
            _draw_neon_comet(
                gd, kd, point, cu, col,
                spacing=spacing * 1.15, n_tail=max(8, n_tail // 2),
                gain=gain, scale=scale * 0.9, alpha=rep_a,
            )
            continue
        pulse = 0.88 + 0.12 * math.sin(phase * 3.4 + i * 1.3)
        _draw_neon_comet(
            gd, kd, point, hu, col,
            spacing=spacing, n_tail=n_tail, gain=gain, scale=scale, alpha=pulse,
        )

    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius=max(2.0, 3.0 * scale))))
    layer.alpha_composite(core)


def _ease_out(t: float) -> float:
    t = max(0.0, min(1.0, t))
    return 1.0 - (1.0 - t) ** 2.4


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


def paint_neonflow(
    layer: Image.Image,
    phase: float,
    *,
    stage: str,
    radius: int,
    light: bool = False,
    ammo: NeonAmmo | None = None,
    ammo_now: float = 0.0,
    planets: NeonPlanets | None = None,
) -> None:
    """霓虹 HUD：色雾 + 仪表底 + 扫描线 + 角标 + 四颗边框子弹 + 偶发故障错位。"""
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

    colors = _neon_bullet_colors(c1, c2, light=light)
    if planets is not None and ammo is not None:
        neon_planets_tick(planets, ammo, ammo_now, bw, bh, phase, colors_n=len(colors))
        paint_neon_planets(layer, planets, phase, colors=colors, stage=stage, light=light, gain=gain)

    # 边框四颗五色绕边流光；射击时缺一颗，中心射出同色弹后再沿边补回
    _total, point = _perimeter(bw, bh, float(radius), 1.5)
    if ammo is not None:
        neon_tick(ammo, ammo_now)
        _paint_neon_border_bullets(
            layer, ammo, ammo_now, phase, point, colors,
            gain=gain, scale=scale, stage=stage, period=period,
        )
    else:
        idle = create_neon_ammo()
        _paint_neon_border_bullets(
            layer, idle, phase, phase, point, colors,
            gain=gain, scale=scale, stage=stage, period=period,
        )

    # 故障：偶发横带错位；窗口很短，避免像整段动画被重置
    cyc = 7.3 if stage != "warn" else 3.1
    g = phase % cyc
    if g < 0.045 and stage != "done":
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


INK_CLICK_SEC = 2.05
MAX_INK_HITS = 5
INK_MERGE_RADIUS = 30.0
INK_MERGE_COOLDOWN = 0.19


def register_ink_hit(
    hits: list[tuple[float, int, int, float]],
    now: float,
    x: int,
    y: int,
) -> list[tuple[float, int, int, float]]:
    """墨水涟漪点击：落墨 + 涟漪，同点合并限频。"""
    alive = [(s, hx, hy, p) for s, hx, hy, p in hits if now - s < INK_CLICK_SEC]
    r2 = INK_MERGE_RADIUS * INK_MERGE_RADIUS
    for i, (s, hx, hy, p) in enumerate(alive):
        if (x - hx) ** 2 + (y - hy) ** 2 <= r2:
            if now - s < INK_MERGE_COOLDOWN:
                return alive
            alive[i] = (now, x, y, min(2.0, p + 0.22))
            return alive
    if len(alive) >= MAX_INK_HITS:
        alive.pop(0)
    alive.append((now, x, y, 1.0))
    return alive


def _ink_splash_at(
    layer: Image.Image,
    dx: float,
    base: float,
    u: float,
    *,
    c1: tuple[int, int, int],
    c2: tuple[int, int, int],
    gain: float,
    scale: float,
    bw: int,
    bh: int,
    phase: float,
    power: float,
) -> None:
    """单点落墨涟漪，u∈[0,1] 为动画进度。"""
    fd = ImageDraw.Draw(layer)
    fall = 0.34
    pwr = min(2.0, max(1.0, power))
    if u < fall:
        v = u / fall
        y = base - bh * 0.55 * (1.0 - v * v)
        rr = (1.4 + 0.8 * v) * scale * (0.92 + 0.08 * pwr)
        fd.ellipse((dx - rr, y - rr * 1.5, dx + rr, y + rr), fill=(*c1, int(220 * gain * pwr)))
        fd.line((dx, y - rr * 3.2, dx, y - rr * 1.3), fill=(*c1, int(82 * gain)), width=max(1, int(scale)))
    else:
        v = (u - fall) / (1.0 - fall)
        cloud_a = int(58 * gain * max(0.0, 1.0 - v * 1.1) * pwr)
        if cloud_a > 4:
            cloud = Image.new("RGBA", (layer.size[0], layer.size[1]), (0, 0, 0, 0))
            _draw_closed(
                ImageDraw.Draw(cloud),
                _blob_pts(
                    dx,
                    base + (bh - base) * (0.16 + 0.32 * v),
                    bw * 0.065 * (0.55 + v * 2.0) * pwr,
                    (bh - base) * 0.12 * (0.55 + v * 1.3) * pwr,
                    phase * 0.5,
                ),
                fill=(*c2, cloud_a),
            )
            layer.alpha_composite(cloud.filter(ImageFilter.GaussianBlur(radius=max(1.6, 2.4 * scale))))
        for k, delay in enumerate((0.0, 0.12, 0.26, 0.42)):
            vv = (v - delay) / max(0.05, 1.0 - delay)
            if not 0.0 < vv < 1.0:
                continue
            fade = (1.0 - vv) ** 1.1
            rx = 4.5 * scale + vv * bw * 0.34 * pwr
            ry = max(1.0, rx * 0.16)
            box = (dx - rx, base - ry, dx + rx, base + ry)
            aa = int((148 - k * 24) * gain * fade * pwr)
            if aa > 6:
                w = 1 if k else max(1, int(round(1.5 * scale * (0.4 + fade))))
                fd.arc(box, 12, 168, fill=(*c1, aa), width=w)
                fd.arc(box, 196, 344, fill=(*c2, int(aa * 0.45)), width=1)
        if v < 0.22:
            fu = v / 0.22
            for i in range(4):
                s = (int(dx * 17 + dy_seed(dx)) + i * 104729) & 0xFFFF
                sx = dx + ((s % 29) - 14) * 0.85 * scale * (0.4 + fu * 1.6)
                sy = base - (3 + (s >> 5) % 6) * scale * (1.0 - fu)
                pr = (0.9 + (s >> 9) % 2) * scale * (1.0 - fu)
                if pr > 0.45:
                    fd.ellipse((sx - pr, sy - pr, sx + pr, sy + pr), fill=(*c1, int(165 * gain * (1.0 - fu))))


def dy_seed(x: float) -> int:
    return int(x * 3.7) & 0xFFFF


def paint_ink_click(
    layer: Image.Image,
    t: float,
    cx: float,
    cy: float,
    *,
    stage: str = "run",
    light: bool = False,
    power: float = 1.0,
) -> None:
    """点击落墨：墨滴飞向水面落点，再漾开涟漪。"""
    if t < 0.0 or t > INK_CLICK_SEC:
        return
    bw, bh = layer.size
    if bw < 40 or bh < 20:
        return
    c1, c2, _cs, gain = _ink_palette(stage, light=light)
    scale = max(0.7, min(2.4, bh / 92.0))
    base = bh * _WATER_Y
    dx = max(bw * 0.12, min(bw * 0.94, cx))
    # 落点压到水面一带：点得高也落在水线上
    u = min(1.0, t / (INK_CLICK_SEC * 0.92))
    ink = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    _ink_splash_at(ink, dx, base, u, c1=c1, c2=c2, gain=gain, scale=scale, bw=bw, bh=bh, phase=t, power=power)
    layer.alpha_composite(ink.filter(ImageFilter.GaussianBlur(radius=max(0.35, 0.5 * scale))))


def paint_neon_reticle(
    layer: Image.Image,
    mx: float,
    my: float,
    phase: float,
    *,
    stage: str = "run",
    light: bool = False,
) -> None:
    """跟随鼠标的瞄准环：比仪表十字更亮更大。"""
    bw, bh = layer.size
    if bw < 40 or bh < 20:
        return
    if mx < 0 or my < 0 or mx > bw or my > bh:
        return
    c1, c2, _period, gain = _stage_palette(stage, light=light)
    scale = max(0.7, min(2.4, bh / 92.0))
    breath = 0.72 + 0.28 * math.sin(phase * 5.2)
    d = ImageDraw.Draw(layer)
    gap = max(3.0, bh * 0.055)
    arm = max(10.0, bh * 0.19)
    w = max(1, int(round(1.8 * scale)))
    aa = int(175 * gain * breath)
    for sign in (-1, 1):
        d.line((mx + sign * gap, my, mx + sign * arm, my), fill=(*c1, aa), width=w)
        d.line((mx, my + sign * gap, mx, my + sign * arm), fill=(*c2, aa), width=w)
    r0 = max(5.0, bh * 0.075)
    r1 = r0 + max(3.0, bh * 0.05)
    d.ellipse((mx - r1, my - r1, mx + r1, my + r1), outline=(*c2, int(120 * gain * breath)), width=w)
    d.ellipse((mx - r0, my - r0, mx + r0, my + r0), outline=(*c1, int(200 * gain * breath)), width=max(1, w - 1))
    d.ellipse((mx - 2.2 * scale, my - 2.2 * scale, mx + 2.2 * scale, my + 2.2 * scale), fill=(255, 255, 255, int(210 * gain)))


def paint_neon_fire_shot(
    layer: Image.Image,
    t: float,
    ox: float,
    oy: float,
    tx: float,
    ty: float,
    *,
    col: tuple[int, int, int],
    stage: str = "run",
    light: bool = False,
) -> None:
    """从中心射向落点的同色流光（t 为射击阶段内时间 0~NEON_FIRE_SEC）。"""
    if t < 0.0 or t > NEON_FIRE_SEC:
        return
    bw, bh = layer.size
    _c1, c2, _period, gain = _stage_palette(stage, light=light)
    c1 = col
    scale = max(0.7, min(2.4, bh / 92.0))
    prog = min(1.0, t / (NEON_FIRE_SEC * 0.88))
    ease = 1.0 - (1.0 - prog) ** 2.2
    hx = ox + (tx - ox) * ease
    hy = oy + (ty - oy) * ease
    fade = max(0.0, 1.0 - max(0.0, t - NEON_FIRE_SEC * 0.55) / (NEON_FIRE_SEC * 0.5))
    glow = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    core = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    gd, cd = ImageDraw.Draw(glow), ImageDraw.Draw(core)
    n_seg = 14
    pts: list[tuple[float, float]] = []
    for i in range(n_seg + 1):
        k = i / n_seg
        px = ox + (hx - ox) * k + math.sin(k * 9.0 + t * 22.0) * scale * 0.35 * (1.0 - k)
        py = oy + (hy - oy) * k
        pts.append((px, py))
    for i in range(len(pts) - 1):
        f = (1.0 - i / len(pts)) * fade
        gd.line([pts[i], pts[i + 1]], fill=(*c2, int(150 * gain * f)), width=max(2, int(round(4.5 * scale * f))))
        cd.line([pts[i], pts[i + 1]], fill=(255, 255, 255, int(220 * gain * f)), width=max(1, int(round(1.6 * scale * f))))
    br = max(5.0, 10.0 * scale) * fade
    gd.ellipse((hx - br, hy - br, hx + br, hy + br), fill=(*c1, int(120 * gain * fade)))
    cd.ellipse((hx - br * 0.35, hy - br * 0.35, hx + br * 0.35, hy + br * 0.35), fill=(255, 255, 255, int(240 * gain * fade)))
    if t < 0.10:
        m = t / 0.10
        mr = max(4.0, 8.0 * scale) * (1.0 - m * 0.35)
        gd.ellipse((ox - mr, oy - mr, ox + mr, oy + mr), fill=(*c1, int(170 * gain * (1.0 - m * 0.5))))
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius=max(2.0, 3.2 * scale))))
    layer.alpha_composite(core)


def paint_neon_active_shots(
    layer: Image.Image,
    ammo: NeonAmmo,
    now: float,
    *,
    stage: str = "run",
    light: bool = False,
) -> None:
    """绘制从中心射出的同色光束（overlay 层）。"""
    bw, bh = layer.size
    ox, oy = bw * 0.52, bh * 0.48
    c1, c2, _period, gain = _stage_palette(stage, light=light)
    colors = _neon_bullet_colors(c1, c2, light=light)
    for s, sl, tx, ty, _done in ammo.shots:
        age = now - s
        if age < NEON_FIRE_SEC:
            paint_neon_fire_shot(
                layer, age, ox, oy, tx, ty,
                col=colors[sl], stage=stage, light=light,
            )


# ---------------------------------------------------------------- 翻牌时钟

FLIP_ANIM_SEC = 0.36
FLIP_TAP_SEC = 0.32

_FLIP_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}
_FLIP_UNIT_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}


def _flip_font(size: int) -> ImageFont.ImageFont:
    import os
    from pathlib import Path

    size = max(10, min(40, size))
    got = _FLIP_FONT_CACHE.get(size)
    if got is not None:
        return got
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("bahnschrift.ttf", "arialbd.ttf", "consola.ttf", "msyhbd.ttc"):
        try:
            font = ImageFont.truetype(str(windir / name), size)
            _FLIP_FONT_CACHE[size] = font
            return font
        except OSError:
            continue
    font = ImageFont.load_default()
    _FLIP_FONT_CACHE[size] = font
    return font


def _flip_unit_font(size: int) -> ImageFont.ImageFont:
    import os
    from pathlib import Path

    size = max(9, min(22, size))
    got = _FLIP_UNIT_FONT_CACHE.get(size)
    if got is not None:
        return got
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("msyh.ttc", "msyhbd.ttc", "simhei.ttf", "msyh.ttf"):
        try:
            font = ImageFont.truetype(str(windir / name), size)
            _FLIP_UNIT_FONT_CACHE[size] = font
            return font
        except OSError:
            continue
    font = ImageFont.load_default()
    _FLIP_UNIT_FONT_CACHE[size] = font
    return font


MIN_FLIP_H = 40


def _font_line_height(font: ImageFont.ImageFont, sample: str = "距") -> int:
    bb = font.getbbox(sample or " ")
    return max(8, bb[3] - bb[1])


def flip_row_layout(
    w: int,
    h: int,
    *,
    title_h: int,
    has_sub: bool,
) -> tuple[int, int, int, int, int]:
    """翻牌行布局：返回 (title_y, flip_pad, row_y, row_w, row_h)，保证不压住标题。"""
    h = max(MIN_FLIP_H, int(h))
    title_h = max(7, title_h)
    top_margin = max(6, int(h * 0.11))
    title_gap = max(4, int(h * 0.055))
    bottom_margin = int(h * 0.16) if has_sub else max(6, int(h * 0.10))
    min_row = 20 if h < 72 else 18
    row_budget = max(min_row, h - top_margin - bottom_margin - title_h - title_gap)
    row_h = max(min_row, min(int(h * 0.46), row_budget))
    # 窗口拉高后翻牌别跟着长到失调，标题会显得过小
    if h >= 104:
        row_h = min(row_h, max(44, int(50 + (h - 104) * 0.08)))
    content_h = title_h + title_gap + row_h
    inner = max(16, h - top_margin - bottom_margin)
    block_top = top_margin + max(0, (inner - content_h) // 2)
    title_y = block_top
    row_y = block_top + title_h + title_gap
    flip_pad = max(4, min(14, w // 16))
    row_w = max(36, w - flip_pad * 2)
    return title_y, flip_pad, row_y, row_w, row_h


def _flip_palette(stage: str, light: bool) -> tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]]:
    """面板、铰链、数字、单位字色。"""
    if stage == "warn":
        digit, led = (255, 214, 140), (255, 96, 64)
    elif stage == "done":
        digit, led = (190, 255, 200), (96, 220, 140)
    elif stage == "idle":
        digit, led = (170, 176, 188), (80, 88, 100)
    else:
        digit, led = (248, 250, 255), (220, 72, 52)
    if light:
        panel, hinge, unit = (58, 60, 68), (38, 40, 48), (120, 126, 138)
    else:
        panel, hinge, unit = (28, 30, 36), (14, 15, 18), (108, 114, 126)
    return panel, hinge, digit, unit


def _flip_palette_overlay(
    stage: str,
    light: bool,
    *,
    skin_kind: str = "",
) -> tuple[tuple[int, int, int], tuple[int, int, int], int]:
    """叠在其它皮肤上的翻牌：半透明牌面。墨水涟漪用宣纸色牌，深墙纸可读。"""
    if skin_kind == "inkpulse":
        if light:
            panel, hinge = (248, 242, 228), (148, 128, 108)
        else:
            panel, hinge = (252, 246, 234), (168, 148, 128)
        return panel, hinge, 168
    panel, hinge, _digit, _unit = _flip_palette(stage, light=light)
    if light:
        panel = tuple(int(c * 0.72 + 58) for c in panel)
        hinge = tuple(int(c * 0.65 + 72) for c in hinge)
    else:
        panel = tuple(int(c * 0.85 + 8) for c in panel)
        hinge = tuple(int(c * 0.75 + 18) for c in hinge)
    return panel, hinge, FLIP_OVERLAY_ALPHA


FLIP_OVERLAY_ALPHA = 142


def flip_paper_light(wallpaper_light: bool, flip_light: bool) -> bool:
    """翻牌牌面是否偏浅（墙纸或皮肤配色）。优先用 contrast_text_color(card_light=...)。"""
    return wallpaper_light or flip_light


def contrast_text_color(
    accent: tuple[int, int, int, int],
    *,
    skin_kind: str,
    wallpaper_light: bool,
    stage: str,
    card_light: bool | None = None,
    flip_light: bool = False,
) -> tuple[int, int, int, int]:
    """文字/翻牌对比色：按卡片实际底色压深字或提亮字。"""
    if skin_kind == "inkpulse":
        # 宣纸底永远浅，跟墙纸明暗无关；以前按 wallpaper 反色会把标题打成白字
        paper = card_light if card_light is not None else True
        if paper:
            if stage == "warn":
                return (118, 46, 20, 252)
            if stage == "done":
                return (30, 40, 38, 252)
            if stage == "idle":
                return (58, 50, 42, 252)
            return (28, 24, 20, 252)
        return (252, 248, 238, 255)
    r, g, b, a = accent[0], accent[1], accent[2], accent[3] if len(accent) > 3 else 255
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    paper_light = card_light if card_light is not None else flip_paper_light(wallpaper_light, flip_light)
    if paper_light:
        if lum >= 130:
            if stage == "warn":
                return (168, 68, 22, 255)
            if stage == "done":
                return (22, 108, 52, 255)
            if stage == "idle":
                return (68, 74, 86, 255)
            return (24, 28, 38, 255)
        return (r, g, b, max(a, 252))
    if lum < 165:
        boost = 175 - lum
        return (
            min(255, int(r + boost * 0.55)),
            min(255, int(g + boost * 0.55)),
            min(255, int(b + boost * 0.50)),
            255,
        )
    return (r, g, b, max(a, 252))


def flip_digit_color(
    accent: tuple[int, int, int, int],
    *,
    skin_kind: str,
    wallpaper_light: bool,
    stage: str,
    flip_light: bool = False,
    card_light: bool | None = None,
) -> tuple[int, int, int, int]:
    return contrast_text_color(
        accent,
        skin_kind=skin_kind,
        wallpaper_light=wallpaper_light,
        stage=stage,
        card_light=card_light,
        flip_light=flip_light,
    )


def flip_unit_color(
    digit_color: tuple[int, int, int, int],
    *,
    paper_light: bool,
    overlay: bool,
    stage: str,
) -> tuple[int, int, int, int]:
    """时/分/秒等单位字：与数字同级对比，禁止叠层时再降透明度。"""
    r, g, b, a = digit_color[0], digit_color[1], digit_color[2], digit_color[3] if len(digit_color) > 3 else 255
    a = max(a, 252 if overlay else 255)
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    if paper_light:
        if lum >= 115:
            if stage == "warn":
                return (156, 62, 18, a)
            if stage == "done":
                return (18, 100, 48, a)
            if stage == "idle":
                return (54, 60, 72, a)
            return (18, 22, 32, a)
        return (max(0, r - 6), max(0, g - 6), max(0, b - 8), a)
    if lum < 155:
        boost = 168 - lum
        return (
            min(255, int(r + boost * 0.50)),
            min(255, int(g + boost * 0.50)),
            min(255, int(b + boost * 0.45)),
            a,
        )
    return (r, g, b, a)


def paint_flipclock(layer: Image.Image, phase: float, *, stage: str, radius: int, light: bool = False) -> None:
    """机械外壳：深灰机箱、内框、角钉与状态灯。"""
    bw, bh = layer.size
    if bw < 40 or bh < 20:
        return
    panel, hinge, _digit, _unit = _flip_palette(stage, light=light)
    outer = (tuple(min(255, c + 10) for c in panel) if light else (20, 22, 28))
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle((0, 0, bw - 1, bh - 1), radius=radius, fill=(*outer, 255))
    inset = max(3, int(min(bw, bh) * 0.045))
    d.rounded_rectangle(
        (inset, inset, bw - 1 - inset, bh - 1 - inset),
        radius=max(4, radius - 2),
        fill=(*panel, 255),
        outline=(*hinge, 180),
        width=1,
    )
    screw = (72, 74, 80) if light else (52, 54, 60)
    for sx, sy in (
        (inset + 5, inset + 5),
        (bw - inset - 5, inset + 5),
        (inset + 5, bh - inset - 5),
        (bw - inset - 5, bh - inset - 5),
    ):
        d.ellipse((sx - 2, sy - 2, sx + 2, sy + 2), fill=(*screw, 220))
    pulse = 0.55 + 0.45 * math.sin(phase * (3.2 if stage == "warn" else 1.6))
    led = (255, 88, 64) if stage == "warn" else ((120, 220, 150) if stage == "done" else (220, 72, 52))
    la = int((55 if stage == "idle" else 95) * pulse)
    lx, ly = bw - inset - 9, inset + 7
    d.ellipse((lx - 3, ly - 3, lx + 3, ly + 3), fill=(*led, la))
    _ = hinge


def _flip_groups(text: str) -> list[tuple[str, str]]:
    """按「数字 + 单位」分组，如 128时 / 30分 / 45秒。"""
    s = text or ""
    if not s or not any(c.isdigit() for c in s):
        return []
    groups: list[tuple[str, str]] = []
    i, n = 0, len(s)
    while i < n:
        if not s[i].isdigit():
            i += 1
            continue
        j = i
        while j < n and s[j].isdigit():
            j += 1
        digits = s[i:j]
        i = j
        k = i
        while k < n and not s[k].isdigit():
            k += 1
        groups.append((digits, s[i:k]))
        i = k
    return groups


def _flip_row_metrics(
    groups: list[tuple[str, str]],
    max_w: float,
    row_h: float,
) -> tuple[float, float, float, float, float, int, ImageFont.ImageFont, float]:
    cell_h = row_h * 0.96
    digit_w = cell_h * 0.70
    digit_gap = max(2.0, cell_h * 0.04)
    group_gap = max(6.0, cell_h * 0.16)
    unit_gap = max(3.0, cell_h * 0.08)
    unit_fs = max(12, int(cell_h * 0.56))
    unit_font = _flip_unit_font(unit_fs)

    def total_width(scale: float) -> float:
        total = 0.0
        probe = ImageDraw.Draw(Image.new("RGBA", (1, 1), (0, 0, 0, 0)))
        for gi, (digits, unit) in enumerate(groups):
            if gi:
                total += group_gap * scale
            if digits:
                total += len(digits) * digit_w * scale
                total += max(0, len(digits) - 1) * digit_gap * scale
            if unit:
                total += unit_gap * scale
                total += probe.textlength(unit, font=unit_font) * scale
        return total

    scale = 1.0
    tw = total_width(1.0)
    if tw > max_w and tw > 1.0:
        scale = max(0.54, max_w / tw)
    return (
        digit_w * scale,
        cell_h * scale,
        digit_gap * scale,
        group_gap * scale,
        unit_gap * scale,
        max(9, int(unit_fs * scale)),
        unit_font,
        scale,
    )


def _char_bbox(font: ImageFont.ImageFont, ch: str) -> tuple[int, int]:
    bbox = font.getbbox(ch or "0")
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def _paint_flap_half(
    target: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    ch: str,
    font: ImageFont.ImageFont,
    color: tuple[int, int, int, int],
    panel: tuple[int, int, int],
    *,
    top: bool,
    scale_y: float,
    panel_alpha: int = 255,
    bare: bool = False,
) -> None:
    """绘制翻牌的上/下半片（scale_y 模拟翻转透视）。"""
    if w < 2 or h < 2 or scale_y < 0.03:
        return
    half_h = max(1, h // 2)
    cell = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    cd = ImageDraw.Draw(cell)
    if not bare:
        cd.rounded_rectangle((0, 0, w - 1, h - 1), radius=max(2, h // 7), fill=(*panel, panel_alpha))
    cw, chh = _char_bbox(font, ch)
    tx = (w - cw) // 2
    ty = (h - chh) // 2 - (1 if top else 0)
    if bare:
        _draw_flip_digit(cd, tx, ty, ch, font, color, stroke=True)
    else:
        cd.text((tx, ty), ch, font=font, fill=color)
    mid = h // 2
    if top:
        piece = cell.crop((0, 0, w, mid))
        nh = max(1, int(mid * scale_y))
        piece = piece.resize((w, nh), Image.Resampling.BILINEAR)
        target.alpha_composite(piece, (x, y + mid - nh))
    else:
        piece = cell.crop((0, mid, w, h))
        nh = max(1, int(mid * scale_y))
        piece = piece.resize((w, nh), Image.Resampling.BILINEAR)
        target.alpha_composite(piece, (x, y + mid))


def _flip_text_has_digits(text: str) -> bool:
    return bool(text) and any(c.isdigit() for c in text)


def _draw_flip_digit(
    d: ImageDraw.ImageDraw,
    x: int,
    y: int,
    ch: str,
    font: ImageFont.ImageFont,
    color: tuple[int, int, int, int],
    *,
    stroke: bool,
) -> None:
    """翻牌数字/单位：加描边提升叠层与缩窗下的可读性。"""
    if not stroke:
        d.text((x, y), ch, font=font, fill=color)
        return
    cr, cg, cb = color[0], color[1], color[2]
    lum = 0.2126 * cr + 0.7152 * cg + 0.0722 * cb
    outline = (0, 0, 0, 115) if lum > 150 else (255, 255, 255, 125)
    for ox, oy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        d.text((x + ox, y + oy), ch, font=font, fill=outline)
    d.text((x, y), ch, font=font, fill=color)


def _paint_flap_cell(
    layer: Image.Image,
    x: int,
    y: int,
    w: int,
    h: int,
    shown: str,
    *,
    from_ch: str | None,
    progress: float | None,
    font: ImageFont.ImageFont,
    digit_color: tuple[int, int, int, int],
    panel: tuple[int, int, int],
    hinge: tuple[int, int, int],
    panel_alpha: int = 255,
    overlay: bool = False,
    bare: bool = False,
) -> None:
    d = ImageDraw.Draw(layer)
    if not bare:
        d.rounded_rectangle((x, y, x + w - 1, y + h - 1), radius=max(2, h // 7), fill=(*panel, panel_alpha))
        mid = y + h // 2
        hinge_a = min(255, int(220 * panel_alpha / 255))
        d.line((x + 2, mid, x + w - 3, mid), fill=(*hinge, hinge_a), width=max(1, h // 18))
    digit_stroke = bare or overlay or h < 30
    if progress is None or from_ch is None or from_ch == shown:
        cw, chh = _char_bbox(font, shown)
        tx = x + (w - cw) // 2
        ty = y + (h - chh) // 2
        _draw_flip_digit(d, tx, ty, shown, font, digit_color, stroke=digit_stroke)
        return
    p = max(0.0, min(1.0, progress))
    if p < 0.5:
        ang = p * math.pi
        sy = max(0.04, abs(math.cos(ang)))
        _paint_flap_half(
            layer, x, y, w, h, from_ch, font, digit_color, panel,
            top=True, scale_y=sy, panel_alpha=panel_alpha, bare=bare,
        )
        _paint_flap_half(
            layer, x, y, w, h, from_ch, font, digit_color, panel,
            top=False, scale_y=1.0, panel_alpha=panel_alpha, bare=bare,
        )
    else:
        ang = p * math.pi
        sy = max(0.04, abs(math.cos(ang)))
        _paint_flap_half(
            layer, x, y, w, h, shown, font, digit_color, panel,
            top=True, scale_y=1.0, panel_alpha=panel_alpha, bare=bare,
        )
        _paint_flap_half(
            layer, x, y, w, h, shown, font, digit_color, panel,
            top=False, scale_y=sy, panel_alpha=panel_alpha, bare=bare,
        )


def paint_flip_row(
    img: Image.Image,
    x: int,
    y: int,
    max_w: int,
    row_h: int,
    text: str,
    anims: dict[int, tuple[float, str, str]],
    now: float,
    font_fallback: ImageFont.ImageFont,
    accent: tuple[int, int, int, int],
    *,
    stage: str = "run",
    light: bool = False,
    hit_rects: list[tuple[int, int, int, int, int]] | None = None,
    overlay: bool = False,
    bare_digits: bool = True,
    skin_kind: str = "",
    wallpaper_light: bool = False,
) -> None:
    """翻牌数字行；anims[digit_idx]=(start, old, new)。bare_digits=True 时只画数字翻动，无牌面底块。"""
    groups = _flip_groups(text)
    if bare_digits:
        panel, hinge, panel_alpha = (0, 0, 0), (0, 0, 0), 0
        _digit_rgb, unit_rgb = _flip_palette(stage, light=light)[2:4]
        overlay = False
    elif overlay:
        panel, hinge, panel_alpha = _flip_palette_overlay(stage, light=light, skin_kind=skin_kind)
        _digit_rgb, unit_rgb = _flip_palette(stage, light=light)[2:4]
    else:
        panel, hinge, _digit_rgb, unit_rgb = _flip_palette(stage, light=light)
        panel_alpha = 255
    paper_light = light
    digit_color = contrast_text_color(
        accent,
        skin_kind=skin_kind,
        wallpaper_light=wallpaper_light,
        card_light=light,
        stage=stage,
    )
    unit_color = flip_unit_color(
        digit_color,
        paper_light=paper_light,
        overlay=overlay,
        stage=stage,
    )
    if not groups:
        d = ImageDraw.Draw(img)
        cw, chh = _char_bbox(font_fallback, text or "")
        tx = x + max(0, (max_w - cw) // 2)
        d.text((tx, y + (row_h - chh) // 2), text, font=font_fallback, fill=digit_color)
        if hit_rects is not None:
            hit_rects.clear()
        return
    digit_w, cell_h, digit_gap, group_gap, unit_gap, unit_fs, unit_font, _sc = _flip_row_metrics(
        groups, float(max_w), float(row_h),
    )
    if digit_w <= 0:
        d = ImageDraw.Draw(img)
        d.text((x, y), text, font=font_fallback, fill=digit_color)
        return
    fs = max(12 if cell_h < 26 else 11, int(cell_h * 0.70))
    font = _flip_font(fs)
    unit_font = _flip_unit_font(unit_fs)
    d_probe = ImageDraw.Draw(img)
    tw = 0.0
    for gi, (digits, unit) in enumerate(groups):
        if gi:
            tw += group_gap
        if digits:
            tw += len(digits) * digit_w + max(0, len(digits) - 1) * digit_gap
        if unit:
            tw += unit_gap + d_probe.textlength(unit, font=unit_font)
    cx = float(x) + max(0.0, (float(max_w) - tw) * 0.5)
    cy = int(y + (row_h - cell_h) // 2)
    d_idx = 0
    if hit_rects is not None:
        hit_rects.clear()
    for gi, (digits, unit) in enumerate(groups):
        if gi:
            cx += group_gap
        for di, ch in enumerate(digits):
            if di:
                cx += digit_gap
            w, h = int(digit_w), int(cell_h)
            anim = anims.get(d_idx)
            prog = None
            from_ch = None
            shown = ch
            if anim is not None:
                start, old, new = anim
                elapsed = now - start
                if elapsed < FLIP_ANIM_SEC:
                    prog = elapsed / FLIP_ANIM_SEC
                    from_ch = old
                    shown = new
                else:
                    shown = new
            _paint_flap_cell(
                img, int(cx), cy, w, h, shown,
                from_ch=from_ch, progress=prog,
                font=font, digit_color=digit_color, panel=panel, hinge=hinge,
                panel_alpha=panel_alpha,
                overlay=overlay,
                bare=bare_digits,
            )
            if hit_rects is not None:
                hit_rects.append((int(cx), cy, w, h, d_idx))
            d_idx += 1
            cx += w
        if unit:
            cx += unit_gap
            _, chh = _char_bbox(unit_font, unit)
            uy = cy + (cell_h - chh) // 2
            _draw_flip_digit(
                d_probe, int(cx), uy, unit, unit_font, unit_color,
                stroke=True,
            )
            cx += d_probe.textlength(unit, font=unit_font)


def flip_anim_signature(anims: dict[int, tuple[float, str, str]], now: float) -> str:
    if not anims:
        return ""
    parts = []
    for i in sorted(anims):
        start, old, new = anims[i]
        parts.append(f"{i}:{int((now - start) * 60)}:{old}>{new}")
    return "|".join(parts)


def flip_digits_only(text: str) -> str:
    return "".join(ch for ch in (text or "") if ch.isdigit())


def sync_flip_anims(
    anims: dict[int, tuple[float, str, str]],
    prev_digits: str,
    text: str,
    now: float,
) -> str:
    """对比数字变化，登记翻牌动画；返回新的 prev_digits。"""
    cur = flip_digits_only(text)
    if cur != prev_digits:
        for i, ch in enumerate(cur):
            old = prev_digits[i] if i < len(prev_digits) else ch
            if ch != old:
                anims[i] = (now, old, ch)
        for i in range(len(cur), len(prev_digits)):
            anims.pop(i, None)
        prev_digits = cur
    expire = FLIP_ANIM_SEC + 0.02
    for k in [k for k, (s, _, _) in anims.items() if now - s >= expire]:
        anims.pop(k, None)
    return prev_digits


def flip_digit_index_at(
    hit_rects: list[tuple[int, int, int, int, int]],
    lx: int,
    ly: int,
) -> int | None:
    for x, y, w, h, idx in hit_rects:
        if x <= lx < x + w and y <= ly < y + h:
            return idx
    return None


def flip_tap_digit(
    anims: dict[int, tuple[float, str, str]],
    digits: str,
    idx: int,
    now: float,
) -> None:
    """点击某一格：机械拨动翻一下（纯视觉，下一秒会回到真实读数）。"""
    if idx < 0 or idx >= len(digits):
        return
    ch = digits[idx]
    if not ch.isdigit():
        return
    nxt = str((int(ch) + 1) % 10)
    anims[idx] = (now, ch, nxt)


# ---------------------------------------------------------------- 霹雳狂潮

_STORM_CACHE: dict[tuple, Image.Image] = {}
CLICK_SEC = 2.35  # 单次点击：蓄力→狠雷→劈底→沿边电涌绕一圈→余烬
BITE_SEC = CLICK_SEC  # main / ornaments 沿用旧名
MAX_THUNDER_HITS = 6  # 不同落点最多同时几道
MERGE_RADIUS = 34.0  # 同点半径内合并为一道，刷新动画而非叠满屏
MERGE_COOLDOWN = 0.17  # 同点最快隔这么久才再吃下一记
HIT_POWER_MAX = 2.0  # 同点连刷微增强度，有顶
THUNDER_QUOTE_DEFAULT = "我命由我不由天"  # 仅作设置页示例，默认不启用字效
CHARGE_END = 0.30
STRIKE_START = 0.18
STRIKE_END = 0.72
CONDUCT_START = 0.52
CONDUCT_END = 1.95


def register_thunder_hit(
    hits: list[tuple[float, int, int, float, int]],
    now: float,
    x: int,
    y: int,
    quote_idx: int,
    quote: str = "",
) -> tuple[list[tuple[float, int, int, float, int]], int | None]:
    """登记点击：远处可叠多道；同处连点合并刷新。返回 (hits, 下一字序号) 或忽略时 None。"""
    alive = [(s, hx, hy, p, q) for s, hx, hy, p, q in hits if now - s < CLICK_SEC]
    q = (quote or "").strip()
    nxt = ((quote_idx + 1) % len(q)) if q else None
    r2 = MERGE_RADIUS * MERGE_RADIUS
    for i, (s, hx, hy, p, _q) in enumerate(alive):
        if (x - hx) ** 2 + (y - hy) ** 2 <= r2:
            if now - s < MERGE_COOLDOWN:
                return alive, None
            p = min(HIT_POWER_MAX, p + 0.26)
            alive[i] = (now, x, y, p, quote_idx)
            return alive, nxt
    if len(alive) >= MAX_THUNDER_HITS:
        alive.pop(0)
    alive.append((now, x, y, 1.0, quote_idx))
    return alive, nxt


def _thunder_palette(stage: str, *, light: bool = False) -> tuple[tuple[int, int, int], tuple[int, int, int], float, float]:
    """(电弧色, 雷云色, 落雷周期秒, 增益)"""
    if light:
        gain = 0.78
        if stage == "warn":
            return (220, 108, 198), (148, 118, 168), 1.7, gain
        if stage == "done":
            return (72, 200, 168), (108, 148, 142), 5.5, gain * 0.82
        if stage == "idle":
            return (140, 178, 230), (128, 142, 178), 6.5, gain * 0.7
        return (96, 168, 238), (118, 138, 188), 2.9, gain
    gain = 1.0
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


def _paint_edge_crawl(
    bd: ImageDraw.ImageDraw,
    gd: ImageDraw.ImageDraw,
    cd: ImageDraw.ImageDraw,
    point,
    phase: float,
    arc: tuple[int, int, int],
    *,
    gain: float,
    scale: float,
    n_runners: int,
    seed: int,
    env: float = 1.0,
    alpha_k: float = 1.0,
) -> None:
    """沿圆角矩形边框爬行的电弧，起点/速度每周期随机。"""
    if n_runners <= 0 or env < 0.02:
        return
    nxt = _rnd(seed)
    for k in range(n_runners):
        spd = 2.2 + nxt(50) / 18.0 + k * 0.35
        head = (phase / spd + nxt(1000) / 1000.0) % 1.0
        n_pt = 8 + nxt(4)
        jig: list[tuple[float, float]] = []
        for i in range(n_pt):
            u = (head + i * 0.0065) % 1.0
            px, py = point(u)
            ax, ay = point((u + 0.002) % 1.0)
            tx, ty = ax - px, ay - py
            ln = math.hypot(tx, ty) or 1.0
            amp = 0.0 if i in (0, n_pt - 1) else ((int(phase * 26) + i * 7 + k * 31 + seed) % 7 - 3) * 0.75 * scale
            jig.append((px - ty / ln * amp, py + tx / ln * amp))
        e = min(1.0, env * alpha_k)
        bd.line(jig, fill=(*arc, int(62 * gain * e)), width=max(3, int(round(5.0 * scale))), joint="curve")
        gd.line(jig, fill=(*arc, int(140 * gain * e)), width=max(2, int(round(2.2 * scale))), joint="curve")
        cd.line(jig, fill=(236, 250, 255, int(190 * gain * e)), width=1, joint="curve")


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

    _total, point = _perimeter(bw, bh, float(radius), 2.0)
    cycle_seed = int(phase / period) * 7919 + 13
    nxt_c = _rnd(cycle_seed)
    # 常驻：每周期 4~7 道淡弧，起点随机，避免总在同几段边框上爬
    n_amb = 4 + nxt_c(4)
    _paint_edge_crawl(
        bd, gd, cd, point, phase, arc,
        gain=gain, scale=scale, n_runners=n_amb, seed=cycle_seed + 3,
        env=0.42 if stage != "idle" else 0.28, alpha_k=0.55,
    )
    if env > 0.06:
        n_flash = 5 + nxt_c(4)
        _paint_edge_crawl(
            bd, gd, cd, point, phase, arc,
            gain=gain, scale=scale, n_runners=n_flash, seed=cycle_seed + 97,
            env=env, alpha_k=1.15,
        )

    if env > (0.35 if stage == "idle" else 0.01):
        seed = cycle_seed
        nxt = nxt_c
        # 主雷落点：左右上缘随机，仍尽量避开左侧大数字区
        zone = nxt(5)
        if zone == 0:
            x0 = bw * (0.58 + nxt(30) / 100.0)
            y1 = bh * (0.78 + nxt(22) / 100.0)
        elif zone == 1:
            x0 = bw * (0.72 + nxt(24) / 100.0)
            y1 = bh * (0.55 + nxt(35) / 100.0)
        elif zone == 2:
            x0 = bw * (0.38 + nxt(28) / 100.0)
            y1 = bh * (0.70 + nxt(26) / 100.0)
        else:
            x0 = bw * (0.48 + nxt(40) / 100.0)
            y1 = bh * (0.35 + nxt(40) / 100.0)
        x1 = x0 + (nxt(240) / 1000.0 - 0.12) * bw
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


# ---- 点一下：劈到边框 → 沿边电涌绕一圈 ----

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
    if g < 0.035:
        return 0.60 * g / 0.035
    if g < 0.075:
        return 0.08
    if g < 0.22:
        return 1.0
    if t < STRIKE_END:
        return max(0.0, 1.0 - (t - STRIKE_START - 0.22) / (STRIKE_END - STRIKE_START - 0.22)) * 0.95
    return 0.0


def _paint_fierce_strike(
    bd: ImageDraw.ImageDraw,
    gd: ImageDraw.ImageDraw,
    cd: ImageDraw.ImageDraw,
    *,
    cx: float,
    cy: float,
    hx: float,
    hy: float,
    bw: int,
    bh: int,
    arc: tuple[int, int, int],
    env: float,
    gain: float,
    scale: float,
    seed: int,
) -> None:
    """点击专属狠雷：比常态落雷更粗更亮——天雷砸落点 + 落点劈底 + 多股分叉。"""
    fg = gain * 1.72
    thick = 1.85
    nxt = _rnd(seed)

    sky_x = cx + (nxt(17) - 8) * scale * 0.35
    sky = _bolt_pts(seed, sky_x, -5.0, cx, cy, depth=6, jitter=0.34)
    _draw_bolt(bd, gd, cd, sky, arc, env=env, gain=fg, scale=scale, thick=thick)

    ground = _bolt_pts(seed + 41, cx, cy, hx, hy, depth=6, jitter=0.30)
    _draw_bolt(bd, gd, cd, ground, arc, env=env, gain=fg * 1.12, scale=scale, thick=thick * 1.08)

    for b, base in enumerate((sky, ground, sky)):
        ridge = base[:-2] if len(base) > 4 else base
        i = int(len(ridge) * (0.22 + 0.24 * b))
        bx, by = ridge[min(i, len(ridge) - 1)]
        ang = math.radians(-58 + nxt(116)) + (math.pi if b == 2 else 0.0)
        ln = bh * (0.26 + nxt(26) / 100.0)
        fork = _bolt_pts(
            seed + 977 * (b + 1),
            bx,
            by,
            bx + math.cos(ang) * ln,
            by + abs(math.sin(ang)) * ln,
            depth=4,
            jitter=0.38,
        )
        _draw_bolt(bd, gd, cd, fork, arc, env=env * 0.84, gain=fg, scale=scale, thick=0.72)

    gr = bh * 0.19
    bd.ellipse((cx - gr, cy - gr * 0.75, cx + gr, cy + gr * 0.75), fill=(*arc, int(155 * env * fg)))
    cd.ellipse(
        (cx - gr * 0.35, cy - gr * 0.3, cx + gr * 0.35, cy + gr * 0.3),
        fill=(255, 255, 255, int(240 * env)),
    )
    gr2 = bh * 0.34
    bd.ellipse((hx - gr2, hy - gr2 * 0.58, hx + gr2, hy + gr2 * 0.58), fill=(*arc, int(135 * env * fg)))


def _conduct_progress(t: float) -> tuple[float, float]:
    """(沿边走了多少圈 0~1, 亮度)。缓出绕满四周，尾部留余烬。"""
    if t < CONDUCT_START:
        return 0.0, 0.0
    tc = t - CONDUCT_START
    dur = CONDUCT_END - CONDUCT_START
    p = min(1.0, tc / dur)
    spread = 1.0 - (1.0 - p) ** 2.55
    if tc < 0.06:
        env = tc / 0.06
    elif tc < dur * 0.38:
        env = 1.0
    elif tc < dur + 0.35:
        env = max(0.0, 1.0 - (tc - dur * 0.38) / (dur * 0.62 + 0.35)) ** 0.75
    else:
        env = max(0.0, 0.22 - (tc - dur - 0.35) / 0.45)
    return spread, env


def _jitter_point(
    point,
    u: float,
    direction: int,
    *,
    t: float,
    i: int,
    scale: float,
    amp_k: float,
) -> tuple[float, float]:
    px, py = point(u)
    ax, ay = point((u + 0.0028 * direction) % 1.0)
    tx, ty = ax - px, ay - py
    ln = math.hypot(tx, ty) or 1.0
    amp = ((int(t * 28 + i * 7) % 9) - 4) * 0.85 * scale * amp_k
    return px - ty / ln * amp, py + tx / ln * amp


def _paint_surge_conduct(
    bd,
    gd,
    cd,
    sparks_d,
    *,
    point,
    total: float,
    hit_u: float,
    spread: float,
    cenv: float,
    t: float,
    arc: tuple[int, int, int],
    gain: float,
    scale: float,
    bw: int,
    bh: int,
    cx: float,
    cy: float,
) -> None:
    """双向彗星头 + 余波 + 已走过路径余辉 + 向内电弧 + 转角爆闪。"""
    if spread < 0.01 or cenv < 0.02:
        return
    inset = 2.0
    corners = (
        (inset, inset),
        (bw - 1 - inset, inset),
        (bw - 1 - inset, bh - 1 - inset),
        (inset, bh - 1 - inset),
    )
    mx, my = bw * 0.5, bh * 0.5
    tail_u = min(0.28, 0.10 + spread * 0.20)
    waves = (
        (spread, cenv, tail_u, 1.0),
        (max(0.0, spread - 0.16), cenv * 0.52, tail_u * 0.72, 0.65),
    )

    # 已走过整段路径：淡蓝电篱
    for direction in (1, -1):
        half = spread * 0.5
        n_lit = max(18, int(half * total / 3.2))
        lit: list[tuple[float, float]] = []
        for i in range(n_lit + 1):
            u = (hit_u + direction * (i / n_lit) * half) % 1.0
            lit.append(_jitter_point(point, u, direction, t=t, i=i, scale=scale * 0.35, amp_k=0.4))
        if len(lit) >= 2:
            gd.line(lit, fill=(*arc, int(38 * gain * cenv)), width=max(2, int(round(4.5 * scale))), joint="curve")
            cd.line(lit, fill=(*arc, int(22 * gain * cenv)), width=1, joint="curve")

    for wave_spread, wave_env, wave_tail, wave_gain in waves:
        if wave_spread < 0.02 or wave_env < 0.03:
            continue
        n_seg = max(28, int(wave_tail * total / 2.0))
        for direction in (1, -1):
            head_u = (hit_u + direction * wave_spread * 0.5) % 1.0
            hx, hy = _jitter_point(point, head_u, direction, t=t, i=0, scale=scale, amp_k=1.0)

            # 彗星尾：分段绘，头亮尾淡
            for i in range(n_seg):
                u0 = (head_u - direction * (i / n_seg) * wave_tail) % 1.0
                u1 = (head_u - direction * ((i + 1) / n_seg) * wave_tail) % 1.0
                p0 = _jitter_point(point, u0, direction, t=t, i=i, scale=scale, amp_k=1.0 - i / n_seg * 0.55)
                p1 = _jitter_point(point, u1, direction, t=t, i=i + 1, scale=scale, amp_k=1.0 - (i + 1) / n_seg * 0.55)
                fade = (1.0 - i / n_seg) ** 1.45 * wave_env * wave_gain
                w_b = max(2, int(round((9.0 - i / n_seg * 5.5) * scale)))
                w_g = max(1, int(round((4.5 - i / n_seg * 2.5) * scale)))
                bd.line([p0, p1], fill=(*arc, int(72 * gain * fade)), width=w_b, joint="curve")
                gd.line([p0, p1], fill=(*arc, int(175 * gain * fade)), width=w_g, joint="curve")
                if i < n_seg // 4:
                    cd.line([p0, p1], fill=(248, 252, 255, int(235 * gain * fade)), width=1, joint="curve")

            # 彗星核 + 光环
            hr = max(4.0, 8.5 * scale) * wave_env
            bd.ellipse((hx - hr * 1.5, hy - hr * 1.5, hx + hr * 1.5, hy + hr * 1.5), fill=(*arc, int(95 * gain * wave_env * wave_gain)))
            gd.ellipse((hx - hr, hy - hr, hx + hr, hy + hr), fill=(*arc, int(215 * gain * wave_env * wave_gain)))
            cr = max(2.0, hr * 0.42)
            cd.ellipse((hx - cr, hy - cr, hx + cr, hy + cr), fill=(255, 255, 255, int(250 * gain * wave_env * wave_gain)))

            # 转角爆闪
            if any(math.hypot(hx - cx, hy - cy) < max(9.0, 11.0 * scale) for cx, cy in corners):
                br = max(6.0, 14.0 * scale) * wave_env
                bd.ellipse((hx - br, hy - br, hx + br, hy + br), fill=(*arc, int(120 * gain * wave_env)))
                cd.ellipse((hx - br * 0.35, hy - br * 0.35, hx + br * 0.35, hy + br * 0.35), fill=(255, 255, 255, int(200 * gain * wave_env)))

    # 活跃区向内短电弧
    nxt = _rnd(int(t * 880) + int(hit_u * 1000) + 17)
    n_sparks = int(8 + spread * 22 * cenv)
    for _ in range(n_sparks):
        du = nxt(1000) / 1000.0 * spread * 0.5
        sign = 1 if nxt(2) else -1
        u = (hit_u + sign * du) % 1.0
        px, py = _jitter_point(point, u, sign, t=t, i=nxt(20), scale=scale * 0.6, amp_k=0.5)
        ang = math.atan2(my - py, mx - px) + math.radians(nxt(36) - 18)
        sl = (7 + nxt(22)) * scale * cenv
        ex, ey = px + math.cos(ang) * sl, py + math.sin(ang) * sl
        mx2 = px + math.cos(ang) * sl * 0.42 + (nxt(7) - 3) * scale
        my2 = py + math.sin(ang) * sl * 0.42 + (nxt(7) - 3) * scale
        sparks_d.line((px, py, mx2, my2, ex, ey), fill=(*arc, int(150 * gain * cenv)), width=max(1, int(round(2.2 * scale))), joint="curve")
        sparks_d.line((mx2, my2, ex, ey), fill=(255, 255, 255, int(210 * gain * cenv)), width=1, joint="curve")


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
    power: float = 1.0,
) -> None:
    """点击：蓄力→劈到底边→沿四边慢速传导一圈。"""
    bw, bh = layer.size
    if bw < 40 or bh < 20 or t < 0.0 or t > CONDUCT_END + 0.35:
        return
    arc, _cloud, _period, gain = _thunder_palette(stage, light=light)
    p = min(HIT_POWER_MAX, max(1.0, power))
    strike_gain = gain * min(1.38, 0.88 + 0.22 * p)
    conduct_gain = gain * min(1.14, 0.94 + 0.08 * p)
    scale = max(0.7, min(2.4, bh / 92.0))
    hit_u, hx, hy = _perim_u_at(bw, bh, float(radius), cx, cy)
    env = _strike_env(t)
    spread, cenv = _conduct_progress(t)

    _paint_charge(layer, t, radius, arc, gain=strike_gain, scale=scale)

    bloom = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    glow = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    core = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    sparks = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    bd, gd, cd = ImageDraw.Draw(bloom), ImageDraw.Draw(glow), ImageDraw.Draw(core)
    sparks_d = ImageDraw.Draw(sparks)

    if env > 0.02:
        seed = 8800 + int(cx) * 3 + int(cy)
        _paint_fierce_strike(
            bd, gd, cd, cx=cx, cy=cy, hx=hx, hy=hy, bw=bw, bh=bh,
            arc=arc, env=env, gain=strike_gain, scale=scale, seed=seed,
        )

    if cenv > 0.02 and spread > 0.01:
        total, point = _perimeter(bw, bh, float(radius), 2.0)
        _paint_surge_conduct(
            bd, gd, cd, sparks_d,
            point=point, total=total, hit_u=hit_u, spread=spread, cenv=cenv, t=t,
            arc=arc, gain=conduct_gain, scale=scale, bw=bw, bh=bh, cx=cx, cy=cy,
        )

    blur_k = 1.35 if env > 0.5 else 1.0
    layer.alpha_composite(bloom.filter(ImageFilter.GaussianBlur(radius=max(4.5, 9.5 * scale * blur_k))))
    layer.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius=max(2.0, 3.2 * scale * blur_k))))
    layer.alpha_composite(sparks.filter(ImageFilter.GaussianBlur(radius=max(1.2, 2.0 * scale))))
    layer.alpha_composite(core)
    flash = min(1.22, max(_charge_env(t) * 0.35, env * 1.15, cenv * 0.8) * (0.92 + 0.06 * p))
    if flash > 0.03:
        top = int((210 if env > 0.5 else 175) * flash * strike_gain)
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
    power: float = 1.0,
) -> None:
    """整段点击互动：蓄力→狠雷劈底→沿边电涌绕一圈。"""
    if t < 0.0 or t > CLICK_SEC:
        return
    paint_strike_conduct(layer, t, cx, cy, radius=radius, stage=stage, light=light, power=power)


_GLYPH_FONT_CACHE: dict[int, ImageFont.ImageFont] = {}


def _glyph_font(bh: int, bw: int) -> ImageFont.ImageFont:
    """大号书体：行楷 / 楷 / 隶，尽量有书法感。"""
    import os
    from pathlib import Path

    size = max(32, min(int(bh * 0.88), int(bw * 0.42)))
    got = _GLYPH_FONT_CACHE.get(size)
    if got is not None:
        return got
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("STXINGKA.TTF", "simkai.ttf", "SIMLI.TTF", "STKAITI.TTF", "msyhbd.ttc", "msyh.ttc"):
        try:
            font = ImageFont.truetype(str(windir / name), size)
            _GLYPH_FONT_CACHE[size] = font
            return font
        except OSError:
            continue
    font = ImageFont.load_default()
    _GLYPH_FONT_CACHE[size] = font
    return font


def paint_thunder_glyph(
    layer: Image.Image,
    box: tuple[int, int, int, int],
    t: float,
    quote_idx: int,
    *,
    anchor_x: float | None = None,
    anchor_y: float | None = None,
    stage: str = "run",
    light: bool = False,
    quote: str = "",
) -> None:
    """每次只亮一个字：大号水墨电纹，锚在点击处（画在倒计时数字下层）。"""
    q = (quote or "").strip()
    if t < 0.0 or t > CLICK_SEC * 0.92 or not q:
        return
    x0, y0, x1, y1 = box
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    char = q[quote_idx % len(q)]
    arc, cloud, _period, gain = _thunder_palette(stage, light=light)
    ink = tuple(int(arc[i] * 0.62 + cloud[i] * 0.38) for i in range(3))
    core = tuple(min(255, int(arc[i] * 0.35 + 220)) for i in range(3))

    if t < 0.22:
        env = (t / 0.22) ** 1.25
        flash = min(1.0, t / 0.11) ** 0.8
    elif t < 1.55:
        env = 0.90 + 0.10 * math.sin((t - 0.22) * 1.85)
        flash = 0.0
    else:
        env = max(0.0, 1.0 - (t - 1.55) / 0.65) ** 1.05
        flash = 0.0
    if t < 0.34:
        flash = max(flash, (1.0 - t / 0.34) * 0.72)
    if env < 0.04:
        return

    font = _glyph_font(bh, bw)
    stroke = max(2, int(bh / 28))
    probe = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    bbox = probe.textbbox((0, 0), char, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    glow_pad = max(10, stroke * 4)
    canv = Image.new("RGBA", (tw + glow_pad * 2, th + glow_pad * 2), (0, 0, 0, 0))
    d = ImageDraw.Draw(canv)
    nxt = _rnd(quote_idx * 991 + 17)
    ox = glow_pad - bbox[0] + (nxt(9) - 4)
    oy = glow_pad - bbox[1] + (nxt(7) - 3)
    rot = (nxt(11) - 5) * 0.55

    body_a = min(255, int(118 * env * gain))
    glow_a = min(255, int(72 * env * gain))
    rim_a = min(255, int((48 + 72 * flash) * env * gain))
    if body_a < 8:
        return

    glow = Image.new("RGBA", canv.size, (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    for dx, dy, k in ((0, 0, 1.0), (2, 1, 0.55), (-2, 1, 0.45)):
        gd.text(
            (ox + dx, oy + dy),
            char,
            font=font,
            fill=(*arc, int(glow_a * k)),
            stroke_width=stroke + 1,
            stroke_fill=(*arc, int(glow_a * 0.5 * k)),
        )
    d.text(
        (ox, oy),
        char,
        font=font,
        fill=(*ink, body_a),
        stroke_width=stroke,
        stroke_fill=(12, 16, 28, min(255, int(body_a * 0.55))),
    )
    d.text((ox - 1, oy - 2), char, font=font, fill=(*core, rim_a))
    canv.alpha_composite(glow.filter(ImageFilter.GaussianBlur(radius=max(1.2, bh * 0.024))))

    if abs(rot) > 0.2:
        canv = canv.rotate(rot, resample=Image.Resampling.BICUBIC, expand=True)

    mask = Image.new("L", canv.size, 0)
    md = ImageDraw.Draw(mask)
    mcx, mcy = canv.width // 2, canv.height // 2
    rx, ry = max(10, int(tw * 0.62)), max(8, int(th * 0.68))
    md.ellipse((mcx - rx, mcy - ry, mcx + rx, mcy + ry), fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=max(2.5, bh * 0.05)))
    fade = mask.point(lambda v: min(255, int(v * (0.65 + 0.35 * env))))
    canv.putalpha(ImageChops.multiply(canv.getchannel("A"), fade))

    ax = anchor_x if anchor_x is not None else (x0 + x1) * 0.5
    ay = anchor_y if anchor_y is not None else (y0 + y1) * 0.5
    lx = int(ax - canv.width / 2)
    ly = int(ay - canv.height / 2)
    margin = 2
    lx = max(x0 - margin, min(lx, x1 - canv.width + margin))
    ly = max(y0 - margin, min(ly, y1 - canv.height + margin))
    layer.alpha_composite(canv, (lx, ly))
