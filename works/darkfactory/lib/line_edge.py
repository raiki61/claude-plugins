"""境の節の中身（線 A の仕様 2 節・計画 Task 10a・裁定 TA1・TA4。並びは C18 の順: 計画 P1 Task 26・P1-R3・P1-R4）。
ライン darkfactory の模块（層 L6。裁定 R59）で、使うのは darkfactory/scripts/edge.py と structure.py・world.py・after.py だけ。止め札そのもの（置く・読む）は共有の
.shared/core/halt.py。

- edge(board_dir, at, repo, …): 境の節（darkfactory/scripts/edge.py の中身）。止め札・関所の答え・次のブロックを盤面から決める
- gate_text(asking, *, run_id): 盤面の問いを修正の前の関所 policy-gate の文にする（h-gate。組み立ては gatemarks.gate_text）
- judge_edge(b, …): h-judge の固有の仕事（包みの確かめ・前提の実測が盤面に在るか。計画 P1 Task 24・P1-R9）
- mat_edge(b, …): h-mat の固有の仕事（目的の文を盤面へ渡し、P1 の目を回すか。計画 P1 Task 32・33）
- rejudge_edge(board_dir, repo): h-rejudge の固有の仕事（修正役の異議の再審を回すか。判定役の会話が無ければ止める。計画 P1 Task 31）
- 同じ run の中の案の直し（依頼 226。core の replan）: h-replan（at replan）は修正の段で fix_plan_item と裁かれた項目を束ね
  （replan.material）、案の直しのブロック（blk-plan の 2 度目の include）を回すか。h-regate（at regate）は直した項目に関所の
  決まりを当て（replan.gate）、関所 replan-gate を開くか。h-refit（at refit）は関所の答えを当て（refit_edge・replan.answer）、
  2 回目の修正の段（blk-fix の 2 度目の include refitting。その物は scope で 1 回目と分かれる）を回すか。どれも今の周の replan.json が無ければ何もしない
- eyes_edge(b): h-look の固有の仕事（独立の目を回すか。計画 P1 Task 33）。h-eyes も同じ go を返す（関所の後にまだ目が待つか——報告が
  blk-eyes の落ちを見分ける）。h-look は先に、blk-plan が修正の前に控えた独立設計（core の design。design.json）を、盤面が r2.design を
  待っていれば渡す（目的の文を h-mat が渡すのと同じ形）
- plan_edge(b, …): h-plan の固有の仕事（判定の出口の控え・判定の渡し替え・直す物が無い周の締め。計画 P1 Task 23）。go は修正案か
  独立設計（design.due）のどちらかを blk-plan で起こす周
- structure_edge(board_dir, structured): h-structure（構造の境の節。darkfactory/scripts/structure.py の中身）。構造のブロックの出口を
  確かめ、盤面の根の控え（core の structmark）を書く。planning はこの節を待つ
- world_edge(board_dir, worlded, due): h-world（世界の解の境の節。darkfactory/scripts/world.py の中身。計画 world-solution の W7）。
  世界の解のブロックの出口を確かめ、盤面の根の控え（core の worldmark）を書く。判定はこの節を待ち、判定の支度・修正案の頭・関所は
  控えから行を読む。段が落ちても線を止めない
- after_edge(board_dir, measured): 直しの後の構造の境（darkfactory/scripts/after.py の中身。計画 2026-10-09-clean-whole の
  Task 2.5）。直しの後に 2 度目に差し込んだ構造のブロックの出口（after.json）に、修正案の外れの訳（planmarks.deviations）を
  足して盤面の根の控え（structmark.write_after）を書く。報告・最後の関所・独立の目の頭・結末の残りがその控えを読む
- trace_empty_fix(b): 機械が p3.fix の空の返答を渡した印（trace の記録。entry.trace_empty_fix の別名）
- 固定材料（core の fixture。計画 220 Task 5）: h-fix は go の後、1 周目なら盤面を $ARTIFACTS_DIR/fix-fixture へ写す
  （固定材料から始めた盤面は capture が写さない。写せなくても run は止めない）。包みの確かめは「この run で役が 1 つ起きた
  後の最初の境の節で止める」（_adapter_guard）: 通常の盤面は h-judge、固定材料から始めた盤面（fixture.adopted）は h-review
  （修正のブロックと再審の後）。
  h-mat は今の周の判定が済んでいれば go を偽にする（判定のブロックを回さない）
- 守りのファイル（core の protect・protected.json。ASF の floor.json に倣う）: h-final は run の修正の差分（修正前の版
  state.inputs.review_rev から。固まる前は record.base。未追跡を含む。_protected）が一覧に当たれば最後の関所を開き方（core の gatepolicy）に関わらず開き、冒頭 3 行で名指して直後の最初の節に並べ、process.human_items に 1 行。h-eyes は答えを
  その行に写し、答えが来なければ（関所が開かなかった）止める。通すのは人の continue だけ。テストの変更の許し（承認済みの修正案の
  rewrite_tests と裁定 fix_test_scope の範囲。core の conflict.test_permits）が名指したテストの変更も守りのファイルの行として並ぶ
- 食い違いの申し出（core の conflict）: 裁定役か機械が ask_human に裁いた単位が在れば、h-final は最後の関所を開き方に関わらず
  開き、文に「食い違いの申し出」の節を並べ、process.human_items に 1 行。答えの写しと、答えが来ない時の止めは守りのファイルと同じ
"""
import json
import os
import pathlib
import sys
from typing import NamedTuple

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように

_LIB = pathlib.Path(__file__).resolve().parent
_CORE = _LIB.parents[1] / ".shared" / "core"
for _p in (_LIB, _CORE):   # core を頭に（節のスクリプトと同じ順。lib の名前は core と重ねない）
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from board import BoardGap  # noqa: E402
from engine.util import Reject  # noqa: E402
import accept  # noqa: E402
import answer  # noqa: E402
import conflict  # noqa: E402
import converge  # noqa: E402
import design  # noqa: E402
import entry  # noqa: E402
import fixture  # noqa: E402
import gatemarks  # noqa: E402
import gatepolicy  # noqa: E402  （L1。人の関所と無人の方針の住処。最後の関所の開き方は始めの記録から読む）
import halt  # noqa: E402
import impact  # noqa: E402
import planmarks  # noqa: E402
import protect  # noqa: E402
import purpose  # noqa: E402
import querytest  # noqa: E402
import reads  # noqa: E402
import rejudge  # noqa: E402
import replan  # noqa: E402
import report  # noqa: E402
import scopes  # noqa: E402
import startrec  # noqa: E402  （始めの記録の読み口）
import stopby  # noqa: E402  （L1。止めの理由の住処）
import structmark  # noqa: E402
import worldmark  # noqa: E402  （世界の解の行と控えの住処）

# ---------------------------------------------------------------- 境の節（線 A の仕様 2 節・計画 Task 10a・裁定 TA1・TA4）
# いつも走る script の節 1 本（darkfactory/scripts/edge.py）を、ラインの中で at を替えて使う。並びは C18 の順（中の関所は無い。
# 人が止まれる所は最後の人の関所 final-gate。P1-R3）。when: と関所の文は境の節の欄だけを読み、go は盤面の ready から決める（TA1）。
# rejudge は修正役の異議の再審を回すかを決める（計画 P1 Task 31）。look は最後のテストの後に独立の目を回すかを決め、eyes は
# spec は仕様の段（任意。入力 spec）の後・並行 PR の前の境で、仕様を固めた後に盤面の engine の節を回し直して pr_go を出す
# 独立の目と最後の関所の後に関所の答えを受ける（人は目の結果を見てから答える。本線の r4.human_gate と同じ順。名 h-eyes は前の並びのまま）
# replan・regate・refit は修正の段の後・再審の前の案の直し（依頼 226。1 run に 1 回）。ci は最後のテストの後に、p4.ci が
# 任せ先に落ちて待っていれば（test_cmd も宣言も無い run）任せ先の CI の役のブロックを回すかを決める
AT = ("entry", "spec", "judge", "mat", "plan", "gate", "fix", "replan", "regate", "refit", "rejudge", "review", "refix", "tests",
      "ci", "look", "final", "eyes")
GO_NODE = {"plan": "p2.fix_plan", "fix": "p3.fix", "review": "p3.delta_review", "refix": "p3.delta_fix", "tests": "p4.ci"}
GATE_AT = ("fix", "refit", "eyes")   # 関所の答えを受ける境の節（fix は policy-gate、refit は replan-gate、eyes は final-gate）
GATE_GO = ("approve", "continue")    # approve は continue と、reject は stop と同じ（台帳 R32）
GATE_STOP = ("stop", "reject")
GATE_STOP_NOTE = "関所で止めた"              # policy-gate の stop・reject に一言が無い時の理由
# 最後の関所の開き方は住処 gatepolicy（語・既定・開くかの決め）。境の節は入力で受けず、入口が置いた始めの記録から読む。
# 開いた関所の stop・reject は use.sh apply が読んで差分を当てずに止まり、当てるのは WORKS_USE_ALLOW_STOPPED=1 の時だけ
FINAL_GATE_FILE = "final-gate.md"            # final-gate の文（b.work）
FINAL_GATE_ANSWER = "final-gate-answer.json" # final-gate の答え {decision, text}（b.work。stop・reject も書く——報告が読む）
FINAL_GATE_BY = "human:final-gate"           # final-gate の stop・reject の by（state.stop.by か、周を締めた後なら trace の行）
FINAL_GATE_STOP_NOTE = "最後の関所で止めた"  # final-gate の stop・reject に一言が無い時の理由
ENDED_BY = "stop_after_round"                # 1 周の run が周を締めた後の盤面の halted.by（最後のテストの後の普通の終わり）
ENDED_AT = ("ci", "look", "final", "eyes")   # 周を締めた後に来る境の節（ENDED_BY の盤面を止めたと読まない）
STOP_AFTER_END_OP = "stop_after_round_end"   # 周を締めた盤面に止める答え・止め札が来た印の trace の行（b.stop は拒まれる）
PROTECTED_BY = stopby.declare("protected", "守りのファイルの行が答えを待つまま止めた")   # その行の node（human_items）も同じ語
PROTECTED_KIND = "protected_files"            # その行の kinds
PROTECTED_HEAD = "守りのファイルを触った"      # 最後の関所の冒頭 3 行の直後の節の見出し（1 行目でも名指す）
PROTECTED_UNKNOWN = "守りのファイルを確かめられなかった"   # 一覧か git が読めない時の見出し（黙って空にしない）
FLAG_BY_PREFIX = "request:"                  # 止め札で止めた盤面の state.stop.by は "request:<札の by>"（報告の stopped_by_request）
FLAG_SEEN_OP = "stop_flag_seen"              # 止め札を見て止めた境の節の trace の行（op・at・reason・by）
AFTER_HALT_OP = "stop_flag_after_halt"       # 止まった後に見た止め札の trace の行（b.stop は呼ばない。M3）
EMPTY_FIX_OP = entry.EMPTY_FIX_OP           # 機械が p3.fix の空の返答を渡した印の trace の行（正本は entry。TA6）
JUDGE_BRIDGE_BY = stopby.declare("judge-bridge", "判定のブロックの出口を盤面が受けなかった")   # state.stop.by（h-plan）
PREMISES_NODE = "p0.premises"
PURPOSE_NODE = "p0.purpose"
SPEC_EDGE_BY = stopby.declare("spec-edge", "仕様の段の後の engine の節の回し直しが入力の誤りで拒まれた")   # state.stop.by（h-spec）
MAT_BLOCK = "blk-material"                   # 表の where がこれの節が P1 の目（素材集め）。h-mat の mat_go
EYES_BLOCK = "blk-eyes"                      # 表の where がこれの節が独立の目。h-eyes の go
ADAPTER_HINT = ("Archon の設定 assistants.claude.claudeBinaryPath に包み（works/.shared/core/claude-adapter）の絶対パスを書くか、"
                "包み無しで回すなら入力 adapter に optional を渡す（works/README.md の包みの節）")
FIXTURE_FAILED_OP = "fixture_capture_failed"  # h-fix が固定材料を写せなかった trace の行（run は止めない）
ADAPTER_FIXTURE_OP = "adapter_check_after_fixture"   # 固定材料から始めた盤面で h-judge が包みの確かめを h-review に回した trace の行
DIAGNOSE_NODE = "p2.diagnose"                # 判定の節（h-mat・h-plan が今の周に済んだかを見る）
JUDGED_FILE = "judged.json"                  # h-plan が受けた判定のブロックの出口の控え（b.work。後ろの境の節が運ぶ。M4）
GATE_FILE = "gate.md"                        # policy-gate の文（b.work）
RUN_ID_HOLE = "<id>"                         # run の id を知らない呼び手の関所の文に入れる穴（gate_text）
NOTES_FILE = "human-notes.md"                # 今の周の人の一言（h-fix が書き、修正役がパスで読む。R44: with: に文を貼らない）
# 判定の単位を blk-structure の入力の契約 {id, paths, summary} に写したファイル（b.work。h-plan が書き、include の with: units が読む。
# 写すのは線の側のここ 1 か所で、ブロックは判定役の返答の形を読まない。設計書 structure-block-design 8 節）
STRUCTURE_UNITS_FILE = "structure-units.json"
STRUCTURE_UNITS_OP = "structure_units_dropped"   # 対象の根からの相対のパスが 1 本も取れず写さなかった単位・捨てたパスの trace の行
EMPTY = {"ok": True, "stop": False, "go": False, "ask": False, "gate_text": "", "judgment_file": "", "open_units": "",
         "plan_file": "", "notes": "", "notes_file": "", "why": "", "gate_file": "", "premises_file": "",
         "pr_go": False, "premises_go": False, "purpose_go": False, "spec_go": False, "mat_go": False,
         "structure_units_file": "", "ripple_file": "", "verify_file": "", "world_go": False, "world_purpose_file": ""}
# 世界の解の段の入力の目的の文のファイル {purpose_text, means}（b.work。h-mat が目的の文と目的の役が分けた依頼の解き方から組み、
# include の with: purpose_file が読む。ブロックの入力の形に写すのは線の側のここ 1 か所）
WORLD_PURPOSE_FILE = "world-purpose.json"
# 修正案のブロックが今の周に置く波及の一覧（その manifest の produces。h-fix・h-refit が修正の段へパスで渡す。線の木の段 1）
RIPPLE_FILE = "ripple.json"
RIPPLE_REPLAN_FILE = "ripple/replan.json"   # 同じブロックの 2 度目の include（案の直し）が直した項目で作り直した一覧（同じ produces ripple/**）
# 判定のブロックが今の周に置く単位の裏取りの申し送り（その manifest の produces。h-plan が修正案のブロックへパスで渡す。線の木の段 3）
VERIFY_FILE = "judge-verify.json"


def gate_text(asking: dict, *, run_id: str = RUN_ID_HOLE) -> str:
    """盤面の問い {node, kinds, question, items, options, in_round}（state.pending_human。写しの RL の human_gate が立てる周の途中の
    問い。項目には gatemarks が足す問いの台帳の問いも載る）を、人が Archon の関所 policy-gate で読む文にする（冒頭 3 行と答え方の行
    つき。組み立ては gatemarks.gate_text）。h-gate が返りの gate_text と r<N>/gate.md に使う。答え方は起動の殻の答えの行
    （answer.line）で continue "<通す範囲と条件>"（一言は run の記録に残り、修正役に届く）と stop "<理由>"。人が決める関所なので、
    答えるのは依頼者（/works を回す Claude は聞いて写す）"""
    return gatemarks.gate_text(asking, run_id=run_id or RUN_ID_HOLE, node=gatemarks.GATE_NODE,
                               record_name="process.human_items")


def _gap(msg):
    return BoardGap(msg)


def _ripple_file(b, name: str = RIPPLE_FILE) -> str:
    """今の周の波及の一覧の置き場（無ければ空）"""
    p = b.work(name)
    return str(p) if p.is_file() else ""


def refit_ripple_file(b) -> str:
    """2 回目の修正の段（refitting）へ渡す波及の一覧: 案の直しが作り直した RIPPLE_REPLAN_FILE が在ればそれ、無ければ 1 回目の
    RIPPLE_FILE（どちらも無ければ空）。1 回目の案の一覧は直した項目の範囲で照らしていない"""
    return _ripple_file(b, RIPPLE_REPLAN_FILE) or _ripple_file(b)
def _verify_file(b) -> str:
    """今の周の判定の単位の裏取りの申し送りの置き場（無ければ空。単位が 2 つ未満の周は判定のブロックが置かない）"""
    p = b.work(VERIFY_FILE)
    return str(p) if p.is_file() else ""


def _write_json(path: pathlib.Path, doc) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _write_text(path: pathlib.Path, text: str) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _gate_words(gate) -> tuple:
    """関所の出口 {decision, text?} を (decision, text) にする。text は字のまま（一言は 1 バイトも変えずに盤面へ）"""
    if not isinstance(gate, dict):
        raise _gap(f"関所の答えが JSON のオブジェクトでない: {type(gate).__name__}")
    decision = gate.get("decision")
    if decision not in GATE_GO + GATE_STOP:
        raise _gap(f"関所の答えの語 {decision!r} を知らない（{' / '.join(GATE_GO + GATE_STOP)}）")
    text = gate.get("text")
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise _gap(f"関所の一言が文字列でない: {type(text).__name__}")
    return decision, text


def _check_args(at, *, judged, gate, tests, premised=None, adapter_mode="") -> None:
    """配線の誤り（知らない at・場違いの入力・形の崩れ・語の外の adapter）を BoardGap にする"""
    if at not in AT:
        raise _gap(f"境の節の at {at!r} を知らない（{' / '.join(AT)}）")
    if (adapter_mode or "") not in entry.ADAPTER_MODES:
        raise _gap(f"adapter={adapter_mode!r} は知らない値（空か optional）")
    if premised is not None and (at != "judge" or not isinstance(premised, dict)):
        raise _gap(f"前提のブロックの出口（premised）を受けるのは at judge の JSON のオブジェクトだけ（at {at}・{type(premised).__name__}）")
    if gate is not None:
        if at not in GATE_AT:
            raise _gap(f"関所の答え（gate）を受けるのは at {' / '.join(GATE_AT)} だけ（at {at}）")
        _gate_words(gate)
    if tests is not None and (at != "final" or not isinstance(tests, dict)):
        raise _gap(f"最後のテストの出口（tests）を受けるのは at final の JSON のオブジェクトだけ（at {at}・{type(tests).__name__}）")
    if judged is not None and (at != "plan" or not isinstance(judged, dict)):
        raise _gap(f"判定の出口（judged）を受けるのは at plan の JSON のオブジェクトだけ（at {at}・{type(judged).__name__}）")


def _carried(b) -> dict:
    """h-plan が控えた判定の出口（b.work(JUDGED_FILE)）から judgment_file・open_units（JSON の配列の文字列）。無ければ空"""
    p = b.work(JUDGED_FILE)
    if not p.is_file():
        return {"judgment_file": "", "open_units": ""}
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise _gap(f"判定の出口の控え {p} が読めない: {e}") from None
    jf, units = doc.get("judgment_file"), doc.get("open_units")
    return {"judgment_file": jf if isinstance(jf, str) else "",
            "open_units": json.dumps(units, ensure_ascii=False) if isinstance(units, list) else ""}


def _closed_round_stop(b) -> dict | None:
    """周を締めた盤面（halted.by stop_after_round。b.stop が拒む）に、盤面を開く口の照らし（entry.open_board）が止めた事実として
    書いた trace の行（STOP_AFTER_END_OP・by stopby.SCOPE_CHECK）の最後の物。無ければ None"""
    if (b.state.get("halted") or {}).get("by") != ENDED_BY:
        return None
    rows = [r for r in report.trace_rows(b, STOP_AFTER_END_OP) if r.get("by") == stopby.SCOPE_CHECK]
    return rows[-1] if rows else None


def _stopped(b) -> dict | None:
    """盤面がもう止まっているなら止めた事実（state.stop か、周を締めた後の照らしの止め _closed_round_stop か halted）。まだなら None"""
    st = b.state
    if st.get("halted") or st.get("stop"):
        return st.get("stop") or _closed_round_stop(b) or st.get("halted")
    return None


def _ended(b) -> bool:
    """1 周の run が周を締めた（halted.by stop_after_round で、人も線も、周を締めた後の照らしも止めていない）。最後のテストの後の
    普通の終わり"""
    st = b.state
    return (st.get("halted") or {}).get("by") == ENDED_BY and not st.get("stop") and _closed_round_stop(b) is None


def _stop_board(b, at: str, reason: str, by: str) -> None:
    """盤面を止める。周を締めた盤面（_ended）は b.stop が拒むので、止めた事実を trace に 1 行（STOP_AFTER_END_OP。at・reason・by）"""
    if _ended(b):
        b.trace(STOP_AFTER_END_OP, at=at, reason=reason, by=by)
    else:
        b.stop(reason, by=by)


def _traced(b, op: str, **kw) -> bool:
    return any(all(row.get(k) == v for k, v in kw.items()) for row in report.trace_rows(b, op))


def _ci_left(b, field="ci_left") -> list:
    """修正の受け付けが周をまたいで手元で回さなかった試験（重ねずに、出た順）。field が final_left なら、直に関わらないので
    回さず最後のテストの段に任せた試験"""
    return list(dict.fromkeys(t for row in report.trace_rows(b, impact.ACCEPT_TRACE_OP) for t in row.get(field) or []))


def _halted_out(b, out: dict, flag, at: str) -> dict:
    """止まった盤面の返り。止め札が在っても b.stop を呼ばず（止めた盤面への stop は Reject）、札の理由は trace にだけ 1 行
    （同じ札を同じ理由で止めた盤面・既に積んだ札は積み増さない）"""
    info = _stopped(b) or {}
    if flag:
        same = info.get("reason") == flag["reason"] and info.get("by") == FLAG_BY_PREFIX + flag["by"]
        if not same and not _traced(b, AFTER_HALT_OP, reason=flag["reason"], by=flag["by"]):
            b.trace(AFTER_HALT_OP, at=at, reason=flag["reason"], by=flag["by"])
    return {**out, "stop": True, "go": False, "ask": False, "why": str(info.get("reason") or "")}


def _answer_policy_gate(b, gate: dict) -> None:
    """policy-gate の答えを盤面の answer に渡す（写しの on_answer_in_round → human_gate_answered が process.human_items に積む）。
    問いがもう無い（Archon の再開で同じ境の節を呼び直した）なら 2 度答えない"""
    decision, text = _gate_words(gate)
    if not b.state.get("pending_human"):
        b.trace("gate_answer_unasked", at="fix", decision=decision)
        return
    if decision in GATE_GO:
        b.answer("continue", text)
    else:
        b.answer("stop", text if text.strip() else GATE_STOP_NOTE)


def _answer_final_gate(b, gate: dict) -> tuple:
    """final-gate（Archon だけの関所。盤面の問いでない）の答えを残す: どの答えも b.work(FINAL_GATE_ANSWER) に {decision, text}
    （stop・reject も。報告が読む）と process.human_items に 1 行（kinds gatepolicy.FINAL_KIND・answer は continue か stop・note は一言の字のまま）。
    同じ答えで呼び直した（Archon の再開）なら積み増さない。返り (止めるか, 止める理由)"""
    decision, text = _gate_words(gate)
    doc = {"decision": decision, "text": text}
    path = b.work(FINAL_GATE_ANSWER)
    try:
        again = json.loads(path.read_text(encoding="utf-8")) == doc
    except (OSError, ValueError):
        again = False
    if not again:
        _write_json(path, doc)
        answer = "continue" if decision in GATE_GO else "stop"
        b.record["process"]["human_items"].append({"round": b.round, "kinds": [gatepolicy.FINAL_KIND], "asked": [FINAL_GATE_FILE],
                                                   "answer": answer, "note": text, "node": FINAL_GATE_BY})
        for row in _waiting_rows(b):   # 守りのファイル・食い違いの申し出の行に人の答えを写す（報告の冒頭 1 に出る）
            row["answer"] = answer
        b.save()
    stop = decision in GATE_STOP
    return stop, (text if text.strip() else FINAL_GATE_STOP_NOTE) if stop else ""


def _out_file(b, nid: str) -> str:
    """今の周に出した節 nid の出力の絶対パス（盤面の外で走る役が読むため。周の番号を仮定しない。今の周に無ければ ""）"""
    info = b.state["outputs"].get(nid)
    return str(b.dir / info["file"]) if info and info.get("round") == b.round else ""


def _notes(b) -> str:
    """今の周の process.human_items の一言（note）を改行で並べた文（字のまま）"""
    items = (b.record.get("process") or {}).get("human_items") or []
    return "\n".join(h["note"] for h in items
                     if isinstance(h, dict) and h.get("round") == b.round and isinstance(h.get("note"), str) and h["note"])


trace_empty_fix = entry.trace_empty_fix     # 機械が p3.fix の空の返答を渡した印（正本は entry。h-plan が take の後に呼ぶ）


def _unit_file_paths(u: dict, repo) -> tuple:
    """単位 1 つが名指すファイル（class_query.how.paths。無ければ key の頭の語）のうち、対象の根からの相対で在るファイルの
    パスと、捨てたパス。how.paths は git の pathspec（ディレクトリ・glob・絶対パスも来る）で、measure.py は根の中の
    ファイルしか測らないので、ここで捨てて数を残す（黙って空の実測にしない）"""
    how = (u.get("class_query") or {}).get("how") or {}
    raw = [p for p in how.get("paths") or [] if isinstance(p, str) and p]
    if not raw and isinstance(u.get("key"), str) and u["key"].split():
        raw = [u["key"].split()[0]]
    root = pathlib.Path(repo).resolve()
    kept, dropped = [], []
    for p in raw:
        q = pathlib.PurePosixPath(p[2:] if p.startswith("./") else p)
        ok = (not q.is_absolute() and ".." not in q.parts and not any(c in p for c in "*?[:")
              and (root / q).is_file())
        (kept if ok else dropped).append(str(q) if ok else p)
    return list(dict.fromkeys(kept)), list(dict.fromkeys(dropped))


def structure_units(b, carried: dict, repo) -> str:
    """判定の直す義務の単位（carried の judgment_file・open_units）を blk-structure の入力の契約 {id, paths, summary} に写して
    b.work(STRUCTURE_UNITS_FILE) に書き、そのパスを返す。summary は単位の reason で、尾に単位のパスと重なる世界の解の行の要点
    （worldmark.unit_note。盤面の根の控えが指す行）を足す。paths が 1 本も残らない単位は写さない（stage_a.read_units は 1 行でも
    paths が空ならファイル全体を落とす）。写さなかった単位と捨てたパスは trace の STRUCTURE_UNITS_OP の 1 行に残す"""
    try:
        doc = json.loads(pathlib.Path(carried["judgment_file"]).read_text(encoding="utf-8"))
        keys = set(json.loads(carried["open_units"] or "[]"))
    except (OSError, ValueError, TypeError):
        doc, keys = {}, set()
    rows, skipped, dropped = [], [], []
    world = worldmark.board_rows(b.dir)
    for u in (doc.get("units") if isinstance(doc, dict) else None) or []:
        if not isinstance(u, dict) or u.get("key") not in keys:
            continue
        paths, bad = _unit_file_paths(u, repo)
        dropped += bad
        if not paths:
            skipped.append(u["key"])
            continue
        reason = u.get("reason") if isinstance(u.get("reason"), str) else ""
        note = worldmark.unit_note(world, paths)   # 単位のパスと類の where が重なる世界の解の行の要点（無ければ ""）
        rows.append({"id": u["key"], "paths": paths, "summary": f"{reason} {note}".strip() if note else reason})
    if skipped or dropped:
        b.trace(STRUCTURE_UNITS_OP, units=skipped, paths=dropped, round=b.round)
    _write_json(b.work(STRUCTURE_UNITS_FILE), rows)
    return str(b.work(STRUCTURE_UNITS_FILE))


def _structure_failed(structured) -> str:
    """構造のブロックの出口が、構造の目の行なしで計画する周か（理由の 1 文。行を受けてよい周は ""）"""
    if not isinstance(structured, dict):
        return "構造のブロックの節が落ちたか走らなかった（出口が無い）"
    if structured.get("status") == "ok":
        return ""
    why = structured.get("reason") or ""
    if not why:
        try:
            doc = json.loads(pathlib.Path(structured.get("structure_file") or "").read_text(encoding="utf-8"))
            why = (doc.get("reason") or "") if isinstance(doc, dict) else ""
        except (OSError, UnicodeDecodeError, ValueError):
            pass
    return f"構造のブロックが status: {structured.get('status') or '無し'} で抜けた" + (f"（{why}）" if why else "")


def structure_edge(board_dir, structured, plan_go=True) -> dict:
    """h-structure: 構造のブロックの出口 structured（飛ばされた・落ちた周は None）を確かめ、盤面の根の控え（structmark）を書く。
    自分の読み書きの失敗（設計の行が読めない・控えを書けない）も節の失敗にせず、status failed と理由で返す（計画は行なしで進む）。
    計画を起こさない周（plan_go が偽）は控えを書かずに status skipped（落ちの印を出さない）"""
    if plan_go is False:
        return {"ok": True, "status": "skipped", "reason": "計画を起こさない周（h-plan の go が偽）", "design_file": "", "wall_s": 0}
    why = _structure_failed(structured)
    got = structured if isinstance(structured, dict) else {}
    design_file, wall = str(got.get("design_file") or ""), got.get("wall_s", 0)
    if not why:
        try:
            structmark.rows(design_file)
        except ValueError as e:
            why = str(e)
    status = "failed" if why else "ok"
    try:
        structmark.write(board_dir, status=status, reason=why, design_file=design_file, wall_s=wall)
    except OSError as e:
        status, why = "failed", (why + "。" if why else "") + f"構造のブロックの控えを書けない: {e}"
    return {"ok": True, "status": status, "reason": why, "design_file": design_file, "wall_s": wall}


WORLD_COUNTS = ("classes", "cached", "skipped", "dropped")   # 世界の解のブロックの出口の数の欄（控えにそのまま写す）


def world_edge(board_dir, worlded, due=True) -> dict:
    """h-world: 世界の解のブロックの出口 worlded（飛ばされた・落ちた周は None）を確かめ、盤面の根の控え（worldmark.write）を書く。
    段の落ち・自分の読み書きの失敗も節の失敗にせず status failed と理由で返す（線を止めない。判定・修正案・関所は行なしで進む）。
    段を回さない周（due が偽: h-mat の world_go が偽か、h-mat が飛ばされた）は控えを書かずに status skipped（run に 1 回の段の
    控えを、回さない周が上書きしない）"""
    if due is False:
        return {"ok": True, "status": "skipped", "reason": "世界の解の段を回さない周", "world_file": ""}
    got = worlded if isinstance(worlded, dict) else {}
    world_file = str(got.get("world_file") or "")
    if not isinstance(worlded, dict):
        why = "世界の解のブロックの節が落ちたか走らなかった（出口が無い）"
    elif got.get("status") != "ok":
        why = f"世界の解のブロックが status: {got.get('status') or '無し'} で抜けた" + (f"（{got['reason']}）" if got.get("reason") else "")
    else:
        why = ""
        try:
            worldmark.rows(world_file)
        except ValueError as e:
            why = str(e)
    status = "failed" if why else "ok"
    counts = {k: got[k] if isinstance(got.get(k), int) else 0 for k in WORLD_COUNTS}
    try:
        worldmark.write(board_dir, status=status, reason=why, world_file=world_file if status == "ok" else "", **counts)
    except OSError as e:
        status, why = "failed", (why + "。" if why else "") + f"世界の解の段の控えを書けない: {e}"
    return {"ok": True, "status": status, "reason": why, "world_file": world_file if status == "ok" else ""}


def after_edge(board_dir, measured) -> dict:
    """直しの後の構造の境: 構造のブロックの出口 measured（飛ばされた・落ちた周は None）の after.json と、今の周の修正案の外れの訳を
    盤面の根の控え（structmark.write_after）に書く。読み書きの失敗も節の失敗にせず status failed と理由で返す（線を止めない）"""
    got = measured if isinstance(measured, dict) else {}
    after, why = {}, ""
    if not got:
        why = "直しの後の構造のブロックの節が落ちたか走らなかった（出口が無い）"
    else:
        try:
            after = json.loads(pathlib.Path(str(got.get("after_file") or "")).read_text(encoding="utf-8"))
            if not isinstance(after, dict):
                raise ValueError("after.json が JSON のオブジェクトでない")
        except (OSError, UnicodeDecodeError, ValueError) as e:
            after, why = {}, f"直しの後の実測の after.json が読めない: {e}"
        if not why and got.get("status") != "ok":
            why = str(got.get("reason") or "直しの後の構造のブロックが status: failed で抜けた")
    try:
        devs = planmarks.deviations(planmarks.read(entry.open_board(pathlib.Path(board_dir), allow_halted=True)))
    except Exception as e:   # 控えが読めなくても実測は残す（外れの訳が無い印を理由に足す）
        devs, why = [], (why + "。" if why else "") + f"修正案の欄が読めない（外れの訳を並べない）: {type(e).__name__}: {e}"
    status = "failed" if why else "ok"
    try:
        structmark.write_after(board_dir, status=status, reason=why, after=after, deviations=devs)
    except OSError as e:
        status, why = "failed", (why + "。" if why else "") + f"直しの後の実測の控えを書けない: {e}"
    return {"ok": True, "status": status, "reason": why}


def _faces(b, nid: str) -> int:
    out = b.output_of_round(nid, b.round) or {}
    return len(out.get("faces") or [])


def _eye_reviews(b) -> dict:
    """独立の目の結果の控え（周の記録 rounds/round-<N>.json か、まだ無ければ盤面の記録の reviews）"""
    try:
        rounded = json.loads((b.dir / "rounds" / f"round-{b.round}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        rounded = b.record
    return rounded.get("reviews") or {}


class Eyes(NamedTuple):
    """独立の目の判定の行（rows）と、目を blocked・not_run・missing に分けた数え（counts。report.EyeCounts）。1 度の盤面の読みから作る"""
    rows: list
    counts: report.EyeCounts


def _eyes(b) -> Eyes:
    """独立の目（R1〜R4）の判定の行と、目の数え（report.eye_counts。関所の文・関所を開ける理由・冒頭 1 の残りの正本）。判定は周の記録
    （rounds/round-<N>.json。目の受け付けの settle が周を締めて書く）か、まだ無ければ盤面の記録から。not_run は目の判定でなく機械が書く欠け
    （返答が無い・止めた周）なので、行には出すが関所を開ける理由には数えない（report.NOT_RUN_GATE_NOTE）。結果が無い目も同じ（report.MISSING_GATE_NOTE）"""
    reviews = _eye_reviews(b)
    lines = []
    for name in report.EYES:
        r = reviews.get(name)
        if not isinstance(r, dict):
            lines.append(f"  - {gatemarks.EYES[name]}（{name}）: 結果が無い")
            continue
        reason = " ".join(str(r.get("reason") or "").split())
        lines.append(f"  - {gatemarks.eye_named(name, r.get('status'))}" + (f"——理由: {reason}" if reason else ""))
        if name == "R2":
            lines += _r2_inputs(b)
    fell = gatemarks.fell_lanes(b)
    if fell:
        lines.append(f"  - 落ちた筋: {fell}")
    return Eyes(lines, report.eye_counts(b, reviews))


ROLE_WORDS = {"design": "独立の設計を作る役", "compare": "独立の設計と差分を比べる役"}   # R2 の 2 つの役の平易な名（記録の名は括弧に回す）


def _r2_inputs(b) -> list:
    """R2 の行の下に、R2 が『渡されていない』と書いた文と、そのうち渡していた物（compare の claims_given）と、支度の時に R2 の 2 つの役へ渡した前提の入力の控え（独立の目の出口の
    premise_inputs。一番新しい周の eyes-exit.json）と、独立設計の後に来た人の答え（compare の after_design）を並べる。人が同じ枚で突き合わせる（受け付けは拒まない）"""
    exits = scopes.all_rounds(b.dir, "eyes-exit.json")   # 独立の目の include の scope の根に在る（周の順）
    try:
        pi = json.loads(exits[-1].read_text(encoding="utf-8")).get("premise_inputs") if exits else None
    except (OSError, ValueError):
        pi = None
    if not isinstance(pi, dict):
        return ["    - 独立の設計と比べる目に渡した入力の控えが無い（R2）"]
    out = [f"    - 独立の設計と比べる目が渡されていないと書いた（R2）: {c}" for c in pi.get("claims") or []]
    led = pi["compare"] if isinstance(pi.get("compare"), dict) else {}
    out += [f"    - 独立の設計と比べる目が渡されていないと書いたが、渡していた（R2）: {m.get('claim')} ← {m.get('kind')}: {m.get('what')}"
            for m in led.get("claims_given") or []]
    late = led.get("after_design")
    if late:
        out.append(f"    - 独立設計の後に来た人の答え（{ROLE_WORDS['compare']}にだけ渡った）: " + "／".join(late))
    for role in ("design", "compare"):
        led = pi.get(role)
        if not isinstance(led, dict):
            out.append(f"    - {ROLE_WORDS[role]}に渡した入力の控えが無い（{role}）")
            continue
        given = "／".join(f"{g.get('kind')}: {g.get('what')}" for g in led.get("given") or []) or "（前提の入力は無い）"
        out.append(f"    - {ROLE_WORDS[role]}に渡した前提の入力（{role}）: {given}")
        held = led.get("withheld") or []
        if held:
            out.append("    - run に在ったが渡していない: "
                       + "／".join(f"{w.get('kind')}: {w.get('what')}（{w.get('why')}）" for w in held))
    return out


def _final_text(b, tests, objection: str, eyes: Eyes, rest: report.Rest, repo, run_id: str) -> str:
    """最後の関所の文: 最後のテストと修正前のテスト（entry.baseline_line）・受け付けが手元で回さなかった試験・最後のテストの段に任せた試験・受け付けの束が
    赤緑を確かめずに通した回（report.gates_lines）・差分の審査の穴の数・穴と独立の目の行の枝の名札（report.branch_rows）・手直しの結果・止めずに残った異議・
    決着した再審の結果（report.rejudge_lines。関所を開ける理由には数えない）・構造のブロックが落ちた周の印
    （structmark.note）・事前審査の壁打ちの往復（converge.lines）・独立の目の判定・clean が消したファイル・レンズ・仕組みの異常・
    残りの件数（report.always_rows。結末に依らず常に）・盤面の問い・判定の役が保留にしたままの問い（gatemarks.held_lines）と答え方（gatemarks.ANSWER_HOW）・関所か依頼の answers で答えた問い（gatemarks.answered_lines）・どの問いにも当たらなかった依頼の答え（gatemarks.unmatched_answer_lines）・読めなかった保留（gatemarks.unread_hold_lines）を 1 枚に。「盤面の問い: 無い」はどれも無い時だけ。行の主語は平易な名で、
    盤面の節・目の名・状態の語は括弧に回す（gatemarks.named・eye_named）"""
    tests = tests or {}
    lines = [f"最後の人の関所（最後のテストと独立の目の後・報告の前）: テストは{rest.tests_word}", ""]
    if tests.get("by"):
        lines.append(f"- テストの一式: {entry.suites_line(tests, role_status=entry.role_ci_status(b, tests))}")
    lines.append(f"- {entry.baseline_line(b)}")
    left = _ci_left(b)
    if left:
        lines.append(f"- 修正の受け付けが手元で回さなかった試験（{len(left)} 件。run はその緑を確かめない——取り込みの前に人が回すか CI で確かめる）:")
        lines += [f"  - {t}" for t in left]
    final = _ci_left(b, "final_left")
    if final:
        lines.append(f"- 修正の受け付けが変更に直には関わらないので回さず、最後のテストの段に任せた試験（{len(final)} 件。上のテストの"
                     "一式に入る物はそこで確かめた。入らない物は CI で確かめる）:")
        lines += [f"  - {t}" for t in final]
    far = _ci_left(b, "final_far")
    if far:
        lines.append(f"- 修正の受け付けが一式を回す理由にせず、最後のテストの段に任せた変更から遠く、どの試験に関わるか読み切れないファイル（{len(far)} 件）:")
        lines += [f"  - {t}" for t in far]
    lines += [f"- {x}" for x in report.gates_lines(b)]   # 修正の受け付けの束が受け入れのテストの赤緑を確かめずに通した回
    lines.append(f"- ログ: {tests.get('log') or '（無い）'}")
    if tests.get("reason"):
        lines.append(f"- 走れなかった理由: {tests['reason']}")
    lines.append(f"- run の作業ツリー: {pathlib.Path(repo).resolve()}")
    lines.append(f"- 差分の審査の穴: {_faces(b, 'p3.delta_review')} 件（2 回目の審査: {_faces(b, 'p3.delta_review2')} 件）")
    lines += [x if x[:1].isspace() else f"- {x}" for x in report.branch_rows(b)]   # 穴と目の行の枝の名札（線の木の段 4a）
    handled = (b.output_of_round("p3.delta_fix", b.round) or {}).get("handled") or []
    lines.append(f"- {gatemarks.named('p3.delta_fix')}の結果（{len(handled)} 件）:")
    lines += [f"  - {h.get('key')}: {gatemarks.HANDLED_WORDS.get(h.get('handled'), '')}（{h.get('handled')}）——{h.get('how')}"
              for h in handled if isinstance(h, dict)] or ["  - （無い）"]
    lines.append(f"- 止めずに残った異議: {objection or '無い'}")
    settled = report.rejudge_lines(b)
    lines += ["- 再審で決着した結果:", *[f"  {x}" if x.startswith("  ") else f"  - {x}" for x in settled]] if settled \
        else ["- 再審: 無い"]
    missing = structmark.note(structmark.read(b.dir))
    if missing:
        lines.append(f"- 構造のブロック: {missing}")
    lines += [x if x[:1].isspace() else f"- {x}" for x in structmark.after_lines(b.dir)]   # 直しの後の実測（増えた所・外れの訳）
    passed = gatemarks.lines(b)
    if passed:
        lines.append(f"- 直す前の関所で通した項目（決め手が在るので聞かずに通した行と、人が通したので後の関所で聞き直さなかった行。{len(passed)} 件）:")
        lines += [f"  - {x}" for x in passed]
    lines += [x if x[:1].isspace() else f"- {x}" for x in converge.lines(b)]   # 往復ごとの行は自分の「  - 」を持つ
    lines.append(f"- 独立の目の判定（阻害: {'・'.join(e['name'] for e in eyes.counts.blocked) or '無い'}）:")
    lines += eyes.rows
    # clean が消したファイル・レンズ・仕組みの異常・残りの数えられる分（0 も、走らせていない・調べていない・読めないも。検証器は数えない）
    lines += [x if x[:1].isspace() else f"- {x}" for x in report.always_rows(b, rest=rest)]
    asking = b.state.get("pending_human")
    if asking:
        lines.append(f"- {gatemarks.named(asking.get('node'))}が人に聞いている問い（記録のまま引く）:")
        lines += [f"  {x}" for x in gatemarks.quote(asking.get("question"))]
        lines += [f"  - {x}" for x in asking.get("items") or []]
        lines.append("  - この関所の答えはこの問いに答えない。問いは報告の冒頭と次の run の依頼の下書きへ渡る")
    held = gatemarks.held_lines(b)
    if held:
        lines.append(f"- 判定の役が人に聞くと保留にしたままの問い（問いの台帳・{len(held)} 件。この関所の答えは問いに答えない。"
                     "問いは報告の冒頭に並ぶ）:")
        lines += [f"  - {x}" for x in held]
        lines.append(f"  {gatemarks.ANSWER_HOW}")
    done = gatemarks.answered_lines(b)
    if done:
        lines.append(f"- {gatemarks.ANSWERED_HEAD}（問いの台帳・{len(done)} 件。保留の件数には数えない）:")
        lines += [f"  - {x}" for x in done]
    unmatched = gatemarks.unmatched_answer_lines(b)
    lines += [f"- {x}" for x in unmatched]
    lines += [f"- {x}" for x in gatemarks.unread_hold_lines(b)]
    if not asking and not held and not done and not unmatched:
        lines.append("- 盤面の問い: 無い")
    lines += ["", "答え方（人が決める関所。依頼者に聞いて、その言葉で答える）:",
              f"- 報告へ進める: {answer.line(run_id, 'continue', '<一言>')}",
              f"- 止める: {answer.line(run_id, 'stop', '<理由>')}（報告は出る）"]
    return "\n".join(lines) + "\n"


def _protected(b, repo) -> tuple:
    """run の修正の差分（修正前の版＝state.inputs.review_rev。固まる前は record.base＝p0.base が固めた版。そこから今の作業ツリー
    まで。commit・消した物・未追跡を含む）のうち守りのファイルに当たる物と、テストの変更の許し（承認済みの修正案の rewrite_tests と
    裁定 fix_test_scope の範囲。conflict.test_permits）が名指したテストの物。変更から入る run の record.base は merge-base で、
    PR にもとからある変更まで数えてしまうので起点にしない。
    返り (rows, rev, 確かめられなかった理由)。一覧・版・git・申し出の控えが読めなければ rows は空で理由を返す（fail closed）"""
    rev = ""
    try:
        rev = accept.resolve_rev(repo, (b.state.get("inputs") or {}).get("review_rev") or b.record.get("base") or "")
        ruled = conflict.ruled_test_doc(b)
        return protect.touched(repo, rev) + (protect.touched(repo, rev, ruled) if ruled else []), rev, ""
    except (protect.Broken, Reject, BoardGap) as e:
        return [], rev, str(e)


def _stat(r) -> str:
    return f"+{r['added']} −{r['deleted']}" if r.get("added") is not None else "行数なし"


def _protected_text(rows, rev: str, err: str, repo) -> str:
    """最後の関所の文の冒頭 3 行の直後の節（触った守りのファイル・行数・規則・差分の見方。確かめられなければその理由）"""
    if err:
        return (f"## {PROTECTED_UNKNOWN}（差分が一覧に触れていないとは言えない）\n\n- 理由: {err}\n"
                f"- 一覧: {protect.MANIFEST}\n\n")
    lines = [f"## {PROTECTED_HEAD}（{len(rows)} 件。works 自身の試験・柵・受け付けの口。通すのは人の continue だけ）", ""]
    lines += [f"- {x}" for x in protect.lines(rows)]
    lines += [f"- 差分: git -C {pathlib.Path(repo).resolve()} diff {rev[:12]} -- <パス>（未追跡は新しいファイル）",
              f"- 一覧: {protect.MANIFEST}", "", ""]
    return "\n".join(lines)


def _row(b, node: str):
    """今の周の process.human_items の node の行（無ければ None）"""
    items = (b.record.get("process") or {}).get("human_items") or []
    return next((h for h in items if isinstance(h, dict) and h.get("node") == node and h.get("round") == b.round), None)


def _protected_row(b):
    return _row(b, PROTECTED_BY)


def _waiting_rows(b) -> list:
    """最後の関所の答えを写す今の周の行（守りのファイル・食い違いの申し出）"""
    return [r for r in (_row(b, PROTECTED_BY), _row(b, stopby.CONFLICT)) if r is not None]


def _record_conflict(b, asks: list) -> None:
    """process.human_items に今の周の 1 行（kinds conflict・answer は最後の関所の答えまで None・note に件数と単位）。
    呼び直しでは積み増さず、答えの前なら中身だけを今の申し出に合わせる"""
    note = f"{conflict.HEAD} {len(asks)} 件: " + "、".join(asks) + "——最後の関所で人が決める（通すのは continue だけ）"
    row = _row(b, stopby.CONFLICT)
    if row is None:
        b.record["process"]["human_items"].append({"round": b.round, "kinds": [conflict.KIND], "asked": list(asks),
                                                   "answer": None, "note": note, "node": stopby.CONFLICT})
    elif row.get("answer") is None and (row.get("asked"), row.get("note")) != (list(asks), note):
        row.update(asked=list(asks), note=note)
    else:
        return
    b.save()


def _conflict_text(asks: list) -> str:
    """最後の関所の文の節（裁定役か機械が人に回した食い違いの申し出。どの単位を直さずに残したか）"""
    lines = [f"## {conflict.HEAD}（{len(asks)} 件。裁定役か機械が人に回した。単位は直さずに残した。通すのは人の continue だけ）", ""]
    lines += [f"- {x}" for x in asks]
    return "\n".join(lines + ["", ""])


def _handoff_text(handoffs: list) -> str:
    """最後の関所の文の節（修正役が人に回した物。report.handoff_lines の行を全部）"""
    lines = [f"## {report.HANDOFF_HEAD}（{len(handoffs)} 件。通すのは人の continue だけ）", ""]
    lines += [f"- {x}" for x in handoffs]
    return "\n".join(lines + ["", ""])


def _unproven_text(unproven: list) -> str:
    """最後の関所の文の節（判定者の問いを例で試していない単位。閉鎖の数え直しはその問いのまま）"""
    lines = [f"## {querytest.UNPROVEN_HEAD}（{len(unproven)} 件。閉鎖の数え直しは例で試していない問いのまま）", ""]
    lines += [f"- {x}" for x in unproven]
    return "\n".join(lines + ["", ""])


def _closure_text(closure: list, head: str = querytest.CLOSURE_HEAD) -> str:
    """最後の関所の文の節（修正の受け付けが判定者の問いで数え直した単位ごとの表のうち、head の見出しに載せる単位。
    同じ run の中で直した修正案の項目の行も、見出し replan.AMEND_HEAD でこの形に並べる）"""
    lines = [f"## {head}（{len(closure)} 件）", ""]
    lines += [f"- {x}" for x in closure]
    return "\n".join(lines + ["", ""])


def _record_protected(b, rows, err: str) -> None:
    """process.human_items に今の周の 1 行（kinds protected_files・answer は最後の関所の答えまで None・note に一覧）。
    呼び直し（Archon の再開）では積み増さず、答えの前なら中身だけを今の差分に合わせる"""
    if err:
        asked, note = [f"{PROTECTED_UNKNOWN}: {err}"], f"{PROTECTED_UNKNOWN}——最後の関所で人が決める（{err}）"
    else:
        asked = protect.lines(rows)
        note = (f"{PROTECTED_HEAD} {len(rows)} 件: " + "、".join(f"{r['path']}（{_stat(r)}・規則 {r['id']}）" for r in rows)
                + "——最後の関所で人が決める（通すのは continue だけ）")
    row = _protected_row(b)
    if row is None:
        b.record["process"]["human_items"].append({"round": b.round, "kinds": [PROTECTED_KIND], "asked": asked,
                                                   "answer": None, "note": note, "node": PROTECTED_BY})
    elif row.get("answer") is None and (row.get("asked"), row.get("note")) != (asked, note):
        row.update(asked=asked, note=note)
    else:
        return
    b.save()


def entry_edge(b) -> dict:
    """h-entry（start の後・判定の前）: 盤面の ready から、任せ先の役・ブロックを回すかの旗。判定から入る run と仕様から入る run の
    両方で、pr-checking・premising・purposing の when: はこの欄だけを読む"""
    ready = b.ready()
    return {"go": True, "pr_go": "p0.parallel_pr" in ready, "premises_go": PREMISES_NODE in ready,
            "purpose_go": "p0.purpose" in ready, "spec_go": any(n.startswith("spec.") for n in ready)}


def spec_edge(b) -> dict:
    """h-spec（仕様の段の後・並行 PR の前。いつも走る）: 盤面の engine の節を回し直す（entry.resume_after_ci と同じ輪。仕様の段を
    挟む run では、版を固める p1.worktree_before が仕様の固め spec.freeze を待つので、並行 PR の確かめ p0.parallel_pr はここで
    初めて出る）。pr-checking の when: はこの欄 pr_go だけを読む（仕様の段の無い run では h-entry と同じ値）。test_cmd は start の
    控えの値（止められた run の呼び直しで道を替えない）。回し直しが入力の誤りで拒まれたら（並行 PR の確かめの拒みなど）、境の節を
    落とさずに盤面を止め（by SPEC_EDGE_BY。CI の役の後の入口へ戻る口 ci_role と同じ扱い）、理由つきで stop"""
    try:
        entry.resume_after_ci(b, test_cmd=str(startrec.read(b.dir).get("test_cmd") or ""))
    except entry.InputRefused as e:
        reason = f"仕様の段の後に盤面の engine の節を回し直せない: {e}"
        entry.open_board(b.dir).stop(reason, by=SPEC_EDGE_BY)
        return {"stop": True, "go": False, "pr_go": False, "why": reason}
    b = entry.open_board(b.dir)
    return {"go": True, "pr_go": "p0.parallel_pr" in b.ready()}


def _guard(b, repo) -> tuple:
    """守りのファイルと食い違いの申し出を確かめ、在れば今の周の行（答えは最後の関所まで None）に書く。返り (rows, rev, err, asks)。
    h-final と、関所の答えの無い h-eyes が呼ぶ（独立の目のブロックが落ちて h-final が飛ばされた run でも、行を見ずに通さない）"""
    rows, rev, err = _protected(b, repo)
    try:
        asks = conflict.human_lines(b)
    except BoardGap as e:   # 申し出の控えが読めない: 黙って空にせず、人に回す
        asks = [f"申し出の控えが読めない（{e}）"]
    if rows or err:
        _record_protected(b, rows, err)
    if asks:
        _record_conflict(b, asks)
    return rows, rev, err, asks


def _final_needs(b, rest: report.Rest, objection: str, rows, err: str, asks: list, mismatched: list, *,
                 handoffs: list = ()) -> list:
    """最後の関所を開ける理由（1 件 1 句）。開ける理由が要る開き方で開くかはこの列の空でなさだけで決め（gatepolicy.opens）、_final_head の 1 行目もこの列を
    並べる（理由を足すのはここだけ）。handoffs は修正役が人に回した物（report.handoff_lines。食い違いの申し出と同じく、役だけで
    決めた代償は人が決める）"""
    why = []
    if err:
        why.append(f"{PROTECTED_UNKNOWN}（人の確かめが要る）")
    elif rows:
        why.append(f"{PROTECTED_HEAD}（{len(rows)} 件。人の確かめが要る）")
    if rest.tests_word != "緑":
        why.append(f"最後のテストが{rest.tests_word}")
    if asks:
        why.append(f"食い違いの申し出を人に回した（{len(asks)} 件）")
    if handoffs:
        why.append(f"修正役が人に回した物が在る（{len(handoffs)} 件）")
    if rest.counts.blocked:
        why.append(f"独立の目が阻害を返した（{'・'.join(e['name'] for e in rest.counts.blocked)}）")
    if mismatched:
        why.append(f"直したという申告と機械の数え直しが合わない単位が在る（{len(mismatched)} 件）")
    fenced = structmark.after_rows(b.dir)
    if fenced:
        why.append(f"考えの住処の柵の数が増えた（{len(fenced)} 件。住処へ寄せるか、増やすなら地図と柵の表を直す）")
    if b.state.get("pending_human"):
        why.append("人に聞いている問いが盤面に在る")
    if objection:
        why.append("止めずに残った異議が在る")
    return why


def _final_head(b, head: str, why: list, guarded: bool) -> list:
    """最後の関所の冒頭 3 行（gatemarks.head3）。起きたこと＝関所を開けた理由（_final_needs。守りのファイルはこの行で名指す）と、
    修正の段が単位を止めて持ち越したなら受けた単位と止めた単位の 1 文（report.split_line）・
    決めてほしいこと＝報告へ進めるか止めるか・推し＝判定の役が問いの理由に書いた推し（機械は作らない）"""
    held = gatemarks.held_lines(b)
    happened = (f"最後のテストと独立の目が済み、報告の前で止まった。テストは{head}。"
                + ("開けた理由: " + "・".join(why) if why else f"関所はいつも開く設定（{gatepolicy.head_words({gatepolicy.FINAL_KEY: gatepolicy.ALWAYS})}）で、ほかに開けた理由は無い")
                + (f"。判定の役が人に聞くと保留にしたままの問いも在る（{len(held)} 件。関所を開ける理由には数えない）" if held else ""))
    split = report.split_line(b)   # 修正の段が受けた単位と止めて持ち越した単位（止めていなければ空）
    happened += f"。{split}" if split else ""
    decide = ("報告へ進めて run を終えるか、止めるか（打つ行は末尾の答え方）"
              + ("。守りのファイルの変更は下の最初の節を確かめてから通す" if guarded else ""))
    asking = b.state.get("pending_human") or {}
    return gatemarks.head3(happened, decide, gatemarks.pushes([*held, *(asking.get("items") or [])]))


def final_edge(b, repo, *, run_id: str, mode: str, tests) -> dict:
    """h-final（最後のテストと独立の目の後）: ask は開き方 mode（gatepolicy.opens）で決める。開ける理由は、最後のテストが緑でない（赤・環境で起こせなかった・
    走れなかった・走らなかった）・盤面が人に聞いている・止めずに残った異議が在る・守りのファイルを触った（確かめられなかった）・独立の目が
    阻害を返した・修正の受け付けの数え直しが修正役の申告と合わない単位が在る・修正役が人に回した物（report.handoff_lines）が在る時。文は冒頭 3 行（_final_head。開けた理由・決めて
    ほしいこと・推し）で始まり、守りのファイルはその 1 行目で名指し、3 行の直後の最初の節と process.human_items の 1 行にもなる。
    開いた関所の文は、例で証明できない単位と、同じ run の中で直した修正案の項目（replan.lines）も並べる（開ける理由には数えない）。案の直しを諦めた fix_plan_item の単位は ask_human と
    同じ食い違いの申し出の行（conflict.human_lines）。文は b.work(FINAL_GATE_FILE) にも。残りは report.rest_outside_validator を 1 度だけ作り（検証器は
    数えない）、exit_problem は渡さない: ok でない目の出口は eyes.collect が b.stop し、この関所は開かない"""
    eyes = _eyes(b)
    absorbed = report.absorbed_falls(reads.events_for(run_id), pathlib.Path(__file__).resolve().parents[2],
                                     seen=("eyeing",))   # 目の段の落ちは目の欄（結果が無い目）が数える
    rest = report.rest_outside_validator(b, tests=tests, counts=eyes.counts, absorbed=absorbed)
    head = rest.tests_word
    left = rejudge.unsettled(b)
    objection = "" if left["settled"] else left["text"]
    rows, rev, err, asks = _guard(b, repo)
    if _stopped(b) and not _ended(b):   # 確かめが盤面を止めた（修正案の欄の控えの食い違い）: 答えが効かない関所は開かない
        return {}
    guarded = bool(rows) or bool(err)
    # 申告と数え直しが合わない単位は、前は返答全体を拒んだ形なので関所を開ける。閉じていないだけの単位（修正役が remaining で
    # 残した）は前も通っていたので、見せるだけ
    mismatched = querytest.closure_lines(b, mismatched_only=True)
    handoffs = report.handoff_lines(b)
    why = _final_needs(b, rest, objection, rows, err, asks, mismatched, handoffs=handoffs)
    if not gatepolicy.opens(mode, reasons=why, guarded=guarded):
        return {}
    unproven = querytest.unproven_lines(b.dir)   # 人に見せる印で、関所を開ける理由（why）には数えない
    stuck = querytest.closure_lines(b, stuck_only=True)
    closure = querytest.closure_lines(b, claimed=report.claimed_units(b))
    try:   # 案の直しの記録の行（関所を開ける理由には数えない）。控えが読めなければその文を 1 行に
        amend = replan.lines(b)
    except BoardGap as e:
        amend = [str(e)]
    text = ("\n".join(_final_head(b, head, why, guarded)) + "\n\n"
            + (_protected_text(rows, rev, err, repo) if guarded else "") + (_conflict_text(asks) if asks else "")
            + (_handoff_text(handoffs) if handoffs else "")
            + (_closure_text(stuck, querytest.STUCK_HEAD) if stuck else "")
            + (_unproven_text(unproven) if unproven else "") + (_closure_text(closure) if closure else "")
            + (_closure_text(amend, replan.AMEND_HEAD) if amend else "")
            + _final_text(b, tests, objection, eyes, rest, repo, run_id))
    _write_text(b.work(FINAL_GATE_FILE), text)
    return {"ask": True, "gate_text": text, "gate_file": str(b.work(FINAL_GATE_FILE))}


def _done_this_round(b, nid: str) -> bool:
    info = b.state["outputs"].get(nid)
    return b.node_state(nid) == "done" and bool(info) and info.get("round") == b.round


def _hand(b, board_dir, nid: str, reply: dict, repo) -> dict:
    """機械が役の返答を盤面へ渡す（判定のブロックが受けた判定・直す物が無い周の空の修正）。手順は entry.hand の 1 か所（待っている
    instance が無ければ BoardGap——線の順の誤り）"""
    return entry.hand(b, board_dir, nid, reply, repo)


def _judgment(judged) -> tuple:
    """判定のブロックの出口から (判定の返答, 読めない理由)。読めれば理由は空。judgment.json の class_query の例（hits・misses）は
    写しの型が持てないので外す（querytest.split）"""
    path = judged.get("judgment_file") if isinstance(judged, dict) else None
    if not isinstance(path, str) or not path:
        return None, "判定のブロックの出口（judgment_file）が届かない"
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"判定のファイル {path} が読めない（{type(e).__name__}: {e}）"
    if not isinstance(doc, dict):
        return None, f"判定のファイル {path} が JSON のオブジェクトでない（{type(doc).__name__}）"
    return querytest.split(doc)[0], ""


def _premises_reply(premised) -> tuple:
    """前提のブロックの出口から (実測役の返答, 読めない理由)。読めれば理由は空"""
    path = premised.get("constraints_file") if isinstance(premised, dict) else None
    if not isinstance(path, str) or not path:
        return None, "前提のブロックの出口（constraints_file）が届かない"
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return None, f"前提のファイル {path} が読めない（{type(e).__name__}: {e}）"
    if not isinstance(doc, dict):
        return None, f"前提のファイル {path} が JSON のオブジェクトでない（{type(doc).__name__}）"
    return doc, ""


def judge_edge(b, board_dir, repo, *, run_id: str, adapter_mode: str, premised=None) -> dict:
    """h-judge の固有の仕事（前提の役の後・判定の前。計画 P1 Task 24・P1-R9・〔線A計〕T22）。順:
    1. 包みの確かめ: reads.adapter_seen（この run の worktree の包みの起動の記録。盤面を作った後の行）が偽で adapter_mode が
       optional でなければ b.stop("包みが通っていない: …", by=stopby.ADAPTER) で stop（_adapter_guard）。決まりは「包みの確かめは、
       この run で役が 1 つ起きた後の最初の境の節で止める」。固定材料から始めた盤面（fixture.adopted）はここまでに起きた役が
       無いので確かめず、trace に ADAPTER_FIXTURE_OP の 1 行を残して h-review（修正のブロックと再審の後）に回す
    2. 表で p0.premises が role なのに盤面で今の周に済んでいなければ、前提のブロックの出口 premised の constraints_file を読んで
       entry.take(p0.premises)（起こした印を置いてから。盤面の写しの schema・measured_needs_output・writes が当たる）。
       出口が届かない・読めない・盤面が受けないなら b.stop("前提の実測が盤面に無い: …", by=stopby.PREMISES) で stop。
       済んでいれば渡さない（Archon の再開で呼び直しても同じ）
    3. go True・premises_file は盤面の state.outputs["p0.premises"] の置き場（絶対パス。na・表に無い節なら空）・
       purpose_go は目的の文（p0.purpose）が盤面で待っているか（前提を渡した後の ready。purposing の when:）"""
    board_dir = pathlib.Path(board_dir)
    if adapter_mode != "optional" and fixture.adopted(board_dir) is not None:
        # 固定材料から始めた run は修正役が最初の役で、ここまでに起きた役が無い。確かめは h-review で
        b.trace(ADAPTER_FIXTURE_OP, at="judge")
    else:
        stopped = _adapter_guard(b, board_dir, repo, run_id=run_id, adapter_mode=adapter_mode)
        if stopped:
            return stopped
    row = b.table.nodes.get(PREMISES_NODE) if b.table is not None else None
    if row is not None and row.by == "role" and b.node_state(PREMISES_NODE) != "na" and not _done_this_round(b, PREMISES_NODE):
        reply, why = _premises_reply(premised)
        if not why:
            got = _hand(b, board_dir, PREMISES_NODE, reply, repo)
            why = "" if got["ok"] else f"盤面が前提の実測を受けない: {got['reason']}"
        if why:
            reason = f"前提の実測が盤面に無い: {why}"
            entry.open_board(board_dir).stop(reason, by=stopby.PREMISES)
            return {"stop": True, "go": False, "why": reason}
        b = entry.open_board(board_dir)
    return {"go": True, "premises_file": _out_file(b, PREMISES_NODE), "purpose_go": PURPOSE_NODE in b.ready()}


def _adapter_guard(b, board_dir, repo, *, run_id: str, adapter_mode: str) -> dict | None:
    """包みの確かめ: adapter_mode が optional でなく、reads.adapter_seen（この run の worktree の包みの起動の記録）が偽なら
    b.stop("包みが通っていない: …", by=stopby.ADAPTER) をして stop の返りを返す。通れば None。呼ぶのは、この run で役が 1 つ
    起きた後の最初の境の節（通常の盤面は h-judge、固定材料から始めた盤面は h-review）"""
    if adapter_mode == "optional":
        return None
    seen = reads.adapter_seen(pathlib.Path(board_dir), run_id, repo=repo)
    if seen["seen"]:
        return None
    reason = f"包みが通っていない: {'・'.join(seen['whys'])}。{ADAPTER_HINT}"
    b.stop(reason, by=stopby.ADAPTER)
    return {"stop": True, "go": False, "why": reason}


def _capture_fixture(b, board_dir, repo, run_id: str) -> None:
    """h-fix の go の後の 1 段: 1 周目なら fixture.capture（既に写していれば書き直さない。固定材料から始めた盤面は capture が
    写さない）。OSError・ValueError は盤面の trace に FIXTURE_FAILED_OP の 1 行を残して続ける（写せなくても run を止めない）"""
    if b.round != 1:
        return
    try:
        fixture.capture(pathlib.Path(board_dir), repo, run_id=run_id, pack_root=entry.PACK)
    except (OSError, ValueError) as e:
        b.trace(FIXTURE_FAILED_OP, at="fix", error=f"{type(e).__name__}: {' '.join(str(e).split())}")


def _role_ready(b, where: str) -> list:
    """盤面の ready のうち、表の where が where の役の節"""
    return [n for n in b.ready() if b.table is not None and n in b.table.nodes and b.table.nodes[n].by == "role"
            and b.table.nodes[n].where == where]


def mat_edge(b, board_dir, repo) -> dict:
    """h-mat の固有の仕事（目的の文の後・P1 の目の前。計画 P1 Task 32・33）。順:
    1. 表で p0.purpose が role なのに盤面で今の周に済んでいなければ、目的の文のブロックが盤面の根に置いた purpose.json
       （core の purpose.read_purpose。blk-purpose の受け付けが書く）を読んで entry.take(p0.purpose)（起こした印を置いてから。
       盤面の写しの schema が当たる）。無い・読めない・盤面が受けないなら b.stop("目的の文が盤面に無い: …", by=stopby.PURPOSE) で
       stop。済んでいれば渡さない（Archon の再開で呼び直しても同じ）。na（条件）なら渡さない
    2. go True（判定へ）・mat_go は P1 の目（表の where が blk-material の役の節）が盤面で 1 つでも待っているか。
       今の周の判定（p2.diagnose）が既に済んだ盤面
       （固定材料から始めた run）は go 偽（判定の支度は待っていない p2.diagnose を線の順の誤りとして拒む）
    3. world_go は世界の解の段（判定の前に run で 1 回）を回すか（_world_due）。回す周は段の入力の目的の文のファイル
       world_purpose_file を今の周の作業の置き場に組む"""
    board_dir = pathlib.Path(board_dir)
    row = b.table.nodes.get(PURPOSE_NODE) if b.table is not None else None
    if row is not None and row.by == "role" and b.node_state(PURPOSE_NODE) == "pending" and not _done_this_round(b, PURPOSE_NODE):
        try:
            _, reply = purpose.read_purpose(board_dir)
            why = ""
        except Reject as e:   # 無い・読めない・型の外。理由は盤面の止めの文へ
            reply, why = None, str(e)
        if not why:
            got = _hand(b, board_dir, PURPOSE_NODE, reply, repo)
            why = "" if got["ok"] else f"盤面が目的の文を受けない: {got['reason']}"
        if why:
            reason = f"目的の文が盤面に無い: {why}"
            entry.open_board(board_dir).stop(reason, by=stopby.PURPOSE)
            return {"stop": True, "go": False, "why": reason}
        b = entry.open_board(board_dir)
    go = not _done_this_round(b, DIAGNOSE_NODE)
    return {"go": go, "mat_go": bool(_role_ready(b, MAT_BLOCK)), **_world_due(b, board_dir, go)}


def _world_due(b, board_dir: pathlib.Path, go: bool) -> dict:
    """{world_go, world_purpose_file}: 判定へ進む周で、入力 features_off の world で切っておらず、盤面の根に世界の解の段の控えが
    まだ無ければ（run で 1 回。呼び直し・次の周は控えが在るので回さない）回す。回す周は目的の文と、目的の役が分けた依頼の解き方
    （worldmark.means_of）を段の入力の形 {purpose_text, means} にして b.work(WORLD_PURPOSE_FILE) に書く。目的の文が読めなければ
    回さない（目的の文の無い盤面は上で止めている）"""
    no = {"world_go": False, "world_purpose_file": ""}
    if not go or entry.WORLD_FEATURE in entry.cut_of(startrec.read(board_dir)) or worldmark.read(board_dir) is not None:
        return no
    try:
        _, doc = purpose.read_purpose(board_dir)
    except Reject:
        return no
    p = b.work(WORLD_PURPOSE_FILE)
    _write_json(p, {"purpose_text": doc["purpose_text"], "means": worldmark.means_of(board_dir)})
    return {"world_go": True, "world_purpose_file": str(p)}


def rejudge_edge(board_dir, repo) -> dict:
    """h-rejudge の固有の仕事（修正の後・中の検査の前。計画 P1 Task 31・rejudge 設計 23c）: 修正役が判定に異議
    （rejudge_requested）を出した周は、盤面が再審の節（p2.rejudge）を出して待つ。その節は p4.ci・p3.gates_cut の deps なので、
    回さないと最後のテストが出ない（run 28）。core の rejudge.route が盤面を settle し、待っている再審の節の役を返す——判定役の
    会話の続きで起こす役なら会話を確かめ（session_ready）、確かめられなければ役を起こさずに盤面を止める（by works:rejudge-session）。
    返り: go は回す役が在るか、止めたら stop と理由"""
    got = rejudge.route(pathlib.Path(board_dir), repo)
    if got["stopped"]:
        info = _stopped(entry.open_board(pathlib.Path(board_dir), allow_halted=True)) or {}
        return {"stop": True, "go": False, "why": str(info.get("reason") or got["why"])}
    return {"go": bool(got["next"])}


def refit_edge(board_dir, repo, gate) -> dict:
    """h-refit の固有の仕事（関所 replan-gate の後・2 回目の修正の段の前。依頼 226）: 関所の答え gate（開かなかったなら None）を
    replan.answer で当てる。stop（答えが盤面を止めた）なら {"stop": True}。そうでなければ go は戻った単位が在り p3.fix が盤面で
    待っているか、open_units は戻った単位だけの JSON の配列（1 回目に受け付けた単位を 2 回目の段の直す義務の並びに入れない——
    TDD の輪の頭が『直すな・not_done に書け』と並べ、受け付けがその行を拒むので）、plan_file は差し替えた承認済みの修正案、
    notes_file は修正の前の関所の条件（h-fix が書いた NOTES_FILE。2 回目の段にも効く）・人の一言・採った項目の事前審査の穴。
    ripple_file は refit_ripple_file（案の直しの 2 度目の include が出口で直した項目から作り直した一覧。作り直せなかった時だけ
    1 回目の案の物）。
    今の周の replan.json が無ければ go 偽"""
    board_dir = pathlib.Path(board_dir)
    fix_notes = entry.open_board(board_dir, allow_halted=True).work(NOTES_FILE)
    got = replan.answer(board_dir, repo, gate, fix_notes=str(fix_notes))
    if got["stop"]:
        return {"stop": True}
    b = entry.open_board(board_dir, allow_halted=True)
    return {"go": bool(got["returned"]) and GO_NODE["fix"] in b.ready(),
            "open_units": json.dumps(got["returned"], ensure_ascii=False),
            "plan_file": got["plan_file"], "notes_file": got["notes_file"], "why": got["why"], "ripple_file": refit_ripple_file(b)}


def eyes_edge(b) -> dict:
    """h-look の固有の仕事（最後のテストの後・最後の関所の前。計画 P1 Task 33）: go は独立の目（表の where が blk-eyes の役の節）が
    盤面で 1 つでも待っているか（p4.assemble が済み、条件に当たった目）。r4.human_gate が人に聞いたら、残りの目は答えるまで出ない——
    ブロックは止めずに asking で抜け、最後の関所の文に問いが載り、報告が needs_human と問いを次の run へ渡す（計画 Task 33 の (b)）。
    h-eyes（関所の後）も同じ go を返し、報告が「目を回すと言ったのに blk-eyes の出口が無い」を見分ける"""
    return {"go": bool(_role_ready(b, EYES_BLOCK))}


def plan_edge(b, board_dir, repo, *, run_id: str, adapter_mode: str, judged) -> dict:
    """h-plan の固有の仕事（edge の手順 5。計画 P1 Task 23・裁定 TA3・TA6）。包みの確かめはここに置かない（h-judge。P1-R9）。順:
    1. judged（判定のブロックの出口）を b.work(JUDGED_FILE) に控える（後ろの境の節が judgment_file・open_units を返す。M4）
    2. 盤面の p2.diagnose が今の周に済んでいなければ、judged の judgment_file を読んで entry.take(p2.diagnose)。出口が届かない・
       読めない・盤面が受けない（ok False）なら b.stop("盤面が判定を受けない: …", by=JUDGE_BRIDGE_BY) で stop。済んでいれば
       渡さない（Archon の再開・盤面で判定を受けた後も同じ）
    3. p2.fix_plan が ready なら go。p3.fix が ready で p2.fix_plan が na（直す物が無い周）なら、機械が空の返答
       （entry.empty_fix_reply）を渡して trace_empty_fix
    4. 修正案が無くても、独立設計を修正の前に作る周（design.due）なら go（最後の R2 の比較が設計を要る。blk-plan は設計の輪だけを回す）
    5. go なら判定の単位を構造のブロックの入力の契約に写し（structure_units）、structure_units_file で返す。判定のブロックが今の周に
       置いた単位の裏取りの申し送りが在れば verify_file で返す（修正案の役の指示書に貼る。線の木の段 3）"""
    if judged is not None:
        _write_json(b.work(JUDGED_FILE), judged)
    carried = _carried(b)
    if not _done_this_round(b, DIAGNOSE_NODE):
        reply, why = _judgment(judged)
        if not why:
            got = _hand(b, board_dir, DIAGNOSE_NODE, reply, repo)
            why = "" if got["ok"] else got["reason"]
        if why:
            reason = f"盤面が判定を受けない: {why}"
            entry.open_board(pathlib.Path(board_dir)).stop(reason, by=JUDGE_BRIDGE_BY)
            return {"stop": True, "go": False, "why": reason, **carried}
        b = entry.open_board(pathlib.Path(board_dir))
    ready = b.ready()
    if GO_NODE["plan"] not in ready:
        if GO_NODE["fix"] in ready and b.node_state("p2.fix_plan") == "na":
            got = _hand(b, board_dir, GO_NODE["fix"], entry.empty_fix_reply(), repo)
            if not got["ok"]:
                raise _gap(f"盤面が直す物の無い周の空の修正を受けない: {got['reason']}")
            trace_empty_fix(entry.open_board(pathlib.Path(board_dir)))
        b = entry.open_board(pathlib.Path(board_dir))
        if not design.due(b)[0]:
            return {"go": False, **carried}
    return {"go": True, **carried, "structure_units_file": structure_units(b, carried, repo), "verify_file": _verify_file(b)}


def edge(board_dir, at: str, repo, *, run_id: str, adapter_mode: str, judged: dict | None = None,
         gate: dict | None = None, tests: dict | None = None, premised: dict | None = None) -> dict:
    """境の節（計画 Task 10a。並びは C18 の順・計画 P1 Task 26）。返りは EMPTY の欄の全部（使わない欄は空の値。judgment_file・
    open_units はどの at でも h-plan の控え b.work(JUDGED_FILE) から）。盤面を開くのは 1 回（渡し替えの後は開き直す）。順:
    0. at rejudge は、盤面を開く前に replan.settle（案の直しを待つ行を諦めた行にする。止まった盤面でも。待つ行が残れば BoardGap）。
    1. 盤面を allow_halted で開く。もう止まっている（halted・state.stop）なら、止め札の理由は trace にだけ書いて stop（M3）。
       ただし at look・final・eyes は、1 周の run が周を締めた盤面（halted.by stop_after_round。最後のテストの後の普通の終わり）を
       止めたと読まない
    2. at fix の gate（policy-gate の出口。None は開かなかった）: approve・continue は b.answer("continue", 一言)、
       stop・reject は b.answer("stop", 一言 か GATE_STOP_NOTE)（盤面は halted.by == "answer"）。at refit の gate（replan-gate の
       出口）は refit_edge（replan.answer。stop・reject は盤面を止める——止めた盤面を _halted_out で返す）。最後の関所の答えの
       ファイル（FINAL_GATE_ANSWER）には書かない
    3. at eyes の gate（final-gate の出口）: どの答えも b.work(FINAL_GATE_ANSWER) に {decision, text} と human_items に 1 行。
       stop・reject は b.stop(一言 か FINAL_GATE_STOP_NOTE, by=FINAL_GATE_BY)——周を締めた盤面では b.stop が拒むので、
       trace に STOP_AFTER_END_OP の 1 行（by FINAL_GATE_BY）を書いて stop。守りのファイルの行（h-final が書いた）にも答えを写す。
       gate が null（関所が開かなかった）なら守りのファイルと食い違いを確かめ直し（_guard。h-final が飛ばされた run でも行を書く）、
       今の周の行が答えを待っていれば、止める（by PROTECTED_BY・stopby.CONFLICT）。at final・eyes の確かめ（_guard）が盤面を止めた
       （修正案の欄の控え plan-fields.json の食い違い。conflict.test_permits）なら、関所を開かず止め直さずに _halted_out
    4. 2・3 で止まったら止め札は trace にだけ（関所の答えが先）。止まっていなければ、止め札（seen）が在れば
       b.stop(理由, by="request:<札の by>")（周を締めた盤面では trace の 1 行）して stop
    5. entry: 盤面の ready から pr_go・premises_go・purpose_go・spec_go（go True）。spec: spec_edge（盤面の engine の節を回し直して pr_go）。judge: judge_edge。plan: plan_edge。
       gate: 盤面の問い（pending_human）が在れば ask と gate_text の文（b.work(GATE_FILE) にも）。
       fix: go は p3.fix が ready・notes は今の周の human_items の一言と、関所で答えた問いで直す義務に戻った単位の行
       （gatemarks.returned_lines。notes_file はそれを書いた b.work のファイル。空なら ""）・plan_file は今の周の p2.fix_plan の出力。
       go なら _capture_fixture（1 周目の盤面を固定材料に写す。写せなくても止めない）。
       mat: mat_edge（目的の文を盤面へ・mat_go）。look・eyes: eyes_edge（go は独立の目が待っているか。look は先に design.hand で
       修正の前に控えた独立設計を盤面へ渡す）。rejudge: rejudge_edge
       （go は再審の節が待っているか。判定役の会話を確かめられなければ止める）。replan: go は replan.material の go（案の直しを
       待つ行が在り、今の周の p3.fix をまだ受けていない）。regate: replan.gate の ask・gate_text・gate_file（今の周の replan.json が
       無ければ何もせず ask 偽）。refit: refit_edge（関所が開かなかった周も答え None で当てる）。
       ci: go は p4.ci が任せ先に落ちて待っている（entry.role_waits。start の ci_role_go と同じ口）。
       review・refix・tests: go は p3.delta_review・p3.delta_fix・p4.ci が ready。review は先に、固定材料から始めた盤面
       （fixture.adopted）なら包みの確かめ（_adapter_guard。通らなければ止める）。
       final: final_edge（始めの記録の最後の関所の開き方（gatepolicy.final_mode）と最後のテストの出口 tests と独立の目の判定から
       ask と文）。
    ready は DiskBoard.ready（書かない。開き直した盤面でも explicit の機械の節を落とさない）。
    配線の誤り（知らない at・場違いの入力・形の崩れ・知らない adapter・始めの記録の語の外の開き方）は BoardGap"""
    _check_args(at, judged=judged, gate=gate, tests=tests, premised=premised, adapter_mode=adapter_mode)
    if at == "rejudge":   # 修正の段を抜ける所: 止まっているかを見る前に、案の直しを待つ行を締める（止まった盤面でも）
        replan.settle(board_dir, repo)
    b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    out = {**EMPTY, **_carried(b)}
    flag = halt.seen(board_dir)
    if _stopped(b) and not (at in ENDED_AT and _ended(b)):
        return _halted_out(b, out, flag, at)
    refit = None
    if gate is not None:
        if at == "fix":
            _answer_policy_gate(b, gate)
            if _stopped(b):
                return _halted_out(b, out, flag, at)
        elif at == "refit":
            refit = refit_edge(board_dir, repo, gate)
            b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
            if refit.get("stop"):
                return _halted_out(b, out, flag, at)
        elif at == "eyes":
            stop, reason = _answer_final_gate(b, gate)
            if stop:
                _stop_board(b, at, reason, FINAL_GATE_BY)
                if flag:
                    b.trace(AFTER_HALT_OP, at=at, reason=flag["reason"], by=flag["by"])
                return {**out, "stop": True, "why": reason}
    if at == "eyes" and gate is None:
        _guard(b, repo)   # h-final が飛ばされた（独立の目のブロックが落ちた）run では行がまだ無い
        if _stopped(b) and not _ended(b):   # 確かめが盤面を止めた（修正案の欄の控えの食い違い）: 2 度止めず、その理由で止まる
            return _halted_out(b, out, flag, at)
        guarded = _protected_row(b)
        if guarded is not None and guarded.get("answer") is None:   # 守りのファイルを触ったのに最後の関所が開かなかった
            reason = f"{PROTECTED_HEAD}のに最後の関所の答えが無い（関所が開かなかった）——通すのは人の continue だけ: {guarded.get('note')}"
            _stop_board(b, at, reason, PROTECTED_BY)
            return {**out, "stop": True, "why": reason}
        asked = _row(b, stopby.CONFLICT)
        if asked is not None and asked.get("answer") is None:   # 食い違いの申し出が人に回ったのに最後の関所が開かなかった
            reason = f"{conflict.HEAD}が人に回ったのに最後の関所の答えが無い（関所が開かなかった）: {asked.get('note')}"
            _stop_board(b, at, reason, stopby.CONFLICT)
            return {**out, "stop": True, "why": reason}
    if flag:
        b.trace(FLAG_SEEN_OP, at=at, reason=flag["reason"], by=flag["by"])
        _stop_board(b, at, flag["reason"], FLAG_BY_PREFIX + flag["by"])
        return {**out, "stop": True, "why": flag["reason"]}
    if at == "entry":
        return {**out, **entry_edge(b)}
    if at == "spec":
        return {**out, **spec_edge(b)}
    if at == "judge":
        return {**out, **judge_edge(b, board_dir, repo, run_id=run_id, adapter_mode=adapter_mode, premised=premised)}
    if at == "plan":
        return {**out, **plan_edge(b, board_dir, repo, run_id=run_id, adapter_mode=adapter_mode, judged=judged)}
    if at == "gate":
        asking = b.state.get("pending_human")
        if not asking:
            return out
        text = gate_text(asking, run_id=run_id)
        _write_text(b.work(GATE_FILE), text)
        return {**out, "ask": True, "gate_text": text, "gate_file": str(b.work(GATE_FILE))}
    if at == "fix":
        notes = "\n".join(x for x in (_notes(b), *gatemarks.returned_lines(b)) if x)
        notes_file = ""
        if notes:
            _write_text(b.work(NOTES_FILE), notes)
            notes_file = str(b.work(NOTES_FILE))
        go = GO_NODE["fix"] in b.ready()
        if go:
            _capture_fixture(b, board_dir, repo, run_id)
        return {**out, "go": go, "notes": notes, "notes_file": notes_file, "plan_file": _out_file(b, "p2.fix_plan"),
                "ripple_file": _ripple_file(b)}
    if at == "replan":
        return {**out, "go": replan.material(b)["go"]}
    if at == "regate":
        return {**out, **replan.gate(b, run_id=run_id)}
    if at == "refit":
        return {**out, **(refit if refit is not None else refit_edge(board_dir, repo, None))}
    if at == "rejudge":
        return {**out, **rejudge_edge(board_dir, repo)}
    if at == "mat":
        return {**out, **mat_edge(b, board_dir, repo)}
    if at == "look":
        design.hand(b, pathlib.Path(board_dir), repo)   # 渡せなければ（設計が無い）目のブロックの出口が理由を言う
        b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
    if at in ("look", "eyes"):
        return {**out, **eyes_edge(b)}
    if at == "ci":
        return {**out, "go": entry.role_waits(b, GO_NODE["tests"])}
    if at == "review" and fixture.adopted(board_dir) is not None:   # 固定材料の盤面で役が起きた後の境の節（h-judge は回した）
        stopped = _adapter_guard(b, board_dir, repo, run_id=run_id, adapter_mode=adapter_mode)
        if stopped:
            return {**out, **stopped}
    if at == "final":
        try:
            mode = gatepolicy.final_mode(b.dir)
        except ValueError as e:
            raise _gap(str(e)) from None
        got = final_edge(b, repo, run_id=run_id, mode=mode, tests=tests)
        if _stopped(b) and not _ended(b):   # final_edge の確かめ（_guard）が盤面を止めた: 関所を開かず、その理由で止まる
            return _halted_out(b, out, flag, at)
        return {**out, **got}
    return {**out, "go": GO_NODE[at] in b.ready()}
