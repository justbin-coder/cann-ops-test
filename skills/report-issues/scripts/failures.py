"""Read ops-test's run_state.json and emit a grouped failure dict.

Failure statuses (from ops-test/scripts/state.py):
    BUILD_FAIL, INSTALL_FAIL, RUN_EXIT_FAIL, RUN_PATTERN_FAIL, TIMEOUT
Other statuses (PASS, PENDING, RUNNING, SKIPPED_*) are excluded.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import paths


FAILURE_STATUSES = {
    "BUILD_FAIL", "INSTALL_FAIL",
    "RUN_EXIT_FAIL", "RUN_PATTERN_FAIL", "TIMEOUT",
}


@dataclass(frozen=True)
class FailureRecord:
    repo: str
    op: str
    failure_type: str
    phase: str
    duration_s: float
    log_path: str
    attempts: int


def load_failures() -> dict[str, dict[str, list[FailureRecord]]]:
    """Return {repo: {failure_type: [FailureRecord, ...]}}.

    Reads CWD/cann-ops-report/test/run_state.json. Raises FileNotFoundError
    with a user-friendly message if run_state.json is absent.
    """
    state_file = paths.TEST_STATE_FILE._resolve()
    if not state_file.exists():
        raise FileNotFoundError(
            f"run_state.json not found at {state_file}. "
            f"Did you run cann-ops:ops-test first?"
        )
    state = json.loads(state_file.read_text(encoding="utf-8"))

    grouped: dict[str, dict[str, list[FailureRecord]]] = {}
    for repo, repo_state in state.get("repos", {}).items():
        for op, op_state in repo_state.get("ops", {}).items():
            for phase, phase_state in op_state.items():
                status = phase_state.get("status", "")
                if status not in FAILURE_STATUSES:
                    continue
                rec = FailureRecord(
                    repo=repo,
                    op=op,
                    failure_type=status,
                    phase=phase,
                    duration_s=float(phase_state.get("duration_s") or 0.0),
                    log_path=phase_state.get("log_path", ""),
                    attempts=int(phase_state.get("attempts") or 0),
                )
                grouped.setdefault(repo, {}).setdefault(status, []).append(rec)

    return grouped
