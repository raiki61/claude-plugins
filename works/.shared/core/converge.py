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

- block_faces(review)・decide(passes, fence=): block の face と、続けるか止めるかの語（CLEAN・AGAIN・PERSISTED・UNSETTLED）
- read(b)・pass_no(b)・note_answers(b, answers)・record_pass(b, review, ...)・stash_rejects(b, rows)・held(b):
  控えの読み書き
- answer_gaps(b, answers)・resolved_gaps(b, faces, resolved): 修正案の役と事前審査の役の返答の欄の欠けと誤りの行
- with_fields(role, schema)・split(role, reply): 役の型に欄を足す・返答から欄を外す
- revise_section(b)・review_section(b)・stuck_reason(b)・lines(b): 指示書に足す文・関所の理由・報告の行（往復ごとの行は
  前の往復の block を審査が suggest に下げた key も名指す）

盤面の b のうち round・dir・work・trace だけを使い、標準ライブラリだけを import する（gatemarks がこの模块を読み、entry が
gatemarks を読むので、entry・rolekit・gatemarks を import すると輪になる）。
"""
from __future__ import annotations

import copy
import json
import os
import shutil

RECORD = "plan-converge.json"
PASS_DIR = "plan-converge"
BY = "works:plan-converge"
OP = "plan_converge"
CLEAN, AGAIN, PERSISTED, UNSETTLED = "clean", "again", "persisted", "unsettled"
STUCK = (PERSISTED, UNSETTLED)
ANSWERS = "block_answers"
RESOLVED = "resolved"
HANDLED = ("fixed", "disputed")
FACE_KEYS = ("key", "kind", "where", "why")

REVISE_ASK = ("事前審査（別の目）が、お前の修正案に下の block（直しへ進めない穴）を挙げた。block ごとに、案を直したなら handled に fixed、"
              "how に直した所を、直さずに異を唱えるなら handled に disputed、how に根拠を、block_answers に 1 行ずつ書け（key は下の key を"
              "一字も変えずに写す）。そのうえで直した案を丸ごと plan に返せ（前の案と同じ型。直さない項目もそのまま入れる）。suggest の穴は"
              "採っても採らなくてもよい。直した案は新しい会話の事前審査に掛かり、同じ block が残れば直しへ進まずに人の関所で止まる。")
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
WORDS = {CLEAN: "block が消えた", PERSISTED: "同じ block が続いた", UNSETTLED: "柵の往復でも block が消えない", AGAIN: "途中"}
NONE = "無い"

ANSWER_SCHEMA = {"type": "array", "items": {
    "type": "object", "additionalProperties": False, "required": ["key", "handled", "how"],
    "properties": {"key": {"type": "string", "minLength": 8}, "handled": {"type": "string", "enum": list(HANDLED)},
                   "how": {"type": "string", "minLength": 10}}}}
RESOLVED_SCHEMA = {"type": "array", "items": {"type": "string"}}
FIELDS = {"plan-revise": (ANSWERS, ANSWER_SCHEMA, True), "plan-review": (RESOLVED, RESOLVED_SCHEMA, False)}


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
    """最後の往復の block が無ければ CLEAN、前のどれかの往復の block と重なれば PERSISTED、柵の往復に着けば UNSETTLED、ほかは AGAIN"""
    last = set(passes[-1]["blocks"])
    if not last:
        return CLEAN
    if any(last & set(p["blocks"]) for p in passes[:-1]):
        return PERSISTED
    return UNSETTLED if len(passes) >= fence else AGAIN


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
    return {"round": b.round, "passes": doc["passes"], "outcome": doc.get("outcome"), "open": doc.get("open", {})}


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


def record_pass(b, review: dict, *, resolved: list, fence: int, files: dict) -> dict:
    """事前審査の返答 1 つを往復の行として足し、decide で抜け方を決めて控えを書く。files（{名: パス}）の在るファイルを
    pass-<k>/ に写し、写した先を行に置く。盤面の trace に OP の行を書く。返りは足した行"""
    doc = read(b)
    passes = doc["passes"]
    k = len(passes) + 1
    faces = block_faces(review)
    blocks = [f.get("key") for f in faces]
    earlier = {key for p in passes for key in p.get("blocks", [])}
    suggests = [f.get("key") for f in _faces(review) if f.get("severity") != "block"]
    row = {"pass": k, "blocks": blocks, "faces": [{n: f.get(n, "") for n in FACE_KEYS} for f in faces],
           "suggests": list(dict.fromkeys(suggests)), "answers": doc["open"].get("answers", []),
           "resolved": list(resolved), "persists": [key for key in blocks if key in earlier], "outcome": None,
           "files": {}, "rejects": []}
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
    b.trace(OP, round=b.round, pass_=k, outcome=row["outcome"], blocks=blocks, persists=row["persists"])
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
def answer_gaps(b, answers) -> list[str]:
    """修正案の役の block_answers の欠けと誤り。返した block の key ごとに、key が一字違わず、handled が HANDLED のどれかで、
    how が 10 字以上の行がちょうど 1 つ要る"""
    row = held(b)
    blocks = row["blocks"] if row else []
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
    passes = read(b)["passes"]
    if not passes:
        return []
    earlier = list(dict.fromkeys(key for p in passes for key in p.get("blocks", [])))
    face_keys = {f.get("key") for f in faces if isinstance(f, dict)}
    block_keys = {f.get("key") for f in block_faces({"faces": faces})}
    gaps = [f"前の block {key} を resolved に入れるか、同じ key で faces に挙げ直せ"
            for key in earlier if key not in resolved and key not in face_keys]
    gaps += [f"resolved の {key} は前の往復の block に無い" for key in resolved if key not in earlier]
    gaps += [f"{key} が resolved と block の face の両方に在る（消えたか残ったかのどちらか 1 つにせよ）"
             for key in resolved if key in block_keys]
    return gaps


def with_fields(role: str, schema: dict) -> dict:
    """役の型に壁打ちの欄を足した写し（plan-revise は必須の block_answers、plan-review は任意の resolved。ほかの役はそのまま）"""
    if role not in FIELDS:
        return schema
    name, field, required = FIELDS[role]
    out = copy.deepcopy(schema)
    out.setdefault("properties", {})[name] = copy.deepcopy(field)
    if required and name not in out.get("required", []):
        out["required"] = [*out.get("required", []), name]
    return out


def split(role: str, reply: dict) -> tuple[dict, list]:
    """（壁打ちの欄を外した返答の写し, 外した値（無ければ []））"""
    out = copy.deepcopy(reply)
    got = out.pop(FIELDS[role][0], None) if role in FIELDS else None
    return out, got if isinstance(got, list) else []


# ---------------------------------------------------------------- 文
def _keys(keys) -> str:
    return "、".join(keys) if keys else NONE


def _face_text(f: dict) -> str:
    return "\n".join([f"### {f['key']}", *(f"- {n}: {f[n]}" for n in FACE_KEYS[1:])])


def revise_section(b) -> str:
    """修正案の役に返す時の指示書の節（REVISE_ASK と、返した block の face 1 件 1 節と、suggest の key）。返さない時は空"""
    row = held(b)
    if row is None:
        return ""
    return "\n\n".join([REVISE_ASK, *(_face_text(f) for f in row["faces"]), f"suggest の key: {_keys(row['suggests'])}"])


def review_section(b) -> str:
    """2 往復目からの事前審査の指示書の節（REREVIEW_ASK と、前の往復ごとの block の face と修正案の役の答え）。1 往復目は空"""
    doc = read(b)
    passes = doc["passes"]
    if not passes:
        return ""
    replies = [p.get("answers", []) for p in passes[1:]] + [doc["open"].get("answers", [])]
    parts = [REREVIEW_ASK]
    for p, answers in zip(passes, replies):
        parts.append(f"## {p['pass']} 往復目の block")
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
    return text.format(keys=_keys(keys), n=len(doc["passes"]), path=b.work(PASS_DIR))


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
        earlier.update(p.get("blocks", []))
    return out
