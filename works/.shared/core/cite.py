"""名指しの出どころが現物に在るかの確かめ（食い違いの申し出の引用の照らしと、修正前の関所の決め手の出どころの照らしが使う 1 か所）。

- CITE: 名指し `<パス>:<行>` か `<パス>:<行>-<行>` の形
- inside(p, root): p が root の中か
- problem(cite, repo, roots=()) -> str: 1 つの名指しの確かめ（通れば空）。相対のパスは作業ツリーの根から（外と .git は拒む）、
  絶対のパスは作業ツリーの中か roots（依頼のファイル・盤面の置き場）の中だけ。ファイルが在り、行がその中に在る
- flat(s) -> str: 空白の並び（改行・タブ・連続する空白）を 1 つの空白に寄せ、色の制御文字（ESC[…m）を除いた文
- quoted_in(quote, text) -> bool: 引いた文 quote が text の中に、flat で寄せた後の部分一致で在るか（空の引用は偽）。
  テストの赤の引用が結末の失敗の文に在るかの照らしが使う（実行器の出力は改行・色の付き方が回ごとに違いうる）
- sources_problem(text, repo, roots=(), quoted="") -> str: 決め手の文（decided_by）の出どころの確かめ（通れば空）。文の中の
  URL（http・https。形だけ見る。取りに行かない）・名指し `<パス>:<行>`（problem）・作業ツリーの中のパス（/ を含むか拡張子を持つ語で、
  在るファイル。フォルダだけは出どころに数えない）・依頼の引用「…」（文に「依頼」の語が在る時だけ。quoted＝依頼の文の中に字のまま
  在る）のどれかが 1 つ以上在り、書いた物が全部現物に在る時だけ通る。どれも無ければ「出どころが現物に無い」。
  パスの形でない名指し（時刻 12:30 など。パスの部分に / も拡張子も無い）は名指しに数えない
- ref_problem(source, prefix, known) -> list[str]: 出どころの文の中の prefix で始まる参照（頭に字が添えてあってもよい）の id が、
  呼び手が渡した実在の id の組 known に在るかの照らし。無い id ごとに誤りの 1 文（prefix の語が無ければ空）

- CITE_IN_WHERE: 場所の文の中の名指し 1 つ分の形（CITE の錨を外した物。パスは空でもよい）
- where_cites(where) -> [(パス, 始め, 終わり)]: 場所の文の中の名指しを順に返す。パスの無い `:<行>` は直前のパス、直前が無ければ空
- lead_path(text) -> str: 場所の文（「x.py:12（…）」「x.py の docstring」）の頭のパス。パスの形でなければ空

標準ライブラリだけ。works の物を何も import しない（読み手が多いので輪を作らない）。
"""
from __future__ import annotations

import pathlib
import re

CITE = re.compile(r"^(?P<path>.+?):(?P<a>[1-9][0-9]*)(?:-(?P<b>[1-9][0-9]*))?$")
CITE_IN_WHERE = re.compile(r"(?P<path>[^\s:：（()、,]*):(?P<a>[1-9][0-9]*)(?:-(?P<b>[1-9][0-9]*))?")
URL = re.compile(r"https?://[^\s）)」』、。,]+")
QUOTE = re.compile(r"「([^」]{4,})」")
TOKEN = re.compile(r"/?[A-Za-z0-9_.][A-Za-z0-9_./-]*(?::[1-9][0-9]*(?:-[1-9][0-9]*)?)?")
REQUEST_WORD = "依頼"   # 引用「…」を依頼の文と照らすのは、この語が文に在る時だけ（出典の文書の引用は照らさない）
ANSI = re.compile(r"\x1b\[[0-9;]*m")
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


def where_cites(where) -> list:
    """場所の文の中の名指しを順に [(パス, 始め, 終わり)] で返す（始め・終わりは字。終わりの無い名指しは None）。
    パスの無い `:<行>` は直前の名指しのパス、直前が無ければパスは空"""
    out, last = [], ""
    for m in CITE_IN_WHERE.finditer(where):
        last = m["path"] or last
        out.append((last, m["a"], m["b"]))
    return out


def lead_path(text: str) -> str:
    """場所の文（「works/x.py:12（…）」「works/x.py の docstring」）の頭のパス。最初の空白か「（」までの字から、最初の「:」の前。
    パスの形（/ か . を持つ）でなければ空"""
    head = str(text or "").strip().split(None, 1)[0] if str(text or "").strip() else ""
    head = head.split("（", 1)[0].split(":", 1)[0]
    return head if "/" in head or "." in head else ""


def flat(s) -> str:
    """空白の並びを 1 つの空白に寄せ、色の制御文字（ESC[…m）を除く。文字列でなければ空"""
    return " ".join(ANSI.sub("", s).split()) if isinstance(s, str) else ""


def quoted_in(quote, text) -> bool:
    """引いた文 quote が text の中に、flat で寄せた後の部分一致で在るか（寄せて空になる引用は偽）"""
    q = flat(quote)
    return bool(q) and q in flat(text)


def _pathish(word: str) -> bool:
    last = word.rsplit("/", 1)[-1]
    return ("/" in word or bool(re.fullmatch(r"[^.]+\.[A-Za-z][A-Za-z0-9]{0,5}", last))) and not word.startswith(".") \
        and not word.startswith("/")


def sources_problem(text, repo, roots=(), quoted: str = "") -> str:
    if not isinstance(text, str) or not text.strip():
        return NO_SOURCE
    found, bad = 0, []
    rest = URL.sub(" ", text)
    found += len(URL.findall(text))
    if REQUEST_WORD in rest:
        for q in QUOTE.findall(rest):
            found += 1
            if q.strip() not in quoted:
                bad.append(f"依頼の引用「{q}」が依頼の文に無い")
    rest = QUOTE.sub(" ", rest)
    repo_p = pathlib.Path(repo).resolve()
    for word in TOKEN.findall(rest):
        word = word.rstrip(".")
        m = CITE.match(word)
        if m and (_pathish(m["path"]) or m["path"].startswith("/")):
            found += 1
            got = problem(word, repo_p, roots)
            if got:
                bad.append(got)
        elif not m and _pathish(word):
            p = (repo_p / word).resolve()
            if inside(p, repo_p) and p.is_file():
                found += 1
    if bad:
        return "決め手の出どころが現物に無い: " + " / ".join(bad)
    return "" if found else NO_SOURCE


def ref_problem(source, prefix, known) -> list:
    """出どころの文（source）の中の prefix で始まる参照（頭に字が添えてあってもよい）の id を、呼び手が渡した実在の id の組（known）と
    照らす。無い id ごとに誤りの 1 文を返す（prefix の語が無ければ空）。頭の字と id の組は、この住処が works の物を知らないよう呼び手が渡す"""
    if not isinstance(source, str):
        return []
    ids = dict.fromkeys(re.findall(re.escape(prefix) + r"([A-Za-z0-9][A-Za-z0-9_-]*)", source))
    return [f"{prefix}{i} が実在の行を指さない" for i in ids if i not in known]
