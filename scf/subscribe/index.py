"""订阅云函数：网页收邮箱，并用 163 把安装包 zip 寄出去。

控制台里建「事件函数」，运行环境 Python 3.10，入口 index.main_handler。
内存 256 MB，超时 120 秒，打开公网访问。
同一个函数挂两个触发器：
- HTTP 触发器，匿名访问，用来打开报名页
- 定时触发器，每 10 分钟，用来给「以后每版都寄」的人发新版本

对象存储建一个私有桶，不必预置文件。环境变量：

    COS_BUCKET          桶名，形如 worktimer-1250000000
    COS_REGION          如 ap-guangzhou
    TENCENT_SECRET_ID
    TENCENT_SECRET_KEY
    SMTP_HOST           smtp.163.com
    SMTP_PORT           465
    SMTP_USER
    SMTP_PASSWORD       163 授权码
    SMTP_FROM
    GITCODE_REPO        mdslanruo/work-timer
    GITCODE_TOKEN       可空；公开仓库拉得到 Release 就不用
"""
from __future__ import annotations

import hashlib
import hmac
import io
import json
import re
import smtplib
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from email.message import EmailMessage

API = "https://api.gitcode.com/api/v5"
ASSET = "WorkTimer-Setup.exe"
STATE_KEY = "/subscribe/state.json"
DAILY_CAP = 40
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,120}\.[^@\s]{1,24}$")


def main_handler(event, context):
    event = event or {}
    if _is_timer(event):
        try:
            return _fanout()
        except Exception as e:  # noqa: BLE001
            return f"群发失败：{_public_error(e)}"
    try:
        return _http(event)
    except Exception as e:  # noqa: BLE001
        return _html(200, _message_html("没寄成", _public_error(e)))


def _is_timer(event: dict) -> bool:
    if str(event.get("Type") or "") == "Timer":
        return True
    if event.get("httpMethod") or event.get("requestContext"):
        return False
    return bool(event.get("TriggerName") or event.get("Time"))


def _http(event: dict) -> dict:
    method = str(event.get("httpMethod") or "GET").upper()
    if method == "OPTIONS":
        return _html(204, "")
    if method == "GET":
        return _html(200, _form())
    if method != "POST":
        return _html(405, _message_html("不支持", "用报名页提交。"))
    form = _form_values(event)
    email = _clean_email(form.get("email") or "")
    mode = "auto" if form.get("mode") == "auto" else "once"
    if email is None:
        return _html(200, _form("邮箱要写成 name@example.com"))
    state = _load_state()
    release = _latest_release()
    decision = signup(state, email, mode, release["version"])
    if decision["send"]:
        _mail_one(email, release)
        decision["state"].setdefault("mailed", {})[email] = release["version"]
        _bump_sent(decision["state"])
    _save_state(decision["state"])
    title = "寄出了" if decision["send"] else "记下了"
    return _html(200, _message_html(title, decision["text"]))


def _fanout() -> str:
    state = _load_state()
    release = _latest_release()
    version = release["version"]
    if not state.get("last_version"):
        state["last_version"] = version
        _save_state(state)
        return f"记下当前版本 {version}，这一轮不群发"
    due = due_auto(state, version)
    if not due:
        return f"没有要寄的人（最新 {version}）"
    sent = []
    for email in due:
        if _sent_today(state) >= DAILY_CAP:
            break
        _mail_one(email, release)
        state.setdefault("mailed", {})[email] = version
        _bump_sent(state)
        sent.append(email)
    if sent and len(sent) == len(due):
        state["last_version"] = version
    _save_state(state)
    return f"已寄 {version} 给 {len(sent)} 人"


def signup(state: dict, email: str, mode: str, version: str) -> dict:
    """决定要不要寄这一版，以及名单怎么改。不碰网络。"""
    email = email.strip().lower()
    state = {
        "last_version": state.get("last_version") or "",
        "auto": list(state.get("auto") or []),
        "mailed": dict(state.get("mailed") or {}),
        "day": state.get("day") or "",
        "sent_count": int(state.get("sent_count") or 0),
    }
    auto = [e for e in state["auto"] if e != email]
    if mode == "auto":
        auto.append(email)
    state["auto"] = auto
    already = state["mailed"].get(email) == version
    if already:
        text = f"{version} 已经寄到这个邮箱了。"
        if mode == "auto":
            text += "以后的新版本也会寄。"
        return {"state": state, "send": False, "text": text}
    if _sent_today(state) >= DAILY_CAP:
        return {"state": state, "send": False, "text": "今天寄得太多了，明天再试。"}
    text = f"{version} 的安装包会寄到 {email}。解压后双击 WorkTimer-Setup.exe。"
    if mode == "auto":
        text += "以后每次新版本也会寄。"
    else:
        text += "只要这一版。"
    return {"state": state, "send": True, "text": text}


def due_auto(state: dict, version: str) -> list[str]:
    if not version or not state.get("last_version") or version == state.get("last_version"):
        return []
    if not _is_newer(version, str(state.get("last_version") or "")):
        return []
    mailed = state.get("mailed") or {}
    return [e for e in (state.get("auto") or []) if mailed.get(e) != version]


def _is_newer(latest: str, current: str) -> bool:
    def parts(v: str) -> tuple:
        out = []
        for bit in (v or "").split("."):
            num = ""
            for ch in bit:
                if ch.isdigit():
                    num += ch
                else:
                    break
            out.append(int(num) if num else 0)
        return tuple(out)

    a, b = parts(latest), parts(current)
    n = max(len(a), len(b))
    a += (0,) * (n - len(a))
    b += (0,) * (n - len(b))
    return a > b


def _sent_today(state: dict) -> int:
    from datetime import datetime, timezone, timedelta

    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    if state.get("day") != today:
        return 0
    return int(state.get("sent_count") or 0)


def _bump_sent(state: dict) -> None:
    from datetime import datetime, timezone, timedelta

    today = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")
    if state.get("day") != today:
        state["day"] = today
        state["sent_count"] = 0
    state["sent_count"] = int(state.get("sent_count") or 0) + 1


def _clean_email(raw: str) -> str | None:
    text = (raw or "").strip().lower()
    if any(ch in text for ch in "\r\n\t ,;"):
        return None
    if not _EMAIL.match(text):
        return None
    return text


def _form_values(event: dict) -> dict[str, str]:
    raw = event.get("body") or ""
    if event.get("isBase64Encoded"):
        import base64

        raw = base64.b64decode(raw).decode("utf-8", errors="replace")
    out: dict[str, str] = {}
    for key, value in urllib.parse.parse_qsl(str(raw), keep_blank_values=True):
        out[key] = value
    return out


def _form(error: str = "") -> str:
    warn = f"<p class='err'>{_esc(error)}</p>" if error else ""
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>用邮箱收 WorkTimer</title>
<style>
body {{ margin:0; font:16px/1.5 "Microsoft YaHei",sans-serif; background:#f6f1e8; color:#3a241c; }}
main {{ max-width:420px; margin:24px auto; padding:0 16px 32px; }}
h1 {{ font-size:22px; }}
label {{ display:block; margin:14px 0; }}
input[type=email] {{ width:100%; box-sizing:border-box; padding:10px; font-size:16px; }}
button {{ margin-top:8px; padding:10px 18px; font-size:16px; background:#b02a24; color:#fff; border:0; border-radius:8px; }}
.err {{ color:#b02a24; }}
</style></head><body><main>
<h1>用邮箱收安装包</h1>
<p>电脑连不上更新时，把安装包寄到邮箱。解压后双击 WorkTimer-Setup.exe。</p>
{warn}
<form method="post">
<label>邮箱<br><input type="email" name="email" required placeholder="name@example.com"></label>
<label><input type="radio" name="mode" value="once" checked> 只要这一版</label>
<label><input type="radio" name="mode" value="auto"> 以后每版都寄</label>
<button type="submit">寄给我</button>
</form>
</main></body></html>"""


def _message_html(title: str, text: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_esc(title)}</title></head>
<body style="font:16px/1.5 'Microsoft YaHei',sans-serif;background:#f6f1e8;color:#3a241c;padding:24px">
<h1>{_esc(title)}</h1><p>{_esc(text)}</p></body></html>"""


def _html(status: int, html: str) -> dict:
    return {
        "isBase64Encoded": False,
        "statusCode": status,
        "headers": {
            "Content-Type": "text/html; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        },
        "body": html,
    }


def _esc(text: str) -> str:
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _public_error(e: BaseException) -> str:
    text = str(e) or e.__class__.__name__
    if "554" in text:
        return "邮箱把这封信退了，过一会儿再试。"
    return "寄的时候出了问题，过一会儿再试。"


def _env(name: str) -> str:
    import os

    return (os.environ.get(name) or "").strip()


def _latest_release() -> dict:
    repo = _env("GITCODE_REPO") or "mdslanruo/work-timer"
    owner, name = repo.strip("/").split("/", 1)
    q = urllib.parse.urlencode({"direction": "desc", "page": 1, "per_page": 10})
    url = f"{API}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/releases?{q}"
    data = _get_json(url, _env("GITCODE_TOKEN"))
    if not isinstance(data, list) or not data:
        raise RuntimeError("还没有发布版本")
    release = next((item for item in data if not item.get("prerelease")), None)
    if release is None:
        raise RuntimeError("还没有正式版")
    tag = str(release.get("tag_name") or "")
    version = tag.lstrip("vV") or str(release.get("name") or "")
    note = str(release.get("body") or "").strip()
    download = (
        f"{API}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/releases/"
        f"{urllib.parse.quote(tag)}/attach_files/{urllib.parse.quote(ASSET)}/download"
    )
    return {"version": version, "note": note, "download": download, "tag": tag}


def _get_json(url: str, token: str) -> object:
    headers = {"User-Agent": "WorkTimer-Subscribe", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str) -> bytes:
    token = _env("GITCODE_TOKEN")
    headers = {"User-Agent": "WorkTimer-Subscribe"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp:
        return resp.read()


def _zip_setup(blob: bytes) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_STORED) as zf:
        zf.writestr(ASSET, blob)
    return buf.getvalue()


def _mail_one(email: str, release: dict) -> None:
    blob = _download(release["download"])
    digest = hashlib.sha256(blob).hexdigest()
    packed = _zip_setup(blob)
    version = release["version"]
    msg = EmailMessage()
    msg["Subject"] = f"WorkTimer {version} 安装包"
    msg["From"] = _env("SMTP_FROM") or _env("SMTP_USER")
    msg["To"] = email
    msg.set_content(
        "\n".join(
            [
                f"WorkTimer {version} 安装包在附件的压缩包里。",
                "解压后双击 WorkTimer-Setup.exe 即可安装。",
                "",
                (release.get("note") or "").strip(),
                "",
                f"sha256: {digest}",
            ]
        )
    )
    msg.add_attachment(packed, maintype="application", subtype="zip", filename=f"WorkTimer-{version}.zip")
    host = _env("SMTP_HOST") or "smtp.163.com"
    port = int(_env("SMTP_PORT") or "465")
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")
    if not user or not password:
        raise RuntimeError("发信账号还没配")
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=180)
    else:
        server = smtplib.SMTP(host, port, timeout=180)
        server.starttls()
    try:
        server.login(user, password)
        server.send_message(msg)
    finally:
        server.quit()


def _load_state() -> dict:
    try:
        raw = _cos("GET", STATE_KEY)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {}
        raise
    if not raw:
        return {}
    data = json.loads(raw.decode("utf-8"))
    return data if isinstance(data, dict) else {}


def _save_state(state: dict) -> None:
    body = json.dumps(state, ensure_ascii=False).encode("utf-8")
    _cos("PUT", STATE_KEY, body)


def _cos(method: str, key: str, body: bytes | None = None) -> bytes:
    bucket = _env("COS_BUCKET")
    region = _env("COS_REGION")
    secret_id = _env("TENCENT_SECRET_ID")
    secret_key = _env("TENCENT_SECRET_KEY")
    if not bucket or not region or not secret_id or not secret_key:
        raise RuntimeError("对象存储还没配")
    host = f"{bucket}.cos.{region}.myqcloud.com"
    path = key if key.startswith("/") else "/" + key
    now = int(__import__("time").time())
    auth = cos_authorization(
        secret_id, secret_key, method, path, host, start=now - 60, end=now + 600,
    )
    req = urllib.request.Request(
        f"https://{host}{path}",
        data=body,
        method=method,
        headers={"Host": host, "Authorization": auth},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read()
    except urllib.error.HTTPError as e:
        if e.code != 404:
            e.read()
        raise


def cos_authorization(
    secret_id: str,
    secret_key: str,
    method: str,
    path: str,
    host: str,
    *,
    start: int,
    end: int,
) -> str:
    """对象存储 V5 签名，只签 host。"""
    key_time = f"{start};{end}"
    sign_key = hmac.new(secret_key.encode(), key_time.encode(), hashlib.sha1).hexdigest()
    headers = f"host={urllib.parse.quote(host, safe='')}"
    http_string = f"{method.lower()}\n{path}\n\n{headers}\n"
    hashed = hashlib.sha1(http_string.encode()).hexdigest()
    string_to_sign = f"sha1\n{key_time}\n{hashed}\n"
    signature = hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()
    return (
        "q-sign-algorithm=sha1"
        f"&q-ak={secret_id}"
        f"&q-sign-time={key_time}"
        f"&q-key-time={key_time}"
        "&q-header-list=host"
        "&q-url-param-list="
        f"&q-signature={signature}"
    )
