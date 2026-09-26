"""TDD の流れ（graphs/review-loop-tdd.json）の赤・緑の確認——rules/review-loop-tdd.py が JUnit XML をテスト 1 件ごとに読んで決める。
関数を直に呼ぶ検査。盤面を回す端から端までの台本は simulate_review.py の test_tdd_flow"""
import json
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


def test_parse_junit_fills_missing_attributes_with_empty_text():
    """classname・name の無い行も文字列で持つ（match_case・_key が文字列として切る）"""
    assert RULES.parse_junit("<testsuite><testcase/></testsuite>") == [{"classname": "", "name": "", "outcome": "passed"}]


def test_run_suite_without_the_suite_input_reports_a_problem(tmp_path, monkeypatch):
    """実行ファイルの入力が無い盤面でも、例外で落ちずに『走らせられない』を返す"""
    monkeypatch.setattr(RULES, "repo_root", lambda git: str(tmp_path))
    cases_, code, why = RULES.run_suite(types.SimpleNamespace(state={"inputs": {}}))
    assert cases_ is None and code is None and "走らせられない" in why[0]


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


def test_green_rejects_named_test_missing_or_skipped():
    """名指しのテストが一式に居ない・飛ばされた——failure・error でないので『ほか』の行は拾わない。名指しの行だけが止める"""
    others = {"test_param[x]": "passed"}
    probs = RULES.green_problems(["test_a.py::test_never_collected"], cases(test_new_red="passed", **others), 0)
    assert probs == ["test_a.py::test_never_collected: 一式の結末に居ない——名指しのテストが緑でない"]
    probs = RULES.green_problems(["test_a.py::test_skipped"], cases(test_new_red="passed", **others), 0)
    assert probs == ["test_a.py::test_skipped: skipped——名指しのテストが緑でない"]


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
    replaced = {"record_round", "finalize", "on_new_round", "CONDS", "BUILTINS", "POST_CHECKS", "LOOP_KEYS", "HIST"}
    public = {k for k in vars(base) if not k.startswith("__")}
    assert not public - set(vars(RULES))
    assert [k for k in public - replaced if getattr(RULES, k) is not getattr(base, k)] == []
    assert all(RULES.BUILTINS[k] is v for k, v in base.BUILTINS.items() if k != "record_round")
    assert all(RULES.CONDS[k] is v for k, v in base.CONDS.items())
    assert all(RULES.POST_CHECKS[k] is v for k, v in base.POST_CHECKS.items())
    assert set(RULES.BUILTINS) - set(base.BUILTINS) == {"tdd_start", "tdd_red", "tdd_green"}
    assert RULES.LOOP_KEYS - base.LOOP_KEYS == {"tdd"} and base.LOOP_KEYS <= RULES.LOOP_KEYS
    assert set(RULES.HIST) - set(base.HIST) == {"tdd_gave_up"}
    assert [k for k, v in base.HIST.items() if RULES.HIST[k] is not v] == ["prev_declared_faces"]


# --- テストだけを書く段の返答の検査（tdd_tests_output）: 直す義務の単位を全部 1 度だけ tdd か direct に振る
UNITS = [{"key": "u-block", "label": "block"}, {"key": "u-donow", "label": "suggest", "disposition": "do-now"}]
BOARD = types.SimpleNamespace(state={"validator": str(REPO / "scripts" / "review-record.py")},
                              record={"units": UNITS, "questions": []}, loop_state={}, round=1)
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
    # 書きにくさの旗を立てても、何が書きにくいか（note）を書けば通る
    noted = {**OK_FRICTION, "setup_heavy": True, "note": "盤面を組むのに git の版が 2 つ要る"}
    assert check_reply([tdd_row(friction=noted), direct_row()]) == ""


@pytest.mark.parametrize("units,words", [
    pytest.param([tdd_row()], "どちらの道にも振っていない", id="unit-left-out"),
    pytest.param([tdd_row(tests=[]), direct_row()], "名指しのテストが無い", id="tdd-without-tests"),
    pytest.param([tdd_row(), direct_row(why="")], "理由", id="direct-without-why"),
    pytest.param([tdd_row(friction={**OK_FRICTION, "setup_heavy": True}), direct_row()], "note", id="friction-without-note"),
    pytest.param([tdd_row(), direct_row(), direct_row()], "u-donow", id="unit-twice"),
    pytest.param(None, "どちらの道にも振っていない", id="no-units"),
    pytest.param([tdd_row(), direct_row(), direct_row(unit_key="u-other")], "今の周に直す義務の単位に無い", id="unknown-unit"),
])
def test_tests_reply_rejects(units, words):
    assert words in check_reply(units)


def test_tests_reply_answers_against_the_shown_rows(monkeypatch):
    """義務の単位は修正の側に見せた行（loop.fix_units の owed）から引く——見せた後に記録が変わっても、答え合わせは見せた値で行う"""
    monkeypatch.setattr(BOARD, "loop_state", {"fix_units": {"round": 1, "rows": [{"key": "u-block", "owed": True},
                                                                                  {"key": "u-donow", "owed": False}]}})
    assert check_reply([tdd_row()]) == ""
    assert "今の周に直す義務の単位に無い" in check_reply([tdd_row(), direct_row()])


def test_tdd_conds_truth_table():
    """TDD の節の条件（rules の関数）: 赤の確認は名指しのテストが在る周だけ、緑の確認はそのうえ赤の確認がこの周に通った周だけ"""
    from engine.board import COND_HEADS, run_cond

    def ev(name, cur=None, loop=None, rnd=2):
        ctx = {**{h: {} for h in COND_HEADS}, "round": rnd, "cur": cur or {}, "loop": loop or {}}
        return run_cond(name, RULES.CONDS[name], ctx)[0]
    named = {"p3.tdd_tests": {"units": [{"route": "tdd", "tests": ["t::a"]}, {"route": "direct", "tests": ["t::b"]}]}}
    direct = {"p3.tdd_tests": {"units": [{"route": "direct", "tests": ["t::b"]}]}}
    assert ev("tdd_named", named) and not ev("tdd_named", direct) and not ev("tdd_named")
    assert not ev("tdd_named", {"p3.tdd_tests": {"units": [{"route": "tdd"}]}})   # tests の欄の無い行は 0 件と数える
    assert not ev("tdd_red_passed", named)   # 盤面にまだ loop.tdd が無い
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
    assert "tdd_gave_up" not in b.loop_state   # 諦めた事実は節の出力が正本——hist が出力から作る
    want = [{"round": 2, "step": step, "problems": [f"{step} の {RULES.RETRY_MAX - 1} 回目"]}]
    h = types.SimpleNamespace(round=3, output=lambda nid, n: got[-1] if (nid, n) == (f"p3.tdd_{step}", 2) else None)
    assert RULES.hist_tdd_gave_up(h) == want
    assert b.record["process"]["tdd"]["rounds"]["2"][step] == "failed"


def test_green_rejects_a_new_test_outside_the_baseline_that_fails():
    """元の結末に無いテスト（この周に足した名指しの外）は通っていなければならない——元から赤だった物だけを問わない"""
    baseline = {"test_a::test_old_green": "passed", "test_a::test_skipped": "skipped"}
    probs = RULES.green_problems(["test_a.py::test_new_red"], cases(test_new_red="passed"), 1, baseline, baseline_exit=1)
    assert any("test_param[x]" in p for p in probs)


# --- 赤・緑の確認の節（tdd_red・tdd_green）: 版と差分と一式を差し替えて直に呼ぶ（git と実行器を使わない）
NAMED_REPLY = {"units": [{"unit_key": "u-block", "route": "tdd", "tests": ["test_a.py::test_new_red"]}], "test_files": ["test_a.py"]}


def check_board(monkeypatch, out, changed, cases_, code):
    monkeypatch.setattr(RULES, "_snap", lambda: "rev")
    monkeypatch.setattr(RULES, "_diff_names", lambda frm, to: changed)
    monkeypatch.setattr(RULES, "run_suite", lambda b: (cases_, code, []))
    return types.SimpleNamespace(round=2, loop_state={}, record={"process": {}}, state={"inputs": {}},
                                 output_of_round=lambda nid, rnd: out, rewind=lambda nodes, by: None)


@pytest.mark.parametrize("out,changed,words", [
    pytest.param(None, [], "名指しのテストが無い", id="no-reply"),
    pytest.param(NAMED_REPLY, None, "テストを書く前の版からの差が取れない", id="no-diff"),
])
def test_red_check_rewinds_instead_of_crashing(monkeypatch, out, changed, words):
    b = check_board(monkeypatch, out, changed, cases(**{"test_param[x]": "passed"}), 1)
    got = RULES.tdd_red(b, "p3.tdd_red")
    assert got["ok"] is False and words in got["problems"], got


def test_green_check_without_reply_or_named_passes_on_a_green_suite(monkeypatch):
    """返答も赤の確認の名指しも無い盤面で、一式が緑なら通す（読めない欄で落ちない）"""
    b = check_board(monkeypatch, None, [], cases(test_new_red="passed", **{"test_param[x]": "passed"}), 0)
    assert RULES.tdd_green(b, "p3.tdd_green") == {"ok": True}


def test_green_check_rejects_when_the_diff_is_unknown(monkeypatch):
    b = check_board(monkeypatch, NAMED_REPLY, None, cases(test_new_red="passed", **{"test_param[x]": "passed"}), 0)
    got = RULES.tdd_green(b, "p3.tdd_green")
    assert got["ok"] is False and "赤を確かめた版からテストのファイルの差が取れない" in got["problems"], got


# --- 効き目の記録（tdd_effect）: 線の結果と次の周の記録を置き場に置いて直に呼ぶ
def test_tdd_effect_counts_only_clean_lane_results(tmp_path, monkeypatch):
    def board(process, loop_state=None):
        return types.SimpleNamespace(record={"process": process}, loop_state=loop_state or {}, dir=tmp_path)
    RULES.tdd_effect(board({}))                      # TDD の記録がまだ無い run（finalize が呼ぶ）
    RULES.tdd_effect(board({"tdd": {"suite": "s"}}))  # 周の行がまだ無い
    results = {1: ({"arms": [{"arm": "a1"}]}, []),                     # 証拠の欠けた腕が 1 本
               2: ({"arms": [{"arm": "a2"}]}, ["schema に合わない"]),  # 誤りのある結果は数えない
               3: ({"lane": "no arms"}, [])}                           # 腕の欄が無い結果は測れていない（None）
    monkeypatch.setattr(RULES.base, "_lane_result", lambda b, lane: results[lane["round"]])
    (tmp_path / "rounds").mkdir()
    (tmp_path / "rounds" / "round-2.json").write_text(json.dumps({"scalars": {"faces_created_by_prev_fix": 4}}), encoding="utf-8")
    (tmp_path / "rounds" / "round-3.json").write_text(json.dumps({"round": 3}), encoding="utf-8")   # scalars の無い周の記録
    rows = {"1": {}, "2": {}, "3": {}}
    lane = lambda i, state="running", **kw: {"round": i, "result": f"r{i}.json", "patch": "", "state": state, **kw}
    RULES.tdd_effect(board({"tdd": {"rounds": rows}}, {"lanes": {f"r{i}": lane(i) for i in (1, 2, 3)}}))
    assert rows == {"1": {"lane_missed": 1, "lane_arms": 1, "lane_state": "running", "faces_created_by_this_fix": 4},
                    "2": {"lane_missed": None, "lane_arms": None, "lane_state": "running", "faces_created_by_this_fix": None},
                    "3": {"lane_missed": None, "lane_arms": 0, "lane_state": "running", "faces_created_by_this_fix": None}}
    # 止めた線は結果を読まない（止めた後に届いた結果を数えない）。形の崩れた行（patch で丸ごと書き換えた）は線が無い扱い
    rows = {"1": {}, "2": {}}
    RULES.tdd_effect(board({"tdd": {"rounds": rows}}, {"lanes": {"r1": lane(1, "abandoned", why="回す側が止めた（検査用）"),
                                                                "r2": {"state": "abandoned", "why": "丸ごと書いた"}}}))
    assert rows["1"]["lane_state"] == "abandoned" and rows["1"]["lane_missed"] is None and rows["2"]["lane_state"] is None



def test_green_names_a_failing_named_test_once():
    """名指しのテストの失敗は『名指しが緑でない』の 1 行だけ——『ほかのテストが緑でない』に重ねて数えない（赤の確認と同じ）"""
    probs = RULES.green_problems(["test_a.py::test_new_red"], cases(**{"test_param[x]": "passed"}), 0)
    assert [p for p in probs if "test_new_red" in p] == [p for p in probs if "名指しのテストが緑でない" in p] and len(probs) == 1


def test_tdd_effect_reads_an_unfired_lane_as_unmeasured(tmp_path):
    """腕を 1 本も撃っていない線は、その周の lane_missed を 0（見逃し 0 本）でなく None（測れていない）にする"""
    import json
    res = tmp_path / "lane.json"
    res.write_text(json.dumps({"rev": "a" * 40, "arms": [], "handled": [], "patch": "", "suite": {"command": "x", "exit": 0}}), encoding="utf-8")
    b = types.SimpleNamespace(round=2, dir=tmp_path, state={"validator": str(REPO / "scripts" / "review-record.py")},
                              nodes=load_graph(GRAPH)[0]["nodes"],
                              record={"process": {"tdd": {"rounds": {"1": {}}}}},
                              loop_state={"lanes": {"a" * 40: {"round": 1, "rev": "a" * 40, "result": str(res), "state": "merged"}}})
    RULES.tdd_effect(b)
    assert b.record["process"]["tdd"]["rounds"]["1"]["lane_missed"] is None


def test_tdd_start_stops_without_a_base_revision(monkeypatch):
    """テストを書く前の版を固められない（git が動かない）なら、一式を走らせずに止める"""
    monkeypatch.setattr(RULES, "_snap", lambda: None)
    monkeypatch.setattr(RULES, "run_suite", lambda b: pytest.fail("版を固められないのに一式を走らせた"))
    b = types.SimpleNamespace(round=1, loop_state={}, record={"process": {}}, state={"inputs": {}})
    assert RULES.tdd_start(b, "p3.tdd_start") == {"ok": False, "problems": ["テストを書く前の版を固められない（git を確かめよ）"]}


def test_diff_names_needs_both_revisions(monkeypatch):
    """片方の版が固められていなければ差を取らない（None——『差が取れない』で止める側に倒す）"""
    monkeypatch.setattr(RULES, "git", lambda *a, **k: pytest.fail("版が無いのに git diff を打った"))
    assert RULES._diff_names(None, "b") is None and RULES._diff_names("a", None) is None


def test_run_and_note_accumulates_what_the_suite_made(monkeypatch):
    """一式が作ったファイルは試行をまたいで積み増す（前の試行の分を落とさない）"""
    monkeypatch.setattr(RULES, "_snap", lambda: "rev")
    monkeypatch.setattr(RULES, "run_suite", lambda b: ([], 0, []))
    monkeypatch.setattr(RULES, "_diff_names", lambda frm, to: ["new.log"])
    t = {"suite_made": ["old.log"]}
    RULES._run_and_note(types.SimpleNamespace(), t)
    assert t["suite_made"] == ["new.log", "old.log"]


def test_finalize_runs_the_base_finalize_then_measures(monkeypatch):
    """TDD の版の仕上げは、元の仕上げを済ませてから効き目を測る"""
    seen = []
    monkeypatch.setattr(RULES.base, "finalize", lambda b: seen.append("base"))
    monkeypatch.setattr(RULES, "tdd_effect", lambda b: seen.append("effect"))
    RULES.finalize(types.SimpleNamespace())
    assert seen == ["base", "effect"]


def test_record_round_measures_after_the_base_record(monkeypatch):
    """周の記録を組んだ後に効き目を測り直し、元の周の記録の返りをそのまま返す"""
    seen = []
    monkeypatch.setattr(RULES.base, "record_round", lambda b, nid: seen.append("base") or {"ok": True})
    monkeypatch.setattr(RULES, "tdd_effect", lambda b: seen.append("effect"))
    assert RULES.record_round(types.SimpleNamespace(), "p4.record") == {"ok": True} and seen == ["base", "effect"]


def test_run_suite_reports_a_suite_that_wrote_no_junit(tmp_path, monkeypatch):
    """実行ファイルが JUnit XML を書かずに終わったら、結末なしで終了コードと出力の末尾を理由に返す（読みに行って落ちない）"""
    exe = tmp_path / "suite.py"
    exe.write_text("import sys\nprint('ran without junit')\nsys.exit(3)\n", encoding="utf-8")
    monkeypatch.setattr(RULES, "repo_root", lambda git: str(tmp_path))
    cases_, code, why = RULES.run_suite(types.SimpleNamespace(state={"inputs": {RULES.SUITE_INPUT: str(exe)}}))
    assert cases_ is None and code == 3 and "JUnit XML を書かなかった（exit 3）" in why[0] and "ran without junit" in why[0]
