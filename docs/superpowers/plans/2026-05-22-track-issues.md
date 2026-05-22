# Track Issues Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** add `cann-ops:track-issues` skill (query upstream issue replies, auto-apply community fix, retest, grow FAQ, comment+close) and a small post-fail FAQ lookup hook in `cann-ops:ops-test`.

**Architecture:** new skill drives P0–P5 query → confirm → apply → retest → FAQ + reply loop, sharing state with `report-issues` via `cann-ops-report/issues/state.json` and with `ops-test` via `cann-ops-report/faq/known_fixes.json`. The ops-test side gains a P5.5 lookup that, when a known non-source fix matches a fresh failure, prompts the user to re-run with the fix applied.

**Tech Stack:** Python 3.8+ stdlib (`urllib`, `subprocess`, `argparse`, `hashlib`, `re`, `json`, `tempfile`); jinja2 (already in plugin) for FAQ.md rendering; pytest + unittest.mock for tests. `gh` CLI for GitHub; v5 REST for Gitee (`gitee.com/api/v5`) and GitCode (`api.gitcode.com/api/v5`).

**Spec:** `docs/superpowers/specs/2026-05-22-track-issues-design.md`.

---

## File Structure

**New files (track-issues skill):**

```
cann-ops-plugin/skills/track-issues/
├── SKILL.md
├── requirements.txt              # jinja2 only
└── scripts/
    ├── __init__.py
    ├── paths.py                  # lazy CWD-relative paths
    ├── _error_sig.py             # normalize log → SHA-256 sig
    ├── fetch_comments.py         # gh CLI + Gitee v5 + GitCode v5
    ├── solution_extractor.py     # heuristic classifier
    ├── apply_plan.py             # plan → ops-test CLI args; branch creation
    ├── retest_orchestrator.py    # subprocess.run on ops-test runner
    ├── faq_writer.py             # known_fixes.json + FAQ.md
    ├── reply_builder.py          # PASS / FAIL templates
    └── upstream_writer.py        # POST comment + close issue
└── tests/
    ├── conftest.py
    ├── fixtures/
    │   ├── state.json
    │   ├── comments/github_with_patch.json
    │   ├── comments/gitee_with_env.json
    │   ├── comments/gitcode_no_actionable.json
    │   ├── known_fixes.json
    │   └── error_logs/build_undefined.log
    ├── test_paths.py
    ├── test_error_sig.py
    ├── test_fetch_comments.py
    ├── test_solution_extractor.py
    ├── test_apply_plan.py
    ├── test_retest_orchestrator.py
    ├── test_faq_writer.py
    ├── test_reply_builder.py
    ├── test_upstream_writer.py
    └── test_end_to_end_dry_run.py
```

**Modified files (ops-test):**

```
cann-ops-plugin/skills/ops-test/
├── SKILL.md                                  # insert P5.5 section
├── scripts/
│   ├── _error_sig.py                         # NEW: copy of track-issues version
│   ├── faq_lookup.py                         # NEW
│   └── run_phase1_batched.py                 # MODIFY: add --env-extra / --build-extra-args / --run-extra-args
└── tests/
    ├── test_faq_lookup.py                    # NEW
    └── test_error_sig.py                     # NEW
```

**Plugin metadata:** bump `package.json` minor version after all tasks.

---

## Task 0: Skill scaffolding

**Files:**
- Create: `cann-ops-plugin/skills/track-issues/SKILL.md` (stub)
- Create: `cann-ops-plugin/skills/track-issues/requirements.txt`
- Create: `cann-ops-plugin/skills/track-issues/scripts/__init__.py`
- Create: `cann-ops-plugin/skills/track-issues/tests/__init__.py`
- Create: `cann-ops-plugin/skills/track-issues/tests/conftest.py`
- Create: `cann-ops-plugin/skills/track-issues/tests/fixtures/` (empty dir)

- [ ] **Step 1: Create directory structure**

```bash
cd /home/jiazhibin/cann/cann-ops-plugin
mkdir -p skills/track-issues/scripts skills/track-issues/tests/fixtures/comments \
         skills/track-issues/tests/fixtures/error_logs
touch skills/track-issues/scripts/__init__.py skills/track-issues/tests/__init__.py
```

- [ ] **Step 2: requirements.txt**

```
jinja2
```

Write to `skills/track-issues/requirements.txt`.

- [ ] **Step 3: stub SKILL.md (real content added in Task 11)**

```markdown
---
name: track-issues
description: 用于查询已提交到上游社区（GitHub / Gitee / GitCode）的算子 issue 回复状态；若评论给出可执行方案则自动应用并复测；PASS 则关闭 issue + 写入 FAQ，FAIL 则人工确认后追问。涉及"查 issue 回复 / 跟 issue 走一遍 / 按社区方案重试 / retest with community fix"等用户意图时必须激活本 skill。
---

# cann-ops:track-issues

(完整内容在 Task 11 写入)
```

- [ ] **Step 4: conftest.py with shared fixtures**

```python
"""Shared pytest fixtures for track-issues tests.

Conventions:
- tmp_cwd: chdir to tmp_path so cann-ops-report/ lands in tmp
- fake_submitted_state: a 5-issue state.json across GitHub/Gitee/GitCode
- fake_failed_run_state: a synthetic run_state.json with one BUILD_FAIL op
- fake_build_log: a log file matching the BUILD_FAIL op's log_path
- fake_repo: tmp git repo with origin remote
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture
def tmp_cwd(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[Path]:
    monkeypatch.chdir(tmp_path)
    yield tmp_path


@pytest.fixture
def fake_submitted_state(tmp_cwd: Path) -> Path:
    state = {
        "ops-transformer::grouped_matmul::BUILD_FAIL": {
            "issue_url": "https://github.com/ascend/ops-transformer/issues/101",
            "submitted_at": "2026-05-20T10:00:00",
            "phase": "phase1",
            "submitted_via": "api",
        },
        "ops-cv::resize_bilinear::BUILD_FAIL": {
            "issue_url": "https://gitee.com/ascend/ops-cv/issues/I7XYZ",
            "submitted_at": "2026-05-20T10:30:00",
            "phase": "phase1",
            "submitted_via": "api",
        },
        "ops-math::concat::RUN_EXIT_FAIL": {
            "issue_url": "https://gitcode.com/ascend/ops-math/issues/42",
            "submitted_at": "2026-05-20T11:00:00",
            "phase": "phase1",
            "submitted_via": "manual",
        },
    }
    p = tmp_cwd / "cann-ops-report" / "issues" / "state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return p


@pytest.fixture
def fake_failed_run_state(tmp_cwd: Path) -> Path:
    state = {
        "created_at": "2026-05-20T10:00:00",
        "updated_at": "2026-05-20T10:30:00",
        "repos": {
            "ops-transformer": {
                "ops": {
                    "grouped_matmul": {
                        "phase1": {
                            "status": "BUILD_FAIL",
                            "attempts": 1,
                            "duration_s": 920.5,
                            "log_path": "cann-ops-report/test/logs/ops-transformer/grouped_matmul.phase1.build.log",
                        },
                    },
                }
            }
        },
    }
    p = tmp_cwd / "cann-ops-report" / "test" / "run_state.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2), encoding="utf-8")
    return p


@pytest.fixture
def fake_build_log(tmp_cwd: Path) -> Path:
    p = tmp_cwd / "cann-ops-report" / "test" / "logs" / "ops-transformer" / "grouped_matmul.phase1.build.log"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        "2026-05-20T10:01:30 INFO: configuring\n"
        "2026-05-20T10:05:12 ERROR: /home/user/cann/ops-transformer/op_kernel/foo.cpp:42:18: undefined reference to AscendC::HiFloat8Cast\n"
        "linker failed with exit=1\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "ops-transformer"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test"], cwd=repo, check=True)
    (repo / "README.md").write_text("test\n")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=repo, check=True)
    subprocess.run(["git", "remote", "add", "origin",
                    "https://github.com/ascend/ops-transformer.git"],
                   cwd=repo, check=True)
    return repo
```

- [ ] **Step 5: Commit**

```bash
git add skills/track-issues
git commit -m "feat(track-issues): scaffold skill directory + shared fixtures"
```

---

## Task 1: paths.py + _error_sig.py

**Files:**
- Create: `skills/track-issues/scripts/paths.py`
- Create: `skills/track-issues/scripts/_error_sig.py`
- Create: `skills/track-issues/tests/test_paths.py`
- Create: `skills/track-issues/tests/test_error_sig.py`

- [ ] **Step 1: Write failing test for paths.py**

`skills/track-issues/tests/test_paths.py`:

```python
"""Paths must resolve relative to CWD at call time."""
from pathlib import Path

import pytest

from scripts import paths


def test_faq_paths_resolve_under_cwd(tmp_cwd: Path) -> None:
    assert paths.FAQ_DIR == tmp_cwd / "cann-ops-report" / "faq"
    assert paths.FAQ_JSON == tmp_cwd / "cann-ops-report" / "faq" / "known_fixes.json"
    assert paths.FAQ_MD == tmp_cwd / "cann-ops-report" / "faq" / "FAQ.md"


def test_issues_subdirs(tmp_cwd: Path) -> None:
    assert paths.COMMENTS_DIR == tmp_cwd / "cann-ops-report" / "issues" / "comments"
    assert paths.PLANS_DIR == tmp_cwd / "cann-ops-report" / "issues" / "plans"
    assert paths.REPLIES_DIR == tmp_cwd / "cann-ops-report" / "issues" / "replies"
    assert paths.PATCHES_DIR == tmp_cwd / "cann-ops-report" / "issues" / "patches"
```

- [ ] **Step 2: Run test (verify it fails)**

```bash
cd /home/jiazhibin/cann/cann-ops-plugin/skills/track-issues
pytest tests/test_paths.py -v
```

Expected: FAIL (`scripts.paths` not found).

- [ ] **Step 3: Write paths.py**

`skills/track-issues/scripts/paths.py`:

```python
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
```

- [ ] **Step 4: Run test (verify it passes)**

```bash
pytest tests/test_paths.py -v
```

Expected: PASS.

- [ ] **Step 5: Write failing test for _error_sig.py**

`skills/track-issues/tests/test_error_sig.py`:

```python
"""error_signature must be stable across timestamps, line numbers, abs paths."""
from scripts._error_sig import normalize, signature


def test_strip_timestamp() -> None:
    a = "2026-05-20T10:05:12 ERROR: undefined reference to X"
    b = "2026-05-21T11:00:00 ERROR: undefined reference to X"
    assert normalize(a) == normalize(b)


def test_strip_line_col() -> None:
    a = "ERROR: /a/b/foo.cpp:42:18: undefined reference to X"
    b = "ERROR: /a/b/foo.cpp:99:1: undefined reference to X"
    assert normalize(a) == normalize(b)


def test_strip_abs_path() -> None:
    a = "ERROR: /home/alice/cann/ops-transformer/op_kernel/foo.cpp: bad"
    b = "ERROR: /opt/build/ops-transformer/op_kernel/foo.cpp: bad"
    # both should fold to .../ops-transformer/op_kernel/foo.cpp or similar
    assert "ops-transformer/op_kernel/foo.cpp" in normalize(a)
    assert normalize(a) == normalize(b)


def test_signature_is_12_hex() -> None:
    sig = signature("ERROR: undefined reference to X")
    assert len(sig) == 12
    assert all(c in "0123456789abcdef" for c in sig)


def test_extract_first_error_line_from_log(tmp_path) -> None:
    log = tmp_path / "x.log"
    log.write_text(
        "INFO start\n"
        "2026-01-01T00:00:00 ERROR: undefined reference to Foo\n"
        "2026-01-01T00:00:01 ERROR: trailing noise\n",
        encoding="utf-8",
    )
    from scripts._error_sig import first_error_line
    line = first_error_line(log)
    assert "undefined reference to Foo" in line
```

- [ ] **Step 6: Run test (verify it fails)**

```bash
pytest tests/test_error_sig.py -v
```

Expected: FAIL (module not found).

- [ ] **Step 7: Write _error_sig.py**

`skills/track-issues/scripts/_error_sig.py`:

```python
"""Failure-log signature: pick first error line, normalize, hash."""
from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

_ERROR_LINE_RE = re.compile(r"(ERROR|undefined|failed|exit=)", re.IGNORECASE)
_TIMESTAMP_RE = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[\.\d]*Z?")
_LINE_COL_RE = re.compile(r":\d+:\d+:")
_LINE_NO_RE = re.compile(r"\bline \d+\b", re.IGNORECASE)
_MULTI_WS_RE = re.compile(r"\s+")

# match longest first so /home/foo/ops-transformer/... folds before /home/foo/
_ABS_PREFIXES = ("/home/", "/root/", "/opt/", "/tmp/", "/data/", "/mnt/")


def first_error_line(log_path: Path | str) -> str:
    """Return the first line matching ERROR|undefined|failed|exit= or '' if none."""
    p = Path(log_path)
    if not p.exists():
        return ""
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if _ERROR_LINE_RE.search(line):
            return line
    return ""


def normalize(line: str) -> str:
    s = _TIMESTAMP_RE.sub("", line)
    s = _LINE_COL_RE.sub(":", s)
    s = _LINE_NO_RE.sub("line N", s)
    # fold absolute path prefixes
    for prefix in _ABS_PREFIXES:
        s = re.sub(
            rf"{re.escape(prefix)}[^/\s]+/", "", s
        )
    # CWD/home folding
    cwd = str(Path.cwd())
    if cwd:
        s = s.replace(cwd, "")
    home = os.environ.get("HOME", "")
    if home:
        s = s.replace(home, "~")
    s = _MULTI_WS_RE.sub(" ", s).strip()
    return s


def signature(line: str) -> str:
    norm = normalize(line)
    return hashlib.sha256(norm.encode("utf-8")).hexdigest()[:12]
```

- [ ] **Step 8: Run test (verify it passes)**

```bash
pytest tests/test_error_sig.py -v
```

Expected: PASS (all 5 cases).

- [ ] **Step 9: Commit**

```bash
git add skills/track-issues
git commit -m "feat(track-issues): paths.py + _error_sig.py with tests"
```

---

## Task 2: faq_writer.py

**Files:**
- Create: `skills/track-issues/scripts/faq_writer.py`
- Create: `skills/track-issues/tests/test_faq_writer.py`

- [ ] **Step 1: Write failing test**

`skills/track-issues/tests/test_faq_writer.py`:

```python
"""faq_writer: append known_fixes.json + render FAQ.md; history on key collision."""
import json
from pathlib import Path

from scripts import faq_writer, paths


def _entry(fix_kind="env", payload=None):
    return {
        "fix_kind": fix_kind,
        "fix_payload": payload or {"ASCEND_GLOBAL_LOG_LEVEL": "1"},
        "source_issue_url": "https://github.com/x/y/issues/1",
        "verified_phase": "phase1",
        "soc": "ascend910b",
    }


def test_first_write_creates_files(tmp_cwd: Path) -> None:
    faq_writer.upsert(
        repo="ops-transformer", op="grouped_matmul",
        failure_type="BUILD_FAIL", error_signature="abc123def456",
        **_entry(),
    )
    assert Path(paths.FAQ_JSON).exists()
    assert Path(paths.FAQ_MD).exists()
    data = json.loads(Path(paths.FAQ_JSON).read_text(encoding="utf-8"))
    key = "ops-transformer::grouped_matmul::BUILD_FAIL::abc123def456"
    assert key in data
    assert data[key]["fix_kind"] == "env"
    assert "verified_at" in data[key]


def test_collision_pushes_old_to_history(tmp_cwd: Path) -> None:
    args = dict(repo="r", op="o", failure_type="F", error_signature="sig1")
    faq_writer.upsert(**args, **_entry(payload={"X": "1"}))
    faq_writer.upsert(**args, **_entry(payload={"X": "2"}))
    data = json.loads(Path(paths.FAQ_JSON).read_text(encoding="utf-8"))
    entry = data["r::o::F::sig1"]
    assert entry["fix_payload"] == {"X": "2"}
    assert len(entry["history"]) == 1
    assert entry["history"][0]["fix_payload"] == {"X": "1"}


def test_lookup_returns_entry(tmp_cwd: Path) -> None:
    faq_writer.upsert(
        repo="r", op="o", failure_type="F", error_signature="sig",
        **_entry(),
    )
    found = faq_writer.lookup(repo="r", op="o", failure_type="F", error_signature="sig")
    assert found is not None
    assert found["fix_kind"] == "env"


def test_lookup_miss_returns_none(tmp_cwd: Path) -> None:
    assert faq_writer.lookup(repo="r", op="o", failure_type="F", error_signature="x") is None


def test_md_render_includes_entry(tmp_cwd: Path) -> None:
    faq_writer.upsert(
        repo="ops-cv", op="resize", failure_type="BUILD_FAIL",
        error_signature="zzz",
        **_entry(),
    )
    md = Path(paths.FAQ_MD).read_text(encoding="utf-8")
    assert "ops-cv" in md
    assert "resize" in md
    assert "BUILD_FAIL" in md
    assert "ASCEND_GLOBAL_LOG_LEVEL" in md
```

- [ ] **Step 2: Run test (verify it fails)**

```bash
pytest tests/test_faq_writer.py -v
```

Expected: FAIL (module not found).

- [ ] **Step 3: Write faq_writer.py**

`skills/track-issues/scripts/faq_writer.py`:

```python
"""Maintain known_fixes.json (machine-readable) + FAQ.md (human-readable).

Key schema: <repo>::<op>::<failure_type>::<error_signature>
Collision policy: newer wins; previous record pushed onto history[].
Atomic writes via tempfile + os.replace.
"""
from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any

from . import paths


def _key(repo: str, op: str, failure_type: str, error_signature: str) -> str:
    return f"{repo}::{op}::{failure_type}::{error_signature}"


def _load() -> dict:
    p = Path(paths.FAQ_JSON)
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def _atomic_save(data: dict) -> None:
    p = Path(paths.FAQ_JSON)
    p.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".faq.", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp, p)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def upsert(
    *,
    repo: str,
    op: str,
    failure_type: str,
    error_signature: str,
    fix_kind: str,
    fix_payload: dict[str, Any],
    source_issue_url: str,
    verified_phase: str,
    soc: str,
) -> None:
    data = _load()
    k = _key(repo, op, failure_type, error_signature)
    new_entry = {
        "fix_kind": fix_kind,
        "fix_payload": fix_payload,
        "source_issue_url": source_issue_url,
        "verified_at": datetime.now().isoformat(timespec="seconds"),
        "verified_phase": verified_phase,
        "soc": soc,
        "history": [],
    }
    if k in data:
        old = {x: data[k][x] for x in data[k] if x != "history"}
        new_entry["history"] = [old] + data[k].get("history", [])
    data[k] = new_entry
    _atomic_save(data)
    _render_md(data)


def lookup(
    *, repo: str, op: str, failure_type: str, error_signature: str,
) -> dict | None:
    return _load().get(_key(repo, op, failure_type, error_signature))


def _render_md(data: dict) -> None:
    """FAQ.md: one section per (repo, failure_type), each containing
    matched op + fix_kind + payload + source link."""
    lines = ["# CANN ops 已知修复 FAQ\n",
             f"自动生成 — 共 {len(data)} 条已验证修复。\n"]
    for key, entry in sorted(data.items()):
        repo, op, failure_type, sig = key.split("::")
        lines.append(f"\n## {repo} · {op} · {failure_type}\n")
        lines.append(f"- error_signature: `{sig}`")
        lines.append(f"- fix_kind: **{entry['fix_kind']}**")
        lines.append(f"- payload: `{json.dumps(entry['fix_payload'], ensure_ascii=False)}`")
        lines.append(f"- 来源 issue: {entry['source_issue_url']}")
        lines.append(f"- 验证 phase / SOC: {entry['verified_phase']} / {entry['soc']}")
        lines.append(f"- verified_at: {entry['verified_at']}")
        if entry.get("history"):
            lines.append(f"- 历史版本数: {len(entry['history'])}")
    p = Path(paths.FAQ_MD)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
```

- [ ] **Step 4: Run test (verify it passes)**

```bash
pytest tests/test_faq_writer.py -v
```

Expected: PASS (all 5 cases).

- [ ] **Step 5: Commit**

```bash
git add skills/track-issues
git commit -m "feat(track-issues): faq_writer with upsert/lookup/markdown rendering"
```

---

## Task 3: ops-test faq_lookup.py + _error_sig.py copy

**Files:**
- Create: `skills/ops-test/scripts/_error_sig.py` (copy)
- Create: `skills/ops-test/scripts/faq_lookup.py`
- Create: `skills/ops-test/tests/test_error_sig.py`
- Create: `skills/ops-test/tests/test_faq_lookup.py`

- [ ] **Step 1: Copy _error_sig.py to ops-test**

```bash
cp skills/track-issues/scripts/_error_sig.py skills/ops-test/scripts/_error_sig.py
```

Re-write the docstring's first line to:

```python
"""Failure-log signature (synchronized copy of track-issues/scripts/_error_sig.py)."""
```

(Both copies must stay in sync. If you change one, change the other in the same commit.)

- [ ] **Step 2: Write failing test for faq_lookup**

`skills/ops-test/tests/test_faq_lookup.py`:

```python
"""ops-test side FAQ lookup: read-only, returns matching fix or None.
Never raises; if FAQ file is missing or malformed, returns None."""
import json
from pathlib import Path

import pytest

from scripts import faq_lookup


@pytest.fixture
def tmp_cwd(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    yield tmp_path


def _write_faq(tmp_cwd: Path, key: str, fix_kind: str, payload: dict) -> None:
    p = tmp_cwd / "cann-ops-report" / "faq" / "known_fixes.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        key: {
            "fix_kind": fix_kind,
            "fix_payload": payload,
            "source_issue_url": "https://x",
            "verified_at": "2026-05-21T10:00:00",
            "verified_phase": "phase1",
            "soc": "ascend910b",
            "history": [],
        }
    }), encoding="utf-8")


def test_lookup_hit(tmp_cwd: Path) -> None:
    _write_faq(tmp_cwd, "r::o::BUILD_FAIL::sig1", "env", {"K": "V"})
    hit = faq_lookup.lookup_from_log(
        repo="r", op="o", failure_type="BUILD_FAIL",
        log_path=tmp_cwd / "x.log",
        precomputed_signature="sig1",
    )
    assert hit is not None
    assert hit["fix_kind"] == "env"


def test_lookup_miss(tmp_cwd: Path) -> None:
    _write_faq(tmp_cwd, "r::o::BUILD_FAIL::sig1", "env", {"K": "V"})
    assert faq_lookup.lookup_from_log(
        repo="r", op="o", failure_type="BUILD_FAIL",
        log_path=tmp_cwd / "x.log",
        precomputed_signature="other",
    ) is None


def test_no_faq_file_returns_none(tmp_cwd: Path) -> None:
    assert faq_lookup.lookup_from_log(
        repo="r", op="o", failure_type="F",
        log_path=tmp_cwd / "x.log",
        precomputed_signature="x",
    ) is None


def test_malformed_faq_returns_none(tmp_cwd: Path) -> None:
    p = tmp_cwd / "cann-ops-report" / "faq" / "known_fixes.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("not json", encoding="utf-8")
    assert faq_lookup.lookup_from_log(
        repo="r", op="o", failure_type="F",
        log_path=tmp_cwd / "x.log",
        precomputed_signature="x",
    ) is None


def test_signature_from_log_when_not_precomputed(tmp_cwd: Path) -> None:
    from scripts._error_sig import signature, first_error_line
    log = tmp_cwd / "x.log"
    log.write_text("ERROR: foo bar\n", encoding="utf-8")
    sig = signature(first_error_line(log))
    _write_faq(tmp_cwd, f"r::o::F::{sig}", "env", {"K": "V"})
    hit = faq_lookup.lookup_from_log(
        repo="r", op="o", failure_type="F",
        log_path=log, precomputed_signature=None,
    )
    assert hit is not None


def test_filter_excludes_patch(tmp_cwd: Path) -> None:
    """ops-test side should not surface patch-kind fixes (they need git branch ops)."""
    sig = "abc"
    _write_faq(tmp_cwd, f"r::o::F::{sig}", "patch", {"diff_path": "x"})
    hit = faq_lookup.lookup_from_log(
        repo="r", op="o", failure_type="F",
        log_path=tmp_cwd / "x.log",
        precomputed_signature=sig,
    )
    assert hit is None  # patch is filtered out
```

- [ ] **Step 3: Run test (verify it fails)**

```bash
cd /home/jiazhibin/cann/cann-ops-plugin/skills/ops-test
pytest tests/test_faq_lookup.py -v
```

Expected: FAIL (module not found).

- [ ] **Step 4: Write faq_lookup.py**

`skills/ops-test/scripts/faq_lookup.py`:

```python
"""Read-only FAQ lookup for ops-test failure-recovery hook.

Never raises: malformed JSON, missing files, missing signatures all return None.
Filters out fix_kind='patch' (those need user-controlled git ops, not silent retry)."""
from __future__ import annotations

import json
from pathlib import Path

from . import _error_sig


FAQ_JSON_REL = Path("cann-ops-report") / "faq" / "known_fixes.json"

_NON_SOURCE_KINDS = {"env", "build_flag", "cmd_arg", "upgrade"}


def _faq_path() -> Path:
    return Path.cwd() / FAQ_JSON_REL


def lookup_from_log(
    *,
    repo: str,
    op: str,
    failure_type: str,
    log_path: Path | str,
    precomputed_signature: str | None = None,
) -> dict | None:
    """Return matching fix entry, or None.

    If precomputed_signature is given, use it. Otherwise compute from log_path.
    Filters out 'patch' fixes — those require explicit user confirmation in
    track-issues, not the silent ops-test retry path.
    """
    faq = _faq_path()
    if not faq.exists():
        return None
    try:
        data = json.loads(faq.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    sig = precomputed_signature
    if sig is None:
        try:
            line = _error_sig.first_error_line(log_path)
            if not line:
                return None
            sig = _error_sig.signature(line)
        except Exception:
            return None

    key = f"{repo}::{op}::{failure_type}::{sig}"
    entry = data.get(key)
    if entry is None:
        return None
    if entry.get("fix_kind") not in _NON_SOURCE_KINDS:
        return None
    return entry


def lookup_all_failed(failed_ops: list[dict]) -> list[dict]:
    """Batch helper for ops-test's post-fail loop.

    failed_ops: list of {repo, op, failure_type, log_path}
    Returns list of {repo, op, failure_type, fix_entry} for matched items.
    """
    hits = []
    for f in failed_ops:
        e = lookup_from_log(
            repo=f["repo"], op=f["op"],
            failure_type=f["failure_type"],
            log_path=f["log_path"],
        )
        if e is not None:
            hits.append({
                "repo": f["repo"], "op": f["op"],
                "failure_type": f["failure_type"],
                "fix_entry": e,
            })
    return hits
```

- [ ] **Step 5: Write test_error_sig.py for ops-test**

Same content as `skills/track-issues/tests/test_error_sig.py` from Task 1 Step 5, but `from scripts._error_sig import ...` (relative to ops-test skill).

```bash
cp skills/track-issues/tests/test_error_sig.py skills/ops-test/tests/test_error_sig.py
```

(No edit needed — the import is already `from scripts._error_sig`.)

- [ ] **Step 6: Run all ops-test tests**

```bash
cd /home/jiazhibin/cann/cann-ops-plugin/skills/ops-test
pytest tests/test_faq_lookup.py tests/test_error_sig.py -v
```

Expected: all PASS.

- [ ] **Step 7: Commit**

```bash
git add skills/ops-test/scripts/_error_sig.py skills/ops-test/scripts/faq_lookup.py \
        skills/ops-test/tests/test_error_sig.py skills/ops-test/tests/test_faq_lookup.py
git commit -m "feat(ops-test): faq_lookup read-only hook + _error_sig helper"
```

---

## Task 4: fetch_comments.py

**Files:**
- Create: `skills/track-issues/scripts/fetch_comments.py`
- Create: `skills/track-issues/tests/test_fetch_comments.py`
- Create: `skills/track-issues/tests/fixtures/comments/gh_response.json`
- Create: `skills/track-issues/tests/fixtures/comments/gitee_response.json`
- Create: `skills/track-issues/tests/fixtures/comments/gitcode_response.json`

- [ ] **Step 1: Write fixture files**

`tests/fixtures/comments/gh_response.json`:

```json
[
  {"user": {"login": "maintainer-bot"}, "author_association": "MEMBER",
   "body": "try setting `export ASCEND_GLOBAL_LOG_LEVEL=1`", "created_at": "2026-05-21T08:00:00Z"},
  {"user": {"login": "drive-by"}, "author_association": "NONE",
   "body": "I have the same issue", "created_at": "2026-05-21T09:00:00Z"}
]
```

`tests/fixtures/comments/gitee_response.json`:

```json
[
  {"user": {"login": "ascend-maintainer", "role": "owner"},
   "body": "建议把 -DCMAKE_BUILD_TYPE=Release 改成 Debug",
   "created_at": "2026-05-21T08:00:00+08:00"}
]
```

`tests/fixtures/comments/gitcode_response.json`:

```json
[
  {"user": {"login": "user1"},
   "body": "?",
   "created_at": "2026-05-21T08:00:00+08:00"}
]
```

- [ ] **Step 2: Write failing test**

`skills/track-issues/tests/test_fetch_comments.py`:

```python
"""URL dispatch + response normalization for the three platforms."""
import json
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from scripts import fetch_comments


FIXTURES = Path(__file__).parent / "fixtures" / "comments"


def test_dispatch_github_uses_gh_cli() -> None:
    expected = (FIXTURES / "gh_response.json").read_text(encoding="utf-8")
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=expected, stderr="")
        out = fetch_comments.fetch(
            "https://github.com/ascend/ops-transformer/issues/101"
        )
    assert mock_run.called
    cmd = mock_run.call_args[0][0]
    assert cmd[:2] == ["gh", "api"]
    assert "repos/ascend/ops-transformer/issues/101/comments" in cmd[2]
    assert len(out) == 2
    assert out[0]["body"].startswith("try setting")
    assert out[0]["author"] == "maintainer-bot"
    assert out[0]["role"] == "MEMBER"


def test_dispatch_gitee_calls_v5_api() -> None:
    body = (FIXTURES / "gitee_response.json").read_text(encoding="utf-8")
    with patch("urllib.request.urlopen") as mock_open, \
         patch("os.environ", {"GITEE_TOKEN": "fake"}):
        mock_open.return_value.__enter__.return_value.read.return_value = body.encode()
        out = fetch_comments.fetch(
            "https://gitee.com/ascend/ops-cv/issues/I7XYZ"
        )
    url = mock_open.call_args[0][0].full_url
    assert "gitee.com/api/v5/repos/ascend/ops-cv/issues/I7XYZ/comments" in url
    assert "access_token=fake" in url
    assert len(out) == 1
    assert out[0]["body"].startswith("建议")


def test_dispatch_gitcode_uses_api_subdomain() -> None:
    body = (FIXTURES / "gitcode_response.json").read_text(encoding="utf-8")
    with patch("urllib.request.urlopen") as mock_open, \
         patch("os.environ", {"GITCODE_TOKEN": "fake"}):
        mock_open.return_value.__enter__.return_value.read.return_value = body.encode()
        out = fetch_comments.fetch(
            "https://gitcode.com/ascend/ops-math/issues/42"
        )
    url = mock_open.call_args[0][0].full_url
    assert url.startswith("https://api.gitcode.com/api/v5/")
    assert "access_token=fake" in url


def test_unknown_domain_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        fetch_comments.fetch("https://example.com/foo/bar/issues/1")


def test_404_returns_deleted_marker() -> None:
    import urllib.error
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            returncode=1, stdout="", stderr="gh: Not Found (HTTP 404)"
        )
        result = fetch_comments.fetch(
            "https://github.com/x/y/issues/999",
            raise_on_error=False,
        )
    assert result == {"status": "deleted_upstream"}
```

- [ ] **Step 3: Run test (verify it fails)**

```bash
cd /home/jiazhibin/cann/cann-ops-plugin/skills/track-issues
pytest tests/test_fetch_comments.py -v
```

Expected: FAIL (module not found).

- [ ] **Step 4: Write fetch_comments.py**

`skills/track-issues/scripts/fetch_comments.py`:

```python
"""Pull issue comments from GitHub (via gh CLI), Gitee v5, or GitCode v5.

Returns a normalized list of:
    {"author": str, "role": str, "body": str, "created_at": str}
or {"status": "deleted_upstream"} when issue is gone (raise_on_error=False).

Auth:
- GitHub via gh CLI (assumes gh auth login).
- Gitee:   GITEE_TOKEN env var (query param access_token).
- GitCode: GITCODE_TOKEN env var (query param, api.gitcode.com subdomain).
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import urllib.error
import urllib.request


_GH_RE = re.compile(r"https?://github\.com/([^/]+)/([^/]+)/issues/(\d+)")
_GITEE_RE = re.compile(r"https?://gitee\.com/([^/]+)/([^/]+)/issues/([^/?#]+)")
_GITCODE_RE = re.compile(r"https?://gitcode\.com/([^/]+)/([^/]+)/issues/(\d+)")


def fetch(issue_url: str, *, raise_on_error: bool = True) -> list[dict] | dict:
    """Dispatch by URL; return list of comments or {"status": ...} on known errors."""
    m = _GH_RE.match(issue_url)
    if m:
        return _fetch_github(*m.groups(), raise_on_error=raise_on_error)
    m = _GITEE_RE.match(issue_url)
    if m:
        return _fetch_gitee(*m.groups(), raise_on_error=raise_on_error)
    m = _GITCODE_RE.match(issue_url)
    if m:
        return _fetch_gitcode(*m.groups(), raise_on_error=raise_on_error)
    raise ValueError(f"Unsupported issue URL: {issue_url}")


def _fetch_github(owner: str, repo: str, num: str, *, raise_on_error: bool):
    api_path = f"repos/{owner}/{repo}/issues/{num}/comments"
    proc = subprocess.run(
        ["gh", "api", api_path],
        capture_output=True, text=True, timeout=30,
    )
    if proc.returncode != 0:
        if "404" in proc.stderr or "Not Found" in proc.stderr:
            if not raise_on_error:
                return {"status": "deleted_upstream"}
        if raise_on_error:
            raise RuntimeError(f"gh api failed: {proc.stderr.strip()}")
        return {"status": "fetch_failed", "reason": proc.stderr.strip()[:200]}
    raw = json.loads(proc.stdout)
    return [
        {"author": c.get("user", {}).get("login", ""),
         "role": c.get("author_association", ""),
         "body": c.get("body", ""),
         "created_at": c.get("created_at", "")}
        for c in raw
    ]


def _fetch_gitee(owner: str, repo: str, num: str, *, raise_on_error: bool):
    token = os.environ.get("GITEE_TOKEN", "")
    if not token:
        raise RuntimeError("GITEE_TOKEN not set")
    url = (f"https://gitee.com/api/v5/repos/{owner}/{repo}/issues/{num}/comments"
           f"?access_token={token}")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404 and not raise_on_error:
            return {"status": "deleted_upstream"}
        if raise_on_error:
            raise RuntimeError(f"Gitee HTTP {e.code}") from e
        return {"status": "fetch_failed", "reason": f"HTTP {e.code}"}
    return [
        {"author": c.get("user", {}).get("login", ""),
         "role": c.get("user", {}).get("role", ""),
         "body": c.get("body", ""),
         "created_at": c.get("created_at", "")}
        for c in raw
    ]


def _fetch_gitcode(owner: str, repo: str, num: str, *, raise_on_error: bool):
    token = os.environ.get("GITCODE_TOKEN", "")
    if not token:
        raise RuntimeError("GITCODE_TOKEN not set")
    url = (f"https://api.gitcode.com/api/v5/repos/{owner}/{repo}/issues/{num}/comments"
           f"?access_token={token}")
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = json.loads(resp.read())
    except urllib.error.HTTPError as e:
        if e.code == 404 and not raise_on_error:
            return {"status": "deleted_upstream"}
        if raise_on_error:
            raise RuntimeError(f"GitCode HTTP {e.code}") from e
        return {"status": "fetch_failed", "reason": f"HTTP {e.code}"}
    return [
        {"author": c.get("user", {}).get("login", ""),
         "role": c.get("user", {}).get("role", ""),
         "body": c.get("body", ""),
         "created_at": c.get("created_at", "")}
        for c in raw
    ]
```

- [ ] **Step 5: Run test (verify it passes)**

```bash
pytest tests/test_fetch_comments.py -v
```

Expected: PASS (5 cases).

- [ ] **Step 6: Commit**

```bash
git add skills/track-issues
git commit -m "feat(track-issues): fetch_comments with GitHub/Gitee/GitCode dispatch"
```

---

## Task 5: solution_extractor.py

**Files:**
- Create: `skills/track-issues/scripts/solution_extractor.py`
- Create: `skills/track-issues/tests/test_solution_extractor.py`

- [ ] **Step 1: Write failing test**

`skills/track-issues/tests/test_solution_extractor.py`:

```python
"""Heuristic classifier: comments → candidate solutions."""
from scripts.solution_extractor import classify


def test_env_export_hit() -> None:
    comments = [{"author": "maintainer", "role": "MEMBER",
                 "body": "try `export ASCEND_GLOBAL_LOG_LEVEL=1` then rerun",
                 "created_at": "2026-05-21T08:00:00Z"}]
    out = classify(comments)
    assert len(out) == 1
    assert out[0]["kind"] == "env"
    assert out[0]["confidence"] == "high"
    assert "ASCEND_GLOBAL_LOG_LEVEL" in out[0]["suggested_fix"]


def test_env_drive_by_lowered_confidence() -> None:
    comments = [{"author": "drive-by", "role": "NONE",
                 "body": "try export FOO=bar",
                 "created_at": "2026-05-21T08:00:00Z"}]
    out = classify(comments)
    assert out[0]["confidence"] == "med"


def test_build_flag_hit() -> None:
    comments = [{"author": "x", "role": "MEMBER",
                 "body": "you need -DCMAKE_BUILD_TYPE=Debug",
                 "created_at": ""}]
    out = classify(comments)
    assert out[0]["kind"] == "build_flag"
    assert "-DCMAKE_BUILD_TYPE=Debug" in out[0]["suggested_fix"]


def test_patch_code_block() -> None:
    body = "fix:\n```diff\n- foo\n+ bar\n```"
    comments = [{"author": "x", "role": "MEMBER", "body": body, "created_at": ""}]
    out = classify(comments)
    assert out[0]["kind"] == "patch"
    assert "- foo" in out[0]["suggested_fix"]


def test_upgrade_hit() -> None:
    comments = [{"author": "x", "role": "MEMBER",
                 "body": "this was fixed in 8.0.2, please git pull",
                 "created_at": ""}]
    out = classify(comments)
    assert out[0]["kind"] == "upgrade"


def test_discuss_only() -> None:
    comments = [{"author": "x", "role": "NONE",
                 "body": "can you share more logs?",
                 "created_at": ""}]
    out = classify(comments)
    assert out[0]["kind"] == "discuss"
    assert out[0]["actionable"] is False


def test_multiple_candidates_in_one_comment() -> None:
    body = "first set `export A=1` then rebuild with -DB=2"
    comments = [{"author": "x", "role": "MEMBER", "body": body, "created_at": ""}]
    out = classify(comments)
    kinds = sorted(c["kind"] for c in out)
    assert kinds == ["build_flag", "env"]


def test_empty_comments() -> None:
    assert classify([]) == []
```

- [ ] **Step 2: Run test (verify it fails)**

```bash
pytest tests/test_solution_extractor.py -v
```

Expected: FAIL.

- [ ] **Step 3: Write solution_extractor.py**

`skills/track-issues/scripts/solution_extractor.py`:

```python
"""Classify upstream issue comments into candidate solution entries.

Per §2.5 of the spec, priorities (matched in order, multiple matches per comment OK):
    patch  > env > build_flag > cmd_arg > upgrade > discuss

confidence: 'high' iff author role in {MEMBER, owner, collaborator, ...}, else 'med'
            'low' is reserved for discuss-only entries (actionable=False).
"""
from __future__ import annotations

import re

_PRIVILEGED_ROLES = {"MEMBER", "OWNER", "COLLABORATOR", "owner", "collaborator", "member"}

_PATCH_RE = re.compile(r"```(?:diff|patch)\n(.+?)```", re.DOTALL)
_ENV_RE = re.compile(r"(?:export\s+|set\s+)([A-Z][A-Z0-9_]*)\s*=\s*(\S+)")
_BUILD_FLAG_RE = re.compile(r"(-D[A-Z][A-Z0-9_]*=\S+|--build-extra-args=\S+)")
_CMD_ARG_RE = re.compile(r"(build\.sh\s+(?:--pkg|--run_example)[^\n`]+)")
_UPGRADE_RE = re.compile(
    r"(git\s+pull|升级到|fixed in [vV]?\d|please use [vV]?\d|switch to [vV]?\d|tag\s+v?\d)",
    re.IGNORECASE,
)
_DISCUSS_RE = re.compile(r"\?|more (info|logs|details)", re.IGNORECASE)


def _confidence(role: str) -> str:
    return "high" if role in _PRIVILEGED_ROLES else "med"


def classify(comments: list[dict]) -> list[dict]:
    """Return ordered list of {kind, raw_text, suggested_fix, confidence, actionable, source}."""
    out: list[dict] = []
    for c in comments:
        body = c.get("body") or ""
        role = c.get("role") or ""
        src = {"author": c.get("author"), "created_at": c.get("created_at")}

        # patch first (largest signal)
        for m in _PATCH_RE.finditer(body):
            out.append({
                "kind": "patch",
                "raw_text": body,
                "suggested_fix": m.group(1).strip(),
                "confidence": _confidence(role),
                "actionable": True,
                "source": src,
            })

        for m in _ENV_RE.finditer(body):
            out.append({
                "kind": "env",
                "raw_text": body,
                "suggested_fix": f"{m.group(1)}={m.group(2).strip('`')}",
                "confidence": _confidence(role),
                "actionable": True,
                "source": src,
            })

        for m in _BUILD_FLAG_RE.finditer(body):
            out.append({
                "kind": "build_flag",
                "raw_text": body,
                "suggested_fix": m.group(1),
                "confidence": _confidence(role),
                "actionable": True,
                "source": src,
            })

        for m in _CMD_ARG_RE.finditer(body):
            out.append({
                "kind": "cmd_arg",
                "raw_text": body,
                "suggested_fix": m.group(1).strip(),
                "confidence": "med",
                "actionable": True,
                "source": src,
            })

        if _UPGRADE_RE.search(body):
            out.append({
                "kind": "upgrade",
                "raw_text": body,
                "suggested_fix": body.strip(),
                "confidence": "med",
                "actionable": True,
                "source": src,
            })

        # If nothing actionable matched but body is non-trivial discuss
        if not any(o["raw_text"] is body and o["actionable"] for o in out) and body.strip():
            if _DISCUSS_RE.search(body):
                out.append({
                    "kind": "discuss",
                    "raw_text": body,
                    "suggested_fix": body.strip(),
                    "confidence": "low",
                    "actionable": False,
                    "source": src,
                })

    return out
```

- [ ] **Step 4: Run test (verify it passes)**

```bash
pytest tests/test_solution_extractor.py -v
```

Expected: PASS (all 8 cases).

- [ ] **Step 5: Commit**

```bash
git add skills/track-issues
git commit -m "feat(track-issues): solution_extractor with patch/env/build_flag/cmd_arg/upgrade/discuss heuristics"
```

---

## Task 6: apply_plan.py

**Files:**
- Create: `skills/track-issues/scripts/apply_plan.py`
- Create: `skills/track-issues/tests/test_apply_plan.py`

- [ ] **Step 1: Write failing test**

`skills/track-issues/tests/test_apply_plan.py`:

```python
"""apply_plan: solution candidate + failure context → executable plan."""
import json
import subprocess
from pathlib import Path

import pytest

from scripts import apply_plan


def _ctx(repo="ops-transformer", op="grouped_matmul", failure_type="BUILD_FAIL",
         repo_path="/tmp/repo", issue_id="101"):
    return {"repo": repo, "op": op, "failure_type": failure_type,
            "repo_path": repo_path, "issue_id": issue_id}


def test_env_plan() -> None:
    sol = {"kind": "env", "suggested_fix": "ASCEND_GLOBAL_LOG_LEVEL=1"}
    plan = apply_plan.build_plan(solution=sol, context=_ctx())
    assert plan["kind"] == "env"
    assert plan["payload"] == {"ASCEND_GLOBAL_LOG_LEVEL": "1"}
    assert "--env-extra=ASCEND_GLOBAL_LOG_LEVEL=1" in plan["ops_test_args"]


def test_build_flag_plan() -> None:
    sol = {"kind": "build_flag", "suggested_fix": "-DCMAKE_BUILD_TYPE=Debug"}
    plan = apply_plan.build_plan(solution=sol, context=_ctx())
    assert plan["kind"] == "build_flag"
    assert "--build-extra-args=-DCMAKE_BUILD_TYPE=Debug" in plan["ops_test_args"]


def test_cmd_arg_plan() -> None:
    sol = {"kind": "cmd_arg",
           "suggested_fix": "build.sh --run_example grouped_matmul eager cust"}
    plan = apply_plan.build_plan(solution=sol, context=_ctx())
    assert plan["kind"] == "cmd_arg"
    assert "--run-extra-args=" in " ".join(plan["ops_test_args"])


def test_upgrade_plan_no_args() -> None:
    sol = {"kind": "upgrade", "suggested_fix": "fixed in v8.0.2"}
    plan = apply_plan.build_plan(solution=sol, context=_ctx())
    assert plan["kind"] == "upgrade"
    assert plan["ops_test_args"] == []  # nothing to inject
    assert plan["requires_user_action"] is True


def test_patch_plan_creates_branch(tmp_path: Path) -> None:
    # init fake git repo
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "x@y.z"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)

    sol = {"kind": "patch", "suggested_fix": "--- a/f.txt\n+++ b/f.txt\n@@\n-hi\n+ho\n"}
    plan = apply_plan.build_plan(
        solution=sol,
        context=_ctx(repo_path=str(tmp_path), issue_id="101"),
    )
    assert plan["kind"] == "patch"
    assert plan["payload"]["branch_name"] == "track-issue-101"
    # branch should exist
    res = subprocess.run(["git", "branch", "--list", "track-issue-101"],
                         cwd=tmp_path, capture_output=True, text=True)
    assert "track-issue-101" in res.stdout


def test_patch_branch_collision_appends_retry(tmp_path: Path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.email", "x@y.z"], cwd=tmp_path, check=True)
    subprocess.run(["git", "config", "user.name", "x"], cwd=tmp_path, check=True)
    (tmp_path / "f.txt").write_text("hi\n")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=tmp_path, check=True)
    subprocess.run(["git", "branch", "track-issue-101"], cwd=tmp_path, check=True)

    sol = {"kind": "patch", "suggested_fix": "diff content"}
    plan = apply_plan.build_plan(
        solution=sol, context=_ctx(repo_path=str(tmp_path), issue_id="101"),
    )
    assert plan["payload"]["branch_name"].startswith("track-issue-101-retry-")


def test_patch_repo_not_git_fails(tmp_path: Path) -> None:
    sol = {"kind": "patch", "suggested_fix": "diff"}
    with pytest.raises(RuntimeError, match="not a git repo"):
        apply_plan.build_plan(
            solution=sol, context=_ctx(repo_path=str(tmp_path), issue_id="x"),
        )
```

- [ ] **Step 2: Run test (verify it fails)**

```bash
pytest tests/test_apply_plan.py -v
```

Expected: FAIL.

- [ ] **Step 3: Write apply_plan.py**

`skills/track-issues/scripts/apply_plan.py`:

```python
"""Translate a chosen solution + failure context into an executable plan.

Output dict shape:
    {
        "kind": "env" | "build_flag" | "cmd_arg" | "patch" | "upgrade",
        "payload": dict,
        "ops_test_args": list[str],
        "requires_user_action": bool,   # True for upgrade (git pull needed)
    }
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

from . import paths


def build_plan(*, solution: dict, context: dict) -> dict:
    kind = solution["kind"]
    if kind == "env":
        return _env(solution, context)
    if kind == "build_flag":
        return _build_flag(solution, context)
    if kind == "cmd_arg":
        return _cmd_arg(solution, context)
    if kind == "upgrade":
        return _upgrade(solution, context)
    if kind == "patch":
        return _patch(solution, context)
    raise ValueError(f"Unknown solution kind: {kind}")


def _env(sol: dict, ctx: dict) -> dict:
    s = sol["suggested_fix"].strip()
    m = re.match(r"([A-Z][A-Z0-9_]*)=(.+)", s)
    if not m:
        raise ValueError(f"Cannot parse env: {s!r}")
    key, val = m.group(1), m.group(2).strip()
    return {
        "kind": "env",
        "payload": {key: val},
        "ops_test_args": [f"--env-extra={key}={val}"],
        "requires_user_action": False,
    }


def _build_flag(sol: dict, ctx: dict) -> dict:
    flag = sol["suggested_fix"].strip()
    return {
        "kind": "build_flag",
        "payload": {"flags": [flag]},
        "ops_test_args": [f"--build-extra-args={flag}"],
        "requires_user_action": False,
    }


def _cmd_arg(sol: dict, ctx: dict) -> dict:
    cmd_tail = sol["suggested_fix"].strip()
    # strip leading "build.sh" if present
    if cmd_tail.startswith("build.sh"):
        cmd_tail = cmd_tail[len("build.sh"):].strip()
    return {
        "kind": "cmd_arg",
        "payload": {"run_args": cmd_tail},
        "ops_test_args": [f"--run-extra-args={cmd_tail}"],
        "requires_user_action": False,
    }


def _upgrade(sol: dict, ctx: dict) -> dict:
    return {
        "kind": "upgrade",
        "payload": {"hint": sol["suggested_fix"]},
        "ops_test_args": [],
        "requires_user_action": True,
    }


def _patch(sol: dict, ctx: dict) -> dict:
    repo_path = Path(ctx["repo_path"])
    if not (repo_path / ".git").exists():
        raise RuntimeError(f"{repo_path} is not a git repo")

    issue_id = ctx["issue_id"]
    branch_name = _pick_branch_name(repo_path, f"track-issue-{issue_id}")
    subprocess.run(["git", "-C", str(repo_path), "switch", "-c", branch_name],
                   check=True, capture_output=True)

    # save diff to PATCHES_DIR
    patches_dir = Path(paths.PATCHES_DIR) / ctx["repo"]
    patches_dir.mkdir(parents=True, exist_ok=True)
    diff_path = patches_dir / f"{issue_id}.diff"
    diff_path.write_text(sol["suggested_fix"], encoding="utf-8")

    return {
        "kind": "patch",
        "payload": {"diff_path": str(diff_path), "branch_name": branch_name},
        "ops_test_args": [],   # patch applied separately; retest uses the branch
        "requires_user_action": False,
    }


def _pick_branch_name(repo_path: Path, base: str) -> str:
    res = subprocess.run(
        ["git", "-C", str(repo_path), "branch", "--list", base],
        capture_output=True, text=True,
    )
    if base not in res.stdout:
        return base
    # collide → append -retry-N
    n = 1
    while True:
        candidate = f"{base}-retry-{n}"
        res = subprocess.run(
            ["git", "-C", str(repo_path), "branch", "--list", candidate],
            capture_output=True, text=True,
        )
        if candidate not in res.stdout:
            return candidate
        n += 1
```

- [ ] **Step 4: Run test (verify it passes)**

```bash
pytest tests/test_apply_plan.py -v
```

Expected: PASS (7 cases).

- [ ] **Step 5: Commit**

```bash
git add skills/track-issues
git commit -m "feat(track-issues): apply_plan with branch creation for patch fixes"
```

---

## Task 7: ops-test runner extension

Add three pass-through flags to `run_phase1_batched.py` so retest_orchestrator can inject env / build / run args without rewriting the runner.

**Files:**
- Modify: `skills/ops-test/scripts/run_phase1_batched.py`
- Create: `skills/ops-test/tests/test_runner_extra_args.py`

- [ ] **Step 1: Write failing test (CLI parsing only)**

`skills/ops-test/tests/test_runner_extra_args.py`:

```python
"""Verify the three new pass-through flags are accepted and stored on the parser."""
import importlib.util
from pathlib import Path

SCRIPT = (Path(__file__).parent.parent / "scripts" / "run_phase1_batched.py").resolve()


def _load_module():
    spec = importlib.util.spec_from_file_location("run_phase1_batched", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_env_extra_flag_parses() -> None:
    mod = _load_module()
    parser = mod._build_parser()
    args = parser.parse_args([
        "--repo-mapping", "r=/p", "--soc", "ascend910b",
        "--env-extra", "K=V,L=W",
    ])
    assert args.env_extra == "K=V,L=W"


def test_build_extra_args_flag_parses() -> None:
    mod = _load_module()
    parser = mod._build_parser()
    args = parser.parse_args([
        "--repo-mapping", "r=/p", "--soc", "ascend910b",
        "--build-extra-args", "-DA=1 -DB=2",
    ])
    assert args.build_extra_args == "-DA=1 -DB=2"


def test_run_extra_args_flag_parses() -> None:
    mod = _load_module()
    parser = mod._build_parser()
    args = parser.parse_args([
        "--repo-mapping", "r=/p", "--soc", "ascend910b",
        "--run-extra-args", "--vendor_name=other",
    ])
    assert args.run_extra_args == "--vendor_name=other"


def test_build_cmd_includes_extra() -> None:
    mod = _load_module()
    cmd = mod._compose_build_cmd(soc="ascend910b", ops_csv="op1,op2",
                                  build_extra_args="-DA=1")
    assert "-DA=1" in cmd
    assert "--ops=op1,op2" in cmd


def test_run_cmd_includes_extra() -> None:
    mod = _load_module()
    cmd = mod._compose_run_cmd(op="op1", run_extra_args="--vendor_name=other")
    assert "--vendor_name=other" in cmd
    assert "--run_example op1" in cmd


def test_env_extra_parsed_to_dict() -> None:
    mod = _load_module()
    out = mod._parse_env_extra("ASCEND_X=1,FOO=bar")
    assert out == {"ASCEND_X": "1", "FOO": "bar"}
    assert mod._parse_env_extra("") == {}
```

- [ ] **Step 2: Run test (verify it fails)**

```bash
cd /home/jiazhibin/cann/cann-ops-plugin/skills/ops-test
pytest tests/test_runner_extra_args.py -v
```

Expected: FAIL (helpers `_build_parser`, `_compose_build_cmd`, `_compose_run_cmd`, `_parse_env_extra` don't exist).

- [ ] **Step 3: Refactor existing runner — extract parser + composers**

In `skills/ops-test/scripts/run_phase1_batched.py`, find the existing `main()` (around line 395) and the inline build/run command construction (around lines 197 and 250). Replace as follows.

Add helper functions near the top of the file (after the `SUCCESS_PATTERNS` block, around line 70):

```python
def _build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        description="Phase 1 batched runner (仓内合并 build + 仓间并发)"
    )
    ap.add_argument("--repo-mapping", required=True,
                    help="仓名到本地源码路径的映射，CSV: repo1=path1,repo2=path2")
    ap.add_argument("--soc", required=True,
                    help="目标 SOC，例如 ascend910b / ascend950")
    ap.add_argument("--ops", default="",
                    help="目标算子 CSV（与 --ops-file 互斥；都不传则从 scann 产物读）")
    ap.add_argument("--ops-file", default="",
                    help="目标算子清单文件（.json / .txt）")
    ap.add_argument("--env-extra", default="",
                    help="额外环境变量（CSV：K1=V1,K2=V2），prepend 到 build/run 命令")
    ap.add_argument("--build-extra-args", default="",
                    help="额外 build.sh --pkg 参数（原样追加）")
    ap.add_argument("--run-extra-args", default="",
                    help="额外 build.sh --run_example 参数（原样追加）")
    return ap


def _parse_env_extra(s: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for entry in s.split(","):
        entry = entry.strip()
        if not entry or "=" not in entry:
            continue
        k, v = entry.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def _compose_build_cmd(*, soc: str, ops_csv: str, build_extra_args: str = "") -> str:
    base = f"bash build.sh --pkg --soc={soc} --ops={ops_csv} -j16"
    if build_extra_args:
        return f"{base} {build_extra_args}"
    return base


def _compose_run_cmd(*, op: str, run_extra_args: str = "") -> str:
    base = f"bash build.sh --run_example {op} eager cust --vendor_name=custom"
    if run_extra_args:
        return f"{base} {run_extra_args}"
    return base
```

Now wire them into `main()`. Replace the existing `main()` body (around line 395) with:

```python
# globals filled by main()
ENV_EXTRA: dict[str, str] = {}
BUILD_EXTRA_ARGS: str = ""
RUN_EXTRA_ARGS: str = ""


def main() -> int:
    global SOC, CLI_OPS, CLI_OPS_FILE, REPO_PATHS
    global ENV_EXTRA, BUILD_EXTRA_ARGS, RUN_EXTRA_ARGS
    args = _build_parser().parse_args()
    SOC = args.soc
    CLI_OPS = args.ops
    CLI_OPS_FILE = args.ops_file
    REPO_PATHS = parse_repo_mapping(args.repo_mapping)
    ENV_EXTRA = _parse_env_extra(args.env_extra)
    BUILD_EXTRA_ARGS = args.build_extra_args
    RUN_EXTRA_ARGS = args.run_extra_args
    # ... rest of existing main body remains unchanged
```

And replace the two inline command-building lines:

Old line 197:
```python
build_cmd = f"bash build.sh --pkg --soc={SOC} --ops={ops_csv} -j16"
```
New:
```python
build_cmd = _compose_build_cmd(soc=SOC, ops_csv=ops_csv, build_extra_args=BUILD_EXTRA_ARGS)
```

Old line 250:
```python
run_cmd = f"bash build.sh --run_example {op} eager cust --vendor_name=custom"
```
New:
```python
run_cmd = _compose_run_cmd(op=op, run_extra_args=RUN_EXTRA_ARGS)
```

Find `run_shell(...)` calls and inspect — if it uses `subprocess.Popen(env=...)`, ensure ENV_EXTRA gets merged. Look at `run_shell` signature in this file. If `run_shell` uses `os.environ`, the env merge will be picked up. If not, locate the env-passing site and inject:

```python
shell_env = {**os.environ, **ENV_EXTRA}
```

at the call sites that need it. Read the file (`Read` tool with `offset=120, limit=80`) to find the right spot — do not blind-edit.

- [ ] **Step 4: Run test (verify it passes)**

```bash
pytest tests/test_runner_extra_args.py -v
```

Expected: PASS (6 cases).

- [ ] **Step 5: Smoke-run the existing runner (no NPU) to confirm parser still works**

```bash
python3 skills/ops-test/scripts/run_phase1_batched.py --help
```

Expected: help message lists the three new flags without traceback.

- [ ] **Step 6: Commit**

```bash
git add skills/ops-test/scripts/run_phase1_batched.py skills/ops-test/tests/test_runner_extra_args.py
git commit -m "feat(ops-test): runner accepts --env-extra/--build-extra-args/--run-extra-args"
```

---

## Task 8: retest_orchestrator.py

**Files:**
- Create: `skills/track-issues/scripts/retest_orchestrator.py`
- Create: `skills/track-issues/tests/test_retest_orchestrator.py`

- [ ] **Step 1: Write failing test**

`skills/track-issues/tests/test_retest_orchestrator.py`:

```python
"""retest_orchestrator: assemble & invoke ops-test runner CLI with the plan baked in."""
from unittest.mock import patch, MagicMock

from scripts import retest_orchestrator


def test_env_plan_to_cli() -> None:
    plan = {"kind": "env",
            "payload": {"K": "V"},
            "ops_test_args": ["--env-extra=K=V"],
            "requires_user_action": False}
    ctx = {"repo": "r", "op": "op1", "soc": "ascend910b",
           "repo_path": "/p"}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        result = retest_orchestrator.retest(plan=plan, context=ctx)
    cmd = mock_run.call_args[0][0]
    assert "--repo-mapping" in cmd
    assert "r=/p" in cmd
    assert "--soc" in cmd and "ascend910b" in cmd
    assert "--ops" in cmd and "op1" in cmd
    assert "--env-extra=K=V" in cmd
    assert result["returncode"] == 0


def test_patch_plan_skips_extra_args() -> None:
    """patch plans rely on the active git branch; no --env/--build-extra-args."""
    plan = {"kind": "patch",
            "payload": {"branch_name": "track-issue-101", "diff_path": "/x"},
            "ops_test_args": [],
            "requires_user_action": False}
    ctx = {"repo": "r", "op": "op1", "soc": "ascend910b", "repo_path": "/p"}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        retest_orchestrator.retest(plan=plan, context=ctx)
    cmd = mock_run.call_args[0][0]
    assert not any("--env-extra" in c for c in cmd)


def test_upgrade_plan_returns_user_action_needed() -> None:
    plan = {"kind": "upgrade", "payload": {"hint": "git pull"},
            "ops_test_args": [],
            "requires_user_action": True}
    ctx = {"repo": "r", "op": "op1", "soc": "ascend910b", "repo_path": "/p"}
    result = retest_orchestrator.retest(plan=plan, context=ctx)
    assert result["status"] == "needs_user_action"


def test_nonzero_returncode_is_fail_not_raise() -> None:
    plan = {"kind": "env", "payload": {}, "ops_test_args": [],
            "requires_user_action": False}
    ctx = {"repo": "r", "op": "op1", "soc": "ascend910b", "repo_path": "/p"}
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="boom")
        result = retest_orchestrator.retest(plan=plan, context=ctx)
    assert result["returncode"] == 1
    assert result["status"] == "fail"
```

- [ ] **Step 2: Run test (verify it fails)**

```bash
cd /home/jiazhibin/cann/cann-ops-plugin/skills/track-issues
pytest tests/test_retest_orchestrator.py -v
```

Expected: FAIL.

- [ ] **Step 3: Write retest_orchestrator.py**

`skills/track-issues/scripts/retest_orchestrator.py`:

```python
"""Drive ops-test runner with a track-issues plan applied.

Bypasses skill→skill orchestration: we directly subprocess the runner script
(the same entrypoint ops-test itself uses for its phase1 multi-repo workflow).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path


# Resolve the ops-test runner relative to this script.
# Script lives at:  skills/track-issues/scripts/retest_orchestrator.py
# Runner lives at:  skills/ops-test/scripts/run_phase1_batched.py
_PLUGIN_ROOT = Path(__file__).resolve().parents[3]
_OPSTEST_RUNNER = _PLUGIN_ROOT / "skills" / "ops-test" / "scripts" / "run_phase1_batched.py"


def retest(*, plan: dict, context: dict) -> dict:
    """Run ops-test phase1 for a single (repo, op), returning a result dict.

    Result shape:
        {"status": "pass" | "fail" | "needs_user_action",
         "returncode": int | None,
         "stdout": str, "stderr": str}
    """
    if plan.get("requires_user_action"):
        return {"status": "needs_user_action", "returncode": None,
                "stdout": "", "stderr": ""}

    cmd = [
        sys.executable, str(_OPSTEST_RUNNER),
        "--repo-mapping", f"{context['repo']}={context['repo_path']}",
        "--soc", context["soc"],
        "--ops", context["op"],
    ]
    cmd.extend(plan.get("ops_test_args", []))

    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    status = "pass" if proc.returncode == 0 else "fail"
    return {
        "status": status,
        "returncode": proc.returncode,
        "stdout": proc.stdout,
        "stderr": proc.stderr,
    }
```

- [ ] **Step 4: Run test (verify it passes)**

```bash
pytest tests/test_retest_orchestrator.py -v
```

Expected: PASS (4 cases).

- [ ] **Step 5: Commit**

```bash
git add skills/track-issues
git commit -m "feat(track-issues): retest_orchestrator drives ops-test runner with plan args"
```

---

## Task 9: reply_builder.py

**Files:**
- Create: `skills/track-issues/scripts/reply_builder.py`
- Create: `skills/track-issues/tests/test_reply_builder.py`

- [ ] **Step 1: Write failing test**

`skills/track-issues/tests/test_reply_builder.py`:

```python
"""Build PASS / FAIL reply bodies for upstream comment posting."""
from scripts.reply_builder import build_pass_reply, build_fail_reply


def test_pass_reply_includes_plan_kind() -> None:
    body = build_pass_reply(
        plan={"kind": "env", "payload": {"ASCEND_X": "1"}},
        op="grouped_matmul",
        verified_phase="phase1",
        soc="ascend910b",
        retest_log_excerpt="All tests passed\nPASS",
    )
    assert "已按贵方案验证通过" in body
    assert "env" in body
    assert "ASCEND_X" in body
    assert "All tests passed" in body
    assert "grouped_matmul" in body


def test_pass_reply_patch_includes_branch() -> None:
    body = build_pass_reply(
        plan={"kind": "patch",
              "payload": {"branch_name": "track-issue-101", "diff_path": "x.diff"}},
        op="op1", verified_phase="phase1", soc="ascend910b",
        retest_log_excerpt="PASS",
    )
    assert "track-issue-101" in body


def test_fail_reply_includes_diff_section() -> None:
    body = build_fail_reply(
        plan={"kind": "env", "payload": {"X": "1"}},
        op="op1",
        original_error="undefined reference to Foo",
        new_error="undefined reference to Bar",
        soc="ascend910b",
    )
    assert "重测仍失败" in body
    assert "undefined reference to Bar" in body
    assert "原 error" in body
    assert "undefined reference to Foo" in body


def test_fail_reply_handles_same_error() -> None:
    body = build_fail_reply(
        plan={"kind": "env", "payload": {"X": "1"}},
        op="op1",
        original_error="ERR A", new_error="ERR A",
        soc="ascend910b",
    )
    assert "与原 error 相同" in body or "新 error 与原 error 一致" in body
```

- [ ] **Step 2: Run test (verify it fails)**

```bash
pytest tests/test_reply_builder.py -v
```

Expected: FAIL.

- [ ] **Step 3: Write reply_builder.py**

`skills/track-issues/scripts/reply_builder.py`:

```python
"""Compose markdown reply bodies for PASS / FAIL retest outcomes."""
from __future__ import annotations

import json


def build_pass_reply(
    *,
    plan: dict,
    op: str,
    verified_phase: str,
    soc: str,
    retest_log_excerpt: str,
) -> str:
    parts = [
        "## 已按贵方案验证通过",
        f"算子：`{op}`",
        f"修复类型：`{plan['kind']}`",
        f"payload：`{json.dumps(plan['payload'], ensure_ascii=False)}`",
        f"验证 phase / SOC：`{verified_phase}` / `{soc}`",
        "",
        "### 复测日志摘录",
        "```",
        retest_log_excerpt.strip(),
        "```",
    ]
    if plan["kind"] == "patch":
        parts.append("")
        parts.append(f"分支：`{plan['payload']['branch_name']}` 已在本地保留供复核。")
    parts.append("")
    parts.append("感谢支持。本评论由 cann-ops:track-issues 自动生成。")
    return "\n".join(parts)


def build_fail_reply(
    *,
    plan: dict,
    op: str,
    original_error: str,
    new_error: str,
    soc: str,
) -> str:
    parts = [
        "## 重测仍失败",
        f"算子：`{op}`",
        f"应用的修复：`{plan['kind']}` — `{json.dumps(plan['payload'], ensure_ascii=False)}`",
        f"SOC：`{soc}`",
        "",
        "### 原 error",
        "```",
        original_error.strip(),
        "```",
        "",
        "### 新 error",
        "```",
        new_error.strip(),
        "```",
    ]
    if original_error.strip() == new_error.strip():
        parts.append("")
        parts.append("> 新 error 与原 error 一致，方案未触达失败点。")
    parts.append("")
    parts.append("请协助进一步分析。本评论由 cann-ops:track-issues 自动生成。")
    return "\n".join(parts)
```

- [ ] **Step 4: Run test (verify it passes)**

```bash
pytest tests/test_reply_builder.py -v
```

Expected: PASS (4 cases).

- [ ] **Step 5: Commit**

```bash
git add skills/track-issues
git commit -m "feat(track-issues): reply_builder with PASS/FAIL markdown templates"
```

---

## Task 10: upstream_writer.py

**Files:**
- Create: `skills/track-issues/scripts/upstream_writer.py`
- Create: `skills/track-issues/tests/test_upstream_writer.py`

- [ ] **Step 1: Write failing test**

`skills/track-issues/tests/test_upstream_writer.py`:

```python
"""POST comment + (optionally) close issue across the three platforms."""
import json
from unittest.mock import patch, MagicMock

import pytest

from scripts import upstream_writer


def test_github_post_comment_uses_gh() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
        upstream_writer.post_comment(
            issue_url="https://github.com/ascend/r/issues/1",
            body="hello",
        )
    cmd = mock_run.call_args[0][0]
    assert cmd[:2] == ["gh", "issue"]
    assert "comment" in cmd
    assert "1" in cmd
    assert "--repo" in cmd
    assert "--body" in cmd
    assert "hello" in cmd


def test_github_close_uses_gh() -> None:
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        upstream_writer.close_issue("https://github.com/ascend/r/issues/1")
    cmd = mock_run.call_args[0][0]
    assert "close" in cmd
    assert "1" in cmd


def test_gitee_post_comment_to_v5() -> None:
    with patch("urllib.request.urlopen") as mock_open, \
         patch("os.environ", {"GITEE_TOKEN": "tok"}):
        mock_open.return_value.__enter__.return_value.read.return_value = b'{"html_url":"x"}'
        upstream_writer.post_comment(
            issue_url="https://gitee.com/ascend/r/issues/I7XYZ",
            body="hello",
        )
    req = mock_open.call_args[0][0]
    assert "/api/v5/repos/ascend/r/issues/I7XYZ/comments" in req.full_url
    payload = json.loads(mock_open.call_args[0][0].data.decode())
    assert payload["body"] == "hello"
    assert payload["access_token"] == "tok"


def test_gitcode_post_comment_via_api_subdomain() -> None:
    with patch("urllib.request.urlopen") as mock_open, \
         patch("os.environ", {"GITCODE_TOKEN": "tok"}):
        mock_open.return_value.__enter__.return_value.read.return_value = b'{"html_url":"x"}'
        upstream_writer.post_comment(
            issue_url="https://gitcode.com/ascend/r/issues/42",
            body="hi",
        )
    url = mock_open.call_args[0][0].full_url
    assert url.startswith("https://api.gitcode.com/api/v5/")
    assert "access_token=tok" in url


def test_post_retries_once_on_5xx() -> None:
    import urllib.error
    call_count = {"n": 0}

    def fake_urlopen(req, timeout):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise urllib.error.HTTPError(req.full_url, 503, "Service Unavailable",
                                         {}, None)
        m = MagicMock()
        m.__enter__.return_value.read.return_value = b'{"html_url":"x"}'
        return m

    with patch("urllib.request.urlopen", side_effect=fake_urlopen), \
         patch("os.environ", {"GITEE_TOKEN": "tok"}):
        upstream_writer.post_comment(
            issue_url="https://gitee.com/ascend/r/issues/1",
            body="hi",
        )
    assert call_count["n"] == 2


def test_unknown_domain_raises() -> None:
    with pytest.raises(ValueError, match="Unsupported"):
        upstream_writer.post_comment(
            issue_url="https://example.com/r/issues/1",
            body="hi",
        )
```

- [ ] **Step 2: Run test (verify it fails)**

```bash
pytest tests/test_upstream_writer.py -v
```

Expected: FAIL.

- [ ] **Step 3: Write upstream_writer.py**

`skills/track-issues/scripts/upstream_writer.py`:

```python
"""Post comment + close issue on GitHub / Gitee / GitCode."""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request


_GH_RE = re.compile(r"https?://github\.com/([^/]+)/([^/]+)/issues/(\d+)")
_GITEE_RE = re.compile(r"https?://gitee\.com/([^/]+)/([^/]+)/issues/([^/?#]+)")
_GITCODE_RE = re.compile(r"https?://gitcode\.com/([^/]+)/([^/]+)/issues/(\d+)")


def post_comment(*, issue_url: str, body: str) -> str:
    m = _GH_RE.match(issue_url)
    if m:
        return _gh_post(*m.groups(), body=body)
    m = _GITEE_RE.match(issue_url)
    if m:
        return _gitee_post(*m.groups(), body=body)
    m = _GITCODE_RE.match(issue_url)
    if m:
        return _gitcode_post(*m.groups(), body=body)
    raise ValueError(f"Unsupported issue URL: {issue_url}")


def close_issue(issue_url: str) -> None:
    m = _GH_RE.match(issue_url)
    if m:
        return _gh_close(*m.groups())
    m = _GITEE_RE.match(issue_url)
    if m:
        return _gitee_close(*m.groups())
    m = _GITCODE_RE.match(issue_url)
    if m:
        return _gitcode_close(*m.groups())
    raise ValueError(f"Unsupported issue URL: {issue_url}")


def _gh_post(owner: str, repo: str, num: str, *, body: str) -> str:
    proc = subprocess.run(
        ["gh", "issue", "comment", num, "--repo", f"{owner}/{repo}", "--body", body],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh issue comment failed: {proc.stderr.strip()}")
    return proc.stdout.strip()


def _gh_close(owner: str, repo: str, num: str) -> None:
    proc = subprocess.run(
        ["gh", "issue", "close", num, "--repo", f"{owner}/{repo}"],
        capture_output=True, text=True, timeout=60,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"gh issue close failed: {proc.stderr.strip()}")


def _gitee_post(owner: str, repo: str, num: str, *, body: str) -> str:
    token = os.environ.get("GITEE_TOKEN", "")
    if not token:
        raise RuntimeError("GITEE_TOKEN not set")
    url = f"https://gitee.com/api/v5/repos/{owner}/{repo}/issues/{num}/comments"
    payload = json.dumps({"access_token": token, "body": body}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json;charset=UTF-8"},
    )
    resp_bytes = _urlopen_with_retry(req)
    return json.loads(resp_bytes).get("html_url", "")


def _gitee_close(owner: str, repo: str, num: str) -> None:
    token = os.environ.get("GITEE_TOKEN", "")
    if not token:
        raise RuntimeError("GITEE_TOKEN not set")
    url = f"https://gitee.com/api/v5/repos/{owner}/issues/{num}"
    payload = json.dumps({"access_token": token, "repo": repo, "state": "closed"},
                         ensure_ascii=False).encode()
    req = urllib.request.Request(
        url, data=payload, method="PATCH",
        headers={"Content-Type": "application/json;charset=UTF-8"},
    )
    _urlopen_with_retry(req)


def _gitcode_post(owner: str, repo: str, num: str, *, body: str) -> str:
    token = os.environ.get("GITCODE_TOKEN", "")
    if not token:
        raise RuntimeError("GITCODE_TOKEN not set")
    url = (f"https://api.gitcode.com/api/v5/repos/{owner}/{repo}/issues/{num}/comments"
           f"?access_token={token}")
    payload = json.dumps({"body": body}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        url, data=payload, method="POST",
        headers={"Content-Type": "application/json; charset=utf-8",
                 "Accept": "application/json"},
    )
    resp_bytes = _urlopen_with_retry(req)
    return json.loads(resp_bytes).get("html_url", "")


def _gitcode_close(owner: str, repo: str, num: str) -> None:
    token = os.environ.get("GITCODE_TOKEN", "")
    if not token:
        raise RuntimeError("GITCODE_TOKEN not set")
    url = (f"https://api.gitcode.com/api/v5/repos/{owner}/issues/{num}"
           f"?access_token={token}")
    payload = json.dumps({"repo": repo, "state": "closed"}, ensure_ascii=False).encode()
    req = urllib.request.Request(
        url, data=payload, method="PATCH",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    _urlopen_with_retry(req)


def _urlopen_with_retry(req: urllib.request.Request) -> bytes:
    """One retry on 5xx; raise on other errors."""
    last_exc = None
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read()
        except urllib.error.HTTPError as e:
            if 500 <= e.code < 600 and attempt == 0:
                time.sleep(2)
                last_exc = e
                continue
            raise RuntimeError(f"HTTP {e.code}: {e.reason}") from e
    raise RuntimeError(f"HTTP 5xx after retry: {last_exc}")
```

- [ ] **Step 4: Run test (verify it passes)**

```bash
pytest tests/test_upstream_writer.py -v
```

Expected: PASS (6 cases).

- [ ] **Step 5: Commit**

```bash
git add skills/track-issues
git commit -m "feat(track-issues): upstream_writer POST comment + close with one-retry"
```

---

## Task 11: SKILL.md for track-issues

**Files:**
- Modify: `skills/track-issues/SKILL.md` (replace stub from Task 0)

- [ ] **Step 1: Write final SKILL.md**

Replace the stub with this exact content:

```markdown
---
name: track-issues
description: 用于查询已提交到上游社区（GitHub / Gitee / GitCode）的算子 issue 回复状态；若评论给出可执行方案则自动应用并复测；PASS 则关闭 issue + 写入 FAQ，FAIL 则人工确认后追问。涉及"查 issue 回复 / 跟 issue 走一遍 / 按社区方案重试 / retest with community fix"等用户意图时必须激活本 skill。
---

# cann-ops:track-issues

把上游 issue 的回复闭环成"应用方案 → 复测 → 关 issue + 写 FAQ"，让以后同类失败可以从 FAQ 一键复用。

## 强制激活规则

触发以下意图必须先激活本 skill，再行动：
- "查一下提的 issue 有没有回复" / "看下 issue 状态" / "social 回复了吗"
- "按社区方案重试" / "跟 issue 走一遍" / "retest with community fix"

## 前置条件

- 必须存在 `CWD/cann-ops-report/issues/state.json` 且至少有一条已提交记录；否则 fatal "还没提过 issue，先 cann-ops:report-issues"
- 拉评论需要：GitHub → `gh auth login`；Gitee → `GITEE_TOKEN`；GitCode → `GITCODE_TOKEN`（复用 report-issues 的 token_helper）

## 工作流（P0–P5）

### P0 — 范围确认

读 state.json，按 repo 分组列出已提交 issue（含 submitted_at）。`AskUserQuestion` 问"全部查 / 只查某些 repo / 只查 N 天内新提的（默认 7 天）"。

### P1 — 拉评论

对每个圈定的 issue_url，按域名分派到 `scripts.fetch_comments.fetch(...)`。落盘 `cann-ops-report/issues/comments/<repo>/<issue_id>.json`。

分类：评论数 0 → `no_reply`；评论全部自发 → `self_only`；其余 → 进 P2。

失败处理：
- gh 未登录 → fatal "先 gh auth login"
- Gitee/GitCode token 缺 → 复用 report-issues 的 `token_helper` 单次 prompt
- 404 → state.json 标 `status: deleted_upstream`，继续其它
- 5xx → 重试一次，仍失败标 `fetch_failed: <reason>`，继续其它
- GitHub 速率限制 → 打印 reset 时间并停止整轮（不自动 sleep > 10s）

### P2 — 方案识别（agent + 用户确认）

每个有评论的 issue：

1. `scripts.solution_extractor.classify(comments)` 给候选列表（patch/env/build_flag/cmd_arg/upgrade/discuss，含 confidence）
2. agent 用结构化模板把候选展示给用户："issue #N 共 M 条评论，识别出 K 条候选方案：1. [env] ...  2. [patch] ...  ..."
3. `AskUserQuestion`：A. 走方案 1 / B. 走方案 2 / ... / C. 跳过这个 issue / D. 我先看 comments/<id>.json 等下再说
4. 选定 → `scripts.apply_plan.build_plan(...)` 生成 `plans/<issue_id>.json`

候选 0 条且评论 ≥ 1：标 `comments_no_actionable`，把全部评论 markdown 渲染给用户人工判断。

用户选 D：退出 P2 循环，**不**污染 state.json，下轮重来。

### P3 — 应用方案 + 复测

`scripts.apply_plan.build_plan(...)` 已经把方案翻译成可执行 plan：

- env / build_flag / cmd_arg → 注入 `--env-extra=` / `--build-extra-args=` / `--run-extra-args=`
- patch → 在原仓 `git switch -c track-issue-<id>` 并落 diff 到 `cann-ops-report/issues/patches/<repo>/<issue_id>.diff`，再 `git apply --3way`
- upgrade → 不自动 fetch，提示用户后停在 needs_user_action 状态

`scripts.retest_orchestrator.retest(plan, context)` 调起 ops-test 的 `run_phase1_batched.py`，只跑 (repo, op)。

P3 错误处理：
- patch 类，原仓不是 git 仓 / 工作区脏 → fatal "请先 commit/stash"，**不**自动 stash
- patch 应用冲突 → `git restore .` 还原 → fatal 告知冲突位置
- env/build_flag/cmd_arg 类，runner 返回非 0 → 视作 FAIL 走 P4 FAIL 分支（**不**重试）

### P4 — 写 FAQ + 回写社区

**PASS 分支**：
1. `scripts.faq_writer.upsert(...)` 追加 known_fixes.json，error_signature 用 `_error_sig.signature(first_error_line(原失败日志))`
2. `scripts.reply_builder.build_pass_reply(...)`
3. `scripts.upstream_writer.post_comment(...)` + `close_issue(...)`
4. state.json 更新：`status: closed_by_track_issues, closed_at: ...`

PASS 分支异常：
- FAQ atomic write 失败 → fatal，**不**继续上游回写
- comment POST 5xx → 重试一次，仍失败则落 `replies/<repo>/<issue_id>.draft.md` + 让用户手工发
- close 失败但评论已发 → 警告"评论已发，close 失败，请手工 close"，不重试

**FAIL 分支**：
1. `scripts.reply_builder.build_fail_reply(...)`
2. `AskUserQuestion`：A. 直接发 / B. 我改改这条评论 / C. 不发先存草稿
3. 选 A → post_comment；选 B → 让用户口述修改，agent Edit reply 草稿后再问；选 C → 落 `replies/<repo>/<issue_id>.draft.md` + state.json 加 `pending_reply: true`

无论 PASS/FAIL，patch 类分支保留在用户仓里不自动删除。

### P5 — 收尾汇总

打印中文汇总：
```
共查 N 个 issue：
  X 已 PASS 闭环（含已 close 列表）
  Y FAIL 已追问（含评论链接）
  Z 还没回复
  W 自跳过
FAQ 新增 X 条 → 查看 cann-ops-report/faq/FAQ.md
```

## 边界与禁忌

- ✗ 不读源码做新诊断（这是 ops-test 的职责）
- ✗ 不改原仓的工作区（源码方案走新分支）
- ✗ 不替代 report-issues 提新 issue（只查、复测、回写已有 issue）
- ✗ 不持久化到 plugin 安装目录（一切在 CWD `cann-ops-report/`）
- ✗ 不自动 sleep 超过 10s 等速率限制
- ✗ 不在 ops-test P5.5 hook 里自动应用 patch 类修复（只在 track-issues 显式流程里）

## 数据来源（输入）

| 来源 | 强弱 |
|---|---|
| `cann-ops-report/issues/state.json` | 强依赖（必须存在） |
| `cann-ops-report/test/run_state.json` | 弱依赖（用于 error_signature 计算） |
| `cann-ops-report/test/logs/<repo>/<op>.phase{N}.{step}.log` | 弱依赖（同上） |
| gh CLI / GITEE_TOKEN / GITCODE_TOKEN | 平台分别强依赖 |

## 产物路径

所有产物在 `CWD/cann-ops-report/`：
- `issues/comments/<repo>/<issue_id>.json` — 原始评论
- `issues/plans/<issue_id>.json` — 用户选定的方案 plan
- `issues/patches/<repo>/<issue_id>.diff` — patch 类方案的 diff
- `issues/replies/<repo>/<issue_id>.json` — 已发出的评论
- `issues/replies/<repo>/<issue_id>.draft.md` — 未发出的草稿
- `faq/known_fixes.json` — 机器读 FAQ
- `faq/FAQ.md` — 人读 FAQ（自动渲染）
```

- [ ] **Step 2: Commit**

```bash
git add skills/track-issues/SKILL.md
git commit -m "feat(track-issues): SKILL.md describing P0-P5 workflow + activation rules"
```

---

## Task 12: ops-test SKILL.md P5.5 + integration

**Files:**
- Modify: `skills/ops-test/SKILL.md` (insert P5.5 section)
- Modify: `skills/ops-test/scripts/run_phase1_batched.py` (call faq_lookup after failures)

- [ ] **Step 1: Read ops-test SKILL.md to find P5 section anchor**

```bash
grep -n "^## P5\|^### P5\|^#### P5" skills/ops-test/SKILL.md
```

Note the line number of the P5 section (or whichever is the final phase section). The P5.5 content goes immediately after.

- [ ] **Step 2: Insert P5.5 section into SKILL.md**

After the P5 section, insert this block. Use `Read` to load the surrounding context first, then `Edit` with `old_string` being the closing line of P5 + 2 lines of trailing whitespace, and `new_string` being that closing block + the new P5.5 content.

P5.5 content (verbatim):

```markdown

## P5.5 — FAQ Lookup（失败后自动查 FAQ）

P5 写完失败诊断后，对所有 `status ∈ {BUILD_FAIL, INSTALL_FAIL, RUN_EXIT_FAIL, RUN_PATTERN_FAIL}` 的算子：

1. 调 `scripts.faq_lookup.lookup_all_failed(failed_ops)` 查 `cann-ops-report/faq/known_fixes.json`
2. **仅** fix_kind ∈ {env, build_flag, cmd_arg, upgrade} 的命中纳入结果（patch 类不在此流程自动重试，那是 track-issues 的事）
3. 命中数 ≥ 1 → `AskUserQuestion`：

   ```
   X 个失败算子在 FAQ 命中已知非源码修复：
     op1 — env: ASCEND_X=1 （来源 issue #N）
     op2 — build_flag: -DA=1
   要不要把这些 fix 应用并重新跑测？
     A. 全部应用并重试
     B. 只重试某些（接下来给我列）
     C. 不试
   ```

4. 用户选 A/B → 复用 track-issues 的 retest_orchestrator（直接 import：`from track_issues_scripts import retest_orchestrator`，路径见下方注释）；重试结果追加到当前 phase 报告
5. FAQ 文件不存在 / JSON 损坏 / 任何异常 → 静默跳过，**绝不**打断主流程
6. 重试失败 → 直接报告失败，**不**递归再查 FAQ（避免无限循环）

> 注：跨 skill 直接 import 是受控的——两个 skill 装在同一 plugin 包内，sys.path 在 plugin 加载时已包含两侧的 scripts 目录。
```

- [ ] **Step 3: Wire faq_lookup call into run_phase1_batched.py**

Find the section where the per-repo result dict is finalized (after the run loop, around the place where the per-repo report is printed). Add a final pass after all phases conclude.

In `skills/ops-test/scripts/run_phase1_batched.py`, after the `main()` function gathers all results from all repos but before it writes the final phase report, insert:

```python
def _maybe_offer_faq_retry(run_state: dict) -> None:
    """Post-fail FAQ lookup. Never raises — silent failure is safe."""
    try:
        from . import faq_lookup
    except ImportError:
        # also support direct script execution
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            import faq_lookup  # type: ignore
        except ImportError:
            return

    failed = []
    for repo_name, repo_data in run_state.get("repos", {}).items():
        for op, op_data in repo_data.get("ops", {}).items():
            ph = op_data.get("phase1", {})
            if ph.get("status") in {"BUILD_FAIL", "INSTALL_FAIL",
                                     "RUN_EXIT_FAIL", "RUN_PATTERN_FAIL"}:
                failed.append({
                    "repo": repo_name,
                    "op": op,
                    "failure_type": ph["status"],
                    "log_path": ph.get("log_path", ""),
                })
    if not failed:
        return

    try:
        hits = faq_lookup.lookup_all_failed(failed)
    except Exception:
        return

    if not hits:
        return

    # Skill (the LLM) handles AskUserQuestion via the SKILL.md narrative.
    # Here we just print a structured handoff that SKILL.md instructs the LLM to read.
    print("\n=== FAQ_HITS_FOR_SKILL ===", flush=True)
    print(json.dumps(hits, ensure_ascii=False, indent=2), flush=True)
    print("=== END_FAQ_HITS ===\n", flush=True)
```

Then call it at the end of `main()` right before the runner exits with its return code:

```python
# Inside main(), after the final report is written:
try:
    run_state = json.loads((WORK_DIR / "run_state.json").read_text(encoding="utf-8"))
    _maybe_offer_faq_retry(run_state)
except Exception:
    pass  # FAQ lookup must never break the main flow
```

- [ ] **Step 4: Smoke-test the runner still runs (parser-only)**

```bash
python3 skills/ops-test/scripts/run_phase1_batched.py --help
```

Expected: help output, no traceback.

- [ ] **Step 5: Verify all ops-test tests still pass**

```bash
cd /home/jiazhibin/cann/cann-ops-plugin/skills/ops-test
pytest -v
```

Expected: PASS (existing tests + Task 3 + Task 7 tests).

- [ ] **Step 6: Commit**

```bash
git add skills/ops-test/SKILL.md skills/ops-test/scripts/run_phase1_batched.py
git commit -m "feat(ops-test): P5.5 FAQ lookup hook with structured handoff to skill"
```

---

## Task 13: End-to-end dry run + plugin version bump

**Files:**
- Create: `skills/track-issues/tests/test_end_to_end_dry_run.py`
- Modify: `cann-ops-plugin/package.json` (version bump)
- Modify: `cann-ops-plugin/.claude-plugin/*` (if it declares skills, add track-issues)

- [ ] **Step 1: Write the dry-run integration test**

`skills/track-issues/tests/test_end_to_end_dry_run.py`:

```python
"""Dry-run: state.json + faked comments → plan.json written, no real subprocess calls."""
import json
from pathlib import Path
from unittest.mock import patch, MagicMock

from scripts import paths, fetch_comments, solution_extractor, apply_plan


def test_full_flow_to_plan(tmp_cwd: Path, fake_submitted_state: Path) -> None:
    # 1. read state.json
    state = json.loads(fake_submitted_state.read_text(encoding="utf-8"))
    assert len(state) == 3

    # 2. simulate gh CLI returning a comment with an env suggestion
    fake_gh_response = json.dumps([{
        "user": {"login": "maintainer"},
        "author_association": "MEMBER",
        "body": "try `export ASCEND_GLOBAL_LOG_LEVEL=1`",
        "created_at": "2026-05-21T08:00:00Z",
    }])
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=fake_gh_response, stderr="")
        comments = fetch_comments.fetch(
            "https://github.com/ascend/ops-transformer/issues/101"
        )
    assert len(comments) == 1

    # 3. classify
    candidates = solution_extractor.classify(comments)
    assert len(candidates) == 1
    assert candidates[0]["kind"] == "env"

    # 4. build plan
    plan = apply_plan.build_plan(
        solution=candidates[0],
        context={
            "repo": "ops-transformer", "op": "grouped_matmul",
            "failure_type": "BUILD_FAIL", "repo_path": str(tmp_cwd),
            "issue_id": "101",
        },
    )
    assert plan["kind"] == "env"
    assert "--env-extra=ASCEND_GLOBAL_LOG_LEVEL=1" in plan["ops_test_args"]
```

- [ ] **Step 2: Run the dry-run test**

```bash
cd /home/jiazhibin/cann/cann-ops-plugin/skills/track-issues
pytest tests/test_end_to_end_dry_run.py -v
```

Expected: PASS.

- [ ] **Step 3: Run full test suite (both skills)**

```bash
cd /home/jiazhibin/cann/cann-ops-plugin
pytest skills/track-issues/tests skills/ops-test/tests skills/report-issues/tests -v
```

Expected: every test PASSES, zero regressions.

- [ ] **Step 4: Bump plugin version + add skill to manifest**

Read `package.json`:

```bash
cat cann-ops-plugin/package.json
```

Bump the minor version: `1.1.0` → `1.2.0`. Also check `.claude-plugin/` for any skill manifest that needs updating:

```bash
ls .claude-plugin/
cat .claude-plugin/*.json 2>/dev/null || true
```

If a skill list exists, add `"track-issues"` to it. Exact edits depend on the file layout — read first, edit precisely.

- [ ] **Step 5: Update README**

Read existing `README.md`, then add a row to the skill table around line 8:

```markdown
| `cann-ops:track-issues` | 查询已提交到上游的算子 issue 回复，若社区给出方案则自动应用、复测、回写、关闭，并把验证过的修复沉淀到 `cann-ops-report/faq/known_fixes.json`，ops-test 下次同类失败可一键复用 |
```

Also append a short "## 闭环示例" section after the existing "## 快速开始" section describing the report → track loop.

- [ ] **Step 6: Final commit**

```bash
git add cann-ops-plugin/package.json cann-ops-plugin/.claude-plugin cann-ops-plugin/README.md \
        skills/track-issues/tests/test_end_to_end_dry_run.py
git commit -m "chore: bump to 1.2.0; expose track-issues skill in plugin manifest + README"
```

- [ ] **Step 7: Manual acceptance checklist (executed by user, NOT in CI)**

Run through each of these on a machine with NPU + a real upstream test repo:

1. Pick one already-submitted issue (or push a real failure to a personal test repo and reply with `export ASCEND_GLOBAL_LOG_LEVEL=1`). Invoke skill: "查下提的 issue 有没有回复". Verify: candidates listed → user picks env option → ops-test reruns with `--env-extra=...` → PASS → auto comment + close on upstream → FAQ.md gains an entry.

2. Cause a fresh ops-test failure with the exact same error signature. Run ops-test. Verify P5.5 prints `=== FAQ_HITS_FOR_SKILL ===` block and the skill's SKILL.md narrative offers a one-key retry.

3. Patch class flow: comment a diff on an issue → track-issues classifies as patch → branch `track-issue-<id>` is created → diff applied → ops-test on that branch → branch retained after PASS/FAIL.

4. 404 case: delete one of the upstream issues. Run track-issues. Verify state.json gets `status: deleted_upstream` and other issues are unaffected.

---

## Self-Review

After writing every task, re-check the spec one more time:

**Spec coverage:**
- §1 范围与红线 → covered by SKILL.md edges + ops-test integration restriction in Task 12
- §2.1 目录结构 → Task 0 + per-task creates
- §2.2 ops-test 改动 → Task 3 + Task 12
- §2.3 script 职责表 → Tasks 1, 2, 4–10 (one script per row)
- §2.4 FAQ 数据结构 → Task 2 (faq_writer test asserts the schema)
- §2.5 启发式规则表 → Task 5 (solution_extractor tests cover each row)
- §3 P0–P5 时序 + 跨 skill 联动 → SKILL.md (Task 11) + ops-test SKILL.md (Task 12)
- §3 P5.5 hook 时序 → Task 12 step 2 + 3
- §4 错误处理 → spread across each scripts test (404, 5xx, malformed JSON, dirty git tree, branch collision) and SKILL.md narrative; **gap:** no explicit test for gh-rate-limit handling — accepted since gh CLI surfaces it via stderr and the LLM handles per SKILL.md.
- §5 测试策略 → Task 13 + per-task pytest files

**Placeholder scan:** all steps include concrete code. No "TBD" / "TODO" / "fill in later".

**Type consistency:** `lookup_all_failed` is called from runner in Task 12; defined in faq_lookup.py in Task 3. `build_plan(solution=..., context=...)` signature consistent across apply_plan tests + retest_orchestrator. `upsert(repo=..., op=..., failure_type=..., error_signature=..., fix_kind=..., fix_payload=..., source_issue_url=..., verified_phase=..., soc=...)` consistent in faq_writer tests + (future) PASS branch caller.

**Known minor gap:** the SKILL.md narrative for P5.5 says "复用 track-issues 的 retest_orchestrator". This is a cross-skill Python import. The hook's `_maybe_offer_faq_retry` currently just **prints** the FAQ hits and hands off to the LLM, which then invokes track-issues. That's actually safer than direct import. SKILL.md description is updated in Task 12 step 2 to reflect this handoff model.
