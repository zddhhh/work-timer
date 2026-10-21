#!/usr/bin/env python3
"""把订阅云函数部署到腾讯云 SCF（事件函数，不覆盖三国的 sanguo-web）。

密钥只从环境变量读：TENCENT_SECRET_ID / TENCENT_SECRET_KEY
发信账号从仓库根目录的 release_mail.secret.json 读（不进代码、不进日志）。
"""

from __future__ import annotations

import base64
import io
import json
import os
import sys
import time
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "scf" / "subscribe" / "index.py"
REGION = os.environ.get("SCF_REGION", "ap-guangzhou")
FUNCTION_NAME = os.environ.get("SCF_FUNCTION_NAME", "worktimer-subscribe")
RUNTIME = "Python3.10"


def _cred():
    from tencentcloud.common import credential

    sid = os.environ.get("TENCENT_SECRET_ID", "").strip()
    skey = os.environ.get("TENCENT_SECRET_KEY", "").strip()
    if not sid or not skey:
        raise SystemExit("缺少 TENCENT_SECRET_ID / TENCENT_SECRET_KEY")
    return credential.Credential(sid, skey)


def _client(pkg: str, cls: str, endpoint: str, region: str = REGION):
    from tencentcloud.common.profile.client_profile import ClientProfile
    from tencentcloud.common.profile.http_profile import HttpProfile

    mod = __import__(pkg, fromlist=[cls])
    hp = HttpProfile(endpoint=endpoint)
    return getattr(mod, cls)(_cred(), region, ClientProfile(httpProfile=hp))


def _scf():
    return _client("tencentcloud.scf.v20180416.scf_client", "ScfClient", "scf.tencentcloudapi.com")


def _appid() -> str:
    cam = _client("tencentcloud.cam.v20190116.cam_client", "CamClient", "cam.tencentcloudapi.com", region="")
    from tencentcloud.cam.v20190116 import models

    r = cam.GetUserAppId(models.GetUserAppIdRequest())
    return str(r.AppId)


def _zip_code() -> str:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.write(SRC, "index.py")
    return base64.b64encode(buf.getvalue()).decode("ascii")


def _gitcode_token() -> str:
    token = os.environ.get("GITCODE_TOKEN", "").strip()
    if token:
        return token
    path = ROOT / ".gitcode_token"
    if path.exists():
        return path.read_text(encoding="utf-8").strip()
    return ""


def _smtp() -> dict:
    path = ROOT / "release_mail.secret.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return {
        "SMTP_HOST": data["host"],
        "SMTP_PORT": str(data["port"]),
        "SMTP_USER": data["user"],
        "SMTP_PASSWORD": data["password"],
        "SMTP_FROM": data["from"],
    }


def _ensure_bucket(appid: str) -> str:
    """私有 COS。桶名必须带 APPID。"""
    sys.path.insert(0, str(SRC.parent))
    from index import cos_authorization  # noqa: WPS433

    name = f"wt-subscribe-{appid}"
    host = f"{name}.cos.{REGION}.myqcloud.com"
    sid = os.environ["TENCENT_SECRET_ID"]
    skey = os.environ["TENCENT_SECRET_KEY"]
    now = int(time.time())
    auth = cos_authorization(sid, skey, "PUT", "/", host, start=now - 60, end=now + 600)
    req = urllib.request.Request(
        f"https://{host}/",
        method="PUT",
        headers={"Host": host, "Authorization": auth, "x-cos-acl": "private"},
        data=b"",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print("COS 桶已创建", name, resp.status)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", "replace")
        if e.code == 409 or "BucketAlreadyOwnedByYou" in body or "BucketAlreadyExists" in body:
            print("COS 桶已存在", name)
        else:
            raise SystemExit(f"建桶失败 {e.code} {body[:300]}")
    return name


def _wait_active(cli) -> None:
    from tencentcloud.scf.v20180416 import models

    for _ in range(40):
        req = models.GetFunctionRequest()
        req.FunctionName = FUNCTION_NAME
        req.Namespace = "default"
        r = cli.GetFunction(req)
        print("函数状态", r.Status)
        if r.Status == "Active":
            return
        if r.Status in ("CreateFailed", "UpdateFailed"):
            raise SystemExit("函数部署失败：" + str(getattr(r, "StatusReasons", "")))
        time.sleep(3)
    raise SystemExit("等函数就绪超时")


def _upsert(cli, zip_b64: str, env: dict) -> None:
    from tencentcloud.common.exception.tencent_cloud_sdk_exception import TencentCloudSDKException
    from tencentcloud.scf.v20180416 import models

    code = models.Code()
    code.ZipFile = zip_b64
    try:
        req = models.CreateFunctionRequest()
        req.FunctionName = FUNCTION_NAME
        req.Runtime = RUNTIME
        req.Handler = "index.main_handler"
        req.Code = code
        req.MemorySize = 512
        req.Timeout = 600
        req.Description = "弹性下班计时器邮箱订阅：收表单并寄下载地址"
        variables = []
        for k, v in env.items():
            var = models.Variable()
            var.Key = k
            var.Value = v
            variables.append(var)
        environment = models.Environment()
        environment.Variables = variables
        req.Environment = environment
        print("创建函数", FUNCTION_NAME)
        cli.CreateFunction(req)
    except TencentCloudSDKException as e:
        if "ResourceInUse" not in str(e) and "already" not in str(e).lower():
            raise
        print("函数已存在，更新代码")
        ureq = models.UpdateFunctionCodeRequest()
        ureq.FunctionName = FUNCTION_NAME
        ureq.Handler = "index.main_handler"
        ureq.ZipFile = zip_b64
        cli.UpdateFunctionCode(ureq)
        _wait_active(cli)
        cfg = models.UpdateFunctionConfigurationRequest()
        cfg.FunctionName = FUNCTION_NAME
        cfg.MemorySize = 512
        cfg.Timeout = 600
        cfg.Description = "弹性下班计时器邮箱订阅：收表单并寄下载地址"
        variables = []
        for k, v in env.items():
            var = models.Variable()
            var.Key = k
            var.Value = v
            variables.append(var)
        environment = models.Environment()
        environment.Variables = variables
        cfg.Environment = environment
        cli.UpdateFunctionConfiguration(cfg)
    _wait_active(cli)


def _triggers(cli) -> str:
    from tencentcloud.scf.v20180416 import models

    listed = models.ListTriggersRequest()
    listed.FunctionName = FUNCTION_NAME
    existing = list(cli.ListTriggers(listed).Triggers or [])
    have_http = any((t.Type or "").lower() == "http" for t in existing)
    have_timer = any((t.Type or "").lower() == "timer" for t in existing)

    if not have_http:
        treq = models.CreateTriggerRequest()
        treq.FunctionName = FUNCTION_NAME
        treq.TriggerName = "subscribe_http"
        treq.Type = "http"
        treq.TriggerDesc = json.dumps(
            {"AuthType": "NONE", "NetConfig": {"EnableIntranet": False, "EnableExtranet": True}},
            separators=(",", ":"),
        )
        print("创建 HTTP 触发器")
        cli.CreateTrigger(treq)
        time.sleep(2)

    if not have_timer:
        treq = models.CreateTriggerRequest()
        treq.FunctionName = FUNCTION_NAME
        treq.TriggerName = "subscribe_timer"
        treq.Type = "timer"
        treq.TriggerDesc = "0 */10 * * * * *"
        print("创建 10 分钟定时器")
        cli.CreateTrigger(treq)

    listed = models.ListTriggersRequest()
    listed.FunctionName = FUNCTION_NAME
    url = ""
    for t in cli.ListTriggers(listed).Triggers or []:
        desc = t.TriggerDesc or ""
        print("触发器", t.TriggerName, t.Type)
        try:
            data = json.loads(desc)
        except json.JSONDecodeError:
            continue
        net = (data.get("NetConfig") or {}) if isinstance(data, dict) else {}
        url = net.get("ExtranetUrl") or url
        if not url and isinstance(data, dict):
            url = data.get("ExtranetUrl") or url
    if not url:
        raise SystemExit("没有拿到公网地址")
    if not url.startswith("http"):
        url = "https://" + url
    return url


def main() -> None:
    appid = _appid()
    print("账号 APPID", appid)
    bucket = _ensure_bucket(appid)
    env = {
        "COS_BUCKET": bucket,
        "COS_REGION": REGION,
        "TENCENT_SECRET_ID": os.environ["TENCENT_SECRET_ID"],
        "TENCENT_SECRET_KEY": os.environ["TENCENT_SECRET_KEY"],
        "GITCODE_REPO": "mdslanruo/work-timer",
        "GITCODE_TOKEN": _gitcode_token(),
    }
    env.update(_smtp())
    cli = _scf()
    _upsert(cli, _zip_code(), env)
    url = _triggers(cli)
    print("SUBSCRIBE_URL", url)
    out = ROOT / "scf" / "subscribe" / "url.txt"
    out.write_text(url + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
