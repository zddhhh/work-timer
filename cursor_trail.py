"""光标后面的一条尾巴。系统箭头不变，尾巴画在点穿的透明层上。

长短按还剩的时间：早上长，快下班收成一个小光点。手停住之后变淡，长度还在。
"""
from __future__ import annotations

import math
import time
from typing import Sequence

from PIL import Image, ImageChops, ImageDraw

import layered_win

FULL_DAY = 9.5 * 3600
MAX_PX = 280.0
MIN_PX = 11.0
SIZE = 640
_HALF = SIZE // 2

WS_EX_TRANSPARENT = 0x00000020
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
SWP_NOACTIVATE = 0x0010
SW_HIDE = 0


def trail_length(remain_s: float) -> float:
    """剩余秒数换成尾巴像素。开方，这样最后一小时还看得出长短。"""
    span = max(0.0, float(remain_s))
    t = min(1.0, span / FULL_DAY)
    return MIN_PX + (MAX_PX - MIN_PX) * math.sqrt(t)


def color_for(remain_s: float) -> tuple[int, int, int]:
    """早上偏冷，下午偏金，最后一段偏暖。"""
    t = min(1.0, max(0.0, float(remain_s) / FULL_DAY))
    if t > 0.35:
        return _lerp((255, 176, 96), (96, 186, 255), (t - 0.35) / 0.65)
    return _lerp((255, 96, 64), (255, 176, 96), t / 0.35)


def trim_trail(points: Sequence[tuple[float, float]], length: float) -> list[tuple[float, float]]:
    """留下靠近头（最后一点）的那一段，弧长不超过 length。"""
    if not points:
        return []
    if len(points) == 1 or length <= 0:
        return [points[-1]]
    kept: list[tuple[float, float]] = [points[-1]]
    acc = 0.0
    for i in range(len(points) - 1, 0, -1):
        x1, y1 = points[i]
        x0, y0 = points[i - 1]
        seg = math.hypot(x1 - x0, y1 - y0)
        if seg <= 0:
            continue
        if acc + seg >= length:
            need = max(0.0, length - acc)
            f = need / seg
            kept.append((x1 - (x1 - x0) * f, y1 - (y1 - y0) * f))
            break
        acc += seg
        kept.append((x0, y0))
    kept.reverse()
    return kept


def draw_ribbon(
    points: Sequence[tuple[float, float]],
    rgb: tuple[int, int, int],
    gain: float,
    *,
    size: int = SIZE,
    width: int | None = None,
    height: int | None = None,
) -> Image.Image:
    """points 是窗口内坐标，最后一点是头。gain 为 1 时最亮。"""
    img = Image.new("RGBA", (width or size, height or size), (0, 0, 0, 0))
    if not points:
        return img
    gain = max(0.0, min(1.0, gain))
    draw = ImageDraw.Draw(img)
    r, g, b = rgb
    samples = _resample(points, 2.2)
    n = len(samples)
    for i, (x, y) in enumerate(samples):
        t = 1.0 if n == 1 else i / (n - 1)
        # 尾巴也留亮度。纯按 t² 衰减时，深色桌面上只剩头上一个点
        body = 0.45 + 0.55 * t
        shade = 3.2 + 11.0 * t
        halo = 3.4 + 11.0 * t
        core = 1.3 + 3.6 * t
        sa = int((30 + 24 * body) * gain)
        ha = int((90 + 110 * body) * gain)
        ca = int((150 + 90 * body) * gain)
        hr, hg, hb = _lerp((r, g, b), (255, 252, 246), 0.72 + 0.28 * t)
        draw.ellipse(_box(x, y, shade), fill=(12, 14, 18, sa))
        draw.ellipse(_box(x, y, halo), fill=(r, g, b, ha))
        draw.ellipse(_box(x, y, core), fill=(hr, hg, hb, ca))
    hx, hy = samples[-1]
    orb = 6.5
    draw.ellipse(_box(hx, hy, orb + 8), fill=(r, g, b, int(90 + 70 * gain)))
    draw.ellipse(_box(hx, hy, orb), fill=(255, 252, 246, int(230 + 25 * gain)))
    return img


def _resample(points: Sequence[tuple[float, float]], step: float) -> list[tuple[float, float]]:
    if len(points) < 2:
        return list(points)
    out = [points[0]]
    acc = 0.0
    prev = points[0]
    for x, y in points[1:]:
        seg = math.hypot(x - prev[0], y - prev[1])
        if seg <= 0:
            continue
        while acc + seg >= step:
            need = step - acc
            f = need / seg
            prev = (prev[0] + (x - prev[0]) * f, prev[1] + (y - prev[1]) * f)
            out.append(prev)
            seg = math.hypot(x - prev[0], y - prev[1])
            acc = 0.0
        acc += seg
        prev = (x, y)
    if math.hypot(out[-1][0] - points[-1][0], out[-1][1] - points[-1][1]) > 0.8:
        out.append(points[-1])
    return out


def _box(x: float, y: float, radius: float) -> tuple[float, float, float, float]:
    return (x - radius, y - radius, x + radius, y + radius)


def _lerp(a: tuple[int, int, int], b: tuple[int, int, int], t: float) -> tuple[int, int, int]:
    t = max(0.0, min(1.0, t))
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))  # type: ignore[return-value]


def frame_for(
    points: Sequence[tuple[float, float]],
    rgb: tuple[int, int, int],
    gain: float,
    *,
    pad: float = 16,
) -> tuple[Image.Image, int, int]:
    """按尾巴的外接框出图，不画一整块空画布。返回图像和屏幕左上角。"""
    if not points:
        img = Image.new("RGBA", (8, 8), (0, 0, 0, 0))
        return img, 0, 0
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    left = int(math.floor(min(xs) - pad))
    top = int(math.floor(min(ys) - pad))
    right = int(math.ceil(max(xs) + pad))
    bottom = int(math.ceil(max(ys) + pad))
    w = max(8, right - left)
    h = max(8, bottom - top)
    local = [(x - left, y - top) for x, y in points]
    return draw_ribbon(local, rgb, gain, width=w, height=h), left, top


def _quantum(n: int) -> int:
    return max(32, (int(n) + 31) // 32 * 32)


def _to_bgra(img: Image.Image) -> bytes:
    r, g, b, a = img.split()
    pm = Image.merge(
        "RGBA",
        (ImageChops.multiply(r, a), ImageChops.multiply(g, a), ImageChops.multiply(b, a), a),
    )
    return pm.tobytes("raw", "BGRA")


class Trail:
    """跟着系统光标的透明层。below 是倒计时卡片，重叠时卡片留在上面。"""

    def __init__(self) -> None:
        self.hot = False
        self._pts: list[tuple[float, float]] = []
        self._cx = 0.0
        self._cy = 0.0
        self._has = False
        self._moved_at = 0.0
        self._gain = 1.0
        self._key: tuple | None = None
        self._shown = False
        self._hwnd = 0
        self._bits = None
        self._bw = 0
        self._bh = 0
        self._hdc_screen = 0
        self._hdc_mem = 0
        self._hbmp = None
        self._old = None
        self._wndproc = None
        self._top = False
        self._card_up = False

    def warm(self) -> None:
        """先在屏幕外交一张小图，把分层窗的第一下摊到启动之后，而不是摊在打开开关时。"""
        if self._hwnd or self._shown:
            return
        if not self._open():
            return
        blank = Image.new("RGBA", (32, 32), (0, 0, 0, 0))
        self._present(blank, -32000, -32000, 0)
        self._hide()

    def tick(self, remain_s: float, *, visible: bool, below: int = 0, raise_windows: bool = True) -> None:
        self._pump()
        if not visible:
            self.hot = False
            self._hide()
            return
        if not self._hwnd and not self._open():
            self.hot = False
            return
        x, y = _cursor()
        now = time.monotonic()
        jumped = self._has and math.hypot(x - self._cx, y - self._cy) > 140
        moved = (not self._has) or math.hypot(x - self._cx, y - self._cy) >= 1.6
        if jumped:
            self._pts.clear()
        if moved:
            self._pts.append((x, y))
            self._moved_at = now
        self._cx, self._cy = x, y
        self._has = True
        length = trail_length(remain_s)
        self._pts = trim_trail(self._pts, length + 24)
        gain = 0.82 if now - self._moved_at > 0.42 else 1.0
        self._gain = gain
        key = (int(x), int(y), int(length), int(gain * 20))
        self.hot = moved
        if key == self._key and self._shown:
            return
        self._key = key
        # 头从箭头尖后面一点开始，避免光点压住点击位置
        pts = _pull_head(self._pts, 14)
        img, left, top = frame_for(pts, color_for(remain_s), gain)
        self._present(img, left, top, below, raise_windows=raise_windows)

    def hide(self) -> None:
        """关掉开关或还没开始计时时收起。窗口留着，下次打开不用重建。"""
        self._hide()

    def destroy(self) -> None:
        user32 = layered_win.user32
        gdi32 = layered_win.gdi32
        if self._old and self._hdc_mem:
            gdi32.SelectObject(self._hdc_mem, self._old)
            self._old = None
        if self._hbmp:
            gdi32.DeleteObject(self._hbmp)
            self._hbmp = None
        self._bits = None
        if self._hdc_mem:
            gdi32.DeleteDC(self._hdc_mem)
            self._hdc_mem = 0
        if self._hdc_screen:
            user32.ReleaseDC(None, self._hdc_screen)
            self._hdc_screen = 0
        if self._hwnd:
            user32.DestroyWindow(self._hwnd)
            self._hwnd = 0
        self._shown = False

    def _open(self) -> bool:
        user32 = layered_win.user32
        gdi32 = layered_win.gdi32
        kernel32 = layered_win.kernel32
        hinst = kernel32.GetModuleHandleW(None)
        self._wndproc = layered_win.WNDPROC(self._wnd_proc)
        wc = layered_win.WNDCLASSW()
        wc.lpfnWndProc = self._wndproc
        wc.hInstance = hinst
        wc.lpszClassName = "WorkTimerCursorTrail"
        user32.RegisterClassW(layered_win.ctypes.byref(wc))
        ex = (
            layered_win.WS_EX_LAYERED
            | layered_win.WS_EX_TOPMOST
            | layered_win.WS_EX_TOOLWINDOW
            | layered_win.WS_EX_NOACTIVATE
            | WS_EX_TRANSPARENT
        )
        self._hwnd = user32.CreateWindowExW(
            ex, "WorkTimerCursorTrail", "下班尾巴", layered_win.WS_POPUP,
            0, 0, 32, 32, None, None, hinst, None,
        )
        if not self._hwnd:
            return False
        user32.ShowWindow(self._hwnd, SW_HIDE)
        self._hdc_screen = user32.GetDC(None)
        self._hdc_mem = gdi32.CreateCompatibleDC(self._hdc_screen)
        return bool(self._hdc_mem)

    def _alloc(self, w: int, h: int) -> None:
        gdi32 = layered_win.gdi32
        if self._old and self._hdc_mem:
            gdi32.SelectObject(self._hdc_mem, self._old)
            self._old = None
        if self._hbmp:
            gdi32.DeleteObject(self._hbmp)
            self._hbmp = None
        self._bits = None
        bmi = layered_win.BITMAPINFO()
        bmi.bmiHeader.biSize = layered_win.ctypes.sizeof(layered_win.BITMAPINFOHEADER)
        bmi.bmiHeader.biWidth = w
        bmi.bmiHeader.biHeight = -h
        bmi.bmiHeader.biPlanes = 1
        bmi.bmiHeader.biBitCount = 32
        bmi.bmiHeader.biCompression = layered_win.BI_RGB
        bits = layered_win.ctypes.c_void_p()
        self._hbmp = gdi32.CreateDIBSection(
            self._hdc_mem, layered_win.ctypes.byref(bmi), layered_win.DIB_RGB_COLORS,
            layered_win.ctypes.byref(bits), None, 0,
        )
        if not self._hbmp:
            return
        self._bits = bits
        self._old = gdi32.SelectObject(self._hdc_mem, self._hbmp)
        self._bw, self._bh = w, h

    def _present(self, img: Image.Image, left: int, top: int, below: int, *, raise_windows: bool = True) -> None:
        if not self._hwnd:
            return
        qw, qh = _quantum(img.width), _quantum(img.height)
        if qw != self._bw or qh != self._bh or not self._bits:
            self._alloc(qw, qh)
        if not self._bits:
            return
        canvas = Image.new("RGBA", (qw, qh), (0, 0, 0, 0))
        canvas.paste(img, (0, 0))
        raw = _to_bgra(canvas)
        layered_win.ctypes.memmove(self._bits, raw, len(raw))
        pt_dst = layered_win.POINT(int(left), int(top))
        size = layered_win.SIZE(qw, qh)
        pt_src = layered_win.POINT(0, 0)
        blend = layered_win.BLENDFUNCTION(layered_win.AC_SRC_OVER, 0, 255, layered_win.AC_SRC_ALPHA)
        layered_win.user32.UpdateLayeredWindow(
            self._hwnd,
            self._hdc_screen,
            layered_win.ctypes.byref(pt_dst),
            layered_win.ctypes.byref(size),
            self._hdc_mem,
            layered_win.ctypes.byref(pt_src),
            0,
            layered_win.ctypes.byref(blend),
            layered_win.ULW_ALPHA,
        )
        if not self._shown:
            layered_win.user32.ShowWindow(self._hwnd, layered_win.SW_SHOWNOACTIVATE)
            self._shown = True
            self._top = False
        if not raise_windows:
            # 菜单自己也是置顶的。这时再抬尾巴或卡片，菜单会被压住。菜单关掉后下一帧再抬回来。
            self._top = False
            self._card_up = False
            return
        self._raise_card(below, left, top, qw, qh)

    def _raise_card(self, below: int, left: int, top: int, w: int, h: int) -> None:
        if not self._hwnd:
            return
        flags = SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE
        user32 = layered_win.user32
        if not self._top:
            user32.SetWindowPos(self._hwnd, layered_win.HWND_TOPMOST, 0, 0, 0, 0, flags)
            self._top = True
        overlap = bool(below) and _overlaps(below, left, top, w, h)
        if overlap and not self._card_up:
            user32.SetWindowPos(below, layered_win.HWND_TOPMOST, 0, 0, 0, 0, flags)
            self._card_up = True
        elif not overlap:
            self._card_up = False

    def _hide(self) -> None:
        if self._shown and self._hwnd:
            layered_win.user32.ShowWindow(self._hwnd, SW_HIDE)
        self._shown = False
        self._top = False
        self._card_up = False
        self._pts.clear()
        self._has = False
        self._key = None

    def _pump(self) -> None:
        if not self._hwnd:
            return
        user32 = layered_win.user32
        msg = layered_win.MSG()
        while user32.PeekMessageW(layered_win.ctypes.byref(msg), self._hwnd, 0, 0, layered_win.PM_REMOVE):
            user32.TranslateMessage(layered_win.ctypes.byref(msg))
            user32.DispatchMessageW(layered_win.ctypes.byref(msg))

    def _wnd_proc(self, hwnd, msg, wparam, lparam):
        if msg in (layered_win.WM_CLOSE, layered_win.WM_DESTROY):
            return 0
        return layered_win.user32.DefWindowProcW(hwnd, msg, wparam, lparam)


def _cursor() -> tuple[float, float]:
    pt = layered_win.POINT()
    layered_win.user32.GetCursorPos(layered_win.ctypes.byref(pt))
    return float(pt.x), float(pt.y)


def _pull_head(points: list[tuple[float, float]], gap: float) -> list[tuple[float, float]]:
    """把头从窗口中心沿来路收回 gap 像素，箭头尖留给系统光标。"""
    if len(points) < 2 or gap <= 0:
        return points
    hx, hy = points[-1]
    px, py = points[-2]
    vx, vy = hx - px, hy - py
    norm = math.hypot(vx, vy)
    if norm < 0.5:
        return points
    hx -= vx / norm * gap
    hy -= vy / norm * gap
    return points[:-1] + [(hx, hy)]


def _overlaps(hwnd: int, left: int, top: int, w: int, h: int) -> bool:
    rect = layered_win.RECT()
    if not layered_win.user32.GetWindowRect(hwnd, layered_win.ctypes.byref(rect)):
        return False
    right = left + w
    bottom = top + h
    return not (right < rect.left or left > rect.right or bottom < rect.top or top > rect.bottom)


def preview() -> None:
    """单独跑一条尾巴，按还剩时间从 8 小时收到 0 再拉开。Esc 退出。"""
    import ctypes

    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
    except Exception:
        pass
    trail = Trail()
    print("尾巴在光标后面。长度会在大约 24 秒里从 8 小时收到 0，再拉开。按 Esc 关掉。")
    started = time.monotonic()
    try:
        while True:
            if layered_win.user32.GetAsyncKeyState(0x1B) & 0x8000:
                break
            phase = ((time.monotonic() - started) % 24) / 24
            tri = phase * 2
            if tri > 1:
                tri = 2 - tri
            trail.tick(tri * 8 * 3600, visible=True)
            time.sleep(1 / 60)
    finally:
        trail.destroy()


if __name__ == "__main__":
    preview()
