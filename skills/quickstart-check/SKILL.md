---
name: quickstart-check
description: 评估 CANN 算子仓的 QuickStart / 快速入门文档质量——忠实模拟开发者「照着快速入门文档一步步操作」,只按文档做、禁止任何文档以外的探索/绕过/workaround,看能否纯按文档跑通;跑不通就出结论报告暴露文档缺陷。涉及「按快速入门跑 / quickstart 体检 / 快速入门验证 / quickstart 评估 / 快速入门能不能跑通 / 快速入门文档质量」等意图时激活本 skill。(只针对 quickstart/快速入门;评估其它类型文档由同类兄弟 skill 负责。)
---

# cann-ops:quickstart-check

**忠实模拟开发者照 QuickStart / 快速入门文档操作,以此体检文档质量。**

一句话:把自己当成一个**只会照文档做、不会自己想办法**的新开发者,严格按文档一步步执行,看能不能跑起来。能跑通→文档合格;卡住→停在那,把「文档让人卡在哪、缺什么」写成结论报告。

## ⚠ 本 skill 的反常之处(灵魂,不可违背)

其它 skill(尤其 `ops-test` 的 P6)鼓励**主动探索找 workaround**;**本 skill 恰恰相反——禁止任何文档以外的探索**。

> 因为:探索也许能把它跑起来,但那是**你**的本事,不是**文档**的本事。一旦你 source 了文档没让你 source 的环境、加了文档没写的 flag、改了文档里的错命令、清了缓存重试……你就**掩盖了文档的缺陷**,体检失去意义。开发者照着这份文档**跑不起来**这一事实,必须被如实暴露。

所以:**只做文档明写的操作,文档没写的一律不做,文档错的照错跑,卡住就停。**

## When to invoke

- 「按这个仓的快速入门跑一遍,看文档能不能跑通」
- 「体检 ops-X 的 QuickStart / 快速入门文档」
- 「评估这份文档质量 / 开发者照文档能不能跑起来」
- 任何「严格照文档操作以验证文档」的请求

## Inputs(零硬编码,每次会话发现或询问)

- **目标仓**:从 CWD 发现候选(有 `docs/` 或 README 的子目录),或用户给绝对路径/仓名。
- **待评测文档**:在选定仓里扫 QuickStart / 快速入门 候选,**让用户确认评测哪一份**(一仓一份,可多仓)。
- **SOC / 执行环境**:文档若要求传 SOC 等,**以文档为准**;不替文档假定。

## 起始状态约定(固定)

- **CANN 默认已装好**,永远当作已满足的前提——用机器上**现成的 CANN**,本 skill 不负责装/换 CANN。
- 假设文档「前提条件 / 环境要求」一节声明的(CANN、NPU、仓已 clone 等)**均已满足**。
- 例外:若文档**要求**某具体前提(如某 CANN 版本)而机器实际不符,记为「前提不符」缺陷——但**不去装/换**(那是探索)。

## 与兄弟 skill 的边界

- **要准备 / 修环境**(装依赖、source CANN、切配套 tag、建 conda)→ 用 `cann-ops:setup-env`,**不是**本 skill。本 skill **只照文档审**,绝不替文档准备环境。
- **想真正跑通算子(主动找 workaround、续跑、探索)** → 用 `cann-ops:ops-test`。本 skill 恰恰**禁止**探索,只忠实复现「照文档能到哪」。
- 本 skill 只评 **quickstart / 快速入门**;评其它类型文档(API 手册、设计文档等)由未来同类兄弟 skill 负责。

## Workflow

### P0 — 发现并确认「目标仓 + 待评测文档」(中文交互)

1. 在 CWD / 用户给的路径下扫候选文档:`docs/QUICKSTART*.md`、`QUICKSTART*.md`、`docs/zh/快速入门*.md`、`**/快速入门*.md`、`docs/**/getting[-_]started*`,兜底 `README*.md`、`docs/zh/*.md` 中标题含「快速入门 / 快速开始 / Quick Start」的。
   ```bash
   cd skills/quickstart-check
   python -m scripts.find_docs <repo_root> --json
   ```
2. 把候选用中文列给用户,`AskUserQuestion` 确认**每个仓评测哪一份文档**。
3. 一仓没有任何候选 → 提示用户给文档路径,或如实记「该仓无快速入门文档」(这本身就是一种文档缺陷)。

### P1 — 把文档解析成「字面步骤序列」(agent 主导,不猜不补)

通读选定文档,抽出**有序**步骤。下表是 agent **解析期**给每步打的标签(用来决定哪些步要执行、哪些只是前提/说明);其中只有 `command`(及它的 `cwd`/`expected`)会进 `steps.json` 落盘——`kind` 等是 agent 心里的分诊,**不持久化**:

| 字段 | 含义 | 是否落盘 |
|---|---|---|
| `kind` | `prerequisite`(前提声明,P2 假设满足)/ `command`(要执行)/ `expected` / `note` —— **解析期分诊,不入 steps.json** | 否 |
| `doc_quote` | 文档**原文**(逐字,含命令/路径/期望)→ `run_step --doc-quote` | 是 |
| `command` | 若是 `command` 类:**逐字**抄(含笔误,不改、不规整化)→ `run_step --cmd` | 是 |
| `cwd` | 文档指明的工作目录 → `run_step --cwd`。**没指明 cwd 怎么办**见下 | 是 |
| `expected` | 文档声称这步应得到的输出/产物/现象 → `run_step --expected` | 是 |

**cwd 缺失的处理(对齐 P3)**:`run_step` 必须给 `--cwd`。若文档**没指明**该命令在哪跑、且**前一步也没隐含**一个 cwd → 这一步判 **`DOC_AMBIGUOUS` 卡住即停**(开发者就是不知道在哪敲),**不要**替文档猜一个目录硬跑;仅当文档/上一步明确隐含了 cwd(如「进入仓根后」)才沿用。

**铁律**:只抄文档明写的;文档没写的步骤**不补**;命令**不修笔误、不补 flag、不规整化**;文档语义含糊处标 `DOC_AMBIGUOUS` 并记「歧义点」,**绝不替文档猜**。

### P2 — 确认起始状态 + 记元

- 假设文档声明的前提均满足(见上「起始状态约定」),用机器现成 CANN。
- 记录文档声明了哪些前提;**不替文档 source 环境 / 装依赖**——除非文档某步明写 `source ...` / `pip install ...`,否则不做。
- 把「选定文档 + 声明的前提」落盘(供报告引用):
  ```bash
  cd skills/quickstart-check
  python -m scripts.run_step --repo <repo> --meta --doc <文档相对仓根路径> \
    --prereq 'CANN 已装' --prereq '<文档声明的其它前提>'
  ```

### P3 — 逐步字面执行 + 单步判定(**卡住即停**)

按 P1 顺序,对每个 `command` 步:**① 执行 → ② agent 看真实输出后判定**。

```bash
cd skills/quickstart-check
# ① 忠实执行(原样命令;绝不注入文档外 env/flag/source)
python -m scripts.run_step --repo <repo> --idx <n> --cwd <doc 指明的目录> \
  --cmd '<逐字命令>' --doc-quote '<文档原文>' --expected '<文档声称的期望>'
# ② agent 对照文档期望判定(verdict ∈ OK/FAIL/DOC_AMBIGUOUS/DOC_MISSING)
python -m scripts.run_step --repo <repo> --idx <n> --judge --verdict <verdict> \
  [--defect '<缺什么/错在哪>'] [--fix '<文档应补/改成什么>']
```

`run_step` 真实落盘 命令/stdout/stderr/退出码/耗时,**绝不注入文档外的 env/flag**;执行后打印输出尾部供 agent 判定。单步判定:

| 判定 | 条件 |
|---|---|
| `OK` | 退出码符合文档隐含期望,且(若文档给了期望输出)输出命中期望 |
| `FAIL` | 退出码≠0,或输出与文档声称的期望矛盾 |
| `DOC_AMBIGUOUS` | 文档没说清这步怎么做 / cwd / 参数,无法确定地执行 |
| `DOC_MISSING` | 执行到这需要一个文档没写的前置动作才能继续 |

**遇到第一个 `FAIL` / `DOC_AMBIGUOUS` / `DOC_MISSING`(blocker)→ 立即停**(开发者就是会在这卡住),记下卡点(`--defect` + `--fix`),进 P4。

**执行期铁律**:失败**不重试、不换参数、不加 flag/env、不找替代命令、不清缓存、不改文档命令、不做文档没写的任何动作**。即使「明知怎么修」也不修。

### P4 — 结论报告(带修订建议)

产出 `CWD/cann-ops-report/doccheck/<repo>/REPORT.md`:

```bash
cd skills/quickstart-check
python -m scripts.render_report --repo <repo> \
  --out <CWD>/cann-ops-report/doccheck/<repo>/REPORT.md
```

**必备模块**:

1. **总评**:能否「纯按文档」跑通?`✅ 通` / `❌ 卡在第 N 步`;一句话结论;文档质量评级(如 可跑通 / 卡死跑不通)。
2. **逐步台账**:每步 序号 / 文档原文 / 实际命令 / cwd / 退出码 / 判定,**每步链到 `steps/<idx>.*.log`(完整真实日志)**。
3. **文档缺陷清单**:每条 现象 / 文档原文 / 缺什么 or 错在哪 / **修订建议(文档应补/改成什么)** / **真实输出摘录**(`render_report` 自动从该步 stderr/stdout 尾部取)。
4. **卡点详情**(若卡住):停在第 N 步、该步文档原文 + **真实报错** + 为什么纯按文档无法继续。

> 即:**台账**链完整日志、**缺陷/卡点**段附真实输出摘录(`render_report.py` 现行行为)。失败/输出**必须是真实执行日志**;推断项标 `(推断)`,与真实摘录严格区分。

## 铁律与禁忌

- ✗ 不做文档明写之外的任何操作(装依赖 / source 环境 / 加 flag/env / 改命令 / 清缓存 / 换工具)。
- ✗ 不探索 / 不找 workaround / 不绕过——**哪怕知道解法**(探索会掩盖文档缺陷,违背本 skill 目的)。
- ✗ 不修文档里的笔误 / 错误命令(逐字照跑,把错误当缺陷记下)。
- ✗ 文档歧义 / 缺步不替它补全或猜测(记为缺陷,卡住即停)。
- ✗ 不假定仓名 / 路径 / 文档 / SOC(每次会话发现或 `AskUserQuestion`)。
- ✗ 不凭空捏造报告(失败必 grep 真实日志)。
- ✓ CANN 默认已装好,用机器现成 CANN(唯一的「环境给定」前提)。

## 运行位置

文档的 build / run 步骤需 NPU + CANN → **执行落到昇腾环境**(远程服务器 / 容器,零硬编码,每次发现或询问);文档发现、解析、报告可本地。范式同 ops-test:`ssh <host> 'docker exec <ctr> bash -lc "<命令>"'`(或直连)。

> **远程执行时产物落点**:`run_step` / `render_report` 在哪跑,`cann-ops-report/doccheck/` 就落在那台机器的 CWD。所以**整套 P2–P4 在同一处跑**(都在远程,或 steps.json 同步回本地后本地 `render_report`),别让台账和报告分散两地。常见做法:在远程一个固定 CWD 跑完 P2–P4,再把 `REPORT.md` 拉回本地看。

## Output(产物:`cann-ops-report/doccheck/`,每仓一个子目录)

```
cann-ops-report/doccheck/<repo>/
├── doc_meta.json          ← 选定文档 + 声明的前提条件
├── steps.json             ← 逐步台账(机读)
├── steps/<idx>.<slug>.log ← 每步真实执行日志(完整 stdout/stderr)
└── REPORT.md              ← 结论报告(给人看,带修订建议)
```

**`doc_meta.json` 字段**(`run_step --meta` 写):

| 字段 | 含义 |
|---|---|
| `doc` | 选定文档相对仓根的路径 |
| `declared_prerequisites` | 文档声明、本 skill 假设已满足的前提(字符串数组) |

**`steps.json` 字段**(`run_step` 执行写 + agent `--judge` 补判定;步骤数=数组长度):

| 字段 | 含义 |
|---|---|
| `idx` | 步序号 |
| `doc_quote` | 文档原文 |
| `command` / `cwd` | 实际逐字执行的命令 + 工作目录 |
| `expected` | 文档声称的期望 |
| `exit_code` / `duration_s` / `timed_out` | 真实执行结果 |
| `stdout_excerpt` / `stderr_excerpt` / `log_path` | 输出尾部摘录 + 完整日志路径 |
| `verdict` | `UNJUDGED` → agent 判 `OK`/`FAIL`/`DOC_AMBIGUOUS`/`DOC_MISSING` |
| `defect` / `fix_suggestion` | agent 填:缺什么/错在哪 + 修订建议 |

## Failure modes

| 触发 | 行为 |
|---|---|
| 选定仓无任何快速入门文档 | 不执行任何步骤;`run_step --meta --doc '(无)' --prereq '该仓未提供快速入门文档'` 后直接 `render_report`(无步骤 → 报告自动出「无可执行步骤」),总评判「文档缺位」缺陷(文档缺位本身是缺陷) |
| 文档某步 `FAIL`/歧义/缺步 | 卡住即停,记卡点,进 P4 出报告 |
| 文档命令含明显笔误 | **照笔误执行**,把笔误当缺陷记下,不修 |
| 想到了 workaround | **禁止使用**,只记「文档缺此步」+ 修订建议 |
