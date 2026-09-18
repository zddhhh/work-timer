"""从 GitCode Release 检查/下载更新。"""
from __future__ import annotations

import ctypes
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from ctypes import wintypes
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import store
from version import APP_VERSION, ASSET_NAME

API_BASE = "https://api.gitcode.com/api/v5"


class DownloadCancelled(Exception):
    """用户取消下载。"""


@dataclass
class ReleaseInfo:
    tag: str
    version: str
    name: str
    body: str
    download_url: str
    asset_name: str


def parse_version(text: str) -> tuple[int, ...]:
    text = (text or "").strip().lstrip("vV")
    nums: list[int] = []
    for part in re.split(r"[.\-+_]", text):
        if part.isdigit():
            nums.append(int(part))
        elif nums:
            break
    return tuple(nums) if nums else (0,)


def is_newer(remote: str, local: str = APP_VERSION) -> bool:
    return parse_version(remote) > parse_version(local)


def parse_repo(repo: str) -> tuple[str, str]:
    raw = (repo or "").strip().rstrip("/")
    if not raw:
        raise ValueError("还没配置 GitCode 仓库地址")
    m = re.search(r"gitcode\.com[/:]([^/]+)/([^/]+?)(?:\.git)?$", raw, re.I)
    if m:
        return m.group(1), m.group(2)
    if "/" in raw and "://" not in raw:
        owner, name = raw.split("/", 1)
        owner, name = owner.strip(), name.strip().removesuffix(".git")
        if owner and name and "/" not in name:
            return owner, name
    raise ValueError(f"仓库地址格式不对：{repo}（例：owner/repo 或 https://gitcode.com/owner/repo）")


def _http_get_json(url: str, token: str = "", *, timeout: float = 10.0) -> object:
    headers = {"User-Agent": f"WorkTimer/{APP_VERSION}", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_download(
    url: str,
    dest: Path,
    token: str = "",
    on_progress: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> None:
    headers = {"User-Agent": f"WorkTimer/{APP_VERSION}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
            total = 0
            try:
                total = int(resp.headers.get("Content-Length") or 0)
            except (TypeError, ValueError):
                total = 0
            done = 0
            while True:
                if cancel_check is not None and cancel_check():
                    raise DownloadCancelled()
                chunk = resp.read(1024 * 256)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if on_progress is not None:
                    on_progress(done, total)
    except DownloadCancelled:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise
    except Exception:
        try:
            dest.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def _pick_asset(assets: list[dict], want: str) -> dict | None:
    if not assets:
        return None
    for a in assets:
        if (a.get("name") or "").lower() == want.lower():
            return a
    for a in assets:
        if str(a.get("name") or "").lower().endswith(".exe"):
            return a
    return None


def fetch_latest_release(
    repo: str,
    *,
    token: str = "",
    asset_name: str = ASSET_NAME,
) -> ReleaseInfo:
    owner, name = parse_repo(repo)
    q = urllib.parse.urlencode({"direction": "desc", "page": 1, "per_page": 10})
    url = f"{API_BASE}/repos/{owner}/{name}/releases?{q}"

    data = _http_get_json(url, token=token, timeout=10.0)
    if not isinstance(data, list) or not data:
        raise RuntimeError("仓库还没有 Release，请先在 GitCode 发布并上传 exe")

    release = None
    for item in data:
        if item.get("prerelease"):
            continue
        release = item
        break
    if release is None:
        release = data[0]

    tag = str(release.get("tag_name") or "")
    version = tag.lstrip("vV") or str(release.get("name") or "")
    assets = release.get("assets") or []
    asset = _pick_asset(assets, asset_name)
    aname = str((asset or {}).get("name") or asset_name)

    download_url = (
        f"{API_BASE}/repos/{owner}/{name}/releases/"
        f"{urllib.parse.quote(tag)}/attach_files/{urllib.parse.quote(aname)}/download"
    )

    return ReleaseInfo(
        tag=tag,
        version=version,
        name=str(release.get("name") or tag),
        body=str(release.get("body") or ""),
        download_url=download_url,
        asset_name=aname,
    )


def _safe_error(e: BaseException) -> str:
    """给 UI 看的错误：不带 URL、不带 token。"""
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        reason = getattr(e, "reason", None)
        return f"网络错误：{reason}" if reason else "网络错误"
    if isinstance(e, TimeoutError):
        return "连接超时"
    text = str(e) or e.__class__.__name__
    return re.sub(r"https?://\S+", "<url>", text)[:160]


def check_update(cfg: dict) -> tuple[str, ReleaseInfo | None]:
    repo = (cfg.get("gitcode_repo") or "").strip()
    if not repo:
        return "no_repo", None
    try:
        info = fetch_latest_release(
            repo,
            token=(cfg.get("gitcode_token") or "").strip(),
            asset_name=(cfg.get("asset_name") or ASSET_NAME).strip() or ASSET_NAME,
        )
    except Exception as e:  # noqa: BLE001
        return f"error:{_safe_error(e)}", None
    if is_newer(info.version, APP_VERSION):
        return "available", info
    return "latest", info


def current_exe_path() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


def _spawn_stable(exe: Path) -> None:
    env = os.environ.copy()
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    subprocess.Popen(
        [str(exe)],
        cwd=str(exe.parent),
        env=env,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
    )


def maybe_relaunch_from_stable_install() -> bool:
    """在微信/QQ 目录或写不进的目录里打开时，拷到 LocalAppData 再启动。"""
    cur = current_exe_path()
    if cur is None or not store.should_relocate_exe(cur):
        return False
    dest = store.install_exe_path()
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists() and dest.resolve() == cur.resolve():
            _write_installed_version(APP_VERSION)
            return False
        pending = Path(str(cur) + ".new")
        has_pending = pending.exists() and pending.stat().st_size >= 1024 * 100
        should_copy = (
            has_pending
            or not dest.exists()
            or is_newer(APP_VERSION, _read_installed_version())
        )
        if should_copy:
            shutil.copy2(pending if has_pending else cur, dest)
            _write_installed_version(APP_VERSION)
        if not dest.exists() or dest.stat().st_size < 1024 * 100:
            return False
        _spawn_stable(dest)
        return True
    except OSError:
        return False


def _installed_version_file() -> Path:
    return store.install_dir() / "installed_version.txt"


def _read_installed_version() -> str:
    try:
        return _installed_version_file().read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _write_installed_version(ver: str) -> None:
    try:
        store.install_dir().mkdir(parents=True, exist_ok=True)
        _installed_version_file().write_text((ver or "").strip(), encoding="utf-8")
    except OSError:
        pass


def stamp_stable_install_version() -> None:
    """已在稳定目录运行时记下版本，避免旧微信包把新安装覆盖掉。"""
    cur = current_exe_path()
    if cur is None:
        return
    try:
        if cur.resolve() == store.install_exe_path().resolve():
            _write_installed_version(APP_VERSION)
    except OSError:
        pass


def cleanup_update_artifacts(*, exe_dir: Path | None = None, keep_pending: bool = True) -> None:
    tmp = Path(tempfile.gettempdir())
    for pat in (
        "WorkTimer_update_*.exe",
        "WorkTimer_update_*.log",
        "WorkTimer_update_*.ps1",
        "WorkTimer_update_*.bat",
    ):
        for p in tmp.glob(pat):
            try:
                p.unlink(missing_ok=True)
            except OSError:
                pass
    stray = tmp / "WorkTimer.exe"
    if stray.exists():
        try:
            stray.unlink(missing_ok=True)
        except OSError:
            pass

    root = exe_dir
    if root is None:
        cur = current_exe_path()
        root = cur.parent if cur else None
    if root is None or not root.is_dir():
        return
    for p in root.glob("WorkTimer-*.exe"):
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    for name in ("WorkTimer.exe.old", "WorkTimer.exe.bak"):
        p = root / name
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass
    # .exe.new 可能是未完成的 OTA，默认保留，启动时会尝试收尾
    if not keep_pending:
        p = root / "WorkTimer.exe.new"
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def pending_update_path() -> Path | None:
    cur = current_exe_path()
    if cur is None:
        return None
    pending = Path(str(cur) + ".new")
    if not pending.exists():
        return None
    try:
        if pending.stat().st_size >= 1024 * 100:
            return pending
        pending.unlink(missing_ok=True)
    except OSError:
        pass
    return None


def download_update(
    info: ReleaseInfo,
    cfg: dict,
    on_progress: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    cleanup_update_artifacts(keep_pending=False)
    token = (cfg.get("gitcode_token") or "").strip()
    # 每次独立文件名，取消后旧线程占着文件也不会挡住下一次下载
    tmp = (
        Path(tempfile.gettempdir())
        / f"WorkTimer_update_{info.version}_{os.getpid()}_{time.time_ns()}.exe"
    )
    _http_download(
        info.download_url,
        tmp,
        token=token,
        on_progress=on_progress,
        cancel_check=cancel_check,
    )
    if cancel_check is not None and cancel_check():
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise DownloadCancelled()
    if tmp.stat().st_size < 1024 * 100 or not _looks_like_exe(tmp):
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError("下载内容不是有效的 exe（可能是错误页或附件名不对）")
    expect = _sha256_from_body(info.body)
    if expect:
        got = _sha256_file(tmp)
        if got.lower() != expect.lower():
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
            raise RuntimeError("下载文件校验失败（sha256 不符），已丢弃")
    return tmp


def _looks_like_exe(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(2) == b"MZ"
    except OSError:
        return False


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _sha256_from_body(body: str) -> str:
    """Release 说明里若有 `sha256: <64 hex>` 就拿来校验；没有则跳过。"""
    m = re.search(r"sha256\s*[:：]\s*([0-9a-fA-F]{64})", body or "")
    return m.group(1) if m else ""


_MIN_EXE = 1024 * 100
_STILL_ACTIVE = 259
_PROCESS_QUERY_LIMITED = 0x1000
_ERROR_ACCESS_DENIED = 5
_DETACHED = 0x00000008
_NEW_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000


def _arg_value(argv: list[str], name: str) -> str:
    try:
        i = argv.index(name)
    except ValueError:
        return ""
    if i + 1 >= len(argv):
        return ""
    return argv[i + 1]


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    k32 = ctypes.windll.kernel32
    k32.OpenProcess.restype = wintypes.HANDLE
    k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = k32.OpenProcess(_PROCESS_QUERY_LIMITED, False, pid)
    if handle:
        code = wintypes.DWORD(0)
        k32.GetExitCodeProcess(handle, ctypes.byref(code))
        k32.CloseHandle(handle)
        return int(code.value) == _STILL_ACTIVE
    return int(k32.GetLastError()) == _ERROR_ACCESS_DENIED


def _ota_log(pid: int, msg: str) -> None:
    line = f"[{time.strftime('%H:%M:%S')}] {msg}\n"
    try:
        p = Path(tempfile.gettempdir()) / f"WorkTimer_update_{pid}.log"
        with p.open("a", encoding="utf-8") as f:
            f.write(line)
    except OSError:
        pass


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _file_ok(path: Path) -> bool:
    try:
        return path.is_file() and path.stat().st_size >= _MIN_EXE
    except OSError:
        return False


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _spawn_hidden(exe: Path, args: list[str], *, cwd: Path) -> None:
    env = os.environ.copy()
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    subprocess.Popen(
        [str(exe), *args],
        cwd=str(cwd),
        env=env,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=si,
        creationflags=_DETACHED | _NEW_GROUP | _CREATE_NO_WINDOW,
    )


def _spawn_ota_helper(*, helper: Path, pid: int, target: Path, staged: Path, source: Path) -> None:
    _spawn_hidden(
        helper,
        [
            "--ota-replace",
            "--wait-pid",
            str(pid),
            "--target",
            str(target),
            "--staged",
            str(staged),
            "--source",
            str(source),
        ],
        cwd=helper.parent,
    )


def _fallback_install(source: Path, staged: Path) -> Path:
    dest = store.install_exe_path()
    dest.parent.mkdir(parents=True, exist_ok=True)
    src = staged if _file_ok(staged) else source
    if not _file_ok(src):
        raise RuntimeError("没有可用的更新文件")
    shutil.copy2(src, dest)
    return dest


def _replace_once(cur: Path, staged: Path, old: Path) -> None:
    """cur→.old，staged→cur。重试时若 cur 已挪走，.old 就是唯一备份，不能删。"""
    if cur.exists():
        _unlink(old)
        cur.replace(old)
    if not staged.exists():
        raise OSError("missing staged")
    staged.replace(cur)


def run_ota_replace_if_requested(argv: list[str] | None = None) -> bool:
    """新 exe 自己当更新助手：等旧进程退出后换文件再启动。不走 PowerShell。"""
    args = list(sys.argv if argv is None else argv)
    if "--ota-replace" not in args:
        return False
    pid_s = _arg_value(args, "--wait-pid")
    target = Path(_arg_value(args, "--target"))
    staged = Path(_arg_value(args, "--staged"))
    source = Path(_arg_value(args, "--source"))
    try:
        pid = int(pid_s)
    except ValueError:
        pid = 0
    _ota_log(pid, "updater started")
    try:
        deadline = time.monotonic() + 120
        while _pid_running(pid):
            if time.monotonic() > deadline:
                _ota_log(pid, "wait timeout, abort")
                return True
            time.sleep(0.4)
        _ota_log(pid, "process exited")
        time.sleep(1)
        if not _file_ok(staged):
            if not _file_ok(source):
                raise RuntimeError("update file too small")
            if not _same_file(source, staged):
                shutil.copy2(source, staged)
                _ota_log(pid, "staged to .new")
        else:
            _ota_log(pid, "using existing .new")
        if not _file_ok(staged):
            raise RuntimeError("staged file too small")
        old = Path(str(target) + ".old")
        ok = False
        for i in range(40):
            try:
                _replace_once(target, staged, old)
                ok = True
                _ota_log(pid, f"replaced ok, size={target.stat().st_size}")
                break
            except OSError as e:
                _ota_log(pid, f"retry {i} : {e}")
                time.sleep(0.5)
        if not ok:
            _ota_log(pid, "replace failed, fallback LocalAppData")
            fb = _fallback_install(source, staged)
            _spawn_stable(fb)
            _ota_log(pid, "fallback restarted")
        else:
            _spawn_stable(target)
            _ota_log(pid, "restarted")
        me = Path(sys.executable).resolve() if getattr(sys, "frozen", False) else None
        for p in (old, Path(str(target) + ".bak"), source):
            if me is None or not _same_file(p, me):
                _unlink(p)
        if target.parent.is_dir():
            for p in target.parent.glob("WorkTimer-*.exe"):
                if me is None or not _same_file(p, me):
                    if not _same_file(p, target):
                        _unlink(p)
    except Exception as e:  # noqa: BLE001
        _ota_log(pid, f"helper failed: {e}")
        try:
            store.append_log(f"ota-replace: {e}")
        except OSError:
            pass
    return True


def apply_update_and_restart(new_exe: Path) -> None:
    cur = current_exe_path()
    if cur is None:
        raise RuntimeError("源码运行模式不能热更新，请重新打包 exe")
    if store.should_relocate_exe(cur):
        dest = store.install_exe_path()
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(new_exe, dest)
        _write_installed_version(APP_VERSION)
        _spawn_stable(dest)
        return
    pid = os.getpid()
    staged = Path(str(cur) + ".new")
    _spawn_ota_helper(helper=new_exe, pid=pid, target=cur, staged=staged, source=new_exe)


def resume_pending_update() -> bool:
    """启动时若发现上次 OTA 留下的 .exe.new，继续替换并重启。"""
    cur = current_exe_path()
    pending = pending_update_path()
    if cur is None or pending is None:
        return False
    pid = os.getpid()
    helper = Path(tempfile.gettempdir()) / f"WorkTimer_update_{pid}_helper.exe"
    try:
        shutil.copy2(pending, helper)
    except OSError:
        return False
    _spawn_ota_helper(helper=helper, pid=pid, target=cur, staged=pending, source=pending)
    return True


def force_exit_for_update() -> None:
    os._exit(0)
