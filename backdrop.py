"""采样窗口周围屏幕亮度，供「自适应」外观切换深/浅字色。"""
from __future__ import annotations

import ctypes
import os
import threading
from ctypes import wintypes

from PIL import Image, ImageStat

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


# 与 layered_win 保持一致的类型声明（ctypes 的 windll 函数对象全进程共享，两边必须同形）
_HANDLE = wintypes.HANDLE
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.GetSystemMetrics.argtypes = [ctypes.c_int]
user32.GetSystemMetrics.restype = ctypes.c_int
gdi32.CreateCompatibleDC.argtypes = [wintypes.HDC]
gdi32.CreateCompatibleDC.restype = wintypes.HDC
gdi32.CreateDIBSection.argtypes = [
    wintypes.HDC, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), _HANDLE, wintypes.DWORD,
]
gdi32.CreateDIBSection.restype = _HANDLE
gdi32.SelectObject.argtypes = [wintypes.HDC, _HANDLE]
gdi32.SelectObject.restype = _HANDLE
gdi32.DeleteObject.argtypes = [_HANDLE]
gdi32.DeleteObject.restype = wintypes.BOOL
gdi32.DeleteDC.argtypes = [wintypes.HDC]
gdi32.DeleteDC.restype = wintypes.BOOL
gdi32.BitBlt.argtypes = [
    wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
]
gdi32.BitBlt.restype = wintypes.BOOL


def _monitor_rect(x: int, y: int) -> tuple[int, int, int, int]:
    """窗口中心所在显示器的物理范围；副屏（负坐标/超主屏）也能正确采样。"""
    try:
        import layered_win  # 复用同一套 POINT/MONITORINFO 声明，避免 argtypes 冲突

        r = layered_win.monitor_rect_at(int(x), int(y))
        if r is not None:
            return int(r.left), int(r.top), int(r.right), int(r.bottom)
    except Exception:
        pass
    return 0, 0, int(user32.GetSystemMetrics(SM_CXSCREEN)), int(user32.GetSystemMetrics(SM_CYSCREEN))


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

    def capture(self, hdc_screen, left: int, top: int, rw: int, rh: int) -> Image.Image | None:
        if rw < 2 or rh < 2 or rw > _MAX_W or rh > _MAX_H:
            return None
        if not self._ensure(hdc_screen):
            return None
        # BitBlt 会等一次 DWM 合成（约 16ms），整块只截这一次
        if not gdi32.BitBlt(self._hdc_mem, 0, 0, rw, rh, hdc_screen, left, top, SRCCOPY):
            return None
        raw = ctypes.string_at(self._bits.value, _MAX_W * rh * 4)
        return Image.frombuffer("RGB", (_MAX_W, rh), raw, "raw", "BGRX", 0, 1).crop((0, 0, rw, rh))


def _box_sums(img: Image.Image, box: tuple[int, int, int, int]) -> tuple[int, float, float, float]:
    """框内像素数与 R/G/B 总和；框会先裁到图内。"""
    l, t, r, b = box
    l, t = max(0, l), max(0, t)
    r, b = min(img.width, r), min(img.height, b)
    if r <= l or b <= t:
        return 0, 0.0, 0.0, 0.0
    s = ImageStat.Stat(img.crop((l, t, r, b))).sum
    return (r - l) * (b - t), s[0], s[1], s[2]


def _mean(n: int, rs: float, gs: float, bs: float) -> tuple[float, tuple[int, int, int]] | None:
    if n <= 0:
        return None
    luma = (0.2126 * rs + 0.7152 * gs + 0.0722 * bs) / n
    return luma, (int(rs / n), int(gs / n), int(bs / n))


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
    x, y, w, h = int(x), int(y), int(w), int(h)
    ml, mt, mr, mb = _monitor_rect(x + w // 2, y + h // 2)
    pad = max(4, int(strip))
    left = max(ml, x - pad)
    top = max(mt, y - pad)
    right = min(mr, x + w + pad)
    bottom = min(mb, y + h + pad)
    rw, rh = right - left, bottom - top
    if rw < 2 or rh < 2:
        return None
    hdc = user32.GetDC(None)
    if not hdc:
        return None
    try:
        img = _SAMPLER.capture(hdc, left, top, rw, rh)
    finally:
        user32.ReleaseDC(None, hdc)
    if img is None:
        return None
    wx, wy = x - left, y - top
    full = _box_sums(img, (0, 0, rw, rh))
    win = _box_sums(img, (wx, wy, wx + w, wy + h))
    around = _mean(*(a - b for a, b in zip(full, win)))
    mx, my = max(4, w // 5), max(4, h // 5)
    ix, iy = wx + mx, wy + my
    behind = _mean(*_box_sums(img, (ix, iy, ix + max(4, w - 2 * mx), iy + max(4, h - 2 * my))))
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


class AsyncSampler:
    """后台线程跑 sample_around：截屏要等合成，别让主循环和拖动陪着等。

    request() 只记下最新的窗口位置，take() 取走最近一次结果（没有新结果返回 None）。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._wake = threading.Event()
        self._rect: tuple[int, int, int, int] | None = None
        self._got: tuple[float, tuple[int, int, int]] | None = None
        self._thread: threading.Thread | None = None

    def request(self, x: int, y: int, w: int, h: int) -> None:
        with self._lock:
            self._rect = (int(x), int(y), int(w), int(h))
        if self._thread is None:
            self._thread = threading.Thread(target=self._run, name="surface-sampler", daemon=True)
            self._thread.start()
        self._wake.set()

    def take(self) -> tuple[float, tuple[int, int, int]] | None:
        with self._lock:
            got, self._got = self._got, None
        return got

    def _run(self) -> None:
        while True:
            self._wake.wait()
            self._wake.clear()
            with self._lock:
                rect, self._rect = self._rect, None
            if rect is None:
                continue
            try:
                got = sample_around(*rect)
            except Exception:  # noqa: BLE001
                got = None
            if got is not None:
                with self._lock:
                    self._got = got


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
