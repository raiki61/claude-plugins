"""単位ごとの深さ（計画 docs/plans/2026-10-06-variable-depth.md。ライン darkfactory の模块・層 L6）。使うのは darkfactory/scripts/depth.py。

判定が切った単位ごとに、修正案の項目の欄（plan-fields.json）の形から深さ（軽量か標準）を機械が決め、修正の後の信号で標準へ上げる。
標準は今の振る舞いのすべて。軽量は、測りで何も見つけなかった確かめ（レンズ・独立の目のコメントの削除候補）を省く。省くのは
graph の外の物と graph が optional と言う物だけ（写しの graph と盤面の層は変えない）。ブロックはこの控えを読まない——線が
省く理由の文（skip_reason）を平の入力として渡す。

- unit_depth(items, key, *, checked): 単位 1 つの (深さ, 理由の並び)。決め 3 の 5 つの条件を全部満たす時だけ軽量
- decide_doc(items, open_units, *, forced, checked): 直す義務の単位の全部の深さ（控えの形）。forced は入力 thickness の語
  （空・自動は機械が決める。軽量・標準は全部をその深さに固定）
- raise_doc(doc, *, units, run): 信号で標準へ上げた控え。units は {単位: 理由}（その単位だけ）、run は理由の並び（全部の単位）。下げない
- run_depth(doc): 切った後の run 全体の段の深さ（全部の単位が軽量の時だけ軽量。単位が無ければ標準）
- skip_reason(doc): run が軽量なら省く理由の文、標準なら空（ブロックの平の入力 skip・skip_optional に渡す）
- lines(doc): 報告の冒頭 2 の行（単位ごとの深さの数・上げた理由・軽量で省いた物）
- unit_map(doc): {単位: 深さ} の JSON の文字列（修正のブロックへのつなぎ目。計画の「blk-fix へのつなぎ目」）
- write(board_dir, doc)・read(board_dir): 盤面の根の控え depth.json
- decide(board_dir, open_units, *, checked)・signals(board_dir)・raise_(board_dir, *, replanned, rejudged): 盤面を読む口
"""
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

LIGHT = "軽量"
STANDARD = "標準"
FILE = "depth.json"   # 盤面の根の控え {"units": {key: {"depth", "why": [...]}}, "forced", "raised": [...]}
MAX_PATHS = 3         # 測り: 何も見つけなかった単位は allowed_paths 1〜3 個、見つけた単位は 4 個以上
MAX_TESTS = 2         # 測り: 同じく受け入れのテストと書き換える既存のテストが合わせて 1 本、見つけた単位は 4 本以上
CONTRACT_SUFFIXES = (".json", ".yaml", ".yml", ".toml")
CONTRACT_DIR = "schemas/"
GLOB_CHARS = ("*", "?", "[")
# 軽量の run で省く物（報告の冒頭 2 に 1 行ずつ名指す）。どれも 2026-10-05 の自分食いの小さい run で何も見つけなかった
SKIPPED = ("レンズ（修正の後の局所レビューの全部。graph の外）",
           "独立の目の r1.comment_candidates（コメントの削除候補。graph で optional。R1 の本体は回す）")


def _items_of(items, key: str) -> list:
    return [it for it in items or [] if isinstance(it, dict) and key in (it.get("unit_keys") or [])]


def _paths(items: list) -> list:
    return [p for it in items for p in it.get("allowed_paths") or [] if isinstance(p, str)]


def _tests(items: list) -> int:
    return sum(len(it.get("tests") or []) + len(it.get("rewrite_tests") or []) for it in items)


def _contract(path: str) -> bool:
    return path.endswith(CONTRACT_SUFFIXES) or CONTRACT_DIR in path


def unit_depth(items, key: str, *, checked: bool) -> tuple:
    """単位 key の (深さ, 理由の並び)。外れた条件が 1 つでも在れば標準で、外れた条件を全部並べる"""
    mine = _items_of(items, key)
    if not mine:
        return STANDARD, ["単位を載せる修正案の項目が無い（形が分からない）"]
    paths, tests = _paths(mine), _tests(mine)
    out = []
    if len(paths) > MAX_PATHS:
        out.append(f"触るファイルが {len(paths)} 個（{MAX_PATHS} 個まで）")
    globs = [p for p in paths if any(c in p for c in GLOB_CHARS)]
    if globs:
        out.append(f"触るファイルに glob が在る（{', '.join(globs)}）")
    if tests > MAX_TESTS:
        out.append(f"受け入れと書き換えのテストが {tests} 本（{MAX_TESTS} 本まで）")
    contracts = [p for p in paths if _contract(p)]
    if contracts:
        out.append(f"約束の形のファイルを触る（{', '.join(contracts)}）")
    if not checked:
        out.append("機械の確かめが無い（tdd_suite も test_cmd も空）")
    if out:
        return STANDARD, out
    return LIGHT, [f"触るファイル {len(paths)} 個・テスト {tests} 本・約束の形のファイルなし・機械の確かめあり"]


def decide_doc(items, open_units, *, forced: str, checked: bool) -> dict:
    forced = (forced or "").strip()
    units = {}
    for key in open_units or []:
        if forced in (LIGHT, STANDARD):
            units[key] = {"depth": forced, "why": [f"入力 thickness の名指し（{forced}）"]}
        else:
            d, why = unit_depth(items, key, checked=checked)
            units[key] = {"depth": d, "why": why}
    return {"units": units, "forced": forced, "raised": []}


def raise_doc(doc: dict, *, units: dict, run: list) -> dict:
    out = json.loads(json.dumps(doc))
    raised = list(out.get("raised") or [])
    for key, why in units.items():
        if key not in out["units"]:
            raised.append(f"{key}: {why}（直す義務の単位の外）")
            continue
        row = out["units"][key]
        if row["depth"] != STANDARD:
            row["depth"] = STANDARD
            row["why"] = [*row["why"], f"標準へ上げた: {why}"]
    for why in run:
        raised.append(why)
        for row in out["units"].values():
            if row["depth"] != STANDARD:
                row["depth"] = STANDARD
                row["why"] = [*row["why"], f"標準へ上げた: {why}"]
    out["raised"] = raised
    return out


def run_depth(doc) -> str:
    rows = list(((doc or {}).get("units") or {}).values())
    return LIGHT if rows and all(r.get("depth") == LIGHT for r in rows) else STANDARD


def skip_reason(doc) -> str:
    if run_depth(doc) != LIGHT:
        return ""
    return f"軽量で省いた（直す義務の単位 {len(doc['units'])} 個がすべて軽量。計画 2026-10-06-variable-depth の決め 6）"


def lines(doc) -> list:
    rows = ((doc or {}).get("units") or {})
    if not rows:
        return [f"深さ: {STANDARD}（直す義務の単位が無い）"]
    light = sum(1 for r in rows.values() if r.get("depth") == LIGHT)
    head = f"深さ: {run_depth(doc)}（単位ごと: {LIGHT} {light} 個・{STANDARD} {len(rows) - light} 個"
    head += f"。入力 thickness の名指し {doc['forced']}）" if doc.get("forced") in (LIGHT, STANDARD) else "。機械が決めた）"
    out = [head]
    out += [f"  - {k[:80]}: {r.get('depth')}（{' / '.join(r.get('why') or [])}）" for k, r in rows.items()]
    out += [f"  - 標準へ上げた信号: {why}" for why in doc.get("raised") or []]
    if run_depth(doc) == LIGHT:
        out += [f"軽量で省いた: {what}" for what in SKIPPED]
    return out


def unit_map(doc) -> str:
    return json.dumps({k: r.get("depth") for k, r in ((doc or {}).get("units") or {}).items()}, ensure_ascii=False)


def write(board_dir, doc: dict) -> pathlib.Path:
    path = pathlib.Path(board_dir) / FILE
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, path)
    return path


def read(board_dir):
    """控え（無ければ None。読めない・形が違えば ValueError）"""
    path = pathlib.Path(board_dir) / FILE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ValueError(f"深さの控え {path} が読めない: {e}") from None
    if not isinstance(doc, dict) or not isinstance(doc.get("units"), dict):
        raise ValueError(f"深さの控え {path} の形が違う（units が要る）")
    return doc
