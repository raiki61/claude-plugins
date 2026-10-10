# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""言い直す役の受け付け（lib/worldblk.classes_accept）。返答（INPUTS_REPLY）を入口の控えと照らし、通れば言い直しの行を書く。
{ok, done, reason} を 1 行出して 0。拒否は例外でなく ok: false（done は rolekit.GIVE_UP_AFTER 回目の拒否で真になり、輪を抜ける。
max_iterations で線を落とさない）。返答が JSON でない時も拒否として返す。入口の控えが無い・環境変数の欠け・思わぬ誤りは
標準エラーに 1 行出して 2（rolekit.script_main）
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
    return worldblk.classes_accept(worldblk.place(board), reply)


if __name__ == "__main__":
    sys.exit(rolekit.script_main(run, INPUTS))
