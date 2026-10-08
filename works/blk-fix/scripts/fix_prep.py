# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役の指示書（blk-fix の節 fix-prep。修正の輪の中で役 fix の前。中身は fixrules.prep）。

読む環境変数: ARTIFACTS_DIR（盤面はその下の board/）と run の値 INPUTS_JUDGMENT_FILE・INPUTS_OPEN_UNITS・INPUTS_PLAN_FILE・
INPUTS_POLICY_PATH・INPUTS_NOTES_FILE・INPUTS_SUMMARY_FILE（空でよい）・INPUTS_BASE_REV（空でよい。修正の形 g1 の審査役の
型の版）・INPUTS_PLAN_SESSION（範囲の相談の相手の会話の印の名。空は相談しない）・INPUTS_RIPPLE_FILE（波及の一覧。空でよい）と
INPUTS_PASS（first か、裁定の後の 2 回目の ruled）。修正役の並べ（入力 fix_lanes）は修正の輪の前の節 fix-fork が持つ。2 回目の修正の段（依頼 226。ブロックの 2 度目の include）の指示書と
数えと座の作業ファイルは、その include の名の置き場（scope）で 1 回目と分かれる。
修正の決まりの正本・直す役の決まり・run の値を組み、
盤面の今の周の prompt-p3_fix.md に書き、起こした印を置いて
{prompt_file, attempt, out_path, node, already, iteration} を 1 行出して 0。役はそのパスを Read する。
出し直しなら前の回の拒否の理由のファイルを指示書の頭で名指す（R44）。cwd（対象の worktree）の差分から変更の種類を選ぶ。
環境変数の欠け・盤面が p3.fix を待っていない・思わぬ誤り: 標準エラーに 1 行出して 2（rolekit.script_main）。
brief の控え（briefs.json）か修正案の欄の控え（plan-fields.json）が壊れている・凍結の印と食い違えば、盤面を止めて 2。
輪の要約（INPUTS_SUMMARY_FILE）の隣の状態から輪が緑にした単位を引き、g3 の修正役の下請けから外す（依頼 243 の 2）。修正役の並べの
枝が直して当てた単位も外す（fixrules.lanes_merged。盤面の作業ファイルの枝の結末）。
修正の形 g3・g1 の盤面で、借りた superpowers の写しが固定（pin）と違う・型の穴が埋まらなければ、座の無い指示書に逃げずに 2。
"""
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import fixrules  # noqa: E402
import tddloop  # noqa: E402  （輪が緑にした単位。g3 の修正役はその単位に下請けを起こさない）
import rolekit  # noqa: E402

# 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_fix.py が見る）
INPUTS = ("INPUTS_JUDGMENT_FILE", "INPUTS_OPEN_UNITS", "INPUTS_PLAN_FILE", "INPUTS_POLICY_PATH", "INPUTS_NOTES_FILE",
          "INPUTS_SUMMARY_FILE", "INPUTS_BASE_REV", "INPUTS_PLAN_SESSION", "INPUTS_RIPPLE_FILE", "INPUTS_PASS")
# 無くても欠けに数えない入力（後から足した範囲の相談の相手と波及の一覧。前の版の with: で再開した run は渡さない。無い・空は使わない）
OPTIONAL = frozenset({"INPUTS_PLAN_SESSION", "INPUTS_RIPPLE_FILE"})
VALUES = tuple(n for n in INPUTS if n != "INPUTS_PASS" and n not in OPTIONAL)   # 指示書に埋める run の値


def run(board, repo, env):
    values = {n[len("INPUTS_"):].lower(): env[n] for n in VALUES}
    values["plan_session"] = os.environ.get("INPUTS_PLAN_SESSION", "")
    values["ripple_file"] = os.environ.get("INPUTS_RIPPLE_FILE", "")
    summary = values["summary_file"]
    values["tdd_state"] = str(Path(summary).parent / tddloop.STATE) if summary else ""   # 事前の確かめが凍結を見る輪の状態
    return fixrules.prep(board, repo, values, env["INPUTS_PASS"], green=tddloop.green_units(values["summary_file"]))


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, tuple(n for n in INPUTS if n not in OPTIONAL)))
