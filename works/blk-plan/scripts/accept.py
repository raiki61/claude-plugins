# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役の返答を受け付ける（planblk.main_accept → rolekit.main_accept → entry.take。独立設計の役は core の design.accept_reply で
盤面の根の design.json へ）。拒否（読めない返答・写しの規則・作業ツリーの変化）は {ok: false, reason_file} で 0、3 回目の拒否で
done・give_up（輪を抜ける）。出口 {ok, done, give_up, reason, reason_file, node, …}"""
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # blk-plan の芯
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # core を頭に（script_io の注意。R7）
import planblk  # noqa: E402

INPUTS = ("INPUTS_ROLE", "INPUTS_REPLY", "INPUTS_REPLAN")   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_plan.py が見る）
# 無くても欠けに数えない入力（後から足した replan。前の版の with: で再開した run は渡さない。無い・空は今どおり）
OPTIONAL = frozenset({"INPUTS_REPLAN"})


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    if "INPUTS_ROLE" not in os.environ:
        print("環境変数が無い: INPUTS_ROLE", file=sys.stderr)
        sys.exit(2)
    try:
        planblk.known_role(os.environ["INPUTS_ROLE"])
    except planblk.BoardGap as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)
    sys.exit(planblk.main_accept(os.environ["INPUTS_ROLE"], os.environ.get("INPUTS_REPLAN", "")))
