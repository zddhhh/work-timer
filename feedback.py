"""用户反馈：写成 GitCode Issue，本地可用脚本拉下来看。"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from datetime import datetime

import store
import updater
from version import APP_VERSION

API = "https://api.gitcode.com/api/v5"
LABEL = "feedback"
USER_AGENT = f"WorkTimer/{APP_VERSION}"


def repo_url(cfg: dict) -> str:
    raw = str(cfg.get("gitcode_repo") or "").strip().rstrip("/")
    return raw or "https://gitcode.com/mdslanruo/work-timer"


def open_repo(cfg: dict) -> None:
    webbrowser.open(repo_url(cfg))


def _token(cfg: dict) -> str:
    """只用专用 feedback_token，不用发版用的 gitcode_token。"""
    t = str(cfg.get("feedback_token") or "").strip()
    if t:
        return t
    for name in ("update_defaults.secret.json", "update_defaults.json"):
        p = store.app_dir() / name
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            t = str(data.get("feedback_token") or "").strip()
            if t:
                return t
    return ""


def _issue_new_url(cfg: dict, title: str, body: str) -> str:
    owner, name = updater.parse_repo(repo_url(cfg))
    q = urllib.parse.urlencode({"title": title, "body": body})
    return f"https://gitcode.com/{owner}/{name}/issues/new?{q}"


def _compose_body(text: str) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    return (
        f"- 版本：{APP_VERSION}\n"
        f"- 时间：{now}\n\n"
        f"{(text or '').strip() or '（无正文）'}\n"
    )


def _post_issue(owner: str, repo: str, title: str, body: str, token: str) -> str:
    url = f"{API}/repos/{urllib.parse.quote(owner)}/issues?access_token={urllib.parse.quote(token)}"

    def _send(payload: dict) -> dict:
        req = urllib.request.Request(
            url,
            data=urllib.parse.urlencode(payload).encode("utf-8"),
            method="POST",
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8") or "{}")
        except urllib.error.HTTPError as e:
            err = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"提交失败 {e.code}: {err[:240]}") from e
        if not isinstance(data, dict):
            raise RuntimeError("提交成功但返回异常")
        return data

    try:
        data = _send({"repo": repo, "title": title, "body": body, "labels": LABEL})
    except RuntimeError:
        data = _send({"repo": repo, "title": title, "body": body})
    html = str(data.get("html_url") or data.get("url") or "").strip()
    number = data.get("number")
    if html:
        return html
    if number:
        return f"https://gitcode.com/{owner}/{repo}/issues/{number}"
    return f"https://gitcode.com/{owner}/{repo}/issues"


def submit(cfg: dict, title: str, text: str) -> tuple[str, str]:
    """返回 (ok|browser|err, 说明或链接)。"""
    today = datetime.now().strftime("%Y-%m-%d")
    if str(cfg.get("feedback_date") or "") != today:
        cfg["feedback_date"] = today
        cfg["feedback_count"] = 0
    try:
        n = int(cfg.get("feedback_count") or 0)
    except (TypeError, ValueError):
        n = 0
    if n >= 8:
        return "err", "今天反馈次数已用完，明天再试"
    title = (title or "").strip() or "用户反馈"
    if not title.startswith("[反馈]"):
        title = f"[反馈] {title}"
    body = _compose_body(text)
    token = _token(cfg)
    if token:
        try:
            owner, name = updater.parse_repo(repo_url(cfg))
            url = _post_issue(owner, name, title, body, token)
            cfg["feedback_count"] = n + 1
            store.save_config(cfg)
            return "ok", url
        except Exception as e:  # noqa: BLE001
            return "err", str(e)
    url = _issue_new_url(cfg, title, body)
    webbrowser.open(url)
    return "browser", url


def list_issues(cfg: dict, token: str, *, label: str | None = LABEL, per_page: int = 50) -> list[dict]:
    owner, name = updater.parse_repo(repo_url(cfg))
    params = {
        "access_token": token,
        "state": "all",
        "per_page": str(per_page),
        "page": "1",
        "sort": "created",
        "direction": "desc",
    }
    if label:
        params["labels"] = label
    q = urllib.parse.urlencode(params)
    url = f"{API}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/issues?{q}"
    req = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read().decode("utf-8") or "[]")
    if not isinstance(data, list):
        raise RuntimeError(f"拉 Issue 返回异常: {data!r}"[:240])
    return [x for x in data if isinstance(x, dict)]
