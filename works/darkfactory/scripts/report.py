# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ラインの最後にいつも走る報告の節（P1 計画 Task 27・〔線A計〕T15。裁定 TA16）。中身は report.build（.shared/core/report.py）。
1 本目の finish の欄を保ったまま、機械が組む短い報告 report.md と、次の run に渡す依頼の下書き next-request.json を盤面に書く。

読む環境変数（Archon が節の with: から JSON の文字列で渡す。どれも在ること。文字列 null と空は None＝その節は走らなかった）:
- INPUTS_JUDGED: 判定のブロックの出口（{ok, open_units, need_fix, judgment_file, one_shot}）
- INPUTS_TESTS:  最後のテスト（blk-tests の final）の出口（{ok, green, log, …}）
- INPUTS_START:  start の出口（無ければ盤面の r1 の start の控え）
- INPUTS_CI:     CI の任せ先の役のブロック（blk-ci）の collect の出口（{ok, reason, note, …}。包み無しの知らせ）
- INPUTS_EYES:   最後の境の節 h-eyes の出口（{go, …}）
- INPUTS_EYEING: 独立の目のブロック（blk-eyes）の出口
- INPUTS_CLEANED_RUNS: use.sh start が起動の前に片付けた前の run（「<id>（<状態>）」を・で並べた文字列。JSON でない）。冒頭 2 に
  1 行で出す。無いのは空と同じ（後から足した入力。前の版の with: で再開した run は渡さない）
- INPUTS_DEPTH: 深さの節 h-redepth の出口（{depth, skip, lines, …}。計画 2026-10-06-variable-depth）。lines を冒頭 2 に並べる。
  無い・null は出さない（後から足した入力。前の版の with: で再開した run は渡さない）
- INPUTS_FIX_TDD・INPUTS_REFIT_TDD: 1 回目と 2 回目の修正の段の TDD の輪の結末（修正のブロックの出口 tdd。{ran, suite, reason, units, …}）。
  単位ごとの結末を報告の節に並べる（keep-essence の 11）。飛ばされた段・無い・null は出さない（後から足した入力。前の版の with: で
  再開した run は渡さない）
- ARTIFACTS_DIR（空も欠け。盤面は その下の board/）・WORKFLOW_ID（Archon の出来事を読む run。空なら start の控えの run_id）
途中で終わった run（上流の節が落ちても報告の節は all_done で走る）: Archon の出来事で最後の状態が落ちた節か、出口の印の欠け
（h-eyes の出口が無い・h-eyes が目を回すと言ったのに blk-eyes の出口が無い）が在れば、結末 interrupted の報告を組み、冒頭 3 に
落ちた節を出す（出来事だけに頼らない: 出来事が取れない run でも出口の印で分かる）。ただし線の YAML が description の末尾の
[optional] で受け止めると宣言した段（地図の元の節の欄 optional。その中の節を含む）の落ちは、出口の印が揃った run では途中で
終わった数えにせず、受け止めた落ちとして冒頭 3 に ABSORBED_HEAD の行で出す（その段は確かめていないので残りにも節ごと 1 行数え、
結末は fixed にならない）。出口の印が欠けた run と、
地図の元が古い・読めない run は落ちた節を全部中断に数える（後者は標準エラーに理由を 1 行出す）。report より下流の節
（AFTER_REPORT）の失敗は前の試みの物なので数えない。resume で前の試みで落ちた節が後で済んだ run は途中で終わった run でなく、
その節を冒頭 3 に試みの記録として出す
出口:
- report.build の結果を 1 行の JSON で出して 0（record_invalid・止めた run・途中で終わった run も 0。結末で知らせる）
- 盤面が開けない（BoardGap・写しの Reject）: 標準エラーに理由を 1 行出して 1。標準出力には何も出さない
- 環境変数が欠けた・JSON が読めない・オブジェクトでない・思わぬ誤り: 標準エラーに 1 行出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import script_io  # noqa: E402

# 裁定 TA16: 読む INPUTS_* の組（YAML の with: の鍵と突き合わせる）
INPUTS = ("INPUTS_JUDGED", "INPUTS_TESTS", "INPUTS_START", "INPUTS_CI", "INPUTS_EYES", "INPUTS_EYEING",
          "INPUTS_CLEANED_RUNS", "INPUTS_DEPTH", "INPUTS_FIX_TDD", "INPUTS_REFIT_TDD")
CLEANED_RUNS = "INPUTS_CLEANED_RUNS"   # 文字列の入力（ほかは JSON）。無くても欠けに数えない
DEPTH = "INPUTS_DEPTH"                 # 後から足した JSON の入力。無くても欠けに数えない
TDD = ("INPUTS_FIX_TDD", "INPUTS_REFIT_TDD")   # 後から足した JSON の入力（修正の段の順。report.TDD_STAGES と同じ並び）。無くても欠けに数えない
LATE = (CLEANED_RUNS, DEPTH, *TDD)
NULL = "null"   # 飛ばされた節の出力（if_skipped: null）が届く字
RUN_ID_ENV = "WORKFLOW_ID"
# darkfactory.yaml で report に依る節（reporting: [report]・result: [report, reporting]）。この節が走る時には今の試みで
# まだ走れないので、出来事の上の最後の状態は前の試み（resume の前）の物
AFTER_REPORT = ("reporting", "result")


class Broken(Exception):
    pass


def _line(text) -> str:
    return " ".join(str(text).split())


def _json_or_none(name: str):
    raw = os.environ[name].strip()
    if raw in ("", NULL):
        return None
    try:
        doc = json.loads(raw)
    except json.JSONDecodeError as e:
        raise Broken(f"{name} が JSON として読めない: {e}（頭: {raw[:200]!r}）") from None
    if not isinstance(doc, dict):
        raise Broken(f"{name} が JSON のオブジェクトでない（{type(doc).__name__}）")
    return doc


def unreached(eyes, eyeing) -> list:
    """出口の印の欠けを落ちた節の形 [{node, error}] で（出来事に依らない。無ければ []）"""
    if eyes is None:
        return [{"node": "h-eyes", "error": "最後の境の節の出口が届いていない（その前のどこかの節が落ちた）"}]
    if eyes.get("go") is True and eyeing is None:
        return [{"node": "eyeing", "error": "独立の目のブロックの出口が届いていない（ブロックの中の節が落ちた）"}]
    return []


def split_failed(events, graph, reached: bool):
    """落ちた節を (中断の落ち, 受け止めた落ち) に分ける（どちらも [{node, error}]）。分け方は最後の関所と同じ口
    （report.split_fallen。線の YAML が [optional] と宣言した段の落ちで、出口の印が揃った run だけ受け止める）"""
    import report
    return report.split_fallen(events, graph, reached, AFTER_REPORT)


def main() -> int:
    missing = [n for n in INPUTS if n not in os.environ and n not in LATE]
    if not os.environ.get(script_io.ARTIFACTS_ENV):
        missing.append(script_io.ARTIFACTS_ENV)
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    try:
        judged, tests, start, ci, eyes, eyeing = (_json_or_none(n) for n in INPUTS if n not in LATE)
        depth = _json_or_none(DEPTH) if DEPTH in os.environ else None
        tdd = [_json_or_none(n) if n in os.environ else None for n in TDD]
    except Broken as e:
        print(f"report: {_line(e)}", file=sys.stderr)
        return 2
    import reads
    import report
    from board import BoardGap
    from engine.util import Reject
    board = Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR
    run_id = os.environ.get(RUN_ID_ENV, "")
    try:
        if not (board / "state.json").is_file():
            raise BoardGap(f"盤面 {board} が無い（start の前に落ちた run か、works の run でない）")
        events = reads.events_for(run_id)
        lost = unreached(eyes, eyeing)
        graph = None
        if not lost and reads.failed_nodes(events, after=AFTER_REPORT):   # 落ちが無ければ受け止めを判じる要が無い
            try:
                graph = report.line_graph(Path(__file__).resolve().parents[2], AFTER_REPORT)   # 報告より下流の節を持つ線の地図の元
            except ValueError as e:
                print(f"report: 落ちた節の受け止めを判じなかった（全部中断に数える）: {_line(e)}", file=sys.stderr)
        failed, absorbed = split_failed(events, graph, not lost)
        failed = failed or lost
        out = report.build(board.resolve(), judged=judged, tests=tests, start=start, ci=ci, run_id=run_id,
                           events=events, interrupted="" if failed else None, failed=failed, absorbed=absorbed,
                           retried=reads.retried_nodes(events, after=AFTER_REPORT), eyeing=eyeing,
                           cleaned_runs=" ".join(os.environ.get(CLEANED_RUNS, "").split()),
                           depth_lines=(depth or {}).get("lines") or (), tdd=tdd)
    except (BoardGap, Reject) as e:
        print(f"報告を組めない（{type(e).__name__}）: {_line(e)}", file=sys.stderr)
        return 1
    except Exception as e:   # 思わぬ誤りも 1 行と 2（traceback を出さない）
        print(f"report の内部の誤り: {type(e).__name__}: {_line(e)}", file=sys.stderr)
        return 2
    script_io._emit(out)
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
