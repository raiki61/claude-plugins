"""役の節の印（works-node）。

役の節の output_format（JSON Schema）の一番上の description に 1 行 `works-node: <名>[ continue=<名>][ <flag>…]` を置く。
Archon の SDK は output_format を claude の argv の `--json-schema` にそのまま載せるので、包み（.shared/adapter）は
argv だけでどの節の起動かを見分けられる（仕様 3.7・5.1、裁定 TA20）。description は JSON Schema の注記なので、
返答の型の検査には効かない。graph の schema（role_schema）の一番上は description を持たない。

- 名と continue の値は [a-z0-9-]+ だけ。flag は FLAGS に在る物だけ
- 見分けられない物（大文字・空の値・知らない flag・同じ語の重なり・余分な空白や改行）は印でないと見なす（parse が None）。
  包みは印の無い起動に触らないので、読み違えて別の節として扱うより素通しの方が安全
- mark は parse が読めない印を作らない（ValueError）
"""
import copy
import json
import re

PREFIX = "works-node: "
# no-post: gh の書き込みの語を包みの柵に足す（並行 PR の任せ先の役。仕様 3.8）。
# no-tree-write: 包みが役の cwd の worktree の根を柵に足し、sandbox・切符の無い起動を拒む（CI の任せ先の役。裁定 R56）。
# isolated: 包みが道具ゼロの役を Git の外の置き場で起こす（独立の目の blind-judge。graphloops の commands._isolated_cwd）。
# self-resume: SDK が前の会話を継ぐ起動では、包みが SDK の会話でなくこの節自身が記録した会話を継ぐ（輪の中に別の会話を継ぐ
# AI の節が挟まる役。修正役と範囲の相談の答えの節。docs/plans/2026-10-06-ask-planner.md）
# lane: 包みが役を枝の単位の worktree を cwd に起こす（TDD の輪の並べの枝の役 tdd-lane-<n>。adapter.py の頭の 6c）
# map: 包みが工程の地図（graphmap。全体のグラフとこの節の会話の居場所）を system prompt に足す（adapter.py の頭の 13 の差し込みの表）
FLAGS = frozenset({"no-post", "no-tree-write", "isolated", "self-resume", "lane", "map"})
_NAME = re.compile(r"[a-z0-9-]+")
_CONT = "continue="
_ARG = "--json-schema"


def _name_ok(s):
    return isinstance(s, str) and _NAME.fullmatch(s) is not None


def parse(description):
    """印の description を {"name", "cont", "flags"} に読む。印でなければ None"""
    if not isinstance(description, str) or not description.startswith(PREFIX):
        return None
    words = description[len(PREFIX):].split(" ")
    name, rest = words[0], words[1:]
    if not _name_ok(name):
        return None
    cont, flags = None, set()
    for w in rest:
        if w.startswith(_CONT):
            if cont is not None or not _name_ok(w[len(_CONT):]):
                return None
            cont = w[len(_CONT):]
        elif w in FLAGS and w not in flags:
            flags.add(w)
        else:
            return None
    return {"name": name, "cont": cont, "flags": frozenset(flags)}


def mark(schema, name, *, cont=None, flags=()):
    """schema の写しの一番上の description に印を置いて返す。元の description が在れば ValueError"""
    if "description" in schema:
        raise ValueError(f"schema の一番上に description が既に在る: {schema['description']!r}")
    text = PREFIX + " ".join([name] + ([_CONT + cont] if cont is not None else []) + list(flags))
    if parse(text) is None:
        raise ValueError(f"印として読めない: {text!r}")
    out = {"description": text}
    out.update(copy.deepcopy(schema))
    return out


def strip(schema):
    """印の description を外した写し。印でない description は残す"""
    out = copy.deepcopy(schema)
    if parse(out.get("description")) is not None:
        del out["description"]
    return out


def from_argv(argv):
    """claude の argv の --json-schema（`--json-schema <値>` と `--json-schema=<値>`）から印を読む。無い・読めないなら None"""
    for i, a in enumerate(argv):
        if a == _ARG:
            if i + 1 >= len(argv):
                return None
            text = argv[i + 1]
        elif a.startswith(_ARG + "="):
            text = a[len(_ARG) + 1:]
        else:
            continue
        try:
            schema = json.loads(text)
        except ValueError:
            return None
        return parse(schema.get("description")) if isinstance(schema, dict) else None
    return None
