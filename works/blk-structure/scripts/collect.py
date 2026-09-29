# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""構造のブロックの出口を組む。段 A が書いた structure.json（INPUTS_STRUCTURE_FILE）と design.jsonl（INPUTS_DESIGN_FILE）を
確かめ、構造の目の輪の出口（INPUTS_EYE。輪が飛ばされた・落ちた周は null）と、目を起こす周だったか（INPUTS_EYE_DUE）を突き合わせ、
{ok, structure_file, design_file, status, reason, wall_s} を 1 行出して 0。後段が読んでよいのはこの 2 本のファイルだけ。

- ok は実測や目が落ちても true（status: failed と reason で分かる。線を止めない）。failed は、実測が落ちた・目を起こす周なのに
  輪の出口が無い（目の会話が落ちた）・目の返答が 3 回とも受け付けで拒まれた周
- wall_s は段 A と構造の目の壁時計の秒の和（structure.json の timing と lib/eye の控え）
- 2 本のどちらかが無い・structure.json が読めない（配線の誤り）: 標準エラーに理由を 1 行出して 1
"""
import json
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import eye  # noqa: E402

STRUCTURE_ENV = "INPUTS_STRUCTURE_FILE"
DESIGN_ENV = "INPUTS_DESIGN_FILE"
EYE_DUE_ENV = "INPUTS_EYE_DUE"
EYE_ENV = "INPUTS_EYE"
INPUTS = (STRUCTURE_ENV, DESIGN_ENV, EYE_DUE_ENV, EYE_ENV)   # 裁定 TA16: 読む INPUTS_* の組


def _eye_exit():
    raw = os.environ.get(EYE_ENV, "").strip()
    try:
        got = json.loads(raw) if raw else None
    except json.JSONDecodeError:
        return None
    return got if isinstance(got, dict) else None


def outcome(doc: dict, due: bool, got, kept: dict) -> tuple:
    """(status, reason)"""
    if doc["status"] != "ok":
        return "failed", f"実測が落ちた: {doc.get('reason') or '理由の記録が無い'}"
    if not due:
        return "ok", ""
    if got is None:
        return "failed", "構造の目の会話が落ちたか走らなかった（輪の出口が無い）"
    if not got.get("ok"):
        return "failed", f"構造の目の返答が {got.get('attempt') or kept.get('attempt') or '?'} 回とも受け付けで拒まれた: {got.get('reason') or ''}"
    return "ok", ""


def main() -> int:
    structure, design = Path(os.environ.get(STRUCTURE_ENV, "")), Path(os.environ.get(DESIGN_ENV, ""))
    try:
        doc = json.loads(structure.read_text(encoding="utf-8"))
        if not design.is_file():
            raise OSError(f"設計の行のファイルが無い: {design}")
        if doc["status"] not in ("ok", "failed"):
            raise KeyError(f"status が ok・failed でない: {doc['status']!r}")
        wall = doc["timing"]["wall_s"]
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as e:
        print(f"collect.py: 出力の 2 本が揃わない: {e}", file=sys.stderr)
        return 1
    kept = eye.state(structure.parent)
    status, reason = outcome(doc, os.environ.get(EYE_DUE_ENV, "").strip() == "true", _eye_exit(), kept)
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"ok": True, "structure_file": str(structure), "design_file": str(design), "status": status,
                      "reason": reason, "wall_s": round(wall + (kept.get("wall_s") or 0), 3)}, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
