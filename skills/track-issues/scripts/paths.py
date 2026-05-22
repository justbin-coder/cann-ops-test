"""Runtime CWD-relative paths for track-issues. Mirrors report-issues/paths.py
so the same _LazyPath idiom works under tests that chdir."""
from __future__ import annotations

from pathlib import Path


class _LazyPath:
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


ISSUES_DIR = _LazyPath("cann-ops-report", "issues")
STATE_FILE = _LazyPath("cann-ops-report", "issues", "state.json")
COMMENTS_DIR = _LazyPath("cann-ops-report", "issues", "comments")
PLANS_DIR = _LazyPath("cann-ops-report", "issues", "plans")
REPLIES_DIR = _LazyPath("cann-ops-report", "issues", "replies")
PATCHES_DIR = _LazyPath("cann-ops-report", "issues", "patches")

FAQ_DIR = _LazyPath("cann-ops-report", "faq")
FAQ_JSON = _LazyPath("cann-ops-report", "faq", "known_fixes.json")
FAQ_MD = _LazyPath("cann-ops-report", "faq", "FAQ.md")

TEST_STATE_FILE = _LazyPath("cann-ops-report", "test", "run_state.json")
TEST_LOGS_DIR = _LazyPath("cann-ops-report", "test", "logs")
