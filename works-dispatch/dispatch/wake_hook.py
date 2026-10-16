#!/usr/bin/env python3
"""待ち受けのフック（受付の設計 docs/specs/2026-10-17-reception-design.md の 3・4 章。仕組みは nodes/wake.py）。

- Stop と SessionStart（asyncRewake）: 部署と窓口の会話で、頼みと納品の知らせを待ち、来たら会話を起こす。順番待ちの次の 1 件を
  渡し（属性に頼みを書いてから起こす）、役が fresh の部署は納品して止まった時点で自分の窓に /clear を打って会話を空にする。
- UserPromptSubmit（`--pause`。async）: 人の文で番が始まったら、その場所の待ち受けを止める（印の token を書き替えるだけ）。

部署か窓口（その場所の git の設定に company.role と company.name が在る）でなければ、すぐ 0 で終わる。待つのは場所の属性
company.session の会話だけ（部署で属性に id が無ければ誰でも。窓口〔代表の clone〕は id が要る）。この会話の id と違うときは、
同じ処理の会話が /clear などで id を替えた（前の待ち受けの印の会話の id が属性の id で、印を書いた処理がこの待ち受けの親と同じ）
ときだけ、属性の id を書き直して待つ。確かめは印を書く前にする（待たない会話は、ほかの待ち受けの印に触らない）。

宛先の会社の名前は、--ask と --tree と同じ読み方（tree.read_info と tree.company_name）で決める。
"""

import json
import os
import pathlib
import signal
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    import config  # noqa: E402
    import gitx  # noqa: E402
    import herdr  # noqa: E402
    from nodes import deliver, provision, role, tree, wake  # noqa: E402
except (ImportError, SyntaxError) as _e:
    # 待ち受けは裏で走るので、古い Python（tomllib の無い 3.10 以前）でも会話を止めない。知らせは止まる前のフック
    # （orders.py stop）が会話ごとに 1 回出す
    sys.exit(0)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


def plan(payload, env=os.environ, attrs_of=gitx.worktree_attrs, parent=os.getppid):
    """待つなら {cwd, root, inbox, place, names, session, owner, adopt}、待たないなら None。adopt は属性の会話の id を書き直すか。"""
    cwd = payload.get("cwd") or os.getcwd()
    sid = payload.get("session_id")
    attrs = attrs_of(cwd)
    if not attrs.get("role") or not attrs.get("name"):
        return None
    common, place = gitx.common_dir(cwd), gitx.git_dir(cwd)
    if not common or not place:
        return None
    desk = os.path.realpath(place) == os.path.realpath(common)
    if desk and not attrs.get("session"):
        return None   # 窓口は --desk が書いた会話の id が要る（代表の clone のほかの会話に知らせを横取りさせない）
    inbox = deliver.inbox_of(common)
    root = gitx.root_of(common)
    adopt = False
    if attrs.get("session") and sid and attrs["session"] != sid:
        held = wake.read_mark(inbox, place)
        if not (held and held.get("session") == attrs["session"] and held.get("owner") == parent()):
            return None
        adopt = True
    info = tree.read_info(root, os.path.dirname(config.path_of(attrs.get("config"), env)))
    names = wake.addresses(tree.company_name(root, info), attrs, gitx.former_names(attrs))
    return {"cwd": cwd, "root": root, "inbox": inbox, "place": place, "names": names, "session": sid, "owner": parent(),
            "adopt": adopt}


# herdr が会話の手が空いたと見る状態（done は番を終えたまま見られていない物）
IDLE = ("idle", "done")


def own_window(cwd, h=herdr):
    """この場所の窓（herdr のペインのうち、場所がこの会話の場所で会話の居る物）。1 つに決まらなければ None。"""
    here = os.path.realpath(cwd)
    hits = [p for p in h.panes() if p.get("agent") and p.get("cwd") and os.path.realpath(p["cwd"]) == here]
    return hits[0]["pane_id"] if len(hits) == 1 else None


def clear_now(got, payload, attrs, h=herdr, pause=lambda: time.sleep(1)):
    """納品して止まった fresh の部署の会話を、自分の窓に /clear を打って空にする。打ったら True（属性 company.cleared を書く）。
    裏の処理が残る・会話がまだ動いている・窓の入力欄に字が在る・窓が 1 つに決まらない・herdr が受け付けないときは False（空にしない）。"""
    if payload.get("background_tasks"):
        return False
    try:
        pane = own_window(got["cwd"], h)
        if pane is None or (h.agent(pane) or {}).get("agent_status") not in IDLE:
            return False   # ほかの止まる前のフックが番を続けさせたなど（次の番の終わりにもう一度見る）
        box = deliver.input_box(h.read(pane, 40))
        if box is None or box.lstrip("❯").strip():
            return False   # 入力欄が見えないか、字が在る（頭の ❯ は入力欄の印）
    except h.HerdrError:
        return False

    def cleared():   # /clear の後の会話の始まりで張った待ち受けが、新しい会話の id で印を書く
        held = wake.read_mark(got["inbox"], got["place"]) or {}
        return bool(held.get("session")) and held.get("session") != got["session"]
    status, _ = deliver.clear_talk(pane, h, pause, cleared)
    if status == "failed":
        return False
    provision.mark(got["cwd"], got["root"], {"cleared": attrs["ask"]}, gitx)
    return True


def checker(got, payload, h=herdr, attrs_of=gitx.worktree_attrs, now=time.time):
    """wake.watch に渡す check（受付の設計 4.2 の順）。"""
    def check():
        attrs = attrs_of(got["cwd"])
        ask = attrs.get("ask")
        if ask and attrs.get("delivered") != ask:
            return None   # 未納品の頼みを持っている
        if (payload.get("hook_event_name") == "Stop" and ask and attrs.get("fresh") == role.FRESH
                and attrs.get("cleared") != ask and clear_now(got, payload, attrs, h)):
            return "end", None   # 空にした後の会話の始まりの待ち受けが、次を渡す
        item = wake.take(got["inbox"], got["place"])
        if item is None:
            return None
        provision.mark(got["cwd"], got["root"], item.get("marks") or {}, gitx)
        deliver.log(got["inbox"], {"id": item.get("id"), "kind": "handed", "at": now(), "place": got["cwd"],
                                   "session": got["session"]})
        return "wake", item.get("line") or wake.wake_text([item])
    return check


def pause_here(payload):
    """人の文で番が始まった: その場所の待ち受けを止める（印の token を書き替える。印は消さない）。"""
    got = plan(payload)
    if not got:
        return 0
    held = wake.read_mark(got["inbox"], got["place"])
    if held and held.get("session") == got["session"]:
        wake.claim(got["inbox"], got["place"], held.get("names") or got["names"], got["session"], got["owner"], "paused",
                   held.get("since") or time.time())
    return 0


def main(argv=None, stdin=sys.stdin, err=sys.stderr):
    argv = sys.argv[1:] if argv is None else argv
    try:
        payload = json.loads(stdin.read() or "{}") or {}
    except ValueError:
        return 0
    if argv[:1] == ["--pause"]:
        return pause_here(payload)
    got = plan(payload)
    if not got:
        return 0
    if got["adopt"]:
        try:
            attrs = gitx.worktree_attrs(got["cwd"])
            provision.mark(got["cwd"], got["root"], provision.renew_session(attrs, got["session"]), gitx)
        except (gitx.GitError, OSError):
            return 0
    token = wake.new_token()

    def stop(*_):
        # 会話が終わる（claude stop）・フックの持ち時間が尽きると Claude Code が TERM を送る。印を消して、送る側をすぐ予備へ回す
        wake.release(got["inbox"], got["place"], token)
        sys.exit(0)
    for name in ("SIGTERM", "SIGHUP", "SIGINT"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    return wake.watch(got["inbox"], got["place"], got["names"], got["session"], got["owner"], token, err,
                      check=checker(got, payload))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # 待ち受けの誤りで会話を起こさない（終了の値 2 だけが会話を起こす。1 は訳を残して終わる）
        print(f"works-dispatch の待ち受けが動かなかった: {e}", file=sys.stderr)
        sys.exit(1)
