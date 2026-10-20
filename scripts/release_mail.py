"""把安装包寄到调用时指定的邮箱。发版脚本不再调用这里。

发信账号放 release_mail.secret.json（不进 git），例如：

    {
      "host": "smtp.qq.com",
      "port": 465,
      "user": "你的邮箱",
      "password": "授权码",
      "from": "你的邮箱"
    }
"""
from __future__ import annotations

import json
import smtplib
from email.message import EmailMessage
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SECRET = ROOT / "release_mail.secret.json"
RELEASE_PAGE = "https://gitcode.com/mdslanruo/work-timer/releases"


def load_smtp(path: Path | None = None) -> dict | None:
    file = path if path is not None else SECRET
    if not file.exists():
        return None
    data = json.loads(file.read_text(encoding="utf-8"))
    host = str(data.get("host") or "").strip()
    user = str(data.get("user") or "").strip()
    password = str(data.get("password") or "").strip()
    sender = str(data.get("from") or user).strip()
    if not host or not user or not password or not sender:
        return None
    return {
        "host": host,
        "port": int(data.get("port") or 465),
        "user": user,
        "password": password,
        "from": sender,
    }


def _subscribe():
    import importlib.util

    path = ROOT / "scf" / "subscribe" / "index.py"
    spec = importlib.util.spec_from_file_location("subscribe_scf_mail", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def build_message(
    version: str,
    note: str,
    setup: Path,
    sender: str,
    recipients: tuple[str, ...],
    cc: tuple[str, ...] = (),
    win7: Path | None = None,
) -> EmailMessage:
    if not recipients:
        raise ValueError("没有收件人")
    # setup / win7 只用来确认文件还在，不再读进邮件。20MB 附件会把 163 当天的流量用完。
    if not setup.is_file():
        raise ValueError("没有主安装包")
    if win7 is not None and not win7.is_file():
        raise ValueError("没有 Win7 安装包")
    msg = _subscribe().build_mail(
        recipients[0], version, sender, note, download_url=RELEASE_PAGE,
    )
    if len(recipients) > 1:
        msg.replace_header("To", ", ".join(recipients))
    if cc:
        msg["Cc"] = ", ".join(cc)
    return msg


def send_release(
    version: str,
    note: str,
    setups: list[Path],
    digests: dict[str, str],
    recipients: tuple[str, ...],
) -> None:
    if not recipients:
        return
    setup = next((p for p in setups if p.name == "WorkTimer-Setup.exe"), None)
    win7 = next((p for p in setups if p.name == "WorkTimer-Win7-Setup.exe"), None)
    if setup is None:
        raise SystemExit("没有主安装包，没法发邮件")
    cfg = load_smtp()
    if cfg is None:
        raise SystemExit(
            "缺少 release_mail.secret.json（host/port/user/password/from），"
            f"安装包还没寄到 {', '.join(recipients)}"
        )
    msg = build_message(version, note, setup, cfg["from"], recipients, win7=win7)
    print(f"寄安装包到 {', '.join(recipients)} …")
    port = cfg["port"]
    if port == 465:
        server = smtplib.SMTP_SSL(cfg["host"], port, timeout=180)
    else:
        server = smtplib.SMTP(cfg["host"], port, timeout=180)
        server.starttls()
    try:
        server.login(cfg["user"], cfg["password"])
        server.send_message(msg)
    finally:
        server.quit()
    print("邮件已发出")
