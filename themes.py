"""计时器皮肤：内置一份，启动后从 GitCode 拉 themes.json，换皮不用发新 exe。"""
from __future__ import annotations

import json
import threading
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from PIL import ImageDraw, ImageFont

import store

DEFAULT_THEME_ID = "ghost"
_KINDS = frozenset({"ghost", "glass", "frost", "neon", "terminal"})
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


def _rgba(v, fallback: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
    if not isinstance(v, (list, tuple)) or len(v) != 4:
        return fallback
    try:
        r, g, b, a = (max(0, min(255, int(x))) for x in v)
        return (r, g, b, a)
    except (TypeError, ValueError):
        return fallback


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
    return Theme(
        tid,
        name,
        _rgba(raw.get("fill"), (22, 26, 34, 160)),
        _rgba(raw.get("outline"), (255, 255, 255, 40)),
        _rgba(raw.get("title"), (180, 186, 200, 210)),
        _rgba(raw.get("big"), (244, 246, 250, 245)),
        _rgba(raw.get("sub"), (150, 158, 172, 190)),
        _rgba(raw.get("idle"), (140, 190, 255, 240)),
        _rgba(raw.get("warn"), (255, 210, 120, 245)),
        _rgba(raw.get("done"), (120, 214, 168, 245)),
        radius,
        kind,
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
    cached = _load_json_file(_cache_path())
    if cached:
        _set_catalog(cached, notify=False)
        return
    bundled = _load_json_file(_bundled_path())
    if bundled:
        _set_catalog(bundled, notify=False)


def _fetch_urls(repo: str, token: str) -> list[str]:
    import updater

    owner, name = updater.parse_repo(repo)
    # 网页 raw 地址会返回 HTML，不能当 JSON 读。只走 GitCode API。
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
                _cache_path().write_text(json.dumps({"version": 1, "themes": [
                    {
                        "id": t.id, "name": t.name, "kind": t.kind, "radius": t.radius,
                        "fill": list(t.fill), "outline": list(t.outline),
                        "title": list(t.title), "big": list(t.big), "sub": list(t.sub),
                        "idle": list(t.idle), "warn": list(t.warn), "done": list(t.done),
                    }
                    for t in items
                ]}, ensure_ascii=False, indent=2), encoding="utf-8")
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


def _halo_text(d: ImageDraw.ImageDraw, xy: tuple[int, int], text: str, font, fill, *, ghost: bool) -> None:
    x, y = xy
    if ghost:
        d.text((x + 1, y + 1), text, font=font, fill=(0, 0, 0, 70))
        d.text((x, y + 1), text, font=font, fill=(0, 0, 0, 40))
    else:
        d.text((x, y + 1), text, font=font, fill=(0, 0, 0, 50))
    d.text((x, y), text, font=font, fill=fill)


def paint_card(
    d: ImageDraw.ImageDraw,
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
) -> None:
    box = (6, 6, w - 7, h - 7)
    kind = theme.kind
    r = theme.radius

    if kind != "ghost":
        d.rounded_rectangle((10, 12, w - 4, h - 3), radius=r + 1, fill=(0, 0, 0, 50))
        d.rounded_rectangle(box, radius=r, fill=theme.fill)
        if theme.outline[3] > 8:
            d.rounded_rectangle(box, radius=r, outline=theme.outline, width=1)
        if kind == "glass":
            d.rounded_rectangle((10, 9, w - 11, 38), radius=max(8, r - 6), fill=(255, 255, 255, 26))
        elif kind == "frost":
            d.rounded_rectangle((10, 9, w - 11, 36), radius=max(8, r - 6), fill=(255, 255, 255, 88))
        elif kind == "neon":
            d.rounded_rectangle((9, 16, 13, h - 16), radius=2, fill=(0, 230, 210, 190))
        elif kind == "terminal":
            d.rectangle((8, 8, w - 9, 10), fill=(70, 180, 100, 150))
            for y in range(16, h - 10, 5):
                d.line((10, y, w - 11, y), fill=(0, 40, 16, 26))

    ghost = kind == "ghost"
    big_y = 42 if sub else 40
    _halo_text(d, (22, 12), title, font_title, theme.title, ghost=ghost)
    _halo_text(d, (22, big_y), big, font_big, accent, ghost=ghost)
    if sub:
        _halo_text(d, (22, 90), sub, font_sub, theme.sub, ghost=ghost)
    if ghost:
        try:
            bb = d.textbbox((22, big_y), big, font=font_big)
            yline = min(int(bb[3]) + 5, h - 22)
            x2 = min(max(int(bb[2]), 102), w - 28)
            d.line((22, yline, x2, yline), fill=(255, 255, 255, 42), width=1)
        except Exception:
            pass


load_local_catalog()
