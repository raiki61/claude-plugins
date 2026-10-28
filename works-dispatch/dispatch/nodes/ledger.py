#!/usr/bin/env python3
"""ledger ノード: 受付箱の台帳（log.jsonl の行。会社をまたいで足し合わせた物）から、頼みの木と、頼みごとの今の状態を組み立てる射影。
外には書かない。

正本は台帳の行で、ここが作る物（頼みの木と状態）は保存しない。開くたびに台帳を頭から読み直して作る（Fowler の Complete Rebuild、
Marten の Live の射影）。行の形・種類・つなぎ方の決まりは docs/ledger.md。

- 頼み: kind ask の行の id（受付番号）。同じ受付の行が 2 つの会社の台帳に在ることがある（頼んだ会社と受けた会社）ので、id で 1 つにまとめる。
- 状態: 頼みごとに、状態を変える行を時刻の順に当て、最後に当たった物（Linear の "based on the last emitted activity" と同じ考え）。
  済・取り下げ・回した（forwarded）は終わりで、後の行で戻さない。状態の名前と、JSCalendar の Task の progress への対応は STATES。
- 親: 頼みの行の cause（その頼みを打った場所が、そのとき受けていた頼み。Marten・KurrentDB の causation id）、--forward で回した
  forwarded の行（回した元が親）。cause のフィールドの無い古い行は、打った場所と名前が同じ部署が、その時より前に最後に受けた頼みを親と見る
  （wake_hook.open_children と同じ見分け。parent_by は inferred）。頼みの行の causes（束の合図で回した頼み）の頼みにも子として並べる
  （木の親は cause の 1 つのまま）。
- 続き: 納品の残った疑問の担当者が受付番号なら、その頼みを続き（follows）に結ぶ。リマインダーの受付なら、リマインダーの続き
  （reminders。頼みの木には入れない）に結ぶ。担当者が部署や持ち主の物は questions に残すだけで、開いている物には数えない（閉じる行が
  台帳に無いため）。
- 開いているか（open）: 自分が終わっていないか、子か続きのどれかが開いているか、続きのリマインダーが閉じていない。届かなかった頼み（failed）は、打った会話がその場で
  知るので、開いている物に数えない。
"""

import html
import json
import os
import re

SCHEMA = 1

# 頼みの状態。値は (画面の字, JSCalendar〔RFC 8984〕の Task の progress)
STATES = {
    "queued": ("順番待ち", "needs-action"),
    "working": ("動いている", "in-process"),
    "waiting": ("答え待ち", "in-process"),
    "done": ("済", "completed"),
    "dropped": ("取り下げ", "cancelled"),
    "failed": ("届かず", "failed"),
}
FINAL = ("done", "dropped")

# 台帳の行の種類（kind）と、行が指す頼みの受付を持つフィールド。None は頼みを指さない行（部署やツールの出来事）。
# 知らせ（to が字の行。宛先の待ち受けが拾う）の id は、どの種類でも頼みか足しの受付（リマインダーの知らせならリマインダーの受付。
# 頼みを指さない知らせは None）
KINDS = {
    "ask": "id",          # 頼んだ（status: sent 届いた・queued 順番待ちに積んだ・failed 届かなかった）。cause は親の頼み
    "queued": "id",       # 知らせ: 順番待ちに積んだ
    "handed": "id",       # 待ち受けが順番待ちの頼みを部署の会話に渡した
    "held": "id",         # 待ち受けが渡さずに待った（detail に訳）
    "taken": "id",        # 順番待ちから取り出した（--take。その場で受けたなら動いている）
    "reordered": "id",    # 順番待ちの先頭に回した（--first）
    "withdrawn": "id",    # 頼みを取り下げた（--withdraw。順番待ちに無い物は was に前の状態、why に訳）
    "forwarded": "id",    # 受けた頼み（id）を回して閉じた。child が回した先の頼み
    "deliver": "ask",     # 納品した（id は要約のファイルの受付、ask が頼み。for は回して閉じた頼みへの返し、parked は保留にした頼みへの返し、
                          # status self は頼み元がこの部署自身で知らせずに閉じた）。知らせの行は id が頼み
    "note": "ask",        # 足した（id は足しの受付、ask が頼み）
    "waiting": "id",      # 部署が頼みを人の答え待ちと印した（--wait。why に訳。parked は --park で保留にして次の頼みを受けた）
    "resumed": "id",      # 人の文で答え待ちの印が外れた
    "nudged": "id",       # 止まった部署を動かした（--nudge）
    "knot": "id",         # 返事待ちの輪をほどくため、輪の頼みを --take で回した
    "start": "id",        # 起動方法の有る受け持ちを起動した（--start・--due）
    "moved": None,        # 部署の会話を別のアカウントで起動し直した（--move）
    "followed": None,     # 待ち受けが永続の部署の作業場をメインブランチの先頭へ進めた・進めなかった（detail に訳、next に順番待ちの先頭の頼み。wake_hook.follow_main）
    "keepalive": None,    # 待ち受けが仕事の終わらない部署・窓口に keepalive を送った（ask に受けている頼み、sent に何回目か、
                          # tasks に待つ物〔裏の処理の id、受けた頼みの ask:<受付>、出した頼みの child:<受付>、保留の頼みの parked:<受付>〕。
                          # 借りるか買うかの部品が答えたら spent に送った費用の累計〔ドル〕と reason に部品の訳、答えなければ limit に上限と
                          # fixed に答えない訳。compact に compact を打たなかった・打った訳〔部品の reason か聞けなかった訳〕。
                          # status stopped は止めた〔部品が buy と答えたか上限〕、skipped は送らなかった〔detail に訳〕、asked は keepalive の
                          # 代わりに compact の焦点を問うた、answered は問いへの答え〔answer〕を読んで部品に聞き直した、compacted は判断で
                          # compact を打った、compact-failed は判断で付けた compact の印を打てずに外した〔detail に訳〕。asked と compacted の
                          # 行で when が turn-end なのは、keepalive の時刻でなくターンの終わりの判断〔Warm._turn_end〕。wake_hook.Warm・
                          # warm_for・consult_answer・compact_turn）。
                          # 機械が書くので、頼みの更新の時刻を進めない
    "hopped": None,       # 前の版の待ち受けが、今入っている版の待ち受けに替わった（from・to に版の置き場。wake_hook.newer_self）
    "retired": None,      # エフェメラルの部署を畳んだ（--retire）
    "call": None,         # 機械窓口のツールを呼んで片づいた（--call）
    "miss": None,         # 機械窓口のツールが片づかなかった
    "remind": None,       # リマインダーを立てた（--remind。id はリマインダーの受付で、頼みではない。nodes/remind）
    "reminded": None,     # 見る時の来たリマインダーを担当者に知らせた（--due）
    "remind-done": None,  # リマインダーを閉じた（--remind-done）
    "handover": None,     # 部署か窓口の受け持ちをほかの部署へ移した（--handover。status は started と done。nodes/handover.py）。
                          # 移すときに写し直した知らせの行は、元の行の種類のまま handover に引き継ぎの id、copied に元の行の鍵を持つ
}

SHORT_ID = re.compile(r"(?<![0-9a-f-])[0-9a-f]{6}(?![0-9a-f])")


def subject(row):
    """行が指す頼みの受付（無ければ None）。"""
    field = KINDS.get(row.get("kind"))
    if isinstance(row.get("to"), str):   # 知らせの行
        return row.get("id")
    return row.get(field) if field else None


def merge(*groups):
    """いくつかの台帳の行を 1 つの並びにする（時刻の順。同じ中身の行は 1 つ。回した行や足しの行は、打った会社と頼み元の会社の
    台帳の両方に書くため）。"""
    seen, out = set(), []
    for rows in groups:
        for r in rows:
            key = json.dumps(r, ensure_ascii=False, sort_keys=True)
            if key not in seen:
                seen.add(key)
                out.append(r)
    return sorted(out, key=lambda r: r.get("at") or 0)


def inboxes_in(rows):
    """行が指すほかの受付箱（本文のファイルの置き場と、頼み元の受付箱）の並び。会社をまたいで台帳をたどるのに使う。"""
    found = []
    for r in rows:
        boss = r.get("boss") if isinstance(r.get("boss"), dict) else {}
        for path in (r.get("file"), boss.get("inbox")):
            if not isinstance(path, str) or not path:
                continue
            d = path if path.rstrip(os.sep).endswith(os.path.join("company", "inbox")) else os.path.dirname(path)
            if d.rstrip(os.sep).endswith(os.path.join("company", "inbox")) and d not in found:
                found.append(d)
    return found


def places_in(rows):
    """行が指す作業場（頼みの宛先の場所・打った場所・渡した場所）の並び。その会社の受付箱を git から引くのに使う（片方の会社から
    だけ頼んだ相手の台帳は、行の本文のファイルからはたどれないため）。"""
    found = []
    for r in rows:
        to = r.get("to") if isinstance(r.get("to"), dict) else {}
        frm = r.get("from") if isinstance(r.get("from"), dict) else {}
        for path in (to.get("path"), frm.get("place"), r.get("place")):
            if isinstance(path, str) and path and path not in found:
                found.append(path)
    return found


def received_at(rows, i):
    """頼み i を最後に受けた（か、受ける）作業場のパス（無ければ None）。宛先の作業場（ask の行の to.path。届かなかった行は除く）と、
    待ち受けが渡した場所（handed の行の place）のうち、時刻の順で最後の物。"""
    place = None
    for r in rows:
        if r.get("kind") == "ask" and r.get("id") == i and isinstance(r.get("to"), dict) and r.get("status") != "failed":
            place = r["to"].get("path") or place
        elif r.get("kind") == "handed" and r.get("id") == i and isinstance(r.get("place"), str):
            place = r["place"] or place
        elif r.get("kind") == "taken" and r.get("id") == i and _took_here(r):
            place = r["by"]["place"]
    return place


def _took_here(row):
    """taken の行が、部署の場所から打った --take でその場で受けた物か（to が受けた部署の名前で、by に打った場所が在る）。"""
    to, by = row.get("to"), row.get("by")
    return (isinstance(to, dict) and "ask" not in to and isinstance(by, dict) and isinstance(by.get("place"), str)
            and bool(by["place"]))


def _inside(at, root):
    at, root = os.path.normpath(at or ""), os.path.normpath(root or "")
    return bool(at and root) and (at == root or at.startswith(root + os.sep))


def _short(asks, h):
    """担当者の字の 6 桁の短い受付番号を、頼みの受付に引く（ちょうど 1 つに当たるときだけ）。holders のフィールドの無い古い納品の行にだけ使う。"""
    for m in SHORT_ID.findall(h):
        hits = [i for i in asks if i.endswith("-" + m)]
        if len(hits) == 1:
            return hits[0]
    return None


def build(rows, title_of=None, questions_of=None, reminders=None):
    """行の並び（merge した物）から射影 {"schema", "tasks": {受付: 頼み}, "roots": [受付], "reminders": {受付: リマインダー}} を作る。
    reminders は同じ行の remind.project の物（{受付: リマインダー}。流れの側が渡す。省けば結ばない）で、頼みの木には入れず、納品の
    残った疑問の担当者に書かれた物を頼みの reminders に結ぶ。題は頼みの行の title。title_of(本文のファイル) は
    題を返し、title の無い古い行にだけ使う。
    questions_of(納品の行) は残った疑問の担当者の並び [{"holder", "ask"}]（行の holders のフィールドと同じ形）を返す。holders のフィールドの無い古い行に
    だけ使う（どちらも省けば使わない）。"""
    tasks, received = {}, []
    for r in rows:
        if r.get("kind") != "ask" or not r.get("id") or isinstance(r.get("to"), str):
            continue
        t = tasks.get(r["id"])
        to = r.get("to") if isinstance(r.get("to"), dict) else {}
        if t is None:
            tasks[r["id"]] = _task(r["id"], r, (r.get("from") or {}).get("name"), to)
        else:
            if to.get("name"):
                t["to"] = {"company": to.get("company"), "name": to.get("name")}
            t["file"] = t["file"] or r.get("file")
            t["title"] = t["title"] or r.get("title")
    for r in rows:
        # 回した元の頼みの行が、読んだ台帳に無い（ほかの会社の台帳にだけ在る）: 回した行から頼みの行を組み立てる（回した先をたどれるように）
        if r.get("kind") == "forwarded" and r.get("id") and r["id"] not in tasks:
            boss = r.get("boss") if isinstance(r.get("boss"), dict) else {}
            to = r.get("from") if isinstance(r.get("from"), dict) else {}
            tasks[r["id"]] = _task(r["id"], {"at": r.get("at"), "cause": None}, boss.get("name"), {"name": to.get("name")})
    for r in rows:
        kind, at, i = r.get("kind"), r.get("at"), subject(r)
        t = tasks.get(i)
        if t is None or r.get("copied"):   # 引き継ぎで写し直した知らせは、元の行で数えた
            continue
        t["updated"] = max(t["updated"] or 0, at or 0)
        if t["state"] in FINAL or t["state"] == "forwarded":
            if kind == "note":
                t["notes"] += 1
            continue
        if kind == "ask" and not isinstance(r.get("to"), str):
            t["state"] = {"sent": "working", "queued": "queued", "failed": "failed"}.get(r.get("status"), t["state"])
            to = r.get("to") or {}
            if r.get("status") == "sent" and to.get("path"):
                received.append((at, to["path"], to.get("name"), i))
        elif kind == "handed":
            t["state"] = "working"
            if r.get("place"):
                received.append((at, r["place"], t["to"].get("name"), i))
        elif kind == "taken" and t["state"] == "queued" and _took_here(r):
            # 部署の場所から --take で取り、その場で受けた（--ask で頼み直したときは、頼み直しの ask の行が状態を決める）
            t["state"] = "working"
            received.append((at, r["by"]["place"], r["to"].get("name"), i))
        elif kind == "waiting":
            t["state"], t["why"] = "waiting", r.get("why")
        elif kind == "resumed" and t["state"] == "waiting":
            t["state"] = "working"
        elif kind == "withdrawn":
            t["state"] = "dropped"
        elif kind == "forwarded":
            t["state"] = "forwarded"
        elif kind == "deliver" and isinstance(r.get("to"), str):
            t["state"] = "done"
        elif kind == "deliver" and r.get("status") != "failed" and not r.get("for"):
            t["state"] = "done"
        elif kind == "note":
            t["notes"] += 1
        if t["closed"] is None and (t["state"] in FINAL or t["state"] == "forwarded"):
            t["closed"] = at
    # 親: 回した行が先、次に頼みの行の cause、どちらも無い古い行は打った場所と名前から（その場所がその時受けていて、まだ閉じて
    # いない頼み。窓口のように頼みを受けては返す永続の部署の会話が、閉じた前の頼みの子として頼みを出したと読まない）
    for r in rows:
        if r.get("kind") == "forwarded" and r.get("id") in tasks and r.get("child") in tasks:
            _link(tasks, r["id"], r["child"], "forwarded")
    received.sort(key=lambda x: x[0] or 0)
    for t in sorted(tasks.values(), key=lambda t: t["created"] or 0):
        if t["parent"]:
            continue
        row = t["_row"]
        if "cause" in row:
            if row["cause"] in tasks:
                _link(tasks, row["cause"], t["id"], "cause")
            continue
        frm = row.get("from") or {}
        got = [x for x in received if (x[0] or 0) <= (t["created"] or 0) and x[3] != t["id"]
               and _inside(frm.get("place"), x[1]) and (not x[2] or x[2] == frm.get("name"))
               and (tasks[x[3]]["closed"] is None or tasks[x[3]]["closed"] > (t["created"] or 0))]
        if got and frm.get("place"):
            _link(tasks, got[-1][3], t["id"], "inferred")
    # 並べた親: 頼みの行の causes（束の合図で回した頼み。どの部署の変更が原因か分からないので、乗った部署の頼みにも子として並べる）。
    # 木の親（parent）は cause の 1 つのまま
    for t in tasks.values():
        for extra in t["_row"].get("causes") or []:
            if extra in tasks and extra not in (t["id"], t["parent"]) and not _below(tasks, t["id"], extra) \
                    and t["id"] not in tasks[extra]["children"]:
                tasks[extra]["children"].append(t["id"])
    # 続き: 納品の残った疑問の担当者の受付（頼みか、リマインダー）
    rems = reminders or {}
    for r in rows:
        if r.get("kind") != "deliver" or isinstance(r.get("to"), str) or r.get("ask") not in tasks or r.get("status") == "failed":
            continue
        field = isinstance(r.get("holders"), list)
        qs = r["holders"] if field else (questions_of(r) if questions_of else [])
        t = tasks[r["ask"]]
        for q in qs or []:
            # 6 桁の短い受付番号を担当者の字から拾うのは、holders のフィールドの無い古い行（要約の文から読んだ担当者）だけ。フィールドの
            # 担当者は頭書きの holder（受付番号は ask に入る）で、名前の中の 16 進の 6 字を受付と取り違えない（2026-10-19 の 4 つの受付箱で、
            # 拾えたのは古い行の 21 件だけで、フィールドの行は 0 件。受付 0715c5）
            got = q.get("ask") or (None if field else _short(tasks, q.get("holder") or ""))
            entry = {"holder": q.get("holder"), "ask": got if got in tasks or got in rems else None}
            t["questions"].append(entry)
            ties = t["reminders"] if got in rems else t["follows"]
            if entry["ask"] and entry["ask"] != t["id"] and entry["ask"] not in ties:
                ties.append(entry["ask"])
    for t in tasks.values():
        if t["state"] == "forwarded":
            t["state"] = "done"
            t["forwarded"] = True
        t["state"] = t["state"] or "working"
        if title_of and t["file"] and not t["title"]:
            t["title"] = title_of(t["file"])   # 題のフィールドの無い古い頼みの行は、本文のファイルから読む
        t.pop("_row", None)
    memo = {}
    for i in tasks:
        _open(tasks, i, memo, set(), rems)
    for i, t in tasks.items():
        t["open"] = memo[i]
        t["label"], t["progress"] = STATES[t["state"]]
    roots = [i for i, t in tasks.items() if not t["parent"]]
    return {"schema": SCHEMA, "tasks": tasks, "roots": roots, "reminders": rems}


def _task(i, row, sender, to):
    return {"id": i, "title": row.get("title"), "state": None, "created": row.get("at"), "updated": row.get("at"), "parent": None,
            "parent_by": None, "children": [], "follows": [], "reminders": [], "questions": [], "notes": 0, "from": sender,
            "to": {"company": to.get("company"), "name": to.get("name")}, "file": row.get("file"), "why": None, "closed": None,
            "_row": row}


def _link(tasks, parent, child, by):
    if parent == child or tasks[child]["parent"] or _below(tasks, child, parent):
        return
    tasks[child]["parent"], tasks[child]["parent_by"] = parent, by
    tasks[parent]["children"].append(child)


def _below(tasks, top, i):
    """i が top の子孫か（親をつなぐと輪になるかの確かめ）。"""
    seen = set()
    while i and i not in seen:
        if i == top:
            return True
        seen.add(i)
        i = tasks[i]["parent"]
    return False


def _open(tasks, i, memo, visiting, rems):
    if i in memo:
        return memo[i]
    t = tasks[i]
    own = t["state"] not in FINAL + ("failed",) or held({"reminders": rems}, t)
    if i in visiting:   # 続きが輪になっている: 輪の中の物は自分の状態（と続きのリマインダー）だけで見る
        return own
    visiting.add(i)
    below = [_open(tasks, c, memo, visiting, rems) for c in t["children"] + t["follows"]]
    memo[i] = own or any(below)
    visiting.discard(i)
    return memo[i]


def held(view, t):
    """頼み t の納品の残った疑問の担当者に、閉じていないリマインダーが在るか（在れば、t は済んでいても開いている物と見る）。"""
    return any(not view["reminders"][r]["closed"] for r in t["reminders"])


def forwarded_open(view, i):
    """回した先（forwarded の線）だけをたどって、i から続く頼みのうち、自分がまだ終わっていない物の受付の並び（i 自身が終わって
    いなければ [i]）。足し（--note）を、回して閉じた頼みから今動いている先へ回すのに使う。"""
    tasks = view["tasks"]
    if i not in tasks:
        return []
    out, stack, seen = [], [i], set()
    while stack:
        j = stack.pop()
        if j in seen:
            continue
        seen.add(j)
        t = tasks[j]
        if t["state"] not in FINAL + ("failed",):
            out.append(j)
            continue
        stack += [c for c in reversed(t["children"]) if tasks[c]["parent_by"] == "forwarded"]
    return out


def awaited(view, i):
    """i の答えがまだ出ていないか。i から、回した先（forwarded の線）と、納品の残った疑問の担当者の頼み（続き）だけを先へたどり、
    自分がまだ終わっていない頼みと、担当者に書かれた閉じていないリマインダーの受付の並びを返す（無ければ空。i を知らなければ空）。子の頼み（cause）はたどらない。受けた部署が
    頼みの途中で出した別の仕事で、i の答えを待つ物ではない（開いているか〔open〕は子もたどるので、持ち主への中継のように頼みを受けたまま
    別の頼みを出し続ける部署の先では、いつまでも閉じない。2026-10-19 の my_notes の受付 22e6bf）。"""
    tasks = view["tasks"]
    out, stack, seen = [], [i] if i in tasks else [], set()
    while stack:
        j = stack.pop()
        if j in seen:
            continue
        seen.add(j)
        t = tasks[j]
        if t["state"] not in FINAL + ("failed",):
            out.append(j)
            continue
        out += [r for r in t["reminders"] if not view["reminders"][r]["closed"] and r not in out]
        stack += [c for c in reversed(t["children"]) if tasks[c]["parent_by"] == "forwarded"] + list(reversed(t["follows"]))
    return out


def select(view, top=None, everything=False):
    """見せる頼みの木 [{"task", "kids", "follows", "reminders"}]。top を渡せばその頼みから下だけ。everything でなければ、開いているブランチと
    閉じていないリマインダーの続きだけ。reminders は続きのリマインダー（remind.project の物）の並び。"""
    tasks, rems = view["tasks"], view["reminders"]
    keep = (lambda i: True) if everything else (lambda i: tasks[i]["open"])
    def node(i, seen):
        seen = seen | {i}
        t = tasks[i]
        kids = [node(c, seen) for c in sorted(t["children"], key=lambda c: tasks[c]["created"] or 0) if keep(c) and c not in seen]
        follows = [f for f in t["follows"] if keep(f) and f not in seen]
        return {"task": t, "kids": kids, "follows": follows,
                "reminders": [rems[r] for r in t["reminders"] if everything or not rems[r]["closed"]]}
    if top is not None:
        return [node(top, set())] if top in tasks else []
    roots = [i for i in view["roots"] if keep(i)]
    return [node(i, set()) for i in sorted(roots, key=lambda i: tasks[i]["updated"] or 0, reverse=True)]


def state_of(word):
    """--state に渡した 1 語（STATES の名前か、画面の字）を状態の名前にする（知らなければ None）。"""
    if word in STATES:
        return word
    return next((k for k, v in STATES.items() if v[0] == word), None)


def scope(view, top=None, to=None):
    """数える頼みの受付の並び。top を渡せばその頼みと、子をたどった下の頼みだけ。to を渡せば宛先の部署の名前・会社の名前・
    「会社/名前」のどれかが to と同じ物だけ。"""
    tasks = view["tasks"]
    if top is None:
        ids = list(tasks)
    else:
        ids, stack = [], [top] if top in tasks else []
        while stack:
            i = stack.pop()
            if i not in ids:
                ids.append(i)
                stack += tasks[i]["children"]
    if to:
        def hit(t):
            d = t["to"] or {}
            return to in (d.get("name"), d.get("company"), f"{d.get('company')}/{d.get('name')}")
        ids = [i for i in ids if hit(tasks[i])]
    return ids


def flat(view, ids, states):
    """絞り込みの見せ方: ids のうち状態が states に入る頼みを、木にせず、更新の古い順（動きの無い間の長い順）に並べた forest。"""
    tasks = view["tasks"]
    keep = [i for i in ids if tasks[i]["state"] in states]
    return [{"task": tasks[i], "kids": [], "follows": [], "reminders": []} for i in sorted(keep, key=lambda i: tasks[i]["updated"] or 0)]


def tally(view, ids, now):
    """ids の頼みの数え: 状態ごとの件数・済の割合（済 ÷ 届かずを除いた全件。分母が 0 なら None）・開いている頼み（自分が順番待ち・
    動いている・答え待ち）のうち更新のいちばん古い物と、その更新から now までの秒。"""
    tasks = view["tasks"]
    counts = {k: 0 for k in STATES}
    for i in ids:
        counts[tasks[i]["state"]] += 1
    base = len(ids) - counts["failed"]
    # 時刻の無い頼み（台帳の行に at が無い）は古さを決められないので選ばない
    live = [i for i in ids if tasks[i]["state"] not in FINAL + ("failed",) and tasks[i]["updated"]]
    old = min(live, key=lambda i: tasks[i]["updated"]) if live else None
    return {"counts": counts, "total": len(ids), "done_ratio": round(counts["done"] / base, 3) if base else None,
            "oldest_open": None if old is None else {"id": old, "updated": tasks[old]["updated"],
                                                     "age": max(0, now - tasks[old]["updated"])}}


def age(sec):
    """経った秒を「N 日」「N 時間」「N 分」の字に。"""
    sec = max(0, int(sec or 0))
    return f"{sec // 86400} 日" if sec >= 86400 else f"{sec // 3600} 時間" if sec >= 3600 else f"{sec // 60} 分"


def tally_line(t):
    """数えの 1 行（--todo の頭と、--html のページの頭）。"""
    parts = "・".join(f"{STATES[k][0]} {n}" for k, n in t["counts"].items())
    ratio = "-" if t["done_ratio"] is None else f"{round(t['done_ratio'] * 100)}%"
    old = t["oldest_open"]
    tail = f"。開いている頼みでいちばん動きの無い物: {old['id']}（{age(old['age'])}前に更新）" if old else ""
    return f"件数: {parts}（全 {t['total']} 件、済の割合 {ratio}）{tail}"


def lines(forest, when=None, now=None):
    """人の読む形（字下げの木）。when(時刻) は日時の字を返す（省けば出さない）。now を渡せば、宛先と、更新から now までの古さも添える
    （絞り込みの見せ方）。"""
    out = []
    def walk(n, depth):
        t = n["task"]
        stamp = f"  {when(t['updated'])}" if when else ""
        if now is not None:
            d = t["to"] or {}
            stamp += f"  宛先 {d.get('company') or '-'}/{d.get('name') or '-'}  " + (f"{age(now - t['updated'])}前" if t["updated"] else "更新の時刻なし")
        out.append(f"{'  ' * depth}- [{t['label']}] {t['title'] or '（題なし）'}  {t['id']}{stamp}")
        if t["state"] == "waiting" and t.get("why"):
            out.append(f"{'  ' * (depth + 1)}答え待ちの訳: {t['why']}")
        for f in n["follows"]:
            out.append(f"{'  ' * (depth + 1)}→ 続き: {f}")
        for r in n["reminders"]:
            out.append(f"{'  ' * (depth + 1)}→ 続き（リマインダー{'、閉じた' if r['closed'] else ''}）: {r['id']}  {r['text'][:60]}")
        for k in n["kids"]:
            walk(k, depth + 1)
    for n in forest:
        walk(n, 0)
    return out


# 1 枚の HTML のページ（--todo --html）。読む側は VS Code の Remote-SSH の HTML の表示で、ページの遷移と外のファイルのスクリプトが効かない
# ので、CSS とスクリプトをページの中に書き、畳みは details にする
MARKS = {"queued": "◌", "working": "○", "waiting": "?", "done": "✓", "dropped": "✕", "failed": "!"}
PAGE = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><title>やること</title>
<style>
body{font:14px/1.6 -apple-system,"Hiragino Sans",sans-serif;margin:1.5em;color:#222;background:#fff}
h1{font-size:1.2em;margin:0 0 .3em}
.bar{color:#666;margin-bottom:1em}
ul{list-style:none;margin:0;padding-left:1.4em}
body>ul{padding-left:0}
li{margin:.15em 0}
summary{cursor:pointer}
.mark{display:inline-block;width:1.3em;text-align:center;color:#888}
.s-working .mark,.s-waiting .mark{color:#0a6}
.s-queued .mark{color:#c80}
.s-failed .mark{color:#c33}
.closed>.row .title,.closed>details>summary .title{color:#999;text-decoration:line-through}
.meta{color:#999;font-size:.85em;margin-left:.6em}
.why,.follow{color:#666;font-size:.9em;margin-left:1.3em}
.follow a{color:#36c}
body.hide .closed{display:none}
:target>.row,:target>details>summary{background:#ffd}
</style></head>
<body class="%(hide)s">
<h1>やること</h1>
<div class="bar">開いている %(open)d 件 ・ 全部 %(all)d 件 ・ %(when)s に台帳から作った
<label><input type="checkbox" id="all"%(checked)s> 済んだ物も出す</label></div>
%(tally)s<ul>
%(body)s
</ul>
<script>
document.getElementById("all").addEventListener("change", function (e) {
  document.body.classList.toggle("hide", !e.target.checked);
});
function reveal() {
  var t = location.hash && document.getElementById(location.hash.slice(1));
  if (!t) return;
  if (t.classList.contains("closed")) { document.body.classList.remove("hide"); document.getElementById("all").checked = true; }
  for (var p = t.parentElement; p; p = p.parentElement) if (p.tagName === "DETAILS") p.open = true;
}
window.addEventListener("hashchange", reveal);
reveal();
</script>
</body></html>
"""


def page(forest, view, made, when=None, everything=False, counted=None, flat=False):
    """頼みの木の 1 枚の HTML。forest は select(view, everything=True) の物を渡し、済んだブランチは class closed で畳む（everything でなければ
    始めは隠す）。made は作った時刻の字。when(時刻) は日時の字を返す。counted は tally の物で、渡せばページの頭に数えの 1 行を出す。
    flat は絞り込みの見せ方（flat の forest）で、済の印を下の頼みでなく自分の状態で付け、数えの行が絞る前の範囲の物と添える。"""
    tasks = view["tasks"]
    def title(t):
        return html.escape(t["title"] or "（題なし）")
    def row(t):
        stamp = f"{when(t['updated'])} ・ " if when else ""
        return (f'<span class="mark" title="{html.escape(t["label"])}">{MARKS[t["state"]]}</span>'
                f'<span class="title">{title(t)}</span><span class="meta">{t["label"]} ・ {stamp}{t["id"][-6:]}</span>')
    def item(n):
        t = n["task"]
        extra = ""
        if t["state"] == "waiting" and t.get("why"):
            extra += f'<div class="why">答え待ちの訳: {html.escape(t["why"])}</div>'
        for f in n["follows"]:
            extra += f'<div class="follow">→ 続き: <a href="#t-{f}">{title(tasks[f])}</a></div>'
        for r in n["reminders"]:
            extra += (f'<div class="follow">→ 続き（リマインダー{"、閉じた" if r["closed"] else ""}）: {html.escape(r["text"][:60])}'
                      f' ・ {r["id"][-6:]}</div>')
        live = t["state"] not in FINAL + ("failed",) if flat else t["open"]
        cls = f'task s-{t["state"]} {"open" if live else "closed"}'
        if n["kids"]:
            kids = "\n".join(item(k) for k in n["kids"])
            return (f'<li class="{cls}" id="t-{t["id"]}"><details{" open" if t["open"] else ""}><summary>{row(t)}</summary>'
                    f'{extra}<ul>\n{kids}\n</ul></details></li>')
        return f'<li class="{cls}" id="t-{t["id"]}"><div class="row">{row(t)}</div>{extra}</li>'
    shown = []
    def walk(n):
        shown.append(n["task"])
        for k in n["kids"]:
            walk(k)
    for n in forest:
        walk(n)
    return PAGE % {"hide": "" if everything else "hide", "checked": " checked" if everything else "",
                   "open": sum(1 for t in shown if t["state"] not in FINAL + ("failed",) or held(view, t)), "all": len(shown),
                   "when": html.escape(made),
                   "tally": f'<div class="bar">{"絞り込む前の範囲の" if flat else ""}{html.escape(tally_line(counted))}</div>\n' if counted else "", "body": "\n".join(item(n) for n in forest)}
