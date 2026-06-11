from pathlib import Path

from scripts import paths


def test_paths_are_under_cann_ops_report_issues(tmp_cwd: Path) -> None:
    assert paths.WORK_DIR == tmp_cwd / "cann-ops-report" / "issues"
    assert paths.STATE_FILE == paths.WORK_DIR / "state.json"
    assert paths.REPOS_FILE == paths.WORK_DIR / "repos.json"
    assert paths.DRAFTS_DIR == paths.WORK_DIR / "drafts"
    assert paths.SUBMITTED_DIR == paths.WORK_DIR / "submitted"


def test_per_repo_test_subtree(tmp_cwd: Path) -> None:
    base = tmp_cwd / "cann-ops-report" / "ops-x" / "test"
    assert paths.repo_test_dir("ops-x") == base
    assert paths.repo_state_file("ops-x") == base / "run_state.json"
    assert paths.repo_logs_dir("ops-x") == base / "logs"
    assert paths.repo_failures_dir("ops-x") == base / "failures"


def test_per_repo_scann_subtree(tmp_cwd: Path) -> None:
    assert paths.repo_scann_dir("ops-x") == tmp_cwd / "cann-ops-report" / "ops-x" / "scann"


def test_iter_repo_states(tmp_cwd: Path, fake_run_state: Path) -> None:
    repos = [r for r, _ in paths.iter_repo_states()]
    assert repos == ["ops-cv", "ops-transformer"]
