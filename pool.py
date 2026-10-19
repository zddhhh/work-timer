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
_FELT = "#127848"
_FELT_DEEP = "#0c5e38"
_WOOD = "#6a3b1f"
_WOOD_EDGE = "#3e2414"
_WOOD_LINE = "#8d5a34"
_CUE = "#f4f1ea"
_HINT = "按住白球往后拉，松开就打。"
_SCALE = 1.42


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

    ox, oy = 36, 28
    tw, th = TABLE_W * _SCALE, TABLE_H * _SCALE
    canvas = tk.Canvas(host, width=int(tw + 72), height=int(th + 56), bg=bg, highlightthickness=0)
    canvas.pack(padx=8, pady=(0, 4))

    def to_table(x: float, y: float) -> tuple[float, float]:
        return (x - ox) / _SCALE, (y - oy) / _SCALE

    def _spot(x: float, y: float) -> tuple[float, float]:
        return ox + x * _SCALE, oy + y * _SCALE

    def redraw() -> None:
        canvas.delete("all")
        status.set(status_text(board))
        rail = 18
        canvas.create_rectangle(ox - rail, oy - rail, ox + tw + rail, oy + th + rail, fill=_WOOD, outline=_WOOD_EDGE, width=2)
        canvas.create_rectangle(ox - rail + 3, oy - rail + 3, ox + tw + rail - 3, oy + th + rail - 3, outline=_WOOD_LINE)
        canvas.create_rectangle(ox, oy, ox + tw, oy + th, fill=_FELT, outline=_FELT)
        cushion = 8
        canvas.create_rectangle(ox + cushion, oy + cushion, ox + tw - cushion, oy + th - cushion, outline=_FELT_DEEP, width=3)
        for px, py in _POCKETS:
            cx, cy = _spot(px, py)
            canvas.create_oval(cx - 13, cy - 13, cx + 13, cy + 13, fill="#1a120e", outline=_WOOD_LINE, width=2)
            canvas.create_oval(cx - 8, cy - 8, cx + 8, cy + 8, fill="#07080c", outline="")
        for i in (1, 3):
            for yb in (oy - 10, oy + th + 10):
                canvas.create_oval(ox + tw * i / 4 - 2, yb - 2, ox + tw * i / 4 + 2, yb + 2, fill="#e6d2a2", outline="")
            for xb in (ox - 10, ox + tw + 10):
                canvas.create_oval(xb - 2, oy + th * i / 4 - 2, xb + 2, oy + th * i / 4 + 2, fill="#e6d2a2", outline="")
        if board.aiming and not board.moving and not board.won and board.cue.alive:
            ax, ay = board.aim
            cx, cy = _spot(board.cue.x, board.cue.y)
            dx, dy = ax - cx, ay - cy
            dist = math.hypot(dx, dy)
            if dist > 4:
                ux, uy = dx / dist, dy / dist
                rr = R * _SCALE
                gap = rr + 3
                reach = min(dist, 120)
                canvas.create_line(
                    cx + ux * gap, cy + uy * gap,
                    cx + ux * (gap + reach), cy + uy * (gap + reach),
                    fill="#ecd9b0", width=4, capstyle="round",
                )
                canvas.create_line(
                    cx + ux * (gap + reach - 14), cy + uy * (gap + reach - 14),
                    cx + ux * (gap + reach), cy + uy * (gap + reach),
                    fill="#2c2418", width=5, capstyle="round",
                )
                aim = min(210.0, dist * 1.35)
                canvas.create_line(
                    cx - ux * rr, cy - uy * rr,
                    cx - ux * (rr + aim), cy - uy * (rr + aim),
                    fill="#d7f3e2", width=1, dash=(4, 3),
                )
        rr = R * _SCALE
        for b in board.balls:
            if not b.alive:
                continue
            x, y = _spot(b.x, b.y)
            canvas.create_oval(x - rr, y - rr, x + rr, y + rr, fill=b.color, outline="#10281c")
            canvas.create_oval(x - rr * 0.45, y - rr * 0.55, x - rr * 0.05, y - rr * 0.15, fill="#ffffff", outline="")

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
    reveal(dlg, min_w=680, min_h=470, near=near)
