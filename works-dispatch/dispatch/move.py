#!/usr/bin/env python3
"""--move <部署か窓口>（move）: 立っている部署か本社の窓口の会話を、ほかのアカウント（--account で名指せば今のアカウント）で
起動し直す（37f8b1・d7d50c の 3）。

永続の部署の会話は、起動したアカウントが 5 時間か 1 週間の使用上限に当たると、上限が戻るまで止まる。--move は、移る先のアカウント
（--account で名指すか、使用率の順で今のアカウントの次に空いている物）で、同じ役・名前・場所の会話を起動し直す。同じ役の会話が
同時に 2 つ動かないよう、前の会話を止めてから起動する。会話の記憶は引き継がない（自動の覚え書きにも頼らない）ので、起動した会話への
最初の文で、受けている頼み（属性 company.ask と頼みのファイル）と作業場のブランチから続きへ戻らせる。

- 部署（裏の会話。claude --bg）: 窓の attach の画面をシェルに戻し（launch.to_shell）、前の会話を claude stop で止め、--task と同じ道
  （dispatch._task）で同じ名前・ブランチ・役の会話を、移る先のアカウントで起動する。頼み元の属性（company.boss など）はそのまま残す。
- 本社の窓口（持ち主の前で動く会話。--desk で名付けた物）: 窓口の窓に /exit を打って前の会話を終え、同じペインで
  `<移る先のコマンド> --name <窓口の名前> [--model …] [--effort …] [--settings <役の設定のファイル>] <最初の文>` を打つ。窓口の役に
  起動の設定（会社の形の [roles.settings]）が有れば、代表の clone の .git の場所に書いて --settings で渡す（--task が部署に渡すのと
  同じ設定。部署だけの鍵は重ねない）。model・effort は役の値（effort の inherit は旗を付けない）。起動した値は属性 company.launched に
  書き、company.launching を付ける（起きた会話の --desk が launching を外し、launched を残す）。起きた会話は窓口の席に座り（前の会話が
  終わっていて、名前が窓口の名前なので、会話の始まりのフックが役の本文を足す）、最初の文のとおり --desk を打って属性を自分に付け替える。
  窓口の会話がターンの途中（herdr の状態が working か blocked）か、窓の入力フィールドに字が在るときは /exit を打たない（ターンの途中に打った /exit は
  ターンの終わりまで待ちの列に回り、起動し直さずに止まった後で効いて、窓口が消えたままになりうる。窓口が自分の番の中で打った --move）。

--account に今のアカウントを名指すと、同じアカウントのまま、会社の形の今の起動の設定で起動し直す（持ち主が起動し直してよいと
答えた、区切りを印さない会話を引き継ぐ部署。受付 93d98b）。部署の窓に会話が見えていれば（窓口と同じく）、ターンの途中か入力フィールドに字が
在るときは止めずに NOT_NOW で終わる（使用上限で移す --if-limited を除く）。会話の外から打った --move がそうして止まったら
（--if-changed を除く）、起動し直さなかった訳をその会話に台帳の知らせで渡す。--account を名指したときは、そのアカウントを属性
company.move-to に印し、区切りで --if-changed がそのアカウントで起動し直す（区切りまで待って移す口。2026-10-19 に p3 の 5 部署を手で
移そうとして、5 つともターンの途中で止まった）。今のアカウントを名指したときも同じく印し、区切りで同じアカウントのまま起動し直す
（2026-10-20、調べものが自分の会話から同じアカウントで起動し直そうとして、印が残らなかった。受付 c149fa）。
知らせは待ち受けが入力フィールドに打たずに会話へ渡すので、持ち主はその会話の窓で訳を見る（打ちかけの字は消えない）。

--if-limited は、上限に当たって止まったときのフック（limit_hook.py）が付ける。今のアカウントの使用率の控えが上限に達しておらず、
使える時間帯（設定の hours）の中でもあれば（一時の混み合いの rate_limit）、移さない。移したことは会社の受付箱の台帳に kind moved で残す。
移さないときと移る先が無いときは、止まった会話をそのままにせず待つ（止まった会話は待ち受けを張らず、ほかに続けさせる物が無い。受付 e33748）。
待つ長さは WAIT から LONGEST の間で、選べるアカウントが無ければ一番早く選べるようになる時刻（accounts.next_look）まで。待った後に見直し、
今のアカウントが使えれば同じ会話に続きの 1 行（GO_ON）を打ち（会話の記憶を残す）、使えずにほかのアカウントが空けば移す。続きの 1 行が
また断られ続けるときは、待つ間を 2 倍ずつ延ばす（LONGEST まで）。待った後に会話がもう動いていれば何もせずにやめ、窓の入力フィールドに
打ちかけの字が在れば待ち直す。待つ間の一時の誤り（herdr や git に届かない・設定を読めない）と、移す先で起動できなかったときと、
続きの 1 行が届かなかったときも待ち直す。部署を移したときも、新しい会話の初めのターンが断られうる（フックは同じ場所で 10 分の間に
2 度は走らない）ので、印を付けて 1 度見直す。待ちの印
（属性 company.limit-hold）が替われば（ターンが誤りなく終わった〔wake_hook.ended_well が外す〕・起動し直した・後から止まった回の
--move が待ちを引き継いだ）、何もせずにやめる。

--if-changed は、待ち受け（wake_hook.py）が付ける。毎回クリアする部署（役が fresh）では次の頼みを渡す前（6bdc72）、会話を引き継ぐ
部署と本社の窓口では、会話が自分で区切りと印した（--rest）ターンの終わりに、/clear の代わりに走らせる。/clear は会話を空にしても
起動したときの --model・--effort・--settings を残すので、会社の形の起動の設定を替えても、立っている会話には起動し直すまで効かない。
会話の中で /model を打つと、そのアカウントの新しい会話の既定まで替わる（持ち主の会話にも効く）ので打たない。会社の形の今の値
（role.launch_key。origin の既定のブランチを取り直してから読む）が、起動したときの値（属性 company.launched）と違えば起動し直す。
アカウントは、今のアカウントの使用率が上限に届かなければ同じアカウント、届けば空いているほかの物。どれも無ければ起動し直さない。
起動の設定が同じでも、名指し（company.move-to）が今のアカウントなら、同じアカウントのまま起動し直す（SAME）。
起動の設定が同じでも、使用上限に当たる前の区切りで、空いているアカウントへ早めに移す（accounts.early）。移すのは、--move の名指し
（company.move-to）が在るときと、今のアカウントが使える時間帯の外か、終わりまで設定の hours_margin_minutes（既定 30 分）を切ったときと、今のアカウントの 5 時間か週の枠が設定の move_early_percent（既定 90%）に達し、達した枠のどれかが
move_early_reset_hours（既定 1 時間）より先まで戻らないとき。移る先は、使用率の高い方の枠が move_early_percent に届かないほかの
アカウントのうち、使用率の順の頭。移る先が無いなどで移さなかった訳は、台帳に kind moved・status skipped で残す。
区切りの印の無い、会話を引き継ぐ部署と窓口は起動し直さない（持ち主と話している途中の会話を切らない。区切りの印は、人がその
会話に打つと外れる）。区切りで起動し直しても、/clear で空にするのと比べて失う物は無い。前の会話を止めたら、待ち受けが付けた印
（属性 company.restarting）と区切りの印を外す。待ち受けは --if-changed が終わるのを待ち、印が残っていれば（前の会話を止めずに終わった）、
頼みを前の会話に渡す（wake_hook.restart_first）。窓口か部署の会話がターンの途中か窓の入力フィールドに打ちかけの字が在って止めなかったときは
NOT_NOW（75）で終わり、待ち受けは今の値を残さずに次の区切りで試し直す。入力フィールドの薄字（Claude Code の次の文の候補）は打ちかけと
数えない（claudex.typed）。
"""

import argparse
import os
import pathlib
import sys
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from ports import chat, term  # noqa: E402
import config  # noqa: E402
import gitx  # noqa: E402
import orders  # noqa: E402
import role_hook  # noqa: E402
from nodes import accounts, deliver, launch, provision, role  # noqa: E402
from nodes import wake  # noqa: E402

LIMITED = "使用上限に当たった"   # 台帳の why（--if-limited で移したとき）
CLOSED = "使える時間帯の外か終わる手前で止まった"   # 台帳の why（--if-limited で、今のアカウントが時間帯で選べないので移したとき）
CHANGED = "会社の形の起動の設定（model・effort・settings）が替わった"   # 台帳の why（--if-changed で起動し直したとき）
SAME = "持ち主か窓口が同じアカウントのまま起動し直した"   # 台帳の why（--account に今のアカウントを名指したとき）
EARLY = wake.EARLY   # 台帳の why（--if-changed で、使用率の目安か --move の名指しで移したとき・移さなかったとき）
NO_FLAGS = role.launch_key(None)   # company.launched の無い部署（この版より前に起動した）は、旗なしで起動したと見る
# 起動し直しても残す頼み元の属性（--task が呼んだ会話で書き直す物）
KEEP = ("boss", "boss-account", "boss-session", "boss-pane", "boss-inbox")
# 前の裏の会話が止まったのを会話の一覧で見る回数（1 回ごとに ports.pause）
STOP_LOOKS = 20
NOT_NOW = wake.NOT_NOW   # 今は起動し直さない（ターンの途中・打ちかけの字）。待ち受けが次の区切りで試し直す
# 今は起動し直さないで終わったときに、その会話の中か待ち受けから打った --move の出力に添える案内（外から打てば、訳を知らせで渡す）
INSIDE = ("。--account を名指して打てば、次の区切り（毎回クリアする部署は次の頼みを渡す前、ほかは頼みを納品した後にその会話で --rest を"
          "打ったターンの終わり）で、待ち受けがそのアカウントで起動し直すよう印す")
BUSY = ("working", "blocked")   # herdr が会話がターンの途中（動いている・確かめの画面で待つ）と見る状態。/exit を打たない
# --if-limited が移さずに待つとき、次に見直すまでの最短と最長の秒。最短はフックが続けて走らない間（limit_hook.AGAIN）と同じにする
# （待った後に打った 1 行がまた断られたら、フックがまた走って待ち直す）。最長の間で見直すのは、控えの取り直しや設定の替わりで
# 選べるアカウントが見込みより早く空くことがあるため
WAIT = 600
LONGEST = 3600
GONE_ON = "使用上限か使える時間帯で止まった会話を、待った後に同じアカウントで続けた"   # 台帳の nudged の行の why
WAITING = "waiting"   # 台帳の moved の行の status: 移さずに待ち始めた（待った後に、起動し直すか、同じ会話に続きの 1 行を打つ）
# 待った後に、止まった会話へ打つ続きの 1 行（{account} は今のアカウント）
GO_ON = ("続きの知らせです: 前のターンは、提供元が要求を断った誤り（使用上限・使える時間帯の外・同時の要求の超過など）で途中で止まった。"
         "アカウント {account} がまた使えるようになったので、止まった所から続ける。もう続けて済ませていれば、何もせずにこのターンを終える")


def move(a, ports, cwd, task):
    """--move。終了の値。--if-limited で移さずに待つと決めたら、決めた時刻まで待って見直す（_once が待ちを返す間、繰り返す）。"""
    token = None
    while True:
        try:
            got = _once(a, ports, cwd, task, token)
        except Exception as e:   # noqa: BLE001
            if token is None:
                raise
            # 待っている間の誤り（herdr に届かない・git の設定のロック・設定の書き替えの途中など）で待つのをやめない（会話が止まったまま残る）
            print(f"見直せなかった（{type(e).__name__}: {e}）。{WAIT // 60} 分後に見直す")
            got = {"until": ports.now() + WAIT, "token": token}
        if not isinstance(got, dict):
            return got
        token = got["token"]
        ports.sleep(max(got["until"] - ports.now(), 0))


def _once(a, ports, cwd, task, token):
    """--move を 1 度見る。終了の値か、待つなら {"until": 次に見直す Unix 時刻, "token": 待ちの印の字}。token は待った後の見直しなら
    前に書いた待ちの印の字（初めは None）。"""
    common = ports.git.common_dir(cwd)
    try:
        cfg, accounts_, sessions_, _, companies, settings, notes = orders.survey(a.config, ports)
        target = deliver.find_target(companies, gitx.root_of(common) if common else None, a.move)
    except term.Error as e:
        if token:
            raise   # 待っている間は、move が見直しを先へ延ばす
        print(f"止めた: {term.NAME} を読めない（{e}）")
        return 1
    except deliver.DeliverError as e:
        if token:
            raise
        print(f"止めた: {e}")
        return 2
    company, dept = target["company"], target["department"]
    if dept is None and token:
        print(f"待つのをやめた: 「{a.move}」という部署も窓口も無くなった")
        return 0
    if dept is None:
        print("\n".join(notes + [f"止めた: 「{a.move}」という部署も窓口も無い（起動し直すのは立っている部署か、--desk で名付けた窓口）"]))
        return 2
    if token and dept["attrs"].get(wake.LIMIT_HOLD) != token:
        print(f"待つのをやめた: {a.move} の待ちの印（company.{wake.LIMIT_HOLD}）が替わった（会話のターンが誤りなく終わったか、起動し直したか、"
              "後から止まった回の --move が待ちを引き継いだ）")
        return 0
    if a.if_changed:
        return _restart(a, ports, task, cfg, sessions_, company, dept, settings, notes)
    if cfg is None:
        if token:
            raise RuntimeError("dispatch の設定を読めない")   # 待っている間は、move が見直しを先へ延ばす
        print("\n".join(notes + ["止めた: 起動し直すには、読める dispatch の設定が要る（アカウントと使用率の上限を読む）"]))
        return 2
    attrs = dept["attrs"]
    old = attrs.get("account")
    names = [x.name for x in cfg.accounts]
    metered = [x.name for x in cfg.accounts if x.limits]
    if not a.dry_run:
        ports.refresh_limits(cfg, metered)
    ranked = accounts.rank(cfg.accounts, ports.read_limits(cfg.limits_dir, metered), cfg.limit_percent, ports.now(),
                           accounts.count_running(sessions_), cfg.reset_soon_hours, cfg.hours_margin_minutes)
    mine = next((r for r in ranked if r["name"] == old), None)
    # 名指しのときだけ使うアカウント（named_only）で動いている会話は、名指しで立ったので、上限と時間帯で外れていなければ使える
    usable = bool(mine and (mine["eligible"] or mine.get("named_ok")) and not mine.get("stale_over"))
    passing = usable and (mine["known"] or mine.get("stale"))   # 使用率の分かる今のアカウントが上限に届かない: 一時の混み合い
    if a.if_limited and not a.dry_run and (passing or token and usable):
        if token:
            # 待った後も今のアカウントが使える: 同じ会話に続きの 1 行を打つ（会話の記憶を残す）
            return _go_on(ports, accounts_, sessions_, company, dept, mine, notes, token)
        return _hold(ports, company, dept, ranked, mine, notes, f"アカウント {old} の使用率は上限 {cfg.limit_percent}% に達していない"
                     "（一時の混み合いと見る）ので移さない", token)
    if a.if_limited and passing:
        print("\n".join(notes + [f"移さない: アカウント {old} の使用率は上限 {cfg.limit_percent}% に達していない（一時の混み合いと見る）。"
                                 f"{WAIT // 60} 分待って、同じ会話に続きの 1 行を打つ"]))
        return 0
    if a.account:
        if a.account not in names:
            print(f"止めた: --account の {a.account} が設定の accounts に無い（{', '.join(names)}）")
            return 2
        chosen = a.account
        row = next(r for r in ranked if r["name"] == chosen)
        # 上限か時間帯の外のアカウントは名指しても使わない。前の会話を止める前に止める（止めた後では起動できず、部署が空になる）
        if not (row["eligible"] or row.get("named_ok")):
            print("\n".join(notes + [f"止めた: アカウント {chosen} は、{row['reason']}"
                                     + ("（時間帯の外では要求が断られる）" if row["shut"] else "（使用率が上限のアカウントでは起動しない）")]))
            return 2
    else:
        chosen = next((r["name"] for r in ranked if r["name"] != old and r["eligible"]), None)
        if chosen is None and a.if_limited and not a.dry_run:
            return _hold(ports, company, dept, ranked, mine, notes, f"移れるアカウントが無い（{old or '-'} のほかに、使用率が上限に届かず、"
                         "使える時間帯の中のアカウントが無い）", token)
        if chosen is None and a.if_limited:
            print("\n".join(notes + [f"待つ: 移れるアカウントが無い（{old or '-'} のほかに、使用率が上限に届かず、使える時間帯の中のアカウントが無い）。"
                                     "待って見直し、ほかのアカウントが空けば移し、今のアカウントが使えれば同じ会話に続きの 1 行を打つ"]))
            return 0
        if chosen is None:
            print("\n".join(notes + [f"止めた: 移れるアカウントが無い（{old or '-'} のほかに、使用率が上限に届かず、使える時間帯の中のアカウントが無い）"]))
            return 2
    if chosen == old and a.if_limited:
        print(f"止めた: {a.move} はもうアカウント {old} で動いている（--if-limited は使用上限で移すので、今のアカウントを名指さない）")
        return 2
    head = bool(dept.get("head_office"))
    where = f"{company['name']}/{attrs.get('name') or dept['branch']}"
    why = (CLOSED if mine and mine["shut"] else LIMITED) if a.if_limited else SAME if chosen == old else "持ち主か窓口が移した"
    if a.dry_run:
        to = f"{chosen} のまま" if chosen == old else f"{old or '-'} から {chosen} へ"
        print("\n".join(notes + [f"{'窓口' if head else '部署'} {where} をアカウント {to}起動し直す（{why}）"]))
        return 0
    if token:
        # 待った後に移す: 待つ間に持ち主が続きを打って会話が動き出したか、窓に打ちかけているなら、止めない（止まった直後に移す
        # 初めの回と違い、会話はもう止まったままとは限らない）
        stay = _stay(dept, _pane_of(dept, ports), ports, company, token, notes, where)
        if stay is not None:
            return stay
    # 使用上限で移すときは、起動し直した部署の会話にも待ちの印を付ける。新しい会話の初めのターンも断られうる（移った先も同時の要求の
    # 超過を返すなど）が、フックは同じ場所で limit_hook.AGAIN 秒の間は走らないので、この処理が 1 度見直す（ターンが誤りなく終われば印が
    # 外れる）。窓口は見直さない: 新しい窓口の会話は --desk を打つまで属性の会話（company.session）が前の会話のままで、見直しても窓を
    # 見つけられず、印も外れない（窓口は持ち主の前で動く）
    watch = f"{os.getpid()}-{int(ports.now())}" if a.if_limited and not head else None
    try:
        rc = _relaunch(a, ports, task, cfg, company, dept, chosen, why, head, settings, notes, cwd, hold=watch)
    except Exception as e:   # noqa: BLE001
        if not a.if_limited:
            raise
        # 前の会話を止めた後の思わぬ誤りで、止まったまま残さない（フックは AGAIN 秒の間は走らない）
        print(f"起動し直す途中で誤りが出た（{type(e).__name__}: {e}）")
        rc = 1
    if a.if_limited and rc != 0:
        # 起動できなかった（前の会話へ戻した）か、窓口が今は止められなかった: 止まったまま残さず、待つ
        return _hold(ports, company, dept, ranked, mine, notes, f"アカウント {chosen} で起動し直せなかった", None)
    if watch:
        print(f"{WAIT // 60} 分後に、起動し直した会話が誤りで止まっていないかを見る（ターンが誤りなく終われば見ずにやめる）")
        return {"until": ports.now() + WAIT, "token": watch}
    return rc


def _pane_of(dept, ports):
    """止まった会話の居るペイン。窓口は属性の会話の居るペイン、部署は会話の居る窓（orders.live_window）。無ければ None。"""
    if dept.get("head_office"):
        sid = dept["attrs"].get("session")
        return next((p["pane_id"] for p in dept["panes"] if sid and p.get("agent_session") == sid), None)
    return orders.live_window(dept, ports)


def _stay(dept, pane, ports, company, token, notes, where, empty=False):
    """待った後に、窓の会話に手を出さない訳が在れば、その終わり方（会話が動いていれば待つのをやめて 0、入力フィールドに字が在れば
    待ち直す）。手を出してよければ None。empty なら、入力フィールドが見えて空なことまで求める（1 行を打つとき）。窓を読めなければ term.Error。"""
    if pane is None:
        return None
    status = (ports.term.agent(pane) or {}).get("agent_status")
    if status in BUSY:
        _unhold(dept, company, token, ports)
        print("\n".join(notes + [f"待つのをやめた: {where} の会話はもう動いている（{status}）"]))
        return 0
    box = chat.typed(ports.term.read(pane, 40, ansi=True))
    if not empty and wake.own_clear(box, dept["attrs"]):
        box = ""   # 待ち受けが打って残った /clear は、会話を止めれば一緒に消える（1 行を打つときは、その頭に付くので待ち直す）
    if box or empty and box is None:
        now = ports.now()
        print("\n".join(notes + [f"待つ: {where} の窓 {pane} の" + (f"入力フィールドに字（「{box[:20]}」）が在る（持ち主が打ちかけの字を消さない）"
                                                               if box else "入力フィールドが見えない")
                                 + f"。{time.strftime('%H:%M', time.localtime(now + WAIT))} に見直す"]))
        return {"until": now + WAIT, "token": token}
    return None


def _unhold(dept, company, token, ports):
    """待ちの印がまだこの処理の字なら外す（後から待ち始めた --move の字は消さない）。"""
    try:
        now_mark = (ports.attrs(dept["path"]) or {}).get(wake.LIMIT_HOLD)
    except (gitx.GitError, OSError):
        return
    if now_mark == token:
        provision.mark(dept["path"], company["root"], {wake.LIMIT_HOLD: None}, ports.git)


def _tries(inbox, place, now):
    """この場所で、続きの 1 行を打った最近（LONGEST の 3 倍の間）の回数。続きの 1 行がまた断られ続けるときに、待つ間を延ばす。"""
    return sum(1 for r in deliver.records(inbox) if r.get("kind") == "nudged" and r.get("why") == GONE_ON
               and r.get("place") == place and isinstance(r.get("at"), (int, float)) and now - r["at"] < 3 * LONGEST)


def _hold(ports, company, dept, ranked, mine, notes, why, token):
    """--if-limited で移さずに待つ。初めて待つ（token が None）ときは、待ちの印（company.limit-hold）をこの処理の字で書き（前に待って
    いた処理は、印が替わったのを見てやめる）、台帳に kind moved・status waiting で残す。{"until", "token"}。"""
    attrs = dept["attrs"]
    now = ports.now()
    inbox = deliver.inbox_of(ports.git.common_dir(company["root"]))
    # 続きの 1 行がまた断られ続ける（使用率の控えに出ない上限など）なら、打つ間を 2 倍ずつ延ばす（LONGEST まで）
    until = min(max(accounts.next_look(ranked, now, WAIT), now + WAIT * 2 ** _tries(inbox, dept["path"], now)), now + LONGEST)
    if token is None:
        token = f"{os.getpid()}-{int(now)}"
        provision.mark(dept["path"], company["root"], {wake.LIMIT_HOLD: token}, ports.git)
        deliver.log(inbox,
                    {"kind": "moved", "at": now, "name": attrs.get("name"), "path": dept["path"], "from": attrs.get("account"),
                     "to": None, "why": CLOSED if mine and mine["shut"] else LIMITED, "status": WAITING, "detail": why})
    at = time.strftime("%H:%M", time.localtime(until))
    print("\n".join(notes + [f"待つ: {why}。{at} に見直す（ほかのアカウントが空けば移し、今のアカウントが使えれば同じ会話に続きの 1 行を打つ）"]))
    return {"until": until, "token": token}


def _go_on(ports, accounts_, sessions_, company, dept, mine, notes, token):
    """待った後に、止まった会話（部署の窓か、窓口の会話の居るペイン）へ続きの 1 行（GO_ON）を打ち、台帳に kind nudged で残す。
    部署の窓に会話が居なければ attach で戻す。会話が動いていれば打たずにやめ、入力フィールドに字が在るか見えなければ待ち直す。
    会話の居るペインが無い（戻せない）ときも待ち直す。終了の値か待ち。"""
    attrs = dept["attrs"]
    where = f"{company['name']}/{attrs.get('name') or dept['branch']}"
    said = None
    pane = _pane_of(dept, ports)
    if pane is None and not dept.get("head_office"):
        pane, said = orders.revive(dept, accounts_, ports, sessions_, company["root"])
    inbox = deliver.inbox_of(ports.git.common_dir(company["root"]))
    ask = attrs.get("ask") if attrs.get("ask") and attrs.get("delivered") != attrs.get("ask") else None
    row = {"id": ask, "kind": "nudged", "at": ports.now(), "place": dept["path"], "pane": pane, "why": GONE_ON}
    if pane is None:
        said = said or "窓口の会話の居るペインが無い"
        deliver.log(inbox, {**row, "status": "failed", "detail": said})
        now = ports.now()
        print("\n".join(notes + [f"待つ: {where} の止まった会話に続きの 1 行を打てなかった（{said}）。"
                                 f"{time.strftime('%H:%M', time.localtime(now + LONGEST))} に見直す"]))
        return {"until": now + LONGEST, "token": token}
    stay = _stay(dept, pane, ports, company, token, notes, where, empty=True)
    if stay is not None:
        return stay
    keep = {k: attrs[k] for k in orders.KEPT_MARKS if attrs.get(k)}
    sent, detail = deliver.send_confirmed(pane, GO_ON.format(account=mine["name"]), ports.term, ports.pause,
                                          orders.busy_check(dept, accounts_, ports))
    detail = orders._put_back(dept, keep, ports, detail)
    deliver.log(inbox, {**row, "status": sent, "detail": "。".join(x for x in (said, detail) if x) or None})
    print("\n".join(notes + [f"{where}: 止まった会話に、アカウント {mine['name']} のまま続きの 1 行を打った（{sent}）"
                             + (f"。{said}" if said else "") + (f"。{detail}" if detail else "")]))
    if sent != "sent":
        # 届かなかった（herdr の一時の誤りなど）: 印を残して待ち直す（打った回に数えるので、待つ間は延びていく）
        now = ports.now()
        return {"until": now + min(WAIT * 2 ** _tries(inbox, dept["path"], now), LONGEST), "token": token}
    _unhold(dept, company, token, ports)
    return 0


def _relaunch(a, ports, task, cfg, company, dept, chosen, why, head, settings, notes, cwd=None, early_why=None, hold=None):
    """前の会話を止めて、アカウント chosen で起動し直し、台帳に kind moved で残す。終了の値。cwd は --move を打った場所
    （その会話の外から打って、今は起動し直さないで終わったら、訳をその会話に知らせる）。early_why は区切りで早めに移す訳（台帳に添える）。
    hold は起動する前に書く待ちの印（company.limit-hold）の字（None なら外す）。"""
    attrs = dept["attrs"]
    old = attrs.get("account")
    acc = {x.name: x for x in cfg.accounts}
    if head:
        text = _first_text(attrs, dept, old, chosen, why, head) + _handoff_line(
            os.path.join(ports.git.git_dir(company["root"]), wake.HANDOFF))
        rc, said = _move_desk(company, dept, acc[chosen], text, ports, settings, acc.get(old), hold)
    else:
        rc, said = _move_dept(a, cfg, company, dept, acc.get(old), chosen, lambda at: _first_text(at, dept, old, chosen, why, head),
                              ports, task, settings, hold)
    inbox = deliver.inbox_of(ports.git.common_dir(company["root"]))
    deliver.log(inbox, {"kind": "moved", "at": ports.now(), "name": attrs.get("name"), "path": dept["path"], "from": old,
                        "to": chosen, "why": why, "status": "done" if rc == 0 else "failed",
                        "detail": "。".join(x for x in (early_why, said) if x) or None})
    where = f"{company['name']}/{attrs.get('name') or dept['branch']}"
    told = None
    if why == EARLY and rc not in (0, NOT_NOW):
        # 起動できずに前の会話へ戻した。同じ先へは早めに移し直さない（区切りのたびに止めて戻すのを繰り返さない）
        provision.mark(dept["path"], company["root"], {wake.MOVE_KEPT: chosen}, ports.git)
    if rc == NOT_NOW and not (a.if_changed or a.if_limited) and a.account:
        # 区切りまで待って移す（待ち受けの --if-changed が、毎回クリアする部署は次の頼みを渡す前、ほかは --rest のターンの終わりに移す。
        # 今のアカウントを名指したなら、同じアカウントのまま起動し直す）
        provision.mark(dept["path"], company["root"], {wake.MOVE_TO: chosen}, ports.git)
        said += (f"。次の区切り（毎回クリアする部署は次の頼みを渡す前、ほかは" + ("頼みを納品した後に " if chosen == old else "")
                 + f"その会話で --rest を打ったターンの終わり）で{'起動し直す' if chosen == old else '移す'}よう印した（属性 company.{wake.MOVE_TO}）")
    if rc == NOT_NOW and not (a.if_changed or a.if_limited) and cwd and not deliver.inside(cwd, dept["path"]):
        told = _tell(inbox, company["name"], dept, old, chosen, said, ports)
    elif rc == NOT_NOW and not a.account:
        said += INSIDE
    print("\n".join(notes + [f"{'窓口' if head else '部署'} {where}: アカウント {old or '-'} → {chosen}  "
                             + ("起動し直した" if rc == 0 else "起動し直せなかった") + (f"（{said}）" if said else "")]
                     + ([told] if told else [])))
    return rc


def _tell(inbox, company_name, dept, old, chosen, said, ports):
    """今は起動し直さないで止めた訳を、起動し直そうとした会話に台帳の知らせで渡す（待ち受けが入力フィールドに打たずに会話へ渡すので、
    持ち主はその会話の窓で訳を見る）。待ち受けが居ないか張った跡も無ければ渡さない（--note と同じ見方）。出す行。"""
    to, heard = orders.listener(inbox, company_name, dept["attrs"].get("name"))
    if not (to and (heard or wake.has_history(inbox, ports.git.git_dir(dept["path"])))):
        return f"注記: {to or '名前の無い会話'} には待ち受けの跡が無いので、起動し直さなかった訳を知らせていない"
    if chosen == old:
        text = (f"知らせ（返事は要らない）: この会話を --move で同じアカウント {chosen} のまま起動し直そうとしたが、止めた（{said}）。"
                "次の区切り（毎回クリアする部署は次の頼みを渡す前、ほかは頼みを納品した後にこの会話で dispatch.py --rest を打ったターンの"
                f"終わり）で、待ち受けが同じアカウント {chosen} のまま、会社の形の今の起動の設定で起動し直す")
    else:
        text = (f"知らせ（返事は要らない）: この会話を --move でアカウント {chosen} へ移して起動し直そうとしたが、止めた（{said}）。"
                "区切り（毎回クリアする部署は次の頼みを渡す前、ほかはこの会話で dispatch.py --rest を打ったターンの終わり）で、"
                f"待ち受けがアカウント {chosen} へ移す。頼みの途中でも、区切りのよい所で作業場の git ディレクトリ（git rev-parse --git-dir）の"
                f" {wake.HANDOFF} に引継ぎ（済んだこと・次の手）を書いて --rest を打てば、そのターンの終わりに移り、新しい会話が頼みを続ける")
    try:
        deliver.log(inbox, wake.notice(to, None, wake.NOTE, None, text, ports.now()))
    except OSError as e:
        return f"注記: 止めた訳を {to} の会話に知らせられなかった（{e}）"
    return f"注記: 止めた訳を {to} の会話に台帳の知らせで渡した（持ち主はその会話の窓で見る）"


def _restart(a, ports, task, cfg, sessions_, company, dept, settings, notes):
    """--if-changed。毎回クリアする部署か、区切りと印した（--rest）部署・窓口を、会社の形の起動の設定が起動したときと違えば
    起動し直す。終了の値。"""
    attrs = dept["attrs"]
    where = f"{company['name']}/{attrs.get('name') or dept['branch']}"
    if a.if_limited or a.account:
        print("止めた: --if-changed は --if-limited・--account と一緒に使わない（アカウントは今の物を先に選ぶ）")
        return 2
    head = bool(dept.get("head_office"))
    if not attrs.get(wake.REST) and (head or attrs.get("fresh") != role.FRESH):
        print("\n".join(notes + [f"止めた: {where} は毎回クリアする部署でなく、区切りの印（--rest）も無い（会話を引き継ぐ部署と窓口は、"
                                 "話の流れを切らないよう、区切りのターンの終わりにだけ起動し直す）"]))
        return 2
    if cfg is None:
        print("\n".join(notes + ["止めた: 起動し直すには、読める dispatch の設定が要る（アカウントと使用率の上限を読む）"]))
        return 2
    if not a.dry_run:
        notes = notes + [n for n in [provision.refresh_shape(company["root"], ports.git)] if n]
    now_key = role_hook.launch_key(dept["path"], attrs, ports.env)
    if now_key is None:
        print("\n".join(notes + [f"起動し直さない: {where} の会社の形を読めない（役が無いか、読めない所がある）"]))
        return 0
    changed = now_key != (attrs.get(wake.LAUNCHED) or NO_FLAGS)
    old = attrs.get("account")
    metered = [x.name for x in cfg.accounts if x.limits]
    if not a.dry_run:
        ports.refresh_limits(cfg, metered)
    now = ports.now()
    ranked = accounts.rank(cfg.accounts, ports.read_limits(cfg.limits_dir, metered), cfg.limit_percent, now,
                           accounts.count_running(sessions_), cfg.reset_soon_hours, cfg.hours_margin_minutes)
    # 使用上限に当たる前の区切りで、空いているアカウントへ早めに移す（上限で移す --if-limited はターンの途中で切られ、そのターンの作業が消える）
    early = accounts.early(ranked, old, cfg.early_percent, cfg.early_reset_hours, now, attrs.get(wake.MOVE_TO), attrs.get(wake.MOVE_KEPT))
    if early and early["to"] is None and not a.dry_run:
        # 移さなかった訳を台帳に残す（同じ訳は 1 度だけ）。待ち受けが同じ訳で何度も打たないよう、名指しの印は外す
        seen = f"{old}/{early['kind']}"
        if attrs.get(wake.MOVE_SKIPPED) != seen:
            deliver.log(deliver.inbox_of(ports.git.common_dir(company["root"])),
                        {"kind": "moved", "at": now, "name": attrs.get("name"), "path": dept["path"], "from": old, "to": None,
                         "why": EARLY, "status": "skipped", "detail": early["why"]})
        provision.mark(dept["path"], company["root"], {wake.MOVE_TO: None, wake.MOVE_SKIPPED: seen}, ports.git)
    again = attrs.get(wake.MOVE_TO) == old and old is not None   # --move が今のアカウントを名指したが、ターンの途中で起動し直せなかった
    if not changed and not again and not (early and early["to"]):
        print("\n".join(notes + [f"起動し直さない: {where} の起動の設定は起動したときと同じ（{now_key}）"
                                 + (f"。{early['why']}" if early else "")]))
        return 0
    # 今のアカウントは、名指しのときだけ使うアカウント（named_only）でも、上限と時間帯で外れていなければ使える（名指しで立った）
    roomy = [r["name"] for r in ranked if r["eligible"] or r["name"] == old and r.get("named_ok")]
    if again and not changed and not (early and early["to"]) and old not in roomy:
        # 同じアカウントの名指しなのに、そのアカウントが選べない。ほかへ移さず、印を外す（区切りのたびに試し直さない）
        if not a.dry_run:
            provision.mark(dept["path"], company["root"], {wake.MOVE_TO: None}, ports.git)
        print("\n".join(notes + [f"起動し直さない: --move で名指したアカウント {old} は使用率が上限に達したか、使える時間帯の外なので、"
                                 f"同じアカウントのまま起動し直さない（印 company.{wake.MOVE_TO} を外した）"]))
        return 0
    if not roomy:
        # 上限に達したアカウントで起動すると、--task が起動せずに終わり、前の会話だけが止まる。前の会話に渡させる
        print("\n".join(notes + [f"起動し直さない: 使用率が上限に届かず、使える時間帯の中のアカウントが無い（{where} は前の起動の設定のまま続ける）"]))
        return 0
    chosen, why = ((early["to"], EARLY) if early and early["to"] else (old if old in roomy else roomy[0], CHANGED if changed else SAME))
    if a.dry_run:
        print("\n".join(notes + [f"{'窓口' if head else '部署'} {where} をアカウント {chosen} で起動し直す（"
                                 + (f"{EARLY}: {early['why']}" if why == EARLY else SAME if why == SAME else
                                    f"{CHANGED}: {attrs.get(wake.LAUNCHED) or NO_FLAGS} → {now_key}") + "）"]))
        return 0
    return _relaunch(a, ports, task, cfg, company, dept, chosen, why, head, settings, notes, early_why=early and early["why"])


def _first_text(attrs, dept, old, chosen, why, head):
    """起動し直した会話への最初の文。会話の記憶は引き継がないので、続きへ戻る手がかり（頼みとブランチ）を渡す。"""
    ask = attrs.get("ask")
    pending = ask and attrs.get("delivered") != ask
    file = os.path.join(attrs.get("boss-inbox") or "", f"{ask}-ask.md") if pending else None
    head_line = (f"前の会話（アカウント {old or '-'}）が使用上限に当たったので、アカウント {chosen} で起動し直した。" if why == LIMITED else
                 f"前の会話（アカウント {old or '-'}）が使える時間帯の外か終わる手前で止まったので、アカウント {chosen} で起動し直した。" if why == CLOSED else
                 f"{CHANGED}ので、アカウント {chosen} で起動し直した。" if why == CHANGED else
                 f"前の会話を、同じアカウント {chosen} のまま、会社の形の今の起動の設定で起動し直した（--move）。" if why == SAME else
                 f"前の会話（アカウント {old or '-'}）を、使用上限か使える時間帯の終わりに当たる前の区切りで、アカウント {chosen} へ移して起動し直した。" if why == EARLY else
                 f"前の会話（アカウント {old or '-'}）を、アカウント {chosen} へ移して起動し直した（--move）。") + "前の会話の記憶は引き継いでいない。"
    if head:
        head_line += (f" まず、この会話の中から works-dispatch の --desk {attrs.get('name') or ''} を打って、窓口の席をこの会話に移す。"
                      "次に、受付箱の台帳（log.jsonl）と、本社の属性の頼み（company.ask）から、受けていた仕事の続きへ戻る。")
    if pending:
        head_line += (f" 受けている頼みは受付 {ask}（本文: {file if file and os.path.isfile(file) else '受付箱の ' + ask + '-ask.md'}）。"
                      f"作業場のブランチ {dept['branch'] or '-'} の commit と差分（git status・git log）から、続きを再開する。")
    elif not head:
        head_line += " 受けている頼みは無い。次の頼みを待つ。"
    return head_line


def _handoff_line(path):
    """前の会話が書いた引継ぎ（wake.HANDOFF）が在れば、最初の文に足す一文。引継ぎは書いた時刻の名前（handoff-<時刻>.md）に替えて
    退け、退けた先を指す（残すと、後の頼みの --move がその頼みの物でない引継ぎを指し続ける）。名前を替えられなければ、元の場所を指す。"""
    try:
        at = time.localtime(os.path.getmtime(path))
    except OSError:
        return ""   # 引継ぎを書いていない
    kept = os.path.join(os.path.dirname(path), f"handoff-{time.strftime('%Y%m%d-%H%M%S', at)}.md")
    try:
        os.replace(path, kept)
    except OSError:
        kept = path   # 退けられなくても、引継ぎは指す
    return f" 前の会話が書いた引継ぎ {kept}（{time.strftime('%Y-%m-%d %H:%M', at)} に書いた）が在る。続きを再開する前に読む。"


def _move_dept(a, cfg, company, dept, old_acc, chosen, text_of, ports, task, settings, hold=None):
    """部署の裏の会話を止め、--task と同じ道で移る先のアカウントの会話を起動する。(終了の値, 言葉)。text_of は属性から最初の文を作る。"""
    attrs = dept["attrs"]
    pane = next((p["pane_id"] for p in dept["panes"]), None)
    talk = deliver.window(dept)
    if talk and not a.if_limited:
        # 部署の窓で持ち主と話す会話（社長室など）を、ターンの途中や打ちかけの字の上から止めない（窓口の /exit と同じ守り）。
        # 使用上限で止まった会話は、待っても動かないので移す
        try:
            held = _held(talk, ports, "部署", "止めない", attrs)
        except term.Error as e:
            return 1, f"部署の窓 {talk} を読めない（{e}）"
        if held:
            return NOT_NOW, held
    if pane and not launch.to_shell(pane, ports.term, ports.pause):
        return 1, f"部署の窓 {pane} をシェルに戻せない（attach の画面を手で閉じてから打ち直す）"
    job = attrs.get("job") or attrs.get("session")
    if job:
        ok, said = ports.stop_session(old_acc.config_dir if old_acc else None, job)
        if not ok:
            return 1, f"前の会話 {job} を止められない（{said}）"
        for _ in range(STOP_LOOKS):
            try:
                items = ports.list_sessions(old_acc.config_dir if old_acc else None)
            except chat.Error:
                break
            if not any(s.get("name") == attrs.get("name") and s.get("state") not in ("done", "failed", "stopped") for s in items):
                break
            ports.pause()
    # 止めた後の属性で続ける。読んだ後、止めるまでの間に前の会話の待ち受けが順番待ちの頼みを渡していれば（属性の頼みと頼み元を
    # 書き替えてから会話を起動する）、渡した字は止めた会話と一緒に消えるので、その頼みを最初の文で渡し、頼み元も今の物を残す
    try:
        attrs = ports.attrs(dept["path"]) or attrs
    except (gitx.GitError, OSError):
        pass
    # 新しい会話の待ち受けが、前の会話の id を見て待たないことの無いよう、会話の id を消してから起動する（--task が新しい id を書く）
    # 前の会話は止まったので、--if-changed の待ち受けの印も外す（新しい会話の待ち受けがすぐ渡す）。毎回クリアする部署で頼みを納品し
    # 終えていれば、空にした印も書く（起動し直した会話は空なので、最初の文のターンの終わりに /clear を打たない）
    ask = attrs.get("ask")
    done = ask and attrs.get("delivered") == ask and attrs.get("fresh") == role.FRESH
    provision.mark(dept["path"], company["root"], {"session": None, "job": None, wake.RESTARTING: None, wake.RESTART_KEPT: None, wake.REST: None,
                                                   wake.MOVE_TO: None, wake.MOVE_KEPT: None, wake.MOVE_SKIPPED: None, wake.LIMIT_HOLD: hold,
                                                   **({"cleared": ask} if done else {})}, ports.git)
    brief = os.path.join(ports.git.git_dir(dept["path"]), "move-brief.md")
    pathlib.Path(brief).write_text(text_of(attrs) + _handoff_line(os.path.join(ports.git.git_dir(dept["path"]), wake.HANDOFF)) + "\n",
                                   encoding="utf-8")
    pending = ask and attrs.get("delivered") != ask
    the_role, _ = orders.shape_role(company["root"], settings, attrs.get("role"), ports.git)
    tail = deliver.tail(deliver.required_items(the_role), orders.RUN) if pending else None
    ns = argparse.Namespace(**{**vars(a), "task": attrs.get("name"), "branch": dept["branch"], "brief": brief,
                               "role": attrs.get("role"), "persistent": attrs.get("lifecycle") == gitx.PERSISTENT, "from_name": None,
                               "from_account": None, "only_account": chosen, "base": None, "dry_run": False})
    repo = config.repo_at(cfg, company["root"], ports.origin)
    rc = task(cfg, repo, ns, ports, extra_attrs={k: attrs.get(k) for k in KEEP}, tail=tail)
    if rc == 0:
        return 0, None
    # 新しい会話が立たなかった: 止めた前の会話を attach で戻す（裏の会話は止めても記録が残り、attach で前の続きから戻る）。
    # 新しい会話が立っていて窓につなぐ所だけ落ちたなら戻さない（同じ部署の会話を 2 つ立てない）
    try:
        risen = any(x.get("name") == attrs.get("name") and x.get("state") not in ("done", "failed", "stopped")
                    for x in ports.list_sessions(next((c.config_dir for c in cfg.accounts if c.name == chosen), None)))
    except chat.Error:
        risen = True   # 確かめられなければ戻さない
    if risen:
        back = "移る先のアカウントに同じ名前の会話が立っているか、確かめられないので戻さない"
    elif pane and job:
        back = launch.bring_back(pane, chat.attach_command(old_acc.command if old_acc else None, job), ports.term)
    else:
        back = "戻す窓か会話の id が無い"
    if back is None:
        provision.mark(dept["path"], company["root"], {k: attrs.get(k) for k in ("session", "job", "account", wake.LAUNCHED, "cleared")}, ports.git)
    return rc, "--task と同じ道で起動できなかった（上の出力を見る）。" + ("前の会話を attach で戻した" if back is None else f"前の会話も戻せなかった（{back}）")


def _move_desk(company, dept, acc, text, ports, settings, old_acc=None, hold=None):
    """窓口の会話を /exit で終え、同じペインで移る先のアカウントの会話を窓口の名前（と役の起動の設定）で起動する。(終了の値, 言葉)。"""
    attrs = dept["attrs"]
    sid = attrs.get("session")
    pane = next((p["pane_id"] for p in dept["panes"] if sid and p.get("agent_session") == sid), None)
    if pane is None:
        return 1, "窓口の会話の居るペインが分からない（属性の会話 company.session の居るペインが無い）"
    try:
        held = _held(pane, ports, "窓口", f"{chat.EXIT} を打たない", attrs)
        box = None if held else chat.typed(ports.term.read(pane, 40, ansi=True))
        if box and wake.own_clear(box, attrs):
            box = deliver.wipe_box(pane, ports.term, ports.pause)   # 待ち受けが打って残った /clear の後ろに /exit を続けて打たない
        if box:   # 読み直す間に人が打ち足したか、消えなかった
            held = f"窓口の窓 {pane} の入力フィールドに字（「{box[:20]}」）が在るので{chat.EXIT} を打たない（持ち主が打ちかけの字を消さない）"
    except term.Error as e:
        return 1, f"窓口の窓 {pane} を読めない（{e}）"
    if held:
        return NOT_NOW, held
    the_role, _ = orders.shape_role(company["root"], settings, attrs.get("role"), ports.git)
    warn = None
    try:
        conf = role.write_desk_settings(ports.git.git_dir(company["root"]), the_role)
    except (gitx.GitError, OSError, TypeError) as e:
        conf, warn = None, f"役 {attrs.get('role')} の設定を書けなかったので、役の設定なしで起動した（{e}）"
    model, effort = role.desk_flags(the_role)
    if not deliver.exit_talk(pane, ports.term, ports.pause):
        return 1, f"窓口の窓 {pane} に /exit を打ったが、シェルに戻らない"
    # 前の会話は終わった。起動する値を書き（設定を書けなければ、起動した値を知らないと見る）、待ち受けと区切りの印を外す
    provision.mark(company["root"], company["root"], {wake.LAUNCHED: None if warn else role.launch_key(the_role), wake.LAUNCHING: "1",
                                                      wake.RESTARTING: None, wake.RESTART_KEPT: None, wake.REST: None, wake.MOVE_TO: None,
                                                      wake.MOVE_KEPT: None, wake.MOVE_SKIPPED: None, wake.LIMIT_HOLD: hold},
                   ports.git)
    got = launch.start_named(acc.command, pane, attrs.get("name") or "窓口", text, ports.term, settings=conf, model=model, effort=effort)
    if got["status"] == "ready":
        return 0, warn
    # 新しい会話が立たなかった: 前の会話を --resume で同じペインに戻す（窓口を消したままにしない。2026-10-17 に段取りが 22 分消えた）
    provision.mark(company["root"], company["root"], {wake.LAUNCHED: attrs.get(wake.LAUNCHED), wake.LAUNCHING: None}, ports.git)
    back = launch.bring_back(pane, f"{(old_acc or acc).command} --resume {sid}", ports.term)
    if back is None and not warn:
        # 戻した会話は前の設定のまま。同じ値で区切りのたびに起動し直しと戻しを繰り返さない（会社の形が替われば試し直す）
        provision.mark(company["root"], company["root"], {wake.RESTART_KEPT: role.launch_key(the_role)}, ports.git)
    return 1, (got["detail"] or got["status"]) + ("。前の会話を --resume で戻した" if back is None else f"。前の会話も戻せなかった（{back}）")


def _held(pane, ports, who, act, attrs):
    """窓の会話がターンの途中（herdr の状態が working か blocked）か、入力フィールドに人の打ちかけの字（薄字の候補と、待ち受けが打って
    送られずに残った /clear〔wake.own_clear。attrs は部署か窓口の属性〕は数えない）が在れば、今は止めない訳。ほかは None。
    窓を読めなければ term.Error。"""
    status = (ports.term.agent(pane) or {}).get("agent_status")
    if status in BUSY:
        return f"{who}の会話がターンの途中（{status}）なので{act}"
    box = chat.typed(ports.term.read(pane, 40, ansi=True))
    if box and not wake.own_clear(box, attrs):
        return f"{who}の窓 {pane} の入力フィールドに字（「{box[:20]}」）が在るので{act}（持ち主が打ちかけの字を消さない）"
    return None
