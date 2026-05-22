"""Post a comment to an upstream issue and optionally close it.

Auth (same as fetch_comments):
- GitHub:  gh CLI
- Gitee:   GITEE_TOKEN env var
- GitCode: GITCODE_TOKEN env var (api.gitcode.com)
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


def post_comment(issue_url: str, body: str) -> None:
    """Post a markdown comment. Raises RuntimeError on failure."""
    m = _GH_RE.match(issue_url)
    if m:
        _gh_comment(m.group(1), m.group(2), m.group(3), body)
        return

    m = _GITEE_RE.match(issue_url)
    if m:
        _gitee_comment(m.group(1), m.group(2), m.group(3), body)
        return

    m = _GITCODE_RE.match(issue_url)
    if m:
        _gitcode_comment(m.group(1), m.group(2), m.group(3), body)
        return

    raise ValueError(f"Unrecognized issue URL: {issue_url}")


def close_issue(issue_url: str) -> None:
    """Close the issue. Raises RuntimeError on failure."""
    m = _GH_RE.match(issue_url)
    if m:
        _gh_close(m.group(1), m.group(2), m.group(3))
        return

    m = _GITEE_RE.match(issue_url)
    if m:
        _gitee_close(m.group(1), m.group(2), m.group(3))
        return

    m = _GITCODE_RE.match(issue_url)
    if m:
        _gitcode_close(m.group(1), m.group(2), m.group(3))
        return

    raise ValueError(f"Unrecognized issue URL: {issue_url}")


# ── GitHub ──────────────────────────────────────────────────────────────────

def _gh_comment(owner: str, repo: str, num: str, body: str) -> None:
    r = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/issues/{num}/comments",
         "-X", "POST", "-f", f"body={body}"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"gh comment failed: {r.stderr}")


def _gh_close(owner: str, repo: str, num: str) -> None:
    r = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/issues/{num}",
         "-X", "PATCH", "-f", "state=closed"],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"gh close failed: {r.stderr}")


# ── Gitee ───────────────────────────────────────────────────────────────────

def _gitee_req(method: str, path: str, payload: dict) -> None:
    token = os.environ.get("GITEE_TOKEN", "")
    url = f"https://gitee.com/api/v5/{path}?access_token={token}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Gitee API error {e.code}: {e.read().decode(errors='replace')}")


def _gitee_comment(owner: str, repo: str, num: str, body: str) -> None:
    _gitee_req("POST", f"repos/{owner}/{repo}/issues/{num}/comments", {"body": body})


def _gitee_close(owner: str, repo: str, num: str) -> None:
    _gitee_req("PATCH", f"repos/{owner}/{repo}/issues/{num}", {"state": "closed"})


# ── GitCode ──────────────────────────────────────────────────────────────────

def _gitcode_req(method: str, path: str, payload: dict) -> None:
    token = os.environ.get("GITCODE_TOKEN", "")
    url = f"https://api.gitcode.com/api/v5/{path}?access_token={token}"
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Content-Type": "application/json"})
    try:
        urllib.request.urlopen(req, timeout=30)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitCode API error {e.code}: {e.read().decode(errors='replace')}")


def _gitcode_comment(owner: str, repo: str, num: str, body: str) -> None:
    _gitcode_req("POST", f"repos/{owner}/{repo}/issues/{num}/comments", {"body": body})


def _gitcode_close(owner: str, repo: str, num: str) -> None:
    _gitcode_req("PATCH", f"repos/{owner}/{repo}/issues/{num}", {"state": "closed"})
