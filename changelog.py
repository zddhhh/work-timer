"""打包进 exe 的更新说明：按版本切开，给「更新后首次启动」弹窗用。"""
from __future__ import annotations

import re
from pathlib import Path

import store
import updater

_HEADING = re.compile(r"^##\s+(\d+\.\d+\.\d+)\s*$")


def notes_path() -> Path:
    return store.app_dir() / "docs" / "更新说明.md"


def load_markdown() -> str:
    path = notes_path()
    if not path.is_file():
        return ""
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return ""


def parse_notes(text: str) -> list[tuple[str, str]]:
    """`## 1.1.5` 段落；遇到不是版本号的 `##` 就停（后面是发包说明）。"""
    sections: list[tuple[str, str]] = []
    cur = ""
    buf: list[str] = []
    for raw in (text or "").splitlines():
        line = raw.rstrip()
        m = _HEADING.match(line.strip())
        if m:
            if cur:
                body = "\n".join(buf).strip()
                if body:
                    sections.append((cur, body))
            cur = m.group(1)
            buf = []
            continue
        if line.startswith("## ") and cur:
            body = "\n".join(buf).strip()
            if body:
                sections.append((cur, body))
            cur = ""
            buf = []
            continue
        if cur:
            buf.append(line)
    if cur:
        body = "\n".join(buf).strip()
        if body:
            sections.append((cur, body))
    return sections


def notes_after(from_ver: str, to_ver: str, *, text: str | None = None) -> list[tuple[str, str]]:
    """from_ver < 版本 <= to_ver，新的在前。"""
    out: list[tuple[str, str]] = []
    for ver, body in parse_notes(text if text is not None else load_markdown()):
        if updater.is_newer(ver, from_ver) and not updater.is_newer(ver, to_ver):
            out.append((ver, body))
    return out
