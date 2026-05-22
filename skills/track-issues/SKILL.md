---
name: track-issues
description: 用于查询已提交到上游社区（GitHub / Gitee / GitCode）的算子 issue 回复状态；若评论给出可执行方案则自动应用并复测；PASS 则关闭 issue + 写入 FAQ，FAIL 则人工确认后追问。涉及"查 issue 回复 / 跟 issue 走一遍 / 按社区方案重试 / retest with community fix"等用户意图时必须激活本 skill。
---

# cann-ops:track-issues

查询已提 issue 的社区回复状态，自动应用可执行修复方案并复测，PASS 则关闭 issue 并写入 FAQ，FAIL 则人工确认后追问。

## 前置检查

1. `cann-ops-report/issues/state.json` 必须存在且包含至少一条记录。
   - 不存在 → 中止，告知用户：「还没提过 issue，请先用 `cann-ops:report-issues`」。
2. 工作目录（CWD）就是项目根目录，所有产物写 `CWD/cann-ops-report/`，不写 plugin 安装目录。

## P0 — 范围确认

读 `cann-ops-report/issues/state.json`，按 repo 分组列出已提交 issue 及 submitted_at。

用 `AskUserQuestion` 呈现：

```
已提交 N 个 issue（按仓分组）：
  ops-transformer: A 个
  ops-cv:          B 个
  ...
要查哪些？
  A. 全部查
  B. 只查某些 repo（请指定）
  C. 只查最近 7 天内新提的
```

确定范围后，还需要知道目标 SOC（复测用）。如果用户消息中没有指明，询问：「`--soc` 是什么？（如 ascend950）」

## P1 — 拉评论

对每个选定的 issue_url，调用 `scripts/fetch_comments.py` 中的 `fetch()`：

```python
from scripts.fetch_comments import fetch
comments = fetch(issue_url, raise_on_error=False)
```

结果落盘到 `cann-ops-report/issues/comments/<repo>/<issue_id>.json`。

分类：
- 返回 `{"status": "deleted_upstream"}` → 标注已删除，跳过。
- 返回 `{"status": "fetch_failed", ...}` → 打印 warning，跳过。
- 评论列表为空 → `no_reply`，跳过。
- 评论全部 `author` 等于提交者自己 → `self_only`，跳过。
- 其余 → 进入 P2。

## P2 — 方案识别

对每个有外部评论的 issue，调用 `solution_extractor.classify(comments)` 获取候选方案列表：

```python
from scripts.solution_extractor import classify
candidates = classify(comments)
```

向用户汇报（中文，结构化）：

```
issue #N（ops-transformer / grouped_matmul）共 M 条评论，识别出 K 条候选方案：
  1. [env]     「ASCEND_GLOBAL_LOG_LEVEL=1」  author=@maintainer  confidence=high
  2. [patch]   「修改 op_kernel/foo.cpp:42」  author=@contributor confidence=med
  3. [discuss] 「能否提供更多日志」                               confidence=low (actionable=no)
```

用 `AskUserQuestion` 让用户选：
- A. 走方案 1（或用户指定编号）
- B. 跳过这个 issue
- C. 我先看 `cann-ops-report/issues/comments/<repo>/<id>.json` 稍后再说

`discuss` 类（actionable=False）仅展示，不列为可选项。

用户选定方案后落盘 `cann-ops-report/issues/plans/<issue_id>.json`。

## P3 — 应用方案 + 复测

调用 `apply_plan.build_plan()` 生成可执行计划：

```python
from scripts.apply_plan import build_plan
ctx = {
    "repo": repo,
    "op": op,
    "failure_type": failure_type,
    "repo_path": "<用户本地仓路径，需询问>",
    "issue_id": issue_id,
}
plan = build_plan(solution=candidate, context=ctx)
```

`repo_path` 是本地仓目录，若未提供，询问：「`<repo>` 的本地路径是什么？」

**upgrade 类**：`plan["requires_user_action"] == True`，提示用户手动 `git pull` / 切 tag 后再继续（等用户确认后继续跑 retest）。

**patch 类**：`apply_plan` 会自动在 `repo_path` 创建 `track-issue-<id>` 分支，告知用户，询问是否继续跑测。

然后调 `retest_orchestrator.retest()` 复测：

```python
from scripts.retest_orchestrator import retest
result = retest(plan=plan, context={
    "repo": repo,
    "op": op,
    "repo_path": repo_path,
    "soc": soc,
})
```

复测时打印：「正在对 `<repo>/<op>` 应用 `<kind>` 方案并复测，请稍候…」

## P4 — 写 FAQ + 回写社区

### 复测 PASS

1. 写入 FAQ：

```python
from scripts.faq_writer import upsert
from scripts._error_sig import signature, first_error_line
upsert(
    repo=repo, op=op, failure_type=failure_type,
    error_signature=signature(first_error_line(original_log_path)),
    fix_kind=plan["kind"],
    fix_payload=plan["payload"],
    source_issue_url=issue_url,
    verified_phase="phase1",
    soc=soc,
)
```

2. 生成并自动发送评论 + 关闭 issue：

```python
from scripts.reply_builder import build_pass_reply
from scripts.upstream_writer import post_comment, close_issue

body = build_pass_reply(
    repo=repo, op=op, soc=soc,
    fix_kind=plan["kind"],
    fix_summary=str(plan["payload"]),
)
post_comment(issue_url, body)
close_issue(issue_url)
```

3. 更新 state.json 该条目加 `status: "closed_by_track_issues"`, `closed_at: <ISO8601>`。

### 复测 FAIL

1. 生成草稿评论：

```python
from scripts.reply_builder import build_fail_reply
body = build_fail_reply(
    repo=repo, op=op, soc=soc,
    fix_kind=plan["kind"],
    fix_summary=str(plan["payload"]),
    error_snippet=result["detail"][-500:],
)
```

2. 展示草稿，用 `AskUserQuestion` 询问：
   - A. 直接发送
   - B. 我来修改（草稿路径：`cann-ops-report/issues/replies/<repo>/<id>.draft.md`）
   - C. 暂不发送

3. 选 A → `post_comment(issue_url, body)`；选 B/C → 写草稿文件告知路径。

4. state.json 不改（issue 仍开着）；落盘 `cann-ops-report/issues/replies/<repo>/<id>.json`。

**patch 类**无论 PASS/FAIL 均保留已创建的 git 分支，不自动删除。

## P5 — 收尾汇总

```
=== track-issues 汇总 ===
共查 N 个 issue：
  ✅ X 已 PASS 闭环（已 close）
  ❌ Y FAIL 已追问
  ⏳ Z 还没有社区回复
  ⏭  W 已跳过
FAQ 新增 X 条 → 查看 cann-ops-report/faq/FAQ.md
```

## 错误处理速查

| 情况 | 处理 |
|------|------|
| state.json 不存在 | fatal，告知先跑 report-issues |
| fetch_comments fetch_failed | warning + 跳过 |
| issue 已被删除（404） | 标注 deleted_upstream，跳过 |
| apply_plan ValueError（无法解析方案） | 告知用户，提供手动操作建议 |
| apply_plan RuntimeError（非 git 目录） | 询问正确 repo_path |
| retest 超时 | 标记 FAIL，进入 FAIL 分支 |
| upstream_writer 失败 | 告知用户评论未发出，展示草稿路径 |
| GITEE_TOKEN / GITCODE_TOKEN 未设置 | 在 P1 前检测，提示 `export GITEE_TOKEN=...` |

## 红线

- 不读原仓源码做新诊断（这是 ops-test 的职责）
- 不修改原仓工作区（源码方案一律走新分支）
- 不替代 report-issues 提新 issue（只处理已提交的）
- 不持久化 token 到文件（仅读环境变量）
- 不覆盖 ops-test 写的 run_state.json（只追加 retest 记录）
