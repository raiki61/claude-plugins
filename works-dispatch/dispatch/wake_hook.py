#!/usr/bin/env python3
"""待ち受けのフック（受付の設計 docs/specs/2026-10-17-reception-design.md の 3・4 章。仕組みは nodes/wake.py）。

- Stop と SessionStart（asyncRewake）: 部署と窓口の会話で、頼みと納品の知らせを待ち、来たら会話を起こす。順番待ちの次の 1 件を
  渡し（属性に頼みを書いてから起こす）、役が fresh の部署は納品して止まった時点で自分の窓に /clear を打って会話を空にする。
  fresh の部署を空にできない間（裏の処理が残る・入力欄に字が在る・窓を確かめられないなど）は、前の会話のまま次を渡さず、
  間を置いて空にするのを試し直す（会話が前の会話の中身で次の頼みを書き直さない）。
  会話を持ち越す部署と窓口も、会話が自分で区切りと印した（--rest。属性 company.rest）番の終わりに、同じく窓に /clear を打つ。
  区切りかどうかは会話が役の本文の決まりで判断し、ここでは決めない。納品していない頼みが在る間は空にしない。
  区切りの番の終わりに、会社の形の起動の設定（model・effort・[roles.settings]）が起こしたとき（属性 company.launched）と違えば、
  /clear の代わりに dispatch.py --move <部署か窓口> --if-changed で起こし直す（空にするのと失う物は同じ。持ち主の手で起こし直さない）。
  都度の部署が終わりと印した（--done。属性 company.finished）番の終わりには、印を外して dispatch.py --retire <部署> を会話から
  切り離して裏で走らせる（会話を止めて部屋を片付ける。--retire はこの会話を止めるので、この会話の子として待たない）。出力は受付箱の
  retires/ に残す。印は 1 度で外す（片付けられなかった部屋は --retire が訳を書いて残し、--clean の一覧で段取りが見る）。
  順番待ちに頼みが在れば畳まずに渡し、印を外す（済ませてから印し直す）。
  毎回空にする部署は、次の頼みを渡す前に、会社の形の model・effort が起こしたとき（属性 company.launched）と違えば、
  dispatch.py --move <部署> --if-changed で起こし直す（/clear は起こしたときの --model・--effort を残すため。restart_due）。
- UserPromptSubmit（`--resume`。裏で走らせない）: 人の文で番が始まったら、部署の答え待ちの印（--wait）と区切りの印（--rest）と
  終わりの印（--done）を外す。会話が文を読む前に済ませる（裏で走らせると、同じ番の中で会話が打った --wait より後に走って、付けたばかりの印を外しうる。
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
import subprocess
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
    """待つなら {cwd, root, inbox, place, names, session, owner, adopt, company, job}、待たないなら None。adopt は属性の会話の id を書き直すか。
    company は会社の名前（--retire に宛てる）。job は会話の裏の処理の短い id（環境変数 CLAUDE_JOB_DIR の名前。裏の会話でなければ None）。"""
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
    company = tree.company_name(root, info)
    names = wake.addresses(company, attrs, gitx.former_names(attrs))
    return {"cwd": cwd, "root": root, "inbox": inbox, "place": place, "names": names, "session": sid, "owner": parent(),
            "adopt": adopt, "company": company, "job": job_of(env)}


def job_of(env=os.environ):
    """この会話の裏の処理の短い id（`claude attach` に渡す物）。Claude Code は裏の会話（claude --bg）の処理に、置き場
    <設定のフォルダ>/jobs/<短い id> を CLAUDE_JOB_DIR で渡し、フックはそれを継ぐ。短い id は会話の id の頭と同じとは限らない
    （2026-10-17 に割り振りで、会話 081f72dd を短い id 8c4a1102 の処理が続けていた）。裏の会話でなければ None。"""
    d = (env.get("CLAUDE_JOB_DIR") or "").rstrip("/\\")
    return os.path.basename(d) or None


# herdr が会話の手が空いたと見る状態（done は番を終えたまま見られていない物）
IDLE = ("idle", "done")


def own_window(cwd, h=herdr, sid=None):
    """この会話の窓（herdr のペインのうち会話の居る物）。場所がこの会話の場所の物のうち、ペインの会話の印（agent_session）が
    この会話の id の物が 1 つならそれ、無ければ場所の同じ物が 1 つならそれ。1 つに決まらなければ None（本社には持ち主のほかの会話も
    居るので、印で結ぶ。場所の違う窓は印が合っても選ばない）。決め方は herdr.own_pane（サイドバーの作業内容と頼み元の窓も同じ決め方）。"""
    return herdr.own_pane(cwd, sid, h.panes())


def talk_window(cwd, h=herdr, pids=(), jobs=()):
    """会話を消す打ち込み（/clear）の打ち先。場所がこの会話の場所のペインのうち、前のプロセスにこの会話が居ると確かめられた物
    （herdr.holds_talk。jobs は attach の短い id の候補で、clear_now は属性 company.job・CLAUDE_JOB_DIR の名前・会話の id の頭を渡す）が
    1 つならそれ、ほかは None。会話の印（agent_session）も、場所だけでの代わりも使わない（印は前に居た会話や
    別の部署の会話の id のまま残り、2026-10-17 に my_notes で別の部署の窓に /clear を打った。持ち主の決め: 自分の会話だと確かめ
    られなければ打たずに残す）。"""
    here = herdr.place_of(cwd)
    hits = [p["pane_id"] for p in h.panes() if p.get("agent") and p.get("cwd") and herdr.place_of(p["cwd"]) == here]
    mine = [x for x in hits if herdr.holds_talk(h.front_processes(x), set(pids), {j for j in jobs if j})]
    return mine[0] if len(mine) == 1 else None


def clear_now(got, payload, attrs, h=herdr, pause=lambda: time.sleep(1), marks=None, me=lambda: claudex.host()[0], why=None):
    """止まった会話を、自分の窓に /clear を打って空にする。空になった（空にした後の会話の始まりの待ち受けが印を書いた）のを見たら
    True（属性に marks を書く。省けば、納品し終えた fresh の部署の company.cleared）。裏の処理が残る・会話がまだ動いている・窓の
    入力欄に字が在る・自分の会話の居る窓だと確かめられない（talk_window。me はこのフックを起こした Claude Code の処理の番号を返す）・
    herdr が受け付けない・打ったが空になったのを見られないときは False（印も書かない）。見られないまま True を返すと、この待ち受けは
    終わるのに次の待ち受けが張られず、順番待ちを渡す者が居なくなる（2026-10-17 に my_notes のノートの手入れで、別の窓に /clear を
    打った後に約 70 分止まった）。why に並びを渡せば、空にしなかった訳を 1 つ足す。"""
    def no(reason):
        if why is not None:
            why.append(reason)
        return False
    if payload.get("background_tasks"):
        return no("裏の処理が残っている")
    try:
        jobs = (attrs.get("job"), got.get("job"), claudex.attach_id(None, payload.get("session_id")))
        pane = talk_window(got["cwd"], h, [me()], jobs)
        if pane is None:
            return no("この会話の居る窓を 1 つに確かめられない（部署の窓で attach を開けば続く）")
        if (h.agent(pane) or {}).get("agent_status") not in IDLE:
            return no("会話がまだ動いている")   # ほかの止まる前のフックが番を続けさせたなど
        box = deliver.input_box(h.read(pane, 40))
        if box is None or box.lstrip("❯").strip():
            return no("窓の入力欄が見えないか、字が在る")   # 頭の ❯ は入力欄の印
    except h.HerdrError as e:
        return no(f"herdr を読めない（{e}）")

    def cleared():   # /clear の後の会話の始まりで張った待ち受けが、新しい会話の id で印を書く
        held = wake.read_mark(got["inbox"], got["place"]) or {}
        return bool(held.get("session")) and held.get("session") != got["session"]
    status, detail = deliver.clear_talk(pane, h, pause, cleared)
    if status == "failed":
        return no(f"/clear を打てない（{detail}）")
    if status != "cleared":
        return no("/clear を打ったが、会話が空になったのを見られない")   # この待ち受けが続く（次の待ち受けが張られたかが分からない）
    provision.mark(got["cwd"], got["root"], marks or {"cleared": attrs["ask"]}, gitx)
    return True


DISPATCH_PY = str(pathlib.Path(__file__).resolve().parent / "dispatch.py")
RETIRES = "retires"   # 受付箱の下の、--retire を走らせた出力の置き場
MOVES = "moves"   # 受付箱の下の、--move を走らせた出力の置き場（limit_hook.py と同じ）
NO_FLAGS = role.launch_key(None)   # company.launched の無い部署（この版より前に起こした）は、旗なしで起こしたと見る


def retire_later(got, attrs, spawn=subprocess.Popen, now=time.time):
    """終わりと印した都度の部署（--done）の印を外し、dispatch.py --retire <会社/部署> を会話から切り離して裏で走らせる。走らせたら True。
    走らせられなければ、残った訳を属性に書いて False（印は外したまま。打ち直しはしない）。"""
    name = attrs["name"]
    argv = [sys.executable, DISPATCH_PY, "--retire", f"{got['company']}/{name}"] + (["--config", attrs["config"]] if attrs.get("config") else [])
    out = os.path.join(got["inbox"], RETIRES, f"{''.join(c for c in name if c.isalnum())}-{int(now())}.log")
    provision.mark(got["cwd"], got["root"], {wake.FINISHED: None}, gitx)
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", encoding="utf-8") as f:
            spawn(argv, cwd=got["root"], stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:
        provision.mark(got["cwd"], got["root"], {wake.RETIRE_KEPT: f"--retire を走らせられなかった（{e}）"}, gitx)
        return False
    return True


# 会話の始まり（SessionStart）のうち、会話が空で始まった物（source）。ほかの始まり（resume・compact）は前の会話を持っている
EMPTY_STARTS = ("startup", "clear")


def open_children(got, attrs, records=None):
    """この部署が出して、まだ閉じていない頼み（納品・取り下げ・回して閉じる、のどれも台帳に無い物）の受付の並び。頼みの行の from の
    名前が部署の名前で、場所が部署の場所（か、その下）の物。"""
    here = os.path.realpath(got["cwd"])
    rows = deliver.records(got["inbox"]) if records is None else records
    out = []
    for r in deliver.open_asks(rows):
        src = r.get("from") or {}
        at = os.path.realpath(src.get("place") or "")
        if src.get("name") == attrs.get("name") and (at == here or at.startswith(here + os.sep)):
            out.append(r["id"])
    return out


def must_clear(payload, attrs):
    """頼みごとに空の会話で受ける部署（fresh）が、次の頼みを受ける前に会話を空にしなければならないか。納品し終えていて
    （company.delivered が company.ask）、まだ空にしていない（company.cleared が違う）とき。ただし会話が空で始まった時を除く。"""
    ask = attrs.get("ask")
    if not (ask and attrs.get("fresh") == role.FRESH and attrs.get("delivered") == ask and attrs.get("cleared") != ask):
        return False
    return not (payload.get("hook_event_name") == "SessionStart" and payload.get("source") in EMPTY_STARTS)


def restart_due(got, payload, attrs, key_of=role_hook.launch_key, at_rest=False):
    """毎回空にする部署が次の頼みを受ける前に（at_rest なら、会話を持ち越す部署か窓口が区切り〔--rest〕の番の終わりに）、起こし直すか。
    起こし直すなら会社の形の今の値（role.launch_key の字）、ほかは None。/clear は起こしたときの --model・--effort・--settings を
    残すので、会社の形の起動の設定を替えたら、空にするのでなく起こし直す（6bdc72）。
    裏の処理が残る・（at_rest でなければ）順番待ちが空・今の値が起こしたとき（company.launched）か、前に起こし直さなかった値（company.restart-kept）と
    同じ・会社の形を読めない・この会話の起こし直しがもう走っている（company.restarting がこの会話の id。人が打って待ち受けが
    替わった後など。2 本走らせると同じ部署の会話が 2 つ立ちうる）ときは起こし直さない。"""
    if (not at_rest and (attrs.get("fresh") != role.FRESH or not wake.queued(got["inbox"], got["place"]))
            or payload.get("background_tasks") or not (attrs.get("job") or attrs.get("session"))
            or attrs.get(wake.RESTARTING) == got["session"]):
        return None
    try:
        key = key_of(got["cwd"], attrs)
    except Exception:  # 会社の形を読めなくても、頼みは渡す
        return None
    return None if key is None or key in (attrs.get(wake.LAUNCHED) or NO_FLAGS, attrs.get(wake.RESTART_KEPT)) else key


def restart_first(got, key, spawn=subprocess.Popen, now=time.time, pause=time.sleep, parent=os.getppid, detach=None):
    """dispatch.py --move <会社/部署> --if-changed を会話から切り離して走らせ、終わるまで待つ。--move がこの会話を止めて起こし直したら
    True（新しい会話の待ち受けが頼みを渡す）。止めずに終わったら（起こし直さない・起こせない）、印を外して今の値を
    company.restart-kept に残し、False（この会話に頼みを渡す。前の model・effort のまま受ける）。待つ間も印の更新の時刻を進め、
    会話の処理が替わる（止められた）か待ち受けが替わったら True。detach（既定は POSIX で本物の Popen のとき）なら detached の殻で
    走らせ、殻の書く終わりの値のファイルで終わりを見る（--move は前の会話を止めても走り続け、起こし直すか、起こせなければ訳を台帳に書く）。"""
    attrs = gitx.worktree_attrs(got["cwd"])
    name = attrs["name"]
    argv = ([sys.executable, "-u", DISPATCH_PY, "--move", f"{got['company']}/{name}", "--if-changed"]
            + (["--config", attrs["config"]] if attrs.get("config") else []))   # -u: 途中で止まっても、そこまでの出力を残す
    out = os.path.join(got["inbox"], MOVES, f"{''.join(c for c in name if c.isalnum())}-{int(now())}.log")
    done = out[:-len(".log")] + ".done"
    detach = os.name != "nt" and spawn is subprocess.Popen if detach is None else detach
    provision.mark(got["cwd"], got["root"], {wake.RESTARTING: got["session"]}, gitx)
    token = (wake.read_mark(got["inbox"], got["place"]) or {}).get("token")
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if detach:
            spawn(wake.detached(argv, out, done), cwd=got["cwd"], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                  stderr=subprocess.DEVNULL, start_new_session=True).wait()
            proc = None if os.path.exists(done) else _DoneFile(done)
        else:
            with open(out, "w", encoding="utf-8") as f:
                proc = spawn(argv, cwd=got["cwd"], stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    except OSError:
        proc = None
    while proc is not None and proc.poll() is None:
        if parent() != got["owner"] or (wake.read_mark(got["inbox"], got["place"]) or {}).get("token") != token:
            return True
        try:
            os.utime(wake.mark_path(got["inbox"], got["place"]))
        except OSError:
            pass
        pause(wake.POLL)
    if not gitx.worktree_attrs(got["cwd"]).get(wake.RESTARTING):
        return True   # --move が前の会話を止めた
    provision.mark(got["cwd"], got["root"], {wake.RESTARTING: None, wake.RESTART_KEPT: key}, gitx)
    return False


class _DoneFile:
    """切り離して走らせた命令の終わりを、殻が書く終わりの値のファイルで見る（Popen の poll と同じ形）。"""

    def __init__(self, path):
        self.path = path

    def poll(self):
        return 0 if os.path.exists(self.path) else None


def checker(got, payload, h=herdr, attrs_of=gitx.worktree_attrs, now=time.time, me=lambda: claudex.host()[0],
            spawn=subprocess.Popen, restart=restart_first, key_of=role_hook.launch_key):
    """wake.watch に渡す check（受付の設計 4.2 の順）。me は clear_now に渡す（この会話の処理の番号）。spawn は --retire を起こす口。
    restart は起こし直す口（restart_first）、key_of は会社の形の今の model・effort を読む口（role_hook.launch_key）。"""
    # fresh の部署を空にできないときは、前の会話のまま次の頼みを渡さず wake.HOLD を返す（watch が間を置いて見直す）。順番待ちに
    # 次が在れば、渡さない訳を順番待ちの受付箱の台帳に 1 度だけ残す（段取りが台帳で見て、--take で回せる）
    told = set()

    def check():
        attrs = attrs_of(got["cwd"])
        ask = attrs.get("ask")
        if ask and attrs.get("delivered") != ask:
            return None   # 未納品の頼みを持っている
        if (payload.get("hook_event_name") == "Stop" and attrs.get(wake.FINISHED) and not payload.get("background_tasks")
                and not wake.queued(got["inbox"], got["place"]) and retire_later(got, attrs, spawn, now)):
            return "end", None   # 都度の部署が終わりと印した（--done）。fresh の /clear より先に見る（空にすると印の会話が居なくなる）
        if must_clear(payload, attrs):
            children = open_children(got, attrs)
            if children:
                # 子の頼み（この部署が出して返事の来ていない頼み）が在る間は空にしない（持ち主の承認 dc0aa2: 受けた頼みも子の頼みも
                # 全部閉じた番の終わりに空にする）。子の納品で起きた番の終わりに、閉じていれば空にする（起こすときに印を外す。woken）。
                # 順番待ちの次の頼みは、前の会話のまま渡さずに待つ
                waiting = wake.queued(got["inbox"], got["place"])
                if not waiting:
                    return None
                why = f"子の頼みの返事を待っている（受付 {'・'.join(children)}）"
                if (waiting[0].get("id"), why) not in told:
                    told.add((waiting[0].get("id"), why))
                    deliver.log(got["inbox"], {"id": waiting[0].get("id"), "kind": "held", "at": now(), "place": got["cwd"],
                                               "session": got["session"], "detail": f"前の会話を空にしないので渡さずに待つ（{why}）"})
                return wake.HOLD
            why = []
            if clear_now(got, payload, attrs, h, me=me, why=why):
                return "end", None   # 空にした後の会話の始まりの待ち受けが、次を渡す
            waiting = wake.queued(got["inbox"], got["place"])
            if waiting and (waiting[0].get("id"), why[0]) not in told:
                told.add((waiting[0].get("id"), why[0]))
                deliver.log(got["inbox"], {"id": waiting[0].get("id"), "kind": "held", "at": now(), "place": got["cwd"],
                                           "session": got["session"], "detail": f"前の会話を空にできないので渡さずに待つ（{why[0]}）"})
            return wake.HOLD
        if payload.get("hook_event_name") == "Stop" and attrs.get(wake.REST) and attrs[wake.REST] in (got["session"], "1"):
            # 区切りの印はこの会話が打った物だけ見る（前の会話の印が残っていても、持ち主と話している今の会話を起こし直さない）
            key = restart_due(got, payload, attrs, key_of, at_rest=True)
            if key and restart(got, key):
                return "end", None   # 区切りで、会社の形の起動の設定が替わっていたので起こし直した。起こし直した会話の待ち受けが、次を渡す
            if clear_now(got, payload, attrs, h, marks={wake.REST: None}, me=me):
                return "end", None   # 会話が自分で区切りと印した（--rest）。空にした後の待ち受けが、次を渡す
        key = restart_due(got, payload, attrs, key_of)
        if key and restart(got, key):
            return "end", None   # 会社の形の起動の設定が替わったので起こし直した。起こし直した会話の待ち受けが、次を渡す
        with wake.ask_lock(got["inbox"], got["place"]):
            # 錠の中で読み直す（上で読んだ後に、--ask が窓に頼みを打っているかもしれない）
            if wake.pending(attrs_of(got["cwd"])):
                return None
            item = wake.take(got["inbox"], got["place"])
            if item is None:
                return None
            # 次の頼みを受けたら、前の終わりの印は外す（終わりは、受けた頼みを済ませてから --done で印し直す）
            provision.mark(got["cwd"], got["root"], {**(item.get("marks") or {}), wake.FINISHED: None}, gitx)
        deliver.log(got["inbox"], {"id": item.get("id"), "kind": "handed", "at": now(), "place": got["cwd"],
                                   "session": got["session"]})
        return "wake", item.get("line") or wake.wake_text([item])
    return check


def resume_from_wait(payload, attrs_of=gitx.worktree_attrs):
    """人の文で番が始まった: 部署の会話が --wait で印した答え待ちを外す（答えを受けたので、止まる前のフックがまた納品を促す）。
    --rest の区切りの印と --done の終わりの印も外す（人と話している途中の会話を空にも畳みもしない）。印を外すのは、場所の属性の会話（company.session）が文を
    受けたときだけ（同じ場所のほかの会話の文では外さない）。"""
    cwd = payload.get("cwd") or os.getcwd()
    attrs = attrs_of(cwd)
    if not (attrs.get("waiting") or attrs.get(wake.REST) or attrs.get(wake.FINISHED)) \
            or attrs.get("session") and attrs["session"] != payload.get("session_id"):
        return
    common = gitx.common_dir(cwd)
    if common:
        provision.mark(cwd, gitx.root_of(common), {"waiting": None, "waiting-why": None, wake.REST: None, wake.FINISHED: None}, gitx)


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


def keep_job(got, attrs_of=gitx.worktree_attrs):
    """部署の属性 company.job（落ちた部署を attach で戻すときと、/clear を打つ窓を確かめるときの短い id）を、この会話の裏の処理の
    短い id に合わせる。裏の会話を起こし直すと短い id が替わり、古い id のままだと窓を自分の物と確かめられずに順番待ちを渡さなかった
    （2026-10-17 の割り振り。属性は a5b0bc07、窓は 8c4a1102 に attach していた）。書けなくても待ち受けは続ける。"""
    try:
        if got.get("job") and attrs_of(got["cwd"]).get("job") != got["job"]:
            provision.mark(got["cwd"], got["root"], {"job": got["job"]}, gitx)
    except (gitx.GitError, OSError):
        pass


def woken(got, attrs_of=gitx.worktree_attrs):
    """待ち受けが会話を起こす（納品・足しの知らせか、順番待ちの頼みを渡す）ときに、毎回空にする部署（役が fresh）なら、空にした印
    （company.cleared）を外す。起こされた番の文脈が会話に残るので、その番の終わりに待ち受けがまた空にする（must_clear）。今までは、
    頼みを受けていない番（社長室の納品で起こされた業務改革など）の後も印が残り、次の頼みが前の番の文脈のまま渡った
    （my_notes の受付 f4ca34 で見つかった。6a9337）。人が窓に打った番では外さない（持ち主と話している途中の会話を空にしない）。"""
    attrs = attrs_of(got["cwd"])
    if attrs.get("fresh") == role.FRESH and attrs.get("cleared"):
        provision.mark(got["cwd"], got["root"], {"cleared": None}, gitx)


class WithRole:
    """会話を起こす字（err に書く物）の頭に、その会話の役の文が替わっていれば今の文を足す（role_hook.changed）。"""

    def __init__(self, err, payload, changed=role_hook.changed, woke=lambda: None):
        self.err, self.payload, self.changed, self.done, self.woke = err, payload, changed, False, woke

    def write(self, text):
        if not self.done:
            self.done = True
            try:
                self.woke()
            except Exception:  # 印を外せなくても、知らせは届ける
                pass
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
    keep_job(got)
    token = wake.new_token()

    def stop(*_):
        # 会話が終わる（claude stop）・フックの持ち時間が尽きると Claude Code が TERM を送る。印を消して、送る側をすぐ予備へ回す
        wake.release(got["inbox"], got["place"], token)
        sys.exit(0)
    for name in ("SIGTERM", "SIGHUP", "SIGINT"):
        if hasattr(signal, name):
            signal.signal(getattr(signal, name), stop)
    return wake.watch(got["inbox"], got["place"], got["names"], got["session"], got["owner"], token, WithRole(err, payload, woke=lambda: woken(got)),
                      check=checker(got, payload))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # 待ち受けの誤りで会話を起こさない（終了の値 2 だけが会話を起こす。1 は訳を残して終わる）
        print(f"works-dispatch の待ち受けが動かなかった: {e}", file=sys.stderr)
        sys.exit(1)
