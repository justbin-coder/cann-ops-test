---
name: ops-test
description: 用于 CANN 算子示例跑测（examples：build → install → 真机跑算子示例）——任意 ops 仓中目标算子的 build/install/run/诊断，覆盖单算子、单仓全量、多仓并发场景，并生成跑测报告。涉及 build.sh / 跑测脚本命令、SOC 名称（ascend910b / ascend950 等）、跑测 / 续跑 / 诊断 / 重测、950 特性（hif8 / simt / regbase）等用户意图时必须激活本 skill 再行动。
---

# cann-ops:ops-test

CANN 算子跑测的决策大脑。**只要任务涉及算子 build / install / run / 诊断（无论是否带 950 关键词），必须激活本 skill 再行动。**

**目标算子来源（多源）**：
- 用户在请求里直接列出（自然语言）→ skill 转 `--ops op1,op2,...` 传给 runner
- 用户给一个清单文件 → skill 转 `--ops-file <path>` 传给 runner
- 默认回退到 `cann-ops:scann-repo` 的产物 `CWD/cann-ops-report/scann/<repo>/_intermediate.json`

**SOC 来源**：每次会话由 skill 询问用户得到（如 `ascend910b` / `ascend950`），不再硬编码。

**输出路径**：所有运行产物写到用户当前工作目录（CWD）的 `cann-ops-report/test/` 子目录：
- `CWD/cann-ops-report/test/run_state.json` — 算子跑测状态
- `CWD/cann-ops-report/test/SUMMARY.md` — 每轮跑完自动生成的简洁摘要（多仓各一行 + 失败明细，给人看）
- `CWD/cann-ops-report/test/logs/` — 每个算子的 build/install/run 日志
- `CWD/cann-ops-report/test/PHASE{N}_FINAL_REPORT.md` — 最终报告（仅用户要求时生成）

## 强制激活规则（不可绕过）

凡是触发以下任意一种意图，**禁止**直接调用 `bash build.sh`、`scripts/phase_*.py`、`build_out/*.run` 或自写并发脚本，**必须**先按本 skill 的工作流执行：

- 跑测（"跑测 / 跑 / 验证 / 测试"）+ 任意 ops 仓 / 任意目标算子 / 示例跑测（examples，历史名 phase1）
- 续跑 / 重跑 / 修复后重测失败算子
- 诊断（"诊断 / 看下为什么失败 / 分析失败"）某个算子的失败日志
- 批量跑某个仓全部目标算子 / 多仓并发跑测
- 生成 / 输出 / 整理跑测报告（Phase X 跑测结束后的最终汇总）

如果不确定是否触发，按"触发"处理。先激活 skill，再行动。

## 前置环境节点（每次跑测必须先做）

### P0 — 发现并确认目标仓（中文交互）

激活后**第一步**：在 CWD 下扫描已被 scann-repo 处理过的仓——找 `CWD/cann-ops-report/scann/*/_intermediate.json` 存在的子目录，每个就是一个候选仓名。

按下面三种情况之一处理：

1. **用户已经明确给了仓名 + 路径**（例如"跑 ops-transformer，路径在 /data/cann/ops-transformer"）
   → 直接使用用户给的，不再问。

2. **用户只说"跑测 / 跑某个仓"，没给路径**
   → 在 CWD 下扫候选仓，把发现结果用中文呈现给用户确认：

   ```
   我在当前工作目录下发现这些已扫描的仓：
     1. ops-transformer  ← cann-ops-report/scann/ops-transformer/_intermediate.json 存在
     2. ops-cv           ← cann-ops-report/scann/ops-cv/_intermediate.json 存在
   还需要每个仓的本地源码路径才能跑测。请确认或补充：
     - ops-transformer：本地源码路径？
     - ops-cv：本地源码路径？
   ```
   用 `AskUserQuestion` 收集仓名 → 路径映射。

3. **CWD 下没有 cann-ops-report/scann/ 目录**
   → 见 P0.5 第 ② 分支处理。

**仓名约束**：完全自由字符串，不再有"四仓"或硬编码列表。用户写什么就用什么（vendor_name 由仓名自动派生：`ops-X` → `custom_X`）。

**仓路径约束**：必须是绝对路径或相对 CWD 的可解析路径，并且目录里有 `build.sh`。

### P0.5 — 确定目标算子来源（中文交互）

P0 确定仓后，**对每个目标仓**走下面的目标算子来源分支：

#### ① CWD 下检测到该仓的 scann 产物（`cann-ops-report/scann/<repo>/_intermediate.json`）

用 `AskUserQuestion` 询问：

```
ops-transformer 已经被 scann-repo 扫描过（产出 N 个目标算子）。请选择：
  A. 跑这 N 个算子（推荐）
  B. 我自己指定要跑的算子（接下来给我列表或文件）
```

- 选 A → 不传 `--ops`，让 runner 默认从 `_intermediate.json` 读
- 选 B → 让用户列算子名（自然语言或粘贴），整理为 CSV 后用 `--ops op1,op2,...` 传给 runner

#### ② CWD 下没有该仓的 scann 产物

用 `AskUserQuestion` 询问：

```
ops-transformer 还没被 scann-repo 扫描过。请选择：
  A. 先调用 cann-ops:scann-repo 扫描这个仓，然后跑扫出的目标算子
  B. 我自己指定要跑的算子（接下来给我列表或文件）
```

- 选 A → **激活 cann-ops:scann-repo 完成扫描** → 回到 P0.5 ①
- 选 B → 让用户列算子名 / 给文件路径

#### 整理算子来源到 CLI 参数

- 用户列出算子（CSV 或自然语言"跑 op1、op2 和 op3"）→ `--ops op1,op2,op3`
- 用户给文件路径 → `--ops-file <path>`（支持 `.json` 含 `unique_targets` / 顶层 list / 一行一算子的纯文本）
- 用 scann 产物 → 不传 `--ops` / `--ops-file`，runner 自动 fallback 到 `_intermediate.json`

### P1 — 询问用户 SOC（中文交互）

如果用户在请求里没明示 SOC（如"对 ascend910b 跑测"），skill 必须用 `AskUserQuestion` 询问：

```
请告诉我目标 SOC 名称：
  - ascend910b
  - ascend950
  - ascend310p
  - 其它（请输入）
```

收集到的 SOC 字符串后续作为 `--soc <soc>` 传入所有 runner 脚本。**不假设默认值**，必须用户确认。

### P2 — CANN 环境

`ASCEND_HOME_PATH` 由 CANN toolkit 安装时自动设置，`scripts/utils.py:run_cmd()` 从中推导 `set_env.sh` 并自动 source，无需用户操作。若 `ASCEND_HOME_PATH` 未设置，说明 CANN toolkit 未安装，提示用户先安装。

## 工作流（含并发拓扑）

### 并发拓扑

| 场景 | 仓间并发 | 仓内并发 | 入口脚本 | 加速比 |
|---|:---:|---|---|:---:|
| **A. 多仓全量示例跑测** | N worker ProcessPool | 合并 build（`--ops=op1,...,opN`）+ 串行 install + 逐个 run_example | `scripts/run_phase1_batched.py` | 6-10× |
| **B. 单仓全量示例跑测** | — | 同上合并 build | `scripts/run_phase1_batched.py`（mapping 只填一项） | 3-5× |
| **C. 单算子示例跑测** | — | 单算子三步 | `scripts/phase_examples.py --op <name>` | 1× |

> 「示例跑测（examples）」= build → install → 真机逐算子跑 `examples/test_aclnn_*.cpp`，即历史命名的 phase1（状态文件 `run_state.json` 中仍用 `phase1` 键，保持兼容）。

**禁止**：通过 `phase_examples.py --op` 起多进程跑同仓多算子（CMakeCache.txt 冲突）。

### 合并 Build 连坐恢复

当 batched run 中一个算子编译失败导致全批连坐，用单算子兜底跑测还原真实状态：

```bash
python3 scripts/run_phase1_fallback.py \
  --repo-mapping <repo1>=<path1>,<repo2>=<path2>,... \
  --soc <soc> \
  [--statuses BUILD_FAIL,INSTALL_FAIL]
```

## Phase 路由表

仓路径用 `--repo-mapping repo1=path1,repo2=path2,...` 显式传入（来自 P0）。
SOC 用 `--soc <soc>` 传入（来自 P1）。
目标算子用 `--ops` / `--ops-file` 传入或 fallback（来自 P0.5）。

| 用户意图 | 入口命令 |
|---|---|
| 多仓全量示例跑测 | `python3 scripts/run_phase1_batched.py --repo-mapping <r1>=<p1>,... --soc <soc> [--ops <csv> \| --ops-file <path>]` |
| 单仓全量示例跑测 | `python3 scripts/run_phase1_batched.py --repo-mapping <repo>=<path> --soc <soc> [--ops <csv> \| --ops-file <path>]` |
| 单算子示例跑测 | `python3 scripts/phase_examples.py --repo <name> --repo-path <path> --soc <soc> --op <op> [--ops <csv> \| --ops-file <path>]` |
| 合并 build 连坐兜底 | `python3 scripts/run_phase1_fallback.py --repo-mapping <r1>=<p1>,... --soc <soc>` |
| 生成跑测报告 | 见下方「最终报告生成」节 |

<!-- 以下阶段暂不开放，占位保留（脚本在 scripts/ 下，待各 ops 仓 build.sh 能力对齐后恢复）：
| Phase 2 OpKernel UT | `python3 scripts/phase_kernel_ut.py --repo <name> --repo-path <path> --soc <soc> [--ops <csv> \| --ops-file <path>]` |  ← 依赖 build.sh --opkernel_test，部分仓（如 ops-cv）不支持
| Phase 3 Pytest | `python3 scripts/phase_pytest.py --repo <name> --repo-path <path> [--ops <csv> \| --ops-file <path>]` |  ← 依赖 per-op pytest 工程
| Phase 4 msprof | `python3 scripts/phase_msprof.py --repo <name> --repo-path <path> [--ops <csv> \| --ops-file <path>]` |
-->

> 跑测范围当前仅「示例跑测」。涉及 kernel UT / pytest / msprof 的请求暂不受理，提示用户该阶段未开放。

## 启动协议

1. **激活确认**：声明 "Using cann-ops:ops-test"，列出范围（仓 / 算子）和并发拓扑（A/B/C）
2. **P0 发现/询问**：拿到 `{repo: path}` 映射并向用户确认（中文）
3. **P0.5 算子来源**：对每个仓决定 ops 来源（scann / 用户列举 / 文件）
4. **P1 询问 SOC**：用 `AskUserQuestion` 收集 SOC 字符串
5. **P2 状态检查**：读 `CWD/cann-ops-report/test/run_state.json`，识别已 PASS 与 SKIPPED 算子（续跑跳过）
6. **环境就绪**：runner 内部已强制 source set_env.sh，无需用户操作
7. **执行**：起后台任务，日志 tail 到 `/tmp/phase1_*.log`
8. **报告**：跑完后输出每仓 PASS/FAIL 汇总，按需生成最终报告

## 实时进度输出

**Per repo**：`[{repo}] {N_pass}/{N_total} PASS, build={s}s, install={s}s, run={s}s`

**Per op**：`[{repo}] [i/N] {symbol} {op}: {status}`

**续跑**：已 PASS 的算子跳过；BUILD_FAIL/INSTALL_FAIL 自动重试，`attempts` 字段累加。

## 最终报告生成（示例跑测全部完成后）

**触发条件**：跑测全部完成 + 用户要求"生成报告"。不要在中途生成。

**产出路径**：`CWD/cann-ops-report/test/PHASE{N}_FINAL_REPORT.md`

**数据来源**（按优先级）：
1. `CWD/cann-ops-report/test/run_state.json` — 算子 × phase × status × duration_s（权威）
2. `CWD/cann-ops-report/test/logs/<repo>/<op>.phase{N}.{step}.log` — 真实错误信息摘录
3. `CWD/cann-ops-report/scann/<repo>/_intermediate.json` — 950 特性命中数据（**若用户没扫描就跳过此数据源**）
4. `CWD/cann-ops-report/test/phase{N}_*_report.json` — 过程性 JSON

**必备 6 大模块**（顺序固定）：

| # | 模块 | 关键内容 |
|---|------|---------|
| I | 执行摘要 | 一句话结论 + 关键数字表 + 三大发现 + 950 特性覆盖矩阵（若有 scann）+ P1/P2/P3 计划 |
| II | 按仓成绩单 | 每仓 × 6 列汇总表（PASS/各类失败/通过率）+ 状态注脚 |
| III | 失败算子分类诊断 | BUILD_FAIL / RUN_EXIT_FAIL / RUN_PATTERN_FAIL 三张表，每行含：仓 / 算子 / 耗时 / 950 特性（若有 scann）/ **真实错误日志摘录** / 根因诊断 / **复现命令** / **诊断步骤 ①②③** |
| IV | PASS 算子汇总 | 按仓列举（含耗时/特性/特点）+ 多规则命中基准表（若有 scann） |
| V | 950 特性覆盖矩阵 | 按规则统计（覆盖率/信号强度）+ 仓级热力图 + 关键发现（**仅当用户跑过 scann 时输出，否则跳过本节**） |
| VI | 构建优化建议 | 超长编译（≥900s）处理 + BUILD_FAIL 代码瘦身 + 并发策略改进 |
| 附录 | 完整算子清单 | 每仓所有算子 × 状态 × 耗时 × 特性（若有）× 日志路径 |

**关键约束**（必须满足）：

1. **失败算子三要素**：① 真实错误（grep 日志，不可凭空推断）② 完整复现命令（cd <abs-path> && bash build.sh ...）③ 带序号诊断步骤 ①②③
2. **超长编译标记**：耗时 ≥900s 标 `⚠️ TIMEOUT`
3. **耗时落表**：PASS 算子也带耗时
4. **950 特性关联**：若 scann 产物存在则标注 hif8/simt/regbase，**不存在则在该列写"—"，不要捏造**
5. **不凭空推断**：日志没有的标 `(推断)` 与真实摘录严格区分
6. **复现命令完整**：不留省略号

**生成流程**：
1. 读 `run_state.json` → 按 repo × status 分组
2. 抽样读 5-10 个失败日志，grep `ERROR\|undefined\|failed\|exit=` 提取真实报错
3. **若 scann 产物存在** → 读 `_intermediate.json` 关联 950 特性；不存在则该维度空缺
4. AskUserQuestion 确认报告用途 + 格式 + 核心模块
5. **先输出大纲预案，用户审视后再落盘**
6. Write `CWD/cann-ops-report/test/PHASE{N}_FINAL_REPORT.md`

## 失败诊断

用户说"诊断 {op}"时：

1. 读 `CWD/cann-ops-report/test/run_state.json` → 找该算子的 status / log_path
2. 读 build/install/run 日志
3. 读算子源码 `<repo>/<category>/<op>/`
4. 输出诊断到 `CWD/cann-ops-report/test/failures/<repo>/{op}.md`：根因 + 排查建议
5. **不修源码、不改测试**

## P5.5 — FAQ Lookup（失败后自动触发）

每次跑测完成、写完失败诊断后，对所有 status ∈ {BUILD_FAIL, INSTALL_FAIL, RUN_EXIT_FAIL, RUN_PATTERN_FAIL} 的算子执行：

```python
from scripts.faq_lookup import lookup_all_failed

failed_ops = [
    {"repo": repo, "op": op, "failure_type": status, "log_path": log_path}
    for repo, op, status, log_path in failed_list
]
hits = lookup_all_failed(failed_ops)
```

- `hits` 为空 → 静默，不打印任何内容。
- `hits` 非空 → 用 `AskUserQuestion` 提示：

  ```
  X 个失败算子在 FAQ 命中已知修复方案，要应用并重试吗？
    1. ops-transformer / grouped_matmul  → [env] ASCEND_GLOBAL_LOG_LEVEL=1（来源：<issue_url>）
    2. ops-cv / resize_bilinear_v2       → [build_flag] -DCMAKE_BUILD_TYPE=Debug
    A. 全部应用并重试
    B. 选择部分（请告诉我编号）
    C. 跳过
  ```

用户选 A 或 B → 对每个命中算子调 `retest_orchestrator.retest()`（来自 track-issues skill 的共享脚本）。

**重要约束**：
- `patch` 类 fix 不在此处自动应用（避免意外修改工作区），仅在汇总里提示「FAQ 中有源码修复方案，可用 `cann-ops:track-issues` 处理」。
- faq_lookup 内部 NEVER raise（任何异常静默 return None），不影响主跑测流程。

## P5.7 — 自动续跑（跑测完成且有 FAIL 时自动触发）

跑测结束、FAQ 未命中时,**不等用户指令**,自动对全部 FAIL 算子续跑一轮(`--ops` 只传失败项,PASS 不重跑):
- 复测仍 FAIL → 确定性确认,直接进 P6
- 复测翻盘 PASS → 标记偶发,记入汇总,不进 P6
- 只续跑 1 轮,不无限循环

## P6 — 失败算子自主探索修复（P5.7 确认确定性后进入）

**前置条件**（全部满足才进入）：
1. 算子失败已被复测确认（同一失败 ≥2 次,P5.7 自动完成）
2. P5.5 FAQ lookup 未命中（已知方案优先）
3. 用户同意进入探索（用 `AskUserQuestion` 列出失败算子，问哪些要探索;同仓同批失败一次确认即可,不必每轮重问）

**目标**：agent 自主定位根因并尝试修复；**无论成败，过程与结论都沉淀为 issue 材料**——成功 → issue 附「已验证修复方案」（高价值）；失败 → issue 附「已排除路径」（同样有价值）。

**探索流程**（每算子独立，按成本从低到高，每层验证后再升级）：

1. **读证据**：失败日志 + 算子源码（op_kernel/op_host/op_api）+ examples + 对照同类 PASS 算子（如失败的 resize_bicubic 对照 PASS 的 resize_bilinear）
2. **形成假设**：缺符号→查 vendor lib 导出与示例链接名；运行错→查 errcode 含义/输入构造；缺示例→对照同类算子的示例改写
3. **低成本验证**：环境变量 / build 参数 / 命令行变体（不动文件）
4. **源码级验证**：在 `git -C <repo> switch -c explore-<op>` 临时分支改示例或源码 → 复测 → **无论结果切回原分支**，diff 存档
5. **预算**：单算子最多 5 次验证，超出即收档止损

**产物**：
- `CWD/cann-ops-report/test/explorations/<repo>/<op>.md`：根因 / 尝试1..N / 结论（SOLVED + diff/方案 或 UNSOLVED + 已排除清单）
- 状态 `EXPLORED_SOLVED / EXPLORED_UNSOLVED` 写入 run_state（不覆盖原始失败 status）
- report-issues 起草时自动引用本目录

**红线**：临时分支不合并、跑完必恢复现场；不动 PASS 算子;NPU 串行。

## 边界与禁忌

- ✗ 不直接调 `bash build.sh` / 起多进程跑同仓多算子
- ✗ 不修改算子源码 / examples / pytest 用例（**唯一例外**：P6 探索的临时分支内,跑完恢复现场）
- ✗ 不假设 SOC（必须用 `AskUserQuestion` 向用户确认）
- ✗ 不硬编码任何仓名（仓名由用户提供，vendor_name 由仓名派生）
- ✗ 不持久化仓路径 / 算子清单 / SOC（每次会话由 P0/P0.5/P1 重新发现/询问）
- ✗ 不重装 CANN，只 source `set_env.sh`
- ✗ 不凭空捏造错误信息（必须 grep 日志）
- ✗ 不在跑测中途生成报告
