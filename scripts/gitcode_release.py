r"""创建 GitCode Release 并上传主安装包和 Win7 安装包。

用法:
  $env:GITCODE_TOKEN = Get-Content .gitcode_token -Raw
  .\.venv\Scripts\python.exe scripts\gitcode_release.py              先打包再发
  .\.venv\Scripts\python.exe scripts\gitcode_release.py --no-build   直接发 release/ 里已测过的包

安装包只上传到 Release。不再给固定邮箱寄信，由订阅功能发送。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
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
    "- 工时盘口短线更跟手，打快停手 K 线更明显"
)

# 订阅页同站：客户端优先读这里，不打 api.gitcode.com
PAGES_OWNER = "zddhhh"
PAGES_REPO = "worktimer-subscribe"
PAGES_FILE = "latest.json"
PUBLIC_DOWNLOAD = f"https://gitcode.com/{OWNER}/{REPO}/releases/download"


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True, encoding="utf-8").strip()


def ensure_release_tree() -> None:
    """安装包按工作目录打。和远程 main 不一致，就会漏掉对方合进去的代码，或带上没提交的改动。"""
    subprocess.check_call(["git", "fetch", "--quiet", "origin", "main"], cwd=ROOT)
    dirty = _git("status", "--porcelain", "--untracked-files=no")
    if dirty:
        raise SystemExit(f"有没提交的改动，会被打进安装包。先提交推到 main，或 git stash：\n{dirty}")
    if _git("rev-parse", "HEAD") != _git("rev-parse", "origin/main"):
        raise SystemExit("本地和远程 main 不一致。先 git pull，把版本号提交推到 main，再发版。")


def _version_key(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in re.findall(r"\d+", v)[:4])


def ensure_new_version(tok: str, ver: str) -> None:
    """两个人都能发版：版本号必须比线上所有 Release 都新，撞号就停，不往别人的 Release 上传。"""
    q = urllib.parse.urlencode({"direction": "desc", "page": 1, "per_page": 20})
    items = api("GET", f"/repos/{OWNER}/{REPO}/releases?{q}", tok) or []
    tags = [str(it.get("tag_name") or "") for it in items if isinstance(it, dict)]
    taken = [t for t in tags if t and _version_key(t) >= _version_key(ver)]
    if taken:
        raise SystemExit(f"线上已有 {', '.join(taken)}，不比 {ver} 旧。先 git pull，再把版本号改大。")


def build_latest_manifest(ver: str, tag: str, body: str, digests: dict[str, str]) -> dict:
    assets = []
    for name, digest in digests.items():
        assets.append(
            {
                "name": name,
                "sha256": digest,
                "url": f"{PUBLIC_DOWNLOAD}/{urllib.parse.quote(tag, safe='')}/{urllib.parse.quote(name, safe='')}",
            }
        )
    return {
        "version": ver,
        "tag": tag,
        "body": body,
        "assets": assets,
        "downloads": {
            "main": next((a["url"] for a in assets if a["name"] == "WorkTimer-Setup.exe"), ""),
            "win7": next((a["url"] for a in assets if a["name"] == "WorkTimer-Win7-Setup.exe"), ""),
        },
    }


def publish_latest_json(manifest: dict) -> None:
    """把 latest.json 推到 GitHub Pages，客户端检查更新优先读这里。"""
    import base64
    import tempfile

    payload = json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    content_b64 = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    api_path = f"repos/{PAGES_OWNER}/{PAGES_REPO}/contents/{PAGES_FILE}"
    sha = ""
    try:
        raw = subprocess.check_output(
            ["gh", "api", api_path, "--jq", ".sha"],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        ).strip()
        sha = raw
    except subprocess.CalledProcessError:
        sha = ""
    body = {
        "message": f"WorkTimer {manifest.get('version')} latest.json",
        "content": content_b64,
        "branch": "main",
    }
    if sha:
        body["sha"] = sha
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".json", delete=False) as tmp:
        json.dump(body, tmp, ensure_ascii=False)
        tmp_path = tmp.name
    try:
        subprocess.check_call(["gh", "api", "--method", "PUT", api_path, "--input", tmp_path])
    except (OSError, subprocess.CalledProcessError) as e:
        raise SystemExit(f"上传 GitHub Pages {PAGES_FILE} 失败：{e}") from e
    finally:
        try:
            Path(tmp_path).unlink(missing_ok=True)
        except OSError:
            pass
    print(f"清单已更新: https://{PAGES_OWNER}.github.io/{PAGES_REPO}/{PAGES_FILE}")


def main() -> None:
    tok = token()
    ensure_release_tree()
    ver, tag = version_tag()
    ensure_new_version(tok, ver)
    setups = ensure_setups(build="--no-build" not in sys.argv[1:])
    digests = {p.name: sha256_of(p) for p in setups}
    print(f"版本 {ver} / {tag}")
    for p in setups:
        print(" ", p.name, p.stat().st_size, "sha256:", digests[p.name])
    # 行首加 #：给人看的更新说明会整行丢掉，校验仍然认得出。
    # 新客户端按 `sha256(<附件名>): <hex>` 校验；老客户端只认第一个 `sha256: <hex>`，它们下的是主包。
    sha_lines = "\n".join(f"# sha256({n}): {h}" for n, h in digests.items())
    body = f"WorkTimer {ver}\n\n{RELEASE_NOTE}\n\n{sha_lines}\n\n# sha256: {digests[setups[0].name]}\n"
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

    for p in setups:
        upload_asset(tok, tag, p)
    publish_latest_json(build_latest_manifest(ver, tag, body, digests))
    print(f"完成：https://gitcode.com/{OWNER}/{REPO}/releases")


if __name__ == "__main__":
    main()
