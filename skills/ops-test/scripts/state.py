"""run_state.json 原子读写与状态机。

状态枚举：
  PENDING / RUNNING / PASS / BUILD_FAIL / RUN_EXIT_FAIL /
  RUN_PATTERN_FAIL / TIMEOUT / SKIPPED_NO_ARTIFACT
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

# 所有运行产物写到用户当前工作目录的 cann-ops-report/test/ 子目录。
# skill 安装目录（__file__ 所在位置）不写任何输出文件。
WORK_DIR = Path.cwd() / "cann-ops-report" / "test"
STATE_FILE = WORK_DIR / "run_state.json"

VALID_STATUSES = {
    "PENDING", "RUNNING", "PASS",
    "BUILD_FAIL", "INSTALL_FAIL",
    "RUN_EXIT_FAIL", "RUN_PATTERN_FAIL",
    "TIMEOUT", "SKIPPED_NO_ARTIFACT", "SKIPPED_USER",
}


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def load() -> dict:
    if not STATE_FILE.exists():
        return {"created_at": _now_iso(), "updated_at": _now_iso(), "repos": {}}
    return json.loads(STATE_FILE.read_text(encoding="utf-8"))


def _atomic_write(data: dict) -> None:
    """原子写：先写临时文件再 rename。"""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".run_state.", dir=str(STATE_FILE.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, STATE_FILE)
    except Exception:
        if os.path.exists(tmp_path):
            os.unlink(tmp_path)
        raise


def init_repo(repo: str, ops: list[str]) -> None:
    """首次为某仓初始化状态，已存在的算子保留旧状态。"""
    data = load()
    repo_state = data["repos"].setdefault(repo, {"ops": {}})
    for op in ops:
        if op not in repo_state["ops"]:
            repo_state["ops"][op] = {
                "phase1": {"status": "PENDING", "attempts": 0},
                "phase2": {"status": "PENDING", "attempts": 0},
                "phase3": {"status": "PENDING", "attempts": 0},
                "phase4": {"status": "PENDING", "attempts": 0},
            }
    data["updated_at"] = _now_iso()
    _atomic_write(data)


def update_op(
    repo: str,
    op: str,
    phase: str,
    status: str,
    duration_s: float | None = None,
    log_path: str | None = None,
    extra: dict[str, Any] | None = None,
) -> None:
    """原子更新某算子某 phase 的状态。"""
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status: {status}")
    if phase not in {"phase1", "phase2", "phase3", "phase4"}:
        raise ValueError(f"invalid phase: {phase}")

    data = load()
    repo_state = data["repos"].setdefault(repo, {"ops": {}})
    op_state = repo_state["ops"].setdefault(op, {})
    phase_state = op_state.setdefault(phase, {"status": "PENDING", "attempts": 0})

    phase_state["status"] = status
    phase_state["attempts"] = phase_state.get("attempts", 0) + 1
    phase_state["last_update"] = _now_iso()
    if duration_s is not None:
        phase_state["duration_s"] = round(duration_s, 1)
    if log_path is not None:
        phase_state["log_path"] = log_path
    if extra:
        phase_state.update(extra)

    data["updated_at"] = _now_iso()
    _atomic_write(data)


def get_op(repo: str, op: str) -> dict:
    return load()["repos"].get(repo, {}).get("ops", {}).get(op, {})


def repo_summary(repo: str, phase: str) -> dict[str, int]:
    """返回某仓某 phase 各状态计数。"""
    data = load()
    counts: dict[str, int] = {}
    ops = data["repos"].get(repo, {}).get("ops", {})
    for op_state in ops.values():
        s = op_state.get(phase, {}).get("status", "PENDING")
        counts[s] = counts.get(s, 0) + 1
    return counts
