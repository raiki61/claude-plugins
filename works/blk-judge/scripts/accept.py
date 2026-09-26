# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""判定役の返答の受け付け（check_judge）。拒否も終了コード 0 で {"ok": false, "reason": …} を 1 行出す（script_io の docstring）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（下の注意）
import script_io  # noqa: E402
from accept import check_judge  # noqa: E402

sys.exit(script_io.main(check_judge))
