# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""判定の根を開く節（線の木の段 3。judgeverify）。stage prep は判定の開いた単位ごとの裏取りの下請けのファイルと束ね役の指示書を
書いて {ok, go, prompt_file}（単位が 2 つ未満・盤面が無い・止まった盤面・入力 verify が off は go 偽）、stage merge は下請けの答えのファイルを
確かめて今の周の申し送りにまとめて {ok, verify_file, verified, unverified}。stage が違う・環境変数の欠け・盤面を開けないなら 2"""
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # blk-judge の芯
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # core を頭に（script_io の注意。R7）
import judgeverify  # noqa: E402
import rolekit  # noqa: E402
from board import BoardGap  # noqa: E402

INPUTS = ("INPUTS_STAGE", "INPUTS_VERIFY")   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_judge.py が見る）
# 無くても欠けに数えない入力（後から足した切り替え。前の版の with: で再開した run は渡さない。無い・空は on＝今どおり）
OPTIONAL = frozenset({"INPUTS_VERIFY"})


def run(board, repo, env):
    stage = env["INPUTS_STAGE"]
    if stage == "prep":
        return judgeverify.prep(board, repo, verify=os.environ.get("INPUTS_VERIFY", ""))
    if stage == "merge":
        return judgeverify.merge(board, repo)
    raise BoardGap(f"stage は prep か merge（{stage!r}）")


if __name__ == "__main__":
    # fence: 束ね役の指示書のパスは Archon の置き換えで指示書へ貼られるので、$ を含む置き場を 2 で断る
    sys.exit(rolekit.script_main(run, tuple(n for n in INPUTS if n not in OPTIONAL), fence=True))
