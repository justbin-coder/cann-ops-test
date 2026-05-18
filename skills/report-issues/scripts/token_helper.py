"""Gitee personal access token handling.

Lookup order:
    1. os.environ['GITEE_TOKEN']
    2. Caller falls back to AskUserQuestion (orchestrate.py does that — not here)

Optional convenience: after a successful single-use prompt, the user may
ask to persist the token to ~/.bashrc / ~/.zshrc / ~/.profile (their choice).
Writes are explicit and never automatic.
"""
from __future__ import annotations

import os
import re
from pathlib import Path


_EXPORT_LINE_PATTERN = re.compile(r"^\s*export\s+GITEE_TOKEN\s*=.*$", re.MULTILINE)


def get_from_env() -> str | None:
    val = os.environ.get("GITEE_TOKEN", "").strip()
    return val or None


def has_existing_export(rc_path: Path) -> bool:
    p = Path(rc_path)
    if not p.exists():
        return False
    return _EXPORT_LINE_PATTERN.search(p.read_text(encoding="utf-8")) is not None


def write_to_shell(rc_path: Path, token: str) -> None:
    """Append `export GITEE_TOKEN=<token>` to rc_path. Creates file if missing."""
    p = Path(rc_path)
    line = f"\nexport GITEE_TOKEN={token}\n"
    if not p.exists():
        p.write_text(line.lstrip("\n"), encoding="utf-8")
        return
    with p.open("a", encoding="utf-8") as f:
        f.write(line)


def overwrite_existing(rc_path: Path, token: str) -> None:
    """Replace any existing `export GITEE_TOKEN=...` line with the new token."""
    p = Path(rc_path)
    if not p.exists():
        return write_to_shell(rc_path, token)
    text = p.read_text(encoding="utf-8")
    new_text = _EXPORT_LINE_PATTERN.sub(f"export GITEE_TOKEN={token}", text)
    p.write_text(new_text, encoding="utf-8")
