# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""前提の実測のブロックの出口を組む。輪（premises-loop）の受け付けが盤面（$ARTIFACTS_DIR/board/）に書いた premises.json を読み、
{"ok", "constraints_file", "constraints_summary"} を 1 行出して 0。

- constraints_summary: 判定役に貼る要約。1 行 1 制約で「- [実測|仮説] <text>（測り方: <measured_how>）」。
  実行したコマンドと出力（measured_output）は載せない（全文は constraints_file）。制約 0 件なら決まった 1 文
- premises.json が無い・読めない・形が崩れている: 標準エラーに理由を 1 行出して 1（受け付けを通らずに輪を抜けた。
  ラインはここで止まり、判定役を起こさない）
- ARTIFACTS_DIR が欠けた（空も欠け）: 標準エラーに名前を出して 2
"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import json  # noqa: E402
import os  # noqa: E402

from premises import PREMISES_FILE  # noqa: E402

ARTIFACTS_ENV = "ARTIFACTS_DIR"
NONE_SUMMARY = "（測る数値・事実の主張は依頼に無かった。制約 0 件）"


def _fail(reason: str) -> int:
    print(" ".join(reason.split()), file=sys.stderr)
    return 1


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _well_formed(c) -> bool:
    return isinstance(c, dict) and all(isinstance(c.get(k), str) for k in ("text", "measured_how", "kind"))


def main() -> int:
    if not os.environ.get(ARTIFACTS_ENV):
        print(f"環境変数が無い: {ARTIFACTS_ENV}", file=sys.stderr)
        return 2
    path = Path(os.environ[ARTIFACTS_ENV]) / "board" / PREMISES_FILE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        return _fail(f"盤面の {PREMISES_FILE} が読めない（{path}: {type(e).__name__}: {e}）——受け付けを通った前提の実測が無い")
    cs = doc.get("constraints") if isinstance(doc, dict) else None
    if not isinstance(cs, list) or not all(_well_formed(c) for c in cs):
        return _fail(f"盤面の {PREMISES_FILE} の形が崩れている（constraints[].text・measured_how・kind が要る）: {path}")
    summary = "\n".join(f"- [{c['kind']}] {_one_line(c['text'])}（測り方: {_one_line(c['measured_how'])}）" for c in cs)
    out = {"ok": True, "constraints_file": str(path), "constraints_summary": summary or NONE_SUMMARY}
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
