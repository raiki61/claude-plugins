#!/usr/bin/env python3
"""受け持ちを起動する流れ。入口の dispatch.py --start と --due から呼ぶ。起動方法のフィールド（[skills.start]）の中身は nodes/start.py。

--start <受け持ち>（start_now）: 受け持ちを今起動する（コマンド）。受け持ちは名前か「会社/名前」。会社を省けば打った場所の会社。
--due（due_all）: herdr に開いている会社の、周期（every）の来た受け持ちを全部起動する。何度打っても、周期の来た物だけを 1 回起動する。
  見る時の来たリマインダー（--remind）も、担当者に 1 度だけ知らせる（reminds.notify）。
  刻むのは頼みと納品（due_later）: 入口の --ask と --deliver が通るたびに、--due を会話から切り離して裏で打つ（受付の設計の 9 章）。
  頼みも納品も来ない間も刻みたい人は、手元の OS の予定（macOS の launchd・Linux の cron か systemd の timer・Windows のタスク
  スケジューラ）に、例えば 10 分ごとに --due を打たせる。

起動するのは orders.ask と同じ宛て方（宛先「会社/受け持ちの役」、部署の名前は受け持ちの名前）: その名前の always の部署が在ればその
順番待ちに積み、無ければその名前の部署を立てる。納品の返り先（頼み元の属性）は起動した者でなく report_to。
一度きりの受け持ち（役が always でない）で、前の回の部署がまだ立っている（納品していない・畳まれていない）なら起動しない
（Kubernetes の CronJob の concurrencyPolicy: Forbid と同じ。同じ名前の部署が 2 つ立つと、名前で宛てられなくなる）。
起動したかどうかは、会社の受付箱の台帳に kind start の行で残す（周期の数えもこの行で）。--due が同じ間に 2 つ走っても（頼みと納品が
続けて通る）、会社ごとの錠を持つ方だけが数えて起動し、もう一方はその会社を待たずに飛ばすので、同じ受け持ちを 2 度起動しない。
"""

import argparse
import contextlib
import os
import sys
import time

import filex
import gitx
from ports import chat, term
import orders
import reminds
from nodes import deliver, role, start, tree

DISPATCH_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dispatch.py")
DUE_LOG = "due.log"   # 受付箱の下の、頼みと納品が裏で打った --due の出力の置き場（打つたびに書き足す）
DUE_LOCK = "due.lock"   # 受付箱の下の、--due が会社ごとに掛ける錠（_due_lock）
CALLER_ENV = (chat.SESSION_ENV, term.PANE_ENV, chat.EFFORT_ENV, chat.JOB_ENV)   # 打った会話の印（id・窓・effort・裏の処理の置き場）。裏の --due には渡さない（due_later）


def _skill(info, name):
    return next((s for s in info.get("skills", []) if s["name"] == name), None)


def _text(root, info, st, g):
    """頼みの本文の字か、読めない訳。brief は会社の形と同じ所（origin の既定のブランチ、無ければ代表の clone の作業ツリー）から読む。"""
    if st.get("text"):
        return st["text"], None
    rel = st["brief"]
    ref = g.origin_head(root) if info.get("source") == "origin" else None
    if ref:
        got = g.file_at(root, ref, rel)
        return (got, None) if got is not None else (None, f"頼みの本文 {ref}:{rel} が無い")
    try:
        with open(os.path.join(root, rel), encoding="utf-8") as f:
            return f.read(), None
    except OSError as e:
        return None, f"頼みの本文 {rel} を読めない（{e}）"


def _boss(report_to, company, companies, ports):
    """report_to（名前か「会社/名前」）から頼み元の属性。(属性, 訳か None)。"""
    where, sep, name = report_to.rpartition("/")
    if sep and where:
        hit = [c for c in companies if c["name"] == where or os.path.basename(os.path.normpath(c["root"])) == where]
        if not hit:
            return None, f"返す先の会社「{where}」が {term.NAME} に開いていない"
        company = hit[0]
    common = ports.git.common_dir(company["root"])
    return {"boss": name, "boss-account": None, "boss-session": None, "boss-pane": None,
            "boss-inbox": deliver.inbox_of(common) if common else None}, None


def fire(company, companies, skill, by, ports, a, task, settings):
    """受け持ちを 1 つ起動する。(終了の値 0 起動した・1 起動できなかった・2 起動しなかった〔形の誤りか前の回が立っている〕, 出す行)。
    by は本文の頭と台帳に書く、起動した者（周期かコマンド）。"""
    name, st = skill["name"], skill["start"]
    info = tree.read_info(company["root"], settings, ports.git)
    if not skill.get("role"):
        return 2, [f"止めた: 受け持ち「{name}」に役（role）が無いので起動できない"]
    shape = role.load(info["path"], info["text"])
    the_role = shape["roles"].get(role.current(shape, skill["role"]))
    if the_role is None or the_role.get("machine"):
        return 2, [f"止めた: 受け持ち「{name}」の役「{skill['role']}」が会社の形に無いか、AI の部署を持たない役"]
    running = [d for d in company["departments"] if d["attrs"].get("name") == name]
    if running and role.lifetime_at(the_role, info["skills"], name) != role.ALWAYS and running[0]["attrs"].get("lifecycle") != gitx.PERSISTENT:
        return 2, [f"起動しなかった: 受け持ち「{name}」の前の回の部署がまだ立っている（{running[0]['path']}）。"
                   "納品して畳まれて（--done・--clean --apply）から起動する"]
    text, why = _text(company["root"], info, st, ports.git)
    if why:
        return 1, [f"止めた: {why}"]
    boss, why = _boss(st["report_to"], company, companies, ports)
    if why:
        return 1, [f"止めた: {why}"]
    ask_id = deliver.new_id(ports.now())
    common = ports.git.common_dir(company["root"])
    inbox = deliver.inbox_of(common)
    if a.dry_run:
        return 0, [f"起動する: {company['name']}/{name}（役 {skill['role']}、{by}）→ 納品は {st['report_to']} に返す",
                   f"- 頼みの本文の頭: {start.body(name, by, text).splitlines()[0]}"]
    brief = deliver.put(inbox, f"{ask_id}-start.md", start.body(name, by, text))
    ns = argparse.Namespace(**{**vars(a), "ask": f"{company['name']}/{skill['role']}", "text": None, "brief": brief,
                               "task": name, "branch": start.branch(skill, ask_id), "role": None, "persistent": False,
                               "ask_id": ask_id, "from_boss": boss, "forward": False, "title": f"受け持ち「{name}」の起動（{by}）"})
    rc = orders.ask(ns, ports, company["root"], task)
    deliver.log(inbox, {"kind": "start", "skill": name, "id": ask_id, "by": by, "report_to": st["report_to"],
                        "status": "sent" if rc == 0 else "failed", "at": ports.now()})
    if rc != 0:
        return 1, [f"受け持ち「{name}」を起動しようとしたが、頼みが通らなかった（終了の値 {rc}。上の出力を見る）"]
    return 0, [f"起動した: {company['name']}/{name}（{by}）受付 {ask_id}。納品は {st['report_to']} に返る"]


def _caller(a, ports, cwd, sessions_):
    """--start を打った会話の名前。Claude Code の外（会話の id が無い）は None。"""
    sid = chat.session_of(ports.env)
    if not sid:
        return None
    return a.from_name or orders.place_name(cwd, sid, ports) or ports.caller(sessions_)[1] or "名の無い会話"


def start_now(a, ports, cwd, task):
    """--start。終了の値（0 起動した・1 起動できなかった・2 使い方の誤りか起動しなかった）。"""
    try:
        _, _, sessions_, _, companies, settings, notes = orders.survey(a.config, ports)
    except term.Error as e:
        print(f"止めた: {term.NAME} を読めない（{e}）")
        return 1
    where, sep, name = a.start.strip().rpartition("/")
    if sep and where:
        pool = [c for c in companies if c["name"] == where or os.path.basename(os.path.normpath(c["root"])) == where]
    else:
        common = ports.git.common_dir(cwd)
        here = gitx.root_of(common) if common else None
        pool = [c for c in companies if here and os.path.realpath(c["root"]) == os.path.realpath(here)]
    if not pool:
        print("\n".join(notes + [f"止めた: 受け持ち「{a.start}」の会社が {term.NAME} に開いていない（「会社/受け持ち」で渡すか、会社の場所から打つ）"]))
        return 2
    try:
        company = deliver.one_company(pool, where or pool[0]["name"])
    except deliver.DeliverError as e:
        print("\n".join(notes + [f"止めた: {e}"]))
        return 2
    info = tree.read_info(company["root"], settings, ports.git)
    skill = _skill(info, name)
    if skill is None or not skill.get("start"):
        print("\n".join(notes + [f"注記: {p}" for p in info["problems"]]
                        + [f"止めた: {company['name']} の会社の形に、起動方法（[skills.start]）の有る受け持ち「{name}」が無い"]))
        return 2
    caller = _caller(a, ports, cwd, sessions_)
    refused = bool(skill["start"]["by"]) and caller is not None and caller not in skill["start"]["by"]
    if refused:
        said = f"受け持ち「{name}」をコマンドで起動できるのは {'・'.join(skill['start']['by'])}（会社の形の by）。打った会話は {caller}"
        if not a.dry_run:
            print("\n".join(notes + [f"止めた: {said}"]))
            return 2
        # 試し打ちは止めずに、本当に打てば止まることを書いて、部署を立てる所まで見立てる（c52730 の 2。d9e752）
        notes.append(f"注記: 本当に打てばここで止まる（{said}）。試し打ちなので、この先も見立てる")
    rc, lines = fire(company, companies, skill, f"コマンド（{caller or '人'}）", ports, a, task, settings)
    print("\n".join(notes + lines))
    # 本当に打てば by で止まる試し打ちは、先を見立てても 2 を返す（--land --dry-run と同じく、本当に打った時の終了の値を返す）
    return 2 if refused else rc


@contextlib.contextmanager
def _due_lock(inbox):
    """その会社の --due の錠を、待たずに取る。取れたら True、ほかが持っていれば False を渡す。受付箱が無ければ True（数える台帳も
    無い）。錠は受付箱の下の due.lock に掛け、持つ処理が落ちれば OS が外す。"""
    if not inbox:
        yield True
        return
    with filex.lock(os.path.join(inbox, DUE_LOCK), wait=False) as got:
        yield got


def due_all(a, ports, task):
    """--due。周期の来た受け持ちを全部起動する。終了の値（0 起動できなかった物が無い・1 1 つでも起動できなかった）。"""
    try:
        _, _, _, _, companies, settings, notes = orders.survey(a.config, ports)
    except term.Error as e:
        print(f"止めた: {term.NAME} を読めない（{e}）")
        return 1
    lines, worst, now = list(notes), 0, ports.now()
    for company in companies:
        common = ports.git.common_dir(company["root"])
        inbox = deliver.inbox_of(common) if common else None
        # 台帳を読んでから起動した行を書くまで、ほかの --due に数えさせない（頼みと納品が続けて通ると、裏の --due が並んで走る）。
        # ほかの --due が錠を持っていれば、待たずにその会社を飛ばす（持っている方が、周期の来た物を起動する。待つ処理を積まない）
        with _due_lock(inbox) as got:
            if not got:
                lines.append(f"飛ばした: {company['name']} はほかの --due が数えている")
                continue
            records = deliver.records(inbox) if inbox else []
            for skill in company["skills"]:
                st = skill.get("start")
                if not start.due(st, start.last_started(records, skill["name"]), now):
                    continue
                rc, out = fire(company, companies, skill, f"周期（{st['every']} ごと）", ports, a, task, settings)
                lines += out
                worst = max(worst, 1 if rc == 1 else 0)
            if inbox:
                # 見る時の来たリマインダーを担当者に知らせる（docs/ledger.md の「リマインダー」。同じ錠の中なので 2 度は知らせない）
                try:
                    lines += reminds.notify(inbox, ports.git.common_dir, now, dry_run=a.dry_run,
                                            reach=reminds.asker(company, companies, settings, ports, a, task))
                except (OSError, ValueError) as e:
                    lines.append(f"注記: {company['name']} のリマインダーを知らせられなかった（{e}）")
                    worst = 1
    if len(lines) == len(notes):
        lines.append("周期の来た受け持ちも、見る時の来たリマインダーも無い")
    print("\n".join(lines))
    return worst


def due_later(a, ports, cwd, trigger):
    """入口の --ask か --deliver が通った後に、--due を会話から切り離して裏で打つ（頼みと納品が周期を刻む。終わりを待たない）。
    出力は打った場所の会社の受付箱の due.log に書き足す。trigger は出力の頭に書く、打たせた物（頼みか納品）。
    裏の --due には打った会話の印（会話の id・窓・effort・裏の処理の置き場）を渡さない。effort を渡すと、effort = "inherit" の受け持ちが
    最後に頼んだ会話の effort で起動する。渡すと --due が打った会話から頼んだことになり、打った部署自身の
    受け持ちを起動する頼みが「宛先はこの会話自身」で止まる（OS の予定から打つ --due と同じく、Claude Code の外から打った形にする）。"""
    try:
        common = ports.git.common_dir(cwd)
        if not common:
            return
        log = os.path.join(deliver.inbox_of(common), DUE_LOG)
        argv = [sys.executable, DISPATCH_PY, "--due"] + (["--config", a.config] if a.config else [])
        env = {k: v for k, v in ports.env.items() if k not in CALLER_ENV}
        os.makedirs(os.path.dirname(log), exist_ok=True)
        with open(log, "a", encoding="utf-8") as f:
            f.write(f"--- {time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime(ports.now()))} {trigger}の後\n")
        ports.spawn(argv, cwd, log, env)
    except Exception as e:  # 頼みと納品はもう通った。裏の --due を打てなくても、その終了の値を変えない
        print(f"注記: 周期の来た受け持ちを起動する --due を裏で打てなかった（{e}）。要れば --due を手で打つ")
