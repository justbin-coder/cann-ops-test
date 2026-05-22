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
