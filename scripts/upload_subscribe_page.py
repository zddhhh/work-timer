#!/usr/bin/env python3
"""把报名页传到 COS，公开读。密钥只从环境变量读。"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HTML = ROOT / "scf" / "subscribe" / "page" / "index.html"
BUCKET = os.environ.get("COS_BUCKET", "wt-subscribe-1407920495")
REGION = os.environ.get("SCF_REGION", "ap-guangzhou")


def _sign(method: str, path: str, headers: dict) -> str:
    secret_id = os.environ["TENCENT_SECRET_ID"]
    secret_key = os.environ["TENCENT_SECRET_KEY"]
    now = int(time.time())
    key_time = f"{now - 60};{now + 600}"
    sign_key = hmac.new(secret_key.encode(), key_time.encode(), hashlib.sha1).hexdigest()
    header_list = sorted(headers, key=str.lower)
    canonical = "&".join(
        f"{name.lower()}={urllib.parse.quote(headers[name], safe='')}" for name in header_list
    )
    http = f"{method.lower()}\n{path}\n\n{canonical}\n"
    hashed = hashlib.sha1(http.encode()).hexdigest()
    string_to_sign = f"sha1\n{key_time}\n{hashed}\n"
    signature = hmac.new(sign_key.encode(), string_to_sign.encode(), hashlib.sha1).hexdigest()
    signed = ";".join(name.lower() for name in header_list)
    return (
        "q-sign-algorithm=sha1"
        f"&q-ak={secret_id}"
        f"&q-sign-time={key_time}"
        f"&q-key-time={key_time}"
        f"&q-header-list={signed}"
        "&q-url-param-list="
        f"&q-signature={signature}"
    )


def main() -> None:
    host = f"{BUCKET}.cos.{REGION}.myqcloud.com"
    path = "/index.html"
    body = HTML.read_bytes()
    headers = {
        "host": host,
        "content-type": "text/html; charset=utf-8",
        "x-cos-acl": "public-read",
    }
    req = urllib.request.Request(
        f"https://{host}{path}",
        data=body,
        method="PUT",
        headers={
            "Host": host,
            "Authorization": _sign("PUT", path, headers),
            "Content-Type": headers["content-type"],
            "x-cos-acl": "public-read",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            print("put", resp.status)
    except urllib.error.HTTPError as e:
        raise SystemExit(f"上传失败 {e.code} {e.read()[:400]!r}")
    print(f"https://{host}/index.html")


if __name__ == "__main__":
    main()
