"""PR の番の述語と、2 本の gh の呼び方の共通の判定。/whose-turn と /catchup で共用。

同じ規則を 2 本のスクリプトに別々に書くと、並行の直しが片方ずつ延びて食い違う（実測 2026-10-02:
変更要求の後にそのレビュアーへ再依頼しても、両方が同じ近道で作者に指摘対応を立て続けた。持ち主の
判定も、/catchup だけが login で数える写しを持ち、Bot だけが assignee の PR を担当待ちと出していた）。
素の dict だけで決める純関数にしてあるので、gh に触らず全分岐を検査できる。
"""

import json

# 人ごとの最新の意見（APPROVED・CHANGES_REQUESTED・DISMISSED）。reviews の窓から人ごとに出すと、作者が
# スレッドに返すたびにできる COMMENTED で窓が埋まり、窓の外の変更要求を見落として番を誤って外す
OPINIONS = "latestOpinionatedReviews(first: 30) { totalCount nodes { state author { __typename login } } }"

# assignees は UserConnection で種別を持たず、Copilot 等の Bot を人と見分けられない。assignedActors は
# Assignee union（Bot・Mannequin・Organization・User）なので種別が取れる。別名で受けて下流の形を変えない
KINDS_FIELD = "assignedActors"
ASSIGNEES = f"assignees: {KINDS_FIELD}(first: 10) {{ totalCount nodes {{ __typename ... on Actor {{ login }} }} }}"
LEGACY_ASSIGNEES = "assignees(first: 10) { totalCount nodes { login } }"


def graphql_errors(out):
    try:
        data = json.loads(out)
    except ValueError:
        return None
    return data.get("errors") if isinstance(data, dict) else None


def after_gh_failure(args, attempt, stderr, stdout):
    """gh が非 0 で終わった後の手。"retry"・"body"（本文を返す）・None（止める）。

    一時的な失敗かは状態だけで先に決める——gh は 2xx 以外でも JSON の本文を stdout に出すので、本文の errors を
    先に見ると 504 が再試行されずに返る（octokit の plugin-retry も状態で決める）。GraphQL のエラーは、gh が
    本文を stdout に出して非 0 で終わる（cli/cli の pkg/cmd/api の processResponse）。ここで止めると、呼び手の
    errors の読み（欄の無い GitHub での取り直し）に届かない"""
    if "504" in stderr and attempt == 1:
        return "retry"
    if args[:2] == ("api", "graphql") and graphql_errors(stdout):
        return "body"
    return None


def missing_only(errors, fields):
    """エラーが全部、fields に挙げた欄をその GitHub が持たないこと（graphql-ruby の静的検証の undefinedField）か"""
    return bool(errors) and all(
        (e.get("extensions") or {}).get("code") == "undefinedField" and e["extensions"].get("fieldName") in fields
        for e in errors
    )


def login(actor):
    # 退会済みユーザーの author は null で返る
    return (actor or {}).get("login")


def is_bot(actor):
    return (actor or {}).get("__typename") == "Bot"


def answerable(actor):
    """返答できる人の login。User だけで、Bot・Mannequin・Organization・退会済み（null）は None。
    login の有無で見分けると、クエリのフラグメントに Bot { login } を足した途端 Bot が人になる"""
    return actor["login"] if (actor or {}).get("__typename") == "User" else None


def is_team(node):
    return (node or {}).get("__typename") == "Team"


def is_reviewer(node):
    """レビュー依頼の依頼先に数えるか。Copilot 等の Bot・Mannequin・退会済み（null）宛は数えない"""
    return bool(answerable(node)) or is_team(node)


def window_cut(conn, size):
    """last: size で取った接続の窓より前にも項目があるか。

    hasPreviousPage は itemTypes で絞った後の意味（実測 2026-10-02・IL-SW-AI/guided-resolver #1901:
    REVIEW_REQUESTED_EVENT に絞ると該当 2 件・totalCount 61 で、last:1 は真、last:2・last:3 は偽）。totalCount は
    絞る前の数なので（#1471 は履歴 5 件のうち対象 1 件）件数と比べられない。pageInfo を取らない接続だけ件数で見る"""
    info = conn.get("pageInfo")
    if info is None:
        return len(conn["nodes"]) >= size
    return info.get("hasPreviousPage") is not False


def assignee_logins(pr):
    """事実の行に出す assignee。Bot も並べる"""
    return [p for p in map(login, pr["assignees"]["nodes"]) if p]


def assigned_people(pr):
    if pr.get("assigneeKindsUnknown"):
        return assignee_logins(pr)
    return [p for p in map(answerable, pr["assignees"]["nodes"]) if p]


def owners(pr):
    """PR の番の持ち主。返答できる assignee がいて作者がその中にいなければその全員、それ以外は [作者]。

    assignee は GitHub の定義で「その PR で作業している人」。作者が自分を入れずに人を assignee に
    付けた PR は渡し終えていて、作者の一覧に出し続けると、受けた側の一覧には「担当」しか出ない
    （実測 2026-10-02・IL-SW-AI/guided-resolver #1928: draft のまま、本文で assignee に実装と
    Ready for review を頼んでいた）。Copilot 等の Bot と
    退会済みのアカウントには渡せない——一覧を読まないので、移すとその PR は誰の一覧にも出ない。
    同じ理由で、assignee の種別が取れない PR（assigneeKindsUnknown）も作者が持つ。"""
    if pr.get("assigneeKindsUnknown") or not handed_to_others(pr):
        return [login(pr["author"])]
    return assigned_people(pr)


def handed_to_others(pr):
    """作者が自分を assignee に入れずに人へ渡したか。持ち主（owners）、/whose-turn の未依頼の段、/catchup の
    担当に渡した PR の分け方がここで決める——別々に書くと、片方だけ延びて作者も assignee の PR を渡した
    扱いにした（実測 2026-10-02）"""
    assigned = assigned_people(pr)
    return bool(assigned) and login(pr["author"]) not in assigned


def author_holds_handed(pr):
    """作者が持ち主のまま人へ渡した PR か。種別が取れる GitHub では owners() がその形を assignee へ付け替えるので、
    当たるのは種別が取れない GitHub だけ。未依頼でもレビュー依頼のボタンを押さずに人へ渡してあり、作者の
    「まだ誰にも渡していない」に置くと、相手が閉じるか進めるかを決める番の PR が作者の一覧に出続ける（実測
    2026-08-23・IL-SW-AI/guided-resolver #1403: 起票者を入れずに assignee を付けて「扱いはお任せします、不要
    だったら閉じてください」と書いた PR が 6 日「まだ誰にも渡していない」に居座っていた）"""
    return login(pr["author"]) in owners(pr) and handed_to_others(pr)


def owner_side(pr):
    return {login(pr["author"]), *owners(pr)}


def others_reviews(pr, reviews, side=None):
    """人のレビューに数えるもの。side（既定は持ち主の側）と Bot のレビューを除く——持ち主の側がレビューコメントに
    返信すると、その人の名義の COMMENTED レビューができる。数えると、誰にも頼んでいない PR が「再依頼」に化ける"""
    side = owner_side(pr) if side is None else side
    return [r for r in reviews if login(r["author"]) not in side and not is_bot(r["author"])]


def split(pr, reviews, asked):
    """依頼が残っていない PR の分け方。人のレビューが付いていれば再依頼、人へ依頼したことがあればレビュー依頼、
    それ以外は未依頼。どの窓から reviews と asked を読むかは呼び手が決める"""
    if others_reviews(pr, reviews):
        return "再依頼"
    return "レビュー依頼" if asked else "未依頼"


def owes_change_requests(pr):
    """持ち主に指摘対応が残るか。reviewDecision は PR 全体の集約値で、変更要求を出した人が承認するまで
    残り、その人への再依頼を映さない。変更要求の人ごとに見て、全員に依頼が出ていれば番はレビュアーにある。

    依頼が残っているかだけを見て時刻は比べない——レビューを送った人を GitHub は依頼の一覧から外すので、
    残っている依頼はその人の変更要求より後に出たもの。Team 宛の依頼は所属の人への再依頼に数えない（所属を
    展開していない）。人ごとの意見が切れている・見えないときは、集約値どおり指摘対応を残す側に倒す。"""
    if pr["reviewDecision"] != "CHANGES_REQUESTED":
        return False
    opinions = pr["latestOpinionatedReviews"]
    if opinions["totalCount"] > len(opinions["nodes"]):
        return True
    changes = {login(r["author"]) for r in opinions["nodes"] if r["state"] == "CHANGES_REQUESTED"}
    asked = {a for rq in pr["reviewRequests"]["nodes"] if (a := answerable(rq["requestedReviewer"]))}
    return not changes or bool(changes - asked)
