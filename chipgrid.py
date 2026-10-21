# -*- coding: utf-8 -*-
"""可换行的圆角矩形标签网格：统计 / 归档窗口的“缩略模式”共用。

每个标签用 Canvas 手绘圆角矩形 + 文本，按可用宽度从左到右、从上到下排列，
整块区域可纵向滚动；换肤时调用 :meth:`ChipGrid.apply_theme` 重绘。
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont, ttk
from typing import Callable, List, Optional

import dice
import theme
from theme import C

PAD_X = 10
PAD_Y = 4
GAP = 7


def record_items(records, limit=None):
    """把记录转换成缩略标签项：按时间从旧到新，超出上限时保留最近 limit 条。"""
    selected = list(records[-limit:]) if limit else list(records)
    return [
        {
            "text": dice.result_text(rec.notation, rec.rolls, rec.modifier),
            "key": rec.index,
            "danger": not rec.verified,
        }
        for rec in selected
    ]


def _round_rect(canvas: tk.Canvas, x1: float, y1: float, x2: float, y2: float, **kwargs):
    """用多段圆弧画圆角矩形（Canvas 没有原生圆角）。"""
    radius = max(2.0, min(9.0, (y2 - y1) / 2, (x2 - x1) / 2))
    points: List[float] = []
    corners = (
        (x2 - radius, y1 + radius, -90),
        (x2 - radius, y2 - radius, 0),
        (x1 + radius, y2 - radius, 90),
        (x1 + radius, y1 + radius, 180),
    )
    for cx, cy, start in corners:
        for i in range(6):
            angle = math.radians(start + 18 * i)
            points.extend((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))
    return canvas.create_polygon(points, **kwargs)


class ChipGrid(tk.Frame):
    def __init__(
        self,
        master: tk.Misc,
        font: Optional[tkfont.Font] = None,
        on_click: Optional[Callable[[int], None]] = None,
        empty_text: str = "没有记录",
    ) -> None:
        super().__init__(master, bg=C.card)
        self._font = font or tkfont.Font(family="TkDefaultFont", size=9)
        self._on_click = on_click
        self._empty_text = empty_text
        self._items: List[dict] = []
        self._boxes: List[dict] = []
        self._selected = None
        self._hover = None
        self._job = None
        self._width = 0

        theme.configure_scrollbar(ttk.Style(self), "Chip.Vertical.TScrollbar")
        self.canvas = tk.Canvas(self, bg=C.card, highlightthickness=0)
        self.scroll = ttk.Scrollbar(
            self,
            orient="vertical",
            command=self.canvas.yview,
            style="Chip.Vertical.TScrollbar",
        )
        self.canvas.configure(yscrollcommand=self.scroll.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        self.scroll.pack(side="right", fill="y")
        self.canvas.bind("<Configure>", self._on_configure)
        self.canvas.bind("<Button-1>", self._on_click_event)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", lambda e: self._set_hover(None))
        self.canvas.bind("<MouseWheel>", self._on_wheel)

    # ------------------------------------------------------------ 数据

    def set_items(self, items: List[dict], selected=None) -> None:
        """items: [{"text": str, "key": int|None, "danger": bool, "accent": bool}]"""
        self._items = list(items)
        if selected is not None:
            self._selected = selected
        else:
            keys = {item.get("key") for item in self._items}
            if self._selected not in keys:
                self._selected = None
        self._hover = None
        self._schedule()

    def set_selected(self, key) -> None:
        if key == self._selected:
            return
        self._selected = key
        self._restyle_all()

    def apply_theme(self) -> None:
        self.configure(bg=C.card)
        self.canvas.configure(bg=C.card)
        theme.configure_scrollbar(ttk.Style(self), "Chip.Vertical.TScrollbar")
        self._draw()

    # ------------------------------------------------------------ 布局

    def _on_configure(self, event=None) -> None:
        width = event.width if event is not None else self.canvas.winfo_width()
        if abs(width - self._width) < 6:
            return
        self._width = width
        self._schedule()

    def _schedule(self) -> None:
        if self._job is not None:
            try:
                self.after_cancel(self._job)
            except Exception:
                pass
        self._job = self.after(30, self._draw)

    def _fit_text(self, text: str, max_width: float) -> str:
        if self._font.measure(text) <= max_width:
            return text
        low, high = 0, len(text)
        while low < high:
            mid = (low + high + 1) // 2
            if self._font.measure(text[:mid] + "…") <= max_width:
                low = mid
            else:
                high = mid - 1
        return text[:low] + "…"

    def _style_for(self, item: dict):
        key = item.get("key")
        if key is not None and key == self._selected:
            return C.selected, C.selected_fg, C.accent, 2
        if item.get("danger"):
            return C.chip_min_bg, C.danger, "", 0
        if key is not None and key == self._hover:
            return C.hover, C.fg, "", 0
        if item.get("accent"):
            return C.chip_max_bg, C.gold, "", 0
        return C.field, C.fg, "", 0

    def _draw(self) -> None:
        self._job = None
        self.canvas.delete("all")
        self._boxes = []
        width = self.canvas.winfo_width()
        if width < 40:
            return
        if not self._items:
            self.canvas.create_text(
                width / 2,
                46,
                text=self._empty_text,
                fill=C.dim,
                font=self._font,
            )
            self.canvas.configure(scrollregion=(0, 0, width, 90))
            return

        max_width = max(60, width - 2 * GAP)
        x = float(GAP)
        y = float(GAP)
        row_height = 0.0
        for item in self._items:
            text = self._fit_text(str(item.get("text", "")), max_width - 2 * PAD_X)
            chip_w = self._font.measure(text) + 2 * PAD_X
            chip_h = self._font.metrics("linespace") + 2 * PAD_Y
            if x + chip_w > width - GAP and x > GAP:
                x = float(GAP)
                y += row_height + GAP
                row_height = 0.0
            x1, y1 = x, y
            x2, y2 = x + chip_w, y + chip_h
            fill, fg, outline, line_width = self._style_for(item)
            rect = _round_rect(
                self.canvas,
                x1,
                y1,
                x2,
                y2,
                fill=fill,
                outline=outline,
                width=line_width,
            )
            text_id = self.canvas.create_text(
                x1 + PAD_X,
                (y1 + y2) / 2,
                text=text,
                anchor="w",
                fill=fg,
                font=self._font,
            )
            self._boxes.append(
                {
                    "x1": x1,
                    "y1": y1,
                    "x2": x2,
                    "y2": y2,
                    "key": item.get("key"),
                    "item": item,
                    "rect": rect,
                    "text": text_id,
                }
            )
            x = x2 + GAP
            row_height = max(row_height, chip_h)
        self.canvas.configure(scrollregion=(0, 0, width, y + row_height + GAP))

    # ------------------------------------------------------------ 交互

    def _hit(self, x: float, y: float) -> Optional[dict]:
        for box in self._boxes:
            if box["x1"] <= x <= box["x2"] and box["y1"] <= y <= box["y2"]:
                return box
        return None

    def _on_click_event(self, event) -> None:
        if self._on_click is None:
            return
        box = self._hit(event.x, event.y)
        if box is not None and box["key"] is not None:
            self._on_click(box["key"])

    def _on_motion(self, event) -> None:
        box = self._hit(event.x, event.y)
        key = box["key"] if box is not None else None
        self._set_hover(key)

    def _set_hover(self, key) -> None:
        if key == self._hover:
            return
        changed = {k for k in (self._hover, key) if k is not None}
        self._hover = key
        if not changed:
            return
        for box in self._boxes:
            if box["key"] in changed:
                fill, fg, outline, line_width = self._style_for(box["item"])
                self.canvas.itemconfigure(
                    box["rect"], fill=fill, outline=outline, width=line_width
                )
                self.canvas.itemconfigure(box["text"], fill=fg)

    def _restyle_all(self) -> None:
        for box in self._boxes:
            fill, fg, outline, line_width = self._style_for(box["item"])
            self.canvas.itemconfigure(
                box["rect"], fill=fill, outline=outline, width=line_width
            )
            self.canvas.itemconfigure(box["text"], fill=fg)

    def _on_wheel(self, event) -> None:
        step = -3 if event.delta > 0 else 3
        self.canvas.yview_scroll(step, "units")
