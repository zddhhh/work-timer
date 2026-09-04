"""备忘录：多条本地笔记，按更新时间排序。"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

import attachments


def ensure_fields(cfg: dict) -> None:
    raw = cfg.get("memos")
    if not isinstance(raw, list):
        cfg["memos"] = []
        return
    cleaned: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict) or not item.get("id"):
            continue
        title = str(item.get("title") or "").strip()
        body = str(item.get("body") or "").strip()
        updated = str(item.get("updated_at") or "")
        if not updated:
            updated = datetime.now().isoformat(timespec="seconds")
        cleaned.append(
            {
                "id": str(item["id"]),
                "title": title,
                "body": body,
                "updated_at": updated,
                "images": attachments.normalize(item.get("images")),
            }
        )
    cfg["memos"] = cleaned


def new_memo(*, title: str = "", body: str = "", now: datetime | None = None) -> dict[str, Any]:
    now = now or datetime.now()
    return {
        "id": uuid.uuid4().hex[:12],
        "title": (title or "").strip(),
        "body": (body or "").strip(),
        "updated_at": now.isoformat(timespec="seconds"),
        "images": [],
    }


def add_memo(cfg: dict, item: dict) -> None:
    ensure_fields(cfg)
    cfg["memos"].append(item)


def find_memo(cfg: dict, mid: str) -> dict | None:
    ensure_fields(cfg)
    for item in cfg["memos"]:
        if str(item.get("id")) == mid:
            return item
    return None


def update_memo(
    cfg: dict,
    mid: str,
    *,
    title: str,
    body: str,
    images: list[dict] | None = None,
    now: datetime | None = None,
) -> bool:
    item = find_memo(cfg, mid)
    if item is None:
        return False
    now = now or datetime.now()
    item["title"] = (title or "").strip()
    item["body"] = (body or "").strip()
    item["updated_at"] = now.isoformat(timespec="seconds")
    if images is not None:
        item["images"] = attachments.normalize(images)
    return True


def remove_memo(cfg: dict, mid: str) -> None:
    ensure_fields(cfg)
    attachments.remove_owner("memo", mid)
    cfg["memos"] = [m for m in cfg["memos"] if str(m.get("id")) != mid]


def list_sorted(cfg: dict) -> list[dict]:
    ensure_fields(cfg)
    return sorted(
        cfg["memos"],
        key=lambda m: str(m.get("updated_at") or ""),
        reverse=True,
    )


def display_title(item: dict) -> str:
    title = str(item.get("title") or "").strip()
    if title:
        return title
    body = str(item.get("body") or "").strip().replace("\n", " ")
    if body:
        return body[:24] + ("…" if len(body) > 24 else "")
    if attachments.count(item):
        return "图片备忘"
    return "空白备忘"


def matches(item: dict, query: str) -> bool:
    return attachments.matches(
        [str(item.get("title") or ""), str(item.get("body") or "")],
        item.get("images"),
        query,
    )


def format_updated(item: dict) -> str:
    raw = str(item.get("updated_at") or "")
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw)
        return dt.strftime("%m-%d %H:%M")
    except ValueError:
        return raw[:16]
