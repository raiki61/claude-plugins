# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""判定のブロックの出口を組む（judgetake.collect）。輪（judge-loop）の受け付けが盤面（$ARTIFACTS_DIR/board/）に書いた judgment.json を読み、
{"ok", "open_units", "need_fix", "judgment_file", "one_shot"} を 1 行出して 0。

- open_units: 直す義務の残る単位（検証器の is_open＝[block] か do-now の [suggest]）の key。受け付けと同じ述語
- need_fix: open_units が 1 つでも在るか。false ならラインは修正から後を飛ばして finish で終える（Ruling R21。
  直す物が無いという判定は失敗ではない）
- judgment.json が無い（輪が 3 回とも拒んで抜けた）: ラインの盤面なら最後の拒否の文で盤面を止めて（by works:judge）ok: false を
  出して 0（次の境の節が止まった盤面を見てラインを止める。R50）。単独の run なら標準エラーに理由を 1 行出して 1
- judgment.json が読めない・形が崩れている: 標準エラーに理由を 1 行出して 1（前の呼び出しの残りは intake が消すので、在ればこの
  呼び出しの受け付けが書いた物）
- ARTIFACTS_DIR が欠けた（空も欠け）・盤面を開けない: 標準エラーに 1 行出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # blk-judge の芯
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import json  # noqa: E402
import os  # noqa: E402

import judgetake  # noqa: E402

ARTIFACTS_ENV = "ARTIFACTS_DIR"


def main() -> int:
    if not os.environ.get(ARTIFACTS_ENV):
        print(f"環境変数が無い: {ARTIFACTS_ENV}", file=sys.stderr)
        return 2
    try:
        out = judgetake.collect(Path(os.environ[ARTIFACTS_ENV]) / "board")
    except judgetake.Unreadable as e:
        print(" ".join(str(e).split()), file=sys.stderr)
        return 1
    except Exception as e:   # 盤面を開けない・止められない（BoardGap・Reject）と思わぬ誤りは 1 行と 2（traceback を出さない）
        print(f"判定の出口を組めない（{type(e).__name__}）: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
