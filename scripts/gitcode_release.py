r"""创建 GitCode Release 并上传 WorkTimer.exe。

用法:
  $env:GITCODE_TOKEN = Get-Content .gitcode_token -Raw
  .\.venv\Scripts\python.exe scripts\gitcode_release.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
API = "https://api.gitcode.com/api/v5"
OWNER = "mdslanruo"
REPO = "work-timer"


def token() -> str:
    t = (os.environ.get("GITCODE_TOKEN") or "").strip()
    if t:
        return t
    p = ROOT / ".gitcode_token"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    raise SystemExit("缺少 GITCODE_TOKEN / .gitcode_token")


def version_tag() -> tuple[str, str]:
    ns: dict = {}
    exec((ROOT / "version.py").read_text(encoding="utf-8"), ns)
    ver = ns["APP_VERSION"]
    return ver, f"v{ver}"


def api(method: str, path: str, tok: str, data: dict | None = None):
    url = f"{API}{path}"
    sep = "&" if "?" in url else "?"
    url = f"{url}{sep}access_token={urllib.parse.quote(tok)}"
    body = None
    headers = {"User-Agent": "WorkTimer-Release/1.0", "Accept": "application/json"}
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            content = resp.read()
            return json.loads(content.decode("utf-8")) if content else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"API 失败 {method} {path}: {e.code} {err}") from e


def ensure_exe() -> Path:
    exe = ROOT / "release" / "WorkTimer.exe"
    print("打包 exe 到 release/（不碰 dist/）…")
    subprocess.check_call([sys.executable, str(ROOT / "scripts" / "build_release.py")], cwd=ROOT)
    if not exe.exists():
        raise SystemExit("找不到 release/WorkTimer.exe")
    return exe


def upload_asset(tok: str, tag: str, exe: Path) -> None:
    q = urllib.parse.urlencode({"file_name": exe.name})
    info = api(
        "GET",
        f"/repos/{OWNER}/{REPO}/releases/{urllib.parse.quote(tag)}/upload_url?{q}",
        tok,
    )
    if isinstance(info, str):
        raise SystemExit(f"upload_url 返回异常: {info}")
    upload_url = info.get("url") or ""
    headers = dict(info.get("headers") or {})
    if not upload_url:
        raise SystemExit(f"没有 upload url: {info}")
    headers["User-Agent"] = "WorkTimer-Release/1.0"
    headers.setdefault("Content-Type", "application/octet-stream")
    data = exe.read_bytes()
    req = urllib.request.Request(upload_url, data=data, method="PUT", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            print("上传成功:", resp.status, resp.read()[:120])
    except urllib.error.HTTPError as e:
        raise SystemExit(
            f"上传失败 {e.code}: {e.read().decode('utf-8', errors='replace')}\n也可网页手动上传: {exe}"
        ) from e


def main() -> None:
    tok = token()
    ver, tag = version_tag()
    exe = ensure_exe()
    print(f"版本 {ver} / {tag}")
    print("exe:", exe, exe.stat().st_size)
    try:
        api(
            "POST",
            f"/repos/{OWNER}/{REPO}/releases",
            tok,
            {
                "tag_name": tag,
                "name": f"WorkTimer {tag}",
                "body": (
                    f"WorkTimer {ver}\n\n"
                    "- 淡影默认皮：标题更弱、数字对比更高\n"
                    "- 计时中底部细进度条，长度跟剩余工时走"
                ),
                "prerelease": False,
                "target_commitish": "main",
            },
        )
        print("Release 已创建:", tag)
    except SystemExit as e:
        print("创建 Release 返回:", e)

    upload_asset(tok, tag, exe)
    print(f"完成：https://gitcode.com/{OWNER}/{REPO}/releases")


if __name__ == "__main__":
    main()
