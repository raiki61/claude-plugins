"""依頼のファイルの形と、依頼が名指した PR・issue を隔離の前に読む 1 か所（設計書 2.8）。層 L1（works の物を何も知らない）。
標準ライブラリだけ（Python 3.9 で動く）。殻（use.sh・dogfood.sh）は `python3 -I ghreads.py read …` でファイルとして呼ぶ。

依頼のファイルは findings の JSON の配列か、{"findings": [...], "pr": [<番号>…], "issue": [<番号>…], "answers": [...],
"prior_failures": [...]} の形。prior_failures は前の run で最後まで通らなかった物 [{where, text}]（前の run の報告が書く
next-request.json の欄。判定役と修正案の役の材料に貼る注意で、直す穴ではない）。
answers は依頼者が前の run の問いに答えた物 [{question, text, command?, output?}]（question は問いの key か出どころ。
command・output は人が手元で測った命令と出力で、両方か無し）。読み手
（entry・判定と前提の intake）はここで解き、graphloops の規則（check_request・add_request・REQUEST_SCHEMA）に渡すのは
findings だけにする（容器の形を規則の側へ漏らさない）。

隔離した Archon の中（HOME を差し替えた env）からは利用者の gh のログインが見えず、非公開のリポジトリは読めない（gh は
exit 4）。だから殻が Archon を起こす前に、利用者の env のまま 1 回だけ読み、結果のファイルをラインの入力 github_reads で
渡す。名指しは依頼の欄 pr・issue と --pr に限る（本文の中の URL は拾わない）。トークンの値は読まない（gh 自身の設定に任せる）。

- request_parts(doc) -> {"findings": list, "pr": [int], "issue": [int], "answers": [dict], "prior_failures": [dict]}: 解けなければ ValueError（1 行）
- carry_ci(doc, ids) -> 依頼の object: run の後の CI が赤と言った試験の id を prior_failures の行（where CI_WHERE）として足す。
  重い試験は run の外の CI で回り、run の報告はその赤を知らないので、人（か回す役）が CI の赤の id を next-request.json に足す口。
  同じ行は 2 度足さない。id が無い・依頼の形が違えば ValueError（1 行）。殻からは `python3 -I ghreads.py carry-ci`
- read(repo, request, pr, out) -> int: 名指した物を読んで out に置く。終了コード（0 以外は --pr の base・head が読めない時だけ）
- load(board_dir, src) -> doc|None: 盤面の根の github.json を先に、無ければ src を読むだけ（盤面を作る前に入力を確かめる）
- adopt(board_dir, src) -> doc|None: 盤面の根の github.json を先に使い、無ければ src を写して元を消す
- 読み出しのファイルの形: {version, pr: {<番号>: {...}}, issue: {<番号>: {...}}}。読めない項は {status: unreadable, reason}。
  対象の remote に forge（PR を持つホスト。forge.py）が無ければ gh を呼ばず、名指した項は {status: not_applicable, reason: no_forge: …}、
  --pr は書かずに 1（base を名指して回す）
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

sys.dont_write_bytecode = True
_HERE = str(pathlib.Path(__file__).resolve().parent)
if _HERE not in sys.path:   # 殻は python3 -I で起こす（-I は自分の置き場を sys.path に足さない）。同じ層の forge だけを読む
    sys.path.append(_HERE)     # 末尾に足す（core の名が標準の模块の名を覆わない）

import forge  # noqa: E402

KEYS = ("findings", "pr", "issue", "answers", "prior_failures")
ANSWER_KEYS = ("question", "text", "command", "output")
PRIOR_KEYS = ("where", "text")   # prior_failures の行の欄（前の run の報告が next-request.json に書いた形）
CI_WHERE = "run の後の CI"   # carry_ci が足す prior_failures の行の where
CI_TEXT = ("試験 {id} が CI で赤だった（重い試験は run の外の CI で回る。前の run の直しがこの試験を赤にした見込み。"
           "同じ試験を赤にしない直しを出す）")
GITHUB_READS_VERSION = 1
BOARD_FILE = "github.json"   # 盤面の根に置く読み出しの写し
PR_FIELDS = "baseRefOid,headRefOid,title,body,comments,reviews"
ISSUE_FIELDS = "title,body,comments"
UNREADABLE = "unreadable"
NOT_APPLICABLE = "not_applicable"   # forge の無い対象（forge.reason）で名指した項。gh を呼ばない


def request_parts(doc) -> dict:
    if isinstance(doc, list):
        return {"findings": doc, "pr": [], "issue": [], "answers": [], "prior_failures": []}
    if not isinstance(doc, dict):
        raise ValueError(f"findings の配列か {{findings, pr, issue, answers, prior_failures}} の形でない（{type(doc).__name__}）")
    extra = sorted(set(doc) - set(KEYS))
    if extra:
        raise ValueError(f"知らない鍵 {extra}（使えるのは {list(KEYS)}）")
    findings = doc.get("findings", [])
    if not isinstance(findings, list):
        raise ValueError(f"findings が配列でない（{type(findings).__name__}）")
    out = {"findings": findings}
    for key in ("pr", "issue"):
        nums = doc.get(key, [])
        if not isinstance(nums, list) or any(type(n) is not int or n <= 0 for n in nums):
            raise ValueError(f"{key} が正の整数の配列でない（{nums!r}）")
        out[key] = nums
    out["answers"] = _answers(doc.get("answers", []))
    out["prior_failures"] = _prior_failures(doc.get("prior_failures", []))
    return out


def _prior_failures(rows) -> list:
    """依頼の prior_failures（前の run で最後まで通らなかった物。前の run の報告が書いた next-request.json の欄）を確かめて
    そのまま返す。行は {where, text} で、どちらも空でない文字列。知らない欄は拒む（ValueError。1 行）"""
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
    return rows


def carry_ci(doc, ids) -> dict:
    """依頼 doc（findings の配列か object）に、CI が赤と言った試験の id の並び ids を prior_failures の行として足した object を
    返す（doc は変えない）。id は前後の空白を落とし、空と重なりは捨てる。既に同じ行が在れば足さない"""
    parts = request_parts(doc)
    got = list(dict.fromkeys(i.strip() for i in ids if isinstance(i, str) and i.strip()))
    if not got:
        raise ValueError("CI の赤の試験の id が 1 つも無い")
    out = dict(doc) if isinstance(doc, dict) else {"findings": list(doc)}
    rows = [dict(r) for r in parts["prior_failures"]]
    for test_id in got:
        row = {"where": CI_WHERE, "text": CI_TEXT.format(id=test_id)}
        if row not in rows:
            rows.append(row)
    out["prior_failures"] = rows
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
        print(f"ghreads carry-ci: {' '.join(str(e).split())}", file=sys.stderr)
        return 2
    dest = pathlib.Path(out)
    tmp = dest.with_name(dest.name + ".tmp")
    tmp.write_text(json.dumps(got, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, dest)
    return 0


def _answers(rows) -> list:
    """依頼の answers を確かめてそのまま返す。question・text は空でない文字列、command・output は両方か無し、
    知らない欄と同じ question の 2 度書きは拒む（ValueError。1 行）"""
    if not isinstance(rows, list):
        raise ValueError(f"answers が配列でない（{type(rows).__name__}）")
    seen = set()
    for i, a in enumerate(rows):
        if not isinstance(a, dict):
            raise ValueError(f"answers[{i}] が {{question, text, command?, output?}} の object でない（{type(a).__name__}）")
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


def _line(text) -> str:
    return " ".join(str(text).split())


def _gh(repo: pathlib.Path, *args):
    """gh を cwd＝repo で 1 回呼んで (JSON の値, None) か (None, 読めない理由の 1 行)。--paginate の連なった配列は 1 つに繋ぐ"""
    try:
        got = subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    except OSError as e:
        return None, _line(f"gh が起きない（{type(e).__name__}: {e}）")
    if got.returncode != 0:
        first = next((s for s in got.stderr.splitlines() if s.strip()), "")
        return None, _line(f"gh {args[0]} が exit {got.returncode}" + (f": {first}" if first else ""))
    dec, text, pos, parts = json.JSONDecoder(), got.stdout, 0, []
    try:
        while text[pos:].strip():
            pos += len(text[pos:]) - len(text[pos:].lstrip())
            value, pos = dec.raw_decode(text, pos)
            parts.append(value)
    except json.JSONDecodeError as e:
        return None, _line(f"gh {args[0]} の出力が JSON でない（{e}）")
    if len(parts) > 1 and all(isinstance(p, list) for p in parts):
        return [x for p in parts for x in p], None
    return (parts[0] if parts else None), None


def _read_pr(repo: pathlib.Path, n: int) -> dict:
    doc, why = _gh(repo, "pr", "view", str(n), "--json", PR_FIELDS)
    if not isinstance(doc, dict):
        return {"status": UNREADABLE, "reason": why or "gh pr view の返りが object でない"}
    lines, why = _gh(repo, "api", "--paginate", f"repos/{{owner}}/{{repo}}/pulls/{n}/comments")
    if not isinstance(lines, list):
        return {**doc, "status": "partial", "reason": why or "行コメントの返りが配列でない", "review_comments": []}
    return {**doc, "status": "ok", "review_comments": lines}


def _read_issue(repo: pathlib.Path, n: int) -> dict:
    doc, why = _gh(repo, "issue", "view", str(n), "--json", ISSUE_FIELDS)
    if not isinstance(doc, dict):
        return {"status": UNREADABLE, "reason": why or "gh issue view の返りが object でない"}
    return {**doc, "status": "ok"}


def _write(out: pathlib.Path, doc: dict) -> None:
    """一時の名に書いて os.replace で一度に置く（途中の残りを作らない）"""
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(doc, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    os.replace(tmp, out)


def read(repo, request: str, pr: str, out) -> int:
    """依頼のファイル（"" か "-" なら無し）の pr・issue と --pr の番号を読み、out に置く。名指しが無ければ何も書かずに 0。
    依頼が読めない・形の外なら何も書かずに 0（形の誤りは start が拒む）。--pr の base・head が読めなければ書かずに 1"""
    repo, out = pathlib.Path(repo), pathlib.Path(out)
    prs, issues = [], []
    if request and request != "-":
        try:
            parts = request_parts(json.loads(pathlib.Path(request).read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, ValueError):
            return 0
        prs, issues = list(parts["pr"]), list(parts["issue"])
    cli = int(pr) if pr else None
    if cli is not None and cli not in prs:
        prs.append(cli)
    if not prs and not issues:
        return 0
    no_forge = forge.reason(forge.detect(repo))
    if no_forge and cli is not None:
        print(f"ghreads: PR #{cli} は GitHub の PR の base・head を読む——対象の remote に PR を持つホストが無い（{no_forge}）。"
              "base を名指して回す", file=sys.stderr)
        return 1
    doc = {"version": GITHUB_READS_VERSION, "pr": {}, "issue": {}}
    na = {"status": NOT_APPLICABLE, "reason": no_forge}
    for n in prs:
        doc["pr"][str(n)] = dict(na) if no_forge else _read_pr(repo, n)
    for n in issues:
        doc["issue"][str(n)] = dict(na) if no_forge else _read_issue(repo, n)
    if cli is not None:
        got = doc["pr"][str(cli)]
        if not got.get("baseRefOid") or not got.get("headRefOid"):
            print(f"ghreads: PR #{cli} の base・head を読めない（{got.get('reason') or '欄が無い'}）——"
                  "利用者の gh でログインしてから回す", file=sys.stderr)
            return 1
    _write(out, doc)
    return 0


def load(board_dir, src):
    """盤面の根の github.json が在ればそれを、無ければ src を読んで返す（書かない・消さない）。どちらも無ければ None"""
    dest = pathlib.Path(board_dir) / BOARD_FILE
    if dest.is_file():
        return json.loads(dest.read_text(encoding="utf-8"))
    if not src or not pathlib.Path(src).is_file():
        return None
    return json.loads(pathlib.Path(src).read_text(encoding="utf-8"))


def adopt(board_dir, src):
    """盤面の根の github.json が在ればそれを返す（Archon の再開で呼び直された時）。無く src が在れば盤面へ写して src を消し、
    写した物を返す。どちらも無ければ None。盤面の置き場は在ること（作るのは盤面の begin）"""
    dest = pathlib.Path(board_dir) / BOARD_FILE
    doc = load(board_dir, src)
    if doc is not None and not dest.is_file():
        _write(dest, doc)
        pathlib.Path(src).unlink()
    return doc


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ghreads.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("read")
    r.add_argument("--repo", required=True)
    r.add_argument("--request", default="-")
    r.add_argument("--pr", default="")
    r.add_argument("--out", required=True)
    c = sub.add_parser("carry-ci")
    c.add_argument("--request", required=True)
    c.add_argument("--failed", required=True)
    c.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    if a.cmd == "carry-ci":
        return _carry_cli(a.request, a.failed, a.out)
    if a.pr and not a.pr.isdigit():
        print(f"ghreads: --pr {a.pr!r} は PR の番号でない", file=sys.stderr)
        return 2
    return read(a.repo, a.request, a.pr, a.out)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
