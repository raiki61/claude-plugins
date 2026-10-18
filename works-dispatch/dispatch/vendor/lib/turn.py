"""PR のターンの持ち主と、持ち主に指摘対応が残るかの判定。/whose-turn と /catchup で共用。

同じ規則を 2 本のスクリプトに別々に書くと、片方だけ直って食い違う（実測 2026-10-02: 変更要求の後にその
レビュアーへ再依頼しても、両方が同じ近道で作者に指摘対応を立て続けた。持ち主の判定も /whose-turn にしか無く、
/catchup は作者を持ち主と決め打ちしていて、担当に渡した PR の CI 赤を渡した作者のターンと出していた）。
素の dict だけで決める純関数にしてあるので、gh に触らず全分岐を試験できる。
"""

# この本文は複数のプラグインに写しで在る。正本は attention/scripts/lib/turn.py、写しは works-dispatch/dispatch/vendor/lib/turn.py。
# 直すのは正本だけで、配るのは python3 scripts/shared-copies.py --sync attention/scripts/lib/turn.py。

# 人ごとの最新の意見（APPROVED・CHANGES_REQUESTED・DISMISSED）。reviews の窓から人ごとに出すと、作者が
# スレッドに返すたびにできる COMMENTED で窓が埋まり、窓の外の変更要求を見落としてターンを誤って外す
OPINIONS = "latestOpinionatedReviews(first: 30) { totalCount nodes { state author { __typename login } } }"

# assignees は UserConnection で種別を持たず、Copilot 等の Bot を人と見分けられない。assignedActors は
# Assignee union（Bot・Mannequin・Organization・User）なので種別が取れる。別名で受けて下流の形を変えない
KINDS_FIELD = "assignedActors"
ASSIGNEES = f"assignees: {KINDS_FIELD}(first: 10) {{ totalCount nodes {{ __typename ... on Actor {{ login }} }} }}"
# UserConnection の __typename はいつも User で、Bot も人と名乗る。種別は取らない
LEGACY_ASSIGNEES = "assignees(first: 10) { totalCount nodes { login } }"


def missing_only(errors, fields):
    """GraphQL のエラーが全部、fields に挙げたフィールドをその GitHub が持たないこと（graphql-ruby の静的検証の
    undefinedField）か。真なら呼ぶ側は種別なしの問い合わせで取り直す——止めると、その GitHub では丸ごと走らない"""
    return bool(errors) and all(
        (e.get("extensions") or {}).get("code") == "undefinedField" and e["extensions"].get("fieldName") in fields
        for e in errors
    )


def login(actor):
    # 退会済みユーザーの author は null で返る
    return (actor or {}).get("login")


def answerable(actor):
    """返答できる人の login。User だけで、Bot・Mannequin・Organization・退会済み（null）は None。
    login の有無で見分けると、クエリのフラグメントに Bot { login } を足した途端 Bot が人になる"""
    return actor["login"] if (actor or {}).get("__typename") == "User" else None


def assigned_people(pr):
    # 種別が取れない GitHub では人か Bot か分からないので、login の取れた全員
    read = login if pr.get("assigneeKindsUnknown") else answerable
    return [p for p in map(read, pr["assignees"]["nodes"]) if p]


def handed_to_others(pr):
    """作者が自分を assignee に入れずに人へ渡したか。作者も assignee に入っていれば作者が持っていて、渡していない"""
    assigned = assigned_people(pr)
    return bool(assigned) and login(pr["author"]) not in assigned


def owners(pr):
    """PR のターンの持ち主。返答できる assignee がいて作者がその中にいなければその全員、それ以外は [作者]。

    assignee は GitHub の定義で「その PR で作業している人」。作者が自分を入れずに人を assignee に
    付けた PR は渡し終えていて、作者の一覧に出し続けると、受けた側の一覧には担当しか出ない
    （実測 2026-10-02・IL-SW-AI/guided-resolver #1928: draft のまま、本文で assignee に実装と
    Ready for review を頼んでいた）。作者も assignee に入っていれば作者が持つ。Copilot 等の Bot と
    退会済みのアカウントには渡せない——一覧を読まないので、移すとその PR は誰の一覧にも出ない。
    同じ理由で、assignee の種別が取れない PR（assigneeKindsUnknown）も作者が持つ。"""
    if pr.get("assigneeKindsUnknown") or not handed_to_others(pr):
        return [login(pr["author"])]
    return assigned_people(pr)


def owner_side(pr):
    """持ち主の側（作者と持ち主）"""
    return {login(pr["author"]), *owners(pr)}


def author_holds_handed(pr):
    """作者が持ち主のまま人へ渡した PR か。種別が取れる GitHub では owners() がその形を assignee へ付け替えるので、
    当たるのは種別が取れない GitHub だけ。未依頼でもレビュー依頼のボタンを押さずに人へ渡してあり、作者の
    「まだ誰にも渡していない」に置くと、相手が閉じるか進めるかを決めるターンの PR が作者の一覧に出続ける（実測
    2026-08-23・IL-SW-AI/guided-resolver #1403: 起票者を入れずに assignee を付けて「扱いはお任せします、不要
    だったら閉じてください」と書いた PR が 6 日「まだ誰にも渡していない」に居座っていた）"""
    return login(pr["author"]) in owners(pr) and handed_to_others(pr)


def owes_change_requests(pr):
    """持ち主に指摘対応が残るか。reviewDecision は PR 全体の集約値で、変更要求を出した人が承認するまで
    残り、その人への再依頼を映さない。変更要求の人ごとに見て、全員に人として依頼が出ていればターンはレビュアーにある
    （実測 #1843: 変更要求 → 直して再依頼 → レビュアーの返事待ちのまま、作者の一覧に指摘対応が出続けた）。

    依頼が残っているかだけを見て時刻は比べない——レビューを送った人を GitHub は依頼の一覧から外すので、
    残っている依頼はその人の変更要求より後に出たもの。Team 宛の依頼は所属の人への再依頼に数えない（所属を
    展開していない）。後で承認に変えた人は変更要求に数えない（人ごとの最新の意見で見る）。人ごとの意見が
    切れている・変更要求が 1 件も見えないときは、集約値どおり指摘対応を残す側に倒す。"""
    if pr["reviewDecision"] != "CHANGES_REQUESTED":
        return False
    opinions = pr["latestOpinionatedReviews"]
    if opinions["totalCount"] > len(opinions["nodes"]):
        return True
    changes = {login(r["author"]) for r in opinions["nodes"] if r["state"] == "CHANGES_REQUESTED"}
    asked = {a for rq in pr["reviewRequests"]["nodes"] if (a := answerable(rq["requestedReviewer"]))}
    return not changes or bool(changes - asked)
