"""gh への口（PR と issue を読む・アカウントの鍵を取り出す・issue にブランチを結ぶ）。dispatch で gh を直に呼ぶのはこの 1 か所だけ。

書く関数は issue_develop（GitHub にブランチを作って issue に結ぶ。持ち主が --issue で指したときだけ）と create_pr（取り込みのコマンド
--land が PR を出す）の 2 つで、呼んでよいノードはチェック（tests/fences.py の D4 の表 WRITES）が構文木で見る。

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
    """1 件の PR を、whose-turn --json の 1 件と同じ名前のフィールド（number・title・head・url）に、状態（state）と fork の PR か（fork。
    head が別のリポジトリ）を足して返す。読めなければ GhError。"""
    p = runner(["gh", "pr", "view", str(number), "--repo", repo, "--json",
                "number,title,headRefName,url,state,isCrossRepository"], env=env)
    try:
        got = json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        got = None
    if not isinstance(got, dict) or "headRefName" not in got:
        raise GhError(f"{repo} の #{number} を読めない: {(p.stderr or p.stdout).strip()[:200]}")
    return {"number": got["number"], "title": got["title"], "head": got["headRefName"], "url": got.get("url"),
            "state": got.get("state"), "fork": bool(got.get("isCrossRepository"))}


def pr_for_branch(repo, branch, runner=_default_runner, env=None):
    """そのブランチを head にする、このリポジトリの PR（fork の PR は数えない）。開いているものが有ればそれ、無ければいちばん新しいもの。
    {number, state, head_sha} か、PR が無ければ None。読めなければ GhError（片付けは消さない側に倒す）。"""
    p = runner(["gh", "pr", "list", "--repo", repo, "--head", branch, "--state", "all", "--limit", "20",
                "--json", "number,state,headRefOid,isCrossRepository"], env=env)
    try:
        got = json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        got = None
    if not isinstance(got, list):
        raise GhError(f"{repo} のブランチ {branch} の PR を読めない: {(p.stderr or p.stdout).strip()[:200]}")
    mine = [x for x in got if isinstance(x, dict) and not x.get("isCrossRepository")]
    pick = next((x for x in mine if x.get("state") == "OPEN"), mine[0] if mine else None)
    return None if pick is None else {"number": pick.get("number"), "state": pick.get("state"),
                                      "head_sha": pick.get("headRefOid")}


def can_read(repo, runner=_default_runner, env=None):
    """gh がそのリポジトリを読めるか。ログインしていても、有効なアカウントが読めないリポジトリはある。gh が無ければ False。"""
    try:
        return runner(["gh", "repo", "view", repo, "--json", "name"], env=env).returncode == 0
    except FileNotFoundError:
        return False


def default_branch(repo, runner=_default_runner, env=None):
    """リポジトリの既定のブランチの名前。読めなければ GhError。"""
    p = runner(["gh", "repo", "view", repo, "--json", "defaultBranchRef", "--jq", ".defaultBranchRef.name"], env=env)
    name = p.stdout.strip()
    if p.returncode != 0 or not name:
        raise GhError(f"{repo} の既定のブランチを読めない: {(p.stderr or p.stdout).strip()[:200]}")
    return name


def issue_info(repo, number, runner=_default_runner, env=None):
    """1 件の issue の {number, title, url, state, prs}。prs は、その issue を閉じる PR（Development のフィールド）の番号のうち、
    このリポジトリのもの。issue に結んだブランチから PR を作ると、GitHub はブランチの結びつきを外して PR に置き換える（GitHub の文書
    「Creating a branch to work on an issue」）ので、ブランチが見えなくなった issue は、この PR からブランチを辿る。読めなければ GhError。"""
    p = runner(["gh", "issue", "view", str(number), "--repo", repo, "--json",
                "number,title,url,state,closedByPullRequestsReferences"], env=env)
    try:
        got = json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        got = None
    if not isinstance(got, dict) or "title" not in got:
        raise GhError(f"{repo} の issue #{number} を読めない: {(p.stderr or p.stdout).strip()[:200]}")
    owner, name = repo.split("/", 1)
    prs = [r.get("number") for r in got.get("closedByPullRequestsReferences") or []
           if isinstance(r, dict) and (r.get("repository") or {}).get("name") == name
           and ((r.get("repository") or {}).get("owner") or {}).get("login") == owner]
    return {"number": got["number"], "title": got["title"], "url": got.get("url"), "state": got.get("state"), "prs": prs}


def issue_branches(repo, number, runner=_default_runner, env=None):
    """issue に結んだブランチの名前の並び（`gh issue develop --list`）。読めなければ GhError。
    端末でないときの gh の表は、見出しを付けずに 1 行 1 ブランチを「ブランチ<TAB>URL」で出す。見出し（BRANCH）が来ても読み飛ばす。"""
    p = runner(["gh", "issue", "develop", "--list", str(number), "--repo", repo], env=env)
    if p.returncode != 0:
        raise GhError(f"{repo} の issue #{number} に結んだブランチを読めない: {(p.stderr or p.stdout).strip()[:200]}")
    names = [line.split()[0] for line in p.stdout.splitlines() if line.strip()]
    return [n for n in names if n != "BRANCH"]


def issue_develop(repo, number, base, runner=_default_runner, env=None):
    """GitHub に、base からブランチを作って issue に結ぶ（`gh issue develop <番号> --base <base>`）。書く口。ブランチの名前は gh の既定に任せ、
    作った後に issue_branches で読み戻す（ここでは返さない）。失敗は GhError。"""
    p = runner(["gh", "issue", "develop", str(number), "--repo", repo, "--base", base], env=env)
    if p.returncode != 0:
        raise GhError(f"{repo} の issue #{number} にブランチを結べない: {(p.stderr or p.stdout).strip()[:200]}")


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
    headRefOid
    reviewRequests(first: 50) { nodes { requestedReviewer { __typename } } }
    reviews(last: 100) { nodes { author { __typename login } submittedAt } }
    comments(last: 100) { nodes { author { __typename login } createdAt } }
    commits(last: 100) { nodes { commit { committedDate authors(first: 10) { nodes { user { login } } } } } }
  } }
}"""


def pr_activity(repo, number, me, runner=_default_runner, env=None):
    """PR の動きのうち、送り直す判断と、作者の PR にレビュアーが居るかの判断に要る物。
    {"reviewers": 人へのレビューの依頼か、作者のほかの人のレビューが有るか, "last_other": me のほかの人の最後のコメント・レビュー・
    commit の時刻（秒）, "head_sha": PR の今の head の commit}。Bot（copilot など）は、レビュアーにも、動きにも数えない。見分けは whose-turn と同じく GraphQL の
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
    return {"reviewers": bool(asked or people), "last_other": max([t for t in times if t is not None], default=None),
            "head_sha": got.get("headRefOid")}


# ゲートの CI を待つ・PR を出す（取り込みのコマンド --land。nodes/land.py）


def runs_for(repo, branch, sha, runner=_default_runner, env=None):
    """そのブランチのその commit の GitHub Actions の run を新しい順に [{id, status, conclusion, url}]。読めなければ GhError。"""
    p = runner(["gh", "run", "list", "--repo", repo, "--branch", branch, "--commit", sha, "--limit", "20",
                "--json", "databaseId,status,conclusion,url,createdAt"], env=env)
    try:
        got = json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        got = None
    if not isinstance(got, list):
        raise GhError(f"{repo} のブランチ {branch} の run を読めない: {(p.stderr or p.stdout).strip()[:200]}")
    got = sorted((x for x in got if isinstance(x, dict)), key=lambda x: x.get("createdAt") or "", reverse=True)
    return [{"id": x.get("databaseId"), "status": x.get("status"), "conclusion": x.get("conclusion"), "url": x.get("url")}
            for x in got]


def watch_run(repo, run_id, runner=_default_runner, env=None):
    """run が終わるまで待ち（gh run watch）、終わりの {id, status, conclusion, url} を読み直して返す。
    緑か赤かは、watch の終わりの値でなく読み直した conclusion で決める。読めない・まだ終わっていなければ GhError。"""
    runner(["gh", "run", "watch", str(run_id), "--repo", repo], env=env)
    p = runner(["gh", "run", "view", str(run_id), "--repo", repo, "--json", "databaseId,status,conclusion,url"], env=env)
    try:
        got = json.loads(p.stdout) if p.returncode == 0 else None
    except ValueError:
        got = None
    if not isinstance(got, dict):
        raise GhError(f"{repo} の run {run_id} を読めない: {(p.stderr or p.stdout).strip()[:200]}")
    if got.get("status") != "completed":
        # watch が途中で切れた（通信・認証）。途中の run を赤と取り違えない
        raise GhError(f"{repo} の run {run_id} を待ち終える前に gh run watch が戻った（今の状態 {got.get('status')}）")
    return {"id": got.get("databaseId"), "status": got.get("status"), "conclusion": got.get("conclusion"), "url": got.get("url")}


def run_failure(repo, run_id, lines=20, runner=_default_runner, env=None):
    """赤の run の要点: 落ちた job と step の名前、落ちた step の記録の終わりの lines 行。読めない分は省く（GhError にしない）。"""
    out = []
    p = runner(["gh", "run", "view", str(run_id), "--repo", repo, "--json", "jobs"], env=env)
    try:
        jobs = json.loads(p.stdout).get("jobs") or [] if p.returncode == 0 else []
    except (ValueError, AttributeError):
        jobs = []
    for j in jobs:
        if isinstance(j, dict) and j.get("conclusion") not in ("success", "skipped", None):
            steps = [s.get("name") for s in j.get("steps") or [] if isinstance(s, dict) and s.get("conclusion") == "failure"]
            out.append(f"落ちた job: {j.get('name')}" + (f"（step: {', '.join(steps)}）" if steps else ""))
    p = runner(["gh", "run", "view", str(run_id), "--repo", repo, "--log-failed"], env=env)
    if p.returncode == 0:
        # 1 行は「job<TAB>step<TAB>時刻と本文」。本文だけを残す
        tail = [line.split("\t")[-1] for line in p.stdout.splitlines() if line.strip()][-lines:]
        out += tail
    return out


def create_pr(repo, branch, base, runner=_default_runner, env=None):
    """ブランチ branch から base へ PR を出す（gh pr create --fill。題と本文は commit から）。書く口。PR の URL を返す。失敗は GhError。"""
    p = runner(["gh", "pr", "create", "--repo", repo, "--head", branch, "--base", base, "--fill"], env=env)
    url = (p.stdout or "").strip().splitlines()[-1:] if p.returncode == 0 else []
    if not url:
        raise GhError(f"{repo} のブランチ {branch} から PR を出せない: {(p.stderr or p.stdout).strip()[:200]}")
    return url[0]
