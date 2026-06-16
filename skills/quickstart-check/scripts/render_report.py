"""P4:从 steps.json + doc_meta.json 渲染结论报告 REPORT.md(纯 stdlib,无第三方依赖)。

报告四块:总评 / 逐步台账 / 文档缺陷清单(带修订建议)/ 卡点详情。
overall 由台账自动算:有 blocker(FAIL/DOC_AMBIGUOUS/DOC_MISSING)→ 卡在第一个;全 OK → 通过。
agent 可用 --conclusion / --rating 覆盖一句话结论与评级。

用法:
  python -m scripts.render_report --repo R --out <CWD>/cann-ops-report/doccheck/R/REPORT.md
    [--conclusion '...'] [--rating '...']
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _state  # noqa: E402


def _cell(s) -> str:
    return (str(s) if s is not None else "—").replace("|", "\\|").replace("\n", " ").strip() or "—"


def _overall(steps: list) -> dict:
    blockers = [s for s in steps if s.get("verdict") in _state.BLOCKER_VERDICTS]
    judged_ok = [s for s in steps if s.get("verdict") == "OK"]
    unjudged = [s for s in steps if s.get("verdict", "UNJUDGED") == "UNJUDGED"]
    first_blocker = min(blockers, key=lambda s: s.get("idx", 0)) if blockers else None
    if first_blocker:
        passable = False
        rating = "卡死跑不通"
    elif steps and not unjudged:
        passable = True
        rating = "可跑通(文档合格)"
    else:
        passable = None
        rating = "未判完 / 无可执行步骤"
    return {"passable": passable, "rating": rating, "first_blocker": first_blocker,
            "n_total": len(steps), "n_ok": len(judged_ok), "n_unjudged": len(unjudged),
            "n_blocker": len(blockers)}


def render(repo: str, conclusion: str = "", rating: str = "") -> str:
    steps = _state.load_steps(repo)
    meta = _state.load_meta(repo)
    ov = _overall(steps)
    fb = ov["first_blocker"]
    rating = rating or ov["rating"]
    if ov["passable"] is True:
        verdict_line = "✅ **能纯按文档跑通**"
        default_concl = "开发者只照本文档操作即可跑起来,文档合格。"
    elif ov["passable"] is False:
        verdict_line = f"❌ **卡在第 {fb['idx']} 步**({fb.get('verdict')})——纯按文档无法继续"
        default_concl = f"开发者只照本文档操作会卡在第 {fb['idx']} 步,文档需修订后才能跑通。"
    else:
        verdict_line = "⏳ **未判完 / 无可执行步骤**"
        default_concl = "尚无足够已判定步骤给出结论(或该仓无快速入门文档)。"
    concl = conclusion or default_concl

    L = []
    L.append(f"# QuickStart 文档体检报告 — {repo}\n")
    L.append(f"> 文档:`{meta.get('doc', '(未记录)')}` · 生成:{datetime.now().isoformat(timespec='seconds')}")
    L.append("> skill:`cann-ops:quickstart-check` —— 忠实模拟开发者照文档操作,**只按文档做、不探索/不绕过**。\n")

    L.append("## 一、总评\n")
    L.append(f"- **能否纯按文档跑通**:{verdict_line}")
    L.append(f"- **文档质量评级**:{rating}")
    L.append(f"- **一句话结论**:{concl}")
    L.append(f"- 步骤:共 {ov['n_total']}，OK {ov['n_ok']}，卡点 {ov['n_blocker']}，待判 {ov['n_unjudged']}")
    if meta.get("declared_prerequisites"):
        L.append(f"- 文档声明的前提(假设已满足):{'; '.join(meta['declared_prerequisites'])}")
    L.append("")

    L.append("## 二、逐步台账\n")
    L.append("| # | 文档原文 | 实际命令 | cwd | 退出码 | 判定 | 日志 |")
    L.append("|---|---|---|---|---|---|---|")
    for s in steps:
        lp = s.get("log_path")
        logcell = f"`steps/{Path(lp).name}`" if lp else "—"
        L.append(f"| {s.get('idx')} | {_cell(s.get('doc_quote'))} | `{_cell(s.get('command'))}` | "
                 f"{_cell(s.get('cwd'))} | {_cell(s.get('exit_code'))} | {_cell(s.get('verdict'))} | {logcell} |")
    L.append("\n> 每步「日志」列即该步完整真实 stdout/stderr;失败步的输出摘录见下方缺陷清单。\n")

    defects = [s for s in steps if s.get("verdict") in _state.BLOCKER_VERDICTS or s.get("defect")]
    L.append("## 三、文档缺陷清单(带修订建议)\n")
    if not defects:
        L.append("（未发现文档缺陷。）\n")
    for i, s in enumerate(defects, 1):
        L.append(f"### 缺陷 {i} — 第 {s.get('idx')} 步（{s.get('verdict')}）")
        L.append(f"- **文档原文**:{s.get('doc_quote') or '（无）'}")
        L.append(f"- **缺什么 / 错在哪**:{s.get('defect') or '（agent 未填——执行判定为非 OK）'}")
        L.append(f"- **修订建议**:{s.get('fix_suggestion') or '（agent 未填）'}")
        err = (s.get("stderr_excerpt") or s.get("stdout_excerpt") or "").strip()
        if err:
            L.append("- **真实报错(摘录)**:\n\n  ```\n  " + "\n  ".join(err.splitlines()[-12:]) + "\n  ```")
        L.append("")

    L.append("## 四、卡点详情\n")
    if fb:
        L.append(f"停在**第 {fb['idx']} 步**（{fb.get('verdict')}）:")
        L.append(f"- 文档原文:{fb.get('doc_quote') or '（无）'}")
        L.append(f"- 实际命令:`{fb.get('command')}`（cwd `{fb.get('cwd')}`,退出码 {fb.get('exit_code')}）")
        L.append(f"- 为什么纯按文档无法继续:{fb.get('defect') or '（见缺陷清单）'}")
    else:
        L.append("（未卡住。）")
    L.append("")
    return "\n".join(L)


def main() -> int:
    ap = argparse.ArgumentParser(description="渲染 quickstart-check 结论报告")
    ap.add_argument("--repo", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--conclusion", default="")
    ap.add_argument("--rating", default="")
    args = ap.parse_args()
    md = render(args.repo, args.conclusion, args.rating)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(md, encoding="utf-8")
    print(f"[report] {args.repo} → {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
