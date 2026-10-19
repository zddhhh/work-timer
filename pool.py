"""台球：按住白球往后拉，松开就打。彩球全进袋即过关。白球进袋会放回开球点。"""
from __future__ import annotations

import math
import tkinter as tk

R = 8.0
TABLE_W = 400.0
TABLE_H = 210.0
POCKET_R = 16.0
_POCKETS = (
    (R, R),
    (TABLE_W / 2, R),
    (TABLE_W - R, R),
    (R, TABLE_H - R),
    (TABLE_W / 2, TABLE_H - R),
    (TABLE_W - R, TABLE_H - R),
)
_COLORS = ("#f0c14a", "#5aa7e8", "#e25b5b", "#b48cff", "#f08a3c", "#5ecf8a")
_FELT = "#0f6a45"
_RAIL = "#163528"
_CUE = "#f4f1ea"
_HINT = "按住白球往后拉，松开就打。"


class Ball:
    def __init__(self, x: float, y: float, color: str, kind: str) -> None:
        self.x = float(x)
        self.y = float(y)
        self.vx = 0.0
        self.vy = 0.0
        self.color = color
        self.kind = kind
        self.alive = True

    @property
    def speed(self) -> float:
        return math.hypot(self.vx, self.vy)


class Board:
    def __init__(self) -> None:
        self.balls: list[Ball] = []
        self.cue = Ball(90, TABLE_H / 2, _CUE, "cue")
        self.moved = False
        self.won = False
        self.aiming = False
        self.aim = (0.0, 0.0)
        self.rack()

    def rack(self) -> None:
        self.won = False
        self.moved = False
        self.aiming = False
        self.cue = Ball(90, TABLE_H / 2, _CUE, "cue")
        colors = []
        origin_x, origin_y = 270.0, TABLE_H / 2
        gap = R * 2 + 1.2
        n = 0
        for row in range(3):
            for col in range(row + 1):
                if n >= len(_COLORS):
                    break
                x = origin_x + row * gap * 0.86
                y = origin_y + (col - row / 2) * gap
                colors.append(Ball(x, y, _COLORS[n], "color"))
                n += 1
        self.balls = [self.cue, *colors]

    @property
    def moving(self) -> bool:
        return any(b.alive and b.speed > 6 for b in self.balls)

    @property
    def pocketed(self) -> int:
        return sum(1 for b in self.balls if b.kind == "color" and not b.alive)

    def shoot(self, dx: float, dy: float) -> bool:
        if self.moving or self.won:
            return False
        dist = math.hypot(dx, dy)
        if dist < 6:
            return False
        speed = min(680.0, dist * 5.5)
        self.cue.vx = -dx / dist * speed
        self.cue.vy = -dy / dist * speed
        self.moved = True
        return True

    def step(self, dt: float) -> bool:
        if self.won or not self.moving:
            return False
        sub = 4
        h = dt / sub
        for _ in range(sub):
            for b in self.balls:
                if not b.alive:
                    continue
                b.x += b.vx * h
                b.y += b.vy * h
                damp = math.exp(-1.5 * h)
                b.vx *= damp
                b.vy *= damp
                if b.speed < 12:
                    b.vx = b.vy = 0.0
            self._pockets()
            self._walls()
            self._pairs()
        colors = [b for b in self.balls if b.kind == "color"]
        if colors and all(not b.alive for b in colors):
            self.won = True
            self.cue.vx = self.cue.vy = 0.0
        return self.moving

    def _pockets(self) -> None:
        for b in self.balls:
            if not b.alive:
                continue
            if not any(math.hypot(b.x - px, b.y - py) <= POCKET_R for px, py in _POCKETS):
                continue
            b.alive = False
            b.vx = b.vy = 0.0
            if b.kind == "cue" and not self.won:
                self._respawn_cue()

    def _respawn_cue(self) -> None:
        self.cue.alive = True
        self.cue.vx = self.cue.vy = 0.0
        self.cue.x, self.cue.y = 90.0, TABLE_H / 2
        for _ in range(10):
            blocked = False
            for other in self.balls:
                if other is self.cue or not other.alive:
                    continue
                if math.hypot(other.x - self.cue.x, other.y - self.cue.y) < R * 2:
                    blocked = True
                    break
            if not blocked:
                return
            self.cue.x += R * 2

    def _walls(self) -> None:
        left, right = R, TABLE_W - R
        top, bot = R, TABLE_H - R
        for b in self.balls:
            if not b.alive:
                continue
            if b.x < left:
                b.x = left
                b.vx = abs(b.vx)
            elif b.x > right:
                b.x = right
                b.vx = -abs(b.vx)
            if b.y < top:
                b.y = top
                b.vy = abs(b.vy)
            elif b.y > bot:
                b.y = bot
                b.vy = -abs(b.vy)

    def _pairs(self) -> None:
        alive = [b for b in self.balls if b.alive]
        for i, a in enumerate(alive):
            for b in alive[i + 1:]:
                dx, dy = b.x - a.x, b.y - a.y
                dist = math.hypot(dx, dy)
                if dist >= R * 2:
                    continue
                if dist < 1e-6:
                    dx, dy, dist = 1.0, 0.0, 1.0
                nx, ny = dx / dist, dy / dist
                overlap = R * 2 - dist
                a.x -= nx * overlap / 2
                a.y -= ny * overlap / 2
                b.x += nx * overlap / 2
                b.y += ny * overlap / 2
                rel = (b.vx - a.vx) * nx + (b.vy - a.vy) * ny
                if rel >= 0:
                    continue
                a.vx += rel * nx
                a.vy += rel * ny
                b.vx -= rel * nx
                b.vy -= rel * ny


def status_text(board: Board) -> str:
    if board.won:
        return "清台了"
    return f"进袋 {board.pocketed}/6"


def mount(host, dlg, *, button, reveal, again, back, close, drag_on, bg, fg, muted, near, board: Board | None = None, tick: dict | None = None) -> None:
    board = board if board is not None else Board()
    head = tk.Frame(host, bg=bg)
    head.pack(fill="x", padx=16, pady=(14, 2))
    title = tk.Label(head, text="台球", fg=fg, bg=bg, font=("Microsoft YaHei UI", 13, "bold"))
    title.pack(side="left")
    drag_on(title)
    status = tk.StringVar(value=status_text(board))
    tk.Label(head, textvariable=status, fg=muted, bg=bg, font=("Microsoft YaHei UI", 10)).pack(side="right")
    hint = tk.Label(host, text=_HINT, fg=muted, bg=bg, font=("Microsoft YaHei UI", 9))
    hint.pack(anchor="w", padx=16, pady=(0, 6))
    drag_on(hint)

    ox, oy = 20, 8
    canvas = tk.Canvas(host, width=int(TABLE_W + 40), height=int(TABLE_H + 24), bg=bg, highlightthickness=0)
    canvas.pack(padx=8, pady=(0, 6))

    def to_table(x: float, y: float) -> tuple[float, float]:
        return x - ox, y - oy

    def redraw() -> None:
        canvas.delete("all")
        status.set(status_text(board))
        canvas.create_rectangle(ox - 10, oy - 8, ox + TABLE_W + 10, oy + TABLE_H + 8, fill=_RAIL, outline=_RAIL)
        canvas.create_rectangle(ox, oy, ox + TABLE_W, oy + TABLE_H, fill=_FELT, outline=_FELT)
        for px, py in _POCKETS:
            canvas.create_oval(ox + px - 9, oy + py - 9, ox + px + 9, oy + py + 9, fill="#0c0e12", outline="#0c0e12")
        if board.aiming and not board.moving and not board.won:
            ax, ay = board.aim
            cx, cy = ox + board.cue.x, oy + board.cue.y
            canvas.create_line(cx, cy, ax, ay, fill="#d7e0c8", width=2)
        for b in board.balls:
            if not b.alive:
                continue
            x, y = ox + b.x, oy + b.y
            canvas.create_oval(x - R, y - R, x + R, y + R, fill=b.color, outline="#10281c")

    def on_press(e) -> None:
        if board.moving or board.won or not board.cue.alive:
            return
        tx, ty = to_table(e.x, e.y)
        if math.hypot(tx - board.cue.x, ty - board.cue.y) > 26:
            return
        board.aiming = True
        board.aim = (e.x, e.y)
        redraw()

    def on_move(e) -> None:
        if not board.aiming:
            return
        board.aim = (e.x, e.y)
        redraw()

    def on_release(e) -> None:
        if not board.aiming:
            return
        board.aiming = False
        tx, ty = to_table(e.x, e.y)
        board.shoot(tx - board.cue.x, ty - board.cue.y)
        redraw()

    def on_tick() -> None:
        was = board.moving or board.aiming
        board.step(0.02)
        if was or board.moving or board.aiming:
            redraw()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_move)
    canvas.bind("<ButtonRelease-1>", on_release)
    redraw()
    if tick is not None:
        tick["tick"] = on_tick

    bar = tk.Frame(host, bg=bg)
    bar.pack(side="bottom", fill="x", pady=(4, 14))
    button(bar, "再来一局", again, accent=True).pack(side="left", padx=(16, 6))
    button(bar, "返回", back).pack(side="left", padx=6)
    button(bar, "关闭", close).pack(side="left", padx=6)
    reveal(dlg, min_w=460, min_h=360, near=near)
