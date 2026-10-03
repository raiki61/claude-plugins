# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正のブロックの出口を集める（blk-fix の節 collect。returns の節）。

読む環境変数:
- INPUTS_ACCEPTED: 輪（fix-loop）の出力 = 最後の周の fix-accept の出力（{ok, reason, changes, …} の JSON の文字列）
- INPUTS_RULED: 2 回目の修正の輪（fix-ruled-loop。食い違いの裁定の後）の出力。飛ばされれば文字列 null（在れば ACCEPTED の代わり）
- INPUTS_CHANGED: assert-changed の出力（{ok, files} の JSON の文字列）
- INPUTS_CLEANED: clean の出力（{ok, count, file} の JSON の文字列。修正役が残した git が無視するファイルのうち消した物の
  件数と、全件を書いた盤面のファイル。出口の removed に {count, file} でそのまま通し、ファイルは開かない）
- INPUTS_TDD: tdd-start の出力（{go, reason, suite, state_file, summary_file} の JSON の文字列。いつも走る節）
- INPUTS_PASS_TAG: 回の印（依頼 226 の 2 回目の修正の段は refit。無い・空は 1 回目）。reads_file はその回の読んだ証拠
- ARTIFACTS_DIR: 盤面はその下の board/
中身は recount.collect: 受け付けた changes を今の周の changes.json（{"changes": [...]}）に書き、1 本目の欄
{"ok": true, "files", "changes_file", "removed"} に、盤面から fix_file・not_done・coverage・reads_file を、TDD の輪から tdd
（tddloop.exit_fields。実行器の無い run は ran: false）を足して 1 行出して 0。
修正の段が諦めた（受け付けか assert-changed の出力が ok: false で、盤面が止まっている——止めるのは assert-changed。R50）ときは、
1 本目の欄を持つ {"ok": false, "files": [], "changes_file": "", "removed", "tdd", "reason": 盤面が止まった理由} を出して 0。
受け付けが通っていないのに盤面が止まっていない・入力が読めない・盤面が今の周の p3.fix を受けていないときは、標準エラーに理由を
1 行出して 2（何も書かない）。
"""
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import entry  # noqa: E402
import recount  # noqa: E402
import script_io  # noqa: E402
import tddloop  # noqa: E402
from board import BoardGap  # noqa: E402  （BoardMismatch も含む）

INPUTS = ("INPUTS_ACCEPTED", "INPUTS_CHANGED", "INPUTS_CLEANED", "INPUTS_TDD", "INPUTS_RULED",   # RULED は飛ばされれば null
          "INPUTS_PASS_TAG")
# 無くても欠けに数えない入力（依頼 226 で後から足した回の印。前の版の with: で再開した run は渡さない。無い・空は 1 回目）
OPTIONAL = frozenset({"INPUTS_PASS_TAG"})


def env_json(name, raw=None):
    raw = os.environ.get(name) if raw is None else raw
    if raw is None:
        raise recount.Unreadable(f"環境変数が無い: {name}")
    try:
        v = json.loads(raw)
    except json.JSONDecodeError as e:
        raise recount.Unreadable(f"{name} が JSON として読めない: {e}（頭: {raw[:200]!r}）")
    if not isinstance(v, dict):
        raise recount.Unreadable(f"{name} が JSON のオブジェクトでない（{type(v).__name__}）")
    return v


def collect():
    first = os.environ.get(INPUTS[0])   # 2 回目の修正の輪（食い違いの裁定の後）が走っていれば、その受け付けの出力
    accepted = env_json(INPUTS[0], None if first is None else script_io.later_output(first, os.environ.get(INPUTS[4])))
    changed, cleaned, tdd = (env_json(n) for n in INPUTS[1:4])
    artifacts = os.environ.get("ARTIFACTS_DIR")
    if not artifacts:
        raise recount.Unreadable("環境変数が無い: ARTIFACTS_DIR")
    count, file = cleaned.get("count"), cleaned.get("file")
    if cleaned.get("ok") is not True or type(count) is not int or count < 0 or not isinstance(file, str):
        raise recount.Unreadable(f"clean の出力に count・file が無い（{cleaned!r}）")
    removed = {"count": count, "file": file}
    board = pathlib.Path(artifacts) / "board"
    if accepted.get("ok") is not True or changed.get("ok") is not True:
        st = entry.open_board(board, allow_halted=True).state
        stop = st.get("stop") or st.get("halted")
        if stop:   # 修正の段が諦めた（assert-changed が止めた）。後ろの段は境の節が飛ばし、報告が走る
            return {"ok": False, "files": [], "changes_file": "", "removed": removed, "tdd": tddloop.exit_fields(tdd),
                    "reason": f"盤面は止まっている（{stop.get('by')}）: {stop.get('reason') or ''}"}
    out = recount.collect(board, accepted, changed, tag=os.environ.get("INPUTS_PASS_TAG", ""))
    return {**out, "removed": removed, "tdd": tddloop.exit_fields(tdd)}


def main():
    try:
        out = collect()
    except (recount.Unreadable, BoardGap, tddloop.Broken) as e:
        print(f"collect: {e}".replace("\n", " "), file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
