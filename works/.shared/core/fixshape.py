"""修正の形（fix_shape）の語と、盤面からの 1 つの読み口（計画 220 Task 1）。標準ライブラリだけ（包みが読む L2）。

語:
- 形: 修正の工程の作り方の 4 つ。current（比べの基準）・af（works 自身の文で回す今の形）・g3（af に借りたスキルの座を足した形。
  既定）・g1（修正役 1 つが SDD の型で下請けを回す形）。
- 盤面の控え:
  - START_REL（r1/start.json）: 線の start が入力 fix_shape を確かめて置く控え（鍵 KEY）。
  - CHOICE_REL（r1/fix-shape.json）: 後の振り分けが選んだ形の控え {shape, by, why}。この計画では試験のほか誰も書かない。

口:
- word(raw): 入力の値を形の語にする（空は DEFAULT。語の外は ValueError）
- shape_at(board_dir): 盤面の形。読む順は CHOICE_REL の shape → START_REL の KEY → BEFORE（記録の無い前の版の盤面）。
  ファイルが無い・鍵が無いなら次へ。JSON が読めない・値が語の外なら ValueError（黙って既定にしない）
- recorded(board_dir): start の控えの記録そのもの {shape: KEY の値か None, fixture: 固定材料の印 FIXTURE_KEY の欄か None}。
  shape_at が隠す「鍵が無い」を測る関数が数える（preflight F6）。固定材料の印の読み口もこれ 1 つ（fixture.adopted が呼ぶ）
- choose(board_dir, shape, *, by, why): CHOICE_REL を書く（後の振り分けの書き口）
- plain(board_dir): 平の run（形が PLAIN＝current）か
- SKILL_NODES: 座が skill の節の名（seat の表と試験で一致を縛る）
- AGENT_NODES: 修正役の節の名（AGENT_SHAPES の形だけ Agent で下請けを起こす）
- SEAT_SHAPE・AGENT_SHAPE・AGENT_SHAPES・DENY: 座の載る形・SDD の型だけで回す形（g1）・修正役が下請けを起こす形の全部（g1 と g3。
  依頼 243 の 2 で既定の g3 の修正役も単位ごとに新しい会話の下請けを起こす）と、形ごとの道具の柵の表（seat がこの語を引く）
- denied_tools(shape, node): 形と印の名から包みが permissions.deny で拒む道具（DENY を引く。g3 以外の座の節で Skill・g1 と g3 の
  外の修正役で Agent）

形はいつもこの shape_at から引く（ブロック・包み・測る関数が start.json を直に読まない）。
"""
from __future__ import annotations

import json
import os
import pathlib

SHAPES = ("current", "af", "g3", "g1")
DEFAULT = "g3"            # 入力が空の run の形
BEFORE = "af"             # 形の記録の無い盤面（220 の前の版で作った盤面）の形
PLAIN = "current"         # 平の run の形（比べの基準。plain が読む）
KEY = "fix_shape"         # start の控えの鍵（ラインの入力の名と同じ）
START_REL = "r1/start.json"       # 線の start の控え（entry.START_FILE の 1 周目。L2 なので entry は import しない）
CHOICE_REL = "r1/fix-shape.json"  # 後の振り分けが選んだ形の控え
FIXTURE_KEY = "fixture"           # start の控えの固定材料の印の鍵（fixture.KEY。entry.start が書く。L2 なので fixture は import しない）
# 座が skill の節（借りたスキルを Skill の道具で読む役の印の名。seat.SEATS のうち use_as が skill の物と同じ。形ごとの道具の柵が読む）
SKILL_NODES = frozenset({"tdd", "refix", "refix2"})
# 修正役の節（AGENT_SHAPES の形で SDD の型の下請けを Agent で起こす役の印の名。ほかの形では拒む）
AGENT_NODES = frozenset({"fix", "fix-ruled"})
SEAT_SHAPE = "g3"         # 座が載る形（seat.SHAPE）
AGENT_SHAPE = "g1"        # 修正役が SDD の型だけで回す形（TDD の輪を回さない。seat.G1_SHAPE）
# 修正役が単位ごとの下請けを Agent で起こす形（依頼 243 の 2: 既定の g3 も、輪の後に直す単位を 1 つの会話に積まず下請けに渡す）
AGENT_SHAPES = frozenset({AGENT_SHAPE, SEAT_SHAPE})
# 形ごとの道具の柵の表: 道具 → (その道具を持つ節の名, その道具を持たせる形)。節の役に、形が持たせる形の外なら拒む。
# 腕の違いはこの表の行だけ（denied_tools は表を引くだけ）
DENY = {"Skill": (SKILL_NODES, frozenset({SEAT_SHAPE})), "Agent": (AGENT_NODES, AGENT_SHAPES)}


def _words() -> str:
    return " / ".join(SHAPES)


def word(raw: str) -> str:
    """入力の値を形の語にする。前後の空白を除き、空なら DEFAULT。SHAPES の外は ValueError"""
    v = "" if raw is None else str(raw).strip()
    if not v:
        return DEFAULT
    if v not in SHAPES:
        raise ValueError(f"fix_shape={v} は知らない値（{_words()}）")
    return v


def _doc(path: pathlib.Path) -> dict | None:
    """控え path の object。ファイルが無ければ None。読めない・JSON でない・object でないは ValueError"""
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except OSError as e:
        raise ValueError(f"修正の形の控え {path} を読めない（{type(e).__name__}: {e}）") from None
    try:
        doc = json.loads(text)
    except ValueError as e:
        raise ValueError(f"修正の形の控え {path} が JSON として読めない（{e}）") from None
    if not isinstance(doc, dict):
        raise ValueError(f"修正の形の控え {path} が JSON の object でない")
    return doc


def _read(path: pathlib.Path, key: str) -> str | None:
    """控え path の key の形の語。ファイルが無い・鍵が無いなら None。読めない・形が違う・語の外は ValueError"""
    doc = _doc(path)
    if doc is None or key not in doc:
        return None
    v = doc[key]
    if not isinstance(v, str) or v not in SHAPES:
        raise ValueError(f"修正の形の控え {path} の {key}={v!r} は知らない値（{_words()}）")
    return v


def shape_at(board_dir) -> str:
    """盤面の形: CHOICE_REL の shape → START_REL の KEY → BEFORE の順に、最初に在る物"""
    root = pathlib.Path(board_dir)
    for rel, key in ((CHOICE_REL, "shape"), (START_REL, KEY)):
        got = _read(root / rel, key)
        if got is not None:
            return got
    return BEFORE


def recorded(board_dir) -> dict:
    """start の控え（START_REL）の記録 {"shape": 鍵 KEY の値（語の確かめは shape_at）か None, "fixture": 固定材料の印
    （FIXTURE_KEY の欄が object の時だけ）か None}。控えが無ければ両方 None。読めない・JSON の object でないは ValueError。
    shape_at と違い、鍵が無いことを af に替えて隠さない（測る関数が「形の記録が無い」を数える）"""
    doc = _doc(pathlib.Path(board_dir) / START_REL) or {}
    mark = doc.get(FIXTURE_KEY)
    return {"shape": doc.get(KEY), "fixture": mark if isinstance(mark, dict) else None}


def choose(board_dir, shape: str, *, by: str, why: str) -> None:
    """後の振り分けが選んだ形を CHOICE_REL に書く。shape は SHAPES の内、by・why は空でない。外れは ValueError（書かない）"""
    if shape not in SHAPES:
        raise ValueError(f"fix_shape={shape} は知らない値（{_words()}）")
    for name, v in (("by", by), ("why", why)):
        if not isinstance(v, str) or not v.strip():
            raise ValueError(f"修正の形の控えの {name} が空")
    path = pathlib.Path(board_dir) / CHOICE_REL
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps({"shape": shape, "by": by, "why": why}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def denied_tools(shape: str, node: str) -> tuple[str, ...]:
    """形 shape の盤面で印 node の役に拒む道具（包みが permissions.deny に足す）。表 DENY の順に、node がその道具を持つ節で
    shape が持たせる形の外なら拒む（座の節は g3 の外で Skill、修正役は g1 と g3 の外で Agent）。ほかの節は ()"""
    return tuple(tool for tool, (nodes, allowed) in DENY.items() if node in nodes and shape not in allowed)


def plain(board_dir) -> bool:
    """平の run（形が current）か"""
    return shape_at(board_dir) == PLAIN
