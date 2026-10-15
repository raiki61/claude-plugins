"""gh への口（片付けで PR の状態を読む・アカウントの鍵を取り出す）。dispatch で gh を直に呼ぶのはこの 1 か所だけ。読むだけで、書かない。

自分の番の PR の一覧は gh を直に呼ばず、写した whose-turn に任せる（nodes/prs.py）。

gh にはフォルダごとにアカウントを替える仕組みが無い。環境変数 GH_TOKEN が保存したログインより優先されるので、
リポジトリごとのアカウント（設定の gh_user）は、`gh auth token --user` で取り出した鍵を子の環境にだけ入れて替える。
マシン全体の有効なアカウント（gh auth switch）は替えない。並行するほかの作業まで巻き込むため。
"""

import datetime
import json
import subprocess


def _default_runner(argv, env=None):
    return subprocess.run(argv, capture_output=True, text=True, encoding="utf-8", errors="replace", env=env)


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


def pr_info(repo, number, runner=_default_runner, env=None):
    """1 件の PR を、whose-turn --json の 1 件と同じ名前の欄（number・title・head・url）で返す。読めなければ GhError。"""
    p = runner(["gh", "pr", "view", str(number), "--repo", repo, "--json", "number,title,headRefName,url"], env=env)
    try:
        got = json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        got = None
    if not isinstance(got, dict) or "headRefName" not in got:
        raise GhError(f"{repo} の #{number} を読めない: {(p.stderr or p.stdout).strip()[:200]}")
    return {"number": got["number"], "title": got["title"], "head": got["headRefName"], "url": got.get("url")}


def login(runner=_default_runner, env=None):
    """gh の今のアカウントのログイン名（env の GH_TOKEN が有ればその鍵の持ち主）。読めなければ GhError。"""
    p = runner(["gh", "api", "user", "--jq", ".login"], env=env)
    name = p.stdout.strip()
    if p.returncode != 0 or not name:
        raise GhError(f"gh のログイン名を読めない: {(p.stderr or p.stdout).strip()[:200]}")
    return name


def _epoch(stamp):
    try:
        return datetime.datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError):
        return None


ACTIVITY_QUERY = """query($owner: String!, $name: String!, $number: Int!) {
  repository(owner: $owner, name: $name) { pullRequest(number: $number) {
    author { login }
    reviewRequests(first: 50) { nodes { requestedReviewer { __typename } } }
    reviews(last: 100) { nodes { author { __typename login } submittedAt } }
    comments(last: 100) { nodes { author { __typename login } createdAt } }
    commits(last: 100) { nodes { commit { committedDate authors(first: 10) { nodes { user { login } } } } } }
  } }
}"""


def pr_activity(repo, number, me, runner=_default_runner, env=None):
    """PR の動きのうち、送り直す判断と、作者の PR にレビュアーが居るかの判断に要る物。
    {"reviewers": 人へのレビューの依頼か、作者のほかの人のレビューが有るか, "last_other": me のほかの人の最後のコメント・レビュー・
    commit の時刻（秒）}。Bot（copilot など）は、レビュアーにも、動きにも数えない。見分けは whose-turn と同じく GraphQL の
    __typename（login の形では見分けない）。レビューのスレッドへの返事は、返した人のレビューとして reviews に入る。読めなければ GhError。"""
    owner, name = repo.split("/", 1)
    p = runner(["gh", "api", "graphql", "-f", f"query={ACTIVITY_QUERY}", "-F", f"owner={owner}", "-F", f"name={name}",
                "-F", f"number={number}"], env=env)
    try:
        got = json.loads(p.stdout)["data"]["repository"]["pullRequest"] if p.returncode == 0 else None
    except (ValueError, KeyError, TypeError):
        got = None
    if not isinstance(got, dict):
        raise GhError(f"{repo} の #{number} の動きを読めない: {(p.stderr or p.stdout).strip()[:200]}")
    nodes = lambda k: (got.get(k) or {}).get("nodes") or []
    who = lambda actor: (actor or {}).get("login")
    author = who(got.get("author"))
    human = lambda actor: (actor or {}).get("__typename") != "Bot"
    times = [_epoch(c.get("createdAt")) for c in nodes("comments") if who(c.get("author")) != me and human(c.get("author"))]
    times += [_epoch(r.get("submittedAt")) for r in nodes("reviews") if who(r.get("author")) != me and human(r.get("author"))]
    times += [_epoch((c.get("commit") or {}).get("committedDate")) for c in nodes("commits")
              if me not in [who(a.get("user")) for a in ((c.get("commit") or {}).get("authors") or {}).get("nodes") or []]]
    people = [r for r in nodes("reviews") if human(r.get("author")) and who(r.get("author")) not in (author, None)]
    asked = [q for q in nodes("reviewRequests") if ((q.get("requestedReviewer") or {}).get("__typename")) in ("User", "Team")]
    return {"reviewers": bool(asked or people), "last_other": max([t for t in times if t is not None], default=None)}


def pr_state(repo, number, runner=_default_runner, env=None):
    """OPEN・MERGED・CLOSED のどれか。読めない時は None（片付けは消さない側に倒す）。"""
    p = runner(["gh", "pr", "view", str(number), "--repo", repo, "--json", "state"], env=env)
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout).get("state")
    except (ValueError, AttributeError):
        return None
