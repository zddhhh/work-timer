r"""用 GitCode Token 一键建仓库，并把本地项目推上去。

用法（PowerShell）:
  $env:GITCODE_TOKEN = Get-Content .gitcode_token -Raw
  .\.venv\Scripts\python.exe scripts\gitcode_bootstrap.py
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
REPO_NAME = os.environ.get("GITCODE_REPO_NAME", "work-timer")
PRIVATE = os.environ.get("GITCODE_PRIVATE", "0") in ("1", "true", "True")


def api(method: str, path: str, token: str, data: dict | None = None) -> dict:
    url = f"{API}{path}"
    if "?" in url:
        url += f"&access_token={urllib.parse.quote(token)}"
    else:
        url += f"?access_token={urllib.parse.quote(token)}"
    body = None
    headers = {
        "User-Agent": "WorkTimer-Bootstrap/1.0",
        "Accept": "application/json",
    }
    if data is not None:
        body = json.dumps(data).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            raw = resp.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except urllib.error.HTTPError as e:
        err = e.read().decode("utf-8", errors="replace")
        raise SystemExit(f"API {method} {path} 失败 HTTP {e.code}: {err}") from e


def run(cmd: list[str]) -> None:
    shown = []
    for part in cmd:
        if "oauth2:" in part:
            shown.append("https://oauth2:***@gitcode.com/...")
        else:
            shown.append(part)
    print("+", " ".join(shown))
    subprocess.check_call(cmd, cwd=ROOT)


def main() -> None:
    token = (os.environ.get("GITCODE_TOKEN") or "").strip()
    if not token:
        p = ROOT / ".gitcode_token"
        if p.exists():
            token = p.read_text(encoding="utf-8").strip()
    if not token:
        raise SystemExit("请先设置环境变量 GITCODE_TOKEN 或写入 .gitcode_token")

    me = api("GET", "/user", token)
    login = me.get("login") or me.get("username") or me.get("name")
    if not login:
        raise SystemExit(f"无法识别用户：{me}")
    print(f"已登录 GitCode 用户：{login}")

    html = f"https://gitcode.com/{login}/{REPO_NAME}"
    clone = f"https://gitcode.com/{login}/{REPO_NAME}.git"
    try:
        created = api(
            "POST",
            "/user/repos",
            token,
            {
                "name": REPO_NAME,
                "path": REPO_NAME,
                "description": "Win 透明弹性下班计时器：8:30–9:30 到岗，对应 18:00–19:00 下班",
                "private": PRIVATE,
                "auto_init": False,
                "has_issues": True,
                "has_wiki": False,
                "default_branch": "main",
            },
        )
        html = created.get("html_url") or html
        clone = created.get("clone_url") or clone
        print("仓库已创建：", html)
    except SystemExit as e:
        if "已存在" in str(e) or "422" in str(e) or "400" in str(e) or "409" in str(e):
            print("仓库可能已存在，继续配置远程：", html)
        else:
            raise

    defaults = ROOT / "update_defaults.json"
    defaults.write_text(
        json.dumps({"gitcode_repo": html, "asset_name": "WorkTimer.exe"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    cfg_dir = Path.home() / "AppData" / "Roaming" / "WorkTimer"
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cfg_path = cfg_dir / "config.json"
    cfg = {}
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cfg = {}
    cfg["gitcode_repo"] = html
    cfg.setdefault("asset_name", "WorkTimer.exe")
    if PRIVATE:
        cfg["gitcode_token"] = token
    else:
        cfg.pop("gitcode_token", None)
    cfg_path.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
    print("已写入更新配置：", cfg_path)

    if not (ROOT / ".git").exists():
        run(["git", "init", "-b", "main"])
    try:
        run(["git", "remote", "remove", "origin"])
    except subprocess.CalledProcessError:
        pass
    # 不把 token 写进 remote URL（会明文留在 .git/config 里）；推送时由凭据管理器保存一次即可
    run(["git", "remote", "add", "origin", clone])
    run(["git", "config", "credential.https://gitcode.com.username", "oauth2"])
    print("仓库：", html)
    print("首次 push 会弹凭据窗口：用户名 oauth2，密码填 GitCode 令牌；之后由 Git Credential Manager 记住。")


if __name__ == "__main__":
    main()
