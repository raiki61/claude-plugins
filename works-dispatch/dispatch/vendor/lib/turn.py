"""PR のターンの持ち主と、持ち主に指摘対応が残るかの判定。/whose-turn と /catchup で共用。

同じ規則を 2 本のスクリプトに別々に書くと、片方だけ直って食い違う（実測 2026-10-02: 変更要求の後にその
レビュアーへ再依頼しても、両方が同じ近道で作者に指摘対応を立て続けた。持ち主の判定も /whose-turn にしか無く、
/catchup は作者を持ち主と決め打ちしていて、担当に渡した PR の CI 赤を渡した作者のターンと出していた）。
素の dict だけで決める純関数にしてあるので、gh に触らず全分岐を試験できる。
"""

# この本文は複数のプラグインに写しで在る。正本は attention/scripts/lib/turn.py、写しは works-dispatch/dispatch/vendor/lib/turn.py。
# 直すのは正本だけで、配るのは python3 scripts/shared-copies.py --sync attention/scripts/lib/turn.py。

from ghtext import is_bot

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


def reviews_by_others(pr, reviews):
    """持ち主の側（作者と持ち主）でも Bot でもない人のレビュー。持ち主の側がスレッドに返すと、その人の名義の
    COMMENTED レビューができる。数えると、誰にも頼んでいない PR が再依頼に化ける。担当に渡した PR では、受けた
    担当のレビューも数えない。退会済み（login が None）は、作者も退会済みなら同じ人と見る（見分けられない）"""
    side = owner_side(pr)
    return [r for r in reviews if login(r["author"]) not in side and not is_bot(r["author"])]


def request_kind(pr, reviews, asked):
    """依頼が残っていない（要修正・承認済みでもない）PR で、持ち主（owners）に立つ依頼先を決めるターンの種別:
    rerequest（持ち主の側でない人のレビューが付き、依頼が消えたまま）・review_requested（人宛に依頼したが、
    レビューが付かないまま依頼も消えた）・unrequested（人宛に依頼したことが無い）。asked は人宛の依頼の記録の有無。

    ターンは種別に依らず持ち主に立てる。作者が自分を入れずに人を assignee に付けた PR は、渡す前に人のレビューや
    依頼の記録があっても、受けた担当が決め直す。作者に残すと、/catchup が作者、/whose-turn が担当と、持ち主が
    割れていた（受付 e199f8）"""
    if reviews_by_others(pr, reviews):
        return "rerequest"
    return "review_requested" if asked else "unrequested"


def thread_turns(pr):
    """未解決スレッドで返すターンがある人と、その人が読むべき発言。
    [(スレッド, ターンの人, 読む発言, その人の返事を待っている人)]。4 つ目は返すターンの行だけ非空で、
    再確認の行は空。

    ターンは人数で決まらない。1 つのスレッドが同時に複数人に載る——答える側は自分たちの最後の発言より
    後に来た指摘に答えるターン、レビュアーは自分の指摘の後に答える側が返した内容を再確認するターンで、
    レビュアーが 2 人以上入ると両方が同時に立つ。作者が bob に答えた後 carol が別の問いを足したら、
    bob は再確認するターンで、作者は carol に答えるターンである。

    ここを「スレッドごとに 1 人」に潰すと、潰した側が黙って落ちる。最後の発言者で決めると
    carol の相槌ひとつで bob の再確認が消え（材料も bob の指摘から carol の相槌に化ける）、
    立てた人と作者の往復だけで決めると carol の問いが誰の一覧にも出ない。

    答える側は持ち主の側（作者と持ち主）で、側の誰が返しても返したことになる——受けた assignee の
    返信で、渡す前に作者が返した分も含めて済む。返すターンは持ち主に立つ。側の人が立てて側の外の人が
    返していないスレッドは側の残りの人への問いで、答えるのも返すターンを負うのも残りの人（作者も含む）。
    側の外の人（返答できる人）が返したら、立てたのが側の誰でも、その人への返事のスレッドで、返すターンは
    持ち主に立つ——担当に渡した PR で担当が残したメモにレビュアーが返したら、渡し終えた作者でなく担当の
    ターン（持ち主 2026-10-31。受付 e07d56）。立てた人が持ち主でなければ（渡した作者が担当に聞いた問い）、
    立てた人の発言は答えに数えず、立てた人も担当の答えを待つ。残りに返答できる人（answerable）がいないスレッドは自注で、
    返す義務の起点にならないので見ない——持ち主が作者で作者が立てて側の外の人が返していないものと、
    返答できない作者（退会済み・Bot・Mannequin）の PR で受けた人が立てたもの。返答できない名義にターンを
    立てても誰も読まず、立てた人には来ない返事の返答待ちが残る。

    /whose-turn の一覧と /catchup の「私が返すターン」は、どちらもこの式で決める（別々に書いていた間は、
    渡した PR のスレッドと、ほかの人の PR で作者でないレビュアーが重ねて返したスレッドで割れていた）。"""
    holders = owners(pr)
    side = owner_side(pr)
    mute = set() if answerable(pr["author"]) else {login(pr["author"])}
    out = []
    for t in pr["reviewThreads"]["nodes"]:
        humans = [c for c in t["comments"]["nodes"] if not is_bot(c["author"])]
        if t["isResolved"] or not humans:
            continue
        opener = login(humans[0]["author"])
        # 側の人が立てたスレッドでも、側の外の人（返答できる人）が返したら、その人への返事のスレッドになる
        outsiders = {answerable(c["author"]) for c in humans} - side - {None}
        # 返答できない作者の自注は、外の人が返しても返す人がいない（ターンを立てると誰も読まない）
        if opener in side and (not outsiders or opener in mute):
            answer = owe = side - {opener} - mute
        elif opener in side:
            # 返すのは持ち主。立てた人の発言を答えに数えるのは、立てた人が持ち主のときだけ——渡した作者が担当に聞いた
            # 問いは、外の人が重ねて聞いても、作者の問いのまま担当の答えを待つ
            answer, owe = (side - {opener} - mute) | set(holders), set(holders)
        else:
            answer, owe = side, set(holders)
        if not answer:
            continue
        mine = [i for i, c in enumerate(humans) if login(c["author"]) in answer]
        after = humans[mine[-1] + 1 :] if mine else humans
        waiting = {login(c["author"]) for c in after}
        if after:
            out += [(t, o, after[-1], waiting) for o in sorted(owe, key=str)]
        others = {login(c["author"]) for c in humans} - answer - waiting
        for p in sorted(others, key=str):
            out.append((t, p, humans[mine[-1]], set()))
    return out
