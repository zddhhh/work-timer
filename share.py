"""发给同事：留下安装包，复制文件，或复制不用登录的下载地址。"""
from __future__ import annotations

import ctypes
import os
import shutil
import struct
import time
import urllib.parse
import urllib.request
from ctypes import wintypes
from pathlib import Path

import store
import updater
from version import APP_VERSION, ASSET_NAME

_MIN_SETUP = 100 * 1024
CF_UNICODETEXT = 13
CF_HDROP = 15
GMEM_MOVEABLE = 0x0002


def public_download_url(repo: str, version: str, asset: str) -> str:
    """公开仓库的安装包直链。不带令牌，打开不用登录。"""
    owner, name = updater.parse_repo(repo)
    ver = (version or "").strip().lstrip("vV")
    asset = (asset or "").strip()
    if not ver or not asset:
        return f"https://gitcode.com/{owner}/{name}/releases"
    tag = urllib.parse.quote(f"v{ver}", safe="")
    filename = urllib.parse.quote(asset, safe="")
    return f"https://gitcode.com/{owner}/{name}/releases/download/{tag}/{filename}"


def share_text(version: str, url: str) -> str:
    return f"下班倒计时 {version}\n点这个安装，不用登录：\n{url}"


def cache_path(asset: str, root: Path | None = None) -> Path:
    name = Path(asset or "").name
    if not name or name != (asset or "") or any(ch in name for ch in "\\/:"):
        raise ValueError("安装包名字不对")
    base = root if root is not None else store.user_data_dir()
    return Path(base) / "share" / name


def _looks_like_exe(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(2) == b"MZ"
    except OSError:
        return False


def cached_setup(asset: str, root: Path | None = None) -> Path | None:
    try:
        path = cache_path(asset, root)
    except ValueError:
        return None
    try:
        if not path.is_file() or path.stat().st_size < _MIN_SETUP:
            return None
    except OSError:
        return None
    if not _looks_like_exe(path):
        return None
    return path


def remember_setup(src: Path, asset: str, root: Path | None = None) -> Path:
    """检查更新下完后留一份，下次发给同事不用再下。"""
    dest = cache_path(asset, root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    shutil.copyfile(src, part)
    os.replace(part, dest)
    return dest


def progress_line(done: int, total: int) -> str:
    got = done / (1024 * 1024)
    if total > 0:
        return f"正在下载安装包… {got:.1f} / {total / (1024 * 1024):.1f} MB"
    if done > 0:
        return f"正在下载安装包… 已下 {got:.1f} MB"
    return "正在下载安装包…"


class Pull:
    """在界面线程上一段段地下。不要丢到后台线程，Windows 代理会和窗口互相等，软件就无响应。"""

    def __init__(self, url: str, part: Path):
        self.url = url
        self.part = part
        self.resp = None
        self.fh = None
        self.done = 0
        self.total = 0

    def step(self) -> str:
        """返回 go 表示还在下，ok 表示文件已经写完并且像安装包。"""
        if self.resp is None:
            self.part.parent.mkdir(parents=True, exist_ok=True)
            req = urllib.request.Request(
                self.url,
                headers={"User-Agent": f"WorkTimer/{APP_VERSION}", "Accept": "*/*"},
            )
            self.resp = urllib.request.urlopen(req, timeout=15)
            try:
                self.total = int(self.resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                self.total = 0
            self.fh = self.part.open("wb")
        deadline = time.perf_counter() + 0.08
        while time.perf_counter() < deadline:
            chunk = self.resp.read(32 * 1024)
            if not chunk:
                self._close_io()
                self._check_file()
                return "ok"
            self.fh.write(chunk)
            self.done += len(chunk)
        return "go"

    def _check_file(self) -> None:
        try:
            size = self.part.stat().st_size
        except OSError:
            size = 0
        if size < _MIN_SETUP or not _looks_like_exe(self.part):
            self.abort()
            raise RuntimeError("安装包没下全")

    def abort(self) -> None:
        self._close_io()
        try:
            self.part.unlink()
        except OSError:
            pass

    def _close_io(self) -> None:
        if self.fh is not None:
            try:
                self.fh.close()
            except OSError:
                pass
            self.fh = None
        if self.resp is not None:
            try:
                self.resp.close()
            except Exception:
                pass
            self.resp = None


def prepare_setup(
    repo: str,
    version: str,
    asset: str,
    *,
    root: Path | None = None,
    cancel_check=None,
) -> Path:
    """一直读到下完。会挡住调用它的线程，弹窗里要改用 Pull.step，中间让窗口处理消息。"""
    found = cached_setup(asset, root)
    if found is not None:
        return found
    dest = cache_path(asset, root)
    part = dest.with_name(dest.name + ".download")
    pull = Pull(public_download_url(repo, version, asset), part)
    try:
        while True:
            if cancel_check is not None and cancel_check():
                pull.abort()
                raise updater.DownloadCancelled()
            if pull.step() == "ok":
                return remember_setup(part, asset, root)
    finally:
        try:
            part.unlink()
        except OSError:
            pass


def hdrop_bytes(path: Path) -> bytes:
    """剪贴板里的文件列表。pFiles 指向后面的宽字符路径，末尾两个空字符。"""
    wide = (str(path.resolve()) + "\0\0").encode("utf-16-le")
    return struct.pack("<IiiII", 20, 0, 0, 0, 1) + wide


def _clipboard_set(items: list[tuple[int, bytes]]) -> None:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    # 句柄是 64 位。不声明参数类型时，ctypes 按 32 位整数传，大地址会直接报错。
    # 按钮回调把这个错误吃掉，界面上就像没复制。
    kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalUnlock.restype = wintypes.BOOL
    kernel32.GlobalFree.argtypes = [ctypes.c_void_p]
    kernel32.GlobalFree.restype = ctypes.c_void_p
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.SetClipboardData.restype = ctypes.c_void_p
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    user32.OpenClipboard.restype = wintypes.BOOL
    user32.EmptyClipboard.argtypes = []
    user32.EmptyClipboard.restype = wintypes.BOOL
    user32.CloseClipboard.argtypes = []
    user32.CloseClipboard.restype = wintypes.BOOL
    opened = False
    for _ in range(10):
        if user32.OpenClipboard(None):
            opened = True
            break
        time.sleep(0.03)
    if not opened:
        raise OSError("剪贴板打不开")
    try:
        user32.EmptyClipboard()
        for fmt, blob in items:
            handle = kernel32.GlobalAlloc(GMEM_MOVEABLE, len(blob))
            if not handle:
                raise OSError("剪贴板放不下")
            ptr = kernel32.GlobalLock(handle)
            if not ptr:
                kernel32.GlobalFree(handle)
                raise OSError("剪贴板放不下")
            ctypes.memmove(ptr, blob, len(blob))
            kernel32.GlobalUnlock(handle)
            if not user32.SetClipboardData(fmt, handle):
                kernel32.GlobalFree(handle)
                raise OSError("没放进剪贴板")
    finally:
        user32.CloseClipboard()


def copy_text(text: str) -> None:
    _clipboard_set([(CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))])


def copy_file(path: Path) -> None:
    """复制文件路径。带上复制效果，企业微信才认这是要粘贴的文件，不是剪切。"""
    items = [(CF_HDROP, hdrop_bytes(path))]
    user32 = ctypes.windll.user32
    user32.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    user32.RegisterClipboardFormatW.restype = wintypes.UINT
    effect = int(user32.RegisterClipboardFormatW("Preferred DropEffect"))
    if effect:
        items.append((effect, struct.pack("<I", 1)))
    _clipboard_set(items)


def current_share(cfg: dict) -> tuple[str, str]:
    repo = str((cfg or {}).get("gitcode_repo") or "").strip() or "mdslanruo/work-timer"
    url = public_download_url(repo, APP_VERSION, ASSET_NAME)
    return url, share_text(APP_VERSION, url)
