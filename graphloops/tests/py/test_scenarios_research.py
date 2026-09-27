"""層 2 の筋書き（research）: 上限で止まる類と、止める・人待ちの台本（graphloops/tests/simulate.py）の check を、given（控えた波）・
when（1 手の関数）・then（手で書いた述語）の行へ移した物。1 行が台本の check 1 件で、行の印 ``moved_from`` が名乗る（台帳は ledger.py）。

前置きは waves.py の WAVES・ROOTS（台本の Run と drive を借りる。research の drive には何もしない hook を渡し、台本の check を
撃たない）。盤面を回すので medium で、印 layer2 も付く。台本はまだ消していない（MIGRATION.md の T2）。
"""
import subprocess
import sys

import pytest
import waves
from engine.schema import load_graph
from engine.validator import TRACES
from waves import play, row

research = waves.research
pytestmark = [pytest.mark.medium, pytest.mark.layer2]


def rec(w):
    return w.run.record()


def last(w):
    return w.values["last"]


def validate(run):
    """検証器を子プロセスで起こす（台本と同じ口）"""
    return subprocess.run([sys.executable, str(research.VALIDATOR), str(run.dir / "record.json")], capture_output=True, text=True, encoding="utf-8")


# ---- 無人・有人の stuck -------------------------------------------------------------------------------------------------

S = "simulate.test_unattended_stuck"
UNATTENDED_STUCK = [
    row(S, "status が stopped", "research/stuck/end", lambda w, g: last(w)["status"] == "stopped", id="status-stopped"),
    row(S, "stopped_reason: ", "research/stuck/end",
        lambda w, g: rec(w)["convergence"]["outcome"] == "stopped" and "無人実行" in rec(w)["convergence"]["stopped_reason"],
        id="stopped-reason-unattended"),
    row(S, "要人間判断に stuck が載る", "research/stuck/end",
        lambda w, g: any("stuck" in str(x) for x in rec(w)["process"]["human_items"]), id="human-items-stuck"),
    row(S, "停止でも報告は出る", "research/stuck/end", lambda w, g: (w.run.dir / "report.md").is_file(), id="report-on-stop"),
]


@pytest.mark.parametrize("given, when, then", UNATTENDED_STUCK)
def test_unattended_stuck(wave, given, when, then):
    play(wave, given, when, then)


S = "simulate.test_attended_stuck_answer"
ATTENDED_STUCK = [
    row(S, "人に聞く番になる", "research/ask/asked",
        lambda w, g: last(w)["status"] == "awaiting_human" and "stuck" in last(w)["ask"]["kinds"], id="asks-human"),
    row(S, "answer escalate が通る", "research/ask/asked", lambda w, g: g.returncode == 0,
        when=lambda w: w.run.cmd("answer", "--text", "escalate"), id="escalate-accepted"),
    row(S, "重厚で 3 周目に入る: ", "research/ask/answered", lambda w, g: g["thickness"] == "重厚" and g["round"] == 3,
        when=lambda w: w.run.status(), id="heavy-round-3"),
    row(S, "stuck 後の重厚では断面の生成が開く", "research/ask/answered", lambda w, g: any(i["node"] == "p0.generation" for i in g["ready"]),
        when=lambda w: w.run.next(), id="generation-opens"),
    row(S, "重厚に上がると cartographer が序盤に出る", "research/ask/answered",
        lambda w, g: any(i["node"] == "p3.cartographer" for i in g["ready"]), when=lambda w: w.run.next(), id="cartographer-early"),
]


@pytest.mark.parametrize("given, when, then", ATTENDED_STUCK)
def test_attended_stuck_answer(wave, given, when, then):
    play(wave, given, when, then)


def test_walking_a_wave_runs_no_script_check(gl_tmp):
    """波の手は台本の check を撃たない（research の drive は hook が None なら中で check を撃つ——撃てば件数の柵が -n の振り分けで揺れ、
    準備の段で落ちた check は数えられない）。まっさらな控えの置き場で、照合と統合の節を通って止まる research の波を 1 本作り、
    台本の件数が動かないことを見る"""
    before = research.ran
    (gl_tmp / "fresh").mkdir()
    waves.Waves(gl_tmp / "fresh").build("research/stuck/end")
    assert research.ran == before


def test_attended_stuck_answer_keeps_the_loop_shape(wave):
    """台本の loop_shape_held（関数の外の check なので台帳には載らない）: 続行した盤面の loop が state_schema の形に収まる"""
    w = wave("research/ask/answered")
    w.run.next()
    st = w.run.state()
    g, _ = load_graph(st["graph"])
    keys = set(st.get("loop") or {})
    assert isinstance((g or {}).get("state_schema"), dict) and {"stuck_hint", "stuck_ids"} <= keys and not st.get("loop_drift"), \
        (sorted(keys), st.get("loop_drift"))


# ---- ゲートが pass しない周が続く ----------------------------------------------------------------------------------------

S = "simulate.test_gate_arms"
GATE_ARMS = [
    row(S, "cold_reader が pass しないまま上限で stopped", "research/coldfail/end",
        lambda w, g: last(w)["status"] == "stopped" and "max_rounds" in rec(w)["convergence"]["stopped_reason"], id="coldfail-stops-at-max"),
    row(S, "何を聞かれて止まったかが記録に残る", "research/coldfail/end",
        lambda w, g: bool(hi := rec(w)["process"]["human_items"]) and "max_rounds" in (hi[-1].get("kinds") or []), id="asked-kinds-kept"),
    row(S, "収束を名乗らず、ゲートの周ごとの verdict が残る", "research/coldfail/end",
        lambda w, g: rec(w)["convergence"]["outcome"] == "stopped"
        and all(r["verdict"] == "redesign-needed" for r in rec(w)["gates"]["cold_reader"]["rounds"]), id="gate-verdicts-kept"),
    row(S, "止まった周は max_rounds", "research/coldfail/end",
        lambda w, g: w.run.state()["round"] == w.run.state()["max_rounds"], id="stopped-at-max-rounds"),
    row(S, "rederiver の redesign-needed が 2 周解消しないと人に聞く", "research/rederiver/end",
        lambda w, g: last(w)["status"] == "awaiting_human" and "zero_base_divergence" in last(w)["ask"]["kinds"], id="rederiver-asks"),
]


@pytest.mark.parametrize("given, when, then", GATE_ARMS)
def test_gate_arms(wave, given, when, then):
    play(wave, given, when, then)


# ---- ゲートが走る前に止まった標準・重厚 -------------------------------------------------------------------------------
# 台本は段ごとのループ（型紙の check）。段の腕は std（標準・人が stop と答える）と heavy（重厚・無人）の 2 本

S = "simulate.test_stopped_before_gates_reports"
TH = {"std": "research/early-std", "heavy": "research/early-heavy"}


def _gates(w):
    return rec(w)["gates"]


STOPPED_BEFORE_GATES = [
    *(row(S, "{th}: 上限を 1 周にできる", f"{c}/patched", lambda w, g: w.values["patch"]["rc"] == 0, id=f"{t}-max-rounds-1")
      for t, c in TH.items()),
    row(S, "{th}: 上限で人に聞く", "research/early-std/asked",
        lambda w, g: last(w)["status"] == "awaiting_human" and "max_rounds" in last(w)["ask"]["kinds"], id="std-asks-at-max"),
    row(S, "{th}: stop と答えられる", "research/early-std/end", lambda w, g: w.values["answer"]["rc"] == 0, id="std-answer-stop"),
    *(row(S, "{th}: 止まった run として終わる", f"{c}/end",
          lambda w, g: last(w)["status"] == "stopped" and rec(w)["convergence"]["outcome"] == "stopped", id=f"{t}-ends-stopped")
      for t, c in TH.items()),
    *(row(S, "{th}: ゲートが走る前に止まっても report.md が出る", f"{c}/end", lambda w, g: (w.run.dir / "report.md").is_file(),
          id=f"{t}-report") for t, c in TH.items()),
    *(row(S, "{th}: 検証器が止まった記録として通す", f"{c}/end", lambda w, g: g.returncode == 0 and "停止（未収束）の申告つき" in g.stdout,
          when=lambda w: validate(w.run), id=f"{t}-validator-accepts-stopped") for t, c in TH.items()),
    *(row(S, "{th}: {k} は『飛ばした』と理由つきで残る", f"{TH[t]}/end",
          lambda w, g, k=k: _gates(w)[k].get("status") == "not_run" and bool(_gates(w)[k].get("reason")), id=f"{t}-{k}-not-run")
      for t, k in (("std", "cold_reader"), ("heavy", "cold_reader"), ("heavy", "cartographer"))),
    row(S, "標準: cartographer はこの段では走らせない", "research/early-std/end",
        lambda w, g: _gates(w)["cartographer"].get("status") == "not_applicable" and bool(_gates(w)["cartographer"].get("reason")),
        id="std-cartographer-not-applicable"),
    *(row(S, "{th}: 突合の前に止まった rederiver は not_run", f"{c}/end",
          lambda w, g: (rd := _gates(w)["rederiver"]).get("status") == "not_run" and (rd.get("provisional") or {}).get("verdict") == "pass"
          and "突合" in rd.get("reason", ""), id=f"{t}-rederiver-provisional") for t, c in TH.items()),
]


@pytest.mark.parametrize("given, when, then", STOPPED_BEFORE_GATES)
def test_stopped_before_gates_reports(wave, given, when, then):
    play(wave, given, when, then)


# ---- 人が途中で止める ---------------------------------------------------------------------------------------------------

S = "simulate.test_stop_midway"


def _finalize_early(w):
    """途中で finalize を打ち、前後の記録を比べる（盤面から写し直す痕跡の欄は足されてよい）"""
    before = w.run.record()
    r = w.run.cmd("finalize")
    after = w.run.record()
    mirrored = {f for f, _ in TRACES} | {"skipped", "stopped_nodes", "launch_missing", "read_through_unchecked"}
    for k in (set(after["process"]) - set(before["process"])) & mirrored:
        after["process"].pop(k)
    return r, before, after


def _stop_after_finalize(w):
    h = w.run.tmp / "halted.json"
    h.write_text('{"node": "converge", "round": 1, "by": "stop_after_round", "reason": "検査: 周の締めの後で止めた"}', encoding="utf-8")
    w.run.cmd("patch", "--path", "state.halted", "--file", str(h), "--reason", "後で止めた盤面を作る")
    w.run.cmd("finalize")
    return w.run.record()


STOP_MIDWAY = [
    row(S, "止める: 止めた時点で convergence に理由が入る", "research/stopmid/stopped",
        lambda w, g: w.values["stop"]["rc"] == 0 and rec(w)["convergence"]["outcome"] == "stopped"
        and "検査: 照合の前で止める" in rec(w)["convergence"]["stopped_reason"], id="reason-in-convergence"),
    row(S, "止める: 次の next は後始末の節だけを出す", "research/stopmid/stopped",
        lambda w, g: [i["node"] for i in g["ready"]] == ["p5.adapt"], when=lambda w: w.run.next(), id="next-is-adapt-only"),
    row(S, "止める: 報告まで届き、記録は検証器を通る", "research/stopmid/end",
        lambda w, g: last(w)["status"] == "stopped" and (w.run.dir / "report.md").is_file() and g.returncode == 0
        and rec(w)["process"]["halted"]["by"] == "stop" and any(x["node"] == "p1.checker" for x in rec(w)["process"]["stopped_nodes"]),
        when=lambda w: validate(w.run), id="report-and-validator"),
    row(S, "止める: 照合の前に止めたので主張とクラスタは空で", "research/stopmid/end",
        lambda w, g: set(rec(w)["process"].get("stopped_gaps") or {}) == {"claims", "clusters"}, id="stopped-gaps"),
    row(S, "止める: 最初の節の前に止めても報告まで届き", "research/stopfirst/end",
        lambda w, g: w.values["stop"]["rc"] == 0 and (w.run.dir / "report.md").is_file()
        and {"question", "constraints", "clusters", "claims"} <= set(rec(w)["process"].get("stopped_gaps") or {}), id="stop-before-first-node"),
    row(S, "途中の finalize: 記録を書き換えず、未決として exit 1", "research/finearly/at-checker",
        lambda w, g: g[0].returncode == 1 and g[2] == g[1] and "未決" in g[0].stdout, when=_finalize_early, id="early-finalize-undecided"),
    row(S, "途中の finalize の後に止めた run は、止めた事実で畳む", "research/finearly/finalized",
        lambda w, g: g["convergence"]["outcome"] == "stopped" and "stop_after_round" in g["convergence"]["stopped_reason"]
        and g["process"].get("unchecked_claims"), when=_stop_after_finalize, id="stopped-after-early-finalize"),
]


@pytest.mark.parametrize("given, when, then", STOP_MIDWAY)
def test_stop_midway(wave, given, when, then):
    play(wave, given, when, then)
