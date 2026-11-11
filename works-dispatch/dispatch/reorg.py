#!/usr/bin/env python3
"""組み直しの流れ（入口の dispatch.py --reorg・--desk）。部署の属性（正本）を付け替え、herdr の表示をその部署の分だけ付け直す。

dispatch.py の流れの続きで、ノード（nodes/provision.py の mark・nodes/sync.py）を呼ぶ順をここが持つ。ほかの部署と dispatch.py を
同時に直すので、ぶつかりを減らすために別のファイルにした（orders.py・landing.py と同じ）。

--reorg（reorg）: 今いる部署（属性 company.role の在る worktree）の名前・役・always か tmp か・頼み元を付け替える。
--desk [名前]（desk）: 本社（代表の clone）で持ち主と話す会話を窓口として名付ける。役（desk_role）・always・名前・アカウントと会話の id と
会話の処理の番号を本社の git の設定に書く（手で書いていた company.role・company.name の正式な口）。役は --role、会社の形の頭の
desk_role、本社が今持つ役、DESK_ROLE の順に決め、名前を省けば本社が今持つ名前、無ければ役の名前。会話の処理の番号（company.pid）は、
その会話を /clear・compact・resume して会話の id が変わったときに、フックが本社の属性の id を書き直すための見分け（同じ処理の会話だけ）。

どちらも、名前を替えたら前の名前を属性 company.former-names（JSON の並び）に足す。--land・--ask は前の名前でも部署を引く
（gitx.former_names）。属性を書いた後に、その場所の分だけ --sync と同じ物（ペインの名前・表示名・題名・札と作業場の名前）を付け直す。
会話の名前（Claude Code の /rename）は外から替える口が無いので替えず、会話の中で打つ /rename を出す。
--desk は、窓口の役に起動の設定（会社の形の [roles.settings]）が有れば、代表の clone の .git の場所に書き、その設定で窓口の会話を
起動するコマンド（`<アカウントのコマンド> --name <窓口の名前> --settings <ファイル>`）を出す。持ち主が手で起動する窓口に設定を届ける口。
--desk を打った会話が --move の起動した会話（company.launching）なら、--move が書いた起動した値（company.launched）を残し、ほかの
新しい会話なら消す（起動した値を知らないので旗なしで起動したと見て、会社の形と違えば区切り〔--rest〕のターンの終わりに待ち受けが
起動し直す）。
"""

import json
import os

import config
import gitx
from ports import chat, term
import orders
from nodes import deliver, launch, provision, role, sync, tree, wake

DESK_ROLE = "窓口"   # 会社の形に desk_role も本社の役も無いときの、本社の会話の役（持ち主 2026-10-16）


def desk_role(shape, attrs, given):
    """--desk で書く役の名前。--role、会社の形の desk_role、本社が今持つ役（前の名前 former_names なら今の名前）、DESK_ROLE の順。"""
    return role.current(shape, given or shape.get("desk_role") or attrs.get("role") or DESK_ROLE)


def _same(a, b):
    return os.path.realpath(a) == os.path.realpath(b)


def _renamed(attrs, new_name, also=()):
    """名前を替えるときに書く former-names の値（JSON の並び。前の名前と also の名前を足し、新しい名前は外す）。足す物が無ければ None。
    今の値が読めなければ gitx.AttrError（読めないまま空として上書きすると、前の名前で宛てた頼みが届かなくなる）。"""
    old = attrs.get("name")
    if (not new_name or new_name == old) and not any(also):
        return None   # 足す物が無いときは前の名前を読まない（読めない値でも、名前を替えない --desk・--reorg を止めない）
    held = gitx.former_names(attrs, strict=True)
    extra = [n for n in also if n and n not in (new_name, old) and n not in held]
    if (not new_name or new_name == old) and not extra:
        return None
    names = [n for n in held + ([old] if old else []) + extra if n != new_name]
    return json.dumps(list(dict.fromkeys(names)), ensure_ascii=False)


def _asked_as(ports, common, talk_name):
    """本社の会話が名付く前に、会話の一覧の名前 talk_name で頼み元を書いた頼みが受付箱の台帳に在れば [talk_name]、無ければ []。
    名付けるときにその名前を前の名前（company.former-names）に足し、その頼みの納品も窓口の待ち受けに届ける（my_notes の本社が
    名付かないまま my-notes-7b で 2 つ頼み、司令塔が手で前の名前を足した。受付 20261111-024844-09198b・20261111-024957-027a84）。
    見るのは本社（git の場所が共通の場所と同じ。_at_office）から頼んだ行だけで、本社の下に置いた部署の作業場の行は見ない。"""
    if not talk_name:
        return []
    for r in deliver.records(deliver.inbox_of(common)):
        got = r.get("from") if r.get("kind") == "ask" else None
        place = isinstance(got, dict) and got.get("name") == talk_name and got.get("place")
        if isinstance(place, str) and _at_office(ports, place, common):
            return [talk_name]
    return []


def _seat_changes(attrs, shape, cfg, source, ports, the_role, name, account, session, pid, talk_name):
    """本社の属性に窓口として書く物（--desk と、--ask の名付け auto_desk で同じ）と、書く gh のアカウントか None の対。account が
    無ければ（会話の一覧に見えない）アカウントと会話の id は今の値のまま。前の名前が読めなければ gitx.AttrError。"""
    changes = {"role": the_role, "lifecycle": gitx.PERSISTENT, "name": name}
    # 本社の会話の gh のアカウント（role_hook.put_env が GH_TOKEN に入れる）。--task と同じ決め方（設定の [[repos]] の gh_user を先に、
    # 無ければ会社の形の gh_user）。無ければ今の値のまま（手で書いた物を消さない）。頼み 4a8deb
    gh_user = role.gh_user(config.repo_at(cfg, source, ports.origin).gh_user if cfg else None, shape)[0]
    if gh_user:
        changes["gh-user"] = gh_user
    if account:
        changes.update({"account": account, "session": session, "pid": str(pid) if pid else None})
        if session != attrs.get("session"):
            changes.update({wake.LAUNCHING: None, **({} if attrs.get(wake.LAUNCHING) else {wake.LAUNCHED: None})})
    common = ports.git.common_dir(source)
    former = _renamed(attrs, name, _asked_as(ports, common, talk_name) if common and talk_name != name else ())
    if former:
        changes["former-names"] = former
    return changes, gh_user


def _clash(companies, place, name, g):
    """同じ会社のほかの場所が同じ名前（今の名前か、--handover で継いだ名前）を持っていれば、その場所の字。宛先が 1 つに決まらなくなるので
    止める（継いだ名前を本社の --desk が名乗ると、前の名前で宛てた頼みと納品の返し先が、継いだ部署でなく本社に当たる）。ほかの会社の
    同じ名前は「会社/名前」で分けられるので止めない（--task と同じ。0.48.0）。"""
    here = os.path.realpath(g.common_dir(place) or place)
    for c in companies:
        if os.path.realpath(g.common_dir(c["root"]) or c["root"]) != here:
            continue
        for d in c["departments"]:
            if not _same(d["path"], place) and (d["attrs"].get("name") == name or name in gitx.inherited_names(d["attrs"])):
                return f"{c['name']}/{d['branch'] or d['path']}"
    return None


def _resync(a, ports, place, notes):
    """その場所の分だけ、herdr の表示を属性から付け直す（--sync と同じ部品）。出す行の並び。"""
    try:
        _, accounts_, _, _, companies, _, more = orders.survey(a.config, ports)
        workspaces_ = ports.term.workspaces()
    except term.Error as e:
        return [f"{term.NAME} を読めないので表示を付け直せなかった（{e}）。{term.NAME} が戻ったら --sync を打つ"]
    notes += more
    mine = [{**c, "departments": [d for d in c["departments"] if _same(d["path"], place)]} for c in companies]
    ops, why = sync.plan(mine, len(accounts_) > 1)
    ws_ops = sync.workspace_ops(mine, workspaces_)
    done = sync.apply_workspaces(ws_ops, ports.term) + sync.apply(ops, ports.term)
    lines = [sync.workspace_line(o) for o in ws_ops] + [f"ペイン {o['pane']}: 名前 {o['label'] or 'そのまま'}" for o in ops]
    out = why + [f"- {line}  {r['status']}" + (f"（{r['detail']}）" if r["detail"] else "") for line, r in zip(lines, done)]
    return out or [f"{term.NAME} の表示は付け直す物が無かった"]


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
        out.append(f"前の名前 {before.get('name')} でも --land・--ask で引ける（ブランチの名前でも引ける）")
    if name and name != talk_name:   # 会話の名前がもうその名前なら勧めない（claude --name 窓口 で起動した窓口など）
        out.append(f"会話の名前は dispatch からは替えられない（{chat.NAME} に外から会話の名前を替える口が無い）。"
                   f"揃えるなら、その会話で /rename {name} を打つ")
    print("\n".join(notes + out + list(after)))
    return 0


def _launch_line(a, ports, source, shape, the_role, name, command):
    """窓口の役に起動の設定が有れば、それを代表の clone の .git の場所に書き（空打ちでは書かない）、その設定で窓口を起動するコマンドの行。"""
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
            + "。窓口の会話を手で起動するときは、次のコマンドで起動する（--move はこの設定で起動する）: "
            f"{command} --name {launch._quote(name, posix)} "
            + "".join(f"--{k} {launch._quote(v, posix)} " for k, v in zip(("model", "effort"), role.desk_flags(got)) if v)
            + f"--settings {launch._quote(path, posix)}",
            "この会話を --move が起動したのでなければ、起動した設定を機械は知らないので、この会話が区切り（--rest）を印したターンの"
            "終わりに、待ち受けがこの設定で起動し直す（持ち主の手は要らない。会社の形の設定を替えたときも同じ）"]


def _shape(source, a, g):
    info = tree.read_info(source, os.path.dirname(config.path_of(a.config, os.environ)), g)
    return role.load(info["path"], info["text"]), info["notes"]


def reorg(a, ports, cwd):
    """--reorg。今いる部署の属性を付け替える。終了の値（2 は使い方の誤りか部署でない）。"""
    if a.persistent and a.ephemeral:
        print("止めた: --persistent と --ephemeral は一緒に使えない")
        return 2
    if not any([a.name, a.role, a.persistent, a.ephemeral, a.boss]):
        print("止めた: --reorg には、替える物（--name・--role・--persistent か --ephemeral・--boss）を 1 つ以上渡す")
        return 2
    cwd = ports.git.toplevel(cwd) or cwd   # 作業場の下のフォルダから打っても、部署の行（作業場のルート）と比べる
    attrs = ports.attrs(cwd)
    common = ports.git.common_dir(cwd)
    if not attrs.get("role") or not common:
        print(f"止めた: {cwd} は部署でない（git の設定 company.role が無い）。部署の場所から打つ"
              f"（本社の会話を窓口として名付けるなら --desk）")
        return 2
    source = gitx.root_of(common)
    shape, notes = _shape(source, a, ports.git)
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
    if a.persistent or a.ephemeral:
        changes["lifecycle"] = gitx.PERSISTENT if a.persistent else gitx.EPHEMERAL
    elif a.role and got and got["lifetime"] == role.ALWAYS:
        changes["lifecycle"] = gitx.PERSISTENT   # 役の lifetime = "always" は --persistent と同じ（--task と揃える）
    if a.role and got:
        changes["fresh"] = role.FRESH if got["context"] == role.NEW else None   # 役の context を写す（--task と揃える）
    if a.name:
        try:
            _, _, sessions_, _, companies, _, _ = orders.survey(a.config, ports)
        except term.Error:
            sessions_, companies = {}, []   # 名前のぶつかりを確かめられないだけ（属性は書ける）
        talk_name = ports.caller(sessions_)[1]
        clash = _clash(companies, cwd, a.name, ports.git)
        if clash:
            print(f"止めた: 「{a.name}」という名前の部署がもう在る（{clash}）。宛先が 1 つに決まらないので、別の名前にする")
            return 2
        changes["name"] = a.name
        try:
            former = _renamed(attrs, a.name)
        except gitx.AttrError as e:
            print(f"止めた: {e}")
            return 2
        if former:
            changes["former-names"] = former
    if a.boss:
        # 頼み元を替えたら、前の頼み元の会話の id とペインは消す（納品は新しい頼み元を名前で引く）。受付箱は残す
        changes.update({"boss": a.boss, "boss-account": a.boss_account, "boss-session": None, "boss-pane": None})
    head = f"部署 {attrs.get('name') or cwd}（役 {the_role}）を組み直す"
    return _write(a, ports, cwd, source, attrs, changes, notes, head, talk_name if a.name else None)


def desk(a, ports, cwd):
    """--desk [名前]。本社で持ち主と話す会話を窓口として名付ける。終了の値。"""
    cwd = ports.git.toplevel(cwd) or cwd   # 本社の下のフォルダから打っても、本社の行（代表の clone のルート）と比べる
    common = ports.git.common_dir(cwd)
    if not common:
        print(f"止めた: {cwd} が git でない（窓口は会社の代表の clone で開く）")
        return 2
    source = gitx.root_of(common)
    attrs = ports.attrs(cwd)
    shape, notes = _shape(source, a, ports.git)
    notes += shape["problems"]
    linked = ports.git.is_main_worktree(cwd) is False   # 部署か PR の作業場（ブランチの worktree）
    if linked and attrs.get("role") and role.current(shape, attrs["role"]) != desk_role(shape, {}, a.role):
        print(f"止めた: {cwd} は部署（役 {attrs['role']}）。部署の名前と役は --reorg で付け替える")
        return 2
    if linked:
        # 窓口がブランチの作業場に座ると、そのブランチへ部署を立てられず（部署はブランチの作業場で起動する）、頼みが届かずに終わる（3d3ccc）
        print(f"止めた: 窓口は本社（代表の clone {source}）で開く。{cwd} はブランチの作業場で、その会話はそのブランチの仕事をする"
              "（頼みを配るなら本社で会話を開いて --desk を打つ）")
        return 2
    the_role = desk_role(shape, attrs, a.role)
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
    except term.Error as e:
        cfg, sessions_, companies, more = None, {}, [], [f"{term.NAME} を読めないので、名前のぶつかりと会話のアカウントを確かめられない（{e}）"]
    notes += more
    clash = _clash(companies, cwd, name, ports.git)
    if clash:
        print("\n".join(notes + [f"止めた: 「{name}」という名前の部署がもう在る（{clash}）。別の名前にする"]))
        return 2
    account, talk_name = ports.caller(sessions_)
    session = chat.session_of(ports.env)
    if not account:
        notes.append("このコマンドを打った会話が会話の一覧に見えないので、アカウントと会話の id は今の値のまま"
                     "（窓口の会話の中から打てば書く）")
    pid = ports.caller_pid(sessions_) if account else None
    if account:
        held = attrs.get("pid")
        if not linked and held and held != str(pid) and session != attrs.get("session") and ports.running_chat(held):
            # 窓口の席は 1 つ。窓口の会話が動いている間に、ほかの会話（試しの claude -p など）が席を取ると、納品がそちらに届き、
            # 同じ役の会話が 2 つ動く（53d5d1・6be241）。一時停止の会話は /exit を受けないので、戻し方を添える（受付 d46e09）
            who = f"窓口 {attrs.get('name') or '-'} の会話（処理 {held}、会話 {attrs.get('session') or '-'}）"
            tty = ports.paused_chat(held)
            print("\n".join(notes + ([f"止めた: {who}が一時停止のまま残っている（ps の状態 T。端末の Ctrl+Z などで止まった物）。"
                                      f"止まった会話は /exit を受けないので、端末 {tty} で fg を打って会話を戻し、/exit で終えてから --desk を打ち直す"
                                      f"（端末を閉じて fg で戻せないなら、ps -p {held} -o command= で {chat.NAME} と確かめてから kill {held}; "
                                      f"kill -CONT {held} で終える。止まった処理は SIGCONT で再開するまで終わらない）"] if tty else
                                     [f"止めた: {who}がまだ動いている。席を移すなら、先にその会話を終える（/exit）"])))
            return 2
    try:
        changes, gh_user = _seat_changes(attrs, shape, cfg, source, ports, the_role, name, account, session, pid, talk_name)
    except gitx.AttrError as e:
        print(f"止めた: {e}")
        return 2
    held_by = account or attrs.get("account")
    command = next((x.command for x in (cfg.accounts if cfg else []) if x.name == held_by), chat.COMMAND)
    after = _launch_line(a, ports, source, shape, the_role, name, command)
    if gh_user and attrs.get("gh-user") != gh_user:
        # フックが GH_TOKEN を入れるのは会話の始まり（SessionStart）だけなので、打った会話には次の始まりから効く
        after.append(f"gh のアカウント {gh_user} は、この本社で次に始めた会話から効く（今の会話に効かせるなら /clear か、開き直す）")
    return _write(a, ports, cwd, source, attrs, changes, notes, f"窓口 {name}（{source}）を名付ける", talk_name, after)


def _at_office(ports, cwd, common):
    """その会話の作業フォルダ cwd が本社（代表の clone。git の場所が共通の場所と同じ）か。読めなければ偽。"""
    try:
        place = cwd and ports.git.git_dir(cwd)
    except (gitx.GitError, OSError):
        return False
    return bool(place) and _same(place, common)


def auto_desk(a, ports, here, sid, sessions_, cfg, companies):
    """--ask の頼み元の名付け。会社の形に desk_role が在る会社の本社で、まだ窓口でない会話（orders.place_name が None）が頼んだとき、
    --desk と同じ属性を本社に書いて窓口に名付ける（持ち主が新しい PC の本社で --desk を打ち忘れ、頼み元が会話の一覧の名前 my-notes-7b で
    書かれ、PC ごとに窓口の名前がずれた。頼み ee7368）。(名付けた窓口の名前か None, 注記の並び)。

    ほかの会話を窓口に取り違えないよう、次のどれかなら名付けない（注記を返し、頼み元は今までどおり会話の一覧の名前）:
    この会話が会話の一覧に見えない・持ち主と話す会話（kind interactive）でない（試しの claude -p や裏の処理）・前の窓口の会話
    （company.pid）がまだ動いている（--desk と同じ席の決まり）・本社にほかの持ち主の会話も居て、どれが窓口か見分けられない。
    名付く前に会話の一覧の名前で頼んだ行が台帳に在れば、その名前を前の名前に足す（_asked_as）。空打ちでは書かない。
    名付けた後に --ask がほかの訳（担当者の検査など）で止まっても、名付けは残す（見分けを通った会話なので、窓口として正しい）。
    git や会社の形を読めなければ名付けず、注記にして --ask は続ける。"""
    if not sid or not here:
        return None, []
    try:
        return _auto_desk(a, ports, here, sid, sessions_, cfg, companies)
    except (gitx.GitError, OSError) as e:
        return None, [f"注記: 本社のこの会話を窓口に名付けなかった（読めなかった: {e}）"]


def _auto_desk(a, ports, here, sid, sessions_, cfg, companies):
    """auto_desk の本体。git か会社の形を読めなければ gitx.GitError か OSError。"""
    common = ports.git.common_dir(here)
    if not common or not _at_office(ports, here, common):
        return None, []
    source = gitx.root_of(common)
    shape, _ = _shape(source, a, ports.git)
    if not shape.get("desk_role"):
        return None, []   # 会社の形に desk_role の無い会社は今までどおり（--desk を手で打つ）
    attrs = ports.attrs(source)
    account, talk_name = ports.caller(sessions_)
    pid = ports.caller_pid(sessions_)
    entry = next((s for items in sessions_.values() for s in items if s.get("sessionId") == sid), None)
    the_role = desk_role(shape, attrs, None)
    name = attrs.get("name") or the_role
    held = attrs.get("pid")
    others = sorted({s.get("name") or s.get("sessionId") or "-" for items in sessions_.values() for s in items
                     if s.get("sessionId") != sid and s.get("kind") == "interactive" and s.get("state") not in orders.FALLEN
                     and _at_office(ports, s.get("cwd"), common)})
    pick = False   # 持ち主の会話が 2 つ以上居て、機械が窓口を選べない
    if not account or not entry:
        why = "この会話が会話の一覧に見えない"
    elif entry.get("kind") != "interactive":
        why = f"この会話は持ち主と話す会話でない（会話の一覧の kind が {entry.get('kind') or '-'}）"
    elif held and held != str(pid) and ports.running_chat(held):
        why = f"窓口 {name} の会話（処理 {held}）が動いている"
    elif others:
        pick = True
        why = f"本社にほかの会話（{', '.join(others)}）も居て、どれが窓口か見分けられない"
    else:
        why = _clash(companies, source, name, ports.git)
        why = why and f"「{name}」という名前の部署がもう在る（{why}）"
    if why:
        # --desk を勧めるのは、持ち主の会話が 2 つ居て機械が選べないときだけ（試しの会話が読んで席を取らない。role_hook の DESK_HINT と同じ）
        return None, [f"注記: 本社のこの会話を窓口に名付けなかった（{why}）。頼み元は会話の一覧の名前 {talk_name or '-'} で書く"
                      + ("（この会話が窓口なら --desk を打つ）" if pick else "")]
    try:
        changes, _ = _seat_changes(attrs, shape, cfg, source, ports, the_role, name, account, sid, pid, talk_name)
    except gitx.AttrError as e:
        return None, [f"注記: 本社のこの会話を窓口に名付けなかった（{e}）"]
    added = [n for n in gitx.former_names({"former-names": changes.get("former-names")}) if n == talk_name]
    said = (f"本社のこの会話を窓口 {name}（役 {the_role}。会社の形の desk_role）に名付け" + ("る（空打ちなので書かない）" if a.dry_run else "た")
            + "。--desk を手で打たなくてよい" + (f"。前に会話の一覧の名前 {talk_name} で頼んだ物の納品もこの窓口に届く" if added else ""))
    if a.dry_run:
        return name, [said]
    try:
        provision.mark(source, source, changes, ports.git)
    except (gitx.GitError, OSError) as e:
        return None, [f"注記: 本社のこの会話を窓口に名付けなかった（属性を書けなかった: {e}）"]
    return name, [said + f"（{term.NAME} のペインの名前は --sync で付け直す）"]
