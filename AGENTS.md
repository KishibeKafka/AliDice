# AGENTS.md

本文件面向在此仓库工作的 AI 代理（以及人类协作者）。请先读完再改代码。

## 项目定位

AliDice 是一个桌面骰子应用（Python 3.9+ / Tkinter / 纯标准库），支持 `xDx`
表达式，默认预设 1D100 与 1D10。所有投掷结果写入**只追加的二进制历史文件**，
已落盘的记录不可修改；任何改动都会在打开历史时被校验发现。

- 界面：`app.py`（`DiceApp(tk.Tk)`，深色单窗口）
- 主题：`theme.py`（暗/亮两套配色、运行时换肤、分类色、字体选择）
- 掷骰：`dice.py`（解析 + `SystemRandom` 投掷）
- 历史：`history.py`（二进制格式、HMAC 链、seal、追加句柄、归档）
- 统计：`stats.py`（`xDy` → `x` 个 `1Dy` 聚合、分箱、占比）、`stats_view.py`
  （统计窗口：分布表 + Canvas 手绘柱状图 / 饼图）
- 归档查看：`archive_view.py`（只读打开 `history-*.dat`，显示校验状态与记录）
- 工具：`verify.py`（只读校验）、`selftest.py`（自测）、`run.bat`（无控制台启动）

## 常用命令

```bash
python app.py                  # 启动界面
python selftest.py             # 自测，必须 69/69 通过
python verify.py               # 只读校验 data/history.dat
python verify.py --file data/history-20260510-120000.dat
python -m pyflakes *.py
python -m py_compile *.py
```

提交前固定跑：`selftest.py` + `pyflakes` + `py_compile`。

## 运行时文件（不要提交）

| 路径 | 说明 |
| --- | --- |
| `data/history.dat` | 历史数据，自动生成 |
| `data/history-*.dat` | 归档的历史（不删除，`verify.py --file` 可校验） |
| `data/error.log` | 界面回调异常日志 |
| `config.json` | 预设骰子 |
| `%LOCALAPPDATA%/AliDice/secret.bin` | 随机密钥（Windows；Linux 为 `~/.local/share/AliDice/`） |
| `%LOCALAPPDATA%/AliDice/seal.bin` | 当前链的锚（条数 + 链头 + file_id） |
| `%LOCALAPPDATA%/AliDice/seals/<file_id>.seal` | 每条历史自己的封印 |

## 架构与数据流

```
app.py ──dice.parse()──> DiceExpression ──roll()──> RollResult
   │                                                   │
   └────────────── store.append(notation, rolls, modifier) ──> history.Record
                              │
                     _AppendWriter(FILE_APPEND_DATA) ─> data/history.dat
                              └─ _seal() ─> seals/<file_id>.seal + seal.bin
```

- `HistoryStore.open()` 返回 `Report(state, message, record_count, head_tag, notes)`，
  `state ∈ {ok, empty, tampered, unverifiable}`；只有 `ok/empty` 允许追加。
- `HistoryStore.append()` 是**唯一**的历史写入口，写入后 `flush()` 并回读最后一条
  MAC 校验；失败则锁定报告。
- 界面层不直接碰文件，只调用 `store.append()`；历史列表为只读 `ttk.Treeview`。
- 统计窗口只读 `store.records`（跳过未校验记录），不写任何文件；主窗口掷骰或
  归档重置后会调用 `StatsWindow.refresh()`。
- 归档查看窗口通过 `HistoryStore.for_file(path)`（`read_only=True`）打开任意
  `history-*.dat`，只展示记录并校验，绝不写文件；主窗口负责在换肤时通知它。
- 主题：界面取色一律用 `theme.C.<角色>`（如 `C.bg`），不要写字面量颜色；
  换肤时 `theme.switch()` 就地更新 `C` 并返回“旧色→新色”映射，
  `theme.apply_to_widgets()` 给已有控件重新上色，统计窗口需要再 `_redraw()`。

## 不可违反的约束

1. **历史只追加**。不要新增任何“修改 / 删除 / 重排 / 压缩 / 清理 / 修复”历史文件的
   路径。需要重新开始时只能 `archive_and_reset()`（重命名归档后建新链）。
2. **`append()` 是唯一写入口**。不要用 `open(path, "wb"/"r+b")` 或普通 `O_APPEND`
   写数据文件；必须经由 `_AppendWriter`（Windows 下只申请 `FILE_APPEND_DATA`）。
3. **二进制格式改动必须升版本**（`FILE_VERSION` / `REC_VERSION`），同步更新
   `README.md` 的格式表，并让旧文件“可读或明确拒绝”。不得静默改变布局。
4. **每条记录必须**含连续 `index`、`prev_tag`、`tag = HMAC(key, "REC" | file_id |
   记录头 | payload)`，且 payload 内 `total == sum(rolls) + modifier`（读取时校验）。
5. **seal 必须双写**：`seals/<file_id>.seal`（用于归档文件独立校验）与 `seal.bin`
   （当前链锚，用于发现数据文件被整体删除）。缺一不可。
6. **密钥不得进入 `data/`，不得提交到仓库**；密钥派生必须包含机器指纹。
7. **校验失败必须锁定**：界面禁止掷骰，只能提示归档重置。不要提供“强制忽略校验”
   之类的开关。
8. **界面不得提供编辑/删除历史的能力**，包括右键菜单、快捷键、隐藏按钮。

## 已知平台陷阱（改代码前必读）

- Windows 下隐藏文件不能再被 `open(path, "wb")` 直接写（`ERROR_ACCESS_DENIED`）；
  写 `seal.bin` / `secret.bin` 必须走“临时文件 + `os.replace`”。
- `os.open()` 在 Windows 默认是文本模式，必须带 `os.O_BINARY`（`_AppendWriter`
  的非 Windows 回退已处理）。
- `_AppendWriter` 以“拒绝写入”方式共享文件：程序运行时其它进程写不进去。
  需要并发校验时用 `HistoryStore(..., read_only=True)`，它不会打开写句柄、
  也不会改写 seal。
- `wintypes.ULONGLONG` 不存在；`GetFileSizeEx` 用 `wintypes.LARGE_INTEGER`
  （`c_longlong`）。
- Tk 的 `<Configure>` 可能在控件创建前触发；`_on_*_card_configure` 里对
  `hint_label` / `detail_label` 用 `getattr(...)` 做了存在性保护，新增回调同理。
- 历史列表列宽由 `_fit_tree_columns()` 按窗口宽度压缩：窄窗口（920×620）下
  必须保证“时间”和“合计”列完整可见。

## 测试要求

- 改 `history.py`：`selftest.py` 必须全过；涉及新校验分支时补篡改用例
  （改字节、删尾部、删文件、跨文件拼接、改序号、换密钥、seal 落后/缺失）。
- 改 `dice.py`：补/改表达式合法性与边界用例。
- 改 `app.py`：至少启动一次并实际掷骰；建议在 920×620 与 1160×740 两种尺寸下检查
  布局（不要提交截图或用例生成的文件）。
- 改 `stats.py`：`selftest.py` 的“统计聚合”用例必须全过；新增聚合口径要补用例
  （拆骰、修正值、未校验、分箱、占比之和）。
- 改 `stats_view.py`：确认柱状图/饼图在 900×600 到 1100×720 下都不裁切图例，
  悬停提示与分布表数值一致；亮/暗两套主题下图表都清晰可读。
- 改 `theme.py`：`selftest.py` 的“主题”用例必须通过（角色唯一、换肤往返一致），
  并手动切换一次主题确认主窗口、统计窗口、归档窗口都完整换色。
- 改归档相关功能：`selftest.py` 的“归档文件打开”用例必须通过（`for_file` 只读、
  归档改动可检测），并确认打开归档不会修改文件或新建 seal。
- 新增依赖：不允许。运行时只用标准库（Pillow 仅供本地截图调试，默认不安装）。

## 编码约定

- 中文注释与中文界面文案；模块/函数 docstring 用中文。
- 类型注解 + `from __future__ import annotations`；行宽约 100。
- 颜色、字体常量集中在 `theme.py`，界面通过 `theme.C` 动态取色；图表分类色用
  `C.series`，不要写死新的十六进制颜色。
- 新增配色角色时必须让两套主题内**各角色颜色互不相同**（重复会导致换肤映射歧义，
  `selftest.py` 的“主题”用例会检查）；同时补齐 `apply_to_widgets` 依赖的颜色选项。
- 独立 `Toplevel`（统计、归档窗口）由自身 `apply_theme()` 换肤，`theme._walk` 不会
  递归进去，避免同一映射被应用两次；主窗口 `_apply_theme()` 负责逐个通知。
- `selftest.py` 用 `check(name, cond)` 输出，不引入 pytest。
- 保持 `pyflakes` 零告警。
- 统计只读：不要为了统计去改写历史、增加记录字段或改动二进制格式；
  `stats.py` 只依赖 `dice.parse()` 与 `Record.notation/rolls`。
- 复制文本统一走 `dice.bracket_text()`（`[3D10 = 3 + 6 + 9 = 18]`），不要在界面里
  另拼一套格式。

## 提交规范

Conventional Commits：`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`，
标题用中文、祈使语气，正文列要点。示例：

```
fix: 窄窗口下历史表“合计”列被裁剪

- 按 Treeview 实际宽度动态压缩列宽
- 保留时间与合计列的完整宽度
```

不要提交 `data/`、`config.json`、密钥、`__pycache__`（已在 `.gitignore` 中）。

## 安全边界（不要过度承诺）

机制目标是：**没有密钥/机器指纹的人无法在不被发现的情况下修改、删除、伪造或截断
历史**，且程序自身无法覆盖写已落盘字节。它不能防住同时拥有 `secret.bin`、
`seal.bin` 读写权限与机器控制权的攻击者；文档与 UI 文案不要宣称“绝对不可篡改”。
