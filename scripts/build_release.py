# 一键打包：单个 WorkTimer.exe
# 用法: .\.venv\Scripts\python.exe scripts\build_release.py

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PY = ROOT / ".venv" / "Scripts" / "python.exe"
DIST_NAME = "WorkTimer"
EXE_PATH = ROOT / "dist" / f"{DIST_NAME}.exe"


def main() -> None:
    py = str(VENV_PY if VENV_PY.exists() else sys.executable)
    for p in (ROOT / "build", ROOT / "dist", ROOT / f"{DIST_NAME}.spec"):
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
        "--add-data",
        "update_defaults.json;.",
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
    print("上传 GitCode Release 后，请从远端下载测试")


if __name__ == "__main__":
    main()
