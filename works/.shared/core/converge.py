"""事前審査の壁打ち（依頼 231）の決まりと往復の控え。

事前審査（p2.plan_review）が修正案に block（直しへ進めない穴）を挙げたら、同じ会話の修正案の役に返して案を直させ、
直した案を新しい会話の事前審査に掛け直す。block の無い案だけが直しへ進む。同じ block が残れば（前のどの往復かの block と
重なれば）直しへ進まずに人の関所で止まる。往復の数を数える定数は持たない（柵は呼び手が rolekit.GIVE_UP_AFTER を渡す）。

控えは盤面の今の周の作業ファイル plan-converge.json（読み書きはこの口だけ）:
{"round": n, "passes": [往復の行], "outcome": 語 | None, "open": {"answers": [...]}}
往復の行: {"pass": k, "blocks": [key], "faces": [{key, kind, where, why}], "suggests": [key],
          "answers": [{key, handled, how}], "resolved": [key], "persists": [key], "outcome": 語,
          "files": {名: 写した先}, "rejects": [行]}
k 往復目の行の answers と resolved は、k-1 往復目の block への修正案の役の答えと、直した案を読んだ審査の言い分。

項目ごとの壁打ち（線の木の段 1。設計 docs/plans/2026-10-06-tree-line.md の 2.3 の 5）: 受けた案の項目を note_plan が控えの
"plan"（[{id, unit_keys, hash}]。id は unit_keys の組・hash は名前に戻した項目の行の sha256）に置くと、往復の行に
"items"（[{n, id, unit_keys, hash, state, blocks, reopened}]）・"synergy"（相乗りの審査が挙げた key）・"face_units"
（{key: unit_keys}）が付く。face は unit_keys が重なる項目の物（どの項目とも重ならない face は審査した全部の項目の物）。
項目の state: block の無い項目は CLOSED（次の往復で審査も直しもしない）・block が前のどれかの往復の block と重なれば HELD
（保留。後の往復でも保留）・ほかは OPEN。閉じた項目は block に名指されれば開き直す（相乗りの審査の道）。抜け方は全部の項目が
閉じれば CLEAN、開いた項目が無く保留が在れば PERSISTED、柵の往復で保留が在れば PERSISTED・無ければ UNSETTLED、ほかは AGAIN。
note_plan の無い控え（行に items が無い）は今までどおり全体で 1 つ。

- block_faces(review)・decide(passes, fence=): block の face と、続けるか止めるかの語（CLEAN・AGAIN・PERSISTED・UNSETTLED）
- read(b)・pass_no(b)・note_answers(b, answers)・record_pass(b, review, ...)・stash_rejects(b, rows)・held(b):
  控えの読み書き
- note_plan(b, rows)・open_items(b)・filled_units(b)・splice(b, rows)・item_id・item_hash: 項目の控え・次に審査する項目の番号・
  機械が差し込む（閉じた・保留の）項目の単位・直しの役が返した開いた項目の行に前の往復の行を差し込んで案の全体を組む口
  （閉じた項目を変えた行は拒み、前と同じ行は捨てる）
- answer_gaps(b, answers)・resolved_gaps(b, faces, resolved): 修正案の役と事前審査の役の返答の欄の欠けと誤りの行（項目の在る
  控えでは、今の往復で開いている項目の分だけ）
- with_fields(role, schema)・split(role, reply): 役の型に欄を足す・返答から欄を外す（事前審査の型には項目ごとの審査の欄
  ITEMS（項目ごとの判定の要約）も任意で足す。tree_split が外す・drop_fields が壁打ちの欄を全部外す。下請けの答えのファイルの
  当たりの答えの型は HITS_SCHEMA）
- item_blocks(b, n): 項目 n が答える前の往復の block の key（受け付けが下請けの答えの resolved を確かめる）
- prev_row(b, n)・answered_hits(b, n)・carried_notes(b): 前の往復のその項目の案の行・当たりの答えと、suggest の穴（往復の行の
  notes。項目を開き直さず、直しの役に参考として渡り、受け付けが後の往復の返答に引き継ぐ）
- revise_section(b)・review_section(b)・stuck_reason(b)・lines(b): 指示書に足す文・関所の理由・報告の行（往復ごとの行は
  前の往復の block を審査が suggest に下げた key も名指す）

役の型に欄を足す・返答から外す手順は住処 marks（種 converge）に任せる。外した欄は足し欄の控えでなく、この往復の控えに置く。
盤面の b のうち round・dir・work・trace だけを使い、標準ライブラリと住処 marks（L1）だけを import する（gatemarks がこのモジュールを
読み、entry が gatemarks を読むので、entry・rolekit・gatemarks を import すると輪になる）。
"""
from __future__ import annotations

import copy
import hashlib
import json
import os
import shutil

import marks
import promptsection

RECORD = "plan-converge.json"
PASS_DIR = "plan-converge"
OP = "plan_converge"
DROPPED_OP = "plan_converge_dropped"
CLEAN = "clean"   # 抜け方の語（控えの outcome）
AGAIN = "again"
PERSISTED = "persisted"
UNSETTLED = "unsettled"
STUCK = (PERSISTED, UNSETTLED)
OPEN = "open"   # 項目の state（往復の行の items[].state）
CLOSED = "closed"
HELD = "held"
ANSWERS = "block_answers"
RESOLVED = "resolved"
HANDLED = ("fixed", "disputed")
FACE_KEYS = ("key", "kind", "where", "why")

REVISE_ASK = ("事前審査（別の目）が、お前の修正案に下の block（直しへ進めない穴）を挙げた。block ごとに、案を直したなら handled に fixed、"
              "how に直した所を、直さずに異を唱えるなら handled に disputed、how に根拠を、block_answers に 1 行ずつ書け（key は下の key を"
              "一字も変えずに写す）。そのうえで開いた項目の行を plan に返せ（前の案と同じ型の行。閉じた項目は書くな。機械が前の往復の行を"
              "差し込む。保留の項目は直す時だけ書け）。suggest の穴は採っても採らなくてもよい。直した案は新しい会話の事前審査に掛かり、"
              "同じ block が残れば直しへ進まずに人の関所で止まる。")
REREVIEW_ASK = ("下は前の往復で挙がった block と、修正案の役の答え（fixed＝直した・disputed＝異を唱えた）。今の案を読み、前の block の key "
                "ごとに、穴が消えたなら resolved にその key を入れ、残っていれば同じ key のまま faces に severity block で挙げ直せ（同じ穴に"
                "別の key を付けない。key は一字も変えずに写す）。新しい穴は新しい key で挙げよ。前の block が 1 つでも block のまま残ると、"
                "案は直しへ進まず人の関所で止まる。")
PERSISTED_WHY = ("事前審査（記録の名 p2.plan_review）の同じ block が、案を直した後も残った（{keys}。壁打ち {n} 往復。"
                 "往復ごとの案と審査: {path}）")
UNSETTLED_WHY = ("事前審査（記録の名 p2.plan_review）の block が、壁打ち {n} 往復でも消えない（往復ごとに別の穴が出た。"
                 "最後の block: {keys}。往復ごとの案と審査: {path}）")
LINE_HEAD = ("事前審査の壁打ち: {n} 往復・抜け方は{word}（記録の名 {outcome}）・続いた block: {persists}"
             "（往復ごとの案と審査: {path}）")
LINE_PASS = ("  - {k} 往復目: block {keys}・修正案の役の答え fixed {f} 件・disputed {d} 件・審査が消えたと言った key {resolved}"
             "・審査が suggest に下げた key {down}")
CLOSED_ASK = "下の項目は前の往復で事前審査が block を挙げずに閉じた。plan に書くな（機械が前の往復の行のまま差し込む）:"
NOTES_HEAD = ("参考: 事前審査が挙げた suggest の穴（block でない。答えなくてよく、採っても採らなくてもよい。項目を開き直さない。"
              "修正の段にも事前審査の返答として渡る）:")
HELD_NOTE = "下の項目は同じ block が続いたので保留にした（直さなくてよい。書かなければ機械が差し込む。人の関所が読む）:"
ITEMS_WHY = "固まった項目: {closed}。保留の項目: {held}。開いたままの項目: {open}"
LINE_ITEMS = "    項目: 閉じた {closed}・開いた {open}・保留 {held}・相乗りの審査の block {synergy}"
WORDS = {CLEAN: "block が消えた", PERSISTED: "同じ block が続いた", UNSETTLED: "柵の往復でも block が消えない", AGAIN: "途中"}
NONE = "無い"

ANSWER_SCHEMA = {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["key", "handled", "how"],
    "properties": {"key": {"type": "string", "minLength": 8}, "handled": {"type": "string", "enum": list(HANDLED)},
                   "how": {"type": "string", "minLength": 10}}}}
RESOLVED_SCHEMA = {"type": "array", "items": {"type": "string"}}
FIELDS = {"plan-revise": (ANSWERS, ANSWER_SCHEMA, True), "plan-review": (RESOLVED, RESOLVED_SCHEMA, False)}
# 事前審査の束ね役の欄（線の木の段 1。役の型にだけ在り、盤面へ渡す前に外す。写しの graph は変えない）。束ね役は項目ごとの判定の
# 要約（ITEMS）だけを返し、当たりの答え・faces・相乗りは下請けが答えのファイルに書いて受け付け（機械）がまとめる（run 68f35d6b:
# 束ね役が当たりの答え 141〜197 行を返答に写して 1 往復に 119〜194 秒を使い、短く写した理由で型に拒まれて書き直した）
ITEMS = "items"
SYNERGY = "synergy"
VERDICTS = ("clean", "block")
ITEMS_SCHEMA = {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["item", "verdict", "blocks"],
    "properties": {"item": {"type": "integer", "minimum": 1}, "verdict": {"type": "string", "enum": list(VERDICTS)},
                   "blocks": {"type": "array", "items": {
                       "type": "object", "additionalProperties": False, "required": ["key", "why"],
                       "properties": {"key": {"type": "string"}, "why": {"type": "string"}}}}}}}
# 下請けの答えのファイルの当たりの答えの欄（受け付けが項目ごとに確かめる。理由は 10 字以上）
HIT_ANSWERS = ("covered", "no_effect", "block")
HITS_SCHEMA = {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["id", "answer", "why"],
    "properties": {"id": {"type": "string", "minLength": 2}, "answer": {"type": "string", "enum": list(HIT_ANSWERS)},
                   "why": {"type": "string", "minLength": 10}}}}
TREE_FIELDS = {"plan-review": {ITEMS: ITEMS_SCHEMA}}


# ---------------------------------------------------------------- 決まり
def _faces(review) -> list[dict]:
    """審査の返答の face の行（返答が dict でない・faces が list でない・行が dict でない物は読まない）"""
    faces = review.get("faces") if isinstance(review, dict) else None
    return [f for f in faces if isinstance(f, dict)] if isinstance(faces, list) else []


def block_faces(review: dict) -> list[dict]:
    """審査の返答の severity が block の face（key で重複を除き、順を保つ）"""
    out = {}
    for f in _faces(review):
        if f.get("severity") == "block" and f.get("key") not in out:
            out[f.get("key")] = f
    return list(out.values())


def decide(passes: list[dict], *, fence: int) -> str:
    """最後の往復の block が無ければ CLEAN、前のどれかの往復の block と重なれば PERSISTED、柵の往復に着けば UNSETTLED、ほかは AGAIN。
    最後の行に items が在れば項目ごと（_decide_items）"""
    if passes[-1].get("items") is not None:
        return _decide_items(passes, fence=fence)
    last = set(passes[-1]["blocks"])
    if not last:
        return CLEAN
    if any(last & set(p["blocks"]) for p in passes[:-1]):
        return PERSISTED
    return UNSETTLED if len(passes) >= fence else AGAIN


def _decide_items(passes: list[dict], *, fence: int) -> str:
    states = [it.get("state") for it in passes[-1]["items"]]
    if OPEN not in states:
        return PERSISTED if HELD in states else CLEAN
    if len(passes) >= fence:
        return PERSISTED if HELD in states else UNSETTLED
    return AGAIN


def item_id(unit_keys) -> str:
    """項目の見分け（unit_keys の組。並びに依らない）"""
    return " | ".join(sorted(str(k) for k in unit_keys or []))


def item_hash(row: dict) -> str:
    """項目の行（名前に戻した物）の sha256"""
    return hashlib.sha256(json.dumps(row, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _label(it: dict) -> str:
    return f"項目 {it['n']}（{'、'.join(str(k) for k in it.get('unit_keys') or [])}）"


def _attributed(units: list, items: list) -> list[int]:
    """face の unit_keys が重なる項目の位置（どの項目とも重ならなければ全部）"""
    hit = [i for i, it in enumerate(items) if set(units) & set(it["unit_keys"])]
    return hit or list(range(len(items)))


def _item_states(plan: list, faces: list, face_units: dict, prev: list, earlier: set) -> list[dict]:
    before = {it["id"]: it for it in prev}
    rows = [{"n": n, "id": it["id"], "unit_keys": list(it["unit_keys"]), "hash": it["hash"], "state": OPEN, "blocks": [],
             "reopened": False, **({"row": copy.deepcopy(it["row"])} if "row" in it else {})} for n, it in enumerate(plan, 1)]
    for f in faces:
        for i in _attributed(face_units.get(f.get("key")) or [], rows):
            rows[i]["blocks"].append(f.get("key"))
    for r in rows:
        was = (before.get(r["id"]) or {}).get("state")
        if was == HELD:
            r["state"], r["blocks"] = HELD, (before[r["id"]].get("blocks") or [])
        elif not r["blocks"]:
            r["state"] = CLOSED
        elif set(r["blocks"]) & earlier:
            r["state"] = HELD
        r["reopened"] = was == CLOSED and r["state"] != CLOSED
    return rows


# ---------------------------------------------------------------- 控え
def _fresh(b) -> dict:
    return {"round": b.round, "passes": [], "outcome": None, "open": {}}


def read(b) -> dict:
    """今の周の控え。無い・読めない・形が違う・周が違うなら往復の無い控え"""
    try:
        doc = json.loads(b.work(RECORD).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return _fresh(b)
    if (not isinstance(doc, dict) or doc.get("round") != b.round or not isinstance(doc.get("passes"), list)
            or not all(isinstance(p, dict) for p in doc["passes"]) or not isinstance(doc.get("open", {}), dict)):
        return _fresh(b)
    out = {"round": b.round, "passes": doc["passes"], "outcome": doc.get("outcome"), "open": doc.get("open", {})}
    if isinstance(doc.get("plan"), list):
        out["plan"] = doc["plan"]
    return out


def _write(b, doc: dict) -> None:
    path = b.work(RECORD)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def pass_no(b) -> int:
    """次の事前審査の往復の番号"""
    return len(read(b)["passes"]) + 1


def note_answers(b, answers: list) -> None:
    """修正案の役の答えを open に置く（次の record_pass が往復の行へ移す）"""
    doc = read(b)
    doc["open"] = {"answers": copy.deepcopy(answers)}
    _write(b, doc)


def note_plan(b, rows: list) -> None:
    """受けた案の項目（名前に戻した行の並び）を控えの plan に置く（次の record_pass が項目ごとに読む。行そのものも row に置き、
    次の往復の下請けが前の往復からの差分を見る元にする）"""
    doc = read(b)
    doc["plan"] = [{"id": item_id(r.get("unit_keys")), "unit_keys": [str(k) for k in r.get("unit_keys") or []],
                    "hash": item_hash(r), "row": copy.deepcopy(r)} for r in rows if isinstance(r, dict)]
    _write(b, doc)


def _last_items(doc: dict) -> dict:
    return {it["id"]: it for it in (doc["passes"][-1].get("items") or [])} if doc["passes"] else {}


def open_items(b) -> list[int]:
    """次の事前審査が見る項目の番号（今の案の項目のうち、最後の往復で閉じた・保留にした項目でない物）。項目の控えが無ければ []"""
    doc = read(b)
    last = _last_items(doc)
    return [n for n, it in enumerate(doc.get("plan") or [], 1)
            if (last.get(it["id"]) or {}).get("state") not in (CLOSED, HELD)]


def prev_row(b, n: int) -> dict | None:
    """項目 n（今の案の項目の控え）を最後に審査した往復のその項目の行（同じ id。無い・行の控えの無い古い控えなら None）"""
    doc = read(b)
    plan = doc.get("plan") or []
    if not 1 <= n <= len(plan):
        return None
    for p in reversed(doc["passes"]):
        it = next((x for x in p.get("items") or [] if x.get("id") == plan[n - 1]["id"]), None)
        if it is not None and "row" in it:
            return it["row"]
    return None


def answered_hits(b, n: int) -> list:
    """項目 n（同じ id）の前の往復の当たりの答えの行（受け付けが下請けの答えから引いて items の hits に置いた物。新しい往復の順）"""
    doc = read(b)
    plan = doc.get("plan") or []
    if not 1 <= n <= len(plan):
        return []
    return [{**h, "pass": p["pass"]} for p in reversed(doc["passes"]) for x in p.get("items") or []
            if x.get("id") == plan[n - 1]["id"] for h in x.get("hits") or []]


def carried_notes(b) -> list:
    """前の往復の suggest の穴（往復の行の notes。key で 1 つ・新しい物を採る）のうち、どの往復でも block でなかった物"""
    doc = read(b)
    blocks = {k for p in doc["passes"] for k in p.get("blocks", [])}
    out = {}
    for p in doc["passes"]:
        for f in p.get("notes") or []:
            if f.get("key") not in blocks:
                out[f.get("key")] = f
    return list(out.values())


def item_blocks(b, n: int) -> list:
    """項目 n（1 始まり。今の案の項目の控え）が答える前の往復の block の key（resolved_gaps と同じ決まり: unit_keys が項目と
    重なる block と、どの項目とも重ならない block。出た順・重なりは 1 つ）。控えか往復が無ければ []"""
    doc = read(b)
    plan = doc.get("plan") or []
    if not doc["passes"] or not 1 <= n <= len(plan):
        return []
    mine = {str(k) for k in plan[n - 1]["unit_keys"]}
    every = {str(k) for it in plan for k in it["unit_keys"]}
    out = [key for p in doc["passes"] for key in p.get("blocks", [])
           if (set((p.get("face_units") or {}).get(key) or []) & mine)
           or not (set((p.get("face_units") or {}).get(key) or []) & every)]
    return list(dict.fromkeys(out))


def _filled_ids(doc: dict) -> dict:
    """今の案の項目の id → 最後の往復で閉じた・保留にした項目の state（開いた項目・まだ審査していない項目は入らない）"""
    last = _last_items(doc)
    return {it["id"]: last[it["id"]]["state"] for it in doc.get("plan") or []
            if (last.get(it["id"]) or {}).get("state") in (CLOSED, HELD)}


def filled_units(b) -> list[str]:
    """機械が前の往復の行を差し込む項目（最後の往復で閉じた・保留にした項目）の単位の key。項目の控えが無ければ []"""
    doc = read(b)
    filled = _filled_ids(doc)
    return [k for it in doc.get("plan") or [] if it["id"] in filled for k in it["unit_keys"]]


def splice(b, rows: list) -> tuple[list, list[str], list[str]]:
    """直しの役が返した行（名前に戻した行の並び）に前の往復の行を差し込んだ案の全体, 拒む行, 捨てた id を返す。
    控えの案の順に、閉じた項目は控えの行、開いた項目と保留の項目は返答の同じ id の行を並べる。控えに当たらない返答の行（単位を
    組み替えた行・新しい項目の行）は返答の順で後ろに足す（捨てない）。保留の項目の行が返答に無く、その単位がどの返答の行にも
    無ければ控えの行を差し込む。閉じた項目の行が返答に在って控えと同じ hash なら捨て（捨てた id）、違えば拒む。閉じた項目の単位を
    別の行に入れた返答、開いた項目の行も単位も返答に無い返答も拒む"""
    doc = read(b)
    given = [r for r in rows if isinstance(r, dict)]
    by_id = {}
    for r in given:
        by_id.setdefault(item_id(r.get("unit_keys")), r)
    in_rows = {str(k) for r in given for k in r.get("unit_keys") or []}
    filled = _filled_ids(doc)
    whole, rejects, dropped, used = [], [], [], set()
    for n, it in enumerate(doc.get("plan") or [], 1):
        mine = by_id.get(it["id"])
        homeless = not {str(k) for k in it["unit_keys"]} & in_rows
        if filled.get(it["id"]) == CLOSED:
            if mine is not None:
                used.add(id(mine))
                if item_hash(mine) == it["hash"]:
                    dropped.append(it["id"])
                else:
                    rejects.append(f"閉じた項目 {n} を変えた（書くな。機械が差し込む）")
            elif not homeless:
                rejects.append(f"閉じた項目 {n} の単位を別の行に入れた（書くな。機械が差し込む）")
            if "row" in it:
                whole.append(copy.deepcopy(it["row"]))
        elif mine is not None:
            used.add(id(mine))
            whole.append(mine)
        elif homeless and filled.get(it["id"]) == HELD:
            if "row" in it:
                whole.append(copy.deepcopy(it["row"]))
        elif homeless:
            rejects.append(f"開いた項目 {n} の行が無い（変えないなら前のまま返せ・単位を移したなら移した行に入れよ）")
    whole += [r for r in given if id(r) not in used]
    return whole, rejects, dropped


def record_pass(b, review: dict, *, resolved: list, fence: int, files: dict, synergy: list | None = None,
                hits: dict | None = None) -> dict:
    """事前審査の返答 1 つを往復の行として足し、decide で抜け方を決めて控えを書く。files（{名: パス}）の在るファイルを
    pass-<k>/ に写し、写した先を行に置く。盤面の trace に OP の行を書く。控えに項目（note_plan）が在れば行に items・
    synergy（相乗りの審査が挙げた key）・face_units を置き、hits（{項目の番号: 当たりの答えの行}。受け付けが下請けの答えの
    ファイルから引いた物）を審査した項目の items の行に置く。返りは足した行"""
    doc = read(b)
    passes = doc["passes"]
    k = len(passes) + 1
    faces = block_faces(review)
    blocks = [f.get("key") for f in faces]
    earlier = {key for p in passes for key in p.get("blocks", [])}
    suggests = [f.get("key") for f in _faces(review) if f.get("severity") != "block"]
    row = {"pass": k, "blocks": blocks, "faces": [{n: f.get(n, "") for n in FACE_KEYS} for f in faces],
           "suggests": list(dict.fromkeys(suggests)), "answers": doc["open"].get("answers", []),
           "notes": list({f.get("key"): copy.deepcopy(f) for f in _faces(review) if f.get("severity") != "block"}.values()),
           "resolved": list(resolved), "persists": [key for key in blocks if key in earlier], "outcome": None,
           "files": {}, "rejects": []}
    if doc.get("plan"):
        row["face_units"] = {f.get("key"): [str(k) for k in f.get("unit_keys") or []] for f in faces}
        row["items"] = _item_states(doc["plan"], faces, row["face_units"],
                                    list(_last_items(doc).values()), earlier)
        for it in row["items"]:
            if it["n"] in (hits or {}):
                it["hits"] = copy.deepcopy(hits[it["n"]])
        row["synergy"] = list(synergy or [])
    passes.append(row)
    row["outcome"] = decide(passes, fence=fence)
    dest = b.work(PASS_DIR) / f"pass-{k}"
    for name, src in files.items():
        if os.path.isfile(src):
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, dest / name)
            row["files"][name] = str(dest / name)
    doc.update(outcome=row["outcome"], open={})
    _write(b, doc)
    extra = {"items": {it["n"]: it["state"] for it in row["items"]}} if "items" in row else {}
    b.trace(OP, round=b.round, pass_=k, outcome=row["outcome"], blocks=blocks, persists=row["persists"], **extra)
    return row


def stash_rejects(b, rows: list) -> None:
    """最後の往復の行の rejects に足す（往復が無ければ何もしない）"""
    doc = read(b)
    if doc["passes"]:
        doc["passes"][-1].setdefault("rejects", []).extend(rows)
        _write(b, doc)


def held(b) -> dict | None:
    """抜け方が AGAIN（修正案の役に返す）時の最後の往復の行"""
    doc = read(b)
    return doc["passes"][-1] if doc["outcome"] == AGAIN and doc["passes"] else None


# ---------------------------------------------------------------- 返答の欄
def _open_blocks(row: dict) -> list:
    """往復の行の block のうち、開いた項目の物（items の無い行は全部）"""
    if row.get("items") is None:
        return list(row["blocks"])
    mine = {k for it in row["items"] if it.get("state") == OPEN for k in it.get("blocks") or []}
    return [k for k in row["blocks"] if k in mine]


def answer_gaps(b, answers) -> list[str]:
    """修正案の役の block_answers の欠けと誤り。返した block の key ごとに、key が一字違わず、handled が HANDLED のどれかで、
    how が 10 字以上の行がちょうど 1 つ要る"""
    row = held(b)
    blocks = _open_blocks(row) if row else []
    rows = [a for a in answers if isinstance(a, dict)] if isinstance(answers, list) else []
    shaped = isinstance(answers, list) and len(rows) == len(answers)
    gaps = [] if shaped else ["block_answers の行の形が違う（{key, handled, how} の行の配列）"]
    for key in blocks:
        mine = [a for a in rows if a.get("key") == key]
        if not mine:
            gaps.append(f"block の key {key} への答えが無い")
            continue
        if len(mine) > 1:
            gaps.append(f"block の key {key} への答えが {len(mine)} 行ある（1 行だけにせよ）")
            continue
        a = mine[0]
        if a.get("handled") not in HANDLED:
            gaps.append(f"{key} の handled は fixed か disputed のどちらか（今は {a.get('handled')!r}）")
        if not isinstance(a.get("how"), str) or len(a["how"]) < 10:
            gaps.append(f"{key} の how が短い（10 字以上で、直した所か異を唱える根拠を書け）")
    gaps += [f"{a.get('key')} は前の往復の block に無い" for a in rows if a.get("key") not in blocks]
    return gaps


def resolved_gaps(b, faces: list, resolved: list) -> list[str]:
    """事前審査の役の resolved の欠けと誤り。前のどの往復かで block だった key は、resolved か faces のどちらかに要る（1 往復目は
    前の往復が無いので見ない）"""
    doc = read(b)
    passes = doc["passes"]
    if not passes:
        return []
    earlier = list(dict.fromkeys(key for p in passes for key in p.get("blocks", [])))
    wanted = earlier
    if passes[-1].get("items") is not None:   # 項目の控え: 今の往復で審査する項目の物だけを求める
        units = {str(k) for n in open_items(b) for k in doc["plan"][n - 1]["unit_keys"]}
        every = {str(k) for it in doc.get("plan") or [] for k in it["unit_keys"]}
        wanted = [key for p in passes for key in p.get("blocks", [])
                  if (set((p.get("face_units") or {}).get(key) or []) & units)
                  or not (set((p.get("face_units") or {}).get(key) or []) & every)]
        wanted = list(dict.fromkeys(wanted))
    face_keys = {f.get("key") for f in faces if isinstance(f, dict)}
    block_keys = {f.get("key") for f in block_faces({"faces": faces})}
    gaps = [f"前の block {key} を resolved に入れるか、同じ key で faces に挙げ直せ"
            for key in wanted if key not in resolved and key not in face_keys]
    gaps += [f"resolved の {key} は前の往復の block に無い" for key in resolved if key not in earlier]
    gaps += [f"{key} が resolved と block の face の両方に在る（消えたか残ったかのどちらか 1 つにせよ）"
             for key in resolved if key in block_keys]
    return gaps


def with_fields(role: str, schema: dict) -> dict:
    """役の型に壁打ちの欄を足した写し（plan-revise は必須の block_answers、plan-review は任意の resolved。ほかの役はそのまま）"""
    if role not in FIELDS:
        return schema
    name, field, required = FIELDS[role]
    # TREE_FIELDS は任意（同じ役の型を案の直しの事前審査も使う）
    return marks.add("converge", role, schema, {name: field, **TREE_FIELDS.get(role, {})}, required=(name,) if required else ())


def split(role: str, reply: dict) -> tuple[dict, list]:
    """（壁打ちの欄を外した返答の写し, 外した値（無ければ []））"""
    if role not in FIELDS:
        return copy.deepcopy(reply), []
    out, got = marks.split("converge", role, reply, (FIELDS[role][0],))
    got = got.get(FIELDS[role][0])
    return out, got if isinstance(got, list) else []


def tree_split(reply: dict) -> tuple[dict, dict]:
    """（束ね役の欄 ITEMS・SYNERGY を外した返答の写し, {ITEMS: 値 | None, SYNERGY: 値 | None}）"""
    out, got = marks.split("converge", "plan-review", reply, (ITEMS, SYNERGY))
    return out, {name: got.get(name) for name in (ITEMS, SYNERGY)}


def drop_fields(reply):
    """事前審査の返答から壁打ちの欄（RESOLVED・ITEMS・SYNERGY）を外した写し（案の直しの事前審査は写しの型で受ける）"""
    if not isinstance(reply, dict):
        return reply
    return marks.split("converge", "plan-review", reply, (RESOLVED, ITEMS, SYNERGY))[0]


# ---------------------------------------------------------------- 文
def _keys(keys) -> str:
    return "、".join(keys) if keys else NONE


FACE_HEAD = promptsection.Section("### {key}", source="fn:converge._face_text")
PASS_HEAD = promptsection.Section("## {n} 往復目の block", source="fn:converge.review_section")


def _face_text(f: dict) -> str:
    return "\n".join([FACE_HEAD.format(key=f['key']), *(f"- {n}: {f[n]}" for n in FACE_KEYS[1:])])


def revise_section(b) -> str:
    """修正案の役に返す時の指示書の節（REVISE_ASK と、返した block の face 1 件 1 節と、suggest の key）。返さない時は空"""
    row = held(b)
    if row is None:
        return ""
    mine = set(_open_blocks(row))
    parts = [REVISE_ASK, *(_face_text(f) for f in row["faces"] if f["key"] in mine)]
    notes = row.get("notes")
    parts.append("\n\n".join([NOTES_HEAD, *(_face_text(f) for f in notes)]) if notes
                 else f"suggest の key: {_keys(row['suggests'])}")
    for state, head in ((CLOSED, CLOSED_ASK), (HELD, HELD_NOTE)):
        named = [it for it in row.get("items") or [] if it.get("state") == state]
        if named:
            parts.append("\n".join([head, *(f"- {_label(it)}" for it in named)]))
    return "\n\n".join(parts)


def review_section(b) -> str:
    """2 往復目からの事前審査の指示書の節（REREVIEW_ASK と、前の往復ごとの block の face と修正案の役の答え）。1 往復目は空"""
    doc = read(b)
    passes = doc["passes"]
    if not passes:
        return ""
    replies = [p.get("answers", []) for p in passes[1:]] + [doc["open"].get("answers", [])]
    parts = [REREVIEW_ASK]
    for p, answers in zip(passes, replies):
        parts.append(PASS_HEAD.format(n=p['pass']))
        parts += [_face_text(f) for f in p["faces"]] or [NONE]
        parts.append("修正案の役の答え:\n" + ("\n".join(f"- {a.get('key')}: {a.get('handled')}（{a.get('how')}）"
                                                      for a in answers) or NONE))
    return "\n\n".join(parts)


def stuck_reason(b) -> str:
    """止まった壁打ちの関所の理由（PERSISTED・UNSETTLED の時だけ。ほかは空）"""
    doc = read(b)
    if doc["outcome"] not in STUCK:
        return ""
    last = doc["passes"][-1]
    text = PERSISTED_WHY if doc["outcome"] == PERSISTED else UNSETTLED_WHY
    keys = last["persists"] if doc["outcome"] == PERSISTED else last["blocks"]
    if last.get("items") is not None:   # 保留の項目の block は前の往復の物（今の往復は審査しない）
        keys = list(dict.fromkeys(k for it in last["items"] if it.get("state") in (HELD, OPEN) for k in it["blocks"]))
    why = text.format(keys=_keys(keys), n=len(doc["passes"]), path=b.work(PASS_DIR))
    return why + ("。" + _items_text(last["items"]) if last.get("items") is not None else "")


def _items_text(items: list) -> str:
    def named(state, blocks=False):
        rows = [_label(it) + (f"・最後の block: {_keys(it['blocks'])}" if blocks else "")
                for it in items if it.get("state") == state]
        return "、".join(rows) or NONE
    return ITEMS_WHY.format(closed=named(CLOSED), held=named(HELD, True), open=named(OPEN, True))


def lines(b) -> list[str]:
    """報告の行（往復が無ければ []。在れば頭の 1 行と往復ごとの 1 行）"""
    doc = read(b)
    passes = doc["passes"]
    if not passes:
        return []
    persists = list(dict.fromkeys(key for p in passes for key in p.get("persists", [])))
    out = [LINE_HEAD.format(n=len(passes), word=WORDS.get(doc["outcome"], doc["outcome"]), outcome=doc["outcome"],
                            persists=_keys(persists), path=b.work(PASS_DIR))]
    earlier = set()
    for p in passes:
        handled = [a.get("handled") for a in p.get("answers", []) if isinstance(a, dict)]
        down = [key for key in p.get("suggests", []) if key in earlier]   # 前の往復の block を suggest に下げた key
        out.append(LINE_PASS.format(k=p["pass"], keys=_keys(p["blocks"]), f=handled.count("fixed"),
                                    d=handled.count("disputed"), resolved=_keys(p.get("resolved", [])), down=_keys(down)))
        if p.get("items") is not None:
            count = {st: [str(it["n"]) for it in p["items"] if it.get("state") == st] for st in (CLOSED, OPEN, HELD)}
            out.append(LINE_ITEMS.format(closed=_keys(count[CLOSED]), open=_keys(count[OPEN]), held=_keys(count[HELD]),
                                         synergy=_keys(p.get("synergy") or [])))
        earlier.update(p.get("blocks", []))
    return out
