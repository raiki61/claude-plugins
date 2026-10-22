#!/usr/bin/env python3
"""待ち受けのフック（受付の設計 docs/specs/2026-10-17-reception-design.md の 3・4 章。仕組みは nodes/wake.py）。

- Stop と SessionStart（asyncRewake）: 部署と窓口の会話で、頼みと納品の知らせを待ち、来たら会話を再開させる。順番待ちの次の 1 件を
  渡し（属性に頼みを書いてから起動する）、役が fresh の部署は納品して止まった時点で自分の窓に /clear を打って会話を空にする。
  fresh の部署を空にできない間（入力フィールドに字が在る・窓を確かめられないなど）は、前の会話のまま次を渡さず、
  間を置いて空にするのを試し直す（会話が前の会話の中身で次の頼みを書き直さない）。ただし、空にしない訳が、この会話が出した子の頼みの
  返事を待っている・裏の処理が残っている、のどちらかなら、順番待ちを止めずに前の会話のまま次を渡す（訳は渡す字の頭と台帳の handed の
  行〔kept〕に添える）。この 2 つの訳は、ほかの部署の順番待ちや会話の中の処理しだいで何時間も替わらないことがある（2026-10-18 に
  claude-plugins の割り振りが半日渡さなかった）。子の頼みは、この会話（属性 company.session）が出した物を、受けた頼みが替わっても数える。
  会話を引き継ぐ部署と窓口も、会話が自分で区切りと印した（--rest。属性 company.rest）ターンの終わりに、同じく窓に /clear を打つ。
  区切りかどうかは会話が役の本文の決まりで判断し、ここでは決めない。納品していない頼みが在る間は空にしない。
  会話が自分で compact の区切りと印した（--compact。属性 company.compact）ターンの終わりには、文脈が wake.COMPACT_FLOOR 以上なら
  窓に /compact <焦点> を打ち、compact の後の会話の始まり（SessionStart の compact）の待ち受けが印を外して続きをさせる 1 行を渡す
  （compact_turn。小さい・打てないときは compact せずに訳を添えて起動する）。納品していない頼みが在っても compact する。
  区切りで空にできずに次を渡すときは、空にできなかった訳を渡す字の頭と台帳の handed の行（unrested）に添える。入力フィールドの薄字
  （Claude Code の次の文の候補）は打ちかけの字と数えない（claudex.typed）。待ち受けが前に打って送られずに残った /clear も打ちかけと
  数えず、Enter で送り直す（wake.own_clear）。
  起動したばかりの裏の会話（claude --bg。SessionStart の startup）は、会話の記録のファイルができる（最初の文を受ける）まで、台帳を
  読まずに待つ（最初の文の前に Claude Code が会話の処理を殺して起動し直すと、それまでに渡した字は処理と一緒に消える。unready）。
  納品していない頼みを持つ会話の記録にその受付番号が無ければ（渡した字が届かなかった）、頼みを 1 度だけ渡し直す（unseen）。
  区切りのターンの終わりに、会社の形の起動の設定（model・effort・[roles.settings]）が起動したとき（属性 company.launched）と違えば、
  /clear の代わりに dispatch.py --move <部署か窓口> --if-changed で起動し直す（空にするのと失う物は同じ。持ち主の手で起動し直さない）。
  起動の設定が同じでも、今のアカウントの使用率が早めに移す目安に達したか、--move の名指し（company.move-to）が在れば同じく走らせ、
  上限に当たる前の区切りでほかのアカウントへ移す（early_due。名指しが今のアカウントなら、同じアカウントのまま起動し直す）。
  エフェメラルの部署が終わりと印した（--done。属性 company.finished）ターンの終わりには、印を外して dispatch.py --retire <部署> を会話から
  切り離して裏で走らせる（会話を止めて部屋を片付ける。--retire はこの会話を止めるので、この会話の子として待たない）。出力は受付箱の
  retires/ に残す。印は 1 度で外す（片付けられなかった部屋は --retire が訳を書いて残し、--clean の一覧で段取りが見る）。
  順番待ちに頼みが在れば畳まずに渡し、印を外す（済ませてから印し直す）。
  渡さずに待つ部署（納品していない頼みが在る）が、子の頼みの宛先をたどって、宛先も同じく止まり、子の頼みが宛先の
  順番待ちに積まれたままこの部署へ戻る輪を見つけたら、輪の一番古い頼みを、それが積まれた部署の会社で dispatch.py --take で既定の役の
  部署へ回す（knot・untie。受付の設計の 4.3。出力は受付箱の takes/、台帳に knot の行）。
  永続の部署は、次の頼みを渡す前に、作業場のブランチを origin のメインブランチの先頭まで fast-forward する（follow_main。書きかけの
  commit が在れば動かさない。会話の裏の処理が動いている間は進めず、遅れていればそれを添える。lag_note）。会話が起動するときにしか読まないファイルが替われば、今のアカウントの名指し（company.move-to）を印して起動し直させる。
  毎回クリアする部署は、次の頼みを渡す前に、会社の形の model・effort が起動したとき（属性 company.launched）と違えば、
  dispatch.py --move <部署> --if-changed で起動し直す（/clear は起動したときの --model・--effort を残すため。restart_due）。
  頼みを渡す・空にするなどの確かめ（checker）の前に毎回、Claude Code の入れた物の控え（installed_plugins.json）がこのプラグインの今の置き場を
  別の版と言っていれば、今の版の wake_hook.py に同じ引数とフックの入力で替わる（POSIX だけで exec。newer_self・hop。台帳に hopped の行）。
  /reload-plugins は裏で待っている待ち受けを止めないので、替わらないと、版を上げる前に立った待ち受けが前の版のまま何時間も後に渡す。
- UserPromptSubmit（`--resume`。裏で走らせない）: 人の文でターンが始まったら、部署の答え待ちの印（--wait）と区切りの印（--rest）と
  終わりの印（--done）を外す。会話が文を読む前に済ませる（裏で走らせると、同じターンの中で会話が打った --wait より後に走って、付けたばかりの印を外しうる。
  そうなると止まる前のフックが答え待ちの頼みを「納品していない」と差し戻し続ける。社長室で 3 回続いた）。
- UserPromptSubmit（`--pause`。async）: 人の文でターンが始まったら、その場所の待ち受けを止める（待ち受けは印の token を書き替えるだけ）。
  窓に打ち込まれた知らせも人の文と同じに数える。

部署か窓口（その場所の git の設定に company.role と company.name が在る）でなければ、すぐ 0 で終わる。待つのは場所の属性
company.session の会話だけ（部署で属性に id が無ければ誰でも。窓口〔代表の clone〕は id が要る）。この会話の id と違うときは、
同じ処理の会話が /clear などで id を替えた（前の待ち受けの印の会話の id が属性の id で、印を書いた処理がこの待ち受けの親と同じか、
窓口で --desk が書いた会話の処理の番号 company.pid がこの待ち受けの親の処理に在る）ときだけ、属性の id を書き直して待つ。
会話を再開させる字の頭には、その会話に前に足した役の文と今の文が違えば、今の文を足す（role_hook.changed。会社の形を替えたことを、
会話を引き継いでいる部署と窓口に届ける）。確かめは印を書く前にする（待たない会話は、ほかの待ち受けの印に触らない）。

宛先の会社の名前は、--ask と --tree と同じ読み方（tree.read_info と tree.company_name）で決める。
"""

import json
import os
import pathlib
import shlex
import signal
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    from ports import chat, term  # noqa: E402
    import windows  # noqa: E402
    import config  # noqa: E402
    import gitx  # noqa: E402
    import role_hook  # noqa: E402
    import filex  # noqa: E402
    import installed  # noqa: E402
    from nodes import accounts, deliver, provision, role, tree, wake  # noqa: E402
except (ImportError, SyntaxError) as _e:
    # 待ち受けは裏で走るので、古い Python（tomllib の無い 3.10 以前）でも会話を止めない。知らせは止まる前のフック
    # （orders.py stop）が会話ごとに 1 回出す
    sys.exit(0)

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


def _attrs(cwd):
    """場所の部署の属性。git の口はこのモジュールの gitx を呼ぶ時に引く（試験は gitx を偽物に替える。tests/fakegit.wire）。"""
    return gitx.worktree_attrs(cwd)


def plan(payload, env=os.environ, attrs_of=_attrs, parent=os.getppid, same=chat.in_process):
    """待つなら {cwd, root, inbox, place, names, session, owner, adopt, company, job, since}、待たないなら None。adopt は属性の会話の id を書き直すか。
    since は --handover で継いだ宛先の {宛先: 台帳の位置}（その位置より後の行だけを自分宛てと見る。wake.watch）。
    company は会社の名前（--retire に宛てる）。job は会話の裏の処理の短い id（環境変数 CLAUDE_JOB_DIR の名前。裏の会話でなければ None）。"""
    cwd = payload.get("cwd") or os.getcwd()
    sid = payload.get("session_id")
    attrs = attrs_of(cwd)
    if not attrs.get("role") or not attrs.get("name"):
        return None
    common, place = gitx.common_dir(cwd), gitx.git_dir(cwd)
    if not common or not place:
        return None
    desk = provision.desk_seat(place, common, attrs)
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
    info = tree.read_info(root, os.path.dirname(config.path_of(attrs.get("config"), env)), gitx)
    company = tree.company_name(root, info)
    names = wake.addresses(company, attrs, gitx.former_names(attrs))
    return {"cwd": cwd, "root": root, "inbox": inbox, "place": place, "names": names, "session": sid, "owner": parent(),
            "adopt": adopt, "company": company, "job": job_of(env), "since": gitx.inherited_since(attrs)}


job_of = chat.job_of


# herdr が会話の手が空いたと見る状態（done はターンを終えたまま見られていない物）
IDLE = ("idle", "done")


def own_window(cwd, h=term, sid=None):
    """この会話の窓（herdr のペインのうち会話の居る物）。場所がこの会話の場所の物のうち、ペインの会話の印（agent_session）が
    この会話の id の物が 1 つならそれ、無ければ場所の同じ物が 1 つならそれ。1 つに決まらなければ None（本社には持ち主のほかの会話も
    居るので、印で結ぶ。場所の違う窓は印が合っても選ばない）。決め方は windows.own_pane（サイドバーの作業内容と頼み元の窓も同じ決め方）。"""
    return windows.own_pane(cwd, sid, h.panes())


def talk_window(cwd, h=term, pids=(), jobs=()):
    """会話を消す打ち込み（/clear）の打ち先（windows.talk_window。tomllib の無い Python でも読めるよう windows に置く）。"""
    return windows.talk_window(cwd, h, pids, jobs)


NOT_CLEARED_BACKGROUND = "裏の処理が残っている"   # clear_now が空にしない訳のうち、checker が前の会話のまま次を渡す物


def clear_now(got, payload, attrs, h=term, pause=lambda: time.sleep(1), marks=None, me=lambda: chat.host()[0], why=None):
    """止まった会話を、自分の窓に /clear を打って空にする。空になった（空にした後の会話の始まりの待ち受けが印を書いた）のを見たら
    True（属性に marks を書く。省けば、納品し終えた fresh の部署の company.cleared）。裏の処理が残る・会話がまだ動いている・窓の
    入力フィールドに字が在る・自分の会話の居る窓だと確かめられない（talk_window。me はこのフックを起動した Claude Code の処理の番号を返す）・
    herdr が受け付けない・打ったが空になったのを見られないときは False（印も書かない）。入力フィールドの字が、前に打って送られずに
    残った /clear（wake.own_clear。打つ直前に属性 company.clear-typed を書く）なら、打ちかけと見ずに Enter で送り直す。見られないまま True を返すと、この待ち受けは
    終わるのに次の待ち受けが張られず、順番待ちを渡す者が居なくなる（2026-10-17 に my_notes のノートの手入れで、別の窓に /clear を
    打った後に約 70 分止まった）。why に並びを渡せば、空にしなかった訳を 1 つ足す。"""
    def no(reason):
        if why is not None:
            why.append(reason)
        return False
    if payload.get("background_tasks"):
        return no(NOT_CLEARED_BACKGROUND)
    try:
        jobs = (attrs.get("job"), got.get("job"), chat.attach_id(None, payload.get("session_id")))
        pane = talk_window(got["cwd"], h, [me()], jobs)
        if pane is None:
            return no("この会話の居る窓を 1 つに確かめられない（部署の窓で attach を開けば続く）")
        if (h.agent(pane) or {}).get("agent_status") not in IDLE:
            return no("会話がまだ動いている")   # ほかの止まる前のフックがターンを続けさせたなど
        box = chat.typed(h.read(pane, 40, ansi=True))
        if box is None:
            return no("窓の入力フィールドが見えない")
        left = bool(box) and wake.own_clear(box, attrs, got["session"])   # 前に打って送られずに残った /clear は送り直す
        if box and not left:
            return no(f"窓の入力フィールドに打ちかけの字が在る（「{box[:20]}」。薄字の候補は数えない）")
    except h.Error as e:
        return no(f"{term.NAME} を読めない（{e}）")

    def cleared():   # /clear の後の会話の始まりで張った待ち受けが、新しい会話の id で印を書く
        held = wake.read_mark(got["inbox"], got["place"]) or {}
        return bool(held.get("session")) and held.get("session") != got["session"]
    if not left:
        # 打った /clear が送られずに残ったとき（打った直後に会話がまた動き出したなど）、次の試しと --move・--nudge が人の字と見分ける
        provision.mark(got["cwd"], got["root"], {wake.CLEAR_TYPED: got["session"]}, gitx)
    status, detail = deliver.clear_talk(pane, h, pause, cleared, left)
    if status == "failed":
        return no(f"{chat.CLEAR} を打てない（{detail}）")
    if status != "cleared":
        return no(f"{chat.CLEAR} を打ったが、会話が空になったのを見られない")   # この待ち受けが続く（次の待ち受けが張られたかが分からない）
    provision.mark(got["cwd"], got["root"], {**(marks or {"cleared": attrs["ask"]}), wake.CLEAR_TYPED: None}, gitx)
    return True


COMPACT_LOOKS = 120   # /compact を打ってから、済んだ（compact の後の会話の始まりの待ち受けが印を外した）のを見る回数（5 秒ごと。10 分）
IDLE_LOOKS = 6   # ターンの終わりの直後に会話がまだ動いていると見えたとき、手が空くのを見直す回数（5 秒ごと。--rest は次の拍で見直す）


def context_of(path, tail=2_000_000):
    """会話の記録（transcript_path）の最後の応答が読んだ文脈のトークン（input + cache_read + cache_creation）。読めなければ None。
    数が全部 0 の行（Claude Code が書く <synthetic> の応答。エラーや割り込みの行）は飛ばす。"""
    try:
        with open(path, "rb") as f:
            f.seek(max(0, os.path.getsize(path) - tail))
            lines = f.read().splitlines()
    except (OSError, TypeError):
        return None
    for line in reversed(lines):
        if b'"usage"' not in line:
            continue
        try:
            usage = (json.loads(line).get("message") or {}).get("usage") or {}
        except ValueError:  # 書きかけの行は飛ばし、前の応答の数を使う
            continue
        size = sum(usage.get(k) or 0 for k in ("input_tokens", "cache_read_input_tokens", "cache_creation_input_tokens"))
        if size:
            return size
    return None


def compact_now(got, payload, attrs, h=term, pause=lambda: time.sleep(5), me=lambda: chat.host()[0], looks=None):
    """止まった会話の窓に /compact <焦点> を打ち、済んだ（compact の後の会話の始まりの待ち受けが印 company.compact を外した）のを見たら
    None。打たなかった・済んだのを見られなかった訳を返す（印は外さない）。窓の確かめは clear_now と同じ（自分の会話の居る窓・手が空いて
    いる・入力フィールドが空）。"""
    if payload.get("background_tasks"):
        return NOT_CLEARED_BACKGROUND
    try:
        jobs = (attrs.get("job"), got.get("job"), chat.attach_id(None, payload.get("session_id")))
        pane = talk_window(got["cwd"], h, [me()], jobs)
        if pane is None:
            return "この会話の居る窓を 1 つに確かめられない"
        for n in range(IDLE_LOOKS):   # Stop の直後は、herdr の会話の状態がまだ動いているのままのことがある
            if (h.agent(pane) or {}).get("agent_status") in IDLE:
                break
            if n == IDLE_LOOKS - 1:
                return "会話がまだ動いている"
            pause()
        box = chat.typed(h.read(pane, 40, ansi=True))
        if box is None:
            return "窓の入力フィールドが見えない"
        if box:
            return f"窓の入力フィールドに打ちかけの字が在る（「{box[:20]}」）"
    except h.Error as e:
        return f"{term.NAME} を読めない（{e}）"
    focus = attrs.get(wake.COMPACT_FOCUS)
    why = deliver.compact_talk(pane, h, pause, lambda: not gitx.worktree_attrs(got["cwd"]).get(wake.COMPACT),
                               f"{chat.COMPACT} {focus}" if focus else chat.COMPACT, COMPACT_LOOKS if looks is None else looks)
    return why and f"{chat.COMPACT} を{why}"


def compact_turn(got, payload, attrs, h=term, me=lambda: chat.host()[0], pause=None, looks=None):
    """会話が compact の区切りと印した（--compact）ターンの終わり（Stop）か、compact の後の会話の始まり（SessionStart の compact）に、
    check が返す物。印がこの会話の物でなければ None。"""
    if not attrs.get(wake.COMPACT) or attrs.get(wake.COMPACT) != got["session"]:
        return None
    clear = {wake.COMPACT: None, wake.COMPACT_FOCUS: None}
    if chat.event(payload) == chat.START and payload.get("source") == "compact":
        provision.mark(got["cwd"], got["root"], clear, gitx)
        focus = attrs.get(wake.COMPACT_FOCUS)
        return "wake", (f"（区切り〔--compact〕で会話を compact した{f'。焦点: {focus}' if focus else ''}。compact の前に受けていた頼みと"
                        "次の手を要約から読み、続ける。続きが返事待ちなどで今は無ければ、そのままターンを終える）")
    if chat.event(payload) != "Stop" or attrs.get(wake.REST) or attrs.get(wake.FINISHED):
        return None
    if payload.get("background_tasks"):
        return None   # 裏の処理が終わると会話が再開する。そのターンの終わりにまた試す
    size = context_of(chat.transcript(payload))
    if size is None or size < wake.COMPACT_FLOOR:
        provision.mark(got["cwd"], got["root"], clear, gitx)
        why = ("会話の記録から文脈の大きさを読めない" if size is None else
               f"文脈が {size} トークンで、{wake.COMPACT_FLOOR} トークンより小さく、compact の費用の元が取れない")
        return "wake", (f"（区切り〔--compact〕で compact しなかった: {why}。この会話のまま続ける。続きが今は無ければ、そのままターンを終える）")
    why = compact_now(got, payload, attrs, h, me=me, looks=looks, **({"pause": pause} if pause else {}))
    if why is None:
        return "end", None   # compact の後の会話の始まりの待ち受けが、続きをさせる
    provision.mark(got["cwd"], got["root"], clear, gitx)
    return "wake", (f"（区切り〔--compact〕で compact できなかった: {why}。この会話のまま続ける。続きが今は無ければ、そのままターンを"
                    "終える）")


DISPATCH_PY = str(pathlib.Path(__file__).resolve().parent / "dispatch.py")
RUN = " ".join(shlex.quote(pathlib.Path(x).as_posix()) for x in (sys.executable, DISPATCH_PY))   # orders.RUN と同じ字
RETIRES = "retires"   # 受付箱の下の、--retire を走らせた出力の置き場
MOVES = "moves"   # 受付箱の下の、--move を走らせた出力の置き場（limit_hook.py と同じ）
NO_FLAGS = role.launch_key(None)   # company.launched の無い部署（この版より前に起動した）は、旗なしで起動したと見る


def retire_later(got, attrs, spawn=subprocess.Popen, now=time.time, detach=None):
    """終わりと印したエフェメラルの部署（--done）の印を外し、dispatch.py --retire <会社/部署> を会話から切り離して裏で走らせる。走らせたら True。
    走らせられなければ、残った訳を属性に書いて False（印は外したまま。打ち直しはしない）。detach（既定は POSIX で本物の Popen のとき）
    なら detached の殻で走らせ、終わりの値を .done に書く（0 でなければ --tree と --todo が出す。health.py）。"""
    name = attrs["name"]
    argv = ([sys.executable, "-u", DISPATCH_PY, "--retire", f"{got['company']}/{name}"]
            + (["--config", attrs["config"]] if attrs.get("config") else []))
    out = os.path.join(got["inbox"], RETIRES, f"{''.join(c for c in name if c.isalnum())}-{int(now())}.log")
    detach = os.name != "nt" and spawn is subprocess.Popen if detach is None else detach
    provision.mark(got["cwd"], got["root"], {wake.FINISHED: None}, gitx)
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if detach:
            spawn(wake.detached(argv, out, out[:-len(".log")] + ".done"), cwd=got["root"], stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True).wait()
            return True
        with open(out, "w", encoding="utf-8") as f:
            spawn(argv, cwd=got["root"], stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    except OSError as e:
        provision.mark(got["cwd"], got["root"], {wake.RETIRE_KEPT: f"--retire を走らせられなかった（{e}）"}, gitx)
        return False
    return True


# 会話の始まり（SessionStart）のうち、会話が空で始まった物（source）。ほかの始まり（resume・compact）は前の会話を持っている
EMPTY_STARTS = ("startup", "clear")


def unready(payload, job, read=None):
    """裏の会話（job が在る。claude --bg）がまだ最初の文を受けていないか: 起動したばかり（SessionStart の startup）で、会話の記録の
    ファイル（transcript_path）がまだ無いか、人の文の行（"type":"user"）がまだ無い。記録のファイルは最初の文を受けたときにでき、
    頭に会話の名前などの行を書いてから文の行を書く（文の行の前に待ち明けると、unseen が受付番号を見つけられずに渡し直す）。
    裏の会話の処理は、最初の文を受ける前に Claude Code（daemon）が殺して同じ id で起動し直すことがあり、それまでに渡した字は処理と
    一緒に消える。--move で起動し直した部署の待ち受けが起動して 3 秒後に順番待ちの頼みを渡し、9 秒後に daemon がその処理を殺して
    起動し直し（Claude Code の daemon.log の「bg settled 8e817daa (killed)」「claimed-spare 8e817daa (respawn)」）、起動し直した会話は
    渡されたのを知らないまま「受けている頼みは無い」と納品した（2026-10-18、my_notes の受付 4bae53。Claude Code 2.1.302）。
    殺されなければ、最初の文の前に渡した字も届く（2026-10-18 の試し。最初の文の 7 秒前に渡した字が、最初のターンの後に届いた）。
    人が端末で起動した会話は daemon が起動し直さず、最初の文を打つまで知らせを止めないよう待たない。記録の場所を知らせない
    Claude Code でも待たない。"""
    if not job or chat.event(payload) != chat.START or payload.get("source") != "startup":
        return False
    path = chat.transcript(payload)
    if not path:
        return False
    try:
        seen = read(path) if read else pathlib.Path(path).read_bytes()
    except OSError:
        return True
    return b'"type":"user"' not in seen


def unseen(got, payload, attrs, git_dir=None):
    """この会話が持つ納品していない頼み（company.ask）の字が、会話に届いていないか: 会話の記録（transcript_path）に受付番号が無く、
    --move の最初の文（move-brief.md を読ませる）で渡した物でもない。渡した字は会話の処理が殺されると消え（unready の 4bae53）、
    台帳の handed の行だけが残る。最初の文の後に処理が殺されたときも、起動し直した会話の待ち受けがここで見つける。
    確かめられないとき（記録の場所が無い・読めない・頼みの会話がこの会話でない）は届いたと見る（同じ頼みを重ねて渡さない）。"""
    ask, path = attrs.get("ask"), chat.transcript(payload)
    if not ask or not path or attrs.get("session") != got["session"]:
        return False
    try:
        with open(path, "rb") as f:
            seen = f.read()
    except OSError:
        return False
    if ask.encode() in seen:
        return False
    if b"move-brief.md" in seen:
        try:
            brief = pathlib.Path((git_dir or gitx.git_dir)(got["cwd"]) or "", "move-brief.md").read_text(encoding="utf-8")
        except (OSError, ValueError):
            return False
        return ask not in brief
    return True


def again_text(attrs, run):
    """届かなかった頼みを渡し直す字。頼みの本文は頼み元の受付箱の <受付>-ask.md に在る。"""
    ask, boss = attrs["ask"], attrs.get("boss") or "頼み元"
    file = os.path.join(attrs.get("boss-inbox") or "", f"{ask}-ask.md")
    where = f"{file} を読んで進めてください" if attrs.get("boss-inbox") and os.path.isfile(file) else f"本文は {boss} に問い合わせる"
    return (f"（前に渡した頼みの字がこの会話に届いていなかった〔会話の記録に受付番号が無い〕ので、渡し直す）頼みです（受付 {ask}、"
            f"{boss} から）: {where}。終わったら、要約をファイルに書いて {deliver.deliver_command(run)} で"
            f"{boss} へ返す（足りない項目はコマンドが教える）。")


def open_children(got, attrs, records=None, read=None):
    """この部署が出して、まだ閉じていない頼みの受付の並び。数えるのは、頼みの行の from が部署（今の名前か前の名前で、場所が部署の
    作業場の中）で、今の会話が出した物（前の会話が残した古い行で順番待ちを止めない）。今の会話が出した物とは、会話の id（got の
    session か、属性 company.session）が同じ物と、今の会話が始まった後に出した物。始まりは、今の頼み（company.ask）を渡した時から、
    空にしないまま渡した（handed の kept）頼みを前へたどった、最初の頼みを渡した時（子の返事を待つ間も次の頼みを前の会話のまま渡すので、
    次の頼みの納品で空にすると、子の返事を受ける会話が黙って居なくなる。compact・resume で会話の id が替わっても、時刻で数え落とさない。
    会話の id の無い古い版の行も時刻で数える）。閉じたとみるのは、待ち受けが読み終えた所（read。省けば台帳の全部）までに、
    その受付への納品・取り下げ・回して閉じる、の行が在る物（返事の知らせを会話が受ける前に空にしない）。"""
    root = os.path.realpath(gitx.toplevel(got["cwd"]) or got["cwd"])
    names = {attrs.get("name"), *gitx.former_names(attrs)} - {None}
    talk = got.get("session") or attrs.get("session")
    rows = deliver.records(got["inbox"]) if records is None else records
    seen = rows if read is None else read
    # 渡し直し（again）は受けた時を動かさない（unseen）
    handed = [r for r in rows if r.get("kind") == "handed" and not r.get("again")
              and _inside(os.path.realpath(r.get("place") or ""), root)]
    first = max((i for i, r in enumerate(handed) if r.get("id") == attrs.get("ask")), default=None)
    while first and handed[first].get("kept"):
        first -= 1
    since = 0 if first is None else handed[first].get("at") or 0

    def ours(sender, at):
        said = sender.get("session")
        return bool(said and said == talk) or at >= since
    mine = {r["id"] for r in rows if r.get("kind") == "ask" and r.get("id")
            and (r.get("from") or {}).get("name") in names and ours(r.get("from") or {}, r.get("at") or 0)
            and _inside(os.path.realpath((r.get("from") or {}).get("place") or ""), root)}
    return sorted(mine - deliver.closed_ids(seen))


def _inside(at, root):
    return at == root or at.startswith(root + os.sep)


def _read_part(got):
    """台帳のうち、この場所の待ち受けが読み終えた所（wake の pos）までの行。読めなければ None（全部を読んだと見る）。"""
    pos = wake.read_pos(got["inbox"], got["place"])
    if pos is None:
        return None
    path = os.path.join(got["inbox"], wake.LOG)
    try:
        read = filex.read_jsonl(path, end=pos)
    except OSError:
        return None
    if read.bad:
        filex.warn("注記: " + filex.bad_text(path, read.bad) + "（その行を飛ばして読んだ）")
    return read.rows


TAKES = "takes"   # 受付箱の下の、輪をほどく --take を走らせた出力の置き場
RESUMED = "resumed"   # 台帳の種類: 人の文で答え待ちの印が外れた（id は答え待ちだった頼み）
KNOT = "knot"     # 台帳の種類: 返事待ちの輪を見つけ、輪の頼みを --take で回した（chain に輪の部署の名前、edges に輪の頼み）


UNTIE_TRIES = 3   # 1 つの待ち受けが同じ輪の頼みを回す回数の上限（最初の回を含む。--take が 0 以外で終わったときだけ回し直す）


def _exit_of(done):
    """切り離して走らせた --take の終わりの値（wake.detached の done のファイル）。まだ書かれていなければ None。"""
    try:
        text = pathlib.Path(done).read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return int(text) if text.lstrip("-").isdigit() else (1 if text else None)


def _root_of(path):
    return os.path.realpath(gitx.toplevel(path) or path)


def blocked(attrs, inbox, place):
    """部署がターンを終えて（待ち受けが動いている）、順番待ちを渡さずに止まっているか: 受けた頼みを納品していない。納品し終えた
    fresh の部署は、子の頼みの返事を待って空にしない間も、順番待ちを前の会話のまま渡すので、止まっていると見ない。"""
    return bool(wake.pending(attrs)) and wake.watching(inbox, place)


def queued_children(children, records):
    """子の頼みのうち、宛先の部署の順番待ちに積まれたまま（まだ渡っていない）物の並び [(子の受付, 宛先の部署の場所)]。宛先は台帳の
    その受付の最後の頼みの行の to.path（--take で回し直されたら、回した先）。"""
    out = []
    for c in children:
        dest = next(((r.get("to") or {}).get("path") for r in reversed(records)
                     if r.get("kind") == "ask" and r.get("id") == c and isinstance(r.get("to"), dict)), None)
        common, place = (gitx.common_dir(dest), gitx.git_dir(dest)) if dest and os.path.isdir(dest) else (None, None)
        if not common or not place:
            continue
        inbox = deliver.inbox_of(common)
        item = wake.find(inbox, c)
        if item and os.path.dirname(item["path"]) == wake.queue_dir(inbox, place):
            out.append((c, _root_of(dest)))
    return out


def knot(got, attrs, children, records=None):
    """この部署が渡さずに止まっている間に、返事待ちが輪になっているか。輪なら、ほどく 1 つの輪の頼みの並び [(受付, 頼んだ部署の名前,
    積まれた部署の名前, 積まれた部署の場所)]（先頭がほどく頼み）、輪でなければ None。
    たどるのは「止まっている部署（blocked）が出して返事の来ていない頼みが、ほかの部署の順番待ちに積まれたまま」の線だけ。会社を
    またぐ頼みも、頼みの行の宛先の場所からその会社の受付箱を読んでたどる。children はこの部署の子の頼み（open_children）。
    ほどく頼みは、この部署からたどれて、この部署へ戻れる部署どうしの線（輪に載る線）のうち受付番号の一番小さい物（一番古く出された
    物）。輪がいくつ重なっていても、その輪のどの部署から見ても同じ線の集まりなので、どの待ち受けが見つけても同じ頼みを選ぶ。"""
    here = _root_of(got["cwd"])
    rows = deliver.records(got["inbox"]) if records is None else records
    names, todo = {here: attrs.get("name") or here}, [here]
    out_of = {here: queued_children(children, rows)}
    while todo:
        node = todo.pop(0)
        for _, dest in out_of[node]:
            if dest in names:
                continue
            a = gitx.worktree_attrs(dest)
            common, place = gitx.common_dir(dest), gitx.git_dir(dest)
            if not common or not place or not a.get("role"):
                continue
            inbox = deliver.inbox_of(common)
            if not blocked(a, inbox, place):
                continue
            names[dest] = a.get("name") or dest
            out_of[dest] = queued_children(open_children({"cwd": dest, "inbox": inbox}, a), deliver.records(inbox))
            todo.append(dest)
    lines = [(c, node, dest) for node, outs in out_of.items() for c, dest in outs if dest in out_of]
    back, grew = {here}, True   # この部署へ戻れる部署（たどった部署はどれもこの部署から行ける）
    while grew:
        grew = False
        for _, node, dest in lines:
            if dest in back and node not in back:
                back.add(node)
                grew = True
    ring = [x for x in lines if x[1] in back and x[2] in back]
    if not ring:
        return None
    first = min(ring)
    came, todo = {first[2]: None}, [first[2]]   # ほどく線の先から元へ戻る道（輪の残り）
    while todo and first[1] not in came:
        node = todo.pop(0)
        for x in ring:
            if x[1] == node and x[2] not in came:
                came[x[2]] = x
                todo.append(x[2])
    path, cur = [], first[1]
    while came.get(cur):
        path.append(came[cur])
        cur = came[cur][1]
    return [(c, names[node], names[dest], dest) for c, node, dest in [first] + path[::-1]]


class UntieError(Exception):
    """untie が回す先（会社と既定の役）を決められない。訳は待ち受けが台帳に残す（loose）。"""


def untie(got, edges, spawn=subprocess.Popen, now=time.time, detach=None, env=os.environ):
    """返事待ちの輪（knot の返り）をほどく: 先頭の頼みを、積まれた部署の会社に、積まれた部署の受け持ちの名前を付けた作業の部署を
    立てて、dispatch.py --take <受付> --ask <会社>/<既定の役> --task <受け持ち>：<受付の末尾> --branch work/ask-<受付の末尾> で回す
    （段取りが手で打っていた物。受付番号と頼み元はそのまま）。会社と既定の役は、積まれた部署の会社の会社の形から読み、--take は
    その会社の代表の clone で打つ（回す頼みの本文の写しをその会社の受付箱に置く）。会話から切り離して走らせ、終わりを待たない
    （--take は herdr を読んで部署を立てる。取り合いは --take が順番待ちのファイルを消す所で 1 つに決まる）。出力は輪を見つけた部署の
    受付箱の takes/ に残し、台帳に kind knot の行を足す。走らせたら (回した受付, 終わりの値を書くファイル)、走らせられなければ None。
    会社の形を読めない・既定の役が会社の形に無いときは、回さずに UntieError を投げる。"""
    ask_id, _, owner, where = edges[0]
    attrs = gitx.worktree_attrs(got["cwd"])
    common = gitx.common_dir(where)
    root = gitx.root_of(common) if common else got["root"]
    try:
        info = tree.read_info(root, os.path.dirname(config.path_of(attrs.get("config"), env)), gitx)
        if info.get("problems"):
            raise ValueError("; ".join(info["problems"]))
        company = tree.company_name(root, info)
        crew, why = role.default(role.load(info["path"], info["text"]), role.DEFAULT)
    except Exception as e:
        # 前は場所の名前の会社と既定の役（作業）に倒して回し、役の名前を英語で書いた会社では役の無い部署を立てえた
        raise UntieError(f"{root} の会社の形を読めない（{type(e).__name__}: {e}）") from e
    if why:
        raise UntieError(why)
    chain = [edges[0][1]] + [e[2] for e in edges]
    note = (f"（待ち受けが回した頼み: 部署どうしが互いに出した頼みの返事を待ち、順番待ちが渡らない輪になっていた（{' → '.join(chain)}。"
            f"矢印は、左の部署が出した頼みが右の部署の順番待ちに積まれたまま）。止まらないよう、この頼みを {owner} の順番待ちから"
            f"取り出し、受付番号と頼み元はそのままに{crew}の部署で受ける。受け持ちは {owner}。）")
    tail = ask_id[-6:]
    argv = ([sys.executable, "-u", DISPATCH_PY, "--take", ask_id, "--ask", f"{company}/{crew}", "--task", f"{owner}：{tail}",
             "--branch", f"work/ask-{tail}", "--text", note] + (["--config", attrs["config"]] if attrs.get("config") else []))
    out = os.path.join(got["inbox"], TAKES, f"{''.join(ch for ch in ask_id if ch.isalnum())}-{int(now())}.log")
    done = out[:-len(".log")] + ".done"
    detach = os.name != "nt" and spawn is subprocess.Popen if detach is None else detach
    try:
        os.makedirs(os.path.dirname(out), exist_ok=True)
        if detach:   # 会話の処理が止まっても --take を止めない（restart_first と同じ殻）
            spawn(wake.detached(argv, out, done), cwd=root, stdin=subprocess.DEVNULL,
                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True).wait()
        else:
            with open(out, "w", encoding="utf-8") as f:
                spawn(argv, cwd=root, stdin=subprocess.DEVNULL, stdout=f, stderr=subprocess.STDOUT, start_new_session=True)
    except OSError:
        return None
    deliver.log(got["inbox"], {"id": ask_id, "kind": KNOT, "at": now(), "place": got["cwd"], "session": got["session"],
                               "chain": chain, "edges": [e[0] for e in edges], "out": out,
                               "detail": f"返事待ちの輪（{' → '.join(chain)}）をほどくため、受付 {ask_id} を {owner} の順番待ちから"
                                         f"{company} の{crew}の部署へ回す"})
    return ask_id, done


def must_clear(payload, attrs):
    """頼みごとに空の会話で受ける部署（fresh）が、次の頼みを受ける前に会話を空にしなければならないか。納品し終えていて
    （company.delivered が company.ask）、まだ空にしていない（company.cleared が違う）とき。ただし会話が空で始まった時と、保留の頼み
    （company.parked。--wait --park）が在る間を除く（空にすると、保留の答えを返す会話の中身が消える）。"""
    ask = attrs.get("ask")
    if attrs.get(deliver.PARKED):
        return False
    if not (ask and attrs.get("fresh") == role.FRESH and attrs.get("delivered") == ask and attrs.get("cleared") != ask):
        return False
    return not (chat.event(payload) == chat.START and payload.get("source") in EMPTY_STARTS)


def early_due(got, attrs, env=os.environ, now=time.time):
    """区切りで早めにほかのアカウントへ移すか（accounts.early。使用率の目安のほか、今のアカウントが使える時間帯の外か終わる手前のときも移す）。使用率の控えは取り直さずに読む（取り直すのは --move --if-changed）。
    移る先が在るか、--move の名指し（company.move-to）が在れば真（名指しの先が上限に達していても --if-changed に渡し、訳を台帳に
    残して印を外させる。名指しが今のアカウントなら、--if-changed が同じアカウントのまま起動し直す）。目安に達したのに移さない（移る先が無い・達した枠がすぐ戻る）ときは偽で、訳を台帳に kind moved・
    status skipped で残す（使える時間帯の終わる手前で移る先の無いときも同じ。同じアカウントの同じ種類の訳は、属性 company.move-skipped で 1 度だけ）。設定や控えを読めなければ偽（頼みは渡す）。"""
    try:
        cfg = config.load(attrs.get("config"), env, missing_ok=True)
        metered = [x.name for x in cfg.accounts if x.limits]
        at = now()
        rows = accounts.rank(cfg.accounts, accounts.read_limits(cfg.limits_dir, metered), cfg.limit_percent, at, None,
                             cfg.reset_soon_hours, cfg.hours_margin_minutes)
        got_ = accounts.early(rows, attrs.get("account"), cfg.early_percent, cfg.early_reset_hours, at, attrs.get(wake.MOVE_TO),
                              attrs.get(wake.MOVE_KEPT))
        if got_ and not got_["to"] and not attrs.get(wake.MOVE_TO):
            seen = f"{attrs.get('account')}/{got_['kind']}"
            if attrs.get(wake.MOVE_SKIPPED) != seen:
                deliver.log(got["inbox"], {"kind": "moved", "at": at, "name": attrs.get("name"), "path": got["cwd"],
                                           "from": attrs.get("account"), "to": None, "why": wake.EARLY, "status": "skipped", "detail": got_["why"]})
                provision.mark(got["cwd"], got["root"], {wake.MOVE_SKIPPED: seen}, gitx)
        elif got_ is None and attrs.get(wake.MOVE_SKIPPED):
            provision.mark(got["cwd"], got["root"], {wake.MOVE_SKIPPED: None}, gitx)   # 目安を下回った。次に達したらまた残す
    except Exception:  # 設定を読めなくても、頼みは渡す
        return False
    return bool(attrs.get(wake.MOVE_TO) or got_ and got_["to"])


def follow_main(got, attrs, catch_up=None):
    """永続の部署（属性 company.lifecycle が persistent）が順番待ちの次の頼みを受ける前に、作業場のブランチを origin のメインブランチの
    先頭まで fast-forward する（provision.follow_main）。永続の部署の作業場は頼みのたびに作り直さないので、進めないとメインブランチに
    入れた組織の直しが効かない（2026-10-20 に my_notes の調べものが 20 commit 遅れ、費用を下げる役の定義の直しが効かなかった。受付 72f7e4）。
    進めて、会話が起動するときにしか読まないファイル（.claude/ の役の定義・設定など。provision.read_at_start）が替わっていれば、
    今のアカウントの名指し（company.move-to）を印し、区切りの --move --if-changed に同じアカウントのまま起動し直させる（restart_due）。
    ほかのアカウントへ移す名指しが在れば、そのまま（移す時に起動し直す）。ブランチにメインブランチに無い commit が在れば（書きかけの作業）
    動かさない。渡す字の頭と台帳（kind followed の行と、handed の行の followed）に添える文を返す（添える事が無ければ None）。何が起きても頼みは渡す。
    同じアカウントのまま起動し直すのは --move の名指し（受付 c149fa）と同じ道で、子の頼みの返事を待って会話を空にしない間は起動し直さない。"""
    if attrs.get("lifecycle") != gitx.PERSISTENT or provision.desk_seat(got["place"], gitx.common_dir(got["cwd"]), attrs):
        return None
    try:
        r = (catch_up or (lambda cwd: provision.follow_main(cwd, gitx)))(got["cwd"])
    except Exception as e:  # 取れない・未コミットの変更と重なるなどでも、頼みは渡す
        return f"作業場のブランチをメインブランチの先頭へ進められなかったので、この作業場のまま渡す（{type(e).__name__}: {e}）"
    main = r["main"]
    if r["status"] == "local_only":
        return (f"作業場のブランチに {main} に無い commit が {r['ahead']} 個在るので、{main} の先頭（足りない commit {r['behind']} 個）へ"
                f"進めていない（書き換えない）。この頼みはこのブランチのまま受ける。前の頼みの書きかけなら、その頼み元に確かめてから --land で入れ、"
                "違うなら扱いを頼み元に問う")
    if r["status"] != "updated":
        return None
    said = f"作業場のブランチを {main} の先頭へ進めた（{r['behind']} 個の commit を取り込んだ）"
    # 会社の形（tree.INFO_FILE）は起動の設定（role.launch_key）と役の文（role_hook.changed）が別に見るので、起動し直す訳にしない
    if r["startup"] is None:   # 替わったかが分からなければ、起動し直す側に倒す（起動し直しても失う物は空にするのと同じ）
        said += "。会話が起動するときにしか読まないファイルが替わったかを比べられなかった"
    else:
        startup = [x for x in r["startup"] if x != "/".join(tree.INFO_FILE)]
        if not startup:
            return said
        files = "・".join(startup[:3]) + (f" ほか {len(startup) - 3} 件" if len(startup) > 3 else "")
        said += f"。会話が起動するときにしか読まないファイル（{files}）が替わった"
    account = attrs.get("account")
    if not account:
        return said + "が、部署のアカウントが分からないので起動し直さない"
    if not attrs.get(wake.MOVE_TO):
        try:
            provision.mark(got["cwd"], got["root"], {wake.MOVE_TO: account}, gitx)
        except Exception as e:  # 印を書けなくても、頼みは渡す
            return said + f"が、起動し直す印を書けないので前の起動のまま受ける（{type(e).__name__}: {e}）"
    if attrs.get("fresh") == role.FRESH:
        return said + "ので、同じアカウントのまま起動し直してから渡す（この文が見えていれば起動し直せなかったので、前の起動のまま受ける）"
    return said + "ので、次の区切り（頼みを納品した後に --rest を打ったターンの終わり）で、同じアカウントのまま起動し直す"


def lag_note(got, attrs, count=None):
    """会話の裏の処理が動いていて follow_main で作業場を進めないとき、渡す字の頭と台帳（kind followed の行と、handed の行の
    followed）に添える文。永続の部署の作業場がメインブランチより遅れていれば、進めていないことと足りない commit の数を書く（遅れて
    いない・永続の部署でなければ None）。黙って進めずに渡すと、会話はメインブランチに入った直しの無い作業場で頼みを受け、それを
    知らない（2026-10-21 に my_notes の調べものが、裏の処理が残ったまま次の頼みを受け、followed の行も無かった。my_notes の受付 35aa1b）。
    count は遅れを数える口（provision.lag。取り直すのは参照だけで、作業場のファイルは替えない）。何が起きても頼みは渡す。"""
    if attrs.get("lifecycle") != gitx.PERSISTENT or provision.desk_seat(got["place"], gitx.common_dir(got["cwd"]), attrs):
        return None
    held = "会話の裏の処理が動いているので、その足元のファイルを替えないよう、作業場のブランチをメインブランチの先頭へ進めていない"
    try:
        r = (count or (lambda cwd: provision.lag(cwd, gitx)))(got["cwd"])
    except Exception as e:  # 取れなくても、頼みは渡す
        return held + f"（遅れているかを確かめられなかった: {type(e).__name__}: {e}）"
    if not r["behind"]:
        return None
    main = r["main"]
    said = (held.replace("メインブランチ", main) + f"（{main} に有って作業場のブランチに無い commit が {r['behind']} 個）。"
            "この頼みはこのブランチのまま受ける（待ち受けがこの頼みのために後から進めることは無い）。")
    if r["ahead"]:   # follow_main の local_only と同じ扱い（書き換えない）
        return said + (f"作業場のブランチに {main} に無い commit が {r['ahead']} 個在るので、fast-forward では進められない。"
                       "前の頼みの書きかけなら、その頼み元に確かめてから --land で入れ、違うなら扱いを頼み元に問う")
    return said + f"{main} に入った直しが要るなら、裏の処理が終わってから、この会話で git merge --ff-only origin/{main} を打って進める"


def restart_due(got, payload, attrs, key_of=role_hook.launch_key, at_rest=False, early_of=early_due):
    """毎回クリアする部署が次の頼みを受ける前に（at_rest なら、会話を引き継ぐ部署か窓口が区切り〔--rest〕のターンの終わりに）、起動し直すか。
    起動し直すなら会社の形の今の値（role.launch_key の字）、ほかは None。/clear は起動したときの --model・--effort・--settings を
    残すので、会社の形の起動の設定を替えたら、空にするのでなく起動し直す（6bdc72）。値が同じでも、使用上限に当たる前の区切りで
    ほかのアカウントへ早めに移すとき（early_of。early_due）は起動し直す（上限に当たってから移ると、ターンの途中で切られて作業が消える）。
    裏の処理が残る・（at_rest でなければ）順番待ちが空・今の値が起動したとき（company.launched）か、前に起動し直さなかった値（company.restart-kept）と
    同じ・会社の形を読めない・この会話の起動し直しがもう走っている（company.restarting がこの会話の id。人が打って待ち受けが
    替わった後など。2 本走らせると同じ部署の会話が 2 つ立ちうる）・保留の頼みが在る（company.parked。起動し直すと、保留の答えを返す
    会話の中身が消える）ときは起動し直さない。"""
    if (attrs.get(deliver.PARKED) or not at_rest and (attrs.get("fresh") != role.FRESH or not wake.queued(got["inbox"], got["place"]))
            or payload.get("background_tasks") or not (attrs.get("job") or attrs.get("session"))
            or attrs.get(wake.RESTARTING) == got["session"]):
        return None
    try:
        key = key_of(got["cwd"], attrs)
    except Exception:  # 会社の形を読めなくても、頼みは渡す
        return None
    if key is None:
        return None
    if key not in (attrs.get(wake.LAUNCHED) or NO_FLAGS, attrs.get(wake.RESTART_KEPT)):
        return key
    return key if early_of(got, attrs) else None


def restart_first(got, key, spawn=subprocess.Popen, now=time.time, pause=time.sleep, parent=os.getppid, detach=None):
    """dispatch.py --move <会社/部署> --if-changed を会話から切り離して走らせ、終わるまで待つ。--move がこの会話を止めて起動し直したら
    True（新しい会話の待ち受けが頼みを渡す）。止めずに終わったら（起動し直さない・起動できない）、印を外して今の値を
    company.restart-kept に残し、False（この会話に頼みを渡す。前の model・effort のまま受ける）。--move が今は起動し直さない
    （wake.NOT_NOW。ターンの途中・打ちかけの字）で終わったときは今の値を残さない（次の区切りでまた試す）。待つ間も印の更新の時刻を進め、
    会話の処理が替わる（止められた）か待ち受けが替わったら True。detach（既定は POSIX で本物の Popen のとき）なら detached の殻で
    走らせ、殻の書く終わりの値のファイルで終わりを見る（--move は前の会話を止めても走り続け、起動し直すか、起動できなければ訳を台帳に書く）。"""
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
            proc = _DoneFile(done)
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
    # 今は起動し直さない（ターンの途中・打ちかけの字）で終わったなら、今の値を残さない（次の区切りで試し直す）
    later = proc is not None and proc.poll() == wake.NOT_NOW
    provision.mark(got["cwd"], got["root"], {wake.RESTARTING: None, **({} if later else {wake.RESTART_KEPT: key})}, gitx)
    return False


class _DoneFile:
    """切り離して走らせたコマンドの終わりを、殻が書く終わりの値のファイルで見る（Popen の poll と同じ形。数でない値は 1）。"""

    def __init__(self, path):
        self.path = path

    def poll(self):
        try:
            text = pathlib.Path(self.path).read_text(encoding="utf-8").strip()
        except OSError:
            return None
        if not text:
            return None   # 殻が書いている途中
        return int(text) if text.isdigit() else 1


def checker(got, payload, h=term, attrs_of=_attrs, now=time.time, me=lambda: chat.host()[0],
            spawn=subprocess.Popen, restart=restart_first, key_of=role_hook.launch_key, unknot=untie, follow=follow_main, lag=lag_note):
    """wake.watch に渡す check（受付の設計 4.2 の順）。me は clear_now に渡す（この会話の処理の番号）。spawn は --retire を起動する口。
    restart は起動し直す口（restart_first）、key_of は会社の形の今の model・effort を読む口（role_hook.launch_key）。
    unknot は返事待ちの輪をほどく口（untie。(got, 輪の頼みの並び) を受ける）。follow は永続の部署の作業場をメインブランチの先頭へ
    進める口（follow_main。(got, 属性) を受け、渡す字に添える文か None を返す）。lag は会話の裏の処理が動いていて進めないときに
    代わりに呼ぶ口（lag_note。同じ形）。"""
    # fresh の部署をすぐ替わる訳で空にできないときは、前の会話のまま次の頼みを渡さず wake.HOLD を返す（watch が間を置いて見直す）。
    # 順番待ちに次が在れば、渡さない訳を順番待ちの受付箱の台帳に 1 度だけ残す（段取りが台帳で見て、--nudge で動かせる）
    told, untied, follows = set(), {}, {}   # follows: 順番待ちの先頭の頼み → 作業場を進めて添える文（follow）

    def trouble(what, e):
        why = str(e) if isinstance(e, UntieError) else f"{type(e).__name__}: {e}"
        try:
            waiting = wake.queued(got["inbox"], got["place"])
            if waiting and (waiting[0].get("id"), what, why) not in told:
                told.add((waiting[0].get("id"), what, why))
                deliver.log(got["inbox"], {"id": waiting[0].get("id"), "kind": "held", "at": now(), "place": got["cwd"],
                                           "session": got["session"], "detail": f"{what}（{why}）"})
        except Exception as e2:  # 台帳に書けなくても待ち受けは止めない。訳は待ち受けの出力に残す
            filex.warn(f"注記: {what}（{why}）。台帳にも書けない（{type(e2).__name__}: {e2}）")

    def loose(attrs):
        # 納品していない頼みを持ったまま止まっている間に、返事待ちが部署をまたいで輪になっていれば（knot）、輪の頼みを 1 つ作業の
        # 部署へ回す（untie）。輪の部署はどれも、今の頼みを納品するまで順番待ちを渡さないので、誰も動かない（2026-10-18 に claude-plugins
        # の割り振り・点検・見直しと、my_notes の調べもの・ノートの手入れで、段取りが --take でほどくまで 2〜6 時間止まった）。同じ頼みを回すのは、
        # 前に回した --take が 0 以外で終わった（ほかの待ち受けと取り合って負けた・頼み直せずに順番待ちへ戻した）ときだけ、
        # 最初の回を含めて UNTIE_TRIES 回まで。輪を読めないなど何が起きても、待ち受けは止めない（止めると渡す待ち受けが居なく
        # なる）。ただし黙らず、訳を順番待ちの先頭の頼みの held の行で台帳に 1 度だけ残す（段取りが --tree と台帳で見る）
        try:
            if not wake.queued(got["inbox"], got["place"]):
                return
            children = open_children(got, attrs, read=_read_part(got))
            if not children:
                return
            edges = knot(got, attrs, children)
            if not edges:
                return
            tries = untied.get(edges[0][0], [])
            if tries and (len(tries) >= UNTIE_TRIES or tries[-1] and _exit_of(tries[-1]) in (None, 0)):
                return
        except Exception as e:
            return trouble("返事待ちの輪を確かめられない", e)
        try:
            ran = unknot(got, edges)
        except Exception as e:
            trouble(f"返事待ちの輪（受付 {edges[0][0]}）をほどけない", e)
            ran = None
        untied[edges[0][0]] = tries + [ran and ran[1]]   # 走らせられなかった回・落ちた回（None）も数え、次の確かめで回し直す

    def check():
        attrs = attrs_of(got["cwd"])
        verdict = compact_turn(got, payload, attrs, h, me=me)
        if verdict:
            return verdict
        ask = attrs.get("ask")
        if ask and attrs.get("delivered") != ask:
            if unseen(got, payload, attrs) and not any(r.get("kind") == "handed" and r.get("again") and r.get("id") == ask
                                                        and r.get("session") == got["session"] for r in deliver.records(got["inbox"])):
                # 同じ会話へ渡し直すのは 1 度まで（記録を読み違えても、ターンごとに同じ頼みを重ねない）
                deliver.log(got["inbox"], {"id": ask, "kind": "handed", "at": now(), "place": got["cwd"], "session": got["session"],
                                           "again": "会話の記録に受付番号が無い（渡した字が届かなかった）"})
                return "wake", again_text(attrs, RUN)
            if (chat.event(payload) == "Stop" and attrs.get(wake.MOVE_TO) not in (None, "", attrs.get("account"))
                    and attrs.get(wake.REST) in (got["session"], "1")):
                # --move がほかのアカウントへ移す印を付け、会話が納品の前に区切りと印した（--rest）。移して起動し直し、新しい会話が
                # 頼みを続ける（--move の最初の文が頼みを渡す）。頼みの途中の会話は空にしない。移せなければ印を外し、この会話のまま続ける
                key = restart_due(got, payload, attrs, key_of, at_rest=True)
                if key and restart(got, key):
                    return "end", None
                if not payload.get("background_tasks"):   # 裏の処理が残る間は、終わった後のターンの終わりでまた試す
                    provision.mark(got["cwd"], got["root"], {wake.REST: None}, gitx)
            if not payload.get("background_tasks"):
                # 納品の前に子の返事を待ってターンを終えた部署（永続の担当なども）も、輪の途中に入りうる
                loose(attrs)
            return None   # 未納品の頼みを持っている
        if (chat.event(payload) == "Stop" and attrs.get(wake.FINISHED) and not payload.get("background_tasks")
                and not wake.queued(got["inbox"], got["place"]) and retire_later(got, attrs, spawn, now)):
            return "end", None   # エフェメラルの部署が終わりと印した（--done）。fresh の /clear より先に見る（空にすると印の会話が居なくなる）
        # 空にする・区切りの判定より先に進める（起動するときに読むファイルが替われば、名指しの印で区切りの起動し直しに間に合わせる）。
        # 裏の処理が動いている間は、その足元のファイルを替えず、進めていないことと遅れを添える（lag。空にできずに待つなら、
        # 次のターンの終わりの待ち受けがまた試す。前の会話のまま渡すなら、会話は遅れを知って受ける）
        # 進めるのは順番待ちの先頭の頼みごとに 1 度（渡さずに待つ間は 5 秒ごとに見直すので、取り直しと台帳の行を重ねない）
        waiting = wake.queued(got["inbox"], got["place"])
        first = waiting[0].get("id") if waiting else None
        if waiting and first not in follows:
            follows[first] = (lag if payload.get("background_tasks") else follow)(got, attrs)
            if follows[first]:
                # 空にした・起動し直した会話の待ち受けが渡すときは、もう先頭を含むので handed の行に添わない。ここで残す
                deliver.log(got["inbox"], {"kind": "followed", "next": first, "at": now(), "place": got["cwd"], "session": got["session"],
                                           "detail": follows[first]})
                attrs = attrs_of(got["cwd"])   # 起動し直す名指し（company.move-to）を印したかもしれない
                if attrs.get(wake.MOVE_TO) == attrs.get("account") and not open_children(got, attrs, read=_read_part(got)):
                    # 起動し直すなら、先に空にしない（空にした後の会話の待ち受けが起動し直すので、/clear が無駄に 1 度挟まる）
                    key = restart_due(got, payload, attrs, key_of)
                    if key and restart(got, key):
                        return "end", None   # 起動し直した会話の待ち受けが、次を渡す
        followed = follows.get(first) if waiting else None
        kept = []   # 空にしないまま前の会話で次を渡す訳（渡す字の頭と台帳に添える。黙って前の会話のまま渡さない）
        if must_clear(payload, attrs):
            children = open_children(got, attrs, read=_read_part(got))
            if children:
                # 子の頼み（この会話が出して返事の来ていない頼み）が在る間は空にしない（持ち主の承認 dc0aa2: 受けた頼みも子の頼みも
                # 全部閉じたターンの終わりに空にする）。子の納品で起きたターンの終わりに、閉じていれば空にする（起動するときに印を外す。woken）。
                # 順番待ちの次の頼みは、空にしないまま前の会話で渡す（子の返事はこの会話で受ける）。前は渡さずに待ったので、子の頼みが
                # 止まった部署の順番待ちに積まれると、待ちが部署から部署へつながって半日止まった（2026-10-18、claude-plugins の割り振り）
                if not wake.queued(got["inbox"], got["place"]):
                    return None
                kept.append(f"この会話が出した子の頼み（受付 {'・'.join(children)}）の返事を、この会話で受けるため")
            else:
                why = []
                if clear_now(got, payload, attrs, h, me=me, why=why):
                    return "end", None   # 空にした後の会話の始まりの待ち受けが、次を渡す
                waiting = wake.queued(got["inbox"], got["place"])
                if not waiting:
                    return wake.HOLD
                if why[0] != NOT_CLEARED_BACKGROUND:
                    # すぐ替わる訳（会話が動いている・入力フィールドに字が在るなど）は、間を置いて空にするのを試し直す
                    if (waiting[0].get("id"), why[0]) not in told:
                        told.add((waiting[0].get("id"), why[0]))
                        deliver.log(got["inbox"], {"id": waiting[0].get("id"), "kind": "held", "at": now(), "place": got["cwd"],
                                                   "session": got["session"], "detail": f"前の会話を空にできないので渡さずに待つ（{why[0]}）"})
                    return wake.HOLD
                # 裏の処理は終わるまで何時間もかかりうる（2026-10-18 に見直しで、自分の行に当たり続ける pgrep の待ちが終わらなかった）。
                # この待ち受けが持つ payload の裏の処理は、ターンの終わりの時の物で、待つ間に読み直せない
                kept.append(why[0])
        unrested = []   # 区切りで空にできなかった訳（次を渡すときに会話と台帳に添える。黙って前の会話のまま渡さない）
        if not kept and chat.event(payload) == "Stop" and attrs.get(wake.REST) and attrs[wake.REST] in (got["session"], "1"):
            # 区切りの印はこの会話が打った物だけ見る（前の会話の印が残っていても、持ち主と話している今の会話を起動し直さない）
            key = restart_due(got, payload, attrs, key_of, at_rest=True)
            if key and restart(got, key):
                return "end", None   # 区切りで、会社の形の起動の設定が替わっていたので起動し直した。起動し直した会話の待ち受けが、次を渡す
            if clear_now(got, payload, attrs, h, marks={wake.REST: None}, me=me, why=unrested):
                return "end", None   # 会話が自分で区切りと印した（--rest）。空にした後の待ち受けが、次を渡す
        key = None if kept else restart_due(got, payload, attrs, key_of)   # 起動し直すと、子の返事を受ける会話が居なくなる
        if key and restart(got, key):
            return "end", None   # 会社の形の起動の設定が替わったので起動し直した。起動し直した会話の待ち受けが、次を渡す
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
                                   "session": got["session"], **({"unrested": unrested[0]} if unrested else {}),
                                   **({"kept": kept[0]} if kept else {}), **({"followed": followed} if followed else {})})
        text = item.get("line") or wake.wake_text([item])
        if kept:
            text = (f"（前の頼みを納品した会話を空にしないまま渡す: {kept[0]}。前の頼みで出した子の頼みの返事や裏の処理の知らせが"
                    "届いたら、この会話で受ける。どれも閉じたターンの終わりに空にする）\n" + text)
        if followed:
            text = f"（{followed}）\n" + text
        if unrested:
            # 2026-10-18 に my_notes の段取りが、空にできない訳を知らないまま 1 時間に 12 回、前の会話のまま受けた
            text = (f"（区切り〔--rest〕で会話を空にできなかったので、前の会話のまま渡す: {unrested[0]}。区切りの印は残してあり、"
                    "次のターンの終わりにまた空にするのを試す）\n" + text)
        return "wake", text
    return check


def resume_from_wait(payload, attrs_of=_attrs, now=time.time):
    """人の文でターンが始まった: 部署の会話が --wait で印した答え待ちを外す（答えを受けたので、止まる前のフックがまた納品を促す）。
    --rest の区切りの印と --done の終わりの印と --compact の区切りの印も外す（人と話している途中の会話を空にも畳みも compact もしない）。印を外すのは、場所の属性の会話（company.session）が文を
    受けたときだけ（同じ場所のほかの会話の文では外さない）。答え待ちを外したら、場所の会社と頼み元の受付箱の台帳に kind resumed を
    足す（頼みの状態を台帳から読めるように。docs/ledger.md）。"""
    cwd = payload.get("cwd") or os.getcwd()
    attrs = attrs_of(cwd)
    # 待ち受けが打った /compact で始まるターンでは、compact の区切りの印を外さない（外すと compact の後に続きをさせる者が居ない）
    compact = not (payload.get("prompt") or "").startswith(chat.COMPACT) and attrs.get(wake.COMPACT)
    if not (attrs.get("waiting") or attrs.get(wake.REST) or attrs.get(wake.FINISHED) or compact) \
            or attrs.get("session") and attrs["session"] != payload.get("session_id"):
        return
    common = gitx.common_dir(cwd)
    if common:
        provision.mark(cwd, gitx.root_of(common), {"waiting": None, "waiting-why": None, wake.REST: None, wake.FINISHED: None,
                                                   **({wake.COMPACT: None, wake.COMPACT_FOCUS: None} if compact else {})}, gitx)
        if attrs.get("waiting"):
            record = {"id": attrs["waiting"], "kind": RESUMED, "at": now(), "place": cwd, "session": payload.get("session_id")}
            for inbox in dict.fromkeys(x for x in (deliver.inbox_of(common), attrs.get("boss-inbox")) if x and os.path.isdir(x)):
                deliver.log(inbox, record)


def ended_well(payload, attrs_of=_attrs):
    """ターンが誤りなく終わった（Stop。誤りで終わったターンでは Stop の代わりに StopFailure が走る）: 使用上限か時間帯で止まった会話を
    --move --if-limited が待っている印（company.limit-hold）を外す。会話はもう続いて区切れたので、待っている処理は続きの 1 行を打たずに
    やめる。人の文で外さないのは、その文のターンがまた断られることがあるため（断られたら印を残し、待っている処理が続けさせる。
    フックは同じ場所で 10 分の間に 2 度は走らないので、そのターンで新しく待ち始める処理は無い）。外すのは、場所の属性の会話がこの会話のときだけ。"""
    if chat.event(payload) != "Stop":
        return
    cwd = payload.get("cwd") or os.getcwd()
    attrs = attrs_of(cwd)
    if not attrs.get(wake.LIMIT_HOLD) or attrs.get("session") and attrs["session"] != payload.get("session_id"):
        return
    common = gitx.common_dir(cwd)
    if common:
        provision.mark(cwd, gitx.root_of(common), {wake.LIMIT_HOLD: None}, gitx)


def resume_here(payload):
    """人の文でターンが始まった（--resume。会話が文を読む前に走る）: 答え待ちと区切りの印を外す（resume_from_wait）。"""
    try:
        resume_from_wait(payload)
    except (gitx.GitError, OSError) as e:
        print(f"works-dispatch: 答え待ちの印を外せなかった（{e}）", file=sys.stderr)
    return 0


def pause_here(payload):
    """人の文でターンが始まった（--pause。裏で走る）: その場所の待ち受けを止める（印の token を書き替える。印は消さない）。"""
    got = plan(payload)
    if not got:
        return 0
    held = wake.read_mark(got["inbox"], got["place"])
    if held and held.get("session") == got["session"]:
        wake.claim(got["inbox"], got["place"], held.get("names") or got["names"], got["session"], got["owner"], "paused",
                   held.get("since") or time.time())
    return 0


def keep_job(got, attrs_of=_attrs):
    """部署の属性 company.job（落ちた部署を attach で戻すときと、/clear を打つ窓を確かめるときの短い id）を、この会話の裏の処理の
    短い id に合わせる。裏の会話を起動し直すと短い id が替わり、古い id のままだと窓を自分の物と確かめられずに順番待ちを渡さなかった
    （2026-10-17 の割り振り。属性は a5b0bc07、窓は 8c4a1102 に attach していた）。書けなくても待ち受けは続ける。"""
    try:
        if got.get("job") and attrs_of(got["cwd"]).get("job") != got["job"]:
            provision.mark(got["cwd"], got["root"], {"job": got["job"]}, gitx)
    except (gitx.GitError, OSError):
        pass


def woken(got, attrs_of=_attrs):
    """待ち受けが会話を再開させる（納品・足しの知らせか、順番待ちの頼みを渡す）ときに、毎回クリアする部署（役が fresh）なら、空にした印
    （company.cleared）を外す。起動されたターンの文脈が会話に残るので、そのターンの終わりに待ち受けがまた空にする（must_clear）。今までは、
    頼みを受けていないターン（社長室の納品で起動された業務改革など）の後も印が残り、次の頼みが前のターンの文脈のまま渡った
    （my_notes の受付 f4ca34 で見つかった。6a9337）。人が窓に打ったターンでは外さない（持ち主と話している途中の会話を空にしない）。"""
    attrs = attrs_of(got["cwd"])
    if attrs.get("fresh") == role.FRESH and attrs.get("cleared"):
        provision.mark(got["cwd"], got["root"], {"cleared": None}, gitx)


HANDED_OVER = "WORKS_DISPATCH_WAKE_FROM"   # 前の版の待ち受けから替わった印（値は前の待ち受けの印の token）


def newer_self(script=__file__, look=installed.look, posix=os.name != "nt"):
    """今入っている版の wake_hook.py が、この待ち受けの版と別の置き場に在れば、そのパス（無い・この版なら None）。
    /reload-plugins は裏で待っている待ち受けを止めないので（nodes/refresh.py）、版を上げる前に立った待ち受けは、何時間も前の版のまま
    頼みを渡しうる（2026-10-21 に my_notes の調べものへ、0.103.1 で足した作業場を進める直しの無い前の版が、入ってから 9 時間半後に渡した。
    my_notes の受付 35aa1b）。環境の乗り換えた先の印（installed.HOPPED）は見ない（dispatch.py の乗り換えた先が起動した会話にも継がれている）。
    Windows では替わらない（os.execv が呼んだ側に先に戻るので子として起動するしかなく、子の親が会話の処理でなくなり、会話が終わっても
    子が残って生きた待ち受けに見え続ける）。"""
    if not posix:
        return None
    there, why = look(script, {})
    if why:
        filex.warn(f"注記: 今入っている版の待ち受けを探せないので、この版のまま待つ（{why}）")
    return there


def hop(there, argv, payload, token, execv=os.execve):
    """今入っている版の待ち受け there に、同じ引数とフックの入力で替わる（POSIX だけ。newer_self）。exec で同じ処理のまま替わるので、
    処理の番号・親の会話の処理・Claude Code が読む標準エラーと終了の値がそのまま続く。フックの入力は読み終えているので、書いた一時の
    ファイルを標準入力に付け直す。token（この待ち受けの印）を環境の HANDED_OVER で渡し、替わった先は印がまだそれなら続ける（替わる間に
    人の文で止められていれば〔--pause〕終わる。main）。exec できなければ OSError を投げる（呼んだ側がこの版のまま待ち直す）。"""
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    with tempfile.TemporaryFile() as f:
        f.write(data)
        f.flush()
        os.lseek(f.fileno(), 0, os.SEEK_SET)
        os.dup2(f.fileno(), 0)
    sys.stdout.flush()
    sys.stderr.flush()
    return execv(sys.executable, [sys.executable, there, *argv], {**os.environ, HANDED_OVER: token})


class WithRole:
    """会話を再開させる字（err に書く物）の頭に、その会話の役の文が替わっていれば今の文を足す（role_hook.changed）。"""

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


def main(argv=None, stdin=sys.stdin, err=sys.stderr, newer=newer_self, jump=hop, now=time.time, env=os.environ):
    argv = sys.argv[1:] if argv is None else argv
    try:
        payload = json.loads(stdin.read() or "{}") or {}
    except ValueError:
        return 0
    if argv[:1] == ["--resume"]:
        return resume_here(payload)
    if argv[:1] == ["--pause"]:
        return pause_here(payload)
    # 前の版の待ち受けから替わった（hop）。フックの入力は何時間も前の物なので、ターンの終わりの後始末（ended_well）はもう済んでいて、
    # 繰り返さない。印は外す（ここから起動する --retire などの子に継がせない）
    handed = env.pop(HANDED_OVER, None)
    if not handed:
        try:
            ended_well(payload)
        except (gitx.GitError, OSError) as e:
            print(f"works-dispatch: 使用上限で止まった会話を待つ印を外せなかった（{e}）", file=err)
    got = plan(payload)
    if not got:
        return 0
    if handed and (wake.read_mark(got["inbox"], got["place"]) or {}).get("token") != handed:
        return 0   # 替わる間に、人の文で止められた（--pause）か、新しい待ち受けに替わった
    if got["adopt"]:
        try:
            attrs = gitx.worktree_attrs(got["cwd"])
            provision.mark(got["cwd"], got["root"], provision.renew_session(attrs, got["session"]), gitx)
        except (gitx.GitError, OSError):
            return 0
    keep_job(got)
    inner, there = checker(got, payload), []

    def check():
        # 頼みを渡すか空にする前に、今入っている版に替わる（替わった先の待ち受けが、同じ順番待ちと台帳の読んだ所から続ける）
        try:
            found = there == [] and newer()
        except (OSError, ValueError, TypeError, AttributeError) as e:   # 控えの形が思っていたのと違う。この版のまま待つ
            filex.warn(f"注記: 今入っている版の待ち受けを探せないので、この版のまま待つ（{type(e).__name__}: {e}）", err)
            found = None
        if found:
            there.append(found)
            return "end", None
        return inner()
    while True:
        token = wake.new_token()

        def stop(*_, token=token):
            # 会話が終わる（claude stop）・フックの持ち時間が尽きると Claude Code が TERM を送る。印を消して、送る側をすぐ予備へ回す
            wake.release(got["inbox"], got["place"], token)
            sys.exit(0)
        for name in ("SIGTERM", "SIGHUP", "SIGINT"):
            if hasattr(signal, name):
                signal.signal(getattr(signal, name), stop)
        code = wake.watch(got["inbox"], got["place"], got["names"], got["session"], got["owner"], token,
                          WithRole(err, payload, woke=lambda: woken(got)), check=check, ready=lambda: not unready(payload, got["job"]),
                          since=got.get("since"))
        if code or len(there) != 1:
            return code
        if (wake.read_mark(got["inbox"], got["place"]) or {}).get("token") != token:
            return 0   # check の後に、人の文で止められた（--pause）か、新しい待ち受けに替わった
        row = {"kind": "hopped", "at": now(), "place": got["cwd"], "session": got["session"],
               "from": str(pathlib.Path(__file__).resolve().parent.parent), "to": str(pathlib.Path(there[0]).parent.parent)}
        try:
            deliver.log(got["inbox"], row)   # exec の後には書けないので先に書く
        except OSError as e:  # 台帳に書けなくても替わる
            filex.warn(f"注記: 待ち受けを今の版に替えたことを台帳に書けない（{e}）", err)
        try:
            return jump(there[0], argv, payload, token)
        except OSError as e:
            # 替われなければ、この版のまま待ち直す（待ち受けが居なくなると、次のターンの終わりまで順番待ちを渡す者が居ない）
            filex.warn(f"注記: 今入っている版の待ち受け {there[0]} に替われないので、この版のまま待つ（{e}）", err)
            there.append(None)
            try:
                deliver.log(got["inbox"], {**row, "at": now(), "status": "failed", "detail": str(e)})
            except OSError as e2:
                filex.warn(f"注記: 替われなかったことを台帳に書けない（{e2}）", err)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # 待ち受けの誤りで会話を再開させない（終了の値 2 だけが会話を再開させる。1 は訳を残して終わる）
        print(f"works-dispatch の待ち受けが動かなかった: {e}", file=sys.stderr)
        sys.exit(1)
