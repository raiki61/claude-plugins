"""ライン darkfactory（C18 の順。P1 計画 Task 29・〔線A計〕T17）の配線の検査。YAML を読むだけ（FAST）。

- 口（interactive・inputs・returns・outcome_field）と、節の並び・種類・include 先・境の節の at・with: が linekit.LINE_ORDER と
  同じ（test_line_order_matches_linekit。手で 2 か所に書き写したまま放さない。裁定 TA16）
- script の節の with: の鍵とスクリプトの定数 INPUTS の突き合わせ（TA16）と入力の名の集合は、速い段の test_line_inputs が見る
- when: と関所の文言は、いつも走る節（start・境の節）の欄と $INPUTS だけを読む（TA1。〔試P: P7〕）。飛ばされうる節の出力を
  script の with: で読むなら if_skipped を持つ（P16）。when: を持つ節に依る節は trigger_rule を持つ
- include の id はブロックの中の節の id と重ならない（R17）。輪の中の節の id はブロックをまたいで一意（模擬実行の stub の鍵。
  同じブロックを 2 度 include した輪の中の節は 1 つの鍵を分け合う）
- 関所は decisions に reject を持つ（P8）。役の節は全部印（works-node）を持ち、印の名はブロックをまたいで一意（同じブロックの
  2 度目の include は 1 度目と同じ印。包みの会話の置き場は印の名で、後の起動が置き場を替える）
- 同じ run の中の案の直し（依頼 226）: 修正の段の後に h-replan → replanning（blk-plan の 2 度目の include）→ h-regate →
  replan-gate（関所）→ h-refit → refitting（blk-fix の 2 度目の include。物は scope で分かれる）→ h-rejudge（test_replan_wiring）
- 筋書き（fixtures/）: 本物で回す start の筋書き（standard・start-refused）のほかは、走る script と役の節を全部 stub する。
  判定の stub の鍵は blk-judge.yaml から組む（test_judging_stubs_follow_block）
"""
import json
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


def walk(nodes, inside=False):
    """(節, 輪の中か) を入れ子の輪の中まで辿って（輪の中の輪の節も、輪の中）"""
    for n in nodes:
        yield n, inside
        if "loop_group" in n:
            yield from walk(n["loop_group"]["nodes"], True)


# 印（works-node）をまだ持たない役（包みが会話を節の名で分けられない。減らす方向にだけ変える）
UNMARKED_ROLES = frozenset()
# 表の置き場のブロックがラインに include されているか（NOT_WIRED_YET）は速い段の test_line_wiring が見る


def stub_keys():
    """模擬実行が stub を引く鍵（Archon 0.11.1 の dry-run: include の頭の節は <include>__<節>、輪の中は入れ子の深さに依らず
    名前空間なしの id（依頼 231 の測り 3）。approval・loop_group は stub を取らない）。同じブロックを 2 度 include すると、輪の中の
    節の鍵は 2 つの include で同じなのでブロックごとに 1 度だけ数える（本物の run の出来事の名は <include>__<輪>.<節> で分かれる。
    依頼 226 の P4 の測り）"""
    keys, seen = [], set()
    for n in line()["nodes"]:
        if "include" in n:
            for m, inner in walk(block(n["include"])["nodes"]):
                if "loop_group" in m or (inner and (n["include"], m["id"]) in seen):
                    continue
                seen.add((n["include"], m["id"]))
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
                                            "policy_md", "lang", "tdd_suite", "unattended", "design_only", "github_reads",
                                            "fix_shape", "fix_fixture"})
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
        出口 result だけは all_done（上流の節が落ちた run でも報告を残し、AI の報告のブロックが落ちても機械の報告で出口を出す）。
        構造の境 h-structure も all_done（任意の上流の構造のブロックの落ちを受けて印を書く）"""
        skippable = {n["id"] for n in line()["nodes"] if "when" in n}
        for n in line()["nodes"]:
            if set(n.get("depends_on") or []) & skippable:
                with self.subTest(n["id"]):
                    want = linekit.ALL_DONE if n["id"] in ("report", "result", "h-structure") else linekit.NFMOS
                    self.assertEqual(n.get("trigger_rule"), want)

    def test_gates_have_reject_and_text_by_path(self):
        """関所は reject を持ち（無いと reject で run が cancelled になり報告が出ない。P8）、文言は置き場（gate_file）だけを載せる"""
        for gid, edge_id in (("policy-gate", "h-gate"), ("replan-gate", "h-regate"), ("final-gate", "h-final")):
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

    def test_nested_loop_stub_keys_are_bare(self):
        """入れ子の輪（blk-plan の壁打ちの輪 converge-loop の中の輪）の節も名前空間なしの鍵。輪そのものは stub を取らない（測り 3）"""
        keys = set(stub_keys())
        self.assertLessEqual({"plan-revise-snap", "plan-revise-prep", "plan-revise", "plan-revise-accept", "plan-review-snap",
                              "plan-review", "converge-check"}, keys)
        self.assertEqual({"planning__plan-review-snap", "planning__converge-check", "converge-loop", "plan-revise-loop",
                          "planning__converge-loop", "replanning__plan-review-snap", "replanning__converge-check"} & keys, set())
        self.assertLessEqual({"planning__plan-snap", "planning__plan-reads", "planning__collect"}, keys)
        self.assertLessEqual({"replanning__plan-snap", "replanning__plan-reads", "replanning__collect"}, keys)   # 2 度目の include の頭

    def test_role_marks_unique(self):
        """役の節（AI）は全部 output_format に印 works-node: <名> を持ち、印の名はブロックをまたいで一意（包みの会話の置き場が
        節の名で分かれる）。同じブロックの 2 度目の include（replanning・refitting）は 1 度目と同じ印なので、ブロックごとに 1 度数える"""
        seen, blocks = {}, set()
        for n in line()["nodes"]:
            if "include" not in n or n["include"] in blocks:
                continue
            blocks.add(n["include"])
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
        self.assertEqual(report.FINAL_GATE_FILE, line_edge.FINAL_GATE_FILE)
        self.assertEqual(report.FINAL_GATE_BY, line_edge.FINAL_GATE_BY)

    def test_every_include_names_its_own_scope(self):
        """部品の置き場（依頼 239 の測り M1 の形 A）: scope は Archon が節に渡す step の名の include の頭から core が引くので、
        YAML は scope を渡さない。線の include の id は全部違い（2 つの include が同じ scope を名乗らない）、scope の名の決まり
        （英字で始まり英数字・_・- だけ・r<数字> でない）に合い、`__` を持たない（step の名の区切りと紛れない）。ブロックは
        include の名を入力に持たない（読んだ証拠の節も core が今の scope から引く）"""
        ids = [n["id"] for n in line()["nodes"] if "include" in n]
        self.assertEqual(len(ids), len(set(ids)), ids)
        for i in ids:
            with self.subTest(i):
                self.assertRegex(i, r"^[A-Za-z][A-Za-z0-9_-]*$")
                self.assertNotRegex(i, r"^r\d+$")
                self.assertNotIn("__", i)
        for n in line()["nodes"]:
            if "include" in n:
                self.assertNotIn("include_id", n.get("with") or {}, n["id"])
                self.assertNotIn("include_id", block(n["include"]).get("inputs") or {}, n["include"])

    def test_block_code_has_no_scope_code(self):
        """部品のコード（blk-*/lib・blk-*/scripts の .py）は scope を知らない: 流れの道具の口・scope の模块・include の名の入力を
        書かない（置き場の分け・登録・集めは core の共通の口だけ。依頼 239 の Global Constraints）"""
        found = [f"{p.relative_to(ROOT)}: {word}" for p in sorted(ROOT.glob("blk-*/*/*.py")) if p.parent.name in ("lib", "scripts")
                 for word in ("flow_adapter", "import scopes", "INCLUDE_ID") if word in p.read_text(encoding="utf-8")]
        self.assertEqual(found, [])
        self.assertTrue(list(ROOT.glob("blk-*/lib/*.py")) and list(ROOT.glob("blk-*/scripts/*.py")))

    def test_structure_block_wired_between_plan_and_planning(self):
        """構造のブロック（blk-structure）は h-plan の直後に include 1 つで入り、h-plan が写した判定の単位のファイルを units に
        受ける。その後の境の節 h-structure（script・all_done・飛ばされた構造のブロックは null で受ける）を planning が待つ。
        planning は既定の trigger_rule と h-plan の when のままで、h-plan の落ち・go が偽の周は飛ぶ。h-structure の節そのものが
        落ちた周は、h-gate が h-plan の落ちと同じく飛び、計画なしで修正へ進まない"""
        ids = [n["id"] for n in line()["nodes"]]
        got = next((n for n in line()["nodes"] if n.get("include") == "blk-structure"), None)
        self.assertIsNotNone(got, "darkfactory.yaml に blk-structure の include が無い")
        self.assertEqual(ids.index(got["id"]), ids.index("h-plan") + 1)
        self.assertEqual(got.get("depends_on"), ["h-plan"])
        self.assertEqual(got["with"]["units"], "$h-plan.output.structure_units_file")
        self.assertIn("h-structure", ids, "構造の境の節 h-structure が無い")
        edge = node("h-structure")
        self.assertIn("script", edge)
        self.assertEqual(set(edge.get("depends_on") or []), {"h-plan", got["id"]})
        self.assertEqual(edge.get("trigger_rule"), "all_done")
        self.assertIn({"from": f"${got['id']}.output", "if_skipped": None}, list((edge.get("with") or {}).values()))
        self.assertLess(ids.index("h-structure"), ids.index("planning"))
        planning = node("planning")
        self.assertEqual(planning["depends_on"], ["h-plan", "h-structure"])
        self.assertNotIn("trigger_rule", planning)
        self.assertEqual(planning["when"], "$h-plan.output.go == true")
        self.assertIn("h-structure", node("h-gate")["depends_on"])


    def test_replan_wiring(self):
        """修正の段の後・再審の前に、案の直し（依頼 226。1 run に 1 回）: h-replan → replanning（blk-plan の 2 度目の include。
        replan の口）→ h-regate → replan-gate（線の最上段の関所。輪の外）→ h-refit（関所の答えを受ける）→ refitting（blk-fix の
        2 度目の include。出来事を引く include の名と物の置き場は core が今の scope から引く）→ h-rejudge（2 回目の段の後を待つ）"""
        ids = [n["id"] for n in line()["nodes"]]
        i = ids.index("fixing")
        self.assertEqual(ids[i:i + 8], ["fixing", "h-replan", "replanning", "h-regate", "replan-gate", "h-refit", "refitting",
                                        "h-rejudge"])
        self.assertEqual([(node(x).get("script"), node(x)["with"]["at"]) for x in ("h-replan", "h-regate", "h-refit")],
                         [("edge", "replan"), ("edge", "regate"), ("edge", "refit")])
        self.assertEqual(node("h-replan")["depends_on"], ["start", "h-fix", "fixing"])
        self.assertEqual(node("h-refit")["with"]["gate"], {"from": "$replan-gate.output", "if_skipped": None})
        self.assertEqual(node("h-rejudge")["depends_on"], ["start", "h-fix", "fixing", "h-refit", "refitting"])
        re_ = node("replanning")
        self.assertEqual((re_["include"], re_["when"]), ("blk-plan", "$h-replan.output.go == true"))
        self.assertEqual(re_["with"]["replan"], "true")
        self.assertEqual({k: v for k, v in re_["with"].items() if k not in ("replan", "judgment_file")},
                         {k: v for k, v in node("planning")["with"].items() if k != "judgment_file"})
        gate = node("replan-gate")
        self.assertNotIn("loop_group", gate)
        self.assertEqual((gate["depends_on"], gate["when"]), (["h-regate"], "$h-regate.output.ask == true"))
        self.assertEqual(gate["approval"]["message"],
                         "修正の段で誤りと裁いた修正案の項目を、run の中で直した。約束の欄が変わったか、事前審査が人に聞く穴を挙げた。\n"
                         "全文と答え方: $h-regate.output.gate_file（Read して答える）。\n"
                         'continue "<一言>" で直した項目を使って修正に戻る。stop "<理由>" で run を止める（1 回目に直した単位の差分は'
                         "報告に残る）。approve は continue、reject は stop と同じ。\n")
        fit = node("refitting")
        self.assertEqual((fit["include"], fit["when"]), ("blk-fix", "$h-refit.output.go == true"))
        self.assertIn("修正（TDD の輪）→（裁定が案の項目の誤りなら）案の直し → 案の直しの関所（要る時だけ）→ 2 回目の修正 →",
                      line()["description"])


    def test_refitting_passes_only_scope(self):
        """2 回目の修正の段（include refitting）の with: は 1 回目（fixing）と同じ鍵で、違いは渡す値（判定・未直しの単位・案・
        覚え書き）だけ。2 回の段を分けるのは include の名（scope。依頼 239）で、回の印 pass_tag は渡さない"""
        fit, fixing = node("refitting"), node("fixing")
        self.assertNotIn("pass_tag", fit["with"])
        self.assertEqual(set(fit["with"]), set(fixing["with"]))
        passed = ("open_units", "plan_file", "notes_file", "judgment_file")
        self.assertEqual({k for k in fit["with"] if fit["with"][k] != fixing["with"][k]}, set(passed))
        for k in passed:
            self.assertEqual(fit["with"][k], f"$h-refit.output.{k}", k)
        self.assertNotEqual(fit["id"], fixing["id"], "scope の名は include の id")

    def test_no_pass_tag_left(self):
        """回の印（依頼 226 の pass_tag・INPUTS_PASS_TAG・script_io.tagged）は pack の .py と .yaml に残らない（docs/・CHANGELOG.md・
        tests/ を除く。依頼 239）"""
        left = []
        for p in sorted(ROOT.rglob("*")):
            rel = p.relative_to(ROOT)
            if p.suffix not in (".py", ".yaml") or not p.is_file() or rel.parts[0] in ("docs", "tests"):
                continue
            for n, text in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
                if any(w in text for w in ("pass_tag", "PASS_TAG", "tagged(")):
                    left.append(f"{rel}:{n}: {text.strip()}")
        self.assertEqual(left, [], "\n".join(left))


class LensWiringCase(unittest.TestCase):
    def test_lens_block_wired_before_review(self):
        """修正の後のレンズ（blk-lens）は h-review の直後に include 1 つで入り、h-review の go を引く（新しい条件を作らない）。
        差分の審査 reviewing はその出口を待つ（none_failed_min_one_success: レンズの節が落ちても集め役が ok で終われば走り、
        境が盤面を止めて ok: false で落ちた周は飛ぶ）"""
        ids = [n["id"] for n in line()["nodes"]]
        got = next((n for n in line()["nodes"] if n.get("include") == "blk-lens"), None)
        self.assertIsNotNone(got, "darkfactory.yaml に blk-lens の include が無い")
        self.assertEqual(ids.index(got["id"]), ids.index("h-review") + 1)
        self.assertEqual((got["depends_on"], got["when"]), (["h-review"], node("reviewing")["when"]))
        self.assertEqual(node("reviewing")["when"], "$h-review.output.go == true")
        self.assertEqual(node("reviewing")["depends_on"], ["h-review", got["id"]])
        self.assertEqual(node("reviewing")["trigger_rule"], linekit.NFMOS)

    def test_rollback_restores_previous_line(self):
        """撤収の手順（include を外し、reviewing の依存を [h-review] に戻す）で、レンズを入れる前の線の並びと配線に戻る"""
        before = [{**r} for r in linekit.LINE_ORDER if r["id"] != "lensing"]
        rv = next(r for r in before if r["id"] == "reviewing")
        rv["depends_on"] = ["h-review"]
        rv.pop("trigger_rule")
        self.assertEqual(rv, {"id": "reviewing", "kind": "include", "block": "blk-delta", "depends_on": ["h-review"],
                              "when": "$h-review.output.go == true", "with": {"base_rev": "$start.output.base_rev"}})
        self.assertFalse([r["id"] for r in before if "lensing" in (r.get("depends_on") or [])
                          or "$lensing." in json.dumps(r.get("with") or {})], "lensing を読む節がほかに在ると戻せない")


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
        """役の stub は役の output_format を入れ子まで満たす（見本の返答を貼った物。どの fixture も、修正案の項目の works の欄まで）"""
        from engine.schema import validate_schema   # 写しの engine の型の検査（linekit が sys.path に足す）
        roles = {}
        for n in line()["nodes"]:
            if "include" in n:
                for m, inner in walk(block(n["include"])["nodes"]):
                    if "command" in m or "prompt" in m:
                        roles[m["id"] if inner else f"{n['id']}__{m['id']}"] = m["output_format"]   # stub_keys と同じ鍵
        for name, f in self.fixtures().items():
            for rid, fmt in roles.items():
                with self.subTest(fixture=name, role=rid):
                    self.assertIn(rid, f)
                    self.assertEqual(validate_schema(f[rid], fmt), [])

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
        # 案の直し（依頼 226）はどの筋書きでも起きない（修正の段で fix_plan_item と裁いた項目が無い）。3 つの境の節は走り、
        # 2 度目の include は飛ぶ
        for name in set(FIXTURES) - {"start-refused"}:
            with self.subTest(name):
                self.assertEqual((f[name]["h-replan"]["go"], f[name]["h-regate"]["ask"], f[name]["h-refit"]["go"]),
                                 (False, False, False))
                reached = f[name]["fixture"]["reached"]
                self.assertFalse({"replanning__collect", "refitting__collect"} & set(reached))
                if "h-rejudge" in reached:
                    i = reached.index("h-rejudge")
                    self.assertEqual(reached[i - 3:i], ["h-replan", "h-regate", "h-refit"])
        self.assertTrue(f["policy-continue"]["h-fix"]["notes_file"])


if __name__ == "__main__":
    unittest.main()
