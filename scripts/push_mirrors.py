r"""把当前分支（默认 main）和可选 tag 推到 GitCode + GitHub。

用法（仓库根目录）：
  .\.venv\Scripts\python.exe scripts\push_mirrors.py
  .\.venv\Scripts\python.exe scripts\push_mirrors.py --tag v1.4.50

约定：先合进 GitCode（origin），再镜像 GitHub。本脚本按 origin → github 顺序推。
安装包 / Release 资产仍只走 scripts\gitcode_release.py，这里只推 git 引用。
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = "origin"
GITHUB = "github"


def _run(args: list[str]) -> str:
    out = subprocess.check_output(args, cwd=ROOT, text=True, stderr=subprocess.STDOUT)
    return (out or "").strip()


def _run_ok(args: list[str]) -> None:
    print("+", " ".join(args))
    subprocess.check_call(args, cwd=ROOT)


def _remote_url(name: str) -> str:
    try:
        return _run(["git", "remote", "get-url", name])
    except subprocess.CalledProcessError as e:
        raise SystemExit(f"缺少 remote `{name}`，先：git remote add {name} <url>") from e


def main() -> None:
    ap = argparse.ArgumentParser(description="双推 GitCode + GitHub")
    ap.add_argument("--branch", default="main", help="要推的分支（默认 main）")
    ap.add_argument("--tag", default="", help="同时推送的 tag，如 v1.4.50")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不推")
    ns = ap.parse_args()

    branch = str(ns.branch).strip() or "main"
    tag = str(ns.tag or "").strip()

    # 只拦已跟踪文件的改动；未跟踪的预览/本地垃圾不挡双推。
    dirty = _run(["git", "status", "--porcelain", "--untracked-files=no"])
    if dirty:
        raise SystemExit("工作区有未提交改动，先提交或收干净再双推。")

    head = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    if head != branch:
        raise SystemExit(f"当前在 `{head}`，请先 git switch {branch}")

    origin_url = _remote_url(ORIGIN)
    github_url = _remote_url(GITHUB)
    print(f"origin  = {origin_url}")
    print(f"github  = {github_url}")
    print(f"branch  = {branch}")
    if tag:
        print(f"tag     = {tag}")
        try:
            _run(["git", "rev-parse", tag])
        except subprocess.CalledProcessError as e:
            raise SystemExit(f"本地没有 tag `{tag}`") from e

    if ns.dry_run:
        print("dry-run：不推送")
        return

    # GitCode 先，GitHub 镜像在后
    _run_ok(["git", "push", ORIGIN, branch])
    _run_ok(["git", "push", GITHUB, branch])
    if tag:
        _run_ok(["git", "push", ORIGIN, tag])
        _run_ok(["git", "push", GITHUB, tag])
    print("双推完成。Release 安装包请仍用 scripts/gitcode_release.py。")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as e:
        sys.stderr.write(getattr(e, "output", None) or str(e))
        sys.stderr.write("\n")
        raise SystemExit(e.returncode) from e
