"""资源管理器拖文件：注册 OLE IDropTarget（WM_DROPFILES 接不到现代拖放）。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

user32 = ctypes.windll.user32
ole32 = ctypes.windll.ole32
shell32 = ctypes.windll.shell32

S_OK = 0
E_NOINTERFACE = 0x80004002
E_POINTER = 0x80004003
E_UNEXPECTED = 0x8000FFFF
CF_HDROP = 15
DVASPECT_CONTENT = 1
TYMED_HGLOBAL = 1
DROPEFFECT_NONE = 0
DROPEFFECT_COPY = 1
GA_ROOT = 2

ole32.OleInitialize.argtypes = [ctypes.c_void_p]
ole32.OleInitialize.restype = ctypes.c_long
ole32.RegisterDragDrop.argtypes = [wintypes.HWND, ctypes.c_void_p]
ole32.RegisterDragDrop.restype = ctypes.c_long
ole32.RevokeDragDrop.argtypes = [wintypes.HWND]
ole32.RevokeDragDrop.restype = ctypes.c_long
ole32.ReleaseStgMedium.argtypes = [ctypes.c_void_p]
ole32.ReleaseStgMedium.restype = None
user32.GetParent.argtypes = [wintypes.HWND]
user32.GetParent.restype = wintypes.HWND
user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
user32.GetAncestor.restype = wintypes.HWND
shell32.DragQueryFileW.argtypes = [wintypes.HANDLE, wintypes.UINT, wintypes.LPWSTR, wintypes.UINT]
shell32.DragQueryFileW.restype = wintypes.UINT

_ole_ready = False


class GUID(ctypes.Structure):
    _fields_ = [
        ("Data1", ctypes.c_uint32),
        ("Data2", ctypes.c_uint16),
        ("Data3", ctypes.c_uint16),
        ("Data4", ctypes.c_ubyte * 8),
    ]


IID_IUnknown = GUID(0x00000000, 0x0000, 0x0000, (0xC0, 0, 0, 0, 0, 0, 0, 0x46))
IID_IDropTarget = GUID(0x00000122, 0x0000, 0x0000, (0xC0, 0, 0, 0, 0, 0, 0, 0x46))


class POINTL(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]


class FORMATETC(ctypes.Structure):
    _fields_ = [
        ("cfFormat", wintypes.WORD),
        ("ptd", ctypes.c_void_p),
        ("dwAspect", wintypes.DWORD),
        ("lindex", ctypes.c_long),
        ("tymed", wintypes.DWORD),
    ]


class STGMEDIUM(ctypes.Structure):
    _fields_ = [
        ("tymed", wintypes.DWORD),
        ("hGlobal", ctypes.c_void_p),
        ("pUnkForRelease", ctypes.c_void_p),
    ]


class IDropTargetVtbl(ctypes.Structure):
    pass


class DropTarget(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(IDropTargetVtbl))]


QI_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
ADDREF_FN = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
RELEASE_FN = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
ENTER_FN = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, POINTL, ctypes.POINTER(wintypes.DWORD)
)
OVER_FN = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_void_p, wintypes.DWORD, POINTL, ctypes.POINTER(wintypes.DWORD)
)
LEAVE_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)
DROP_FN = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, POINTL, ctypes.POINTER(wintypes.DWORD)
)
GETDATA_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(FORMATETC), ctypes.POINTER(STGMEDIUM))

IDropTargetVtbl._fields_ = [
    ("QueryInterface", QI_FN),
    ("AddRef", ADDREF_FN),
    ("Release", RELEASE_FN),
    ("DragEnter", ENTER_FN),
    ("DragOver", OVER_FN),
    ("DragLeave", LEAVE_FN),
    ("Drop", DROP_FN),
]

_by_this: dict[int, dict] = {}


def _ensure_ole() -> None:
    global _ole_ready
    if _ole_ready:
        return
    hr = int(ole32.OleInitialize(None))
    # 0 S_OK, 1 S_FALSE 已初始化
    if hr in (0, 1):
        _ole_ready = True


def _iid_eq(a: GUID, b: GUID) -> bool:
    return bytes(a) == bytes(b)


def _hdrop_paths(pdata: int) -> list[str]:
    if not pdata:
        return []
    vtbl_ptr = ctypes.cast(pdata, ctypes.POINTER(ctypes.c_void_p)).contents.value
    vtbl = ctypes.cast(vtbl_ptr, ctypes.POINTER(ctypes.c_void_p))
    get_data = GETDATA_FN(vtbl[3])
    fmt = FORMATETC(CF_HDROP, None, DVASPECT_CONTENT, -1, TYMED_HGLOBAL)
    stg = STGMEDIUM()
    if int(get_data(pdata, ctypes.byref(fmt), ctypes.byref(stg))) != 0 or not stg.hGlobal:
        return []
    hdrop = stg.hGlobal
    n = int(shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0))
    out: list[str] = []
    buf = ctypes.create_unicode_buffer(1024)
    for i in range(n):
        shell32.DragQueryFileW(hdrop, i, buf, 1024)
        if buf.value:
            out.append(buf.value)
    ole32.ReleaseStgMedium(ctypes.byref(stg))
    return out


def _hwnds_of(widget) -> list[int]:
    found: list[int] = []
    try:
        inner = int(widget.winfo_id())
        found.append(inner)
        parent = int(user32.GetParent(inner) or 0)
        if parent:
            found.append(parent)
        root = int(user32.GetAncestor(inner, GA_ROOT) or 0)
        if root:
            found.append(root)
    except Exception:
        pass
    try:
        frame = widget.wm_frame()
        if frame:
            found.append(int(str(frame), 16))
    except Exception:
        pass
    out: list[int] = []
    seen: set[int] = set()
    for h in found:
        if h and h not in seen:
            seen.add(h)
            out.append(h)
    return out


def hook_files(widget, on_files: Callable[[list[str]], None]) -> None:
    if getattr(widget, "_drop_hooked", False):
        return
    _ensure_ole()
    if not _ole_ready:
        return
    hwnds = _hwnds_of(widget)
    if not hwnds:
        return

    state = {"ref": 1, "cb": on_files, "hwnds": [], "widget": widget}

    def QueryInterface(this, riid, ppv):
        if not ppv:
            return E_POINTER
        iid = riid.contents
        if _iid_eq(iid, IID_IUnknown) or _iid_eq(iid, IID_IDropTarget):
            ppv[0] = this
            state["ref"] += 1
            return S_OK
        ppv[0] = None
        return E_NOINTERFACE

    def AddRef(this):
        state["ref"] += 1
        return state["ref"]

    def Release(this):
        state["ref"] = max(0, state["ref"] - 1)
        return state["ref"]

    def DragEnter(this, pdata, _keys, _pt, effect):
        if effect:
            effect[0] = DROPEFFECT_COPY if pdata else DROPEFFECT_NONE
        return S_OK

    def DragOver(this, _keys, _pt, effect):
        if effect:
            effect[0] = DROPEFFECT_COPY
        return S_OK

    def DragLeave(this):
        return S_OK

    def Drop(this, pdata, _keys, _pt, effect):
        files = _hdrop_paths(int(pdata or 0))
        if effect:
            effect[0] = DROPEFFECT_COPY if files else DROPEFFECT_NONE
        if files:
            cb = state["cb"]
            wg = state["widget"]
            try:
                wg.after(0, lambda fs=files: cb(fs))
            except Exception:
                cb(files)
        return S_OK

    vtbl = IDropTargetVtbl(
        QI_FN(QueryInterface),
        ADDREF_FN(AddRef),
        RELEASE_FN(Release),
        ENTER_FN(DragEnter),
        OVER_FN(DragOver),
        LEAVE_FN(DragLeave),
        DROP_FN(Drop),
    )
    obj = DropTarget(ctypes.pointer(vtbl))
    this_ptr = ctypes.cast(ctypes.pointer(obj), ctypes.c_void_p)
    _by_this[this_ptr.value or 0] = state

    hooked: list[int] = []
    for hwnd in hwnds:
        hr = int(ole32.RegisterDragDrop(hwnd, this_ptr))
        if hr == 0:
            hooked.append(hwnd)
    if not hooked:
        return

    state["hwnds"] = hooked
    widget._drop_hooked = True
    widget._drop_vtbl = vtbl
    widget._drop_obj = obj
    widget._drop_this = this_ptr
    widget._drop_fns = (QueryInterface, AddRef, Release, DragEnter, DragOver, DragLeave, Drop)

    def _revoke(_e=None) -> None:
        for hwnd in list(state["hwnds"]):
            try:
                ole32.RevokeDragDrop(hwnd)
            except Exception:
                pass
        state["hwnds"] = []

    widget.bind("<Destroy>", _revoke, add="+")
