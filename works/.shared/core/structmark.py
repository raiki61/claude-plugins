"""構造のブロックの出口の控え（盤面の根の structure-state.json）。線の構造の境の節が 1 回書き、修正案の指示書の頭・報告・最後の
関所の 3 か所がこの 1 つのファイルだけを読む（読み直しを 3 か所に割らない）。Archon を知らない関数だけを出す。

控えの形: {status: ok|failed, reason, design_file, wall_s}。failed は「構造の目の行なしで計画した」周（構造のブロックが走らなかった・
落ちた・status: failed で抜けた・設計の行のファイルが読めない）で、reason に理由の 1 文。

- write(board_dir, …): 控えを書く（書けなければ OSError。受ける側が理由にして返す）
- read(board_dir):     控え（無い・読めない・形が違うなら None。拒まない）
- rows(design_file):   設計の行（design.jsonl の JSON のオブジェクトの並び）。読めない・行が壊れていれば ValueError
- note(state):         落ちた周の 1 文（ok の周・控えが無い周は ""）
- plan_section(board_dir): 修正案の指示書の頭に貼る節（行が在れば行と守り方の指示、落ちた周は note、控えが無い・行が無い周は ""）
- dirty(board_dir):    汚れると見た行（単位の id → 行）。控えが無い・落ちた周・行が読めない周は {}（修正案の欄 structure の要る行）
- report_lines(board_dir): 報告の「構造の目」の節の行（判定の行か落ちの印と、増えた時間と、直しの後の実測の行。控えが無い run は []）

直しの後の実測の控え（盤面の根の structure-after.json。計画 2026-10-09-clean-whole の Task 2.5）: 線の直しの後の境の節が 1 回書き、
報告・最後の関所・独立の目の頭・結末の残りの数え（report.rest_outside_validator）がこの 1 つのファイルだけを読む。
形: {status: ok|failed, reason, after: <構造のブロックの after.json の中身か {}>, deviations: [修正案の外れの訳]}。
- write_after(board_dir, …)・read_after(board_dir): 控えを書く・読む（無い・読めない・形が違うなら None）
- after_rows(board_dir): 結末を fixed にしない残りの行 [{where, text}]（柵の表を持つ対象で、住処の外の知る場所が増えた所。
  text は「考えの住処: 」で始まる。表の無い対象・控えが無い run は []）
- after_lines(board_dir): 最後の関所と報告に並べる行（実測の数・増えた所・外れの訳。控えが無い run は []）
- after_counts(board_dir): 独立の目の頭に渡す数の 1 文（控えが無い run は ""）
"""
import json
import pathlib

import concepthome
import planmarks   # 修正案の外れの訳の文の住処（answer_line）

STATE_FILE = "structure-state.json"
AFTER_FILE = "structure-after.json"
MISSING = "構造の目の行なしで計画した"
PLAN_HEAD = "## 構造の目の行（設計を知らない次の人が足す形が増えないかを別の目が見た判定。機械が貼った）"
DIRTY = "汚れる"           # 設計の行の verdict の語（約束は構造のブロックの設計の行の型の enum）
ROUTE_UP = "人に上げる"    # 設計の行の route の語（同じ約束。関所の項目にする行。gatemarks が読む）
PLAN_ASK = ("汚れると見た行の単位を持つ項目は、行ごとに避け方（chosen）に従うか、従わない訳を、項目の works の欄 structure に書け"
            "（{row: <行の頭の単位の id>, follows: true} か {row, deviation: <訳>}。欠けは受け付けが拒む）。")


def write(board_dir, *, status: str, reason: str, design_file: str, wall_s) -> pathlib.Path:
    path = pathlib.Path(board_dir) / STATE_FILE
    doc = {"status": status, "reason": reason, "design_file": design_file, "wall_s": wall_s}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def read(board_dir) -> dict | None:
    try:
        doc = json.loads((pathlib.Path(board_dir) / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    return doc if isinstance(doc, dict) and doc.get("status") in ("ok", "failed") else None


def rows(design_file: str) -> list:
    if not design_file:
        raise ValueError("設計の行のファイルの名が空")
    try:
        text = pathlib.Path(design_file).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise ValueError(f"設計の行のファイルが読めない: {e}") from None
    out = []
    for i, line in enumerate(text.splitlines(), 1):
        try:
            row = json.loads(line)
        except ValueError as e:
            raise ValueError(f"設計の行 {i} が JSON でない: {e}") from None
        if not isinstance(row, dict):
            raise ValueError(f"設計の行 {i} が JSON のオブジェクトでない")
        out.append(row)
    return out


def note(state: dict | None) -> str:
    if not state or state.get("status") != "failed":
        return ""
    return f"{MISSING}（理由: {state.get('reason') or '理由の記録が無い'}）"


def _row_line(r: dict) -> str:
    faces = "・".join(str(f) for f in r.get("faces") or []) or "なし"
    evidence = "・".join(str(e) for e in r.get("evidence") or []) or "なし"
    text = f"{r.get('unit_id', '')}: {r.get('verdict', '')}（形 {faces}・根拠 {evidence}）——{r.get('reason', '')}"
    if r.get("chosen"):
        text += f"。避け方: {r['chosen']}"
        if r.get("chosen_reason"):
            text += f"（{r['chosen_reason']}）"
    return text


def _state_rows(board_dir):
    """(控え, 行, 落ちの 1 文)。控えが無ければ (None, [], "")。行が読めない周は落ちとして 1 文を返す"""
    state = read(board_dir)
    if state is None:
        return None, [], ""
    if state["status"] == "failed":
        return state, [], note(state)
    try:
        return state, rows(state.get("design_file") or ""), ""
    except ValueError as e:
        return state, [], note({"status": "failed", "reason": str(e)})


def dirty(board_dir) -> dict:
    """{単位の id: 汚れると見た設計の行}。控えが無い・落ちた周・行が読めない周は {}（行なしで計画した周は欄を求めない）"""
    _, got, _ = _state_rows(board_dir)
    return {r["unit_id"]: r for r in got if r.get("verdict") == DIRTY and isinstance(r.get("unit_id"), str)}


def plan_section(board_dir) -> str:
    state, got, missing = _state_rows(board_dir)
    if missing:
        return f"{PLAN_HEAD}\n\n{missing}"
    if not got:
        return ""
    return f"{PLAN_HEAD}\n\n{PLAN_ASK}\n\n" + "\n".join(f"- {_row_line(r)}" for r in got)


def report_lines(board_dir) -> list:
    state, got, missing = _state_rows(board_dir)
    if state is None:
        return after_lines(board_dir)
    wall = f"構造のブロックで増えた時間: {state.get('wall_s', 0)} 秒"
    if missing:
        return [missing, wall, *after_lines(board_dir)]
    return [*(_row_line(r) for r in got), wall, *after_lines(board_dir)] if got else ["構造の目の行は無い", wall, *after_lines(board_dir)]


# ---------------------------------------------------------------- 直しの後の実測
def write_after(board_dir, *, status: str, reason: str, after: dict, deviations: list) -> pathlib.Path:
    path = pathlib.Path(board_dir) / AFTER_FILE
    doc = {"status": status, "reason": reason, "after": after, "deviations": deviations}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def read_after(board_dir) -> dict | None:
    try:
        doc = json.loads((pathlib.Path(board_dir) / AFTER_FILE).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(doc, dict) or doc.get("status") not in ("ok", "failed") or not isinstance(doc.get("after"), dict):
        return None
    return doc


def _fence_up(doc: dict) -> list:
    return [f for f in doc["after"].get("fence_up") or [] if isinstance(f, dict)]


def after_rows(board_dir) -> list:
    doc = read_after(board_dir)
    if doc is None or not doc["after"].get("tables"):
        return []
    return [{"where": str(f.get("path")),
             "text": f"{concepthome.PREFIX}{f.get('concept')}（{f.get('what')}）を知る場所が {f.get('path')} で増えた"
                     f"（{f.get('before')} → {f.get('after')} 行）。住処へ寄せるか、増やすなら考えの地図と柵の表を直す"}
            for f in _fence_up(doc)]


def after_counts(board_dir) -> str:
    doc = read_after(board_dir)
    if doc is None:
        return ""
    a = doc["after"]
    fence = f"柵の表 {len(a.get('tables') or [])} 本で住処の外の知る場所の増え {len(_fence_up(doc))} 件" if a.get("tables") \
        else "柵の表は無い（知る場所の増えは数えていない）"
    tail = "" if doc["status"] == "ok" else f"（実測の一部が落ちた: {doc.get('reason') or '理由の記録が無い'}）"
    return (f"直しの後の実測（直しの前の版と今の作業ツリーの差分。機械が測った）: 変わったファイル {len(a.get('changed') or [])} 本・"
            f"{fence}・新しい名 {len(a.get('new_names') or [])} 個・増えた写しの塊 {a.get('dup_blocks_added') or 0} 個・"
            f"構造の目の避け方と処方から外れた訳 {len(doc.get('deviations') or [])} 件{tail}")


def after_lines(board_dir) -> list:
    doc = read_after(board_dir)
    if doc is None:
        return []
    out = [after_counts(board_dir)]
    out += [f"  - {r['text']}" for r in after_rows(board_dir)]
    for n in doc["after"].get("new_names") or []:
        if isinstance(n, dict):
            out.append(f"  - 新しい名 {n.get('name')}（現れる所 {n.get('sites')} か所）")
    out += [f"  - 修正案の{planmarks.answer_line(d)}" for d in doc.get("deviations") or [] if isinstance(d, dict)]
    return out
