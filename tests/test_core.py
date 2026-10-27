"""纯函数回归：不开窗、不联网。运行：.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v"""
from __future__ import annotations

import os
import sys
import tempfile
import unittest
import urllib.error
from datetime import date, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import attachments  # noqa: E402
import feedback  # noqa: E402
import festival  # noqa: E402
import store  # noqa: E402
import flex_time  # noqa: E402
import hydrate  # noqa: E402
import key_hide  # noqa: E402
import uninstall  # noqa: E402
import ornaments  # noqa: E402
import schedules  # noqa: E402
import themes  # noqa: E402
import updater  # noqa: E402
import worklog  # noqa: E402
from PIL import Image  # noqa: E402


class VersionTests(unittest.TestCase):
    def test_parse_and_compare(self):
        self.assertEqual(updater.parse_version("v1.0.91")[:3], (1, 0, 91))
        self.assertTrue(updater.is_newer("1.0.92", "1.0.91"))
        self.assertFalse(updater.is_newer("1.0.91", "1.0.91"))
        self.assertTrue(updater.is_newer("1.1.0", "1.0.99"))
        # 预发布排在同号正式版之前
        self.assertFalse(updater.is_newer("1.0.92-beta", "1.0.92"))
        self.assertTrue(updater.is_newer("1.0.92", "1.0.92-beta"))
        self.assertTrue(updater.is_newer("1.0.92-beta", "1.0.91"))
        self.assertTrue(updater.is_newer("1.0.92-beta.2", "1.0.91"))

    def test_pick_asset(self):
        assets = [{"name": "readme.txt"}, {"name": "worktimer.EXE"}]
        self.assertEqual(updater._pick_asset(assets, "WorkTimer.exe")["name"], "worktimer.EXE")
        self.assertIsNone(updater._pick_asset([], "WorkTimer.exe"))

    def test_sha256_from_body(self):
        h = "a" * 64
        self.assertEqual(updater._sha256_from_body(f"note\n\nsha256: {h}\n"), h)
        self.assertEqual(updater._sha256_from_body("no hash here"), "")
        self.assertEqual(updater._sha256_from_body(f"sha256：{h}"), h)

    def test_sha256_per_asset(self):
        a, b = "a" * 64, "b" * 64
        body = f"note\n\nsha256(WorkTimer-Setup.exe): {a}\nsha256(WorkTimer-Win7-Setup.exe): {b}\n\nsha256: {a}\n"
        self.assertEqual(updater._sha256_from_body(body, "WorkTimer-Setup.exe"), a)
        self.assertEqual(updater._sha256_from_body(body, "workTimer-win7-setup.EXE"), b)
        hidden = f"# sha256(WorkTimer-Setup.exe): {a}\n# sha256: {a}\n"
        self.assertEqual(updater._sha256_from_body(hidden, "WorkTimer-Setup.exe"), a)
        import changelog

        self.assertEqual(changelog.highlights(hidden), [])
        # 有按附件列的哈希但没列这个附件：宁可不校验，也不能拿别的包的哈希去比
        self.assertEqual(updater._sha256_from_body(body, "Other.exe"), "")

    def test_normalize_proxies(self):
        got = updater._normalize_proxies({"http": "http://127.0.0.1:1", "https": "https://127.0.0.1:1"})
        self.assertEqual(got["https"], "http://127.0.0.1:1")
        self.assertEqual(got["http"], "http://127.0.0.1:1")
        self.assertEqual(updater._normalize_proxies({}), {})

    def test_pick_asset_exact_only(self):
        assets = [{"name": "WorkTimer-Setup.exe"}, {"name": "WorkTimer-Win7-Setup.exe"}]
        self.assertEqual(updater._pick_asset(assets, "WorkTimer-Win7-Setup.exe")["name"], "WorkTimer-Win7-Setup.exe")
        self.assertIsNone(updater._pick_asset(assets, "WorkTimer.exe"))

    def test_looks_like_exe(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "x.bin"
            p.write_bytes(b"MZ" + b"\0" * 10)
            self.assertTrue(updater._looks_like_exe(p))
            p.write_bytes(b"<html>")
            self.assertFalse(updater._looks_like_exe(p))

    def test_safe_error_strips_url(self):
        msg = updater._safe_error(RuntimeError("bad https://x/y?access_token=abc end"))
        self.assertNotIn("access_token", msg)
        self.assertIn("<url>", msg)


class FestivalScheduleTests(unittest.TestCase):
    def _cfg(self):
        return {"schedules": [], "pin_order": ["offwork"], "theme": "ghost", "active_pin_id": "offwork"}

    def test_seasons_do_not_overlap(self):
        self.assertTrue(festival.midautumn_in_season(datetime(2026, 9, 27)))
        self.assertFalse(festival.national_in_season(datetime(2026, 9, 27)))
        self.assertTrue(festival.national_in_season(datetime(2026, 9, 28)))
        self.assertTrue(festival.midautumn_past_season(datetime(2026, 9, 28)))
        self.assertTrue(festival.national_past_season(datetime(2026, 10, 9)))

    def test_sync_three_phases(self):
        cfg = self._cfg()
        self.assertTrue(schedules.sync_festival(cfg, now=datetime(2026, 9, 18)))
        self.assertEqual(cfg["theme"], "midautumn")
        self.assertIn("midautumn", cfg["pin_order"])
        self.assertTrue(schedules.sync_festival(cfg, now=datetime(2026, 9, 28)))
        self.assertEqual(cfg["theme"], "nationalday")
        ids = [s["id"] for s in cfg["schedules"]]
        self.assertNotIn("midautumn", ids)
        self.assertIn("nationalday", ids)
        self.assertTrue(schedules.sync_festival(cfg, now=datetime(2026, 10, 9)))
        self.assertEqual(cfg["theme"], "ghost")
        self.assertEqual(cfg["schedules"], [])
        # 过季状态键清干净，再跑一次不该再有改动
        self.assertFalse(any(k.startswith(("midautumn_", "nationalday_", "theme_before_")) for k in cfg))
        self.assertFalse(schedules.sync_festival(cfg, now=datetime(2026, 10, 10)))

    def test_next_year_retriggers(self):
        cfg = self._cfg()
        schedules.sync_festival(cfg, now=datetime(2026, 9, 18))
        schedules.sync_festival(cfg, now=datetime(2026, 12, 1))
        self.assertEqual(cfg["theme"], "ghost")
        self.assertTrue(schedules.sync_festival(cfg, now=datetime(2027, 9, 10)))
        self.assertEqual(cfg["theme"], "midautumn")
        item = schedules.find_schedule(cfg, "midautumn")
        self.assertEqual(item["date"], "2027-09-15")

    def test_stale_item_date_refreshed(self):
        cfg = self._cfg()
        item = schedules.new_clock("中秋", 19, 0, date="2025-10-06")
        item["id"] = "midautumn"
        cfg["schedules"].append(item)
        schedules.sync_festival(cfg, now=datetime(2026, 9, 18))
        self.assertEqual(schedules.find_schedule(cfg, "midautumn")["date"], "2026-09-25")

    def test_user_edited_festival_item_is_kept(self):
        cfg = self._cfg()
        schedules.sync_festival(cfg, now=datetime(2026, 9, 18))
        item = schedules.find_schedule(cfg, "midautumn")
        item["date"], item["hm"] = "2026-09-26", [21, 30]
        for day in (19, 20, 21):
            schedules.sync_festival(cfg, now=datetime(2026, 9, day))
            item = schedules.find_schedule(cfg, "midautumn")
            self.assertEqual(item["date"], "2026-09-26")
            self.assertEqual(item["hm"], [21, 30])

    def test_stale_item_keeps_custom_time(self):
        cfg = self._cfg()
        item = schedules.new_clock("中秋", 21, 30, date="2025-10-06")
        item["id"] = "midautumn"
        cfg["schedules"].append(item)
        schedules.sync_festival(cfg, now=datetime(2026, 9, 18))
        item = schedules.find_schedule(cfg, "midautumn")
        self.assertEqual(item["date"], "2026-09-25")
        self.assertEqual(item["hm"], [21, 30])

    def test_unknown_year_has_no_midautumn(self):
        self.assertFalse(festival.midautumn_in_season(datetime(2099, 9, 20)))
        self.assertTrue(festival.national_in_season(datetime(2099, 10, 1)))
        cfg = self._cfg()
        schedules.sync_festival(cfg, now=datetime(2099, 9, 20))
        self.assertIsNone(schedules.find_schedule(cfg, "midautumn"))

    def test_manual_theme_not_overridden(self):
        cfg = self._cfg()
        cfg["theme"] = "neon"
        schedules.sync_festival(cfg, now=datetime(2026, 9, 28))
        self.assertEqual(cfg["theme"], "neon")

    def test_locked_schedule_cannot_be_removed(self):
        cfg = self._cfg()
        schedules.sync_festival(cfg, now=datetime(2026, 9, 28))
        schedules.remove_schedule(cfg, "nationalday")
        self.assertIsNotNone(schedules.find_schedule(cfg, "nationalday"))
        schedules.remove_schedule(cfg, "nationalday", force=True)
        self.assertIsNone(schedules.find_schedule(cfg, "nationalday"))

    def test_bonus_pins_do_not_count(self):
        cfg = self._cfg()
        # offwork 自身占 1 个名额，再加 2 条到顶
        for i in range(2):
            item = schedules.new_clock(f"t{i}", 10, 0, date="2026-09-18")
            schedules.add_schedule(cfg, item)
            ok, _ = schedules.set_pinned(cfg, item["id"], True)
            self.assertTrue(ok)
        extra = schedules.new_clock("t9", 10, 0, date="2026-09-18")
        schedules.add_schedule(cfg, extra)
        ok, msg = schedules.set_pinned(cfg, extra["id"], True)
        self.assertFalse(ok)
        self.assertIn("3", msg)
        schedules.sync_festival(cfg, now=datetime(2026, 9, 28))
        self.assertIn("nationalday", cfg["pin_order"])


class ThemeTests(unittest.TestCase):
    def test_parse_catalog_unknown_kind_falls_back(self):
        items = themes._parse_catalog({"themes": [{"id": "x", "name": "X", "kind": "nope"}]})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0].kind, "glass")

    def test_merge_keeps_bundled_when_remote_incomplete(self):
        bundled = themes._load_json_file(ROOT / "themes.json")
        self.assertTrue(bundled)
        remote = [t for t in bundled if t.id == "glass"]
        merged = themes._merge_with_bundled(remote, bundled)
        ids = [t.id for t in merged]
        self.assertIn("ghost", ids)
        self.assertIn("nationalday", ids)
        self.assertLessEqual(len(merged), 17)

    def test_removed_ids_filtered_and_normalized(self):
        items = themes._parse_catalog({"themes": [
            {"id": "auto", "name": "自适应", "kind": "ghost"},
            {"id": "sky", "name": "天色", "kind": "glass"},
            {"id": "glass", "name": "玻璃", "kind": "glass"},
        ]})
        self.assertEqual([t.id for t in items], ["glass"])
        self.assertEqual(themes.normalize_id("auto"), "ghost")
        self.assertEqual(themes.normalize_id("sky"), "ghost")
        self.assertEqual(themes.normalize_id("neon"), "neon")
        self.assertNotIn("auto", [t.id for t in themes._load_json_file(ROOT / "themes.json")])

    def test_merge_prefers_bundled_colors(self):
        bundled = themes._load_json_file(ROOT / "themes.json")
        ghost = next(t for t in bundled if t.id == "ghost")
        tampered = themes.replace(ghost, fill=(1, 2, 3, 4))
        merged = themes._merge_with_bundled([tampered], bundled)
        self.assertEqual(next(t for t in merged if t.id == "ghost").fill, ghost.fill)

    def test_font_size_tracks_window(self):
        base = ornaments.layout_for(248, 92)
        self.assertEqual(base, (15.0, 28.0, 12.0))
        # 加宽 8 像素：以前要凑满约 16 像素才跳一整号，现在只跟着大一点点
        grown = ornaments.layout_for(256, 95)
        self.assertGreater(grown[0], base[0])
        self.assertLess(grown[0] - base[0], 1.0)
        self.assertGreater(grown[1], base[1])
        self.assertLess(grown[1] - base[1], 2.0)


class MeowTests(unittest.TestCase):
    def test_catalog_has_meow_but_json_does_not(self):
        import meow

        self.assertTrue(ornaments.has_skin(meow.KIND))
        self.assertTrue(ornaments.is_animated(meow.KIND))
        self.assertIn("meow", [t.id for t in themes._bundled_themes()])
        # 老版本不认识 meow 会退成玻璃，所以只写在代码里
        self.assertNotIn("meow", [t.id for t in themes._load_json_file(ROOT / "themes.json")])
        self.assertLessEqual(len(themes._bundled_themes()), 17)
        self.assertIn("meow", [t.id for t in themes.menu_sections()["fancy"]])
        self.assertIn("suofen", [t.id for t in themes._bundled_themes()])
        self.assertNotIn("suofen", [t.id for t in themes._load_json_file(ROOT / "themes.json")])
        self.assertIn("发激励啦", [t.name for t in themes.menu_sections()["fancy"]])

    def test_suofen_poke_pays_a_bundle(self):
        import suofen

        lines = {suofen.poke(float(i)) for i in range(12)}
        self.assertGreater(len(lines), 1)
        for line in lines:
            self.assertIn("捆", line)
        self.assertIsNone(suofen.callout(100.0))
        suofen.poke(200.0)
        self.assertIn("捆", suofen.callout(200.2) or "")
        self.assertIsNone(suofen.callout(200.0 + suofen.POP_SEC + 0.1))
        sizes = {suofen._pose("run", t).size for t in (0.2, 3.0, 5.4)}
        self.assertGreaterEqual(len(sizes), 3)

    def test_suofen_line_follows_the_pose(self):
        import suofen

        hold = suofen._talk("run", 0.4)
        side = suofen._talk("run", 2.2)
        bounce = suofen._talk("run", 4.0)
        self.assertIn(hold, suofen._TALK["hold"]["run"])
        self.assertIn(side, suofen._TALK["side"]["run"])
        self.assertIn(bounce, suofen._TALK["bounce"]["run"])
        self.assertEqual(suofen._talk("run", 2.2), suofen._talk("run", 2.8))
        self.assertNotEqual(suofen._talk("run", 2.2), suofen._talk("run", 2.2 + suofen._LOOP))
        self.assertNotEqual(suofen._pose("run", 2.2).size, suofen._pose("run", 7.0).size)
        self.assertGreater(suofen._hop("run", 4.2), suofen._hop("run", 0.05))
        from PIL import ImageDraw

        probe = Image.new("RGBA", (248, 84), (0, 0, 0, 0))
        d = ImageDraw.Draw(probe)
        suofen._bubble(d, 160, 4, 80, 76, 248, 84, "得了五捆激励", pop=True)
        box = probe.getbbox()
        self.assertGreaterEqual(box[0], int(248 * suofen.TEXT_SHARE))
        card = Image.new("RGBA", (320, 120), (0, 0, 0, 0))
        suofen.paint(card, 2.2, stage="run")
        again = suofen._backdrop(320, 120)
        self.assertIs(again, suofen._backdrop(320, 120))

    def test_suofen_paint_waits_for_frames_without_knocking(self):
        import suofen

        saved = (suofen._FRAMES, suofen._DURS, suofen._loading, suofen.ensure_loading)
        suofen._FRAMES = None
        suofen._DURS = None
        suofen._loading = False
        suofen.ensure_loading = lambda: None
        try:
            card = Image.new("RGBA", (320, 120), (0, 0, 0, 0))
            suofen.paint(card, 1.2, stage="run")
            self.assertIsNone(suofen._FRAMES)
            self.assertGreater(card.getpixel((8, 8))[3], 200)
        finally:
            suofen._FRAMES, suofen._DURS, suofen._loading, suofen.ensure_loading = saved

    def test_paint_all_stages_and_sizes(self):
        import meow

        theme = next(t for t in themes._bundled_themes() if t.id == "meow")
        from PIL import ImageFont

        f = ImageFont.load_default()
        for w, h in ((148, 55), (260, 96), (420, 156)):
            for stage, big in (("idle", "点我开始"), ("run", "2时15分30秒"),
                               ("warn", "18分30秒"), ("done", "已到点")):
                troupe = meow.Troupe(seed=1)
                img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                themes.paint_card(
                    img, w, h, theme, "距离下班", big, "", theme.title, f, f, f,
                    stage=stage, meow_troupe=troupe, meow_mins=18,
                    meow_drinking=stage == "run",
                )
                self.assertGreater(img.getpixel((w // 2, h // 2))[3], 200)

    def test_poke_show_and_cheer(self):
        import meow

        t = meow.Troupe(seed=1)
        self.assertIsNone(t.callout(0.0))
        self.assertEqual(t.poke(1.0), "show")
        self.assertEqual(t.callout(1.1), "预备——")
        self.assertEqual(t.poke(1.2), "busy")
        self.assertGreaterEqual(t.fps("run", 1.5), 30)
        self.assertIsNone(t.callout(1.0 + meow.SHOW_E + 0.1))
        self.assertLessEqual(t.fps("run", 1.0 + meow.SHOW_E + 0.1), 12)
        t.cheer(20.0)
        self.assertEqual(t.callout(20.2), "喝过啦，真乖")
        self.assertEqual(t.fps("idle", 30.0), 10)

    def test_resize_freezes_motion_and_reuses_sprites(self):
        import meow

        t = meow.Troupe(seed=1)
        from PIL import ImageFont

        f = ImageFont.load_default()
        theme = next(th for th in themes._bundled_themes() if th.id == "meow")

        def frame(w: int, now: float) -> None:
            h = round(w * 92 / 248)
            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            themes.paint_card(
                img, w, h, theme, "距离下班", "2时15分30秒", "", theme.title, f, f, f,
                stage="run", meow_troupe=t,
            )

        frame(260, 5.0)
        t.resizing(True, 5.0)
        before = len(t._cache)
        for w in range(262, 300, 2):
            frame(w, 9.0)
        # 定格后姿势不变，二十来个尺寸只落到少数几档，不会一只猫一个尺寸各画一张
        self.assertLess(len(t._cache) - before, 20)
        t.resizing(False, 9.0)


class RenderTests(unittest.TestCase):
    def test_rgba_to_bgra_premultiplied(self):
        import main

        img = Image.new("RGBA", (4, 2), (200, 100, 50, 128))
        img.putpixel((0, 0), (255, 255, 255, 0))
        bgra, mask = main._rgba_to_bgra(img)
        self.assertEqual(len(bgra), 4 * 2 * 4)
        self.assertEqual(mask, b"\xff" * 8)
        # 全透明像素 alpha 被抬到 1，不会点穿
        self.assertEqual(bgra[3], 1)
        # 预乘：B=50*128/255≈25
        self.assertEqual(bgra[4], 50 * 128 // 255)
        self.assertEqual(bgra[7], 128)


class DialogAnchorTests(unittest.TestCase):
    """弹窗绕开计时器：工作区固定为 1920×1040 便于断言。"""

    def _anchor(self, x, y, w=248, h=92):
        import main

        a = main._Anchor(x, y, w, h)
        a._work = lambda: (0, 0, 1920, 1040)  # type: ignore[method-assign]
        return a

    def _no_overlap(self, a, x, y, w, h):
        return x + w <= a.x or x >= a.x + a.w or y + h <= a.y or y >= a.y + a.h

    def test_bottom_right_timer_goes_above(self):
        a = self._anchor(1660, 940)
        x, y = a.place(320, 200)
        self.assertTrue(self._no_overlap(a, x, y, 320, 200))
        self.assertLess(y + 200, a.y)  # 放到上面

    def test_top_left_timer_goes_below(self):
        a = self._anchor(20, 20)
        x, y = a.place(320, 200)
        self.assertTrue(self._no_overlap(a, x, y, 320, 200))
        self.assertGreaterEqual(y, a.y + a.h)

    def test_tall_dialog_uses_side(self):
        a = self._anchor(800, 500, 496, 184)  # 大号计时器居中，上下都放不下 620 高
        x, y = a.place(480, 620)
        self.assertTrue(self._no_overlap(a, x, y, 480, 620))

    def test_tuple_compat(self):
        a = self._anchor(100, 100)
        self.assertEqual((a[0], a[1]), (100, 200))
        self.assertTrue(a)

    def test_first_map_stays_offscreen(self):
        import main

        self.assertEqual(main._offscreen_bounds("360x220+12+40"), "360x220+-20000+0")
        self.assertEqual(main._offscreen_bounds("360x220"), "360x220+-20000+0")
        self.assertEqual(main._geom_wh("360x220+12+40"), (360, 220))
        self.assertEqual(main._geom_wh("360x220+-20000+0"), (360, 220))
        self.assertEqual(main._geom_wh("360x220-10+20"), (360, 220))

    def test_refit_grows_and_stays_opaque(self):
        import tkinter as tk

        import main

        root = tk.Tk()
        root.withdraw()
        try:
            dlg = main._card_dialog(root, near=(80, 80), width=220, height=80)
            tk.Label(dlg, text="短", bg=main._CARD_BG, fg=main._CARD_FG).pack()
            main._fit_card(dlg, min_w=200, min_h=80, near=(80, 80))
            self.assertGreaterEqual(float(dlg.attributes("-alpha")), 0.99)
            self.assertGreater(dlg.winfo_x(), -1000)
            h1 = dlg.winfo_height()
            tk.Label(dlg, text="第二行\n" * 8, bg=main._CARD_BG, fg=main._CARD_FG).pack()
            main._fit_card(dlg, min_w=200, min_h=80, near=(80, 80))
            self.assertGreaterEqual(float(dlg.attributes("-alpha")), 0.99)
            self.assertGreater(dlg.winfo_x(), -1000)
            self.assertGreater(dlg.winfo_height(), h1)
        finally:
            root.destroy()


class GameDialogTests(unittest.TestCase):
    def setUp(self):
        import mines

        mines.reset_session()

    def _walk(self, widget, text):
        import tkinter as tk

        if isinstance(widget, (tk.Label, tk.Button)) and widget.cget("text") == text:
            return widget
        for child in widget.winfo_children():
            found = self._walk(child, text)
            if found is not None:
                return found
        return None

    def test_list_and_both_games_show_without_hiding_the_clock(self):
        import time
        import tkinter as tk

        import main
        import mines

        root = tk.Tk()
        root.withdraw()
        calls = {"n": 0}

        def shown(dlg) -> None:
            self.assertGreaterEqual(float(dlg.attributes("-alpha")), 0.99)
            self.assertGreater(dlg.winfo_x(), -1000)
            self.assertTrue(dlg.winfo_viewable())

        def click(dlg, text) -> None:
            widget = self._walk(dlg, text)
            self.assertIsNotNone(widget)
            if isinstance(widget, tk.Button):
                widget.invoke()
            else:
                widget.event_generate("<Button-1>")
            dlg.update()
            time.sleep(0.02)
            dlg.update()

        def modal(dlg, _win, on_frame=None):
            dlg.update()
            if on_frame:
                on_frame()
            shown(dlg)
            self.assertIsNotNone(self._walk(dlg, "小游戏"))
            click(dlg, "扫雷")
            if on_frame:
                on_frame()
            shown(dlg)
            self.assertIsNotNone(self._walk(dlg, "剩余 10"))
            self.assertIsNotNone(self._walk(dlg, "关闭"))
            click(dlg, "中级")
            if on_frame:
                on_frame()
            shown(dlg)
            self.assertIsNotNone(self._walk(dlg, "剩余 40"))
            click(dlg, "返回")
            if on_frame:
                on_frame()
            shown(dlg)
            click(dlg, "高尔夫")
            if on_frame:
                on_frame()
            shown(dlg)
            self.assertIsNotNone(self._walk(dlg, "点亮边的牌接上，或点牌堆翻一张。"))
            self.assertIsNotNone(self._walk(dlg, "关闭"))
            click(dlg, "返回")
            if on_frame:
                on_frame()
            shown(dlg)
            click(dlg, "台球")
            if on_frame:
                on_frame()
            shown(dlg)
            self.assertIsNotNone(self._walk(dlg, "按住白球往后拉，松开就打。"))
            self.assertIsNotNone(self._walk(dlg, "关闭"))
            dlg.destroy()

        mines.open_games(
            root, (80, 80), None,
            dialog=main._card_dialog,
            button=main._card_btn,
            reveal=main._reveal_card,
            modal=modal,
            bg=main._CARD_BG,
            fg=main._CARD_FG,
            muted=main._CARD_MUTED,
            live=lambda: calls.__setitem__("n", calls["n"] + 1),
        )
        self.assertGreaterEqual(calls["n"], 3)
        root.destroy()

    def test_modal_loop_refreshes_clock(self):
        import tkinter as tk

        import main

        root = tk.Tk()
        root.withdraw()
        dlg = tk.Toplevel(root)
        dlg.withdraw()
        hits = {"n": 0}

        class Win:
            def pump(self):
                return None

            def blocked_live(self):
                hits["n"] += 1

            def note_beat(self):
                return None

        main._run_card_modal(dlg, Win(), stop=lambda: hits["n"] >= 2)
        self.assertGreaterEqual(hits["n"], 2)
        root.destroy()

    def test_hide_key_conceals_the_open_card(self):
        import tkinter as tk

        import main

        root = tk.Tk()
        root.withdraw()
        dlg = main._card_dialog(root, near=(80, 80), width=220, height=120)
        tk.Label(dlg, text="弹窗", bg=main._CARD_BG, fg=main._CARD_FG).pack()
        hidden = {"v": False}
        n = {"v": 0}

        class Win:
            def pump(self):
                return None

            def dialog_hidden(self):
                return hidden["v"]

            def note_beat(self):
                n["v"] += 1
                if n["v"] == 2:
                    hidden["v"] = True
                if n["v"] >= 4:
                    dlg.destroy()

        main._reveal_card(dlg, min_w=200, min_h=80, near=(80, 80))
        main._run_card_modal(dlg, Win())
        self.assertTrue(getattr(dlg, "_key_hidden", False))
        root.destroy()

    def test_dismiss_popup_is_safe_without_a_menu(self):
        import layered_win

        self.assertTrue(callable(layered_win.user32.EndMenu))
        win = layered_win.LayeredPetWindow(80, 40, visible=False)
        try:
            win.dismiss_popup()
        finally:
            win.destroy()


class FeedbackTests(unittest.TestCase):
    def test_body_has_contact_and_roundtrip(self):
        body = feedback._compose_body("hi", "  me@x.com   wx:abc ")
        self.assertIn("- 联系：me@x.com wx:abc", body)
        self.assertEqual(feedback.parse_contact(body), "me@x.com wx:abc")
        self.assertNotIn("联系", feedback._compose_body("hi", ""))

    def test_normalize_contact_truncates(self):
        self.assertEqual(len(feedback.normalize_contact("a" * 500)), 120)


class ScheduleFieldTests(unittest.TestCase):
    def test_schedule_countdown_title(self):
        self.assertEqual(schedules.schedule_countdown_title("中秋"), "距离中秋还有")
        self.assertEqual(schedules.schedule_countdown_title("国庆"), "距离国庆还有")
        self.assertEqual(schedules.schedule_countdown_title("中秋", done=True), "中秋 · 到点")
        self.assertEqual(
            schedules.schedule_countdown_title("距离年假还有"),
            "距离年假还有",
        )

    def test_invalid_clock_not_done(self):
        bad = {"kind": "clock", "hm": [99, 0], "date": "2026-09-18"}
        self.assertEqual(schedules.schedule_remaining(bad, datetime(2026, 9, 18)), (0, False))
        self.assertEqual(schedules.format_schedule_when(bad), "时间无效")

    def test_ensure_fields_fills_date_once(self):
        cfg = {"schedules": [{"id": "a", "kind": "clock", "hm": [9, 0]}, {"id": "b", "kind": "clock", "hm": [9, 0], "date": ""}]}
        schedules.ensure_fields(cfg)
        self.assertTrue(cfg["schedules"][0]["date"])
        self.assertEqual(cfg["schedules"][1]["date"], "")


class _TmpStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._orig = store.user_data_dir
        tmp = Path(self._tmp.name)
        store.user_data_dir = lambda: tmp  # type: ignore[assignment]
        store._pending = None
        store._last_write = 0.0

    def tearDown(self):
        store.user_data_dir = self._orig  # type: ignore[assignment]
        store._pending = None
        self._tmp.cleanup()


class StoreTests(_TmpStore):
    def test_tokens_not_persisted_and_debounce(self):
        cfg = {"theme": "ghost", "feedback_token": "f", "gitcode_token": "g"}
        store.save_config(cfg)  # 首次立即落盘
        text = store.config_path().read_text(encoding="utf-8")
        self.assertNotIn("_token", text)
        cfg["theme"] = "neon"
        store.save_config(cfg)  # 1s 内：挂起
        self.assertIn('"ghost"', store.config_path().read_text(encoding="utf-8"))
        self.assertFalse(store.flush_pending())
        self.assertTrue(store.flush_pending(force=True))
        self.assertIn('"neon"', store.config_path().read_text(encoding="utf-8"))
        self.assertFalse(store.flush_pending(force=True))

    def test_legacy_key_migrates(self):
        store.config_path().write_text('{"esc_disguise": true}', encoding="utf-8")
        cfg = store.load_config()
        self.assertTrue(key_hide.enabled(cfg))
        self.assertEqual(key_hide.vk(cfg), 0x11)
        self.assertNotIn("esc_disguise", cfg)
        self.assertNotIn("ctrl_hide", cfg)

    def test_ctrl_hide_migrates(self):
        store.config_path().write_text('{"ctrl_hide": true}', encoding="utf-8")
        cfg = store.load_config()
        self.assertTrue(key_hide.enabled(cfg))
        self.assertEqual(key_hide.vk(cfg), 0x11)
        self.assertNotIn("ctrl_hide", cfg)

    def test_log_keeps_tail(self):
        path = store.user_data_dir() / "error.log"
        path.write_bytes(b"x" * 90_000 + b"\nKEEP\n")
        store.append_log("new")
        data = path.read_bytes()
        self.assertLess(len(data), 41_000)
        self.assertIn(b"KEEP", data)
        self.assertTrue(data.endswith(b"new\n"))


class UninstallTests(unittest.TestCase):
    def test_unique_paths(self):
        a = Path("C:/a")
        got = uninstall._unique_paths([a, a, Path("c:/a")])
        self.assertEqual(len(got), 1)

    def test_summary_has_warning(self):
        self.assertTrue(any("不可恢复" in line for line in uninstall.summary_lines()))

    def test_manifest_has_data_and_legacy_only(self):
        got = {os.path.normcase(str(p)) for p in uninstall.build_manifest()}
        self.assertIn(os.path.normcase(str(store.user_data_dir())), got)
        self.assertIn(os.path.normcase(str(store.legacy_install_dir())), got)
        self.assertFalse(any(p.endswith(".exe") for p in got))

    def test_legacy_cleanup_noop_from_source(self):
        # 源码运行（非安装版）不能去删 LocalAppData 里的东西
        updater.cleanup_legacy_install(Path("C:/nope/WorkTimer.exe"), wait_sec=0)

    def test_legacy_cleanup_installed(self):
        from unittest import mock

        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            app = root / "Programs" / "WorkTimer"
            app.mkdir(parents=True)
            (app / "WorkTimer.exe").write_bytes(b"MZ")
            (app / "unins000.exe").write_bytes(b"MZ")
            legacy = root / "legacy"
            legacy.mkdir()
            for n in ("WorkTimer.exe", "WorkTimer.exe.old", "installed_version.txt"):
                (legacy / n).write_text("x")
            old = root / "Desktop" / "WorkTimer.exe"
            old.parent.mkdir()
            old.write_text("x")
            keep = root / "Desktop" / "notes.txt"
            keep.write_text("x")
            with mock.patch.object(updater, "current_exe_path", return_value=app / "WorkTimer.exe"), \
                    mock.patch.object(store, "legacy_install_dir", return_value=legacy):
                updater.cleanup_legacy_install(old, wait_sec=0)
                # 新安装目录里的 exe 绝不能被当成老版本删掉
                updater.cleanup_legacy_install(app / "WorkTimer.exe", wait_sec=0)
            self.assertFalse(legacy.exists())
            self.assertFalse(old.exists())
            self.assertTrue(keep.exists())
            self.assertTrue((app / "WorkTimer.exe").exists())


class HydrateTests(unittest.TestCase):
    def _cfg(self, **kwargs):
        cfg: dict = {}
        hydrate.ensure_fields(cfg)
        cfg["hydrate"].update(kwargs)
        hydrate.ensure_fields(cfg)
        return cfg

    def test_defaults_off(self):
        cfg: dict = {}
        hydrate.ensure_fields(cfg)
        self.assertFalse(hydrate.enabled(cfg))
        self.assertEqual(hydrate.interval_min(cfg), 45)
        self.assertEqual(hydrate.menu_caption(cfg), "设置喝水久坐提醒…")
        self.assertFalse(hydrate.strengthen(cfg))
        self.assertEqual(hydrate.card_copy(cfg), ("该喝水了", "点一下", "喝过了再点"))

    def test_clamp_interval(self):
        self.assertEqual(hydrate.clamp_interval(0), 15)
        self.assertEqual(hydrate.clamp_interval(999), 180)
        self.assertEqual(hydrate.clamp_interval("x"), 45)

    def test_enable_starts_round_not_due(self):
        cfg: dict = {}
        now = datetime(2026, 10, 13, 10, 0, 0)
        hydrate.set_enabled(cfg, True, now=now)
        self.assertEqual(hydrate.decide(cfg, now), "none")
        later = now.replace(minute=44, second=59)
        self.assertEqual(hydrate.decide(cfg, later), "none")
        due = now.replace(minute=45)
        self.assertEqual(hydrate.decide(cfg, due), "fire")

    def test_stale_cross_day_no_catchup(self):
        cfg = self._cfg(enabled=True, interval_min=45, anchor="2026-10-12T18:00:00")
        now = datetime(2026, 10, 13, 9, 0, 0)
        self.assertEqual(hydrate.decide(cfg, now), "none")
        self.assertTrue(cfg["hydrate"]["anchor"].startswith("2026-10-13T09:00:00"))

    def test_same_day_long_gap_fires_once(self):
        cfg = self._cfg(enabled=True, interval_min=45, anchor="2026-10-13T09:00:00")
        now = datetime(2026, 10, 13, 11, 0, 0)
        self.assertEqual(hydrate.decide(cfg, now), "fire")

    def test_hidden_queues_once(self):
        cfg = self._cfg(enabled=True, interval_min=45, anchor="2026-10-13T09:00:00")
        now = datetime(2026, 10, 13, 9, 50, 0)
        self.assertEqual(hydrate.decide(cfg, now, hidden=True), "none")
        self.assertTrue(cfg["hydrate"]["pending"])
        self.assertEqual(hydrate.decide(cfg, now, hidden=False), "fire")

    def test_after_offwork_silences(self):
        cfg = self._cfg(enabled=True, interval_min=45, anchor="2026-10-13T09:00:00", pending=True)
        now = datetime(2026, 10, 13, 18, 30, 0)
        self.assertEqual(hydrate.decide(cfg, now, after_offwork=True), "none")
        self.assertFalse(cfg["hydrate"]["pending"])

    def test_shift_anchor_keeps_remaining(self):
        cfg = self._cfg(enabled=True, interval_min=45, anchor="2026-10-13T09:00:00")
        now = datetime(2026, 10, 13, 9, 10, 0)
        left = hydrate.interval_sec(cfg) - hydrate.elapsed_sec(cfg, now)
        from datetime import timedelta

        hydrate.shift_anchor(cfg, timedelta(minutes=20))
        later = datetime(2026, 10, 13, 9, 30, 0)
        self.assertAlmostEqual(hydrate.interval_sec(cfg) - hydrate.elapsed_sec(cfg, later), left)

    def test_arm_waits_for_a_click(self):
        cfg = self._cfg(enabled=True, interval_min=45, anchor="2026-10-13T09:00:00")
        now = datetime(2026, 10, 13, 9, 50, 0)
        self.assertEqual(hydrate.decide(cfg, now), "fire")
        hydrate.arm(cfg)
        self.assertTrue(cfg["hydrate"]["pending"])
        self.assertEqual(hydrate.decide(cfg, now), "fire")
        hydrate.reset_anchor(cfg, now)
        self.assertFalse(cfg["hydrate"]["pending"])
        self.assertEqual(hydrate.decide(cfg, now), "none")

    def test_click_reset_restarts_round(self):
        cfg = self._cfg(enabled=True, interval_min=45, anchor="2026-10-13T09:00:00", pending=True)
        now = datetime(2026, 10, 13, 9, 50, 0)
        hydrate.reset_anchor(cfg, now)
        self.assertEqual(hydrate.decide(cfg, now), "none")
        self.assertFalse(cfg["hydrate"]["pending"])

    def test_menu_caption_on(self):
        cfg = self._cfg(enabled=True, interval_min=30)
        self.assertIn("30", hydrate.menu_caption(cfg))
        self.assertFalse(hydrate.strengthen(cfg))
        hydrate.set_strengthen(cfg, True)
        self.assertTrue(hydrate.strengthen(cfg))
        self.assertEqual(hydrate.card_copy(cfg)[1], "起来站一会")
        self.assertIn("含久坐", hydrate.menu_caption(cfg))
        hydrate.set_enabled(cfg, False)
        self.assertTrue(hydrate.strengthen(cfg))

    def test_disable_clears(self):
        cfg = self._cfg(enabled=True, interval_min=45, anchor="2026-10-13T09:00:00", pending=True)
        hydrate.set_enabled(cfg, False)
        self.assertFalse(hydrate.enabled(cfg))
        self.assertEqual(cfg["hydrate"]["anchor"], "")
        self.assertEqual(hydrate.decide(cfg, datetime(2026, 10, 13, 10, 0, 0)), "none")


class KeyHideTests(unittest.TestCase):
    def test_defaults_off_and_backtick(self):
        cfg: dict = {}
        key_hide.ensure_fields(cfg)
        self.assertFalse(key_hide.enabled(cfg))
        self.assertEqual(key_hide.vk(cfg), key_hide.DEFAULT_VK)

    def test_label_and_modifier(self):
        self.assertEqual(key_hide.label(0x11), "Ctrl")
        self.assertTrue(key_hide.is_modifier(0x11))
        self.assertFalse(key_hide.is_modifier(0xC0))

    def test_menu_caption(self):
        cfg = {"key_hide": {"enabled": True, "vk": 0xC0}}
        self.assertIn("`", key_hide.menu_caption(cfg))


class AttachmentGcTests(_TmpStore):
    def test_gc_removes_orphans(self):
        root = store.user_data_dir() / "attachments"
        (root / "schedule_a").mkdir(parents=True)
        (root / "schedule_a" / "keep.jpg").write_bytes(b"1")
        (root / "schedule_a" / "orphan.jpg").write_bytes(b"1")
        (root / "memo_zzz").mkdir()
        (root / "memo_zzz" / "x.jpg").write_bytes(b"1")
        cfg = {"schedules": [{"id": "a", "images": [{"id": "k1", "file": "keep.jpg"}]}], "memos": []}
        self.assertEqual(attachments.gc(cfg), 1)
        self.assertTrue((root / "schedule_a" / "keep.jpg").exists())
        self.assertFalse((root / "schedule_a" / "orphan.jpg").exists())
        self.assertFalse((root / "memo_zzz").exists())


class ConfettiTests(unittest.TestCase):
    def test_confetti_does_not_crash(self):
        img = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
        for tt in (0.0, 1.0, 2.7, 5.0):
            ornaments.paint_confetti(img, 248, 92, tt)
        self.assertEqual(img.size, (248, 92))


class FxTests(unittest.TestCase):
    def test_flag_geometry(self):
        import fx

        flag = fx.flag_image(120)
        self.assertEqual(flag.size, (120, 80))
        # 大星心 (5,5)/30 为金色，右下角为红色，小星之间的空隙为红色
        self.assertEqual(flag.getpixel((20, 20))[:3], fx.FLAG_GOLD)
        self.assertEqual(flag.getpixel((110, 70))[:3], fx.FLAG_RED)
        self.assertEqual(flag.getpixel((44, 44))[:3], fx.FLAG_RED)
        # 四颗小星各自的星心为金色
        for gx, gy in ((10, 2), (12, 4), (12, 7), (10, 9)):
            r, g, b = flag.getpixel((gx * 4, gy * 4))[:3]
            self.assertTrue(r > 240 and g > 180 and b < 60, (r, g, b))

    def test_flag_and_neon_paint(self):
        import fx

        layer = Image.new("RGBA", (248, 92), (160, 20, 24, 255))
        for ph in (0.0, 0.7, 3.3, 10.5):
            for st in ("run", "warn", "done", "idle"):
                fx.paint_national(layer, ph, stage=st, light=(st == "idle"))
                fx.paint_neonflow(layer, ph, stage=st, radius=14)
                fx.paint_inkpulse(layer, ph, stage=st, radius=14)
                fx.paint_flipclock(layer, ph, stage=st, radius=12)
        anims: dict[int, tuple[float, str, str]] = {2: (0.0, "4", "5")}
        fx.paint_flip_row(
            layer, 10, 28, 220, 34, "128时30分45秒", anims, 0.18, fx._flip_font(20),
            (248, 250, 255, 252), stage="run",
        )
        self.assertEqual(layer.size, (248, 92))
        self.assertTrue(ornaments.has_skin("neonflow"))
        self.assertTrue(ornaments.has_skin("inkpulse"))
        self.assertTrue(ornaments.has_skin("flipclock"))
        self.assertTrue(ornaments.is_animated("inkpulse"))
        self.assertTrue(ornaments.is_animated("flipclock"))
        self.assertIn("flipclock", [t.id for t in themes.menu_sections()["fancy"]])
        prev = fx.sync_flip_anims({}, "", "1时00分00秒", 1.0)
        anims2: dict[int, tuple[float, str, str]] = {}
        fx.sync_flip_anims(anims2, prev, "1时00分01秒", 1.0)
        self.assertIn(4, anims2)

    def test_thunder_paint(self):
        import fx

        layer = Image.new("RGBA", (248, 92), (8, 9, 18, 255))
        for st in ("run", "warn", "done", "idle"):
            _a, _c, period, _g = fx._thunder_palette(st)
            for frac in (0.0, 0.12, 0.3, 1.5):
                fx.paint_thunder(layer, period * 2 + frac, stage=st, radius=14, light=(st == "idle"))
        self.assertEqual(layer.size, (248, 92))
        self.assertTrue(ornaments.has_skin("thunder"))
        self.assertTrue(ornaments.is_animated("thunder"))
        self.assertIn("thunder", [t.id for t in themes.menu_sections()["fancy"]])

    def test_thunder_strike_is_brighter_than_calm(self):
        """主放电那一帧必须明显亮过平静帧，否则闪电等于没闪。"""
        import fx

        _a, _c, period, _g = fx._thunder_palette("run")

        def lum(frac):
            layer = Image.new("RGBA", (248, 92), (8, 9, 18, 255))
            fx.paint_thunder(layer, period * 2 + frac, stage="run", radius=14)
            px = layer.convert("L")
            return sum(px.getdata()) / (248 * 92)

        self.assertGreater(lum(0.12), lum(1.5) * 1.5)
        self.assertEqual(fx.thunder_fps("run", period * 2 + 0.12), 60)
        self.assertLess(fx.thunder_fps("run", period * 2 + 1.5), 30)

    def test_click_strike_reaches_border(self):
        """点一下：落点→边框要有亮线传导。"""
        import fx

        layer = Image.new("RGBA", (248, 92), (8, 9, 18, 255))
        fx.paint_thunder_click(layer, 0.38, 120, 46, radius=14, stage="run")
        self.assertGreater(max(layer.getchannel("A").getdata()), 80)
        peak = Image.new("RGBA", (248, 92), (8, 9, 18, 255))
        calm = Image.new("RGBA", (248, 92), (8, 9, 18, 255))
        fx.paint_thunder_click(peak, 0.35, 120, 46, radius=14, stage="run")
        fx.paint_thunder_click(calm, 2.60, 120, 46, radius=14, stage="run")
        self.assertGreater(sum(peak.convert("L").getdata()), sum(calm.convert("L").getdata()))

    def test_click_strike_brighter_than_ambient(self):
        """点击狠雷要比常态落雷亮一截。"""
        import fx

        bw, bh = 248, 92
        click = Image.new("RGBA", (bw, bh), (8, 9, 18, 255))
        fx.paint_thunder_click(click, 0.32, 120, 46, radius=14, stage="run")
        ambient = Image.new("RGBA", (bw, bh), (8, 9, 18, 255))
        _a, _c, period, _g = fx._thunder_palette("run")
        fx.paint_thunder(ambient, period * 2 + 0.12, stage="run", radius=14)
        self.assertGreater(sum(click.convert("L").getdata()), sum(ambient.convert("L").getdata()) * 1.15)

    def test_thunder_combo_stacks_brightness(self):
        """连击叠两道雷应比单道更亮。"""
        import fx

        one = Image.new("RGBA", (248, 92), (8, 9, 18, 255))
        two = Image.new("RGBA", (248, 92), (8, 9, 18, 255))
        fx.paint_thunder_click(one, 0.32, 80, 46, radius=14, stage="run")
        fx.paint_thunder_click(two, 0.32, 80, 46, radius=14, stage="run")
        fx.paint_thunder_click(two, 0.32, 168, 46, radius=14, stage="run")
        self.assertGreater(sum(two.convert("L").getdata()), sum(one.convert("L").getdata()) * 1.08)

    def test_thunder_skin_renamed(self):
        import themes

        th = themes.get_theme("thunder")
        self.assertEqual(th.name, "霹雳狂潮")
        self.assertIn("thunder", [t.id for t in themes.menu_sections()["fancy"]])

    def test_skin_settings_thunder_quote_default_empty(self):
        import skin_settings

        cfg = {}
        self.assertEqual(skin_settings.thunder_quote(cfg), "")
        skin_settings.set_thunder_quote(cfg, "  我命由我不由天  \n")
        self.assertEqual(skin_settings.thunder_quote(cfg), "我命由我不由天")
        skin_settings.set_thunder_quote(cfg, "")
        self.assertEqual(skin_settings.thunder_quote(cfg), "")

    def test_thunder_hit_without_quote_no_glyph_step(self):
        import fx

        hits, nxt = fx.register_thunder_hit([], 100.0, 120, 46, 0, quote="")
        self.assertIsNone(nxt)
        self.assertEqual(len(hits), 1)
        layer = Image.new("RGBA", (248, 92), (8, 9, 18, 255))
        fx.paint_thunder_glyph(layer, (4, 4, 244, 88), 0.35, 0, anchor_x=180, anchor_y=46, quote="")
        self.assertEqual(max(layer.getchannel("A").getdata()), 255)

    def test_thunder_same_spot_merges(self):
        """同处狂点应合并刷新，不能叠满屏。"""
        import fx

        t0 = 100.0
        quote = "我命由我不由天"
        hits, nxt = fx.register_thunder_hit([], t0, 120, 46, 0, quote=quote)
        self.assertEqual(nxt, 1)
        hits, nxt = fx.register_thunder_hit(hits, t0 + 0.05, 122, 47, nxt, quote=quote)
        self.assertIsNone(nxt)
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0][0], t0)
        hits, nxt = fx.register_thunder_hit(hits, t0 + 0.22, 121, 45, 1, quote=quote)
        self.assertEqual(len(hits), 1)
        self.assertAlmostEqual(hits[0][0], t0 + 0.22)
        self.assertGreater(hits[0][3], 1.0)
        self.assertEqual(hits[0][4], 1)

    def test_thunder_far_apart_stacks(self):
        import fx

        t0 = 100.0
        quote = "我命由我不由天"
        hits, nxt = fx.register_thunder_hit([], t0, 50, 46, 0, quote=quote)
        hits, nxt2 = fx.register_thunder_hit(hits, t0 + 0.01, 200, 46, nxt, quote=quote)
        self.assertEqual(len(hits), 2)
        self.assertEqual(nxt2, 2)

    def test_thunder_glyph_single_char(self):
        import fx

        quote = fx.THUNDER_QUOTE_DEFAULT
        layer = Image.new("RGBA", (248, 92), (8, 9, 18, 255))
        box = (4, 4, 244, 88)
        fx.paint_thunder_glyph(layer, box, 0.35, 0, anchor_x=180, anchor_y=46, stage="run", quote=quote)
        a0 = max(layer.getchannel("A").getdata())
        blank = Image.new("RGBA", (248, 92), (8, 9, 18, 255))
        fx.paint_thunder_glyph(blank, box, 3.0, 0, anchor_x=180, anchor_y=46, stage="run", quote=quote)
        self.assertGreater(a0, 24)
        self.assertEqual(max(blank.getchannel("A").getdata()), 255)  # 过期帧不画

    def test_thunder_glyph_follows_anchor(self):
        """左右落点亮的区域应明显分开，不能都被 clamp 到同一角。"""
        import fx

        box = (4, 4, 244, 88)

        def centroid(ax):
            layer = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
            fx.paint_thunder_glyph(
                layer, box, 0.35, 0, anchor_x=ax, anchor_y=46, stage="run", quote=fx.THUNDER_QUOTE_DEFAULT,
            )
            a = layer.getchannel("A")
            xs = [x for y in range(layer.height) for x in range(layer.width) if a.getpixel((x, y)) > 40]
            return sum(xs) / len(xs)

        self.assertGreater(centroid(190), centroid(70) + 80)

    def test_ink_click_visible(self):
        import fx

        layer = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
        fx.paint_ink_click(layer, 0.55, 180, 46, stage="run")
        self.assertGreater(max(layer.getchannel("A").getdata()), 40)

    def test_neon_planets_spawn_and_hit(self):
        import fx

        field = fx.create_neon_planets()
        ammo = fx.create_neon_ammo()
        bw, bh = 240, 84
        t0 = 2000.0
        fx.neon_planets_resize(field, bw, bh, t0)
        self.assertGreaterEqual(len(field.planets), fx.NEON_PLANET_MIN)
        px, py, pr = fx._neon_planet_pos(field.planets[0], t0, bw, bh)  # noqa: SLF001
        fx.neon_try_fire(ammo, t0, px, py, bw=bw, bh=bh, radius=14, phase=t0)
        fx.neon_planets_tick(field, ammo, t0 + fx.NEON_FIRE_SEC * 0.86, bw, bh, t0, colors_n=4)
        self.assertGreater(len(field.explosions), 0)
        self.assertLess(len(field.planets), fx.NEON_PLANET_MIN + 1)

    def test_neon_bullet_shot_cycle(self):
        import fx

        layer = Image.new("RGBA", (248, 92), (8, 9, 18, 255))
        fx.paint_neon_fire_shot(layer, 0.12, 124, 44, 200, 50, col=(0, 232, 255), stage="run")
        self.assertGreater(max(layer.getchannel("A").getdata()), 30)
        ammo = fx.create_neon_ammo()
        t0 = 1000.0
        self.assertTrue(fx.neon_try_fire(ammo, t0, 180, 50, bw=240, bh=84, radius=14, phase=t0))
        self.assertEqual(len(ammo.shots), 1)
        self.assertLess(ammo.present[ammo.shots[0][1]], 0.1)
        fx.neon_tick(ammo, t0 + fx.NEON_FIRE_SEC + 0.4)
        self.assertGreater(ammo.present[ammo.shots[0][1]], 0.2)

    def test_inkpulse_visible(self):
        import fx

        layer = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
        fx.paint_inkpulse(layer, 2.1, stage="run", radius=14)
        alphas = list(layer.getchannel("A").getdata())
        self.assertGreater(max(alphas), 120)
        self.assertGreater(sum(1 for a in alphas if a > 40), 800)
        light = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
        fx.paint_inkpulse(light, 0.4, stage="run", radius=14, light=True)
        self.assertGreater(max(light.getchannel("A").getdata()), 100)

    def test_ridge_ends_return_to_waterline(self):
        """山脊两端必须收回水线，不然闭合多边形会在纸上留一块灰方板。"""
        import fx

        base, amp = 80.0, 40.0
        pts = fx._ridge_poly(10.0, 200.0, base, amp, 1.6, fade_l=0.4, fade_r=0.25)
        ridge = pts[:-2]
        self.assertLess(base - ridge[0][1], amp * 0.06)
        self.assertLess(base - ridge[-1][1], amp * 0.06)
        self.assertGreater(base - min(p[1] for p in ridge), amp * 0.4)
        # 不收口的那端应当留在高处（近山要跑出画外）
        open_end = fx._ridge_poly(10.0, 200.0, base, amp, 5.3, fade_l=0.26, fade_r=0.0)[:-2]
        self.assertGreater(base - open_end[-1][1], amp * 0.1)

    def test_seal_is_carved(self):
        """朱印得是白文：朱底上刻出透明笔画，不能是一块实心红方。"""
        import fx

        seal = fx._seal(22, (190, 52, 38), gain=1.0)
        alphas = list(seal.getchannel("A").getdata())
        self.assertGreater(sum(1 for a in alphas if a > 120), 120)
        self.assertGreater(sum(1 for a in alphas if a == 0), 40)

    def test_release_highlights_strip_noise(self):
        """Release 正文要能变成给人看的几条：版本号标题、sha256、行首标记都得去掉。"""
        import changelog

        digest = "a" * 64
        body = (
            "WorkTimer 1.2.2\n\n"
            "- 墨水涟漪的落墨点移到大数字右边\n"
            "* 更新提示改成人话\n"
            "\n"
            f"sha256(WorkTimer-Setup.exe): {digest}\n"
            f"sha256(WorkTimer-Win7-Setup.exe): {digest}\n"
            f"sha256: {digest}\n"
        )
        got = changelog.highlights(body)
        self.assertEqual(got, ["墨水涟漪的落墨点移到大数字右边", "更新提示改成人话"])
        self.assertEqual(changelog.highlights(""), [])
        self.assertEqual(changelog.highlights("WorkTimer 1.2.2\nsha256: abc"), [])
        self.assertEqual(len(changelog.highlights("- a\n- b\n- c\n- d\n- e\n- f")), 4)

    def test_friendly_update_errors(self):
        """弹窗不该把 HTTPError 原文甩给用户。"""
        cases = {
            "HTTP 404": "暂时还没有新版本",
            "HTTP 403": "现在没法更新",
            "HTTP 502": "更新这边有点忙",
            "HTTP 429": "更新这边有点忙",
            "网络错误：[Errno 11001] getaddrinfo failed": "现在连不上网",
            "连接超时": "现在连不上网",
            "sha256 校验失败": "下载的文件不完整",
            "新版本 1.3.37 还没有上传 WorkTimer-Win7-Setup.exe": "新版本还在准备",
        }
        for raw, head in cases.items():
            self.assertEqual(updater.friendly_error(raw)[0], head, raw)
        self.assertFalse(updater._retryable(urllib.error.URLError(TimeoutError("timed out"))))
        busy = urllib.error.HTTPError("https://example.test", 429, "Too Many", None, None)
        self.assertTrue(updater._retryable(busy))
        self.assertTrue(updater.is_busy_error("HTTP 429"))
        self.assertFalse(updater.is_network_error("HTTP 429"))
        head, hint = updater.friendly_error("something exploded")
        self.assertEqual(head, "这次没更新成功")
        self.assertNotIn("exploded", hint)

    def test_menu_sections_cover_catalog(self):
        secs = themes.menu_sections()
        flat = [t.id for grp in secs.values() for t in grp]
        self.assertEqual(sorted(flat), sorted(t.id for t in themes.list_themes()))
        self.assertEqual(len(flat), len(set(flat)))
        self.assertEqual({t.id for t in secs["festival"]}, {"midautumn", "nationalday"})
        self.assertIn("ghost", [t.id for t in secs["classic"]])
        self.assertTrue(all(len(t.name) <= 2 for t in secs["classic"]))
        self.assertIn("neonflow", [t.id for t in secs["fancy"]])
        self.assertIn("inkpulse", [t.id for t in secs["fancy"]])
        self.assertTrue(all(len(t.name) >= 3 for t in secs["fancy"]))

    def test_flip_digits_global(self):
        self.assertTrue(themes.use_flip_display("ghost", "1时30分"))
        self.assertFalse(themes.use_flip_display("ghost", "点我开始"))
        self.assertTrue(themes.use_flip_display("neon", "11566秒", h=48))
        self.assertIn("neonflow", themes.INTERACTIVE_SKINS)

    def test_flip_row_larger_than_before(self):
        import fx

        font = fx._flip_font(14)
        title_h = fx._font_line_height(font, "距离下班")
        _, _, _, _, row_h = fx.flip_row_layout(248, 92, title_h=title_h, has_sub=False)
        self.assertGreaterEqual(row_h, 36)

    def test_flip_layout_keeps_title_clear(self):
        import fx

        font = fx._flip_font(14)
        title_h = fx._font_line_height(font, "距离下班")
        for h in (55, 62, 72, 92, 120):
            title_y, _pad, row_y, _rw, row_h = fx.flip_row_layout(248, h, title_h=title_h, has_sub=False)
            self.assertGreaterEqual(row_y, title_y + title_h + 2, (h, title_y, row_y, row_h))
            self.assertLessEqual(row_y + row_h, h - 4, (h, row_y, row_h))

    def test_flip_overlay_transparency(self):
        import fx

        self.assertGreaterEqual(fx.FLIP_OVERLAY_ALPHA, 130)
        layer = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
        fx.paint_flip_row(
            layer, 10, 30, 220, 40, "1时30分45秒", {}, 0.0,
            fx._flip_font(16), (240, 250, 255, 252),
            overlay=True, bare_digits=False,
        )
        # 叠层牌面应比旧版更实，但仍能透底（数字描边可以很实，牌面区应有半透明像素）
        band = layer.crop((10, 30, 230, 70))
        alphas = [p[3] for p in band.getdata()]
        self.assertGreater(max(alphas), 40)
        translucent = [a for a in alphas if 30 < a < 220]
        self.assertTrue(translucent)

    def test_flip_bare_digits_no_panel_blocks(self):
        import fx

        layer = Image.new("RGBA", (248, 92), (120, 130, 140, 255))
        fx.paint_flip_row(
            layer, 10, 30, 220, 40, "1时30分45秒", {}, 0.0,
            fx._flip_font(16), (24, 28, 38, 255), bare_digits=True,
        )
        band = layer.crop((10, 30, 230, 70))
        # 纯数字翻动：不应有大片深色牌面底块
        dark_panel = sum(
            1 for p in band.getdata()
            if p[3] > 180 and sum(p[:3]) < 90
        )
        self.assertLess(dark_panel, 40)

    def test_paint_card_flip_all_themes_sizes(self):
        import fx

        big = "2时15分30秒"
        title = "距离下班"
        for th in themes.list_themes():
            for w, h in ((148, 55), (200, 72), (248, 92), (360, 120)):
                if not themes.use_flip_display(th.kind, big, h=h):
                    continue
                img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                font_t, font_b, font_s = ornaments.layout_for(w, h)
                from PIL import ImageFont

                ft = ImageFont.load_default()
                themes.paint_card(
                    img, w, h, th, title, big, "", th.big,
                    ft, ft, ft,
                    stage="run",
                    flip_anims={},
                    flip_now=0.0,
                    flip_hit_rects=[],
                )
                self.assertEqual(img.size, (w, h))
                title_y, _p, row_y, _rw, row_h = fx.flip_row_layout(
                    w, h,
                    title_h=fx._font_line_height(ft, title),
                    has_sub=False,
                )
                self.assertGreaterEqual(row_y, title_y + 8)

    def test_inkpulse_flip_digit_contrast(self):
        import fx

        # 宣纸底恒浅，深浅墙纸都应出深墨字
        for wallpaper_light in (False, True):
            c = fx.flip_digit_color(
                (252, 248, 238, 255),
                skin_kind="inkpulse",
                wallpaper_light=wallpaper_light,
                card_light=True,
                stage="run",
            )
            self.assertLess(c[0] + c[1] + c[2], 120, msg=wallpaper_light)

    def test_flip_digit_dark_on_light_wallpaper(self):
        import fx

        white_accent = (255, 252, 255, 255)
        for kind in ("frost", "glass", "midautumn", "nationalday"):
            c = fx.flip_digit_color(
                white_accent,
                skin_kind=kind,
                wallpaper_light=True,
                flip_light=True,
                stage="run",
            )
            lum = 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
            self.assertLess(lum, 130, msg=kind)

    def test_flip_unit_not_fainter_than_digits(self):
        import fx

        digit = fx.flip_digit_color(
            (255, 252, 255, 200),
            skin_kind="frost",
            wallpaper_light=True,
            flip_light=True,
            stage="run",
        )
        unit = fx.flip_unit_color(
            digit, paper_light=True, overlay=True, stage="run",
        )
        self.assertGreaterEqual(unit[3], 252)
        self.assertLess(0.2126 * unit[0] + 0.7152 * unit[1] + 0.0722 * unit[2], 120)

    def test_neon_click_not_on_flip_digit(self):
        import fx

        rects = [(40, 36, 22, 28, 0), (66, 36, 22, 28, 1)]
        self.assertIsNone(fx.flip_digit_index_at(rects, 120, 46))
        self.assertEqual(fx.flip_digit_index_at(rects, 50, 40), 0)

    def test_flysword_removed(self):
        self.assertEqual(themes.normalize_id("flysword"), themes.DEFAULT_THEME_ID)
        self.assertNotIn("flysword", [t.id for t in themes.list_themes()])

    def test_thunder_light_palette_soft_cloud(self):
        import fx

        _arc, cloud, _p, _g = fx._thunder_palette("run", light=True)
        self.assertGreater(sum(cloud), 360)

    def test_skin_adapt_context_card_light(self):
        th = themes.get_theme("midautumn")
        light = themes.skin_adapt_context(themes.resolve_for_surface(th, "light"), "light")
        dark = themes.skin_adapt_context(themes.resolve_for_surface(th, "dark"), "dark")
        self.assertTrue(light.wallpaper_light)
        self.assertFalse(light.card_light)
        self.assertFalse(dark.card_light)

        thunder = themes.get_theme("thunder")
        t_light = themes.skin_adapt_context(themes.resolve_for_surface(thunder, "light"), "light")
        self.assertTrue(t_light.card_light)

    def test_adapt_text_on_light_card(self):
        th = themes.get_theme("thunder")
        theme = themes.resolve_for_surface(th, "light")
        ctx = themes.skin_adapt_context(theme, "light")
        c = themes.adapt_text_color(theme.title, ctx, kind=theme.kind, stage="run")
        self.assertLess(0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2], 130)

    def test_inkpulse_dark_wallpaper_keeps_dark_ink(self):
        th = themes.get_theme("inkpulse")
        theme = themes.resolve_for_surface(th, "dark")
        ctx = themes.skin_adapt_context(theme, "dark")
        self.assertTrue(ctx.card_light)
        c = themes.adapt_text_color(theme.title, ctx, kind="inkpulse", stage="run")
        self.assertLess(c[0] + c[1] + c[2], 120)

    def test_flip_row_capped_on_tall_window(self):
        import fx

        font = fx._flip_font(14)
        title_h = fx._font_line_height(font, "距离下班")
        _, _, _, _, row_h = fx.flip_row_layout(400, 140, title_h=title_h, has_sub=False)
        self.assertLessEqual(row_h, 56)

    def test_perimeter_closed(self):
        import fx

        total, point = fx._perimeter(248, 92, 14.0, 1.5)
        self.assertGreater(total, 2 * (248 + 92) * 0.8)
        x0, y0 = point(0.0)
        x1, y1 = point(0.999999)
        self.assertLess(abs(x0 - x1) + abs(y0 - y1), 1.0)
        for u in (0.1, 0.3, 0.5, 0.7, 0.9):
            x, y = point(u)
            self.assertTrue(0 <= x <= 248 and 0 <= y <= 92)


class KineticTests(unittest.TestCase):
    def test_festival_sequence_has_lead_and_countdown(self):
        import kinetic

        mid = kinetic.festival_show_phrases(kinetic.MIDAUTUMN_LEAD, kinetic.MIDAUTUMN_PHRASES)
        self.assertEqual(mid[:4], ("中秋将至", "3", "2", "1"))
        self.assertIn("中秋快乐", mid)
        nat = kinetic.festival_show_phrases(kinetic.NATIONAL_LEAD, kinetic.NATIONAL_PHRASES)
        self.assertEqual(nat[:4], ("国庆将至", "3", "2", "1"))
        # 321 明显短于祝福句，避免倒数拖沓
        self.assertLess(kinetic.duration("3"), kinetic.duration("月圆人圆") * 0.55)
        self.assertLess(kinetic.duration("中秋将至"), kinetic.duration("但愿人长久"))
        # paint 冒烟：走完将至与 321 不崩
        from PIL import Image, ImageFont

        show = kinetic.Show(mid, 0.0)
        img = Image.new("RGBA", (248, 92), (0, 0, 0, 255))
        font = ImageFont.load_default()
        for t in (0.2, kinetic.duration("中秋将至") + 0.1, kinetic.duration("中秋将至") + 1.2):
            kinetic.paint(img, show, font, (255, 255, 255, 255), t)


class ChangelogTests(unittest.TestCase):
    def test_parse_stops_at_non_version_heading(self):
        import changelog

        md = (
            "# GitCode 自动更新\n\n"
            "## 1.1.5\n\n"
            "墨水加实。\n\n"
            "## 1.1.4\n\n"
            "新皮。\n\n"
            "## 1. 你这边发包\n\n"
            "不要进弹窗。\n"
        )
        notes = changelog.parse_notes(md)
        self.assertEqual([v for v, _ in notes], ["1.1.5", "1.1.4"])
        self.assertIn("墨水加实", notes[0][1])
        got = changelog.notes_after("1.1.4", "1.1.5", text=md)
        self.assertEqual(got, [("1.1.5", "墨水加实。")])
        jump = changelog.notes_after("1.1.3", "1.1.5", text=md)
        self.assertEqual([v for v, _ in jump], ["1.1.5", "1.1.4"])

    def test_bundled_notes_include_current_version(self):
        import changelog
        from version import APP_VERSION

        found = [v for v, b in changelog.parse_notes(changelog.load_markdown()) if v == APP_VERSION]
        self.assertEqual(found, [APP_VERSION])

    def test_pending_file_roundtrip(self):
        with tempfile.TemporaryDirectory() as d:
            old = store.user_data_dir
            store.user_data_dir = lambda: Path(d)
            try:
                self.assertEqual(store.consume_pending_whats_new(), "")
                store.write_pending_whats_new("1.1.4")
                self.assertEqual(store.consume_pending_whats_new(), "1.1.4")
                self.assertEqual(store.consume_pending_whats_new(), "")
            finally:
                store.user_data_dir = old


class FlexTimeTests(unittest.TestCase):
    def test_offwork_mapping(self):
        self.assertEqual(flex_time.offwork_hm(8, 30), (18, 0))
        self.assertEqual(flex_time.offwork_hm(9, 30), (19, 0))
        self.assertEqual(flex_time.offwork_hm(9, 0), (18, 30))

    def test_parse_clock(self):
        self.assertEqual(flex_time.parse_clock("18:00"), (18, 0))
        self.assertEqual(flex_time.parse_clock("18.30"), (18, 30))
        self.assertIsNone(flex_time.parse_clock("25:00"))

    def test_setup_dialog_default_mode(self):
        fresh = {"time_mode": "flex"}
        self.assertEqual(
            flex_time.setup_dialog_default_mode(fresh, has_target=False, time_mode="flex"),
            "direct",
        )
        veteran = {"time_mode": "flex", "start_date": "2026-09-23", "start_h": 9, "start_m": 0}
        self.assertEqual(
            flex_time.setup_dialog_default_mode(veteran, has_target=False, time_mode="flex"),
            "flex",
        )
        self.assertEqual(
            flex_time.setup_dialog_default_mode(
                {"time_mode": "direct", "off_h": 18, "off_m": 0, "remember_offwork": True},
                has_target=True,
                time_mode="direct",
            ),
            "direct",
        )


class WorklogTests(unittest.TestCase):
    D = datetime(2026, 10, 8)  # 周四
    LATER = datetime(2026, 10, 20).date()

    def at(self, h, m, s=0):
        return self.D.replace(hour=h, minute=m, second=s)

    def prove(self, cfg, h, m, s=10, target=(18, 30)):
        """连续三秒有输入，记成一段上机。"""
        base = self.at(h, m, s)
        state = None
        start = None
        last = base
        for i in range(3):
            last = base + timedelta(seconds=i)
            state, start = worklog.note_second(state, last)
        self.assertIsNotNone(start)
        worklog.mark_span(cfg, start, last, target_hm=target)
        return state

    def test_live_today_has_no_diff_and_skips_summary(self):
        cfg = {}
        self.prove(cfg, 8, 40, target=(18, 10))
        self.prove(cfg, 14, 0, target=(18, 10))
        live = worklog.row(cfg, self.D.date(), today=self.D.date())
        self.assertTrue(live["live"])
        self.assertIsNone(live["diff"])
        self.assertEqual(live["dur"], 320)
        self.assertEqual(worklog.summarize([live])["days"], 0)
        done = worklog.row(cfg, self.D.date(), today=self.LATER)
        self.assertFalse(done["live"])
        self.assertEqual(done["diff"], -250)
        late = worklog.row(cfg, self.D.date(), today=self.D.date())
        # 14:00 还没到 18:10，差额仍隐藏
        self.assertIsNone(late["diff"])
        self.prove(cfg, 18, 30, target=(18, 10))
        overtime = worklog.row(cfg, self.D.date(), today=self.D.date())
        self.assertTrue(overtime["live"])
        self.assertEqual(overtime["diff"], 20)

    def test_span_follows_proven_bursts(self):
        cfg = {}
        self.prove(cfg, 8, 20, target=None)
        self.assertEqual(worklog.get_day(cfg, self.D.date())["src"], "seen")
        self.prove(cfg, 12, 0, target=(18, 10))
        self.prove(cfg, 18, 35, target=(18, 10))
        self.assertFalse(worklog.touch_target(cfg, self.D.date(), (18, 10)))
        r = worklog.row(cfg, self.D.date(), today=self.LATER)
        self.assertEqual((r["in"], r["out"], r["target"]), (500, 1115, 1090))
        self.assertEqual(r["dur"], 615)
        self.assertEqual(r["diff"], 25)
        self.assertEqual(r["src"], "seen")

    def test_gaps_stay_inside_the_span_until_midnight(self):
        cfg = {}
        tgt = (18, 0)
        for hm in ((9, 0), (11, 30), (13, 40), (18, 20), (21, 0), (21, 5)):
            self.prove(cfg, *hm, target=tgt)
        r = worklog.row(cfg, self.D.date())
        self.assertEqual((r["in"], r["out"]), (9 * 60, 21 * 60 + 5))
        self.assertFalse(r["closed"])

    def test_long_afternoon_meeting_keeps_counting(self):
        cfg = {}
        tgt = (18, 0)
        for hm in ((9, 0), (15, 0), (18, 40), (19, 10)):
            self.prove(cfg, *hm, target=tgt)
        r = worklog.row(cfg, self.D.date())
        self.assertEqual(r["out"], 19 * 60 + 10)
        self.assertFalse(r["closed"])

    def test_evening_use_extends_the_same_day(self):
        cfg = {}
        tgt = (18, 0)
        self.prove(cfg, 9, 0, target=tgt)
        self.prove(cfg, 17, 0, target=tgt)
        self.prove(cfg, 20, 30, target=tgt)
        self.assertEqual(worklog.row(cfg, self.D.date())["out"], 20 * 60 + 30)

    def test_manual_edit_wins_and_blank_deletes(self):
        cfg = {}
        self.prove(cfg, 9, 0, target=(18, 30))
        self.assertIsNone(worklog.set_manual(cfg, self.D.date(), "8.50", "19:05"))
        self.prove(cfg, 19, 30, target=(18, 30))
        r = worklog.row(cfg, self.D.date())
        self.assertEqual((r["in"], r["out"]), (530, 1145))
        self.assertTrue(r["manual"])
        self.assertIn("早于", worklog.set_manual(cfg, self.D.date(), "19:00", "9:00"))
        self.assertIn("看不懂", worklog.set_manual(cfg, self.D.date(), "abc", ""))
        self.assertIsNone(worklog.set_manual(cfg, self.D.date(), "", ""))
        self.assertIsNone(worklog.get_day(cfg, self.D.date()))

    def test_should_track_includes_weekends_and_days_without_a_target(self):
        sat = datetime(2026, 10, 10, 10, 0)
        self.assertTrue(worklog.should_track(sat, has_target=True, set_today=False))
        self.assertTrue(worklog.should_track(sat, has_target=False, set_today=False))
        self.assertTrue(worklog.should_track(self.at(10, 0), has_target=False, set_today=False))

    def test_summary_and_csv(self):
        cfg = {}
        worklog.set_manual(cfg, self.D.date(), "9:00", "18:30")
        cfg["worklog"]["2026-10-08"]["target"] = 18 * 60
        worklog.set_manual(cfg, datetime(2026, 10, 9).date(), "8:30", "18:00")
        rows = [worklog.row(cfg, d, today=self.LATER) for d in worklog.week_dates(self.D.date())]
        s = worklog.summarize(rows)
        self.assertEqual((s["days"], s["total"], s["avg"], s["diff"]), (2, 1140, 570, 30))
        self.assertIn("一共 19小时", worklog.summary_text("本周", s))
        self.assertIn("晚走 30分", worklog.summary_text("本周", s))
        self.assertEqual(worklog.fmt_elapsed(9 * 3600 + 52 * 60 + 8), "9小时52分8秒")
        self.assertEqual(worklog.fmt_span(570), "9小时30分")
        self.assertEqual(worklog.fmt_diff(20), "晚走20分")
        self.assertEqual(worklog.fmt_diff(-15), "早走15分")
        csv_text = worklog.to_csv(cfg, worklog.month_dates(2026, 10))
        lines = csv_text.strip().splitlines()
        self.assertEqual(len(lines), 3)
        self.assertIn("2026-10-08,周四,9:00,18:30,9小时30分,18:00,晚走30分,手改", lines[1])

    def test_three_seconds_inside_thirty_sets_the_span(self):
        cfg = {}
        state = None
        start = None
        first = self.at(8, 59, 50)
        for extra in (0, 5, 15):
            when = first + timedelta(seconds=extra)
            state, start = worklog.note_second(state, when)
        self.assertEqual(start, first)
        worklog.mark_span(cfg, start, first + timedelta(seconds=15), target_hm=(18, 0))
        day = worklog.get_day(cfg, self.D.date())
        self.assertEqual((day["in"], day["out"]), (8 * 60 + 59, 9 * 60))

    def test_note_input_works_when_activity_counts_are_off(self):
        import activity

        cfg = {}
        state = None
        changed = False
        first = self.at(9, 3, 1)
        for extra in (0, 4, 12):
            state, changed = worklog.note_input(
                cfg, state, first + timedelta(seconds=extra), target_hm=(18, 0)
            )
        self.assertTrue(changed)
        self.assertEqual(
            (worklog.get_day(cfg, self.D.date())["in"], worklog.get_day(cfg, self.D.date())["out"]),
            (9 * 60 + 3, 9 * 60 + 3),
        )
        self.assertFalse(activity.enabled(cfg))
        self.assertEqual(activity.totals(cfg, self.D.date()), (0, 0, 0))

    def test_worklog_privacy_switch_stops_writes_but_keeps_history(self):
        cfg = {}
        state = None
        first = self.at(9, 3, 1)
        for extra in (0, 4, 12):
            state, _changed = worklog.note_input(cfg, state, first + timedelta(seconds=extra))
        before = dict(worklog.get_day(cfg, self.D.date()))
        self.assertTrue(worklog.tracking_enabled(cfg))

        worklog.set_tracking_enabled(cfg, False)
        for extra in (60, 65, 70):
            state, changed = worklog.note_input(cfg, state, first + timedelta(seconds=extra))
            self.assertIsNone(state)
            self.assertFalse(changed)
        self.assertEqual(worklog.get_day(cfg, self.D.date()), before)

        worklog.set_tracking_enabled(cfg, True)
        state = None
        for extra in (120, 125, 130):
            state, changed = worklog.note_input(cfg, state, first + timedelta(seconds=extra))
        self.assertTrue(changed)
        self.assertGreater(worklog.get_day(cfg, self.D.date())["out"], before["out"])

    def test_worklog_and_activity_privacy_switches_are_independent(self):
        import activity

        cfg = {}
        worklog.set_tracking_enabled(cfg, False)
        activity.set_enabled(cfg, True)
        self.assertFalse(worklog.tracking_enabled(cfg))
        self.assertTrue(activity.enabled(cfg))
        activity.set_enabled(cfg, False)
        worklog.set_tracking_enabled(cfg, True)
        self.assertTrue(worklog.tracking_enabled(cfg))
        self.assertFalse(activity.enabled(cfg))

    def test_last_input_fallback_only_uses_changed_ticks(self):
        now = self.at(10, 0, 10)
        tick, when = worklog.fallback_input(None, (1000, 0.2), now)
        self.assertEqual(tick, 1000)
        self.assertIsNone(when)  # 启动时只建基线，不把启动前的输入算进来
        tick, when = worklog.fallback_input(tick, (1000, 0.0), now + timedelta(seconds=1))
        self.assertEqual(tick, 1000)
        self.assertIsNone(when)  # 空闲一直报 0，但 tick 没变，仍然不是新输入
        tick, when = worklog.fallback_input(tick, None, now + timedelta(seconds=2))
        self.assertEqual(tick, 1000)
        self.assertIsNone(when)  # API 失败也不是新输入
        tick, when = worklog.fallback_input(tick, (1008, 0.25), now + timedelta(seconds=3))
        self.assertEqual(tick, 1008)
        self.assertEqual(when, now + timedelta(seconds=2.75))
        # 官方说明 tick 不保证递增，所以只看“是否改变”，不比较大小。
        tick, when = worklog.fallback_input(tick, (998, 0.1), now + timedelta(seconds=4))
        self.assertEqual(tick, 998)
        self.assertEqual(when, now + timedelta(seconds=3.9))

    def test_three_changed_fallback_ticks_can_set_the_span(self):
        cfg = {}
        state = None
        tick = 100
        first = self.at(10, 12, 0)
        for index, extra in enumerate((0, 6, 18), start=1):
            now = first + timedelta(seconds=extra, milliseconds=200)
            tick, when = worklog.fallback_input(tick, (100 + index, 0.2), now)
            self.assertIsNotNone(when)
            state, changed = worklog.note_input(cfg, state, when)
        self.assertTrue(changed)
        self.assertEqual(worklog.get_day(cfg, self.D.date())["in"], 10 * 60 + 12)

    def test_real_input_is_allowed_immediately_after_wake(self):
        worklog.reset_wake_watch()
        before = self.at(7, 0, 0)
        worklog.observe_clock(before, wall=1000.0, unbiased_100ns=1000 * 10_000_000)
        woke = before + timedelta(hours=2)
        self.assertEqual(
            worklog.observe_clock(woke, wall=8200.0, unbiased_100ns=1001 * 10_000_000),
            "wake",
        )
        cfg = {}
        state = None
        # quiet 只挡 LastInput 兜底；可信 Raw Input 仍直接送进 note_input。
        for extra in (0, 4, 11):
            state, changed = worklog.note_input(cfg, state, woke + timedelta(seconds=extra))
        self.assertTrue(changed)
        self.assertEqual(worklog.get_day(cfg, woke.date())["in"], 9 * 60)
        worklog.reset_wake_watch()

    def test_standby_wake_does_not_count_as_input(self):
        worklog.reset_wake_watch()
        t0 = self.at(21, 0, 0)
        # 睡着前：墙上时间和待机时钟一起走。
        self.assertEqual(worklog.observe_clock(t0, wall=1000.0, unbiased_100ns=1000 * 10_000_000), "ok")
        self.assertEqual(worklog.observe_clock(t0, wall=1001.0, unbiased_100ns=1001 * 10_000_000), "ok")
        # 睡了两小时：墙上时间跳了，待机时钟几乎没动。
        woke = t0 + timedelta(hours=2)
        self.assertEqual(worklog.observe_clock(woke, wall=8201.0, unbiased_100ns=1002 * 10_000_000), "wake")
        state = None
        start = None
        for sec in range(3):
            when = woke + timedelta(seconds=sec + 1)
            phase = worklog.observe_clock(when, wall=8201.0 + sec + 1, unbiased_100ns=(1003 + sec) * 10_000_000)
            self.assertEqual(phase, "quiet")
            # 主循环在 wake / quiet 时丢掉这段，不送进 note_second。
            if phase != "ok":
                state = None
                continue
            state, start = worklog.note_second(state, when)
        self.assertIsNone(start)
        later = woke + timedelta(seconds=worklog.WAKE_QUIET_SEC + 1)
        self.assertEqual(
            worklog.observe_clock(later, wall=8201.0 + worklog.WAKE_QUIET_SEC + 1, unbiased_100ns=1018 * 10_000_000),
            "ok",
        )
        # 安静窗口过后，连续 3 秒的真输入仍然记来和走。
        state = None
        for extra in (0, 5, 12):
            state, start = worklog.note_second(state, later + timedelta(seconds=extra))
        self.assertEqual(start, later)
        worklog.reset_wake_watch()

    def test_a_short_bump_does_not_move_the_span(self):
        cfg = {}
        self.prove(cfg, 18, 10, target=(18, 0))
        state, start = worklog.note_second(None, self.at(18, 40, 3))
        self.assertIsNone(start)
        state, start = worklog.note_second(state, self.at(18, 40, 8))
        self.assertIsNone(start)
        self.assertEqual(worklog.get_day(cfg, self.D.date())["out"], 18 * 60 + 10)
        spread = None
        found = None
        for sec in (0, 10, 41):
            spread, found = worklog.note_second(spread, self.at(19, 0, sec))
        self.assertIsNone(found)
        state, start = worklog.note_second(state, self.at(18, 40, 20))
        self.assertEqual(start, self.at(18, 40, 3))
        worklog.mark_span(cfg, start, self.at(18, 40, 20), target_hm=(18, 0))
        self.assertEqual(worklog.get_day(cfg, self.D.date())["out"], 18 * 60 + 40)

    def test_midnight_starts_a_new_day(self):
        state, start = worklog.note_second(None, self.at(23, 59, 50))
        state, start = worklog.note_second(state, self.at(23, 59, 58))
        nxt = datetime(2026, 10, 9, 0, 0, 2)
        state, start = worklog.note_second(state, nxt)
        self.assertIsNone(start)
        self.assertEqual(state["day"], "2026-10-09")
        self.assertEqual(state["secs"], [2])

    def test_idle_does_not_seal_or_move_out(self):
        cfg = {}
        tgt = (18, 0)
        self.prove(cfg, 18, 10, target=tgt)
        self.assertFalse(worklog.touch_target(cfg, self.D.date(), tgt))
        r = worklog.row(cfg, self.D.date())
        self.assertEqual(r["out"], 18 * 60 + 10)
        self.assertFalse(r["closed"])
        self.assertIsNone(worklog.last_active_minute(self.at(0, 10), 20 * 60))

    def test_ensure_fields_prunes_garbage_and_old(self):
        cfg = {
            "worklog": {
                "2026-10-08": {"in": 540, "out": 99999, "src": "flex"},
                "2024-01-01": {"in": 540},
                "bad": {"in": 1},
                "2026-10-07": "x",
            }
        }
        worklog.ensure_fields(cfg, today=self.D.date())
        self.assertEqual(cfg["worklog"], {"2026-10-08": {"in": 540, "src": "flex"}})

    def test_arrival_follows_the_same_keep_as_counts(self):
        import activity

        today = date(2026, 10, 19)
        cfg = {
            "worklog": {
                "2026-10-19": {"in": 540, "out": 1080},
                "2026-08-20": {"in": 540, "out": 1080},
                "2026-08-19": {"in": 540, "out": 1080},
            }
        }
        worklog.ensure_fields(cfg, today=today)
        self.assertIn("2026-10-19", cfg["worklog"])
        self.assertIn("2026-08-20", cfg["worklog"])
        self.assertNotIn("2026-08-19", cfg["worklog"])
        cfg["worklog"]["2026-10-12"] = {"in": 540, "out": 1080}
        cfg["worklog"]["2026-10-11"] = {"in": 500, "out": 1000}
        self.assertEqual(activity.set_keep_days(cfg, 7, today=today), 7)
        self.assertIn("2026-10-12", cfg["worklog"])
        self.assertNotIn("2026-10-11", cfg["worklog"])


class HabitTests(unittest.TestCase):
    def _stamp(self, cfg, d, hours=None, wheels=None, arrived=None, left=None):
        import activity

        if hours or wheels:
            activity.set_enabled(cfg, True)
            days = cfg.setdefault("activity", {}).setdefault("days", {})
            rec = days.setdefault(
                d.isoformat(),
                {
                    "keys": 0, "clicks": 0, "wheels": 0,
                    "hours": [0] * 24, "keys_h": [0] * 24,
                    "clicks_h": [0] * 24, "wheels_h": [0] * 24,
                },
            )
            for hour, n in (hours or {}).items():
                rec["hours"][hour] += n
                rec["keys_h"][hour] += n
                rec["keys"] += n
            for hour, n in (wheels or {}).items():
                rec["hours"][hour] += n
                rec["wheels_h"][hour] += n
                rec["wheels"] += n
        if arrived is not None:
            cfg.setdefault("worklog", {})[d.isoformat()] = {
                "in": arrived,
                "out": left,
                "target": arrived + 9 * 60,
                "closed": True,
            }

    def test_short_week_says_nothing(self):
        today = date(2026, 10, 23)
        cfg = {}
        self._stamp(cfg, date(2026, 10, 19), hours={14: 40, 15: 30})
        text = worklog.habit_text(cfg, worklog.week_dates(today), today, this_week=True)
        self.assertEqual(text, "")

    def test_afternoon_habit_names_the_busy_hours(self):
        today = date(2026, 10, 23)
        cfg = {}
        for d in (date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)):
            self._stamp(cfg, d, hours={14: 40, 15: 30})
        text = worklog.habit_text(cfg, worklog.week_dates(today), today, this_week=True)
        self.assertIn("上午几乎不动，忙集中在下午", text)
        self.assertIn("最勤在 14–16 点", text)
        self.assertNotIn("效率", text)
        self.assertNotIn("开会", text)

    def test_same_band_for_several_weeks(self):
        today = date(2026, 10, 23)
        cfg = {}
        for day in range(5, 24):
            self._stamp(cfg, date(2026, 10, day), hours={14: 20, 15: 16})
        text = worklog.habit_text(cfg, worklog.week_dates(today), today, this_week=True)
        self.assertIn("这几周都是下午更忙", text)

    def test_this_week_moves_to_the_morning(self):
        today = date(2026, 10, 23)
        cfg = {}
        for day in range(5, 17):
            self._stamp(cfg, date(2026, 10, day), hours={14: 20, 15: 16})
        for d in (date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)):
            self._stamp(cfg, d, hours={9: 30, 10: 28})
        text = worklog.habit_text(cfg, worklog.week_dates(today), today, this_week=True)
        self.assertIn("本周上午更忙，前几周都是下午", text)

    def test_arrival_clusters_around_the_same_time(self):
        today = date(2026, 10, 23)
        cfg = {}
        for d, arrived in (
            (date(2026, 10, 19), 9 * 60 + 8),
            (date(2026, 10, 20), 9 * 60 + 10),
            (date(2026, 10, 21), 9 * 60 + 12),
        ):
            self._stamp(cfg, d, arrived=arrived, left=18 * 60)
        text = worklog.habit_text(cfg, worklog.week_dates(today), today, this_week=True)
        self.assertIn("到岗多在 9:10 前后", text)
        self.assertIn("不到半小时", text)

    def test_arrival_later_than_earlier_weeks(self):
        today = date(2026, 10, 23)
        cfg = {}
        for day in range(5, 17):
            d = date(2026, 10, day)
            if d.weekday() >= 5:
                continue
            self._stamp(cfg, d, arrived=9 * 60, left=18 * 60)
        for d in (date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)):
            self._stamp(cfg, d, arrived=10 * 60, left=18 * 60)
        text = worklog.habit_text(cfg, worklog.week_dates(today), today, this_week=True)
        self.assertIn("到岗比前几周晚了", text)


class WorklogScrollTests(unittest.TestCase):
    def test_tall_screen_keeps_the_middle_full_height(self):
        import worklog_ui

        view, scroll = worklog_ui.scroll_view(640, 860, 1080)
        self.assertEqual((view, scroll), (640, False))

    def test_short_screen_only_shrinks_the_middle(self):
        import worklog_ui

        view, scroll = worklog_ui.scroll_view(640, 860, 720)
        self.assertTrue(scroll)
        self.assertLess(view, 640)
        self.assertGreaterEqual(view, 180)
        self.assertLessEqual(860 - (640 - view) + 24, 720 - 48)

    def test_summary_stays_outside_the_scroller(self):
        import tkinter as tk

        import worklog_ui

        root = tk.Tk()
        root.withdraw()

        class Host(worklog_ui.WorklogDialogMixin):
            def __init__(self) -> None:
                self.cfg = {}

            def _tk_root(self):
                return root

            def _dialog_near(self):
                return (40, 40)

        host = Host()
        ui = host._build_worklog_dialog()
        dlg = ui["dlg"]
        try:
            host._fill_worklog(ui)
            self.assertIs(ui["month_lbl"].master, ui["sums"])
            self.assertIs(ui["sums"].master, dlg)
            self.assertIs(ui["sheet"].master, ui["scroll"])
            self.assertIsNot(ui["controls"].master, ui["sheet"])
            self.assertEqual(ui["controls"].winfo_manager(), "pack")
            self.assertEqual(len(ui["slot_buttons"]), 3)
            self.assertTrue(all(isinstance(btn, tk.Menubutton) for btn in ui["slot_buttons"]))
            self.assertTrue(all(str(btn.cget("textvariable")) for btn in ui["slot_buttons"]))
            host._fit_worklog_scroll(ui, screen_h=720)
            dlg.update_idletasks()
            self.assertTrue(ui["scroll_sb"].winfo_manager())
            self.assertEqual(ui["controls"].winfo_manager(), "pack")
            self.assertLess(int(ui["scroll"].cget("height")), int(ui["sheet"].winfo_reqheight()))
            self.assertLessEqual(int(dlg.winfo_reqheight()) + 24, 720 - 48 + 8)
            host._fit_worklog_scroll(ui, screen_h=1600)
            dlg.update_idletasks()
            self.assertEqual(ui["scroll_sb"].winfo_manager(), "")
            self.assertEqual(int(ui["scroll"].cget("height")), int(ui["sheet"].winfo_reqheight()))

            worklog.set_manual(host.cfg, date.today(), "9:00", "18:00")
            worklog.set_tracking_enabled(host.cfg, False)
            host._fill_worklog(ui)
            self.assertEqual(ui["table"].winfo_manager(), "")
            self.assertEqual(ui["history_notice"].winfo_manager(), "pack")
            self.assertEqual(ui["week_sum_lbl"].winfo_manager(), "")
            self.assertIsNotNone(worklog.get_day(host.cfg, date.today()))
            worklog.set_tracking_enabled(host.cfg, True)
            host._fill_worklog(ui)
            self.assertEqual(ui["table"].winfo_manager(), "pack")
            self.assertEqual(ui["history_notice"].winfo_manager(), "")
        finally:
            dlg.destroy()
            root.destroy()


class ActivityTests(unittest.TestCase):
    def test_counts_and_report_without_storing_keys(self):
        import activity

        cfg = {}
        d = date(2026, 10, 19)
        now = datetime(2026, 10, 19, 10, 15)
        self.assertFalse(activity.note(cfg, "key", now))
        activity.set_enabled(cfg, True)
        self.assertTrue(activity.note(cfg, "key", now))
        self.assertTrue(activity.note(cfg, "click", now.replace(hour=11)))
        self.assertTrue(activity.note(cfg, "wheel", now.replace(hour=11)))
        c = activity.counts(cfg, d)
        self.assertEqual((c["keys"], c["clicks"], c["wheels"]), (1, 1, 1))
        text = activity.report_text(cfg, d)
        self.assertIn("敲了 1 下", text)
        self.assertIn("点了 1 次", text)
        self.assertNotIn("vk", text.lower())
        peak = activity.peak_hours(c["hours"])
        self.assertEqual(peak, (10, 12))
        self.assertEqual(c["keys_h"][10], 1)
        self.assertEqual(c["clicks_h"][11], 1)
        self.assertEqual(c["hours"][11], 2)
        self.assertEqual(c["wheels_h"][11], 1)

    def test_speed_counts_a_stretch_and_skips_a_tap(self):
        import activity

        cfg = {}
        activity.set_enabled(cfg, True)
        t0 = datetime(2026, 10, 26, 10, 0, 0)
        activity.note(cfg, "key", t0)
        activity.settle(cfg, t0 + timedelta(seconds=3))
        self.assertEqual(sum(activity.counts(cfg, t0.date())["keys_pace"]), 0)
        for sec in (0, 0.4, 0.8, 1.2):
            activity.note(cfg, "key", t0 + timedelta(seconds=10 + sec))
        live = activity.speed_snapshot(cfg, t0 + timedelta(seconds=11.2))
        self.assertEqual(activity.rate_value("key", *live["key"]), 180)
        activity.settle(cfg, t0 + timedelta(seconds=15))
        stored = activity.counts(cfg, t0.date())
        self.assertEqual(sum(stored["keys_pace"]), 4)
        self.assertGreaterEqual(sum(stored["keys_ms"]), 1000)
        self.assertEqual(activity.fmt_key_rate(4, 1200), "200下/分")
        move = t0.replace(minute=5)
        activity.add_travel(cfg, 1600, 0, move)
        activity.add_travel(cfg, 1600, 0, move + timedelta(seconds=0.2))
        activity.settle(cfg, move + timedelta(seconds=1))
        moved = activity.counts(cfg, t0.date())
        self.assertEqual(sum(moved["travel_pace"]), 3200)
        self.assertEqual(activity.fmt_move_rate(3200, 200), "约 25 厘米/秒")
        spin = t0.replace(minute=8)
        for sec in (0, 0.4, 0.8, 1.2):
            activity.note(cfg, "wheel", spin + timedelta(seconds=sec))
        activity.settle(cfg, spin + timedelta(seconds=3))
        self.assertEqual(sum(activity.counts(cfg, t0.date())["wheels_pace"]), 4)
        self.assertIn("打字", activity.fmt_speed_line(4, 1200, 0, 0, 0, 0))
        self.assertIn("滚轮 —", activity.fmt_speed_line(4, 1200, 0, 0, 0, 0))
        done = activity.counts(cfg, t0.date())
        self.assertEqual(done["keys_last"][10], 3)
        self.assertEqual(len(done["inst_key"]), 1)
        self.assertEqual(activity.card_slots(cfg), ("keys", "clicks", "wheels"))
        swapped = activity.set_card_slot(cfg, 0, "key_now")
        self.assertEqual(swapped[0], "key_now")
        self.assertEqual(len(set(swapped)), 3)
        again = activity.set_card_slot(cfg, 1, "key_now")
        self.assertEqual(again.count("key_now"), 1)
        stopped = t0.replace(minute=30)
        idle = activity.speed_snapshot(cfg, stopped)
        self.assertEqual(idle["key"], (0, 0))
        parts = activity.card_parts(cfg, stopped, speed=idle)
        self.assertTrue(any(text == "0/分" for _icon, text in parts))

    def test_speed_charts_draw_average_and_curve(self):
        import activity_chart

        pace = [0] * 24
        ms = [0] * 24
        pace[10] = 4
        ms[10] = 1200
        today = {
            "mode": "split",
            "keys": 4, "clicks": 0, "wheels": 0,
            "keys_h": pace[:], "clicks_h": [0] * 24, "wheels_h": [0] * 24, "hours": [0] * 24,
            "travel": 0, "travel_h": [0] * 24,
            "keys_pace": pace, "keys_ms": ms,
            "wheels_pace": [0] * 24, "wheels_ms": [0] * 24,
            "travel_pace": [0] * 24, "travel_ms": [0] * 24,
            "inst_key": [[10 * 3600, 4, 1200], [10 * 3600 + 30, 8, 2400]],
            "inst_wheel": [],
            "inst_move": [[10 * 3600 + 300, 3200, 200]],
        }
        _im, hits = activity_chart.render(today, [], enabled=True, this_week=True, mode="avg")
        self.assertTrue(any(h["text"] == "10点" and "200下/分" in h["speed"] for h in hits))
        _curve, curve_hits = activity_chart.render(today, [], enabled=True, this_week=True, mode="inst")
        self.assertTrue(any(h["text"] == "10点" and "200下/分" in h["speed"] for h in curve_hits))
        self.assertTrue(any("25 厘米/秒" in h["speed"] for h in curve_hits))
        steps = activity_chart._interval_points(
            [[36000, 10, 1000], [36020, 20, 21000], [36300, 5, 1000]],
            "key",
        )
        self.assertEqual(steps, [(36000, 600), (36020, 30), (36021, 0), (36300, 300)])

    def test_instant_speed_follows_the_last_few_seconds(self):
        import activity

        cfg = {}
        activity.set_enabled(cfg, True)
        t0 = datetime(2026, 10, 26, 10, 0, 0)
        for i in range(25):
            activity.note(cfg, "key", t0 + timedelta(seconds=i))
        end = t0 + timedelta(seconds=24)
        for k in range(20):
            activity.note(cfg, "key", end + timedelta(milliseconds=300 * k))
        when = end + timedelta(milliseconds=300 * 19)
        snap = activity.speed_snapshot(cfg, when)
        n, ms = snap["key"]
        self.assertGreater(activity.rate_value("key", n, ms), 150)
        whole = activity.rate_value("key", 45, int((when - t0).total_seconds() * 1000))
        self.assertLess(whole, 120)
        activity.settle(cfg, when + timedelta(seconds=3))
        saved = activity.counts(cfg, t0.date())
        self.assertGreater(activity.rate_value("key", saved["keys_last"][10], saved["keys_last_ms"][10]), 150)
        self.assertEqual(activity.speed_snapshot(cfg, when + timedelta(seconds=3))["key"], (0, 0))

    def test_instant_drops_when_typing_slows_and_is_zero_when_idle(self):
        """按真实节奏：打快、放慢、停手，滚轮和鼠标停了也是 0。均速能反推操作秒数。"""
        import activity

        cfg = {}
        activity.set_enabled(cfg, True)
        t0 = datetime(2026, 10, 26, 11, 0, 0)
        for i in range(8):
            activity.note(cfg, "key", t0 + timedelta(milliseconds=250 * i))
        fast_at = t0 + timedelta(milliseconds=250 * 7)
        fast = activity.rate_value("key", *activity.speed_snapshot(cfg, fast_at)["key"])
        self.assertEqual(fast, 300)
        slow_at = fast_at
        for i in range(1, 4):
            slow_at = fast_at + timedelta(milliseconds=900 * i)
            activity.note(cfg, "key", slow_at)
        slow = activity.rate_value("key", *activity.speed_snapshot(cfg, slow_at)["key"])
        self.assertLess(slow, fast)
        self.assertGreater(slow, 0)
        self.assertEqual(activity.speed_snapshot(cfg, slow_at + timedelta(seconds=1.2))["key"], (0, 0))
        self.assertEqual(activity.fmt_instant("key", 0, 0), "0下/分")

        w0 = t0 + timedelta(minutes=5)
        for i in range(10):
            activity.note(cfg, "wheel", w0 + timedelta(milliseconds=80 * i))
        wheel_at = w0 + timedelta(milliseconds=80 * 9)
        self.assertGreater(activity.rate_value("wheel", *activity.speed_snapshot(cfg, wheel_at)["wheel"]), 0)
        self.assertEqual(activity.speed_snapshot(cfg, wheel_at + timedelta(seconds=1.2))["wheel"], (0, 0))
        self.assertEqual(activity.fmt_instant("wheel", 0, 0), "0格/分")

        m0 = t0 + timedelta(minutes=8)
        for i in range(6):
            activity.add_travel(cfg, 400, 0, m0 + timedelta(milliseconds=100 * i))
        move_at = m0 + timedelta(milliseconds=500)
        self.assertGreater(activity.rate_value("move", *activity.speed_snapshot(cfg, move_at)["move"]), 0)
        self.assertEqual(activity.speed_snapshot(cfg, move_at + timedelta(seconds=1.2))["move"], (0, 0))
        self.assertEqual(activity.fmt_instant("move", 0, 0), "0")

        activity.settle(cfg, slow_at + timedelta(seconds=3))
        counted = activity.counts(cfg, t0.date())
        total = sum(counted["keys_h"])
        active = sum(counted["keys_ms"])
        rate = activity.rate_value("key", total, active)
        self.assertGreater(active, 0)
        self.assertEqual(rate, round(total * 60000 / active))
        self.assertAlmostEqual(total * 60000 / rate, active, delta=active * 0.01)

    def test_tally_bubble_sits_above_and_falls_below_at_top(self):
        import tally_bubble

        small = tally_bubble.render(12, 3, 0, scale=1.0)
        big = tally_bubble.render(123456, 9999, 88, scale=1.5)
        self.assertGreater(big.width, small.width)
        self.assertGreater(big.height, small.height)
        self.assertEqual(small.getpixel((small.width // 2, 1))[3] > 0, True)
        area = (0, 0, 1920, 1040)
        x, y = tally_bubble.place(800, 500, 248, 92, small.width, small.height, area)
        self.assertLess(y + small.height, 500)
        self.assertAlmostEqual(x + small.width / 2, 800 + 124, delta=1)
        _x, y2 = tally_bubble.place(800, 2, 248, 92, small.width, small.height, area)
        self.assertGreaterEqual(y2, 2 + 92)
        x3, _y = tally_bubble.place(1900, 500, 248, 92, small.width, small.height, area)
        self.assertLessEqual(x3 + small.width, 1920)
        bubble = tally_bubble.TallyBubble()
        bubble.follow((10, 10, 248, 92))
        self.assertEqual((bubble.x, bubble.y), (0, 0))

    def test_tally_row_stays_inside_the_top_band(self):
        import tally_bubble

        img = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
        shift = tally_bubble.paint_top(img, (2, 4, 142, 88), (1284, 86, 12), light=False)
        box = img.getbbox()
        self.assertIsNotNone(box)
        self.assertGreaterEqual(shift, 10)
        self.assertLessEqual(shift, 24)
        self.assertLessEqual(box[3], 4 + shift)
        self.assertLessEqual(box[2], 142)
        self.assertGreaterEqual(box[0], 2)

    def test_still_phrase_waits_three_minutes(self):
        import activity

        self.assertIsNone(activity.still_phrase(179))
        self.assertEqual(activity.still_phrase(180), "手停了 3 分钟")
        self.assertEqual(activity.still_phrase(18 * 60 + 40), "手停了 18 分钟")
        self.assertEqual(activity.still_phrase(60 * 60), "手停了 1 小时")
        self.assertEqual(activity.still_phrase(72 * 60 + 10), "手停了 1 小时 12 分")

    def test_still_line_sits_under_the_counts(self):
        import tally_bubble

        plain = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
        with_line = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
        box = (2, 4, 220, 88)
        bare = tally_bubble.paint_top(plain, box, (1284, 86, 12), light=False)
        full = tally_bubble.paint_top(with_line, box, (1284, 86, 12), light=False, still="手停了 18 分钟")
        self.assertGreater(full, bare)
        self.assertLessEqual(full, 40)
        bb = with_line.getbbox()
        self.assertIsNotNone(bb)
        self.assertLessEqual(bb[3], 4 + full)
        hit = False
        for yy in range(min(with_line.height - 1, bare + 2), min(with_line.height, 4 + full)):
            for xx in range(16, 200):
                if with_line.getpixel((xx, yy))[3] > 40:
                    hit = True
                    break
            if hit:
                break
        self.assertTrue(hit)

    def test_mouse_travel_is_relative_and_skips_absolute(self):
        import activity

        buf = bytearray(64)
        buf[activity._DX_AT:activity._DX_AT + 4] = (3).to_bytes(4, "little", signed=True)
        buf[activity._DY_AT:activity._DY_AT + 4] = (-4).to_bytes(4, "little", signed=True)
        self.assertEqual(activity.mouse_delta(bytes(buf)), (3, -4))
        buf[activity._FLAG_AT] = 1
        self.assertIsNone(activity.mouse_delta(bytes(buf)))
        cfg = {}
        self.assertFalse(activity.add_travel(cfg, 3, -4, datetime(2026, 10, 19, 10, 0)))
        activity.set_enabled(cfg, True)
        self.assertTrue(activity.add_travel(cfg, 3, -4, datetime(2026, 10, 19, 10, 0)))
        self.assertEqual(activity.counts(cfg, date(2026, 10, 19))["travel"], 5)
        self.assertEqual(activity.counts(cfg, date(2026, 10, 19))["travel_h"][10], 5)
        self.assertEqual(activity.fmt_travel(1600), "约 2.5 厘米")
        self.assertEqual(activity.fmt_travel(64000), "约 1.0 米")
        self.assertEqual(activity.chart_style({}), "line")
        self.assertEqual(activity.set_chart_style(cfg, "bar"), "bar")
        self.assertEqual(activity.chart_style(cfg), "bar")

    def test_line_chart_draws_the_hour_shape(self):
        import activity_chart

        hours = [0] * 24
        keys = [0] * 24
        clicks = [0] * 24
        wheels = [0] * 24
        travel_h = [0] * 24
        travel_h[12] = 64000
        keys[10] = 40
        clicks[15] = 12
        today = {
            "mode": "split",
            "keys": 40,
            "clicks": 12,
            "wheels": 0,
            "keys_h": keys,
            "clicks_h": clicks,
            "wheels_h": wheels,
            "hours": hours,
            "travel": 64000,
            "travel_h": travel_h,
            "peak": (10, 11),
        }
        im, hits = activity_chart.render(today, [], enabled=True, this_week=True, view="today", style="line")
        self.assertEqual(im.size, (activity_chart.W, activity_chart.H))
        self.assertGreaterEqual(len(hits), 8)
        self.assertTrue(any("约 1.0 米" in h["text"] for h in hits))
        self.assertTrue(any(str(h.get("speed", "")).startswith("打字") for h in hits))
        # 距离用自己的纵轴。若跟 6 万计数挤在一根轴上，40 次的键盘线会贴在底上。
        top_blues = lilacs = 0
        for y in range(80, 130):
            for x in range(30, im.width - 10, 2):
                p = im.getpixel((x, y))
                if p[2] > 180 and p[0] < 160 and p[1] > 140:
                    top_blues += 1
                if p[2] > p[0] > p[1] and p[2] > 150 and p[0] > 120:
                    lilacs += 1
        self.assertGreater(top_blues, 4)
        self.assertGreater(lilacs, 4)
        bars, _bar_hits = activity_chart.render(today, [], enabled=True, this_week=True, view="today", style="bar")
        self.assertEqual(bars.size, im.size)
        self.assertTrue(any(bars.getpixel((x, y))[:3] == (198, 160, 255) for y in range(60, bars.height - 20) for x in range(40, bars.width - 10, 3)))

    def test_surface_ring_is_full_minus_window(self):
        import backdrop

        img = Image.new("RGB", (20, 10), (200, 100, 0))
        img.paste((0, 0, 0), (5, 2, 15, 8))
        full = backdrop._box_sums(img, (0, 0, 20, 10))
        win = backdrop._box_sums(img, (5, 2, 15, 8))
        self.assertEqual(win, (60, 0.0, 0.0, 0.0))
        luma, rgb = backdrop._mean(*(a - b for a, b in zip(full, win)))
        self.assertEqual(rgb, (200, 100, 0))
        self.assertAlmostEqual(luma, 0.2126 * 200 + 0.7152 * 100, places=3)
        self.assertEqual(backdrop._box_sums(img, (30, 30, 40, 40))[0], 0)
        self.assertIsNone(backdrop._mean(0, 0.0, 0.0, 0.0))

    def test_async_sampler_hands_back_the_latest_result(self):
        import time as _time

        import backdrop

        s = backdrop.AsyncSampler()
        self.assertIsNone(s.take())
        s.request(100, 100, 248, 92)
        got = None
        deadline = _time.monotonic() + 2.0
        while got is None and _time.monotonic() < deadline:
            _time.sleep(0.02)
            got = s.take()
        self.assertIsNotNone(got)
        self.assertEqual(len(got[1]), 3)
        self.assertIsNone(s.take())

    def test_card_line_follows_the_display_switch(self):
        import activity

        cfg = {}
        d = date(2026, 10, 20)
        self.assertFalse(activity.show_on_card(cfg))
        activity.set_show_on_card(cfg, True)
        self.assertTrue(activity.enabled(cfg))
        self.assertTrue(activity.show_on_card(cfg))
        now = datetime(2026, 10, 20, 9, 0)
        activity.note(cfg, "key", now)
        activity.note(cfg, "click", now)
        activity.note(cfg, "wheel", now)
        activity.note(cfg, "key", now)
        self.assertEqual(activity.totals(cfg, d), (2, 1, 1))
        self.assertEqual(activity.totals(cfg, date(2026, 10, 19)), (0, 0, 0))
        activity.set_enabled(cfg, False)
        self.assertFalse(activity.show_on_card(cfg))
        self.assertFalse(activity.enabled(cfg))

    def test_chart_series_and_render(self):
        import activity
        import activity_chart

        self.assertEqual(activity_chart.nice_max(0), 10)
        self.assertEqual(activity_chart.nice_max(11), 15)
        self.assertEqual(activity_chart.nice_max(1000), 1000)
        self.assertEqual(activity_chart.visible_span([0] * 24), (8, 19))
        hours = [0] * 24
        hours[7] = 3
        hours[21] = 1
        self.assertEqual(activity_chart.visible_span(hours), (7, 21))

        cfg = {}
        d = date(2026, 10, 19)
        empty = activity_chart.today_pack(cfg, d)
        self.assertEqual(empty["mode"], "empty")
        activity.set_enabled(cfg, True)
        now = datetime(2026, 10, 19, 14, 0)
        activity.note(cfg, "click", now)
        activity.note(cfg, "click", now)
        activity.note(cfg, "key", now.replace(hour=9))
        pack = activity_chart.today_pack(cfg, d)
        self.assertEqual(pack["mode"], "split")
        self.assertEqual(pack["clicks_h"][14], 2)
        self.assertEqual(pack["keys_h"][9], 1)

        monday = d - timedelta(days=d.weekday())
        split_days = activity_chart.week_pack(
            cfg, [monday + timedelta(days=i) for i in range(7)], d,
        )
        self.assertEqual(activity.keep_days({}), 60)
        activity.set_keep_days(cfg, 7, today=d)
        self.assertEqual(activity.keep_days(cfg), 7)
        cfg["activity"]["days"]["2026-10-01"] = {"keys": 1, "clicks": 0, "wheels": 0, "hours": [0] * 24}
        activity.ensure_fields(cfg, today=d)
        self.assertNotIn("2026-10-01", cfg["activity"]["days"])
        self.assertEqual(activity.set_keep_days(cfg, 3, today=d), 60)

        self.assertEqual(activity_chart.week_totals(split_days), (1, 2, 0))
        week_im, week_hits = activity_chart.render(pack, split_days, enabled=True, this_week=True, view="week")
        self.assertEqual(week_im.size, (activity_chart.W, activity_chart.H))
        self.assertEqual(len(week_hits), 7)
        self.assertTrue(any("键盘" in h["text"] and "鼠标" in h["text"] for h in week_hits))
        self.assertEqual(
            activity_chart.week_totals(
                [{"mode": "split", "keys": 1, "clicks": 2, "wheels": 3}, {"mode": "combined", "keys": 9, "clicks": 9, "wheels": 0}],
            ),
            (1, 2, 3),
        )

        old = {"keys": 3, "clicks": 5, "wheels": 0, "hours": [0] * 24}
        old["hours"][10] = 8
        cfg["activity"]["days"]["2026-10-19"] = old
        legacy = activity_chart.today_pack(cfg, d)
        self.assertEqual(legacy["mode"], "combined")

        days = activity_chart.week_pack(cfg, [d], d)
        im, hits = activity_chart.render(pack, days, enabled=True, this_week=True)
        self.assertEqual(im.size, (activity_chart.W, activity_chart.H))
        sampled = {im.getpixel((x, y)) for x in range(0, im.width, 12) for y in range(0, im.height, 12)}
        self.assertGreater(len(sampled), 8)
        self.assertTrue(any("鼠标" in h["text"] and "滚轮" in h["text"] for h in hits))
        held = {"today_ptr": (hits[0]["x0"] + 1, hits[0]["y0"] + 1), "week_ptr": None}
        x, y = activity_chart.remembered_hover(held, "today")
        self.assertEqual(activity_chart.hover_text(hits, x, y), hits[0]["text"])
        self.assertEqual(activity_chart.remembered_hover(held, "week"), (-1, -1))
        off, off_hits = activity_chart.render(pack, days, enabled=False, this_week=True)
        self.assertEqual(off.size, im.size)
        self.assertEqual(off_hits, [])
        self.assertEqual(activity_chart.hover_text(hits, hits[0]["x0"] + 1, hits[0]["y0"] + 1), hits[0]["text"])

    def test_parse_raw_ignores_key_up(self):
        import activity

        key_down = bytearray(activity._HDR + 24)
        key_down[0] = 1
        self.assertEqual(activity.parse_raw(bytes(key_down)), "key")
        key_up = bytearray(key_down)
        key_up[activity._KEY_FLAGS_AT] = 1
        self.assertIsNone(activity.parse_raw(bytes(key_up)))
        mouse = bytearray(activity._HDR + 24)
        mouse[activity._BUTTON_FLAGS_AT] = 0x01
        self.assertEqual(activity.parse_raw(bytes(mouse)), "click")
        wheel = bytearray(activity._HDR + 24)
        wheel[activity._BUTTON_FLAGS_AT + 1] = 0x04
        self.assertEqual(activity.parse_raw(bytes(wheel)), "wheel")

    def test_physical_input_rejects_injected_and_empty_packets(self):
        import activity

        def hardware(kind: int) -> bytearray:
            buf = bytearray(activity._HDR + 24)
            buf[0:4] = kind.to_bytes(4, "little")
            buf[activity._DEVICE_AT:activity._DEVICE_AT + activity._DEVICE_SIZE] = (
                1234
            ).to_bytes(activity._DEVICE_SIZE, "little")
            return buf

        key = hardware(1)
        self.assertEqual(activity.physical_input(bytes(key)), "key")
        key[activity._KEY_FLAGS_AT] = 1
        self.assertIsNone(activity.physical_input(bytes(key)))  # 松键

        mouse = hardware(0)
        self.assertIsNone(activity.physical_input(bytes(mouse)))  # 0,0 空包
        mouse[activity._DX_AT:activity._DX_AT + 4] = (3).to_bytes(4, "little", signed=True)
        self.assertEqual(activity.physical_input(bytes(mouse)), "move")
        mouse[activity._BUTTON_FLAGS_AT] = 0x01
        self.assertEqual(activity.physical_input(bytes(mouse)), "click")

        injected = bytearray(mouse)
        injected[activity._DEVICE_AT:activity._DEVICE_AT + activity._DEVICE_SIZE] = bytes(
            activity._DEVICE_SIZE
        )
        self.assertIsNone(activity.physical_input(bytes(injected)))


class MinesTests(unittest.TestCase):
    def test_list_starts_with_mines(self):
        import mines

        self.assertEqual(mines.GAMES[0]["id"], "mines")
        self.assertIn("扫雷", mines.GAMES[0]["name"])

    def test_levels_and_cell_size(self):
        import mines

        easy, normal, hard = mines.LEVELS
        self.assertEqual((easy["rows"], easy["cols"], easy["mines"]), (9, 9, 10))
        self.assertEqual((normal["rows"], normal["cols"], normal["mines"]), (16, 16, 40))
        self.assertEqual((hard["rows"], hard["cols"], hard["mines"]), (16, 30, 99))
        self.assertEqual(mines.cell_side(9, 9), 28)
        self.assertLess(mines.cell_side(30, 16), 28)
        board = mines.Board(hard["rows"], hard["cols"], hard["mines"], seed=1)
        self.assertEqual(board.reveal(0, 0), "ok")
        self.assertFalse(board.mine[0][0])

    def test_first_click_is_safe_and_zero_floods(self):
        import mines

        board = mines.Board(seed=3)
        self.assertEqual(board.reveal(4, 4), "ok")
        self.assertFalse(board.mine[4][4])
        self.assertTrue(board.open[4][4])
        if board.around(4, 4) == 0:
            opened = sum(sum(1 for cell in row if cell) for row in board.open)
            self.assertGreater(opened, 1)

    def test_flag_blocks_reveal_and_boom_ends_the_game(self):
        import mines

        board = mines.Board(seed=5)
        board.reveal(0, 0)
        mine = next((r, c) for r in range(board.rows) for c in range(board.cols) if board.mine[r][c])
        self.assertEqual(board.toggle_flag(*mine), "flag")
        self.assertEqual(board.reveal(*mine), "noop")
        self.assertEqual(board.toggle_flag(*mine), "flag")
        self.assertEqual(board.reveal(*mine), "boom")
        self.assertTrue(board.dead)
        self.assertEqual(board.reveal(0, 1), "over")

    def test_clearing_safe_cells_wins(self):
        import mines

        board = mines.Board(rows=3, cols=3, mines=1, seed=1)
        board.reveal(0, 0)
        last = "win" if board.won else "ok"
        for r in range(3):
            for c in range(3):
                if board.mine[r][c] or board.open[r][c] or board.won:
                    continue
                last = board.reveal(r, c)
        self.assertTrue(board.won)
        self.assertEqual(last, "win")
        self.assertEqual(sum(sum(1 for m in row if m) for row in board.mine), 1)

    def test_session_keeps_board_until_new_game(self):
        import mines

        mines.reset_session()
        easy = mines.mines_slot("easy")["board"]
        self.assertFalse(mines.mines_in_progress())
        easy.reveal(0, 0)
        self.assertTrue(mines.mines_in_progress("easy"))
        opened = sum(sum(1 for cell in row if cell) for row in easy.open)
        self.assertIs(mines.mines_slot("easy")["board"], easy)
        self.assertEqual(sum(sum(1 for cell in row if cell) for row in mines.mines_slot("easy")["board"].open), opened)
        normal = mines.mines_slot("normal")["board"]
        self.assertIsNot(normal, easy)
        self.assertTrue(mines.mines_in_progress("easy"))
        self.assertFalse(mines.mines_in_progress("normal"))
        mines.resume_mines_clock("easy")
        self.assertIsNotNone(mines.mines_slot("easy")["running_since"])
        mines.pause_mines_clock("easy")
        self.assertIsNone(mines.mines_slot("easy")["running_since"])
        self.assertGreaterEqual(mines.mines_elapsed("easy"), 0)
        mines.mines_slot("easy", reset=True)
        self.assertIsNot(mines.mines_slot("easy")["board"], easy)
        self.assertFalse(mines.mines_in_progress("easy"))
        mines.reset_session()
        b = mines.golf_board()
        self.assertFalse(mines.golf_in_progress())
        b.draw()
        self.assertTrue(mines.golf_in_progress())
        self.assertIs(mines.golf_board(), b)
        mines.golf_board(reset=True)
        self.assertIsNot(mines.golf_board(), b)
        self.assertFalse(mines.golf_in_progress())
        mines.reset_session()
        p = mines.pool_board()
        self.assertFalse(mines.pool_in_progress())
        p.shoot(40, 0)
        self.assertTrue(mines.pool_in_progress())
        self.assertIs(mines.pool_board(), p)
        mines.pool_board(reset=True)
        self.assertIsNot(mines.pool_board(), p)
        self.assertFalse(mines.pool_in_progress())


class GolfTests(unittest.TestCase):
    def test_listed_after_mines(self):
        import mines

        ids = [g["id"] for g in mines.GAMES]
        self.assertEqual(ids[0], "mines")
        self.assertIn("golf", ids)

    def test_deal_and_only_adjacent_ranks_play(self):
        import golf

        board = golf.Board(seed=2)
        again = golf.Board(seed=2)
        self.assertEqual(board.columns[0][0], again.columns[0][0])
        self.assertEqual(len(board.columns), 7)
        self.assertEqual(len(board.stock), 16)
        self.assertEqual(len(board.waste), 1)
        top = board.waste_top()
        board.columns = [[golf.Card(0, top.rank)]]
        self.assertFalse(board.can_play(0))
        board.columns = [[golf.Card(0, 1)]]
        board.waste = [golf.Card(1, 13)]
        self.assertFalse(board.can_play(0))
        board.waste = [golf.Card(1, 2)]
        self.assertTrue(board.play(0))
        self.assertEqual(board.waste[-1].rank, 1)
        self.assertTrue(board.won)
        self.assertEqual(golf.status_text(board), "接完了")

    def test_draw_then_stuck(self):
        import golf

        board = golf.Board(seed=1)
        board.columns = [[golf.Card(0, 5)] for _ in range(7)]
        board.waste = [golf.Card(1, 5)]
        board.stock = [golf.Card(2, 9)]
        self.assertFalse(board.can_play(0))
        self.assertTrue(board.draw())
        self.assertFalse(board.stock)
        self.assertTrue(board.stuck)
        self.assertEqual(golf.status_text(board), "接不上了")
        self.assertFalse(board.draw())


class PoolTests(unittest.TestCase):
    def test_listed_with_the_others(self):
        import mines

        ids = [g["id"] for g in mines.GAMES]
        self.assertEqual(ids, ["mines", "golf", "pool"])

    def test_shoot_collides_and_pockets(self):
        import pool

        board = pool.Board()
        self.assertFalse(board.shoot(2, 0))
        self.assertTrue(board.shoot(40, 0))
        self.assertLess(board.cue.vx, 0)
        self.assertTrue(board.moved)

        cue, color = board.balls[0], board.balls[1]
        cue.x, cue.y, cue.vx, cue.vy = 100, 100, 120, 0
        color.x, color.y, color.vx, color.vy = 110, 100, 0, 0
        board._pairs()
        self.assertGreater(color.vx, 50)
        self.assertLess(abs(cue.vx), 50)

        color.x, color.vx = 2, -30
        board._walls()
        self.assertGreaterEqual(color.x, pool.R)
        self.assertGreater(color.vx, 0)

        color.x, color.y = 0, 0
        board._pockets()
        self.assertFalse(color.alive)
        self.assertEqual(pool.status_text(board), "进袋 1/6")

        board.cue.x, board.cue.y = 0, 0
        board._pockets()
        self.assertTrue(board.cue.alive)
        self.assertGreater(board.cue.x, 40)

        for ball in board.balls:
            if ball.kind == "color":
                ball.alive = False
        board.cue.vx = 40
        board.step(0.02)
        self.assertTrue(board.won)
        self.assertEqual(pool.status_text(board), "清台了")

    def test_guide_shows_the_ball_and_a_cushion(self):
        import math
        import pool

        board = pool.Board()
        other = board.balls[1]
        board.balls = [board.cue, other]
        board.cue.x, board.cue.y = 80, 100
        other.x, other.y = 200, 100
        hit = board.guide(-50, 0)
        self.assertIs(hit["ball"], other)
        self.assertGreater(hit["object_dir"][0], 0.9)
        self.assertAlmostEqual(math.hypot(*hit["object_dir"]), 1, places=3)

        board.balls = [board.cue]
        board.cue.x, board.cue.y = 80, 40
        bank = board.guide(0, 30)
        self.assertIsNone(bank["ball"])
        self.assertGreaterEqual(len(bank["path"]), 2)
        self.assertGreater(bank["path"][1][3], bank["path"][1][1])

    def test_a_shot_rolls_to_a_stop_on_the_table(self):
        import pool

        board = pool.Board()
        self.assertTrue(board.shoot(70, 12))
        for _ in range(350):
            board.step(0.02)
            for ball in board.balls:
                if not ball.alive:
                    continue
                self.assertGreaterEqual(ball.x, pool.R - 0.2)
                self.assertLessEqual(ball.x, pool.TABLE_W - pool.R + 0.2)
                self.assertGreaterEqual(ball.y, pool.R - 0.2)
                self.assertLessEqual(ball.y, pool.TABLE_H - pool.R + 0.2)
        self.assertFalse(board.moving)

    def test_guide_lines_start_off_and_stay_with_the_next_rack(self):
        import pool

        pool.set_guide_lines(False)
        self.assertFalse(pool.Board().guide_on)
        pool.set_guide_lines(True)
        self.assertTrue(pool.Board().guide_on)
        pool.set_guide_lines(False)

    def test_cushion_bounces_unless_the_ball_enters_the_pocket(self):
        import pool

        board = pool.Board()
        ball = board.balls[1]
        ball.x, ball.y, ball.vx, ball.vy = 120, pool.R, 30, 0
        board._pockets()
        self.assertTrue(ball.alive)
        ball.x, ball.y, ball.vy = 50, 2, -80
        board._walls()
        self.assertGreater(ball.vy, 0)
        self.assertTrue(ball.alive)
        ball.x, ball.y = pool.R, pool.R
        board._pockets()
        self.assertTrue(ball.alive)
        for other in board.balls:
            if other is not ball:
                other.alive = False
        ball.x, ball.y, ball.vx, ball.vy = 130, pool.R, 240, 0
        for _ in range(60):
            board.step(0.02)
        self.assertTrue(ball.alive)
        self.assertGreaterEqual(ball.y, pool.R - 0.2)
        ball.alive = True
        ball.x, ball.y, ball.vx, ball.vy = pool.TABLE_W / 2, 78, 0, -420
        for _ in range(40):
            board.step(0.02)
        self.assertFalse(ball.alive)


class ReleaseMailTests(unittest.TestCase):
    def _mail(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import release_mail

        return release_mail

    def test_message_goes_to_the_configured_address_with_the_setup(self):
        mail = self._mail()
        with tempfile.TemporaryDirectory() as tmp:
            setup = Path(tmp) / "WorkTimer-Setup.exe"
            setup.write_bytes(b"setup-bytes")
            win7 = Path(tmp) / "WorkTimer-Win7-Setup.exe"
            win7.write_bytes(b"win7-bytes")
            msg = mail.build_message(
                "1.3.56",
                "- 说明\nsha256: abcdef",
                setup,
                "from@example.com",
                ("to@example.com",),
                win7=win7,
            )
        body = msg.get_body(preferencelist=("plain",)).get_content()
        self.assertEqual(msg["To"], "to@example.com")
        self.assertIsNone(msg["Cc"])
        self.assertIn("最新版本：1.3.56", body)
        self.assertIn("from@example.com", body)
        self.assertNotIn("sha256", body.lower())
        self.assertNotIn("abcdef", body)
        self.assertIn("1.3.56", msg["Subject"])
        self.assertIn("安装包不在附件里", body)
        self.assertIn(mail.RELEASE_PAGE, body)
        self.assertEqual(list(msg.iter_attachments()), [])

    def test_smtp_secret_is_optional_until_the_file_is_complete(self):
        mail = self._mail()
        self.assertIsNone(mail.load_smtp(ROOT / "missing-release-mail.json"))
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "release_mail.secret.json"
            path.write_text('{"host": "smtp.example.com", "user": "a@b.c"}', encoding="utf-8")
            self.assertIsNone(mail.load_smtp(path))
            path.write_text(
                '{"host": "smtp.example.com", "port": 465, "user": "a@b.c",'
                ' "password": "secret", "from": "a@b.c"}',
                encoding="utf-8",
            )
            cfg = mail.load_smtp(path)
        self.assertEqual(cfg["host"], "smtp.example.com")
        self.assertEqual(cfg["from"], "a@b.c")
        self.assertNotIn("secret", cfg["host"])


class GhostGripTests(unittest.TestCase):
    def test_corner_marks_only_while_pointer_is_over(self):
        from PIL import ImageFont

        theme = next(t for t in themes._bundled_themes() if t.kind == "ghost")
        font = ImageFont.load_default()

        def corner(ptr):
            img = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
            themes.paint_card(
                img, 248, 92, theme, "", "", "", theme.title, font, font, font,
                stage="run", ghost_ptr=ptr,
            )
            px = img.load()
            return max(px[x, y][3] for y in range(0, 14) for x in range(0, 14))

        self.assertEqual(corner(None), 0)
        self.assertGreater(corner((120, 46)), 40)
        self.assertGreater(corner((4, 4)), corner((200, 70)))


class ShareTests(unittest.TestCase):
    def test_public_link_needs_no_token_and_names_the_setup(self):
        import share

        url = share.public_download_url(
            "https://gitcode.com/mdslanruo/work-timer", "1.3.72", "WorkTimer-Setup.exe",
        )
        self.assertEqual(
            url,
            "https://gitcode.com/mdslanruo/work-timer/releases/download/v1.3.72/WorkTimer-Setup.exe",
        )
        self.assertNotIn("token", url.lower())
        text = share.share_text("1.3.72", url)
        self.assertIn("不用登录", text)
        self.assertIn(url, text)

    def test_remembered_setup_can_be_handed_on(self):
        import share

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            src = root / "in.exe"
            src.write_bytes(b"MZ" + b"x" * (100 * 1024))
            saved = share.remember_setup(src, "WorkTimer-Setup.exe", root)
            self.assertEqual(share.cached_setup("WorkTimer-Setup.exe", root), saved)
            self.assertTrue(saved.is_file())
            small = root / "small.exe"
            small.write_bytes(b"MZ" + b"x" * 20)
            share.remember_setup(small, "WorkTimer-Win7-Setup.exe", root)
            self.assertIsNone(share.cached_setup("WorkTimer-Win7-Setup.exe", root))
            html = root / "page.exe"
            html.write_bytes(b"<h" + b"x" * (100 * 1024))
            share.remember_setup(html, "not-an-exe.exe", root)
            self.assertIsNone(share.cached_setup("not-an-exe.exe", root))
            with self.assertRaises(ValueError):
                share.cache_path(r"..\WorkTimer-Setup.exe", root)

    def test_file_clipboard_points_at_the_path(self):
        import share

        blob = share.hdrop_bytes(Path(r"C:\share\WorkTimer-Setup.exe"))
        self.assertEqual(int.from_bytes(blob[:4], "little"), 20)
        self.assertIn("WorkTimer-Setup.exe", blob.decode("utf-16-le", errors="ignore"))

    def test_text_clipboard_survives_a_tk_window(self):
        import ctypes
        import tkinter as tk
        import share

        user32 = ctypes.windll.user32
        kernel32 = ctypes.windll.kernel32
        root = tk.Tk()
        root.withdraw()
        marker = "弹性下班计时器-剪贴板"
        try:
            share.copy_text(marker)
            user32.OpenClipboard.argtypes = [ctypes.wintypes.HWND]
            user32.OpenClipboard.restype = ctypes.wintypes.BOOL
            user32.GetClipboardData.argtypes = [ctypes.wintypes.UINT]
            user32.GetClipboardData.restype = ctypes.c_void_p
            user32.CloseClipboard.argtypes = []
            kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalLock.restype = ctypes.c_void_p
            kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]
            kernel32.GlobalSize.argtypes = [ctypes.c_void_p]
            kernel32.GlobalSize.restype = ctypes.c_size_t
            self.assertTrue(user32.OpenClipboard(None))
            try:
                handle = user32.GetClipboardData(13)
                self.assertTrue(handle)
                ptr = kernel32.GlobalLock(handle)
                self.assertTrue(ptr)
                size = kernel32.GlobalSize(handle)
                raw = ctypes.string_at(ptr, size)
                kernel32.GlobalUnlock(handle)
            finally:
                user32.CloseClipboard()
            self.assertEqual(raw.decode("utf-16-le").split("\0", 1)[0], marker)
        finally:
            root.destroy()

    def test_progress_line_names_how_much_is_down(self):
        import share

        self.assertEqual(share.progress_line(0, 0), "正在下载安装包…")
        self.assertIn("已下", share.progress_line(2 * 1024 * 1024, 0))
        line = share.progress_line(3 * 1024 * 1024, 19 * 1024 * 1024)
        self.assertIn("3.0", line)
        self.assertIn("19.0", line)

    def test_pull_reads_in_steps_and_drops_a_short_file(self):
        import threading
        import share
        from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

        body = {"b": b"MZ" + b"x" * (120 * 1024)}

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                data = body["b"]
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, fmt, *args):
                return

        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = httpd.server_address[1]
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                part = Path(tmp) / "WorkTimer-Setup.exe.download"
                pull = share.Pull(f"http://127.0.0.1:{port}/a", part)
                state = "go"
                for _ in range(40):
                    state = pull.step()
                    if state == "ok":
                        break
                self.assertEqual(state, "ok")
                self.assertTrue(part.read_bytes().startswith(b"MZ"))
                self.assertGreaterEqual(part.stat().st_size, 100 * 1024)
                body["b"] = b"MZ" + b"y" * 30
                short = Path(tmp) / "short.download"
                bad = share.Pull(f"http://127.0.0.1:{port}/b", short)
                with self.assertRaises(RuntimeError):
                    for _ in range(10):
                        if bad.step() == "ok":
                            break
                self.assertFalse(short.exists())
        finally:
            httpd.shutdown()
            httpd.server_close()


class PaintCostTests(unittest.TestCase):
    def test_stamped_text_matches_draw_text(self):
        import fx
        from PIL import ImageDraw

        font = fx._flip_font(26)
        base = Image.new("RGBA", (90, 50), (30, 40, 60, 210))
        ImageDraw.Draw(base).rectangle((8, 8, 50, 30), fill=(240, 230, 200, 255))
        for text, fill, xy in (("8", (0, 0, 0, 115), (12, 4)), ("时", (255, 255, 255, 125), (-4, 30)), ("5", (248, 250, 255), (70, -6))):
            want = base.copy()
            ImageDraw.Draw(want).text(xy, text, font=font, fill=fill)
            for _ in range(2):
                got = base.copy()
                fx.stamp_text(ImageDraw.Draw(got), xy, text, font, fill)
                self.assertEqual(got.tobytes(), want.tobytes(), text)

    def test_stroked_stamp_is_within_one_level(self):
        import fx
        from PIL import ImageDraw

        font = fx._flip_font(24)
        base = Image.new("RGBA", (60, 50), (250, 220, 230, 255))
        want = base.copy()
        ImageDraw.Draw(want).text((10, 6), "7", font=font, fill=(255, 255, 255, 255), stroke_width=3, stroke_fill=(255, 255, 255, 255))
        got = base.copy()
        fx.stamp_text(ImageDraw.Draw(got), (10, 6), "7", font, (255, 255, 255, 255), stroke_width=3)
        self.assertLessEqual(max(abs(a - b) for a, b in zip(got.tobytes(), want.tobytes())), 1)

    def test_card_background_is_reused_within_its_frame(self):
        theme = themes.resolve_for_surface(themes.get_theme("frost"), "dark")
        font = ornaments.fx._flip_font(20)
        calls = {"n": 0}
        real = ornaments.paste_skin

        def counting(*a, **k):
            calls["n"] += 1
            return real(*a, **k)

        ornaments.paste_skin = counting
        themes._BG_CACHE.clear()
        try:
            frames = []
            for _ in range(3):
                img = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
                themes.paint_card(
                    img, 248, 92, theme, "距离下班", "1:23:45", "", theme.big, font, font, font,
                    bg_hz=0.001,
                )
                frames.append(img.tobytes())
        finally:
            ornaments.paste_skin = real
            themes._BG_CACHE.clear()
        self.assertEqual(calls["n"], 1)
        self.assertEqual(frames[0], frames[1])

    def test_screen_asleep_follows_lock_and_display_messages(self):
        import ctypes

        import layered_win as lw

        # 同名窗口类只登记第一次的窗口过程，换个类名才收得到自己的消息
        win = lw.LayeredPetWindow(80, 40, class_name="WorkTimerSleepTestWnd", visible=False)
        try:
            self.assertFalse(win.screen_asleep)
            lw.user32.SendMessageW(win.hwnd, lw.WM_WTSSESSION_CHANGE, lw.WTS_SESSION_LOCK, 0)
            self.assertTrue(win.screen_asleep)
            lw.user32.SendMessageW(win.hwnd, lw.WM_WTSSESSION_CHANGE, lw.WTS_SESSION_UNLOCK, 0)
            self.assertFalse(win.screen_asleep)

            note = lw.POWERBROADCAST_SETTING()
            note.PowerSetting = lw._DISPLAY_GUIDS[0]
            note.DataLength = 4
            note.Data = 0
            lw.user32.SendMessageW(win.hwnd, lw.WM_POWERBROADCAST, lw.PBT_POWERSETTINGCHANGE, ctypes.addressof(note))
            self.assertTrue(win.screen_asleep)
            note.Data = 1
            lw.user32.SendMessageW(win.hwnd, lw.WM_POWERBROADCAST, lw.PBT_POWERSETTINGCHANGE, ctypes.addressof(note))
            self.assertFalse(win.screen_asleep)

            # 漏收解锁消息：这台机子没锁，能打开输入桌面，就该自己醒过来
            lw.user32.SendMessageW(win.hwnd, lw.WM_WTSSESSION_CHANGE, lw.WTS_SESSION_LOCK, 0)
            win.check_awake()
            self.assertFalse(win.screen_asleep)
        finally:
            win.destroy()


if __name__ == "__main__":
    unittest.main()
