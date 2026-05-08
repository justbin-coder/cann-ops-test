"""Phase 1：examples 端到端跑测。

来源：<repo>/docs/QUICKSTART.md §一（4 仓接口同构）

每个算子的生命周期：
  step 1: build       bash build.sh --pkg --soc=<soc> --ops=<op> -j16
  step 2: install     ./build_out/cann-ops-<repo>-*linux*.run --quiet
  step 3: run         bash build.sh --run_example <op> eager cust --vendor_name=<vendor>
  step 4: judge       exit_code==0 AND stdout matches success_pattern

CLI（skill 内部使用，用户不直接调用）：
  python3 phase_examples.py --repo <name> --repo-path <path> \
      --inputs <json> --soc <soc_version> [--op <op>] [--build-timeout 600] \
      [--test-timeout 600]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# 允许直接 python3 phase_examples.py（不用 -m runner.phase_examples）
sys.path.insert(0, str(Path(__file__).resolve().parent))

from state import init_repo, update_op  # noqa: E402
from utils import (  # noqa: E402
    append_ld_library_path, ensure_log_path, find_run_pkg, run_cmd, vendor_name_for,
)


def has_examples(op_dir: Path) -> bool:
    """判断算子目录下是否存在可跑的 example（test_*.cpp）。"""
    ex = op_dir / "examples"
    if not ex.is_dir():
        return False
    return any(ex.rglob("test_*.cpp"))


def find_op_dir(repo_path: Path, op: str) -> Path | None:
    """在仓内定位算子目录（带 op_kernel/op_host 的才算真目录，排除 3rd 和 fast_kernel_launch_example）。"""
    for p in repo_path.rglob(op):
        if not (p.is_dir() and p.name == op):
            continue
        sp = str(p)
        if "/3rd/" in sp or "/fast_kernel_launch_example/" in sp:
            continue
        if (p / "op_kernel").exists() or (p / "op_host").exists():
            return p
    return None


def build_op(repo: str, repo_path: Path, op: str, soc: str, timeout: int) -> bool:
    log = ensure_log_path(repo, op, "phase1.build")
    cmd = f"bash build.sh --pkg --soc={soc} --ops={op} -j16"
    res = run_cmd(cmd, repo_path, timeout=timeout, log_path=log)
    if res.exit_code != 0:
        update_op(repo, op, "phase1", "BUILD_FAIL", res.duration_s, str(log),
                  extra={"step": "build"})
        return False
    return True


def install_pkg(repo: str, repo_path: Path, op: str, install_timeout: int) -> bool:
    pkg = find_run_pkg(repo_path)
    log = ensure_log_path(repo, op, "phase1.install")
    if pkg is None:
        log.write_text("[ERROR] build_out/cann-ops-*linux*.run not found\n", encoding="utf-8")
        update_op(repo, op, "phase1", "INSTALL_FAIL", 0.0, str(log),
                  extra={"step": "install", "reason": "run_pkg_not_found"})
        return False
    cmd = f"{pkg} --quiet"
    res = run_cmd(cmd, repo_path, timeout=install_timeout, log_path=log)
    if res.exit_code != 0:
        # 部分版本没有 --quiet，回退尝试无参
        cmd = str(pkg)
        res = run_cmd(cmd, repo_path, timeout=install_timeout, log_path=log)
        if res.exit_code != 0:
            update_op(repo, op, "phase1", "INSTALL_FAIL", res.duration_s, str(log),
                      extra={"step": "install"})
            return False
    return True


def run_example(repo: str, repo_path: Path, op: str, timeout: int) -> tuple[bool, str]:
    """跑 run_example，返回 (passed, status)。"""
    log = ensure_log_path(repo, op, "phase1.run")
    # vendor_name=custom 来自 <repo>/docs/QUICKSTART.md §一-5，literal value(not per-repo)
    cmd = f"bash build.sh --run_example {op} eager cust --vendor_name=custom"

    env = os.environ.copy()
    ascend_home = env.get("ASCEND_HOME_PATH", "")
    if ascend_home:
        env = append_ld_library_path(env, repo, ascend_home)

    res = run_cmd(cmd, repo_path, timeout=timeout, log_path=log, env=env)

    if res.timed_out:
        update_op(repo, op, "phase1", "TIMEOUT", res.duration_s, str(log),
                  extra={"step": "run_example"})
        return False, "TIMEOUT"
    if res.exit_code != 0:
        update_op(repo, op, "phase1", "RUN_EXIT_FAIL", res.duration_s, str(log),
                  extra={"step": "run_example", "exit_code": res.exit_code})
        return False, "RUN_EXIT_FAIL"
    if not res.stdout_matches_success():
        update_op(repo, op, "phase1", "RUN_PATTERN_FAIL", res.duration_s, str(log),
                  extra={"step": "run_example", "note": "exit==0 but no success pattern"})
        return False, "RUN_PATTERN_FAIL"

    update_op(repo, op, "phase1", "PASS", res.duration_s, str(log))
    return True, "PASS"


def process_op(repo: str, repo_path: Path, op: str, soc: str,
               build_timeout: int, install_timeout: int, test_timeout: int) -> str:
    op_dir = find_op_dir(repo_path, op)
    if op_dir is None or not has_examples(op_dir):
        log = ensure_log_path(repo, op, "phase1.precheck")
        log.write_text(
            f"[SKIP] op_dir={op_dir} examples_present="
            f"{has_examples(op_dir) if op_dir else False}\n",
            encoding="utf-8",
        )
        update_op(repo, op, "phase1", "SKIPPED_NO_ARTIFACT", 0.0, str(log),
                  extra={"reason": "no examples/test_*.cpp"})
        return "SKIP"

    if not build_op(repo, repo_path, op, soc, build_timeout):
        return "BUILD_FAIL"
    if not install_pkg(repo, repo_path, op, install_timeout):
        return "INSTALL_FAIL"

    passed, status = run_example(repo, repo_path, op, test_timeout)
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--repo-path", required=True)
    ap.add_argument("--inputs", required=True, help="path to inputs/<repo>.json")
    ap.add_argument("--soc", required=True, help="from precheck, e.g. ascend950")
    ap.add_argument("--op", default=None, help="run a single op only")
    ap.add_argument("--build-timeout", type=int, default=900)
    ap.add_argument("--install-timeout", type=int, default=300)
    ap.add_argument("--test-timeout", type=int, default=600)
    args = ap.parse_args()

    repo_path = Path(args.repo_path)
    if not repo_path.is_dir():
        print(f"[ERROR] repo path not found: {repo_path}", file=sys.stderr)
        return 1

    with open(args.inputs, encoding="utf-8") as f:
        ops = json.load(f)["unique_targets"]

    init_repo(args.repo, ops)

    target_ops = [args.op] if args.op else ops
    for op in target_ops:
        if op not in ops:
            print(f"[WARN] op '{op}' not in inputs, skipping", file=sys.stderr)
            continue
        status = process_op(args.repo, repo_path, op, args.soc,
                           args.build_timeout, args.install_timeout, args.test_timeout)
        print(f"[{args.repo}] {op}: {status}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
