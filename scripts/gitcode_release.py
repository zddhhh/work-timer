r"""创建 GitCode Release 并上传主安装包和 Win7 安装包。

用法:
  $env:GITCODE_TOKEN = Get-Content .gitcode_token -Raw
  .\.venv\Scripts\python.exe scripts\gitcode_release.py              先打包再发
  .\.venv\Scripts\python.exe scripts\gitcode_release.py --no-build   直接发 release/ 里已测过的包
"""
from __future__ import annotations

import hashlib
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


def ensure_setups(build: bool) -> list[Path]:
    """主包在前：1.3.34 及更早的客户端找不到 WorkTimer.exe 时取第一个 .exe 附件。"""
    ns: dict = {}
    exec((ROOT / "version.py").read_text(encoding="utf-8"), ns)
    setups = [ROOT / "release" / ns["MAIN_SETUP"], ROOT / "release" / ns["WIN7_SETUP"]]
    if build:
        print("打包安装包到 release/（不碰 dist/）…")
        subprocess.check_call([sys.executable, str(ROOT / "scripts" / "build_release.py")], cwd=ROOT)
    missing = [p.name for p in setups if not p.exists()]
    if missing:
        raise SystemExit(f"release/ 里缺 {missing}")
    return setups


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


RELEASE_NOTE = (
    "- 检查更新的说明里不再出现一长串校验码\n"
    "- 下载完成后，「日程和设置不会丢」不再压在进度条上"
)


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def main() -> None:
    tok = token()
    ver, tag = version_tag()
    setups = ensure_setups(build="--no-build" not in sys.argv[1:])
    digests = {p.name: sha256_of(p) for p in setups}
    print(f"版本 {ver} / {tag}")
    for p in setups:
        print(" ", p.name, p.stat().st_size, "sha256:", digests[p.name])
    # 新客户端按 `sha256(<附件名>): <hex>` 校验；老客户端只认第一个 `sha256: <hex>`，它们下的是主包
    sha_lines = "\n".join(f"sha256({n}): {h}" for n, h in digests.items())
    body = f"WorkTimer {ver}\n\n{RELEASE_NOTE}\n\n{sha_lines}\n\nsha256: {digests[setups[0].name]}\n"
    try:
        api(
            "POST",
            f"/repos/{OWNER}/{REPO}/releases",
            tok,
            {
                "tag_name": tag,
                "name": f"WorkTimer {tag}",
                "body": body,
                "prerelease": False,
                "target_commitish": "main",
            },
        )
        print("Release 已创建:", tag)
    except SystemExit as e:
        print("创建 Release 返回:", e)

    for p in setups:
        upload_asset(tok, tag, p)
    print(f"完成：https://gitcode.com/{OWNER}/{REPO}/releases")


if __name__ == "__main__":
    main()
