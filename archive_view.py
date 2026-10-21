# -*- coding: utf-8 -*-
"""归档历史查看窗口：只读打开 ``history-*.dat``，显示记录与校验状态。

归档文件使用独立的历史链，用该文件自己的 seal 校验（见 history.py）；
窗口内没有任何写入入口，也不能修改历史。
"""

from __future__ import annotations

import os
import tkinter as tk
from tkinter import font as tkfont, ttk
from typing import Dict, Optional

import chipgrid
import dice
import history as hist
import theme
from theme import C

DISPLAY_LIMIT = 2000


class ArchiveWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc, path: str) -> None:
        super().__init__(master)
        self.path = os.path.abspath(path)
        self.store = hist.HistoryStore.for_file(self.path, read_only=True)
        self.report = self.store.open()
        self._by_iid: Dict[str, hist.Record] = {}
        self._detail_record: Optional[hist.Record] = None
        self._tree_width = 0
        self._col_widths: Dict[str, int] = {}
        self._status_job = None
        self.view_mode = "table"

        self.title("AliDice · 归档")
        self.configure(bg=C.bg)
        self.transient(master)
        self._setup_fonts()
        self._setup_style()
        self._build_ui()
        self._fill()

        self.minsize(760, 520)
        self.update_idletasks()
        width, height = 960, 660
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = max(760, min(width, screen_w - 80))
        height = max(520, min(height, screen_h - 130))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.geometry(f"{width}x{height}+{x}+{y}")
        self.bind("<Escape>", lambda e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)
        self.after(30, self._focus_self)

    # ------------------------------------------------------------ 外观

    def _focus_self(self) -> None:
        try:
            self.lift()
            self.focus_set()
        except tk.TclError:
            pass

    def _setup_fonts(self) -> None:
        ui = theme.pick_family(self, theme.UI_FONTS)
        mono = theme.pick_family(self, theme.MONO_FONTS)
        self.f_chip = tkfont.Font(family=mono, size=9)
        self.f_brand = (ui, 14, "bold")
        self.f_h = (ui, 11, "bold")
        self.f_ui = (ui, 10)
        self.f_small = (ui, 9)
        self.f_tiny = (ui, 8)
        self.f_mono = (mono, 9)

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.layout("Archive.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure(
            "Archive.Treeview",
            background=C.card,
            fieldbackground=C.card,
            foreground=C.fg,
            borderwidth=0,
            rowheight=26,
            font=self.f_small,
        )
        style.configure(
            "Archive.Treeview.Heading",
            background=C.card_alt,
            foreground=C.muted,
            borderwidth=0,
            relief="flat",
            font=self.f_tiny,
        )
        style.map(
            "Archive.Treeview",
            background=[("selected", C.selected)],
            foreground=[("selected", C.selected_fg)],
        )
        style.map("Archive.Treeview.Heading", background=[("active", C.card_alt)])
        theme.configure_scrollbar(style, "Archive.Vertical.TScrollbar")

    def _card(self, master) -> tk.Frame:
        return tk.Frame(master, bg=C.card, highlightthickness=1, highlightbackground=C.border)

    # ------------------------------------------------------------ 布局

    def _build_ui(self) -> None:
        head = tk.Frame(self, bg=C.bg)
        head.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(head, text="归档", bg=C.bg, fg=C.fg, font=self.f_brand).pack(side="left")
        self.name_label = tk.Label(
            head, text=os.path.basename(self.path), bg=C.bg, fg=C.muted, font=self.f_small
        )
        self.name_label.pack(side="left", padx=(10, 0), pady=(4, 0))
        self.badge = tk.Label(
            head, text="", bg=C.ok_bg, fg=C.accent, font=self.f_tiny, padx=12, pady=5
        )
        self.badge.pack(side="right")

        view_box = tk.Frame(head, bg=C.card_alt)
        view_box.pack(side="right", padx=(0, 8))
        self.view_chips = {}
        for mode, label in (("table", "表格"), ("compact", "缩略")):
            chip = self._view_chip(view_box, label, lambda m=mode: self._set_view(m))
            chip.pack(side="left", padx=1, pady=1)
            self.view_chips[mode] = chip
        self._sync_view_chips()

        self.path_label = tk.Label(
            self, text=self.path, bg=C.bg, fg=C.dim, font=self.f_tiny, anchor="w"
        )
        self.path_label.pack(fill="x", padx=18, pady=(6, 0))
        self.meta_label = tk.Label(
            self, text="", bg=C.bg, fg=C.muted, font=self.f_small, anchor="w"
        )
        self.meta_label.pack(fill="x", padx=18, pady=(4, 0))

        body = tk.Frame(self, bg=C.bg)
        body.pack(fill="both", expand=True, padx=18, pady=(10, 0))
        card = self._card(body)
        card.pack(fill="both", expand=True)
        inner = tk.Frame(card, bg=C.card)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        self.table_frame = tk.Frame(inner, bg=C.card)
        self.table_frame.pack(fill="both", expand=True)
        wrap = tk.Frame(self.table_frame, bg=C.card)
        wrap.pack(fill="both", expand=True, padx=(10, 6), pady=(8, 4))
        cols = ("idx", "time", "expr", "rolls", "total")
        headings = {"idx": "#", "time": "时间", "expr": "表达式", "rolls": "点数", "total": "合计"}
        measure = tkfont.Font(font=self.f_small).measure
        self._col_widths = {
            "idx": measure("#888") + 10,
            "time": measure("88:88:88") + 16,
            "expr": measure("88D888+88D8") + 14,
            "total": measure("88888") + 12,
        }
        self.tree = ttk.Treeview(
            wrap, columns=cols, show="headings", style="Archive.Treeview", selectmode="browse"
        )
        for col in cols:
            anchor = "e" if col == "total" else "w"
            self.tree.heading(col, text=headings[col], anchor=anchor)
            self.tree.column(
                col,
                width=self._col_widths.get(col, 120),
                minwidth=20,
                anchor=anchor,
                stretch=(col == "rolls"),
            )
        scroll = ttk.Scrollbar(
            wrap,
            orient="vertical",
            command=self.tree.yview,
            style="Archive.Vertical.TScrollbar",
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Configure>", self._fit_columns)
        self.tree.bind("<<TreeviewSelect>>", self._on_select)
        self._apply_tags()

        self.chips = chipgrid.ChipGrid(
            inner,
            font=self.f_chip,
            on_click=self._on_chip_click,
            empty_text="空归档",
        )

        detail_card = self._card(self)
        detail_card.pack(fill="x", padx=18, pady=(10, 0))
        self.detail = tk.Label(
            detail_card,
            text="选中记录查看明细",
            bg=C.card_alt,
            fg=C.muted,
            font=self.f_tiny,
            justify="left",
            anchor="w",
            padx=12,
            pady=9,
        )
        self.detail.pack(fill="x")

        foot = tk.Frame(self, bg=C.bg)
        foot.pack(fill="x", padx=18, pady=(10, 12))
        self.status = tk.Label(foot, text="", bg=C.bg, fg=C.dim, font=self.f_tiny, anchor="w")
        self.status.pack(side="left", fill="x", expand=True)
        self._button(foot, "关闭", self._close).pack(side="right")
        self._button(foot, "复制结果", self._copy_result).pack(side="right", padx=(0, 8))
        self.bind("<Configure>", self._on_resize)

    def _view_chip(self, parent, text, command) -> tk.Button:
        return tk.Button(
            parent,
            text=text,
            command=command,
            bg=C.card_alt,
            fg=C.muted,
            activebackground=C.hover,
            activeforeground=C.fg,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            font=self.f_tiny,
            padx=9,
            pady=3,
        )

    def _sync_view_chips(self) -> None:
        for mode, chip in self.view_chips.items():
            if mode == self.view_mode:
                chip.configure(bg=C.selected, fg=C.fg)
            else:
                chip.configure(bg=C.card_alt, fg=C.muted)

    def _set_view(self, mode: str) -> None:
        self.view_mode = mode
        if mode == "table":
            self.chips.pack_forget()
            self.table_frame.pack(fill="both", expand=True)
        else:
            self.table_frame.pack_forget()
            self._fill_chips()
            self.chips.pack(fill="both", expand=True, padx=(10, 6), pady=(8, 4))
        self._sync_view_chips()

    def _fill_chips(self) -> None:
        items = []
        for rec in reversed(self.store.records[-DISPLAY_LIMIT:]):
            items.append(
                {
                    "text": dice.result_text(rec.notation, rec.rolls, rec.modifier),
                    "key": rec.index,
                    "danger": not rec.verified,
                }
            )
        selected = self._detail_record.index if self._detail_record else None
        self.chips.set_items(items, selected=selected)

    def _on_chip_click(self, key: int) -> None:
        for rec in self.store.records:
            if rec.index == key:
                self._show_record(rec)
                self.chips.set_selected(key)
                if str(key) in self._by_iid:
                    self.tree.selection_set(str(key))
                return

    def _button(self, parent, text, command) -> tk.Button:
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=C.card_alt,
            fg=C.fg,
            activebackground=C.hover,
            activeforeground=C.fg,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            font=self.f_small,
            padx=12,
            pady=5,
        )
        btn.bind("<Enter>", lambda e: btn.configure(bg=C.hover))
        btn.bind("<Leave>", lambda e: btn.configure(bg=C.card_alt))
        return btn

    def _on_resize(self, event=None) -> None:
        if event is not None and event.widget is not self:
            return
        width = event.width if event is not None else self.winfo_width()
        wrap = max(300, width - 60)
        if getattr(self, "_detail_wrap", 0) != wrap:
            self._detail_wrap = wrap
            self.detail.configure(wraplength=wrap)

    def _fit_columns(self, event=None) -> None:
        width = event.width if event is not None else self.tree.winfo_width()
        if width < 120 or abs(width - self._tree_width) < 8:
            return
        self._tree_width = width
        keys = ("idx", "time", "expr", "total")
        minimum = {"idx": 38, "time": 74, "expr": 64, "total": 44}
        fixed = {k: self._col_widths[k] for k in keys}
        room = width - 110
        excess = sum(fixed.values()) - room
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

    def _apply_tags(self) -> None:
        self.tree.tag_configure("odd", background=C.card)
        self.tree.tag_configure("even", background=C.row_alt)
        self.tree.tag_configure("bad", foreground=C.danger)

    # ------------------------------------------------------------ 数据

    def _fill(self) -> None:
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
            total = rec.total if (rec.verified or rec.rolls) else "?"
            self.tree.insert(
                "", "end", iid=iid, values=(idx_text, rec.clock_text, rec.notation, rolls, total), tags=tags
            )
            self._by_iid[iid] = rec
        # 清掉 Tk 默认给第一行画的焦点高亮
        self.tree.focus("")
        self.tree.selection_remove(*self.tree.selection())
        self._update_badge()
        self._update_meta()
        if self.view_mode == "compact":
            self._fill_chips()

    def _update_badge(self) -> None:
        rep = self.report
        count = len(self.store.records)
        if rep.state in (hist.STATE_OK, hist.STATE_EMPTY):
            self.badge.configure(text=f"✔ 校验通过 · {count} 条", bg=C.ok_bg, fg=C.accent)
        elif rep.state == hist.STATE_UNVERIFIABLE:
            self.badge.configure(text="⚠ 无法校验", bg=C.warn_bg, fg=C.gold)
        else:
            self.badge.configure(text="⚠ 校验失败", bg=C.danger_bg, fg=C.danger)

    def _update_meta(self) -> None:
        records = self.store.records
        if not records:
            self.meta_label.configure(text=self.report.message or "空归档", fg=C.dim)
            return
        first, last = records[0], records[-1]
        span = first.time_text if first.index == last.index else f"{first.time_text} ~ {last.time_text}"
        text = f"{len(records)} 条记录 · {span} · 链头 {self.report.head_text}"
        if len(records) > DISPLAY_LIMIT:
            text += f" · 仅显示最近 {DISPLAY_LIMIT} 条"
        if not self.report.can_append:
            text += f" · {self.report.message}"
        self.meta_label.configure(text=text, fg=C.muted)

    def _on_select(self, event=None) -> None:
        sel = self.tree.selection()
        if not sel:
            return
        rec = self._by_iid.get(sel[0])
        if rec is not None:
            self._show_record(rec)

    def _show_record(self, rec: hist.Record) -> None:
        self._detail_record = rec
        rolls = rec.rolls_text or "—"
        if len(rolls) > 220:
            rolls = rolls[:218] + "…"
        verified = "✔ 校验通过" if rec.verified else "⚠ 未通过校验"
        self.detail.configure(
            text=(
                f"#{rec.index}　{rec.time_text}　{rec.notation}\n"
                f"点数 {rolls}\n"
                f"合计 {rec.total}　·　{verified}　·　MAC {rec.short_tag}"
            ),
            fg=C.muted if rec.verified else C.danger,
        )
        chips = getattr(self, "chips", None)
        if chips is not None:
            chips.set_selected(rec.index)

    def _copy_result(self) -> None:
        rec = self._detail_record
        if rec is None:
            sel = self.tree.selection()
            if sel:
                rec = self._by_iid.get(sel[0])
        if rec is None and self.store.records:
            for candidate in reversed(self.store.records):
                if candidate.verified:
                    rec = candidate
                    break
        if rec is None:
            self._flash("没有可复制的结果")
            return
        if not rec.verified and not rec.rolls:
            self._flash("该记录未通过校验，无法复制")
            return
        text = dice.bracket_text(rec.notation, rec.rolls, rec.modifier)
        self.clipboard_clear()
        self.clipboard_append(text)
        self._flash(f"已复制 {text}")

    def _flash(self, message: str) -> None:
        self.status.configure(text=message)
        if self._status_job is not None:
            try:
                self.after_cancel(self._status_job)
            except Exception:
                pass
        self._status_job = self.after(2400, lambda: self.status.configure(text=""))

    # ------------------------------------------------------------ 主题

    def apply_theme(self, mapping=None) -> None:
        if mapping:
            theme.apply_to_widgets(self, mapping)
        self._setup_style()
        self._apply_tags()
        self._update_badge()
        self._update_meta()
        if self.view_mode == "compact":
            self.chips.apply_theme()
        self._sync_view_chips()
        self._on_select()

    # ------------------------------------------------------------ 关闭

    def _close(self) -> None:
        try:
            self.store.close()
        finally:
            self.destroy()
