from pathlib import Path

from scripts import paths


def test_paths_are_under_cann_ops_report_issues(tmp_cwd: Path) -> None:
    assert paths.WORK_DIR == tmp_cwd / "cann-ops-report" / "issues"
    assert paths.STATE_FILE == paths.WORK_DIR / "state.json"
    assert paths.REPOS_FILE == paths.WORK_DIR / "repos.json"
    assert paths.DRAFTS_DIR == paths.WORK_DIR / "drafts"
    assert paths.SUBMITTED_DIR == paths.WORK_DIR / "submitted"


def test_test_subtree_resolves_to_ops_test_outputs(tmp_cwd: Path) -> None:
    assert paths.TEST_DIR == tmp_cwd / "cann-ops-report" / "test"
    assert paths.TEST_STATE_FILE == paths.TEST_DIR / "run_state.json"
    assert paths.TEST_LOGS_DIR == paths.TEST_DIR / "logs"
    assert paths.TEST_FAILURES_DIR == paths.TEST_DIR / "failures"


def test_scann_subtree_resolves_to_scann_repo_outputs(tmp_cwd: Path) -> None:
    assert paths.SCANN_DIR == tmp_cwd / "cann-ops-report" / "scann"
