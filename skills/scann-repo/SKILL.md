---
name: scann-repo
description: Scans a CANN ops repository (ops-transformer / ops-cv / ops-math / ops-nn) for operators that depend on Ascend 950 hardware features (simt / hif8 / RegBase / cube+vector fusion) and produces a markdown checklist for the test team. Use when the user wants to find 950-related operators, refresh the API whitelist, or scan a CANN repo for 950 coverage.
---

# cann-ops:scann-repo

Identify operators in CANN open-source ops repos that depend on Ascend 950 hardware features, output a target list for the test team.

## 首次运行前置检查（P0）

激活后先检查 Python 依赖，缺失则自动安装：

```bash
python3 -c "import jinja2, pdfplumber, pypdf" 2>/dev/null \
  || pip install -r scripts/requirements.txt
```

## When to invoke

- "用 cann-ops 扫一下 ops-transformer"
- "扫描 ops-math 的 950 特性算子"
- "重新生成白名单"
- 任何要列出 "950 相关算子" 的请求

## Inputs

- 目标仓的路径（用户给路径或仓名，默认 cwd）
- API 文档路径（首次问一次，之后存在 `~/.config/cann-ops/scann-repo-state.json`）

## Workflow

### 1. 定位目标仓

- 用户给了路径/仓名 → 用它
- 没给 → 用 cwd
- 校验 `<root>/docs/zh/op_list.md` 是否存在；不存在 → fatal，告诉用户"这看起来不是 CANN ops 仓"

### 2. 检查白名单状态

读 `~/.config/cann-ops/scann-repo-state.json`（用 `scripts.state.load_state`）。

- state 不存在 → 进入 §3 对话式抽取
- state 存在，但白名单 MD 不在 `<api_doc_path>/` → 进入 §3 对话式抽取
- state 存在且 MD 都在 → 校验 PDF SHA（读 `<api_doc_path>/WHITELIST_SOURCE.md`），匹配 → 直接进 §4 扫描；不匹配 → 询问"PDF 已变，是否刷新白名单？"，同意走 §3，拒绝则警告后进 §4

### 3. 对话式抽取白名单

#### 3a. 询问 API 路径

如果 state.json 已有 `api_doc_path`，默认沿用并提示"使用上次的路径 X，如要更换请告知"。否则：

> 我需要 Ascend C API 的 PDF 文档来生成 950 接口白名单。
> 请告诉我 PDF 放在哪个路径（单个 .pdf 或包含分册的目录）。

#### 3b. 校验路径

- 路径存在
- 至少 1 份 *.pdf
- 路径可写（`os.access(path, os.W_OK)`）；不可写 → fatal，提示用户换路径或改权限

#### 3c. 抽取章节（LLM + pdf skill）

调用环境的 PDF 库（`pypdf` 读 outline + `pdfplumber` 抽页文本）读取 PDF。本节给出对 `Ascend-API-DOC.pdf`（2026-05 版）的**精确章节映射 + 页码区间**；若 PDF 升级，LLM 应先核对 outline，把页码区间替换为新值后再抽。

**cube 类（写入 whitelist_cube.md）：**

| 章节标题（以 PDF outline 实际为准） | 页码区间 |
|------------------------------------|----------|
| 2.3.2 矩阵计算（ISASI）             | p263–403 |
| 2.4.2 矩阵计算                      | p1551–1756 |
| 2.4.12 卷积计算                     | p2289–2370 |

**vector 类（写入 whitelist_vector.md）：**

| 章节标题 | 页码区间 |
|----------|----------|
| 2.3.3 Memory矢量计算                | p404–797 |
| 2.4.1 数学计算                      | p1290–1550 |
| 2.4.3 激活函数                      | p1757–1865 |
| 2.4.4 归一化操作                    | p1866–1949 |
| 2.4.5 量化操作                      | p1950–2019 |
| 2.4.6 归约操作                      | p2020–2071 |
| 2.4.7 排序操作                      | p2072–2119 |
| 2.4.8 索引计算                      | p2120–2122 |
| 2.4.9 数据过滤                      | p2123–2139 |
| 2.4.10 张量变换                     | p2140–2191 |
| 2.4.13 随机函数                     | p2371–2373 |

减法清单（**不要**抽进 vector 白名单）：
- 2.4.2 矩阵计算（它属于 cube）
- 2.4.11 HCCL通信类
- 2.4.12 卷积计算（它属于 cube）

**不要**抽进任何白名单的章节（避免误并）：
- 2.3.1 Memory数据搬运，2.3.4 Reg矢量计算（由 rule 3 RegBase 覆盖），2.3.5 标量计算，2.3.6–2.3.14 其他基础设施
- 第 3 章 SIMT API（由 rule 1 simt 覆盖）
- 第 4–6 章 Utils / AI CPU / 附录

**抽取要求：**
- 每个章节内，列出该节及其所有子节里的 API 名；名称形式为 `AscendC::Xxx`（若 PDF 中出现裸名，补 `AscendC::` 前缀）
- 不收 *Tiling* / *GetXxxTmpSize* / *GetXxxMaxMinTmpSize* 等只用于 host 侧 tiling 计算的辅助函数
- 同名去重，按字母排序

**结果组织成内存 dict：**

```python
cube_chapters = {
    "基础API / 矩阵计算(ISASI)": ["AscendC::Mmad", ...],
    "高阶API / 矩阵计算":         ["AscendC::Matmul", ...],
    "高阶API / 卷积计算":         ["AscendC::Conv3D", ...],
}
vector_chapters = {
    "基础API / Memory矢量计算":   [...],
    "高阶API / 数学计算":         ["AscendC::Tanh", ...],
    ...
}
```

#### 3d. 让用户 review

报告草稿摘要（只报数量，不打全清单）：

> 草稿就绪：
> - cube 47 项（ISASI 12 / 矩阵 23 / 卷积 12）
> - vector 132 项（Memory 矢量 34 / 高阶其他 98）
>
> 回复"确认"→ 落盘；给修改建议 → 调整后重展示；"中止"→ 不落盘退出

#### 3e. 落盘

调 `scripts.write_whitelist.write_whitelists(...)`，更新 `~/.config/cann-ops/scann-repo-state.json`。

### 4. 扫描

从 skill 目录（`skills/scann-repo/`）执行：

```bash
python -m scripts.scan_repo <repo_root> \
  --op-list <repo_root>/docs/zh/op_list.md \
  --whitelist-cube <api_doc_path>/whitelist_cube.md \
  --whitelist-vector <api_doc_path>/whitelist_vector.md \
  --output <cwd>/950-scann/<repo_name>/_intermediate.json
```

### 5. 渲染

```bash
python -m scripts.render_report \
  <cwd>/950-scann/<repo_name>/_intermediate.json \
  --out <cwd>/950-scann/<repo_name>/ \
  --templates templates/
```

### 6. 汇报给用户

```
✓ 扫描完成，产物：
  - <cwd>/950-scann/<repo_name>/summary.md  （主清单，N 命中）
  - <cwd>/950-scann/<repo_name>/detail.md   （证据明细）
  - <cwd>/950-scann/<repo_name>/_intermediate.json （机读 JSON）

⚠ 共发现 K 处 README/代码不一致（详见 summary.md §3）
```

## 四条扫描规则

| 规则 | 识别依据 | 说明 |
|------|---------|------|
| **SIMT** | `__simt_vf__` 关键字 | NPU 上动态执行分支逻辑 |
| **HIF8** | `HIFLOAT8` 类型 | 950 专属 8bit 高保真浮点 |
| **RegBase** | `AscendC::MicroAPI::RegTensor` API | 寄存器块级别向量存取 |
| **CV 融合** | `op_kernel` 内同时出现真 cube + 真 vector API | 仅扫 op_kernel，不扫 op_host/op_api/op_graph |

## Failure modes

| 触发 | 行为 |
|------|------|
| 目标路径无 `docs/zh/op_list.md` | fatal，提示"非 CANN ops 仓" |
| API doc 路径不可写 | fatal，提示更换路径 |
| API doc 路径无 PDF | 对话里再次询问 |
| 算子目录缺失 / 读取失败 | warning，不阻塞 |
| 用户 review 阶段拒绝落盘 | 退出，不修改任何文件 |
