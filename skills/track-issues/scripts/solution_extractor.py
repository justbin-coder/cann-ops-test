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
        matched_any = False

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
            matched_any = True

        for m in _ENV_RE.finditer(body):
            out.append({
                "kind": "env",
                "raw_text": body,
                "suggested_fix": f"{m.group(1)}={m.group(2).strip('`')}",
                "confidence": _confidence(role),
                "actionable": True,
                "source": src,
            })
            matched_any = True

        for m in _BUILD_FLAG_RE.finditer(body):
            out.append({
                "kind": "build_flag",
                "raw_text": body,
                "suggested_fix": m.group(1),
                "confidence": _confidence(role),
                "actionable": True,
                "source": src,
            })
            matched_any = True

        for m in _CMD_ARG_RE.finditer(body):
            out.append({
                "kind": "cmd_arg",
                "raw_text": body,
                "suggested_fix": m.group(1).strip(),
                "confidence": "med",
                "actionable": True,
                "source": src,
            })
            matched_any = True

        if _UPGRADE_RE.search(body):
            out.append({
                "kind": "upgrade",
                "raw_text": body,
                "suggested_fix": body.strip(),
                "confidence": "med",
                "actionable": True,
                "source": src,
            })
            matched_any = True

        # If nothing actionable matched but body is non-trivial discuss
        if not matched_any and body.strip():
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
