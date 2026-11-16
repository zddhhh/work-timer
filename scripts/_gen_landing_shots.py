"""导出官网用透明底真卡片（本机 paint_card，页面再用 CSS 托氛围）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from PIL import Image, ImageFont

import themes

OUT = ROOT / "scf" / "subscribe" / "page" / "shots"
OUT.mkdir(parents=True, exist_ok=True)

# 2x 渲染，页面按 CSS 缩小，边缘更利落
SCALE = 2
CARD_W = 280 * SCALE
CARD_H = 104 * SCALE


def _font(size: int) -> ImageFont.ImageFont:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("msyhbd.ttc", "msyh.ttc", "simhei.ttf"):
        try:
            return ImageFont.truetype(str(windir / name), size * SCALE)
        except OSError:
            continue
    return ImageFont.load_default()


def _save(name: str, theme_id: str, title: str, big: str, *, tally=None) -> None:
    theme = next(t for t in themes._bundled_themes() if t.id == theme_id)
    card = Image.new("RGBA", (CARD_W, CARD_H), (0, 0, 0, 0))
    themes.paint_card(
        card, CARD_W, CARD_H, theme, title, big, "",
        theme.big, _font(12), _font(26), _font(11),
        stage="run",
        tally=tally,
    )
    path = OUT / f"{name}.png"
    card.save(path, "PNG", optimize=True)
    print("wrote", path, card.size)


def main() -> None:
    _save("night", "midnight", "距离您下班还有", "2时14分08秒")
    _save("hero", "ghost", "距离您下班还有", "2时14分08秒", tally=(1284, 86, 12))
    _save("timer", "frost", "距离您下班还有", "01:08:22")
    _save("tally", "midnight", "距离您下班还有", "45分", tally=(3201, 210, 48))
    _save("warm", "warmglow", "距离您下班还有", "1时32分")
    print("ok", OUT)


if __name__ == "__main__":
    main()
