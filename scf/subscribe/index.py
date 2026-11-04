"""订阅云函数：网页收邮箱，并用 163 把下载地址寄出去。

不附安装包。一封带 20MB 附件的信就会把 163 当天的发信流量用完。

控制台里建「事件函数」，运行环境 Python 3.10，入口 index.main_handler。
内存 512 MB，超时 600 秒，打开公网访问。
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

import base64
import hashlib
import hmac
import json
import re
import smtplib
import time
import urllib.error
import urllib.parse
import urllib.request
from email.message import EmailMessage

API = "https://api.gitcode.com/api/v5"
ASSET = "WorkTimer-Setup.exe"
WIN7_ASSET = "WorkTimer-Win7-Setup.exe"
# 两类安装包。8.1 起用主包，Windows 8 和 Windows 7 用另一份。寄过其中一类，还可以再要另一类。
SYSTEMS = {
    "main": ("Windows 8.1、10、11", ASSET),
    "win7": ("Windows 7、8", WIN7_ASSET),
}
_OS_ALIAS = {"win10": "main", "win81": "main", "win8": "win7", "main": "main", "win7": "win7"}
STATE_KEY = "/subscribe/state.json"
PAGE_URL = "https://zddhhh.github.io/worktimer-subscribe/"
DAILY_CAP = 40
_EMAIL = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,120}\.[^@\s]{1,24}$")


def main_handler(event, context):
    event = event or {}
    if _is_timer(event):
        try:
            return _fanout()
        except Exception as e:  # noqa: BLE001
            _log_error(e)
            return f"群发失败：{_public_error(e)}"
    try:
        return _http(event)
    except Exception as e:  # noqa: BLE001
        _log_error(e)
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
        if query_params(event).get("meta") == "1":
            return _meta()
        return _html(200, _form(sender=_sender()))
    if method != "POST":
        return _html(405, _message_html("不支持", "用报名页提交。"))
    form = _form_values(event)
    if form.get("cancel"):
        return _cancel(form.get("cancel") or "")
    email = _clean_email(form.get("email") or "")
    mode = "auto" if form.get("mode") == "auto" else "once"
    os_key = _clean_os(form.get("os") or "")
    if email is None:
        return _html(200, _form("邮箱要写成 name@example.com", sender=_sender()))
    if os_key is None:
        return _html(200, _form("先选一个系统", sender=_sender()))
    state = _load_state()
    release = _latest_release()
    sender = _sender()
    decision = signup(state, email, mode, release["version"], sender, os_key)
    if decision["send"] and _hold_mail(state):
        _save_state(decision["state"])
        return _html(200, _message_html("记下了", _full_text(mode)))
    if decision["send"]:
        try:
            _mail_one(email, release, os_key, unsub=(mode == "auto"))
        except Exception as e:  # noqa: BLE001
            if not _flow_out(e):
                raise
            _log_error(e)
            decision["state"]["smtp_full"] = _today()
            _save_state(decision["state"])
            return _html(200, _message_html("记下了", _full_text(mode)))
        mailed = decision["state"].setdefault("mailed", {})
        mailed[email] = remember_sent(mailed.get(email), release["version"], os_key)
        _bump_sent(decision["state"])
    _save_state(decision["state"])
    if decision["send"]:
        title = "寄出了"
    elif decision["text"].startswith("翻翻邮件"):
        title = "翻翻邮件"
    else:
        title = "记下了"
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
    if state.get("smtp_full") == _today():
        return f"发信邮箱今天寄满了，明天再寄 {version}"
    sent = []
    for person in due:
        if _sent_today(state) >= DAILY_CAP:
            break
        try:
            _mail_one(person["email"], release, person["os"], unsub=True)
        except Exception as e:  # noqa: BLE001
            if not _flow_out(e):
                _save_state(state)
                raise
            _log_error(e)
            state["smtp_full"] = _today()
            _save_state(state)
            return f"发信邮箱今天寄满了，已寄 {len(sent)} 人，明天再寄 {version}"
        mailed = state.setdefault("mailed", {})
        mailed[person["email"]] = remember_sent(mailed.get(person["email"]), version, person["os"])
        _bump_sent(state)
        sent.append(person["email"])
    if sent and len(sent) == len(due):
        state["last_version"] = version
    _save_state(state)
    if sent and len(sent) < len(due):
        return f"已寄 {version} 给 {len(sent)} 人，其余明天再寄"
    return f"已寄 {version} 给 {len(sent)} 人"


def _clean_os(raw: str) -> str | None:
    key = (raw or "").strip().lower()
    return _OS_ALIAS.get(key)


def _entry(item: object) -> dict[str, str] | None:
    if isinstance(item, str):
        email = item.strip().lower()
        os_key = "main"
    elif isinstance(item, dict):
        email = str(item.get("email") or "").strip().lower()
        os_key = _clean_os(str(item.get("os") or "")) or "main"
    else:
        return None
    if not email:
        return None
    return {"email": email, "os": os_key}


def _package(os_key: str) -> str:
    return "win7" if SYSTEMS[_clean_os(os_key) or "main"][1] == WIN7_ASSET else "main"


def packages_sent(record: object, version: str) -> set[str]:
    """这一版已经寄过哪几类。老记录只记了版本号，当成主安装包，Win7 那份还可以再寄。"""
    if record == version:
        return {"main"}
    if not isinstance(record, dict) or record.get("version") != version:
        return set()
    raw = record.get("os")
    items = raw if isinstance(raw, list) else [raw]
    found = set()
    for item in items:
        key = _clean_os(str(item or ""))
        if key:
            found.add(_package(key))
    return found


def remember_sent(record: object, version: str, os_key: str) -> dict:
    found = set(packages_sent(record, version))
    found.add(_package(os_key))
    return {"version": version, "os": sorted(found)}


def already_sent(record: object, version: str, os_key: str) -> bool:
    return _package(os_key) in packages_sent(record, version)


def signup(state: dict, email: str, mode: str, version: str, sender: str = "", os_key: str = "main") -> dict:
    """决定要不要寄这一版，以及名单怎么改。不碰网络。"""
    email = email.strip().lower()
    os_key = _clean_os(os_key) or "main"
    state = {
        "last_version": state.get("last_version") or "",
        "auto": list(state.get("auto") or []),
        "mailed": dict(state.get("mailed") or {}),
        "day": state.get("day") or "",
        "sent_count": int(state.get("sent_count") or 0),
        "smtp_full": state.get("smtp_full") or "",
    }
    # 两类各算一份：再要另一类不会把这一类的长期订阅冲掉。
    # 「只要这一版」只停掉这一类，另一类还在的话继续寄。
    was_auto = False
    auto = []
    for item in state["auto"]:
        entry = _entry(item)
        if entry is None:
            continue
        if entry["email"] == email and entry["os"] == os_key:
            was_auto = True
            continue
        auto.append(entry)
    if mode == "auto":
        auto.append({"email": email, "os": os_key})
    state["auto"] = auto
    label = SYSTEMS[os_key][0]
    other = "win7" if os_key == "main" else "main"
    other_label = SYSTEMS[other][0]
    record = state["mailed"].get(email)
    if already_sent(record, version, os_key):
        text = f"翻翻邮件，{label} 的 {version} 已经寄过了。"
        if not already_sent(record, version, other):
            text += f"{other_label} 还可以再要。"
        if mode == "auto":
            text += "以后这一类的新版本也会寄。"
        elif was_auto:
            text += "这一类以后不再自动寄。"
        return {"state": state, "send": False, "text": text}
    if _sent_today(state) >= DAILY_CAP or _hold_mail(state):
        return {"state": state, "send": False, "text": _full_text(mode)}
    text = f"最新版 {version} 的 {label} 下载地址会寄到 {email}。"
    if sender:
        text += f"发信邮箱是 {sender}，请核对发件人再点开。"
    if mode == "auto":
        text += "以后这一类的新版本也会寄。不想要了，用邮件里的链接取消。"
    else:
        text += "只要这一版。"
        if not already_sent(record, version, other):
            text += f"{other_label} 还可以另要一份。"
    return {"state": state, "send": True, "text": text}


def due_auto(state: dict, version: str) -> list[dict[str, str]]:
    if not version or not state.get("last_version") or version == state.get("last_version"):
        return []
    if not _is_newer(version, str(state.get("last_version") or "")):
        return []
    mailed = state.get("mailed") or {}
    due = []
    for item in state.get("auto") or []:
        entry = _entry(item)
        if entry is None or already_sent(mailed.get(entry["email"]), version, entry["os"]):
            continue
        due.append(entry)
    return due


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


def _today() -> str:
    from datetime import datetime, timezone, timedelta

    return datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _flow_out(e: BaseException) -> bool:
    """163 当天发信流量用完：550 flow over limit。第二天自动恢复。"""
    return "over limit" in (str(e) or "").lower()


def _full_text(mode: str) -> str:
    if mode == "auto":
        return "发信邮箱今天寄满了。已经记下，明天自动寄给你。"
    return "发信邮箱今天寄满了，明天再来要。"


def _hold_mail(state: dict) -> bool:
    return state.get("smtp_full") == _today()


def _sent_today(state: dict) -> int:
    if state.get("day") != _today():
        return 0
    return int(state.get("sent_count") or 0)


def _bump_sent(state: dict) -> None:
    today = _today()
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


def _form(error: str = "", sender: str = "") -> str:
    warn = f"<p class='err'>{_esc(error)}</p>" if error else ""
    main_url, win7_url, version = "", "", ""
    try:
        release = _latest_release()
        version = str(release.get("version") or "")
        tag = str(release.get("tag") or "")
        repo = _env("GITCODE_REPO") or "mdslanruo/work-timer"
        main_url = download_link(repo, tag, ASSET)
        win7_url = download_link(repo, tag, WIN7_ASSET)
    except Exception as e:  # noqa: BLE001
        _log_error(e)
    if sender:
        lead = (
            f"也可让 {_esc(sender)} 把地址寄到邮箱。请认准这个发件人。"
            "两类分开寄，互不影响。同一类的同一个版本只寄一次。"
        )
    else:
        lead = "先选自己的系统再下载。也可以填邮箱收链接。"
    ver = f"<p>最新版本：{_esc(version)}</p>" if version else ""
    dl = ""
    if main_url and win7_url:
        dl = (
            f"<p><a href='{_esc(main_url)}'>下载 Windows 8.1、10、11 安装包</a></p>"
            f"<p><a href='{_esc(win7_url)}'>下载 Windows 7、8 安装包</a></p>"
        )
    return f"""<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>下载 WorkTimer</title>
<style>
body {{ margin:0; font:16px/1.5 "Microsoft YaHei",sans-serif; background:#f6f1e8; color:#3a241c; }}
main {{ max-width:420px; margin:24px auto; padding:0 16px 32px; }}
h1 {{ font-size:22px; }}
label {{ display:block; margin:14px 0; }}
input[type=email] {{ width:100%; box-sizing:border-box; padding:10px; font-size:16px; }}
button {{ margin-top:8px; padding:10px 18px; font-size:16px; background:#b02a24; color:#fff; border:0; border-radius:8px; }}
.err {{ color:#b02a24; }}
</style></head><body><main>
<h1>选系统，下载安装包</h1>
{ver}
<p>{lead}</p>
{dl}
{warn}
<form method="post">
<label>邮箱<br><input type="email" name="email" required placeholder="name@example.com"></label>
<label>系统</label>
<label><input type="radio" name="os" value="main" checked> Windows 8.1、10、11</label>
<label><input type="radio" name="os" value="win7"> Windows 7、8</label>
<label><input type="radio" name="mode" value="once" checked> 只要这一版</label>
<label><input type="radio" name="mode" value="auto"> 以后每版都寄</label>
<button type="submit">寄到邮箱</button>
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
    low = text.lower()
    if "over limit" in low:
        return "发信邮箱今天寄满了，明天再试。"
    if "554" in text:
        return "邮箱把这封信退了，过一会儿再试。"
    if "429" in text or "too many" in low or "invokes this api is too large" in low:
        return "安装包列表暂时繁忙，过一会儿再试。"
    return "寄的时候出了问题，过一会儿再试。"


def _log_error(e: BaseException) -> None:
    text = re.sub(r"https?://\S+", "<url>", str(e) or e.__class__.__name__)
    text = re.sub(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "<email>", text)
    print(f"subscribe error: {type(e).__name__}: {text[:180]}")


def query_params(event: dict) -> dict[str, str]:
    for key in ("queryStringParameters", "queryString"):
        raw = (event or {}).get(key)
        if isinstance(raw, dict):
            return {str(k): "" if v is None else str(v) for k, v in raw.items()}
        if isinstance(raw, str) and raw:
            return {k: v for k, v in urllib.parse.parse_qsl(raw.lstrip("?"))}
    path = str((event or {}).get("path") or "")
    if "?" in path:
        return {k: v for k, v in urllib.parse.parse_qsl(path.split("?", 1)[1])}
    return {}


def _meta() -> dict:
    version = ""
    downloads: dict[str, str] = {}
    try:
        release = _latest_release()
        version = str(release.get("version") or "")
        tag = str(release.get("tag") or "")
        repo = _env("GITCODE_REPO") or "mdslanruo/work-timer"
        downloads = {
            "main": download_link(repo, tag, ASSET),
            "win7": download_link(repo, tag, WIN7_ASSET),
        }
    except Exception as e:  # noqa: BLE001
        _log_error(e)
    body = json.dumps(
        {"version": version, "sender": _sender(), "downloads": downloads},
        ensure_ascii=False,
    )
    return _json(200, body)


def _json(status: int, body: str) -> dict:
    return {
        "isBase64Encoded": False,
        "statusCode": status,
        "headers": {
            "Content-Type": "application/json; charset=utf-8",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, POST, OPTIONS",
        },
        "body": body,
    }


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
    downloads = {asset: _asset_url(owner, name, tag, asset) for asset in (ASSET, WIN7_ASSET)}
    return {"version": version, "note": note, "downloads": downloads, "tag": tag}


def _asset_url(owner: str, name: str, tag: str, asset: str) -> str:
    return (
        f"{API}/repos/{urllib.parse.quote(owner)}/{urllib.parse.quote(name)}/releases/"
        f"{urllib.parse.quote(tag)}/attach_files/{urllib.parse.quote(asset)}/download"
    )


def download_link(repo: str, tag: str, asset: str) -> str:
    """给收件人点的公开地址。不带令牌，过期的临时链接也不写进邮件。"""
    repo = (repo or "mdslanruo/work-timer").strip().strip("/")
    tag = (tag or "").strip()
    asset = (asset or "").strip()
    if not tag or not asset:
        return f"https://gitcode.com/{repo}/releases"
    return (
        f"https://gitcode.com/{repo}/releases/download/"
        f"{urllib.parse.quote(tag, safe='')}/{urllib.parse.quote(asset, safe='')}"
    )


def _sender() -> str:
    return _env("SMTP_FROM") or _env("SMTP_USER")


_SHA_LINE = re.compile(r"sha-?256", re.I)


def public_note(note: str) -> str:
    """更新说明里的校验行不进邮件正文。"""
    kept = [line.rstrip() for line in (note or "").splitlines() if not _SHA_LINE.search(line)]
    text = "\n".join(kept).strip()
    while "\n\n\n" in text:
        text = text.replace("\n\n\n", "\n\n")
    return text


def unsub_token(email: str, secret: str) -> str:
    """邮箱和签名绑在一起，别人改一个字母就对不上。"""
    email = email.strip().lower()
    sig = hmac.new(secret.encode(), email.encode(), hashlib.sha256).hexdigest()[:32]
    blob = base64.urlsafe_b64encode(email.encode()).decode().rstrip("=")
    return f"{blob}.{sig}"


def parse_unsub(token: str, secret: str) -> str | None:
    if not secret or "." not in (token or ""):
        return None
    blob, sig = token.rsplit(".", 1)
    pad = "=" * (-len(blob) % 4)
    try:
        email = base64.urlsafe_b64decode(blob + pad).decode("utf-8")
    except (ValueError, UnicodeError):
        return None
    email = _clean_email(email) or ""
    if not email:
        return None
    expect = hmac.new(secret.encode(), email.encode(), hashlib.sha256).hexdigest()[:32]
    if not hmac.compare_digest(expect, sig):
        return None
    return email


def cancel_link(email: str, secret: str, page: str = PAGE_URL) -> str:
    return page.rstrip("/") + "/?cancel=" + urllib.parse.quote(unsub_token(email, secret))


def unsubscribe(state: dict, token: str, secret: str) -> dict:
    """从长期名单里拿掉。不碰网络。签不对就什么都不改。"""
    email = parse_unsub(token, secret)
    state = dict(state or {})
    state["auto"] = list(state.get("auto") or [])
    if not email:
        return {"ok": False, "changed": False, "state": state, "text": "这个链接不对。"}
    auto = []
    found = False
    for item in state["auto"]:
        entry = _entry(item)
        if entry is None:
            continue
        if entry["email"] == email:
            found = True
            continue
        auto.append(entry)
    state["auto"] = auto
    if found:
        text = "已经取消长期订阅，以后的新版本不再寄到这个邮箱。"
    else:
        text = "这个邮箱没有长期订阅，不用取消。"
    return {"ok": True, "changed": found, "state": state, "text": text}


def mail_text(
    version: str,
    sender: str,
    note: str = "",
    system: str = "main",
    unsub_url: str = "",
    download_url: str = "",
) -> str:
    os_key = _clean_os(system) or "main"
    label, asset = SYSTEMS[os_key]
    lines = [
        f"最新版本：{version}",
        f"这一封是给 {label} 的。",
        f"装好后看窗口标题「下班倒计时」，后面的数字对上 {version} 就是这一版。",
        "",
    ]
    if sender:
        lines.extend(
            [
                f"这封信由 {sender} 发出。",
                "发件人不是这个邮箱，不要点里面的链接。",
                "",
            ]
        )
    lines.extend(
        [
            f"安装包不在附件里。用浏览器打开下面的地址，下载 {asset}：",
            download_url or "https://gitcode.com/mdslanruo/work-timer/releases",
            "下载后双击它安装。",
        ]
    )
    extra = public_note(note)
    if extra:
        lines.extend(["", extra])
    if unsub_url:
        lines.extend(["", "不想再收以后的新版本，打开这个链接就停：", unsub_url])
    return "\n".join(lines)


def _get_json(url: str, token: str) -> object:
    headers = {"User-Agent": "WorkTimer-Subscribe", "Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    last: BaseException | None = None
    for attempt in range(3):
        if attempt:
            time.sleep(1.0 if attempt == 1 else 2.0)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last = e
            try:
                e.close()
            except Exception:
                pass
            if e.code not in (429, 500, 502, 503, 504) or attempt == 2:
                raise
    raise last  # pragma: no cover


def build_mail(
    email: str,
    version: str,
    sender: str,
    note: str,
    system: str = "main",
    unsub_url: str = "",
    download_url: str = "",
) -> EmailMessage:
    os_key = _clean_os(system) or "main"
    msg = EmailMessage()
    msg["Subject"] = f"WorkTimer 最新版 {version}（{SYSTEMS[os_key][0]}）"
    msg["From"] = sender
    msg["To"] = email
    msg.set_content(mail_text(version, sender, note, os_key, unsub_url, download_url))
    return msg


def _cancel(token: str) -> dict:
    state = _load_state()
    result = unsubscribe(state, token, _env("SMTP_PASSWORD"))
    if result["changed"]:
        _save_state(result["state"])
    title = "已取消" if result["ok"] else "没取消"
    return _html(200, _message_html(title, result["text"]))


def _mail_one(email: str, release: dict, system: str = "main", unsub: bool = False) -> None:
    os_key = _clean_os(system) or "main"
    asset = SYSTEMS[os_key][1]
    repo = _env("GITCODE_REPO") or "mdslanruo/work-timer"
    page = download_link(repo, str(release.get("tag") or ""), asset)
    link = cancel_link(email, _env("SMTP_PASSWORD")) if unsub and _env("SMTP_PASSWORD") else ""
    msg = build_mail(
        email, release["version"], _sender(), release.get("note") or "", os_key, link, page,
    )
    host = _env("SMTP_HOST") or "smtp.163.com"
    port = int(_env("SMTP_PORT") or "465")
    user = _env("SMTP_USER")
    password = _env("SMTP_PASSWORD")
    if not user or not password:
        raise RuntimeError("发信账号还没配")
    last: BaseException | None = None
    for attempt in range(3):
        try:
            _smtp_send(host, port, user, password, msg)
            return
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, ConnectionError, TimeoutError) as e:
            last = e
            _log_error(e)
            time.sleep(4 + attempt * 6)
    raise last  # type: ignore[misc]


def _smtp_send(host: str, port: int, user: str, password: str, msg) -> None:
    if port == 465:
        server = smtplib.SMTP_SSL(host, port, timeout=300)
    else:
        server = smtplib.SMTP(host, port, timeout=300)
        server.starttls()
    try:
        server.login(user, password)
        server.send_message(msg)
    finally:
        # 163 先断开时 quit() 会再抛一次，把真正的原因盖住
        try:
            server.quit()
        except (smtplib.SMTPException, OSError):
            server.close()


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
