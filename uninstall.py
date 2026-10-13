"""应用内卸载：本进程清快捷方式与配置，程序文件交给 Inno 的卸载程序 unins000.exe 删。"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import autostart
import desktop_shortcut
import store
import updater

_DETACHED = 0x00000008
_NEW_GROUP = 0x00000200


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


def build_manifest() -> list[Path]:
    """本进程直接删的：快捷方式、配置目录、老版本单文件副本目录。"""
    paths: list[Path] = []
    paths.extend(_shortcut_paths())
    paths.append(store.user_data_dir())
    paths.append(store.legacy_install_dir())
    return _unique_paths(paths)


def _uninstaller() -> Path | None:
    cur = updater.current_exe_path()
    if cur is None:
        return None
    p = cur.parent / "unins000.exe"
    return p if p.is_file() else None


def summary_lines() -> list[str]:
    lines = [
        "将删除：",
        "· 桌面与开始菜单快捷方式",
        "· 开机自启动项（如有）",
        "· 日程、备忘、设置与皮肤配置",
    ]
    cur = updater.current_exe_path()
    if _uninstaller() is not None:
        lines.append("· 程序文件（由系统卸载程序移除）")
    elif cur is not None:
        lines.append("· 程序文件夹需要你手动删除（卸载后会自动打开）：")
        lines.append(f"  {cur.parent}")
    lines.append("")
    lines.append("此操作不可恢复，确定卸载吗？")
    return lines


def _remove_path(path: Path) -> None:
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        elif path.exists() or path.is_symlink():
            path.unlink(missing_ok=True)
    except OSError:
        pass


def request_and_exit() -> None:
    """清掉用户数据后退出；安装版拉起 unins000.exe 删程序文件，绿色版打开所在文件夹让用户自己删。"""
    cur = updater.current_exe_path()
    if cur is None:
        raise RuntimeError("开发模式不支持应用内卸载")
    unins = _uninstaller()
    try:
        autostart._clear_run_key()
    except OSError:
        pass
    for p in build_manifest():
        _remove_path(p)
    if unins is not None:
        env = os.environ.copy()
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        subprocess.Popen(
            [str(unins), "/VERYSILENT", "/SUPPRESSMSGBOXES", "/NORESTART"],
            cwd=str(Path(os.environ.get("TEMP") or unins.parent)),
            env=env,
            close_fds=True,
            creationflags=_DETACHED | _NEW_GROUP,
        )
    else:
        try:
            os.startfile(str(cur.parent))  # noqa: S606
        except OSError:
            pass
    os._exit(0)
