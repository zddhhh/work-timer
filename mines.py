"""小游戏列表。规则在这里，不碰下班倒计时。"""
from __future__ import annotations

import random
import time
import tkinter as tk
import webbrowser

LEVELS = (
    {"id": "easy", "name": "初级", "rows": 9, "cols": 9, "mines": 10},
    {"id": "normal", "name": "中级", "rows": 16, "cols": 16, "mines": 40},
    {"id": "hard", "name": "高级", "rows": 16, "cols": 30, "mines": 99},
)
ROWS = LEVELS[0]["rows"]
COLS = LEVELS[0]["cols"]
MINES = LEVELS[0]["mines"]

# 浏览器精选：Fable 5.2 一类单文件/程序化小作。不打包进安装包，只打开系统浏览器。
# Saltline 用作者镜像；其余走 fable52 可玩页（沙箱页，链接稳一点）。
SALTLINE_URL = "https://realcodebear.github.io/saltline-fable-5.2/"
FABLE52_PLAY = "https://fable52.games/play"
BROWSER_ARCADE_URL = "https://fable52.games/"

GAMES = (
    {
        "id": "mines",
        "name": "扫雷",
        "blurb": "左键翻开，右键插旗。初级、中级、高级都能选。",
        "kind": "local",
        "group": "本机",
    },
    {
        "id": "golf",
        "name": "高尔夫",
        "blurb": "只点不拖：牌面差 1 就能接，点牌堆翻一张。",
        "kind": "local",
        "group": "本机",
    },
    {
        "id": "pool",
        "name": "台球",
        "blurb": "按住白球往后拉，松开就打。彩球都进袋就过关。",
        "kind": "local",
        "group": "本机",
    },
    {
        "id": "saltline",
        "name": "港区射击",
        "blurb": "雨夜集装箱码头。点页面锁定鼠标后开始。",
        "kind": "browser",
        "group": "浏览器 · 射击",
        "tag": "FPS",
        "url": SALTLINE_URL,
    },
    {
        "id": "sublevel",
        "name": "地下变电",
        "blurb": "潮湿走廊 + 反光地面，三波悬浮无人机。体积只有约 128KB。",
        "kind": "browser",
        "group": "浏览器 · 射击",
        "tag": "FPS",
        "url": f"{FABLE52_PLAY}/sublevel-07-fps-repro",
    },
    {
        "id": "transport",
        "name": "运输船",
        "blurb": "经典运输船图，浏览器里和人机混战。",
        "kind": "browser",
        "group": "浏览器 · 射击",
        "tag": "FPS",
        "url": f"{FABLE52_PLAY}/transport-ship-3d",
    },
    {
        "id": "mothlight",
        "name": "蛾光竞速",
        "blurb": "雨夜赛博城穿光门，五个区十二道门。",
        "kind": "browser",
        "group": "浏览器 · 其它",
        "tag": "竞速",
        "url": f"{FABLE52_PLAY}/mothlight",
    },
    {
        "id": "soccer",
        "name": "口袋足球",
        "blurb": "七人制 3D，有裁判、越位和点球。",
        "kind": "browser",
        "group": "浏览器 · 其它",
        "tag": "运动",
        "url": f"{FABLE52_PLAY}/pocket-soccer-3d",
    },
    {
        "id": "evensong",
        "name": "晚祷对决",
        "blurb": "淹水教堂里的灵魂系单 Boss。",
        "kind": "browser",
        "group": "浏览器 · 其它",
        "tag": "动作",
        "url": f"{FABLE52_PLAY}/evensong",
    },
    {
        "id": "waterkeeps",
        "name": "水中所留",
        "blurb": "灯笼小船漂过多重梦境河段，偏氛围。",
        "kind": "browser",
        "group": "浏览器 · 其它",
        "tag": "氛围",
        "url": f"{FABLE52_PLAY}/what-the-water-keeps",
    },
    {
        "id": "qingyun",
        "name": "青云御剑",
        "blurb": "云海上御剑采灵，点亮宗门。",
        "kind": "browser",
        "group": "浏览器 · 其它",
        "tag": "飞行",
        "url": f"{FABLE52_PLAY}/qingyun-sword-flight",
    },
    {
        "id": "tidebell",
        "name": "潮钟",
        "blurb": "驾驶小潜器下潜，唤醒七口潮钟。",
        "kind": "browser",
        "group": "浏览器 · 其它",
        "tag": "探索",
        "url": f"{FABLE52_PLAY}/tidebell",
    },
    {
        "id": "wusuo",
        "name": "雾锁山门",
        "blurb": "雪夜山门武侠动作小品。",
        "kind": "browser",
        "group": "浏览器 · 其它",
        "tag": "武侠",
        "url": f"{FABLE52_PLAY}/wusuo-shanmen",
    },
)

GAME_GROUPS = ("本机", "浏览器 · 射击", "浏览器 · 其它")


def games_in_group(group: str) -> list[dict]:
    return [g for g in GAMES if g.get("group") == group]


def open_browser_game(url: str) -> bool:
    """打开用户默认浏览器。失败返回 False，由界面提示。"""
    target = (url or "").strip()
    if not target:
        return False
    try:
        return bool(webbrowser.open(target, new=2))
    except Exception:
        return False

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


def cell_side(cols: int, rows: int) -> int:
    """格子别大过初级的 28，也别小过能点中的 16。高级因此不用上百个控件。"""
    return max(16, min(28, 520 // max(1, cols), 440 // max(1, rows)))


def reset_session() -> None:
    """测试或主动清档。关掉窗口不会清，下一把还能接着玩。"""
    _SAVE.clear()
    _SAVE.update({"page": "list", "level": LEVELS[0]["id"], "mines": {}, "golf": None, "pool": None})
    import pool
    pool.set_guide_lines(False)


_SAVE: dict = {}
reset_session()


def _level(lid: str | None = None) -> dict:
    want = lid or _SAVE.get("level") or LEVELS[0]["id"]
    for lv in LEVELS:
        if lv["id"] == want:
            return lv
    return LEVELS[0]


def mines_slot(level_id: str | None = None, *, reset: bool = False) -> dict:
    lid = _level(level_id)["id"]
    _SAVE["level"] = lid
    bag = _SAVE.setdefault("mines", {})
    slot = bag.get(lid)
    lv = _level(lid)
    if reset or not isinstance(slot, dict) or not isinstance(slot.get("board"), Board):
        slot = {"board": Board(lv["rows"], lv["cols"], lv["mines"]), "elapsed": 0.0, "running_since": None}
        bag[lid] = slot
    return slot


def mines_in_progress(level_id: str | None = None) -> bool:
    if level_id is None:
        return any(mines_in_progress(lv["id"]) for lv in LEVELS)
    slot = _SAVE.get("mines", {}).get(level_id)
    board = slot.get("board") if isinstance(slot, dict) else None
    return isinstance(board, Board) and board.started and not board.dead and not board.won


def mines_elapsed(level_id: str | None = None) -> float:
    slot = _SAVE.get("mines", {}).get(level_id or _SAVE.get("level"))
    if not isinstance(slot, dict):
        return 0.0
    total = float(slot.get("elapsed") or 0.0)
    started = slot.get("running_since")
    if isinstance(started, (int, float)):
        total += max(0.0, time.monotonic() - started)
    return total


def pause_mines_clock(level_id: str | None = None) -> None:
    slot = _SAVE.get("mines", {}).get(level_id or _SAVE.get("level"))
    if not isinstance(slot, dict) or slot.get("running_since") is None:
        return
    slot["elapsed"] = mines_elapsed(level_id or _SAVE.get("level"))
    slot["running_since"] = None


def resume_mines_clock(level_id: str | None = None) -> None:
    slot = mines_slot(level_id)
    board = slot["board"]
    if not board.started or board.dead or board.won:
        return
    if slot.get("running_since") is None:
        slot["running_since"] = time.monotonic()


def golf_board(*, reset: bool = False):
    import golf

    board = _SAVE.get("golf")
    if reset or board is None:
        board = golf.Board()
        _SAVE["golf"] = board
    return board


def golf_in_progress() -> bool:
    board = _SAVE.get("golf")
    return board is not None and bool(getattr(board, "moved", False)) and not getattr(board, "won", False)


def pool_board(*, reset: bool = False):
    import pool

    board = _SAVE.get("pool")
    if reset or board is None:
        board = pool.Board()
        _SAVE["pool"] = board
    return board


def pool_in_progress() -> bool:
    board = _SAVE.get("pool")
    return board is not None and bool(getattr(board, "moved", False)) and not getattr(board, "won", False)


def _clock_text(elapsed: float) -> str:
    sec = max(0, int(elapsed))
    return f"{sec // 60:02d}:{sec % 60:02d}"


def open_games(
    parent, near, win, *, dialog, button, reveal, modal, bg: str, fg: str, muted: str,
    poll_hide=None, live=None,
) -> None:
    """右键「小游戏」：先列表。poll_hide 用和卡片一样的隐藏键。live 在弹窗挡住主循环时继续刷新倒计时。"""
    dlg = dialog(parent, near=near, width=400, height=540)
    # 整窗拖拽会把格子上的点击也当成挪窗口
    dlg.unbind("<ButtonPress-1>")
    dlg.unbind("<B1-Motion>")
    host = tk.Frame(dlg, bg=bg)
    host.pack(fill="both", expand=True)
    state: dict = {"tick": None, "level_id": _SAVE.get("level") or LEVELS[0]["id"]}

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
        dlg.unbind("<MouseWheel>")
        for w in host.winfo_children():
            w.destroy()

    def conceal() -> None:
        """换页前先透明。清控件和改尺寸都发生在看不见的时候，避免空底板闪一下。"""
        try:
            if dlg.state() == "withdrawn":
                return
            dlg.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

    def show_list() -> None:
        pause_mines_clock()
        _SAVE["page"] = "list"
        conceal()
        clear()
        title = tk.Label(host, text="小游戏", fg=fg, bg=bg, font=("Microsoft YaHei UI", 13, "bold"))
        title.pack(anchor="w", padx=18, pady=(14, 2))
        drag_on(title)
        tip = tk.Label(
            host,
            text="本机免联网；浏览器项会打开系统浏览器，不装进安装包。",
            fg=muted,
            bg=bg,
            font=("Microsoft YaHei UI", 8),
            wraplength=350,
            justify="left",
        )
        tip.pack(anchor="w", padx=18, pady=(0, 8))
        drag_on(tip)

        list_w = 360
        mid = tk.Frame(host, bg=bg)
        mid.pack(side="top", fill="both", expand=True, padx=18)
        canvas = tk.Canvas(mid, bg=bg, highlightthickness=0, bd=0, width=list_w, height=380)
        rows = tk.Frame(canvas, bg=bg)
        win_id = canvas.create_window((0, 0), window=rows, anchor="nw", width=list_w)
        canvas.pack(fill="both", expand=True)

        def sync_scroll(_e=None) -> None:
            width = canvas.winfo_width()
            if width < 50:
                width = list_w
            canvas.itemconfigure(win_id, width=width)
            canvas.configure(scrollregion=canvas.bbox("all") or (0, 0, width, 0))

        wheel = {"acc": 0.0}
        canvas.configure(yscrollincrement=1)

        def on_wheel(e) -> str:
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

        rows.bind("<Configure>", sync_scroll)
        canvas.bind("<Configure>", sync_scroll)
        dlg.bind("<MouseWheel>", on_wheel)

        def launch(gid: str, link: str, blurb_lbl: tk.Label) -> None:
            if gid == "mines":
                dlg.after(1, lambda: show_mines(reset=False))
            elif gid == "golf":
                dlg.after(1, lambda: show_golf(reset=False))
            elif gid == "pool":
                dlg.after(1, lambda: show_pool(reset=False))
            elif link:
                ok = open_browser_game(str(link))
                if ok:
                    try:
                        dlg.destroy()
                    except tk.TclError:
                        pass
                else:
                    blurb_lbl.configure(text="浏览器没打开，检查默认浏览器设置后再试。")

        for group in GAME_GROUPS:
            items = games_in_group(group)
            if not items:
                continue
            head = tk.Label(
                rows,
                text=group,
                fg=muted,
                bg=bg,
                font=("Microsoft YaHei UI", 9, "bold"),
            )
            head.pack(anchor="w", pady=(6 if group != GAME_GROUPS[0] else 0, 4))
            drag_on(head)
            for game in items:
                going = (
                    (game["id"] == "mines" and mines_in_progress())
                    or (game["id"] == "golf" and golf_in_progress())
                    or (game["id"] == "pool" and pool_in_progress())
                )
                row = tk.Frame(rows, bg="#222733", cursor="hand2")
                row.pack(fill="x", pady=(0, 6))
                top = tk.Frame(row, bg="#222733")
                top.pack(fill="x", padx=12, pady=(9, 0))
                label = game["name"] + ("  · 继续" if going else "")
                name = tk.Label(
                    top,
                    text=label,
                    fg=fg,
                    bg="#222733",
                    font=("Microsoft YaHei UI", 11, "bold"),
                )
                name.pack(side="left")
                badge = "本机" if game.get("kind") == "local" else (game.get("tag") or "浏览器")
                tag = tk.Label(
                    top,
                    text=badge,
                    fg="#9aa3b5",
                    bg="#2c3344",
                    font=("Microsoft YaHei UI", 8),
                    padx=6,
                    pady=1,
                )
                tag.pack(side="right")
                blurb_text = "点这里接着上一次。" if going else game["blurb"]
                blurb = tk.Label(
                    row,
                    text=blurb_text,
                    fg=muted,
                    bg="#222733",
                    font=("Microsoft YaHei UI", 8),
                    wraplength=320,
                    justify="left",
                )
                blurb.pack(anchor="w", padx=12, pady=(2, 9))

                def go(_e=None, gid=game["id"], link=game.get("url") or "", blurb_lbl=blurb) -> None:
                    launch(gid, str(link), blurb_lbl)

                for w in (row, top, name, tag, blurb):
                    w.bind("<Button-1>", go)

        bar = tk.Frame(host, bg=bg)
        bar.pack(side="bottom", fill="x", pady=(6, 14))
        button(bar, "关闭", dlg.destroy).pack(side="left", padx=(18, 6))
        button(bar, "更多…", lambda: open_browser_game(BROWSER_ARCADE_URL)).pack(side="left")
        reveal(dlg, min_w=360, min_h=420, near=near)
        sync_scroll()

    def show_mines(*, reset: bool = False) -> None:
        conceal()
        clear()
        level = _level(state.get("level_id"))
        state["level_id"] = level["id"]
        slot = mines_slot(level["id"], reset=reset)
        board = slot["board"]
        _SAVE["page"] = "mines"
        side = cell_side(board.cols, board.rows)
        was_hidden = [bool(getattr(dlg, "_key_hidden", False))]
        status = tk.StringVar(value=f"剩余 {board.mines}")
        clock = tk.StringVar(value=_clock_text(mines_elapsed(level["id"])))
        head = tk.Frame(host, bg=bg)
        head.pack(fill="x", padx=16, pady=(14, 6))
        title = tk.Label(head, text="扫雷", fg=fg, bg=bg, font=("Microsoft YaHei UI", 13, "bold"))
        title.pack(side="left")
        drag_on(title)
        tk.Label(head, textvariable=clock, fg=muted, bg=bg, font=("Consolas", 12)).pack(side="right")
        tk.Label(head, textvariable=status, fg=fg, bg=bg, font=("Microsoft YaHei UI", 10)).pack(side="right", padx=(0, 12))

        pick = tk.Frame(host, bg=bg)
        pick.pack(fill="x", padx=16, pady=(0, 8))

        def choose(lv: dict) -> None:
            if lv["id"] == level["id"]:
                return
            pause_mines_clock(level["id"])
            state["level_id"] = lv["id"]
            dlg.after(1, lambda: show_mines(reset=False))

        for lv in LEVELS:
            button(pick, lv["name"], lambda lv=lv: choose(lv), accent=lv["id"] == level["id"]).pack(side="left", padx=(0, 6))

        width = board.cols * side + 8
        height = board.rows * side + 8
        canvas = tk.Canvas(host, width=width, height=height, bg=bg, highlightthickness=0)
        canvas.pack(pady=(0, 8))
        font_px = 11 if side >= 24 else 8

        def paint() -> None:
            left = board.mines - board.flags()
            if board.won:
                status.set("扫完了")
            elif board.dead:
                status.set("踩到了")
            else:
                status.set(f"剩余 {left}")
            canvas.delete("all")
            for r in range(board.rows):
                for c in range(board.cols):
                    x1 = 4 + c * side
                    y1 = 4 + r * side
                    x2, y2 = x1 + side - 2, y1 + side - 2
                    text, fill, color = "", _HIDDEN, fg
                    if board.open[r][c]:
                        if board.mine[r][c]:
                            text, fill, color = "●", _BOOM, "white"
                        else:
                            n = board.around(r, c)
                            text = "" if n == 0 else str(n)
                            fill, color = _OPEN, _NUM.get(n, fg)
                    elif board.dead and board.mine[r][c]:
                        text, fill, color = "●", _HIDDEN, _BOOM
                    elif board.flag[r][c]:
                        text, fill, color = "▲", _HIDDEN, _FLAG
                    canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=fill)
                    if text:
                        canvas.create_text(
                            (x1 + x2) / 2, (y1 + y2) / 2, text=text, fill=color,
                            font=("Consolas", font_px, "bold"),
                        )

        def tick() -> None:
            hidden = bool(getattr(dlg, "_key_hidden", False))
            if hidden or board.dead or board.won:
                pause_mines_clock(level["id"])
            elif board.started:
                resume_mines_clock(level["id"])
            if was_hidden[0] and not hidden:
                paint()
            was_hidden[0] = hidden
            clock.set(_clock_text(mines_elapsed(level["id"])))

        def cell_at(e) -> tuple[int, int] | None:
            c = (e.x - 4) // side
            r = (e.y - 4) // side
            if 0 <= r < board.rows and 0 <= c < board.cols:
                return r, c
            return None

        def on_reveal(e) -> None:
            pos = cell_at(e)
            if pos is None:
                return
            kind = board.reveal(*pos)
            if kind == "noop" or kind == "over":
                return
            if kind in ("boom", "win"):
                pause_mines_clock(level["id"])
            else:
                resume_mines_clock(level["id"])
            paint()

        def on_flag(e) -> None:
            pos = cell_at(e)
            if pos is not None and board.toggle_flag(*pos) == "flag":
                paint()

        canvas.bind("<Button-1>", on_reveal)
        canvas.bind("<Button-3>", on_flag)
        paint()

        bar = tk.Frame(host, bg=bg)
        bar.pack(side="bottom", fill="x", pady=(4, 14))
        button(bar, "再来一局", lambda: dlg.after(1, lambda: show_mines(reset=True)), accent=True).pack(side="left", padx=(16, 6))
        button(bar, "返回", lambda: dlg.after(1, show_list)).pack(side="left", padx=6)
        button(bar, "关闭", dlg.destroy).pack(side="left", padx=6)
        state["tick"] = tick
        reveal(dlg, min_w=max(340, width + 36), min_h=max(280, height + 150), near=near)

    def show_golf(*, reset: bool = False) -> None:
        import golf

        pause_mines_clock()
        conceal()
        clear()
        _SAVE["page"] = "golf"
        golf.mount(
            host, dlg,
            button=button, reveal=reveal, drag_on=drag_on,
            again=lambda: dlg.after(1, lambda: show_golf(reset=True)),
            back=lambda: dlg.after(1, show_list),
            close=dlg.destroy,
            bg=bg, fg=fg, muted=muted, near=near,
            board=golf_board(reset=reset),
        )

    def show_pool(*, reset: bool = False) -> None:
        import pool

        pause_mines_clock()
        conceal()
        clear()
        _SAVE["page"] = "pool"
        pool.mount(
            host, dlg,
            button=button, reveal=reveal, drag_on=drag_on,
            again=lambda: dlg.after(1, lambda: show_pool(reset=True)),
            back=lambda: dlg.after(1, show_list),
            close=dlg.destroy,
            bg=bg, fg=fg, muted=muted, near=near,
            board=pool_board(reset=reset),
            tick=state,
        )

    page = _SAVE.get("page") or "list"
    if page == "mines":
        show_mines(reset=False)
    elif page == "golf":
        show_golf(reset=False)
    elif page == "pool":
        show_pool(reset=False)
    else:
        show_list()

    def on_frame() -> None:
        # 弹窗循环已经在刷倒计时、跟隐藏键时，这里不要再刷一遍
        if live is not None and getattr(win, "blocked_live", None) is not live:
            live()
        tick = state["tick"]
        if tick is not None:
            tick()

    modal(dlg, win, on_frame=on_frame)
