"""GitHub の発言と値を読む共通部。/whose-turn・/catchup・/what-am-i-doing で共用。

同じ読み方を各スクリプトに書いていたとき、片方だけ直って食い違った（@名前 の当て方が catchup だけ
緩く、`@bob` が `@bob-smith` にも当たっていた。2026-10-19 の見渡し）。読み方はここに 1 つだけ置く。
"""

# この本文は複数のプラグインに写しで在る。正本は attention/scripts/lib/ghtext.py、写しは works-dispatch/dispatch/vendor/lib/ghtext.py。
# 直すのは正本だけで、配るのは python3 scripts/shared-copies.py --sync attention/scripts/lib/ghtext.py。

import re

# CheckRun.conclusion のうち、終わっていて赤ではないもの。CANCELLED / STALE は新しい push に打ち切られた
# 実行で、作者が直すものではない。未知の値は赤に倒す（CI の結論は増える。知らない値を緑に倒すと、増えた
# 瞬間に検査が黙って甘くなる）。実行中（PENDING・空）をどう数えるかは呼ぶ側で決める
DONE_NOT_RED = frozenset({"SUCCESS", "NEUTRAL", "SKIPPED", "EXPECTED", "CANCELLED", "STALE"})


def is_bot(actor):
    """GraphQL の actor が Bot か。login の形（`[bot]` の末尾など）では見分けない。"""
    return (actor or {}).get("__typename") == "Bot"


# GFM のコードブロックの囲みは ``` と ~~~ の両方。行の頭（字下げ 3 つまで）で開き、開いた囲みと同じ文字で閉じる。
# 行の頭に限らないと、文の中の 2 つの ~~~（ありがとう~~~）の間を消す
_FENCE = re.compile(r"^[ ]{0,3}(`{3,}|~{3,}).*?^[ ]{0,3}\1", re.S | re.M)
_INLINE = re.compile(r"`[^`\n]*`")
_QUOTE = re.compile(r"^[ \t]*>.*$", re.M)
_LINK = re.compile(r"\[([^\]]*)\]\([^)]*\)")
# GitHub の login は英数字とハイフン。メールアドレスの @ と @org/team は除く。末尾の lookahead が無いと
# @org/team を org/tea... まで後退して拾い、@bob-smith を @bob と読む
_MENTION = re.compile(
    r"(?<![A-Za-z0-9_.@/])@([A-Za-z0-9][A-Za-z0-9_-]*)(?![A-Za-z0-9_/-])"
)
# 本文の中の #番号。直前が ASCII の英数字か / & . - のもの（URL の fragment、word#12、&#123; の文字参照）は
# 番号ではない。ただし PR#12・issue#12 は人がよく書く形なので拾う。日本語の直後（対応は#12）も拾う——
# \w で見ると日本語の文字も英数字に数えて落とす
_REF = r"(?:(?<=PR)|(?<=pr)|(?<=issue)|(?<=Issue)|(?<![A-Za-z0-9_/&.-]))#(\d{1,7})(?!\d)"
_REF_RE = re.compile(_REF)


def clean(text):
    """呼びかけと参照を数える用。コードブロック・インラインコード・引用を落とし、リンクは表示の文字だけ残す。
    コードの中の @name や #12 を呼びかけ・参照に数えない。"""
    return _LINK.sub(r"\1", _QUOTE.sub("", _INLINE.sub("", _FENCE.sub("", text or ""))))


def readable(text):
    """材料として読む用。引用（>）とコードブロックだけ落とし、インラインコードは残す。

    clean() はインラインコードまで落とす——材料で同じことをすると、指摘の主語（ファイル名・
    コミット SHA・設定キー）が消えて「を新設しました」だけが残り、読んでも何の話か判定できない。"""
    return " ".join(
        _LINK.sub(r"\1", _QUOTE.sub("", _FENCE.sub("", text or ""))).split()
    )


def mentions(text):
    """本文が呼びかけている login の集合（コード・引用の中は数えない）。"""
    return set(_MENTION.findall(clean(text)))


def mentioned(text, who):
    """本文が who を呼びかけているか。GitHub の login は大文字小文字を区別しない（@Bob は bob を呼んでいる）"""
    return bool(who) and who.casefold() in {m.casefold() for m in mentions(text)}


def refs(text):
    """本文が # で指す番号を、出た順・重複なしで返す（コード・引用の中は数えない）。"""
    return list(dict.fromkeys(int(n) for n in _REF_RE.findall(clean(text))))


def repo_refs(text, repo):
    """本文が指す自リポジトリの issue / PR の番号。`#12` と、自リポジトリの完全 URL の両方を数える。

    URL は自リポジトリのものだけ——他所の URL を拾うと番号空間が重なって別物を指す
    （実測 2026-08-23・#1424: argoproj/argo-cd の issues/7673 を自分の 7673 として拾っていた）。"""
    url = re.compile(re.escape(repo) + r"/(?:issues|pull)/(\d{1,7})(?!\d)")
    body = clean(text)
    return {int(n) for n in _REF_RE.findall(body)} | {int(n) for n in url.findall(body)}
