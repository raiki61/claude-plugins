"""世界の解の抜き書きの照らしと検索語の検査（計画 docs/plans/2026-10-09-world-solution.md の 5.2 節の 1・4。構造の目の設計書
docs/specs/2026-09-29-structure-block-design.md の 5 節の「検索語の検査」と「抜き書きの照合」をこのブロックの照らしにした物）。

検索語の検査: 依頼の行から対象の識別子を集め、問題の類・作業の名・検索語・定石の文に現れたら名指す。上に上がって世界に聞く
（依頼の示した仕組みの部品でなく、作業の種類を問う）ための機械の歯止めで、「作業の言葉か」は見られない（見られるのは識別子だけ）。
識別子と見る物:
- 依頼の行の欄（where・text など字の欄の全部）の語のうち、識別子の形の物（_ . / - か数字を含む・小文字の後に大文字が続く。3 字以上で
  文字を含む）。/ を含む語はその段の識別子の形の物と、最後の段（ファイルの名）も足す。大文字とアンダースコアの名・ブロックの名・
  run の id はこの形に入る
- バッククォートで囲んだ字（2 字以上）
普通の語（作業の名・略語・フォルダの名）は識別子に数えない（問いの言葉を奪わない）。照らしは語の切れ目で、大小を問わない。

抜き書きの照らし: 役の取得の道具は本文を要約して返すので、役が見た字は原文の記録にならない。照らしは機械が同じ URL を取り直した
本文だけで行う。網に出してよい URL でない・取り直せない・答えが 2xx でない・本文に字のまま無い（正規化した後）・短い
（MIN_EXCERPT 字未満）抜き書きは落とす。同じ URL（# と末尾の / の違いは同じ）は 1 度だけ取り直す。取り直した全部が網に
届かなければ offline（網に出られない run。抜き書きの無い知識だけの道へ）。

- banned_tokens(findings) -> set[str]
- text_problems(text, banned) -> [当たった識別子]（名の順）
- normalize(body) -> str: HTML の札（script・style・注釈の中身ごと）を外し、文字の参照を戻し、NFKC・飾りの引用符と線の字の揃え・
  Markdown の飾りの字とリンクの形の外し・空白の詰め・大小の揃え
- verify(excerpts, get) -> {kept: [{id, class, url, excerpt}], dropped: [{class, url, why}], offline}: excerpts は
  [{class, url, excerpt}]（class は呼び手が付けた札で、そのまま運ぶ）、get(url) -> (状態の番号, 本文)（網に届かなければ
  webget.FetchError）
"""
from __future__ import annotations

import html
import pathlib
import re
import sys
import unicodedata
import urllib.parse

_CORE = pathlib.Path(__file__).resolve().parents[2] / ".shared" / "core"
if str(_CORE) not in sys.path:
    sys.path.insert(0, str(_CORE))
import webget  # noqa: E402  （網に出してよい URL と、網に届かない時の例外の住処）

MIN_EXCERPT = 20   # 抜き書きの字の下限（正規化の前の字数。短い字は本文のどこにでも在りうる）
WORD = re.compile(r"[A-Za-z0-9_.][A-Za-z0-9_./\-]*")
TICKED = re.compile(r"`([^`\n]{2,})`")
CAMEL = re.compile(r"[a-z][A-Z]")
DROP_BLOCKS = re.compile(r"<(script|style|noscript)\b[^>]*>.*?</\1\s*>|<!--.*?-->", re.S | re.I)
TAG = re.compile(r"<[^>]+>")
MD_LINK = re.compile(r"!?\[([^\]]*)\]\([^)]*\)")
MD_MARKS = str.maketrans({c: " " for c in "*`#>|"})
QUOTES = str.maketrans({"‘": "'", "’": "'", "‚": "'", "‛": "'", "“": '"', "”": '"', "„": '"', "‟": '"',
                        "–": "-", "—": "-", "―": "-", "‐": "-", "…": "..."})


# ---------------------------------------------------------------- 検索語の検査
def _shaped(tok: str) -> bool:
    """識別子の形か: 3 字以上で文字を含み、_ . / - か数字を含むか、小文字の後に大文字が続く"""
    return (len(tok) >= 3 and any(c.isalpha() for c in tok)
            and (any(c in "_./-" or c.isdigit() for c in tok) or CAMEL.search(tok) is not None))


def _tokens(text: str) -> set:
    out = set()
    for raw in WORD.findall(text):
        tok = raw.rstrip(".-/").split(":", 1)[0]
        if _shaped(tok):
            out.add(tok)
        if "/" in tok:
            parts = [p for p in tok.split("/") if p]
            out |= {p for p in parts if _shaped(p)}
            if parts and len(parts[-1]) >= 3:
                out.add(parts[-1])
    return out


def banned_tokens(findings) -> set:
    out = set()
    for f in findings if isinstance(findings, list) else []:
        if not isinstance(f, dict):
            continue
        for v in f.values():
            if isinstance(v, str):
                out |= _tokens(v)
                out |= {t.strip() for t in TICKED.findall(v) if t.strip()}
    return out


def text_problems(text, banned) -> list:
    text = text if isinstance(text, str) else ""
    return sorted(b for b in banned
                  if re.search(rf"(?<![A-Za-z0-9_]){re.escape(b)}(?![A-Za-z0-9_])", text, re.I))


# ---------------------------------------------------------------- 抜き書きの照らし
def normalize(body) -> str:
    text = body.decode("utf-8", "replace") if isinstance(body, (bytes, bytearray)) else str(body or "")
    text = TAG.sub(" ", DROP_BLOCKS.sub(" ", text))
    text = unicodedata.normalize("NFKC", html.unescape(text)).translate(QUOTES)
    text = MD_LINK.sub(r"\1", text).translate(MD_MARKS)
    return " ".join(text.split()).casefold()


def _same(url) -> str:
    """URL の比べの形（前後の空白・# から後・末尾の / を落とす）"""
    try:
        p = urllib.parse.urlsplit(str(url).strip())
    except ValueError:
        return str(url).strip()
    return urllib.parse.urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), p.query, ""))


def verify(excerpts, get) -> dict:
    bodies, reached, tried = {}, 0, 0
    kept, dropped = [], []

    def drop(row, why):
        dropped.append({"class": row.get("class"), "url": row.get("url"), "why": why})

    for row in excerpts if isinstance(excerpts, list) else []:
        if not isinstance(row, dict):
            continue
        url, text = row.get("url"), row.get("excerpt")
        if not isinstance(url, str) or not isinstance(text, str):
            drop(row, "url か excerpt が字でない")
            continue
        if len(text.strip()) < MIN_EXCERPT:
            drop(row, f"抜き書きが {MIN_EXCERPT} 字より短い")
            continue
        if not webget.safe_url(url):
            drop(row, "網に出してよい URL でない（https で公の名の host だけ）")
            continue
        key = _same(url)
        if key not in bodies:
            tried += 1
            try:
                status, body = get(url)
                reached += 1
                bodies[key] = (status, normalize(body))
            except webget.FetchError as e:
                bodies[key] = (None, f"取り直せない（{e}）")
            except ValueError as e:
                bodies[key] = (None, f"取り直せない（URL の形: {e}）")
        status, body = bodies[key]
        if status is None:
            drop(row, body)
        elif not 200 <= status < 300:
            drop(row, f"取り直しの答えが {status}")
        elif normalize(text) not in body:
            drop(row, "抜き書きが取り直した本文に無い（字のままでない・要約か言い換え）")
        else:
            kept.append({"id": f"x{len(kept) + 1}", "class": row.get("class"), "url": url, "excerpt": text})
    return {"kept": kept, "dropped": dropped, "offline": tried > 0 and reached == 0}
