"""判定役の class_query の問いを、例で試してから受ける（Semgrep の ruleid/ok と同じ形）。works だけの検査（裁定 TA25）。

写しの class_query は additionalProperties: false で例の欄を持てないので、例は役の型（accept.role_schema）にだけ足し、
受け付けは盤面へ渡す前に例を外して query-examples.json に置く。項目 35: 部分一致の defects の問いが、直した後の正しい行も
数えたまま判定の基準になり、修正役が何をしても件数が減らなかった。

- NODES・EXAMPLE_FIELDS・REASON_FIELDS・with_examples(schema): 例を持てる節と、例の欄（hits＝当たるべき 1 行・misses＝当たってはならない
  1 行）と理由の欄（examples_unavailable＝例を出せない理由・misses_omitted_why＝defects の misses を書けない理由）と、
  units[].class_query にそれを足した役の型
- run_examples(how, lines): 例を 1 行 1 ファイルに書き、数える本体と同じ旗（engine の count_argv）の git grep --no-index で当てる
- judge_hits(units): 食い違いの申し出の correct_lines に判定者の問いを当てる口（conflict.problems の try_query）
- problems(units, is_open): 今の周に直す単位の例の誤り（当たらない hits・当たる misses・理由の無い defects の misses の欠け・
  例を出せない理由と例の同時の記入・走らない問い）。例の無い単位は拒まない
- unproven(units, is_open)・unproven_lines(board): 例の無い開いた単位（「例で証明できない」印）と、最後の関所と報告に載せるその行
- split(reply, is_open): 例と理由を外した返答の写しと {単位の key: {例・理由・unproven}}
- save(board, examples, replace)・restore(doc, board): 盤面の query-examples.json に置く・判定の写しの class_query に戻す（印は戻さない）
- save_closure(b, rows)・closure_lines(b): 修正の受け付けが問いを数え直した単位ごとの閉鎖の表を置く・最後の関所と報告の行
  （当たりが減っていない単位は stuck_only で別の見出し STUCK_HEAD の節に出す）
"""
import copy
import json
import pathlib
import sys
import tempfile

sys.dont_write_bytecode = True

_GL = pathlib.Path(__file__).resolve().parent / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

import engine.util as _util  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
import scopes  # noqa: E402

EXAMPLES_FILE = "query-examples.json"
NODES = ("p2.diagnose", "p2.rejudge", "p2.rejudge_third")   # 役の型に例の欄を足し、受け付けが例を外して試す節（blk-judge・blk-rejudge）
EXAMPLE_FIELDS = ("hits", "misses")
UNAVAILABLE, MISSES_OMITTED = "examples_unavailable", "misses_omitted_why"
REASON_FIELDS = (UNAVAILABLE, MISSES_OMITTED)   # 例を出せない・misses を書けない理由（例の欄と同じく盤面へ渡す前に外す）
FIELDS = EXAMPLE_FIELDS + REASON_FIELDS
MIN_WHY = 10
NO_EXAMPLES = "例が無い（当たるべき行・当たってはならない行で問いを試していない）"
UNPROVEN = "unproven"                          # query-examples.json の行の印（例で証明できない理由）
UNPROVEN_HEAD = "例で証明できない判定の問い"      # 最後の関所の文の節の見出し・報告の行の頭
CLOSURE_FILE = "fix-unit-rows.json"              # 修正の受け付けが問いを数え直した単位ごとの表（盤面の置き場。周の番号つき）
# 最後の関所の文の節の見出し・報告の行の頭。主語は平易に、記録の語（閉鎖の数え直し）は括弧に回す
CLOSURE_HEAD = "機械が判定の問いで数え直すと、直したという申告と合わない・まだ閉じていない・問いの外に直しを並べた単位（閉鎖の数え直し）"
STUCK_HEAD = "直したのに、機械が判定の問いで数えた欠陥の数が 1 件も減っていない単位"   # CLOSURE_HEAD の節から分けて先に出す
TIMEOUT = 60
_LINES = {"type": "array", "maxItems": 20, "items": _util._TEXT}
_WHY = {"type": "string", "minLength": MIN_WHY}
EXAMPLES_SCHEMA = {
    "hits": {**_LINES, "note": "この問いが当たるべき 1 行（今の版に在る欠陥・母数の行の写し）"},
    "misses": {**_LINES, "note": "この問いが当たってはならない 1 行。counts が defects なら、正しく直した後の行を 1 つは入れる"},
    UNAVAILABLE: {**_WHY, "note": "例を 1 行も出せない理由（hits・misses と一緒に書かない）。例の無い単位は「例で証明できない」印で人に見せる"},
    MISSES_OMITTED: {**_WHY, "note": "counts が defects なのに misses を書けない理由（在るべき物が無い型など、直した後を 1 行に書けない時）"},
}


def with_examples(schema: dict) -> dict:
    """units[].class_query を持つ節の型に例の欄を足した写し（持たなければそのまま）"""
    cq = (((schema.get("properties") or {}).get("units") or {}).get("items") or {}).get("properties", {}).get("class_query")
    if not isinstance(cq, dict) or "properties" not in cq:
        return schema
    out = copy.deepcopy(schema)
    out["properties"]["units"]["items"]["properties"]["class_query"]["properties"].update(copy.deepcopy(EXAMPLES_SCHEMA))
    return out


def _flags(how) -> tuple:
    """count_argv が組む argv の旗（git grep から -- の前まで）を、例を当てる形にする——（旗, ""）か（None, 理由）。
    未追跡の旗は落とし、ファイルの本数（-l）は行の数（-c）に替える（1 例 1 ファイルなので、どちらでも当たったかが分かる）"""
    argv, why = _util.count_argv(how)
    if why:
        return None, why
    flags = argv[2:argv.index("--")]
    out = []
    for i, f in enumerate(flags):
        if i and flags[i - 1] == "-e":   # 検索語はそのまま（旗と同じ字でも）
            out.append(f)
        elif f != "--untracked":
            out.append("-c" if f == "-l" else f)
    return out, ""


def run_examples(how, lines) -> tuple:
    """lines の行のうち how が当たる物の番号の集合 ——（集合, ""）か（None, 理由）。読めなかった問いを当たらないにしない"""
    flags, why = _flags(how)
    if why:
        return None, why
    if not lines:
        return set(), ""
    with tempfile.TemporaryDirectory() as d:
        names = []
        for i, line in enumerate(lines):
            (pathlib.Path(d) / str(i)).write_text(line + "\n", encoding="utf-8")
            names.append(str(i))
        _, out, why = _util._grep_run(["git", "grep", "--no-index", *flags, "--", *names], d, TIMEOUT, _util.COUNT_CAP)
    if why:
        return None, why
    got = set()
    for row in out.decode("utf-8", "replace").splitlines():
        name, _, n = row.rpartition(":")
        if not (name.isdigit() and n.strip().isdigit()):
            return None, f"git grep の出力が読めない（{row[:80]!r}）"
        if int(n) > 0:
            got.add(int(name))
    return got, ""


def judge_hits(units):
    """食い違いの申し出の確かめ（conflict.problems）の try_query: which_is_right: query の申し出の correct_lines に、判定者の
    class_query の how を run_examples で当てる（どれかに当たれば空。問いの無い単位は見ない）。修正役の受け付けと TDD の輪が使う"""
    hows = {u.get("key"): u["class_query"].get("how") for u in units
            if isinstance(u, dict) and isinstance(u.get("class_query"), dict)}

    def hits(key, lines):
        how = hows.get(key)
        if not how:
            return ""
        got, why = run_examples(how, lines)
        if why:
            return f"判定者の問いを correct_lines に当てられない（{why}）"
        return "" if got else "判定者の問いは correct_lines のどの行にも当たらない（問いが正しい形に当たる、の証拠にならない）"
    return hits


def unproven(units, is_open) -> list:
    """今の周に直す単位（is_open）のうち、class_query に例（hits・misses）の無い物 [{key, why}]。拒まずに「例で証明できない」
    印として人に見せる。why は examples_unavailable の理由か NO_EXAMPLES"""
    out = []
    for u in units or []:
        cq = u.get("class_query") if isinstance(u, dict) else None
        if is_open(u) and isinstance(cq, dict) and not any(k in cq for k in EXAMPLE_FIELDS):
            why = cq.get(UNAVAILABLE)
            out.append({"key": str(u.get("key")), "why": why if isinstance(why, str) and why.strip() else NO_EXAMPLES})
    return out


def problems(units, is_open) -> list:
    """今の周に直す単位（is_open）のうち、class_query に例か理由の欄を持つ物の誤りの文。例の無い単位は拒まない（unproven の印）"""
    errs = []
    for u in units or []:
        cq = u.get("class_query") if isinstance(u, dict) else None
        if not is_open(u) or not isinstance(cq, dict) or not any(k in cq for k in FIELDS):
            continue
        key = str(u.get("key"))
        bad = validate_schema({k: cq[k] for k in FIELDS if k in cq},
                              {"type": "object", "properties": EXAMPLES_SCHEMA}, "class_query")
        if bad:
            errs.append(f"{key}: class_query の例の型が合わない（{'; '.join(bad[:3])}）")
            continue
        if UNAVAILABLE in cq:
            if any(k in cq for k in EXAMPLE_FIELDS):
                errs.append(f"{key}: class_query に {UNAVAILABLE}（例を出せない理由）と例（hits・misses）を一緒に書いた——"
                            "例を出せるなら理由を消し、出せないなら例を消せ")
            continue
        hits, misses = list(cq.get("hits") or []), list(cq.get("misses") or [])
        if cq.get("counts") == "defects" and not misses and MISSES_OMITTED not in cq:
            errs.append(f"{key}: 欠陥の形を数える問い（counts: defects）に misses が無い——正しく直した後の行を misses に 1 つは書け"
                        f"（直した後も当たる問いは、修正が何をしても件数が減らない。直した後を 1 行に書けないなら {MISSES_OMITTED} に理由）")
        got, why = run_examples(cq.get("how"), hits + misses)
        if why:
            errs.append(f"{key}: class_query の例を当てられない（{why}）")
            continue
        missed = [h for i, h in enumerate(hits) if i not in got]
        struck = [m for i, m in enumerate(misses) if len(hits) + i in got]
        if missed:
            errs.append(f"{key}: class_query の how が hits に当たらない: " + " / ".join(repr(h) for h in missed))
        if struck:
            what = "欠陥の形を数える問い（counts: defects）が、直した後の正しい形にも当たる" if cq.get("counts") == "defects" \
                else "class_query の how が misses に当たる"
            errs.append(f"{key}: {what}: " + " / ".join(repr(m) for m in struck) + "——当たらない形（錨・完全一致など）に問いを直せ")
    return errs


def split(reply: dict, is_open=None) -> tuple:
    """（例と理由の欄を外した返答の写し, {単位の key: {hits, misses, examples_unavailable, misses_omitted_why, unproven}}）。
    例か理由を持つ単位と、is_open が渡れば例の無い開いた単位（unproven: 印の理由）を載せる"""
    out = copy.deepcopy(reply)
    units = out.get("units") or [] if isinstance(out, dict) else []
    marks = {r["key"]: r["why"] for r in unproven(units, is_open)} if is_open else {}
    examples = {}
    for u in units:
        cq = u.get("class_query") if isinstance(u, dict) else None
        if isinstance(cq, dict) and any(k in cq for k in FIELDS):
            examples[str(u.get("key"))] = {k: cq.pop(k) for k in FIELDS if k in cq}
    for key, why in marks.items():
        examples.setdefault(key, {})[UNPROVEN] = why
    return out, examples


def save(board, examples: dict, *, replace: bool = False) -> pathlib.Path:
    """盤面の query-examples.json に足す（同じ key は新しい方）。replace は前の中身を捨てる（判定が単位を全部出し直した時）"""
    p = pathlib.Path(board) / EXAMPLES_FILE
    doc = {**({} if replace else _saved(board)), **examples}
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return p


def _saved(board) -> dict:
    p = pathlib.Path(board) / EXAMPLES_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        doc = {}
    return doc if isinstance(doc, dict) else {}


def restore(doc: dict, board) -> dict:
    """判定の写し doc の units[].class_query に、盤面の query-examples.json の例と理由を戻す（doc を書き換えて返す。
    印 unproven は戻さない）"""
    examples = _saved(board)
    for u in doc.get("units") or []:
        ex = examples.get(str(u.get("key")))
        if isinstance(ex, dict) and isinstance(u.get("class_query"), dict):
            u["class_query"].update({k: ex[k] for k in FIELDS if k in ex})
    return doc


def unproven_lines(board) -> list:
    """最後の関所と報告に載せる「例で証明できない」単位の行（1 件 1 行。盤面の query-examples.json の印 unproven から）"""
    return [f"{key}: {ex[UNPROVEN]}" for key, ex in _saved(board).items()
            if isinstance(ex, dict) and isinstance(ex.get(UNPROVEN), str)]


def save_closure(b, rows: list) -> pathlib.Path:
    """単位ごとの閉鎖の表 {round, rows: [{unit_key, how_from, counts, total, after, claimed, covered, out_of_query, bound, closed,
    discrepancies}]} を盤面の置き場に置く（covered は申告の site が在る問いの当たりのファイルの件数、out_of_query は当たりの外の
    site のパス、bound は site を当たりのファイルに結べたか。結べなければ covered は claimed と同じ）。（受けた返答の分で上書きする。読む側は今の周の表だけを読む）。
    置き場は盤面の今の scope の根（b.scope_root。修正のブロックの include ごとに分かれ、2 回目の修正の段が 1 回目の表を上書きしない）"""
    p = pathlib.Path(b.scope_root) / CLOSURE_FILE
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps({"round": b.round, "rows": rows}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(p)
    return p


def _stuck(r: dict) -> bool:
    """欠陥の形を数える問い（defects）で、修正前に当たりが在り、修正後に 1 件も減っていない行（population は直しても減らない母集団）"""
    total, after = r.get("total"), r.get("after")
    return (r.get("counts") == "defects" and isinstance(total, int) and isinstance(after, int) and total > 0
            and after >= total)


def closure_rows(b) -> list:
    """今の周の閉鎖の表の行（表が無い・読めない・前の周の物なら空）。表は include ごとに scope の根に在るので、盤面の根と
    今の周に登録した scope の根（scopes.scope_roots）のうち最後に登録した物から読む（2 回目の修正の段の表が在ればそれ）"""
    roots = [r for r in scopes.scope_roots(b) if (r / CLOSURE_FILE).is_file()]
    if not roots:
        return []
    try:
        doc = json.loads((roots[-1] / CLOSURE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(doc, dict) or doc.get("round") != getattr(b, "round", None):
        return []
    return [r for r in doc.get("rows") or [] if isinstance(r, dict)]


def closure_lines(b, *, mismatched_only: bool = False, stuck_only: bool = False, claimed=()) -> list:
    """最後の関所と報告に載せる今の周の表の行（1 件 1 行）: 申告と数え直しが合わない単位と、数え直しで閉じていない単位と、
    問いの当たりの外に site を並べた単位（パスを並べる。合わないには数えない）。当たりが減っていない単位（_stuck）は
    見出し STUCK_HEAD の節に分けて stuck_only で返し、既定の列からは外す（二重に並べない）。
    mismatched_only は合わない単位だけ（前は返答全体を拒んだ形で、関所を開ける理由になる。減っていない単位も含む）。
    claimed は修正役が changes に載せた単位の key で、表に行が無い物は既定の列に名指しで足す（申告だけでは閉じたと言わない）"""
    rows = closure_rows(b)
    out = []
    for r in rows:
        bad = r.get("discrepancies") or []
        outside = r.get("out_of_query") or []
        if stuck_only:
            show = _stuck(r)
        elif mismatched_only:
            show = bool(bad)
        else:
            show = not _stuck(r) and bool(bad or r.get("closed") is False or outside)
        if show:
            state = "閉じた" if r.get("closed") else "閉じていない"
            out.append(f"{r.get('unit_key')}: {state}（{r.get('counts')}・修正前 {r.get('total')}・修正後 {r.get('after')}・"
                       f"申告の site {r.get('claimed')}" + (f"・site が覆う当たり {r['covered']}" if r.get("bound") else "") +
                       f"・問い {r.get('how_from')}）" + (f"——合わない: {' / '.join(bad)}" if bad else "") +
                       (f"——問いの外の site {len(outside)} 件: {', '.join(outside)}" if outside else ""))
    if not (stuck_only or mismatched_only):
        seen = {r.get("unit_key") for r in rows}
        out += [f"{k}: 閉鎖の表に行が無い（修正役の申告だけで、機械の数え直しで閉じたと確かめていない）"
                for k in claimed if k not in seen]
    return out
