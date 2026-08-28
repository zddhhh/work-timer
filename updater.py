"""从 GitCode Release 检查/下载更新。"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from version import APP_VERSION, ASSET_NAME

API_BASE = "https://api.gitcode.com/api/v5"


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


def _http_get_json(url: str, token: str = "") -> object:
    headers = {"User-Agent": f"WorkTimer/{APP_VERSION}", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_download(url: str, dest: Path, token: str = "") -> None:
    headers = {"User-Agent": f"WorkTimer/{APP_VERSION}"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp, open(dest, "wb") as f:
        while True:
            chunk = resp.read(1024 * 256)
            if not chunk:
                break
            f.write(chunk)


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

    data = _http_get_json(url, token=token)
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


def cleanup_update_artifacts(*, exe_dir: Path | None = None) -> None:
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
    for name in ("WorkTimer.exe.new", "WorkTimer.exe.old", "WorkTimer.exe.bak"):
        p = root / name
        try:
            p.unlink(missing_ok=True)
        except OSError:
            pass


def download_update(info: ReleaseInfo, cfg: dict) -> Path:
    cleanup_update_artifacts()
    token = (cfg.get("gitcode_token") or "").strip()
    tmp = Path(tempfile.gettempdir()) / f"WorkTimer_update_{info.version}.exe"
    if tmp.exists():
        tmp.unlink()
    _http_download(info.download_url, tmp, token=token)
    if tmp.stat().st_size < 1024 * 100:
        raise RuntimeError("下载文件太小，可能不是有效的 exe（检查 Release 附件名）")
    return tmp


def apply_update_and_restart(new_exe: Path) -> None:
    cur = current_exe_path()
    if cur is None:
        raise RuntimeError("源码运行模式不能热更新，请重新打包 exe")

    pid = os.getpid()
    tmp_dir = Path(tempfile.gettempdir())
    ps1_path = tmp_dir / f"WorkTimer_update_{pid}.ps1"
    log_path = tmp_dir / f"WorkTimer_update_{pid}.log"
    new_s = str(new_exe).replace("'", "''")
    cur_s = str(cur).replace("'", "''")
    cur_dir = str(cur.parent).replace("'", "''")
    tmp_dir_s = str(tmp_dir).replace("'", "''")
    log_s = str(log_path).replace("'", "''")
    ps1 = f"""$ErrorActionPreference = 'Stop'
function Log($m) {{ Add-Content -LiteralPath '{log_s}' -Value ("[{{0}}] {{1}}" -f (Get-Date -Format 'HH:mm:ss'), $m) -ErrorAction SilentlyContinue }}
Log 'updater started'
$deadline = (Get-Date).AddSeconds(90)
while (Get-Process -Id {pid} -ErrorAction SilentlyContinue) {{
  if ((Get-Date) -gt $deadline) {{ Log 'wait timeout, continue'; break }}
  Start-Sleep -Seconds 1
}}
Log 'process exited'
Start-Sleep -Seconds 2
$src = Get-Item -LiteralPath '{new_s}'
if ($src.Length -lt 100KB) {{ throw 'update file too small' }}
$tmpOut = '{cur_s}.new'
Copy-Item -LiteralPath '{new_s}' -Destination $tmpOut -Force
Move-Item -LiteralPath $tmpOut -Destination '{cur_s}' -Force
Log ('replaced ok, size=' + (Get-Item -LiteralPath '{cur_s}').Length)
Remove-Item -LiteralPath '{new_s}' -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath '{cur_dir}' -Filter 'WorkTimer-*.exe' -ErrorAction SilentlyContinue | ForEach-Object {{
  if ($_.FullName -ne '{cur_s}') {{
    Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
    Log ('removed old copy ' + $_.Name)
  }}
}}
Remove-Item -LiteralPath '{cur_s}.new','{cur_s}.old','{cur_s}.bak' -Force -ErrorAction SilentlyContinue
Get-ChildItem -LiteralPath '{tmp_dir_s}' -Filter 'WorkTimer_update_*' -ErrorAction SilentlyContinue | ForEach-Object {{
  Remove-Item -LiteralPath $_.FullName -Force -ErrorAction SilentlyContinue
}}
$env:PYINSTALLER_RESET_ENVIRONMENT = '1'
$p = Start-Process -FilePath '{cur_s}' -WorkingDirectory '{cur_dir}' -PassThru
Log ('restarted pid=' + $p.Id)
Remove-Item -LiteralPath $MyInvocation.MyCommand.Path -Force -ErrorAction SilentlyContinue
"""
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


def force_exit_for_update() -> None:
    os._exit(0)
