# /// script
# requires-python = ">=3.10"
# dependencies = []
# ///
"""役の返答を受け付ける（ci_role.take）。拒否（作業ツリーの変化・写しの規則・読めない返答）は {ok: false, done, give_up, reason} で 0
（3 回目の拒否で done・give_up。輪が抜けて collect が盤面を止める）。通れば {ok: true, done: true, …, status}。
INPUTS_ADAPTER は ci-fence が読んだ包みの形（YAML の with: で $ci-fence.output.adapter。start の控えは読み直さない。再審査 N8）"""
import sys
from pathlib import Path

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように。必ず import より前
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / ".shared" / "core"))   # 頭に入れる（script_io の注意）
import ci_role  # noqa: E402

INPUTS = ("INPUTS_NODE", "INPUTS_REPLY", "INPUTS_ADAPTER")   # 読む INPUTS_*（YAML の with: の鍵と同じ。tests/test_blk_ci.py が見る）


def run(board, repo, env):
    node = env["INPUTS_NODE"]
    reply, why = ci_role.parse_reply(env["INPUTS_REPLY"])
    if reply is None:
        return ci_role.refuse(board, node, why)
    return ci_role.take(board, node, reply, repo, env["INPUTS_ADAPTER"])


if __name__ == "__main__":
    sys.exit(ci_role.script_main(run, INPUTS))
