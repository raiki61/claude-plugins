"""筋書き（<工程>/fixtures/*.stubs.yaml）の共通の stub の置き場と、合わせ方。

  python3 works/dev/stubfold.py materialize <pack の dir>

筋書きの置き場に共通の基（BASE。筋書きと同じ形の「節の鍵 → stub」の写像。Archon は名が *.stubs.yaml の物だけを筋書きに読むので
基は読まない）が在れば、筋書き 1 本の stub は次の 1 つの決まりで合わせる:
- 基の鍵を基の並びで置き、筋書きが同じ鍵を持てば筋書きの値で丸ごと置き替える（入れ子の中は合わせない）
- 筋書きの値が空（`鍵:`・null・~）の鍵は落とす（基に在っても、その筋書きでは stub しない節。本物で回す節など）
- 筋書きにだけ在る鍵（筋書きの宣言 fixture を含む）は後ろに足す
基が無ければ筋書きはそのまま。合わせはテキストで行い、鍵の塊（頭の桁の `鍵:` の行と、続く字下げの行・その前の注記の行）を
元の字のまま並べる（模擬実行の読み手の解析をこちらの解析で置き替えない）。頭の桁の鍵の 2 度書きは拒む。

materialize は模擬実行に渡す前の写し（dev/mktarget.sh が写した pack）で、基の在る置き場の筋書きを合わせた物に書き替え、基を消す。
試験は load（合わせた stub を解析して返す。解析は試験の側の YAML の道具）で筋書きを読む。標準ライブラリだけを使う（load の解析を除く）。
"""
from __future__ import annotations

import pathlib
import re
import sys

BASE = "base.yaml"
SUFFIX = ".stubs.yaml"
_KEY = re.compile(r"^([A-Za-z0-9_][A-Za-z0-9_.-]*):(?:[ \t]+(.*))?$")
_NULL = re.compile(r"^(?:null|~|Null|NULL)?[ \t]*(?:#.*)?$")


def _blocks(text):
    """(頭の行の文字列, [(鍵, 塊の文字列, 空か)], 末尾の注記・空行)。塊は前の注記・空行と、鍵の行と続く字下げの行"""
    head, blocks, pending, cur = [], [], [], None
    for line in text.splitlines(keepends=True):
        m = _KEY.match(line.rstrip("\r\n"))
        if m:
            if cur is not None:
                blocks.append(cur)
            cur = {"key": m.group(1), "lines": pending + [line], "value": m.group(2) or "", "body": False}
            pending = []
        elif line.strip() == "" or line.startswith("#"):
            (pending if cur is not None else head).append(line)
        else:
            if cur is None:
                raise ValueError(f"頭の桁の鍵の前に中身の行がある: {line!r}")
            cur["lines"].extend(pending + [line])
            cur["body"] = cur["body"] or not line.lstrip().startswith("#")
            pending = []
    if cur is not None:
        blocks.append(cur)
    out, seen = [], set()
    for b in blocks:
        if b["key"] in seen:
            raise ValueError(f"頭の桁の鍵 {b['key']} を 2 度書いている")
        seen.add(b["key"])
        out.append((b["key"], "".join(b["lines"]), not b["body"] and bool(_NULL.match(b["value"]))))
    return "".join(head), out, "".join(pending)


def _nl(s):
    return s if not s or s.endswith("\n") else s + "\n"


def merge_text(base_text, scenario_text):
    """基と筋書きのテキストを合わせた筋書きのテキスト（頭は筋書きの頭）"""
    _, base, _ = _blocks(base_text)
    head, own, tail = _blocks(scenario_text)
    mine = {k: (b, empty) for k, b, empty in own}
    parts = [_nl(head)]
    for key, block, _ in base:
        if key in mine:
            block, empty = mine.pop(key)
            if empty:
                continue
        parts.append(_nl(block))
    parts.extend(_nl(b) for k, b, empty in own if k in mine and not empty)
    parts.append(tail)
    return "".join(parts)


def text(path):
    """筋書き path の合わせたテキスト（置き場に基が無ければ筋書きのまま）"""
    path = pathlib.Path(path)
    own = path.read_text(encoding="utf-8")
    base = path.parent / BASE
    return merge_text(base.read_text(encoding="utf-8"), own) if base.is_file() else own


def load(path):
    """筋書き path の合わせた stub（解析した写像）"""
    import yaml
    return yaml.safe_load(text(path)) or {}


def materialize(pack):
    """pack の下の基の在る筋書きの置き場ごとに、筋書きを合わせたテキストに書き替えて基を消す。書き替えた筋書きのパスの一覧"""
    done = []
    for base in sorted(pathlib.Path(pack).glob(f"**/fixtures/{BASE}")):
        for p in sorted(base.parent.glob(f"*{SUFFIX}")):
            merged = text(p)
            p.write_text(merged, encoding="utf-8")
            done.append(p)
        base.unlink()
    return done


def main(argv):
    if len(argv) != 2 or argv[0] != "materialize":
        print("usage: stubfold.py materialize <pack の dir>", file=sys.stderr)
        return 2
    materialize(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
