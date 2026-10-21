# -*- coding: utf-8 -*-
"""共享主题：暗色 / 亮色两套配色、字体选择、运行时换肤。

所有窗口都通过模块级可变对象 :data:`C` 取色（例如 ``C.bg``），
:func:`switch` 会就地更新它并返回“旧色 -> 新色”的映射，
:func:`apply_to_widgets` 用这个映射把已存在的控件重新上色。
"""

from __future__ import annotations

import tkinter as tk
from dataclasses import dataclass, fields
from tkinter import font as tkfont
from types import SimpleNamespace
from typing import Dict, Iterable, Tuple


@dataclass(frozen=True)
class Palette:
    name: str
    label: str  # 切换按钮上的文案（“亮色”/“暗色”）
    bg: str
    card: str
    card_alt: str
    field: str
    border: str
    fg: str
    muted: str
    dim: str
    accent: str
    accent_hover: str
    accent_text: str
    blue: str
    gold: str
    danger: str
    danger_bg: str
    ok_bg: str
    warn_bg: str
    selected: str
    selected_fg: str
    hover: str
    row_alt: str
    chip_max_bg: str
    chip_min_bg: str
    chart_label: str
    series: Tuple[str, ...]


DARK = Palette(
    name="dark",
    label="亮色",
    bg="#0e1016",
    card="#181c26",
    card_alt="#1e2330",
    field="#202634",
    border="#2b3242",
    fg="#e9edf6",
    muted="#8b95a8",
    dim="#5b6478",
    accent="#5ee0b0",
    accent_hover="#7cf0c6",
    accent_text="#05160f",
    blue="#7aa2ff",
    gold="#ffcf6b",
    danger="#ff6b6b",
    danger_bg="#3a1f24",
    ok_bg="#17362c",
    warn_bg="#3a3021",
    selected="#2c3a55",
    selected_fg="#ffffff",
    hover="#2b3446",
    row_alt="#1c212c",
    chip_max_bg="#2f2a18",
    chip_min_bg="#2a1f26",
    chart_label="#0b0d12",
    series=(
        "#5ee0b0",
        "#7aa2ff",
        "#ffcf6b",
        "#ff8fab",
        "#8b7dff",
        "#4dd0e1",
        "#ffa94d",
        "#a0e57c",
        "#f78fb3",
        "#8ab4ff",
        "#ffe08a",
        "#66d9c4",
    ),
)

LIGHT = Palette(
    name="light",
    label="暗色",
    bg="#eef1f6",
    card="#ffffff",
    card_alt="#f5f7fb",
    field="#e8edf5",
    border="#dde3ec",
    fg="#1a2230",
    muted="#5d6a80",
    dim="#95a0b3",
    accent="#0b8f6a",
    accent_hover="#0a7a5b",
    accent_text="#f8fffc",
    blue="#2f6fdb",
    gold="#a96b10",
    danger="#c0392b",
    danger_bg="#fdecea",
    ok_bg="#e4f5ec",
    warn_bg="#fdf3df",
    selected="#dbe7ff",
    selected_fg="#0f1726",
    hover="#e7edf7",
    row_alt="#f2f5fa",
    chip_max_bg="#fdf0d0",
    chip_min_bg="#fdeaea",
    chart_label="#fbfdff",
    series=(
        "#0b8f6a",
        "#2f6fdb",
        "#a96b10",
        "#c2185b",
        "#6b5bd2",
        "#0e7490",
        "#ea580c",
        "#4d7c0f",
        "#a21caf",
        "#2563eb",
        "#a16207",
        "#0f766e",
    ),
)

PALETTES: Dict[str, Palette] = {"dark": DARK, "light": LIGHT}
DEFAULT_THEME = "dark"

# 当前配色：换肤时就地更新这个对象，各模块持有同一个引用即可生效
C = SimpleNamespace(**{f.name: getattr(DARK, f.name) for f in fields(DARK)})
_current = DARK


def current() -> str:
    return _current.name


def current_palette() -> Palette:
    return _current


def palette(name: str) -> Palette:
    return PALETTES.get(name, DARK)


def switch(name: str) -> Dict[str, str]:
    """切换配色，更新 :data:`C`，返回旧色到新色的映射（键为小写十六进制）。"""
    global _current
    new = palette(name)
    old = _current
    if new is old:
        return {}
    mapping: Dict[str, str] = {}
    for f in fields(Palette):
        if f.name in ("name", "label"):
            continue
        old_value = getattr(old, f.name)
        new_value = getattr(new, f.name)
        if isinstance(old_value, str) and old_value.lower() != new_value.lower():
            # 同一旧色对应多个角色时以先出现者为准（调色板本身保证不会重复）
            mapping.setdefault(old_value.lower(), new_value)
    for i, old_value in enumerate(old.series):
        new_value = new.series[i % len(new.series)]
        if old_value.lower() != new_value.lower():
            mapping.setdefault(old_value.lower(), new_value)
    for f in fields(Palette):
        if f.name in ("name", "label"):
            continue
        setattr(C, f.name, getattr(new, f.name))
    _current = new
    return mapping


def configure_scrollbar(style, name: str) -> None:
    """统一暗/亮主题下滚动条的滑块、槽与禁用状态颜色。"""
    style.configure(
        name,
        background=C.card_alt,
        troughcolor=C.bg,
        bordercolor=C.bg,
        lightcolor=C.card_alt,
        darkcolor=C.card_alt,
        arrowcolor=C.muted,
        relief="flat",
        width=10,
    )
    style.map(
        name,
        background=[
            ("disabled", C.border),
            ("active", C.hover),
            ("pressed", C.card_alt),
        ],
        arrowcolor=[("disabled", C.dim), ("active", C.fg)],
    )


# 可重新上色的控件选项
_COLOR_OPTIONS = (
    "background",
    "foreground",
    "activebackground",
    "activeforeground",
    "highlightbackground",
    "highlightcolor",
    "insertbackground",
    "selectbackground",
    "selectforeground",
    "disabledforeground",
    "troughcolor",
    "readonlybackground",
)


def _walk(widget: tk.Misc):
    yield widget
    for child in widget.winfo_children():
        # 独立的 Toplevel 各自换肤，避免同一个映射被重复应用
        if isinstance(child, tk.Toplevel):
            continue
        yield from _walk(child)


def apply_to_widgets(root: tk.Misc, mapping: Dict[str, str]) -> None:
    """按映射把窗口内所有控件的颜色换成新主题。"""
    if not mapping:
        return
    for widget in _walk(root):
        for option in _COLOR_OPTIONS:
            try:
                value = widget.cget(option)
            except tk.TclError:
                continue
            if not isinstance(value, str):
                continue
            new_value = mapping.get(value.lower())
            if new_value is None:
                continue
            try:
                widget.configure(**{option: new_value})
            except tk.TclError:
                pass


# ---------------------------------------------------------------- 字体

UI_FONTS = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "PingFang SC",
    "Noto Sans CJK SC",
    "Source Han Sans SC",
    "WenQuanYi Micro Hei",
    "Segoe UI",
    "DejaVu Sans",
)

MONO_FONTS = (
    "Cascadia Mono",
    "Consolas",
    "JetBrains Mono",
    "DejaVu Sans Mono",
    "Courier New",
)


def pick_family(root: tk.Misc, candidates: Iterable[str] = UI_FONTS) -> str:
    """返回系统中第一个可用字体族，找不到就退回 Tk 默认字体。"""
    families = set(tkfont.families(root))
    for name in candidates:
        if name in families:
            return name
    return str(tkfont.nametofont("TkDefaultFont").actual("family"))
