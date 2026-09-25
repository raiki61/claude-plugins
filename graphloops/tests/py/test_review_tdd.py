"""TDD の流れ（graphs/review-loop-tdd.json）の赤・緑の確認——rules/review-loop-tdd.py が JUnit XML をテスト 1 件ごとに読んで決める。
関数を直に呼ぶ検査。盤面を回す端から端までの台本は simulate_review.py の test_tdd_flow"""
import types

import pytest

from conftest import PLUGIN, REPO
from engine.rules import load_rules
from engine.schema import load_graph

GRAPH = PLUGIN / "graphs" / "review-loop-tdd.json"
RULES = load_rules(GRAPH, load_graph(GRAPH)[0])

# pytest --junitxml の形（rootdir が tests/py のとき classname は "test_x"、リポジトリの根なら "tests.py.test_x"）
JUNIT = """<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">
<testcase classname="test_a" name="test_new_red"><failure message="assert 1 == 2">AssertionError</failure></testcase>
<testcase classname="test_a" name="test_old_green"/>
<testcase classname="pkg.test_b.TestK" name="test_param[x]"><error message="fixture boom">E</error></testcase>
<testcase classname="test_a" name="test_skipped"><skipped message="why"/></testcase>
</testsuite></testsuites>"""


def cases(**over):
    got = RULES.parse_junit(JUNIT)
    for c in got:
        c["outcome"] = over.get(c["name"], c["outcome"])
    return got


def test_parse_junit_reads_each_outcome():
    got = {c["name"]: c["outcome"] for c in RULES.parse_junit(JUNIT)}
    assert got == {"test_new_red": "failure", "test_old_green": "passed", "test_param[x]": "error", "test_skipped": "skipped"}


@pytest.mark.parametrize("test_id,name", [
    pytest.param("test_a.py::test_new_red", "test_new_red", id="rootdir-relative"),
    pytest.param("graphloops/tests/py/test_a.py::test_new_red", "test_new_red", id="repo-relative"),
    pytest.param("src/pkg/test_b.py::TestK::test_param[x]", "test_param[x]", id="class-and-param"),
])
def test_match_case_finds_the_named_test(test_id, name):
    assert RULES.match_case(test_id, RULES.parse_junit(JUNIT))["name"] == name


@pytest.mark.parametrize("test_id", [
    pytest.param("test_other.py::test_new_red", id="other-module"),
    pytest.param("test_a.py::test_missing", id="other-name"),
])
def test_match_case_does_not_guess(test_id):
    assert RULES.match_case(test_id, RULES.parse_junit(JUNIT)) is None


def test_red_passes_when_named_fail_and_others_pass():
    assert RULES.red_problems(["test_a.py::test_new_red"], cases(**{"test_param[x]": "passed"}), 1) == []


@pytest.mark.parametrize("outcome,words", [
    pytest.param("error", "error で落ちた", id="load-or-setup-error"),
    pytest.param("passed", "もう通る", id="already-green"),
    pytest.param("skipped", "飛ばされた", id="skipped"),
])
def test_red_rejects_the_wrong_kind_of_red(outcome, words):
    probs = RULES.red_problems(["test_a.py::test_new_red"], cases(**{"test_new_red": outcome, "test_param[x]": "passed"}), 1)
    assert any(words in p for p in probs)


def test_red_rejects_a_named_test_missing_from_the_suite():
    probs = RULES.red_problems(["test_a.py::test_never_collected"], cases(**{"test_param[x]": "passed"}), 1)
    assert any("一式の結末に居ない" in p for p in probs)


def test_red_rejects_other_tests_broken():
    probs = RULES.red_problems(["test_a.py::test_new_red"], cases(), 1)
    assert any("test_param[x]" in p and "ほか" in p for p in probs)


def test_red_rejects_exit_zero():
    probs = RULES.red_problems(["test_a.py::test_new_red"], cases(**{"test_param[x]": "passed"}), 0)
    assert any("exit 0" in p for p in probs)


def test_green_passes_only_when_everything_passes():
    assert RULES.green_problems(["test_a.py::test_new_red"], cases(**{"test_new_red": "passed", "test_param[x]": "passed"}), 0) == []


def test_green_rejects_named_still_red_and_nonzero_exit():
    probs = RULES.green_problems(["test_a.py::test_new_red"], cases(**{"test_param[x]": "passed"}), 1)
    assert any("test_new_red" in p and "緑でない" in p for p in probs) and any("exit 1" in p for p in probs)


def test_red_and_green_ignore_tests_already_red_at_the_round_head():
    """『ほかは緑のまま』は元の結末で通っていたテスト（SWE-bench の PASS_TO_PASS）——周の頭で赤い一式でも必ず落ちる形にしない"""
    baseline = {"pkg.test_b.TestK::test_param[x]": "error", "test_a::test_old_green": "passed"}
    assert RULES.red_problems(["test_a.py::test_new_red"], cases(), 1, baseline) == []
    assert RULES.green_problems(["test_a.py::test_new_red"], cases(test_new_red="passed"), 1, baseline, baseline_exit=1) == []
    probs = RULES.red_problems(["test_a.py::test_new_red"], cases(test_old_green="failure"), 1, baseline)
    assert any("test_old_green" in p for p in probs)


def test_green_keeps_exit_zero_when_the_suite_was_green_before():
    probs = RULES.green_problems(["test_a.py::test_new_red"], cases(test_new_red="passed", **{"test_param[x]": "passed"}), 1, {}, baseline_exit=0)
    assert any("exit 1" in p for p in probs)


def test_tdd_rules_extend_the_default_rules_without_changing_them():
    """TDD の rules は今の流れの rules の公開名を全部そのまま出し、差し替えるのは名乗った物だけ——フックや表の出し忘れは
    engine から見ると『このループは持たない』に黙って倒れるので、名前を選んで並べていないことを見る"""
    base = RULES.base
    replaced = {"record_round", "finalize", "on_new_round", "CONDS", "BUILTINS", "POST_CHECKS", "LOOP_KEYS"}
    public = {k for k in vars(base) if not k.startswith("__")}
    assert not public - set(vars(RULES))
    assert [k for k in public - replaced if getattr(RULES, k) is not getattr(base, k)] == []
    assert all(RULES.BUILTINS[k] is v for k, v in base.BUILTINS.items() if k != "record_round")
    assert all(RULES.CONDS[k] is v for k, v in base.CONDS.items())
    assert all(RULES.POST_CHECKS[k] is v for k, v in base.POST_CHECKS.items())
    assert set(RULES.BUILTINS) - set(base.BUILTINS) == {"tdd_start", "tdd_red", "tdd_green"}
    assert RULES.LOOP_KEYS - base.LOOP_KEYS == {"tdd", "tdd_gave_up"} and base.LOOP_KEYS <= RULES.LOOP_KEYS


# --- テストだけを書く段の返答の検査（tdd_tests_output）: 直す義務の単位を全部 1 度だけ tdd か direct に振る
UNITS = [{"key": "u-block", "label": "block"}, {"key": "u-donow", "label": "suggest", "disposition": "do-now"}]
BOARD = types.SimpleNamespace(state={"validator": str(REPO / "scripts" / "review-record.py")},
                              record={"units": UNITS, "questions": []})
OK_FRICTION = {"setup_heavy": False, "reaches_internals": False, "name_unclear": False}


def tdd_row(**kw):
    return {"unit_key": "u-block", "route": "tdd", "tests": ["t.py::test_x"], "friction": OK_FRICTION, **kw}


def direct_row(**kw):
    return {"unit_key": "u-donow", "route": "direct", "why": "注記だけの直しで、先に落とせるテストが無い", **kw}


def check_reply(units):
    try:
        RULES.POST_CHECKS["tdd_tests_output"](BOARD, "p3.tdd_tests", {"units": units, "test_files": ["t.py"]}, None)
        return ""
    except RULES.Reject as e:
        return str(e)


def test_tests_reply_accepts_every_unit_routed_once():
    assert check_reply([tdd_row(), direct_row()]) == ""


@pytest.mark.parametrize("units,words", [
    pytest.param([tdd_row()], "どちらの道にも振っていない", id="unit-left-out"),
    pytest.param([tdd_row(tests=[]), direct_row()], "名指しのテストが無い", id="tdd-without-tests"),
    pytest.param([tdd_row(), direct_row(why="")], "理由", id="direct-without-why"),
    pytest.param([tdd_row(friction={**OK_FRICTION, "setup_heavy": True}), direct_row()], "note", id="friction-without-note"),
    pytest.param([tdd_row(), direct_row(), direct_row()], "u-donow", id="unit-twice"),
])
def test_tests_reply_rejects(units, words):
    assert words in check_reply(units)


def test_tdd_conds_truth_table():
    """TDD の節の条件（rules の関数）: 赤の確認は名指しのテストが在る周だけ、緑の確認はそのうえ赤の確認がこの周に通った周だけ"""
    from engine.board import COND_HEADS, run_cond

    def ev(name, cur=None, loop=None, rnd=2):
        ctx = {**{h: {} for h in COND_HEADS}, "round": rnd, "cur": cur or {}, "loop": loop or {}}
        return run_cond(name, RULES.CONDS[name], ctx)[0]
    named = {"p3.tdd_tests": {"units": [{"route": "tdd", "tests": ["t::a"]}, {"route": "direct", "tests": ["t::b"]}]}}
    direct = {"p3.tdd_tests": {"units": [{"route": "direct", "tests": ["t::b"]}]}}
    assert ev("tdd_named", named) and not ev("tdd_named", direct) and not ev("tdd_named")
    assert ev("tdd_red_passed", named, {"tdd": {"round": 2, "red": "passed"}})
    assert not ev("tdd_red_passed", named, {"tdd": {"round": 2, "red": "failed"}})
    assert not ev("tdd_red_passed", named, {"tdd": {"round": 2}})
    assert not ev("tdd_red_passed", named, {"tdd": {"round": 1, "red": "passed"}})
    assert not ev("tdd_red_passed", direct, {"tdd": {"round": 2, "red": "passed"}})


# --- 差し戻しと諦め（_retry・_give_up）: 盤面を手で組んで直に呼ぶ
def retry_board(fixes):
    calls = []
    b = types.SimpleNamespace(round=2, loop_state={}, record={"process": {"fixes": fixes}}, state={"inputs": {}},
                              rewind=lambda nodes, by: calls.append((tuple(nodes), by)))
    return b, calls


def test_green_retry_drops_this_rounds_fix_rows_and_rewinds_the_fix():
    """緑の確認が落ちて実装へ差し戻すとき、この周の修正の行（process.fixes）を外す——落ちた試行が残ると、どれを採ったか読めない"""
    b, calls = retry_board([{"round": 1, "n": "前の周"}, {"round": 2, "n": "落ちた試行"}])
    got = RULES._retry(b, RULES._tdd(b), "green", "p3.fix", ["名指しが緑でない"])
    assert got["ok"] is False and got["rewound"] == ["p3.fix"] and calls == [(("p3.fix",), "p3.tdd_green")]
    assert [r["round"] for r in b.record["process"]["fixes"]] == [1]


def test_red_retry_keeps_the_fix_rows():
    b, calls = retry_board([{"round": 2, "n": "この周"}])
    RULES._retry(b, RULES._tdd(b), "red", "p3.tdd_tests", ["赤でない"])
    assert [r["round"] for r in b.record["process"]["fixes"]] == [2] and calls == [(("p3.tdd_tests",), "p3.tdd_red")]


@pytest.mark.parametrize("step,back", [pytest.param("red", "p3.tdd_tests", id="red"), pytest.param("green", "p3.fix", id="green")])
def test_retry_gives_up_at_the_limit_without_stopping(step, back):
    """同じ周に RETRY_MAX 回落ちたら TDD を諦めて今の流れで進む（ok で返し、止めない）——理由は記録と次の周の判定役へ"""
    b, calls = retry_board([])
    t = RULES._tdd(b)
    got = [RULES._retry(b, t, step, back, [f"{step} の {i} 回目"]) for i in range(RULES.RETRY_MAX)]
    assert [g["ok"] for g in got] == [False] * (RULES.RETRY_MAX - 1) + [True]
    assert got[-1]["gave_up"] == step and len(calls) == RULES.RETRY_MAX - 1
    assert b.loop_state["tdd_gave_up"] == [{"round": 2, "step": step, "problems": [f"{step} の {RULES.RETRY_MAX - 1} 回目"]}]
    assert b.record["process"]["tdd"]["rounds"]["2"][step] == "failed"


def test_green_rejects_a_new_test_outside_the_baseline_that_fails():
    """元の結末に無いテスト（この周に足した名指しの外）は通っていなければならない——元から赤だった物だけを問わない"""
    baseline = {"test_a::test_old_green": "passed", "test_a::test_skipped": "skipped"}
    probs = RULES.green_problems(["test_a.py::test_new_red"], cases(test_new_red="passed"), 1, baseline, baseline_exit=1)
    assert any("test_param[x]" in p for p in probs)
