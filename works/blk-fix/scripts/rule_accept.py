# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""裁定役の返答の受け付け（blk-fix の節 rule-accept。中身は ruling.accept_rule を script_io.main が回す）。

読む環境変数: INPUTS_REPLY（役 rule の返答）・INPUTS_BASE_REV（受けるだけ）・INPUTS_ITERATION（rule-prep の iteration）・ARTIFACTS_DIR・
INPUTS_PASS_TAG（回の印。無い・空は 1 回目の修正の段。裁定の文と拒否の理由のファイルの名を分ける）。
通れば裁定を盤面の控えと trace に積み、{ok: true, done: true, rulings_file, counts} を 1 行出して 0。拒めば理由の本文を盤面の
reject-accept_rule-<連番>.txt（回の印が在れば reject-accept_rule-<連番>.<印>.txt）に書き（reason_file。R44）、3 回目の拒否では裁かれていない申し出を人へ回して done（R50）。
回す側の誤り（盤面が開けない・作業ツリーの控えが無い・思わぬ誤り）は標準エラーに 1 行出して 2。
"""
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックの模块（lib/ は Archon が探さない）
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import ruling  # noqa: E402
import script_io  # noqa: E402

INPUTS = ("INPUTS_REPLY", "INPUTS_BASE_REV", "INPUTS_ITERATION", "INPUTS_PASS_TAG")
# 無くても欠けに数えない入力（依頼 226 で後から足した回の印と include の名。前の版の with: で再開した run は渡さない。無い・空は今どおり）
OPTIONAL = frozenset({"INPUTS_PASS_TAG"})


def main() -> int:
    if "INPUTS_ITERATION" not in os.environ:
        print("rule-accept: 環境変数が無い: INPUTS_ITERATION", file=sys.stderr)
        return 2
    try:
        return script_io.main(ruling.accept_rule)
    except Exception as e:   # 盤面の欠け（BoardGap）・写しの Reject・思わぬ誤りは 1 行と 2
        print(f"rule-accept: {type(e).__name__}: {' '.join(str(e).split())}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
