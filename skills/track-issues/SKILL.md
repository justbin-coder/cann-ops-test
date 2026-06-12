---
name: track-issues
description: 用于查询已提交到上游社区（GitHub / Gitee / GitCode）的算子 issue 回复状态；agent 自主理解评论中的修复方案，应用并复测；PASS 则关闭 issue + 写入 FAQ，FAIL 则人工确认后追问。涉及"查 issue 回复 / 跟 issue 走一遍 / 按社区方案重试 / retest with community fix"等用户意图时必须激活本 skill。
---

# cann-ops:track-issues

查询已提 issue 的社区回复状态，**agent 自主读懂评论里的修复方案**，应用并复测，PASS 则关闭 issue 并写入 FAQ，FAIL 则人工确认后追问。

## 设计原则

- **方案理解交给 agent，不依赖正则**：`apply_plan` 只是执行原语，agent 必须自己读 comments 决定 kind / suggested_fix。永远不要回退到"用正则提候选"的旧思路——那样必然漏。
- **元数据先自动发现，再问人**：SOC / repo_path / failure_type 都有持久化来源（state.json / run_state.json / issue body），把 `context_discovery` 跑一遍后只问真不知道的字段。
- **写副作用全部经过用户确认**：发评论 / 关 issue / 创建 git 分支 / 执行 shell 清理，每一步都用 `AskUserQuestion` 确认或提供 `CANN_OPS_DRY_RUN=1` 预演。

## 前置检查

**issue 记录文件位置**：`CWD/cann-ops-report/issues/state.json`

1. 检查 `cann-ops-report/issues/state.json` 是否存在且包含至少一条记录：

   - **不存在 / 为空** → 用 `AskUserQuestion` 询问：
     ```
     还没有已提交 issue 的记录。你是否已在浏览器里手动提过 issue？
       A. 是，我来提供 issue URL，帮我注册到记录里
       B. 还没提过，先去跑 cann-ops:report-issues
     ```
     - 选 A → 进入**手动注册流**（见下）
     - 选 B → fatal 退出

   - **存在** → 正常进入 P0

2. 工作目录（CWD）就是项目根目录，所有产物写 `CWD/cann-ops-report/`，不写 plugin 安装目录。

### 手动注册流（state.json 不存在时）

请用户逐条提供 issue URL。**对每条 URL，agent 应当先尝试自动发现元数据**：

```python
# 1. 直接 curl 拿 issue body：
#    curl -s "https://api.gitcode.com/api/v5/repos/<owner>/<repo>/issues/<num>?access_token=$GITCODE_TOKEN"
# 2. 从 URL 推断 repo（最后一段 owner/repo）
# 3. 从 issue title 推断 op 名（通常 title 形如 "[Bug] <op>: ..."）
# 4. 从 issue body 表格 / 标题推断 failure_type 和 SOC
```

把推断结果展示给用户用 AskUserQuestion 确认（给候选 + Other），然后调：

```python
import sys
sys.path.insert(0, "<plugin-root>/skills/report-issues/scripts")
import dedup
dedup.mark_submitted(
    repo=repo, op=op, failure_type=failure_type,
    issue_url=issue_url, phase="phase1", submitted_via="manual",
    soc=soc,   # ← 关键：把 SOC 一并存进 state.json，下次复测无需再问
)
```

注册完毕后告知：「已注册 N 条记录，进入跟踪流程。」继续 P0。

## P0 — 范围确认

读 `cann-ops-report/issues/state.json`，**按 status 分组**展示，让用户一眼看清闭环进度：

```
已提交 N 个 issue：
  ⏳ 等待回复 (X)：ops-transformer / moe_init_routing #9999
  🔁 有回复待处理 (Y)：ops-nn / quant_batch_matmul_v3 #2859
  📌 PR 待合并 (Z)：...
  ✅ 已闭环 (W)：ops-nn / quant_batch_matmul_v3 #2749（含 follow-up #2859）
  ❌ 复测失败待追问 (V)：...
要查哪些？
  A. 全部查（跳过已闭环）
  B. 只查等待回复的
  C. 只查某些 repo（请指定）
```

**status → 展示分组映射**（`dedup.load_all()` 读全表后按此分类）：

| status 值 | 展示分组 |
|---|---|
| `submitted` / 无 status 字段 | ⏳ 等待回复 |
| `replied_discuss` / `replied_pr_pending` | 🔁 有回复待处理 |
| `plan_selected` | 🔁 方案已选，等复测 |
| `closed_pass` / `closed_by_track_issues` | ✅ 已闭环 |
| `closed_by_track_issues_partial` | ✅ 已闭环（含 follow-up） |
| `retest_fail` | ❌ 复测失败待追问 |
| `closed_upstream` | ✅ 上游已关闭 |
| `deleted_upstream` | （不展示，跳过） |

**不要单独问 SOC** —— 把它留到 P3 复测前自动发现。

## P1 — 拉评论 + issue 开关状态

对每个选定的 issue_url，**同时**拉评论和 issue 开/关状态：

```python
from scripts.fetch_comments import fetch, fetch_issue_state
import sys
sys.path.insert(0, "<plugin-root>/skills/report-issues/scripts")
import dedup
from datetime import datetime

now_iso = lambda: datetime.now().isoformat(timespec="seconds")

comments    = fetch(issue_url, raise_on_error=False)
issue_state = fetch_issue_state(issue_url, raise_on_error=False)
```

**同时拉 issue body**（不是 comments，是 issue 本身）保存到 `cann-ops-report/issues/bodies/<repo>/<issue_id>.txt`，
P3 的 SOC 自动发现会用到它。

**issue 开关状态处理**（优先于评论分类）：

```python
if issue_state.get("state") == "closed":
    # 上游 maintainer 已关闭（不是我们关的）
    dedup.update_status(repo, op, failure_type,
        status="closed_upstream",
        closed_at=issue_state.get("closed_at"),
        last_checked_at=now_iso())
    # 提示用户，跳过 P2
    print(f"issue #{issue_id} 已被上游关闭，跳过。")
    continue
```

**每次拉完评论都更新 last_checked_at**（无论 open/closed）：

```python
current_status = dedup.get_record(repo, op, failure_type).get("status", "submitted")
dedup.update_status(repo, op, failure_type,
    status=current_status,
    last_checked_at=now_iso())
```

结果落盘到 `cann-ops-report/issues/comments/<repo>/<issue_id>.json`。

评论分类：
- `{"status": "deleted_upstream"}` → `dedup.update_status(..., status="deleted_upstream")`，跳过
- `{"status": "fetch_failed", ...}` → 打印 warning，跳过（不改 status）
- 评论列表为空 → `no_reply`，跳过
- 评论全部 `author` 等于提交者自己 → `self_only`，跳过
- 其余 → 进入 P2

## P2 — 方案理解（agent 自主完成，不调任何"分类器"）

**对每个有外部评论的 issue，agent 必须自己读 `comments[i].body`，回答三个问题：**

1. **这条评论有没有给"动作"？**
   - "我们会修 / PR 进行中 / 等下个版本" → 没有立刻可执行的动作 → 归为 `pr_pending`（actionable=False），仅展示
   - "请提供更多日志 / 能否复现" → 没有动作，归为 `discuss`（actionable=False），仅展示
   - "做 X / 执行 Y / 用 Z" → 有动作，进入下一步

2. **动作的形态是什么？** 按下面"方案模板附录"对号入座选 kind：

   | kind | 形态 | 示例 |
   |---|---|---|
   | `env` | 设环境变量 | `ASCEND_GLOBAL_LOG_LEVEL=1` |
   | `build_flag` | cmake / 构建参数 | `-DENABLE_HIF8=ON` |
   | `cmd_arg` | build.sh 多加参数 | `build.sh --pkg --extra-flag` |
   | `clean` | 跑测前的清理命令 | `pkill bisheng; rm -rf kernel_meta_*` |
   | `patch` | 提供代码 diff | 评论里 ` ```diff ... ``` ` |
   | `upgrade` | 切版本 / 拉新代码 | "升级到 v2.1 / git pull" |

   遇到**不在表里的新形态**：
   - 如果本质是 shell 命令序列 → 归 `clean`
   - 如果本质是给 build.sh 加参数 → 归 `cmd_arg`
   - 如果本质是改源码 → 归 `patch`
   - **永远不要**因为"形态没见过"就放弃可执行的方案

3. **这条方案的 confidence**：
   - 评论作者带 MEMBER / OWNER / COLLABORATOR 角色 → `high`
   - 普通贡献者 → `med`
   - actionable=False（pr_pending / discuss）→ 不算候选

把每个 issue 的候选清单结构化呈现给用户。**如果有多个 actionable 方案，在展示列表前加一行优先级提示**：

```
【建议顺序】无副作用方案优先：设环境变量 / 构建参数 → 清理遗留文件 → 源码修改。
先试低成本方案，失败再升级，避免工作区被意外改动。
```

然后展示候选清单：

```
issue #N（ops-nn / quant_batch_matmul_v3）共 M 条评论，识别出 K 条候选方案：
  1. [设环境变量]   「ASCEND_GLOBAL_LOG_LEVEL=1」  来自 @cong-jiyu  可信度：中（普通贡献者）
  2. [清理遗留文件] 「pkill -f bisheng; rm -rf kernel_meta_*」  来自 @cong-jiyu  可信度：中
  3. [等待 PR 合并] 「会删除 qbmmv3 的冗余依赖 → PR #5065」 来自 @liuyufan0725  (无法自动执行，仅供参考)
```

**展示规则**：
- kind 用中文描述（env→设环境变量、build_flag→调构建参数、cmd_arg→调命令行参数、clean→清理遗留文件、patch→修改源码、upgrade→升级版本）
- actionable 方案标序号可选；pr_pending / discuss 不标序号，放列表末尾标"仅供参考"
- 只有一个 actionable 方案时，省略优先级提示，直接询问"是否应用此方案？"

用 `AskUserQuestion` 让用户选 actionable 候选，pr_pending / discuss 仅展示不可选。

用户选定后落盘 `cann-ops-report/issues/plans/<issue_id>.json`：

```json
{
  "kind": "clean",
  "suggested_fix": "pkill -f ${ASCEND_HOME_PATH}/bin/bisheng;rm -rf scripts/kernel/binary_script/kernel_meta_*",
  "confidence": "med",
  "source": {"author": "cong-jiyu", "created_at": "2026-05-19T14:10:19+08:00"}
}
```

## P3 — 应用方案 + 复测

### P3.0 — 自动发现 SOC / repo_path（先于任何询问）

```python
from scripts.context_discovery import discover_soc, discover_repo_path

issue_body = open(f"cann-ops-report/issues/bodies/{repo}/{issue_id}.txt").read()
soc = discover_soc(
    repo=repo, op=op, failure_type=failure_type,
    issue_body=issue_body,
)
repo_path = discover_repo_path(repo)
```

**只有当返回 None 时才问用户**。同一次 P3 内**一次性问完**所有缺失字段。

### P3.1 — build_plan

```python
from scripts.apply_plan import build_plan
ctx = {
    "repo": repo, "op": op, "failure_type": failure_type,
    "repo_path": repo_path, "issue_id": issue_id,
}
plan = build_plan(solution=chosen_candidate, context=ctx)
```

各 kind 的副作用：

| kind | apply_plan 做什么 | 用户确认必要性 |
|---|---|---|
| env / build_flag / cmd_arg | 只生成 args，不动文件 | 否 |
| upgrade | `requires_user_action=True`，提示用户手动 `git pull`，等用户确认后继续 | **是**（用户必须确认已切到新版本） |
| patch | 在 `repo_path` 创建 `track-issue-<id>` 分支 + 写 .diff 到 `cann-ops-report/issues/patches/`。**不自动 git apply**，告知用户分支已建 | **是**（询问是否继续复测） |
| clean | 解析 cleanup 命令到 `plan.pre_cleanup_commands`；拒绝针对 `/`, `/home`, `/usr`, `/etc` 等 root 的 `rm`/`find -delete` | **是**（展示命令清单让用户确认） |

### P3.2 — retest_orchestrator

```python
from scripts.retest_orchestrator import retest
result = retest(plan=plan, context={
    "repo": repo, "op": op, "repo_path": repo_path, "soc": soc,
})
```

复测时打印：「正在对 `<repo>/<op>` 应用 `<kind>` 方案并复测，请稍候…」

`retest` 会：
1. 先在 `repo_path` 下执行 `plan.pre_cleanup_commands`（shell=True, timeout=300/cmd）
2. 调 `run_phase1_batched.py` 跑 phase1
3. **从 `run_state.json` 读权威 status**（不再 grep stdout）→ 返回 PASS / FAIL / ERROR

### P3.3 — partial-PASS 判定（必看）

`retest` 只回 PASS / FAIL / ERROR 总判，但 phase1 跑测可能"build/install 成功 + 部分 examples 失败"。**这种情况要单独识别**，因为：

- 原 issue 报的是 BUILD_FAIL / INSTALL_FAIL → 已恢复
- 但 run 阶段有**全新的**失败面 → 跟原 issue 是不同问题

判定流程：

1. 读 `cann-ops-report/<repo>/test/phase1_report_final.json`，找 `repos[repo].ops[op]`
2. 看 `phase1.examples`（list of `{name, status}`）
3. 如果 `examples` 全成功 → 真 PASS
4. 如果至少一个 example PASS 且至少一个 FAIL → **partial-PASS**
5. 全 FAIL → 真 FAIL（走 P4 FAIL 分支）

**partial-PASS 走 P4 的 "partial-PASS" 分支**（详见下方），不是 PASS 也不是 FAIL。

## P4 — 写 FAQ + 回写社区

### 复测 PASS

1. 写入 FAQ：

```python
from scripts.faq_writer import upsert
from scripts._error_sig import signature, first_error_line
upsert(
    repo=repo, op=op, failure_type=failure_type,
    error_signature=signature(first_error_line(original_log_path)),
    fix_kind=plan["kind"], fix_payload=plan["payload"],
    source_issue_url=issue_url,
    verified_phase="phase1", soc=soc,
)
```

2. 生成并发送评论 + 关闭 issue（**默认 dry-run 一次给用户看**，确认后再真发）：

```python
import os
os.environ["CANN_OPS_DRY_RUN"] = "1"

from scripts.reply_builder import build_pass_reply
from scripts.upstream_writer import post_comment, close_issue

body = build_pass_reply(
    repo=repo, op=op, soc=soc,
    fix_kind=plan["kind"], fix_summary=str(plan["payload"]),
)

# [预览确认 — 必做] 在对话中展示完整回评内容（不截断），格式：
# ─────────────────────────────────────────
# 将向 {issue_url} 发送以下评论并关闭 issue：
#
# {body 完整内容}
# ─────────────────────────────────────────
# 然后 AskUserQuestion：
#   A. 确认发送并关闭 issue
#   B. 我先修改（写入 cann-ops-report/issues/replies/<repo>/<id>.draft.md，改好告诉我）
#   C. 暂不发送
# 选 B/C → 写草稿文件告知路径，流程结束
# 选 A → 清 CANN_OPS_DRY_RUN，再真发

os.environ["CANN_OPS_DRY_RUN"] = "1"
post_comment(issue_url, body)   # dry-run，只 print 不发
close_issue(issue_url)           # dry-run
# 选 A → 清掉环境变量再真发
```

3. 更新 state.json 该条目加 `status: "closed_by_track_issues"`, `closed_at: <ISO8601>`。

### 复测 partial-PASS

build/install 已成功、部分 examples 失败的情况。原 issue 视为已修复，但必须为 follow-up 失败开新 issue 并链回原 issue。

```python
from scripts.reply_builder import (
    build_partial_pass_reply,
    build_followup_issue_body,
)
from scripts.upstream_writer import post_comment, close_issue, create_issue
from scripts.faq_writer import upsert
from scripts._error_sig import signature, first_error_line

# 1. 从 phase1_report_final.json 抽 pass/fail examples 清单
import json
report = json.load(open("cann-ops-report/<repo>/test/phase1_report_final.json"))
examples = report["repos"][repo]["ops"][op]["phase1"]["examples"]
passed = [e["name"] for e in examples if e["status"] == "PASS"]
failed = [e["name"] for e in examples if e["status"] != "PASS"]

# 2. 抓 run.log 里的错误片段
run_log = f"cann-ops-report/<repo>/test/logs/{repo}/{op}.phase1.run.log"
error_snippet = subprocess.run(
    ["grep", "-nE", "ERROR:|failed\\.", run_log],
    capture_output=True, text=True,
).stdout[-1500:]

# 3. 在同一上游仓开 follow-up issue（先 dry-run 给用户看）
repo_url = issue_url.rsplit("/issues/", 1)[0]   # 把 issue URL 砍成仓 URL
followup_title = f"[{repo}] {op} {','.join(failed)} fail at runtime on {soc} (follow-up to #{issue_id})"
followup_body = build_followup_issue_body(
    repo=repo, op=op, soc=soc,
    source_issue_url=issue_url,
    fix_kind=plan["kind"], fix_summary=str(plan["payload"]),
    failed_examples=failed,
    error_snippet=error_snippet,
)

# [预览确认 — 必做] 在对话中展示将要新建的 follow-up issue 草稿（完整标题 + 正文，不截断），格式：
# ─────────────────────────────────────────
# 将在 {repo_url} 新建以下 follow-up issue：
# 标题：{followup_title}
# 正文：
# {followup_body 完整内容}
# ─────────────────────────────────────────
# 然后 AskUserQuestion：
#   A. 确认新建
#   B. 我先修改草稿（告诉我修改内容）
#   C. 不新建
# 选 B/C → 告知 followup_body 草稿路径，暂不创建 issue
# 选 A → 清 CANN_OPS_DRY_RUN，再 create_issue() 一次拿真 URL

os.environ["CANN_OPS_DRY_RUN"] = "1"
followup_url = create_issue(repo_url, title=followup_title, body=followup_body)
# 选 A → 清 dry-run，再 create_issue() 一次拿真 URL

# 4. 原 issue 走 partial-PASS 回评 + close
reply = build_partial_pass_reply(
    repo=repo, op=op, soc=soc,
    fix_kind=plan["kind"], fix_summary=str(plan["payload"]),
    original_failure_type=failure_type,
    pass_count=len(passed), total_count=len(examples),
    failed_examples=failed,
    followup_issue_url=followup_url,
)

# [预览确认 — 必做] 在对话中展示将向原 issue 发送的回评内容（完整，不截断），格式：
# ─────────────────────────────────────────
# 将向 {issue_url} 发送以下评论并关闭 issue：
#
# {reply 完整内容}
# ─────────────────────────────────────────
# 然后 AskUserQuestion：
#   A. 确认发送并关闭 issue
#   B. 我先修改（告诉我修改内容）
#   C. 暂不发送
# 选 B/C → 写草稿文件告知路径，流程结束
# 选 A → 真发

post_comment(issue_url, reply)
close_issue(issue_url)

# 5. FAQ 还是要写 —— 原 issue 的修复方案是有效的
upsert(
    repo=repo, op=op, failure_type=failure_type,
    error_signature=signature(first_error_line(original_log_path)),
    fix_kind=plan["kind"], fix_payload=plan["payload"],
    source_issue_url=issue_url,
    verified_phase="phase1", soc=soc,
)

# 6. state.json：原 issue 标 closed_by_track_issues_partial；同时记 follow-up URL
dedup.update_status(repo, op, failure_type,
    status="closed_by_track_issues_partial",
    closed_at=now_iso(),
    followup_issue_url=followup_url)

# 7. 把 follow-up issue 注册为可独立追踪的 state.json 条目（必须做，否则 track-issues 下次不知道追踪它）
dedup.mark_submitted(
    repo=repo, op=op,
    failure_type="RUN_EXIT_FAIL",       # follow-up 报告的是运行期失败
    issue_url=followup_url,
    phase="phase1",
    submitted_via="track_issues_followup",
    soc=soc,
    status="submitted",
    parent_issue_url=issue_url,         # 反向关联，方便溯源
)
```

**红线**：
- follow-up issue **必须**在 body 里写 `Follow-up to <original_issue_url>` —— 这是给 maintainer 看的关联线索
- follow-up **必须**在步骤 7 注册到 state.json，否则 track-issues 下次运行时无法追踪其回复和闭环
- partial-PASS 不算 PASS 也不算 FAIL，是单独的第三状态

### 复测 FAIL

1. 生成草稿评论：

```python
from scripts.reply_builder import build_fail_reply
body = build_fail_reply(
    repo=repo, op=op, soc=soc,
    fix_kind=plan["kind"], fix_summary=str(plan["payload"]),
    error_snippet=result["detail"][-500:],
)
```

2. 展示草稿，用 `AskUserQuestion` 询问：
   - A. 直接发送
   - B. 我来修改（草稿路径：`cann-ops-report/issues/replies/<repo>/<id>.draft.md`）
   - C. 暂不发送

3. 选 A → 清掉 dry-run 真发；选 B/C → 写草稿文件告知路径。

4. state.json 不改（issue 仍开着）；落盘 `cann-ops-report/issues/replies/<repo>/<id>.json`。

**patch 类**无论 PASS/FAIL 均保留已创建的 git 分支，不自动删除。

## P5 — 收尾汇总

```
=== track-issues 汇总 ===
共查 N 个 issue：
  ✅ X 已 PASS 闭环（已 close）
  🟡 P partial-PASS（原问题修好，已开 follow-up issue）
  ❌ Y FAIL 已追问
  ⏳ Z 还没有社区回复
  📌 W pr_pending（等上游合并）
  ⏭  V 已跳过
FAQ 新增 X 条 → 查看 cann-ops-report/faq/FAQ.md
follow-up issue：
  - <repo>/<op> → <new_issue_url>  (follow-up to #<original>)
```

## 方案模板附录（agent 参考，非穷举）

下面列举常见社区回复形态供 agent 对号入座。**遇到新形态时按"形态本质"归类到最接近的 kind**，不要因为没见过就放弃。

### env

```
请设置 export ASCEND_GLOBAL_LOG_LEVEL=1 再重试
```
→ `{"kind": "env", "suggested_fix": "ASCEND_GLOBAL_LOG_LEVEL=1"}`

### build_flag

```
cmake 加 -DENABLE_HIF8=ON
```
→ `{"kind": "build_flag", "suggested_fix": "-DENABLE_HIF8=ON"}`

### cmd_arg

```
试试 build.sh --pkg --soc=ascend950 --ops=foo --no_aicpu
```
→ `{"kind": "cmd_arg", "suggested_fix": "--pkg --soc=ascend950 --ops=foo --no_aicpu"}`

### clean

```
这个是上次编译遗留文件导致，请执行：
pkill -f ${ASCEND_HOME_PATH}/bin/bisheng;
rm -rf scripts/kernel/binary_script/kernel_meta_*
后重新构建
```
→ `{"kind": "clean", "suggested_fix": "pkill -f ${ASCEND_HOME_PATH}/bin/bisheng;rm -rf scripts/kernel/binary_script/kernel_meta_*"}`

### patch

```
试试这个 diff：
\`\`\`diff
--- a/op_kernel/foo.cpp
+++ b/op_kernel/foo.cpp
@@ -42 +42 @@
-old line
+new line
\`\`\`
```
→ `{"kind": "patch", "suggested_fix": "--- a/op_kernel/foo.cpp\n..."}`

### upgrade

```
请升级到 v9.0.1，这个问题在 commit abc123 已修复
```
→ `{"kind": "upgrade", "suggested_fix": "升级到 v9.0.1，commit abc123"}`

### pr_pending（不可自动执行，仅展示给用户）

```
会删除 qbmmv3 的冗余依赖 → https://gitcode.com/cann/ops-nn/pull/5065
```
→ 归为 `pr_pending`，向用户展示 PR 链接，不进入 P3。

### discuss（不可自动执行）

```
能否提供完整的构建日志和环境变量？
```
→ 归为 `discuss`，向用户展示，不进入 P3。

## 错误处理速查

| 情况 | 处理 |
|------|------|
| state.json 不存在 | AskUserQuestion：手动注册 or 先跑 report-issues |
| fetch_comments fetch_failed | warning + 跳过 |
| issue 已被删除（404） | 标注 deleted_upstream，跳过 |
| apply_plan ValueError（unknown kind） | 检查 agent 选的 kind 是否在支持列表内 |
| apply_plan ValueError（refusing destructive） | 检查 clean 命令是否针对 `/`, `/home` 等 root |
| apply_plan RuntimeError（非 git 目录） | 询问正确 repo_path |
| retest 超时 | 标记 FAIL，进入 FAIL 分支 |
| upstream_writer 失败 | 告知用户评论未发出，展示草稿路径 |
| GITEE_TOKEN / GITCODE_TOKEN 未设置 | 在 P1 前检测，提示 `export GITEE_TOKEN=...` |
| context_discovery 返回 None | 此时（且只有此时）才用 AskUserQuestion 问用户 |

## 红线

- **不要回退到正则分类器**：agent 必须自己读评论，不再调任何 `solution_extractor.classify`（该模块已删除）
- 不读原仓源码做新诊断（这是 ops-test 的职责）
- 不修改原仓工作区（源码方案一律走新分支）
- 不替代 report-issues 提新 issue（只处理已提交的）
- 不持久化 token 到文件（仅读环境变量）
- 不覆盖 ops-test 写的 run_state.json（只追加 retest 记录）
- clean kind 不允许针对 `/`, `/home`, `/root`, `/usr`, `/etc`, `/var`, `/opt` 的 `rm` 或 `find -delete`
