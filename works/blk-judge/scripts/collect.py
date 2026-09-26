"""判定のブロックの出口を組む。輪（judge-loop）の受け付けが盤面（$ARTIFACTS_DIR/board/）に書いた judgment.json を読み、
{"ok", "open_units", "need_fix", "judgment_file", "one_shot"} を 1 行出して 0。

- open_units: 直す義務の残る単位（検証器の is_open＝[block] か do-now の [suggest]）の key。check_judge と同じ述語
- need_fix: open_units が 1 つでも在るか。false ならラインは修正から後を飛ばして finish で終える（Ruling R21。
  直す物が無いという判定は失敗ではない）
- judgment.json が無い・読めない・形が崩れている: 標準エラーに理由を 1 行出して 1（受け付けを通らずに輪を抜けたことになる）
- ARTIFACTS_DIR が欠けた（空も欠け）: 標準エラーに名前を出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import json  # noqa: E402
import os  # noqa: E402
import types  # noqa: E402

from accept import JUDGMENT_FILE, VALIDATOR  # noqa: E402
from engine.rules import validator_module  # noqa: E402

ARTIFACTS_ENV = "ARTIFACTS_DIR"


def _fail(reason: str) -> int:
    print(" ".join(reason.split()), file=sys.stderr)
    return 1


def main() -> int:
    if not os.environ.get(ARTIFACTS_ENV):
        print(f"環境変数が無い: {ARTIFACTS_ENV}", file=sys.stderr)
        return 2
    path = Path(os.environ[ARTIFACTS_ENV]) / "board" / JUDGMENT_FILE
    try:
        judgment = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _fail(f"盤面の {JUDGMENT_FILE} が読めない（{path}: {type(e).__name__}: {e}）——受け付けを通った判定が無い")
    units = judgment.get("units") if isinstance(judgment, dict) else None
    one_shot = judgment.get("one_shot") if isinstance(judgment, dict) else None
    if not isinstance(units, list) or not all(isinstance(u, dict) and "key" in u and "label" in u for u in units) \
            or not isinstance(one_shot, str):
        return _fail(f"盤面の {JUDGMENT_FILE} の形が崩れている（units[].key・label と one_shot が要る）: {path}")
    V = validator_module(types.SimpleNamespace(state={"validator": str(VALIDATOR)}))
    open_units = [u["key"] for u in units if V.is_open(u)]
    out = {"ok": True, "open_units": open_units, "need_fix": bool(open_units),
           "judgment_file": str(path), "one_shot": one_shot}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
