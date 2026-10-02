# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""TDD の輪の指示書（blk-fix の節 tdd-prep。輪の中で役 tdd の前。中身は tddloop.prep → fixrules）。

読む環境変数: INPUTS_STATE_FILE（tdd-start の state_file）と run の値 INPUTS_JUDGMENT_FILE・INPUTS_PLAN_FILE・INPUTS_POLICY_PATH・
INPUTS_NOTES_FILE（空でよい）。修正の決まりの正本・TDD の決まり・今の段・前の回に拒んだ理由・run の値を組み、状態の置き場の
next.md（full の写し）と隣の 2 つの形に書き、{"prompt_file"} を 1 行出して 0。役はそのパスを Read する（理由の本文を
$LOOP_PREV で貼らない。R44）。cwd（対象の worktree）の差分から変更の種類を選ぶ。
環境変数が欠けた・状態が読めない・輪が済んでいる: 標準エラーに 1 行出して 2。
brief の控え（briefs.json）か修正案の欄の控え（plan-fields.json）が壊れている・凍結の印と食い違えば、盤面を止めて 2。
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import json  # noqa: E402
import os  # noqa: E402

import tddloop  # noqa: E402

INPUTS = ("INPUTS_STATE_FILE", "INPUTS_JUDGMENT_FILE", "INPUTS_PLAN_FILE", "INPUTS_POLICY_PATH", "INPUTS_NOTES_FILE")


def main() -> int:
    lack = [n for n in INPUTS if n not in os.environ] + ([] if os.environ.get(INPUTS[0]) else [INPUTS[0]])
    if lack:
        print(f"tdd-prep: 環境変数が無い・空: {', '.join(dict.fromkeys(lack))}", file=sys.stderr)
        return 2
    values = {n[len("INPUTS_"):].lower(): os.environ[n] for n in INPUTS[1:]}
    try:
        out = tddloop.prep(os.environ[INPUTS[0]], values, Path.cwd())
    except (tddloop.Broken, OSError) as e:
        print(f"tdd-prep: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
