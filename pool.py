"""台球：按住白球往后拉，松开就打。彩球全进袋即过关。白球进袋会放回开球点。"""
from __future__ import annotations

import math
import tkinter as tk

R = 8.0
TABLE_W = 400.0
TABLE_H = 210.0
POCKET_R = 16.0
_ROLL = 92.0
_STOP = 8.0
_CUSHION = 0.76
_BALL_E = 0.97
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
_SCALE = 1.58


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
        speed = min(760.0, dist * 6.2)
        self.cue.vx = -dx / dist * speed
        self.cue.vy = -dy / dist * speed
        self.moved = True
        return True

    def guide(self, dx: float, dy: float) -> dict | None:
        """拉杆方向的反向是出杆。返回母球路线、先碰到的球，以及碰完各自往哪边走。"""
        dist = math.hypot(dx, dy)
        if dist < 6 or not self.cue.alive:
            return None
        ux, uy = -dx / dist, -dy / dist
        x, y = self.cue.x, self.cue.y
        path: list[tuple[float, float, float, float]] = []
        ghost = None
        target = None
        obj_dir = None
        cue_dir = None
        remain = 460.0
        for _ in range(2):
            t_ball, ball = self._ray_ball(x, y, ux, uy)
            t_wall, wall = self._ray_wall(x, y, ux, uy)
            t_hit = t_wall if t_ball is None else min(t_wall, t_ball)
            travel = min(remain, t_hit)
            if travel > 0.5:
                path.append((x, y, x + ux * travel, y + uy * travel))
            if travel >= remain - 0.1 or t_hit > remain:
                break
            nx, ny = x + ux * t_hit, y + uy * t_hit
            if t_ball is not None and t_ball <= t_wall + 1e-6:
                ghost = (nx, ny)
                target = ball
                to_obj = math.hypot(ball.x - nx, ball.y - ny) or 1.0
                obj_dir = ((ball.x - nx) / to_obj, (ball.y - ny) / to_obj)
                dot = ux * obj_dir[0] + uy * obj_dir[1]
                tx, ty = ux - obj_dir[0] * dot, uy - obj_dir[1] * dot
                tang = math.hypot(tx, ty)
                cue_dir = (tx / tang, ty / tang) if tang > 0.08 else None
                break
            if wall == "x":
                ux = -ux
            else:
                uy = -uy
            x, y = nx, ny
            remain -= t_hit
            if remain < 12:
                break
        return {"path": path, "ghost": ghost, "ball": target, "object_dir": obj_dir, "cue_dir": cue_dir}

    def _ray_ball(self, x: float, y: float, ux: float, uy: float) -> tuple[float | None, Ball | None]:
        best_t = None
        best = None
        limit = (R * 2) ** 2
        for ball in self.balls:
            if not ball.alive or ball is self.cue:
                continue
            fx, fy = ball.x - x, ball.y - y
            dot = ux * fx + uy * fy
            disc = dot * dot - (fx * fx + fy * fy - limit)
            if disc < 0 or dot <= 0:
                continue
            t = dot - math.sqrt(disc)
            if t < 0.4:
                continue
            if best_t is None or t < best_t:
                best_t, best = t, ball
        return best_t, best

    def _ray_wall(self, x: float, y: float, ux: float, uy: float) -> tuple[float, str]:
        best_t, best = 1e9, "x"
        if ux < 0:
            t = (R - x) / ux
            if 0 < t < best_t:
                best_t, best = t, "x"
        elif ux > 0:
            t = (TABLE_W - R - x) / ux
            if 0 < t < best_t:
                best_t, best = t, "x"
        if uy < 0:
            t = (R - y) / uy
            if 0 < t < best_t:
                best_t, best = t, "y"
        elif uy > 0:
            t = (TABLE_H - R - y) / uy
            if 0 < t < best_t:
                best_t, best = t, "y"
        return best_t, best

    def step(self, dt: float) -> bool:
        if self.won or not self.moving:
            return False
        sub = 6
        h = dt / sub
        for _ in range(sub):
            for b in self.balls:
                if not b.alive:
                    continue
                b.x += b.vx * h
                b.y += b.vy * h
            self._pockets()
            self._walls()
            self._pairs()
            self._pairs()
            for b in self.balls:
                if b.alive:
                    _roll(b, h)
        colors = [b for b in self.balls if b.kind == "color"]
        if colors and all(not b.alive for b in colors):
            self.won = True
            for b in self.balls:
                b.vx = b.vy = 0.0
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
                if b.vx < 0:
                    b.vx = -b.vx * _CUSHION
            elif b.x > right:
                b.x = right
                if b.vx > 0:
                    b.vx = -b.vx * _CUSHION
            if b.y < top:
                b.y = top
                if b.vy < 0:
                    b.vy = -b.vy * _CUSHION
            elif b.y > bot:
                b.y = bot
                if b.vy > 0:
                    b.vy = -b.vy * _CUSHION

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
                j = -(1.0 + _BALL_E) * rel / 2.0
                a.vx -= j * nx
                a.vy -= j * ny
                b.vx += j * nx
                b.vy += j * ny


def _roll(ball: Ball, dt: float) -> None:
    speed = ball.speed
    if speed <= _STOP:
        ball.vx = ball.vy = 0.0
        return
    drop = _ROLL * dt
    if drop >= speed:
        ball.vx = ball.vy = 0.0
        return
    keep = (speed - drop) / speed
    ball.vx *= keep
    ball.vy *= keep


def _mix(color: str, factor: float) -> str:
    h = color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"#{int(r * factor):02x}{int(g * factor):02x}{int(b * factor):02x}"


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

    ox, oy = 44, 34
    tw, th = TABLE_W * _SCALE, TABLE_H * _SCALE
    canvas = tk.Canvas(host, width=int(tw + 88), height=int(th + 68), bg=bg, highlightthickness=0)
    canvas.pack(padx=8, pady=(0, 4))

    def to_table(x: float, y: float) -> tuple[float, float]:
        return (x - ox) / _SCALE, (y - oy) / _SCALE

    def _spot(x: float, y: float) -> tuple[float, float]:
        return ox + x * _SCALE, oy + y * _SCALE

    def redraw() -> None:
        canvas.delete("all")
        status.set(status_text(board))
        rail = 22
        canvas.create_rectangle(ox - rail, oy - rail, ox + tw + rail, oy + th + rail, fill=_WOOD, outline=_WOOD_EDGE, width=2)
        canvas.create_rectangle(ox - rail + 4, oy - rail + 4, ox + tw + rail - 4, oy + th + rail - 4, outline=_WOOD_LINE)
        canvas.create_rectangle(ox, oy, ox + tw, oy + th, fill=_FELT_DEEP, outline=_FELT_DEEP)
        canvas.create_rectangle(ox + 10, oy + 10, ox + tw - 10, oy + th - 10, fill=_FELT, outline=_FELT)
        _cushions(canvas, ox, oy, tw, th)
        for i in (1, 3):
            for yb in (oy - 12, oy + th + 12):
                canvas.create_oval(ox + tw * i / 4 - 2, yb - 2, ox + tw * i / 4 + 2, yb + 2, fill="#e6d2a2", outline="")
            for xb in (ox - 12, ox + tw + 12):
                canvas.create_oval(xb - 2, oy + th * i / 4 - 2, xb + 2, oy + th * i / 4 + 2, fill="#e6d2a2", outline="")
        for px, py in _POCKETS:
            cx, cy = _spot(px, py)
            canvas.create_oval(cx - 15, cy - 15, cx + 15, cy + 15, fill="#24160f", outline="#c4a574", width=2)
            canvas.create_oval(cx - 10, cy - 10, cx + 10, cy + 10, fill="#05060a", outline="")
        if board.aiming and not board.moving and not board.won and board.cue.alive:
            _draw_aim(canvas, _spot, to_table, board)
        for b in board.balls:
            if b.alive:
                _draw_ball(canvas, *_spot(b.x, b.y), R * _SCALE, b.color, cue=b.kind == "cue")

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
    reveal(dlg, min_w=900, min_h=540, near=near)


def _cushions(canvas: tk.Canvas, ox: float, oy: float, tw: float, th: float) -> None:
    mouth, nose = 20.0, 9.0
    rubber, lip = "#145c36", "#1e7a48"
    mid = ox + tw / 2
    spans = (
        (ox + mouth, oy, mid - mouth, oy, mid - mouth - nose, oy + 11, ox + mouth + nose, oy + 11),
        (mid + mouth, oy, ox + tw - mouth, oy, ox + tw - mouth - nose, oy + 11, mid + mouth + nose, oy + 11),
        (ox + mouth, oy + th, mid - mouth, oy + th, mid - mouth - nose, oy + th - 11, ox + mouth + nose, oy + th - 11),
        (mid + mouth, oy + th, ox + tw - mouth, oy + th, ox + tw - mouth - nose, oy + th - 11, mid + mouth + nose, oy + th - 11),
    )
    for pts in spans:
        canvas.create_polygon(*pts, fill=rubber, outline=lip)
    sides = (
        (ox, oy + mouth, ox, mid_y(oy, th) - mouth, ox + 11, mid_y(oy, th) - mouth - nose, ox + 11, oy + mouth + nose),
        (ox, mid_y(oy, th) + mouth, ox, oy + th - mouth, ox + 11, oy + th - mouth - nose, ox + 11, mid_y(oy, th) + mouth + nose),
        (ox + tw, oy + mouth, ox + tw, mid_y(oy, th) - mouth, ox + tw - 11, mid_y(oy, th) - mouth - nose, ox + tw - 11, oy + mouth + nose),
        (ox + tw, mid_y(oy, th) + mouth, ox + tw, oy + th - mouth, ox + tw - 11, oy + th - mouth - nose, ox + tw - 11, mid_y(oy, th) + mouth + nose),
    )
    for pts in sides:
        canvas.create_polygon(*pts, fill=rubber, outline=lip)


def mid_y(oy: float, th: float) -> float:
    return oy + th / 2


def _draw_aim(canvas, spot, to_table, board: Board) -> None:
    ax, ay = board.aim
    cx, cy = spot(board.cue.x, board.cue.y)
    tx, ty = to_table(ax, ay)
    dx, dy = tx - board.cue.x, ty - board.cue.y
    dist = math.hypot(dx, dy)
    if dist < 4:
        return
    ux, uy = dx / dist, dy / dist
    rr = R * _SCALE
    gap = rr + 3
    reach = min(dist, 128)
    canvas.create_line(
        cx + ux * gap, cy + uy * gap,
        cx + ux * (gap + reach), cy + uy * (gap + reach),
        fill="#ecd9b0", width=4, capstyle="round",
    )
    canvas.create_line(
        cx + ux * (gap + reach - 16), cy + uy * (gap + reach - 16),
        cx + ux * (gap + reach), cy + uy * (gap + reach),
        fill="#3a6ea5", width=5, capstyle="round",
    )
    info = board.guide(dx, dy)
    if not info:
        return
    for x0, y0, x1, y1 in info["path"]:
        a, b = spot(x0, y0), spot(x1, y1)
        canvas.create_line(*a, *b, fill="#e7fff1", width=1, dash=(4, 3))
    ghost = info["ghost"]
    if ghost is None:
        return
    gx, gy = spot(*ghost)
    canvas.create_oval(gx - rr, gy - rr, gx + rr, gy + rr, outline="#f4f1ea", width=1)
    if info["object_dir"] and info["ball"] is not None:
        ox, oy = spot(info["ball"].x, info["ball"].y)
        vx, vy = info["object_dir"]
        canvas.create_line(ox, oy, ox + vx * 54, oy + vy * 54, fill=info["ball"].color, width=2, capstyle="round")
    if info["cue_dir"]:
        vx, vy = info["cue_dir"]
        canvas.create_line(gx, gy, gx + vx * 42, gy + vy * 42, fill="#f4f1ea", width=1, dash=(2, 3))


def _draw_ball(canvas: tk.Canvas, x: float, y: float, r: float, color: str, *, cue: bool) -> None:
    canvas.create_oval(x - r + 1, y - r + 3, x + r + 1, y + r + 3, fill="#07140e", outline="")
    shade = "#d5d0c6" if cue else _mix(color, 0.62)
    canvas.create_oval(x - r, y - r, x + r, y + r, fill=shade, outline="#10281c")
    canvas.create_oval(x - r * 0.86, y - r * 0.9, x + r * 0.62, y + r * 0.55, fill=color, outline="")
    canvas.create_oval(x - r * 0.42, y - r * 0.58, x - r * 0.08, y - r * 0.22, fill="#ffffff", outline="")
