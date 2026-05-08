---
name: ops-test
description: Use when any user request involves CANN 950 operator testing — running, resuming, diagnosing, or batch-executing target operators across ops-transformer / ops-cv / ops-math / ops-nn. MUST be activated before issuing any build.sh / run_example / phase_*.py command for 950 operators. Covers single-op, single-repo-all-ops, and four-repo all-ops scenarios. Also handles post-run report generation.
---

# cann-ops:ops-test

CANN 950 算子跑测的决策大脑。**只要任务涉及 950 算子（hif8 / simt / regbase / cv_fusion 特性算子的 build / install / run / 诊断），必须激活本 skill 再行动。**

工具根目录：skill 目录（`skills/ops-test/`），脚本在 `scripts/`，算子配置在 `inputs/`，运行产物在 `outputs/`。

## 强制激活规则（不可绕过）

凡是触发以下任意一种意图，**禁止**直接调用 `bash build.sh`、`runner/phase_*.py`、`build_out/*.run` 或自写并发脚本，**必须**先按本 skill 的工作流执行：

- 跑测（"跑测 / 跑 / 验证 / 测试"）+（任意 ops 仓 OR 任意目标算子 OR phase1/2/3/4 OR 950 / hif8 / simt / regbase / cv_fusion 关键词）
- 续跑 / 重跑 / 修复后重测失败算子
- 诊断（"诊断 / 看下为什么失败 / 分析失败"）某个算子的失败日志
- 批量跑某个仓全部目标算子 / 四仓全部 63 个目标算子
- 生成 / 输出 / 整理跑测报告（Phase X 跑测结束后的最终汇总）

如果不确定是否触发，按"触发"处理。先激活 skill，再行动。

## 前置环境节点（每次跑测必须先做）

**P0 — 激活 CANN 环境**：subprocess 不会自动继承 ASCEND_HOME_PATH。所有调用 build.sh 的命令必须先 source set_env.sh：

```bash
source $ASCEND_HOME_PATH/../../set_env.sh   # 由 scripts/utils.py 自动推导，无需手动 source
```

**实现位置**：`scripts/utils.py:run_cmd()` 与 `scripts/run_phase1_batched.py` 通过 `bash -c "source <set_env.sh> && <cmd>"` 自动包裹。路径从 `ASCEND_HOME_PATH` 环境变量推导，fallback `~/Ascend/ascend-toolkit/latest/set_env.sh`。**禁止**让调用方自己 source。

**P1 — 硬编码 SOC**：所有脚本 `SOC = "ascend950"` 写死，不再参数化。

## 工作流（含并发拓扑）

### 并发拓扑（正式定义）

| 场景 | 仓间并发 | 仓内并发 | 入口脚本 | 加速比 |
|---|:---:|---|---|:---:|
| **A. 四仓全量 phase1** | 4 worker ProcessPool | 合并 build（`--ops=op1,...,opN`）+ 串行 install + 逐个 run_example | `runner/run_phase1_batched.py` | 6-10× |
| **B. 单仓全量 phase1** | — | 同上合并 build | `runner/run_phase1_batched.py --repo <name>` | 3-5× |
| **C. 单算子 phase1** | — | 单算子三步 | `runner/phase_examples.py --op <name>` | 1× |
| **D. phase 2/3/4** | 仓间可启用 | 仓内串行（NPU 共享） | `runner/phase_kernel_ut.py` / `phase_pytest.py` / `phase_msprof.py` | 4× |

**禁止**：通过 `phase_examples.py --op` 起多进程跑同仓多算子（CMakeCache.txt 冲突）。

### 合并 Build 连坐恢复

当 batched run 中一个算子编译失败导致全批连坐，用单算子兜底跑测还原真实状态：

```bash
cd /home/jiazhibin/cann/cann-950-ops-tester
python3 runner/run_phase1_fallback.py \
  [--repos ops-transformer,ops-math,ops-nn] \
  [--statuses BUILD_FAIL,INSTALL_FAIL]
```

## Phase 路由表

| 用户意图 | 入口命令 |
|---|---|
| 跑四仓全部 phase 1 | `python3 scripts/run_phase1_batched.py` |
| 跑某仓全部 phase 1 | `python3 scripts/run_phase1_batched.py --repo <name>` |
| 跑单算子 phase 1 | `python3 scripts/phase_examples.py --repo <name> --repo-path <path> --inputs inputs/<name>.json --op <op>` |
| 合并 build 连坐兜底 | `python3 scripts/run_phase1_fallback.py [--repos a,b,c]` |
| Phase 2 OpKernel UT | `python3 scripts/phase_kernel_ut.py --repo <name> --repo-path <path> --inputs inputs/<name>.json` |
| Phase 3 Pytest | `python3 scripts/phase_pytest.py --repo <name> --repo-path <path> --inputs inputs/<name>.json` |
| Phase 4 msprof | `python3 scripts/phase_msprof.py --repo <name> --repo-path <path> --inputs inputs/<name>.json` |
| 生成跑测报告 | 见下方「最终报告生成」节 |

## 启动协议

1. **激活确认**：声明 "Using cann-ops:ops-test"，列出范围（仓 / 算子 / phase）和并发拓扑（A/B/C/D）
2. **状态检查**：读 `outputs/run_state.json`，识别已 PASS 与 SKIPPED 算子（续跑跳过）
3. **环境就绪**：runner 内部已强制 source set_env.sh，无需用户操作
4. **执行**：起后台任务，日志 tail 到 `/tmp/phase1_*.log`
5. **报告**：跑完后输出每仓 PASS/FAIL 汇总，按需生成最终报告

## 实时进度输出

**Per repo**：`[{repo}] {N_pass}/{N_total} PASS, build={s}s, install={s}s, run={s}s`

**Per op**：`[{repo}] [i/N] {symbol} {op}: {status}`

**续跑**：已 PASS 的算子跳过；BUILD_FAIL/INSTALL_FAIL 自动重试，`attempts` 字段累加。

## 最终报告生成（Phase X 跑测全部完成后）

**触发条件**：跑测全部完成 + 用户要求"生成报告"。不要在中途生成。

**产出路径**：`outputs/PHASE{N}_FINAL_REPORT.md`

**数据来源**（按优先级）：
1. `outputs/run_state.json` — 算子 × phase × status × duration_s（权威）
2. `outputs/logs/<repo>/<op>.phase{N}.{step}.log` — 真实错误信息摘录
3. `/home/jiazhibin/cann/950-scann/PANORAMA_REPORT.md` — 950 特性命中数据
4. `outputs/phase{N}_*_report.json` — 过程性 JSON

**必备 6 大模块**（顺序固定）：

| # | 模块 | 关键内容 |
|---|------|---------|
| I | 执行摘要 | 一句话结论 + 关键数字表 + 三大发现 + 950 特性覆盖矩阵 + P1/P2/P3 计划 |
| II | 按仓成绩单 | 4 仓 × 6 列汇总表（PASS/各类失败/通过率）+ 状态注脚 |
| III | 失败算子分类诊断 | BUILD_FAIL / RUN_EXIT_FAIL / RUN_PATTERN_FAIL 三张表，每行含：仓 / 算子 / 耗时 / 950 特性 / **真实错误日志摘录** / 根因诊断 / **复现命令** / **诊断步骤 ①②③** |
| IV | PASS 算子汇总 | 按仓列举（含耗时/特性/特点）+ 多规则命中基准表 |
| V | 950 特性覆盖矩阵 | 按规则统计（覆盖率/信号强度）+ 仓级热力图 + 关键发现 |
| VI | 构建优化建议 | 超长编译（≥900s）处理 + BUILD_FAIL 代码瘦身 + 并发策略改进 |
| 附录 | 完整算子清单 | 每仓所有算子 × 状态 × 耗时 × 特性 × 日志路径 |

**关键约束**（必须满足）：

1. **失败算子三要素**：① 真实错误（grep 日志，不可凭空推断）② 完整复现命令（cd <abs-path> && bash build.sh ...）③ 带序号诊断步骤 ①②③
2. **超长编译标记**：耗时 ≥900s 标 `⚠️ TIMEOUT`
3. **耗时落表**：PASS 算子也带耗时
4. **950 特性关联**：每个失败算子标注 hif8/simt/regbase/cv_fusion，关联 PANORAMA_REPORT
5. **不凭空推断**：日志没有的标 `(推断)` 与真实摘录严格区分
6. **复现命令完整**：不留省略号

**生成流程**：
1. 读 `run_state.json` → 按 repo × status 分组
2. 抽样读 5-10 个失败日志，grep `ERROR\|undefined\|failed\|exit=` 提取真实报错
3. 读 PANORAMA_REPORT 关联 950 特性
4. AskUserQuestion 确认报告用途 + 格式 + 核心模块
5. **先输出大纲预案，用户审视后再落盘**
6. Write `outputs/PHASE{N}_FINAL_REPORT.md`

## 失败诊断

用户说"诊断 {op}"时：

1. 读 `outputs/run_state.json` → 找该算子的 status / log_path
2. 读 build/install/run 日志
3. 读算子源码 `<repo>/<category>/<op>/`
4. 输出诊断到 `outputs/failures/<repo>/{op}.md`：根因 + 排查建议
5. **不修源码、不改测试**

## 边界与禁忌

- ✗ 不直接调 `bash build.sh` / 起多进程跑同仓多算子
- ✗ 不修改算子源码 / examples / pytest 用例
- ✗ 不改 SOC（写死 `ascend950`）
- ✗ 不改 vendor_name（写死 `custom`）
- ✗ 不重装 CANN，只 source `set_env.sh`
- ✗ 不动 `inputs/*.json`（63 个目标算子已固化）
- ✗ 不凭空捏造错误信息（必须 grep 日志）
- ✗ 不在跑测中途生成报告
