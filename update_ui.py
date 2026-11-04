"""检查更新窗口：下载、安装、连不上时扫码寄到邮箱。"""
from __future__ import annotations

import threading
import time
import tkinter as tk
from pathlib import Path

from PIL import Image, ImageTk

import changelog
import store
import updater
from card_ui import (
    _CARD_ACCENT,
    _CARD_BG,
    _CARD_FG,
    _CARD_MUTED,
    _card_btn,
    _card_dialog,
    _fit_card,
    _sync_open_card_hide,
)
from version import APP_VERSION


class UpdateDialogMixin:
    """WorkTimer 的一部分，方法里的 self 就是 WorkTimer。"""

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
            wraplength=284, justify="left", anchor="w",
        ).pack(fill="x", padx=18, anchor="w")
        progress = tk.StringVar(value="")
        progress_lbl = tk.Label(
            dlg, textvariable=progress, fg=_CARD_MUTED, bg=_CARD_BG, font=("Microsoft YaHei UI", 9),
            anchor="w",
        )
        # 更新前先让用户看到这版改了什么，别让人闭着眼点「现在更新」
        notes_box = tk.Frame(dlg, bg=_CARD_BG)
        notes_box.pack(fill="x", padx=18, anchor="w")
        # 不用系统进度条：它是原生控件，第一次画上去常是一条白的，深色卡片上就像闪了一下
        track = tk.Canvas(dlg, width=270, height=4, bg=_CARD_BG, highlightthickness=0, bd=0)
        pulse = {"mode": "idle", "n": 0}
        track_on = {"v": False}

        def paint_track() -> None:
            track.delete("all")
            track.create_rectangle(0, 0, 270, 4, fill="#2a3140", outline="")
            if pulse["mode"] == "busy":
                x = (int(pulse["n"]) * 18) % 340 - 70
                track.create_rectangle(max(0, x), 0, min(270, x + 70), 4, fill=_CARD_ACCENT, outline="")
            elif pulse["mode"] == "pct":
                width = max(0, min(270, int(270 * int(pulse["n"]) / 100)))
                if width:
                    track.create_rectangle(0, 0, width, 4, fill=_CARD_ACCENT, outline="")

        def show_track() -> None:
            if track_on["v"]:
                return
            track.pack(pady=(12, 4), padx=18)
            track_on["v"] = True

        def hide_track() -> None:
            pulse["mode"] = "idle"
            if not track_on["v"]:
                return
            try:
                track.pack_forget()
            except tk.TclError:
                pass
            track_on["v"] = False

        def conceal() -> None:
            """换内容前先透明。拆按钮、加说明都发生在看不见的时候。"""
            try:
                if dlg.state() == "withdrawn" or float(dlg.attributes("-alpha")) < 0.05:
                    return
                dlg.attributes("-alpha", 0.0)
                dlg.update()
            except tk.TclError:
                pass

        def present(min_w: int, min_h: int) -> None:
            _fit_card(dlg, min_w=min_w, min_h=min_h, near=near)

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
            conceal()
            hide_track()
            clear_notes()
            progress.set("")
            try:
                progress_lbl.pack_forget()
            except Exception:
                pass
            status.set(msg)
            detail.set(short(sub))
            set_btns([("好", on_close, False)])
            present(300, 160)

        def fail(msg: str) -> None:
            store.append_log(f"update: {(msg or '')[:180]}")
            head, hint = updater.friendly_error(msg)
            url = str(self.cfg.get("subscribe_url") or "").strip()
            if url and updater.is_network_error(msg):
                finish_subscribe(head, url)
                return
            finish_idle(head, hint, error=True)

        def finish_subscribe(head: str, url: str, detail_text: str = "") -> None:
            if not alive():
                return
            state["phase"] = "idle"
            conceal()
            hide_track()
            clear_notes()
            progress.set("")
            try:
                progress_lbl.pack_forget()
            except Exception:
                pass
            status.set(head)
            detail.set(detail_text or "扫下面的码，把下载地址寄到邮箱。")
            import qrcode

            code = qrcode.QRCode(border=1, box_size=4, error_correction=qrcode.constants.ERROR_CORRECT_M)
            code.add_data(url)
            code.make(fit=True)
            img = code.make_image(fill_color="#1a1a1a", back_color="#f6f1e8").convert("RGB")
            img = img.resize((168, 168), Image.NEAREST)
            photo = ImageTk.PhotoImage(img)
            slot = tk.Label(notes_box, image=photo, bg=_CARD_BG)
            slot.image = photo
            slot.pack(pady=(8, 0))
            set_btns([("好", on_close, False)])
            present(300, 320)

        def start_download(info: updater.ReleaseInfo) -> None:
            if not alive():
                return
            if updater.current_exe_path() is None:
                finish_idle("开发模式不能在线更新", "用安装好的程序才能检查更新", error=True)
                return
            state["phase"] = "download"
            state["cancel"] = False
            conceal()
            clear_notes()
            try:
                notes_box.pack_forget()
            except Exception:
                pass
            status.set("正在下载新版本…")
            detail.set("下完会自己装上。")
            progress.set("")
            set_btns([("取消", on_close, False)])
            pulse["mode"] = "pct"
            pulse["n"] = 0
            paint_track()
            # 进度条和说明都就位后再量高度，不然条会压到「日程不会丢」那一行上
            try:
                progress_lbl.pack(fill="x", padx=18, pady=(6, 0), anchor="w")
            except Exception:
                pass
            show_track()
            present(320, 168)

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
                            pulse["mode"] = "pct"
                            pulse["n"] = pct
                            paint_track()
                            progress.set(
                                f"已下 {done / (1024 * 1024):.1f} MB，一共 {total / (1024 * 1024):.1f} MB"
                            )
                        else:
                            pulse["mode"] = "busy"
                            pulse["n"] = int(pulse["n"]) + 1
                            paint_track()
                            progress.set(f"已下 {done / (1024 * 1024):.1f} MB")
                    elif kind == "ok":
                        path = done_box[0][1]
                        try:
                            import share

                            share.remember_setup(Path(path), info.asset_name)
                        except Exception:
                            pass
                        status.set("正在安装，马上就好")
                        detail.set("窗口会关一下再打开。")
                        progress.set("下载完成")
                        pulse["mode"] = "pct"
                        pulse["n"] = 100
                        paint_track()
                        present(320, 168)
                        dlg.update()
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
                    _sync_open_card_hide(dlg, self.win)
                    dlg.update()
                    self.win.pump()
                    self._card_frame()
                    self._note_beat()
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
            conceal()
            hide_track()
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
            present(300, 170)

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
            started = time.monotonic()
            checking_shown = False

            def apply_result() -> None:
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

            while alive() and state["phase"] == "check":
                if result_box:
                    apply_result()
                    break
                # 查得快就别先弹出「正在看看」再立刻换成结果，那一下也是闪
                if not checking_shown and time.monotonic() - started >= 0.28:
                    pulse["mode"] = "busy"
                    paint_track()
                    show_track()
                    present(300, 170)
                    checking_shown = True
                elif checking_shown:
                    pulse["n"] = int(pulse["n"]) + 1
                    paint_track()
                try:
                    _sync_open_card_hide(dlg, self.win)
                    dlg.update()
                    self.win.pump()
                    self._card_frame()
                    self._note_beat()
                except Exception:
                    state["closed"] = True
                    break
                time.sleep(0.03)

        while alive() and state["phase"] in ("ask", "idle"):
            pending = state.get("pending_dl")
            if pending is not None:
                state["pending_dl"] = None
                start_download(pending)
                break
            try:
                _sync_open_card_hide(dlg, self.win)
                dlg.update()
                self.win.pump()
                self._card_frame()
                self._note_beat()
            except Exception:
                break
            time.sleep(0.03)
