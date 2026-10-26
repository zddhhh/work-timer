"""告诉启动器：这一版已经进了主界面。文件名规则要和 launcher/launcher.c 一致。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import store

def signal() -> None:
    """安装包拉起时带 --boot-token。源码运行、或没有这个参数，什么都不写。"""
    if not getattr(sys, "frozen", False):
        return
    try:
        _write()
    except Exception:
        return


def _write() -> None:
    argv = sys.argv[1:]
    flag = "--boot-token"
    if flag not in argv:
        return
    i = argv.index(flag)
    if i + 1 >= len(argv):
        return
    token = argv[i + 1].strip()
    if not token or len(token) > 32 or any(c not in "0123456789abcdefABCDEF" for c in token):
        return
    override = os.environ.get("WT_BOOT_DIR", "").strip()
    folder = Path(override) if override else store.user_data_dir()
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"boot-{token}.ok").write_text("ok", encoding="ascii")
