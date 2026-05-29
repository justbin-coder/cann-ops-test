---
name: report-issues
description: 用于把 ops-test 跑测产生的失败算子转为上游 GitHub / Gitee / GitCode 社区可受理的 issue 草稿，支持半自动提交。涉及"给失败算子提 issue / 向社区报告失败 / 上报 bug 给开源社区 / report failures to upstream"等用户意图时必须激活本 skill。
---

# cann-ops:report-issues

把 `ops-test` 跑测后的失败算子转成上游社区 issue。**默认只生成草稿**，由用户在交互中决定"我自己提"（输出 prefilled URL）还是"agent 帮我提"（调 gh CLI 或 Gitee API）。本地 state.json 跨多轮跑测去重。

## 强制激活规则

凡触发以下意图，必须先激活本 skill，再行动：
- "给失败算子提 issue" / "向社区报告失败" / "提个 issue 给上游"
- "report failures to community" / "open upstream issues for failed ops"
- 提 issue 前需要批量生成草稿
- 已经手工提了 issue，需要回写 state.json 标已提交

## 前置条件

- **必须**已经跑过 `cann-ops:ops-test` 并产出 `CWD/cann-ops-report/test/run_state.json`
- **可选**跑过 `cann-ops:scann-repo`：有 `_intermediate.json` 则草稿带 950 特性命中，否则该段空

## 工作流（P0–P5）

### P0 — 范围确认（中文交互）

1. 读 `CWD/cann-ops-report/test/run_state.json`；不存在则 fatal："请先跑 cann-ops:ops-test"
2. 过滤 `status ∈ {BUILD_FAIL, INSTALL_FAIL, RUN_EXIT_FAIL, RUN_PATTERN_FAIL, TIMEOUT}`，按 `(repo, failure_type)` 分组
3. 用 `AskUserQuestion` 呈现：
   ```
   发现 N 个仓的失败算子：
     ops-transformer: X 个失败（BUILD_FAIL=A, RUN_EXIT_FAIL=B, ...）
     ops-cv:          Y 个失败（...）
   全部都要走 issue 流程吗？
     A. 全部
     B. 只选某些仓 / 某些失败类型（接下来给我列表）
   ```

### P1 — 解析每个仓的 platform/owner/repo

对每个圈定的仓：
1. 命中 `CWD/cann-ops-report/issues/repos.json` 缓存 → 跳过
2. 否则在仓路径执行 `git -C <repo_path> remote get-url origin`，正则识别 `github.com` / `gitee.com` / `gitcode.com`
3. 推不出（remote 不存在 / URL 不是上述三个域名 / 内部镜像）→ `AskUserQuestion` 问 platform + owner + repo
4. 写回 `repos.json`

### P2 — 去重

读 `CWD/cann-ops-report/issues/state.json`，对每个 `(repo, op, failure_type)` 三元组：
- `new` → 进入 P3
- `already_submitted` → 默认跳过，呈现"已跳过 N 项；如需重提加 --force"

### P3 — 生成 per-op 草稿

每个失败算子对应一个 issue 草稿，这是开源社区的基本规范——维护者需要独立追踪、关闭、打 label，混合多算子会导致 issue 无法闭环。

调用 `scripts.orchestrate.generate_drafts(...)`，写入 `CWD/cann-ops-report/issues/drafts/<repo>/<op>__<failure_type>.md`：

每篇统一 body：环境 / 复现命令 / 错误日志摘录（grep ERROR|undefined|failed|exit=，≤80 行）/ 建议 labels。

### P4 — 草稿审阅确认

草稿生成后，用 `AskUserQuestion` 询问：

```
已为 N 个失败算子生成 issue 草稿（每算子一个）：

  ops-transformer: grouped_matmul、flash_attention_score …（X 个）
  ops-cv:          resize_bilinear_v2 …（Y 个）

草稿路径：cann-ops-report/issues/drafts/

  A. 直接进入提交流程
  B. 我先看一下草稿，改好再告诉你
```

- 选 B → 告知草稿路径，等用户回来；用户后续用自然语言改稿（"把 grouped_matmul 那篇标题改成…"），skill 直接 Edit 对应文件
- 选 A → 进入 P5

### P5 — 提交决策（自然语言驱动）

**用户说"我自己提"**：
1. 对每篇草稿构造 prefilled URL（`scripts.url_builder.build_prefilled_url(...)`）
2. URL ≥ 7500 字节 → 降级为"打开空白 issue 页 + 输出草稿路径"，交互里告知降级
3. 输出 URL + 草稿路径对照表
4. **立即用 `AskUserQuestion` 追问确认**（不等用户主动回来）：
   ```
   请把你提交成功的 issue URL 告诉我，我帮你写入记录（以便后续 track-issues 跟踪）。
   每行一个，格式：<issue_url>  对应草稿：<draft_filename>
   没有成功提交的留空即可。
   ```
5. 用户回复后，对每个确认的 URL 调用 `mark_submitted.mark_from_draft_path(..., status="submitted")` 写入 `state.json`（**必须带 `status="submitted"`**，供 track-issues P0 状态分组使用）；
   同时写 `submitted/<repo>/<id>.json`（`id` 从 URL 末位数字段提取）。
6. 汇报：「已记录 N 条，state.json 路径：`CWD/cann-ops-report/issues/state.json`」

**用户说"你帮我提"**：

**[提交前预览 — 必做，不可跳过]** 在对话中逐篇输出每篇草稿的完整标题 + 正文（不截断），然后用 `AskUserQuestion` 询问：

```
即将提交以下 N 篇 issue，请预览确认：

━━━ [1/N] <repo> / <op_name> ━━━
标题：<draft 实际标题>
正文：
<draft 完整正文>

...（每篇以分隔线隔开）

确认提交以上 N 篇 issue 吗？
  A. 全部提交
  B. 我先看/修改草稿，稍后再告诉你
  C. 取消，本次不提交
```

- 选 B / C → 告知草稿目录路径（`cann-ops-report/issues/drafts/<repo>/`），流程结束，**不调任何 API**
- 选 A → 继续以下平台提交步骤

1. GitHub：`gh issue create --repo {o}/{r} --title ... --body-file <draft> --label ...`
   - 提交前先 `gh auth status`；未登录则 fatal "先 gh auth login"
2. Gitee：
   - 读 `GITEE_TOKEN` env；没有 → `AskUserQuestion` 单次 prompt
   - 提交成功后 `AskUserQuestion` 询问是否写入 shell 配置（详见 token 写入流）
   - 调 `scripts.submit.submit_gitee(...)`
3. GitCode：
   - 读 `GITCODE_TOKEN` env；没有 → `AskUserQuestion` 单次 prompt
   - 调 `scripts.submit.submit_gitcode(...)`，**走 `api.gitcode.com/api/v5` 子域名**（`gitcode.com/api/*` 被 CloudWAF 拦截，绕不过）
   - `labels` 传 CSV 字符串，**绝不传数组**（GitCode v5 与 Gitee v5 一致，传数组 422）
4. 解析 issue URL → 调 `dedup.mark_submitted(..., status="submitted")` 写入 `state.json`（**必须带 `status="submitted"`**）+ `submitted/<repo>/<id>.json`

## Token 写入 env 流（Gitee / GitCode）

详见 `scripts/token_helper.py`。env var：Gitee 用 `GITEE_TOKEN`，GitCode 用 `GITCODE_TOKEN`。通过 `token_helper.env_var_for_platform(platform)` 选取。

触发：用户选"你帮我提" + env 无对应 token + 单次 prompt 提交成功后。

```
AskUserQuestion:
  "已用本次会话提供的 token 成功提了 N 个 issue。要不要写入 shell 配置以后免再问？
     A. 写到 ~/.bashrc
     B. 写到 ~/.zshrc
     C. 写到 ~/.profile
     D. 不用"
```

- 选 A/B/C：grep 目标文件是否已有 `<env_var>=` 行
  - 有 → 让用户选"覆盖 / 跳过"
  - 无 → 追加 `\nexport <env_var>=<token>\n` 到末尾
  - 写后明确提示："token 以明文存储在该文件中"
- 选 D：不动文件

## 边界与禁忌

- ✗ 不重跑测试、不读算子源码做新诊断
- ✗ 不在 plugin 或 `cann-ops-report/` 任何子目录持久化 token
- ✗ 不修改 ops-test 的 `run_state.json` / `logs/`
- ✗ 不假设 SOC（必须用 `AskUserQuestion` 收 SOC，与 ops-test 一致）
- ✗ 不自动创建上游不存在的 labels（不存在则静默忽略）

## 数据来源（输入）

| 来源 | 强弱 |
|---|---|
| `cann-ops-report/test/run_state.json` | 强依赖 |
| `cann-ops-report/test/logs/<repo>/<op>.phase{N}.{step}.log` | 强依赖 |
| `cann-ops-report/test/failures/<repo>/<op>.md` | 弱依赖（"已尝试的诊断"段） |
| `cann-ops-report/scann/<repo>/_intermediate.json` | 弱依赖（950 特性命中、is_delegated） |
| `git -C <repo_path> remote get-url origin` | 弱依赖（platform 推断） |
| `$ASCEND_HOME_PATH/version.info` | 弱依赖（CANN 版本） |

## 产物路径

所有产物在 `CWD/cann-ops-report/issues/`：
- `state.json` — 去重状态
- `repos.json` — repo → (platform, owner, repo) 缓存
- `drafts/<repo>/<op>__<failure_type>.md` — 草稿（每算子一文件）
- `submitted/<repo>/<id>.json` — 已提交记录
