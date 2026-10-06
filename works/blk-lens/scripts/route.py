# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""振り分けの節（lenses.route。AI なし）。レンズごとの <名>_go と理由・指示書を 1 行で出し、盤面の今の周の lens.json に書く。
入力 skip（環境変数 INPUTS_SKIP）に理由の文が在れば、どのレンズも起こさない。
盤面に今の周の修正の差分が無い・環境変数の欠けは標準エラーに 1 行で 2（集め役が控えの無いことを理由に ok: false を返す）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # 頭に入れる（スクリプトのフォルダより先。Ruling R7）
import lenses  # noqa: E402
import rolekit  # noqa: E402

INPUTS = ("INPUTS_SKIP",)   # 省く理由の文（空は今どおり）


def run(board, repo, env):
    return lenses.route(board, skip=env["INPUTS_SKIP"])


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
