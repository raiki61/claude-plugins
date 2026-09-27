# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""目的の役の返答の受け付け（purpose.check_purpose）。拒否も終了コード 0 で {"ok": false, "reason": …} を 1 行出す（script_io の docstring）。
出口に輪を抜ける旗 done を足す（rolekit.with_done: 通った時か、この呼び出しの 3 回目の拒否。R50）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import script_io  # noqa: E402
from purpose import NODE, check_purpose  # noqa: E402
import rolekit  # noqa: E402


def with_done(out: dict) -> dict:
    return rolekit.with_done(script_io.board_dir(), NODE, out)


sys.exit(script_io.main(check_purpose, finish=with_done))
