"""works/dev/graphmap_build.py — 工程の地図の元（入口の YAML の隣の <名>.graph.json）と設計図（<pack>/docs/<入口の名>-design.md）を
書く・古さを確かめる（開発の道具）。

  uv run --no-project --with pyyaml python3 works/dev/graphmap_build.py build <pack> [<入口の名>…]
  uv run --no-project --with pyyaml python3 works/dev/graphmap_build.py check <pack> [<入口の名>…]

pack の宣言 archon-plugin.json の entrypoints の入口ごとに、部品 .shared/core/graphmap の build で地図の元を組み、その地図の元と
受け手の表の行（各モジュールの RECEIVES。読み口は tests/prepkit.py の receive_rows）から design で設計図を組む（入口の名を
省けば全部）。build は書き、check は書かずに、今の YAML と宣言から組んだ物と字で違う（か無い）ファイルを名指して終了コード 1 で抜ける。
YAML か宣言を替えたら build で書き直す（包みは古い元の地図を足さない。試験 tests/test_graphmap.py が古い元と古い設計図を赤にする）。
pack のモジュールは標準ライブラリだけなので、YAML を読む PyYAML はこの道具が渡す。

設計図は役と情報の流れの文書: 工程ごとに mermaid の素の flowchart（名前・入れ子・順・渡る物だけ）と、細目の表（何をするか・
機械が貼る節・受け取る物）。材料は地図の元（節の種類・順・輪・when・with・description の目的の 1 行）と受け手の表の行だけで、
宣言から引けない物（目的の 1 行の無い節・受け手の表に行の無い役）は「設計に無い」と書き、指示書や docstring から拾い直さない。
"""
import pathlib
import re
import sys

sys.dont_write_bytecode = True
_PACK = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PACK / ".shared" / "core"))
sys.path.insert(0, str(_PACK / "tests"))

import graphmap  # noqa: E402
import prepkit  # noqa: E402

LACK = "設計に無い"
_DRAWN = frozenset({"ai", "ai-loop", "call", "approval"})   # 図に描く節（役・呼び・関所）。機械の節は描かず、順はその先へたどる
_FIELD = re.compile(r"\$([A-Za-z0-9_-]+)\.output\.([A-Za-z0-9_]+)")
_KIND = {"ai": "AI", "ai-loop": "AI", "approval": "人の関所"}


def _flat(nodes):
    for n in nodes:
        yield n
        yield from _flat(n.get("body") or [])


def _drawn(n: dict) -> bool:
    return n["kind"] in _DRAWN or (n["kind"] == "loop" and any(_drawn(m) for m in n["body"]))


def _mid(n: dict) -> str:
    """mermaid の id（輪は囲みの L_、ほかは N_。id に使えない字は _）"""
    return ("L_" if n["kind"] == "loop" else "N_") + re.sub(r"[^A-Za-z0-9_]", "_", n["id"])


def _cell(text: str) -> str:
    return text.replace("|", "\\|")


def _boxes(nodes, depth: int) -> list:
    out = []
    pad = "  " * depth
    for n in nodes:
        if not _drawn(n):
            continue
        if n["kind"] == "loop":
            out.append(f'{pad}subgraph {_mid(n)}["⟳{n.get("max") or ""} {n["id"]}"]')
            out.extend(_boxes(n["body"], depth + 1))
            out.append(f"{pad}end")
        elif n["kind"] == "approval":
            out.append(f'{pad}{_mid(n)}{{"{n["id"]}"}}')
        elif n["kind"] == "call":
            out.append(f'{pad}{_mid(n)}["{n["id"]} ⇒ {n["call"]}"]')
        else:
            out.append(f'{pad}{_mid(n)}["{n["id"]}"]')
    return out


def _arrows(nodes) -> list:
    """順（depends_on。描かない節はその依存の先へたどる）の矢印。ほかの矢印をたどって着く矢印は省く（順は残る）。後の節が when・with で
    読む返答の欄を矢印の字にする: 矢印の元の節の欄は <欄>、描かない機械の節の欄は、その節をたどって着く矢印に <節>.<欄>
    （省いた矢印に当たる欄は表の「受け取る物」に在る）"""
    index = {n["id"]: n for n in _flat(nodes)}

    def ends(nid: str, seen: set) -> set:
        n = index.get(nid)
        if n is None or nid in seen:
            return set()
        seen.add(nid)
        return {_mid(n)} if _drawn(n) else set().union(*(ends(d, seen) for d in n["deps"]))

    drawn = [n for n in _flat(nodes) if _drawn(n)]
    order = {(a, _mid(n)) for n in drawn for a in set().union(*(ends(d, set()) for d in n["deps"]))}

    def detour(a: str, b: str) -> bool:
        stack, seen = [x for (s, x) in order if s == a and x != b], set()
        while stack:
            x = stack.pop()
            if x == b:
                return True
            if x not in seen:
                seen.add(x)
                stack.extend(y for (s, y) in order if s == x)
        return False

    edges = {e: set() for e in order if not detour(*e)}
    for n in drawn:
        for ref, field in _FIELD.findall(" ".join([n.get("when") or "", *(n.get("with") or {}).values()])):
            if ref not in index:
                continue
            tails, label = ({_mid(index[ref])}, field) if _drawn(index[ref]) else (ends(ref, set()), f"{ref}.{field}")
            for a in tails:
                if (a, _mid(n)) in edges:
                    edges[(a, _mid(n))].add(label)
    return [f'{a} -->|"{", ".join(sorted(fields))}"| {b}' if fields else f"{a} --> {b}" for (a, b), fields in sorted(edges.items())]


def _figure(nodes) -> list:
    return ["```mermaid", "flowchart TD", *(f"  {ln}" for ln in _boxes(nodes, 0) + _arrows(nodes)), "```"]


def _bound(value: str) -> str:
    """with の束ねの値の字: $<節>.output.<欄> は <節>.<欄>、$INPUTS.<名> は 入力.<名>、ほかは字のまま"""
    value = value.strip()
    m = _FIELD.fullmatch(value)
    if m:
        return f"{m.group(1)}.{m.group(2)}"
    return "入力." + value[len("$INPUTS."):] if value.startswith("$INPUTS.") else value


def _table(nodes, rows) -> list:
    """描く節の細目: 何をするか（目的の 1 行）・機械が貼る節の数（AI の役。受け手の表の行の節の字の数）・受け取る物（with の束ねの全部）"""
    out = ["| 節 | 種類 | 何をする | 機械が貼る節 | 受け取る物 |", "| --- | --- | --- | --- | --- |"]
    for n in _flat(nodes):
        if not _drawn(n):
            continue
        kind = f"⇒ {n['call']}" if n["kind"] == "call" else f"⟳{n.get('max') or ''}" if n["kind"] == "loop" else _KIND[n["kind"]]
        pasted = "-"
        if n["kind"] in ("ai", "ai-loop"):
            count = len({str(r.section) for r in rows if r.role == n.get("marker", n["id"])})
            pasted = str(count) if count else LACK
        got = [f"{k} ← {_bound(v)}" for k, v in sorted((n.get("with") or {}).items())]
        out.append(f"| {n['id']} | {_cell(kind)} | {_cell(n.get('purpose') or LACK)} | {pasted} | {_cell(', '.join(got) or '-')} |")
    return out


def _heading(section) -> str:
    return next((ln.lstrip("#").strip() for ln in str(section).splitlines() if ln.strip()), LACK)


def _pasted(rows) -> list:
    """機械が役の指示書に貼る節（受け手の表の行）: 見出し・出どころ・受ける役・入る条件の関数。同じ節・出どころ・条件の役は 1 行に"""
    if not rows:
        return [f"機械が貼る節: {LACK}（受け手の表 RECEIVES に行が無い）"]
    group: dict = {}
    for r in rows:
        group.setdefault((_heading(r.section), r.section.source or LACK, r.when), set()).add(r.role)
    out = ["| 機械が貼る節 | 出どころ | 受ける役 | 入る条件 |", "| --- | --- | --- | --- |"]
    out += [f"| {_cell(h)} | {_cell(s)} | {'・'.join(sorted(roles))} | {_cell(w)} |" for (h, s, w), roles in sorted(group.items())]
    return out


def design(graph: dict, rows) -> str:
    """設計図の文書。graph は地図の元、rows は (工程の名, promptsection.Receive) の受け手の表の行。同じ入力からいつも同じ字"""
    entry = graph["entry"]
    wfs = graph["workflows"]
    out = [f"# {entry} の設計図（役と情報の流れ）", "",
           f"地図の元（`{entry}` の工程の YAML から組んだ graph.json）・節の `description:` の目的の 1 行・受け手の表（各モジュールの "
           "`RECEIVES` と `promptsection.Section` の宣言）から機械で作った文書。手で書かない（`uv run --no-project --with pyyaml "
           "python3 works/dev/graphmap_build.py build works` で作り直し、`check works` と試験 `tests/test_graphmap.py` が古さを見る）。",
           "",
           "- 図: 箱は AI の役、`⇒` はブロックの工程を呼ぶ節、ひし形は人の関所、囲みは輪（`⟳` の後は上限の周）。機械の節は描かない",
           "- 矢印: 順（depends_on）。字は後の節が `when`・`with` で読む返答の欄（矢印の元の節の欄は `欄`、間の機械の節の欄は `節.欄`）",
           "- 表: 節の何をするか・機械が役の指示書に貼る節の数・受け取る物（`with` の欄 ← 節.返答の欄・入力.名・字の値）と、貼る節の出どころ・受ける役・入る条件の関数",
           f"- 「{LACK}」: 宣言から引けない物（目的の 1 行の無い節・受け手の表に行の無い役）。指示書や docstring から拾い直さない。"
           "受け手の表は貼る節が 0 の役と書き忘れの役を分けないので、どちらもこう出る", ""]
    order = [entry, *sorted(w for w in wfs if w != entry)]
    for wf in order:
        nodes = wfs[wf]["nodes"]
        mine = [r for w, r in rows if w == wf]
        if wf == entry:
            out += [f"## 線 {wf}", ""]
        else:
            sites = sorted({n["id"] for doc in wfs.values() for n in _flat(doc["nodes"]) if n.get("call") == wf})
            out += [f"## ブロック {wf}", "", f"呼ぶ節: {'・'.join(sites) or '-'}", ""]
        out += [*_figure(nodes), "", *_table(nodes, mine), ""]
        if mine or any(n["kind"] in ("ai", "ai-loop") for n in _flat(nodes)):   # 役の無い工程（線）には貼る先が無い
            out += [*_pasted(mine), ""]
    return "\n".join(out)


def main(argv) -> int:
    for stream in (sys.stdout, sys.stderr):   # 場所の設定が ASCII・cp1252 でも日本語の行で落ちない
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")
    if len(argv) < 2 or argv[0] not in ("build", "check"):
        print("usage: graphmap_build.py build|check <pack> [<入口の名>…]", file=sys.stderr)
        return 2
    import yaml

    pack = pathlib.Path(argv[1]).resolve()
    eps = graphmap.entrypoints(pack)
    names = list(argv[2:]) or sorted(eps)
    unknown = [n for n in names if n not in eps]
    if unknown:
        print(f"graphmap_build: 入口に無い名 {', '.join(unknown)}（在るのは {', '.join(sorted(eps))}）", file=sys.stderr)
        return 2
    resolve = graphmap.pack_resolver(pack, yaml.safe_load)
    rows = [(wf, row) for _, wf, row in prepkit.receive_rows(pack)]
    bad = 0
    for name in names:
        graph = graphmap.build(pack / eps[name], resolve, pack, yaml.safe_load)
        for out, text in ((graphmap.graph_path(pack, eps[name]), graphmap.dumps(graph)),
                          (pack / "docs" / f"{name}-design.md", design(graph, rows))):
            if argv[0] == "build":
                out.parent.mkdir(parents=True, exist_ok=True)
                out.write_text(text, encoding="utf-8")
                print(f"graphmap_build: {out.relative_to(pack)} を書いた")
            elif not out.is_file() or out.read_text(encoding="utf-8") != text:
                print(f"graphmap_build: {out.relative_to(pack)} が古い（graphmap_build.py build {argv[1]} {name} で書き直す）",
                      file=sys.stderr)
                bad = 1
    return bad


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
