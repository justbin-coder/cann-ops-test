"""Runtime path helpers. Paths are computed on each call so that fixtures
which change cwd mid-test resolve correctly.
"""
from __future__ import annotations

from pathlib import Path


class _LazyPath:
    """Recompute the path from cwd on every attribute access used by tests."""

    def __init__(self, *parts: str) -> None:
        self._parts = parts

    def __eq__(self, other: object) -> bool:
        return self._resolve() == other

    def __truediv__(self, other: str) -> Path:
        return self._resolve() / other

    def __fspath__(self) -> str:
        return str(self._resolve())

    def __repr__(self) -> str:
        return repr(self._resolve())

    def _resolve(self) -> Path:
        return Path.cwd().joinpath(*self._parts)


WORK_DIR = _LazyPath("cann-ops-report", "issues")
STATE_FILE = _LazyPath("cann-ops-report", "issues", "state.json")
REPOS_FILE = _LazyPath("cann-ops-report", "issues", "repos.json")
DRAFTS_DIR = _LazyPath("cann-ops-report", "issues", "drafts")
SUBMITTED_DIR = _LazyPath("cann-ops-report", "issues", "submitted")

TEST_DIR = _LazyPath("cann-ops-report", "test")
TEST_STATE_FILE = _LazyPath("cann-ops-report", "test", "run_state.json")
TEST_LOGS_DIR = _LazyPath("cann-ops-report", "test", "logs")
TEST_FAILURES_DIR = _LazyPath("cann-ops-report", "test", "failures")

SCANN_DIR = _LazyPath("cann-ops-report", "scann")
