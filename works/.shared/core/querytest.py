"""判定役の class_query の問いを、例で試してから受ける（Semgrep の ruleid/ok と同じ形）。works だけの検査（裁定 TA25）。

写しの class_query は additionalProperties: false で例の欄を持てないので、例は役の型（accept.role_schema）にだけ足し、
受け付けは盤面へ渡す前に例を外して query-examples.json に置く。項目 35: 部分一致の defects の問いが、直した後の正しい行も
数えたまま判定の基準になり、修正役が何をしても件数が減らなかった。

- NODES・EXAMPLE_FIELDS・with_examples(schema): 例を持てる節と、例の欄（hits＝当たるべき 1 行・misses＝当たってはならない 1 行）と、units[].class_query に
  それを足した役の型
- run_examples(how, lines): 例を 1 行 1 ファイルに書き、数える本体と同じ旗（engine の count_argv）の git grep --no-index で当てる
- problems(units, is_open): 今の周に直す単位の例の誤り（当たらない hits・当たる misses・defects の misses の欠け・走らない問い）
- split(reply): 例を外した返答の写しと {単位の key: {hits, misses}}
- save(board, examples, replace)・restore(doc, board): 盤面の query-examples.json に置く・判定の写しの class_query に戻す
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

EXAMPLES_FILE = "query-examples.json"
NODES = ("p2.diagnose", "p2.rejudge", "p2.rejudge_third")   # 役の型に例の欄を足し、受け付けが例を外して試す節（blk-judge・blk-rejudge）
EXAMPLE_FIELDS = ("hits", "misses")
TIMEOUT = 60
_LINES = {"type": "array", "maxItems": 20, "items": _util._TEXT}
EXAMPLES_SCHEMA = {
    "hits": {**_LINES, "note": "この問いが当たるべき 1 行（今の版に在る欠陥・母数の行の写し）"},
    "misses": {**_LINES, "note": "この問いが当たってはならない 1 行。counts が defects なら、正しく直した後の行を 1 つは入れる"},
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


def problems(units, is_open) -> list:
    """今の周に直す単位（is_open）のうち、class_query に例を持つ物の誤りの文。例の無い単位は見ない"""
    errs = []
    for u in units or []:
        cq = u.get("class_query") if isinstance(u, dict) else None
        if not is_open(u) or not isinstance(cq, dict) or not any(k in cq for k in EXAMPLE_FIELDS):
            continue
        key = str(u.get("key"))
        bad = validate_schema({k: cq[k] for k in EXAMPLE_FIELDS if k in cq},
                              {"type": "object", "properties": EXAMPLES_SCHEMA}, "class_query")
        if bad:
            errs.append(f"{key}: class_query の例の型が合わない（{'; '.join(bad[:3])}）")
            continue
        hits, misses = list(cq.get("hits") or []), list(cq.get("misses") or [])
        if cq.get("counts") == "defects" and not misses:
            errs.append(f"{key}: 欠陥の形を数える問い（counts: defects）に misses が無い——正しく直した後の行を misses に 1 つは書け"
                        "（直した後も当たる問いは、修正が何をしても件数が減らない）")
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


def split(reply: dict) -> tuple:
    """（例を外した返答の写し, {単位の key: {hits, misses}}）。例を持つ単位だけを載せる"""
    out = copy.deepcopy(reply)
    examples = {}
    for u in out.get("units") or [] if isinstance(out, dict) else []:
        cq = u.get("class_query") if isinstance(u, dict) else None
        if isinstance(cq, dict) and any(k in cq for k in EXAMPLE_FIELDS):
            examples[str(u.get("key"))] = {k: cq.pop(k) for k in EXAMPLE_FIELDS if k in cq}
    return out, examples


def save(board, examples: dict, *, replace: bool = False) -> pathlib.Path:
    """盤面の query-examples.json に足す（同じ key は新しい方）。replace は前の中身を捨てる（判定が単位を全部出し直した時）"""
    p = pathlib.Path(board) / EXAMPLES_FILE
    try:
        doc = json.loads(p.read_text(encoding="utf-8")) if p.is_file() and not replace else {}
    except (OSError, ValueError):
        doc = {}
    doc = {**(doc if isinstance(doc, dict) else {}), **examples}
    p.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return p


def restore(doc: dict, board) -> dict:
    """判定の写し doc の units[].class_query に、盤面の query-examples.json の例を戻す（doc を書き換えて返す）"""
    p = pathlib.Path(board) / EXAMPLES_FILE
    try:
        examples = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
    except (OSError, ValueError):
        examples = {}
    for u in doc.get("units") or []:
        ex = examples.get(str(u.get("key"))) if isinstance(examples, dict) else None
        if isinstance(ex, dict) and isinstance(u.get("class_query"), dict):
            u["class_query"].update({k: ex[k] for k in EXAMPLE_FIELDS if k in ex})
    return doc
