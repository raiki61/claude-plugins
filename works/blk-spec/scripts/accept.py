# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役の返答を受け付ける（specblk.take）。拒否（写しの規則・読むだけの役の作業ツリーの変化・読めない返答）は {ok: false, done,
give_up, reason} で 0（GIVE_UP_AFTER 回目の拒否で done・give_up。輪が抜けて collect が盤面を止める）。通れば {ok: true, done: true, …}"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "lib"))   # ブロックのモジュール（specblk が .shared/core を足す）
import specblk  # noqa: E402

INPUTS = ("INPUTS_ROLE", "INPUTS_REPLY")   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_spec.py が見る）


def run(board, repo, env):
    role = env["INPUTS_ROLE"]
    reply, why = specblk.parse_reply(env["INPUTS_REPLY"])
    if reply is None:
        return specblk.refuse(board, role, why)
    return specblk.take(board, role, reply, repo)


if __name__ == "__main__":
    sys.exit(specblk.script_main(run, INPUTS))
