# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""世界の解のブロックの入口（lib/worldblk.intake）。置き場を置き直し、依頼（INPUTS_REQUEST）・目的の文（INPUTS_PURPOSE_FILE。任意）・
web の切り替え（INPUTS_WEB。on・off）を読んで入口の控えを書き、{due, findings, reason} を 1 行出して 0。読めない時も止めない
（reason に残し、due は偽。出口が status: failed にする）。環境変数の欠け・思わぬ誤りは標準エラーに 1 行出して 2（rolekit.script_main）
"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import worldblk  # noqa: E402  （core を sys.path に足すのもここ）
import rolekit  # noqa: E402

REQUEST_ENV = "INPUTS_REQUEST"
PURPOSE_ENV = "INPUTS_PURPOSE_FILE"
WEB_ENV = "INPUTS_WEB"
INPUTS = (REQUEST_ENV, PURPOSE_ENV, WEB_ENV)


def run(board, repo, env):
    return worldblk.intake(worldblk.place(board), request=env[REQUEST_ENV], purpose_file=env[PURPOSE_ENV], web=env[WEB_ENV],
                           cwd=repo)


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
