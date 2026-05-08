# cann-ops

CANN 950 算子全流程工具 plugin，包含两个子 skill：

| Skill | 触发方式 | 用途 |
|---|---|---|
| `cann-ops:scann-repo` | 扫描仓、生成白名单 | 扫描 CANN ops 仓，识别依赖 950 硬件特性的算子（hif8/simt/RegBase/CV融合），输出跑测靶子清单 |
| `cann-ops:ops-test` | 跑测、续跑、诊断、生成报告 | 对目标算子执行 Phase 1-4 跑测，支持仓间并发 + 合并 build + 单算子兜底，并生成最终报告 |

## 目录结构

```
cann-ops-plugin/
├── .claude-plugin/plugin.json      # plugin manifest
├── package.json
├── README.md
└── skills/
    ├── scann-repo/
    │   ├── SKILL.md                # 扫描工作流指令
    │   ├── requirements.txt        # Python 依赖
    │   ├── scripts/                # 扫描脚本（相对路径调用）
    │   │   ├── scan_repo.py
    │   │   ├── render_report.py
    │   │   ├── write_whitelist.py
    │   │   ├── state.py
    │   │   └── ...
    │   ├── templates/              # 报告模板（Jinja2）
    │   │   ├── summary.md.j2
    │   │   └── detail.md.j2
    │   └── exemptions/             # 豁免清单
    └── ops-test/
        ├── SKILL.md                # 跑测工作流指令
        ├── inputs/                 # 目标算子配置
        │   ├── ops-transformer.json
        │   ├── ops-cv.json
        │   ├── ops-math.json
        │   └── ops-nn.json
        └── scripts/                # 跑测脚本（相对路径调用）
            ├── run_phase1_batched.py
            ├── run_phase1_fallback.py
            ├── phase_examples.py
            ├── state.py
            ├── utils.py
            └── ...
```

## 安装

### 1. 克隆

```bash
git clone https://github.com/your-org/cann-ops-plugin.git ~/cann-ops-plugin
```

### 2. 安装 Python 依赖

```bash
# scann-repo 依赖
pip install -r ~/cann-ops-plugin/skills/scann-repo/requirements.txt

# ops-test 依赖（Python 3.8+，无额外 pip 包，仅需 CANN toolkit 已安装）
```

### 3. 注册 plugin

编辑 `~/.claude/plugins/installed_plugins.json`，在 `plugins` 节点追加：

```json
"cann-ops@local": [
  {
    "scope": "user",
    "installPath": "/path/to/your/cann-ops-plugin",
    "version": "1.0.0",
    "installedAt": "2026-01-01T00:00:00.000Z",
    "lastUpdated": "2026-01-01T00:00:00.000Z"
  }
]
```

### 4. 配置环境变量（ops-test 必须）

在 `~/.bashrc` / `~/.zshrc` 里追加：

```bash
# CANN 安装后会自动设置 ASCEND_HOME_PATH，ops-test 从此推导 set_env.sh 路径
# 如果未自动设置，手动指定：
export ASCEND_HOME_PATH=~/Ascend/ascend-toolkit/latest/aarch64-linux

# ops 源码仓的根目录（4 个仓 clone 到哪里）
export CANN_REPOS_PATH=~/cann    # 默认 ~/cann，按实际情况修改
```

### 5. 重启 Claude Code

重启后，skill 列表中会出现：
- `cann-ops:scann-repo`
- `cann-ops:ops-test`

## 使用

### 扫描算子

```
用户："用 cann-ops 扫描 ops-transformer"
→ Claude 激活 cann-ops:scann-repo，引导完成 API 白名单生成 + 仓扫描
```

### 跑测

```
用户："对 ops-cv 的目标算子跑一遍 phase 1"
→ Claude 激活 cann-ops:ops-test，按并发拓扑执行 build/install/run
```

### 生成报告

```
用户："生成本次跑测报告"
→ Claude 读 outputs/run_state.json + 日志，生成 outputs/PHASE1_FINAL_REPORT.md
```

## 状态文件路径

| 文件 | 路径 | 说明 |
|---|---|---|
| scann-repo 状态 | `~/.config/cann-ops/scann-repo-state.json` | 白名单路径、PDF 指纹 |
| ops-test 运行状态 | `skills/ops-test/outputs/run_state.json` | 63 个算子的跑测状态 |
| ops-test 日志 | `skills/ops-test/outputs/logs/` | 每个算子的 build/install/run 日志 |

## 硬件要求

- Ascend 950 NPU
- CANN toolkit（安装后 `ASCEND_HOME_PATH` 自动设置）
- Python 3.8+
