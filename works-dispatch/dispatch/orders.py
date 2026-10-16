#!/usr/bin/env python3
"""依頼と納品の流れ（会社の形の設計 4.5・4.10 の 3・9.2）。入口の dispatch.py --ask・--deliver と、プラグインの Stop フックから呼ぶ。

dispatch.py の流れの続きで、ノード（nodes/deliver.py ほか）を呼ぶ順をここが持つ。ほかの部署と dispatch.py を同時に直すので、
ぶつかりを減らすために別のファイルにした。

--ask <宛先>（ask）: 頼む会話の場所から、宛先の部署を「会社/役」か部署の名前で決め（deliver.find_target。会社は herdr に開いている
リポジトリ。tree と同じ読み方）、頼みの本文を頼む側の受付箱に置き、宛先の部署の窓（attach のペイン）に 1 行を打ち込む。宛先の部署が
立っていなければ、--task と同じ道（dispatch._task）で立て、最初の文で頼みを渡す。宛先の部署の属性に、受けた頼み（company.ask）と
頼み元（company.boss・boss-account・boss-session・boss-pane・boss-inbox）を書く。

--deliver <要約のファイル>（deliver）: 部署の場所から、要約の項目がそろっているかを確かめ（欠けていれば送らずに欠けた項目を返す）、
頼み元の受付箱に置き、頼み元の窓に 1 行を打ち込み、属性に納品済み（company.delivered）を書く。

`python3 orders.py stop`（stop_hook）: プラグインの Stop フック。部署でない場所では何もしない。
"""

import argparse
import json
import os
import pathlib
import shlex
import sys
import tempfile

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import claudex  # noqa: E402
import config  # noqa: E402
import gitx  # noqa: E402
import herdr  # noqa: E402
from nodes import deliver, provision, tree  # noqa: E402

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
        cfg = config.load(config_path, os.environ)
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


def shape_paths(root, settings):
    """会社の形のファイルの候補（読む順。tree.read_info と同じ）。"""
    return [os.path.join(root, *tree.INFO_FILE), tree.settings_info_path(settings, root)]


def _repo_for(cfg, root, ports):
    """会社の根の dispatch の設定の repo。設定に無ければ、その根を代表の clone とする最小の repo を作る。"""
    for r in cfg.repos:
        if r.source and os.path.realpath(r.source) == os.path.realpath(root):
            return r
    return config.Repo(ports.origin(root) or os.path.basename(os.path.normpath(root)), "", root)


def ask(a, ports, cwd, task):
    """--ask。task は dispatch._task（部署を立てる道）。終了の値を返す。"""
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
        cfg, _, sessions_, _, companies, settings, notes = survey(a.config, ports)
        target = deliver.find_target(companies, gitx.root_of(common), a.ask)
    except herdr.HerdrError as e:
        print(f"止めた: herdr を読めない（{e}）")
        return 1
    except deliver.DeliverError as e:
        print(f"止めた: {e}")
        return 2
    company, dept, role = target["company"], target["department"], target["role"]
    required, why = deliver.required_items(shape_paths(company["root"], settings), role)
    notes += [why] if why else []
    account, name = ports.caller(sessions_)
    sender = name or "名の無い会話"
    inbox = deliver.inbox_of(common)
    ask_id = deliver.new_id(ports.now())
    boss = {"ask": ask_id, "boss": name, "boss-account": account, "boss-session": ports.env.get("CLAUDE_CODE_SESSION_ID"),
            "boss-pane": ports.env.get("HERDR_PANE_ID"), "boss-inbox": inbox}
    where = f"{company['name']}/{(dept or {}).get('attrs', {}).get('name') or role}"
    if dept is not None:
        held = dept["attrs"].get("ask")
        if held and dept["attrs"].get("delivered") != held:
            # 部署は頼みを 1 つずつ受ける（頼み元の属性は 1 組なので、上書きすると前の頼み元に納品が返らない）
            print("\n".join(notes + [f"止めた: 宛先の部署 {where} は受付 {held}（頼み元 {dept['attrs'].get('boss') or '-'}）を"
                                     "まだ納品していない。納品を待つか、別の部署に頼む"]))
            return 2
        if a.task or a.branch:
            notes.append(f"宛先の部署 {where} は立っているので、--task・--branch は使わない")
        pane = deliver.window(dept)
        if pane is None:
            print("\n".join(notes + [f"止めた: 宛先の部署 {where}（{dept['branch']}）の窓に会話が居ない"
                                     "（--sync で付け直すか、部署を開き直す）"]))
            return 1
        if a.dry_run:
            line = deliver.ask_line(ask_id, sender, body, os.path.join(inbox, f"{ask_id}-ask.md"), required, RUN)
            print("\n".join(notes + [f"頼む先: {where}  ペイン {pane}", f"打ち込む 1 行: {line}",
                                     "書く属性: " + "、".join(f"company.{k}={v}" for k, v in boss.items() if v)]))
            return 0
        path = deliver.put(inbox, f"{ask_id}-ask.md", body)
        line = deliver.ask_line(ask_id, sender, body, path, required, RUN)
        status, detail = deliver.send(pane, line, ports.herdr)
        if status == "sent":
            try:
                provision.mark(dept["path"], company["root"], boss, ports.git)   # 値の無い頼み元の属性は消える（前の頼み元を残さない）
            except (gitx.GitError, OSError) as e:
                notes.append(f"宛先の部署に頼みの属性を書けなかった（{e}）。納品の命令が頼み元を見つけられず、Stop フックが効かない")
        deliver.log(inbox, {"id": ask_id, "kind": "ask", "at": ports.now(), "status": status, "detail": detail,
                            "from": {"name": name, "account": account, "session": boss["boss-session"], "place": cwd},
                            "to": {"company": company["name"], "name": dept["attrs"].get("name"), "role": role,
                                   "branch": dept["branch"], "path": dept["path"], "pane": pane}, "file": path})
        print("\n".join(notes + [f"頼み {ask_id} → {where}  {status}" + (f"（{detail}）" if detail else ""),
                                 f"- 本文: {path}"]))
        return 0 if status == "sent" else 1
    # 宛先の役の部署が無い: 頼みごとに新しい部署を立てる（会社の形の設計 4.10 の 2。枝の名前は頼む側が渡す）
    if not (a.task and a.task.strip() and a.branch):
        print("\n".join(notes + [f"止めた: {company['name']} に役「{role}」の常駐の部署が無いので新しく立てる。"
                                 "部署の名前を --task <名前>、枝を --branch <枝> で渡す"]))
        return 2
    if cfg is None:
        print("\n".join(notes + ["止めた: 部署を立てるには dispatch の設定が要る（アカウントと使用率の上限を読む）"]))
        return 2
    repo = _repo_for(cfg, company["root"], ports)
    if a.dry_run:
        print("\n".join(notes + [f"頼む先: {company['name']} に部署 {a.task}（役 {role}、枝 {a.branch}）を立て、最初の文で頼む",
                                 f"- 受付箱: {inbox}",
                                 "- 書く属性: " + "、".join(f"company.{k}={v}" for k, v in boss.items() if v)]))
        return 0
    path = deliver.put(inbox, f"{ask_id}-ask.md", body)
    ns = argparse.Namespace(**{**vars(a), "brief": path, "role": role})
    rc = task(cfg, repo, ns, ports, extra_attrs=boss, tail=deliver.tail(required, RUN))
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
    print("\n".join(notes + [f"頼み {ask_id} → {company['name']}/{a.task}（新しく立てた部署）  {status}", f"- 本文: {path}"]))
    return rc if status == "sent" else (rc or 1)


def deliver_summary(a, ports, cwd):
    """--deliver。終了の値を返す（2 は要約の項目が足りず送らなかった）。"""
    attrs = ports.attrs(cwd)
    if not attrs.get("role"):
        print(f"止めた: {cwd} は部署でない（git の設定 company.role が無い）。納品は頼まれた部署の場所から返す")
        return 2
    try:
        text = sys.stdin.read() if a.deliver == "-" else \
            pathlib.Path(os.path.expanduser(a.deliver)).read_text(encoding="utf-8")
    except OSError as e:
        print(f"止めた: 要約のファイルを読めない（{e}）")
        return 2
    common = ports.git.common_dir(cwd)
    settings = os.path.dirname(config.path_of(a.config, os.environ))
    required, why = deliver.required_items(shape_paths(gitx.root_of(common), settings) if common else [], attrs["role"])
    items = deliver.parse(text, set(required) | set(deliver.DEFAULT_ITEMS))
    branch = ports.branch(cwd)
    if deliver.BRANCH_ITEM in required and not items.get(deliver.BRANCH_ITEM) and branch:
        items[deliver.BRANCH_ITEM] = branch
    missing = deliver.check(items, required)
    notes = [why] if why else []
    if missing:
        print("\n".join(notes + ["送らなかった: 要約に足りない項目がある: " + "、".join(missing),
                                 f"- 必須の項目（{attrs['role']}）: " + "・".join(required)
                                 + "。見出し（## 結論）か行の頭の札（結論: …）で書く。結論は 3 行以内、決め手には原典の URL"]))
        return 2
    try:
        _, _, sessions_, panes, companies, _, more = survey(a.config, ports)
    except herdr.HerdrError as e:
        print(f"止めた: herdr を読めない（{e}）")
        return 1
    notes += more
    sid, entry = deliver.boss_session(attrs, sessions_)
    inbox = attrs.get("boss-inbox")
    if not inbox and entry and entry.get("cwd"):
        boss_common = ports.git.common_dir(entry["cwd"])
        inbox = deliver.inbox_of(boss_common) if boss_common else None
    if not inbox:
        print("\n".join(notes + ["止めた: 頼み元の受付箱が分からない（属性 company.boss-inbox が無く、頼み元の会話も一覧に見えない）"]))
        return 1
    pane, how = deliver.boss_window(attrs, sid, entry, panes, companies)
    ask_id = attrs.get("ask")
    sender = attrs.get("name") or os.path.basename(os.path.normpath(cwd))
    file_id = deliver.new_id(ports.now())   # 納品ごとに別のファイル（打ち直しで前の要約を消さない）
    target = os.path.join(inbox, f"{file_id}-deliver.md")
    line = deliver.deliver_line(ask_id, sender, branch, items, required, target)
    if a.dry_run:
        print("\n".join(notes + [f"送り先: {attrs.get('boss') or '-'}  " + (f"ペイン {pane}（{how}）" if pane else f"窓なし（{how}）"),
                                 f"受付箱: {target}", f"打ち込む 1 行: {line}"]))
        return 0
    path = deliver.put(inbox, os.path.basename(target), deliver.summary_text(items, required))
    status, detail = deliver.send(pane, line, ports.herdr) if pane else ("failed", how)
    deliver.log(inbox, {"id": file_id, "kind": "deliver", "ask": ask_id, "at": ports.now(), "status": status, "detail": detail,
                        "from": {"name": attrs.get("name"), "account": attrs.get("account"), "session": attrs.get("session"),
                                 "branch": branch, "place": cwd},
                        "to": {"name": attrs.get("boss"), "account": attrs.get("boss-account"), "session": sid, "pane": pane},
                        "file": path})
    if ask_id and status == "sent":
        try:
            provision.mark(cwd, gitx.root_of(common), {"delivered": ask_id}, ports.git)
        except (gitx.GitError, OSError) as e:
            notes.append(f"納品済みの印（company.delivered）を書けなかった（{e}）。Stop フックが差し戻し続ける（上限まで）")
    if status != "sent":
        notes.append("要約は受付箱に置いたが、頼み元に知らせられなかったので納品済みにしない。頼み元の窓が開いたら打ち直す")
    print("\n".join(notes + [f"納品 {file_id} → {attrs.get('boss') or '頼み元'}  {status}" + (f"（{detail}）" if detail else ""),
                             f"- 要約: {path}"]))
    return 0 if status == "sent" else 1


def stop_hook(stdin=sys.stdin, out=sys.stdout, attrs_of=gitx.worktree_attrs, tmp_dir=None):
    """プラグインの Stop フック。部署の会話で受けた頼みを納品していなければ、止まるのを差し戻す（{"decision": "block"}）。"""
    payload = json.loads(stdin.read() or "{}")
    cwd = payload.get("cwd") or os.getcwd()
    attrs = attrs_of(cwd)
    if not attrs.get("role") or not attrs.get("ask"):
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
