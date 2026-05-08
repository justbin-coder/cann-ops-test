"""通用工具：subprocess 包装、日志落盘、PASS 判定、目标算子来源解析。"""
from __future__ import annotations

import json
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

# SOC 不再硬编码。每个 runner 通过 --soc CLI 参数显式接收，由 skill 询问用户得到。

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


class OpsResolutionError(RuntimeError):
    """目标算子来源解析失败（多源未命中或文件格式不对）。"""


def resolve_ops(
    repo: str,
    cli_ops: Optional[str] = None,
    cli_ops_file: Optional[str] = None,
    scann_root: Optional[Path] = None,
) -> list[str]:
    """按优先级解析目标算子清单。

    优先级（高→低）：
      1. ``cli_ops``：CSV 字符串，例如 ``op1,op2,op3``。skill 显式传入时使用。
      2. ``cli_ops_file``：路径，可以是 .json（含 ``unique_targets`` 列表 / 顶层 list）
         或纯文本（一行一个算子，``#`` 开头为注释，空行忽略）。
      3. ``scann_root / repo / _intermediate.json`` 的 ``unique_targets`` 字段
         （由 ``cann-ops:scann-repo`` 生成的默认入口）。

    全部未命中 → 抛 ``OpsResolutionError``，要求 skill 与用户交互后重试。

    返回：去重后保持原始顺序的算子名列表。
    """
    if cli_ops:
        return _dedupe([s.strip() for s in cli_ops.split(",") if s.strip()])

    if cli_ops_file:
        return _read_ops_file(Path(cli_ops_file))

    root = scann_root or (Path.cwd() / "cann-ops-report" / "scann")
    intermediate = root / repo / "_intermediate.json"
    if intermediate.exists():
        try:
            data = json.loads(intermediate.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise OpsResolutionError(f"{intermediate} 不是合法 JSON: {e}")
        ops = data.get("unique_targets")
        if not ops:
            raise OpsResolutionError(
                f"{intermediate} 缺少 unique_targets 字段或为空，"
                f"请重新运行 cann-ops:scann-repo 扫描 {repo}"
            )
        return _dedupe(list(ops))

    raise OpsResolutionError(
        f"未指定目标算子来源：未传 --ops/--ops-file，且 {intermediate} 不存在。"
        f"请先用 cann-ops:scann-repo 扫描，或显式提供 --ops 算子清单。"
    )


def _read_ops_file(path: Path) -> list[str]:
    if not path.exists():
        raise OpsResolutionError(f"--ops-file 指向的文件不存在: {path}")
    text = path.read_text(encoding="utf-8").strip()
    # 尝试 JSON：支持 {"unique_targets": [...]} 或顶层 list
    try:
        data = json.loads(text)
        if isinstance(data, dict) and "unique_targets" in data:
            return _dedupe(list(data["unique_targets"]))
        if isinstance(data, list):
            return _dedupe([str(x) for x in data])
    except json.JSONDecodeError:
        pass
    # 纯文本：每行一个算子，# 注释，空行忽略
    ops: list[str] = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        ops.append(s)
    if not ops:
        raise OpsResolutionError(f"--ops-file {path} 解析后为空")
    return _dedupe(ops)


def _dedupe(seq: list[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for x in seq:
        if x not in seen:
            seen.add(x)
            out.append(x)
    return out
