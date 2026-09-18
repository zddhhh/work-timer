"""日程/备忘的本地图片附件。文件放 Roaming，配置里只记引用。"""
from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from PIL import Image

import store

MAX_IMAGES = 6
MAX_SRC_BYTES = 12 * 1024 * 1024
MAX_SIDE = 1600
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


def normalize(raw: object) -> list[dict]:
    out: list[dict] = []
    if not isinstance(raw, list):
        return out
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            continue
        iid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip() or "图片"
        file_name = str(item.get("file") or "").strip()
        if not iid or iid in seen:
            continue
        if not file_name:
            file_name = f"{iid}.jpg"
        seen.add(iid)
        out.append({"id": iid, "file": file_name, "name": name[:80]})
        if len(out) >= MAX_IMAGES:
            break
    return out


def _safe_id(raw: str) -> str:
    return "".join(c for c in str(raw) if c.isalnum())[:24] or "x"


def owner_dir(kind: str, owner_id: str) -> Path:
    folder = "memo" if kind == "memo" else "schedule"
    d = store.user_data_dir() / "attachments" / f"{folder}_{_safe_id(owner_id)}"
    d.mkdir(parents=True, exist_ok=True)
    return d


def file_path(kind: str, owner_id: str, rec: dict) -> Path:
    name = str(rec.get("file") or f"{rec.get('id')}.jpg")
    name = Path(name).name
    return owner_dir(kind, owner_id) / name


def count(item: dict | None) -> int:
    if not isinstance(item, dict):
        return 0
    return len(normalize(item.get("images")))


def matches(text_parts: list[str], images: object, query: str) -> bool:
    q = (query or "").strip().casefold()
    if not q:
        return True
    hay = " ".join(str(p or "") for p in text_parts)
    for rec in normalize(images):
        hay += " " + str(rec.get("name") or "")
    return q in hay.casefold()


def _display_name(src: Path) -> str:
    name = src.name.strip() or "图片"
    return name[:80]


def import_one(kind: str, owner_id: str, src: str | Path) -> dict | None:
    path = Path(src)
    if not path.is_file():
        return None
    ext = path.suffix.lower()
    if ext not in ALLOWED_EXT:
        return None
    try:
        if path.stat().st_size > MAX_SRC_BYTES:
            return None
    except OSError:
        return None
    iid = uuid.uuid4().hex[:10]
    dest_dir = owner_dir(kind, owner_id)
    try:
        with Image.open(path) as im:
            im.load()
            if getattr(im, "n_frames", 1) > 1:
                im.seek(0)
            has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
            if has_alpha:
                converted = im.convert("RGBA")
                out_name = f"{iid}.png"
                fmt = "PNG"
            else:
                converted = im.convert("RGB")
                out_name = f"{iid}.jpg"
                fmt = "JPEG"
            converted.thumbnail((MAX_SIDE, MAX_SIDE))
            dest = dest_dir / out_name
            try:
                if fmt == "JPEG":
                    converted.save(dest, format="JPEG", quality=85, optimize=True)
                else:
                    converted.save(dest, format="PNG", optimize=True)
            except OSError:
                converted.save(dest, format=fmt)
    except OSError:
        return None
    return {"id": iid, "file": out_name, "name": _display_name(path)}


def delete_one(kind: str, owner_id: str, rec: dict) -> None:
    path = file_path(kind, owner_id, rec)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def remove_owner(kind: str, owner_id: str) -> None:
    d = store.user_data_dir() / "attachments" / (
        f"{'memo' if kind == 'memo' else 'schedule'}_{_safe_id(owner_id)}"
    )
    shutil.rmtree(d, ignore_errors=True)


def commit(
    kind: str,
    owner_id: str,
    *,
    keep: list[dict],
    pending: list[str],
    removed: list[dict],
) -> list[dict]:
    for rec in removed:
        delete_one(kind, owner_id, rec)
    out = normalize(keep)
    for src in pending:
        if len(out) >= MAX_IMAGES:
            break
        rec = import_one(kind, owner_id, src)
        if rec:
            out.append(rec)
    return out[:MAX_IMAGES]


def gc(cfg: dict) -> int:
    """启动时清理孤儿附件：不被任何日程/备忘引用的文件与目录。返回删除的文件数。"""
    root = store.user_data_dir() / "attachments"
    if not root.is_dir():
        return 0
    keep: dict[str, set[str]] = {}
    for kind, key in (("schedule", "schedules"), ("memo", "memos")):
        for item in cfg.get(key) or []:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            folder = f"{kind}_{_safe_id(str(item['id']))}"
            names = keep.setdefault(folder, set())
            for rec in normalize(item.get("images")):
                names.add(Path(str(rec.get("file") or f"{rec.get('id')}.jpg")).name)
    removed = 0
    try:
        children = list(root.iterdir())
    except OSError:
        return 0
    for d in children:
        if not d.is_dir():
            continue
        names = keep.get(d.name)
        if names is None:
            shutil.rmtree(d, ignore_errors=True)
            continue
        try:
            for f in d.iterdir():
                if f.is_file() and f.name not in names:
                    try:
                        f.unlink()
                        removed += 1
                    except OSError:
                        pass
        except OSError:
            pass
    return removed


def open_file(path: Path) -> None:
    try:
        os.startfile(str(path))  # type: ignore[attr-defined]
    except OSError:
        pass
