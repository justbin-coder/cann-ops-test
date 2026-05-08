"""通用工具：subprocess 包装、日志落盘、PASS 判定。"""
from __future__ import annotations

import re
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

# 运行产物写到 CWD/cann-ops-report/test/（与 state.py 保持一致）
WORK_DIR = Path.cwd() / "cann-ops-report/test"
OUTPUTS_DIR = WORK_DIR
LOGS_DIR = WORK_DIR / "logs"

# CANN 环境激活脚本：CANN toolkit 安装后会自动设置 ASCEND_HOME_PATH，
# 从中推导 set_env.sh 路径；找不到时 fallback 到标准安装默认路径。
import os as _os
def _find_set_env_sh() -> str:
    ascend_home = _os.environ.get("ASCEND_HOME_PATH", "")
    if ascend_home:
        candidate = Path(ascend_home).parent.parent / "set_env.sh"
        if candidate.exists():
            return str(candidate)
    return str(Path.home() / "Ascend/ascend-toolkit/latest/set_env.sh")

CANN_SET_ENV_SH = _find_set_env_sh()

# 950 工具固定 SOC，写死避免 --soc 参数化。见 SKILL.md 「前置环境节点 P1」。
DEFAULT_SOC = "ascend950"

# PASS 判定的 stdout 模式（覆盖 examples / pytest / 通用 UT 三种风格）
SUCCESS_PATTERNS = [
    re.compile(r"result\[\d+\]\s+is:"),       # examples 风格（QUICKSTART §5 输出样例）
    re.compile(r"All tests passed"),
    re.compile(r"Test PASSED"),
    re.compile(r"\bpassed\b", re.IGNORECASE),  # pytest 风格
    re.compile(r"PASS\b"),
]


@dataclass
class CmdResult:
    cmd: str
    cwd: str
    exit_code: int
    duration_s: float
    stdout: str
    stderr: str
    log_path: Optional[Path] = None
    timed_out: bool = False

    def stdout_matches_success(self) -> bool:
        return any(p.search(self.stdout) for p in SUCCESS_PATTERNS)

    def passed(self) -> bool:
        return self.exit_code == 0 and self.stdout_matches_success()


def ensure_log_path(repo: str, op: str, phase: str) -> Path:
    repo_logs = LOGS_DIR / repo
    repo_logs.mkdir(parents=True, exist_ok=True)
    return repo_logs / f"{op}.{phase}.log"


def run_cmd(
    cmd: str,
    cwd: str | Path,
    timeout: int,
    log_path: Optional[Path] = None,
    env: Optional[dict] = None,
) -> CmdResult:
    """跑一条 shell 命令，全量捕获 stdout+stderr 并落盘。

    自动在 cmd 前 source CANN_SET_ENV_SH，确保 ASCEND_HOME_PATH 等环境变量
    在 subprocess 中可用（见 SKILL.md 「前置环境节点 P0」）。
    """
    start = time.time()
    timed_out = False
    wrapped_cmd = f"source {CANN_SET_ENV_SH} && {cmd}"
    try:
        proc = subprocess.run(
            wrapped_cmd,
            shell=True,
            executable="/bin/bash",
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=env,
        )
        exit_code = proc.returncode
        stdout = proc.stdout or ""
        stderr = proc.stderr or ""
    except subprocess.TimeoutExpired as e:
        exit_code = 124  # 约定超时退出码
        stdout = (e.stdout.decode() if isinstance(e.stdout, bytes) else (e.stdout or "")) or ""
        stderr = (e.stderr.decode() if isinstance(e.stderr, bytes) else (e.stderr or "")) or ""
        stderr += f"\n[TIMEOUT after {timeout}s]\n"
        timed_out = True

    duration = time.time() - start

    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        log_path.write_text(
            f"$ cd {cwd}\n$ {cmd}\n[exit={exit_code} duration={duration:.1f}s timeout={timeout}s]\n"
            f"\n--- STDOUT ---\n{stdout}\n--- STDERR ---\n{stderr}\n",
            encoding="utf-8",
            errors="replace",
        )

    return CmdResult(
        cmd=cmd,
        cwd=str(cwd),
        exit_code=exit_code,
        duration_s=duration,
        stdout=stdout,
        stderr=stderr,
        log_path=log_path,
        timed_out=timed_out,
    )


def find_run_pkg(repo_path: Path) -> Optional[Path]:
    """找到 build_out 下的 cann-ops-*-linux*.run。"""
    candidates = sorted((repo_path / "build_out").glob("cann-ops-*linux*.run"))
    return candidates[-1] if candidates else None


def vendor_name_for(repo: str) -> str:
    """从仓名派生 vendor name。

    约定：`ops-X` → `custom_X`（剥掉 `ops-` 前缀加 `custom_`）。
    非 `ops-` 前缀仓名兜底为 `custom_<repo>`。
    """
    name = repo[4:] if repo.startswith("ops-") else repo
    return f"custom_{name}"


def append_ld_library_path(env: dict, repo: str, ascend_home: str) -> dict:
    """将该仓的 vendor lib 路径前置到 LD_LIBRARY_PATH（QUICKSTART §4）。"""
    vendor = vendor_name_for(repo)
    seg = f"{ascend_home}/opp/vendors/{vendor}/op_api/lib"
    cur = env.get("LD_LIBRARY_PATH", "")
    env["LD_LIBRARY_PATH"] = f"{seg}:{cur}" if cur else seg
    return env
