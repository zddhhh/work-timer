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
from tkinter import filedialog, messagebox, ttk

from PIL import Image, ImageChops, ImageFont, ImageTk

import attachments
import autostart
import backdrop
import changelog
import desktop_shortcut
import festival
import feedback
import flex_time
import hydrate
import key_hide
import kinetic
import layered_win
import memos
import ornaments
import schedules
import single_instance
import skin_settings
import store
import themes
import uninstall
import updater
import win_drop
import worklog
from version import APP_VERSION

FPS = 60
IDLE_FPS = 30
_LEGACY_SIZES = {"s": (248, 92), "m": (320, 118), "l": (400, 148)}


def _font(size: int) -> ImageFont.ImageFont:
    windir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Fonts"
    for name in ("msyhbd.ttc", "msyh.ttc", "msyh.ttf", "simhei.ttf"):
        try:
            return ImageFont.truetype(str(windir / name), size)
        except OSError:
            continue
    return ImageFont.load_default()


def _kinetic_font(w: int, n: int) -> ImageFont.ImageFont:
    n = max(1, n)
    return _font(max(16, min(40, int((w * 0.76) / n))))


_ALPHA_FLOOR_LUT = bytes([1] + list(range(1, 256)))


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
    return pm.tobytes("raw", "BGRA"), b"\xff" * (w * h)


_CARD_BG = "#161a22"
_CARD_FG = "#f0f3f8"
_CARD_MUTED = "#8b93a5"
_CARD_ACCENT = "#3d7eff"
_CARD_BTN = "#2a3140"


class _Anchor:
    """弹窗锚点：绕开计时器矩形放置，下→上→右→左依次试，都放不下就选重叠最少的。

    也可当 (x, y) 二元组用（兼容只取 near[0]/near[1] 的旧调用）。
    """

    GAP = 8

    def __init__(self, x: int, y: int, w: int, h: int) -> None:
        self.x, self.y, self.w, self.h = int(x), int(y), int(w), int(h)

    def __getitem__(self, i: int) -> int:
        return (self.x, self.y + self.h + self.GAP)[i]

    def __len__(self) -> int:
        return 2

    def _work(self) -> tuple[int, int, int, int]:
        try:
            r = layered_win.monitor_work_at(self.x + self.w // 2, self.y + self.h // 2)
            return int(r.left), int(r.top), int(r.right), int(r.bottom)
        except Exception:
            return 0, 0, 1920, 1040

    def place(self, w: int, h: int) -> tuple[int, int]:
        left, top, right, bottom = self._work()
        pad = 8
        g = self.GAP

        def clamp(x: int, y: int) -> tuple[int, int]:
            x = min(max(left + pad, x), max(left + pad, right - pad - w))
            y = min(max(top + pad, y), max(top + pad, bottom - pad - h))
            return x, y

        def overlap(x: int, y: int) -> int:
            ox = max(0, min(x + w, self.x + self.w) - max(x, self.x))
            oy = max(0, min(y + h, self.y + self.h) - max(y, self.y))
            return ox * oy

        cands = (
            (self.x, self.y + self.h + g),  # 下
            (self.x, self.y - g - h),  # 上
            (self.x + self.w + g, self.y),  # 右
            (self.x - g - w, self.y),  # 左
        )
        best: tuple[int, int] | None = None
        best_ov = 1 << 60
        for cx, cy in cands:
            x, y = clamp(cx, cy)
            ov = overlap(x, y)
            if ov == 0:
                return x, y
            if ov < best_ov:
                best_ov, best = ov, (x, y)
        return best or clamp(self.x, self.y + self.h + g)


def _resolve_near(near, w: int, h: int, sw: int, sh: int) -> tuple[int, int]:
    if isinstance(near, _Anchor):
        return near.place(w, h)
    x = min(max(8, int(near[0])), max(8, sw - w))
    y = min(max(8, int(near[1])), max(8, sh - h))
    return x, y


def _place_dialog(dlg: tk.Toplevel, near, *, min_w: int, min_h: int) -> None:
    """按内容自适应尺寸，避免高 DPI 下按钮被裁切。"""
    dlg.update_idletasks()
    w = max(min_w, dlg.winfo_reqwidth() + 24)
    h = max(min_h, dlg.winfo_reqheight() + 24)
    if near:
        x, y = _resolve_near(near, w, h, int(dlg.winfo_screenwidth()), int(dlg.winfo_screenheight()))
        dlg.geometry(f"{w}x{h}+{x}+{y}")
    else:
        dlg.geometry(f"{w}x{h}")


def _card_bounds(dlg: tk.Toplevel, *, min_w: int, min_h: int, near) -> str:
    dlg.update_idletasks()
    w = max(min_w, int(dlg.winfo_reqwidth()) + 20)
    h = max(min_h, int(dlg.winfo_reqheight()) + 24)
    sw = max(min_w, int(dlg.winfo_screenwidth()) - 24)
    sh = max(min_h, int(dlg.winfo_screenheight()) - 48)
    w, h = min(w, sw), min(h, sh)
    if near:
        x, y = _resolve_near(near, w, h, sw, sh)
        return f"{w}x{h}+{x}+{y}"
    return f"{w}x{h}"


def _alpha(dlg: tk.Toplevel) -> float:
    try:
        return float(dlg.attributes("-alpha"))
    except tk.TclError:
        return 1.0


def _fit_card(dlg: tk.Toplevel, *, min_w: int, min_h: int, near) -> None:
    """按内容把卡片撑开；藏着的卡片在全透明状态下映射并画完，再亮出来。

    update_idletasks 只排版、不处理 WM_PAINT。直接亮出会先看到空底板和白色按钮块，
    控件再分几次画上去。必须 update() 让控件真正画完。
    """
    try:
        withdrawn = dlg.state() == "withdrawn"
        visible = not withdrawn and _alpha(dlg) >= 0.99
    except tk.TclError:
        withdrawn, visible = True, False
    if not visible:
        # 带着 WS_EX_TRANSPARENT 挪回屏幕会被当成「底下变了」整窗重画，必须先摘掉
        _click_through(dlg, False)
    dlg.geometry(_card_bounds(dlg, min_w=min_w, min_h=min_h, near=near))
    if visible:
        return
    try:
        # 已映射（_park_card 收起的）别再 deiconify：Tk 会整窗重显、所有控件重画一遍
        if withdrawn:
            dlg.attributes("-alpha", 0.0)
            dlg.deiconify()
        dlg.update()
        dlg.geometry(_card_bounds(dlg, min_w=min_w, min_h=min_h, near=near))
        dlg.update()
        dlg.attributes("-alpha", 1.0)
        dlg.lift()
        dlg.focus_force()
    except tk.TclError:
        pass


_GWL_EXSTYLE = -20
_WS_EX_TRANSPARENT = 0x20
_WS_EX_LAYERED = 0x80000
_PARK_POS = "+-20000+0"


def _frame_hwnd(dlg: tk.Toplevel) -> int:
    try:
        return int(dlg.wm_frame(), 16)
    except (tk.TclError, ValueError):
        return 0


def _click_through(dlg: tk.Toplevel, on: bool) -> None:
    hwnd = _frame_hwnd(dlg)
    if not hwnd:
        return
    u = layered_win.user32
    ex = u.GetWindowLongW(hwnd, _GWL_EXSTYLE)
    want = (ex | _WS_EX_TRANSPARENT | _WS_EX_LAYERED) if on else (ex & ~_WS_EX_TRANSPARENT)
    if want != ex:
        u.SetWindowLongW(hwnd, _GWL_EXSTYLE, want)


def _park_card(dlg: tk.Toplevel, give_focus_to: int = 0) -> None:
    """收起常驻卡片：不 withdraw，挪到屏幕外、全透明、鼠标穿透。

    withdraw 后再显示要把每个子控件重画一遍，这台机子上一张日程卡片也要 70~100ms；
    保持映射时系统留着画好的内容，下次 _fit_card 几毫秒就能亮出来。
    窗口一直映射着，收起时若还占着前台，要把前台还回去，否则键盘输入会落进看不见的输入框。
    """
    try:
        dlg.attributes("-alpha", 0.0)
        dlg.geometry(_PARK_POS)
        if dlg.state() == "withdrawn":
            dlg.deiconify()
            dlg.update()
        else:
            dlg.update_idletasks()
        _click_through(dlg, True)
        hwnd = _frame_hwnd(dlg)
        u = layered_win.user32
        if hwnd and u.GetForegroundWindow() == hwnd and give_focus_to and u.IsWindow(give_focus_to):
            u.SetForegroundWindow(give_focus_to)
    except tk.TclError:
        pass


def _reveal_card(
    dlg: tk.Toplevel,
    *,
    min_w: int,
    min_h: int,
    near: tuple[int, int] | None = None,
    cover: tuple[int, int, int, int] | None = None,
) -> None:
    """按内容定尺寸再显示。cover 只用来对齐位置，不锁死高度，避免把附件/报错裁掉。"""
    if cover is not None:
        cx, cy, cw, _ch = (int(v) for v in cover)
        near = (cx, cy)
        min_w = max(min_w, min(int(cw), 560))
    _fit_card(dlg, min_w=min_w, min_h=min_h, near=near)
    cb = getattr(dlg, "_on_drop_files", None)
    if callable(cb):
        win_drop.hook_files(dlg, cb)


def _pack_err_line(parent: tk.Misc, err: tk.StringVar, *, wrap: int = 400) -> tk.Frame:
    """预留报错行，空文案时也占位，避免一报错才把下面顶没。"""
    row = tk.Frame(parent, bg=_CARD_BG, height=36)
    row.pack(side="bottom", fill="x", pady=(4, 0))
    row.pack_propagate(False)
    tk.Label(
        row,
        textvariable=err,
        fg="#ff8b8b",
        bg=_CARD_BG,
        font=("Microsoft YaHei UI", 9),
        wraplength=wrap,
        justify="left",
        anchor="w",
    ).pack(fill="both", expand=True, padx=0, pady=2)
    return row


def _pack_full_text(
    parent: tk.Misc,
    sections: list[tuple[str, str]],
    *,
    wrap_px: int = 400,
    max_px: int = 420,
) -> None:
    """更新说明正文：先量高度再决定直铺还是滚动。

    正文 Frame 不能挂在 Canvas 上当 parent——那样 create_window 之前 winfo_reqheight
    量不准，canvas 高度又按 max_px 撑开，用户就看到「只有标题、下面一大片空白」。
    """
    wrap_px = max(160, int(wrap_px))
    max_px = max(80, int(max_px))
    slot = tk.Frame(parent, bg=_CARD_BG)
    slot.pack(fill="x", padx=18, pady=(10, 0))

    content = tk.Frame(slot, bg=_CARD_BG)
    f_head = ("Microsoft YaHei UI", 11, "bold")
    f_body = ("Microsoft YaHei UI", 10)
    for i, (ver, body) in enumerate(sections):
        if i:
            tk.Frame(content, bg=_CARD_BG, height=12).pack(fill="x")
        tk.Label(
            content,
            text=ver,
            fg=_CARD_FG,
            bg=_CARD_BG,
            font=f_head,
            anchor="w",
            justify="left",
        ).pack(anchor="w", fill="x")
        txt = (body or "").strip()
        if txt:
            tk.Label(
                content,
                text=txt,
                fg="#c8ceda",
                bg=_CARD_BG,
                font=f_body,
                wraplength=wrap_px,
                justify="left",
                anchor="nw",
            ).pack(anchor="w", fill="x", pady=(4, 0))

    content.update_idletasks()
    need = max(1, int(content.winfo_reqheight()))
    if need <= max_px:
        content.pack(anchor="nw", fill="x")
        return

    outer = tk.Frame(slot, bg=_CARD_BG)
    outer.pack(fill="x")
    canvas = tk.Canvas(
        outer, bg=_CARD_BG, highlightthickness=0, bd=0, relief="flat", width=wrap_px, height=max_px
    )
    sb = tk.Scrollbar(outer, orient="vertical", command=canvas.yview, width=10)
    canvas.configure(yscrollcommand=sb.set)
    sb.pack(side="right", fill="y", padx=(4, 0))
    canvas.pack(side="left", fill="x", expand=True)
    step = max(1, int(need / 24))

    def _wheel(event) -> None:
        canvas.yview_scroll(-1 if event.delta > 0 else 1, "units")

    canvas.configure(yscrollincrement=step)
    canvas.bind_all("<MouseWheel>", _wheel, add="+")
    canvas.bind("<Destroy>", lambda _e: canvas.unbind_all("<MouseWheel>"))

    win_id = canvas.create_window((0, 0), window=content, anchor="nw", width=wrap_px)

    def _sync(_event=None) -> None:
        canvas.itemconfigure(win_id, width=max(wrap_px, int(canvas.winfo_width()) or wrap_px))
        canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, wrap_px, need))

    content.bind("<Configure>", _sync)
    canvas.bind("<Configure>", _sync)
    _sync()


def _card_dialog(
    parent: tk.Tk | None,
    *,
    near: tuple[int, int] | None,
    width: int,
    height: int,
) -> tk.Toplevel:
    """无边框、置顶深色卡片（贴近主界面）。不裁圆角，避免把按钮切掉。

    创建时先藏着（withdraw），控件排完由 _fit_card / _reveal_card 按最终尺寸、最终位置一次亮出，
    否则会先看到一块空壳再变形跳位。
    """
    dlg = tk.Toplevel(parent)
    dlg.withdraw()
    dlg.overrideredirect(True)
    try:
        dlg.attributes("-alpha", 0.0)
    except tk.TclError:
        pass
    dlg.resizable(False, False)
    dlg.attributes("-topmost", True)
    dlg.configure(bg=_CARD_BG)
    if near:
        x, y = _resolve_near(near, width, height, int(dlg.winfo_screenwidth()), int(dlg.winfo_screenheight()))
        dlg.geometry(f"{width}x{height}+{x}+{y}")
    else:
        dlg.geometry(f"{width}x{height}")
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
    def ask() -> tuple[str, ...]:
        paths = filedialog.askopenfilenames(
            parent=dlg,
            title="选择图片",
            filetypes=[
                ("图片", "*.png;*.jpg;*.jpeg;*.webp;*.bmp;*.gif"),
                ("全部文件", "*.*"),
            ],
        )
        return tuple(str(p) for p in (paths or ()) if p)

    return _native_file_dialog(dlg, ask)


def _native_file_dialog(dlg: tk.Toplevel, ask):
    """系统文件框不能被无边框置顶卡片挡住；但只关当前卡片的置顶时，底下列表仍置顶会把卡片盖没。"""
    lowered: list[tk.Misc] = []

    def _lower(w: tk.Misc) -> None:
        try:
            if w.winfo_exists() and bool(w.attributes("-topmost")):
                w.attributes("-topmost", False)
                lowered.append(w)
        except Exception:
            pass

    try:
        root = dlg.nametowidget(".")
        for w in (root, *root.winfo_children()):
            _lower(w)
        if dlg not in lowered:
            _lower(dlg)
    except Exception:
        _lower(dlg)
    try:
        return ask()
    finally:
        for w in lowered:
            try:
                if w.winfo_exists():
                    w.attributes("-topmost", True)
            except Exception:
                pass
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
    pack_side: str = "top",
) -> tk.Frame:
    box = tk.Frame(parent, bg=_CARD_BG)
    box.pack(side=pack_side, fill="x", pady=(8, 0), anchor="w")
    head = tk.Frame(box, bg=_CARD_BG)
    head.pack(fill="x")
    tk.Label(head, text="图片附件", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
        side="left"
    )
    count = tk.StringVar(value="")
    tk.Label(head, textvariable=count, fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
        side="left", padx=(8, 0)
    )
    tk.Label(
        head, text="可拖入图片", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 8),
    ).pack(side="right")
    thumbs = tk.Frame(box, bg="#222733", height=96)
    thumbs.pack(fill="x", pady=(6, 0))
    thumbs.pack_propagate(False)
    btn_row = tk.Frame(box, bg=_CARD_BG)
    btn_row.pack(fill="x", pady=(8, 0))

    def total() -> int:
        return len(state["keep"]) + len(state["pending"])

    def open_path(path: Path) -> None:
        if path.is_file():
            attachments.open_file(path)

    def ingest(paths: list[str] | tuple[str, ...]) -> None:
        room = attachments.MAX_IMAGES - total()
        if room <= 0:
            err.set(f"最多 {attachments.MAX_IMAGES} 张图片")
            return
        expanded: list[Path] = []
        for raw in paths:
            p = Path(str(raw))
            if p.is_dir():
                for ext in attachments.ALLOWED_EXT:
                    expanded.extend(sorted(p.glob(f"*{ext}")))
                    expanded.extend(sorted(p.glob(f"*{ext.upper()}")))
            elif p.is_file():
                expanded.append(p)
        added = 0
        last_err = ""
        for p in expanded:
            if added >= room:
                last_err = f"最多 {attachments.MAX_IMAGES} 张，已截断"
                break
            if p.suffix.lower() not in attachments.ALLOWED_EXT:
                last_err = "只支持 png / jpg / webp / bmp / gif"
                continue
            try:
                if p.stat().st_size > attachments.MAX_SRC_BYTES:
                    last_err = "单张不超过 12MB"
                    continue
            except OSError:
                continue
            key = str(p.resolve()) if p.exists() else str(p)
            if key in state["pending"]:
                continue
            state["pending"].append(str(p))
            added += 1
        if added:
            err.set("" if not last_err else last_err)
        elif last_err:
            err.set(last_err)
        elif expanded:
            err.set("没有可添加的图片")
        refresh()

    def refresh() -> None:
        for child in thumbs.winfo_children():
            child.destroy()
        state["photos"].clear()
        count.set(f"{total()}/{attachments.MAX_IMAGES}")
        inner = tk.Frame(thumbs, bg="#222733")
        inner.pack(side="left", padx=8, pady=8)

        def add_cell(photo: ImageTk.PhotoImage | None, on_open, on_drop, label: str) -> None:
            cell = tk.Frame(inner, bg="#2a3140", width=64, height=70)
            cell.pack_propagate(False)
            cell.pack(side="left", padx=(0, 8))
            tk.Button(
                cell, text="去掉", command=on_drop, fg="#ffb4b4", bg="#2a3140",
                activebackground="#2a3140", activeforeground="#ffb4b4",
                relief="flat", bd=0, highlightthickness=0, font=("Microsoft YaHei UI", 8),
            ).pack(side="bottom")
            if photo is not None:
                state["photos"].append(photo)
                img_btn = tk.Button(
                    cell, image=photo, command=on_open, bg="#2a3140", activebackground="#2a3140",
                    relief="flat", bd=0, highlightthickness=0, cursor="hand2",
                )
                img_btn.pack(fill="both", expand=True)
            else:
                tk.Label(cell, text=label[:4] or "图", fg=_CARD_MUTED, bg="#2a3140").pack(expand=True)

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

        if not state["keep"] and not state["pending"]:
            tk.Label(
                inner, text="还没有图片，点下面按钮或直接拖进来", fg=_CARD_MUTED, bg="#222733",
                font=("Microsoft YaHei UI", 9),
            ).pack(side="left", padx=8)

        for child in btn_row.winfo_children():
            child.destroy()
        if total() < attachments.MAX_IMAGES:
            _card_btn(btn_row, "+  添加图片", add_files, accent=True).pack(side="left")
        else:
            tk.Label(
                btn_row, text=f"已满 {attachments.MAX_IMAGES} 张", fg=_CARD_MUTED, bg=_CARD_BG,
                font=("Microsoft YaHei UI", 9),
            ).pack(side="left")
        win_drop.hook_files(dlg, on_drop)

    def add_files() -> None:
        err.set("")
        if attachments.MAX_IMAGES - total() <= 0:
            err.set(f"最多 {attachments.MAX_IMAGES} 张图片")
            return
        paths = _pick_image_files(dlg)
        if paths:
            ingest(paths)

    def on_drop(files: list[str]) -> None:
        ingest(files)

    dlg._on_drop_files = on_drop

    def enable_drop(_e=None) -> None:
        win_drop.hook_files(dlg, on_drop)

    dlg.bind("<Map>", enable_drop, add="+")
    try:
        if int(dlg.winfo_ismapped()):
            enable_drop()
    except tk.TclError:
        pass
    refresh()
    return box


def _run_card_modal(
    dlg: tk.Toplevel,
    win: layered_win.LayeredPetWindow | None = None,
    *,
    on_frame=None,
    stop=None,
) -> None:
    """与分层窗泵兼容的模态循环。默认 Esc 关闭；stop() 为真时只退出循环，不销毁窗口。"""
    if stop is None:
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
    while True:
        try:
            if stop is not None and stop():
                break
            if not dlg.winfo_exists():
                break
            dlg.update()
            if win is not None:
                win.pump()
            if on_frame is not None:
                on_frame()
        except Exception:
            break
        time.sleep(0.02)


def _ask_offwork_setup(
    parent: tk.Tk | None,
    *,
    mode: str,
    start_preset: tuple[int, int] | None,
    off_preset: tuple[int, int] | None,
    remember_off: bool = True,
    near: tuple[int, int] | None = None,
    win: layered_win.LayeredPetWindow | None = None,
) -> tuple[str, tuple[int, int], bool] | None:
    """统一设置下班：卡片风无边框。返回 (mode, hm, 是否记住固定下班)。"""
    result: list[tuple[str, tuple[int, int], bool] | None] = [None]
    dlg = _card_dialog(parent, near=near, width=400, height=430)
    bar = tk.Frame(dlg, bg=_CARD_BG)
    bar.pack(side="bottom", fill="x", pady=(8, 16))
    init_mode = "flex" if mode == "flex" else "direct"
    mode_var = tk.StringVar(value=init_mode)
    remember_var = tk.BooleanVar(value=bool(remember_off))
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
    remember_row = tk.Frame(dlg, bg=_CARD_BG)
    tk.Checkbutton(
        remember_row,
        text="记住这个下班时间，第二天不用再设",
        variable=remember_var,
        fg=_CARD_FG,
        bg=_CARD_BG,
        activebackground=_CARD_BG,
        activeforeground=_CARD_FG,
        selectcolor=_CARD_BTN,
        font=("Microsoft YaHei UI", 10),
        anchor="w",
    ).pack(anchor="w")
    err = tk.StringVar(value="")
    err_lbl = tk.Label(dlg, textvariable=err, fg="#ff8b8b", bg=_CARD_BG, font=("Microsoft YaHei UI", 9))
    err_lbl.pack(padx=20, pady=(6, 0), anchor="w")

    def current_var() -> tk.StringVar:
        return start_var if mode_var.get() == "flex" else off_var

    def sync_entry_from_mode(*_a) -> None:
        entry.configure(textvariable=current_var())
        if mode_var.get() == "flex":
            tip.set("到岗时间，例如 8.45 / 9:10")
            remember_row.pack_forget()
        else:
            tip.set("下班时刻，例如 18:00")
            remember_row.pack(padx=20, pady=(10, 0), anchor="w", before=err_lbl)
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
        remember = bool(remember_var.get())
        if mode_var.get() == "flex":
            parsed = flex_time.parse_start(start_var.get())
            if parsed is None:
                err.set("到岗请填 8:30–9:30")
                return
            result[0] = ("flex", parsed, remember)
        else:
            parsed = flex_time.parse_clock(off_var.get())
            if parsed is None:
                err.set("请填合法时刻，例如 18:00")
                return
            result[0] = ("direct", parsed, remember)
        dlg.destroy()

    _card_btn(bar, "开始计时", ok, accent=True).pack(side="left", padx=(20, 6))
    _card_btn(bar, "取消", dlg.destroy).pack(side="left", padx=6)
    dlg.bind("<Return>", lambda _e: ok())
    _fit_card(dlg, min_w=400, min_h=400, near=near)
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
        if not single_instance.claim():
            os._exit(0)  # 已有实例在跑：唤起窗口并提示后退出
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
        self._schedule_list_open = False
        self._need_close_schedule_list = False
        self._tk: tk.Tk | None = None
        self._update_available = False
        self._update_info: updater.ReleaseInfo | None = None
        self._update_prompted = False
        self._update_dialog_open = False
        self._last_pin_rotate = 0.0
        self._last_key = ""
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
        self._worklog_at = 0.0
        self._worklog_dirty = False
        self._worklog_save_at = 0.0
        self._ui_prewarmed = False
        self._worklog_ui: dict | None = None
        self._schedule_ui: dict | None = None
        self._check_clock_on_boot()

        w, h = self._load_size()
        self._win_w, self._win_h = w, h
        ft, fb, fs = ornaments.layout_for(w, h)

        self.win = layered_win.LayeredPetWindow(w, h, "下班倒计时")
        self.win.set_left_click_handler(self._on_click)
        self.win.set_mouse_move_handler(self._on_mouse_move)
        self.win.set_right_click_handler(self._request_menu)
        self.win.set_request_show_handler(self._on_request_show)
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
        self._hydrate_paused_at: datetime | None = None
        self._font_kinetic = self._font_big
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
        if kinetic.playing(self._kinetic, phase):
            return
        if aid == schedules.OFFWORK_ID:
            self._start_kinetic(kinetic.OFFWORK_PHRASES)
        elif not festival.is_locked(aid):
            item = schedules.find_schedule(self.cfg, aid)
            raw = str(item.get("title") or "").strip() if item else title
            if 0 < len(raw) <= 6:
                self._start_kinetic((raw,))

    def _tick_kinetic(self, now: float) -> None:
        if kinetic.playing(self._kinetic, now):
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

    def _maybe_show_whats_new(self) -> None:
        pending = store.consume_pending_whats_new()
        last = str(self.cfg.get("last_run_version") or "").strip()
        from_ver = pending or last
        sections: list[tuple[str, str]] = []
        try:
            if from_ver and updater.is_newer(APP_VERSION, from_ver):
                sections = changelog.notes_after(from_ver, APP_VERSION)
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
        if self._kinetic is not None:
            drank = self._hydrate_showing
            self._kinetic.skip()
            self._kinetic = None
            self._hydrate_showing = False
            if drank:
                hydrate.reset_anchor(self.cfg, datetime.now())
                store.save_config(self.cfg)
            self._last_key = ""
            return
        self._maybe_skin_interact(lx, ly)
        schedules.ensure_fields(self.cfg)
        aid = schedules.active_id(self.cfg)
        # 下班项空闲「点我开始」始终进设置，不要被多日程轮换抢走
        if (aid is None or aid == schedules.OFFWORK_ID) and not self._has_target():
            self._need_dialog = True
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
        if self._esc_hidden or self._theme().kind != "neonflow":
            return
        if abs(lx - self._mouse_lx) > 2 or abs(ly - self._mouse_ly) > 2:
            self._mouse_lx, self._mouse_ly = lx, ly
            self._last_key = ""

    def _maybe_skin_interact(self, lx: int, ly: int) -> None:
        """特效皮点击互动：霹雳狂潮落雷 / 墨水落墨 / 霓虹射击 / 翻牌拨动。"""
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

    def _set_hydrate(self, on: bool) -> None:
        hydrate.set_enabled(self.cfg, on)
        self._hydrate_paused_at = None
        if not on and self._hydrate_showing:
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
            self._hydrate_paused_at = None
            return
        if self._hydrate_showing and not kinetic.playing(self._kinetic, now_m):
            self._hydrate_showing = False
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
        now = datetime.now()
        if self._hydrate_after_offwork(now):
            self._hydrate_paused_at = None
            hydrate.decide(self.cfg, now, after_offwork=True)
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
        hydrate.reset_anchor(self.cfg, now)
        store.save_config(self.cfg)
        self._start_kinetic(kinetic.HYDRATE_PHRASES)

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

    def _show_after_esc(self) -> None:
        self.win.show()
        self.win.keep_topmost()
        self._esc_hidden = False
        self._last_key = ""
        self._force_surface_sample = True

    def _on_request_show(self) -> None:
        """快捷方式/再次启动唤起：同步清掉 Ctrl 隐藏状态，避免窗可见但主循环仍挂起。"""
        if self._esc_hidden:
            self._show_after_esc()
        else:
            self.win.show()
            self.win.keep_topmost()
            self._last_key = ""
            self._force_surface_sample = True

    def _toggle_key_hide(self) -> None:
        if not self._key_hide_on() and not self._esc_hidden:
            return
        if self._esc_hidden:
            self._show_after_esc()
            return
        self.win.hide()
        self._esc_hidden = True

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
        """弹窗绕开计时器本体放，不遮挡倒计时。"""
        return _Anchor(self.win.x, self.win.y, self._win_w, self._win_h)

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
        if mode == "flex":
            self.cfg["start_h"], self.cfg["start_m"] = hm
            # 弹性每天重填到岗，不沿用固定下班点
            worklog.record_arrival(self.cfg, datetime.now(), hm)
        else:
            self.cfg["off_h"], self.cfg["off_m"] = hm
            self.cfg["remember_offwork"] = bool(remember)
        schedules.ensure_fields(self.cfg)
        schedules.set_pinned(self.cfg, schedules.OFFWORK_ID, True)
        self.cfg["active_pin_id"] = schedules.OFFWORK_ID
        self._worklog_tick(force=True)
        store.save_config(self.cfg)
        self._last_key = ""

    def _worklog_tick(self, *, force: bool = False, flush: bool = False) -> None:
        mono = time.monotonic()
        if not force and mono - self._worklog_at < 1:
            return
        self._worklog_at = mono
        now = datetime.now()
        set_today = str(self.cfg.get("start_date") or "") == self._today()
        if not worklog.should_track(now, has_target=self._has_target(), set_today=set_today):
            return
        idle = worklog.idle_seconds()
        mark = worklog.last_active_minute(now, idle)
        # 打开面板、退出都不能假装「此刻正在干活」，否则离开时间会被改成现在
        active = mark is not None and idle < worklog.IDLE_LIMIT_SEC
        if worklog.heartbeat(
            self.cfg, now, active=active, activity_min=mark, target_hm=self._off_hm()
        ):
            self._worklog_dirty = True
        if self._worklog_dirty and (flush or mono - self._worklog_save_at >= 180):
            store.save_config(self.cfg)
            self._worklog_dirty = False
            self._worklog_save_at = mono

    def _card_frame(self) -> None:
        """弹窗开着时主循环进不去，这里继续记工时并刷新倒计时，避免整窗卡死。"""
        self._worklog_tick()
        self._refresh_worklog_live()
        self._paint()

    def _worklog_dur_text(self, r: dict, now: datetime) -> str:
        """记录中的那一行按秒走；已经封账的仍用分钟。"""
        if not r.get("live") or r.get("in") is None:
            return worklog.fmt_span(r.get("dur"))
        start = int(r["in"]) * 60
        if worklog.idle_seconds() < worklog.IDLE_LIMIT_SEC:
            end = now.hour * 3600 + now.minute * 60 + now.second
        elif r.get("out") is not None:
            end = int(r["out"]) * 60
        else:
            end = start
        if end < start:
            end = start
        return worklog.fmt_elapsed(end - start) + " 记录中"

    def _refresh_worklog_live(self) -> None:
        """账本开着时，今天这一行每秒改时长，不重画整表，也不覆盖正在改的格子。"""
        ui = self._worklog_ui
        if ui is None or ui.get("stop"):
            return
        dlg = ui["dlg"]
        try:
            if not dlg.winfo_exists() or dlg.state() == "withdrawn":
                return
        except tk.TclError:
            return
        sec = int(time.monotonic())
        if ui.get("live_sec") == sec:
            return
        ui["live_sec"] = sec
        today = date.today()
        now = datetime.now()
        days = worklog.week_dates(ui["anchor"])
        touched = False
        for d, slot in zip(days, ui["slots"]):
            if d != today:
                continue
            r = worklog.row(self.cfg, d, today=today)
            text = self._worklog_dur_text(r, now)
            if slot["dur"].cget("text") != text:
                slot["dur"].configure(text=text)
            diff_text = worklog.fmt_span(r["diff"], signed=True)
            if slot["diff"].cget("text") != diff_text:
                slot["diff"].configure(text=diff_text, fg=self._worklog_diff_fg(r["diff"]))
                touched = True
            out_s = worklog.fmt_clock(r["out"])
            if slot.get("auto_out") == slot["vout"].get() and out_s != slot.get("auto_out"):
                slot["vout"].set(out_s)
                slot["auto_out"] = out_s
                edits = ui["edits"]
                for i, (ed, vin, vout, old_in, _old_out) in enumerate(edits):
                    if ed == d:
                        edits[i] = (ed, vin, vout, old_in, out_s)
                        break
                touched = True
            break
        if not touched:
            return
        rows = [worklog.row(self.cfg, d, today=today) for d in days]
        this_week = days[0] <= today <= days[-1]
        ui["week_sum"].set(worklog.summary_text("本周" if this_week else "这周", worklog.summarize(rows)))
        m = ui["anchor"]
        mrows = [worklog.row(self.cfg, d, today=today) for d in worklog.month_dates(m.year, m.month)]
        ui["month_sum"].set(worklog.summary_text(f"{m.year} 年 {m.month} 月", worklog.summarize(mrows)))

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
        tk.Label(
            body, text="发到官方仓库 Issue，我们可随时拉下来看。",
            fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9),
        ).pack(anchor="w")
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
            body, text="联系方式（邮箱 / 微信，方便我们回复你；会记住）",
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
                err.set("请留一个联系方式，不然我们没法回复你")
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
        ).pack(pady=(16, 4), anchor="w")
        tk.Label(
            body,
            text="各特效皮肤的个性化选项；后续新皮肤也会集中在这里。",
            fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9), wraplength=360, justify="left",
        ).pack(anchor="w", pady=(0, 10))

        th_frame = tk.Frame(body, bg="#1e2430", highlightthickness=1, highlightbackground="#2a3140")
        th_frame.pack(fill="x", pady=(0, 8))
        th_inner = tk.Frame(th_frame, bg="#1e2430")
        th_inner.pack(fill="x", padx=12, pady=10)
        tk.Label(
            th_inner, text="霹雳狂潮", fg=_CARD_FG, bg="#1e2430", font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(anchor="w")
        tk.Label(
            th_inner,
            text="点击台词（留空则不显示单字彩蛋，劈雷与电涌仍保留）",
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
            new_q = skin_settings.set_thunder_quote(self.cfg, quote_var.get())
            store.save_config(self.cfg)
            self._thunder_quote_step = 0
            self._last_key = ""
            err.set("已保存" if new_q else "已保存（未启用点击字效）")

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
        ).pack(pady=(16, 4), anchor="w")
        tk.Label(
            body,
            text="单击指定按键可快速隐藏/显示计时窗。建议用 `、F12 等；Ctrl/Alt 易与组合键冲突。",
            fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9), wraplength=360, justify="left",
        ).pack(anchor="w", pady=(0, 10))

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
            text="在下方按下新按键以替换",
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
        dlg = _card_dialog(self._tk_root(), near=self._dialog_near(), width=420, height=300)
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(8, 16))
        body = tk.Frame(dlg, bg=_CARD_BG)
        body.pack(side="top", fill="both", expand=True, padx=18)
        tk.Label(
            body, text="喝水提醒", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(16, 4), anchor="w")
        tk.Label(
            body,
            text="到点时卡片上闪一句「该喝水了」，不抢下班倒计时。离开座位、开会隐藏窗口、过了下班点都不会催。点一下卡片表示喝过了。",
            fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9), wraplength=360, justify="left",
        ).pack(anchor="w", pady=(0, 10))
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
            text="启用喝水提醒",
            variable=enabled_var,
            fg=_CARD_FG,
            bg=_CARD_BG,
            activebackground=_CARD_BG,
            activeforeground=_CARD_FG,
            selectcolor="#222733",
            font=("Microsoft YaHei UI", 10),
        ).pack(anchor="w", pady=(4, 0))

        def save() -> None:
            hydrate.set_interval(self.cfg, interval_var.get())
            self._set_hydrate(bool(enabled_var.get()))
            dlg.destroy()

        _card_btn(bar, "保存", save, accent=True).pack(side="left", padx=(18, 6))
        _card_btn(bar, "关闭", dlg.destroy).pack(side="left", padx=6)
        _reveal_card(dlg, min_w=420, min_h=280, near=self._dialog_near())
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

    def _ensure_worklog_ui(self) -> dict:
        ui = self._worklog_ui
        if ui is not None:
            try:
                if ui["dlg"].winfo_exists():
                    return ui
            except tk.TclError:
                pass
        ui = self._build_worklog_dialog()
        self._worklog_ui = ui
        return ui

    def _worklog_diff_fg(self, v: int | None) -> str:
        if v is None or v == 0:
            return _CARD_MUTED
        return "#ffc46b" if v > 0 else "#ff8b8b"

    def _worklog_apply(self, ui: dict) -> bool:
        changed = False
        for d, vin, vout, old_in, old_out in ui["edits"]:
            if vin.get().strip() == old_in and vout.get().strip() == old_out:
                continue
            msg = worklog.set_manual(self.cfg, d, vin.get(), vout.get())
            if msg:
                ui["err"].set(msg)
                return False
            changed = True
        if changed:
            store.save_config(self.cfg)
            self._worklog_dirty = False
            self._worklog_save_at = time.monotonic()
        return True

    def _fill_worklog(self, ui: dict) -> None:
        today = date.today()
        days = worklog.week_dates(ui["anchor"])
        ui["week_var"].set(f"{days[0].month}/{days[0].day} – {days[-1].month}/{days[-1].day}")
        ui["edits"].clear()
        rows = []
        for d, slot in zip(days, ui["slots"]):
            r = worklog.row(self.cfg, d, today=today)
            rows.append(r)
            label = f"{d.month}/{d.day} 周{worklog.WEEKDAY_CN[d.weekday()]}"
            if d == today:
                label += " · 今天"
            slot["date"].configure(
                text=label,
                fg=_CARD_FG if d.weekday() < 5 else _CARD_MUTED,
                font=("Microsoft YaHei UI", 10, "bold" if d == today else "normal"),
            )
            out_s = worklog.fmt_clock(r["out"])
            slot["auto_out"] = out_s
            slot["vin"].set(worklog.fmt_clock(r["in"]))
            slot["vout"].set(out_s)
            state = "disabled" if d > today else "normal"
            slot["ein"].configure(state=state)
            slot["eout"].configure(state=state)
            slot["dur"].configure(text=self._worklog_dur_text(r, datetime.now()))
            slot["diff"].configure(text=worklog.fmt_span(r["diff"], signed=True), fg=self._worklog_diff_fg(r["diff"]))
            ui["edits"].append((d, slot["vin"], slot["vout"], slot["vin"].get(), slot["vout"].get()))
        this_week = days[0] <= today <= days[-1]
        ui["week_sum"].set(worklog.summary_text("本周" if this_week else "这周", worklog.summarize(rows)))
        m = ui["anchor"]
        mrows = [worklog.row(self.cfg, d, today=today) for d in worklog.month_dates(m.year, m.month)]
        ui["month_sum"].set(worklog.summary_text(f"{m.year} 年 {m.month} 月", worklog.summarize(mrows)))

    def _build_worklog_dialog(self) -> dict:
        dlg = _card_dialog(self._tk_root(), near=self._dialog_near(), width=560, height=560)
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(8, 16))
        body = tk.Frame(dlg, bg=_CARD_BG)
        body.pack(side="top", fill="both", expand=True, padx=18)
        err = tk.StringVar(value="")
        _pack_err_line(body, err, wrap=500)
        tk.Label(
            body, text="工时账本", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(16, 4), anchor="w")
        tk.Label(
            body,
            text=(
                "到岗取弹性打卡（固定下班取当天首次使用），离开取最后一次键鼠操作。\n"
                "过了下班点离开 90 分钟自动封账；时间可直接改，两格清空即删除当天。"
            ),
            fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9), justify="left",
        ).pack(anchor="w", pady=(0, 10))

        cell_bg = "#1e2430"
        week_var = tk.StringVar()
        nav = tk.Frame(body, bg=_CARD_BG)
        nav.pack(fill="x", pady=(0, 8))
        table = tk.Frame(body, bg=cell_bg, highlightthickness=1, highlightbackground="#2a3140")
        table.pack(fill="x")
        for c, text in enumerate(("日期", "到岗", "离开", "时长", "比应下班")):
            tk.Label(
                table, text=text, fg=_CARD_MUTED, bg=cell_bg, font=("Microsoft YaHei UI", 9),
            ).grid(row=0, column=c, sticky="w", padx=(14 if c == 0 else 8, 8), pady=(10, 4))
        slots = []
        for i in range(1, 8):
            date_lbl = tk.Label(table, text="", fg=_CARD_FG, bg=cell_bg, font=("Microsoft YaHei UI", 10))
            date_lbl.grid(row=i, column=0, sticky="w", padx=(14, 8), pady=3)
            vin = tk.StringVar()
            vout = tk.StringVar()
            ein = tk.Entry(
                table, textvariable=vin, width=7, font=("Consolas", 11), justify="center",
                bg="#222733", fg=_CARD_FG, insertbackground=_CARD_FG, relief="flat",
                disabledbackground=cell_bg, disabledforeground=_CARD_MUTED,
            )
            eout = tk.Entry(
                table, textvariable=vout, width=7, font=("Consolas", 11), justify="center",
                bg="#222733", fg=_CARD_FG, insertbackground=_CARD_FG, relief="flat",
                disabledbackground=cell_bg, disabledforeground=_CARD_MUTED,
            )
            ein.grid(row=i, column=1, padx=8, pady=3, ipady=2)
            eout.grid(row=i, column=2, padx=8, pady=3, ipady=2)
            dur = tk.Label(table, text="", fg=_CARD_FG, bg=cell_bg, font=("Consolas", 11))
            diff = tk.Label(table, text="", fg=_CARD_MUTED, bg=cell_bg, font=("Consolas", 11))
            dur.grid(row=i, column=3, sticky="w", padx=8)
            diff.grid(row=i, column=4, sticky="w", padx=8)
            slots.append({"date": date_lbl, "vin": vin, "vout": vout, "ein": ein, "eout": eout, "dur": dur, "diff": diff})
        tk.Frame(table, bg=cell_bg, height=8).grid(row=8, column=0)
        week_sum = tk.StringVar()
        month_sum = tk.StringVar()
        tk.Label(body, textvariable=week_sum, fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 10)).pack(
            anchor="w", pady=(10, 0)
        )
        tk.Label(body, textvariable=month_sum, fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", pady=(2, 0)
        )
        ui = {
            "dlg": dlg,
            "stop": False,
            "anchor": date.today(),
            "slots": slots,
            "edits": [],
            "err": err,
            "week_var": week_var,
            "week_sum": week_sum,
            "month_sum": month_sum,
        }

        def close() -> None:
            ui["stop"] = True
            _park_card(dlg, ui.get("fg", 0))

        def save() -> None:
            if self._worklog_apply(ui):
                self._fill_worklog(ui)
                err.set("已保存")

        def shift(days: int) -> None:
            if not self._worklog_apply(ui):
                return
            ui["anchor"] = ui["anchor"] + timedelta(days=days) if days else date.today()
            err.set("")
            self._fill_worklog(ui)

        def export() -> None:
            if not self._worklog_apply(ui):
                return
            self._fill_worklog(ui)
            m = ui["anchor"]

            def ask() -> str:
                return filedialog.asksaveasfilename(
                    parent=dlg,
                    title="导出工时账本",
                    defaultextension=".csv",
                    initialfile=f"工时账本-{m.year}-{m.month:02d}.csv",
                    filetypes=[("CSV 表格", "*.csv")],
                )

            path = _native_file_dialog(dlg, ask)
            if not path:
                return
            try:
                Path(path).write_text(
                    worklog.to_csv(self.cfg, worklog.month_dates(m.year, m.month)), encoding="utf-8-sig"
                )
            except OSError as e:
                err.set(f"导出失败：{e}")
                return
            err.set(f"已导出 {m.month} 月：{path}")

        _card_btn(nav, "‹ 上周", lambda: shift(-7)).pack(side="left")
        tk.Label(nav, textvariable=week_var, fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 11, "bold")).pack(
            side="left", padx=12
        )
        _card_btn(nav, "下周 ›", lambda: shift(7)).pack(side="left")
        _card_btn(nav, "回到本周", lambda: shift(0)).pack(side="right")
        _card_btn(bar, "保存修改", save, accent=True).pack(side="left", padx=(18, 6))
        _card_btn(bar, "导出本月 CSV…", export).pack(side="left", padx=6)
        _card_btn(bar, "关闭", close).pack(side="left", padx=6)
        dlg.bind("<Return>", lambda _e: save())
        dlg.bind("<Escape>", lambda _e: close())
        return ui

    def _open_worklog_dialog(self) -> None:
        self._worklog_tick(force=True)
        ui = self._ensure_worklog_ui()
        ui["stop"] = False
        ui["fg"] = layered_win.user32.GetForegroundWindow()
        ui["err"].set("")
        ui["anchor"] = date.today()
        self._fill_worklog(ui)
        _reveal_card(ui["dlg"], min_w=560, min_h=480, near=self._dialog_near())
        _run_card_modal(ui["dlg"], self.win, on_frame=self._card_frame, stop=lambda: ui["stop"])

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
        title = schedules.schedule_countdown_title(str(item.get("title") or "日程"), done=done)
        return title, left, done, False

    def _ask_new_schedule(
        self,
        *,
        near: tuple[int, int] | None = None,
        cover: tuple[int, int, int, int] | None = None,
        schedule_id: str | None = None,
    ) -> dict | None:
        """cover=(x,y,w,h) 时盖在日程列表上，避免先藏列表再弹窗造成闪烁。"""
        result: list[dict | None] = [None]
        now = datetime.now()
        existing = schedules.find_schedule(self.cfg, schedule_id) if schedule_id else None
        editing = existing is not None
        fest_title = festival.locked_title(str(existing.get("id") or "")) if editing else None
        fest = bool(fest_title)
        if cover is not None:
            cx, cy, cw, ch = (int(v) for v in cover)
            near = (cx, cy)
            dlg = _card_dialog(self._tk_root(), near=near, width=max(480, cw), height=max(560, ch))
        else:
            near = near or self._dialog_near()
            dlg = _card_dialog(self._tk_root(), near=near, width=480, height=560)
        # 先藏着排版，排完再显示，避免空壳闪一下
        try:
            dlg.withdraw()
        except Exception:
            pass
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(8, 16))
        init_kind = "duration" if editing and str(existing.get("kind") or "") == "duration" else "clock"
        init_title = str(existing.get("title") or "") if editing else ""
        if fest:
            init_kind = "clock"
            init_title = fest_title or init_title
        init_time = "15:00"
        init_y, init_mo, init_d = now.year, now.month, now.day
        if editing:
            if init_kind == "clock":
                hm = existing.get("hm")
                if isinstance(hm, (list, tuple)) and len(hm) == 2:
                    try:
                        init_time = f"{int(hm[0])}:{int(hm[1]):02d}"
                    except (TypeError, ValueError):
                        pass
                raw = str(existing.get("date") or "")[:10]
                parts = raw.split("-")
                if len(parts) == 3:
                    try:
                        init_y, init_mo, init_d = int(parts[0]), int(parts[1]), int(parts[2])
                    except ValueError:
                        pass
            else:
                try:
                    init_time = str(max(1, int(existing.get("duration_sec") or 60) // 60))
                except (TypeError, ValueError):
                    init_time = "25"
        kind_var = tk.StringVar(value=init_kind)
        title_var = tk.StringVar(value=init_title)
        time_var = tk.StringVar(value=init_time)
        y_var = tk.StringVar(value=str(init_y))
        m_var = tk.StringVar(value=str(init_mo))
        d_var = tk.StringVar(value=str(init_d))
        tip = tk.StringVar()
        body = tk.Frame(dlg, bg=_CARD_BG)
        body.pack(side="top", fill="both", expand=True, padx=18)
        err = tk.StringVar(value="")
        _pack_err_line(body, err, wrap=420)
        attach = _new_attach_state(existing.get("images") if editing else None)
        _pack_attach_editor(
            body,
            dlg=dlg,
            state=attach,
            kind="schedule",
            owner_id=str(existing.get("id") or "") if editing else None,
            err=err,
            pack_side="bottom",
        )

        tk.Label(
            body,
            text=f"编辑{fest_title}日程" if fest else ("编辑日程" if editing else "新增日程"),
            fg=_CARD_FG,
            bg=_CARD_BG,
            font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(16, 6), anchor="w")
        if fest:
            tk.Label(
                body,
                text=f"名称固定为「{fest_title}」，可改倒计时时间；节后自动消失，不可删除。",
                fg=_CARD_MUTED,
                bg=_CARD_BG,
                font=("Microsoft YaHei UI", 9),
                wraplength=420,
                justify="left",
            ).pack(anchor="w", pady=(0, 6))
        box = tk.Frame(body, bg=_CARD_BG)
        box.pack(anchor="w")
        kind_opts = (("clock", "指定日期+时刻"),) if fest else (("clock", "指定日期+时刻"), ("duration", "倒计时长（分钟）"))
        for val, lab in kind_opts:
            tk.Radiobutton(
                box, text=lab, variable=kind_var, value=val, fg=_CARD_FG, bg=_CARD_BG,
                selectcolor=_CARD_BTN, activebackground=_CARD_BG, font=("Microsoft YaHei UI", 10),
            ).pack(anchor="w")

        tk.Label(body, text="名称", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9)).pack(
            anchor="w", pady=(8, 0)
        )
        title_ent = tk.Entry(
            body, textvariable=title_var, font=("Microsoft YaHei UI", 12), bg="#222733", fg=_CARD_FG,
            insertbackground=_CARD_FG, relief="flat", width=28,
        )
        title_ent.pack(anchor="w", ipady=5)
        if fest:
            title_ent.configure(state="disabled", disabledbackground="#1c212c", disabledforeground=_CARD_MUTED)

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

        def ok() -> None:
            err.set("")
            if fest:
                kind_var.set("clock")
                title_var.set(fest_title or title_var.get())
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
                if editing:
                    item["id"] = str(existing.get("id"))
                    if kind_var.get() == "duration" and str(existing.get("kind") or "") == "duration":
                        item["started_at"] = existing.get("started_at") or item.get("started_at")
                item["images"] = attachments.commit(
                    "schedule",
                    str(item["id"]),
                    keep=attach["keep"],
                    pending=attach["pending"],
                    removed=attach["removed"],
                )
            dlg.destroy()

        _card_btn(bar, "保存" if editing else "开始倒计时", ok, accent=True).pack(side="left", padx=(18, 6))
        _card_btn(bar, "取消", dlg.destroy).pack(side="left", padx=6)
        dlg.bind("<Return>", lambda _e: ok())
        _reveal_card(dlg, min_w=480, min_h=560, near=near, cover=cover)
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
            dlg = _card_dialog(self._tk_root(), near=near, width=max(480, cw), height=max(560, ch))
        else:
            near = self._dialog_near()
            dlg = _card_dialog(self._tk_root(), near=near, width=480, height=560)
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
        _pack_err_line(body, err, wrap=420)
        attach = _new_attach_state(existing.get("images") if existing else None)
        mid = str(existing.get("id") or "") if existing else None
        _pack_attach_editor(body, dlg=dlg, state=attach, kind="memo", owner_id=mid, err=err, pack_side="bottom")

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
            body, height=5, wrap="word", font=("Microsoft YaHei UI", 11), bg="#222733", fg=_CARD_FG,
            insertbackground=_CARD_FG, relief="flat", bd=0, highlightthickness=0, padx=8, pady=8,
        )
        text.pack(anchor="w", fill="both", expand=True, pady=(4, 8))
        if existing:
            text.insert("1.0", str(existing.get("body") or ""))

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
        _reveal_card(dlg, min_w=480, min_h=560, near=near, cover=cover)
        try:
            text.focus_set()
        except Exception:
            pass
        _run_card_modal(dlg, self.win)
        return result[0]

    def _ensure_schedule_ui(self) -> dict:
        ui = self._schedule_ui
        if ui is not None:
            try:
                if ui["dlg"].winfo_exists():
                    return ui
            except tk.TclError:
                pass
        ui = self._build_schedule_list()
        self._schedule_ui = ui
        return ui

    def _open_schedule_list(self) -> None:
        if self._schedule_list_open:
            self._need_close_schedule_list = True
            return
        schedules.ensure_fields(self.cfg)
        memos.ensure_fields(self.cfg)
        ui = self._ensure_schedule_ui()
        dlg, closed = ui["dlg"], ui["closed"]
        closed["v"] = False
        ui["fg"] = layered_win.user32.GetForegroundWindow()
        self._schedule_list_open = True
        self._need_close_schedule_list = False
        self._last_key = ""
        if ui["search_var"].get():
            ui["search_var"].set("")
        ui["show_tab"]("schedules")
        _fit_card(dlg, min_w=480, min_h=560, near=self._dialog_near())
        close = ui["close"]
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
            self._schedule_list_open = False
            self._need_close_schedule_list = False
            self._last_key = ""

    def _build_schedule_list(self) -> dict:
        dlg = _card_dialog(self._tk_root(), near=self._dialog_near(), width=480, height=560)
        closed = {"v": False}
        tab = {"name": "schedules"}
        ui: dict = {"dlg": dlg, "closed": closed, "fg": 0}

        def close() -> None:
            closed["v"] = True
            _park_card(dlg, ui["fg"])

        # 底栏先占位，保证「新增 / 关闭」永远在窗口里
        foot = tk.Frame(dlg, bg=_CARD_BG)
        foot.pack(side="bottom", fill="x", padx=16, pady=(8, 16))
        hint = tk.StringVar(value="")
        btn_row = tk.Frame(foot, bg=_CARD_BG)
        btn_row.pack(side="bottom", fill="x")
        tk.Label(
            foot, textvariable=hint, fg="#ffd28a", bg=_CARD_BG, font=("Microsoft YaHei UI", 8),
            wraplength=420, justify="left", anchor="w",
        ).pack(side="bottom", fill="x", pady=(0, 6))

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

        # 窗口还没显示时 canvas 宽度是 1。若按 1 排文字，打开会先挤成一列再弹开。
        list_w = 448
        canvas = tk.Canvas(mid, bg=_CARD_BG, highlightthickness=0, bd=0, width=list_w, height=320)
        rows = tk.Frame(canvas, bg=_CARD_BG)
        win_id = canvas.create_window((0, 0), window=rows, anchor="nw", width=list_w)

        def _sync(_e=None) -> None:
            width = canvas.winfo_width()
            if width < 50:
                width = list_w
            canvas.itemconfigure(win_id, width=width)
            canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, width, 0))

        # 绑在整个弹窗上，别用画布 <Enter>/<Leave> 切 bind_all：鼠标移到日程卡片上画布就收到 <Leave>。
        # 按像素滚、余量累积：一格（delta 120）≈60px，触控板的小 delta 也能平滑走。
        canvas.configure(yscrollincrement=1)
        wheel = {"acc": 0.0}

        def _wheel(e) -> str:
            region = canvas.bbox("all")
            if not region or region[3] - region[1] <= canvas.winfo_height():
                wheel["acc"] = 0.0
                return "break"
            px = -e.delta / 2
            if (px > 0) != (wheel["acc"] > 0):
                wheel["acc"] = 0.0
            wheel["acc"] += px
            step = int(wheel["acc"])
            if step:
                wheel["acc"] -= step
                canvas.yview_scroll(step, "units")
            return "break"

        rows.bind("<Configure>", _sync)
        canvas.bind("<Configure>", _sync)
        dlg.bind("<MouseWheel>", _wheel)
        canvas.pack(fill="both", expand=True)

        def _panel_cover() -> tuple[int, int, int, int] | None:
            try:
                return (
                    int(dlg.winfo_rootx()),
                    int(dlg.winfo_rooty()),
                    max(480, int(dlg.winfo_width())),
                    max(420, int(dlg.winfo_height())),
                )
            except Exception:
                return None

        def _after_card(refresh=None) -> None:
            """先落盘再处理列表：倒三角关列表不能把刚确定的内容丢掉。"""
            try:
                if dlg.winfo_exists():
                    dlg.lift()
                    if refresh is not None and not self._need_close_schedule_list:
                        refresh()
            except Exception:
                pass
            if self._need_close_schedule_list:
                close()

        # 列表结构没变时只改「剩余时间」那行字；整排销毁重建 + 重新排版要几十毫秒
        cards: dict = {"key": None, "whens": []}

        def rebuild() -> None:
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
                can_del = not festival.is_locked(sid)
                items.append((sid, str(s.get("title") or "日程"), rem, when, can_del, attachments.count(s)))

            aid = schedules.active_id(self.cfg)
            key = tuple(
                (sid, title, when, can_del, nimg, schedules.is_pinned(self.cfg, sid), aid == sid)
                for sid, title, _rem, when, can_del, nimg in items
            )
            if items and key == cards["key"]:
                for lbl, (_sid, _title, rem, when, _del, nimg) in zip(cards["whens"], items):
                    extra = f"  ·  {nimg}图" if nimg else ""
                    lbl.configure(text=f"{when}  ·  {rem}{extra}")
                return
            for child in rows.winfo_children():
                child.destroy()
            cards["key"] = key if items else None
            cards["whens"] = []

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
                title_lbl = tk.Label(
                    inner, text=title, fg="#7ec8ff" if active else _CARD_FG, bg="#222733",
                    font=("Microsoft YaHei UI", 11, "bold"), anchor="w",
                )
                title_lbl.pack(fill="x")
                extra = f"  ·  {nimg}图" if nimg else ""
                when_lbl = tk.Label(
                    inner, text=f"{when}  ·  {rem}{extra}", fg=_CARD_MUTED, bg="#222733",
                    font=("Microsoft YaHei UI", 9), anchor="w",
                )
                when_lbl.pack(fill="x")
                cards["whens"].append(when_lbl)
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
                can_edit = can_del or festival.is_locked(sid)
                if can_edit:
                    _card_btn(btns, "编辑", lambda s=sid: edit_schedule(s)).pack(side="left", padx=(0, 8))
                    for w in (card, inner, title_lbl, when_lbl):
                        w.bind("<Button-1>", lambda _e, s=sid: edit_schedule(s))
                if can_del:
                    def drop(s=sid) -> None:
                        hint.set("")
                        schedules.remove_schedule(self.cfg, s)
                        store.save_config(self.cfg)
                        self._last_key = ""
                        rebuild()

                    _card_btn(btns, "删除", drop, danger=True).pack(side="left")
            _sync()

        def rebuild_memos() -> None:
            cards["key"] = None
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
            item = self._ask_new_schedule(cover=_panel_cover())
            if item is not None:
                schedules.add_schedule(self.cfg, item)
                ok, msg = schedules.set_pinned(self.cfg, item["id"], True)
                if not ok:
                    try:
                        if dlg.winfo_exists():
                            hint.set(msg + "，日程已添加")
                    except Exception:
                        pass
                else:
                    self.cfg["active_pin_id"] = item["id"]
                store.save_config(self.cfg)
                self._last_key = ""
            _after_card(rebuild if item is not None else None)

        def edit_schedule(sid: str) -> None:
            hint.set("")
            item = self._ask_new_schedule(schedule_id=sid, cover=_panel_cover())
            if item is not None:
                schedules.replace_schedule(self.cfg, item)
                store.save_config(self.cfg)
                self._last_key = ""
            _after_card(rebuild if item is not None else None)

        def edit_memo(mid: str | None = None) -> None:
            hint.set("")
            data = self._ask_memo_edit(mid, cover=_panel_cover())
            if data is not None:
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
            _after_card(rebuild_memos if data is not None else None)

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
        ui.update(close=close, show_tab=show_tab, search_var=search_var)
        return ui

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
        elif op == "worklog":
            self._open_worklog_dialog()
        elif op == "toggle_key_hide":
            self._set_key_hide(not self._key_hide_on())
        elif op == "key_hide_settings":
            self._open_key_hide_dialog()
        elif op == "toggle_hydrate":
            self._set_hydrate(not self._hydrate_on())
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

    def _check_update(self, *, known: updater.ReleaseInfo | None = None) -> None:
        if self._update_dialog_open:
            return
        self._update_dialog_open = True
        self._update_prompted = True
        try:
            self._check_update_ui(known=known)
        finally:
            self._update_dialog_open = False

    def _check_update_ui(self, *, known: updater.ReleaseInfo | None = None) -> None:
        near = self._dialog_near()
        dlg = _card_dialog(self._tk_root(), near=near, width=320, height=200)
        btn_row = tk.Frame(dlg, bg=_CARD_BG)
        btn_row.pack(side="bottom", fill="x", padx=16, pady=(8, 16))

        if known is not None:
            status = tk.StringVar(value="有新版本可以用")
            detail = tk.StringVar(value=f"你现在是 {APP_VERSION}，可以升到 {known.version}")
        else:
            status = tk.StringVar(value="正在看看有没有新版本…")
            detail = tk.StringVar(value="")

        tk.Label(
            dlg, textvariable=status, fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(pady=(16, 6), padx=18, anchor="w")
        tk.Label(
            dlg, textvariable=detail, fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9),
            wraplength=270, justify="left", anchor="w",
        ).pack(padx=18, anchor="w")
        # 更新前先让用户看到这版改了什么，别让人闭着眼点「现在更新」
        notes_box = tk.Frame(dlg, bg=_CARD_BG)
        notes_box.pack(fill="x", padx=18, anchor="w")
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

        def short(msg: str, n: int = 72) -> str:
            t = (msg or "").replace("\n", " ").strip()
            return t[:n] + ("…" if len(t) > n else "")

        def clear_notes() -> None:
            for w in notes_box.winfo_children():
                w.destroy()

        def finish_idle(msg: str, sub: str = "", *, error: bool = False) -> None:
            if not alive():
                return
            state["phase"] = "idle"
            try:
                bar.stop()
                bar.pack_forget()
            except Exception:
                pass
            clear_notes()
            status.set(msg)
            detail.set(short(sub))
            set_btns([("好", on_close, False)])
            _fit_card(dlg, min_w=300, min_h=160, near=near)

        def fail(msg: str) -> None:
            head, hint = updater.friendly_error(msg)
            finish_idle(head, hint, error=True)

        def start_download(info: updater.ReleaseInfo) -> None:
            if not alive():
                return
            if updater.current_exe_path() is None:
                finish_idle("开发模式不能在线更新", "用安装好的程序才能检查更新", error=True)
                return
            state["phase"] = "download"
            state["cancel"] = False
            clear_notes()
            try:
                notes_box.pack_forget()
            except Exception:
                pass
            status.set("正在下载新版本…")
            detail.set("下完会自己装上。日程、备忘和设置都还在。")
            set_btns([("取消", on_close, False)])
            # 更新要点清掉了，窗口得跟着缩回去，不然底下一大片空白
            _fit_card(dlg, min_w=300, min_h=120, near=near)
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
                            detail.set(
                                f"已下 {done / (1024 * 1024):.1f} MB，一共 {total / (1024 * 1024):.1f} MB"
                            )
                        else:
                            detail.set(f"已下 {done / (1024 * 1024):.1f} MB")
                    elif kind == "ok":
                        path = done_box[0][1]
                        status.set("正在安装，马上就好")
                        detail.set("窗口会关一下再打开，日程和设置不会丢。")
                        bar.configure(value=100)
                        dlg.update_idletasks()
                        try:
                            updater.apply_update_and_restart(path)  # type: ignore[arg-type]
                            updater.force_exit_for_update()
                        except Exception as e:  # noqa: BLE001
                            fail(str(e))
                        return
                    elif kind == "cancel":
                        return
                    else:
                        fail(str(done_box[0][1]))
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
                updater.cleanup_update_artifacts()
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
            status.set("有新版本可以用")
            # 换行写死：Tk 不在中文里断词，一长串跟在空格后面会把前面那一小截甩成孤行
            detail.set(f"你现在是 {APP_VERSION}，可以升到 {info.version}。\n点更新后窗口会关一下再打开，日程和设置都还在。")
            clear_notes()
            try:
                notes = changelog.highlights(info.body)
            except Exception as e:  # noqa: BLE001
                store.log_exception("changelog", e)
                notes = []
            if notes:
                tk.Label(
                    notes_box, text="这一版有什么变化", fg=_CARD_FG, bg=_CARD_BG,
                    font=("Microsoft YaHei UI", 9, "bold"), anchor="w",
                ).pack(anchor="w", pady=(10, 3))
                for item in notes:
                    tk.Label(
                        notes_box, text=item, fg="#c8ceda", bg=_CARD_BG,
                        font=("Microsoft YaHei UI", 9), wraplength=268,
                        justify="left", anchor="w",
                    ).pack(anchor="w", pady=(0, 3))

            def go(inf=info) -> None:
                state["pending_dl"] = inf

            set_btns([("立即更新", go, True), ("暂不", on_close, False)])
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
                        finish_idle("这个版本不能在线更新", "请到官网手动下载安装包", error=True)
                    elif st.startswith("error:"):
                        fail(st[6:])
                    elif st == "latest":
                        finish_idle("已经是最新的了", f"当前是 {APP_VERSION}，不用更新")
                    elif st == "available" and info is not None:
                        show_available(info)
                    else:
                        finish_idle("暂时没有新版本", f"当前是 {APP_VERSION}")
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
            if env is not None:
                key = f"{key}-e{env[0] // 20}{env[1] // 20}{env[2] // 20}"
            if ornaments.has_skin(theme.kind):
                if theme.kind == "thunder":
                    # 落雷那半秒要满帧，平时只有雨在下
                    fps = ornaments.thunder_fps(stage, phase)
                elif themes.use_flip_display(theme.kind, big, self.cfg, h=h):
                    fps = 60 if self._flip_anims else (14 if stage in ("idle", "done") else 20)
                elif theme.kind in ("neonflow", "inkpulse"):
                    fps = 30 if stage == "warn" else (16 if stage in ("idle", "done") else 28)
                else:
                    period = 11.0 if stage == "warn" else (20.0 if stage == "done" else 15.5)
                    sweeping = (phase % period) < 1.95
                    fps = 30 if sweeping else (12 if stage in ("idle", "done") else 24)
                key = f"{key}-a{int(phase * fps)}"
            elif theme.kind != "ghost":
                key = f"{key}-p{int(phase * 6)}"
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
            if kinetic.playing(self._kinetic, phase):
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
                )
                kinetic.paint(
                    img,
                    self._kinetic,
                    self._font_kinetic,
                    accent,
                    phase,
                    ghost=theme.kind == "ghost",
                )
            else:
                if self._kinetic is not None:
                    self._kinetic = None
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
                    surface=surface,
                    thunder_glyphs=thunder_glyphs,
                    thunder_quote=thunder_quote,
                    neon_ammo=self._neon_ammo if theme.kind == "neonflow" else None,
                    neon_now=phase,
                    neon_planets=self._neon_planets if theme.kind == "neonflow" else None,
                    flip_anims=self._flip_anims if themes.use_flip_display(theme.kind, big, self.cfg, h=h) else None,
                    flip_now=phase,
                    flip_hit_rects=self._flip_hit_rects if themes.use_flip_display(theme.kind, big, self.cfg, h=h) else None,
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
        self._maybe_show_whats_new()
        last_save = time.monotonic()
        booted = time.monotonic()
        was_dragging = False
        was_resizing = False
        while self.running and not self.win.closed:
            try:
                self.win.pump()
                self._poll_key_hide()
                if self._esc_hidden:
                    # 单实例 ShowWindow 可能已把 hwnd 显示，但 _esc_hidden 未清 → 主循环空转像卡死
                    if self.win.hwnd and layered_win.user32.IsWindowVisible(self.win.hwnd):
                        self._show_after_esc()
                    else:
                        time.sleep(0.008)
                        continue
                if self._menu_pos is not None:
                    sx, sy = self._menu_pos
                    self._menu_pos = None
                    self._handle_menu(sx, sy)
                if self._need_dialog:
                    self._need_dialog = False
                    self._open_idle_dialog()
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
                self._worklog_tick()
                self._refresh_surface()
                self._paint()
                now = time.monotonic()
                self._prune_thunder_hits(now)
                self._prune_ink_hits(now)
                if now - last_save > 1.5:
                    self._persist_pos()
                    last_save = now
                store.flush_pending()
                if now < self._surface_hot_until or kinetic.playing(self._kinetic, now):
                    time.sleep(0.001)
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
                    time.sleep(1.0 / FPS)
                else:
                    # 无动画皮时 _paint 只在秒数变化才重绘，主循环没必要 60Hz 空转
                    time.sleep(1.0 / IDLE_FPS)
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
