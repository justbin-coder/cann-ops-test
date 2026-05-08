# cann-ops

CANN 950 算子全流程工具 plugin，包含两个子 skill：

| Skill | 用途 |
|---|---|
| `cann-ops:scann-repo` | 扫描 CANN ops 仓，识别依赖 950 硬件特性的算子（hif8/simt/RegBase/CV融合），输出跑测靶子清单 |
| `cann-ops:ops-test` | 对目标算子执行 Phase 1-4 跑测，支持仓间并发 + 合并 build + 单算子兜底，并生成最终报告 |

## 工作目录约定

两个 skill 均以用户**当前工作目录（CWD）**为 I/O 根路径，不在 plugin 安装目录写任何数据：

```
<用户 CWD>/
├── 950-scann/               ← scann-repo 的扫描产物
│   └── <repo>/
│       ├── summary.md
│       ├── detail.md
│       └── _intermediate.json   ← ops-test 从此读取目标算子
└── 950-test/                ← ops-test 的跑测产物
    ├── run_state.json
    ├── logs/
    └── PHASE1_FINAL_REPORT.md
```

## 安装

### 1. 添加 marketplace 并安装（两条命令）

```bash
claude plugin marketplace add justbin-coder/cann-ops-test
claude plugin install cann-ops@cann-ops-test
```

### 2. 重启 Claude Code

重启后 skill 列表出现 `cann-ops:scann-repo` 和 `cann-ops:ops-test`。

## 使用

### 扫描仓

```
用户："用 cann-ops 扫描 ops-transformer"
```

首次运行时 skill 会自动检查并安装 Python 依赖，然后引导填写 Ascend C API 文档路径。

扫描产物写入 `CWD/950-scann/ops-transformer/`。

### 跑测

```
用户："对 ops-cv 的 950 算子跑 phase 1"
```

首次运行时 skill 会询问各 ops 仓的本地路径并保存到 `~/.config/cann-ops/config.json`，后续自动读取，无需重复配置。

跑测产物写入 `CWD/950-test/`。

### 生成报告

```
用户："生成本次跑测报告"
```

报告写入 `CWD/950-test/PHASE1_FINAL_REPORT.md`。

## 硬件要求

- Ascend 950 NPU
- CANN toolkit（安装后 `ASCEND_HOME_PATH` 自动设置，skill 从中推导 set_env.sh，无需手动配置）
- Python 3.8+
