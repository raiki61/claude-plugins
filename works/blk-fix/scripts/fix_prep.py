# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役の指示書（blk-fix の節 fix-prep。修正の輪の中で役 fix の前。中身は fixrules.prep）。

読む環境変数: ARTIFACTS_DIR（盤面はその下の board/）と run の値 INPUTS_JUDGMENT_FILE・INPUTS_OPEN_UNITS・INPUTS_PLAN_FILE・
INPUTS_POLICY_PATH・INPUTS_NOTES_FILE・INPUTS_SUMMARY_FILE（空でよい）・INPUTS_BASE_REV（空でよい。修正の形 g1 の審査役の
型の版）と INPUTS_PASS（first か、裁定の後の 2 回目の ruled）と INPUTS_PASS_TAG（回の印。無い・空は 1 回目の修正の段。依頼 226 の
2 回目の段は refit で、指示書と数えと座の作業ファイルを分ける）。
修正の決まりの正本・直す役の決まり・run の値を組み、
盤面の今の周の prompt-p3_fix.md（full の写し）と隣の 2 つの形に書き、起こした印を置いて
{prompt_file, attempt, out_path, node, already, variants_file} を 1 行出して 0。役はそのパスを Read する。
出し直しなら前の回の拒否の理由のファイルを指示書の頭で名指す（R44）。cwd（対象の worktree）の差分から変更の種類を選ぶ。
環境変数の欠け・盤面が p3.fix を待っていない・思わぬ誤り: 標準エラーに 1 行出して 2（rolekit.script_main）。
brief の控え（briefs.json）か修正案の欄の控え（plan-fields.json）が壊れている・凍結の印と食い違えば、盤面を止めて 2。
修正の形 g3・g1 の盤面で、借りた superpowers の写しが固定（pin）と違う・型の穴が埋まらなければ、座の無い指示書に逃げずに 2。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import fixrules  # noqa: E402
import rolekit  # noqa: E402

# 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_fix.py が見る）
INPUTS = ("INPUTS_JUDGMENT_FILE", "INPUTS_OPEN_UNITS", "INPUTS_PLAN_FILE", "INPUTS_POLICY_PATH", "INPUTS_NOTES_FILE",
          "INPUTS_SUMMARY_FILE", "INPUTS_BASE_REV", "INPUTS_PASS", "INPUTS_PASS_TAG")
# 無くても欠けに数えない入力（依頼 226 で後から足した回の印と include の名。前の版の with: で再開した run は渡さない。無い・空は今どおり）
OPTIONAL = frozenset({"INPUTS_PASS_TAG"})
VALUES = tuple(n for n in INPUTS if n not in OPTIONAL and n != "INPUTS_PASS")   # 指示書に埋める run の値


def run(board, repo, env):
    values = {n[len("INPUTS_"):].lower(): env[n] for n in VALUES}
    return fixrules.prep(board, repo, values, env["INPUTS_PASS"])


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, tuple(n for n in INPUTS if n not in OPTIONAL)))
