#!/usr/bin/env python3
"""組み直しの流れ（入口の dispatch.py --reorg・--desk）。部署の属性（正本）を付け替え、herdr の表示をその部署の分だけ付け直す。

dispatch.py の流れの続きで、ノード（nodes/provision.py の mark・nodes/sync.py）を呼ぶ順をここが持つ。ほかの部署と dispatch.py を
同時に直すので、ぶつかりを減らすために別のファイルにした（orders.py・landing.py と同じ）。

--reorg（reorg）: 今いる部署（属性 company.role の在る worktree）の名前・役・常設か都度か・頼み元を付け替える。
--desk [名前]（desk）: 本社（代表の clone）で持ち主と話す会話を窓口として名付ける。役（desk_role）・常設・名前・アカウントと会話の id と
会話の処理の番号を本社の git の設定に書く（手で書いていた company.role・company.name の正式な口）。役は --role、会社の形の頭の
desk_role、本社が今持つ役、DESK_ROLE の順に決め、名前を省けば本社が今持つ名前、無ければ役の名前。会話の処理の番号（company.pid）は、
その会話を /clear・compact・resume して会話の id が変わったときに、フックが本社の属性の id を書き直すための見分け（同じ処理の会話だけ）。

どちらも、名前を替えたら前の名前を属性 company.former-names（JSON の並び）に足す。--land・--ask は前の名前でも部署を引く
（gitx.former_names）。属性を書いた後に、その場所の分だけ --sync と同じ物（ペインの名前・表示名・題名・札と作業場の名前）を付け直す。
会話の名前（Claude Code の /rename）は外から替える口が無いので替えず、会話の中で打つ /rename を出す。
--desk は、窓口の役に起動の設定（会社の形の [roles.settings]）が有れば、代表の clone の .git の場所に書き、その設定で窓口の会話を
起こす命令（`<アカウントのコマンド> --name <窓口の名前> --settings <ファイル>`）を出す。持ち主が手で起こす窓口に設定を届ける口。
--desk を打った会話が --move の起こした会話（company.launching）なら、--move が書いた起こした値（company.launched）を残し、ほかの
新しい会話なら消す（起こした値を知らないので旗なしで起こしたと見て、会社の形と違えば区切り〔--rest〕の番の終わりに待ち受けが
起こし直す）。
"""

import json
import os

import config
import gitx
import herdr
import orders
from nodes import launch, provision, role, sync, tree, wake

DESK_ROLE = "窓口"   # 会社の形に desk_role も本社の役も無いときの、本社の会話の役（持ち主 2026-10-16）


def desk_role(shape, attrs, given):
    """--desk で書く役の名前。--role、会社の形の desk_role、本社が今持つ役（前の名前 former_names なら今の名前）、DESK_ROLE の順。"""
    return role.current(shape, given or shape.get("desk_role") or attrs.get("role") or DESK_ROLE)


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
    """同じ会社のほかの場所が同じ名前（今の名前）を持っていれば、その場所の字。宛先が 1 つに決まらなくなるので止める。ほかの会社の
    同じ名前は「会社/名前」で分けられるので止めない（--task と同じ。0.48.0）。"""
    here = os.path.realpath(gitx.common_dir(place) or place)
    for c in companies:
        if os.path.realpath(gitx.common_dir(c["root"]) or c["root"]) != here:
            continue
        for d in c["departments"]:
            if not _same(d["path"], place) and d["attrs"].get("name") == name:
                return f"{c['name']}/{d['branch'] or d['path']}"
    return None


def _resync(a, ports, place, notes):
    """その場所の分だけ、herdr の表示を属性から付け直す（--sync と同じ部品）。出す行の並び。"""
    try:
        _, accounts_, _, _, companies, _, more = orders.survey(a.config, ports)
        workspaces_ = ports.herdr.workspaces()
    except herdr.HerdrError as e:
        return [f"herdr を読めないので表示を付け直せなかった（{e}）。herdr が戻ったら --sync を打つ"]
    notes += more
    mine = [{**c, "departments": [d for d in c["departments"] if _same(d["path"], place)]} for c in companies]
    ops, why = sync.plan(mine, len(accounts_) > 1)
    ws_ops = sync.workspace_ops(mine, workspaces_)
    done = sync.apply_workspaces(ws_ops, ports.herdr) + sync.apply(ops, ports.herdr)
    lines = [sync.workspace_line(o) for o in ws_ops] + [f"ペイン {o['pane']}: 名前 {o['label'] or 'そのまま'}" for o in ops]
    out = why + [f"- {line}  {r['status']}" + (f"（{r['detail']}）" if r["detail"] else "") for line, r in zip(lines, done)]
    return out or ["herdr の表示は付け直す物が無かった"]


def _write(a, ports, place, source, before, changes, notes, head, talk_name=None, after=()):
    """属性を書き、表示を付け直して報告する。after は報告の最後に足す行。終了の値。"""
    shown = [f"- company.{k}: {before.get(k) or '-'} → {v or '（消す）'}" for k, v in changes.items() if (before.get(k) or None) != v]
    if not shown:
        print("\n".join(notes + [f"{head}: 付け替える物は無い（今の属性と同じ）"] + list(after)))
        return 0
    if a.dry_run:
        print("\n".join(notes + [f"{head}（空打ち。何も書かない）:"] + shown + list(after)))
        return 0
    try:
        provision.mark(place, source, changes, ports.git)
    except (gitx.GitError, OSError) as e:
        print("\n".join(notes + [f"止めた: 属性を書けなかった（{e}）"]))
        return 1
    out = [f"{head}:"] + shown + _resync(a, ports, place, notes)
    name = changes.get("name")
    if name and name != before.get("name") and before.get("name"):
        out.append(f"前の名前 {before.get('name')} でも --land・--ask で引ける（枝の名前でも引ける）")
    if name and name != talk_name:   # 会話の名前がもうその名前なら勧めない（claude --name 窓口 で起こした窓口など）
        out.append(f"会話の名前は dispatch からは替えられない（Claude Code に外から会話の名前を替える口が無い）。"
                   f"揃えるなら、その会話で /rename {name} を打つ")
    print("\n".join(notes + out + list(after)))
    return 0


def _launch_line(a, ports, source, shape, the_role, name, command):
    """窓口の役に起動の設定が有れば、それを代表の clone の .git の場所に書き（空打ちでは書かない）、その設定で窓口を起こす命令の行。"""
    got = shape["roles"].get(the_role)
    if not (got and got.get("settings")):
        return []
    posix = os.name != "nt"
    try:
        folder = ports.git.git_dir(source)
        path = os.path.join(folder, role.SETTINGS_FILE)
        if not a.dry_run:
            role.write_desk_settings(folder, got)
    except (gitx.GitError, OSError, TypeError) as e:
        return [f"窓口の役 {the_role} の起動の設定（[roles.settings]）を書けなかった（{e}）。窓口の会話は役の設定なしで起きる"]
    return [f"窓口の役 {the_role} に起動の設定（会社の形の [roles.settings]）が有る"
            + ("（空打ちなので書いていない）" if a.dry_run else f"ので {path} に書いた")
            + "。窓口の会話を手で起こすときは、次の命令で起こす（--move はこの設定で起こす）: "
            f"{command} --name {launch._quote(name, posix)} "
            + "".join(f"--{k} {launch._quote(v, posix)} " for k, v in zip(("model", "effort"), role.desk_flags(got)) if v)
            + f"--settings {launch._quote(path, posix)}",
            "この会話を --move が起こしたのでなければ、起こした設定を機械は知らないので、この会話が区切り（--rest）を印した番の"
            "終わりに、待ち受けがこの設定で起こし直す（持ち主の手は要らない。会社の形の設定を替えたときも同じ）"]


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
    the_role = role.current(shape, attrs["role"])
    if a.role:
        got, why = role.pick(shape, a.role, True)
        if why:
            print(f"止めた: {why}")
            return 2
        the_role = role.current(shape, a.role)
    else:
        got = shape["roles"].get(the_role)
    changes = {}
    if a.role:
        changes["role"] = the_role
    if a.resident or a.per_task:
        changes["residency"] = "resident" if a.resident else "per-task"
    elif a.role and got and got["resident"]:
        changes["residency"] = "resident"   # 役の resident = true は --resident と同じ（--task と揃える）
    if a.role and got:
        changes["fresh"] = role.FRESH if got["fresh"] else None   # 役の fresh を写す（--task と揃える）
    if a.name:
        try:
            _, _, sessions_, _, companies, _, _ = orders.survey(a.config, ports)
        except herdr.HerdrError:
            sessions_, companies = {}, []   # 名前のぶつかりを確かめられないだけ（属性は書ける）
        talk_name = ports.caller(sessions_)[1]
        clash = _clash(companies, cwd, a.name)
        if clash:
            print(f"止めた: 「{a.name}」という名前の部署がもう在る（{clash}）。宛先が 1 つに決まらないので、別の名前にする")
            return 2
        changes["name"] = a.name
        former = _renamed(attrs, a.name)
        if former:
            changes["former-names"] = former
    if a.boss:
        # 頼み元を替えたら、前の頼み元の会話の id とペインは消す（納品は新しい頼み元を名前で引く）。受付箱は残す
        changes.update({"boss": a.boss, "boss-account": a.boss_account, "boss-session": None, "boss-pane": None})
    head = f"部署 {attrs.get('name') or cwd}（役 {the_role}）を組み直す"
    return _write(a, ports, cwd, source, attrs, changes, notes, head, talk_name if a.name else None)


def desk(a, ports, cwd):
    """--desk [名前]。本社で持ち主と話す会話を窓口として名付ける。終了の値。"""
    common = ports.git.common_dir(cwd)
    if not common:
        print(f"止めた: {cwd} が git でない（窓口は会社の代表の clone で開く）")
        return 2
    source = gitx.root_of(common)
    attrs = ports.attrs(cwd)
    shape, notes = _shape(source, a)
    notes += shape["problems"]
    linked = ports.git.is_main_worktree(cwd) is False   # 部署の worktree（部署の役を窓口の役の候補にしない）
    the_role = desk_role(shape, {} if linked else attrs, a.role)
    if linked and attrs.get("role") and role.current(shape, attrs["role"]) != the_role:
        print(f"止めた: {cwd} は部署（役 {attrs['role']}）。部署の名前と役は --reorg で付け替える")
        return 2
    name = (a.desk or "").strip() or attrs.get("name") or the_role
    if a.role:
        _, why = role.pick(shape, a.role, True)
        if why:
            print(f"止めた: {why}")
            return 2
    elif shape["roles"] and the_role not in shape["roles"]:
        notes.append(f"会社の形に役 {the_role} が無いので、窓口の会話に足す役の本文は無い（要るなら会社の形の頭に "
                     f"desk_role = \"<役>\" を書くか、--role で名指す。在る役: {', '.join(shape['roles'])}）")
    try:
        cfg, _, sessions_, _, companies, _, more = orders.survey(a.config, ports)
    except herdr.HerdrError as e:
        cfg, sessions_, companies, more = None, {}, [], [f"herdr を読めないので、名前のぶつかりと会話のアカウントを確かめられない（{e}）"]
    notes += more
    clash = _clash(companies, cwd, name)
    if clash:
        print("\n".join(notes + [f"止めた: 「{name}」という名前の部署がもう在る（{clash}）。別の名前にする"]))
        return 2
    account, talk_name = ports.caller(sessions_)
    session = ports.env.get("CLAUDE_CODE_SESSION_ID")
    if not account:
        notes.append("この命令を打った会話が会話の一覧に見えないので、アカウントと会話の id は今の値のまま"
                     "（窓口の会話の中から打てば書く）")
    changes = {"role": the_role, "residency": "resident", "name": name}
    if account:
        pid = ports.caller_pid(sessions_)
        held = attrs.get("pid")
        if not linked and held and held != str(pid) and session != attrs.get("session") and ports.running_claude(held):
            # 窓口の席は 1 つ。窓口の会話が動いている間に、ほかの会話（試しの claude -p など）が席を取ると、納品がそちらに届き、
            # 同じ役の会話が 2 つ動く（53d5d1・6be241）
            print("\n".join(notes + [f"止めた: 窓口 {attrs.get('name') or '-'} の会話（処理 {held}、会話 {attrs.get('session') or '-'}）"
                                     "がまだ動いている。席を移すなら、先にその会話を終える（/exit）"]))
            return 2
        changes.update({"account": account, "session": session, "pid": str(pid) if pid else None})
        if session != attrs.get("session"):
            changes.update({wake.LAUNCHING: None, **({} if attrs.get(wake.LAUNCHING) else {wake.LAUNCHED: None})})
    former = _renamed(attrs, name)
    if former:
        changes["former-names"] = former
    held_by = account or attrs.get("account")
    command = next((x.command for x in (cfg.accounts if cfg else []) if x.name == held_by), "claude")
    after = _launch_line(a, ports, source, shape, the_role, name, command)
    return _write(a, ports, cwd, source, attrs, changes, notes, f"窓口 {name}（{source}）を名付ける", talk_name, after)
