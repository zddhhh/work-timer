"""打包进 exe 的更新说明：按版本切开，给「更新后首次启动」弹窗用。"""
from __future__ import annotations

import re
from pathlib import Path

import store
import updater

_HEADING = re.compile(r"^##\s+(\d+\.\d+\.\d+)\s*$")
# 老格式 `sha256: <hex>`，以及按安装包写的 `sha256(WorkTimer-Setup.exe): <hex>`
_NOISE = re.compile(
    r"^\s*(?:sha256|md5|sha1)(?:\s*\([^)]*\))?\s*[:：]",
    re.IGNORECASE,
)


def highlights(body: str, *, limit: int = 4) -> list[str]:
    """Release 正文 → 给人看的几条（不带 - 之类的行首标记）。

    本地 md 里没有「将要下载的那一版」的说明，只能用线上 Release 的正文，
    所以得把版本号标题和 sha256 校验行滤掉。标记也一并去掉：Tk 换行会把
    「- 一长串中文」的短横甩到单独一行。"""
    out: list[str] = []
    for raw in (body or "").splitlines():
        line = raw.strip()
        if not line or _NOISE.match(line):
            continue
        if _HEADING.match(line) or line.startswith("#"):
            continue
        if re.match(r"^worktimer\s+v?\d", line, re.IGNORECASE):
            continue
        line = line.lstrip("-*•·").strip()
        if line:
            out.append(line)
        if len(out) >= limit:
            break
    return out


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
            # 弹窗是纯 Label，没法渲染强调；** 原样露出来只会碍眼
            buf.append(line.replace("**", ""))
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
