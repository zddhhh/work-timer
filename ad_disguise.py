"""ESC 老板键：伪装成常见广告弹窗。"""
from __future__ import annotations

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

import layered_win

AD_W = 420
AD_H = 268


def _font(size: int, bold: bool = False) -> ImageFont.ImageFont:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    names = ("msyhbd.ttc", "msyh.ttc") if bold else ("msyh.ttc", "msyh.ttf", "msyhbd.ttc")
    for name in names:
        try:
            return ImageFont.truetype(str(windir / name), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rgba_to_bgra(img: Image.Image) -> tuple[bytes, bytes]:
    w, h = img.size
    raw = img.tobytes("raw", "RGBA")
    bgra = bytearray(w * h * 4)
    mask = bytearray(w * h)
    for i in range(w * h):
        r, g, b, a = raw[i * 4 : i * 4 + 4]
        bgra[i * 4 + 0] = (b * a) // 255
        bgra[i * 4 + 1] = (g * a) // 255
        bgra[i * 4 + 2] = (r * a) // 255
        bgra[i * 4 + 3] = a
        mask[i] = a
    return bytes(bgra), bytes(mask)


def _render() -> tuple[bytes, bytes]:
    img = Image.new("RGBA", (AD_W, AD_H), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle((0, 0, AD_W - 1, AD_H - 1), radius=10, fill=(255, 255, 255, 255))
    d.rectangle((0, 0, AD_W, 42), fill=(232, 84, 48, 255))
    title = _font(16, bold=True)
    body = _font(14)
    small = _font(12)
    d.text((16, 11), "精选推荐", font=title, fill=(255, 255, 255, 255))
    d.text((AD_W - 36, 8), "×", font=title, fill=(255, 255, 255, 255))
    d.text((24, 64), "办公加速限时福利", font=title, fill=(32, 32, 32, 255))
    d.text((24, 98), "检测到您的电脑可领取本月专属加速包", font=body, fill=(90, 90, 90, 255))
    d.text((24, 124), "关闭本窗口即可继续使用。", font=body, fill=(90, 90, 90, 255))
    d.rounded_rectangle((24, 178, AD_W - 25, 228), radius=8, fill=(232, 84, 48, 255))
    d.text((158, 190), "立即关闭", font=title, fill=(255, 255, 255, 255))
    d.text((24, 238), "广告  ·  关闭后不再提示", font=small, fill=(160, 160, 160, 255))
    return _rgba_to_bgra(img)


class AdDisguise:
    def __init__(self) -> None:
        self.win = layered_win.LayeredPetWindow(
            AD_W, AD_H, "精选推荐", class_name="WorkTimerAdWnd", visible=False
        )
        bgra, mask = _render()
        self._place_bottom_right()
        self.win.present_bgra(bgra, mask)
        self.visible = False
        self._on_dismiss = None
        self.win.set_left_click_handler(self._clicked)
        self.win.set_right_click_handler(lambda *_a: self._clicked())

    def set_dismiss_handler(self, fn) -> None:
        self._on_dismiss = fn

    def _clicked(self) -> None:
        if self._on_dismiss:
            self._on_dismiss()

    def _place_bottom_right(self) -> None:
        area = layered_win.work_area()
        margin = 18
        x = int(area.right - AD_W - margin)
        y = int(area.bottom - AD_H - margin)
        self.win.move(x, y)

    def show(self) -> None:
        self.visible = True
        self._place_bottom_right()
        self.win.show()
        self.win.keep_topmost()

    def hide(self) -> None:
        self.visible = False
        self.win.hide()

    def pump(self) -> None:
        self.win.pump()

    def destroy(self) -> None:
        self.win.destroy()
