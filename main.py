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


_CARD_BG = "#161a22"
_CARD_FG = "#f0f3f8"
_CARD_MUTED = "#8b93a5"
_CARD_ACCENT = "#3d7eff"
_CARD_BTN = "#2a3140"


def _place_dialog(dlg: tk.Toplevel, near: tuple[int, int] | None, *, min_w: int, min_h: int) -> None:
    """按内容自适应尺寸，避免高 DPI 下按钮被裁切。"""
    dlg.update_idletasks()
    w = max(min_w, dlg.winfo_reqwidth() + 24)
    h = max(min_h, dlg.winfo_reqheight() + 24)
    if near:
        dlg.geometry(f"{w}x{h}+{int(near[0])}+{int(near[1])}")
    else:
        dlg.geometry(f"{w}x{h}")


def _round_card(dlg: tk.Toplevel, radius: int = 16) -> None:
    """无边框卡片裁成圆角，避免系统窗口矩形感。"""
    dlg.update_idletasks()
    try:
        hwnd = int(dlg.winfo_id())
        w = max(1, int(dlg.winfo_width()))
        h = max(1, int(dlg.winfo_height()))
        hrgn = ctypes.windll.gdi32.CreateRoundRectRgn(0, 0, w + 1, h + 1, radius * 2, radius * 2)
        ctypes.windll.user32.SetWindowRgn(hwnd, hrgn, True)
    except Exception:
        pass


def _card_dialog(
    parent: tk.Tk | None,
    *,
    near: tuple[int, int] | None,
    width: int,
    height: int,
) -> tk.Toplevel:
    """无边框、置顶、深色圆角卡片（贴近主界面，不像系统窗口）。"""
    dlg = tk.Toplevel(parent)
    dlg.overrideredirect(True)
    dlg.resizable(False, False)
    dlg.attributes("-topmost", True)
    dlg.configure(bg=_CARD_BG)
    if near:
        dlg.geometry(f"{width}x{height}+{int(near[0])}+{int(near[1])}")
    else:
        dlg.geometry(f"{width}x{height}")
    try:
        dlg.lift()
        dlg.focus_force()
    except Exception:
        pass
    _round_card(dlg)
    # 拖拽移动
    state = {"x": 0, "y": 0}

    def start(e) -> None:
        state["x"], state["y"] = e.x_root, e.y_root

    def drag(e) -> None:
        dx, dy = e.x_root - state["x"], e.y_root - state["y"]
        state["x"], state["y"] = e.x_root, e.y_root
        dlg.geometry(f"+{dlg.winfo_x() + dx}+{dlg.winfo_y() + dy}")

    dlg.bind("<ButtonPress-1>", start)
    dlg.bind("<B1-Motion>", drag)
    return dlg


def _run_card_modal(dlg: tk.Toplevel, win: layered_win.LayeredPetWindow | None = None) -> None:
    """与分层窗泵兼容的模态循环；调用方 destroy 即结束。"""
    dlg.bind("<Escape>", lambda _e: dlg.destroy())
    while True:
        try:
            if not dlg.winfo_exists():
                break
            dlg.update()
            if win is not None:
                win.pump()
        except Exception:
            break
        time.sleep(0.02)


def _ask_offwork_setup(
    parent: tk.Tk | None,
    *,
    mode: str,
    start_preset: tuple[int, int] | None,
    off_preset: tuple[int, int] | None,
    near: tuple[int, int] | None = None,
    win: layered_win.LayeredPetWindow | None = None,
) -> tuple[str, tuple[int, int]] | None:
    """统一设置下班：卡片风无边框。返回 (mode, hm)。"""
    result: list[tuple[str, tuple[int, int]] | None] = [None]
    dlg = _card_dialog(parent, near=near, width=380, height=320)
    init_mode = "flex" if mode == "flex" else "direct"
    mode_var = tk.StringVar(value=init_mode)
    sh, sm = start_preset if start_preset else (9, 0)
    oh, om = off_preset if off_preset else (18, 0)
    start_var = tk.StringVar(value="" if start_preset is None else f"{sh}:{sm:02d}")
    off_var = tk.StringVar(value="" if off_preset is None else f"{oh}:{om:02d}")
    tip = tk.StringVar()
    preview = tk.StringVar()

    tk.Label(dlg, text="设置下班时间", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold")).pack(
        pady=(18, 8), padx=20, anchor="w"
    )
    radios = tk.Frame(dlg, bg=_CARD_BG)
    radios.pack(padx=20, anchor="w")
    for value, label in (
        ("direct", "我知道下班几点"),
        ("flex", "按到岗时间推算（8:30–9:30）"),
    ):
        tk.Radiobutton(
            radios,
            text=label,
            variable=mode_var,
            value=value,
            fg=_CARD_FG,
            bg=_CARD_BG,
            activebackground=_CARD_BG,
            activeforeground=_CARD_FG,
            selectcolor=_CARD_BTN,
            font=("Microsoft YaHei UI", 10),
            anchor="w",
        ).pack(anchor="w", pady=1)
    tk.Label(dlg, textvariable=tip, fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
        padx=20, pady=(10, 4), anchor="w"
    )
    entry = tk.Entry(
        dlg,
        font=("Microsoft YaHei UI", 16),
        justify="center",
        bg="#222733",
        fg=_CARD_FG,
        insertbackground=_CARD_FG,
        relief="flat",
        width=14,
    )
    entry.pack(pady=8, ipady=6)

    tk.Label(dlg, textvariable=preview, fg="#7ec8ff", bg=_CARD_BG, font=("Microsoft YaHei UI", 10)).pack(
        padx=20, anchor="w"
    )
    err = tk.StringVar(value="")
    tk.Label(dlg, textvariable=err, fg="#ff8b8b", bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
        padx=20, pady=(6, 0), anchor="w"
    )

    def current_var() -> tk.StringVar:
        return start_var if mode_var.get() == "flex" else off_var

    def sync_entry_from_mode(*_a) -> None:
        entry.configure(textvariable=current_var())
        tip.set(
            "到岗时间，例如 8.45 / 9:10"
            if mode_var.get() == "flex"
            else "下班时刻，例如 18:00"
        )
        refresh_preview()

    def refresh_preview(*_a) -> None:
        if mode_var.get() == "flex":
            parsed = flex_time.parse_start(start_var.get())
            if parsed is None:
                preview.set("请输入 8:30–9:30")
                return
            ph, pm = flex_time.offwork_hm(*parsed)
            preview.set(f"推算下班 {flex_time.format_hm(ph, pm)}")
            return
        parsed = flex_time.parse_clock(off_var.get())
        if parsed is None:
            preview.set("请输入 0:00–23:59")
            return
        preview.set(f"倒计时到 {flex_time.format_hm(*parsed)}")

    mode_var.trace_add("write", sync_entry_from_mode)
    start_var.trace_add("write", refresh_preview)
    off_var.trace_add("write", refresh_preview)
    sync_entry_from_mode()
    entry.focus_set()

    def ok() -> None:
        err.set("")
        if mode_var.get() == "flex":
            parsed = flex_time.parse_start(start_var.get())
            if parsed is None:
                err.set("到岗请填 8:30–9:30")
                return
            result[0] = ("flex", parsed)
        else:
            parsed = flex_time.parse_clock(off_var.get())
            if parsed is None:
                err.set("请填合法时刻，例如 18:00")
                return
            result[0] = ("direct", parsed)
        dlg.destroy()

    bar = tk.Frame(dlg, bg=_CARD_BG)
    bar.pack(side="bottom", pady=16)
    tk.Button(
        bar, text="开始计时", command=ok, bg=_CARD_ACCENT, fg="white", relief="flat",
        font=("Microsoft YaHei UI", 10, "bold"), padx=16, pady=6,
    ).pack(side="left", padx=6)
    tk.Button(
        bar, text="取消", command=dlg.destroy, bg=_CARD_BTN, fg="white", relief="flat",
        font=("Microsoft YaHei UI", 10), padx=16, pady=6,
    ).pack(side="left", padx=6)
    dlg.bind("<Return>", lambda _e: ok())
    _run_card_modal(dlg, win)
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
        # 仅倒三角热区打开日程列表
        if ornaments.chevron_hit(lx, ly, self._win_w, self._win_h):
            self._need_schedule_list = True
            return
        pins = self.cfg.get("pin_order") or []
        if isinstance(pins, list) and len(pins) >= 2:
            if schedules.cycle_active(self.cfg):
                store.save_config(self.cfg)
                self._last_key = ""
                self._last_pin_rotate = time.monotonic()
            return
        if not self._has_target():
            self._need_dialog = True
            return

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
            win=self.win,
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
            title = "已经到点" if done else "距离您下班还有"
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
        now = datetime.now()
        dlg = _card_dialog(self._tk_root(), near=self._dialog_near(), width=380, height=360)
        kind_var = tk.StringVar(value="clock")
        title_var = tk.StringVar(value="")
        time_var = tk.StringVar(value="15:00")
        y_var = tk.StringVar(value=str(now.year))
        m_var = tk.StringVar(value=str(now.month))
        d_var = tk.StringVar(value=str(now.day))
        tip = tk.StringVar()

        tk.Label(dlg, text="新增日程", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold")).pack(
            pady=(16, 6), padx=18, anchor="w"
        )
        box = tk.Frame(dlg, bg=_CARD_BG)
        box.pack(padx=18, anchor="w")
        for val, lab in (("clock", "指定日期+时刻"), ("duration", "倒计时长（分钟）")):
            tk.Radiobutton(
                box, text=lab, variable=kind_var, value=val, fg=_CARD_FG, bg=_CARD_BG,
                selectcolor=_CARD_BTN, activebackground=_CARD_BG, font=("Microsoft YaHei UI", 10),
            ).pack(anchor="w")

        tk.Label(dlg, text="名称", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
            padx=18, anchor="w", pady=(8, 0)
        )
        tk.Entry(
            dlg, textvariable=title_var, font=("Microsoft YaHei UI", 12), bg="#222733", fg=_CARD_FG,
            insertbackground=_CARD_FG, relief="flat",
        ).pack(padx=18, fill="x", ipady=5)

        date_row = tk.Frame(dlg, bg=_CARD_BG)
        date_row.pack(padx=18, pady=(10, 0), anchor="w")
        tk.Label(date_row, text="日期", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(side="left")
        for var, lab, w in ((y_var, "年", 5), (m_var, "月", 3), (d_var, "日", 3)):
            tk.Entry(
                date_row, textvariable=var, width=w, justify="center", font=("Microsoft YaHei UI", 11),
                bg="#222733", fg=_CARD_FG, insertbackground=_CARD_FG, relief="flat",
            ).pack(side="left", padx=(6, 2), ipady=3)
            tk.Label(date_row, text=lab, fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 8)).pack(side="left")

        tk.Label(dlg, textvariable=tip, fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
            padx=18, anchor="w", pady=(10, 0)
        )
        tk.Entry(
            dlg, textvariable=time_var, font=("Microsoft YaHei UI", 14), justify="center",
            bg="#222733", fg=_CARD_FG, insertbackground=_CARD_FG, relief="flat",
        ).pack(padx=18, pady=8, fill="x", ipady=6)

        def sync(*_a) -> None:
            if kind_var.get() == "clock":
                tip.set("时刻，例如 15:00")
                date_row.pack(padx=18, pady=(10, 0), anchor="w")
                if ":" not in time_var.get() and "." not in time_var.get():
                    time_var.set("15:00")
            else:
                tip.set("分钟数，例如 25")
                date_row.pack_forget()
                if ":" in time_var.get() or "." in time_var.get():
                    time_var.set("25")

        kind_var.trace_add("write", sync)
        sync()

        err = tk.StringVar(value="")
        tk.Label(dlg, textvariable=err, fg="#ff8b8b", bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
            padx=18, anchor="w"
        )

        def ok() -> None:
            err.set("")
            name = title_var.get().strip() or ("日程" if kind_var.get() == "clock" else "倒计时")
            if kind_var.get() == "clock":
                hm = flex_time.parse_clock(time_var.get())
                if hm is None:
                    err.set("请输入时刻，例如 15:00")
                    return
                try:
                    y, m, d = int(y_var.get()), int(m_var.get()), int(d_var.get())
                    datetime(y, m, d)
                except ValueError:
                    err.set("日期无效")
                    return
                result[0] = schedules.new_clock(name, *hm, date=f"{y:04d}-{m:02d}-{d:02d}")
            else:
                try:
                    mins = int(float(time_var.get().strip()))
                except ValueError:
                    err.set("请输入分钟数")
                    return
                if mins < 1 or mins > 24 * 60:
                    err.set("时长 1–1440 分钟")
                    return
                result[0] = schedules.new_duration(name, mins)
            dlg.destroy()

        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", pady=14)
        tk.Button(
            bar, text="开始倒计时", command=ok, bg=_CARD_ACCENT, fg="white", relief="flat",
            font=("Microsoft YaHei UI", 10, "bold"), padx=14, pady=6,
        ).pack(side="left", padx=6)
        tk.Button(
            bar, text="取消", command=dlg.destroy, bg=_CARD_BTN, fg="white", relief="flat",
            font=("Microsoft YaHei UI", 10), padx=14, pady=6,
        ).pack(side="left", padx=6)
        dlg.bind("<Return>", lambda _e: ok())
        _run_card_modal(dlg, self.win)
        return result[0]

    def _open_schedule_list(self) -> None:
        schedules.ensure_fields(self.cfg)
        dlg = _card_dialog(self._tk_root(), near=self._dialog_near(), width=390, height=420)
        closed = {"v": False}

        def close() -> None:
            closed["v"] = True
            try:
                dlg.destroy()
            except Exception:
                pass

        head = tk.Frame(dlg, bg=_CARD_BG)
        head.pack(side="top", fill="x", padx=14, pady=(14, 6))
        tk.Label(head, text="日程", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold")).pack(side="left")
        rotate_var = tk.BooleanVar(value=bool(self.cfg.get("auto_rotate_pins")))

        def on_rotate() -> None:
            self.cfg["auto_rotate_pins"] = bool(rotate_var.get())
            store.save_config(self.cfg)
            self._last_key = ""

        tk.Checkbutton(
            head, text="自动轮播", variable=rotate_var, command=on_rotate, fg=_CARD_MUTED, bg=_CARD_BG,
            selectcolor=_CARD_BTN, activebackground=_CARD_BG, font=("Microsoft YaHei UI", 9),
        ).pack(side="right")

        foot = tk.Frame(dlg, bg=_CARD_BG)
        foot.pack(side="bottom", fill="x", padx=14, pady=(8, 14))
        mid = tk.Frame(dlg, bg=_CARD_BG)
        mid.pack(side="top", fill="both", expand=True, padx=14, pady=4)

        hint = tk.StringVar(value="")
        canvas = tk.Canvas(mid, bg=_CARD_BG, highlightthickness=0, bd=0)
        rows = tk.Frame(canvas, bg=_CARD_BG)
        win_id = canvas.create_window((0, 0), window=rows, anchor="nw")

        def _sync(_e=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))
            canvas.itemconfigure(win_id, width=max(1, canvas.winfo_width()))

        def _wheel(e) -> None:
            canvas.yview_scroll(int(-1 * (e.delta / 120)), "units")

        def _bind_wheel(_e=None) -> None:
            canvas.bind_all("<MouseWheel>", _wheel)

        def _unbind_wheel(_e=None) -> None:
            canvas.unbind_all("<MouseWheel>")

        rows.bind("<Configure>", _sync)
        canvas.bind("<Configure>", _sync)
        canvas.bind("<Enter>", _bind_wheel)
        canvas.bind("<Leave>", _unbind_wheel)
        canvas.pack(side="left", fill="both", expand=True)

        def rebuild() -> None:
            for child in rows.winfo_children():
                child.destroy()
            now = datetime.now()
            items: list[tuple[str, str, str, str, bool]] = []
            if self._has_target():
                off = self._off_hm()
                if off is not None:
                    td = flex_time.remaining_to(now, off[0], off[1])
                    total, done = flex_time.remaining_parts(td)
                    rem = "已到点" if done else flex_time.format_remaining(total, self._display_mode())
                    items.append((schedules.OFFWORK_ID, "距离您下班还有", rem, "今天", False))
                else:
                    items.append((schedules.OFFWORK_ID, "距离您下班还有", "未设置", "今天", False))
            else:
                items.append((schedules.OFFWORK_ID, "距离您下班还有", "点击设置", "今天", False))
            for s in self.cfg.get("schedules") or []:
                if not isinstance(s, dict) or not s.get("id"):
                    continue
                sid = str(s["id"])
                left, done = schedules.schedule_remaining(s, now)
                rem = "已到点" if done else flex_time.format_remaining(left, self._display_mode())
                when = schedules.format_schedule_when(s)
                items.append((sid, str(s.get("title") or "日程"), rem, when, True))

            for sid, title, rem, when, can_del in items:
                card = tk.Frame(rows, bg="#222733")
                card.pack(fill="x", pady=5)
                inner = tk.Frame(card, bg="#222733")
                inner.pack(fill="x", padx=10, pady=9)
                left_col = tk.Frame(inner, bg="#222733")
                left_col.pack(side="left", fill="x", expand=True)
                active = schedules.active_id(self.cfg) == sid
                tk.Label(
                    left_col, text=title, fg="#7ec8ff" if active else _CARD_FG, bg="#222733",
                    font=("Microsoft YaHei UI", 11, "bold"), anchor="w",
                ).pack(fill="x")
                tk.Label(
                    left_col, text=f"{when}  ·  {rem}", fg=_CARD_MUTED, bg="#222733",
                    font=("Microsoft YaHei UI", 9), anchor="w",
                ).pack(fill="x")
                btns = tk.Frame(inner, bg="#222733")
                btns.pack(side="right")
                pinned = schedules.is_pinned(self.cfg, sid)

                def toggle_pin(s=sid, was=pinned) -> None:
                    hint.set("")
                    if s == schedules.OFFWORK_ID and not self._has_target() and not was:
                        close()
                        self._open_setup_dialog()
                        return
                    ok, msg = schedules.set_pinned(self.cfg, s, not was)
                    if not ok:
                        hint.set(msg)
                        return
                    if not was:
                        self.cfg["active_pin_id"] = s
                    store.save_config(self.cfg)
                    self._last_key = ""
                    rebuild()

                tk.Button(
                    btns, text="优先" if pinned else "未优先", command=toggle_pin,
                    bg="#3a4254", fg="#ffd28a" if pinned else _CARD_MUTED, relief="flat",
                    font=("Microsoft YaHei UI", 9), padx=8, pady=3,
                ).pack(side="left", padx=3)

                if can_del:
                    def drop(s=sid) -> None:
                        hint.set("")
                        schedules.remove_schedule(self.cfg, s)
                        store.save_config(self.cfg)
                        self._last_key = ""
                        rebuild()

                    tk.Button(
                        btns, text="删除", command=drop, bg="#4a3038", fg="#ffb4b4", relief="flat",
                        font=("Microsoft YaHei UI", 9), padx=8, pady=3,
                    ).pack(side="left", padx=3)
            _sync()

        def add() -> None:
            hint.set("")
            _unbind_wheel()
            item = self._ask_new_schedule()
            if item is None:
                return
            schedules.add_schedule(self.cfg, item)
            ok, msg = schedules.set_pinned(self.cfg, item["id"], True)
            if not ok:
                hint.set(msg + "，日程已添加")
            else:
                self.cfg["active_pin_id"] = item["id"]
            store.save_config(self.cfg)
            self._last_key = ""
            rebuild()

        tk.Label(foot, textvariable=hint, fg="#ffd28a", bg=_CARD_BG, font=("Microsoft YaHei UI", 8)).pack(
            side="bottom", fill="x", pady=(0, 6)
        )
        tk.Button(
            foot, text="+  新增日程", command=add, bg=_CARD_ACCENT, fg="white", relief="flat",
            font=("Microsoft YaHei UI", 10, "bold"), padx=16, pady=7,
        ).pack(side="left")
        tk.Button(
            foot, text="关闭", command=close, bg=_CARD_BTN, fg="white", relief="flat",
            font=("Microsoft YaHei UI", 10), padx=14, pady=7,
        ).pack(side="right")
        rebuild()
        try:
            while not closed["v"]:
                try:
                    if not dlg.winfo_exists():
                        break
                    dlg.update()
                    self.win.pump()
                except Exception:
                    break
                time.sleep(0.02)
        finally:
            _unbind_wheel()
        self._last_key = ""

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
        elif op == "schedules":
            self._open_schedule_list()
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
