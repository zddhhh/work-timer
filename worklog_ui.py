"""工时账本窗口：一周的来了、走了，键鼠次数图，保留天数。"""
from __future__ import annotations

import time
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog

from PIL import ImageTk

import activity
import activity_chart
import keyboard_heat
import layered_win
import power_save
import store
import worklog
from card_ui import (
    _CARD_ACCENT,
    _CARD_BG,
    _CARD_FG,
    _CARD_MUTED,
    _card_btn,
    _card_dialog,
    _native_file_dialog,
    _pack_err_line,
    _park_card,
    _reveal_card,
    _run_card_modal,
)

# 七天的说明框用同一尺寸。框里固定两行：上一行对公司时间，下一行说忙闲。
_SUMMARY_W = 252
_SUMMARY_H = 58
_SUMMARY_WRAP = 228
_FOLD_BAR = "#1e2430"
_FOLD_EDGE = "#2c3444"
_FOLD_CHIP = "#2c3950"


def _fold_chip(parent: tk.Misc) -> tk.Label:
    """收起展开做成蓝底按钮，收着时更显眼。"""
    return tk.Label(
        parent, text="展开", fg="white", bg=_CARD_ACCENT,
        font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2", padx=12, pady=3,
    )


def _style_fold(lbl: tk.Label | None, opened: bool) -> None:
    if lbl is None:
        return
    lbl.configure(
        text="收起" if opened else "展开",
        bg=_FOLD_CHIP if opened else _CARD_ACCENT,
        fg="white",
        font=("Microsoft YaHei UI", 9, "bold"),
        padx=12,
        pady=3,
    )


def _apply_fold(body: tk.Misc | None, toggle: tk.Label | None, opened: bool) -> None:
    if body is None:
        return
    shown = bool(body.winfo_manager())
    if opened and not shown:
        body.pack(fill="x", pady=(8, 0))
    elif not opened and shown:
        body.pack_forget()
    _style_fold(toggle, opened)


def scroll_view(
    sheet_h: int,
    natural_h: int,
    screen_h: int,
    *,
    pad: int = 24,
    margin: int = 48,
    floor: int = 180,
) -> tuple[int, bool]:
    """中间区域给多高。屏幕装得下就用内容原高，装不下就只缩短中间。"""
    limit = max(240, int(screen_h) - int(margin))
    sheet_h = max(1, int(sheet_h))
    overflow = int(natural_h) + int(pad) - limit
    if overflow <= 0:
        return sheet_h, False
    view = min(sheet_h, max(int(floor), sheet_h - overflow))
    return view, view < sheet_h


class _SlimBar(tk.Canvas):
    """深色细条。系统滚动条在这块深底上会画成一条白杠，还带着上下箭头。"""

    def __init__(self, master: tk.Misc, command) -> None:
        super().__init__(master, width=12, height=10, bg=_CARD_BG, highlightthickness=0, bd=0)
        self._command = command
        self._first = 0.0
        self._last = 1.0
        self._grab: tuple[int, float] | None = None
        self.bind("<Configure>", lambda _e: self._draw())
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", lambda _e: setattr(self, "_grab", None))

    def set(self, first, last) -> None:
        self._first = max(0.0, min(1.0, float(first)))
        self._last = max(self._first, min(1.0, float(last)))
        self._draw()

    def _geom(self) -> tuple[int, int, int]:
        height = max(1, int(self.winfo_height() or 1))
        if self._last - self._first >= 0.999:
            return 0, height, height
        top = int(self._first * height)
        bot = int(self._last * height)
        if bot - top < 36:
            bot = top + 36
        if bot > height:
            bot = height
            top = max(0, height - 36)
        return top, bot, height

    def _draw(self) -> None:
        self.delete("thumb")
        if self._last - self._first >= 0.999:
            return
        top, bot, _height = self._geom()
        self.create_rectangle(3, top + 2, 9, max(top + 6, bot - 2), fill="#5c677c", outline="", tags="thumb")

    def _press(self, event) -> None:
        top, bot, _height = self._geom()
        if event.y < top:
            self._command("scroll", -1, "pages")
        elif event.y > bot:
            self._command("scroll", 1, "pages")
        else:
            self._grab = (int(event.y), self._first)

    def _motion(self, event) -> None:
        if self._grab is None:
            return
        y0, first0 = self._grab
        _top, _bot, height = self._geom()
        span = max(0.05, self._last - self._first)
        nxt = first0 + (int(event.y) - y0) / max(1, height)
        self._command("moveto", max(0.0, min(1.0 - span, nxt)))


def wheel_pixels(delta: int) -> int:
    """滚轮按像素走。Windows 一格大约 120，折成约 40 像素，触控板的小增量也跟着走。"""
    step = int(-int(delta) / 3)
    if step == 0:
        return -1 if int(delta) > 0 else 1
    return step


class _ClipScroll(tk.Frame):
    """固定视口，整页用 place 挪。

    画布滚动会先抄一层像素再挪子窗口，键鼠图在 Windows 上会撕开。
    整页是一个子窗口，系统挪它时把看得见的像素直接搬走，只补画新露出来的一条。
    不要在这里强制整页重画：一百多个控件一起重画，降频时就是花屏。
    """

    def __init__(self, master: tk.Misc, **kwargs) -> None:
        super().__init__(master, **kwargs)
        self.pack_propagate(False)
        self._sheet: tk.Frame | None = None
        self._offset = 0
        self._placed = 0
        self._yscrollcommand = None

    def attach(self, sheet: tk.Frame) -> None:
        self._sheet = sheet
        self._placed = 0
        sheet.place(x=0, y=0, relwidth=1.0)

    def set_yscrollcommand(self, command) -> None:
        self._yscrollcommand = command

    def _view_h(self) -> int:
        # 排版之后实际高度才算数。只用设定高度时，窗口被压矮，底下会滚不到。
        actual = int(self.winfo_height() or 0)
        if actual > 1:
            return actual
        return max(1, int(self.cget("height") or 1))

    def _content_h(self) -> int:
        sheet = self._sheet
        if sheet is None:
            return 1
        return max(1, int(sheet.winfo_reqheight()))

    def _span(self) -> tuple[float, float]:
        total = self._content_h()
        view = self._view_h()
        if total <= view:
            return (0.0, 1.0)
        first = self._offset / total
        return (first, min(1.0, (self._offset + view) / total))

    def refresh(self) -> None:
        total = self._content_h()
        view = self._view_h()
        self._offset = max(0, min(self._offset, max(0, total - view)))
        if self._sheet is not None and self._placed != self._offset:
            self._placed = self._offset
            self._sheet.place(x=0, y=-self._offset, relwidth=1.0)
        if self._yscrollcommand is not None:
            first, last = self._span()
            self._yscrollcommand(first, last)

    def yview(self, *args):
        if not args:
            return self._span()
        if args[0] == "moveto" and len(args) >= 2:
            self._offset = int(float(args[1]) * self._content_h())
            self.refresh()
        elif args[0] == "scroll" and len(args) >= 2:
            count = int(float(args[1]))
            what = str(args[2]) if len(args) > 2 else "units"
            step = self._view_h() if what == "pages" else 1
            self._offset += count * step
            self.refresh()
        return None

    def yview_moveto(self, fraction: float) -> None:
        self.yview("moveto", fraction)

    def yview_scroll(self, number: int, what: str) -> None:
        self.yview("scroll", number, what)


class WorklogDialogMixin:
    """WorkTimer 的一部分，方法里的 self 就是 WorkTimer。"""

    def _worklog_dur_text(self, r: dict, now: datetime) -> str:
        """记录中的那一行按秒走；已经封账的仍用分钟。"""
        if r.get("held") or not r.get("live") or r.get("in") is None:
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
        return worklog.fmt_elapsed(end - start) + " · 还在记"

    def _sync_doubt(self, slot: dict, r: dict, hidden: bool) -> None:
        row = slot.get("doubt_row")
        if row is None:
            return
        text = "" if hidden else str(r.get("doubt") or "")
        if not text:
            if row.winfo_manager():
                row.grid_remove()
            return
        if slot["doubt"].cget("text") != text:
            slot["doubt"].configure(text=text)
        if not row.winfo_manager():
            row.grid(row=2, column=1, columnspan=8, sticky="w", pady=(0, 6))

    def _refresh_worklog_live(self) -> None:
        """账本开着时，今天这一行每秒改时长，不重画整表，也不覆盖正在改的格子。"""
        ui = self._worklog_ui
        if ui is None or ui.get("stop") or ui.get("minimized"):
            return
        dlg = ui["dlg"]
        try:
            if not dlg.winfo_exists() or dlg.state() == "withdrawn":
                return
        except tk.TclError:
            return
        # 手指还在滑时改字、换图，会把正在移动的卡片撕开。
        mono = time.monotonic()
        if mono < float(ui.get("scroll_until") or 0):
            return
        activity_chart.collect(ui)
        sec = int(mono)
        if ui.get("live_sec") == sec:
            return
        ui["live_sec"] = sec
        today = date.today()
        now = datetime.now()
        # 图在后台画；节电时少画几张，读数照样每秒走。
        gap = 3.0 if power_save.saving() else 1.0
        if mono - float(ui.get("chart_live_at") or 0) >= gap:
            ui["chart_live_at"] = mono
            self._paint_activity_chart(ui)
        days = worklog.week_dates(ui["anchor"])
        touched = False
        for d, slot in zip(days, ui["slots"]):
            if d != today:
                continue
            r = worklog.row(self.cfg, d, today=today)
            text = self._worklog_dur_text(r, now)
            if slot["dur"].cget("text") != text:
                slot["dur"].configure(text=text)
            came = worklog.fmt_clock(r["in"])
            left = worklog.fmt_clock(r["out"])
            if slot["came"].cget("text") != came:
                slot["came"].configure(text=came)
                touched = True
            if slot["left"].cget("text") != left:
                slot["left"].configure(text=left)
                touched = True
            note_text = worklog.company_span(r.get("note_in"), r.get("note_out"))
            if slot["note_dur"].cget("text") != note_text:
                slot["note_dur"].configure(text=note_text)
            summary = worklog.day_summary(self.cfg, d, r)
            pace = slot.get("summary_pace")
            shown = slot["summary"].cget("text")
            if pace is not None and pace.cget("text"):
                shown = f"{shown}\n{pace.cget('text')}" if shown else pace.cget("text")
            if shown != summary:
                self._paint_day_copy(
                    slot, summary, self._note_gap_fg(r.get("arrive_gap"), r.get("leave_gap")),
                )
            else:
                self._fit_day_copy(slot)
            self._follow_declared(ui, d, slot, "in", worklog.fmt_clock(r["note_in"]))
            self._follow_declared(ui, d, slot, "out", worklog.fmt_clock(r["note_out"]))
            self._sync_doubt(slot, r, False)
            break
        if not touched:
            self._set_habit(ui, days, today)
            return
        rows = [worklog.row(self.cfg, d, today=today) for d in days]
        this_week = days[0] <= today <= days[-1]
        ui["week_sum"].set(worklog.summary_text("本周" if this_week else "这周", worklog.summarize(rows)))
        m = ui["anchor"]
        mrows = [worklog.row(self.cfg, d, today=today) for d in worklog.month_dates(m.year, m.month)]
        ui["month_sum"].set(worklog.summary_text(f"{m.year} 年 {m.month} 月", worklog.summarize(mrows)))
        self._set_habit(ui, days, today)

    def _set_habit(self, ui: dict, days: list, today: date) -> None:
        if ui.get("habit_sum") is None:
            return
        if not worklog.tracking_enabled(self.cfg):
            lbl = ui.get("habit_lbl")
            if lbl is not None and lbl.winfo_manager():
                lbl.pack_forget()
            return
        this_week = days[0] <= today <= days[-1]
        text = worklog.habit_text(self.cfg, days, today, this_week=this_week)
        ui["habit_sum"].set(text)
        lbl = ui.get("habit_lbl")
        month = ui.get("month_lbl")
        if lbl is None:
            return
        shown = bool(lbl.winfo_manager())
        if text and not shown:
            lbl.pack(anchor="w", pady=(2, 0), before=month)
        elif not text and shown:
            lbl.pack_forget()

    def _sync_worklog_privacy(self, ui: dict) -> None:
        """关闭工时记录时隐藏历史，但不删除本地数据。"""
        on = worklog.tracking_enabled(self.cfg)
        var = ui.get("track_on")
        if var is not None:
            var.set(on)
        week_lbl = ui.get("week_sum_lbl")
        month_lbl = ui.get("month_lbl")
        habit_lbl = ui.get("habit_lbl")
        table = ui.get("table")
        notice = ui.get("history_notice")
        if on:
            if week_lbl is not None and not week_lbl.winfo_manager():
                week_lbl.pack(anchor="w", pady=(8, 0))
            if month_lbl is not None and not month_lbl.winfo_manager():
                month_lbl.pack(anchor="w", pady=(2, 4))
            if notice is not None and notice.winfo_manager():
                notice.pack_forget()
            if table is not None and not table.winfo_manager():
                table.pack(fill="x", pady=(10, 0))
        else:
            for widget in (week_lbl, habit_lbl, month_lbl, table):
                if widget is not None and widget.winfo_manager():
                    widget.pack_forget()
            if notice is not None and not notice.winfo_manager():
                notice.pack(fill="x", pady=(10, 0))
        for key in ("save_btn", "export_btn"):
            btn = ui.get(key)
            if btn is not None:
                btn.configure(state="normal" if on else "disabled")

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

    def _follow_declared(self, ui: dict, d: date, slot: dict, field: str, text: str) -> None:
        """默认值后到时填进格子。用户已经改过的那一格不动。"""
        shown_key = "shown_" + field
        var = slot["vin" if field == "in" else "vout"]
        if slot.get(shown_key) != var.get() or text == slot.get(shown_key):
            return
        var.set(text)
        slot[shown_key] = text
        edits = ui.get("edits") or []
        for i, (ed, vin, vout, old_in, old_out) in enumerate(edits):
            if ed != d:
                continue
            if field == "in":
                edits[i] = (ed, vin, vout, text, old_out)
            else:
                edits[i] = (ed, vin, vout, old_in, text)
            break

    def _paint_day_copy(self, slot: dict, text: str, fg: str, *, quiet: bool = False) -> None:
        """第一句是和公司时间的差别，第二句是这一天哪里忙。两句分开，都从框的左上角写起。"""
        parts = (text or "").split("\n", 1)
        head = parts[0] if parts else ""
        body = parts[1] if len(parts) > 1 else ""
        slot["summary"].configure(text=head, fg=_CARD_MUTED if quiet or not head else fg)
        pace = slot.get("summary_pace")
        if pace is not None:
            pace.configure(text=body, fg=_CARD_MUTED if quiet or not body else "#d5deea")
        self._fit_day_copy(slot)

    def _fit_day_copy(self, slot: dict) -> None:
        """说明框每天一样大。字多字少只影响框里的内容，不改变框的尺寸。"""
        box = slot.get("summary_box")
        if box is None:
            return
        # 字是 pack 进去的。grid_propagate 管不住它，框会跟着字缩成一小块。
        if box.pack_propagate():
            box.pack_propagate(False)
        if not box.winfo_manager():
            box.grid(row=0, column=8, rowspan=2, sticky="nsew", padx=(8, 12), pady=8)
        for key in ("summary", "summary_pace"):
            label = slot.get(key)
            if label is None:
                continue
            current = int(float(str(label.cget("wraplength") or 0)))
            if current != _SUMMARY_WRAP:
                label.configure(wraplength=_SUMMARY_WRAP)

    def _note_gap_fg(self, arrive: int | None, leave: int | None) -> str:
        vals = [v for v in (arrive, leave) if isinstance(v, int)]
        if not vals or all(v == 0 for v in vals):
            return _CARD_MUTED
        if any(v > 0 for v in vals):
            return "#ffc46b"
        return "#ff8b8b"

    def _worklog_apply(self, ui: dict) -> bool:
        changed = False
        for d, vin, vout, old_in, old_out in ui["edits"]:
            if vin.get().strip() == old_in and vout.get().strip() == old_out:
                continue
            msg = worklog.set_note(self.cfg, d, vin.get(), vout.get())
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
        self._sync_worklog_privacy(ui)
        today = date.today()
        sync_declared = getattr(self, "_sync_declared", None)
        if callable(sync_declared) and sync_declared(today):
            store.save_config(self.cfg)
        earliest = today - timedelta(days=activity.keep_days(self.cfg))
        week = worklog.week_dates(ui["anchor"])
        if week[0] > today or week[-1] < earliest:
            ui["anchor"] = today
            week = worklog.week_dates(today)
        days = week
        ui["week_var"].set(f"{days[0].month}/{days[0].day} – {days[-1].month}/{days[-1].day}")
        self._sync_week_nav(ui, today, earliest)
        ui["edits"].clear()
        rows = []
        for i, (d, slot) in enumerate(zip(days, ui["slots"])):
            too_old = d < earliest
            r = worklog.row(self.cfg, d, today=today)
            rows.append(r)
            label = f"{d.month}/{d.day}  周{worklog.WEEKDAY_CN[d.weekday()]}"
            if too_old:
                fg = "#3a4150"
            elif d == today:
                fg = "#9ecbff"
            elif d.weekday() < 5:
                fg = _CARD_FG
            else:
                fg = _CARD_MUTED
            slot["date"].configure(
                text=label,
                fg=fg,
                font=("Microsoft YaHei UI", 10, "bold" if d == today else "normal"),
            )
            slot["came"].configure(text="" if too_old else worklog.fmt_clock(r["in"]))
            slot["left"].configure(text="" if too_old else worklog.fmt_clock(r["out"]))
            note_in = "" if too_old else worklog.fmt_clock(r["note_in"])
            note_out = "" if too_old else worklog.fmt_clock(r["note_out"])
            slot["vin"].set(note_in)
            slot["vout"].set(note_out)
            slot["shown_in"] = note_in
            slot["shown_out"] = note_out
            state = "disabled" if d > today or too_old else "normal"
            slot["ein"].configure(state=state)
            slot["eout"].configure(state=state)
            slot["dur"].configure(text="" if too_old else self._worklog_dur_text(r, datetime.now()))
            slot["note_dur"].configure(
                text="" if too_old else worklog.company_span(r.get("note_in"), r.get("note_out")),
            )
            self._paint_day_copy(
                slot,
                "" if too_old else worklog.day_summary(self.cfg, d, r),
                _CARD_MUTED if too_old else self._note_gap_fg(r.get("arrive_gap"), r.get("leave_gap")),
                quiet=too_old,
            )
            slot["day"] = None if too_old else d
            self._sync_doubt(slot, r, too_old)
            can_reset = d == today and bool(r.get("note_custom")) and not too_old
            slot["reset"].configure(
                text="恢复默认" if can_reset else "",
                fg=_CARD_ACCENT if can_reset else _CARD_MUTED,
                cursor="hand2" if can_reset else "arrow",
            )
            if d == today:
                row_bg = "#243044"
            elif i % 2:
                row_bg = "#1b212d"
            else:
                row_bg = "#202634"
            for w in slot.get("row_widgets", ()):
                w.configure(bg=row_bg)
            slot["card"].configure(highlightbackground="#38506f" if d == today else "#2c3444")
            show_today = d == today and not too_old
            slot["today_tag"].configure(
                text="今天" if show_today else "",
                fg="#9ecbff" if show_today else row_bg,
                bg=row_bg,
                highlightthickness=0,
            )
            field = "#3d4a62" if state == "normal" else row_bg
            border = "#9eb0cc" if state == "normal" else "#3a4254"
            for w in (slot["ein"], slot["eout"]):
                w.configure(
                    bg=field,
                    highlightthickness=1,
                    highlightbackground=border,
                    highlightcolor="#7eb6ff",
                    disabledbackground=row_bg,
                )
            ui["edits"].append((d, slot["vin"], slot["vout"], slot["vin"].get(), slot["vout"].get()))
        this_week = days[0] <= today <= days[-1]
        ui["week_sum"].set(worklog.summary_text("本周" if this_week else "这周", worklog.summarize(rows)))
        m = ui["anchor"]
        mrows = [worklog.row(self.cfg, d, today=today) for d in worklog.month_dates(m.year, m.month)]
        ui["month_sum"].set(worklog.summary_text(f"{m.year} 年 {m.month} 月", worklog.summarize(mrows)))
        self._set_habit(ui, days, today)
        if ui.get("act_on") is not None:
            ui["act_on"].set(activity.enabled(self.cfg))
        if ui.get("card_on") is not None:
            ui["card_on"].set(activity.show_on_card(self.cfg))
        self._sync_worklog_privacy(ui)
        if ui.get("minimized"):
            return
        self._fit_worklog_width(ui)
        self._paint_activity_chart(ui)

    def _paint_activity_chart(self, ui: dict | None = None, *, background: bool = True) -> None:
        """图交给后台线程画，主线程不等。画好由 _refresh_worklog_live 里的 collect 换上。"""
        ui = ui if ui is not None else self._worklog_ui
        if ui is None or ui.get("today_lbl") is None or ui.get("minimized"):
            return
        try:
            if not ui["dlg"].winfo_exists():
                return
        except tk.TclError:
            return
        today = date.today()
        days = worklog.week_dates(ui["anchor"])
        lo, hi = self._week_day_bounds(ui, today)
        focus = ui.get("chart_day") or today
        if focus > hi:
            focus = hi
        if focus < lo:
            focus = lo
        ui["chart_day"] = focus
        off = "#3a4150"
        for widget, ok in ((ui.get("day_prev"), focus > lo), (ui.get("day_next"), focus < hi)):
            if widget is not None:
                widget.configure(fg=_CARD_FG if ok else off, cursor="hand2" if ok else "arrow")
        day_var = ui.get("day_var")
        if day_var is not None:
            if focus == today:
                caption = f"今天 {focus.month}/{focus.day}"
            elif focus == today - timedelta(days=1):
                caption = f"昨天 {focus.month}/{focus.day}"
            else:
                caption = f"{focus.month}/{focus.day} 周{worklog.WEEKDAY_CN[focus.weekday()]}"
            day_var.set(caption)
        if activity.settle(self.cfg, datetime.now()):
            self._activity_dirty = True
        brief = ui.get("chart_brief")
        if brief is not None:
            brief.set(self._chart_brief(focus, today))
        self._apply_chart_open(ui)
        self._apply_heat_open(ui)
        keyboard_heat.paint_into(
            ui, self.cfg, focus, today, enabled=activity.enabled(self.cfg),
        )
        if activity.chart_open(self.cfg):
            activity_chart.paint_into(
                ui,
                self.cfg,
                today=today,
                days=days,
                enabled=activity.enabled(self.cfg),
                this_week=days[0] <= today <= days[-1],
                focus=focus,
                style=activity.chart_style(self.cfg),
                mode=activity.chart_view(self.cfg),
                background=background,
            )
        self._style_chart_buttons(ui)

    def _style_chart_buttons(self, ui: dict) -> None:
        cur = activity.chart_style(self.cfg)
        for key, btn in (ui.get("chart_btns") or {}).items():
            on = key == cur
            btn.configure(
                fg=_CARD_FG if on else _CARD_MUTED,
                font=("Microsoft YaHei UI", 9, "bold" if on else "normal"),
            )
        view = activity.chart_view(self.cfg)
        for key, btn in (ui.get("view_btns") or {}).items():
            on = key == view
            btn.configure(
                fg=_CARD_FG if on else _CARD_MUTED,
                font=("Microsoft YaHei UI", 9, "bold" if on else "normal"),
            )
        self._style_heat(ui)

    def _set_chart_style(self, ui: dict, style: str) -> None:
        if activity.chart_style(self.cfg) == style:
            return
        activity.set_chart_style(self.cfg, style)
        store.save_config(self.cfg)
        self._style_chart_buttons(ui)
        ui["chart_sig"] = None
        self._paint_activity_chart(ui)

    def _set_chart_view(self, ui: dict, view: str) -> None:
        if activity.chart_view(self.cfg) == view:
            return
        activity.set_chart_view(self.cfg, view)
        store.save_config(self.cfg)
        self._style_chart_buttons(ui)
        ui["chart_sig"] = None
        self._paint_activity_chart(ui)

    def _style_heat(self, ui: dict) -> None:
        view = activity.heat_view(self.cfg)
        for key, btn in (ui.get("heat_view_btns") or {}).items():
            on = key == view
            btn.configure(
                fg=_CARD_FG if on else _CARD_MUTED,
                font=("Microsoft YaHei UI", 9, "bold" if on else "normal"),
            )

    def _set_heat_view(self, ui: dict, view: str) -> None:
        opening = not activity.heat_open(self.cfg)
        if activity.heat_view(self.cfg) == view and not opening:
            return
        activity.set_heat_view(self.cfg, view)
        if opening:
            activity.set_heat_open(self.cfg, True)
        store.save_config(self.cfg)
        ui["heat_sig"] = None
        ui["heat_hover"] = False
        self._apply_heat_open(ui)
        self._style_heat(ui)
        self._paint_activity_chart(ui)

    def _chart_brief(self, focus: date, today: date) -> str:
        if not activity.enabled(self.cfg):
            return "没在记键鼠"
        counted = activity.counts(self.cfg, focus)
        keys = int(counted.get("keys") or 0)
        clicks = int(counted.get("clicks") or 0)
        if keys <= 0 and clicks <= 0:
            return "还没有键鼠"
        day = "今天" if focus == today else ("昨天" if focus == today - timedelta(days=1) else f"{focus.month}/{focus.day}")
        return f"{day}敲了 {activity.fmt_count(keys)} 下 · 点了 {activity.fmt_count(clicks)} 次"

    def _apply_chart_open(self, ui: dict) -> None:
        _apply_fold(ui.get("chart_body"), ui.get("chart_toggle"), activity.chart_open(self.cfg))

    def _toggle_chart(self, ui: dict) -> None:
        activity.set_chart_open(self.cfg, not activity.chart_open(self.cfg))
        store.save_config(self.cfg)
        ui["chart_sig"] = None
        self._apply_chart_open(ui)
        self._paint_activity_chart(ui)

    def _ensure_worklog_dock(self) -> tk.Toplevel | None:
        dock = getattr(self, "_worklog_dock", None)
        if dock is not None:
            try:
                if dock.winfo_exists():
                    return dock
            except tk.TclError:
                pass
        root = self._tk_root()
        dock = tk.Toplevel(root)
        dock.withdraw()
        dock.overrideredirect(True)
        dock.resizable(False, False)
        try:
            dock.attributes("-topmost", True)
        except tk.TclError:
            pass
        dock.configure(bg=_CARD_ACCENT)
        btn = tk.Label(
            dock, text="工时账本", fg="white", bg=_CARD_ACCENT,
            font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2", padx=12, pady=4,
        )
        btn.pack()
        btn.bind("<Button-1>", lambda _e: self._restore_worklog(self._ensure_worklog_ui()))
        dock.bind("<Button-1>", lambda _e: self._restore_worklog(self._ensure_worklog_ui()))
        self._worklog_dock = dock
        return dock

    def _place_worklog_dock(self) -> None:
        if not getattr(self, "_worklog_docked", False):
            return
        dock = getattr(self, "_worklog_dock", None)
        if dock is None:
            return
        try:
            if not dock.winfo_exists():
                return
            if getattr(self, "_esc_hidden", False):
                dock.withdraw()
                return
        except tk.TclError:
            return
        win = getattr(self, "win", None)
        try:
            dock.update_idletasks()
            bw = max(1, int(dock.winfo_reqwidth()))
            bh = max(1, int(dock.winfo_reqheight()))
            if win is not None:
                area = layered_win.work_area()
                x = int(win.x) + max(0, (int(getattr(self, "_win_w", bw)) - bw) // 2)
                y = int(win.y) - bh + 6
                if y < int(area.top):
                    y = int(win.y) + 4
                x = max(int(area.left), min(x, int(area.right) - bw))
            else:
                x, y = 40, 40
            if dock.state() == "withdrawn":
                dock.deiconify()
            dock.geometry(f"{bw}x{bh}+{x}+{y}")
            dock.attributes("-topmost", True)
            dock.lift()
        except tk.TclError:
            pass

    def _show_worklog_dock(self) -> None:
        self._worklog_docked = True
        if self._ensure_worklog_dock() is None:
            return
        self._place_worklog_dock()

    def _hide_worklog_dock(self) -> None:
        self._worklog_docked = False
        dock = getattr(self, "_worklog_dock", None)
        if dock is None:
            return
        try:
            dock.withdraw()
        except tk.TclError:
            pass

    def _minimize_worklog(self, ui: dict) -> None:
        dlg = ui.get("dlg")
        if dlg is None or ui.get("minimized"):
            return
        try:
            ui["dock_near"] = (int(dlg.winfo_x()), int(dlg.winfo_y()))
        except tk.TclError:
            ui["dock_near"] = None
        ui["minimized"] = True
        _park_card(dlg, ui.get("fg", 0))
        self._show_worklog_dock()

    def _restore_worklog(self, ui: dict) -> None:
        dlg = ui.get("dlg")
        if dlg is None:
            return
        if not ui.get("minimized"):
            try:
                dlg.lift()
                dlg.focus_force()
            except tk.TclError:
                pass
            return
        ui["minimized"] = False
        self._hide_worklog_dock()
        self._fill_worklog(ui)
        self._fit_worklog_scroll(ui)
        near = ui.get("dock_near") or self._dialog_near()
        _reveal_card(
            dlg,
            min_w=int(ui.get("content_w") or (activity_chart.W * 2 + activity_chart.GAP)) + 48,
            min_h=420,
            near=near,
        )

    def _apply_heat_open(self, ui: dict) -> None:
        _apply_fold(ui.get("heat_body"), ui.get("heat_toggle"), activity.heat_open(self.cfg))

    def _toggle_heat(self, ui: dict) -> None:
        activity.set_heat_open(self.cfg, not activity.heat_open(self.cfg))
        store.save_config(self.cfg)
        ui["heat_sig"] = None
        ui["heat_hover"] = False
        self._apply_heat_open(ui)
        self._paint_activity_chart(ui)

    def _week_day_bounds(self, ui: dict, today: date) -> tuple[date, date]:
        """左边按天翻，只在当前选中的这一周里，而且不超过今天。"""
        week = worklog.week_dates(ui["anchor"])
        earliest = today - timedelta(days=activity.keep_days(self.cfg))
        lo = max(week[0], earliest)
        hi = min(week[-1], today)
        if hi < lo:
            hi = lo
        return lo, hi

    def _sync_week_nav(self, ui: dict, today: date, earliest: date) -> None:
        week = worklog.week_dates(ui["anchor"])
        can_prev = week[0] - timedelta(days=1) >= earliest
        can_next = week[0] + timedelta(days=7) <= today
        here = week[0] <= today <= week[-1]
        on, off = _CARD_FG, "#3a4150"

        def paint(widget: tk.Widget | None, ok: bool, accent: bool = False) -> None:
            if widget is None:
                return
            if accent:
                fg = _CARD_MUTED if ok else _CARD_ACCENT
                cursor = "arrow" if ok else "hand2"
            else:
                fg = on if ok else off
                cursor = "hand2" if ok else "arrow"
            widget.configure(fg=fg, cursor=cursor)

        paint(ui.get("week_prev"), can_prev)
        paint(ui.get("week_next"), can_next)
        paint(ui.get("week_home"), here, accent=True)

    def _build_worklog_dialog(self) -> dict:
        pair_w = activity_chart.W * 2 + activity_chart.GAP
        dlg = _card_dialog(self._tk_root(), near=self._dialog_near(), width=pair_w + 48, height=868)
        bar = tk.Frame(dlg, bg=_CARD_BG)
        bar.pack(side="bottom", fill="x", pady=(6, 14))
        err = tk.StringVar(value="")
        err_row = _pack_err_line(dlg, err, wrap=pair_w)
        err_row.pack_configure(padx=16)
        sums = tk.Frame(dlg, bg=_CARD_BG)
        sums.pack(side="bottom", fill="x", padx=16)
        week_sum = tk.StringVar()
        habit_sum = tk.StringVar()
        month_sum = tk.StringVar()
        week_sum_lbl = tk.Label(
            sums, textvariable=week_sum, fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 10),
            wraplength=pair_w, justify="left",
        )
        week_sum_lbl.pack(anchor="w", pady=(8, 0))
        habit_lbl = tk.Label(
            sums, textvariable=habit_sum, fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 10),
            wraplength=pair_w, justify="left",
        )
        month_lbl = tk.Label(
            sums, textvariable=month_sum, fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9),
            wraplength=pair_w, justify="left",
        )
        month_lbl.pack(anchor="w", pady=(2, 4))
        body = tk.Frame(dlg, bg=_CARD_BG)
        body.pack(side="top", fill="both", expand=True, padx=16)
        top = tk.Frame(body, bg=_CARD_BG)
        top.pack(fill="x", pady=(8, 6))
        tk.Label(
            top, text="工时账本", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 13, "bold"),
        ).pack(side="left")
        min_toggle = tk.Label(
            top, text="最小化", fg="white", bg=_FOLD_CHIP,
            font=("Microsoft YaHei UI", 9, "bold"), cursor="hand2", padx=12, pady=3,
        )
        min_toggle.pack(side="right", padx=(10, 0), pady=1)
        week_var = tk.StringVar()
        nav = tk.Frame(top, bg=_CARD_BG)
        nav.pack(side="right")
        scroll_host = tk.Frame(body, bg=_CARD_BG)
        scroll_host.pack(anchor="nw", fill="y", expand=True)
        scroll = _ClipScroll(
            scroll_host, bg=_CARD_BG, highlightthickness=0, bd=0,
            width=pair_w, height=200,
        )
        gutter = tk.Frame(scroll_host, width=12, bg=_CARD_BG, highlightthickness=0, bd=0)
        gutter.pack_propagate(False)
        gutter.pack(side="right", fill="y")

        def _on_scroll(*args) -> None:
            ui["scroll_until"] = time.monotonic() + 0.25
            if args and args[0] == "scroll":
                count = int(float(args[1]))
                what = str(args[2]) if len(args) > 2 else "units"
                if what == "pages":
                    scroll.yview_scroll(count, "pages")
                else:
                    scroll.yview_scroll(count * 28, "units")
                return
            scroll.yview(*args)

        scroll_sb = _SlimBar(gutter, _on_scroll)
        scroll.set_yscrollcommand(scroll_sb.set)
        scroll.pack(side="left", fill="y", expand=True)
        sheet = tk.Frame(scroll, bg=_CARD_BG)
        scroll.attach(sheet)
        track_on = tk.BooleanVar(value=worklog.tracking_enabled(self.cfg))
        act_on = tk.BooleanVar(value=activity.enabled(self.cfg))

        card_on = tk.BooleanVar(value=activity.show_on_card(self.cfg))

        def toggle_track() -> None:
            self._set_worklog_tracking(bool(track_on.get()))
            self._fill_worklog(ui)
            ui["err"].set(
                "" if track_on.get() else "已停止记录并隐藏工时历史；重新开启后会恢复显示。"
            )

        def toggle_act() -> None:
            on = bool(act_on.get())
            activity.set_enabled(self.cfg, on)
            if not on:
                card_on.set(False)
            self.win.listen_raw_input(True)
            self._tally_at = 0.0
            store.save_config(self.cfg)
            self._paint_activity_chart(ui)

        def toggle_card() -> None:
            activity.set_show_on_card(self.cfg, bool(card_on.get()))
            act_on.set(activity.enabled(self.cfg))
            self.win.listen_raw_input(True)
            self._tally_at = 0.0
            store.save_config(self.cfg)
            self._paint_activity_chart(ui)

        acts = tk.Frame(sheet, bg=_CARD_BG)
        acts.pack(fill="x")
        acts_head = tk.Frame(
            acts, bg=_FOLD_BAR, highlightthickness=1, highlightbackground=_FOLD_EDGE,
        )
        acts_head.pack(fill="x")
        chart_title = tk.Label(
            acts_head, text="键鼠", fg=_CARD_FG, bg=_FOLD_BAR,
            font=("Microsoft YaHei UI", 10, "bold"), cursor="hand2",
        )
        chart_title.pack(side="left", padx=(12, 0), pady=7)
        chart_brief = tk.StringVar(value="还没有键鼠")
        tk.Label(
            acts_head, textvariable=chart_brief, fg=_CARD_MUTED, bg=_FOLD_BAR,
            font=("Microsoft YaHei UI", 9), anchor="w",
        ).pack(side="left", padx=(12, 8), pady=7)
        chart_toggle = _fold_chip(acts_head)
        chart_toggle.pack(side="right", padx=(8, 12), pady=5)
        chart_body = tk.Frame(acts, bg=_CARD_BG)
        charts = tk.Frame(chart_body, bg=_CARD_BG, width=pair_w, height=activity_chart.H + 32)
        charts.pack(fill="x")
        charts.pack_propagate(False)
        charts.columnconfigure(0, minsize=activity_chart.W, weight=1)
        charts.columnconfigure(1, minsize=activity_chart.W, weight=1)

        day_var = tk.StringVar(value="今天")

        def shift_chart_day(delta: int) -> None:
            today = date.today()
            lo, hi = self._week_day_bounds(ui, today)
            cur = ui.get("chart_day") or today
            nxt = cur + timedelta(days=delta)
            if nxt < lo or nxt > hi:
                return
            ui["chart_day"] = nxt
            self._paint_activity_chart(ui)

        day_card = tk.Frame(charts, bg=_CARD_BG)
        # 内容比两张图宽时，两张图各贴一边，外沿和下面的卡片对齐，多出来的宽度留在中间。
        day_card.grid(row=0, column=0, sticky="nsw", padx=(0, activity_chart.GAP // 2))
        day_head = tk.Frame(day_card, bg=_CARD_BG)
        day_head.pack(fill="x", pady=(0, 4))

        day_nav: dict[str, tk.Label] = {}

        def _chev(text: str, delta: int, key: str) -> None:
            lbl = tk.Label(
                day_head, text=text, fg=_CARD_FG, bg=_CARD_BG,
                font=("Microsoft YaHei UI", 12, "bold"), cursor="hand2",
            )
            lbl.bind("<Button-1>", lambda _e: shift_chart_day(delta))
            lbl.pack(side="left", padx=(0, 4))
            day_nav[key] = lbl

        _chev("‹", -1, "prev")
        tk.Label(
            day_head, textvariable=day_var, fg=_CARD_FG, bg=_CARD_BG,
            font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(side="left", padx=(2, 6))
        _chev("›", 1, "next")
        view_btns: dict[str, tk.Label] = {}
        for key, label in (("inst", "瞬时"), ("avg", "均速"), ("counts", "次数")):
            btn = tk.Label(
                day_head, text=label, fg=_CARD_MUTED, bg=_CARD_BG,
                font=("Microsoft YaHei UI", 9), cursor="hand2",
            )
            btn.pack(side="right", padx=(8, 0))
            view_btns[key] = btn
        today_lbl = tk.Label(day_card, bg=_CARD_BG, bd=0, highlightthickness=0)
        today_lbl.pack(anchor="w")

        week_card = tk.Frame(charts, bg=_CARD_BG)
        week_card.grid(row=0, column=1, sticky="nse", padx=(activity_chart.GAP // 2, 0))
        week_head = tk.Frame(week_card, bg=_CARD_BG)
        week_head.pack(fill="x", pady=(0, 4))
        tk.Label(
            week_head, text="这周每天", fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 11, "bold"), anchor="w",
        ).pack(side="left")
        chart_btns: dict[str, tk.Label] = {}
        for key, label in (("bar", "柱状"), ("line", "折线")):
            btn = tk.Label(
                week_head, text=label, fg=_CARD_MUTED, bg=_CARD_BG,
                font=("Microsoft YaHei UI", 9), cursor="hand2",
            )
            btn.pack(side="right", padx=(8, 0))
            chart_btns[key] = btn
        week_lbl = tk.Label(week_card, bg=_CARD_BG, bd=0, highlightthickness=0)
        week_lbl.pack(anchor="w")
        placeholder = ImageTk.PhotoImage(activity_chart.blank())
        today_lbl.configure(image=placeholder)
        week_lbl.configure(image=placeholder)

        heat = tk.Frame(sheet, bg=_CARD_BG)
        heat.pack(fill="x", pady=(10, 2))
        heat_head = tk.Frame(
            heat, bg=_FOLD_BAR, highlightthickness=1, highlightbackground=_FOLD_EDGE,
        )
        heat_head.pack(fill="x")
        heat_title = tk.Label(
            heat_head, text="键盘", fg=_CARD_FG, bg=_FOLD_BAR,
            font=("Microsoft YaHei UI", 10, "bold"), cursor="hand2",
        )
        heat_title.pack(side="left", padx=(12, 0), pady=7)
        heat_brief = tk.StringVar(value="还没有按键")
        tk.Label(
            heat_head, textvariable=heat_brief, fg=_CARD_MUTED, bg=_FOLD_BAR,
            font=("Microsoft YaHei UI", 9), anchor="w",
        ).pack(side="left", padx=(12, 8), pady=7)
        heat_toggle = _fold_chip(heat_head)
        heat_toggle.pack(side="right", padx=(8, 12), pady=5)
        heat_body = tk.Frame(heat, bg=_CARD_BG)
        heat_tools = tk.Frame(heat_body, bg=_CARD_BG)
        heat_tools.pack(fill="x", pady=(8, 0))
        heat_view_btns: dict[str, tk.Label] = {}
        for key, label in (("rank", "排行"), ("map", "热力图")):
            btn = tk.Label(
                heat_tools, text=label, fg=_CARD_MUTED, bg=_CARD_BG,
                font=("Microsoft YaHei UI", 9), cursor="hand2",
            )
            btn.pack(side="right", padx=(10, 0))
            heat_view_btns[key] = btn
        heat_lbl = tk.Label(heat_body, bg=_CARD_BG, bd=0, highlightthickness=0)
        heat_lbl.pack(anchor="w")
        heat_var = tk.StringVar(value="数字是这个键按了多少下")
        tk.Label(
            heat_body, textvariable=heat_var, fg=_CARD_MUTED, bg=_CARD_BG,
            font=("Microsoft YaHei UI", 9), anchor="w", justify="left", wraplength=960,
        ).pack(anchor="w", pady=(6, 0))

        keep_var = tk.IntVar(value=activity.keep_days(self.cfg))

        keep_btns: dict[int, tk.Label] = {}

        def _style_keep() -> None:
            cur = activity.keep_days(self.cfg)
            for n, btn in keep_btns.items():
                on = n == cur
                btn.configure(
                    bg=_CARD_ACCENT if on else "#222733",
                    fg="white" if on else _CARD_MUTED,
                    font=("Microsoft YaHei UI", 9, "bold" if on else "normal"),
                )

        def on_keep(days_n: int) -> None:
            keep_var.set(days_n)
            activity.set_keep_days(self.cfg, days_n)
            store.save_config(self.cfg)
            _style_keep()
            today = date.today()
            earliest = today - timedelta(days=activity.keep_days(self.cfg))
            week = worklog.week_dates(ui["anchor"])
            if week[-1] < earliest or week[0] > today:
                ui["anchor"] = today
            focus = ui.get("chart_day") or today
            if focus < earliest or focus > today:
                ui["chart_day"] = today if today >= earliest else earliest
            self._fill_worklog(ui)

        controls = tk.Frame(body, bg=_CARD_BG)
        controls.pack(fill="x", pady=(0, 8), before=scroll_host)

        privacy = tk.Frame(
            controls, bg="#1e2430", highlightthickness=1, highlightbackground="#2c3444",
        )
        privacy.pack(fill="x", pady=(0, 8))
        privacy_inner = tk.Frame(privacy, bg="#1e2430")
        privacy_inner.pack(fill="x", padx=12, pady=9)
        privacy_head = tk.Frame(privacy_inner, bg="#1e2430")
        privacy_head.pack(fill="x")
        tk.Label(
            privacy_head, text="隐私与记录", fg=_CARD_FG, bg="#1e2430",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")
        tk.Label(
            privacy_head, text="数据仅保存在本机", fg=_CARD_MUTED, bg="#1e2430",
            font=("Microsoft YaHei UI", 8),
        ).pack(side="left", padx=(10, 0))
        checks = tk.Frame(privacy_inner, bg="#1e2430")
        checks.pack(fill="x", pady=(5, 0))
        tk.Checkbutton(
            checks, text="记录来 / 走时间", variable=track_on, command=toggle_track,
            fg=_CARD_FG, bg="#1e2430", selectcolor="#222733", activebackground="#1e2430",
            activeforeground=_CARD_FG, highlightthickness=0, font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        tk.Checkbutton(
            checks, text="记录按键分布、鼠标次数和位移", variable=act_on, command=toggle_act,
            fg=_CARD_FG, bg="#1e2430", selectcolor="#222733", activebackground="#1e2430",
            activeforeground=_CARD_FG, highlightthickness=0, font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(18, 0))
        picks = tk.Frame(checks, bg="#1e2430")
        picks.pack(side="right")
        tk.Label(
            picks, text="保留", fg=_CARD_MUTED, bg="#1e2430", font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(0, 8))
        for days_n in activity.KEEP_PRESETS:
            btn = tk.Label(
                picks, text=f"{days_n} 天", fg=_CARD_MUTED, bg="#222733",
                font=("Microsoft YaHei UI", 9), cursor="hand2", padx=10, pady=2,
            )
            btn.pack(side="left", padx=(0, 4))
            btn.bind("<Button-1>", lambda _e, n=days_n: on_keep(n))
            keep_btns[days_n] = btn
        _style_keep()

        top_panel = tk.Frame(
            controls, bg="#1e2430", highlightthickness=1, highlightbackground="#2c3444",
        )
        top_panel.pack(fill="x")
        top_inner = tk.Frame(top_panel, bg="#1e2430")
        top_inner.pack(fill="x", padx=12, pady=6)
        tk.Label(
            top_inner, text="计时器顶栏", fg=_CARD_FG, bg="#1e2430",
            font=("Microsoft YaHei UI", 10, "bold"),
        ).pack(side="left")
        tk.Checkbutton(
            top_inner, text="显示", variable=card_on, command=toggle_card,
            fg=_CARD_FG, bg="#1e2430", selectcolor="#222733", activebackground="#1e2430",
            activeforeground=_CARD_FG, highlightthickness=0, font=("Microsoft YaHei UI", 9),
        ).pack(side="right")
        slot_row = tk.Frame(top_inner, bg="#1e2430")
        slot_row.pack(side="left", fill="x", expand=True, padx=(12, 8))
        slot_vars: list[tk.StringVar] = []
        slot_buttons: list[tk.Menubutton] = []
        slot_labels = [label for _key, label in activity.CARD_CHOICES]

        def pick_slot(index: int, value: str) -> None:
            updated = activity.set_card_slot(self.cfg, index, activity.card_id(value))
            for j, slot in enumerate(updated):
                slot_vars[j].set(activity.card_label(slot) + "    ▼")
            store.save_config(self.cfg)
            self._tally_at = 0.0
            self._tally_speed_at = 0.0
            self._tally_speed = None
            self._last_key = ""

        chosen = activity.card_slots(self.cfg)
        for index in range(3):
            var = tk.StringVar(value=activity.card_label(chosen[index]) + "    ▼")
            slot_vars.append(var)
            picker = tk.Menubutton(
                slot_row, textvariable=var, anchor="w", cursor="hand2", indicatoron=False,
                bg="#222733", fg=_CARD_FG, activebackground="#2a3344", activeforeground=_CARD_FG,
                highlightthickness=1, highlightbackground="#3a465c", highlightcolor=_CARD_ACCENT,
                relief="flat", bd=0, font=("Microsoft YaHei UI", 9, "bold"), padx=10, pady=3,
            )
            menu = tk.Menu(
                picker, tearoff=False, bg="#222733", fg=_CARD_FG,
                activebackground=_CARD_ACCENT, activeforeground="white",
                font=("Microsoft YaHei UI", 9),
            )
            for label in slot_labels:
                menu.add_command(label=label, command=lambda v=label, i=index: pick_slot(i, v))
            picker.configure(menu=menu)
            picker.pack(side="left", fill="x", expand=True, padx=(0, 8 if index < 2 else 0))
            slot_buttons.append(picker)

        history_notice = tk.Frame(
            sheet, bg="#1e2430", highlightthickness=1, highlightbackground="#2c3444",
        )
        tk.Label(
            history_notice,
            text="来 / 走记录已关闭\n历史数据仍保存在本机，重新开启后会恢复显示。",
            fg=_CARD_MUTED, bg="#1e2430", justify="center",
            font=("Microsoft YaHei UI", 10), pady=22,
        ).pack(fill="x")

        table = tk.Frame(sheet, bg=_CARD_BG)
        table.pack(fill="x", pady=(10, 0))

        def reset_today() -> None:
            if not self._worklog_apply(ui):
                return
            today = date.today()
            worklog.set_note(self.cfg, today, "", "")
            sync_declared = getattr(self, "_sync_declared", None)
            if callable(sync_declared):
                sync_declared(today, force=True)
            store.save_config(self.cfg)
            self._fill_worklog(ui)
            err.set("已恢复今天的倒计时时间")

        # 还在记的时长会带到秒，日期也会写成「今天 12/31  周五」。
        # 列宽按最长的那句留，不然说明框会盖住时长，窗口又会把说明框切掉。
        dur_probe = tk.Label(table, text="23小时59分59秒 · 还在记", font=("Microsoft YaHei UI", 9))
        note_probe = tk.Label(table, text="12小时59分", font=("Microsoft YaHei UI", 9))
        reset_probe = tk.Label(table, text="恢复默认", font=("Microsoft YaHei UI", 8))
        today_probe = tk.Label(table, text="今天", width=4, font=("Microsoft YaHei UI", 8))
        date_probe = tk.Label(table, text="12/31  周五", font=("Microsoft YaHei UI", 10, "bold"))
        dur_probe.update_idletasks()
        dur_col = max(
            dur_probe.winfo_reqwidth(),
            note_probe.winfo_reqwidth() + 16 + reset_probe.winfo_reqwidth(),
        ) + 8
        date_col = max(168, today_probe.winfo_reqwidth() + 6 + date_probe.winfo_reqwidth() + 20)
        for probe in (dur_probe, note_probe, reset_probe, today_probe, date_probe):
            probe.destroy()
        slots = []
        for i in range(7):
            row_bg = "#202634"
            card = tk.Frame(
                table, bg=row_bg, highlightthickness=1, highlightbackground="#2c3444",
            )
            card.pack(fill="x", pady=(0, 6))
            # 七天共用同一套列宽，两行的名称、时间和时长才能对上。
            for col, size in ((0, date_col), (1, 122), (2, 40), (3, 78), (5, 78), (6, 24)):
                card.columnconfigure(col, minsize=size)
            card.columnconfigure(4, minsize=22)
            card.columnconfigure(7, minsize=dur_col, weight=1)
            card.columnconfigure(8, minsize=_SUMMARY_W)
            card.rowconfigure(0, minsize=42, uniform="dayrow")
            card.rowconfigure(1, minsize=42, uniform="dayrow")
            date_box = tk.Frame(card, bg=row_bg)
            today_tag = tk.Label(
                date_box, text="", width=4, fg="#9ecbff", bg=row_bg,
                font=("Microsoft YaHei UI", 8), anchor="center",
                highlightthickness=0,
            )
            date_lbl = tk.Label(
                date_box, text="", fg=_CARD_FG, bg=row_bg,
                font=("Microsoft YaHei UI", 10), anchor="w",
            )
            today_tag.pack(side="left", padx=(0, 6))
            date_lbl.pack(side="left")
            came_tag = tk.Label(
                card, text="软件记录使用时间段", fg=_CARD_MUTED, bg=row_bg,
                font=("Microsoft YaHei UI", 9), anchor="w",
            )
            note_tag = tk.Label(
                card, text="公司正常上下班时间", fg=_CARD_MUTED, bg=row_bg,
                font=("Microsoft YaHei UI", 9), anchor="w",
            )
            came = tk.Label(
                card, text="", width=6, fg=_CARD_FG, bg=row_bg,
                font=("Consolas", 11), anchor="center",
            )
            left = tk.Label(
                card, text="", width=6, fg=_CARD_FG, bg=row_bg,
                font=("Consolas", 11), anchor="center",
            )
            record_arrow = tk.Label(
                card, text="→", fg=_CARD_MUTED, bg=row_bg, font=("Microsoft YaHei UI", 9),
            )
            soft_tail = tk.Frame(card, bg=row_bg)
            dur = tk.Label(
                soft_tail, text="", fg=_CARD_FG, bg=row_bg,
                font=("Microsoft YaHei UI", 9), anchor="w",
            )
            dur.pack(side="left")
            summary_box = tk.Frame(
                card, width=_SUMMARY_W, height=_SUMMARY_H, bg="#161d2b",
                highlightthickness=1, highlightbackground="#3d4b63",
            )
            summary_box.pack_propagate(False)
            summary = tk.Label(
                summary_box, text="", fg=_CARD_MUTED, bg="#161d2b",
                font=("Microsoft YaHei UI", 9), anchor="nw", justify="left",
                wraplength=_SUMMARY_WRAP,
            )
            summary_pace = tk.Label(
                summary_box, text="", fg="#d5deea", bg="#161d2b",
                font=("Microsoft YaHei UI", 9), anchor="nw", justify="left",
                wraplength=_SUMMARY_WRAP,
            )
            summary.pack(anchor="nw", fill="x", padx=12, pady=(8, 0))
            summary_pace.pack(anchor="nw", fill="x", padx=12, pady=(4, 0))
            vin = tk.StringVar()
            vout = tk.StringVar()
            ein = tk.Entry(
                card, textvariable=vin, width=6, font=("Consolas", 11), justify="center",
                bg="#3d4a62", fg=_CARD_FG, insertbackground=_CARD_FG, relief="flat",
                highlightthickness=1, highlightbackground="#9eb0cc", highlightcolor="#7eb6ff",
                disabledbackground="#202634", disabledforeground=_CARD_MUTED,
            )
            eout = tk.Entry(
                card, textvariable=vout, width=6, font=("Consolas", 11), justify="center",
                bg="#3d4a62", fg=_CARD_FG, insertbackground=_CARD_FG, relief="flat",
                highlightthickness=1, highlightbackground="#9eb0cc", highlightcolor="#7eb6ff",
                disabledbackground="#202634", disabledforeground=_CARD_MUTED,
            )
            arrow = tk.Label(
                card, text="→", fg=_CARD_MUTED, bg=row_bg, font=("Microsoft YaHei UI", 9),
            )
            note_tail = tk.Frame(card, bg=row_bg)
            note_dur = tk.Label(
                note_tail, text="", fg=_CARD_FG, bg=row_bg,
                font=("Microsoft YaHei UI", 9), anchor="w",
            )
            reset = tk.Label(
                note_tail, text="", fg=_CARD_ACCENT, bg=row_bg,
                font=("Microsoft YaHei UI", 8), anchor="w", cursor="arrow",
            )
            note_dur.pack(side="left")
            reset.pack(side="left", padx=(16, 0))
            date_box.grid(row=0, column=0, rowspan=2, sticky="w", padx=(12, 8), pady=8)
            came_tag.grid(row=0, column=1, sticky="w", pady=(8, 2))
            note_tag.grid(row=1, column=1, sticky="w", pady=(2, 8))
            came.grid(row=0, column=3, sticky="", pady=(8, 2))
            ein.grid(row=1, column=3, sticky="", ipady=2, ipadx=2, pady=(2, 8))
            record_arrow.grid(row=0, column=4, pady=(8, 2))
            arrow.grid(row=1, column=4, pady=(2, 8))
            left.grid(row=0, column=5, sticky="", pady=(8, 2))
            eout.grid(row=1, column=5, sticky="", ipady=2, ipadx=2, pady=(2, 8))
            soft_tail.grid(row=0, column=7, columnspan=1, sticky="w", pady=(8, 2), padx=(0, 8))
            note_tail.grid(row=1, column=7, columnspan=1, sticky="w", pady=(2, 8), padx=(0, 8))
            summary_box.grid(row=0, column=8, rowspan=2, sticky="nsew", padx=(8, 12), pady=8)
            reset.bind("<Button-1>", lambda _e: reset_today())
            doubt_row = tk.Frame(card, bg=row_bg)
            doubt = tk.Label(
                doubt_row, text="", fg=_CARD_MUTED, bg=row_bg,
                font=("Microsoft YaHei UI", 9), anchor="w",
            )
            doubt_drop = tk.Label(
                doubt_row, text="不算", fg=_CARD_ACCENT, bg=row_bg,
                font=("Microsoft YaHei UI", 8), cursor="hand2",
            )
            doubt_keep = tk.Label(
                doubt_row, text="算上", fg=_CARD_ACCENT, bg=row_bg,
                font=("Microsoft YaHei UI", 8), cursor="hand2",
            )
            doubt.pack(side="left")
            doubt_drop.pack(side="left", padx=(12, 0))
            doubt_keep.pack(side="left", padx=(8, 0))
            slot = {
                "card": card, "date": date_lbl, "today_tag": today_tag, "came": came, "left": left,
                "vin": vin, "vout": vout, "ein": ein, "eout": eout,
                "dur": dur, "note_dur": note_dur, "summary": summary,
                "summary_pace": summary_pace, "summary_box": summary_box,
                "reset": reset,
                "day": None, "doubt_row": doubt_row, "doubt": doubt,
                "doubt_drop": doubt_drop, "doubt_keep": doubt_keep,
                "row_widgets": (
                    card, date_box, today_tag, date_lbl, came_tag, note_tag, came, left, record_arrow,
                    soft_tail, dur, arrow, note_tail, note_dur, reset,
                    doubt_row, doubt, doubt_drop, doubt_keep,
                ),
            }

            def on_doubt(keep: bool, this: dict = slot) -> None:
                day = this.get("day")
                if day is None or not this["doubt"].cget("text"):
                    return
                if not worklog.decide_doubt(self.cfg, day, keep=keep):
                    return
                store.save_config(self.cfg)
                self._worklog_dirty = False
                self._worklog_save_at = time.monotonic()
                self._fill_worklog(ui)

            doubt_drop.bind("<Button-1>", lambda _e, this=slot, fn=on_doubt: fn(False, this))
            doubt_keep.bind("<Button-1>", lambda _e, this=slot, fn=on_doubt: fn(True, this))
            slot["card"].bind("<Configure>", lambda _e, this=slot: self._fit_day_copy(this), add="+")
            slots.append(slot)

        ui = {
            "dlg": dlg,
            "stop": False,
            "live": False,
            "anchor": date.today(),
            "slots": slots,
            "edits": [],
            "err": err,
            "week_var": week_var,
            "week_sum": week_sum,
            "habit_sum": habit_sum,
            "habit_lbl": habit_lbl,
            "month_lbl": month_lbl,
            "month_sum": month_sum,
            "week_sum_lbl": week_sum_lbl,
            "sums": sums,
            "sheet": sheet,
            "scroll": scroll,
            "scroll_host": scroll_host,
            "scroll_sb": scroll_sb,
            "bar": bar,
            "err_row": err_row,
            "nav": nav,
            "minimized": False,
            "min_toggle": min_toggle,
            "pair_w": pair_w,
            "track_on": track_on,
            "act_on": act_on,
            "card_on": card_on,
            "table": table,
            "history_notice": history_notice,
            "controls": controls,
            "privacy_panel": privacy,
            "top_panel": top_panel,
            "slot_buttons": slot_buttons,
            "today_lbl": today_lbl,
            "week_lbl": week_lbl,
            "charts": charts,
            "chart_body": chart_body,
            "chart_toggle": chart_toggle,
            "chart_brief": chart_brief,
            "heat_lbl": heat_lbl,
            "heat_var": heat_var,
            "heat_brief": heat_brief,
            "heat_body": heat_body,
            "heat_toggle": heat_toggle,
            "heat_tools": heat_tools,
            "heat_view_btns": heat_view_btns,
            "chart_placeholder": placeholder,
            "day_var": day_var,
            "chart_day": date.today(),
            "day_prev": day_nav.get("prev"),
            "day_next": day_nav.get("next"),
            "keep_var": keep_var,
            "chart_sig": None,
            "chart_btns": chart_btns,
            "view_btns": view_btns,
            "save_btn": None,
            "export_btn": None,
        }
        for key, btn in chart_btns.items():
            btn.bind("<Button-1>", lambda _e, s=key: self._set_chart_style(ui, s))
        for key, btn in view_btns.items():
            btn.bind("<Button-1>", lambda _e, s=key: self._set_chart_view(ui, s))
        for key, btn in heat_view_btns.items():
            btn.bind("<Button-1>", lambda _e, s=key: self._set_heat_view(ui, s))
        heat_toggle.bind("<Button-1>", lambda _e: self._toggle_heat(ui))
        heat_title.bind("<Button-1>", lambda _e: self._toggle_heat(ui))
        chart_toggle.bind("<Button-1>", lambda _e: self._toggle_chart(ui))
        chart_title.bind("<Button-1>", lambda _e: self._toggle_chart(ui))
        min_toggle.bind("<Button-1>", lambda _e: self._minimize_worklog(ui))
        self._style_chart_buttons(ui)
        self._apply_chart_open(ui)
        self._apply_heat_open(ui)

        def on_charts_width(e) -> None:
            width = int(getattr(e, "width", 0) or 0)
            if width <= 1 or ui.get("heat_width") == width:
                return
            ui["heat_width"] = width
            ui["heat_sig"] = None
            if ui.get("heat_job") is not None:
                return

            def paint() -> None:
                ui["heat_job"] = None
                try:
                    if not charts.winfo_exists():
                        return
                except tk.TclError:
                    return
                focus = ui.get("chart_day") or date.today()
                keyboard_heat.paint_into(
                    ui, self.cfg, focus, date.today(), enabled=activity.enabled(self.cfg),
                )

            ui["heat_job"] = charts.after_idle(paint)

        charts.bind("<Configure>", on_charts_width, add="+")

        def bind_chart(lbl: tk.Label, panel: str) -> None:
            def move(e) -> None:
                ww = max(1, lbl.winfo_width())
                wh = max(1, lbl.winfo_height())
                x = int(e.x * activity_chart.W / ww)
                y = int(e.y * activity_chart.H / wh)
                ui[f"{panel}_ptr"] = (x, y)
                activity_chart.apply_hover(ui, panel, x, y)

            def leave(_e) -> None:
                # 数字一变就换图，Tk 会多送一次 Leave。鼠标还在格子上就保持底部那行。
                try:
                    px, py = lbl.winfo_pointerxy()
                    x, y = lbl.winfo_rootx(), lbl.winfo_rooty()
                    inside = x <= px < x + lbl.winfo_width() and y <= py < y + lbl.winfo_height()
                except tk.TclError:
                    inside = False
                if inside:
                    return
                ui[f"{panel}_ptr"] = None
                activity_chart.apply_hover(ui, panel, -1, -1)

            lbl.bind("<Motion>", move)
            lbl.bind("<Leave>", leave)

        bind_chart(today_lbl, "today")
        bind_chart(week_lbl, "week")

        def heat_move(e) -> None:
            ww = max(1, heat_lbl.winfo_width())
            wh = max(1, heat_lbl.winfo_height())
            width, height = ui.get("heat_size") or keyboard_heat.image_size()
            keyboard_heat.hover(ui, int(e.x * width / ww), int(e.y * height / wh))

        def heat_leave(_e) -> None:
            try:
                px, py = heat_lbl.winfo_pointerxy()
                x, y = heat_lbl.winfo_rootx(), heat_lbl.winfo_rooty()
                inside = x <= px < x + heat_lbl.winfo_width() and y <= py < y + heat_lbl.winfo_height()
            except tk.TclError:
                inside = False
            if inside:
                return
            ui["heat_hover"] = False
            keyboard_heat.hover(ui, -1, -1)

        heat_lbl.bind("<Motion>", heat_move)
        heat_lbl.bind("<Leave>", heat_leave)

        def on_week_click(e) -> None:
            ww = max(1, week_lbl.winfo_width())
            wh = max(1, week_lbl.winfo_height())
            hit = activity_chart.hit_at(
                ui.get("week_hits") or [],
                int(e.x * activity_chart.W / ww),
                int(e.y * activity_chart.H / wh),
            )
            raw = str((hit or {}).get("date") or "")
            if not raw:
                return
            try:
                picked = date.fromisoformat(raw)
            except ValueError:
                return
            today = date.today()
            lo, hi = self._week_day_bounds(ui, today)
            if picked < lo or picked > hi:
                return
            ui["chart_day"] = picked
            self._paint_activity_chart(ui)

        week_lbl.bind("<Button-1>", on_week_click)

        def close() -> None:
            ui["minimized"] = False
            self._hide_worklog_dock()
            ui["stop"] = True
            _park_card(dlg, ui.get("fg", 0))

        def save() -> None:
            if not worklog.tracking_enabled(self.cfg):
                err.set("先开启「记录来 / 走时间」才能修改自己填的时间。")
                return
            if self._worklog_apply(ui):
                self._fill_worklog(ui)
                err.set("已保存")

        def shift(days: int) -> None:
            if not self._worklog_apply(ui):
                return
            today = date.today()
            earliest = today - timedelta(days=activity.keep_days(self.cfg))
            nxt = today if not days else ui["anchor"] + timedelta(days=days)
            week = worklog.week_dates(nxt)
            if week[-1] < earliest or week[0] > today:
                return
            if not days:
                ui["chart_day"] = today
            else:
                focus = ui.get("chart_day") or today
                if focus < week[0] or focus > week[-1]:
                    pick = min(today, week[-1])
                    ui["chart_day"] = earliest if pick < earliest else pick
            ui["anchor"] = nxt
            err.set("")
            self._fill_worklog(ui)

        def export() -> None:
            if not worklog.tracking_enabled(self.cfg):
                err.set("工时历史当前已隐藏，重新开启后才能导出。")
                return
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

        def _week_chev(text: str, days: int, key: str) -> None:
            lbl = tk.Label(
                nav, text=text, fg=_CARD_FG, bg=_CARD_BG,
                font=("Microsoft YaHei UI", 14, "bold"), cursor="hand2",
            )
            lbl.bind("<Button-1>", lambda _e: shift(days))
            lbl.pack(side="left", padx=(8 if key == "week_next" else 0, 0))
            ui[key] = lbl

        _week_chev("‹", -7, "week_prev")
        tk.Label(
            nav, textvariable=week_var, fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 11, "bold"),
        ).pack(side="left", padx=8)
        _week_chev("›", 7, "week_next")
        home = tk.Label(
            nav, text="本周", fg=_CARD_ACCENT, bg=_CARD_BG, font=("Microsoft YaHei UI", 9), cursor="hand2",
        )
        home.bind("<Button-1>", lambda _e: shift(0))
        home.pack(side="left", padx=(12, 0))
        ui["week_home"] = home
        save_btn = _card_btn(bar, "保存修改", save, accent=True)
        save_btn.pack(side="left", padx=(18, 6))
        export_btn = _card_btn(bar, "导出本月 CSV…", export)
        export_btn.pack(side="left", padx=6)
        ui["save_btn"] = save_btn
        ui["export_btn"] = export_btn
        _card_btn(bar, "关闭", close).pack(side="left", padx=6)
        dlg.bind("<Return>", lambda _e: save())
        dlg.bind("<Escape>", lambda _e: close())

        def _flush_wheel() -> None:
            ui["wheel_job"] = None
            step = int(ui.pop("wheel_acc", 0) or 0)
            if not step:
                return
            if int(sheet.winfo_reqheight()) <= int(scroll.winfo_height()) + 1:
                return
            scroll.yview_scroll(step, "units")

        def _wheel(event) -> None:
            # 一串滚轮先累加，空闲时一次挪完，键鼠图只贴一次。
            ui["scroll_until"] = time.monotonic() + 0.25
            ui["wheel_acc"] = int(ui.get("wheel_acc") or 0) + wheel_pixels(int(event.delta))
            if ui.get("wheel_job") is None:
                ui["wheel_job"] = scroll.after_idle(_flush_wheel)

        def _bind_wheel(widget) -> None:
            widget.bind("<MouseWheel>", _wheel, add="+")
            for child in widget.winfo_children():
                _bind_wheel(child)

        def _sync_scroll(_event=None) -> None:
            height = max(1, int(sheet.winfo_reqheight()))
            # winfo_height 在窗口重排前还是上一档高度，会把刚收起的滚动条又装回来。
            view = scroll._view_h()
            width = int(scroll.winfo_width())
            if view <= 1:
                return
            # 滚动时嵌进去的卡片会反复发 Configure。尺寸没变就别重设滚动区域，否则画面会撕开、位置乱跳。
            if (
                ui.get("scroll_h") == height
                and ui.get("scroll_view") == view
                and ui.get("scroll_w") == width
            ):
                return
            ui["scroll_h"] = height
            ui["scroll_view"] = view
            ui["scroll_w"] = width
            scroll.refresh()
            shown = bool(scroll_sb.winfo_manager())
            if height > view + 4 and not shown:
                scroll_sb.pack(fill="both", expand=True)
            elif height <= view + 1 and shown:
                scroll_sb.pack_forget()

        sheet.bind("<Configure>", _sync_scroll, add="+")
        scroll.bind("<Configure>", _sync_scroll, add="+")
        _bind_wheel(scroll_host)
        self._sync_worklog_privacy(ui)
        self._fit_worklog_width(ui)
        return ui

    def _fit_worklog_width(self, ui: dict) -> None:
        """行比两张图宽时，把视口撑到行的宽度。挤在固定宽度里，时长会被说明框盖住。"""
        table = ui.get("table")
        scroll = ui.get("scroll")
        if table is None or scroll is None:
            return
        table.update_idletasks()
        need = max(int(ui["pair_w"]), int(table.winfo_reqwidth()))
        if int(scroll.cget("width")) != need:
            scroll.configure(width=need)
        ui["content_w"] = need

    def _fit_worklog_scroll(self, ui: dict, *, screen_h: int | None = None) -> None:
        canvas = ui.get("scroll")
        sheet = ui.get("sheet")
        sb = ui.get("scroll_sb")
        dlg = ui.get("dlg")
        if canvas is None or sheet is None or dlg is None or ui.get("minimized"):
            return
        sheet.update_idletasks()
        sheet_h = max(1, int(sheet.winfo_reqheight()))
        canvas.configure(height=sheet_h)
        canvas.yview_moveto(0)
        if sb is not None and sb.winfo_manager():
            sb.pack_forget()
        dlg.update_idletasks()
        natural = max(1, int(dlg.winfo_reqheight()))
        raw = int(screen_h if screen_h is not None else dlg.winfo_screenheight())
        view, scroll = scroll_view(sheet_h, natural, raw)
        canvas.configure(height=view)
        canvas.yview_moveto(0)
        dlg.update_idletasks()
        if sb is None:
            return
        if scroll and not sb.winfo_manager():
            sb.pack(fill="both", expand=True)
        elif not scroll and sb.winfo_manager():
            sb.pack_forget()

    def _open_worklog_dialog(self) -> None:
        self._worklog_tick(force=True)
        ui = self._ensure_worklog_ui()
        ui["err"].set("")
        ui["anchor"] = date.today()
        ui["chart_day"] = date.today()
        if ui.get("live"):
            if ui.get("minimized"):
                self._restore_worklog(ui)
            else:
                try:
                    ui["dlg"].lift()
                    ui["dlg"].focus_force()
                except tk.TclError:
                    pass
            return
        ui["live"] = True
        ui["stop"] = False
        ui["minimized"] = False
        self._hide_worklog_dock()
        ui["fg"] = layered_win.user32.GetForegroundWindow()
        self._fill_worklog(ui)
        self._fit_worklog_scroll(ui)
        _reveal_card(
            ui["dlg"],
            min_w=int(ui.get("content_w") or (activity_chart.W * 2 + activity_chart.GAP)) + 48,
            min_h=420,
            near=self._dialog_near(),
        )
        # 建窗口时 Tk 不占 Python，图已经在后台画了一大半；剩下的等一下，别先露出空板。
        activity_chart.wait(ui, 0.4)
        try:
            _run_card_modal(ui["dlg"], self.win, on_frame=self._card_frame, stop=lambda: ui["stop"])
        finally:
            ui["live"] = False
