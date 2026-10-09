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
import sys
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
if str(ROOT / ".shared" / "core" / "graphloops") not in sys.path:
    sys.path.insert(0, str(ROOT / ".shared" / "core" / "graphloops"))   # 写しの engine（engine.schema）
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
    ("blk-fix", "tdd"): ({"units", "unit_key", "what", "files", "refactor"},
                         "段（phase）ごとに欄が違う（route は units、単位の段 test・fix・refactor は unit_key・what、"
                         "fix は files と整えの申告 refactor も）"),
    ("blk-plan", "plan-accept"): ({"asking", "halted", "out_file", "ready"},
                                  "拒否（ok: false）の返りは盤面に渡していないので、盤面の欄を持たない（give-up・plan-rejected）"),
    ("blk-fix", "collect"): ({"coverage", "fix_file", "not_done", "reads_file"},
                             "ラインの筋書きは 1 本目の欄と tdd だけを置く（盤面から足す 4 欄。ラインの下流はどれも読まない）"),
    ("blk-delta", "review-accept"): ({"review_file", "give_up", "node"},
                                     "ラインの筋書きは古い受け付けの欄 review_file を持つ（今の受け付けは返さない。下流は done と "
                                     "reason_file だけを読む）。give_up・node は、線の筋書きの review-accept が仕様の段（blk-spec）の輪の"
                                     "受け付けと模擬実行の鍵が重なり（test_line の SHARED_STUB_KEYS）、両方の型を満たすので持つ欄"),
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


def node_defs():
    """{(ブロック, 節の id): 節}。ラインは "darkfactory"。輪の中は入れ子の深さに依らず辿る（blk-plan の converge-loop）"""
    def deep(nodes):
        for n in nodes:
            yield n
            yield from deep((n.get("loop_group") or {}).get("nodes") or ())
    out = {("darkfactory", n["id"]): n for n in deep(line()["nodes"])}
    for p in ROOT.glob("*/*.yaml"):
        if p.stem == p.parent.name and p.parent.name != "darkfactory":
            out.update({(p.stem, n["id"]): n for n in deep(load(p).get("nodes") or ())})
    return out


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


class WorldWiringCase(unittest.TestCase):
    """世界の解の段（計画 world-solution の W7・5.1 節）: 目的の後・判定の前に 1 回だけ"""

    def test_world_block_between_purpose_and_judge(self):
        """blk-world は線に include 1 つで入り、目的の文を渡す h-mat の後（h-mat の world_go が真の周だけ。入力は依頼と、h-mat が
        組んだ目的の文のファイル）・判定の前に在る。その後の境 h-world（script・all_done・飛ばされた段は null で受ける）が控えを
        書き、判定は h-world を待つ"""
        nodes = line()["nodes"]
        ids = [n["id"] for n in nodes]
        got = [n for n in nodes if n.get("include") == "blk-world"]
        self.assertEqual(len(got), 1, "blk-world の include が 1 つでない")
        w = got[0]
        self.assertLess(ids.index("purposing"), ids.index(w["id"]))
        self.assertLess(ids.index("h-mat"), ids.index(w["id"]))
        self.assertLess(ids.index(w["id"]), ids.index("judging"))
        self.assertEqual(w.get("depends_on"), ["h-mat"])
        self.assertEqual(w.get("when"), "$h-mat.output.world_go == true")
        self.assertEqual(w.get("with"), {"request": "$INPUTS.request", "purpose_file": "$h-mat.output.world_purpose_file"})
        edge = next((n for n in nodes if n["id"] == "h-world"), None)
        self.assertIsNotNone(edge, "世界の解の境 h-world が無い")
        self.assertEqual(edge.get("script"), "world")
        self.assertEqual(set(edge.get("depends_on") or []), {"h-mat", w["id"]})
        self.assertEqual(edge.get("trigger_rule"), "all_done")
        self.assertIn({"from": f"${w['id']}.output", "if_skipped": None}, list((edge.get("with") or {}).values()))
        self.assertLess(ids.index("h-world"), ids.index("judging"))
        self.assertIn("h-world", next(n for n in nodes if n["id"] == "judging")["depends_on"])


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

    def test_stubs_carry_required_fields(self):
        """stub は節の output_format の required を全部持つ（Archon の模擬実行は欠けた欄を読む節を理由なしで落とす。blk-refix の
        refix-prep が prompt_file を足した後も筋書き 14 本が欄を欠いたまま残り、dev/check.sh でしか見えなかった）"""
        defs = node_defs()
        for nid, per_file in sorted(stub_key_sets().items()):
            node = defs.get(nid) or next((n for (b, i), n in defs.items() if i == nid[1] and nid[0] == "darkfactory"), None)
            required = set(((node or {}).get("output_format") or {}).get("required") or ())
            for f, keys in per_file.items():
                if keys is None:
                    continue
                with self.subTest(f"{f}: {nid[1]}"):
                    self.assertEqual(sorted(required - keys), [], "stub が節の output_format の required を欠く")

    def test_stubs_pass_output_format(self):
        """stub は節の output_format を入れ子まで満たす（役の節だけでなく script の節も。Archon の模擬実行は stub を節の
        output_format に通し、合わなければ節を落とす。h-depth・h-redepth の stub の lines の行『深さ: 標準（…）』は引用符が無く
        YAML が {深さ: …} の dict に読み、ラインの筋書き 13 本が dev/check.sh の workflow test でだけ落ちていた）"""
        from engine.schema import validate_schema   # 写しの engine の型の検査
        defs = node_defs()
        owner = line_stub_owner()
        for p in fixture_files():
            folder = p.parent.parent.name
            for key, stub in (load(p) or {}).items():
                if key in NOT_STUBS:
                    continue
                nid = owner.get(key, ("darkfactory", key)) if folder == "darkfactory" else (folder, key)
                node = defs.get(nid) or next((n for (b, i), n in defs.items() if i == nid[1] and nid[0] == "darkfactory"), None)
                fmt = (node or {}).get("output_format")
                if not fmt:
                    continue
                with self.subTest(f"{p.relative_to(ROOT)}: {key}"):
                    self.assertEqual(validate_schema(stub, fmt), [])

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
            if set(re.findall(r"\$([A-Za-z][\w-]*)\.output", src)) - {"entering"}:
                with self.subTest(k):
                    self.assertIsInstance(v, dict)
                    self.assertIn("if_skipped", v)
                    self.assertIsNone(v["if_skipped"])

    def test_report_reads_tdd_outcomes_of_both_fix_stages(self):
        """keep-essence の 11: 修正の段ごとの TDD の輪の単位の結末（修正のブロックの出口 tdd）を、機械の報告が 2 つの段とも受ける
        （飛ばされた段は null）"""
        n = next(n for n in line()["nodes"] if n["id"] == "report")
        fixes = [m["id"] for m in line()["nodes"] if m.get("include") == "blk-fix"]
        self.assertEqual(fixes, ["fixing", "refitting"])
        self.assertEqual(n["with"].get("fix_tdd"), {"from": "$fixing.output.tdd", "if_skipped": None})
        self.assertEqual(n["with"].get("refit_tdd"), {"from": "$refitting.output.tdd", "if_skipped": None})

    def test_report_reruns_on_resume(self):
        """機械の報告 report は Archon の resume のたびに回し直す（always_run）。上流の節が落ちても all_done の節（tdd-join・fix-join）が
        受け止めて最後まで進んだ run は、report が結末 interrupted を書き、result が落ちて run が failed で残る。resume は落ちた節と
        それに依る節だけを回し直し、report の依り先（start・h-eyes・eyeing）の出口は替わらないので、always_run が無いと report は
        前の試みの interrupted のまま使われ、result が何度 resume しても落ちる（canary run 7d95d3bc の resume。落ちた枝の輪は
        続いて済んだのに run が completed にならなかった）"""
        n = next(n for n in line()["nodes"] if n["id"] == "report")
        self.assertIs(n.get("always_run"), True)

    def test_all_done_reads_upstream_with_if_skipped(self):
        """all_done の節（report・result・h-structure）は、start と all_done の節のほかの出力を if_skipped つきの binding で受ける。
        上流が飛ばされた run で字の参照を解けずに落ちる（start が入力を拒んだ run で h-structure が $h-plan.output.go で落ちた）"""
        nodes = line()["nodes"]
        always = {"entering"} | {n["id"] for n in nodes if n.get("trigger_rule") == "all_done"}
        for n in nodes:
            if n.get("trigger_rule") != "all_done":
                continue
            for k, v in (n.get("with") or {}).items():
                src = v.get("from") if isinstance(v, dict) else v if isinstance(v, str) else ""
                if set(re.findall(r"\$([A-Za-z][\w-]*)\.output", src)) - always:
                    with self.subTest(f"{n['id']}.{k}"):
                        self.assertIsInstance(v, dict)
                        self.assertIn("if_skipped", v)

    def test_after_report_matches_line(self):
        """報告の節の AFTER_REPORT（report より下流の節の写し）が darkfactory.yaml の depends_on から引いた report の子孫と同じ
        （写しがずれると、その節の前の試みの失敗を今の失敗に数え直す。run 43・54 の形）"""
        import importlib.util
        import sys
        deps = {n["id"]: set(n.get("depends_on") or ()) for n in line()["nodes"]}
        after, grew = set(), True
        while grew:
            more = {i for i, d in deps.items() if d & (after | {"report"})} - after
            after |= more
            grew = bool(more)
        spec = importlib.util.spec_from_file_location("_report_script_wiring", LINE / "scripts" / "report.py")
        mod = importlib.util.module_from_spec(spec)
        dont = sys.dont_write_bytecode
        sys.dont_write_bytecode = True  # exec_module は中身を動かす前に .pyc を書く（pack の中に __pycache__ を作らない）
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.dont_write_bytecode = dont
        self.assertEqual(set(mod.AFTER_REPORT), after)


if __name__ == "__main__":
    unittest.main()
