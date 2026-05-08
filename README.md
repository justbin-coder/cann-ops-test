# cann-ops

CANN 950 算子全流程工具的 Claude Code 插件：**任意 ops 仓**的 950 特性扫描 + Phase 1-4 跑测 + 结构化报告生成。

## 这个插件能做什么

| Skill | 解决什么问题 |
|---|---|
| `cann-ops:scann-repo` | 扫描某个 CANN ops 仓（任意名称、任意路径），自动识别使用了 950 硬件特性（simt / hif8 / RegBase / cube+vector fusion）的算子，输出 markdown 清单和机读 JSON |
| `cann-ops:ops-test` | 对扫描出的目标算子执行 Phase 1-4 跑测，支持仓间并发 + 仓内合并 build + 单算子兜底，并产出含真实日志摘录、复现命令、950 特性归因的最终报告 |

两个 skill 一前一后形成闭环：scann-repo 的输出（`_intermediate.json`）就是 ops-test 的输入。

## 设计原则

- **零硬编码**：仓名、路径、API 文档位置都不写死，每次会话由 Skill 主动发现或询问用户
- **零持久化配置**：不写 `~/.config/`、不写 plugin 安装目录；所有产物都在用户当前工作目录下
- **中文交互**：发现候选、确认选择、错误提示都用中文
- **统一输出根目录**：两个 skill 的所有产物都收敛到 `CWD/cann-ops-report/` 一个文件夹

## 工作目录约定

skill 在用户**当前工作目录（CWD）**下读写，统一使用 `cann-ops-report/` 作为根：

```
<用户 CWD>/
└── cann-ops-report/
    ├── scann/                 ← scann-repo 的扫描产物（每个仓一个子目录）
    │   └── <repo>/
    │       ├── summary.md         (主清单：N 个命中算子按规则分桶)
    │       ├── detail.md          (每个命中算子的文件:行号证据)
    │       └── _intermediate.json (机读 JSON，ops-test 从此读取目标算子)
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

安装后**重启 Claude Code**（或在已开启的会话里 `/reload-plugins`），skill 列表里会出现 `cann-ops:scann-repo` 和 `cann-ops:ops-test`。

## 快速开始

### 场景 1：扫描一个 ops 仓

```
用户："用 cann-ops 扫描 ops-transformer，路径在 /data/cann/ops-transformer"
```

skill 行为：
1. 检查 Python 依赖（jinja2 / pdfplumber / pypdf），缺失则自动 `pip install`
2. 校验目标仓有 `docs/zh/op_list.md`
3. 检查白名单：`<api_doc_path>/whitelist_cube.md` 和 `whitelist_vector.md` 是否都已生成
   - 已存在 → 询问用户复用或刷新
   - 不存在 → 启动对话式抽取流程（询问 PDF 路径、读 outline、按章节抽 API、用户 review、落盘）
4. 执行 `scripts.scan_repo` + `scripts.render_report`
5. 产物写入 `CWD/cann-ops-report/scann/ops-transformer/`

如果用户不指定路径，skill 会先在 CWD 下扫描候选仓（找 `docs/zh/op_list.md`），用中文呈现给用户确认。

### 场景 2：跑测扫描出的目标算子

```
用户："对 ops-transformer 跑 Phase 1"
```

skill 行为：
1. 读 `CWD/cann-ops-report/scann/ops-transformer/_intermediate.json` 获取目标算子（必须先扫描过）
2. 询问 / 确认 ops-transformer 的本地源码路径（用 `--repo-mapping` 传给脚本）
3. 自动 source `set_env.sh`，调度 `run_phase1_batched.py` 执行合并 build + 串行 install + 逐算子 run_example
4. 产物写入 `CWD/cann-ops-report/test/`

支持多仓并发：传给 skill 多个 `repo=path` 映射，会启 ProcessPool 仓间并发。

### 场景 3：跑测后生成最终报告

```
用户："把跑测结果整理成一份完整报告"
```

skill 会读 `run_state.json` 和失败日志，输出含 6 大模块的 markdown 报告：执行摘要 / 按仓成绩单 / 失败算子分类诊断（含真实错误日志摘录、复现命令、诊断步骤）/ PASS 算子汇总 / 950 特性覆盖矩阵 / 构建优化建议。报告写到 `CWD/cann-ops-report/test/PHASE{N}_FINAL_REPORT.md`。

## 950 算子识别的 4 条规则

| 规则 | 识别依据 | 说明 |
|---|---|---|
| **SIMT** | 源码出现 `__simt_vf__` 关键字 | NPU 上动态执行分支逻辑 |
| **HIF8** | 源码出现 `HIFLOAT8` 类型 | 950 专属 8bit 高保真浮点格式 |
| **RegBase** | 源码使用 `AscendC::MicroAPI::RegTensor` API | 寄存器块级别向量存取 |
| **CV 融合** | `op_kernel/` 内同时出现真 cube + 真 vector API | 仅扫 op_kernel，过滤 op_host/op_api/op_graph 的 tiling 噪声 |

CV 融合规则的 cube/vector API 白名单从 Ascend C API 文档（PDF）里对话式抽取，按章节映射；PDF 升级会自动触发 SHA 校验提示。

## 硬件 / 环境要求

- **NPU**：Ascend 950
- **CANN toolkit**：安装后 `ASCEND_HOME_PATH` 自动设置；skill 从中推导 `set_env.sh`，无需手动 source
- **Python**：3.8+（依赖 jinja2 / pdfplumber / pypdf，scann-repo 首次运行会自动安装）

## 常见问题

**Q：仓必须叫 `ops-X` 吗？**
A：不必。仓名是任意字符串，scann-repo 只检查 `docs/zh/op_list.md` 是否存在；ops-test 自动从仓名派生 vendor name（`ops-X` → `custom_X`，其它 → `custom_<repo>`）。

**Q：可以跑同一个仓的多个算子并发吗？**
A：单仓内禁止并发（CMakeCache.txt 冲突），用合并 build（`--ops=op1,op2,...`）取代。仓间可以并发。

**Q：scann 失败的白名单可以手工修吗？**
A：可以。`whitelist_cube.md` 和 `whitelist_vector.md` 落在你指定的 API 文档目录下，是普通 markdown，编辑后下次扫描直接读。

## 仓库

- 主页：https://github.com/justbin-coder/cann-ops-test
- License：MIT
