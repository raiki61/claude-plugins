"""依頼のファイルの形と、依頼が名指した PR・issue を隔離の前に読む 1 か所（設計書 2.8）。層 L1（works の物を何も知らない）。
標準ライブラリだけ（Python 3.9 で動く）。殻（use.sh・dogfood.sh）は `python3 -I ghreads.py read …` でファイルとして呼ぶ。

依頼のファイルは findings の JSON の配列か、{"findings": [...], "pr": [<番号>…], "issue": [<番号>…], "answers": [...]} の形。
answers は依頼者が前の run の問いに答えた物 [{question, text, command?, output?}]（question は問いの key か出どころ。
command・output は人が手元で測った命令と出力で、両方か無し）。読み手
（entry・判定と前提の intake）はここで解き、graphloops の規則（check_request・add_request・REQUEST_SCHEMA）に渡すのは
findings だけにする（容器の形を規則の側へ漏らさない）。

隔離した Archon の中（HOME を差し替えた env）からは利用者の gh のログインが見えず、非公開のリポジトリは読めない（gh は
exit 4）。だから殻が Archon を起こす前に、利用者の env のまま 1 回だけ読み、結果のファイルをラインの入力 github_reads で
渡す。名指しは依頼の欄 pr・issue と --pr に限る（本文の中の URL は拾わない）。トークンの値は読まない（gh 自身の設定に任せる）。

- request_parts(doc) -> {"findings": list, "pr": [int], "issue": [int], "answers": [dict]}: 解けなければ ValueError（1 行）
- read(repo, request, pr, out) -> int: 名指した物を読んで out に置く。終了コード（0 以外は --pr の base・head が読めない時だけ）
- load(board_dir, src) -> doc|None: 盤面の根の github.json を先に、無ければ src を読むだけ（盤面を作る前に入力を確かめる）
- adopt(board_dir, src) -> doc|None: 盤面の根の github.json を先に使い、無ければ src を写して元を消す
- 読み出しのファイルの形: {version, pr: {<番号>: {...}}, issue: {<番号>: {...}}}。読めない項は {status: unreadable, reason}
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys

sys.dont_write_bytecode = True

KEYS = ("findings", "pr", "issue", "answers")
ANSWER_KEYS = ("question", "text", "command", "output")
GITHUB_READS_VERSION = 1
BOARD_FILE = "github.json"   # 盤面の根に置く読み出しの写し
PR_FIELDS = "baseRefOid,headRefOid,title,body,comments,reviews"
ISSUE_FIELDS = "title,body,comments"
UNREADABLE = "unreadable"


def request_parts(doc) -> dict:
    if isinstance(doc, list):
        return {"findings": doc, "pr": [], "issue": [], "answers": []}
    if not isinstance(doc, dict):
        raise ValueError(f"findings の配列か {{findings, pr, issue, answers}} の形でない（{type(doc).__name__}）")
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
    return out


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
    doc = {"version": GITHUB_READS_VERSION, "pr": {}, "issue": {}}
    for n in prs:
        doc["pr"][str(n)] = _read_pr(repo, n)
    for n in issues:
        doc["issue"][str(n)] = _read_issue(repo, n)
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
    a = ap.parse_args(argv)
    if a.pr and not a.pr.isdigit():
        print(f"ghreads: --pr {a.pr!r} は PR の番号でない", file=sys.stderr)
        return 2
    return read(a.repo, a.request, a.pr, a.out)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
