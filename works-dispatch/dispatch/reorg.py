#!/usr/bin/env python3
"""組み直しの流れ（入口の dispatch.py --reorg・--desk）。部署の属性（正本）を付け替え、herdr の表示をその部署の分だけ付け直す。

dispatch.py の流れの続きで、ノード（nodes/provision.py の mark・nodes/sync.py）を呼ぶ順をここが持つ。ほかの部署と dispatch.py を
同時に直すので、ぶつかりを減らすために別のファイルにした（orders.py・landing.py と同じ）。

--reorg（reorg）: 今いる部署（属性 company.role の在る worktree）の名前・役・常駐か都度か・上役を付け替える。
--desk [名前]（desk）: 本社（代表の clone）で持ち主と話す会話を窓口として名付ける（名前を省けば DESK_ROLE）。役 DESK_ROLE・常駐・名前・アカウントと会話の id を
本社の git の設定に書く（手で書いていた company.role・company.name の正式な口）。

どちらも、名前を替えたら前の名前を属性 company.former-names（JSON の並び）に足す。--land・--ask は前の名前でも部署を引く
（gitx.former_names）。属性を書いた後に、その場所の分だけ --sync と同じ物（ペインの名前・表示名・題名・札と作業場の名前）を付け直す。
会話の名前（Claude Code の /rename）は外から替える口が無いので替えず、会話の中で打つ /rename を出す。
"""

import json
import os

import config
import gitx
import herdr
import orders
from nodes import provision, role, sync, tree

DESK_ROLE = "窓口"   # 持ち主と話して頼みを配る本社の会話の役（持ち主 2026-10-16）


def _same(a, b):
    return os.path.realpath(a) == os.path.realpath(b)


def _renamed(attrs, new_name):
    """名前を替えるときに書く former-names の値（JSON の並び。前の名前を足し、新しい名前は外す）。替えないなら None。"""
    old = attrs.get("name")
    if not new_name or new_name == old:
        return None
    names = [n for n in gitx.former_names(attrs) + ([old] if old else []) if n != new_name]
    return json.dumps(list(dict.fromkeys(names)), ensure_ascii=False)


def _clash(companies, place, name):
    """ほかの場所が同じ名前（今の名前）を持っていれば、その場所の字。宛先が 1 つに決まらなくなるので止める。"""
    for c in companies:
        for d in c["departments"]:
            if not _same(d["path"], place) and d["attrs"].get("name") == name:
                return f"{c['name']}/{d['branch'] or d['path']}"
    return None


def _resync(a, ports, place, notes):
    """その場所の分だけ、herdr の表示を属性から付け直す（--sync と同じ部品）。出す行の並び。"""
    try:
        _, accounts_, _, _, companies, _, more = orders.survey(a.config, ports)
        labels = {w["workspace_id"]: w.get("label") for w in ports.herdr.workspaces()}
    except herdr.HerdrError as e:
        return [f"herdr を読めないので表示を付け直せなかった（{e}）。herdr が戻ったら --sync を打つ"]
    notes += more
    mine = [{**c, "departments": [d for d in c["departments"] if _same(d["path"], place)]} for c in companies]
    ops, why = sync.plan(mine, len(accounts_) > 1)
    ws_ops = sync.workspace_ops(mine, labels)
    done = sync.apply_workspaces(ws_ops, ports.herdr) + sync.apply(ops, ports.herdr)
    lines = [f"作業場 {o['workspace']}: 名前 {o['label']}" for o in ws_ops] + [f"ペイン {o['pane']}: 名前 {o['label'] or 'そのまま'}"
                                                                              for o in ops]
    out = why + [f"- {line}  {r['status']}" + (f"（{r['detail']}）" if r["detail"] else "") for line, r in zip(lines, done)]
    return out or ["herdr の表示は付け直す物が無かった"]


def _write(a, ports, place, source, before, changes, notes, head):
    """属性を書き、表示を付け直して報告する。終了の値。"""
    shown = [f"- company.{k}: {before.get(k) or '-'} → {v or '（消す）'}" for k, v in changes.items() if (before.get(k) or None) != v]
    if not shown:
        print("\n".join(notes + [f"{head}: 付け替える物は無い（今の属性と同じ）"]))
        return 0
    if a.dry_run:
        print("\n".join(notes + [f"{head}（空打ち。何も書かない）:"] + shown))
        return 0
    try:
        provision.mark(place, source, changes, ports.git)
    except (gitx.GitError, OSError) as e:
        print("\n".join(notes + [f"止めた: 属性を書けなかった（{e}）"]))
        return 1
    out = [f"{head}:"] + shown + _resync(a, ports, place, notes)
    name = changes.get("name")
    if name and name != before.get("name"):
        out.append(f"前の名前 {before.get('name') or '-'} でも --land・--ask で引ける（枝の名前でも引ける）")
        out.append(f"会話の名前は dispatch からは替えられない（Claude Code に外から会話の名前を替える口が無い）。"
                   f"揃えるなら、その会話で /rename {name} を打つ")
    print("\n".join(notes + out))
    return 0


def _shape(source, a):
    info = tree.read_info(source, os.path.dirname(config.path_of(a.config, os.environ)))
    return role.load(info["path"], info["text"]), info["notes"]


def reorg(a, ports, cwd):
    """--reorg。今いる部署の属性を付け替える。終了の値（2 は使い方の誤りか部署でない）。"""
    if a.resident and a.per_task:
        print("止めた: --resident と --per-task は一緒に使えない")
        return 2
    if not any([a.name, a.role, a.resident, a.per_task, a.boss]):
        print("止めた: --reorg には、替える物（--name・--role・--resident か --per-task・--boss）を 1 つ以上渡す")
        return 2
    attrs = ports.attrs(cwd)
    common = ports.git.common_dir(cwd)
    if not attrs.get("role") or not common:
        print(f"止めた: {cwd} は部署でない（git の設定 company.role が無い）。部署の場所から打つ"
              f"（本社の会話を窓口として名付けるなら --desk）")
        return 2
    source = gitx.root_of(common)
    shape, notes = _shape(source, a)
    notes += shape["problems"]
    the_role = attrs["role"]
    if a.role:
        got, why = role.pick(shape, a.role, True)
        if why:
            print(f"止めた: {why}")
            return 2
        the_role = a.role
    else:
        got = shape["roles"].get(the_role)
    changes = {}
    if a.role:
        changes["role"] = a.role
    if a.resident or a.per_task:
        changes["residency"] = "resident" if a.resident else "per-task"
    elif a.role and got and got["resident"]:
        changes["residency"] = "resident"   # 役の resident = true は --resident と同じ（--task と揃える）
    if a.name:
        try:
            _, _, _, _, companies, _, _ = orders.survey(a.config, ports)
        except herdr.HerdrError:
            companies = []   # 名前のぶつかりを確かめられないだけ（属性は書ける）
        clash = _clash(companies, cwd, a.name)
        if clash:
            print(f"止めた: 「{a.name}」という名前の部署がもう在る（{clash}）。宛先が 1 つに決まらないので、別の名前にする")
            return 2
        changes["name"] = a.name
        former = _renamed(attrs, a.name)
        if former:
            changes["former-names"] = former
    if a.boss:
        # 上役を替えたら、前の上役の会話の id とペインは消す（納品は新しい上役を名前で引く）。受付箱は残す
        changes.update({"boss": a.boss, "boss-account": a.boss_account, "boss-session": None, "boss-pane": None})
    head = f"部署 {attrs.get('name') or cwd}（役 {the_role}）を組み直す"
    return _write(a, ports, cwd, source, attrs, changes, notes, head)


def desk(a, ports, cwd):
    """--desk [名前]。本社で持ち主と話す会話を窓口として名付ける。終了の値。"""
    name = (a.desk or "").strip() or DESK_ROLE
    common = ports.git.common_dir(cwd)
    if not common:
        print(f"止めた: {cwd} が git でない（窓口は会社の代表の clone で開く）")
        return 2
    source = gitx.root_of(common)
    attrs = ports.attrs(cwd)
    if ports.git.is_main_worktree(cwd) is False and attrs.get("role") and attrs["role"] != (a.role or DESK_ROLE):
        print(f"止めた: {cwd} は部署（役 {attrs['role']}）。部署の名前と役は --reorg で付け替える")
        return 2
    shape, notes = _shape(source, a)
    notes += shape["problems"]
    the_role = a.role or DESK_ROLE
    if a.role:
        _, why = role.pick(shape, a.role, True)
        if why:
            print(f"止めた: {why}")
            return 2
    elif shape["roles"] and DESK_ROLE not in shape["roles"]:
        notes.append(f"会社の形に役 {DESK_ROLE} が無いので、窓口の会話に足す役の本文は無い（要るなら [[roles]] に {DESK_ROLE} を"
                     "書けば、次の会話の始まりから足される）")
    try:
        _, _, sessions_, _, companies, _, more = orders.survey(a.config, ports)
    except herdr.HerdrError as e:
        sessions_, companies, more = {}, [], [f"herdr を読めないので、名前のぶつかりと会話のアカウントを確かめられない（{e}）"]
    notes += more
    clash = _clash(companies, cwd, name)
    if clash:
        print("\n".join(notes + [f"止めた: 「{name}」という名前の部署がもう在る（{clash}）。別の名前にする"]))
        return 2
    account, _ = ports.caller(sessions_)
    session = ports.env.get("CLAUDE_CODE_SESSION_ID")
    if not account:
        notes.append("この命令を打った会話が会話の一覧に見えないので、アカウントと会話の id は今の値のまま"
                     "（窓口の会話の中から打てば書く）")
    changes = {"role": the_role, "residency": "resident", "name": name}
    if account:
        changes.update({"account": account, "session": session})
    former = _renamed(attrs, name)
    if former:
        changes["former-names"] = former
    return _write(a, ports, cwd, source, attrs, changes, notes, f"窓口 {name}（{source}）を名付ける")
