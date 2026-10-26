"""启动器：更新没进主界面就回到上一版，并且自己不依赖 VC 运行库。"""
from __future__ import annotations

import os
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import boot_ok  # noqa: E402
import build_release  # noqa: E402
import desktop_shortcut  # noqa: E402

def _gcc_dir() -> Path:
    return build_release._gcc_bin()


def _compile_stub(gcc_dir: Path, out: Path) -> None:
    subprocess.check_call(
        [
            str(gcc_dir / "gcc.exe"),
            "-Os", "-s", "-static", "-static-libgcc", "-mwindows",
            "-Wl,--subsystem,windows:6.1",
            "-o", str(out),
            str(ROOT / "launcher" / "bootstub.c"),
            "-lkernel32",
        ]
    )


def _runtime(folder: Path, *, ok: bool = True, py: str = "python312.dll") -> None:
    internal = folder / "_internal"
    internal.mkdir(parents=True, exist_ok=True)
    (internal / py).write_bytes(b"x")
    if not ok:
        return
    (internal / "vcruntime140.dll").write_bytes(b"x")
    if py == "python312.dll":
        (internal / "vcruntime140_1.dll").write_bytes(b"x")


def _exe(folder: Path, stub: bytes, tail: bytes) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "WorkTimer.bin.exe").write_bytes(stub + tail)


class LauncherTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        gcc = _gcc_dir()
        cls.launcher = build_release.compile_launcher()
        cls.stub_path = ROOT / "build" / "bootstub.exe"
        cls.stub_path.parent.mkdir(parents=True, exist_ok=True)
        _compile_stub(gcc, cls.stub_path)
        cls.stub = cls.stub_path.read_bytes()
        cls.objdump = gcc / "objdump.exe"
        cls.mutex_name = f"Local\\WorkTimer.LauncherTest.{os.getpid()}"

    def _run(self, app: Path, boot: Path, extra: tuple[str, ...] = ()) -> subprocess.CompletedProcess:
        env = os.environ.copy()
        env["WT_BOOT_DIR"] = str(boot)
        env["WT_MUTEX_NAME"] = self.mutex_name
        return subprocess.run(
            [str(app / "WorkTimer.exe"), *extra],
            cwd=app,
            env=env,
            timeout=20,
            check=False,
        )

    def _install_launcher(self, app: Path) -> None:
        app.mkdir(parents=True, exist_ok=True)
        (app / "WorkTimer.exe").write_bytes(self.launcher.read_bytes())

    def test_launcher_does_not_need_vcruntime(self) -> None:
        dump = subprocess.check_output([str(self.objdump), "-p", str(self.launcher)], text=True, errors="replace")
        low = dump.lower()
        for banned in ("vcruntime", "python3", "libgcc", "libwinpthread", "libstdc"):
            self.assertNotIn(banned, low, banned)
        self.assertLess(self.launcher.stat().st_size, 2 * 1024 * 1024)

    def test_swap_keeps_the_new_version_after_it_boots(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            self._install_launcher(app)
            _runtime(app)
            _exe(app, self.stub, b"GOOD")
            pending = app / "_pending"
            _runtime(pending)
            _exe(pending, self.stub, b"NEW1")
            (pending / "_internal" / "marker.txt").write_text("new", encoding="ascii")
            (app / "_internal" / "marker.txt").write_text("old", encoding="ascii")
            (pending / "READY").write_text("ok", encoding="ascii")
            result = self._run(app, root / "boot", ("--legacy-cleanup", r"C:\nope"))
            self.assertEqual(result.returncode, 0)
            cmdline = (app / "cmdline.txt").read_text(encoding="utf-8")
            self.assertIn("--boot-token", cmdline)
            self.assertIn("--legacy-cleanup", cmdline)
            self.assertIn("nope", cmdline)
            self.assertTrue((app / "WorkTimer.bin.exe").read_bytes().endswith(b"NEW1"))
            self.assertEqual((app / "_internal" / "marker.txt").read_text(encoding="ascii"), "new")
            self.assertFalse((app / "_prev").exists())
            self.assertFalse((app / "_pending").exists())
            self.assertTrue((app / "good-ran.txt").is_file())

    def test_failed_boot_restores_the_previous_version(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            self._install_launcher(app)
            _runtime(app)
            _exe(app, self.stub, b"GOOD")
            (app / "_internal" / "marker.txt").write_text("old", encoding="ascii")
            pending = app / "_pending"
            _runtime(pending)
            _exe(pending, self.stub, b"BAD!")
            (pending / "READY").write_text("ok", encoding="ascii")
            result = self._run(app, root / "boot")
            self.assertEqual(result.returncode, 0)
            self.assertTrue((app / "WorkTimer.bin.exe").read_bytes().endswith(b"GOOD"))
            self.assertEqual((app / "_internal" / "marker.txt").read_text(encoding="ascii"), "old")
            self.assertTrue((app / "bad-ran.txt").is_file())
            self.assertTrue((app / "good-ran.txt").is_file())
            self.assertFalse((app / "_prev").exists())
            self.assertFalse(app.joinpath("_pending").exists())

    def test_incomplete_pending_is_left_until_it_is_ready(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            self._install_launcher(app)
            _runtime(app)
            _exe(app, self.stub, b"GOOD")
            pending = app / "_pending"
            _runtime(pending)
            _exe(pending, self.stub, b"NEW1")
            result = self._run(app, root / "boot")
            self.assertEqual(result.returncode, 0)
            self.assertTrue((app / "WorkTimer.bin.exe").read_bytes().endswith(b"GOOD"))
            self.assertTrue((pending / "WorkTimer.bin.exe").read_bytes().endswith(b"NEW1"))

    def test_ready_but_missing_runtime_is_discarded(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            self._install_launcher(app)
            _runtime(app)
            _exe(app, self.stub, b"GOOD")
            pending = app / "_pending"
            _runtime(pending, ok=False)
            _exe(pending, self.stub, b"NEW1")
            (pending / "READY").write_text("ok", encoding="ascii")
            result = self._run(app, root / "boot")
            self.assertEqual(result.returncode, 0)
            self.assertTrue((app / "WorkTimer.bin.exe").read_bytes().endswith(b"GOOD"))
            self.assertFalse(pending.exists())

    def test_unconfirmed_backup_is_restored_before_start(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            self._install_launcher(app)
            _runtime(app, ok=False)
            _exe(app, self.stub, b"BAD!")
            prev = app / "_prev"
            _runtime(prev)
            _exe(prev, self.stub, b"GOOD")
            (prev / "COMMIT").write_text("1", encoding="ascii")
            result = self._run(app, root / "boot")
            self.assertEqual(result.returncode, 0)
            self.assertTrue((app / "WorkTimer.bin.exe").read_bytes().endswith(b"GOOD"))
            self.assertFalse((app / "bad-ran.txt").exists())
            self.assertTrue((app / "good-ran.txt").is_file())
            self.assertFalse(prev.exists())

    def test_crash_of_a_confirmed_version_does_not_roll_back(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            self._install_launcher(app)
            _runtime(app)
            _exe(app, self.stub, b"BAD!")
            result = self._run(app, root / "boot")
            self.assertEqual(result.returncode, 1)
            self.assertTrue((app / "WorkTimer.bin.exe").read_bytes().endswith(b"BAD!"))
            self.assertFalse((app / "_prev").exists())
            self.assertTrue((app / "bad-ran.txt").is_file())

    def test_win7_runtime_swaps_without_vcruntime140_1(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            self._install_launcher(app)
            _runtime(app, py="python38.dll")
            _exe(app, self.stub, b"GOOD")
            pending = app / "_pending"
            _runtime(pending, py="python38.dll")
            _exe(pending, self.stub, b"NEW1")
            (pending / "READY").write_text("ok", encoding="ascii")
            result = self._run(app, root / "boot")
            self.assertEqual(result.returncode, 0)
            self.assertTrue((app / "WorkTimer.bin.exe").read_bytes().endswith(b"NEW1"))
            self.assertTrue((app / "_internal" / "python38.dll").is_file())
            self.assertFalse((app / "_internal" / "vcruntime140_1.dll").exists())

    def test_running_app_blocks_any_swap(self) -> None:
        import ctypes
        import tempfile
        kernel32 = ctypes.windll.kernel32
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        handle = kernel32.CreateMutexW(None, False, self.mutex_name)
        self.assertTrue(handle)
        try:
            with tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                app = root / "app"
                self._install_launcher(app)
                _runtime(app)
                _exe(app, self.stub, b"GOOD")
                prev = app / "_prev"
                _runtime(prev)
                _exe(prev, self.stub, b"OLD1")
                (prev / "COMMIT").write_text("1", encoding="ascii")
                pending = app / "_pending"
                _runtime(pending)
                _exe(pending, self.stub, b"NEW1")
                (pending / "READY").write_text("ok", encoding="ascii")
                result = self._run(app, root / "boot")
                self.assertEqual(result.returncode, 0)
                self.assertTrue((app / "WorkTimer.bin.exe").read_bytes().endswith(b"GOOD"))
                self.assertTrue((prev / "COMMIT").is_file())
                self.assertTrue((pending / "READY").is_file())
                import time
                for _ in range(40):
                    try:
                        (app / "WorkTimer.bin.exe").unlink()
                        break
                    except OSError:
                        time.sleep(0.1)
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))

    def test_locked_live_runtime_is_not_half_deleted(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            app = root / "app"
            self._install_launcher(app)
            _runtime(app)
            _exe(app, self.stub, b"BAD!")
            prev = app / "_prev"
            _runtime(prev)
            _exe(prev, self.stub, b"GOOD")
            (prev / "COMMIT").write_text("1", encoding="ascii")
            locked = (app / "_internal" / "zz-locked.pyd").open("wb")
            try:
                result = self._run(app, root / "boot")
            finally:
                locked.close()
            self.assertNotEqual(result.returncode, 2)
            for name in ("python312.dll", "vcruntime140.dll", "vcruntime140_1.dll"):
                self.assertTrue((app / "_internal" / name).is_file(), name)

    def test_shortcut_points_at_the_launcher(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "WorkTimer.bin.exe").write_bytes(b"MZ")
            (root / "WorkTimer.exe").write_bytes(b"MZ")
            self.assertEqual(desktop_shortcut.installed_exe(root / "WorkTimer.bin.exe").name, "WorkTimer.exe")
            (root / "WorkTimer.exe").unlink()
            self.assertEqual(desktop_shortcut.installed_exe(root / "WorkTimer.bin.exe").name, "WorkTimer.bin.exe")

    def test_boot_signal_writes_the_token_file(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(sys, "argv", ["WorkTimer.bin.exe", "--boot-token", "ab12"]), \
                    mock.patch.dict(os.environ, {"WT_BOOT_DIR": str(folder)}):
                boot_ok.signal()
            self.assertEqual((folder / "boot-ab12.ok").read_text(encoding="ascii"), "ok")
            with mock.patch.object(sys, "frozen", True, create=True), \
                    mock.patch.object(sys, "argv", ["WorkTimer.bin.exe", "--boot-token", "../x"]), \
                    mock.patch.dict(os.environ, {"WT_BOOT_DIR": str(folder)}):
                boot_ok.signal()
            self.assertFalse((folder / "boot-../x.ok").exists())


if __name__ == "__main__":
    unittest.main()
