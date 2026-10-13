"""喵喵仪仗队：卡片底部一排原创小猫，跟着倒计时打盹/站岗/踏步/正步，点一下集合踢正步。

造型用局部坐标（脚底中心为原点，向上为负）描述，按姿势矩阵变换后超采样绘制；
每只猫按量化后的姿势缓存精灵图，站岗时几乎全命中缓存。
"""
from __future__ import annotations

import math
import random
import re
from collections import OrderedDict

from PIL import Image, ImageChops, ImageDraw

KIND = "meow"
INK = (43, 29, 34, 255)
WHITE = (255, 255, 255, 255)
SW = 1.3
SS = 3
# 精灵按这个步长分档缓存：拖动时相邻尺寸共用一张画好的猫，再等比缩放到当前大小
_SCALE_STEP = 0.05

SHOW_A = 0.55
SHOW_T = 0.46
SHOW_M = SHOW_A + 8 * SHOW_T
SHOW_L = SHOW_M + 0.4
SHOW_E = SHOW_L + 1.5
CHEER_SEC = 1.3
# 到点后先正步游行这么久，再坐下歇着，免得整晚满帧
DONE_MARCH_SEC = 600.0
_CALLS = ("一", "二", "一", "二", "一", "二", "三", "四")

# 精灵图包围盒（局部单位）：含举旗、敬礼星星、Zz
_BX0, _BY0, _BX1, _BY1 = -30.0, -82.0, 32.0, 6.0


def _hex(s: str, a: int = 255) -> tuple[int, int, int, int]:
    s = s.lstrip("#")
    return (int(s[0:2], 16), int(s[2:4], 16), int(s[4:6], 16), a)


CATS: tuple[dict, ...] = (
    {"id": "maomao", "name": "毛毛", "hat": "beanie", "beanie": ("#7a5cf0", "#ffd23f"),
     "body": "#ffffff", "sleeve": "#7a5cf0", "collar": "#ffffff", "emblem": "star", "emblem_c": "#ff6f91", "shoes": "#ffd23f"},
    {"id": "ningmeng", "name": "柠檬", "hood": "#ffd84a", "hood_ears": "cat", "ear_in": "#ffb3c6",
     "body": "#ffd84a", "sleeve": "#ffd84a", "collar": "#ffd84a", "bowtie": "#3aa0ff", "emblem": "heart", "emblem_c": "#ff6f91", "shoes": "#ff9a3c"},
    {"id": "taotao", "name": "桃桃", "hood": "#ff8fb8", "hood_ears": "bunny", "ear_in": "#ffd6e4",
     "body": "#4f8df5", "sleeve": "#ff8fb8", "collar": "#ffffff", "emblem": "pocket", "shoes": "#2f3b73"},
    {"id": "buding", "name": "布丁", "hat": "cone",
     "body": "#ffb347", "sleeve": "#ff6f91", "collar": "#ff6f91", "emblem": "buttons", "emblem_c": "#ffffff", "shoes": "#e8505b"},
    {"id": "xingye", "name": "星夜", "hood": "#27306a", "hood_ears": "cat", "ear_in": "#4a5bb0", "dots": "#ffd23f", "pompom": "#ffd23f",
     "body": "#27306a", "sleeve": "#4a90e2", "collar": "#4a90e2", "emblem": "star", "emblem_c": "#ffd23f", "shoes": "#27306a"},
    {"id": "tuanzhang", "name": "团长", "leader": True, "tuft": True, "clip": "#ffd23f",
     "body": "#5cc46a", "sleeve": "#5cc46a", "collar": "#ffe066", "emblem": "buttons", "emblem_c": "#ffe066", "shoes": "#e8505b"},
)

# ---------- 几何 ----------

def _mul(m, n):
    a, b, c, d, e, f = m
    A, B, C, D, E, F = n
    return (a * A + c * B, b * A + d * B, a * C + c * D, b * C + d * D, a * E + c * F + e, b * E + d * F + f)


def _tr(x: float, y: float):
    return (1.0, 0.0, 0.0, 1.0, x, y)


def _sc(sx: float, sy: float | None = None):
    return (sx, 0.0, 0.0, sx if sy is None else sy, 0.0, 0.0)


def _rot(deg: float, cx: float = 0.0, cy: float = 0.0):
    r = math.radians(deg)
    co, si = math.cos(r), math.sin(r)
    m = (co, si, -si, co, 0.0, 0.0)
    if cx or cy:
        return _mul(_tr(cx, cy), _mul(m, _tr(-cx, -cy)))
    return m


def _chain(*ms):
    out = (1.0, 0.0, 0.0, 1.0, 0.0, 0.0)
    for m in ms:
        out = _mul(out, m)
    return out


def _apply(m, pts):
    a, b, c, d, e, f = m
    return [(a * x + c * y + e, b * x + d * y + f) for x, y in pts]


_TOK = re.compile(r"[MLCQZ]|-?\d*\.?\d+")


def _path(d: str, seg: int = 8) -> list[tuple[list[tuple[float, float]], bool]]:
    toks = _TOK.findall(d.replace(",", " "))
    subs: list[tuple[list[tuple[float, float]], bool]] = []
    cur: list[tuple[float, float]] = []
    i, cmd = 0, "M"
    x = y = 0.0

    def num() -> float:
        nonlocal i
        v = float(toks[i])
        i += 1
        return v

    while i < len(toks):
        t = toks[i]
        if t in ("M", "L", "C", "Q", "Z"):
            cmd = t
            i += 1
            if cmd == "Z":
                if cur:
                    subs.append((cur, True))
                cur = []
            continue
        if cmd == "M":
            if cur:
                subs.append((cur, False))
            x, y = num(), num()
            cur = [(x, y)]
            cmd = "L"
        elif cmd == "L":
            x, y = num(), num()
            cur.append((x, y))
        elif cmd == "C":
            x1, y1, x2, y2, x3, y3 = num(), num(), num(), num(), num(), num()
            for k in range(1, seg + 1):
                u = k / seg
                v = 1 - u
                cur.append((
                    v * v * v * x + 3 * v * v * u * x1 + 3 * v * u * u * x2 + u * u * u * x3,
                    v * v * v * y + 3 * v * v * u * y1 + 3 * v * u * u * y2 + u * u * u * y3,
                ))
            x, y = x3, y3
        elif cmd == "Q":
            x1, y1, x2, y2 = num(), num(), num(), num()
            for k in range(1, seg + 1):
                u = k / seg
                v = 1 - u
                cur.append((v * v * x + 2 * v * u * x1 + u * u * x2, v * v * y + 2 * v * u * y1 + u * u * y2))
            x, y = x2, y2
        else:
            i += 1
    if cur:
        subs.append((cur, False))
    return subs


def _ellipse_pts(cx: float, cy: float, rx: float, ry: float, n: int = 28) -> list[tuple[float, float]]:
    return [(cx + rx * math.cos(2 * math.pi * k / n), cy + ry * math.sin(2 * math.pi * k / n)) for k in range(n)]


def _rrect_pts(x: float, y: float, w: float, h: float, r: float, n: int = 5) -> list[tuple[float, float]]:
    r = max(0.0, min(r, w / 2, h / 2))
    pts: list[tuple[float, float]] = []
    for cx, cy, a0 in ((x + w - r, y + r, -90), (x + w - r, y + h - r, 0), (x + r, y + h - r, 90), (x + r, y + r, 180)):
        for k in range(n + 1):
            a = math.radians(a0 + 90 * k / n)
            pts.append((cx + r * math.cos(a), cy + r * math.sin(a)))
    return pts


def _star_pts(cx: float, cy: float, r: float, ri: float | None = None) -> list[tuple[float, float]]:
    ri = r * 0.5 if ri is None else ri
    out = []
    for k in range(10):
        rr = ri if k % 2 else r
        a = math.radians(-90 + k * 36)
        out.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    return out


def _heart_d(cx: float, cy: float, s: float) -> str:
    return (
        f"M {cx},{cy + s * 0.95} C {cx - s * 1.7},{cy - s * 0.1} {cx - s * 0.95},{cy - s * 1.35} {cx},{cy - s * 0.45} "
        f"C {cx + s * 0.95},{cy - s * 1.35} {cx + s * 1.7},{cy - s * 0.1} {cx},{cy + s * 0.95} Z"
    )


class Prim:
    __slots__ = ("paths", "fill", "stroke", "sw", "alpha")

    def __init__(self, paths, fill=None, stroke=INK, sw: float = SW, alpha: float = 1.0):
        self.paths = paths
        self.fill = fill
        self.stroke = stroke
        self.sw = sw
        self.alpha = alpha

    def xf(self, m) -> "Prim":
        return Prim([(_apply(m, pts), closed) for pts, closed in self.paths], self.fill, self.stroke, self.sw, self.alpha)


def _P(d: str, fill=None, *, sw: float = SW, stroke=INK, alpha: float = 1.0) -> Prim:
    return Prim(_path(d), fill, stroke, sw, alpha)


def _E(cx, cy, rx, ry, fill=None, *, sw: float = SW, stroke=INK, alpha: float = 1.0) -> Prim:
    return Prim([(_ellipse_pts(cx, cy, rx, ry), True)], fill, stroke, sw, alpha)


def _R(x, y, w, h, r, fill=None, *, sw: float = SW, stroke=INK) -> Prim:
    return Prim([(_rrect_pts(x, y, w, h, r), True)], fill, stroke, sw)


def _S(cx, cy, r, fill, *, sw: float = SW, stroke=INK) -> Prim:
    return Prim([(_star_pts(cx, cy, r), True)], fill, stroke, sw)


_MIRROR = (-1.0, 0.0, 0.0, 1.0, 0.0, 0.0)


def _mir(prims: list) -> list:
    out = []
    for p in prims:
        if isinstance(p, tuple):
            out.append((p[0], p[1].xf(_MIRROR)))
        else:
            out.append(p.xf(_MIRROR))
    return out


def _dome_band(left: list[tuple[float, float]], y0: float, y1: float) -> list[tuple[float, float]]:
    """毛线帽条纹：横条与帽顶轮廓求交（左半轮廓按 y 插值，镜像出右边）。"""

    def half_w(y: float) -> float:
        best = 0.0
        for (xa, ya), (xb, yb) in zip(left, left[1:]):
            if (ya - y) * (yb - y) <= 0 and ya != yb:
                t = (y - ya) / (yb - ya)
                best = max(best, -(xa + (xb - xa) * t))
        return best

    ys = [y0 + (y1 - y0) * k / 4 for k in range(5)]
    lefts = [(-half_w(y), y) for y in ys]
    rights = [(half_w(y), y) for y in reversed(ys)]
    return lefts + rights


# ---------- 造型 ----------

def _build_head(d: dict) -> list[tuple[str, Prim]]:
    out: list[tuple[str, Prim]] = []

    def add(prims, tag: str = "") -> None:
        for p in prims:
            out.append((tag, p))

    hood = _hex(d["hood"]) if d.get("hood") else None
    if hood is not None:
        if d.get("hood_ears") == "cat":
            ear = [
                _P("M -16.5,-41 C -17.5,-50 -16,-56 -14.5,-57.5 C -13.2,-58.5 -10.5,-56.5 -5,-50.5 Z", hood),
                _P("M -14.6,-45.5 C -15.2,-50.5 -14.4,-53.6 -13.6,-54.4 C -12.8,-54.8 -11,-53.4 -8,-50.6 Z", _hex(d["ear_in"]), stroke=None),
            ]
        else:
            m = _rot(-16, -6, -50)
            ear = [
                _E(-6, -57, 4.2, 8.5, hood).xf(m),
                _E(-6, -56.5, 2, 6, _hex(d["ear_in"]), stroke=None).xf(m),
            ]
        add(ear)
        add(_mir(ear))
        add([_E(0, -38.5, 17, 14.5, hood)])
        if d.get("dots"):
            dc = _hex(d["dots"])
            add([_E(x, y, 0.9, 0.9, dc, stroke=None) for x, y in ((-6, -50.6), (1, -51.6), (7.6, -50.2), (-14.6, -41), (15, -40.2), (-15.2, -33.4), (15.2, -32.6))])
        if d.get("pompom"):
            add([_E(0, -54.4, 2.9, 2.9, _hex(d["pompom"]))])
        add([_E(0, -37.3, 13, 10.6, WHITE)])
    else:
        if not d.get("hat"):
            ear = [
                _P("M -13.8,-43 C -14.5,-48 -13.8,-52.5 -12.6,-53.6 C -11.6,-54.4 -9.5,-53 -4.5,-48.6 Z", WHITE),
                _P("M -12.4,-45.6 C -12.7,-48.4 -12.3,-50.6 -11.7,-51.2 C -10.9,-51.5 -9.5,-50.5 -7.2,-48.4 Z", _hex("#ffc2d1"), stroke=None),
            ]
            add(ear)
            add(_mir(ear))
        add([_E(0, -38, 15.5, 12.5, WHITE)])
    blush = [_E(-10.2, -33.4, 2.9, 1.7, _hex("#ff9fb5"), stroke=None, alpha=0.85)]
    add(blush)
    add(_mir(blush))
    wh = [_P("M -13.4,-36.2 L -19.6,-37.5 M -13.4,-33.6 L -19.6,-33.1", sw=0.95)]
    add(wh)
    add(_mir(wh))
    out.append(("EYES", Prim([])))
    add([_P("M -8.1,-37.6 Q -6.2,-35.6 -4.3,-37.6 M 4.3,-37.6 Q 6.2,-35.6 8.1,-37.6", sw=1.05)], "eS")
    add([_P("M -8.1,-36.6 Q -6.2,-39.8 -4.3,-36.6 M 4.3,-36.6 Q 6.2,-39.8 8.1,-36.6", sw=1.15)], "eH")
    add([_E(0, -34.3, 1.45, 1.05, _hex("#ff7b9c"), sw=0.6)])
    add([_P("M -2.5,-32.9 Q -1.25,-31.2 0,-32.7 Q 1.25,-31.2 2.5,-32.9", sw=0.9)], "mo")
    add([_P("M -2,-32.8 Q 0,-28.6 2,-32.8 Z", _hex("#ff6f8e"), sw=0.8)], "moO")
    if d.get("hat") == "cone":
        m = _rot(9, 0, -47)
        orange = _hex("#ff9a3c")
        add([p.xf(m) for p in (
            _P("M -10.6,-46.4 L -1.1,-61.6 Q 0,-63.2 1.1,-61.6 L 10.6,-46.4 Q 0,-43.4 -10.6,-46.4 Z", _hex("#ffcf4a")),
            _E(-3.4, -49.6, 1.4, 1.1, orange, stroke=None),
            _E(3.6, -52.8, 1.2, 0.95, orange, stroke=None),
            _E(-0.6, -57, 0.95, 0.8, orange, stroke=None),
            _E(5, -48.2, 0.9, 0.7, orange, stroke=None),
            _E(0, -63, 2.6, 2.6, _hex("#ff5a6e")),
        )])
    elif d.get("hat") == "beanie":
        c0, c1 = _hex(d["beanie"][0]), _hex(d["beanie"][1])
        dome = "M -14.6,-44.2 C -14.6,-54.6 -8.2,-58.6 0,-58.6 C 8.2,-58.6 14.6,-54.6 14.6,-44.2 Z"
        left = _path("M -14.6,-44.2 C -14.6,-54.6 -8.2,-58.6 0,-58.6", seg=16)[0][0]
        add([
            _P(dome, c0, stroke=None),
            Prim([(_dome_band(left, -53.4, -50.6), True)], c1, None),
            Prim([(_dome_band(left, -57.8, -55.4), True)], c1, None),
            _P(dome),
            _R(-15.8, -47.2, 31.6, 4.8, 2.4, c1),
            _E(0, -60.4, 3.1, 3.1, c1),
        ])
    if d.get("tuft"):
        add([_P("M .4,-50.2 C -1,-54.8 3.4,-57.6 5.3,-54.7 C 6.3,-52.8 3.6,-51.5 3.4,-53.6", sw=1.25)])
    if d.get("clip"):
        add([_S(10.8, -48.2, 3.4, _hex(d["clip"]), sw=1.0)])
    return out


def _build(d: dict) -> dict:
    ec = _hex(d.get("emblem_c") or "#ffffff")
    emblem: list[Prim] = []
    kind = d.get("emblem")
    if kind == "star":
        emblem = [_S(0, -18.2, 3.7, ec, sw=0.9)]
    elif kind == "heart":
        emblem = [_P(_heart_d(0, -17.6, 2.7), ec, sw=0.9)]
    elif kind == "buttons":
        emblem = [_E(0, -21, 1.15, 1.15, ec, sw=0.8), _E(0, -16, 1.15, 1.15, ec, sw=0.8)]
    elif kind == "pocket":
        emblem = [_P("M -3.6,-19.2 L 3.6,-19.2 L 3.6,-15 Q 3.6,-13.6 2.2,-13.6 L -2.2,-13.6 Q -3.6,-13.6 -3.6,-15 Z", WHITE, sw=0.9)]
    body = [_P("M -6.5,-27 C -8.5,-22 -10.2,-16 -10.2,-12.6 Q -10.2,-10.4 -8,-10.4 L 8,-10.4 Q 10.2,-10.4 10.2,-12.6 C 10.2,-16 8.5,-22 6.5,-27 Z", _hex(d["body"]))] + emblem
    collar = [_E(0, -26.6, 7.6, 2.7, _hex(d["collar"]))]
    if d.get("bowtie"):
        bc = _hex(d["bowtie"])
        collar += [
            _P("M 0,-26.4 L -4.4,-28.9 L -4.4,-23.9 Z M 0,-26.4 L 4.4,-28.9 L 4.4,-23.9 Z", bc, sw=0.9),
            _E(0, -26.4, 1.3, 1.3, bc, sw=0.9),
        ]
    out = {
        "d": d,
        "leader": bool(d.get("leader")),
        "shoes": _hex(d["shoes"]),
        "body": body,
        "collar": collar,
        "sleeve": _R(-2.4, -1.5, 4.8, 10.6, 2.4, _hex(d["sleeve"])),
        "paw": _E(0, 9.6, 2.7, 2.7, WHITE),
        "head": _build_head(d),
        "eye": _E(0, 0, 1.8, 2.4, INK, stroke=None),
        "hl": _E(-0.6, -0.95, 0.72, 0.72, WHITE, stroke=None),
        "hlS": _E(-0.6, -0.95, 1.0, 1.0, WHITE, stroke=None),
        "puff": [_E(-2.2, -0.4, 1.7, 1.7, WHITE, sw=0.7), _E(2, -1, 1.3, 1.3, WHITE, sw=0.7)],
        "popS": [_S(0, 0, 4.6, _hex("#ffd23f"), sw=1.0)],
        "popH": [_P(_heart_d(0, 0, 3.4), _hex("#ff6f91"), sw=1.0)],
    }
    if out["leader"]:
        out["pole"] = [_P("M 0,4 L 0,-26", sw=2.6), _P("M 0,4 L 0,-26", stroke=_hex("#c88a5a"), sw=1.1)]
        out["cloth"] = [
            _P("M .8,-25.6 L 13.4,-21.4 L .8,-16.8 Z", _hex("#ff5a7a"), sw=1.0),
            _S(5.4, -21.3, 1.9, WHITE, stroke=None),
        ]
        out["ball"] = [_E(0, -27, 1.6, 1.6, _hex("#ffd23f"), sw=0.8)]
    else:
        out["cup_back"] = [
            _P("M 1,-4.4 L 2.8,-9", sw=1.9),
            _P("M 1,-4.4 L 2.8,-9", stroke=_hex("#ff8fb8"), sw=0.9),
            _P("M -2.9,-4.6 L 2.9,-4.6 L 2.3,1.9 Q 2.2,2.9 1.1,2.9 L -1.1,2.9 Q -2.2,2.9 -2.3,1.9 Z", _hex("#dff3ff"), sw=1.0),
        ]
        out["cup_front"] = [
            _E(-0.8, 0.4, 0.5, 0.5, INK, stroke=None, alpha=0.55),
            _E(0.9, -0.6, 0.5, 0.5, INK, stroke=None, alpha=0.55),
        ]
    return out


_RIGS: dict[str, dict] = {}


def _rig(cid: str) -> dict:
    got = _RIGS.get(cid)
    if got is None:
        d = next(c for c in CATS if c["id"] == cid)
        got = _RIGS[cid] = _build(d)
    return got


# ---------- 绘制 ----------

def _fade(c: tuple[int, int, int, int], a: float) -> tuple[int, int, int, int]:
    if a >= 0.999:
        return c
    return (c[0], c[1], c[2], max(0, min(255, int(c[3] * a))))


def _draw(dr: ImageDraw.ImageDraw, p: Prim, m, u: float, alpha: float = 1.0) -> None:
    a = alpha * p.alpha
    if a <= 0.02 or not p.paths:
        return
    tps = [(_apply(m, pts), closed) for pts, closed in p.paths]
    if p.fill is not None:
        col = _fade(p.fill, a)
        for pts, closed in tps:
            if closed and len(pts) >= 3:
                dr.polygon(pts, fill=col)
    if p.stroke is not None and p.sw > 0:
        wpx = max(1, int(round(p.sw * u)))
        col = _fade(p.stroke, a)
        for pts, closed in tps:
            if closed:
                pts = pts + pts[:2]
            if len(pts) >= 2:
                dr.line(pts, fill=col, width=wpx, joint="curve")


def _draw_all(dr, prims, m, u: float, alpha: float = 1.0) -> None:
    for p in prims:
        _draw(dr, p, m, u, alpha)


class Pose:
    __slots__ = (
        "y", "lean", "squash", "legL", "legR", "kL", "kR", "liftL", "liftR",
        "armL", "armR", "fsL", "fsR", "head", "eyes", "blink", "sparkle", "shout",
        "zz", "zzT", "pop", "popA", "popKind", "popRot", "puffL", "puffR",
        "cup", "cupTilt", "water", "flagWave",
    )

    def __init__(self, leader: bool) -> None:
        self.reset(leader)

    def reset(self, leader: bool) -> None:
        self.y = 0.0
        self.lean = 0.0
        self.squash = 1.0
        self.legL = self.legR = 0.0
        self.kL = self.kR = 0.0
        self.liftL = self.liftR = 0.0
        self.armL = 14.0
        self.armR = -28.0 if leader else -14.0
        self.fsL = self.fsR = 1.0
        self.head = 0.0
        self.eyes = "open"
        self.blink = 1.0
        self.sparkle = False
        self.shout = False
        self.zz = False
        self.zzT = 0.0
        self.pop = 0.0
        self.popA = 1.0
        self.popKind = "star"
        self.popRot = 0.0
        self.puffL = self.puffR = 0.0
        self.cup = False
        self.cupTilt = 0.0
        self.water = 0.8
        self.flagWave = 0.0

    def quantize(self) -> tuple:
        def q(v: float, step: float) -> float:
            return round(v / step) * step

        self.y = q(self.y, 0.25)
        self.lean = q(self.lean, 1.0)
        self.squash = q(self.squash, 0.01)
        self.legL, self.legR = q(self.legL, 2.0), q(self.legR, 2.0)
        self.kL, self.kR = q(self.kL, 0.05), q(self.kR, 0.05)
        self.liftL, self.liftR = q(self.liftL, 0.25), q(self.liftR, 0.25)
        self.armL, self.armR = q(self.armL, 2.0), q(self.armR, 2.0)
        self.fsL, self.fsR = q(self.fsL, 0.03), q(self.fsR, 0.03)
        self.head = q(self.head, 1.0)
        self.blink = q(self.blink, 0.22)
        self.zzT = q((self.zzT * 0.45) % 1.0, 0.04) if self.zz else 0.0
        self.pop = q(self.pop, 0.05)
        self.popA = q(self.popA, 0.1)
        self.popRot = q(self.popRot, 4.0)
        self.puffL, self.puffR = q(self.puffL, 0.1), q(self.puffR, 0.1)
        self.cupTilt = q(self.cupTilt, 3.0)
        self.water = q(self.water, 0.05)
        self.flagWave = q(self.flagWave, 1.5)
        return tuple(getattr(self, s) for s in self.__slots__)


def _leg_prims(kk: float, shoes) -> list[Prim]:
    ln = 10.5 * (1 - 0.55 * kk)
    return [
        _R(-2.8, -0.5, 5.6, ln + 0.5, 2.8, WHITE),
        _E(0, ln + 0.1, 3.7 * (1 + 0.3 * kk), 2.3 * (1 + 1.05 * kk), shoes),
        _E(0, ln + 0.3, 2 * (1 + 0.45 * kk), 1.3 * (1 + 1.2 * kk), WHITE, stroke=None, alpha=0.8 * kk),
    ]


def _z_prims(x: float, y: float, fs: float) -> tuple[Prim, Prim]:
    d = f"M {x},{y - 0.6 * fs} L {x + 0.55 * fs},{y - 0.6 * fs} L {x},{y} L {x + 0.55 * fs},{y}"
    return _P(d, stroke=WHITE, sw=0.42 * fs), _P(d, stroke=_hex("#8f8cff"), sw=0.2 * fs)


def render_cat(cid: str, P: Pose, k: float) -> Image.Image:
    """按姿势画一只猫；返回最终尺寸精灵（原点在 (-_BX0*k, -_BY0*k)）。"""
    rig = _rig(cid)
    U = k * SS
    W = int(math.ceil((_BX1 - _BX0) * k)) * SS
    H = int(math.ceil((_BY1 - _BY0) * k)) * SS
    im = Image.new("RGBA", (max(SS, W), max(SS, H)), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im, "RGBA")
    outer = (U, 0.0, 0.0, U, -_BX0 * U, -_BY0 * U)

    for side, a in ((-4.5, P.puffL), (4.5, P.puffR)):
        if a > 0.02:
            _draw_all(dr, rig["puff"], _chain(outer, _tr(side, 0), _sc(1.6 - 0.8 * a)), U, a)

    bob = _chain(outer, _tr(0, P.y), _rot(P.lean), _sc(2 - P.squash, P.squash))
    for hx, rot, kk, lift in ((-4.5, P.legL, P.kL, P.liftL), (4.5, P.legR, P.kR, P.liftR)):
        _draw_all(dr, _leg_prims(kk, rig["shoes"]), _chain(bob, _tr(hx, -12.5 - lift), _rot(rot)), U)
    _draw_all(dr, rig["body"], bob, U)

    leader = rig["leader"]

    def draw_arm(side: str) -> None:
        if side == "L":
            m = _chain(bob, _tr(-7.5, -24.5), _rot(P.armL), _sc(1, P.fsL))
        else:
            m = _chain(bob, _tr(7.5, -24.5), _rot(P.armR), _sc(1, P.fsR))
        _draw(dr, rig["sleeve"], m, U)
        if side == "R":
            if leader:
                pm = _chain(m, _tr(0, 9.6), _sc(1, 1 / P.fsR), _rot(-P.armR))
                _draw_all(dr, rig["pole"], pm, U)
                _draw_all(dr, rig["cloth"], _chain(pm, _rot(P.flagWave, 0.8, -21.2)), U)
                _draw_all(dr, rig["ball"], pm, U)
            elif P.cup:
                cm = _chain(m, _tr(0, 9.6), _sc(1, 1 / P.fsR), _rot(-P.armR + P.cupTilt), _tr(1.2, -2.6), _sc(1.55))
                _draw_all(dr, rig["cup_back"], cm, U)
                lv = 1.6 - 4.2 * P.water
                _draw(dr, Prim([([(-2.55, lv), (2.55, lv), (2.2, 1.6), (-2.2, 1.6)], True)], _hex("#6cc4ff"), None), cm, U)
                _draw_all(dr, rig["cup_front"], cm, U)
        _draw(dr, rig["paw"], m, U)

    top = "L" if P.armL > 100 else ("R" if P.armR < -100 else "")
    for side in ("L", "R"):
        if side != top:
            draw_arm(side)
    _draw_all(dr, rig["collar"], bob, U)

    head = _chain(bob, _rot(P.head, 0, -27))
    for tag, p in rig["head"]:
        if tag == "EYES":
            if P.eyes == "open":
                hl = rig["hlS"] if P.sparkle else rig["hl"]
                for ex in (-6.2, 6.2):
                    em = _chain(head, _tr(ex, -37.6), _sc(1, P.blink))
                    _draw(dr, rig["eye"], em, U)
                    if P.blink > 0.5:
                        _draw(dr, hl, em, U)
            continue
        if tag == "eS" and P.eyes != "sleep":
            continue
        if tag == "eH" and P.eyes != "happy":
            continue
        if tag == "mo" and P.shout:
            continue
        if tag == "moO" and not P.shout:
            continue
        _draw(dr, p, head, U)
    if top:
        draw_arm(top)

    if P.zz:
        for j in range(3):
            ph = (P.zzT + j / 3.0) % 1.0
            fs = 5.5 + ph * 4.5
            a = math.sin(math.pi * ph)
            for zp in _z_prims(8 + ph * 7 + math.sin(ph * 6) * 1.2, -50 - ph * 16, fs):
                _draw(dr, zp, outer, U, a)
    if P.pop > 0.01:
        pm = _chain(outer, _tr(0, -68 - 4 * P.pop), _sc(P.pop), _rot(P.popRot))
        _draw_all(dr, rig["popS"] if P.popKind == "star" else rig["popH"], pm, U, P.popA)
    return im.reduce(SS)


# ---------- 姿势 ----------

def _clamp(v: float, a: float, b: float) -> float:
    return a if v < a else (b if v > b else v)


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def _ease_out(t: float) -> float:
    t = _clamp(t, 0.0, 1.0)
    return 1 - (1 - t) ** 3


def _ease_back(t: float) -> float:
    t = _clamp(t, 0.0, 1.0)
    c = 1.9
    return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2


def _kick(p: float) -> float:
    if p < 0.26:
        return _ease_out(p / 0.26)
    if p < 0.6:
        return 1.0
    if p < 0.74:
        q = (p - 0.6) / 0.14
        return 1 - q * q
    return 0.0


def _stand(P: Pose, t: float, ev: list, leader: bool, i: int, wave: float) -> None:
    P.squash = 1 + 0.012 * math.sin(t * 2.2 + i)
    P.armL = 14 + 1.5 * math.sin(t * 1.3 + i)
    if not leader:
        P.armR = -14 - 1.5 * math.sin(t * 1.3 + i)
    x = t - ev[2]
    P.head = ev[3] * math.sin(math.pi * x / 1.6) if 0 <= x < 1.6 else 0.0
    b = t - ev[0]
    P.blink = 0.12 if (0 <= b < 0.13 or (ev[1] and 0.24 <= b < 0.37)) else 1.0
    P.flagWave = 5 * math.sin(t * 3.2)
    if wave > 0 and not leader:
        P.armR = _lerp(P.armR, -150, wave) + 16 * math.sin(t * 14) * wave
        P.head = _lerp(P.head, -6, wave)


def _sit(P: Pose, t: float, leader: bool, i: int, *, sleepy: bool = True) -> None:
    P.y = 3.5
    P.kL = P.kR = 1.0
    P.legL, P.legR = 16.0, -16.0
    P.armL = 6.0
    P.armR = -12.0 if leader else -6.0
    P.head = 6 * math.sin(t * 0.9 + i * 1.3)
    P.squash = 1 + 0.022 * math.sin(t * 1.6 + i)
    if sleepy:
        P.eyes = "sleep"
        P.zz = i % 2 == 0
        P.zzT = t + i * 0.7
    else:
        P.eyes = "happy"


def _march(P: Pose, tt: float, T: float, amp: float, leader: bool) -> None:
    n = int(math.floor(tt / T))
    p = tt / T - n
    k = _kick(p) * amp
    right = n % 2 == 0
    if right:
        P.kR, P.liftR, P.legR, P.legL = k, 6.2 * k, -6 * k, 3 * k
    else:
        P.kL, P.liftL, P.legL, P.legR = k, 6.2 * k, 6 * k, -3 * k
    P.y = -1.8 * k
    if 0.6 < p < 0.8:
        P.squash = 1 - 0.075 * amp * math.sin(math.pi * (p - 0.6) / 0.2)
    if right:
        P.armL, P.fsL = _lerp(14, -62, k), 1 - 0.25 * k
    elif not leader:
        P.armR, P.fsR = _lerp(-14, 62, k), 1 - 0.25 * k
    P.head = (1 if right else -1) * 1.8 * k
    P.flagWave = 7 * math.sin(tt * 7)
    if amp > 0.8 and p > 0.66:
        a = 1 - (p - 0.66) / 0.34
        if right:
            P.puffR = a
        else:
            P.puffL = a


def _show(P: Pose, dt: float, cid: str, leader: bool, i: int) -> None:
    P.reset(leader)
    if dt < SHOW_A:
        P.armL = 6.0
        if leader:
            P.armR = -28 - 18 * math.sin(math.pi * dt / SHOW_A)
        else:
            P.armR = -6.0
        P.flagWave = 10 * math.sin(dt * 18)
        P.shout = cid == "buding"
    elif dt < SHOW_M:
        _march(P, dt - SHOW_A, SHOW_T, 1.0, leader)
        P.shout = cid == "buding" and ((dt - SHOW_A) % SHOW_T) < 0.26
    elif dt < SHOW_L:
        q = (dt - SHOW_M) / 0.4
        P.armL = 4.0
        if not leader:
            P.armR = -4.0
        P.squash = 1 - 0.06 * math.sin(math.pi * q)
    else:
        q = dt - SHOW_L
        r = _ease_out(q / 0.22)
        P.armL = 4.0
        if not leader:
            P.armR = -4.0
        if leader:
            P.armL = _lerp(4, 154, r)
        else:
            P.armR = _lerp(-4, -156, r)
        P.eyes = "happy"
        P.head = -3 * r
        qs = q - i * 0.07
        if qs > 0:
            P.pop = _ease_back(qs / 0.35)
            P.popA = _clamp((SHOW_E - SHOW_L - q) / 0.3, 0.0, 1.0)
            P.popRot = 20 * math.sin(qs * 4)


def _cheer(P: Pose, dt: float, i: int) -> None:
    q = _clamp(dt / CHEER_SEC, 0.0, 1.0)
    j = math.sin(math.pi * _clamp((dt - i * 0.05) / 0.55, 0.0, 1.0))
    P.y = -6 * j
    P.kL = P.kR = 0.35 * j
    P.legL, P.legR = 12 * j, -12 * j
    up = min(1.0, dt / 0.2)
    P.armL, P.armR = _lerp(14, 150, up), _lerp(-14, -150, up)
    P.fsL = P.fsR = 1.0
    P.eyes = "happy"
    P.zz = False
    P.cup = False
    P.pop = _ease_back(dt / 0.35)
    P.popA = _clamp((1 - q) / 0.25, 0.0, 1.0)
    P.popKind = "heart"
    P.popRot = 12 * math.sin(dt * 5 + i)


# ---------- 卡片 ----------

class Layout:
    __slots__ = ("s", "k", "gy", "title_y", "row_y", "row_h", "cy", "box")

    def __init__(self, box: tuple[int, int, int, int]) -> None:
        x0, y0, x1, y1 = box
        bh = max(1, y1 - y0)
        self.box = box
        self.s = bh / 92.0
        self.k = 0.5 * self.s
        self.gy = y0 + bh - 6.5 * self.s
        self.title_y = y0 + 3.5 * self.s
        self.cy = y0 + 36.0 * self.s
        self.row_h = max(16.0, 37.0 * self.s)
        self.row_y = self.cy - self.row_h / 2.0


def layout(box: tuple[int, int, int, int]) -> Layout:
    return Layout(box)


_FONT_CACHE: dict[float, object] = {}


def big_font(size: int, fallback=None):
    """「点我开始」这类纯文字：比默认大字小一号，免得压到标题和猫头。"""
    import os
    from pathlib import Path

    from PIL import ImageFont

    size = max(10.0, min(40.0, float(size)))
    size = round(size * 4.0) / 4.0
    got = _FONT_CACHE.get(size)
    if got is not None:
        return got
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf"):
        try:
            got = ImageFont.truetype(str(windir / name), size)
            break
        except OSError:
            continue
    if got is None:
        return fallback
    _FONT_CACHE[size] = got
    return got


_GROUND_CACHE: dict[tuple[int, int, int], Image.Image] = {}
_MASK_CACHE: dict[tuple[int, int, int], Image.Image] = {}
_BACK_CACHE: dict[tuple[int, int], Image.Image] = {}
_STAR_CACHE: dict[tuple, Image.Image] = {}


def _mask(bw: int, bh: int, r: int) -> Image.Image:
    key = (bw, bh, r)
    got = _MASK_CACHE.get(key)
    if got is None:
        got = Image.new("L", (bw, bh), 0)
        ImageDraw.Draw(got).rounded_rectangle((0, 0, bw - 1, bh - 1), radius=max(0, r), fill=255)
        if len(_MASK_CACHE) > 12:
            _MASK_CACHE.clear()
        _MASK_CACHE[key] = got
    return got


def _ground(bw: int, bh: int, s: float) -> Image.Image:
    key = (bw, bh, int(s * 100))
    got = _GROUND_CACHE.get(key)
    if got is None:
        got = Image.new("RGBA", (bw, bh), (0, 0, 0, 0))
        d = ImageDraw.Draw(got)
        gy = bh - 6.5 * s
        d.rectangle((0, int(round(gy)), bw, bh), fill=_hex("#f7a6be"))
        d.line((0, gy, bw, gy), fill=INK, width=max(1, int(round(1.3 * s))))
        if len(_GROUND_CACHE) > 8:
            _GROUND_CACHE.clear()
        _GROUND_CACHE[key] = got
    return got


def _composite(dst: Image.Image, src: Image.Image, x: int, y: int) -> None:
    sx0, sy0 = max(0, -x), max(0, -y)
    sx1, sy1 = min(src.width, dst.width - x), min(src.height, dst.height - y)
    if sx1 <= sx0 or sy1 <= sy0:
        return
    dst.alpha_composite(src, (x + sx0, y + sy0), (sx0, sy0, sx1, sy1))


def _star_sprite(r: float, color, scale_q: int, rot_q: int, *, dot: bool) -> Image.Image:
    key = (round(r, 1), color, scale_q, rot_q, dot)
    got = _STAR_CACHE.get(key)
    if got is not None:
        return got
    sc = 1.0 + 0.16 * (scale_q / 2.0)
    rr = r * sc
    n = int(math.ceil(rr * 2 + 4))
    U = 4
    im = Image.new("RGBA", (n * U, n * U), (0, 0, 0, 0))
    dr = ImageDraw.Draw(im, "RGBA")
    c = n * U / 2.0
    m = _chain(_tr(c, c), _sc(U), _rot(rot_q * 6.0))
    if dot:
        _draw(dr, _E(0, 0, rr, rr, color, sw=0.6 * r / 1.8), m, U)
    else:
        _draw(dr, _S(0, 0, rr, color, sw=0.7 * r / 3.2), m, U)
    got = im.reduce(U)
    if len(_STAR_CACHE) > 160:
        _STAR_CACHE.clear()
    _STAR_CACHE[key] = got
    return got


_DECO = (
    (0.06, 0.2, 3.4, "#ffd23f", False), (0.94, 0.24, 3.1, "#5aa9ff", False),
    (0.1, 0.55, 2.4, "#ff6f91", False), (0.9, 0.58, 1.8, "#3ccf7a", True), (0.17, 0.12, 1.4, "#ffffff", True),
)


def paint_backdrop(layer: Image.Image, phase: float, *, stage: str, radius: int, light: bool = False) -> None:
    """奶粉色底 + 波点 + 几颗会眨的星星（操场和小猫画在文字之上，见 Troupe.paint）。"""
    bw, bh = layer.size
    if bw < 20 or bh < 12:
        return
    key = (bw, bh)
    base = _BACK_CACHE.get(key)
    if base is None:
        top, bot = (255, 246, 249), (255, 224, 235)
        col = Image.new("RGBA", (1, bh))
        for yy in range(bh):
            t = yy / max(1, bh - 1)
            col.putpixel((0, yy), tuple(int(a + (b - a) * t) for a, b in zip(top, bot)) + (255,))
        base = col.resize((bw, bh))
        d = ImageDraw.Draw(base, "RGBA")
        s = (bh + 9) / 92.0
        step = max(8.0, 14.0 * s)
        rr = max(0.8, 1.1 * s)
        yy = 3 * s
        while yy < bh:
            xx = 3 * s
            while xx < bw:
                d.ellipse((xx - rr, yy - rr, xx + rr, yy + rr), fill=(255, 255, 255, 235))
                d.ellipse((xx + 7 * s - rr, yy + 7 * s - rr, xx + 7 * s + rr, yy + 7 * s + rr), fill=(255, 207, 221, 190))
                xx += step
            yy += step
        if len(_BACK_CACHE) > 6:
            _BACK_CACHE.clear()
        _BACK_CACHE[key] = base
    layer.alpha_composite(base)
    s = (bh + 9) / 92.0
    fast = 3.2 if stage in ("warn", "done") else 1.2
    for j, (fx_, fy_, rr, c, dot) in enumerate(_DECO):
        sq = int(round(2 * math.sin(phase * fast + j * 1.7)))
        rq = int(round(math.sin(phase * 0.8 + j)))
        spr = _star_sprite(rr * s, _hex(c), sq, rq, dot=dot)
        _composite(layer, spr, int(round(fx_ * bw - spr.width / 2)), int(round(fy_ * bh - spr.height / 2)))


_CONF_COLORS = ("#ff6f91", "#ffd23f", "#5aa9ff", "#3ccf7a", "#a78bfa", "#ff9a3c")


def _hash01(n: int, salt: int) -> float:
    s = (n * 2654435761 + salt * 40503) & 0xFFFFFFFF
    s = (s * 1103515245 + 12345) & 0x7FFFFFFF
    return (s >> 8) / float(1 << 23)


class Troupe:
    """一支仪仗队的运行状态：点击表演、欢呼、到点游行计时、眨眼歪头等随机小动作。"""

    def __init__(self, seed: int | None = None) -> None:
        self.show_at: float | None = None
        self.cheer_at: float | None = None
        self.done_at: float | None = None
        self.stage = "run"
        self._rng = random.Random(seed)
        self._ev: dict[str, list] = {}
        self._wave_at = 3.0
        self._wave_id = "taotao"
        self._cache: OrderedDict[tuple, Image.Image] = OrderedDict()
        self._pose = Pose(False)
        self._resize_at: float | None = None

    # ---- 交互 ----
    def _expire(self, now: float) -> None:
        if self.show_at is not None and now - self.show_at > SHOW_E:
            self.show_at = None
        if self.cheer_at is not None and now - self.cheer_at > CHEER_SEC:
            self.cheer_at = None

    def poke(self, now: float) -> str:
        """点卡片：到点后欢呼，其它时候集合踢正步。表演中再点不打断。"""
        self._expire(now)
        if self.show_at is not None or self.cheer_at is not None:
            return "busy"
        if self.stage == "done":
            self.cheer_at = now
            return "cheer"
        self.show_at = now
        return "show"

    def cheer(self, now: float) -> None:
        self.show_at = None
        self.cheer_at = now

    def busy(self, now: float) -> bool:
        self._expire(now)
        return self.show_at is not None or self.cheer_at is not None

    def callout(self, now: float) -> str | None:
        """表演时顶上那行字跟着喊口号。"""
        self._expire(now)
        if self.cheer_at is not None:
            return "喝过啦，真乖" if self.stage != "done" else "下班快乐"
        if self.show_at is None:
            return None
        dt = now - self.show_at
        if dt < SHOW_A:
            return "预备——"
        if dt < SHOW_M:
            return _CALLS[min(7, int((dt - SHOW_A) / SHOW_T))] + "！"
        if dt < SHOW_L:
            return "立正！"
        return "敬礼！"

    def marching_done(self, now: float) -> bool:
        return self.done_at is None or now - self.done_at < DONE_MARCH_SEC

    def resizing(self, on: bool, now: float) -> None:
        """拖边拉伸期间把小动作定格，尺寸变化就不再叠着眨眼挥手一起抖。"""
        if on:
            if self._resize_at is None:
                self._resize_at = now
        else:
            self._resize_at = None

    def fps(self, stage: str, now: float, *, drinking: bool = False) -> int:
        self._expire(now)
        if self.show_at is not None or self.cheer_at is not None:
            return 30
        if drinking:
            return 20
        if stage == "done":
            return 24 if self.marching_done(now) else 8
        if stage == "warn":
            return 24
        if stage == "idle":
            return 10
        return 12

    # ---- 随机小动作 ----
    def _events(self, cid: str, t: float) -> list:
        r = self._rng.random
        e = self._ev.get(cid)
        if e is None:
            e = self._ev[cid] = [t + 0.6 + r() * 3, False, t + 1.5 + r() * 5, 0.0]
        if t > e[0] + 0.5:
            e[0] = t + 2 + r() * 3.6
            e[1] = r() < 0.3
        if t > e[2] + 1.6:
            e[2] = t + 3 + r() * 6
            e[3] = (-1 if r() < 0.5 else 1) * (6 + r() * 5)
        return e

    def _wave(self, cid: str, t: float) -> float:
        if t > self._wave_at + 1.8:
            pool = [c["id"] for c in CATS if not c.get("leader")]
            self._wave_at = t + 6 + self._rng.random() * 7
            self._wave_id = pool[int(self._rng.random() * len(pool)) % len(pool)]
        if cid != self._wave_id:
            return 0.0
        x = t - self._wave_at
        if x < 0 or x > 1.8:
            return 0.0
        return _clamp(min(x / 0.25, (1.8 - x) / 0.25), 0.0, 1.0)

    def _sprite(self, cid: str, P: Pose, k: float) -> Image.Image:
        """按姿势取精灵。k 落到最近的档位上画，再缩到需要的尺寸。

        描边是矢量里最贵的一步，拖动时尺寸连续变化，档位让相邻尺寸共用一张画好的猫。
        """
        base = _SCALE_STEP * max(1, round(k / _SCALE_STEP))
        key = (cid, round(base, 4)) + P.quantize()
        got = self._cache.get(key)
        if got is None:
            got = render_cat(cid, P, base)
            while len(self._cache) >= 420:
                self._cache.popitem(last=False)
            self._cache[key] = got
        else:
            self._cache.move_to_end(key)
        if abs(base - k) < 1e-3:
            return got
        ratio = k / base
        w = max(1, int(round(got.width * ratio)))
        h = max(1, int(round(got.height * ratio)))
        return got.resize((w, h), Image.Resampling.BILINEAR)

    # ---- 绘制 ----
    def paint(
        self,
        img: Image.Image,
        box: tuple[int, int, int, int],
        *,
        radius: int,
        stage: str,
        now: float,
        mins_left: int = 30,
        drinking: bool = False,
    ) -> None:
        x0, y0, x1, y1 = box
        bw, bh = max(1, x1 - x0), max(1, y1 - y0)
        if bw < 60 or bh < 30:
            return
        self._expire(now)
        if stage == "done":
            if self.done_at is None:
                self.done_at = now
        else:
            self.done_at = None
        self.stage = stage
        lay = Layout(box)
        s, k = lay.s, lay.k
        gy_local = bh - 6.5 * s
        layer = _ground(bw, bh, s).copy()

        count = int(_clamp(math.floor((bw - 16 * s) / (31 * s)), 2, len(CATS)))
        cats = CATS[len(CATS) - count:]
        gap = min(34 * s, (bw - 26 * s) / count)
        xs = [bw / 2.0 - (count - 1) * gap / 2.0 + i * gap for i in range(count)]
        drinker = None
        if drinking:
            ids = [c["id"] for c in cats]
            drinker = "taotao" if "taotao" in ids else next(c["id"] for c in cats if not c.get("leader"))
        drinker_x = xs[[c["id"] for c in cats].index(drinker)] if drinker else 0.0
        marching = stage == "done" and self.marching_done(now)
        # 拖边时尺寸每帧都变，小动作也跟着变就会两边一起抖；定格到按下那一刻，松手再继续
        t = self._resize_at if self._resize_at is not None else now
        P = self._pose
        for i, (c, x) in enumerate(zip(cats, xs)):
            cid = c["id"]
            leader = bool(c.get("leader"))
            P.reset(leader)
            X = x
            if stage == "idle":
                _sit(P, t, leader, i)
            elif stage == "warn" and not drinking:
                _stand(P, t, self._events(cid, t), leader, i, 0.0)
                Tw = _lerp(0.3, 0.62, _clamp((mins_left - 1) / 29.0, 0.0, 1.0))
                _march(P, t, Tw, 0.5, leader)
                P.sparkle = True
            elif stage == "done":
                if marching:
                    _march(P, t, 0.5, 1.0, leader)
                    P.eyes = "happy"
                    span = bw + 30 * s
                    X = (x + 15 * s + t * 13 * s) % span - 15 * s
                else:
                    _sit(P, t, leader, i, sleepy=False)
            else:
                _stand(P, t, self._events(cid, t), leader, i, self._wave(cid, t) if stage == "run" else 0.0)
                if drinker is not None:
                    if cid == drinker:
                        P.cup = True
                        P.armR = -112.0
                        cyc = t % 2.8
                        f = math.sin(math.pi * (cyc - 0.5) / 1.1) if 0.5 < cyc < 1.6 else 0.0
                        P.cupTilt = -40 * f
                        P.head = 9 * f
                        if f > 0.35:
                            P.eyes = "happy"
                        P.water = 0.85 - 0.35 * ((t / 2.8) % 3) / 3
                    else:
                        P.head = 6.0 if drinker_x > x else -6.0
            if self.show_at is not None:
                _show(P, t - self.show_at, cid, leader, i)
            if self.cheer_at is not None:
                _cheer(P, t - self.cheer_at, i)
            spr = self._sprite(cid, P, k)
            _composite(layer, spr, int(round(X + _BX0 * k)), int(round(gy_local + _BY0 * k)))

        if marching or self.cheer_at is not None:
            d = ImageDraw.Draw(layer, "RGBA")
            for j in range(14):
                vy = (14 + _hash01(j, 1) * 18) * s
                yy = (_hash01(j, 2) * (bh + 8) + t * vy) % (bh + 8) - 4
                xx = _hash01(j, 3) * bw + math.sin(t * 2 + j) * 4 * s
                rot = t * 4.2 + j
                cw, ch = 1.3 * s, 0.75 * s
                co, si = math.cos(rot), math.sin(rot)
                pts = [(xx + px * co - py * si, yy + px * si + py * co) for px, py in ((-cw, -ch), (cw, -ch), (cw, ch), (-cw, ch))]
                d.polygon(pts, fill=_hex(_CONF_COLORS[j % len(_CONF_COLORS)]))

        a = layer.getchannel("A")
        layer.putalpha(ImageChops.multiply(a, _mask(bw, bh, int(radius))))
        img.alpha_composite(layer, (x0, y0))


_DEFAULT: Troupe | None = None


def default_troupe() -> Troupe:
    global _DEFAULT
    if _DEFAULT is None:
        _DEFAULT = Troupe(seed=7)
    return _DEFAULT
