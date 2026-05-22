"""Run ops-test runner with an apply_plan result injected as extra args.

Returns:
    {"status": "PASS" | "FAIL" | "ERROR", "detail": str, "log_path": str}
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# Path to run_phase1_batched.py (sibling skill, resolved at call time)
_RUNNER = Path(__file__).resolve().parent.parent.parent.parent / "ops-test" / "scripts" / "run_phase1_batched.py"


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

    # Determine PASS/FAIL from runner output
    if result.returncode == 0 and ("PASS" in combined or "passed" in combined.lower()):
        status = "PASS"
    elif "BUILD_FAIL" in combined or "INSTALL_FAIL" in combined or result.returncode != 0:
        status = "FAIL"
    else:
        status = "FAIL"

    return {
        "status": status,
        "detail": combined[-4000:],  # last 4k chars for context
        "log_path": "",              # runner writes per-op logs under cann-ops-report/test/logs/
    }
