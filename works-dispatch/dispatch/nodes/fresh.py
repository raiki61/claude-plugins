#!/usr/bin/env python3
"""fresh ノード: 会話の開いている自分の番の PR を、新しい目で送り直すかを決める純粋な関数（設計書 2 節の 3）。外には書かない。

送り直す（refresh）のは、PR の clone の中で開いている会話が、次の全部を満たすときだけ。
- 会話が手すき（Claude Code の status が idle）。作業中・確認待ちの会話は触らない（busy）
- clone に未コミットの変更も git に足していないファイルも無く（dirty）、手元にしか無い commit も無い（unpushed）
- 前に送った時（dispatch の控え）か会話を起こした時の、遅い方より後に、自分以外の動き（コメント・レビュー・commit）が PR に有る。
  無ければ、相手の返事を待っている途中なので送り直さない（no_news）
送り直すときは、入口が会話を終えてペインを畳み、同じフォルダに新しい作業場と会話を立てて /catchup から送る（場所はフォルダだけを
使い直す。会話を /clear で使い回さないのは、作る道を 1 本にするため）。

own_unreviewed は、自分が作者でレビュアーの付いていない PR（レビューの依頼も、作者のほかの人のレビューも無い）。持ち主の決め
（2026-10-15「自分のレビュワーついてない作業のやつはたてなくていい」）で、一覧から開かない。--pr で指したものは入口が外さない。
"""

import pathlib


def inside(cwd, path):
    c, p = pathlib.PurePath(cwd), pathlib.PurePath(path)
    return c == p or p in c.parents


def own_unreviewed(pr, activity):
    return pr.get("role") == "implementer" and not activity.get("reviewers")


def decide(session, activity, sent_at, clean, unpushed):
    """refresh・busy・dirty・unpushed・no_news のどれか。session は sessions ノードの 1 行、activity は {last_other}。"""
    if session.get("status") != "idle":
        return "busy"
    if not clean:
        return "dirty"
    if unpushed:
        return "unpushed"
    last = activity.get("last_other")
    since = max([t for t in (sent_at, session.get("started")) if isinstance(t, (int, float))], default=None)
    if last is None or (since is not None and last <= since):
        return "no_news"
    return "refresh"
