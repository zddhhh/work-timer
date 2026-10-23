"""工时账本窗口：一周的来了、走了，键鼠次数图，保留天数。"""
from __future__ import annotations

import time
import tkinter as tk
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import filedialog

import activity
import activity_chart
import layered_win
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


class WorklogDialogMixin:
    """WorkTimer 的一部分，方法里的 self 就是 WorkTimer。"""

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
        return worklog.fmt_elapsed(end - start) + " · 还在记"

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
            diff_text = worklog.fmt_diff(r["diff"])
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
            if d == today:
                label += "  今天"
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
            out_s = "" if too_old else worklog.fmt_clock(r["out"])
            slot["auto_out"] = out_s
            slot["vin"].set("" if too_old else worklog.fmt_clock(r["in"]))
            slot["vout"].set(out_s)
            state = "disabled" if d > today or too_old else "normal"
            slot["ein"].configure(state=state)
            slot["eout"].configure(state=state)
            slot["dur"].configure(text="" if too_old else self._worklog_dur_text(r, datetime.now()))
            slot["diff"].configure(
                text="" if too_old else worklog.fmt_diff(r["diff"]),
                fg=self._worklog_diff_fg(None if too_old else r["diff"]),
            )
            if d == today:
                row_bg = "#243044"
            elif i % 2:
                row_bg = "#1b212d"
            else:
                row_bg = "#202634"
            for w in (slot["date"], slot["dur"], slot["diff"]):
                w.configure(bg=row_bg)
            slot["ein"].configure(disabledbackground=row_bg)
            slot["eout"].configure(disabledbackground=row_bg)
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
        self._paint_activity_chart(ui)

    def _paint_activity_chart(self, ui: dict | None = None) -> None:
        ui = ui if ui is not None else self._worklog_ui
        if ui is None or ui.get("today_lbl") is None:
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
        activity_chart.paint_into(
            ui,
            self.cfg,
            today=today,
            days=days,
            enabled=activity.enabled(self.cfg),
            this_week=days[0] <= today <= days[-1],
            focus=focus,
            style=activity.chart_style(self.cfg),
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

    def _set_chart_style(self, ui: dict, style: str) -> None:
        if activity.chart_style(self.cfg) == style:
            return
        activity.set_chart_style(self.cfg, style)
        store.save_config(self.cfg)
        self._style_chart_buttons(ui)
        ui["chart_sig"] = None
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
        tk.Label(
            sums, textvariable=week_sum, fg=_CARD_FG, bg=_CARD_BG, font=("Microsoft YaHei UI", 10),
            wraplength=pair_w, justify="left",
        ).pack(anchor="w", pady=(8, 0))
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
        week_var = tk.StringVar()
        nav = tk.Frame(top, bg=_CARD_BG)
        nav.pack(side="right")
        scroll_host = tk.Frame(body, bg=_CARD_BG)
        scroll_host.pack(anchor="nw", fill="y", expand=True)
        scroll = tk.Canvas(
            scroll_host, bg=_CARD_BG, highlightthickness=0, bd=0, relief="flat",
            width=pair_w, height=200,
        )
        scroll_sb = tk.Scrollbar(
            scroll_host, orient="vertical", command=scroll.yview, width=8,
            bg="#3a4254", activebackground="#5a6478", troughcolor=_CARD_BG,
            relief="flat", bd=0, highlightthickness=0,
        )
        scroll.configure(yscrollcommand=scroll_sb.set)
        scroll.pack(side="left", fill="y", expand=True)
        sheet = tk.Frame(scroll, bg=_CARD_BG)
        scroll_win = scroll.create_window((0, 0), window=sheet, anchor="nw", width=pair_w)
        act_on = tk.BooleanVar(value=activity.enabled(self.cfg))

        card_on = tk.BooleanVar(value=activity.show_on_card(self.cfg))

        def toggle_act() -> None:
            on = bool(act_on.get())
            activity.set_enabled(self.cfg, on)
            if not on:
                card_on.set(False)
            self.win.listen_raw_input(activity.enabled(self.cfg))
            self._tally_at = 0.0
            store.save_config(self.cfg)
            self._paint_activity_chart(ui)

        def toggle_card() -> None:
            activity.set_show_on_card(self.cfg, bool(card_on.get()))
            act_on.set(activity.enabled(self.cfg))
            self.win.listen_raw_input(activity.enabled(self.cfg))
            self._tally_at = 0.0
            store.save_config(self.cfg)
            self._paint_activity_chart(ui)

        charts = tk.Frame(sheet, bg=_CARD_BG, width=pair_w, height=activity_chart.H + 32)
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
        day_card.grid(row=0, column=0, sticky="nsew", padx=(0, activity_chart.GAP // 2))
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
        today_lbl = tk.Label(day_card, bg=_CARD_BG, bd=0, highlightthickness=0)
        today_lbl.pack(anchor="w")

        week_card = tk.Frame(charts, bg=_CARD_BG)
        week_card.grid(row=0, column=1, sticky="nsew", padx=(activity_chart.GAP // 2, 0))
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

        tool = tk.Frame(sheet, bg=_CARD_BG)
        tool.pack(fill="x", pady=(8, 0))
        tk.Checkbutton(
            tool, text="记录键盘、鼠标次数和位移", variable=act_on, command=toggle_act,
            fg=_CARD_FG, bg=_CARD_BG, selectcolor="#222733", activebackground=_CARD_BG,
            activeforeground=_CARD_FG, highlightthickness=0, font=("Microsoft YaHei UI", 9),
        ).pack(side="left")
        tk.Checkbutton(
            tool, text="在计时器顶部显示", variable=card_on, command=toggle_card,
            fg=_CARD_FG, bg=_CARD_BG, selectcolor="#222733", activebackground=_CARD_BG,
            activeforeground=_CARD_FG, highlightthickness=0, font=("Microsoft YaHei UI", 9),
        ).pack(side="left", padx=(12, 0))
        picks = tk.Frame(tool, bg=_CARD_BG)
        picks.pack(side="right")
        tk.Label(
            picks, text="留多久", fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9),
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

        head_bg = "#191e28"
        entry_bg = "#2a3344"
        table = tk.Frame(sheet, bg=head_bg, highlightthickness=1, highlightbackground="#2c3444")
        table.pack(fill="x", pady=(10, 0))
        for c, (text, wide) in enumerate((("日期", 148), ("来了", 78), ("走了", 78), ("待了多久", 120), ("比该走", 100))):
            table.columnconfigure(c, minsize=wide, weight=2 if c == 0 else 1)
            tk.Label(
                table, text=text, fg=_CARD_MUTED, bg=head_bg, font=("Microsoft YaHei UI", 9),
            ).grid(row=0, column=c, sticky="w", padx=(14 if c == 0 else 8, 6), pady=(8, 6))
        slots = []
        for i in range(1, 8):
            date_lbl = tk.Label(table, text="", fg=_CARD_FG, bg="#202634", font=("Microsoft YaHei UI", 10), anchor="w")
            date_lbl.grid(row=i, column=0, sticky="ew", padx=(14, 6), pady=3)
            vin = tk.StringVar()
            vout = tk.StringVar()
            ein = tk.Entry(
                table, textvariable=vin, width=6, font=("Consolas", 11), justify="center",
                bg=entry_bg, fg=_CARD_FG, insertbackground=_CARD_FG, relief="flat",
                highlightthickness=0, disabledbackground="#202634", disabledforeground=_CARD_MUTED,
            )
            eout = tk.Entry(
                table, textvariable=vout, width=6, font=("Consolas", 11), justify="center",
                bg=entry_bg, fg=_CARD_FG, insertbackground=_CARD_FG, relief="flat",
                highlightthickness=0, disabledbackground="#202634", disabledforeground=_CARD_MUTED,
            )
            ein.grid(row=i, column=1, sticky="w", padx=8, pady=3, ipady=2)
            eout.grid(row=i, column=2, sticky="w", padx=8, pady=3, ipady=2)
            dur = tk.Label(table, text="", fg=_CARD_FG, bg="#202634", font=("Microsoft YaHei UI", 10), anchor="w")
            diff = tk.Label(table, text="", fg=_CARD_MUTED, bg="#202634", font=("Microsoft YaHei UI", 10), anchor="w")
            dur.grid(row=i, column=3, sticky="ew", padx=8)
            diff.grid(row=i, column=4, sticky="ew", padx=(8, 14))
            slots.append({"date": date_lbl, "vin": vin, "vout": vout, "ein": ein, "eout": eout, "dur": dur, "diff": diff})
        tk.Frame(table, bg=head_bg, height=8).grid(row=8, column=0, columnspan=5, sticky="ew")

        ui = {
            "dlg": dlg,
            "stop": False,
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
            "sums": sums,
            "sheet": sheet,
            "scroll": scroll,
            "scroll_sb": scroll_sb,
            "scroll_win": scroll_win,
            "pair_w": pair_w,
            "act_on": act_on,
            "card_on": card_on,
            "today_lbl": today_lbl,
            "week_lbl": week_lbl,
            "day_var": day_var,
            "chart_day": date.today(),
            "day_prev": day_nav.get("prev"),
            "day_next": day_nav.get("next"),
            "keep_var": keep_var,
            "chart_sig": None,
            "chart_btns": chart_btns,
        }
        for key, btn in chart_btns.items():
            btn.bind("<Button-1>", lambda _e, s=key: self._set_chart_style(ui, s))
        self._style_chart_buttons(ui)

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
            ui["stop"] = True
            _park_card(dlg, ui.get("fg", 0))

        def save() -> None:
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
        _card_btn(bar, "保存修改", save, accent=True).pack(side="left", padx=(18, 6))
        _card_btn(bar, "导出本月 CSV…", export).pack(side="left", padx=6)
        _card_btn(bar, "关闭", close).pack(side="left", padx=6)
        dlg.bind("<Return>", lambda _e: save())
        dlg.bind("<Escape>", lambda _e: close())

        def _wheel(event) -> None:
            if int(sheet.winfo_reqheight()) <= int(scroll.winfo_height()) + 1:
                return
            scroll.yview_scroll(-1 if event.delta > 0 else 1, "units")

        def _bind_wheel(widget) -> None:
            widget.bind("<MouseWheel>", _wheel, add="+")
            for child in widget.winfo_children():
                _bind_wheel(child)

        def _sync_scroll(_event=None) -> None:
            height = max(1, int(sheet.winfo_reqheight()))
            scroll.configure(scrollregion=(0, 0, pair_w, height))
            scroll.itemconfigure(scroll_win, width=pair_w)
            view = int(scroll.winfo_height())
            if view <= 1:
                return
            shown = bool(scroll_sb.winfo_manager())
            if height > view + 4 and not shown:
                scroll_sb.pack(side="right", fill="y")
            elif height <= view + 1 and shown:
                scroll_sb.pack_forget()

        sheet.bind("<Configure>", _sync_scroll, add="+")
        scroll.bind("<Configure>", _sync_scroll, add="+")
        _bind_wheel(scroll_host)
        return ui

    def _fit_worklog_scroll(self, ui: dict, *, screen_h: int | None = None) -> None:
        canvas = ui.get("scroll")
        sheet = ui.get("sheet")
        sb = ui.get("scroll_sb")
        dlg = ui.get("dlg")
        if canvas is None or sheet is None or dlg is None:
            return
        sheet.update_idletasks()
        sheet_h = max(1, int(sheet.winfo_reqheight()))
        pair_w = int(ui.get("pair_w") or sheet.winfo_reqwidth() or 1)
        canvas.itemconfigure(ui["scroll_win"], width=pair_w)
        canvas.configure(height=sheet_h, scrollregion=(0, 0, pair_w, sheet_h))
        if sb is not None and sb.winfo_manager():
            sb.pack_forget()
        dlg.update_idletasks()
        natural = max(1, int(dlg.winfo_reqheight()))
        raw = int(screen_h if screen_h is not None else dlg.winfo_screenheight())
        view, scroll = scroll_view(sheet_h, natural, raw)
        canvas.configure(height=view, scrollregion=(0, 0, pair_w, sheet_h))
        canvas.yview_moveto(0)
        if sb is None:
            return
        if scroll and not sb.winfo_manager():
            sb.pack(side="right", fill="y")
        elif not scroll and sb.winfo_manager():
            sb.pack_forget()

    def _open_worklog_dialog(self) -> None:
        self._worklog_tick(force=True)
        ui = self._ensure_worklog_ui()
        ui["stop"] = False
        ui["fg"] = layered_win.user32.GetForegroundWindow()
        ui["err"].set("")
        ui["anchor"] = date.today()
        ui["chart_day"] = date.today()
        self._fill_worklog(ui)
        self._fit_worklog_scroll(ui)
        _reveal_card(ui["dlg"], min_w=activity_chart.W * 2 + activity_chart.GAP + 48, min_h=420, near=self._dialog_near())
        _run_card_modal(ui["dlg"], self.win, on_frame=self._card_frame, stop=lambda: ui["stop"])
