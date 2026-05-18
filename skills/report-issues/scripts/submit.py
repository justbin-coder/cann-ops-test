"""Submit issues to GitHub (via gh CLI), Gitee, and GitCode (via urllib).

GitHub: uses `gh issue create` so auth is managed by gh CLI's own login.
Gitee:  POST gitee.com/api/v5/repos/{owner}/{repo}/issues, token in JSON body.
GitCode: POST api.gitcode.com/api/v5/repos/{owner}/{repo}/issues,
         token as access_token query parameter (NOT a header — gitcode.com's
         CloudWAF blocks /api/* on the bare domain; the api.gitcode.com
         subdomain is the only reliable path). labels MUST be a CSV string,
         never a JSON array (GitCode 422s on arrays — same as Gitee v5).

Returns the new issue URL on success; raises RuntimeError on failure.
"""
from __future__ import annotations

import json
import subprocess
import urllib.error
import urllib.request as urllib_request
from pathlib import Path


def submit_github(
    *,
    owner: str,
    repo: str,
    title: str,
    body_file: Path,
    labels: list[str],
) -> str:
    args = ["gh", "issue", "create",
             "--repo", f"{owner}/{repo}",
             "--title", title,
             "--body-file", str(body_file)]
    for label in labels:
        args += ["--label", label]
    proc = subprocess.run(args, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f"gh issue create failed: {proc.stderr.strip()}")
    # gh prints the URL on its own line
    for line in proc.stdout.strip().splitlines():
        line = line.strip()
        if line.startswith("https://"):
            return line
    raise RuntimeError(f"gh issue create succeeded but URL not parsed: {proc.stdout!r}")


def submit_gitee(
    *,
    owner: str,
    repo: str,
    title: str,
    body: str,
    labels: list[str],
    token: str,
) -> str:
    url = f"https://gitee.com/api/v5/repos/{owner}/{repo}/issues"
    payload: dict = {
        "access_token": token,
        "repo": repo,
        "title": title,
        "body": body,
    }
    if labels:
        payload["labels"] = ",".join(labels)
    data = json.dumps(payload).encode("utf-8")
    req = urllib_request.Request(
        url, data=data, method="POST",
        headers={"Content-Type": "application/json;charset=UTF-8"},
    )
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            body_bytes = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Gitee API HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"Gitee API network error: {e}") from e
    result = json.loads(body_bytes.decode("utf-8"))
    return result.get("html_url") or result.get("url") or "(missing URL in response)"


def submit_gitcode(
    *,
    owner: str,
    repo: str,
    title: str,
    body: str,
    labels: list[str],
    token: str,
) -> str:
    url = (f"https://api.gitcode.com/api/v5/repos/{owner}/{repo}/issues"
           f"?access_token={token}")
    payload: dict = {"title": title, "body": body}
    if labels:
        payload["labels"] = ",".join(labels)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib_request.Request(
        url, data=data, method="POST",
        headers={
            "Content-Type": "application/json; charset=utf-8",
            "Accept": "application/json",
        },
    )
    try:
        with urllib_request.urlopen(req, timeout=30) as resp:
            body_bytes = resp.read()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"GitCode API HTTP {e.code}: {e.reason}") from e
    except urllib.error.URLError as e:
        raise RuntimeError(f"GitCode API network error: {e}") from e
    result = json.loads(body_bytes.decode("utf-8"))
    return result.get("html_url") or result.get("url") or "(missing URL in response)"
