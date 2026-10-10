"""依頼が名指した PR・issue を run の中で読む 1 か所（設計書 2.8）。層 L1（works の物を何も知らない）。
標準ライブラリだけ（Python 3.9 で動く）。依頼のファイルの形（欄 pr・issue を含む容器）は持ち越しの住処 carry が解く。

名指した PR・issue は、線の入口（entry.start）が run の中で gh を対象の根で呼んで読む。run の中の gh は開発の殻
（dev/hostgh.py の口）が利用者の gh のログインを継がせる（2026-10-08 から。それより前は隔離した Archon の中から利用者の
ログインが見えず、殻が隔離の前に読んでファイルで渡していた）。名指しは依頼の欄 pr・issue と入力 pr に限る（本文の中の URL は
拾わない）。トークンの値は読まない（gh 自身の設定に任せる）。殻の口は持たない（前の carry-ci は carry.py へ移った）。

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
import json
import os
import pathlib
import subprocess
import sys

sys.dont_write_bytecode = True
_HERE = str(pathlib.Path(__file__).resolve().parent)
if _HERE not in sys.path:   # 置き場を sys.path に持たない起こし方（python3 -I など）でも同じ層の forge だけを読む
    sys.path.append(_HERE)     # 末尾に足す（core の名が標準のモジュールの名を覆わない）

import forge  # noqa: E402

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
    """殻の口は無い: 起こされたら移った先を 1 行で言って 2（前の carry-ci の打ち方を黙って通さない）"""
    print("ghreads.py に殻の口は無い——run の後の CI の赤を次の依頼へ足す carry-ci は同じ置き場の carry.py へ移った"
          "（python3 -I carry.py carry-ci --request … --failed … --out …）", file=sys.stderr)
    return 2


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main())
