# -*- coding: utf-8 -*-
"""AliDice 图形界面（Tkinter）。

布局：左侧"本次结果 + 输入"，右侧"历史记录（只读）"，底部状态栏。
历史写入只经 :meth:`history.HistoryStore.append`，界面上没有任何
修改/删除历史记录的入口。
"""

from __future__ import annotations

import json
import os
import random
import sys
import time
import tkinter as tk
from tkinter import font as tkfont, messagebox, simpledialog, ttk
from typing import List, Optional, Tuple

import dice
import history as hist
import theme
from theme import (
    ACCENT,
    ACCENT_HOVER,
    BG,
    BLUE,
    BORDER,
    CARD,
    CARD_ALT,
    DANGER,
    DANGER_BG,
    DIM,
    FG,
    FIELD,
    GOLD,
    MUTED,
    OK_BG,
    WARN_BG,
)

CONFIG_PATH = os.path.join(hist.project_dir(), "config.json")
DEFAULT_PRESETS = ("1D100", "1D10")
DISPLAY_LIMIT = 400

ICON_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAIAAAACACAYAAADDPmHLAAADeUlEQVR42u3cPVLcQBCGYUm1BVW+hLmHiYkJHHMMDsExiB0QE+N74EtQBQmOSOzVz2hGo9HM84VLoZ3t7+2eltQ1XUdEREREzanP/YV3r0+fwj6tx6vbvhoAGF42ED3j2wahZ3zbIPSMbxuEfg/zn6/vuTeim5eHrBD0Ocxn+LZAxEDQM75tEPotzGf8fiCEQjAw/1iai29oP3bKtTBKD0Fowxi9BYzRFWP+xeW35g39eH9LviUs3Qr6PcxneloYYiDoc5rP+O1AWAvBKcePYfz6mMVsD0nuAmKzn/l5kmfMj7m7gqHbsONnfhkQrAYg5gUP88vZRqd8HLbIfubvB0FoFRhSZz/zy6wEY34OKbOf+WVAEFIFBuFsW4N7/faawlkAjHfVqXO+Din2f9lfXhVY2gfoAfQABADNX7PNoAqgAhAACADUpk5HW/CfXz/+++z7z9/WUzsA5wL9799yBr609VQLwFSg9wh8aeupugcICXaK/zvaejSBVC8AsVmTOutKW48KQPUCkCpbar2OCkAAIAAQAKhKAFI9Oav1OioA1Q9AbLakzrbS1qMCUP0ArM2arbKttPV0LbwO/grekqdoOQJd2nqaGQiZCvyaQMdeJ/V6AJCpnKae5DmS2VUAYJLHXYBJHgAQABqf5AEAAaDlSR4AEAAIAAQAAkDX3iQPAAgALU/yAIAA0PIkT+d1cNuTPM4IKmSSx0TQQc/kKW2yCADOCNIEOiMIAAQAZwQBgJwR5DoqAAGAAEAAIGcEuY4KQM4IckaQCkDOCHJGUOeMIGcEOSNo30A7I+jgt4i1rkcTSAAgABAAKAsAH+9vorijYuOvAqgABIAFunl5sA0cqPxP+TULwOPVbS+89emcr0MpzQjtE289gB5gueb2FVWgjOxfuv9PArC2DwBBmaV/zM/gLWAJXSDYz/yQ7J8FIOZuAATlNH1TPq5qApdSBoK85odm/yIAxugBwTHMn6vip5w/4uLyG0cL20IX7/F3r0+f5z5/vr4P/lIgpDV+bfYHAZAaAjCkyfYY84MB2AoC2sf8pD3A12KAsJ/xXY53AXN0pVwchcc39NnN6gc9Y1uBbWG/rF/z4C76vT8Qjml8MgCWQgCIbfb32OGdZJM/oRBQt8mEz24AAOFYxm8GABCOYfzmAAChbOOzAQCIsgwnIiIi6rqu+wsaAvAjp953/wAAAABJRU5ErkJggg=="
)


# ---------------------------------------------------------------- 配置


def load_presets() -> List[str]:
    presets: List[str] = []
    try:
        with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
            raw = json.load(fh)
        for item in raw.get("presets", []):
            if not isinstance(item, str):
                continue
            try:
                presets.append(dice.parse(item).text)
            except dice.DiceError:
                continue
    except (OSError, ValueError, AttributeError):
        pass
    if not presets:
        presets = list(DEFAULT_PRESETS)
    # 去重保序
    seen = set()
    return [p for p in presets if not (p in seen or seen.add(p))]


def save_presets(presets: List[str]) -> None:
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
            json.dump({"presets": presets}, fh, ensure_ascii=False, indent=2)
    except OSError:
        pass


# ---------------------------------------------------------------- 主窗口


class DiceApp(tk.Tk):
    def __init__(self, store: hist.HistoryStore) -> None:
        super().__init__()
        self.store = store
        self.presets = load_presets()
        self._last: Optional[Tuple[dice.RollResult, hist.Record]] = None
        self._by_iid = {}
        self._animating = False
        self._chip_items: List[Tuple[str, str, str]] = []
        self._chips_width = -1
        self._toast_job = None
        self._detail_record: Optional[hist.Record] = None
        self._stats_win = None

        self.title("AliDice · 骰子")
        self.configure(bg=BG)
        try:
            self._icon_image = tk.PhotoImage(data=ICON_B64)
            self.iconphoto(True, self._icon_image)
        except tk.TclError:
            self._icon_image = None
        self._setup_fonts()
        self._setup_style()
        self._build_ui()
        self._render_presets()
        self._refresh_history()
        self._update_badge()
        self._update_footer()
        if not self.store.report.can_append:
            self.hint_label.configure(
                text="历史校验未通过，掷骰已锁定 · 可点底部「归档并重置」", fg=DANGER
            )

        self.minsize(920, 620)
        self.update_idletasks()
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = max(920, min(1160, screen_w - 80))
        height = max(620, min(740, screen_h - 130))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.geometry(f"{width}x{height}+{x}+{y}")

        self.bind("<Control-t>", lambda e: self._open_stats())

        if not self.store.report.can_append:
            self.after(400, self._show_integrity_notice)

    # ------------------------------------------------------------ 外观

    def _setup_fonts(self) -> None:
        ui = theme.pick_family(self, theme.UI_FONTS)
        mono = theme.pick_family(self, theme.MONO_FONTS)
        self.f_brand = (ui, 20, "bold")
        self.f_huge = (ui, 40, "bold")
        self.f_h = (ui, 12, "bold")
        self.f_ui = (ui, 11)
        self.f_small = (ui, 10)
        self.f_tiny = (ui, 9)
        self.f_btn = (ui, 11, "bold")
        self.f_mono = (mono, 11)
        self.f_mono_small = (mono, 10)
        self.f_chip = tkfont.Font(family=mono, size=10)

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.layout(
            "Ali.Treeview",
            [("Treeview.treearea", {"sticky": "nswe"})],
        )
        style.configure(
            "Ali.Treeview",
            background=CARD,
            fieldbackground=CARD,
            foreground=FG,
            borderwidth=0,
            rowheight=28,
            font=self.f_small,
        )
        style.configure(
            "Ali.Treeview.Heading",
            background=CARD_ALT,
            foreground=MUTED,
            borderwidth=0,
            relief="flat",
            font=self.f_tiny,
        )
        style.map(
            "Ali.Treeview",
            background=[("selected", "#2c3a55")],
            foreground=[("selected", "#ffffff")],
        )
        style.map("Ali.Treeview.Heading", background=[("active", CARD_ALT)])
        style.configure(
            "Ali.Vertical.TScrollbar",
            background=CARD_ALT,
            troughcolor=BG,
            bordercolor=BG,
            arrowcolor=MUTED,
            relief="flat",
            width=10,
        )
        style.map("Ali.Vertical.TScrollbar", background=[("active", BORDER)])

    def _button(self, parent, text, command, kind="ghost", font=None, padx=14, pady=7):
        spec = {
            "accent": (ACCENT, "#05160f", ACCENT_HOVER),
            "ghost": (CARD_ALT, FG, "#2b3446"),
            "chip": (FIELD, BLUE, "#2b3446"),
            "danger": (DANGER_BG, DANGER, "#4b262e"),
        }[kind]
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=spec[0],
            fg=spec[1],
            activebackground=spec[2],
            activeforeground=spec[1],
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            font=font or self.f_btn,
            padx=padx,
            pady=pady,
        )
        btn.bind("<Enter>", lambda e: btn.configure(bg=spec[2]) if str(btn["state"]) == "normal" else None)
        btn.bind("<Leave>", lambda e: btn.configure(bg=spec[0]) if str(btn["state"]) == "normal" else None)
        return btn

    def _card(self, master) -> tk.Frame:
        return tk.Frame(
            master,
            bg=CARD,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
        )

    # ------------------------------------------------------------ 布局

    def _build_ui(self) -> None:
        root = tk.Frame(self, bg=BG)
        root.pack(fill="both", expand=True, padx=22, pady=(16, 12))

        header = tk.Frame(root, bg=BG)
        header.pack(fill="x")
        tk.Label(header, text="AliDice", bg=BG, fg=FG, font=self.f_brand).pack(side="left")
        tk.Label(
            header,
            text="掷骰 ·  历史只追加、不可修改",
            bg=BG,
            fg=DIM,
            font=self.f_small,
        ).pack(side="left", padx=(12, 0), pady=(6, 0))
        self.badge = tk.Label(
            header, text="", bg=OK_BG, fg=ACCENT, font=self.f_tiny, padx=12, pady=6
        )
        self.badge.pack(side="right")

        # 先占住底部工具栏，窗口变矮时优先压缩内容区而不是裁掉按钮
        self._build_footer(root)

        body = tk.Frame(root, bg=BG)
        body.pack(fill="both", expand=True, pady=(14, 0))
        body.columnconfigure(0, weight=5, uniform="col")
        body.columnconfigure(1, weight=6, uniform="col")
        body.rowconfigure(0, weight=1)

        left = self._card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 9))
        right = self._card(body)
        right.grid(row=0, column=1, sticky="nsew", padx=(9, 0))
        self._build_roll_card(left)
        self._build_history_card(right)

        self._toast_label = tk.Label(
            self, text="", bg=CARD_ALT, fg=FG, font=self.f_small, padx=14, pady=8
        )

    def _build_roll_card(self, card: tk.Frame) -> None:
        self._hint_wrap = 0
        card.bind("<Configure>", self._on_roll_card_configure)
        head = tk.Frame(card, bg=CARD)
        head.pack(fill="x", padx=20, pady=(16, 0))
        tk.Label(head, text="本次结果", bg=CARD, fg=MUTED, font=self.f_small).pack(side="left")
        self.expr_label = tk.Label(head, text="—", bg=CARD, fg=BLUE, font=self.f_mono_small)
        self.expr_label.pack(side="right")

        # 输入区优先占位，窗口变矮时先压缩结果区而不是裁掉输入框
        bottom = tk.Frame(card, bg=CARD)
        bottom.pack(side="bottom", fill="x", padx=20, pady=(0, 18))

        self.total_label = tk.Label(card, text="?", bg=CARD, fg=DIM, font=self.f_huge)
        self._result_spacer_top = tk.Frame(card, bg=CARD)
        self._result_spacer_top.pack(fill="both", expand=True)
        self.total_label.pack(fill="x", padx=16, pady=(6, 0))

        self.hint_label = tk.Label(
            card,
            text="输入 xDx（如 3D6），按 Enter 掷骰",
            bg=CARD,
            fg=DIM,
            font=self.f_small,
            wraplength=430,
            justify="center",
        )
        self.hint_label.pack(fill="x", padx=20)

        self.chips = tk.Frame(card, bg=CARD, height=88)
        self._result_spacer_bottom = tk.Frame(card, bg=CARD)
        self.chips.pack(fill="x", padx=16, pady=(8, 4))
        self.chips.pack_propagate(False)
        self.chips.bind("<Configure>", self._on_chips_configure)
        self._result_spacer_bottom.pack(fill="both", expand=True)

        self.preset_bar = tk.Frame(bottom, bg=CARD)
        self.preset_bar.pack(fill="x")

        row = tk.Frame(bottom, bg=CARD)
        row.pack(fill="x", pady=(10, 0))
        self.roll_btn = self._button(row, "掷 骰", self.do_roll, kind="accent", pady=10, padx=22)
        self.roll_btn.pack(side="right", padx=(10, 0))

        entry_wrap = tk.Frame(
            row,
            bg=FIELD,
            highlightthickness=1,
            highlightbackground=BORDER,
            highlightcolor=ACCENT,
        )
        entry_wrap.pack(side="left", fill="x", expand=True)
        self.var_expr = tk.StringVar(value="1D100")
        self.entry = tk.Entry(
            entry_wrap,
            textvariable=self.var_expr,
            bg=FIELD,
            fg=FG,
            insertbackground=ACCENT,
            relief="flat",
            bd=0,
            font=self.f_mono,
        )
        self.entry.pack(fill="x", padx=14, pady=11)
        self.entry.bind("<Return>", lambda e: self.do_roll())
        self.entry.bind("<FocusIn>", lambda e: entry_wrap.configure(highlightbackground=ACCENT))
        self.entry.bind("<FocusOut>", lambda e: entry_wrap.configure(highlightbackground=BORDER))
        self.entry.focus_set()
        self.entry.select_range(0, "end")

    def _build_history_card(self, card: tk.Frame) -> None:
        self._detail_wrap = 0
        card.bind("<Configure>", self._on_history_card_configure)
        head = tk.Frame(card, bg=CARD)
        head.pack(fill="x", padx=18, pady=(16, 8))
        tk.Label(head, text="历史记录", bg=CARD, fg=FG, font=self.f_h).pack(side="left")
        tk.Label(head, text="只读 · 不可修改", bg=CARD, fg=DIM, font=self.f_tiny).pack(
            side="left", padx=(10, 0), pady=(2, 0)
        )
        self.count_label = tk.Label(head, text="", bg=CARD, fg=MUTED, font=self.f_tiny)
        self.count_label.pack(side="right")

        wrap = tk.Frame(card, bg=CARD)
        wrap.pack(fill="both", expand=True, padx=16)
        columns = ("idx", "time", "expr", "rolls", "total")
        headings = {
            "idx": "#",
            "time": "时间",
            "expr": "表达式",
            "rolls": "点数",
            "total": "合计",
        }
        measure = tkfont.Font(font=self.f_small).measure
        widths = {
            "idx": measure("#888") + 10,
            "time": measure("88:88:88") + 16,
            "expr": measure("88D888+88D8") + 14,
            "rolls": 120,
            "total": measure("8888") + 12,
        }
        self._col_widths = {k: widths[k] for k in ("idx", "time", "expr", "total")}
        anchors = {"idx": "w", "time": "w", "expr": "w", "rolls": "w", "total": "e"}
        self.tree = ttk.Treeview(
            wrap, columns=columns, show="headings", style="Ali.Treeview", selectmode="browse"
        )
        for col in columns:
            self.tree.heading(col, text=headings[col], anchor=anchors[col])
            self.tree.column(
                col,
                width=widths[col],
                minwidth=20,
                anchor=anchors[col],
                stretch=(col == "rolls"),
            )
        scroll = ttk.Scrollbar(
            wrap, orient="vertical", command=self.tree.yview, style="Ali.Vertical.TScrollbar"
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._tree_width = 0
        self.tree.bind("<Configure>", self._fit_tree_columns)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self.empty_label = tk.Label(
            wrap,
            text="还没有记录\n掷骰后会自动写入不可修改的历史",
            bg=CARD,
            fg=DIM,
            font=self.f_small,
            justify="center",
        )
        self.tree.tag_configure("odd", background=CARD)
        self.tree.tag_configure("even", background="#1c212c")
        self.tree.tag_configure("bad", foreground=DANGER)

        detail = tk.Frame(card, bg=CARD_ALT, highlightthickness=1, highlightbackground=BORDER)
        detail.pack(fill="x", padx=16, pady=(10, 16))
        self.detail_label = tk.Label(
            detail,
            text="选中一条记录可查看投掷明细与校验信息",
            bg=CARD_ALT,
            fg=MUTED,
            font=self.f_tiny,
            justify="left",
            anchor="w",
            wraplength=460,
            padx=12,
            pady=9,
        )
        self.detail_label.pack(fill="x")

    def _build_footer(self, root: tk.Frame) -> None:
        bar = tk.Frame(root, bg=BG)
        bar.pack(side="bottom", fill="x", pady=(10, 0))
        self.status_label = tk.Label(bar, text="", bg=BG, fg=DIM, font=self.f_tiny, anchor="w")
        self._button(bar, "归档并重置", self._confirm_reset, kind="ghost", pady=5, padx=12).pack(
            side="right"
        )
        self._button(bar, "复制结果", self._copy_result, kind="ghost", pady=5, padx=12).pack(
            side="right", padx=(0, 8)
        )
        self._button(bar, "统计图表", self._open_stats, kind="ghost", pady=5, padx=12).pack(
            side="right", padx=(0, 8)
        )
        self.status_label.pack(side="left", fill="x", expand=True)

    # ------------------------------------------------------------ 预设

    def _render_presets(self) -> None:
        for child in self.preset_bar.winfo_children():
            child.destroy()
        for expr in self.presets:
            btn = self._button(
                self.preset_bar,
                expr,
                lambda e=expr: self._pick_preset(e),
                kind="chip",
                font=self.f_mono_small,
                pady=5,
                padx=12,
            )
            btn.pack(side="left", padx=(0, 7))
            btn.bind("<Button-3>", lambda ev, e=expr: self._remove_preset(e))
        self._button(
            self.preset_bar,
            "＋ 预设",
            self._add_preset,
            kind="ghost",
            font=self.f_small,
            pady=5,
            padx=10,
        ).pack(side="left")

    def _pick_preset(self, expr: str) -> None:
        self.var_expr.set(expr)
        self.do_roll(expr)

    def _add_preset(self) -> None:
        text = simpledialog.askstring("添加预设", "骰子表达式（例如 2D6）", parent=self)
        if not text:
            return
        try:
            normalized = dice.parse(text).text
        except dice.DiceError as exc:
            messagebox.showwarning("表达式不合法", str(exc), parent=self)
            return
        if normalized in self.presets:
            self._toast("该预设已存在")
            return
        self.presets.append(normalized)
        save_presets(self.presets)
        self._render_presets()
        self._toast(f"已添加预设 {normalized}")

    def _remove_preset(self, expr: str) -> None:
        if expr not in self.presets:
            return
        if len(self.presets) <= 1:
            self._toast("至少保留一个预设")
            return
        if not messagebox.askyesno("移除预设", f"移除预设 {expr}？（不影响历史记录）", parent=self):
            return
        self.presets.remove(expr)
        save_presets(self.presets)
        self._render_presets()
        self._toast(f"已移除 {expr}")

    # ------------------------------------------------------------ 掷骰

    def do_roll(self, text: Optional[str] = None) -> None:
        if self._animating:
            return
        raw = (text if text is not None else self.var_expr.get()).strip()
        try:
            expr = dice.parse(raw)
        except dice.DiceError as exc:
            self._show_error(str(exc))
            return
        if not self.store.can_append:
            self._guard_writable()
            return

        try:
            result = expr.roll()
            record = self.store.append(result.notation, list(result.rolls), result.modifier)
        except (hist.HistoryError, dice.DiceError) as exc:
            messagebox.showerror("写入失败", str(exc), parent=self)
            self._refresh_history()
            self._update_badge()
            self._update_footer()
            return

        self.var_expr.set(result.notation)
        self._animate(result, record)

    def _animate(self, result: dice.RollResult, record: hist.Record) -> None:
        self._animating = True
        self.roll_btn.configure(state="disabled", bg=CARD_ALT, fg=DIM)
        self.expr_label.configure(text=result.notation)
        self.hint_label.configure(text="掷骰中…", fg=DIM)
        top = max(6, result.total + 4, result.expression.dice_total * 6)
        frames = [random.randint(1, top) for _ in range(9)] + [result.total] * 3

        def step(i: int = 0) -> None:
            if i < len(frames):
                last = i >= len(frames) - 3
                self.total_label.configure(text=str(frames[i]), fg=GOLD if last else DIM)
                self.after(34 + i * 4, step, i + 1)
            else:
                self._finish(result, record)

        step()

    def _finish(self, result: dice.RollResult, record: hist.Record) -> None:
        self._animating = False
        self.roll_btn.configure(
            state="normal", bg=ACCENT, fg="#05160f"
        )
        self.total_label.configure(text=str(result.total), fg=GOLD)
        self.expr_label.configure(text=result.notation)
        self.hint_label.configure(text=self._breakdown_text(result, record), fg=MUTED)
        self._set_chips(result)
        self._last = (result, record)
        self._refresh_history(select=record.index)
        self._update_badge()
        self._update_footer()
        self._refresh_stats_window()

    def _breakdown_text(self, result: dice.RollResult, record: hist.Record) -> str:
        parts = []
        for term, values in result.groups:
            shown = ",".join(str(v) for v in values[:12])
            if len(values) > 12:
                shown += f",…共{len(values)}个"
            parts.append(f"{term.text()} → {shown}")
        if result.modifier:
            parts.append(f"修正 {result.modifier:+d}")
        head = "　·　".join(parts)
        return f"{head}\n合计 {result.total}　·　已写入历史 #{record.index}"

    def _set_chips(self, result: Optional[dice.RollResult]) -> None:
        items: List[Tuple[str, str, str]] = []
        if result is not None:
            limit = 240
            for term, values in result.groups:
                for value in values:
                    if len(items) >= limit:
                        break
                    if value == term.sides:
                        items.append((str(value), "#2f2a18", GOLD))
                    elif value == 1:
                        items.append((str(value), "#2a1f26", DANGER))
                    else:
                        items.append((str(value), FIELD, FG))
                if len(items) >= limit:
                    items.append(("…", FIELD, MUTED))
                    break
        self._chip_items = items
        self._chips_width = -1
        self._relayout_chips()

    def _fit_tree_columns(self, event=None) -> None:
        """窗口变窄时压缩列宽，保证“合计”始终可见。"""
        width = event.width if event is not None else self.tree.winfo_width()
        if width < 120 or abs(width - self._tree_width) < 8:
            return
        self._tree_width = width
        keys = ("idx", "time", "expr", "total")
        minimum = {"idx": 38, "time": 74, "expr": 64, "total": 44}
        fixed = {k: self._col_widths[k] for k in keys}
        room = width - 110
        excess = sum(fixed.values()) - room
        # 先压表达式，再压时间/序号/合计，尽量让“合计”和“时间”完整
        for key in ("expr", "time", "idx", "total"):
            if excess <= 0:
                break
            take = min(fixed[key] - minimum[key], excess)
            if take > 0:
                fixed[key] -= take
                excess -= take
        for key in keys:
            self.tree.column(key, width=fixed[key], minwidth=20)
        self.tree.column(
            "rolls", width=max(50, width - sum(fixed.values())), minwidth=20
        )

    def _on_roll_card_configure(self, event=None) -> None:
        if getattr(self, "hint_label", None) is None:
            return
        wrap = max(180, event.width - 52)
        if abs(wrap - self._hint_wrap) > 12:
            self._hint_wrap = wrap
            self.hint_label.configure(wraplength=wrap)

    def _on_history_card_configure(self, event=None) -> None:
        if getattr(self, "detail_label", None) is None:
            return
        wrap = max(180, event.width - 66)
        if abs(wrap - self._detail_wrap) > 12:
            self._detail_wrap = wrap
            self.detail_label.configure(wraplength=wrap)

    def _on_chips_configure(self, event=None) -> None:
        self._relayout_chips()

    def _relayout_chips(self) -> None:
        if not self.winfo_exists():
            return
        width = max(self.chips.winfo_width(), 120)
        if abs(width - self._chips_width) < 24:
            return
        self._chips_width = width
        for child in self.chips.winfo_children():
            child.destroy()
        row = None
        used = 0
        for text, bg, fg in self._chip_items:
            chip_w = self.f_chip.measure(text) + 18
            if row is None or used + chip_w > width - 4:
                row = tk.Frame(self.chips, bg=CARD)
                row.pack(anchor="w", pady=2)
                used = 0
            tk.Label(
                row,
                text=text,
                bg=bg,
                fg=fg,
                font=self.f_chip,
                padx=7,
                pady=2,
            ).pack(side="left", padx=(0, 6))
            used += chip_w + 6

    def _show_error(self, message: str) -> None:
        self.hint_label.configure(text=message, fg=DANGER)
        self.after(2400, self._restore_hint)

    def _restore_hint(self) -> None:
        if self._animating:
            return
        if not self.store.can_append:
            self.hint_label.configure(
                text="历史校验未通过，掷骰已锁定 · 可点底部「归档并重置」", fg=DANGER
            )
        elif self._last:
            self.hint_label.configure(
                text=self._breakdown_text(*self._last), fg=MUTED
            )
        else:
            self.hint_label.configure(text="输入 xDx（如 3D6），按 Enter 掷骰", fg=DIM)

    # ------------------------------------------------------------ 历史显示

    def _refresh_history(self, select: Optional[int] = None) -> None:
        prev = select
        if prev is None:
            sel = self.tree.selection()
            if sel:
                try:
                    prev = int(sel[0])
                except ValueError:
                    prev = None
        self.tree.delete(*self.tree.get_children())
        self._by_iid = {}
        records = self.store.records
        shown = records[-DISPLAY_LIMIT:]
        for pos, rec in enumerate(reversed(shown)):
            iid = str(rec.index)
            rolls = rec.rolls_text
            if len(rolls) > 88:
                rolls = rolls[:86] + "…"
            idx_text = f"#{rec.index}" if rec.verified else f"⚠{rec.index}"
            tags = ("even" if pos % 2 else "odd",) if rec.verified else ("bad",)
            total_text = rec.total if (rec.verified or rec.rolls) else "?"
            self.tree.insert(
                "",
                "end",
                iid=iid,
                values=(idx_text, rec.clock_text, rec.notation, rolls, total_text),
                tags=tags,
            )
            self._by_iid[iid] = rec

        if len(records) > len(shown):
            self.count_label.configure(text=f"共 {len(records)} 条 · 显示最近 {len(shown)} 条")
        else:
            self.count_label.configure(text=f"共 {len(records)} 条")
        if records:
            self.empty_label.place_forget()
        else:
            self.empty_label.place(relx=0.5, rely=0.42, anchor="center")
            self.empty_label.lift()

        if prev is not None and str(prev) in self._by_iid:
            self.tree.selection_set(str(prev))
            self.tree.see(str(prev))
            self._on_select()
        elif self._detail_record is None or self._detail_record.index not in {
            r.index for r in records
        }:
            self.detail_label.configure(
                text="选中一条记录可查看投掷明细与校验信息", fg=MUTED
            )

    def _on_select(self, event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        rec = self._by_iid.get(sel[0])
        if rec is None:
            return
        self._detail_record = rec
        rolls = rec.rolls_text or "—"
        if len(rolls) > 220:
            rolls = rolls[:218] + "…"
        verified = "✔ 校验通过" if rec.verified else "⚠ 未通过校验"
        self.detail_label.configure(
            text=(
                f"#{rec.index}　{rec.time_text}　{rec.notation}\n"
                f"点数 {rolls}\n"
                f"合计 {rec.total}　·　{verified}　·　MAC {rec.short_tag}"
            ),
            fg=MUTED if rec.verified else DANGER,
        )

    # ------------------------------------------------------------ 状态

    def _update_badge(self) -> None:
        rep = self.store.report
        count = len(self.store.records)
        if rep.can_append:
            self.badge.configure(
                text=f"✔ 历史已校验 · {count} 条", bg=OK_BG, fg=ACCENT
            )
        elif rep.state == hist.STATE_UNVERIFIABLE:
            self.badge.configure(text="⚠ 无法校验 · 已锁定", bg=WARN_BG, fg=GOLD)
        else:
            self.badge.configure(text="⚠ 历史异常 · 已锁定", bg=DANGER_BG, fg=DANGER)

    def _update_footer(self) -> None:
        rep = self.store.report
        try:
            rel = os.path.relpath(self.store.path, hist.project_dir())
        except ValueError:
            rel = self.store.path
        self.status_label.configure(
            text=f"{rel}　·　{len(self.store.records)} 条记录　·　链头 {rep.head_text}"
            + ("" if rep.can_append else f"　·　{rep.message}")
        )

    def _show_integrity_notice(self) -> None:
        rep = self.store.report
        details = "\n".join(f"· {line}" for line in rep.notes[:6])
        body = f"{rep.message}"
        if details:
            body += f"\n\n{details}"
        body += (
            "\n\n历史记录在校验通过前不会被改写，掷骰也已锁定。"
            "\n你可以把当前历史归档（保留文件、不删除），然后开始新的校验链。"
        )
        if messagebox.askyesno("历史校验未通过", body, icon="warning", parent=self):
            self._reset_history()

    def _guard_writable(self) -> None:
        rep = self.store.report
        body = (
            f"{rep.message}\n\n"
            "为避免写入不可信的历史，掷骰已被锁定。\n\n"
            "是否将当前历史文件归档（保留原文件，不删除），并开始新的校验链？"
        )
        if messagebox.askyesno("历史校验未通过", body, icon="warning", parent=self):
            self._reset_history()

    def _confirm_reset(self) -> None:
        if not messagebox.askyesno(
            "归档并重置",
            "当前历史文件会被重命名为 history-<时间>.dat 归档保存（不会删除），\n"
            "然后从空历史开始新的校验链。\n\n继续吗？",
            icon="warning",
            parent=self,
        ):
            return
        self._reset_history()

    def _reset_history(self) -> None:
        try:
            archived = self.store.archive_and_reset()
        except hist.HistoryError as exc:
            messagebox.showerror("重置失败", str(exc), parent=self)
            return
        self._last = None
        self._detail_record = None
        self._chip_items = []
        self._chips_width = -1
        self._relayout_chips()
        self.total_label.configure(text="?", fg=DIM)
        self.expr_label.configure(text="—")
        self.hint_label.configure(text="已开始新的校验链", fg=MUTED)
        self._refresh_history()
        self._update_badge()
        self._update_footer()
        self._refresh_stats_window()
        if archived:
            self._toast("已归档为 " + os.path.basename(archived))
        else:
            self._toast("历史已重置")

    def report_callback_exception(self, exc, val, tb) -> None:  # noqa: D401
        """界面回调异常：写日志并提示，避免 pythonw 下静默失败。"""
        import traceback

        text = "".join(traceback.format_exception(exc, val, tb))
        try:
            os.makedirs(self.store.data_dir, exist_ok=True)
            with open(os.path.join(self.store.data_dir, "error.log"), "a", encoding="utf-8") as fh:
                fh.write(time.strftime("[%Y-%m-%d %H:%M:%S]\n") + text + "\n")
        except OSError:
            pass
        try:
            messagebox.showerror("AliDice 出错", f"{exc.__name__}: {val}", parent=self)
        except Exception:
            pass

    # ------------------------------------------------------------ 统计

    def _open_stats(self) -> None:
        win = self._stats_win
        if win is not None:
            try:
                if win.winfo_exists():
                    win.refresh()
                    win.lift()
                    win.focus_set()
                    return
            except tk.TclError:
                pass
            self._stats_win = None
        from stats_view import StatsWindow

        try:
            self._stats_win = StatsWindow(self, self.store)
        except tk.TclError as exc:
            messagebox.showerror("统计", f"无法打开统计窗口：{exc}", parent=self)

    def _refresh_stats_window(self) -> None:
        win = self._stats_win
        if win is None:
            return
        try:
            if win.winfo_exists():
                win.refresh()
            else:
                self._stats_win = None
        except tk.TclError:
            self._stats_win = None

    # ------------------------------------------------------------ 其它

    def _copy_result(self) -> None:
        rec = self._detail_record if self.tree.selection() else None
        if rec is None and self._last:
            rec = self._last[1]
        if rec is None:
            self._toast("还没有可复制的结果")
            return
        text = (
            f"{rec.time_text}  {rec.notation} = {rec.total}"
            f"  [{rec.rolls_text}]"
        )
        self.clipboard_clear()
        self.clipboard_append(text)
        self._toast("结果已复制到剪贴板")

    def _toast(self, message: str) -> None:
        if self._toast_job is not None:
            try:
                self.after_cancel(self._toast_job)
            except Exception:
                pass
            self._toast_job = None
        self._toast_label.configure(text=message)
        self._toast_label.place(relx=0.5, rely=0.985, anchor="s")
        self._toast_label.lift()

        def hide() -> None:
            self._toast_label.place_forget()
            self._toast_job = None

        self._toast_job = self.after(2400, hide)


# ---------------------------------------------------------------- 启动


def _enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        try:
            import ctypes

            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def _single_instance():
    """防止两个进程同时追加同一条历史链。"""
    if sys.platform != "win32":
        return None
    try:
        import ctypes

        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        handle = k32.CreateMutexW(None, True, "Local\\AliDice.SingleInstance")
        if ctypes.get_last_error() == 183:  # ERROR_ALREADY_EXISTS
            return False
        return handle
    except Exception:
        return None


def _splash_error(title: str, message: str) -> None:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror(title, message)
    root.destroy()


def main() -> None:
    _enable_dpi_awareness()
    guard = _single_instance()
    if guard is False:
        root = tk.Tk()
        root.withdraw()
        messagebox.showwarning("AliDice", "AliDice 已经在运行了。")
        root.destroy()
        return

    store = hist.HistoryStore()
    try:
        store.open()
    except hist.HistoryError as exc:
        _splash_error("AliDice", f"无法打开历史记录：\n{exc}")
        return

    app = None
    try:
        app = DiceApp(store)
    except Exception as exc:  # 启动失败时给个可见的提示
        _splash_error("AliDice", f"启动失败：\n{exc}")
        store.close()
        return
    try:
        app.mainloop()
    finally:
        store.close()


if __name__ == "__main__":
    main()
