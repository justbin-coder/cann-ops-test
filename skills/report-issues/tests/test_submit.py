import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts import submit


def test_submit_github_via_gh_cli(tmp_path: Path) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text("body content\n", encoding="utf-8")
    fake_completed = MagicMock()
    fake_completed.returncode = 0
    fake_completed.stdout = "https://github.com/o/r/issues/42\n"
    fake_completed.stderr = ""
    with patch.object(submit.subprocess, "run", return_value=fake_completed) as mocked:
        url = submit.submit_github(
            owner="o", repo="r",
            title="t", body_file=draft,
            labels=["bug", "ops-failure"],
        )
    assert url == "https://github.com/o/r/issues/42"
    args = mocked.call_args[0][0]
    assert args[:2] == ["gh", "issue"]
    assert "create" in args
    assert "--repo" in args and "o/r" in args
    assert "--label" in args


def test_submit_github_failure_raises(tmp_path: Path) -> None:
    draft = tmp_path / "d.md"; draft.write_text("x")
    fake = MagicMock(returncode=1, stdout="", stderr="auth required\n")
    with patch.object(submit.subprocess, "run", return_value=fake):
        with pytest.raises(RuntimeError, match="gh issue create failed"):
            submit.submit_github(owner="o", repo="r", title="t",
                                  body_file=draft, labels=[])


def test_submit_gitee_via_urllib() -> None:
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({
        "html_url": "https://gitee.com/o/r/issues/I0001",
        "number": 1,
    }).encode("utf-8")
    fake_response.__enter__ = lambda s: s
    fake_response.__exit__ = lambda s, *a: None
    with patch.object(submit.urllib_request, "urlopen", return_value=fake_response):
        url = submit.submit_gitee(owner="o", repo="r",
                                    title="t", body="b",
                                    labels=["bug"], token="tok123")
    assert url == "https://gitee.com/o/r/issues/I0001"


def test_submit_gitcode_via_urllib() -> None:
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({
        "html_url": "https://gitcode.com/cann/ops-nn/issues/2749",
        "number": 2749,
    }).encode("utf-8")
    fake_response.__enter__ = lambda s: s
    fake_response.__exit__ = lambda s, *a: None
    captured = {}

    def fake_urlopen(req, timeout=30):
        captured["url"] = req.full_url
        captured["data"] = req.data
        return fake_response

    with patch.object(submit.urllib_request, "urlopen", side_effect=fake_urlopen):
        url = submit.submit_gitcode(owner="cann", repo="ops-nn",
                                     title="t", body="b",
                                     labels=["bug", "p1"], token="tok123")
    assert url == "https://gitcode.com/cann/ops-nn/issues/2749"
    # API host + auth via access_token query param
    assert captured["url"].startswith(
        "https://api.gitcode.com/api/v5/repos/cann/ops-nn/issues?access_token=tok123")
    payload = json.loads(captured["data"].decode("utf-8"))
    # labels MUST be CSV string, never a list (GitCode 422s on arrays)
    assert payload["labels"] == "bug,p1"
    assert payload["title"] == "t"
    assert payload["body"] == "b"


def test_submit_gitcode_no_labels_omits_field() -> None:
    fake_response = MagicMock()
    fake_response.read.return_value = json.dumps({
        "html_url": "https://gitcode.com/o/r/issues/1"}).encode("utf-8")
    fake_response.__enter__ = lambda s: s
    fake_response.__exit__ = lambda s, *a: None
    captured = {}

    def fake_urlopen(req, timeout=30):
        captured["data"] = req.data
        return fake_response

    with patch.object(submit.urllib_request, "urlopen", side_effect=fake_urlopen):
        submit.submit_gitcode(owner="o", repo="r", title="t", body="b",
                               labels=[], token="tok")
    payload = json.loads(captured["data"].decode("utf-8"))
    assert "labels" not in payload


def test_submit_gitcode_http_error_raises() -> None:
    import urllib.error
    with patch.object(submit.urllib_request, "urlopen",
                       side_effect=urllib.error.HTTPError(
                           url="x", code=403, msg="forbidden", hdrs=None, fp=None)):
        with pytest.raises(RuntimeError, match="GitCode API"):
            submit.submit_gitcode(owner="o", repo="r", title="t",
                                    body="b", labels=[], token="tok")


def test_submit_gitee_http_error_raises() -> None:
    import urllib.error
    with patch.object(submit.urllib_request, "urlopen",
                       side_effect=urllib.error.HTTPError(
                           url="x", code=401, msg="unauthorized", hdrs=None, fp=None)):
        with pytest.raises(RuntimeError, match="Gitee API"):
            submit.submit_gitee(owner="o", repo="r", title="t",
                                  body="b", labels=[], token="tok")
