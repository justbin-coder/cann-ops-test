"""Local-state dedup. Key = repo::op::failure_type.

state.json schema:
    {
      "<repo>::<op>::<failure_type>": {
        "issue_url": "...",
        "submitted_at": "ISO8601",
        "phase": "phase1",
        "submitted_via": "api" | "manual"
      },
      ...
    }
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Iterable

from . import paths


def make_key(repo: str, op: str, failure_type: str) -> str:
    return f"{repo}::{op}::{failure_type}"


def _load() -> dict:
    state_file = paths.STATE_FILE._resolve()
    if not state_file.exists():
        return {}
    return json.loads(state_file.read_text(encoding="utf-8"))


def _atomic_save(data: dict) -> None:
    state_file = paths.STATE_FILE._resolve()
    state_file.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".state.", dir=str(state_file.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, state_file)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def is_submitted(repo: str, op: str, failure_type: str) -> bool:
    return make_key(repo, op, failure_type) in _load()


def get_record(repo: str, op: str, failure_type: str) -> dict | None:
    return _load().get(make_key(repo, op, failure_type))


def mark_submitted(
    *,
    repo: str,
    op: str,
    failure_type: str,
    issue_url: str,
    phase: str,
    submitted_via: str,
) -> None:
    data = _load()
    data[make_key(repo, op, failure_type)] = {
        "issue_url": issue_url,
        "submitted_at": datetime.now().isoformat(timespec="seconds"),
        "phase": phase,
        "submitted_via": submitted_via,
    }
    _atomic_save(data)


def split_new_vs_submitted(
    keys: Iterable[tuple[str, str, str]],
) -> tuple[list[tuple[str, str, str]], list[tuple[str, str, str]]]:
    data = _load()
    new: list[tuple[str, str, str]] = []
    already: list[tuple[str, str, str]] = []
    for repo, op, ft in keys:
        if make_key(repo, op, ft) in data:
            already.append((repo, op, ft))
        else:
            new.append((repo, op, ft))
    return new, already
