"""应用内卸载：清快捷方式、配置、副本 exe，helper 等主进程退出后删文件。"""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import autostart
import desktop_shortcut
import store
import updater

_MANIFEST_PREFIX = "WorkTimer_uninstall_"
_WAIT_SEC = 90
_DETACHED = 0x00000008
_NEW_GROUP = 0x00000200
_CREATE_NO_WINDOW = 0x08000000


def _arg_value(argv: list[str], name: str) -> str:
    try:
        i = argv.index(name)
    except ValueError:
        return ""
    if i + 1 >= len(argv):
        return ""
    return argv[i + 1]


def _unique_paths(paths: list[Path]) -> list[Path]:
    out: list[Path] = []
    seen: set[str] = set()
    for p in paths:
        key = os.path.normcase(str(p))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out


def _exe_sidecars(exe: Path) -> list[Path]:
    base = str(exe)
    return [Path(base + ".new"), Path(base + ".old")]


def _shortcut_paths() -> list[Path]:
    out: list[Path] = []
    desktop = desktop_shortcut._desktop_dir()
    if desktop is not None:
        out.append(desktop / desktop_shortcut._LNK_NAME)
    programs = desktop_shortcut._start_menu_programs_dir()
    if programs is not None:
        out.append(programs / desktop_shortcut._LNK_NAME)
    lnk = autostart._lnk_path()
    if lnk is not None:
        out.append(lnk)
    return out


def _exe_paths() -> list[Path]:
    out: list[Path] = []
    cur = updater.current_exe_path()
    if cur is not None:
        out.append(cur)
        out.extend(_exe_sidecars(cur))
    stable = store.install_exe_path()
    if stable.exists():
        out.append(stable.resolve())
        out.extend(_exe_sidecars(stable))
    return out


def build_manifest() -> list[Path]:
    """待删除路径：快捷方式、配置目录、安装目录、exe 及 OTA 旁路文件。"""
    paths: list[Path] = []
    paths.extend(_shortcut_paths())
    paths.append(store.user_data_dir())
    paths.append(store.install_dir())
    paths.extend(_exe_paths())
    return _unique_paths(paths)


def summary_lines() -> list[str]:
    lines = [
        "将删除：",
        "· 桌面与开始菜单快捷方式",
        "· 开机自启动项（如有）",
        "· 日程、备忘、设置与皮肤配置",
        "· 程序文件（含本机自动复制的副本）",
    ]
    cur = updater.current_exe_path()
    if cur is not None:
        lines.append(f"· {cur}")
    stable = store.install_exe_path()
    try:
        if stable.exists() and cur is not None and stable.resolve() != cur.resolve():
            lines.append(f"· {stable}")
    except OSError:
        if stable.exists():
            lines.append(f"· {stable}")
    lines.append("")
    lines.append("此操作不可恢复，确定卸载吗？")
    return lines


def _write_manifest(pid: int, paths: list[Path]) -> Path:
    p = Path(tempfile.gettempdir()) / f"{_MANIFEST_PREFIX}{pid}.txt"
    text = "\n".join(str(x) for x in paths)
    p.write_text(text, encoding="utf-8")
    return p


def _spawn_helper(exe: Path, pid: int, manifest: Path) -> None:
    env = os.environ.copy()
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = 0
    subprocess.Popen(
        [
            str(exe),
            "--uninstall",
            "--wait-pid",
            str(pid),
            "--manifest",
            str(manifest),
        ],
        cwd=str(exe.parent),
        env=env,
        close_fds=True,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        startupinfo=si,
        creationflags=_DETACHED | _NEW_GROUP | _CREATE_NO_WINDOW,
    )


def _remove_path(path: Path) -> None:
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists() or path.is_symlink():
            path.unlink(missing_ok=True)
    except OSError:
        pass


def _run_helper(argv: list[str]) -> bool:
    pid_s = _arg_value(argv, "--wait-pid")
    manifest_s = _arg_value(argv, "--manifest")
    try:
        pid = int(pid_s)
    except ValueError:
        pid = 0
    manifest = Path(manifest_s) if manifest_s else None
    if manifest is None or not manifest.is_file():
        return True
    deadline = time.monotonic() + _WAIT_SEC
    while updater._pid_running(pid):
        if time.monotonic() > deadline:
            break
        time.sleep(0.35)
    time.sleep(0.6)
    try:
        lines = manifest.read_text(encoding="utf-8").splitlines()
    except OSError:
        lines = []
    for line in lines:
        s = line.strip()
        if not s:
            continue
        _remove_path(Path(s))
    _remove_path(manifest)
    return True


def run_if_requested(argv: list[str] | None = None) -> bool:
    args = list(sys.argv if argv is None else argv)
    if "--uninstall" not in args:
        return False
    return _run_helper(args)


def request_and_exit() -> None:
    """当前进程发起卸载并立即退出；由 helper 进程收尾删 exe。"""
    if not getattr(sys, "frozen", False):
        raise RuntimeError("开发模式不支持应用内卸载")
    exe = updater.current_exe_path()
    if exe is None:
        raise RuntimeError("找不到程序文件")
    pid = os.getpid()
    try:
        autostart._clear_run_key()
    except OSError:
        pass
    manifest = _write_manifest(pid, build_manifest())
    _spawn_helper(exe, pid, manifest)
    os._exit(0)
