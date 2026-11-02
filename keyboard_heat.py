"""工时账本里的键盘。每个键一块，按次数从冷到暖着色。不画按键顺序。"""
from __future__ import annotations

import os
from datetime import date, timedelta
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageTk

import activity
import activity_chart

W = activity_chart.W * 2 + activity_chart.GAP
_PAD_X = 16
_HEAD = 42
_RANK = 52
_FOLD = {"10": "A0", "11": "A2", "12": "A4"}
_FONT: dict[tuple, ImageFont.ImageFont] = {}

_DECK = (16, 20, 30, 255)
_IDLE = (27, 33, 46, 255)
_EDGE = (58, 68, 86, 255)
_INK = (214, 222, 234, 255)
_DIM = (132, 142, 160, 255)
_QUIET = (96, 106, 124, 255)
_STOPS = (
    (0.0, (32, 52, 78)),
    (0.22, (38, 92, 148)),
    (0.55, (72, 168, 206)),
    (0.82, (186, 214, 168)),
    (1.0, (255, 196, 112)),
)


def _font(size: float, *, bold: bool = False) -> ImageFont.ImageFont:
    key = (round(float(size) * 4.0) / 4.0, bold)
    got = _FONT.get(key)
    if got is not None:
        return got
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    names = ("msyhbd.ttc", "msyhbd.ttf", "msyh.ttc") if bold else ("msyh.ttc", "msyh.ttf", "msyhbd.ttc", "simhei.ttf")
    for name in names:
        try:
            got = ImageFont.truetype(str(windir / name), key[0])
            break
        except OSError:
            continue
    if got is None:
        got = ImageFont.load_default()
    _FONT[key] = got
    return got


def _hx(n: int) -> str:
    return f"{int(n):02X}"


def _board() -> list[tuple]:
    """一块键：(键号, 名字, 左, 上, 宽, 高, 区域)。单位是主键的一格。

    区域：main 字母数字，extra 屏/滚/停，nav 方向和 Ins，num 小键盘。
    没按过的区域不画，笔记本就不会空着一块小键盘。
    """
    row = 1.32
    step = 1.08
    y1, y2, y3, y4, y5 = row, row + step, row + step * 2, row + step * 3, row + step * 4
    keys: list[tuple] = [(_hx(0x1B), "Esc", 0.0, 0.0, 1.25, 1.0, "main")]
    x = 2.05
    for i in range(12):
        if i in (4, 8):
            x += 0.42
        keys.append((_hx(0x70 + i), f"F{i + 1}", x, 0.0, 1.0, 1.0, "main"))
        x += 1.0
    x += 0.28
    for ident, label in ((_hx(0x2C), "屏"), (_hx(0x91), "滚"), (_hx(0x13), "停")):
        keys.append((ident, label, x, 0.0, 1.0, 1.0, "extra"))
        x += 1.0

    number = [(_hx(0xC0), "`")]
    number += [(_hx(0x30 + i), str(i)) for i in range(1, 10)]
    number.append((_hx(0x30), "0"))
    number += [(_hx(0xBD), "-"), (_hx(0xBB), "=")]
    x = 0.0
    for ident, label in number:
        keys.append((ident, label, x, y1, 1.0, 1.0, "main"))
        x += 1.0
    keys.append((_hx(0x08), "退格", x, y1, 2.0, 1.0, "main"))

    letters = "QWERTYUIOP"
    punct = [(_hx(0xDB), "["), (_hx(0xDD), "]")]
    x = 1.5
    keys.append((_hx(0x09), "Tab", 0.0, y2, 1.5, 1.0, "main"))
    for ch in letters:
        keys.append((_hx(ord(ch)), ch, x, y2, 1.0, 1.0, "main"))
        x += 1.0
    for ident, label in punct:
        keys.append((ident, label, x, y2, 1.0, 1.0, "main"))
        x += 1.0
    keys.append((_hx(0xDC), "\\", x, y2, 1.5, 1.0, "main"))

    home = "ASDFGHJKL"
    x = 1.75
    keys.append((_hx(0x14), "Caps", 0.0, y3, 1.75, 1.0, "main"))
    for ch in home:
        keys.append((_hx(ord(ch)), ch, x, y3, 1.0, 1.0, "main"))
        x += 1.0
    for ident, label in ((_hx(0xBA), ";"), (_hx(0xDE), "'")):
        keys.append((ident, label, x, y3, 1.0, 1.0, "main"))
        x += 1.0
    keys.append((_hx(0x0D), "回车", x, y3, 15.0 - x, 1.0, "main"))

    bottom_letters = "ZXCVBNM"
    x = 2.25
    keys.append((_hx(0xA0), "Shift", 0.0, y4, 2.25, 1.0, "main"))
    for ch in bottom_letters:
        keys.append((_hx(ord(ch)), ch, x, y4, 1.0, 1.0, "main"))
        x += 1.0
    for ident, label in ((_hx(0xBC), ","), (_hx(0xBE), "."), (_hx(0xBF), "/")):
        keys.append((ident, label, x, y4, 1.0, 1.0, "main"))
        x += 1.0
    keys.append((_hx(0xA1), "Shift", x, y4, 15.0 - x, 1.0, "main"))

    mods = (
        (_hx(0xA2), "Ctrl", 1.3),
        (_hx(0x5B), "Win", 1.25),
        (_hx(0xA4), "Alt", 1.25),
    )
    x = 0.0
    for ident, label, width in mods:
        keys.append((ident, label, x, y5, width, 1.0, "main"))
        x += width
    space_w = 6.4
    keys.append((_hx(0x20), "空格", x, y5, space_w, 1.0, "main"))
    x += space_w
    for ident, label, width in (
        (_hx(0xA5), "Alt", 1.2),
        (_hx(0x5C), "Win", 1.2),
        (_hx(0x5D), "菜单", 1.2),
        (_hx(0xA3), "Ctrl", 15.0 - (x + 1.2 + 1.2 + 1.2)),
    ):
        keys.append((ident, label, x, y5, width, 1.0, "main"))
        x += width

    nav_x = 15.48
    for col, (ident, label) in enumerate(
        ((_hx(0x2D), "Ins"), (_hx(0x24), "Home"), (_hx(0x21), "PgUp"))
    ):
        keys.append((ident, label, nav_x + col, y1, 1.0, 1.0, "nav"))
    for col, (ident, label) in enumerate(
        ((_hx(0x2E), "Del"), (_hx(0x23), "End"), (_hx(0x22), "PgDn"))
    ):
        keys.append((ident, label, nav_x + col, y2, 1.0, 1.0, "nav"))
    keys.append((_hx(0x26), "上", nav_x + 1.0, y4, 1.0, 1.0, "nav"))
    for col, (ident, label) in enumerate(
        ((_hx(0x25), "左"), (_hx(0x28), "下"), (_hx(0x27), "右"))
    ):
        keys.append((ident, label, nav_x + col, y5, 1.0, 1.0, "nav"))

    num_x = 19.0
    top = ((_hx(0x90), "Num"), (_hx(0x6F), "/"), (_hx(0x6A), "*"), (_hx(0x6D), "-"))
    for col, (ident, label) in enumerate(top):
        keys.append((ident, label, num_x + col, y1, 1.0, 1.0, "num"))
    for col, ident in enumerate((_hx(0x67), _hx(0x68), _hx(0x69))):
        keys.append((ident, str(7 + col), num_x + col, y2, 1.0, 1.0, "num"))
    keys.append((_hx(0x6B), "+", num_x + 3, y2, 1.0, 2.0, "num"))
    for col, ident in enumerate((_hx(0x64), _hx(0x65), _hx(0x66))):
        keys.append((ident, str(4 + col), num_x + col, y3, 1.0, 1.0, "num"))
    for col, ident in enumerate((_hx(0x61), _hx(0x62), _hx(0x63))):
        keys.append((ident, str(1 + col), num_x + col, y4, 1.0, 1.0, "num"))
    keys.append(("numenter", "回车", num_x + 3, y4, 1.0, 2.0, "num"))
    keys.append((_hx(0x60), "0", num_x, y5, 2.0, 1.0, "num"))
    keys.append((_hx(0x6E), ".", num_x + 2, y5, 1.0, 1.0, "num"))
    return keys


_KEYS = _board()
_LABELS = {ident: label for ident, label, *_rest in _KEYS}
_ZONE = {ident: zone for ident, _l, _x, _y, _w, _h, zone in _KEYS}
_NUM_SHIFT = 19.0 - 15.48


def _live_zones(keymap: dict | None = None, hide_id: str | None = None, remembered: list | None = None) -> frozenset:
    """今天按过的，加上这台电脑以前按过的区域。字母区总在。"""
    zones = {"main"}
    for z in remembered or []:
        if z in ("nav", "num", "extra"):
            zones.add(z)
    for ident in keymap or {}:
        zones.add(_ZONE.get(_FOLD.get(str(ident), str(ident)), activity.key_zone(str(ident))))
    if hide_id:
        zones.add(_ZONE.get(hide_id, activity.key_zone(hide_id)))
    return frozenset(zones)


def _live_keys(zones: frozenset | set | None = None) -> list[tuple]:
    """按区域拼键盘。没有方向键时，小键盘往左靠，不留空档。"""
    zones = zones or frozenset({"main"})
    nav = "nav" in zones
    out = []
    for ident, label, x, y, w, h, zone in _KEYS:
        if zone not in zones:
            continue
        if zone == "num" and not nav:
            x = x - _NUM_SHIFT
        out.append((ident, label, x, y, w, h))
    return out


def _geom(keys: list[tuple] | None = None) -> tuple[float, float]:
    keys = keys or _live_keys()
    span = max(x + w for _i, _l, x, _y, w, _h in keys)
    depth = max(y + h for _i, _l, _x, y, _w, h in keys)
    return span, depth


def _board_width(width: int | None) -> int:
    """和上面两张图同一条宽度。窄于两张图时仍按两张图来，避免键挤坏。"""
    if width is None:
        return W
    return max(W, int(width))


def _full_span() -> float:
    return _geom(_live_keys(frozenset({"main", "extra", "nav", "num"})))[0]


def _scale(width: int | None = None, span: float | None = None) -> float:
    """键的大小按完整键盘来，缺的区域不把剩下的键撑大。"""
    inner = _board_width(width) - _PAD_X * 2
    full = _full_span()
    live = span or _geom()[0]
    return min(inner / live, inner / full)


def _rect(x: float, y: float, w: float, h: float, unit: float, origin: float = 0.0) -> tuple[int, int, int, int]:
    inset = max(2, int(unit * 0.07))
    left = _PAD_X + int(origin + x * unit) + inset
    top = _HEAD + int(y * unit) + inset
    right = _PAD_X + int(origin + (x + w) * unit) - inset
    bottom = _HEAD + int((y + h) * unit) - inset
    return left, top, max(left + 4, right), max(top + 4, bottom)


def image_size(width: int | None = None, zones: frozenset | set | None = None) -> tuple[int, int]:
    width = _board_width(width)
    span, depth = _geom(_live_keys(zones))
    unit = _scale(width, span)
    return width, _HEAD + int(depth * unit) + _RANK + 12


def _heat(t: float) -> tuple[int, int, int, int]:
    t = max(0.0, min(1.0, t))
    for i in range(1, len(_STOPS)):
        left_t, left = _STOPS[i - 1]
        right_t, right = _STOPS[i]
        if t <= right_t or i == len(_STOPS) - 1:
            span = right_t - left_t or 1.0
            u = (t - left_t) / span
            rgb = tuple(int(left[c] + (right[c] - left[c]) * u) for c in range(3))
            return rgb[0], rgb[1], rgb[2], 255
    return _STOPS[-1][1][0], _STOPS[-1][1][1], _STOPS[-1][1][2], 255


def _ink(fill: tuple[int, int, int, int], hot: bool) -> tuple[int, int, int, int]:
    if not hot:
        return _DIM
    bright = fill[0] * 0.3 + fill[1] * 0.5 + fill[2] * 0.2
    if bright > 150:
        return (42, 32, 18, 255)
    return _INK


def _center(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int], text: str, font, fill) -> None:
    if not text:
        return
    x0, y0, x1, y1 = box
    try:
        bb = draw.textbbox((0, 0), text, font=font)
        tw, th = bb[2] - bb[0], bb[3] - bb[1]
        ox, oy = bb[0], bb[1]
    except AttributeError:
        tw, th = font.getsize(text)
        ox = oy = 0
    draw.text((x0 + (x1 - x0 - tw) / 2 - ox, y0 + (y1 - y0 - th) / 2 - oy), text, font=font, fill=fill)


def _title(focus: date, today: date) -> str:
    if focus == today:
        return "今天的键盘"
    if focus == today - timedelta(days=1):
        return "昨天的键盘"
    return f"{focus.month}/{focus.day} 的键盘"


def _shown(ident: str) -> str:
    if ident == _hx(0x20):
        return "空格"
    label = _LABELS.get(ident)
    if label:
        return label
    try:
        import key_hide
        return key_hide.label(int(ident, 16))
    except ValueError:
        return ident


def _top(keymap: dict) -> list[tuple[str, int]]:
    folded: dict[str, int] = {}
    for ident, count in keymap.items():
        name = _FOLD.get(str(ident), str(ident))
        folded[name] = folded.get(name, 0) + int(count)
    ranked = sorted(folded.items(), key=lambda item: item[1], reverse=True)
    return [(ident, count) for ident, count in ranked if count > 0][:3]


def _summary(keymap: dict, *, enabled: bool, legacy: int) -> str:
    if not enabled:
        return "次数开关关着，不记每个键"
    total = sum(int(n) for n in keymap.values())
    if total <= 0 and legacy > 0:
        return "这天只记了总次数，没有每个键"
    if total <= 0:
        return "还没有按键。指到键上可以看按了多少下"
    parts = [f"{_shown(ident)} 按了 {activity.fmt_count(count)} 次" for ident, count in _top(keymap)]
    return "按得最多：" + "，".join(parts)


def _rank_name(ident: str) -> str:
    """排行里左右键、小键盘和主键要能分开认。图上靠位置区分，列表里不行。"""
    special = {
        "A0": "左 Shift",
        "A1": "右 Shift",
        "A2": "左 Ctrl",
        "A3": "右 Ctrl",
        "A4": "左 Alt",
        "A5": "右 Alt",
        "5B": "左 Win",
        "5C": "右 Win",
        "0D": "回车",
        "numenter": "小键盘回车",
        "6F": "小键盘 /",
        "6A": "小键盘 *",
        "6D": "小键盘 -",
        "6B": "小键盘 +",
        "6E": "小键盘 .",
    }
    if ident in special:
        return special[ident]
    try:
        vk = int(ident, 16)
    except ValueError:
        return _shown(ident)
    if 0x60 <= vk <= 0x69:
        return f"小键盘 {vk - 0x60}"
    return _shown(ident)


def _ordered(keymap: dict | None) -> list[tuple[str, int]]:
    folded: dict[str, int] = {}
    for ident, count in (keymap or {}).items():
        n = int(count)
        if n <= 0:
            continue
        name = _FOLD.get(str(ident), str(ident))
        folded[name] = folded.get(name, 0) + n
    return sorted(folded.items(), key=lambda item: (-item[1], item[0]))


def _fold(keymap: dict | None) -> dict[str, int]:
    board: dict[str, int] = {}
    for key, count in (keymap or {}).items():
        n = int(count)
        if n <= 0:
            continue
        ident = _FOLD.get(str(key), str(key))
        if ident not in _LABELS and ident != "numenter":
            continue
        board[ident] = board.get(ident, 0) + n
    return board


def render(
    keymap: dict | None,
    *,
    enabled: bool = True,
    legacy: int = 0,
    focus: date | None = None,
    today: date | None = None,
    hide_id: str | None = None,
    width: int | None = None,
    zones: frozenset | set | None = None,
) -> tuple[Image.Image, list[dict], str]:
    """画出键盘。hits 给鼠标悬停用，第三项是键下面那一行说明。"""
    board = _fold(keymap) if enabled else {}
    today = today or date.today()
    focus = focus or today
    zones = zones or _live_zones(keymap, hide_id)
    keys = _live_keys(zones)
    span, depth = _geom(keys)
    width, height = image_size(width, zones)
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=14, fill=_DECK)
    title_font = _font(13, bold=True)
    meta_font = _font(11)
    draw.text((18, 12), _title(focus, today), font=title_font, fill=_INK if enabled else _QUIET)
    total = sum(board.values()) if enabled else 0
    if enabled and total > 0:
        count = activity.fmt_count(total) + " 次"
        try:
            tw = draw.textbbox((0, 0), count, font=meta_font)[2]
        except AttributeError:
            tw = meta_font.getsize(count)[0]
        draw.text((width - 18 - tw, 14), count, font=meta_font, fill=_DIM)
        _legend(draw, width - 18 - tw - 78, 16)
    elif enabled and legacy > 0:
        draw.text((width - 196, 14), "只有总次数", font=meta_font, fill=_QUIET)

    peak = max(board.values()) if board else 0
    unit = _scale(width, span)
    origin = max(0.0, (_board_width(width) - _PAD_X * 2 - span * unit) / 2)
    name_font = _font(10)
    hits = []
    for ident, label, x, y, w, h in keys:
        box = _rect(x, y, w, h, unit, origin)
        count = board.get(ident, 0) if enabled else 0
        hot = enabled and count > 0 and peak > 0
        if not enabled:
            fill = (24, 29, 40, 255)
            edge = (42, 48, 62, 255)
        elif not hot:
            fill = _IDLE
            edge = _EDGE
        else:
            fill = _heat((count / peak) ** 0.55)
            edge = tuple(min(255, c + 24) for c in fill[:3]) + (255,)
        draw.rounded_rectangle(box, radius=6, fill=fill, outline=edge)
        if ident in (_hx(0x46), _hx(0x4A)):
            notch = (box[0] + (box[2] - box[0] - 10) // 2, box[3] - 5, box[0] + (box[2] - box[0] + 10) // 2, box[3] - 3)
            draw.rounded_rectangle(notch, radius=1, fill=_QUIET if not hot else _ink(fill, True))
        _center(draw, box, label, name_font, _ink(fill, hot) if enabled else _QUIET)
        share = f"{round(100 * count / total)}%" if total and count else ""
        shown = _LABELS.get(ident) or label or ident
        if ident == _hx(0x20):
            shown = "空格"
        if not enabled:
            text = f"{shown} · 没在记"
        elif count <= 0:
            text = f"{shown} · 还没按过"
        else:
            text = f"{shown} · 按了 {activity.fmt_count(count)} 次"
            if share:
                text += f" · 占今天 {share}"
        if hide_id and ident == hide_id:
            dot = 5
            draw.ellipse((box[2] - dot - 5, box[1] + 4, box[2] - 5, box[1] + 4 + dot), fill=(255, 196, 112, 255))
            text += " · 隐藏键"
        hits.append({"x0": box[0], "y0": box[1], "x1": box[2], "y1": box[3], "text": text})
    _rank(draw, _top(board) if enabled else [], width, _HEAD + int(depth * unit) + 6)
    return img, hits, _summary(board if enabled else {}, enabled=enabled, legacy=legacy if enabled else 0)


def _rank(draw: ImageDraw.ImageDraw, ranked: list[tuple[str, int]], width: int, top: int) -> None:
    """按得最多的三个键，键名和「按了多少次」写在一起。"""
    font = _font(11)
    if not ranked:
        note = "数字是这个键按了多少下"
        try:
            tw = draw.textbbox((0, 0), note, font=font)[2]
        except AttributeError:
            tw = font.getsize(note)[0]
        draw.text(((width - tw) / 2, top + 12), note, font=font, fill=_QUIET)
        return
    chips = []
    for ident, count in ranked:
        name = _shown(ident)
        times = f"按了 {activity.fmt_count(count)} 次"
        try:
            nw = draw.textbbox((0, 0), name, font=font)[2]
            cw = draw.textbbox((0, 0), times, font=font)[2]
        except AttributeError:
            nw = font.getsize(name)[0]
            cw = font.getsize(times)[0]
        cap = max(28, nw + 16)
        chips.append((name, times, cap, cap + 8 + cw))
    gap = 28
    total_w = sum(item[3] for item in chips) + gap * (len(chips) - 1)
    x = max(16, (width - total_w) / 2)
    for name, times, cap, whole in chips:
        y0, y1 = top + 8, top + 36
        draw.rounded_rectangle((x, y0, x + cap, y1), radius=6, fill=(36, 64, 96, 255), outline=_EDGE)
        _center(draw, (int(x), y0, int(x + cap), y1), name, font, _INK)
        draw.text((x + cap + 8, top + 14), times, font=font, fill=_INK)
        x += whole + gap


_RANK_ROWS = 12
_RANK_ROW = 36


def _text_w(draw: ImageDraw.ImageDraw, text: str, font) -> int:
    try:
        return int(draw.textbbox((0, 0), text, font=font)[2])
    except AttributeError:
        return int(font.getsize(text)[0])


def render_rank(
    keymap: dict | None,
    *,
    enabled: bool = True,
    legacy: int = 0,
    focus: date | None = None,
    today: date | None = None,
    hide_id: str | None = None,
    width: int | None = None,
    zones: frozenset | set | None = None,
) -> tuple[Image.Image, list[dict], str]:
    """按次数从多到少排。和键盘图同一宽度。"""
    _ = zones
    ranked = _ordered(keymap) if enabled else []
    today = today or date.today()
    focus = focus or today
    width = _board_width(width)
    shown = ranked[:_RANK_ROWS]
    rows = max(1, len(shown))
    extra = 22 if len(ranked) > _RANK_ROWS else 0
    height = 50 + rows * _RANK_ROW + 14 + extra
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle((0, 0, width - 1, height - 1), radius=14, fill=_DECK)
    title_font = _font(13, bold=True)
    meta_font = _font(11)
    name_font = _font(12)
    title = _title(focus, today).replace("的键盘", "的排行")
    draw.text((18, 14), title, font=title_font, fill=_INK if enabled else _QUIET)
    total = sum(count for _ident, count in ranked)
    if enabled and total > 0:
        count_text = activity.fmt_count(total) + " 次"
        draw.text((width - 18 - _text_w(draw, count_text, meta_font), 16), count_text, font=meta_font, fill=_DIM)
    elif enabled and legacy > 0:
        draw.text((width - 196, 16), "只有总次数", font=meta_font, fill=_QUIET)

    hits: list[dict] = []
    if not enabled or not shown:
        note = "没在记按键" if not enabled else ("这天只记了总次数，没有每个键" if legacy > 0 else "还没有按键")
        draw.text(((width - _text_w(draw, note, meta_font)) / 2, 64), note, font=meta_font, fill=_QUIET)
        summary = _summary({}, enabled=enabled, legacy=legacy if enabled else 0)
        return img, hits, summary

    def _listed(items: list[tuple[str, int]]) -> str:
        parts = [
            f"{_rank_name(ident)} 按了 {activity.fmt_count(count)} 次"
            for ident, count in items[:3]
        ]
        return "按得最多：" + "，".join(parts)

    peak = shown[0][1]
    name_x, name_w = 58, 132
    count_w, share_w = 92, 52
    bar_x = name_x + name_w + 12
    bar_right = width - 18 - share_w - count_w - 8
    for i, (ident, count) in enumerate(shown):
        y = 48 + i * _RANK_ROW
        if i % 2 == 0:
            draw.rounded_rectangle((10, y, width - 11, y + _RANK_ROW - 6), radius=8, fill=(22, 27, 38, 255))
        place = str(i + 1)
        place_fill = (255, 196, 112, 255) if i < 3 else _QUIET
        draw.text((18, y + 8), place, font=meta_font, fill=place_fill)
        t = (count / peak) ** 0.55 if peak else 0
        fill = _heat(t)
        draw.rounded_rectangle((34, y + 12, 48, y + 24), radius=3, fill=fill)
        name = _rank_name(ident)
        draw.text((name_x, y + 7), name, font=name_font, fill=_INK)
        if hide_id and ident == hide_id:
            dot_x = name_x + min(name_w - 12, _text_w(draw, name, name_font) + 6)
            draw.ellipse((dot_x, y + 11, dot_x + 8, y + 19), fill=(255, 196, 112, 255))
        track = (bar_x, y + 13, max(bar_x + 8, bar_right), y + 23)
        draw.rounded_rectangle(track, radius=4, fill=_IDLE)
        span = max(0, bar_right - bar_x)
        filled = max(6, int(span * count / peak)) if peak else 0
        draw.rounded_rectangle((bar_x, y + 13, bar_x + filled, y + 23), radius=4, fill=fill)
        times = f"{activity.fmt_count(count)} 次"
        share = f"{round(100 * count / total)}%" if total else ""
        draw.text((bar_right + 12, y + 8), times, font=meta_font, fill=_INK)
        draw.text((width - 18 - _text_w(draw, share, meta_font), y + 8), share, font=meta_font, fill=_DIM)
        text = f"{name} · 按了 {activity.fmt_count(count)} 次"
        if share:
            text += f" · 占今天 {share}"
        text += f" · 第 {i + 1}"
        if hide_id and ident == hide_id:
            text += " · 隐藏键"
        hits.append({"x0": 10, "y0": y, "x1": width - 10, "y1": y + _RANK_ROW - 4, "text": text})
    summary = _listed(ranked)
    if len(ranked) > _RANK_ROWS:
        rest = len(ranked) - _RANK_ROWS
        note = f"还有 {rest} 个键，没有列在上面"
        draw.text(((width - _text_w(draw, note, meta_font)) / 2, 48 + rows * _RANK_ROW), note, font=meta_font, fill=_QUIET)
        summary += f"。下面是前 {_RANK_ROWS} 名，还有 {rest} 个键"
    return img, hits, summary


def _legend(draw: ImageDraw.ImageDraw, x: int, y: int) -> None:
    for i in range(4):
        fill = _heat(i / 3)
        draw.rounded_rectangle((x + i * 12, y, x + i * 12 + 8, y + 8), radius=2, fill=fill)


def hit_text(hits: list[dict], x: int, y: int) -> str:
    for hit in hits:
        if hit["x0"] <= x < hit["x1"] and hit["y0"] <= y < hit["y1"]:
            return str(hit["text"])
    return ""


def brief(keymap: dict | None, *, enabled: bool = True, legacy: int = 0) -> str:
    """收起时那一行。只留按得最多的那个键。"""
    if not enabled:
        return "次数开关关着，不记每个键"
    ranked = _ordered(keymap)
    if not ranked and legacy > 0:
        return "这天只记了总次数"
    if not ranked:
        return "还没有按键"
    ident, count = ranked[0]
    return f"按得最多 {_rank_name(ident)} 按了 {activity.fmt_count(count)} 次"


def view_width(ui: dict) -> int:
    """和上面两张图那一行一样宽。"""
    charts = ui.get("charts")
    try:
        if charts is not None and charts.winfo_ismapped():
            got = int(charts.winfo_width())
            if got > 1:
                return got
    except Exception:
        pass
    try:
        content = int(ui.get("content_w") or 0)
    except (TypeError, ValueError):
        content = 0
    return content if content > 1 else W


def paint_into(ui: dict, cfg: dict, focus: date, today: date, *, enabled: bool) -> None:
    """选中的那一天。收起时只改标题栏那一句。次数没变就不重画。"""
    label = ui.get("heat_lbl")
    brief_var = ui.get("heat_brief")
    if label is None and brief_var is None:
        return
    counted = activity.counts(cfg, focus) if enabled else {}
    keymap = counted.get("keymap") or {}
    legacy = int(counted.get("keys") or 0)
    hide_id = None
    try:
        import key_hide
        if key_hide.enabled(cfg):
            hide_id = _FOLD.get(f"{key_hide.vk(cfg):02X}", f"{key_hide.vk(cfg):02X}")
    except Exception:
        hide_id = None
    view = activity.heat_view(cfg)
    opened = activity.heat_open(cfg)
    zones = _live_zones(keymap, hide_id, activity.heat_zones(cfg))
    width = view_width(ui)
    sig = (
        focus.isoformat(),
        bool(enabled),
        legacy,
        hide_id,
        tuple(sorted((str(k), int(v)) for k, v in keymap.items())),
        view,
        width,
        opened,
        tuple(sorted(zones)),
    )
    if ui.get("heat_sig") == sig and (not opened or ui.get("heat_photo") is not None):
        return
    line = brief(keymap, enabled=enabled, legacy=legacy)
    if brief_var is not None:
        brief_var.set(line)
    ui["heat_sig"] = sig
    if not opened or label is None:
        ui["heat_hits"] = []
        ui["heat_summary"] = line
        return
    common = dict(
        enabled=enabled, legacy=legacy, focus=focus, today=today, hide_id=hide_id,
        width=width, zones=zones,
    )
    if view == "rank":
        img, hits, summary = render_rank(keymap, **common)
    else:
        img, hits, summary = render(keymap, **common)
    ui["heat_hits"] = hits
    ui["heat_summary"] = summary
    ui["heat_size"] = img.size
    photo = ImageTk.PhotoImage(img)
    ui["heat_photo"] = photo
    label.configure(image=photo)
    if not ui.get("heat_hover"):
        var = ui.get("heat_var")
        if var is not None:
            var.set(summary)


def hover(ui: dict, x: int, y: int) -> None:
    var = ui.get("heat_var")
    if var is None:
        return
    text = hit_text(ui.get("heat_hits") or [], x, y)
    ui["heat_hover"] = bool(text)
    var.set(text or ui.get("heat_summary") or "")
