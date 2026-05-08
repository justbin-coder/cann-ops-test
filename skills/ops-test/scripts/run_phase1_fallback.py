"""Phase 1 单算子兜底跑测：用于合并 build 连坐失败的仓。

策略：对指定仓的 BUILD_FAIL 算子，串行调用 phase_examples.process_op
（独立 build/install/run），仓间 ProcessPool 并发（默认 3 worker）。

为什么不复用 run_phase1_batched：合并 build 一坏全坏，无法区分真假；
单算子串行才能识别每个算子的真实状态。

CLI：
  python3 run_phase1_fallback.py --repo-mapping repo1=path1,repo2=path2,...
                                 [--statuses BUILD_FAIL,INSTALL_FAIL]
                                 [--max-workers 3]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from state import load as load_state  # noqa: E402

# 所有产物写到 CWD/cann-ops-report/test/
WORK_DIR = Path.cwd() / "cann-ops-report/test"
OUTPUTS_DIR = WORK_DIR

DEFAULT_STATUSES = {"BUILD_FAIL", "INSTALL_FAIL"}

# SOC 由 main() 从 --soc 参数填入，跨进程通过 fork 继承
SOC: str = ""


def parse_repo_mapping(s: str) -> dict[str, str]:
    """解析 --repo-mapping 参数：repo1=path1,repo2=path2 → dict。"""
    out: dict[str, str] = {}
    for entry in s.split(","):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError(f"--repo-mapping 项 {entry!r} 缺少 '='")
        name, path = entry.split("=", 1)
        out[name.strip()] = path.strip()
    return out


# REPO_PATHS 在 main() 由 CLI 参数填入，跨进程通过 fork 继承
REPO_PATHS: dict[str, str] = {}


def pick_ops(repo: str, statuses: set[str]) -> list[str]:
    data = load_state()
    ops = data["repos"].get(repo, {}).get("ops", {})
    return [
        op for op, st in ops.items()
        if st.get("phase1", {}).get("status") in statuses
    ]


def run_repo_fallback(repo: str, ops: list[str]) -> dict:
    """对一个仓的 ops 列表串行单算子跑测。子进程内 import phase_examples 直跑。"""
    from phase_examples import process_op

    repo_path_str = REPO_PATHS.get(repo)
    if not repo_path_str:
        print(f"[{repo}] SKIP: 调用方未提供该仓路径（--repo-mapping）", flush=True)
        return {"repo": repo, "total_s": 0, "counts": {"SKIPPED": len(ops)}, "per_op": []}
    repo_path = Path(repo_path_str)
    t0 = time.time()
    counts: dict[str, int] = {}
    per_op = []
    print(f"[{repo}] start fallback for {len(ops)} ops", flush=True)
    for i, op in enumerate(ops, 1):
        op_t0 = time.time()
        status = process_op(
            repo, repo_path, op, SOC,
            build_timeout=900, install_timeout=300, test_timeout=600,
        )
        dt = time.time() - op_t0
        counts[status] = counts.get(status, 0) + 1
        per_op.append({"op": op, "status": status, "duration_s": round(dt, 1)})
        symbol = "✓" if status == "PASS" else "✗"
        print(f"[{repo}] [{i}/{len(ops)}] {symbol} {op}: {status} ({dt:.0f}s)", flush=True)

    total = time.time() - t0
    print(f"[{repo}] done {counts.get('PASS',0)}/{len(ops)} PASS in {total:.0f}s", flush=True)
    return {"repo": repo, "total_s": total, "counts": counts, "per_op": per_op}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo-mapping", required=True,
                    help="仓名到本地路径的映射，CSV 格式：repo1=path1,repo2=path2,...")
    ap.add_argument("--soc", required=True,
                    help="目标 SOC 名称（如 ascend910b / ascend950 等），由 skill 询问用户得到")
    ap.add_argument("--statuses", default="BUILD_FAIL,INSTALL_FAIL",
                    help="re-run ops in these phase1 statuses")
    ap.add_argument("--max-workers", type=int, default=3)
    args = ap.parse_args()

    global SOC
    SOC = args.soc

    REPO_PATHS.update(parse_repo_mapping(args.repo_mapping))
    repos = list(REPO_PATHS.keys())
    if not repos:
        ap.error("--repo-mapping 至少要包含一项")
    statuses = {s.strip() for s in args.statuses.split(",") if s.strip()}

    plan = {repo: pick_ops(repo, statuses) for repo in repos}
    total_ops = sum(len(v) for v in plan.values())
    print(f"=== fallback plan: {total_ops} ops across {len(repos)} repos ===")
    for repo, ops in plan.items():
        print(f"  [{repo}] {len(ops)} ops")
    if total_ops == 0:
        print("nothing to do.")
        return 0

    t0 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=args.max_workers) as ex:
        fut2repo = {
            ex.submit(run_repo_fallback, repo, ops): repo
            for repo, ops in plan.items() if ops
        }
        for fut in as_completed(fut2repo):
            results.append(fut.result())

    total = time.time() - t0
    print("\n📊 单算子兜底跑测最终报告")
    overall: dict[str, int] = {}
    for r in sorted(results, key=lambda x: x["repo"]):
        c = r["counts"]
        passed = c.get("PASS", 0)
        n = sum(c.values())
        print(f"  [{r['repo']}] {passed}/{n} PASS, {r['total_s']:.0f}s, {c}")
        for k, v in c.items():
            overall[k] = overall.get(k, 0) + v
    print(f"\nTOTAL: {overall.get('PASS',0)}/{sum(overall.values())} PASS")
    print(f"状态分布: {overall}")
    print(f"总耗时: {total/60:.1f} 分钟")

    OUTPUTS_DIR.mkdir(exist_ok=True)
    report_path = OUTPUTS_DIR / "phase1_fallback_report.json"
    report_path.write_text(json.dumps({
        "results": results, "overall": overall, "total_s": total,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"📄 详细报告: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
