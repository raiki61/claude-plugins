# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""ラインの入口の節 start（線 A の仕様 4 節。計画 Task 7）。中身は entry.start（.shared/core/entry.py）。

読む環境変数（Archon が節の with: から渡す。どれも在ること。値の空は既定の意味）:
- INPUTS_REQUEST（依頼のファイル。相対なら cwd＝対象の根から）・INPUTS_TEST_CMD・INPUTS_THICKNESS・INPUTS_GATES・
  INPUTS_FINAL_GATE・INPUTS_ADAPTER・INPUTS_POLICY_MD（INPUTS_LANG・INPUTS_BASE・INPUTS_PR・INPUTS_GITHUB_READS・INPUTS_UNATTENDED・
  INPUTS_DESIGN_ONLY・INPUTS_FIX_FIXTURE・INPUTS_FEATURES_OFF・INPUTS_FEATURES_ON は無くてよい。
  LANG は報告の言語で、無いのは空＝依頼文の言語。BASE・PR は変更の入口で、無いのは空＝名指さない。GITHUB_READS は殻が隔離の
  前に読んだ PR・issue のファイルで、無いのは空＝読んだ物が無い。FIX_FIXTURE は固定材料のフォルダで、
  無いのは空＝盤面を新しく作る。FEATURES_OFF・FEATURES_ON は切る機能・入れる機能の語で、無いのは空＝既定（entry.FEATURE_DEFAULTS））
- ARTIFACTS_DIR（空も欠け。盤面は その下の board/）・WORKFLOW_ID（切符の run_id。空も欠け）
版の控え: 入力を確かめる前（拒む run でも）に <ARTIFACTS_DIR>/versions.json を書く（versions.snapshot。盤面の外）。
設定の写し settings に切る機能・入れる機能 {features_off: [語], features_on: [語]}（入力の語を区切って重ねずに並べた物。知らない語も
字のまま。確かめは start）を載せる。
書けなくても run は止めず、標準エラーに 1 行出す
出口:
- 通れば entry.start の結果を 1 行の JSON で出して 0
- 入力を受けない（entry.InputRefused。CI・並行 PR の engine の拒みも含む）: 標準エラーに理由を 1 行出して 1
  （AI を起こす前に run を止める。1 本目の intake と同じ）。標準出力には何も出さない
- 環境変数が欠けた・盤面の誤り（BoardGap・Reject。任せ先の素材を受け付けが拒んだ AnswerReject も）・思わぬ誤り:
  標準エラーに 1 行出して 2
- 止められた（tree_run.Stopped。テストのコマンドは木ごと止めた）: 128+信号
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import os  # noqa: E402
import re  # noqa: E402

import script_io  # noqa: E402

# 裁定 TA16: 読む INPUTS_* の組と raw の鍵（Task 17 の試験が YAML の with: の鍵と突き合わせる）
INPUTS = {"INPUTS_REQUEST": "request", "INPUTS_BASE": "base", "INPUTS_PR": "pr", "INPUTS_GITHUB_READS": "github_reads",
          "INPUTS_TEST_CMD": "test_cmd", "INPUTS_THICKNESS": "thickness", "INPUTS_GATES": "gates",
          "INPUTS_FINAL_GATE": "final_gate", "INPUTS_ADAPTER": "adapter", "INPUTS_POLICY_MD": "policy_md", "INPUTS_LANG": "lang",
          "INPUTS_UNATTENDED": "unattended", "INPUTS_DESIGN_ONLY": "design_only",
          "INPUTS_FIX_FIXTURE": "fix_fixture", "INPUTS_FEATURES_OFF": "features_off", "INPUTS_FEATURES_ON": "features_on"}
# 無くても欠けに数えない入力（後から足した入力。前の版の with: で再開した run は渡さない。無いのは空と同じ）
OPTIONAL = frozenset({"INPUTS_LANG", "INPUTS_BASE", "INPUTS_PR", "INPUTS_GITHUB_READS", "INPUTS_UNATTENDED",
                      "INPUTS_DESIGN_ONLY", "INPUTS_FIX_FIXTURE", "INPUTS_FEATURES_OFF",
                      "INPUTS_FEATURES_ON"})
RUN_ID_ENV = "WORKFLOW_ID"
NON_EMPTY = (script_io.ARTIFACTS_ENV, RUN_ID_ENV)


def _line(text) -> str:
    return " ".join(str(text).split())


def _settings() -> dict:
    """版の控えの settings（入力を確かめる前に書くので、entry を引かずに区切るだけ。区切りは entry.features_off と同じ）"""
    return {key: sorted({w for w in re.split(r"[\s,、・]+", os.environ.get(env, "")) if w})
            for key, env in (("features_off", "INPUTS_FEATURES_OFF"), ("features_on", "INPUTS_FEATURES_ON"))}


def main() -> int:
    missing = [n for n in (*INPUTS, *NON_EMPTY) if n not in os.environ and n not in OPTIONAL]
    missing += [n for n in NON_EMPTY if n in os.environ and not os.environ[n]]
    if missing:
        print(f"環境変数が無い: {', '.join(missing)}", file=sys.stderr)
        return 2
    import versions
    try:
        versions.write(Path(os.environ[script_io.ARTIFACTS_ENV]),
                       versions.snapshot(Path(__file__).resolve().parents[2], run_id=os.environ[RUN_ID_ENV],
                                         settings=_settings()))
    except OSError as e:   # 版の控えは run を止めない（止めずに 1 行で知らせる）
        print(f"版の控え {versions.FILE} を書けない: {type(e).__name__}: {_line(e)}", file=sys.stderr)
    import entry
    import tree_run
    from board import BoardGap
    from engine.util import Reject
    raw = {key: os.environ.get(name, "") for name, key in INPUTS.items()}
    board = Path(os.environ[script_io.ARTIFACTS_ENV]) / script_io.BOARD_DIR
    try:
        out = entry.start(board, Path.cwd(), raw, run_id=os.environ[RUN_ID_ENV])
    except entry.InputRefused as e:
        print(f"run を始めない: {_line(e)}", file=sys.stderr)
        return 1
    except (BoardGap, Reject) as e:
        print(f"盤面の誤り: {_line(e)}", file=sys.stderr)
        return 2
    except tree_run.Stopped as e:
        print(f"止められた（信号 {e.signum}）。テストのコマンドは木ごと止めた", file=sys.stderr)
        return 128 + e.signum
    except Exception as e:   # 思わぬ誤りも 1 行と 2（入力の拒みの 1 と混ぜない。traceback を出さない）
        print(f"start の内部の誤り: {type(e).__name__}: {_line(e)}", file=sys.stderr)
        return 2
    script_io._emit(out)
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
