# cann-ops

CANN 算子全流程工具的 Claude Code 插件：**任意 ops 仓 + 任意 SOC** 的 950 特性扫描 + Phase 1-4 跑测 + 结构化报告。

## 这个插件能做什么

| Skill | 解决什么问题 |
|---|---|
| `cann-ops:scann-repo` | 扫描某个 CANN ops 仓（任意名称 / 任意路径），自动识别使用了 950 硬件特性（simt / hif8 / RegBase / cube+vector fusion）的算子，输出 markdown 清单和机读 JSON |
| `cann-ops:ops-test` | 对**任意来源**的目标算子（scann-repo 产物 / 用户列举 / 文件清单）执行 Phase 1-4 跑测，支持仓间并发 + 仓内合并 build + 单算子兜底，并产出含真实日志摘录、复现命令、950 特性归因的最终报告 |

两个 skill 解耦但能协同：
- 想用 950 特性筛选算子？先调 scann-repo，ops-test 默认读它的产物
- 已有自己的算子清单？跳过 scann-repo，直接告诉 ops-test 算子名

## 设计原则

- **零硬编码**：仓名 / 仓路径 / SOC / API 文档位置 / 目标算子，都不写死，每次会话由 skill 主动发现或询问用户
- **零持久化配置**：不写 `~/.config/`，不写 plugin 安装目录；所有产物都在用户当前工作目录下
- **中文交互**：发现候选、确认选择、错误提示都用中文
- **统一输出根目录**：两个 skill 的所有产物都收敛到 `CWD/cann-ops-report/` 一个文件夹
- **不绑定 950**：SOC 由用户输入（`ascend910b` / `ascend950` / `ascend310p` 等），跑测脚本仅做命令行透传

## 工作目录约定

skill 在用户**当前工作目录（CWD）**下读写，统一使用 `cann-ops-report/` 作为根：

```
<用户 CWD>/
└── cann-ops-report/
    ├── scann/                 ← scann-repo 的扫描产物（每个仓一个子目录）
    │   └── <repo>/
    │       ├── summary.md         (主清单：N 个命中算子按规则分桶)
    │       ├── detail.md          (每个命中算子的文件:行号证据)
    │       └── _intermediate.json (机读 JSON，ops-test 默认从此读取目标算子)
    └── test/                  ← ops-test 的跑测产物
        ├── run_state.json         (算子 × phase × status × duration_s)
        ├── logs/<repo>/<op>.phase{N}.{build,install,run}.log
        ├── failures/<repo>/<op>.md (失败诊断)
        ├── phase{N}_*_report.json  (过程性 JSON)
        └── PHASE{N}_FINAL_REPORT.md (最终结构化报告)
```

## 安装

### 方式 A：从 GitHub marketplace（推荐）

```bash
claude plugin marketplace add justbin-coder/cann-ops-test
claude plugin install cann-ops@cann-ops-test
```

### 方式 B：本地开发版

```bash
git clone https://github.com/justbin-coder/cann-ops-test.git
claude plugin marketplace add ./cann-ops-test
claude plugin install cann-ops@cann-ops-test
```

安装后**重启 Claude Code**（或 `/reload-plugins`），skill 列表里会出现 `cann-ops:scann-repo` 和 `cann-ops:ops-test`。

## 快速开始

### 场景 1：扫描一个 ops 仓的 950 特性算子

```
用户："用 cann-ops 扫描 ops-transformer，路径在 /data/cann/ops-transformer"
```

skill 行为：
1. 检查 Python 依赖（jinja2 / pdfplumber / pypdf），缺失则自动 `pip install`
2. 校验目标仓有 `docs/zh/op_list.md`
3. 检查白名单：`<api_doc_path>/whitelist_cube.md` 和 `whitelist_vector.md`
   - 已存在 → 询问用户复用或刷新
   - 不存在 → 对话式抽取（询问 PDF 路径、读 outline、按章节抽 API、用户 review、落盘）
4. 执行扫描和报告渲染
5. 产物写入 `CWD/cann-ops-report/scann/ops-transformer/`

用户没指定路径，skill 会先在 CWD 下扫描候选仓（找含 `docs/zh/op_list.md` 的子目录），用中文呈现给用户确认。

### 场景 2：跑测一个仓的目标算子（多种来源）

#### 2A — 已扫描过，跑扫描出的算子（最常见）

```
用户："对 ops-transformer 跑 phase1"
```

skill 行为：
1. **P0** 询问 / 确认 ops-transformer 的本地源码路径
2. **P0.5** 检测到 `cann-ops-report/scann/ops-transformer/_intermediate.json` → 用 `AskUserQuestion` 询问：
   - A. 跑这 N 个扫出来的算子（推荐）
   - B. 我自己指定要跑的算子
3. **P1** 询问 SOC（`ascend910b` / `ascend950` / 其它）
4. 调度 `run_phase1_batched.py` 执行合并 build + 串行 install + 逐算子 run_example
5. 产物写入 `CWD/cann-ops-report/test/`

#### 2B — 还没扫描，想跑某些算子

```
用户："对 ops-transformer 跑 phase1，目标算子：flash_attention_score, grouped_matmul"
```

skill 行为：
1. **P0** 询问仓路径
2. **P0.5** CWD 没有 scann 产物 → 用 `AskUserQuestion` 询问：
   - A. 先扫描这个仓再跑
   - B. 我自己指定算子（用户已经列了 → 走这个分支）
3. **P1** 询问 SOC
4. 转 `--ops flash_attention_score,grouped_matmul` 传给脚本
5. 不需要 `_intermediate.json`，直接跑

#### 2C — 多仓并发

```
用户："并发跑 ops-transformer 和 ops-cv 的 950 算子"
```

skill 收集两个仓的路径，传 `--repo-mapping ops-transformer=...,ops-cv=...`，runner 启 ProcessPool 仓间并发。

#### 2D — 用文件喂算子清单

```
用户："对 ops-math 跑 phase1，算子清单见 my-ops.txt"
```

skill 转 `--ops-file my-ops.txt` 传给脚本（支持 `.json` 含 `unique_targets` / 顶层 list / 一行一算子的纯文本）。

### 场景 3：跑测后生成最终报告

```
用户："把跑测结果整理成一份完整报告"
```

skill 读 `run_state.json` 和失败日志，输出含 6 大模块的 markdown 报告：执行摘要 / 按仓成绩单 / 失败算子分类诊断（含真实错误日志摘录、复现命令、诊断步骤）/ PASS 算子汇总 / 950 特性覆盖矩阵（仅当 scann 产物存在时）/ 构建优化建议。报告写到 `CWD/cann-ops-report/test/PHASE{N}_FINAL_REPORT.md`。

## CLI 参数速查

所有跑测脚本现在统一接收以下三组参数（由 skill 帮你填，但手动调脚本也支持）：

| 参数 | 含义 | 来源 |
|---|---|---|
| `--repo-mapping <r1>=<p1>,<r2>=<p2>,...` | 仓名到本地源码路径的映射（CSV） | skill P0 询问 |
| `--soc <soc>` | 目标 SOC 名称 | skill P1 询问 |
| `--ops <op1>,<op2>,...` 或 `--ops-file <path>` 或 *都不传* | 目标算子来源（CSV / 文件 / 默认从 scann-repo 产物） | skill P0.5 决定 |

## 950 算子识别的 4 条规则（仅 scann-repo）

| 规则 | 识别依据 | 说明 |
|---|---|---|
| **SIMT** | 源码出现 `__simt_vf__` 关键字 | NPU 上动态执行分支逻辑 |
| **HIF8** | 源码出现 `HIFLOAT8` 类型 | 950 专属 8bit 高保真浮点格式 |
| **RegBase** | 源码使用 `AscendC::MicroAPI::RegTensor` API | 寄存器块级别向量存取 |
| **CV 融合** | `op_kernel/` 内同时出现真 cube + 真 vector API | 仅扫 op_kernel，过滤 op_host/op_api/op_graph 的 tiling 噪声 |

CV 融合规则的 cube/vector API 白名单从 Ascend C API 文档（PDF）里对话式抽取，按章节映射；PDF 升级会自动触发 SHA 校验提示。

## 硬件 / 环境要求

- **NPU**：任意 Ascend 系列（910B / 950 / 310P 等），由用户在跑测时指定 SOC
- **CANN toolkit**：安装后 `ASCEND_HOME_PATH` 自动设置；skill 从中推导 `set_env.sh`，无需手动 source
- **Python**：3.8+（依赖 jinja2 / pdfplumber / pypdf，scann-repo 首次运行会自动安装）

## 常见问题

**Q：跑测必须先扫描吗？**
A：不必。如果你自己有算子清单（自然语言列举 / 文件），ops-test 直接接收，跳过 scann-repo。两个 skill 解耦。

**Q：仓必须叫 `ops-X` 吗？**
A：不必。仓名是任意字符串。scann-repo 只检查 `docs/zh/op_list.md` 是否存在；ops-test 自动从仓名派生 vendor name（`ops-X` → `custom_X`，其它 → `custom_<repo>`）。

**Q：必须用 Ascend 950 吗？**
A：不必。SOC 是参数化的，用户在跑测时指定（`ascend910b` / `ascend950` 等）。950 特性扫描规则只在 scann-repo 里使用，跑测本身和 SOC 无关。

**Q：可以跑同一个仓的多个算子并发吗？**
A：单仓内禁止并发（CMakeCache.txt 冲突），用合并 build（`--ops=op1,op2,...`）取代。仓间可以并发。

**Q：scann 抽出的白名单可以手工修吗？**
A：可以。`whitelist_cube.md` 和 `whitelist_vector.md` 落在你指定的 API 文档目录下，是普通 markdown，编辑后下次扫描直接读。

## 仓库

- 主页：https://github.com/justbin-coder/cann-ops-test
- License：MIT
