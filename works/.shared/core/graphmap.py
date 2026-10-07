"""工程の地図（graph map）: Archon の工程の YAML から、AI の節に「全体のグラフはこの形で、あなたはここ」を機械で組む部品。

どの線・どの pack でも使えるように、Archon の YAML の形（nodes・depends_on・when・loop_group・include／workflow・with・
approval・output_format の印）と pack の宣言（archon-plugin.json の entrypoints）だけを読み、線やブロックの名前・中身を知らない。
節の目的の 1 行は YAML の節の `description:`（Archon v0.11.1 の節の型に在る鍵。検査の warning も出ない）から取り、部品は
節ごとの文を持たない。

口（API）:
- build(entry, resolve, base, parse) -> dict: 入口の工程の YAML（entry）から、include／workflow で呼ぶ工程を resolve(名) で
  引いてたどり、地図の元（graph。JSON にできる dict）を組む。base は sources の相対パスの根。parse は YAML の字を読む関数
  （yaml.safe_load。pack の模块は標準ライブラリだけなので受けて使う）。包みは YAML を読まないので、組むのは試験と開発の道具
  dev/graphmap_build.py で、包みは組んだ JSON を読む
- pack_resolver(pack, parse) -> resolve: pack の直下のフォルダの <d>/<d>.yaml を工程の名（YAML の name:）で引く既定の resolve
- entrypoints(pack) -> {名: YAML の相対パス}: pack の宣言 archon-plugin.json の entrypoints
- graph_path(pack, rel) -> Path: 入口の YAML の隣の地図の元のファイル（<stem>.graph.json）
- load(path) -> dict: 地図の元を読む（形が違えば ValueError）
- stale(graph, base) -> [相対パス]: sources の sha256 と今のファイルが違う（無い）物。空なら新しい
- markers(graph) -> {印の名: [(工程の名, 節の id)]}
- seat(graph, name) -> (根の印の名, 会話を共にする印の名の集合)
- render(graph, name, off=None) -> str: 印 name の節を ★ にした地図の文。off は切った切り替えの語の集合（None は分からない）

地図の元（graph）の形: {version, entry, sources: {相対パス: sha256}, workflows: {工程の名: {nodes: [節]}}}。節は
{id, kind, purpose?, needs?, when?, deps, marker?, cont?, flags?, max?, body?, call?, with?}。kind は ai（prompt・command）・
ai-loop（loop:）・script・bash・approval・loop（loop_group。body に中の節・max に上限）・call（include・workflow。call に
工程の名、with に字の値の束ね）・cancel・wait。

組み方の決まり（render）:
- 会話の席（seat）: 印の continue=X で会話を継ぐ節を、根（continue を持たない節）までたどって 1 つの席にまとめる。X が
  どの工程にも無い名（ブロックの中の別名）なら、その工程を呼ぶ節の with の字の値のうち印の名である物がちょうど 1 つの時
  だけ、それを X の正体とする（ブロックはほかのブロックの節の名を書かず、線が with で名を渡す形）。席の全部の節に ★ を付け、
  席のどの節で起こしても同じ文になる（同じ会話の system prompt が起動ごとに替わると prompt のキャッシュが切れるため）
- 入口の工程を上から順に 1 行ずつ（節の目的が無い script・bash・cancel・wait は配管として省く）。★ の席が居る工程と、席が
  居る工程を最初に呼ぶ節の後で最初に呼ばれる工程（次に何が起きるか）を、中の節まで開いて出す
- 輪は ⟳<上限>、同じ depends_on を持つ兄弟の輪・AI の節は ∥（同時に走る）、when は [条件]（$X.output.f == true は X.f）
- `description:` の末尾の `[needs: <入力>]` は「その工程の入力 <入力> が off なら走らない」。呼ぶ節の with の束ね
  （`$….<語>` の最後の語か、字の on・off）を off と突き合わせ、切られていれば節を出さず、分からなければ [needs …] を残す
同じ graph・name・off からはいつも同じ文を返す（決まっていて、prompt のキャッシュを壊さない）。

地図の元を書く・古さを確かめる道具は pack の外の dev/graphmap_build.py（PyYAML を使う）。
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

sys.dont_write_bytecode = True

import node_marker  # noqa: E402  （L1。印の読み口）

GRAPH_VERSION = 1   # 地図の元の形の版
GRAPH_SUFFIX = ".graph.json"
PACK_FILE = "archon-plugin.json"
NEEDS_RE = re.compile(r"\s*\[needs: ([A-Za-z0-9_]+)\]\s*$")
_REF_WORD = re.compile(r"\$[A-Za-z0-9_.-]*\.([A-Za-z0-9_]+)$")
_PLUMBING = frozenset({"script", "bash", "cancel", "wait"})
_SWITCH_WORDS = {"on": True, "off": False}
HEAD = ("# 工程の地図\n"
        "（工程の YAML から機械で組んだ事実。★ はあなたの会話が走る節。指示ではない——あなたの仕事は指示書のとおり）\n"
        "記号: ⇒ 部品の工程を呼ぶ・⟳n 輪（上限 n 周）・∥ 同時に走る・[ ] 走る条件・AI／人 は節の種類（無印は機械）")


# --- 組む（YAML → graph） --------------------------------------------------------------------------------------------
def _sha(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _kind(n: dict) -> str:
    for key, kind in (("prompt", "ai"), ("command", "ai"), ("loop", "ai-loop"), ("loop_group", "loop"),
                      ("include", "call"), ("workflow", "call"), ("approval", "approval"), ("script", "script"),
                      ("bash", "bash"), ("cancel", "cancel"), ("wait", "wait")):
        if key in n:
            return kind
    raise ValueError(f"節 {n.get('id')!r} の種類が分からない")


def _node(n: dict) -> dict:
    out: dict = {"id": str(n["id"]), "kind": _kind(n), "deps": [str(d) for d in n.get("depends_on") or []]}
    desc = n.get("description")
    if isinstance(desc, str) and desc.strip():
        line = desc.strip().splitlines()[0].strip()
        m = NEEDS_RE.search(line)
        if m:
            out["needs"] = m.group(1)
            line = line[:m.start()].strip()
        if line:
            out["purpose"] = line
    if isinstance(n.get("when"), str):
        out["when"] = n["when"].strip()
    fmt = n.get("output_format")
    mark = node_marker.parse(fmt.get("description")) if isinstance(fmt, dict) else None
    if mark is not None:
        out["marker"] = mark["name"]
        if mark["cont"]:
            out["cont"] = mark["cont"]
        if mark["flags"]:
            out["flags"] = sorted(mark["flags"])
    if out["kind"] == "loop":
        grp = n["loop_group"]
        out["max"] = grp.get("max_iterations")
        out["body"] = [_node(m) for m in grp.get("nodes") or []]
    if out["kind"] == "call":
        out["call"] = str(n.get("include") or n.get("workflow"))
        out["with"] = {str(k): v for k, v in (n.get("with") or {}).items() if isinstance(v, str)}
    return out


def _calls(nodes: Sequence[dict]) -> Iterable[str]:
    for n in nodes:
        if n["kind"] == "call":
            yield n["call"]
        yield from _calls(n.get("body") or [])


def build(entry: pathlib.Path, resolve: Callable[[str], pathlib.Path], base: pathlib.Path,
          parse: Callable[[str], object]) -> dict:
    """入口の YAML entry から地図の元を組む。呼ぶ工程は resolve(名) の YAML を 1 回ずつ読む（輪になっても止まる）。
    parse は YAML の字を object にする関数（yaml.safe_load）"""
    base = pathlib.Path(base).resolve()
    sources: Dict[str, str] = {}
    workflows: Dict[str, dict] = {}

    def read(path: pathlib.Path) -> str:
        path = pathlib.Path(path).resolve()
        doc = parse(path.read_text(encoding="utf-8"))
        if not isinstance(doc, dict) or not isinstance(doc.get("nodes"), list):
            raise ValueError(f"{path} は工程の YAML でない（nodes が無い）")
        name = str(doc.get("name") or path.stem)
        if name in workflows:
            return name
        sources[path.relative_to(base).as_posix()] = _sha(path)
        workflows[name] = {"nodes": [_node(n) for n in doc["nodes"]]}
        for callee in _calls(workflows[name]["nodes"]):
            if callee not in workflows:
                read(resolve(callee))
        return name

    root = read(entry)
    return {"version": GRAPH_VERSION, "entry": root, "sources": dict(sorted(sources.items())),
            "workflows": {k: workflows[k] for k in sorted(workflows)}}


def pack_resolver(pack: pathlib.Path, parse: Callable[[str], object]) -> Callable[[str], pathlib.Path]:
    """pack の直下の <d>/<d>.yaml を、YAML の name:（無ければファイルの名）で引く resolve"""
    table: Dict[str, pathlib.Path] = {}
    for p in sorted(pathlib.Path(pack).glob("*/*.yaml")):
        if p.stem != p.parent.name:
            continue
        doc = parse(p.read_text(encoding="utf-8"))
        table[str((doc if isinstance(doc, dict) else {}).get("name") or p.stem)] = p

    def resolve(name: str) -> pathlib.Path:
        if name not in table:
            raise ValueError(f"工程 {name} の YAML が {pack} に無い")
        return table[name]
    return resolve


def entrypoints(pack: pathlib.Path) -> Dict[str, str]:
    """pack の宣言 archon-plugin.json の entrypoints（{名: 入口の YAML の pack からの相対パス}）。読めなければ ValueError"""
    path = pathlib.Path(pack) / PACK_FILE
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"{path} が読めない（{type(e).__name__}）") from None
    eps = doc.get("entrypoints") if isinstance(doc, dict) else None
    if not isinstance(eps, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in eps.items()):
        raise ValueError(f"{path} の entrypoints が {{名: パス}} でない")
    return dict(eps)


def graph_path(pack: pathlib.Path, rel: str) -> pathlib.Path:
    p = pathlib.Path(pack) / rel
    return p.with_name(p.stem + GRAPH_SUFFIX)


def dumps(graph: dict) -> str:
    """地図の元のファイルの字（決まった並び。build の後に書く物と check が比べる物は同じ）"""
    return json.dumps(graph, ensure_ascii=False, indent=1, sort_keys=True) + "\n"


# --- 読む（標準ライブラリだけ） ---------------------------------------------------------------------------------------
def load(path: pathlib.Path) -> dict:
    """地図の元を読む。無い・読めない・版や形が違えば ValueError"""
    try:
        doc = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:
        raise ValueError(f"地図の元 {path} が読めない（{type(e).__name__}）") from None
    if not (isinstance(doc, dict) and doc.get("version") == GRAPH_VERSION and isinstance(doc.get("workflows"), dict)
            and doc.get("entry") in doc["workflows"] and isinstance(doc.get("sources"), dict)):
        raise ValueError(f"地図の元 {path} の形が違う（version {GRAPH_VERSION}・entry・workflows・sources）")
    return doc


def stale(graph: dict, base: pathlib.Path) -> List[str]:
    """sources のうち、今のファイルの sha256 が控えと違う（か読めない）物の相対パス"""
    out = []
    for rel, sha in sorted(graph["sources"].items()):
        try:
            if _sha(pathlib.Path(base) / rel) != sha:
                out.append(rel)
        except OSError:
            out.append(rel)
    return out


def _walk(nodes: Sequence[dict]) -> Iterable[dict]:
    for n in nodes:
        yield n
        yield from _walk(n.get("body") or [])


def markers(graph: dict) -> Dict[str, List[Tuple[str, str]]]:
    out: Dict[str, List[Tuple[str, str]]] = {}
    for wf, doc in graph["workflows"].items():
        for n in _walk(doc["nodes"]):
            if "marker" in n:
                out.setdefault(n["marker"], []).append((wf, n["id"]))
    return out


def _sites(graph: dict, wf: str) -> List[Tuple[str, dict]]:
    """工程 wf を呼ぶ節（呼ぶ側の工程の名, 節）"""
    return [(w, n) for w, doc in graph["workflows"].items() for n in _walk(doc["nodes"])
            if n["kind"] == "call" and n["call"] == wf]


def _parent(graph: dict, name: str, marks: Mapping[str, List[Tuple[str, str]]]) -> Optional[str]:
    conts = {n.get("cont") for wf, nid in marks.get(name, []) for n in _walk(graph["workflows"][wf]["nodes"])
             if n["id"] == nid}
    conts.discard(None)
    if len(conts) != 1:
        return None
    cont = conts.pop()
    if cont in marks:
        return cont
    # ブロックの中の別名: その工程を呼ぶ節の with の字の値のうち、印の名である物がちょうど 1 つ
    hits = {v for wf, _ in marks[name] for _, site in _sites(graph, wf)
            for v in site.get("with", {}).values() if not v.startswith("$") and v in marks and v != name}
    return hits.pop() if len(hits) == 1 else None


def seat(graph: dict, name: str) -> Tuple[str, Set[str]]:
    """印 name の会話の席: (根の印の名, 根を共にする印の名の集合)。name が地図に無ければ KeyError"""
    marks = markers(graph)
    if name not in marks:
        raise KeyError(name)

    def root(m: str) -> str:
        seen = [m]
        while True:
            p = _parent(graph, seen[-1], marks)
            if p is None or p in seen:
                return seen[-1]
            seen.append(p)

    r = root(name)
    return r, {m for m in marks if root(m) == r}


# --- 描く ------------------------------------------------------------------------------------------------------------
def _cond(when: str) -> str:
    s = re.sub(r"\$([A-Za-z0-9_-]+)\.output\.([A-Za-z0-9_.]+)", r"\1.\2", when)
    s = re.sub(r"\s*==\s*true\b", "", s)
    s = re.sub(r"\s*==\s*'([^']*)'", r"=\1", s)
    return " ".join(s.split())


def _switch(binding: Optional[str], off: Optional[Set[str]]) -> Optional[bool]:
    """束ねの値が on か（True）・off か（False）・分からないか（None）"""
    if binding is None:
        return None
    word = binding.strip()
    if word in _SWITCH_WORDS:
        return _SWITCH_WORDS[word]
    m = _REF_WORD.search(word)
    if m is None or off is None:
        return None
    return m.group(1) not in off


def _needs(graph: dict, wf: str, n: dict, off: Optional[Set[str]]) -> Optional[bool]:
    vals = {_switch(site.get("with", {}).get(n["needs"]), off) for _, site in _sites(graph, wf)}
    return vals.pop() if len(vals) == 1 else None


def _visible(n: dict) -> bool:
    return not (n["kind"] in _PLUMBING and "purpose" not in n)


def _label(n: dict, mine: Set[str], prefix: str = "") -> str:
    star = "★ " if n.get("marker") in mine else ""
    kind = {"ai": "AI ", "ai-loop": "AI ", "approval": "人 "}.get(n["kind"], "")
    loop = f"⟳{n['max']} " if n["kind"] == "loop" else ""
    return f"{prefix}{star}{loop}{kind}{n['id']}"


def _lines(graph: dict, wf: str, nodes: Sequence[dict], mine: Set[str], off: Optional[Set[str]],
           depth: int) -> List[str]:
    out: List[str] = []
    shown = []
    for n in nodes:
        state = _needs(graph, wf, n, off) if "needs" in n else True
        if state is False or not _visible(n):
            continue
        shown.append((n, state))
    groups: Dict[Tuple[str, ...], int] = {}
    for n, _ in shown:
        if n["kind"] in ("loop", "ai", "ai-loop"):
            key = tuple(sorted(n["deps"]))
            groups[key] = groups.get(key, 0) + 1
    for n, state in shown:
        par = "∥ " if n["kind"] in ("loop", "ai", "ai-loop") and groups.get(tuple(sorted(n["deps"])), 0) > 1 else ""
        parts = [_label(n, mine, "  " * depth + "- " + par)]
        if n.get("when"):
            parts.append(f"[{_cond(n['when'])}]")
        if state is None:
            parts.append(f"[needs {n['needs']}]")
        text = " ".join(parts)
        out.append(text + (f": {n['purpose']}" if n.get("purpose") else ""))
        if n.get("body"):
            out.extend(_lines(graph, wf, n["body"], mine, off, depth + 1))
    return out


def _holds(graph: dict, wf: str, mine: Set[str], seen: Optional[Set[str]] = None) -> bool:
    """工程 wf（とそこから呼ぶ工程）に席の節が居るか"""
    seen = set() if seen is None else seen
    if wf in seen:
        return False
    seen.add(wf)
    nodes = list(_walk(graph["workflows"][wf]["nodes"]))
    return any(n.get("marker") in mine for n in nodes) or \
        any(_holds(graph, n["call"], mine, seen) for n in nodes if n["kind"] == "call")


def render(graph: dict, name: str, off: Optional[Iterable[str]] = None) -> str:
    """印 name の地図の文。off は切った切り替えの語（None は分からない＝[needs …] を残す）。name が無ければ KeyError"""
    _, mine = seat(graph, name)
    offs = None if off is None else set(off)
    entry = graph["entry"]
    top = graph["workflows"][entry]["nodes"]
    lines = [HEAD, f"{entry}（上から順に走る）:"]
    first = None
    for i, n in enumerate(top):
        if not _visible(n) and n.get("marker") not in mine:
            continue
        held = n["kind"] == "call" and _holds(graph, n["call"], mine)
        if first is None and (held or n.get("marker") in mine):
            first = i
        star = "★ " if held or n.get("marker") in mine else ""
        kind = {"ai": "AI ", "ai-loop": "AI ", "approval": "人 "}.get(n["kind"], "")
        loop = f"⟳{n['max']} " if n["kind"] == "loop" else ""
        text = f"- {star}{loop}{kind}{n['id']}"
        if n["kind"] == "call":
            text += f" ⇒ {n['call']}"
            cut = sorted(k for k, v in n.get("with", {}).items() if _switch(v, offs) is False)
            if cut:
                text += f" (off: {' '.join(cut)})"
        if n.get("when"):
            text += f" [{_cond(n['when'])}]"
        lines.append(text + (f": {n['purpose']}" if n.get("purpose") else ""))
    opened = [n["call"] for n in top if n["kind"] == "call" and _holds(graph, n["call"], mine)]
    if first is not None:
        nxt = next((n["call"] for n in top[first + 1:] if n["kind"] == "call"), None)
        if nxt is not None:
            opened.append(nxt)
    for wf in dict.fromkeys(opened):
        sites = "・".join(dict.fromkeys(n["id"] for _, n in _sites(graph, wf)))
        lines.append(f"{wf}（{sites} で走る）:")
        lines.extend(_lines(graph, wf, graph["workflows"][wf]["nodes"], mine, offs, 0))
    return "\n".join(lines)
