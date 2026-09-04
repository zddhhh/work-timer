"""资源管理器拖文件到 Tk：OLE IDropTarget。只挂外壳 HWND，回调不向外抛异常。"""
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
CF_HDROP = 15
DVASPECT_CONTENT = 1
TYMED_HGLOBAL = 1
DROPEFFECT_NONE = 0
DROPEFFECT_COPY = 1

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


class FORMATETC(ctypes.Structure):
    _fields_ = [
        ("cfFormat", ctypes.c_ushort),
        ("ptd", ctypes.c_void_p),
        ("dwAspect", ctypes.c_uint32),
        ("lindex", ctypes.c_int32),
        ("tymed", ctypes.c_uint32),
    ]


class STGMEDIUM(ctypes.Structure):
    _fields_ = [
        ("tymed", ctypes.c_uint32),
        ("hGlobal", ctypes.c_void_p),
        ("pUnkForRelease", ctypes.c_void_p),
    ]


class IDropTargetVtbl(ctypes.Structure):
    pass


class DropTarget(ctypes.Structure):
    _fields_ = [("lpVtbl", ctypes.POINTER(IDropTargetVtbl))]


# x64 上 POINTL(8 字节)按值进寄存器；用 c_int64，不能用 Structure，否则 ctypes 会当成指针，一写 pdwEffect 就崩。
QI_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p, ctypes.POINTER(GUID), ctypes.POINTER(ctypes.c_void_p))
ADDREF_FN = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
RELEASE_FN = ctypes.WINFUNCTYPE(ctypes.c_ulong, ctypes.c_void_p)
ENTER_FN = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64, ctypes.POINTER(ctypes.c_uint32)
)
OVER_FN = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64, ctypes.POINTER(ctypes.c_uint32)
)
LEAVE_FN = ctypes.WINFUNCTYPE(ctypes.c_long, ctypes.c_void_p)
DROP_FN = ctypes.WINFUNCTYPE(
    ctypes.c_long, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int64, ctypes.POINTER(ctypes.c_uint32)
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


def _ensure_ole() -> None:
    global _ole_ready
    if _ole_ready:
        return
    hr = int(ole32.OleInitialize(None))
    if hr in (0, 1):
        _ole_ready = True


def _iid_eq(a: GUID, b: GUID) -> bool:
    return bytes(a) == bytes(b)


def _set_effect(effect, value: int) -> None:
    try:
        if effect:
            effect[0] = value
    except Exception:
        pass


def _hdrop_paths(pdata) -> list[str]:
    try:
        pdata = int(pdata or 0)
        if not pdata:
            return []
        vtbl_ptr = ctypes.cast(pdata, ctypes.POINTER(ctypes.c_void_p)).contents.value
        vtbl = ctypes.cast(vtbl_ptr, ctypes.POINTER(ctypes.c_void_p))
        get_data = GETDATA_FN(vtbl[3])
        fmt = FORMATETC()
        fmt.cfFormat = CF_HDROP
        fmt.ptd = None
        fmt.dwAspect = DVASPECT_CONTENT
        fmt.lindex = -1
        fmt.tymed = TYMED_HGLOBAL
        stg = STGMEDIUM()
        if int(get_data(pdata, ctypes.byref(fmt), ctypes.byref(stg))) != 0:
            return []
        try:
            hdrop = stg.hGlobal
            if not hdrop:
                return []
            n = int(shell32.DragQueryFileW(hdrop, 0xFFFFFFFF, None, 0))
            out: list[str] = []
            buf = ctypes.create_unicode_buffer(1024)
            for i in range(max(0, n)):
                shell32.DragQueryFileW(hdrop, i, buf, 1024)
                if buf.value:
                    out.append(buf.value)
            return out
        finally:
            ole32.ReleaseStgMedium(ctypes.byref(stg))
    except Exception:
        return []


def _shell_hwnd(widget) -> int:
    """只要 Tk 外壳，不要 winfo_id 那个内部窗，OLE 挂内部窗会和 Tk 抢消息然后崩。"""
    try:
        inner = int(widget.winfo_id())
    except Exception:
        return 0
    try:
        parent = int(user32.GetParent(inner) or 0)
        if parent:
            return parent
    except Exception:
        pass
    try:
        frame = widget.wm_frame()
        if frame:
            return int(str(frame), 16)
    except Exception:
        pass
    return inner


def hook_files(widget, on_files: Callable[[list[str]], None]) -> None:
    if getattr(widget, "_drop_hooked", False):
        return
    _ensure_ole()
    if not _ole_ready:
        return
    hwnd = _shell_hwnd(widget)
    if not hwnd:
        return

    state = {"ref": 1, "cb": on_files, "hwnd": hwnd, "widget": widget}

    def QueryInterface(this, riid, ppv):
        try:
            if not ppv:
                return E_POINTER
            iid = riid.contents
            if _iid_eq(iid, IID_IUnknown) or _iid_eq(iid, IID_IDropTarget):
                ppv[0] = this
                state["ref"] += 1
                return S_OK
            ppv[0] = None
            return E_NOINTERFACE
        except Exception:
            return E_NOINTERFACE

    def AddRef(this):
        state["ref"] += 1
        return state["ref"]

    def Release(this):
        state["ref"] = max(0, state["ref"] - 1)
        return state["ref"]

    def DragEnter(this, pdata, _keys, _pt, effect):
        _set_effect(effect, DROPEFFECT_COPY if pdata else DROPEFFECT_NONE)
        return S_OK

    def DragOver(this, _keys, _pt, effect):
        _set_effect(effect, DROPEFFECT_COPY)
        return S_OK

    def DragLeave(this):
        return S_OK

    def Drop(this, pdata, _keys, _pt, effect):
        files: list[str] = []
        try:
            files = _hdrop_paths(pdata)
        except Exception:
            files = []
        _set_effect(effect, DROPEFFECT_COPY if files else DROPEFFECT_NONE)
        if files:
            cb = state["cb"]
            wg = state["widget"]

            def _apply(fs=files) -> None:
                try:
                    cb(fs)
                except Exception:
                    pass

            try:
                wg.after(0, _apply)
            except Exception:
                _apply()
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
    hr = int(ole32.RegisterDragDrop(hwnd, this_ptr))
    if hr != 0:
        return

    widget._drop_hooked = True
    widget._drop_vtbl = vtbl
    widget._drop_obj = obj
    widget._drop_this = this_ptr
    widget._drop_fns = (QueryInterface, AddRef, Release, DragEnter, DragOver, DragLeave, Drop)

    def _revoke(_e=None) -> None:
        try:
            ole32.RevokeDragDrop(state["hwnd"])
        except Exception:
            pass
        state["hwnd"] = 0

    widget.bind("<Destroy>", _revoke, add="+")
