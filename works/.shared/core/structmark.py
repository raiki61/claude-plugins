"""構造のブロックの出口の控え（盤面の根の structure-state.json）。線の構造の境の節が 1 回書き、修正案の指示書の頭・報告・最後の
関所の 3 か所がこの 1 つのファイルだけを読む（読み直しを 3 か所に割らない）。Archon を知らない関数だけを出す。

控えの形: {status: ok|failed, reason, design_file, wall_s}。failed は「構造の目の行なしで計画した」周（構造のブロックが走らなかった・
落ちた・status: failed で抜けた・設計の行のファイルが読めない）で、reason に理由の 1 文。

- write(board_dir, …): 控えを書く（書けなければ OSError。受ける側が理由にして返す）
- read(board_dir):     控え（無い・読めない・形が違うなら None。拒まない）
- rows(design_file):   設計の行（design.jsonl の JSON のオブジェクトの並び）。読めない・行が壊れていれば ValueError
- note(state):         落ちた周の 1 文（ok の周・控えが無い周は ""）
- plan_section_file(state_file): 修正案の指示書の頭に貼る節。blk-plan の明示の入力 structure_state_file（境の節の出口 state_file）
  だけを読む（行が在れば行と守り方の指示、落ちた周は note、入力が空・控えが無い・行が無い周は ""）
- with_kept(schema)・split_kept(reply)・check_kept(state_file, kept)・save_kept(board_dir, round, kept): 修正案の返答の欄
  structure_kept（避け方の在る行ごとに守ったか・守らない理由）の型・外し方・機械の確かめ・控え（盤面の根の structure-kept.json）
- report_lines(board_dir): 報告の「構造の目」の節の行（判定の行か落ちの印と、計画が守ったかと、増えた時間。控えが無い run は []）
- kept_line(board_dir): 計画が避け方を守ったかの 1 行（最後の関所。避け方の行が無い run は ""）
"""
import copy
import json
import pathlib

STATE_FILE = "structure-state.json"
KEPT_FILE = "structure-kept.json"
KEPT_FIELD = "structure_kept"
PLAN_NODE = "p2.fix_plan"      # 欄 structure_kept を持つ役の節（修正案）
MISSING = "構造の目の行なしで計画した"
PLAN_HEAD = "## 構造の目の行（設計を知らない次の人が足す形が増えないかを別の目が見た判定。機械が貼った）"
PLAN_ASK = ("計画は各行の避け方（chosen）を守るか、守らないならその単位の計画に理由を書け。避け方の在る行ごとに、返答の最上位の欄 "
            "structure_kept に {unit_id, kept, why} を 1 つずつ書け（kept は守ったか。守らないなら why に理由。受け付けが行と突き合わせる）。")
KEPT_SCHEMA = {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": ["unit_id", "kept", "why"],
                                          "properties": {"unit_id": {"type": "string", "minLength": 1},
                                                         "kept": {"type": "boolean"}, "why": {"type": "string"}}}}


def write(board_dir, *, status: str, reason: str, design_file: str, wall_s) -> pathlib.Path:
    path = pathlib.Path(board_dir) / STATE_FILE
    doc = {"status": status, "reason": reason, "design_file": design_file, "wall_s": wall_s}
    path.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def read(board_dir) -> dict | None:
    return read_file(pathlib.Path(board_dir) / STATE_FILE)


def read_file(path) -> dict | None:
    if not path:
        return None
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
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


def _state_rows(board_dir=None, state_file=None):
    """(控え, 行, 落ちの 1 文)。控えが無ければ (None, [], "")。行が読めない周は落ちとして 1 文を返す。state_file を渡せばそれだけを読む"""
    state = read_file(state_file) if state_file is not None else read(board_dir)
    if state is None:
        return None, [], ""
    if state["status"] == "failed":
        return state, [], note(state)
    try:
        return state, rows(state.get("design_file") or ""), ""
    except ValueError as e:
        return state, [], note({"status": "failed", "reason": str(e)})


def plan_section_file(state_file) -> str:
    state, got, missing = _state_rows(state_file=state_file or "")
    if missing:
        return f"{PLAN_HEAD}\n\n{missing}"
    if not got:
        return ""
    return f"{PLAN_HEAD}\n\n{PLAN_ASK}\n\n" + "\n".join(f"- {_row_line(r)}" for r in got)


def _chosen_units(got) -> list:
    return [str(r.get("unit_id", "")) for r in got if r.get("chosen")]


def with_kept(schema: dict) -> dict:
    """修正案の役の型に任意の欄 structure_kept を足した写し（写しの型は欄を持たない。受け付けが外してから盤面へ渡す）"""
    out = copy.deepcopy(schema)
    out.setdefault("properties", {})[KEPT_FIELD] = copy.deepcopy(KEPT_SCHEMA)
    return out


def split_kept(reply) -> tuple:
    """(欄 structure_kept を外した返答の写し, 欄の値か None)"""
    out = copy.deepcopy(reply)
    kept = out.pop(KEPT_FIELD, None) if isinstance(out, dict) else None
    return out, kept


def check_kept(state_file, kept) -> str:
    """指示書に貼った行のうち避け方（chosen）の在る単位ごとに、structure_kept に 1 つずつ在るか・守らない行に理由が在るか。
    拒否の理由の 1 文（合えば ""）。行の無い周・入力が空の周は何も求めない"""
    _, got, missing = _state_rows(state_file=state_file or "")
    need = [] if missing else _chosen_units(got)
    rows = kept if isinstance(kept, list) else []
    if not need:
        return ""
    ids = [str(k.get("unit_id", "")) for k in rows if isinstance(k, dict)]
    lack = [u for u in need if u not in ids]
    extra = sorted({u for u in ids if u not in need})
    dup = sorted({u for u in ids if ids.count(u) > 1})
    bare = [str(k.get("unit_id", "")) for k in rows if isinstance(k, dict) and k.get("kept") is False
            and not str(k.get("why") or "").strip()]
    out = []
    if lack:
        out.append(f"避け方の在る構造の目の行に、structure_kept の行が無い: {', '.join(lack)}")
    if extra:
        out.append(f"structure_kept に、避け方の在る行に無い unit_id が在る: {', '.join(extra)}")
    if dup:
        out.append(f"structure_kept に同じ unit_id が 2 つ以上在る: {', '.join(dup)}")
    if bare:
        out.append(f"structure_kept の守らない行（kept: false）に理由（why）が無い: {', '.join(bare)}")
    return "。".join(out) + ("——構造の目の行ごとに守ったかを 1 つずつ書いて出し直せ" if out else "")


def save_kept(board_dir, rnd: int, kept) -> None:
    """控えを周の分で置き換える。欄が無い返答は書かない"""
    if kept is None:
        return
    p = pathlib.Path(board_dir) / KEPT_FILE
    p.write_text(json.dumps({"round": rnd, "kept": kept}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")


def kept_line(board_dir) -> str:
    _, got, missing = _state_rows(board_dir)
    need = [] if missing else _chosen_units(got)
    if not need:
        return ""
    try:
        doc = json.loads((pathlib.Path(board_dir) / KEPT_FILE).read_text(encoding="utf-8"))
        rows = [k for k in doc.get("kept") or [] if isinstance(k, dict)]
    except (OSError, UnicodeDecodeError, ValueError, AttributeError):
        return f"計画が構造の目の避け方を守ったか: 返答に無い（避け方の在る行 {len(need)} 件）"
    no = [k for k in rows if k.get("kept") is False]
    text = f"計画が構造の目の避け方を守ったか: 守った {len(rows) - len(no)} 件・守らない {len(no)} 件"
    return text + ("（" + "／".join(f"{k.get('unit_id')}: {k.get('why')}" for k in no) + "）" if no else "")


def report_lines(board_dir) -> list:
    state, got, missing = _state_rows(board_dir)
    if state is None:
        return []
    wall = f"構造のブロックで増えた時間: {state.get('wall_s', 0)} 秒"
    if missing:
        return [missing, wall]
    kept = kept_line(board_dir)
    return [*(_row_line(r) for r in got), *([kept] if kept else []), wall] if got else ["構造の目の行は無い", wall]
