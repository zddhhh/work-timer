"""单实例：已在跑就唤起窗口，不再开一份。"""
from __future__ import annotations

import ctypes
import sys
import time
from ctypes import wintypes

_MUTEX_NAME = "Local\\WorkTimer.SingleInstance"
_CLASS_NAME = "WorkTimerLayeredWnd"
_ERROR_ALREADY_EXISTS = 183
_SW_RESTORE = 9
_HWND_TOPMOST = -1
_SWP_NOSIZE = 0x0001
_SWP_NOMOVE = 0x0002
_SWP_SHOWWINDOW = 0x0040

_mutex_handle = None


def _activate_existing() -> bool:
    user32 = ctypes.windll.user32
    user32.FindWindowW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR]
    user32.FindWindowW.restype = wintypes.HWND
    hwnd = 0
    for _ in range(20):
        hwnd = user32.FindWindowW(_CLASS_NAME, None)
        if hwnd:
            break
        time.sleep(0.08)
    if not hwnd:
        return False
    user32.ShowWindow(hwnd, _SW_RESTORE)
    user32.SetWindowPos(
        hwnd,
        _HWND_TOPMOST,
        0,
        0,
        0,
        0,
        _SWP_NOMOVE | _SWP_NOSIZE | _SWP_SHOWWINDOW,
    )
    try:
        user32.AllowSetForegroundWindow(-1)
    except Exception:
        pass
    user32.SetForegroundWindow(hwnd)
    return True


def claim() -> bool:
    """True 表示本进程继续跑；False 表示已有实例并已唤起。"""
    global _mutex_handle
    # 源码模式用独立的 mutex：开发时能发现自己多开，又不会和用户机器上正在跑的 exe 互斥
    name = _MUTEX_NAME if getattr(sys, "frozen", False) else _MUTEX_NAME + ".dev"
    kernel32 = ctypes.windll.kernel32
    kernel32.CreateMutexW.restype = wintypes.HANDLE
    kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    handle = kernel32.CreateMutexW(None, False, name)
    if not handle:
        return True
    err = kernel32.GetLastError()
    if err == _ERROR_ALREADY_EXISTS:
        kernel32.CloseHandle(handle)
        _activate_existing()
        return False
    _mutex_handle = handle
    return True
