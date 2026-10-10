"""単位ごとの深さ（計画 docs/plans/2026-10-06-variable-depth.md。ライン darkfactory のモジュール・層 L6）。使うのは darkfactory/scripts/depth.py。

判定が切った単位ごとに、修正案の項目の欄（plan-fields.json）の形から深さ（軽量か標準）を機械が決め、修正の後の信号で標準へ上げる。
標準は今の振る舞いのすべて。軽量は、測りで何も見つけなかった確かめ（SKIPPED: 差分の審査とレンズ・手直し、独立の目の R1〜R4 と
コメントの削除候補）を省く。省くのは graph の外の物と graph が optional と言う物だけ（R1〜R4 本体と差分の審査は持ち主の決定
2026-10-06 で写しの graph の ! 行で optional にした）。ブロックはこの控えを読まない——線が省く理由の文（skip_reason）を平の入力
として渡し、差分の審査だけは線の h-redepth が盤面で省く（差分の審査のブロックを起こす前に、境の節 h-review が盤面の待ちを見るため）。

- unit_depth(items, key, *, checked): 単位 1 つの (深さ, 理由の並び)。決め 3 の 5 つの条件を全部満たす時だけ軽量。
  配線だけの単位（触るファイルが全部 wiring の物）は条件 4（約束の形のファイル）に数えない（決め 3 の補い）
- wiring(path): 配線のファイルか（線とブロックの YAML＝<名>/<名>.yaml・.yml と manifest.json。schemas/ の下は除く）
- decide_doc(items, open_units, *, forced, checked): 直す義務の単位の全部の深さ（控えの形）。forced は入力 thickness の語
  （空・自動は機械が決める。軽量・標準は全部をその深さに固定）
- raise_doc(doc, *, units, run): 信号で標準へ上げた控え。units は {単位: 理由}（その単位だけ）、run は理由の並び（全部の単位）。下げない
- run_depth(doc): 切った後の run 全体の段の深さ（全部の単位が軽量の時だけ軽量。単位が無ければ標準）
- skip_reason(doc): run が軽量なら省く理由の文、標準なら空（ブロックの平の入力 skip・skip_optional に渡す）
- lines(doc): 報告の冒頭 2 の行（単位ごとの深さの数・上げた理由・軽量で省いた物）
- unit_map(doc): {単位: 深さ} の JSON の文字列（修正のブロックへのつなぎ目。計画の「blk-fix へのつなぎ目」）
- write(board_dir, doc)・read(board_dir): 盤面の根の控え depth.json
- decide(b, open_units, *, tdd_suite): 盤面を読む口（修正の前の節 h-depth）。修正案の項目の欄（planmarks.read）・start の控えの
  thickness と test_cmd・入力 tdd_suite から決めて控えを書く。open_units は h-fix の出口の JSON の配列の文字列（読めなければ単位なし）
- signals(b): 修正の後の上げる信号 ({単位: 理由}, [run の理由])。食い違いの申し出（各 scope の今の周の conflicts.json）・止めた単位
  （trace の conflict.ACCEPT_PARKED_OP の行）・答えていない問い（gatemarks.pending）
- raise_(b, *, replanned, rejudged): 盤面を読む口（修正の後の節 h-redepth）。signals と線の信号（案の直し・再審が走った）で上げて
  控えを書き直す。控えが無い（h-depth が走らなかった）run は単位なし（標準）。run が軽量のままなら、待っている差分の審査
  （DELTA_NODE）を省く理由（skip_reason）で盤面から省く（board.skip。記録の省略した機構に残る）
"""
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))

import conflict  # noqa: E402
import gatemarks  # noqa: E402
import planmarks  # noqa: E402
import scopes  # noqa: E402
import startrec  # noqa: E402  （始めの記録の読み口）

LIGHT = "軽量"
STANDARD = "標準"
FILE = "depth.json"   # 盤面の根の控え {"units": {key: {"depth", "why": [...]}}, "forced", "raised": [...]}
MAX_PATHS = 3         # 測り: 何も見つけなかった単位は allowed_paths 1〜3 個、見つけた単位は 4 個以上
MAX_TESTS = 2         # 測り: 同じく受け入れのテストと書き換える既存のテストが合わせて 1 本、見つけた単位は 4 本以上
CONTRACT_SUFFIXES = (".json", ".yaml", ".yml", ".toml")
CONTRACT_DIR = "schemas/"
GLOB_CHARS = ("*", "?", "[")
WIRING_FILES = (scopes.MANIFEST,)   # 配線のファイルの名（部品の consumes・produces の宣言）
WIRING_SUFFIXES = (".yaml", ".yml")  # <名>/<名>.yaml の形の物が線とブロックの配線（nodes・include・with）
# 軽量の run で省く物（報告の冒頭 2 に 1 行ずつ名指す）。どれも 2026-10-05 の自分食いの小さい run で何も見つけなかった
# 決め 6 は 2026-10-05 の測り、決め 9 は持ち主の決定 2026-10-06（写しの graph の ! 行で optional にした節）。AI の報告は省かない（決め 10）
SKIPPED = ("差分の審査（p3.delta_review）と、それに続くレンズ・手直し（修正の後の局所レビューの全部を含む）",
           "独立の目の r1.comment_candidates（コメントの削除候補）",
           "独立の目 R1（r1.minimality。冗長と最小性）",
           "独立の目 R2（r2.compare。独立設計との突き合わせ。独立設計そのものは修正の前に作る）",
           "独立の目 R3（r3.coherence。全体の整合）",
           "独立の目 R4（r4.hidden_scope。見えていない範囲）")
DELTA_NODE = "p3.delta_review"   # 軽量の run で線の h-redepth が盤面で省く節（ほかの省く節は目のブロックが入力で受けて省く）


def _items_of(items, key: str) -> list:
    return [it for it in items or [] if isinstance(it, dict) and key in (it.get("unit_keys") or [])]


def _paths(items: list) -> list:
    return [p for it in items for p in it.get("allowed_paths") or [] if isinstance(p, str)]


def _tests(items: list) -> int:
    return sum(len(it.get("tests") or []) + len(it.get("rewrite_tests") or []) for it in items)


def _contract(path: str) -> bool:
    return path.endswith(CONTRACT_SUFFIXES) or CONTRACT_DIR in path


def wiring(path: str) -> bool:
    if CONTRACT_DIR in path:
        return False
    p = pathlib.PurePosixPath(path)
    if p.name in WIRING_FILES:
        return True
    return p.suffix in WIRING_SUFFIXES and len(p.parts) >= 2 and p.stem == p.parent.name


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
    wired = bool(paths) and all(wiring(p) for p in paths)
    contracts = [] if wired else [p for p in paths if _contract(p)]
    if contracts:
        out.append(f"約束の形のファイルを触る（{', '.join(contracts)}）")
    if not checked:
        out.append("機械の確かめが無い（tdd_suite も test_cmd も空）")
    if out:
        return STANDARD, out
    shape = "配線だけ（線とブロックの YAML と manifest.json）" if wired else "約束の形のファイルなし"
    return LIGHT, [f"触るファイル {len(paths)} 個・テスト {tests} 本・{shape}・機械の確かめあり"]


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
        out.append("軽量で省いた: " + "／".join(SKIPPED))   # 1 行にまとめる（項目の中に「・」が在るので区切りは「／」）
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


# ---------------------------------------------------------------- 盤面を読む口（線の節 h-depth・h-redepth）
def _open_units(raw) -> list:
    try:
        got = json.loads(raw) if isinstance(raw, str) else raw
    except ValueError:
        return []
    return [k for k in got if isinstance(k, str)] if isinstance(got, list) else []


def decide(b, open_units, *, tdd_suite: str) -> dict:
    start = startrec.read(b.dir)
    checked = bool((tdd_suite or "").strip() or str(start.get("test_cmd") or "").strip())
    doc = decide_doc(planmarks.read(b), _open_units(open_units), forced=str(start.get("thickness") or ""), checked=checked)
    write(b.dir, doc)
    return doc


def _rows(path) -> list:
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    items = doc.get("items") if isinstance(doc, dict) else doc
    return [r for r in items or [] if isinstance(r, dict)] if isinstance(items, list) else []


def _trace(b, op: str) -> list:
    try:
        lines = (pathlib.Path(b.dir) / "trace.jsonl").read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError):
        return []
    out = []
    for line in lines:
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("op") == op:
            out.append(row)
    return out


def signals(b) -> tuple:
    units = {}
    for path in scopes.each(b, conflict.FILE):
        for r in _rows(path):
            if isinstance(r.get("unit_key"), str):
                units.setdefault(r["unit_key"], "食い違いの申し出が在る")
    for row in _trace(b, conflict.ACCEPT_PARKED_OP):
        for k in row.get("unit_keys") or []:
            if isinstance(k, str):
                units.setdefault(k, "修正の受け付けが最後の回に止めた")
    try:
        held = gatemarks.pending(b)
    except Exception as e:   # 台帳が読めない盤面は上げる側へ倒す（軽量のまま黙って残さない）
        return units, [f"問いの台帳が読めない（{type(e).__name__}）"]
    run = [f"答えていない問い {q.get('key')}" for q in held if isinstance(q, dict)]
    return units, run


def raise_(b, *, replanned: bool, rejudged: bool) -> dict:
    doc = read(b.dir) or {"units": {}, "forced": "", "raised": []}
    units, run = signals(b)
    if replanned:
        run.append("同じ run の案の直しが走った")
    if rejudged:
        run.append("判定への異議の再審が走った")
    doc = raise_doc(doc, units=units, run=run)
    write(b.dir, doc)
    why = skip_reason(doc)
    if why and b.node_state(DELTA_NODE) == "pending":
        b.skip(DELTA_NODE, why)
    return doc


NODE_FIELDS = ("ok", "why", "depth", "unit_depths", "skip", "lines", "depth_file")
ATS = ("decide", "raise")


def _out(doc: dict, *, ok: bool, why: str, path) -> dict:
    return {"ok": ok, "why": why, "depth": run_depth(doc), "unit_depths": unit_map(doc), "skip": skip_reason(doc),
            "lines": lines(doc), "depth_file": str(path or "")}


def node(board_dir, at: str, *, open_units: str = "", tdd_suite: str = "", replanned: bool = False,
         rejudged: bool = False) -> dict:
    if at not in ATS:
        raise ValueError(f"at={at!r} は知らない値（{' / '.join(ATS)}）")
    import entry
    try:
        b = entry.open_board(pathlib.Path(board_dir), allow_halted=True)
        doc = decide(b, open_units, tdd_suite=tdd_suite) if at == "decide" else raise_(b, replanned=replanned, rejudged=rejudged)
    except Exception as e:   # 節を落とさず標準へ倒す（理由は why に 1 行）
        return _out({"units": {}}, ok=False, why=f"盤面を読めないので標準にした（{type(e).__name__}: {' '.join(str(e).split())[:300]}）",
                    path=None)
    return _out(doc, ok=True, why="", path=pathlib.Path(board_dir) / FILE)
