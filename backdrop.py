"""采样窗口周围屏幕亮度，供「自适应」外观切换深/浅字色。"""
from __future__ import annotations

import ctypes
import os
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0
SM_CXSCREEN = 0
SM_CYSCREEN = 1
SPI_GETDESKWALLPAPER = 0x0073

# 滞回加宽：减少临界区来回翻
LUMA_TO_LIGHT = 188.0
LUMA_TO_DARK = 105.0

# 一次 BitBlt 足够；多次 1px 截屏会被 DWM 拖成上百毫秒
_MAX_W = 320
_MAX_H = 160


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", wintypes.DWORD * 1)]


class _RingSampler:
    """复用一块 DIB，整圈一次截屏。"""

    def __init__(self) -> None:
        self._hdc_mem = 0
        self._hbmp = 0
        self._old = 0
        self._bits = ctypes.c_void_p()

    def _ensure(self, hdc_screen) -> bool:
        if self._hdc_mem:
            return True
        hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
        if not hdc_mem:
            return False
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = _MAX_W
        bmi.bmiHeader.biHeight = -_MAX_H
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bits_ptr = ctypes.c_void_p()
        hbmp = gdi32.CreateDIBSection(
            hdc_mem, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits_ptr), None, 0
        )
        if not hbmp or not bits_ptr.value:
            if hbmp:
                gdi32.DeleteObject(hbmp)
            gdi32.DeleteDC(hdc_mem)
            return False
        self._hdc_mem = hdc_mem
        self._hbmp = hbmp
        self._bits = bits_ptr
        self._old = gdi32.SelectObject(hdc_mem, hbmp)
        return True

    def luma(
        self,
        hdc_screen,
        left: int,
        top: int,
        rw: int,
        rh: int,
        win_x: int,
        win_y: int,
        win_w: int,
        win_h: int,
    ) -> float | None:
        if rw < 2 or rh < 2 or rw > _MAX_W or rh > _MAX_H:
            return None
        if not self._ensure(hdc_screen):
            return None
        if not gdi32.BitBlt(self._hdc_mem, 0, 0, rw, rh, hdc_screen, left, top, SRCCOPY):
            return None
        buf = (ctypes.c_ubyte * (_MAX_W * _MAX_H * 4)).from_address(self._bits.value)
        total = 0.0
        count = 0
        step = 2
        inner_l = win_x - left
        inner_t = win_y - top
        inner_r = inner_l + win_w
        inner_b = inner_t + win_h
        for y in range(0, rh, step):
            row = y * _MAX_W * 4
            for x in range(0, rw, step):
                if inner_l <= x < inner_r and inner_t <= y < inner_b:
                    continue
                i = row + x * 4
                b, g, r = buf[i], buf[i + 1], buf[i + 2]
                total += 0.2126 * r + 0.7152 * g + 0.0722 * b
                count += 1
        if count <= 0:
            return None
        return total / count


_SAMPLER = _RingSampler()


def wallpaper_token() -> tuple:
    """墙纸路径 + 文件指纹；换纸或幻灯片改文件时会变。"""
    buf = ctypes.create_unicode_buffer(1024)
    if not user32.SystemParametersInfoW(SPI_GETDESKWALLPAPER, 1024, buf, 0):
        return ("", 0, 0)
    path = buf.value or ""
    if not path:
        return ("", 0, 0)
    try:
        st = os.stat(path)
        mtime_ns = int(getattr(st, "st_mtime_ns", int(st.st_mtime * 1e9)))
        return (path, mtime_ns, st.st_size)
    except OSError:
        return (path, 0, 0)


def sample_luma_around(x: int, y: int, w: int, h: int, *, strip: int = 8) -> float | None:
    """一次截取窗口外扩一圈，只平均圈上的像素。"""
    sw = int(user32.GetSystemMetrics(SM_CXSCREEN))
    sh = int(user32.GetSystemMetrics(SM_CYSCREEN))
    x, y, w, h = int(x), int(y), int(w), int(h)
    pad = max(4, int(strip))
    left = max(0, x - pad)
    top = max(0, y - pad)
    right = min(sw, x + w + pad)
    bottom = min(sh, y + h + pad)
    rw, rh = right - left, bottom - top
    if rw < 2 or rh < 2:
        return None
    hdc = user32.GetDC(None)
    if not hdc:
        return None
    try:
        return _SAMPLER.luma(hdc, left, top, rw, rh, x, y, w, h)
    finally:
        user32.ReleaseDC(None, hdc)


def classify_surface(luma: float, current: str) -> str:
    """返回 dark / light。带滞回，current 为当前判定。"""
    cur = current if current in ("dark", "light") else "dark"
    if cur == "dark":
        return "light" if luma >= LUMA_TO_LIGHT else "dark"
    return "dark" if luma <= LUMA_TO_DARK else "light"
