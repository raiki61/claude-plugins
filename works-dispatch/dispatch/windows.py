"""会話の窓（その会話を映すペイン）の決め方。どのペインに打ち込んでよいかは works-dispatch の決まりなので、端末の口（ports.term）
の外のここに置き、端末の口からは、ペインの並びと前のプロセスを読むだけにする。

サイドバーの作業内容のフック（activity.py）が Python 3.9 でも読むので、3.9 の文法で書き、tomllib などを読まない。
"""

import os

from ports import chat, term


def place_of(path):
    """場所のルート（path から上へたどって最初に .git の在るフォルダ。git の作業場のルート）。無ければ path 自身。git を呼ばずに字と
    ファイルだけで決める（ペインの数だけ呼ぶので）。"""
    here = os.path.realpath(path)
    up = here
    while True:
        if os.path.exists(os.path.join(up, ".git")):
            return up
        parent = os.path.dirname(up)
        if parent == up:
            return here
        up = parent


def own_pane(cwd, sid=None, listed=None):
    """会話の居るペイン。場所のルート（place_of）がこの会話と同じペインのうち、会話の印〔agent_session〕がこの会話の id の物が 1 つなら
    それ、無ければ場所の同じ物が 1 つならそれ。決まらなければ None。listed は端末の口の panes() の並び（省けば読む）。
    場所の違うペインは、印がこの会話の id でも選ばない（端末の印は前にそのペインに居た会話や別の部署の会話の id のまま残ることが
    あり、2026-10-17 に my_notes で、ノートの手入れの待ち受けが印の合った調べものの窓に /clear を打った）。
    端末がペインに渡す環境変数（ペインの id）は使わない（裏の会話は前もって起動した控えの処理の値を継ぎ、別のペインを指していた。
    2026-10-17 に見た）。"""
    if not cwd:
        return None
    here = place_of(cwd)
    talking = [p for p in (term.panes() if listed is None else listed) if p.get("agent")]
    hits = [p for p in talking if p.get("cwd") and place_of(p["cwd"]) == here]
    mine = [p for p in hits if sid and p.get("agent_session") == sid]
    if len(mine) == 1:
        return mine[0]["pane_id"]
    return hits[0]["pane_id"] if len(hits) == 1 else None


def holds_talk(processes, pids, jobs):
    """ペインの前のプロセス（端末の口の front_processes）に、この会話が居るか。会話の処理そのもの（pids のどれか。前で開いた会話）か、
    この会話の裏の処理を開いた処理（会話の口の attached。jobs は裏の処理の短い id の候補）が居れば真。
    会話の印〔agent_session〕は古いまま残ることがあるので見ない。"""
    return any(p.get("pid") in pids or chat.attached(p.get("argv") or [], jobs) for p in processes)


def talk_window(cwd, h, pids=(), jobs=()):
    """会話を消す打ち込み（/clear）の打ち先。場所がこの会話の場所のペインのうち、前のプロセスにこの会話が居ると確かめられた物
    （holds_talk。jobs は裏の処理の短い id の候補で、clear_now は属性 company.job・会話の口の job_of・会話の id の頭を渡す）が
    1 つならそれ、ほかは None。h は端末の口。会話の印（agent_session）も、場所だけでの代わりも使わない（印は前に居た会話や
    別の部署の会話の id のまま残り、2026-10-17 に my_notes で別の部署の窓に /clear を打った。持ち主の決め: 自分の会話だと確かめ
    られなければ打たずに残す）。"""
    here = place_of(cwd)
    hits = [p["pane_id"] for p in h.panes() if p.get("agent") and p.get("cwd") and place_of(p["cwd"]) == here]
    mine = [x for x in hits if holds_talk(h.front_processes(x), {p for p in pids if p is not None}, {j for j in jobs if j})]
    return mine[0] if len(mine) == 1 else None
