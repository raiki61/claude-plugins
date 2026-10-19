#!/usr/bin/env python3
"""依頼と納品の流れ（会社の形の設計 4.5・4.10 の 3・9.2）。入口の dispatch.py --ask・--deliver と、プラグインの Stop フックから呼ぶ。

dispatch.py の流れの続きで、ノード（nodes/deliver.py ほか）を呼ぶ順をここが持つ。ほかの部署と dispatch.py を同時に直すので、
ぶつかりを減らすために別のファイルにした。

--ask <宛先>（ask）: 頼む会話の場所から、宛先の部署を「会社/役」か部署の名前か会社の名前（その会社の窓口）で決め（deliver.find_target。会社は herdr に開いている
リポジトリ。tree と同じ読み方）、頼みの本文を頼む側の受付箱に置き、宛先の部署に知らせる。宛先（「会社/部署の名前」）の待ち受けが
居れば、宛先の会社の受付箱の台帳に知らせの 1 行を足し、待ち受けが会話を再開させる（nodes/wake.py）。居なければ（フックの無い古い会話・
落ちた会話）、宛先の部署の窓（attach のペイン）に 1 行を打ち込む。宛先の部署が立っていなければ、--task と同じ道（dispatch._task）で
立て、最初の文で頼みを渡す。宛先の部署の属性に、受けた頼み（company.ask）と頼み元（company.boss・boss-account・boss-session・
boss-pane・boss-inbox）を書く。頼み元の名前は、頼んだ場所の名前（company.name。place_name）か、会話の一覧の名前。--forward を添えれば、打った部署か窓口が受けている頼みを、この頼みで回したとして閉じる（forwarded。
回した先は台帳にだけ書き、頼み元の会話は起動しない）。

--deliver <要約のファイル>（deliver）: 部署の場所から、要約の項目がそろっているかを確かめ（欠けていれば送らずに欠けた項目を返す）、
役に納品の検査（会社の形の deliver_check）が在れば走らせ（0 以外で終われば送らずに検査の出力を返す。deliver.gate）、
頼み元の受付箱に置き、頼み元（「頼み元の会社/company.boss」。引けなければ company.boss-session の会話）の待ち受けが居ればその
台帳に知らせの 1 行を足し、居なければ頼み元の窓に 1 行を打ち込み、属性に納品済み（company.delivered）を書く。
--for <受付> を添えれば、--forward で回して閉じた頼みの頼み元（台帳の forwarded の行）か、cause 付きの --ask で回した子の頼みの
元の頼みの頼み元（元の頼みの kind ask の行）へ返し、今受けている頼みは閉じない。

`python3 orders.py stop`（stop_hook）: プラグインの Stop フック。部署でない場所では何もしない。
"""

import argparse
import contextlib
import io
import json
import os
import pathlib
import re
import shlex
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
try:
    from ports import chat, term  # noqa: E402
    import windows  # noqa: E402
    import config  # noqa: E402
    import ghx  # noqa: E402
    import gitx  # noqa: E402
    import todo  # noqa: E402
    from nodes import deliver, land, launch, ledger, provision, role, sync, tools, tree, wake  # noqa: E402
except (ImportError, SyntaxError) as _e:
    # Stop のフックはどの会話の終わりにも走るので、古い Python（tomllib の無い 3.10 以前）でも traceback を出さず、短い言葉で
    # 知らせて会話を止めない（終了の値 1 は、Claude Code が会話を止めない誤りとして stderr を見せる）。ターンごとに出さず、
    # 会話ごとに 1 回だけ出す（hooks/run-python.sh の --once と同じ。会話の id はフックの入力から読む）
    import tempfile
    try:
        _sid = (json.loads(sys.stdin.read() or "{}") or {}).get("session_id") or "none"
    except ValueError:
        _sid = "none"
    _mark = pathlib.Path(tempfile.gettempdir()) / f"works-dispatch-no-python-{_sid}"
    if _mark.exists():
        sys.exit(0)
    try:
        _mark.touch()
    except OSError:
        pass
    print(f"works-dispatch: 止まる前のフックを動かせない（Python 3.11 以上が要る: {_e}）", file=sys.stderr)
    sys.exit(1)

DISPATCH_PY = str(pathlib.Path(__file__).resolve().parent / "dispatch.py")
# 部署に「この字で返せ」と渡す dispatch.py の起動コマンド。今動いている Python で、パスは / 区切りで引用符を付ける
# （Windows の Claude Code の Bash のツールは Git Bash で、\ と空白のパスがそのままでは崩れ、python3 が無いこともある）
RUN = " ".join(shlex.quote(pathlib.Path(x).as_posix()) for x in (sys.executable, DISPATCH_PY))


def own_version():
    """この works-dispatch の版（plugin.json の version）。読めなければ None。ゲート（deliver_check・ask_check）に JSON の version で渡し、
    会社の側の台本が版の下限を確かめられるようにする（古い版は知らないフィールドを読み飛ばすので、会社の形に下限を書いても止まらない。3c9a61）。"""
    try:
        return json.loads((pathlib.Path(__file__).resolve().parent.parent / ".claude-plugin" / "plugin.json")
                          .read_text(encoding="utf-8")).get("version")
    except (OSError, ValueError, AttributeError):
        return None

for _s in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


def survey(config_path, ports):
    """herdr に開いている会社と部署を読む（dispatch._company と同じ読み方）。(設定か None, アカウントの並び, 会話の一覧, ペイン,
    会社の並び, 設定の置き場, 注記)。herdr を読めなければ term.Error。"""
    notes = []
    path = config.path_of(config_path, os.environ)
    try:
        cfg = config.load(config_path, os.environ, missing_ok=True)
        accounts_ = cfg.accounts
    except config.ConfigError as e:
        cfg, accounts_ = None, (config.Account("default", chat.COMMAND),)
        if os.path.exists(path):
            notes.append(f"dispatch の設定を読めないので、既定のアカウント 1 つとして見る（{e}）")
    sessions_ = {}
    for acc in accounts_:
        try:
            sessions_[acc.name] = ports.list_sessions(acc.config_dir, include_done=True)
        except chat.Error as e:
            notes.append(f"アカウント {acc.name} の会話の一覧を読めないので、そのアカウントの会話を見ない（{e}）")
            continue
        odd = chat.unknown_values(sessions_[acc.name])
        if odd:
            notes.append(f"アカウント {acc.name} の会話の一覧（{chat.LIST_COMMAND}）に、読み方を知らない値がある: "
                         f"{', '.join(f'{k} が {n} 件' for k, n in sorted(odd.items()))}（claudex.py の KNOWN_STATUS・KNOWN_STATE と読む所を見直す）")
    panes = ports.term.panes()
    roots = tree.roots(ports.term.workspaces(), panes, ports.common_of,
                       list(dict.fromkeys(s["cwd"] for items in sessions_.values() for s in items if s.get("cwd"))))
    places_of = {}
    for root in roots:
        try:
            places_of[root] = ports.term.worktrees(root)
        except term.Error as e:
            places_of[root] = []
            notes.append(f"{root}: worktree を並べられない（{e}）")
    settings = os.path.dirname(path)
    companies = tree.build(roots, places_of, panes, ports.attrs, lambda root: tree.read_info(root, settings), sessions_)
    return cfg, accounts_, sessions_, panes, companies, settings, notes


def current_role(settings):
    """find_target に渡す (会社, 役の名前) → 今の役の名前（その会社の形の former_names）。会社ごとに 1 度だけ読む。"""
    shapes = {}

    def current(company, name):
        if company["root"] not in shapes:
            info = tree.read_info(company["root"], settings)
            shapes[company["root"]] = role.load(info["path"], info["text"])
        return role.current(shapes[company["root"]], name)
    return current


def shape_role(root, settings, name):
    """会社の形（--task と同じ読み方。root が None なら無い）からその役の項目と、会社の形の注記（読み方の注記と形の誤り）。"""
    info = tree.read_info(root, settings) if root else {"path": None, "text": None, "notes": []}
    shape = role.load(info["path"], info["text"])
    return shape["roles"].get(role.current(shape, name)), info["notes"] + shape["problems"]


# 頼みごとに空の会話で受ける部署の属性の値（ask の中では role が役の名前の字なので、ここで写す）
FRESH = role.FRESH

# 落ちた部署の会話を attach で戻した後、窓に会話が出るのを見る回数（1 回ごとに ports.pause）
REVIVE_LOOKS = 20


# 会話の一覧の状態のうち、会話が落ちている物（tree の STATES の鍵）
FALLEN = ("stopped", "failed")
# attach の画面が終わったときに Claude Code がペインに出す行（「Session cb2d81c3 has exited.」。2.1.301 で見た）
EXITED = re.compile(r"Session \S+ has exited\.")


def inbox_company(inbox, settings):
    """受付箱の在る会社の名前（宛先の「会社/名前」の会社。待ち受けと同じ読み方）。"""
    root = gitx.root_of(deliver.common_of_inbox(inbox))
    return tree.company_name(root, tree.read_info(root, settings))


def listener(inbox, company_name, name):
    """宛先「会社/名前」の待ち受けの (宛先, 印)。名前が無いか、待ち受けが居なければ (宛先か None, None)。"""
    if not (inbox and company_name and name):
        return None, None
    to = wake.address(company_name, name)
    return to, wake.listening(inbox, to)


def place_name(here, sid, ports):
    """頼んだ場所の名前（属性 company.name）か None。窓口と部署の待ち受けはこの名前で宛先を受ける（wake_hook.plan）ので、頼み元の
    名前に会話の一覧の名前より先に使う（一覧の名前は替わりうる。段取りが会話の名前 my-notes-d7 で頼み、納品が待ち受けに届かず
    窓に打ち込まれた。my_notes の受付 20261017-032608-18b5f5）。本社（代表の clone）は持ち主のほかの会話も居るので、--desk が書いた
    会話（company.session）か、その会話の処理（company.pid）の中から頼んだときだけ。窓口が /clear で会話を空にすると会話の id が
    替わり、待ち受けが company.session を書き直すまでの間は id が合わない（その間の頼みが会話の一覧の名前 my-notes-d7 で頼み元を
    書き、納品が窓に直に打ち込まれ続けた。my_notes の受付 20261017-054115-5bc0b0）ので、処理でも見る（wake_hook.plan と同じ見分け方）。"""
    attrs = ports.attrs(here)
    if not attrs.get("role") or not attrs.get("name"):
        return None
    place, common = ports.git.git_dir(here), ports.git.common_dir(here)
    desk = provision.desk_seat(place, common, attrs)
    return attrs["name"] if not desk or (sid and attrs.get("session") == sid) or ports.same_process(attrs.get("pid")) else None


def live_window(dept, ports):
    """部署の窓（会話の居るペイン）か None。herdr はペインの会話の印を、attach の画面が終わってシェルに戻った後も残すので、
    印だけでは落ちた会話を見分けられない（まっさらな環境での 6 回目の試しの 1）。前に居るのがシェルなら（macOS・Linux）、
    画面の終わりに「Session … has exited.」が出ていれば（Windows を含む。Windows は前のプロセスを見る口が当てにならない）、
    会話は居ないと見る。"""
    pane = deliver.window(dept)
    if pane is None:
        return None
    if dept.get("state") in FALLEN:
        # 会話の一覧が止まったと言う。裏の処理が止まった後も、窓の attach が「Waking session …」のまま前に残る（Linux で見た。
        # まっさらな環境での 7 回目の試しの 2）ので、窓の前のプロセスだけでは見分けられない
        return None
    try:
        if os.name != "nt" and ports.term.shell_in_front(pane):
            return None
        tail = ports.term.read(pane, 6)
    except term.Error:
        return pane   # 確かめられないときは、居ると見て今までどおり（打ち込んで会話を乱さない側）
    lines = [x for x in (tail or "").splitlines() if x.strip()]
    if lines and EXITED.search("\n".join(lines[-3:])):
        return None
    return pane


def place_talk(dept, sessions_, accounts_):
    """会話の一覧（アカウントの名 → 並び。終わった物も含む）のうち、作業フォルダが部署の場所の裏の会話の (アカウントの名, 1 件)。
    属性にアカウントが残っていれば、そのアカウントの一覧だけを見る。動いている（作業中か返事待ち）物を先に、次に名前が部署の名前の
    物を先に、その中で起きた時刻の新しい物。本社（窓口）は選ばない（代表の clone には持ち主のほかの会話も居る）。無ければ None。"""
    if dept.get("head_office"):
        return None
    here = os.path.realpath(dept["path"])
    mine = dept["attrs"].get("account")
    hits = [(name, x) for name, items in (sessions_ or {}).items() if not mine or name == mine for x in items
            if x.get("kind") == "background" and x.get("sessionId") and x.get("cwd") and os.path.realpath(x["cwd"]) == here]
    live = [h for h in hits if h[1].get("state") in ("working", "blocked")]
    named = [h for h in (live or hits) if h[1].get("name") == dept["attrs"].get("name")]
    return max(named or live or hits, key=lambda h: h[1].get("startedAt") or 0, default=None)


def revive(dept, accounts_, ports, sessions_=None, source=None):
    """部署の窓に会話が居ない（PC やサーバーの再起動で attach の窓が落ちたなど）とき、部署の属性の会話の id で、部署のペインに
    `<アカウントのコマンド> attach <id>` を打ち、窓に会話が戻るのを見る。裏の会話は落ちても記録が残り、attach で前の続きから
    戻る（まっさらな環境での 5 回目の試しの 1。Windows で確かめた）。(戻ったペインか None, 言葉)。"""
    full = dept["attrs"].get("session")
    found = None if full else place_talk(dept, sessions_, accounts_)
    if not full and not found:
        return None, "部署の属性に会話の id（company.session）が無く、会話の一覧にも部署の場所の裏の会話が無いので戻せない（部署を立て直す）"
    if found:
        # 属性の会話の id が消えていた（前の版の --move が前の会話を止めた直後に止められ、id を消したまま終わった。2026-10-17 の
        # 割り振り・説明書・ノートの手入れ）: 会話の一覧の、部署の場所の裏の会話で戻し、属性も書き戻す
        account, entry = found
        full = entry["sessionId"]
        dept = {**dept, "attrs": {**dept["attrs"], "session": full, "job": chat.attach_id(entry), "account": account}}
    acc = next((x for x in accounts_ if x.name == dept["attrs"].get("account")), accounts_[0] if len(accounts_) == 1 else None)
    entry = next((x for items in (sessions_ or {}).values() for x in items if x.get("sessionId") == full), None)
    # attach は短い id で打つ（部署を立てるときと同じ）。一覧に無ければ属性の短い id（company.job。/clear で会話の id が変わっても
    # 変わらない）
    sid = chat.attach_id(entry, full) if entry or not dept["attrs"].get("job") else dept["attrs"]["job"]
    command = chat.attach_command(acc.command if acc else None, sid)
    try:
        if not dept["panes"] and source:
            # ペインを閉じると部署の作業場も閉じる。開き直し、新しいペインのシェルで attach を打つ
            fresh, ws = provision.reopen(source, dept["path"], dept["attrs"].get("name") or os.path.basename(dept["path"]), ports.term)
            if fresh:
                dept = {**dept, "panes": [{"pane_id": fresh, "agent": None}]}
                # 開き直したペインにも、部署の名前・表示名・札を --sync と同じに付ける。開き直した作業場は新しいので、印も付け直す
                sync.apply([sync.op(fresh, dept["attrs"], len(accounts_) > 1)], ports.term)
                if ws:
                    sync.apply_workspaces([sync.kind_op(ws, dept["attrs"])], ports.term)
                for _ in range(REVIVE_LOOKS):
                    if ports.term.shell_in_front(fresh):
                        break
                    ports.pause()
        pane = next((p["pane_id"] for p in dept["panes"] if ports.term.shell_in_front(p["pane_id"])), None)
        if pane is None:
            # 止まった attach が窓の前に残っていれば Ctrl+Z（2.1.302 からは続けて Esc）でシェルに戻し、シェルに戻るのを見る
            for p in dept["panes"]:
                if launch.to_shell(p["pane_id"], ports.term, ports.pause, REVIVE_LOOKS):
                    pane = p["pane_id"]
                    break
    except term.Error as e:
        pane = None
        why = str(e)
    else:
        why = f"部署の作業場が {term.NAME} に開いていない" if not dept["panes"] else "部署のペインの前にシェルが居ない"
    if pane is None:
        return None, f"部署の会話を戻せなかった（{why}）。部署の作業場のペインで {command} を打って戻す"
    got = launch.attach({"account": {"command": acc.command if acc else chat.COMMAND}}, pane, sid, ports.term)
    if got["status"] != "attached":
        return None, f"部署の会話を戻せなかった（{got['detail']}）。部署のペイン {pane} で {command} を打って戻す"
    for look in range(REVIVE_LOOKS):
        ports.pause()
        try:
            screen = ports.term.read(pane, 6)
            alive = (ports.term.agent(pane) or {}).get("agent") and not EXITED.search(screen or "") \
                and "No job matching" not in (screen or "") and (os.name == "nt" or not ports.term.shell_in_front(pane))
        except term.Error:
            alive = False
        if alive:
            said = f"部署の窓に会話が居なかったので、ペイン {pane} で {command} を打って戻した"
            if found:
                # 会話の一覧から選んだ会話が窓に戻ったのを見てから、属性に書き戻す（外れた会話を属性に残さない）
                try:
                    provision.mark(dept["path"], source or gitx.root_of(ports.git.common_dir(dept["path"])),
                                   {k: dept["attrs"][k] for k in ("session", "job", "account")}, ports.git)
                    said += "（属性に会話の id が無かったので、会話の一覧の部署の場所の会話で戻し、属性に書き戻した）"
                except (gitx.GitError, OSError) as e:
                    said += f"（会話の一覧の部署の場所の会話で戻したが、属性に書き戻せなかった: {e}）"
            return pane, said
    try:
        screen = ports.term.read(pane, 6)
    except term.Error:
        screen = ""
    if "00~" in screen:
        # attach の画面を強く終わらせると、窓の端末に貼り付けの印（ESC[200~）が残り、打ったコマンドの前後に 00~ と 01~ が付いて
        # 届く（まっさらな環境での 7 回目の試しの 4。macOS で見た）。dispatch の打つ字も同じ道を通るので、ここでは直せない
        return None, (f"ペイン {pane} の端末に貼り付けの印が残っていて、{command} が崩れて届いた（画面に 00~ が出ている）。"
                      f"部署の窓で reset を打って端末を戻してから、--ask を打ち直す")
    return None, f"ペイン {pane} で {command} を打ったが、窓に会話が戻らない（画面を見て、会話が戻ったら --ask を打ち直す）"


def dept_talk(dept, items):
    """会話の一覧から部署の会話の 1 件。属性の会話の id（company.session）の物、無ければ部署の場所に居る裏の会話が 1 つだけならそれ。
    部署の会話で /clear を打つと会話の id が変わり、属性の id は古いまま残る（2026-10-16 の試しの部署で、属性と一覧の id が違った）。"""
    full = dept["attrs"].get("session")
    mine = next((x for x in items if full and x.get("sessionId") == full), None)
    if mine:
        return mine
    here = [x for x in items if x.get("kind") == "background" and x.get("state") not in ("done", "failed", "stopped")
            and x.get("cwd") and os.path.realpath(x["cwd"]) == os.path.realpath(dept["path"])]
    return here[0] if len(here) == 1 else None


def busy_check(dept, accounts_, ports):
    """部署の会話が動いている（会話の一覧の status が busy）かを見る関数。送った 1 行が届いたかの確かめに使う。
    見つけた会話の id を関数の found に残す（属性の id が古ければ、頼みの属性と一緒に書き直す）。"""
    acc = next((x for x in accounts_ if x.name == dept["attrs"].get("account")), accounts_[0] if len(accounts_) == 1 else None)

    def busy():
        try:
            items = ports.list_sessions(acc.config_dir if acc else None)
        except chat.Error:
            return False
        talk = dept_talk(dept, items)
        if talk:
            busy.found = talk.get("sessionId")
        return bool(talk) and talk.get("status") == "busy"
    busy.found = None
    return busy


def clear_before_ask(dept, held, pane, busy, ports, newest=lambda: None):
    """頼みごとに空の会話で受ける役（fresh）の部署に、新しい頼みを打つ前に /clear を打つ。(送ってよいか, 出す注記の並び)。
    空にするのは、前の頼み（company.ask）を納品し終えていて、会話が止まっているときだけ（納品していない頼みはここまでに止めている。
    頼みの無い部署は --task の頼みのファイルで働いているかもしれず、動いている会話を空にすると途中の仕事が消える）。納品し終えた
    部署を空にできない（動いている・空になったのを見られない）ときは送らない（打った頼みは前の会話のまま届く）。
    空になったのは、会話の一覧の id が替わったか、newest（部署の場所のいちばん新しい会話の記録の (名前, 時刻)。claudex.newest_talk）が
    打つ前と別のファイルになったかで見る（裏の会話は /clear の後も一覧の id が替わらないことがある）。"""
    if not held:
        return True, ["頼みごとに空にする役だが、部署にまだ納品した頼みが無いので、空にせずに送る"]
    if busy():
        return False, ["頼みごとに空にする役だが、部署の会話が動いていて空にできないので送らなかった（打つとターンの後に前の会話のまま"
                       "届く）。ターンが終わってから --ask を打ち直す"]
    before, talk = busy.found, newest()

    def cleared():
        busy()
        now = newest()
        return bool(busy.found) and busy.found != before or bool(now) and bool(talk) and now[0] != talk[0]
    status, detail = deliver.clear_talk(pane, ports.term, ports.pause, cleared)
    if status == "cleared":
        return True, [f"前の頼み（受付 {held}）を納品し終えているので、/clear で会話を空にしてから送る"]
    if talk is None:   # 置き場の名前は Claude Code の作り方を写している（claudex.newest_talk）。作り方が変われば、ここに出る
        detail += f"。部署の場所の会話の記録が見つからなかった（claudex.newest_talk の作る置き場の名前が、{chat.NAME} の物と違うかもしれない）"
    return False, [f"会話を空にできなかったので送らなかった（{detail}）。部署の窓を見て、空になっていれば --ask を打ち直す"]


def nudge_line(held, boss, now=None):
    """戻した部署に、落ちる前の頼みの納品を促す 1 行。頭に時刻を入れて、前に送った促しと字を分ける（届いたかの確かめが、画面に
    残った前の促しを今の促しと見誤らないように）。"""
    stamp = time.strftime("%H:%M:%S", time.localtime(now)) if now else ""
    return (f"再開の知らせです{f'（{stamp}）' if stamp else ''}: この会話は落ちて戻った。受付 {held}（{boss or '頼み元'} から）の頼みをまだ納品していない。"
            "済んでいれば要約を納品のコマンド（--deliver）で返し、途中なら続けてから返す。")


def ask(a, ports, cwd, task):
    """--ask。task は dispatch._task（部署を立てる道）。終了の値を返す。--forward なら、打った場所が受けている頼みを、この頼みで
    回したとして閉じる（forwarded）。"""
    held = None
    if getattr(a, "forward", False):
        mine = ports.attrs(cwd)
        held = mine.get("ask")
        if not mine.get("role") or not held or mine.get("delivered") == held:
            print("止めた: --forward は、受けた頼みをまだ納品していない部署か窓口の場所から打つ（回す元の頼みが無い）")
            return 2
    sent = {}
    rc = _ask(a, ports, cwd, task, sent)
    if held and rc == 0:
        if a.dry_run:
            print(f"- 回した元: 受付 {held} を閉じ、回した先を台帳に書く（頼み元 {mine.get('boss') or '-'} の会話は起動しない）")
        elif sent:
            print("\n".join(forwarded(mine, sent, ports, cwd)))
    return rc


def forwarded(attrs, sent, ports, cwd):
    """--forward で回した後: 受けた頼み（attrs の company.ask）から回した先の頼み（sent の id と to）への結び付きを、自分と頼み元の
    受付箱の台帳に kind forwarded で残し、受けた頼みを納品済みにする。頼み元には知らせない（回しただけの知らせで頼み元の会話を
    起動しない。頼み元は、結果か問いの納品で起きたときに台帳で追う）。結果と問いは --deliver --for <受けた頼み> で返す（頼み元は
    この行から引く）。出す行を返す。"""
    held = attrs["ask"]
    common = ports.git.common_dir(cwd)
    record = {"id": held, "kind": "forwarded", "at": ports.now(), "child": sent["id"], "to": sent["to"],
              "from": {"name": attrs.get("name"), "session": attrs.get("session"), "place": cwd},
              "boss": {"name": attrs.get("boss"), "session": attrs.get("boss-session"), "account": attrs.get("boss-account"),
                       "pane": attrs.get("boss-pane"), "inbox": attrs.get("boss-inbox")}}
    boss_inbox = attrs.get("boss-inbox")
    for inbox in dict.fromkeys([deliver.inbox_of(common)] + ([boss_inbox] if boss_inbox and os.path.isdir(boss_inbox) else [])):
        deliver.log(inbox, record)
    try:
        provision.mark(cwd, gitx.root_of(common), {"delivered": held, WAITING: None, WAITING_WHY: None}, ports.git)
    except (gitx.GitError, OSError) as e:
        return [f"回した元の受付 {held} を納品済みにできなかった（{e}）。台帳には回した先を書いた。--deliver で閉じる"]
    return [f"回した元の受付 {held} を閉じた（頼み元 {attrs.get('boss') or '-'} の会話は起動せず、回した先を台帳に書いた）"]


def _ask(a, ports, cwd, task, sent):
    """--ask の本体。頼みが宛先に届いた（送った・積んだ・同じ中身が動いている）なら、sent に回した先の頼みの id と宛先（to）を書く。"""
    if bool(a.text) == bool(a.brief):
        print("止めた: --ask には --text <文> か --brief <ファイル> のどちらか 1 つが要る")
        return 2
    body = a.text
    if a.brief:
        try:
            body = pathlib.Path(os.path.expanduser(a.brief)).read_text(encoding="utf-8")
        except OSError as e:
            print(f"止めた: 頼みのファイルを読めない（{e}）")
            return 2
    data, rest, bad = deliver.front(body)
    bad += deliver.front_problems(data, deliver.ASK_FIELDS)
    title = deliver.ask_title_of(body) or getattr(a, "title", None)   # 回し直し（--take）は順番待ちの件の題
    if not title and not getattr(a, "ask_id", None):   # 回し直し（--take・合図）は元の頼みの行の題を使う
        bad.append("題が無い。本文が 2 行以上なら、頭書きに title を書く")
    if bad:
        print("\n".join(["止めた: 頼みの本文の頭書き（機械が読むフィールド）が足りないか形が違う"] + [f"  {x}" for x in bad]
                        + [deliver.ASK_FORMAT]))
        return 2
    common = ports.git.common_dir(cwd)
    if not common:
        print(f"止めた: 頼む会話の場所 {cwd} が git でないので、受付箱を置けない（会社の本社か部署の場所から頼む）")
        return 2
    try:
        cfg, accounts_, sessions_, panes, companies, settings, notes = survey(a.config, ports)
        target = deliver.find_target(companies, gitx.root_of(common), a.ask, a.task, current_role(settings))
    except term.Error as e:
        print(f"止めた: {term.NAME} を読めない（{e}）")
        return 1
    except deliver.DeliverError as e:
        print(f"止めた: {e}")
        return 2
    company, dept, role = target["company"], target["department"], target["role"]
    if dept is None and not a.dry_run:
        # 部署を新しく立てる: 納品の項目と起動するときの設定を、立てた後のフックと同じ会社の形で決める（--task と同じ。task には
        # 取り直したことを渡し、2 度は取らない）
        notes += [n for n in [provision.refresh_shape(company["root"], ports.git)] if n]
    the_role, problems = shape_role(company["root"], settings, role)
    required = deliver.required_items(the_role)
    notes += problems
    relays = (the_role or {}).get("ask_holders")
    ask_id = getattr(a, "ask_id", None) or deliver.new_id(ports.now())
    check = (the_role or {}).get("ask_check")
    if check:
        # 受ける会社のゲート: 頼む会話の会社でなく、受ける会社の origin の既定のブランチの中身で走らせる（止める中身は受ける会社の持ち物。
        # 代表の clone の作業ツリーは古いブランチのことがあるので、機械窓口のツールと同じ場所の作り方。242baa）
        try:
            with tools.place(company["root"], ports.git) as (here, said):
                code, out = deliver.gate(check, here, {"to": a.ask, "role": role, "body": body, "ask": ask_id,
                                                       "type": deliver.ask_type_of(data), "from": chat.session_of(ports.env),
                                                       "version": own_version()},
                                         subprocess.run)
        except (gitx.GitError, OSError) as e:
            code, out, said = 1, str(e), None
        if said:
            notes.append(said)
        if code != 0:
            print("\n".join(notes + [f"止めた: 受ける会社 {company['name']} のゲート（役「{role}」の ask_check: {check}）が通さなかった"
                                     f"（終了の値 {code}）"] + [f"  {x}" for x in out.splitlines()]))
            return 2
    found_account, found_name = ports.caller(sessions_)
    inbox = deliver.inbox_of(common)
    sid = chat.session_of(ports.env)
    # 頼み元の窓は、頼んだ会話の居るペイン（windows.own_pane。環境変数 HERDR_PANE_ID は裏の会話では別のペインを指すことがある）。
    # Claude Code の外から頼んだ（会話の id が無い）なら、頼んだ会話が無いので窓も記録しない
    here = next((s.get("cwd") for items in sessions_.values() for s in items if sid and s.get("sessionId") == sid and s.get("cwd")), cwd)
    account, name = a.from_account or found_account, a.from_name or place_name(here, sid, ports) or found_name
    sender = name or "名の無い会話"
    if relays is not None:
        # 問いを受ける役（相談）へ宛てた頼みにも、残った疑問（頭書きの open）が在れば同じ担当者の検査を掛ける。頼む側が自分で持つ物は
        # 頼む側の名前を担当者に書ける
        # 回し直し（--take）の本文は、頭書きの入る前に積まれた物も在るので、本文の見出しは見ない
        bad = deliver.holder_problems(data.get("open"), relays, name) + (
            [deliver.OPEN_IN_BODY] if not getattr(a, "ask_id", None) and deliver.OPEN in deliver.parse(rest, {deliver.OPEN}) else [])
        if bad:
            print("\n".join(notes + [f"止めた: 宛先の役「{role}」への頼みの残った疑問に、担当者が足りない（役の ask_holders の検査）"]
                            + [f"  {x}" for x in bad] + [deliver.ASK_FORMAT]))
            return 2
    elif data.get("open"):   # 受ける役が残った疑問を読まないのに書いた（台帳にも残らず、黙って捨てることになる）
        print("\n".join(notes + [f"止めた: 宛先の役「{role}」は頼みの残った疑問（頭書きの [[open]]）を受けない（役に ask_holders が無い）。"
                                 "疑問は本文に書く"]))
        return 2
    if dept is not None and sid and dept["attrs"].get("session") == sid:   # 宛先の会話が、頼むこの会話
        print("\n".join(notes + [f"止めた: 宛先「{a.ask}」はこの会話自身（{dept['attrs'].get('name') or dept['path']}）"
                                 + (f"。{target['via']}が、この会話だった" if target.get("via") else "")]))
        return 2
    if target.get("via"):
        notes.append(f"宛先「{a.ask}」は{target['via']}の {company['name']}/{dept['attrs'].get('name')} に届ける")
    # 納品を受ける受付箱は、頼んだ会話の居る場所の会社の物（待ち受けはそこで宛先を受ける）。コマンドを打った場所（cwd）がほかの会社の
    # clone でも替えない（段取りが claude-plugins の clone で打った頼みの返り先が claude-plugins の受付箱になり、段取りの待ち受けに
    # 届かなかった。my_notes の受付 20261017-054115-5bc0b0）
    here_common = ports.git.common_dir(here) if here != cwd else common
    boss = {"ask": ask_id, "boss": name, "boss-account": account, "boss-session": sid,
            "boss-pane": windows.own_pane(here, sid, panes) if sid else None,
            "boss-inbox": deliver.inbox_of(here_common) if here_common else inbox}
    if getattr(a, "from_boss", None):
        # 合図で回した頼み（calls.fire）: 頼み元は、メインブランチに入れた部署の頼み元
        boss.update({k: v for k, v in a.from_boss.items() if k != "ask"})
        name = boss.get("boss")
        sender = name or sender
    if not boss.get("boss"):
        notes.append("頼み元が分からないので、この頼みの納品の返り先が無い（会話の中から打つか --from-name を渡す）")
    cause = cause_of(a, here, ports)
    cause_boss = cause_boss_of(a, here, ports, cause)
    where = f"{company['name']}/{(dept or {}).get('attrs', {}).get('name') or role}"
    if (the_role or {}).get("machine"):
        print("\n".join(notes + [f"止めた: 役「{role}」は機械だけの役（AI の部署を持たない）なので頼めない。ツールを --call で呼ぶ"
                                 f"（--tree がツールを出す）"]))
        return 2
    if dept is not None:
        held = dept["attrs"].get("ask")
        pending = held and dept["attrs"].get("delivered") != held
        digest = deliver.digest(body)
        if pending and dept["attrs"].get("ask-digest") == digest:
            sent.update(id=held, to={"company": company["name"], "name": dept["attrs"].get("name"), "role": role})
            print("\n".join(notes + [f"頼み {held} → {where}  同じ中身の頼みが動いている（新しく積まない）"]))
            return 0
        dest_common = ports.git.common_dir(company["root"])
        dest_inbox = deliver.inbox_of(dest_common) if dest_common else None
        place_dir = ports.git.git_dir(dept["path"])
        to, heard = listener(dest_inbox, company["name"], dept["attrs"].get("name"))
        fresh = bool((the_role or {}).get("fresh"))
        # 待ち受けの跡の在る fresh の部署が、納品し終えてターンの途中（待ち受けが止まっている）なら積む。ターンの終わりの待ち受けが空にしてから渡す
        mid_turn = fresh and held and not pending and busy_check(dept, accounts_, ports)()
        def queue(d):   # 待ち受けの居る部署: 順番待ちに積み、待ち受けが渡す（受付の設計 4.1）
            return queue_ask(a, ports, notes, where, d, dest_inbox, place_dir, to, heard, digest,
                             {"id": ask_id, "sender": sender, "body": body, "title": title, "inbox": inbox, "required": required, "boss": boss,
                              "fresh": fresh, "cause": cause, "cause_boss": cause_boss, "from": {"name": name, "account": account,
                              "session": boss["boss-session"], "place": cwd}, "company": company["name"], "role": role},
                             accounts_, sessions_, company["root"], sent)
        if to and dest_inbox and place_dir and (heard or (pending or mid_turn) and wake.has_history(dest_inbox, place_dir)):
            return queue(dept)
        pane, revived = live_window(dept, ports), False
        if pane is None and not a.dry_run:
            # 窓に会話が居ない: 部署の会話が落ちた（PC やサーバーの再起動など）。attach で前の続きから戻す
            pane, said = revive(dept, accounts_, ports, sessions_, company["root"])
            notes.append(said)
            revived = pane is not None
        if pane is None:
            print("\n".join(notes + [f"止めた: 宛先の部署 {where}（{dept['branch']}）の窓に会話が居ない"
                                     + ("（--dry-run なので戻さない。--dry-run を外すと、部署のペインで attach を打って戻す）"
                                        if a.dry_run else "")]))
            return 1
        if pending:
            # 部署は頼みを 1 つずつ受ける（頼み元の属性は 1 組なので、上書きすると前の頼み元に納品が返らない）
            if revived:
                status, detail = deliver.send_confirmed(pane, nudge_line(held, dept["attrs"].get("boss"), ports.now()), ports.term, ports.pause,
                                                        busy_check(dept, accounts_, ports))
                notes.append(f"戻した部署に、受付 {held} の納品を促した（{status}" + (f"。{detail}" if detail else "") + "）")
                print("\n".join(notes + [f"止めた: 宛先の部署 {where} は受付 {held}（頼み元 {dept['attrs'].get('boss') or '-'}）を"
                                         "まだ納品していない。会話が落ちていたので戻して納品を促した。納品が届いてから頼み直す"]))
                return 2
            print("\n".join(notes + [f"止めた: 宛先の部署 {where} は受付 {held}（頼み元 {dept['attrs'].get('boss') or '-'}）を"
                                     f"まだ納品していない。納品を待つか、別の部署に頼む（部署の会話が止まって見えるなら、部署の窓"
                                     f"{f' {pane}' if pane else ''} で続きを頼む）"]))
            return 2
        if a.task or a.branch:
            notes.append(f"宛先の部署 {where} は立っているので、--task・--branch は使わない")
        if a.dry_run:
            line = deliver.ask_line(ask_id, sender, body, os.path.join(inbox, f"{ask_id}-ask.md"), required, RUN)
            print("\n".join(notes + [f"頼む先: {where}  ペイン {pane}", f"打ち込む 1 行: {line}",
                                     "書く属性: " + "、".join(f"company.{k}={v}" for k, v in boss.items() if v)]))
            return 0
        busy = busy_check(dept, accounts_, ports)
        with wake.ask_lock(dest_inbox, place_dir):
            # 錠の中で属性を読み直す。部署を読んでから今までの間に、待ち受けが順番待ちの頼みを渡していれば（属性の頼みが替わった）、
            # 窓に打たない（打つと、この頼みの頼み元が、渡された頼みの頼み元を上書きする。my_notes の受付 20261017-082903-87f45f）
            now = ports.attrs(dept["path"])
            raced = now.get("ask") != held
            if not raced and fresh:
                acc = next((x for x in accounts_ if x.name == dept["attrs"].get("account")), accounts_[0] if len(accounts_) == 1 else None)
                # 記録はペインのシェルで起きた会話のアカウントの下に在る。頼む会話の CLAUDE_CONFIG_DIR（別のアカウント）で探さない
                # （設定のフォルダを書かないアカウントの部署を、別のアカウントの段取りから頼むと、記録が見つからず止まった。
                # my_notes の受付 20261017-075753-01991f）
                ok, said = clear_before_ask(dept, held, pane, busy, ports,
                                            lambda: chat.newest_talk(acc.config_dir if acc else None, dept["path"], ports.account_env))
                notes += said
                if not ok:
                    print("\n".join(notes + [f"止めた: 宛先の部署 {where} は頼みごとに空の会話で受ける役なので、前の会話のままでは送らない"]))
                    return 1
            if not raced:
                path = deliver.put(inbox, f"{ask_id}-ask.md", body)
                line = deliver.ask_line(ask_id, sender, body, path, required, RUN)
                status, detail = deliver.send_confirmed(pane, line, ports.term, ports.pause, busy)
            if not raced and status == "sent":
                # 役の fresh を写す（会社の形を後から変えても、次の頼みから herdr の表示が合う）
                marks = {**boss, "fresh": FRESH if fresh else None, "ask-digest": digest}
                if busy.found and busy.found != dept["attrs"].get("session"):
                    # /clear で変わった会話の id を書き直す（Stop フックの見分けと、落ちたときの attach が古い id を使わない）
                    marks.update(provision.renew_session(dept["attrs"], busy.found))
                try:
                    provision.mark(dept["path"], company["root"], marks, ports.git)   # 値の無い頼み元の属性は消える（前の頼み元を残さない）
                except (gitx.GitError, OSError) as e:
                    notes.append(f"宛先の部署に頼みの属性を書けなかった（{e}）。納品のコマンドが頼み元を見つけられず、Stop フックが効かない")
        if raced:   # 順番待ちに積むのは錠の外で（積む道は窓を戻したり打ったりするので、その間待ち受けを止めない）
            dept = {**dept, "attrs": now}
            if wake.pending(now) and now.get("ask-digest") == digest:
                sent.update(id=now["ask"], to={"company": company["name"], "name": now.get("name"), "role": role})
                print("\n".join(notes + [f"頼み {now['ask']} → {where}  同じ中身の頼みが動いている（新しく積まない）"]))
                return 0
            if to and dest_inbox and place_dir and wake.has_history(dest_inbox, place_dir):
                return queue(dept)
            print("\n".join(notes + [f"止めた: 宛先の部署 {where} は、読んでから打つまでの間に受付 {now.get('ask')}（頼み元 "
                                     f"{now.get('boss') or '-'}）を受けた。納品を待つか、別の部署に頼む"]))
            return 2
        deliver.log(inbox, {"id": ask_id, "kind": "ask", "at": ports.now(), "status": status, "detail": detail, "cause": cause,
                            **({"cause_boss": cause_boss} if cause_boss else {}),
                            "from": {"name": name, "account": account, "session": boss["boss-session"], "place": cwd},
                            "to": {"company": company["name"], "name": dept["attrs"].get("name"), "role": role,
                                   "branch": dept["branch"], "path": dept["path"], "pane": pane}, "file": path, "title": title})
        if status == "sent":
            sent.update(id=ask_id, to={"company": company["name"], "name": dept["attrs"].get("name"), "role": role})
        print("\n".join(notes + [f"頼み {ask_id} → {where}  {status}" + (f"（{detail}）" if detail else ""),
                                 f"- 本文: {path}"]))
        return 0 if status == "sent" else 1
    # 宛先の役の部署が無い: 頼みごとに新しい部署を立てる（会社の形の設計 4.10 の 2。ブランチの名前は頼む側が渡す）
    if target.get("on_demand"):
        # オンデマンドの受け持ち: 部署の名前は受け持ちの名前、ブランチは受付番号から作る（--task・--branch を渡さなくてよい）。
        # 部署はエフェメラルの部署で立ち（dispatch._task が受け持ちの on_demand を見る）、納品してメインブランチに入れたら --done で畳まれる
        a = argparse.Namespace(**{**vars(a), "task": target["on_demand"], "branch": a.branch or f"work/ask-{ask_id[-6:]}"})
        notes.append(f"{target['on_demand']} はオンデマンドの受け持ち（頼まれたときだけ立てる）なので、部署 {a.task}（ブランチ {a.branch}）を立てる")
    if not (a.task and a.task.strip() and a.branch):
        print("\n".join(notes + [f"止めた: {company['name']} に役「{role}」の永続の部署が無いので新しく立てる。"
                                 "部署の名前を --task <名前>、ブランチを --branch <ブランチ> で渡す"]))
        return 2
    if cfg is None:
        print("\n".join(notes + ["止めた: 部署を立てるには、読める dispatch の設定が要る（アカウントと使用率の上限を読む。"
                                 "ファイルが無ければ既定で動くが、在って読めない物は直す）"]))
        return 2
    repo = config.repo_at(cfg, company["root"], ports.origin)
    if own_branch(cwd, a.branch, repo.source, ports.git):
        # 部署はブランチの作業場で起動するので、頼んだ会話の居るブランチには立たない。前は立てる道が「会話がもう開いている」で
        # 何もせず、台帳に訳の無い failed を残し、会話は道を持ち主に問い直した（3d3ccc）
        print("\n".join(notes + [f"止めた: ブランチ {a.branch} は、この頼みを打った会話の居る作業場 {cwd} が開いている。部署は"
                                 "ブランチの作業場で起動するので、同じブランチには立てない。この会話がそのブランチの作業場に居るので、"
                                 "部署を立てずにこの会話で進める（別の仕事なら別の --branch で頼む）"]))
        return 2
    if a.dry_run:
        print("\n".join(notes + [f"頼む先: {company['name']} に部署 {a.task}（役 {role}、ブランチ {a.branch}）を立て、最初の文で頼む",
                                 f"- 受付箱: {inbox}",
                                 "- 書く属性: " + "、".join(f"company.{k}={v}" for k, v in boss.items() if v)]))
        return 0
    path = deliver.put(inbox, f"{ask_id}-ask.md", body)
    ns = argparse.Namespace(**{**vars(a), "brief": path, "role": role})
    said = io.StringIO()
    try:
        with contextlib.redirect_stdout(said):
            rc = task(cfg, repo, ns, ports, extra_attrs=boss, tail=deliver.tail(required, RUN), refreshed=True)
    finally:
        sys.stdout.write(said.getvalue())   # 立てる道が誤りで抜けても、そこまでに書いた物を捨てない
    try:
        got = next((p for p in ports.places(repo) if p.get("branch") == a.branch), None)
    except term.Error as e:
        got = None
        notes.append(f"立てた後に部署の場所を読めない（{e}）")
    attrs = ports.attrs(got["path"]) if got else {}
    status = "sent" if attrs.get("ask") == ask_id and attrs.get("session") else "failed"
    deliver.log(inbox, {"id": ask_id, "kind": "ask", "at": ports.now(), "status": status,
                        "detail": None if status == "sent" else (why_not(said.getvalue()) or f"rc={rc}"),
                        "cause": cause, **({"cause_boss": cause_boss} if cause_boss else {}),
                        "from": {"name": name, "account": account, "session": boss["boss-session"], "place": cwd},
                        "to": {"company": company["name"], "name": a.task, "role": role, "branch": a.branch,
                               "path": got and got["path"], "pane": None}, "file": path, "title": title})
    if status == "sent":
        sent.update(id=ask_id, to={"company": company["name"], "name": a.task, "role": role})
    print("\n".join(notes + [f"頼み {ask_id} → {company['name']}/{a.task}（新しく立てた部署）  {status}", f"- 本文: {path}"]))
    return rc if status == "sent" else (rc or 1)


def own_branch(cwd, branch, source, g=gitx):
    """頼んだ会話の居る場所（cwd）が、同じリポジトリのブランチの作業場（linked worktree）で、そのブランチ（branch）を開いているか。"""
    common, theirs = g.common_dir(cwd), g.common_dir(source)
    if not common or not theirs or os.path.realpath(common) != os.path.realpath(theirs):
        return False
    return g.is_main_worktree(cwd) is False and g.branch(cwd) == branch


def why_not(said):
    """部署を立てる道（dispatch._task）が画面に書いた物から、立たなかった訳の 1 行（台帳の detail）。止めた行が有ればその最後、
    無ければ箇条（「- 」で始まる行）でない行を「；」でつないだ物（起動に失敗した訳は要約の行より前の行に在る）。何も書いていなければ None。"""
    lines = [x.strip() for x in said.splitlines() if x.strip()]
    told = [x for x in lines if not x.startswith("- ")]
    return next((x for x in reversed(lines) if x.startswith("止めた")), None) or ("；".join(told) or None)


def cause_of(a, here, ports):
    """頼みの行の cause（この頼みを打った場所が、そのとき受けていて、まだ納品していない頼みの受付。台帳の頼みの木の親。
    docs/ledger.md）。合図で回した頼みは、メインブランチに入れた部署の頼み。受けている頼みが無い場所（窓口・持ち主の会話）は None。"""
    boss = getattr(a, "from_boss", None) or {}
    if boss.get("ask"):
        return boss["ask"]
    try:
        attrs = ports.attrs(here) or {}
    except (gitx.GitError, OSError):
        return None
    held = attrs.get("ask")
    return held if held and attrs.get("delivered") != held else None


def cause_boss_of(a, here, ports, cause):
    """頼みの行の cause_boss（cause の頼みの頼み元。forwarded の行の boss と同じ形）か None。子の頼みの答えを --deliver --for で
    元の頼み元へ返すときに引く（元の頼みの頼み元は、部署の属性が次の頼みで書き替わると、ほかに残らない）。"""
    if not cause:
        return None
    boss = getattr(a, "from_boss", None) or {}
    if boss.get("ask") != cause:
        try:
            boss = ports.attrs(here) or {}
        except (gitx.GitError, OSError):
            return None
        if boss.get("ask") != cause:
            return None
    if not (boss.get("boss") or boss.get("boss-session")):
        return None   # 頼み元の分からない頼み: 中身の無い写しを書かない（--for は元の頼みの行から引き直す）
    return {"name": boss.get("boss"), "session": boss.get("boss-session"), "account": boss.get("boss-account"),
            "pane": boss.get("boss-pane"), "inbox": boss.get("boss-inbox")}


def queue_ask(a, ports, notes, where, dept, dest_inbox, place_dir, to, heard, digest, ask, accounts_, sessions_, source, sent):
    """待ち受けの居る部署への --ask: 順番待ちに積み（同じ中身が積まれていればその受付番号を返す）、宛先の会社の台帳に知らせを
    足す。渡すのは部署の待ち受け（wake_hook.py）。会話が落ちていれば attach で戻す（戻った会話の始まりの待ち受けが渡す）。
    積んだ（か同じ中身が積まれていた）なら、sent にその頼みの id と宛先を書く。"""
    waiting = wake.queued(dest_inbox, place_dir)
    same = next((q for q in waiting if q.get("digest") == digest), None)
    dest = {"company": ask["company"], "name": dept["attrs"].get("name"), "role": ask["role"]}
    if same:
        sent.update(id=same.get("id"), to=dest)
        if not a.dry_run:
            notes += wake_stuck(dept, where, dest_inbox, place_dir, accounts_, ports, sessions_, source)
        print("\n".join(notes + [f"頼み {same.get('id')} → {where}  同じ中身の頼みが順番待ちに積まれている（新しく積まない）"]))
        return 0
    file = os.path.join(ask["inbox"], f"{ask['id']}-ask.md")
    if a.dry_run:
        line = deliver.ask_line(ask["id"], ask["sender"], ask["body"], file, ask["required"], RUN)
        print("\n".join(notes + [f"頼む先: {where}  順番待ちに積む（{len(waiting) + 1} 件目。"
                                 + ("待ち受けが渡す）" if heard else "今の頼みの納品の後に待ち受けが渡す）"),
                                 f"順番待ち: {wake.queue_dir(dest_inbox, place_dir)}", f"会話に渡す 1 行: {line}",
                                 "渡すときに書く属性: " + "、".join(f"company.{k}={v}" for k, v in ask["boss"].items() if v)]))
        return 0
    path = deliver.put(ask["inbox"], os.path.basename(file), ask["body"])
    line = deliver.ask_line(ask["id"], ask["sender"], ask["body"], path, ask["required"], RUN)
    marks = {**ask["boss"], "fresh": FRESH if ask["fresh"] else None, "ask-digest": digest}
    wake.enqueue(dest_inbox, place_dir, {"id": ask["id"], "to": to, "file": path, "line": line, "digest": digest, "marks": marks,
                                         "at": ports.now(), "from": ask["sender"], "title": ask.get("title")})
    deliver.log(dest_inbox, wake.notice(to, ask["id"], wake.QUEUED, path, None, ports.now()))
    if not heard and live_window(dept, ports) is None:
        notes.append(revive(dept, accounts_, ports, sessions_, source)[1])
    elif heard:   # 会話の処理は生きている（ターンの途中で待ち受けが居ないのは、ターンの終わりに張られる）
        notes += wake_stuck(dept, where, dest_inbox, place_dir, accounts_, ports, sessions_, source)
    n = len(wake.queued(dest_inbox, place_dir))
    detail = f"順番待ちに積んだ（{n} 件目。{'待ち受けが渡す' if heard else '今の頼みの納品の後に待ち受けが渡す'}）"
    deliver.log(ask["inbox"], {"id": ask["id"], "kind": "ask", "at": ports.now(), "status": "queued", "detail": detail,
                               "cause": ask.get("cause"), **({"cause_boss": ask["cause_boss"]} if ask.get("cause_boss") else {}),
                               "from": ask["from"], "to": {"company": ask["company"], "name": dept["attrs"].get("name"),
                                                          "role": ask["role"], "branch": dept["branch"], "path": dept["path"],
                                                          "pane": None, "wake": to}, "file": path, "title": ask.get("title")})
    sent.update(id=ask["id"], to=dest)
    print("\n".join(notes + [f"頼み {ask['id']} → {where}  {detail}", f"- 本文: {path}"]))
    return 0


POSTED = "posted"   # 納品の台帳の status: 頼み元の窓が無いので、頼み元の名前に宛てた知らせを台帳に置いた（納品済みにする）

# 順番待ちが渡らずに止まった部署の会話に打つ 1 行（wake_stuck）。ターンを 1 つ回すだけで、返事も仕事も要らない
STUCK_LINE = ("順番待ちの知らせです: この部署の順番待ちが渡らずに止まっていたので、ターンを 1 つ回す。返事は要らない。受けている頼みが"
              "途中なら、それを続ける。無ければ何もせずにこのターンを終える（ターンの終わりに待ち受けが張り直して、次の頼みを渡す）。")


def stuck_why(dest_inbox, place_dir, dept):
    """部署の順番待ちが渡らずに止まっていれば、その訳。止まっていなければ None。止まり方は 2 つ: ターンを終えたのに渡す待ち受けが居ない
    （wake.stalled）と、待ち受けは居るが渡さずに待っている（wake.held。台帳の最後の行が held）。"""
    if wake.stalled(dest_inbox, place_dir, dept["attrs"]):
        return "渡す待ち受けが居ない"
    why = wake.held(dest_inbox, dept["path"], place_dir, dept["attrs"])
    return f"待ち受けが渡さずに待っている（{why}）" if why else None


# 待ち受けが渡さずに待つ訳のうち、すぐ替わる物（待ち受けが 5 秒ごとに試し直して自分で抜ける）。この訳では窓に打たない（待ち受けの
# /clear と打ち込みがぶつからないように）。中身は wake_hook.clear_now の訳の頭（窓の入力フィールドが見えない・打ちかけの字が在る）。
# 子の頼みの返事待ちと裏の処理は、何時間も替わらないことがあるので入れない（今の版の待ち受けはこの 2 つでは止めずに渡す。台帳にこの
# 訳が在れば前の版の待ち受けなので、プラグインを読み直させてから 1 行打ってターンを回し、今の版の待ち受けに張り替える。2026-10-18 に
# claude-plugins の割り振りが子の頼みの返事待ちで半日止まり、--nudge が「訳がすぐ替わる」で何もしなかった）
PASSING = ("会話がまだ動いている", "窓の入力フィールド")
# 人の文でターンが始まると外れる印（wake_hook.resume_from_wait）。STUCK_LINE は人の文ではないので、打った後に書き戻す
KEPT_MARKS = ("rest", "waiting", "waiting-why", "finished")


def _free(pane, ports):
    """窓の会話の手が空いていて（idle か done）、入力フィールドが見えて空か。読めなければ term.Error を投げる。"""
    status = (ports.term.agent(pane) or {}).get("agent_status")
    return status in ("idle", "done") and chat.typed(ports.term.read(pane, 40, ansi=True)) == ""


def _put_back(dept, keep, ports, detail):
    """窓に打った字で外れうる印（KEPT_MARKS のうち打つ前に在った物 keep）を書き戻す。書き戻せなければその訳を detail に足して返す。"""
    if not keep:
        return detail
    try:
        provision.mark(dept["path"], gitx.root_of(ports.git.common_dir(dept["path"])), keep, ports.git)
    except (gitx.GitError, OSError) as e:
        return f"{detail + '。' if detail else ''}外れた印（{'・'.join(keep)}）を書き戻せなかった（{e}）"
    return detail


def wake_stuck(dept, where, dest_inbox, place_dir, accounts_, ports, sessions_=None, source=None, moved=None):
    """順番待ちが渡らずに止まった部署（stuck_why）を、人の手なしに動かす。出す注記の並びを返す（止まっていなければ空）。
    - 窓に会話が居なければ（live_window）、attach で戻す（revive。戻った会話の始まりの待ち受けが渡す）。
    - 窓に会話が居て、手が空いていて（herdr の状態が idle か done）入力フィールドが空なら、プラグインを読み直させ（deliver.reload_talk）、
      STUCK_LINE を 1 行打ってターンを 1 つ回す。ターンの初めに前の待ち受けが止まり（--pause）、ターンの終わりに今の版の待ち受けが張り直して、
      空にしてから次を渡す。読み直させるのは、会話が前の版のプラグインのままだと、ターンの終わりに張り直すのも前の版の待ち受けで、同じ訳で
      また止めるため（2026-10-19 の 06:04 に割り振りへ打った 1 行は、11 秒後に同じ訳で止まった。配るツールが読み直させた後の 06:07 に
      打ち直して渡った）。読み直しは待っている待ち受けを止めないので、読み直しだけでは足りず、1 行で次のターンを回す。前の版かは外から
      確かには分からない（窓の前に見えるのは裏の会話へ attach した処理で、裏の会話の処理が起きた時刻が分からない）ので、版を見分けずに
      毎回打つ（今の版の会話に打っても、ターンを始めず会話も消さず、読み直すだけで害は無い）。読み直しの後は、1 拍おいて手が空いて入力
      フィールドが空なのをもう一度見てから 1 行を打ち、見られなければ打たない（読み直しを待つ間に人が打ち始めた字に 1 行を足さない）。
    - 会話が動いている・入力フィールドに字が在るとき、待ち受けが渡さない訳がすぐ替わる物（PASSING）のときは打たない（ターンの終わりに待ち受けが
      張り直すか、待ち受けが自分で抜ける。人の打ちかけの字と待ち受けの /clear を壊さない）。
    打ったか戻したかは受付箱の台帳に kind nudged で残し、動かしたら moved（並び）に True を足す。打った字で外れる印（KEPT_MARKS）は、
    1 行を打たずに終えたときも書き戻す。以前は「部署の窓に 1 文打つ」と持ち主に打たせていた（2026-10-17 の割り振り・説明書）。"""
    why = stuck_why(dest_inbox, place_dir, dept)
    if not why:
        return []
    head = f"宛先の部署 {where} の順番待ちが止まっていた（{why}）"
    first_id = (wake.queued(dest_inbox, place_dir) or [{}])[0].get("id")
    pane = live_window(dept, ports)
    if pane is None:
        pane, said = revive(dept, accounts_, ports, sessions_, source)
        deliver.log(dest_inbox, {"id": first_id, "kind": "nudged", "at": ports.now(), "place": dept["path"], "pane": pane,
                                 "why": why, "status": "revived" if pane else "failed", "detail": said})
        if pane and moved is not None:
            moved.append(True)
        return [f"{head}。{said}"]
    if any(x in why for x in PASSING):
        return [f"{head}。訳がすぐ替わる物なので打たなかった（待ち受けが 5 秒ごとに試し直す）"]
    again = f"--nudge {dept['attrs'].get('name') or where} で打ち直す"
    try:
        free = _free(pane, ports)
    except term.Error as e:
        return [f"{head}。窓 {pane} を読めないので打たなかった（{e}）。{again}"]
    if not free:
        return [f"{head}。会話が動いているか入力フィールドに字が在るので打たなかった（ターンの終わりに待ち受けが張り直す。止まったままなら "
                f"{again}）"]
    keep = {k: dept["attrs"][k] for k in KEPT_MARKS if dept["attrs"].get(k)}
    reloaded, detail = deliver.reload_talk(pane, ports.term, ports.pause)
    if reloaded == "sent":
        # 読み直しを待つ間に人が打ち始めたか、会話が動き出したなら、1 行を人の字に足さない（入力フィールドから出たのは受け付けた印でしか
        # なく、読み直しの済んだ印ではないので、1 拍おいて手が空いて入力フィールドが空なのをもう一度見る）
        ports.pause()
        try:
            free = _free(pane, ports)
        except term.Error as e:
            free, detail = False, str(e)
        if not free:
            reloaded, detail = "failed", detail or f"{chat.RELOAD} の後に、会話が動き出したか入力フィールドに字が入った"
    if reloaded != "sent":
        detail = _put_back(dept, keep, ports, detail)
        deliver.log(dest_inbox, {"id": first_id, "kind": "nudged", "at": ports.now(),
                                 "place": dept["path"], "pane": pane, "why": why, "status": "failed", "detail": detail})
        return [f"{head}。窓 {pane} で {chat.RELOAD} の後に手が空いて入力フィールドが空なのを見られないので、1 行を打たなかった（{detail}。"
                f"部署の窓を見て、{again}）"]
    sent, detail = deliver.send_confirmed(pane, STUCK_LINE, ports.term, ports.pause, busy_check(dept, accounts_, ports))
    detail = _put_back(dept, keep, ports, detail)
    deliver.log(dest_inbox, {"id": first_id, "kind": "nudged", "at": ports.now(),
                             "place": dept["path"], "pane": pane, "why": why, "status": sent, "detail": detail})
    if sent == "sent" and moved is not None:
        moved.append(True)
    return [f"{head}。窓 {pane} で {chat.RELOAD} を打ち、1 行打ってターンを回した（{sent}" + (f"。{detail}" if detail else "") + "）。ターンの終わりに待ち受けが渡す"]


def nudge(a, ports, cwd):
    """--nudge <部署>。順番待ちが渡らずに止まった部署を動かす（wake_stuck）。--ask が止まった部署に積むときは同じことを自分でする
    ので、これは頼みを足さずに動かす口（段取りが --tree の「止まっている」を見て打つ）。終了の値を返す。"""
    common = ports.git.common_dir(cwd)
    try:
        cfg, accounts_, sessions_, panes, companies, settings, notes = survey(a.config, ports)
        target = deliver.find_target(companies, gitx.root_of(common) if common else None, a.nudge, None, current_role(settings))
    except term.Error as e:
        print(f"止めた: {term.NAME} を読めない（{e}）")
        return 1
    except deliver.DeliverError as e:
        print(f"止めた: {e}")
        return 2
    company, dept = target["company"], target["department"]
    where = f"{company['name']}/{(dept or {}).get('attrs', {}).get('name') or a.nudge}"
    dest_common = ports.git.common_dir(company["root"])
    place_dir = ports.git.git_dir(dept["path"]) if dept else None
    if not (dest_common and place_dir):
        print("\n".join(notes + [f"止めた: 「{a.nudge}」という立っている部署が無い"]))
        return 2
    dest_inbox = deliver.inbox_of(dest_common)
    why = stuck_why(dest_inbox, place_dir, dept)
    if not why:
        n = len(wake.queued(dest_inbox, place_dir))
        print("\n".join(notes + [f"{where} の順番待ち（{n} 件）は止まっていない（" + ("待ち受けが渡す）" if n else "順番待ちが空）")]))
        return 0
    if a.dry_run:
        print("\n".join(notes + [f"{where} の順番待ちが止まっている（{why}）。窓に会話が居なければ attach で戻し、居ればプラグインを読み直させてから 1 行打ってターンを回す"]))
        return 0
    moved = []
    print("\n".join(notes + wake_stuck(dept, where, dest_inbox, place_dir, accounts_, ports, sessions_, company["root"], moved)))
    return 0 if moved else 1


def _queue_inbox(item):
    """順番待ちの件のファイル（<受付箱>/queue/<場所の鍵>/<受付>.json）から、その受付箱。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(item["path"])))


def _forwarded_to(ask_id, ports, cwd, companies):
    """受付 ask_id が回して閉じた頼み（台帳に kind forwarded の行が在る）なら、回した先をたどった、まだ終わっていない頼みの受付の
    並び（台帳の射影の nodes/ledger。docs/ledger.md）。回していなければ None。台帳は打った場所の会社と herdr に開いている会社の物から、
    --todo と同じく行が指すほかの会社の受付箱へたどる（開いていない会社にだけ在る回した先も見つける）。"""
    rows = _ledger(ports, cwd, companies)[1]
    if not any(r.get("kind") == "forwarded" and r.get("id") == ask_id for r in rows):
        return None
    return [i for i in ledger.forwarded_open(ledger.build(rows), ask_id) if i != ask_id]


def _ledger(ports, cwd, companies):
    """打った場所の会社と herdr に開いている会社の受付箱から、--todo と同じく行が指すほかの会社の受付箱へたどった (受付箱の並び, 全部の行)。"""
    inboxes = [deliver.inbox_of(got) for got in [ports.git.common_dir(cwd)] + [ports.git.common_dir(c["root"]) for c in companies] if got]
    return todo.inboxes_from(inboxes, ports.git.common_dir)


def _find_queued(ask_id, config_path, ports, cwd, companies=None):
    """受付 ask_id の順番待ちの件を、打った場所の会社と herdr に開いている会社の受付箱から探す。(件か None, 注記)。
    companies（survey の会社の並び）を渡せば herdr を読み直さない。"""
    inboxes, notes = [], []
    common = ports.git.common_dir(cwd)
    if common:
        inboxes.append(deliver.inbox_of(common))
    if companies is None:
        try:
            companies = survey(config_path, ports)[4]
        except term.Error as e:
            companies = []
            notes.append(f"{term.NAME} を読めないので、打った場所の会社の順番待ちだけを探した（{e}）")
    for c in companies:
        got = ports.git.common_dir(c["root"])
        if got:
            inboxes.append(deliver.inbox_of(got))
    for inbox in dict.fromkeys(inboxes):
        item = wake.find(inbox, ask_id)
        if item:
            return item, notes
    return None, notes


def _log_taken(item, record, also=()):
    """順番待ちから取った知らせを、順番待ちの在る受付箱と頼み元の受付箱（と also の受付箱）の台帳に足す（取り下げと回した先を
    両方に残す）。記録の行なので、to は辞書にする（to が字の行は待ち受けが知らせと読み、宛先の会話を再開させる。設計の 3.1）。"""
    boss_inbox = (item.get("marks") or {}).get("boss-inbox")
    _log_each([_queue_inbox(item), boss_inbox, *also], record)


def _log_each(inboxes, record):
    """在る受付箱のそれぞれの台帳に 1 行ずつ足す（同じ受付箱には 1 行だけ）。"""
    for inbox in dict.fromkeys(x for x in inboxes if x and os.path.isdir(x)):
        deliver.log(inbox, record)


def take(a, ports, cwd, task):
    """--take <受付>。順番待ちの 1 件を、積んだ順を飛ばして取り出す（2d707e）。--ask を添えなければ、打った部署（その順番待ちの
    持ち主）が今受ける（待ち受けが渡すときと同じに、頼み元の属性を書いて頼みの 1 行を出す）。--ask <宛先>（と --task・--branch）を
    添えれば、受付番号と頼み元をそのままに、ほかの部署に頼み直す（担当が手一杯のときに、受け持ちの名前の付いた作業へ回す。納品は
    元の頼み元に返る）。--text は回す側の添え書きで、元の本文の前に置く。取り出しと回した先は台帳に kind taken で残す。終了の値を返す。"""
    if a.ask is None:
        return _take_here(a, ports, cwd)
    item, notes = _find_queued(a.take, a.config, ports, cwd)
    if item is None:
        print("\n".join(notes + [f"止めた: 受付 {a.take} はどの順番待ちにも無い（もう渡ったか、取り下げられた）"]))
        return 2
    if a.dry_run:
        print("\n".join(notes + [f"受付 {a.take} を順番待ち（{os.path.dirname(item['path'])}）から取り、{a.ask} に頼み直す"
                                 f"（頼み元 {(item.get('marks') or {}).get('boss') or '-'} はそのまま）"]))
        return 0
    if not wake.pull(item):
        print("\n".join(notes + [f"止めた: 受付 {a.take} はほかが先に取った"]))
        return 2
    marks = item.get("marks") or {}
    brief = item.get("file")
    if a.text:
        # 回す側の添え書き（担当が回したこと・避けるファイルなど）を、元の頼みの本文の前に置く
        try:
            body = pathlib.Path(brief).read_text(encoding="utf-8")
        except (OSError, TypeError) as e:
            wake.put_back(item)
            print(f"止めた: 受付 {a.take} の頼みのファイルを読めないので、元の順番待ちに戻した（{e}）")
            return 2
        common = ports.git.common_dir(cwd)
        brief = deliver.put(deliver.inbox_of(common) if common else _queue_inbox(item), f"{item.get('id')}-ask.md",
                            deliver.wrap(a.text, body))
    ns = argparse.Namespace(**{**vars(a), "brief": brief, "text": None, "ask_id": item.get("id"), "title": item.get("title"),
                               "from_boss": {k: v for k, v in marks.items() if k == "boss" or k.startswith("boss-")}})
    rc = ask(ns, ports, cwd, task)
    if rc != 0:
        wake.put_back(item)
        print(f"受付 {a.take} を {a.ask} に頼み直せなかったので、元の順番待ちの同じ場所に戻した")
        return rc
    _log_taken(item, {"id": item.get("id"), "kind": "taken", "at": ports.now(), "from": os.path.dirname(item["path"]),
                      "to": {"ask": a.ask}, "name": a.task, "by": {"session": chat.session_of(ports.env), "place": cwd}})
    return 0


def _take_here(a, ports, cwd):
    common = ports.git.common_dir(cwd)
    attrs = ports.attrs(cwd) if common else {}
    if not attrs.get("role"):
        print(f"止めた: {cwd} は部署でも窓口でもない（git の設定 company.role が無い）。ほかの部署の順番待ちから回すなら --ask <宛先> を添える")
        return 2
    inbox, place_dir = deliver.inbox_of(common), ports.git.git_dir(cwd)
    with wake.ask_lock(inbox, place_dir):   # 待ち受けが同じ間に順番待ちの頼みを渡して、属性を書き換えないように
        return _take_locked(a, ports, cwd, common, inbox, place_dir)


def _take_locked(a, ports, cwd, common, inbox, place_dir):
    attrs = ports.attrs(cwd)
    held = wake.pending(attrs)
    if held:
        print(f"止めた: 受付 {held} をまだ納品していない（頼み元の属性は 1 組なので、納品してから取る。今の頼みを手放して回すなら、"
              f"ほかの部署から --take {a.take} --ask <宛先>）")
        return 2
    item = wake.find(inbox, a.take)
    if item is None or os.path.dirname(item["path"]) != wake.queue_dir(inbox, place_dir):
        print(f"止めた: 受付 {a.take} はこの部署の順番待ちに無い（ほかの部署の物を回すなら --ask <宛先> を添える）")
        return 2
    skipped = [q.get("id") for q in wake.queued(inbox, place_dir)]
    skipped = skipped[:skipped.index(a.take)] if a.take in skipped else []
    if a.dry_run:
        print(f"受付 {a.take} を順番待ちから取り、この部署で今受ける（先に積まれた {len(skipped)} 件を飛ばす）")
        return 0
    if not wake.pull(item):
        print(f"止めた: 受付 {a.take} はほかが先に取った")
        return 2
    provision.mark(cwd, gitx.root_of(common), item.get("marks") or {}, ports.git)
    _log_taken(item, {"id": item.get("id"), "kind": "taken", "at": ports.now(), "from": os.path.dirname(item["path"]),
                      "to": {"name": attrs.get("name"), "role": attrs.get("role")}, "skipped": skipped, "by": {"session": chat.session_of(ports.env), "place": cwd}})
    print("\n".join([f"受付 {a.take} を順番待ちから取った（先に積まれた {len(skipped)} 件" + (f"〔{'・'.join(skipped)}〕" if skipped else "")
                      + "は順番待ちに残る）。この頼みを今受ける:", item.get("line") or wake.wake_text([item])]))
    return 0


def withdraw(a, ports, cwd):
    """--withdraw <受付>。順番待ちの 1 件を取り下げる（渡さずに消し、順番待ちの在る受付箱と頼み元の受付箱の台帳に kind withdrawn で
    残す。頼み元が取り下げを頼んだときや、段取りが同じ頼みを別の道で出し直したとき）。順番待ちに無ければ、台帳がまだ開いていると
    出す頼みを、取り下げの行を足して閉じる（_withdraw_stray）。終了の値を返す。"""
    try:
        companies, notes = survey(a.config, ports)[4], []
    except term.Error as e:
        companies, notes = [], [f"{term.NAME} を読めないので、打った場所の会社と、その台帳がたどれる会社だけを探した（{e}）"]
    item = _find_queued(a.withdraw, a.config, ports, cwd, companies)[0]
    found = rows = None
    if item is None:   # herdr に開いていない会社の順番待ちも、台帳がたどれれば探す
        found, rows = _ledger(ports, cwd, companies)
        item = next((got for got in (wake.find(x, a.withdraw) for x in found) if got), None)
    if item is None:
        return _withdraw_stray(a, ports, cwd, found, rows, notes)
    if a.dry_run:
        print("\n".join(notes + [f"受付 {a.withdraw} を順番待ち（{os.path.dirname(item['path'])}）から取り下げる"]))
        return 0
    if not wake.pull(item):
        print("\n".join(notes + [f"止めた: 受付 {a.withdraw} はほかが先に取った"]))
        return 2
    _log_taken(item, {"id": item.get("id"), "kind": "withdrawn", "at": ports.now(), "from": os.path.dirname(item["path"]),
                      "by": {"session": chat.session_of(ports.env), "place": cwd}})
    print("\n".join(notes + [f"受付 {a.withdraw} を順番待ちから取り下げた（台帳に残した）"]))
    return 0


def _withdraw_stray(a, ports, cwd, found, rows, notes):
    """順番待ちに無いのに、台帳の射影が開いている（順番待ち・動いている・答え待ち）と出す頼みを、取り下げの行を足して閉じる。
    台帳に閉じる行の無いまま、順番待ちの件が消えた（--withdraw の無かった 2026-10-17 の朝に、段取りが my_notes の 6 件を手で
    動かした）か、受けた部署の作業場が納品せずに消えた（my_notes の 75aeee）頼みで、閉じないと --todo に開いている物として残り続ける。
    古い行は書き換えず、行を足す（docs/ledger.md）。行には前の状態（was）と訳（why）を書く。受けた部署がまだその頼みを受けていれば
    （属性の頼みがその受付で、まだ納品していない）閉じない。確かめと書き込みは、その部署の待ち受けと同じ錠の中でする（待ち受けは
    順番待ちの件を消してから属性を書くので、その間に確かめると、渡している最中の頼みを閉じてしまう）。"""
    i = a.withdraw
    t = ledger.build(rows)["tasks"].get(i)
    if t is None:
        print("\n".join(notes + [f"止めた: 受付 {i} はどの順番待ちにも、読んだ台帳にも無い（短い 6 桁でなく、長い受付番号で渡す）"]))
        return 2
    if t["state"] not in ("queued", "working", "waiting"):
        print("\n".join(notes + [f"止めた: 受付 {i} はどの順番待ちにも無く、台帳ではもう閉じている（{t['label']}）"]))
        return 2
    place = ledger.received_at(rows, i)
    there = bool(place) and os.path.isdir(place)
    common = ports.git.common_dir(place) if there else None
    lock = wake.ask_lock(deliver.inbox_of(common), ports.git.git_dir(place)) if common else contextlib.nullcontext()
    with lock:
        if there and wake.pending(ports.attrs(place)) == i:
            print("\n".join(notes + [f"止めた: 受付 {i} は {place} の部署がまだ受けている（取り下げるなら、その旨を --note {i} で足す）"]))
            return 2
        why = ("順番待ちの置き場に無い" if t["state"] == "queued" else
               f"受けた作業場 {place} がもう無い" if place and not there else
               f"受けた作業場 {place} の部署は、今はこの頼みを受けていない" if place else "受けた作業場が台帳に無い")
        if a.dry_run:
            print("\n".join(notes + [f"受付 {i} は、{why}ので、台帳で「{t['label']}」と出る頼みを取り下げで閉じる"]))
            return 0
        # 頼みの行の在る受付箱のそれぞれに足す（頼んだ会社と受けた会社）
        _log_each([x for x in found if any(ledger.subject(r) == i for r in deliver.records(x))],
                  {"id": i, "kind": "withdrawn", "at": ports.now(), "was": t["state"], "why": why,
                   "by": {"session": chat.session_of(ports.env), "place": cwd}})
    print("\n".join(notes + [f"受付 {i} は、{why}ので、台帳で「{t['label']}」と出る頼みを取り下げで閉じた（台帳に行を足した）"]))
    return 0


def first(a, ports, cwd):
    """--first <受付>。順番待ちの 1 件を、その順番待ちの先頭に回す（急ぐ物を先にする。渡すのは今までどおり待ち受けで、今の頼みの
    納品の後）。後から回した物ほど前に並ぶ。台帳に kind reordered で、追い越した件と一緒に残す。終了の値を返す。"""
    item, notes = _find_queued(a.first, a.config, ports, cwd)
    if item is None:
        print("\n".join(notes + [f"止めた: 受付 {a.first} はどの順番待ちにも無い（もう渡ったか、取り下げられた）"]))
        return 2
    line = [q.get("id") for q in wake.listed(os.path.dirname(item["path"]))]
    passed = line[:line.index(a.first)] if a.first in line else []
    if a.dry_run:
        print("\n".join(notes + [f"受付 {a.first} を順番待ち（{os.path.dirname(item['path'])}）の先頭に回す（{len(passed)} 件を追い越す）"]))
        return 0
    if not wake.pull(item):
        print("\n".join(notes + [f"止めた: 受付 {a.first} はほかが先に取った"]))
        return 2
    wake.put_back({**item, "front": ports.now()})
    _log_taken(item, {"id": item.get("id"), "kind": "reordered", "at": ports.now(), "from": os.path.dirname(item["path"]),
                      "passed": passed, "by": {"session": chat.session_of(ports.env), "place": cwd}})
    print("\n".join(notes + [f"受付 {a.first} を順番待ちの先頭に回した（{len(passed)} 件" + (f"〔{'・'.join(passed)}〕" if passed else "")
                              + "を追い越した。台帳に残した）。今の頼みの納品の後に待ち受けが渡す"]))
    return 0


def note_line(ask_id, note_id, sender, text, file):
    """今受けている頼みへの足しを、部署の会話に渡す 1 行。短い文は本文ごと、長い物は受付箱のファイルを指す。"""
    body = text if text and "\n" not in text and len(text) <= deliver.SHORT_TEXT else f"{file} を読む。"
    return (f"頼みの足しです（受付 {ask_id} への、{sender} から。足しの受付 {note_id}）: {body} "
            "今の頼みの進め方に入れて続ける（足しに別の納品はしない。今の頼みの納品にまとめる。取り下げなら、そこで止めて、"
            "どこまで済んだかを納品で返す）。")


def note(a, ports, cwd):
    """--note <受付>（--text か --brief）。受付の頼みに、変更・足し・取り下げを届ける。順番待ちに積まれていれば、その件に足しを
    添える（渡すときに頼みの 1 行と一緒に出る）。部署が今受けている（未納品の）頼みなら、宛先の会社の台帳に足しの知らせ
    （kind note）を足し、部署の待ち受けがターンの終わりに会話を再開させて渡す（ターンの途中の会話の入力フィールドには打たない）。待ち受けの跡の無い
    部署（フックの無い古い版の会話）には、今までどおり窓に打ち込む。打った場所・頼み元・宛先の受付箱の台帳に kind note で残す。
    終了の値を返す。"""
    if bool(a.text) == bool(a.brief):
        print("止めた: --note には --text <文> か --brief <ファイル> のどちらか 1 つが要る")
        return 2
    body = a.text
    if a.brief:
        try:
            body = pathlib.Path(os.path.expanduser(a.brief)).read_text(encoding="utf-8")
        except OSError as e:
            print(f"止めた: 足しのファイルを読めない（{e}）")
            return 2
    common = ports.git.common_dir(cwd)
    if not common:
        print(f"止めた: 打った場所 {cwd} が git でないので、受付箱を置けない（会社の本社か部署の場所から打つ）")
        return 2
    try:
        cfg, accounts_, sessions_, panes, companies, settings, notes = survey(a.config, ports)
    except term.Error as e:
        print(f"止めた: {term.NAME} を読めない（{e}）")
        return 1
    inbox = deliver.inbox_of(common)
    sid = chat.session_of(ports.env)
    found_account, found_name = ports.caller(sessions_)
    name = a.from_name or place_name(cwd, sid, ports) or found_name
    sender = name or "名の無い会話"
    note_id = deliver.new_id(ports.now())
    by = {"name": name, "account": a.from_account or found_account, "session": sid, "place": cwd}
    item, more = _find_queued(a.note, a.config, ports, cwd, companies)
    notes += more
    if item is not None:
        if a.dry_run:
            print("\n".join(notes + [f"受付 {a.note} は順番待ち（{os.path.dirname(item['path'])}）に在る。渡すときの 1 行に足しを添える"]))
            return 0
        if not wake.pull(item):
            print("\n".join(notes + [f"止めた: 受付 {a.note} は今ちょうど渡った。もう一度打つと、受けた部署に足しを届ける"]))
            return 2
        path = deliver.put(inbox, f"{note_id}-note.md", body)
        line = note_line(a.note, note_id, sender, body, path)
        wake.put_back({**item, "line": f"{item.get('line') or wake.wake_text([item])}\n{line}",
                       "notes": (item.get("notes") or []) + [{"id": note_id, "file": path, "from": sender, "at": ports.now()}]})
        _log_taken(item, {"id": note_id, "kind": "note", "ask": a.note, "at": ports.now(), "status": "queued", "from": by,
                          "file": path}, also=[inbox])
        print("\n".join(notes + [f"足し {note_id} → 受付 {a.note}（順番待ちに在る）  渡すときの 1 行に添えた", f"- 本文: {path}"]))
        return 0
    held = [(c, d) for c in companies for d in c["departments"] if d["attrs"].get("ask") == a.note]
    if not held or held[0][1]["attrs"].get("delivered") == a.note:
        leaves = _forwarded_to(a.note, ports, cwd, companies)
        if leaves is not None:
            # 回して閉じた頼み（--forward）: 回した先をたどり、まだ終わっていない先に足す（社長室の足しが「もう納品した」で止まった）
            if len(leaves) == 1:
                print("\n".join(notes + [f"受付 {a.note} は回して閉じた頼みなので、回した先の受付 {leaves[0]} に足す"]))
                return note(argparse.Namespace(**{**vars(a), "note": leaves[0]}), ports, cwd)
            if not leaves:
                print("\n".join(notes + [f"止めた: 受付 {a.note} は回して閉じた頼みで、回した先もみな閉じた（足すなら新しい頼みとして "
                                         "--ask で頼む）"]))
                return 2
            print("\n".join(notes + [f"止めた: 受付 {a.note} は回して閉じた頼みで、回した先の開いている頼みが {len(leaves)} 件ある。"
                                     "どれに足すかを決めて、その受付で打ち直す"] + [f"  {x}" for x in leaves]))
            return 2
    if not held:
        print("\n".join(notes + [f"止めた: 受付 {a.note} はどの部署も受けておらず、どの順番待ちにも無い（会社が {term.NAME} に開いているか、"
                                 "受付番号を確かめる）"]))
        return 2
    company, dept = held[0]
    where = f"{company['name']}/{dept['attrs'].get('name') or dept['branch']}"
    if dept["attrs"].get("delivered") == a.note:
        print("\n".join(notes + [f"止めた: {where} は受付 {a.note} をもう納品した（足すなら新しい頼みとして --ask で頼む）"]))
        return 2
    dest_common = ports.git.common_dir(company["root"])
    dest_inbox = deliver.inbox_of(dest_common) if dest_common else None
    place_dir = ports.git.git_dir(dept["path"])
    to, heard = listener(dest_inbox, company["name"], dept["attrs"].get("name"))
    path = os.path.join(inbox, f"{note_id}-note.md")
    line = note_line(a.note, note_id, sender, body, path)
    by_ledger = bool(to and dest_inbox and place_dir and (heard or wake.has_history(dest_inbox, place_dir)))
    pane = None
    if not by_ledger:
        pane = live_window(dept, ports)
        if pane is None:
            print("\n".join(notes + [f"止めた: {where} は待ち受けの跡が無く、窓にも会話が居ない（部署の会話を戻してから打ち直す）"]))
            return 1
    if a.dry_run:
        print("\n".join(notes + [f"足す先: {where}（受付 {a.note} を受けている）  "
                                 + ("台帳に知らせを足す（待ち受けがターンの終わりに渡す）" if by_ledger else f"窓 {pane} に打ち込む"),
                                 f"会話に渡す 1 行: {line}"]))
        return 0
    path = deliver.put(inbox, f"{note_id}-note.md", body)
    if by_ledger:
        deliver.log(dest_inbox, wake.notice(to, note_id, wake.NOTE, path, line, ports.now()))
        status, detail = "noticed", ("待ち受けが渡す" if heard else "ターンの終わりに待ち受けが渡す")
    else:
        status, detail = deliver.send_confirmed(pane, line, ports.term, ports.pause, busy_check(dept, accounts_, ports))
    _log_each([inbox, dest_inbox, dept["attrs"].get("boss-inbox")],
              {"id": note_id, "kind": "note", "ask": a.note, "at": ports.now(), "status": status, "detail": detail, "from": by,
               "to": {"company": company["name"], "name": dept["attrs"].get("name"), "path": dept["path"], "pane": pane,
                      "wake": to if by_ledger else None}, "file": path})
    print("\n".join(notes + [f"足し {note_id} → {where}（受付 {a.note}）  {status}" + (f"（{detail}）" if detail else ""),
                             f"- 本文: {path}"]))
    return 0 if status in ("noticed", "sent") else 1


# 人の答え待ちの印（部署の属性）。値は受付番号と訳。A2A の input-required（人の入力が要って止まっている頼み）に当たる
WAITING, WAITING_WHY = "waiting", "waiting-why"


def wait_for_input(a, ports, cwd):
    """--wait <訳>。部署が今の頼みを、人の答えが要って止まっている（答え待ち）と印す。その間、止まる前のフックは納品を促さない。
    人がその会話に打つと、文を受けたフック（wake_hook.py --pause）が印を外す。印は納品でも外れる。打った場所の会社と頼み元の
    受付箱の台帳に kind waiting で残す。終了の値を返す。"""
    attrs = ports.attrs(cwd)
    ask = attrs.get("ask")
    why = (a.wait or "").strip()
    if not attrs.get("role"):
        print(f"止めた: {cwd} は部署でない（git の設定 company.role が無い）。答え待ちは頼まれた部署の場所で印す")
        return 2
    if not ask or attrs.get("delivered") == ask:
        print("止めた: 納品していない頼みが無い（答え待ちにする頼みが無い）")
        return 2
    if not why:
        print("止めた: 何の答えを誰から待つのかを --wait に書く")
        return 2
    common = ports.git.common_dir(cwd)
    try:
        provision.mark(cwd, gitx.root_of(common), {WAITING: ask, WAITING_WHY: why}, ports.git)
    except (gitx.GitError, OSError) as e:
        print(f"止めた: 答え待ちの印を書けなかった（{e}）")
        return 1
    # 答え待ちを台帳にも残す（頼みの状態を台帳から読めるように。印は git の属性で、台帳の射影からは見えない。docs/ledger.md）
    _log_each([deliver.inbox_of(common), attrs.get("boss-inbox")],
              {"id": ask, "kind": "waiting", "at": ports.now(), "why": why,
               "from": {"name": attrs.get("name"), "session": attrs.get("session"), "place": cwd}})
    print(f"受付 {ask} を答え待ちにした（{why}）。止まる前のフックは納品を促さない。人がこの会話に打つと印が外れる。"
          "答えが出たら --deliver で返す")
    return 0


def rest_here(a, ports, cwd):
    """--rest。部署か窓口の会話が、今は会話を空にしてよい区切りだと印す（属性 company.rest に場所の会話の id。待ち受けが会話の
    始まりに今の会話の id へ書き直す属性なので、打った会話の id になる。待ち受けは、この印が自分の会話の id のときだけ区切りと見る）。このターンの終わりに
    待ち受け（wake_hook.py）が、窓の入力フィールドが空なら窓に /clear を打って空にし、印を外す。区切りかどうかは会話が役の本文の決まりで
    判断する（ここでは決めない）。人がその会話に打つと印が外れる（人と話している途中の会話を空にしない）。終了の値を返す。"""
    attrs = ports.attrs(cwd)
    if not attrs.get("role") or not attrs.get("name"):
        print(f"止めた: {cwd} は部署でも窓口でもない（git の設定 company.role と company.name が無い）。区切りは部署か窓口の場所で印す")
        return 2
    ask = attrs.get("ask")
    pending = ask and attrs.get("delivered") != ask
    moving = attrs.get(wake.MOVE_TO) and attrs[wake.MOVE_TO] != attrs.get("account")
    if pending and not moving:
        print(f"止めた: 納品していない頼み（受付 {ask}）が在る。区切りは、受けた頼みを納品で閉じてから印す（--move がほかのアカウントへ"
              f"移す印 company.{wake.MOVE_TO} を付けた会話だけは、納品の前でも印せる）")
        return 2
    common = ports.git.common_dir(cwd)
    try:
        provision.mark(cwd, gitx.root_of(common), {wake.REST: attrs.get("session") or "1"}, ports.git)
    except (gitx.GitError, OSError) as e:
        print(f"止めた: 区切りの印を書けなかった（{e}）")
        return 1
    if pending:
        # --move が移す印を付けたが、会話がターンの途中で移せなかった。区切りの印が納品の後にしか打てないと、頼みが長いと移す時が
        # 来ない（2026-10-19、p3 の週の枠が尽きる前に移そうとした部署。受付 20261019-004101-f39d00 の困りごと）
        print(f"区切りと印した。このターンの終わりに、待ち受けがこの会話をアカウント {attrs[wake.MOVE_TO]} へ移して起動し直し、"
              f"新しい会話に受付 {ask} を渡す（会話は空にしない。移せなければ区切りの印 company.{wake.REST} を外し、この会話のまま続ける。"
              f"移す先の印 company.{wake.MOVE_TO} は残るので、次の --rest でまた試す）。新しい会話は前の会話の記憶を持たないので、"
              f"このターンを終える前に、作業場の git ディレクトリの {wake.HANDOFF}（{os.path.join(ports.git.git_dir(cwd), wake.HANDOFF)}）に"
              "引継ぎ（済んだこと・次の手）を書く。新しい会話への最初の文がそのファイルを指す")
        return 0
    print("区切りと印した。このターンの終わりに、窓の入力フィールドが空なら、機械がこの会話の窓に /clear を打って空にする"
          "（空にした後の会話の始まりに役の本文が足される。会社の形の起動の設定が起動したときと違えば、/clear の代わりに"
          "その設定で起動し直す）。人がこの会話に打つと印が外れる")
    return 0


def finish_here(a, ports, cwd):
    """--done。エフェメラルの部署の会話が、納品してメインブランチに入れ終えたので片付けてよいと印す（属性 company.finished に場所の会話の id）。このターンの
    終わりに待ち受け（wake_hook.py）が --retire を会話から切り離して走らせ、会話を止めて部屋を --clean と同じ決まりで片付ける。
    断るのは、部署でない・窓口・永続・会話の id が無い・納品していない頼みか順番待ちの頼みが在る・未コミットの変更か手元にしか無い
    commit が在る・ブランチがメインブランチに入っていない（landed。マージ済みの PR に入った物も入ったとみなす）時（commit の無い部署は入っているとみなす）。前の --retire が
    残した訳（company.retire-kept）は消す。人がその会話に打つと印が外れる。終了の値を返す。"""
    attrs = ports.attrs(cwd)
    if not attrs.get("role") or not attrs.get("name"):
        print(f"止めた: {cwd} は部署でない（git の設定 company.role と company.name が無い）。終わりはエフェメラルの部署の場所で印す")
        return 2
    common, place = ports.git.common_dir(cwd), ports.git.git_dir(cwd)
    if not common or not place or os.path.realpath(place) == os.path.realpath(common):
        print("止めた: 窓口は畳まない。会話を空にしてよい区切りなら --rest で印す")
        return 2
    if attrs.get("lifecycle") == gitx.PERSISTENT:
        print("止めた: 永続の部署は畳まない。会話を空にしてよい区切りなら --rest で印す")
        return 2
    if not attrs.get("session"):
        print("止めた: 部署の属性に会話の id（company.session）が無いので、機械が会話を止めて畳めない。--clean で並べて手で片付ける")
        return 2
    ask = attrs.get("ask")
    if ask and attrs.get("delivered") != ask:
        print(f"止めた: 納品していない頼み（受付 {ask}）が在る。終わりは、受けた頼みを納品で閉じてから印す")
        return 2
    if wake.queued(deliver.inbox_of(common), place):
        print("止めた: 順番待ちに頼みが在る。待ち受けが渡す次の頼みを済ませてから印す")
        return 2
    waiting = asked_open(deliver.inbox_of(common), attrs, cwd)
    if waiting:
        # この部署が頼んで、まだ返事（納品）の来ていない頼み。畳むと、返事が届いても受ける会話が居ない（業務改革が社長室の答えを待つ間など）
        print(f"止めた: この部署が頼んで返事の来ていない頼みが在る（受付 {'・'.join(waiting)}）。返事を受けて済ませてから印す")
        return 2
    if not ports.is_clean(cwd):
        print("止めた: 未コミットの変更か、git に足していないファイルが在る（片付けると消える）。commit するか消してから印す")
        return 2
    root = gitx.root_of(common)
    try:
        main = gitx.default_branch(root)
    except gitx.GitError as e:
        print(f"止めた: ブランチがメインブランチに入っているかを読めない（{e}）")
        return 1
    merged = landed(cwd, main, attrs)
    if ports.unpushed(cwd, landed=lambda: merged):
        print("止めた: 手元にしか無い commit か stash が在る（片付けると消える）。メインブランチに入れてから印す")
        return 2
    if not merged:
        # 読むだけの部署がほかのブランチを detached で開いたまま打つと、そのブランチの commit で断られる。手を添える（2026-10-19 の
        # works-factory の会社で、部署が自分で手を考えた）
        here = gitx.branch(cwd)
        print(f"止めた: ブランチがメインブランチ（origin/{main} の手元の控え）に入っておらず、先頭の commit を含む PR も {main} に"
              "マージされていない。--land で入れるか、PR で入れる会社なら PR がマージされてから印す"
              "（ほかの会話が入れたなら、git fetch してから打ち直す）"
              + ("。今はブランチに乗っていない（detached）。読むためにほかのブランチを開いたなら、自分のブランチ（部署を立てたときのブランチ）を"
                 "checkout し直してから打ち直す" if not here else
                 "。自分の commit が無くても、ほかのブランチの上に切ったブランチ（--task の --base）は、そのブランチがメインブランチに入るまで"
                 "入っていないと見る（入れるのが人の会社なら、--done を打たずに止まり、入った後に窓口が --retire で畳む）"))
        return 2
    try:
        provision.mark(cwd, root, {wake.FINISHED: attrs["session"], wake.RETIRE_KEPT: None}, ports.git)
    except (gitx.GitError, OSError) as e:
        print(f"止めた: 終わりの印を書けなかった（{e}）")
        return 1
    print("終わりと印した。このターンの終わりに、機械がこの会話を止め、部屋（作業場・worktree・会話・手元のブランチ）を --clean と同じ決まりで"
          "片付ける。片付けられなければ部屋を残し、訳は --clean の一覧に出る。人がこの会話に打つと印が外れる")
    return 0


def asked_open(inbox, attrs, cwd):
    """この部署（名前と場所）が頼んで、まだ返事（納品）の来ていない頼みの受付の並び。頼みの行は頼んだ側の会社の受付箱に残る。"""
    return [r["id"] for r in deliver.open_asks(deliver.records(inbox))
            if (r.get("from") or {}).get("name") == attrs.get("name") and (r.get("from") or {}).get("place")
            and os.path.realpath(r["from"]["place"]) == os.path.realpath(cwd)]


def landed(cwd, main, attrs, g=gitx, gh=ghx):
    """部署のブランチの先頭がメインブランチ main に入ったか。origin/<main> の手元の控えの祖先なら入った。祖先でなくても、先頭の commit を
    含む PR が GitHub で main にマージ済みなら入ったとみなす（squash でのマージと、束ねた別の PR で入れた形。どちらも先頭は祖先にならない。
    2026-10-19 に works-factory の #776・#789・#790 で、マージ済みの部署が --done・--retire・--clean で止まった）。gh に問う鍵は部署の
    属性 company.gh-user（無ければこの処理の環境のまま）。origin が GitHub でない・gh で読めないときは入っていないとみなす（消さない側に倒す）。"""
    if g.is_merged(cwd, f"refs/remotes/origin/{main}"):
        return True
    repo, sha = g.origin_repo(cwd), g.head_sha(cwd)
    if not repo or not sha:
        return False
    try:
        env = gh.env_for(attrs["gh-user"], dict(os.environ)) if attrs.get("gh-user") else None
        return gh.merged_pr_of(repo, sha, main, env=env) is not None
    except (gh.GhError, OSError):
        return False


def leftover(cwd, attrs, g=gitx):
    """受けた頼みを納品し終えた部署が、ターンを終えて残る訳。(種類, 中身) か None。種類は waiting（この部署が頼んだ返事を待つ。中身は
    受付の並び）・unlanded（ブランチの先頭がメインブランチに入っていない〔landed〕。中身はメインブランチの名前）・finish（エフェメラルの
    部署で、ブランチもメインブランチに入っているのに終わりの印〔--done〕が無い）。部署でない・窓口・納品していない頼みが在る・終わりの印が在る・
    順番待ちに頼みが在る（待ち受けが次を渡す）・メインブランチを読めない・永続の部署でブランチが入っている、ときは None。
    --clean の一覧（入れ損ねた部署と、返事を待つだけの部署を分けて出す）と Stop フック（stop_after）が使う。2026-10-17 に my_notes で、
    --land が止まって入れ損ねた部署が、残った疑問に「担当者: 段取り」と書いただけで段取りに頼まず、1 日残った。--clean はこれを、
    返事を待つだけの部署と同じ一行で出していた。"""
    ask = attrs.get("ask")
    if not attrs.get("role") or not ask or attrs.get("delivered") != ask or attrs.get(wake.FINISHED):
        return None
    common, place = g.common_dir(cwd), g.git_dir(cwd)
    if not common or not place or os.path.realpath(place) == os.path.realpath(common):
        return None
    inbox = deliver.inbox_of(common)
    if wake.queued(inbox, place):
        return None
    root = g.toplevel(cwd) or cwd
    waiting = asked_open(inbox, attrs, root)
    if waiting:
        return "waiting", waiting
    try:
        main = g.default_branch(gitx.root_of(common))
    except g.GitError:
        return None
    if not landed(root, main, attrs, g):
        return "unlanded", main
    return None if attrs.get("lifecycle") == gitx.PERSISTENT else ("finish", main)


def stop_after(payload, cwd, attrs, count, settings, g=gitx):
    """納品し終えた部署のターンの終わりに差し戻す訳（leftover が unlanded か finish のとき）。差し戻さないなら None。count はこの会話・
    この頼みで差し戻した回数（deliver.STOP_LIMIT まで）。unlanded は --land を使う会社（会社の形の [land] の取り込み方が
    ff-after-ci）だけ（PR で入れる会社は、ブランチがメインブランチに入るのを人の見直しが待つ）。残った疑問に担当者を書いただけでは、その担当者が
    頼みを受けていなければ誰も追わない。"""
    sid = payload.get("session_id")
    if attrs.get("session") and sid and attrs["session"] != sid or count >= deliver.STOP_LIMIT:
        return None
    got = leftover(cwd, attrs, g)
    if got is None or got[0] == "waiting":
        return None
    kind, main = got
    name = attrs.get("name") or attrs.get("branch") or "<部署>"
    limit = f"（この差し戻しは {deliver.STOP_LIMIT} 回まで。{count + 1} 回目）"
    if kind == "finish":
        return (f"頼み（受付 {attrs['ask']}）は納品済みで、ブランチもメインブランチに入っている。エフェメラルの部署なので、{RUN} --done でターンを終える（会話を"
                f"止めて部屋を片付けるのは機械がする）。持ち主と話している途中なら、印さずにターンを終えてよい{limit}")
    root = gitx.root_of(g.common_dir(cwd))
    info = tree.read_info(root, settings)
    if land.read_rules(info.get("path"), attrs.get("role"), info.get("text"))["mode"] != "ff-after-ci":
        return None
    return (f"頼み（受付 {attrs['ask']}）は納品済みだが、ブランチがメインブランチ（origin/{main} の手元の控え）に入っていない。止まる前に "
            f"{RUN} --land {shlex.quote(name)} で入れる（ほかの会話が入れたなら、git fetch origin してから止まる）。--land が自動の"
            f"権限の判定に止められたなら、打ち直さず、入れてほしいと {RUN} --ask {shlex.quote(tree.company_name(root, info))} で窓口に"
            f"頼む（頼んだ返事を待つ間は、この差し戻しは出ない）。残った疑問に担当者を書くだけでは、担当者に頼みが届かない。"
            f"持ち主と話している途中なら、入れずにターンを終えてよい{limit}")


def forwarded_ask(inbox, ask_id):
    """--deliver --for の引き当て: 受付箱の台帳から、回した元の頼み（id）か回した先の頼み（child）が ask_id の forwarded の行の
    最後の 1 件。無ければ None。"""
    rows = [r for r in deliver.records(inbox) if r.get("kind") == "forwarded" and ask_id in (r.get("id"), r.get("child"))]
    return rows[-1] if rows else None


def caused_ask(rows, ask_id):
    """--deliver --for の 2 つ目の引き当て: cause 付きの --ask で回した子の頼み（受けた頼みを閉じずに、残った疑問などをほかの部署へ
    回した物）。ask_id が子の受付（kind ask の行の id）か、子を出した元の受付（その行の cause）なら、子の行の cause_boss（--ask が
    書く）か、それが無ければ元の受付の kind ask の行（頼み元の受付箱の台帳に在る。頼み元が部署でない会話でも、別の会社でも在る）から
    頼み元を組み立て、forwarded の行と同じ形（id と boss）で返す。無ければ None。rows は会社をまたいでたどった台帳の行（todo.inboxes_from）。"""
    asks = [r for r in rows if r.get("kind") == "ask" and r.get("cause")]
    # 子の受付に当たる行を先に見る（cause で当てると、子がさらに回した孫の行を拾う）。同じ受付の行が何本も在れば最初の行
    # （--take で回し直した行は、回し直した部署が受けている頼みを cause に書く）
    children = [r for r in asks if r.get("id") == ask_id] or [r for r in asks if r.get("cause") == ask_id]
    if not children:
        return None
    origin = children[0]["cause"]
    if isinstance(children[0].get("cause_boss"), dict):
        return {"id": origin, "boss": children[0]["cause_boss"]}
    # cause_boss を書く前の版の行: 元の頼みの行の頼み元（台帳の行のファイルの置き場や作業場からたどれた受付箱に在る物だけ）
    asks = [r for r in rows if r.get("kind") == "ask" and r.get("id") == origin and r.get("file") and r.get("from")]
    if not asks:
        return None
    sender = asks[-1]["from"]
    return {"id": origin, "boss": {"name": sender.get("name"), "session": sender.get("session"), "account": sender.get("account"),
                                   "pane": None, "inbox": os.path.dirname(asks[-1]["file"])}}


def for_attrs(attrs, record):
    """回して閉じた頼みへ納品するときの属性: 受けた頼みと頼み元を forwarded の行の物に替える（ほかの属性は今の場所の物）。"""
    boss = record.get("boss") or {}
    return {**attrs, "ask": record["id"], "boss": boss.get("name"), "boss-session": boss.get("session"),
            "boss-account": boss.get("account"), "boss-pane": boss.get("pane"), "boss-inbox": boss.get("inbox")}


def deliver_summary(a, ports, cwd):
    """--deliver。終了の値を返す（2 は要約の項目が足りず送らなかった）。--for <受付> なら、--forward で回して閉じた頼みか、cause
    付きの --ask で回した子の頼みの元の頼みの頼み元へ返し、今受けている頼み（company.ask）は閉じない。"""
    attrs = ports.attrs(cwd)
    if not attrs.get("role"):
        print(f"止めた: {cwd} は部署でない（git の設定 company.role が無い）。納品は頼まれた部署の場所から返す")
        return 2
    for_ask = getattr(a, "for_ask", None)
    if for_ask:
        common = ports.git.common_dir(cwd)
        record = forwarded_ask(deliver.inbox_of(common), for_ask) if common else None
        if not record and common:
            rows = todo.inboxes_from([deliver.inbox_of(common)], ports.git.common_dir)[1]
            record = caused_ask(rows, for_ask)
            if record and record["id"] not in deliver.closed_ids(rows):
                # 頼み元への知らせの行は元の受付を閉じたと読まれる。元の頼みを受けている部署がまだ納品していないなら、その納品で返す
                print(f"止めた: 受付 {for_ask} の元の頼み（受付 {record['id']}）がまだ納品されていない。--for は元の頼みを納品した後に"
                      "届いた子の頼みの答えを返す口なので、答えは元の頼みの納品に含めて返す")
                return 2
        if not record:
            print(f"止めた: 受付 {for_ask} を回した行が台帳に無い（この会社の受付箱の kind forwarded の行も、cause 付きの kind ask の行と"
                  "その元の頼みの行も無い）。--for には、--ask … --forward で回した元の受付か回した先の受付、または cause 付きの --ask で"
                  "回した子の受付かその元の受付を渡す")
            return 2
        attrs = for_attrs(attrs, record)
    try:
        text = sys.stdin.read() if a.deliver == "-" else \
            pathlib.Path(os.path.expanduser(a.deliver)).read_text(encoding="utf-8")
    except OSError as e:
        print(f"止めた: 要約のファイルを読めない（{e}）")
        return 2
    common = ports.git.common_dir(cwd)
    settings = os.path.dirname(config.path_of(a.config, os.environ))
    the_role, problems = shape_role(gitx.root_of(common) if common else None, settings, attrs["role"])
    required = deliver.required_items(the_role)
    data, body, bad = deliver.front(text)
    bad += deliver.front_problems(data, deliver.DELIVER_FIELDS)
    items = deliver.parse(body, set(required) | set(deliver.DEFAULT_ITEMS))
    if deliver.PREAMBLE in items:
        bad.append("最初の見出しの前に字がある（どの項目にも入らないので送れない）。見出しの下に移す")
    if deliver.OPEN in items:
        bad.append(deliver.OPEN_IN_BODY)
    if bad:
        print("\n".join(["送らなかった: 要約の頭書き（機械が読むフィールド）か見出しの形が違う"] + [f"  {x}" for x in bad] + [deliver.DELIVER_FORMAT]))
        return 2
    questions = data.get("open")
    if questions is not None:
        items[deliver.OPEN] = deliver.render_open(questions)
    branch = ports.branch(cwd)
    if deliver.BRANCH_ITEM in required and not items.get(deliver.BRANCH_ITEM) and branch:
        items[deliver.BRANCH_ITEM] = branch
    missing = deliver.check(items, required)
    notes = list(problems)
    if missing:
        print("\n".join(notes + ["送らなかった: 要約に足りない項目がある: " + "、".join(missing),
                                 f"- 必須の項目（{attrs['role']}）: " + "・".join(required)
                                 + f"。{deliver.OPEN}の外は見出し（## 結論）で書く。結論は 3 行以内、決め手には原典の URL",
                                 deliver.DELIVER_FORMAT]))
        return 2
    relays = (the_role or {}).get("holders")
    if relays is not None:
        bad = deliver.holder_problems(questions, relays, attrs.get("boss")) + deliver.unsure_problems(items)
        if bad:
            print("\n".join(notes + ["送らなかった: 残った疑問の担当者が足りない（役の holders の検査）"] + [f"  {x}" for x in bad]
                            + [deliver.DELIVER_FORMAT]))
            return 2
    check = (the_role or {}).get("deliver_check")
    if check:
        place = ports.git.toplevel(cwd) or cwd
        code, out = deliver.gate(check, place, {"role": attrs["role"], "ask": attrs.get("ask"), "branch": branch, "place": place,
                                                "items": items, "open": questions or [], "summary": deliver.summary_text(items, required),
                                                "version": own_version()},
                                 subprocess.run)
        if code != 0:
            print("\n".join(notes + [f"送らなかった: 納品の検査が通らなかった（終了の値 {code}）: {check}"]
                            + [f"  {x}" for x in out.splitlines()]
                            + [f"- 検査の台本 {x} がこの作業場に無い（会社の形は origin のメインブランチから読むが、検査は作業場で走る）。"
                               "ブランチをメインブランチの上にリベースしてから（git fetch origin && git rebase origin/main）打ち直す"
                               for x in deliver.absent_files(check, place)]
                            + [f"- 検査は会社の形の役 {attrs['role']} の deliver_check。上の訳を直してから --deliver を打ち直す"]))
            return 2
        notes.append(f"納品の検査が通った: {check}")
    inbox = attrs.get("boss-inbox")
    to, heard = listener(inbox, inbox and inbox_company(inbox, settings), attrs.get("boss"))
    if not heard and inbox and attrs.get("boss-session"):
        # 頼み元の名前で待ち受けが引けない（前の版は会話の一覧の名前を頼み元に書いた。place_name）: 頼んだ会話の id で引く
        heard = wake.listening_session(inbox, attrs["boss-session"])
        to = heard["names"][0] if heard else to
    gone = False   # 頼み元の会話が終わった（窓も会話の一覧の生きた会話も無い）
    if heard:
        # 頼み元の待ち受けが居る: herdr の窓を探さない（知らせは台帳の 1 行で届く）
        sid, pane, how = attrs.get("boss-session"), None, f"{to} の待ち受けが会話を再開させる"
    else:
        try:
            _, _, sessions_, panes, companies, _, more = survey(a.config, ports)
        except term.Error as e:
            print(f"止めた: {term.NAME} を読めない（{e}）")
            return 1
        notes += more
        sid, entry = deliver.boss_session(attrs, sessions_)
        if not inbox and entry and entry.get("cwd"):
            boss_common = ports.git.common_dir(entry["cwd"])
            inbox = deliver.inbox_of(boss_common) if boss_common else None
        if not inbox:
            print("\n".join(notes + ["止めた: 頼み元の受付箱が分からない（属性 company.boss-inbox が無く、頼み元の会話も一覧に見えない）"]))
            return 1
        pane, how = deliver.boss_window(attrs, sid, entry, panes, companies)
        living = [s for items in sessions_.values() for s in items if s.get("sessionId") == sid and s.get("state") not in FALLEN]
        if pane is None and attrs.get("boss") and sid and not living:
            # 頼み元の会話が終わった（窓が無く、会話の一覧にも居ないか止まっている）: 頼み元の名前に宛てた知らせを台帳に置き、納品済みにする。
            # 会話が生きていて窓を 1 つに決められないだけのときと、頼み元が誰か分からないときは、今までどおり納品済みにしない。待ち続けても
            # 終わった会話の窓は開かず、部署は次の頼みを受けられないまま止まる（2026-10-17 の点検。頼み元 my-notes-ad が終わり、
            # 順番待ちが 5 時間渡らなかった）。頼み元の名前の待ち受けが後で張られれば、台帳の知らせで起きる
            to, gone = wake.address(inbox_company(inbox, settings), attrs["boss"]), True
    ask_id = attrs.get("ask")
    sender = attrs.get("name") or os.path.basename(os.path.normpath(cwd))
    file_id = deliver.new_id(ports.now())   # 納品ごとに別のファイル（打ち直しで前の要約を消さない）
    target = os.path.join(inbox, f"{file_id}-deliver.md")
    line = deliver.deliver_line(ask_id, sender, branch, items, required, target)
    if a.dry_run:
        where = how if heard else (f"ペイン {pane}（{how}）" if pane else f"窓なし（{how}）" + (f"。{to} への知らせを台帳に置く" if gone else ""))
        print("\n".join(notes + [f"送り先: {attrs.get('boss') or '-'}  {where}", f"受付箱: {target}",
                                 f"{'会話に渡す' if heard else '打ち込む'} 1 行: {line}"]))
        return 0
    path = deliver.put(inbox, os.path.basename(target), deliver.summary_text(items, required))
    if heard:
        deliver.log(inbox, wake.notice(to, ask_id, "deliver", path, line, ports.now()))
        status, detail = "sent", how
    elif gone:
        deliver.log(inbox, wake.notice(to, ask_id, "deliver", path, line, ports.now()))
        status, detail = POSTED, f"{how}。{to} への知らせを台帳に置いた（頼み元の待ち受けが張られたら届く）"
    else:
        status, detail = deliver.send(pane, line, ports.term, ports.pause) if pane else ("failed", how)
    deliver.log(inbox, {"id": file_id, "kind": "deliver", "ask": ask_id, "at": ports.now(), "status": status, "detail": detail,
                        "from": {"name": attrs.get("name"), "account": attrs.get("account"), "session": attrs.get("session"),
                                 "branch": branch, "place": cwd},
                        "to": {"name": attrs.get("boss"), "account": attrs.get("boss-account"), "session": sid, "pane": pane,
                               "wake": to if heard or status == POSTED else None},
                        "file": path, "holders": deliver.holders_of(questions),
                        **({"for": for_ask} if for_ask else {})})
    if ask_id and status in ("sent", POSTED) and not for_ask:   # --for は回して閉じた頼みへ返すので、今の頼みの印は変えない
        try:
            provision.mark(cwd, gitx.root_of(common), {"delivered": ask_id, WAITING: None, WAITING_WHY: None}, ports.git)
        except (gitx.GitError, OSError) as e:
            notes.append(f"納品済みの印（company.delivered）を書けなかった（{e}）。Stop フックが差し戻し続ける（上限まで）")
    if common:
        notes += follow_main(gitx.root_of(common), settings, attrs.get("role"), ports.git)
    if status == POSTED:
        notes.append("頼み元の会話が見つからないので、要約と知らせを頼み元の受付箱に置いて納品済みにした（次の頼みを受けられる）。"
                     "頼み元の代わりに読む人（窓口など）が要れば、受付箱の台帳のこの行から要約を渡す")
    elif status != "sent":
        notes.append("要約は受付箱に置いたが、頼み元に知らせられなかったので納品済みにしない。頼み元の窓が開いたら打ち直す")
    print("\n".join(notes + [f"納品 {file_id} → {attrs.get('boss') or '頼み元'}  {status}" + (f"（{detail}）" if detail else ""),
                             f"- 要約: {path}"]))
    return 0 if status in ("sent", POSTED) else 1


def follow_main(source, settings, role_name, g):
    """納品の後に、部署の会社の代表の clone のメインブランチを origin のメインブランチにそろえる（そろえられなければ窓口に知らせる。landing.catch_up）。
    --land（取り込み方 ff-after-ci）を使う会社だけ。部署が --land を通さずに手で push しても、成果が代表の clone に届く。出す行の並び。"""
    info = tree.read_info(source, settings)
    rules = land.read_rules(info.get("path"), role_name, info.get("text"))
    if rules["mode"] != "ff-after-ci":
        return []
    try:
        main = rules["main"] or gitx.default_branch(source)
    except gitx.GitError as e:
        return [f"注記: メインブランチの名前を読めないので、代表の clone をそろえていない（{e}）"]
    import landing   # --land の流れは Stop フックでは要らないので、ここで読む（フックが読み込む物を増やさない）
    return landing.catch_up(source, info, main, g) if main else []


def in_flight(payload, shells):
    """ターンの終わりに裏で動いている処理の数。分からなければ None。Claude Code が Stop フックの入力に渡す background_tasks（裏の処理の
    一覧。run_in_background の Bash・裏で立てたサブエージェント〔Agent〕・Monitor など。https://code.claude.com/docs/en/hooks#stop-input）
    が在れば、その中の status が running の物を数える（2026-10-17 に 2.1.301 で、裏のサブエージェントが running で載り、終わった後のターンでは
    空なのを見た）。一覧の無い版では、裏の Bash を ps で数える（shells。裏のサブエージェントは見えない）。"""
    tasks = payload.get("background_tasks")
    if isinstance(tasks, list):
        return sum(1 for t in tasks if isinstance(t, dict) and t.get("status") == "running")
    return shells()


def stop_hook(stdin=sys.stdin, out=sys.stdout, attrs_of=gitx.worktree_attrs, tmp_dir=None, shells=chat.background_shells):
    """プラグインの Stop フック。部署の会話で受けた頼みを納品していなければ、止まるのを差し戻す（{"decision": "block"}）。
    納品し終えた後も、ブランチをメインブランチに入れていないか、エフェメラルの部署が終わりの印を打っていなければ差し戻す（stop_after）。
    部署の会話が裏の処理（run_in_background の Bash・裏で立てたサブエージェントなど。in_flight）を待っている間は差し戻さない（裏の処理が
    終わると Claude Code が会話を再開させるので、納品はその後でよい。差し戻すと待つだけのターンを回数の上限まで繰り返した。裏の
    サブエージェントは 0.50.5 まで数えておらず、待つ手の無い会話が 1 つの返答で待つ字を出し続けた。2026-10-17 の割り振り）。動いているのを
    確かめられないとき（一覧も ps も無い）と、裏の処理が終わったときは差し戻す。待っている印を herdr に出すのは tiers の statusline
    （tiers-statusline setup で入れる。全部の会話に効き、30 秒ごとに描き直す）の受け持ちで、ここでは出さない。"""
    payload = json.loads(stdin.read() or "{}")
    cwd = payload.get("cwd") or os.getcwd()
    attrs = attrs_of(cwd)
    if not attrs.get("role"):
        return 0
    if not attrs.get("ask") or in_flight(payload, shells):
        return 0
    path = deliver.stop_count_path(tmp_dir or tempfile.gettempdir(), payload.get("session_id") or "-", attrs["ask"])
    try:
        count = int(pathlib.Path(path).read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        count = 0
    reason = deliver.stop_verdict(payload, attrs, count, RUN)
    if reason is None and attrs.get("delivered") == attrs["ask"]:
        # 納品の後: ブランチをメインブランチに入れずに、かエフェメラルの部署が終わりの印を打たずに、ターンを終えて残らない（leftover）。数えるのは別の控え
        path = deliver.stop_count_path(tmp_dir or tempfile.gettempdir(), payload.get("session_id") or "-", f"{attrs['ask']}-after")
        try:
            count = int(pathlib.Path(path).read_text(encoding="utf-8").strip() or 0)
        except (OSError, ValueError):
            count = 0
        reason = stop_after(payload, cwd, attrs, count, os.path.dirname(config.path_of(attrs.get("config"), os.environ)))
    if reason is None:
        return 0
    os.makedirs(os.path.dirname(path), exist_ok=True)
    pathlib.Path(path).write_text(str(count + 1), encoding="utf-8")
    out.write(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    if sys.argv[1:] == ["stop"]:
        try:
            sys.exit(stop_hook())
        except Exception as e:  # フックの誤りで会話を止めない。訳は利用者に見せる（終了の値 1 は止めずに stderr を出す）
            print(f"works-dispatch の Stop フックが動かなかった: {e}", file=sys.stderr)
            sys.exit(1)
    print("使い方: python3 orders.py stop（Stop フックとして。--ask・--deliver は dispatch.py から）", file=sys.stderr)
    sys.exit(2)
