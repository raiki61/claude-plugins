#!/usr/bin/env python3
"""fresh ノード: 会話の開いている自分の番の PR を、新しい目で送り直すかを決める純粋な関数（設計書 2 節の 3）。外には書かない。

送り直す（refresh）のは、PR の枝の場所（元の clone の worktree）の中で開いている会話が、次の全部を満たすときだけ。
- 会話が手すき（Claude Code の status が idle）。作業中・確認待ちの会話は触らない（busy）
- 場所に未コミットの変更も git に足していないファイルも無く（dirty）、手元にしか無い commit もその枝の stash も無い（unpushed）
- 前に送った時（dispatch の控え）か会話を起こした時の、遅い方より後に、自分以外の動き（コメント・レビュー・commit）が PR に有る。
  無ければ、相手の返事を待っている途中なので送り直さない（no_news）
送り直すときは、入口が会話を終えてペインを畳み、同じ場所に新しい作業場と会話を立てて /catchup から送る（場所は checkout だけを
使い直す。会話を /clear で使い回さないのは、作る道を 1 本にするため）。

quiet_since_sent は、会話の開いていない PR を開き直さずに置くか（前に送った後に動きが無ければ no_news）。入口は、--pr で名指した
ときは使わない。

own_unreviewed は、自分が作者でレビュアーの付いていない PR（レビューの依頼も、作者のほかの人のレビューも無い）。持ち主の決め
（2026-10-15「自分のレビュワーついてない作業のやつはたてなくていい」）で、一覧から開かない。--pr で指したものは入口が外さない。
"""

import os
import pathlib


def inside(cwd, path):
    """cwd が path かその下か。リンクを辿った実際のパスで比べる（clean と同じ。~/src がリンクでも見落とさない）。"""
    c, p = pathlib.PurePath(os.path.realpath(cwd)), pathlib.PurePath(os.path.realpath(path))
    return c == p or p in c.parents


def own_unreviewed(pr, activity):
    return pr.get("role") == "implementer" and not activity.get("reviewers")


def quiet_since_sent(sent, activity):
    """会話が開いていない PR を、開き直さずに置くか（no_news）。前に送った控え（{at, head}）が有り、送った時刻より後に自分以外の
    動きが無く、PR の今の head も控えの head のままなら真。持ち主の決め（2026-10-15）: 返事待ちの PR は、持ち主が会話を閉じた
    だけでは開き直さない。head が違えば、commit の時刻に依らず動きとする（force-push で古い時刻の commit が来ることがあるため）。
    控えが無い・控えに時刻が無いなら偽（開く）。"""
    at = (sent or {}).get("at")
    if not isinstance(at, (int, float)):
        return False
    if _head_moved((sent or {}).get("head"), activity):
        return False
    last = activity.get("last_other")
    return last is None or last <= at


def _head_moved(sent_head, activity):
    """控えの head と PR の今の head が違うか（作者の push。どちらかが分からなければ偽）。"""
    now = activity.get("head_sha")
    return bool(sent_head and now and sent_head != now)


def decide(session, activity, sent_at, clean, unpushed, sent_head=None):
    """refresh・busy・dirty・unpushed・no_news のどれか。session は sessions ノードの 1 行、activity は {last_other, head_sha}。
    sent_head は前に送った時の head。今の PR の head と違えば、時刻に依らず動きとする（quiet_since_sent と同じ見方）。"""
    if session.get("status") != "idle":
        return "busy"
    if not clean:
        return "dirty"
    if unpushed:
        return "unpushed"
    if _head_moved(sent_head, activity):
        return "refresh"
    last = activity.get("last_other")
    since = max([t for t in (sent_at, session.get("started")) if isinstance(t, (int, float))], default=None)
    if last is None or (since is not None and last <= since):
        return "no_news"
    return "refresh"
