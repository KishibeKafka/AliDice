# -*- coding: utf-8 -*-
"""命令行校验工具：只读检查历史完整性并打印记录。

用法::

    python verify.py                 # 最近 20 条
    python verify.py --tail 0        # 全部
    python verify.py --data-dir D:\\some\\data

退出码：0 = 校验通过；1 = 校验失败（不可校验 / 被改动 / 文件缺失）。
"""

from __future__ import annotations

import argparse
import os
import sys

import history as hist


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="校验 AliDice 历史文件（只读，不写入）")
    parser.add_argument("--data-dir", default=None, help="历史文件所在目录（默认 ./data）")
    parser.add_argument("--file", default=None, help="直接指定历史文件（例如归档的 history-*.dat）")
    parser.add_argument("--tail", type=int, default=20, help="打印最近 N 条，0 表示全部")
    args = parser.parse_args(argv)

    store = hist.HistoryStore(data_dir=args.data_dir, read_only=True)
    if args.file:
        store.data_dir = os.path.dirname(os.path.abspath(args.file))
        store.path = os.path.abspath(args.file)
    report = store.open()

    print(f"文件  : {store.path}")
    print(f"状态  : {report.state}（{report.message}）")
    print(f"记录  : {report.record_count} 条")
    print(f"链头  : {report.head_text}")
    for note in report.notes:
        print(f"说明  : {note}")
    if report.record_count:
        print("")

    records = store.records
    if args.tail and args.tail > 0:
        records = records[-args.tail :]
    for rec in records:
        flag = "OK " if rec.verified else "BAD"
        total = rec.total if (rec.verified or rec.rolls) else "?"
        print(
            f"[{flag}] #{rec.index:>4}  {rec.time_text}  {rec.notation:<16}"
            f"{total!s:>8}  {rec.rolls_text}"
        )
    store.close()

    ok = report.state in (hist.STATE_OK, hist.STATE_EMPTY)
    print("")
    print("校验通过：历史完整且未被改动。" if ok else "校验失败：历史不可信，请勿继续使用该文件。")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
