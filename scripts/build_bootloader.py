# 用 MinGW 从源码编译 PyInstaller bootloader，装回指定 venv。
# 官方预编译 bootloader 与大量恶意样本共用同一份二进制，自编译后特征不同，杀软误报少很多。
# 用法: python scripts\build_bootloader.py .venv      （Win10/11 包，Python 3.12）
#       python scripts\build_bootloader.py .venv38    （Win7 包，Python 3.8）
# 升级 PyInstaller 后要重跑一次，否则 pip 装回来的又是官方 bootloader。

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build_tools"
WINLIBS_GLOB = "BrechtSanders.WinLibs.POSIX.MSVCRT_*"


def _gcc_bin() -> Path:
    found = shutil.which("gcc")
    if found:
        return Path(found).parent
    pkgs = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for d in sorted(pkgs.glob(WINLIBS_GLOB)):
        b = d / "mingw64" / "bin"
        if (b / "gcc.exe").exists():
            return b
    raise SystemExit("找不到 gcc：winget install BrechtSanders.WinLibs.POSIX.MSVCRT")


def _pyinstaller_version(py: Path) -> str:
    out = subprocess.check_output([str(py), "-c", "import PyInstaller; print(PyInstaller.__version__)"], text=True)
    return out.strip()


def _fetch_sdist(ver: str) -> Path:
    WORK.mkdir(exist_ok=True)
    src = WORK / f"pyinstaller-{ver}"
    if (src / "bootloader" / "waf").exists() and (src / "bootloader" / "tests").is_dir():
        return src
    with urllib.request.urlopen(f"https://pypi.org/pypi/pyinstaller/{ver}/json", timeout=60) as r:
        meta = json.load(r)
    sd = next(u for u in meta["urls"] if u["packagetype"] == "sdist")
    tgz = WORK / sd["filename"]
    if not tgz.exists():
        print("下载", sd["url"])
        urllib.request.urlretrieve(sd["url"], tgz)
    with tarfile.open(tgz) as tf:
        # 顶层 tests/ 里有符号链接，Windows 上解不出来，也用不到；bootloader/tests 是 waf 要读的，不能跳
        members = [
            m for m in tf.getmembers()
            if not (m.issym() or m.islnk()) and not m.name.startswith(f"pyinstaller-{ver}/tests/")
        ]
        tf.extractall(WORK, members=members)
    return src


def main() -> None:
    venv = ROOT / (sys.argv[1] if len(sys.argv) > 1 else ".venv")
    py = venv / "Scripts" / "python.exe"
    if not py.exists():
        raise SystemExit(f"没有 {py}")
    ver = _pyinstaller_version(py)
    src = _fetch_sdist(ver)
    env = os.environ.copy()
    env["PATH"] = str(_gcc_bin()) + os.pathsep + env.get("PATH", "")
    subprocess.check_call(
        [str(py), "waf", "distclean", "all", "--gcc", "--target-arch=64bit"],
        cwd=src / "bootloader",
        env=env,
    )
    subprocess.check_call([str(py), "-m", "pip", "install", "--no-deps", "--force-reinstall", "-q", str(src)])
    built = src / "PyInstaller" / "bootloader" / "Windows-64bit-intel" / "runw.exe"
    out = subprocess.check_output(
        [str(py), "-c", "import PyInstaller,os;print(os.path.join(os.path.dirname(PyInstaller.__file__),"
         "'bootloader','Windows-64bit-intel','runw.exe'))"],
        text=True,
    ).strip()
    a = hashlib.sha256(built.read_bytes()).hexdigest()
    b = hashlib.sha256(Path(out).read_bytes()).hexdigest()
    if a != b:
        raise SystemExit("装回 venv 的 bootloader 与自编译的不一致")
    # build_release.py 靠这个确认打包用的不是官方 bootloader
    (venv / "wt_bootloader.sha256").write_text(a, encoding="ascii")
    print(f"OK: PyInstaller {ver} 自编译 bootloader 已装入 {venv.name}（runw.exe sha256 {a[:16]}…）")


if __name__ == "__main__":
    main()
