# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""web の役の受け付け（lib/worldblk.judge_accept）。返答（INPUTS_REPLY）を判断の材料と照らし、通れば抜き書きを機械が取り直した
本文（worldblk.fetch。web が off の run は取り直さない）で照らして、判断の行を書く。字のまま本文に無い抜き書きを指す根拠は外れ、
根拠の残らない行の印は knowledge になる。{ok, done, reason} を 1 行出して 0。拒否は例外でなく ok: false（done は
rolekit.GIVE_UP_AFTER 回目の拒否で真になり、輪を抜ける）。返答が JSON でない時も拒否として返す。材料の控えが無い・環境変数の欠け・
思わぬ誤りは標準エラーに 1 行出して 2（rolekit.script_main）
"""

import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))
import worldblk  # noqa: E402  （core を sys.path に足すのもここ）
import rolekit  # noqa: E402

REPLY_ENV = "INPUTS_REPLY"
INPUTS = (REPLY_ENV,)


def run(board, repo, env):
    reply, _ = rolekit.parse_reply(env[REPLY_ENV])
    return worldblk.judge_accept(worldblk.place(board), reply, worldblk.fetch)


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
