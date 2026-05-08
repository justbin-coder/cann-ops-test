"""~/.config/cann-ops/config.json 的读写工具。

存储用户个性化配置（ops 仓路径），由 skill 首次运行时通过对话写入，
后续自动读取，无需用户手动配置环境变量。
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

CONFIG_FILE = Path.home() / ".config" / "cann-ops" / "config.json"

KNOWN_REPOS = ["ops-transformer", "ops-cv", "ops-math", "ops-nn"]


def load() -> dict:
    if not CONFIG_FILE.exists():
        return {}
    return json.loads(CONFIG_FILE.read_text(encoding="utf-8"))


def _save(data: dict) -> None:
    CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def get_repo_path(repo: str) -> str | None:
    return load().get("repo_paths", {}).get(repo)


def get_all_repo_paths() -> dict[str, str]:
    return load().get("repo_paths", {})


def set_repo_path(repo: str, path: str) -> None:
    data = load()
    data.setdefault("repo_paths", {})[repo] = path
    _save(data)


def is_configured() -> bool:
    paths = get_all_repo_paths()
    return all(repo in paths for repo in KNOWN_REPOS)


def missing_repos() -> list[str]:
    paths = get_all_repo_paths()
    return [r for r in KNOWN_REPOS if r not in paths]


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="cann-ops 配置管理")
    sub = ap.add_subparsers(dest="cmd")

    p_set = sub.add_parser("set-repo", help="设置某仓的本地路径")
    p_set.add_argument("repo", choices=KNOWN_REPOS)
    p_set.add_argument("path", help="本地路径，如 /data/cann/ops-transformer")

    p_get = sub.add_parser("get-repo", help="查询某仓的本地路径")
    p_get.add_argument("repo", choices=KNOWN_REPOS)

    sub.add_parser("status", help="显示所有配置")

    args = ap.parse_args()

    if args.cmd == "set-repo":
        p = Path(args.path)
        if not p.is_dir():
            print(f"[ERROR] 路径不存在：{p}", file=sys.stderr)
            sys.exit(1)
        set_repo_path(args.repo, str(p.resolve()))
        print(f"✓ {args.repo} → {p.resolve()}")

    elif args.cmd == "get-repo":
        v = get_repo_path(args.repo)
        print(v if v else f"[未配置] {args.repo}")

    elif args.cmd == "status":
        paths = get_all_repo_paths()
        for repo in KNOWN_REPOS:
            v = paths.get(repo, "[未配置]")
            print(f"  {repo}: {v}")

    else:
        ap.print_help()
