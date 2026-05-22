# cann-ops:track-issues 设计文档

- 日期：2026-05-22
- 作者：jiazhibin48@gmail.com（昇腾 CANN 技术生态 DR）
- 状态：设计已经过对话评审，待用户复核 spec 后进入 writing-plans

## 0. 背景与动机

cann-ops-plugin 当前已有：

- `cann-ops:scann-repo`：扫 950 特性算子
- `cann-ops:ops-test`：跑测 Phase 1–4
- `cann-ops:report-issues`：把失败算子转成上游 GitHub / Gitee / GitCode 社区 issue 并提交，本地 `cann-ops-report/issues/state.json` 跨轮去重

目前断点：issue 提交之后没有回路。社区回复 → 应用方案 → 复测 → 关闭 issue → 沉淀知识，这一闭环只能人工拼。

本设计新增 `cann-ops:track-issues` skill 并在 `ops-test` 末端加一个 FAQ lookup hook，把闭环跑通：

```
ops-test 失败 → report-issues 提 → 社区回复 → track-issues 查回复 + 复测 + 写 FAQ + 回写社区
                                                       ↓ 写入
                                              cann-ops-report/faq/known_fixes.json
                                                       ↓ 失败时查询
ops-test 下次失败 → P5.5 hook 命中已知 fix → 一键重试
```

## 1. 范围与红线

**新增 skill**：`cann-ops:track-issues`（独立交付，与 report-issues 并列）。

**改动现有 skill**：`cann-ops:ops-test` 在失败诊断之后加一段 `P5.5 — FAQ Lookup`，约 30 行调用，不动现有 phase 脚本。

**强制激活意图**（track-issues 的关键词）：

- "查一下提的 issue 有没有回复" / "看下 issue 状态" / "social 回复了吗"
- "按社区方案重试" / "跟 issue 走一遍" / "retest with community fix"

**激活前置**：`cann-ops-report/issues/state.json` 存在且至少有一条已提交记录。否则中文 fatal："还没提过 issue，先 cann-ops:report-issues"。

**红线（明确不做）**：

- 不读源码做新诊断（这是 ops-test 的事）
- 不改原仓的工作区（源码方案走 `git switch -c track-issue-<id>` 新分支）
- 不替代 report-issues 提新 issue（只查、复测、回写已有 issue）
- 不持久化到 plugin 安装目录（一切落 CWD `cann-ops-report/`）

## 2. 组件分解

### 2.1 目录结构

```
cann-ops-plugin/skills/track-issues/
├── SKILL.md                    ~8 KB，描述 P0–P5
├── requirements.txt            预计仅 stdlib，可能复用 report-issues 的 jinja2
├── scripts/
│   ├── __init__.py
│   ├── paths.py                复用 report-issues paths 概念，新增 FAQ_FILE / FAQ_MD
│   ├── fetch_comments.py       拉评论：gh CLI / Gitee v5 / GitCode v5
│   ├── solution_extractor.py   评论 → 候选方案条目列表
│   ├── apply_plan.py           方案 → 可执行 plan（kind ∈ env/build_flag/cmd_arg/patch/upgrade）
│   ├── retest_orchestrator.py  组装 ops-test runner 调用参数，拉起重测
│   ├── faq_writer.py           PASS 后写 known_fixes.json + 渲染 FAQ.md
│   ├── reply_builder.py        PASS / FAIL 回写 issue 的评论 body
│   └── upstream_writer.py      调 gh / Gitee / GitCode API 评论 + close
└── tests/
    ├── conftest.py
    ├── fixtures/
    │   ├── state.json
    │   ├── comments/
    │   ├── known_fixes.json
    │   └── error_logs/
    ├── test_solution_extractor.py
    ├── test_apply_plan.py
    ├── test_faq_writer.py
    ├── test_reply_builder.py
    ├── test_fetch_comments.py
    ├── test_upstream_writer.py
    └── test_retest_orchestrator.py
```

### 2.2 ops-test 侧改动

```
cann-ops-plugin/skills/ops-test/scripts/
└── faq_lookup.py               新增：失败后 (repo, op, failure_type, error_signature) → match → 候选 fix
```

ops-test 的 SKILL.md 在 P5（失败诊断输出）之后插入 `P5.5 — FAQ Lookup`：调 `faq_lookup`，命中则 AskUserQuestion 提示是否应用 fix 重试。test 文件 `ops-test/tests/test_faq_lookup.py` 与之配套。

### 2.3 各 script 职责

| script | 输入 | 输出 | 关键约束 |
|---|---|---|---|
| `fetch_comments` | state.json 的 issue_url | `comments/<repo>/<issue_id>.json`（含 author/role/body/created_at） | gh CLI 走 `gh api`；Gitee/GitCode 走 v5 REST；author role 标记是否是 owner/collaborator |
| `solution_extractor` | comments JSON | 候选方案条目（kind, raw_text, suggested_fix, confidence） | 启发式见 §2.5 |
| `apply_plan` | 单条方案 + 原失败上下文 | `plans/<issue_id>.json`：{kind, payload, ops_test_args} | env 类生成 `--env-extra=`；build_flag 类生成 `--build-extra-args=`；patch 类先 `git switch -c track-issue-<id>` |
| `retest_orchestrator` | plan + 原算子标识 | 调用 ops-test runner 的 CLI（与现有脚本同一接口） | 不通过 skill 间接调度，直接 `subprocess.run` ops-test runner（与 ops-test 内的多仓并发同一入口） |
| `faq_writer` | (repo, op, failure_type, error_signature, plan, issue_url) | 追加 known_fixes.json + 重渲染 FAQ.md | atomic write；key 冲突走 "newer wins + 旧条目入 history" |
| `reply_builder` | retest 结果 + plan + 算子 | reply markdown body | PASS 模板含验证日志摘录；FAIL 模板含新 error 与原 error 的 diff |
| `upstream_writer` | issue_url + body + close? | API 调用 + 落 `replies/<repo>/<issue_id>.json` | 复用 report-issues 的 token_helper（GITEE_TOKEN / GITCODE_TOKEN） |
| `faq_lookup`（ops-test 侧） | 失败上下文 | 命中的 fix（或 None） | error_signature 用 normalized error line（去时间戳/路径/行号） |

### 2.4 FAQ 数据结构

`cann-ops-report/faq/known_fixes.json`：

```json
{
  "<repo>::<op>::<failure_type>::<error_signature>": {
    "fix_kind": "env" | "build_flag" | "cmd_arg" | "patch" | "upgrade",
    "fix_payload": { },
    "source_issue_url": "https://...",
    "verified_at": "ISO8601",
    "verified_phase": "phase1",
    "soc": "ascend950",
    "history": [
      { }
    ]
  }
}
```

`fix_payload` 形态随 `fix_kind`：

| fix_kind | payload 形态 |
|---|---|
| env | `{"ENV_VAR_1": "value1", "ENV_VAR_2": "value2"}` |
| build_flag | `{"flags": ["-DXXX=YYY", "-DZZZ=AAA"]}` |
| cmd_arg | `{"build_sh_args": "--soc=ascend910b --run_example op_name eager cust"}` |
| patch | `{"diff_path": "cann-ops-report/issues/patches/<repo>/<issue_id>.diff", "branch_name": "track-issue-<id>"}` |
| upgrade | `{"hint": "建议 git pull / 切到 tag vX.Y.Z 后重跑"}` |

`FAQ.md` 是 known_fixes.json 渲染出的人读版（包含每条 fix 的来源 issue 链接、复测时间、覆盖 SOC），同源单源真相。

**error_signature 算法**：取失败日志中第一条 `ERROR` / `undefined` / `failed` / `exit=` 命中行，做归一化：

1. 删时间戳（正则 `\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\.\d]*Z?`）
2. 删行号与列号（正则 `:\d+:\d+:`，`line \d+`）
3. 把绝对路径替换为相对路径（去掉 `$ASCEND_HOME_PATH`、用户 home、CWD 前缀）
4. 折叠多空白
5. 对归一化结果做 SHA-256，取前 12 个 hex 字符作为 `error_signature`

### 2.5 solution_extractor 启发式规则

按命中顺序逐条评论扫描，每条评论可产生 0 个或多个候选条目。优先级从高到低：

| fix_kind | 命中模式 | confidence |
|---|---|---|
| patch | 评论含 ```diff ... ``` / ```patch ... ``` 代码块；或链接到 PR / commit | high |
| env | 评论含 `export FOO=...` / `set FOO=...` / `FOO=... bash ...` 模式 | high if author is owner/collaborator, else med |
| build_flag | 评论含 `-D<KEY>=` / `--<flag>` 且与已知 cmake/build.sh 参数前缀匹配 | high if author is owner/collaborator, else med |
| cmd_arg | 评论含 `build.sh --run_example` / `--soc=` / `--ops=` 等具体跑测命令重写 | med |
| upgrade | 评论含 `try latest` / `git pull` / `升级到` / `tag v` / `请使用 vX.Y` 模式 | med |
| discuss | 上述都不命中、但有问号或要求更多信息 | low（actionable=no，仅展示给用户参考） |

`confidence` 用于排序候选列表呈现给用户；用户最终拍板，启发式不阻止任何选项。

## 3. 数据流与 P0–P5 时序

起点：用户在 CWD（含 state.json）说"查下提的 issue 有没有回复"。

### P0 — 范围确认

读 `cann-ops-report/issues/state.json` → 按 repo 分组列出已提交 issue（含 submitted_at）。

`AskUserQuestion` 呈现：

```
已提交 N 个 issue（按仓分组）：
  ops-transformer: A 个
  ops-cv:          B 个
  ...
要查哪些？
  A. 全部查
  B. 只查某些 repo（接下来给我列）
  C. 只查 N 天内新提的（默认 7 天）
```

### P1 — 拉评论

对每个 issue_url：

1. 域名分派：`github.com` → `gh api`；`gitee.com` → Gitee v5；`gitcode.com` → GitCode v5（`api.gitcode.com` 子域名）
2. 评论落盘 `cann-ops-report/issues/comments/<repo>/<issue_id>.json`
3. 分类：评论数 0 → `no_reply`；评论全部自发 → `self_only`；其余 → 进 P2

### P2 — 方案识别

`solution_extractor` 跑启发式给出候选方案列表。agent 用结构化模板向用户报告：

```
issue #N 共 M 条评论，识别出 K 条候选方案：
  1. [env]   「设 ASCEND_GLOBAL_LOG_LEVEL=1」  author=@maintainer  confidence=high
  2. [patch] 「修改 op_kernel/foo.cpp:42」      author=@contributor confidence=med
  3. [discuss] 「需要更多日志」                                       confidence=low (actionable=no)
```

`AskUserQuestion`：A. 走方案 1 / B. 走方案 2 / C. 跳过这个 issue / D. 我先看 comments/<id>.json 等下再说。

用户选定 → `plans/<issue_id>.json` 落盘。

### P3 — 应用方案 + 复测

`apply_plan` 把 plan 翻译成 ops-test runner CLI 参数：

- env → `--env-extra="K1=V1,K2=V2"`
- build_flag → `--build-extra-args="-DXXX=YYY"`
- cmd_arg → 重写 build.sh 的 `--run_example` 参数
- patch → `git -C <repo_path> switch -c track-issue-<id>` + `git apply --3way <diff_path>` + 在新分支跑测（diff 来源：评论中 ```diff ... ``` 代码块或附件链接，落盘到 `cann-ops-report/issues/patches/<repo>/<issue_id>.diff`）
- upgrade → 提示用户先 git pull / 切 tag（不自动 fetch）

`retest_orchestrator` 调起 ops-test runner，只跑 (repo, op, failure_type) 对应的算子。结果落 `cann-ops-report/test/run_state.json`（追加，不覆盖原 phase 记录）+ `retest_<issue_id>.json`。

### P4 — 写 FAQ + 回写社区

**PASS**：

1. `faq_writer` 追加条目（error_signature 用原失败日志的归一化签名）
2. `reply_builder` 生成"已按贵方案验证通过 + 复测日志摘录"
3. `upstream_writer` 自动 POST 评论 + close issue
4. state.json 加 `status: closed_by_track_issues, closed_at: ...`

**FAIL**：

1. `reply_builder` 生成"按方案 X 重测仍失败 + 新 error 与原 error 的 diff"
2. `AskUserQuestion`：A. 直接发 / B. 我改改这条评论 / C. 不发先存草稿
3. 发出去后落 `replies/<repo>/<issue_id>.json`，state.json 不动（issue 还开着）

patch 类无论 PASS/FAIL，分支保留在用户仓里不自动删除。

### P5 — 收尾汇总

打印中文汇总：

```
共查 N 个 issue：
  X 已 PASS 闭环（含已 close 列表）
  Y FAIL 已追问（含评论链接）
  Z 还没回复
  W 自跳过
FAQ 新增 X 条 → 查看 cann-ops-report/faq/FAQ.md
```

不持久化交互态（state.json 已是 sot）。

### P5.5 ops-test hook 时序

```
... 现有 P0–P5 跑完，失败诊断已写入 cann-ops-report/test/failures/<repo>/<op>.md
P5.5 faq_lookup:
  对所有 status ∈ {BUILD_FAIL, INSTALL_FAIL, RUN_*_FAIL} 的算子：
    计算 error_signature → 查 known_fixes.json
    命中（仅 fix_kind ∈ {env, build_flag, cmd_arg, upgrade}）：
      AskUserQuestion: "X 个失败算子在 FAQ 命中已知非源码修复，要不要应用并重试？"
      用户 yes → 调 retest_orchestrator（与 track-issues 共用同一脚本）
      用户 no  → 跳过
    无命中 → 静默
  patch 类不在 ops-test 侧自动重试（避免误改用户工作区），只在 FAQ.md 展示参考
```

### 跨 skill 状态联动

| 写者 | 文件 | 读者 |
|---|---|---|
| report-issues | `issues/state.json` | track-issues 拿 issue_url 列表 |
| track-issues | `issues/state.json` | 加 closed_at / last_replied_at / status |
| track-issues | `faq/known_fixes.json` | ops-test 失败 hook 查 |
| ops-test | `test/run_state.json` | track-issues 拿 error_signature 用于 FAQ 匹配 |
| ops-test 失败 hook | （只读 FAQ） | 无 |

## 4. 错误处理

按出问题的位置分组，每一类都说明 detect → degrade 路径。

### P0

- state.json 不存在 → fatal "还没提过 issue，先 cann-ops:report-issues"
- JSON 解析失败 → fatal 给文件路径，要求用户人工修复（不自动重写）

### P1 — 拉评论

| 故障 | detect | 行为 |
|---|---|---|
| gh CLI 未登录 | `gh auth status` 非 0 | fatal "先 gh auth login"，github issue 全部停 |
| Gitee/GitCode token 缺失 | env 没读到 | AskUserQuestion 单次 prompt（复用 report-issues 的 token_helper） |
| API HTTP 4xx | 解析返回 | 这个 issue 标 `fetch_failed: <reason>` 落盘 `comments/<id>.error.json`，继续其它 |
| API HTTP 5xx / 网络超时 | urlopen exception | 重试一次（间隔 5s），仍失败则同上 |
| issue 已删除（404） | 解析 | state.json 标 `status: deleted_upstream`，继续 |
| GitHub 速率限制（403 + rate limit header） | header 检查 | 打印剩余配额 + 等待 reset 时间，**停止整轮**让用户稍后再来（不自动 sleep 超过 10s） |

### P2 — 方案识别

- 候选方案 0 条且评论 ≥ 1 → 标 `comments_no_actionable`，把全部评论 markdown 渲染给用户人工判断
- 用户选 C. 跳过 → state.json 加 `last_checked_at`，本轮不再问该 issue
- 用户选 D. 我先看 → 退出 P2 循环，不污染 state.json，下轮重来

### P3 — 应用 + 复测

| 故障 | 行为 |
|---|---|
| patch 类，原仓不是 git 仓 / 工作区脏 | fatal "请先 commit/stash"，**不**自动 stash |
| patch 类，分支已存在 | 后缀加 `-retry-<N>` 自增创建新分支 |
| patch 应用冲突 | `git restore .` 还原，fatal 告知冲突位置，让用户人工 patch 后重新触发 |
| env/build_flag 类，ops-test runner 返回非 0 | 视作 FAIL 走 P4 FAIL 分支（不重试，避免无限循环） |
| ops-test runner 卡住（超时） | 复用 ops-test 自身的 phase timeout 机制（已存在） |

### P4 — 写 FAQ + 回写

| 故障 | 行为 |
|---|---|
| FAQ 文件已存在同 key | 用新条目覆盖，旧条目入 `history[]` |
| FAQ 写盘失败（磁盘满 / 权限） | atomic write 失败 → fatal，**不**继续上游回写（避免社区状态领先于本地） |
| 上游 POST 评论 5xx | 重试一次，仍失败则把评论落到 `cann-ops-report/issues/replies/<repo>/<issue_id>.draft.md` + 让用户手工发 |
| close issue 失败但评论已发 | 警告"评论已发，close 失败，请手工 close"，不重试 |
| FAIL 用户选 C. 不发 | 落 `cann-ops-report/issues/replies/<repo>/<issue_id>.draft.md`，state.json 加 `pending_reply: true` |

### ops-test P5.5 hook

- 读 FAQ 失败（不存在 / JSON 损坏）→ 静默跳过，**不**打断 ops-test 主流程
- 用户选"应用并重试"后 retest 失败 → 不递归再查 FAQ，避免无限循环
- error_signature 计算失败 → 跳过该算子的 FAQ 查询，继续其它

### 横切原则

- 任何分支决策点必须用 `AskUserQuestion`
- 任何 fatal 必须中文 + 给"下一步做什么"的指令
- 任何"继续跑其它"的策略，在 P5 收尾里要明确报告失败的 issue 列表

## 5. 测试策略

延续 cann-ops-plugin 现有约定（每个 script 一个 pytest 文件，stdlib + unittest.mock，零真实 NPU / 零真实 API）。

### 5.1 pytest 文件清单

每个 script 一个 test 文件（路径见 §2.1）：

- `test_solution_extractor.py`：启发式分类正负样本（每种 fix_kind ≥ 3 例）+ discuss-only 负样本
- `test_apply_plan.py`：各 fix_kind → ops-test CLI 参数字符串映射；patch 类分支命令字符串
- `test_faq_writer.py`：新增 / 覆盖 + history；atomic write；key 冲突；error_signature 归一化（去时间戳/行号/绝对路径）
- `test_reply_builder.py`：PASS / FAIL 模板，patch 类附加分支信息
- `test_fetch_comments.py`：URL 分派 + 错误码处理（404 / 403 / 5xx），用 `unittest.mock` 拦截 urlopen / subprocess.run
- `test_upstream_writer.py`：三平台 POST 评论 body 形状；close API 调用；重试逻辑
- `test_retest_orchestrator.py`：mock subprocess 验证调起 ops-test runner 的 CLI 参数串完整
- `test_faq_lookup.py`（ops-test 侧）：命中 / 未命中 / FAQ 文件不存在不抛错

外加：

- `test_end_to_end_dry_run.py`：喂 fixture state.json + 假评论 → 走到 plan.json 写盘，不真跑 ops-test、不真发 API

### 5.2 fixtures

- `fixtures/state.json` — 3 个 repo / 5 条已提交 issue（GitHub × 2、Gitee × 2、GitCode × 1）
- `fixtures/comments/*.json` — 每平台一个真实形态样本
- `fixtures/known_fixes.json` — 覆盖各 fix_kind 的种子
- `fixtures/error_logs/*.txt` — error_signature 归一化的输入样本

### 5.3 不做的事

- 不真调 gh / Gitee / GitCode API（速率 / 认证不稳）
- 不真跑 NPU（CI / 开发机没有 ASCEND_HOME_PATH）
- 不试图 mock 出完整跑测产物，直接喂 fixture
- 不写 e2e UI 测试

注：以上"不真跑"只限 plugin 仓自身的 pytest。用户在生产侧使用 track-issues skill 时，P3 复测会真的调起 ops-test 跑 NPU——这是 skill 存在的意义。

### 5.4 手工验收清单（用户验收用）

1. 故意把一个 ops-test 跑测的失败提到自家测试仓 → 评论一个 `export ASCEND_GLOBAL_LOG_LEVEL=1` → 跑 track-issues → 验证：识别到 env 类 → AskUserQuestion 拍板 → ops-test 复测 PASS → 自动评论+close → FAQ.md 新增条目
2. 故意造 ops-test 失败 → 不查 issue，直接重跑 ops-test → 验证 P5.5 hook 提示 FAQ 命中且能一键应用
3. patch 类：评论给 diff → 验证创建分支 `track-issue-<id>` → 应用 → 跑测 → 留分支不删
4. 404 issue：验证 state.json 标 `deleted_upstream` 不影响其它

## 6. 设计总结

- skill 新增：`cann-ops:track-issues`（P0–P5）
- skill 改动：`cann-ops:ops-test` 末端加 ~30 行 FAQ hook
- 新增产物根目录：`cann-ops-report/faq/`（known_fixes.json + FAQ.md）
- 跨 skill 解耦：通过 state.json / known_fixes.json / run_state.json 三个文件，不直接相互调用
