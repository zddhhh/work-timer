"""日程列表、新建日程、备忘编辑窗口。"""
from __future__ import annotations

import time
import tkinter as tk
from datetime import datetime

import attachments
import festival
import flex_time
import layered_win
import memos
import schedules
import store
from card_ui import (
    _CARD_ACCENT,
    _CARD_BG,
    _CARD_BTN,
    _CARD_FG,
    _CARD_MUTED,
    _card_btn,
    _card_dialog,
    _fit_card,
    _new_attach_state,
    _pack_attach_editor,
    _pack_err_line,
    _park_card,
    _reveal_card,
    _run_card_modal,
    _sync_open_card_hide,
)


class ScheduleDialogMixin:
    """WorkTimer 的一部分，方法里的 self 就是 WorkTimer。"""

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
                    _sync_open_card_hide(dlg, self.win)
                    dlg.update()
                    self.win.pump()
                    self._card_frame()
                    self._note_beat()
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
