"""立場（この件で私は何者か）の判定。/catchup と /what-am-i-doing で共用。

戻ったとき真っ先に要るのがこれで、会話からは読み取りにくい（どちらの側でもレビューの話を
するため）。素の値だけで決める純関数にしてあるので、gh に触らず全分岐を検査できる。

「どちらでもない」と断定しない——名指しで呼ばれただけの件で「どちらでもない · 私の番」と並ぶと
1 行目の中で食い違って見える。発言していれば参加者、していなければ未参加。

レビュー依頼（reviewRequests）だけを見ない——レビューを送った時点で GitHub が依頼から外すので、
自分がレビュー中の PR が「依頼は来ていない」に落ちる（実測: /what-am-i-doing が自分のレビュー済みの
PR を「どちらでもない」と出した。/catchup は同じ PR を「レビュアー」と出していた）。送ったレビューも数える。
"""


def stance(me, author, is_pr=True, requested=(), reviewed=False, assignees=(), spoke=False):
    """me: 私の login。author: 作者の login。requested: レビュー依頼先の login。reviewed: 私が
    レビューかレビュースレッドで発言したか。assignees: 担当の login。spoke: 私がこの件で発言したか。"""
    if author == me:
        return "実装者（作者）" if is_pr else "起票者"
    if is_pr and (me in requested or reviewed):
        return "レビュアー"
    if me in assignees:
        return "担当"
    return "参加者" if spoke else "未参加"
