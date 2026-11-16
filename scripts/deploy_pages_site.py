r"""把官网落地页发到 GitHub Pages 仓库（zddhhh/worktimer-subscribe）。

用法：
  .\.venv\Scripts\python.exe scripts\deploy_pages_site.py --dry-run
  .\.venv\Scripts\python.exe scripts\deploy_pages_site.py

只更新 index.html 和 shots/*.png；latest.json 由 scripts\gitcode_release.py 维护。
需要 gh 已登录（repo 权限）。整次发布是一个 commit。
"""
from __future__ import annotations

import argparse
import base64
import json
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "scf" / "subscribe" / "page"
OWNER = "zddhhh"
REPO = "worktimer-subscribe"
BRANCH = "main"
SITE = f"https://{OWNER}.github.io/{REPO}/"


def gh(*args: str, body: dict | None = None) -> dict:
    cmd = ["gh", "api", *args]
    if body is not None:
        cmd += ["--input", "-"]
    proc = subprocess.run(
        cmd,
        input=json.dumps(body, ensure_ascii=False) if body is not None else None,
        text=True,
        encoding="utf-8",
        capture_output=True,
        cwd=ROOT,
    )
    if proc.returncode != 0:
        raise SystemExit(f"gh api 失败: {' '.join(cmd)}\n{proc.stderr.strip()}")
    out = (proc.stdout or "").strip()
    return json.loads(out) if out else {}


def files_to_publish() -> list[tuple[str, Path]]:
    items = [("index.html", PAGE / "index.html")]
    for path in sorted((PAGE / "shots").glob("*.png")):
        items.append((f"shots/{path.name}", path))
    return items


def dry_run(items: list[tuple[str, Path]]) -> None:
    ref = gh(f"repos/{OWNER}/{REPO}/git/ref/heads/{BRANCH}")
    head = ref["object"]["sha"]
    print(f"仓库 {OWNER}/{REPO} @ {BRANCH} = {head[:7]}")
    for name, path in items:
        print(f"  {name:<22} {path.stat().st_size:>8,} bytes")
    print("dry-run：没有提交")


def wait_live(title: str) -> None:
    for i in range(18):
        try:
            req = urllib.request.Request(SITE, headers={"User-Agent": "WorkTimer-Deploy/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                html = resp.read().decode("utf-8", errors="replace")
            if title in html:
                print("线上已更新:", SITE)
                return
        except Exception as e:  # noqa: BLE001
            last = str(e)
        else:
            last = "还是旧内容"
        print(f"等待 Pages 构建… {i + 1}/18 ({last})")
        time.sleep(10)
    print("已提交但线上还没刷新，稍后打开确认:", SITE)


def main() -> None:
    ap = argparse.ArgumentParser(description="发布官网落地页到 GitHub Pages")
    ap.add_argument("--dry-run", action="store_true", help="只检查仓库和文件，不提交")
    ap.add_argument("--no-wait", action="store_true", help="提交后不等 Pages 刷新")
    ns = ap.parse_args()

    items = files_to_publish()
    missing = [name for name, path in items if not path.exists()]
    if missing:
        raise SystemExit(f"缺文件: {missing}")
    if ns.dry_run:
        dry_run(items)
        return

    ref = gh(f"repos/{OWNER}/{REPO}/git/ref/heads/{BRANCH}")
    head = ref["object"]["sha"]
    commit = gh(f"repos/{OWNER}/{REPO}/git/commits/{head}")
    base_tree = commit["tree"]["sha"]

    tree = []
    for name, path in items:
        blob = gh(
            "--method", "POST", f"repos/{OWNER}/{REPO}/git/blobs",
            body={"content": base64.b64encode(path.read_bytes()).decode("ascii"), "encoding": "base64"},
        )
        tree.append({"path": name, "mode": "100644", "type": "blob", "sha": blob["sha"]})
        print("上传", name)

    new_tree = gh(
        "--method", "POST", f"repos/{OWNER}/{REPO}/git/trees",
        body={"base_tree": base_tree, "tree": tree},
    )
    message = (
        "Redesign landing page: centered hero with real UI shot\n\n"
        "Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
    )
    new_commit = gh(
        "--method", "POST", f"repos/{OWNER}/{REPO}/git/commits",
        body={"message": message, "tree": new_tree["sha"], "parents": [head]},
    )
    gh(
        "--method", "PATCH", f"repos/{OWNER}/{REPO}/git/refs/heads/{BRANCH}",
        body={"sha": new_commit["sha"], "force": False},
    )
    print(f"已提交 {new_commit['sha'][:7]} → {OWNER}/{REPO}@{BRANCH}")
    if not ns.no_wait:
        wait_live("弹性下班计时器")


if __name__ == "__main__":
    main()
