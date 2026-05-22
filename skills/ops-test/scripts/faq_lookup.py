"""Read-only FAQ lookup for ops-test failure-recovery hook.

Never raises: malformed JSON, missing files, missing signatures all return None.
Filters out fix_kind='patch' (those need user-controlled git ops, not silent retry)."""
from __future__ import annotations

import json
from pathlib import Path

try:
    from . import _error_sig
except ImportError:
    import _error_sig  # type: ignore


FAQ_JSON_REL = Path("cann-ops-report") / "faq" / "known_fixes.json"

_NON_SOURCE_KINDS = {"env", "build_flag", "cmd_arg", "upgrade"}


def _faq_path() -> Path:
    return Path.cwd() / FAQ_JSON_REL


def lookup_from_log(
    *,
    repo: str,
    op: str,
    failure_type: str,
    log_path,
    precomputed_signature: str | None = None,
) -> dict | None:
    """Return matching fix entry, or None."""
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
    """Batch lookup. failed_ops: list of {repo, op, failure_type, log_path}."""
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
