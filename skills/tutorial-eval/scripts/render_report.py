"""P4:从 findings.json + doc_meta.json 渲染体检报告 REPORT.md(纯 stdlib)。

强制**自校验闸**:每条缺陷先过 `_state.self_check_finding`——可量化必带代码位置、不可量化
必带判例+steelman、「确认讲错」必带外部反证。**不过的不准进正文**,落到「待补」段。
报告分两段:事实问题(可量化,先列,可计数) / 教学判断(不可量化,后列,只定性)。

用法:python -m scripts.render_report --repo R --out <CWD>/cann-ops-report/tutorial-eval/R/REPORT.md
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _state  # noqa: E402

_CONFIRMED = {"CONFIRMED_MISMATCH", "CONFIRMED_CONCEPT_WRONG"}


def _axis_grade(axis_findings: list) -> str:
    if any(f.get("verdict") in _CONFIRMED for f in axis_findings):
        return "不合格"
    if any(f.get("verdict") in _state.DEFECT_VERDICTS for f in axis_findings):
        return "有缺陷"
    return "合格"


def _cell(s) -> str:
    return (str(s) if s is not None else "—").replace("|", "\\|").replace("\n", " ").strip() or "—"


def render(repo: str) -> str:
    meta = _state.load_meta(repo)
    raw = _state.load_findings(repo)

    valid, needs_fix = [], []
    for f in raw:
        probs = _state.self_check_finding(f)
        (needs_fix if probs else valid).append((f, probs))

    defects = [f for f, _ in valid if f.get("verdict") in _state.DEFECT_VERDICTS]
    quant = [f for f in defects if f.get("cls") == "quantifiable"]
    nonquant = [f for f in defects if f.get("cls") == "non_quantifiable"]
    quant.sort(key=lambda f: (f.get("verdict") != "CONFIRMED_MISMATCH", f.get("idx", 0)))

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
    for ax in ["findable", "trustworthy", "learnable", "operable", "readable"]:
        af = [f for f, _ in valid if f.get("axis") == ax]
        nq = len([f for f in af if f.get("cls") == "quantifiable" and f.get("verdict") in _state.DEFECT_VERDICTS])
        L.append(f"| {_state.AXIS_ZH[ax]} | {_axis_grade(af)} | {nq} |")
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


def main() -> int:
    ap = argparse.ArgumentParser(description="渲染 tutorial-eval 体检报告(含自校验闸)")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    md = render(args.repo)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"[report] {args.repo} → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
