"""把文件拖进 Tk 窗口：Windows WM_DROPFILES，不额外依赖。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

user32 = ctypes.windll.user32
shell32 = ctypes.windll.shell32

WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t
WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM)

GWLP_WNDPROC = -4
WM_DROPFILES = 0x0233
WM_NCDESTROY = 0x0082

shell32.DragAcceptFiles.argtypes = [wintypes.HWND, wintypes.BOOL]
shell32.DragAcceptFiles.restype = None
shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
shell32.DragQueryFileW.restype = wintypes.UINT
shell32.DragFinish.argtypes = [wintypes.HANDLE]
shell32.DragFinish.restype = None
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_void_p]
user32.SetWindowLongPtrW.restype = ctypes.c_void_p
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_void_p
user32.CallWindowProcW.argtypes = [ctypes.c_void_p, wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM]
user32.CallWindowProcW.restype = LRESULT


def _hwnd_of(widget) -> int:
    try:
        frame = widget.wm_frame()
        if frame:
            return int(str(frame), 16)
    except Exception:
        pass
    return int(widget.winfo_id())


def _read_drop(hdrop) -> list[str]:
    n = int(shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0))
    out: list[str] = []
    buf = ctypes.create_unicode_buffer(1024)
    for i in range(n):
        shell32.DragQueryFileW(hdrop, i, buf, 1024)
        if buf.value:
            out.append(buf.value)
    shell32.DragFinish(hdrop)
    return out


def hook_files(widget, on_files: Callable[[list[str]], None]) -> None:
    """对已创建的 Toplevel 打开文件拖放。同一窗口只钩一次。"""
    if getattr(widget, "_drop_hooked", False):
        return
    hwnds: list[int] = []
    try:
        hwnds.append(_hwnd_of(widget))
    except Exception:
        pass
    try:
        hwnds.append(int(widget.winfo_id()))
    except Exception:
        pass
    seen: set[int] = set()
    hwnds = [h for h in hwnds if h and h not in seen and not seen.add(h)]
    if not hwnds:
        return
    hwnd = hwnds[0]
    for h in hwnds:
        shell32.DragAcceptFiles(h, True)
    old = user32.GetWindowLongPtrW(hwnd, GWLP_WNDPROC)
    state = {"old": old, "proc": None}

    def wndproc(h, msg, wp, lp):
        if msg == WM_DROPFILES:
            files = _read_drop(wp)
            try:
                widget.after(0, lambda fs=files: on_files(fs))
            except Exception:
                on_files(files)
            return 0
        if msg == WM_NCDESTROY:
            if state["old"]:
                user32.SetWindowLongPtrW(h, GWLP_WNDPROC, state["old"])
        return user32.CallWindowProcW(state["old"], h, msg, wp, lp)

    proc = WNDPROC(wndproc)
    state["proc"] = proc
    user32.SetWindowLongPtrW(hwnd, GWLP_WNDPROC, ctypes.cast(proc, ctypes.c_void_p).value)
    shell32.DragAcceptFiles(hwnd, True)
    widget._drop_hooked = True
    widget._drop_proc = proc
    widget._drop_hwnd = hwnd
