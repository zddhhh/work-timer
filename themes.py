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

from PIL import Image, ImageDraw, ImageFont

import ornaments
import store

DEFAULT_THEME_ID = "ghost"
_KINDS = frozenset({"ghost", "glass", "frost", "neon", "terminal", "aurora", "inkgold", "warmglow"})
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
        if th is None or th.id in seen:
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
        return list(_catalog)


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


def load_local_catalog() -> None:
    bundled = _load_json_file(_bundled_path())
    cached = _load_json_file(_cache_path())
    bmap = {t.id: t for t in bundled}
    # 这些皮会随版本改配色/自适应，优先用内置覆盖旧缓存
    prefer_bundled = {"ghost", "auto", "midnight", "frost", "terminal", "aurora", "inkgold", "warmglow"}
    if cached:
        items: list[Theme] = []
        seen: set[str] = set()
        for t in cached:
            if t.id == "blink":
                continue
            if t.id in prefer_bundled and t.id in bmap:
                items.append(bmap[t.id])
            else:
                items.append(t)
            seen.add(t.id)
        for t in bundled:
            if t.id in seen:
                continue
            if t.id == "auto":
                idx = next((i for i, x in enumerate(items) if x.id == "ghost"), -1) + 1
                items.insert(max(0, idx), t)
            else:
                items.append(t)
            seen.add(t.id)
            if len(items) >= 16:
                break
        items = items[:16]
    else:
        items = bundled or _fallback()
    _set_catalog(items, notify=False)


def _fetch_urls(repo: str, token: str) -> list[str]:
    import updater

    owner, name = updater.parse_repo(repo)
    path = f"/repos/{owner}/{name}/raw/themes.json"
    urls = [f"https://api.gitcode.com/api/v5{path}?ref=main"]
    if token:
        q = urllib.parse.urlencode({"access_token": token, "ref": "main"})
        urls.insert(0, f"https://api.gitcode.com/api/v5{path}?{q}")
    return urls


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


def _halo_text(
    d: ImageDraw.ImageDraw,
    xy: tuple[int, int],
    text: str,
    font,
    fill,
    *,
    ghost: bool,
    glow: bool = False,
) -> None:
    x, y = xy
    if glow:
        aura = (fill[0], fill[1], fill[2], max(40, min(120, fill[3] // 2)))
        for dx, dy in ((0, -1), (0, 2), (-1, 0), (1, 0)):
            d.text((x + dx, y + dy), text, font=font, fill=aura)
    if ghost:
        d.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 70))
        d.text((x, y + 1), text, font=font, fill=(0, 0, 0, 40))
    elif _luma(fill) < 140:
        d.text((x + 1, y + 1), text, font=font, fill=(255, 255, 255, 90))
        d.text((x, y + 1), text, font=font, fill=(255, 255, 255, 50))
    else:
        d.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 90))
        d.text((x, y + 1), text, font=font, fill=(0, 0, 0, 55))
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
) -> None:
    d = ImageDraw.Draw(img)
    box = (4, 4, w - 5, h - 5)
    kind = theme.kind
    r = min(theme.radius, max(8, h // 5))
    pad_x = max(10, min(22, w // 12))
    title_y = max(6, h // 10)
    big_y = int(h * (0.42 if sub else 0.38))
    now = time.monotonic()
    pulse = 0.84 + 0.16 * math.sin(now * (1.15 if stage == "done" else (0.85 if stage == "warn" else 0.5)))

    if kind != "ghost":
        light_card = _luma(theme.fill) >= 160
        if ornaments.has_skin(kind):
            # 圆角卡片：托底和贴图用同一半径，四个圆角弧也铺上生图
            if kind in ("aurora", "neon", "terminal"):
                base = (248, 246, 255, 22) if light_card else (12, 14, 24, 16)
            elif kind == "frost":
                base = (248, 250, 252, 40) if light_card else (20, 24, 32, 36)
            elif kind == "inkgold":
                base = (250, 244, 230, 36) if light_card else (16, 12, 10, 28)
            elif kind == "warmglow":
                # 浅底托底加厚，避免暖色纹理被墙纸洗掉
                base = (255, 236, 214, 96) if light_card else (28, 18, 12, 36)
            else:  # glass
                base = (252, 253, 255, 36) if light_card else (14, 16, 22, 28)
            d.rounded_rectangle(box, radius=r, fill=base)
            ornaments.paste_skin(
                img, box, kind, light=light_card, stage=stage, env_rgb=env_rgb, radius=r
            )
            if theme.outline[3] > 8:
                oa = max(8, min(255, int(theme.outline[3] * pulse)))
                d.rounded_rectangle(box, radius=r, outline=(*theme.outline[:3], oa), width=1)
            inset = 2
            ibox = (box[0] + inset, box[1] + inset, box[2] - inset, box[3] - inset)
            rim_a = int((18 if light_card else 22) * pulse)
            if stage == "done":
                rim_a = int(rim_a * 1.35)
            d.rounded_rectangle(
                ibox,
                radius=max(4, r - 2),
                outline=(255, 255, 255, rim_a) if light_card else (255, 248, 236, rim_a),
                width=1,
            )
        else:
            d.rounded_rectangle((8, 10, w - 3, h - 2), radius=r + 1, fill=(0, 0, 0, 40))
            # 按填充明暗铺一层实底，避免半透明把字洗掉；深浅皮各自适配
            if theme.fill[3] < 230:
                if light_card:
                    d.rounded_rectangle(box, radius=r, fill=(252, 253, 255, 235))
                else:
                    d.rounded_rectangle(box, radius=r, fill=(10, 12, 18, 235))
            d.rounded_rectangle(box, radius=r, fill=theme.fill)
            if theme.outline[3] > 8:
                oa = max(8, min(255, int(theme.outline[3] * pulse)))
                d.rounded_rectangle(box, radius=r, outline=(*theme.outline[:3], oa), width=1)

    ghost = kind == "ghost"
    _halo_text(d, (pad_x, title_y), title, font_title, theme.title, ghost=ghost)
    _halo_text(d, (pad_x, big_y), big, font_big, accent, ghost=ghost, glow=stage == "done")
    if sub:
        _halo_text(d, (pad_x, int(h * 0.78)), sub, font_sub, theme.sub, ghost=ghost)


load_local_catalog()
