"""依頼のファイルの形と、依頼が名指した PR・issue を run の中で読む 1 か所（設計書 2.8）。層 L1（works の物を何も知らない）。
標準ライブラリだけ（Python 3.9 で動く）。殻は `python3 -I ghreads.py carry-ci …` でファイルとして呼ぶ。

依頼のファイルは findings の JSON の配列か、{"findings": [...], "pr": [<番号>…], "issue": [<番号>…], "answers": [...],
"prior_failures": [...]} の形。prior_failures は前の run で最後まで通らなかった物 [{where, text}]（前の run の報告が書く
next-request.json の欄。判定役と修正案の役の材料に貼る注意で、直す穴ではない）。
answers は依頼者が前の run の問いに答えた物 [{question, text, command?, output?}]（question は問いの key か出どころ。
command・output は人が手元で測った命令と出力で、両方か無し。前の run の報告が書いた答えの下書きの印 draft・source の在る行は、
人が見直していないので拒む。findings の行も同じ: 前の run の判定が目的の外とした所見を報告が下書きの印つきで運ぶ）。読み手
（entry・判定と前提の intake）はここで解き、graphloops の規則（check_request・add_request・REQUEST_SCHEMA）に渡すのは
findings だけにする（容器の形を規則の側へ漏らさない）。

名指した PR・issue は、線の入口（entry.start）が run の中で gh を対象の根で呼んで読む。run の中の gh は開発の殻
（dev/hostgh.py の口）が利用者の gh のログインを継がせる（2026-10-08 から。それより前は隔離した Archon の中から利用者の
ログインが見えず、殻が隔離の前に読んでファイルで渡していた）。名指しは依頼の欄 pr・issue と入力 pr に限る（本文の中の URL は
拾わない）。トークンの値は読まない（gh 自身の設定に任せる）。

- request_parts(doc) -> {"findings": list, "pr": [int], "issue": [int], "answers": [dict], "prior_failures": [dict]}: 解けなければ ValueError（1 行）
- without_prior(doc) -> 依頼の object か None: 前の run の判断（欄 prior_failures）を外した写し。前の run の判断を知らない別の目
  （目的の役）に渡す形を機械が作る口。欄が無い・object でない（findings の配列の形）なら None（そのまま渡してよい）
- carry_ci(doc, ids) -> 依頼の object: run の後の CI が赤と言った試験の id を prior_failures の行（where CI_WHERE）として足す。
  重い試験は run の外の CI で回り、run の報告はその赤を知らないので、人（か回す役）が CI の赤の id を next-request.json に足す口。
  同じ行は 2 度足さない。id が無い・依頼の形が違えば ValueError（1 行）。殻からは `python3 -I ghreads.py carry-ci`
- read_named(repo, prs, issues) -> 読み出し: 名指した物を gh で読む（gh の cwd は repo）。読めない項も記録して返す（止めない）
- load_board(board_dir) -> 読み出し|None: 盤面の根の github.json（Archon の再開で読み直さない）。無ければ None
- place(board_dir, doc): 読み出しを盤面の根の github.json に 0600 で置く（非公開の本文を持つ）
- 読み出しの形: {version, pr: {<番号>: {...}}, issue: {<番号>: {...}}}。読めない項は {status: unreadable, reason}。
  対象の remote に forge（PR を持つホスト。forge.py）が無くても、利用者が名指した項は gh で読む（GH_REPO・別の remote・自前の
  ドメインの GitHub Enterprise Server なら gh は読める。名指した物を黙って落とさない）。forge の無い対象で、gh も GitHub の
  ホストを見つけなかった項（GH_NO_HOST の言葉か exit 4。gh が起きない時も）は unreadable でなく {status: not_applicable, reason: no_forge: …。gh でも
  読めなかった: …}。gh が GitHub のホストとして読みに行って読めなかった項（自前のドメインの GHES でログインが切れた・HTTP 401
  など）は forge の無い対象でも {status: unreadable, reason: gh の言葉, forge: no_forge: …}。入力 pr の base・head が読めない時に
  止めるのは読み手（entry）
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
DRAFT_KEYS = ("draft", "source")   # 前の run の報告が next-request.json の answers・findings に置く下書きの印（人が見直して消すまで拒む）
PRIOR_KEYS = ("where", "text")   # prior_failures の行の欄（前の run の報告が next-request.json に書いた形）
CI_WHERE = "run の後の CI"   # carry_ci が足す prior_failures の行の where
CI_TEXT = ("試験 {id} が CI で赤だった（重い試験は run の外の CI で回る。前の run の直しがこの試験を赤にした見込み。"
           "同じ試験を赤にしない直しを出す）")
GITHUB_READS_VERSION = 1
BOARD_FILE = "github.json"   # 盤面の根に置く読み出しの写し
PR_FIELDS = "baseRefOid,headRefOid,title,body,comments,reviews"
ISSUE_FIELDS = "title,body,comments"
UNREADABLE = "unreadable"
NOT_APPLICABLE = "not_applicable"   # forge の無い対象（forge.reason）で名指し、gh も GitHub のホストを見つけなかった項
# gh が対象を GitHub のホストと見なかった（読みに行く先が無かった）時の言葉。gh 2.96 の実測（2026-10-07）: GitHub でないホスト・
# ローカルのパスの remote は前者、remote が無ければ後者（どちらも exit 1）。どこにもログインしていない gh は remote を見る前に
# exit 4（gh help exit-codes の Authentication required）。これらのほか（HTTP 401・404・網）は、gh が GitHub のホストとして
# 読みに行って読めなかった物（自前のドメインの GitHub Enterprise Server でログインが切れた、など）
GH_NO_HOST = ("point to a known GitHub host", "no git remotes found")
GH_EXIT_AUTH = 4


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
    for i, f in enumerate(findings):
        if isinstance(f, dict) and any(k in f for k in DRAFT_KEYS):
            raise ValueError(f"findings[{i}] は前の run の報告が運んだ所見の下書き（draft・source の欄が在る。前の run の判定が目的の"
                             "外とした所見で、人が見直していない）——この run の目的に入れるなら draft と source の欄を消し、入れない"
                             "なら行を消す")
    out = {"findings": findings}
    for key in ("pr", "issue"):
        nums = doc.get(key, [])
        if not isinstance(nums, list) or any(type(n) is not int or n <= 0 for n in nums):
            raise ValueError(f"{key} が正の整数の配列でない（{nums!r}）")
        out[key] = nums
    out["answers"] = _answers(doc.get("answers", []))
    out["prior_failures"] = _prior_failures(doc.get("prior_failures", []))
    return out


def without_prior(doc):
    """依頼 doc から前の run の判断（欄 prior_failures）を外した写し（ほかの欄は字のまま）。欄が無い・object でなければ None"""
    if isinstance(doc, dict) and "prior_failures" in doc:
        return {k: v for k, v in doc.items() if k != "prior_failures"}
    return None


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
    返す（doc は変えない）。id は前後の空白を落とし、空と重なりは捨てる。既に同じ行が在れば足さない。answers と findings の下書き
    （DRAFT_KEYS の在る行。前の run の報告が書き、人がまだ見直していない）は確かめずにそのまま残す（下書きは次の run の入口が拒む）"""
    def drop(rows):
        return [r for r in rows if not (isinstance(r, dict) and any(k in r for k in DRAFT_KEYS))]
    bare = drop(doc) if isinstance(doc, list) else doc
    if isinstance(doc, dict):
        bare = {**doc, **{k: drop(doc[k]) for k in ("answers", "findings") if isinstance(doc.get(k), list)}}
    parts = request_parts(bare)
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
        if any(k in a for k in DRAFT_KEYS):
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


def _line(text) -> str:
    return " ".join(str(text).split())


def _gh(repo: pathlib.Path, *args):
    """gh を cwd＝repo で 1 回呼んで (JSON の値, None, False) か (None, 読めない理由の 1 行, no_host)。no_host は gh が読みに行く
    GitHub のホストを見つけなかった（GH_NO_HOST の言葉か exit 4。gh が起きない時も）か。--paginate の連なった配列は 1 つに繋ぐ"""
    try:
        got = subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True, encoding="utf-8")
    except OSError as e:
        return None, _line(f"gh が起きない（{type(e).__name__}: {e}）"), True
    if got.returncode != 0:
        first = next((s for s in got.stderr.splitlines() if s.strip()), "")
        no_host = got.returncode == GH_EXIT_AUTH or any(w in got.stderr for w in GH_NO_HOST)
        return None, _line(f"gh {args[0]} が exit {got.returncode}" + (f": {first}" if first else "")), no_host
    dec, text, pos, parts = json.JSONDecoder(), got.stdout, 0, []
    try:
        while text[pos:].strip():
            pos += len(text[pos:]) - len(text[pos:].lstrip())
            value, pos = dec.raw_decode(text, pos)
            parts.append(value)
    except json.JSONDecodeError as e:
        return None, _line(f"gh {args[0]} の出力が JSON でない（{e}）"), False
    if len(parts) > 1 and all(isinstance(p, list) for p in parts):
        return [x for p in parts for x in p], None, False
    return (parts[0] if parts else None), None, False


def _read_pr(repo: pathlib.Path, n: int) -> dict:
    doc, why, no_host = _gh(repo, "pr", "view", str(n), "--json", PR_FIELDS)
    if not isinstance(doc, dict):
        return _unreadable(why or "gh pr view の返りが object でない", no_host)
    lines, why, _ = _gh(repo, "api", "--paginate", f"repos/{{owner}}/{{repo}}/pulls/{n}/comments")
    if not isinstance(lines, list):
        return {**doc, "status": "partial", "reason": why or "行コメントの返りが配列でない", "review_comments": []}
    return {**doc, "status": "ok", "review_comments": lines}


def _read_issue(repo: pathlib.Path, n: int) -> dict:
    doc, why, no_host = _gh(repo, "issue", "view", str(n), "--json", ISSUE_FIELDS)
    if not isinstance(doc, dict):
        return _unreadable(why or "gh issue view の返りが object でない", no_host)
    return {**doc, "status": "ok"}


def _unreadable(why: str, no_host: bool) -> dict:
    """読めない項。_no_host（gh が GitHub のホストを見つけなかったか）は _settle が読んで外す内側の印で、ファイルには残らない"""
    return {"status": UNREADABLE, "reason": why, "_no_host": no_host}


def _settle(got: dict, no_forge: str) -> dict:
    """読めない項の行き先を決め、内側の印を外す。forge の無い対象（no_forge は forge.reason の文）で、gh も GitHub のホストを
    見つけなかった項は not_applicable（確かめる物が無い。理由の頭は no_forge: <種類>、gh の言葉も添える）。gh が GitHub の
    ホストとして読みに行って読めなかった項（自前のドメインの GitHub Enterprise Server でログインが切れた、など）は、forge の無い
    対象でも unreadable のままにして理由は gh の言葉、forge の無い決めは欄 forge に分けて残す（本当に条件外の項と見分ける）。
    読めた項（ok・partial）と forge の在る対象の項はそのまま"""
    got = dict(got)
    no_host = got.pop("_no_host", False)
    if not no_forge or got.get("status") != UNREADABLE:
        return got
    if no_host:
        return {"status": NOT_APPLICABLE, "reason": f"{no_forge}。gh でも読めなかった: {got.get('reason') or '理由なし'}"}
    return {**got, "forge": no_forge}


def _write(out: pathlib.Path, doc: dict) -> None:
    """一時の名に 0600 で作って書き、os.replace で一度に置く（途中の残りを作らない）。落ちたら一時の名を残さない。
    読み出しは非公開の本文を持つので、umask に任せず、前から緩い権限で在った一時の名・out も 0600 で置き直す"""
    data = (json.dumps(doc, ensure_ascii=False, indent=1) + "\n").encode("utf-8")
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_name(f".{out.name}.{os.getpid()}.tmp")
    tmp.unlink(missing_ok=True)
    try:
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0), 0o600)
        with os.fdopen(fd, "wb") as f:
            if hasattr(os, "fchmod"):
                os.fchmod(f.fileno(), 0o600)
            f.write(data)
        os.replace(tmp, out)
    except BaseException:
        tmp.unlink(missing_ok=True)
        raise


def read_named(repo, prs, issues) -> dict:
    """名指した PR（番号の並び prs）と issue（issues）を gh で 1 回ずつ読み、読み出しの形で返す（何も書かない）。
    読めない項も理由つきで載せて返す。gh の cwd は対象の根 repo"""
    repo = pathlib.Path(repo)
    no_forge = forge.reason(forge.detect(repo))
    doc = {"version": GITHUB_READS_VERSION, "pr": {}, "issue": {}}
    for n in dict.fromkeys(prs):
        doc["pr"][str(n)] = _settle(_read_pr(repo, n), no_forge)
    for n in dict.fromkeys(issues):
        doc["issue"][str(n)] = _settle(_read_issue(repo, n), no_forge)
    return doc


def load_board(board_dir):
    """盤面の根の github.json を読んで返す（Archon の再開で同じ読み出しを使う）。無ければ None。壊れていれば ValueError・OSError"""
    dest = pathlib.Path(board_dir) / BOARD_FILE
    if not dest.is_file():
        return None
    return json.loads(dest.read_text(encoding="utf-8"))


def place(board_dir, doc) -> None:
    """読み出しを盤面の根の github.json に 0600 で置く（_write。盤面の置き場は在ること）"""
    _write(pathlib.Path(board_dir) / BOARD_FILE, doc)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="ghreads.py")
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
