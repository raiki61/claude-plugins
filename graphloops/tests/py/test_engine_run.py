"""走らせるだけの節（graph の engine_run）の部品——宣言の読み手（engine/declared.py）・走らせてよい語の柵
（commands.engine_run_refusal）・語を走らせる関数（role_run.run_steps）。関数を直に呼ぶ検査。盤面を回す端から端までの台本は
simulate_review.py の test_engine_run_checks・test_engine_run_parallel_pr"""
import importlib.util
import json
import subprocess
import sys
import types

import pytest

from conftest import PLUGIN
from engine import declared
from engine.advance import helper_argv, engine_run_entry, plan_engine_run
from engine.commands import engine_run_refusal
from engine.role_run import run_steps

OK = [{"name": "suite", "argv": [sys.executable, "-c", "print('ok')"]}]


def repo(tmp_path, steps=OK):
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    (tmp_path / declared.DECL_NAME).write_text(json.dumps({"suite": steps}), encoding="utf-8")
    return tmp_path


@pytest.mark.parametrize("text,want", [
    ("{", "JSON として読めない"),
    ('{"suite": [], "x": 1}', "最上位は"),
    ('{"suite": []}', "1 段以上"),
    ('{"suite": [{"name": "a"}]}', "suite[0] は"),
    ('{"suite": [{"name": "a", "argv": []}]}', "1 語以上"),
    ('{"suite": [{"name": "a", "argv": "bash run.sh"}]}', "1 語以上"),
    ('{"suite": [{"name": "a", "argv": ["x"]}, {"name": "a", "argv": ["y"]}]}', "重ならない"),
    ('{"sweet": []}', "在る鍵: ['sweet']"),   # 綴り違いの鍵を名指す（型の名前 dict だけでは直す所が分からない）
])
def test_parse_rejects_shapes_it_cannot_run(text, want):
    steps, err = declared.parse(text)
    assert steps is None and want in err


def test_sha_ignores_layout_but_not_content():
    a, _ = declared.parse('{"suite": [{"name": "a", "argv": ["x", "y"]}]}')
    b, _ = declared.parse('{ "suite" : [ { "argv": ["x","y"], "name":"a" } ] }')
    c, _ = declared.parse('{"suite": [{"name": "a", "argv": ["x", "z"]}]}')
    assert declared.steps_sha(a) == declared.steps_sha(b) != declared.steps_sha(c)


def test_refusal_runs_declared_steps_without_approval(tmp_path):
    """人の承認は要らない——ルートの宣言と一致する語はそのまま走らせてよい"""
    root = repo(tmp_path)
    inst = {"launch": {"kind": "engine_run", "steps": OK, "sha": declared.steps_sha(OK)}}
    assert engine_run_refusal(inst, root) is None


def test_refusal_rejects_steps_that_differ_from_root_declaration(tmp_path):
    root = repo(tmp_path)
    inst = {"launch": {"kind": "engine_run", "steps": OK, "sha": declared.steps_sha(OK)}}
    # 盤面の手当てで instance に語を書き足しても走らない
    bad = {"launch": {**inst["launch"], "steps": OK + [{"name": "evil", "argv": ["sh", "-c", "true"]}]}}
    assert "一致しない" in engine_run_refusal(bad, root)
    # emit の後に宣言が変わった・読めなくなった・消えた——古い instance の語は走らせず、relaunch で計画し直させる
    (root / declared.DECL_NAME).write_text(json.dumps({"suite": [{"name": "suite", "argv": ["other"]}]}), encoding="utf-8")
    assert "relaunch" in engine_run_refusal(inst, root)
    (root / declared.DECL_NAME).write_text("{", encoding="utf-8")
    assert "一致しない" in engine_run_refusal(inst, root)
    (root / declared.DECL_NAME).unlink()
    assert "一致しない" in engine_run_refusal(inst, root)


def test_refusal_reads_the_declaration_at_root_not_a_board_field(tmp_path):
    """突き合わせる宣言は呼び元が渡すルートの物だけ——盤面に書ける欄（launch.cwd）が指す別の場所の宣言は読まない"""
    root = repo(tmp_path / "repo")
    evil = [{"name": "evil", "argv": ["sh", "-c", "true"]}]
    elsewhere = repo(tmp_path / "elsewhere", steps=evil)
    inst = {"launch": {"kind": "engine_run", "steps": evil, "sha": declared.steps_sha(evil), "cwd": str(elsewhere)}}
    assert "一致しない" in engine_run_refusal(inst, root)
    assert engine_run_refusal(inst, elsewhere) is None


def test_refusal_exempts_only_the_bundled_helper_by_argv(tmp_path):
    """宣言の無いルートで確かめる——免除が効くのは argv の頭が engine の同梱の語を指すときだけ"""
    ok = {"launch": {"kind": "engine_run", "steps": [{"name": "parallel-pr.py", "argv": helper_argv("parallel-pr.py", ["--repo", "t/x"])}],
                     "sha": None}}
    assert not (tmp_path / declared.DECL_NAME).exists()
    assert engine_run_refusal(ok, tmp_path) is None
    # 名前だけ同梱の語を名乗り、別の置き場のスクリプトを指す語は免除されず、宣言との突き合わせに回る
    fake = {"launch": {**ok["launch"], "steps": [{"name": "parallel-pr.py", "argv": [sys.executable, str(tmp_path / "parallel-pr.py")]}]}}
    assert "一致しない" in engine_run_refusal(fake, tmp_path)
    assert "形が" in engine_run_refusal({"launch": {"steps": [{"name": "x", "argv": "bash"}]}}, tmp_path)


def _board_with(plan):
    return types.SimpleNamespace(rules=types.SimpleNamespace(ENGINE_RUNS={"x": {"plan": plan, "reply": None}}))


def test_engine_run_entry_refuses_unknown_builtin(capsys):
    with pytest.raises(SystemExit):
        engine_run_entry(_board_with(lambda b, nid: {}), {"engine_run": {"builtin": "nope"}})
    assert "ENGINE_RUNS に無い" in capsys.readouterr().err


def test_plan_runs_only_bundled_helpers(capsys):
    """同梱の語（ENGINE_HELPERS）は宣言に無くても走らせる。args の無い計画は引数なしの argv になる"""
    n = {"engine_run": {"builtin": "x"}}
    inst = {}
    plan_engine_run(_board_with(lambda b, nid: {"helper": "parallel-pr.py"}), "p0.x", n, inst)
    assert inst["mode"] == "engine_run" and inst["launch"]["steps"] == [{"name": "parallel-pr.py", "argv": helper_argv("parallel-pr.py")}]
    with pytest.raises(SystemExit):
        plan_engine_run(_board_with(lambda b, nid: {"helper": "evil.sh"}), "p0.x", n, {})
    assert "ENGINE_HELPERS に無い" in capsys.readouterr().err


def test_parallel_pr_stops_when_gh_fails(monkeypatch, capsys):
    """gh が非 0 なら、標準出力が JSON に見えても使わず、理由を標準エラーに書いて exit 1"""
    spec = importlib.util.spec_from_file_location("parallel_pr", PLUGIN / "scripts" / "parallel-pr.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    monkeypatch.setattr(mod, "GH", sys.executable)
    with pytest.raises(SystemExit) as e:
        mod.gh("-c", "import sys; sys.stdout.write('[]'); sys.stderr.write('boom'); sys.exit(3)")
    assert e.value.code == 1 and "が exit 3: boom" in capsys.readouterr().err


def test_run_steps_waits_and_keeps_output(tmp_path):
    steps = [{"name": "slow", "argv": [sys.executable, "-c", "import time; time.sleep(1); print('done 572')"]},
             {"name": "red", "argv": [sys.executable, "-c", "import sys; sys.stderr.write('boom'); sys.exit(4)"]},
             {"name": "missing", "argv": ["no-such-command-gl-test"]}]
    runs = run_steps(steps, str(tmp_path), tmp_path / "log")
    assert [r["exit"] for r in runs] == [0, 4, None]
    assert (tmp_path / "log" / "1.out").read_text(encoding="utf-8").strip() == "done 572"   # 走り終えてから読む
    assert "boom" in runs[1]["tail"] and runs[2].get("error")
