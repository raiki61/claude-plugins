# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""段 A の実測（設計書 structure-block-design の 2 節・8 節）。入力の契約の単位のファイル（INPUTS_UNITS。JSON の配列で、各行は
{id, paths, summary}）を読み、単位ごとに paths を同じフォルダの measure.py に子のプロセスで渡し（コマンド 1 つの口。import しない）、
結果を $ARTIFACTS_DIR/structure/structure.json に書く。設計の行のファイル design.jsonl は 0 バイトで置き直す（JSON Lines は空行を
許さないので改行も書かない。行を書くのは構造の目の受け付け）。前の周の構造の目の控え eye.json は消す。

structure.json: {status: ok|failed, reason, root, policy_path, units: [{id, summary, paths, status, reason, measure}],
timing: {started_at, finished_at, wall_s}}。単位の status は measured か failed（failed なら reason に measure.py の標準エラーの末尾）。

- 対象の根（INPUTS_ROOT）は空なら cwd。相対なら cwd から解く。方針の文書（INPUTS_POLICY_PATH）は任意で、パスを控えるだけ
- 単位のファイルが読めない・形が違う・measure.py が落ちた時も、structure.json の status: failed と reason に残して 0 で終える
  （実測が落ちても線を止めない。GitHub Actions の continue-on-error と同じ分け方で、節の結末は成功のまま）
- {"structure_file", "design_file", "eye"} を 1 行出して 0（eye は構造の目を起こす周か。lib/eye.due）。ARTIFACTS_DIR が欠けた（空も欠け）時だけ、標準エラーに名前を出して 2
"""
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "lib"))
import eye  # noqa: E402

UNITS_ENV = "INPUTS_UNITS"
ROOT_ENV = "INPUTS_ROOT"
POLICY_ENV = "INPUTS_POLICY_PATH"
INPUTS = (UNITS_ENV, ROOT_ENV, POLICY_ENV)   # 裁定 TA16: 読む INPUTS_* の組
ARTIFACTS_ENV = "ARTIFACTS_DIR"
OUT_DIR = "structure"
STRUCTURE_FILE = "structure.json"
DESIGN_FILE = "design.jsonl"
MEASURE = Path(__file__).resolve().parent / "measure.py"
REASON_TAIL = 2000


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_units(path: str) -> list:
    """単位のファイルを読み、形を確かめて返す。読めない・形が違うなら ValueError"""
    if not path:
        raise ValueError(f"{UNITS_ENV} が空")
    try:
        rows = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ValueError(f"単位のファイルが読めない: {e}") from None
    if not isinstance(rows, list):
        raise ValueError("単位のファイルが JSON の配列でない")
    for i, r in enumerate(rows):
        ok = (isinstance(r, dict) and isinstance(r.get("id"), str) and r["id"]
              and isinstance(r.get("paths"), list) and r["paths"] and all(isinstance(p, str) and p for p in r["paths"])
              and isinstance(r.get("summary", ""), str))
        if not ok:
            raise ValueError(f"単位 {i} の形が違う（id は空でない文字列・paths は空でない文字列の空でない配列・summary は文字列）")
    return rows


def measure_unit(unit: dict, root: Path) -> dict:
    row = {"id": unit["id"], "summary": unit.get("summary", ""), "paths": unit["paths"]}
    p = subprocess.run([sys.executable, str(MEASURE), "--paths", *unit["paths"], "--repo", str(root)], cwd=str(root),
                       capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
    if p.returncode == 0:
        try:
            return {**row, "status": "measured", "reason": "", "measure": json.loads(p.stdout)}
        except json.JSONDecodeError as e:
            return {**row, "status": "failed", "reason": f"measure.py の出力が JSON でない: {e}", "measure": None}
    why = (p.stderr.strip() or f"measure.py が終了コード {p.returncode}")[-REASON_TAIL:]
    return {**row, "status": "failed", "reason": why, "measure": None}


def main() -> int:
    art = os.environ.get(ARTIFACTS_ENV)
    if not art:
        print(f"環境変数が無い: {ARTIFACTS_ENV}", file=sys.stderr)
        return 2
    t0, started = time.monotonic(), _now()
    out_dir = Path(art) / OUT_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    design = out_dir / DESIGN_FILE
    design.write_bytes(b"")
    (out_dir / eye.EYE_FILE).unlink(missing_ok=True)
    root = Path(os.environ.get(ROOT_ENV) or ".").resolve()
    doc = {"status": "ok", "reason": "", "root": str(root), "policy_path": os.environ.get(POLICY_ENV, ""), "units": []}
    try:
        units = read_units(os.environ.get(UNITS_ENV, ""))
    except ValueError as e:
        doc.update(status="failed", reason=str(e))
    else:
        doc["units"] = [measure_unit(u, root) for u in units]
        failed = [u["id"] for u in doc["units"] if u["status"] == "failed"]
        if failed:
            doc.update(status="failed", reason=f"実測が落ちた単位: {', '.join(failed)}")
    doc["timing"] = {"started_at": started, "finished_at": _now(), "wall_s": round(time.monotonic() - t0, 3)}
    structure = out_dir / STRUCTURE_FILE
    structure.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps({"structure_file": str(structure), "design_file": str(design), "eye": eye.due(doc)}, ensure_ascii=False),
          flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
