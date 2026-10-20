"""发激励啦：表情包里的人抠出来站在卡片右侧。点一下跳起来，甩出几捆激励。"""
from __future__ import annotations

import math
import random
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageSequence

KIND = "suofen"
_AMBIENT = {
    "idle": ("点一下先", "等下先"),
    "run": ("莫慌嘛", "发你激励先"),
    "warn": ("快走先", "莫走丢先"),
    "done": ("发激励啦", "拿去先"),
}
_NUM = {1: "一", 2: "两", 3: "三", 5: "五", 8: "八"}
_PAY = (
    "得了{n}捆激励",
    "发你{n}捆先",
    "{n}捆，拿稳先",
    "这回{n}捆",
)
POP_SEC = 2.4
# 原图第 3 帧是残缺的中间张，不用。4、5、6 几乎是同一张，来回切会看成重影。
_FRAMES: list[Image.Image] | None = None
_DURS: list[int] | None = None
_pop_at: float | None = None
_pop_line = ""
_rng = random.Random()


def poke(now: float) -> str:
    """点卡片：跳起来发一捆激励。连点就再发一回。"""
    global _pop_at, _pop_line
    n = _rng.choice((1, 1, 2, 2, 3, 3, 5, 8))
    _pop_line = _rng.choice(_PAY).format(n=_NUM[n])
    _pop_at = now
    return _pop_line


def callout(now: float) -> str | None:
    global _pop_at
    if _pop_at is None:
        return None
    if now - _pop_at > POP_SEC:
        _pop_at = None
        return None
    return _pop_line


def pop_age(now: float) -> float | None:
    if callout(now) is None or _pop_at is None:
        return None
    return now - _pop_at


def fps(stage: str, now: float) -> int:
    if callout(now):
        return 30
    if stage == "done":
        return 20
    return 16


def _ambient(stage: str, phase: float) -> str:
    lines = _AMBIENT.get(stage, _AMBIENT["run"])
    return lines[int(phase / 3.4) % len(lines)]


def _font(size: int) -> ImageFont.ImageFont:
    try:
        return ImageFont.truetype("msyh.ttc", max(8, size))
    except OSError:
        return ImageFont.load_default()


def _components(mask: Image.Image) -> list[tuple]:
    w, h = mask.size
    mp = mask.load()
    seen = [[False] * w for _ in range(h)]
    out = []
    for y in range(h):
        for x in range(w):
            if seen[y][x] or not mp[x, y]:
                continue
            q = deque([(x, y)])
            seen[y][x] = True
            cells = []
            minx = maxx = x
            miny = maxy = y
            while q:
                cx, cy = q.popleft()
                cells.append((cx, cy))
                minx, maxx = min(minx, cx), max(maxx, cx)
                miny, maxy = min(miny, cy), max(maxy, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny][nx] and mp[nx, ny]:
                        seen[ny][nx] = True
                        q.append((nx, ny))
            out.append((len(cells), minx, miny, maxx, maxy, cells))
    out.sort(reverse=True)
    return out


def _knock(im: Image.Image, thresh: int = 40) -> Image.Image:
    """黑底抠人。头发、裤子这些包在轮廓里的黑色留着，外面的字幕丢掉。"""
    w, h = im.size
    px = im.load()
    color = Image.new("L", (w, h), 0)
    cp = color.load()
    for y in range(h):
        for x in range(w):
            if max(px[x, y][:3]) > thresh:
                cp[x, y] = 255
    comps = _components(color)
    if not comps:
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))
    _n, ax0, ay0, ax1, ay1, cells = comps[0]
    keep = Image.new("L", (w, h), 0)
    kp = keep.load()
    for x, y in cells:
        kp[x, y] = 255
    for cn, x0, y0, x1, y1, cc in comps[1:]:
        if cn < 80:
            continue
        cy = (y0 + y1) / 2
        if ay0 - 8 <= cy <= ay1 + 8 and cn < _n * 0.85:
            for x, y in cc:
                kp[x, y] = 255
    # 只把轮廓上的小缝补上，用来判断哪些黑色在身体里面。补上的那圈本身不画，
    # 否则人物左右晃时黑边会拖成重影。
    sealed = keep.filter(ImageFilter.MaxFilter(5))
    sp = sealed.load()
    outside: set[tuple[int, int]] = set()
    q: deque[tuple[int, int]] = deque()
    for x in range(w):
        q.append((x, 0))
        q.append((x, h - 1))
    for y in range(h):
        q.append((0, y))
        q.append((w - 1, y))
    while q:
        x, y = q.popleft()
        if (x, y) in outside or not (0 <= x < w and 0 <= y < h) or sp[x, y]:
            continue
        outside.add((x, y))
        q.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    out = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    opx = out.load()
    for y in range(h):
        for x in range(w):
            if (x, y) in outside:
                continue
            r, g, b, _a = px[x, y]
            if max(r, g, b) > thresh:
                opx[x, y] = (r, g, b, 255)
                continue
            if _on_fringe(x, y, outside, w, h):
                continue
            opx[x, y] = (22, 16, 16, 255)
    box = out.getbbox()
    return out.crop(box) if box else out


def _on_fringe(x: int, y: int, outside: set[tuple[int, int]], w: int, h: int) -> bool:
    """贴着外轮廓两像素以内的黑，是补缝时扩出来的，不是头发裤子。"""
    for dy in range(-2, 3):
        for dx in range(-2, 3):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h) or (nx, ny) in outside:
                return True
    return False


def _load() -> tuple[list[Image.Image], list[int]]:
    global _FRAMES, _DURS
    if _FRAMES is not None and _DURS is not None:
        return _FRAMES, _DURS
    path = Path(__file__).resolve().parent / "assets" / "suofen_idle.gif"
    frames: list[Image.Image] = []
    durs: list[int] = []
    try:
        im = Image.open(path)
    except OSError:
        _FRAMES, _DURS = frames, durs
        return frames, durs
    try:
        canvas = Image.new("RGBA", im.size, (0, 0, 0, 255))
        for fr in ImageSequence.Iterator(im):
            method = im.disposal_method if hasattr(im, "disposal_method") else 0
            frame = fr.convert("RGBA")
            base = Image.new("RGBA", im.size, (0, 0, 0, 255)) if method == 2 else canvas.copy()
            base.alpha_composite(frame)
            frames.append(_knock(base))
            durs.append(max(40, int(fr.info.get("duration") or im.info.get("duration") or 200)))
            if method != 3:
                canvas = base
    finally:
        im.close()
    _FRAMES, _DURS = frames, durs
    return frames, durs


def _at(frames: list[Image.Image], idx: int) -> Image.Image:
    return frames[idx if idx < len(frames) else 0]


# 常驻一轮：抱着红包 → 侧过脸笑一下 → 再抱着 → 把红包举起来。
# 用差得开的姿势，不左右滑同一张图，避免又拖出重影。
_LOOP = 7.2


def _resident_frame(phase: float) -> int:
    cyc = phase % _LOOP
    if 2.3 <= cyc < 3.9:
        return 1
    if 5.0 <= cyc < 6.35:
        return 2
    return 4


def _pose(stage: str, phase: float) -> Image.Image | None:
    frames, _durs = _load()
    if not frames:
        return None
    if pop_age(phase) is not None or stage == "done":
        return _at(frames, 2)
    return _at(frames, _resident_frame(phase))


def _hop(stage: str, phase: float) -> float:
    """跳起的高度，按身高原比例。举起红包时垫一下，点中就跳高。"""
    age = pop_age(phase)
    if age is not None and age < 0.62:
        return math.sin(age / 0.62 * math.pi)
    if stage == "done":
        cyc = phase % 3.2
        if cyc < 0.34:
            return math.sin(cyc / 0.34 * math.pi) * 0.16
        return 0.0
    cyc = phase % _LOOP
    if 5.0 <= cyc < 5.72:
        return math.sin((cyc - 5.0) / 0.72 * math.pi) * 0.2
    return 0.0


def paint(layer: Image.Image, phase: float, *, stage: str) -> None:
    w, h = layer.size
    if w < 8 or h < 8:
        return
    d = ImageDraw.Draw(layer)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=(int(255 - 4 * t), int(244 - 14 * t), int(224 - 16 * t), 255))
    d.rounded_rectangle(
        (1, 1, w - 2, h - 2),
        radius=max(8, h // 10),
        outline=(176, 42, 36, 255),
        width=max(2, h // 46),
    )
    sprite = _pose(stage, phase)
    if sprite is None:
        return
    top = max(4, int(h * 0.05))
    foot = h - max(4, int(h * 0.06))
    avail = max(8, foot - top)
    sh = max(8, int(avail * 0.96))
    sw = max(1, int(sprite.width * sh / sprite.height))
    max_w = int(w * 0.40)
    if sw > max_w:
        sw = max_w
        sh = max(1, int(sprite.height * sw / sprite.width))
    fitted = sprite.resize((sw, sh), Image.Resampling.BOX)
    # 身体中线固定在右侧。侧脸、举红包换姿势时人还站在原地。
    cx = w - max(10, int(w * 0.16))
    ox = max(4, min(w - sw - 4, cx - sw // 2))
    hop = _hop(stage, phase)
    breathe = 0 if pop_age(phase) is not None or stage == "done" else int(math.sin(phase * 1.6) * max(1, sh // 90))
    oy = int(foot - sh - hop * sh * 0.22 - breathe)
    _shadow(d, ox + sw // 2, foot, int(sw * (1 - 0.25 * hop)))
    if stage == "done" and pop_age(phase) is None:
        _toss(d, ox, oy, sw, sh, phase)
    layer.alpha_composite(fitted, (ox, max(0, oy)))
    age = pop_age(phase)
    if age is not None:
        _burst(d, ox, oy, sw, sh, age)
    line = callout(phase) or _ambient(stage, phase)
    _bubble(d, ox, max(0, oy), sw, sh, w, h, line, pop=age is not None)


def _shadow(d: ImageDraw.ImageDraw, cx: int, foot: int, sw: int) -> None:
    rw, rh = int(sw * 0.42), max(3, sw // 14)
    d.ellipse((cx - rw, foot - rh, cx + rw, foot + rh), fill=(120, 70, 40, 50))


def _coin(d: ImageDraw.ImageDraw, cx: int, cy: int, r: int) -> None:
    d.ellipse((cx - r, cy - int(r * 0.72), cx + r, cy + int(r * 0.72)), fill=(232, 184, 64, 235))
    d.ellipse((cx - r // 3, cy - r // 5, cx + r // 3, cy + r // 5), fill=(255, 226, 140, 235))


def _packet(d: ImageDraw.ImageDraw, x: int, y: int, pw: int, ph: int) -> None:
    d.rounded_rectangle((x, y, x + pw, y + ph), radius=1, fill=(214, 48, 42, 240))
    d.rectangle((x, y + ph // 3, x + pw, y + ph // 3 + max(1, ph // 8)), fill=(232, 186, 74, 240))


def _toss(d: ImageDraw.ImageDraw, ox: int, oy: int, sw: int, sh: int, phase: float) -> None:
    """到点以后隔一会儿从手里甩出一捆，走个弧线落下去。"""
    t = phase % 1.7
    if t > 1.15:
        return
    x = ox + sw // 2 - int(sw * 1.1 * t)
    y = oy + int(sh * 0.34) - int(sh * 0.55 * math.sin(t / 1.15 * math.pi))
    _packet(d, x, y, max(6, sw // 9), max(8, sw // 7))


def _burst(d: ImageDraw.ImageDraw, ox: int, oy: int, sw: int, sh: int, age: float) -> None:
    """点中的那一下：红包和元宝从胸口甩出去，再掉下来。"""
    if age > 1.35:
        return
    g = sh * 2.4
    pw, ph = max(6, sw // 9), max(8, sw // 7)
    for i in range(6):
        ang = -2.55 + i * 0.42
        speed = sh * (1.15 + (i % 3) * 0.22)
        x = ox + sw // 2 + int(math.cos(ang) * speed * age)
        y = oy + int(sh * 0.28) + int(math.sin(ang) * speed * age + 0.5 * g * age * age)
        if y > oy + sh + 6:
            continue
        if i % 2:
            _packet(d, x, y, pw, ph)
        else:
            _coin(d, x, y, max(3, sw // 14))


def _bubble(
    d: ImageDraw.ImageDraw,
    ox: int,
    oy: int,
    sw: int,
    sh: int,
    card_w: int,
    card_h: int,
    text: str,
    *,
    pop: bool,
) -> None:
    size = max(11, min(18, sw // 5)) if pop else max(9, min(15, sw // 6))
    font = _font(size)
    box = d.textbbox((0, 0), text, font=font)
    tw, th = box[2] - box[0], box[3] - box[1]
    pad = max(3, size // 3)
    bw, bh = tw + pad * 2, th + pad * 2
    floor = int(card_w * (0.34 if pop else 0.50))
    right = min(card_w - 4, ox + int(sw * (0.42 if pop else 0.72)))
    left = max(floor, right - bw)
    right = min(card_w - 4, left + bw)
    top = max(3, oy - bh - 2) if pop else max(3, oy + int(sh * 0.02))
    if not pop and top + bh > oy + sh * 0.45:
        top = max(3, oy - bh + 4)
    if top + bh > card_h - 3:
        top = max(3, card_h - 3 - bh)
    rect = (left, top, right, top + bh)
    d.rounded_rectangle(rect, radius=max(3, size // 2), fill=(255, 250, 242, 235), outline=(176, 42, 36, 255))
    d.polygon(
        [
            (right - pad, rect[3] - 1),
            (min(card_w - 6, ox + sw // 3), rect[3] + max(4, sh // 10)),
            (right - pad * 3, rect[3] - 1),
        ],
        fill=(255, 250, 242, 235),
    )
    d.text((left + pad, top + pad - box[1]), text, font=font, fill=(140, 36, 28, 255))
