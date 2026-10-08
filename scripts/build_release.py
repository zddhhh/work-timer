# 一键打包：产物进 release/，不碰 dist/（dist 留给本机旧版做 OTA 测试）
# 用法: .\.venv\Scripts\python.exe scripts\build_release.py

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
DIST_NAME = "WorkTimer"
OUT_DIR = ROOT / "release"
EXE_PATH = OUT_DIR / f"{DIST_NAME}.exe"


def _bundle_update_defaults() -> Path:
    """把本地 update_defaults.secret.json 的 feedback_token 打进包，不改仓库里的 json。"""
    data = json.loads((ROOT / "update_defaults.json").read_text(encoding="utf-8"))
    secret = ROOT / "update_defaults.secret.json"
    if secret.exists():
        extra = json.loads(secret.read_text(encoding="utf-8"))
        if isinstance(extra, dict):
            for k, v in extra.items():
                if v not in ("", None):
                    data[k] = v
    out_dir = ROOT / "build" / "_bundle"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "update_defaults.json"
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    py = str(VENV_PY if VENV_PY.exists() else sys.executable)
    for p in (ROOT / "build", OUT_DIR, ROOT / f"{DIST_NAME}.spec"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink(missing_ok=True)

    bundled_defaults = _bundle_update_defaults()
    cmd = [
        py,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--icon",
        str(ROOT / "assets" / "app.ico"),
        "--name",
        DIST_NAME,
        "--distpath",
        str(OUT_DIR),
        "--workpath",
        str(ROOT / "build"),
        "--add-data",
        f"{bundled_defaults};.",
        "--add-data",
        "themes.json;.",
        "--add-data",
        "assets;assets",
        "--add-data",
        "docs/更新说明.md;docs",
        "--hidden-import",
        "themes",
        "--hidden-import",
        "changelog",
        "--hidden-import",
        "backdrop",
        "--hidden-import",
        "ornaments",
        "--hidden-import",
        "schedules",
        "--hidden-import",
        "memos",
        "--hidden-import",
        "worklog",
        "--hidden-import",
        "attachments",
        "--hidden-import",
        "PIL.ImageTk",
        "--hidden-import",
        "autostart",
        "--hidden-import",
        "desktop_shortcut",
        "--hidden-import",
        "single_instance",
        "--hidden-import",
        "key_hide",
        "--hidden-import",
        "uninstall",
        "--hidden-import",
        "store",
        "--hidden-import",
        "layered_win",
        "--hidden-import",
        "festival",
        "--hidden-import",
        "kinetic",
        "--hidden-import",
        "flex_time",
        "--hidden-import",
        "feedback",
        "--hidden-import",
        "updater",
        "--hidden-import",
        "win_drop",
        "--hidden-import",
        "tkinterdnd2",
        "--collect-all",
        "tkinterdnd2",
        "--hidden-import",
        "version",
        "main.py",
    ]
    subprocess.check_call(cmd, cwd=ROOT)
    size_mb = EXE_PATH.stat().st_size / (1024 * 1024)
    print(f"\nOK: {EXE_PATH}")
    print(f"大小约 {size_mb:.1f} MB")
    print("已写入 release/，未改动 dist/。请上传 GitCode 后用 dist 里的旧 exe 测 OTA。")


if __name__ == "__main__":
    main()
