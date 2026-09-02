"""透明下班倒计时：桌面置顶小窗，点一下设置今天下班时间。"""
from __future__ import annotations

import ctypes
import os
import ssl
import sys
import threading
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageFont

import ad_disguise
import backdrop
import flex_time
import layered_win
import ornaments
import schedules
import store
import themes
import updater
from version import APP_VERSION

FPS = 60
_LEGACY_SIZES = {"s": (248, 92), "m": (320, 118), "l": (400, 148)}


def _font(size: int) -> ImageFont.ImageFont:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("msyhbd.ttc", "msyh.ttc", "msyh.ttf", "simhei.ttf"):
        try:
            return ImageFont.truetype(str(windir / name), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _rgba_to_bgra(img: Image.Image) -> tuple[bytes, bytes]:
    w, h = img.size
    raw = img.tobytes("raw", "RGBA")
    bgra = bytearray(w * h * 4)
    mask = bytearray(w * h)
    for i in range(w * h):
        r = raw[i * 4 + 0]
        g = raw[i * 4 + 1]
        b = raw[i * 4 + 2]
        a = raw[i * 4 + 3]
        # 分层窗 alpha=0 的像素系统会点穿到后面的程序；整块区域至少留 1，肉眼看不出。
        if a < 1:
            a = 1
        bgra[i * 4 + 0] = (b * a) // 255
        bgra[i * 4 + 1] = (g * a) // 255
        bgra[i * 4 + 2] = (r * a) // 255
        bgra[i * 4 + 3] = a
        mask[i] = 255
    return bytes(bgra), bytes(mask)


def _place_dialog(dlg: tk.Toplevel, near: tuple[int, int] | None, *, min_w: int, min_h: int) -> None:
    """按内容自适应尺寸，避免高 DPI 下按钮被裁切。"""
    dlg.update_idletasks()
    w = max(min_w, dlg.winfo_reqwidth() + 24)
    h = max(min_h, dlg.winfo_reqheight() + 24)
    if near:
        dlg.geometry(f"{w}x{h}+{int(near[0])}+{int(near[1])}")
    else:
        dlg.geometry(f"{w}x{h}")


def _ask_offwork_setup(
    parent: tk.Tk | None,
    *,
    mode: str,
    start_preset: tuple[int, int] | None,
    off_preset: tuple[int, int] | None,
    near: tuple[int, int] | None = None,
) -> tuple[str, tuple[int, int]] | None:
    """统一设置下班：直接设点，或按到岗时间推算。返回 (mode, hm)。"""
    result: list[tuple[str, tuple[int, int]] | None] = [None]
    dlg = tk.Toplevel(parent)
    dlg.title("设置下班时间")
    dlg.resizable(False, False)
    dlg.attributes("-topmost", True)
    dlg.configure(bg="#1b1e26")
    try:
        dlg.lift()
        dlg.focus_force()
    except Exception:
        pass
    dlg.grab_set()

    init_mode = "flex" if mode == "flex" else "direct"
    mode_var = tk.StringVar(value=init_mode)
    sh, sm = start_preset if start_preset else (9, 0)
    oh, om = off_preset if off_preset else (18, 0)
    start_var = tk.StringVar(value="" if start_preset is None else f"{sh}:{sm:02d}")
    off_var = tk.StringVar(value="" if off_preset is None else f"{oh}:{om:02d}")
    tip = tk.StringVar()
    preview = tk.StringVar()

    tk.Label(
        dlg,
        text="怎么设置今天下班？",
        fg="#f4f6fb",
        bg="#1b1e26",
        font=("Microsoft YaHei UI", 13, "bold"),
    ).pack(pady=(16, 8), padx=18, anchor="w")

    radios = tk.Frame(dlg, bg="#1b1e26")
    radios.pack(padx=18, anchor="w")
    for value, label in (
        ("direct", "我知道下班几点（直接倒计时）"),
        ("flex", "按到岗时间推算（8:30–9:30 → 18:00–19:00）"),
    ):
        tk.Radiobutton(
            radios,
            text=label,
            variable=mode_var,
            value=value,
            fg="#e8ecf4",
            bg="#1b1e26",
            activebackground="#1b1e26",
            activeforeground="#e8ecf4",
            selectcolor="#2a3140",
            font=("Microsoft YaHei UI", 10),
            anchor="w",
            justify="left",
        ).pack(anchor="w", pady=2)

    tk.Label(
        dlg,
        textvariable=tip,
        fg="#9aa3b5",
        bg="#1b1e26",
        font=("Microsoft YaHei UI", 9),
        wraplength=360,
        justify="left",
    ).pack(padx=18, pady=(10, 4), anchor="w")

    entry = ttk.Entry(dlg, font=("Microsoft YaHei UI", 16), justify="center", width=14)
    entry.pack(pady=10, padx=18)

    tk.Label(dlg, textvariable=preview, fg="#7ec8ff", bg="#1b1e26", font=("Microsoft YaHei UI", 10)).pack(
        padx=18, anchor="w"
    )

    def current_var() -> tk.StringVar:
        return start_var if mode_var.get() == "flex" else off_var

    def sync_entry_from_mode(*_a) -> None:
        v = current_var()
        entry.configure(textvariable=v)
        if mode_var.get() == "flex":
            tip.set("填写今天几点到岗，自动按 9.5 小时推算下班点")
        else:
            tip.set("填写今天下班几点，例如 18:00（固定下班选这个）")
        refresh_preview()

    def refresh_preview(*_a) -> None:
        if mode_var.get() == "flex":
            parsed = flex_time.parse_start(start_var.get())
            if parsed is None:
                preview.set("请输入 8:30–9:30，例如 8.45 或 9:10")
                return
            ph, pm = flex_time.offwork_hm(*parsed)
            preview.set(f"推算下班：{flex_time.format_hm(ph, pm)}")
            return
        parsed = flex_time.parse_clock(off_var.get())
        if parsed is None:
            preview.set("请输入 0:00–23:59，例如 18:00")
            return
        preview.set(f"倒计时到 {flex_time.format_hm(*parsed)}")

    mode_var.trace_add("write", sync_entry_from_mode)
    start_var.trace_add("write", refresh_preview)
    off_var.trace_add("write", refresh_preview)
    sync_entry_from_mode()
    entry.select_range(0, tk.END)
    entry.focus_set()

    def ok() -> None:
        if mode_var.get() == "flex":
            parsed = flex_time.parse_start(start_var.get())
            if parsed is None:
                messagebox.showwarning(
                    "设置下班时间",
                    "到岗时间请填 8:30 到 9:30，例如 8.45 或 9:10",
                    parent=dlg,
                )
                return
            result[0] = ("flex", parsed)
        else:
            parsed = flex_time.parse_clock(off_var.get())
            if parsed is None:
                messagebox.showwarning(
                    "设置下班时间",
                    "下班时间请填 0:00 到 23:59，例如 18:00 或 18.30",
                    parent=dlg,
                )
                return
            result[0] = ("direct", parsed)
        dlg.destroy()

    def cancel() -> None:
        dlg.destroy()

    bar = tk.Frame(dlg, bg="#1b1e26")
    bar.pack(pady=(14, 16))
    tk.Button(
        bar,
        text="开始计时",
        command=ok,
        bg="#3d7eff",
        fg="white",
        activebackground="#5a92ff",
        activeforeground="white",
        relief="flat",
        font=("Microsoft YaHei UI", 10, "bold"),
        padx=18,
        pady=6,
    ).pack(side="left", padx=8)
    tk.Button(
        bar,
        text="取消",
        command=cancel,
        bg="#3a3f4b",
        fg="white",
        activebackground="#4a5160",
        activeforeground="white",
        relief="flat",
        font=("Microsoft YaHei UI", 10),
        padx=18,
        pady=6,
    ).pack(side="left", padx=8)
    dlg.bind("<Return>", lambda _e: ok())
    dlg.bind("<Escape>", lambda _e: cancel())
    _place_dialog(dlg, near, min_w=400, min_h=300)
    dlg.wait_window()
    return result[0]


class WorkTimer:
    def __init__(self) -> None:
        try:
            # Per-monitor v2，避免窗口画在 A、点击命中在 B
            ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        except Exception:
            try:
                ctypes.windll.user32.SetProcessDPIAware()
            except Exception:
                pass
        if updater.resume_pending_update():
            updater.force_exit_for_update()
        updater.cleanup_update_artifacts()
        self.cfg = store.load_config()
        schedules.ensure_fields(self.cfg)
        self.running = True
        self._menu_pos: tuple[int, int] | None = None
        self._need_dialog = False
        self._need_schedule_list = False
        self._tk: tk.Tk | None = None
        self._update_available = False
        self._last_pin_rotate = 0.0

        w, h = self._load_size()
        self._win_w, self._win_h = w, h
        ft, fb, fs = ornaments.layout_for(w, h)

        self.win = layered_win.LayeredPetWindow(w, h, "下班倒计时")
        self.win.set_left_click_handler(self._on_click)
        self.win.set_right_click_handler(self._request_menu)
        self.ad = ad_disguise.AdDisguise()
        self.ad.set_dismiss_handler(self._toggle_disguise)
        self._disguised = False
        self._esc_held = False

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
        self._last_key = ""
        self._surface = "dark"
        self._force_surface_sample = True
        self._wallpaper_token = backdrop.wallpaper_token()
        self._surface_hot_until = 0.0
        self._last_surface_sample = 0.0
        self._last_luma = None
        mode = str(self.cfg.get("display_mode") or "hms")
        self.cfg["display_mode"] = mode if mode in flex_time.DISPLAY_MODES else "hms"
        tid = str(self.cfg.get("theme") or themes.DEFAULT_THEME_ID)
        self.cfg["theme"] = tid
        try:
            ssl.create_default_context()
        except Exception:
            pass
        self.cfg["esc_disguise"] = bool(self.cfg.get("esc_disguise"))
        themes.refresh_async(self.cfg)
        self._silent_check_update()

    def _today(self) -> str:
        return datetime.now().strftime("%Y-%m-%d")

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

    def _has_target(self) -> bool:
        if str(self.cfg.get("start_date") or "") != self._today():
            return False
        if self._time_mode() == "direct":
            return isinstance(self.cfg.get("off_h"), int) and isinstance(self.cfg.get("off_m"), int)
        return self._has_start()

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
        store.save_config(self.cfg)
        self._last_key = ""
        self._force_surface_sample = True

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
        self._last_key = ""

    def _persist_size(self) -> None:
        if self.cfg.get("win_w") == self._win_w and self.cfg.get("win_h") == self._win_h:
            return
        self.cfg["win_w"] = self._win_w
        self.cfg["win_h"] = self._win_h
        store.save_config(self.cfg)

    def _refresh_surface(self, *, force: bool = False) -> None:
        """窗周+窗下采样；最小化/切前台会强制连采。"""
        theme = self._theme()
        if not theme.adaptive:
            return
        now = time.monotonic()
        token = backdrop.wallpaper_token()
        if token != self._wallpaper_token:
            self._wallpaper_token = token
            force = True
        if force or self._force_surface_sample:
            self._force_surface_sample = False
            self._surface_hot_until = now + 0.45
        hot = now < self._surface_hot_until
        if not force and not hot and now - self._last_surface_sample < 0.08:
            return
        self._last_surface_sample = now
        luma = backdrop.sample_luma_around(self.win.x, self.win.y, self._win_w, self._win_h)
        if luma is None:
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
                kind, info = updater.check_update(self.cfg)
                if kind == "available" and info is not None:
                    self._update_available = True
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True, name="silent-update").start()

    def _on_click(self, lx: int, ly: int) -> None:
        if self._disguised:
            return
        # 底部中间：打开日程列表；其余左键切换优先项 / 未设下班则打开向导
        if ly >= self._win_h - 22 and abs(lx - self._win_w // 2) <= 28:
            self._need_schedule_list = True
            return
        pins = self.cfg.get("pin_order") or []
        if isinstance(pins, list) and len(pins) >= 2:
            if schedules.cycle_active(self.cfg):
                store.save_config(self.cfg)
                self._last_key = ""
                self._last_pin_rotate = time.monotonic()
            return
        if not self._has_target() and not pins:
            self._need_dialog = True
            return
        if len(pins) == 1 or self._has_target():
            # 仅一项时点空白也打开列表，方便管理
            self._need_schedule_list = True

    def _esc_disguise_on(self) -> bool:
        return bool(self.cfg.get("esc_disguise"))

    def _set_esc_disguise(self, on: bool) -> None:
        self.cfg["esc_disguise"] = bool(on)
        store.save_config(self.cfg)
        if not on and self._disguised:
            self.ad.hide()
            self.win.show()
            self._disguised = False
            self._last_key = ""

    def _toggle_disguise(self) -> None:
        if not self._esc_disguise_on() and not self._disguised:
            return
        if self._disguised:
            self.ad.hide()
            self.win.show()
            self._disguised = False
            self._last_key = ""
            return
        self.win.hide()
        self.ad.show()
        self._disguised = True

    def _poll_esc(self) -> None:
        down = bool(layered_win.user32.GetAsyncKeyState(0x1B) & 0x8000)
        if down and not self._esc_held and self._esc_disguise_on():
            self._toggle_disguise()
        self._esc_held = down

    def _request_menu(self, sx: int, sy: int) -> None:
        if self._disguised:
            return
        self._menu_pos = (sx, sy)

    def _tk_root(self) -> tk.Tk:
        if self._tk is None:
            root = tk.Tk()
            root.withdraw()
            self._tk = root
        return self._tk

    def _dialog_near(self) -> tuple[int, int]:
        return (self.win.x, self.win.y + self._win_h + 8)

    def _open_setup_dialog(self) -> None:
        start_preset = self._start_hm()
        if self._time_mode() == "direct" and self._has_target():
            off_preset = self._off_hm()
        else:
            oh, om = self.cfg.get("off_h"), self.cfg.get("off_m")
            off_preset = (int(oh), int(om)) if isinstance(oh, int) and isinstance(om, int) else (18, 0)
        # 今天还没设过：默认「直接设下班点」，避免一上来就被弹性流程带偏
        mode = self._time_mode() if self._has_target() else "direct"
        picked = _ask_offwork_setup(
            self._tk_root(),
            mode=mode,
            start_preset=start_preset,
            off_preset=off_preset,
            near=self._dialog_near(),
        )
        if picked is None:
            return
        mode, hm = picked
        self.cfg["time_mode"] = mode
        self.cfg["start_date"] = self._today()
        if mode == "flex":
            self.cfg["start_h"], self.cfg["start_m"] = hm
        else:
            self.cfg["off_h"], self.cfg["off_m"] = hm
        schedules.ensure_fields(self.cfg)
        schedules.set_pinned(self.cfg, schedules.OFFWORK_ID, True)
        self.cfg["active_pin_id"] = schedules.OFFWORK_ID
        store.save_config(self.cfg)
        self._last_key = ""

    def _open_idle_dialog(self) -> None:
        self._open_setup_dialog()

    def _active_view(self, now: datetime) -> tuple[str, int, bool, bool]:
        """当前主界面项：(标题, 剩余秒, 是否到点, 是否空闲未设)。"""
        schedules.ensure_fields(self.cfg)
        aid = schedules.active_id(self.cfg)
        if aid is None:
            return "距离下班", 0, False, True
        if aid == schedules.OFFWORK_ID:
            off = self._off_hm()
            if off is None:
                return "距离下班", 0, False, True
            td = flex_time.remaining_to(now, off[0], off[1])
            total, done = flex_time.remaining_parts(td)
            title = "已经到点" if done else "下班"
            return title, total, done, False
        item = schedules.find_schedule(self.cfg, aid)
        if item is None:
            return "距离下班", 0, False, True
        left, done = schedules.schedule_remaining(item, now)
        title = str(item.get("title") or "日程")
        if done:
            title = f"{title} · 到点"
        return title, left, done, False

    def _ask_new_schedule(self) -> dict | None:
        result: list[dict | None] = [None]
        dlg = tk.Toplevel(self._tk_root())
        dlg.title("新增日程")
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        dlg.configure(bg="#1b1e26")
        try:
            dlg.lift()
            dlg.focus_force()
        except Exception:
            pass
        dlg.grab_set()
        kind_var = tk.StringVar(value="clock")
        title_var = tk.StringVar(value="")
        time_var = tk.StringVar(value="15:00")
        tip = tk.StringVar()

        tk.Label(dlg, text="新增日程", fg="#f4f6fb", bg="#1b1e26", font=("Microsoft YaHei UI", 13, "bold")).pack(
            pady=(14, 6), padx=16, anchor="w"
        )
        box = tk.Frame(dlg, bg="#1b1e26")
        box.pack(padx=16, anchor="w")
        for val, lab in (("clock", "到点时刻（今天几点）"), ("duration", "倒计时长（分钟）")):
            tk.Radiobutton(
                box,
                text=lab,
                variable=kind_var,
                value=val,
                fg="#e8ecf4",
                bg="#1b1e26",
                selectcolor="#2a3140",
                activebackground="#1b1e26",
                font=("Microsoft YaHei UI", 10),
            ).pack(anchor="w")
        tk.Label(dlg, text="名称", fg="#9aa3b5", bg="#1b1e26", font=("Microsoft YaHei UI", 9)).pack(
            padx=16, anchor="w", pady=(8, 0)
        )
        ttk.Entry(dlg, textvariable=title_var, font=("Microsoft YaHei UI", 12)).pack(padx=16, fill="x")
        tk.Label(dlg, textvariable=tip, fg="#9aa3b5", bg="#1b1e26", font=("Microsoft YaHei UI", 9)).pack(
            padx=16, anchor="w", pady=(8, 0)
        )
        ttk.Entry(dlg, textvariable=time_var, font=("Microsoft YaHei UI", 14), justify="center").pack(
            padx=16, pady=8, fill="x"
        )

        def sync(*_a) -> None:
            if kind_var.get() == "clock":
                tip.set("例如 15:00 / 15.30")
                if not time_var.get().strip():
                    time_var.set("15:00")
            else:
                tip.set("例如 25（表示 25 分钟）")
                if not time_var.get().strip() or ":" in time_var.get():
                    time_var.set("25")

        kind_var.trace_add("write", sync)
        sync()

        def ok() -> None:
            name = title_var.get().strip() or ("日程" if kind_var.get() == "clock" else "倒计时")
            if kind_var.get() == "clock":
                hm = flex_time.parse_clock(time_var.get())
                if hm is None:
                    messagebox.showwarning("新增日程", "请输入今天的时刻，例如 15:00", parent=dlg)
                    return
                result[0] = schedules.new_clock(name, *hm)
            else:
                raw = time_var.get().strip()
                try:
                    mins = int(float(raw))
                except ValueError:
                    messagebox.showwarning("新增日程", "请输入分钟数，例如 25", parent=dlg)
                    return
                if mins < 1 or mins > 24 * 60:
                    messagebox.showwarning("新增日程", "时长请在 1–1440 分钟", parent=dlg)
                    return
                result[0] = schedules.new_duration(name, mins)
            dlg.destroy()

        def cancel() -> None:
            dlg.destroy()

        bar = tk.Frame(dlg, bg="#1b1e26")
        bar.pack(pady=12)
        tk.Button(bar, text="开始倒计时", command=ok, bg="#3d7eff", fg="white", relief="flat", padx=14, pady=5).pack(
            side="left", padx=6
        )
        tk.Button(bar, text="取消", command=cancel, bg="#3a3f4b", fg="white", relief="flat", padx=14, pady=5).pack(
            side="left", padx=6
        )
        dlg.bind("<Return>", lambda _e: ok())
        dlg.bind("<Escape>", lambda _e: cancel())
        _place_dialog(dlg, self._dialog_near(), min_w=360, min_h=280)
        dlg.wait_window()
        return result[0]

    def _open_schedule_list(self) -> None:
        schedules.ensure_fields(self.cfg)
        root = self._tk_root()
        dlg = tk.Toplevel(root)
        dlg.title("日程")
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        dlg.configure(bg="#1b1e26")
        try:
            dlg.lift()
            dlg.focus_force()
        except Exception:
            pass
        near = self._dialog_near()
        dlg.geometry(f"420x360+{near[0]}+{near[1]}")

        head = tk.Frame(dlg, bg="#1b1e26")
        head.pack(fill="x", padx=12, pady=(12, 4))
        tk.Label(head, text="日程列表", fg="#f4f6fb", bg="#1b1e26", font=("Microsoft YaHei UI", 12, "bold")).pack(
            side="left"
        )
        rotate_var = tk.BooleanVar(value=bool(self.cfg.get("auto_rotate_pins")))

        def on_rotate() -> None:
            self.cfg["auto_rotate_pins"] = bool(rotate_var.get())
            store.save_config(self.cfg)

        tk.Checkbutton(
            head,
            text="自动轮播",
            variable=rotate_var,
            command=on_rotate,
            fg="#c8d0dc",
            bg="#1b1e26",
            selectcolor="#2a3140",
            activebackground="#1b1e26",
            font=("Microsoft YaHei UI", 9),
        ).pack(side="right")

        canvas = tk.Canvas(dlg, bg="#1b1e26", highlightthickness=0, height=240)
        scroll = ttk.Scrollbar(dlg, orient="vertical", command=canvas.yview)
        rows = tk.Frame(canvas, bg="#1b1e26")
        rows.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=rows, anchor="nw")
        canvas.configure(yscrollcommand=scroll.set)
        canvas.pack(side="left", fill="both", expand=True, padx=(12, 0), pady=4)
        scroll.pack(side="right", fill="y", padx=(0, 8), pady=4)

        def rebuild() -> None:
            for w in rows.winfo_children():
                w.destroy()
            now = datetime.now()
            items: list[tuple[str, str, str]] = []
            # offwork
            if self._has_target():
                off = self._off_hm()
                assert off is not None
                td = flex_time.remaining_to(now, off[0], off[1])
                total, done = flex_time.remaining_parts(td)
                label = "已到点" if done else flex_time.format_remaining(total, self._display_mode())
                items.append((schedules.OFFWORK_ID, "下班", label))
            else:
                items.append((schedules.OFFWORK_ID, "下班（未设置）", "—"))
            for s in self.cfg.get("schedules") or []:
                if not isinstance(s, dict) or not s.get("id"):
                    continue
                sid = str(s["id"])
                left, done = schedules.schedule_remaining(s, now)
                label = "已到点" if done else flex_time.format_remaining(left, self._display_mode())
                items.append((sid, str(s.get("title") or "日程"), label))

            for sid, title, label in items:
                row = tk.Frame(rows, bg="#242833")
                row.pack(fill="x", pady=3, padx=4)
                pinned = schedules.is_pinned(self.cfg, sid)

                def focus(s=sid) -> None:
                    if s == schedules.OFFWORK_ID and not self._has_target():
                        dlg.destroy()
                        self._open_setup_dialog()
                        return
                    if not schedules.is_pinned(self.cfg, s):
                        ok, msg = schedules.set_pinned(self.cfg, s, True)
                        if not ok:
                            messagebox.showinfo("优先显示", msg, parent=dlg)
                            return
                    self.cfg["active_pin_id"] = s
                    store.save_config(self.cfg)
                    self._last_key = ""
                    dlg.destroy()

                tk.Button(
                    row,
                    text=f"{title}  {label}",
                    command=focus,
                    anchor="w",
                    bg="#242833",
                    fg="#e8ecf4",
                    relief="flat",
                    font=("Microsoft YaHei UI", 10),
                    padx=8,
                ).pack(side="left", fill="x", expand=True)

                pin_var = tk.BooleanVar(value=pinned)

                def toggle(s=sid, v=pin_var) -> None:
                    ok, msg = schedules.set_pinned(self.cfg, s, bool(v.get()))
                    if not ok:
                        v.set(False)
                        messagebox.showinfo("优先显示", msg, parent=dlg)
                        return
                    if s == schedules.OFFWORK_ID and not self._has_target() and v.get():
                        # 允许钉未设置的下班，点开主界面会提示设置
                        pass
                    store.save_config(self.cfg)
                    self._last_key = ""
                    rebuild()

                tk.Checkbutton(
                    row,
                    text="优先",
                    variable=pin_var,
                    command=toggle,
                    fg="#9aa3b5",
                    bg="#242833",
                    selectcolor="#2a3140",
                    activebackground="#242833",
                    font=("Microsoft YaHei UI", 9),
                ).pack(side="right", padx=4)

                if sid != schedules.OFFWORK_ID:

                    def drop(s=sid) -> None:
                        if messagebox.askyesno("删除日程", "确定删除这项日程？", parent=dlg):
                            schedules.remove_schedule(self.cfg, s)
                            store.save_config(self.cfg)
                            self._last_key = ""
                            rebuild()

                    tk.Button(
                        row,
                        text="删",
                        command=drop,
                        bg="#3a3f4b",
                        fg="white",
                        relief="flat",
                        font=("Microsoft YaHei UI", 9),
                        padx=6,
                    ).pack(side="right", padx=4)

        def add() -> None:
            item = self._ask_new_schedule()
            if item is None:
                return
            schedules.add_schedule(self.cfg, item)
            ok, msg = schedules.set_pinned(self.cfg, item["id"], True)
            if not ok:
                messagebox.showinfo("优先显示", msg + "\n日程已添加，可稍后手动优先。", parent=dlg)
            else:
                self.cfg["active_pin_id"] = item["id"]
            store.save_config(self.cfg)
            self._last_key = ""
            rebuild()

        foot = tk.Frame(dlg, bg="#1b1e26")
        foot.pack(fill="x", padx=12, pady=10)
        tk.Button(
            foot,
            text="新增日程",
            command=add,
            bg="#3d7eff",
            fg="white",
            relief="flat",
            font=("Microsoft YaHei UI", 10, "bold"),
            padx=14,
            pady=5,
        ).pack(side="left")
        tk.Button(
            foot,
            text="关闭",
            command=dlg.destroy,
            bg="#3a3f4b",
            fg="white",
            relief="flat",
            padx=12,
            pady=5,
        ).pack(side="right")
        rebuild()
        dlg.wait_window()

    def _handle_menu(self, sx: int, sy: int) -> None:
        op = self.win.popup_menu(
            sx,
            sy,
            self._display_mode(),
            self._theme().id,
            esc_disguise=self._esc_disguise_on(),
            update_available=self._update_available,
        )
        if op == "quit":
            self.running = False
        elif op == "update":
            self._check_update()
        elif op in ("set_time", "set_off"):
            self._open_setup_dialog()
        elif op == "toggle_esc_disguise":
            self._set_esc_disguise(not self._esc_disguise_on())
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

    def _check_update(self) -> None:
        self.cfg = store.load_config()
        root = self._tk_root()
        near = self._dialog_near()
        dlg = tk.Toplevel(root)
        dlg.title("检查更新")
        dlg.resizable(False, False)
        dlg.attributes("-topmost", True)
        dlg.configure(bg="#1b1e26")
        dlg.geometry(f"380x210+{near[0]}+{near[1]}")
        try:
            dlg.lift()
            dlg.focus_force()
        except Exception:
            pass

        status = tk.StringVar(value="正在连接 GitCode…")
        detail = tk.StringVar(value=f"当前版本 {APP_VERSION}")
        tk.Label(dlg, textvariable=status, fg="#f4f6fb", bg="#1b1e26", font=("Microsoft YaHei UI", 11, "bold")).pack(
            pady=(16, 6), padx=16, anchor="w"
        )
        detail_lbl = tk.Label(
            dlg, textvariable=detail, fg="#9aa3b5", bg="#1b1e26", font=("Microsoft YaHei UI", 9),
            justify="left", wraplength=340, anchor="w",
        )
        detail_lbl.pack(padx=16, anchor="w")
        bar = ttk.Progressbar(dlg, mode="indeterminate", length=340)
        bar.pack(pady=(14, 8), padx=16)
        bar.start(12)
        btn_row = tk.Frame(dlg, bg="#1b1e26")
        btn_row.pack(side="bottom", pady=(4, 16))

        state: dict = {"closed": False, "phase": "check", "yes": None, "pending_dl": None}

        def alive() -> bool:
            return not state["closed"] and bool(dlg.winfo_exists())

        def on_close() -> None:
            state["closed"] = True
            try:
                bar.stop()
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass

        dlg.protocol("WM_DELETE_WINDOW", on_close)

        def finish_idle(msg: str, sub: str = "", *, error: bool = False) -> None:
            if not alive():
                return
            state["phase"] = "idle"
            bar.stop()
            bar.configure(mode="determinate", value=0 if error else 100)
            status.set(msg)
            detail.set(sub or "可以关闭窗口")

        def start_download(info: updater.ReleaseInfo) -> None:
            if not alive():
                return
            if updater.current_exe_path() is None:
                finish_idle("当前是源码运行", "请重新打包 exe，或手动下载 Release 附件。", error=True)
                return
            state["phase"] = "download"
            status.set(f"正在下载 {info.version}…")
            detail.set("准备下载安装包")
            bar.stop()
            bar.configure(mode="determinate", maximum=100, value=0)
            try:
                bar.pack(pady=(14, 8), padx=16, before=btn_row)
            except Exception:
                bar.pack(pady=(14, 8), padx=16)
            if state["yes"] is not None:
                try:
                    state["yes"].pack_forget()
                except Exception:
                    pass

            done_box: list[object] = []

            def on_progress(done: int, total: int) -> None:
                done_box.clear()
                done_box.append(("progress", done, total))

            def worker_dl() -> None:
                try:
                    path = updater.download_update(info, self.cfg, on_progress=on_progress)
                    done_box.clear()
                    done_box.append(("ok", path))
                except Exception as e:  # noqa: BLE001
                    done_box.clear()
                    done_box.append(("err", str(e)))

            threading.Thread(target=worker_dl, daemon=True, name="update-download").start()
            while alive() and state["phase"] == "download":
                if done_box:
                    kind = done_box[0][0]
                    if kind == "progress":
                        _k, done, total = done_box.pop(0)
                        if total > 0:
                            pct = max(0, min(100, int(done * 100 / total)))
                            bar.configure(value=pct)
                            detail.set(f"{done / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MB（{pct}%）")
                        else:
                            detail.set(f"已下载 {done / (1024 * 1024):.1f} MB")
                    elif kind == "ok":
                        path = done_box[0][1]
                        status.set("正在安装并重启…")
                        detail.set("替换完成后会自动重新打开")
                        bar.configure(value=100)
                        dlg.update_idletasks()
                        try:
                            updater.apply_update_and_restart(path)  # type: ignore[arg-type]
                            updater.force_exit_for_update()
                        except Exception as e:  # noqa: BLE001
                            finish_idle("更新失败", str(e), error=True)
                        return
                    else:
                        finish_idle("下载失败", str(done_box[0][1]), error=True)
                        return
                try:
                    dlg.update()
                except Exception:
                    state["closed"] = True
                    return
                time.sleep(0.03)

        def show_available(info: updater.ReleaseInfo) -> None:
            if not alive():
                return
            state["phase"] = "ask"
            bar.stop()
            try:
                bar.pack_forget()
            except Exception:
                pass
            body = (info.body or "").strip().replace("\n", " ")
            tip = body[:90] + ("…" if len(body) > 90 else "")
            status.set(f"发现新版本 {info.version}")
            detail.set(tip or f"标签 {info.tag}")
            dlg.geometry(f"380x200+{dlg.winfo_x()}+{dlg.winfo_y()}")

            def go() -> None:
                state["pending_dl"] = info

            yes = tk.Button(
                btn_row,
                text="下载并更新",
                width=16,
                height=1,
                bg="#3d7eff",
                fg="white",
                activebackground="#5a92ff",
                activeforeground="white",
                relief="flat",
                font=("Microsoft YaHei UI", 10, "bold"),
                command=go,
            )
            state["yes"] = yes
            yes.pack(ipady=4)

        result_box: list[tuple[str, updater.ReleaseInfo | None]] = []

        def worker_check() -> None:
            try:
                result_box.append(updater.check_update(self.cfg))
            except Exception as e:  # noqa: BLE001
                result_box.append((f"error:{e}", None))

        threading.Thread(target=worker_check, daemon=True, name="update-check").start()
        # 不用 wait_window：和 Win32 主循环混用时 after 回调可能一直不跑，表现为「一直连接中」
        while alive() and state["phase"] == "check":
            if result_box:
                st, info = result_box[0]
                if st == "no_repo":
                    finish_idle("还没配置仓库", f"请写入 {store.config_path()} 的 gitcode_repo", error=True)
                elif st.startswith("error:"):
                    finish_idle("检查失败", st[6:], error=True)
                elif st == "latest":
                    finish_idle("已是最新版", f"当前 {APP_VERSION} · 远端 {info.version if info else '-'}")
                elif st == "available" and info is not None:
                    show_available(info)
                else:
                    finish_idle("检查结束", "没有可用更新", error=True)
                break
            try:
                dlg.update()
            except Exception:
                state["closed"] = True
                break
            time.sleep(0.03)

        # 询问/结果阶段：泵事件直到关闭，或点了下载
        while alive() and state["phase"] in ("ask", "idle"):
            pending = state.get("pending_dl")
            if pending is not None:
                state["pending_dl"] = None
                start_download(pending)
                break
            try:
                dlg.update()
            except Exception:
                break
            time.sleep(0.03)

    def _paint(self) -> None:
        try:
            now = datetime.now()
            mode = self._display_mode()
            base = self._theme()
            surface = self._surface if base.adaptive else "dark"
            theme = themes.resolve_for_surface(base, surface)
            w, h = self._win_w, self._win_h
            phase = time.monotonic()
            title, total, done, idle = self._active_view(now)
            sub = ""
            if idle:
                big = "点我开始"
                accent = theme.idle
                key = f"idle-{mode}-{theme.id}-{theme.fill}-{surface}-{w}x{h}"
            elif done:
                big = flex_time.format_remaining(0, mode)
                accent = theme.done
                key = f"done-{mode}-{theme.id}-{title}-{theme.fill}-{surface}-{w}x{h}"
            else:
                big = flex_time.format_remaining(total, mode)
                mins = total // 60
                accent = theme.warn if mins < 30 else theme.big
                key = f"run-{mode}-{theme.id}-{title}-{big}-{theme.fill}-{surface}-{w}x{h}"
            aid = schedules.active_id(self.cfg) or "-"
            idx, n = schedules.pin_index(self.cfg)
            key = f"{key}-{aid}-{idx}/{n}"
            if ornaments.has_skin(theme.kind):
                key = f"{key}-a{int(phase * 24)}"

            if key == self._last_key:
                return

            img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
            themes.paint_card(
                img,
                w,
                h,
                theme,
                title if not idle else "距离下班",
                big,
                sub,
                accent,
                self._font_title,
                self._font_big,
                self._font_sub,
            )
            chev = theme.outline if theme.outline[3] > 20 else (255, 255, 255, 70)
            if (0.2126 * accent[0] + 0.7152 * accent[1] + 0.0722 * accent[2]) < 140:
                chev = (40, 44, 52, 90)
            dots = (idx, n) if n >= 2 and bool(self.cfg.get("auto_rotate_pins")) else (0, 0)
            ornaments.paint_chevron(img, w, h, color=chev, pin_dots=dots)
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
        last_save = time.monotonic()
        was_dragging = False
        was_resizing = False
        while self.running and not self.win.closed:
            try:
                self.win.pump()
                self.ad.pump()
                self._poll_esc()
                if self._disguised:
                    time.sleep(0.008)
                    continue
                if self._menu_pos is not None:
                    sx, sy = self._menu_pos
                    self._menu_pos = None
                    self._handle_menu(sx, sy)
                if self._need_dialog:
                    self._need_dialog = False
                    self._open_idle_dialog()
                if self._need_schedule_list:
                    self._need_schedule_list = False
                    self._open_schedule_list()
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
                if resizing:
                    was_resizing = True
                    self._sync_layout_from_window()
                    self._paint()
                    time.sleep(0.001)
                    continue
                if dragging:
                    was_dragging = True
                    self._refresh_surface(force=True)
                    self._paint()
                    time.sleep(0.001)
                    continue
                if was_resizing or resized:
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
                if schedules.rotate_tick(self.cfg, self._last_pin_rotate, now_m):
                    self._last_pin_rotate = now_m
                    store.save_config(self.cfg)
                    self._last_key = ""
                self._refresh_surface()
                self._paint()
                now = time.monotonic()
                if now - last_save > 1.5:
                    self._persist_pos()
                    last_save = now
                if now < self._surface_hot_until:
                    time.sleep(0.001)
                else:
                    time.sleep(1.0 / FPS)
            except Exception as e:  # noqa: BLE001
                store.log_exception("loop", e)
                time.sleep(0.05)
        self._persist_pos()
        self._persist_size()
        self.ad.destroy()
        self.win.destroy()
        if self._tk is not None:
            self._tk.destroy()


def main() -> None:
    sys.excepthook = lambda *args: store.append_log("".join(__import__("traceback").format_exception(*args)))
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
