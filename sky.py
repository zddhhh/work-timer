"""「天色」皮：一张皮随一天走，日落绑在下班时间上。

t 是「天时」参数 0~1：0 深夜 → 0.25 破晓 → 0.5 正午 → 0.66 金色时刻 → 0.78 日落 → 0.88 黄昏 → 1.0 夜。
剩余 > 30 分钟时按真实钟点走（但压在 0.62 以内，太阳不落）；最后 30 分钟从 0.62 匀速走到 1.0，
到点正好入夜亮星。不用看数字，瞄一眼颜色就知道离下班多远。
"""
from __future__ import annotations

import math
from datetime import datetime

from PIL import Image, ImageChops, ImageDraw

SUNSET_WINDOW_SEC = 30 * 60
_DAY_CAP = 0.62  # 还没进最后 30 分钟时最多走到「傍晚前」

# (t, 天顶色, 地平色)
_KEYS: tuple[tuple[float, tuple[int, int, int], tuple[int, int, int]], ...] = (
    (0.00, (8, 12, 34), (26, 32, 68)),
    (0.10, (18, 20, 56), (60, 44, 92)),
    (0.20, (72, 88, 160), (238, 160, 120)),
    (0.30, (104, 156, 224), (255, 212, 160)),
    (0.42, (96, 168, 240), (196, 226, 250)),
    (0.55, (78, 156, 236), (186, 218, 246)),
    (0.66, (110, 150, 214), (255, 206, 128)),
    (0.76, (98, 84, 156), (255, 130, 78)),
    (0.84, (52, 40, 104), (176, 76, 108)),
    (0.92, (16, 16, 52), (48, 36, 84)),
    (1.00, (8, 12, 34), (26, 32, 68)),
)


def _lerp(a: float, b: float, k: float) -> float:
    return a + (b - a) * k


def _lerp_rgb(a: tuple[int, int, int], b: tuple[int, int, int], k: float) -> tuple[int, int, int]:
    return tuple(int(round(_lerp(x, y, k))) for x, y in zip(a, b))  # type: ignore[return-value]


def _smooth(k: float) -> float:
    k = max(0.0, min(1.0, k))
    return k * k * (3.0 - 2.0 * k)


def colors_at(t: float) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    t = t % 1.0
    for (t0, top0, bot0), (t1, top1, bot1) in zip(_KEYS, _KEYS[1:]):
        if t0 <= t <= t1:
            k = _smooth((t - t0) / max(1e-6, t1 - t0))
            return _lerp_rgb(top0, top1, k), _lerp_rgb(bot0, bot1, k)
    return _KEYS[-1][1], _KEYS[-1][2]


def clock_t(now: datetime) -> float:
    """真实钟点 → 天时。"""
    h = now.hour + now.minute / 60.0 + now.second / 3600.0
    pts = ((0.0, 0.0), (4.5, 0.04), (6.0, 0.18), (7.5, 0.30), (11.0, 0.50), (15.0, 0.55), (17.5, 0.66), (19.0, 0.80), (20.5, 0.94), (24.0, 1.0))
    for (h0, t0), (h1, t1) in zip(pts, pts[1:]):
        if h0 <= h <= h1:
            return _lerp(t0, t1, (h - h0) / max(1e-6, h1 - h0))
    return 0.0


def solar_t(now: datetime, *, remaining_sec: int | None, done: bool, idle: bool) -> float:
    """把「离下班还有多久」折成天时。"""
    if done:
        return 1.0
    if idle or remaining_sec is None:
        return clock_t(now)
    if remaining_sec > SUNSET_WINDOW_SEC:
        tc = clock_t(now)
        # 夜里加班也不给全黑夜，至少还是上午色；未进最后半小时太阳不落
        if tc > 0.9 or tc < 0.3:
            tc = 0.3 if tc < 0.3 else _DAY_CAP
        return min(_DAY_CAP, tc)
    k = 1.0 - remaining_sec / float(SUNSET_WINDOW_SEC)
    return _DAY_CAP + (1.0 - _DAY_CAP) * k


def is_bright(t: float) -> bool:
    """天亮时用深色字，否则白字。"""
    return 0.20 <= (t % 1.0) <= 0.735


def bucket(t: float) -> int:
    """给渲染缓存键用：颜色在 1/400 精度内变化不重绘。"""
    return int((t % 1.0) * 400)


def _sun_pos(t: float) -> tuple[float, float, float] | None:
    """(x 比例, y 比例, 强度 0~1)；夜里 None。"""
    if t < 0.16 or t > 0.86:
        return None
    if t <= 0.55:
        k = (t - 0.16) / (0.55 - 0.16)
        y = _lerp(1.02, 0.22, _smooth(k))
        x = _lerp(0.86, 0.74, k)
    else:
        k = (t - 0.55) / (0.86 - 0.55)
        y = _lerp(0.22, 1.04, _smooth(k))
        x = _lerp(0.74, 0.62, k)
    edge = min(1.0, (t - 0.16) / 0.08, (0.86 - t) / 0.08)
    return x, y, max(0.0, edge)


def _star_seed(i: int) -> tuple[float, float, float, float]:
    s = (i * 2246822519) & 0xFFFFFFFF
    out: list[float] = []
    for _ in range(4):
        s = (s * 1103515245 + 12345) & 0x7FFFFFFF
        out.append((s >> 8) / float(1 << 23))
    return out[0], out[1], out[2], out[3]


def night_alpha(t: float) -> float:
    t = t % 1.0
    if t >= 0.86:
        return min(1.0, (t - 0.86) / 0.10)
    if t <= 0.16:
        return min(1.0, (0.16 - t) / 0.10)
    return 0.0


def paint(
    img: Image.Image,
    box: tuple[int, int, int, int],
    t: float,
    phase: float,
    *,
    radius: int,
    stage: str = "run",
) -> None:
    """把天色画进圆角框；phase 为单调秒，用来让星星眨眼、阳光呼吸。"""
    x0, y0, x1, y1 = box
    bw, bh = max(1, x1 - x0), max(1, y1 - y0)
    top, bot = colors_at(t)
    grad = Image.linear_gradient("L").resize((bw, bh), Image.Resampling.BILINEAR)
    layer = Image.composite(Image.new("RGBA", (bw, bh), (*bot, 255)), Image.new("RGBA", (bw, bh), (*top, 255)), grad)

    fx = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
    d = ImageDraw.Draw(fx)
    scale = max(0.7, min(2.4, bh / 92.0))

    sun = _sun_pos(t)
    if sun is not None:
        sx, sy, k = sun
        px, py = sx * bw, sy * bh
        low = max(0.0, min(1.0, (sy - 0.55) / 0.5))  # 越接近地平越红
        rgb = _lerp_rgb((255, 250, 232), (255, 132, 70), low)
        breathe = 1.0 + 0.05 * math.sin(phase * 0.7)
        r = (5.2 + 2.4 * low) * scale * breathe
        for m, a in ((5.0, 22), (3.2, 40), (1.9, 74)):
            hr = r * m
            d.ellipse((px - hr, py - hr, px + hr, py + hr), fill=(*rgb, int(a * k)))
        d.ellipse((px - r, py - r, px + r, py + r), fill=(*rgb, int(245 * k)))
        # 地平线上的一道暖光带
        if low > 0.25:
            band = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
            bd = ImageDraw.Draw(band)
            gh = int(bh * 0.28)
            for i in range(gh):
                a = int(70 * low * k * (1.0 - i / gh) ** 1.6)
                if a <= 0:
                    break
                yy = bh - 1 - i
                bd.line((0, yy, bw, yy), fill=(255, 150, 90, a))
            fx.alpha_composite(band)

    na = night_alpha(t)
    if na > 0.0:
        slow = stage in ("idle", "done")
        for i in range(26):
            rx, ry, sp, ph = _star_seed(i)
            if ry > 0.78:
                continue
            tw = 0.5 + 0.5 * math.sin(phase * (0.6 if slow else 1.0) * (0.8 + sp * 1.4) + ph * 6.283)
            a = int(255 * na * (0.25 + 0.75 * tw) * (0.55 if i % 3 else 1.0))
            if a < 8:
                continue
            px, py = rx * bw, ry * bh
            rr = (0.55 + 0.75 * tw * (1.0 if i % 4 else 1.6)) * scale
            d.ellipse((px - rr, py - rr, px + rr, py + rr), fill=(236, 240, 255, a))
        # 月亮：右上角一枚小月
        mx, my = bw * 0.80, bh * 0.30
        mr = 5.0 * scale
        for m, a in ((3.4, 18), (2.0, 36)):
            hr = mr * m
            d.ellipse((mx - hr, my - hr, mx + hr, my + hr), fill=(226, 232, 255, int(a * na)))
        d.ellipse((mx - mr, my - mr, mx + mr, my + mr), fill=(240, 244, 255, int(235 * na)))
        # 挖出一弯：用背景色盖掉一部分
        cut = _lerp_rgb(top, bot, my / bh)
        cx = mx + mr * 0.55
        cy = my - mr * 0.28
        cr = mr * 0.86
        d.ellipse((cx - cr, cy - cr, cx + cr, cy + cr), fill=(*cut, int(255 * na)))

    layer.alpha_composite(fx)

    rad = max(0, int(radius))
    if rad > 0:
        mask = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(mask).rounded_rectangle((0, 0, bw - 1, bh - 1), radius=rad, fill=255)
        r_, g_, b_, a_ = layer.split()
        layer = Image.merge("RGBA", (r_, g_, b_, ImageChops.multiply(a_, mask)))
    img.alpha_composite(layer, (x0, y0))
