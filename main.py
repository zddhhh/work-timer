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
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageFont, ImageTk

import ad_disguise
import attachments
import autostart
import backdrop
import flex_time
import layered_win
import memos
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


def _fit_card(dlg: tk.Toplevel, *, min_w: int, min_h: int, near: tuple[int, int] | None) -> None:
    """按内容把卡片撑开，避免高 DPI 下底栏按钮被裁掉。"""
    dlg.update_idletasks()
    w = max(min_w, int(dlg.winfo_reqwidth()) + 20)
    h = max(min_h, int(dlg.winfo_reqheight()) + 24)
    sw = max(min_w, int(dlg.winfo_screenwidth()) - 24)
    sh = max(min_h, int(dlg.winfo_screenheight()) - 48)
    w, h = min(w, sw), min(h, sh)
    if near:
        x = min(max(8, int(near[0])), max(8, sw - w))
        y = min(max(8, int(near[1])), max(8, sh - h))
        dlg.geometry(f"{w}x{h}+{x}+{y}")
    else:
        dlg.geometry(f"{w}x{h}")


def _card_dialog(
    parent: tk.Tk | None,
    *,
    near: tuple[int, int] | None,
    width: int,
    height: int,
) -> tk.Toplevel:
    """无边框、置顶深色卡片（贴近主界面）。不裁圆角，避免把按钮切掉。"""
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


def _card_btn(parent: tk.Misc, text: str, command, *, accent: bool = False, danger: bool = False) -> tk.Button:
    if danger:
        bg, fg = "#4a3038", "#ffb4b4"
    elif accent:
        bg, fg = _CARD_ACCENT, "white"
    else:
        bg, fg = _CARD_BTN, "white"
    return tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=bg,
        activeforeground=fg,
        relief="flat",
        bd=0,
        highlightthickness=0,
        font=("Microsoft YaHei UI", 10, "bold" if accent else "normal"),
        padx=14,
        pady=6,
    )


def _new_attach_state(existing: object = None) -> dict:
    return {
        "keep": attachments.normalize(existing),
        "pending": [],
        "removed": [],
        "photos": [],
    }


def _pick_image_files(dlg: tk.Toplevel) -> tuple[str, ...]:
    try:
        dlg.attributes("-topmost", False)
    except Exception:
        pass
    try:
        paths = filedialog.askopenfilenames(
            parent=dlg,
            title="选择图片",
            filetypes=[
                ("图片", "*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif"),
                ("全部文件", "*.*"),
            ],
        )
        return tuple(str(p) for p in (paths or ()) if p)
    finally:
        try:
            dlg.attributes("-topmost", True)
            dlg.lift()
            dlg.focus_force()
        except Exception:
            pass


def _load_thumb(path: Path, size: int = 56) -> ImageTk.PhotoImage | None:
    try:
        with Image.open(path) as im:
            im = im.convert("RGBA")
            im.thumbnail((size, size))
            canvas = Image.new("RGBA", (size, size), (34, 39, 51, 255))
            x = (size - im.size[0]) // 2
            y = (size - im.size[1]) // 2
            canvas.alpha_composite(im, (x, y))
            return ImageTk.PhotoImage(canvas)
    except OSError:
        return None


def _pack_attach_editor(
    parent: tk.Misc,
    *,
    dlg: tk.Toplevel,
    state: dict,
    kind: str,
    owner_id: str | None,
    err: tk.StringVar,
) -> None:
    box = tk.Frame(parent, bg=_CARD_BG)
    box.pack(fill="x", pady=(8, 0), anchor="w")
    head = tk.Frame(box, bg=_CARD_BG)
    head.pack(fill="x")
    tk.Label(head, text="图片附件", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
        side="left"
    )
    count = tk.StringVar(value="")
    tk.Label(head, textvariable=count, fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
        side="left", padx=(8, 0)
    )
    thumbs = tk.Frame(box, bg=_CARD_BG)
    thumbs.pack(fill="x", pady=(4, 0))

    def total() -> int:
        return len(state["keep"]) + len(state["pending"])

    def open_path(path: Path) -> None:
        if path.is_file():
            attachments.open_file(path)

    def refresh() -> None:
        for child in thumbs.winfo_children():
            child.destroy()
        state["photos"].clear()
        count.set(f"{total()}/{attachments.MAX_IMAGES}")

        def add_cell(photo: ImageTk.PhotoImage | None, on_open, on_drop, label: str) -> None:
            cell = tk.Frame(thumbs, bg="#222733")
            cell.pack(side="left", padx=(0, 8), pady=2)
            if photo is not None:
                state["photos"].append(photo)
                img_btn = tk.Button(
                    cell, image=photo, command=on_open, bg="#222733", activebackground="#222733",
                    relief="flat", bd=0, highlightthickness=0, cursor="hand2",
                )
                img_btn.pack()
            else:
                tk.Label(cell, text=label[:4] or "图", fg=_CARD_MUTED, bg="#222733", width=6, height=2).pack()
            tk.Button(
                cell, text="去掉", command=on_drop, fg="#ffb4b4", bg="#222733",
                activebackground="#222733", activeforeground="#ffb4b4",
                relief="flat", bd=0, highlightthickness=0, font=("Microsoft YaHei UI", 8),
            ).pack()

        for i, rec in enumerate(list(state["keep"])):
            path = attachments.file_path(kind, owner_id, rec) if owner_id else Path()
            photo = _load_thumb(path) if owner_id else None

            def drop_keep(idx=i) -> None:
                rec_drop = state["keep"].pop(idx)
                state["removed"].append(rec_drop)
                err.set("")
                refresh()

            add_cell(photo, lambda p=path: open_path(p), drop_keep, str(rec.get("name") or "图"))

        for i, src in enumerate(list(state["pending"])):
            path = Path(src)
            photo = _load_thumb(path)

            def drop_pending(idx=i) -> None:
                state["pending"].pop(idx)
                err.set("")
                refresh()

            add_cell(photo, lambda p=path: open_path(p), drop_pending, path.stem)

        if total() < attachments.MAX_IMAGES:
            add = tk.Frame(thumbs, bg="#222733")
            add.pack(side="left", padx=(0, 8), pady=2)
            tk.Button(
                add,
                text="+ 图片",
                command=add_files,
                bg=_CARD_BTN,
                fg="white",
                activebackground=_CARD_BTN,
                activeforeground="white",
                relief="flat",
                bd=0,
                highlightthickness=0,
                font=("Microsoft YaHei UI", 9),
                padx=10,
                pady=16,
            ).pack()

    def add_files() -> None:
        err.set("")
        room = attachments.MAX_IMAGES - total()
        if room <= 0:
            err.set(f"最多 {attachments.MAX_IMAGES} 张图片")
            return
        paths = _pick_image_files(dlg)
        if not paths:
            return
        added = 0
        for src in paths:
            if added >= room:
                err.set(f"最多 {attachments.MAX_IMAGES} 张，已截断")
                break
            p = Path(src)
            if p.suffix.lower() not in attachments.ALLOWED_EXT:
                err.set("只支持 png / jpg / webp / bmp / gif")
                continue
            try:
                if p.stat().st_size > attachments.MAX_SRC_BYTES:
                    err.set("单张不超过 12MB")
                    continue
            except OSError:
                continue
            state["pending"].append(str(p))
            added += 1
        refresh()

    refresh()


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
    dlg = _card_dialog(parent, near=near, width=400, height=380)
    bar = tk.Frame(dlg, bg=_CARD_BG)
    bar.pack(side="bottom", fill="x", pady=(8, 16))
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

    _card_btn(bar, "开始计时", ok, accent=True).pack(side="left", padx=(20, 6))
    _card_btn(bar, "取消", dlg.destroy).pack(side="left", padx=6)
    dlg.bind("<Return>", lambda _e: ok())
    _fit_card(dlg, min_w=400, min_h=360, near=near)
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
        if updater.maybe_relaunch_from_stable_install():
            updater.force_exit_for_update()
        if updater.resume_pending_update():
            updater.force_exit_for_update()
        updater.cleanup_update_artifacts()
        updater.stamp_stable_install_version()
        self.cfg = store.load_config()
        schedules.ensure_fields(self.cfg)
        memos.ensure_fields(self.cfg)
        self.running = True
        self._menu_pos: tuple[int, int] | None = None
        self._need_dialog = False
        self._need_schedule_list = False
        self._schedule_list_open = False
        self._need_close_schedule_list = False
        self._tk: tk.Tk | None = None
        self._update_available = False
        self._update_info: updater.ReleaseInfo | None = None
        self._update_prompted = False
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
        self.cfg["esc_disguise"] = bool(self.cfg.get("esc_disguise"))
        self.cfg["auto_start"] = bool(self.cfg.get("auto_start"))
        try:
            autostart.sync(self.cfg["auto_start"])
        except OSError:
            pass
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
        got = backdrop.sample_around(self.win.x, self.win.y, self._win_w, self._win_h)
        if got is None:
            return
        luma, rgb = got
        q = (rgb[0] // 20, rgb[1] // 20, rgb[2] // 20)
        if q != self._env_q:
            self._env_q = q
            self._env_rgb = rgb
            self._last_key = ""
        theme = self._theme()
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
                kind, info = updater.check_update(self.cfg)
                if kind == "available" and info is not None:
                    self._update_info = info
                    self._update_available = True
            except Exception:
                pass

        threading.Thread(target=_run, daemon=True, name="silent-update").start()

    def _on_click(self, lx: int, ly: int) -> None:
        if self._disguised:
            return
        # 倒三角：打开 / 再点收回
        if ornaments.chevron_hit(lx, ly, self._win_w, self._win_h):
            if self._schedule_list_open:
                self._need_close_schedule_list = True
            else:
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

    def _auto_start_on(self) -> bool:
        return bool(self.cfg.get("auto_start"))

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

    def _ask_new_schedule(
        self,
        *,
        near: tuple[int, int] | None = None,
        cover: tuple[int, int, int, int] | None = None,
    ) -> dict | None:
        """cover=(x,y,w,h) 时盖在日程列表上，避免先藏列表再弹窗造成闪烁。"""
        result: list[dict | None] = [None]
        now = datetime.now()
        if cover is not None:
            cx, cy, cw, ch = (int(v) for v in cover)
            near = (cx, cy)
            dlg = _card_dialog(self._tk_root(), near=near, width=max(300, cw), height=max(420, ch))
        else:
            near = near or self._dialog_near()
            dlg = _card_dialog(self._tk_root(), near=near, width=320, height=460)
        # 先藏着排版，排完再显示，避免空壳闪一下
        try:
            dlg.withdraw()
        except Exception:
            pass
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(8, 16))
        kind_var = tk.StringVar(value="clock")
        title_var = tk.StringVar(value="")
        time_var = tk.StringVar(value="15:00")
        y_var = tk.StringVar(value=str(now.year))
        m_var = tk.StringVar(value=str(now.month))
        d_var = tk.StringVar(value=str(now.day))
        tip = tk.StringVar()
        body = tk.Frame(dlg, bg=_CARD_BG)
        body.pack(side="top", fill="both", expand=True, padx=18)

        tk.Label(body, text="新增日程", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold")).pack(
            pady=(16, 6), anchor="w"
        )
        box = tk.Frame(body, bg=_CARD_BG)
        box.pack(anchor="w")
        for val, lab in (("clock", "指定日期+时刻"), ("duration", "倒计时长（分钟）")):
            tk.Radiobutton(
                box, text=lab, variable=kind_var, value=val, fg=_CARD_FG, bg=_CARD_BG,
                selectcolor=_CARD_BTN, activebackground=_CARD_BG, font=("Microsoft YaHei UI", 10),
            ).pack(anchor="w")

        tk.Label(body, text="名称", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", pady=(8, 0)
        )
        tk.Entry(
            body, textvariable=title_var, font=("Microsoft YaHei UI", 12), bg="#222733", fg=_CARD_FG,
            insertbackground=_CARD_FG, relief="flat", width=28,
        ).pack(anchor="w", ipady=5)

        date_row = tk.Frame(body, bg=_CARD_BG)
        date_row.pack(pady=(10, 0), anchor="w")
        tk.Label(date_row, text="日期", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(side="left")
        for var, lab, w in ((y_var, "年", 5), (m_var, "月", 3), (d_var, "日", 3)):
            tk.Entry(
                date_row, textvariable=var, width=w, justify="center", font=("Microsoft YaHei UI", 11),
                bg="#222733", fg=_CARD_FG, insertbackground=_CARD_FG, relief="flat",
            ).pack(side="left", padx=(6, 2), ipady=3)
            tk.Label(date_row, text=lab, fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 8)).pack(side="left")

        tk.Label(body, textvariable=tip, fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", pady=(10, 0)
        )
        tk.Entry(
            body, textvariable=time_var, font=("Microsoft YaHei UI", 14), justify="center",
            bg="#222733", fg=_CARD_FG, insertbackground=_CARD_FG, relief="flat", width=28,
        ).pack(anchor="w", pady=8, ipady=6)

        def sync(*_a) -> None:
            if kind_var.get() == "clock":
                tip.set("时刻，例如 15:00")
                date_row.pack(pady=(10, 0), anchor="w")
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
        attach = _new_attach_state()
        _pack_attach_editor(body, dlg=dlg, state=attach, kind="schedule", owner_id=None, err=err)
        tk.Label(body, textvariable=err, fg="#ff8b8b", bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(anchor="w")

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
            item = result[0]
            if item is not None:
                item["images"] = attachments.commit(
                    "schedule",
                    str(item["id"]),
                    keep=attach["keep"],
                    pending=attach["pending"],
                    removed=attach["removed"],
                )
            dlg.destroy()

        _card_btn(bar, "开始倒计时", ok, accent=True).pack(side="left", padx=(18, 6))
        _card_btn(bar, "取消", dlg.destroy).pack(side="left", padx=6)
        dlg.bind("<Return>", lambda _e: ok())
        if cover is not None:
            cx, cy, cw, ch = (int(v) for v in cover)
            dlg.geometry(f"{max(300, cw)}x{max(420, ch)}+{cx}+{cy}")
        else:
            _fit_card(dlg, min_w=300, min_h=420, near=near)
        try:
            dlg.update_idletasks()
            dlg.deiconify()
            dlg.lift()
            dlg.focus_force()
        except Exception:
            pass
        _run_card_modal(dlg, self.win)
        return result[0]

    def _ask_memo_edit(
        self,
        memo_id: str | None = None,
        *,
        cover: tuple[int, int, int, int] | None = None,
    ) -> dict | None:
        """新增或编辑备忘。cover 时盖在日程弹层上，避免闪一下。"""
        result: list[dict | None] = [None]
        existing = memos.find_memo(self.cfg, memo_id) if memo_id else None
        if cover is not None:
            cx, cy, cw, ch = (int(v) for v in cover)
            near = (cx, cy)
            dlg = _card_dialog(self._tk_root(), near=near, width=max(300, cw), height=max(420, ch))
        else:
            near = self._dialog_near()
            dlg = _card_dialog(self._tk_root(), near=near, width=320, height=460)
        try:
            dlg.withdraw()
        except Exception:
            pass
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(8, 16))
        title_var = tk.StringVar(value=str(existing.get("title") or "") if existing else "")
        err = tk.StringVar(value="")
        body = tk.Frame(dlg, bg=_CARD_BG)
        body.pack(side="top", fill="both", expand=True, padx=18)

        tk.Label(
            body,
            text="编辑备忘" if existing else "新增备忘",
            fg=_CARD_FG,
            bg=_CARD_BG,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(16, 6), anchor="w")
        tk.Label(body, text="标题（可选）", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
            anchor="w"
        )
        tk.Entry(
            body, textvariable=title_var, font=("Microsoft YaHei UI", 12), bg="#222733", fg=_CARD_FG,
            insertbackground=_CARD_FG, relief="flat", width=28,
        ).pack(anchor="w", ipady=5, fill="x")
        tk.Label(body, text="正文", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", pady=(10, 0)
        )
        text = tk.Text(
            body, height=8, wrap="word", font=("Microsoft YaHei UI", 11), bg="#222733", fg=_CARD_FG,
            insertbackground=_CARD_FG, relief="flat", bd=0, highlightthickness=0, padx=8, pady=8,
        )
        text.pack(anchor="w", fill="both", expand=True, pady=(4, 8))
        if existing:
            text.insert("1.0", str(existing.get("body") or ""))
        attach = _new_attach_state(existing.get("images") if existing else None)
        mid = str(existing.get("id") or "") if existing else None
        _pack_attach_editor(body, dlg=dlg, state=attach, kind="memo", owner_id=mid, err=err)
        tk.Label(body, textvariable=err, fg="#ff8b8b", bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        def ok() -> None:
            err.set("")
            title = title_var.get().strip()
            body_txt = text.get("1.0", "end-1c").strip()
            if not title and not body_txt and not (attach["keep"] or attach["pending"]):
                err.set("请填写标题、正文或添加图片")
                return
            result[0] = {"title": title, "body": body_txt, "attach": attach}
            dlg.destroy()

        _card_btn(bar, "保存", ok, accent=True).pack(side="left", padx=(18, 6))
        _card_btn(bar, "取消", dlg.destroy).pack(side="left", padx=6)
        if cover is not None:
            cx, cy, cw, ch = (int(v) for v in cover)
            dlg.geometry(f"{max(300, cw)}x{max(420, ch)}+{cx}+{cy}")
        else:
            _fit_card(dlg, min_w=300, min_h=420, near=near)
        try:
            dlg.update_idletasks()
            dlg.deiconify()
            dlg.lift()
            dlg.focus_force()
            text.focus_set()
        except Exception:
            pass
        _run_card_modal(dlg, self.win)
        return result[0]

    def _ask_schedule_images(
        self,
        sid: str,
        *,
        cover: tuple[int, int, int, int] | None = None,
    ) -> list[dict] | None:
        item = schedules.find_schedule(self.cfg, sid)
        if item is None:
            return None
        result: list[list[dict] | None] = [None]
        if cover is not None:
            cx, cy, cw, ch = (int(v) for v in cover)
            near = (cx, cy)
            dlg = _card_dialog(self._tk_root(), near=near, width=max(300, cw), height=max(280, min(ch, 360)))
        else:
            near = self._dialog_near()
            dlg = _card_dialog(self._tk_root(), near=near, width=320, height=280)
        try:
            dlg.withdraw()
        except Exception:
            pass
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(8, 16))
        err = tk.StringVar(value="")
        body = tk.Frame(dlg, bg=_CARD_BG)
        body.pack(side="top", fill="both", expand=True, padx=18)
        tk.Label(
            body,
            text=f"图片 · {item.get('title') or '日程'}",
            fg=_CARD_FG,
            bg=_CARD_BG,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(16, 6), anchor="w")
        attach = _new_attach_state(item.get("images"))
        _pack_attach_editor(body, dlg=dlg, state=attach, kind="schedule", owner_id=sid, err=err)
        tk.Label(body, textvariable=err, fg="#ff8b8b", bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(anchor="w")

        def ok() -> None:
            result[0] = attachments.commit(
                "schedule",
                sid,
                keep=attach["keep"],
                pending=attach["pending"],
                removed=attach["removed"],
            )
            dlg.destroy()

        _card_btn(bar, "保存", ok, accent=True).pack(side="left", padx=(18, 6))
        _card_btn(bar, "取消", dlg.destroy).pack(side="left", padx=6)
        if cover is not None:
            cx, cy, cw, ch = (int(v) for v in cover)
            dlg.geometry(f"{max(300, cw)}x{max(280, min(ch, 360))}+{cx}+{cy}")
        else:
            _fit_card(dlg, min_w=300, min_h=260, near=near)
        try:
            dlg.update_idletasks()
            dlg.deiconify()
            dlg.lift()
            dlg.focus_force()
        except Exception:
            pass
        _run_card_modal(dlg, self.win)
        return result[0]

    def _open_schedule_list(self) -> None:
        if self._schedule_list_open:
            self._need_close_schedule_list = True
            return
        schedules.ensure_fields(self.cfg)
        memos.ensure_fields(self.cfg)
        near = self._dialog_near()
        dlg = _card_dialog(self._tk_root(), near=near, width=440, height=520)
        closed = {"v": False}
        tab = {"name": "schedules"}
        self._schedule_list_open = True
        self._need_close_schedule_list = False
        self._last_key = ""

        def close() -> None:
            closed["v"] = True
            try:
                dlg.destroy()
            except Exception:
                pass

        # 底栏先占位，保证「新增 / 关闭」永远在窗口里
        foot = tk.Frame(dlg, bg=_CARD_BG)
        foot.pack(side="bottom", fill="x", padx=16, pady=(8, 16))
        hint = tk.StringVar(value="")
        btn_row = tk.Frame(foot, bg=_CARD_BG)
        btn_row.pack(side="bottom", fill="x")
        tk.Label(foot, textvariable=hint, fg="#ffd28a", bg=_CARD_BG, font=("Microsoft YaHei UI", 8)).pack(
            side="bottom", fill="x", pady=(0, 6)
        )

        head = tk.Frame(dlg, bg=_CARD_BG)
        head.pack(side="top", fill="x", padx=16, pady=(14, 6))
        tabs = tk.Frame(head, bg=_CARD_BG)
        tabs.pack(side="left")
        tab_btns: dict[str, tk.Button] = {}

        def _style_tab(name: str, active: bool) -> None:
            btn = tab_btns.get(name)
            if btn is None:
                return
            bg = _CARD_ACCENT if active else _CARD_BTN
            font = ("Microsoft YaHei UI", 10, "bold" if active else "normal")
            btn.configure(bg=bg, fg="white", activebackground=bg, activeforeground="white", font=font)

        rotate_var = tk.BooleanVar(value=bool(self.cfg.get("auto_rotate_pins")))

        def on_rotate() -> None:
            self.cfg["auto_rotate_pins"] = bool(rotate_var.get())
            store.save_config(self.cfg)
            self._last_key = ""

        rotate_chk = tk.Checkbutton(
            head, text="自动轮播", variable=rotate_var, command=on_rotate, fg=_CARD_MUTED, bg=_CARD_BG,
            selectcolor=_CARD_BTN, activebackground=_CARD_BG, font=("Microsoft YaHei UI", 9),
        )
        rotate_chk.pack(side="right")

        search_var = tk.StringVar(value="")
        search_row = tk.Frame(dlg, bg=_CARD_BG)
        search_row.pack(side="top", fill="x", padx=16, pady=(0, 2))
        tk.Label(
            search_row, text="搜索", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        search_ent = tk.Entry(
            search_row, textvariable=search_var, font=("Microsoft YaHei UI", 11),
            bg="#222733", fg=_CARD_FG, insertbackground=_CARD_FG, relief="flat",
        )
        search_ent.pack(side="left", fill="x", expand=True, padx=(8, 0), ipady=5)

        mid = tk.Frame(dlg, bg=_CARD_BG)
        mid.pack(side="top", fill="both", expand=True, padx=16, pady=4)

        canvas = tk.Canvas(mid, bg=_CARD_BG, highlightthickness=0, bd=0, height=320)
        rows = tk.Frame(canvas, bg=_CARD_BG)
        win_id = canvas.create_window((0, 0), window=rows, anchor="nw")

        def _sync(_e=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, 0, 0))
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
        canvas.pack(fill="both", expand=True)

        def _panel_cover() -> tuple[int, int, int, int] | None:
            try:
                return (
                    int(dlg.winfo_rootx()),
                    int(dlg.winfo_rooty()),
                    max(300, int(dlg.winfo_width())),
                    max(340, int(dlg.winfo_height())),
                )
            except Exception:
                return None

        def rebuild() -> None:
            for child in rows.winfo_children():
                child.destroy()
            now = datetime.now()
            q = search_var.get()
            items: list[tuple[str, str, str, str, bool, int]] = []
            if self._has_target():
                off = self._off_hm()
                if off is not None:
                    td = flex_time.remaining_to(now, off[0], off[1])
                    total, done = flex_time.remaining_parts(td)
                    rem = (
                        f"已过 {flex_time.format_remaining(total, self._display_mode())}"
                        if done
                        else flex_time.format_remaining(total, self._display_mode())
                    )
                    off_row = (schedules.OFFWORK_ID, "距离您下班还有", rem, "今天", False, 0)
                else:
                    off_row = (schedules.OFFWORK_ID, "距离您下班还有", "未设置", "今天", False, 0)
            else:
                off_row = (schedules.OFFWORK_ID, "距离您下班还有", "点击设置", "今天", False, 0)
            if attachments.matches([off_row[1], off_row[2], off_row[3], "下班"], [], q):
                items.append(off_row)
            for s in self.cfg.get("schedules") or []:
                if not isinstance(s, dict) or not s.get("id"):
                    continue
                if not schedules.matches(s, q):
                    continue
                sid = str(s["id"])
                left, done = schedules.schedule_remaining(s, now)
                rem = (
                    f"已过 {flex_time.format_remaining(left, self._display_mode())}"
                    if done
                    else flex_time.format_remaining(left, self._display_mode())
                )
                when = schedules.format_schedule_when(s)
                items.append((sid, str(s.get("title") or "日程"), rem, when, True, attachments.count(s)))

            if not items:
                tk.Label(
                    rows,
                    text="没有匹配的日程" if q.strip() else "还没有日程",
                    fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 11),
                ).pack(pady=28)
                _sync()
                return

            for sid, title, rem, when, can_del, nimg in items:
                card = tk.Frame(rows, bg="#222733")
                card.pack(fill="x", pady=6)
                inner = tk.Frame(card, bg="#222733")
                inner.pack(fill="x", padx=10, pady=8)
                active = schedules.active_id(self.cfg) == sid
                tk.Label(
                    inner, text=title, fg="#7ec8ff" if active else _CARD_FG, bg="#222733",
                    font=("Microsoft YaHei UI", 11, "bold"), anchor="w",
                ).pack(fill="x")
                extra = f"  ·  {nimg}图" if nimg else ""
                tk.Label(
                    inner, text=f"{when}  ·  {rem}{extra}", fg=_CARD_MUTED, bg="#222733",
                    font=("Microsoft YaHei UI", 9), anchor="w",
                ).pack(fill="x")
                btns = tk.Frame(inner, bg="#222733")
                btns.pack(fill="x", pady=(8, 0), anchor="w")
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

                _card_btn(btns, "优先" if pinned else "未优先", toggle_pin, accent=pinned).pack(
                    side="left", padx=(0, 8)
                )
                if can_del:
                    def edit_imgs(s=sid) -> None:
                        hint.set("")
                        _unbind_wheel()
                        imgs = self._ask_schedule_images(s, cover=_panel_cover())
                        try:
                            if dlg.winfo_exists():
                                dlg.lift()
                        except Exception:
                            pass
                        if self._need_close_schedule_list:
                            close()
                            return
                        if imgs is None:
                            return
                        schedules.set_images(self.cfg, s, imgs)
                        store.save_config(self.cfg)
                        rebuild()

                    def drop(s=sid) -> None:
                        hint.set("")
                        schedules.remove_schedule(self.cfg, s)
                        store.save_config(self.cfg)
                        self._last_key = ""
                        rebuild()

                    _card_btn(btns, f"图片{nimg}" if nimg else "图片", edit_imgs).pack(
                        side="left", padx=(0, 8)
                    )
                    _card_btn(btns, "删除", drop, danger=True).pack(side="left")
            _sync()

        def rebuild_memos() -> None:
            for child in rows.winfo_children():
                child.destroy()
            q = search_var.get()
            items = [m for m in memos.list_sorted(self.cfg) if memos.matches(m, q)]
            if not items:
                empty = "没有匹配的备忘" if q.strip() else "还没有备忘"
                tk.Label(
                    rows, text=empty, fg=_CARD_MUTED, bg=_CARD_BG,
                    font=("Microsoft YaHei UI", 11),
                ).pack(pady=28)
                _sync()
                return
            for item in items:
                mid = str(item.get("id") or "")
                nimg = attachments.count(item)
                card = tk.Frame(rows, bg="#222733")
                card.pack(fill="x", pady=6)
                inner = tk.Frame(card, bg="#222733")
                inner.pack(fill="x", padx=10, pady=8)
                title_lbl = tk.Label(
                    inner, text=memos.display_title(item), fg=_CARD_FG, bg="#222733",
                    font=("Microsoft YaHei UI", 11, "bold"), anchor="w",
                )
                title_lbl.pack(fill="x")
                extra = f"  ·  {nimg}图" if nimg else ""
                when_lbl = tk.Label(
                    inner, text=f"{memos.format_updated(item)}{extra}", fg=_CARD_MUTED, bg="#222733",
                    font=("Microsoft YaHei UI", 9), anchor="w",
                )
                when_lbl.pack(fill="x")
                btns = tk.Frame(inner, bg="#222733")
                btns.pack(fill="x", pady=(8, 0), anchor="w")

                def open_edit(m=mid) -> None:
                    edit_memo(m)

                def drop_memo(m=mid) -> None:
                    hint.set("")
                    memos.remove_memo(self.cfg, m)
                    store.save_config(self.cfg)
                    rebuild_memos()

                _card_btn(btns, "编辑", open_edit).pack(side="left", padx=(0, 8))
                _card_btn(btns, "删除", drop_memo, danger=True).pack(side="left")
                for w in (card, inner, title_lbl, when_lbl):
                    w.bind("<Button-1>", lambda _e, m=mid: edit_memo(m))
            _sync()

        def add_schedule() -> None:
            hint.set("")
            _unbind_wheel()
            item = self._ask_new_schedule(cover=_panel_cover())
            try:
                if dlg.winfo_exists():
                    dlg.lift()
            except Exception:
                pass
            if self._need_close_schedule_list:
                close()
                return
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

        def edit_memo(mid: str | None = None) -> None:
            hint.set("")
            _unbind_wheel()
            data = self._ask_memo_edit(mid, cover=_panel_cover())
            try:
                if dlg.winfo_exists():
                    dlg.lift()
            except Exception:
                pass
            if self._need_close_schedule_list:
                close()
                return
            if data is None:
                return
            attach = data.get("attach") or _new_attach_state()
            if mid:
                images = attachments.commit(
                    "memo",
                    mid,
                    keep=attach["keep"],
                    pending=attach["pending"],
                    removed=attach["removed"],
                )
                memos.update_memo(self.cfg, mid, title=data["title"], body=data["body"], images=images)
            else:
                item = memos.new_memo(title=data["title"], body=data["body"])
                item["images"] = attachments.commit(
                    "memo",
                    str(item["id"]),
                    keep=attach["keep"],
                    pending=attach["pending"],
                    removed=attach["removed"],
                )
                memos.add_memo(self.cfg, item)
            store.save_config(self.cfg)
            rebuild_memos()

        def add_memo() -> None:
            edit_memo(None)

        def on_add() -> None:
            if tab["name"] == "memos":
                add_memo()
            else:
                add_schedule()

        add_btn = _card_btn(btn_row, "+  新增日程", on_add, accent=True)
        add_btn.pack(side="left")
        _card_btn(btn_row, "关闭", close).pack(side="right")

        def show_tab(name: str) -> None:
            tab["name"] = name
            hint.set("")
            _style_tab("schedules", name == "schedules")
            _style_tab("memos", name == "memos")
            if name == "memos":
                rotate_chk.pack_forget()
                add_btn.configure(text="+  新增备忘")
                rebuild_memos()
            else:
                rotate_chk.pack(side="right")
                add_btn.configure(text="+  新增日程")
                rebuild()

        tab_btns["schedules"] = _card_btn(tabs, "日程", lambda: show_tab("schedules"))
        tab_btns["memos"] = _card_btn(tabs, "备忘", lambda: show_tab("memos"))
        tab_btns["schedules"].pack(side="left", padx=(0, 6))
        tab_btns["memos"].pack(side="left")

        def on_search(*_a) -> None:
            if tab["name"] == "memos":
                rebuild_memos()
            else:
                rebuild()

        search_var.trace_add("write", on_search)

        def focus_search(_e=None):
            search_ent.focus_set()
            return "break"

        dlg.bind("<Control-f>", focus_search)
        show_tab("schedules")
        _fit_card(dlg, min_w=440, min_h=560, near=near)
        try:
            while not closed["v"]:
                try:
                    if not dlg.winfo_exists():
                        break
                    if self._need_close_schedule_list:
                        close()
                        break
                    if self._menu_pos is not None:
                        sx, sy = self._menu_pos
                        self._menu_pos = None
                        self._handle_menu(sx, sy)
                        if closed["v"] or self._need_close_schedule_list:
                            close()
                            break
                    dlg.update()
                    self.win.pump()
                    self._paint()
                except Exception:
                    break
                time.sleep(0.02)
        finally:
            _unbind_wheel()
            self._schedule_list_open = False
            self._need_close_schedule_list = False
            self._last_key = ""

    def _handle_menu(self, sx: int, sy: int) -> None:
        op = self.win.popup_menu(
            sx,
            sy,
            self._display_mode(),
            self._theme().id,
            esc_disguise=self._esc_disguise_on(),
            auto_start=self._auto_start_on(),
        )
        if op == "quit":
            self.running = False
        elif op == "update":
            self._check_update()
        elif op in ("set_time", "set_off"):
            self._open_setup_dialog()
        elif op == "schedules":
            if self._schedule_list_open:
                self._need_close_schedule_list = True
            else:
                self._open_schedule_list()
        elif op == "toggle_esc_disguise":
            self._set_esc_disguise(not self._esc_disguise_on())
        elif op == "toggle_auto_start":
            self._set_auto_start(not self._auto_start_on())
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

    def _check_update(self, *, known: updater.ReleaseInfo | None = None) -> None:
        self.cfg = store.load_config()
        near = self._dialog_near()
        dlg = _card_dialog(self._tk_root(), near=near, width=320, height=200)
        btn_row = tk.Frame(dlg, bg=_CARD_BG)
        btn_row.pack(side="bottom", fill="x", padx=16, pady=(8, 16))

        if known is not None:
            status = tk.StringVar(value=f"有新版本 {known.version}")
            detail = tk.StringVar(value=f"当前 {APP_VERSION}，要现在更新吗？")
        else:
            status = tk.StringVar(value="正在检查更新…")
            detail = tk.StringVar(value=f"当前 {APP_VERSION}")

        tk.Label(
            dlg, textvariable=status, fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(16, 6), padx=18, anchor="w")
        tk.Label(
            dlg, textvariable=detail, fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9),
            wraplength=270, justify="left", anchor="w",
        ).pack(padx=18, anchor="w")
        bar = ttk.Progressbar(dlg, mode="indeterminate", length=270)
        if known is None:
            bar.pack(pady=(12, 4), padx=18)
            bar.start(12)

        state: dict = {
            "closed": False,
            "phase": "ask" if known else "check",
            "pending_dl": None,
            "cancel": False,
        }

        def alive() -> bool:
            return not state["closed"] and bool(dlg.winfo_exists())

        def on_close() -> None:
            state["cancel"] = True
            state["closed"] = True
            try:
                bar.stop()
            except Exception:
                pass
            try:
                dlg.destroy()
            except Exception:
                pass

        def set_btns(specs: list[tuple[str, object, bool]]) -> None:
            for w in btn_row.winfo_children():
                w.destroy()
            for text, cmd, accent in specs:
                _card_btn(btn_row, text, cmd, accent=accent).pack(side="left", padx=(0, 8))

        def short(msg: str, n: int = 48) -> str:
            t = (msg or "").replace("\n", " ").strip()
            return t[:n] + ("…" if len(t) > n else "")

        def finish_idle(msg: str, sub: str = "", *, error: bool = False) -> None:
            if not alive():
                return
            state["phase"] = "idle"
            try:
                bar.stop()
                bar.pack_forget()
            except Exception:
                pass
            status.set(msg)
            detail.set(short(sub) if sub else ("可以关闭" if not error else ""))
            set_btns([("关闭", on_close, False)])
            _fit_card(dlg, min_w=300, min_h=160, near=near)

        def start_download(info: updater.ReleaseInfo) -> None:
            if not alive():
                return
            if updater.current_exe_path() is None:
                finish_idle("当前是源码运行", "请重新打包 exe", error=True)
                return
            state["phase"] = "download"
            state["cancel"] = False
            status.set(f"正在下载 {info.version}")
            detail.set("下载完成后会自动重启")
            set_btns([("取消", on_close, False)])
            try:
                bar.stop()
            except Exception:
                pass
            bar.configure(mode="determinate", maximum=100, value=0)
            try:
                bar.pack(pady=(12, 4), padx=18)
            except Exception:
                pass

            done_box: list[object] = []

            def on_progress(done: int, total: int) -> None:
                if state["cancel"]:
                    return
                done_box.clear()
                done_box.append(("progress", done, total))

            def worker_dl() -> None:
                try:
                    path = updater.download_update(
                        info,
                        self.cfg,
                        on_progress=on_progress,
                        cancel_check=lambda: bool(state["cancel"]),
                    )
                    if state["cancel"]:
                        done_box.clear()
                        done_box.append(("cancel",))
                        return
                    done_box.clear()
                    done_box.append(("ok", path))
                except updater.DownloadCancelled:
                    done_box.clear()
                    done_box.append(("cancel",))
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
                            detail.set(f"{done / (1024 * 1024):.1f} / {total / (1024 * 1024):.1f} MB")
                        else:
                            detail.set(f"已下载 {done / (1024 * 1024):.1f} MB")
                    elif kind == "ok":
                        path = done_box[0][1]
                        status.set("正在安装并重启…")
                        detail.set("请稍候")
                        bar.configure(value=100)
                        dlg.update_idletasks()
                        try:
                            updater.apply_update_and_restart(path)  # type: ignore[arg-type]
                            updater.force_exit_for_update()
                        except Exception as e:  # noqa: BLE001
                            finish_idle("更新失败", str(e), error=True)
                        return
                    elif kind == "cancel":
                        return
                    else:
                        finish_idle("下载失败", str(done_box[0][1]), error=True)
                        return
                try:
                    dlg.update()
                    self.win.pump()
                except Exception:
                    state["cancel"] = True
                    state["closed"] = True
                    return
                time.sleep(0.03)
            # 取消后尽量清掉残留临时包，避免下次提示文件被占用
            state["cancel"] = True
            try:
                updater.cleanup_update_artifacts(keep_pending=True)
            except Exception:
                pass

        def show_available(info: updater.ReleaseInfo) -> None:
            if not alive():
                return
            self._update_info = info
            self._update_available = True
            state["phase"] = "ask"
            try:
                bar.stop()
                bar.pack_forget()
            except Exception:
                pass
            status.set(f"有新版本 {info.version}")
            detail.set(f"当前 {APP_VERSION}，要现在更新吗？")

            def go(inf=info) -> None:
                state["pending_dl"] = inf

            set_btns([("现在更新", go, True), ("稍后", on_close, False)])
            _fit_card(dlg, min_w=300, min_h=170, near=near)

        if known is not None:
            show_available(known)
        else:
            set_btns([("取消", on_close, False)])
            result_box: list[tuple[str, updater.ReleaseInfo | None]] = []

            def worker_check() -> None:
                try:
                    result_box.append(updater.check_update(self.cfg))
                except Exception as e:  # noqa: BLE001
                    result_box.append((f"error:{e}", None))

            threading.Thread(target=worker_check, daemon=True, name="update-check").start()
            while alive() and state["phase"] == "check":
                if result_box:
                    st, info = result_box[0]
                    if st == "no_repo":
                        finish_idle("还没配置仓库", error=True)
                    elif st.startswith("error:"):
                        finish_idle("检查失败", st[6:], error=True)
                    elif st == "latest":
                        finish_idle("已是最新版", f"当前 {APP_VERSION}")
                    elif st == "available" and info is not None:
                        show_available(info)
                    else:
                        finish_idle("没有可用更新", error=True)
                    break
                try:
                    dlg.update()
                    self.win.pump()
                except Exception:
                    state["closed"] = True
                    break
                time.sleep(0.03)

        _fit_card(dlg, min_w=300, min_h=170, near=near)
        while alive() and state["phase"] in ("ask", "idle"):
            pending = state.get("pending_dl")
            if pending is not None:
                state["pending_dl"] = None
                start_download(pending)
                break
            try:
                dlg.update()
                self.win.pump()
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
            key = f"{key}-{aid}-{idx}/{n}-o{int(self._schedule_list_open)}-{stage}"
            env = self._env_rgb
            if env is not None:
                key = f"{key}-e{env[0] // 20}{env[1] // 20}{env[2] // 20}"
            if ornaments.has_skin(theme.kind):
                period = 11.0 if stage == "warn" else (20.0 if stage == "done" else 15.5)
                sweeping = (phase % period) < 1.7
                fps = 20 if sweeping else (4 if stage in ("idle", "done") else 8)
                key = f"{key}-a{int(phase * fps)}"
            elif theme.kind != "ghost":
                key = f"{key}-p{int(phase * 6)}"

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
                stage=stage,
                env_rgb=self._env_rgb,
            )
            chev = theme.outline if theme.outline[3] > 20 else (255, 255, 255, 70)
            if (0.2126 * accent[0] + 0.7152 * accent[1] + 0.0722 * accent[2]) < 140:
                chev = (40, 44, 52, 90)
            dots = (idx, n) if n >= 2 and bool(self.cfg.get("auto_rotate_pins")) else (0, 0)
            ornaments.paint_chevron(
                img, w, h, color=chev, pin_dots=dots, opened=self._schedule_list_open
            )
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
                if self._update_available and not self._update_prompted and not self._disguised:
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
