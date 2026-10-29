#!/usr/bin/env python3
"""リマインダーの流れ（入口の dispatch.py から呼ぶ）。射影と見る時の判じは nodes/remind、形と決めた事は docs/ledger.md の「リマインダー」。

--remind <何を見るか> --on <日時> / --after <受付>（put）: 打った部署か窓口を担当者に、見る日か、閉じるのを待つ頼み（どちらか先に
  来た方で見る時が来る）を台帳に kind remind の行で残す。条件を文でしか書けない待ち（「次に X が起きたら」）は、見直す日を --on に付ける。
--remind-done <受付>（close）: 見たリマインダーを閉じる（kind remind-done）。
--due の中（notify）: 見る時が来て、まだ知らせていないリマインダーを、担当者の待ち受けへ台帳の知らせ（kind note）で 1 度だけ渡し、
  kind reminded の行で知らせたと残す。担当者の部署が立っていなければ（畳まれた tmp の部署など。知らせを拾う待ち受けが無い）、
  知らせの代わりに --ask と同じ道で頼む（route と asker）。--due は頼みと納品のたびに裏で走る（starts.due_later）。--todo は見る時の来た物を出す。
"""

import argparse
import os

import config
import gitx
import orders
import todo
from ports import chat
from nodes import deliver, ledger, wake
from nodes import remind


def _resolve(tasks, short):
    hits = [i for i in tasks if i == short or i.endswith("-" + short)]
    return hits[0] if len(hits) == 1 else None, len(hits)


def put(a, ports, cwd):
    """--remind。終了の値を返す。"""
    text = " ".join((a.remind or "").split())
    if not text:
        print("止めた: 何を見るかを --remind に書く")
        return 2
    if a.on is None and not a.after:
        print("止めた: 見る日（--on <YYYY-MM-DD か YYYY-MM-DDTHH:MM>）か、閉じるのを待つ頼み（--after <受付>）を付ける。"
              "条件を文でしか書けない待ち（「次に X が起きたら」）は、見直す日を --on に付ける")
        return 2
    on = None
    if a.on is not None:
        on = remind.parse_on(a.on)
        if on is None:
            print(f"止めた: --on {a.on} を日時に読めない（手元の時刻の YYYY-MM-DD か YYYY-MM-DDTHH:MM）")
            return 2
    common = ports.git.common_dir(cwd)
    if not common:
        print(f"止めた: {cwd} が git でないので、受付箱が決まらない（会社の部署か窓口の場所から打つ）")
        return 2
    sid = chat.session_of(ports.env)
    name = orders.place_name(cwd, sid, ports)
    if not name:
        print("止めた: 知らせを受けられるのは名前の有る部署か窓口の会話だけ（待ち受けはそこにだけ張られる）。部署か窓口の場所から打つ")
        return 2
    inbox = deliver.inbox_of(common)
    after = []
    if a.after:
        _, rows = todo.inboxes_from([inbox], ports.git.common_dir)
        tasks = ledger.build(rows)["tasks"]
        for short in a.after:
            got, n = _resolve(tasks, short)
            if got is None:
                print(f"止めた: 受付 {short} が台帳に" + ("無い" if not n else f" {n} 件ある（長い受付番号で渡す）"))
                return 2
            if tasks[got]["state"] in remind.CLOSED:
                print(f"止めた: 受付 {got} はもう閉じている（{tasks[got]['label']}）。今見る")
                return 2
            after.append(got)
    # 会社の名前は待ち受けと同じ読み方で決める（wake_hook.plan。設定の置き場の会社の形も読む。違えば知らせが届かない）
    settings = os.path.dirname(config.path_of(ports.attrs(cwd).get("config"), ports.env))
    holder = wake.address(orders.inbox_company(inbox, settings, ports.git), name)
    rid = deliver.new_id(ports.now())
    waits = remind.waits_for({"on": on, "after": after})
    if a.dry_run:
        print(f"リマインダーを立てる: {text}（{waits}）。担当者 {holder}")
        return 0
    deliver.log(inbox, {"id": rid, "kind": remind.REMIND, "at": ports.now(), "text": text, "holder": holder, "on": on, "after": after,
                        "from": {"name": name, "session": sid, "place": cwd}})
    print(f"リマインダーを立てた: 受付 {rid}（{waits}）。見る時が来たら、頼みか納品の後に裏で走る --due が {holder} の待ち受けに"
          f"知らせる（--todo にも出る）。見たら --remind-done {rid} で閉じる")
    return 0


def close(a, ports, cwd):
    """--remind-done <受付>。終了の値を返す。"""
    common = ports.git.common_dir(cwd)
    if not common:
        print(f"止めた: {cwd} が git でないので、受付箱が決まらない（会社の部署か窓口の場所から打つ）")
        return 2
    inboxes, _ = todo.inboxes_from([deliver.inbox_of(common)], ports.git.common_dir)
    for inbox in inboxes:
        rems = remind.project(deliver.records(inbox))
        got, n = _resolve(rems, a.remind_done)
        if n > 1:
            print(f"止めた: 受付 {a.remind_done} のリマインダーが {n} 件ある（長い受付番号で渡す）")
            return 2
        if got is None:
            continue
        if rems[got]["closed"]:
            print(f"受付 {got} のリマインダーはもう閉じている")
            return 0
        if a.dry_run:
            print(f"受付 {got} のリマインダーを閉じる: {rems[got]['text']}")
            return 0
        deliver.log(inbox, {"id": got, "kind": remind.REMIND_DONE, "at": ports.now(),
                            "by": {"session": chat.session_of(ports.env), "place": cwd}})
        print(f"受付 {got} のリマインダーを閉じた: {rems[got]['text']}")
        return 0
    print(f"止めた: 受付 {a.remind_done} のリマインダーが、打った場所の会社とたどれる会社の台帳に無い")
    return 2


def due(rems, tasks, now):
    """開いていて、見る時が来た (リマインダー, 訳) の並び（知らせたかは問わない。--todo が出す）。"""
    return [(r, why) for r in rems.values() for why in [remind.came(r, tasks, now)] if why]


def route(holder, companies, here_root, current):
    """担当者 holder（「会社/名前」）に届ける道。None なら担当者の名前の部署か窓口が立っているので、今までどおり担当者の待ち受けへ
    台帳の知らせで渡す。立っていなければ (宛先, 訳, 宛先の会社)。宛先は次の順で決める。
    - 担当者の名前が会社の形の on-demand の受け持ち（頼まれたときだけ部署を立てる受け持ち）なら、その受け持ち。--ask と同じく、
      受け持ちの名前の部署が立つ。
    - 担当者の名前が役で、その役の keep の部署が別の名前で立っているなら、その部署。
    - それ以外（頼みごとに立てる部署・作業など、名前で立て直せない部署）は、担当者の会社の窓口。
    担当者の会社が端末に開いていないなどで宛先が決まらなければ None（知らせだけ書く）。"""
    company, _, name = holder.rpartition("/")
    try:
        got = deliver.find_target(companies, here_root, holder, None, current)
    except deliver.DeliverError:
        return None
    d = got.get("department")
    if d is not None:
        now = d["attrs"].get("name")
        if now == name or name in gitx.former_names(d["attrs"]):
            return None
        return f"{company}/{now}", f"担当者 {holder} の名前の部署が無く、同じ役の部署 {now} が立っているので、そこに頼む", got["company"]
    if got.get("on_demand") and not got.get("per_ask"):
        return holder, f"担当者の部署が立っていないので、on-demand の受け持ち {name} に頼んで部署を立てる", got["company"]
    try:
        desk = deliver.find_target(companies, here_root, company, None, current)
    except deliver.DeliverError:
        return None
    return company, f"担当者 {holder} の部署が立っておらず、名前で立て直せないので、会社 {company} の窓口に頼む", desk["company"]


def boss_of(company, companies, here_root, current, git):
    """リマインダーの頼みの頼み元の属性（担当者の会社 company の窓口）か None（窓口が決まらない）。頼み元の名前の待ち受けが納品を
    受ける（starts._boss と同じく、会話の id は持たない）。"""
    try:
        got = deliver.find_target(companies, here_root, company, None, current)
    except deliver.DeliverError:
        return None
    common = git.common_dir(got["company"]["root"])
    if not common or not got["department"]["attrs"].get("name"):
        return None
    return {"boss": got["department"]["attrs"]["name"], "boss-account": None, "boss-session": None, "boss-pane": None,
            "boss-inbox": deliver.inbox_of(common)}


def asked(company, ask_id, git):
    """受付 ask_id の頼みが company の台帳で届いたか（sent）か積まれた（queued）か。orders.ask は、頼みが部署に届いた後に立てる道が
    0 以外を返しても、その値を返すので、終了の値でなく台帳で見る。"""
    common = git.common_dir(company["root"])
    if not common:
        return False
    return any(r.get("id") == ask_id and r.get("kind") == "ask" and r.get("status") in ("sent", "queued")
               for r in deliver.records(deliver.inbox_of(common)))


def asker(company, companies, settings, ports, a, task):
    """notify に渡す、担当者の部署が立っていないリマインダーを頼みにする関数。(r, 知らせの文, 試し打ちか) → (出す行, 頼みの受付か None)
    か None（担当者の部署が立っているか、宛先か頼み元が決まらないので、知らせで渡す）。頼みは --due の外から打った形で、starts.fire と
    同じく orders.ask に渡す。頼み元は担当者の会社の窓口で、納品は窓口の待ち受けに届く。頼みが通らなければ (出す行, None) を返し、
    reminded の行を書かずに次の --due で頼み直す。"""
    current = orders.current_role(settings, ports.git)

    def reach(r, line, dry_run):
        how = route(r["holder"], companies, company["root"], current)
        if how is None:
            return None
        to, why, there = how
        boss = boss_of(r["holder"].rpartition("/")[0], companies, company["root"], current, ports.git)
        if boss is None:
            return None
        if dry_run:
            return f"頼む: リマインダー 受付 {r['id']} を {to} に（{why}）", None
        ask_id = deliver.new_id(ports.now())
        ns = argparse.Namespace(**{**vars(a), "ask": to, "text": line, "brief": None, "task": None, "branch": None, "role": None,
                                   "persistent": False, "ask_id": ask_id, "forward": False, "title": f"リマインダー（受付 {r['id']}）",
                                   "from_boss": boss})
        rc = orders.ask(ns, ports, company["root"], task)
        if rc != 0 and not asked(there, ask_id, ports.git):
            return f"頼めなかった: リマインダー 受付 {r['id']} を {to} に（終了の値 {rc}。次の --due で頼み直す）", None
        return f"頼んだ: リマインダー 受付 {r['id']} を {to} に 受付 {ask_id}（{why}）", ask_id
    return reach


def notify(inbox, common_dir, now, dry_run=False, reach=None):
    """--due の中で、その会社の受付箱のリマインダーのうち、見る時が来てまだ知らせていない物を、担当者の待ち受けへ台帳の知らせで渡す。
    知らせの行そのものが知らせた印で（remind.project）、2 度は知らせない（RFC 9074 の VALARM の ACKNOWLEDGED と同じく、受けたかを
    返さない知らせは送った時に印す）。続けて kind reminded の行に来た訳を残す。reach（asker の返す関数）が頼みにした物は、知らせの
    行を書かず、reminded の行に頼みの受付（child）を残す。頼みが通らなかった物は reminded を書かず、次の --due で頼み直す。dry_run なら書かずに、知らせる物を言うだけ。出す行の並びを返す。"""
    rems = {i: r for i, r in remind.project(deliver.records(inbox)).items() if not r["closed"] and not r["reminded"]}
    if not rems:
        return []
    tasks = {}
    if any(r["after"] for r in rems.values()):
        _, rows = todo.inboxes_from([inbox], common_dir)
        tasks = ledger.build(rows)["tasks"]
    out = []
    for r, why in due(rems, tasks, now):
        if not r["holder"]:
            continue
        line = (f"リマインダーです（受付 {r['id']}。{why}）: {r['text']}。見たら {orders.RUN} --remind-done {r['id']} で閉じる"
                "（まだ早ければ閉じて、見る日を替えて --remind で立て直す）")
        asked = reach(r, line, dry_run) if reach else None
        if asked:
            said, child = asked
            out.append(said)
            if child:
                deliver.log(inbox, {"id": r["id"], "kind": remind.REMINDED, "at": now, "why": why, "child": child})
            continue
        if dry_run:
            out.append(f"知らせる: リマインダー 受付 {r['id']}（{why}）を {r['holder']} に")
            continue
        deliver.log(inbox, wake.notice(r["holder"], r["id"], wake.NOTE, None, line, now))
        deliver.log(inbox, {"id": r["id"], "kind": remind.REMINDED, "at": now, "why": why})
        out.append(f"知らせた: リマインダー 受付 {r['id']}（{why}）を {r['holder']} に")
    return out
