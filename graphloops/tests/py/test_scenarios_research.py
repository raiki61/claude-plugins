"""層 2 の筋書き（research）: 上限で止まる類と、止める・人待ちの台本（graphloops/tests/simulate.py）の check の移し先。

列と行の形は test_scenarios_review.py と同じ（scenes.py・docs/adr/0067）。1 行が台本の check 1 件で、行の印 ``moved_from`` が名乗る。
"""
import pytest
from engine.schema import load_graph
from engine.validator import TRACES
from scenes import cmd, file, history, init, look, nxt, play, roles, row, until, validate

pytestmark = [pytest.mark.medium, pytest.mark.layer2]

for base in ("std", "stuck", "coldfail", "rederiver_fail", "heavy"):
    roles(base)


def rec(s):
    return s.board.record()


# ---- 無人・有人の stuck -------------------------------------------------------------------------------------------------

S = "simulate.test_unattended_stuck"
history("research/stuck", init("stuck", unattended=True), until("stuck", mark="end"))
UNATTENDED_STUCK = [
    row(S, "status が stopped", "research/stuck", "end", lambda s: s.reply["status"] == "stopped", id="status-stopped"),
    row(S, "stopped_reason: ", "research/stuck", "end",
        lambda s: rec(s)["convergence"]["outcome"] == "stopped" and "無人実行" in rec(s)["convergence"]["stopped_reason"],
        id="stopped-reason-unattended"),
    row(S, "要人間判断に stuck が載る", "research/stuck", "end", lambda s: any("stuck" in str(x) for x in rec(s)["process"]["human_items"]),
        id="human-items-stuck"),
    row(S, "停止でも報告は出る", "research/stuck", "end", lambda s: s.board.has("report.md"), id="report-on-stop"),
]


@pytest.mark.parametrize("name, at, expect", UNATTENDED_STUCK)
def test_unattended_stuck(scene, name, at, expect):
    play(scene, name, at, expect)


S = "simulate.test_attended_stuck_answer"
history("research/ask", init("ask"), until("stuck", mark="asked"), cmd("answer", "--text", "escalate", mark="answer"),
        cmd("status", mark="status"), nxt(mark="next"))
ATTENDED_STUCK = [
    row(S, "人に聞く番になる", "research/ask", "asked",
        lambda s: s.reply["status"] == "awaiting_human" and "stuck" in s.reply["ask"]["kinds"], id="asks-human"),
    row(S, "answer escalate が通る", "research/ask", "answer", lambda s: s.reply.returncode == 0, id="escalate-accepted"),
    row(S, "重厚で 3 周目に入る: ", "research/ask", "status", lambda s: (g := s.reply.json())["thickness"] == "重厚" and g["round"] == 3,
        id="heavy-round-3"),
    row(S, "stuck 後の重厚では断面の生成が開く", "research/ask", "next", lambda s: any(i["node"] == "p0.generation" for i in s.reply["ready"]),
        id="generation-opens"),
    row(S, "重厚に上がると cartographer が序盤に出る", "research/ask", "next",
        lambda s: any(i["node"] == "p3.cartographer" for i in s.reply["ready"]), id="cartographer-early"),
]


@pytest.mark.parametrize("name, at, expect", ATTENDED_STUCK)
def test_attended_stuck_answer(scene, name, at, expect):
    play(scene, name, at, expect)


def test_attended_stuck_answer_keeps_the_loop_shape(scene):
    """台本の loop_shape_held（関数の外の check なので台帳には載らない）: 続行した盤面の loop が state_schema の形に収まる"""
    st = scene("research/ask", "next").board.state()
    g, _ = load_graph(st["graph"])
    keys = set(st.get("loop") or {})
    assert isinstance((g or {}).get("state_schema"), dict) and {"stuck_hint", "stuck_ids"} <= keys and not st.get("loop_drift"), \
        (sorted(keys), st.get("loop_drift"))


# ---- ゲートが pass しない周が続く ----------------------------------------------------------------------------------------

S = "simulate.test_gate_arms"
history("research/coldfail", init("coldfail", unattended=True), until("coldfail", mark="end"))
history("research/rederiver", init("rederiver"), until("rederiver_fail", mark="end"))
GATE_ARMS = [
    row(S, "cold_reader が pass しないまま上限で stopped", "research/coldfail", "end",
        lambda s: s.reply["status"] == "stopped" and "max_rounds" in rec(s)["convergence"]["stopped_reason"], id="coldfail-stops-at-max"),
    row(S, "何を聞かれて止まったかが記録に残る", "research/coldfail", "end",
        lambda s: bool(hi := rec(s)["process"]["human_items"]) and "max_rounds" in (hi[-1].get("kinds") or []), id="asked-kinds-kept"),
    row(S, "収束を名乗らず、ゲートの周ごとの verdict が残る", "research/coldfail", "end",
        lambda s: rec(s)["convergence"]["outcome"] == "stopped"
        and all(r["verdict"] == "redesign-needed" for r in rec(s)["gates"]["cold_reader"]["rounds"]), id="gate-verdicts-kept"),
    row(S, "止まった周は max_rounds", "research/coldfail", "end",
        lambda s: (st := s.board.state())["round"] == st["max_rounds"], id="stopped-at-max-rounds"),
    row(S, "rederiver の redesign-needed が 2 周解消しないと人に聞く", "research/rederiver", "end",
        lambda s: s.reply["status"] == "awaiting_human" and "zero_base_divergence" in s.reply["ask"]["kinds"], id="rederiver-asks"),
]


@pytest.mark.parametrize("name, at, expect", GATE_ARMS)
def test_gate_arms(scene, name, at, expect):
    play(scene, name, at, expect)


# ---- ゲートが走る前に止まった標準・重厚 -------------------------------------------------------------------------------
# 台本は段ごとのループ（型紙の check）。段の腕は std（標準・人が stop と答える）と heavy（重厚・無人）の 2 本。上限を 1 周にし、
# report の前で検証器に落とされても例外で抜けずに赤の 1 件として数える（catch）

S = "simulate.test_stopped_before_gates_reports"
ONE_ROUND = ("--path", "state.max_rounds", "--file", file("one.json", 1), "--reason", "1 周目で止める筋を作る")
history("research/early-std", init("stop-early-標準", thickness="標準", unattended=False), cmd("patch", *ONE_ROUND, mark="patch"),
        until("std", catch=True, mark="asked"), cmd("answer", "--text", "stop", mark="answer"), until("std", catch=True, mark="end"),
        validate(mark="validate"))
history("research/early-heavy", init("stop-early-重厚", thickness="重厚", unattended=True), cmd("patch", *ONE_ROUND, mark="patch"),
        until("heavy", catch=True, mark="end"), validate(mark="validate"))
TH = {"std": "research/early-std", "heavy": "research/early-heavy"}


def _gates(s):
    return rec(s)["gates"]


STOPPED_BEFORE_GATES = [
    *(row(S, "{th}: 上限を 1 周にできる", h, "patch", lambda s: s.reply.returncode == 0, id=f"{t}-max-rounds-1") for t, h in TH.items()),
    row(S, "{th}: 上限で人に聞く", TH["std"], "asked",
        lambda s: s.reply.get("status") == "awaiting_human" and "max_rounds" in s.reply["ask"]["kinds"], id="std-asks-at-max"),
    row(S, "{th}: stop と答えられる", TH["std"], "answer", lambda s: s.reply.returncode == 0, id="std-answer-stop"),
    *(row(S, "{th}: 止まった run として終わる", h, "end",
          lambda s: s.reply.get("status") == "stopped" and rec(s)["convergence"]["outcome"] == "stopped", id=f"{t}-ends-stopped")
      for t, h in TH.items()),
    *(row(S, "{th}: ゲートが走る前に止まっても report.md が出る", h, "end", lambda s: s.board.has("report.md"), id=f"{t}-report")
      for t, h in TH.items()),
    *(row(S, "{th}: 検証器が止まった記録として通す", h, "validate",
          lambda s: s.reply.returncode == 0 and "停止（未収束）の申告つき" in s.reply.stdout, id=f"{t}-validator-accepts-stopped")
      for t, h in TH.items()),
    *(row(S, "{th}: {k} は『飛ばした』と理由つきで残る", TH[t], "validate",
          lambda s, k=k: _gates(s)[k].get("status") == "not_run" and bool(_gates(s)[k].get("reason")), id=f"{t}-{k}-not-run")
      for t, k in (("std", "cold_reader"), ("heavy", "cold_reader"), ("heavy", "cartographer"))),
    row(S, "標準: cartographer はこの段では走らせない", TH["std"], "validate",
        lambda s: _gates(s)["cartographer"].get("status") == "not_applicable" and bool(_gates(s)["cartographer"].get("reason")),
        id="std-cartographer-not-applicable"),
    *(row(S, "{th}: 突合の前に止まった rederiver は not_run", h, "validate",
          lambda s: (rd := _gates(s)["rederiver"]).get("status") == "not_run" and (rd.get("provisional") or {}).get("verdict") == "pass"
          and "突合" in rd.get("reason", ""), id=f"{t}-rederiver-provisional") for t, h in TH.items()),
]


@pytest.mark.parametrize("name, at, expect", STOPPED_BEFORE_GATES)
def test_stopped_before_gates_reports(scene, name, at, expect):
    play(scene, name, at, expect)


# ---- 人が途中で止める ---------------------------------------------------------------------------------------------------

S = "simulate.test_stop_midway"
AT_CHECKER = {"ready": "p1.checker"}
history("research/stop-mid", init("stop-mid"), until("std", stop=AT_CHECKER), cmd("stop", "--reason", "検査: 照合の前で止める", mark="stop"),
        nxt(mark="next"), until("std", mark="end"), validate(mark="validate"))
history("research/stop-first", init("stop-first"), cmd("stop", "--reason", "検査: すぐ止める", mark="stop"), until("std", mark="end"))
# 途中で打った finalize は記録を書き換えない。後で本当に止めたら（盤面を止めた形に手当てして）、その事実で畳む
history("research/finalize-early", init("finalize-early"), until("std", stop=AT_CHECKER), look(mark="before"), cmd("finalize", mark="finalize"),
        cmd("patch", "--path", "state.halted", "--file",
            file("halted.json", {"node": "converge", "round": 1, "by": "stop_after_round", "reason": "検査: 周の締めの後で止めた"}),
            "--reason", "後で止めた盤面を作る"),
        cmd("finalize", mark="finalize2"))


def _unchanged_by_early_finalize(s):
    """盤面から写し直す痕跡の欄は足されてよい"""
    before, after = s.got["before"]["record"], rec(s)
    mirrored = {f for f, _ in TRACES} | {"skipped", "stopped_nodes", "launch_missing", "read_through_unchecked"}
    for k in (set(after["process"]) - set(before["process"])) & mirrored:
        after["process"].pop(k)
    return s.reply.returncode == 1 and after == before and "未決" in s.reply.stdout


STOP_MIDWAY = [
    row(S, "止める: 止めた時点で convergence に理由が入る", "research/stop-mid", "stop",
        lambda s: s.reply.returncode == 0 and rec(s)["convergence"]["outcome"] == "stopped"
        and "検査: 照合の前で止める" in rec(s)["convergence"]["stopped_reason"], id="reason-in-convergence"),
    row(S, "止める: 次の next は後始末の節だけを出す", "research/stop-mid", "next", lambda s: [i["node"] for i in s.reply["ready"]] == ["p5.adapt"],
        id="next-is-adapt-only"),
    row(S, "止める: 報告まで届き、記録は検証器を通る", "research/stop-mid", "validate",
        lambda s: s.got["end"]["status"] == "stopped" and s.board.has("report.md") and s.reply.returncode == 0
        and rec(s)["process"]["halted"]["by"] == "stop" and any(x["node"] == "p1.checker" for x in rec(s)["process"]["stopped_nodes"]),
        id="report-and-validator"),
    row(S, "止める: 照合の前に止めたので主張とクラスタは空で", "research/stop-mid", "validate",
        lambda s: set(rec(s)["process"].get("stopped_gaps") or {}) == {"claims", "clusters"}, id="stopped-gaps"),
    row(S, "止める: 最初の節の前に止めても報告まで届き", "research/stop-first", "end",
        lambda s: s.got["stop"].returncode == 0 and s.board.has("report.md")
        and {"question", "constraints", "clusters", "claims"} <= set(rec(s)["process"].get("stopped_gaps") or {}), id="stop-before-first-node"),
    row(S, "途中の finalize: 記録を書き換えず、未決として exit 1", "research/finalize-early", "finalize", _unchanged_by_early_finalize,
        id="early-finalize-undecided"),
    row(S, "途中の finalize の後に止めた run は、止めた事実で畳む", "research/finalize-early", "finalize2",
        lambda s: (r := rec(s))["convergence"]["outcome"] == "stopped" and "stop_after_round" in r["convergence"]["stopped_reason"]
        and r["process"].get("unchecked_claims"), id="stopped-after-early-finalize"),
]


@pytest.mark.parametrize("name, at, expect", STOP_MIDWAY)
def test_stop_midway(scene, name, at, expect):
    play(scene, name, at, expect)
