"""構造のブロックの出口の控え（盤面の根の structure-state.json）。線の構造の境の節が 1 回書き、修正案の指示書の頭・報告・最後の
関所の 3 か所がこの 1 つのファイルだけを読む（読み直しを 3 か所に割らない）。Archon を知らない関数だけを出す。

控えの形: {status: ok|failed, reason, design_file, wall_s}。failed は「構造の目の行なしで計画した」周（構造のブロックが走らなかった・
落ちた・status: failed で抜けた・設計の行のファイルが読めない）で、reason に理由の 1 文。

- write(board_dir, …): 控えを書く（書けなければ OSError。受ける側が理由にして返す）
- read(board_dir):     控え（無い・読めない・形が違うなら None。拒まない）
- rows(design_file):   設計の行（design.jsonl の JSON のオブジェクトの並び）。読めない・行が壊れていれば ValueError
- note(state):         落ちた周の 1 文（ok の周・控えが無い周は ""）
- plan_section(board_dir): 修正案の指示書の頭に貼る節（行が在れば行と守り方の指示、落ちた周は note、控えが無い・行が無い周は ""）
- report_lines(board_dir): 報告の「構造の目」の節の行（判定の行か落ちの印と、増えた時間。控えが無い run は []）
"""
import json
import pathlib

STATE_FILE = "structure-state.json"
MISSING = "構造の目の行なしで計画した"
PLAN_HEAD = "## 構造の目の行（設計を知らない次の人が足す形が増えないかを別の目が見た判定。機械が貼った）"
PLAN_ASK = "計画は各行の避け方（chosen）を守るか、守らないならその単位の計画に理由を書け。"


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
        return []
    wall = f"構造のブロックで増えた時間: {state.get('wall_s', 0)} 秒"
    if missing:
        return [missing, wall]
    return [*(_row_line(r) for r in got), wall] if got else ["構造の目の行は無い", wall]
