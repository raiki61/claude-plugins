"""部品の置き場（scope）と宣言（manifest）の読み口（依頼 239）。層 L3。

部品（ブロック）が盤面で読み書きしてよいのは、自分の scope の根・宣言した入力（consumes）・宣言した出力（produces）の 3 つだけ。
宣言はブロックか線のフォルダごとの manifest.json（形の正本は同じ置き場の manifest.schema.json）。ここはそれを読んで照らし、
公開の名（scope の外の周の置き場 r<N>/ に置く名）と持ち主を引く口だけを持つ。まだどこにも配線しない（盤面を開く口へ繋ぐのは後の作業）。

- PACK: works の pack の根（blk-*/ と線のフォルダ＝nodes.json を持つフォルダの親）
- ManifestBroken(BoardGap): manifest が無い・読めない・形が合わない（パスと誤りの全部を文に載せる）
- manifest(owner_dir): 1 つの owner の manifest を読んで照らした dict
- manifests(pack): 全部の owner（blk-*/ と線のフォルダ）の名 → manifest
- published(pack): per_include でない produces の名（fnmatch の形を含む）の集合
- owner_of(name, pack): その名を per_include でなく出す owner（無ければ None）
- matches(name, pattern): "/" で区切った段ごとの fnmatch（* は段をまたがない。末尾の ** は 1 段以上の残りの全部）

名の形は段ごとに当てる（* が / をまたぐ fnmatch のままだと、rejects-*.json が rejects-a/b.json のような scope の下の私物まで
公開の名に数える）。形の字は manifest を読む時に照らす: 空の段・"."・".."・頭の "/" を持たず、** は末尾の段そのものだけ。
"""
from __future__ import annotations

import fnmatch
import json
import pathlib
import sys

_CORE = pathlib.Path(__file__).resolve().parent
_GL = _CORE / "graphloops"
if str(_GL) not in sys.path:
    sys.path.insert(0, str(_GL))

from board import BoardGap  # noqa: E402
from engine.schema import validate_schema  # noqa: E402

PACK = _CORE.parents[1]                       # works/（.shared/core の 2 つ上）
MANIFEST = "manifest.json"                    # owner のフォルダの宣言のファイル
SCHEMA_PATH = _CORE / "manifest.schema.json"  # manifest の形の正本
BLOCK_GLOB = "blk-*"                          # ブロックのフォルダ
LINE_MARK = "nodes.json"                      # 線のフォルダの印（tests/test_layers の L7 と同じ見分け）
ANY_BELOW = "**"                              # 名の形の末尾の段だけに置ける「下の全部」


class ManifestBroken(BoardGap):
    """manifest が無い・読めない・形が合わない・owner がフォルダの名と違う。文にパスと誤りの全部を載せる"""


def matches(name: str, pattern: str) -> bool:
    """name が pattern に当たるか（"/" で区切った段ごとの fnmatchcase。末尾の ** は 1 段以上の残りの全部）"""
    segs, pats = name.split("/"), pattern.split("/")
    if pats[-1] == ANY_BELOW:
        pats = pats[:-1]
        if len(segs) <= len(pats):
            return False
        segs = segs[:len(pats)]
    return len(segs) == len(pats) and all(fnmatch.fnmatchcase(s, p) for s, p in zip(segs, pats))


def _name_errors(name: str, where: str) -> list[str]:
    """名の形の誤り（空の段・"."・".."・頭の "/"・"\\"・末尾の段そのものでない **）"""
    segs = name.split("/")
    bad = name.startswith("/") or "\\" in name or any(s in ("", ".", "..") for s in segs) \
        or any(ANY_BELOW in s and (s != ANY_BELOW or i != len(segs) - 1) for i, s in enumerate(segs))
    return [f"{where}: 名の形 {name!r} が使えない（/ で区切った段に空・.・.. を持たず、** は末尾の段そのものだけ）"] if bad else []


def _conditions(value, schema: dict, path: str = "$") -> list[str]:
    """validate_schema が見ない allOf の if／then を当てた誤り（manifest.schema.json の条件。properties と items の下も辿る）"""
    errs = []
    for c in schema.get("allOf", []):
        if "if" in c and not validate_schema(value, c["if"], path):
            errs += validate_schema(value, c.get("then", {}), path)
    if isinstance(value, dict):
        for k, s in schema.get("properties", {}).items():
            if k in value:
                errs += _conditions(value[k], s, f"{path}.{k}")
    if isinstance(value, list) and "items" in schema:
        for i, v in enumerate(value):
            errs += _conditions(v, schema["items"], f"{path}[{i}]")
    return errs


def _schema() -> dict:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def manifest(owner_dir: pathlib.Path) -> dict:
    """owner_dir/manifest.json を読み、manifest.schema.json と名の形と owner の名と schema のファイルに照らした dict。
    無い・読めない・合わないは ManifestBroken（パスと誤りの全部）"""
    owner_dir = pathlib.Path(owner_dir)
    path = owner_dir / MANIFEST
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, ValueError) as e:
        raise ManifestBroken(f"manifest {path} が読めない: {type(e).__name__}: {e}") from None
    schema = _schema()
    errs = validate_schema(doc, schema) + _conditions(doc, schema)
    if isinstance(doc, dict):
        if doc.get("owner") != owner_dir.name:
            errs.append(f"$.owner: {doc.get('owner')!r} がフォルダの名 {owner_dir.name!r} と違う")
        seen = set()
        for key in ("consumes", "produces"):
            rows = doc.get(key)
            for i, row in enumerate(rows if isinstance(rows, list) else []):
                name = row.get("name") if isinstance(row, dict) else None
                if not isinstance(name, str):
                    continue
                errs += _name_errors(name, f"$.{key}[{i}].name")
                if key == "produces":
                    if name in seen:
                        errs.append(f"$.produces[{i}].name: {name!r} を 2 度宣言している")
                    seen.add(name)
                    rel = row.get("schema")
                    if isinstance(rel, str):   # core が書く形（reads-<役>.json など）は core の Schema を owner から指す
                        target = (owner_dir / rel).resolve()
                        if not (target.is_relative_to(owner_dir.resolve().parent) and target.is_file()):
                            errs.append(f"$.produces[{i}].schema: {rel!r} が pack の下のファイルでない（{owner_dir} から）")
    if errs:
        raise ManifestBroken(f"manifest {path} が合わない:\n" + "\n".join(f"  - {e}" for e in errs))
    return doc


def _owner_dirs(pack: pathlib.Path) -> list[pathlib.Path]:
    pack = pathlib.Path(pack)
    blocks = [p for p in pack.glob(BLOCK_GLOB) if p.is_dir()]
    lines = [p.parent for p in pack.glob(f"*/{LINE_MARK}")]
    return sorted(set(blocks) | set(lines))


def manifests(pack: pathlib.Path = PACK) -> dict[str, dict]:
    """pack の全部の owner（blk-*/ と nodes.json を持つ線のフォルダ）の名 → manifest。壊れた物が在れば、全部の文を 1 つの
    ManifestBroken に並べる"""
    out, broken = {}, []
    for d in _owner_dirs(pack):
        try:
            out[d.name] = manifest(d)
        except ManifestBroken as e:
            broken.append(str(e))
    if broken:
        raise ManifestBroken("\n".join(broken))
    return out


def published(pack: pathlib.Path = PACK) -> frozenset[str]:
    """per_include でない produces の名（形を含む）の和。盤面の公開の置き場 r<N>/ に置く名"""
    return frozenset(p["name"] for m in manifests(pack).values() for p in m["produces"] if not p.get("per_include"))


def owner_of(name: str, pack: pathlib.Path = PACK) -> str | None:
    """name を per_include でなく出す owner（どの produces の形にも当たらなければ None）。2 つの owner の形に当たれば
    ManifestBroken（持ち主は 1 つ）"""
    hits = sorted({owner for owner, m in manifests(pack).items() for p in m["produces"]
                   if not p.get("per_include") and matches(name, p["name"])})
    if len(hits) > 1:
        raise ManifestBroken(f"名 {name!r} を 2 つ以上の owner が公開の名に宣言している: {', '.join(hits)}")
    return hits[0] if hits else None
