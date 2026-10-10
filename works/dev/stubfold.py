"""筋書き（<工程>/fixtures/*.stubs.yaml）の共通の stub の置き場と、合わせ方。

  python3 works/dev/stubfold.py materialize <pack の dir>

筋書きの置き場に共通の基（BASE。筋書きと同じ形の「節の鍵 → stub」の写像。Archon は名が *.stubs.yaml の物だけを筋書きに読むので
基は読まない）が在れば、筋書き 1 本の stub は RFC 7386（JSON Merge Patch）の形の 1 つの決まりで合わせる:
- 基の鍵を基の並びで置き、筋書きが同じ鍵を持てば、両方の値が写像なら中を同じ決まりで鍵ごとに合わせ（入れ子のどの深さでも）、
  どちらかが写像でない（列・字・数・流れの形 {…}・[…]・| などの塊）なら筋書きの値で丸ごと置き替える
- 合わせる写像の中で筋書きの値が空（`鍵:`・null・~）の鍵は落とす（最上位なら、基に在ってもその筋書きでは stub しない節。
  入れ子なら、基の stub からその欄を外す）
- 筋書きにだけ在る鍵（筋書きの宣言 fixture を含む）は後ろに足す（値は元の字のまま。中の null も値として残る）
基が無ければ筋書きはそのまま。合わせはテキストで行い、鍵の塊（その字下げの `鍵:` の行と、続く深い行・その前の注記の行）を
元の字のまま並べる（模擬実行の読み手の解析をこちらの解析で置き替えない。葉の行は書き直さない）。同じ字下げの鍵の 2 度書き・
引用した鍵などの `鍵:` の形でない行・合わせる写像どうしの字下げの違いは拒む（ValueError）。

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


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _blocks(text, depth=0):
    """(頭の行の文字列, [塊], 末尾の注記・空行)。塊は {key, text, kind（null・map・leaf）, line（鍵の行まで）, body, child}。
    depth の字下げの `鍵:` の行で切る。塊の字は前の注記・空行と、鍵の行と続く深い行"""
    head, blocks, pending, cur = [], [], [], None
    for line in text.splitlines(keepends=True):
        bare = line.rstrip("\r\n")
        ind = _indent(bare)
        m = _KEY.match(bare[depth:]) if ind == depth else None
        if m:
            if cur is not None:
                blocks.append(cur)
            cur = {"key": m.group(1), "pre": pending, "line": line, "value": (m.group(2) or "").strip(), "body": []}
            pending = []
        elif bare.strip() == "" or (bare.lstrip().startswith("#") and ind <= depth):
            (pending if cur is not None else head).append(line)
        elif ind > depth or (ind == depth and cur is not None and (bare[depth:] == "-" or bare[depth:].startswith("- "))):
            if cur is None:
                raise ValueError(f"字下げ {depth} の鍵の前に中身の行がある: {line!r}")
            cur["body"].extend(pending + [line])
            pending = []
        else:
            raise ValueError(f"字下げ {depth} の行が `鍵:` の形でない（引用した鍵・字下げの違いなどは合わせない）: {line!r}")
    if cur is not None:
        blocks.append(cur)
    seen = set()
    for b in blocks:
        if b["key"] in seen:
            raise ValueError(f"字下げ {depth} の鍵 {b['key']} を 2 度書いている")
        seen.add(b["key"])
        b["text"] = "".join(b["pre"] + [b["line"]] + b["body"])
        _kind(b)
    return "".join(head), blocks, "".join(pending)


def _kind(b):
    """塊の値の種類: null（空）・map（字下げした写像）・leaf（それ以外。丸ごと置き替える）。map なら child に中の字下げ"""
    value = "" if b["value"].startswith("#") else b["value"]
    rows = [ln for ln in b["body"] if ln.strip() and not ln.lstrip().startswith("#")]
    b["child"] = None
    if value:
        b["kind"] = "null" if _NULL.match(value) and not rows else "leaf"
    elif not rows:
        b["kind"] = "null"
    elif rows[0].lstrip().startswith("- ") or rows[0].strip() == "-":
        b["kind"] = "leaf"
    else:
        b["kind"], b["child"] = "map", _indent(rows[0])


def _nl(s):
    return s if not s or s.endswith("\n") else s + "\n"


def _merge(base_text, own_text, depth):
    """1 つの字下げの写像どうしを合わせたテキスト（頭と尾は筋書きの物）"""
    _, base, _ = _blocks(base_text, depth)
    head, own, tail = _blocks(own_text, depth)
    mine = {b["key"]: b for b in own}
    parts = [_nl(head)]
    for b in base:
        o = mine.pop(b["key"], None)
        if o is None:
            parts.append(_nl(b["text"]))
        elif o["kind"] == "null":
            continue
        elif o["kind"] == "map" and b["kind"] == "map":
            if o["child"] != b["child"]:
                raise ValueError(f"鍵 {b['key']} の中の字下げが基（{b['child']}）と筋書き（{o['child']}）で違う")
            parts.append(_nl("".join(o["pre"] + [o["line"]])))
            parts.append(_nl(_merge("".join(b["body"]), "".join(o["body"]), o["child"])))
        else:
            parts.append(_nl(o["text"]))
    parts.extend(_nl(o["text"]) for o in own if o["key"] in mine and o["kind"] != "null")
    parts.append(tail)
    return "".join(parts)


def merge_text(base_text, scenario_text):
    """基と筋書きのテキストを合わせた筋書きのテキスト（頭は筋書きの頭）"""
    return _merge(base_text, scenario_text, 0)


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
        base.unlink()  # 基が残ると、合わせ済みの筋書きにもう一度 materialize した時に、空で落とした鍵が基から戻る。Archon が基を読むかは手元で確かめていない（読まないなら、消しても模擬実行は変わらない）
    return done


def main(argv):
    if len(argv) != 2 or argv[0] != "materialize":
        print("usage: stubfold.py materialize <pack の dir>", file=sys.stderr)
        return 2
    materialize(argv[1])
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
