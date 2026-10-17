#!/usr/bin/env python3
"""受け持ちを起こす流れ。入口の dispatch.py --start と --due から呼ぶ。起こし方の欄（[skills.start]）の中身は nodes/start.py。

--start <受け持ち>（start_now）: 受け持ちを今起こす（命令）。受け持ちは名前か「会社/名前」。会社を省けば打った場所の会社。
--due（due_all）: herdr に開いている会社の、周期（every）の来た受け持ちを全部起こす。刻むのは works-dispatch でなく、その人の
  手元の OS の予定（macOS の launchd・Linux の cron か systemd の timer・Windows のタスク スケジューラ）で、例えば 10 分ごとに
  --due を打たせる。何度打っても、周期の来た物だけを 1 回起こす。

起こすのは orders.ask と同じ宛て方（宛先「会社/受け持ちの役」、部署の名前は受け持ちの名前）: その名前の常設の部署が在ればその
順番待ちに積み、無ければその名前の部署を立てる。納品の返り先（頼み元の属性）は起こした者でなく report_to。
一度きりの受け持ち（役が常設でない）で、前の回の部署がまだ立っている（納品していない・畳まれていない）なら起こさない
（Kubernetes の CronJob の concurrencyPolicy: Forbid と同じ。同じ名前の部署が 2 つ立つと、名前で宛てられなくなる）。
起こしたかどうかは、会社の受付箱の台帳に kind start の行で残す（周期の数えもこの行で）。
"""

import argparse
import os

import gitx
import herdr
import orders
from nodes import deliver, role, start, tree


def _skill(info, name):
    return next((s for s in info.get("skills", []) if s["name"] == name), None)


def _text(root, info, st):
    """頼みの本文の字か、読めない訳。brief は会社の形と同じ所（origin の既定の枝、無ければ代表の clone の作業ツリー）から読む。"""
    if st.get("text"):
        return st["text"], None
    rel = st["brief"]
    ref = gitx.origin_head(root) if info.get("source") == "origin" else None
    if ref:
        got = gitx.file_at(root, ref, rel)
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
            return None, f"返す先の会社「{where}」が herdr に開いていない"
        company = hit[0]
    common = ports.git.common_dir(company["root"])
    return {"boss": name, "boss-account": None, "boss-session": None, "boss-pane": None,
            "boss-inbox": deliver.inbox_of(common) if common else None}, None


def fire(company, companies, skill, by, ports, a, task, settings):
    """受け持ちを 1 つ起こす。(終了の値 0 起こした・1 起こせなかった・2 起こさなかった〔形の誤りか前の回が立っている〕, 出す行)。
    by は本文の頭と台帳に書く、起こした者（周期か命令）。"""
    name, st = skill["name"], skill["start"]
    info = tree.read_info(company["root"], settings)
    if not skill.get("role"):
        return 2, [f"止めた: 受け持ち「{name}」に役（role）が無いので起こせない"]
    shape = role.load(info["path"], info["text"])
    the_role = shape["roles"].get(role.current(shape, skill["role"]))
    if the_role is None or the_role.get("machine"):
        return 2, [f"止めた: 受け持ち「{name}」の役「{skill['role']}」が会社の形に無いか、AI の部署を持たない役"]
    running = [d for d in company["departments"] if d["attrs"].get("name") == name]
    if running and not the_role.get("resident") and running[0]["attrs"].get("residency") != "resident":
        return 2, [f"起こさなかった: 受け持ち「{name}」の前の回の部署がまだ立っている（{running[0]['path']}）。"
                   "納品して畳まれて（--done・--clean --apply）から起こす"]
    text, why = _text(company["root"], info, st)
    if why:
        return 1, [f"止めた: {why}"]
    boss, why = _boss(st["report_to"], company, companies, ports)
    if why:
        return 1, [f"止めた: {why}"]
    ask_id = deliver.new_id(ports.now())
    common = ports.git.common_dir(company["root"])
    inbox = deliver.inbox_of(common)
    if a.dry_run:
        return 0, [f"起こす: {company['name']}/{name}（役 {skill['role']}、{by}）→ 納品は {st['report_to']} に返す",
                   f"- 頼みの本文の頭: {start.body(name, by, text).splitlines()[0]}"]
    brief = deliver.put(inbox, f"{ask_id}-start.md", start.body(name, by, text))
    ns = argparse.Namespace(**{**vars(a), "ask": f"{company['name']}/{skill['role']}", "text": None, "brief": brief,
                               "task": name, "branch": start.branch(skill, ask_id), "role": None, "resident": False,
                               "ask_id": ask_id, "from_boss": boss, "forward": False})
    rc = orders.ask(ns, ports, company["root"], task)
    deliver.log(inbox, {"kind": "start", "skill": name, "id": ask_id, "by": by, "report_to": st["report_to"],
                        "status": "sent" if rc == 0 else "failed", "at": ports.now()})
    if rc != 0:
        return 1, [f"受け持ち「{name}」を起こそうとしたが、頼みが通らなかった（終了の値 {rc}。上の出力を見る）"]
    return 0, [f"起こした: {company['name']}/{name}（{by}）受付 {ask_id}。納品は {st['report_to']} に返る"]


def _caller(a, ports, cwd, sessions_):
    """--start を打った会話の名前。Claude Code の外（会話の id が無い）は None。"""
    sid = ports.env.get("CLAUDE_CODE_SESSION_ID")
    if not sid:
        return None
    return a.from_name or orders.place_name(cwd, sid, ports) or ports.caller(sessions_)[1] or "名の無い会話"


def start_now(a, ports, cwd, task):
    """--start。終了の値（0 起こした・1 起こせなかった・2 使い方の誤りか起こさなかった）。"""
    try:
        _, _, sessions_, _, companies, settings, notes = orders.survey(a.config, ports)
    except herdr.HerdrError as e:
        print(f"止めた: herdr を読めない（{e}）")
        return 1
    where, sep, name = a.start.strip().rpartition("/")
    if sep and where:
        pool = [c for c in companies if c["name"] == where or os.path.basename(os.path.normpath(c["root"])) == where]
    else:
        common = ports.git.common_dir(cwd)
        here = gitx.root_of(common) if common else None
        pool = [c for c in companies if here and os.path.realpath(c["root"]) == os.path.realpath(here)]
    if not pool:
        print("\n".join(notes + [f"止めた: 受け持ち「{a.start}」の会社が herdr に開いていない（「会社/受け持ち」で渡すか、会社の場所から打つ）"]))
        return 2
    company = pool[0]
    info = tree.read_info(company["root"], settings)
    skill = _skill(info, name)
    if skill is None or not skill.get("start"):
        print("\n".join(notes + [f"注記: {p}" for p in info["problems"]]
                        + [f"止めた: {company['name']} の会社の形に、起こし方（[skills.start]）の有る受け持ち「{name}」が無い"]))
        return 2
    caller = _caller(a, ports, cwd, sessions_)
    refused = bool(skill["start"]["by"]) and caller is not None and caller not in skill["start"]["by"]
    if refused:
        said = f"受け持ち「{name}」を命令で起こせるのは {'・'.join(skill['start']['by'])}（会社の形の by）。打った会話は {caller}"
        if not a.dry_run:
            print("\n".join(notes + [f"止めた: {said}"]))
            return 2
        # 試し打ちは止めずに、本当に打てば止まることを書いて、部署を立てる所まで見立てる（c52730 の 2。d9e752）
        notes.append(f"注記: 本当に打てばここで止まる（{said}）。試し打ちなので、この先も見立てる")
    rc, lines = fire(company, companies, skill, f"命令（{caller or '人'}）", ports, a, task, settings)
    print("\n".join(notes + lines))
    # 本当に打てば by で止まる試し打ちは、先を見立てても 2 を返す（--land --dry-run と同じく、本当に打った時の終了の値を返す）
    return 2 if refused else rc


def due_all(a, ports, task):
    """--due。周期の来た受け持ちを全部起こす。終了の値（0 起こせなかった物が無い・1 1 つでも起こせなかった）。"""
    try:
        _, _, _, _, companies, settings, notes = orders.survey(a.config, ports)
    except herdr.HerdrError as e:
        print(f"止めた: herdr を読めない（{e}）")
        return 1
    lines, worst, now = list(notes), 0, ports.now()
    for company in companies:
        common = ports.git.common_dir(company["root"])
        records = deliver.records(deliver.inbox_of(common)) if common else []
        for skill in company["skills"]:
            st = skill.get("start")
            if not start.due(st, start.last_started(records, skill["name"]), now):
                continue
            rc, out = fire(company, companies, skill, f"周期（{st['every']} ごと）", ports, a, task, settings)
            lines += out
            worst = max(worst, 1 if rc == 1 else 0)
    if len(lines) == len(notes):
        lines.append("周期の来た受け持ちは無い")
    print("\n".join(lines))
    return worst
