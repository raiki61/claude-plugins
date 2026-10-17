#!/usr/bin/env python3
"""待ち受けのフック（受付の設計 docs/specs/2026-10-17-reception-design.md の 3・4 章。仕組みは nodes/wake.py）。

- Stop と SessionStart（asyncRewake）: 部署と窓口の会話で、頼みと納品の知らせを待ち、来たら会話を起こす。順番待ちの次の 1 件を
  渡し（属性に頼みを書いてから起こす）、役が fresh の部署は納品して止まった時点で自分の窓に /clear を打って会話を空にする。
  会話を持ち越す部署と窓口も、会話が自分で区切りと印した（--rest。属性 company.rest）番の終わりに、同じく窓に /clear を打つ。
  区切りかどうかは会話が役の本文の決まりで判断し、ここでは決めない。納品していない頼みが在る間は空にしない。
- UserPromptSubmit（`--resume`。裏で走らせない）: 人の文で番が始まったら、部署の答え待ちの印（--wait）と区切りの印（--rest）を
  外す。会話が文を読む前に済ませる（裏で走らせると、同じ番の中で会話が打った --wait より後に走って、付けたばかりの印を外しうる。
  そうなると止まる前のフックが答え待ちの頼みを「納品していない」と差し戻し続ける。社長室で 3 回続いた）。
- UserPromptSubmit（`--pause`。async）: 人の文で番が始まったら、その場所の待ち受けを止める（待ち受けは印の token を書き替えるだけ）。
  窓に打ち込まれた知らせも人の文と同じに数える。

部署か窓口（その場所の git の設定に company.role と company.name が在る）でなければ、すぐ 0 で終わる。待つのは場所の属性
company.session の会話だけ（部署で属性に id が無ければ誰でも。窓口〔代表の clone〕は id が要る）。この会話の id と違うときは、
同じ処理の会話が /clear などで id を替えた（前の待ち受けの印の会話の id が属性の id で、印を書いた処理がこの待ち受けの親と同じか、
窓口で --desk が書いた会話の処理の番号 company.pid がこの待ち受けの親の処理に在る）ときだけ、属性の id を書き直して待つ。
会話を起こす字の頭には、その会話に前に足した役の文と今の文が違えば、今の文を足す（role_hook.changed。会社の形を替えたことを、
会話を持ち越している部署と窓口に届ける）。確かめは印を書く前にする（待たない会話は、ほかの待ち受けの印に触らない）。

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
    import claudex  # noqa: E402
    import config  # noqa: E402
    import gitx  # noqa: E402
    import role_hook  # noqa: E402
    import herdr  # noqa: E402
    from nodes import deliver, provision, role, tree, wake  # noqa: E402
except (ImportError, SyntaxError) as _e:
    # 待ち受けは裏で走るので、古い Python（tomllib の無い 3.10 以前）でも会話を止めない。知らせは止まる前のフック
    # （orders.py stop）が会話ごとに 1 回出す
    sys.exit(0)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


def plan(payload, env=os.environ, attrs_of=gitx.worktree_attrs, parent=os.getppid, same=claudex.in_process):
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
        if not (held and held.get("session") == attrs["session"] and held.get("owner") == parent()
                or desk and same(attrs.get("pid"))):
            return None   # 窓口は、--desk が書いた会話の処理（company.pid）の会話なら、印が消えていても続きと見る
        adopt = True
    info = tree.read_info(root, os.path.dirname(config.path_of(attrs.get("config"), env)))
    names = wake.addresses(tree.company_name(root, info), attrs, gitx.former_names(attrs))
    return {"cwd": cwd, "root": root, "inbox": inbox, "place": place, "names": names, "session": sid, "owner": parent(),
            "adopt": adopt}


# herdr が会話の手が空いたと見る状態（done は番を終えたまま見られていない物）
IDLE = ("idle", "done")


def own_window(cwd, h=herdr, sid=None):
    """この会話の窓（herdr のペインのうち会話の居る物）。場所がこの会話の場所の物のうち、ペインの会話の印（agent_session）が
    この会話の id の物が 1 つならそれ、無ければ場所の同じ物が 1 つならそれ。1 つに決まらなければ None（本社には持ち主のほかの会話も
    居るので、印で結ぶ。場所の違う窓は印が合っても選ばない）。決め方は herdr.own_pane（サイドバーの作業内容と頼み元の窓も同じ決め方）。"""
    return herdr.own_pane(cwd, sid, h.panes())


def talk_window(cwd, h=herdr, pids=(), jobs=()):
    """会話を消す打ち込み（/clear）の打ち先。場所がこの会話の場所のペインのうち、前のプロセスにこの会話が居ると確かめられた物
    （herdr.holds_talk）が 1 つならそれ、ほかは None。会話の印（agent_session）も、場所だけでの代わりも使わない（印は前に居た会話や
    別の部署の会話の id のまま残り、2026-10-17 に my_notes で別の部署の窓に /clear を打った。持ち主の決め: 自分の会話だと確かめ
    られなければ打たずに残す）。"""
    here = herdr.place_of(cwd)
    hits = [p["pane_id"] for p in h.panes() if p.get("agent") and p.get("cwd") and herdr.place_of(p["cwd"]) == here]
    mine = [x for x in hits if herdr.holds_talk(h.front_processes(x), set(pids), {j for j in jobs if j})]
    return mine[0] if len(mine) == 1 else None


def clear_now(got, payload, attrs, h=herdr, pause=lambda: time.sleep(1), marks=None, me=lambda: claudex.host()[0]):
    """止まった会話を、自分の窓に /clear を打って空にする。打ったら True（属性に marks を書く。省けば、納品し終えた fresh の部署の
    company.cleared）。裏の処理が残る・会話がまだ動いている・窓の入力欄に字が在る・自分の会話の居る窓だと確かめられない
    （talk_window。me はこのフックを起こした Claude Code の処理の番号を返す）・herdr が受け付けないときは False（空にしない）。"""
    if payload.get("background_tasks"):
        return False
    try:
        jobs = (attrs.get("job"), claudex.attach_id(None, payload.get("session_id")))
        pane = talk_window(got["cwd"], h, [me()], jobs)
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
    provision.mark(got["cwd"], got["root"], marks or {"cleared": attrs["ask"]}, gitx)
    return True


def checker(got, payload, h=herdr, attrs_of=gitx.worktree_attrs, now=time.time, me=lambda: claudex.host()[0]):
    """wake.watch に渡す check（受付の設計 4.2 の順）。me は clear_now に渡す（この会話の処理の番号）。"""
    def check():
        attrs = attrs_of(got["cwd"])
        ask = attrs.get("ask")
        if ask and attrs.get("delivered") != ask:
            return None   # 未納品の頼みを持っている
        if (payload.get("hook_event_name") == "Stop" and ask and attrs.get("fresh") == role.FRESH
                and attrs.get("cleared") != ask and clear_now(got, payload, attrs, h, me=me)):
            return "end", None   # 空にした後の会話の始まりの待ち受けが、次を渡す
        if payload.get("hook_event_name") == "Stop" and attrs.get(wake.REST) and clear_now(got, payload, attrs, h, marks={wake.REST: None}, me=me):
            return "end", None   # 会話が自分で区切りと印した（--rest）。空にした後の待ち受けが、次を渡す
        item = wake.take(got["inbox"], got["place"])
        if item is None:
            return None
        provision.mark(got["cwd"], got["root"], item.get("marks") or {}, gitx)
        deliver.log(got["inbox"], {"id": item.get("id"), "kind": "handed", "at": now(), "place": got["cwd"],
                                   "session": got["session"]})
        return "wake", item.get("line") or wake.wake_text([item])
    return check


def resume_from_wait(payload, attrs_of=gitx.worktree_attrs):
    """人の文で番が始まった: 部署の会話が --wait で印した答え待ちを外す（答えを受けたので、止まる前のフックがまた納品を促す）。
    --rest の区切りの印も外す（人と話している途中の会話を空にしない）。印を外すのは、場所の属性の会話（company.session）が文を
    受けたときだけ（同じ場所のほかの会話の文では外さない）。"""
    cwd = payload.get("cwd") or os.getcwd()
    attrs = attrs_of(cwd)
    if not (attrs.get("waiting") or attrs.get(wake.REST)) or attrs.get("session") and attrs["session"] != payload.get("session_id"):
        return
    common = gitx.common_dir(cwd)
    if common:
        provision.mark(cwd, gitx.root_of(common), {"waiting": None, "waiting-why": None, wake.REST: None}, gitx)


def resume_here(payload):
    """人の文で番が始まった（--resume。会話が文を読む前に走る）: 答え待ちと区切りの印を外す（resume_from_wait）。"""
    try:
        resume_from_wait(payload)
    except (gitx.GitError, OSError) as e:
        print(f"works-dispatch: 答え待ちの印を外せなかった（{e}）", file=sys.stderr)
    return 0


def pause_here(payload):
    """人の文で番が始まった（--pause。裏で走る）: その場所の待ち受けを止める（印の token を書き替える。印は消さない）。"""
    got = plan(payload)
    if not got:
        return 0
    held = wake.read_mark(got["inbox"], got["place"])
    if held and held.get("session") == got["session"]:
        wake.claim(got["inbox"], got["place"], held.get("names") or got["names"], got["session"], got["owner"], "paused",
                   held.get("since") or time.time())
    return 0


class WithRole:
    """会話を起こす字（err に書く物）の頭に、その会話の役の文が替わっていれば今の文を足す（role_hook.changed）。"""

    def __init__(self, err, payload, changed=role_hook.changed):
        self.err, self.payload, self.changed, self.done = err, payload, changed, False

    def write(self, text):
        if not self.done:
            self.done = True
            try:
                note = self.changed(self.payload)
            except Exception:  # 役の文を読めなくても、知らせは届ける
                note = None
            text = f"{note}\n\n{text}" if note else text
        self.err.write(text)

    def flush(self):
        self.err.flush()


def main(argv=None, stdin=sys.stdin, err=sys.stderr):
    argv = sys.argv[1:] if argv is None else argv
    try:
        payload = json.loads(stdin.read() or "{}") or {}
    except ValueError:
        return 0
    if argv[:1] == ["--resume"]:
        return resume_here(payload)
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
    return wake.watch(got["inbox"], got["place"], got["names"], got["session"], got["owner"], token, WithRole(err, payload),
                      check=checker(got, payload))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # 待ち受けの誤りで会話を起こさない（終了の値 2 だけが会話を起こす。1 は訳を残して終わる）
        print(f"works-dispatch の待ち受けが動かなかった: {e}", file=sys.stderr)
        sys.exit(1)
