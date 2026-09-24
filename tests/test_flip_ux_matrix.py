"""翻牌全局化体验矩阵：多皮肤 × 多尺寸冒烟。运行：python -m tests.test_flip_ux_matrix"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fx  # noqa: E402
import ornaments  # noqa: E402
import themes  # noqa: E402
from PIL import Image, ImageFont  # noqa: E402

SIZES = ((148, 55), (180, 68), (248, 92), (320, 110), (400, 140))
BIG_SAMPLES = ("1时28分45秒", "11566秒", "28分钟", "2天3时15分")
TITLE = "距离下班"
STAGES = ("idle", "run", "warn", "done")


def main() -> int:
    fails: list[str] = []
    font = ImageFont.load_default()
    title_h = fx._font_line_height(font, TITLE)

    for th in themes.list_themes():
        for big in BIG_SAMPLES:
            for w, h in SIZES:
                if not themes.use_flip_display(th.kind, big, h=h):
                    continue
                title_y, _pad, row_y, _rw, row_h = fx.flip_row_layout(
                    w, h, title_h=title_h, has_sub=False,
                )
                if row_y < title_y + 6:
                    fails.append(f"{th.id} {w}x{h} {big}: row overlaps title")
                for stage in STAGES:
                    hit: list[tuple[int, int, int, int, int]] = []
                    img = Image.new("RGBA", (w, h), (32, 36, 48, 255))
                    try:
                        surface = "light" if w <= 200 else "dark"
                        theme = themes.resolve_for_surface(th, surface)
                        themes.paint_card(
                            img, w, h, theme, TITLE, big, "", theme.big,
                            font, font, font,
                            stage=stage,
                            surface=surface,
                            flip_anims={},
                            flip_now=0.0,
                            flip_hit_rects=hit,
                        )
                    except Exception as e:  # noqa: BLE001
                        fails.append(f"{th.id} {w}x{h} {big} {stage}: {e}")
                        continue
                    if th.kind in themes.INTERACTIVE_SKINS and not hit:
                        fails.append(f"{th.id} {w}x{h} {big}: no flip hit rects")
                    if row_y + row_h < h:
                        band = img.crop((0, row_y, w, min(h, row_y + row_h)))
                        if th.id == "inkpulse" and w <= 200:
                            bright = sum(1 for p in band.getdata() if p[3] > 80 and sum(p[:3]) > 420)
                            if bright < 8:
                                fails.append(f"inkpulse {w}x{h} {big}: flip digits too dim")
                        if surface == "light" and w <= 200 and stage == "run":
                            dark = sum(
                                1 for p in band.getdata()
                                if p[3] > 140 and 0.2126 * p[0] + 0.7152 * p[1] + 0.0722 * p[2] < 130
                            )
                            if dark < 6:
                                fails.append(f"{th.id} {w}x{h} {big}: flip text too faint on light bg")

    if fails:
        print("FAIL", len(fails))
        for line in fails[:40]:
            print(" ", line)
        if len(fails) > 40:
            print(f"  ... +{len(fails) - 40} more")
        return 1
    n = sum(
        1 for th in themes.list_themes()
        for big in BIG_SAMPLES
        for w, h in SIZES
        if themes.use_flip_display(th.kind, big, h=h)
    )
    print(f"OK: {n} theme×text×size combos × {len(STAGES)} stages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
