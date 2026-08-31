# 一键打包：产物进 release/，不碰 dist/（dist 留给本机旧版做 OTA 测试）
# 用法: .\.venv\Scripts\python.exe scripts\build_release.py

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
DIST_NAME = "WorkTimer"
OUT_DIR = ROOT / "release"
EXE_PATH = OUT_DIR / f"{DIST_NAME}.exe"


def main() -> None:
    py = str(VENV_PY if VENV_PY.exists() else sys.executable)
    for p in (ROOT / "build", OUT_DIR, ROOT / f"{DIST_NAME}.spec"):
        if p.is_dir():
            shutil.rmtree(p, ignore_errors=True)
        elif p.is_file():
            p.unlink(missing_ok=True)

    cmd = [
        py,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onefile",
        "--name",
        DIST_NAME,
        "--distpath",
        str(OUT_DIR),
        "--workpath",
        str(ROOT / "build"),
        "--add-data",
        "update_defaults.json;.",
        "--hidden-import",
        "themes",
        "--hidden-import",
        "ad_disguise",
        "--hidden-import",
        "store",
        "--hidden-import",
        "layered_win",
        "--hidden-import",
        "flex_time",
        "--hidden-import",
        "updater",
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
