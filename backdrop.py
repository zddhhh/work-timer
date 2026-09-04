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
# 亮度猛跳时（最小化露出墙纸）用更中性的门槛，避免卡在滞回里
LUMA_SOFT = 148.0

# 一次 BitBlt 足够；多次 1px 截屏会被 DWM 拖成上百毫秒
_MAX_W = 640
_MAX_H = 280


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

    def stats(
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
    ) -> tuple[float, tuple[int, int, int]] | None:
        if rw < 2 or rh < 2 or rw > _MAX_W or rh > _MAX_H:
            return None
        if not self._ensure(hdc_screen):
            return None
        if not gdi32.BitBlt(self._hdc_mem, 0, 0, rw, rh, hdc_screen, left, top, SRCCOPY):
            return None
        buf = (ctypes.c_ubyte * (_MAX_W * _MAX_H * 4)).from_address(self._bits.value)
        luma_sum = 0.0
        rs = gs = bs = 0.0
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
                luma_sum += 0.2126 * r + 0.7152 * g + 0.0722 * b
                rs += r
                gs += g
                bs += b
                count += 1
        if count <= 0:
            return None
        rgb = (int(rs / count), int(gs / count), int(bs / count))
        return luma_sum / count, rgb

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
        got = self.stats(hdc_screen, left, top, rw, rh, win_x, win_y, win_w, win_h)
        return None if got is None else got[0]


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


def sample_around(x: int, y: int, w: int, h: int, *, strip: int = 8) -> tuple[float, tuple[int, int, int]] | None:
    """采窗周 + 窗下的亮度与平均色。"""
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
        around = _SAMPLER.stats(hdc, left, top, rw, rh, x, y, w, h)
        ix = x + max(4, w // 5)
        iy = y + max(4, h // 5)
        iw = max(4, w - 2 * max(4, w // 5))
        ih = max(4, h - 2 * max(4, h // 5))
        behind = _SAMPLER.stats(hdc, ix, iy, iw, ih, -1, -1, 0, 0)
        if around is None:
            return behind
        if behind is None:
            return around
        la, ca = around
        lb, cb = behind
        luma = lb * 0.7 + la * 0.3
        rgb = (
            int(cb[0] * 0.7 + ca[0] * 0.3),
            int(cb[1] * 0.7 + ca[1] * 0.3),
            int(cb[2] * 0.7 + ca[2] * 0.3),
        )
        return luma, rgb
    finally:
        user32.ReleaseDC(None, hdc)


def sample_luma_around(x: int, y: int, w: int, h: int, *, strip: int = 8) -> float | None:
    """采窗周 + 窗下（分层窗通常不进 BitBlt，能看到背后应用/墙纸）。"""
    got = sample_around(x, y, w, h, strip=strip)
    return None if got is None else got[0]


def classify_surface(luma: float, current: str, *, soft: bool = False) -> str:
    """返回 dark / light。soft=亮度猛跳时跳过滞回。"""
    if soft:
        return "light" if luma >= LUMA_SOFT else "dark"
    cur = current if current in ("dark", "light") else "dark"
    if cur == "dark":
        return "light" if luma >= LUMA_TO_LIGHT else "dark"
    return "dark" if luma <= LUMA_TO_DARK else "light"
