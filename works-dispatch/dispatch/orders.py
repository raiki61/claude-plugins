#!/usr/bin/env python3
"""依頼と納品の流れ（会社の形の設計 4.5・4.10 の 3・9.2）。入口の dispatch.py --ask・--deliver と、プラグインの Stop フックから呼ぶ。

dispatch.py の流れの続きで、ノード（nodes/deliver.py ほか）を呼ぶ順をここが持つ。ほかの部署と dispatch.py を同時に直すので、
ぶつかりを減らすために別のファイルにした。

--ask <宛先>（ask）: 頼む会話の場所から、宛先の部署を「会社/役」か部署の名前で決め（deliver.find_target。会社は herdr に開いている
リポジトリ。tree と同じ読み方）、頼みの本文を頼む側の受付箱に置き、宛先の部署に知らせる。宛先（「会社/部署の名前」）の待ち受けが
居れば、宛先の会社の受付箱の台帳に知らせの 1 行を足し、待ち受けが会話を起こす（nodes/wake.py）。居なければ（フックの無い古い会話・
落ちた会話）、宛先の部署の窓（attach のペイン）に 1 行を打ち込む。宛先の部署が立っていなければ、--task と同じ道（dispatch._task）で
立て、最初の文で頼みを渡す。宛先の部署の属性に、受けた頼み（company.ask）と頼み元（company.boss・boss-account・boss-session・
boss-pane・boss-inbox）を書く。頼み元の名前は、頼んだ場所の名前（company.name。place_name）か、会話の一覧の名前。--forward を添えれば、打った部署か窓口が受けている頼みを、この頼みで回したとして閉じる（forwarded。
回した先は台帳にだけ書き、頼み元の会話は起こさない）。

--deliver <要約のファイル>（deliver）: 部署の場所から、要約の項目がそろっているかを確かめ（欠けていれば送らずに欠けた項目を返す）、
役に納品の検査（会社の形の deliver_check）が在れば走らせ（0 以外で終われば送らずに検査の出力を返す。deliver.gate）、
頼み元の受付箱に置き、頼み元（「頼み元の会社/company.boss」。引けなければ company.boss-session の会話）の待ち受けが居ればその
台帳に知らせの 1 行を足し、居なければ頼み元の窓に 1 行を打ち込み、属性に納品済み（company.delivered）を書く。
--for <受付> を添えれば、--forward で回して閉じた頼みの頼み元（台帳の forwarded の行）へ返し、今受けている頼みは閉じない。

`python3 orders.py stop`（stop_hook）: プラグインの Stop フック。部署でない場所では何もしない。
"""

import argparse
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
    import claudex  # noqa: E402
    import config  # noqa: E402
    import gitx  # noqa: E402
    import herdr  # noqa: E402
    from nodes import deliver, launch, provision, role, sync, tree, wake  # noqa: E402
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
# 部署に「この字で返せ」と渡す dispatch.py の起こし方。今動いている Python で、パスは / 区切りで引用符を付ける
# （Windows の Claude Code の Bash の道具は Git Bash で、\ と空白のパスがそのままでは崩れ、python3 が無いこともある）
RUN = " ".join(shlex.quote(pathlib.Path(x).as_posix()) for x in (sys.executable, DISPATCH_PY))

for _s in (sys.stdin, sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")


def survey(config_path, ports):
    """herdr に開いている会社と部署を読む（dispatch._company と同じ読み方）。(設定か None, アカウントの並び, 会話の一覧, ペイン,
    会社の並び, 設定の置き場, 注記)。herdr を読めなければ herdr.HerdrError。"""
    notes = []
    path = config.path_of(config_path, os.environ)
    try:
        cfg = config.load(config_path, os.environ, missing_ok=True)
        accounts_ = cfg.accounts
    except config.ConfigError as e:
        cfg, accounts_ = None, (config.Account("default", "claude"),)
        if os.path.exists(path):
            notes.append(f"dispatch の設定を読めないので、既定のアカウント 1 つとして見る（{e}）")
    sessions_ = {}
    for acc in accounts_:
        try:
            sessions_[acc.name] = ports.list_sessions(acc.config_dir, include_done=True)
        except claudex.ClaudeError as e:
            notes.append(f"アカウント {acc.name} の会話の一覧を読めないので、そのアカウントの会話を見ない（{e}）")
    panes = ports.herdr.panes()
    roots = tree.roots(ports.herdr.workspaces(), panes, ports.common_of,
                       list(dict.fromkeys(s["cwd"] for items in sessions_.values() for s in items if s.get("cwd"))))
    places_of = {}
    for root in roots:
        try:
            places_of[root] = ports.herdr.worktrees(root)
        except herdr.HerdrError as e:
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
    desk = bool(place and common) and os.path.realpath(place) == os.path.realpath(common)
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
        if os.name != "nt" and ports.herdr.shell_in_front(pane):
            return None
        tail = ports.herdr.read(pane, 6)
    except herdr.HerdrError:
        return pane   # 確かめられないときは、居ると見て今までどおり（打ち込んで会話を乱さない側）
    lines = [x for x in (tail or "").splitlines() if x.strip()]
    if lines and EXITED.search("\n".join(lines[-3:])):
        return None
    return pane


def revive(dept, accounts_, ports, sessions_=None, source=None):
    """部署の窓に会話が居ない（PC やサーバーの再起動で attach の窓が落ちたなど）とき、部署の属性の会話の id で、部署のペインに
    `<アカウントのコマンド> attach <id>` を打ち、窓に会話が戻るのを見る。裏の会話は落ちても記録が残り、attach で前の続きから
    戻る（まっさらな環境での 5 回目の試しの 1。Windows で確かめた）。(戻ったペインか None, 言葉)。"""
    full = dept["attrs"].get("session")
    if not full:
        return None, "部署の属性に会話の id（company.session）が無いので戻せない（部署を立て直す）"
    acc = next((x for x in accounts_ if x.name == dept["attrs"].get("account")), accounts_[0] if len(accounts_) == 1 else None)
    entry = next((x for items in (sessions_ or {}).values() for x in items if x.get("sessionId") == full), None)
    # attach は短い id で打つ（部署を立てるときと同じ）。一覧に無ければ属性の短い id（company.job。/clear で会話の id が変わっても
    # 変わらない）
    sid = claudex.attach_id(entry, full) if entry or not dept["attrs"].get("job") else dept["attrs"]["job"]
    command = f"{acc.command if acc else 'claude'} attach {sid}"
    try:
        if not dept["panes"] and source:
            # ペインを閉じると部署の作業場も閉じる。開き直し、新しいペインのシェルで attach を打つ
            fresh, ws = provision.reopen(source, dept["path"], dept["attrs"].get("name") or os.path.basename(dept["path"]), ports.herdr)
            if fresh:
                dept = {**dept, "panes": [{"pane_id": fresh, "agent": None}]}
                # 開き直したペインにも、部署の名前・表示名・札を --sync と同じに付ける。開き直した作業場は新しいので、印も付け直す
                sync.apply([sync.op(fresh, dept["attrs"], len(accounts_) > 1)], ports.herdr)
                if ws:
                    sync.apply_workspaces([sync.kind_op(ws, dept["attrs"])], ports.herdr)
                for _ in range(REVIVE_LOOKS):
                    if ports.herdr.shell_in_front(fresh):
                        break
                    ports.pause()
        pane = next((p["pane_id"] for p in dept["panes"] if ports.herdr.shell_in_front(p["pane_id"])), None)
        if pane is None:
            # 止まった attach が窓の前に残っていれば Ctrl+Z（2.1.302 からは続けて Esc）でシェルに戻し、シェルに戻るのを見る
            for p in dept["panes"]:
                if launch.to_shell(p["pane_id"], ports.herdr, ports.pause, REVIVE_LOOKS):
                    pane = p["pane_id"]
                    break
    except herdr.HerdrError as e:
        pane = None
        why = str(e)
    else:
        why = "部署の作業場が herdr に開いていない" if not dept["panes"] else "部署のペインの前にシェルが居ない"
    if pane is None:
        return None, f"部署の会話を戻せなかった（{why}）。部署の作業場のペインで {command} を打って戻す"
    got = launch.attach({"account": {"command": acc.command if acc else "claude"}}, pane, sid, ports.herdr)
    if got["status"] != "attached":
        return None, f"部署の会話を戻せなかった（{got['detail']}）。部署のペイン {pane} で {command} を打って戻す"
    for look in range(REVIVE_LOOKS):
        ports.pause()
        try:
            screen = ports.herdr.read(pane, 6)
            alive = (ports.herdr.agent(pane) or {}).get("agent") and not EXITED.search(screen or "") \
                and "No job matching" not in (screen or "") and (os.name == "nt" or not ports.herdr.shell_in_front(pane))
        except herdr.HerdrError:
            alive = False
        if alive:
            return pane, f"部署の窓に会話が居なかったので、ペイン {pane} で {command} を打って戻した"
    try:
        screen = ports.herdr.read(pane, 6)
    except herdr.HerdrError:
        screen = ""
    if "00~" in screen:
        # attach の画面を強く終わらせると、窓の端末に貼り付けの印（ESC[200~）が残り、打った命令の前後に 00~ と 01~ が付いて
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
        except claudex.ClaudeError:
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
        return False, ["頼みごとに空にする役だが、部署の会話が動いていて空にできないので送らなかった（打つと番の後に前の会話のまま"
                       "届く）。番が終わってから --ask を打ち直す"]
    before, talk = busy.found, newest()

    def cleared():
        busy()
        now = newest()
        return bool(busy.found) and busy.found != before or bool(now) and bool(talk) and now[0] != talk[0]
    status, detail = deliver.clear_talk(pane, ports.herdr, ports.pause, cleared)
    if status == "cleared":
        return True, [f"前の頼み（受付 {held}）を納品し終えているので、/clear で会話を空にしてから送る"]
    return False, [f"会話を空にできなかったので送らなかった（{detail}）。部署の窓を見て、空になっていれば --ask を打ち直す"]


def nudge_line(held, boss, now=None):
    """戻した部署に、落ちる前の頼みの納品を促す 1 行。頭に時刻を入れて、前に送った促しと字を分ける（届いたかの確かめが、画面に
    残った前の促しを今の促しと見誤らないように）。"""
    stamp = time.strftime("%H:%M:%S", time.localtime(now)) if now else ""
    return (f"再開の知らせです{f'（{stamp}）' if stamp else ''}: この会話は落ちて戻った。受付 {held}（{boss or '頼み元'} から）の頼みをまだ納品していない。"
            "済んでいれば要約を納品の命令（--deliver）で返し、途中なら続けてから返す。")


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
            print(f"- 回した元: 受付 {held} を閉じ、回した先を台帳に書く（頼み元 {mine.get('boss') or '-'} の会話は起こさない）")
        elif sent:
            print("\n".join(forwarded(mine, sent, ports, cwd)))
    return rc


def forwarded(attrs, sent, ports, cwd):
    """--forward で回した後: 受けた頼み（attrs の company.ask）から回した先の頼み（sent の id と to）への結び付きを、自分と頼み元の
    受付箱の台帳に kind forwarded で残し、受けた頼みを納品済みにする。頼み元には知らせない（回しただけの知らせで頼み元の会話を
    起こさない。頼み元は、結果か問いの納品で起きたときに台帳で追う）。結果と問いは --deliver --for <受けた頼み> で返す（頼み元は
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
    return [f"回した元の受付 {held} を閉じた（頼み元 {attrs.get('boss') or '-'} の会話は起こさず、回した先を台帳に書いた）"]


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
    common = ports.git.common_dir(cwd)
    if not common:
        print(f"止めた: 頼む会話の場所 {cwd} が git でないので、受付箱を置けない（会社の本社か部署の場所から頼む）")
        return 2
    try:
        cfg, accounts_, sessions_, panes, companies, settings, notes = survey(a.config, ports)
        target = deliver.find_target(companies, gitx.root_of(common), a.ask, a.task, current_role(settings))
    except herdr.HerdrError as e:
        print(f"止めた: herdr を読めない（{e}）")
        return 1
    except deliver.DeliverError as e:
        print(f"止めた: {e}")
        return 2
    company, dept, role = target["company"], target["department"], target["role"]
    if dept is None and not a.dry_run:
        # 部署を新しく立てる: 納品の項目と起こすときの設定を、立てた後のフックと同じ会社の形で決める（--task と同じ。task には
        # 取り直したことを渡し、2 度は取らない）
        notes += [n for n in [provision.refresh_shape(company["root"], ports.git)] if n]
    the_role, problems = shape_role(company["root"], settings, role)
    required = deliver.required_items(the_role)
    notes += problems
    found_account, found_name = ports.caller(sessions_)
    inbox = deliver.inbox_of(common)
    ask_id = getattr(a, "ask_id", None) or deliver.new_id(ports.now())
    sid = ports.env.get("CLAUDE_CODE_SESSION_ID")
    # 頼み元の窓は、頼んだ会話の居るペイン（herdr.own_pane。環境変数 HERDR_PANE_ID は裏の会話では別のペインを指すことがある）。
    # Claude Code の外から頼んだ（会話の id が無い）なら、頼んだ会話が無いので窓も記録しない
    here = next((s.get("cwd") for items in sessions_.values() for s in items if sid and s.get("sessionId") == sid and s.get("cwd")), cwd)
    account, name = a.from_account or found_account, a.from_name or place_name(here, sid, ports) or found_name
    sender = name or "名の無い会話"
    # 納品を受ける受付箱は、頼んだ会話の居る場所の会社の物（待ち受けはそこで宛先を受ける）。命令を打った場所（cwd）がほかの会社の
    # clone でも替えない（段取りが claude-plugins の clone で打った頼みの返り先が claude-plugins の受付箱になり、段取りの待ち受けに
    # 届かなかった。my_notes の受付 20261017-054115-5bc0b0）
    here_common = ports.git.common_dir(here) if here != cwd else common
    boss = {"ask": ask_id, "boss": name, "boss-account": account, "boss-session": sid,
            "boss-pane": herdr.own_pane(here, sid, panes) if sid else None,
            "boss-inbox": deliver.inbox_of(here_common) if here_common else inbox}
    if getattr(a, "from_boss", None):
        # 合図で回した頼み（calls.fire）: 頼み元は、本流に入れた部署の頼み元
        boss.update({k: v for k, v in a.from_boss.items() if k != "ask"})
        name = boss.get("boss")
        sender = name or sender
    if not boss.get("boss"):
        notes.append("頼み元が分からないので、この頼みの納品の返り先が無い（会話の中から打つか --from-name を渡す）")
    where = f"{company['name']}/{(dept or {}).get('attrs', {}).get('name') or role}"
    if (the_role or {}).get("machine"):
        print("\n".join(notes + [f"止めた: 役「{role}」は機械だけの役（AI の部署を持たない）なので頼めない。道具を --call で呼ぶ"
                                 f"（--tree が道具を出す）"]))
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
        # 待ち受けの跡の在る fresh の部署が、納品し終えて番の途中（待ち受けが止まっている）なら積む。番の終わりの待ち受けが空にしてから渡す
        mid_turn = fresh and held and not pending and busy_check(dept, accounts_, ports)()
        if to and dest_inbox and place_dir and (heard or (pending or mid_turn) and wake.has_history(dest_inbox, place_dir)):
            # 待ち受けの居る部署: 順番待ちに積み、待ち受けが渡す（受付の設計 4.1）
            return queue_ask(a, ports, notes, where, dept, dest_inbox, place_dir, to, heard, digest,
                             {"id": ask_id, "sender": sender, "body": body, "inbox": inbox, "required": required, "boss": boss,
                              "fresh": bool((the_role or {}).get("fresh")), "from": {"name": name, "account": account,
                              "session": boss["boss-session"], "place": cwd}, "company": company["name"], "role": role},
                             accounts_, sessions_, company["root"], sent)
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
                status, detail = deliver.send_confirmed(pane, nudge_line(held, dept["attrs"].get("boss"), ports.now()), ports.herdr, ports.pause,
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
        if fresh:
            acc = next((x for x in accounts_ if x.name == dept["attrs"].get("account")), accounts_[0] if len(accounts_) == 1 else None)
            # 記録はペインのシェルで起きた会話のアカウントの下に在る。頼む会話の CLAUDE_CONFIG_DIR（別のアカウント）で探さない
            # （設定のフォルダを書かないアカウントの部署を、別のアカウントの段取りから頼むと、記録が見つからず止まった。
            # my_notes の受付 20261017-075753-01991f）
            ok, said = clear_before_ask(dept, held, pane, busy, ports,
                                        lambda: claudex.newest_talk(acc.config_dir if acc else None, dept["path"], ports.account_env))
            notes += said
            if not ok:
                print("\n".join(notes + [f"止めた: 宛先の部署 {where} は頼みごとに空の会話で受ける役なので、前の会話のままでは送らない"]))
                return 1
        path = deliver.put(inbox, f"{ask_id}-ask.md", body)
        line = deliver.ask_line(ask_id, sender, body, path, required, RUN)
        status, detail = deliver.send_confirmed(pane, line, ports.herdr, ports.pause, busy)
        if status == "sent":
            # 役の fresh を写す（会社の形を後から変えても、次の頼みから herdr の表示が合う）
            marks = {**boss, "fresh": FRESH if fresh else None, "ask-digest": digest}
            if busy.found and busy.found != dept["attrs"].get("session"):
                # /clear で変わった会話の id を書き直す（Stop フックの見分けと、落ちたときの attach が古い id を使わない）
                marks.update(provision.renew_session(dept["attrs"], busy.found))
            try:
                provision.mark(dept["path"], company["root"], marks, ports.git)   # 値の無い頼み元の属性は消える（前の頼み元を残さない）
            except (gitx.GitError, OSError) as e:
                notes.append(f"宛先の部署に頼みの属性を書けなかった（{e}）。納品の命令が頼み元を見つけられず、Stop フックが効かない")
        deliver.log(inbox, {"id": ask_id, "kind": "ask", "at": ports.now(), "status": status, "detail": detail,
                            "from": {"name": name, "account": account, "session": boss["boss-session"], "place": cwd},
                            "to": {"company": company["name"], "name": dept["attrs"].get("name"), "role": role,
                                   "branch": dept["branch"], "path": dept["path"], "pane": pane}, "file": path})
        if status == "sent":
            sent.update(id=ask_id, to={"company": company["name"], "name": dept["attrs"].get("name"), "role": role})
        print("\n".join(notes + [f"頼み {ask_id} → {where}  {status}" + (f"（{detail}）" if detail else ""),
                                 f"- 本文: {path}"]))
        return 0 if status == "sent" else 1
    # 宛先の役の部署が無い: 頼みごとに新しい部署を立てる（会社の形の設計 4.10 の 2。枝の名前は頼む側が渡す）
    if not (a.task and a.task.strip() and a.branch):
        print("\n".join(notes + [f"止めた: {company['name']} に役「{role}」の常設の部署が無いので新しく立てる。"
                                 "部署の名前を --task <名前>、枝を --branch <枝> で渡す"]))
        return 2
    if cfg is None:
        print("\n".join(notes + ["止めた: 部署を立てるには、読める dispatch の設定が要る（アカウントと使用率の上限を読む。"
                                 "ファイルが無ければ既定で動くが、在って読めない物は直す）"]))
        return 2
    repo = config.repo_at(cfg, company["root"], ports.origin)
    if a.dry_run:
        print("\n".join(notes + [f"頼む先: {company['name']} に部署 {a.task}（役 {role}、枝 {a.branch}）を立て、最初の文で頼む",
                                 f"- 受付箱: {inbox}",
                                 "- 書く属性: " + "、".join(f"company.{k}={v}" for k, v in boss.items() if v)]))
        return 0
    path = deliver.put(inbox, f"{ask_id}-ask.md", body)
    ns = argparse.Namespace(**{**vars(a), "brief": path, "role": role})
    rc = task(cfg, repo, ns, ports, extra_attrs=boss, tail=deliver.tail(required, RUN), refreshed=True)
    try:
        got = next((p for p in ports.places(repo) if p.get("branch") == a.branch), None)
    except herdr.HerdrError as e:
        got = None
        notes.append(f"立てた後に部署の場所を読めない（{e}）")
    attrs = ports.attrs(got["path"]) if got else {}
    status = "sent" if attrs.get("ask") == ask_id and attrs.get("session") else "failed"
    deliver.log(inbox, {"id": ask_id, "kind": "ask", "at": ports.now(), "status": status, "detail": None if rc == 0 else f"rc={rc}",
                        "from": {"name": name, "account": account, "session": boss["boss-session"], "place": cwd},
                        "to": {"company": company["name"], "name": a.task, "role": role, "branch": a.branch,
                               "path": got and got["path"], "pane": None}, "file": path})
    if status == "sent":
        sent.update(id=ask_id, to={"company": company["name"], "name": a.task, "role": role})
    print("\n".join(notes + [f"頼み {ask_id} → {company['name']}/{a.task}（新しく立てた部署）  {status}", f"- 本文: {path}"]))
    return rc if status == "sent" else (rc or 1)


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
                                         "at": ports.now(), "from": ask["sender"]})
    deliver.log(dest_inbox, wake.notice(to, ask["id"], wake.QUEUED, path, None, ports.now()))
    if not heard and live_window(dept, ports) is None:
        notes.append(revive(dept, accounts_, ports, sessions_, source)[1])
    elif heard:   # 会話の処理は生きている（番の途中で待ち受けが居ないのは、番の終わりに張られる）
        notes += wake_stuck(dept, where, dest_inbox, place_dir, accounts_, ports, sessions_, source)
    n = len(wake.queued(dest_inbox, place_dir))
    detail = f"順番待ちに積んだ（{n} 件目。{'待ち受けが渡す' if heard else '今の頼みの納品の後に待ち受けが渡す'}）"
    deliver.log(ask["inbox"], {"id": ask["id"], "kind": "ask", "at": ports.now(), "status": "queued", "detail": detail,
                               "from": ask["from"], "to": {"company": ask["company"], "name": dept["attrs"].get("name"),
                                                          "role": ask["role"], "branch": dept["branch"], "path": dept["path"],
                                                          "pane": None, "wake": to}, "file": path})
    sent.update(id=ask["id"], to=dest)
    print("\n".join(notes + [f"頼み {ask['id']} → {where}  {detail}", f"- 本文: {path}"]))
    return 0


POSTED = "posted"   # 納品の台帳の status: 頼み元の窓が無いので、頼み元の名前に宛てた知らせを台帳に置いた（納品済みにする）

# 順番待ちが渡らずに止まった部署の会話に打つ 1 行（wake_stuck）。番を 1 つ回すだけで、返事も仕事も要らない
STUCK_LINE = ("順番待ちの知らせです: この部署の順番待ちが渡らずに止まっていたので、番を 1 つ回す。返事は要らない。受けている頼みが"
              "途中なら、それを続ける。無ければ何もせずにこの番を終える（番の終わりに待ち受けが張り直して、次の頼みを渡す）。")


def stuck_why(dest_inbox, place_dir, dept):
    """部署の順番待ちが渡らずに止まっていれば、その訳。止まっていなければ None。止まり方は 2 つ: 番を終えたのに渡す待ち受けが居ない
    （wake.stalled）と、待ち受けは居るが渡さずに待っている（wake.held。台帳の最後の行が held）。"""
    if wake.stalled(dest_inbox, place_dir, dept["attrs"]):
        return "渡す待ち受けが居ない"
    why = wake.held(dest_inbox, dept["path"], place_dir, dept["attrs"])
    return f"待ち受けが渡さずに待っている（{why}）" if why else None


# 待ち受けが渡さずに待つ訳のうち、すぐ替わる物（待ち受けが 5 秒ごとに試し直して自分で抜ける）。この訳では窓に打たない（待ち受けの
# /clear と打ち込みがぶつからないように）
PASSING = ("裏の処理が残っている", "会話がまだ動いている", "窓の入力欄が見えないか、字が在る")
# 人の文で番が始まると外れる印（wake_hook.resume_from_wait）。STUCK_LINE は人の文ではないので、打った後に書き戻す
KEPT_MARKS = ("rest", "waiting", "waiting-why", "finished")


def wake_stuck(dept, where, dest_inbox, place_dir, accounts_, ports, sessions_=None, source=None, moved=None):
    """順番待ちが渡らずに止まった部署（stuck_why）を、人の手なしに動かす。出す注記の並びを返す（止まっていなければ空）。
    - 窓に会話が居なければ（live_window）、attach で戻す（revive。戻った会話の始まりの待ち受けが渡す）。
    - 窓に会話が居て、手が空いていて（herdr の状態が idle か done）入力欄が空なら、STUCK_LINE を 1 行打って番を 1 つ回す。番の初めに
      前の待ち受けが止まり（--pause）、番の終わりに今の版の待ち受けが張り直して、空にしてから次を渡す。
    - 会話が動いている・入力欄に字が在るとき、待ち受けが渡さない訳がすぐ替わる物（PASSING）のときは打たない（番の終わりに待ち受けが
      張り直すか、待ち受けが自分で抜ける。人の打ちかけの字と待ち受けの /clear を壊さない）。
    打ったか戻したかは受付箱の台帳に kind nudged で残し、動かしたら moved（並び）に True を足す。打った 1 行で外れる印（KEPT_MARKS）は
    書き戻す。以前は「部署の窓に 1 文打つ」と持ち主に打たせていた（2026-10-17 の割り振り・説明書）。"""
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
    try:
        status = (ports.herdr.agent(pane) or {}).get("agent_status")
        box = deliver.input_box(ports.herdr.read(pane, 40))
    except herdr.HerdrError as e:
        return [f"{head}。窓 {pane} を読めないので打たなかった（{e}）。--nudge {dept['attrs'].get('name') or where} で打ち直す"]
    if status not in ("idle", "done") or box is None or box.lstrip("❯").strip():
        return [f"{head}。会話が動いているか入力欄に字が在るので打たなかった（番の終わりに待ち受けが張り直す。止まったままなら "
                f"--nudge {dept['attrs'].get('name') or where} で打ち直す）"]
    keep = {k: dept["attrs"][k] for k in KEPT_MARKS if dept["attrs"].get(k)}
    sent, detail = deliver.send_confirmed(pane, STUCK_LINE, ports.herdr, ports.pause, busy_check(dept, accounts_, ports))
    if keep:
        try:
            provision.mark(dept["path"], gitx.root_of(ports.git.common_dir(dept["path"])), keep, ports.git)
        except (gitx.GitError, OSError) as e:
            detail = f"{detail + '。' if detail else ''}外れた印（{'・'.join(keep)}）を書き戻せなかった（{e}）"
    deliver.log(dest_inbox, {"id": first_id, "kind": "nudged", "at": ports.now(),
                             "place": dept["path"], "pane": pane, "why": why, "status": sent, "detail": detail})
    if sent == "sent" and moved is not None:
        moved.append(True)
    return [f"{head}。窓 {pane} に 1 行打って番を回した（{sent}" + (f"。{detail}" if detail else "") + "）。番の終わりに待ち受けが渡す"]


def nudge(a, ports, cwd):
    """--nudge <部署>。順番待ちが渡らずに止まった部署を動かす（wake_stuck）。--ask が止まった部署に積むときは同じことを自分でする
    ので、これは頼みを足さずに動かす口（段取りが --tree の「止まっている」を見て打つ）。終了の値を返す。"""
    common = ports.git.common_dir(cwd)
    try:
        cfg, accounts_, sessions_, panes, companies, settings, notes = survey(a.config, ports)
        target = deliver.find_target(companies, gitx.root_of(common) if common else None, a.nudge, None, current_role(settings))
    except herdr.HerdrError as e:
        print(f"止めた: herdr を読めない（{e}）")
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
        print("\n".join(notes + [f"{where} の順番待ちが止まっている（{why}）。窓に会話が居なければ attach で戻し、居れば 1 行打って番を回す"]))
        return 0
    moved = []
    print("\n".join(notes + wake_stuck(dept, where, dest_inbox, place_dir, accounts_, ports, sessions_, company["root"], moved)))
    return 0 if moved else 1


def _queue_inbox(item):
    """順番待ちの件のファイル（<受付箱>/queue/<場所の鍵>/<受付>.json）から、その受付箱。"""
    return os.path.dirname(os.path.dirname(os.path.dirname(item["path"])))


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
        except herdr.HerdrError as e:
            companies = []
            notes.append(f"herdr を読めないので、打った場所の会社の順番待ちだけを探した（{e}）")
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
    両方に残す）。記録の行なので、to は辞書にする（to が字の行は待ち受けが知らせと読み、宛先の会話を起こす。設計の 3.1）。"""
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
                            f"{a.text.strip()}\n\n---\n\n{body}")
    ns = argparse.Namespace(**{**vars(a), "brief": brief, "text": None, "ask_id": item.get("id"),
                               "from_boss": {k: v for k, v in marks.items() if k == "boss" or k.startswith("boss-")}})
    rc = ask(ns, ports, cwd, task)
    if rc != 0:
        wake.put_back(item)
        print(f"受付 {a.take} を {a.ask} に頼み直せなかったので、元の順番待ちの同じ場所に戻した")
        return rc
    _log_taken(item, {"id": item.get("id"), "kind": "taken", "at": ports.now(), "from": os.path.dirname(item["path"]),
                      "to": {"ask": a.ask}, "name": a.task, "by": {"session": ports.env.get("CLAUDE_CODE_SESSION_ID"), "place": cwd}})
    return 0


def _take_here(a, ports, cwd):
    common = ports.git.common_dir(cwd)
    attrs = ports.attrs(cwd) if common else {}
    if not attrs.get("role"):
        print(f"止めた: {cwd} は部署でも窓口でもない（git の設定 company.role が無い）。ほかの部署の順番待ちから回すなら --ask <宛先> を添える")
        return 2
    held = attrs.get("ask")
    if held and attrs.get("delivered") != held:
        print(f"止めた: 受付 {held} をまだ納品していない（頼み元の属性は 1 組なので、納品してから取る。今の頼みを手放して回すなら、"
              f"ほかの部署から --take {a.take} --ask <宛先>）")
        return 2
    inbox, place_dir = deliver.inbox_of(common), ports.git.git_dir(cwd)
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
                      "to": {"name": attrs.get("name"), "role": attrs.get("role")}, "skipped": skipped, "by": {"session": ports.env.get("CLAUDE_CODE_SESSION_ID"), "place": cwd}})
    print("\n".join([f"受付 {a.take} を順番待ちから取った（先に積まれた {len(skipped)} 件" + (f"〔{'・'.join(skipped)}〕" if skipped else "")
                      + "は順番待ちに残る）。この頼みを今受ける:", item.get("line") or wake.wake_text([item])]))
    return 0


def withdraw(a, ports, cwd):
    """--withdraw <受付>。順番待ちの 1 件を取り下げる（渡さずに消し、順番待ちの在る受付箱と頼み元の受付箱の台帳に kind withdrawn で
    残す。頼み元が取り下げを頼んだときや、段取りが同じ頼みを別の道で出し直したとき）。終了の値を返す。"""
    item, notes = _find_queued(a.withdraw, a.config, ports, cwd)
    if item is None:
        print("\n".join(notes + [f"止めた: 受付 {a.withdraw} はどの順番待ちにも無い（もう渡ったか、取り下げられた）"]))
        return 2
    if a.dry_run:
        print("\n".join(notes + [f"受付 {a.withdraw} を順番待ち（{os.path.dirname(item['path'])}）から取り下げる"]))
        return 0
    if not wake.pull(item):
        print("\n".join(notes + [f"止めた: 受付 {a.withdraw} はほかが先に取った"]))
        return 2
    _log_taken(item, {"id": item.get("id"), "kind": "withdrawn", "at": ports.now(), "from": os.path.dirname(item["path"]),
                      "by": {"session": ports.env.get("CLAUDE_CODE_SESSION_ID"), "place": cwd}})
    print("\n".join(notes + [f"受付 {a.withdraw} を順番待ちから取り下げた（台帳に残した）"]))
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
                      "passed": passed, "by": {"session": ports.env.get("CLAUDE_CODE_SESSION_ID"), "place": cwd}})
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
    （kind note）を足し、部署の待ち受けが番の終わりに会話を起こして渡す（番の途中の会話の入力欄には打たない）。待ち受けの跡の無い
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
    except herdr.HerdrError as e:
        print(f"止めた: herdr を読めない（{e}）")
        return 1
    inbox = deliver.inbox_of(common)
    sid = ports.env.get("CLAUDE_CODE_SESSION_ID")
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
    if not held:
        print("\n".join(notes + [f"止めた: 受付 {a.note} はどの部署も受けておらず、どの順番待ちにも無い（会社が herdr に開いているか、"
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
                                 + ("台帳に知らせを足す（待ち受けが番の終わりに渡す）" if by_ledger else f"窓 {pane} に打ち込む"),
                                 f"会話に渡す 1 行: {line}"]))
        return 0
    path = deliver.put(inbox, f"{note_id}-note.md", body)
    if by_ledger:
        deliver.log(dest_inbox, wake.notice(to, note_id, wake.NOTE, path, line, ports.now()))
        status, detail = "noticed", ("待ち受けが渡す" if heard else "番の終わりに待ち受けが渡す")
    else:
        status, detail = deliver.send_confirmed(pane, line, ports.herdr, ports.pause, busy_check(dept, accounts_, ports))
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
    人がその会話に打つと、文を受けたフック（wake_hook.py --pause）が印を外す。印は納品でも外れる。終了の値を返す。"""
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
    print(f"受付 {ask} を答え待ちにした（{why}）。止まる前のフックは納品を促さない。人がこの会話に打つと印が外れる。"
          "答えが出たら --deliver で返す")
    return 0


def rest_here(a, ports, cwd):
    """--rest。部署か窓口の会話が、今は会話を空にしてよい区切りだと印す（属性 company.rest に場所の会話の id。待ち受けが会話の
    始まりに今の会話の id へ書き直す属性なので、打った会話の id になる。待ち受けは、この印が自分の会話の id のときだけ区切りと見る）。この番の終わりに
    待ち受け（wake_hook.py）が、窓の入力欄が空なら窓に /clear を打って空にし、印を外す。区切りかどうかは会話が役の本文の決まりで
    判断する（ここでは決めない）。人がその会話に打つと印が外れる（人と話している途中の会話を空にしない）。終了の値を返す。"""
    attrs = ports.attrs(cwd)
    if not attrs.get("role") or not attrs.get("name"):
        print(f"止めた: {cwd} は部署でも窓口でもない（git の設定 company.role と company.name が無い）。区切りは部署か窓口の場所で印す")
        return 2
    ask = attrs.get("ask")
    if ask and attrs.get("delivered") != ask:
        print(f"止めた: 納品していない頼み（受付 {ask}）が在る。区切りは、受けた頼みを納品で閉じてから印す")
        return 2
    common = ports.git.common_dir(cwd)
    try:
        provision.mark(cwd, gitx.root_of(common), {wake.REST: attrs.get("session") or "1"}, ports.git)
    except (gitx.GitError, OSError) as e:
        print(f"止めた: 区切りの印を書けなかった（{e}）")
        return 1
    print("区切りと印した。この番の終わりに、窓の入力欄が空なら、機械がこの会話の窓に /clear を打って空にする"
          "（空にした後の会話の始まりに役の本文が足される。会社の形の起動の設定が起こしたときと違えば、/clear の代わりに"
          "その設定で起こし直す）。人がこの会話に打つと印が外れる")
    return 0


def finish_here(a, ports, cwd):
    """--done。都度の部署の会話が、納品して本流に入れ終えたので片付けてよいと印す（属性 company.finished に場所の会話の id）。この番の
    終わりに待ち受け（wake_hook.py）が --retire を会話から切り離して走らせ、会話を止めて部屋を --clean と同じ決まりで片付ける。
    断るのは、部署でない・窓口・常設・会話の id が無い・納品していない頼みか順番待ちの頼みが在る・未コミットの変更か手元にしか無い
    commit が在る・枝が本流（origin の既定の枝の手元の控え）に入っていない時（commit の無い部署は入っているとみなす）。前の --retire が
    残した訳（company.retire-kept）は消す。人がその会話に打つと印が外れる。終了の値を返す。"""
    attrs = ports.attrs(cwd)
    if not attrs.get("role") or not attrs.get("name"):
        print(f"止めた: {cwd} は部署でない（git の設定 company.role と company.name が無い）。終わりは都度の部署の場所で印す")
        return 2
    common, place = ports.git.common_dir(cwd), ports.git.git_dir(cwd)
    if not common or not place or os.path.realpath(place) == os.path.realpath(common):
        print("止めた: 窓口は畳まない。会話を空にしてよい区切りなら --rest で印す")
        return 2
    if attrs.get("residency") == "resident":
        print("止めた: 常設の部署は畳まない。会話を空にしてよい区切りなら --rest で印す")
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
    if not ports.is_clean(cwd):
        print("止めた: 未コミットの変更か、git に足していないファイルが在る（片付けると消える）。commit するか消してから印す")
        return 2
    if ports.unpushed(cwd):
        print("止めた: 手元にしか無い commit か stash が在る（片付けると消える）。本流に入れてから印す")
        return 2
    root = gitx.root_of(common)
    try:
        main = gitx.default_branch(root)
        merged = gitx.is_merged(cwd, f"refs/remotes/origin/{main}")
    except gitx.GitError as e:
        print(f"止めた: 枝が本流に入っているかを読めない（{e}）")
        return 1
    if not merged:
        print(f"止めた: 枝が本流（origin/{main} の手元の控え）に入っていない。--land で入れてから印す"
              "（ほかの会話が入れたなら、git fetch してから打ち直す）")
        return 2
    try:
        provision.mark(cwd, root, {wake.FINISHED: attrs["session"], wake.RETIRE_KEPT: None}, ports.git)
    except (gitx.GitError, OSError) as e:
        print(f"止めた: 終わりの印を書けなかった（{e}）")
        return 1
    print("終わりと印した。この番の終わりに、機械がこの会話を止め、部屋（作業場・worktree・会話・手元の枝）を --clean と同じ決まりで"
          "片付ける。片付けられなければ部屋を残し、訳は --clean の一覧に出る。人がこの会話に打つと印が外れる")
    return 0


def forwarded_ask(inbox, ask_id):
    """--deliver --for の引き当て: 受付箱の台帳から、回した元の頼み（id）か回した先の頼み（child）が ask_id の forwarded の行の
    最後の 1 件。無ければ None。"""
    rows = [r for r in deliver.records(inbox) if r.get("kind") == "forwarded" and ask_id in (r.get("id"), r.get("child"))]
    return rows[-1] if rows else None


def for_attrs(attrs, record):
    """回して閉じた頼みへ納品するときの属性: 受けた頼みと頼み元を forwarded の行の物に替える（ほかの属性は今の場所の物）。"""
    boss = record.get("boss") or {}
    return {**attrs, "ask": record["id"], "boss": boss.get("name"), "boss-session": boss.get("session"),
            "boss-account": boss.get("account"), "boss-pane": boss.get("pane"), "boss-inbox": boss.get("inbox")}


def deliver_summary(a, ports, cwd):
    """--deliver。終了の値を返す（2 は要約の項目が足りず送らなかった）。--for <受付> なら、--forward で回して閉じた頼みの頼み元へ
    返し、今受けている頼み（company.ask）は閉じない。"""
    attrs = ports.attrs(cwd)
    if not attrs.get("role"):
        print(f"止めた: {cwd} は部署でない（git の設定 company.role が無い）。納品は頼まれた部署の場所から返す")
        return 2
    for_ask = getattr(a, "for_ask", None)
    if for_ask:
        common = ports.git.common_dir(cwd)
        record = forwarded_ask(deliver.inbox_of(common), for_ask) if common else None
        if not record:
            print(f"止めた: 受付 {for_ask} を回して閉じた行（kind forwarded）が、この会社の受付箱の台帳に無い。"
                  "--for には --ask … --forward で回した元の受付か、回した先の受付を渡す")
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
    items = deliver.parse(text, set(required) | set(deliver.DEFAULT_ITEMS))
    branch = ports.branch(cwd)
    if deliver.BRANCH_ITEM in required and not items.get(deliver.BRANCH_ITEM) and branch:
        items[deliver.BRANCH_ITEM] = branch
    missing = deliver.check(items, required)
    notes = list(problems)
    if missing:
        print("\n".join(notes + ["送らなかった: 要約に足りない項目がある: " + "、".join(missing),
                                 f"- 必須の項目（{attrs['role']}）: " + "・".join(required)
                                 + "。見出し（## 結論）か行の頭の札（結論: …）で書く。結論は 3 行以内、決め手には原典の URL"]))
        return 2
    check = (the_role or {}).get("deliver_check")
    if check:
        place = ports.git.toplevel(cwd) or cwd
        code, out = deliver.gate(check, place, {"role": attrs["role"], "ask": attrs.get("ask"), "branch": branch, "place": place,
                                                "items": items, "summary": deliver.summary_text(items, required)},
                                 subprocess.run)
        if code != 0:
            print("\n".join(notes + [f"送らなかった: 納品の検査が通らなかった（終了の値 {code}）: {check}"]
                            + [f"  {x}" for x in out.splitlines()]
                            + [f"- 検査の台本 {x} がこの作業場に無い（会社の形は origin の本流から読むが、検査は作業場で走る）。"
                               "枝を本流の上に載せ直してから（git fetch origin && git rebase origin/main）打ち直す"
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
        sid, pane, how = attrs.get("boss-session"), None, f"{to} の待ち受けが会話を起こす"
    else:
        try:
            _, _, sessions_, panes, companies, _, more = survey(a.config, ports)
        except herdr.HerdrError as e:
            print(f"止めた: herdr を読めない（{e}）")
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
        status, detail = deliver.send(pane, line, ports.herdr, ports.pause) if pane else ("failed", how)
    deliver.log(inbox, {"id": file_id, "kind": "deliver", "ask": ask_id, "at": ports.now(), "status": status, "detail": detail,
                        "from": {"name": attrs.get("name"), "account": attrs.get("account"), "session": attrs.get("session"),
                                 "branch": branch, "place": cwd},
                        "to": {"name": attrs.get("boss"), "account": attrs.get("boss-account"), "session": sid, "pane": pane,
                               "wake": to if heard or status == POSTED else None},
                        "file": path, **({"for": for_ask} if for_ask else {})})
    if ask_id and status in ("sent", POSTED) and not for_ask:   # --for は回して閉じた頼みへ返すので、今の頼みの印は変えない
        try:
            provision.mark(cwd, gitx.root_of(common), {"delivered": ask_id, WAITING: None, WAITING_WHY: None}, ports.git)
        except (gitx.GitError, OSError) as e:
            notes.append(f"納品済みの印（company.delivered）を書けなかった（{e}）。Stop フックが差し戻し続ける（上限まで）")
    if status == POSTED:
        notes.append("頼み元の会話が見つからないので、要約と知らせを頼み元の受付箱に置いて納品済みにした（次の頼みを受けられる）。"
                     "頼み元の代わりに読む人（窓口など）が要れば、受付箱の台帳のこの行から要約を渡す")
    elif status != "sent":
        notes.append("要約は受付箱に置いたが、頼み元に知らせられなかったので納品済みにしない。頼み元の窓が開いたら打ち直す")
    print("\n".join(notes + [f"納品 {file_id} → {attrs.get('boss') or '頼み元'}  {status}" + (f"（{detail}）" if detail else ""),
                             f"- 要約: {path}"]))
    return 0 if status in ("sent", POSTED) else 1


def wait_mark(tmp_dir, sid):
    """その会話が裏の処理を待っているかの控え（中身は 1 か 0）の置き場。"""
    return pathlib.Path(tmp_dir, "works-dispatch-wait", re.sub(r"[^0-9A-Za-z_.-]", "_", sid or "-"))


def waiting_of(tmp_dir):
    """部署の属性を受けて、その部署の会話（company.session）が裏の処理を待っているかを控えから返す口（sync.plan に渡す。--sync が
    「裏の処理待ち」の印を消さないため）。"""
    def waiting(attrs):
        try:
            return bool(attrs.get("session")) and wait_mark(tmp_dir, attrs["session"]).read_text(encoding="utf-8") == "1"
        except OSError:
            return False
    return waiting


def show_waiting(payload, cwd, attrs, tmp_dir, shells, h):
    """部署の会話の番の終わりに、裏で走らせた Bash の数を見て、待っていれば herdr の表示名に「裏の処理待ち」を添え、待ち終えたら
    外す。前の番と変わったときだけ書く（会話ごとの控えのファイルに前の値を残す）。裏の数（分からなければ None）を返す。"""
    n = shells()
    if n is None:
        return None
    mark = wait_mark(tmp_dir, payload.get("session_id"))
    try:
        last = mark.read_text(encoding="utf-8")
    except OSError:
        last = "0"
    now = "1" if n else "0"
    if now != last:
        here = os.path.realpath(cwd)
        panes = [x for x in h.panes() if x.get("agent") and x.get("cwd") and os.path.realpath(x["cwd"]) == here]
        if len(panes) == 1:
            sync.apply([sync.waiting_op(panes[0]["pane_id"], attrs, bool(n))], h)
            mark.parent.mkdir(parents=True, exist_ok=True)
            mark.write_text(now, encoding="utf-8")
    return n


def stop_hook(stdin=sys.stdin, out=sys.stdout, attrs_of=gitx.worktree_attrs, tmp_dir=None, shells=claudex.background_shells, h=herdr):
    """プラグインの Stop フック。部署の会話で受けた頼みを納品していなければ、止まるのを差し戻す（{"decision": "block"}）。
    部署の会話が裏の処理（run_in_background の Bash）を待っている間は、herdr の表示名に「裏の処理待ち」を出し、差し戻さない
    （裏の処理が終わると Claude Code が会話を起こすので、納品はその後でよい。差し戻すと待つだけの番を回数の上限まで繰り返した）。"""
    payload = json.loads(stdin.read() or "{}")
    cwd = payload.get("cwd") or os.getcwd()
    attrs = attrs_of(cwd)
    if not attrs.get("role"):
        return 0
    try:
        waiting = show_waiting(payload, cwd, attrs, tmp_dir or tempfile.gettempdir(), shells, h)
    except (herdr.HerdrError, OSError, ValueError) as e:
        print(f"works-dispatch: 裏の処理待ちを herdr に出せなかった（{e}）", file=sys.stderr)
        waiting = None
    if not attrs.get("ask") or waiting:
        return 0
    path = deliver.stop_count_path(tmp_dir or tempfile.gettempdir(), payload.get("session_id") or "-", attrs["ask"])
    try:
        count = int(pathlib.Path(path).read_text(encoding="utf-8").strip() or 0)
    except (OSError, ValueError):
        count = 0
    reason = deliver.stop_verdict(payload, attrs, count, RUN)
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
