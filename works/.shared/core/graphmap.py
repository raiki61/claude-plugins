"""工程の地図（graph map）: Archon の工程の YAML から、AI の節に「全体のグラフはこの形で、あなたはここ」を機械で組む部品。

どの線・どの pack でも使えるように、Archon の YAML の形（nodes・depends_on・when・loop_group・include／workflow・with・
approval・output_format の印）と pack の宣言（archon-plugin.json の entrypoints）だけを読み、線やブロックの名前・中身を知らない。
節の目的の 1 行は YAML の節の `description:`（Archon v0.11.1 の節の型に在る鍵。検査の warning も出ない）から取り、部品は
節ごとの文を持たない。

口（API）:
- build(entry, resolve, base, parse) -> dict: 入口の工程の YAML（entry）から、include／workflow で呼ぶ工程を resolve(名) で
  引いてたどり、地図の元（graph。JSON にできる dict）を組む。base は sources の相対パスの根。parse は YAML の字を読む関数
  （yaml.safe_load。pack のモジュールは標準ライブラリだけなので受けて使う）。包みは YAML を読まないので、組むのは試験と開発の道具
  dev/graphmap_build.py で、包みは組んだ JSON を読む
- pack_resolver(pack, parse) -> resolve: pack の直下のフォルダの <d>/<d>.yaml を工程の名（YAML の name:）で引く既定の resolve
- entrypoints(pack) -> {名: YAML の相対パス}: pack の宣言 archon-plugin.json の entrypoints
- graph_path(pack, rel) -> Path: 入口の YAML の隣の地図の元のファイル（<stem>.graph.json）
- load(path) -> dict: 地図の元を読む（形が違えば ValueError）
- stale(graph, base) -> [相対パス]: sources の sha256 と今のファイルが違う（無い）物。空なら新しい
- one_graph(pack, has) -> dict: pack の入口ごとの地図の元のうち has(地図の元) が真のちょうど 1 本（古い・読めない・本数が違えば ValueError）
- markers(graph) -> {印の名: [(工程の名, 節の id)]}
- seat(graph, name) -> (根の印の名, 会話を共にする印の名の集合)
- render(graph, name, off=None, budget=MAP_BUDGET) -> str: 印 name の節を ★ にした地図の文。off は切った切り替えの語の集合
  （None は分からない）。budget は字数の枠（None は枠なし）
- design(graph, sections, receives, manifests) -> str: 人が読む設計図の文書（mermaid の図。線の全体 1 枚とブロックごと 1 枚）。
  sections は貼る節の宣言の行 {module, name, heading, source, human}、receives は受け手の行 {workflow, role, module, name, when}、
  manifests はブロックごとの {consumes, produces}（graphmap は節の宣言もブロックも知らず、dev の道具が集めて渡す）。宣言の欠け
  （目的の無い AI の節・graph に無い役を名指す受け手の行）と、1 枚の図が mermaid の既定の枠（字数・エッジ数）を超える時は、図を出さずに ValueError

地図の元（graph）の形: {version, entry, sources: {相対パス: sha256}, workflows: {工程の名: {nodes: [節]}}}。節は
{id, kind, purpose?, needs?, optional?, when?, deps, marker?, cont?, flags?, max?, body?, call?, with?}。kind は ai（prompt・command）・
ai-loop（loop:）・script・bash・approval・loop（loop_group。body に中の節・max に上限）・call（include・workflow。call に
工程の名、with に字の値の束ね）・cancel・wait。

組み方の決まり（render）:
- 会話の席（seat）: 印の continue=X で会話を継ぐ節を、根（continue を持たない節）までたどって 1 つの席にまとめる。X が
  どの工程にも無い名（ブロックの中の別名）なら、その工程を呼ぶ節の with の字の値のうち印の名である物がちょうど 1 つの時
  だけ、それを X の正体とする（ブロックはほかのブロックの節の名を書かず、線が with で名を渡す形）。席の全部の節に ★ を付け、
  席のどの節で起こしても同じ文になる（同じ会話の system prompt が起動ごとに替わると prompt のキャッシュが切れるため）
- 入口の工程を上から順に 1 行ずつ（輪は中の節も。節の目的が無い script・bash・cancel・wait は配管として省く）。席へ至る
  呼びの道の工程の全部（入れ子の呼びも）と、入口の工程で席を最初に持つ節の後で最初に呼ばれる工程（次に何が起きるか）を、
  中の節まで開いて出す。呼ぶ節は、呼ぶ先に席が居れば ★
- 輪は ⟳<上限>、同じ depends_on を持つ兄弟の輪・AI の節は ∥（同時に走る）、when は [条件]（$X.output.f == true は X.f）
- `description:` の末尾の `[needs: <入力>]` は「その工程の入力 <入力> が off なら仕事をしない（走らないか、走っても何もしない）」。呼ぶ節の with の束ね
  （`$….<語>` の最後の語か、字の on・off）を off と突き合わせ、切られていれば節を出さず、分からなければ [needs …] を残す
- `description:` の末尾の `[optional]` は「この節が落ちても線は止めない（報告の節が落ちを受け止めた落ちとして数える）」。節の欄 optional: true に
  切り出し、目的の文と地図の文には出さない
- 短く保つ: when の指す節が 1 つも地図に出ない（配管・切られた節の欄）なら [?]。∥ の兄弟で depends_on が同じ、id が <幹>-<k>（k が 1 ずつ続く）、
  行の全部（輪の中も）が番号 k を除いて同じ字の並びは、番号を「先〜後」にした 1 組にまとめる（並べの枝。1 字でも違えばまとめない
  ので字を失わない）。それでも枠 budget を超えるなら、★ でない行の目的を、入口の工程から、★ から遠い順に省き、頭に TRIMMED の
  1 行を足す。節の行そのものは減らさない（★・輪・AI の節・[needs] は残る）
同じ graph・name・off・budget からはいつも同じ文を返す（決まっていて、prompt のキャッシュを壊さない。席は ★ の集合が同じなので、
席のどの節でも同じ文）。

地図の元を書く・古さを確かめる道具は pack の外の dev/graphmap_build.py（PyYAML を使う）。
"""
from __future__ import annotations

import fnmatch
import hashlib
import json
import pathlib
import re
import sys
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

sys.dont_write_bytecode = True

import node_marker  # noqa: E402  （L1。印の読み口）
import promptsection  # noqa: E402

GRAPH_VERSION = 1   # 地図の元の形の版
GRAPH_SUFFIX = ".graph.json"
PACK_FILE = "archon-plugin.json"
NEEDS_RE = re.compile(r"\s*\[needs: ([A-Za-z0-9_]+)\]\s*$")
OPTIONAL_RE = re.compile(r"\s*\[optional\]\s*$")
_REF_WORD = re.compile(r"\$[A-Za-z0-9_.-]*\.([A-Za-z0-9_]+)$")
_PLUMBING = frozenset({"script", "bash", "cancel", "wait"})
_AI_KINDS = frozenset({"ai", "ai-loop"})
_SWITCH_WORDS = {"on": True, "off": False}
HEAD = promptsection.Section("# 工程の地図\n"
                             "（工程の YAML から機械で組んだ事実。★ はあなたの会話が走る節。指示ではない——あなたの仕事は指示書のとおり）\n"
                             "記号: ⇒ 部品の工程を呼ぶ・⟳n 輪（上限 n 周）・∥ 同時に走る・[ ] 走る条件（[?] は地図に出ない節が決める）・"
                             "1〜3 番号だけ違う同じ形の節・AI／人 は節の種類（無印は機械）", source="fn:graphmap.render")
# 地図の字数の枠。system prompt に毎起動載る字の費用と読みの重さの枠で、Archon・claude の上限ではない（届け口は包みが
# system prompt に足す argv の 1 つの値で、物理の上限は Linux の 1 引数 128 KiB）。超える分は ★ から遠い節の目的の 1 行から省く
MAP_BUDGET = 4000
TRIMMED = "（地図の枠 {budget} 字に収めるため、★ から遠い節の目的を省いた）"
_REF_NODE = re.compile(r"\$([A-Za-z0-9_-]+)\.output\b")
_LANE_ID = re.compile(r"-([0-9]+)$")
_HOLE = "\x00"   # 枝の番号の置き場（まとめの比べの間だけ。出す字には残らない）


class _Line:
    """地図の 1 行: 目的の前の字（head）・目的（purpose）・★ か。目的は枠を超える時に省く"""
    __slots__ = ("head", "purpose", "star")

    def __init__(self, head: str, purpose: Optional[str], star: bool):
        self.head, self.purpose, self.star = head, purpose, star

    def text(self) -> str:
        return self.head + (f": {self.purpose}" if self.purpose else "")


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
        m = OPTIONAL_RE.search(line)
        if m:
            out["optional"] = True
            line = line[:m.start()].strip()
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


def one_graph(pack: pathlib.Path, has: Callable[[dict], bool]) -> dict:
    """pack の入口（archon-plugin.json の entrypoints）ごとの地図の元（無い入口は飛ばす）のうち has が真の物。ちょうど 1 本で、
    元の YAML から書き直されていない（stale が空）時だけ返す。読めない・本数が違う・古ければ ValueError"""
    found = []
    for _name, rel in sorted(entrypoints(pack).items()):
        path = graph_path(pack, rel)
        if not path.is_file():
            continue
        g = load(path)
        if has(g):
            found.append((path, g))
    if len(found) != 1:
        raise ValueError(f"当たる地図の元が {len(found)} 本（ちょうど 1 本の時だけ読む）")
    path, g = found[0]
    old = stale(g, pack)
    if old:
        raise ValueError(f"地図の元 {path.name} が YAML より古い（{', '.join(old)}。dev/graphmap_build.py の build で書き直す）")
    return g


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


def _holds(graph: dict, wf: str, mine: Set[str], seen: Optional[Set[str]] = None) -> bool:
    """工程 wf（とそこから呼ぶ工程）に席の節が居るか"""
    seen = set() if seen is None else seen
    if wf in seen:
        return False
    seen.add(wf)
    return any(_held(graph, n, mine, seen) for n in graph["workflows"][wf]["nodes"])


def _held(graph: dict, n: dict, mine: Set[str], seen: Optional[Set[str]] = None) -> bool:
    """節 n（輪の中・呼ぶ工程の中も）に席の節が居るか"""
    seen = set() if seen is None else seen
    return any(m.get("marker") in mine or (m["kind"] == "call" and _holds(graph, m["call"], mine, seen))
               for m in _walk([n]))


def _shown(graph: dict, wf: str, off: Optional[Set[str]], nodes: Optional[Sequence[dict]] = None) -> Set[str]:
    """工程 wf で地図に出る節の id（配管でなく、切り替えで切られていない物。切られていない輪の中も）"""
    out: Set[str] = set()
    for n in graph["workflows"][wf]["nodes"] if nodes is None else nodes:
        if "needs" in n and _needs(graph, wf, n, off) is False:
            continue   # 切られた輪は中の節も出ない
        if _visible(n):
            out.add(n["id"])
        out |= _shown(graph, wf, off, n.get("body") or [])
    return out


def _when(when: str, shown: Set[str]) -> str:
    """条件の字。指す節が 1 つも地図に出ない（配管・切られた節・無い節）なら ?（地図に無い名は役に引けない）"""
    refs = set(_REF_NODE.findall(when))
    return "?" if refs and not refs & shown else _cond(when)


def _numbered(text: str, k: int, to: str) -> str:
    return re.sub(rf"(?<![0-9]){k}(?![0-9])", to, text)


def _collapse(blocks: List[Tuple[dict, List[_Line]]]) -> List[_Line]:
    """∥ の兄弟のうち、depends_on が同じで、id が <幹>-<k> で k が 1 ずつ続き、行の全部が番号 k を除いて同じ字の並びを、
    番号を「先〜後」にした 1 組にまとめる（並べの枝）。1 字でも違えばまとめない（まとめで字を失わない）"""
    out: List[_Line] = []
    i = 0
    while i < len(blocks):
        j = i + 1
        first = _LANE_ID.search(blocks[i][0]["id"])
        if first is not None and blocks[i][1][0].head.lstrip(" -").startswith("∥ "):
            k0 = int(first.group(1))
            want = [(_numbered(l.head, k0, _HOLE), _numbered(l.purpose or "", k0, _HOLE), l.star) for l in blocks[i][1]]
            while j < len(blocks):
                m = _LANE_ID.search(blocks[j][0]["id"])
                k = k0 + (j - i)
                if m is None or int(m.group(1)) != k or sorted(blocks[j][0]["deps"]) != sorted(blocks[i][0]["deps"]) or [
                        (_numbered(l.head, k, _HOLE), _numbered(l.purpose or "", k, _HOLE), l.star)
                        for l in blocks[j][1]] != want:
                    break
                j += 1
            if j - i > 1:
                span = f"{k0}〜{k0 + j - i - 1}"
                out.extend(_Line(h.replace(_HOLE, span), p.replace(_HOLE, span) or None, st) for h, p, st in want)
                i = j
                continue
        out.extend(blocks[i][1])
        i += 1
    return out


def _lines(graph: dict, wf: str, nodes: Sequence[dict], mine: Set[str], off: Optional[Set[str]],
           depth: int, shown_ids: Optional[Set[str]] = None) -> List[_Line]:
    shown_ids = _shown(graph, wf, off) if shown_ids is None else shown_ids
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
    blocks: List[Tuple[dict, List[_Line]]] = []
    for n, state in shown:
        par = "∥ " if n["kind"] in ("loop", "ai", "ai-loop") and groups.get(tuple(sorted(n["deps"])), 0) > 1 else ""
        starred = n.get("marker") in mine or (n["kind"] == "call" and _holds(graph, n["call"], mine))
        kind = {"ai": "AI ", "ai-loop": "AI ", "approval": "人 "}.get(n["kind"], "")
        loop = f"⟳{n['max']} " if n["kind"] == "loop" else ""
        text = f"{'  ' * depth}- {par}{'★ ' if starred else ''}{loop}{kind}{n['id']}"
        if n["kind"] == "call":
            text += f" ⇒ {n['call']}"
            cut = sorted(k for k, v in n.get("with", {}).items() if _switch(v, off) is False)
            if cut:
                text += f" (off: {' '.join(cut)})"
        if n.get("when"):
            text += f" [{_when(n['when'], shown_ids)}]"
        if state is None:
            text += f" [needs {n['needs']}]"
        rows = [_Line(text, n.get("purpose"), starred)]
        if n.get("body"):
            rows.extend(_lines(graph, wf, n["body"], mine, off, depth + 1, shown_ids))
        blocks.append((n, rows))
    return _collapse(blocks)


def _distances(rows: Sequence[_Line], far: int) -> List[int]:
    """各行から最も近い ★ の行までの行の数（★ の無い節の行は far。どの ★ の在る節の行より遠い）"""
    stars = [i for i, r in enumerate(rows) if r.star]
    return [min((abs(i - s) for s in stars), default=far) for i in range(len(rows))]


def _fit(fixed: Sequence[str], sections: Sequence[Tuple[str, List[_Line]]], budget: Optional[int]) -> str:
    """節ごとの行を繋ぐ。budget を超えるなら、★ でない行の目的を、入口の工程（各工程の 1 行の要約）から、★ から遠い順
    （同じ遠さは上の行から）に省いて収める。行そのものは減らさない（収まらなければ省けるだけ省いた字を返し、試験が超えを名指す）"""
    def join(note: bool) -> str:
        out = list(fixed) + ([TRIMMED.format(budget=budget)] if note else [])
        for title, rows in sections:
            out.append(title)
            out.extend(r.text() for r in rows)
        return "\n".join(out)

    text = join(False)
    if budget is None or len(text) <= budget:
        return text
    order = []
    far = sum(len(rows) for _, rows in sections) + 1
    for tier, (_, rows) in enumerate(sections):
        dist = _distances(rows, far)
        order.extend((min(tier, 1), -dist[i], tier, i, rows[i]) for i in range(len(rows))
                     if rows[i].purpose and not rows[i].star)
    for *_, row in sorted(order, key=lambda o: o[:4]):
        row.purpose = None
        text = join(True)
        if len(text) <= budget:
            break
    return text


def render(graph: dict, name: str, off: Optional[Iterable[str]] = None, budget: Optional[int] = MAP_BUDGET) -> str:
    """印 name の地図の文。off は切った切り替えの語（None は分からない＝[needs …] を残す）。budget は字数の枠（超える分は
    ★ から遠い節の目的を省く。None は省かない）。name が無ければ KeyError"""
    _, mine = seat(graph, name)
    offs = None if off is None else set(off)
    entry = graph["entry"]
    top = graph["workflows"][entry]["nodes"]
    sections = [(f"{entry}（上から順に走る）:", _lines(graph, entry, top, mine, offs, 0))]
    opened: List[str] = []

    def visit(wf: str) -> None:   # 席へ至る呼びの道の工程を全部（入れ子の呼びも）、入口から辿った順に
        for n in _walk(graph["workflows"][wf]["nodes"]):
            if n["kind"] == "call" and n["call"] not in opened and _holds(graph, n["call"], mine):
                opened.append(n["call"])
                visit(n["call"])

    visit(entry)
    first = next((i for i, n in enumerate(top) if _held(graph, n, mine)), None)
    if first is not None:
        nxt = next((n["call"] for n in top[first + 1:] if n["kind"] == "call"), None)
        if nxt is not None and nxt not in opened:
            opened.append(nxt)
    for wf in opened:
        sites = "・".join(dict.fromkeys(n["id"] for _, n in _sites(graph, wf)))
        sections.append((f"{wf}（{sites} で走る）:", _lines(graph, wf, graph["workflows"][wf]["nodes"], mine, offs, 0)))
    return _fit([HEAD], sections, budget)


# --- 設計図（graph → mermaid の文書） ---------------------------------------------------------------------------------
MERMAID_MAX_TEXT = 50000   # mermaid の既定の枠 maxTextSize / maxEdges。超える図は表示されないので、出さずに拒む
MERMAID_MAX_EDGES = 500
_REF_FIELD = re.compile(r"\$([A-Za-z0-9_-]+)\.output\.([A-Za-z0-9_]+)")


def _mid(text: str) -> str:
    """mermaid の id に使える字だけにする（他の字は _）"""
    return re.sub(r"[^A-Za-z0-9_]", "_", text)


def _md(level: int, text: str) -> str:
    """文書の見出しの行（役の指示書に貼る見出しの宣言と取り違えない書き方）"""
    return "#" * level + " " + text


def _q(text: str) -> str:
    """mermaid の引用の字（" と改行を避ける）"""
    return text.replace('"', "'").replace("\n", " ")


def _edges(pairs: Mapping[Tuple[str, str], Set[str]], dotted: Sequence[Tuple[str, str]] = ()) -> List[str]:
    out = []
    for (a, b), labels in sorted(pairs.items()):
        out.append(f'{a} -->|"{_q(", ".join(sorted(labels)))}"| {b}' if labels else f"{a} --> {b}")
    out.extend(f'{a} -.->|"次の周"| {b}' for a, b in dotted)
    return out


def _flat(nodes: Sequence[dict], above: Sequence[dict] = ()) -> List[Tuple[dict, Tuple[dict, ...]]]:
    """(節, 外側の輪の列) を上から順に。輪の中の節も平らに出す"""
    out = []
    for n in nodes:
        out.append((n, tuple(above)))
        out.extend(_flat(n.get("body") or [], (*above, n)))
    return out


class _Wf:
    """1 つの工程の節の索引。節の効く先の依存（外側の輪の依存も含む）と、描く節への解き方を持つ"""

    def __init__(self, wf: str, nodes: Sequence[dict], shown: Callable[[dict], bool]):
        self.wf, self.nodes, self.shown = wf, nodes, shown
        self.flat = _flat(nodes)
        self.by_id = {n["id"]: (n, above) for n, above in self.flat}

    def deps(self, nid: str) -> List[str]:
        n, above = self.by_id[nid]
        return [d for m in (*above, n) for d in m["deps"] if d in self.by_id]

    def resolve(self, nid: str, seen: Optional[Set[str]] = None) -> List[str]:
        """節 nid が終わった時に出ている描く節。描かない節（配管）は、その依存の先へ辿る"""
        seen = set() if seen is None else seen
        if nid in seen or nid not in self.by_id:
            return []
        seen.add(nid)
        n, _ = self.by_id[nid]
        if self.shown(n):
            return [nid]
        inside = [m["id"] for m, above in self.flat if n in above and self.shown(m)]
        if inside:
            return inside
        return [s for d in self.deps(nid) for s in self.resolve(d, seen)]

    def edges(self, skip_refs: Set[str]) -> Dict[Tuple[str, str], Set[str]]:
        """描く節どうしのエッジ → 添える欄の名（when・with の $<節>.output.<欄>。skip_refs の節の出口は線にしない）"""
        out: Dict[Tuple[str, str], Set[str]] = {}
        for n, above in self.flat:
            if not self.shown(n):
                continue
            for d in self.deps(n["id"]):
                for s in self.resolve(d):
                    if s != n["id"]:
                        out.setdefault((s, n["id"]), set())
            texts = [n.get("when") or "", *(n.get("with") or {}).values()]
            for ref, field in (m for t in texts for m in _REF_FIELD.findall(t)):
                if ref in skip_refs:
                    continue
                for s in self.resolve(ref):
                    if s != n["id"]:
                        out.setdefault((s, n["id"]), set()).add(field)
        return out


def _role_label(n: dict, pasted: int) -> str:
    outs = ", ".join(n.get("outputs") or []) or "-"
    return _q(f'{n["id"]}<br/>{n["purpose"]}<br/>機械が貼る {pasted}<br/>返す: {outs}')


def _manifest_edges(frames: Sequence[str], manifests: Mapping[str, Mapping]) -> List[str]:
    pairs: Dict[Tuple[str, str], Set[str]] = {}
    for p, pm in manifests.items():
        for c, cm in manifests.items():
            if p == c or p not in frames or c not in frames:
                continue
            for made in pm.get("produces") or []:
                for used in cm.get("consumes") or []:
                    a, b = made["name"], used["name"]
                    if a == b or fnmatch.fnmatchcase(b, a) or fnmatch.fnmatchcase(a, b):
                        pairs.setdefault((p, c), set()).add(b)
    return [f'F_{_mid(p)} -->|"{_q(", ".join(sorted(names)))}"| F_{_mid(c)}' for (p, c), names in sorted(pairs.items())]


def design(graph: dict, sections: Sequence[Mapping], receives: Sequence[Mapping], manifests: Mapping[str, Mapping]) -> str:
    """設計図の文書（mermaid の図: 線の全体 1 枚と、入口でない工程（ブロック）ごと 1 枚）。同じ入力からいつも同じ字。
    目的の無い AI の節・graph に無い役か宣言に無い節を名指す受け手の行・枠を超える図は、図を出さずに ValueError"""
    wfs = graph["workflows"]
    entry = graph["entry"]
    for wf, doc in sorted(wfs.items()):
        for n, _ in _flat(doc["nodes"]):
            if n["kind"] in _AI_KINDS and not n.get("purpose"):
                raise ValueError(f"工程 {wf} の AI の節 {n['id']} に目的の 1 行（description:）が無い")
    decl = {(s["module"], s["name"]): s for s in sections}
    rows = sorted(receives, key=lambda r: (r["workflow"], r["role"], r["module"], r["name"], r["when"]))
    pasted: Dict[Tuple[str, str], List[Tuple[Mapping, Mapping]]] = {}   # (工程, 節の id) → [(宣言, 受け手の行)]
    for r in rows:
        sec = decl.get((r["module"], r["name"]))
        if sec is None:
            raise ValueError(f"受け手の行 {r['workflow']}/{r['role']} が名指す節の宣言 {r['module']}.{r['name']} が無い")
        doc = wfs.get(r["workflow"])
        hit = [n["id"] for n, _ in _flat(doc["nodes"]) if n["kind"] in _AI_KINDS and r["role"] in (n["id"], n.get("marker"))] if doc else []
        if not hit:
            raise ValueError(f"受け手の行の役 {r['role']!r}（工程 {r['workflow']}）が graph に無い")
        for nid in hit:
            pasted.setdefault((r["workflow"], nid), []).append((sec, r))
    figures: List[Tuple[str, str, List[str], List[str]]] = []   # (見出し, 図の名, 行, エッジの行)

    top = wfs[entry]["nodes"]
    first_call = next((i for i, n in enumerate(top) if n["kind"] == "call"), None)
    givers = {n["id"] for n in top[:first_call + 1] if n["kind"] in _PLUMBING | {"call"}} if first_call is not None else set()
    called = list(dict.fromkeys(n["call"] for n, _ in _flat(top) if n["kind"] == "call"))
    line = _Wf(entry, top, lambda n: n["kind"] in _AI_KINDS | {"call", "approval"})
    body: List[str] = []
    for blk in called:
        members = [n for n, _ in line.flat if n["kind"] == "call" and n["call"] == blk]
        body.append(f'subgraph F_{_mid(blk)}["{_q(blk)}"]')
        body += [f'  {_mid(n["id"])}["{_q(n["id"])} ⇒ {_q(blk)}<br/>{_q(n.get("purpose") or "")}"]' for n in members]
        body.append("end")
    for n, _ in line.flat:
        if n["kind"] == "approval":
            body.append(f'{_mid(n["id"])}{{"{_q(n["id"])}<br/>{_q(n.get("purpose") or "")}"}}')
        elif n["kind"] in _AI_KINDS:
            body.append(f'{_mid(n["id"])}["{_role_label(n, len(pasted.get((entry, n["id"]), [])))}"]')
    pairs = {(_mid(a), _mid(b)): lab for (a, b), lab in line.edges(givers).items()}
    edges = _edges(pairs) + _manifest_edges(called, manifests)
    figures.append((f"線の全体（{entry}）", f"線の全体 {entry}", body, edges))

    for wf in sorted(w for w in wfs if w != entry):
        ai = _Wf(wf, wfs[wf]["nodes"], lambda n: n["kind"] in _AI_KINDS)
        roles = [n for n, _ in ai.flat if n["kind"] in _AI_KINDS]
        body = [f'subgraph F_{_mid(wf)}["{_q(wf)}"]']
        body += [f'  {_mid(n["id"])}["{_role_label(n, len(pasted.get((wf, n["id"]), [])))}"]' for n in roles]
        body.append("end")
        dotted = []
        for n, _ in ai.flat:
            if n["kind"] == "loop":
                mine = [m for m in n["body"] if m["kind"] in _AI_KINDS]
                if len(mine) >= 2:
                    dotted.append((_mid(mine[-1]["id"]), _mid(mine[0]["id"])))
        pairs = {(_mid(a), _mid(b)): lab for (a, b), lab in ai.edges(set()).items()}
        edges = _edges(pairs, dotted)
        sources = sorted({s["source"] or "出どころ未宣言" for (w, _), items in pasted.items() if w == wf for s, _ in items})
        sid = {s: f"S_{i}" for i, s in enumerate(sources)}
        body += [f'{sid[s]}(["{_q(s)}"])' for s in sources]
        for (w, nid), items in sorted(pasted.items()):
            if w == wf:
                for s, r in items:
                    head = (s["heading"].strip().splitlines() or [""])[0].lstrip("# ").strip()   # 見出しの字は本文を含みうるので 1 行目だけ
                    edges.append(f'{sid[s["source"] or "出どころ未宣言"]} -->|"{_q(head)} / {_q(r["when"])}"| {_mid(nid)}')
        figures.append((wf, wf, body, edges))

    out = [_md(1, f"{entry} の設計図"), "",
           "工程の YAML（役・順序・輪・with・when）、役の指示書に機械が貼る節の宣言（出どころ・受け手・入る条件）、各ブロックの manifest（produces・consumes）"
           "から作った文書。手で書かない（`uv run --no-project --with pyyaml python3 works/dev/graphmap_build.py build works` で作り直す）。", "",
           "- 役の四角: 名前・役の 1 行・`機械が貼る N`（その役の指示書に機械が貼る節の数）・`返す:`（返答の必須の欄）",
           "- 実線の矢印: 工程の順序。字は後の工程が `when`・`with` で読む前の工程の返答の欄、または manifest の produces → consumes の名",
           "- 点線の矢印: 役が 2 つ以上いる輪の、次の周への戻り",
           "- 丸い箱から役への矢印: 機械が貼る節の出どころ → 受け取る役。字は見出し / 入る条件を判じる関数", ""]
    for title, name, body, edges in figures:
        text = "\n".join(["flowchart TD", *(f"  {ln}" for ln in [*body, *edges])])
        if len(text) > MERMAID_MAX_TEXT:
            raise ValueError(f"図 {name} の字数 {len(text)} が mermaid の枠 maxTextSize {MERMAID_MAX_TEXT} を超える")
        if len(edges) > MERMAID_MAX_EDGES:
            raise ValueError(f"図 {name} のエッジ {len(edges)} 本が mermaid の枠 maxEdges {MERMAID_MAX_EDGES} を超える")
        out += [_md(2, title), "", "```mermaid", text, "```", ""]
    return "\n".join(out)
