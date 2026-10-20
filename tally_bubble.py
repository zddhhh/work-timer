"""计时器上方的小胶囊：今天的键盘、鼠标、滚轮次数。鼠标点不到它，直接穿过去。"""
from __future__ import annotations

import ctypes
import os
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFont

import activity
import layered_win as lw

WS_EX_TRANSPARENT = 0x00000020
GAP = 5
_CLASS = "WorkTimerTallyBubble"
_SS = 2
_FONTS: dict[int, ImageFont.ImageFont] = {}
_FILL = (22, 26, 36, 228)
_EDGE = (255, 255, 255, 46)
_ICON = (150, 172, 206, 255)
_TEXT = (240, 243, 248, 255)


def _font(size: int) -> ImageFont.ImageFont:
    got = _FONTS.get(size)
    if got is not None:
        return got
    fonts = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf"):
        try:
            got = ImageFont.truetype(str(fonts / name), size)
            break
        except OSError:
            continue
    if got is None:
        got = ImageFont.load_default()
    _FONTS[size] = got
    return got


def scale_for(card_h: int) -> float:
    return max(0.85, min(1.6, card_h / 92.0))


def _keyboard(d: ImageDraw.ImageDraw, x: int, cy: int, s: int) -> int:
    w, h = int(s * 1.45), int(s * 0.95)
    top = cy - h // 2
    lw_ = max(2, s // 7)
    d.rounded_rectangle((x, top, x + w, top + h), radius=max(2, s // 5), outline=_ICON, width=lw_)
    dot = max(2, s // 8)
    for row in range(2):
        for col in range(4):
            dx = x + int(w * (0.2 + col * 0.2))
            dy = top + int(h * (0.3 + row * 0.22))
            d.rectangle((dx - dot // 2, dy - dot // 2, dx + dot // 2, dy + dot // 2), fill=_ICON)
    by = top + int(h * 0.76)
    d.rectangle((x + int(w * 0.28), by - dot // 2, x + int(w * 0.72), by + dot // 2), fill=_ICON)
    return w


def _mouse(d: ImageDraw.ImageDraw, x: int, cy: int, s: int) -> int:
    w, h = int(s * 0.78), int(s * 1.1)
    top = cy - h // 2
    lw_ = max(2, s // 7)
    d.rounded_rectangle((x, top, x + w, top + h), radius=w // 2, outline=_ICON, width=lw_)
    mid = x + w // 2
    d.line((mid, top + lw_, mid, top + int(h * 0.38)), fill=_ICON, width=lw_)
    return w


def _wheel(d: ImageDraw.ImageDraw, x: int, cy: int, s: int) -> int:
    w = int(s * 0.8)
    half = int(s * 0.5)
    gap = max(2, s // 8)
    mid = x + w // 2
    d.polygon([(mid, cy - half), (x + w, cy - gap), (x, cy - gap)], fill=_ICON)
    d.polygon([(mid, cy + half), (x + w, cy + gap), (x, cy + gap)], fill=_ICON)
    return w


def render(keys: int, clicks: int, wheels: int, scale: float = 1.0) -> Image.Image:
    """深色胶囊，图标在前、数字在后。先按两倍画再缩小，小图标边缘不发毛。"""
    k = scale * _SS
    font = _font(max(10, int(round(12 * k))))
    icon = int(round(13 * k))
    pad = int(round(9 * k))
    inner = int(round(4 * k))
    sep = int(round(11 * k))
    h = int(round(23 * k))
    parts = (
        (_keyboard, activity.fmt_count(keys)),
        (_mouse, activity.fmt_count(clicks)),
        (_wheel, activity.fmt_count(wheels)),
    )
    probe = ImageDraw.Draw(Image.new("L", (1, 1)))
    widths = []
    for draw_icon, text in parts:
        iw = {_keyboard: int(icon * 1.45), _mouse: int(icon * 0.78), _wheel: int(icon * 0.8)}[draw_icon]
        widths.append((iw, int(probe.textlength(text, font=font))))
    w = pad * 2 + sum(iw + inner + tw for iw, tw in widths) + sep * (len(parts) - 1)
    im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((0, 0, w - 1, h - 1), radius=h // 2, fill=_FILL, outline=_EDGE, width=max(1, _SS))
    cy = h // 2
    x = pad
    box = probe.textbbox((0, 0), "0", font=font)
    ty = cy - (box[1] + box[3]) // 2
    for (draw_icon, text), (iw, tw) in zip(parts, widths):
        draw_icon(d, x, cy, icon)
        x += iw + inner
        d.text((x, ty), text, font=font, fill=_TEXT)
        x += tw + sep
    return im.resize((max(1, w // _SS), max(1, h // _SS)), Image.Resampling.LANCZOS)


def place(card_x: int, card_y: int, card_w: int, card_h: int, bw: int, bh: int,
          area: tuple[int, int, int, int]) -> tuple[int, int]:
    """优先放在卡片正上方；顶到屏幕上沿就放到下面。"""
    left, top, right, bottom = area
    x = card_x + (card_w - bw) // 2
    y = card_y - bh - GAP
    if y < top:
        y = card_y + card_h + GAP
    if y + bh > bottom:
        y = max(top, bottom - bh)
    x = max(left, min(x, right - bw))
    return x, y


def _premultiplied_bgra(im: Image.Image) -> bytes:
    r, g, b, a = im.split()
    pm = Image.merge("RGBA", (ImageChops.multiply(r, a), ImageChops.multiply(g, a), ImageChops.multiply(b, a), a))
    return pm.tobytes("raw", "BGRA")


class TallyBubble:
    def __init__(self) -> None:
        self.hwnd = 0
        self.w = self.h = 0
        self.x = self.y = 0
        self._shown = False
        self._sig: tuple | None = None
        self._wndproc = lw.WNDPROC(self._proc)
        self._hinst = lw.kernel32.GetModuleHandleW(None)
        self._hdc_screen = 0
        self._hdc_mem = 0
        self._hbmp = 0
        self._old = 0
        self._bits = None

    def _proc(self, hwnd, msg, wparam, lparam):
        if msg == lw.WM_NCHITTEST:
            return lw.HTTRANSPARENT
        return lw.user32.DefWindowProcW(hwnd, msg, wparam, lparam)

    def _ensure(self) -> bool:
        if self.hwnd:
            return True
        wc = lw.WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = self._hinst
        wc.hCursor = lw.user32.LoadCursorW(None, lw.IDC_ARROW)
        wc.lpszClassName = _CLASS
        lw.user32.RegisterClassW(ctypes.byref(wc))
        ex = lw.WS_EX_LAYERED | lw.WS_EX_TOPMOST | lw.WS_EX_TOOLWINDOW | lw.WS_EX_NOACTIVATE | WS_EX_TRANSPARENT
        self.hwnd = lw.user32.CreateWindowExW(
            ex, _CLASS, "", lw.WS_POPUP, 0, 0, 1, 1, None, None, self._hinst, None,
        ) or 0
        if not self.hwnd:
            return False
        self._hdc_screen = lw.user32.GetDC(None)
        self._hdc_mem = lw.gdi32.CreateCompatibleDC(self._hdc_screen)
        return True

    def _alloc(self, w: int, h: int) -> None:
        if self._old:
            lw.gdi32.SelectObject(self._hdc_mem, self._old)
            self._old = 0
        if self._hbmp:
            lw.gdi32.DeleteObject(self._hbmp)
            self._hbmp = 0
        bmi = lw.BITMAPINFO()
        bmi.bmiHeader.biSize = ctypes.sizeof(lw.BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = lw.BI_RGB
        bits = ctypes.c_void_p()
        self._hbmp = lw.gdi32.CreateDIBSection(
            self._hdc_mem, ctypes.byref(bmi), lw.DIB_RGB_COLORS, ctypes.byref(bits), None, 0,
        ) or 0
        self._bits = bits
        self._old = lw.gdi32.SelectObject(self._hdc_mem, self._hbmp) if self._hbmp else 0
        self.w, self.h = w, h

    def show(self, counts: tuple[int, int, int], card: tuple[int, int, int, int]) -> None:
        """counts 或卡片大小变了才重画；只挪位置时只移窗口。"""
        if not self._ensure():
            return
        cx, cy, cw, ch = card
        scale = scale_for(ch)
        sig = (counts, round(scale, 2))
        repaint = sig != self._sig
        if repaint:
            im = render(*counts, scale=scale)
            if im.size != (self.w, self.h) or not self._hbmp:
                self._alloc(*im.size)
            if not self._hbmp:
                return
            ctypes.memmove(self._bits, _premultiplied_bgra(im), self.w * self.h * 4)
            self._sig = sig
        r = lw.monitor_work_at(cx + cw // 2, cy + ch // 2)
        x, y = place(cx, cy, cw, ch, self.w, self.h, (int(r.left), int(r.top), int(r.right), int(r.bottom)))
        if not repaint and self._shown and (x, y) == (self.x, self.y):
            return
        self.x, self.y = x, y
        pt = lw.POINT(x, y)
        size = lw.SIZE(self.w, self.h)
        src = lw.POINT(0, 0)
        blend = lw.BLENDFUNCTION(lw.AC_SRC_OVER, 0, 255, lw.AC_SRC_ALPHA)
        lw.user32.UpdateLayeredWindow(
            self.hwnd, self._hdc_screen, ctypes.byref(pt), ctypes.byref(size),
            self._hdc_mem, ctypes.byref(src), 0, ctypes.byref(blend), lw.ULW_ALPHA,
        )
        if not self._shown:
            lw.user32.ShowWindow(self.hwnd, lw.SW_SHOWNOACTIVATE)
            self._shown = True

    def follow(self, card: tuple[int, int, int, int]) -> None:
        """只挪位置。拖动时和计时器走同一条鼠标消息，不重画、不等主循环。"""
        if not self.hwnd or not self._shown or self.w < 2:
            return
        cx, cy, cw, ch = card
        r = lw.monitor_work_at(cx + cw // 2, cy + ch // 2)
        x, y = place(cx, cy, cw, ch, self.w, self.h, (int(r.left), int(r.top), int(r.right), int(r.bottom)))
        if (x, y) == (self.x, self.y):
            return
        self.x, self.y = x, y
        lw.user32.SetWindowPos(
            self.hwnd, lw.HWND_TOPMOST, x, y, 0, 0, lw.SWP_NOSIZE | lw.SWP_NOACTIVATE,
        )

    def hide(self) -> None:
        if self.hwnd and self._shown:
            lw.user32.ShowWindow(self.hwnd, 0)
        self._shown = False

    def pump(self) -> None:
        if not self.hwnd:
            return
        msg = lw.MSG()
        while lw.user32.PeekMessageW(ctypes.byref(msg), self.hwnd, 0, 0, lw.PM_REMOVE):
            lw.user32.DispatchMessageW(ctypes.byref(msg))

    def destroy(self) -> None:
        if self._old and self._hdc_mem:
            lw.gdi32.SelectObject(self._hdc_mem, self._old)
            self._old = 0
        if self._hbmp:
            lw.gdi32.DeleteObject(self._hbmp)
            self._hbmp = 0
        if self._hdc_mem:
            lw.gdi32.DeleteDC(self._hdc_mem)
            self._hdc_mem = 0
        if self._hdc_screen:
            lw.user32.ReleaseDC(None, self._hdc_screen)
            self._hdc_screen = 0
        if self.hwnd:
            lw.user32.DestroyWindow(self.hwnd)
            self.hwnd = 0
        self._shown = False
