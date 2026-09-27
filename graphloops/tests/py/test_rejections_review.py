"""review-loop の否定検査（graphloops/tests/simulate_review.py の test_rejections を、控えた波・1 手・手で書いた期待へ移した物）。

各テストは waves.py が控えた波から始め、1 手（next・done・launch・cmd）を打って期待を見る。移した元の check は
``moved_from`` の印が名乗り、台帳（ledger.py）が台本の check ごとの行き先を機械で組む。台本はまだ消していない（MIGRATION.md の T1）。
"""
import json
import os
import pathlib

import pytest
import waves

SRC = "simulate_review.test_rejections"
review = waves.review
M = review.M
pytestmark = pytest.mark.medium


def moved(head, **kw):
    return pytest.mark.moved_from(SRC, head, **kw)


def rejected(r, *words, absent=()):
    """exit 1 で拒み、拒否文に words が全部在り、absent が 1 つも無い"""
    assert r.returncode == 1, f"rc={r.returncode} {(r.stdout + r.stderr).strip()[-300:]}"
    missing = [w for w in words if w not in r.stderr]
    assert not missing, f"拒否文に {missing} が無い: {r.stderr.strip()[-300:]}"
    present = [w for w in absent if w in r.stderr]
    assert not present, f"拒否文に {present} が在る: {r.stderr.strip()[-300:]}"


def ready_by_node(nx):
    return {i["node"]: i for i in nx["ready"]}


# ---- P0 ------------------------------------------------------------------------------------------------------------

@moved("返答の置き場のディレクトリは engine が作る")
def test_out_path_directories_are_made_by_the_engine(wave):
    nx = wave("review/neg/init").run.next()
    assert nx["ready"]
    assert all(pathlib.Path(i["out_path"]).parent.is_dir() for i in nx["ready"])


@moved("宣言の在るリポジトリでは、走らせるだけの節は engine が走らせる節")
def test_declared_checks_run_as_an_engine_run_node(wave):
    by = ready_by_node(wave("review/neg/init").run.next())
    assert by["p0.local_checks"]["mode"] == "engine_run"
    assert "delegate" not in by["p0.local_checks"]


@moved("任せ先: graph が delegate を宣言した回す側の節は ready に任せ先が載り")
def test_undeclared_repo_falls_back_to_a_delegate(wave):
    by = ready_by_node(wave("review/nodecl/init").run.next())
    assert by["p0.local_checks"].get("delegate", {}).get("model") == "sonnet"
    assert "delegate" not in by["p0.base"]
    assert "が無い" in (by["p0.local_checks"].get("engine_fallback") or "")


@moved("実在しない BASE は exit 1")
def test_nonexistent_base_is_rejected(wave):
    w = wave("review/neg/p0")
    t = review.answers(w.run, "std", 1)
    r = w.run.done(w.pending()["p0.base"]["id"], {**t["p0.base"](None), "base_sha": "deadbeef"})
    rejected(r, "コミットでない")


@moved("機械の節（作業ツリーの写し）は ready に出ない")
def test_machine_nodes_are_not_ready(wave):
    by = ready_by_node(wave("review/neg/p0-settled").run.next())
    assert "p0.prior_decisions" in by
    assert "p1.worktree_before" not in by


@moved("loop.py record は record.json の丸写し",
       kept="子プロセスで起こした loop.py record の標準出力の文字コードと終了コード（台本が CLI の煙を置く唯一の所）")
def test_record_command_copies_record_json(wave):
    run = wave("review/neg/p0b").run
    assert run.record_cli() == run.record()


# ---- P1 ------------------------------------------------------------------------------------------------------------

@moved("P1 の役が同じ波に並ぶ")
def test_p1_roles_share_one_wave(wave):
    by = ready_by_node(wave("review/neg/p0b-settled").run.next())
    assert {"p1.local_review", "p1.consistency_bypass", "p1.hygiene", "p1.external_standards", "p1.provenance"} <= set(by)


@moved("inspector は Read を持っても本文を貼る渡し方")
def test_inspector_gets_pasted_body_and_investigator_gets_a_path(wave):
    by = ready_by_node(wave("review/neg/p0b-settled").run.next())
    assert by["p1.consistency_bypass"].get("deliver") == "paste"
    assert by["p1.external_standards"].get("deliver") == "path"


@moved("今の周に走った節の素材が carried_over を名乗ると exit 1")
def test_material_of_a_node_that_ran_cannot_claim_carried_over(wave):
    w = wave("review/neg/p1")
    r = w.run.done(w.pending()["p1.provenance"]["id"],
                   {"material": M("carried_over", from_round=1, reason="確認: 前の周の流用（検査用の嘘）"), "claims": []})
    rejected(r, "carried_over")


@moved("cold-reader には観点の節と差分本文だけが貼られ、目的は貼られない")
def test_cold_reader_prompt_has_lens_and_diff_but_no_purpose(wave):
    by = ready_by_node(wave("review/neg/p0b-settled").run.next())
    body = pathlib.Path(by["p1.hygiene"]["prompt_file"]).read_text(encoding="utf-8")
    assert "## コード衛生観点" in body
    assert "diff --git a/src/b.py" in body
    assert "上限を付けて" not in body


@moved("found なのに count が無い素材は exit 1")
def test_found_material_without_count_is_rejected(wave):
    w = wave("review/neg/p1")
    r = w.run.done(w.pending()["p1.local_review"]["id"], {**w.values["t"]["p1.local_review"], "material": {"status": "found"}})
    rejected(r, "count")


@moved("investigator の instance の前後で作業ツリーが変わると exit 1")
def test_worktree_change_around_an_investigator_is_rejected(wave):
    w = wave("review/neg/p1")
    (w.run.repo / "stray.txt").write_text("x", encoding="utf-8")
    r = w.run.done(w.pending()["p1.external_standards"]["id"], w.values["t"]["p1.external_standards"])
    rejected(r, "作業ツリーが変わっている")


@moved("順位（主経路）: 外部標準照合の done は、空の順位を付けられない理由なしで拒む")
def test_external_standards_without_rankings_none_is_rejected(wave):
    w = wave("review/neg/p1")
    good = w.values["t"]["p1.external_standards"]
    r = w.run.done(w.pending()["p1.external_standards"]["id"], {k: v for k, v in good.items() if k != "rankings_none"})
    rejected(r, "rankings_none")


@moved("cli で起こした遮断系の done に --agent-id を渡すと exit 1")
def test_agent_id_on_a_cli_node_is_rejected(wave):
    w = wave("review/neg/p1")
    r = w.run.done(w.pending()["p1.hygiene"]["id"], w.values["t"]["p1.hygiene"], agent_id="cli-has-no-agent")
    rejected(r, "agent_id")


# ---- P1 の後の作業ツリーの突合 --------------------------------------------------------------------------------------------

@moved("既に変更済みのファイルの中身を差し替えても止まる")
def test_replacing_content_of_an_already_modified_file_stops(wave):
    run = wave("review/neg/p1-done").run
    a = run.repo / "src" / "a.py"
    a.write_text(a.read_text(encoding="utf-8") + "# 役が書き換えた\n", encoding="utf-8")
    nx = run.next()
    assert not nx["ready"]
    assert any("tree:" in n for n in nx["notes"]), nx["notes"]


@moved("P1 の前後で作業ツリーが変わると先へ進まない")
def test_worktree_change_across_p1_stops(wave):
    run = wave("review/neg/p1-done").run
    (run.repo / "stray.txt").write_text("x", encoding="utf-8")
    nx = run.next()
    assert not nx["ready"]
    assert any("作業ツリーが変わっている" in n for n in nx["notes"]), nx["notes"]


@moved("同じ止まり方で next を叩き直しても git_mismatches は増えない")
def test_repeated_next_on_the_same_stop_does_not_grow_git_mismatches(wave):
    run = wave("review/neg/p1-done").run
    (run.repo / "stray.txt").write_text("x", encoding="utf-8")
    run.next()
    before = len(run.state().get("git_mismatches", []))
    run.next()
    assert len(run.state().get("git_mismatches", [])) == before


@moved("git が無い場では P1 の前後の突合が『測れない』で止まる")
def test_without_git_the_p1_comparison_stops_as_unmeasurable(wave, tmp_path):
    run = wave("review/neg/p1-done").run
    (run.repo / "stray.txt").write_text("x", encoding="utf-8")
    empty = tmp_path / "empty-bin"
    empty.mkdir()
    r = run.cmd("next", env={**os.environ, "PATH": str(empty)})
    assert r.returncode == 0, r.stderr[-300:]
    nx = json.loads(r.stdout)
    assert not nx["ready"]
    assert any("取れない" in n and "突き合わせられない" in n for n in nx["notes"]), nx["notes"]


@moved("自分の変更なら next --accept-tree-change で通る")
def test_accept_tree_change_passes_the_comparison(wave):
    run = wave("review/neg/p1-done").run
    (run.repo / "stray.txt").write_text("x", encoding="utf-8")
    r = run.cmd("next", "--accept-tree-change", "writer の変更（検査用）")
    assert r.returncode == 0, r.stderr[-300:]
    assert not any("作業ツリーが変わっている" in n for n in json.loads(r.stdout).get("notes", []))


@moved("受け付けた理由が git_mismatches に残る")
def test_accepted_reason_is_kept_in_git_mismatches(wave):
    run = wave("review/neg/p1-done").run
    (run.repo / "stray.txt").write_text("x", encoding="utf-8")
    run.cmd("next", "--accept-tree-change", "writer の変更（検査用）")
    gm = run.state().get("git_mismatches", [])
    assert gm and gm[-1].get("accepted") == "writer の変更（検査用）" and gm[-1].get("where") == "P1", gm


# ---- P2 の判定役の返答 ----------------------------------------------------------------------------------------------------

@moved("受け付ければ judge に進み、素材は 15 欄で渡る")
def test_after_acceptance_the_judge_runs_with_materials(wave):
    run = wave("review/neg/p2-pre").run
    jd = ready_by_node(run.next())["p2.diagnose"]
    assert jd["mode"] == "agent"
    assert "fix_closure" in json.dumps(run.record()["materials"])


def _eq(good):
    return {"key": "人でないと決められない（検査用）", "kind": "stuck", "status": "escalate", "reason": "r", "origin": good["units"][0]["key"]}


def _fork_with_adopting_precedent(good):
    fq = {"key": "どちらに倒すか（検査用）", "kind": "fork", "status": "held", "reason": "r", "origin": good["units"][0]["key"], "options": ["a", "b"]}
    return {**good, "questions": [fq], "precedents": good["precedents"] + [
        {"key": fq["key"], "problem": "人が決める分岐", "source": "https://example.invalid/", "verdict": "adopt", "reason": "そのまま採れる形"}]}


def _nocq(good):
    return {k: v for k, v in good["units"][0].items() if k != "class_query"}


def _defer_twice(good):
    d = {**_nocq(good), "label": "suggest", "disposition": "defer", "reason": "共有面に及ぶ（検査用）"}
    return {**good, "units": [d, d], "questions": []}


JUDGE_REJECTS = [
    # (id, 移した元の頭, 返答を作る, 拒否文に在る語, 無い語)
    ("origin-not-in-units", "台帳の出どころが無い judge の返答は exit 1",
     lambda g: {**g, "questions": [{"key": "q", "kind": "fork", "status": "held", "reason": "r", "origin": "無いユニット", "options": ["a", "b"]}]},
     ["units にも defer 台帳にも無い"], []),
    ("split-origin-is-block", "split の出どころが [block] の返答は exit 1",
     lambda g: {**g, "questions": [{"key": "q", "kind": "split", "status": "held", "reason": "r", "origin": "src/a.py:f — 上限が効かない経路がある"}]},
     ["人に聞く前に直す義務"], []),
    ("precedent-row-missing", "先行例: 直す単位の行が欠けた judge の返答は exit 1",
     lambda g: {**g, "precedents": g["precedents"][1:]}, ["precedents に", "の行が無い"], []),
    ("precedent-without-source", "先行例: 出典の無い行は exit 1",
     lambda g: {**g, "precedents": [{**g["precedents"][0], "source": ""}] + g["precedents"][1:]}, ["source（一次情報の出典）が無い"], []),
    ("not-found-without-searched", "先行例: 見つからないなら何を探したかが要る",
     lambda g: {**g, "precedents": [{**g["precedents"][0], "verdict": "not_found", "source": ""}] + g["precedents"][1:]},
     ["searched（何をどう探したか）が無い"], []),
    ("precedent-key-duplicated", "先行例: 同じ key の行が 2 つある judge の返答は exit 1",
     lambda g: {**g, "precedents": g["precedents"] + [g["precedents"][0]]}, ["key が重複"], []),
    ("escalate-needs-precedent", "先行例: 人へ回す問い（escalate）にも先行例の行が要る",
     lambda g: {**g, "questions": [_eq(g)]}, ["人でないと決められない（検査用）' の行が無い"], []),
    ("human-question-needs-undecided-because", "先行例: 人へ回す問いに決まらない理由が無ければ exit 1",
     _fork_with_adopting_precedent, ["undecided_because が無い", "人に回さず"], []),
    ("label-outside-vocabulary", "judge の label が語彙外（blocker）なら exit 1",
     lambda g: {**g, "units": [{**g["units"][0], "label": "blocker"}]}, ["型に合わない"], []),
    ("kind-outside-vocabulary", "台帳の kind が語彙外なら exit 1",
     lambda g: {**g, "questions": [{"key": "q", "kind": "whatever", "status": "held", "reason": "r", "origin": g["units"][0]["key"]}]},
     ["型に合わない"], []),
    ("disposition-outside-vocabulary", "disposition が語彙外なら exit 1",
     lambda g: {**g, "units": [{**g["units"][0], "disposition": "later"}]}, ["型に合わない"], []),
    ("status-outside-vocabulary", "台帳の status が語彙外なら exit 1",
     lambda g: {**g, "questions": [{"key": "q", "kind": "fork", "status": "maybe", "reason": "r", "origin": g["units"][0]["key"], "options": ["a", "b"]}]},
     ["型に合わない"], []),
    ("unknown-field", "judge の返答に知らない欄があれば exit 1",
     lambda g: {**g, "verdict": "pass"}, ["型に合わない"], []),
    ("defer-without-reason", "defer に reason の無い judge の返答は exit 1",
     lambda g: {**g, "units": [{**g["units"][0], "label": "suggest", "disposition": "defer"}]}, ["defer"], []),
    ("one-shot-closes-empty", "一撃が閉じると見込む unit を名指ししない judge の返答は exit 1",
     lambda g: {**g, "one_shot_closes": []}, ["one_shot_closes"], []),
    ("one-shot-closes-unknown-key", "one_shot_closes が今の周の units に無い key を指すと exit 1",
     lambda g: {**g, "one_shot_closes": ["存在しないユニット"]}, ["units に無い key"], []),
    ("block-without-class-query", "[block] に class_query（母数の問い）が無い judge の返答は exit 1",
     lambda g: {**g, "units": [_nocq(g)]}, ["class_query"], []),
    ("class-query-total-not-a-number", "class_query.total が数でなければ exit 1",
     lambda g: {**g, "units": [{**g["units"][0], "class_query": {"how": {"patterns": ["limit"], "paths": ["src"], "count": "files"},
                                                                  "counts": "population", "total": True}}]},
     ["型に合わない"], []),
    ("class-query-unrunnable", "判定者の class_query も、走らせられない問いは exit 1",
     lambda g: {**g, "units": [{**g["units"][0], "class_query": {"how": {"patterns": ["x"], "paths": ["nope/"], "count": "lines"},
                                                                  "counts": "defects", "total": 1}}]},
     ["走らせられない", "units[0].class_query"], []),
    # defer の単位には母数を求めない——正しい返答だと節が済むので、key の重複で赤くして class_query で赤くないことを見る
    ("defer-needs-no-class-query", "defer の単位には母数を求めない", _defer_twice, ["重複"], ["class_query"]),
]


@pytest.mark.parametrize("make, words, absent", [
    pytest.param(make, words, absent, id=cid, marks=moved(head)) for cid, head, make, words, absent in JUDGE_REJECTS])
def test_judge_reply_is_rejected(wave, make, words, absent):
    w = wave("review/neg/p2")
    r = w.run.done(w.pending()["p2.diagnose"]["id"], make(w.values["t"]["p2.diagnose"]))
    rejected(r, *words, absent=absent)


def _accept_fresh_judge_reply_from_stdin(w):
    """置き場に古い返答を置いたまま、件数を書き違えた新しい返答を標準入力で渡す（PYTHONIOENCODING=cp1252 を環境に入れる）"""
    jd = w.pending()["p2.diagnose"]
    good = w.values["t"]["p2.diagnose"]
    out = pathlib.Path(jd["out_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({**good, "framing": "STALE"}, ensure_ascii=False), encoding="utf-8")
    r = w.run.cmd("done", "--node", jd["id"], "--stdin", "--agent-id", "judge-1",
                  input=json.dumps(waves.fresh_judge_reply(good), ensure_ascii=False), env={**os.environ, "PYTHONIOENCODING": "cp1252"})
    return r, json.loads(out.read_text(encoding="utf-8")), good


@moved("正しい judge の返答は通り、どこから読んだかが返事に残る",
       kept="PYTHONIOENCODING=cp1252 は Python の起動時にだけ効く——同じプロセスでは、標準入力をバイトで読んで UTF-8 に決める経路を"
            "cp1252 の既定で試せない（3 OS の通しで windows-latest だけ赤だった実測の腕）")
def test_judge_reply_from_stdin_is_accepted_and_says_where_it_was_read(wave):
    r, _, _ = _accept_fresh_judge_reply_from_stdin(wave("review/neg/p2"))
    assert r.returncode == 0, (r.stdout + r.stderr)[-300:]
    assert "読んだ先: stdin" in r.stdout


@moved("標準入力の返答が置き場の古い返答より優先され")
def test_stdin_reply_wins_over_a_stale_out_path(wave):
    _, stored, _ = _accept_fresh_judge_reply_from_stdin(wave("review/neg/p2"))
    assert stored.get("framing") == "FRESH"


@moved("判定者の書いた件数は engine が数えた件数に置き換わり")
def test_judge_count_is_replaced_by_the_engine_count(wave):
    r, stored, _ = _accept_fresh_judge_reply_from_stdin(wave("review/neg/p2"))
    cq = stored["units"][0]["class_query"]
    assert cq["total"] == 1
    assert "engine が how を走らせた 1 に置き換えた" in cq.get("note", "")
    assert "3 → 1" in r.stdout


@moved("engine が 0 件を数えた単位は置き換えず")
def test_zero_engine_count_is_not_substituted(wave):
    r, stored, _ = _accept_fresh_judge_reply_from_stdin(wave("review/neg/p2"))
    cq = stored["units"][1]["class_query"]
    assert cq["total"] == 1
    assert "0 件" in cq.get("note", "")
    assert "置き換えなかった" in r.stdout


@moved("engine が 0 件を数えた単位の key は、判定の出口の欄（p2.diagnose の出力の engine_zero）に残り、盤面の loop には書かない")
def test_zero_count_unit_keys_are_left_for_the_fix(wave):
    w = wave("review/neg/p2")
    _, _, good = _accept_fresh_judge_reply_from_stdin(w)
    assert (w.run.output("p2.diagnose") or {}).get("engine_zero") == [good["units"][1]["key"]]
    assert "engine_zero" not in w.run.state().get("loop", {})


# ---- P3 の修正の返答 ------------------------------------------------------------------------------------------------------

BLOCK_KEY = "src/a.py:f — 上限が効かない経路がある"
UNKNOWN_CITE = {"kind": "text", "cite": "検査用に無い字列", "target": "README.md", "where": "src/a.py"}


@moved("[block] を直さない writer の返答は exit 1 で、残した理由を拒否文に併記する")
def test_fix_leaving_a_block_unfixed_is_rejected_with_its_reason(wave):
    w = wave("review/neg/p3")
    # 台本は P0 の波で引いた表の p3.fix を土台にする（その時点の記録には単位が無い）
    r = w.run.done(w.pending()["p3.fix"]["id"], {**w.values["t"]["p3.fix"], "changes": [], "not_done": [{"unit_key": BLOCK_KEY, "why": "面倒"}]})
    rejected(r, "直していない", "理由: 面倒")


@moved("閉鎖の実証で赤を見ていないのに fix_closure=clean の返答は exit 1")
def test_clean_closure_without_red_seen_is_rejected(wave):
    w = wave("review/neg/p3")
    fix = w.values["fix"]
    nored = {**fix, "changes": [{**c, "closure": {**c["closure"], "sites": [{"site": s["site"], "red_seen": False} for s in c["closure"]["sites"]]}}
                                for c in fix["changes"]]}
    assert fix["changes"]
    rejected(w.run.done(w.pending()["p3.fix"]["id"], nored), "赤を一度も見ていない")


def _with_changes(fix, **kw):
    return {**fix, "changes": [{**c, **kw} for c in fix["changes"]]}


def _with_coverage(fix, **kw):
    return {**fix, "changes": [{**c, "coverage": {**c["coverage"], **kw}} for c in fix["changes"]]}


def _no_coverage_on_first(fix):
    # 判定者の how が台本の how と同じ単位（先頭）だけ coverage を省く
    return {**fix, "wrote_refs": [UNKNOWN_CITE], "changes": [{k: v for k, v in fix["changes"][0].items() if k != "coverage"}] + fix["changes"][1:]}


def _remaining_only_on_first(fix):
    nocov = _no_coverage_on_first(fix)
    return {**nocov, "changes": [{**nocov["changes"][0], "coverage": {"remaining": "検査用に残した理由を書いた"}}] + nocov["changes"][1:]}


def _narrow(fix):
    return {**fix, "changes": [{**c, "closure": {**c["closure"], "sites": []},
                                "coverage": {**c["coverage"], "how": {"patterns": ["no-such-word"], "paths": ["src"], "count": "lines"}}}
                               for c in fix["changes"]]}


def _narrow_with_empty_remaining(fix):
    n = _narrow(fix)
    return {**n, "changes": [{**c, "coverage": {**c["coverage"], "remaining": "なし"}} for c in n["changes"]]}


def _from_judge_row(fix):
    # 修正役が向きを書いても使われない（判定者の値が勝つ）——population の判定者に defects と書く
    return {**fix, "wrote_refs": [UNKNOWN_CITE],
            "changes": [{**c, "precedent": {"verdict": "adopt", "from_judge_row": True, "reason": "判定者の行（検査用）"},
                         "coverage": {**c["coverage"], "counts": "defects"}} for c in fix["changes"]]}


def _with_remaining(fix):
    return {**_with_coverage(fix, remaining="残り 2 件は fork の出どころ（検査用）"), "wrote_refs": [UNKNOWN_CITE]}


def _write(run, rel, text):
    p = run.repo / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _readme_with_links(run):
    readme = run.repo / "README.md"
    readme.write_text(readme.read_text(encoding="utf-8") + "詳しくは [設計](docs/nowhere.md) と [見出し](README.md#no-such) と"
                      " [在る](README.md#demo) を見よ。`[例](x.md)` は書式の例\n", encoding="utf-8")


FIX_REJECTS = [
    # (id, 移した元の頭, 返答を作る, 作業ツリーの支度, 拒否文に在る語, 無い語)
    ("not-applicable-closure-with-changes", "修正が在るのに fix_closure=not_applicable の返答は exit 1",
     lambda f: {**f, "fix_closure": M("not_applicable", reason="条件に当たらない（検査用の嘘）")}, None, ["not_applicable"], []),
    ("interactions-left-out", "2 つ以上の修正が触った面を書き落とすと exit 1",
     lambda f: {**f, "interactions": []}, None, ["interactions に無い"], []),
    ("interactions-listing-changes", "面ごとの修正の一覧（changes）は役に書かせない",
     lambda f: {**f, "interactions": [{**f["interactions"][0], "changes": [c["unit_key"] for c in f["changes"]]}]}, None, ["型に合わない"], []),
    ("interactions-checked-empty-word", "干渉を突き合わせた結果が空同然なら exit 1",
     lambda f: {**f, "interactions": [{**f["interactions"][0], "checked": "なし"}]}, None, ["checked が空同然"], []),
    ("bypass-not-tried", "修正を残したまま破りに行った形跡が無い返答は exit 1",
     lambda f: _with_changes(f, bypass_tried="なし"), None, ["bypass_tried"], []),
    ("breaks-result-empty-word", "壊しうる面を確かめた結果が空同然なら exit 1",
     lambda f: {**f, "changes": [{**c, "breaks": {**c["breaks"], "result": "特になし"}} for c in f["changes"]]}, None, ["breaks.result"], []),
    ("symptom-without-why-now", "症状を塞ぐ修正に「なぜ今それで止めるか」が無ければ exit 1",
     lambda f: _with_changes(f, root_or_symptom={"kind": "symptom", "why": "後で"}), None, ["症状"], []),
    ("coverage-omitted-under-judge-query", "判定者が class_query を持つ単位は coverage を省いても coverage では拒まない",
     _no_coverage_on_first, None, ["の中に無い"], ["coverage"]),
    ("coverage-remaining-only", "coverage に remaining だけを書いた返答も coverage では拒まない",
     _remaining_only_on_first, None, ["の中に無い"], ["coverage"]),
    ("partial-closure-without-remaining", "母数 2 のうち閉鎖を実証した site が 1 件で残りが在るのに remaining が無ければ exit 1",
     lambda f: _with_coverage(f, how={"patterns": ["def"], "paths": ["src"], "count": "lines"}), None, ["remaining"], []),
    ("how-as-one-command", "1 行のコマンドの how は型で拒む",
     lambda f: _with_coverage(f, how="git grep -l -e limit -- src | wc -l"), None, ["型に合わない"], []),
    ("how-unrunnable", "走らせられない how は拒む",
     lambda f: _with_coverage(f, how={"patterns": ["x"], "paths": ["nope/"], "count": "lines"}), None, ["走らせられない"], []),
    ("how-narrower-than-judge", "覆い: 判定者の母数より狭い how は理由なしで拒む",
     _narrow, None, ["問いを狭めている"], []),
    ("remaining-empty-word", "覆い: 空語（『なし』）の remaining は理由に数えない",
     _narrow_with_empty_remaining, None, ["問いを狭めている"], []),
    ("fix-precedent-without-source", "先行例: 修正の先行例に出典が無ければ exit 1",
     lambda f: _with_changes(f, precedent={"verdict": "adopt", "reason": "採った（検査用）"}), None, ["precedent に problem と source"], []),
    ("fix-precedent-from-judge-row", "先行例: 判定者の行が在る単位は from_judge_row で採れる",
     _from_judge_row, None, ["の中に無い"], ["from_judge_row なのに", "precedent に"]),
    ("closure-sites-over-population", "closure.sites が母数を超える返答は exit 1",
     lambda f: _with_coverage(f, how={"patterns": ["no-such-word"], "paths": ["src"], "count": "lines"}), None, ["母数を超えて"], []),
    ("markdown-links-added-by-the-diff", "リンク: 申告が空でも、差分が足したリンクの指し先と見出しを引いて拒む",
     lambda f: f, _readme_with_links, ["Markdown のリンクが指し先に届かない", "docs/nowhere.md", "#no-such"], ["#demo", "x.md"]),
    ("partial-coverage-with-remaining", "残した理由を書けば部分的な覆いは通る",
     _with_remaining, None, ["の中に無い"], ["remaining", "coverage"]),
    ("cite-not-in-target", "指し先に無い字列は exit 1",
     lambda f: {**f, "wrote_refs": [{"kind": "text", "cite": "Data Platform の責務", "target": "README.md", "where": "src/a.py"}]},
     None, ["の中に無い", "README.md"], []),
    ("cite-target-missing", "指し先のファイルが無ければ exit 1",
     lambda f: {**f, "wrote_refs": [{"kind": "text", "cite": "# demo", "target": "docs/nowhere.md", "where": "README.md"}]},
     None, ["作業ツリーに無い"], ["の中に無い"]),
    ("wrote-refs-dropped", "wrote_refs を落とした返答は型で拒まれる",
     lambda f: {k: v for k, v in f.items() if k != "wrote_refs"}, None, ["wrote_refs"], []),
    ("same-text-in-another-file", "別のファイルに同じ字列が在っても、target に無ければ exit 1",
     lambda f: {**f, "wrote_refs": [{"kind": "text", "cite": "# demo", "target": "src/a.py", "where": "README.md"}]},
     lambda run: _write(run, "src/b.py", "# demo\ndef g(y):\n    return y * 2\n"), ["の中に無い"], []),
    ("cite-with-newline", "改行を含む cite は exit 1",
     lambda f: {**f, "wrote_refs": [{"kind": "text", "cite": "def f(x, limit=None):\n\n    return x", "target": "src/a.py", "where": "README.md"}]},
     None, ["指し先の 1 行から写す"], ["git grep"]),
]


@pytest.mark.parametrize("make, prepare, words, absent", [
    pytest.param(make, prepare, words, absent, id=cid, marks=moved(head)) for cid, head, make, prepare, words, absent in FIX_REJECTS])
def test_fix_reply_is_rejected(wave, make, prepare, words, absent):
    w = wave("review/neg/p3")
    if prepare:
        prepare(w.run)
    rejected(w.run.done(w.pending()["p3.fix"]["id"], make(w.values["fix"])), *words, absent=absent)


def _accept_mixed_fix_from_out_path(w):
    """赤を見た修正と見ていない修正（文書）が混じり、この周に作ったファイルを指す申告を、out_path に書いて --output 無しで done"""
    run, fix = w.run, w.values["fix"]
    fx = w.pending()["p3.fix"]
    _write(run, "src/b.py", "# demo\ndef g(y):\n    return y * 2\n")
    _write(run, "docs/made-this-round.md", "# この周に書いた見出し\n")
    # 欠陥の形そのもの（limit）を数える問いで全部直した——修正で limit が消え、同じ how は修正後に 0 件を返す
    _write(run, "src/a.py", "def f(x, cap=None):\n    return x if cap is None else min(x, cap)\n")
    mixed = {**fix, "changes": [fix["changes"][0], {**fix["changes"][1], "closure": {**fix["changes"][1]["closure"],
                                                                                         "sites": [{"site": "docs（赤を見られない）", "red_seen": False}]}}],
             "wrote_refs": [{"kind": "text", "cite": "# demo", "target": "README.md", "where": "src/a.py"},
                            {"kind": "text", "cite": "# この周に書いた見出し", "target": "docs/made-this-round.md", "where": "README.md"}]}
    out = pathlib.Path(fx["out_path"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(mixed, ensure_ascii=False), encoding="utf-8")
    return run.cmd("done", "--node", fx["id"]), fix


@moved("修正前の母数 1・修正後に engine が数えた 0 が記録に残る")
def test_coverage_before_and_after_are_recorded(wave):
    w = wave("review/neg/p3")
    r, _ = _accept_mixed_fix_from_out_path(w)
    assert r.returncode == 0, (r.stdout + r.stderr)[-300:]
    after = (w.run.output("p3.fix") or {}).get("coverage_after") or {}
    assert after.get("round") == w.values["round"] and after.get("items"), after
    assert all(x["total"] == 1 and x["after"] == 0 for x in after["items"]), after


@moved("赤を見た修正と見ていない修正（文書）が混じる周の clean は通る")
def test_mixed_closure_passes_and_reads_the_out_path(wave):
    r, fix = _accept_mixed_fix_from_out_path(wave("review/neg/p3"))
    assert len(fix["changes"]) >= 2
    assert r.returncode == 0, (r.stdout + r.stderr)[-300:]
    assert "読んだ先: out_path" in r.stdout
