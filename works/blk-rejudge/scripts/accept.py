# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役の返答を受け付ける（rejudge.take）。拒否（写しの規則・作業ツリーの変化・読めない返答）は {ok: false, reason} で 0
（輪が理由を貼って出し直させる）。通れば {ok: true, reason, node, verdict}"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import rejudge  # noqa: E402

INPUTS = ("INPUTS_ROLE", "INPUTS_REPLY")   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_rejudge.py が見る）


def run(board, repo, env):
    nid = rejudge.node_of(env["INPUTS_ROLE"])
    reply, why = rejudge.parse_reply(env["INPUTS_REPLY"])
    if reply is None:
        return rejudge.refuse(board, nid, why)
    return rejudge.take(board, nid, reply, repo)


if __name__ == "__main__":
    sys.exit(rejudge.script_main(run, INPUTS))
