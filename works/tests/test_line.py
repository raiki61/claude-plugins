"""ライン darkfactory（C18 の順。P1 計画 Task 29・〔線A計〕T17）の配線の検査。YAML を読むだけ（FAST）。

- 口（interactive・inputs・returns・outcome_field）と、節の並び・種類・include 先・境の節の at・with: が linekit.LINE_ORDER と
  同じ（test_line_order_matches_linekit。手で 2 か所に書き写したまま放さない。裁定 TA16）
- script の節の with: の鍵とスクリプトの定数 INPUTS の突き合わせ（TA16）と入力の名の集合は、速い段の test_line_inputs が見る
- when: と関所の文言は、いつも走る節（start・境の節）の欄と $INPUTS だけを読む（TA1。〔試P: P7〕）。飛ばされうる節の出力を
  script の with: で読むなら if_skipped を持つ（P16）。when: を持つ節に依る節は trigger_rule を持つ
- include の id はブロックの中の節の id と重ならない（R17）。輪の中の節の id はライン全体で一意（模擬実行の stub の鍵）
- 関所は decisions に reject を持つ（P8）。役の節は全部印（works-node）を持ち、印の名はブロックをまたいで一意
- 筋書き（fixtures/）: 本物で回す start の筋書き（standard・start-refused）のほかは、走る script と役の節を全部 stub する。
  判定の stub の鍵は blk-judge.yaml から組む（test_judging_stubs_follow_block）
"""
import pathlib
import re
import sys
import unittest

import yaml

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
LINE = ROOT / "darkfactory"
sys.dont_write_bytecode = True
sys.path.insert(0, str(TESTS))
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
import linekit  # noqa: E402
import line_edge  # noqa: E402
from test_line_inputs import script_inputs  # noqa: E402

DEADLINE = 1728000000
# when: で飛ばされない節（start・境の節・機械の報告 report・出口 result）。上流が落ちた後でも走るのは all_done の
# report・result だけで、境の節は none_failed_min_one_success なので飛ばされる（落ちた run の読み手は if_skipped で受ける）
ALWAYS = {"start", "report", "result"} | {r["id"] for r in linekit.LINE_ORDER if r.get("script") == "edge"}
REAL_START = {"standard", "start-refused"}   # start を本物で回す筋書き（TA16）
FIXTURES = {"standard", "no-fix", "policy-continue", "policy-stop", "final-when-needed-green", "final-stop", "stop-flag",
            "start-refused", "pr-fallback", "ai-report-fail", "conflict-ask", "rejudge", "rejudge-no-session"}
# conflict-ask は test_blk_fix_conflict が中身を見る


def load(path):
    return yaml.safe_load(pathlib.Path(path).read_text(encoding="utf-8"))


def line():
    return load(LINE / "darkfactory.yaml")


def block(name):
    return load(ROOT / name / f"{name}.yaml")


def node(nid):
    return next(n for n in line()["nodes"] if n["id"] == nid)


def walk(nodes):
    """(節, 輪の中か) を入れ子も辿って"""
    for n in nodes:
        yield n, False
        if "loop_group" in n:
            for m in n["loop_group"]["nodes"]:
                yield m, True


# 印（works-node）をまだ持たない役（包みが会話を節の名で分けられない。減らす方向にだけ変える）
UNMARKED_ROLES = frozenset()
# 表の置き場のブロックがラインに include されているか（NOT_WIRED_YET）は速い段の test_line_wiring が見る


def stub_keys():
    """模擬実行が stub を引く鍵（Archon 0.11.1 の dry-run: include の中の節は <include>__<節>、輪の中は名前空間なしの id。
    approval・loop_group は stub を取らない）"""
    keys = []
    for n in line()["nodes"]:
        if "include" in n:
            for m, inner in walk(block(n["include"])["nodes"]):
                if "loop_group" in m:
                    continue
                keys.append(m["id"] if inner else f"{n['id']}__{m['id']}")
        elif "approval" not in n:
            keys.append(n["id"])
    return keys


def refs(text: str) -> set:
    return set(re.findall(r"\$([A-Za-z][\w-]*)\.output", text))


class LineShapeCase(unittest.TestCase):
    def test_signature(self):
        y = line()
        self.assertEqual(y["name"], "darkfactory")
        self.assertIs(y["interactive"], True)
        self.assertEqual(set(y["inputs"]), {"request", "base", "pr", "test_cmd", "thickness", "gates", "final_gate", "adapter",
                                            "policy_md", "lang", "tdd_suite", "unattended"})
        self.assertIsNot(y["inputs"]["request"].get("required"), True)   # 依頼・base・pr の少なくとも 1 つは check_inputs が要る
        for k in set(y["inputs"]):
            self.assertEqual(y["inputs"][k].get("default"), "", k)
        self.assertEqual((y["returns"], y["outcome_field"]), ("result", "ok"))
        # 出口 result は機械の報告 report の欄を全部持ち、最後の報告を選んだ欄を足す（計画 P1 Task 34）
        rep, of = node("report")["output_format"], node("result")["output_format"]
        self.assertLessEqual(set(rep["properties"]), set(of["properties"]))
        self.assertEqual(rep["required"], of["required"])
        self.assertLessEqual({"machine_report_file", "ai_report"}, set(of["properties"]))
        self.assertEqual(node("result")["trigger_rule"], linekit.ALL_DONE)
        self.assertEqual(of["properties"]["ok"], {"type": "boolean"})
        # 1 本目の finish の欄を全部残す（出口の約束）
        self.assertLessEqual({"ok", "outcome", "judgment_file"}, set(of["required"]))
        self.assertLessEqual({"review_file", "diff_file", "faces"}, set(of["properties"]))
        import report
        self.assertEqual(of["properties"]["outcome"]["enum"], list(report.OUTCOMES))
        self.assertFalse((LINE / "scripts" / "finish.py").exists(), "finish は report が継いだ")

    def test_line_order_matches_linekit(self):
        nodes = line()["nodes"]
        self.assertEqual([n["id"] for n in nodes], [r["id"] for r in linekit.LINE_ORDER])
        for n, r in zip(nodes, linekit.LINE_ORDER):
            with self.subTest(n["id"]):
                kind = "approval" if "approval" in n else "include" if "include" in n else "script"
                self.assertEqual(kind, r["kind"])
                self.assertEqual(n.get("include"), r.get("block"))
                self.assertEqual(n.get("script"), r.get("script"))
                self.assertEqual(n.get("depends_on"), r.get("depends_on"))
                self.assertEqual(n.get("trigger_rule"), r.get("trigger_rule"))
                self.assertEqual(n.get("when"), r.get("when"))
                if kind == "approval":
                    got = [d["id"] for d in n["approval"].get("decisions") or []]
                    self.assertEqual(got, r.get("decisions", []))
                else:
                    self.assertEqual(n.get("with") or {}, r.get("with") or {})
                if r.get("at"):
                    self.assertEqual(n["with"]["at"], r["at"])

    def test_edges_use_every_edge_input(self):
        """境の節は edge.py の INPUTS を全部受ける（使わない物は文字列 null。A-T10a の持ち越し 1）。出口は line_edge.EMPTY の欄"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("edge_script", LINE / "scripts" / "edge.py")
        want = script_inputs(LINE / "scripts" / "edge.py")
        self.assertIsNotNone(spec)
        for r in linekit.LINE_ORDER:
            if r.get("script") != "edge":
                continue
            with self.subTest(r["id"]):
                n = node(r["id"])
                self.assertEqual({f"INPUTS_{k.upper()}" for k in n["with"]}, want)
                self.assertEqual(n["with"]["at"] in line_edge.AT, True)
                self.assertEqual(set(n["output_format"]["required"]), set(line_edge.EMPTY))

    def test_include_with_matches_block_inputs(self):
        """渡す鍵はブロックが宣言した入力だけ、required の入力は全部渡す"""
        for n in line()["nodes"]:
            if "include" not in n:
                continue
            with self.subTest(n["id"]):
                inputs = block(n["include"]).get("inputs") or {}
                given = set(n.get("with") or {})
                self.assertLessEqual(given, set(inputs))
                self.assertLessEqual({k for k, v in inputs.items() if v.get("required")}, given)

    def test_when_and_gate_text_read_only_always_run_nodes(self):
        """when: と関所の文言が読む $<節>.output は、いつも走る節だけ（TA1）。include の with: も同じ（M4）"""
        for n in line()["nodes"]:
            texts = [n.get("when") or ""]
            if "approval" in n:
                texts.append(n["approval"]["message"])
            if "include" in n:
                texts += [v for v in (n.get("with") or {}).values() if isinstance(v, str)]
            with self.subTest(n["id"]):
                self.assertLessEqual(set().union(*(refs(t) for t in texts)), ALWAYS)

    def test_script_reads_skippable_with_if_skipped(self):
        """script の節の with: が when: を持つ節（か関所）の出力を読むなら if_skipped: null（P16）"""
        skippable = {n["id"] for n in line()["nodes"] if "when" in n}
        for n in line()["nodes"]:
            for k, v in (n.get("with") or {}).items():
                src = v.get("from") if isinstance(v, dict) else v if isinstance(v, str) else ""
                hit = refs(src) & skippable
                if hit and "script" in n:
                    with self.subTest(f"{n['id']}.{k}"):
                        self.assertIsInstance(v, dict)
                        self.assertIn("if_skipped", v)
                        self.assertIsNone(v["if_skipped"])

    def test_join_after_skippable_has_trigger_rule(self):
        """when: を持つ節に依る節は trigger_rule: none_failed_min_one_success（前の段が飛ばされても走る）。機械の報告 report と
        出口 result だけは all_done（上流の節が落ちた run でも報告を残し、AI の報告のブロックが落ちても機械の報告で出口を出す）"""
        skippable = {n["id"] for n in line()["nodes"] if "when" in n}
        for n in line()["nodes"]:
            if set(n.get("depends_on") or []) & skippable:
                with self.subTest(n["id"]):
                    want = linekit.ALL_DONE if n["id"] in ("report", "result") else linekit.NFMOS
                    self.assertEqual(n.get("trigger_rule"), want)

    def test_gates_have_reject_and_text_by_path(self):
        """関所は reject を持ち（無いと reject で run が cancelled になり報告が出ない。P8）、文言は置き場（gate_file）だけを載せる"""
        for gid, edge_id in (("policy-gate", "h-gate"), ("final-gate", "h-final")):
            with self.subTest(gid):
                g = node(gid)
                self.assertEqual([d["id"] for d in g["approval"]["decisions"]], ["approve", "continue", "stop", "reject"])
                self.assertEqual(g["when"], f"${edge_id}.output.ask == true")
                self.assertIn(f"${edge_id}.output.gate_file", g["approval"]["message"])
                self.assertNotIn("gate_text", g["approval"]["message"])

    def test_every_node_has_deadline(self):
        for n in line()["nodes"]:
            if "script" in n:
                with self.subTest(n["id"]):
                    self.assertEqual((n["runtime"], n["timeout"]), ("uv", DEADLINE))
            else:
                self.assertNotIn("timeout", n)

    def test_include_ids_do_not_collide_with_block_nodes(self):
        """Ruling R17: include の id がブロックの中の節の id と同じだと、ブロックの中の $<id>.output が include を指す"""
        inner = set()
        for n in line()["nodes"]:
            if "include" in n:
                inner |= {m["id"] for m, _ in walk(block(n["include"])["nodes"])}
        self.assertEqual({n["id"] for n in line()["nodes"]} & inner, set())

    def test_stub_keys_are_unique(self):
        keys = stub_keys()
        self.assertEqual(len(keys), len(set(keys)), sorted(k for k in keys if keys.count(k) > 1))

    def test_role_marks_unique(self):
        """役の節（AI）は全部 output_format に印 works-node: <名> を持ち、印の名はブロックをまたいで一意（包みの会話の置き場が
        節の名で分かれる）"""
        seen = {}
        for n in line()["nodes"]:
            if "include" not in n:
                continue
            for m, _ in walk(block(n["include"])["nodes"]):
                if "command" not in m and "prompt" not in m:
                    continue
                desc = (m.get("output_format") or {}).get("description") or ""
                with self.subTest(f"{n['include']}/{m['id']}"):
                    if (n["include"], m["id"]) in UNMARKED_ROLES:
                        self.assertFalse(desc.startswith("works-node: "), "印を持った。UNMARKED_ROLES から消す")
                        continue
                    self.assertTrue(desc.startswith("works-node: "), desc)
                    name = desc.split(" ")[1]
                    self.assertNotIn(name, seen, f"印の名 {name} が {seen.get(name)} と重なる")
                    seen[name] = f"{n['include']}/{m['id']}"

    def test_report_reads_edge_stop_words(self):
        """報告が読む止めの語（周を締めた後の止めの trace の op・最後の関所の答えのファイルと by）が境の節の語と同じ"""
        import report
        self.assertEqual(report.STOP_AFTER_END_OP, line_edge.STOP_AFTER_END_OP)
        self.assertEqual(report.FINAL_GATE_ANSWER, line_edge.FINAL_GATE_ANSWER)
        self.assertEqual(report.FINAL_GATE_BY, line_edge.FINAL_GATE_BY)

    def test_reads_include_ids_match_line(self):
        """読んだ証拠の節が Archon の出来事を引く include の id（core の READS）が、線の include の id と同じ（V5〜V7 の当座の形）"""
        import prcheck
        import recount
        import refix
        ids = {n["id"]: n.get("include") for n in line()["nodes"]}
        self.assertEqual(ids[recount.READS[1]], "blk-fix")
        self.assertEqual(ids[prcheck.READS[1]], "blk-pr")
        for role, (_, inc, _, _) in refix.READS.items():
            self.assertEqual(ids[inc], "blk-delta" if role == "review" else "blk-refix", role)
        self.assertEqual(node("planning")["with"]["include_id"], "planning")


class LineFixturesCase(unittest.TestCase):
    def fixtures(self):
        return {p.name.removesuffix(".stubs.yaml"): load(p) for p in (LINE / "fixtures").glob("*.stubs.yaml")}

    def test_fixture_names(self):
        self.assertEqual(set(self.fixtures()), FIXTURES)

    def test_every_stubbable_node_is_stubbed(self):
        """本物で回す start のほかは、走りうる script と役の節を全部 stub する（stub の無い節に届くと exec-code で本物が走る）"""
        keys = set(stub_keys())
        for name, f in self.fixtures().items():
            with self.subTest(name):
                want = keys - ({"start"} if name in REAL_START else set())
                self.assertEqual(want - set(f), set())
                self.assertEqual("start" in f, name not in REAL_START)
                self.assertIs(f.get("exec-code"), True)

    def test_judging_stubs_follow_block(self):
        """判定の stub の鍵は blk-judge.yaml から組んだ stub できる節の集合を含む（判定のブロックが節の名前を替えたら赤。TA18 の 4）"""
        want = set()
        for m, inner in walk(block("blk-judge")["nodes"]):
            if "loop_group" not in m:
                want.add(m["id"] if inner else f"judging__{m['id']}")
        for name, f in self.fixtures().items():
            if name == "start-refused":
                continue
            with self.subTest(name):
                self.assertLessEqual(want, set(f))

    def test_role_stubs_pass_role_output_format(self):
        """役の stub は役の output_format の必須の欄を持つ（見本の返答を貼った物）"""
        roles = {}
        for n in line()["nodes"]:
            if "include" in n:
                for m, _ in walk(block(n["include"])["nodes"]):
                    if "command" in m or "prompt" in m:
                        roles[m["id"]] = m["output_format"]
        f = self.fixtures()["policy-continue"]
        for rid, fmt in roles.items():
            with self.subTest(rid):
                self.assertLessEqual(set(fmt.get("required") or []), set(f[rid]))

    def test_outcomes_and_expectations(self):
        f = self.fixtures()
        self.assertEqual(f["start-refused"]["fixture"]["expect"], "failed")
        # 出口 result は all_done で走り、機械の報告が無いので落ちる（報告の無い run を成功と言わない）
        self.assertEqual(f["start-refused"]["fixture"]["fail-node"], ["start", "report", "result"])
        self.assertEqual(f["start-refused"]["fixture"]["inputs"]["thickness"], "軽量")
        for name, outcome in (("standard", "fixed"), ("no-fix", "no_fix_needed"), ("policy-stop", "stopped_by_human"),
                              ("final-stop", "stopped_by_human"), ("stop-flag", "stopped_by_request"), ("rejudge", "fixed"),
                              ("rejudge-no-session", "stopped_by_line")):
            with self.subTest(name):
                self.assertEqual(f[name]["fixture"]["expect"], "completed")
                self.assertEqual(f[name]["report"]["outcome"], outcome)
                self.assertEqual(f[name]["result"]["outcome"], outcome)
                self.assertEqual(f[name]["fixture"]["reached"][-1], "result")
        # 止めた盤面（計画 P1 Task 34）と、周を締めて止めた普通の run（R61 の B: 報告が report_after_round で報告の節を出す）は
        # AI の報告が回り、最後の報告は report-ai.md。結末は機械の報告のまま
        for name in ("final-stop", "stop-flag", "standard", "no-fix", "policy-continue", "pr-fallback",
                     "final-when-needed-green"):
            with self.subTest(name):
                self.assertIs(f[name]["report"]["ai_report_go"], True)
                self.assertIn("reporting__collect", f[name]["fixture"]["reached"])
                self.assertEqual(f[name]["result"]["report_file"], "board/report-ai.md")
                self.assertEqual(f[name]["result"]["outcome"], f[name]["report"]["outcome"])
        # 周の途中の関所の stop（halted.by answer）は本線と同じく報告の節を出さない
        self.assertIs(f["policy-stop"]["report"]["ai_report_go"], False)
        self.assertNotIn("reporting__collect", f["policy-stop"]["fixture"]["reached"])
        # AI の報告が諦めても出口は機械の報告を選ぶ（all_done）
        self.assertIs(f["ai-report-fail"]["reporting__collect"]["ok"], False)
        self.assertEqual(f["ai-report-fail"]["result"]["report_file"], "board/report.md")
        self.assertEqual(f["ai-report-fail"]["fixture"]["reached"][-2:], ["reporting__collect", "result"])
        self.assertIs(f["no-fix"]["judging__collect"]["need_fix"], False)
        # 直す物の無い判定でも、最後の R2 が要る独立設計を作りに修正案のブロックへ入る（修正案の輪は plan-snap で飛ぶ）
        self.assertIs(f["no-fix"]["h-plan"]["go"], True)
        self.assertIs(f["no-fix"]["planning__plan-snap"]["go"], False)
        self.assertIs(f["no-fix"]["planning__r2-design-snap"]["go"], True)
        self.assertIs(f["pr-fallback"]["h-entry"]["pr_go"], True)
        self.assertIn("pr-checking__collect", f["pr-fallback"]["fixture"]["reached"])
        self.assertIs(f["final-when-needed-green"]["h-final"]["ask"], False)
        self.assertEqual(f["final-when-needed-green"]["fixture"]["inputs"]["final_gate"], "when_needed")
        self.assertIs(f["stop-flag"]["h-review"]["stop"], True)
        self.assertIs(f["policy-stop"]["h-fix"]["stop"], True)
        self.assertIs(f["policy-continue"]["h-gate"]["ask"], True)
        # 修正役の異議（run 28）: 再審を回してから最後のテストへ。判定役の会話が無ければ h-rejudge が止め、後ろは飛ぶ
        self.assertIs(f["rejudge"]["h-rejudge"]["go"], True)
        self.assertLessEqual({"rejudging__collect", "testing__run", "eyeing__eyes-collect"}, set(f["rejudge"]["fixture"]["reached"]))
        self.assertEqual((f["rejudge-no-session"]["h-rejudge"]["stop"], f["rejudge-no-session"]["h-rejudge"]["go"]), (True, False))
        self.assertFalse({"rejudging__collect", "reviewing__collect", "testing__run", "eyeing__eyes-collect"}
                         & set(f["rejudge-no-session"]["fixture"]["reached"]))
        for name in set(FIXTURES) - {"rejudge", "rejudge-no-session", "start-refused"}:
            with self.subTest(name):
                self.assertIs(f[name]["h-rejudge"]["go"], False)
        self.assertTrue(f["policy-continue"]["h-fix"]["notes_file"])


if __name__ == "__main__":
    unittest.main()
