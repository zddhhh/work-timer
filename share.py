"""发给同事：留下安装包，复制文件，或复制不用登录的下载地址。"""
from __future__ import annotations

import ctypes
import os
import shutil
import struct
import urllib.parse
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
    return f"弹性下班计时器 {version}\n点这个安装，不用登录：\n{url}"


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


def prepare_setup(
    repo: str,
    version: str,
    asset: str,
    *,
    root: Path | None = None,
    cancel_check=None,
) -> Path:
    found = cached_setup(asset, root)
    if found is not None:
        return found
    dest = cache_path(asset, root)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".download")
    updater._http_download(
        public_download_url(repo, version, asset),
        part,
        cancel_check=cancel_check,
    )
    try:
        if part.stat().st_size < _MIN_SETUP or not _looks_like_exe(part):
            raise RuntimeError("安装包没下全")
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


def _clipboard_set(fmt: int, blob: bytes) -> None:
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    kernel32.GlobalAlloc.restype = ctypes.c_void_p
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
    user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]
    user32.OpenClipboard.argtypes = [wintypes.HWND]
    if not user32.OpenClipboard(None):
        raise OSError("剪贴板打不开")
    try:
        user32.EmptyClipboard()
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
    _clipboard_set(CF_UNICODETEXT, (text + "\0").encode("utf-16-le"))


def copy_file(path: Path) -> None:
    _clipboard_set(CF_HDROP, hdrop_bytes(path))


def reveal_in_folder(path: Path) -> None:
    os.startfile(path.parent)  # noqa: S606  打开留下安装包的文件夹，不启动安装包


def current_share(cfg: dict) -> tuple[str, str]:
    repo = str((cfg or {}).get("gitcode_repo") or "").strip() or "mdslanruo/work-timer"
    url = public_download_url(repo, APP_VERSION, ASSET_NAME)
    return url, share_text(APP_VERSION, url)
