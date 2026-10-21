# -*- coding: utf-8 -*-
"""统计窗口：1D10 / 1D100 / 自定义 1Dx 的分布表 + 柱状图 / 饼图。

数据全部来自 :class:`history.HistoryStore` 的已校验记录；``xDy`` 会按
“拆成 x 个 1Dy” 的口径统计。窗口只读，不写历史。
"""

from __future__ import annotations

import math
import tkinter as tk
from tkinter import font as tkfont, messagebox, ttk
from typing import Dict, List, Optional, Tuple

import history as hist
import stats as statsmod
import theme
from theme import C

MAX_SIDES_UI = 10000
TABLE_ROW_LIMIT = 1000


def _mix(color_a: str, color_b: str, t: float) -> str:
    """在两个 #rrggbb 颜色之间插值。"""
    t = max(0.0, min(1.0, t))
    ca = [int(color_a[i : i + 2], 16) for i in (1, 3, 5)]
    cb = [int(color_b[i : i + 2], 16) for i in (1, 3, 5)]
    return "#" + "".join(f"{round(a + (b - a) * t):02x}" for a, b in zip(ca, cb))


def _nice_ceil(value: float) -> float:
    """把坐标上限取整到 1/2/5×10^k，避免出现 37.4 这种轴刻度。"""
    if value <= 0:
        return 1.0
    exp = math.floor(math.log10(value))
    base = 10.0**exp
    for step in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
        candidate = step * base
        if value <= candidate:
            return candidate
    return 10 * base


class StatsWindow(tk.Toplevel):
    def __init__(self, master: tk.Misc, store: hist.HistoryStore) -> None:
        super().__init__(master)
        self.store = store
        self.sides = 100
        self.chart_kind = "bar"
        self.stats: Optional[statsmod.DieStats] = None
        self._bar_hits: List[dict] = []
        self._pie_hits: List[dict] = []
        self._hover_key = None
        self._redraw_job = None
        self._summary_wrap = 900

        self.title("AliDice · 统计")
        self.configure(bg=C.bg)
        self.transient(master)
        self._setup_fonts()
        self._setup_style()
        self._build_ui()
        self.refresh()

        self.minsize(900, 600)
        self.update_idletasks()
        width, height = 1100, 720
        screen_w = self.winfo_screenwidth()
        screen_h = self.winfo_screenheight()
        width = max(900, min(width, screen_w - 60))
        height = max(600, min(height, screen_h - 110))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.geometry(f"{width}x{height}+{x}+{y}")
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
        self.f_brand = (ui, 15, "bold")
        self.f_h = (ui, 11, "bold")
        self.f_ui = (ui, 10)
        self.f_small = (ui, 9)
        self.f_tiny = (ui, 8)
        self.f_mono = (mono, 10)
        self.f_chart = tkfont.Font(family=ui, size=8)
        self.f_pie = tkfont.Font(family=ui, size=8)

    def _setup_style(self) -> None:
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.layout("Stats.Treeview", [("Treeview.treearea", {"sticky": "nswe"})])
        style.configure(
            "Stats.Treeview",
            background=C.card,
            fieldbackground=C.card,
            foreground=C.fg,
            borderwidth=0,
            rowheight=24,
            font=self.f_small,
        )
        style.configure(
            "Stats.Treeview.Heading",
            background=C.card_alt,
            foreground=C.muted,
            borderwidth=0,
            relief="flat",
            font=self.f_tiny,
        )
        style.map("Stats.Treeview", background=[("selected", C.selected)])
        style.map("Stats.Treeview.Heading", background=[("active", C.card_alt)])
        style.configure(
            "Stats.Vertical.TScrollbar",
            background=C.card_alt,
            troughcolor=C.bg,
            bordercolor=C.bg,
            arrowcolor=C.muted,
            relief="flat",
            width=10,
        )

    def _card(self, master) -> tk.Frame:
        return tk.Frame(
            master, bg=C.card, highlightthickness=1, highlightbackground=C.border
        )

    def _chip(self, parent, text, command, active=False) -> tk.Button:
        btn = tk.Button(
            parent,
            text=text,
            command=command,
            bg=C.selected if active else C.field,
            fg=C.fg if active else C.muted,
            activebackground=C.selected if active else C.hover,
            activeforeground=C.fg,
            relief="flat",
            bd=0,
            highlightthickness=0,
            cursor="hand2",
            font=self.f_small,
            padx=11,
            pady=5,
        )
        return btn

    # ------------------------------------------------------------ 布局

    def _build_ui(self) -> None:
        head = tk.Frame(self, bg=C.bg)
        head.pack(fill="x", padx=18, pady=(14, 0))
        tk.Label(head, text="统计", bg=C.bg, fg=C.fg, font=self.f_brand).pack(side="left")
        self.sub_label = tk.Label(head, text="", bg=C.bg, fg=C.dim, font=self.f_small)
        self.sub_label.pack(side="left", padx=(10, 0), pady=(5, 0))

        controls = self._card(self)
        controls.pack(fill="x", padx=18, pady=(12, 0))
        row = tk.Frame(controls, bg=C.card)
        row.pack(fill="x", padx=14, pady=10)

        tk.Label(row, text="骰子", bg=C.card, fg=C.muted, font=self.f_small).pack(side="left")
        self.die_chips: Dict[int, tk.Button] = {}
        for sides in (10, 100):
            btn = self._chip(row, f"1D{sides}", lambda s=sides: self._set_sides(s))
            btn.pack(side="left", padx=(8, 0))
            self.die_chips[sides] = btn

        tk.Label(row, text="自定义 1D", bg=C.card, fg=C.muted, font=self.f_small).pack(
            side="left", padx=(16, 0)
        )
        self.custom_var = tk.StringVar()
        entry_wrap = tk.Frame(
            row, bg=C.field, highlightthickness=1, highlightbackground=C.border, highlightcolor=C.accent
        )
        entry_wrap.pack(side="left", padx=(8, 0))
        self.custom_entry = tk.Entry(
            entry_wrap,
            textvariable=self.custom_var,
            width=7,
            bg=C.field,
            fg=C.fg,
            insertbackground=C.accent,
            relief="flat",
            bd=0,
            font=self.f_mono,
            justify="center",
        )
        self.custom_entry.pack(padx=6, pady=4)
        self.custom_entry.bind("<Return>", lambda e: self._apply_custom())
        self._chip(row, "统计", self._apply_custom).pack(side="left", padx=(6, 0))

        tk.Frame(row, bg=C.border, width=1).pack(side="left", fill="y", padx=14)
        tk.Label(row, text="图表", bg=C.card, fg=C.muted, font=self.f_small).pack(side="left")
        self.chart_chips: Dict[str, tk.Button] = {}
        for kind, label in (("bar", "柱状图"), ("pie", "饼图")):
            btn = self._chip(row, label, lambda k=kind: self._set_chart(k))
            btn.pack(side="left", padx=(8, 0))
            self.chart_chips[kind] = btn

        spacer = tk.Frame(row, bg=C.card)
        spacer.pack(side="left", fill="x", expand=True)
        self._chip(row, "刷新", self.refresh).pack(side="right")

        body = tk.Frame(self, bg=C.bg)
        body.pack(fill="both", expand=True, padx=18, pady=(12, 0))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, minsize=300, weight=0)
        body.rowconfigure(0, weight=1)

        chart_card = self._card(body)
        chart_card.grid(row=0, column=0, sticky="nsew", padx=(0, 10))
        inner = tk.Frame(chart_card, bg=C.card)
        inner.pack(fill="both", expand=True, padx=1, pady=1)
        self.canvas = tk.Canvas(inner, bg=C.card, highlightthickness=0)
        self.canvas.pack(fill="both", expand=True, padx=10, pady=(10, 2))
        self.canvas.bind("<Configure>", self._on_canvas_configure)
        self.canvas.bind("<Motion>", self._on_motion)
        self.canvas.bind("<Leave>", self._on_leave)
        self.hint = tk.Label(
            inner,
            text="",
            bg=C.card,
            fg=C.dim,
            font=self.f_tiny,
            anchor="w",
        )
        self.hint.pack(fill="x", padx=14, pady=(0, 8))

        table_card = self._card(body)
        table_card.grid(row=0, column=1, sticky="nsew")
        tinner = tk.Frame(table_card, bg=C.card)
        tinner.pack(fill="both", expand=True, padx=1, pady=1)
        thead = tk.Frame(tinner, bg=C.card)
        thead.pack(fill="x", padx=12, pady=(10, 6))
        tk.Label(thead, text="分布表", bg=C.card, fg=C.fg, font=self.f_h).pack(side="left")
        self.table_info = tk.Label(thead, text="", bg=C.card, fg=C.dim, font=self.f_tiny)
        self.table_info.pack(side="right")

        wrap = tk.Frame(tinner, bg=C.card)
        wrap.pack(fill="both", expand=True, padx=(10, 8), pady=(0, 10))
        cols = ("face", "count", "pct")
        self.tree = ttk.Treeview(
            wrap,
            columns=cols,
            show="headings",
            style="Stats.Treeview",
            selectmode="browse",
        )
        for col, title, width, anchor in (
            ("face", "点数", 76, "w"),
            ("count", "次数", 80, "e"),
            ("pct", "占比", 96, "e"),
        ):
            self.tree.heading(col, text=title, anchor=anchor)
            self.tree.column(col, width=width, minwidth=52, anchor=anchor, stretch=(col == "pct"))
        scroll = ttk.Scrollbar(
            wrap, orient="vertical", command=self.tree.yview, style="Stats.Vertical.TScrollbar"
        )
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self._configure_tags()

        foot = tk.Frame(self, bg=C.bg)
        foot.pack(fill="x", padx=18, pady=(10, 12))
        self.summary = tk.Label(
            foot,
            text="",
            bg=C.bg,
            fg=C.muted,
            font=self.f_small,
            anchor="w",
            justify="left",
            wraplength=self._summary_wrap,
        )
        self.summary.pack(fill="x")
        self.bind("<Configure>", self._on_window_configure)
        self.bind("<Escape>", lambda e: self.destroy())

    def apply_theme(self, mapping=None) -> None:
        if mapping:
            theme.apply_to_widgets(self, mapping)
        self._setup_style()
        self._configure_tags()
        self._sync_chips()
        self._update_table()
        self._update_summary()
        self._redraw()

    def _configure_tags(self) -> None:
        self.tree.tag_configure("hot", foreground=C.gold)
        self.tree.tag_configure("zero", foreground=C.dim)
        self.tree.tag_configure("odd", background=C.card)
        self.tree.tag_configure("even", background=C.row_alt)

    def _on_window_configure(self, event=None) -> None:
        if event is not None and event.widget is not self:
            return
        wrap = max(400, event.width - 40 if event is not None else 900)
        if abs(wrap - self._summary_wrap) > 20:
            self._summary_wrap = wrap
            self.summary.configure(wraplength=wrap)

    # ------------------------------------------------------------ 选择

    def _set_sides(self, sides: int) -> None:
        if not 1 <= sides <= MAX_SIDES_UI:
            messagebox.showwarning(
                "面数超出范围", f"自定义骰子支持 1 到 {MAX_SIDES_UI} 面。", parent=self
            )
            return
        self.sides = int(sides)
        self.custom_var.set("")
        self.refresh()

    def _apply_custom(self) -> None:
        text = self.custom_var.get().strip().replace(" ", "").upper()
        if text.startswith("1D"):
            text = text[2:]
        elif text.startswith("D"):
            text = text[1:]
        if not text.isdigit():
            messagebox.showwarning("格式不对", "请输入面数，例如 20，或写 1D20。", parent=self)
            return
        value = int(text)
        if not 1 <= value <= MAX_SIDES_UI:
            messagebox.showwarning(
                "面数超出范围", f"自定义骰子支持 1 到 {MAX_SIDES_UI} 面。", parent=self
            )
            return
        self.sides = value
        self.custom_var.set(str(value))
        self.refresh()

    def _set_chart(self, kind: str) -> None:
        self.chart_kind = kind
        self._sync_chips()
        self._redraw()

    def _sync_chips(self) -> None:
        for sides, btn in self.die_chips.items():
            active = sides == self.sides
            btn.configure(
                bg=C.selected if active else C.field,
                fg=C.fg if active else C.muted,
                activebackground=C.selected if active else C.hover,
            )
        for kind, btn in self.chart_chips.items():
            active = kind == self.chart_kind
            btn.configure(
                bg=C.selected if active else C.field,
                fg=C.fg if active else C.muted,
                activebackground=C.selected if active else C.hover,
            )
        custom_active = self.sides not in self.die_chips
        self.custom_entry.configure(
            bg=C.selected if custom_active else C.field,
            fg=C.fg if custom_active else C.muted,
        )

    # ------------------------------------------------------------ 数据

    def refresh(self) -> None:
        if not self.winfo_exists():
            return
        self.stats = statsmod.collect(self.store.records, self.sides)
        self.sub_label.configure(
            text=f"当前 1D{self.sides}　·　{len(self.store.records)} 条历史记录"
        )
        self._sync_chips()
        self._update_table()
        self._update_summary()
        self._redraw()

    def _update_table(self) -> None:
        self.tree.delete(*self.tree.get_children())
        st = self.stats
        if st is None or st.total == 0:
            self.table_info.configure(text="无数据")
            return
        faces = st.faces()
        limited = st.sides > TABLE_ROW_LIMIT
        if limited:
            faces = [f for f in faces if f.count > 0]
        hot = st.hottest
        for i, face in enumerate(faces):
            stripe = "even" if i % 2 else "odd"
            tags = (stripe,)
            if face.count == 0:
                tags = ("zero",)
            elif hot is not None and face.face == hot.face:
                tags = (stripe, "hot")
            self.tree.insert(
                "",
                "end",
                values=(face.face, face.count, f"{face.ratio * 100:.2f}%"),
                tags=tags,
            )
        if limited:
            self.table_info.configure(text=f"仅显示出现过的点数（共 {st.sides} 面）")
        else:
            self.table_info.configure(text=f"{len(faces)} 行")
        # 重建后清掉 Tk 残留的焦点项高亮
        self.tree.focus("")
        self.tree.selection_remove(*self.tree.selection())

    def _update_summary(self) -> None:
        st = self.stats
        if st is None or st.total == 0:
            self.summary.configure(
                text=f"还没有 1D{self.sides} 的记录。",
                fg=C.dim,
            )
            return
        hot = st.hottest
        cold = st.coldest
        parts = [
            f"共 {st.total} 个 1D{st.sides} 点数",
            f"来自 {st.records_used} 条记录",
            f"平均 {st.mean:.2f}（期望 {(st.sides + 1) / 2:.2f}）",
        ]
        if hot is not None:
            parts.append(
                f"最常见 {hot.face}（{hot.count} 次，{hot.ratio * 100:.2f}%）"
            )
        if cold is not None:
            parts.append(f"最少见 {cold.face}（{cold.count} 次）")
        text = "　·　".join(parts)
        notes = []
        if st.records_unverified:
            notes.append(f"{st.records_unverified} 条未通过校验的记录未计入")
        if st.records_ignored:
            notes.append(f"{st.records_ignored} 条无法解析的记录未计入")
        if notes:
            text += "\n" + "；".join(notes) + "。"
        self.summary.configure(text=text, fg=C.muted)

    # ------------------------------------------------------------ 绘制

    def _on_canvas_configure(self, event=None) -> None:
        if self._redraw_job is not None:
            try:
                self.after_cancel(self._redraw_job)
            except Exception:
                pass
        self._redraw_job = self.after(60, self._redraw_now)

    def _redraw_now(self) -> None:
        self._redraw_job = None
        self._redraw()

    def _redraw(self) -> None:
        if not self.winfo_exists():
            return
        self._hover_key = None
        self._bar_hits = []
        self._pie_hits = []
        self.canvas.delete("all")
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        if width < 80 or height < 80:
            return
        st = self.stats
        if st is None or st.total == 0:
            self.canvas.create_text(
                width / 2,
                height / 2,
                text=f"没有可统计的 1D{self.sides} 记录",
                fill=C.dim,
                font=self.f_ui,
            )
            self.hint.configure(text="在主窗口掷骰后，这里会自动更新")
            return
        if self.chart_kind == "bar":
            self._draw_bars(width, height)
        else:
            self._draw_pie(width, height)

    def _draw_bars(self, width: int, height: int) -> None:
        st = self.stats
        assert st is not None
        bins = st.bins(statsmod.MAX_BARS)
        if not bins:
            return
        pad_l, pad_r, pad_t, pad_b = 48, 16, 20, 32
        plot_w = width - pad_l - pad_r
        plot_h = height - pad_t - pad_b
        if plot_w < 40 or plot_h < 40:
            return

        max_count = max(b.count for b in bins)
        uniform = len(bins) == st.sides
        y_max = max(max_count, st.expected if uniform else 0.0, 1.0)
        y_max = _nice_ceil(y_max * 1.05)

        for i in range(5):
            y = pad_t + plot_h * i / 4
            value = y_max * (1 - i / 4)
            self.canvas.create_line(pad_l, y, width - pad_r, y, fill=C.border)
            label = f"{value:g}"
            self.canvas.create_text(
                pad_l - 8, y, text=label, anchor="e", fill=C.dim, font=self.f_chart
            )

        slot = plot_w / len(bins)
        gap = min(7.0, max(1.0, slot * 0.2))
        for i, b in enumerate(bins):
            x0 = pad_l + i * slot + gap / 2
            x1 = pad_l + (i + 1) * slot - gap / 2
            bar_h = plot_h * (b.count / y_max)
            y0 = pad_t + plot_h - bar_h
            expected = st.total * b.width / st.sides if st.sides else 0.0
            color = _mix(C.accent, C.gold, (b.count / max_count) if max_count else 0.0)
            rect = self.canvas.create_rectangle(
                x0, y0, max(x1, x0 + 1), pad_t + plot_h, fill=color, outline=""
            )
            self._bar_hits.append(
                {
                    "x0": x0,
                    "x1": max(x1, x0 + 1),
                    "y0": y0,
                    "rect": rect,
                    "label": b.label,
                    "count": b.count,
                    "ratio": b.ratio,
                    "expected": expected,
                    "y1": pad_t + plot_h,
                }
            )

        if uniform:
            exp_y = pad_t + plot_h * (1 - st.expected / y_max)
            self.canvas.create_line(
                pad_l, exp_y, width - pad_r, exp_y, fill=C.blue, dash=(4, 4)
            )
            self.canvas.create_text(
                width - pad_r - 4,
                exp_y - 9,
                text=f"期望 {st.expected:.1f}",
                anchor="e",
                fill=C.blue,
                font=self.f_chart,
            )

        self.canvas.create_line(
            pad_l, pad_t + plot_h, width - pad_r, pad_t + plot_h, fill=C.border
        )

        step = max(1, math.ceil(len(bins) / 12))
        for i in range(0, len(bins), step):
            cx = pad_l + (i + 0.5) * slot
            self.canvas.create_text(
                cx,
                pad_t + plot_h + 8,
                text=bins[i].label,
                anchor="n",
                fill=C.muted,
                font=self.f_chart,
            )

        self.hint.configure(text="")

    def _draw_pie(self, width: int, height: int) -> None:
        st = self.stats
        assert st is not None

        slices: List[Tuple[str, int, float, str]] = []
        if st.sides <= 12:
            for face in st.faces():
                slices.append(
                    (
                        f"点数 {face.face}",
                        face.count,
                        face.ratio,
                        C.series[(face.face - 1) % len(C.series)],
                    )
                )
        else:
            bins = st.bins(10)
            for i, b in enumerate(bins):
                slices.append(
                    (f"点数 {b.label}", b.count, b.ratio, C.series[i % len(C.series)])
                )
        if not slices:
            return

        # 按图例文本的实际宽度给饼图留位，避免窄窗口下图例被裁掉
        legend_texts = [
            f"{label}　{count} 次 · {ratio * 100:.1f}%"
            for label, count, ratio, _color in slices
        ]
        text_w = max(self.f_chart.measure(t) for t in legend_texts) + 40
        legend_w = min(max(float(text_w), 190.0), width * 0.55)
        pie_w = width - legend_w - 28
        radius = min(pie_w, height - 40) * 0.42
        if radius <= 10:
            return
        cx = 20 + pie_w / 2
        cy = height / 2
        self._pie_geom = (cx, cy, radius)

        angle = 90.0
        for label, count, ratio, color in slices:
            extent = 360.0 * ratio
            if extent <= 0:
                continue
            item = self.canvas.create_arc(
                cx - radius,
                cy - radius,
                cx + radius,
                cy + radius,
                start=angle,
                extent=extent,
                fill=color,
                outline=C.card,
                width=2,
            )
            lo = angle % 360.0
            hi = (angle + extent) % 360.0
            self._pie_hits.append(
                {
                    "lo": lo,
                    "hi": hi,
                    "arc": item,
                    "label": label,
                    "count": count,
                    "ratio": ratio,
                }
            )
            if extent >= 14:
                mid = math.radians(angle + extent / 2)
                lx = cx + radius * 0.62 * math.cos(mid)
                ly = cy - radius * 0.62 * math.sin(mid)
                self.canvas.create_text(
                    lx,
                    ly,
                    text=f"{ratio * 100:.1f}%",
                    fill=C.chart_label,
                    font=self.f_pie,
                )
            angle += extent

        # 图例（单行文本，避免窄窗口下与次数/占比列重叠）
        x = 20 + pie_w + 14
        y = max(18.0, cy - (len(slices) * 22) / 2)
        for i, (label, count, ratio, color) in enumerate(slices):
            if y > height - 16:
                break
            self.canvas.create_rectangle(x, y + 2, x + 10, y + 12, fill=color, outline="")
            self.canvas.create_text(
                x + 18,
                y + 7,
                text=legend_texts[i],
                anchor="w",
                fill=C.muted,
                font=self.f_chart,
            )
            y += 22

        self.hint.configure(text="")

    # ------------------------------------------------------------ 悬停

    def _on_motion(self, event) -> None:
        if not self.stats or self.stats.total == 0:
            return
        if self.chart_kind == "bar":
            hit = None
            for info in self._bar_hits:
                if (
                    info["x0"] <= event.x <= info["x1"]
                    and info["y0"] - 2 <= event.y <= info["y1"]
                ):
                    hit = info
                    break
            self._apply_hover(hit, "bar")
        else:
            hit = self._pie_hit(event.x, event.y)
            self._apply_hover(hit, "pie")

    def _pie_hit(self, x: int, y: int) -> Optional[dict]:
        if not self._pie_hits:
            return None
        # 用与 _draw_pie 相同的方式推算圆心与半径
        width = self.canvas.winfo_width()
        height = self.canvas.winfo_height()
        legend_w = min(300.0, max(190.0, width * 0.38))
        pie_w = width - legend_w - 28
        radius = min(pie_w, height - 40) * 0.42
        cx = 20 + pie_w / 2
        cy = height / 2
        if math.hypot(x - cx, y - cy) > radius:
            return None
        angle = math.degrees(math.atan2(cy - y, x - cx)) % 360.0
        for info in self._pie_hits:
            lo, hi = info["lo"], info["hi"]
            inside = (lo <= angle <= hi) if lo <= hi else (angle >= lo or angle <= hi)
            if inside:
                return info
        return None

    def _apply_hover(self, hit: Optional[dict], kind: str) -> None:
        key = None if hit is None else (kind, hit.get("label"), hit.get("count"))
        if key == self._hover_key:
            return
        self._hover_key = key
        for info in self._bar_hits:
            self.canvas.itemconfigure(info["rect"], outline="", width=0)
        for info in self._pie_hits:
            self.canvas.itemconfigure(info["arc"], outline=C.card, width=2)
        if hit is None:
            self.hint.configure(text="")
            return
        if kind == "bar":
            self.canvas.itemconfigure(hit["rect"], outline=C.fg, width=1)
            self.hint.configure(
                text=(
                    f"{hit['label']}：{hit['count']} 次（{hit['ratio'] * 100:.2f}%）"
                    f"　·　期望 {hit['expected']:.2f}"
                )
            )
        else:
            self.canvas.itemconfigure(hit["arc"], outline=C.fg, width=1)
            self.hint.configure(
                text=f"{hit['label']}：{hit['count']} 次（{hit['ratio'] * 100:.2f}%）"
            )

    def _on_leave(self, event=None) -> None:
        self._apply_hover(None, self.chart_kind)
