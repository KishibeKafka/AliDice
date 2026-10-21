# -*- coding: utf-8 -*-
"""核心逻辑自检：``python selftest.py``。

覆盖：表达式解析、复制格式、大成功判定、负值合计、追加入库、重开校验、各种篡改检测、归档重置、
归档文件读取、统计聚合、主题。
"""

from __future__ import annotations

import os
import shutil
import struct
import sys
import tempfile

import dice
import history
import stats
import theme


PASS = 0
FAIL = 0


def check(name: str, cond: bool, extra: str = "") -> None:
    global PASS, FAIL
    if cond:
        PASS += 1
        print(f"  [ok]   {name}")
    else:
        FAIL += 1
        print(f"  [FAIL] {name} {extra}")


def section(title: str) -> None:
    print(f"\n== {title} ==")


def make_store(root: str) -> history.HistoryStore:
    return history.HistoryStore(
        data_dir=os.path.join(root, "data"), key_path=os.path.join(root, "keys")
    )


def expr_tests() -> None:
    section("表达式解析")
    e = dice.parse("1d100")
    check("1D100 解析", e.text == "1D100" and e.dice_total == 1)
    check("省略数量 D6", dice.parse("d6").text == "1D6")
    check("带空格", dice.parse(" 3 d 6 ").text == "3D6")
    check("多组 + 修正", dice.parse("2d20+1d8-2").text == "2D20+1D8-2")
    check("纯修正值不合法", _err("3"))
    check("缺少面数", _err("2D"))
    check("负骰子组", _err("-2D6"))
    check("非法字符", _err("3D6x"))
    check("过多骰子", _err("1001D6"))

    result = dice.parse("1D100").roll()
    check("投掷范围", 1 <= result.total <= 100)
    res2 = dice.parse("2D20+1D8-2").roll()
    check("多组点数数量", len(res2.rolls) == 3)
    check("合计一致", res2.total == sum(res2.rolls) - 2)


def _err(text: str) -> bool:
    try:
        dice.parse(text)
    except dice.DiceError:
        return True
    return False


def copy_format_tests() -> None:
    section("复制格式")

    check("单骰", dice.bracket_text("1D100", [67]) == "[1D100 = 67]")
    check("单骰 1D10", dice.bracket_text("1D10", [1]) == "[1D10 = 1]")
    check("多骰", dice.bracket_text("3D10", [3, 6, 9]) == "[3D10 = 3 + 6 + 9 = 18]")
    check(
        "多骰带修正",
        dice.bracket_text("2D20+1D8-2", [17, 3, 5], -2)
        == "[2D20+1D8-2 = 17 + 3 + 5 - 2 = 23]",
    )
    check(
        "单骰带修正",
        dice.bracket_text("1D100+5", [95], 5) == "[1D100+5 = 95 + 5 = 100]",
    )
    check("空点数", dice.bracket_text("1D100", []) == "[1D100 = 0]")

    check("简版单骰", dice.result_text("1D10", [8]) == "1D10 = 8")
    check("简版多骰", dice.result_text("2D100", [33, 66]) == "2D100 = 33 + 66 = 99")
    check(
        "简版带修正",
        dice.result_text("2D20+1D8-2", [17, 3, 5], -2)
        == "2D20+1D8-2 = 17 + 3 + 5 - 2 = 23",
    )

    roll = dice.parse("3D10").roll()
    check(
        "与真实投掷一致",
        dice.bracket_text(roll.notation, roll.rolls, roll.modifier)
        == f"[{' + '.join(str(v) for v in roll.rolls)} = {roll.total}]".replace(
            "[", "[3D10 = ", 1
        ),
    )


def negative_total_tests(root: str) -> None:
    section("负值合计")

    sub = os.path.join(root, "neg")
    store = make_store(sub)
    store.open()
    rec = store.append("1D100-50", [3], -50)
    check("负合计写入", rec.total == -47, rec.total)
    rec2 = store.append("2D6-20", [2, 1], -20)
    check("负合计多骰", rec2.total == -17, rec2.total)
    store.close()

    store2 = make_store(sub)
    rep = store2.open()
    check("负合计重开校验", rep.state == history.STATE_OK, rep.message)
    check("负合计读回", [r.total for r in store2.records] == [-47, -17])
    store2.close()

    check(
        "负合计复制格式",
        dice.bracket_text("1D100-50", [3], -50) == "[1D100-50 = 3 - 50 = -47]",
    )
    st = stats.collect(
        [history.Record(0, 0, "1D100-50", (3,), -50, -47, b"", True)], 100
    )
    check("统计忽略修正值", st.total == 1 and st.counts[2] == 1)
    check(
        "非负合计编码与旧格式一致",
        struct.pack("<q", 87) == struct.pack("<Q", 87),
    )


def crit_tests() -> None:
    section("大成功判定")

    check("1D100 96 大成功", dice.crit_kind(96, 100) == dice.CRIT_SUCCESS)
    check("1D100 100 大成功", dice.crit_kind(100, 100) == dice.CRIT_SUCCESS)
    check("1D100 95 普通", dice.crit_kind(95, 100) == "")
    check("1D100 5 大失败", dice.crit_kind(5, 100) == dice.CRIT_FAILURE)
    check("1D100 6 普通", dice.crit_kind(6, 100) == "")
    check("1D20 19/20 大成功", all(dice.crit_kind(v, 20) == dice.CRIT_SUCCESS for v in (19, 20)))
    check("1D20 1 大失败", dice.crit_kind(1, 20) == dice.CRIT_FAILURE)
    check("1D6 6 大成功", dice.crit_kind(6, 6) == dice.CRIT_SUCCESS)
    check("1D10 1 不是大失败", dice.crit_kind(1, 10) == "")
    check(
        "1D1000 按比例",
        dice.crit_kind(50, 1000) == dice.CRIT_FAILURE
        and dice.crit_kind(950, 1000) == dice.CRIT_SUCCESS,
    )


def basic_flow(root: str) -> None:
    section("追加与重开校验")
    store = make_store(root)
    report = store.open()
    check("首次为空", report.state == history.STATE_EMPTY and report.can_append, report.state)

    rec1 = store.append("1D100", [87])
    rec2 = store.append("1D10", [4])
    rec3 = store.append("2D20+1D8-2", [17, 3, 5], modifier=-2)
    check("序号递增", [rec1.index, rec2.index, rec3.index] == [0, 1, 2])
    check("合计计算", rec3.total == 17 + 3 + 5 - 2)
    head = rec3.tag
    store.close()

    store2 = make_store(root)
    report = store2.open()
    check("重开后校验通过", report.state == history.STATE_OK and report.can_append, report.message)
    check("记录完整", [r.total for r in store2.records] == [87, 4, 23])
    check("合并明细保留", store2.records[2].rolls == (17, 3, 5))
    check("链头一致", report.head_tag == head)
    with open(store2.path, "rb") as fh:
        raw = fh.read()
    expect = history.FILE_HEADER_SIZE + sum(
        history.REC_HEADER_SIZE + _payload_len_from(raw, i) + history.TAG_SIZE for i in range(3)
    )
    check("文件长度符合二进制布局", len(raw) == expect, f"{len(raw)} != {expect}")
    store2.close()


def _payload_len_from(raw: bytes, index: int) -> int:
    pos = history.FILE_HEADER_SIZE
    for i in range(index + 1):
        _m, _idx, plen, _ts, _v, _r, _p = struct.unpack(
            history.REC_HEADER_FMT, raw[pos : pos + history.REC_HEADER_SIZE]
        )
        if i == index:
            return plen
        pos += history.REC_HEADER_SIZE + plen + history.TAG_SIZE
    return 0


def tamper_tests(root: str) -> None:
    section("篡改检测")

    # 1) 修改 payload 中的一个字节
    sub = os.path.join(root, "t1")
    store = make_store(sub)
    store.open()
    store.append("1D100", [56])
    store.append("1D100", [12])
    store.close()
    path = store.path
    raw = bytearray(open(path, "rb").read())
    target = history.FILE_HEADER_SIZE + history.REC_HEADER_SIZE + 12  # 第一条 payload 内
    raw[target] ^= 0xFF
    open(path, "wb").write(raw)
    s = make_store(sub)
    rep = s.open()
    check("改动字节被检测", rep.state == history.STATE_TAMPERED, rep.message)
    check("篡改后禁止追加", not s.can_append)
    check("篡改后 append 抛错", _append_fails(s))
    s.close()

    # 2) 截断尾部一条记录
    sub = os.path.join(root, "t2")
    store = make_store(sub)
    store.open()
    store.append("1D100", [11])
    store.append("1D100", [22])
    store.close()
    raw = open(store.path, "rb").read()
    tail = history.REC_HEADER_SIZE + _payload_len_from(raw, 1) + history.TAG_SIZE
    open(store.path, "wb").write(raw[:-tail])
    s = make_store(sub)
    rep = s.open()
    check("删除尾部记录被检测", rep.state == history.STATE_TAMPERED, rep.message)
    s.close()

    # 3) 删除数据文件
    sub = os.path.join(root, "t3")
    store = make_store(sub)
    store.open()
    store.append("1D10", [7])
    store.close()
    os.remove(store.path)
    s = make_store(sub)
    rep = s.open()
    check("删除历史文件被检测", rep.state == history.STATE_TAMPERED, rep.message)
    s.close()

    # 4) 从别的历史文件拼接记录
    sub_a = os.path.join(root, "t4a")
    sub_b = os.path.join(root, "t4b")
    a = make_store(sub_a)
    a.open()
    a.append("1D100", [99])
    a.close()
    b = make_store(sub_b)
    b.open()
    b.append("1D100", [1])
    b.close()
    raw_b = open(b.path, "rb").read()
    foreign = raw_b[history.FILE_HEADER_SIZE:]
    with open(a.path, "ab") as fh:
        fh.write(foreign)
    s = make_store(sub_a)
    rep = s.open()
    check("跨文件拼接被检测", rep.state == history.STATE_TAMPERED, rep.message)
    s.close()

    # 5) 换一套密钥（相当于挪到别的机器/篡改后重签）
    sub = os.path.join(root, "t5")
    store = make_store(sub)
    store.open()
    store.append("1D100", [42])
    store.close()
    shutil.rmtree(os.path.join(sub, "keys"))
    s = make_store(sub)
    rep = s.open()
    check("密钥不匹配为不可校验", rep.state == history.STATE_UNVERIFIABLE, rep.message)
    check("不可校验时禁止追加", not s.can_append)
    s.close()

    # 6) 正常记录不能被改写成"看似合法"的内容（MAC 绑定序号/链）
    sub = os.path.join(root, "t6")
    store = make_store(sub)
    store.open()
    store.append("1D100", [50])
    store.close()
    raw = bytearray(open(store.path, "rb").read())
    # 修改序号（重排/伪造）
    struct.pack_into("<I", raw, history.FILE_HEADER_SIZE + 4, 7)
    open(store.path, "wb").write(raw)
    s = make_store(sub)
    rep = s.open()
    check("改动序号被检测", rep.state == history.STATE_TAMPERED, rep.message)
    s.close()


def _append_fails(store: history.HistoryStore) -> bool:
    try:
        store.append("1D100", [1])
    except history.HistoryError:
        return True
    return False


def reset_tests(root: str) -> None:
    section("归档重置")
    sub = os.path.join(root, "r1")
    store = make_store(sub)
    store.open()
    store.append("1D100", [66])
    path = store.path
    archived = store.archive_and_reset()
    check("产生归档文件", bool(archived) and os.path.exists(archived), archived)
    check("原文件已重建", os.path.exists(path) and os.path.getsize(path) == history.FILE_HEADER_SIZE)
    check("重置后为空历史", store.report.state == history.STATE_EMPTY, store.report.state)
    store.append("1D10", [9])
    check("重置后可继续记录", store.report.state == history.STATE_OK and len(store.records) == 1)
    store.close()

    # 归档文件仍然可以独立校验（每条历史都有自己的 seal）
    ro = history.HistoryStore(
        data_dir=os.path.join(sub, "data"),
        key_path=os.path.join(sub, "keys"),
        read_only=True,
    )
    ro.path = archived
    rep = ro.open()
    check("归档文件可独立校验", rep.state == history.STATE_OK and rep.record_count == 1, rep.message)
    check("只读模式不追加", not ro.can_append)
    ro.close()


def archive_file_tests(root: str) -> None:
    section("归档文件打开")

    sub = os.path.join(root, "a1")
    store = make_store(sub)
    store.open()
    store.append("1D100", [88])
    store.append("3D6", [1, 2, 3])
    archived = store.archive_and_reset()
    store.close()

    keys = os.path.join(sub, "keys")
    ro = history.HistoryStore.for_file(archived, key_path=keys)
    rep = ro.open()
    check(
        "for_file 校验通过",
        rep.state == history.STATE_OK and rep.record_count == 2,
        rep.message,
    )
    check("for_file 只读", not ro.can_append)
    check("归档点数可读", ro.records[1].rolls == (1, 2, 3))
    ro.close()

    missing = history.HistoryStore.for_file(
        os.path.join(sub, "data", "nope.dat"), key_path=keys
    )
    rep2 = missing.open()
    check("缺失文件报告异常", rep2.state == history.STATE_TAMPERED, rep2.message)
    missing.close()

    # 归档文件被改动后同样能被发现
    raw = bytearray(open(archived, "rb").read())
    raw[history.FILE_HEADER_SIZE + history.REC_HEADER_SIZE + 6] ^= 0x7F
    open(archived, "wb").write(raw)
    broken = history.HistoryStore.for_file(archived, key_path=keys)
    rep3 = broken.open()
    check("归档改动可检测", rep3.state == history.STATE_TAMPERED, rep3.message)
    broken.close()


def crash_safety_tests(root: str) -> None:
    section("seal 落后自动追平")
    sub = os.path.join(root, "c1")
    store = make_store(sub)
    store.open()
    store.append("1D100", [1])
    store.close()
    # 模拟"数据已写但 seal 未更新"：把 seal 回滚成 0 条（用同一密钥重签，模拟崩溃现场）
    seal_path = os.path.join(sub, "keys", "seal.bin")
    probe = make_store(sub)
    probe._load_secret()
    file_id = open(probe.path, "rb").read()[12:28]
    mac = history._mac(probe._key, b"SEAL", file_id, struct.pack("<I", 0), history.ZERO_TAG)
    probe.close()
    blob = struct.pack(
        history.SEAL_FMT,
        history.SEAL_MAGIC,
        history.SEAL_VERSION,
        0,
        0,
        file_id,
        history.ZERO_TAG,
        mac,
    )
    with open(seal_path + ".new", "wb") as fh:
        fh.write(blob)
    os.replace(seal_path + ".new", seal_path)
    check("旧 seal 被自动追平", make_check_seal_tail(sub))


def make_check_seal_tail(sub: str) -> bool:
    store = make_store(sub)
    rep = store.open()
    ok = rep.state == history.STATE_OK and any("seal" in n for n in rep.notes)
    store.close()
    return ok


def stats_tests() -> None:
    section("统计聚合")

    def rec(idx, notation, rolls, modifier=0, verified=True):
        return history.Record(
            idx, 0, notation, tuple(rolls), modifier, sum(rolls) + modifier, b"", verified
        )

    records = [
        rec(0, "3D6", (1, 2, 3)),
        rec(1, "2D6+1", (6, 6), 1),
        rec(2, "1D100", (42,)),
        rec(3, "2D100+1D10", (100, 1, 7)),
        rec(4, "1D6", (6,), verified=False),
    ]

    s6 = stats.collect(records, 6)
    check("3D6 拆成 3 个 1D6", s6.total == 5, s6.total)
    check("1D6 计数正确", s6.counts == [1, 1, 1, 0, 0, 2], s6.counts)
    check("修正值不参与统计", s6.counts[5] == 2)
    check("未校验记录默认跳过", s6.records_unverified == 1)
    check("可包含未校验记录", stats.collect(records, 6, include_unverified=True).total == 6)
    check("matched 记录匹配同面数", [r.index for r in s6.matched] == [0, 1])

    s100 = stats.collect(records, 100)
    check("多组拆解只取同面数骰子", s100.total == 3, s100.total)
    check("matched 包含多组记录", [r.index for r in s100.matched] == [2, 3])
    check("最高/最低点计数", s100.counts[99] == 1 and s100.counts[0] == 1)

    check("占比之和为 1", abs(sum(f.ratio for f in s6.faces()) - 1.0) < 1e-9)
    check("平均值", abs(s6.mean - (1 + 2 + 3 + 6 + 6) / 5) < 1e-9)
    check("分箱总和等于总数", sum(b.count for b in s100.bins(10)) == s100.total)

    empty = stats.collect([], 100)
    check("空历史", empty.total == 0 and empty.hottest is None and empty.mean == 0.0)

    bad = stats.collect([rec(0, "??", (1,))], 6)
    check("无法解析的记录被忽略", bad.total == 0 and bad.records_ignored == 1)

    big = stats.collect([rec(0, "1D1000", (1000,))], 1000)
    bins = big.bins(100)
    check("大面数分箱数量", len(bins) == 100, len(bins))
    check("大面数分箱覆盖完整", bins[0].start == 1 and bins[-1].end == 1000)
    check("大面数分箱总和", sum(b.count for b in bins) == 1)

    hot = stats.collect([rec(0, "1D6", (6, 6, 6))], 6)
    check("最常见/最少见点数", hot.hottest.face == 6 and hot.coldest.face == 1)


def theme_tests() -> None:
    section("主题")

    from dataclasses import fields as dc_fields

    for name, palette in theme.PALETTES.items():
        seen = {}
        duplicates = []
        for f in dc_fields(theme.Palette):
            if f.name in ("name", "label", "series"):
                continue
            value = getattr(palette, f.name).lower()
            if value in seen:
                duplicates.append(f"{f.name} 与 {seen[value]}")
            seen[value] = f.name
        check(f"{name} 配色角色不重复", not duplicates, ", ".join(duplicates))

    def snapshot():
        return {
            f.name: getattr(theme.C, f.name)
            for f in dc_fields(theme.Palette)
            if f.name not in ("name", "label", "series")
        }

    original = theme.current()
    before = snapshot()
    mapping = theme.switch("light" if original == "dark" else "dark")
    check("换肤返回颜色映射", bool(mapping))
    check("切换后当前主题", theme.current() != original)
    theme.switch(original)
    check("换肤往返一致", snapshot() == before)


def main() -> int:
    root = tempfile.mkdtemp(prefix="alidice-selftest-")
    try:
        expr_tests()
        copy_format_tests()
        crit_tests()
        negative_total_tests(root)
        basic_flow(root)
        tamper_tests(root)
        reset_tests(root)
        archive_file_tests(root)
        crash_safety_tests(root)
        stats_tests()
        theme_tests()
    finally:
        shutil.rmtree(root, ignore_errors=True)
    print(f"\n结果：{PASS} 通过 / {FAIL} 失败")
    return 1 if FAIL else 0


if __name__ == "__main__":
    sys.exit(main())
