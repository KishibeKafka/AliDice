# -*- coding: utf-8 -*-
"""共享主题：配色常量与字体选择（主窗口、统计窗口共用）。"""

from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont
from typing import Iterable, Tuple

# ---------------------------------------------------------------- 配色

BG = "#0e1016"
CARD = "#181c26"
CARD_ALT = "#1e2330"
FIELD = "#202634"
BORDER = "#2b3242"
FG = "#e9edf6"
MUTED = "#8b95a8"
DIM = "#5b6478"
ACCENT = "#5ee0b0"
ACCENT_HOVER = "#7cf0c6"
BLUE = "#7aa2ff"
GOLD = "#ffcf6b"
DANGER = "#ff6b6b"
DANGER_BG = "#3a1f24"
OK_BG = "#17362c"
WARN_BG = "#3a3021"

# 图表分类色（深色背景上可辨识，按顺序循环使用）
SERIES: Tuple[str, ...] = (
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
)

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
