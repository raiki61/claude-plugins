# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""修正役の並べの枝を切るか（blk-fix の節 fix-fork。TDD の輪の後・修正の輪の前。中身は fixlanes.fork。
設計 docs/plans/2026-10-07-fix-lane-nodes.md）。

読む環境変数: ARTIFACTS_DIR（盤面はその下の board/）と run の値 INPUTS_JUDGMENT_FILE・INPUTS_OPEN_UNITS・INPUTS_PLAN_FILE・
INPUTS_POLICY_PATH・INPUTS_NOTES_FILE・INPUTS_SUMMARY_FILE（輪の要約。空でよい）・INPUTS_BASE_REV・INPUTS_PLAN_SESSION（範囲の相談の
相手。空は相談しない）・INPUTS_RIPPLE_FILE（波及の一覧。空でよい）・INPUTS_FIX_LANES（修正役の並べを使うか。on・off、空は on）。
既定の形 g3 で、修正役が下請けを起こす単位（TDD の輪が緑にした単位を除く）を持つ範囲の在る修正案の項目が、単位を共にしない 2 本以上の
枝に分かれれば、単位の worktree を切って枝の控え・項目の決まりのファイルを書き {"go": true, "lanes", "lane_<n>": true…, "why": ""}、
ほかは go: false と理由を 1 行出して 0。どちらでも、前に切った枝の締めの結末（fix-lanes-out.json・fix-lanes.md）は消す。枝の輪 fix-lane-loop-<n> は lane_<n> を、締めの節 fix-join は go を when: で読む。
入力 fix_lanes の知らない語・環境変数の欠け・git が効かない・思わぬ誤り: 標準エラーに 1 行出して 2（rolekit.script_main）。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックのモジュール（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import fixlanes  # noqa: E402
import rolekit  # noqa: E402
import tddloop  # noqa: E402  （輪が緑にした単位。枝に入れない）

# 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_fix_lane_wiring.py が見る）
INPUTS = ("INPUTS_JUDGMENT_FILE", "INPUTS_OPEN_UNITS", "INPUTS_PLAN_FILE", "INPUTS_POLICY_PATH", "INPUTS_NOTES_FILE",
          "INPUTS_SUMMARY_FILE", "INPUTS_BASE_REV", "INPUTS_PLAN_SESSION", "INPUTS_RIPPLE_FILE", "INPUTS_FIX_LANES")
VALUES = INPUTS[:-1]   # 指示書に埋める run の値（fix_lanes は切り替えの語）


def run(board, repo, env):
    values = {n[len("INPUTS_"):].lower(): env[n] for n in VALUES}
    summary = values["summary_file"]
    values["tdd_state"] = str(Path(summary).parent / tddloop.STATE) if summary else ""   # 枝の確かめが凍結と試験を見る輪の状態
    return fixlanes.fork(board, repo, values, tddloop.green_units(summary), env["INPUTS_FIX_LANES"])


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
