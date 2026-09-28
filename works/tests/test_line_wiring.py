"""ライン darkfactory の配線と筋書き（fixtures/）の形の突き合わせ。YAML と JSON を読むだけ（FAST。git・子のプロセスなし）。

- 表（nodes.json）が役・任せ先に置いた節の置き場のブロックが、ラインに include されている（test_table_role_nodes_are_wired。
  run 28 は p2.rejudge の blk-rejudge を配線し忘れ、最後のテストが出なかった。前は重い段の test_line に在り、速い段で見えなかった）
- 全部の筋書き（works/*/fixtures/*.stubs.yaml）で、同じ節の stub は同じ鍵の組を持つ（test_same_node_stubs_share_keys）。
  節は (ブロック, 節の id) で同じと見る: ブロックの筋書きの鍵はそのブロックの節の id、ラインの筋書きの鍵は模擬実行の鍵
  （include の中は <include>__<節>、輪の中は名前空間なしの id）をブロックの節に引き戻す。組が違ってよいのは MAY_LACK に
  理由つきで名指した欄だけ（run 28 の merge の後、conflict-ask・rejudge・rejudge-no-session の 3 本が輪の受け付けの done と
  premising__intake の go を欠いたまま残り、模擬実行でしか見えなかった）
"""
import collections
import json
import pathlib
import re
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
LINE = ROOT / "darkfactory"
NOT_STUBS = frozenset({"fixture", "exec-code"})   # 筋書きの鍵のうち stub でない物

# 表（nodes.json）が役・任せ先（role・engine_run）に置いた節のうち、置き場（where）のブロックがまだラインに include されていない物
# {表の節: 理由}。減らす方向にだけ変える（配線したら消す。run 28 は p2.rejudge の blk-rejudge を配線し忘れ、最後のテストが出なかった）
NOT_WIRED_YET = {}

# 同じ節の stub のうち、筋書きによって無くてよい欄 {(ブロック, 節): (欄の組, 理由)}。減らす方向にだけ変える
# （どの筋書きでも揃った欄は消す。test_may_lack_is_live が赤にする）
MAY_LACK = {
    ("blk-delta", "review"): ({"faces_none"}, "faces が空の返答だけが書く欄（bad-cite は faces を持つ返答）"),
    ("blk-spec", "spec-review"): ({"faces_none"}, "faces が空の返答だけが書く欄（pass は faces を持つ返答）"),
    ("blk-fix", "fix"): ({"conflicts"}, "食い違いの申し出を出す返答（conflict・conflict-ask）だけが持つ欄"),
    ("blk-fix", "fix-accept"): ({"parked"}, "申し出で単位を止めた受け付けの返り（conflict・conflict-ask）だけが持つ欄"),
    ("blk-fix", "tdd"): ({"units", "unit_key", "what"},
                         "段（phase）ごとに欄が違う（route は units、単位の段 red・green・refactor は unit_key・what）"),
    ("blk-plan", "plan-accept"): ({"asking", "halted", "out_file", "ready"},
                                  "拒否（ok: false）の返りは盤面に渡していないので、盤面の欄を持たない（give-up・plan-rejected）"),
    ("blk-fix", "collect"): ({"coverage", "fix_file", "not_done", "reads_file"},
                             "ラインの筋書きは 1 本目の欄と tdd だけを置く（盤面から足す 4 欄。ラインの下流はどれも読まない）"),
    ("blk-delta", "review-accept"): ({"review_file"},
                                     "ラインの筋書きは古い受け付けの欄 review_file を持つ（今の受け付けは返さない。下流は done と "
                                     "reason_file だけを読む）"),
}


def load(path):
    return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))


def line():
    return load(LINE / "darkfactory.yaml")


def block(name):
    return load(ROOT / name / f"{name}.yaml")


def walk(nodes):
    """(節, 輪の中か) を入れ子も辿って"""
    for n in nodes:
        yield n, False
        if "loop_group" in n:
            for m in n["loop_group"]["nodes"]:
                yield m, True


def line_stub_owner():
    """ラインの筋書きの鍵 → (ブロック, 節)。include の中は <include>__<節>、輪の中は名前空間なしの id（Archon の dry-run の鍵）。
    ラインの節はそのまま ("darkfactory", 節)"""
    owner = {}
    for n in line()["nodes"]:
        if "include" in n:
            for m, inner in walk(block(n["include"])["nodes"]):
                owner[m["id"] if inner else f"{n['id']}__{m['id']}"] = (n["include"], m["id"])
        else:
            owner[n["id"]] = ("darkfactory", n["id"])
    return owner


def fixture_files():
    return sorted(ROOT.glob("*/fixtures/*.stubs.yaml"))


def stub_key_sets(files=None):
    """{(ブロック, 節): {筋書きのパス（works の根から）: 鍵の組}}。stub が dict でなければ鍵の組は None"""
    owner = line_stub_owner()
    out = collections.defaultdict(dict)
    for p in fixture_files() if files is None else files:
        folder = p.parent.parent.name
        for key, stub in (load(p) or {}).items():
            if key in NOT_STUBS:
                continue
            nid = owner.get(key, ("darkfactory", key)) if folder == "darkfactory" else (folder, key)
            out[nid][str(p.relative_to(ROOT))] = frozenset(stub) if isinstance(stub, dict) else None
    return out


class TableWiringCase(unittest.TestCase):
    def test_table_role_nodes_are_wired(self):
        """表が role・engine_run（任せ先が role の物を含む）に置いた節は、置き場（where）にラインから届く: where がブロックなら
        darkfactory.yaml がそのブロックを include し、そうでなければ where はラインの節の id（start など）。
        届かない節は NOT_WIRED_YET に理由つきで名指す（減らす方向だけ）"""
        table = json.loads((LINE / "nodes.json").read_text(encoding="utf-8"))["nodes"]
        ids = {n["id"] for n in line()["nodes"]}
        included = {n["include"] for n in line()["nodes"] if "include" in n}
        unreached = {}
        for nid, row in table.items():
            if row["by"] not in ("role", "engine_run"):
                continue
            where = row.get("where")
            with self.subTest(nid):
                self.assertTrue(where, "role・engine_run の節は where を持つ")
                if where.startswith("blk-"):
                    self.assertTrue((ROOT / where / f"{where}.yaml").is_file(), f"置き場のブロック {where} が無い")
                    if where not in included:
                        unreached[nid] = where
                else:
                    self.assertIn(where, ids, f"where {where} がラインの節に無い")
        self.assertEqual(set(unreached), set(NOT_WIRED_YET),
                         f"表の置き場のブロックがラインに include されていない: {unreached}（配線するか、"
                         "NOT_WIRED_YET に理由つきで名指す。配線した節は NOT_WIRED_YET から消す）")
        for nid, why in NOT_WIRED_YET.items():
            self.assertTrue(why.strip(), f"NOT_WIRED_YET の {nid} に理由が無い")


class FixtureStubKeysCase(unittest.TestCase):
    def test_fixtures_found(self):
        """筋書きの glob が空なら下の突き合わせは何も見ない"""
        self.assertTrue([p for p in fixture_files() if p.parent.parent.name == "darkfactory"])
        self.assertGreater(len({p.parent.parent.name for p in fixture_files()}), 1)

    def test_same_node_stubs_share_keys(self):
        """同じ節の stub は、どの筋書きでも同じ鍵の組を持つ（無くてよいのは MAY_LACK の欄だけ）。merge で片方の筋書きにだけ
        欄が足されると、足されなかった筋書きの模擬実行は when: で飛ぶか下流が落ちる（run 28 の後の 3 本）"""
        for nid, per_file in sorted(stub_key_sets().items()):
            if len(per_file) < 2:
                continue
            with self.subTest(f"{nid[0]}/{nid[1]}"):
                self.assertNotIn(None, per_file.values(), f"dict でない stub: {per_file}")
                full = frozenset().union(*per_file.values())
                allowed = MAY_LACK.get(nid, (set(), ""))[0]
                bad = {f: sorted(full - keys) for f, keys in per_file.items() if not (full - keys) <= allowed}
                self.assertEqual(bad, {}, f"同じ節の stub に欄の欠け（筋書き: 欠けた欄）。欠けた欄を足すか、筋書きによって"
                                          f"無くてよい欄なら MAY_LACK に理由つきで名指す（全部の鍵: {sorted(full)}）")

    def test_may_lack_is_live(self):
        """MAY_LACK の欄は、その節の stub のどれかに在り、どれかに無い（揃ったら消す。減らす方向だけ）。理由は空でない"""
        seen = stub_key_sets()
        for nid, (keys, why) in MAY_LACK.items():
            with self.subTest(f"{nid[0]}/{nid[1]}"):
                self.assertTrue(why.strip())
                self.assertIn(nid, seen, "どの筋書きもこの節を stub しない。MAY_LACK から消す")
                sets = list(seen[nid].values())
                for k in sorted(keys):
                    self.assertTrue(any(k in s for s in sets) and any(k not in s for s in sets),
                                    f"{k} はどの筋書きでも揃っている（か、どこにも無い）。MAY_LACK から消す")


class ReportAfterFailureCase(unittest.TestCase):
    def test_report_runs_after_failed_upstream(self):
        """機械の報告 report は上流の節が落ちた run でも走り（all_done。run 30・31 では飛ばされ、result が $report.output の
        binding で落ちて報告が残らなかった）、start のほかの節の出力は落ちても飛ばされても if_skipped: null で受ける"""
        n = next(n for n in line()["nodes"] if n["id"] == "report")
        self.assertEqual(n.get("trigger_rule"), "all_done")
        for k, v in (n.get("with") or {}).items():
            src = v.get("from") if isinstance(v, dict) else v if isinstance(v, str) else ""
            if set(re.findall(r"\$([A-Za-z][\w-]*)\.output", src)) - {"start"}:
                with self.subTest(k):
                    self.assertIsInstance(v, dict)
                    self.assertIn("if_skipped", v)
                    self.assertIsNone(v["if_skipped"])


class LangInputCase(unittest.TestCase):
    """報告の言語を利用者が渡す口（本線 loop.py の --lang の写し）: ラインの入力 lang が start の with に渡り、
    入口の check_inputs がそれを返す（空は空のまま。盤面の既定 LANG_DEFAULT が効く）"""

    def test_line_passes_lang_to_start(self):
        doc = line()
        self.assertIn("lang", doc["inputs"])
        start = next(n for n in doc["nodes"] if n["id"] == "start")
        self.assertEqual(start["with"].get("lang"), "$INPUTS.lang")

    def test_start_script_reads_lang(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("start_script", LINE / "scripts" / "start.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.INPUTS.get("INPUTS_LANG"), "lang")

    def test_check_inputs_returns_lang(self):
        import sys
        import tempfile
        core = str(ROOT / ".shared" / "core")
        if core not in sys.path:
            sys.path.insert(0, core)
        import entry
        with tempfile.TemporaryDirectory() as tmp:
            repo = pathlib.Path(tmp)
            (repo / "req.json").write_text(json.dumps([{"where": "a.py", "text": "直す"}]), encoding="utf-8")
            got = [entry.check_inputs({"request": "req.json", "lang": given}, repo).get("lang") for given in ("English", "")]
        self.assertEqual(got, ["English", ""])


if __name__ == "__main__":
    unittest.main()
