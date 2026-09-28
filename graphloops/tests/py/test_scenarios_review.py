"""層 2 の筋書き（review）: 上限で止まる類と、止める・人待ちの台本（graphloops/tests/simulate_review.py）の check の移し先（T2）と、
移す順の (3)(4) のうち今の出来事で書ける関数（T3）の移し先。

列（history）は台本の関数の中の Run 1 つが打った出来事を元の順に並べたデータで、行はその列の印を指す（形と規範は scenes.py と
docs/adr/0067）。1 行が台本の check 1 件で、行の印 ``moved_from`` が名乗る（台帳は ledger.py。台本の関数を消した行は印を持たない）。
"""
import json
import pathlib
import re

import glharness
import pytest
from scenes import NONE, cmd, done, file, history, init, look, loop, merged, nxt, play, prompt, replaced, roles, row, rule, until, write

review = glharness.script("review")
pytestmark = [pytest.mark.medium, pytest.mark.layer2]
KEPT = "通しに残す 10 本（docs/adr/0067）——cli の口で回す台本を、同じ振る舞いの層 2 の筋書きと突き合わせる相手"
POLICY = ".git/graphloops/policy.md"   # 人の方針の文書の既定の置き場（型のリポジトリからの道。台本の policy_default と同じ所）

for base in ("std", "awaiting", "premise", "runaway", "cired"):
    roles(base)


def rec(s):
    return s.board.record()


def st(s):
    return s.board.state()


def kinds(reply):
    return ((reply or {}).get("ask") or {}).get("kinds")


# ---- 上限で止まる類 -----------------------------------------------------------------------------------------------------

S = None
history("review/runaway", init("runaway", unattended=True), until("runaway", mark="end"))
RUNAWAY = [
    row(S, "5 周で停止", "review/runaway", "end", lambda s: s.reply["status"] == "stopped" and st(s)["round"] == 5, id="stops-at-round-5"),
    # 旧い check の 2 つの枝（記録の停止理由の暴走ガード・盤面の loop の max_rounds）を落とさない
    row(S, "停止の理由が上限", "review/runaway", "end",
        lambda s: "暴走ガード" in rec(s)["process"].get("stop_reason", "") or st(s)["loop"].get("stop_reason") == "max_rounds",
        id="stop-reason-is-the-cap"),
]


@pytest.mark.parametrize("name, at, expect", RUNAWAY)
def test_runaway(scene, name, at, expect):
    play(scene, name, at, expect)


S = "simulate_review.test_ci_red_runaway"
CI_RED = [{"name": "suite", "argv": [review.PY, "-c", "import sys; print('1 failed'); sys.exit(1)"]}]   # engine が走らせて毎周赤
history("review/cired", init("cired", unattended=True, checks=CI_RED), until("cired", mark="end"))
CI_RED_RUNAWAY = [
    row(S, "CI が赤のままの run は 5 周で止まる", "review/cired", "end", lambda s: s.reply["status"] == "stopped" and st(s)["round"] == 5,
        id="stops-at-round-5"),
    row(S, "停止の理由が上限", "review/cired", "end", lambda s: st(s)["loop"].get("stop_reason") == "max_rounds", id="stop-reason-max-rounds"),
]


@pytest.mark.parametrize("name, at, expect", CI_RED_RUNAWAY)
def test_ci_red_runaway(scene, name, at, expect):
    play(scene, name, at, expect)


# ---- 人待ち -------------------------------------------------------------------------------------------------------------

S = None
roles("noawait", rule("p4.ci", once="rc", before=[
    done("@", {"material": review.M("awaiting_human", reason="runner で確かめる話があるので（検査用の取り違え）")}, mark="rc")]), base="std")
history("review/noawait", init("noawait", checks=None), until("noawait", stop={"round": 2}, catch=True, mark="end"))
NO_NEW_AWAITING = [
    row(S, "判定の後の人待ち: 問いの無い awaiting_human を書いた p4.ci は拒む", "review/noawait", "end",
        lambda s: (r := s.got.get("rc", NONE)).returncode == 1 and "人待ちの問い（kind=awaiting）が無い" in r.stderr and "not_run" in r.stderr,
        id="p4-ci-awaiting-without-question"),
]


@pytest.mark.parametrize("name, at, expect", NO_NEW_AWAITING)
def test_no_new_awaiting_after_judge(scene, name, at, expect):
    play(scene, name, at, expect)


S = "simulate_review.test_awaiting"
LIE = review.CLEAN("画面は未観測だが異常なし（検査用の嘘）")
roles("await", rule("p1.main_path_observation", once="lied", before=[
    done("@", {"material": LIE, "observed": []}, mark="lied"),
    done("@", {"material": LIE, "observed": [{"path": " ", "value": " "}]}, mark="blank")]), base="awaiting")
history("review/await", init("await"), until("await", catch=True, mark="asked"),
        cmd("answer", "--text", "continue", "--note", "テスト用設定 config/dev.local.example で起動できる", mark="answer"),
        until("awaiting", mark="end"))
AWAITING = [
    row(S, "主経路の観測: 見たと言う状態なのに観測した値が無ければ exit 1", "review/await", "asked",
        lambda s: (r := s.got.get("lied", NONE)).returncode == 1 and "observed" in r.stderr, id="observed-empty"),
    row(S, "主経路の観測: 空白だけの観測の行も観測した値に数えない", "review/await", "asked",
        lambda s: (r := s.got.get("blank", NONE)).returncode == 1 and "observed" in r.stderr, id="observed-blank"),
    row(S, "残る阻害が保留の問いだけになった周に聞く", "review/await", "asked",
        lambda s: s.reply["status"] == "awaiting_human" and kinds(s.reply) == ["work_exhausted"], id="asks-work-exhausted"),
    row(S, "立った周（1）には聞かず、2 周目に聞く", "review/await", "asked", lambda s: st(s)["round"] == 2, id="asks-in-round-2"),
    row(S, "答えを渡して続行", "review/await", "answer", lambda s: s.reply.returncode == 0, id="answer-continue"),
    row(S, "答えの後に収束", "review/await", "end", lambda s: s.reply["status"] == "converged", id="converges-after-answer"),
    row(S, "3 周目に観測して問いは resolved", "review/await", "end",
        lambda s: (r3 := s.board.round(3))["materials"]["main_path_observation"]["status"] == "clean"
        and any(q["status"] == "resolved" for q in r3["questions"]), id="round-3-resolves"),
    row(S, "人の答えが記録に残り次の周の judge に渡る", "review/await", "end",
        lambda s: any("config/dev.local.example" in (a.get("note") or "") for a in rec(s)["process"]["human_answers"]),
        id="answer-kept-in-record"),
]


@pytest.mark.parametrize("name, at, expect", AWAITING)
def test_awaiting(scene, name, at, expect):
    play(scene, name, at, expect)


S = "simulate_review.test_awaiting_origin_guards"
FIELD_Q = {"key": "Windows の実機で動かしたか", "kind": "field", "status": "held", "reason": "手元にも CI にも Windows の実機が無い（検査用）"}
WAIT_CI = {"key": "CI をどこで走らせるか", "kind": "awaiting", "origin": "local_checks", "status": "held", "reason": "手元で CI を走らせられない（検査用）"}
roles("awaitorigin",
      rule("p0.local_checks", reply=replaced({"material": review.M("awaiting_human", reason="CI 専用のジョブで手元では走らない（検査用）")})),
      rule("p2.diagnose", round=1, before=[
          done("@", merge={"questions": [FIELD_Q]}, agent_id="judge-1", mark="unlisted"),
          done("@", merge={"questions": [WAIT_CI, {"key": "Windows の実機で動かしたか", "kind": "awaiting", "origin": "main_path_observation",
                                                   "status": "held", "reason": "（検査用）"}]}, agent_id="judge-1", mark="judge")],
           reply=merged({"questions": [WAIT_CI, FIELD_Q]})),
      rule("p4.ci", round=1, before=[prompt(mark="ci_prompt"), done("@", {"material": review.CLEAN("pytest 緑（検査用）")}, mark="ci")],
           reply=replaced({"material": review.M("awaiting_human", reason="手元の pytest は緑。CI 専用のジョブは人待ち（検査用）")})),
      base="std")
history("review/awaitorigin", init("awaitorigin", checks=None), until("awaitorigin", stop={"round": 2}, catch=True, mark="end"))


def _round1(s):
    return s.board.round(1) if s.board.has("rounds/round-1.json") else {"questions": [], "materials": {}}


AWAITING_ORIGIN_GUARDS = [
    row(S, "判定の時点: 人待ちの素材を出どころにする問いを台帳に載せない判定は拒む", "review/awaitorigin", "end",
        lambda s: (r := s.got.get("unlisted", NONE)).returncode == 1 and "素材 'local_checks' が awaiting_human なのに台帳に kind=awaiting で無い" in r.stderr,
        id="judge-unlisted"),
    row(S, "判定の時点: 人待ちでない素材を出どころにした awaiting は拒み", "review/awaitorigin", "end",
        lambda s: (r := s.got.get("judge", NONE)).returncode == 1 and all(x in r.stderr for x in ("awaiting の出どころは", "main_path_observation", "kind=field")),
        id="judge-wrong-origin"),
    row(S, "書いた時点: 人に諮っている欄を後の工程が clean で上書きすると拒む", "review/awaitorigin", "end",
        lambda s: (r := s.got.get("ci", NONE)).returncode == 1 and "local_checks" in r.stderr and "awaiting_human のまま書け" in r.stderr,
        id="ci-overwrite"),
    row(S, "CI を再実行する節のプロンプトに、この周の問いの台帳が渡る", "review/awaitorigin", "end",
        lambda s: WAIT_CI["key"] in s.got.get("ci_prompt", ""), id="ci-prompt-has-ledger"),
    row(S, "実地の問いは field で台帳に載り", "review/awaitorigin", "end",
        lambda s: any(q["kind"] == "field" and not q.get("origin") for q in _round1(s)["questions"])
        and _round1(s)["materials"].get("local_checks", {}).get("status") == "awaiting_human", id="field-question-kept"),
]


@pytest.mark.parametrize("name, at, expect", AWAITING_ORIGIN_GUARDS)
def test_awaiting_origin_guards(scene, name, at, expect):
    play(scene, name, at, expect)


S = None
roles("gate-empty", rule("p4.final_gates", reply=merged({"arms": [], "handled": []})), base="std")
history("review/gate-empty", init("gate-empty"), until("gate-empty", mark="asked"),
        cmd("answer", "--text", "continue", "--note", "文書だけの差分と確かめた（検査用）", mark="answer"), until("gate-empty", mark="end"))
# 2 本目の run は、1 本目が 0 本の関門で諮った周を上限にする
history("review/gate-empty-max", init("gate-empty-max"),
        cmd("patch", "--path", "state.max_rounds", "--file", file("max.json", ref=("review/gate-empty", "asked", "state", "round")),
            "--reason", "台本: 上限の周で 0 本にする", mark="max"),
        until("gate-empty", mark="asked"), cmd("answer", "--text", "continue", "--note", "確かめた（検査用）", mark="answer"),
        until("gate-empty", mark="end"))


def _extended_by_one(s):
    a = s.got["max"]["files"]["max.json"]
    return st(s)["max_rounds"] == a + 1 and (rec(s)["process"].get("human_answers") or [{}])[-1].get("max_rounds") == {"from": a, "to": a + 1}


FINAL_GATE_EMPTY = [
    row(S, "撃てた腕が 0 本の関門で収束を言わず人に諮る", "review/gate-empty", "asked",
        lambda s: s.reply["status"] == "awaiting_human" and kinds(s.reply) == ["final_gate_empty"], id="asks-on-empty-gate"),
    row(S, "諮る前に止めた理由（stop_reason）を立てる", "review/gate-empty", "asked",
        lambda s: st(s)["loop"].get("stop_reason") == "final_gate_empty", id="stop-reason-before-asking"),
    row(S, "continue を返す", "review/gate-empty", "answer", lambda s: s.reply.returncode == 0, id="answer-continue"),
    row(S, "人が認めた木なら、次の周の 0 本の関門で収束する", "review/gate-empty", "end", lambda s: s.reply["status"] == "converged",
        id="converges-next-round"),
    row(S, "上限の周でも 0 本の関門は人に諮る", "review/gate-empty-max", "asked",
        lambda s: s.reply["status"] == "awaiting_human" and kinds(s.reply) == ["final_gate_empty"], id="asks-at-max-round"),
    row(S, "上限の周の continue は上限を 1 周だけ延ばし", "review/gate-empty-max", "answer", _extended_by_one, id="continue-extends-by-one"),
    row(S, "延ばした次の周で、同じ木の 0 本の関門が通って収束する", "review/gate-empty-max", "end", lambda s: s.reply["status"] == "converged",
        id="converges-after-extension"),
]


@pytest.mark.parametrize("name, at, expect", FINAL_GATE_EMPTY)
def test_final_gate_empty_asks_human(scene, name, at, expect):
    play(scene, name, at, expect)


# ---- 止める ---------------------------------------------------------------------------------------------------------------

S = "simulate_review.test_stop_midround"
AT_FIX_PLAN = {"ready": "p2.fix_plan"}
history("review/stop-mid", init("stop-mid"), until("std", stop=AT_FIX_PLAN), cmd("stop", "--reason", " ", mark="empty"),
        cmd("stop", "--reason", "検査: 修正案の前で止める", mark="stop"), done("p2.fix_plan", {}, mark="late"),
        cmd("stop", "--reason", "二度目", mark="second"), nxt(mark="next"), until("std", mark="end"))
history("review/stop-stale", init("stop-stale"), until("std", stop=AT_FIX_PLAN), write("dir", "rounds/round-1.json", '{"stale": true}'),
        cmd("stop", "--reason", "検査: 負けた試行の残したファイルの上で止める", mark="stop"))
history("review/stop-r2", init("stop-r2"), until("std", stop={"round": 2}), look(mark="prev"),
        cmd("stop", "--reason", "検査: 2 周目の頭で止める", mark="stop"))
history("review/stop-ask", init("stop-ask"), until("premise", mark="asked"), cmd("stop", "--reason", "検査: 人に聞いている最中に止める", mark="stop"))
# 宣言（graph の stop）の無い graph の写しで回す run（init の版が古い run）
history("review/stop-nodecl", init("stop-nodecl", graph_drop=("stop",)), until("std", stop=AT_FIX_PLAN),
        cmd("stop", "--reason", "検査: 宣言の無い graph", mark="stop"), nxt(mark="next"),
        cmd("stop", "--reason", "検査: 止まった run をもう一度止める", mark="again"))


def _stopped_round_record(rf):
    return (all(rf["reviews"][k]["status"] == "not_run" and "人が止めた" in rf["reviews"][k]["reason"] for k in ("R1", "R2", "R3", "R4"))
            and rf["materials"]["fix_closure"]["status"] == "not_run" and "人が止めた" in rf["materials"]["fix_closure"]["reason"])


def _stopped_while_asking(s):
    proc = rec(s)["process"]
    un = (proc.get("halted") or {}).get("unanswered") or {}
    hi = [h for h in proc.get("human_items") or [] if "答えないまま人が止めた" in (h.get("note") or "") and h.get("answer") is None]
    asked = s.got["asked"]
    return (asked["status"] == "awaiting_human" and s.reply.returncode == 0 and un.get("question") and un.get("node") == asked["ask"].get("node")
            and "pending_human" not in st(s) and len(hi) == 1)


def _prev_round_kept(s):
    prev, r = s.got["prev"]["rounds"]["1"], rec(s)
    return s.reply.returncode == 0 and r["units"] == prev["units"] and r["questions"] == prev["questions"] and not s.board.has("rounds/round-2.json")


STOP_MIDROUND = [
    row(S, "止める: 理由の空は拒む", "review/stop-mid", "empty", lambda s: s.reply.returncode == 1 and "理由が空" in s.reply.stderr,
        id="empty-reason", kept=KEPT),
    row(S, "止める: 宣言の在る graph では halted にせず報告へ進む", "review/stop-mid", "stop",
        lambda s: s.reply.returncode == 0 and s.reply.json()["stopped"]["report"] is True and st(s)["status"] == "stopped" and "halted" not in st(s),
        id="declared-graph-goes-to-report", kept=KEPT),
    row(S, "止める: 待ちの節は止めた印（省いた印と別）になる", "review/stop-mid", "stop",
        lambda s: "p2.fix_plan" in (rd := st(s)["rounds"][-1])["stopped"] and rd["instances"]["p2.fix_plan"]["status"] == "stopped"
        and "p2.fix_plan" not in rd["skipped"], id="pending-node-marked-stopped", kept=KEPT),
    row(S, "止める: 止めた周の記録は、走らなかった R と素材を止めた事実で書く", "review/stop-mid", "stop",
        lambda s: _stopped_round_record(s.board.round(1)), id="round-record-says-stopped", kept=KEPT),
    row(S, "止める: 止めた時点で記録に理由が入る", "review/stop-mid", "stop",
        lambda s: bool(s.board.round(1)["units"]) and rec(s)["process"]["halted"]["reason"] == "検査: 修正案の前で止める",
        id="reason-in-record", kept=KEPT),
    row(S, "止める: 止めた節の返答は受け付けない", "review/stop-mid", "late", lambda s: s.reply.returncode == 1 and "stopped" in s.reply.stderr,
        id="late-reply-rejected", kept=KEPT),
    row(S, "止める: 止まった run は二度止めない", "review/stop-mid", "second",
        lambda s: s.reply.returncode == 1 and "止める物が無い" in s.reply.stderr, id="no-second-stop", kept=KEPT),
    row(S, "止める: 次の next は報告の節だけを出す", "review/stop-mid", "next",
        lambda s: [i["node"] for i in s.reply["ready"]] == ["report.human_items"], id="next-is-report-only", kept=KEPT),
    row(S, "止める: 報告まで届き、仕上げた記録に止めた口と止めた節が残る", "review/stop-mid", "end",
        lambda s: s.reply["status"] == "stopped" and s.board.has("report.md")
        and (p := rec(s)["process"])["stop_reason"] == "stop" and p["outcome"] == "stopped"
        and any(x["node"] == "p2.fix_plan" for x in p["stopped_nodes"]) and not any(x["node"] == "p2.fix_plan" for x in p["skipped"]),
        id="reaches-report", kept=KEPT),
    row(S, "止める: 残ったファイルを済んだと読まず", "review/stop-stale", "stop",
        lambda s: s.reply.returncode == 0 and "stale" not in (rf := s.board.round(1)) and rf["reviews"] == (r := rec(s))["reviews"]
        and all(r["reviews"][k]["status"] == "not_run" for k in ("R1", "R2", "R3", "R4")), id="stale-round-file", kept=KEPT),
    row(S, "止める: 2 周目の判定より前なら前の周の単位と台帳を報告に残す", "review/stop-r2", "stop", _prev_round_kept,
        id="stop-before-round-2-judge", kept=KEPT),
    row(S, "止める: 人に聞いている最中なら", "review/stop-ask", "stop", _stopped_while_asking, id="stop-while-asking", kept=KEPT),
    row(S, "止める: 宣言の無い graph は halted（by=stop）で後の節を出さない", "review/stop-nodecl", "next",
        lambda s: (r := s.got["stop"]).returncode == 0 and "報告の節は出ない" in r.stdout and s.reply["halted"]["by"] == "stop" and not s.reply["ready"],
        id="undeclared-graph-halts", kept=KEPT),
    row(S, "止める: halted の run は『もう止まっている』で拒む", "review/stop-nodecl", "again",
        lambda s: s.reply.returncode == 1 and "もう止まっている" in s.reply.stderr, id="halted-run-refuses-stop", kept=KEPT),
]


@pytest.mark.parametrize("name, at, expect", STOP_MIDROUND)
def test_stop_midround(scene, name, at, expect):
    play(scene, name, at, expect)


S = "simulate_review.test_stop_after_round"
history("review/stop1", init("stop1", init_args=["--stop-after-round", "1"], mark="init"), until("std", mark="end1"), nxt(mark="next"),
        cmd("status", mark="status"), cmd("finalize", mark="finalize"), look(mark="r1"),
        cmd("resume", "--reason", "検査: 続ける", "--stop-after-round", "2", mark="resume"), until("std", mark="end2"),
        cmd("finalize", mark="finalize2"))
history("review/stop2", init("stop2", init_args=["--stop-after-round", "2"]), until("std", mark="end"))
history("review/stop1-answer", init("stop1-answer", init_args=["--stop-after-round", "1"]), until("premise", mark="asked"),
        cmd("answer", "--text", "continue", "--note", "続けて（検査用）", mark="answer"))
history("review/stop0", init("stop0", init_args=["--stop-after-round", "0"], mark="init"))


def _halts(s):
    return [json.loads(x) for x in s.board.lines("trace.jsonl") if '"halted"' in x]


def _resumed(s):
    return (s.reply.returncode == 0 and (x := st(s))["round"] == 2 and x["status"] == "running" and "halted" not in x
            and x["rounds"][0]["instances"] == s.got["r1"]["state"]["rounds"][0]["instances"] and not x.get("patches"))


STOP_AFTER_ROUND = [
    row(S, "init が --stop-after-round を受ける", "review/stop1", "init", lambda s: s.reply.returncode == 0, id="init-accepts"),
    row(S, "1 周目の締めの後の next が stopped と halted", "review/stop1", "end1",
        lambda s: s.reply["status"] == "stopped" and (s.reply.get("halted") or {}).get("by") == "stop_after_round" and not s.reply["ready"],
        id="stops-after-round-1"),
    row(S, "周の締め（周の記録・converge）は済み、2 周目は開いていない", "review/stop1", "end1",
        lambda s: (x := st(s))["round"] == 1 and len(x["rounds"]) == 1 and "converge" in x["rounds"][0]["done"] and s.board.has("rounds/round-1.json"),
        id="round-closed-not-opened"),
    row(S, "止めた後の next は節を出さず、止めた口を言う", "review/stop1", "next",
        lambda s: s.reply["status"] == "stopped" and not s.reply["ready"] and s.reply["halted"]["by"] == "stop_after_round"
        and "stop_after_round" in s.reply["note"], id="next-after-stop"),
    row(S, "status に halted と stop_after_round が出る", "review/stop1", "status",
        lambda s: (g := s.reply.json())["halted"]["by"] == "stop_after_round" and g["stop_after_round"] == 1 and g["status"] == "stopped",
        id="status-shows-halted"),
    row(S, "仕上げた記録に止めた理由が残る", "review/stop1", "finalize",
        lambda s: (p := rec(s)["process"]).get("outcome") == "stopped" and p.get("stop_reason") == "stop_after_round", id="finalized-reason"),
    row(S, "止めたことは trace にも 1 行残る", "review/stop1", "finalize",
        lambda s: [(x.get("op"), x.get("by"), x.get("round")) for x in _halts(s)] == [("halted", "stop_after_round", 1)], id="trace-has-one-halt"),
    row(S, "resume が 2 周目を開き、1 周目の試行はそのまま", "review/stop1", "resume", _resumed, id="resume-opens-round-2"),
    row(S, "続けた run は新しい止め周（2 周目）の締めで止まり", "review/stop1", "end2",
        lambda s: s.reply["status"] == "stopped" and (x := st(s))["halted"]["by"] == "stop_after_round" and x["halted"]["round"] == 2
        and [r["prev_halted"]["round"] for r in x["resumes"]] == [1], id="resumed-stops-at-round-2"),
    row(S, "続けた痕跡は記録の process.resumes にも写る", "review/stop1", "finalize2",
        lambda s: [x["reason"] for x in rec(s)["process"].get("resumes", [])] == ["検査: 続ける"], id="resumes-in-record"),
    row(S, "--stop-after-round 2 は 1 周目の後は次の周を開き", "review/stop2", "end",
        lambda s: s.reply["status"] == "stopped" and (x := st(s))["halted"]["round"] == 2 and len(x["rounds"]) == 2, id="stop-after-2"),
    row(S, "answer continue でも次の周を開かずに止まる", "review/stop1-answer", "answer",
        lambda s: s.got["asked"]["status"] == "awaiting_human" and s.reply.returncode == 0 and "halted" in s.reply.stdout
        and (x := st(s))["status"] == "stopped" and x["halted"]["by"] == "stop_after_round" and len(x["rounds"]) == 1,
        id="answer-continue-also-stops"),
    row(S, "--stop-after-round 0 は init が拒み、盤面を残さない", "review/stop0", "init",
        lambda s: s.reply.returncode == 2 and "1 以上" in s.reply.stderr and not s.board.has(), id="zero-rejected-at-init"),
]


@pytest.mark.parametrize("name, at, expect", STOP_AFTER_ROUND)
def test_stop_after_round(scene, name, at, expect):
    play(scene, name, at, expect)


# ---- 人の決定権の関所 -----------------------------------------------------------------------------------------------------

S = "simulate_review.test_human_gate"
WRITER_POLICY = "修正役が書いた方針（検査用 WRITER-POLICY）"
EXCLUDE_WHY = "この周は触らない（検査用 EXCLUDE-WHY）"
roles("gate",
      rule("p2.diagnose", once="diagnose", before=[prompt(mark="diagnose")]),
      rule("p2.fix_plan", round=1, reply=merged({"narrows": [{"what": "呼び元が上限なしで呼べる経路（検査用 NARROW-1）",
                                                              "why": "上限を入口 1 か所に寄せると呼び元の分岐が消える（検査用）"}]}, at=("plan", 0))),
      # 役が方針の文書を書き換える形
      rule("p3.fix", round=1, before=[prompt(mark="fix"), write("repo", POLICY, WRITER_POLICY + "\n")]),
      rule("p3.delta_review", once="delta", before=[done("@", merge={"faces": [{
          "key": "後退: 呼び元の経路", "kind": "regression", "where": "src/a.py", "cite": "limit", "why": "呼び元の上限なしの経路が消えた（検査用）"}]}, mark="delta")]),
      rule("r4.hidden_scope", reply=merged({"capability_inventory": {"fired": True, "lost": ["呼び元の上限なしの経路（検査用 LOST-1）"]},
                                            "policy_conflicts": ["期限を足した（検査用 CONFLICT-1）"]})),
      base="std")
history("review/gate", init("gate"), until("gate", mark="asked1"),
        cmd("answer", "--text", "continue", "--note", "呼び元の経路は残せ（検査用 KEEP-NOTE）", mark="answer1"), until("gate", mark="asked2"),
        cmd("answer", "--text", "continue", "--note", "確かめた（検査用）", mark="answer2"),
        # 人が通すたびに次の関所まで回す（6 回まで）。R4 の lost と方針とのぶつかりを聞かれた回数は、返事の並びから数える
        loop(until("gate"), cmd("answer", "--text", "continue", "--note", "消えてよい（検査用）"), times=6, mark="rest"))
roles("gate-stop", rule("p2.plan_review", reply=merged({"faces": [{
    "key": "後退: 上限なしで呼べる経路が消える", "unit_keys": [1], "kind": "regression", "where": "src/a.py",
    "why": "案が呼び元の分岐を消すと、上限なしの呼び出しができなくなる（検査用）", "severity": "block"}]})), base="std")
history("review/gate-stop", init("gate-stop"), until("gate-stop", mark="asked"), cmd("answer", "--text", "stop", "--note", "削らない向きで出し直す"),
        nxt(mark="next"))
roles("gate-exclude",
      rule("p2.fix_plan", reply=merged({"narrows": [{"what": "検査用の狭め", "why": "関所を立てるため（検査用）"}]}, at=("plan", 0))),
      rule("p3.fix", once="fix", before=[prompt(mark="fix")]),
      base="std")
history("review/gate-exclude", init("gate-exclude"), until("gate-exclude", mark="asked"),
        cmd("answer", "--text", "continue", "--note", "通す（検査用）", "--detail",
            file("bad.json", {"exclude": [{"unit": "義務に無い単位（検査用）", "why": "外す（検査用）"}]}), mark="bad"),
        look(mark="after_bad"),
        cmd("answer", "--text", "continue", "--note", "通す（検査用）", "--detail", file("good.json", {"exclude": [{"unit": 1, "why": EXCLUDE_WHY}]}),
            mark="good"),
        until("gate-exclude", stop={"got": "fix"}, mark="to_fix"))
roles("gate-unattended", rule("p2.fix_plan", reply=merged({"narrows": [{"what": "検査用の狭め", "why": "無人で止まるか（検査用）"}]}, at=("plan", 0))),
      base="std")
history("review/gate-unattended", init("gate-unattended", unattended=True), until("gate-unattended", mark="end"))


def _policy_diff(reply):
    row_ = "".join(reply["ask"]["items"])
    return row_, (row_.split("差分 ", 1)[-1].split("・", 1)[0] if "差分 " in row_ else "")


def _fix_rows(s):
    return (st(s)["loop"].get("fix_units") or {}).get("rows") or []


def _unit_rows_match(s):
    rows, fix = _fix_rows(s), s.got.get("fix", "")
    return ([r["key"] for r in rows] == [u["key"] for u in rec(s)["units"]] and any(r["owed"] for r in rows)
            and all(f'"key": {json.dumps(r["key"], ensure_ascii=False)}' in fix for r in rows))


def _long_bodies_not_pasted(s):
    rows, fix = _fix_rows(s), s.got.get("fix", "")
    judged = [u for u in rec(s)["process"]["diagnosis"]["units"] if u.get("class_query")]
    refs = re.findall(r"置き場 (\S+?record\.json)（", fix)
    return bool(judged and all(r["has_class_query"] for r in rows) and '"class_query"' not in fix and refs
                and all(pathlib.Path(x).is_file() for x in refs))


def _policy_row_points_to_diff(s):
    row_, diff = _policy_diff(s.reply)
    return bool("WRITER-POLICY" not in row_ and diff and "+" + WRITER_POLICY in s.board.read(diff))


def _policy_refixed(s):
    pol = rec(s)["process"]["policy"]
    _, diff = _policy_diff(s.got["asked2"])
    return (len(pol["amendments"]) == 1 and pol["path"] == str((s.board.repo / POLICY).resolve()) and len(pol["sha256"] or "") == 64
            and st(s)["inputs"].get("policy_md") is None and "WRITER-POLICY" in s.board.read(pol["copy"])
            and pol["amendments"][0]["diff_file"] == diff)


def _asked_once(s):
    asked = [r for r in s.reply if r["status"] == "awaiting_human"]
    counts = {k: sum(k in "".join(r["ask"]["items"]) for r in asked) for k in ("LOST-1", "CONFLICT-1")}
    return counts == {"LOST-1": 1, "CONFLICT-1": 1} and {"regression", "policy"} <= {k for r in asked for k in r["ask"]["kinds"]}


def _excluded(s):
    hi, bad = rec(s)["process"]["human_items"], s.got["bad"]
    asked = (s.got["asked"].get("ask") or {}).get("question", "")
    unit1 = rec(s)["units"][0]["key"]
    return ("--detail" in asked and "1. " in asked and bad.returncode == 1 and "直す義務の単位でない" in bad.stderr
            and not s.got["after_bad"]["record"]["process"]["human_items"]
            and s.reply.returncode == 0 and hi and hi[-1].get("excluded") == [{"unit": unit1, "why": EXCLUDE_WHY}])


HUMAN_GATE = [
    row(S, "関所: 修正案の narrows が 1 件でもあれば、修正の前に人に聞く", "review/gate", "asked1",
        lambda s: s.reply["status"] == "awaiting_human" and s.reply["ask"].get("in_round") and kinds(s.reply) == ["regression"]
        and "NARROW-1" in "".join(s.reply["ask"]["items"]), id="narrows-ask-before-fix", kept=KEPT),
    row(S, "関所: 人が答えるまで修正の節は出ない", "review/gate", "asked1",
        lambda s: not any(i["node"] == "p3.fix" for i in st(s)["rounds"][0]["instances"].values()), id="no-fix-until-answered", kept=KEPT),
    row(S, "関所: 方針の文書が無い run では、固定する版は無く", "review/gate", "asked1",
        lambda s: rec(s)["process"]["policy"]["path"] is None and "人の方針" in s.got.get("diagnose", ""), id="no-policy-document", kept=KEPT),
    row(S, "関所: continue を返す", "review/gate", "answer1", lambda s: s.reply.returncode == 0, id="answer-continue", kept=KEPT),
    row(S, "関所: 答えは人の答えの台帳（process.human_items）に残る", "review/gate", "answer1",
        lambda s: len(hi := rec(s)["process"]["human_items"]) == 1 and hi[0]["node"] == "p2.human_gate" and hi[0]["answer"] == "continue"
        and "KEEP-NOTE" in hi[0]["note"], id="answer-in-human-items", kept=KEPT),
    row(S, "関所: 人の答えの note が同じ周の修正役のプロンプトに届く", "review/gate", "asked2", lambda s: "KEEP-NOTE" in s.got.get("fix", ""),
        id="note-reaches-fix", kept=KEPT),
    row(S, "修正の入口: 単位の行は記録の単位と同じ順で全部載り", "review/gate", "asked2", _unit_rows_match, id="fix-unit-rows", kept=KEPT),
    row(S, "修正の入口: 判定の長い本文（母数の問いなど）は貼らず", "review/gate", "asked2", _long_bodies_not_pasted,
        id="fix-long-bodies-not-pasted", kept=KEPT),
    row(S, "関所: 修正差分の審査は後退の語を使えない", "review/gate", "asked2",
        lambda s: (r := s.got.get("delta", NONE)).returncode == 1 and "事前審査だけ" in r.stderr, id="delta-review-no-regression", kept=KEPT),
    row(S, "関所: 方針の文書が init の後に変わった", "review/gate", "asked2",
        lambda s: s.reply["status"] == "awaiting_human" and kinds(s.reply) == ["policy_changed"], id="policy-changed-asks", kept=KEPT),
    row(S, "関所: 方針の文書の変化の行は差分のファイルの置き場を載せ", "review/gate", "asked2", _policy_row_points_to_diff,
        id="policy-row-points-to-diff", kept=KEPT),
    row(S, "関所: 通した方針の文書の変更は新しい版", "review/gate", "answer2", _policy_refixed, id="policy-refixed", kept=KEPT),
    row(S, "関所: R4 の lost と方針とのぶつかり", "review/gate", "rest", _asked_once, id="lost-and-conflict-asked-once", kept=KEPT),
    row(S, "関所: 人が通した後は収束まで進む", "review/gate", "rest", lambda s: s.reply[-1]["status"] == "converged", id="converges", kept=KEPT),
    row(S, "関所: 事前審査が後退の穴を挙げたら、修正の前に人に聞く", "review/gate-stop", "asked",
        lambda s: s.reply["status"] == "awaiting_human" and kinds(s.reply) == ["regression"]
        and "事前審査の穴 [regression]" in "".join(s.reply["ask"]["items"]), id="plan-review-regression-asks"),
    row(S, "関所: stop で run がその場で止まり、修正を出さない", "review/gate-stop", "next",
        lambda s: s.reply["status"] == "stopped" and s.reply.get("halted", {}).get("node") == "p2.human_gate" and not s.reply["ready"],
        id="stop-halts-at-gate"),
    row(S, "関所: --detail で直す義務の単位を外せる", "review/gate-exclude", "good", _excluded, id="detail-excludes-unit"),
    row(S, "関所: 外した単位は修正の側に見せる義務の印", "review/gate-exclude", "good",
        lambda s: [r.get("owed") for r in _fix_rows(s) if r.get("key") == rec(s)["units"][0]["key"]] == [False], id="excluded-unit-not-owed"),
    row(S, "関所: 外した単位と理由が同じ周の修正役のプロンプトに届く", "review/gate-exclude", "to_fix",
        lambda s: "EXCLUDE-WHY" in s.got.get("fix", ""), id="exclusion-reaches-fix"),
    row(S, "関所: 無人では狭めの問いで止まり、修正を出さない", "review/gate-unattended", "end",
        lambda s: s.reply["status"] == "stopped" and (st(s).get("halted") or {}).get("by") == "unattended"
        and not any(i["node"] == "p3.fix" for i in st(s)["rounds"][0]["instances"].values()), id="unattended-stops"),
]


@pytest.mark.parametrize("name, at, expect", HUMAN_GATE)
def test_human_gate(scene, name, at, expect):
    play(scene, name, at, expect)


# ---- 判定から入る入口・修正案の審査・線・TDD・仕様（移す順の (3)(4)） -------------------------------------------------------

S = None
roles("deferjudge")
history("review/defer", init("defer", unattended=True), until("deferjudge", mark="end"))
DEFERJUDGE = [
    row(S, "理由付きの defer は受理され defer_ledger に残る", "review/defer", "end",
        lambda s: s.reply["status"] == "converged" and any("定数の重複" in k for k in rec(s)["process"].get("defer_ledger", {})),
        id="defer-with-reason-kept"),
]


@pytest.mark.parametrize("name, at, expect", DEFERJUDGE)
def test_deferjudge(scene, name, at, expect):
    play(scene, name, at, expect)


S = None
# 赤の確認の節の前に毎回、読み込みで落ちるテストを書く——狙いどおりの赤にならない
roles("tdd-giveup", rule("p3.tdd_tests", before=[write("repo", "tests/test_limit.py",
                                                       "import no_such_module_for_red  # noqa\n\n\ndef test_limit_is_fixed():\n    assert False\n")]),
      base="std")
history("review/tdd-giveup", init("tdd-giveup", loop="review-loop-tdd", inputs=(f"tdd_suite={review.TINYJUNIT}",)),
        write("repo", "tests/test_old_red.py", "def test_was_red_before():\n    assert False\n"), until("tdd-giveup", mark="end"))


def _tdd_row(s):
    return ((rec(s)["process"].get("tdd") or {}).get("rounds") or {}).get("1") or {}


def _tdd_tests_calls(s):
    """赤の確認の前にテストを書く節（p3.tdd_tests）を答えた回数（trace の done の行）"""
    return sum(1 for x in s.board.lines("trace.jsonl") if (j := json.loads(x)).get("op") == "done" and j.get("instance") == "p3.tdd_tests")


TDD_GIVES_UP = [
    row(S, "赤の確認が 3 回通らなければ TDD を諦めて今の流れで直し、緑の確認は撃たない", "review/tdd-giveup", "end",
        lambda s: s.reply["status"] == "converged" and _tdd_tests_calls(s) == 3 and _tdd_row(s).get("red") == "failed" and "green" not in _tdd_row(s),
        id="gives-up-after-three"),
    row(S, "周の頭で元から落ちていたテストは記録に残し、赤の確認の『ほか』には数えない", "review/tdd-giveup", "end",
        lambda s: _tdd_row(s).get("baseline_red") == ["tests.test_old_red::test_was_red_before"]
        and not any("test_was_red_before" in p for p in _tdd_row(s).get("red_problems") or []), id="baseline-red-not-counted"),
    row(S, "諦めた理由は次の周の判定役に穴の行として届く", "review/tdd-giveup", "end",
        lambda s: any("TDD の赤の確認が上限で通らなかった" in r["key"]
                      for r in json.loads(s.board.read(s.board.dir / "out" / "r2" / "p2.history.json")).get("declared_routed") or []),
        id="reason-reaches-next-judge"),
    row(S, "TDD を諦めた盤面は、諦めた確認の節の出力から hist.tdd_gave_up が作られる（loop には書かない）", "review/tdd-giveup", "end",
        lambda s: bool(json.loads(s.board.read(s.board.dir / "hist.json"))["values"].get("tdd_gave_up"))
        and "tdd_gave_up" not in (st(s).get("loop") or {}), id="hist-not-loop"),
]


@pytest.mark.parametrize("name, at, expect", TDD_GIVES_UP)
def test_tdd_gives_up_without_dead_end(scene, name, at, expect):
    play(scene, name, at, expect)


def test_tdd_gives_up_keeps_the_loop_shape(scene):
    """台本の loop_shape_held（関数の外の check なので台帳には載らない）: TDD を諦めた盤面の loop が state_schema の形に収まる"""
    from engine.schema import load_graph
    s = st(scene("review/tdd-giveup", "end"))
    g, _ = load_graph(s["graph"])
    keys = set(s.get("loop") or {})
    assert isinstance((g or {}).get("state_schema"), dict) and not s.get("loop_drift"), (sorted(keys), s.get("loop_drift"))
