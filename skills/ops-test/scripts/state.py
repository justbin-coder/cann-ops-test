"""run_state.json 原子读写与状态机。

状态枚举：
  PENDING / RUNNING / PASS / BUILD_FAIL / INSTALL_FAIL /
  RUN_EXIT_FAIL / RUN_PATTERN_FAIL / UNCERTAIN /
  TIMEOUT / SKIPPED_NO_ARTIFACT / SKIPPED_USER

UNCERTAIN：四层日志判定 L3 兜底状态——exit==0 但既无强成功也无强失败信号。
  跑测中不阻塞，标记后跑完由 agent 集中判定，最终落到 PASS 或 RUN_PATTERN_FAIL。
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
    "RUN_EXIT_FAIL", "RUN_PATTERN_FAIL", "UNCERTAIN",
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


# 失败类状态（写 SUMMARY.md 时归入"失败明细"）
_FAIL_STATUSES = {"BUILD_FAIL", "INSTALL_FAIL", "RUN_EXIT_FAIL", "RUN_PATTERN_FAIL", "TIMEOUT"}


def write_summary_md(phase: str = "phase1", soc: str = "") -> Path:
    """把 run_state 渲染成给人看的简洁 SUMMARY.md（覆盖写，多仓各一行）。"""
    data = load()
    lines = [
        "# 跑测摘要（示例跑测）",
        "",
        f"> 更新：{_now_iso()}" + (f" · SOC: {soc}" if soc else ""),
        "",
        "| 仓 | 通过 | 失败 | 跳过 | 待复核 |",
        "|---|---|---|---|---|",
    ]
    fail_rows = []
    for repo in sorted(data["repos"]):
        ops = data["repos"][repo]["ops"]
        cnt: dict[str, int] = {}
        for op, st in sorted(ops.items()):
            s = st.get(phase, {}).get("status", "PENDING")
            cnt[s] = cnt.get(s, 0) + 1
            if s in _FAIL_STATUSES:
                fail_rows.append(f"| {repo} | {op} | {s} | {st[phase].get('log_path', '—')} |")
        total = len(ops)
        n_fail = sum(cnt.get(s, 0) for s in _FAIL_STATUSES)
        n_skip = cnt.get("SKIPPED_NO_ARTIFACT", 0) + cnt.get("SKIPPED_USER", 0)
        lines.append(f"| {repo} | {cnt.get('PASS', 0)}/{total} | {n_fail} | {n_skip} | {cnt.get('UNCERTAIN', 0)} |")

    if fail_rows:
        lines += ["", "## 失败明细", "", "| 仓 | 算子 | 类型 | 日志 |", "|---|---|---|---|"] + fail_rows

    explore_rows = _collect_exploration_rows()
    if explore_rows:
        lines += ["", "## 探索结果（P6）", "", "| 仓 | 算子 | 结论 | 方案 / 根因 |", "|---|---|---|---|"] + explore_rows
    lines.append("")

    out = WORK_DIR / "SUMMARY.md"
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def _collect_exploration_rows() -> list[str]:
    """从 explorations/<repo>/<op>.md 抽取 P6 结论行（无产物时返回空）。"""
    rows = []
    root = WORK_DIR / "explorations"
    if not root.is_dir():
        return rows
    for repo_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        for f in sorted(repo_dir.glob("*.md")):
            if f.name.startswith("_"):
                continue
            text = f.read_text(encoding="utf-8").splitlines()
            verdict = "SOLVED" if "UNSOLVED" not in text[0] else "UNSOLVED"
            hint = ""
            for l in text:
                stripped = l.lstrip("- ").strip()
                if stripped.startswith(("方案", "修复在仓")):
                    hint = stripped.split(":", 1)[-1].split("：", 1)[-1].strip()
                    break
            rows.append(f"| {repo_dir.name} | {f.stem} | {verdict} | {hint[:70]} |")
    return rows
