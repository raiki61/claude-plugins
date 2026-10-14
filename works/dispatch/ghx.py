"""gh への口（片付けで PR の状態を読む）。dispatch で gh を直に呼ぶのはこの 1 か所だけ。読むだけで、書かない。

自分の番の PR の一覧は gh を直に呼ばず、写した whose-turn に任せる（nodes/prs.py）。
"""

import json
import subprocess


def _default_runner(argv, env=None):
    return subprocess.run(argv, capture_output=True, text=True, env=env)


def pr_state(repo, number, runner=_default_runner):
    """OPEN・MERGED・CLOSED のどれか。読めない時は None（片付けは消さない側に倒す）。"""
    p = runner(["gh", "pr", "view", str(number), "--repo", repo, "--json", "state"])
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout).get("state")
    except (ValueError, AttributeError):
        return None
