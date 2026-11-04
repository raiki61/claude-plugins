"""その件に関わっている人の事実。/whose-turn・/catchup・/milestone-map で共用。

置くのは GitHub の材料から読み取る事実だけ（担当者とその種別・Linked PR の作者・閉じた人と閉じ方・login の取り方・
返答できる人か）。その事実から「誰のターンか」（turn.py）や「誰が進めているか」（milestone-map.py の doers）を決める
規則は、各コマンドの側に置く。同じ事実を各スクリプトが別々に読むと、片方だけ直って食い違う（持ち主 2026-11-04
「それぞれ担保してるロジックはmyturnと共有してるだろうが、それを綺麗に担保していかないと修正で崩れるのは怖いね」）。
素の dict だけで決める純関数にしてあるので、gh に触らず全分岐を試験できる（tests/people-suite.py。同じ試験が、ほかの
スクリプトがここの事実を読み直していないことも見る）。

人の種別（User・Bot・Mannequin・Organization・退会済み〔null〕）の扱いは、問いごとに違ってよく、名前を分けてここに置く:
- answerable: 返答できる人か（User だけ）。ターンを渡せる相手か、に使う（turn.py）。Bot は一覧を読まないので渡せない。
- ghtext.is_bot: Bot か。人の発言か、に使う（Mannequin と退会済みは人の側）。
- assigned_people: 担当者のうち返答できる人。種別の取れない GitHub（assigneeKindsUnknown）では login の取れた全員。
- logins: 担当者の login を種別を見ずに全部。/milestone-map の「誰が進めているか」は、Copilot の coding agent など
  Bot に振った issue も、その Bot が進めている物として数える（GitHub では Copilot を Assignees に入れると、Copilot が
  進めて PR を出す。https://docs.github.com/en/copilot/how-tos/use-copilot-agents/cloud-agent/use-cloud-agent-on-github
  の「Assigning an issue to Copilot」）。ターンの持ち主の規則（返答できる人にしか渡さない。turn.owners と /whose-turn の
  判定）とは問いが違うので、揃えない。
  /catchup の担当者の表示と、自分が担当かの理由（reason_table）も、今は logins で Bot を含む。
  ただし手で閉じた人（closer_of）は Bot を数えない（stale の Bot が閉じた物は、誰かが進め終えた物ではない）。
- requested_person: レビューの依頼先が人か（User か Team）。Bot（Copilot など）宛の依頼は依頼に数えない。
- team_slug: レビューの依頼先が Team なら、その org/slug。
"""

# この本文は複数のプラグインに写しで在る。正本は attention/scripts/lib/people.py、写しは works-dispatch/dispatch/vendor/lib/people.py。
# 直すのは正本だけで、配るのは python3 scripts/shared-copies.py --sync attention/scripts/lib/people.py。

from ghtext import is_bot

# assignees は UserConnection で種別を持たず、Copilot 等の Bot を人と見分けられない。assignedActors は
# Assignee union（Bot・Mannequin・Organization・User）なので種別が取れる。別名で受けて下流の形を変えない
KINDS_FIELD = "assignedActors"
ASSIGNEES = f"assignees: {KINDS_FIELD}(first: 10) {{ totalCount nodes {{ __typename ... on Actor {{ login }} }} }}"
# UserConnection の __typename はいつも User で、Bot も人と名乗る。種別は取らない
LEGACY_ASSIGNEES = "assignees(first: 10) { totalCount nodes { login } }"


def login(actor):
    # 退会済みユーザーの author は null で返る
    return (actor or {}).get("login")


def answerable(actor):
    """返答できる人の login。User だけで、Bot・Mannequin・Organization・退会済み（null）は None。
    login の有無で見分けると、クエリのフラグメントに Bot { login } を足した途端 Bot が人になる"""
    return actor["login"] if (actor or {}).get("__typename") == "User" else None


def assignee_nodes(node):
    """担当者の生の並び（種別と login）。材料に担当者が無ければ空"""
    return (node.get("assignees") or {}).get("nodes") or []


def assigned_people(node):
    """担当者のうち返答できる人の login。種別が取れない GitHub では人か Bot か分からないので、login の取れた全員"""
    read = login if node.get("assigneeKindsUnknown") else answerable
    return [p for p in map(read, assignee_nodes(node)) if p]


def logins(node):
    """担当者の login を、GitHub の並びのまま種別を見ずに全部（Bot も入る）。表示と、Bot も数える問いに使う"""
    return [a["login"] for a in assignee_nodes(node)]


def requested_person(reviewer):
    """レビューの依頼先が人（User か Team）か。Copilot などの Bot 宛の依頼は依頼に数えない（/whose-turn・/catchup）。
    クエリは Bot に login を取らない（GHES の古い版の RequestedReviewer には Bot が無く、fragment を書くとクエリごと
    落ちる）ので、login の有無で見分けると Bot 宛が名前の無い依頼先として残る"""
    return (reviewer or {}).get("__typename") in ("User", "Team")


def team_slug(reviewer):
    """レビューの依頼先が Team ならその org/slug（combinedSlug）。Team でなければ None"""
    return reviewer["combinedSlug"] if (reviewer or {}).get("__typename") == "Team" else None


def linked_prs(issue, state="OPEN"):
    """issue を閉じる Linked PR（closedByPullRequestsReferences）のうち state の物の [番号, 作者の login] の並び。
    退会済みの作者は None。Bot の作者も入る"""
    nodes = (issue.get("closedByPullRequestsReferences") or {}).get("nodes") or []
    return [[p["number"], login(p.get("author"))] for p in nodes if p.get("state") == state]


def closer_of(issue):
    """閉じた人と閉じ方 (login, "pr" か "hand")。最後の ClosedEvent の、閉じたのが PR ならその PR を出した人（"pr"）。
    PR でなく閉じた物（手で閉じた・commit で閉じた・PR の作者のアカウントが消えた）は、担当者が居なければ閉じる操作を
    した人（"hand"）、居れば (None, None)（担当者を実質の担当とする）。ただし手で閉じた物は、完了（stateReason が
    COMPLETED）で閉じた物だけを数え、Bot が閉じた物と、not planned・duplicate で閉じた物は誰の仕事にもしない（stale の
    Bot や、重複を閉じて回った人が、仕事を終えた人に見えないように）。"""
    ev = ((issue.get("timelineItems") or {}).get("nodes") or [None])[-1] or {}
    by = login((ev.get("closer") or {}).get("author"))
    if by:
        return by, "pr"
    actor = ev.get("actor")
    done = issue.get("stateReason") in (None, "COMPLETED") and not is_bot(actor)
    who = None if assignee_nodes(issue) or not done else login(actor)
    return (who, "hand") if who else (None, None)
