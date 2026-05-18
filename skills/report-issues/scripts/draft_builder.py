"""Render markdown issue drafts in 3 granularities.

Output paths:
    CWD/cann-ops-report/issues/drafts/<repo>/per_op/<op>__<type>.md
    CWD/cann-ops-report/issues/drafts/<repo>/by_type/<type>.md
    CWD/cann-ops-report/issues/drafts/<repo>/whole_repo.md
"""
from __future__ import annotations

from pathlib import Path

from . import log_extract, paths
from .failures import FailureRecord


def _env_section(env: dict[str, str]) -> str:
    return (
        "## 环境\n"
        f"- SOC: {env['soc']}\n"
        f"- CANN 版本: {env['cann_version']}\n"
        f"- 仓 commit: {env['git_rev']}\n"
        f"- Python: {env['python_version']}\n"
        f"- OS: {env['os']}\n"
    )


def _ops_table(recs: list[FailureRecord]) -> str:
    rows = ["| repo | op | failure_type | phase | duration_s | attempts |",
            "|---|---|---|---|---|---|"]
    for r in recs:
        rows.append(f"| {r.repo} | {r.op} | {r.failure_type} | {r.phase} | "
                    f"{r.duration_s} | {r.attempts} |")
    return "## 失败算子\n" + "\n".join(rows) + "\n"


def _repro_block(recs: list[FailureRecord], soc: str) -> str:
    ops = ",".join(sorted({r.op for r in recs}))
    return (
        "## 复现命令\n"
        "（社区相对路径，省略本地绝对路径）\n"
        "```bash\n"
        "cd <repo_root>\n"
        f"bash build.sh --pkg --soc={soc} --ops={ops} -j16\n"
        f"bash build.sh --run_example {ops.split(',')[0]} eager cust --vendor_name=custom\n"
        "```\n"
    )


def _logs_block(recs: list[FailureRecord]) -> str:
    parts = ["## 错误日志摘录"]
    for r in recs:
        parts.append(f"\n### {r.op} ({r.failure_type})")
        lines = log_extract.extract_errors(Path(r.log_path), max_lines=80)
        parts.append(log_extract.format_as_code_block(lines))
    return "\n".join(parts) + "\n"


def _labels_block(failure_type: str, soc: str) -> str:
    return (
        "## 建议 labels\n"
        f"bug, ops-failure, soc:{soc}, {failure_type.lower()}\n"
    )


def _drafts_root(repo: str) -> Path:
    return paths.DRAFTS_DIR._resolve() / repo


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def build_per_op(repo: str,
                 by_type: dict[str, list[FailureRecord]],
                 *, env: dict[str, str], repo_path: Path) -> list[Path]:
    """One file per (op, failure_type) failure."""
    written: list[Path] = []
    out_dir = _drafts_root(repo) / "per_op"
    for failure_type, recs in by_type.items():
        for r in recs:
            body = "\n".join([
                _env_section(env),
                _ops_table([r]),
                _repro_block([r], env["soc"]),
                _logs_block([r]),
                _labels_block(failure_type, env["soc"]),
            ])
            path = out_dir / f"{r.op}__{failure_type}.md"
            _write(path, body)
            written.append(path)
    return written


def build_by_type(repo: str,
                  by_type: dict[str, list[FailureRecord]],
                  *, env: dict[str, str], repo_path: Path) -> list[Path]:
    """One file per failure_type, listing all ops of that type."""
    written: list[Path] = []
    out_dir = _drafts_root(repo) / "by_type"
    for failure_type, recs in by_type.items():
        body = "\n".join([
            _env_section(env),
            _ops_table(recs),
            _repro_block(recs, env["soc"]),
            _logs_block(recs),
            _labels_block(failure_type, env["soc"]),
        ])
        path = out_dir / f"{failure_type}.md"
        _write(path, body)
        written.append(path)
    return written


def build_whole_repo(repo: str,
                     by_type: dict[str, list[FailureRecord]],
                     *, env: dict[str, str], repo_path: Path) -> list[Path]:
    """A single file per repo, sections grouped by failure_type."""
    parts: list[str] = [_env_section(env)]
    all_recs: list[FailureRecord] = []
    for failure_type, recs in by_type.items():
        parts.append(f"## {failure_type}\n")
        parts.append(_ops_table(recs))
        parts.append(_logs_block(recs))
        all_recs.extend(recs)
    parts.append(_repro_block(all_recs, env["soc"]))
    parts.append("## 建议 labels\n"
                 f"bug, ops-failure, soc:{env['soc']}\n")
    path = _drafts_root(repo) / "whole_repo.md"
    _write(path, "\n".join(parts))
    return [path]
