"""从 GitCode Release 检查/下载更新。"""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
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


def parse_version(text: str) -> tuple:
    """`1.0.92` → (1, 0, 92, 1)；`1.0.92-beta` → (1, 0, 92, 0)，同号预发布排在正式版之前。"""
    text = (text or "").strip().lstrip("vV")
    nums: list[int] = []
    pre = False
    for part in re.split(r"[.\-+_]", text):
        if part.isdigit():
            if pre:
                break
            nums.append(int(part))
        elif nums:
            pre = bool(part)
            if pre:
                break
    if not nums:
        return (0, 0)
    return tuple(nums) + (0 if pre else 1,)


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
        owner, name = owner.strip(), name.strip()
        if name.lower().endswith(".git"):
            name = name[:-4]
        if owner and name and "/" not in name:
            return owner, name
    raise ValueError(f"仓库地址格式不对：{repo}（例：owner/repo 或 https://gitcode.com/owner/repo）")


def _normalize_proxies(proxies: dict) -> dict:
    out = dict(proxies)
    v = out.get("https") or ""
    if v.lower().startswith("https://"):
        out["https"] = "http://" + v[len("https://"):]
    return out


def patch_legacy_proxy() -> None:
    """Python 3.8（Win7 版）把系统代理 `127.0.0.1:端口` 读成 https:// 代理，连 HTTPS 必报
    check_hostname requires server_hostname；3.9 起已改成 http://，这里对齐。"""
    if sys.version_info >= (3, 9) or getattr(urllib.request, "_wt_proxy_patched", False):
        return
    orig = urllib.request.getproxies
    urllib.request.getproxies = lambda: _normalize_proxies(orig())
    urllib.request._wt_proxy_patched = True


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
    """只认自己那份安装包：Win7 包和主包同在一个 Release，随便拿个 .exe 会装错。"""
    for a in assets or []:
        if str(a.get("name") or "").lower() == want.lower():
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
        raise RuntimeError("仓库暂无正式版 Release（只有预发布），稍后再试")

    tag = str(release.get("tag_name") or "")
    version = tag.lstrip("vV") or str(release.get("name") or "")
    assets = release.get("assets") or []
    asset = _pick_asset(assets, asset_name)
    if asset is None and is_newer(version, APP_VERSION):
        raise RuntimeError(f"新版本 {version} 还没有上传 {asset_name}")
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


def friendly_error(msg: str) -> tuple[str, str]:
    """底层报错 → (标题, 下一步怎么做)。弹窗里不出现 HTTP、sha256、令牌这类词。"""
    low = (msg or "").lower()
    if "还没有上传" in (msg or ""):
        return "新版本还在准备", "过几分钟再试一次"
    if "http 404" in low:
        return "暂时还没有新版本", "过一会儿再试试"
    if "http 401" in low or "http 403" in low:
        return "现在没法更新", "过几分钟再试，还不行就到官网下安装包"
    if "http 5" in low:
        return "更新这边有点忙", "过几分钟再试一次"
    if any(k in low for k in ("网络", "超时", "timeout", "timed out", "urlopen", "getaddrinfo", "ssl", "unreachable")):
        return "现在连不上网", "检查一下网络，再试一次"
    if "prerelease" in low or "预发布" in msg or "no stable" in low:
        return "正式版还没出", "等正式版发布了再更新"
    if "sha256" in low or "校验" in msg:
        return "下载的文件不完整", "已经删掉了，再更新一次就好"
    if "winerror 32" in low or "被占用" in msg or "拒绝访问" in msg or "access is denied" in low:
        return "现在没法写入文件", "先关掉多开的窗口，再试一次"
    if "no space" in low or "磁盘" in msg or "enospc" in low:
        return "电脑空间不够了", "腾出大约 50 MB 再试"
    return "这次没更新成功", "再试一次，还不行就到官网下安装包"


def check_update(cfg: dict) -> tuple[str, ReleaseInfo | None]:
    repo = (cfg.get("gitcode_repo") or "").strip()
    if not repo:
        return "no_repo", None
    try:
        info = fetch_latest_release(
            repo,
            token=(cfg.get("gitcode_token") or "").strip(),
            # 不读 cfg["asset_name"]：老配置里存着单文件版的 WorkTimer.exe
            asset_name=ASSET_NAME,
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


def is_installed() -> bool:
    """安装包装的：exe 同目录有 Inno 的卸载程序。"""
    cur = current_exe_path()
    return cur is not None and (cur.parent / "unins000.exe").is_file()


def cleanup_update_artifacts() -> None:
    """清掉临时目录里上次下载/老版本 OTA 留下的文件。正被占用的跳过，下次再清。"""
    tmp = Path(tempfile.gettempdir())
    for pat in (
        "WorkTimer_update_*.exe",
        "WorkTimer_update_*.log",
        "WorkTimer_update_*.ps1",
        "WorkTimer_update_*.bat",
        "WorkTimer_uninstall_*.exe",
        "WorkTimer_uninstall_*.txt",
    ):
        for p in tmp.glob(pat):
            _unlink(p)
    _unlink(tmp / "WorkTimer.exe")


def cleanup_legacy_install(old_exe: Path | None = None, *, wait_sec: float = 30.0) -> None:
    """安装包版首次启动：删掉单文件老版本（1.3.34 及更早）留下的 exe 和副本。

    old_exe 是老进程自己的路径，由安装包从老版本的 --ota-replace --target 参数转交过来；
    老进程可能还没退干净，占用就隔一秒重试。
    """
    me = current_exe_path()
    if me is None or not is_installed():
        return
    legacy = store.legacy_install_dir()
    targets = [legacy / n for n in ("WorkTimer.exe", "WorkTimer.exe.new", "WorkTimer.exe.old", "WorkTimer.exe.bak")]
    targets.append(legacy / "installed_version.txt")
    if old_exe is not None and old_exe.suffix.lower() == ".exe" and not _same_file(old_exe.parent, me.parent):
        targets += [old_exe, Path(str(old_exe) + ".new"), Path(str(old_exe) + ".old")]
    deadline = time.monotonic() + wait_sec
    while True:
        for p in targets:
            if p.exists():
                _unlink(p)
        if not any(p.exists() for p in targets) or time.monotonic() > deadline:
            break
        time.sleep(1.0)
    try:
        legacy.rmdir()
    except OSError:
        pass


def download_update(
    info: ReleaseInfo,
    cfg: dict,
    on_progress: Callable[[int, int], None] | None = None,
    cancel_check: Callable[[], bool] | None = None,
) -> Path:
    cleanup_update_artifacts()
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
    expect = _sha256_from_body(info.body, info.asset_name)
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


_SHA_PER_ASSET = re.compile(r"sha256\(\s*([^)\s]+)\s*\)\s*[:：]\s*([0-9a-fA-F]{64})", re.I)


def _sha256_from_body(body: str, asset: str = "") -> str:
    """Release 说明里按附件 `sha256(<附件名>): <hex>` 取；只有老格式 `sha256: <hex>` 时用它。没有则跳过校验。"""
    per = {name.lower(): h for name, h in _SHA_PER_ASSET.findall(body or "")}
    if per:
        return per.get(asset.lower(), "") if asset else ""
    m = re.search(r"sha256\s*[:：]\s*([0-9a-fA-F]{64})", body or "")
    return m.group(1) if m else ""


_MIN_EXE = 1024 * 100
_DETACHED = 0x00000008
_NEW_GROUP = 0x00000200


def _same_file(a: Path, b: Path) -> bool:
    try:
        return a.resolve() == b.resolve()
    except OSError:
        return os.path.normcase(str(a)) == os.path.normcase(str(b))


def _unlink(path: Path) -> None:
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def apply_update_and_restart(setup: Path) -> None:
    """静默运行新版安装包覆盖安装，装完由安装包拉起新版。

    不再复制自己当隐藏助手去换 exe：那套「自我复制 + 无窗口进程 + 替换自身」最像木马，杀软重点盯。
    """
    cur = current_exe_path()
    if cur is None:
        raise RuntimeError("源码运行模式不能热更新，请重新打包")
    try:
        store.write_pending_whats_new(APP_VERSION)
    except OSError:
        pass
    args = [str(setup), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART", "/SP-"]
    if not is_installed():
        args.append(f"/WTLEGACY={cur}")
    env = os.environ.copy()
    # 安装包拉起的新版也是 PyInstaller 程序，别让它继承本进程的 _PYI_* 变量
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    subprocess.Popen(
        args,
        cwd=str(setup.parent),
        env=env,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=_DETACHED | _NEW_GROUP,
    )


def force_exit_for_update() -> None:
    try:
        store.flush_pending(force=True)  # 挂起的配置先落盘，别被 os._exit 吞掉
    except Exception:  # noqa: BLE001
        pass
    os._exit(0)
