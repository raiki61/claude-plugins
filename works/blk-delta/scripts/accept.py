"""審査役の返答を受け付ける節（accept.check_delta）。拒否も終了コード 0 で {"ok": false, "reason": ...} を 1 行出す。
通れば盤面の delta-review.json に返答を書く。入口の環境変数は script_io の docstring。"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（Ruling R7）
import script_io  # noqa: E402
from accept import check_delta  # noqa: E402

sys.exit(script_io.main(check_delta))
