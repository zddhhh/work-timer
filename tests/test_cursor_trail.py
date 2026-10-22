"""光标尾巴：长度、裁剪、画面。不开窗口。"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import cursor_trail as trail  # noqa: E402


class TrailMathTests(unittest.TestCase):
    def test_length_shrinks_toward_the_end_of_the_day(self):
        morning = trail.trail_length(8 * 3600)
        afternoon = trail.trail_length(2 * 3600)
        last = trail.trail_length(5 * 60)
        done = trail.trail_length(0)
        self.assertGreater(morning, afternoon)
        self.assertGreater(afternoon, last)
        self.assertGreater(last, done)
        self.assertAlmostEqual(done, trail.MIN_PX)
        self.assertAlmostEqual(trail.trail_length(trail.FULL_DAY + 999), trail.MAX_PX)

    def test_trim_keeps_the_head_and_the_requested_length(self):
        points = [(float(i), 0.0) for i in range(0, 101)]
        kept = trail.trim_trail(points, 40)
        self.assertEqual(kept[-1], (100.0, 0.0))
        span = kept[-1][0] - kept[0][0]
        self.assertAlmostEqual(span, 40.0, places=3)
        self.assertLess(kept[0][0], kept[-1][0])

    def test_frame_matches_the_trail_instead_of_a_full_screen(self):
        points = [(float(i * 4), 10.0) for i in range(20)]
        img, left, top = trail.frame_for(points, (96, 186, 255), 1.0)
        self.assertLess(img.width, 160)
        self.assertLess(img.height, 80)
        self.assertLess(left, 0)
        self.assertGreater(img.getpixel((img.width - 8, img.height // 2))[3], 40)

    def test_ribbon_is_bright_at_the_head_and_clear_in_the_corner(self):
        pts = []
        for i in range(80):
            pts.append((180 + i * 3.2, 320 + (i - 40) * 0.4))
        img = trail.draw_ribbon(pts, (176, 214, 236), 1.0)
        hx, hy = int(pts[-1][0]), int(pts[-1][1])
        self.assertGreater(img.getpixel((hx, hy))[3], 80)
        self.assertEqual(img.getpixel((2, 2))[3], 0)
        self.assertEqual(img.getpixel((img.width - 2, 2))[3], 0)
