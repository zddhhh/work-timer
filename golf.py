"""高尔夫纸牌：只点不拖。七列牌面差 1 就能接，点牌堆翻一张。"""
from __future__ import annotations

import random
import tkinter as tk
from dataclasses import dataclass

SUITS = "♠♥♣♦"
_RED = {1, 3}
_RANKS = ("", "A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K")

_FACE = "#f7f4ee"
_INK = "#1c1f27"
_RED_INK = "#d24b4b"
_BACK = "#3a445c"
_SLOT = "#2a3142"
_PLAY = "#f0c56a"


@dataclass(frozen=True)
class Card:
    suit: int
    rank: int

    @property
    def red(self) -> bool:
        return self.suit in _RED

    @property
    def label(self) -> str:
        return f"{_RANKS[self.rank]}{SUITS[self.suit]}"


class Board:
    """七列各五张正面朝上，牌堆先翻一张做底。A 和 K 不相接。"""

    def __init__(self, seed: int | None = None) -> None:
        self._rng = random.Random(seed)
        self.columns: list[list[Card]] = []
        self.stock: list[Card] = []
        self.waste: list[Card] = []
        self.moved = False
        self.deal()

    def deal(self) -> None:
        deck = [Card(s, r) for s in range(4) for r in range(1, 14)]
        self._rng.shuffle(deck)
        self.columns = [deck[i * 5:(i + 1) * 5] for i in range(7)]
        rest = deck[35:]
        self.waste = [rest[0]]
        self.stock = rest[1:]
        self.moved = False

    def waste_top(self) -> Card | None:
        return self.waste[-1] if self.waste else None

    def can_play(self, col: int) -> bool:
        if not 0 <= col < len(self.columns) or not self.columns[col]:
            return False
        top = self.waste_top()
        if top is None:
            return False
        return abs(self.columns[col][-1].rank - top.rank) == 1

    def play(self, col: int) -> bool:
        if not self.can_play(col):
            return False
        self.waste.append(self.columns[col].pop())
        self.moved = True
        return True

    def draw(self) -> bool:
        if not self.stock:
            return False
        self.waste.append(self.stock.pop())
        self.moved = True
        return True

    @property
    def won(self) -> bool:
        return bool(self.columns) and all(not col for col in self.columns)

    @property
    def stuck(self) -> bool:
        if self.won or self.stock:
            return False
        return not any(self.can_play(i) for i in range(len(self.columns)))


def status_text(board: Board) -> str:
    if board.won:
        return "接完了"
    if board.stuck:
        return "接不上了"
    return "差 1 点就能接"


def mount(host, dlg, *, button, reveal, again, back, drag_on, bg: str, fg: str, muted: str, near, board: Board | None = None) -> None:
    """画在已经清空的 host 上。again / back 由外面安排到下一拍执行。传入 board 则接着玩。"""
    board = board if board is not None else Board()
    head = tk.Frame(host, bg=bg)
    head.pack(fill="x", padx=16, pady=(14, 2))
    title = tk.Label(head, text="高尔夫", fg=fg, bg=bg, font=("Microsoft YaHei UI", 13, "bold"))
    title.pack(side="left")
    drag_on(title)
    status = tk.StringVar(value=status_text(board))
    tk.Label(head, textvariable=status, fg=muted, bg=bg, font=("Microsoft YaHei UI", 10)).pack(side="right")
    hint = tk.Label(host, text="点亮边的牌接上，或点牌堆翻一张。", fg=muted, bg=bg, font=("Microsoft YaHei UI", 9))
    hint.pack(anchor="w", padx=16, pady=(0, 8))
    drag_on(hint)

    canvas = tk.Canvas(host, width=392, height=250, bg=bg, highlightthickness=0)
    canvas.pack(padx=8, pady=(0, 6))
    hits: list[tuple[int, int, int, int, str]] = []

    def redraw() -> None:
        canvas.delete("all")
        hits.clear()
        status.set(status_text(board))
        _draw_pile(canvas, hits, 16, 8, board)
        _draw_columns(canvas, hits, 16, 86, board)

    def on_click(e) -> None:
        if board.won:
            return
        for x1, y1, x2, y2, kind in reversed(hits):
            if x1 <= e.x <= x2 and y1 <= e.y <= y2:
                if kind == "stock":
                    board.draw()
                elif kind.startswith("col-"):
                    board.play(int(kind.split("-", 1)[1]))
                redraw()
                return

    canvas.bind("<Button-1>", on_click)
    redraw()

    bar = tk.Frame(host, bg=bg)
    bar.pack(side="bottom", fill="x", pady=(4, 14))
    button(bar, "再来一局", again, accent=True).pack(side="left", padx=(16, 6))
    button(bar, "返回", back).pack(side="left", padx=6)
    reveal(dlg, min_w=420, min_h=390, near=near)


def _round(canvas: tk.Canvas, x1, y1, x2, y2, fill, outline, width=1):
    return canvas.create_rectangle(x1, y1, x2, y2, fill=fill, outline=outline, width=width)


def _draw_pile(canvas, hits, x, y, board: Board) -> None:
    w, h = 52, 70
    if board.stock:
        _round(canvas, x, y, x + w, y + h, _BACK, "#55607a", 1)
        canvas.create_text(x + w / 2, y + h / 2 - 8, text="翻", fill="#f4f1ea", font=("Microsoft YaHei UI", 11, "bold"))
        canvas.create_text(x + w / 2, y + h / 2 + 14, text=str(len(board.stock)), fill="#c5cedd", font=("Consolas", 11))
        hits.append((x, y, x + w, y + h, "stock"))
    else:
        _round(canvas, x, y, x + w, y + h, "", _SLOT, 1)
        canvas.create_text(x + w / 2, y + h / 2, text="空", fill="#667084", font=("Microsoft YaHei UI", 10))
    top = board.waste_top()
    if top is not None:
        _paint_card(canvas, x + w + 10, y, w, h, top, playable=False)


def _draw_columns(canvas, hits, x, y, board: Board) -> None:
    card_w, card_h, gap, step = 48, 64, 6, 16
    for i, col in enumerate(board.columns):
        cx = x + i * (card_w + gap)
        if not col:
            _round(canvas, cx, y, cx + card_w, y + card_h, "", _SLOT, 1)
            continue
        playable = board.can_play(i)
        for n, card in enumerate(col):
            cy = y + n * step
            last = n == len(col) - 1
            _paint_card(canvas, cx, cy, card_w, card_h, card, playable=playable and last)
        bottom = y + (len(col) - 1) * step
        hits.append((cx, bottom, cx + card_w, bottom + card_h, f"col-{i}"))


def _paint_card(canvas, x, y, w, h, card: Card, *, playable: bool) -> None:
    outline = _PLAY if playable else "#d9d3c7"
    width = 3 if playable else 1
    _round(canvas, x, y, x + w, y + h, _FACE, outline, width)
    ink = _RED_INK if card.red else _INK
    canvas.create_text(x + 8, y + 12, text=_RANKS[card.rank], fill=ink, anchor="w", font=("Consolas", 11, "bold"))
    canvas.create_text(x + w / 2, y + h / 2 + 6, text=SUITS[card.suit], fill=ink, font=("Microsoft YaHei UI", 13))
