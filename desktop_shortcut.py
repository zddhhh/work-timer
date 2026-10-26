"""桌面与开始菜单快捷方式：无安装向导，首次落到本机时各建一次。不走 PowerShell。"""
from __future__ import annotations

import ctypes
import sys
from ctypes import POINTER, WINFUNCTYPE, byref, c_void_p, c_wchar_p
from ctypes.wintypes import BOOL, DWORD, LPCWSTR, WORD
from pathlib import Path

_LNK_NAME = "下班倒计时.lnk"
_ICON_STAMP = "hourglass-1"
_CSIDL_DESKTOPDIRECTORY = 0x0010
_CSIDL_PROGRAMS = 0x0002  # 当前用户「开始菜单 → 程序」，Win 搜索会索引这里
_CLSCTX_INPROC_SERVER = 1
_COINIT_APARTMENTTHREADED = 0x2
_CLSID_SHELL_LINK = "{00021401-0000-0000-C000-000000000046}"
_IID_ISHELL_LINK_W = "{000214F9-0000-0000-C000-000000000046}"
_IID_IPERSIST_FILE = "{0000010b-0000-0000-C000-000000000046}"

ole32 = ctypes.WinDLL("ole32")


class _GUID(ctypes.Structure):
    _fields_ = (
        ("Data1", DWORD),
        ("Data2", WORD),
        ("Data3", WORD),
        ("Data4", ctypes.c_ubyte * 8),
    )


ole32.CLSIDFromString.argtypes = [LPCWSTR, POINTER(_GUID)]
ole32.CLSIDFromString.restype = ctypes.HRESULT
ole32.CoInitializeEx.argtypes = [c_void_p, DWORD]
ole32.CoInitializeEx.restype = ctypes.HRESULT
ole32.CoCreateInstance.argtypes = [
    POINTER(_GUID),
    c_void_p,
    DWORD,
    POINTER(_GUID),
    POINTER(c_void_p),
]
ole32.CoCreateInstance.restype = ctypes.HRESULT


def _guid(text: str) -> _GUID:
    g = _GUID()
    if ole32.CLSIDFromString(c_wchar_p(text), byref(g)):
        raise OSError("bad guid")
    return g


def _vtbl(punk: int):
    obj = ctypes.cast(c_void_p(punk), POINTER(c_void_p))
    return ctypes.cast(obj.contents, POINTER(c_void_p))


def _release(punk: int) -> None:
    fn = WINFUNCTYPE(ctypes.c_ulong, c_void_p)(_vtbl(punk)[2])
    fn(punk)


def _query_interface(punk: int, iid: str) -> int:
    out = c_void_p()
    g = _guid(iid)
    fn = WINFUNCTYPE(ctypes.HRESULT, c_void_p, POINTER(_GUID), POINTER(c_void_p))(_vtbl(punk)[0])
    hr = fn(punk, byref(g), byref(out))
    if hr or not out.value:
        return 0
    return int(out.value)


_com_ready = False


def _ensure_com() -> None:
    global _com_ready
    if _com_ready:
        return
    hr = ole32.CoInitializeEx(None, _COINIT_APARTMENTTHREADED)
    # S_OK / S_FALSE / RPC_E_CHANGED_MODE 都继续试
    if hr not in (0, 1) and (hr & 0xFFFFFFFF) != 0x80010106:
        pass
    _com_ready = True


def _create_shell_link() -> int:
    _ensure_com()
    punk = c_void_p()
    clsid = _guid(_CLSID_SHELL_LINK)
    iid = _guid(_IID_ISHELL_LINK_W)
    hr = ole32.CoCreateInstance(
        byref(clsid), None, _CLSCTX_INPROC_SERVER, byref(iid), byref(punk)
    )
    if hr or not punk.value:
        raise OSError(f"CoCreateInstance {hr}")
    return int(punk.value)


def _shell_folder(csidl: int, fallback: Path) -> Path | None:
    buf = ctypes.create_unicode_buffer(260)
    try:
        hr = ctypes.windll.shell32.SHGetFolderPathW(None, csidl, None, 0, buf)
    except OSError:
        hr = -1
    if hr == 0 and buf.value:
        p = Path(buf.value)
        if p.is_dir():
            return p
    return fallback if fallback.is_dir() else None


def _desktop_dir() -> Path | None:
    return _shell_folder(_CSIDL_DESKTOPDIRECTORY, Path.home() / "Desktop")


def _start_menu_programs_dir() -> Path | None:
    return _shell_folder(
        _CSIDL_PROGRAMS,
        Path.home() / "AppData" / "Roaming" / "Microsoft" / "Windows" / "Start Menu" / "Programs",
    )


def installed_exe(exe: Path | None = None) -> Path | None:
    """快捷方式和开机启动指向启动器。真正的程序在旁边的 WorkTimer.bin.exe。"""
    if exe is None:
        if not getattr(sys, "frozen", False):
            return None
        try:
            exe = Path(sys.executable).resolve()
        except OSError:
            return None
    if exe.name.lower() == "worktimer.bin.exe":
        launcher = exe.with_name("WorkTimer.exe")
        if launcher.is_file():
            return launcher
    return exe


def _current_exe() -> Path | None:
    if not getattr(sys, "frozen", False):
        return None
    return installed_exe()


def _load_shell_link(lnk: Path) -> tuple[int, int] | None:
    """返回 (IShellLink, IPersistFile)，失败时 None。"""
    if not lnk.exists():
        return None
    try:
        sl = _create_shell_link()
    except OSError:
        return None
    persist = 0
    try:
        persist = _query_interface(sl, _IID_IPERSIST_FILE)
        if not persist:
            _release(sl)
            return None
        load = WINFUNCTYPE(ctypes.HRESULT, c_void_p, LPCWSTR, DWORD)(_vtbl(persist)[5])
        if load(persist, str(lnk), 0):
            _release(persist)
            _release(sl)
            return None
        return sl, persist
    except OSError:
        if persist:
            _release(persist)
        _release(sl)
        return None


def _release_shell_link(sl: int, persist: int) -> None:
    if persist:
        _release(persist)
    _release(sl)


def _read_target(lnk: Path) -> str:
    loaded = _load_shell_link(lnk)
    if not loaded:
        return ""
    sl, persist = loaded
    try:
        get_path = WINFUNCTYPE(
            ctypes.HRESULT, c_void_p, ctypes.c_wchar_p, ctypes.c_int, c_void_p, DWORD
        )(_vtbl(sl)[3])
        buf = ctypes.create_unicode_buffer(32768)
        if get_path(sl, buf, 32768, None, 0):
            return ""
        return buf.value
    except OSError:
        return ""
    finally:
        _release_shell_link(sl, persist)


def _read_icon(lnk: Path) -> tuple[str, int]:
    loaded = _load_shell_link(lnk)
    if not loaded:
        return "", 0
    sl, persist = loaded
    try:
        get_icon = WINFUNCTYPE(
            ctypes.HRESULT,
            c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_int,
            ctypes.POINTER(ctypes.c_int),
        )(_vtbl(sl)[16])
        buf = ctypes.create_unicode_buffer(32768)
        idx = ctypes.c_int()
        if get_icon(sl, buf, 32768, byref(idx)):
            return "", 0
        return buf.value, int(idx.value)
    except OSError:
        return "", 0
    finally:
        _release_shell_link(sl, persist)


def _path_same(path: str, exe: Path) -> bool:
    if not path:
        return False
    try:
        return Path(path).resolve() == exe.resolve()
    except OSError:
        return False


def _shortcut_matches_exe(lnk: Path, exe: Path) -> bool:
    """目标与图标来源都应指向当前 exe（剪切后 Windows 常只更新目标，图标仍留在旧路径）。"""
    if not _path_same(_read_target(lnk), exe):
        return False
    icon_path, _ = _read_icon(lnk)
    return _path_same(icon_path, exe)


def _write_shortcut(lnk: Path, exe: Path, *, arguments: str = "") -> bool:
    try:
        sl = _create_shell_link()
    except OSError:
        return False
    persist = 0
    try:
        v = _vtbl(sl)
        set_path = WINFUNCTYPE(ctypes.HRESULT, c_void_p, LPCWSTR)(v[20])
        set_dir = WINFUNCTYPE(ctypes.HRESULT, c_void_p, LPCWSTR)(v[9])
        set_desc = WINFUNCTYPE(ctypes.HRESULT, c_void_p, LPCWSTR)(v[7])
        set_icon = WINFUNCTYPE(ctypes.HRESULT, c_void_p, LPCWSTR, ctypes.c_int)(v[17])
        set_args = WINFUNCTYPE(ctypes.HRESULT, c_void_p, LPCWSTR)(v[11])
        if set_path(sl, str(exe)):
            return False
        if set_dir(sl, str(exe.parent)):
            return False
        if arguments and set_args(sl, arguments):
            return False
        set_desc(sl, "弹性下班计时器")
        set_icon(sl, str(exe), 0)
        persist = _query_interface(sl, _IID_IPERSIST_FILE)
        if not persist:
            return False
        save = WINFUNCTYPE(ctypes.HRESULT, c_void_p, LPCWSTR, BOOL)(_vtbl(persist)[6])
        if save(persist, str(lnk), True):
            return False
        return lnk.exists()
    except OSError:
        return False
    finally:
        if persist:
            _release(persist)
        _release(sl)


def _notify_shell(lnk: Path | None = None) -> None:
    """刷新单个 lnk 及其目录，勿用 SHCNE_ASSOCCHANGED（会令整桌图标缓存失效、先闪白再恢复）。"""
    try:
        shell32 = ctypes.windll.shell32
        shcne_updateitem = 0x00002000
        shcne_updatedir = 0x00001000
        shcnf_path = 0x0001
        shcnf_flushnowait = 0x3000
        if lnk is not None and lnk.exists():
            shell32.SHChangeNotify(
                shcne_updateitem, shcnf_path | shcnf_flushnowait, str(lnk), None
            )
            parent = lnk.parent
            if parent.is_dir():
                shell32.SHChangeNotify(
                    shcne_updatedir, shcnf_path | shcnf_flushnowait, str(parent), None
                )
    except OSError:
        pass


def _ensure_link(
    cfg: dict,
    lnk: Path,
    *,
    done_key: str,
    icon_key: str,
    exe: Path,
) -> bool:
    """首次建 lnk；用户删掉后不再建；目标或图标变了则更新现有 lnk。"""
    already = bool(cfg.get(done_key))
    if already and not lnk.exists():
        return False
    icon_stale = str(cfg.get(icon_key) or "") != _ICON_STAMP
    if lnk.exists():
        if _shortcut_matches_exe(lnk, exe) and not icon_stale:
            if not already:
                cfg[done_key] = True
                cfg[icon_key] = _ICON_STAMP
                return True
            return False
    lnk.parent.mkdir(parents=True, exist_ok=True)
    if not _write_shortcut(lnk, exe):
        return False
    cfg[done_key] = True
    cfg[icon_key] = _ICON_STAMP
    _notify_shell(lnk)
    return True


def ensure(cfg: dict) -> bool:
    """桌面快捷方式。"""
    exe = _current_exe()
    if exe is None:
        return False
    desktop = _desktop_dir()
    if desktop is None:
        return False
    return _ensure_link(
        cfg,
        desktop / _LNK_NAME,
        done_key="desktop_shortcut_done",
        icon_key="desktop_shortcut_icon",
        exe=exe,
    )


def ensure_start_menu(cfg: dict) -> bool:
    """开始菜单快捷方式（Win 搜索主要索引这里）。"""
    exe = _current_exe()
    if exe is None:
        return False
    programs = _start_menu_programs_dir()
    if programs is None:
        return False
    return _ensure_link(
        cfg,
        programs / _LNK_NAME,
        done_key="startmenu_shortcut_done",
        icon_key="startmenu_shortcut_icon",
        exe=exe,
    )


def ensure_all(cfg: dict) -> bool:
    changed = ensure(cfg)
    if ensure_start_menu(cfg):
        changed = True
    return changed


def create_desktop_shortcut(cfg: dict) -> tuple[bool, str]:
    """用户主动创建桌面快捷方式（误删后可从设置里重建）。"""
    exe = _current_exe()
    if exe is None:
        return False, "开发模式不支持创建快捷方式。"
    desktop = _desktop_dir()
    if desktop is None:
        return False, "找不到桌面文件夹。"
    lnk = desktop / _LNK_NAME
    lnk.parent.mkdir(parents=True, exist_ok=True)
    if not _write_shortcut(lnk, exe):
        return False, "创建失败，请稍后再试。"
    cfg["desktop_shortcut_done"] = True
    cfg["desktop_shortcut_icon"] = _ICON_STAMP
    _notify_shell(lnk)
    return True, "已在桌面创建「下班倒计时」快捷方式。"
