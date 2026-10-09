"""次の run への持ち越しの住処（考え carry-over。地図 docs/concepts.md）。層 L1: works のほかの物を import せず、標準ライブラリと
写しの engine の型検査（engine.schema。L0）だけを読む。Python 3.9 で動く。殻は `python3 -I carry.py carry-ci …` でファイルとして呼ぶ。

持つのは形だけ: 依頼の容器の欄の名・下書きの印・前の失敗の行・盤面の根のファイルの名・約束の JSON Schema（この置き場の
next-request.schema.json と prior-failures.schema.json）の読みと照らし・依頼の解き方・置き場への読み書き。何を運ぶか（残りの行・
答えの下書きの選び）は書き手の側（報告・関所の足し欄・目的の外の所見）が決める。書き手は書く前に Schema で照らし、読み手は
依頼を解く時に同じ Schema で前の失敗の行を照らす（欄の名の定数と Schema の欄が揃うことは tests/test_carry_home が縛る）。

依頼のファイルは findings の JSON の配列か、{"findings": [...], "pr": [<番号>…], "issue": [<番号>…], "answers": [...],
"prior_failures": [...]} の形。prior_failures は前の run で最後まで通らなかった物 [{where, text}]（前の run の報告が書く
next-request.json の欄。判定役と修正案の役の材料に貼る注意で、直す穴ではない）。
answers は依頼者が前の run の問いに答えた物 [{question, text, command?, output?}]（question は問いの key か出どころ。
command・output は人が手元で測った命令と出力で、両方か無し。前の run の報告が書いた答えの下書きの印 draft・source の在る行は、
人が見直していないので拒む。findings の行も同じ: 前の run の判定が目的の外とした所見を報告が下書きの印つきで運ぶ）。読み手
（入口・判定と前提の受け口）はここで解き、graphloops の規則（check_request・add_request・REQUEST_SCHEMA）に渡すのは
findings だけにする（容器の形を規則の側へ漏らさない）。

- parts(doc) -> {"findings": list, "pr": [int], "issue": [int], "answers": [dict], "prior_failures": [dict]}: 解けなければ ValueError（1 行）
- without_prior(doc) -> 依頼の object か None: 前の run の判断（欄 prior_failures）を外した写し。前の run の判断を知らない別の目
  （目的の役）に渡す形を機械が作る口。欄が無い・object でない（findings の配列の形）なら None（そのまま渡してよい）
- carry_ci(doc, ids) -> 依頼の object: run の後の CI が赤と言った試験の id を prior_failures の行（where CI_WHERE）として足す。
  重い試験は run の外の CI で回り、run の報告はその赤を知らないので、人（か回す役）が CI の赤の id を next-request.json に足す口。
  同じ行は 2 度足さない。id が無い・依頼の形が違えば ValueError（1 行）。殻からは `python3 -I carry.py carry-ci`
- is_draft(row)・draft(row, source, note="")・compose(findings, prior, drafts): 下書きの印の読みと付け方・次の依頼の下書きの中身
- row_key(row): 行の鍵（where と、text の最初の「（」までを空白を詰めて \\t でつないだ物。理由の尾だけ違う行を同じ物と見る）
- schema(name)・errors(doc, name): 約束の Schema（NEXT_SCHEMA・PRIOR_SCHEMA）と、それに照らした誤りの一覧
- save_next(board_dir, doc)・save_prior(board_dir, rows)・place_prior(board_dir, rows)・prior_section(board_dir, gap=ValueError):
  盤面の根に照らしてから書く口と、依頼の前の失敗を役の材料に貼る節（読めなければ呼び手が渡した例外の型 gap）
"""
import argparse
import functools
import json
import os
import pathlib
import sys

sys.dont_write_bytecode = True
_HERE = pathlib.Path(__file__).resolve().parent
if str(_HERE / "graphloops") not in sys.path:   # 殻は python3 -I で起こす（-I は自分の置き場を sys.path に足さない）
    sys.path.insert(0, str(_HERE / "graphloops"))   # 写しの engine（board と同じ足し方）

from engine.schema import validate_schema  # noqa: E402

# 依頼の容器の欄の名
FINDINGS, PR, ISSUE, ANSWERS, PRIOR = "findings", "pr", "issue", "answers", "prior_failures"
KEYS = (FINDINGS, PR, ISSUE, ANSWERS, PRIOR)
ANSWER_KEYS = ("question", "text", "command", "output")
DRAFT, SOURCE, NOTE = "draft", "source", "note"
DRAFT_KEYS = (DRAFT, SOURCE)   # 前の run の報告が next-request.json の answers・findings に置く下書きの印（人が見直して消すまで拒む）
PRIOR_KEYS = ("where", "text")   # prior_failures の行の欄（前の run の報告が next-request.json に書いた形）
CI_WHERE = "run の後の CI"   # carry_ci が足す prior_failures の行の where
CI_TEXT = ("試験 {id} が CI で赤だった（重い試験は run の外の CI で回る。前の run の直しがこの試験を赤にした見込み。"
           "同じ試験を赤にしない直しを出す）")

# 盤面の根のファイル
NEXT_REQUEST_FILE = "next-request.json"   # 次の run の依頼の下書き {findings, prior_failures, answers?}（依頼の型の object の形）
PRIOR_FAILURES_FILE = "prior-failures.json"   # この run で最後まで通らなかった受け付けと R2 の作り直しの理由 [{where, text}]
PRIOR_IN_FILE = "prior-failures-in.json"   # 依頼の prior_failures の写し [{where, text}]（place_prior。読むのは consumes で宣言した物）
PRIOR_HEAD = ("## 前の run で最後まで通らなかった物（機械が貼った。直す穴ではない——同じ所で落ちない返答を出すための注意。"
              "直す穴は依頼の findings だけ）")

# 約束（この置き場の JSON Schema）
NEXT_SCHEMA = "next-request.schema.json"
PRIOR_SCHEMA = "prior-failures.schema.json"


@functools.lru_cache(maxsize=None)
def _schema_text(name: str) -> str:
    return (_HERE / name).read_text(encoding="utf-8")


def schema(name: str) -> dict:
    """約束の Schema（NEXT_SCHEMA か PRIOR_SCHEMA）。呼ぶたびに新しい写し"""
    if name not in (NEXT_SCHEMA, PRIOR_SCHEMA):
        raise ValueError(f"持ち越しの約束でない Schema {name!r}")
    return json.loads(_schema_text(name))


def errors(doc, name: str) -> list:
    """doc を約束の Schema name に照らした誤りの一覧（空なら合う。写しの engine の型検査）"""
    return validate_schema(doc, schema(name))


def parts(doc) -> dict:
    if isinstance(doc, list):
        return {FINDINGS: doc, PR: [], ISSUE: [], ANSWERS: [], PRIOR: []}
    if not isinstance(doc, dict):
        raise ValueError(f"findings の配列か {{findings, pr, issue, answers, prior_failures}} の形でない（{type(doc).__name__}）")
    extra = sorted(set(doc) - set(KEYS))
    if extra:
        raise ValueError(f"知らない鍵 {extra}（使えるのは {list(KEYS)}）")
    findings = doc.get(FINDINGS, [])
    if not isinstance(findings, list):
        raise ValueError(f"findings が配列でない（{type(findings).__name__}）")
    for i, f in enumerate(findings):
        if is_draft(f):
            raise ValueError(f"findings[{i}] は前の run の報告が運んだ所見の下書き（draft・source の欄が在る。前の run の判定が目的の"
                             "外とした所見で、人が見直していない）——この run の目的に入れるなら draft と source の欄を消し、入れない"
                             "なら行を消す")
    out = {FINDINGS: findings}
    for key in (PR, ISSUE):
        nums = doc.get(key, [])
        if not isinstance(nums, list) or any(type(n) is not int or n <= 0 for n in nums):
            raise ValueError(f"{key} が正の整数の配列でない（{nums!r}）")
        out[key] = nums
    out[ANSWERS] = _answers(doc.get(ANSWERS, []))
    out[PRIOR] = _prior_failures(doc.get(PRIOR, []))
    return out


def without_prior(doc):
    """依頼 doc から前の run の判断（欄 prior_failures）を外した写し（ほかの欄は字のまま）。欄が無い・object でなければ None"""
    if isinstance(doc, dict) and PRIOR in doc:
        return {k: v for k, v in doc.items() if k != PRIOR}
    return None


def _prior_failures(rows) -> list:
    """依頼の prior_failures（前の run で最後まで通らなかった物。前の run の報告が書いた next-request.json の欄）を確かめて
    そのまま返す。行は {where, text} で、どちらも空でない文字列。知らない欄は拒む。最後に約束の Schema で照らす（ValueError。1 行）"""
    if not isinstance(rows, list):
        raise ValueError(f"prior_failures が配列でない（{type(rows).__name__}）")
    for i, r in enumerate(rows):
        if not isinstance(r, dict):
            raise ValueError(f"prior_failures[{i}] が {{where, text}} の object でない（{type(r).__name__}）")
        extra = sorted(set(r) - set(PRIOR_KEYS))
        if extra:
            raise ValueError(f"prior_failures[{i}] の知らない欄 {extra}（使えるのは {list(PRIOR_KEYS)}）")
        for key in PRIOR_KEYS:
            if not (isinstance(r.get(key), str) and r[key].strip()):
                raise ValueError(f"prior_failures[{i}] の {key} が空でない文字列でない（{r.get(key)!r}）")
    errs = errors(rows, PRIOR_SCHEMA)
    if errs:
        raise ValueError(f"prior_failures が約束 {PRIOR_SCHEMA} に合わない: {'; '.join(errs)}")
    return rows


def _answers(rows) -> list:
    """依頼の answers を確かめてそのまま返す。question・text は空でない文字列、command・output は両方か無し、
    知らない欄と同じ question の 2 度書きは拒む（ValueError。1 行）"""
    if not isinstance(rows, list):
        raise ValueError(f"answers が配列でない（{type(rows).__name__}）")
    seen = set()
    for i, a in enumerate(rows):
        if not isinstance(a, dict):
            raise ValueError(f"answers[{i}] が {{question, text, command?, output?}} の object でない（{type(a).__name__}）")
        if is_draft(a):
            raise ValueError(f"answers[{i}] は前の run の報告が書いた答えの下書き（draft・source の欄が在る。機械は答えていない）——"
                             "見直して、台帳の問いの行（question が問いの key）は採るなら draft と source（と note）の欄を消し"
                             "（text は直してよい。推しの無い行は text が空なので、note の材料から答えを書く）、"
                             "採らないなら行を消す。関所の項目の行（question が関所の項目の文）は次の run の関所の continue の一言の材料で、"
                             "依頼ではどの問いにも当たらないので、一言に写してから行を消す")
        extra = sorted(set(a) - set(ANSWER_KEYS))
        if extra:
            raise ValueError(f"answers[{i}] の知らない欄 {extra}（使えるのは {list(ANSWER_KEYS)}）")
        for key in ANSWER_KEYS:
            if (key in a or key in ("question", "text")) and not (isinstance(a.get(key), str) and a[key].strip()):
                raise ValueError(f"answers[{i}] の {key} が空でない文字列でない（{a.get(key)!r}）")
        if ("command" in a) != ("output" in a):
            raise ValueError(f"answers[{i}] の command と output は両方書くか、どちらも書かない")
        if a["question"] in seen:
            raise ValueError(f"answers[{i}] の question {a['question']!r} が 2 度目（1 つの問いに答えは 1 つ）")
        seen.add(a["question"])
    return rows


def is_draft(row) -> bool:
    """下書きの印（DRAFT_KEYS のどれか）の在る行か。依頼の入口が拒む行と同じ決まり"""
    return isinstance(row, dict) and any(k in row for k in DRAFT_KEYS)


def draft(row: dict, source: str, note: str = "") -> dict:
    """行 row に下書きの印（draft: true と出どころ source。note が在れば人が答えを書く材料）を足した写し。欄の順は row の欄の後に
    draft・source・note"""
    out = {**row, DRAFT: True, SOURCE: source}
    if note:
        out[NOTE] = note
    return out


def compose(findings: list, prior: list, drafts: list) -> dict:
    """次の run の依頼の下書きの中身 {findings, prior_failures, answers?}（answers は答えの下書きが在る時だけ）。盤面を知らない"""
    doc = {FINDINGS: findings, PRIOR: prior}
    if drafts:
        doc[ANSWERS] = drafts
    return doc


def row_key(row: dict) -> str:
    """行の鍵: where と、text の最初の「（」までを空白を詰めて \\t でつないだ物（理由の尾だけ違う行を同じ物と見る）"""
    def squeeze(v):
        return " ".join(str(v or "").split())
    return f"{squeeze(row.get('where'))}\t{squeeze(str(row.get('text') or '').split('（', 1)[0])}"


def write(path, doc) -> None:
    """JSON を一時の名に書いて os.replace で一度に置く（indent 2・字のまま・末尾の改行）"""
    path = pathlib.Path(path)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _checked(doc, name: str, what: str):
    errs = errors(doc, name)
    if errs:
        raise ValueError(f"{what} が約束 {name} に合わない（works の不具合。置かない）: {'; '.join(errs)}")
    return doc


def save_next(board_dir, doc: dict) -> pathlib.Path:
    """次の run の依頼の下書きを盤面の根の NEXT_REQUEST_FILE に置く（NEXT_SCHEMA に照らし、合わなければ ValueError で置かない）"""
    p = pathlib.Path(board_dir) / NEXT_REQUEST_FILE
    write(p, _checked(doc, NEXT_SCHEMA, NEXT_REQUEST_FILE))
    return p


def save_prior(board_dir, rows: list) -> pathlib.Path:
    """この run で最後まで通らなかった物を盤面の根の PRIOR_FAILURES_FILE に置く（PRIOR_SCHEMA に照らす）"""
    p = pathlib.Path(board_dir) / PRIOR_FAILURES_FILE
    write(p, _checked(rows, PRIOR_SCHEMA, PRIOR_FAILURES_FILE))
    return p


def place_prior(board_dir, rows: list) -> None:
    """依頼の prior_failures を盤面の根の PRIOR_IN_FILE に置く（行が無くても空の配列。PRIOR_SCHEMA に照らす。読み手は manifest の
    consumes で宣言したブロックだけ）"""
    write(pathlib.Path(board_dir) / PRIOR_IN_FILE, _checked(list(rows), PRIOR_SCHEMA, PRIOR_IN_FILE))


def prior_section(board_dir, gap=ValueError) -> str:
    """盤面の根の PRIOR_IN_FILE の行を、役の材料に貼る節にした物（PRIOR_HEAD と 1 件 1 行）。無い・空なら ""。読めない・形が違えば
    gap（呼び手が渡す例外の型。盤面の層の呼び手は BoardGap。黙って 0 件に見せない）"""
    p = pathlib.Path(board_dir) / PRIOR_IN_FILE
    if not p.is_file():
        return ""
    try:
        rows = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise gap(f"{p} が読めない: {e}") from None
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise gap(f"{p} の形が違う（[{{where, text}}]）")
    if not rows:
        return ""
    return PRIOR_HEAD + "\n\n" + "\n".join(f"- {' '.join(str(r.get('where', '')).split())}: "
                                             f"{' '.join(str(r.get('text', '')).split())}" for r in rows)


def carry_ci(doc, ids) -> dict:
    """依頼 doc（findings の配列か object）に、CI が赤と言った試験の id の並び ids を prior_failures の行として足した object を
    返す（doc は変えない）。id は前後の空白を落とし、空と重なりは捨てる。既に同じ行が在れば足さない。answers と findings の下書き
    （DRAFT_KEYS の在る行。前の run の報告が書き、人がまだ見直していない）は確かめずにそのまま残す（下書きは次の run の入口が拒む）"""
    def drop(rows):
        return [r for r in rows if not is_draft(r)]
    bare = drop(doc) if isinstance(doc, list) else doc
    if isinstance(doc, dict):
        bare = {**doc, **{k: drop(doc[k]) for k in (ANSWERS, FINDINGS) if isinstance(doc.get(k), list)}}
    got_parts = parts(bare)
    got = list(dict.fromkeys(i.strip() for i in ids if isinstance(i, str) and i.strip()))
    if not got:
        raise ValueError("CI の赤の試験の id が 1 つも無い")
    out = dict(doc) if isinstance(doc, dict) else {FINDINGS: list(doc)}
    rows = [dict(r) for r in got_parts[PRIOR]]
    for test_id in got:
        row = {"where": CI_WHERE, "text": CI_TEXT.format(id=test_id)}
        if row not in rows:
            rows.append(row)
    out[PRIOR] = rows
    return out


def _carry_cli(request: str, failed: str, out: str) -> int:
    """carry-ci の口: request（next-request.json）を読み、failed（1 行に 1 つの試験の id。# で始まる行と空の行は飛ばす。- は
    標準入力）の id を足して out に書く（request と同じでよい）。誤りは標準エラーに 1 行で 2（out は書かない）"""
    try:
        doc = json.loads(pathlib.Path(request).read_text(encoding="utf-8"))
        text = sys.stdin.read() if failed == "-" else pathlib.Path(failed).read_text(encoding="utf-8")
        ids = [ln for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
        got = carry_ci(doc, ids)
    except (OSError, ValueError) as e:
        print(f"carry carry-ci: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    write(out, got)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="carry.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("carry-ci")
    c.add_argument("--request", required=True)
    c.add_argument("--failed", required=True)
    c.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    return _carry_cli(a.request, a.failed, a.out)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
