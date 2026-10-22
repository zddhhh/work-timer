"""发激励啦：表情包里的人抠出来站在卡片右侧。点一下跳起来，甩出几捆激励。"""
from __future__ import annotations

import math
import random
import threading
from collections import deque
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageSequence

KIND = "suofen"
# 每个动作一句柳州话，同一轮里不换，下一轮再换一句。
_TALK = {
    "hold": {
        "idle": ("点一下先", "等下先", "来玩先"),
        "run": ("莫慌嘛", "发你激励先", "得行先"),
        "warn": ("快走先", "莫走丢", "时间少咯"),
    },
    "side": {
        "idle": ("看你先", "笑哪样", "转过来咯"),
        "run": ("看你先", "笑哪样", "转过来咯"),
        "warn": ("看下钟", "还不走", "转过来催"),
    },
    "bounce": {
        "idle": ("蹦两下", "跳下先", "好耍嘛"),
        "run": ("蹦两下", "跳下先", "高兴咯"),
        "warn": ("跳起走", "蹦一下", "快走咯"),
    },
    "raise": {
        "idle": ("激励在这", "举高点", "拿去先"),
        "run": ("举高点", "激励在这", "发你咯"),
        "warn": ("拿了就走", "举给你", "莫留咯"),
    },
    "back": {
        "idle": ("莫看我", "背过去", "等下转来"),
        "run": ("莫看我", "背过去", "等下转来"),
        "warn": ("背过去咯", "莫留了", "快走嘛"),
    },
    "look": {
        "idle": ("又来咯", "看下先", "转回来了"),
        "run": ("又来咯", "看下先", "转回来了"),
        "warn": ("还在不", "走不走", "看你先"),
    },
}
_DONE = ("发激励啦", "拿去先", "得行咯")
_NUM = {1: "一", 2: "两", 3: "三", 5: "五", 8: "八"}
_PAY = (
    "得了{n}捆激励",
    "发你{n}捆先",
    "{n}捆，拿稳先",
    "这回{n}捆",
)
POP_SEC = 2.4
# 卡片左边这一份给标题和倒计时，和 themes.paint_card 的 text_w 一致
TEXT_SHARE = 0.58
# 原图第 3 帧是残缺的中间张，不用。4、5、6 几乎是同一张，来回切会看成重影。
_FRAMES: list[Image.Image] | None = None
_DURS: list[int] | None = None
_load_lock = threading.Lock()
_loading = False
_BACKDROP: dict[tuple[int, int], Image.Image] = {}
_FITTED: dict[tuple[int, int, int], Image.Image] = {}
_FONTS: dict[int, ImageFont.ImageFont] = {}
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
    """贴一张缓存好的图。30 帧跳起来才连续，16 帧时轻轻颠那一下会一顿一顿。"""
    if callout(now) or stage == "done":
        return 30
    return 30


def _line(stage: str, phase: float) -> str:
    if stage == "done":
        return _DONE[int(phase / 2.4) % len(_DONE)]
    return _talk(stage, phase)


def _talk(stage: str, phase: float) -> str:
    _local, beat = _resident_beat(phase)
    table = _TALK.get(beat[3], _TALK["hold"])
    pool = table.get(stage) or table["run"]
    slot = int(phase // _LOOP) + _BEATS.index(beat)
    return pool[slot % len(pool)]


def _font(size: int) -> ImageFont.ImageFont:
    size = max(8, size)
    got = _FONTS.get(size)
    if got is not None:
        return got
    try:
        got = ImageFont.truetype("msyh.ttc", size)
    except OSError:
        got = ImageFont.load_default()
    _FONTS[size] = got
    return got


def _components(mask: bytearray, w: int, h: int) -> list[tuple]:
    seen = bytearray(w * h)
    out = []
    for y in range(h):
        row = y * w
        for x in range(w):
            i = row + x
            if seen[i] or not mask[i]:
                continue
            q = deque([i])
            seen[i] = 1
            cells = []
            minx = maxx = x
            miny = maxy = y
            while q:
                c = q.popleft()
                cells.append(c)
                cx, cy = c % w, c // w
                if cx < minx:
                    minx = cx
                elif cx > maxx:
                    maxx = cx
                if cy < miny:
                    miny = cy
                elif cy > maxy:
                    maxy = cy
                if cx + 1 < w and not seen[c + 1] and mask[c + 1]:
                    seen[c + 1] = 1
                    q.append(c + 1)
                if cx > 0 and not seen[c - 1] and mask[c - 1]:
                    seen[c - 1] = 1
                    q.append(c - 1)
                if cy + 1 < h and not seen[c + w] and mask[c + w]:
                    seen[c + w] = 1
                    q.append(c + w)
                if cy > 0 and not seen[c - w] and mask[c - w]:
                    seen[c - w] = 1
                    q.append(c - w)
            out.append((len(cells), minx, miny, maxx, maxy, cells))
    out.sort(key=lambda item: (item[0], item[1], item[2], item[3], item[4]), reverse=True)
    return out


def _knock(im: Image.Image, thresh: int = 40) -> Image.Image:
    """黑底抠人。头发、裤子这些包在轮廓里的黑色留着，外面的字幕丢掉。"""
    rgba = im if im.mode == "RGBA" else im.convert("RGBA")
    w, h = rgba.size
    src = rgba.tobytes()
    n = w * h
    mask = bytearray(n)
    for i in range(n):
        o = i * 4
        if src[o] > thresh or src[o + 1] > thresh or src[o + 2] > thresh:
            mask[i] = 1
    comps = _components(mask, w, h)
    if not comps:
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))
    count, ax0, ay0, ax1, ay1, cells = comps[0]
    keep = bytearray(n)
    for c in cells:
        keep[c] = 255
    for cn, _x0, y0, _x1, y1, cc in comps[1:]:
        if cn < 80:
            continue
        cy = (y0 + y1) / 2
        if ay0 - 8 <= cy <= ay1 + 8 and cn < count * 0.85:
            for c in cc:
                keep[c] = 255
    # 只把轮廓上的小缝补上，用来判断哪些黑色在身体里面。补上的那圈本身不画，
    # 否则人物左右晃时黑边会拖成重影。
    sealed = Image.frombytes("L", (w, h), bytes(keep)).filter(ImageFilter.MaxFilter(5))
    sealed_b = sealed.tobytes()
    outside = bytearray(n)
    q: deque[int] = deque()
    for x in range(w):
        q.append(x)
        q.append((h - 1) * w + x)
    for y in range(h):
        q.append(y * w)
        q.append(y * w + (w - 1))
    while q:
        c = q.popleft()
        if outside[c] or sealed_b[c]:
            continue
        outside[c] = 1
        x, y = c % w, c // w
        if x + 1 < w:
            q.append(c + 1)
        if x > 0:
            q.append(c - 1)
        if y + 1 < h:
            q.append(c + w)
        if y > 0:
            q.append(c - w)
    # 贴着外轮廓两像素以内，或贴着画面边，都算补缝扩出来的黑，不画成头发裤子。
    pad = Image.new("L", (w + 4, h + 4), 255)
    pad.paste(Image.frombytes("L", (w, h), bytes(255 if outside[i] else 0 for i in range(n))), (2, 2))
    near = pad.filter(ImageFilter.MaxFilter(5)).crop((2, 2, w + 2, h + 2)).tobytes()
    outb = bytearray(n * 4)
    for i in range(n):
        if outside[i]:
            continue
        o = i * 4
        r, g, b = src[o], src[o + 1], src[o + 2]
        if r > thresh or g > thresh or b > thresh:
            outb[o] = r
            outb[o + 1] = g
            outb[o + 2] = b
            outb[o + 3] = 255
        elif not near[i]:
            outb[o] = 22
            outb[o + 1] = 16
            outb[o + 2] = 16
            outb[o + 3] = 255
    out = Image.frombytes("RGBA", (w, h), bytes(outb))
    box = out.getbbox()
    return out.crop(box) if box else out


def _decode_frames() -> tuple[list[Image.Image], list[int]]:
    path = Path(__file__).resolve().parent / "assets" / "suofen_idle.gif"
    frames: list[Image.Image] = []
    durs: list[int] = []
    try:
        im = Image.open(path)
    except OSError:
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
    return frames, durs


def _load() -> tuple[list[Image.Image], list[int]]:
    global _FRAMES, _DURS, _loading
    with _load_lock:
        if _FRAMES is not None and _DURS is not None:
            _loading = False
            return _FRAMES, _DURS
        try:
            frames, durs = _decode_frames()
        finally:
            _loading = False
        _FRAMES, _DURS = frames, durs
        return frames, durs


def ensure_loading() -> None:
    """启动时在后台抠好。切到这张皮时界面不再等这一下。"""
    global _loading
    if _FRAMES is not None:
        return
    with _load_lock:
        if _FRAMES is not None or _loading:
            return
        _loading = True
    threading.Thread(target=_load, daemon=True, name="suofen-load").start()


def _at(frames: list[Image.Image], idx: int) -> Image.Image:
    return frames[idx if idx < len(frames) else 0]


# 常驻一轮：抱着轻轻颠 → 侧过脸 → 抱着蹦两下 → 举红包跳一下 → 背过身 → 再转回来。
# 只用差得开的姿势，不左右滑同一张图，避免又拖出重影。
# (秒, 帧, 跳法, 台词)
_BEATS = (
    (1.9, 4, "bob", "hold"),
    (1.6, 1, "turn", "side"),
    (1.7, 4, "double", "bounce"),
    (1.6, 2, "big", "raise"),
    (1.5, 0, "hop", "back"),
    (1.5, 1, "turn", "look"),
)
_LOOP = sum(b[0] for b in _BEATS)


def _resident_beat(phase: float) -> tuple[float, tuple]:
    cyc = phase % _LOOP
    start = 0.0
    for beat in _BEATS:
        dur = beat[0]
        if cyc < start + dur:
            return cyc - start, beat
        start += dur
    return 0.0, _BEATS[-1]


def _pose(stage: str, phase: float) -> Image.Image | None:
    frames, _durs = _load()
    if not frames:
        return None
    if pop_age(phase) is not None or stage == "done":
        return _at(frames, 2)
    _local, beat = _resident_beat(phase)
    return _at(frames, beat[1])


def _motion(local: float, dur: float, kind: str) -> float:
    """跳起高度。1 是点中那一下的高度，常驻的蹦跳矮一些。"""
    if kind == "bob":
        return abs(math.sin(local / 0.48 * math.pi)) * 0.18
    if kind == "double":
        half = max(0.2, dur / 2)
        return math.sin((local % half) / half * math.pi) * 0.62
    amp = {"turn": 0.36, "hop": 0.5, "big": 0.92}.get(kind, 0.4)
    return math.sin(min(1.0, local / max(0.2, dur)) * math.pi) * amp


def _hop(stage: str, phase: float) -> float:
    """跳起的高度，按身高原比例。点中就跳高，平时按当前这个动作蹦。"""
    age = pop_age(phase)
    if age is not None and age < 0.62:
        return math.sin(age / 0.62 * math.pi)
    if stage == "done":
        cyc = phase % 3.2
        if cyc < 0.34:
            return math.sin(cyc / 0.34 * math.pi) * 0.28
        return 0.0
    local, beat = _resident_beat(phase)
    return _motion(local, beat[0], beat[2])


def _backdrop(w: int, h: int) -> Image.Image:
    key = (w, h)
    got = _BACKDROP.get(key)
    if got is not None:
        return got
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    for y in range(h):
        t = y / max(1, h - 1)
        d.line([(0, y), (w, y)], fill=(int(255 - 4 * t), int(244 - 14 * t), int(224 - 16 * t), 255))
    d.rounded_rectangle(
        (1, 1, w - 2, h - 2),
        radius=max(8, h // 10),
        outline=(176, 42, 36, 255),
        width=max(2, h // 46),
    )
    if len(_BACKDROP) > 3:
        _BACKDROP.clear()
    _BACKDROP[key] = im
    return im


def _fitted(frame_i: int, sprite: Image.Image, sw: int, sh: int) -> Image.Image:
    key = (frame_i, sw, sh)
    got = _FITTED.get(key)
    if got is not None:
        return got
    got = sprite.resize((sw, sh), Image.Resampling.BOX)
    if len(_FITTED) > 16:
        _FITTED.clear()
    _FITTED[key] = got
    return got


def paint(layer: Image.Image, phase: float, *, stage: str) -> None:
    w, h = layer.size
    if w < 8 or h < 8:
        return
    layer.alpha_composite(_backdrop(w, h))
    if not _FRAMES:
        ensure_loading()
        return
    d = ImageDraw.Draw(layer)
    sprite = _pose(stage, phase)
    if sprite is None:
        return
    frames, _durs = _load()
    frame_i = 2 if pop_age(phase) is not None or stage == "done" else _resident_beat(phase)[1][1]
    if frame_i >= len(frames):
        frame_i = 0
    top = max(4, int(h * 0.05))
    foot = h - max(4, int(h * 0.06))
    avail = max(8, foot - top)
    sh = max(8, int(avail * 0.96))
    sw = max(1, int(sprite.width * sh / sprite.height))
    max_w = int(w * 0.40)
    if sw > max_w:
        sw = max_w
        sh = max(1, int(sprite.height * sw / sprite.width))
    fitted = _fitted(frame_i, sprite, sw, sh)
    # 身体中线固定在右侧。侧脸、举红包、背过身时人还站在原地。
    cx = w - max(10, int(w * 0.16))
    ox = max(4, min(w - sw - 4, cx - sw // 2))
    hop = _hop(stage, phase)
    oy = int(foot - sh - hop * sh * 0.22)
    _shadow(d, ox + sw // 2, foot, int(sw * (1 - 0.25 * hop)))
    if stage == "done" and pop_age(phase) is None:
        _toss(d, ox, oy, sw, sh, phase)
    layer.alpha_composite(fitted, (ox, max(0, oy)))
    age = pop_age(phase)
    if age is not None:
        _burst(d, ox, oy, sw, sh, age)
    line = callout(phase) or _line(stage, phase)
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
    # 左边 58% 是标题和倒计时，气泡只在人物这一侧，放不下就缩字
    floor = int(card_w * TEXT_SHARE) + 2
    room = max(16, card_w - 4 - floor)
    size = max(11, min(18, sw // 5)) if pop else max(9, min(15, sw // 6))
    while True:
        font = _font(size)
        box = d.textbbox((0, 0), text, font=font)
        tw, th = box[2] - box[0], box[3] - box[1]
        pad = max(3, size // 3)
        bw, bh = tw + pad * 2, th + pad * 2
        if bw <= room or size <= 8:
            break
        size -= 1
    right = min(card_w - 4, ox + int(sw * (0.42 if pop else 0.72)))
    left = max(floor, right - bw)
    right = min(card_w - 4, left + bw)
    if right - left < bw:
        left = max(floor, right - bw)
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
