# cann-ops

> 一套帮你「**找出 950 算子 → 跑测 → 把失败上报社区 → 跟进社区修复并复测**」的 Claude Code 插件。
> 任意 ops 仓、任意 SOC，全程中文交互，产物都落在你当前目录下的一个文件夹里。

## 一图看懂

四个 skill 串成一条算子质量闭环。你可以从任意一环切入，也可以只用其中一个：

```
  ┌──────────────┐   ┌────────────┐   ┌────────────────┐   ┌────────────────┐
  │  scann-repo  │──▶│  ops-test  │──▶│  report-issues │──▶│  track-issues  │
  │              │   │            │   │                │   │                │
  │  扫出依赖     │   │  Phase1-4  │   │  把失败算子转   │   │  查社区回复，   │
  │  950 特性的   │   │  build/run │   │  成社区 issue   │   │  按方案复测，   │
  │  算子靶子     │   │  跑测+报告 │   │  草稿并提交     │   │  PASS 则收尾    │
  └──────────────┘   └─────┬──────┘   └────────────────┘   └───────┬────────┘
                           │                                       │
                           │        ◀── 复用已验证的修复 ──         │
                           │         (known_fixes.json / FAQ)       │
                           └───────────────────────────────────────┘
```

闭环的关键：**track-issues 验证通过的社区修复会写进 FAQ；下次 ops-test 再遇到同样的失败，会自动认出来并提示「用已知方案重试」**——跑得越久，越省事。

## 四个 skill 各管什么

| Skill | 一句话职责 | 典型触发语 |
|---|---|---|
| `cann-ops:scann-repo` | 扫描一个 CANN ops 仓，揪出用了 **950 硬件特性**（simt / hif8 / RegBase）的算子，给出 markdown 清单 + 机读 JSON | "扫一下 ops-transformer 里的 950 算子" |
| `cann-ops:ops-test` | 对目标算子跑**示例跑测**（examples：build → install → 真机跑示例，即历史 phase1；kernel UT / pytest / msprof 暂未开放），支持仓间并发、仓内合并 build、单算子兜底，产出带真实日志、复现命令、特性归因的报告 | "对 ops-cv 跑示例跑测" |
| `cann-ops:report-issues` | 把跑测失败的算子整理成 **GitHub / Gitee / GitCode** 社区能直接受理的 issue 草稿（每算子一篇），提交前逐篇预览确认，本地去重不重复提 | "给失败的算子提 issue" |
| `cann-ops:track-issues` | 查已提 issue 的**社区回复**，读懂维护者给的修复方案，复测验证；PASS 就关 issue + 写进 FAQ，FAIL 就人工确认后追问 | "看看那些 issue 有没有回复" |

> 四个 skill 彼此解耦，但共享同一个 `cann-ops-report/` 目录，所以能自然接力：
> - 想用 950 特性筛算子？先 `scann-repo`，`ops-test` 默认读它的产物。
> - 已经有自己的算子清单？跳过扫描，直接告诉 `ops-test` 算子名。
> - 跑出一堆失败？`report-issues` 接力上报，`track-issues` 接力跟进。

## 设计原则

- **零硬编码**：仓名 / 仓路径 / SOC / API 文档位置 / 目标算子，统统不写死，每次会话由 skill 主动发现或问你。
- **零持久化配置**：不碰 `~/.config/`，不写插件安装目录；所有产物都在你当前工作目录（CWD）下。
- **全程中文**：发现候选、确认选择、错误提示，都用中文。
- **副作用必先确认**：发评论 / 关 issue / 提交 issue / 建 git 分支，每一步都先问你，或支持 `CANN_OPS_DRY_RUN=1` 干跑预演。
- **不绑定 950**：SOC 由你指定（`ascend910b` / `ascend950` / `ascend310p` …），跑测脚本只做命令行透传。

## 产物都放哪：`cann-ops-report/`

所有 skill 都在你**当前工作目录**下读写，统一收敛到 `cann-ops-report/` 这一个根目录：

```
<你的 CWD>/
└── cann-ops-report/
    ├── scann/                    ← scann-repo 扫描产物（每仓一个子目录）
    │   └── <repo>/
    │       ├── summary.md            （主清单：命中算子按规则分桶）
    │       ├── detail.md             （每个命中算子的 文件:行号 证据）
    │       └── _intermediate.json    （机读 JSON，ops-test 默认从这里读靶子）
    │
    ├── test/                     ← ops-test 跑测产物
    │   ├── run_state.json            （算子 × phase × status × 耗时）
    │   ├── logs/<repo>/<op>.phase{N}.{build,install,run}.log
    │   ├── failures/<repo>/<op>.md   （失败诊断）
    │   └── PHASE{N}_FINAL_REPORT.md  （最终结构化报告）
    │
    ├── issues/                   ← report-issues + track-issues 共享
    │   ├── state.json                （去重 + 提交状态: repo::op::failure → issue_url）
    │   ├── repos.json                （repo → platform/owner/repo 缓存）
    │   ├── drafts/<repo>/<op>__<failure_type>.md   （草稿，每算子一篇）
    │   ├── submitted/<repo>/<id>.json              （已提交记录）
    │   ├── comments/  plans/  replies/  patches/   （track-issues 跟进过程产物）
    │
    └── faq/                      ← track-issues 沉淀的「已知修复」
        ├── known_fixes.json         （机读：ops-test 下次自动查询）
        └── FAQ.md                   （人读：你的团队知识库）
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

安装后**重启 Claude Code**（或 `/reload-plugins`），skill 列表里会出现：
`cann-ops:scann-repo`、`cann-ops:ops-test`、`cann-ops:report-issues`、`cann-ops:track-issues`。

## 快速开始

### 场景 1 · 扫出一个仓的 950 算子

```
你："用 cann-ops 扫描 ops-transformer，路径在 /data/cann/ops-transformer"
```

skill 会：检查 Python 依赖 → 校验仓里有 `docs/zh/op_list.md` → 扫描并渲染报告到 `cann-ops-report/scann/ops-transformer/`。

> 没指定路径也行——skill 会在 CWD 下找含 `docs/zh/op_list.md` 的子目录，列出来让你确认。

### 场景 2 · 跑测目标算子（几种来源都支持）

| 你怎么说 | skill 怎么取算子 |
|---|---|
| "对 ops-transformer 跑示例跑测" | 已扫过 → 问你「跑扫出来的 N 个」还是「自己指定」 |
| "跑示例跑测，目标：flash_attention_score, grouped_matmul" | 直接用你列的算子，不需要扫描产物 |
| "并发跑 ops-transformer 和 ops-cv 的 950 算子" | 收集两个仓路径，启进程池仓间并发 |
| "对 ops-math 跑示例跑测，清单见 my-ops.txt" | 读文件（`.json` / 一行一算子的纯文本都行） |

跑测前 skill 会先问你**仓路径**和 **SOC**，然后调度合并 build + 串行 install + 逐算子 run，产物写到 `cann-ops-report/test/`。

#### 跑测结果怎么判定（4 层日志判定）

不再是「退出码 0 就算过」的粗判。每个算子按 4 层来定性：

```
L0  退出码 ≠ 0                         → FAIL
L1  命中强失败信号（段错误/core/EE码…）  → FAIL
L2  命中强成功信号（result[i] is:…）     → PASS
L3  以上都没命中                        → UNCERTAIN（标记出来，跑完由你/agent 集中复核）
```

`UNCERTAIN` 的意义：**不让一条模糊的日志阻塞整批跑测**，先记下来，最后统一判，避免误判成 PASS 或 FAIL。

### 场景 3 · 整理成最终报告

```
你："把跑测结果整理成一份完整报告"
```

skill 读 `run_state.json` 和失败日志，产出含 6 大模块的 markdown：执行摘要 / 按仓成绩单 / 失败算子分类诊断（带真实日志摘录 + 复现命令）/ PASS 汇总 / 950 特性覆盖矩阵（有 scann 产物时）/ 构建优化建议。

### 场景 4 · 把失败上报社区，并跟进修复

```
你："给跑失败的算子提 issue"          →  report-issues
你："看看那几个 issue 社区回了没"      →  track-issues
```

- **report-issues**：为每个失败算子生成一篇草稿（社区规范：一算子一 issue 才好追踪/关闭/打 label）。你说「我自己提」就给你预填 URL；说「你帮我提」就**逐篇预览完整标题+正文 → 确认 → 才调 API**。提交成功的 URL 写进 `state.json`，交给下一棒。
- **track-issues**：拉取 issue 的社区回复，**agent 自己读懂**维护者给的方案（环境变量 / 编译开关 / 补丁 / 升级），自动补齐 SOC、仓路径等上下文后复测。PASS → 关 issue + 把修复写进 `faq/`；FAIL → 人工确认后礼貌追问。

## CLI 参数速查（手动调跑测脚本时用）

| 参数 | 含义 | 来源 |
|---|---|---|
| `--repo-mapping <r1>=<p1>,<r2>=<p2>,…` | 仓名 → 本地源码路径（CSV） | skill 询问 |
| `--soc <soc>` | 目标 SOC 名称 | skill 询问 |
| `--ops <op1>,<op2>,…` / `--ops-file <path>` / *都不传* | 目标算子来源（CSV / 文件 / 默认读 scann 产物） | skill 决定 |

跟社区平台交互的脚本读这些环境变量：`GITEE_TOKEN`、`GITCODE_TOKEN`（GitHub 走 `gh` CLI），`CANN_OPS_DRY_RUN=1` 可全程干跑不发请求。

## 950 算子识别的 3 条规则（scann-repo 专用）

| 规则 | 识别依据 | 说明 |
|---|---|---|
| **SIMT** | 源码出现 `__simt_vf__` 关键字 | NPU 上动态执行分支逻辑 |
| **HIF8** | 源码出现 `HIFLOAT8` 类型 | 950 专属 8bit 高保真浮点格式 |
| **RegBase** | 使用 `AscendC::MicroAPI::RegTensor` API | 寄存器块级别向量存取 |

## 硬件 / 环境要求

- **NPU**：任意 Ascend 系列（910B / 950 / 310P …），跑测时由你指定 SOC。
- **CANN toolkit**：安装后 `ASCEND_HOME_PATH` 自动设置；skill 据此推导 `set_env.sh`，无需手动 source。
- **Python**：3.8+（依赖 jinja2，scann-repo 首次运行会自动安装）。

## 常见问题

**Q：跑测必须先扫描吗？**
A：不必。自己有算子清单（自然语言列举 / 文件）就直接喂给 ops-test，跳过 scann-repo。

**Q：仓必须叫 `ops-X` 吗？**
A：不必。仓名是任意字符串。scann-repo 只看有没有 `docs/zh/op_list.md`；ops-test 自动从仓名派生 vendor name。

**Q：必须用 Ascend 950 吗？**
A：不必。SOC 是参数。950 特性规则只在 scann-repo 里用，跑测本身和 SOC 无关。

**Q：能并发跑同一个仓的多个算子吗？**
A：单仓内禁止并发（CMakeCache.txt 会冲突），用合并 build（`--ops=op1,op2,…`）替代；仓间可以并发。

**Q：report-issues 会自动提交吗？会不会乱发？**
A：不会自动。「你帮我提」也要先逐篇预览完整正文 + 你点确认才调 API；任何发评论/关 issue 同样先确认。想试水就设 `CANN_OPS_DRY_RUN=1`。

**Q：FAQ（known_fixes.json）是怎么长出来的？**
A：track-issues 每验证通过一个社区修复，就写一条进去。下次 ops-test 遇到同样的失败签名，会自动认出并提示「用已知方案重试」，越跑越省心。

## 仓库

- 主页：https://github.com/justbin-coder/cann-ops-test
- License：MIT
