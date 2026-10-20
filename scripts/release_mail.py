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

import io
import json
import smtplib
import zipfile
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


def _zip_setup(setup: Path) -> bytes:
    """163 会拒收 exe 附件，压成 zip 再寄。"""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.write(setup, setup.name)
    return buf.getvalue()


def build_message(
    version: str,
    note: str,
    setup: Path,
    digest: str,
    sender: str,
    recipients: tuple[str, ...],
    cc: tuple[str, ...] = (),
) -> EmailMessage:
    if not recipients:
        raise ValueError("没有收件人")
    packed = f"WorkTimer-{version}.zip"
    msg = EmailMessage()
    msg["Subject"] = f"WorkTimer {version} 安装包"
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    if cc:
        msg["Cc"] = ", ".join(cc)
    msg.set_content(
        "\n".join(
            [
                f"WorkTimer {version} 安装包在附件的压缩包里。",
                "解压后双击 WorkTimer-Setup.exe 即可安装。",
                "",
                note.strip(),
                "",
                f"sha256: {digest}",
                f"发布页：{RELEASE_PAGE}",
            ]
        )
    )
    msg.add_attachment(
        _zip_setup(setup),
        maintype="application",
        subtype="zip",
        filename=packed,
    )
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
    if setup is None:
        raise SystemExit("没有主安装包，没法发邮件")
    cfg = load_smtp()
    if cfg is None:
        raise SystemExit(
            "缺少 release_mail.secret.json（host/port/user/password/from），"
            f"安装包还没寄到 {', '.join(recipients)}"
        )
    msg = build_message(version, note, setup, digests[setup.name], cfg["from"], recipients)
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
