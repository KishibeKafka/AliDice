# -*- coding: utf-8 -*-
"""骰子表达式解析与投掷。

支持的语法（大小写不敏感，允许空格）::

    xDy            投 x 个 y 面骰（x 省略时为 1）
    xDy + k        带固定修正值
    xDy + aDb - k  多个骰子组相加

示例：``1D100``、``3D6``、``2D20 + 1D8 - 2``。
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from typing import Optional, Sequence, Tuple

__all__ = [
    "DiceError",
    "DiceTerm",
    "DiceExpression",
    "RollResult",
    "parse",
]

MAX_DICE_PER_TERM = 1000
MAX_TOTAL_DICE = 1000
MAX_SIDES = 1_000_000
MAX_TERMS = 32
MAX_MODIFIER = 1_000_000
MAX_TEXT_LEN = 120

_rng = random.SystemRandom()


class DiceError(ValueError):
    """表达式不合法（给用户看的错误）。"""


@dataclass(frozen=True)
class DiceTerm:
    count: int
    sides: int

    def text(self) -> str:
        return f"{self.count}D{self.sides}"


@dataclass(frozen=True)
class DiceExpression:
    terms: Tuple[DiceTerm, ...]
    modifier: int
    text: str

    @property
    def dice_total(self) -> int:
        return sum(t.count for t in self.terms)

    def roll(self, rng: Optional[random.Random] = None) -> "RollResult":
        rng = rng or _rng
        groups = []
        rolls = []
        for term in self.terms:
            values = tuple(rng.randint(1, term.sides) for _ in range(term.count))
            groups.append((term, values))
            rolls.extend(values)
        return RollResult(
            expression=self,
            groups=tuple(groups),
            rolls=tuple(rolls),
            modifier=self.modifier,
            total=sum(rolls) + self.modifier,
        )


@dataclass(frozen=True)
class RollResult:
    expression: DiceExpression
    groups: Tuple[Tuple[DiceTerm, Tuple[int, ...]], ...]
    rolls: Tuple[int, ...]
    modifier: int
    total: int

    @property
    def notation(self) -> str:
        return self.expression.text

    def breakdown(self) -> str:
        """例如 ``17 + 2D6(3,4) = 17``。"""
        parts = []
        for term, values in self.groups:
            if len(values) == 1:
                parts.append(f"{term.text()}({values[0]})")
            else:
                parts.append(f"{term.text()}({','.join(map(str, values))})")
        if self.modifier:
            parts.append(f"{self.modifier:+d}")
        return " + ".join(parts) + f" = {self.total}"


def _canonical(terms: Sequence[DiceTerm], modifier: int) -> str:
    text = "+".join(t.text() for t in terms)
    if modifier > 0:
        text += f"+{modifier}"
    elif modifier < 0:
        text += f"-{-modifier}"
    return text


def parse(text: str) -> DiceExpression:
    """解析 ``xDx`` 表达式，失败时抛出 :class:`DiceError`。"""
    if not isinstance(text, str):
        raise DiceError("表达式必须是文本")
    compact = re.sub(r"\s+", "", text).upper()
    if not compact:
        raise DiceError("请输入骰子表达式，例如 3D6 或 1D100")
    if len(compact) > MAX_TEXT_LEN:
        raise DiceError("表达式过长")

    terms = []
    modifier = 0
    dice_total = 0
    i = 0
    first = True

    while i < len(compact):
        sign = 1
        if compact[i] in "+-":
            sign = -1 if compact[i] == "-" else 1
            i += 1
            if i >= len(compact):
                raise DiceError("表达式不能以 + 或 - 结尾")
        elif not first:
            raise DiceError(f"第 {len(terms) + 1} 项前缺少 + 或 -")

        start = i
        while i < len(compact) and compact[i].isdigit():
            i += 1
        count_str = compact[start:i]

        if i < len(compact) and compact[i] == "D":
            i += 1
            if sign < 0:
                raise DiceError("骰子组不能为负，负号请用于固定修正值，例如 3D6-2")
            sides_start = i
            while i < len(compact) and compact[i].isdigit():
                i += 1
            sides_str = compact[sides_start:i]
            if not sides_str:
                raise DiceError("D 之后需要写面数，例如 1D100")
            sides = int(sides_str)
            count = int(count_str) if count_str else 1
            if count < 1:
                raise DiceError("骰子数量必须大于 0")
            if count > MAX_DICE_PER_TERM:
                raise DiceError(f"单个骰子组最多 {MAX_DICE_PER_TERM} 个骰子")
            if not 1 <= sides <= MAX_SIDES:
                raise DiceError(f"面数必须在 1 到 {MAX_SIDES} 之间")
            if len(terms) + 1 > MAX_TERMS:
                raise DiceError(f"最多 {MAX_TERMS} 个骰子组")
            dice_total += count
            terms.append(DiceTerm(count, sides))
        else:
            if not count_str:
                raise DiceError(f"无法识别：{compact[i:i + 8] or compact}")
            value = int(count_str)
            if value > MAX_MODIFIER:
                raise DiceError(f"修正值不能超过 {MAX_MODIFIER}")
            modifier += sign * value

        first = False
        if i < len(compact) and compact[i] not in "+-":
            raise DiceError(f"无法识别：{compact[i:i + 8]}")

    if not terms:
        raise DiceError("表达式里至少要有一个骰子组，例如 1D100")
    if dice_total > MAX_TOTAL_DICE:
        raise DiceError(f"一次最多投 {MAX_TOTAL_DICE} 个骰子")
    if abs(modifier) > MAX_MODIFIER:
        raise DiceError(f"修正值不能超过 {MAX_MODIFIER}")

    return DiceExpression(tuple(terms), modifier, _canonical(terms, modifier))
