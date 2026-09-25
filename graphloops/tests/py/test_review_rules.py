"""review-loop の rules（rules/review-loop.py）の関数を直に呼ぶ検査——欄が欠けた・空の入力で落ちずに既定へ倒れるか、
倒れた理由を残すか。盤面は types.SimpleNamespace の偽物で、engine の道具（git・_repo_root）は monkeypatch で差し替える。
盤面を回す端から端までの台本は simulate_review.py"""
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
