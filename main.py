"""透明弹性下班计时器：桌面置顶小窗，点一下录入 8:30–9:30 到岗时间。"""
from __future__ import annotations

import ctypes
import os
import ssl
import sys
import time
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import messagebox, ttk

from PIL import Image, ImageDraw, ImageFont

import ad_disguise
import flex_time
import layered_win
import store
import themes
import updater
from version import APP_VERSION

WIN_W = 360
WIN_H = 100
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
        bgra[i * 4 + 0] = (b * a) // 255
        bgra[i * 4 + 1] = (g * a) // 255
        bgra[i * 4 + 2] = (r * a) // 255
        bgra[i * 4 + 3] = a
        mask[i] = a
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
        mode = str(self.cfg.get("display_mode") or "hms")
        self.cfg["display_mode"] = mode if mode in flex_time.DISPLAY_MODES else "hms"
        tid = str(self.cfg.get("theme") or themes.DEFAULT_THEME_ID)
        self.cfg["theme"] = tid
        try:
            ssl.create_default_context()
        except Exception:
            pass
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
        if self._has_start():
            self._cycle_display()
            return
        self._need_dialog = True

    def _toggle_disguise(self) -> None:
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
        if down and not self._esc_held:
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

    def _open_time_dialog(self) -> None:
        preset = self._start_hm()
        picked = _ask_start_time(
            self._tk_root(),
            preset,
            near=(self.win.x, self.win.y + WIN_H + 8),
        )
        if picked is None:
            return
        self.cfg["start_h"], self.cfg["start_m"] = picked
        self.cfg["start_date"] = self._today()
        store.save_config(self.cfg)
        self._last_key = ""

    def _handle_menu(self, sx: int, sy: int) -> None:
        op = self.win.popup_menu(sx, sy, self._display_mode(), self._theme().id)
        if op == "quit":
            self.running = False
        elif op == "update":
            self._check_update()
        elif op == "set_time":
            self._open_time_dialog()
        elif op == "disguise":
            self._toggle_disguise()
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
        status, info = updater.check_update(self.cfg)
        root = self._tk_root()
        if status == "no_repo":
            messagebox.showinfo(
                "检查更新",
                f"还没配置 GitCode 仓库。\n当前版本：{APP_VERSION}\n\n"
                f"写入 {store.config_path()} 的 gitcode_repo 字段。",
                parent=root,
            )
            return
        if status.startswith("error:"):
            messagebox.showerror("检查更新", status[6:], parent=root)
            return
        if status == "latest":
            messagebox.showinfo(
                "检查更新",
                f"已是最新版。\n当前：{APP_VERSION}\n远端：{info.version if info else '-'}",
                parent=root,
            )
            return
        if status != "available" or info is None:
            return
        body = (info.body or "").strip()
        tip = body[:300] + ("…" if len(body) > 300 else "")
        ok = messagebox.askyesno(
            "发现新版本",
            f"当前：{APP_VERSION}\n最新：{info.version}（{info.tag}）\n\n{tip}\n\n是否下载并更新？",
            parent=root,
        )
        if not ok:
            return
        if updater.current_exe_path() is None:
            messagebox.showinfo("检查更新", "源码运行请重新打包 exe，或手动下载 Release 附件。", parent=root)
            return
        try:
            path = updater.download_update(info, self.cfg)
            updater.apply_update_and_restart(path)
            updater.force_exit_for_update()
        except Exception as e:  # noqa: BLE001
            messagebox.showerror("更新失败", str(e), parent=root)

    def _paint(self) -> None:
        try:
            start = self._start_hm()
            now = datetime.now()
            mode = self._display_mode()
            theme = self._theme()
            if start is None:
                key = f"idle-{mode}-{theme.id}-{theme.fill}-{theme.kind}"
                title = "弹性下班"
                big = "点击开始"
                sub = ""
                accent = theme.idle
            else:
                oh, om = flex_time.offwork_hm(*start)
                td = flex_time.remaining_to(now, oh, om)
                total, done = flex_time.remaining_parts(td)
                big = flex_time.format_remaining(total, mode)
                sub = ""
                if done:
                    key = f"done-{mode}-{theme.id}-{total}-{theme.fill}"
                    title = "已经到点"
                    accent = theme.done
                else:
                    key = f"run-{mode}-{theme.id}-{big}-{theme.fill}"
                    title = "距离您下班还有"
                    mins = total // 60
                    accent = theme.warn if mins < 30 else theme.big

            if key == self._last_key:
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
                    self._open_time_dialog()
                if themes.consume_updated():
                    self._last_key = ""
                dragging = self.win.dragging
                moved = self.win.just_moved
                if dragging:
                    was_dragging = True
                    time.sleep(0.001)
                    continue
                if was_dragging or moved:
                    self.win.ensure_visible()
                    self._last_key = ""
                    self._persist_pos()
                    last_save = time.monotonic()
                    was_dragging = False
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
