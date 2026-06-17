"""tutorial-eval 脚本单测(纯逻辑;codecheck 用系统 grep)。"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

import _state          # noqa: E402
import find_tutorials  # noqa: E402
import codecheck       # noqa: E402
import render_report   # noqa: E402


def _redirect(monkeypatch, tmp_path):
    monkeypatch.setattr(_state, "TUTEVAL_ROOT", tmp_path / "tutorial-eval")


# ---- find_tutorials:命中开发指南、排除 quickstart/README/参考、跳噪声目录 ----

def test_find_tutorials(tmp_path):
    d = tmp_path / "docs" / "zh"
    (d / "develop").mkdir(parents=True)
    (d / "develop" / "aicore_develop_guide.md").write_text("# AI Core算子开发指南\n", encoding="utf-8")  # 文件名命中
    (d / "advanced.md").write_text("## 进阶\n内容", encoding="utf-8")                                    # 标题命中
    (tmp_path / "QUICKSTART.md").write_text("# 快速入门", encoding="utf-8")                               # 排除
    (d / "op_list.md").write_text("# 算子清单", encoding="utf-8")                                         # 排除(参考清单)
    (tmp_path / "README.md").write_text("# Develop Guide here", encoding="utf-8")                          # 文件名排除
    (tmp_path / "build").mkdir()
    (tmp_path / "build" / "x_develop_guide.md").write_text("# guide", encoding="utf-8")                   # 噪声目录,跳

    paths = [x["path"] for x in find_tutorials.find_tutorials(str(tmp_path))]
    assert "docs/zh/develop/aicore_develop_guide.md" in paths
    assert "docs/zh/advanced.md" in paths
    assert "QUICKSTART.md" not in paths
    assert "docs/zh/op_list.md" not in paths
    assert "README.md" not in paths
    assert all("build/" not in p for p in paths)


# ---- codecheck triage:占位符 / 外部命令 / 仓内对象 ----

def test_triage():
    assert codecheck.triage("<repo>", "path") == "placeholder"
    assert codecheck.triage("$ASCEND_HOME/x", "path") == "placeholder"
    assert codecheck.triage("cmake ..", "command") == "external"
    assert codecheck.triage("pip install x", "command") == "external"
    assert codecheck.triage("build.sh --pkg", "command") == "repo_object"
    assert codecheck.triage("build/foo.run", "path") == "generated"


# ---- codecheck 取证:强命中→CONSISTENT;缺失+近似变体→SUSPECTED 带变体 ----

def test_codecheck_strong_and_variant(tmp_path):
    (tmp_path / "build.sh").write_text(
        'case "$1" in\n  --opkernel) echo ok ;;\nesac\n', encoding="utf-8")
    # 文档写的 --opkernel 真有(case 分支=强证据)
    r1 = codecheck.check(str(tmp_path), "--opkernel", "flag")
    assert r1["triage"] == "repo_object"
    assert r1["grade"] == "strong" and r1["suggested_verdict"] == "CONSISTENT"
    # 文档写的 --opkernel_test 没有,但近似变体 --opkernel 在 → SUSPECTED + 变体(agent 可升 CONFIRMED)
    r2 = codecheck.check(str(tmp_path), "--opkernel_test", "flag")
    assert r2["suggested_verdict"] == "SUSPECTED"
    assert "--opkernel" in r2["near_variants"]
    # codecheck 绝不自己下 CONFIRMED
    assert r2["suggested_verdict"] != "CONFIRMED_MISMATCH"


def test_codecheck_path_missing_vs_present(tmp_path):
    (tmp_path / "real.txt").write_text("x", encoding="utf-8")
    assert codecheck.check(str(tmp_path), "real.txt", "path")["suggested_verdict"] == "CONSISTENT"
    assert codecheck.check(str(tmp_path), "scripts/requirements.txt", "path")["suggested_verdict"] == "SUSPECTED"


# ---- 自校验闸:可量化无代码位置 / 不可量化无判例·steelman / 确认讲错无外部反证 → 不过 ----

def test_self_check_gate():
    ok_q = {"cls": "quantifiable", "axis": "trustworthy", "quote": "x", "verdict": "CONFIRMED_MISMATCH",
            "improvement": "改", "code_location": "build.sh:3"}
    assert _state.self_check_finding(ok_q) == []
    bad_q = {**ok_q, "code_location": None}
    assert any("code_location" in p for p in _state.self_check_finding(bad_q))   # 可量化缺陷必带代码位置

    ok_n = {"cls": "non_quantifiable", "axis": "learnable", "quote": "x", "verdict": "TEACHING_JUDGMENT",
            "improvement": "改", "precedent": "读者卡在…", "steelman": "已反论"}
    assert _state.self_check_finding(ok_n) == []
    assert any("precedent" in p for p in _state.self_check_finding({**ok_n, "precedent": None}))
    assert any("steelman" in p for p in _state.self_check_finding({**ok_n, "steelman": None}))
    # 确认讲错必带外部反证,否则违规
    cw = {**ok_n, "verdict": "CONFIRMED_CONCEPT_WRONG"}
    assert any("external_evidence" in p for p in _state.self_check_finding(cw))


# ---- render:自校验闸把无证据的踢进「待补」;两段分开;轴档 ----

def test_render_two_sections_and_gate(tmp_path, monkeypatch):
    _redirect(monkeypatch, tmp_path)
    _state.save_meta("ops-x", {"doc": "docs/zh/develop/g.md", "type": "教学型", "audience": "已读 quickstart",
                               "code_root": "/x"})
    # 1 可量化确认(过闸) 1 教学判断(过闸) 1 无证据(踢待补)
    _state.add_finding("ops-x", {"cls": "quantifiable", "axis": "trustworthy", "form": "错",
                                 "source": "code_mismatch", "quote": "--opkernel_test", "verdict": "CONFIRMED_MISMATCH",
                                 "evidence_grade": "strong", "code_location": "build.sh:3", "improvement": "改成 --opkernel"})
    _state.add_finding("ops-x", {"cls": "non_quantifiable", "axis": "learnable", "form": "缺",
                                 "quote": "适当配置 tiling", "verdict": "TEACHING_JUDGMENT",
                                 "precedent": "读者不知 tiling 取值依据", "steelman": "上文未给公式",
                                 "improvement": "补 tiling 计算约束"})
    _state.add_finding("ops-x", {"cls": "quantifiable", "axis": "trustworthy", "quote": "无证据条",
                                 "verdict": "CONFIRMED_MISMATCH", "improvement": "x"})   # 缺 code_location → 待补
    md = render_report.render("ops-x")
    assert "事实问题" in md and "教学判断" in md
    assert "--opkernel_test" in md and "适当配置 tiling" in md
    assert "待补" in md and "无证据条" in md          # 无证据的被踢进待补,不进事实问题正文
    assert "不合格" in md                             # trustworthy 轴有 CONFIRMED → 不合格
