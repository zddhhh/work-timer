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
import sky  # noqa: E402
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
        self.assertEqual(ids.index("auto"), ids.index("ghost") + 1)

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


class SkyTests(unittest.TestCase):
    def test_solar_mapping(self):
        noon = datetime(2026, 9, 18, 12, 0)
        self.assertEqual(sky.solar_t(noon, remaining_sec=0, done=True, idle=False), 1.0)
        # 剩余 > 30 分钟：太阳不落
        self.assertLessEqual(sky.solar_t(noon, remaining_sec=7200, done=False, idle=False), 0.62)
        late = datetime(2026, 9, 18, 23, 0)
        self.assertGreaterEqual(sky.solar_t(late, remaining_sec=7200, done=False, idle=False), 0.3)
        # 最后 30 分钟单调走向夜
        a = sky.solar_t(noon, remaining_sec=1500, done=False, idle=False)
        b = sky.solar_t(noon, remaining_sec=300, done=False, idle=False)
        self.assertLess(a, b)
        self.assertLess(b, 1.0)
        # 闲置按钟点
        self.assertLess(sky.solar_t(datetime(2026, 9, 18, 2, 0), remaining_sec=None, done=False, idle=True), 0.1)
        self.assertTrue(sky.is_bright(0.5))
        self.assertFalse(sky.is_bright(0.95))

    def test_paint_and_confetti_do_not_crash(self):
        img = Image.new("RGBA", (248, 92), (0, 0, 0, 0))
        for t in (0.0, 0.22, 0.5, 0.78, 0.9, 1.0):
            sky.paint(img, (4, 4, 243, 87), t, 12.3, radius=18)
        for tt in (0.0, 1.0, 2.7, 5.0):
            ornaments.paint_confetti(img, 248, 92, tt)
        self.assertEqual(img.size, (248, 92))
        self.assertEqual(themes.get_theme("sky").kind, "sky")


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
