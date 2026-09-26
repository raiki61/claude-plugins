"""review-loop の rules（rules/review-loop.py）の関数を直に呼ぶ検査——欄が欠けた・空の入力で落ちずに既定へ倒れるか、
倒れた理由を残すか。盤面は types.SimpleNamespace の偽物で、engine の道具（git・_repo_root）は monkeypatch で差し替える。
盤面を回す端から端までの台本は simulate_review.py"""
import ast
import pathlib
import types

import pytest

from conftest import PLUGIN, REPO
from engine.rules import load_rules
from engine.schema import load_graph
from engine.util import Reject

GRAPH = PLUGIN / "graphs" / "review-loop.json"
RULES = load_rules(GRAPH, load_graph(GRAPH)[0])
VALIDATOR = str(REPO / "scripts" / "review-record.py")


def board(tmp_path, *, outputs=None, latest=None, record=None, loop_state=None, inputs=None, rnd=1, max_rounds=5):
    """rules が読む分だけの盤面の偽物。outputs は周の出力（output_of_round）、latest は最新の出力（latest_output）"""
    outputs, latest = outputs or {}, latest or {}
    rec = {"base": None, "materials": {}, "units": [], "questions": [], "process": {}}
    rec.update(record or {})
    return types.SimpleNamespace(
        round=rnd, dir=tmp_path, record=rec, loop_state=dict(loop_state or {}),
        state={"validator": VALIDATOR, "max_rounds": max_rounds, "inputs": dict(inputs or {})},
        output_of_round=lambda nid, r: outputs.get(nid), latest_output=lambda nid: latest.get(nid),
        cond=lambda name, overlay=None: (name == RULES.ENTRY_BUILTIN, "偽物"))


def fake_git(table):
    """git の偽物: 引数の頭の組が表に在ればその値、無ければ None（git の『失敗なら None』の契約）"""
    def git(*args, env=None):
        for head, out in table.items():
            if args[:len(head)] == head:
                return out
        return None
    return git


class View:
    """条件の関数に渡す v の偽物"""

    def __init__(self, vals):
        self.vals, self.unevaluated = vals, []

    def __call__(self, path, default=None):
        return self.vals.get(path, default)

    def unevaluable(self, name, why):
        self.unevaluated.append((name, why))


# ---------------------------------------------------------------- 目的の出典（purpose_sources_changed）
def test_purpose_sources_without_output_is_unevaluable():
    v = View({})
    ok, why = RULES.purpose_sources_changed(v)
    assert ok is False and "source_files が無い" in why and v.unevaluated


def test_purpose_sources_without_prev_fix_files_is_untouched():
    ok, why = RULES.purpose_sources_changed(View({"out.p0.purpose": {"source_files": ["README.md"]}}))
    assert (ok, why) == (False, "前の周の P3 は目的の出典を触っていない")


# ---------------------------------------------------------------- 収束（converge）の CI の自己申告
def test_converge_asks_when_ci_clean_without_any_checks_note(tmp_path):
    b = board(tmp_path, outputs={"p4.record": {"branch": "converged"}},
              record={"materials": {"local_checks": {"status": "clean"}}})
    got = RULES.converge(b, "p4.converge")
    assert got["decision"] == "ask" and got["ask"]["kinds"] == ["ci_unverified"]
    assert "この周の p4.ci を engine が走らせていない" in got["ask"]["question"]
    assert got["ask"]["items"] == ["local_checks: clean（任せ先の申告）— "]


# ---------------------------------------------------------------- 規模の数値（scalars・_comment_ratio）
def script(tmp_path, body):
    d = tmp_path / "scripts"
    d.mkdir(exist_ok=True)
    (d / "comment-ratio.sh").write_text(body, encoding="utf-8")
    return str(d)


def test_scalars_without_cut_or_base_records_why(tmp_path):
    b = board(tmp_path)
    got = RULES.scalars(b, "p4.scalars")
    assert got["unmeasured"] == ["この周の最後の版（p3.gates_cut）か BASE が無い"] and got["scalars"] == {}
    assert b.record["process"]["scalars_unmeasured"] == {"1": "この周の最後の版（p3.gates_cut）か BASE が無い"}


def test_scalars_records_why_when_numstat_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(RULES, "git", fake_git({}))   # _repo_root も git の diff も引けない
    b = board(tmp_path, record={"base": "b" * 40}, loop_state={"gates_cut": {"round": 1, "rev": "c" * 40}},
              inputs={"scripts_dir": script(tmp_path, "echo 'scalars: added_lines=3 comment_lines=1 comment_ratio_pct=33'\n")})
    got = RULES.scalars(b, "p4.scalars")
    assert got["scalars"] == {"added_lines": 3, "comment_lines": 1, "comment_ratio_pct": 33}
    assert got["unmeasured"] == [f"git diff --numstat {'b' * 12} {'c' * 12} が取れない（doc_lines）"]


def test_comment_ratio_without_scripts_dir_reports_exit(tmp_path, monkeypatch):
    monkeypatch.setattr(RULES, "_repo_root", lambda: str(tmp_path))
    got, why = RULES._comment_ratio(board(tmp_path), "b" * 40, "c" * 40)
    assert got == {} and why.startswith("comment-ratio.sh が exit ")


def test_comment_ratio_failure_with_empty_stderr_shows_stdout(tmp_path, monkeypatch):
    monkeypatch.setattr(RULES, "_repo_root", lambda: str(tmp_path))
    b = board(tmp_path, inputs={"scripts_dir": script(tmp_path, "echo 標準出力の末尾; exit 3\n")})
    assert RULES._comment_ratio(b, "b" * 40, "c" * 40) == ({}, "comment-ratio.sh が exit 3: 標準出力の末尾")


# ---------------------------------------------------------------- CI を engine が走らせた返答（checks_reply）
AWAITING = [{"kind": "awaiting", "status": "held", "origin": "local_checks", "key": "CI を人が確かめる"}]


@pytest.mark.parametrize("launch,runs,words", [
    pytest.param({"sha": "a" * 40}, [{"name": "t", "exit": 0, "wall_s": 1}], "走らせた結果: engine が宣言", id="clean-checked"),
    pytest.param({"sha": "a" * 40}, [{"name": "t", "exit": 1, "wall_s": 1, "tail": "赤の末尾"}], "t の末尾: 赤の末尾", id="found-detail"),
    pytest.param({"blocked": "承認されていない"}, [], "走らせた結果: 承認されていない", id="blocked-reason"),
])
def test_checks_reply_keeps_result_under_awaiting_question(tmp_path, launch, runs, words):
    b = board(tmp_path, record={"questions": AWAITING})
    m = RULES.checks_reply(b, "p4.ci", launch, runs)["reply"]["material"]
    assert m["status"] == "awaiting_human" and words in m["reason"]


@pytest.mark.parametrize("launch,runs,words", [
    pytest.param({"blocked": "宣言が読めない"}, [], "宣言が読めない", id="blocked"),
    pytest.param({"sha": "a" * 40}, [{"name": "t", "exit": None, "wall_s": 0, "error": "起こせない"}], "宣言の語を起こせない: t: 起こせない",
                 id="cannot-start"),
])
def test_checks_reply_before_judge_waits_for_human(tmp_path, launch, runs, words):
    """判定の前（p0.local_checks）に走らせられないときは人待ち。盤面の台帳は空にする——人待ちの問いが在ると、p4.ci の
    置き換えでも awaiting_human に戻り、p0 を p4 と取り違える退行が見えない"""
    m = RULES.checks_reply(board(tmp_path), "p0.local_checks", launch, runs)["reply"]["material"]
    assert m["status"] == "awaiting_human" and words in m["reason"]


# ---------------------------------------------------------------- 並行 PR（_github_repo・_pr_files・parallel_pr_*）
def test_github_repo_blank_upstream_falls_back_to_origin(monkeypatch):
    monkeypatch.setattr(RULES, "git", fake_git({("rev-parse",): " \n", ("remote", "get-url", "origin"): "https://github.com/o/r.git\n"}))
    assert RULES._github_repo() == ("o/r", None)


def entry_board(tmp_path):
    return board(tmp_path, record={"process": {"request_findings": [
        {"round": 1, "origin": "人", "findings": [{"where": "src/a.py: 3 行目", "text": "直せ"}]}]}})


def test_pr_files_takes_tracked_paths_named_by_where(tmp_path, monkeypatch):
    monkeypatch.setattr(RULES, "git", fake_git({("ls-files",): "src/a.py\0src/b.py\0"}))
    assert RULES._pr_files(entry_board(tmp_path)) == ["src/a.py"]


def test_pr_files_without_ls_files_is_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(RULES, "git", fake_git({}))
    assert RULES._pr_files(entry_board(tmp_path)) == []


def test_parallel_pr_plan_without_head_passes_empty(tmp_path, monkeypatch):
    monkeypatch.setattr(RULES, "git", fake_git({("rev-parse", "--abbrev-ref"): "origin/main\n",
                                                ("remote", "get-url", "origin"): "git@github.com:o/r.git\n"}))
    monkeypatch.setattr(RULES, "shutil", types.SimpleNamespace(which=lambda name: "/bin/" + name))
    (tmp_path / "changed.txt").write_text("src/a.py\n", encoding="utf-8")
    b = board(tmp_path, loop_state={"changed_files_file": str(tmp_path / "changed.txt")})
    got = RULES.parallel_pr_plan(b, "p0.parallel_pr")
    assert got["helper"] == "parallel-pr.py" and got["args"][:4] == ["--repo", "o/r", "--head", ""]


@pytest.mark.parametrize("run,words", [
    pytest.param({"exit": None, "error": "起こせない", "tail": "末尾"}, "（確かめられなかった）: 起こせない", id="error-first"),
    pytest.param({"exit": 2, "tail": "末尾"}, "（確かめられなかった）: 末尾", id="tail-without-error"),
])
def test_parallel_pr_reply_failed_run_shows_why(tmp_path, run, words):
    m = RULES.parallel_pr_reply(board(tmp_path), "p0.parallel_pr", {}, [run])["reply"]["material"]
    assert m["status"] == "awaiting_human" and m["reason"].endswith(words)


# ---------------------------------------------------------------- 修正案（fix_plan_covers_units）
def test_fix_plan_rejects_unknown_unit_key(tmp_path):
    b = board(tmp_path, record={"units": [{"key": "K1", "label": "block"}]})
    with pytest.raises(Reject, match="今の周に直す単位に無い key"):
        RULES.fix_plan_covers_units(b, "p2.fix_plan", {"plan": [{"unit_keys": ["K1", "写した key"]}]}, None)


# ---------------------------------------------------------------- 修正の入口（fix_units・_owed_shown）
UNITS = [{"key": "K1", "label": "block", "reason": "長い理由 1"}, {"key": "K2", "label": "suggest", "disposition": "do-now"},
         {"key": "K3", "label": "suggest", "disposition": "defer"}, {"key": "K4", "label": "block"}]
FORK = {"key": "Q1", "kind": "fork", "origin": "K4", "depends": [], "status": "held"}


def fix_board(tmp_path, questions=(FORK,), rnd=1):
    diag = {"units": [{"key": "K1", "why_chain": ["なぜ"], "class_query": {"how": {}}}, {"key": "K2"}]}
    return board(tmp_path, rnd=rnd, record={"units": [dict(u) for u in UNITS], "questions": [dict(q) for q in questions],
                                            "process": {"diagnosis": diag}})


def test_fix_units_rows_keep_record_order_and_mark_owed(tmp_path):
    b = fix_board(tmp_path)
    got = RULES.fix_units(b, "p2.fix_units")
    rows = b.loop_state["fix_units"]["rows"]
    assert got == {"ok": True, "units": 4, "owed": 2} and b.loop_state["fix_units"]["round"] == 1
    assert [r["key"] for r in rows] == ["K1", "K2", "K3", "K4"]
    assert [r["owed"] for r in rows] == [True, True, False, False]
    assert [r["has_class_query"] for r in rows] == [True, False, False, False]
    assert all(set(r) <= {"key", "label", "disposition", "owed", "has_class_query"} for r in rows)


def test_fix_units_owes_the_origin_of_a_decided_fork(tmp_path):
    b = fix_board(tmp_path, questions=({**FORK, "status": "resolved"},))
    RULES.fix_units(b, "p2.fix_units")
    assert [r["owed"] for r in b.loop_state["fix_units"]["rows"]] == [True, True, False, True]


def test_fix_acceptance_answers_against_the_shown_rows(tmp_path):
    b = fix_board(tmp_path)
    RULES.fix_units(b, "p2.fix_units")
    b.record["questions"] = []   # 見せた後に台帳が変わっても、答え合わせは見せた値で行う（今の台帳なら K4 も義務）
    assert RULES._owed_shown(b) == {"K1", "K2"}
    RULES.fix_plan_covers_units(b, "p2.fix_plan", {"plan": [{"unit_keys": ["K1", "K2"]}]}, None)
    b.record["questions"] = [{**FORK, "origin": "K2"}]   # 今の台帳なら K2 は待ってよいが、見せた行では義務
    with pytest.raises(Reject, match="K2"):
        RULES.fix_covers_open_units(b, "p3.fix", {"changes": [{"unit_key": "K1"}], "not_done": [{"unit_key": "K2", "why": "待つ"}]}, None)


def test_owed_shown_without_rows_of_this_round_reads_owed_units(tmp_path):
    b = fix_board(tmp_path, rnd=2)
    b.loop_state["fix_units"] = {"round": 1, "rows": [{"key": "K3", "owed": True}]}
    assert RULES._owed_shown(b) == RULES._owed_units(b) == {"K1", "K2"}


@pytest.mark.parametrize("graph, node", [("review-loop.json", "p2.fix_plan"), ("review-loop.json", "p3.fix"),
                                         ("review-loop-tdd.json", "p3.tdd_tests")])
def test_fix_side_prompts_paste_units_once(graph, node):
    """修正の側の指示書は単位の一覧を fix_units の行から 1 度だけ貼り、判定の写しは短い欄だけを貼る（長い本文は置き場を指す）"""
    from engine.render import node_prompt
    path = PLUGIN / "graphs" / graph
    n = load_graph(path)[0]["nodes"][node]
    body = node_prompt(path, n)
    assert "{{loop.fix_units.rows}}" in body and "{{record.units" not in body and "{{record.process.diagnosis}}" not in body
    assert all(p["from"] == ["loop.fix_units.rows"] for p in n["pointers"] if p["at"] != "plan_faces[].key")
    assert "p2.fix_units" in n["deps"]


# ---------------------------------------------------------------- 仕様の道（spec.*）
SPEC = {"requirements": [{"key": "R1", "text": "要件"}],
        "acceptance": [{"key": "A1", "requirement": "R1", "file": "t_spec.py", "name": "test_spec", "run": "true"}]}


@pytest.fixture
def no_repo(tmp_path, monkeypatch):
    """リポジトリのルートが引けない（_repo_root が None）——相対パスは今の作業場所から読む"""
    monkeypatch.setattr(RULES, "_repo_root", lambda: None)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "t_spec.py").write_text("def test_spec():\n    # Given\n    # When\n    # Then\n    pass\n", encoding="utf-8")
    return tmp_path


def test_spec_errors_reads_relative_to_cwd_without_repo(no_repo):
    assert RULES._spec_errors(SPEC) == []


def test_spec_errors_rejects_missing_test_name(no_repo):
    spec = {**SPEC, "acceptance": [{**SPEC["acceptance"][0], "name": "test_absent"}]}
    assert RULES._spec_errors(spec) == ["acceptance 'A1' の name 'test_absent' が t_spec.py に無い"]


@pytest.mark.parametrize("review", [pytest.param(None, id="no-review"), pytest.param({"faces": []}, id="no-faces")])
def test_spec_revise_output_without_review_faces(no_repo, review):
    RULES.spec_revise_output(board(no_repo, latest={"spec.review": review}), "spec.revise", {"handled": [], "spec": SPEC}, None)


def test_spec_approve_without_review_or_revise(no_repo):
    got = RULES.spec_approve(board(no_repo, latest={"spec.write": SPEC}), "spec.approve")
    assert got["decision"] == "ask" and len(got["ask"]["items"]) == 2


def test_on_answer_in_round_without_kinds(tmp_path):
    b = board(tmp_path)
    RULES.on_answer_in_round(b, {"node": "spec.approve"}, "continue")
    assert b.loop_state["in_round_answers"] == [{"round": 1, "node": "spec.approve", "kinds": [], "answer": "continue", "note": ""}]


def test_spec_freeze_without_repo(no_repo):
    b = board(no_repo, loop_state={"spec_pending": {"requirements": [], "acceptance": []}})
    assert RULES.spec_freeze(b, "spec.freeze") == {"ok": True}


def test_spec_check_without_repo(no_repo):
    b = board(no_repo, record={"process": {"spec": {"acceptance": []}}})
    assert RULES.spec_check(b, "spec.check") == {"ok": True}


# ---------------------------------------------------------------- 判定の受け付けで当てる検証器の規則（JUDGE_TIME_RULES・FAIL_LAYERS）
VAL = RULES.validator_module(board(pathlib.Path(".")))
LEDGER = {"defer_ledger": {"u1": {"reason": "構造的な理由", "round": 1}},
          "prev_questions": [{"key": "q0", "kind": "fork", "status": "held", "origin": "u1", "reason": "r", "options": ["a", "b"]}]}


def judge_reject(tmp_path, nid, out, loop_state=None):
    b = board(tmp_path, loop_state=loop_state, rnd=2)
    b.graph = load_graph(GRAPH)[0]
    with pytest.raises(Reject) as e:
        RULES.judge_output(b, nid, out, None)
    return str(e.value)


def reopened_block():
    return {"units": [{"key": "u1", "label": "block", "reason": "r"}], "questions": [], "one_shot_closes": ["u1"], "precedents": []}


def test_question_key_duplicate_rejected_at_judge(tmp_path):
    out = reopened_block()
    q = {"key": "q1", "kind": "fork", "status": "held", "origin": "u1", "reason": "r", "options": ["a", "b"]}
    out["questions"] = [q, dict(q)]
    assert "questions[1] の key が重複: q1" in judge_reject(tmp_path, "p2.diagnose", out)


# ---------------------------------------------------------------- 人が関所で直す義務の単位を外す（answer_detail）
GATE_UNITS = [{"key": "u1", "label": "block", "reason": "r"}, {"key": "u2", "label": "suggest", "disposition": "do-now", "reason": "r"}]


def test_human_excluded_units_leave_owed(tmp_path):
    rows = [{"round": 1, "node": "p2.human_gate", "answer": "continue", "excluded": [{"unit": "u1", "why": "人の理由"}]},
            {"round": 0, "node": "p2.human_gate", "answer": "continue", "excluded": [{"unit": "u2", "why": "前の周"}]}]
    b = board(tmp_path, record={"units": GATE_UNITS, "process": {"human_items": rows}})
    assert RULES._owed_units(b) == {"u2"}


@pytest.mark.parametrize("node,ans,detail,want", [
    pytest.param("p2.human_gate", "continue", {"exclude": [{"unit": 9, "why": "人の理由"}]}, "直す義務の単位でない", id="out-of-range"),
    pytest.param("p2.human_gate", "continue", {"exclude": [{"unit": "u1", "why": ""}]}, "理由（why）が無い", id="no-why"),
    pytest.param("p2.human_gate", "continue", {"exclude": [], "x": 1}, "--detail の形", id="shape"),
    pytest.param("r4.human_gate", "continue", {"exclude": [{"unit": "u1", "why": "人の理由"}]}, "p2.human_gate", id="other-gate"),
])
def test_answer_detail_rejects(tmp_path, node, ans, detail, want):
    b = board(tmp_path, record={"units": GATE_UNITS, "process": {"human_items": []}})
    with pytest.raises(Reject, match=want):
        RULES.answer_detail(b, {"node": node}, ans, detail)


def test_answer_detail_names_units_and_reaches_ledger(tmp_path):
    b = board(tmp_path, record={"units": GATE_UNITS, "process": {"human_items": []}})
    got = RULES.answer_detail(b, {"node": "p2.human_gate"}, "continue", {"exclude": [{"unit": 2, "why": "この周は\n触らない"}]})
    assert got == {"exclude": [{"unit": "u2", "why": "この周は 触らない"}]}
    RULES.human_gate_answered(b, {"node": "p2.human_gate", "items": [], "detail": got}, "continue")
    assert b.record["process"]["human_items"][-1]["excluded"] == got["exclude"] and RULES._owed_units(b) == {"u1"}


def test_fail_layers_cover_every_function_that_fails():
    tree = ast.parse(pathlib.Path(VALIDATOR).read_text(encoding="utf-8"))
    owners = set()
    for top in tree.body:
        name = top.name if isinstance(top, ast.FunctionDef) else "<module>"
        if any(isinstance(n, ast.Call) and getattr(n.func, "id", None) == "fail" for n in ast.walk(top)):
            owners.add(name)
    assert owners == set(VAL.FAIL_LAYERS), (sorted(owners - set(VAL.FAIL_LAYERS)), sorted(set(VAL.FAIL_LAYERS) - owners))


def test_judge_time_rules_are_called_by_rules():
    """判定の時点で当てると検証器が名乗る述語を、rules が呼んでいる（名乗りだけで届いていない形を落とす）"""
    src = (PLUGIN / "rules" / "review-loop.py").read_text(encoding="utf-8")
    for name in VAL.JUDGE_TIME_RULES:
        assert callable(getattr(VAL, name, None)), name
        assert f".{name}(" in src, f"rules が検証器の {name} を呼んでいない"


def test_settled_state_rejected_at_judge(tmp_path):
    out = reopened_block()
    out["questions"] = [{"key": "q1", "kind": "fork", "status": "resolved", "origin": "u1", "reason": "r", "resolution": "x",
                         "options": ["a", "b"]}]
    assert "出どころが [block] / do-now のまま resolved" in judge_reject(tmp_path, "p2.diagnose", out)


def test_history_rules_only_where_history_is_read(tmp_path):
    hist = judge_reject(tmp_path, "p2.history", reopened_block(), LEDGER)
    assert "reopen_evidence が無い: u1" in hist and "今ラウンドの台帳に無い: q0" in hist
    diag = judge_reject(tmp_path, "p2.diagnose", reopened_block(), LEDGER)
    assert "reopen_evidence" not in diag and "q0" not in diag


def test_rejudge_rejects_reopened_defer(tmp_path):
    b = board(tmp_path, loop_state=LEDGER, rnd=2)
    out = {"new_facts": "回す側が出した事実を、作業ツリーの現物を読み直して自分で確かめた", "verdict": "採る", **reopened_block()}
    with pytest.raises(Reject, match="reopen_evidence が無い: u1"):
        RULES.rejudge_output(b, "p2.rejudge", out, None)
    out["units"][0]["reopen_evidence"] = "新しい実測"
    RULES.rejudge_output(b, "p2.rejudge", out, None)


def test_history_rules_leave_machine_rows_to_record(tmp_path):
    b = board(tmp_path, loop_state={"prev_questions": [{"key": "R2 が取れない", "kind": "unverifiable", "origin": "R2", "status": "held",
                                                        "reason": "r"}]}, rnd=2)
    nd = load_graph(GRAPH)[0]["nodes"]["p2.history"]
    assert RULES._history_rules(b, VAL, nd, {"units": [], "questions": []}) == []


# ---------------------------------------------------------------- 人の修正依頼（add）の締め
def test_add_rejects_once_the_judge_node_left_pending_without_an_instance(tmp_path):
    """判定の節が待ちを抜けていれば（省いた・止めた等）、周に instance が残っていなくても add は拒む——
    instance の起き方だけで締めると、判定役がもう起きない周に依頼を積んでしまう"""
    b = board(tmp_path)
    b.node_state = lambda nid: "skipped" if nid == "p2.diagnose" else "pending"
    b.rd = {"instances": {}}
    with pytest.raises(Reject, match="既に起きている"):
        RULES.add(b, [{"where": "a.py:1", "text": "直せ"}], "人の依頼")


def test_add_rejects_once_the_judge_instance_left_pending(tmp_path):
    """判定の instance が待ちを抜けていれば（起こした印も返答のファイルも無くても）、add は拒む——
    役がもう入力を読んだかもしれない"""
    b = board(tmp_path)
    b.node_state = lambda nid: "pending"
    b.rd = {"instances": {"p2.diagnose": {"node": "p2.diagnose", "status": "done", "out_path": str(tmp_path / "無い.json")}}}
    with pytest.raises(Reject, match="既に起きている"):
        RULES.add(b, [{"where": "a.py:1", "text": "直せ"}], "人の依頼")


def test_after_first_round_without_a_round_is_false():
    """周の数が無い・数でない盤面では、落ちずに『2 周目以降でない』に倒れる"""
    for r in (None, "2"):
        ok, why = RULES.after_first_round(View({"round": r}))
        assert ok is False and f"round={r}" in why


def test_checks_plan_without_repo_falls_back_to_the_role(no_repo, tmp_path):
    """リポジトリのルートが引けなければ、宣言を探さずに任せ先へ落とし、その理由を言う"""
    assert RULES.checks_plan(board(tmp_path), "p0.local_checks") == {"fallback": "リポジトリのルートが引けない"}


@pytest.mark.parametrize("kind", ["regression", "policy"])
def test_delta_review_sends_human_kinds_to_the_gate(tmp_path, kind):
    """修正差分のレビューが人に聞く語（後退・方針とのぶつかり）を挙げたら、その語はこの節の物でないと返す——
    ファイルの照合まで流して別の理由で落とさない"""
    face = {"key": "k1", "kind": kind, "where": "a.py", "cite": "x", "why": "理由"}
    with pytest.raises(Reject) as e:
        RULES.delta_review_output(board(tmp_path), "p3.delta_review", {"faces": [face]}, None)
    assert "修正の後の後退" in str(e.value) and "修正が触ったファイルでない" not in str(e.value)


def test_finalize_writes_the_policy_change_after_the_last_gate(tmp_path, monkeypatch):
    """最後の関所の後に方針の文書が変わった run も、仕上げが変化を記録に書く。変化が無ければ前に書いた欄を消す"""
    b = board(tmp_path, record={"process": {"policy": {"path": "POLICY.md", "sha": "a"}}})
    b.state["status"] = "stopped"
    monkeypatch.setattr(RULES.policy_input, "change", lambda b, git, pol: {"before": "a", "after": "b"})
    RULES.finalize(b)
    assert b.record["process"]["policy_change"] == {"before": "a", "after": "b"}
    monkeypatch.setattr(RULES.policy_input, "change", lambda b, git, pol: None)
    RULES.finalize(b)
    assert "policy_change" not in b.record["process"]


def test_gates_merge_says_which_way_the_run_shoots():
    """合流でまとめる run はそう言い、そうでない run は『この run で撃つ』と言う——理由の文が真偽と食い違わない"""
    assert RULES.gates_merge(View({"loop.gates": "merge"})) == (True, RULES.GATES_MERGE_WHY)
    ok, why = RULES.gates_merge(View({}))
    assert ok is False and "この run で撃つ" in why


def test_not_request_entry_says_why_the_p1_roles_wait(monkeypatch):
    """判定から入る run の周なら、P1 の役を起こさないことを理由に足す。そうでない周は入口の理由をそのまま返す"""
    monkeypatch.setattr(RULES, "request_entry", lambda v: (True, "入口の印が在る"))
    assert RULES.not_request_entry(View({})) == (False, "入口の印が在るのため、P1 の役を起こさない")
    monkeypatch.setattr(RULES, "request_entry", lambda v: (False, "入口の印が無い"))
    assert RULES.not_request_entry(View({})) == (True, "入口の印が無い")


def test_parallel_pr_reply_blocked_launch_is_not_run(tmp_path):
    """走らせる前に止められた（blocked）なら、印字を読みに行かずに not_run と止めた理由で返す"""
    got = RULES.parallel_pr_reply(board(tmp_path), "p0.parallel_pr", {"blocked": "gh が無い"}, [])
    assert got["reply"]["material"] == {"status": "not_run", "reason": "gh が無い"} and got["reply"]["conflicts"] == []


def test_rejudge_exhausted_needs_an_objection_this_round():
    """往復が上限まで数えられていても、今の周に回す側の異議が無ければ第三の目を立てない"""
    ok, why = RULES.rejudge_exhausted(View({"round": 2, "loop.rejudge_rounds": {"round": 2, "n": RULES.REJUDGE_MAX}}))
    assert ok is False and "異議を出していない" in why


def test_spec_check_without_a_fixed_spec_says_so(tmp_path):
    """仕様が固定されていない記録では、落ちずに『仕様が無い』と返す"""
    got = RULES.spec_check(board(tmp_path), "spec.check")
    assert got["ok"] is False and "record.process.spec が無い" in got["problems"][0]


def test_sha_file_of_what_cannot_be_read_is_none(tmp_path):
    """通常のファイルでない・無いパスの sha256 は None——読めた物だけに sha を付ける"""
    (tmp_path / "f.txt").write_text("x", encoding="utf-8")
    assert RULES.sha_file(tmp_path) is None and RULES.sha_file(tmp_path / "無い") is None
    assert RULES.sha_file(tmp_path / "f.txt") == "2d711642b726b04401627ca9fbac32f5c8530fb1903cc4db02258717921a4881"


def test_spec_flow_says_which_way_the_run_goes():
    """仕様の道を選んだ run はそう言い、選んでいない run は今の流れのままと言う——理由の文が真偽と食い違わない"""
    assert RULES.spec_flow(View({"loop.flow": "spec"})) == (True, "仕様の道を選んだ run（flow=spec）")
    ok, why = RULES.spec_flow(View({}))
    assert ok is False and "今の流れのまま" in why
