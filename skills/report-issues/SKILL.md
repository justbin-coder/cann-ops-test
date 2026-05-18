---
name: report-issues
description: 用于把 ops-test 跑测产生的失败算子转为上游 GitHub / Gitee 社区可受理的 issue 草稿，支持半自动提交。涉及"给失败算子提 issue / 向社区报告失败 / 上报 bug 给开源社区 / report failures to upstream"等用户意图时必须激活本 skill。
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
2. 否则在仓路径执行 `git -C <repo_path> remote get-url origin`，正则识别 `github.com` / `gitee.com`
3. 推不出（remote 不存在 / URL 不是这俩域名 / 内部镜像）→ `AskUserQuestion` 问 platform + owner + repo
4. 写回 `repos.json`

### P2 — 去重

读 `CWD/cann-ops-report/issues/state.json`，对每个 `(repo, op, failure_type)` 三元组：
- `new` → 进入 P3
- `already_submitted` → 默认跳过，呈现"已跳过 N 项；如需重提加 --force"

### P3 — 同时生成 3 种粒度草稿

调用 `scripts.orchestrate.generate_drafts(...)`，全部写入 `CWD/cann-ops-report/issues/drafts/<repo>/`：

- `per_op/<op>__<failure_type>.md`：一算子一草稿
- `by_type/<failure_type>.md`：按失败类型聚合
- `whole_repo.md`：整仓一篇

每篇统一 body：环境 / 失败算子表 / 复现命令 / 错误日志摘录（grep ERROR|undefined|failed|exit=，≤80 行）/ 建议 labels。

### P4 — 用户选粒度

`AskUserQuestion` 呈现 4 选项：
```
三种粒度的草稿已写到 cann-ops-report/issues/drafts/，请选：
  A. per_op    （N 个文件）
  B. by_type   （M 个文件）
  C. whole_repo（每仓 1 篇）
  D. 我先看，等下告诉你
```

用户后续用自然语言改稿（"把 grouped_matmul 那篇标题改成…"），skill 直接 Edit drafts/ 下对应文件。

### P5 — 提交决策（自然语言驱动）

**用户说"我自己提"**：
1. 对选定粒度的每篇草稿构造 prefilled URL（`scripts.url_builder.build_prefilled_url(...)`）
2. URL ≥ 7500 字节 → 降级为"打开空白 issue 页 + 输出草稿路径"，交互里告知降级
3. 输出 URL + 草稿路径对照表，结束
4. **不写 state.json**，提供后置子命令 `mark-submitted`

**用户说"你帮我提"**：
1. GitHub：`gh issue create --repo {o}/{r} --title ... --body-file <draft> --label ...`
   - 提交前先 `gh auth status`；未登录则 fatal "先 gh auth login"
2. Gitee：
   - 读 `GITEE_TOKEN` env；没有 → `AskUserQuestion` 单次 prompt
   - 提交成功后 `AskUserQuestion` 询问是否写入 shell 配置（详见 token 写入流）
   - 调 `scripts.submit.submit_gitee(...)`
3. 解析 issue URL → 写入 `state.json` + `submitted/<repo>/<id>.json`

## Token 写入 env 流（Gitee 专用）

详见 `scripts/token_helper.py`。

触发：用户选"你帮我提" + env 无 `GITEE_TOKEN` + 单次 prompt 提交成功后。

```
AskUserQuestion:
  "已用本次会话提供的 token 成功提了 N 个 issue。要不要写入 shell 配置以后免再问？
     A. 写到 ~/.bashrc
     B. 写到 ~/.zshrc
     C. 写到 ~/.profile
     D. 不用"
```

- 选 A/B/C：grep 目标文件是否已有 `GITEE_TOKEN=` 行
  - 有 → 让用户选"覆盖 / 跳过"
  - 无 → 追加 `\nexport GITEE_TOKEN=<token>\n` 到末尾
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
- `drafts/<repo>/{per_op,by_type,whole_repo}/` — 草稿
- `submitted/<repo>/<id>.json` — 已提交记录
