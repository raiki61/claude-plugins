"""モデル名の揃え。曖昧な照合はしない（違うモデルの値段を拾うと、自動の判断がずれるため）。"""
import json
import re
from typing import Iterable, Optional

_BRACKET = re.compile(r"\[[^\]]*\]$")
_VERSION = re.compile(r"-v\d+(:\d+)?$")
_DATE = re.compile(r"-\d{8}$")


def normalize(name: str) -> str:
    """記録に書かれた名前を値段表の名前に揃える。

    小文字にし、末尾の `[…]` を削り、`claude-` より前（`us.anthropic.` などの前置き）を削り、`.` と `@` を `-` に替え、
    末尾の版（`-v1:0`）と日付（`-20261001`）を削る。
    """
    n = _BRACKET.sub("", name.strip().lower())
    i = n.find("claude-")
    if i > 0:
        n = n[i:]
    n = n.replace(".", "-").replace("@", "-")
    for _ in range(2):  # 日付と版は、どちらの順で付いていても削る
        n = _VERSION.sub("", _DATE.sub("", n))
    return n


def parse_aliases(text: Optional[str]) -> dict:
    """環境変数 RENT_OR_BUY_MODEL_ALIASES を表にする。`名前=モデル` のカンマ区切りか JSON。形が違えば ValueError。"""
    if not text or not text.strip():
        return {}
    text = text.strip()
    if text.startswith("{"):
        table = json.loads(text)
        if not isinstance(table, dict) or not all(isinstance(v, str) for v in table.values()):
            raise ValueError("the alias JSON must map a name to a model name (string)")
        return table
    table = {}
    for pair in text.split(","):
        key, sep, value = pair.partition("=")
        if not sep or not key.strip() or not value.strip():
            raise ValueError("an alias entry must look like name=model: %r" % pair)
        table[key.strip()] = value.strip()
    return table


def resolve(name: str, known: Iterable[str], aliases: Optional[dict] = None) -> Optional[str]:
    """値段表の名前を返す。使う人の対応表でそのまま引き、揃えた名前で値段表と対応表を引く。引けなければ None。"""
    known, aliases = set(known), aliases or {}
    if name in aliases:
        name = aliases[name]
    for cand in (name, normalize(name)):
        if cand in known:
            return cand
        if cand in aliases and normalize(aliases[cand]) in known:
            return normalize(aliases[cand])
    return None
