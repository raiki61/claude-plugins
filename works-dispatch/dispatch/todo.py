#!/usr/bin/env python3
"""--todo の流れ（入口の dispatch.py から呼ぶ）。受付箱の台帳から頼みの木を作って出す。射影は nodes/ledger、台帳の行の形と
決めた事は docs/ledger.md。

--todo [受付]: 打った場所の会社の受付箱から始め、台帳の行が指すほかの会社の受付箱（本文のファイルの置き場・頼み元の受付箱・
宛先や打った場所の作業場の会社の物）をたどって全部の台帳を読み、頼みの木を出す（herdr は読まない。会社が開いていなくても
台帳だけで組む）。受付を渡せば、その頼みから下だけ（短い 6 桁でもよい）。済んだブランチは出さない（--all で出す）。--json は射影を
JSON で、--html <ファイル> は 1 枚の HTML のページに書く。
頭に、台帳をたどった受付箱の壊れの注記（裏の処理の失敗・誰も受けない頼み・台帳の大きさ。health.py）と、台帳では開いているのに
順番待ちにも作業場にも無い頼み（strays）を「!」で出す。
誰のターンかは出さない（部署の様子は --tree）。作った物は保存せず、開くたびに台帳から作り直す。
"""

import os
import time

import health
import jsonio
from nodes import deliver, ledger, wake


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
    if a.html:
        forest = ledger.select(view, top, everything=True)
        made = time.strftime("%Y-%m-%d %H:%M", time.localtime(ports.now()))
        try:
            with open(os.path.expanduser(a.html), "w", encoding="utf-8") as f:
                f.write(ledger.page(forest, view, made, when, everything=a.all or top is not None))
        except OSError as e:
            print(f"止めた: ページを書けない（{e}）")
            return 1
        print(f"頼みの木のページを書いた: {a.html}（台帳 {len(inboxes)} つから {len(view['tasks'])} 件）")
        return 0
    forest = ledger.select(view, top, everything=a.all or top is not None)
    now = ports.now()
    # 裏の処理の失敗・誰も受けない頼み・台帳の大きさ。受付箱が 2 つ以上なら、どの受付箱の話かを頭に付ける
    notes = [(f"{x}: " if len(inboxes) > 1 else "") + n for x in inboxes for n in health.inbox_notes(x, now)] + strays(view, rows, inboxes)
    if a.json:
        jsonio.dump({"schema": ledger.SCHEMA, "inboxes": inboxes, "notes": notes, "forest": forest}, None)
        return 0
    out = ledger.lines(forest, when)
    print("\n".join([f"! {n}" for n in notes] + (out or ["開いている頼みは無い（済んだ物は --all で出す）"])))
    return 0
