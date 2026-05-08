#!/usr/bin/env python3
"""
Phase 1 优化版：合并 build + 串行 install + run_example 受限并发
- 仓间：4 个仓并行（build/ 独立）
- 仓内：
  * 一次性 build 全部目标算子（--ops=op1,op2,...）
  * 一次性 install
  * run_example 逐个跑（共享 NPU，避免争抢）
"""
import argparse
import json
import os
import subprocess
import sys
import time
import re
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor, as_completed
from datetime import datetime

# 脚本自身在 skills/ops-test/scripts/，parents[1] 即 skills/ops-test（含 inputs/）
SKILL_DIR = Path(__file__).resolve().parents[1]
CANN_950_TESTER = SKILL_DIR

# ops 仓根目录：优先读 CANN_REPOS_PATH 环境变量，fallback ~/cann
REPOS_PATH = Path(os.environ.get("CANN_REPOS_PATH", str(Path.home() / "cann")))

SOC = "ascend950"

# CANN set_env.sh：优先读 ASCEND_HOME_PATH 推导，fallback 标准路径
def _find_set_env_sh() -> str:
    ascend_home = os.environ.get("ASCEND_HOME_PATH", "")
    if ascend_home:
        candidate = Path(ascend_home).parent.parent / "set_env.sh"
        if candidate.exists():
            return str(candidate)
    return str(Path.home() / "Ascend/ascend-toolkit/latest/set_env.sh")

SET_ENV_SH = _find_set_env_sh()
REPOS = ['ops-transformer', 'ops-cv', 'ops-math', 'ops-nn']

# PASS 判定的 stdout 模式（从 utils.py 同步）
SUCCESS_PATTERNS = [
    re.compile(r"result\[\d+\]\s+is:"),
    re.compile(r"All tests passed"),
    re.compile(r"Test PASSED"),
    re.compile(r"\bpassed\b", re.IGNORECASE),
    re.compile(r"PASS\b"),
]


def extract_ops(repo: str) -> list:
    """从 inputs JSON 提取目标算子列表"""
    with open(CANN_950_TESTER / f"inputs/{repo}.json") as f:
        return json.load(f).get("unique_targets", [])


def find_op_dir(repo_path: Path, op: str) -> Path | None:
    """定位算子目录"""
    for p in repo_path.rglob(op):
        if not (p.is_dir() and p.name == op):
            continue
        sp = str(p)
        if "/3rd/" in sp or "/fast_kernel_launch_example/" in sp:
            continue
        if (p / "op_kernel").exists() or (p / "op_host").exists():
            return p
    return None


def has_examples(op_dir: Path) -> bool:
    ex = op_dir / "examples"
    return ex.is_dir() and any(ex.rglob("test_*.cpp"))


def run_shell(cmd: str, cwd: Path, log_path: Path, timeout: int) -> dict:
    """运行 shell 命令（带 set_env.sh），全量捕获日志"""
    # 在 bash -c 里 source set_env.sh，再跑命令
    full_cmd = f"source {SET_ENV_SH} && {cmd}"
    
    log_path.parent.mkdir(parents=True, exist_ok=True)
    start = time.time()
    
    try:
        proc = subprocess.run(
            ["bash", "-c", full_cmd],
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        timed_out = False
        exit_code = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as e:
        exit_code = 124
        stdout = (e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")) or ""
        stderr = (e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")) or ""
        stderr += f"\n[TIMEOUT after {timeout}s]\n"
        timed_out = True
    
    duration = time.time() - start
    
    # 写日志
    log_path.write_text(
        f"$ cd {cwd}\n$ {cmd}\n[exit={exit_code} duration={duration:.1f}s timeout={timeout}s]\n"
        f"\n--- STDOUT ---\n{stdout}\n--- STDERR ---\n{stderr}\n",
        encoding="utf-8", errors="replace",
    )
    
    return {
        "exit_code": exit_code,
        "duration_s": duration,
        "stdout": stdout,
        "stderr": stderr,
        "timed_out": timed_out,
    }


def stdout_matches_success(stdout: str) -> bool:
    return any(p.search(stdout) for p in SUCCESS_PATTERNS)


def run_repo_optimized(repo: str) -> dict:
    """
    优化的仓级跑测：
    1. 过滤出有 examples 的目标算子
    2. 一次性 build 全部
    3. 一次性 install
    4. 逐个 run_example
    """
    repo_path = REPOS_PATH / repo
    if not repo_path.exists():
        return {"repo": repo, "status": "REPO_NOT_FOUND"}
    
    repo_log_dir = CANN_950_TESTER / "outputs" / "logs" / repo
    repo_log_dir.mkdir(parents=True, exist_ok=True)
    
    target_ops = extract_ops(repo)
    
    # Step 0: 算子分类
    buildable_ops = []   # 有 examples，要参与 build
    skipped_ops = []     # 无 examples 或目录找不到
    
    for op in target_ops:
        op_dir = find_op_dir(repo_path, op)
        if op_dir and has_examples(op_dir):
            buildable_ops.append(op)
        else:
            skipped_ops.append(op)
    
    result = {
        "repo": repo,
        "total": len(target_ops),
        "buildable": len(buildable_ops),
        "skipped_no_artifact": len(skipped_ops),
        "ops_status": {},
        "phase_durations": {},
    }
    
    for op in skipped_ops:
        result["ops_status"][op] = "SKIPPED_NO_ARTIFACT"
    
    if not buildable_ops:
        result["status"] = "NO_BUILDABLE_OPS"
        return result
    
    print(f"[{repo}] 开始：{len(buildable_ops)} 个可 build / {len(skipped_ops)} 个 SKIP", flush=True)
    
    # Step 1: 合并 build（一次性 build 全部目标算子）
    ops_csv = ",".join(buildable_ops)
    build_log = repo_log_dir / "_BATCH.phase1.build.log"
    build_cmd = f"bash build.sh --pkg --soc={SOC} --ops={ops_csv} -j16"
    
    print(f"[{repo}] Building {len(buildable_ops)} ops...", flush=True)
    build_t0 = time.time()
    build_res = run_shell(build_cmd, repo_path, build_log, timeout=3600)
    result["phase_durations"]["build"] = time.time() - build_t0
    
    if build_res["exit_code"] != 0:
        # 全部算子标记 BUILD_FAIL
        for op in buildable_ops:
            result["ops_status"][op] = "BUILD_FAIL"
        result["status"] = "BUILD_FAIL"
        result["build_log"] = str(build_log)
        print(f"[{repo}] ❌ Build failed (exit={build_res['exit_code']}, {result['phase_durations']['build']:.0f}s)", flush=True)
        return result
    
    print(f"[{repo}] ✓ Build done in {result['phase_durations']['build']:.0f}s", flush=True)
    
    # Step 2: 一次性 install
    pkg_candidates = sorted((repo_path / "build_out").glob("cann-ops-*linux*.run"))
    if not pkg_candidates:
        for op in buildable_ops:
            result["ops_status"][op] = "INSTALL_FAIL"
        result["status"] = "INSTALL_FAIL_NO_PKG"
        return result
    
    pkg = pkg_candidates[-1]
    install_log = repo_log_dir / "_BATCH.phase1.install.log"
    install_cmd = f"{pkg} --quiet"
    
    print(f"[{repo}] Installing pkg...", flush=True)
    install_t0 = time.time()
    install_res = run_shell(install_cmd, repo_path, install_log, timeout=600)
    result["phase_durations"]["install"] = time.time() - install_t0
    
    if install_res["exit_code"] != 0:
        # fallback 不带 --quiet
        install_res = run_shell(str(pkg), repo_path, install_log, timeout=600)
        if install_res["exit_code"] != 0:
            for op in buildable_ops:
                result["ops_status"][op] = "INSTALL_FAIL"
            result["status"] = "INSTALL_FAIL"
            return result
    
    print(f"[{repo}] ✓ Install done in {result['phase_durations']['install']:.0f}s", flush=True)
    
    # Step 3: 逐个 run_example（NPU 共享，串行）
    print(f"[{repo}] Running {len(buildable_ops)} examples...", flush=True)
    run_t0 = time.time()
    pass_count = 0
    
    for i, op in enumerate(buildable_ops, 1):
        run_log = repo_log_dir / f"{op}.phase1.run.log"
        run_cmd = f"bash build.sh --run_example {op} eager cust --vendor_name=custom"
        
        run_res = run_shell(run_cmd, repo_path, run_log, timeout=300)
        
        if run_res["timed_out"]:
            status = "TIMEOUT"
        elif run_res["exit_code"] != 0:
            status = "RUN_EXIT_FAIL"
        elif not stdout_matches_success(run_res["stdout"]):
            status = "RUN_PATTERN_FAIL"
        else:
            status = "PASS"
            pass_count += 1
        
        result["ops_status"][op] = status
        symbol = "✅" if status == "PASS" else "❌"
        print(f"[{repo}] [{i}/{len(buildable_ops)}] {symbol} {op}: {status}", flush=True)
    
    result["phase_durations"]["run"] = time.time() - run_t0
    result["pass_count"] = pass_count
    result["status"] = "DONE"
    
    return result


def sync_to_state_json(repo_results):
    """把 batched 跑测结果同步写入 run_state.json（主进程统一写，无并发冲突）。

    见 SKILL.md 「报告与续跑」节：诊断模式与下次续跑都依赖此文件。
    """
    # 延迟导入，避免 ProcessPool worker 进程也加载 state.py
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from state import init_repo, update_op  # noqa: E402

    for r in repo_results:
        repo = r.get("repo")
        if not repo:
            continue
        ops_status = r.get("ops_status", {})
        if not ops_status:
            continue
        # 先初始化（保持 PENDING 占位）
        init_repo(repo, list(ops_status.keys()))
        # 再逐个写状态
        durations = r.get("phase_durations", {})
        # 平均化分摊到每个算子（合并 build 没有 per-op build 时长）
        per_op_share = {
            "build": durations.get("build", 0) / max(1, len(ops_status)),
            "install": durations.get("install", 0) / max(1, len(ops_status)),
        }
        for op, status in ops_status.items():
            extra = {"mode": "batched"}
            if status == "BUILD_FAIL":
                extra["step"] = "build"
                extra["log_path_hint"] = r.get("build_log")
            update_op(repo, op, "phase1", status,
                      duration_s=per_op_share["build"] + per_op_share["install"],
                      extra=extra)


def generate_report(repo_results, total_time):
    """生成最终报告"""
    sync_to_state_json(repo_results)

    print(f"\n\n{'='*80}")
    print(f"📊 Phase 1 跑测最终报告（合并 build + 仓间并发）")
    print(f"{'='*80}\n")
    
    grand_total_pass = 0
    grand_total_ops = 0
    grand_status_counts = {}
    
    full_report = {
        "phase": 1,
        "mode": "batched_build_with_repo_concurrency",
        "timestamp": datetime.now().isoformat(),
        "total_duration_seconds": total_time,
        "repos": {},
    }
    
    for r in repo_results:
        repo = r["repo"]
        total = r.get("total", 0)
        pass_count = r.get("pass_count", 0)
        durations = r.get("phase_durations", {})
        
        grand_total_pass += pass_count
        grand_total_ops += total
        
        for op, status in r.get("ops_status", {}).items():
            grand_status_counts[status] = grand_status_counts.get(status, 0) + 1
        
        # 仓内状态分布
        repo_status_counts = {}
        for status in r.get("ops_status", {}).values():
            repo_status_counts[status] = repo_status_counts.get(status, 0) + 1
        
        pct = 100 * pass_count // total if total > 0 else 0
        build_t = durations.get("build", 0)
        install_t = durations.get("install", 0)
        run_t = durations.get("run", 0)
        
        print(f"┌─ {repo} ({total} 个算子)")
        print(f"│  ⏱️  build={build_t:.0f}s  install={install_t:.0f}s  run={run_t:.0f}s")
        print(f"│  ✅ PASS: {pass_count}/{total} ({pct}%)")
        for status, count in sorted(repo_status_counts.items(), key=lambda x: -x[1]):
            if status != "PASS":
                symbol = "⏱️" if status == "TIMEOUT" else "❌"
                print(f"│  {symbol} {status}: {count}")
        print(f"└─\n")
        
        full_report["repos"][repo] = {
            "total": total,
            "passed": pass_count,
            "phase_durations": durations,
            "status_counts": repo_status_counts,
            "ops_status": r.get("ops_status", {}),
            "build_log": r.get("build_log"),
        }
    
    print(f"{'─'*80}")
    pass_pct = 100 * grand_total_pass // grand_total_ops if grand_total_ops > 0 else 0
    print(f"  TOTAL: {grand_total_pass}/{grand_total_ops} PASS ({pass_pct}%)")
    print(f"{'─'*80}\n")
    
    print(f"📋 状态分布:")
    for status, count in sorted(grand_status_counts.items(), key=lambda x: -x[1]):
        pct = 100 * count // grand_total_ops if grand_total_ops > 0 else 0
        print(f"   {status:25s} {count:3d} ({pct}%)")
    
    full_report["total_operators"] = grand_total_ops
    full_report["total_passed"] = grand_total_pass
    full_report["pass_rate"] = pass_pct
    full_report["status_distribution"] = grand_status_counts
    
    report_file = CANN_950_TESTER / "outputs/phase1_report_final.json"
    with open(report_file, 'w') as f:
        json.dump(full_report, f, indent=2, ensure_ascii=False)
    print(f"\n📄 详细报告: {report_file}")
    print(f"⏱️  总耗时: {total_time/60:.1f} 分钟")
    
    return full_report


def main():
    ap = argparse.ArgumentParser(description="Phase 1 batched runner (仓内合并 build + 仓间并发)")
    ap.add_argument("--repo", choices=REPOS, default=None,
                    help="只跑指定仓（场景 B）；不传则四仓并发（场景 A）")
    args = ap.parse_args()

    target_repos = [args.repo] if args.repo else REPOS

    print(f"📋 启动 Phase 1 优化版跑测")
    if args.repo:
        print(f"   策略：单仓模式（{args.repo}） + 仓内合并 build")
    else:
        print(f"   策略：仓间并发({len(target_repos)}) + 仓内合并 build")
    print(f"   SOC: {SOC}")
    print(f"   set_env.sh: {SET_ENV_SH}")
    print()

    for repo in target_repos:
        ops = extract_ops(repo)
        print(f"   {repo:20s}  {len(ops):2d} 个目标算子")
    print()

    total_start = time.time()

    repo_results = []
    if len(target_repos) == 1:
        # 场景 B：单仓直接跑（不进 ProcessPool，便于实时日志）
        try:
            result = run_repo_optimized(target_repos[0])
            repo_results.append(result)
        except Exception as e:
            repo_results.append({"repo": target_repos[0], "status": "EXEC_ERROR", "error": str(e)})
    else:
        # 场景 A：仓间并发 4 worker
        with ProcessPoolExecutor(max_workers=len(target_repos)) as executor:
            future_to_repo = {executor.submit(run_repo_optimized, repo): repo for repo in target_repos}
            for future in as_completed(future_to_repo):
                try:
                    result = future.result()
                    repo_results.append(result)
                except Exception as e:
                    repo = future_to_repo[future]
                    print(f"💥 {repo}: {e}", flush=True)
                    repo_results.append({"repo": repo, "status": "EXEC_ERROR", "error": str(e)})

    total_time = time.time() - total_start
    generate_report(repo_results, total_time)


if __name__ == '__main__':
    main()
