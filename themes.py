"""计时器皮肤。默认 ghost：低对比半透明，桌面上不显眼。"""
from __future__ import annotations

from dataclasses import dataclass

from PIL import ImageDraw, ImageFont


@dataclass(frozen=True)
class Theme:
    id: str
    name: str
    fill: tuple[int, int, int, int]
    outline: tuple[int, int, int, int]
    title: tuple[int, int, int, int]
    big: tuple[int, int, int, int]
    sub: tuple[int, int, int, int]
    idle: tuple[int, int, int, int]
    warn: tuple[int, int, int, int]
    done: tuple[int, int, int, int]
    radius: int
    kind: str


THEMES: tuple[Theme, ...] = (
    Theme(
        "ghost", "淡影（默认）",
        (18, 20, 24, 48), (255, 255, 255, 22),
        (210, 214, 220, 140), (232, 234, 238, 190), (190, 194, 200, 120),
        (200, 210, 220, 170), (220, 200, 160, 180), (180, 210, 190, 180),
        18, "ghost",
    ),
    Theme(
        "midnight", "深夜",
        (18, 22, 32, 220), (255, 255, 255, 70),
        (186, 196, 214, 230), (244, 246, 251, 255), (154, 163, 181, 220),
        (90, 168, 255, 255), (255, 214, 102, 255), (88, 214, 141, 255),
        22, "midnight",
    ),
    Theme(
        "frost", "霜白",
        (236, 244, 252, 150), (120, 170, 220, 90),
        (70, 100, 140, 200), (30, 55, 90, 230), (90, 120, 150, 180),
        (40, 100, 170, 230), (160, 90, 30, 230), (20, 130, 90, 230),
        22, "frost",
    ),
    Theme(
        "neon", "霓虹",
        (6, 8, 18, 220), (0, 230, 200, 160),
        (150, 240, 230, 230), (255, 90, 190, 255), (110, 170, 190, 210),
        (0, 240, 210, 255), (255, 220, 50, 255), (80, 255, 180, 255),
        18, "neon",
    ),
    Theme(
        "terminal", "终端",
        (4, 12, 6, 230), (40, 180, 70, 160),
        (80, 160, 90, 220), (90, 255, 120, 255), (70, 140, 80, 200),
        (120, 255, 140, 255), (210, 255, 90, 255), (170, 255, 140, 255),
        8, "terminal",
    ),
)

THEME_BY_ID = {t.id: t for t in THEMES}
DEFAULT_THEME_ID = "ghost"


def get_theme(theme_id: str) -> Theme:
    return THEME_BY_ID.get(theme_id) or THEME_BY_ID[DEFAULT_THEME_ID]


def paint_card(
    d: ImageDraw.ImageDraw,
    w: int,
    h: int,
    theme: Theme,
    title: str,
    big: str,
    sub: str,
    accent: tuple[int, int, int, int],
    font_title: ImageFont.ImageFont,
    font_big: ImageFont.ImageFont,
    font_sub: ImageFont.ImageFont,
) -> None:
    box = (4, 4, w - 5, h - 5)
    d.rounded_rectangle(box, radius=theme.radius, fill=theme.fill)
    if theme.kind != "ghost":
        d.rounded_rectangle(box, radius=theme.radius, outline=theme.outline, width=1)

    if theme.kind == "neon":
        d.rounded_rectangle((6, 6, 10, h - 7), radius=2, fill=(255, 40, 180, 200))
    elif theme.kind == "terminal":
        for y in range(8, h - 8, 4):
            d.line((8, y, w - 9, y), fill=(0, 40, 10, 40), width=1)
    elif theme.kind == "frost":
        d.rounded_rectangle((8, 8, w - 9, 26), radius=10, fill=(255, 255, 255, 70))

    d.text((24, 16), title, font=font_title, fill=theme.title)
    d.text((24, 44), big, font=font_big, fill=accent)
    d.text((24, 92), sub, font=font_sub, fill=theme.sub)
