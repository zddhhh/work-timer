"""透明下班倒计时：桌面置顶小窗，点一下设置今天下班时间。"""
from __future__ import annotations

import ctypes
import os
import ssl
import sys
import threading
import time
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import messagebox

from PIL import Image, ImageChops, ImageFont

import activity
import attachments
import autostart
import backdrop
import boot_ok
import changelog
import cursor_trail
import desktop_shortcut
import festival
import feedback
import flex_time
import hydrate
import key_hide
import kinetic
import layered_win
import memos
import meow
import mines
import ornaments
import power_save
import schedules
import share
import single_instance
import skin_settings
import store
import suofen
import themes
import ticker
import uninstall
import updater
import worklog
from card_ui import (
    _CARD_ACCENT,
    _CARD_BG,
    _CARD_BTN,
    _CARD_FG,
    _CARD_MUTED,
    _Anchor,
    _ask_offwork_setup,
    _card_btn,
    _card_dialog,
    _fit_card,
    _geom_wh,  # noqa: F401  测试从 main 里取
    _hide_open_card,
    _offscreen_bounds,  # noqa: F401  测试从 main 里取
    _pack_err_line,
    _pack_full_text,
    _park_card,
    _reveal_card,
    _run_card_modal,
)
from schedule_ui import ScheduleDialogMixin
from update_ui import UpdateDialogMixin
from version import APP_VERSION
from worklog_ui import WorklogDialogMixin

FPS = 60
IDLE_FPS = 30
_LEGACY_SIZES = {"s": (248, 92), "m": (320, 118), "l": (400, 148)}


_FONT_CACHE: dict[float, ImageFont.ImageFont] = {}


def _font(size: float) -> ImageFont.ImageFont:
    """字号按 0.25 像素一档缓存。拉伸时字连续变大，又不用每帧重新读字体文件。"""
    key = round(float(size) * 4.0) / 4.0
    got = _FONT_CACHE.get(key)
    if got is not None:
        return got
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("msyhbd.ttc", "msyh.ttc", "msyh.ttf", "simhei.ttf"):
        try:
            got = ImageFont.truetype(str(windir / name), key)
            break
        except OSError:
            continue
    if got is None:
        got = ImageFont.load_default()
    _FONT_CACHE[key] = got
    return got


def _kinetic_font(w: int, n: int) -> ImageFont.ImageFont:
    n = max(1, n)
    return _font(max(16, min(40, int((w * 0.76) / n))))


_ALPHA_FLOOR_LUT = bytes([1] + list(range(1, 256)))
_HIT_MASK: dict[int, bytes] = {}


def _rgba_to_bgra(img: Image.Image) -> tuple[bytes, bytes]:
    """直接 RGBA → 预乘 BGRA。全部走 PIL 通道运算，比逐像素 Python 循环快约 10 倍。"""
    w, h = img.size
    r, g, b, a = img.split()
    # 分层窗 alpha=0 的像素系统会点穿到后面的程序；整块区域至少留 1，肉眼看不出。
    a = a.point(_ALPHA_FLOOR_LUT)
    pm = Image.merge(
        "RGBA",
        (ImageChops.multiply(r, a), ImageChops.multiply(g, a), ImageChops.multiply(b, a), a),
    )
    n = w * h
    mask = _HIT_MASK.get(n)
    if mask is None:
        mask = b"\xff" * n
        if len(_HIT_MASK) > 4:
            _HIT_MASK.clear()
        _HIT_MASK[n] = mask
    return pm.tobytes("raw", "BGRA"), mask


class WorkTimer(WorklogDialogMixin, ScheduleDialogMixin, UpdateDialogMixin):
    def __init__(self) -> None:
        try:
            # Per-monitor v2，避免窗口画在 A、点击命中在 B
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        if not single_instance.claim():
            os._exit(0)  # 已有实例在跑：唤起窗口并提示后退出
        suofen.ensure_loading()
        updater.cleanup_update_artifacts()
        threading.Thread(
            target=updater.cleanup_legacy_install,
            args=(_arg_path("--legacy-cleanup"),),
            daemon=True,
        ).start()
        self.cfg = store.load_config()
        try:
            if desktop_shortcut.ensure_all(self.cfg):
                store.save_config(self.cfg)
        except Exception as e:  # noqa: BLE001
            store.log_exception("desktop-shortcut", e)
        schedules.ensure_fields(self.cfg)
        memos.ensure_fields(self.cfg)
        worklog.ensure_fields(self.cfg)
        activity.ensure_fields(self.cfg)
        # 下架的皮（自适应/天色）回落到淡影
        fixed_theme = themes.normalize_id(self.cfg.get("theme"))
        if fixed_theme != self.cfg.get("theme"):
            self.cfg["theme"] = fixed_theme
            store.save_config(self.cfg)
        if schedules.sync_festival(self.cfg):
            store.save_config(self.cfg)
        try:
            attachments.gc(self.cfg)
        except Exception as e:  # noqa: BLE001
            store.log_exception("attachments-gc", e)
        self.running = True
        self._menu_pos: tuple[int, int] | None = None
        self._need_dialog = False
        self._need_worklog = False
        self._need_schedule_list = False
        self._schedule_list_open = False
        self._need_close_schedule_list = False
        self._tk: tk.Tk | None = None
        self._update_available = False
        self._update_info: updater.ReleaseInfo | None = None
        self._update_prompted = False
        self._update_dialog_open = False
        self._last_pin_rotate = 0.0
        self._last_key = ""
        self._present_hz = 0
        self._tally_at = 0.0
        self._tally_speed_at = 0.0
        self._tally_parts: tuple | None = None
        self._tally_speed: dict | None = None
        self._fest_day = datetime.now().strftime("%Y-%m-%d")
        self._wall_at = datetime.now()
        self._mono_at = time.monotonic()
        self._hide_key_held = False
        self._hide_key_chord = False
        self._hide_key_down_at = 0.0
        self._hide_key_input_tick: int | None = None
        self._done_seen: dict[str, bool] = {}
        self._celebrate_start = 0.0
        self._celebrate_until = 0.0
        self._thunder_hits: list[tuple[float, int, int, float, int]] = []  # start,x,y,power,quote_idx
        self._thunder_quote_step = 0
        self._ink_hits: list[tuple[float, int, int, float]] = []
        self._flip_prev_digits = ""
        self._flip_anims: dict[int, tuple[float, str, str]] = {}
        self._flip_hit_rects: list[tuple[int, int, int, int, int]] = []
        self._flip_last_big = ""
        self._neon_ammo = ornaments.create_neon_ammo()
        self._neon_planets = ornaments.create_neon_planets()
        self._mouse_lx = -1
        self._mouse_ly = -1
        self._loop_beat = time.monotonic()
        self._painting = False
        self._was_asleep = False
        self._wake_checked = 0.0
        self._ghost_ptr: tuple[int, int] | None = None
        self._ghost_q: tuple[int, int] | None = None
        self._meow = meow.Troupe()
        self._worklog_at = 0.0
        self._worklog_dirty = False
        self._worklog_save_at = 0.0
        self._burst: dict | None = None
        self._work_input_second: datetime | None = None
        self._last_input_seen = worklog.last_input_tick()
        self._activity_dirty = False
        self._ui_prewarmed = False
        self._worklog_ui: dict | None = None
        self._worklog_dock = None
        self._worklog_docked = False
        self._schedule_ui: dict | None = None
        self._check_clock_on_boot()

        w, h = self._load_size()
        self._win_w, self._win_h = w, h
        ft, fb, fs = ornaments.layout_for(w, h)

        self.win = layered_win.LayeredPetWindow(w, h, "下班倒计时")
        self._trail: cursor_trail.Trail | None = None
        self._trail_failed = False
        self.win.set_left_click_handler(self._on_click)
        self.win.set_mouse_move_handler(self._on_mouse_move)
        self.win.set_mouse_leave_handler(self._on_mouse_leave)
        self.win.set_right_click_handler(self._request_menu)
        self.win.set_request_show_handler(self._on_request_show)
        self.win.set_geometry_handler(self._follow_worklog_dock)
        self._esc_hidden = False

        area = layered_win.work_area()
        x = self.cfg.get("win_x")
        y = self.cfg.get("win_y")
        if not isinstance(x, int) or not isinstance(y, int):
            x = int(area.right - w - 24)
            y = int(area.top + 24)
        x, y = layered_win.clamp_pos(int(x), int(y), w, h)
        self.win.move(x, y)

        self._font_title = _font(ft)
        self._font_big = _font(fb)
        self._font_sub = _font(fs)
        self._kinetic: kinetic.Show | None = None
        self._hydrate_showing = False
        self._hydrate_waiting = bool(hydrate.read(self.cfg).get("pending")) and hydrate.enabled(self.cfg)
        self._hydrate_paused_at: datetime | None = None
        self._card_modal_abort = False
        self.win.blocked_live = self._card_frame
        self.win.note_beat = self._note_beat
        self.win.dialog_hidden = self._games_hide_state
        self.win.modal_should_stop = lambda: (not self.running) or bool(self._card_modal_abort)
        self.win.set_live_timer(self._on_live_timer)
        self.win.set_raw_input_handler(self._on_raw_input)
        # 来和走始终看真实输入；次数统计开关只决定是否保存次数。
        self.win.listen_raw_input(True)
        self._font_kinetic = self._font_big
        self._surface = "dark"
        self._force_surface_sample = True
        self._wallpaper_token = backdrop.wallpaper_token()
        self._wallpaper_checked = 0.0
        self._surface_hot_until = 0.0
        self._last_surface_sample = 0.0
        self._sampler = backdrop.AsyncSampler()
        self._last_luma = None
        self._env_rgb: tuple[int, int, int] | None = None
        self._env_q: tuple[int, int, int] | None = None
        mode = str(self.cfg.get("display_mode") or "hms")
        self.cfg["display_mode"] = mode if mode in flex_time.DISPLAY_MODES else "hms"
        tid = str(self.cfg.get("theme") or themes.DEFAULT_THEME_ID)
        self.cfg["theme"] = tid
        try:
            ssl.create_default_context()
        except Exception:
            pass
        key_hide.ensure_fields(self.cfg)
        hydrate.ensure_fields(self.cfg)
        self.cfg["remember_offwork"] = bool(self.cfg.get("remember_offwork", True))
        self.cfg["auto_start"] = bool(self.cfg.get("auto_start"))
        try:
            autostart.sync(self.cfg["auto_start"])
        except OSError:
            pass
        themes.refresh_async(self.cfg)
        self._silent_check_update()

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

    def _wall_plausible(self, dt: datetime) -> bool:
        return 2024 <= dt.year <= 2035

    def _parse_last_wall(self) -> datetime | None:
        raw = str(self.cfg.get("last_wall") or "").strip()
        if not raw:
            return None
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None

    def _touch_last_wall(self, now: datetime | None = None) -> None:
        now = now or datetime.now()
        if not self._wall_plausible(now):
            return
        self.cfg["last_wall"] = now.strftime("%Y-%m-%dT%H:%M:%S")

    def _session_stale(self) -> bool:
        return bool(self.cfg.get("session_stale"))

    def _mark_session_stale(self, why: str) -> None:
        if self.cfg.get("session_stale"):
            self._last_key = ""
            return
        self.cfg["session_stale"] = True
        self._touch_last_wall()
        store.save_config(self.cfg)
        self._last_key = ""
        store.append_log(f"session_stale: {why}")

    def _clear_session_stale(self) -> None:
        self.cfg["session_stale"] = False
        self._touch_last_wall()

    def _check_clock_on_boot(self) -> None:
        now = datetime.now()
        prev = self._parse_last_wall()
        if prev is not None and now < prev - timedelta(minutes=5):
            self._mark_session_stale("clock went backward on boot")
        self._touch_last_wall(now)
        self._wall_at = now
        self._mono_at = time.monotonic()

    def _poll_clock_skew(self) -> None:
        now = datetime.now()
        mono = time.monotonic()
        wall_delta = (now - self._wall_at).total_seconds()
        mono_delta = mono - self._mono_at
        self._wall_at = now
        self._mono_at = mono
        if abs(wall_delta - mono_delta) >= 300:
            self._mark_session_stale(
                f"clock skew wall={wall_delta:.0f}s mono={mono_delta:.0f}s"
            )
        self._touch_last_wall(now)

    def _has_start(self) -> bool:
        if str(self.cfg.get("start_date") or "") != self._today():
            return False
        h, m = self.cfg.get("start_h"), self.cfg.get("start_m")
        return isinstance(h, int) and isinstance(m, int)

    def _start_hm(self) -> tuple[int, int] | None:
        if not self._has_start():
            return None
        return int(self.cfg["start_h"]), int(self.cfg["start_m"])

    def _time_mode(self) -> str:
        mode = str(self.cfg.get("time_mode") or "flex")
        return mode if mode in ("flex", "direct") else "flex"

    def _remember_offwork(self) -> bool:
        return bool(self.cfg.get("remember_offwork", True))

    def _has_target(self) -> bool:
        if self._session_stale():
            return False
        dated = str(self.cfg.get("start_date") or "") == self._today()
        if self._time_mode() == "direct":
            has_off = isinstance(self.cfg.get("off_h"), int) and isinstance(self.cfg.get("off_m"), int)
            return has_off and (dated or self._remember_offwork())
        return dated and self._has_start()

    def _off_hm(self) -> tuple[int, int] | None:
        if not self._has_target():
            return None
        if self._time_mode() == "direct":
            return int(self.cfg["off_h"]), int(self.cfg["off_m"])
        start = self._start_hm()
        if start is None:
            return None
        return flex_time.offwork_hm(*start)

    def _display_mode(self) -> str:
        mode = str(self.cfg.get("display_mode") or "hms")
        return mode if mode in flex_time.DISPLAY_MODES else "hms"

    def _set_display_mode(self, mode: str) -> None:
        if mode not in flex_time.DISPLAY_MODES:
            return
        self.cfg["display_mode"] = mode
        store.save_config(self.cfg)
        self._last_key = ""

    def _cycle_display(self) -> None:
        self._set_display_mode(flex_time.next_display_mode(self._display_mode()))

    def _theme(self) -> themes.Theme:
        return themes.get_theme(str(self.cfg.get("theme") or ""))

    def _set_theme(self, theme_id: str) -> None:
        if theme_id not in themes.theme_map():
            return
        self.cfg["theme"] = theme_id
        # 用户手动选过皮，过季就不再替他还原
        self.cfg.pop("midautumn_theme_auto", None)
        self.cfg.pop("nationalday_theme_auto", None)
        store.save_config(self.cfg)
        self._last_key = ""
        self._force_surface_sample = True

    def _stop_kinetic(self) -> None:
        if self._kinetic is not None:
            self._kinetic.skip()
            self._kinetic = None
        self._hydrate_showing = False
        self._last_key = ""

    def _start_kinetic(self, phrases: tuple[str, ...] | None = None) -> None:
        phrases = phrases or kinetic.MIDAUTUMN_PHRASES
        self._kinetic = kinetic.Show(phrases, time.monotonic())
        self._hydrate_showing = phrases == kinetic.HYDRATE_PHRASES
        self._font_kinetic = _kinetic_font(self._win_w, max(len(p) for p in phrases))
        self._last_key = ""

    def _try_start_fest_kinetic(
        self,
        now: float,
        *,
        past: bool,
        sid: str,
        theme_id: str,
        done_key: str,
        phrases: tuple[str, ...],
    ) -> bool:
        if past:
            return False
        if kinetic.playing(self._kinetic, now):
            return False
        if self._theme().id != theme_id:
            return False
        item = schedules.find_schedule(self.cfg, sid)
        if item is None:
            return False
        _, done = schedules.schedule_remaining(item, datetime.now())
        if not done:
            if self.cfg.get(done_key):
                self.cfg[done_key] = False
                store.save_config(self.cfg)
            return False
        if self.cfg.get(done_key):
            return False
        if self._esc_hidden or self._update_dialog_open or self._need_dialog:
            return False
        if self.win.dragging or self.win.resizing:
            return False
        self.cfg[done_key] = True
        if sid in (self.cfg.get("pin_order") or []):
            self.cfg["active_pin_id"] = sid
        store.save_config(self.cfg)
        self._start_kinetic(phrases)
        return True

    def _check_celebrate(self, aid: str, title: str, total: int, done: bool, idle: bool, phase: float) -> None:
        """当前显示的项从「未到点」翻到「到点」的那一刻：纸屑 + 一句字幕。

        只认运行中发生的翻转（启动即已到点、切到早就到点的项都不算），且到点不超过 2 分钟。
        """
        if idle:
            return
        prev = self._done_seen.get(aid)
        self._done_seen[aid] = done
        if prev is not True and prev is not False:
            return
        if prev or not done or total > 120:
            return
        if self._esc_hidden or self._update_dialog_open or self._need_dialog or self._schedule_list_open:
            return
        if self.win.dragging or self.win.resizing:
            return
        self._celebrate_start = phase
        self._celebrate_until = phase + ornaments.CONFETTI_SEC
        if kinetic.playing(self._kinetic, phase) or self._hydrate_waiting:
            return
        if aid == schedules.OFFWORK_ID:
            self._start_kinetic(kinetic.OFFWORK_PHRASES)
        elif not festival.is_locked(aid):
            item = schedules.find_schedule(self.cfg, aid)
            raw = str(item.get("title") or "").strip() if item else title
            if 0 < len(raw) <= 6:
                self._start_kinetic((raw,))

    def _tick_kinetic(self, now: float) -> None:
        if self._hydrate_waiting or kinetic.playing(self._kinetic, now):
            return
        wall = datetime.now()
        if self._try_start_fest_kinetic(
            now,
            past=festival.midautumn_past_season(wall),
            sid=festival.MIDAUTUMN_ID,
            theme_id=festival.MIDAUTUMN_THEME_ID,
            done_key="midautumn_kinetic_done",
            phrases=kinetic.festival_show_phrases(kinetic.MIDAUTUMN_LEAD, kinetic.MIDAUTUMN_PHRASES),
        ):
            return
        self._try_start_fest_kinetic(
            now,
            past=festival.national_past_season(wall),
            sid=festival.NATIONAL_ID,
            theme_id=festival.NATIONAL_THEME_ID,
            done_key="nationalday_kinetic_done",
            phrases=kinetic.festival_show_phrases(kinetic.NATIONAL_LEAD, kinetic.NATIONAL_PHRASES),
        )

    def _load_size(self) -> tuple[int, int]:
        w, h = self.cfg.get("win_w"), self.cfg.get("win_h")
        if not isinstance(w, int) or not isinstance(h, int):
            legacy = str(self.cfg.get("win_size") or "")
            w, h = _LEGACY_SIZES.get(legacy, (248, 92))
        w, h = layered_win.snap_size(int(w), int(h))
        self.cfg["win_w"], self.cfg["win_h"] = w, h
        return w, h

    def _sync_layout_from_window(self) -> None:
        w, h = self.win.width, self.win.height
        if w == self._win_w and h == self._win_h:
            return
        self._win_w, self._win_h = w, h
        ft, fb, fs = ornaments.layout_for(w, h)
        self._font_title = _font(ft)
        self._font_big = _font(fb)
        self._font_sub = _font(fs)
        if self._kinetic is not None:
            self._font_kinetic = _kinetic_font(w, len(self._kinetic.text))
        self._last_key = ""

    def _persist_size(self) -> None:
        if self.cfg.get("win_w") == self._win_w and self.cfg.get("win_h") == self._win_h:
            return
        self.cfg["win_w"] = self._win_w
        self.cfg["win_h"] = self._win_h
        store.save_config(self.cfg)

    def _refresh_surface(self, *, force: bool = False) -> None:
        """窗周+窗下采样；最小化/切前台会强制连采。"""
        now = time.monotonic()
        theme = self._theme()
        if not theme.adaptive and not ornaments.uses_env(theme.kind):
            # 固定深底、不吃环境色的皮肤，截屏取色白忙
            return
        if now - self._wallpaper_checked >= 1.0:
            self._wallpaper_checked = now
            token = backdrop.wallpaper_token()
            if token != self._wallpaper_token:
                self._wallpaper_token = token
                force = True
        if force or self._force_surface_sample:
            self._force_surface_sample = False
            self._surface_hot_until = now + 0.45
        hot = now < self._surface_hot_until
        # 节电时平常一秒采四次就够；刚挪过窗、换过前台（hot）照样连采。
        gap = 0.25 if power_save.saving() else 0.08
        if force or hot or now - self._last_surface_sample >= gap:
            self._last_surface_sample = now
            self._sampler.request(self.win.x, self.win.y, self._win_w, self._win_h)
        got = self._sampler.take()
        if got is None:
            return
        luma, rgb = got
        q = (rgb[0] // 20, rgb[1] // 20, rgb[2] // 20)
        if q != self._env_q:
            self._env_q = q
            self._env_rgb = rgb
            self._last_key = ""
        if not theme.adaptive:
            return
        prev = self._last_luma
        self._last_luma = luma
        jumped = prev is not None and abs(luma - prev) >= 24
        if jumped:
            self._surface_hot_until = now + 0.45
        surface = backdrop.classify_surface(luma, self._surface, soft=jumped)
        if surface != self._surface:
            self._surface = surface
            self._last_key = ""

    def _refresh_themes(self) -> None:
        ok = themes.refresh_from_repo(self.cfg)
        self._last_key = ""
        root = self._tk_root()
        if ok:
            names = "、".join(t.name for t in themes.list_themes())
            messagebox.showinfo("外观", f"已同步在线样式。\n当前：{names}", parent=root)
            return
        messagebox.showwarning(
            "外观",
            "拉不到在线样式，继续用本机缓存/内置。\n改仓库里的 themes.json 后再点「刷新在线外观」。",
            parent=root,
        )

    def _silent_check_update(self) -> None:
        def _run() -> None:
            try:
                # 静默检查有本地节流，6 小时内不重复打网；手动检查不受限。
                kind, info = updater.check_update(self.cfg, force=False)
                if kind == "available" and info is not None:
                    self._update_info = info
                    self._update_available = True
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True, name="silent-update").start()

    def _maybe_show_whats_new(self) -> None:
        pending = store.consume_pending_whats_new()
        last = str(self.cfg.get("last_run_version") or "").strip()
        from_ver = pending or last
        sections: list[tuple[str, str]] = []
        try:
            if from_ver and updater.is_newer(APP_VERSION, from_ver):
                sections = changelog.notes_for_popup(from_ver, APP_VERSION)
            elif not last:
                # 手动换 exe / 本机从没记过版本：只展示当前这一版，避免把历史全倒出来
                sections = [
                    (v, b)
                    for v, b in changelog.parse_notes(changelog.load_markdown())
                    if v == APP_VERSION
                ]
        except Exception as e:  # noqa: BLE001
            store.log_exception("changelog", e)
        if str(self.cfg.get("last_run_version") or "") != APP_VERSION:
            self.cfg["last_run_version"] = APP_VERSION
            store.save_config(self.cfg, now=True)
        if sections:
            self._show_whats_new(sections, from_ver=from_ver if from_ver else "")

    def _show_whats_new(self, sections: list[tuple[str, str]], *, from_ver: str = "") -> None:
        near = self._dialog_near()
        card_w = 420
        dlg = _card_dialog(self._tk_root(), near=near, width=card_w, height=200)
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(8, 14))
        _card_btn(bar, "知道了", dlg.destroy, accent=True).pack(side="left", padx=18)
        # 这弹窗是重启后自己冒出来的，标题得先说清「刚才那次更新成了」
        tk.Label(
            dlg,
            text="更新好了",
            fg=_CARD_FG,
            bg=_CARD_BG,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(14, 2), padx=18, anchor="w")
        tk.Label(
            dlg,
            text=(f"从 {from_ver} 升到 {APP_VERSION}，这次改了这些" if from_ver else f"现在是 {APP_VERSION}，这次改了这些"),
            fg=_CARD_MUTED,
            bg=_CARD_BG,
            font=("Microsoft YaHei UI", 9),
        ).pack(padx=18, anchor="w")
        try:
            r = layered_win.monitor_work_at(self.win.x + self._win_w // 2, self.win.y + self._win_h // 2)
            work_h = int(r.bottom) - int(r.top)
        except Exception:
            work_h = 900
        # 标题+副标题+底栏约占 110px；正文最多吃掉剩余工作区，短文不撑空、不加滚动条
        max_px = max(120, min(480, work_h - 200))
        wrap_px = card_w - 36  # 与 outer padx=18*2 对齐
        _pack_full_text(dlg, sections, wrap_px=wrap_px, max_px=max_px)
        _fit_card(dlg, min_w=card_w, min_h=120, near=near)
        _run_card_modal(dlg, self.win)

    def _on_click(self, lx: int, ly: int) -> None:
        if self._esc_hidden:
            return
        if self._hydrate_waiting:
            self._ack_hydrate()
            return
        if self._kinetic is not None:
            self._kinetic.skip()
            self._kinetic = None
            self._hydrate_showing = False
            self._last_key = ""
            return
        self._maybe_skin_interact(lx, ly)
        schedules.ensure_fields(self.cfg)
        aid = schedules.active_id(self.cfg)
        # 无优先项或当前是下班：未设下班 → 设置；优先列表被清空但已有下班 → 打开日程列表重设优先
        if aid is None or aid == schedules.OFFWORK_ID:
            if not self._has_target():
                self._need_dialog = True
                return
            if aid is None:
                self._need_schedule_list = True
                return
        pins = self.cfg.get("pin_order") or []
        if isinstance(pins, list) and len(pins) >= 2:
            if schedules.cycle_active(self.cfg):
                store.save_config(self.cfg)
                self._last_key = ""
                self._last_pin_rotate = time.monotonic()

    def _prune_thunder_hits(self, now: float) -> None:
        dur = ornaments.BITE_SEC
        self._thunder_hits = [(s, x, y, p, q) for s, x, y, p, q in self._thunder_hits if now - s < dur]

    def _prune_ink_hits(self, now: float) -> None:
        self._ink_hits = [(s, x, y, p) for s, x, y, p in self._ink_hits if now - s < ornaments.INK_CLICK_SEC]

    def _neon_needs_frames(self, now: float) -> bool:
        if any(p < 0.98 for p in self._neon_ammo.present):
            return True
        if bool(self._neon_ammo.shots):
            return True
        return ornaments.neon_planets_animating(self._neon_planets, now)

    def _on_mouse_move(self, lx: int, ly: int) -> None:
        if self._esc_hidden:
            return
        kind = self._theme().kind
        if kind == "ghost":
            q = (lx // 16, ly // 16)
            if q != self._ghost_q:
                self._ghost_q = q
                self._ghost_ptr = (lx, ly)
                self._last_key = ""
        elif self._ghost_ptr is not None:
            self._ghost_ptr = None
            self._ghost_q = None
            self._last_key = ""
        if kind != "neonflow":
            return
        if abs(lx - self._mouse_lx) > 2 or abs(ly - self._mouse_ly) > 2:
            self._mouse_lx, self._mouse_ly = lx, ly
            self._last_key = ""

    def _on_mouse_leave(self) -> None:
        if self._ghost_ptr is None and self._ghost_q is None:
            return
        self._ghost_ptr = None
        self._ghost_q = None
        self._last_key = ""

    def _games_hide_state(self) -> bool:
        """右键弹窗跟卡片用同一套隐藏键。"""
        self._poll_key_hide()
        return bool(self._esc_hidden)

    def _note_work_input(self, when: datetime, kind: str | None = None) -> None:
        if not worklog.tracking_enabled(self.cfg):
            self._burst = None
            return
        second = when.replace(microsecond=0)
        if second == self._work_input_second:
            if worklog.note_kind(self.cfg, when, kind):
                self._worklog_dirty = True
            return
        self._work_input_second = second
        self._burst, changed = worklog.note_input(
            self.cfg, self._burst, when, target_hm=self._off_hm(), kind=kind,
        )
        if changed:
            self._worklog_dirty = True

    def _on_raw_input(self, buf: bytes) -> None:
        activity.track_key(buf)
        kind = activity.parse_raw(buf)
        # 没开键鼠统计时不必每帧解析位移，减轻 Raw Input 洪峰。
        delta = activity.mouse_delta(buf) if activity.enabled(self.cfg) else None
        evidence = activity.physical_input(buf)
        if delta is None and kind is None and evidence is None:
            return
        now = datetime.now()
        if evidence is not None:
            # 第一条真实输入可能正是唤醒电脑的动作。先清掉睡前候选，再立即记它，
            # 不让待机后的安静窗口拖慢真实到岗时间。
            phase = "ok"
            if time.monotonic() - self._worklog_at >= 1:
                phase = worklog.observe_clock(now)
            if phase == "wake":
                self._burst = None
                snap = worklog.last_input_snapshot()
                self._last_input_seen = snap[0] if snap is not None else None
            self._note_work_input(now, evidence)
        if delta is not None and activity.add_travel(self.cfg, delta[0], delta[1], now):
            self._activity_dirty = True
        key = activity.key_id(buf) if kind == "key" else None
        if kind == "key" and evidence is None:
            # 输入法、SendInput 没有硬件设备，热力图上会凭空多出空格、回车。
            kind = None
            key = None
        if kind and activity.note(self.cfg, kind, now, key=key):
            self._activity_dirty = True

    def _maybe_skin_interact(self, lx: int, ly: int) -> None:
        """特效皮点击互动：霹雳狂潮落雷 / 墨水落墨 / 霓虹射击 / 翻牌拨动 / 仪仗队踢正步。"""
        kind = self._theme().kind
        now = time.monotonic()
        if themes.use_flip_display(kind, self._flip_last_big, self.cfg, h=self._win_h):
            import fx

            idx = fx.flip_digit_index_at(self._flip_hit_rects, int(lx), int(ly))
            if idx is not None:
                digits = fx.flip_digits_only(self._flip_last_big)
                fx.flip_tap_digit(self._flip_anims, digits, idx, now)
                self._last_key = ""
                if kind not in themes.INTERACTIVE_SKINS:
                    return
        if kind == "thunder":
            hits, nxt = ornaments.register_thunder_hit(
                self._thunder_hits,
                now,
                int(lx),
                int(ly),
                self._thunder_quote_step,
                quote=skin_settings.thunder_quote(self.cfg),
            )
            self._thunder_hits = hits
            if nxt is not None:
                self._thunder_quote_step = nxt
        elif kind == "inkpulse":
            self._ink_hits = ornaments.register_ink_hit(self._ink_hits, now, int(lx), int(ly))
        elif kind == meow.KIND:
            self._meow.poke(now)
            self._last_key = ""
        elif kind == suofen.KIND:
            suofen.poke(now)
            self._last_key = ""
        elif kind == ticker.KIND:
            ticker.poke(now)
            self._last_key = ""
        elif kind == "neonflow":
            rr = min(self._theme().radius, max(8, self._win_h // 5))
            ornaments.neon_try_fire(
                self._neon_ammo,
                now,
                float(lx - 4),
                float(ly - 4),
                bw=max(1, self._win_w - 9),
                bh=max(1, self._win_h - 9),
                radius=rr,
                phase=now,
                light=(self._surface == "light"),
            )
            self._last_key = ""

    def _key_hide_on(self) -> bool:
        return key_hide.enabled(self.cfg)

    def _set_key_hide(self, on: bool) -> None:
        key_hide.set_enabled(self.cfg, on)
        store.save_config(self.cfg)
        if not on and self._esc_hidden:
            self._show_after_esc()

    def _hydrate_on(self) -> bool:
        return hydrate.enabled(self.cfg)

    def _trail_on(self) -> bool:
        return cursor_trail.enabled(self.cfg)

    def _set_trail(self, on: bool) -> None:
        cursor_trail.set_enabled(self.cfg, on)
        store.save_config(self.cfg)
        if not on and self._trail is not None:
            self._trail.hide()

    def _set_worklog_tracking(self, on: bool) -> None:
        worklog.set_tracking_enabled(self.cfg, on)
        self._burst = None
        self._work_input_second = None
        snap = worklog.last_input_snapshot()
        self._last_input_seen = snap[0] if snap is not None else None
        store.save_config(self.cfg)

    def _set_hydrate(self, on: bool) -> None:
        hydrate.set_enabled(self.cfg, on)
        self._hydrate_paused_at = None
        if not on:
            self._hydrate_waiting = False
            if self._hydrate_showing:
                self._stop_kinetic()
        store.save_config(self.cfg)

    def _hydrate_after_offwork(self, now: datetime | None = None) -> bool:
        hm = self._off_hm()
        if hm is None:
            return False
        now = now or datetime.now()
        _, done = flex_time.remaining_parts(flex_time.remaining_to(now, hm[0], hm[1]))
        return done

    def _tick_hydrate(self, now_m: float) -> None:
        if not hydrate.enabled(self.cfg):
            self._hydrate_waiting = False
            self._hydrate_paused_at = None
            return
        now = datetime.now()
        if self._hydrate_after_offwork(now):
            if self._hydrate_waiting or hydrate.read(self.cfg)["pending"]:
                self._hydrate_waiting = False
                self._hydrate_paused_at = None
                hydrate.decide(self.cfg, now, after_offwork=True)
                store.save_config(self.cfg)
            return
        if hydrate.is_stale(self.cfg, now):
            self._hydrate_waiting = False
            self._hydrate_paused_at = None
            hydrate.decide(self.cfg, now)
            store.save_config(self.cfg)
            return
        if self._hydrate_waiting:
            return
        if (
            kinetic.playing(self._kinetic, now_m)
            or self._esc_hidden
            or self._update_dialog_open
            or self._need_dialog
            or self._schedule_list_open
            or self.win.dragging
            or self.win.resizing
        ):
            return
        idle = worklog.idle_seconds()
        if idle >= worklog.IDLE_LIMIT_SEC:
            if self._hydrate_paused_at is None:
                self._hydrate_paused_at = now
            return
        if self._hydrate_paused_at is not None:
            hydrate.shift_anchor(self.cfg, now - self._hydrate_paused_at)
            self._hydrate_paused_at = None
            store.save_config(self.cfg)
        if hydrate.decide(self.cfg, now) != "fire":
            return
        hydrate.arm(self.cfg)
        store.save_config(self.cfg)
        self._hydrate_waiting = True
        if self._kinetic is not None:
            self._kinetic.skip()
            self._kinetic = None
        self._last_key = ""

    def _ack_hydrate(self) -> None:
        self._hydrate_waiting = False
        self._hydrate_showing = False
        if self._kinetic is not None:
            self._kinetic.skip()
            self._kinetic = None
        hydrate.reset_anchor(self.cfg, datetime.now())
        store.save_config(self.cfg)
        if self._theme().kind == meow.KIND:
            self._meow.cheer(time.monotonic())
        self._last_key = ""

    def _auto_start_on(self) -> bool:
        return bool(self.cfg.get("auto_start"))

    def _confirm_uninstall(self) -> None:
        if not getattr(sys, "frozen", False):
            try:
                messagebox.showinfo(
                    "卸载本程序",
                    "开发模式请手动删除源码目录与 %AppData%\\Roaming\\WorkTimer。",
                    parent=self._tk_root(),
                )
            except Exception:
                pass
            return
        try:
            ok = messagebox.askyesno(
                "卸载本程序",
                "\n".join(uninstall.summary_lines()),
                parent=self._tk_root(),
                icon="warning",
            )
        except Exception:
            return
        if not ok:
            return
        self.running = False
        store.flush_pending(force=True)
        try:
            uninstall.request_and_exit()
        except Exception as e:  # noqa: BLE001
            try:
                messagebox.showerror("卸载本程序", str(e), parent=self._tk_root())
            except Exception:
                pass

    def _create_desktop_shortcut(self) -> None:
        ok, msg = desktop_shortcut.create_desktop_shortcut(self.cfg)
        if ok:
            store.save_config(self.cfg)
        try:
            if ok:
                messagebox.showinfo("桌面快捷方式", msg, parent=self._tk_root())
            else:
                messagebox.showwarning("桌面快捷方式", msg, parent=self._tk_root())
        except Exception:
            pass

    def _set_auto_start(self, on: bool) -> None:
        on = bool(on)
        try:
            autostart.sync(on)
        except OSError as e:
            try:
                messagebox.showwarning("开机自启动", f"设置失败：{e}", parent=self._tk_root())
            except Exception:
                pass
            return
        self.cfg["auto_start"] = on
        store.save_config(self.cfg)

    def _tally_for_paint(self) -> tuple | None:
        """顶部三项。次数变了就换，速度最多一秒换一次，避免鼠标一动就重画整张卡片。"""
        if not activity.show_on_card(self.cfg):
            return None
        now = time.monotonic()
        if now - self._tally_at >= 0.25:
            self._tally_at = now
            speed = self._tally_speed
            if speed is None or now - self._tally_speed_at >= 1.0:
                self._tally_speed_at = now
                if activity.settle(self.cfg, datetime.now()):
                    self._activity_dirty = True
                speed = activity.speed_snapshot(self.cfg, datetime.now())
                self._tally_speed = speed
            parts = activity.card_parts(self.cfg, datetime.now(), speed=speed)
            if parts != self._tally_parts:
                self._tally_parts = parts
        return self._tally_parts

    def _show_after_esc(self) -> None:
        self.win.show()
        self.win.keep_topmost()
        self._esc_hidden = False
        self._last_key = ""
        self._force_surface_sample = True
        # 隐藏久了分层贴条可能被系统弄没；强制走完整 show，不能只 follow。
        dock = getattr(self, "_worklog_dock", None)
        if getattr(self, "_worklog_docked", False) and dock is not None:
            dock._shown = False
        self._place_worklog_dock()

    def _on_request_show(self) -> None:
        """快捷方式/再次启动唤起：同步清掉 Ctrl 隐藏状态，避免窗可见但主循环仍挂起。"""
        if self._esc_hidden:
            self._show_after_esc()
        else:
            self.win.show()
            self.win.keep_topmost()
            self._last_key = ""
            self._force_surface_sample = True
            self._place_worklog_dock()

    def _hide_key_companions(self) -> None:
        """隐藏键只收「正开着」的卡片和贴条。

        预热后停在屏幕外的账本/日程不要再标 _key_hidden：否则再打开时
        _show_open_card 会按屏幕外的 _hide_xy 把窗拖回去，看起来像打不开。
        """
        dlg = getattr(self.win, "_open_card", None) if self.win is not None else None
        if dlg is not None:
            _hide_open_card(dlg)
        ui = getattr(self, "_worklog_ui", None)
        other = ui.get("dlg") if ui else None
        if (
            other is not None
            and other is not dlg
            and ui is not None
            and ui.get("live")
            and not ui.get("minimized")
        ):
            _hide_open_card(other)
        sched = getattr(self, "_schedule_ui", None)
        sdlg = sched.get("dlg") if sched else None
        if (
            sdlg is not None
            and sdlg is not dlg
            and sdlg is not other
            and getattr(self, "_schedule_list_open", False)
        ):
            _hide_open_card(sdlg)
        dock = getattr(self, "_worklog_dock", None)
        if dock is not None:
            dock.hide()

    def _toggle_key_hide(self) -> None:
        if not self._key_hide_on() and not self._esc_hidden:
            return
        if self._esc_hidden:
            self._show_after_esc()
            return
        # 账本模态还在转时只藏窗、不退循环 → 主循环回不去，退出/再开账本都会假死。
        # 隐藏前先最小化账本（只记账、先不亮贴条），显示后再 _place 贴条。
        ui = getattr(self, "_worklog_ui", None)
        if ui is not None and ui.get("live") and not ui.get("minimized"):
            try:
                self._minimize_worklog(ui, place_dock=False)
            except Exception:
                ui["stop"] = True
        # 日程列表同样：藏起来却不退循环，再开会卡在看不见的模态里。
        if getattr(self, "_schedule_list_open", False):
            self._need_close_schedule_list = True
        self.win.dismiss_popup()
        self._hide_key_companions()
        self.win.hide()
        self._esc_hidden = True

    def _request_quit(self) -> None:
        """退出必须能打断卡片模态；只改 running 的话会卡在 _run_card_modal 里。"""
        self.running = False
        self._card_modal_abort = True
        ui = getattr(self, "_worklog_ui", None)
        if ui is not None:
            ui["stop"] = True
        dlg = getattr(self.win, "_open_card", None) if self.win is not None else None
        if dlg is not None:
            try:
                if dlg.winfo_exists():
                    dlg.destroy()
            except tk.TclError:
                pass

    def _poll_key_hide(self) -> None:
        self._poll_clock_skew()
        if not self._key_hide_on() and not self._esc_hidden:
            self._hide_key_held = False
            return
        hide_vk = key_hide.vk(self.cfg)
        down = bool(layered_win.user32.GetAsyncKeyState(hide_vk) & 0x8000)
        # 修饰键单按才隐藏：按住期间系统「最后输入时刻」变了，就是又按了别的键/动了鼠标（Ctrl+C 等组合）。
        # 不逐个扫全键盘 GetAsyncKeyState，那是键盘记录器的典型行为，杀软会盯。
        if down and not self._hide_key_held:
            self._hide_key_chord = False
            self._hide_key_down_at = time.monotonic()
            self._hide_key_input_tick = worklog.last_input_tick() if key_hide.is_modifier(hide_vk) else None
            # 右键菜单自己占着消息循环，不先关掉会留在屏幕上
            if self._key_hide_on() or self._esc_hidden:
                self.win.dismiss_popup()
        elif down and not self._hide_key_chord and self._hide_key_input_tick is not None:
            tick = worklog.last_input_tick()
            if tick is not None and tick != self._hide_key_input_tick:
                self._hide_key_chord = True
        if (not down) and self._hide_key_held:
            held = time.monotonic() - self._hide_key_down_at
            if (
                (self._key_hide_on() or self._esc_hidden)
                and not self._hide_key_chord
                and 0.04 <= held <= 0.55
            ):
                self._toggle_key_hide()
        self._hide_key_held = down

    def _request_menu(self, sx: int, sy: int) -> None:
        if self._esc_hidden:
            return
        self._menu_pos = (sx, sy)

    def _tk_root(self) -> tk.Tk:
        if self._tk is None:
            try:
                from tkinterdnd2 import TkinterDnD

                root = TkinterDnD.Tk()
            except Exception:
                root = tk.Tk()
            root.withdraw()
            self._tk = root
        return self._tk

    def _dialog_near(self) -> _Anchor:
        """弹窗绕开计时器本体放；账本最小化时连顶上小签一起让开。"""
        return self._timer_anchor()

    def _open_setup_dialog(self) -> None:
        start_preset = self._start_hm()
        if self._time_mode() == "direct" and self._has_target():
            off_preset = self._off_hm()
        else:
            oh, om = self.cfg.get("off_h"), self.cfg.get("off_m")
            off_preset = (int(oh), int(om)) if isinstance(oh, int) and isinstance(om, int) else (18, 0)
        mode = flex_time.setup_dialog_default_mode(
            self.cfg,
            has_target=self._has_target(),
            time_mode=self._time_mode(),
        )
        picked = _ask_offwork_setup(
            self._tk_root(),
            mode=mode,
            start_preset=start_preset,
            off_preset=off_preset,
            remember_off=self._remember_offwork(),
            near=self._dialog_near(),
            win=self.win,
        )
        if picked is None:
            return
        mode, hm, remember = picked
        self.cfg["time_mode"] = mode
        self.cfg["start_date"] = self._today()
        self._clear_session_stale()
        today = datetime.now().date()
        if mode == "flex":
            self.cfg["start_h"], self.cfg["start_m"] = hm
        else:
            self.cfg["off_h"], self.cfg["off_m"] = hm
            self.cfg["remember_offwork"] = bool(remember)
        self._sync_declared(today, force=True)
        schedules.ensure_fields(self.cfg)
        schedules.set_pinned(self.cfg, schedules.OFFWORK_ID, True)
        self.cfg["active_pin_id"] = schedules.OFFWORK_ID
        self._worklog_tick(force=True)
        store.save_config(self.cfg)
        self._last_key = ""

    def _sync_declared(self, day: date, *, force: bool = False) -> bool:
        """自填默认跟着倒计时。弹性用填写的到岗和推算下班；固定下班用首次上机和固定时间。"""
        if not self._has_target():
            return False
        mode = self._time_mode()
        start = self._start_hm() if mode == "flex" else None
        return worklog.sync_declared(
            self.cfg, day, mode=mode, start=start, off=self._off_hm(), force=force,
        )

    def _worklog_tick(self, *, force: bool = False, flush: bool = False) -> None:
        mono = time.monotonic()
        if not force and mono - self._worklog_at < 1:
            return
        self._worklog_at = mono
        now = datetime.now()
        if activity.settle(self.cfg, now):
            self._activity_dirty = True
        tracking = worklog.tracking_enabled(self.cfg)
        changed = tracking and worklog.touch_target(self.cfg, now.date(), self._off_hm())
        if not tracking:
            self._burst = None
        # Raw Input 是主证据；LastInput 只在事件 tick 真变过时补触摸、笔和远程输入。
        snapshot = worklog.last_input_snapshot()
        phase = worklog.observe_clock(now)
        if phase == "wake":
            self._burst = None
            self._last_input_seen = snapshot[0] if snapshot is not None else None
        elif phase == "quiet":
            # 安静窗口只屏蔽低可信兜底。Raw Input 仍会直接进入 _note_work_input。
            if snapshot is not None:
                self._last_input_seen = snapshot[0]
        else:
            self._last_input_seen, last = worklog.fallback_input(
                self._last_input_seen, snapshot, now
            )
            if tracking and last is not None and last.date() == now.date():
                self._note_work_input(last)
        idle = snapshot[1] if snapshot is not None else 0.0
        if tracking and worklog.settle_doubt(self.cfg, now, idle):
            changed = True
        if self._sync_declared(now.date()):
            changed = True
        if changed:
            self._worklog_dirty = True
        if (self._worklog_dirty or self._activity_dirty) and (flush or mono - self._worklog_save_at >= 180):
            store.save_config(self.cfg)
            self._worklog_dirty = False
            self._activity_dirty = False
            self._worklog_save_at = mono

    def _note_beat(self) -> None:
        """主循环或自家弹窗循环还在转。定时器看到心跳新鲜就不动手。"""
        self._loop_beat = time.monotonic()

    def _on_live_timer(self) -> None:
        """菜单、文件选择、系统提示框自己转消息循环，主循环进不去。"""
        if self._painting or self.win.dragging or self.win.resizing:
            return
        if time.monotonic() - self._loop_beat < 0.07:
            return
        try:
            self._tick_alive()
        except Exception as e:  # noqa: BLE001
            store.log_exception("live-timer", e)

    def _tick_alive(self, *, paint: bool = True) -> None:
        """倒计时、动画、喝水提醒、日程轮播、工时。不采样桌面，避免在系统对话框里卡住。"""
        self._poll_key_hide()
        self._tick_trail()
        now_m = time.monotonic()
        self._tick_kinetic(now_m)
        self._tick_hydrate(now_m)
        today = self._today()
        if today != self._fest_day:
            self._fest_day = today
            if schedules.sync_festival(self.cfg):
                store.save_config(self.cfg)
                self._last_key = ""
        if not kinetic.playing(self._kinetic, now_m) and schedules.rotate_tick(
            self.cfg, self._last_pin_rotate, now_m
        ):
            self._last_pin_rotate = now_m
            self._last_key = ""
        self._worklog_tick()
        self._place_worklog_dock(follow_only=True)
        self._pump_worklog_dock()
        if paint and not self.win.screen_asleep:
            self._paint()
        self._prune_thunder_hits(now_m)
        self._prune_ink_hits(now_m)

    def _card_frame(self) -> None:
        """自家弹窗循环里调用：比定时器多刷新工时账本那一行。"""
        try:
            ui = getattr(self, "_worklog_ui", None)
            if ui is not None and ui.get("stop"):
                return
            if self.win.resizing:
                self._card_was_resizing = True
                self._sync_layout_from_window()
                self._meow.resizing(True, time.monotonic())
                self._place_worklog_dock(follow_only=True)
                self._paint()
                return
            if self.win.dragging:
                self._card_was_dragging = True
                self._place_worklog_dock(follow_only=True)
                return
            if getattr(self, "_card_was_resizing", False) or self.win.just_resized:
                self._card_was_resizing = False
                self._meow.resizing(False, time.monotonic())
                self.win.ensure_visible()
                self._sync_layout_from_window()
                self._persist_size()
                self._persist_pos()
                self._last_key = ""
                self._force_surface_sample = True
                self._place_worklog_dock()
            if getattr(self, "_card_was_dragging", False) or self.win.just_moved:
                self._card_was_dragging = False
                self.win.ensure_visible()
                self._persist_pos()
                self._last_key = ""
                self._force_surface_sample = True
            if self._menu_pos is not None:
                sx, sy = self._menu_pos
                self._menu_pos = None
                self._handle_menu(sx, sy)
            if self._need_worklog and not self._update_dialog_open:
                # 主循环被卡片模态挡住时，贴条点击只会落到这里。
                self._need_worklog = False
                if ui is not None and ui.get("live"):
                    self._restore_worklog(ui)
                else:
                    self._open_worklog_dialog()
            paint = True
            if ui is not None and time.monotonic() < float(ui.get("scroll_until") or 0):
                # 账本正在滑。这一帧把 CPU 留给窗口挪动，倒计时晚几十毫秒再画。
                paint = False
            elif power_save.saving():
                now_m = time.monotonic()
                if now_m - getattr(self, "_card_paint_at", 0.0) < 1.0 / power_save.BATTERY_HZ:
                    paint = False
                else:
                    self._card_paint_at = now_m
            self._tick_alive(paint=paint)
            self._refresh_surface()
            self._refresh_worklog_live()
        except Exception as e:  # noqa: BLE001
            store.log_exception("card-frame", e)

    def _open_share(self) -> None:
        url, text = share.current_share(self.cfg)
        dlg = _card_dialog(self._tk_root(), near=self._dialog_near(), width=420, height=360)
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(8, 16))
        body = tk.Frame(dlg, bg=_CARD_BG)
        body.pack(side="top", fill="both", expand=True, padx=18)
        status = tk.StringVar(value="")
        tk.Label(
            body, text="发给同事", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(16, 6), anchor="w")
        tk.Label(
            body,
            text="优先发下载地址，对方打开后自己选 Windows 版本。不确定对方电脑，不要直接发安装包。",
            fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9),
            wraplength=380, justify="left",
        ).pack(anchor="w")
        tk.Label(
            body, text=url, fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 9),
            wraplength=380, justify="left",
        ).pack(anchor="w", pady=(8, 0))
        tk.Label(
            body, text=share.file_share_hint(), fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9),
            wraplength=380, justify="left",
        ).pack(anchor="w", pady=(8, 0))
        tk.Label(
            body, textvariable=status, fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9),
            wraplength=380, justify="left",
        ).pack(anchor="w", pady=(8, 0))
        pull: dict = {"job": None}

        def copy_link() -> None:
            try:
                share.copy_text(text)
            except (OSError, ctypes.ArgumentError):
                status.set("剪贴板没放进去，再试一次。")
                return
            status.set("已复制下载页地址，对方打开后自己选系统。")

        def finish_file(path) -> None:
            try:
                share.copy_file(path)
            except (OSError, ctypes.ArgumentError):
                status.set("安装包没复制上。改点「复制下载地址」。")
                return
            status.set("已复制安装包。请确认对方电脑系统对得上。")

        def copy_setup() -> None:
            if pull["job"] is not None:
                return
            ok = messagebox.askyesno(
                "复制安装包",
                share.file_share_hint() + "\n\n仍然复制这个安装包？不确定就发下载地址。",
                parent=dlg,
            )
            if not ok:
                status.set("已取消。改发下载地址更稳。")
                return
            found = share.cached_setup(share.ASSET_NAME)
            if found is not None:
                finish_file(found)
                return
            repo = str(self.cfg.get("gitcode_repo") or "").strip() or "mdslanruo/work-timer"
            try:
                dest = share.cache_path(share.ASSET_NAME)
            except ValueError:
                status.set("这台电脑下不了。把下载地址发给能上网的同事。")
                return
            status.set(share.progress_line(0, 0))
            pull["job"] = share.Pull(
                share.public_download_url(repo, APP_VERSION, share.ASSET_NAME),
                dest.with_name(dest.name + ".download"),
            )

        def fail_pull(job) -> None:
            job.abort()
            pull["job"] = None
            status.set("这台电脑下不了。把下载地址发给能上网的同事。")

        def on_frame() -> None:
            job = pull["job"]
            if job is None:
                return
            try:
                state = job.step()
            except Exception:
                fail_pull(job)
                return
            if state != "ok":
                status.set(share.progress_line(job.done, job.total))
                return
            part = job.part
            pull["job"] = None
            try:
                path = share.remember_setup(part, share.ASSET_NAME)
            except OSError:
                try:
                    part.unlink()
                except OSError:
                    pass
                status.set("这台电脑下不了。把下载地址发给能上网的同事。")
                return
            try:
                part.unlink()
            except OSError:
                pass
            finish_file(path)

        _card_btn(bar, "复制下载地址", copy_link, accent=True).pack(side="left", padx=(18, 8))
        _card_btn(bar, "复制安装包", copy_setup).pack(side="left", padx=8)
        _card_btn(bar, "好", dlg.destroy).pack(side="right", padx=(8, 18))
        _reveal_card(dlg, min_w=360, min_h=220, near=self._dialog_near())
        try:
            _run_card_modal(dlg, self.win, on_frame=on_frame)
        finally:
            job = pull["job"]
            if job is not None:
                job.abort()

    def _open_about(self) -> None:
        dlg = _card_dialog(self._tk_root(), near=self._dialog_near(), width=480, height=620)
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(8, 16))
        body = tk.Frame(dlg, bg=_CARD_BG)
        body.pack(side="top", fill="both", expand=True, padx=18)
        err = tk.StringVar(value="")
        _pack_err_line(body, err, wrap=420)
        tk.Label(
            body, text="关于", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(16, 6), anchor="w")
        tk.Label(
            body,
            text=f"下班倒计时  {APP_VERSION}",
            fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 11),
        ).pack(anchor="w")
        tk.Label(
            body,
            text=feedback.repo_url(self.cfg),
            fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9),
            wraplength=420, justify="left",
        ).pack(anchor="w", pady=(4, 0))
        tk.Label(
            body, text="用户反馈", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w", pady=(14, 4))
        title_var = tk.StringVar()
        tk.Label(body, text="标题", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", pady=(8, 0)
        )
        tk.Entry(
            body, textvariable=title_var, font=("Microsoft YaHei UI", 12), bg="#222733", fg=_CARD_FG,
            insertbackground=_CARD_FG, relief="flat",
        ).pack(anchor="w", ipady=5, fill="x")
        contact_var = tk.StringVar(value=str(self.cfg.get("feedback_contact") or ""))
        tk.Label(
            body, text="联系方式",
            fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(8, 0))
        tk.Entry(
            body, textvariable=contact_var, font=("Microsoft YaHei UI", 11), bg="#222733", fg=_CARD_FG,
            insertbackground=_CARD_FG, relief="flat",
        ).pack(anchor="w", ipady=4, fill="x")
        tk.Label(body, text="内容", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", pady=(8, 0)
        )
        text = tk.Text(
            body, height=6, wrap="word", font=("Microsoft YaHei UI", 11), bg="#222733", fg=_CARD_FG,
            insertbackground=_CARD_FG, relief="flat", bd=0, highlightthickness=0, padx=8, pady=8,
        )
        text.pack(anchor="w", fill="both", expand=True, pady=(4, 8))
        busy = {"v": False}

        def send() -> None:
            if busy["v"]:
                return
            title = title_var.get().strip()
            content = text.get("1.0", "end-1c").strip()
            contact = feedback.normalize_contact(contact_var.get())
            if not title and not content:
                err.set("请填写标题或内容")
                return
            if not contact:
                err.set("请填写联系方式")
                return
            busy["v"] = True
            err.set("正在提交…")
            try:
                dlg.update()
            except Exception:
                pass
            kind, info = feedback.submit(self.cfg, title, content, contact)
            busy["v"] = False
            if kind == "ok":
                err.set("已提交到仓库")
                title_var.set("")
                text.delete("1.0", "end")
                return
            if kind == "browser":
                err.set("已打开仓库反馈页，登录后点提交即可。")
                return
            err.set(info)

        _card_btn(bar, "打开官方仓库", lambda: feedback.open_repo(self.cfg)).pack(side="left", padx=(18, 6))
        _card_btn(bar, "提交反馈", send, accent=True).pack(side="left", padx=6)
        _card_btn(bar, "关闭", dlg.destroy).pack(side="left", padx=6)
        _reveal_card(dlg, min_w=480, min_h=580, near=self._dialog_near())
        _run_card_modal(dlg, self.win)

    def _open_idle_dialog(self) -> None:
        self._open_setup_dialog()

    def _open_skin_settings_dialog(self) -> None:
        dlg = _card_dialog(self._tk_root(), near=self._dialog_near(), width=420, height=300)
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(8, 16))
        body = tk.Frame(dlg, bg=_CARD_BG)
        body.pack(side="top", fill="both", expand=True, padx=18)
        err = tk.StringVar(value="")
        _pack_err_line(body, err, wrap=360)
        tk.Label(
            body, text="皮肤设置", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(16, 10), anchor="w")

        th_frame = tk.Frame(body, bg="#1e2430", highlightthickness=1, highlightbackground="#2a3140")
        th_frame.pack(fill="x", pady=(0, 8))
        th_inner = tk.Frame(th_frame, bg="#1e2430")
        th_inner.pack(fill="x", padx=12, pady=10)
        tk.Label(
            th_inner, text="霹雳狂潮", fg=_CARD_FG, bg="#1e2430", font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w")
        tk.Label(
            th_inner,
            text="点击台词",
            fg=_CARD_MUTED, bg="#1e2430", font=("Microsoft YaHei UI", 9), wraplength=340, justify="left",
        ).pack(anchor="w", pady=(4, 2))
        quote_var = tk.StringVar(value=skin_settings.thunder_quote(self.cfg))
        tk.Entry(
            th_inner, textvariable=quote_var, font=("Microsoft YaHei UI", 12), bg="#222733", fg=_CARD_FG,
            insertbackground=_CARD_FG, relief="flat",
        ).pack(anchor="w", ipady=5, fill="x")
        tk.Label(
            th_inner,
            text=f"最多 {skin_settings.THUNDER_QUOTE_MAX} 字，例如：{skin_settings.THUNDER_QUOTE_EXAMPLE}",
            fg=_CARD_MUTED, bg="#1e2430", font=("Microsoft YaHei UI", 8), wraplength=340, justify="left",
        ).pack(anchor="w", pady=(4, 0))

        def save() -> None:
            skin_settings.set_thunder_quote(self.cfg, quote_var.get())
            store.save_config(self.cfg)
            self._thunder_quote_step = 0
            self._last_key = ""
            err.set("已保存")

        _card_btn(bar, "保存", save, accent=True).pack(side="left", padx=(18, 6))
        _card_btn(bar, "关闭", dlg.destroy).pack(side="left", padx=6)
        _reveal_card(dlg, min_w=420, min_h=280, near=self._dialog_near())
        _run_card_modal(dlg, self.win)

    def _open_key_hide_dialog(self) -> None:
        dlg = _card_dialog(self._tk_root(), near=self._dialog_near(), width=420, height=320)
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(8, 16))
        body = tk.Frame(dlg, bg=_CARD_BG)
        body.pack(side="top", fill="both", expand=True, padx=18)
        err = tk.StringVar(value="")
        _pack_err_line(body, err, wrap=360)
        tk.Label(
            body, text="按键隐藏", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(16, 10), anchor="w")

        box = tk.Frame(body, bg="#1e2430", highlightthickness=1, highlightbackground="#2a3140")
        box.pack(fill="x", pady=(0, 8))
        inner = tk.Frame(box, bg="#1e2430")
        inner.pack(fill="x", padx=12, pady=12)
        preview = tk.StringVar(value=key_hide.label(key_hide.vk(self.cfg)))
        tk.Label(inner, text="当前按键", fg=_CARD_MUTED, bg="#1e2430", font=("Microsoft YaHei UI", 9)).pack(
            anchor="w"
        )
        key_lbl = tk.Label(
            inner,
            textvariable=preview,
            fg=_CARD_ACCENT,
            bg="#1e2430",
            font=("Consolas", 22, "bold"),
        )
        key_lbl.pack(anchor="w", pady=(4, 8))
        tk.Label(
            inner,
            text="按下要换成的键",
            fg=_CARD_MUTED,
            bg="#1e2430",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w")

        enabled_var = tk.BooleanVar(value=self._key_hide_on())
        tk.Checkbutton(
            body,
            text="启用按键隐藏",
            variable=enabled_var,
            fg=_CARD_FG,
            bg=_CARD_BG,
            activebackground=_CARD_BG,
            activeforeground=_CARD_FG,
            selectcolor="#222733",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        pending = {"vk": key_hide.vk(self.cfg)}

        def on_key(event: tk.Event) -> str:
            if event.keysym == "Escape":
                dlg.destroy()
                return "break"
            code = key_hide.normalize_vk(event.keycode)
            if code is None:
                err.set("此键不可用，请换别的键。")
                return "break"
            pending["vk"] = code
            preview.set(key_hide.label(code))
            err.set("")
            return "break"

        dlg.bind("<KeyPress>", on_key)

        def save() -> None:
            key_hide.set_vk(self.cfg, pending["vk"])
            key_hide.set_enabled(self.cfg, enabled_var.get())
            store.save_config(self.cfg)
            if not enabled_var.get() and self._esc_hidden:
                self._show_after_esc()
            err.set(f"已保存：{key_hide.label(pending['vk'])}")

        _card_btn(bar, "保存", save, accent=True).pack(side="left", padx=(18, 6))
        _card_btn(bar, "关闭", dlg.destroy).pack(side="left", padx=6)
        _reveal_card(dlg, min_w=420, min_h=300, near=self._dialog_near())
        dlg.after(80, dlg.focus_force)
        _run_card_modal(dlg, self.win)

    def _open_hydrate_dialog(self) -> None:
        dlg = _card_dialog(self._tk_root(), near=self._dialog_near(), width=440, height=380)
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(8, 16))
        body = tk.Frame(dlg, bg=_CARD_BG)
        body.pack(side="top", fill="both", expand=True, padx=18)
        tk.Label(
            body, text="喝水久坐提醒", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(16, 10), anchor="w")
        interval_var = tk.IntVar(value=hydrate.interval_min(self.cfg))
        box = tk.Frame(body, bg=_CARD_BG)
        box.pack(anchor="w")
        tk.Label(box, text="间隔", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(anchor="w")
        row = tk.Frame(box, bg=_CARD_BG)
        row.pack(anchor="w", pady=(4, 8))
        for mins in hydrate.PRESETS:
            tk.Radiobutton(
                row, text=f"{mins} 分钟", variable=interval_var, value=mins,
                fg=_CARD_FG, bg=_CARD_BG, selectcolor=_CARD_BTN, activebackground=_CARD_BG,
                font=("Microsoft YaHei UI", 10),
            ).pack(side="left", padx=(0, 10))
        enabled_var = tk.BooleanVar(value=self._hydrate_on())
        tk.Checkbutton(
            body,
            text="启用提醒",
            variable=enabled_var,
            fg=_CARD_FG,
            bg=_CARD_BG,
            activebackground=_CARD_BG,
            activeforeground=_CARD_FG,
            selectcolor="#222733",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(4, 0))
        strong_var = tk.BooleanVar(value=hydrate.strengthen(self.cfg))
        tk.Checkbutton(
            body,
            text="加强：到点同时提醒久坐",
            variable=strong_var,
            fg=_CARD_FG,
            bg=_CARD_BG,
            activebackground=_CARD_BG,
            activeforeground=_CARD_FG,
            selectcolor="#222733",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(8, 0))
        tk.Label(
            body,
            text="默认只催喝水。勾上加强后，卡片会写「起来站一会」，\n并注明要喝一杯、离开座位站一会。点一下表示两件都做了。",
            fg=_CARD_MUTED,
            bg=_CARD_BG,
            justify="left",
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(6, 0))

        def save() -> None:
            hydrate.set_interval(self.cfg, interval_var.get())
            hydrate.set_strengthen(self.cfg, bool(strong_var.get()))
            self._set_hydrate(bool(enabled_var.get()))
            dlg.destroy()

        _card_btn(bar, "保存", save, accent=True).pack(side="left", padx=(18, 6))
        _card_btn(bar, "关闭", dlg.destroy).pack(side="left", padx=6)
        _reveal_card(dlg, min_w=440, min_h=360, near=self._dialog_near())
        _run_card_modal(dlg, self.win)

    def _open_trail_settings_dialog(self) -> None:
        dlg = _card_dialog(self._tk_root(), near=self._dialog_near(), width=440, height=430)
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(8, 16))
        body = tk.Frame(dlg, bg=_CARD_BG)
        body.pack(side="top", fill="both", expand=True, padx=18)
        tk.Label(
            body, text="光标尾巴", fg=_CARD_FG, bg=_CARD_BG,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(16, 2), anchor="w")
        tk.Label(
            body, text="只改变视觉效果，不记录光标位置。", fg=_CARD_MUTED, bg=_CARD_BG,
            font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w", pady=(0, 10))

        enabled_var = tk.BooleanVar(value=self._trail_on())
        tk.Checkbutton(
            body, text="启用光标尾巴", variable=enabled_var,
            fg=_CARD_FG, bg=_CARD_BG, selectcolor="#222733",
            activebackground=_CARD_BG, activeforeground=_CARD_FG,
            highlightthickness=0, font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(0, 8))

        panel = tk.Frame(body, bg="#1e2430", highlightthickness=1, highlightbackground="#2a3140")
        panel.pack(fill="x")
        inner = tk.Frame(panel, bg="#1e2430")
        inner.pack(fill="x", padx=12, pady=12)
        tk.Label(
            inner, text="尾巴颜色", fg=_CARD_FG, bg="#1e2430",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(anchor="w")
        tk.Label(
            inner, text="「随时间」会从早上的冰蓝逐渐变成下班前的暖橙。",
            fg=_CARD_MUTED, bg="#1e2430", font=("Microsoft YaHei UI", 8),
        ).pack(anchor="w", pady=(2, 8))

        preview = tk.Canvas(inner, height=66, bg="#171c25", highlightthickness=0)
        preview.pack(fill="x", pady=(0, 10))
        selected = {"id": cursor_trail.color_id(self.cfg)}
        tiles: dict[str, tk.Frame] = {}

        def draw_preview() -> None:
            preview.delete("all")
            rgb = cursor_trail.resolved_color(selected["id"], 4 * 3600)
            color = "#%02x%02x%02x" % rgb
            width = max(260, int(preview.winfo_width() or 360))
            pts = [(24, 44), (74, 37), (126, 42), (182, 25), (244, 31), (width - 26, 18)]
            preview.create_line(*sum(([x, y] for x, y in pts), []), fill=color, width=9, smooth=True)
            preview.create_line(*sum(([x, y] for x, y in pts), []), fill="#fffaf2", width=3, smooth=True)
            x, y = pts[-1]
            preview.create_oval(x - 6, y - 6, x + 6, y + 6, fill="#fffaf2", outline=color, width=3)

        def choose(value: str) -> None:
            selected["id"] = value
            for key, tile in tiles.items():
                tile.configure(
                    bg=_CARD_ACCENT if key == value else "#222733",
                    highlightbackground=_CARD_ACCENT if key == value else "#30394a",
                )
                for child in tile.winfo_children():
                    if isinstance(child, tk.Label):
                        child.configure(bg=_CARD_ACCENT if key == value else "#222733")
            draw_preview()

        choices = tk.Frame(inner, bg="#1e2430")
        choices.pack(fill="x")
        for index, (key, label, rgb) in enumerate(cursor_trail.COLOR_PRESETS):
            tile = tk.Frame(
                choices, bg="#222733", highlightthickness=1, highlightbackground="#30394a",
                cursor="hand2", width=112, height=38,
            )
            tile.grid(row=index // 3, column=index % 3, padx=(0, 8), pady=(0, 8), sticky="ew")
            tile.grid_propagate(False)
            choices.columnconfigure(index % 3, weight=1)
            shown = cursor_trail.resolved_color(key, 4 * 3600) if rgb is None else rgb
            dot = tk.Canvas(tile, width=18, height=18, bg="#222733", highlightthickness=0, cursor="hand2")
            dot.create_oval(2, 2, 16, 16, fill="#%02x%02x%02x" % shown, outline="")
            dot.pack(side="left", padx=(9, 3), pady=9)
            lbl = tk.Label(
                tile, text=label, fg=_CARD_FG, bg="#222733",
                font=("Microsoft YaHei UI", 9), cursor="hand2",
            )
            lbl.pack(side="left")
            for widget in (tile, dot, lbl):
                widget.bind("<Button-1>", lambda _e, value=key: choose(value))
            tiles[key] = tile
        dlg.after_idle(lambda: choose(selected["id"]))

        def save() -> None:
            cursor_trail.set_color(self.cfg, selected["id"])
            self._set_trail(bool(enabled_var.get()))
            dlg.destroy()

        _card_btn(bar, "保存", save, accent=True).pack(side="left", padx=(18, 6))
        _card_btn(bar, "关闭", dlg.destroy).pack(side="left", padx=6)
        _reveal_card(dlg, min_w=440, min_h=410, near=self._dialog_near())
        _run_card_modal(dlg, self.win)

    def _prewarm_ui(self) -> None:
        """建控件、首次映射加起来两三百毫秒。启动后先建好并在屏幕外画一遍，右键打开就不再顿住。"""
        fg = layered_win.user32.GetForegroundWindow()
        ui = self._ensure_worklog_ui()
        self._fill_worklog(ui)
        _park_card(ui["dlg"], fg)
        sched = self._ensure_schedule_ui()
        sched["show_tab"]("schedules")
        _park_card(sched["dlg"], fg)

    def _offwork_countdown(self, now: datetime) -> tuple[str, int, bool, bool] | None:
        """已有下班时刻则返回倒计时视图；否则 None（调用方再当空闲）。"""
        off = self._off_hm()
        if off is None:
            return None
        td = flex_time.remaining_to(now, off[0], off[1])
        total, done = flex_time.remaining_parts(td)
        title = "已经到点" if done else "距离您下班还有"
        return title, total, done, False

    def _active_view(self, now: datetime) -> tuple[str, int, bool, bool]:
        """当前主界面项：(标题, 剩余秒, 是否到点, 是否空闲未设)。"""
        schedules.ensure_fields(self.cfg)
        aid = schedules.active_id(self.cfg)
        if aid is None:
            # 优先列表被清空时，有下班时间就回退显示倒计时，别装成「点我开始」却点不动
            return self._offwork_countdown(now) or ("距离下班", 0, False, True)
        if aid == schedules.OFFWORK_ID:
            return self._offwork_countdown(now) or ("距离下班", 0, False, True)
        item = schedules.find_schedule(self.cfg, aid)
        if item is None:
            return "距离下班", 0, False, True
        left, done = schedules.schedule_remaining(item, now)
        title = schedules.schedule_countdown_title(str(item.get("title") or "日程"), done=done)
        return title, left, done, False

    def _ticker_seconds(self, now: datetime, total: int, done: bool, idle: bool) -> float:
        if idle:
            return 0.0
        aid = schedules.active_id(self.cfg)
        # 与 _active_view 一致：无优先项时回退下班倒计时
        if aid is None or aid == schedules.OFFWORK_ID:
            off = self._off_hm()
            if off is None:
                return 0.0
            return flex_time.remaining_to(now, off[0], off[1]).total_seconds()
        item = schedules.find_schedule(self.cfg, aid) if aid else None
        if item is not None and str(item.get("kind") or "") == "clock":
            target = schedules.schedule_target(item)
            if target is not None:
                return (target - now).total_seconds()
        return -float(total) if done else float(total)

    def _handle_menu(self, sx: int, sy: int) -> None:
        op = self.win.popup_menu(
            sx,
            sy,
            self._display_mode(),
            self._theme().id,
            key_hide_enabled=self._key_hide_on(),
            key_hide_settings_label=key_hide.menu_caption(self.cfg),
            hydrate_enabled=self._hydrate_on(),
            hydrate_settings_label=hydrate.menu_caption(self.cfg),
            trail_enabled=self._trail_on(),
            auto_start=self._auto_start_on(),
        )
        if op == "quit":
            self._request_quit()
        elif op == "share":
            self._open_share()
        elif op == "update":
            self._check_update()
        elif op in ("set_time", "set_off"):
            self._open_setup_dialog()
        elif op == "schedules":
            if self._schedule_list_open:
                self._need_close_schedule_list = True
            else:
                self._open_schedule_list()
        elif op == "worklog":
            self._open_worklog_dialog()
        elif op == "games":
            mines.open_games(
                self._tk_root(),
                self._dialog_near(),
                self.win,
                dialog=_card_dialog,
                button=_card_btn,
                reveal=_reveal_card,
                modal=_run_card_modal,
                bg=_CARD_BG,
                fg=_CARD_FG,
                muted=_CARD_MUTED,
                poll_hide=self._games_hide_state,
                live=self._card_frame,
            )
        elif op == "toggle_key_hide":
            self._set_key_hide(not self._key_hide_on())
        elif op == "key_hide_settings":
            self._open_key_hide_dialog()
        elif op == "toggle_hydrate":
            self._set_hydrate(not self._hydrate_on())
        elif op == "toggle_trail":
            self._set_trail(not self._trail_on())
        elif op == "trail_settings":
            self._open_trail_settings_dialog()
        elif op == "hydrate_settings":
            self._open_hydrate_dialog()
        elif op == "toggle_auto_start":
            self._set_auto_start(not self._auto_start_on())
        elif op == "about":
            self._open_about()
        elif op == "skin_settings":
            self._open_skin_settings_dialog()
        elif op == "create_desktop_shortcut":
            self._create_desktop_shortcut()
        elif op == "uninstall":
            self._confirm_uninstall()
        elif op == "fmt_hms":
            self._set_display_mode("hms")
        elif op == "fmt_min":
            self._set_display_mode("min")
        elif op == "fmt_sec":
            self._set_display_mode("sec")
        elif op == "refresh_themes":
            self._refresh_themes()
        elif op.startswith("theme:"):
            self._set_theme(op.split(":", 1)[1])

    def _tick_trail(self) -> None:
        """光标尾巴。没设下班、锁屏时不画。隐藏键只收卡片，尾巴继续跟。失败只记一次。"""
        if self._trail_failed or not self._trail_on():
            if self._trail is not None:
                try:
                    self._trail.hide()
                except Exception as e:  # noqa: BLE001
                    self._trail_failed = True
                    store.log_exception("trail", e)
            return
        try:
            if self._trail is None:
                self._trail = cursor_trail.Trail()
            _title, total, done, idle = self._active_view(datetime.now())
            remain = 0 if idle or done else total
            visible = not idle and not self.win.screen_asleep
            # 菜单自己转消息循环。这时再抬卡片或尾巴，菜单会被压住或直接关掉。
            popup = bool(self.win._popup_open)
            below = 0 if self._esc_hidden or popup else int(self.win.hwnd or 0)
            self._trail.tick(
                remain,
                visible=visible,
                color=cursor_trail.color_id(self.cfg),
                below=below,
                raise_windows=not popup,
            )
        except Exception as e:  # noqa: BLE001
            self._trail_failed = True
            store.log_exception("trail", e)
            try:
                self._trail.destroy()
            except Exception:
                pass

    def _paint(self) -> None:
        if self._painting:
            return
        if self.win.width != self._win_w or self.win.height != self._win_h:
            self._sync_layout_from_window()
        self._painting = True
        try:
            self._paint_now()
        finally:
            self._painting = False

    def _paint_now(self) -> None:
        try:
            now = datetime.now()
            mode = self._display_mode()
            tally = self._tally_for_paint()
            still = activity.still_phrase(worklog.idle_seconds()) if tally is not None else None
            base = self._theme()
            w, h = self._win_w, self._win_h
            phase = time.monotonic()
            title, total, done, idle = self._active_view(now)
            self._check_celebrate(schedules.active_id(self.cfg) or "-", title, total, done, idle, phase)
            surface = self._surface if base.adaptive else "dark"
            theme = themes.resolve_for_surface(base, surface)
            sub = ""
            if idle:
                big = "点我开始"
                accent = theme.idle
                stage = "idle"
                key = f"idle-{mode}-{theme.id}-{theme.fill}-{surface}-{w}x{h}"
            elif done:
                big = flex_time.format_remaining(total, mode)
                accent = theme.done
                stage = "done"
                key = f"done-{mode}-{theme.id}-{title}-{big}-{theme.fill}-{surface}-{w}x{h}"
            else:
                big = flex_time.format_remaining(total, mode)
                mins = total // 60
                accent = theme.warn if mins < 30 else theme.big
                stage = "warn" if mins < 30 else "run"
                key = f"run-{mode}-{theme.id}-{title}-{big}-{theme.fill}-{surface}-{w}x{h}"
            aid = schedules.active_id(self.cfg) or "-"
            idx, n = schedules.pin_index(self.cfg)
            key = f"{key}-{aid}-{idx}/{n}-{stage}"
            env = self._env_rgb
            if env is not None and ornaments.uses_env(theme.kind):
                key = f"{key}-e{env[0] // 20}{env[1] // 20}{env[2] // 20}"
            shown_title = title if not idle else "距离下班"
            if theme.kind == ticker.KIND:
                signed = self._ticker_seconds(now, total, done, idle)
                big = ticker.format_clock(signed, idle=idle)
                shown_title = ticker.header_title(stage, idle=idle)
                ticker.observe(phase, activity.live_intensity(self.cfg, now))
            meow_on = theme.kind == meow.KIND
            drinking = meow_on and self._hydrate_showing and kinetic.playing(self._kinetic, phase)
            if meow_on:
                call = self._meow.callout(phase)
                if call:
                    shown_title = call
                    key = f"{key}-m{call}"
            fps = 0
            bg_hz = 0
            if ornaments.has_skin(theme.kind):
                if theme.kind == "thunder":
                    # 落雷那半秒要满帧，平时只有雨在下
                    bg_hz = ornaments.thunder_fps(stage, phase)
                elif meow_on:
                    bg_hz = self._meow.fps(stage, phase, drinking=drinking)
                elif theme.kind == suofen.KIND:
                    bg_hz = suofen.fps(stage, phase)
                elif theme.kind == ticker.KIND:
                    bg_hz = ticker.fps(stage, phase)
                elif themes.use_flip_display(theme.kind, big, self.cfg, h=h):
                    if ornaments.drift_only(theme.kind) and not ornaments.sweeping(stage, phase):
                        bg_hz = 10
                    else:
                        bg_hz = 14 if stage in ("idle", "done") else 20
                elif theme.kind in ("neonflow", "inkpulse"):
                    bg_hz = 30 if stage == "warn" else (16 if stage in ("idle", "done") else 28)
                else:
                    sweeping = ornaments.sweeping(stage, phase)
                    bg_hz = 30 if sweeping else (12 if stage in ("idle", "done") else 24)
                fps = bg_hz
                if self._flip_anims and theme.kind != "thunder":
                    fps = 60
                key = f"{key}-a{int(phase * fps)}"
            elif theme.kind != "ghost":
                key = f"{key}-p{int(phase * 6)}"
            self.win.corner_hit = 22 if theme.kind == "ghost" else layered_win.EDGE
            if kinetic.playing(self._kinetic, phase):
                key = (
                    f"kinetic-{self._kinetic.current_text(phase)}"
                    f"-{int(phase * 60)}-{theme.id}-{w}x{h}"
                )
            celebrating = phase < self._celebrate_until
            if celebrating:
                key = f"{key}-c{int(phase * 30)}"
            if themes.use_flip_display(theme.kind, big, self.cfg, h=h):
                import fx

                self._flip_prev_digits = fx.sync_flip_anims(
                    self._flip_anims, self._flip_prev_digits, big, phase,
                )
                self._flip_last_big = big
                flip_sig = fx.flip_anim_signature(self._flip_anims, phase)
                if flip_sig:
                    key = f"{key}-f{flip_sig}"
            self._prune_thunder_hits(phase)
            self._prune_ink_hits(phase)
            thunder_hits = self._thunder_hits
            ink_hits = self._ink_hits
            neon_sig = ""
            if theme.kind == "neonflow":
                neon_sig = ornaments.neon_ammo_signature(self._neon_ammo, phase)
                neon_sig = f"{neon_sig}|{ornaments.neon_planets_signature(self._neon_planets, phase)}"
            if thunder_hits:
                sig = "-".join(f"{int((phase - s) * 45)}:{p:.1f}:{q}" for s, _, _, p, q in thunder_hits)
                key = f"{key}-t{len(thunder_hits)}-{sig}"
            if ink_hits:
                sig = "-".join(f"{int((phase - s) * 40)}:{p:.1f}" for s, _, _, p in ink_hits)
                key = f"{key}-i{len(ink_hits)}-{sig}"
            if neon_sig:
                key = f"{key}-n{neon_sig}"
            if theme.kind == "neonflow" and self._mouse_lx >= 0:
                key = f"{key}-m{self._mouse_lx // 3}-{self._mouse_ly // 3}"
            if theme.kind == "ghost" and self._ghost_ptr is not None:
                gx, gy = self._ghost_ptr
                key = f"{key}-gh{gx // 16}-{gy // 16}"
            if self._hydrate_waiting:
                blink = int(phase * 2) % 2 == 0
                shown_title, hint, sub = hydrate.card_copy(self.cfg)
                accent = theme.warn if blink else theme.big
                if theme.kind == ticker.KIND:
                    # 盘口大字必须是倒计时。中文走标题和右侧「点一下」，不能整卡换成 hydrate 缓存键，
                    # 否则毫秒钟和 K 线会按 2Hz 一顿一顿跳。
                    big = ticker.format_clock(signed, idle=idle)
                    sub = hint
                    key = f"{key}-hydrate-{int(blink)}"
                else:
                    big = hint
                    key = f"hydrate-wait-{int(blink)}-{theme.id}-{w}x{h}"

            hz = fps
            if kinetic.playing(self._kinetic, phase):
                hz = 60
            if celebrating:
                hz = max(hz, 30)
            if thunder_hits:
                hz = max(hz, 45)
            if ink_hits:
                hz = max(hz, 40)
            if theme.kind == "neonflow" and self._mouse_lx >= 0:
                hz = max(hz, 45)
            self._present_hz = hz
            if tally is not None:
                key = f"{key}-y{''.join(icon + text for icon, text in tally)}"
            if still:
                key = f"{key}-s{still}"

            if key == self._last_key:
                return

            thunder_quote = skin_settings.thunder_quote(self.cfg) if theme.kind == "thunder" else ""
            thunder_glyphs = None
            if theme.kind == "thunder" and thunder_hits and thunder_quote:
                thunder_glyphs = [
                    (phase - start, qidx, bx, by)
                    for start, bx, by, _power, qidx in thunder_hits
                ]
            if thunder_quote:
                key = f"{key}-tq{len(thunder_quote)}-{hash(thunder_quote) & 0xFFFF}"

            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            if kinetic.playing(self._kinetic, phase) and not self._hydrate_waiting:
                themes.paint_card(
                    img,
                    w,
                    h,
                    theme,
                    "",
                    "",
                    "",
                    accent,
                    self._font_title,
                    self._font_big,
                    self._font_sub,
                    stage=stage,
                    env_rgb=self._env_rgb,
                    surface=surface,
                    thunder_glyphs=thunder_glyphs,
                    thunder_quote=thunder_quote,
                    neon_ammo=self._neon_ammo if theme.kind == "neonflow" else None,
                    neon_now=phase,
                    neon_planets=self._neon_planets if theme.kind == "neonflow" else None,
                    flip_anims=self._flip_anims if themes.use_flip_display(theme.kind, big, self.cfg, h=h) else None,
                    flip_now=phase,
                    flip_hit_rects=self._flip_hit_rects if themes.use_flip_display(theme.kind, big, self.cfg, h=h) else None,
                    meow_troupe=self._meow,
                    meow_mins=total // 60,
                    meow_drinking=drinking,
                    ghost_ptr=self._ghost_ptr if theme.kind == "ghost" else None,
                    tally=tally,
                    still=None,
                    bg_hz=bg_hz,
                )
                kinetic.paint(
                    img,
                    self._kinetic,
                    self._font_kinetic,
                    accent,
                    phase,
                    ghost=theme.kind == "ghost",
                    center_y=meow.layout(themes.card_box(w, h)).cy if meow_on else None,
                )
            else:
                if self._kinetic is not None:
                    self._kinetic = None
                themes.paint_card(
                    img,
                    w,
                    h,
                    theme,
                    shown_title,
                    big,
                    sub,
                    accent,
                    self._font_title,
                    self._font_big,
                    self._font_sub,
                    stage=stage,
                    env_rgb=self._env_rgb,
                    surface=surface,
                    thunder_glyphs=thunder_glyphs,
                    thunder_quote=thunder_quote,
                    neon_ammo=self._neon_ammo if theme.kind == "neonflow" else None,
                    neon_now=phase,
                    neon_planets=self._neon_planets if theme.kind == "neonflow" else None,
                    flip_anims=self._flip_anims if themes.use_flip_display(theme.kind, big, self.cfg, h=h) else None,
                    flip_now=phase,
                    flip_hit_rects=self._flip_hit_rects if themes.use_flip_display(theme.kind, big, self.cfg, h=h) else None,
                    meow_troupe=self._meow,
                    meow_mins=total // 60,
                    meow_drinking=drinking,
                    ghost_ptr=self._ghost_ptr if theme.kind == "ghost" else None,
                    tally=tally,
                    still=still,
                    bg_hz=bg_hz,
                )
                chev = theme.outline if theme.outline[3] > 20 else (255, 255, 255, 70)
                if (0.2126 * accent[0] + 0.7152 * accent[1] + 0.0722 * accent[2]) < 140:
                    chev = (40, 44, 52, 90)
                dots = (idx, n) if n >= 2 and bool(self.cfg.get("auto_rotate_pins")) else (0, 0)
                ornaments.paint_pin_dots(img, w, h, color=chev, pin_dots=dots)
            if celebrating:
                ornaments.paint_confetti(img, w, h, phase - self._celebrate_start)
            box = (4, 4, w - 5, h - 5)
            rr = min(theme.radius, max(8, h // 5))
            for start, bx, by, power, _q in thunder_hits:
                ornaments.paint_bite(
                    img,
                    box,
                    phase - start,
                    stage=stage,
                    light=(surface == "light"),
                    radius=rr,
                    cx=bx - 4,
                    cy=by - 4,
                    power=power,
                )
            for start, bx, by, power in ink_hits:
                ornaments.paint_ink_splash(
                    img,
                    box,
                    phase - start,
                    cx=bx - 4,
                    cy=by - 4,
                    stage=stage,
                    light=(surface == "light"),
                    radius=rr,
                    power=power,
                )
            if theme.kind == "neonflow":
                mouse_xy = None
                if self._mouse_lx >= 0 and self._mouse_ly >= 0:
                    mouse_xy = (float(self._mouse_lx - 4), float(self._mouse_ly - 4))
                ornaments.paint_neon_overlay(
                    img,
                    box,
                    ammo=self._neon_ammo,
                    planets=self._neon_planets,
                    now=phase,
                    phase=phase,
                    mouse_xy=mouse_xy,
                    stage=stage,
                    light=(surface == "light"),
                    radius=rr,
                )
                rdx, rdy = ornaments.neon_recoil(phase, self._neon_ammo)
                if abs(rdx) > 0.05 or abs(rdy) > 0.05:
                    shifted = Image.new("RGBA", (w, h), (0, 0, 0, 0))
                    shifted.alpha_composite(img, (int(round(rdx)), int(round(rdy))))
                    img = shifted
            bgra, mask = _rgba_to_bgra(img)
            self.win.present_bgra(bgra, mask)
            self._last_key = key
        except Exception as e:  # noqa: BLE001
            store.log_exception("paint", e)

    def _persist_pos(self) -> None:
        if self.cfg.get("win_x") == self.win.x and self.cfg.get("win_y") == self.win.y:
            return
        self.cfg["win_x"] = self.win.x
        self.cfg["win_y"] = self.win.y
        store.save_config(self.cfg)

    def run(self) -> None:
        self._paint()
        boot_ok.signal()
        self._maybe_show_whats_new()
        last_save = time.monotonic()
        booted = time.monotonic()
        was_dragging = False
        was_resizing = False
        while self.running and not self.win.closed:
            try:
                self._note_beat()
                self.win.pump()
                self._pump_worklog_dock()
                self._poll_key_hide()
                self._tick_trail()
                if self._esc_hidden:
                    # 单实例 ShowWindow 可能已把 hwnd 显示，但 _esc_hidden 未清 → 主循环空转像卡死
                    self._place_worklog_dock()
                    if self.win.hwnd and layered_win.user32.IsWindowVisible(self.win.hwnd):
                        self._show_after_esc()
                    else:
                        if activity.settle(self.cfg, datetime.now()):
                            self._activity_dirty = True
                        time.sleep(0.008)
                        continue
                if self._menu_pos is not None:
                    sx, sy = self._menu_pos
                    self._menu_pos = None
                    self._handle_menu(sx, sy)
                if self._need_dialog:
                    self._need_dialog = False
                    self._open_idle_dialog()
                if self._need_schedule_list and not self._schedule_list_open:
                    self._need_schedule_list = False
                    self._open_schedule_list()
                if self._need_worklog and not self._update_dialog_open:
                    self._need_worklog = False
                    self._open_worklog_dialog()
                if (
                    self._update_available
                    and not self._update_prompted
                    and not self._update_dialog_open
                    and not self._esc_hidden
                ):
                    self._update_prompted = True
                    self._check_update(known=self._update_info)
                if themes.consume_updated():
                    self._last_key = ""
                    self._force_surface_sample = True
                dragging = self.win.dragging
                resizing = self.win.resizing
                moved = self.win.just_moved
                resized = self.win.just_resized
                if self.win.desktop_changed:
                    self._force_surface_sample = True
                    self._last_key = ""
                    self.win.keep_topmost()
                if resizing:
                    was_resizing = True
                    self._sync_layout_from_window()
                    self._meow.resizing(True, time.monotonic())
                    self._paint()
                    time.sleep(0.001)
                    continue
                if dragging:
                    # 拖动只搬现成的画面。重画和截屏都要等桌面合成，松手后再补一帧。
                    was_dragging = True
                    self._place_worklog_dock(follow_only=True)
                    time.sleep(0.001)
                    continue
                if was_resizing or resized:
                    self._meow.resizing(False, time.monotonic())
                    self.win.ensure_visible()
                    self._sync_layout_from_window()
                    self._persist_size()
                    self._persist_pos()
                    self._force_surface_sample = True
                    self._last_key = ""
                    last_save = time.monotonic()
                    was_resizing = False
                if was_dragging or moved:
                    self.win.ensure_visible()
                    self._last_key = ""
                    self._force_surface_sample = True
                    self._persist_pos()
                    last_save = time.monotonic()
                    was_dragging = False
                now_m = time.monotonic()
                self._tick_kinetic(now_m)
                self._tick_hydrate(now_m)
                today = self._today()
                if today != self._fest_day:
                    self._fest_day = today
                    if schedules.sync_festival(self.cfg):
                        store.save_config(self.cfg)
                        self._last_key = ""
                        self._force_surface_sample = True
                if not kinetic.playing(self._kinetic, now_m) and schedules.rotate_tick(
                    self.cfg, self._last_pin_rotate, now_m
                ):
                    # active_pin 是易失状态，轮播切换不值得每 5s 写一次盘
                    self._last_pin_rotate = now_m
                    self._last_key = ""
                if (
                    not self._ui_prewarmed
                    and now_m - booted > 0.8
                    and not dragging
                    and not resizing
                ):
                    # 失败也只试一次，避免每帧重试把主循环卡死
                    self._ui_prewarmed = True
                    try:
                        self._prewarm_ui()
                    except Exception as e:  # noqa: BLE001
                        store.log_exception("ui-prewarm", e)
                    try:
                        if self._trail is None:
                            self._trail = cursor_trail.Trail()
                        self._trail.warm()
                    except Exception as e:  # noqa: BLE001
                        store.log_exception("trail-warm", e)
                self._worklog_tick()
                self._place_worklog_dock(follow_only=True)
                asleep = self.win.screen_asleep
                if asleep:
                    # 锁屏或关屏：倒计时和工时照走，画面不画、桌面不截。醒来补一帧
                    if now_m - self._wake_checked >= 1.0:
                        self._wake_checked = now_m
                        self.win.check_awake()
                    self._was_asleep = True
                else:
                    if self._was_asleep:
                        self._was_asleep = False
                        self._last_key = ""
                        self._force_surface_sample = True
                    self._refresh_surface()
                    self._paint()
                now = time.monotonic()
                self._prune_thunder_hits(now)
                self._prune_ink_hits(now)
                if now - last_save > 1.5:
                    self._persist_pos()
                    last_save = now
                store.flush_pending()
                if asleep:
                    time.sleep(0.25)
                elif now < self._surface_hot_until or kinetic.playing(self._kinetic, now):
                    time.sleep(1.0 / power_save.frame_hz(FPS))
                elif self._trail is not None and self._trail.hot:
                    time.sleep(1.0 / power_save.frame_hz(FPS))
                elif (
                    ornaments.is_animated(self._theme().kind)
                    or now < self._celebrate_until
                    or bool(self._thunder_hits)
                    or bool(self._ink_hits)
                    or bool(self._flip_anims)
                    or (
                        self._theme().kind == "neonflow"
                        and (self._mouse_lx >= 0 or self._neon_needs_frames(now))
                    )
                ):
                    # 睡到这张皮实际在画的帧率。节电时再收到 20 帧，避免降频后一帧画不完。
                    hz = power_save.frame_hz(self._present_hz if self._present_hz > 0 else FPS)
                    time.sleep(1.0 / min(FPS, hz))
                else:
                    # 无动画皮时 _paint 只在秒数变化才重绘，主循环没必要 60Hz 空转
                    time.sleep(1.0 / power_save.frame_hz(IDLE_FPS))
            except Exception as e:  # noqa: BLE001
                store.log_exception("loop", e)
                time.sleep(0.05)
        try:
            self._worklog_tick(force=True, flush=True)
        except Exception as e:  # noqa: BLE001
            store.log_exception("worklog-quit", e)
        self._persist_pos()
        self._persist_size()
        store.flush_pending(force=True)
        try:
            if self._trail is not None:
                self._trail.destroy()
        except Exception:
            pass
        self.win.destroy()
        if self._tk is not None:
            self._tk.destroy()


def _arg_path(flag: str) -> Path | None:
    argv = sys.argv[1:]
    if flag in argv:
        i = argv.index(flag)
        if i + 1 < len(argv) and argv[i + 1].strip():
            return Path(argv[i + 1].strip().strip('"'))
    return None


def main() -> None:
    sys.excepthook = lambda *args: store.append_log("".join(__import__("traceback").format_exception(*args)))
    updater.patch_legacy_proxy()
    try:
        WorkTimer().run()
    except Exception as e:  # noqa: BLE001
        store.log_exception("main", e)
        try:
            messagebox.showerror("下班倒计时", str(e))
        except Exception:
            pass


if __name__ == "__main__":
    main()
