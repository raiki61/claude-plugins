"""返答の足し欄（marks）の住処: 写しの graph の型が持てない works の欄を、役の型にだけ足し、受け付けが盤面へ渡す前に外し、
盤面の控えに置き、後で読み戻す手順（地図 docs/concepts.md の marks）。

写しの graph の型は欄を足せない（写しはバイト一致で縛られる）。そこで works の欄は役の型（accept.role_schema・ブロックの
output_format）にだけ足し、受け付けが返答から外してから盤面へ渡し、外した欄は盤面の控えに置く。手順はここ 1 か所に住み、
欄を持つモジュールは欄の意味（欄の型・欠けと誤りの検査・控えの中身の形・読んだ後の使い方）だけを持つ。

- KINDS: 種の表。1 行は Kind(at, file, place):
  at＝節（か役）の名 → 行の在り処（型と返答で同じ道。鍵の名か EACH＝並びの各行）、
  file＝盤面の控えの名（None は控えを別の考えの記録に置く種）、place＝ROOT（盤面の根）か WORK（今の周の作業の置き場）
- nodes(kind): 欄を持つ節（か役）の名
- add(kind, node, schema, fields, required=()): 役の型の写しの行に欄を足す（表に無い節は渡した物をそのまま返す）
- rows(kind, node, reply): 欄を持つ行（写さずにその場の物）を道の形で（検査が行を名指すのに使う。表に無い節は None）
- split(kind, node, reply, names): （欄を外した返答の写し, 外した欄）。外した欄は道の EACH の段だけ入れ子の並びで、葉は
  外した欄の dict。形の崩れた返答（dict でない・並びでない）でも落ちず、その所は空（{} か []）。表に無い節は（写し, None）
- path_of(kind, board)・write(path, doc)・load(path): 控えの置き場・一時のファイルから置き換える書き方（リンクの先へ書かない。
  置いたバイトを返す）・読み方（無い・読めない・JSON でなければ None）

標準ライブラリだけ（works のほかの物を import しない）。
"""
from __future__ import annotations

import copy
import json
import os
import pathlib
from typing import NamedTuple

EACH = "[]"
ROOT = "root"
WORK = "work"


class Kind(NamedTuple):
    at: dict
    file: str | None
    place: str


KINDS = {
    # 修正前の関所の項目の決め手（gatemarks）: 修正案の narrows の行と事前審査の faces の行
    "gate": Kind({"p2.fix_plan": ("plan", EACH, "narrows", EACH), "p2.plan_review": ("faces", EACH)}, "gate-marks.json", ROOT),
    # 修正案の項目の works の欄（planmarks）
    "plan": Kind({"p2.fix_plan": ("plan", EACH)}, "plan-fields.json", ROOT),
    # 差分の審査の 2 判定（deltamarks）
    "delta": Kind({"p3.delta_review": ()}, "delta-verdicts.json", WORK),
    # 事前審査の壁打ちの欄（converge。控えは壁打ちの往復の記録に置く）
    "converge": Kind({"plan-revise": (), "plan-review": ()}, None, WORK),
    # 判定の問いの例（querytest）
    "query": Kind({n: ("units", EACH, "class_query") for n in ("p2.diagnose", "p2.rejudge", "p2.rejudge_third")},
                  "query-examples.json", ROOT),
    # 判定が凍結した目的の外の所見（outpurpose）
    "purpose": Kind({"p2.diagnose": ()}, "out-of-purpose.json", ROOT),
    # 並行 PR の任せ先が外す hunk（prcheck）
    "pr": Kind({"p0.parallel_pr": ()}, "pr-excluded.json", WORK),
}


def nodes(kind: str) -> tuple:
    return tuple(KINDS[kind].at)


def add(kind: str, node: str, schema: dict, fields: dict, required=()) -> dict:
    """schema の写しの、node の行の在り処の properties に fields を足し、required に無い名を後ろに足す（required が空なら
    required に触らない）。node が表に無ければ schema をそのまま返す"""
    steps = KINDS[kind].at.get(node)
    if steps is None:
        return schema
    out = copy.deepcopy(schema)
    row = out
    for k in steps:
        row = row["items"] if k == EACH else row["properties"][k]
    row.setdefault("properties", {}).update(copy.deepcopy(fields))
    if required:
        have = row.get("required", [])
        row["required"] = [*have, *dict.fromkeys(k for k in required if k not in have)]
    return out


def _walk(obj, steps, leaf):
    """道を辿り、行ごとに leaf(行) を呼んだ値を EACH の段だけ入れ子の並びで返す（並びでない所は []、dict でない所は None で辿る）"""
    if not steps:
        return leaf(obj)
    k, rest = steps[0], steps[1:]
    if k == EACH:
        return [_walk(x, rest, leaf) for x in obj] if isinstance(obj, list) else []
    return _walk(obj.get(k) if isinstance(obj, dict) else None, rest, leaf)


def rows(kind: str, node: str, reply):
    """reply の欄を持つ行（写さずにその場の物）を道の形で。node が表に無ければ None"""
    steps = KINDS[kind].at.get(node)
    return None if steps is None else _walk(reply, steps, lambda row: row)


def split(kind: str, node: str, reply, names) -> tuple:
    """（names の欄を外した reply の写し, 外した欄）。reply は変えない"""
    out = copy.deepcopy(reply)
    steps = KINDS[kind].at.get(node)
    if steps is None:
        return out, None
    names = tuple(names)
    return out, _walk(out, steps, lambda row: {k: row.pop(k) for k in names if k in row} if isinstance(row, dict) else {})


def path_of(kind: str, board) -> pathlib.Path:
    """控えのパス。ROOT は盤面の根（board は盤面か、その置き場のパス）、WORK は今の周の作業の置き場（board.work）"""
    k = KINDS[kind]
    if k.place == WORK:
        return board.work(k.file)
    return pathlib.Path(getattr(board, "dir", board)) / k.file


def write(path, doc) -> bytes:
    """doc を JSON（字のまま・字下げ 1・末尾の改行）で、一時のファイル <名>.tmp から os.replace で置く（リンクは置き換え、
    先へ書かない）。置いたバイトを返す"""
    p = pathlib.Path(path)
    raw = (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    tmp = p.with_name(p.name + ".tmp")
    tmp.unlink(missing_ok=True)
    tmp.write_bytes(raw)
    os.replace(tmp, p)
    return raw


def load(path):
    """控えの中身。無い・読めない・JSON でなければ None"""
    try:
        return json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
