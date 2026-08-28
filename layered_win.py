"""Win32 分层置顶窗：透明像素点穿，拖拽移动，左键点击 / 右键菜单。"""
from __future__ import annotations

import ctypes
from ctypes import wintypes
from typing import Callable

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32
kernel32 = ctypes.windll.kernel32

WPARAM = ctypes.c_size_t
LPARAM = ctypes.c_ssize_t
LRESULT = ctypes.c_ssize_t

WS_POPUP = 0x80000000
WS_EX_LAYERED = 0x00080000
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = -1
SWP_SHOWWINDOW = 0x0040
SWP_NOACTIVATE = 0x0010
SW_SHOWNOACTIVATE = 4
ULW_ALPHA = 0x00000002
AC_SRC_OVER = 0x00
AC_SRC_ALPHA = 0x01
BI_RGB = 0
DIB_RGB_COLORS = 0
WM_DESTROY = 0x0002
WM_CLOSE = 0x0010
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONUP = 0x0205
WM_MOUSEMOVE = 0x0200
WM_NCHITTEST = 0x0084
HTCLIENT = 1
HTTRANSPARENT = -1
PM_REMOVE = 0x0001
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
TPM_LEFTALIGN = 0x0000
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080

ID_QUIT = 1
ID_CHECK_UPDATE = 2
ID_SET_TIME = 3

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM)

user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT


class WNDCLASSW(ctypes.Structure):
    _fields_ = [
        ("style", wintypes.UINT),
        ("lpfnWndProc", WNDPROC),
        ("cbClsExtra", ctypes.c_int),
        ("cbWndExtra", ctypes.c_int),
        ("hInstance", wintypes.HINSTANCE),
        ("hIcon", wintypes.HICON),
        ("hCursor", wintypes.HANDLE),
        ("hbrBackground", wintypes.HBRUSH),
        ("lpszMenuName", wintypes.LPCWSTR),
        ("lpszClassName", wintypes.LPCWSTR),
    ]


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


class POINT(ctypes.Structure):
    _fields_ = [("x", wintypes.LONG), ("y", wintypes.LONG)]


class SIZE(ctypes.Structure):
    _fields_ = [("cx", wintypes.LONG), ("cy", wintypes.LONG)]


class BLENDFUNCTION(ctypes.Structure):
    _fields_ = [
        ("BlendOp", ctypes.c_byte),
        ("BlendFlags", ctypes.c_byte),
        ("SourceConstantAlpha", ctypes.c_byte),
        ("AlphaFormat", ctypes.c_byte),
    ]


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", wintypes.LONG),
        ("top", wintypes.LONG),
        ("right", wintypes.LONG),
        ("bottom", wintypes.LONG),
    ]


class MSG(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("message", wintypes.UINT),
        ("wParam", WPARAM),
        ("lParam", LPARAM),
        ("time", wintypes.DWORD),
        ("pt", POINT),
    ]


user32.UpdateLayeredWindow.argtypes = [
    wintypes.HWND,
    wintypes.HDC,
    ctypes.POINTER(POINT),
    ctypes.POINTER(SIZE),
    wintypes.HDC,
    ctypes.POINTER(POINT),
    wintypes.DWORD,
    ctypes.POINTER(BLENDFUNCTION),
    wintypes.DWORD,
]


class LayeredPetWindow:
    def __init__(self, width: int, height: int, title: str = "弹性下班") -> None:
        self.width = width
        self.height = height
        self.x = 0
        self.y = 0
        self._on_right_click: Callable[[int, int], None] | None = None
        self._on_left_click: Callable[[], None] | None = None
        self._dragging = False
        self._drag_moved = False
        self._press_x = 0
        self._press_y = 0
        self._drag_dx = 0
        self._drag_dy = 0
        self._closed = False
        self._hit_mask = None
        self.drag_enabled = True

        self._hinst = kernel32.GetModuleHandleW(None)
        self._class_name = "WorkTimerLayeredWnd"
        self._wndproc = WNDPROC(self._wnd_proc)

        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = self._wndproc
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = self._hinst
        wc.hIcon = None
        wc.hCursor = user32.LoadCursorW(None, 32512)
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = self._class_name
        user32.RegisterClassW(ctypes.byref(wc))

        ex = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        self.hwnd = user32.CreateWindowExW(
            ex, self._class_name, title, WS_POPUP, 0, 0, width, height, None, None, self._hinst, None
        )
        if not self.hwnd:
            raise RuntimeError("CreateWindowEx 失败")

        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self._hdc_screen = user32.GetDC(None)
        self._hdc_mem = gdi32.CreateCompatibleDC(self._hdc_screen)
        self._bits = None
        self._hbmp = None
        self._old = None
        self._alloc_bitmap()

    def _alloc_bitmap(self) -> None:
        bmi = BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = self.width
        bmi.bmiHeader.biHeight = -self.height
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = BI_RGB
        bits_ptr = ctypes.c_void_p()
        self._hbmp = gdi32.CreateDIBSection(
            self._hdc_mem, ctypes.byref(bmi), DIB_RGB_COLORS, ctypes.byref(bits_ptr), None, 0
        )
        if not self._hbmp:
            raise RuntimeError("CreateDIBSection 失败")
        self._bits = bits_ptr
        self._old = gdi32.SelectObject(self._hdc_mem, self._hbmp)

    def set_right_click_handler(self, fn: Callable[[int, int], None]) -> None:
        self._on_right_click = fn

    def set_left_click_handler(self, fn: Callable[[], None]) -> None:
        self._on_left_click = fn

    def destroy(self) -> None:
        if self._old:
            gdi32.SelectObject(self._hdc_mem, self._old)
        if self._hbmp:
            gdi32.DeleteObject(self._hbmp)
        if self._hdc_mem:
            gdi32.DeleteDC(self._hdc_mem)
        if self._hdc_screen:
            user32.ReleaseDC(None, self._hdc_screen)
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = 0

    def move(self, x: int, y: int) -> None:
        self.x, self.y = int(x), int(y)
        user32.SetWindowPos(
            self.hwnd, HWND_TOPMOST, self.x, self.y, self.width, self.height, SWP_SHOWWINDOW | SWP_NOACTIVATE
        )

    def keep_topmost(self) -> None:
        user32.SetWindowPos(
            self.hwnd, HWND_TOPMOST, 0, 0, 0, 0, 0x0001 | 0x0002 | SWP_NOACTIVATE | SWP_SHOWWINDOW
        )
        user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)

    def present_bgra(self, bgra: bytes, alpha_mask: bytes) -> None:
        expected = self.width * self.height * 4
        if len(bgra) != expected:
            raise ValueError("像素长度不对")
        ctypes.memmove(self._bits, bgra, expected)
        self._hit_mask = alpha_mask

        pt_dst = POINT(self.x, self.y)
        size = SIZE(self.width, self.height)
        pt_src = POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        ok = user32.UpdateLayeredWindow(
            self.hwnd,
            self._hdc_screen,
            ctypes.byref(pt_dst),
            ctypes.byref(size),
            self._hdc_mem,
            ctypes.byref(pt_src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        )
        if not ok:
            self.keep_topmost()

    def _alpha_at(self, lx: int, ly: int) -> int:
        if not self._hit_mask:
            return 255
        if lx < 0 or ly < 0 or lx >= self.width or ly >= self.height:
            return 0
        return self._hit_mask[ly * self.width + lx]

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_NCHITTEST:
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            lx, ly = pt.x - self.x, pt.y - self.y
            if self._alpha_at(lx, ly) < 16:
                return HTTRANSPARENT
            return HTCLIENT
        if msg == WM_LBUTTONDOWN:
            if not self.drag_enabled:
                return 0
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            self._dragging = True
            self._drag_moved = False
            self._press_x = pt.x
            self._press_y = pt.y
            self._drag_dx = pt.x - self.x
            self._drag_dy = pt.y - self.y
            user32.SetCapture(hwnd)
            return 0
        if msg == WM_MOUSEMOVE and self._dragging:
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            if abs(pt.x - self._press_x) > 6 or abs(pt.y - self._press_y) > 6:
                self._drag_moved = True
            if self._drag_moved:
                self.move(pt.x - self._drag_dx, pt.y - self._drag_dy)
            return 0
        if msg == WM_LBUTTONUP and self._dragging:
            moved = self._drag_moved
            self._dragging = False
            self._drag_moved = False
            user32.ReleaseCapture()
            if not moved and self._on_left_click:
                self._on_left_click()
            return 0
        if msg == WM_RBUTTONUP:
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            if self._on_right_click:
                self._on_right_click(pt.x, pt.y)
            return 0
        if msg == WM_CLOSE:
            self._closed = True
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def popup_menu(self, x: int, y: int) -> str:
        hmenu = user32.CreatePopupMenu()
        if not hmenu:
            return ""
        user32.AppendMenuW(hmenu, MF_STRING, ID_SET_TIME, "设置上班时间")
        user32.AppendMenuW(hmenu, MF_STRING, ID_CHECK_UPDATE, "检查更新")
        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(hmenu, MF_STRING, ID_QUIT, "退出")
        try:
            user32.AllowSetForegroundWindow(-1)
        except Exception:
            pass
        user32.SetForegroundWindow(self.hwnd)
        cmd = user32.TrackPopupMenu(
            hmenu,
            TPM_LEFTALIGN | TPM_RIGHTBUTTON | TPM_RETURNCMD | TPM_NONOTIFY,
            int(x),
            int(y),
            0,
            self.hwnd,
            None,
        )
        user32.PostMessageW(self.hwnd, 0, 0, 0)
        user32.DestroyMenu(hmenu)
        if cmd == ID_QUIT:
            return "quit"
        if cmd == ID_CHECK_UPDATE:
            return "update"
        if cmd == ID_SET_TIME:
            return "set_time"
        return ""

    def pump(self) -> None:
        msg = MSG()
        while user32.PeekMessageW(ctypes.byref(msg), 0, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    @property
    def closed(self) -> bool:
        return self._closed


def work_area() -> RECT:
    r = RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
    return r
