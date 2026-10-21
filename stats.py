# -*- coding: utf-8 -*-
"""历史记录的统计聚合。

规则：``xDy`` 拆分成 ``x`` 个 ``1Dy`` 点数分别计数，固定修正值不参与统计。
统计只读取历史记录，不写任何文件。
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import dice
import history

__all__ = ["FaceStat", "Bin", "DieStats", "collect", "MAX_BARS"]

MAX_BARS = 100


@dataclass(frozen=True)
class FaceStat:
    face: int
    count: int
    ratio: float  # 0..1


@dataclass(frozen=True)
class Bin:
    label: str
    start: int  # 含
    end: int  # 含
    count: int
    ratio: float

    @property
    def width(self) -> int:
        return self.end - self.start + 1


@dataclass
class DieStats:
    sides: int
    counts: List[int]
    records_used: int = 0
    records_ignored: int = 0
    records_unverified: int = 0
    matched: List[history.Record] = field(default_factory=list)

    # ------------------------------------------------------------ 基本量

    @property
    def total(self) -> int:
        return sum(self.counts)

    @property
    def expected(self) -> float:
        return self.total / self.sides if self.sides else 0.0

    @property
    def expected_ratio(self) -> float:
        return 1.0 / self.sides if self.sides else 0.0

    @property
    def mean(self) -> float:
        if not self.total:
            return 0.0
        return sum((i + 1) * c for i, c in enumerate(self.counts)) / self.total

    @property
    def hottest(self) -> Optional[FaceStat]:
        faces = self.faces()
        if not faces or not self.total:
            return None
        return max(faces, key=lambda f: (f.count, -f.face))

    @property
    def coldest(self) -> Optional[FaceStat]:
        faces = self.faces()
        if not faces or not self.total:
            return None
        return min(faces, key=lambda f: (f.count, f.face))

    # ------------------------------------------------------------ 派生视图

    def faces(self) -> List[FaceStat]:
        total = self.total
        return [
            FaceStat(i + 1, c, (c / total) if total else 0.0)
            for i, c in enumerate(self.counts)
        ]

    def top(self, n: int = 10) -> List[FaceStat]:
        if n <= 0:
            return []
        return sorted(self.faces(), key=lambda f: (-f.count, f.face))[:n]

    def bins(self, max_bars: int = MAX_BARS) -> List[Bin]:
        """给柱状图用的分箱；面数超过 max_bars 时按区间合并。"""
        n = self.sides
        total = self.total
        if n <= max_bars:
            return [
                Bin(str(i + 1), i + 1, i + 1, c, (c / total) if total else 0.0)
                for i, c in enumerate(self.counts)
            ]
        size = math.ceil(n / max_bars)
        out: List[Bin] = []
        for start in range(0, n, size):
            end = min(n, start + size)
            count = sum(self.counts[start:end])
            label = str(start + 1) if end == start + 1 else f"{start + 1}-{end}"
            out.append(Bin(label, start + 1, end, count, (count / total) if total else 0.0))
        return out


def collect(
    records: Sequence[history.Record],
    sides: int,
    include_unverified: bool = False,
) -> DieStats:
    """把记录里所有 ``1Dsides`` 的点数抽出来计数。"""
    sides = int(sides)
    if sides < 1:
        raise ValueError("面数必须大于 0")

    stats = DieStats(sides=sides, counts=[0] * sides)
    for rec in records:
        if not rec.verified and not include_unverified:
            stats.records_unverified += 1
            continue
        try:
            expr = dice.parse(rec.notation)
        except dice.DiceError:
            stats.records_ignored += 1
            continue

        pos = 0
        used = False
        for term in expr.terms:
            values = rec.rolls[pos : pos + term.count]
            pos += term.count
            if term.sides != sides:
                continue
            for value in values:
                if 1 <= value <= sides:
                    stats.counts[value - 1] += 1
                    used = True
        if used:
            stats.records_used += 1
            stats.matched.append(rec)

    return stats
