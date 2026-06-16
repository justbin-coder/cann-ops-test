"""quickstart-check 脚本单测(纯逻辑,无 NPU)。"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import _state          # noqa: E402
import find_docs       # noqa: E402
import run_step        # noqa: E402
import render_report   # noqa: E402


def _redirect(monkeypatch, tmp_path):
    """把产物根重定向到 tmp(_state 的路径函数读模块全局,monkeypatch 即生效)。"""
    monkeypatch.setattr(_state, "DOCCHECK_ROOT", tmp_path / "doccheck")


# ---- find_docs:文件名命中 + 标题命中 + 跳过噪声目录 ----

def test_find_docs(tmp_path):
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "QUICKSTART.md").write_text("# Quick Start\n步骤", encoding="utf-8")
    (tmp_path / "docs" / "zh").mkdir()
    (tmp_path / "docs" / "zh" / "intro.md").write_text("## 快速入门\n内容", encoding="utf-8")  # heading
    (tmp_path / "README.md").write_text("# Project\n无关", encoding="utf-8")                    # 不命中
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "QUICKSTART.md").write_text("# Quick Start", encoding="utf-8")        # 噪声目录,跳过

    docs = find_docs.find_docs(str(tmp_path))
    paths = [d["path"] for d in docs]
    assert "docs/QUICKSTART.md" in paths            # 文件名命中
    assert "docs/zh/intro.md" in paths              # 标题命中
    assert "README.md" not in paths                 # 无关键字,不收
    assert all("build/" not in p for p in paths)    # 噪声目录跳过
    assert docs[0]["match"] == "filename"           # 文件名命中排前


# ---- run_step 执行:忠实记录退出码 + 落盘日志,verdict 待判 ----

def test_run_step_execute(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    work = tmp_path / "w"; work.mkdir()
    rec = run_step.execute("ops-x", 1, str(work), "echo hello-quickstart")
    assert rec["exit_code"] == 0
    assert "hello-quickstart" in rec["stdout_excerpt"]
    assert rec["verdict"] == "UNJUDGED"             # 执行不判定
    assert os.path.isfile(rec["log_path"])          # 真实日志落盘
    steps = _state.load_steps("ops-x")
    assert len(steps) == 1 and steps[0]["idx"] == 1


def test_run_step_failure_recorded(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    work = tmp_path / "w"; work.mkdir()
    rec = run_step.execute("ops-x", 2, str(work), "exit 3")
    assert rec["exit_code"] == 3                    # 失败如实记录,不重试


def test_run_step_no_injection(tmp_path, monkeypatch):
    """纪律核验:execute 不注入文档外 env —— 文档没让 export 的变量就不该存在。"""
    _redirect(monkeypatch, tmp_path)
    work = tmp_path / "w"; work.mkdir()
    rec = run_step.execute("ops-x", 1, str(work), 'echo "VAR=[${QUICKSTART_INJECT:-unset}]"')
    assert "VAR=[unset]" in rec["stdout_excerpt"]


# ---- 判定 + 卡住即停语义 ----

def test_set_verdict_and_blocker(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    work = tmp_path / "w"; work.mkdir()
    run_step.execute("ops-x", 1, str(work), "echo ok")
    run_step.execute("ops-x", 2, str(work), "exit 1")
    assert _state.set_verdict("ops-x", 1, "OK")
    assert _state.set_verdict("ops-x", 2, "FAIL", defect="文档未说明需先 source 环境", fix="文档应在第 2 步前加 `source set_env.sh`")
    assert not _state.set_verdict("ops-x", 99, "OK")        # 不存在的步
    assert "FAIL" in _state.BLOCKER_VERDICTS                 # FAIL 是卡点


# ---- 报告:有 blocker → 卡在第 N 步;全 OK → 通过 ----

def test_render_blocked(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    work = tmp_path / "w"; work.mkdir()
    _state.save_meta("ops-x", {"doc": "docs/QUICKSTART.md", "declared_prerequisites": ["CANN 已装"]})
    run_step.execute("ops-x", 1, str(work), "echo ok")
    run_step.execute("ops-x", 2, str(work), "exit 1")
    _state.set_verdict("ops-x", 1, "OK")
    _state.set_verdict("ops-x", 2, "FAIL", defect="缺 source 步骤", fix="补 source")
    md = render_report.render("ops-x")
    assert "卡在第 2 步" in md
    assert "缺 source 步骤" in md and "补 source" in md       # 缺陷 + 修订建议都进报告
    assert "docs/QUICKSTART.md" in md


def test_render_passed(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    work = tmp_path / "w"; work.mkdir()
    run_step.execute("ops-y", 1, str(work), "echo a")
    run_step.execute("ops-y", 2, str(work), "echo b")
    _state.set_verdict("ops-y", 1, "OK")
    _state.set_verdict("ops-y", 2, "OK")
    md = render_report.render("ops-y")
    assert "能纯按文档跑通" in md
    assert "未发现文档缺陷" in md
