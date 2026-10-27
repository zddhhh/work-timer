# 一键打包：PyInstaller 目录版 + Inno Setup 安装包，产物进 release/，不碰 dist/（dist 留给本机旧版做 OTA 测试）
# 用法: .\.venv\Scripts\python.exe scripts\build_release.py            主包 + Win7 包
#       .\.venv\Scripts\python.exe scripts\build_release.py main       只打主包（.venv，Python 3.12，Win8.1+）
#       .\.venv\Scripts\python.exe scripts\build_release.py win7       只打 Win7 包（.venv38，Python 3.8）

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DIST_NAME = "WorkTimer"
OUT_DIR = ROOT / "release"
ISS = ROOT / "installer" / "WorkTimer.iss"

HIDDEN_IMPORTS = [
    "themes", "changelog", "backdrop", "boot_ok", "ornaments", "schedules", "memos", "worklog", "attachments",
    "PIL.ImageTk", "autostart", "desktop_shortcut", "single_instance", "key_hide", "uninstall", "store",
    "layered_win", "festival", "kinetic", "meow", "mines", "golf", "pool", "flex_time", "hydrate", "activity", "activity_chart", "feedback", "updater", "win_drop", "tkinterdnd2",
    "suofen", "tally_bubble", "card_ui", "worklog_ui", "schedule_ui", "update_ui", "PIL.ImageStat",
    "qrcode", "qrcode.image.pil",
    "version", "share",
]


def _version_ns() -> dict:
    ns: dict = {}
    exec((ROOT / "version.py").read_text(encoding="utf-8"), ns)
    return ns


VARIANTS = {
    "main": {"venv": ROOT / ".venv", "asset": _version_ns()["MAIN_SETUP"], "win7": False},
    "win7": {"venv": ROOT / ".venv38", "asset": _version_ns()["WIN7_SETUP"], "win7": True},
}


def setup_path(variant: str) -> Path:
    return OUT_DIR / VARIANTS[variant]["asset"]


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


def _version_file() -> Path:
    """exe 属性里的产品名/公司/版本。没有这些元数据的 PyInstaller 包更容易被杀软启发式判可疑。"""
    ver = str(_version_ns()["APP_VERSION"])
    nums = [int(x) for x in ver.split(".")[:4] if x.isdigit()]
    nums += [0] * (4 - len(nums))
    tup = tuple(nums)
    dotted = ".".join(str(n) for n in tup)
    fields = {
        "CompanyName": "mdslanruo",
        "FileDescription": "WorkTimer 下班倒计时",
        "FileVersion": dotted,
        "InternalName": DIST_NAME,
        "LegalCopyright": "© mdslanruo",
        "OriginalFilename": f"{DIST_NAME}.exe",
        "ProductName": "WorkTimer 下班倒计时",
        "ProductVersion": ver,
    }
    strings = ",\n".join(f"            StringStruct({k!r}, {v!r})" for k, v in fields.items())
    text = f"""VSVersionInfo(
  ffi=FixedFileInfo(filevers={tup}, prodvers={tup}, mask=0x3f, flags=0x0, OS=0x40004,
                    fileType=0x1, subtype=0x0, date=(0, 0)),
  kids=[
    StringFileInfo([
        StringTable('080404b0', [
{strings}
        ])
    ]),
    VarFileInfo([VarStruct('Translation', [2052, 1200])])
  ]
)
"""
    out = ROOT / "build" / "_bundle" / "version_info.txt"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text, encoding="utf-8")
    return out


def _check_bootloader(venv: Path, py: Path) -> None:
    """官方预编译 bootloader 被大量恶意样本复用，杀软误报多；必须是 build_bootloader.py 编的。"""
    runw = subprocess.check_output(
        [str(py), "-c", "import PyInstaller,os;print(os.path.join(os.path.dirname(PyInstaller.__file__),"
         "'bootloader','Windows-64bit-intel','runw.exe'))"],
        text=True,
    ).strip()
    got = hashlib.sha256(Path(runw).read_bytes()).hexdigest()
    marker = venv / "wt_bootloader.sha256"
    want = marker.read_text(encoding="ascii").strip() if marker.exists() else ""
    if got != want:
        raise SystemExit(
            f"{venv.name} 里的 bootloader 不是自编译的（升级过 PyInstaller？）\n"
            f"先跑: python scripts\\build_bootloader.py {venv.name}"
        )


# 安装包认这三份文件才把新版本换上去。launcher/launcher.c、WorkTimer.iss 里同一份名单。
_RUNTIME_DLLS = ("vcruntime140.dll", "vcruntime140_1.dll")


def _gcc_bin() -> Path:
    found = shutil.which("gcc")
    if found:
        return Path(found).parent
    pkgs = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    for d in sorted(pkgs.glob("BrechtSanders.WinLibs.POSIX.MSVCRT_*")):
        b = d / "mingw64" / "bin"
        if (b / "gcc.exe").exists():
            return b
    raise SystemExit("找不到 gcc：winget install BrechtSanders.WinLibs.POSIX.MSVCRT")


def compile_launcher() -> Path:
    """启动器静态链接，不依赖 vcruntime140，更新把运行库换坏了它自己还能起来。"""
    gcc_dir = _gcc_bin()
    out = ROOT / "launcher" / "WorkTimer.exe"
    res = ROOT / "launcher" / "launcher.res"
    subprocess.check_call(
        [str(gcc_dir / "windres"), "-O", "coff", "-o", str(res), str(ROOT / "launcher" / "launcher.rc")],
        cwd=ROOT / "launcher",
    )
    subprocess.check_call(
        [
            str(gcc_dir / "gcc.exe"),
            "-Os", "-s", "-static", "-static-libgcc", "-mwindows",
            "-Wl,--subsystem,windows:6.1",
            "-o", str(out),
            str(ROOT / "launcher" / "launcher.c"),
            str(res),
            "-luser32", "-lkernel32",
        ],
        cwd=ROOT / "launcher",
    )
    return out


def _require_runtime(dist: Path, win7: bool) -> None:
    internal = dist / "_internal"
    if win7:
        names = ("python38.dll", "vcruntime140.dll")
    else:
        names = ("python312.dll", *_RUNTIME_DLLS)
    missing = [name for name in names if not (internal / name).is_file()]
    if missing:
        raise SystemExit(f"运行库缺 {', '.join(missing)}，安装包不会把这一版换上去")


def _iscc() -> Path:
    found = shutil.which("ISCC")
    if found:
        return Path(found)
    for base in (os.environ.get("LOCALAPPDATA", ""), os.environ.get("ProgramFiles(x86)", ""), os.environ.get("ProgramFiles", "")):
        for p in (Path(base) / "Programs" / "Inno Setup 6" / "ISCC.exe", Path(base) / "Inno Setup 6" / "ISCC.exe"):
            if p.exists():
                return p
    raise SystemExit("找不到 ISCC.exe：winget install JRSoftware.InnoSetup")


def _clean_build_env() -> dict[str, str]:
    """构建只能从当前 Python 和系统目录找 DLL，不能捎上外部 Conda 运行库。"""
    env = dict(os.environ)
    blocked = ("miniforge", "miniconda", "anaconda", "mambaforge")
    paths = [
        entry for entry in env.get("PATH", "").split(os.pathsep)
        if entry and not any(name in entry.lower() for name in blocked)
    ]
    env["PATH"] = os.pathsep.join(paths)
    env["PYTHONNOUSERSITE"] = "1"
    for key in ("CONDA_PREFIX", "CONDA_DEFAULT_ENV", "CONDA_PROMPT_MODIFIER", "CONDA_SHLVL"):
        env.pop(key, None)
    return env


def build(variant: str) -> Path:
    cfg = VARIANTS[variant]
    venv: Path = cfg["venv"]
    py = venv / "Scripts" / "python.exe"
    if not py.exists():
        raise SystemExit(f"没有 {py}")
    _check_bootloader(venv, py)
    work = ROOT / "build" / variant
    app_dir = work / "dist"
    shutil.rmtree(work, ignore_errors=True)
    (ROOT / f"{DIST_NAME}.spec").unlink(missing_ok=True)

    cmd = [
        str(py), "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed",
        # 目录版：单文件版每次启动要往 %TEMP% 解压一整套 Python 再执行，是杀软最敏感的行为之一
        "--onedir",
        "--noupx",
        "--version-file", str(_version_file()),
        "--icon", str(ROOT / "assets" / "app.ico"),
        "--name", DIST_NAME,
        "--distpath", str(app_dir),
        "--workpath", str(work / "pyi"),
        "--specpath", str(work),
        "--add-data", f"{_bundle_update_defaults()};.",
        "--add-data", f"{ROOT / 'themes.json'};.",
        "--add-data", f"{ROOT / 'assets'};assets",
        "--add-data", f"{ROOT / 'docs' / '更新说明.md'};docs",
        "--collect-all", "tkinterdnd2",
    ]
    for mod in HIDDEN_IMPORTS:
        cmd += ["--hidden-import", mod]
    cmd.append(str(ROOT / "main.py"))
    subprocess.check_call(cmd, cwd=ROOT, env=_clean_build_env())
    _require_runtime(app_dir / DIST_NAME, cfg["win7"])
    leaked = sorted((app_dir / DIST_NAME / "_internal").glob("api-ms-win-*.dll"))
    if leaked:
        names = ", ".join(p.name for p in leaked[:5])
        raise SystemExit(f"打包环境混入了外部 Windows 兼容 DLL：{names}")

    OUT_DIR.mkdir(exist_ok=True)
    out = setup_path(variant)
    out.unlink(missing_ok=True)
    iscc = [
        str(_iscc()), "/Q",
        f"/DAppVersion={_version_ns()['APP_VERSION']}",
        f"/DSourceDir={app_dir / DIST_NAME}",
        f"/DOutputDir={OUT_DIR}",
        f"/DOutputName={out.stem}",
    ]
    if cfg["win7"]:
        iscc.append("/DWin7")
    iscc.append(str(ISS))
    subprocess.check_call(iscc, cwd=ISS.parent)
    print(f"OK: {out}  {out.stat().st_size / (1024 * 1024):.1f} MB")
    return out


def main() -> None:
    which = sys.argv[1:] or list(VARIANTS)
    bad = [w for w in which if w not in VARIANTS]
    if bad:
        raise SystemExit(f"不认识的包：{bad}，可选 {list(VARIANTS)}")
    try:
        (OUT_DIR / f"{DIST_NAME}.exe").unlink(missing_ok=True)  # 单文件时代的产物
    except OSError:
        pass
    compile_launcher()
    for w in which:
        build(w)
    print("已写入 release/，未改动 dist/。")


if __name__ == "__main__":
    main()
