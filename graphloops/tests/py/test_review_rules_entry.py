"""review-loop の rules のうち、判定から入る入口（entry_opens）と空差分の拒否文（_take_diff）を関数で直に呼ぶ検査。
盤面を端から端まで回す検査（空差分で止まる・案内どおりの add で入口が開く）は tests/simulate_review.py に在る。"""
import json
import subprocess
import types

import pytest

from conftest import PLUGIN
from engine import util
from engine.rules import load_rules

GRAPH = PLUGIN / "graphs" / "review-loop.json"


@pytest.fixture(scope="module")
def rules():
    return load_rules(GRAPH, json.loads(GRAPH.read_text(encoding="utf-8")))


def _board(tmp_path, round_=1, p1="pending", process=None, base=None):
    return types.SimpleNamespace(round=round_, node_state=lambda nid: p1 if nid == "p1.worktree_before" else None,
                                 record={"process": process or {}, "base": base}, loop_state={}, dir=tmp_path)


def test_entry_opens_only_before_the_first_round_p1(rules, tmp_path):
    assert rules.entry_opens(_board(tmp_path))
    assert not rules.entry_opens(_board(tmp_path, round_=2))
    assert not rules.entry_opens(_board(tmp_path, p1="done"))


def test_empty_diff_after_the_fix_points_at_the_fix_not_the_base(rules, tmp_path, monkeypatch):
    """P3 の後の取り直し（接尾辞つき）で差分が空なら、BASE ではなく修正が全部戻した可能性を言う"""
    repo = tmp_path / "r"
    repo.mkdir()
    run = lambda *a: subprocess.run(["git", "-C", str(repo), "-c", "user.email=t@t", "-c", "user.name=t", *a], check=True,
                                    capture_output=True, text=True, encoding="utf-8").stdout
    run("init", "-q")
    (repo / "a.txt").write_text("a\n")
    run("add", ".")
    run("commit", "-q", "-m", "base")
    head = run("rev-parse", "HEAD").strip()
    monkeypatch.setattr(util, "GIT_CWD", str(repo))
    monkeypatch.setattr(rules, "_freeze_revision", lambda b: head)
    after = rules._take_diff(_board(tmp_path, round_=2, p1="done", base=head), "-after-fix")
    assert not after["ok"] and "全部戻した" in after["problems"][0]
    first = rules._take_diff(_board(tmp_path, round_=2, p1="done", base=head))
    assert not first["ok"] and "BASE を確かめよ" in first["problems"][0] and "全部戻した" not in first["problems"][0]
