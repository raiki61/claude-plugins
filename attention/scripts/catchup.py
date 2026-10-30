#!/usr/bin/env python3
"""1 件の PR / issue について「前回自分が触ってから何が起きたか」を機械で取り切り、短く出す。

〈目的〉並行作業から戻ったときに「この作業のどこで止まっていたか」を思い出す。判定（次に何を
するか）はしない——それは読む人か /catchup の AI の仕事。

〈私が最後にしたこと〉このツールの中心は diff ではなく**自分の最後の痕跡**である。本文コメント・
レビュー・レビュースレッド・push を全部見て最も新しい自分の痕跡を「私が最後にしたこと」に置き、
その後に起きたことだけを並べる。自分がまだ一度も触っていないときは、自分に渡された時点
（レビュー依頼・assign・メンションのうち最も新しいもの）に落とし、それも無ければ作成時に落とす。

〈依頼を探す範囲〉push は返事ではない。私宛の依頼を探す範囲は、最後の push ではなく最後の
**発言**（コメント・レビュー・スレッド）より後で切る。push で切ると、push の前に来ていた問いが
答えたことになって消える。

〈commit の主〉GitHub は commit の author をメールで人に結び付ける。結び付いていないメールで
commit していると author の login は空で、名前とメールだけが残る。手元の git config の user.email と
一致する commit は自分の push として扱う——これを怠ると、自分の push が「その後に起きたこと」に
他人の出来事として混ざり、「私が最後にしたこと」が実際より古くなる（実測: 個人メールで commit
している PR で 1 か月ずれた）。名前では照合しない（同名の他人の push を私にしてしまう）。照合に
使う config は実行した場所のものなので、一致しなかった結び付き無しの commit は末尾で申告する。

〈参照は出来事ではない〉他の PR / issue がこの番号を書いた（CrossReferenced）だけでは、この件の
状態は変わらない。時系列に混ぜると表示上限を食い、本当の出来事（コメント・レビュー）を押し出す。
「つながっている先」にだけ置く。

〈本文〉作者の本文は、末尾の材料の先頭に全文（60 行まで。--full で全部）を出す。閉じる issue と、本文が
# で指す issue / PR（3 件まで）の本文の冒頭も添える——背景は Closes の無い参照先に書いてあることが多い
（実測: 本文が「あわせて #1105」とだけ書く PR で、AI が gh issue view を自分で引いた）。戻るとき「何の PR か」も失われていて、題名と diff だけでは内容が分からない（実測: 28 file の
PR で、型の 1〜2 文と地図の 1 文だけでは初見に内容が読めなかった）。AI は本文と地図の先頭コメントから
「説明」（背景と課題・何をどう変えるか・使う側の変化）を書く。機械は要約しない。

〈末尾の材料〉行の要約は出さない。それは思い出す助けにならず、AI が要約すると実物と違う言葉に
なる。末尾に付けるのは実物の行の材料——指摘（相手の発言と head のその行）・CI（落ちた step の
ログ）・地図（置き場所・骨組み・配線）——で、**有れば出す、無ければ出さない**。作者が私かどうかでは
出し分けない。このツールを呼ぶこと自体が、自分の PR でも中身を忘れている印だから（実測: 自分の PR で
木が出ず、欲しかった）。焦点の語（指摘・地図・CI）は、その 1 つに絞る口。材料でも判断はせず、行は
1 文字も変えない。

〈短さ〉既定の出力は画面 1 つに収める。全文が要るときだけ --full を付ける。長い抜粋を既定に
すると、思い出すためのツールが読み直しの作業になり、目的と衝突する。

〈手元〉戻るとき、会話の位置と一緒に手元のブランチも失われている。--switch を付けると、該当ブランチ（PR は
head のブランチ、issue は名前に番号を持つ手元のブランチが 1 本のとき）へ git switch で移る。PR のブランチが
手元に無ければ、origin からその元を 1 本だけ fetch して git switch -c で作って移る（名前と追跡先は
gh pr checkout と同じ）。手元を変える操作はこの git switch と、その 1 本の fetch だけで、手元にあるブランチは
動かさない（pull・merge・stash・commit・gh pr checkout はしない）。移った・移らなかった理由は見出しの
「ブランチ」の行に出し、移った（または既に居た）ときは末尾に「手元のブランチ」のセクションが付く。移らない条件と
その実測は「該当ブランチへ移る」のセクションに。
"""

import argparse
import concurrent.futures
import datetime as dt
import functools
import json
import os
import re
import shutil
import subprocess
import sys
from urllib.parse import quote

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "lib"))
import changemap  # noqa: E402 — 変更の地図と手元の木の部品。/what-am-i-doing と共用
from stance import stance  # noqa: E402 — 立場の判定。/what-am-i-doing と共用
import outfile  # noqa: E402 — 報告をファイルへ逃がす共通部。/whose-turn と共用
from ghcli import GH_TIMEOUT_SEC, gh  # noqa: E402 — gh を呼ぶ共通部。/whose-turn と共用
from ghtext import DONE_NOT_RED, is_bot, mentioned, refs  # noqa: E402 — 発言の読み方。/whose-turn と共用
import turn  # noqa: E402 — PR のターンの持ち主と指摘対応の判定。/whose-turn と共用
import catchup_html  # noqa: E402 — 報告を 1 枚の HTML に描く部品（--render と --setup）

# Windows では stdio が locale 既定の code page になり(GitHub Actions windows-latest で
# cp1252 を実測。日本語 Windows なら cp932)、日本語の出力が UnicodeEncodeError で落ちる。
# 報告そのものが日本語なので、落ちるとツールが丸ごと使えない。UTF-8 に固定する
for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

# CheckRun.conclusion / StatusContext.state のうち、赤ではないもの。未知の値は赤に倒す
# （CI の結論は増える。知らない値を緑に倒すと、増えた瞬間に検査が黙って甘くなる）
GREEN = DONE_NOT_RED

# API の値をそのまま出さず、中身を先に書いて括弧で原語を添える。戻ってきた人が読む報告で
# REVIEW_REQUIRED と書かれても、承認が無いのか承認が要らないのかは読み取れない。原語を残すのは
# grep で追えるようにするためで、消すと GitHub の画面や他のツールの出力と突き合わせられなくなる
APPROVAL = {
    "REVIEW_REQUIRED": "まだ承認されていない（REVIEW_REQUIRED）",
    "CHANGES_REQUESTED": "要修正が付いている（CHANGES_REQUESTED）",
    "APPROVED": "承認済み（APPROVED）",
    # null は「まだ誰もレビューしていない」だけでなく、承認の規則が無い base でも返る（そこでは承認しても null のまま）
    None: "承認・要修正の判定なし（reviewDecision なし——まだ誰もレビューしていないか、承認の規則が無い base。"
          "後者では承認しても付かない）",
}

MERGEABLE = {
    "MERGEABLE": "衝突なし（MERGEABLE）",
    "CONFLICTING": "衝突あり。解消しないと入らない（CONFLICTING）",
    "UNKNOWN": "GitHub が判定中（UNKNOWN）",
}

# 出来事の種別。spoken だけが「発言」で、依頼を探す範囲の切れ目になる。push は痕跡だが返事ではない
SPOKEN, PUSH, EVENT = "spoken", "push", "event"


# QUERY の requestEvents の窓。formal_state はこの中しか見ない
REQUEST_WINDOW = 100


def query(assignees):
    return """
query($owner:String!,$name:String!,$num:Int!){
  repository(owner:$owner,name:$name){
    issueOrPullRequest(number:$num){
      __typename
      ... on PullRequest {
        number title url state isDraft createdAt body
        headRefName headRepository{nameWithOwner} baseRefOid headRefOid
        maintainerCanModify baseRepository{defaultBranchRef{name}}
        baseRefName isCrossRepository
        baseRef{name associatedPullRequests(last:5){totalCount nodes{number title state reviewDecision
          isCrossRepository author{login}}}}
        suggestedReviewers{isAuthor isCommenter reviewer{login}}
        additions deletions changedFiles mergeable reviewDecision
        files(first:100){totalCount nodes{path changeType additions deletions}}
        author { __typename login }
        """ + assignees + """
        reviewRequests(first:20){nodes{requestedReviewer{__typename
          ... on User{login} ... on Team{name}}}}
        closingIssuesReferences(first:10){nodes{number title state url body}}
        comments(last:100){totalCount nodes{createdAt body author{__typename login}}}
        reviews(last:60){totalCount nodes{submittedAt state body author{__typename login}
          commit{oid}}}
        latestReviews(first:100){nodes{author{__typename login}}}
        """ + turn.OPINIONS + """
        reviewThreads(last:80){totalCount nodes{isResolved isOutdated path line diffSide
          comments(first:60){nodes{createdAt body url author{__typename login} originalCommit{oid}}}}}
        allCommits: commits(last:100){totalCount nodes{commit{
          oid committedDate messageHeadline additions deletions parents{totalCount}
          author{user{login} name email} committer{user{login}}}}}
        head: commits(last:1){nodes{commit{oid statusCheckRollup{contexts(first:100){
          totalCount nodes{__typename
            ... on CheckRun{name conclusion status detailsUrl}
            ... on StatusContext{context state targetUrl}}}}}}}
        requestEvents: timelineItems(last:100, itemTypes:[REVIEW_REQUESTED_EVENT]){
          pageInfo{hasPreviousPage} nodes{__typename
            ... on ReviewRequestedEvent{createdAt actor{login}
              requestedReviewer{__typename ... on User{login} ... on Team{name}}}}}
        timelineItems(last:100, itemTypes:[ASSIGNED_EVENT,
            READY_FOR_REVIEW_EVENT, CONVERT_TO_DRAFT_EVENT, CROSS_REFERENCED_EVENT]){
          nodes{__typename
            ... on AssignedEvent{createdAt actor{login} assignee{... on User{login}}}
            ... on ReadyForReviewEvent{createdAt actor{login}}
            ... on ConvertToDraftEvent{createdAt actor{login}}
            ... on CrossReferencedEvent{createdAt source{__typename
              ... on PullRequest{number title state url}
              ... on Issue{number title state url}}}}}
      }
      ... on Issue {
        number title url state createdAt body
        author { __typename login }
        """ + assignees + """
        labels(first:20){nodes{name}}
        comments(last:100){totalCount nodes{createdAt body author{__typename login}}}
        timelineItems(last:100, itemTypes:[ASSIGNED_EVENT, CROSS_REFERENCED_EVENT]){
          nodes{__typename
            ... on AssignedEvent{createdAt actor{login} assignee{... on User{login}}}
            ... on CrossReferencedEvent{createdAt source{__typename
              ... on PullRequest{number title state url}
              ... on Issue{number title state url}}}}}
      }
    }
  }
}
"""


QUERY = query(turn.ASSIGNEES)
# assignedActors の無い GitHub（GHES）で取り直す形。assignee の種別は取れない
LEGACY_QUERY = query(turn.LEGACY_ASSIGNEES)


# ---- 取得 ------------------------------------------------------------------

# 外部コマンドを無制限に待たない（決着済みの規約 issue #5。隣の what-am-i-doing.py と同じ形）。gh の秒は lib/ghcli.py
GIT_TIMEOUT_SEC = 20


def local_email():
    """手元の git config の user.email（小文字）。GitHub の login に結び付いていない commit を
    自分のものと見分けるのに使う。git が無い・未設定なら空文字で、その場合は照合しない。"""
    exe = shutil.which("git")
    if not exe:
        return ""
    try:
        r = subprocess.run([exe, "config", "--get", "user.email"],  # noqa: S603 — git は which で解決
                           capture_output=True, encoding="utf-8", errors="replace",
                           timeout=GIT_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        return ""   # 照合しないだけ。本体の報告は成り立つ
    return r.stdout.strip().lower() if r.returncode == 0 else ""


# 焦点の語。番号の後ろに付けると、末尾の材料をその 1 つに絞る（付けなければ有るものを全部）。
# 内部のキー（threads / map / ci）そのものでも受ける——日本語の語だけだと英語で使う人が絞れない。
# 大文字小文字は問わない。表示は FOCUS_LABELS の日本語の語
FOCUS_LABELS = {"threads": "指摘", "map": "地図", "ci": "CI"}
FOCUS = {**{k: k for k in FOCUS_LABELS}, **{v.lower(): k for k, v in FOCUS_LABELS.items()}}
URL_RE = re.compile(r"https?://[^/]+/([^/]+)/([^/]+)/(?:pull|issues)/(\d+)")


def split_words(words):
    """引数の語を (対象, 焦点の集合) に分ける。対象が無ければ今のブランチ（this）。
    焦点だけを渡した `catchup 指摘` も、今のブランチの指摘として通る。"""
    focus, rest = set(), []
    for w in words:
        key = FOCUS.get(w.lower())
        if key:
            focus.add(key)
        else:
            rest.append(w)
    if len(rest) > 1:
        sys.exit(f"対象は 1 つだけ渡す（受け取った値: {' '.join(rest)}）")
    return (rest[0] if rest else "this"), focus


def focus_words(focus):
    """焦点の内部 key（threads / map / ci）を人の語（指摘・地図・CI）に戻して「・」で繋ぐ。"""
    return "・".join(FOCUS_LABELS[k] for k in FOCUS_LABELS if k in focus)


def pick_tails(is_pr, focus, has_threads, has_red):
    """末尾に付ける材料 (地図, 指摘, CI) を決める。有れば出す——地図は PR なら常に、指摘は人が
    入っている未解決スレッドが有れば、CI は赤が有れば。作者が私かどうかは見ない（このツールを呼ぶこと
    自体が、自分の PR でも中身を忘れている印）。焦点を付けたときはその材料だけで、無くても出して
    「無い」と言わせる——黙って落とすと、絞った側が「出なかった」のか「無かった」のか分からない。
    issue には何も無い。"""
    if not is_pr:
        return False, False, False
    if focus:
        return "map" in focus, "threads" in focus, "ci" in focus
    return True, has_threads, has_red


# ブランチ名の日付（release/2026-10-30・hotfix/2026-10・backup-20261030）。年を issue の番号に読むと、関係の無い
# #2026 の報告を出すか「#2026 が無い」で止まる
DATE_IN_BRANCH = re.compile(r"(?<!\d)(?:19|20)\d{2}(?:[-_.](?:0[1-9]|1[0-2])(?:[-_.](?:0[1-9]|[12]\d|3[01]))?"
                            r"|(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01]))(?!\d)")


def branch_number(branch):
    """ブランチ名の中の issue / PR 番号。区切り（/ _ -）に挟まれた数字だけを取る——`python3.12` の
    12 や `node-20.x` の 20 を番号にしない。1 桁も通す（issue-9）。日付（DATE_IN_BRANCH）は番号にしない。無ければ None。"""
    m = re.search(r"(?:^|[/_-])#?(\d+)(?=[/_-]|$)", DATE_IN_BRANCH.sub("/", branch or ""))
    return int(m.group(1)) if m else None


def current_pr_url():
    """今のブランチの PR の URL。無ければ ""。gh が無い・未認証・失敗は止まる——「PR が無い」に潰すと、
    認証切れのときに「今のブランチに PR は無い」と断定した報告が出る（突合で実測）。GitHub の remote が
    無いリポジトリだけは PR が有り得ないので「無い」と同じに扱う（手元だけの repo でも this が使える）。"""
    exe = shutil.which("gh")
    if not exe:
        sys.exit("gh が見つからない（PATH に通す）")
    try:
        r = subprocess.run(  # noqa: S603 — gh は which で解決。引数はリテラルだけ
            [exe, "pr", "view", "--json", "url", "-q", ".url"],
            capture_output=True, encoding="utf-8", errors="replace", timeout=GH_TIMEOUT_SEC)
    except subprocess.TimeoutExpired:
        sys.exit(f"gh pr view が {GH_TIMEOUT_SEC} 秒で返らない")
    if r.returncode == 0:
        return r.stdout.strip()
    err = r.stderr.strip()
    # no git remotes found / none of the git remotes（remote 無し）、not on any branch（detached）は PR が有り得ない
    if ("no pull requests found" in err or "git remotes" in err or "not on any branch" in err
            or "could not determine current branch" in err):
        return ""
    sys.exit("gh pr view が失敗（今のブランチに PR が無いのとは別。理由: " + err + "）")


# 両端は . を含んでよい（v1.2.0 のタグ・release/1.2 のブランチ）。ref の名前に .. は使えないので、最初の .. が区切り
RANGE_RE = re.compile(r"^(?P<a>\S+?)(?P<sep>\.\.\.?)(?P<b>\S+)$")


def resolve_range(token, cwd=None):
    """`A..B` / `A...B` の両端が手元の commit に解ければ "oidA..oidB"（`...` は merge-base から）。違えば None。
    会話の話題がこのセッションの commit 数件に結び付いているとき（「今の修正」）、AI が
    `<一番古い sha>^..<一番新しい sha>` で呼ぶ口。"""
    m = RANGE_RE.match(token)
    if not m:
        return None
    a, b = changemap.commit_oid(m["a"], cwd), changemap.commit_oid(m["b"], cwd)
    if not (a and b):
        return None
    if m["sep"] == "...":
        a = (changemap.git("merge-base", a, b, cwd=cwd) or "").strip()
        if not a:
            return None
    return f"{a}..{b}"


def resolve_target(token, repo_opt):
    """番号・URL・this から (owner, name, number, 今のブランチとの関係) を決める。関係は None
    （番号や URL で呼んだ）／"pr"（今のブランチの PR）／"branch"（PR が無く、ブランチ名の番号を
    issue と見た。chore/1513-fold-remainders → #1513）／"none"（PR も番号も無い。GitHub 側の材料は
    無く、手元のブランチだけを出す——止めると、main で書きかけの人に何も返らない）。URL なら -R は要らない。"""
    m = URL_RE.match(token)
    if m:
        return m.group(1), m.group(2), int(m.group(3)), None
    local = None
    if token == "this":
        url = current_pr_url()
        m = URL_RE.match(url)
        if m:
            return m.group(1), m.group(2), int(m.group(3)), "pr"
        branch = changemap.current_branch() or ""
        num = branch_number(branch)
        if num is None:
            return None, None, None, "none"
        token, local = str(num), "branch"
    digits = token.lstrip("#").isdigit()
    if ".." in token:
        # ブランチの名前に .. は使えない（git の禁則）ので、範囲としてだけ読む
        rng = resolve_range(token)
        if rng:
            return None, None, rng, "range"
        sys.exit(f"範囲 {token} の両端が手元の commit に解けない（A..B の A と B は sha・HEAD~n・タグ・ブランチ名）")
    if not digits and changemap.branch_exists(token):
        return None, None, token, "branchname"
    # 数字だけの語は番号が先。ただし 7 桁以上（PR / issue の番号はそこまで行かない）で手元の commit に
    # 解けるなら短縮 sha（git log --oneline の 7 桁は 3 本に 1 本ほどが全数字。実測 113 本中 6 本）
    if not digits or (len(token) >= 7 and not token.startswith("#")):
        oid = changemap.commit_oid(token)
        if oid:
            return None, None, oid, "commit"
    if not digits:
        sys.exit(f"番号か PR / issue の URL、手元の commit を渡す（受け取った値: {token}。"
                 "引数なしか this なら今のブランチ、番号でない語は会話の話題として"
                 " what-am-i-doing.py --topic で追う）")
    slug = repo_opt or gh("repo", "view", "--json", "nameWithOwner",
                          "-q", ".nameWithOwner").strip()
    if "/" not in slug:
        sys.exit("リポジトリを特定できない（-R owner/repo を渡すか、リポジトリ内で実行する）")
    owner, name = slug.split("/", 1)
    return owner, name, int(token.lstrip("#")), local


def fetch(owner, name, num):
    """assignedActors の無い GitHub では種別なしで取り直し、assigneeKindsUnknown の印を付ける——止めると、
    その GitHub では /catchup が丸ごと走らない"""
    def ask(q):
        return json.loads(gh("api", "graphql", "-f", "query=" + q, "-f", "owner=" + owner,
                             "-f", "name=" + name, "-F", "num=%d" % num, graphql_errors=True))
    data = ask(QUERY)
    legacy = turn.missing_only(data.get("errors"), {turn.KINDS_FIELD})
    if legacy:
        data = ask(LEGACY_QUERY)
    if data.get("errors"):
        sys.exit("GraphQL エラー: " + json.dumps(data["errors"], ensure_ascii=False))
    node = data["data"]["repository"]["issueOrPullRequest"]
    if not node:
        sys.exit(f"{owner}/{name} に #{num} が無い")
    if legacy:
        node["assigneeKindsUnknown"] = True
    return node


# ---- 整形の補助関数 ------------------------------------------------------------


def ts(raw):
    return dt.datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone()


def hhmm(t):
    return t.strftime("%m-%d %H:%M")


def excerpt(body, limit, keep_quotes=False):
    """本文を 1 行に畳む。引用（>）は落とす——引用だけの返信が自分の発言に化けるため。--full で出すときは
    keep_quotes で残す（GitHub の alert 記法 `> [!CAUTION]` のように引用行だけの発言は、落とすと --full でも
    「本文なし」になり、機械が約束した「発言の全文。--full で出る」が嘘になる。実走で実測）。"""
    lines = (body or "").splitlines() if keep_quotes else unquoted_lines(body)
    s = re.sub(r"\s+", " ", " ".join(lines)).strip()
    if limit and len(s) > limit:
        return s[:limit] + "…"
    return s or "（本文なし）"


def login_of(actor):
    return (actor or {}).get("login") or "（不明）"


def thread_where(th):
    """スレッドの場所（path:行。行が無ければ path だけ）。削除された行への指摘（diffSide が LEFT）は、行番号が base の版の
    物なので、そう添える（head の同じ番号の行を開くと別のコードを読む）"""
    left = th.get("left") or th.get("diffSide") == "LEFT"
    return th["path"] + (f":{th['line']}" if th["line"] else "") + ("（削除された側。base の版の行）" if left and th["line"] else "")


def unquoted_lines(body):
    """発言の行から引用（>）を落とした列。"""
    return [ln for ln in (body or "").splitlines() if not ln.lstrip().startswith(">")]


def their_lines(body):
    """指摘の相手の発言の全文の行。引用は落とすが、引用行だけの発言（GitHub の alert 記法 `> [!NOTE]`）は落とさずに
    そのまま（落とすと本文が空のまま出る。excerpt の keep_quotes と同じ理由）。空行しか残らないときも同じ。"""
    kept = unquoted_lines(body)
    return kept if any(ln.strip() for ln in kept) else (body or "").splitlines()


def threads_awaiting(node, me):
    """未解決スレッドのうち、私が返すターンのもの。判定は unresolved_threads の my_turn そのもの（bot の発言は数えない。
    自分の件で私がまだ入っていない新しい指摘も数える——指摘の一覧で「私が返すターン」と出る物を 1 行目の理由から落とさない）。"""
    return [th for th in unresolved_threads(node, me) if th["my_turn"]]


# ---- 出来事の並び ------------------------------------------------------------


def collect_events(node, me, my_email=""):
    """全部の発言・push・受け渡しを 1 本の時系列にする。基準探しも表示もこれを使う。

    戻り値は (出来事, 参照, 結び付き無し)。参照（他の PR / issue がこの番号を書いた）は出来事に
    混ぜない——この件の状態を変えないのに表示枠を食う。my_email は手元の git config の
    user.email（小文字）で、login に結び付いていない commit をこれで自分のものと見分ける。
    結び付き無しは、それでも誰のものか決められなかった commit の author 名（申告用）。"""
    ev, refs, unlinked = [], [], set()

    def add(t, who, kind, text, cat, bot=False, oid=None, key=None, to=None, resolved=None):
        # kind は表示の語で、判定には使わない。判定は key（言語に依らない種類）・to（受け渡しの宛先の login）・
        # resolved（スレッドが解決済みか）で見る。表示の語を比べると、文言を直すと黙って判定が変わる。
        # oid は出来事が指す commit（レビューは提出時の head、スレッドの最初の発言は付けた時点の commit、
        # push はその commit）。「私の痕跡以降に変わった file」の基準になる。本文コメントとスレッドへの
        # 返信には無い——返信の originalCommit は元の発言の commit を継ぐので、返信の時点を指さない
        ev.append({"t": ts(t), "who": who, "kind": kind, "text": text,
                   "bot": bot, "cat": cat, "oid": oid, "key": key, "to": to, "resolved": resolved})

    for c in node["comments"]["nodes"]:
        add(c["createdAt"], login_of(c["author"]), "コメント", c["body"], SPOKEN,
            is_bot(c["author"]), key="comment")

    for r in node.get("reviews", {}).get("nodes", []):
        # 未送信（PENDING）は submittedAt が null で、相手にも届いていない。時系列には入れず
        # 「止めているもの」側で自分の宿題として扱う
        if r["state"] == "PENDING" or not r["submittedAt"]:
            continue
        label = {"APPROVED": "レビュー（承認）",
                 "CHANGES_REQUESTED": "レビュー（要修正）"}.get(r["state"], "レビュー")
        add(r["submittedAt"], login_of(r["author"]), label, r["body"], SPOKEN,
            is_bot(r["author"]), oid=(r.get("commit") or {}).get("oid"), key="review")

    for th in node.get("reviewThreads", {}).get("nodes", []):
        state = "解決済" if th["isResolved"] else "未解決"
        for k, c in enumerate(th["comments"]["nodes"]):
            add(c["createdAt"], login_of(c["author"]), f"スレッド {thread_where(th)}（{state}）",
                c["body"], SPOKEN, is_bot(c["author"]),
                oid=(c.get("originalCommit") or {}).get("oid") if k == 0 else None,
                key="thread", resolved=bool(th["isResolved"]))

    for n in node.get("allCommits", {}).get("nodes", []):
        c = n["commit"]
        actor = c.get("author") or {}
        who = (actor.get("user") or {}).get("login")
        if not who:
            name, email = (actor.get("name") or "（不明）"), (actor.get("email") or "").lower()
            if my_email and email == my_email:
                who = me
            else:
                who = name
                unlinked.add(name)
        # 私の commit を他の人が rebase して push すると、作者は私のまま committedDate だけ新しくなる。それを私の push
        # に数えると「私が最後にしたこと」が rebase の時刻へ進み、その間の相手の発言が「その後」から消える。committer
        # が私でない人なら、その人の push にする（web-flow は GitHub の画面で私が出した commit。提案の取り込みなど）
        pusher = ((c.get("committer") or {}).get("user") or {}).get("login")
        if who == me and pusher and pusher not in (me, "web-flow"):
            who = pusher
        add(c["committedDate"], who, "push",
            f"{c['oid'][:9]} {c['messageHeadline']} (+{c['additions']}/-{c['deletions']})",
            PUSH, oid=c["oid"], key="push")

    # 依頼の出来事は他の出来事と窓を取り合わないよう別に取る（QUERY の requestEvents）
    for it in node.get("requestEvents", {}).get("nodes", []):
        r = it.get("requestedReviewer") or {}
        to = reviewer_name(r) if is_person(r) else f"{r.get('__typename') or '（不明）'}（依頼に数えない）"
        add(it["createdAt"], login_of(it.get("actor")), "レビュー依頼", "→ " + to, EVENT,
            key="review_request", to=r.get("login") if is_person(r) else None)

    for it in node.get("timelineItems", {}).get("nodes", []):
        k = it["__typename"]
        if k == "AssignedEvent":
            add(it["createdAt"], login_of(it.get("actor")), "担当",
                "→ " + login_of(it.get("assignee")), EVENT,
                key="assign", to=(it.get("assignee") or {}).get("login"))
        elif k == "ReadyForReviewEvent":
            add(it["createdAt"], login_of(it.get("actor")), "下書き解除", "", EVENT, key="ready")
        elif k == "ConvertToDraftEvent":
            add(it["createdAt"], login_of(it.get("actor")), "下書きへ戻す", "", EVENT, key="draft")
        elif k == "CrossReferencedEvent":
            s = it.get("source") or {}
            if s.get("number"):
                refs.append({"t": ts(it["createdAt"]),
                             "text": f"#{s['number']} {s.get('title', '')}"})

    ev.sort(key=lambda e: e["t"])
    refs.sort(key=lambda e: e["t"])
    return ev, refs, sorted(unlinked)


def find_anchor(ev, node, me):
    """「私が最後にしたこと」を決める。戻り値は (出来事 or None, 種別)。種別は
    mine（私の痕跡）/ handover（私に渡された時点）/ created（作成時）。

    自分の痕跡 → 自分に渡された時点 → 作成時、の順に落とす。渡された時点まで落とすのは、
    まだ一度も触っていない件（依頼が来たきり）でも「何がいつ自分に来たか」は思い出す助けに
    なるため。ここを作成時に直行させると、依頼の存在が出力から消える。"""
    mine = [e for e in ev if e["who"] == me and e["cat"] in (SPOKEN, PUSH)]
    if mine:
        return mine[-1], "mine"

    handover = []
    for e in ev:
        if e["key"] in ("review_request", "assign") and e["to"] == me:
            handover.append(e)
        elif e["cat"] == SPOKEN and mentioned(e["text"], me):
            handover.append(e)
    if handover:
        return handover[-1], "handover"
    return None, "created"


def last_spoken(ev, me):
    """私の最後の発言（push は含まない）。私宛の依頼を探す範囲はここで切る。"""
    mine = [e for e in ev if e["who"] == me and e["cat"] == SPOKEN]
    return mine[-1] if mine else None


# ---- 状態 --------------------------------------------------------------------


def check_state(node):
    """head commit のチェックを ([(赤の名前, URL)], 実行中の数, 緑の数) に畳む。"""
    heads = node.get("head", {}).get("nodes", [])
    rollup = (heads[0]["commit"].get("statusCheckRollup") if heads else None)
    if not rollup:
        return [], 0, 0
    red, running, green = [], 0, 0
    for c in rollup["contexts"]["nodes"]:
        if c["__typename"] == "CheckRun":
            if c["status"] != "COMPLETED":
                running += 1
            elif c["conclusion"] in GREEN:
                green += 1
            else:
                red.append((c["name"], c.get("detailsUrl") or ""))
        else:
            if c["state"] in ("PENDING", "EXPECTED"):
                running += 1
            elif c["state"] == "SUCCESS":
                green += 1
            else:
                red.append((c["context"], c.get("targetUrl") or ""))
    return red, running, green


def role_of(node, me, ev):
    """この件での私の立場。判定は lib/stance.py（/what-am-i-doing と共用）で、ここは GraphQL の
    node から素の値を取り出すだけ。"""
    is_pr = node["__typename"] == "PullRequest"
    requested = [r.get("login") for r in requested_reviewers(node)] if is_pr else []
    reviewed = is_pr and (
        any(login_of(r["author"]) == me for r in node["reviews"]["nodes"])
        or any(login_of(c["author"]) == me
               for th in node["reviewThreads"]["nodes"] for c in th["comments"]["nodes"]))
    return stance(me, login_of(node["author"]), is_pr, requested, reviewed,
                  [a["login"] for a in node["assignees"]["nodes"]],
                  any(e["who"] == me and e["cat"] == SPOKEN for e in ev))


def my_turn(node, me, red):
    """「なぜ今それが私の番なのか」を機械で列挙する。空なら私の番ではない。

    理由を出すのは、ターンだけ告げられても戻れないため——戻ったときに要るのは、自分が何を
    期待されているかの中身の方である。持ち主（作者か、作者から渡された担当）の分は reason_table が決める。"""
    reasons = []
    if node["__typename"] == "PullRequest":
        if any(r.get("login") == me for r in requested_reviewers(node)):
            reasons.append("レビュー依頼が私に来ている")
        if any(r["state"] == "PENDING" and login_of(r["author"]) == me
               for r in node["reviews"]["nodes"]):
            reasons.append("書きかけのレビューが未送信（相手には届いていない）")

        waiting = sum(1 for _ in threads_awaiting(node, me))
        if waiting:
            reasons.append(f"未解決スレッド {waiting} 件で相手が返している（私が返すターン）")
    return reasons + reason_table(node, red).get(me, [])


ASSIGNED = "私が担当（assignee）"


def reason_table(node, red):
    """形式上の理由の表 {login: [理由]}。見る人に依らない——my_turn は自分の分を、waiting_on は待ち先を読む。

    持ち主は /whose-turn と同じ turn.owners: 作者が自分を入れずに人を assignee に付けた PR は、下書き・CI 赤・衝突・
    指摘対応・マージ・依頼先を決めるターンが担当へ移る。"""
    author = turn.login(node["author"])
    table = {}
    if node["__typename"] != "PullRequest":
        for a in (a["login"] for a in node["assignees"]["nodes"]):
            table.setdefault(a, []).append(ASSIGNED)
        return table
    holders = turn.owners(node)
    holder = "作者" if author in holders else "担当"
    owned = []
    if node["isDraft"]:
        owned.append("下書きのまま（渡すのは私）")
    if red:
        owned.append(f"CI 赤は{holder}（私）しか外せない")
    if node["mergeable"] == "CONFLICTING":
        owned.append(f"衝突の解消は{holder}（私）")
    # 変更要求を出した人全員に依頼し直していれば、ターンはレビュアー（#1843）
    if turn.owes_change_requests(node):
        owned.append("要修正が付いている（指摘対応は私）")
    elif node["reviewDecision"] == "APPROVED" and not requested_reviewers(node):
        owned.append("承認済みで依頼も残っていない（マージは私）")
    for o in holders:
        table.setdefault(o, []).extend(owned)
    kinds, asked = formal_state(node)
    for who, kind in kinds.items():
        if kind in ("unrequested", "review_requested"):
            # 誰にも渡していない PR は、渡すまで誰も動けない。ここを「待ち」に落とすと、
            # 自分が止めている件が相手のターンに見える
            table.setdefault(who, []).append("レビュー依頼が誰にも出ていない（依頼先を決めるのは私）")
        elif kind == "rerequest":
            table.setdefault(who, []).append(
                "作者以外の人のレビューが付き、依頼は残っていない（再依頼か指摘対応は私）" if asked else
                "作者以外の人のレビューが付いた。人宛のレビュー依頼を出した記録は無い（依頼先を決めるか指摘対応は私）")
    # 作者が assignee にもなっているのは普通の運用で、それだけではターンの理由にならない。持ち主でない assignee は、
    # 担当がターンの根拠
    for a in (a["login"] for a in node["assignees"]["nodes"]):
        if a != author and a not in holders:
            table.setdefault(a, []).append(ASSIGNED)
    return table


def is_person(reviewer):
    # Copilot などの Bot 宛の依頼は依頼に数えない（whose-turn.py と同じ）。QUERY は Bot に login を取らない
    # （GHES の古い版の RequestedReviewer には Bot が無く、fragment を書くとクエリごと落ちる）ので、login の有無で
    # 見分けると Bot 宛が名前の無い依頼先として残る
    return (reviewer or {}).get("__typename") in ("User", "Team")


def reviewer_name(reviewer):
    return reviewer.get("login") or reviewer.get("name")


def requested_reviewers(node):
    return [r["requestedReviewer"] for r in node["reviewRequests"]["nodes"]
            if is_person(r["requestedReviewer"])]


def request_window_cut(node):
    """依頼の出来事の窓（REQUEST_WINDOW 件）が埋まり、それより前が有りうるか。timelineItems の totalCount は
    itemTypes で絞る前の総数で比べられず、hasPreviousPage が絞った後の意味かは GitHub の文書に無い。どちらの意味でも
    偽なら前は無いので、件数と両方で見る。"""
    req = node.get("requestEvents") or {}
    return len(req.get("nodes", [])) >= REQUEST_WINDOW \
        and (req.get("pageInfo") or {}).get("hasPreviousPage") is not False


def formal_state(node):
    """今の依頼が無い PR を、人ごとに、もう渡したかで分けた {login: 分け方} と、人宛のレビュー依頼を出したか（asked）の組。
    対象外（issue・下書き・依頼が残る・要修正・承認済み）は ({}, None)。分け方のキーは、持ち主（turn.owners）に立つ
    依頼先を決めるターンの種別（turn.request_kind。/whose-turn と同じ判定で、rerequest・review_requested・
    unrequested）と、渡し終えた作者の assigned（依頼先を決めるのは担当で、作者のターンは無い）。
    今の依頼の一覧だけで見ないのは、レビューを送った人を GitHub が依頼から外すため（#1901）。レビューは人ごとの
    最新（latestReviews）から、依頼は依頼の出来事だけの窓（requestEvents）から読み、他の出来事と窓を取り合わない。"""
    if not (node["__typename"] == "PullRequest"
            and not node["isDraft"] and not requested_reviewers(node)
            and node["reviewDecision"] not in ("CHANGES_REQUESTED", "APPROVED")):
        return {}, None
    # 窓に無くても前が有りうるなら None。分け方は依頼していない側に倒し、見ていないものに読み違いを添える
    asked = any(is_person(it.get("requestedReviewer")) for it in node["requestEvents"]["nodes"]) \
        or (None if request_window_cut(node) else False)
    author = turn.login(node["author"])
    holders = turn.owners(node)
    kind = turn.request_kind(node, node["latestReviews"]["nodes"], asked)
    if author not in holders:
        return {author: "assigned", **{o: kind for o in holders}}, asked
    # 作者が持ち主のまま人へ渡した、まだ誰も依頼もレビューもしていない PR（assignee の種別が取れない GitHub）
    if kind == "unrequested" and turn.author_holds_handed(node):
        return {author: "assigned"}, asked
    return {author: kind}, asked


def shows_candidates(node, me):
    """依頼先の候補を出すか。依頼先を決める（決め直す）のが私の PR——誰にも渡していない・依頼がレビュー無しで外れた・
    人宛の依頼の記録が無いままレビューだけ付いた。my_turn の理由と、端末と HTML の候補が同じ述語を見る。"""
    kinds, asked = formal_state(node)
    kind = kinds.get(me)
    return kind in ("unrequested", "review_requested") or (kind == "rerequest" and not asked)


def request_cap_line(node, me):
    """依頼の出来事の窓が切れた PR の「見ていないもの」の 1 項（切れていなければ None）。私の分け方が、前に人へ
    依頼していれば変わるときだけ、その読み違いを添える（unrequested は、前に依頼していても review_requested と同じ
    出力なので添えない）。"""
    if not request_window_cut(node):
        return None
    kinds, asked = formal_state(node)
    kind = kinds.get(me)
    note = ""
    if asked is None and kind == "rerequest":
        note = "。前に人へ依頼していれば再依頼のターンで、出している依頼先の候補は要らない"
    elif asked is None and kind == "assigned" and turn.author_holds_handed(node):
        note = "。前に人へ依頼していれば、担当に渡したと分けたのは誤りで、依頼先を決めるのは私（依頼先の候補も出していない）"
    return (f"レビュー依頼の出来事の古い方（新しい {REQUEST_WINDOW} 件で窓が埋まり、それより前が有りうる。件数は"
            "読めない。Bot 宛の依頼もこの数に入る）。私宛の依頼がそこにだけあれば見落とす" + note)


def owner_cap_lines(node):
    """持ち主と指摘対応の判定が見ていないものの項。assignee の種別が取れない GitHub と、人ごとの意見が切れた要修正"""
    if node["__typename"] != "PullRequest":
        return []
    out = []
    author = turn.login(node["author"])
    if node.get("assigneeKindsUnknown") and any(a["login"] != author for a in node["assignees"]["nodes"]):
        out.append("assignee が人か Bot か（この GitHub は assignedActors を返さない。CI 赤・衝突・要修正・マージ・下書きの"
                   "ターンを担当へ移さず作者が持つ形で出した。Bot の assignee も人として数え、作者が assignee に入っていない"
                   "未依頼の PR は担当待ちと出した）")
    opinions = node["latestOpinionatedReviews"]
    if node["reviewDecision"] == "CHANGES_REQUESTED" and opinions["totalCount"] > len(opinions["nodes"]):
        out.append(f"人ごとの意見の残り {opinions['totalCount'] - len(opinions['nodes'])} 件（{opinions['totalCount']} 件中、"
                   f"{len(opinions['nodes'])} 件だけ取った）。変更要求の全員に依頼し直したかを見ずに、指摘対応を持ち主の"
                   "ターンとして出している")
    return out


def judge_cap_lines(node, me):
    """判定が見ていないものの項（依頼の出来事の窓と、持ち主・指摘対応の判定）。端末と HTML が同じ並びで使う。"""
    first = request_cap_line(node, me) if node["__typename"] == "PullRequest" else None
    return ([first] if first else []) + owner_cap_lines(node)


def waiting_on(node, me):
    """私の番でないときに待っている相手。PR は依頼先、無ければ形式上の理由を持つ人（持ち主を先に、次に返答できる
    作者）、それも無ければ担当がターンの根拠の人。担当の印だけで選ばない——作者が持ち主のまま担当を付けた PR（assignee の種別が
    取れない GitHub）で依頼先を決めるターンが作者にあるとき、作者本人には私の番と出しながら第三者には担当待ちと出す"""
    is_pr = node["__typename"] == "PullRequest"
    author = turn.login(node["author"])
    # 退会済みの作者は None で比べ、名前を出す所でだけ「（不明）」にする
    shown = login_of(node["author"])
    if is_pr:
        names = [reviewer_name(r) for r in requested_reviewers(node)]
        if names:
            return "レビュー待ち: " + ", ".join(names)
        table = reason_table(node, check_state(node)[0])
        owes = {p for p, rs in table.items() if any(r != ASSIGNED for r in rs)}
        who = [o for o in turn.owners(node) if o in owes] \
            or ([author] if turn.answerable(node["author"]) and author in owes else []) \
            or [a for a in turn.assigned_people(node) if table.get(a)]
        if who == [author]:
            return f"作者 {shown} 待ち"
        if who:
            return "担当 " + ", ".join(who) + " 待ち"
        if author != me:
            return f"作者 {shown} 待ち"
    elif author != me:
        return f"起票者 {shown} 待ち"
    return "待っている相手は記録に無い"


# ---- 積まれている先・依頼先の候補・私の痕跡以降に変わった file ----------------------
#
# どれも機械は事実だけ出す。取り込み先が既定ブランチでないこと、そのブランチに開いている PR、GitHub が
# 提案する依頼先、基準の commit より後に作者側が触った file。判断（積み直すか・誰に頼むか・どこを
# 読み直すか）は読む人か AI の側。

STACKED_SHOWN = 3        # 「上に積む」で名前を出す数。gh pr list は +1 件取って「他にもある」を言う
BASE_PRS_SHOWN = 3       # 取り込み先のブランチの PR を出す数（GraphQL は新しい方から 5 件と総数を取る）
SINCE_COMMIT_CAP = 20    # gh 経路で file を取る commit の上限（新しい方から）
SINCE_FILE_CAP = 20      # 変わった file を並べる行数の上限
GH_FILES_CAP = 300       # gh api の commits/{sha} が返す files の上限。ちょうど届いたら切れている
# gh api の files[].status を git の 1 文字に寄せる。無い値は頭文字（大文字）で出す
STATUS_LETTER = {"modified": "M", "added": "A", "removed": "D", "renamed": "R", "copied": "C",
                 "changed": "T", "unchanged": "U"}
COMMIT_FILES_JQ = ".files[]|[.status,.filename]|@tsv"
# suggestedReviewers の根拠 (isCommenter, isAuthor) → 添える語
SUGGESTED_WHY = {(True, True): "発言あり・commit 者", (True, False): "この PR に発言あり",
                 (False, True): "変更 file の commit 者", (False, False): ""}


def approval(decision):
    """reviewDecision の日本語。知らない値は生のまま出す（API の値を隠さない）。"""
    return APPROVAL.get(decision, str(decision))


def me_or(who, me):
    return "私" if who == me else who


def base_lines(node, me):
    """取り込み先が既定ブランチでない PR の、そのブランチとブランチの PR の行。既定と同じなら空。既定が分からなければ
    （baseRepository が無い）比べられないので空。fork からの同名のブランチの PR（isCrossRepository）は
    そのブランチの PR ではない。GraphQL は古い順なので新しい 5 件を取り、新しい順に並べる（長寿のブランチは同名の
    PR を何十件も持つ——最古の 5 件では今 open のものが窓に入らない。実測: release ブランチで 748 件）。"""
    base, default = node.get("baseRefName"), default_branch(node)
    if not base or not default or base == default:
        return []
    ref = node.get("baseRef")
    if ref is None:
        # ブランチが消えているので、そのブランチの PR は分からない（「無い」とは言えない）
        return [f"  取り込み先: {base}（ブランチは消えている）"]
    out = [f"  取り込み先: {base}（既定 {default} ではない）"]
    assoc = ref.get("associatedPullRequests") or {}
    fetched = assoc.get("nodes") or []
    prs = [p for p in reversed(fetched) if not p.get("isCrossRepository")][:BASE_PRS_SHOWN]
    total = assoc.get("totalCount") or len(fetched)
    for p in prs:
        out.append(f"  そのブランチの PR: #{p['number']} {p['state'].lower()}・{approval(p.get('reviewDecision'))}"
                   f"・作者 {me_or(login_of(p.get('author')), me)}")
    see = f"gh pr list --head {base} --state all で見る"
    if not prs:
        out.append("  そのブランチの PR: 無い" if not total else
                   f"  そのブランチの PR: 新しい {len(fetched)} 件は fork の同名のブランチの分（全 {total} 件。{see}）")
    elif total > len(prs):
        out.append(f"  （そのブランチの PR は他に {total - len(prs)} 件。fork の分も含む。{see}）")
    return out


def suggested_line(node):
    """GitHub が提案する依頼先（suggestedReviewers）と、提案の根拠。決めるのは私で、機械は選ばない。"""
    names = []
    for sg in node.get("suggestedReviewers") or []:
        why = SUGGESTED_WHY[(bool(sg.get("isCommenter")), bool(sg.get("isAuthor")))]
        names.append(login_of(sg.get("reviewer")) + (f"（{why}）" if why else ""))
    if not names:
        return "  依頼先の候補（GitHub の提案）: なし"
    return "  依頼先の候補（GitHub の提案。決めるのは私）: " + "、".join(names)


def commit_window(node):
    """allCommits の nodes（古い→新しい）と総数。last:100 なので、古い PR では nodes が総数より少ない。"""
    cs = node.get("allCommits") or {}
    nodes = [c["commit"] for c in cs.get("nodes", [])]
    return nodes, cs.get("totalCount") or len(nodes)


def since_base(anchor, node):
    """「私の痕跡以降」の基準の commit。(oid, 近似か) か None。痕跡が commit を指していれば（レビュー・
    スレッドの最初の発言・push）それを厳密に使う。本文コメントとスレッドへの返信には commit が無いので、
    その時刻以前の最新の commit で置く（近似。rebase や merge で前後していればずれる）。発言が取った
    commit の全部より前なら基準を置けない。"""
    if anchor.get("oid"):
        return anchor["oid"], False
    before = [c for c in commit_window(node)[0] if ts(c["committedDate"]) <= anchor["t"]]
    if not before:
        return None
    return before[-1]["oid"], True


def since_commits(node, base_oid):
    """基準より後ろの commit を allCommits の並び（古い→新しい）で切る。戻り値は (作者側の oid の列,
    取り込みの数, 基準が nodes に無いか)。parents が 2 つ以上の commit は取り込み（base の merge 等）で、
    file を取ると base 側の変更が全部混ざるので数だけ数える。基準が nodes に無いのは、履歴が書き換えられた
    （rebase / amend）か、窓（last:100）より古いか——どちらかは呼び手が総数で見分ける。"""
    cs, _ = commit_window(node)
    idx = next((i for i, c in enumerate(cs) if c["oid"] == base_oid), None)
    if idx is None:
        return [], 0, True
    after = cs[idx + 1:]
    authored = [c["oid"] for c in after if (c.get("parents") or {}).get("totalCount", 1) < 2]
    return authored, len(after) - len(authored), False


def latest_status(rows):
    """[(status の 1 文字, path)] を古い→新しいの順で重ね、path ごとに最後の status。並びは path 順。
    手元の git 経路と gh 経路が同じ合成を通る。"""
    files = {}
    for st, path in rows:
        files[path] = st
    return sorted((st, path) for path, st in files.items())


def local_range(owner, name, *oids):
    """手元がこのリポジトリの checkout で、oids の commit を全部持っていればそのルート。無ければ None。
    関数まるごとの diff（pr_function_diff）と痕跡以降の file（since_files_git）が同じ門を通る。"""
    top = local_checkout(owner, name)
    return top if top and all(changemap.has_commit(o, top) for o in oids) else None


def since_files_git(owner, name, base, head):
    """経路 1（手元）。基準と head の commit を持っていれば、作者側の commit（first-parent の非 merge）が
    触った file を git log 1 回で。持っていなければ None（gh 経路へ）。"""
    top = local_range(owner, name, base, head)
    if not top:
        return None
    out = changemap.git("-c", "core.quotePath=false", "log", "--first-parent", "--no-merges",
                        "--format=", "--name-status", f"{base}..{head}", cwd=top)
    if out is None:
        return None
    rows = [(r.split("\t")[0][:1], r.split("\t")[-1]) for r in out.splitlines() if "\t" in r and r[:1]]
    return latest_status(reversed(rows))  # log は新しい→古い


def gh_file_rows(text):
    """gh api commits/{sha} の TSV（status \t path）を [(status の 1 文字, path)] に。"""
    return [(STATUS_LETTER.get(r[0], r[0][:1].upper()), r[-1])
            for r in (row.split("\t") for row in text.splitlines() if "\t" in row)]


def since_files_gh(oids, get):
    """経路 2（gh）。commit ごとに get(sha)（gh api commits/{sha} の TSV。取れなければ None）を並列で呼び、
    file を合成する。戻り値は ([(status, path)], 300 件で切れた commit が有るか, 取れなかった commit の数)。
    oids は古い→新しい。"""
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(len(oids), SINCE_COMMIT_CAP))) as ex:
        texts = list(ex.map(get, oids))
    rows, cap300, failed = [], False, 0
    for text in texts:
        if text is None:
            failed += 1
            continue
        got = gh_file_rows(text)
        cap300 = cap300 or len(got) >= GH_FILES_CAP
        rows.extend(got)
    return latest_status(rows), cap300, failed


def collect_since(node, anchor, get_git, get_gh):
    """「私の痕跡以降に変わった file」の材料。anchor は私の痕跡（find_anchor の mine）。get_git(base, head)
    は手元の経路（無ければ None）、get_gh(sha) は gh の経路（1 commit の TSV か None）——検査で差し替える口。
    基準を置けなければ None。戻り値の dict は render_since と since_unseen が読む。"""
    nodes, total = commit_window(node)
    truncated = total > len(nodes)
    since = {"base": None, "approx": False, "rewritten": False, "outside": False,
             "window": (len(nodes), total), "commits": 0, "merges": 0, "skipped": 0, "files": [],
             "cap300": False, "failed": 0}
    found = since_base(anchor, node)
    if not found:
        if not truncated:
            return None  # 発言が最初の commit より前——全 file が対象で、材料として役に立たない
        since["outside"] = True  # 窓の中に基準を置けない。古い側に有るかは取っていない
        return since
    base, approx = found
    since.update(base=base[:7], base_oid=base, approx=approx)
    authored, merges, missing = since_commits(node, base)
    if missing:
        # 窓が切れていれば「取っていない」と「書き換え」を見分けられない。切れていなければ書き換え
        since["outside" if truncated else "rewritten"] = True
        return since
    since.update(commits=len(authored), merges=merges, authored=authored)
    if not authored:
        return since
    files = get_git(base, node.get("headRefOid"))
    if files is None:
        wanted = authored[-SINCE_COMMIT_CAP:]
        since["skipped"] = len(authored) - len(wanted)
        files, since["cap300"], since["failed"] = since_files_gh(wanted, get_gh)
    since["files"] = files
    return since


def render_since(since):
    """「私の痕跡以降に変わった file」のセクション。基準が窓の外か履歴に無ければ、その 1 行だけ。"""
    out = []
    w = out.append
    if since["outside"] or since["rewritten"]:
        w("## 私の痕跡以降に変わった file")
        got, total = since["window"]
        if since["outside"]:
            w(f"  基準（{since['base'] or '私の痕跡の時点'}）は取った新しい {got} 本より前（commit {total} 本中）。"
              "履歴の書き換えかどうかは分からず、古い方の commit は見ていない")
        else:
            w(f"  基準の commit {since['base']} は今の head の履歴に無い（履歴が書き換えられた）。"
              "git range-diff で見る")
        return out
    files = since["files"]
    w(f"## 私の痕跡以降に変わった file — {len(files)} 件（作者側の commit {since['commits']} 本。"
      f"取り込み {since['merges']} 本の分は含めない）"
      + ("（基準は commit の日付で置いた近似）" if since["approx"] else ""))
    for st, path in files[:SINCE_FILE_CAP]:
        w(f"  {st}  {path}")
    if len(files) > SINCE_FILE_CAP:
        w(f"  …ほか {len(files) - SINCE_FILE_CAP} file")
    if not files:
        w("  なし" + (f"（取り込み {since['merges']} 本だけ）" if since["merges"] else ""))
    if since["failed"]:
        w(f"  （commit {since['failed']} 本の file は取れなかった。gh api が失敗した）")
    return out


def since_unseen(since):
    """「見ていないもの」に足す行（先頭の「  - 」は呼び手が付ける）。窓の外・書き換えはセクションの行が言う。"""
    out = []
    if since["outside"] or since["rewritten"]:
        return out
    if since["approx"]:
        out.append("変わった file の基準は commit の日付で置いた近似。rebase や merge で前後していれば数件ずれる")
    if since["skipped"]:
        out.append(f"私の痕跡以降の古い方の commit {since['skipped']} 本の file（上限 {SINCE_COMMIT_CAP} 本）")
    if since["cap300"]:
        out.append(f"1 commit の file が {GH_FILES_CAP} 件で切れている")
    return out


def fetch_stacked(owner, name, node):
    """このブランチを base にする open PR（積まれている先）。fork の PR と既定ブランチ自身では探さない——
    fork のブランチは base リポジトリの --base に無く、既定ブランチを base にする PR は全部になる。gh が失敗すれば None（「積まれた PR は無い」の () と分ける）。"""
    if fork_of(node, owner, name) is not None or node.get("headRefName") == default_branch(node):
        return ()
    got = gh_try("pr", "list", "-R", f"{owner}/{name}", "--base", node["headRefName"],
                 "--state", "open", "--limit", str(STACKED_SHOWN + 1), "--json", "number,title")
    return None if got is None else tuple(json.loads(got))


# ---- 出力 --------------------------------------------------------------------


def find_ask(ev, node, me, cutoff, own):
    """最後に私へ向けられた依頼を 1 つ返す。cutoff より後だけを見る（None なら全期間）。

    自分の最後の発言だけでは戻れない——「相手が今その件で私に何を求めているか」が要る。
    メンション・レビュー依頼・私が返すターンの未解決スレッドを同じ土俵で見て、最も新しいものを取る。

    cutoff を None にできるのが要点。自分がまだ発言していない件では、依頼は「渡された時点」より
    前に来ていることがある（本文で頼まれた後にレビュー依頼ボタンが押される順序）。基準より後に
    限ると、その依頼が丸ごと消えて「依頼は来ていない」と出る（実測: レビュー依頼の 27 分前に
    本文で 3 点を名指しで委ねられていた PR で発生）。

    own（私が持っている自分の PR〔担当に渡していない〕/ 担当の issue）では、名指しの無い発言も最後の 1 件だけ拾う。自分の件への
    発言は宛先を書かないのが普通で（実測: 「main を取り込むと lint が赤になるので合わせて
    ほしい」が @ 無しで来ていた）、名指しだけを待つと丸ごと落ちる。unaddressed=True を付けて
    返し、表示側で「名指しは無い」と断る。拾うのは本文のある発言だけで、解決済みスレッドは
    見ない——本文なしの承認や、push で直して閉じたスレッドが「求められていること」に化ける。"""
    later = [e for e in ev if cutoff is None or e["t"] > cutoff]
    hits = [e for e in later if (
        (e["cat"] == SPOKEN and mentioned(e["text"], me) and not e["resolved"])
        or (e["key"] == "review_request" and e["to"] == me))]
    if hits:
        # 本文を持つ発言を、レビュー依頼ボタンより優先する。ボタンは中身が無く、押された順序も
        # 本文の依頼と前後する（本文で頼んでからボタンを押す運用が普通）。新しい方を機械的に
        # 取ると、実際の用件が書いてある方が消える
        spoken = [h for h in hits if h["cat"] == SPOKEN]
        chosen = spoken[-1] if spoken else hits[-1]
        buttons = [h for h in hits if h["cat"] != SPOKEN and h["t"] > chosen["t"]]
        if buttons:
            chosen = dict(chosen, followup=buttons[-1])
        return chosen

    # 名指しが無くても、私が返すターンの未解決スレッドに cutoff より後に相手が返していれば、それが依頼にあたる。
    # 新しい返事のものを取る。私がまだ入っていないスレッド（自分の件の新しい指摘）は名指しが無いと断る
    waiting = [th for th in threads_awaiting(node, me) if cutoff is None or ts(th["last"]["createdAt"]) > cutoff]
    if waiting:
        # 私が入っているスレッドの返事を、私がまだ入っていない新しい指摘より先に取る（名指しの無い方を取ると、私への
        # 返事が「求められていること」から消え、理由も「問いかは本文で確かめる」に弱まる）
        th = max(waiting, key=lambda th: (bool(th["mine_last"]), ts(th["last"]["createdAt"])))
        c = th["last"]
        ask = {"t": ts(c["createdAt"]), "who": login_of(c["author"]),
               "kind": f"スレッド {thread_where(th)}（未解決）", "text": c["body"],
               "bot": is_bot(c["author"]), "cat": SPOKEN,
               "key": "thread", "to": None, "resolved": False}
        return ask if th["mine_last"] else dict(ask, unaddressed=True)

    # スレッドの発言は上の threads_awaiting が私のターンかを決め終えているので、ここでは見ない。担当に渡した自分の
    # PR は担当のターンで（unresolved_threads・/whose-turn と同じ）、own が偽で来る（turn_reasons）
    if own:
        others = [e for e in later if e["cat"] == SPOKEN and e["key"] != "thread" and e["who"] != me
                  and not e["bot"] and not e["resolved"] and (e["text"] or "").strip()]
        if others:
            return dict(others[-1], unaddressed=True)
    return None


def turn_reasons(node, me, ev, red):
    """私の番の理由と、それを決めた材料。戻り値は (理由の列, 私宛の依頼か None, 私の最後の発言か None,
    名指しの無い発言も見たか〔自分の件を私が持っている〕)。
    端末の報告（render）と HTML の材料（page_item）が同じ式を通る。"""
    reasons = my_turn(node, me, red)
    spoke = last_spoken(ev, me)
    # 名指しの無い発言も私への依頼に読むのは、自分の件を私が持っているときだけ。担当に渡した自分の PR は担当のターン
    # で、名指しの無い発言を見ない。見ていないのに「私の件への発言も無い」と言わないよう、戻り値の 4 つ目もこれにする
    own = owns(node, me) and (node["__typename"] != "PullRequest" or me in turn.owners(node))
    ask = find_ask(ev, node, me, spoke["t"] if spoke else None, own)
    # 名指しで頼まれて返していない状態は、依頼ボタンも未解決スレッドも無いまま成立する。
    # 形式の信号が 1 つも立たないときの取りこぼしを、これで塞ぐ。他の理由があっても足す——
    # 別の事実で、片方だけ告げると依頼の存在が 1 行目から消える。名指しの無い発言（unaddressed）は
    # 問いかどうか機械では決められないが、自分の件で相手が最後に発言していれば少なくとも読むのは私
    if ask:
        reasons.append("私の件に相手の発言があり、その後に私は発言していない（問いかは本文で確かめる）"
                       if ask.get("unaddressed") else
                       "私宛の依頼が来ていて、その後に私は発言していない")
    return reasons, ask, spoke, own


def render(node, me, ev, refs, unlinked, anchor, anchor_kind, full, limit, caps,
           with_map=False, with_threads=False, with_ci=False, branch_lines=(),
           stacked=(), since=None):
    """branch_lines は --switch の結果（見出しの URL の行の後ろに足す。無ければ何も足さない）。
    stacked はこのブランチを base にする open PR の列（main() が gh pr list で取る。gh が失敗すれば None）、
    since は「私の痕跡以降に変わった file」（collect_since の戻り値。無ければ None）。ここは gh も
    git も叩かない——取得は全部 main() で済ませ、材料だけ受け取る。セクションは下の *_lines が 1 つずつ書き、
    出さないセクションは None を返す。"""
    is_pr = node["__typename"] == "PullRequest"
    red, running, green = check_state(node) if is_pr else ([], 0, 0)
    reasons, ask, spoke, own = turn_reasons(node, me, ev, red)
    anchor_t = anchor["t"] if anchor else ts(node["createdAt"])
    human = unresolved_threads(node, me) if is_pr else []
    sections = [
        head_lines(node, me, ev, reasons, branch_lines),
        last_done_lines(me, anchor, anchor_kind, anchor_t, full),
        asked_lines(me, ask, spoke, own, full),
        after_lines(me, ev, anchor_t, full, limit),
        render_since(since) if since is not None else None,
        state_lines(node, me, red, running, green, human),
        linked_lines(node, refs, stacked),
    ]
    out = []
    for lines in sections:
        if lines is not None:
            out.extend(lines)
            out.append("")
    out.extend(unseen_lines(node, me, caps, unlinked, ask, since, full, red, human,
                            with_map, with_threads, with_ci))
    return "\n".join(out)


def closing_issues(node):
    """PR が閉じる issue。issue なら空。"""
    if node["__typename"] != "PullRequest":
        return []
    return node.get("closingIssuesReferences", {}).get("nodes", [])


CHECKS = "CI のチェック"


def cap_text(label, total, got):
    # 上限は「何件切れたか」ではなく「それで何を見落としうるか」まで書く。件数だけでは、
    # 読む人がこの報告のどこを疑えばよいか分からない
    if label == CHECKS:
        return (f"{label}の残り {total - got} 件（{total} 件中、{got} 件だけ取った）。赤がそこにあれば見落とす"
                "（CI の判定は取った分だけで出している）")
    return (f"{label}の古い方 {total - got} 件（{total} 件中、新しい {got} 件だけ取った）。"
            "私の痕跡や私宛の依頼がそこにあれば見落とす")


def head_lines(node, me, ev, reasons, branch_lines):
    """見出し: 件名・立場と私の番か・件の種別と大きさ・URL・ブランチの行。"""
    is_pr = node["__typename"] == "PullRequest"
    author = login_of(node["author"])
    kind = "PR" if is_pr else "issue"
    out = []
    w = out.append
    w(f"# #{node['number']} {node['title']}")
    role = role_of(node, me, ev)
    # 理由が 1 つなら 1 行、複数なら箇条書き。／で繋ぐと 3 つで 100 字を超え、端末で折り返して
    # 1 行目の役目（一目でターンと理由）を失う。閉じた件は誰のターンでもない——merged の PR で「作者 待ち」と
    # 出すと読む人が迷う（実走で実測）
    if node["state"] != "OPEN":
        w(f"  {role} · 済み — " + ("merge 済み。動くものは無い" if node["state"] == "MERGED"
                                   else "close 済み。動くものは無い"))
    elif not reasons:
        w(f"  {role} · ○ 待ち — " + waiting_on(node, me))
    elif len(reasons) == 1:
        w(f"  {role} · ● 私の番 — " + reasons[0])
    else:
        w(f"  {role} · ● 私の番")
        for r in reasons:
            w(f"    - {r}")
    head = [f"{kind} {node['state'].lower()}"]
    if author != me:
        head.append(f"作者 {author}")
    if is_pr:
        if node["isDraft"]:
            head.append("下書き")
        head.append(f"{node['changedFiles']} ファイル "
                    f"+{node['additions']}/-{node['deletions']}")
    w("  " + " · ".join(head))
    w("  " + node["url"])
    # ブランチの行は URL の後ろ——スキルの文書は「URL は見出しの下の行から写す」で、行が下がるとずれる
    out.extend("  " + ln for ln in branch_lines)
    return out


def last_done_lines(me, anchor, anchor_kind, anchor_t, full):
    """「私が最後にしたこと」のセクション。"""
    out = []
    w = out.append
    w("## 私が最後にしたこと")
    if anchor_kind == "mine":
        w(f"  {hhmm(anchor['t'])}  {anchor['kind']}")
        w("  " + excerpt(anchor["text"], 0 if full else 220, keep_quotes=full))
    else:
        w("  この件で私はまだ何もしていない")
        if anchor_kind == "handover":
            w(f"  {hhmm(anchor['t'])}  {me_or(anchor['who'], me)} の {anchor['kind']} で私に渡された")
        else:
            w(f"  {hhmm(anchor_t)}  作成")
    return out


def asked_lines(me, ask, spoke, own, full):
    """「私に求められていること」のセクション。"""
    out = []
    w = out.append
    w("## 私に求められていること")
    if ask:
        note = "（名指しは無い。私の件への発言）" if ask.get("unaddressed") else ""
        w(f"  {hhmm(ask['t'])}  {me_or(ask['who'], me)} の {ask['kind']}{note}")
        # 依頼の抜粋だけ長めに取る。220 字だと結論の前で切れて用件が読めない（実測: 対象ファイルの
        # パスの途中で切れ、初見の読み手 2 人が「何を直せばよいか分からない」で止まった）
        w("  " + excerpt(ask["text"], 0 if full else 400, keep_quotes=full))
        f = ask.get("followup")
        if f:
            w(f"  （その後 {hhmm(f['t'])} に {me_or(f['who'], me)} が {f['kind']} を出している）")
    elif spoke:
        w(f"  私の最後の発言（{hhmm(spoke['t'])}）より後には無い"
          + ("（名指しも、私の件への発言も）" if own else ""))
    else:
        w("  無い")
    return out


def after_lines(me, ev, anchor_t, full, limit):
    """「その後に起きたこと」のセクション。--full でなければ新しい方から limit 件。"""
    out = []
    w = out.append
    after = [e for e in ev if e["t"] > anchor_t]
    shown = after if full else after[-limit:]
    w(f"## その後に起きたこと — {len(after)} 件"
      + ("" if len(shown) == len(after) else f"（新しい方から {len(shown)} 件だけ表示）"))
    if not after:
        w("  なし")
    for e in shown:
        who = f"{me_or(e['who'], me)} が " if e["who"] else ""
        tag = "[bot] " if e["bot"] else ""
        w(f"  {hhmm(e['t'])}  {tag}{who}{e['kind']}")
        body = excerpt(e["text"], 0 if full else 110, keep_quotes=full)
        if body != "（本文なし）":
            w(f"      {body}")
    return out


def ci_unseen(node):
    """head のチェックのうち、取得の上限で取れなかった数。"""
    heads = node.get("head", {}).get("nodes", [])
    rollup = heads[0]["commit"].get("statusCheckRollup") if heads else None
    conn = (rollup or {}).get("contexts") or {}
    return max(0, (conn.get("totalCount") or 0) - len(conn.get("nodes") or []))


def ci_summary(red, running, green, unseen=0):
    """CI の 1 行の値。端末の「いまの状態」と HTML の札が同じ文を使う。unseen は取得の上限で取れなかったチェックの数で、
    あれば取った分だけで「全 pass」と言い切らない（残りに赤があっても見えていない）。"""
    # チェックが 1 本も無い状態を「全 pass」と言うと、検査が無いことが緑に化ける
    if not (red or running or green):
        return "報告なし"
    if not (red or running):
        if unseen:
            return f"取った {green} 件は全 pass（残り {unseen} 件は見ていない）"
        return f"全 pass（緑 {green}）"
    parts = []
    if red:
        names = ", ".join(n for n, _ in red[:3]) + ("…" if len(red) > 3 else "")
        parts.append(f"赤 {len(red)} 件（{names}）")
    if running:
        parts.append(f"実行中 {running} 件")
    if green:
        parts.append(f"緑 {green}")
    if unseen:
        parts.append(f"見ていない {unseen} 件")
    return "／".join(parts)


def state_lines(node, me, red, running, green, human):
    """「いまの状態」のセクション。書く行が無ければ None。human は unresolved_threads の戻り値。"""
    is_pr = node["__typename"] == "PullRequest"
    state = []
    st = state.append
    if is_pr:
        st("  承認: " + approval(node["reviewDecision"])
           + " ／ 取り込み: " + MERGEABLE.get(node["mergeable"], str(node["mergeable"])))
        state.extend(base_lines(node, me))
        if shows_candidates(node, me):
            st(suggested_line(node))
        st("  CI: " + ci_summary(red, running, green, ci_unseen(node)))
        # 赤の行き先を出す。「CI 赤は作者しか外せない」と告げておいて理由への道が無いと、
        # 読む人は自分で探しに行くことになる
        for n, url in red[:3]:
            if url:
                st(f"      {n}  {url}")
        unresolved = [t for t in node["reviewThreads"]["nodes"] if not t["isResolved"]]
        # 「人が入っている」は指摘の材料と同じ数え方（私以外の人の発言があるもの）。私だけの
        # スレッドや bot だけのスレッドを数えると、本体の数字と末尾の材料が食い違う（実測）
        st(f"  未解決スレッド: {len(unresolved)} 件"
           f"（うち人が入っているもの {len(human)} 件）")
    else:
        labels = [lb["name"] for lb in node.get("labels", {}).get("nodes", [])]
        if labels:
            st("  ラベル: " + ", ".join(labels))
    assignees = [a["login"] for a in node["assignees"]["nodes"]]
    # 自分だけが担当の行は、1 行目の立場と重なるので出さない
    if any(a != me for a in assignees):
        st("  担当: " + ", ".join(me_or(a, me) for a in assignees))
    if not state:
        return None
    return ["## いまの状態"] + state


def linked_lines(node, refs, stacked):
    """「つながっている先」のセクション。閉じる issue・上に積む PR・参照のどれも無ければ None。"""
    linked = closing_issues(node)
    if not (linked or refs or stacked or stacked is None):
        return None
    out = []
    w = out.append
    w("## つながっている先")
    for i in linked:
        w(f"  閉じる  #{i['number']} {i['state'].lower()}  {i['title']}")
    if stacked is None:
        w(f"  上に積む  （gh pr list --base {node.get('headRefName')} が失敗して読めなかった）")
    for s in (stacked or ())[:STACKED_SHOWN]:
        w(f"  上に積む  #{s['number']} {s['title']}")
    if stacked and len(stacked) > STACKED_SHOWN:
        # gh pr list は STACKED_SHOWN + 1 件までしか取っていないので、残りの数は言えない
        w(f"  （上に積む PR は他にもある。gh pr list --base {node.get('headRefName')} で見る）")
    # 参照は新しい 3 件だけ。5 件出したら初見の読み手 3 人中 2 人が「読まなくてよかった」と言った。
    # 残すのは、この PR から分かれた後続の PR がここに出るため
    for r in refs[-3:]:
        w(f"  参照    {hhmm(r['t'])}  {r['text']}")
    if len(refs) > 3:
        w(f"  （参照は他に {len(refs) - 3} 件）")
    return out


def unseen_lines(node, me, caps, unlinked, ask, since, full, red, human,
                 with_map, with_threads, with_ci):
    """報告の最後の「見ていないもの:」。後ろに空行を付けない。"""
    is_pr = node["__typename"] == "PullRequest"
    kind = "PR" if is_pr else "issue"
    out = []
    w = out.append
    w("見ていないもの:")
    for cap in caps:
        w("  - " + cap_text(*cap))
    for line in judge_cap_lines(node, me):
        w("  - " + line)
    w("  - GitHub の外（チャット・口頭・メール）でのやり取り")
    if is_pr:
        # 有るのに末尾に無い材料（焦点で他に絞ったとき）は、出す口を添える
        w(("  - diff の全文（下の地図は置き場所と骨組みと抜粋。gh pr diff で見る）" if with_map
           else "  - diff の中身（gh pr diff で見る。地図 を付けて呼ぶと末尾に出る）")
          + ("、CI が落ちた理由（上の URL か gh pr checks で見る）。CI を付けて呼ぶと末尾に出る"
             if red and not with_ci else ""))
        if with_threads and human:
            w("  - スレッドの経緯（下の指摘は相手の最後の発言と、その行の前後だけ）")
        elif human:
            w("  - 未解決スレッドの中身（指摘 を付けて呼ぶと末尾に出る）")
    if since is not None:
        out.extend("  - " + ln for ln in since_unseen(since))
    # 本文は末尾の材料に出る。上限で切れた分だけ申告する
    cut = 0 if full else max(0, len(body_rows(node.get("body"))) - BODY_CAP)
    if cut:
        w(f"  - 本文の残り {cut} 行（--full か gh {kind.lower()} view で見る）")
    if unlinked:
        w(f"  - GitHub の login に結び付いていない commit（名前: {', '.join(unlinked)}）が誰のものか。"
          "自分のものなら「私が最後にしたこと」は実際より古い（手元の git config の user.email と"
          "一致すれば私の push と数える）")
    w("  - 名指しの無い発言が私への問いかどうか"
      + ("（私の件なので、最後の 1 件だけは上に出した）" if ask and ask.get("unaddressed") else ""))
    if not full:
        w("  - 発言の全文。--full で出る")
    return out


# ---- 本文（材料） ---------------------------------------------------------------
#
# 作者の本文と、閉じる issue の本文の冒頭。PR でも issue でも、焦点に関係なく末尾の先頭に出す——
# 件名（型の 1 段落目）と「説明」の材料で、どの呼び方でも要る。行は 1 文字も変えない。

BODY_CAP = 60          # 本文を出す行数の上限（--full で外れる）
ISSUE_HEAD_LINES = 12  # 閉じる issue・本文が指す番号の本文の冒頭を出す行数
ISSUE_CAP = 3          # 冒頭を出す閉じる issue の数
BODY_REF_CAP = 3       # 本文が # で指す番号のうち、冒頭を出す数


def body_refs(body, self_number, exclude):
    """本文が # で指す番号（出た順・重複なし）。自分と閉じる issue は除く。拾い方（URL の fragment や
    word#12、コード・引用の中は番号にしない）は lib/ghtext.py の refs。"""
    return [n for n in refs(body) if n != self_number and n not in exclude]


def fetch_ref(owner, name, num):
    """本文が指す番号の題名と本文。REST の issues は PR も返す（pull_request キーで見分ける）。
    取れなければ None——材料は無くても本体の報告は成り立つ。"""
    out = gh_try("api", f"repos/{owner}/{name}/issues/{num}")
    if not out:
        return None
    try:
        d = json.loads(out)
    except ValueError:
        return None
    return {"number": num, "title": d.get("title") or "", "body": d.get("body") or "",
            "kind": "PR" if d.get("pull_request") else "issue",
            "state": (d.get("state") or "").lower()}


def body_rows(body):
    """本文の行。改行コードを揃え、末尾の空行だけ落とす。引用も HTML コメントも残す——
    作者が置いたものは作者の言葉で、落とすと本文の形が変わる。"""
    rows = (body or "").replace("\r\n", "\n").split("\n")
    while rows and not rows[-1].strip():
        rows.pop()
    return rows


def body_head(title, note, body, full, more):
    """閉じる issue・本文が指す番号の本文の冒頭（見出し・`| ` の行・続きの口）。note は括弧の先頭に添える語。"""
    rows = body_rows(body)
    head = rows if full else rows[:ISSUE_HEAD_LINES]
    out = [f"  === {title}（{note}" + (f"本文の冒頭 {len(head)} 行／{len(rows)} 行）" if rows else "本文なし）")]
    out += ["  | " + ln for ln in head]
    if len(head) < len(rows):
        out.append(f"  （続きは --full か {more} で見る）")
    return out


def render_body(node, full, get_ref=None):
    """get_ref は番号 → fetch_ref の戻り値（検査用の差し替え口。None なら本文が指す番号は引かない）。"""
    is_pr = node["__typename"] == "PullRequest"
    kind = "PR" if is_pr else "issue"
    out = []
    w = out.append
    w("## 本文（材料。作者の言葉。件名と「説明」はここと地図の先頭コメントから書く）" if is_pr
      else "## 本文（材料。作者の言葉。件名はここから書く）")
    w("  `| ` の後ろは 1 文字も変えていない。写すときはそのまま使う")
    rows = body_rows(node.get("body"))
    if not rows:
        w(f"  === {kind} の本文: （本文なし）")
    else:
        shown = rows if full else rows[:BODY_CAP]
        w(f"  === {kind} の本文（{len(rows)} 行）")
        for ln in shown:
            w("  | " + ln)
        if len(shown) < len(rows):
            w(f"  （本文はあと {len(rows) - len(shown)} 行。--full か gh {kind.lower()} view で見る）")
    linked = closing_issues(node)
    for i in (linked if full else linked[:ISSUE_CAP]):
        out.extend(body_head(f"閉じる issue #{i['number']} {i['title']}", "", i.get("body"), full,
                             f"gh issue view {i['number']}"))
    if not full and len(linked) > ISSUE_CAP:
        w(f"  （閉じる issue は他に {len(linked) - ISSUE_CAP} 件。--full で全部）")
    refs = body_refs(node.get("body"), node["number"], {i["number"] for i in linked}) if get_ref else []
    for n in (refs if full else refs[:BODY_REF_CAP]):
        r = get_ref(n)
        if not r:
            w(f"  === 本文が指す #{n}: 取れなかった（gh issue view {n} で見る）")
            continue
        out.extend(body_head(f"本文が指す {r['kind']} #{n} {r['title']}", f"{r['state']}。", r["body"], full,
                             f"gh {'pr' if r['kind'] == 'PR' else 'issue'} view {n}"))
    if not full and len(refs) > BODY_REF_CAP:
        w(f"  （本文が指す番号は他に {len(refs) - BODY_REF_CAP} 件。--full で全部）")
    return "\n".join(out)


# ---- 変更の地図（材料） --------------------------------------------------------
#
# PR なら作者を問わず出す。戻るとき「何の PR か」も失われている——自分の PR でも（理由は冒頭の
# 〈末尾の材料〉）。それでも行の要約は出さない（思い出す助けにならず、AI が要約すると実物と違う
# 言葉になる）。出すのは置き場所・骨組み・配線の材料で、判断はしない。AI はここから選んで並べ、散文
# だけ自分で書く。部品は scripts/lib/changemap.py（/what-am-i-doing と共用）。
#
# 出すもの:
#   - 変更ファイルの一覧（種別と ±行数）と、直近マージの規模の目安
#   - 変更ファイルの木（周辺の既存を薄く並べたもの。そのまま diff の枠に貼れる）
#   - 名前の言及（追加行が他の変更ファイルの名前を含む関係と、その行。呼び出しの当たり）
#   - 新規ファイルの先頭コメント / docstring（作者の自己紹介）と骨組み（step 名・def・上位 key）
#   - 既存ファイルの変更（今の姿に帯を入れた枠。関数まるごと。lib/changemap.py の「変更の枠」）
#
# 行は 1 文字も変えずに `| ` の後ろに出す。AI が写す元になるので、ここで整えると写した先が実物と
# 違ってしまう。

TREE_NOTE = "  変更ファイルの木（行頭 + が新規・~ が変更・- が削除。そのまま diff の枠に貼る）:"
MAP_SIBLINGS_CAP = 40    # 同じ階層の名前の上限（材料の一覧。木は lib が数件に絞る）
MAP_DIFF_CAP = 400_000   # 取った diff（手元なら git diff -W、無ければ gh pr diff）がこの文字数を超えたら中身の
                         # 抽出をやめる。-W は文脈が関数まるごとに広がるので、同じ PR でも gh より早く当たる


def gh_try(*args):
    """gh を呼ぶが、失敗しても止めない。地図の材料は無くても本体の報告は成り立つ。"""
    exe = shutil.which("gh")
    if not exe:
        return None
    try:
        r = subprocess.run(  # noqa: S603 — gh は which で解決。引数はこのファイル内のリテラルと番号だけ
            [exe, *args], capture_output=True, encoding="utf-8", errors="replace",
            timeout=GH_TIMEOUT_SEC,
        )
    except subprocess.TimeoutExpired:
        return None     # 地図の材料は無くても本体の報告は成り立つ
    return r.stdout if r.returncode == 0 else None


@functools.lru_cache(maxsize=None)
def local_checkout(owner, name):
    """手元（cwd）がこのリポジトリの checkout ならそのルート、違えば None。地図・指摘・手元のセクションがそれぞれ聞くので
    覚えておく（同じ rev-parse と remote get-url を 1 回の実行で 4〜5 回 spawn していた）。ルートと origin は
    git switch でブランチを移っても変わらない。"""
    top = changemap.repo_top()
    return top if top and changemap.origin_matches(top, owner, name) else None


def sibling_dirs(owner, name, paths):
    """手元の checkout が同じリポジトリなら、変更ファイルと同じ階層の追跡ファイル名を返す。
    違えば None。中身は手元の HEAD のもので、PR の head ではない。"""
    top = local_checkout(owner, name)
    if not top:
        return None
    sib = changemap.siblings_for(top, paths)
    return [(d, sib[d]) for d in sorted(sib)]


@functools.lru_cache(maxsize=None)
def gh_pr_diff(owner, name, num):
    """gh pr diff（文脈 3 行）。地図（手元に commit が無いとき）と HTML の差分が同じ 1 回を使う。"""
    return gh_try("pr", "diff", str(num), "-R", f"{owner}/{name}")


@functools.lru_cache(maxsize=None)
def merged_size_context(owner, name):
    """直近マージ 60 本の行数（追加＋削除）の中央値と上位 25%。「大きい PR か」の目安。"""
    out = gh_try("pr", "list", "-R", f"{owner}/{name}", "--state", "merged",
                 "--limit", "60", "--json", "additions,deletions")
    if not out:
        return None
    sizes = sorted(p["additions"] + p["deletions"] for p in json.loads(out))
    if not sizes:
        return None
    n = len(sizes)
    return n, sizes[n // 2], sizes[min(n - 1, (3 * n) // 4)]


def scale_text(node, owner, name):
    """PR の規模と、直近マージの規模の目安。地図と HTML の札が同じ文を使う。"""
    size = f"{node['changedFiles']} ファイル +{node['additions']}/-{node['deletions']}"
    ctx = merged_size_context(owner, name)
    return size + (f" ／ 直近マージ {ctx[0]} 本の中央値 {ctx[1]} 行、上位 25% {ctx[2]} 行" if ctx else "")


def render_map(node, owner, name):
    out = []
    w = out.append
    files = node.get("files") or {}
    nodes = sorted(files.get("nodes") or [], key=lambda f: f["path"])
    paths = [f["path"] for f in nodes]
    kinds = {f["path"]: f["changeType"] for f in nodes}

    w("## 変更の地図（材料。PR なら作者を問わず出る。焦点で他の材料に絞ったときだけ出ない）")
    w("  `| ` の後ろは 1 文字も変えていない。写すときはそのまま使う")
    w("  規模: " + scale_text(node, owner, name))
    if files.get("totalCount", 0) > len(nodes):
        w(f"  変更ファイルは {files['totalCount']} 件中、先頭の {len(nodes)} 件だけ取った")
    w("  変更ファイル（ADDED = 新規）:")
    for f in nodes:
        w(f"    {f['changeType']:9} {'+%d/-%d' % (f['additions'], f['deletions']):<12} {f['path']}")

    sib = sibling_dirs(owner, name, paths)
    if sib is None:
        w("  同じ階層の既存: 出せない（手元がこのリポジトリの checkout ではない）")
    else:
        w("  同じ階層の既存（手元の HEAD が追跡しているファイル。変更ファイル自身も含む）:")
        for d, names in sib:
            if names is None:
                w(f"    {d}/: 手元に無い階層")
                continue
            shown = names[:MAP_SIBLINGS_CAP]
            more = f" …ほか {len(names) - len(shown)}" if len(names) > len(shown) else ""
            w(f"    {d}/ ({len(names)}): " + " ".join(shown) + more)

    entries = []
    for f in nodes:
        mark = {"ADDED": "+", "DELETED": "-"}.get(f["changeType"], "~")
        a, d = f["additions"], f["deletions"]
        note = f"-{d}" if mark == "-" else (f"+{a}" if not d else f"+{a}/-{d}")
        entries.append({"path": f["path"], "mark": mark, "note": note})
    w(TREE_NOTE)
    for ln in changemap.render_tree(entries, dict(sib) if sib else None, root_label=name):
        w(ln)

    # diff は手元に base と head があれば git（コードは関数まるごと、散文は前後 PROSE_CONTEXT 行）、無ければ gh pr diff（文脈 3 行）。
    # 先頭・骨組み・名前の言及は + の行しか見ないので、文脈の広さで変わらない
    text, note = pr_function_diff(owner, name, node, lambda: gh_pr_diff(owner, name, node["number"]))
    if text is None:
        w("  中身: 出せない（diff が取れない。gh pr diff が失敗した）")
        return "\n".join(out)
    if len(text) > MAP_DIFF_CAP:
        w(f"  中身: 出さない（diff が {len(text)} 文字で上限 {MAP_DIFF_CAP} を超える）")
        return "\n".join(out)
    hunks, renames = changemap.split_diff(text)

    rel = changemap.call_refs([p for p in paths if not p.endswith((".adoc", ".md", ".txt"))], hunks)
    if rel:
        w("  名前の言及（追加行が他の変更ファイルの名前を含む。下の行が uses:・run:・-f・import なら"
          "呼び出し、コメントなら言及だけ）:")
        for a in sorted(rel):
            for b, hits in sorted(rel[a]):
                w(f"    {a} → {b}")
                for ln in hits:
                    w("    | " + ln)

    new = [p for p in paths if kinds[p] == "ADDED"]
    if new:
        w("  新規ファイルの先頭と骨組み:")
        for p in new:
            lines = changemap.added_lines(hunks.get(p, []))
            w(f"    === {p}  ({len(lines)} 行) {changemap.lang_tag(p)}")
            if not lines:
                w("    | （中身が diff に無い。バイナリか空）")
                continue
            for prefix, ln in changemap.head_and_outline(
                    p, lines, more="。続きは gh pr diff で見る。切れた文を作者の言葉として写さない"):
                w("    " + prefix + ln)

    mod = [f for f in nodes if f["changeType"] != "ADDED"]
    if mod:
        frames = changemap.framed_diff(text)
        total = 0
        w("  既存ファイルの変更（" + changemap.FRAME_NOTE + changemap.FRAME_CAP_NOTE + "。" + changemap.JUMP_NOTE
          + (f"。{note}" if note else "") + "）:")
        for f in mod:
            old = renames.get(f["path"])
            frm = f"  旧: {old}" if old else ""
            w(f"    === {f['path']}  ({f['changeType']} +{f['additions']}/-{f['deletions']}){frm} "
              + changemap.lang_tag(f['path']))
            info = frames.get(f["path"])
            if not info:
                w("    （改名のみ。中身の変更なし）" if old and not (f["additions"] or f["deletions"])
                  else "    （中身が diff に無い。バイナリか空）")
                continue
            rows = changemap.frame_lines(f["path"], info)
            # 合計の上限（/what-am-i-doing と同じ）。地図だけ青天井だと、散文の多い PR で報告が
            # 材料に埋もれる。先頭の file はそれ 1 本で超えても出す
            if total and total + len(rows) > changemap.FRAME_TOTAL_CAP:
                w(f"    （合計の上限 {changemap.FRAME_TOTAL_CAP} 行。--frame {f['path']} で出る）")
                continue
            out.extend(rows)
            total += len(rows)
    return "\n".join(out)


def pr_function_diff(owner, name, node, get_text):
    """PR の diff を枠の文脈で（コードは関数まるごと、散文は 3 行）。手元がこのリポジトリの checkout で
    base と head の commit を持っていれば changemap.frame_diff(base...head)。無ければ get_text()
    （gh pr diff。文脈 3 行）をそのまま使い、理由を返す。戻り値は (diff の本文 or None, 見出しに添える
    断り。関数まるごとなら "")。"""
    top = local_checkout(owner, name)
    if not top:
        return get_text(), "文脈は 3 行——手元がこのリポジトリの checkout ではない"
    base, head = node.get("baseRefOid"), node.get("headRefOid")
    if not local_range(owner, name, base, head):
        return get_text(), "文脈は 3 行——手元に base と head の commit が無い。fetch すれば関数まるごとになる"
    wide = changemap.frame_diff(cwd=top, rev=f"{base}...{head}")
    return (wide, "") if wide is not None else (get_text(), "文脈は 3 行——手元の git diff が失敗した")


# ---- 指摘・CI・手元のブランチ（材料） --------------------------------------------
#
# 戻るとき「何を言われて、どこで止まっているか」も失われている——自分の PR でも、レビューで渡された
# PR で作者が返してきた件でも。人が入っている未解決スレッドが有れば、作者を問わず出す。
# 未解決スレッドごとに、相手の最後の発言の全文と head のその行の前後を出す。AI はこれを地図の
# file ごとのセクションと同じ「箇所」の形（見出し・誰が何を求めているか・実物の行・直すなら）に並べる。
# CI は落ちた step のログの末尾、手元のブランチは push していない commit と未コミットの木。
# どれも判断はせず、行は 1 文字も変えない。

THREAD_CONTEXT = 5    # 指摘の行の前後に出す行数
THREAD_CAP = 10       # 指摘の材料に出すスレッド数の上限
THREAD_BODY_CAP = 40  # 相手の発言を出す行数の上限
CI_TAIL = 30          # 落ちた step のログの末尾の行数
RUN_URL = re.compile(r"/actions/runs/(\d+)/job/(\d+)")


def head_oid(node):
    heads = node.get("head", {}).get("nodes") or []
    return (heads[0].get("commit") or {}).get("oid") if heads else None


def head_reader(owner, name, oid):
    """PR の head にあるファイルの行を返す関数を作る。手元の checkout が同じリポジトリで、その
    commit を持っていれば `git show <oid>:<path>` で（working tree は読まない——未コミットの編集が
    「head の行」に混ざる。実測: 手元で短くした file の窓が空で出た）、無ければ GitHub から取る
    （取れなければ None）。同じ path は 1 回だけ読む。"""
    top = local_checkout(owner, name)
    local = bool(top and oid)
    cache = {}

    def read(path):
        if path in cache:
            return cache[path]
        text = changemap.git("show", f"{oid}:{path}", cwd=top) if local else None
        if text is None and oid:
            text = gh_try("api", "-H", "Accept: application/vnd.github.raw",
                          f"repos/{owner}/{name}/contents/{quote(path)}?ref={oid}")
        cache[path] = text.splitlines() if text is not None else None
        return cache[path]
    return read


def owns(node, me):
    """自分の件か（作者か assignee）。"""
    return login_of(node.get("author")) == me or any(a["login"] == me for a in node.get("assignees", {}).get("nodes", []))


def unresolved_threads(node, me):
    """未解決で人が入っているスレッド。相手（私でない人）の最後の発言と、私が返すターンかを添える。
    私しか発言していないスレッドは出さない——それは指摘ではなく、私が出した側。私が返すターンは、人の最後の発言が
    相手のもので、私がそのスレッドで発言しているか自分の件のとき（人の PR で他の人同士が話しているスレッドは、
    私が返すターンではない）。"""
    out = []
    own = owns(node, me)
    # 自分の件では、持ち主の側（作者と、作者から渡された担当）の返事も私の側の返事。担当の仲間が最後に返したスレッドは
    # 相手（レビュアー）のターンで、私が返すターンではない
    side = {me} | (set(turn.owner_side(node)) if own and node.get("assignees") else set())
    for th in node.get("reviewThreads", {}).get("nodes", []):
        if th["isResolved"]:
            continue
        cs = [c for c in th["comments"]["nodes"] if not is_bot(c["author"])]
        theirs = [c for c in cs if login_of(c["author"]) != me]
        if not theirs:
            continue
        mine = [c for c in cs if login_of(c["author"]) == me]
        last = login_of(cs[-1]["author"])
        # 仲間の返事を私の側に数えるのは、スレッドに持ち主の側の外の人（レビュアー）が居るときだけ。私と担当だけの
        # スレッドで担当が返せば、それは私への返事で私が返すターン
        ours = side if any(login_of(c["author"]) not in side for c in cs) else {me}
        opener = login_of(cs[0]["author"])
        # 削除された行への指摘（diffSide が LEFT）は、line が base の版の行番号。head の行として読むと別の行になる
        out.append({"path": th["path"], "line": th.get("line"), "outdated": th.get("isOutdated"),
                    "left": th.get("diffSide") == "LEFT",
                    # 私が入っていないスレッドが私のターンになるのは、私が持ち主（turn.owners）のときと、持ち主の側の
                    # 私以外の人（渡した担当など）が立てたとき（側の残りの私への問い）。作者でも担当に渡した後は、外の人が
                    # 立てたスレッドは担当のターンで、持ち主でない共同の担当も同じ（どれも /whose-turn の thread_turns と同じ）
                    "last": theirs[-1],
                    "my_turn": last not in ours and bool(mine or (own and (me in turn.owners(node)
                                                                           or opener in side - {me}))),
                    # 人の最後の発言が私の側（私以外の持ち主）か。端末の「相手のターン」の言い方を分ける
                    "side_last": last if last != me and last in ours else None,
                    # 私の最後の発言の時刻。私が返すターンで相手がその後に返していれば、「私の発言以降にその file が
                    # どう変わったか」を出す基準になる（直したと言われた件で要るのは関数の今の姿でなく差分）
                    "mine_t": ts(mine[-1]["createdAt"]) if mine else None,
                    "mine_last": mine[-1] if mine else None})
    # 私が返すターンを先に（並びはそのほかは GitHub の順のまま）。一覧は THREAD_CAP 件で切るので、他の人同士の
    # スレッドが前に 10 件並ぶと、1 行目が「私が返すターン」と言うスレッドが一覧から落ちた
    out.sort(key=lambda th: not th["my_turn"])
    return out


FUNC_SPAN_CAP = 200   # 関数まるごとの上限。超えたら前後 THREAD_CONTEXT 行に戻す
THREAD_DIFF_CAP = 200  # 私の発言以降の変更の枠の行数の上限（1 スレッドあたり。--full で外す）


DEF_RE = re.compile(r"^\s*(?:async\s+def|def|class)\s")  # 字下げのある def / class（Python のメソッド等）


def func_span(lines, n, cap=FUNC_SPAN_CAP):
    """指摘の行 n を含む関数の範囲 (lo, hi, 関数まるごとか)。境目は git diff -W の既定の funcname と同じ
    「行頭が空白でない行」に、字下げのある def / class を足したもの（class の行まで遡ると Python のメソッドは
    class 全体になり、200 行超で前後 5 行に落ちる。実測: 指摘の行 264 の関数 200〜282 行を AI が head から
    足していた）。長すぎる（cap 超）・境目が無い（散文）ときは前後 THREAD_CONTEXT 行（仕様の原則 4「前後は
    長めに」。指摘の行だけの数行では読む人が file を開いて前後を確かめに行く）。"""
    def top(i):
        s = lines[i - 1]
        return bool(s) and (not s[0].isspace() or bool(DEF_RE.match(s)))
    lo = n
    while lo > 1 and not top(lo):
        lo -= 1
    hi = n + 1
    while hi <= len(lines) and not top(hi):
        hi += 1
    hi -= 1
    while hi > n and not lines[hi - 1].strip():
        hi -= 1
    # 境目が無い・長すぎる・関数が前後の窓より小さい（行頭に空白の無い file——yaml・md・平らな設定——は
    # 1 行ごとが「関数」になる）ときは、前後 THREAD_CONTEXT 行の窓
    if not top(lo) or hi - lo + 1 > cap or hi - lo < 2 * THREAD_CONTEXT:
        return max(1, n - THREAD_CONTEXT), min(len(lines), n + THREAD_CONTEXT), False
    return lo, hi, True


def split_hunks(lines):
    """split_diff が返す 1 file の行（@@ と +/-/空白の行）を hunk ごとに [(新側の開始行, 新側の行数, 行の列)] に。"""
    out, cur = [], None
    for ln in lines:
        m = changemap.HUNK_RE.match(ln)
        if m:
            cur = (int(m.group(1)), int(m.group(2) or 1), [])
            out.append(cur)
        elif cur is not None:
            cur[2].append(ln or " ")
    return out


def since_differ(owner, name, head):
    """私の発言以降の変更の diff を取る関数 (path, base, head) → git diff -U0 の全文か None。手元の checkout が
    このリポジトリのときだけ作る（commit を持っていなければ git が失敗して None）。文脈 0 行で取り、関数の
    範囲は func_span（head の行）で決めて重ねる——-W の関数の境目は git の既定 funcname（行頭が空白でない行）
    で、Python のメソッドは class 全体になる。"""
    top = local_checkout(owner, name)
    if not top or not head:
        return None

    def diff(path, base, head_oid):
        return plain_diff(f"{base}..{head_oid}", top, [path], opts=("-U0",))
    return diff


def hunk_overlaps(hunk, lo, hi):
    """-U0 の hunk (新側の開始行, 行数, 行) が head の lo〜hi 行に掛かるか。行数 0（削除だけ）の hunk は
    「開始行の直後」に消えた行が有った印で、lo〜hi の中か直後なら掛かる。"""
    s, n, _ = hunk
    return (s <= hi and s + n - 1 >= lo) if n else (lo <= s + 1 <= hi + 1)


def framed_span(lines, lo, hi, hunks):
    """head の lo〜hi 行に -U0 の hunk を重ねて、frame_hunk の入力（印つきの行）にする。+ の行は head の行
    そのもの、- の行は消えた位置に前の行として挟む。範囲の外に掛かる分は落とす（単位は関数まるごと）。"""
    added, gone = set(), {}
    for s, n, body in hunks:
        added.update(range(s, s + n))
        gone.setdefault(s if n else s + 1, []).extend(ln[1:] for ln in body if ln.startswith("-"))
    items = []
    for k in range(lo, hi + 1):
        items.extend(("-", t) for t in gone.get(k, []))
        items.append(("+" if k in added else " ", lines[k - 1]))
    items.extend(("-", t) for t in gone.get(hi + 1, []))
    return items


def merge_spans(spans):
    out = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1] + 1:
            out[-1] = (out[-1][0], max(out[-1][1], hi))
        else:
            out.append((lo, hi))
    return out


def render_since_thread(th, node, lines, lo, hi, diff_since, full, frame=True):
    """私が返すターンで、私の発言の後に相手が返している件——私の発言以降にこの file がどう変わったかを、今の姿に
    帯を入れた関数まるごとで出す（相手が「直した」と言う件で確かめるのは関数の今の姿でなく、私の発言以降の
    差分。関数まるごとを head から写すと 1 行の修正に 83 行を読む——実測）。lo〜hi（指摘の行の関数）に掛かる
    hunk だけ。行の無い指摘（file 全体）は、変わった所ごとにその関数。戻り値は (行の列, 枠を出したか)。出せない
    理由も行で返す（黙って落とさない）。frame が偽なら、変わったかどうかの行だけで枠は出さない（削除された側の行への
    指摘。head に行が無く、どの関数かを決められない）。"""
    out = []
    w = out.append
    when = f"私の発言（{hhmm(th['mine_t'])}）"
    found = since_base({"t": th["mine_t"]}, node)
    if not found:
        w(f"  {when}以降の変更: 基準の commit を置けない（発言が取った commit の全部より前）")
        return out, False
    base, _ = found
    authored, merges, missing = since_commits(node, base)
    if missing:
        w(f"  {when}以降の変更: 基準の commit {base[:7]} が今の head の履歴に無い（履歴の書き換えか、窓の外）")
        return out, False
    if not authored and not merges:
        w(f"  {when}以降、commit は無い")
        return out, False
    tally = f"作者側の commit {len(authored)} 本" + (f"。取り込み {merges} 本の分も含む" if merges else "")
    head = node.get("headRefOid")
    text = diff_since(th["path"], base, head) if diff_since and head else None
    if text is None:
        w(f"  {when}以降の変更: 出せない（手元にこの PR の commit が無い。gh pr diff で見る）")
        return out, False
    hunks = split_hunks(changemap.split_diff(text)[0].get(th["path"], []))
    if not hunks:
        w(f"  {when}以降、この file は変わっていない（{tally}）")
        return out, False
    if not frame:
        w(f"  {when}以降、この file は {len(hunks)} か所変わっている（{tally}。削除された側の行への指摘なので枠にしない。"
          "gh pr diff で見る）")
        return out, False
    if lines is None:
        w(f"  {when}以降の変更: 変わっている（{tally}）が、head の file が読めないので枠にできない。gh pr diff で見る")
        return out, False
    if lo is None:
        spans = merge_spans(func_span(lines, min(max(s, 1), len(lines)))[:2] for s, _, _ in hunks)
    else:
        spans = [(lo, hi)]
    picked = [(a, b, [h for h in hunks if hunk_overlaps(h, a, b)]) for a, b in spans]
    picked = [p for p in picked if p[2]]
    if not picked:
        w(f"  {when}以降、この関数は変わっていない（file の他の所に {len(hunks)} 枠。{tally}）")
        return out, False
    w(f"  {when}以降のこの file の変更（{tally}）。今の姿に帯（前の行は #│、色の行は今。`| ` の後ろをそのまま写す）:")
    total = 0
    for i, (a, b, hs) in enumerate(picked):
        items = framed_span(lines, a, b, hs)
        prefix = changemap.common_indent([t for _, t in items])
        frame = changemap.frame_hunk(th["path"], [m + t for m, t in zip((m for m, _ in items),
                                                                        changemap.dedent([t for _, t in items], prefix))])
        if not full and total and total + len(frame) > THREAD_DIFF_CAP:   # 最初の枠は上限を超えても出す（render_map と同じ）
            w(f"  （残り {len(picked) - i} 枠は --full か gh pr diff で）")
            break
        w(f"  飛び先 {th['path']}:{a}（head の {a}〜{b} 行" + (f"。共通の字下げ {len(prefix)} 桁を落とした" if prefix else "") + "）")
        for ln in frame:
            w("  | " + ln)
        total += len(frame)
    return out, True


def render_threads(node, me, read_lines, full=False, diff_since=None):
    threads = unresolved_threads(node, me)
    out = []
    w = out.append
    w("## 指摘（材料。未解決スレッドごとに、相手の最後の発言の全文と head のその行の前後）")
    w("  `| ` の後ろは head の実物の行（行番号つき。共通の字下げは落としてある——字下げ分は戻さない）。写すときはそのまま使う")
    if not threads:
        w("  人が入っている未解決スレッドは無い")
        return "\n".join(out)
    for i, th in enumerate(threads if full else threads[:THREAD_CAP], 1):
        if th["my_turn"]:
            turn = "← 私が返すターン"
        elif th["side_last"]:
            turn = f"← 持ち主の側の {th['side_last']} が最後に返している（相手のターン）"
        elif th["mine_last"]:
            turn = "← 私が最後に発言している（相手のターン）"
        else:
            turn = "← 私は入っていない（他の人同士の会話）"
        w(f"  === {i}/{len(threads)} {thread_where(th)}  {turn} {changemap.lang_tag(th['path'])}")
        c = th["last"]
        w(f"  {login_of(c['author'])}（{hhmm(ts(c['createdAt']))}）:")
        body = their_lines(c["body"])
        for ln in body[:THREAD_BODY_CAP]:
            w("    " + ln)
        if len(body) > THREAD_BODY_CAP:
            w(f"    （発言はあと {len(body) - THREAD_BODY_CAP} 行。gh api で見る）")
        # 削除された側の行への指摘は head に行が無く、どの関数かを決められない。私の発言以降に変わったかは出し、
        # 枠は出さない（file の変わった所ごとの関数を並べると、指摘と関係の無い関数ばかりになる）
        since_turn = th["my_turn"] and bool(th["mine_t"])
        lines = read_lines(th["path"]) if (th["line"] or since_turn) and not th["left"] else None
        lo = hi = whole = None
        if th["line"] and not th["left"] and lines is not None and th["line"] <= len(lines):
            lo, hi, whole = func_span(lines, th["line"])
        if since_turn:
            since_out, framed = render_since_thread(th, node, lines, lo, hi, diff_since, full, frame=not th["left"])
            out.extend(since_out)
            if framed:
                continue  # 変更に帯を入れた関数まるごとが出た。今の姿だけの行を重ねない
        if not th["line"]:
            w("  行: 今の head に無い（消えた行か、diff の外）")
            continue
        if th["left"]:
            w(f"  行: 削除された側の行 {th['line']}（base の版）への指摘。head にこの行は無い（gh pr diff で見る）")
            continue
        if lines is None:
            w("  行: 取れない（手元にその commit が無く、GitHub からも読めなかった）")
            continue
        if lo is None:
            w(f"  行 {th['line']} は head のファイル（{len(lines)} 行）の外")
            continue
        span = lines[lo - 1:hi]
        prefix = changemap.common_indent(span)
        w(f"  head の {lo}〜{hi} 行" + ("（指摘の行を含む関数まるごと）" if whole else f"（指摘の行の前後 {THREAD_CONTEXT} 行）")
          + (f"（共通の字下げ {len(prefix)} 桁を落とした）" if prefix else "")
          + ("（指摘した時点から行がずれている。isOutdated）" if th["outdated"] else "") + ":")
        for k, ln in changemap.fold_literals(changemap.dedent(span, prefix), th["path"]):
            w(f"  | {lo + k:4} {ln}" if k is not None else f"  |      {ln}")
    if not full and len(threads) > THREAD_CAP:
        w(f"  （スレッドは他に {len(threads) - THREAD_CAP} 件。--full で全部）")
    return "\n".join(out)


def ci_excerpt(log, tail=CI_TAIL):
    """--log-failed の出力から、落ちた場所だけを残す。行頭の job・step・時刻と色の制御文字は落とし、
    最後の ##[error] までを出す——その後ろは後片付けのログで、落ちた理由ではない（実測: 末尾 30 行を
    そのまま出すと、理由の行が Post job cleanup の 20 行の上に埋もれた）。"""
    rows = []
    for ln in log.splitlines():
        parts = ln.split("\t", 2)
        body = parts[2] if len(parts) == 3 else ln
        body = re.sub(r"^\d{4}-\d\d-\d\dT[\d:.]+Z ?", "", body)
        rows.append(re.sub(r"\x1b\[[0-9;]*m", "", body))
    errs = [i for i, r in enumerate(rows) if "##[error]" in r]
    end = errs[-1] + 1 if errs else len(rows)
    return rows[max(0, end - tail):end]


CI_RED_CAP = 3  # ログを取る赤の件数（--full で外す）


def ci_failures(node, owner, name, run_log=None, full=False):
    """赤いチェックごとに {name, url, log（落ちた step のログの末尾の行。取れなければ None）, note}。
    run_log は検査用の差し替え口。端末の報告（render_ci）と HTML の材料が同じ取得を使う（ログを 2 回取らない）。"""
    red, _, _ = check_state(node)
    out = []
    for cname, url in (red if full else red[:CI_RED_CAP]):
        m = RUN_URL.search(url or "")
        if not m:
            out.append({"name": cname, "url": url, "log": None,
                        "note": "GitHub Actions の run ではないのでログを取れない。URL を開く"})
            continue
        log = (run_log or (lambda run, job: gh_try(
            "run", "view", run, "-R", f"{owner}/{name}", "--job", job, "--log-failed")))(
            m.group(1), m.group(2))
        out.append({"name": cname, "url": url, "log": ci_excerpt(log) if log else None,
                    "note": "" if log else "ログを取れなかった。gh run view <run> --job <job> --log-failed で見る"})
    return out, max(0, len(red) - len(out))


def render_ci(node, owner, name, run_log=None, full=False, failures=None):
    """赤いチェックごとに、失敗した step のログの末尾。failures は ci_failures の戻り値（呼び手が取って
    あれば渡す）。"""
    fails, more = failures if failures is not None else ci_failures(node, owner, name, run_log, full)
    out = []
    w = out.append
    w("## CI が落ちた理由（材料。赤いチェックごとに、失敗した step のログの末尾）")
    if not fails:
        unseen = ci_unseen(node)
        # 取得の上限を超えた PR は、見ていない残りに赤が在りうる（ci_summary と同じ断り）
        w(f"  取った分に赤いチェックは無い（残り {unseen} 件は見ていない）" if unseen else "  赤いチェックは無い")
        return "\n".join(out)
    for f in fails:
        w(f"  === {f['name']}  {f['url'] or '（URL なし）'} （言語名 plaintext）")
        if f["log"] is None:
            w(f"  | （{f['note']}）")
            continue
        for ln in f["log"]:
            w("  | " + ln)
    if more:
        w(f"  （赤は他に {more} 件。--full で全部）")
    return "\n".join(out)


# ---- 該当ブランチへ移る（--switch） -----------------------------------------------
#
# 並行作業から戻るとき、会話の位置と一緒に手元のブランチも失われている。--switch を付けると、該当ブランチ
# （PR は head のブランチ、issue は名前に番号を持つ手元のブランチが 1 本のとき）へ git switch で移る。
#
# PR のブランチが手元に無ければ、origin からその元を 1 本だけ fetch して git switch -c で作って移る（実測: 手元に
# 無いブランチで「gh pr checkout で取れる」と案内して止まり、戻るツールなのに戻れなかった）。作る名前と元は
# gh pr checkout と同じ——同じリポジトリの PR は refs/heads/<head> を origin/<head> に取って追跡させ、fork の
# PR は refs/pull/N/head を取って <head>（head が base の既定ブランチ名なら <fork の owner>/<head>）に作り、
# branch.<名前>.remote / merge を gh と同じ値にする。手元にあるブランチは fetch でも動かさない（更新するのは
# origin/<head> の追跡 ref だけ。pull・merge・stash・commit・gh pr checkout はしない）。手元の origin/<head> の
# ref を見るだけで作らないのは、fetch していない ref は古いから（--no-guess もそのため）。issue は origin を
# 探さない（番号で origin のブランチを選ぶのは当て推量）。fetch は端末に認証を聞かない（GIT_TERMINAL_PROMPT=0）
# ので、認証が要る origin では固まらず失敗して理由が行に出る。
#
# 追跡ファイルに未コミットの変更があれば移らない。git は衝突しない限り黙って持ち越す（実測: exit 0 で
# ` M a.txt` が次のブランチに付いて来る）ので、別のブランチに commit する事故の材料になる。未追跡だけなら移る
# （git は失われる変更を作らない。衝突すれば拒む）。ignored のファイルは git 自身に守らせる
# （--no-overwrite-ignore。既定は警告なしに置き換え、git のどこにも残らない）。
#
# 成否は git の終了コードでなく前後のブランチ名で決める——post-checkout hook が非 0 を返すと終了コードも
# 非 0 だが HEAD は既に移っている。
#
# fork の PR は名前だけでは移らない——fork の head が trunk / main のような名前で来るのは普通で、名前一致で
# 移ると別物のブランチに「居る」と申告する。手元のブランチが PR の head の commit を含むときだけ移る
# （gh pr checkout で取ったブランチは head の commit を持っているので通る）。逆向き（手元の先端が head の
# 先祖）は見ない——fork の head は base から切られているので手元の main が先祖になり、head が main の
# fork PR で手元の main に移ってしまう（実測）。gh pr checkout は fork の head が base の既定ブランチと
# 同名のとき <fork の owner>/<head> の名前で取るので、その名前を先に探す。
#
# 移る前に merge / rebase / cherry-pick の途中でないことを git の印（MERGE_HEAD 等）で見る。衝突を解決し
# 終えた merge は普通の staged 変更に見え、「commit か stash」と助言すると stash が MERGE_HEAD を消す。

STDERR_LINES = 4  # git の言い分を出す行数。拒否文の 1 行目は総称で、邪魔している path は 2 行目以降
GONE = "消えた fork"  # headRepository が null（fork が消えている）のときの呼び名。出所が分からないので fork として扱う
IN_PROGRESS = ("MERGE_HEAD", "CHERRY_PICK_HEAD", "REVERT_HEAD", "rebase-merge", "rebase-apply")
# 手元に無いブランチの元を 1 本 fetch するのに待つ秒数。fetch は殺しても ref を書きかけにしない（ref は転送の
# 最後にまとめて更新される）ので、switch と違って timeout を付ける
FETCH_TIMEOUT = 120
NO_PROMPT = {"GIT_TERMINAL_PROMPT": "0"}  # 認証を端末に聞かず失敗する（stdin は閉じてあるが git は /dev/tty で聞く）


def local_branches(cwd=None):
    """(手元のブランチ名 → それを checkout している worktree の path（していなければ ""）, 今のブランチ名
    （detached なら ""）)。読めなければ (None, None)。for-each-ref 1 回で全部取る。
    %(refname:short) は同名のタグがあると heads/x になる（実測）ので、%(refname) から refs/heads/ を剥ぐ。"""
    out = changemap.git("for-each-ref", "--format=%(HEAD)\t%(refname)\t%(worktreepath)",
                        "refs/heads/", cwd=cwd)
    if out is None:
        return None, None
    found, current = {}, ""
    for line in out.splitlines():
        mark, ref, path = (line.split("\t") + ["", ""])[:3]
        if not ref.startswith("refs/heads/"):
            continue
        name = ref[len("refs/heads/"):]
        found[name] = path.strip()
        if mark == "*":
            current = name
    return found, current


def issue_branch(num, branches):
    """issue の移る先。名前に番号を持つ手元のブランチが 1 本のときだけ（this の解決と同じ規則の逆向き。
    0 本・2 本以上なら移らない）。戻り値は (名前 or None, 移らない理由)。"""
    hits = sorted(b for b in branches if branch_number(b) == num)
    if len(hits) == 1:
        return hits[0], ""
    if not hits:
        return None, f"名前に #{num} を持つ手元のブランチは無い"
    return None, (f"名前に #{num} を持つ手元のブランチが {len(hits)} 本ある（{', '.join(hits)}）。"
                  "どれかを選んで手で git switch する")


def fork_of(node, owner, name):
    """PR の head が別のリポジトリ（fork）なら、その owner/name。同じなら None。fork が消えていると
    headRepository は null——出所が分からないので GONE を返し、fork として扱う（名前だけでは移らない）。"""
    if "headRepository" in node and node["headRepository"] is None:
        return GONE
    repo = (node.get("headRepository") or {}).get("nameWithOwner") or ""
    return repo if repo and repo.lower() != f"{owner}/{name}".lower() else None


def contains_head(branch, oid, cwd=None):
    """手元の branch が commit oid を含む（先端かその先祖）か。True／False／None（oid を手元に持っていない）。"""
    if not changemap.has_commit(oid, cwd):
        return None
    return changemap.git("merge-base", "--is-ancestor", oid, f"refs/heads/{branch}", cwd=cwd) is not None


def in_progress(top):
    """merge / rebase / cherry-pick / revert の途中か。git が置く印の有無で見る（git 1 回）。読めなければ None。"""
    out = changemap.git("rev-parse", *(a for n in IN_PROGRESS for a in ("--git-path", n)), cwd=top)
    if out is None:
        return None
    return any(os.path.exists(os.path.join(top, p)) for p in out.splitlines() if p)


def tree_blocker(text, nxt):
    """git status --porcelain -z の出力から、移るのを止める理由と未追跡の件数を返す。(理由 or None, 未追跡の数)。
    text が None（読めない・timeout）なら止める——空と同じに扱うと、状態を測れないまま移る（fail-open）。
    nxt は片付けた後の一手。手元にあるブランチなら git switch <名前> だが、origin から作るブランチはまだ無い
    （git switch は失敗するか、古い追跡 ref から DWIM で作る）ので、呼び手が「もう一度 /catchup」を渡す。"""
    if text is None:
        return "手元の状態が読めないので移らない", 0
    rows = changemap.porcelain_records(text)
    tracked = [r for r in rows if r[0] != "??"]
    untracked = len(rows) - len(tracked)
    if tracked:
        return (f"追跡ファイルに未コミットの変更 {len(tracked)} 件があるので移らない（git は持ち越せるが、"
                f"別のブランチに commit する事故になるので止めた。自分の編集か確かめてから commit か stash → "
                f"{nxt}）"), untracked
    return None, untracked


def switch_blocker(top, target, worktree, nxt):
    """移る直前に手元を見て、止める理由（無ければ None）と未追跡の件数を返す。理由は「ブランチ <名前>: 」の
    後ろに置く形。安い判定から順に見て、最後が git status（worktree は for-each-ref で既に取れている）。"""
    if worktree:
        if os.path.isdir(worktree):
            return f"別の worktree に checkout 済み: {worktree}（そこで続ける）", 0
        return (f"worktree {worktree} に checkout 済みだが、その dir が無い"
                f"（git worktree prune → git switch {target} で移れる）"), 0
    busy = in_progress(top)
    if busy is None:
        return "手元の状態が読めないので移らない", 0
    if busy:
        return ("merge / rebase / cherry-pick / revert の途中なので移らない"
                "（終えるか --quit で止める。別に取るなら git worktree add）"), 0
    # submodule の変更は switch がそのまま持ち越すので数えない
    return tree_blocker(changemap.git("status", "--porcelain", "-z", "--ignore-submodules=all", cwd=top), nxt)


def git_notes(err, failed=False):
    """git switch の stderr から、行に添える言い分。成功なら Switched to 以外（置き去りの commit・origin より
    遅れ・hook の出力）、失敗なら拒否文を Please / Aborting の手前まで（1 行目は総称で、邪魔している path は
    2 行目以降）。どちらも STDERR_LINES 行まで。"""
    notes = [ln.rstrip() for ln in err.splitlines() if ln.strip() and not ln.startswith("Switched to")]
    if failed:
        notes = notes[:next((i for i, n in enumerate(notes) if n.startswith(("Please", "Aborting"))),
                            len(notes))]
    return notes[:STDERR_LINES]


def default_branch(node):
    """base リポジトリの既定ブランチ名。node に無ければ ""。"""
    return ((node.get("baseRepository") or {}).get("defaultBranchRef") or {}).get("name") or ""


def pull_ref(num):
    """PR の head を GitHub が置く ref。fetch する元であり、branch.<ブランチ>.merge に書く値でもある——
    2 つが食い違うと追跡先が壊れるので、同じ 1 か所から取る。"""
    return f"refs/pull/{num}/head"


def pr_branch_names(head_ref, fork, default):
    """PR の head を手元で探す名前の列と、どれも無いときに作る名前（決められないなら None）。gh pr checkout と
    同じ——fork の PR は前に gh が付けた <fork の owner>/<head> も探すが、作るのは <head>。head が base の
    既定ブランチ名（main など）なら素の <head> は使わない（手元の main は base 側のブランチで fork の main とは
    別物。gh もその名前では作らない）ので <fork の owner>/<head> を作り、消えた fork でそれが無ければ
    作る名前が無い。"""
    if not fork:
        return [head_ref], head_ref
    prefixed = [f"{fork.split('/', 1)[0]}/{head_ref}"] if fork != GONE else []
    if default and head_ref == default:
        return prefixed, (prefixed[0] if prefixed else None)
    return prefixed + [head_ref], head_ref


def fetch_source(top, num, node, fork):
    """手元に無い PR のブランチの元を origin から 1 本だけ fetch する。戻り値は (switch -c の元, 失敗の行の列)。
    同じリポジトリの PR は refs/heads/<head> を origin/<head> へ（ブランチはそれを追跡する）、fork の PR は
    refs/pull/N/head を FETCH_HEAD へ取り、その commit の oid を元にする（FETCH_HEAD は worktree に 1 つの
    file で、他のセッションの fetch が書き換えるので名前では使わない）。"""
    head_ref = node.get("headRefName")
    spec = pull_ref(num) if fork else f"+refs/heads/{head_ref}:refs/remotes/origin/{head_ref}"
    rc, _, err = changemap.run("fetch", "--no-tags", "origin", spec, cwd=top, timeout=FETCH_TIMEOUT,
                               env=NO_PROMPT)
    if rc is None:
        return None, [f"origin から取れなかった（{err}）"]
    if rc != 0:
        if "couldn't find remote ref" in err:
            if fork:
                return None, [f"origin に {pull_ref(num)} が無い（origin は GitHub の base リポジトリか）"]
            gone = {"MERGED": "PR は merge 済みで、ブランチは削除済み", "CLOSED": "PR は close 済みで、ブランチは削除済み"
                    }.get(node.get("state"), "PR は open のままブランチだけが消えている")
            return None, [f"手元に無く、origin にももう無い（{gone}）。中身は git fetch origin "
                          f"{pull_ref(num)} → git switch -c {head_ref} FETCH_HEAD で取れる"]
        return None, ["origin から取れなかった（git fetch が失敗）", *git_notes(err, failed=True)]
    if not fork:
        # 完全名で渡す。短縮名 origin/<head> は手元に同名のブランチかタグがあると ambiguous で拒まれる（実測）
        return f"refs/remotes/origin/{head_ref}", []
    oid = (changemap.git("rev-parse", "--verify", "--quiet", "FETCH_HEAD^{commit}", cwd=top) or "").strip()
    if not oid:
        return None, [f"origin から取った {pull_ref(num)} の commit が読めない"]
    return oid, []


def track_fork(top, branch, num, node, fork, origin):
    """fork の PR から作ったブランチの追跡先を gh pr checkout と同じにする——PR が maintainer の push を許していれば
    fork の URL の refs/heads/<head>（pull も push もそこへ）、そうでなければ origin の refs/pull/N/head（pull は
    効き、push は上流名が違うので git が拒む）。書けなかった key を返す。"""
    remote, merge = "origin", pull_ref(num)
    if node.get("maintainerCanModify") and fork != GONE:
        remote, merge = changemap.swap_repo(origin, fork), f"refs/heads/{node.get('headRefName')}"
    return [k for k, v in (("remote", remote), ("pushRemote", remote), ("merge", merge))
            if changemap.git("config", f"branch.{branch}.{k}", v, cwd=top) is None]


def branch_state(cwd=None):
    """(ルート, 手元のブランチの一覧, 今のブランチ)。ルートが無ければ (None, None, None)。"""
    top = changemap.repo_top(cwd)
    # ブランチの一覧と今のブランチは同じ for-each-ref 1 回で取る。一覧が読めなかったときだけ、位置を単独で聞く
    branches, cur = local_branches(top) if top else (None, None)
    if top and branches is None:
        cur = changemap.current_branch(top)
    return top, branches, cur


def where_now(top, cur):
    """移らなかった行の末尾に添える、今の位置。"""
    return ("手元に git の checkout が無い" if not top
            else "手元の位置は読めない" if cur is None
            else f"手元は {cur or 'detached HEAD'} のまま")


def git_switch(top, target, args):
    """git switch を打つ。戻り値は (target に移れたか, 終了コード, stderr)。成否は前後のブランチ名で決める。"""
    # 書く操作は timeout で殺さない——途中で殺すと HEAD は元のまま file だけ書き換わり、index.lock が残る
    # （実測: smudge filter に sleep を仕込んで 15 秒で殺した）
    rc, _, err = changemap.run("switch", "--no-guess", "--no-overwrite-ignore", *args, cwd=top, timeout=None)
    moved = changemap.current_branch(top) == target
    if moved:
        # プロセスの cwd の階層が移った先に無いと消え、以後の cwd 無しの git が全部落ちる
        # （render_local が「持っていない」「変更なし」と嘘を出す）。ルートに寄せる
        try:
            os.getcwd()
        except FileNotFoundError:
            os.chdir(top)
    return moved, rc, err


def moved_line(head, cur, untracked):
    line = head + f"{cur or '（detached）'} から移った"
    return line + (f"（未追跡 {untracked} 件は持ち越した）" if untracked else "")


def switch_branch(owner, name, num, node, cwd=None):
    """--switch のとき、該当ブランチへ git switch で移る。PR のブランチが手元に無ければ origin から取って作る。
    戻り値は (見出しに足す行, 居るブランチ名 or None)。居る＝移った、または既に居た（末尾に手元のセクションを
    出す）。移らない理由は行に書く——黙って何もしないことは無い。"""
    is_pr = node["__typename"] == "PullRequest"
    top, branches, cur = branch_state(cwd)

    def stay(lines):
        """移らなかった行。今どこに居るかを 1 行目の末尾に必ず添える——無いと読む手が推測で書く（実測: 別の
        ブランチに居るのに「手元は main のまま」と報告した）。位置を書くのはここだけで、判定の側は理由だけを返す。"""
        return [lines[0] + f"（{where_now(top, cur)}）", *lines[1:]], None

    if not top:
        return stay(["ブランチ: 移らない"])
    url = changemap.origin_url(top)
    fork = fork_of(node, owner, name) if is_pr else None
    # 三角 workflow（origin が自分の fork で、PR の head がその fork）なら手元は head の側。名前一致でよく、
    # 手元に無ければ同じリポジトリの PR と同じく origin の refs/heads/<head> から作る
    on_fork = bool(fork) and fork != GONE and changemap.origin_is(url, *fork.split("/", 1))
    if not on_fork and not changemap.origin_is(url, owner, name):
        return stay([f"ブランチ: 手元の origin が {owner}/{name} でない（{url or 'origin が無い'}）ので移らない"])
    if on_fork:
        fork = None
    if branches is None:
        return stay(["ブランチ: 手元のブランチ一覧が読めないので移らない"])
    head_ref = node.get("headRefName")
    who = "" if not fork else (GONE if fork == GONE else f"fork {fork}")
    fresh = False  # 手元に無く、origin から取って作る
    if is_pr:
        # 番号では探さない——別のブランチに移るのは危ない。名前は gh pr checkout と同じ
        names, make = pr_branch_names(head_ref, fork, default_branch(node))
        target = next((n for n in names if n in branches), None)
        if target is None:
            if make is None:
                return stay([f"ブランチ {head_ref}: {who} の PR で head が既定ブランチ名なので、作る名前を決められない"
                             f"（git fetch origin {pull_ref(num)} → git switch -c <名前> FETCH_HEAD で取る）"])
            target, fresh = make, True
    else:
        target, why = issue_branch(num, branches)
        if target is None:
            return stay([f"ブランチ: {why}"])
    label = f"ブランチ {target}: "
    if fork and not fresh:
        has = contains_head(target, head_oid(node), top)
        if not has:
            why = ("とは照合できない（PR の head の commit を手元に持っていない）" if has is None
                   else "は PR の head の commit を含まない（別物か、head より古い）")
            return stay([label + f"{who} のブランチ。手元の {target} {why}ので移らない。"
                         f"gh pr checkout {num} で取り直せる"])
    if cur == target:
        return [label + "既に居る"], target
    # 片付けた後の一手。origin から作るブランチはまだ無いので git switch では取れない
    nxt = f"もう一度 /catchup {num}（機械が origin から取って作る）" if fresh else f"git switch {target}"
    block, untracked = switch_blocker(top, target, branches.get(target), nxt)
    if block:
        return stay([label + block])
    if fresh:
        # guard を全部通ってから fetch する——止まる木のために origin を叩かない
        src, fail = fetch_source(top, num, node, fork)
        if fail:
            return stay([label + fail[0], *("    " + n for n in fail[1:])])
        args = ("-c", target, "--", src) if fork else ("--track", "-c", target, "--", src)
        # fork の側は「）」で閉じるので、続く「から」の前に空白を置かない
        whence = f"PR の head（origin の {pull_ref(num)}。{who}）" if fork else f"origin/{head_ref} "
        made = f"手元に無かったので {whence}から作って "
    else:
        args, made = ("--", target), ""
    moved, rc, err = git_switch(top, target, args)
    if moved:
        notes = git_notes(err)
        if fork and fresh:
            failed_keys = track_fork(top, target, num, node, fork, url)
            if failed_keys:
                notes.append(f"追跡先を書けなかった（branch.{target}.{' / '.join(failed_keys)}）")
        return [moved_line(label + made, cur, untracked), *("    " + n for n in notes)], target
    verb, refused = (("作れなかった", "（origin からは取れたが git switch -c が拒んだ）") if fresh
                     else ("移れなかった", "（git switch が拒んだ）"))
    if rc is None:
        return stay([label + f"{verb}（{err}）"])
    return stay([label + verb + refused, *("    " + n for n in git_notes(err, failed=True))])


def switch_to_branch(name, cwd=None):
    """ブランチ名で呼ばれたとき、そのブランチへ git switch で移る（仕様の原則 1）。手元に無く origin にだけ有れば
    origin/<name> を追跡するブランチを作って移る。止まる条件は PR のブランチと同じ（switch_blocker）。戻り値は
    (見出しに足す行, 移った・既に居たか)。"""
    top, branches, cur = branch_state(cwd)

    def stay(text):
        return [text + f"（{where_now(top, cur)}）"], False
    if not top:
        return stay("ブランチ: 移らない")
    if branches is None:
        return stay("ブランチ: 手元のブランチ一覧が読めないので移らない")
    label = f"ブランチ {name}: "
    if cur == name:
        return [label + "既に居る"], True
    fresh = name not in branches
    block, untracked = switch_blocker(top, name, branches.get(name), f"git switch {name}")
    if block:
        return stay(label + block)
    args = ("--track", "-c", name, "--", f"origin/{name}") if fresh else ("--", name)
    moved, rc, err = git_switch(top, name, args)
    if moved:
        made = f"手元に無かったので origin/{name} から作って " if fresh else ""
        return [moved_line(label + made, cur, untracked), *("    " + n for n in git_notes(err))], True
    if rc is None:
        return stay(label + f"移れなかった（{err}）")
    return stay(label + ("作れなかった（origin には有るが git switch -c が拒んだ）" if fresh
                         else "移れなかった（git switch が拒んだ）"))


# 「見ていないもの」。端末の報告と HTML の材料が同じ文を使う
COMMIT_UNSEEN = (
    "GitHub の PR / issue（この commit を含む PR があっても見ていない。番号か URL を渡せば出る）",
    "この commit の前後の commit（範囲は親との差 1 つだけ。merge は第 1 親との差）",
    "この commit を誰かが取り込んだか、手元と origin のどちらが先か",
)


def range_unseen(sa, sb):
    return ["GitHub の PR / issue（この範囲を含む PR があっても見ていない。番号か URL を渡せば出る）",
            f"範囲の外の commit（{sa} より前と {sb} より後）と、各 commit の本文（題だけ出した）",
            "この範囲を誰かが取り込んだか、手元と origin のどちらが先か"]


def commit_jump(sha):
    # 飛び先の行番号は commit の版のもの——手元の file は先へ進んでいて別の行（実走で実測）
    return (f"各枠の前の『飛び先 path:行』は commit {sha} の版の行番号（git show {sha}:path で開く）。"
            "AI は箇所の見出しと枠の上の注釈に写す")


def frame_only(rev, frame, jump, what, cwd=None):
    """--frame: その 1 file だけを上限なしの枠で。what は「この commit の変更」など。"""
    text = changemap.frame_diff(cwd=cwd, rev=rev, paths=(frame,))
    if text is None:
        sys.exit("git diff が失敗した（枠は出せない）")
    info = changemap.framed_diff(text).get(frame)
    if not info:
        sys.exit(f"{frame} は{what}に無い（path はリポジトリのルートからの相対）")
    return f"    === {frame} （{jump}）{changemap.lang_tag(frame)}\n" + "\n".join(
        changemap.frame_lines(frame, info, cap=None))


def rev_map(out, rev, paths, tree, cwd, frame_cmd, jump, empty, unseen):
    """commit・範囲の報告の後半（変更の地図と見ていないもの）。変更が無ければ empty の 1 行で終える。
    paths が None は git が読めなかった（「変更なし」と断定しない）。"""
    if paths is None:
        return "\n".join(out + ["", "  変更の地図: 出せない（git diff が失敗した。git show で見る）"])
    if not paths:
        return "\n".join(out + ["", empty])
    out += ["", "## 変更の地図（材料）", TREE_NOTE, *tree]
    # 見出しは frames_section が自分で出す（上限の案内をこの呼び方のコマンドで書くため）
    out += changemap.frames_section(cwd, paths, rev=rev, frame_cmd=frame_cmd, new_from_file=False,
                                    jump_note=jump)
    return "\n".join(out + ["", "見ていないもの:"] + ["  - " + s for s in unseen])


def render_commit(oid, cwd=None, frame=None, full=False):
    """手元の commit（push 済みでも）の報告。GitHub には何も聞かない——この repo のように PR を
    立てずに main へ直接 commit する運用では、変更を読み直す口が他に無い。出す形は PR の地図と
    同じ（木 → 変更の中身の枠と飛び先）——読む人が commit と PR で読み方を変えなくていい。
    frame を渡すとその 1 file だけを上限なしで出す。"""
    rev = changemap.commit_range(oid, cwd)
    head = changemap.git("show", "-s", "--format=%h%n%an%n%ad%n%s%n%b", "--date=short", oid,
                         cwd=cwd) or ""
    short, author, date, subject, *body = head.split("\n")
    jump = commit_jump(short)
    if frame:
        return frame_only(rev, frame, jump, "この commit の変更", cwd)
    paths, tree = changemap.commit_tree(rev, cwd)
    out = [f"# {short} {subject}",
           f"  {author} · {date} · {'分からない' if paths is None else len(paths)} ファイル",
           "  GitHub 側は見ていない——手元の git の commit として出す"]
    lines = [ln.rstrip() for ln in body]
    while lines and not lines[-1]:
        lines.pop()
    shown = lines if full else lines[:BODY_CAP]
    if shown:
        out += ["", "## 本文（材料。作者の言葉。1 文字も変えていない）"] + ["  | " + ln for ln in shown]
    if len(lines) > len(shown):
        out.append(f"  （本文はあと {len(lines) - len(shown)} 行。--full か git show {short} で見る）")
    return rev_map(out, rev, paths, tree, cwd, f"catchup.py {short} --frame", jump,
                   "  変更なし（空の commit か、mode だけの変更）", COMMIT_UNSEEN)


def render_range(rev, cwd=None, frame=None, full=False):
    """commit の範囲 A..B の報告。1 commit と同じ形（commit の一覧 → 木 → 変更の中身の枠と飛び先）で、差は
    A の版と B の版の間。会話の話題がこのセッションの commit 数件に結び付いているとき（「今の修正」）の口——
    話題の形（型と手元だけ）では、全部 push 済みだと何も出ない（実測）。frame はその 1 file だけを上限なしで。"""
    a, b = rev.split("..", 1)
    sa, sb = a[:7], b[:7]
    jump = commit_jump(sb)
    if frame:
        return frame_only(rev, frame, jump, "この範囲の変更", cwd)
    log = changemap.git("log", "--format=%h%x09%ad%x09%an%x09%s", "--date=short", rev, cwd=cwd) or ""
    commits = [ln for ln in log.splitlines() if ln.strip()]
    paths, tree = changemap.commit_tree(rev, cwd)
    ends = ""
    if commits:
        first, last = commits[-1].split("\t", 1)[0], commits[0].split("\t", 1)[0]
        ends = f"（{first} → {last}。{sa} は範囲の外）" if len(commits) > 1 else f"（{first}。{sa} は範囲の外）"
    out = [f"# {sa}..{sb} commit {len(commits)} 件{ends}",
           f"  {'分からない' if paths is None else len(paths)} ファイル · 差は {sa} の版と {sb} の版の間",
           "  GitHub 側は見ていない——手元の git の commit の範囲として出す"]
    shown = commits if full else commits[:BODY_CAP]
    out += ["", "## 範囲の commit（材料。古い順に sha・日付・作者・題。本文は git show <sha>）"]
    for ln in reversed(shown):
        h, d, an, s = (ln.split("\t", 3) + ["", "", ""])[:4]
        out.append(f"  | {h}  {d}  {an}  {s}")
    if len(commits) > len(shown):
        out.append(f"  （commit はあと {len(commits) - len(shown)} 件。--full か git log {rev} で見る）")
    return rev_map(out, rev, paths, tree, cwd, f"catchup.py {sa}..{sb} --frame", jump,
                   "  変更なし（範囲が空か、mode だけの変更）", range_unseen(sa, sb))


def ahead_of_default(cwd=None):
    """PR の無いブランチで、既定ブランチ（origin/HEAD）より先の commit の変更を、木と枠で。ブランチ名で来た人が
    期待するのはブランチ全体の差で、未コミットや tip の 1 commit ではない（読み役の実測。仕様のセクション 11 で決めた）。
    既定ブランチに居る・先の commit が無い・origin が無いときは []。続きの口は git diff -W（この経路の
    --frame は無い）。"""
    base = changemap.default_branch_ref(cwd)
    if not base:
        return []
    count = (changemap.git("rev-list", "--count", f"{base}..HEAD", cwd=cwd) or "0").strip()
    if not count.isdigit() or int(count) == 0:
        return []
    mb = (changemap.git("merge-base", base, "HEAD", cwd=cwd) or "").strip()
    if not mb:
        return []
    rev = f"{mb}..HEAD"
    paths, tree = changemap.commit_tree(rev, cwd)
    out = ["", f"## {base} より先の commit {count} 件の変更（材料。ブランチ全体の差。未コミットは含まない）",
           TREE_NOTE]
    if paths is None:
        return out + ["  読めない（git diff が失敗した）"]
    if not paths:
        return out + ["  変更なし"]
    out += tree
    out += changemap.frames_section(cwd, paths, rev=rev, new_from_file=False,
                                    frame_cmd=f"git diff -W {mb[:7]}..HEAD --",
                                    jump_note="各枠の前の『飛び先 path:行』は HEAD（手元の commit）の行番号。"
                                              "AI は箇所の見出しと枠の上の注釈に写す")
    return out


def render_no_target(cwd=None):
    """PR も番号も無い this の出力。GitHub には何も聞かず、手元のブランチのセクションと、未コミットの変更の
    中身（枠と飛び先）を出す。見出しで「GitHub 側は見ていない」と断る——断らないと、読む人は
    「PR に動きが無い」と読む。中身まで出すのは、PR が無いときこそ木だけでは何をしていたか分からない
    ため（file の一覧は「どこ」しか言わない）。"""
    # 新規 file の先頭は path（ルートからの相対）を cwd に繋いで読むので、ルートを渡す。渡さないと未追跡の
    # 新規 file が 1 つでも有れば Path(None) で落ちて報告が一切出ない（実測）
    cwd = cwd or changemap.repo_top() or os.getcwd()
    branch = changemap.current_branch(cwd) or ""
    wt = changemap.working_tree(cwd)
    frames = changemap.frames_section(cwd, wt[0], frame_cmd="what-am-i-doing.py --frame") if wt[0] else []
    ahead = ahead_of_default(cwd)
    return "\n".join([
        f"# 今のブランチ {branch or '（detached）'}（PR も、名前の番号も無い）",
        "  GitHub 側は見ていない——この呼び方で出るのは手元の git だけ",
        "",
        render_local(why="this で呼んだので出す", cwd=cwd, wt=wt),
        *frames,
        *ahead,
        "",
        "見ていないもの:",
        "  - GitHub の PR / issue（今のブランチに PR が無く、名前にも番号が無い。"
        "番号か URL を渡せば出る）",
        "  - 他のブランチ・他の worktree の状態",
        "  - このセッションで何をしたか（what-am-i-doing.py で出る）",
    ])


def render_local(derived=None, why="", pr_head=None, cwd=None, wt=None, derived_kind="issue"):
    """今のブランチに居るときに出す手元の状態（this で呼んだ、または --switch で移った・既に居た。why は
    その理由）。GitHub に無いものはここにしか出ない。derived は、PR が無くブランチ名の番号を issue と見た
    ときのその番号（申告用）。pr_head は PR の head の commit——手元がそれより後ろなら数えて出す（push して
    いない commit だけ数えると、別の機械から push した後の古い手元が「同期済み」に読める）。wt は
    working_tree の戻り値——呼び手が既に取っていれば渡す（同じ git を 2 回叩かない）。"""
    out = []
    w = out.append
    branch = changemap.current_branch(cwd) or ""
    w(f"## 手元のブランチ {branch or '（detached）'}（{why}）")
    if derived:
        w(f"  今のブランチに PR が無いので、ブランチ名の番号から #{derived} を引いた（{derived_kind} だった。"
          "違えば番号を渡す）")
    # 「push していない」は origin の同名ブランチとの差で数える。@{upstream} だと、origin/main から
    # 切って -u 無しで push したブランチは追跡先が origin/main のままで、push 済みの commit まで
    # 「push していない」に数える（実測）
    remote = f"origin/{branch}" if branch else ""
    if remote and changemap.git("rev-parse", "--verify", "--quiet", remote, cwd=cwd) is not None:
        ahead = changemap.git("log", "--oneline", f"{remote}..HEAD", cwd=cwd)
        label = "push していない commit"
    else:
        upstream = (changemap.git("rev-parse", "--abbrev-ref", "@{upstream}", cwd=cwd) or "").strip()
        ahead = changemap.git("log", "--oneline", "@{upstream}..HEAD", cwd=cwd) if upstream else None
        label = f"origin に {branch or 'このブランチ'} が無い（未 push）。{upstream} より先の commit"
    if ahead is None:
        w("  push していない commit: 分からない（origin に同名のブランチも、追跡先も無い）")
    elif ahead.strip():
        lines = ahead.strip().splitlines()
        w(f"  {label} {len(lines)} 件:")
        for ln in lines[:10]:
            w("    " + ln)
    else:
        w(f"  {label}: なし")
    if pr_head:
        # 持っていない commit を範囲に書くと rev-list が落ちる（None）。それで「持っていない」が分かる
        behind = changemap.git("rev-list", "--count", f"HEAD..{pr_head}", cwd=cwd)
        if behind is None:
            w(f"  PR の head {pr_head[:7]} を手元に持っていない（fetch していない）")
        elif behind.strip() != "0":
            w(f"  PR の head {pr_head[:7]} より {behind.strip()} commit 後ろ（fetch / pull していない）")
    dirty, tree = wt if wt is not None else changemap.working_tree(cwd)
    if dirty is None:
        w("  未コミットの変更: 読めなかった（git status が失敗した）")
    elif dirty:
        w(f"  未コミット {len(dirty)} 件。木（行頭 + が新規・~ が変更・- が削除。"
          "そのまま diff の枠に貼る）:")
        out.extend(tree)
    else:
        w("  未コミットの変更なし")
    return "\n".join(out)


# ---- HTML の材料（--out のときに書き、--render が描く） ------------------------------------
#
# 端末の報告（AI が読む文字の材料）と同じ取得から、雛形（attention/templates/catchup.html）が描く構造を組む。
# ここも事実だけで判断はしない。AI のフィールド（headline・where・turn・next・unseen・explain・figure）は別の JSON で
# 来て、catchup_html が 2 つを雛形に流し込む。形の正本は catchup_html.py の見本（SAMPLE_DATA）と仕様のセクション 5。


def page_base(kind, page, repo, head):
    return {"schema": catchup_html.SCHEMA, "kind": kind, "page": page, "repo": repo,
            "generated": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "head": head, "anchor": "", "anchor_label": "", "mine": None, "events": [], "status": [],
            "links": {"closes": [], "stacked": [], "refs": []}, "unseen": [], "threads": [], "ci": [],
            "views": [], "scale": "", "local": ""}


def page_event(e, me):
    return {"when": hhmm(e["t"]), "min": int(e["t"].timestamp() // 60), "who": me_or(e["who"], me),
            "kind": e["kind"], "cat": e["cat"], "sha": (e.get("oid") or "")[:7] if e["cat"] == PUSH else "",
            "text": excerpt(e["text"], 160)}


def page_turn(node, me, reasons):
    """ターンの札。閉じた件は誰のターンでもない（済み）。理由が無ければ待ちで、誰を待っているかを添える。"""
    if node["state"] != "OPEN":
        return {"kind": "done", "label": "済み", "reasons": [],
                "detail": "merge 済み" if node["state"] == "MERGED" else "close 済み"}
    if not reasons:
        return {"kind": "wait", "label": "待ち", "reasons": [], "detail": waiting_on(node, me)}
    return {"kind": "mine", "label": "私の番", "reasons": reasons, "detail": ""}


def page_status(node, me, red, running, green):
    """止めているものの行（GitHub のマージボックスと同じ並び）。tone は札の色: ok・warn・bad・mine・neutral。"""
    out = []
    add = lambda key, label, value, tone: out.append({"key": key, "label": label, "value": value, "tone": tone})  # noqa: E731
    if node["__typename"] != "PullRequest":
        labels = [lb["name"] for lb in node.get("labels", {}).get("nodes", [])]
        if labels:
            add("labels", "ラベル", ", ".join(labels), "neutral")
    else:
        unresolved = [t for t in node["reviewThreads"]["nodes"] if not t["isResolved"]]
        human = unresolved_threads(node, me)
        mine_n = sum(1 for t in human if t["my_turn"])
        add("threads", "未解決の会話", f"{len(unresolved)} 件（うち人が入っているもの {len(human)} 件）"
            + (f" · 私が返すターン {mine_n} 件" if mine_n else ""),
            "mine" if mine_n else "warn" if human else "ok")
        unseen = ci_unseen(node)
        add("ci", "CI", ci_summary(red, running, green, unseen),
            "bad" if red else "warn" if running or unseen else "ok" if green else "neutral")
        decision = node["reviewDecision"]
        add("approval", "承認", approval(decision),
            "ok" if decision == "APPROVED" else "warn" if decision in ("REVIEW_REQUIRED", "CHANGES_REQUESTED") else "neutral")
        merge = node["mergeable"]
        add("merge", "取り込み", MERGEABLE.get(merge, str(merge)),
            "ok" if merge == "MERGEABLE" else "bad" if merge == "CONFLICTING" else "neutral")
        base = [ln.strip() for ln in base_lines(node, me)]
        if base:
            add("base", "取り込み先", " ／ ".join(re.sub(r"^取り込み先: ", "", ln) for ln in base), "warn")
        if shows_candidates(node, me):
            add("suggested", "依頼先の候補", suggested_line(node).split(": ", 1)[-1], "neutral")
    others = [a["login"] for a in node["assignees"]["nodes"] if a["login"] != me]
    if others:
        add("assignees", "担当", ", ".join(me_or(a["login"], me) for a in node["assignees"]["nodes"]), "neutral")
    return out


def page_threads(node, me, url, by_path, read_lines, since_paths, full):
    """指摘（人が入っている未解決スレッド）。GitHub のスレッドと同じ形にする材料: 指摘の行を含む差分の抜粋
    （差分に無い行なら head の前後の行）・私の最後の発言・相手の最後の発言・前回から file が変わったか。"""
    threads = unresolved_threads(node, me)
    out = []
    for th in (threads if full else threads[:THREAD_CAP]):
        c = th["last"]
        f = by_path.get(th["path"])
        ex = catchup_html.excerpt(f, th["line"], old=th["left"]) if f and th["line"] else None
        if ex is None and th["line"] and not th["left"] and read_lines:
            ex = catchup_html.context_excerpt(th["path"], read_lines(th["path"]), th["line"])
        mine = th.get("mine_last")
        out.append({
            "path": th["path"], "line": th["line"], "left": bool(th["left"]), "my_turn": th["my_turn"], "side_last": th["side_last"], "outdated": bool(th["outdated"]),
            "who": login_of(c["author"]), "when": hhmm(ts(c["createdAt"])),
            "quote": "\n".join(their_lines(c["body"])).strip(),
            "mine": {"when": hhmm(ts(mine["createdAt"])), "quote": excerpt(mine["body"], 300)} if mine else None,
            "href": c.get("url") or (f"{url}/files#{catchup_html.anchor(th['path'])}" if url else ""),
            "excerpt": ex, "changed": None if since_paths is None else th["path"] in since_paths})
    return out, max(0, len(threads) - len(out))


def since_diff_text(owner, name, node, since):
    """私の痕跡以降に作者側が触った file の差分（基準の commit から head まで）。手元に commit が有れば git、
    無ければ GitHub の compare。取り込み（merge）が挟まると base 側の変更がその file に混ざりうる。"""
    if not since or since.get("outside") or since.get("rewritten") or not since.get("files"):
        return None
    base, head = since["base_oid"], node.get("headRefOid")
    paths = [p for _, p in since["files"]]
    top = local_range(owner, name, base, head)
    if top:
        return plain_diff(f"{base}..{head}", top, paths)
    text = gh_try("api", "-H", "Accept: application/vnd.github.diff", f"repos/{owner}/{name}/compare/{base}...{head}")
    return catchup_html.filter_diff(text, paths) if text else None


def pr_views(owner, name, node, since):
    """変更のセクションの見え方: 前回から（私の痕跡以降）と PR 全体。PR 全体は GitHub の Files changed と同じ
    base...head の文脈 3 行（手元に commit が有れば git、無ければ gh pr diff）。"""
    url = node["url"]
    base, head = node.get("baseRefOid"), node.get("headRefOid")
    top = local_range(owner, name, base, head) if base and head else None
    text = plain_diff(f"{base}...{head}", top) if top else None
    if text is None:
        text = gh_pr_diff(owner, name, node["number"])
    since_text = since_diff_text(owner, name, node, since)
    since_paths = [p for _, p in since["files"]] if since_text else []
    views = []
    if since_text and len(since_text) <= MAP_DIFF_CAP:
        authored = since.get("authored") or []
        one = authored[-1][:9] if len(authored) == 1 else ""
        label = one or f"{since['commits']} 本の commit"
        note = f"取り込み {since['merges']} 本の分が混ざりうる" if since["merges"] else ""
        if since["approx"]:
            note = "基準は commit の日付で置いた近似。" + note
        v = catchup_html.view("since", f"前回から（{label} · {len(since_paths)} files）", since_text,
                              url=f"{url}/commits/{authored[-1]}" if one else f"{url}/files/{since['base_oid']}..{head}",
                              note=note)
        v.update(sha=one, label=label)
        views.append(v)
    n = node["changedFiles"]
    if text is None:
        views.append(catchup_html.view("all", f"PR 全体（{n} files）", "", url=f"{url}/files",
                                       note="差分を取れなかった（gh pr diff が失敗した）。"))
    elif len(text) > MAP_DIFF_CAP:
        views.append(catchup_html.view("all", f"PR 全体（{n} files）", "", url=f"{url}/files",
                                       note=f"差分が {len(text)} 文字で大きいので載せない（上限 {MAP_DIFF_CAP}）。"))
    else:
        views.append(catchup_html.view("all", f"PR 全体（{n} files）", text, since_paths=since_paths))
    # 指摘の「前回から変わったか」は差分の文字でなく file の一覧で決める（差分を取れなくても一覧は在る）。
    # 基準を置けない（私の痕跡が無い・窓の外・書き換え）なら分からないので None
    valid = since is not None and not since.get("outside") and not since.get("rewritten")
    return views, ({p for _, p in since["files"]} if valid else None)


def page_unseen(caps, unlinked, since, more_threads, ci_more, threads, ask):
    """「見ていないもの」（HTML の末尾）。端末の報告の同じセクションから、HTML では見えているもの（差分の全文・
    発言の全文の口）を除いた分。"""
    out = [cap_text(*cap) for cap in caps]
    out.append("GitHub の外（チャット・口頭・メール）でのやり取り")
    if threads:
        out.append("指摘のスレッドの途中の発言（私と相手の最後の発言だけを出した）")
    if more_threads:
        out.append(f"指摘の残り {more_threads} 件（上限 {THREAD_CAP} 件。--full で出る）")
    if ci_more:
        out.append(f"赤の残り {ci_more} 件のログ（上限 {CI_RED_CAP} 件。--full で出る）")
    if since is not None:
        out.extend(since_unseen(since))
    if unlinked:
        out.append(f"GitHub の login に結び付いていない commit（名前: {', '.join(unlinked)}）が誰のものか")
    out.append("名指しの無い発言が私への問いかどうか"
               + ("（私の件なので、最後の 1 件だけは材料に出した）" if ask and ask.get("unaddressed") else ""))
    return out


def page_item(node, owner, name, me, ev, refs, unlinked, anchor, anchor_kind, caps, *, full, stacked, since,
              with_map, with_threads, ci, read_lines, local_text):
    """PR / issue の材料。ci は ci_failures の戻り値（取っていなければ None）。"""
    is_pr = node["__typename"] == "PullRequest"
    red, running, green = check_state(node) if is_pr else ([], 0, 0)
    reasons, ask, _, _ = turn_reasons(node, me, ev, red)
    head = {"kind": "pr" if is_pr else "issue", "ref": f"#{node['number']}", "title": node["title"], "url": node["url"],
            "state": node["state"].lower(), "draft": bool(node.get("isDraft")),
            "author": me_or(login_of(node["author"]), me), "role": role_of(node, me, ev),
            "turn": page_turn(node, me, reasons),
            "files": node.get("changedFiles"), "additions": node.get("additions"), "deletions": node.get("deletions"),
            "notes": []}
    if is_pr and head_oid(node):
        head["oid"] = head_oid(node)  # 差分の外のファイル（受け先の API の形など）を、描くときにこの版から読む
    page = page_base(head["kind"], f"{owner}-{name}/{node['number']}", f"{owner}/{name}", head)
    anchor_t = anchor["t"] if anchor else ts(node["createdAt"])
    page["anchor"] = anchor_kind
    page["anchor_label"] = {"mine": "前回から", "handover": "渡されてから"}.get(anchor_kind, "作られてから")
    if anchor:
        page["mine"] = page_event(anchor, me)
    page["events"] = [page_event(e, me) for e in ev if e["t"] > anchor_t]
    page["status"] = page_status(node, me, red, running, green)
    linked = closing_issues(node)
    page["links"] = {"closes": [{"number": i["number"], "state": i["state"].lower(), "title": i["title"]} for i in linked],
                     "stacked": [{"number": s["number"], "title": s["title"]} for s in (stacked or ())[:STACKED_SHOWN]],
                     "refs": [{"when": hhmm(r["t"]), "text": r["text"]} for r in refs[-3:]]}
    more_threads = 0
    if is_pr and with_map:
        page["views"], since_paths = pr_views(owner, name, node, since)
        page["scale"] = scale_text(node, owner, name)
    else:
        since_paths = None
    if is_pr and with_threads:
        all_view = next((v for v in page["views"] if v["id"] == "all"), None)
        by_path = {f["path"]: f for f in catchup_html.parse_diff(all_view["text"])} if all_view else {}
        page["threads"], more_threads = page_threads(node, me, node["url"], by_path, read_lines, since_paths, full)
    ci_more = 0
    if ci is not None:
        page["ci"], ci_more = ci
    page["local"] = local_text or ""
    page["unseen"] = page_unseen(caps, unlinked, since, more_threads, ci_more, page["threads"], ask)
    # 端末の報告と同じく、上限で切れた分の後ろに
    page["unseen"][len(caps):len(caps)] = judge_cap_lines(node, me)
    if stacked is None:
        page["unseen"].append(f"このブランチを base にする PR（gh pr list --base {node.get('headRefName')} が失敗して読めなかった）")
    return page


def local_slug(cwd=None):
    """手元の git の対象（commit・範囲・手元のブランチ）の置き場の名前と owner/repo。origin が無ければルートの名前。"""
    top = changemap.repo_top(cwd)
    repo = changemap.repo_of(changemap.origin_url(top)) if top else None
    if repo:
        return repo.replace("/", "-"), repo
    return "local-" + catchup_html._safe(os.path.basename(top) if top else "unknown"), ""


def plain_diff(rev, cwd=None, paths=(), opts=()):
    """git diff の本文。失敗なら None。複写の探し（diff.renames=copies）は止める——端末の枠（changemap.no_copies）と同じく、
    複写先を元との差にすると、そのままの複写は中身が無い。"""
    return changemap.git("-c", "core.quotePath=false", "diff", *changemap.DIFF_SANE, *changemap.no_copies(cwd), *opts,
                         rev, "--",
                         *changemap.pathspecs(paths), cwd=cwd)


def local_head(kind, ref, title, author="", notes=()):
    """手元の git の対象（commit・範囲・手元のブランチ）の見出し。GitHub の札（状態・ターン・規模）は空。"""
    return {"kind": kind, "ref": ref, "title": title, "url": "", "state": "", "draft": False,
            "author": author, "role": "", "turn": {"kind": "none", "label": "", "reasons": [], "detail": ""},
            "files": None, "additions": None, "deletions": None, "notes": [*notes, "GitHub 側は見ていない"]}


def page_commit(oid, cwd=None):
    rev = changemap.commit_range(oid, cwd)
    short, author, date, subject = ((changemap.git("show", "-s", "--format=%h%n%an%n%ad%n%s", "--date=short", oid,
                                                   cwd=cwd) or "").split("\n") + ["", "", "", ""])[:4]
    slug, repo = local_slug(cwd)
    text = plain_diff(rev, cwd)
    head = local_head("commit", short, subject, author, [date])
    page = page_base("commit", f"{slug}/commit-{short}", repo, head)
    page["views"] = [catchup_html.view("all", f"この commit（{len(catchup_html.parse_diff(text))} files）", text)] if text else []
    page["unseen"] = list(COMMIT_UNSEEN)
    return page


def page_range(rev, cwd=None):
    a, b = rev.split("..", 1)
    sa, sb = a[:7], b[:7]
    n = len([ln for ln in (changemap.git("log", "--format=%h", rev, cwd=cwd) or "").splitlines() if ln.strip()])
    slug, repo = local_slug(cwd)
    text = plain_diff(rev, cwd)
    head = local_head("range", f"{sa}..{sb}", f"commit {n} 件")
    page = page_base("range", f"{slug}/range-{catchup_html._safe(sa)}-{catchup_html._safe(sb)}", repo, head)
    page["views"] = [catchup_html.view("all", f"この範囲（{len(catchup_html.parse_diff(text))} files）", text)] if text else []
    page["unseen"] = range_unseen(sa, sb)
    return page


def page_local(cwd=None, pre_lines=()):
    """PR も番号も無いブランチ。未コミットの変更（追跡している file）と、既定ブランチより先の commit の差。
    pre_lines はブランチ名で移った行で、手元のセクションの前に置く（PR の page_item と同じ並び）。"""
    cwd = cwd or changemap.repo_top() or os.getcwd()
    branch = changemap.current_branch(cwd) or ""
    slug, repo = local_slug(cwd)
    head = local_head("local", branch or "（detached）", f"今のブランチ {branch or '（detached）'}")
    page = page_base("local", f"{slug}/branch-{catchup_html._safe(branch or 'detached')}", repo, head)
    views = []
    text = plain_diff(changemap.diff_base("HEAD", cwd), cwd)  # commit がまだ無ければ空の木と比べる（端末と同じ）
    if text:
        views.append(catchup_html.view("local", f"未コミット（{len(catchup_html.parse_diff(text))} files）", text,
                                       note="追跡している file だけ。未追跡の新規 file は手元のセクションの木に出る。"))
    base = changemap.default_branch_ref(cwd)
    mb = (changemap.git("merge-base", base, "HEAD", cwd=cwd) or "").strip() if base else ""
    ahead = plain_diff(f"{mb}..HEAD", cwd) if mb else ""
    if ahead:
        views.append(catchup_html.view("ahead", f"{base} より先（{len(catchup_html.parse_diff(ahead))} files）", ahead))
    page["views"] = views
    page["local"] = "\n".join([ln.strip() for ln in pre_lines] + [render_local(why="this で呼んだので出す", cwd=cwd)])
    page["unseen"] = ["GitHub の PR / issue（今のブランチに PR が無く、名前にも番号が無い。番号か URL を渡せば出る）",
                      "他のブランチ・他の worktree の状態"]
    return page


def render_command(data_path, fields_path):
    """--render: 材料（--out が書いた JSON。会話の話題なら -）と AI のフィールドを雛形に流し込み、path と 1 行を出す。"""
    def load(path, what):
        try:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        except OSError as e:
            sys.exit(f"{what} {path} が読めない（{e.strerror or e}）")
        except ValueError as e:
            sys.exit(f"{what} {path} が JSON として読めない（{e}）")
    data = None if data_path == "-" else load(data_path, "材料")
    if data is not None and (not isinstance(data, dict) or data.get("schema") != catchup_html.SCHEMA):
        sys.exit(f"材料 {data_path} の形が違う（版 {catchup_html.SCHEMA} の catchup.py --out が書いたものを渡す。"
                 "走らせ直せば新しく書く）")
    fields = load(fields_path, "フィールドの JSON")
    # 図や変更点が差分の外のファイルを指したら、PR の先頭の版から読む（手元に同じ commit が有れば git show、無ければ GitHub）
    owner, _, name = ((data or {}).get("repo") or "").partition("/")
    oid = ((data or {}).get("head") or {}).get("oid")
    read = head_reader(owner, name, oid) if owner and name and oid else None
    errs = catchup_html.validate_fields(fields, need_title=data is None, data=data, read=read)
    if errs:
        print(f"フィールドの JSON {fields_path} を直す所が {len(errs)} 件ある:", file=sys.stderr)
        for e in errs:
            print("  - " + e, file=sys.stderr)
        return 2
    path, line = catchup_html.write_page(data, fields, read=read)
    print(path)
    print(line)
    print(catchup_html.open_in_vscode(path), file=sys.stderr)
    return 0


def setup_command(check):
    code, lines = catchup_html.setup(check=check)
    print("\n".join(lines))
    return code


def collect_caps(node):
    caps = []
    for field, label in (("comments", "コメント"), ("reviews", "レビュー"),
                         ("reviewThreads", "スレッド"), ("allCommits", "コミット")):
        conn = node.get(field)
        if conn and conn.get("totalCount", 0) > len(conn["nodes"]):
            caps.append((label, conn["totalCount"], len(conn["nodes"])))
    # CI のチェックは先頭の 100 件だけ取る。切れていれば「全 pass」は取った分だけの話（/whose-turn の limits_of_pr と同じ）
    for h in node.get("head", {}).get("nodes", [])[:1]:
        conn = (h["commit"].get("statusCheckRollup") or {}).get("contexts")
        if conn and conn.get("totalCount", 0) > len(conn["nodes"]):
            caps.append((CHECKS, conn["totalCount"], len(conn["nodes"])))
    return caps


def parser():
    p = argparse.ArgumentParser(
        description="1 件の PR / issue について、前回自分が触ってから何が起きたかを出す")
    p.add_argument("words", nargs="*", metavar="対象 [焦点]",
                   help="対象は番号か PR / issue の URL、または手元の commit（sha・HEAD~2・タグ・ブランチ名。"
                        "GitHub は見ない）、または commit の範囲 A..B（2971ea2..HEAD・HEAD~4..HEAD。差は A の版と"
                        " B の版の間）。無ければ（または this なら）今のブランチの "
                        "PR、それも無ければブランチ名の番号を引く。末尾の材料は有れば全部出る"
                        "（地図は PR なら常に、指摘は人が入っている未解決スレッドが有れば、CI は赤が"
                        "有れば）。焦点の語 指摘・地図・CI を後ろに付けると、その 1 つに絞る")
    p.add_argument("-R", "--repo", help="owner/repo（URL を渡すときは不要）")
    p.add_argument("--me", help="基準にする login（既定は gh の認証ユーザ）。指定すると、"
                   "手元の git config の user.email による commit の照合はしない")
    p.add_argument("--full", action="store_true",
                   help="発言と本文を全文で出す（本文の 60 行、閉じる issue の冒頭 12 行、指摘 10 件、"
                        "CI の赤 3 件の上限も外す）")
    p.add_argument("--limit", type=int, default=12,
                   help="その後に起きたことの表示件数（既定 12）")
    p.add_argument("--frame", metavar="path",
                   help="本体の報告を出さず、この file の変更だけを関数まるごとの枠で全部出す（上限なし。"
                        "PR と commit で使える。手元の未コミットは what-am-i-doing.py --frame）")
    p.add_argument("--switch", action="store_true",
                   help="該当ブランチへ git switch で移る（PR は head のブランチ、issue は名前に番号を持つ"
                        "手元のブランチが 1 本のとき）。PR のブランチが手元に無ければ origin からその 1 本だけ"
                        " fetch して作る（名前と追跡先は gh pr checkout と同じ）。追跡ファイルに未コミットが"
                        "あれば移らない。手元にあるブランチは動かさない（pull・stash・gh pr checkout はしない）。"
                        "this では何もしない")
    p.add_argument("--render", nargs=2, metavar=("材料.json", "フィールド.json"),
                   help="--out が書いた材料（会話の話題なら -）と AI が書いたフィールドの JSON を雛形に流し込み、"
                        "~/.cache/attention/catchup/<owner>-<repo>/<番号>.html を書いて index を組み直す。"
                        "出すのはページの path と 1 行の要約。ATTENTION_CATCHUP_OPEN=0 でなければ VS Code の窓で開く")
    p.add_argument("--setup", action="store_true",
                   help="HTML を VS Code で見る準備（生きた窓・拡張 Simple HTML Viewer・Machine の設定 2 つ）を確かめ、"
                        "足りなければ入れて、見本を描いて開く")
    p.add_argument("--check", action="store_true", help="--setup と一緒に: 何も変えずに確かめて報告だけする")
    outfile.add_flag(p)
    return p


def main(argv=None):
    a = parser().parse_args(argv)
    if a.render:
        if a.words or a.setup or a.check:
            sys.exit("--render は材料とフィールドの JSON の 2 つだけを取る（対象・--setup と一緒に使えない）")
        return render_command(*a.render)
    if a.setup:
        if a.words:
            sys.exit("--setup は対象を取らない")
        return setup_command(a.check)
    if a.check:
        sys.exit("--check は --setup と一緒に使う（何も変えずに準備を確かめる）")

    sink = {}  # HTML の材料。--out のときだけ組んで JSON に書く（組むのに gh と git を余分に呼ぶ）
    if not a.out:
        return report(a)
    code = outfile.run_to_file(lambda: report(a, sink), "catchup")
    if sink.get("page"):
        path = catchup_html.save_data(sink["page"])
        print(f"描く材料は {path} に書いた。フィールドの JSON を書いて catchup.py --render {path} <フィールドの JSON> で描く")
    elif sink.get("error"):
        print(f"描く材料を組めなかった（{sink['error']}）。ページは描けない——報告のファイルを読んで端末で返す")
    return code


def report(a, sink=None):
    """端末の報告を出す。sink（dict）を渡すと、HTML の材料を sink["page"] に入れる（--frame では入れない）。"""
    def keep(build):
        # 描く材料は文字の材料の後で組む。組めなくても文字の材料（AI が読む本体）は落とさない
        if sink is not None and not a.frame:
            try:
                sink["page"] = build()
            except Exception as e:  # noqa: BLE001 — 落とすと、取り終えた文字の材料まで失われる
                sink["error"] = f"{type(e).__name__}: {e}"
    target, focus = split_words(a.words)
    owner, name, num, local = resolve_target(target, a.repo)
    pre_lines = []  # ブランチ名で移った・移らなかったの行（見出しに足す）
    if local == "branchname":
        # 原則 1: 指定があればそこへ移ってから追いつく。移れたら this と同じに解く。移れなければ、そのブランチの
        # PR が有れば PR として（手元のセクションは無し）、無ければブランチの tip の commit として出す
        pre_lines, on = switch_to_branch(num) if a.switch else (
            ["ブランチ: --switch を付けていないので移らない（今のブランチのまま）"], False)
        if on:
            owner, name, num, local = resolve_target("this", a.repo)
        else:
            url = gh_try("pr", "view", num, "--json", "url", "-q", ".url") or ""
            m = URL_RE.match(url.strip())
            if m:
                owner, name, num, local = m.group(1), m.group(2), int(m.group(3)), None
            else:
                print("\n".join("  " + ln for ln in pre_lines))
                print()
                # origin にだけ在るブランチは、短い名前では rev-parse が解けない（refs/remotes/origin/ を付けて引く）
                oid = changemap.commit_oid(num) or changemap.commit_oid(f"refs/remotes/origin/{num}")
                if not oid:
                    sys.exit(f"ブランチ {num} の tip の commit が引けない（手元にも origin/{num} にも無い）")
                print(render_commit(oid, frame=a.frame, full=a.full))
                keep(lambda: dict(page_commit(oid), local="\n".join(ln.strip() for ln in pre_lines)))
                print()
                print(f"（移っていないので、ブランチ {num} の tip の commit として出した。ブランチ全体の差は移ってから this で）")
                return 0
    if local in ("range", "commit"):
        is_range = local == "range"
        if a.switch:
            print(f"ブランチ: {'commit の範囲' if is_range else 'commit '}には移る先が無い（--switch は何もしない）")
            print()
        print((render_range if is_range else render_commit)(num, frame=a.frame, full=a.full))
        keep(lambda: (page_range if is_range else page_commit)(num))
        # 地図は commit にも出る（上で出した）。指摘・CI だけが PR / issue の材料。語は人の語で
        # （内部 key の threads / ci を出すと、スキルの文書のどの語にも結び付かない。実測）
        rest = focus_words(focus - {"map"})
        if rest:
            print()
            print(f"（{rest} の材料は PR / issue のもの。commit には無い）")
        return 0
    if local == "none":
        # PR も番号も無い。GitHub には聞かず、手元のブランチだけ出す（gh も走らせない）
        if a.frame:
            sys.exit("--frame は PR か commit でだけ使える（今のブランチに PR が無い。手元の未コミットの 1 file は"
                     " what-am-i-doing.py --frame path で）")
        if pre_lines:
            # ブランチ名で移った先に PR も番号も無い。移ったことは見出しに残す（「移らない」と言わない）
            print("\n".join("  " + ln for ln in pre_lines))
            print()
        elif a.switch:
            print("ブランチ: this では移らない（今のブランチのまま）")
            print()
        print(render_no_target())
        keep(lambda: page_local(pre_lines=pre_lines))
        if focus:
            print()
            print(f"（{focus_words(focus)} の材料は PR / issue のもの。今のブランチには PR が無い）")
        return 0
    if a.frame:
        # 1 file の変更だけを関数まるごとの枠で。地図の 1 file の上限で切れた続きを見るための口。
        # 本体の報告は組まないので、gh は base と head の 2 値を取る 1 回（と手元に commit が無いときの
        # pr diff）だけ——本体の GraphQL（発言・レビュー・スレッド・commit・timeline）は要らない
        got = gh_try("pr", "view", str(num), "-R", f"{owner}/{name}", "--json", "baseRefOid,headRefOid")
        if got is None:
            sys.exit("--frame は PR でだけ使える（issue には diff が無い）。PR なら gh pr view が失敗した")
        node = json.loads(got)
        wide, note = pr_function_diff(owner, name, node, lambda: gh_pr_diff(owner, name, num))
        if wide is None:
            sys.exit("diff が取れない（gh pr diff が失敗した）")
        info = changemap.framed_diff(wide).get(a.frame)
        if not info:
            sys.exit(f"{a.frame} はこの PR の変更に無い（改名だけの file も含む。path はリポジトリのルートからの相対）")
        print(f"    === {a.frame} " + ("（新規）" if info["new"] else f"（{changemap.JUMP_NOTE}）")
              + (f"（{note}）" if note else "") + changemap.lang_tag(a.frame))
        print("\n".join(changemap.frame_lines(a.frame, info, cap=None)))
        return 0
    me = a.me or gh("api", "user", "--jq", ".login").strip()
    # 他人を基準にするときは、手元の git config はその人のものではないので照合しない
    my_email = "" if a.me else local_email()
    node = fetch(owner, name, num)
    is_pr = node["__typename"] == "PullRequest"
    # 移るのは render より前——地図の「同じ階層の既存」は手元の HEAD から数えるので、移った後のブランチで描く。
    # this で呼んだときは今のブランチが対象なので何もしない
    # ブランチ名で移った（または移れなかった）行は見出しに足す。PR のブランチへの switch は重ねない
    branch_lines, on_branch = list(pre_lines), None
    if a.switch and not pre_lines:
        branch_lines, on_branch = (["ブランチ: this では移らない（今のブランチのまま）"], None) if local \
            else switch_branch(owner, name, num, node)
    ev, refs, unlinked = collect_events(node, me, my_email)
    anchor, anchor_kind = find_anchor(ev, node, me)
    with_map, with_threads, with_ci = pick_tails(
        is_pr, focus, bool(unresolved_threads(node, me)),
        bool(check_state(node)[0]) if is_pr else False)
    # 積まれている先（gh 1 回）と私の痕跡以降に変わった file（git 1 回か gh 数回）は独立で、どちらも
    # 本体の前に要る。直列だと足し算の待ちになるので、片方を裏で走らせる。私の痕跡が無い（渡された
    # だけ・作成時）なら基準が無いので後者は無い
    stacked, since = (), None
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
        job = ex.submit(fetch_stacked, owner, name, node) if is_pr else None
        if is_pr and anchor_kind == "mine":
            since = collect_since(
                node, anchor, functools.partial(since_files_git, owner, name),
                lambda sha: gh_try("api", f"repos/{owner}/{name}/commits/{sha}", "--jq", COMMIT_FILES_JQ))
        stacked = job.result() if job else ()
    print(render(node, me, ev, refs, unlinked, anchor, anchor_kind, a.full, a.limit,
                 collect_caps(node), with_map=with_map, with_threads=with_threads,
                 with_ci=with_ci, branch_lines=branch_lines, stacked=stacked, since=since))
    # 並びは、作者の言葉（本文。どの呼び方でも出る）→ 私が動く材料（指摘・CI）→ 読み直す材料（地図）
    # → GitHub に無い手元の状態
    tails = [render_body(node, a.full, lambda n: fetch_ref(owner, name, n))]
    pr_head = head_oid(node)  # issue なら None
    read_lines = head_reader(owner, name, pr_head) if with_threads else None
    if with_threads:
        tails.append(render_threads(node, me, read_lines, full=a.full,
                                    diff_since=since_differ(owner, name, pr_head)))
    ci = ci_failures(node, owner, name, full=a.full) if with_ci else None
    if with_ci:
        tails.append(render_ci(node, owner, name, full=a.full, failures=ci))
    if with_map:
        tails.append(render_map(node, owner, name))
    local_text = ""
    if local or on_branch:
        local_text = render_local(
            num if local == "branch" else None,
            "this で呼んだので出す" if local else "--switch でこの件のブランチに居るので出す",
            pr_head=pr_head, derived_kind="PR" if is_pr else "issue")
        tails.append(local_text)
    keep(lambda: page_item(
        node, owner, name, me, ev, refs, unlinked, anchor, anchor_kind, collect_caps(node), full=a.full,
        stacked=stacked, since=since, with_map=with_map, with_threads=with_threads, ci=ci, read_lines=read_lines,
        local_text="\n".join([ln.strip() for ln in branch_lines] + ([local_text] if local_text else []))))
    if not is_pr and focus:
        tails.append("（issue には地図・指摘・CI の材料は無い）")
    for t in tails:
        print()
        print(t)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
    except SystemExit:
        raise
    except Exception as e:  # noqa: BLE001 — 想定外は 2 で落とす（1 は「見つからない」に使う）
        sys.exit(f"catchup.py が想定外の例外で停止: {type(e).__name__}: {e}")
