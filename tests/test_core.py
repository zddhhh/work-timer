"""纯函数回归：不开窗、不联网。运行：.\\.venv\\Scripts\\python.exe -m unittest discover -s tests -v"""
from __future__ import annotations

import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import attachments  # noqa: E402
import feedback  # noqa: E402
import festival  # noqa: E402
import store  # noqa: E402
import flex_time  # noqa: E402
import ornaments  # noqa: E402
import schedules  # noqa: E402
import themes  # noqa: E402
import updater  # noqa: E402
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


class ReplaceOnceTests(unittest.TestCase):
    def test_retry_keeps_backup(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            cur, staged, old = root / "a.exe", root / "a.exe.new", root / "a.exe.old"
            cur.write_bytes(b"OLD")
            staged.write_bytes(b"NEW")
            updater._replace_once(cur, staged, old)
            self.assertEqual(cur.read_bytes(), b"NEW")
            self.assertEqual(old.read_bytes(), b"OLD")
            # 模拟第一次只完成了 cur→old、staged 尚未就位时的重试：备份不能被删
            cur.unlink()
            staged.write_bytes(b"NEW2")
            updater._replace_once(cur, staged, old)
            self.assertEqual(cur.read_bytes(), b"NEW2")
            self.assertEqual(old.read_bytes(), b"OLD")


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
        self.assertLessEqual(len(merged), 16)

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


class FeedbackTests(unittest.TestCase):
    def test_body_has_contact_and_roundtrip(self):
        body = feedback._compose_body("hi", "  me@x.com   wx:abc ")
        self.assertIn("- 联系：me@x.com wx:abc", body)
        self.assertEqual(feedback.parse_contact(body), "me@x.com wx:abc")
        self.assertNotIn("联系", feedback._compose_body("hi", ""))

    def test_normalize_contact_truncates(self):
        self.assertEqual(len(feedback.normalize_contact("a" * 500)), 120)


class ScheduleFieldTests(unittest.TestCase):
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
        self.assertTrue(cfg["ctrl_hide"])
        self.assertNotIn("esc_disguise", cfg)

    def test_log_keeps_tail(self):
        path = store.user_data_dir() / "error.log"
        path.write_bytes(b"x" * 90_000 + b"\nKEEP\n")
        store.append_log("new")
        data = path.read_bytes()
        self.assertLess(len(data), 41_000)
        self.assertIn(b"KEEP", data)
        self.assertTrue(data.endswith(b"new\n"))


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
        self.assertEqual(layer.size, (248, 92))
        self.assertTrue(ornaments.has_skin("neonflow"))
        self.assertTrue(ornaments.has_skin("inkpulse"))
        self.assertTrue(ornaments.is_animated("inkpulse"))

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

    def test_wolf_jaw_opens_downward(self):
        """下颌绕关节转的方向极易搞反：张口时下巴必须往下走，不能把嘴掀上天。"""
        import fx

        def chin_y(jaw):
            head = fx._wolf_head(120, jaw, (176, 228, 255), gain=1.0)
            a = head.getchannel("A")
            # 只看吻部那一段（局部 x 10~50），颈背会一直顶到画布底
            ys = [y for y in range(head.height) for x in range(12, 60) if a.getpixel((x, y)) > 100]
            return max(ys), min(ys)

        closed_low, closed_top = chin_y(0)
        open_low, open_top = chin_y(32)
        self.assertGreater(open_low, closed_low + 4)
        self.assertLessEqual(closed_top, open_top + 2)  # 上颌不该跟着动

    def test_wolf_bite_window(self):
        """咬合只在 0~BITE_SEC 内画，越界必须什么都不留。"""
        import fx

        mid = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
        fx.paint_wolf_bite(mid, fx.BITE_SEC * 0.4, stage="run")
        self.assertGreater(sum(1 for a in mid.getchannel("A").getdata() if a > 60), 400)
        for t in (-0.1, fx.BITE_SEC + 0.01):
            blank = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
            fx.paint_wolf_bite(blank, t, stage="run")
            self.assertEqual(max(blank.getchannel("A").getdata()), 0, t)

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

        body = (
            "WorkTimer 1.2.2\n\n"
            "- 墨水涟漪的落墨点移到大数字右边\n"
            "* 更新提示改成人话\n"
            "\n"
            "sha256: 634fdfeb2db5a675de54bfdff8241661\n"
        )
        got = changelog.highlights(body)
        self.assertEqual(got, ["墨水涟漪的落墨点移到大数字右边", "更新提示改成人话"])
        self.assertEqual(changelog.highlights(""), [])
        self.assertEqual(changelog.highlights("WorkTimer 1.2.2\nsha256: abc"), [])
        self.assertEqual(len(changelog.highlights("- a\n- b\n- c\n- d\n- e\n- f")), 4)

    def test_friendly_update_errors(self):
        """弹窗不该把 HTTPError 原文甩给用户。"""
        cases = {
            "HTTP 404": "更新源上还没有发布版本",
            "HTTP 403": "更新服务器拒绝了请求",
            "HTTP 502": "更新服务器暂时故障",
            "网络错误：[Errno 11001] getaddrinfo failed": "连不上更新服务器",
            "连接超时": "连不上更新服务器",
            "sha256 校验失败": "下载的文件没通过校验",
        }
        for raw, head in cases.items():
            self.assertEqual(updater.friendly_error(raw)[0], head, raw)
        # 兜底也得有标题，且不能把原文丢掉
        head, hint = updater.friendly_error("something exploded")
        self.assertTrue(head)
        self.assertIn("exploded", hint)

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


if __name__ == "__main__":
    unittest.main()
