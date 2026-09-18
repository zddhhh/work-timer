"""Win32 分层置顶窗：透明像素点穿，拖拽移动，左键点击 / 右键菜单。"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Callable

import themes

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
HWND_NOTOPMOST = -2
GWL_EXSTYLE = -20
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
WM_SYSCOMMAND = 0x0112
WM_CAPTURECHANGED = 0x0215
SC_MOVE_CAPTION = 0xF012
SC_MINIMIZE = 0xF020
SC_MAXIMIZE = 0xF030
SC_SIZE = 0xF000
SC_MASK = 0xFFF0
WM_SETTINGCHANGE = 0x001A
WM_DISPLAYCHANGE = 0x007E
WM_MOUSEACTIVATE = 0x0021
MA_ACTIVATE = 1
SW_RESTORE = 9
MONITOR_DEFAULTTONEAREST = 2
HTCLIENT = 1
HTTRANSPARENT = -1
PM_REMOVE = 0x0001
MF_STRING = 0x0000
MF_SEPARATOR = 0x0800
TPM_LEFTALIGN = 0x0000
TPM_RIGHTBUTTON = 0x0002
TPM_RETURNCMD = 0x0100
TPM_NONOTIFY = 0x0080

MF_CHECKED = 0x00000008
MF_POPUP = 0x00000010
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOZORDER = 0x0004

ID_QUIT = 1
ID_CHECK_UPDATE = 2
ID_SET_TIME = 3
ID_DISGUISE = 4
ID_REFRESH_THEMES = 5
ID_SET_OFF = 6
ID_SCHEDULES = 7
ID_AUTO_START = 8
ID_FMT_HMS = 10
ID_FMT_MIN = 11
ID_FMT_SEC = 12
ID_ABOUT = 13
ID_THEME_BASE = 20

WNDPROC = ctypes.WINFUNCTYPE(LRESULT, wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM)
WINEVENTPROC = ctypes.WINFUNCTYPE(
    None,
    wintypes.HANDLE,
    wintypes.DWORD,
    wintypes.HWND,
    wintypes.LONG,
    wintypes.LONG,
    wintypes.DWORD,
    wintypes.DWORD,
)
EVENT_SYSTEM_FOREGROUND = 0x0003
EVENT_SYSTEM_MINIMIZESTART = 0x0016
EVENT_SYSTEM_MINIMIZEEND = 0x0017
EVENT_SYSTEM_DESKTOPSWITCH = 0x0020
WINEVENT_OUTOFCONTEXT = 0x0000
EDGE = 12
BASE_W, BASE_H = 248, 92
MIN_W, MIN_H = 148, 55
MAX_W = 520
MAX_H = int(round(MAX_W * BASE_H / BASE_W))
ASPECT = BASE_W / BASE_H
IDC_ARROW = 32512
IDC_SIZENWSE = 32642
IDC_SIZENESW = 32643

user32.DefWindowProcW.argtypes = [wintypes.HWND, ctypes.c_uint, WPARAM, LPARAM]
user32.DefWindowProcW.restype = LRESULT
user32.SetWinEventHook.restype = ctypes.c_void_p
user32.SetWinEventHook.argtypes = [
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.HMODULE,
    WINEVENTPROC,
    wintypes.DWORD,
    wintypes.DWORD,
    wintypes.DWORD,
]
user32.UnhookWinEvent.argtypes = [ctypes.c_void_p]
user32.UnhookWinEvent.restype = wintypes.BOOL


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


class MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", RECT),
        ("rcWork", RECT),
        ("dwFlags", wintypes.DWORD),
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
user32.GetWindowRect.argtypes = [wintypes.HWND, ctypes.POINTER(RECT)]
user32.GetWindowRect.restype = wintypes.BOOL
user32.SendMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.SendMessageW.restype = LRESULT
user32.MonitorFromPoint.argtypes = [POINT, wintypes.DWORD]
user32.MonitorFromPoint.restype = wintypes.HANDLE
user32.GetMonitorInfoW.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
user32.GetMonitorInfoW.restype = wintypes.BOOL
user32.IsIconic.argtypes = [wintypes.HWND]
user32.IsIconic.restype = wintypes.BOOL
user32.IsWindowVisible.argtypes = [wintypes.HWND]
user32.IsWindowVisible.restype = wintypes.BOOL
user32.GetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int]
user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.SetWindowLongPtrW.argtypes = [wintypes.HWND, ctypes.c_int, ctypes.c_ssize_t]
user32.SetWindowLongPtrW.restype = ctypes.c_ssize_t

# 句柄/指针在 Win64 是 64 位；不声明的话 ctypes 默认按 c_int 传/收，高位会被截掉。
_HANDLE = wintypes.HANDLE
kernel32.GetModuleHandleW.argtypes = [wintypes.LPCWSTR]
kernel32.GetModuleHandleW.restype = wintypes.HMODULE
user32.LoadImageW.argtypes = [_HANDLE, ctypes.c_void_p, wintypes.UINT, ctypes.c_int, ctypes.c_int, wintypes.UINT]
user32.LoadImageW.restype = _HANDLE
user32.LoadCursorW.argtypes = [_HANDLE, ctypes.c_void_p]
user32.LoadCursorW.restype = _HANDLE
user32.RegisterClassW.argtypes = [ctypes.POINTER(WNDCLASSW)]
user32.RegisterClassW.restype = wintypes.ATOM
user32.CreateWindowExW.argtypes = [
    wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
    wintypes.HWND, _HANDLE, _HANDLE, ctypes.c_void_p,
]
user32.CreateWindowExW.restype = wintypes.HWND
user32.DestroyWindow.argtypes = [wintypes.HWND]
user32.DestroyWindow.restype = wintypes.BOOL
user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
user32.ShowWindow.restype = wintypes.BOOL
user32.SetWindowPos.argtypes = [
    wintypes.HWND, ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT,
]
user32.SetWindowPos.restype = wintypes.BOOL
user32.SetForegroundWindow.argtypes = [wintypes.HWND]
user32.SetForegroundWindow.restype = wintypes.BOOL
user32.SetCapture.argtypes = [wintypes.HWND]
user32.SetCapture.restype = wintypes.HWND
user32.ReleaseCapture.argtypes = []
user32.ReleaseCapture.restype = wintypes.BOOL
user32.SetCursor.argtypes = [_HANDLE]
user32.SetCursor.restype = _HANDLE
user32.GetCursorPos.argtypes = [ctypes.POINTER(POINT)]
user32.GetCursorPos.restype = wintypes.BOOL
user32.GetDC.argtypes = [wintypes.HWND]
user32.GetDC.restype = wintypes.HDC
user32.ReleaseDC.argtypes = [wintypes.HWND, wintypes.HDC]
user32.ReleaseDC.restype = ctypes.c_int
user32.CreatePopupMenu.argtypes = []
user32.CreatePopupMenu.restype = _HANDLE
user32.AppendMenuW.argtypes = [_HANDLE, wintypes.UINT, ctypes.c_size_t, wintypes.LPCWSTR]
user32.AppendMenuW.restype = wintypes.BOOL
user32.TrackPopupMenu.argtypes = [
    _HANDLE, wintypes.UINT, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, ctypes.c_void_p,
]
user32.TrackPopupMenu.restype = ctypes.c_int
user32.DestroyMenu.argtypes = [_HANDLE]
user32.DestroyMenu.restype = wintypes.BOOL
user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT, WPARAM, LPARAM]
user32.PostMessageW.restype = wintypes.BOOL
user32.PeekMessageW.argtypes = [ctypes.POINTER(MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT, wintypes.UINT]
user32.PeekMessageW.restype = wintypes.BOOL
user32.TranslateMessage.argtypes = [ctypes.POINTER(MSG)]
user32.TranslateMessage.restype = wintypes.BOOL
user32.DispatchMessageW.argtypes = [ctypes.POINTER(MSG)]
user32.DispatchMessageW.restype = LRESULT
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


class LayeredPetWindow:
    def __init__(
        self,
        width: int,
        height: int,
        title: str = "下班倒计时",
        class_name: str = "WorkTimerLayeredWnd",
        *,
        visible: bool = True,
    ) -> None:
        self.width = width
        self.height = height
        self.x = 0
        self.y = 0
        self._on_right_click: Callable[[int, int], None] | None = None
        self._on_left_click: Callable[[int, int], None] | None = None
        self._dragging = False
        self._resizing = False
        self._drag_moved = False
        self._press_x = 0
        self._press_y = 0
        self._drag_dx = 0
        self._drag_dy = 0
        self._resize_left = False
        self._resize_right = False
        self._resize_top = False
        self._resize_bottom = False
        self._resize_ox = 0
        self._resize_oy = 0
        self._resize_ow = 0
        self._resize_oh = 0
        self._resize_opx = 0
        self._resize_opy = 0
        self._closed = False
        self._hit_mask = None
        self.drag_enabled = True
        self._has_pixels = False
        self._just_moved = False
        self._just_resized = False
        self._desktop_changed = False
        self._user_hidden = False
        self._need_topmost = True
        self._winevent_hooks: list = []
        self._winevent_proc = WINEVENTPROC(self._on_win_event)

        self._hinst = kernel32.GetModuleHandleW(None)
        self._class_name = class_name
        self._wndproc = WNDPROC(self._wnd_proc)

        wc = WNDCLASSW()
        wc.style = 0
        wc.lpfnWndProc = self._wndproc
        wc.cbClsExtra = 0
        wc.cbWndExtra = 0
        wc.hInstance = self._hinst
        wc.hIcon = None
        if getattr(sys, "frozen", False):
            image_icon = 1
            lr_defaultsize = 0x0040
            for rid in (1, 0):
                hicon = user32.LoadImageW(self._hinst, rid, image_icon, 0, 0, lr_defaultsize)
                if hicon:
                    wc.hIcon = hicon
                    break
        wc.hCursor = user32.LoadCursorW(None, IDC_ARROW)
        wc.hbrBackground = None
        wc.lpszMenuName = None
        wc.lpszClassName = self._class_name
        user32.RegisterClassW(ctypes.byref(wc))

        # 不要 WS_EX_NOACTIVATE：高 DPI 下点击容易被系统丢掉
        ex = WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW
        self.hwnd = user32.CreateWindowExW(
            ex, self._class_name, title, WS_POPUP, 0, 0, width, height, None, None, self._hinst, None
        )
        if not self.hwnd:
            raise RuntimeError("CreateWindowEx 失败")

        if visible:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        for a, b in (
            (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_FOREGROUND),
            (EVENT_SYSTEM_MINIMIZESTART, EVENT_SYSTEM_MINIMIZEEND),
            (EVENT_SYSTEM_DESKTOPSWITCH, EVENT_SYSTEM_DESKTOPSWITCH),
        ):
            hook = user32.SetWinEventHook(a, b, None, self._winevent_proc, 0, 0, WINEVENT_OUTOFCONTEXT)
            if hook:
                self._winevent_hooks.append(hook)
        self._hdc_screen = user32.GetDC(None)
        self._hdc_mem = gdi32.CreateCompatibleDC(self._hdc_screen)
        self._bits = None
        self._hbmp = None
        self._old = None
        self._alloc_bitmap()

    def _free_bitmap(self) -> None:
        if self._old and self._hdc_mem:
            gdi32.SelectObject(self._hdc_mem, self._old)
            self._old = None
        if self._hbmp:
            gdi32.DeleteObject(self._hbmp)
            self._hbmp = None
        self._bits = None

    def _alloc_bitmap(self) -> None:
        self._free_bitmap()
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

    def resize(self, width: int, height: int, *, x: int | None = None, y: int | None = None) -> None:
        width, height = snap_size(int(width), int(height))
        nx = self.x if x is None else int(x)
        ny = self.y if y is None else int(y)
        nx, ny = clamp_pos(nx, ny, width, height)
        if width == self.width and height == self.height and nx == self.x and ny == self.y:
            return
        size_changed = width != self.width or height != self.height
        self.width = width
        self.height = height
        self.x, self.y = nx, ny
        if size_changed:
            self._alloc_bitmap()
            self._has_pixels = False
            self._hit_mask = None
        if self.hwnd:
            user32.SetWindowPos(
                self.hwnd,
                None,
                self.x,
                self.y,
                width,
                height,
                SWP_NOZORDER | SWP_NOACTIVATE,
            )

    def set_right_click_handler(self, fn: Callable[[int, int], None]) -> None:
        self._on_right_click = fn

    def set_left_click_handler(self, fn: Callable[[int, int], None]) -> None:
        """左键单击回调，参数为窗口内坐标 (lx, ly)。"""
        self._on_left_click = fn

    def _on_win_event(self, _hook, event, hwnd, _obj, _child, _thread, _time) -> None:
        self._desktop_changed = True
        if self._user_hidden:
            return
        if event in (EVENT_SYSTEM_FOREGROUND, EVENT_SYSTEM_MINIMIZEEND, EVENT_SYSTEM_DESKTOPSWITCH):
            if hwnd != self.hwnd:
                self._need_topmost = True

    def destroy(self) -> None:
        for hook in self._winevent_hooks:
            user32.UnhookWinEvent(hook)
        self._winevent_hooks.clear()
        self._free_bitmap()
        if self._hdc_mem:
            gdi32.DeleteDC(self._hdc_mem)
            self._hdc_mem = 0
        if self._hdc_screen:
            user32.ReleaseDC(None, self._hdc_screen)
            self._hdc_screen = 0
        if self.hwnd:
            user32.DestroyWindow(self.hwnd)
            self.hwnd = 0

    def hide(self) -> None:
        self._user_hidden = True
        if self.hwnd:
            user32.ShowWindow(self.hwnd, 0)

    def show(self) -> None:
        self._user_hidden = False
        if self.hwnd:
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
            self.keep_topmost()

    def _blit(self, *, move: bool) -> None:
        if not self.hwnd or not self._has_pixels:
            return
        pt_dst = POINT(self.x, self.y)
        size = SIZE(self.width, self.height)
        pt_src = POINT(0, 0)
        blend = BLENDFUNCTION(AC_SRC_OVER, 0, 255, AC_SRC_ALPHA)
        user32.UpdateLayeredWindow(
            self.hwnd,
            self._hdc_screen,
            ctypes.byref(pt_dst) if move else None,
            ctypes.byref(size),
            self._hdc_mem,
            ctypes.byref(pt_src),
            0,
            ctypes.byref(blend),
            ULW_ALPHA,
        )

    def _sync_rect(self) -> None:
        if not self.hwnd:
            return
        r = RECT()
        if user32.GetWindowRect(self.hwnd, ctypes.byref(r)):
            self.x, self.y = int(r.left), int(r.top)

    def _apply_pos(self, x: int, y: int) -> None:
        self.x, self.y = clamp_pos(int(x), int(y), self.width, self.height)
        if self._has_pixels:
            self._blit(move=True)
            return
        if self.hwnd:
            user32.SetWindowPos(
                self.hwnd,
                None,
                self.x,
                self.y,
                0,
                0,
                SWP_NOSIZE | SWP_NOZORDER | SWP_NOACTIVATE,
            )

    def move(self, x: int, y: int) -> None:
        self._apply_pos(x, y)

    def ensure_visible(self) -> None:
        """拖到任务栏/最小化后，分层窗没有任务栏按钮，看起来像崩了。拉回工作区。"""
        if not self.hwnd or self._closed or self._user_hidden:
            return
        if user32.IsIconic(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_RESTORE)
        if not user32.IsWindowVisible(self.hwnd):
            user32.ShowWindow(self.hwnd, SW_SHOWNOACTIVATE)
        self._sync_rect()
        self._apply_pos(self.x, self.y)
        self.keep_topmost()

    def keep_topmost(self) -> None:
        """钉回最前。ShowWindow 隐藏后再显示，Win11 常会丢掉 WS_EX_TOPMOST。"""
        if not self.hwnd or self._closed or self._user_hidden:
            return
        hwnd = self.hwnd
        flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
        ex = int(user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) or 0)
        if not (ex & WS_EX_TOPMOST):
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, ex | WS_EX_LAYERED | WS_EX_TOPMOST | WS_EX_TOOLWINDOW)
            user32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, flags)
        user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, flags | SWP_SHOWWINDOW)

    def present_bgra(self, bgra: bytes, alpha_mask: bytes) -> None:
        """只更新画面，不改窗口位置（避免切显示时乱跳）。"""
        if not self.hwnd or self._closed:
            return
        expected = self.width * self.height * 4
        if len(bgra) != expected:
            raise ValueError("像素长度不对")
        ctypes.memmove(self._bits, bgra, expected)
        self._hit_mask = alpha_mask
        self._has_pixels = True
        self._blit(move=False)

    def _alpha_at(self, lx: int, ly: int) -> int:
        if not self._hit_mask:
            return 255
        if lx < 0 or ly < 0 or lx >= self.width or ly >= self.height:
            return 0
        return self._hit_mask[ly * self.width + lx]

    def _edge_hit(self, lx: int, ly: int) -> tuple[bool, bool, bool, bool]:
        """只认四角，保证斜向等比缩放。"""
        left = lx < EDGE
        right = lx >= self.width - EDGE
        top = ly < EDGE
        bottom = ly >= self.height - EDGE
        if (left or right) and (top or bottom):
            return left, right, top, bottom
        return False, False, False, False

    def _set_edge_cursor(self, left: bool, right: bool, top: bool, bottom: bool) -> None:
        if (left and top) or (right and bottom):
            cur = IDC_SIZENWSE
        elif (right and top) or (left and bottom):
            cur = IDC_SIZENESW
        else:
            cur = IDC_ARROW
        user32.SetCursor(user32.LoadCursorW(None, cur))

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg == WM_NCHITTEST:
            return HTCLIENT
        if msg == WM_MOUSEACTIVATE:
            return MA_ACTIVATE
        if msg == WM_SYSCOMMAND:
            cmd = int(wparam) & SC_MASK
            if cmd in (SC_MINIMIZE, SC_MAXIMIZE, SC_SIZE):
                return 0
        if msg == WM_MOUSEMOVE and not self._dragging and not self._resizing:
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            left, right, top, bottom = self._edge_hit(pt.x - self.x, pt.y - self.y)
            if any((left, right, top, bottom)):
                self._set_edge_cursor(left, right, top, bottom)
            else:
                user32.SetCursor(user32.LoadCursorW(None, IDC_ARROW))
        if msg == WM_LBUTTONDOWN:
            if not self.drag_enabled:
                return 0
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            left, right, top, bottom = self._edge_hit(pt.x - self.x, pt.y - self.y)
            user32.SetForegroundWindow(hwnd)
            self.keep_topmost()
            user32.SetCapture(hwnd)
            if any((left, right, top, bottom)):
                self._resizing = True
                self._drag_moved = False
                self._resize_left, self._resize_right = left, right
                self._resize_top, self._resize_bottom = top, bottom
                self._resize_ox, self._resize_oy = self.x, self.y
                self._resize_ow, self._resize_oh = self.width, self.height
                self._resize_opx, self._resize_opy = pt.x, pt.y
                self._set_edge_cursor(left, right, top, bottom)
                return 0
            self._dragging = True
            self._drag_moved = False
            self._press_x = pt.x
            self._press_y = pt.y
            self._drag_dx = pt.x - self.x
            self._drag_dy = pt.y - self.y
            return 0
        if msg == WM_MOUSEMOVE and self._resizing:
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            dx = pt.x - self._resize_opx
            dy = pt.y - self._resize_opy
            ow, oh = self._resize_ow, self._resize_oh
            raw_w = ow + dx if self._resize_right else ow - dx
            raw_h = oh + dy if self._resize_bottom else oh - dy
            sw = raw_w / max(1, ow)
            sh = raw_h / max(1, oh)
            scale = sw if abs(sw - 1.0) >= abs(sh - 1.0) else sh
            nw = int(round(ow * scale))
            nh = int(round(nw / ASPECT))
            nw, nh = snap_size(nw, nh)
            nx, ny = self._resize_ox, self._resize_oy
            if self._resize_left:
                nx = self._resize_ox + ow - nw
            if self._resize_top:
                ny = self._resize_oy + oh - nh
            if abs(nw - self.width) >= 2 or abs(nh - self.height) >= 2 or nx != self.x or ny != self.y:
                self._drag_moved = True
                self.resize(nw, nh, x=nx, y=ny)
            return 0
        if msg == WM_MOUSEMOVE and self._dragging:
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            if not self._drag_moved and abs(pt.x - self._press_x) <= 4 and abs(pt.y - self._press_y) <= 4:
                return 0
            self._drag_moved = True
            self._apply_pos(pt.x - self._drag_dx, pt.y - self._drag_dy)
            return 0
        if msg == WM_LBUTTONUP and self._resizing:
            moved = self._drag_moved
            self._resizing = False
            self._drag_moved = False
            user32.ReleaseCapture()
            user32.SetCursor(user32.LoadCursorW(None, IDC_ARROW))
            if moved:
                self.ensure_visible()
                self._just_resized = True
            return 0
        if msg == WM_LBUTTONUP and self._dragging:
            moved = self._drag_moved
            self._dragging = False
            self._drag_moved = False
            user32.ReleaseCapture()
            if moved:
                self.ensure_visible()
                self._just_moved = True
                return 0
            if self._on_left_click:
                pt = POINT()
                user32.GetCursorPos(ctypes.byref(pt))
                self._on_left_click(int(pt.x - self.x), int(pt.y - self.y))
            return 0
        if msg == WM_CAPTURECHANGED and (self._dragging or self._resizing):
            moved = self._drag_moved
            was_resize = self._resizing
            self._dragging = False
            self._resizing = False
            self._drag_moved = False
            if moved:
                self.ensure_visible()
                if was_resize:
                    self._just_resized = True
                else:
                    self._just_moved = True
            return 0
        if msg in (WM_SETTINGCHANGE, WM_DISPLAYCHANGE):
            self._desktop_changed = True
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)
        if msg == WM_RBUTTONUP:
            pt = POINT()
            user32.GetCursorPos(ctypes.byref(pt))
            if self._on_right_click:
                self._on_right_click(pt.x, pt.y)
            return 0
        if msg == WM_CLOSE:
            self._closed = True
            return 0
        if msg == WM_DESTROY:
            self._closed = True
            return 0
        return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def popup_menu(
        self,
        x: int,
        y: int,
        display_mode: str = "hms",
        theme_id: str = "ghost",
        *,
        esc_disguise: bool = False,
        auto_start: bool = False,
    ) -> str:
        hmenu = user32.CreatePopupMenu()
        if not hmenu:
            return ""
        hfmt = user32.CreatePopupMenu()
        user32.AppendMenuW(
            hfmt, MF_STRING | (MF_CHECKED if display_mode == "hms" else 0), ID_FMT_HMS, "时分秒"
        )
        user32.AppendMenuW(
            hfmt, MF_STRING | (MF_CHECKED if display_mode == "min" else 0), ID_FMT_MIN, "分钟"
        )
        user32.AppendMenuW(
            hfmt, MF_STRING | (MF_CHECKED if display_mode == "sec" else 0), ID_FMT_SEC, "秒"
        )
        # 外观：在季节日置顶 → 素底 → 炫彩 → 过季节日收进子菜单；catalog 按追加顺序做 ID 映射
        sections = themes.menu_sections()
        catalog: list = []
        htheme = user32.CreatePopupMenu()

        def _append_themes(menu, group: list) -> None:
            for th in group:
                checked = MF_CHECKED if th.id == theme_id else 0
                user32.AppendMenuW(menu, MF_STRING | checked, ID_THEME_BASE + len(catalog), th.name)
                catalog.append(th)

        if sections["featured"]:
            _append_themes(htheme, sections["featured"])
            user32.AppendMenuW(htheme, MF_SEPARATOR, 0, None)
        _append_themes(htheme, sections["basic"])
        if sections["basic"] and sections["fancy"]:
            user32.AppendMenuW(htheme, MF_SEPARATOR, 0, None)
        _append_themes(htheme, sections["fancy"])
        if sections["festival"]:
            hfest = user32.CreatePopupMenu()
            _append_themes(hfest, sections["festival"])
            user32.AppendMenuW(htheme, MF_SEPARATOR, 0, None)
            user32.AppendMenuW(htheme, MF_POPUP, hfest, "节日")
        user32.AppendMenuW(htheme, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(htheme, MF_STRING, ID_REFRESH_THEMES, "刷新在线外观")

        # 设置：显示方式三选一 + 两个开关，收成一个子菜单
        hset = user32.CreatePopupMenu()
        user32.AppendMenuW(hset, MF_POPUP, hfmt, "显示方式")
        user32.AppendMenuW(hset, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(
            hset,
            MF_STRING | (MF_CHECKED if esc_disguise else 0),
            ID_DISGUISE,
            "Ctrl 隐藏窗口",
        )
        user32.AppendMenuW(
            hset,
            MF_STRING | (MF_CHECKED if auto_start else 0),
            ID_AUTO_START,
            "开机自启动",
        )

        user32.AppendMenuW(hmenu, MF_STRING, ID_SET_OFF, "设置下班时间…")
        user32.AppendMenuW(hmenu, MF_STRING, ID_SCHEDULES, "日程列表…")
        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(hmenu, MF_POPUP, htheme, "外观")
        user32.AppendMenuW(hmenu, MF_POPUP, hset, "设置")
        user32.AppendMenuW(hmenu, MF_SEPARATOR, 0, None)
        user32.AppendMenuW(hmenu, MF_STRING, ID_CHECK_UPDATE, "检查更新")
        user32.AppendMenuW(hmenu, MF_STRING, ID_ABOUT, "关于…")
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
        if cmd == ID_ABOUT:
            return "about"
        if cmd == ID_SET_TIME:
            return "set_time"
        if cmd == ID_SET_OFF:
            return "set_off"
        if cmd == ID_SCHEDULES:
            return "schedules"
        if cmd == ID_DISGUISE:
            return "toggle_esc_disguise"
        if cmd == ID_AUTO_START:
            return "toggle_auto_start"
        if cmd == ID_FMT_HMS:
            return "fmt_hms"
        if cmd == ID_FMT_MIN:
            return "fmt_min"
        if cmd == ID_FMT_SEC:
            return "fmt_sec"
        if cmd == ID_REFRESH_THEMES:
            return "refresh_themes"
        if ID_THEME_BASE <= cmd < ID_THEME_BASE + len(catalog):
            return "theme:" + catalog[cmd - ID_THEME_BASE].id
        return ""

    @property
    def dragging(self) -> bool:
        return self._dragging

    @property
    def resizing(self) -> bool:
        return self._resizing

    @property
    def just_moved(self) -> bool:
        flag = self._just_moved
        self._just_moved = False
        return flag

    @property
    def just_resized(self) -> bool:
        flag = self._just_resized
        self._just_resized = False
        return flag

    @property
    def desktop_changed(self) -> bool:
        flag = self._desktop_changed
        self._desktop_changed = False
        return flag

    def pump(self) -> None:
        if not self.hwnd:
            return
        msg = MSG()
        while user32.PeekMessageW(ctypes.byref(msg), self.hwnd, 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        # hwnd=-1 才吃到线程消息，WinEvent（切前台）靠这个才会回调
        while user32.PeekMessageW(ctypes.byref(msg), wintypes.HWND(-1), 0, 0, PM_REMOVE):
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))
        if self._need_topmost:
            self._need_topmost = False
            self.keep_topmost()

    @property
    def closed(self) -> bool:
        return self._closed


def work_area() -> RECT:
    r = RECT()
    user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(r), 0)
    return r


def _monitor_info_at(x: int, y: int) -> MONITORINFO | None:
    hmon = user32.MonitorFromPoint(POINT(int(x), int(y)), MONITOR_DEFAULTTONEAREST)
    mi = MONITORINFO()
    mi.cbSize = ctypes.sizeof(MONITORINFO)
    if hmon and user32.GetMonitorInfoW(hmon, ctypes.byref(mi)):
        return mi
    return None


def monitor_work_at(x: int, y: int) -> RECT:
    mi = _monitor_info_at(x, y)
    return mi.rcWork if mi is not None else work_area()


def monitor_rect_at(x: int, y: int) -> RECT | None:
    """该点所在显示器的完整物理矩形（含任务栏）。"""
    mi = _monitor_info_at(x, y)
    return mi.rcMonitor if mi is not None else None


def snap_size(w: int, h: int) -> tuple[int, int]:
    """锁定 248:92 比例；最小约 148×55。"""
    w = int(w)
    # 以宽为准等比，再夹到合法范围
    w = max(MIN_W, min(MAX_W, w))
    h = int(round(w * BASE_H / BASE_W))
    if h > MAX_H:
        h = MAX_H
        w = int(round(h * BASE_W / BASE_H))
    if h < MIN_H:
        h = MIN_H
        w = int(round(h * BASE_W / BASE_H))
    w = max(MIN_W, min(MAX_W, w))
    h = int(round(w * BASE_H / BASE_W))
    return w, h


def clamp_pos(x: int, y: int, w: int, h: int) -> tuple[int, int]:
    """整窗夹在当前显示器工作区内，不探出屏幕、不钻进任务栏。"""
    area = monitor_work_at(int(x) + int(w) // 2, int(y) + int(h) // 2)
    min_x, min_y = int(area.left), int(area.top)
    max_x = int(area.right) - int(w)
    max_y = int(area.bottom) - int(h)
    if max_x < min_x:
        max_x = min_x
    if max_y < min_y:
        max_y = min_y
    return max(min_x, min(int(x), max_x)), max(min_y, min(int(y), max_y))
