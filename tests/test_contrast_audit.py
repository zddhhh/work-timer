"""全皮肤对比度审计：逻辑色 + 渲染采样。运行：python -m tests.test_contrast_audit"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import fx  # noqa: E402
import themes  # noqa: E402
from PIL import Image, ImageFont  # noqa: E402

STAGES = ("idle", "run", "warn", "done")
SURFACES = ("dark", "light")
SIZES = ((148, 55), (248, 92), (400, 140))
TITLE = "距离下班"
BIG = "1时28分45秒"


def _luma(rgb: tuple[int, ...]) -> float:
    return 0.2126 * rgb[0] + 0.7152 * rgb[1] + 0.0722 * rgb[2]


def _accent(theme: themes.Theme, stage: str) -> tuple[int, int, int, int]:
    if stage == "idle":
        return theme.idle
    if stage == "done":
        return theme.done
    if stage == "warn":
        return theme.warn
    return theme.big


def audit_logic() -> list[str]:
    fails: list[str] = []
    for th in themes.list_themes():
        for surface in SURFACES:
            theme = themes.resolve_for_surface(th, surface)
            ctx = themes.skin_adapt_context(theme, surface)
            for stage in STAGES:
                title_c = themes.adapt_text_color(
                    theme.title, ctx, kind=theme.kind, stage=stage,
                )
                acc_c = themes.adapt_text_color(
                    _accent(theme, stage), ctx, kind=theme.kind, stage=stage,
                )
                for label, c in (("title", title_c), ("accent", acc_c)):
                    lum = _luma(c[:3])
                    if ctx.card_light and lum > 130:
                        fails.append(f"{th.id} {surface} {stage} {label} too bright lum={lum:.0f}")
                    if not ctx.card_light and lum < 150:
                        fails.append(f"{th.id} {surface} {stage} {label} too dim lum={lum:.0f}")
    return fails


def audit_render() -> list[str]:
    fails: list[str] = []
    font = ImageFont.load_default()
    title_h = fx._font_line_height(font, TITLE)
    for th in themes.list_themes():
        for surface in SURFACES:
            theme = themes.resolve_for_surface(th, surface)
            ctx = themes.skin_adapt_context(theme, surface)
            bg = (180, 190, 200, 255) if surface == "light" else (30, 34, 42, 255)
            for w, h in SIZES:
                for stage in STAGES:
                    img = Image.new("RGBA", (w, h), bg)
                    try:
                        themes.paint_card(
                            img, w, h, theme, TITLE, BIG, "",
                            _accent(theme, stage),
                            font, font, font,
                            stage=stage,
                            surface=surface,
                            flip_anims={},
                            flip_now=0.0,
                            flip_hit_rects=[],
                        )
                    except Exception as e:  # noqa: BLE001
                        fails.append(f"{th.id} {surface} {w}x{h} {stage}: {e}")
                        continue
                    if themes.use_flip_display(th.kind, BIG, h=h):
                        ty, _, ry, _, rh = fx.flip_row_layout(
                            w, h, title_h=title_h, has_sub=False,
                        )
                        title_band = img.crop((0, ty, w, min(h, ty + title_h + 8)))
                        flip_band = img.crop((0, ry, w, min(h, ry + rh)))
                    else:
                        title_band = img.crop((0, 8, w, h // 3))
                        flip_band = title_band

                    def score(band: Image.Image, want_dark: bool) -> int:
                        px = [p for p in band.getdata() if p[3] > 100]
                        if not px:
                            return 0
                        if want_dark:
                            return sum(1 for p in px if _luma(p[:3]) < 130)
                        return sum(1 for p in px if _luma(p[:3]) > 150)

                    want_dark = ctx.card_light
                    if score(title_band, want_dark) < 4:
                        fails.append(
                            f"{th.id} {surface} {w}x{h} {stage}: title low contrast",
                        )
                    if themes.use_flip_display(th.kind, BIG, h=h):
                        if score(flip_band, want_dark) < 6:
                            fails.append(
                                f"{th.id} {surface} {w}x{h} {stage}: flip low contrast",
                            )
                    if h >= 104 and rh > 58:
                        fails.append(
                            f"{th.id} {w}x{h}: flip row too tall ({rh})",
                        )
    return fails


def main() -> int:
    logic = audit_logic()
    render = audit_render()
    fails = logic + render
    if fails:
        print("FAIL", len(fails))
        for line in fails[:50]:
            print(" ", line)
        if len(fails) > 50:
            print(f"  ... +{len(fails) - 50} more")
        return 1
    n = len(themes.list_themes()) * len(SURFACES) * len(STAGES)
    print(f"OK: logic {n} + render {n * len(SIZES)} combos")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
