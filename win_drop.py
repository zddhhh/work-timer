"""把文件拖进 Tk 窗口：用 tkdnd（C 实现 OLE），不手写 COM。"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Callable

_tkdnd_ok = False


def _ensure_tkdnd(widget) -> bool:
    global _tkdnd_ok
    if _tkdnd_ok:
        return True
    try:
        from tkinterdnd2 import TkinterDnD

        TkinterDnD.require(widget)
        _tkdnd_ok = True
        return True
    except Exception:
        pass
    if getattr(sys, "frozen", False):
        try:
            meipass = Path(getattr(sys, "_MEIPASS", ""))
            for name in ("win-x64", "win-x86", "win-arm64"):
                folder = meipass / "tkinterdnd2" / "tkdnd" / name
                if folder.is_dir():
                    widget.tk.call("lappend", "auto_path", str(folder))
                    widget.tk.call("package", "require", "tkdnd")
                    _tkdnd_ok = True
                    return True
        except Exception:
            return False
    return False


def _parse_files(widget, data: object) -> list[str]:
    raw = "" if data is None else str(data)
    if not raw.strip():
        return []
    try:
        parts = widget.tk.splitlist(raw)
    except Exception:
        parts = (raw,)
    out: list[str] = []
    for item in parts:
        p = str(item).strip()
        if p.startswith("{") and p.endswith("}"):
            p = p[1:-1]
        if p.startswith("file:///"):
            from urllib.parse import unquote

            p = unquote(p[8:]).replace("/", "\\")
            if len(p) >= 3 and p[0] == "\\" and p[2] == ":":
                p = p[1:]
        if p:
            out.append(p)
    return out


def hook_files(widget, on_files: Callable[[list[str]], None]) -> None:
    if not _ensure_tkdnd(widget):
        return
    widget._drop_cb = on_files

    def on_drop(event):
        cb = getattr(widget, "_drop_cb", on_files)
        data = getattr(event, "data", "") or ""
        files = _parse_files(widget, data)
        if files and cb:
            def _apply(fs=files, fn=cb) -> None:
                try:
                    fn(fs)
                except Exception:
                    pass

            try:
                widget.after(0, _apply)
            except Exception:
                _apply()
        return "copy"

    def rec(w) -> None:
        if not getattr(w, "_drop_hooked", False):
            try:
                w.drop_target_register("DND_Files", "CF_HDROP")
                w.dnd_bind("<<Drop>>", on_drop)
                w._drop_hooked = True
            except Exception:
                pass
        try:
            kids = w.winfo_children()
        except Exception:
            return
        for child in kids:
            rec(child)

    rec(widget)
