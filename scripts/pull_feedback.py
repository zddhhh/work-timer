r"""把仓库里的用户反馈 Issue 拉到本地 feedback/ 目录。

用法:
  $env:GITCODE_TOKEN = Get-Content .gitcode_token -Raw
  .\.venv\Scripts\python.exe scripts\pull_feedback.py
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import feedback  # noqa: E402
import store  # noqa: E402


def token() -> str:
    t = (os.environ.get("GITCODE_TOKEN") or "").strip()
    if t:
        return t
    p = ROOT / ".gitcode_token"
    if p.exists():
        return p.read_text(encoding="utf-8").strip()
    raise SystemExit("缺少 GITCODE_TOKEN / .gitcode_token")


def _safe_name(n: int, title: str) -> str:
    slug = re.sub(r"[^\w\u4e00-\u9fff]+", "-", (title or "feedback").strip())[:40].strip("-")
    return f"{n:04d}-{slug or 'feedback'}.md"


def main() -> None:
    tok = token()
    cfg = store.load_config()
    items = feedback.list_issues(cfg, tok, label=feedback.LABEL)
    if not items:
        items = [
            it
            for it in feedback.list_issues(cfg, tok, label=None)
            if str(it.get("title") or "").startswith("[反馈]")
        ]
    out = ROOT / "feedback"
    out.mkdir(parents=True, exist_ok=True)
    for it in items:
        n = int(it.get("number") or 0)
        title = str(it.get("title") or "反馈")
        body = str(it.get("body") or "")
        html = str(it.get("html_url") or "")
        created = str(it.get("created_at") or "")
        contact = feedback.parse_contact(body)
        path = out / _safe_name(n, title)
        path.write_text(
            f"# {title}\n\n- 编号: #{n}\n- 时间: {created}\n- 联系: {contact or '（未留）'}\n- 链接: {html}\n\n{body}\n",
            encoding="utf-8",
        )
        print("写入", path.name, f"联系={contact or '-'}")
    (out / "index.json").write_text(
        json.dumps(
            [
                {
                    "number": it.get("number"),
                    "title": it.get("title"),
                    "contact": feedback.parse_contact(str(it.get("body") or "")),
                    "html_url": it.get("html_url"),
                }
                for it in items
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"共 {len(items)} 条 → {out}")


if __name__ == "__main__":
    main()
