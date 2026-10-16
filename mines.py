"""小游戏列表。规则在这里，不碰下班倒计时。"""
from __future__ import annotations

import random
import time
import tkinter as tk

ROWS = 9
COLS = 9
MINES = 10
_CELL = 28

GAMES = (
    {"id": "mines", "name": "扫雷", "blurb": "9×9，10 颗雷。左键翻开，右键插旗。"},
    {"id": "golf", "name": "高尔夫", "blurb": "只点不拖：牌面差 1 就能接，点牌堆翻一张。"},
)

_NUM = {
    1: "#7eb6ff",
    2: "#7dcea0",
    3: "#ff8b8b",
    4: "#c9a6ff",
    5: "#ffc46b",
    6: "#5fd0d0",
    7: "#f0f3f8",
    8: "#8b93a5",
}
_HIDDEN = "#2a3142"
_OPEN = "#12151c"
_FLAG = "#ffc46b"
_BOOM = "#c4552a"


class Board:
    """第一下不会踩雷。翻开所有非雷格即过关，旗子插错不影响判定。"""

    def __init__(self, rows: int = ROWS, cols: int = COLS, mines: int = MINES, seed: int | None = None) -> None:
        if mines >= rows * cols:
            raise ValueError("雷比格子还多")
        self.rows = rows
        self.cols = cols
        self.mines = mines
        self._rng = random.Random(seed)
        self.mine = [[False] * cols for _ in range(rows)]
        self.open = [[False] * cols for _ in range(rows)]
        self.flag = [[False] * cols for _ in range(rows)]
        self.started = False
        self.dead = False
        self.won = False

    def neighbors(self, r: int, c: int) -> list[tuple[int, int]]:
        out = []
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                rr, cc = r + dr, c + dc
                if 0 <= rr < self.rows and 0 <= cc < self.cols:
                    out.append((rr, cc))
        return out

    def around(self, r: int, c: int) -> int:
        return sum(1 for rr, cc in self.neighbors(r, c) if self.mine[rr][cc])

    def _lay(self, safe_r: int, safe_c: int) -> None:
        spots = [(r, c) for r in range(self.rows) for c in range(self.cols) if (r, c) != (safe_r, safe_c)]
        for r, c in self._rng.sample(spots, self.mines):
            self.mine[r][c] = True

    def _cleared(self) -> bool:
        for r in range(self.rows):
            for c in range(self.cols):
                if not self.mine[r][c] and not self.open[r][c]:
                    return False
        return True

    def _flood(self, r: int, c: int) -> None:
        stack = [(r, c)]
        while stack:
            rr, cc = stack.pop()
            if self.open[rr][cc] or self.flag[rr][cc] or self.mine[rr][cc]:
                continue
            self.open[rr][cc] = True
            if self.around(rr, cc) == 0:
                stack.extend(self.neighbors(rr, cc))

    def reveal(self, r: int, c: int) -> str:
        if self.dead or self.won:
            return "over"
        if self.flag[r][c] or self.open[r][c]:
            return "noop"
        if not self.started:
            self._lay(r, c)
            self.started = True
        if self.mine[r][c]:
            self.dead = True
            self.open[r][c] = True
            return "boom"
        self._flood(r, c)
        if self._cleared():
            self.won = True
            return "win"
        return "ok"

    def toggle_flag(self, r: int, c: int) -> str:
        if self.dead or self.won or self.open[r][c]:
            return "noop"
        self.flag[r][c] = not self.flag[r][c]
        return "flag"

    def flags(self) -> int:
        return sum(sum(1 for f in row if f) for row in self.flag)


def open_games(
    parent, near, win, *, dialog, button, reveal, modal, bg: str, fg: str, muted: str, poll_hide=None,
) -> None:
    """右键「小游戏」：先列表。poll_hide 用和卡片一样的隐藏键，把这个窗口一起收起。"""
    dlg = dialog(parent, near=near, width=360, height=460)
    # 整窗拖拽会把格子上的点击也当成挪窗口
    dlg.unbind("<ButtonPress-1>")
    dlg.unbind("<B1-Motion>")
    host = tk.Frame(dlg, bg=bg)
    host.pack(fill="both", expand=True)
    state: dict = {"tick": None}

    def drag_on(widget: tk.Misc) -> None:
        origin = {"x": 0, "y": 0}

        def start(e) -> None:
            origin["x"], origin["y"] = e.x_root, e.y_root

        def move(e) -> None:
            dx, dy = e.x_root - origin["x"], e.y_root - origin["y"]
            origin["x"], origin["y"] = e.x_root, e.y_root
            dlg.geometry(f"+{dlg.winfo_x() + dx}+{dlg.winfo_y() + dy}")

        widget.bind("<ButtonPress-1>", start)
        widget.bind("<B1-Motion>", move)

    def clear() -> None:
        state["tick"] = None
        for w in host.winfo_children():
            w.destroy()

    def show_list() -> None:
        clear()
        title = tk.Label(host, text="小游戏", fg=fg, bg=bg, font=("Microsoft YaHei UI", 13, "bold"))
        title.pack(anchor="w", padx=18, pady=(16, 4))
        drag_on(title)
        sub = tk.Label(host, text="隐藏键同样把这个窗口收起来。", fg=muted, bg=bg, font=("Microsoft YaHei UI", 9))
        sub.pack(anchor="w", padx=18, pady=(0, 12))
        drag_on(sub)
        for game in GAMES:
            row = tk.Frame(host, bg="#222733", cursor="hand2")
            row.pack(fill="x", padx=18, pady=(0, 8))
            name = tk.Label(row, text=game["name"], fg=fg, bg="#222733", font=("Microsoft YaHei UI", 12, "bold"))
            name.pack(anchor="w", padx=12, pady=(10, 0))
            blurb = tk.Label(row, text=game["blurb"], fg=muted, bg="#222733", font=("Microsoft YaHei UI", 9))
            blurb.pack(anchor="w", padx=12, pady=(2, 10))

            def go(_e=None, gid=game["id"]) -> None:
                if gid == "mines":
                    dlg.after(1, show_mines)
                elif gid == "golf":
                    dlg.after(1, show_golf)

            for w in (row, name, blurb):
                w.bind("<Button-1>", go)
        bar = tk.Frame(host, bg=bg)
        bar.pack(side="bottom", fill="x", pady=(8, 16))
        button(bar, "关闭", dlg.destroy).pack(side="left", padx=18)
        reveal(dlg, min_w=320, min_h=220, near=near)

    def show_mines() -> None:
        clear()
        board = Board()
        begun: list[float | None] = [None]
        status = tk.StringVar(value=f"剩余 {MINES}")
        clock = tk.StringVar(value="00:00")
        head = tk.Frame(host, bg=bg)
        head.pack(fill="x", padx=16, pady=(14, 8))
        title = tk.Label(head, text="扫雷", fg=fg, bg=bg, font=("Microsoft YaHei UI", 13, "bold"))
        title.pack(side="left")
        drag_on(title)
        tk.Label(head, textvariable=clock, fg=muted, bg=bg, font=("Consolas", 12)).pack(side="right")
        tk.Label(head, textvariable=status, fg=fg, bg=bg, font=("Microsoft YaHei UI", 10)).pack(side="right", padx=(0, 12))

        grid = tk.Frame(host, bg=bg, width=COLS * _CELL + 8, height=ROWS * _CELL + 8)
        grid.pack(pady=(0, 8))
        grid.pack_propagate(False)
        cells: dict[tuple[int, int], tk.Label] = {}

        def paint() -> None:
            left = board.mines - board.flags()
            if board.won:
                status.set("扫完了")
            elif board.dead:
                status.set("踩到了")
            else:
                status.set(f"剩余 {left}")
            for r in range(board.rows):
                for c in range(board.cols):
                    lab = cells[(r, c)]
                    if board.open[r][c]:
                        if board.mine[r][c]:
                            lab.configure(text="●", fg="white", bg=_BOOM)
                        else:
                            n = board.around(r, c)
                            lab.configure(text="" if n == 0 else str(n), fg=_NUM.get(n, fg), bg=_OPEN)
                    elif board.dead and board.mine[r][c]:
                        lab.configure(text="●", fg=_BOOM, bg=_HIDDEN)
                    elif board.flag[r][c]:
                        lab.configure(text="▲", fg=_FLAG, bg=_HIDDEN)
                    else:
                        lab.configure(text="", fg=fg, bg=_HIDDEN)

        def tick() -> None:
            if begun[0] is None or board.dead or board.won:
                return
            sec = int(time.monotonic() - begun[0])
            clock.set(f"{sec // 60:02d}:{sec % 60:02d}")

        def on_reveal(r: int, c: int) -> None:
            kind = board.reveal(r, c)
            if kind == "noop" or kind == "over":
                return
            if begun[0] is None:
                begun[0] = time.monotonic()
            paint()

        def on_flag(r: int, c: int) -> None:
            if board.toggle_flag(r, c) == "flag":
                paint()

        for r in range(ROWS):
            for c in range(COLS):
                lab = tk.Label(
                    grid, text="", bg=_HIDDEN, fg=fg,
                    font=("Consolas", 11, "bold"),
                )
                lab.place(x=4 + c * _CELL, y=4 + r * _CELL, width=_CELL - 2, height=_CELL - 2)
                lab.bind("<Button-1>", lambda _e, rr=r, cc=c: on_reveal(rr, cc))
                lab.bind("<Button-3>", lambda _e, rr=r, cc=c: on_flag(rr, cc))
                cells[(r, c)] = lab

        bar = tk.Frame(host, bg=bg)
        bar.pack(side="bottom", fill="x", pady=(4, 14))
        button(bar, "再来一局", lambda: dlg.after(1, show_mines), accent=True).pack(side="left", padx=(16, 6))
        button(bar, "返回", lambda: dlg.after(1, show_list)).pack(side="left", padx=6)
        state["tick"] = tick
        reveal(dlg, min_w=340, min_h=400, near=near)

    def show_golf() -> None:
        import golf

        clear()
        golf.mount(
            host, dlg,
            button=button, reveal=reveal, drag_on=drag_on,
            again=lambda: dlg.after(1, show_golf),
            back=lambda: dlg.after(1, show_list),
            bg=bg, fg=fg, muted=muted, near=near,
        )

    show_list()

    def on_frame() -> None:
        tick = state["tick"]
        if tick is not None:
            tick()
        if poll_hide is None:
            return
        try:
            hidden = bool(poll_hide())
            if not dlg.winfo_exists():
                return
            gone = dlg.state() == "withdrawn"
        except tk.TclError:
            return
        if hidden and not gone:
            dlg.withdraw()
        elif not hidden and gone:
            dlg.deiconify()
            try:
                dlg.attributes("-topmost", True)
            except tk.TclError:
                pass
            dlg.lift()

    modal(dlg, win, on_frame=on_frame)
