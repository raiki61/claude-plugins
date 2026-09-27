"""層 2 の筋書き（review）: 上限で止まる類と、止める・人待ちの台本（graphloops/tests/simulate_review.py）の check を、given（控えた
波）・when（1 手の関数）・then（手で書いた述語）の行へ移した物。1 行が台本の check 1 件で、行の印 ``moved_from`` が名乗る（台帳は
ledger.py）。

前置きは waves.py の WAVES・ROOTS（台本の Run・drive・answers と、台本の関数の中の hook の写し）。盤面を回すので medium で、
印 layer2 も付く。台本はまだ消していない（MIGRATION.md の T2）。test_stop_midround と test_human_gate の主経路は通しに残す 10 本
なので、印の kept に理由を書く。
"""
import json
import pathlib
import re

import pytest
import waves
from waves import EXCLUDE_WHY, WAIT_CI, WRITER_POLICY, play, row

review = waves.review
pytestmark = [pytest.mark.medium, pytest.mark.layer2]
KEPT = "通しに残す 10 本（testplan の REDESIGN.md 3.6）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手"


def rec(w):
    return w.run.record()


def st(w):
    return w.run.state()


def last(w):
    return w.values["last"]


def kinds(w):
    return ((last(w) or {}).get("ask") or {}).get("kinds")


def rc(w, key):
    return w.values[key]["rc"]


# ---- 上限で止まる類 -----------------------------------------------------------------------------------------------------

S = "simulate_review.test_runaway"
RUNAWAY = [
    row(S, "5 周で停止", "review/runaway/end", lambda w, g: last(w)["status"] == "stopped" and st(w)["round"] == 5, id="stops-at-round-5"),
    # 旧い check の 2 つの枝（記録の停止理由の暴走ガード・盤面の loop の max_rounds）を落とさない
    row(S, "停止の理由が上限", "review/runaway/end",
        lambda w, g: "暴走ガード" in rec(w)["process"].get("stop_reason", "") or st(w)["loop"].get("stop_reason") == "max_rounds",
        id="stop-reason-is-the-cap"),
]


@pytest.mark.parametrize("given, when, then", RUNAWAY)
def test_runaway(wave, given, when, then):
    play(wave, given, when, then)


S = "simulate_review.test_ci_red_runaway"
CI_RED_RUNAWAY = [
    row(S, "CI が赤のままの run は 5 周で止まる", "review/cired/end",
        lambda w, g: last(w)["status"] == "stopped" and st(w)["round"] == 5, id="stops-at-round-5"),
    row(S, "停止の理由が上限", "review/cired/end", lambda w, g: st(w)["loop"].get("stop_reason") == "max_rounds", id="stop-reason-max-rounds"),
]


@pytest.mark.parametrize("given, when, then", CI_RED_RUNAWAY)
def test_ci_red_runaway(wave, given, when, then):
    play(wave, given, when, then)


# ---- 人待ち -------------------------------------------------------------------------------------------------------------

S = "simulate_review.test_no_new_awaiting_after_judge"
NO_NEW_AWAITING = [
    row(S, "判定の後の人待ち: 問いの無い awaiting_human を書いた p4.ci は拒む", "review/noawait/end",
        lambda w, g: (s := w.values["seen"]).get("rc") == 1 and "人待ちの問い（kind=awaiting）が無い" in s.get("err", "")
        and "not_run" in s.get("err", ""), id="p4-ci-awaiting-without-question"),
]


@pytest.mark.parametrize("given, when, then", NO_NEW_AWAITING)
def test_no_new_awaiting_after_judge(wave, given, when, then):
    play(wave, given, when, then)


S = "simulate_review.test_awaiting"
AWAITING = [
    row(S, "主経路の観測: 見たと言う状態なのに観測した値が無ければ exit 1", "review/await/asked",
        lambda w, g: (lied := w.values["lied"]).get("rc") == 1 and "observed" in lied.get("err", ""), id="observed-empty"),
    row(S, "主経路の観測: 空白だけの観測の行も観測した値に数えない", "review/await/asked",
        lambda w, g: (lied := w.values["lied"]).get("blank_rc") == 1 and "observed" in lied.get("blank_err", ""), id="observed-blank"),
    row(S, "残る阻害が保留の問いだけになった周に聞く", "review/await/asked",
        lambda w, g: last(w)["status"] == "awaiting_human" and kinds(w) == ["work_exhausted"], id="asks-work-exhausted"),
    row(S, "立った周（1）には聞かず、2 周目に聞く", "review/await/asked", lambda w, g: st(w)["round"] == 2, id="asks-in-round-2"),
    row(S, "答えを渡して続行", "review/await/asked", lambda w, g: g.returncode == 0,
        when=lambda w: w.run.cmd("answer", "--text", "continue", "--note", "テスト用設定 config/dev.local.example で起動できる"),
        id="answer-continue"),
    row(S, "答えの後に収束", "review/await/end", lambda w, g: last(w)["status"] == "converged", id="converges-after-answer"),
    row(S, "3 周目に観測して問いは resolved", "review/await/end",
        lambda w, g: (r3 := w.run.round_file(3))["materials"]["main_path_observation"]["status"] == "clean"
        and any(q["status"] == "resolved" for q in r3["questions"]), id="round-3-resolves"),
    row(S, "人の答えが記録に残り次の周の judge に渡る", "review/await/end",
        lambda w, g: any("config/dev.local.example" in (a.get("note") or "") for a in rec(w)["process"]["human_answers"]),
        id="answer-kept-in-record"),
]


@pytest.mark.parametrize("given, when, then", AWAITING)
def test_awaiting(wave, given, when, then):
    play(wave, given, when, then)


def _seen(w, key):
    return w.values["seen"].get(key) or [None, ""]


S = "simulate_review.test_awaiting_origin_guards"
AWAITING_ORIGIN_GUARDS = [
    row(S, "判定の時点: 人待ちの素材を出どころにする問いを台帳に載せない判定は拒む", "review/awaitorigin/end",
        lambda w, g: _seen(w, "unlisted")[0] == 1
        and "素材 'local_checks' が awaiting_human なのに台帳に kind=awaiting で無い" in _seen(w, "unlisted")[1], id="judge-unlisted"),
    row(S, "判定の時点: 人待ちでない素材を出どころにした awaiting は拒み", "review/awaitorigin/end",
        lambda w, g: _seen(w, "judge")[0] == 1 and all(x in _seen(w, "judge")[1] for x in ("awaiting の出どころは", "main_path_observation", "kind=field")),
        id="judge-wrong-origin"),
    row(S, "書いた時点: 人に諮っている欄を後の工程が clean で上書きすると拒む", "review/awaitorigin/end",
        lambda w, g: _seen(w, "ci")[0] == 1 and "local_checks" in _seen(w, "ci")[1] and "awaiting_human のまま書け" in _seen(w, "ci")[1],
        id="ci-overwrite"),
    row(S, "CI を再実行する節のプロンプトに、この周の問いの台帳が渡る", "review/awaitorigin/end",
        lambda w, g: WAIT_CI["key"] in (w.values["seen"].get("ci_prompt") or ""), id="ci-prompt-has-ledger"),
    row(S, "実地の問いは field で台帳に載り", "review/awaitorigin/end",
        lambda w, g: any(q["kind"] == "field" and not q.get("origin") for q in _round1(w)["questions"])
        and _round1(w)["materials"].get("local_checks", {}).get("status") == "awaiting_human", id="field-question-kept"),
]


def _round1(w):
    return w.run.round_file(1) if (w.run.dir / "rounds" / "round-1.json").is_file() else {"questions": [], "materials": {}}


@pytest.mark.parametrize("given, when, then", AWAITING_ORIGIN_GUARDS)
def test_awaiting_origin_guards(wave, given, when, then):
    play(wave, given, when, then)


S = "simulate_review.test_final_gate_empty_asks_human"
FINAL_GATE_EMPTY = [
    row(S, "撃てた腕が 0 本の関門で収束を言わず人に諮る", "review/gate-empty/asked",
        lambda w, g: last(w)["status"] == "awaiting_human" and kinds(w) == ["final_gate_empty"], id="asks-on-empty-gate"),
    row(S, "諮る前に止めた理由（stop_reason）を立てる", "review/gate-empty/asked",
        lambda w, g: st(w)["loop"].get("stop_reason") == "final_gate_empty", id="stop-reason-before-asking"),
    row(S, "continue を返す", "review/gate-empty/asked", lambda w, g: g.returncode == 0,
        when=lambda w: w.run.cmd("answer", "--text", "continue", "--note", "文書だけの差分と確かめた（検査用）"), id="answer-continue"),
    row(S, "人が認めた木なら、次の周の 0 本の関門で収束する", "review/gate-empty/end",
        lambda w, g: last(w)["status"] == "converged", id="converges-next-round"),
    row(S, "上限の周でも 0 本の関門は人に諮る", "review/gate-empty-max/asked",
        lambda w, g: last(w)["status"] == "awaiting_human" and kinds(w) == ["final_gate_empty"], id="asks-at-max-round"),
    row(S, "上限の周の continue は上限を 1 周だけ延ばし", "review/gate-empty-max/extended",
        lambda w, g: st(w)["max_rounds"] == (a := w.values["asked_round"]) + 1
        and (rec(w)["process"].get("human_answers") or [{}])[-1].get("max_rounds") == {"from": a, "to": a + 1}, id="continue-extends-by-one"),
    row(S, "延ばした次の周で、同じ木の 0 本の関門が通って収束する", "review/gate-empty-max/end",
        lambda w, g: last(w)["status"] == "converged", id="converges-after-extension"),
]


@pytest.mark.parametrize("given, when, then", FINAL_GATE_EMPTY)
def test_final_gate_empty_asks_human(wave, given, when, then):
    play(wave, given, when, then)


# ---- 止める ---------------------------------------------------------------------------------------------------------------

S = "simulate_review.test_stop_midround"


def _stale_then_stop(w):
    waves._stale_round_file(w.run)
    return w.run.cmd("stop", "--reason", "検査: 負けた試行の残したファイルの上で止める")


def _stop_at_r2(w):
    prev = w.run.round_file(1)
    return prev, w.run.cmd("stop", "--reason", "検査: 2 周目の頭で止める")


def _stop_while_asking(w):
    r = w.run.cmd("stop", "--reason", "検査: 人に聞いている最中に止める")
    proc = w.run.record()["process"]
    un = (proc.get("halted") or {}).get("unanswered") or {}
    hi = [h for h in proc.get("human_items") or [] if "答えないまま人が止めた" in (h.get("note") or "") and h.get("answer") is None]
    return r, un, hi


def _stopped_round_record(rf):
    return (all(rf["reviews"][k]["status"] == "not_run" and "人が止めた" in rf["reviews"][k]["reason"] for k in ("R1", "R2", "R3", "R4"))
            and rf["materials"]["fix_closure"]["status"] == "not_run" and "人が止めた" in rf["materials"]["fix_closure"]["reason"])


def _late_done(w):
    f = w.run.tmp / "late.json"
    f.write_text("{}", encoding="utf-8")
    return w.run.cmd("done", "--node", "p2.fix_plan", "--output", str(f))


STOP_MIDROUND = [
    row(S, "止める: 理由の空は拒む", "review/stopmid/at-fixplan", lambda w, g: g.returncode == 1 and "理由が空" in g.stderr,
        when=lambda w: w.run.cmd("stop", "--reason", " "), id="empty-reason", kept=KEPT),
    row(S, "止める: 宣言の在る graph では halted にせず報告へ進む", "review/stopmid/stopped",
        lambda w, g: rc(w, "stop") == 0 and json.loads(w.values["stop"]["out"])["stopped"]["report"] is True
        and st(w)["status"] == "stopped" and "halted" not in st(w), id="declared-graph-goes-to-report", kept=KEPT),
    row(S, "止める: 待ちの節は止めた印（省いた印と別）になる", "review/stopmid/stopped",
        lambda w, g: "p2.fix_plan" in (rd := st(w)["rounds"][-1])["stopped"] and rd["instances"]["p2.fix_plan"]["status"] == "stopped"
        and "p2.fix_plan" not in rd["skipped"], id="pending-node-marked-stopped", kept=KEPT),
    row(S, "止める: 止めた周の記録は、走らなかった R と素材を止めた事実で書く", "review/stopmid/stopped",
        lambda w, g: _stopped_round_record(w.run.round_file(1)), id="round-record-says-stopped", kept=KEPT),
    row(S, "止める: 止めた時点で記録に理由が入る", "review/stopmid/stopped",
        lambda w, g: bool(w.run.round_file(1)["units"]) and rec(w)["process"]["halted"]["reason"] == "検査: 修正案の前で止める",
        id="reason-in-record", kept=KEPT),
    row(S, "止める: 止めた節の返答は受け付けない", "review/stopmid/stopped", lambda w, g: g.returncode == 1 and "stopped" in g.stderr,
        when=_late_done, id="late-reply-rejected", kept=KEPT),
    row(S, "止める: 止まった run は二度止めない", "review/stopmid/stopped", lambda w, g: g.returncode == 1 and "止める物が無い" in g.stderr,
        when=lambda w: w.run.cmd("stop", "--reason", "二度目"), id="no-second-stop", kept=KEPT),
    row(S, "止める: 次の next は報告の節だけを出す", "review/stopmid/stopped",
        lambda w, g: [i["node"] for i in g["ready"]] == ["report.human_items"], when=lambda w: w.run.next(), id="next-is-report-only", kept=KEPT),
    row(S, "止める: 報告まで届き、仕上げた記録に止めた口と止めた節が残る", "review/stopmid/end",
        lambda w, g: last(w)["status"] == "stopped" and (w.run.dir / "report.md").is_file()
        and (p := rec(w)["process"])["stop_reason"] == "stop" and p["outcome"] == "stopped"
        and any(x["node"] == "p2.fix_plan" for x in p["stopped_nodes"]) and not any(x["node"] == "p2.fix_plan" for x in p["skipped"]),
        id="reaches-report", kept=KEPT),
    row(S, "止める: 残ったファイルを済んだと読まず", "review/stopstale/at-fixplan",
        lambda w, g: g.returncode == 0 and "stale" not in (rf := w.run.round_file(1)) and rf["reviews"] == (r := rec(w))["reviews"]
        and all(r["reviews"][k]["status"] == "not_run" for k in ("R1", "R2", "R3", "R4")), when=_stale_then_stop, id="stale-round-file",
        kept=KEPT),
    row(S, "止める: 2 周目の判定より前なら前の周の単位と台帳を報告に残す", "review/stopr2/at-r2",
        lambda w, g: g[1].returncode == 0 and (r := rec(w))["units"] == g[0]["units"] and r["questions"] == g[0]["questions"]
        and not (w.run.dir / "rounds" / "round-2.json").is_file(), when=_stop_at_r2, id="stop-before-round-2-judge", kept=KEPT),
    row(S, "止める: 人に聞いている最中なら", "review/stopask/asked",
        lambda w, g: last(w)["status"] == "awaiting_human" and g[0].returncode == 0 and g[1].get("question")
        and g[1].get("node") == last(w)["ask"].get("node") and "pending_human" not in st(w) and len(g[2]) == 1,
        when=_stop_while_asking, id="stop-while-asking", kept=KEPT),
    row(S, "止める: 宣言の無い graph は halted（by=stop）で後の節を出さない", "review/stopnodecl/stopped",
        lambda w, g: rc(w, "stop") == 0 and "報告の節は出ない" in w.values["stop"]["out"] and (nx := w.values["nx"])["halted"]["by"] == "stop"
        and not nx["ready"], id="undeclared-graph-halts", kept=KEPT),
    row(S, "止める: halted の run は『もう止まっている』で拒む", "review/stopnodecl/stopped",
        lambda w, g: g.returncode == 1 and "もう止まっている" in g.stderr,
        when=lambda w: w.run.cmd("stop", "--reason", "検査: 止まった run をもう一度止める"), id="halted-run-refuses-stop", kept=KEPT),
]


@pytest.mark.parametrize("given, when, then", STOP_MIDROUND)
def test_stop_midround(wave, given, when, then):
    play(wave, given, when, then)


S = "simulate_review.test_stop_after_round"


def _halts_after_finalize(w):
    w.run.cmd("finalize")
    return [json.loads(x) for x in (w.run.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines() if '"halted"' in x]


def _answer_continue(w):
    r = w.run.cmd("answer", "--text", "continue", "--note", "続けて（検査用）")
    return r, w.run.state()


STOP_AFTER_ROUND = [
    row(S, "init が --stop-after-round を受ける", "review/stop1/init", lambda w, g: w.run.init.returncode == 0, id="init-accepts"),
    row(S, "1 周目の締めの後の next が stopped と halted", "review/stop1/end1",
        lambda w, g: last(w)["status"] == "stopped" and (last(w).get("halted") or {}).get("by") == "stop_after_round" and not last(w)["ready"],
        id="stops-after-round-1"),
    row(S, "周の締め（周の記録・converge）は済み、2 周目は開いていない", "review/stop1/end1",
        lambda w, g: (s := st(w))["round"] == 1 and len(s["rounds"]) == 1 and "converge" in s["rounds"][0]["done"]
        and (w.run.dir / "rounds" / "round-1.json").is_file(), id="round-closed-not-opened"),
    row(S, "止めた後の next は節を出さず、止めた口を言う", "review/stop1/end1",
        lambda w, g: g["status"] == "stopped" and not g["ready"] and g["halted"]["by"] == "stop_after_round" and "stop_after_round" in g["note"],
        when=lambda w: w.run.next(), id="next-after-stop"),
    row(S, "status に halted と stop_after_round が出る", "review/stop1/end1",
        lambda w, g: g["halted"]["by"] == "stop_after_round" and g["stop_after_round"] == 1 and g["status"] == "stopped",
        when=lambda w: json.loads(w.run.cmd("status").stdout), id="status-shows-halted"),
    row(S, "仕上げた記録に止めた理由が残る", "review/stop1/end1",
        lambda w, g: g.get("outcome") == "stopped" and g.get("stop_reason") == "stop_after_round",
        when=lambda w: w.run.cmd("finalize") and w.run.record()["process"], id="finalized-reason"),
    row(S, "止めたことは trace にも 1 行残る", "review/stop1/end1",
        lambda w, g: [(x.get("op"), x.get("by"), x.get("round")) for x in g] == [("halted", "stop_after_round", 1)],
        when=_halts_after_finalize, id="trace-has-one-halt"),
    row(S, "resume が 2 周目を開き、1 周目の試行はそのまま", "review/stop1/resumed",
        lambda w, g: rc(w, "resume") == 0 and (s := st(w))["round"] == 2 and s["status"] == "running" and "halted" not in s
        and s["rounds"][0]["instances"] == w.values["r1"] and not s.get("patches"), id="resume-opens-round-2"),
    row(S, "続けた run は新しい止め周（2 周目）の締めで止まり", "review/stop1/end2",
        lambda w, g: last(w)["status"] == "stopped" and (s := st(w))["halted"]["by"] == "stop_after_round" and s["halted"]["round"] == 2
        and [x["prev_halted"]["round"] for x in s["resumes"]] == [1], id="resumed-stops-at-round-2"),
    row(S, "続けた痕跡は記録の process.resumes にも写る", "review/stop1/end2",
        lambda w, g: [x["reason"] for x in g.get("resumes", [])] == ["検査: 続ける"],
        when=lambda w: w.run.cmd("finalize") and w.run.record()["process"], id="resumes-in-record"),
    row(S, "--stop-after-round 2 は 1 周目の後は次の周を開き", "review/stop2/end",
        lambda w, g: last(w)["status"] == "stopped" and (s := st(w))["halted"]["round"] == 2 and len(s["rounds"]) == 2, id="stop-after-2"),
    row(S, "answer continue でも次の周を開かずに止まる", "review/stop1a/asked",
        lambda w, g: last(w)["status"] == "awaiting_human" and g[0].returncode == 0 and "halted" in g[0].stdout
        and g[1]["status"] == "stopped" and g[1]["halted"]["by"] == "stop_after_round" and len(g[1]["rounds"]) == 1,
        when=_answer_continue, id="answer-continue-also-stops"),
    row(S, "--stop-after-round 0 は init が拒み、盤面を残さない", None,
        lambda w, g: g.init.returncode == 2 and "1 以上" in g.init.stderr and not g.dir.exists(),
        when=lambda w: review.Run("stop0", init_args=["--stop-after-round", "0"]), id="zero-rejected-at-init"),
]


@pytest.mark.parametrize("given, when, then", STOP_AFTER_ROUND)
def test_stop_after_round(wave, given, when, then):
    play(wave, given, when, then)


# ---- 人の決定権の関所 -----------------------------------------------------------------------------------------------------

S = "simulate_review.test_human_gate"


def _policy_diff(last_next):
    row_ = "".join(last_next["ask"]["items"])
    return row_, (row_.split("差分 ", 1)[-1].split("・", 1)[0] if "差分 " in row_ else "")


def _fix_rows(w):
    return (st(w)["loop"].get("fix_units") or {}).get("rows") or []


def _unit_rows_match(w):
    rows, fix = _fix_rows(w), w.values["seen"].get("fix", "")
    return ([r["key"] for r in rows] == [u["key"] for u in rec(w)["units"]] and any(r["owed"] for r in rows)
            and all(f'"key": {json.dumps(r["key"], ensure_ascii=False)}' in fix for r in rows))


def _long_bodies_not_pasted(w):
    rows, fix = _fix_rows(w), w.values["seen"].get("fix", "")
    judged = [u for u in rec(w)["process"]["diagnosis"]["units"] if u.get("class_query")]
    refs = re.findall(r"置き場 (\S+?record\.json)（", fix)
    return bool(judged and all(r["has_class_query"] for r in rows) and '"class_query"' not in fix and refs
                and all(pathlib.Path(x).is_file() for x in refs))


def _policy_row_points_to_diff(w):
    row_, diff = _policy_diff(last(w))
    return bool("WRITER-POLICY" not in row_ and diff and "+" + WRITER_POLICY in pathlib.Path(diff).read_text(encoding="utf-8"))


def _policy_refixed(w):
    pol = rec(w)["process"]["policy"]
    _, diff = _policy_diff(last(w))
    return (len(pol["amendments"]) == 1 and pol["path"] == str(review.policy_default(w.run).resolve()) and len(pol["sha256"] or "") == 64
            and st(w)["inputs"].get("policy_md") is None and "WRITER-POLICY" in pathlib.Path(pol["copy"]).read_text(encoding="utf-8")
            and pol["amendments"][0]["diff_file"] == diff)


def _stop_answer(w):
    w.run.cmd("answer", "--text", "stop", "--note", "削らない向きで出し直す")
    return w.run.next()


def _excluded(w):
    v, hi = w.values, rec(w)["process"]["human_items"]
    asked = (last(w).get("ask") or {}).get("question", "")
    return ("--detail" in asked and "1. " in asked and v["bad"]["rc"] == 1 and "直す義務の単位でない" in v["bad"]["err"] and not v["hi_after_bad"]
            and v["good"]["rc"] == 0 and hi and hi[-1].get("excluded") == [{"unit": v["unit1"], "why": EXCLUDE_WHY}])


HUMAN_GATE = [
    row(S, "関所: 修正案の narrows が 1 件でもあれば、修正の前に人に聞く", "review/gate/asked1",
        lambda w, g: last(w)["status"] == "awaiting_human" and last(w)["ask"].get("in_round") and kinds(w) == ["regression"]
        and "NARROW-1" in "".join(last(w)["ask"]["items"]), id="narrows-ask-before-fix", kept=KEPT),
    row(S, "関所: 人が答えるまで修正の節は出ない", "review/gate/asked1",
        lambda w, g: not any(i["node"] == "p3.fix" for i in st(w)["rounds"][0]["instances"].values()), id="no-fix-until-answered", kept=KEPT),
    row(S, "関所: 方針の文書が無い run では、固定する版は無く", "review/gate/asked1",
        lambda w, g: rec(w)["process"]["policy"]["path"] is None and "人の方針" in w.values["seen"].get("diagnose", ""),
        id="no-policy-document", kept=KEPT),
    row(S, "関所: continue を返す", "review/gate/asked1", lambda w, g: g.returncode == 0,
        when=lambda w: w.run.cmd("answer", "--text", "continue", "--note", "呼び元の経路は残せ（検査用 KEEP-NOTE）"), id="answer-continue",
        kept=KEPT),
    row(S, "関所: 答えは人の答えの台帳（process.human_items）に残る", "review/gate/answered1",
        lambda w, g: len(hi := rec(w)["process"]["human_items"]) == 1 and hi[0]["node"] == "p2.human_gate" and hi[0]["answer"] == "continue"
        and "KEEP-NOTE" in hi[0]["note"], id="answer-in-human-items", kept=KEPT),
    row(S, "関所: 人の答えの note が同じ周の修正役のプロンプトに届く", "review/gate/asked2",
        lambda w, g: "KEEP-NOTE" in w.values["seen"].get("fix", ""), id="note-reaches-fix", kept=KEPT),
    row(S, "修正の入口: 単位の行は記録の単位と同じ順で全部載り", "review/gate/asked2", lambda w, g: _unit_rows_match(w),
        id="fix-unit-rows", kept=KEPT),
    row(S, "修正の入口: 判定の長い本文（母数の問いなど）は貼らず", "review/gate/asked2", lambda w, g: _long_bodies_not_pasted(w),
        id="fix-long-bodies-not-pasted", kept=KEPT),
    row(S, "関所: 修正差分の審査は後退の語を使えない", "review/gate/asked2",
        lambda w, g: (d := w.values["seen"].get("delta") or [0, ""])[0] == 1 and "事前審査だけ" in d[1], id="delta-review-no-regression",
        kept=KEPT),
    row(S, "関所: 方針の文書が init の後に変わった", "review/gate/asked2",
        lambda w, g: last(w)["status"] == "awaiting_human" and kinds(w) == ["policy_changed"], id="policy-changed-asks", kept=KEPT),
    row(S, "関所: 方針の文書の変化の行は差分のファイルの置き場を載せ", "review/gate/asked2", lambda w, g: _policy_row_points_to_diff(w),
        id="policy-row-points-to-diff", kept=KEPT),
    row(S, "関所: 通した方針の文書の変更は新しい版", "review/gate/answered2", lambda w, g: _policy_refixed(w), id="policy-refixed",
        kept=KEPT),
    row(S, "関所: R4 の lost と方針とのぶつかり", "review/gate/end",
        lambda w, g: w.values["asked"] == {"LOST-1": 1, "CONFLICT-1": 1} and {"regression", "policy"} <= set(w.values["kinds"]),
        id="lost-and-conflict-asked-once", kept=KEPT),
    row(S, "関所: 人が通した後は収束まで進む", "review/gate/end", lambda w, g: last(w)["status"] == "converged", id="converges", kept=KEPT),
    row(S, "関所: 事前審査が後退の穴を挙げたら、修正の前に人に聞く", "review/gatestop/asked",
        lambda w, g: last(w)["status"] == "awaiting_human" and kinds(w) == ["regression"]
        and "事前審査の穴 [regression]" in "".join(last(w)["ask"]["items"]), id="plan-review-regression-asks"),
    row(S, "関所: stop で run がその場で止まり、修正を出さない", "review/gatestop/asked",
        lambda w, g: g["status"] == "stopped" and g.get("halted", {}).get("node") == "p2.human_gate" and not g["ready"],
        when=_stop_answer, id="stop-halts-at-gate"),
    row(S, "関所: --detail で直す義務の単位を外せる", "review/gateex/excluded", lambda w, g: _excluded(w), id="detail-excludes-unit"),
    row(S, "関所: 外した単位は修正の側に見せる義務の印", "review/gateex/excluded",
        lambda w, g: [r.get("owed") for r in _fix_rows(w) if r.get("key") == w.values["unit1"]] == [False], id="excluded-unit-not-owed"),
    row(S, "関所: 外した単位と理由が同じ周の修正役のプロンプトに届く", "review/gateex/fix",
        lambda w, g: "EXCLUDE-WHY" in w.values["seen"].get("fix", ""), id="exclusion-reaches-fix"),
    row(S, "関所: 無人では狭めの問いで止まり、修正を出さない", "review/gateun/end",
        lambda w, g: last(w)["status"] == "stopped" and (st(w).get("halted") or {}).get("by") == "unattended"
        and not any(i["node"] == "p3.fix" for i in st(w)["rounds"][0]["instances"].values()), id="unattended-stops"),
]


@pytest.mark.parametrize("given, when, then", HUMAN_GATE)
def test_human_gate(wave, given, when, then):
    play(wave, given, when, then)
