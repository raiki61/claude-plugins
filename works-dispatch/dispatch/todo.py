#!/usr/bin/env python3
"""--todo の流れ（入口の dispatch.py から呼ぶ）。受付箱の台帳から頼みの木を作って出す。射影は nodes/ledger、台帳の行の形と
決めた事は docs/ledger.md。

--todo [受付]: 打った場所の会社の受付箱から始め、台帳の行が指すほかの会社の受付箱（本文のファイルの置き場・頼み元の受付箱・
宛先や打った場所の作業場の会社の物）をたどって全部の台帳を読み、頼みの木を出す（herdr は読まない。会社が開いていなくても
台帳だけで組む）。受付を渡せば、その頼みから下だけ（短い 6 桁でもよい）。済んだブランチは出さない（--all で出す）。--json は射影を
JSON で、--html <ファイル> は 1 枚の HTML のページに書く。
--state <状態>（カンマで区切って幾つでも。STATES の名前か画面の字）か --to <宛先>（部署の名前・会社の名前・「会社/名前」）を付けると、
木にせず、当たった頼みを更新の古い順に平らに並べる（--state を省けば開いている状態〔順番待ち・動いている・答え待ち〕、--all なら全部の状態）。
どの形でも、注記とリマインダーの後、一覧の前に数え（状態ごとの件数・済の割合・開いている頼みでいちばん動きの無い物）を出す。数えるのは、受付を渡せばその頼みと子をたどった下の頼み、--to を付ければ宛先の当たる頼みの、
全部の状態の頼み（--state では絞らない。済の割合の分母が要るため）。--json は summary に、--html はページの頭に出す。
頭に、台帳をたどった受付箱の壊れの注記（裏の処理の失敗・誰も受けない頼み・台帳の大きさ。health.py）と、台帳では開いているのに
順番待ちにも作業場にも無い頼み（strays）を「!」で出す。
台帳のリマインダー（--remind）のうち見る時の来た物を、木の前に出す（--all でまだ来ていない物と閉じた物も）。
誰のターンかは出さない（部署の様子は --tree）。作った物は保存せず、開くたびに台帳から作り直す。
"""

import os
import time

import health
import jsonio
from nodes import deliver, ledger, wake
from nodes import remind


def inboxes_from(starts, common_dir, records=deliver.records):
    """starts（受付箱の並び）から、台帳の行が指す受付箱（ledger.inboxes_in）と、行が指す作業場の会社の受付箱（ledger.places_in を
    common_dir で引く。在る場所だけ）を順にたどった並びと、全部の行（ledger.merge した物）。--note が回した先を探すのにも使う。"""
    found, groups, seen, i = list(dict.fromkeys(starts)), [], set(), 0
    while i < len(found):
        rows = records(found[i]) if os.path.isdir(found[i]) else []
        groups.append(rows)
        more = ledger.inboxes_in(rows)
        for place in ledger.places_in(rows):
            if place not in seen and os.path.isdir(place):
                seen.add(place)
                got = common_dir(place)
                if got:
                    more.append(deliver.inbox_of(got))
        found += [x for x in dict.fromkeys(more) if x not in found and os.path.isdir(x)]
        i += 1
    return found, ledger.merge(*groups)


def questions(row):
    """holders のフィールドの無い古い納品の行の残った疑問の担当者（要約のファイルから読む）。"""
    try:
        with open(row.get("file") or "", encoding="utf-8") as f:
            text = f.read()
    except (OSError, UnicodeDecodeError):
        return []
    return deliver.open_holders(deliver.parse(text, {deliver.OPEN}).get(deliver.OPEN))


def strays(view, rows, inboxes, isdir=os.path.isdir):
    """台帳の射影が開いていると出すのに、順番待ちの件も受けた作業場も無い頼みの注記の並び。順番待ちと出るのに、どの受付箱の順番待ちの置き場にも無い物と、
    動いている・答え待ちと出るのに、受けた作業場がもう無い物。どちらも台帳に閉じる行が無いまま残った物で、--withdraw で閉じる
    （渡す物も納品する部署も無いので、ほかの行では閉じない。docs/ledger.md の「台帳と、順番待ち・作業場が食い違うとき」）。"""
    out = []
    for i, t in view["tasks"].items():
        if t["state"] == "queued" and not any(wake.find(x, i) for x in inboxes):
            out.append(f"受付 {i} は順番待ちと出るが、どの順番待ちの置き場にも無い（--withdraw {i} で閉じる）")
        elif t["state"] in ("working", "waiting"):
            place = ledger.received_at(rows, i)
            if place and not isdir(place):
                out.append(f"受付 {i} は{t['label']}と出るが、受けた作業場 {place} がもう無い（--withdraw {i} で閉じる）")
    return out


def when(at):
    return time.strftime("%m-%d %H:%M", time.localtime(at)) if at else "-"


def todo(a, ports, cwd):
    """--todo。終了の値を返す。"""
    common = ports.git.common_dir(cwd)
    if not common:
        print(f"止めた: {cwd} が git でないので、受付箱が決まらない（会社の本社か部署の場所から打つ）")
        return 2
    inboxes, rows = inboxes_from([deliver.inbox_of(common)], ports.git.common_dir)
    view = ledger.build(rows, title_of=lambda f: deliver.task_title(f, 60), questions_of=questions)
    top = None
    if a.todo:
        hits = [i for i in view["tasks"] if i == a.todo or i.endswith("-" + a.todo)]
        if len(hits) != 1:
            print(f"止めた: 受付 {a.todo} が台帳に" + ("無い" if not hits else f" {len(hits)} 件ある（長い受付番号で渡す）"))
            return 2
        top = hits[0]
    now = ports.now()
    states = None
    if getattr(a, "state", None):
        states = [ledger.state_of(w.strip()) for w in a.state.split(",") if w.strip()]
        if not states or None in states:
            print(f"止めた: --state {a.state} に知らない状態が在る（使える物: "
                  + "・".join(f"{k}（{v[0]}）" for k, v in ledger.STATES.items()) + "）")
            return 2
    to = getattr(a, "to", None)
    ids = ledger.scope(view, top, to)
    counted = ledger.tally(view, ids, now)
    filtering = states is not None or bool(to)
    if filtering and states is None:
        states = list(ledger.STATES) if a.all else ["queued", "working", "waiting"]
    if a.html:
        forest = ledger.flat(view, ids, states) if filtering else ledger.select(view, top, everything=True)
        made = time.strftime("%Y-%m-%d %H:%M", time.localtime(now))
        try:
            with open(os.path.expanduser(a.html), "w", encoding="utf-8") as f:
                f.write(ledger.page(forest, view, made, when, everything=filtering or a.all or top is not None, counted=counted,
                                    flat=filtering))
        except OSError as e:
            print(f"止めた: ページを書けない（{e}）")
            return 1
        print(f"頼みの木のページを書いた: {a.html}（台帳 {len(inboxes)} つから {len(view['tasks'])} 件）")
        return 0
    forest = ledger.flat(view, ids, states) if filtering else ledger.select(view, top, everything=a.all or top is not None)
    # 裏の処理の失敗・誰も受けない頼み・台帳の大きさ。受付箱が 2 つ以上なら、どの受付箱の話かを頭に付ける
    notes = [(f"{x}: " if len(inboxes) > 1 else "") + n for x in inboxes for n in health.inbox_notes(x, now)] + strays(view, rows, inboxes)
    rems = [] if top else reminders(rows, view, now, everything=a.all)
    if a.json:
        jsonio.dump({"schema": ledger.SCHEMA, "inboxes": inboxes, "notes": notes, "forest": forest, "reminders": rems,
                     "summary": {**counted, "filter": {"states": states, "to": to} if filtering else None}}, None)
        return 0
    out = ledger.lines(forest, when, now if filtering else None)
    empty = "当たる頼みは無い" if filtering else "開いている頼みは無い（済んだ物は --all で出す）"
    print("\n".join([f"! {n}" for n in notes] + reminder_lines(rems) + [ledger.tally_line(counted), ""] + (out or [empty])))
    return 0


def reminders(rows, view, now, everything=False):
    """台帳のリマインダーの並び（立てた順）。開いていて見る時の来た物だけ。everything なら、まだ来ていない物と閉じた物も。
    各々に、見る時が来た訳 due（来ていなければ None）を添える。"""
    out = []
    for r in remind.project(rows).values():
        why = remind.came(r, view["tasks"], now)
        if everything or why:
            out.append({**r, "due": why})
    return out


def reminder_lines(rems):
    """--todo の頭に出すリマインダーの行。"""
    if not rems:
        return []
    out = ["リマインダー:"]
    for r in rems:
        mark = "閉じた" if r["closed"] else "見る時" if r["due"] else "待ち"
        text = r["text"] if len(r["text"]) <= 60 else r["text"][:60] + "…"
        out.append(f"- [{mark}] {text}  {r['id']}  担当者 {r['holder'] or '-'}（{r['due'] or remind.waits_for(r)}）")
    return out + [""]
