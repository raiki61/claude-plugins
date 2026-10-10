"""工程の地図（.shared/core/graphmap.py）と、包みの system prompt の差し込みの表（adapter.py の頭の 13。設計
docs/plans/2026-10-07-graph-map.md）の検査。

縛る事:
- 組み（build）: Archon の YAML の節の種類・輪の中（入れ子も）・include の先の工程・with の字の値・description の 1 行目と
  末尾の [needs: <入力>]・印の名と continue と旗・元の YAML の sha。種は tests/graphmap/（Archon では回さない小さな pack）
- 会話の席（seat）: continue=X をたどって根にまとめる。ブロックの中の別名は、呼ぶ節の with の字の値で印の名が 1 つの時だけ解く
- 描き（render）: 席の全部の節と、席の居る工程を呼ぶ節に ★。配管の script を省く。席の工程と次に呼ばれる工程を開く。∥・⟳n・
  [条件]・[needs]・(off: …)。切った切り替えの節は出さない。席のどの節でも同じ文（prompt のキャッシュ）
- 新しさ: 本物の地図の元 darkfactory/darkfactory.graph.json は今の YAML から組み直した物と同じ（YAML を替えたら
  dev/graphmap_build.py の build で書き直す）。古い元は stale が名指す・道具の check が 1 で抜ける
- 本物の線: 旗 map の節の席は旗が揃う（会話の中で system prompt を替えない）。地図の文は字数の枠の中。地図に載る AI・輪・
  呼ぶ節は全部が目的の 1 行を持つ。description は 1 行。features_off の語 graph_map と包みの定数が合う
- 包みの差し込みの表: 旗 map の起動に地図を、道具を持つ起動に検索語の規律を、決まった順に 1 つの繋ぎ方で足し、塊ごとの digest を
  fence に残す。graph_map が切られた run・古い元・繋げない起動は足さずに理由を残して起こす。required の行が作れなければ拒む
git なし。子のプロセスは地図の元を書く道具 dev/graphmap_build.py を python3 で 4 本起こすだけ。
"""
import ast
import contextlib
import hashlib
import importlib.util
import inspect
import json
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from unittest import mock

import yaml

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent                 # works/
CORE = ROOT / ".shared" / "core"
SEED = TESTS / "graphmap"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

import adapter  # noqa: E402
import entry  # noqa: E402
import graphmap  # noqa: E402
import hermetic  # noqa: E402
import node_marker  # noqa: E402



def seed_graph(pack: pathlib.Path = SEED) -> dict:
    return graphmap.build(pack / "line" / "line.yaml", graphmap.pack_resolver(pack, yaml.safe_load), pack, yaml.safe_load)


def find(nodes, nid):
    for n in nodes:
        if n["id"] == nid:
            return n
        hit = find(n.get("body") or [], nid)
        if hit:
            return hit
    return None


# --- 役の指示書に機械が貼る節の見出しの宣言（考え prompt-sections。.shared/core/promptsection.py）---
HEADING_LINE = re.compile(r"(?m)^#{1,6} ")
# 見出しを貼るのでなく読む所（照らし・切り出し）の method
READING_METHODS = {"startswith", "endswith", "strip", "lstrip", "rstrip", "split", "rsplit", "partition", "rpartition",
                   "find", "rfind", "index", "rindex", "count"}


def prep_files() -> list:
    """役の支度のモジュール。写しの graphloops/・gl-prompts/（core の下の子の置き場）は入らない"""
    out = []
    for pat in ("blk-*/lib/*.py", "blk-*/scripts/*.py", "darkfactory/lib/*.py", "darkfactory/scripts/*.py", ".shared/core/*.py"):
        out.extend(sorted(ROOT.glob(pat)))
    return out


def docstring_constants(tree) -> set:
    out = set()
    for n in ast.walk(tree):
        if isinstance(n, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and n.body:
            first = n.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                out.add(id(first.value))
    return out


def reading_constants(tree) -> set:
    """re の関数の引数・str の照らしの method の引数・比べの項に在る字面"""
    out = set()

    def mark(node):
        out.update(id(c) for c in ast.walk(node) if isinstance(c, ast.Constant))
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare):
            mark(n)
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            f = n.func
            if (isinstance(f.value, ast.Name) and f.value.id == "re") or f.attr in READING_METHODS:
                for a in [*n.args, *(k.value for k in n.keywords)]:
                    mark(a)
    return out


def declared_constants(tree) -> set:
    """モジュールの直下の `<名> = promptsection.Section(...)` の最初の引数に在る字面"""
    out = set()
    for n in tree.body:
        call = n.value if isinstance(n, (ast.Assign, ast.AnnAssign)) else None
        if (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute) and call.func.attr == "Section"
                and isinstance(call.func.value, ast.Name) and call.func.value.id == "promptsection" and call.args):
            out.update(id(c) for c in ast.walk(call.args[0]) if isinstance(c, ast.Constant))
    return out


@contextlib.contextmanager
def prep_path(near: pathlib.Path):
    """支度のモジュールを読む間の import の道（core・読む物の隣・ブロックの lib）。読んだ後に道と私的な読み込みを戻す"""
    added = [str(CORE), str(near), *map(str, sorted(ROOT.glob("blk-*/lib")))]
    before = set(sys.modules)
    sys.path[:0] = added
    try:
        yield
    finally:
        for a in added:
            sys.path.remove(a)
        for name in set(sys.modules) - before:
            f = getattr(sys.modules[name], "__file__", None) or ""
            here = pathlib.Path(f).resolve() if f else None
            if here and here.is_relative_to(ROOT.resolve()) and not here.is_relative_to(CORE.resolve()):
                del sys.modules[name]


_PREP_MODULES: dict = {}


def load_prep(path: pathlib.Path):
    """支度のモジュールを場所から読む（同じ名の別の置き場の物と取り違えない）"""
    key = path.resolve()
    if key not in _PREP_MODULES:
        name = "_prep_" + "_".join(key.relative_to(ROOT.resolve()).with_suffix("").parts).replace("-", "_").replace(".", "_")
        spec = importlib.util.spec_from_file_location(name, key)
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        with prep_path(key.parent):
            spec.loader.exec_module(mod)
        _PREP_MODULES[key] = mod
    return _PREP_MODULES[key]


def import_named(name: str, near: pathlib.Path):
    """`<モジュール>` の名で引く（core か読む物の隣）"""
    with prep_path(near):
        return importlib.import_module(name)


def declaring_files() -> list:
    """promptsection を使う支度のモジュール（Section を宣言する物・RECEIVES を持つ物）"""
    out = []
    for p in prep_files():
        if p.name != "promptsection.py" and "promptsection" in p.read_text(encoding="utf-8"):
            out.append(p)
    return out


def all_sections() -> list:
    """(読んだ物の場所, 定数の名, Section の値) の全部"""
    try:
        import promptsection
    except ImportError as e:   # 宣言の住処が無い: 試験の誤りでなく、欠けとして落とす
        raise AssertionError(f"promptsection が読めない: {e}") from None
    if not hasattr(promptsection, "declared_sections"):
        raise AssertionError("promptsection.declared_sections が無い")
    return [(p, name, val) for p in declaring_files() for name, val in promptsection.declared_sections(load_prep(p))]


def assemblers() -> list:
    """(読んだ物の場所, 持ち主のブロック): 役の指示書を組むモジュール。ブロックの lib と、指示書を組む core の L4 のモジュール
    （test_layers の MOD で持ち主のブロックに結ぶ）。受け手の表 RECEIVES の置き場"""
    from test_layers import MOD
    out = [(p, p.parent.parent.name) for p in sorted(ROOT.glob("blk-*/lib/*.py"))]
    out.extend((CORE / f"{name}.py", owner) for name, (layer, owner) in sorted(MOD.items()) if layer == 4 and owner)
    return out


def used_in_code(path: pathlib.Path, mod) -> tuple:
    """モジュールの本体が名で使う物: (Section の値の字 → 値, 呼ぶ関数の完全な名 `<モジュール>.<関数>` の集まり)。
    宣言の文（モジュール直下の Section の代入と RECEIVES の表）と、見出しを読む所（比べの項・照らしの method の引数）は使いに数えない。
    別名・import した名・`<モジュール>.<名>` の形は、実物を引いて解く。このファイルの中の関数（読み込み名が私的）は数えない"""
    import promptsection
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    skip = reading_constants(tree)
    for n in tree.body:
        if isinstance(n, (ast.Assign, ast.AnnAssign)):
            targets = n.targets if isinstance(n, ast.Assign) else [n.target]
            names = [t.id for t in targets if isinstance(t, ast.Name)]
            if names and all(nm == "RECEIVES" or isinstance(getattr(mod, nm, None), promptsection.Section) for nm in names):
                skip.update(id(x) for x in ast.walk(n))
    reading = set()   # 比べの項・照らしの method の引数の中の名
    for n in ast.walk(tree):
        if isinstance(n, ast.Compare):
            reading.update(id(x) for x in ast.walk(n))
        elif isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr in READING_METHODS:
            for a in [*n.args, *(k.value for k in n.keywords)]:
                reading.update(id(x) for x in ast.walk(a))
    sections, calls = {}, set()
    for n in ast.walk(tree):
        if id(n) in skip or id(n) in reading:
            continue
        if isinstance(n, ast.Name):
            value = getattr(mod, n.id, None)
        elif isinstance(n, ast.Attribute) and isinstance(n.value, ast.Name):
            value = getattr(getattr(mod, n.value.id, None), n.attr, None)
        else:
            continue
        if isinstance(value, promptsection.Section):
            sections[str(value)] = value
        elif callable(value) and getattr(value, "__name__", None) and not str(getattr(value, "__module__", "")).startswith("_prep_"):
            calls.add(f"{value.__module__}.{value.__name__}")
    return sections, calls


class BuildCase(unittest.TestCase):
    def setUp(self):
        self.g = seed_graph()

    def test_workflows_and_sources(self):
        self.assertEqual(self.g["version"], graphmap.GRAPH_VERSION)
        self.assertEqual(self.g["entry"], "line")
        self.assertEqual(set(self.g["workflows"]), {"line", "blk-a", "blk-b"})
        self.assertEqual(set(self.g["sources"]), {"line/line.yaml", "blk-a/blk-a.yaml", "blk-b/blk-b.yaml"})
        for rel, sha in self.g["sources"].items():
            self.assertEqual(sha, hashlib.sha256((SEED / rel).read_bytes()).hexdigest())

    def test_node_kinds_and_fields(self):
        line = self.g["workflows"]["line"]["nodes"]
        self.assertEqual([(n["id"], n["kind"]) for n in line],
                         [("gate", "approval"), ("start", "script"), ("h-a", "script"), ("writing", "call"),
                          ("h-b", "script"), ("doing", "call"), ("closing", "call")])
        doing = find(line, "doing")
        self.assertEqual(doing["call"], "blk-b")
        self.assertEqual(doing["with"], {"lanes": "$start.output.lanes", "asker": "writer"})   # 字の値だけ（from の束ねは落とす）
        self.assertEqual(doing["when"], "$h-b.output.go == true")
        self.assertEqual(doing["deps"], ["h-b"])
        loop = find(self.g["workflows"]["blk-a"]["nodes"], "write-loop")
        self.assertEqual((loop["kind"], loop["max"], loop["purpose"]), ("loop", 3, "書く輪"))   # description の 1 行目だけ
        self.assertEqual([n["id"] for n in loop["body"]], ["write-prep", "writer", "write-accept", "revise-loop"])
        reviser = find(loop["body"], "reviser")   # 入れ子の輪の中
        self.assertEqual((reviser["kind"], reviser["marker"], reviser["cont"], reviser["flags"]),
                         ("ai", "reviser", "writer", ["map"]))
        lane = find(self.g["workflows"]["blk-b"]["nodes"], "lane-1")
        self.assertEqual((lane["kind"], lane["flags"]), ("ai", ["lane"]))   # command も AI
        self.assertNotIn("purpose", find(self.g["workflows"]["blk-a"]["nodes"], "prep"))

    def test_needs_tag_is_split_from_the_purpose(self):
        fork = find(self.g["workflows"]["blk-b"]["nodes"], "fork")
        self.assertEqual((fork["purpose"], fork["needs"]), ("枝を分ける", "lanes"))

    def test_unknown_kind_is_refused(self):
        with self.assertRaises(ValueError):
            graphmap._node({"id": "x"})

    def test_build_is_deterministic_and_round_trips(self):
        text = graphmap.dumps(self.g)
        self.assertEqual(text, graphmap.dumps(seed_graph()))
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "g.json"
            p.write_text(text, encoding="utf-8")
            self.assertEqual(graphmap.load(p), self.g)

    def test_load_refuses_other_shapes(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "g.json"
            for doc in ({"version": 99}, {"version": 1, "entry": "x", "workflows": {}, "sources": {}}, []):
                p.write_text(json.dumps(doc), encoding="utf-8")
                with self.subTest(doc=doc), self.assertRaises(ValueError):
                    graphmap.load(p)
            with self.assertRaises(ValueError):
                graphmap.load(pathlib.Path(tmp) / "none.json")

    def test_entrypoints_and_graph_path(self):
        self.assertEqual(graphmap.entrypoints(SEED), {"line": "line/line.yaml"})
        self.assertEqual(graphmap.graph_path(SEED, "line/line.yaml"), SEED / "line" / "line.graph.json")


class SeatCase(unittest.TestCase):
    def setUp(self):
        self.g = seed_graph()

    def test_continue_chain_and_block_alias(self):
        """reviser は continue=writer（同じ工程）。answer は continue=peer-writer（ブロックの中の別名）で、blk-b を呼ぶ節の
        with の字の値 writer が印の名なので writer に解ける"""
        want = ("writer", {"writer", "reviser", "answer"})
        for name in ("writer", "reviser", "answer"):
            with self.subTest(name):
                self.assertEqual(graphmap.seat(self.g, name), want)
        self.assertEqual(graphmap.seat(self.g, "fixer"), ("fixer", {"fixer"}))   # self-resume は席を作らない
        with self.assertRaises(KeyError):
            graphmap.seat(self.g, "nobody")

    def test_ambiguous_alias_stays_unresolved(self):
        g = json.loads(json.dumps(self.g))
        find(g["workflows"]["line"]["nodes"], "closing")["with"]["other"] = "fixer"
        find(g["workflows"]["line"]["nodes"], "closing")["call"] = "blk-b"   # blk-b を呼ぶ節が 2 つ、印の名の字が 2 つ
        self.assertEqual(graphmap.seat(g, "answer"), ("answer", {"answer"}))


class RenderCase(unittest.TestCase):
    def setUp(self):
        self.g = seed_graph()

    def test_writer_map(self):
        text = graphmap.render(self.g, "writer", off=[])
        self.assertEqual(text, "\n".join([
            graphmap.HEAD,
            "line（上から順に走る）:",
            "- 人 gate: 人の関所",
            "- start: 入力を確かめる",
            "- ★ writing ⇒ blk-a (off: peer) [?]: 案を書く",   # 条件の元 h-a は地図に出ない配管
            "- ★ doing ⇒ blk-b [?]: 案を直す",
            "- ★ closing ⇒ blk-a: 締める",
            "blk-a（writing・closing で走る）:",
            "- ⟳3 write-loop [?]: 書く輪",
            "  - ★ AI writer: 書く役",
            "  - ⟳2 revise-loop: 直しの輪",
            "    - ★ AI reviser: 直す役",
            "- peer-check [needs peer]: 相手を確かめる",
            "blk-b（doing で走る）:",
            "- fork: 枝を分ける",
            "- ∥ ⟳40 lane-loop-1〜2 [fork.lane_1〜2]: 枝 1〜2 の輪",   # 番号だけ違う同じ形の枝は 1 つにまとめる
            "  - AI lane-1〜2: 枝 1〜2 の役",
            "- join: 枝を 3 方向で合わせる",
            "- ⟳12 fix-loop: 直す輪",
            "  - AI fixer: 直す役",
            "  - ★ AI answer [fixer.ask]: 相談に答える（書いた会話の続き）",
        ]))

    def test_same_text_for_every_seat_member(self):
        for off in (None, [], ["lanes"]):
            with self.subTest(off=off):
                texts = {graphmap.render(self.g, n, off=off) for n in ("writer", "reviser", "answer")}
                self.assertEqual(len(texts), 1)

    def test_switched_off_nodes_are_dropped(self):
        text = graphmap.render(self.g, "writer", off=["lanes"])
        for gone in ("fork", "lane-loop-1", "lane-1", "lane-loop-2", "join"):
            self.assertNotIn(f" {gone}", text)
        self.assertIn("(off: lanes", text)
        self.assertIn("fix-loop", text)

    def test_unknown_switches_keep_conditions(self):
        text = graphmap.render(self.g, "writer", off=None)
        self.assertIn("- fork [needs lanes]: 枝を分ける", text)
        self.assertIn("∥ ⟳40 lane-loop-1〜2 [fork.lane_1〜2] [needs lanes]", text)
        self.assertIn("★ writing ⇒ blk-a (off: peer)", text)   # 字の off は run に依らず切り
        self.assertIn("peer-check [needs peer]", text)          # 呼ぶ節ごとに on と off が違う

    def test_next_called_workflow_is_opened(self):
        """席が線の工程に居ない節（fixer。blk-b）の地図は、blk-b を呼ぶ節の次に呼ばれる工程（blk-a の closing）も開く"""
        text = graphmap.render(self.g, "fixer", off=[])
        self.assertIn("- ★ doing ⇒ blk-b", text)
        self.assertIn("- writing ⇒ blk-a", text)
        self.assertIn("blk-a（writing・closing で走る）:", text)
        self.assertIn("  - ★ AI fixer: 直す役", text)
        self.assertNotIn("★ AI answer", text)

    def test_plumbing_scripts_are_hidden(self):
        text = graphmap.render(self.g, "writer", off=[])
        for hidden in ("h-a", "h-b", "prep", "write-accept", "write-prep", "fix-accept"):
            self.assertNotIn(f"- {hidden}", text)

    def test_conditions(self):
        self.assertEqual(graphmap._cond("$h-fix.output.go == true"), "h-fix.go")
        self.assertEqual(graphmap._cond("$rj-route1.output.next == 'rejudge'"), "rj-route1.next=rejudge")
        self.assertEqual(graphmap._switch("$start.output.tdd_lanes", {"tdd_lanes"}), False)
        self.assertEqual(graphmap._switch("$INPUTS.tdd_lanes", set()), True)
        self.assertIsNone(graphmap._switch("$start.output.tdd_lanes", None))
        self.assertEqual(graphmap._switch("off", None), False)
        self.assertIsNone(graphmap._switch(None, set()))

    def test_unknown_node(self):
        with self.assertRaises(KeyError):
            graphmap.render(self.g, "nobody")

    @staticmethod
    def node(nid, kind, **kw):
        return {"id": nid, "kind": kind, "deps": [], **kw}

    def test_seat_inside_an_entry_loop_and_a_nested_call(self):
        """席が入口の工程の輪の中に居る・呼ぶ工程がさらに呼ぶ工程に居る時も ★ が付き、道の工程を全部開く"""
        n = self.node
        g = {"version": graphmap.GRAPH_VERSION, "entry": "L", "sources": {}, "workflows": {
            "L": {"nodes": [n("lp", "loop", max=3, purpose="輪", body=[n("w", "ai", marker="w", purpose="書く")]),
                            n("c", "call", call="B", **{"with": {}}, purpose="呼ぶ"),
                            n("d", "call", call="M", **{"with": {}}, purpose="中を呼ぶ")]},
            "B": {"nodes": [n("b", "ai", marker="b", purpose="B の役")]},
            "M": {"nodes": [n("m", "call", call="I", **{"with": {}}, purpose="奥を呼ぶ")]},
            "I": {"nodes": [n("i", "ai", marker="i", purpose="奥の役")]}}}
        self.assertEqual(graphmap.render(g, "w", off=[]).split("\n")[3:], [
            "L（上から順に走る）:", "- ⟳3 lp: 輪", "  - ★ AI w: 書く", "- c ⇒ B: 呼ぶ", "- d ⇒ M: 中を呼ぶ",
            "B（c で走る）:", "- AI b: B の役"])
        self.assertEqual(graphmap.render(g, "i", off=[]).split("\n")[3:], [
            "L（上から順に走る）:", "- ⟳3 lp: 輪", "  - AI w: 書く", "- c ⇒ B: 呼ぶ", "- ★ d ⇒ M: 中を呼ぶ",
            "M（d で走る）:", "- ★ m ⇒ I: 奥を呼ぶ", "I（m で走る）:", "- ★ AI i: 奥の役"])


class CompactCase(unittest.TestCase):
    """地図を短く保つ描き方: 番号だけ違う同じ形の兄弟（並べの枝）は 1 行にまとめる・条件の元が地図に出ない配管なら [?]・
    枠を超える時は ★ から遠い節の目的から省く（節そのもの・★・輪・[needs] は残す）"""

    node = staticmethod(RenderCase.node)

    def lanes_graph(self, purposes, ids=("lp-1", "lp-2", "lp-3")):
        n = self.node
        body = [n(f"{i}", "loop", deps=["f"], max=9, when=f"$f.output.lane_{i[-1]} == true", purpose=p,
                  body=[n(f"r-{i[-1]}", "ai", purpose=f"枝 {i[-1]} の役")]) for i, p in zip(ids, purposes)]
        return {"version": graphmap.GRAPH_VERSION, "entry": "L", "sources": {}, "workflows": {
            "L": {"nodes": [n("f", "script", purpose="分ける"), *body, n("w", "ai", marker="w", purpose="書く")]}}}

    def test_lanes_collapse_only_when_same_but_the_number(self):
        text = graphmap.render(self.lanes_graph(["枝 1 の輪", "枝 2 の輪", "枝 3 の輪"]), "w", off=[])
        self.assertIn("- ∥ ⟳9 lp-1〜3 [f.lane_1〜3]: 枝 1〜3 の輪\n  - AI r-1〜3: 枝 1〜3 の役\n", text)
        text = graphmap.render(self.lanes_graph(["枝 1 の輪（長い）", "枝 2 の輪", "枝 3 の輪"]), "w", off=[])
        self.assertIn("- ∥ ⟳9 lp-1 [f.lane_1]: 枝 1 の輪（長い）\n  - AI r-1: 枝 1 の役\n", text)   # 目的が違えばまとめない
        self.assertIn("- ∥ ⟳9 lp-2〜3 [f.lane_2〜3]: 枝 2〜3 の輪", text)   # 同じ形の残りはまとめる
        text = graphmap.render(self.lanes_graph(["枝 1 の輪", "枝 2 の輪", "枝 4 の輪"], ids=("lp-1", "lp-2", "lp-4")),
                               "w", off=[])
        self.assertIn("lp-1〜2", text)   # 番号の続かない lp-4 はまとめない
        self.assertIn("- ∥ ⟳9 lp-4 [f.lane_4]: 枝 4 の輪", text)

    def test_only_parallel_siblings_with_the_same_deps_collapse(self):
        """番号だけ違う兄弟でも、同時に走らない（∥ でない）組・depends_on の違う組はまとめない（審査 88befff0）"""
        n = self.node
        g = {"version": graphmap.GRAPH_VERSION, "entry": "L", "sources": {}, "workflows": {"L": {"nodes": [
            n("a", "script", purpose="甲"), {**n("s-1", "loop", max=2, purpose="段 1"), "deps": ["p"]},
            {**n("s-2", "loop", max=2, purpose="段 2"), "deps": ["q"]},
            {**n("x-1", "ai", purpose="枝 1"), "deps": ["a"]}, {**n("x-2", "ai", purpose="枝 2"), "deps": ["b"]},
            {**n("y", "ai", purpose="別"), "deps": ["a"]}, {**n("z", "ai", purpose="別"), "deps": ["b"]},
            {**n("w", "ai", marker="w", purpose="書く"), "deps": ["z"]}]}}}
        text = graphmap.render(g, "w", off=[])
        self.assertNotIn("〜", text[len(graphmap.HEAD):])
        self.assertIn("- ⟳2 s-1: 段 1\n- ⟳2 s-2: 段 2\n- ∥ AI x-1: 枝 1\n- ∥ AI x-2: 枝 2", text)

    def test_condition_on_a_hidden_node_is_a_question_mark(self):
        n = self.node
        g = {"version": graphmap.GRAPH_VERSION, "entry": "L", "sources": {}, "workflows": {"L": {"nodes": [
            n("h", "script"), n("s", "script", purpose="見える"),
            {**n("a", "ai", marker="a", when="$h.output.go == true", purpose="配管が決める"), "deps": ["s"]},
            {**n("b", "ai", when="$s.output.go == true", purpose="見える節が決める"), "deps": ["a"]},
            {**n("c", "ai", when="$h.output.go == true && $s.output.x == true", purpose="混ぜ"), "deps": ["b"]}]}}}
        text = graphmap.render(g, "a", off=[])
        self.assertIn("- ★ AI a [?]: 配管が決める", text)
        self.assertIn("- AI b [s.go]: 見える節が決める", text)
        self.assertIn("- AI c [h.go && s.x]: 混ぜ", text)   # 1 つでも地図に在る節を指すなら字のまま
        g["workflows"]["L"]["nodes"].append({**n("d", "ai", when="$ARGS.x == 'y'", purpose="節を指さない"), "deps": ["c"]})
        self.assertIn("- AI d [$ARGS.x=y]: 節を指さない", graphmap.render(g, "a", off=[]))   # 節を指さない条件は字のまま

    def test_condition_on_a_switched_off_node_is_a_question_mark(self):
        """切られた節（切られた輪の中の節も）は地図に出ないので、それを指す条件も [?]"""
        n = self.node
        g = {"version": graphmap.GRAPH_VERSION, "entry": "L", "sources": {}, "workflows": {
            "L": {"nodes": [n("c", "call", call="B", **{"with": {"lanes": "$start.output.lanes"}}, purpose="呼ぶ")]},
            "B": {"nodes": [n("lp", "loop", max=2, purpose="輪", needs="lanes", body=[n("r", "ai", purpose="役")]),
                            {**n("k", "ai", when="$lp.output.go == true", purpose="輪を見る"), "deps": ["lp"]},
                            {**n("q", "ai", marker="q", when="$r.output.go == true", purpose="役を見る"), "deps": ["k"]}]}}}
        on = graphmap.render(g, "q", off=[])
        self.assertIn("- AI k [lp.go]: 輪を見る", on)
        self.assertIn("- ★ AI q [r.go]: 役を見る", on)
        cut = graphmap.render(g, "q", off=["lanes"])
        self.assertIn("- AI k [?]: 輪を見る", cut)
        self.assertIn("- ★ AI q [?]: 役を見る", cut)

    def budget_graph(self):
        n = self.node
        top = [n(f"u{i}", "call", call="B", **{"with": {}}, purpose=f"上の段 {i} の目的の文") for i in range(6)]
        top.insert(3, n("me", "ai", marker="me", purpose="★ の目的"))
        return {"version": graphmap.GRAPH_VERSION, "entry": "L", "sources": {}, "workflows": {
            "L": {"nodes": top}, "B": {"nodes": [n("lp", "loop", max=2, purpose="輪の目的", needs="x",
                                                    body=[n("r", "ai", purpose="役の目的")])]}}}

    def test_budget_drops_far_purposes_first(self):
        g = self.budget_graph()
        full = graphmap.render(g, "me", off=[], budget=None)
        self.assertNotIn(graphmap.TRIMMED.split("{")[0], full)
        lines = full.split("\n")
        cut = graphmap.render(g, "me", off=[], budget=len(full) - 1)
        self.assertLessEqual(len(cut), len(full) - 1)
        self.assertIn(graphmap.TRIMMED.format(budget=len(full) - 1), cut)
        self.assertIn("- ★ AI me: ★ の目的", cut)
        self.assertIn("- u0 ⇒ B\n", cut)              # 最も遠い（★ から 3 行・上が先）
        self.assertIn("- u2 ⇒ B: 上の段 2 の目的の文", cut)   # ★ の隣は残る
        tight = graphmap.render(g, "me", off=None, budget=1)   # 収まらなくても節は消さない（試験が枠の超えを名指す）
        for word in ("★ AI me: ★ の目的", "- u0 ⇒ B", "- u5 ⇒ B", "⟳2 lp [needs x]", "AI r"):
            self.assertIn(word, tight)
        self.assertNotIn("目的の文", tight)
        self.assertEqual(lines[:3], graphmap.HEAD.split("\n"))

    def test_budget_takes_the_entry_line_first_and_seatless_workflows_as_far(self):
        """省く順: 入口の工程の行が先。開いた工程では、★ の無い工程の行は ★ の在る工程のどの行より遠い（審査 88befff0）"""
        n = self.node
        g = {"version": graphmap.GRAPH_VERSION, "entry": "L", "sources": {}, "workflows": {
            "L": {"nodes": [n("u", "call", call="B", **{"with": {}}, purpose="入口の行の目的"),
                            n("v", "call", call="C", **{"with": {}}, purpose="次の工程")]},
            "B": {"nodes": [n("me", "ai", marker="me", purpose="★")]
                  + [{**n(f"b{i}", "ai", purpose=f"B の {i} 行目"), "deps": [f"b{i - 1}" if i else "me"]} for i in range(8)]},
            "C": {"nodes": [n("c0", "ai", purpose="C の 0 行目"), {**n("c1", "ai", purpose="C の 1 行目"), "deps": ["c0"]}]}}}
        full = graphmap.render(g, "me", off=[], budget=None)
        self.assertIn("C（v で走る）:", full)   # 席の工程の後に呼ばれる、★ の無い工程
        trimmed = graphmap.render(g, "me", off=[], budget=len(full) - 1)   # 断りの 1 行の分も含め 4 つ省けば収まる
        self.assertIn("- v ⇒ C\n", trimmed)               # 入口の工程の ★ でない行が先
        self.assertIn("- ★ u ⇒ B: 入口の行の目的", trimmed)   # ★ の行の目的は省かない
        self.assertIn("- AI c0\n", trimmed)               # 次は ★ の無い工程の行を、
        self.assertTrue(trimmed.endswith("\n- AI c1"), trimmed)
        self.assertIn("- AI b6: B の 6 行目", trimmed)     # ★ の在る工程の遠い行より先に省く
        self.assertIn("- AI b7\n", trimmed)

    def test_budget_is_the_default_and_deterministic(self):
        g = self.budget_graph()
        self.assertEqual(graphmap.render(g, "me", off=[]), graphmap.render(g, "me", off=[], budget=graphmap.MAP_BUDGET))
        self.assertEqual(graphmap.render(g, "me", off=[], budget=200), graphmap.render(g, "me", off=[], budget=200))


class StaleCase(unittest.TestCase):
    def test_stale_names_changed_sources_and_cli_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = pathlib.Path(tmp) / "pack"
            shutil.copytree(SEED, pack)
            run = lambda *a: subprocess.run([sys.executable, str(ROOT / "dev" / "graphmap_build.py"), *a, str(pack)],  # noqa: E731
                                            capture_output=True, text=True, encoding="utf-8",
                                            env=hermetic.child_env(PYTHONDONTWRITEBYTECODE="1"))
            self.assertEqual(run("check").returncode, 1)   # まだ書いていない
            self.assertEqual(run("build").returncode, 0)
            self.assertEqual(run("check").returncode, 0)
            g = graphmap.load(pack / "line" / "line.graph.json")
            self.assertEqual(graphmap.stale(g, pack), [])
            p = pack / "blk-b" / "blk-b.yaml"
            p.write_text(p.read_text(encoding="utf-8").replace("枝 1 の役", "枝 1 の役（替えた）"), encoding="utf-8")
            self.assertEqual(graphmap.stale(g, pack), ["blk-b/blk-b.yaml"])
            r = run("check")
            self.assertEqual(r.returncode, 1)
            self.assertIn("line/line.graph.json が古い", r.stderr)
            (pack / "blk-a" / "blk-a.yaml").unlink()
            self.assertEqual(graphmap.stale(g, pack), ["blk-a/blk-a.yaml", "blk-b/blk-b.yaml"])


def real_graph() -> dict:
    eps = graphmap.entrypoints(ROOT)
    (name, rel), = eps.items()
    return graphmap.load(graphmap.graph_path(ROOT, rel))


class RealLineCase(unittest.TestCase):
    """本物の pack（works/）の地図の元"""

    PURPOSE_MAX = 100   # 節の目的の 1 行の字数の枠

    def test_graph_file_is_fresh(self):
        """地図の元は今の YAML から組み直した物と同じ（替えたら dev/graphmap_build.py build works で書き直す）"""
        resolve = graphmap.pack_resolver(ROOT, yaml.safe_load)
        for name, rel in graphmap.entrypoints(ROOT).items():
            with self.subTest(name):
                path = graphmap.graph_path(ROOT, rel)
                self.assertTrue(path.is_file(), f"{path} が無い")
                self.assertEqual(path.read_text(encoding="utf-8"), graphmap.dumps(graphmap.build(ROOT / rel, resolve, ROOT, yaml.safe_load)),
                                 f"{path.name} が YAML より古い。`uv run --no-project --with pyyaml python3 works/dev/graphmap_build.py "
                                 f"build works` で書き直す")

    def flagged(self, g):
        return sorted(m for m, places in graphmap.markers(g).items()
                      for wf, nid in places if "map" in (find(g["workflows"][wf]["nodes"], nid).get("flags") or []))

    def test_flagged_nodes_are_the_planner_conversation(self):
        """持ち主 2026-10-07: 地図は旗 map の節だけ。今は修正案の役の会話（修正案・直し・範囲の相談の答え）だけ。修正役の並べの枝の
        答えの節（旗 fork）は修正案の役の会話の写しを継ぐので同じ席に入り、同じ地図を受ける"""
        g = real_graph()
        seat = {"plan", "plan-revise", "plan-answer", "plan-answer-ruled",
                "plan-answer-lane-1", "plan-answer-lane-2", "plan-answer-lane-3"}
        self.assertEqual(set(self.flagged(g)), seat)
        self.assertEqual(graphmap.seat(g, "plan-answer"), ("plan", seat))
        self.assertEqual(graphmap.render(g, "plan-answer-lane-1", off=[]), graphmap.render(g, "plan", off=[]))

    def test_seats_agree_on_the_flag(self):
        """会話を共にする節は旗 map が揃う（同じ会話の起動ごとに system prompt が替わると prompt のキャッシュが切れる）"""
        g = real_graph()
        flagged = set(self.flagged(g))
        for m in graphmap.markers(g):
            _, members = graphmap.seat(g, m)
            with self.subTest(m):
                self.assertTrue(members <= flagged or not (members & flagged), sorted(members))

    def test_flagged_maps_fit_and_name_every_purpose(self):
        """地図は枠の中（超える分は ★ から遠い節の目的を省いて収める。節の行は減らさない）。YAML は地図に載る節の全部に目的を持つ"""
        g = real_graph()
        for m in self.flagged(g):
            for off in (None, []):
                with self.subTest(m, off=off):
                    text = graphmap.render(g, m, off=off)
                    full = graphmap.render(g, m, off=off, budget=None)
                    self.assertLessEqual(len(text), graphmap.MAP_BUDGET)
                    self.assertEqual(len(text.splitlines()) - (text != full), len(full.splitlines()))
                    for line in full.splitlines():
                        if line.lstrip().startswith("- ") and ("AI " in line or "⟳" in line or "⇒" in line):
                            self.assertIn(": ", line.split("]")[-1] if "]" in line else line, f"目的の 1 行が無い: {line}")

    def test_planner_map_names_the_downstream_lanes(self):
        """修正案の役が知る後の流れ: 項目は修正の段で枝に分かれて同時に走り、3 方向で合わさる（canary3 の動機）"""
        text = graphmap.render(real_graph(), "plan", off=[])
        for word in ("★ AI plan:", "tdd-fork", "∥ ⟳40 tdd-lane-loop-1〜3", "  - AI tdd-lane-1〜3 [?]:", "tdd-join", "3 方向",
                     "fix-fork", "∥ ⟳18 fix-lane-loop-1〜3", "  - AI fix-lane-1〜3 [?]:", "★ AI plan-answer-lane-1〜3", "fix-join",
                     "★ AI plan-answer", "AI plan-review"):
            self.assertIn(word, text)   # 枝の 3 本は番号だけ違う同じ形なので 1 行（YAML の目的を枝ごとに同じ字にしておく）
        for line in text.splitlines():
            if line.lstrip().startswith("- ") and "★" in line:
                self.assertIn(": ", line, f"★ の行は目的を省かない: {line}")
        off = graphmap.render(real_graph(), "plan", off=["tdd_lanes"])
        self.assertNotIn("tdd-lane-loop-1", off)
        self.assertIn("(off: tdd_lanes)", off)

    def test_optional_stages_are_declared_on_the_line(self):
        """落ちても線を止めない足しの検査の段（目・レンズ・構造・直しの後の測り・世界の解）だけが optional: true を持つ。修正の本体・
        判定・計画・最後のテスト・CI・差分の審査・素材集めと境の節は持たない。印は目的の文に残らない"""
        g = real_graph()
        nodes = g["workflows"][g["entry"]]["nodes"]
        purposes = {"eyeing": "独立の目（冗長と最小性・独立設計との比較・整合・範囲）",
                    "lensing": "修正の後の局所レビュー（レンズ）",
                    "structuring": "判定の単位が名指すファイルの構造を実測し、汚れるかを判定する",
                    "measuring-after": "直しの後の差分で、設計の考えを知る場所の増減・新しい名・写しの塊を測る",
                    "worlding": "依頼の行を問題の類に言い直し、世の中の定石を集めて依頼の解き方と比べる"}
        for nid, purpose in purposes.items():
            with self.subTest(nid):
                node = find(nodes, nid)
                self.assertIs(node.get("optional"), True, f"{nid} に optional: true が無い")
                self.assertEqual(node.get("purpose"), purpose, "目的の文に印が残っている（印は欄 optional に切り出す）")
        for nid in ("fixing", "refitting", "judging", "planning", "testing", "ci-final", "reviewing", "gathering",
                    "h-ci", "h-final"):
            with self.subTest(nid):
                self.assertFalse(find(nodes, nid).get("optional"), f"{nid} は落ちたら線を止める節で optional でない")

    def test_descriptions_are_one_short_line(self):
        for p in sorted(ROOT.glob("*/*.yaml")):
            if p.stem != p.parent.name:
                continue
            raw = yaml.safe_load(p.read_text(encoding="utf-8"))["nodes"]
            stack = list(raw)
            while stack:
                n = stack.pop()
                stack.extend((n.get("loop_group") or {}).get("nodes") or [])
                if "description" in n:
                    with self.subTest(f"{p.name}:{n['id']}"):
                        self.assertIsInstance(n["description"], str)   # Archon の節の型は string
                        self.assertNotIn("\n", n["description"].strip())
                        self.assertLessEqual(len(n["description"]), self.PURPOSE_MAX)

    def test_machine_headings_are_declared_sections(self):
        """考え prompt-sections の範囲の正本: 役の支度のモジュールの docstring でない全部の字面（ast の Constant・f-string の字の破片・
        + の連結の各項）で、`#` の見出しの行を持つ物（f"## {X}" の破片 '## ' も）は、モジュールの直下の
        `<名> = promptsection.Section(...)` の最初の引数に在る。見出しを貼るのでなく読む所（re の関数・str の照らしの method の引数・
        比べの項）は外す"""
        bad = []
        for p in prep_files():
            tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
            skip = docstring_constants(tree) | reading_constants(tree) | declared_constants(tree)
            for n in ast.walk(tree):
                if (isinstance(n, ast.Constant) and isinstance(n.value, str) and id(n) not in skip
                        and HEADING_LINE.search(n.value)):
                    bad.append(f"{p.relative_to(ROOT)}:{n.lineno}")
        self.assertEqual(bad, [], f"Section の宣言の外に見出しの字面が {len(bad)} 本ある:\n" + "\n".join(bad[:40]))

    def test_section_declarations_resolve(self):
        """全部の Section は出どころが解ける。board:<モジュール>.<定数> は持ち主の定数が引けて str、fn:<モジュール>.<関数> は関数として引け、
        input:<名> はブロックの lib に在る Section だけが使えて、そのブロックの YAML の inputs: に在る。役の文脈の節は source を、
        人向けの節は human に理由を持つ"""
        found = all_sections()
        self.assertTrue(found, "Section の宣言が 1 つも無い")
        for path, name, sec in found:
            where = f"{path.relative_to(ROOT)}:{name}"
            with self.subTest(where):
                self.assertTrue(sec.source or sec.human, f"{where}: source も human も空（出どころか人向けの理由が要る）")
                if not sec.source:
                    continue
                kind, _, rest = sec.source.partition(":")
                self.assertIn(kind, ("input", "board", "fn"), f"{where}: source の形が input:・board:・fn: のどれでもない: {sec.source}")
                if kind == "input":
                    self.assertEqual(path.parent.name, "lib", f"{where}: input: はブロックの lib の Section だけが使える")
                    block = path.parent.parent
                    self.assertTrue(block.name.startswith("blk-"), f"{where}: input: はブロックの lib の Section だけが使える")
                    inputs = yaml.safe_load((block / f"{block.name}.yaml").read_text(encoding="utf-8")).get("inputs") or {}
                    self.assertIn(rest, inputs, f"{where}: {block.name}.yaml の inputs: に {rest} が無い")
                    continue
                mod, _, attr = rest.rpartition(".")
                self.assertTrue(mod and attr, f"{where}: <モジュール>.<名> の形でない: {sec.source}")
                target = getattr(import_named(mod, path.parent), attr, None)
                if kind == "board":
                    self.assertIsInstance(target, str, f"{where}: {rest} が持ち主の str の定数として引けない")
                else:
                    self.assertTrue(callable(target), f"{where}: {rest} が関数として引けない")

    def test_receives_match_the_code(self):
        """受け手の役の側の表 RECEIVES（その役の指示書を組むモジュールの直下。ブロックの lib と、指示書を組む core の L4 のモジュール）
        の各行: role はそのブロックの工程の graph の印の名に在り、when の関数は引けて、その関数の本体が行の Section の定数を参照する
        （使わない関数の名を書いた古い行は落ちる）。人向けでない Section はどれも、少なくとも 1 つのブロックの RECEIVES の行に在る
        （受け手の無い貼る節は落ちる）。逆の向きも照らす: ブロックのモジュールが人向けでない Section の定数を使うか、ほかの行の
        when に名指された core の関数を呼べば、そのブロックの RECEIVES にその節の行が在る（別のブロックが同じ節を貼り始めて
        行が増えないまま緑、を落とす）。RECEIVES を持つ core のモジュールは、ブロックに結んだ L4 だけ"""
        g = real_graph()
        roles = {}
        for marker, places in graphmap.markers(g).items():
            for wf, _ in places:
                roles.setdefault(wf, set()).add(marker)
        names = {}   # Section の値（字）→ それを持つ定数の名
        for _, name, sec in all_sections():
            names.setdefault(str(sec), set()).add(name)
        homes = assemblers()
        owned = {p for p, _ in homes}
        stray = [p.relative_to(ROOT).as_posix() for p in sorted(CORE.glob("*.py"))
                 if p not in owned and re.search(r"(?m)^RECEIVES\b", p.read_text(encoding="utf-8"))]
        self.assertEqual(stray, [], "指示書を組むブロックに結ばない core のモジュールが RECEIVES を持つ（置き場は tests/test_layers.py の MOD の L4）")
        rows = []    # (ブロック, 読んだ物の場所, 行)
        for p, block in homes:
            if re.search(r"(?m)^RECEIVES\b", p.read_text(encoding="utf-8")):
                rows.extend((block, p, r) for r in getattr(load_prep(p), "RECEIVES", ()))
        self.assertTrue(rows, "RECEIVES の行が 1 つも無い")
        listed = set()
        by_block = {}    # ブロック → 受ける節の字
        by_when = {}     # 入る条件の関数の完全な名 → 受ける節の字
        for block, path, row in rows:
            where = f"{path.relative_to(ROOT)}: {row.role} <- {row.section}"
            with self.subTest(where):
                listed.add(str(row.section))
                by_block.setdefault(block, set()).add(str(row.section))
                by_when.setdefault(row.when, set()).add(str(row.section))
                self.assertIn(row.role, roles.get(block, set()), f"{where}: {block} の工程の graph に印 {row.role} が無い")
                mod, _, func = row.when.rpartition(".")
                self.assertTrue(mod and func, f"{where}: when が <モジュール>.<関数> の形でない: {row.when!r}")
                fn = getattr(import_named(mod, path.parent), func, None)
                self.assertTrue(callable(fn), f"{where}: when の関数 {row.when} が引けない")
                body = ast.parse(textwrap.dedent(inspect.getsource(fn)))
                used = {n.id for n in ast.walk(body) if isinstance(n, ast.Name)} | {n.attr for n in ast.walk(body) if isinstance(n, ast.Attribute)}
                self.assertTrue(used & names.get(str(row.section), set()),
                                f"{where}: {row.when} の本体が Section の定数 {sorted(names.get(str(row.section), set()))} を参照しない")
        orphans = sorted(f"{path.relative_to(ROOT)}:{name}" for path, name, sec in all_sections()
                         if not sec.human and str(sec) not in listed)
        self.assertEqual(orphans, [], "どのブロックの RECEIVES にも無い貼る節（受け手の無い節）がある")
        for path, block in homes:   # 逆の向き: コードが使う節・呼ぶ条件の関数 → そのブロックの RECEIVES の行
            used_sections, called = used_in_code(path, load_prep(path))
            want = {s for s, v in used_sections.items() if not v.human}
            for func in called:
                want |= by_when.get(func, set())
            missing = sorted(s.splitlines()[0] for s in want if s not in by_block.get(block, set()))
            with self.subTest(f"{path.relative_to(ROOT)} が使う節の行"):
                self.assertEqual(missing, [], f"{path.relative_to(ROOT)} が使う節に、{block} の RECEIVES の行が無い（受け手の役と入る条件を足す）")

    def test_feature_word_and_constants_agree(self):
        self.assertIn(adapter.MAP_FEATURE, entry.FEATURES)
        self.assertEqual(adapter.FEATURES_KEY, entry.FEATURES_KEY)
        self.assertEqual(adapter.FEATURES_CUT_KEY, entry.FEATURES_CUT_KEY)
        self.assertIn(adapter.MAP, node_marker.FLAGS)


class InjectCase(unittest.TestCase):
    """包みの差し込みの表（adapter.INJECTORS と adapter.inject）を、adapter.plan を直に呼んで見る"""

    WEB = "Read,Grep,Glob,WebSearch,WebFetch"

    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = pathlib.Path(tmp.name).resolve()
        (self.tmp / "wt").mkdir()
        self.board = self.tmp / "board"
        (self.board / "r1").mkdir(parents=True)

    def start_doc(self, off, cut=None):
        doc = {"features_off": off} if cut is None else {"features_off": off, "features_cut": cut}
        (self.board / "r1" / "start.json").write_text(json.dumps(doc), encoding="utf-8")

    def plan(self, marker, tools=WEB, extra=(), board=True):
        schema = json.dumps({"type": "object", "description": marker, "properties": {}})
        argv = ["--output-format", "stream-json", "--json-schema", schema, "--tools", tools,
                "--setting-sources=project,user", *extra]
        return adapter.plan(argv, self.tmp / "wt", self.tmp / "home", "true", env={"PATH": "/usr/bin:/bin"},
                            board=(lambda: str(self.board)) if board else None)

    @staticmethod
    def appended(p):
        vals = [p.argv[i + 1] for i, a in enumerate(p.argv) if a == "--append-system-prompt"]
        return vals

    def test_map_flag_appends_the_map_after_the_query_rule(self):
        self.start_doc([])
        p = self.plan("works-node: plan map")
        self.assertEqual(p.mode, "merged", p.why)
        vals = self.appended(p)
        self.assertEqual(len(vals), 1)
        want = graphmap.render(real_graph(), "plan", off=[])
        rule = adapter.query_rule()
        self.assertEqual(vals[0], adapter.QUERY_RULE_LEAD + "\n" + rule + "\n\n" + want)
        self.assertEqual(p.fence["graph_map"], hashlib.sha256(want.encode("utf-8")).hexdigest()[:16])
        self.assertEqual(p.fence["query_rule"], hashlib.sha256(rule.encode("utf-8")).hexdigest()[:16])   # 前と同じ値

    def test_same_system_prompt_across_the_planner_conversation(self):
        """continue= の起動は相手の会話の id が要るので、表を Launch で直に当てる"""
        self.start_doc([])
        texts = set()
        for name, cont in (("plan", None), ("plan-revise", "plan"), ("plan-answer", "fix-planner"),
                           ("plan-answer-ruled", "fix-planner")):
            out, fence = adapter.inject([], adapter.Launch(name, cont, ("map",), frozenset({"Read"}), False,
                                                           lambda: str(self.board)))
            texts.add(out[-1])
        self.assertEqual(len(texts), 1)

    def test_concept_map_row_appends_the_map_section(self):
        """旗 concept-map の起動に、考えの住処の地図の節（core の concepthome.section。対象の根は盤面の inputs.cwd）を足す
        （計画 2026-10-09-clean-whole の Task 2.7。指示書の組み立てに引数を足さず、差し込みの表の 1 行から配る）"""
        import concepthome
        self.start_doc([])
        (self.board / "state.json").write_text(json.dumps({"inputs": {"cwd": str(self.tmp / "wt")}}), encoding="utf-8")
        p = self.plan("works-node: plan-review concept-map")
        self.assertIn("concept_map", p.fence)
        self.assertIn("## 考えの住処の地図", self.appended(p)[0])
        self.assertNotIn("concept_map", self.plan("works-node: plan-review").fence)
        rows = [i.name for i in adapter.INJECTORS]
        self.assertEqual(rows.count("concept_map"), 1)
        self.assertIn(concepthome.MAP_NAME, self.appended(p)[0])

    def test_concept_map_without_board_state_skips(self):
        self.start_doc([])
        self.assertIn("skipped", self.plan("works-node: plan-review concept-map").fence["concept_map"])

    def test_unflagged_and_tool_less(self):
        self.start_doc([])
        p = self.plan("works-node: plan")
        self.assertNotIn("graph_map", p.fence)
        self.assertNotIn("# 工程の地図", self.appended(p)[0])
        p = self.plan("works-node: plan map", tools="")
        self.assertNotIn("query_rule", p.fence)   # 道具ゼロは規律を足さない
        self.assertTrue(self.appended(p)[0].startswith("# 工程の地図"))

    def test_features_off_graph_map_skips(self):
        self.start_doc(["graph_map"])
        p = self.plan("works-node: plan map")
        self.assertEqual(p.mode, "merged", p.why)
        self.assertEqual(p.fence["graph_map"], {"skipped": "入力 features_off の graph_map で切った run"})
        self.assertNotIn("# 工程の地図", self.appended(p)[0])

    def test_default_off_features_reach_the_map(self):
        """start の控えの実効で off の機能（features_cut。既定で off の judge_verify を含む）を地図が切った物として描く。
        欄の無い前の版の控えは features_off だけ（前の版の既定は全部 on）"""
        self.start_doc([], cut=["judge_verify"])
        self.assertIn("(off: verify)", self.appended(self.plan("works-node: plan map"))[0])
        self.start_doc([])
        self.assertNotIn("(off: verify)", self.appended(self.plan("works-node: plan map"))[0])
        self.start_doc([], cut=["graph_map"])
        self.assertIn("skipped", self.plan("works-node: plan map").fence["graph_map"])

    def test_run_switches_reach_the_map(self):
        self.start_doc(["tdd_lanes"])
        text = self.appended(self.plan("works-node: plan map"))[0]
        self.assertNotIn("tdd-lane-loop-1", text)
        self.assertIn("(off: tdd_lanes)", text)

    def test_no_board_keeps_conditions(self):
        text = self.appended(self.plan("works-node: plan map", board=False))[0]
        self.assertIn("[needs tdd_lanes]", text)

    def test_malformed_features_skip_but_launch(self):
        """控えの切った機能の欄が語の配列でなければ地図を足さずに起こす（足す物なので。控えそのものが読めない起動は 18 の
        形の柵が拒む）"""
        self.start_doc("graph_map")
        p = self.plan("works-node: plan map")
        self.assertEqual(p.mode, "merged", p.why)
        self.assertIn("skipped", p.fence["graph_map"])

    def test_stale_graph_skips(self):
        with tempfile.TemporaryDirectory() as tmp:
            pack = pathlib.Path(tmp) / "pack"
            shutil.copytree(SEED, pack)
            (pack / "line" / "line.graph.json").write_text(graphmap.dumps(seed_graph(pack)), encoding="utf-8")
            got = adapter.graph_map_text("writer", [], pack=pack)
            self.assertIsInstance(got, adapter.Block)
            self.assertEqual(got.text, graphmap.render(seed_graph(pack), "writer", off=[]))
            p = pack / "blk-a" / "blk-a.yaml"
            p.write_text(p.read_text(encoding="utf-8") + "\n", encoding="utf-8")
            got = adapter.graph_map_text("writer", [], pack=pack)
            self.assertIsInstance(got, adapter.Skip)
            self.assertIn("blk-a/blk-a.yaml", got.why)
            self.assertIsInstance(adapter.graph_map_text("nobody", [], pack=pack), adapter.Skip)
            with mock.patch.object(adapter, "PACK", pack):
                self.start_doc([])
                p = self.plan("works-node: writer map")
                self.assertEqual(p.mode, "merged", p.why)
                self.assertIn("古い", p.fence["graph_map"]["skipped"])

    def test_malformed_graph_file_skips_but_launches(self):
        """地図の元の JSON の中の形が崩れても（手で書き換えた）、包みは落ちずに地図を足さずに起こす"""
        with tempfile.TemporaryDirectory() as tmp:
            pack = pathlib.Path(tmp) / "pack"
            shutil.copytree(SEED, pack)
            g = seed_graph(pack)
            find(g["workflows"]["line"]["nodes"], "doing")["with"] = []
            (pack / "line" / "line.graph.json").write_text(graphmap.dumps(g), encoding="utf-8")
            with mock.patch.object(adapter, "PACK", pack):
                self.start_doc([])
                p = self.plan("works-node: writer map")
            self.assertEqual(p.mode, "merged", p.why)
            self.assertIn("skipped", p.fence["graph_map"])

    def test_append_file_refuses_only_when_a_required_block_is_there(self):
        self.start_doc([])
        f = self.tmp / "sp.md"
        f.write_text("x", encoding="utf-8")
        p = self.plan("works-node: plan map", extra=["--append-system-prompt-file", str(f)])
        self.assertEqual(p.mode, "refused")
        self.assertIn("検索語の規律", p.why)
        p = self.plan("works-node: plan map", tools="", extra=["--append-system-prompt-file", str(f)])
        self.assertEqual(p.mode, "merged", p.why)
        self.assertIn("append-system-prompt-file", p.fence["graph_map"]["skipped"])
        self.assertEqual(self.appended(p), [])

    def test_sdk_value_is_kept_in_front(self):
        self.start_doc([])
        p = self.plan("works-node: plan map", extra=["--append-system-prompt=SDK の本文"])
        vals = [a for a in p.argv if a.startswith("--append-system-prompt=")]
        self.assertEqual(len(vals), 1)
        self.assertTrue(vals[0].startswith("--append-system-prompt=SDK の本文\n\n" + adapter.QUERY_RULE_LEAD))
        self.assertTrue(vals[0].endswith(graphmap.render(real_graph(), "plan", off=[])))

    def test_registry_contract(self):
        """表に 1 行足せば差し込みが増える: 順のとおりに繋ぎ、塊ごとに digest を名で残す。Skip は理由を残し、required の
        失敗は拒む（Unrecognised）"""
        launch = adapter.Launch("x", None, ("map",), frozenset(), True, lambda: None)
        rows = (adapter.Injector("a", "甲", lambda l: True, lambda l: adapter.block("A"), True),
                adapter.Injector("b", "乙", lambda l: False, lambda l: adapter.block("B"), False),
                adapter.Injector("c", "丙", lambda l: True, lambda l: adapter.Skip("無い"), False),
                adapter.Injector("d", "丁", lambda l: True, lambda l: adapter.block("D", of="d"), False),
                adapter.Injector("e", "戊", lambda l: True, lambda l: (_ for _ in ()).throw(ValueError("壊れた")), False),
                adapter.Injector("f", "己", lambda l: True, lambda l: (_ for _ in ()).throw(TypeError("型")), False))
        out, fence = adapter.inject(["--x"], launch, rows)
        self.assertEqual(out, ["--x", "--append-system-prompt", "A\n\nD"])
        self.assertEqual(fence, {"a": hashlib.sha256(b"A").hexdigest()[:16], "c": {"skipped": "無い"},
                                 "d": hashlib.sha256(b"d").hexdigest()[:16], "e": {"skipped": "ValueError: 壊れた"},
                                 "f": {"skipped": "TypeError: 型"}})
        self.assertEqual(adapter.inject(["--x"], launch, rows[1:3]), (["--x"], {"c": {"skipped": "無い"}}))
        bad = (adapter.Injector("a", "甲", lambda l: True, lambda l: adapter.Skip("無い"), True),)
        with self.assertRaises(adapter.Unrecognised) as cm:
            adapter.inject([], launch, bad)
        self.assertIn("甲を足せない", str(cm.exception))
        with self.assertRaises(adapter.Unrecognised):
            adapter.inject(["--append-system-prompt", "a", "--append-system-prompt", "b"], launch, rows[:1])

    def test_registry_order(self):
        self.assertEqual([i.name for i in adapter.INJECTORS], ["query_rule", "graph_map", "text_reply", "concept_map"])
        self.assertEqual([i.required for i in adapter.INJECTORS], [True, False, True, False])


if __name__ == "__main__":
    unittest.main()
