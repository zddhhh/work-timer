"""计时器皮肤：内置一份，启动后从 GitCode 拉 themes.json，换皮不用发新 exe。"""
from __future__ import annotations

import json
import math
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

import festival
import fx
import ornaments
import store

DEFAULT_THEME_ID = "ghost"


def use_flip_display(kind: str, big: str, cfg: dict | None = None, *, h: int = 92) -> bool:
    """含数字的剩余时间一律翻牌渲染（「点我开始」等纯文案仍走大字）。cfg/h 保留兼容旧调用。"""
    return bool(big) and fx._flip_text_has_digits(big)


INTERACTIVE_SKINS = frozenset({"thunder", "inkpulse", "neonflow"})
_KINDS = frozenset(
    {
        "ghost", "glass", "frost", "neon", "terminal", "aurora", "inkgold", "warmglow",
        "midautumn", "nationalday", "neonflow", "inkpulse", "thunder", "flipclock",
    }
)
# 已下架的皮：即便旧缓存 / 旧在线目录里还有，也不再显示；配置里存着的回落到淡影
_REMOVED_IDS = frozenset({"auto", "sky", "blink", "flysword"})


def normalize_id(theme_id: object) -> str:
    tid = str(theme_id or "").strip()
    if not tid or tid in _REMOVED_IDS:
        return DEFAULT_THEME_ID
    return tid
_updated = False
_lock = threading.Lock()


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    fill: tuple[int, int, int, int]
    outline: tuple[int, int, int, int]
    title: tuple[int, int, int, int]
    big: tuple[int, int, int, int]
    sub: tuple[int, int, int, int]
    idle: tuple[int, int, int, int]
    warn: tuple[int, int, int, int]
    done: tuple[int, int, int, int]
    radius: int
    kind: str
    adaptive: bool = False
    light: Theme | None = None


def _rgba(v, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        return fallback
    try:
        r, g, b, a = (max(0, min(255, int(x))) for x in v)
        return (r, g, b, a)
    except (TypeError, ValueError):
        return fallback


def _luma(c: tuple[int, int, int, int]) -> float:
    r, g, b, _a = c
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


_WALLPAPER_KINDS = frozenset({"midautumn", "nationalday", "thunder", "inkpulse"})
_CARD_LIGHT_LUMA = 152.0


@dataclass(frozen=True)
class SkinAdaptContext:
    """墙纸自适应上下文：区分「墙纸明暗」「特效浅化」「卡片实际底色」。"""

    surface: str
    wallpaper_light: bool
    skin_light: bool
    card_light: bool
    fx_light: bool


def _skin_base_rgba(
    kind: str,
    *,
    wallpaper_light: bool,
    skin_light: bool,
) -> tuple[int, int, int, int] | None:
    if not ornaments.has_skin(kind):
        return None
    if kind == "neon":
        return (236, 252, 250, 170) if skin_light else (6, 10, 16, 72)
    if kind == "terminal":
        return (232, 244, 236, 150) if skin_light else (4, 10, 6, 68)
    if kind == "aurora":
        return (242, 240, 252, 145) if skin_light else (10, 10, 22, 60)
    if kind == "frost":
        return (248, 250, 252, 110) if skin_light else (18, 22, 30, 48)
    if kind == "inkgold":
        return (250, 244, 230, 120) if skin_light else (14, 10, 8, 55)
    if kind == "warmglow":
        return (255, 236, 214, 175) if skin_light else (32, 18, 12, 95)
    if kind == "midautumn":
        return (8, 10, 34, 155) if skin_light else (8, 10, 32, 55)
    if kind == "nationalday":
        return (56, 8, 12, 140) if skin_light else (40, 6, 10, 50)
    if kind == "neonflow":
        return (244, 250, 255, 165) if skin_light else (6, 8, 14, 135)
    if kind == "inkpulse":
        return (252, 246, 232, 232) if wallpaper_light else (250, 242, 222, 214)
    if kind == "flipclock":
        return (24, 26, 32, 200) if skin_light else (16, 18, 24, 178)
    if kind == "thunder":
        return (238, 244, 254, 168) if skin_light else (8, 9, 18, 132)
    if kind == "glass":
        return (252, 253, 255, 95) if skin_light else (12, 14, 20, 42)
    return (252, 253, 255, 95) if skin_light else (12, 14, 20, 42)


def skin_adapt_context(theme: Theme, surface: str) -> SkinAdaptContext:
    """统一计算墙纸自适应：文字对比看 card_light，特效参数看 skin_light / fx_light。"""
    kind = theme.kind
    wallpaper_light = surface == "light"
    if kind in _WALLPAPER_KINDS:
        skin_light = wallpaper_light
    else:
        skin_light = _luma(theme.fill) >= _CARD_LIGHT_LUMA
    base = _skin_base_rgba(kind, wallpaper_light=wallpaper_light, skin_light=skin_light)
    if kind == "inkpulse":
        card_light = True
    elif base is not None:
        card_light = _luma(base) >= _CARD_LIGHT_LUMA
    elif kind == "ghost":
        card_light = wallpaper_light
    else:
        card_light = _luma(theme.fill) >= _CARD_LIGHT_LUMA
    fx_light = wallpaper_light if kind == "inkpulse" else skin_light
    return SkinAdaptContext(
        surface=surface,
        wallpaper_light=wallpaper_light,
        skin_light=skin_light,
        card_light=card_light,
        fx_light=fx_light,
    )


def adapt_text_color(
    color: tuple[int, int, int, int],
    ctx: SkinAdaptContext,
    *,
    kind: str,
    stage: str,
    card_light: bool | None = None,
) -> tuple[int, int, int, int]:
    return fx.contrast_text_color(
        color,
        skin_kind=kind,
        wallpaper_light=ctx.wallpaper_light,
        card_light=card_light if card_light is not None else ctx.card_light,
        stage=stage,
    )


def _parse_theme(raw: object) -> Theme | None:
    if not isinstance(raw, dict):
        return None
    tid = str(raw.get("id") or "").strip()
    name = str(raw.get("name") or "").strip()
    if not tid or not name:
        return None
    kind = str(raw.get("kind") or "glass").strip().lower()
    if kind not in _KINDS:
        kind = "glass"
    try:
        radius = max(4, min(28, int(raw.get("radius") or 18)))
    except (TypeError, ValueError):
        radius = 18
    adaptive = bool(raw.get("adaptive"))
    fill = _rgba(raw.get("fill"), (22, 26, 34, 160))
    outline = _rgba(raw.get("outline"), (255, 255, 255, 40))
    title = _rgba(raw.get("title"), (180, 186, 200, 210))
    big = _rgba(raw.get("big"), (244, 246, 250, 245))
    sub = _rgba(raw.get("sub"), (150, 158, 172, 190))
    idle = _rgba(raw.get("idle"), (140, 190, 255, 240))
    warn = _rgba(raw.get("warn"), (255, 210, 120, 245))
    done = _rgba(raw.get("done"), (120, 214, 168, 245))
    light: Theme | None = None
    on_light = raw.get("on_light")
    if adaptive and isinstance(on_light, dict):
        light = Theme(
            tid,
            name,
            _rgba(on_light.get("fill"), fill),
            _rgba(on_light.get("outline"), outline),
            _rgba(on_light.get("title"), title),
            _rgba(on_light.get("big"), big),
            _rgba(on_light.get("sub"), sub),
            _rgba(on_light.get("idle"), idle),
            _rgba(on_light.get("warn"), warn),
            _rgba(on_light.get("done"), done),
            radius,
            kind,
            True,
            None,
        )
    return Theme(
        tid, name, fill, outline, title, big, sub, idle, warn, done, radius, kind, adaptive, light
    )


def _theme_to_dict(t: Theme) -> dict:
    d = {
        "id": t.id,
        "name": t.name,
        "kind": t.kind,
        "radius": t.radius,
        "adaptive": t.adaptive,
        "fill": list(t.fill),
        "outline": list(t.outline),
        "title": list(t.title),
        "big": list(t.big),
        "sub": list(t.sub),
        "idle": list(t.idle),
        "warn": list(t.warn),
        "done": list(t.done),
    }
    if t.adaptive and t.light is not None:
        d["on_light"] = {
            "fill": list(t.light.fill),
            "outline": list(t.light.outline),
            "title": list(t.light.title),
            "big": list(t.light.big),
            "sub": list(t.light.sub),
            "idle": list(t.light.idle),
            "warn": list(t.light.warn),
            "done": list(t.light.done),
        }
    return d


def resolve_for_surface(theme: Theme, surface: str) -> Theme:
    """adaptive 主题按背后明暗取色；其它主题原样返回。"""
    if not theme.adaptive:
        return theme
    if surface == "light" and theme.light is not None:
        return theme.light
    return replace(theme, light=None)


def _lerp_rgba(
    a: tuple[int, int, int, int], b: tuple[int, int, int, int], t: float
) -> tuple[int, int, int, int]:
    t = max(0.0, min(1.0, float(t)))
    return tuple(int(round(x + (y - x) * t)) for x, y in zip(a, b))  # type: ignore[return-value]


def blend_themes(a: Theme, b: Theme, t: float) -> Theme:
    """在两套配色之间插值，用于自适应缓变。"""
    t = max(0.0, min(1.0, float(t)))
    if t <= 0:
        return replace(a, light=None)
    if t >= 1:
        return replace(b, light=None)
    return Theme(
        b.id,
        b.name,
        _lerp_rgba(a.fill, b.fill, t),
        _lerp_rgba(a.outline, b.outline, t),
        _lerp_rgba(a.title, b.title, t),
        _lerp_rgba(a.big, b.big, t),
        _lerp_rgba(a.sub, b.sub, t),
        _lerp_rgba(a.idle, b.idle, t),
        _lerp_rgba(a.warn, b.warn, t),
        _lerp_rgba(a.done, b.done, t),
        int(round(a.radius + (b.radius - a.radius) * t)),
        b.kind,
        b.adaptive,
        None,
    )


def _parse_catalog(data: object) -> list[Theme]:
    if isinstance(data, dict):
        items = data.get("themes")
    elif isinstance(data, list):
        items = data
    else:
        return []
    if not isinstance(items, list):
        return []
    out: list[Theme] = []
    seen: set[str] = set()
    for item in items:
        th = _parse_theme(item)
        if th is None or th.id in seen or th.id in _REMOVED_IDS:
            continue
        seen.add(th.id)
        out.append(th)
        if len(out) >= 16:
            break
    return out


def _bundled_path() -> Path:
    return store.app_dir() / "themes.json"


def _cache_path() -> Path:
    return store.user_data_dir() / "themes.json"


def _load_json_file(path: Path) -> list[Theme]:
    if not path.exists():
        return []
    try:
        return _parse_catalog(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError):
        return []


def _fallback() -> list[Theme]:
    bundled = _load_json_file(_bundled_path())
    if bundled:
        return bundled
    return [
        Theme(
            "ghost", "淡影",
            (16, 18, 22, 36), (255, 255, 255, 0),
            (220, 224, 230, 120), (236, 238, 242, 200), (200, 204, 210, 100),
            (210, 218, 226, 170), (232, 214, 180, 190), (190, 220, 200, 190),
            16, "ghost",
        )
    ]


_catalog: list[Theme] = _fallback()


def _set_catalog(items: list[Theme], *, notify: bool = True) -> None:
    global _catalog, _updated
    if not items:
        return
    with _lock:
        _catalog = items
        if notify:
            _updated = True


def list_themes() -> list[Theme]:
    with _lock:
        items = list(_catalog)
    ma = festival.midautumn_in_season()
    nd = festival.national_in_season()
    if not ma and not nd:
        return items
    out: list[Theme] = []
    for t in items:
        if ma and t.id == festival.MIDAUTUMN_THEME_ID:
            out.append(replace(t, name="中秋 · 限定"))
        elif nd and t.id == festival.NATIONAL_THEME_ID:
            out.append(replace(t, name="国庆 · 限定"))
        else:
            out.append(t)

    def _rank(t: Theme) -> int:
        if ma and t.id == festival.MIDAUTUMN_THEME_ID:
            return 0
        if nd and t.id == festival.NATIONAL_THEME_ID:
            return 0
        return 1

    out.sort(key=_rank)
    return out


def menu_sections() -> dict[str, list[Theme]]:
    """右键「外观」分三个子菜单：classic（两字名：淡影/玻璃/霓虹…）、
    fancy（四字名：霓虹流光…）、festival（中秋/国庆，在季的带「· 限定」后缀）。"""
    items = list_themes()
    fest_ids = {festival.MIDAUTUMN_THEME_ID, festival.NATIONAL_THEME_ID}
    out: dict[str, list[Theme]] = {"classic": [], "fancy": [], "festival": []}
    for t in items:
        if t.id in fest_ids:
            out["festival"].append(t)
        elif len(t.name.strip()) <= 2:
            out["classic"].append(t)
        else:
            out["fancy"].append(t)
    return out


def theme_map() -> dict[str, Theme]:
    return {t.id: t for t in list_themes()}


def get_theme(theme_id: str) -> Theme:
    mp = theme_map()
    return mp.get(theme_id) or mp.get(DEFAULT_THEME_ID) or _fallback()[0]


def consume_updated() -> bool:
    global _updated
    with _lock:
        flag = _updated
        _updated = False
        return flag


# 这些皮会随版本改配色/自适应，优先用内置覆盖缓存或在线版本
_PREFER_BUNDLED = frozenset(
    {
        "ghost", "midnight", "frost", "neon", "terminal", "aurora", "inkgold", "warmglow",
        "midautumn", "nationalday", "neonflow", "inkpulse", "thunder", "flipclock",
    }
)


def _merge_with_bundled(remote: list[Theme], bundled: list[Theme]) -> list[Theme]:
    """在线/缓存目录 + 内置目录合并：内置皮以内置为准，远端缺的内置皮补回来，上限 16。"""
    if not remote:
        return list(bundled)
    bmap = {t.id: t for t in bundled}
    items: list[Theme] = []
    seen: set[str] = set()
    for t in remote:
        if t.id in _REMOVED_IDS or t.id in seen:
            continue
        items.append(bmap[t.id] if (t.id in _PREFER_BUNDLED and t.id in bmap) else t)
        seen.add(t.id)
    for t in bundled:
        if t.id in seen:
            continue
        if len(items) >= 16:
            break
        items.append(t)
        seen.add(t.id)
    return items[:16]


def load_local_catalog() -> None:
    bundled = _load_json_file(_bundled_path())
    cached = _load_json_file(_cache_path())
    items = _merge_with_bundled(cached, bundled) if cached else (bundled or _fallback())
    _set_catalog(items, notify=False)


def _fetch_urls(repo: str, token: str) -> list[str]:
    import updater

    owner, name = updater.parse_repo(repo)
    path = f"/repos/{owner}/{name}/raw/themes.json"
    # token 走 Authorization 头，不进 URL
    return [f"https://api.gitcode.com/api/v5{path}?ref=main"]


def refresh_from_repo(cfg: dict, *, timeout: float = 4.0) -> bool:
    repo = str(cfg.get("gitcode_repo") or "").strip()
    token = str(cfg.get("gitcode_token") or "").strip()
    if not repo:
        return False
    headers = {"User-Agent": "WorkTimer-themes", "Accept": "application/json,text/plain,*/*"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    try:
        urls = _fetch_urls(repo, token)
    except ValueError:
        return False
    limit = 256 * 1024
    for url in urls:
        try:
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                blob = resp.read(limit + 1)
            if len(blob) > limit:
                continue
            raw = blob.decode("utf-8", errors="replace").lstrip("\ufeff").strip()
            if not raw.startswith("{") and not raw.startswith("["):
                continue
            items = _parse_catalog(json.loads(raw))
            if not items:
                continue
            items = _merge_with_bundled(items, _load_json_file(_bundled_path()))
            _set_catalog(items)
            try:
                _cache_path().write_text(
                    json.dumps({"version": 1, "themes": [_theme_to_dict(t) for t in items]}, ensure_ascii=False, indent=2),
                    encoding="utf-8",
                )
            except OSError:
                pass
            return True
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, OSError, ValueError):
            continue
    return False


def refresh_async(cfg: dict) -> None:
    def _run() -> None:
        try:
            refresh_from_repo(cfg)
        except Exception as e:  # noqa: BLE001
            store.log_exception("theme-refresh", e)

    threading.Thread(target=_run, daemon=True, name="theme-refresh").start()


def _centered_text_x(d: ImageDraw.ImageDraw, text: str, font, width: int) -> int:
    if not text:
        return 0
    tw = d.textlength(text, font=font)
    return max(0, int((width - tw) // 2))


def _halo_text(
    d: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    fill,
    *,
    ghost: bool,
    glow: bool = False,
    compact: bool = False,
) -> None:
    if not text:
        return
    x, y = xy
    # 窗口矮时双层阴影会糊成重影，只画正文
    if compact:
        d.text((x, y), text, font=font, fill=fill)
        return
    if glow:
        aura = (fill[0], fill[1], fill[2], max(40, min(120, fill[3] // 2)))
        for dx, dy in ((0, -1), (0, 2), (-1, 0), (1, 0)):
            d.text((x + dx, y + dy), text, font=font, fill=aura)
    if ghost:
        d.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 70))
        d.text((x, y + 1), text, font=font, fill=(0, 0, 0, 40))
    elif _luma(fill) < 140:
        d.text((x + 1, y + 1), text, font=font, fill=(255, 255, 255, 70))
    else:
        d.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 65))
    d.text((x, y), text, font=font, fill=fill)


def paint_card(
    img: Image.Image,
    w: int,
    h: int,
    theme: Theme,
    title: str,
    big: str,
    sub: str,
    accent: tuple[int, int, int, int],
    font_title: ImageFont.ImageFont,
    font_big: ImageFont.ImageFont,
    font_sub: ImageFont.ImageFont,
    *,
    text_right: int | None = None,
    stage: str = "run",
    env_rgb: tuple[int, int, int] | None = None,
    surface: str = "dark",
    thunder_glyphs: list[tuple[float, int, int, int]] | None = None,
    thunder_quote: str = "",
    neon_ammo=None,
    neon_now: float = 0.0,
    neon_planets=None,
    flip_anims: dict[int, tuple[float, str, str]] | None = None,
    flip_now: float = 0.0,
    flip_hit_rects: list[tuple[int, int, int, int, int]] | None = None,
) -> None:
    d = ImageDraw.Draw(img)
    kind = theme.kind
    compact_chrome = h < 72 or w < 200
    large_chrome = h >= 104 or w >= 320
    if compact_chrome:
        box = (2, 2, w - 3, h - 3)
        r = min(theme.radius, max(4, h // 8))
    elif large_chrome:
        box = (3, 3, w - 4, h - 4)
        r = min(theme.radius, max(10, h // 7))
    else:
        box = (4, 4, w - 5, h - 5)
        r = min(theme.radius, max(8, h // 5))
    pad_x = max(10, min(22, w // 12))
    title_y = max(8, int(h * 0.11))
    big_y = int(h * (0.42 if sub else 0.38))
    title_h = fx._font_line_height(font_title, title or "距")
    now = time.monotonic()
    pulse = 0.84 + 0.16 * math.sin(now * (1.15 if stage == "done" else (0.85 if stage == "warn" else 0.5)))

    ctx = skin_adapt_context(theme, surface)
    title_fill = adapt_text_color(theme.title, ctx, kind=kind, stage=stage)
    sub_fill = adapt_text_color(theme.sub, ctx, kind=kind, stage=stage)
    accent_fill = adapt_text_color(accent, ctx, kind=kind, stage=stage)

    if kind != "ghost":
        base = _skin_base_rgba(
            kind,
            wallpaper_light=ctx.wallpaper_light,
            skin_light=ctx.skin_light,
        )
        if base is not None:
            d.rounded_rectangle(box, radius=r, fill=base)
            ornaments.paste_skin(
                img,
                box,
                kind,
                light=ctx.fx_light,
                stage=stage,
                env_rgb=env_rgb,
                radius=r,
                neon_ammo=neon_ammo if kind == "neonflow" else None,
                neon_now=neon_now,
                neon_planets=neon_planets if kind == "neonflow" else None,
            )
            if theme.outline[3] > 8:
                oa = max(8, min(255, int(theme.outline[3] * pulse)))
                if compact_chrome:
                    oa = min(oa, 10)
                elif large_chrome:
                    oa = min(oa, 14)
                d.rounded_rectangle(box, radius=r, outline=(*theme.outline[:3], oa), width=1)
            if not compact_chrome:
                inset = 2
                ibox = (box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset)
                pale_rim = ctx.card_light and kind not in ("midautumn", "nationalday", "thunder")
                rim_a = int((18 if pale_rim else 22) * pulse)
                if large_chrome:
                    rim_a = int(rim_a * 0.5)
                if stage == "done":
                    rim_a = int(rim_a * 1.35)
                d.rounded_rectangle(
                    ibox,
                    radius=max(4, r - 2),
                    outline=(255, 255, 255, rim_a) if pale_rim else (255, 248, 236, rim_a),
                    width=1,
                )
            if kind == "thunder" and thunder_glyphs:
                for gt, gidx, gx, gy in thunder_glyphs:
                    ornaments.paint_thunder_glyph(
                        img,
                        box,
                        gt,
                        gidx,
                        anchor_x=float(gx),
                        anchor_y=float(gy),
                        stage=stage,
                        light=ctx.wallpaper_light,
                        quote=thunder_quote,
                    )
        else:
            d.rounded_rectangle((8, 10, w - 3, h - 2), radius=r + 1, fill=(0, 0, 0, 40))
            if theme.fill[3] < 230:
                if ctx.card_light:
                    d.rounded_rectangle(box, radius=r, fill=(252, 253, 255, 235))
                else:
                    d.rounded_rectangle(box, radius=r, fill=(10, 12, 18, 235))
            d.rounded_rectangle(box, radius=r, fill=theme.fill)
            if theme.outline[3] > 8:
                oa = max(8, min(255, int(theme.outline[3] * pulse)))
                d.rounded_rectangle(box, radius=r, outline=(*theme.outline[:3], oa), width=1)

    ghost = kind == "ghost"
    compact_text = h < 72
    show_flip = use_flip_display(kind, big, h=h)
    if show_flip:
        title_y, flip_pad, row_y, row_w, row_h = fx.flip_row_layout(
            w, h, title_h=title_h, has_sub=bool(sub),
        )
    title_x = _centered_text_x(d, title, font_title, w)
    _halo_text(
        d, (title_x, title_y), title, font_title, title_fill,
        ghost=ghost, compact=compact_text,
    )
    if show_flip:
        fx.paint_flip_row(
            img,
            flip_pad,
            row_y,
            row_w,
            row_h,
            big,
            flip_anims or {},
            flip_now,
            font_big,
            accent_fill,
            stage=stage,
            light=ctx.card_light,
            hit_rects=flip_hit_rects,
            bare_digits=(kind != "flipclock"),
            skin_kind=kind,
            wallpaper_light=ctx.wallpaper_light,
        )
    elif big:
        _halo_text(
            d, (pad_x, big_y), big, font_big, accent_fill,
            ghost=ghost, glow=(stage == "done" and not compact_text), compact=compact_text,
        )
    if sub:
        _halo_text(
            d, (pad_x, int(h * 0.78)), sub, font_sub, sub_fill,
            ghost=ghost, compact=compact_text,
        )


load_local_catalog()
