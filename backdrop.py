"""采样窗口周围屏幕亮度，供「自适应」外观切换深/浅字色。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

SRCCOPY = 0x00CC0020
BI_RGB = 0
DIB_RGB_COLORS = 0
SM_CXSCREEN = 0
SM_CYSCREEN = 1

# 滞回加宽：减少临界区来回翻
LUMA_TO_LIGHT = 188.0
LUMA_TO_DARK = 105.0


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


def _rect_luma(hdc_screen, left: int, top: int, width: int, height: int) -> tuple[float, int] | None:
    if width < 2 or height < 2:
        return None
    hdc_mem = gdi32.CreateCompatibleDC(hdc_screen)
    if not hdc_mem:
        return None
    bits_ptr = ctypes.c_void_p()
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32
    bmi.bmiHeader.biCompression = BI_RGB
    hbmp = gdi32.CreateDIBSection(
        hdc_mem, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits_ptr), None, 0
    )
    if not hbmp or not bits_ptr.value:
        if hbmp:
            gdi32.DeleteObject(hbmp)
        gdi32.DeleteDC(hdc_mem)
        return None
    old = gdi32.SelectObject(hdc_mem, hbmp)
    ok = gdi32.BitBlt(hdc_mem, 0, 0, width, height, hdc_screen, left, top, SRCCOPY)
    total = 0.0
    count = 0
    if ok:
        # 步进取样，避免全量扫
        step = max(2, min(width, height) // 8)
        buf = (ctypes.c_ubyte * (width * height * 4)).from_address(bits_ptr.value)
        for y in range(0, height, step):
            row = y * width * 4
            for x in range(0, width, step):
                i = row + x * 4
                b, g, r = buf[i], buf[i + 1], buf[i + 2]
                total += 0.2126 * r + 0.7152 * g + 0.0722 * b
                count += 1
    gdi32.SelectObject(hdc_mem, old)
    gdi32.DeleteObject(hbmp)
    gdi32.DeleteDC(hdc_mem)
    if count <= 0:
        return None
    return total / count, count


def sample_luma_around(x: int, y: int, w: int, h: int, *, strip: int = 10) -> float | None:
    """采窗口四周条带平均亮度（不采窗内，避免采到自己）。"""
    sw = int(user32.GetSystemMetrics(SM_CXSCREEN))
    sh = int(user32.GetSystemMetrics(SM_CYSCREEN))
    x, y, w, h = int(x), int(y), int(w), int(h)
    strip = max(4, int(strip))
    rects: list[tuple[int, int, int, int]] = []
    # 上
    if y > 0:
        t = max(0, y - strip)
        rects.append((max(0, x), t, min(w, sw - max(0, x)), y - t))
    # 下
    if y + h < sh:
        rects.append((max(0, x), y + h, min(w, sw - max(0, x)), min(strip, sh - (y + h))))
    # 左
    if x > 0:
        l = max(0, x - strip)
        rects.append((l, max(0, y), x - l, min(h, sh - max(0, y))))
    # 右
    if x + w < sw:
        rects.append((x + w, max(0, y), min(strip, sw - (x + w)), min(h, sh - max(0, y))))

    hdc = user32.GetDC(None)
    if not hdc:
        return None
    try:
        acc = 0.0
        n = 0
        for left, top, rw, rh in rects:
            if rw < 2 or rh < 2:
                continue
            got = _rect_luma(hdc, left, top, rw, rh)
            if got is None:
                continue
            luma, count = got
            acc += luma * count
            n += count
        if n <= 0:
            return None
        return acc / n
    finally:
        user32.ReleaseDC(None, hdc)


def classify_surface(luma: float, current: str) -> str:
    """返回 dark / light。带滞回，current 为当前判定。"""
    cur = current if current in ("dark", "light") else "dark"
    if cur == "dark":
        return "light" if luma >= LUMA_TO_LIGHT else "dark"
    return "dark" if luma <= LUMA_TO_DARK else "light"
