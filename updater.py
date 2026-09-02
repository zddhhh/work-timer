"""从 GitCode Release 检查/下载更新。"""
from __future__ import annotations

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
    if token:
        url += f"&access_token={urllib.parse.quote(token)}"

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
    if token:
        download_url += f"?access_token={urllib.parse.quote(token)}"

    return ReleaseInfo(
        tag=tag,
        version=version,
        name=str(release.get("name") or tag),
        body=str(release.get("body") or ""),
        download_url=download_url,
        asset_name=aname,
    )


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
        return f"error:{e}", None
    if is_newer(info.version, APP_VERSION):
        return "available", info
    return "latest", info


def current_exe_path() -> Path | None:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve()
    return None


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
    if tmp.stat().st_size < 1024 * 100:
        try:
            tmp.unlink(missing_ok=True)
        except OSError:
            pass
        raise RuntimeError("下载文件太小，可能不是有效的 exe（检查 Release 附件名）")
    return tmp


def _spawn_replacer(ps1: str, pid: int) -> None:
    tmp_dir = Path(tempfile.gettempdir())
    ps1_path = tmp_dir / f"WorkTimer_update_{pid}.ps1"
    ps1_path.write_text(ps1, encoding="utf-8")
    create_no_window = 0x08000000
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(ps1_path),
        ],
        creationflags=create_no_window,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def _replace_script(*, pid: int, new_exe: Path, cur: Path, already_staged: bool) -> str:
    """等待本进程退出后，用 rename 替换 exe（比直接 Move 覆盖更稳）。"""
    new_s = str(new_exe).replace("'", "''")
    cur_s = str(cur).replace("'", "''")
    cur_dir = str(cur.parent).replace("'", "''")
    tmp_dir_s = str(Path(tempfile.gettempdir())).replace("'", "''")
    log_s = str(Path(tempfile.gettempdir()) / f"WorkTimer_update_{pid}.log").replace("'", "''")
    stage = "1" if already_staged else "0"
    return f"""$ErrorActionPreference = 'Stop'
function Log($m) {{ Add-Content -LiteralPath '{log_s}' -Value ("[{{0}}] {{1}}" -f (Get-Date -Format 'HH:mm:ss'), $m) -ErrorAction SilentlyContinue }}
Log 'updater started'
$deadline = (Get-Date).AddSeconds(120)
while (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{
  if ((Get-Date) -gt $deadline) {{ Log 'wait timeout, abort'; exit 1 }}
  Start-Sleep -Milliseconds 400
}}
Log 'process exited'
Start-Sleep -Seconds 1
$cur = '{cur_s}'
$new = '{new_s}'
$staged = '{cur_s}.new'
$old = '{cur_s}.old'
if ({stage} -eq 0) {{
  $src = Get-Item -LiteralPath $new
  if ($src.Length -lt 100KB) {{ throw 'update file too small' }}
  Copy-Item -LiteralPath $new -Destination $staged -Force
  Log 'staged to .new'
}} else {{
  if (-not (Test-Path -LiteralPath $staged)) {{ throw 'missing staged .new' }}
  if ((Get-Item -LiteralPath $staged).Length -lt 100KB) {{ throw 'staged file too small' }}
  Log 'using existing .new'
}}
$ok = $false
for ($i = 0; $i -lt 40; $i++) {{
  try {{
    if (Test-Path -LiteralPath $old) {{ Remove-Item -LiteralPath $old -Force -ErrorAction SilentlyContinue }}
    if (Test-Path -LiteralPath $cur) {{
      Move-Item -LiteralPath $cur -Destination $old -Force
    }}
    Move-Item -LiteralPath $staged -Destination $cur -Force
    $ok = $true
    Log ('replaced ok, size=' + (Get-Item -LiteralPath $cur).Length)
    break
  }} catch {{
    Log ("retry $i : " + $_.Exception.Message)
    Start-Sleep -Milliseconds 500
  }}
}}
if (-not $ok) {{ throw 'replace failed after retries' }}
Remove-Item -LiteralPath $new,$old,'{cur_s}.bak' -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath '{cur_dir}' -Filter 'WorkTimer-*.exe' -ErrorAction SilentlyContinue | ForEach-Object {{
  if ($_.FullName -ne $cur) {{
    Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
  }}
}}
Get-ChildItem -LiteralPath '{tmp_dir_s}' -Filter 'WorkTimer_update_*' -ErrorAction SilentlyContinue | ForEach-Object {{
  Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
}}
$env:PYINSTALLER_RESET_ENVIRONMENT = '1'
$p = Start-Process -FilePath $cur -WorkingDirectory '{cur_dir}' -PassThru
Log ('restarted pid=' + $p.Id)
Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
"""


def apply_update_and_restart(new_exe: Path) -> None:
    cur = current_exe_path()
    if cur is None:
        raise RuntimeError("源码运行模式不能热更新，请重新打包 exe")
    pid = os.getpid()
    ps1 = _replace_script(pid=pid, new_exe=new_exe, cur=cur, already_staged=False)
    _spawn_replacer(ps1, pid)


def resume_pending_update() -> bool:
    """启动时若发现上次 OTA 留下的 .exe.new，继续替换并重启。"""
    cur = current_exe_path()
    pending = pending_update_path()
    if cur is None or pending is None:
        return False
    pid = os.getpid()
    ps1 = _replace_script(pid=pid, new_exe=pending, cur=cur, already_staged=True)
    _spawn_replacer(ps1, pid)
    return True


def force_exit_for_update() -> None:
    os._exit(0)
