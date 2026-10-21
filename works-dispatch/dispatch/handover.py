#!/usr/bin/env python3
"""引き継ぎの流れ（入口の dispatch.py --handover <前の名前>）。同じ会社の部署か窓口（前の部署）の受け持ちを、今いる部署（後継）へ移す。

後継の場所の会話が、そのターンの中で打つ（後継の待ち受けが動いていない間に、読んだ所を決める）。前の部署は待ち受けを止めておく
（会話を止めるか、ターンの途中にする）。--dry-run は何も書かずに、移す物と止める訳を出す。

移す物と、移さずに残す物:
- 宛先: 前の名前（と前の部署の former-names）を後継の company.former-names に足す。会社の名前だけの宛先と会社の形の desk も、
  後継の company.inherited の desk（本社の窓口を継いだ）か前の名前で後継へ届く（deliver.find_target）。前の場所の company.* は全部消す。
- 未読の知らせ: 前の部署の待ち受けが読んだ所から台帳の終わりまでの、前の宛先宛ての知らせを、後継の宛先宛てに写し直す。後継の待ち受けは、
  前の宛先宛ての知らせを、移した時の台帳の終わり（since）より後の物だけ拾う（wake.watch の since）。重ねず、取りこぼさない。
- 順番待ち: 前の部署の順番待ちの件を、後継の役の ask_check を通してから後継の順番待ちへ移す（通らない件が 1 つでも在れば移さずに止める）。
- 保留にした頼み（--wait --park）: 後継の company.parked へ移す。答えは後継が --deliver --for <受付> で返す。
- 受付番号・頼みの親子（cause・forwarded の行）・頼み元の属性: 替えない。納品の返し先は、頼み元が前の部署で、移すより前に頼んだ物なら、
  頼み元の受付箱の台帳の handover の行で後継へ読み替える（orders.deliver_summary）。読み替えた先がこの部署自身なら送らずに閉じる（status self）。
- 前の部署が納品していない頼みを持つ間は止める（その頼みは前の部署の会話が納品で閉じる。打ち直しの続きでも、前の場所の属性が残っていれば見る）。
- 移す物（読んだ所と順番待ち）は錠を取る前に読み、錠の中で読み直して替わっていれば止める。続きで、始めた後に積まれた順番待ちの件も
  後継の役の ask_check を通す。後継に読んだ所が無ければ、移した時の台帳の終わりを書く（写した行を取りこぼさない）。

途中で落ちたら、同じコマンドを打ち直すと、台帳の started で done の無い handover の行から、残りの手順を続ける（どの手順も 2 度打って同じ）。
"""

import contextlib
import json
import os

import config
import filex
import gitx
from ports import term
import orders
import reorg
import windows
from nodes import deliver, handover as ho, provision, tree, wake


def _plan_lines(old, prev, attrs, names, queue, copies, parked, children, owed, mine, since):
    out = [f"- 移す宛先: {'、'.join(names)} → {attrs.get('name')}（後継の company.former-names に足す）",
           f"- 前の場所 {prev['path']} の company.* を全部消す" + ("（本社の窓口を解く）" if prev["head"] else ""),
           f"- 写し直す未読の知らせ: {len(copies)} 件（後継は台帳の {since} バイトより後の、前の宛先宛ての知らせを拾う）",
           f"- 移す順番待ち: {'、'.join(q['id'] for q in queue) or 'なし'}",
           f"- 移す保留の頼み: {'、'.join(p['id'] for p in parked) or 'なし'}"]
    if children:
        out.append(f"- 頼み元が {old} の部署（納品の返し先を後継に読み替える）: " + "、".join(children))
    if owed:
        out.append(f"- {old} が回して、まだ --for で返していない頼み（後継が --deliver --for <受付> で返す）: " + "、".join(owed))
    if mine:
        out.append(f"- この部署が持つ頼みのうち頼み元が {old} の物（納品すると頼み元が自分になり、送らずに閉じる）: " + "、".join(mine))
    return out


def _owed(records, old, prev_path):
    """前の部署が --forward で回し、まだ --for で返していない頼み（回した元の受付）の並び。"""
    back = {r.get("for") for r in records if r.get("kind") == "deliver" and r.get("for") and r.get("status") != "failed"}
    out = []
    for r in records:
        sender = r.get("from") or {}
        if r.get("kind") == "forwarded" and (sender.get("name") == old or os.path.realpath(sender.get("place") or "-")
                                             == os.path.realpath(prev_path)) and not {r.get("id"), r.get("child")} & back:
            out.append(r["id"])
    return list(dict.fromkeys(out))


def _children(companies, old, inbox):
    """頼み元が前の部署で、まだ納品していない部署（どの会社でも）の「会社/名前（受付）」の並び。"""
    return [f"{c['name']}/{d['attrs'].get('name') or d['branch']}（{d['attrs'].get('ask')}）" for c in companies for d in c["departments"]
            if wake.pending(d["attrs"]) and d["attrs"].get("boss") == old
            and os.path.realpath(d["attrs"].get("boss-inbox") or "-") == os.path.realpath(inbox)]


def _find_prev(ports, source, old, here):
    """同じ会社の場所のうち、今の名前が old の物の並び（[{path, attrs, place, head}]）と、old を前の名前に持つほかの場所の並び。"""
    hits, former = [], []
    for w in ports.git.listed_worktrees(source):
        if os.path.realpath(w["path"]) == os.path.realpath(here):
            continue
        got = ports.attrs(w["path"])
        if not got.get("role"):
            continue
        one = {"path": w["path"], "attrs": got, "place": ports.git.git_dir(w["path"]),
               "head": ports.git.is_main_worktree(w["path"]) is True}
        if got.get("name") == old:
            hits.append(one)
        elif old in gitx.former_names(got) or old in gitx.inherited_names(got):
            former.append(one)
    return hits, former


def _unread(path, start, end, names):
    """台帳の start〜end バイトの、names（宛先の並び）宛ての知らせの行の並び（待ち受けと同じ見分け。wake.mine）。"""
    if start is None or end is None or start >= end:
        return []
    return [r for r in filex.read_jsonl(path, start, end).rows if wake.mine(r, names)]


def _line_end(log, pos):
    """台帳の、書き終わった最後の行の終わり（バイト）。待ち受けが読む切れ目に使うので、書きかけの行の途中を指さない。"""
    if not os.path.isfile(log):
        return 0
    start = pos if pos is not None and pos <= os.path.getsize(log) else 0
    return filex.read_jsonl(log, start).pos


def _own_pane(ports, here, sid):
    try:
        listed = ports.term.panes()
    except term.Error:
        return None
    return windows.own_pane(here, sid, listed) if sid else None


def handover(a, ports, cwd):
    """--handover <前の名前>。終了の値（2 は使い方の誤りか、移せない訳がある）。"""
    old = (a.handover or "").strip()
    attrs = ports.attrs(cwd)
    common = ports.git.common_dir(cwd)
    if not old:
        print("止めた: --handover に前の部署か窓口の名前を渡す")
        return 2
    if not attrs.get("role") or not attrs.get("name") or not common:
        print(f"止めた: {cwd} は部署でない（git の設定 company.role と company.name が無い）。引き継ぎは後継の部署の場所から打つ")
        return 2
    if old == attrs["name"]:
        print(f"止めた: {old} はこの部署の今の名前。--handover には移す元（前の部署か窓口）の名前を渡す")
        return 2
    source = gitx.root_of(common)
    here = ports.git.toplevel(cwd) or cwd
    place = ports.git.git_dir(here)
    inbox = deliver.inbox_of(common)
    log = os.path.join(inbox, deliver.LOG)
    settings = os.path.dirname(config.path_of(a.config, os.environ))
    company = tree.company_name(source, tree.read_info(source, settings, ports.git))
    records = deliver.records(inbox) if os.path.isdir(inbox) else []
    row = ho.unfinished(records, old, place)
    if row:
        prev = {k: row["from"].get(k) for k in ("path", "place", "head")}
        prev["attrs"] = row["from"].get("attrs") or {}
        hid = row["id"]
    else:
        hits, former = _find_prev(ports, source, old, here)
        if not hits:
            done = [r for r in ho.rows_of(records) if r.get("status") == ho.DONE and (r.get("from") or {}).get("name") == old
                    and os.path.realpath((r.get("to") or {}).get("place") or "-") == os.path.realpath(place)]
            if done:
                print(f"{old} はもうこの部署へ移してある（引き継ぎ {done[-1]['id']}）。移す物は無い")
                return 0
            print(f"止めた: 会社 {company} に今の名前が {old} の部署も窓口も無い（--tree で名前を見る）")
            return 2
        if len(hits) > 1:
            print(f"止めた: 会社 {company} に名前 {old} の場所が 2 つ以上ある（{'、'.join(h['path'] for h in hits)}）。"
                  "片方の名前を --reorg で替えてから打つ")
            return 2
        if former:
            print(f"止めた: {old} を前の名前に持つほかの場所が在る（{'、'.join(f['path'] for f in former)}）。移すと、{old} 宛ての"
                  "頼みが 1 つに決まらない")
            return 2
        prev, hid = hits[0], None
    prev_attrs = prev["attrs"]
    names = wake.addresses(company, prev_attrs, gitx.former_names(prev_attrs)) if not row else row["from"].get("names") or []
    me = wake.address(company, attrs["name"])
    try:
        parked_prev = deliver.parked_of(prev_attrs, strict=True)
        deliver.parked_of(attrs, strict=True)
        gitx.former_names(attrs, strict=True)
    except gitx.AttrError as e:
        print(f"止めた: {e}")
        return 2
    why = _blockers(inbox, prev, place, ports.attrs(prev["path"]) if row and prev.get("path") else prev_attrs)
    if why:
        print("\n".join(why))
        return 2
    the_role, notes = orders.shape_role(source, settings, attrs["role"], ports.git)
    queue = wake.queued(inbox, prev["place"]) if prev.get("place") else []
    bad = orders.gate_queued(queue, the_role, company, source, attrs["name"], ports)
    if bad:
        print("\n".join(notes + ["止めた: 前の部署の順番待ちに、後継の役が受けない頼みが在る（移さない）"] + [f"  {x}" for x in bad]
                        + ["- その件を前の部署か頼み元が取り下げるか、後継の役の ask_check が受ける形にしてから打ち直す"]))
        return 2
    pos = wake.read_pos(inbox, prev["place"]) if prev.get("place") else None
    end = _line_end(log, pos)
    copies = _unread(log, end if pos is None else pos, end, names)
    try:
        _, _, _, _, companies, _, more = orders.survey(a.config, ports)
        notes += more
    except term.Error as e:
        companies = []
        notes.append(f"{term.NAME} を読めないので、頼み元が {old} の部署の一覧は出さない（{e}）")
    plan = _plan_lines(old, prev, attrs, names, queue, copies, parked_prev, _children(companies, old, inbox),
                       _owed(records, old, prev["path"]),
                       [attrs["ask"]] if wake.pending(attrs) and attrs.get("boss") == old else [], end)
    if a.dry_run:
        print("\n".join(notes + [f"{old} を {attrs['name']} へ移す（空打ち。何も書かない）:"] + plan
                        + ([f"- 続き: 引き継ぎ {hid} の残りの手順を続ける"] if hid else [])))
        return 0
    with contextlib.ExitStack() as stack:
        for p in sorted({place, prev["place"]} - {None}, key=wake.key):
            stack.enter_context(wake.ask_lock(inbox, p))
        live = ports.attrs(prev["path"]) if prev.get("path") else {}
        why = _blockers(inbox, prev, place, live)
        if live and live.get("name") != old:
            why.append(f"止めた: 前の場所 {prev['path']} に、今は別の名前 {live.get('name') or '-'} が付いている（引き継ぎを始めた後に --desk か"
                       " --reorg で名付けた）。その名前の部署か窓口を畳まずに残すなら、その場所の属性を --reorg で戻してから打ち直す")
        if live:
            try:
                parked_prev = deliver.parked_of(live, strict=True)   # 錠の中の今の保留（読んでから足した物も移す）
            except gitx.AttrError as e:
                why.append(f"止めた: {e}")
        if not row and not why:
            # 錠を取る前に読んだ読んだ所と順番待ちが、錠の中でも同じか（その間に前の待ち受けが読み進めるか、頼みが積まれたら、
            # 写す知らせと ask_check を通した順番待ちが替わる）
            if (wake.read_pos(inbox, prev["place"]) if prev.get("place") else None) != pos \
                    or [q["id"] for q in wake.queued(inbox, prev["place"]) if prev.get("place")] != [q["id"] for q in queue]:
                why = ["止めた: 移す物を読んだ後に、前の部署の待ち受けが台帳を読み進めたか、順番待ちに頼みが積まれた。前の待ち受けを止めて"
                       "から打ち直す（--dry-run で移す物を読み直す）"]
        if why:
            print("\n".join(why))
            return 2
        if not row:
            hid = deliver.new_id(ports.now())
            sid = attrs.get("session")
            deliver.log(inbox, {"id": hid, "kind": ho.KIND, "at": ports.now(), "status": ho.STARTED,
                                "from": {"name": old, "former": gitx.former_names(prev_attrs), "names": names,
                                         "role": prev_attrs.get("role"), "session": prev_attrs.get("session"),
                                         "account": prev_attrs.get("account"), "path": prev["path"], "place": prev["place"],
                                         "head": prev["head"], "attrs": prev_attrs, "pos": pos, "end": end},
                                "to": {"name": attrs["name"], "role": attrs.get("role"), "session": sid,
                                       "account": attrs.get("account"), "pane": _own_pane(ports, here, sid),
                                       "path": here, "place": place},
                                "queue": [q["id"] for q in queue], "parked": [p["id"] for p in parked_prev]})
            row = {"id": hid, "from": {"pos": pos, "end": end, "names": names}, "queue": [q["id"] for q in queue]}
        try:
            out, ok = _apply(ports, source, inbox, log, hid, row, old, prev, attrs, here, place, me, company, the_role, parked_prev)
        except (gitx.GitError, OSError) as e:
            print("\n".join(notes + [f"止めた: 引き継ぎ {hid} の途中で書けなかった（{e}）。訳を直して同じコマンドを打ち直すと、残りの手順を"
                                     "続ける（済んだ手順は 2 度しない）"]))
            return 1
        if not ok:
            print("\n".join(notes + out))
            return 2
        deliver.log(inbox, {"id": hid, "kind": ho.KIND, "at": ports.now(), "status": ho.DONE, "from": {"name": old},
                            "to": {"name": attrs["name"], "place": place}})
    out += reorg._resync(a, ports, here, notes) + (reorg._resync(a, ports, prev["path"], notes) if prev.get("path") else [])
    print("\n".join(notes + [f"{old} を {attrs['name']} へ移した（引き継ぎ {hid}）:"] + plan + out))
    return 0


def _blockers(inbox, prev, place, prev_attrs):
    """移せない訳の並び（空なら移せる）。prev_attrs は前の場所の今の属性（続きで、もう消してあれば空）。"""
    out = []
    if prev.get("place") and wake.watching(inbox, prev["place"]):
        out.append(f"止めた: 前の部署（{prev['path']}）の待ち受けが動いている。前の会話を止める（/exit）か、その会話のターンの途中にしてから打つ"
                   "（待ち受けが知らせを読み進めると、移す未読の知らせが決まらない）")
    if place and wake.watching(inbox, place):
        out.append("止めた: この部署の待ち受けが動いている。この部署の会話のターンの中で打つ（ターンの外の別の処理から打つと、待ち受けが"
                   "読み進めて、前の宛先宛ての知らせを取りこぼす）")
    held = wake.pending(prev_attrs)
    if held:
        out.append(f"止めた: 前の部署が受けた頼み（受付 {held}）をまだ納品していない。前の部署の会話が納品で閉じるか、--wait <訳> --park で"
                   "保留にしてから打つ")
    return out


def _apply(ports, source, inbox, log, hid, row, old, prev, attrs, here, place, me, company, the_role, parked_prev):
    """引き継ぎの手順（どれも 2 度打って同じ）。(出す行の並び, 済ませたか)。止める訳は、前の場所の属性を消す前に全部見る。"""
    out = []
    now = ports.now
    names = row["from"].get("names") or []
    # 0. 引き継ぎを始めた後に前の部署の順番待ちに積まれた件は、ここで後継の役の ask_check を通す（通らなければ何も替えずに止める）
    left_queue = wake.queued(inbox, prev["place"]) if prev.get("place") else []
    bad = orders.gate_queued([q for q in left_queue if q["id"] not in set(row.get("queue") or [])], the_role, company, source,
                             attrs["name"], ports)
    if bad:
        return [f"止めた: 引き継ぎ {hid} を始めた後に前の部署の順番待ちに積まれた頼みを、後継の役が受けない（移さない）"] \
            + [f"  {x}" for x in bad] + ["- その件を頼み元が取り下げるか、後継の役の ask_check が受ける形にしてから打ち直す（残りの手順を続ける）"], False
    # 1. 後継の属性: 前の名前と継いだ物。保留の頼みは、まだ継いでいない（この引き継ぎの印が無い）ときだけ移す（打ち直しで、後継が
    #    もう --for で返して外した物を戻さない）
    succ = ports.attrs(here)
    entries = gitx.inherited(succ)
    first = not any(x.get("id") == hid for x in entries)
    if first:
        end = row["from"].get("end") or 0
        entries.append({"id": hid, "from": old, "names": names, "place": prev["path"], "session": prev["attrs"].get("session"),
                        "since": end, "desk": bool(prev.get("head"))})
    former = [n for n in gitx.former_names(succ) + [old] + list(gitx.former_names(prev["attrs"])) if n != succ.get("name")]
    parked = deliver.parked_of(succ)
    moved = [p for p in parked_prev if p["id"] not in {x["id"] for x in parked}] if first else []
    provision.mark(here, source, {"former-names": json.dumps(list(dict.fromkeys(former)), ensure_ascii=False),
                                  gitx.INHERITED: json.dumps(entries, ensure_ascii=False),
                                  deliver.PARKED: json.dumps(parked + moved, ensure_ascii=False) if parked or moved else None},
                   ports.git)
    out.append(f"- company.former-names に {old} を足し、company.{gitx.INHERITED} に引き継ぎ {hid} を書いた")
    if moved:
        out.append(f"- 保留の頼み {'、'.join(p['id'] for p in moved)} を移した（答えは --deliver --for <受付> で返す）")
    # 2. 未読の知らせを写し直す（後継の待ち受けは動いていないので、写した行は後継が次に読む）
    pos, end = row["from"].get("pos"), row["from"].get("end") or 0
    records = deliver.records(inbox)
    done = ho.copies(records, hid)
    copies = [r for r in _unread(log, end if pos is None else pos, end, names) if tuple(ho.copy_key(r)) not in done]
    for r in copies:
        deliver.log(inbox, ho.copied(r, me, hid))
    out.append(f"- 未読の知らせ {len(copies)} 件を {me} 宛てに写し直した")
    # 3. 後継に読んだ所が無ければ、移した時の台帳の終わりを書く（初めての待ち受けが台帳の終わりから読み始めて、写した行を取りこぼさない）
    wake.start_pos(inbox, place, end)
    # 4. 前の場所の属性を全部消す（本社なら窓口を解く）。この後は、前の場所を宛てた --ask が錠の中で読み直して止まる（orders.moved_away）
    left = ports.attrs(prev["path"]) if prev.get("path") else {}
    if left:
        provision.mark(prev["path"], source, {**{k: None for k in left}, gitx.OWN_ID: None}, ports.git)
        out.append(f"- {prev['path']} の company.* を消した")
    # 5. 順番待ちを移す。1 件ずつ、宛先を書き直してから rename で後継の順番待ちへ移す（件はいつもどちらか 1 か所にだけ在るので、
    #    途中で落ちても 2 度渡らず、取り下げなどが片方にだけ効くこともない）。台帳の知らせの行は移す前に書き、引き継ぎの id で 2 度書かない
    fresh = orders.FRESH if (the_role or {}).get("fresh") else None
    logged = {r.get("id") for r in records if r.get("kind") == wake.QUEUED and r.get(ho.KIND) == hid}
    for q in wake.queued(inbox, prev["place"]) if prev.get("place") else []:
        item = {k: v for k, v in q.items() if k != "path"}
        if item["id"] not in logged:
            deliver.log(inbox, {**wake.notice(me, item["id"], wake.QUEUED, item.get("file"), None, now()), ho.KIND: hid})
        wake.move(q, inbox, place, {**item, "to": me, "marks": {**(item.get("marks") or {}), "fresh": fresh}})
        out.append(f"- 順番待ちの {item['id']} を移した")
    return out, True
