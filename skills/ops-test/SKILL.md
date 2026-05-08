---
name: ops-test
description: 用于 CANN 950 算子跑测——任意 ops 仓中目标算子的 build/install/run/诊断，覆盖单算子、单仓全量、多仓并发场景，并生成跑测报告。涉及 build.sh / phase_*.py 命令、950 / hif8 / simt / regbase / cv_fusion 关键词、跑测 / 续跑 / 诊断 / 重测 等用户意图时必须激活本 skill 再行动。
---

# cann-ops:ops-test

CANN 950 算子跑测的决策大脑。**只要任务涉及 950 算子（hif8 / simt / regbase / cv_fusion 特性算子的 build / install / run / 诊断），必须激活本 skill 再行动。**

**输入来源**：目标算子从 `CWD/cann-ops-report/scann/<repo>/_intermediate.json` 读取（由 `cann-ops:scann-repo` 生成）。仓名与本地路径**每次会话由 Skill 主动询问/发现**，不再依赖任何持久化配置文件。

**输出路径**：所有运行产物写到用户当前工作目录（CWD）的 `cann-ops-report/test/` 子目录：
- `CWD/cann-ops-report/test/run_state.json` — 算子跑测状态
- `CWD/cann-ops-report/test/logs/` — 每个算子的 build/install/run 日志
- `CWD/cann-ops-report/test/PHASE{N}_FINAL_REPORT.md` — 最终报告

## 强制激活规则（不可绕过）

凡是触发以下任意一种意图，**禁止**直接调用 `bash build.sh`、`scripts/phase_*.py`、`build_out/*.run` 或自写并发脚本，**必须**先按本 skill 的工作流执行：

- 跑测（"跑测 / 跑 / 验证 / 测试"）+（任意 ops 仓 OR 任意目标算子 OR phase1/2/3/4 OR 950 / hif8 / simt / regbase / cv_fusion 关键词）
- 续跑 / 重跑 / 修复后重测失败算子
- 诊断（"诊断 / 看下为什么失败 / 分析失败"）某个算子的失败日志
- 批量跑某个仓全部目标算子 / 多仓并发跑测
- 生成 / 输出 / 整理跑测报告（Phase X 跑测结束后的最终汇总）

如果不确定是否触发，按"触发"处理。先激活 skill，再行动。

## 前置环境节点（每次跑测必须先做）

### P0 — 发现并确认目标仓（中文交互）

激活后**第一步**：在用户当前工作目录（CWD）下扫描已被 scann-repo 处理过的仓——找 `CWD/cann-ops-report/scann/*/_intermediate.json` 存在的子目录，每个就是一个候选仓名。

**根据用户原话**判断意图，按下面三种情况之一处理：

1. **用户在请求里已经明确给了仓名 + 路径**（例如"跑 ops-transformer，路径在 /data/cann/ops-transformer"）
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
   → 提示用户先用 `cann-ops:scann-repo` 扫描，或直接给仓名 + 路径让我跑测。

**仓名约束**：完全自由字符串，不再有"四仓"或硬编码列表。用户写什么就用什么（vendor_name 由仓名自动派生：`ops-X` → `custom_X`，非 `ops-` 前缀仓名 → `custom_<repo>`）。

**仓路径约束**：必须是绝对路径或相对 CWD 的可解析路径，并且目录里有 `build.sh`（CANN ops 仓的标志）。

**收集到 `{repo: path}` 映射后**：本会话内一直使用，不写任何持久化文件。下次会话重新走 P0。

### P1 — CANN 环境

`ASCEND_HOME_PATH` 由 CANN toolkit 安装时自动设置，`scripts/utils.py:run_cmd()` 从中推导 `set_env.sh` 并自动 source，无需用户操作。若 `ASCEND_HOME_PATH` 未设置，说明 CANN toolkit 未安装，提示用户先安装。

### P2 — 硬编码 SOC

所有脚本 `SOC = "ascend950"` 写死，不再参数化。

## 工作流（含并发拓扑）

### 并发拓扑

| 场景 | 仓间并发 | 仓内并发 | 入口脚本 | 加速比 |
|---|:---:|---|---|:---:|
| **A. 多仓全量 phase1** | N worker ProcessPool | 合并 build（`--ops=op1,...,opN`）+ 串行 install + 逐个 run_example | `scripts/run_phase1_batched.py` | 6-10× |
| **B. 单仓全量 phase1** | — | 同上合并 build | `scripts/run_phase1_batched.py`（mapping 只填一项） | 3-5× |
| **C. 单算子 phase1** | — | 单算子三步 | `scripts/phase_examples.py --op <name>` | 1× |
| **D. phase 2/3/4** | 仓间可启用 | 仓内串行（NPU 共享） | `scripts/phase_kernel_ut.py` / `phase_pytest.py` / `phase_msprof.py` | N× |

**禁止**：通过 `phase_examples.py --op` 起多进程跑同仓多算子（CMakeCache.txt 冲突）。

### 合并 Build 连坐恢复

当 batched run 中一个算子编译失败导致全批连坐，用单算子兜底跑测还原真实状态：

```bash
python3 scripts/run_phase1_fallback.py \
  --repo-mapping <repo1>=<path1>,<repo2>=<path2>,... \
  [--statuses BUILD_FAIL,INSTALL_FAIL]
```

## Phase 路由表

仓路径用 `--repo-mapping repo1=path1,repo2=path2,...` 显式传入（来自 P0 发现/询问）。

| 用户意图 | 入口命令 |
|---|---|
| 多仓全量 phase 1 | `python3 scripts/run_phase1_batched.py --repo-mapping <r1>=<p1>,<r2>=<p2>,...` |
| 单仓全量 phase 1 | `python3 scripts/run_phase1_batched.py --repo-mapping <repo>=<path>` |
| 单算子 phase 1 | `python3 scripts/phase_examples.py --repo <name> --repo-path <path> --op <op>` |
| 合并 build 连坐兜底 | `python3 scripts/run_phase1_fallback.py --repo-mapping <r1>=<p1>,...` |
| Phase 2 OpKernel UT | `python3 scripts/phase_kernel_ut.py --repo <name> --repo-path <path>` |
| Phase 3 Pytest | `python3 scripts/phase_pytest.py --repo <name> --repo-path <path>` |
| Phase 4 msprof | `python3 scripts/phase_msprof.py --repo <name> --repo-path <path>` |
| 生成跑测报告 | 见下方「最终报告生成」节 |

## 启动协议

1. **激活确认**：声明 "Using cann-ops:ops-test"，列出范围（仓 / 算子 / phase）和并发拓扑（A/B/C/D）
2. **P0 发现/询问**：按 P0 流程拿到 `{repo: path}` 映射并向用户确认（中文）
3. **状态检查**：读 `CWD/cann-ops-report/test/run_state.json`，识别已 PASS 与 SKIPPED 算子（续跑跳过）
4. **环境就绪**：runner 内部已强制 source set_env.sh，无需用户操作
5. **执行**：起后台任务，日志 tail 到 `/tmp/phase1_*.log`
6. **报告**：跑完后输出每仓 PASS/FAIL 汇总，按需生成最终报告

## 实时进度输出

**Per repo**：`[{repo}] {N_pass}/{N_total} PASS, build={s}s, install={s}s, run={s}s`

**Per op**：`[{repo}] [i/N] {symbol} {op}: {status}`

**续跑**：已 PASS 的算子跳过；BUILD_FAIL/INSTALL_FAIL 自动重试，`attempts` 字段累加。

## 最终报告生成（Phase X 跑测全部完成后）

**触发条件**：跑测全部完成 + 用户要求"生成报告"。不要在中途生成。

**产出路径**：`CWD/cann-ops-report/test/PHASE{N}_FINAL_REPORT.md`

**数据来源**（按优先级）：
1. `CWD/cann-ops-report/test/run_state.json` — 算子 × phase × status × duration_s（权威）
2. `CWD/cann-ops-report/test/logs/<repo>/<op>.phase{N}.{step}.log` — 真实错误信息摘录
3. `CWD/cann-ops-report/scann/<repo>/_intermediate.json` — 950 特性命中数据（与 scann-repo 共享）
4. `CWD/cann-ops-report/test/phase{N}_*_report.json` — 过程性 JSON

**必备 6 大模块**（顺序固定）：

| # | 模块 | 关键内容 |
|---|------|---------|
| I | 执行摘要 | 一句话结论 + 关键数字表 + 三大发现 + 950 特性覆盖矩阵 + P1/P2/P3 计划 |
| II | 按仓成绩单 | 每仓 × 6 列汇总表（PASS/各类失败/通过率）+ 状态注脚 |
| III | 失败算子分类诊断 | BUILD_FAIL / RUN_EXIT_FAIL / RUN_PATTERN_FAIL 三张表，每行含：仓 / 算子 / 耗时 / 950 特性 / **真实错误日志摘录** / 根因诊断 / **复现命令** / **诊断步骤 ①②③** |
| IV | PASS 算子汇总 | 按仓列举（含耗时/特性/特点）+ 多规则命中基准表 |
| V | 950 特性覆盖矩阵 | 按规则统计（覆盖率/信号强度）+ 仓级热力图 + 关键发现 |
| VI | 构建优化建议 | 超长编译（≥900s）处理 + BUILD_FAIL 代码瘦身 + 并发策略改进 |
| 附录 | 完整算子清单 | 每仓所有算子 × 状态 × 耗时 × 特性 × 日志路径 |

**关键约束**（必须满足）：

1. **失败算子三要素**：① 真实错误（grep 日志，不可凭空推断）② 完整复现命令（cd <abs-path> && bash build.sh ...）③ 带序号诊断步骤 ①②③
2. **超长编译标记**：耗时 ≥900s 标 `⚠️ TIMEOUT`
3. **耗时落表**：PASS 算子也带耗时
4. **950 特性关联**：每个失败算子标注 hif8/simt/regbase/cv_fusion
5. **不凭空推断**：日志没有的标 `(推断)` 与真实摘录严格区分
6. **复现命令完整**：不留省略号

**生成流程**：
1. 读 `run_state.json` → 按 repo × status 分组
2. 抽样读 5-10 个失败日志，grep `ERROR\|undefined\|failed\|exit=` 提取真实报错
3. 读 `_intermediate.json` 关联 950 特性
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

## 边界与禁忌

- ✗ 不直接调 `bash build.sh` / 起多进程跑同仓多算子
- ✗ 不修改算子源码 / examples / pytest 用例
- ✗ 不改 SOC（写死 `ascend950`）
- ✗ 不硬编码任何仓名（`ops-transformer / ops-cv / ops-math / ops-nn` 不再是固定列表）
- ✗ 不持久化仓路径或 vendor 映射（每次会话由 P0 重新发现/询问）
- ✗ 不重装 CANN，只 source `set_env.sh`
- ✗ 不凭空捏造错误信息（必须 grep 日志）
- ✗ 不在跑测中途生成报告
