---
name: scann-repo
description: 扫描任意 CANN ops 仓中依赖 Ascend 950 硬件特性（simt / hif8 / RegBase / cube+vector fusion）的算子，输出测试团队可用的 markdown 清单。涉及"找 950 相关算子 / 刷新白名单 / 扫描 950 覆盖度"等用户意图时使用。仓名与本地路径每次会话由 Skill 主动从 CWD 发现或询问，不再硬编码。
---

# cann-ops:scann-repo

识别任意 CANN ops 仓中依赖 Ascend 950 硬件特性的算子，输出测试团队的靶子清单。

## 首次运行前置检查（P0）

激活后先检查 Python 依赖，缺失则自动安装：

```bash
python3 -c "import jinja2, pdfplumber, pypdf" 2>/dev/null \
  || pip install -r scripts/requirements.txt
```

## When to invoke

- "扫一下某个 ops 仓的 950 算子"
- "扫描 ops-X 的 950 特性算子"
- "重新生成白名单"
- 任何要列出 "950 相关算子" 的请求

## Inputs

每次会话**都向用户确认**输入，绝不假定。所有发现/确认/询问用**中文**和用户交互。

- **目标仓路径**：从 CWD 扫描候选 → 让用户确认 → 兜底询问（无持久化）
- **API 文档路径**：从 CWD 扫描 PDF → 让用户确认 → 兜底询问（无持久化）

## Workflow

### 1. 定位目标仓（按下面三步走）

**Step 1.1 — 用户已经明确给了路径或仓名**
- 如果给了**绝对路径** → 直接用
- 如果给了**仓名（如 ops-transformer）** → 在 CWD 下找同名子目录，找到则用，找不到询问绝对路径

**Step 1.2 — 用户没指定，扫描 CWD 候选**

在 CWD 下查找具有 `docs/zh/op_list.md` 的子目录（这是 CANN ops 仓的标志），把候选列出来用中文向用户确认：

```
我在当前工作目录下发现这些候选 CANN ops 仓：
  1. ./ops-transformer  ← 含 docs/zh/op_list.md
  2. ./ops-math         ← 含 docs/zh/op_list.md
请选择要扫描的仓（多选用逗号分隔），或直接给我一个绝对路径。
```

用 `AskUserQuestion` 收集选择。

**Step 1.3 — 没找到任何候选**

提示：

```
当前工作目录 <CWD> 下未发现 CANN ops 仓（没有任何子目录含 docs/zh/op_list.md）。
请提供目标仓的绝对路径。
```

**最终校验**：选定的目标仓必须有 `<root>/docs/zh/op_list.md`，否则 fatal："这看起来不是 CANN ops 仓"。

### 2. 检查白名单状态

不再读任何持久化 state 文件。直接基于本会话的 API 文档路径（§3a 收集）判断：

- `<api_doc_path>/whitelist_cube.md` 与 `<api_doc_path>/whitelist_vector.md` **都存在** → 询问用户"白名单已存在，是否复用？"
  - 复用 → 直接进 §4 扫描
  - 刷新 → 进 §3 重新抽取
- 其中**任一缺失** → 进 §3 对话式抽取

### 3. 对话式抽取白名单

#### 3a. 询问 API 文档路径（按下面三步走）

**Step 3a.1 — 用户已给路径** → 用它

**Step 3a.2 — 扫描 CWD 候选 PDF**

在 CWD 及一级子目录下搜索 `*.pdf`，呈现给用户确认：

```
我在当前工作目录下发现这些 PDF 候选：
  1. ./Ascend-API-DOC.pdf
  2. ./docs/api/Ascend-API-DOC-V2.pdf
请选择 API 文档（用作 950 接口白名单的源），或给我一个绝对路径。
```

用 `AskUserQuestion` 收集。

**Step 3a.3 — 没找到候选**

```
当前工作目录下未发现 PDF。请提供 Ascend C API PDF 文档的绝对路径
（单个 .pdf 或包含分册的目录）。
```

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

调 `scripts.write_whitelist.write_whitelists(...)` 把 cube/vector 两份 markdown 写到 `<api_doc_path>/`，并写一份 `<api_doc_path>/WHITELIST_SOURCE.md`（记录 PDF 名 + SHA + 抽取时间，方便下次会话校验）。**不写任何 ~/.config/ 下的持久化 state。**

### 4. 扫描

从 skill 目录（`skills/scann-repo/`）执行：

```bash
python -m scripts.scan_repo <repo_root> \
  --op-list <repo_root>/docs/zh/op_list.md \
  --whitelist-cube <api_doc_path>/whitelist_cube.md \
  --whitelist-vector <api_doc_path>/whitelist_vector.md \
  --output <CWD>/cann-ops-report/scann/<repo_name>/_intermediate.json
```

### 5. 渲染

```bash
python -m scripts.render_report \
  <CWD>/cann-ops-report/scann/<repo_name>/_intermediate.json \
  --out <CWD>/cann-ops-report/scann/<repo_name>/ \
  --templates templates/
```

### 6. 汇报给用户（中文）

```
✓ 扫描完成，产物：
  - <CWD>/cann-ops-report/scann/<repo_name>/summary.md  （主清单，N 命中）
  - <CWD>/cann-ops-report/scann/<repo_name>/detail.md   （证据明细）
  - <CWD>/cann-ops-report/scann/<repo_name>/_intermediate.json （机读 JSON）

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
| API doc 路径无 PDF | 在 §3a 流程里继续询问 |
| 算子目录缺失 / 读取失败 | warning，不阻塞 |
| 用户 review 阶段拒绝落盘 | 退出，不修改任何文件 |
