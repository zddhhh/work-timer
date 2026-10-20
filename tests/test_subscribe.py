"""订阅云函数：报名名单和连不上网时的二维码。"""
from __future__ import annotations

import hashlib
import importlib.util
import io
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _fn():
    spec = importlib.util.spec_from_file_location(
        "subscribe_scf", ROOT / "scf" / "subscribe" / "index.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class SubscribeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fn = _fn()

    def test_form_offers_once_and_auto(self):
        html = self.fn._form()
        self.assertIn("只要这一版", html)
        self.assertIn("以后每版都寄", html)
        self.assertIn('name="email"', html)

    def test_signup_once_sends_current_and_does_not_stay(self):
        got = self.fn.signup({}, "a@x.com", "once", "1.3.57")
        self.assertTrue(got["send"])
        self.assertEqual(got["state"]["auto"], [])
        self.assertIn("只要这一版", got["text"])

    def test_signup_auto_stays_and_second_time_skips_same_version(self):
        first = self.fn.signup({}, "A@X.com", "auto", "1.3.57")
        self.assertEqual(first["state"]["auto"], ["a@x.com"])
        first["state"]["mailed"]["a@x.com"] = "1.3.57"
        second = self.fn.signup(first["state"], "a@x.com", "auto", "1.3.57")
        self.assertFalse(second["send"])
        self.assertEqual(second["state"]["auto"], ["a@x.com"])

    def test_manual_removes_auto(self):
        state = {"auto": ["a@x.com"], "mailed": {}}
        got = self.fn.signup(state, "a@x.com", "once", "1.3.58")
        self.assertEqual(got["state"]["auto"], [])
        self.assertTrue(got["send"])

    def test_fanout_waits_for_a_newer_version(self):
        state = {"last_version": "1.3.57", "auto": ["a@x.com"], "mailed": {"a@x.com": "1.3.57"}}
        self.assertEqual(self.fn.due_auto(state, "1.3.57"), [])
        self.assertEqual(self.fn.due_auto({"auto": ["a@x.com"]}, "1.3.57"), [])
        self.assertEqual(self.fn.due_auto(state, "1.3.58"), ["a@x.com"])

    def test_mail_shows_version_and_sender_without_the_checksum(self):
        note = "WorkTimer 1.3.58\n\n- 说明一条\n\n# sha256(WorkTimer-Setup.exe): deadbeef\n# sha256: deadbeef\n"
        text = self.fn.mail_text("1.3.58", "earoot@163.com", note)
        self.assertIn("最新版本：1.3.58", text)
        self.assertIn("earoot@163.com", text)
        self.assertIn("WorkTimer-Win7-Setup.exe", text)
        self.assertIn("说明一条", text)
        self.assertNotIn("sha256", text.lower())
        self.assertNotIn("deadbeef", text)
        files = [("WorkTimer-Setup.exe", b"main"), ("WorkTimer-Win7-Setup.exe", b"win7")]
        msg = self.fn.build_mail("a@x.com", "1.3.58", "earoot@163.com", note, files)
        self.assertEqual(msg["Subject"], "WorkTimer 最新版 1.3.58")
        self.assertNotIn("sha256", msg.get_body(preferencelist=("plain",)).get_content().lower())
        self.assertEqual(msg["X-WorkTimer-Setup"], hashlib.sha256(b"main").hexdigest())
        self.assertEqual(msg["X-WorkTimer-Win7"], hashlib.sha256(b"win7").hexdigest())
        packed = next(msg.iter_attachments()).get_payload(decode=True)
        self.assertEqual(
            zipfile.ZipFile(io.BytesIO(packed)).namelist(),
            ["WorkTimer-Setup.exe", "WorkTimer-Win7-Setup.exe"],
        )

    def test_signup_names_the_sender(self):
        got = self.fn.signup({}, "a@x.com", "once", "1.3.58", "earoot@163.com")
        self.assertIn("最新版 1.3.58", got["text"])
        self.assertIn("earoot@163.com", got["text"])
        self.assertIn("Win7", got["text"])

    def test_bad_email_rejected(self):
        self.assertIsNone(self.fn._clean_email("not-an-email"))
        self.assertIsNone(self.fn._clean_email("a@b.com\nBcc: evil@x.com"))
        self.assertEqual(self.fn._clean_email(" A@B.COM "), "a@b.com")

    def test_cos_signature_covers_host(self):
        auth = self.fn.cos_authorization(
            "AKID", "secret", "PUT", "/subscribe/state.json",
            "demo-125.cos.ap-guangzhou.myqcloud.com",
            start=100, end=200,
        )
        self.assertIn("q-ak=AKID", auth)
        self.assertIn("q-header-list=host", auth)
        self.assertIn("q-sign-time=100;200", auth)
        self.assertIn("q-signature=", auth)

    def test_network_error_shows_subscribe_case(self):
        import updater

        self.assertTrue(updater.is_network_error("网络错误：timed out"))
        self.assertFalse(updater.is_network_error("HTTP 404"))

    def test_qr_encodes_url(self):
        import qrcode

        url = "https://example.com/subscribe"
        code = qrcode.QRCode(border=1, box_size=4)
        code.add_data(url)
        code.make(fit=True)
        img = code.make_image(fill_color="black", back_color="white").convert("RGB")
        colors = img.getcolors(500000)
        self.assertGreater(len(colors or []), 1)
        self.assertGreater(img.width, 40)
