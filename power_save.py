"""未接电源或系统节电时少画几帧。

接电时一帧画得完，看不出重绘。节电降频后，同样的满速重绘会跨过屏幕刷新，
画面就花、操作就顿。倒计时和记录仍按原来的节奏走，只是少做画不完的那几帧。
"""
from __future__ import annotations

import ctypes
import sys
import time

# 节电时动画和弹窗重绘的上限。再高，降频的 CPU 经常一帧画不完。
BATTERY_HZ = 20.0
_CACHE_S = 2.0
_at = 0.0
_on = False


class _PowerStatus(ctypes.Structure):
    _fields_ = [
        ("ACLineStatus", ctypes.c_byte),
        ("BatteryFlag", ctypes.c_byte),
        ("BatteryLifePercent", ctypes.c_byte),
        ("SystemStatusFlag", ctypes.c_byte),
        ("BatteryLifeTime", ctypes.c_uint),
        ("BatteryFullLifeTime", ctypes.c_uint),
    ]


def cap_hz(hz: float, saving: bool, limit: float = BATTERY_HZ) -> float:
    """节电时把帧率收到上限以内。0 表示这一帧本来就不画。"""
    if hz <= 0 or not saving:
        return float(hz)
    return min(float(hz), float(limit))


def saving() -> bool:
    """未接电，或 Windows 节电已打开。桌面机报未知时不当成节电。"""
    global _at, _on
    now = time.monotonic()
    if now - _at < _CACHE_S:
        return _on
    _at = now
    _on = _read()
    return _on


def frame_hz(hz: float) -> float:
    return cap_hz(hz, saving())


def _read() -> bool:
    if sys.platform != "win32":
        return False
    status = _PowerStatus()
    try:
        kernel = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel.GetSystemPowerStatus.argtypes = [ctypes.POINTER(_PowerStatus)]
        kernel.GetSystemPowerStatus.restype = ctypes.c_bool
        ok = kernel.GetSystemPowerStatus(ctypes.byref(status))
    except (AttributeError, OSError):
        return False
    if not ok:
        return False
    # 0 未接电，255 未知。SystemStatusFlag 1 是系统节电。
    if status.ACLineStatus == 0:
        return True
    return status.SystemStatusFlag == 1
