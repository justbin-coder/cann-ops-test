"""P4:从 findings.json + doc_meta.json 渲染体检报告(Markdown + HTML,纯 stdlib)。

强制**自校验闸**:每条缺陷先过 `_state.self_check_finding`——可量化必带代码位置、不可量化
必带判例+steelman、「确认讲错」必带外部反证。**不过的不准进正文**,落到「待补」段。
报告分两段:事实问题(可量化,先列,可计数) / 教学判断(不可量化,后列,只定性)。

三项约定:
- **TE-1 未评≠合格**:`doc_meta.axes_evaluated`(本轮真评过的轴列表)若存在,不在其中的轴标
  「本轮未评」而非「合格」,避免把覆盖缺口伪装成通过;字段缺省=向后兼容(视作全评过)。
- **TE-2 跨轴去重**:多个 finder 在同一文档行命中同一处(如信得过+读得懂各报一遍)时,按
  `(cls, 文档行号)` 折叠,保留证据最强一条,其余记 `also_hit`,五轴计数不再虚高。
- **TE-3 双格式**:默认 `--format both`,同目录产 REPORT.md + REPORT.html(卡片式/三态色标/折叠)。

用法:python -m scripts.render_report --repo R [--out <...>/REPORT.md] [--format md|html|both]
"""
from __future__ import annotations

import argparse
import html
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _state  # noqa: E402

_CONFIRMED = {"CONFIRMED_MISMATCH", "CONFIRMED_CONCEPT_WRONG"}
_AX_ORDER = ["findable", "trustworthy", "learnable", "operable", "readable"]

_VERDICT_ZH = {"CONFIRMED_MISMATCH": "确认对不上", "SUSPECTED": "疑似",
               "CONSISTENT": "一致", "NO_STATIC_EVIDENCE": "未找到静态证据",
               "TEACHING_JUDGMENT": "教学判断", "SUSPECTED_CONCEPT_RISK": "疑似概念风险",
               "CONFIRMED_CONCEPT_WRONG": "确认讲错"}


def _axis_grade(axis_findings: list) -> str:
    if any(f.get("verdict") in _CONFIRMED for f in axis_findings):
        return "不合格"
    if any(f.get("verdict") in _state.DEFECT_VERDICTS for f in axis_findings):
        return "有缺陷"
    return "合格"


def _score(f: dict) -> int:
    s = 10 if f.get("verdict") in _CONFIRMED else (5 if f.get("verdict") in _state.DEFECT_VERDICTS else 0)
    return s + {"trustworthy": 3, "findable": 2, "operable": 2}.get(f.get("axis"), 1)


def _doc_line(f: dict, docbase: str):
    """从 code_location 提取教程自身的行号(只认指向被评教程文件的 `<docbase>:NNN`)。"""
    if not docbase:
        return None
    m = re.search(re.escape(docbase) + r":(\d+)", f.get("code_location") or "")
    return int(m.group(1)) if m else None


def _dedup(findings: list, docbase: str) -> list:
    """TE-2:按 (cls, 教程行号) 折叠跨 finder/跨轴重复,保留证据最强一条,其余记 also_hit。
    无教程行号的(多为教学判断)原样保留——不强行合并不同处的判断。"""
    winners, seq = {}, []
    for f in findings:
        ln = _doc_line(f, docbase)
        if ln is None:
            seq.append(("F", f))
            continue
        key = (f.get("cls"), ln)
        if key not in winners:
            winners[key] = dict(f)            # 复制,避免改到 findings.json 原对象
            seq.append(("K", key))
        else:
            cur = winners[key]
            keeper, folded = (f, cur) if _score(f) > _score(cur) else (cur, f)  # 留证据最强,折叠另一条
            merged = dict(keeper)
            merged["also_hit"] = (keeper.get("also_hit", []) + folded.get("also_hit", [])
                                  + [{"axis": folded.get("axis"), "verdict": folded.get("verdict")}])
            winners[key] = merged
    return [winners[tok[1]] if tok[0] == "K" else tok[1] for tok in seq]


def _partition(repo: str):
    """共享:读 meta/findings → 自校验闸分 valid/needs_fix → 跨轴去重 → 分可量化/不可量化。"""
    meta = _state.load_meta(repo)
    raw = _state.load_findings(repo)
    docbase = (meta.get("doc") or "").split("/")[-1]

    valid_raw, needs_fix = [], []
    for f in raw:
        probs = _state.self_check_finding(f)
        if probs:
            needs_fix.append((f, probs))
        else:
            valid_raw.append(f)

    valid = _dedup(valid_raw, docbase)
    defects = [f for f in valid if f.get("verdict") in _state.DEFECT_VERDICTS]
    quant = [f for f in defects if f.get("cls") == "quantifiable"]
    nonquant = [f for f in defects if f.get("cls") == "non_quantifiable"]
    quant.sort(key=lambda f: (f.get("verdict") != "CONFIRMED_MISMATCH", f.get("idx", 0)))
    return meta, valid, needs_fix, quant, nonquant


def _axis_cells(meta: dict, valid: list):
    """逐轴出 (中文名, 定性档, 可量化缺陷数显示)。TE-1:未评过的轴 → 本轮未评 / —。"""
    evaluated = meta.get("axes_evaluated")  # None=向后兼容(视作全评)
    for ax in _AX_ORDER:
        af = [f for f in valid if f.get("axis") == ax]
        if evaluated is not None and ax not in evaluated:
            yield _state.AXIS_ZH[ax], "本轮未评", "—"
        else:
            nq = len([f for f in af if f.get("cls") == "quantifiable" and f.get("verdict") in _state.DEFECT_VERDICTS])
            yield _state.AXIS_ZH[ax], _axis_grade(af), str(nq)


def _also(f: dict) -> str:
    hits = f.get("also_hit") or []
    return "、".join(f"{_state.AXIS_ZH.get(h.get('axis'), '?')}" for h in hits)


# ============================== Markdown ==============================

def _cell(s) -> str:
    return (str(s) if s is not None else "—").replace("|", "\\|").replace("\n", " ").strip() or "—"


def render(repo: str) -> str:
    meta, valid, needs_fix, quant, nonquant = _partition(repo)

    L = []
    L.append(f"# 进阶教程体检报告 — {repo}\n")
    L.append(f"> 教程:`{meta.get('doc', '(未记录)')}` · 类型:{meta.get('type', '?')} · "
             f"受众:{meta.get('audience', '?')} · 代码根:`{meta.get('code_root', '?')}`")
    L.append(f"> 生成:{datetime.now().isoformat(timespec='seconds')} · "
             "skill `cann-ops:tutorial-eval` —— 通读+对照代码**静态**评(默认不跑);"
             "**不打玄学分、grep 不到≠编造**。\n")

    # 一、五轴总评
    L.append("## 一、五轴总评\n")
    L.append("| 轴 | 定性档 | 可量化缺陷数 |")
    L.append("|---|---|---|")
    for name, grade, cnt in _axis_cells(meta, valid):
        L.append(f"| {name} | {grade} | {cnt} |")
    L.append("")
    L.append(f"- **可量化缺陷**(高置信,可计数):{len(quant)}  ·  **教学判断**(只定性,不计分):{len(nonquant)}")
    if needs_fix:
        L.append(f"- ⚠ **{len(needs_fix)} 条未过自校验闸**(无证据/无判例),见文末「待补」,**不计入结论**")
    L.append("")

    # 二、事实问题（可量化）
    L.append("## 二、事实问题（可量化 · 对照代码 · 高置信）\n")
    if not quant:
        L.append("（未发现可量化事实问题。）\n")
    else:
        L.append("| # | 文档原文 | 轴·形态·来源 | 证据等级 | 三态 | 代码位置 | 改进建议 |")
        L.append("|---|---|---|---|---|---|---|")
        for f in quant:
            tag = f"{_state.AXIS_ZH.get(f.get('axis'),'?')}·{_cell(f.get('form'))}·{_cell(f.get('source'))}"
            L.append(f"| {f.get('idx')} | {_cell(f.get('quote'))} | {tag} | {_cell(f.get('evidence_grade'))} | "
                     f"**{_cell(f.get('verdict'))}** | `{_cell(f.get('code_location'))}` | {_cell(f.get('improvement'))} |")
        L.append("")
        for f in quant:
            if f.get("open_question"):
                L.append(f"> #{f.get('idx')} 开放问题:{f['open_question']}")
            if f.get("also_hit"):
                L.append(f"> #{f.get('idx')} 另命中此处的轴:{_also(f)}")
        L.append("")

    # 三、教学判断（不可量化）
    L.append("## 三、教学判断（不可量化 · steelman 已过 · 只定性）\n")
    if not nonquant:
        L.append("（未发现教学判断类缺陷。）\n")
    for f in nonquant:
        L.append(f"### #{f.get('idx')} — {_state.AXIS_ZH.get(f.get('axis'),'?')}（{f.get('verdict')}）`教学判断`")
        L.append(f"- **文档原文**:{f.get('quote')}")
        L.append(f"- **判例(读者会卡在哪)**:{f.get('precedent')}")
        L.append(f"- **steelman(已打反论)**:{f.get('steelman')}")
        if f.get("external_evidence"):
            L.append(f"- **外部反证**:{f.get('external_evidence')}")
        L.append(f"- **改进建议**:{f.get('improvement')}")
        L.append(f"- 下一责任人:{f.get('next_owner', '文档作者')}")
        L.append("")

    # 四、待补（未过自校验闸）
    if needs_fix:
        L.append("## 四、待补（未过自校验闸,不计入结论）\n")
        for f, probs in needs_fix:
            L.append(f"- 原文「{_cell(f.get('quote'))}」({f.get('cls')}/{f.get('verdict')}):缺 {'; '.join(probs)}")
        L.append("")
    return "\n".join(L)


# ================================ HTML ================================

_VCLASS = {"CONFIRMED_MISMATCH": "v-red", "CONFIRMED_CONCEPT_WRONG": "v-red",
           "SUSPECTED": "v-amber", "SUSPECTED_CONCEPT_RISK": "v-amber",
           "TEACHING_JUDGMENT": "v-blue", "CONSISTENT": "v-green", "NO_STATIC_EVIDENCE": "v-gray"}
_GRADE_CLASS = {"合格": "g-green", "有缺陷": "g-amber", "不合格": "g-red", "本轮未评": "g-gray"}

_CSS = """
:root{--bg:#f6f7f9;--card:#fff;--ink:#1f2933;--muted:#66727f;--line:#e3e8ee}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);font:15px/1.65 -apple-system,BlinkMacSystemFont,"PingFang SC","Microsoft YaHei",Segoe UI,sans-serif}
.wrap{max-width:1040px;margin:0 auto;padding:32px 22px 80px}
h1{font-size:25px;margin:0 0 6px}
h2{font-size:19px;margin:38px 0 14px;padding-bottom:8px;border-bottom:2px solid var(--line)}
.sub{color:var(--muted);font-size:13.5px;margin:2px 0}
.tag{display:inline-block;padding:1px 8px;border-radius:999px;font-size:12px;font-weight:600;vertical-align:middle}
.soul{background:#eef3fb;border:1px solid #d6e2f5;border-radius:10px;padding:10px 14px;margin:14px 0;font-size:13.5px;color:#33455c}
table.axis{width:100%;border-collapse:collapse;background:var(--card);border:1px solid var(--line);border-radius:12px;overflow:hidden}
table.axis th,table.axis td{padding:11px 14px;text-align:left;border-bottom:1px solid var(--line)}
table.axis th{background:#fafbfc;font-size:13px;color:var(--muted);font-weight:600}
table.axis tr:last-child td{border-bottom:0}
.g-green{background:#e6f6ec;color:#1f8a4c}.g-amber{background:#fdf0e1;color:#b9650f}.g-red{background:#fde8e6;color:#c0392b}.g-gray{background:#eef0f2;color:#66727f}
.cnt{font-variant-numeric:tabular-nums;font-weight:700}
.stat{display:flex;gap:18px;flex-wrap:wrap;margin:14px 0 4px}
.stat .pill{background:var(--card);border:1px solid var(--line);border-radius:10px;padding:8px 14px;font-size:13.5px}
.stat b{font-size:18px}
.card{background:var(--card);border:1px solid var(--line);border-left:4px solid var(--line);border-radius:10px;padding:14px 16px;margin:12px 0;box-shadow:0 1px 2px rgba(20,30,40,.04)}
.card.v-red{border-left-color:#c0392b}.card.v-amber{border-left-color:#e67e22}.card.v-blue{border-left-color:#2980b9}
.v-red{background:#fde8e6;color:#c0392b}.v-amber{background:#fdf0e1;color:#b9650f}.v-blue{background:#e7f1fa;color:#1f6aa8}.v-green{background:#e6f6ec;color:#1f8a4c}.v-gray{background:#eef0f2;color:#66727f}
.chead{display:flex;align-items:center;gap:8px;flex-wrap:wrap;margin-bottom:8px}
.idx{font-weight:700;color:var(--muted)}
.atag{background:#eef0f2;color:#46525e;font-size:11.5px;padding:1px 7px;border-radius:6px}
.quote{background:#0f1722;color:#e7edf3;border-radius:8px;padding:9px 12px;margin:8px 0;font-family:"SF Mono",Menlo,Consolas,monospace;font-size:12.5px;white-space:pre-wrap;word-break:break-word;overflow-x:auto}
.fix{margin:8px 0 2px}.fix b{color:#1f8a4c}
.prec{margin:8px 0 2px}.prec b{color:#b9650f}
details{margin:8px 0 0;border-top:1px dashed var(--line);padding-top:8px}
details summary{cursor:pointer;color:var(--muted);font-size:12.5px;font-weight:600;user-select:none}
details .body{font-size:12.5px;color:#3a4651;margin-top:7px;white-space:pre-wrap;word-break:break-word}
.empty{color:var(--muted);font-style:italic;padding:6px 2px}
.todo{background:#fff8e6;border:1px solid #f3e3b3;border-radius:8px;padding:8px 12px;margin:8px 0;font-size:12.5px;color:#7a5b12}
footer{margin-top:40px;color:var(--muted);font-size:12.5px;border-top:1px solid var(--line);padding-top:14px}
"""


def _esc(s) -> str:
    return html.escape(html.unescape(str(s) if s is not None else ""), quote=False)


def _card_quant(f: dict) -> str:
    v = f.get("verdict", "")
    src = " · ".join(x for x in [f.get("form"), f.get("source")] if x)
    oq = f.get("open_question")
    also = _also(f)
    return f"""<div class="card {_VCLASS.get(v,'')}">
  <div class="chead">
    <span class="idx">#{f.get('idx','')}</span>
    <span class="tag {_VCLASS.get(v,'')}">{_esc(_VERDICT_ZH.get(v,v))}</span>
    <span class="atag">{_esc(_state.AXIS_ZH.get(f.get('axis'),'?'))}</span>
    {f'<span class="atag">{_esc(src)}</span>' if src else ''}
    <span class="atag">证据 {_esc(f.get('evidence_grade','?'))}</span>
    {f'<span class="atag">另命中:{_esc(also)}</span>' if also else ''}
  </div>
  <div class="quote">{_esc(f.get('quote'))}</div>
  <div class="fix"><b>改进 ▸</b> {_esc(f.get('improvement'))}</div>
  {f'<div class="prec"><b>开放问题 ▸</b> {_esc(oq)}</div>' if oq else ''}
  <details><summary>代码位置 / 取证</summary><div class="body">{_esc(f.get('code_location'))}</div></details>
</div>"""


def _card_nonquant(f: dict) -> str:
    v = f.get("verdict", "")
    ext = f.get("external_evidence")
    return f"""<div class="card {_VCLASS.get(v,'')}">
  <div class="chead">
    <span class="idx">#{f.get('idx','')}</span>
    <span class="tag {_VCLASS.get(v,'')}">{_esc(_VERDICT_ZH.get(v,v))}</span>
    <span class="atag">{_esc(_state.AXIS_ZH.get(f.get('axis'),'?'))}</span>
    <span class="atag">教学判断 · 非代码事实</span>
  </div>
  <div class="quote">{_esc(f.get('quote'))}</div>
  <div class="prec"><b>判例(读者会卡在哪)▸</b> {_esc(f.get('precedent'))}</div>
  <div class="fix"><b>改进 ▸</b> {_esc(f.get('improvement'))}</div>
  {f'<div class="prec"><b>外部反证 ▸</b> {_esc(ext)}</div>' if ext else ''}
  <details><summary>steelman(已替原文打过的最强反论)</summary><div class="body">{_esc(f.get('steelman'))}</div></details>
</div>"""


def render_html(repo: str) -> str:
    meta, valid, needs_fix, quant, nonquant = _partition(repo)

    rows = ""
    for name, grade, cnt in _axis_cells(meta, valid):
        rows += (f'<tr><td>{name}</td>'
                 f'<td><span class="tag {_GRADE_CLASS.get(grade,"g-gray")}">{grade}</span></td>'
                 f'<td class="cnt">{cnt}</td></tr>')

    body_q = "\n".join(_card_quant(f) for f in quant) or '<div class="empty">未发现可量化事实问题。</div>'
    body_n = "\n".join(_card_nonquant(f) for f in nonquant) or '<div class="empty">未发现教学判断类缺陷。</div>'

    todo = ""
    if needs_fix:
        items = "\n".join(
            f'<div class="todo">原文「{_esc((f.get("quote") or "")[:60])}」'
            f'({_esc(f.get("cls"))}/{_esc(f.get("verdict"))}):缺 {_esc("; ".join(probs))}</div>'
            for f, probs in needs_fix)
        todo = f"<h2>四、待补(未过自校验闸,不计入结论)</h2>\n{items}"

    return f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>进阶教程体检报告 — {_esc(repo)}</title><style>{_CSS}</style></head>
<body><div class="wrap">
<h1>进阶教程体检报告 <span class="tag g-amber">{_esc(repo)}</span></h1>
<p class="sub">教程 <code>{_esc(meta.get('doc','?'))}</code></p>
<p class="sub">类型:{_esc(meta.get('type','?'))} · 受众:{_esc(meta.get('audience','?'))}</p>
<p class="sub">代码根 <code>{_esc(meta.get('code_root','?'))}</code> · 生成 {datetime.now().isoformat(timespec='seconds')}</p>
<div class="soul">skill <code>cann-ops:tutorial-eval</code> —— 通读 + 对照代码<b>静态</b>评(默认不跑)。两条灵魂:<b>不打玄学分</b>(主观判断先 steelman 再 flag)、<b>grep 不到 ≠ 编造</b>(三态结论,只有强证据才写「确认」)。</div>

<h2>一、五轴总评</h2>
<table class="axis"><thead><tr><th>轴</th><th>定性档</th><th>可量化缺陷数</th></tr></thead><tbody>{rows}</tbody></table>
<div class="stat">
  <div class="pill">可量化缺陷(高置信,可计数)<b>{len(quant)}</b></div>
  <div class="pill">教学判断(只定性,不计分)<b>{len(nonquant)}</b></div>
  {f'<div class="pill">未过自校验闸(待补)<b>{len(needs_fix)}</b></div>' if needs_fix else ''}
</div>

<h2>二、事实问题(可量化 · 对照代码 · 高置信)</h2>
{body_q}

<h2>三、教学判断(不可量化 · steelman 已过 · 只定性)</h2>
{body_n}

{todo}

<footer>评分只定性(档 + 缺陷计数,仅可量化条计数),不打数字分。每条可量化必带代码位置、不可量化必带判例 + steelman(自校验闸);不过闸的落「待补」、不进正文。跨轴重复按文档行号折叠。本 skill 只评不改不跑不探索。</footer>
</div></body></html>"""


def main() -> int:
    ap = argparse.ArgumentParser(description="渲染 tutorial-eval 体检报告(MD + HTML,含自校验闸/去重/未评标注)")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", help="REPORT.md 输出路径(默认 CWD/cann-ops-report/tutorial-eval/<repo>/REPORT.md)")
    ap.add_argument("--format", choices=["md", "html", "both"], default="both")
    args = ap.parse_args()

    md_out = Path(args.out) if args.out else _state.repo_dir(args.repo) / "REPORT.md"
    md_out.parent.mkdir(parents=True, exist_ok=True)
    html_out = md_out.with_suffix(".html")

    if args.format in ("md", "both"):
        md_out.write_text(render(args.repo), encoding="utf-8")
        print(f"[report] {args.repo} → {md_out}")
    if args.format in ("html", "both"):
        html_out.write_text(render_html(args.repo), encoding="utf-8")
        print(f"[report] {args.repo} → {html_out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
