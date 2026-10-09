"""名指しの出どころが現物に在るかの確かめ（食い違いの申し出の引用の照らしと、修正前の関所の決め手の出どころの照らしが使う 1 か所）。

- CITE: 名指し `<パス>:<行>` か `<パス>:<行>-<行>` の形
- inside(p, root): p が root の中か
- problem(cite, repo, roots=()) -> str: 1 つの名指しの確かめ（通れば空）。相対のパスは作業ツリーの根から（外と .git は拒む）、
  絶対のパスは作業ツリーの中か roots（依頼のファイル・盤面の置き場）の中だけ。ファイルが在り、行がその中に在る
- sources_problem(text, repo, roots=(), quoted="") -> str: 決め手の文（decided_by）の出どころの確かめ（通れば空）。文の中の
  URL（http・https。形だけ見る。取りに行かない）・名指し `<パス>:<行>`（problem）・作業ツリーの中のパス（/ を含むか拡張子を持つ語で、
  在るファイルかフォルダ）・依頼の引用「…」（quoted＝依頼の文の中に字のまま在る）のどれかが 1 つ以上在り、書いた物が全部現物に
  在る時だけ通る。どれも無ければ「出どころが現物に無い」

標準ライブラリだけ。works の物を何も import しない（conflict と gatemarks の両方が読む。輪を作らない）。
"""
from __future__ import annotations

import pathlib
import re

CITE = re.compile(r"^(?P<path>.+?):(?P<a>[1-9][0-9]*)(?:-(?P<b>[1-9][0-9]*))?$")
URL = re.compile(r"https?://[^\s）)」』、。,]+")
QUOTE = re.compile(r"「([^」]{4,})」")
TOKEN = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_./-]*(?::[1-9][0-9]*(?:-[1-9][0-9]*)?)?")
NO_SOURCE = "決め手の出どころが現物に無い（パス:行・URL・依頼の引用「…」・設計の決定の記録のパスのどれも書いていない）"


def inside(p: pathlib.Path, root: pathlib.Path) -> bool:
    try:
        p.relative_to(root)
        return True
    except ValueError:
        return False


def problem(cite, repo, roots=()) -> str:
    """名指し `<パス>:<行>` か `<パス>:<行>-<行>` の確かめ（通れば空）"""
    if not isinstance(cite, str):
        return f"名指し {cite!r} が文字列でない"
    m = CITE.match(cite.strip())
    if not m:
        return f"名指し {cite!r} が <パス>:<行> の形でない（例 tests/test_x.py:12・src/x.py:30-34・依頼のファイルの絶対パス:3）"
    a, b = int(m["a"]), int(m["b"] or m["a"])
    if b < a:
        return f"名指し {cite!r} の行の範囲が逆"
    repo = pathlib.Path(repo).resolve()
    raw = pathlib.Path(m["path"])
    p = (raw if raw.is_absolute() else repo / raw).resolve()
    allowed = [repo] + [pathlib.Path(r).resolve() for r in roots if r]
    if not any(p == r or inside(p, r) for r in allowed) or inside(p, repo / ".git"):
        return f"名指し {cite!r} のパスが作業ツリー・依頼のファイル・盤面の外"
    if not p.is_file():
        return f"名指し {cite!r} のファイルが無い"
    try:
        n = len(p.read_text(encoding="utf-8", errors="replace").splitlines())
    except OSError as e:
        return f"名指し {cite!r} のファイルが読めない（{type(e).__name__}）"
    if b > n:
        return f"名指し {cite!r} の行がファイルに無い（{n} 行しか無い）"
    return ""


def _pathish(word: str) -> bool:
    last = word.rsplit("/", 1)[-1]
    return ("/" in word or bool(re.fullmatch(r"[^.]+\.[A-Za-z][A-Za-z0-9]{0,5}", last))) and not word.startswith(".")


def sources_problem(text, repo, roots=(), quoted: str = "") -> str:
    if not isinstance(text, str) or not text.strip():
        return NO_SOURCE
    found, bad = 0, []
    rest = URL.sub(" ", text)
    found += len(URL.findall(text))
    for q in QUOTE.findall(rest):
        found += 1
        if q.strip() not in quoted:
            bad.append(f"依頼の引用「{q}」が依頼の文に無い")
    rest = QUOTE.sub(" ", rest)
    repo_p = pathlib.Path(repo).resolve()
    for word in TOKEN.findall(rest):
        word = word.rstrip(".")
        if CITE.match(word):
            found += 1
            got = problem(word, repo_p, roots)
            if got:
                bad.append(got)
        elif _pathish(word):
            p = (repo_p / word).resolve()
            if inside(p, repo_p) and p.exists():
                found += 1
    if bad:
        return "決め手の出どころが現物に無い: " + " / ".join(bad)
    return "" if found else NO_SOURCE
