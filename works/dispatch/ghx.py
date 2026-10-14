"""gh への口（片付けで PR の状態を読む・アカウントの鍵を取り出す）。dispatch で gh を直に呼ぶのはこの 1 か所だけ。読むだけで、書かない。

自分の番の PR の一覧は gh を直に呼ばず、写した whose-turn に任せる（nodes/prs.py）。

gh にはフォルダごとにアカウントを替える仕組みが無い。環境変数 GH_TOKEN が保存したログインより優先されるので、
リポジトリごとのアカウント（設定の gh_user）は、`gh auth token --user` で取り出した鍵を子の環境にだけ入れて替える。
マシン全体の有効なアカウント（gh auth switch）は替えない。並行するほかの作業まで巻き込むため。
"""

import json
import subprocess


def _default_runner(argv, env=None):
    return subprocess.run(argv, capture_output=True, text=True, env=env)


class GhError(Exception):
    pass


def env_for(user, base_env, runner=_default_runner):
    """base_env の写しに、gh のアカウント user の鍵を GH_TOKEN として入れて返す。base_env は変えない。"""
    p = runner(["gh", "auth", "token", "--user", user], env=dict(base_env))
    token = p.stdout.strip()
    if p.returncode != 0 or not token:
        raise GhError(f"gh のアカウント {user} の鍵を取り出せない（gh auth status で、ログインしているかを確かめる）: "
                      f"{p.stderr.strip()[:200]}")
    return {**base_env, "GH_TOKEN": token}


def pr_state(repo, number, runner=_default_runner, env=None):
    """OPEN・MERGED・CLOSED のどれか。読めない時は None（片付けは消さない側に倒す）。"""
    p = runner(["gh", "pr", "view", str(number), "--repo", repo, "--json", "state"], env=env)
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout).get("state")
    except (ValueError, AttributeError):
        return None
