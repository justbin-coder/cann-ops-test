---
name: setup-env
description: 为 CANN 算子仓搭建可构建/可跑测的基础环境——发现并 source CANN toolkit、检查系统构建依赖（cmake/gcc/ccache…）、按 CANN 版本把算子仓切到配套 tag、把仓依赖装进 conda 环境、单算子冒烟验证。涉及"搭环境/装环境/初始化/准备 CANN 环境/配 conda/bootstrap/setup/为跑测准备机器"等用户意图时使用。机器布局、CANN 版本、conda 是否存在、python 版本均每次会话运行时探测或询问，绝不硬编码到某台机器。
---

# cann-ops:setup-env

把一台**裸机/新服务器**搭成「能 build/跑测 CANN 算子仓」的基础环境。是 `scann-repo → ops-test → report-issues → track-issues` 闭环的**前置第 0 步**。

**核心原则：泛化、零硬编码。** 任何一台机器的具体布局（CANN 装在哪、哪个版本激活、有没有 conda、python 几点几）都只是「当前个例」，一律**运行时探测或 `AskUserQuestion` 询问**，不写死。

## 强制激活规则

涉及以下意图，先激活本 skill：
- 「搭/装/初始化环境」「准备 CANN 环境」「配 conda」「bootstrap / setup」
- 新机器/新服务器要开始跑算子，但 `source set_env.sh` 没法直接用、仓还没拉、依赖没装
- ops-test 跑测前报「ASCEND_HOME_PATH 未设置 / build.sh 缺依赖 / 仓在 master 编不过」

## 设计约定（必须守住）

- **零硬编码**：CANN 路径、版本、仓名、仓 host、SOC、python 版本、conda env 名——全部探测/询问。脚本里的默认值只是「常见值」，呈现给用户确认。
- **零持久化配置**：不写 `~/.config`、不改 shell rc（除非用户明确要求）。产物落 `CWD/cann-ops-report/setup/`。
- **全程中文**交互。
- **副作用先确认**：创建 conda env、`pip install`、`sudo` 装系统包、`git clone`、`git checkout` tag——每类先列计划、经用户点头再做；支持 `CANN_OPS_DRY_RUN=1` 全程干跑（只探测+出计划，不改任何东西）。
- **不替用户 sudo**：系统包（ccache 等）缺失只报告 + 给安装命令，由用户决定是否装。

## 模式

| 模式 | 状态 | 说明 |
|---|---|---|
| **conda（裸机/虚拟环境）** | ✅ 已实现 | conda env + source CANN toolkit；本 skill 当前主路径 |
| **container（容器）** | 🔜 扩展位 | 后续 `docker run` + 挂载 workspace + 容器内复用同一套 P 节点；SKILL 预留 mode 分叉，脚本逻辑容器/裸机通用 |

> 用户没指明则默认 conda 模式；明确说「在容器里搭」时走 container（当前提示「容器模式待开放，可先用 conda 模式」）。

## 工作流（P0–P6，每步可被 DRY_RUN 拦在“出计划”为止）

所有脚本以模块跑，**cwd 在本 skill 目录**（`skills/setup-env/`）。

### P1 — 探测现状（只读，先看清再动）

```bash
python3 scripts/detect_env.py --json     # 或不带 --json 看人读摘要
```

一次性给出：CANN（set_env.sh 路径 / 真实 ASCEND_HOME_PATH / 解析出的版本 / ready）、conda（是否可用 + 已有 env）、系统构建依赖（cmake/gcc/g++/make/git 必需 + ccache 可选）、可见 python 解释器。

把摘要用中文呈现给用户，作为后续每步的依据。

- **CANN `ready=false`**（没探到 set_env.sh）：提示用户 CANN toolkit 可能未装或在非常见路径，用 `AskUserQuestion` 让用户给 set_env.sh 路径 → `--set-env <path>` 重探；仍无 → 指引装 CANN，止步。
- **版本解析**：以 `ASCEND_HOME_PATH` 的 basename（如 `cann-9.0.0-beta.1`）为准，**不取 driver 版本**（`/usr/local/Ascend/version.info` 那种 25.x 是 driver，不是 CANN）。

### P2 — 系统构建依赖

读 P1 结果：
- `missing_required` 非空（cmake/gcc/g++/make/git 任一缺）→ 列出缺的 + 对应安装命令（按发行版给 `yum/apt/dnf`），**让用户去装**（可能要 sudo），装完回到 P1 复探。
- `ccache` 缺：只提示「装上构建更快、不阻塞」，给安装命令，用户可跳过。

### P3 — conda 环境

读 P1 的 `conda`：
- **conda 不可用**：`AskUserQuestion` 问用户：
  - A. 装 miniconda（给出官方安装脚本命令，用户确认后执行或自行装）
  - B. 改用 python `venv`（用 P1 探到的某个 python 解释器建 venv）
  - C. 已有别处的 conda，手动给路径
- **conda 可用**：问用户用**已有 env** 还是**新建**；新建则问 env 名 + **python 版本**（不写死——把 P1 探到的可用 python 版本列给用户选，或问用户指定；说明「与目标 CANN/容器一致更稳」）。

创建命令形如（确认后执行）：`conda create -y -n <env> python=<ver>`。

### P4 — 算子仓：定位 / clone + 切配套 tag（关键）

> **教训固化**：算子仓 master 是中间态（算子代码升级到新 opbase 宏但 opbase pin 落后），直接编撞缺符号。**必须切到与 CANN 版本配套的 tag**。

先只读出计划：

```bash
python3 scripts/repo_setup.py plan \
  --cann-version <P1解析出的版本> \
  --repos ops-cv,ops-math,ops-nn,ops-transformer \
  --search-root <用户workspace> [--search-root <更多根>] \
  --git-base <仓host，默认 https://gitcode.com/cann> --json
```

每仓给出 `action`（checkout / clone_then_checkout / no_matching_tag_*）、`target_tag`、可用 tag 样本。把计划用中文列给用户：

- 已有仓 + 匹配到 tag → 确认后 `git -C <path> fetch --tags && git -C <path> checkout <tag>`
- 没仓 + 远端有匹配 tag → 确认后 `git clone <url> <dest> && git -C <dest> checkout <tag>`
- **`no_matching_tag_*`（只有 master/main）→ 不要静默用 master**。报给用户：远端无配套 tag，问是否（a）用最接近的 tag（b）暂用 master 并知会风险（c）跳过该仓。

仓名、host、目标版本、落地目录都从 P1/用户来，**不写死**。

### P5 — 把仓依赖装进 conda 环境

仓拉好后，**发现每个仓声明的 Python 依赖**再装（不预设清单）：
- 找各仓的 `requirements*.txt` / `setup.py` / `pyproject.toml` / `docs` 里写的依赖
- 把发现的依赖**汇总去重**，中文列给用户确认
- 在**目标 conda env / venv 内**执行 `pip install ...`（确认后；`CANN_OPS_DRY_RUN=1` 只打印不装）
- 找不到任何依赖声明 → 如实说明「未发现仓级 Python 依赖声明」，问用户是否手动补（如 numpy、torch_npu 等）

> 装的是**这四个仓构建/跑测需要的依赖**，不是本插件 skill 自己的依赖。

### P6 — 单算子冒烟验证

挑一个仓、一个最小算子，证明「环境真能编出算子包」：

```bash
python3 scripts/smoke_build.py --repo-path <repo> --soc <用户给的SOC> \
  --set-env <P1的set_env.sh> [--op <算子，可省自动挑>] [--jobs 0]
```

成功（exit0 + 出 `.run`）→ 环境就绪。失败 → grep `log_tail` 报真实错误，按错误指向回到 P2/P3/P4 修。**SOC 必须询问用户**（`ascend950` 等），不假设。

### 汇报

把 P1–P6 结果写 `CWD/cann-ops-report/setup/env_report.md`（人读）+ `status.json`（机读），中文总结「已就绪/待办」，并指引下一步 `cann-ops:scann-repo`。

## 边界与禁忌

- ✗ 不把任何机器的具体路径/版本/布局写死到脚本或 SKILL（一律探测/询问）
- ✗ 不替用户 `sudo` 装系统包（只报告 + 给命令）
- ✗ 不静默把仓停在 master 编（无配套 tag 必须问用户）
- ✗ 不改宿主 shell rc / 全局环境（除非用户明确要求）
- ✗ 不假设 conda 一定存在、不假设 python 版本（运行时探/问）
- ✗ 不假设 SOC（冒烟构建前必须询问用户）
- ✗ 副作用（建 env / pip / clone / checkout）一律先确认或 `CANN_OPS_DRY_RUN=1` 干跑

## 附录：常见问题（FAQ）

裸机/新机搭建反复会遇到的环境坑，见 [`docs/FAQ.md`](docs/FAQ.md)（每条「现象 → 根因 → 解法」）：
conda ToS 未接受致 `conda create` 失败、国内 conda/pip 镜像被封需回退代理、`npu-smi -8005`（不在 `HwHiAiUser` 组）、国际网慢需 scp 离线装 miniconda、共享磁盘满需最小足迹、仓缺 `OP_LOGE_FOR_INVALID_*` 需切配套 tag。
