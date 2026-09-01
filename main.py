"""透明弹性下班计时器：桌面置顶小窗，点一下录入 8:30–9:30 到岗时间。"""
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

from PIL import Image, ImageDraw, ImageFont

import ad_disguise
import backdrop
import flex_time
import layered_win
import store
import themes
import updater
from version import APP_VERSION

WIN_W = 248
WIN_H = 92
FPS = 60


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


def _ask_start_time(
    parent: tk.Tk | None,
    preset: tuple[int, int] | None,
    *,
    near: tuple[int, int] | None = None,
) -> tuple[int, int] | None:
    result: list[tuple[int, int] | None] = [None]
    dlg = tk.Toplevel(parent)
    dlg.title("上班时间")
    dlg.resizable(False, False)
    dlg.attributes("-topmost", True)
    dlg.configure(bg="#1b1e26")
    if near:
        dlg.geometry(f"340x220+{int(near[0])}+{int(near[1])}")
    else:
        dlg.geometry("340x220")
    try:
        dlg.lift()
        dlg.focus_force()
    except Exception:
        pass
    dlg.grab_set()

    ph, pm = preset if preset else (9, 0)
    var = tk.StringVar(value="" if preset is None else f"{ph}:{pm:02d}")
    preview = tk.StringVar()

    def refresh_preview(*_a) -> None:
        parsed = flex_time.parse_start(var.get())
        if parsed is None:
            preview.set("请输入 8:30–9:30 之间的时间")
            return
        oh, om = flex_time.offwork_hm(*parsed)
        preview.set(f"弹性下班：{flex_time.format_hm(oh, om)}")

    var.trace_add("write", refresh_preview)
    refresh_preview()

    tk.Label(
        dlg,
        text="今天几点到岗？",
        fg="#f4f6fb",
        bg="#1b1e26",
        font=("Microsoft YaHei UI", 13, "bold"),
    ).pack(pady=(18, 4))
    tk.Label(
        dlg,
        text="弹性区间 8:30–9:30，对应下班 18:00–19:00",
        fg="#9aa3b5",
        bg="#1b1e26",
        font=("Microsoft YaHei UI", 9),
    ).pack()

    entry = ttk.Entry(dlg, textvariable=var, font=("Microsoft YaHei UI", 16), justify="center", width=12)
    entry.pack(pady=14)
    entry.select_range(0, tk.END)
    entry.focus_set()

    tk.Label(dlg, textvariable=preview, fg="#7ec8ff", bg="#1b1e26", font=("Microsoft YaHei UI", 10)).pack()

    def ok() -> None:
        parsed = flex_time.parse_start(var.get())
        if parsed is None:
            messagebox.showwarning("上班时间", "请输入 8:30 到 9:30 之间的时间，例如 8.45 或 9:10", parent=dlg)
            return
        result[0] = parsed
        dlg.destroy()

    def cancel() -> None:
        dlg.destroy()

    bar = tk.Frame(dlg, bg="#1b1e26")
    bar.pack(pady=16)
    tk.Button(bar, text="开始计时", command=ok, width=10, bg="#3d7eff", fg="white", relief="flat").pack(
        side="left", padx=8
    )
    tk.Button(bar, text="取消", command=cancel, width=8, bg="#3a3f4b", fg="white", relief="flat").pack(
        side="left", padx=8
    )
    dlg.bind("<Return>", lambda _e: ok())
    dlg.bind("<Escape>", lambda _e: cancel())
    dlg.wait_window()
    return result[0]


def _ask_off_time(
    parent: tk.Tk | None,
    preset: tuple[int, int] | None,
    *,
    near: tuple[int, int] | None = None,
) -> tuple[int, int] | None:
    result: list[tuple[int, int] | None] = [None]
    dlg = tk.Toplevel(parent)
    dlg.title("下班时间")
    dlg.resizable(False, False)
    dlg.attributes("-topmost", True)
    dlg.configure(bg="#1b1e26")
    if near:
        dlg.geometry(f"340x200+{int(near[0])}+{int(near[1])}")
    else:
        dlg.geometry("340x200")
    try:
        dlg.lift()
        dlg.focus_force()
    except Exception:
        pass
    dlg.grab_set()

    ph, pm = preset if preset else (18, 0)
    var = tk.StringVar(value="" if preset is None else f"{ph}:{pm:02d}")
    preview = tk.StringVar()

    def refresh_preview(*_a) -> None:
        parsed = flex_time.parse_clock(var.get())
        if parsed is None:
            preview.set("请输入今天的下班时间，例如 18:00")
            return
        preview.set(f"倒计时到 {flex_time.format_hm(*parsed)}")

    var.trace_add("write", refresh_preview)
    refresh_preview()

    tk.Label(
        dlg,
        text="今天下班几点？",
        fg="#f4f6fb",
        bg="#1b1e26",
        font=("Microsoft YaHei UI", 13, "bold"),
    ).pack(pady=(18, 4))
    tk.Label(
        dlg,
        text="直接按这个点倒计时，不走弹性 9.5 小时",
        fg="#9aa3b5",
        bg="#1b1e26",
        font=("Microsoft YaHei UI", 9),
    ).pack()

    entry = ttk.Entry(dlg, textvariable=var, font=("Microsoft YaHei UI", 16), justify="center", width=12)
    entry.pack(pady=14)
    entry.select_range(0, tk.END)
    entry.focus_set()
    tk.Label(dlg, textvariable=preview, fg="#7ec8ff", bg="#1b1e26", font=("Microsoft YaHei UI", 10)).pack()

    def ok() -> None:
        parsed = flex_time.parse_clock(var.get())
        if parsed is None:
            messagebox.showwarning("下班时间", "请输入 0:00 到 23:59，例如 18:00 或 18.30", parent=dlg)
            return
        result[0] = parsed
        dlg.destroy()

    def cancel() -> None:
        dlg.destroy()

    bar = tk.Frame(dlg, bg="#1b1e26")
    bar.pack(pady=16)
    tk.Button(bar, text="开始计时", command=ok, width=10, bg="#3d7eff", fg="white", relief="flat").pack(
        side="left", padx=8
    )
    tk.Button(bar, text="取消", command=cancel, width=8, bg="#3a3f4b", fg="white", relief="flat").pack(
        side="left", padx=8
    )
    dlg.bind("<Return>", lambda _e: ok())
    dlg.bind("<Escape>", lambda _e: cancel())
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
        self.running = True
        self._menu_pos: tuple[int, int] | None = None
        self._need_dialog = False
        self._tk: tk.Tk | None = None

        self.win = layered_win.LayeredPetWindow(WIN_W, WIN_H, "弹性下班")
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
            x = int(area.right - WIN_W - 24)
            y = int(area.top + 24)
        x, y = layered_win.clamp_pos(int(x), int(y), WIN_W, WIN_H)
        self.win.move(x, y)

        self._font_title = _font(15)
        self._font_big = _font(28)
        self._font_sub = _font(12)
        self._last_key = ""
        self._surface = "dark"
        self._blend_from_surface = "dark"
        self._blend_to_surface = "dark"
        self._blend_t0: float | None = None
        self._surface_votes = 0
        self._surface_vote_for = ""
        self._surface_boot = True
        self._last_surface_sample = 0.0
        self._force_surface_sample = True
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

    def _blend_amount(self) -> float:
        if self._blend_t0 is None:
            return 1.0
        # ~0.55 秒缓变：既不明显跳，又不会拖太久
        u = (time.monotonic() - self._blend_t0) / 0.55
        if u >= 1.0:
            self._blend_t0 = None
            self._blend_from_surface = self._blend_to_surface
            return 1.0
        # smoothstep
        return u * u * (3.0 - 2.0 * u)

    def _start_surface_blend(self, to: str) -> None:
        if to not in ("dark", "light"):
            return
        if to == self._surface and self._blend_t0 is None:
            return
        amt = self._blend_amount()
        if self._blend_t0 is not None and amt < 1.0:
            # 缓变中途改方向：从当前更接近的一侧接着混
            self._blend_from_surface = (
                self._blend_to_surface if amt >= 0.5 else self._blend_from_surface
            )
        else:
            self._blend_from_surface = self._surface
        self._blend_to_surface = to
        self._surface = to
        self._blend_t0 = time.monotonic()
        self._last_key = ""

    def _refresh_surface(self, *, force: bool = False) -> None:
        """带 adaptive 的皮采样窗周明暗；切换用缓变，避免闪一下。"""
        theme = self._theme()
        if not theme.adaptive:
            return
        now = time.monotonic()
        # 约 1.2s 采一次；连续 2 次同意就切（约 2.5s 内开始缓变）
        if not force and not self._force_surface_sample and now - self._last_surface_sample < 1.2:
            return
        self._last_surface_sample = now
        self._force_surface_sample = False
        luma = backdrop.sample_luma_around(self.win.x, self.win.y, WIN_W, WIN_H)
        if luma is None:
            return
        surface = backdrop.classify_surface(luma, self._surface)
        # 启动第一次：直接落到正确一侧，不播放缓变（避免先错色再闪）
        if self._surface_boot:
            self._surface_boot = False
            self._surface = surface
            self._blend_from_surface = surface
            self._blend_to_surface = surface
            self._blend_t0 = None
            self._last_key = ""
            return
        if surface == self._surface:
            self._surface_votes = 0
            self._surface_vote_for = ""
            return
        if surface == self._surface_vote_for:
            self._surface_votes += 1
        else:
            self._surface_vote_for = surface
            self._surface_votes = 1
        if self._surface_votes >= 2:
            self._surface_votes = 0
            self._surface_vote_for = ""
            self._start_surface_blend(surface)

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

    def _on_click(self) -> None:
        if self._disguised:
            return
        if self._has_target():
            self._cycle_display()
            return
        self._need_dialog = True

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
        return (self.win.x, self.win.y + WIN_H + 8)

    def _open_time_dialog(self) -> None:
        preset = self._start_hm()
        picked = _ask_start_time(self._tk_root(), preset, near=self._dialog_near())
        if picked is None:
            return
        self.cfg["time_mode"] = "flex"
        self.cfg["start_h"], self.cfg["start_m"] = picked
        self.cfg["start_date"] = self._today()
        store.save_config(self.cfg)
        self._last_key = ""

    def _open_off_dialog(self) -> None:
        if self._time_mode() == "direct" and self._has_target():
            preset = self._off_hm()
        else:
            oh, om = self.cfg.get("off_h"), self.cfg.get("off_m")
            preset = (int(oh), int(om)) if isinstance(oh, int) and isinstance(om, int) else (18, 0)
        picked = _ask_off_time(self._tk_root(), preset, near=self._dialog_near())
        if picked is None:
            return
        self.cfg["time_mode"] = "direct"
        self.cfg["off_h"], self.cfg["off_m"] = picked
        self.cfg["start_date"] = self._today()
        store.save_config(self.cfg)
        self._last_key = ""

    def _open_idle_dialog(self) -> None:
        if self._time_mode() == "direct":
            self._open_off_dialog()
            return
        self._open_time_dialog()

    def _handle_menu(self, sx: int, sy: int) -> None:
        op = self.win.popup_menu(
            sx, sy, self._display_mode(), self._theme().id, esc_disguise=self._esc_disguise_on()
        )
        if op == "quit":
            self.running = False
        elif op == "update":
            self._check_update()
        elif op == "set_time":
            self._open_time_dialog()
        elif op == "set_off":
            self._open_off_dialog()
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
            target = self._off_hm()
            now = datetime.now()
            mode = self._display_mode()
            base = self._theme()
            blend_amt = 1.0
            if base.adaptive:
                blend_amt = self._blend_amount()
                ta = themes.resolve_for_surface(base, self._blend_from_surface)
                tb = themes.resolve_for_surface(base, self._blend_to_surface)
                theme = themes.blend_themes(ta, tb, blend_amt)
                surface_key = f"{self._blend_from_surface}-{self._blend_to_surface}"
            else:
                theme = base
                surface_key = "fixed"
            if target is None:
                key = f"idle-{mode}-{theme.id}-{theme.fill}-{theme.kind}-{surface_key}"
                title = "弹性下班"
                big = "点击开始"
                sub = ""
                accent = theme.idle
            else:
                oh, om = target
                td = flex_time.remaining_to(now, oh, om)
                total, done = flex_time.remaining_parts(td)
                big = flex_time.format_remaining(total, mode)
                sub = ""
                if done:
                    key = f"done-{mode}-{theme.id}-{total}-{theme.fill}-{surface_key}"
                    title = "已经到点"
                    accent = theme.done
                else:
                    key = f"run-{mode}-{theme.id}-{big}-{theme.fill}-{surface_key}"
                    title = "距离您下班还有"
                    mins = total // 60
                    accent = theme.warn if mins < 30 else theme.big

            # 缓变中每帧重绘；静止时按 key 省电
            if self._blend_t0 is None and key == self._last_key:
                return

            img = Image.new("RGBA", (WIN_W, WIN_H), (0, 0, 0, 0))
            d = ImageDraw.Draw(img)
            themes.paint_card(
                d, WIN_W, WIN_H, theme, title, big, sub, accent,
                self._font_title, self._font_big, self._font_sub,
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
                if themes.consume_updated():
                    self._last_key = ""
                    self._force_surface_sample = True
                dragging = self.win.dragging
                moved = self.win.just_moved
                if dragging:
                    was_dragging = True
                    time.sleep(0.001)
                    continue
                if was_dragging or moved:
                    self.win.ensure_visible()
                    self._last_key = ""
                    # 拖完立刻采一次，缩短「换墙纸还干等」的感觉
                    self._force_surface_sample = True
                    self._surface_votes = 0
                    self._surface_vote_for = ""
                    self._persist_pos()
                    last_save = time.monotonic()
                    was_dragging = False
                self._refresh_surface()
                self._paint()
                now = time.monotonic()
                if now - last_save > 1.5:
                    self._persist_pos()
                    last_save = now
                time.sleep(1.0 / FPS)
            except Exception as e:  # noqa: BLE001
                store.log_exception("loop", e)
                time.sleep(0.05)
        self._persist_pos()
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
            messagebox.showerror("弹性下班计时器", str(e))
        except Exception:
            pass


if __name__ == "__main__":
    main()
