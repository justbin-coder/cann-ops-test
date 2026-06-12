"""Run ops-test runner with an apply_plan result injected as extra args.

Returns:
    {"status": "PASS" | "FAIL" | "ERROR", "detail": str, "log_path": str}
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

try:
    from . import paths
except ImportError:
    import paths  # type: ignore[no-redef]

# Path to run_phase1_batched.py (sibling skill, resolved at call time)
_RUNNER = Path(__file__).resolve().parent.parent.parent.parent / "ops-test" / "scripts" / "run_phase1_batched.py"


def _read_op_phase1(repo: str, op: str) -> dict | None:
    """Return the op's phase1 record from run_state.json, or None if absent."""
    state_path = paths.repo_state_file(repo)
    if not state_path.exists():
        return None
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
        return data["ops"][op]["phase1"]
    except (KeyError, json.JSONDecodeError, TypeError):
        return None


def retest(
    *,
    plan: dict,
    context: dict,
    python: str = sys.executable,
) -> dict:
    """
    context keys: repo, op, repo_path, soc
    plan keys:    ops_test_args (list[str]), kind
    """
    repo = context["repo"]
    op = context["op"]
    repo_path = context.get("repo_path", "")
    soc = context.get("soc", "ascend950")

    if not repo_path:
        return {"status": "ERROR", "detail": "context.repo_path is required for retest", "log_path": ""}

    # Pre-cleanup (clean kind): run shell commands in repo_path before retest.
    cleanup = plan.get("pre_cleanup_commands", []) or []
    for cmd in cleanup:
        try:
            cp = subprocess.run(
                cmd, shell=True, cwd=repo_path,
                capture_output=True, text=True, timeout=300,
            )
        except subprocess.TimeoutExpired:
            return {"status": "ERROR",
                    "detail": f"pre-cleanup command timed out: {cmd}",
                    "log_path": ""}
        if cp.returncode != 0:
            return {"status": "ERROR",
                    "detail": f"pre-cleanup failed (rc={cp.returncode}): {cmd}\n{cp.stderr[-500:]}",
                    "log_path": ""}

    # Snapshot phase1.attempts before the run. update_op() bumps it on every
    # write, so a higher counter afterwards proves THIS retest wrote state —
    # guarding against trusting a STALE status (e.g. an old PASS) if the runner
    # crashes before writing, which would otherwise produce a false PASS.
    before_attempts = (_read_op_phase1(repo, op) or {}).get("attempts", 0)

    base_args = [
        python, str(_RUNNER),
        f"--repo-mapping={repo}={repo_path}",
        f"--soc={soc}",
        f"--ops={op}",
    ]
    base_args.extend(plan.get("ops_test_args", []))

    try:
        result = subprocess.run(
            base_args,
            capture_output=True,
            text=True,
            timeout=3600,
        )
    except subprocess.TimeoutExpired:
        return {"status": "ERROR", "detail": "retest timed out after 3600s", "log_path": ""}
    except Exception as exc:
        return {"status": "ERROR", "detail": str(exc), "log_path": ""}

    combined = result.stdout + result.stderr

    # Primary: authoritative status from run_state.json — but ONLY if this retest
    # actually wrote it (attempts bumped). A stale record (runner crashed before
    # updating) must not be trusted; fall back to the exit code instead.
    after = _read_op_phase1(repo, op)
    if after is not None and after.get("attempts", 0) > before_attempts:
        status = "PASS" if after.get("status") == "PASS" else "FAIL"
    else:
        status = "PASS" if result.returncode == 0 else "FAIL"

    # per-op run log lives under cann-ops-report/<repo>/test/logs/ (per-repo layout)
    run_log = paths.repo_logs_dir(repo) / f"{op}.phase1.run.log"
    return {
        "status": status,
        "detail": combined[-4000:],  # last 4k chars for context
        "log_path": str(run_log) if run_log.exists() else "",
    }
