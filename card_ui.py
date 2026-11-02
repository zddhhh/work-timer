"""计时器弹出的深色卡片窗：定位、拖动、隐藏到屏幕外、模态等待、附件编辑。"""
from __future__ import annotations

import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog

from PIL import Image, ImageTk

import attachments
import flex_time
import layered_win
import win_drop


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
    sw = max(320, int(dlg.winfo_screenwidth()) - 24)
    sh = max(240, int(dlg.winfo_screenheight()) - 48)
    w = min(sw, max(min(min_w, sw), int(dlg.winfo_reqwidth()) + 20))
    h = min(sh, max(min(min_h, sh), int(dlg.winfo_reqheight()) + 24))
    if near:
        x, y = _resolve_near(near, w, h, sw, sh)
        return f"{w}x{h}+{x}+{y}"
    return f"{w}x{h}"


def _alpha(dlg: tk.Toplevel) -> float:
    try:
        return float(dlg.attributes("-alpha"))
    except tk.TclError:
        return 1.0


def _offscreen_bounds(bounds: str) -> str:
    """保留宽高，挪到屏幕外。deiconify 那一帧经常不听透明度，不能在屏幕上映射。"""
    size = bounds
    for mark in ("+", "-"):
        i = bounds.find(mark)
        if i > 0:
            size = bounds[:i]
            break
    return f"{size}+-20000+0"


def _geom_wh(geom: str) -> tuple[int, int]:
    cut = len(geom)
    for mark in ("+", "-"):
        i = geom.find(mark)
        if 0 < i < cut:
            cut = i
    w, h = geom[:cut].split("x", 1)
    return int(w), int(h)


def _fit_card(dlg: tk.Toplevel, *, min_w: int, min_h: int, near) -> None:
    """按内容把卡片撑开；藏着的卡片在屏幕外画完，再挪回来亮出。

    update_idletasks 只排版、不处理 WM_PAINT。直接亮出会先看到空底板和白色按钮块，
    控件再分几次画上去。必须 update() 让控件真正画完。
    第一次 deiconify 时 -alpha 经常被打回 1，所以映射之后要再设一次 0，画完再挪进屏幕。
    已经亮着时，尺寸没变就只刷新；要变高变宽就先透明，避免改尺寸那一帧闪出空底板。
    """
    try:
        if dlg.state() == "iconic":
            return
        withdrawn = dlg.state() == "withdrawn"
        visible = not withdrawn and _alpha(dlg) >= 0.99
    except tk.TclError:
        withdrawn, visible = True, False
    if not visible:
        # 带着 WS_EX_TRANSPARENT 挪回屏幕会被当成「底下变了」整窗重画，必须先摘掉
        _click_through(dlg, False)
    bounds = _card_bounds(dlg, min_w=min_w, min_h=min_h, near=near)
    try:
        if visible:
            if _geom_wh(dlg.geometry()) == _geom_wh(bounds):
                dlg.update()
                return
            dlg.attributes("-alpha", 0.0)
            dlg.update()
            dlg.geometry(bounds)
            dlg.update()
            dlg.attributes("-alpha", 1.0)
            return
        dlg.attributes("-alpha", 0.0)
        # 已映射（换页时先透明、或 _park_card 收起的）别再 deiconify：Tk 会整窗重显
        if withdrawn:
            dlg.geometry(_offscreen_bounds(bounds))
            dlg.deiconify()
            dlg.update()
            dlg.attributes("-alpha", 0.0)
            bounds = _card_bounds(dlg, min_w=min_w, min_h=min_h, near=near)
            dlg.geometry(_offscreen_bounds(bounds))
            dlg.update()
            bounds = _card_bounds(dlg, min_w=min_w, min_h=min_h, near=near)
        dlg.attributes("-alpha", 0.0)
        dlg.geometry(bounds)
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


def _hide_open_card(dlg: tk.Toplevel) -> None:
    """隐藏键把右键弹窗一起收起。已经藏过就不动。"""
    try:
        if getattr(dlg, "_key_hidden", False):
            return
        dlg._key_hidden = True
        dlg._hide_geom = dlg.geometry()
        dlg.attributes("-alpha", 0.0)
        dlg.geometry(_PARK_POS)
        _click_through(dlg, True)
    except tk.TclError:
        pass


def _show_open_card(dlg: tk.Toplevel) -> None:
    try:
        if not getattr(dlg, "_key_hidden", False):
            return
        dlg._key_hidden = False
        geom = getattr(dlg, "_hide_geom", None)
        _click_through(dlg, False)
        if dlg.state() == "withdrawn":
            dlg.deiconify()
        if geom:
            dlg.geometry(geom)
        dlg.update()
        dlg.attributes("-alpha", 1.0)
        dlg.lift()
        try:
            dlg.attributes("-topmost", True)
        except tk.TclError:
            pass
        dlg.focus_force()
    except tk.TclError:
        pass


def _sync_open_card_hide(dlg: tk.Toplevel, win) -> None:
    """弹窗循环里跟卡片用同一套隐藏键。"""
    fn = getattr(win, "dialog_hidden", None) if win is not None else None
    if fn is None:
        return
    try:
        hidden = bool(fn())
        if not dlg.winfo_exists() or dlg.state() == "iconic":
            return
    except tk.TclError:
        return
    if hidden:
        _hide_open_card(dlg)
    else:
        _show_open_card(dlg)


def _run_card_modal(
    dlg: tk.Toplevel,
    win: layered_win.LayeredPetWindow | None = None,
    *,
    on_frame=None,
    stop=None,
) -> None:
    """与分层窗泵兼容的模态循环。默认 Esc 关闭；stop() 为真时只退出循环，不销毁窗口。

    循环挡住主循环时，仍调用窗口上的 blocked_live，倒计时和动画继续走。
    隐藏键把这个窗口和卡片一起收起。
    """
    live = getattr(win, "blocked_live", None) if win is not None else None
    note = getattr(win, "note_beat", None) if win is not None else None
    if stop is None:
        dlg.bind("<Escape>", lambda _e: dlg.destroy())
    while True:
        try:
            if stop is not None and stop():
                break
            if not dlg.winfo_exists():
                break
            _sync_open_card_hide(dlg, win)
            dlg.update()
            if win is not None:
                win.pump()
            if live is not None and on_frame is not live:
                live()
            if on_frame is not None:
                on_frame()
            if note is not None:
                note()
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
