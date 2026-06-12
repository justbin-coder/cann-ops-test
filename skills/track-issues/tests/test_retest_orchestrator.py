"""Tests for retest_orchestrator.

The orchestrator shells out to run_phase1_batched.py, so we mock subprocess.run
and — after the bug-fix — also verify that run_state.json is consulted.
"""
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import retest_orchestrator


BASE_CTX = {
    "repo": "ops-transformer",
    "op": "grouped_matmul",
    "repo_path": "/fake/repo",
    "soc": "ascend950",
}
BASE_PLAN = {"ops_test_args": [], "kind": "env"}


def _mock_proc(returncode: int, stdout: str = "", stderr: str = "") -> MagicMock:
    return MagicMock(returncode=returncode, stdout=stdout, stderr=stderr)


def _write_state(tmp_cwd: Path, status: str, attempts: int = 1) -> Path:
    state = {"ops": {"grouped_matmul": {"phase1": {"status": status, "attempts": attempts}}}}
    p = tmp_cwd / "cann-ops-report" / "ops-transformer" / "test" / "run_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state), encoding="utf-8")
    return p


def _runner_writes(p: Path, proc: MagicMock):
    """side_effect simulating a real runner: bump phase1.attempts, then return proc."""
    def _se(*args, **kwargs):
        data = json.loads(p.read_text())
        ph = data["ops"]["grouped_matmul"]["phase1"]
        ph["attempts"] = ph.get("attempts", 0) + 1
        p.write_text(json.dumps(data))
        return proc
    return _se


# ── PASS path ────────────────────────────────────────────────────────────────

def test_pass_when_state_shows_pass(tmp_cwd: Path) -> None:
    """Runner writes PASS (attempts bumped) → result PASS."""
    p = _write_state(tmp_cwd, "PASS")
    with patch("subprocess.run", side_effect=_runner_writes(p, _mock_proc(0, stdout="ok"))):
        result = retest_orchestrator.retest(plan=BASE_PLAN, context=BASE_CTX)
    assert result["status"] == "PASS"


# ── FAIL path ────────────────────────────────────────────────────────────────

def test_fail_when_state_shows_build_fail(tmp_cwd: Path) -> None:
    p = _write_state(tmp_cwd, "BUILD_FAIL")
    with patch("subprocess.run", side_effect=_runner_writes(p, _mock_proc(1, stderr="CMake Error"))):
        result = retest_orchestrator.retest(plan=BASE_PLAN, context=BASE_CTX)
    assert result["status"] == "FAIL"


def test_fail_when_no_state_file_and_nonzero_rc(tmp_cwd: Path) -> None:
    """No state file + rc != 0 → FAIL (safe fallback)."""
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc(1, stderr="linker error")
        result = retest_orchestrator.retest(plan=BASE_PLAN, context=BASE_CTX)
    assert result["status"] == "FAIL"


# ── false-positive regressions ───────────────────────────────────────────────

def test_no_false_pass_from_stdout_keyword(tmp_cwd: Path) -> None:
    """PASS keyword in stdout must NOT override a FAIL freshly written to state."""
    p = _write_state(tmp_cwd, "RUN_EXIT_FAIL")
    with patch("subprocess.run",
               side_effect=_runner_writes(p, _mock_proc(0, stdout="All previous tests: PASS test_init"))):
        result = retest_orchestrator.retest(plan=BASE_PLAN, context=BASE_CTX)
    assert result["status"] == "FAIL"


def test_no_false_pass_from_stale_status(tmp_cwd: Path) -> None:
    """If the runner crashes before updating state, a STALE PASS must not be trusted."""
    _write_state(tmp_cwd, "PASS", attempts=5)  # old PASS from a previous run
    # runner crashes: rc != 0 and attempts is NOT bumped (state untouched)
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc(1, stderr="bisheng crashed")
        result = retest_orchestrator.retest(plan=BASE_PLAN, context=BASE_CTX)
    assert result["status"] == "FAIL"


# ── ERROR paths ──────────────────────────────────────────────────────────────

def test_error_when_repo_path_missing(tmp_cwd: Path) -> None:
    ctx = {**BASE_CTX, "repo_path": ""}
    result = retest_orchestrator.retest(plan=BASE_PLAN, context=ctx)
    assert result["status"] == "ERROR"
    assert "repo_path" in result["detail"]


def test_error_on_timeout(tmp_cwd: Path) -> None:
    import subprocess
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=[], timeout=3600)):
        result = retest_orchestrator.retest(plan=BASE_PLAN, context=BASE_CTX)
    assert result["status"] == "ERROR"
    assert "timed out" in result["detail"]


def test_error_on_generic_exception(tmp_cwd: Path) -> None:
    with patch("subprocess.run", side_effect=OSError("no such file")):
        result = retest_orchestrator.retest(plan=BASE_PLAN, context=BASE_CTX)
    assert result["status"] == "ERROR"
    assert "no such file" in result["detail"]


# ── extra ops_test_args are forwarded ────────────────────────────────────────

def test_extra_args_forwarded_to_runner(tmp_cwd: Path) -> None:
    plan = {"ops_test_args": ["--env-extra=FOO=1", "--build-extra-args=-DBAR=ON"], "kind": "env"}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc(1)
        retest_orchestrator.retest(plan=plan, context=BASE_CTX)
    cmd = mock_run.call_args[0][0]
    assert "--env-extra=FOO=1" in cmd
    assert "--build-extra-args=-DBAR=ON" in cmd


# ── pre-cleanup integration ──────────────────────────────────────────────────

def test_pre_cleanup_commands_run_before_retest(tmp_cwd: Path) -> None:
    plan = {
        "kind": "clean",
        "ops_test_args": [],
        "pre_cleanup_commands": ["pkill -f bisheng", "rm -rf kernel_meta_*"],
    }
    calls = []

    def _capture(cmd, *args, **kwargs):
        calls.append((cmd, kwargs.get("shell", False), kwargs.get("cwd")))
        return _mock_proc(0, stdout="")

    with patch("subprocess.run", side_effect=_capture):
        retest_orchestrator.retest(plan=plan, context=BASE_CTX)

    # First two calls must be the cleanup commands (shell=True, cwd=repo_path),
    # last call must be the runner subprocess (list cmd, no shell).
    assert calls[0][0] == "pkill -f bisheng"
    assert calls[0][1] is True
    assert calls[0][2] == "/fake/repo"
    assert calls[1][0] == "rm -rf kernel_meta_*"
    assert isinstance(calls[-1][0], list)
    assert calls[-1][1] is False


def test_pre_cleanup_failure_returns_error(tmp_cwd: Path) -> None:
    plan = {
        "kind": "clean",
        "ops_test_args": [],
        "pre_cleanup_commands": ["bad-command"],
    }
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc(127, stderr="command not found")
        result = retest_orchestrator.retest(plan=plan, context=BASE_CTX)
    assert result["status"] == "ERROR"
    assert "pre-cleanup failed" in result["detail"]


def test_pre_cleanup_timeout_returns_error(tmp_cwd: Path) -> None:
    import subprocess
    plan = {
        "kind": "clean",
        "ops_test_args": [],
        "pre_cleanup_commands": ["sleep 9999"],
    }
    with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=300)):
        result = retest_orchestrator.retest(plan=plan, context=BASE_CTX)
    assert result["status"] == "ERROR"
    assert "pre-cleanup command timed out" in result["detail"]
