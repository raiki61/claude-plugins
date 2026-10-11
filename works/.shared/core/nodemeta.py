"""節ごとの読み書きの宣言（`_meta`）の形と、Archon に渡す前に YAML から落とす口。層 L1（works の物を何も知らない）。標準ライブラリだけ。

宣言は工程の YAML の節の隣に置く: `_meta: {reads: [...], writes: [...]}`。要素は 2 種類:
- file:<型>  run の置き場（ARTIFACTS_DIR。盤面はその下の board/）からの相対パスの型。"/" で区切った段ごとの fnmatch
  （* は段をまたがない。末尾の ** は下の全部。盤面の名の当て方 board.name_matches と同じ）
- record:<record|state>.<欄の道>  盤面の共有の記録（board/record.json・board/state.json）の欄
入力（with:）で受けたパスの読みは線の配線が宣言しているので書かない。書きは全部書く。照らす口は scopes.node_io_gaps。

Archon v0.11.1 は節の知らない鍵を落として node_unknown_key_ignored の警告を出す（loader.ts の collectUnknownNodeKeys）。
pack を対象へ写す 1 つの口（dev/lib.sh の works_dev_copy_pack）がこのモジュールの strip で `_meta` を落としてから Archon に渡す。
地図の元（graphmap）の sources の指紋は strip した字から取る（写しと元で同じ指紋になる）。

- KEY・FIELDS・RECORDS: 宣言の鍵の名・2 つの並びの名・record: の頭に置ける共有の記録のファイルの名
- strip(text) -> str: YAML の字から `_meta` の鍵（引用した形も）を下の行ごと落とす。節の鍵に限らずどこの `_meta` も落とす
  （works の予約の鍵）。塊の字 `|`・`>` と行をまたぐ引用の字（値が `"`・`'` で始まる素の鍵の行。流れの列の中・引用した鍵・
  タグやアンカーの付いた値は見分けない）の中の字は落とさない。宣言の塊の中の空行とコメントの行は字下げを
  見ず、次の字の在る行が宣言の下なら一緒に落とす。`_meta` を持たない字はバイトのまま返す。節の最初の鍵
  （`- _meta:`）は ValueError
- parse(raw, where) -> {"reads": [...], "writes": [...]}: 宣言の形を確かめて返す（違えば ValueError。where は文の名指し）
- python3 nodemeta.py strip <pack>: pack の直下の <d>/<d>.yaml を strip で書き直す
"""
from __future__ import annotations

import pathlib
import re
import sys

KEY = "_meta"
FIELDS = ("reads", "writes")
KINDS = ("file", "record")
RECORDS = ("record", "state")   # 盤面の共有の記録のファイル（board/<名>.json）
RECORD_FIELD = re.compile(r"(?:" + "|".join(RECORDS) + r")(?:\.[A-Za-z0-9_-]+)+")   # record:<record|state>.<欄の道>
_META_LINE = re.compile(r"""(["']?)""" + KEY + r"\1\s*:")   # 引用した鍵も同じ鍵
_SCALAR_HEAD = re.compile(r":\s*[|>][-+0-9]*\s*(?:#.*)?$")   # 塊の字の頭（key: | や key: >-）
_ITEM_SCALAR = re.compile(r"-\s+[|>][-+0-9]*\s*(?:#.*)?$")   # 列の要素の塊の字の頭（- |）
_QUOTE_HEAD = re.compile(r"""(?:-\s+)?(?:[^\s"'#][^#]*?:\s+)?(["'])(.*)""")   # 値が引用の字で始まる行（鍵: "… や - '…）


def _indent(line: str) -> int:
    return len(line) - len(line.lstrip(" "))


def _quiet(line: str) -> bool:
    """字の無い行（空行か、字だけのコメントの行）。宣言の塊の中では字下げを見ない"""
    body = line.strip()
    return not body or body.startswith("#")


def _closes(text: str, quote: str) -> bool:
    """引用の字 quote が text の中で閉じるか（"…" は \\ の逃がしを、'…' は '' の 2 度書きを飛ばす）"""
    i = 0
    while i < len(text):
        c = text[i]
        if quote == '"' and c == "\\":
            i += 2
            continue
        if c == quote:
            if quote == "'" and text[i + 1:i + 2] == "'":
                i += 2
                continue
            return True
        i += 1
    return False


def strip(text: str) -> str:
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    scalar = None   # 塊の字の持ち主の鍵の字下げ（その中に居る間）
    quote = None    # 行をまたぐ引用の字の印（その中に居る間）
    i = 0
    while i < len(lines):
        line = lines[i]
        body = line.strip()
        ind = _indent(line)
        if quote is not None:
            out.append(line)
            i += 1
            if _closes(body, quote):
                quote = None
            continue
        if scalar is not None:
            if not body or ind > scalar:
                out.append(line)
                i += 1
                continue
            scalar = None
        if body.startswith("- ") and _META_LINE.match(body[2:].lstrip()):
            raise ValueError(f"{i + 1} 行目: {KEY} を節の最初の鍵に置かない（落とすと節の頭が消える）")
        if _META_LINE.match(body):
            i += 1
            while i < len(lines):
                if not _quiet(lines[i]):
                    if _indent(lines[i]) <= ind:
                        break
                    i += 1
                    continue
                j = i   # 空行・コメントの行: 次の字の在る行が宣言の下なら一緒に落とす
                while j < len(lines) and _quiet(lines[j]):
                    j += 1
                if j < len(lines) and _indent(lines[j]) > ind:
                    i = j
                    continue
                break
            continue
        if _ITEM_SCALAR.fullmatch(body):
            scalar = ind
        elif _SCALAR_HEAD.search(body):
            scalar = ind + (2 if body.startswith("- ") else 0)
        else:
            m = _QUOTE_HEAD.fullmatch(body)
            if m and not _closes(m.group(2), m.group(1)):
                quote = m.group(1)
        out.append(line)
        i += 1
    return "".join(out)


def parse(raw, where: str) -> dict:
    if not isinstance(raw, dict) or set(raw) != set(FIELDS):
        raise ValueError(f"{where}: {KEY} は reads と writes の 2 つの鍵だけを持つ（受けた値: {raw!r}）")
    out = {}
    for field in FIELDS:
        items = raw[field]
        if not isinstance(items, list):
            raise ValueError(f"{where}: {KEY}.{field} が並びでない")
        for item in items:
            kind, sep, body = item.partition(":") if isinstance(item, str) else ("", "", "")
            if not sep or kind not in KINDS or not body:
                raise ValueError(f"{where}: {KEY}.{field} の {item!r} が file:<型> か record:<record|state>.<欄> でない")
            if kind == "record" and not RECORD_FIELD.fullmatch(body):
                raise ValueError(f"{where}: {KEY}.{field} の {item!r} は record:<record|state>.<欄の道> の形でない")
        if len(set(items)) != len(items):
            raise ValueError(f"{where}: {KEY}.{field} に同じ要素が 2 度ある")
        out[field] = list(items)
    return out


def main(argv) -> int:
    if len(argv) != 2 or argv[0] != "strip":
        print("usage: nodemeta.py strip <pack>", file=sys.stderr)
        return 2
    for p in sorted(pathlib.Path(argv[1]).glob("*/*.yaml")):
        if p.stem != p.parent.name:
            continue
        text = p.read_text(encoding="utf-8")
        try:
            done = strip(text)
        except ValueError as e:
            print(f"nodemeta.py: {p}: {e}", file=sys.stderr)
            return 1
        if done != text:
            p.write_text(done, encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
