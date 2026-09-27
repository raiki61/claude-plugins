# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役の返答を受け付ける（material.take）。拒否（写しの規則・作業ツリーの変化・読めない返答）は {ok: false, done, give_up, reason,
reason_file} で 0（3 回目の拒否で done・give_up）。旗の役の起動に包みの柵が無ければ盤面を止めて done。
盤面がもう止まっていれば（同じ波の別の目が止めた。役を飛ばした周の null も）受けずに done・stopped。配線の誤りは 2"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意。Ruling R7）
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))                # ブロックの芯（lib/material.py）
import material  # noqa: E402

INPUTS = ("INPUTS_ROLE", "INPUTS_REPLY", "INPUTS_ADAPTER")   # 読む INPUTS_*（YAML の with: の鍵と同じ）

if __name__ == "__main__":
    sys.exit(material.main_accept())
