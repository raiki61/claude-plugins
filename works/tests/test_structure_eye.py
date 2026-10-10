"""構造の目の受け付けと出口の決定的な試験（blk-structure/lib/eye.py・scripts/collect.py）と、線の構造の境 h-structure の落ち所
（人の条件: 境の中の失敗は行なしで計画に進み、境の節そのものが落ちた周は h-plan の落ちと同じく計画なしで修正へ進まない）。
ブロックを通しで回す試験は test_blk_structure の EyeCase、計画の頭は test_blk_plan の StructureHeadCase が見る"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

import yaml

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
BLOCK = ROOT / "blk-structure"
sys.dont_write_bytecode = True
sys.path.insert(0, str(BLOCK / "lib"))
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
import eye  # noqa: E402
import line_edge  # noqa: E402
import prepkit  # noqa: E402
import scriptline  # noqa: E402
import structmark  # noqa: E402
from hermetic import child_env  # noqa: E402

DESIGN_DOC = ROOT / "docs" / "specs" / "2026-09-29-structure-block-design.md"
DOC = {"status": "ok", "reason": "", "units": [
    {"id": "u-1", "summary": "直す所", "paths": ["a.txt"], "status": "measured", "reason": "", "measure": {"churn": 3}},
    {"id": "u-2", "summary": "測れない所", "paths": ["b.txt"], "status": "failed", "reason": "x", "measure": None}],
    "timing": {"wall_s": 0.5}}
CLEAN = {"unit_id": "u-1", "verdict": "汚れない", "faces": [], "evidence": ["/units/0/measure/churn"], "reason": "形が増えない"}
DIRTY = {"unit_id": "u-1", "verdict": "汚れる", "faces": [2], "evidence": ["/units/0/measure"], "reason": "責務を割る",
         "chosen": "1 か所に固める", "chosen_reason": "読み直しを割らない"}


class EyeAcceptCase(unittest.TestCase):
    def test_six_forms_are_the_design_doc_list(self):
        """指示書の 6 つの形は設計書 4 節の番号つきの一覧と一字も違わない（faces の 1〜6 の意味の正本は設計書）"""
        text = DESIGN_DOC.read_text(encoding="utf-8").split("## 4. 構造の目", 1)[1].split("\n## ", 1)[0]
        self.assertEqual(tuple(re.findall(r"^  \d\. (.+)$", text, re.M)), eye.FORMS)

    def test_prompt_carries_only_measured_units_and_the_forms(self):
        prompt = eye.render(DOC)
        self.assertIn("u-1", prompt)
        self.assertNotIn("u-2", prompt)
        self.assertIn(eye.concepthome.EYE_ASK, prompt)
        for i, f in enumerate(eye.FORMS, 1):
            self.assertIn(f"{i}. {f}", prompt)
        again = eye.render(DOC, "evidence が空")
        self.assertIn("前の回の受け付けが拒んだ理由", again)
        prepkit.drawn(self, "structure-eye", again)

    def test_prompt_asks_chosen_to_follow_world_practice(self):
        """単位の要約の尾の世界の解の要点を読み、避け方 chosen を定石の作りに沿わせ、沿わないなら訳を chosen_reason に書けと頼む
        （計画 world-solution の W8・5.3 節の 3。入力の契約は 3 つのまま）"""
        prompt = eye.render(DOC)
        rule = next((ln for ln in prompt.splitlines() if "定石" in ln), "")
        self.assertIn("chosen", rule)
        self.assertIn("chosen_reason", rule)
        self.assertIn("世界の解", rule)

    def test_good_rows_pass(self):
        self.assertEqual(eye.problems(DOC, {"rows": [CLEAN]}), [])
        self.assertEqual(eye.problems(DOC, {"rows": [DIRTY]}), [])

    def test_bad_rows_are_named(self):
        for name, rows in (("汚れるで避け方が無い", [{**DIRTY, "chosen": ""}]),
                           ("汚れるで形が無い", [{**DIRTY, "faces": []}]),
                           ("知らない行き先", [{**DIRTY, "route": "後で"}]),
                           ("測れなかった単位", [CLEAN, {**CLEAN, "unit_id": "u-2"}]),
                           ("同じ単位の 2 行", [CLEAN, CLEAN]),
                           ("行が無い", []),
                           ("形の外の欄", [{**CLEAN, "note": "x"}]),
                           ("真偽を形の番号に", [{**CLEAN, "faces": [True]}]),
                           ("ポインタでない根拠", [{**CLEAN, "evidence": ["units/0/measure"]}]),
                           ("前に 0 を付けた添字", [{**CLEAN, "evidence": ["/units/00/measure"]}]),
                           ("測れなかった単位の null", [{**CLEAN, "evidence": ["/units/1/measure"]}])):
            with self.subTest(name):
                self.assertTrue(eye.problems(DOC, {"rows": rows}))
        self.assertTrue(eye.problems(DOC, None))

    def test_route_up_needs_reason(self):
        """人に上げる行は、決め手を当たっても決まらない訳（undecided_because）と、捨てた案と代償（rejected）が要る。汚れない行は上げない"""
        up = {**DIRTY, "route": "人に上げる", "rejected": [{"option": "2 か所に置く", "cost": "読み直しが割れる"}],
              "undecided_because": "人の前の決定が 2 つの置き場を別々に推していて、どちらにも決まらない"}
        self.assertEqual(eye.problems(DOC, {"rows": [up]}), [])
        for name, bad in (("訳が無い", {"undecided_because": ""}), ("捨てた案が無い", {"rejected": []}),
                          ("汚れないのに上げる", {"verdict": "汚れない", "faces": []})):
            with self.subTest(name):
                got = eye.problems(DOC, {"rows": [{**up, **bad}]})
                self.assertTrue(got, name)
        self.assertTrue(any("undecided_because" in g for g in eye.problems(DOC, {"rows": [{**up, "undecided_because": ""}]})))

    def test_route_up_row_written(self):
        """受け付けた人に上げる行は、行き先とその訳（route_reason＝決まらない訳）を design.jsonl に残す。自分で決める行は既定の訳"""
        up = {**DIRTY, "route": "人に上げる", "rejected": [{"option": "2 か所に置く", "cost": "読み直しが割れる"}],
              "undecided_because": "人の前の決定が 2 つの置き場を別々に推していて、どちらにも決まらない"}
        with tempfile.TemporaryDirectory() as d:
            s = pathlib.Path(d) / "structure.json"
            s.write_text(json.dumps(DOC, ensure_ascii=False), encoding="utf-8")
            design = pathlib.Path(d) / "design.jsonl"
            design.write_bytes(b"")
            eye.prep(s)
            self.assertTrue(eye.accept(s, design, {"rows": [up]})["ok"])
            row = json.loads(design.read_text(encoding="utf-8"))
        self.assertEqual((row["route"], row["route_reason"], row["undecided_because"]),
                         ("人に上げる", up["undecided_because"], up["undecided_because"]))
        schema = json.loads((BLOCK / "design-row.schema.json").read_text(encoding="utf-8"))
        from engine.schema import validate_schema
        self.assertEqual(validate_schema(row, schema), [])

    def test_prompt_carries_concepts_and_rules(self):
        """目に見せる物に、単位に当たる考えの地図の行・知る場所の数と、方針と根の地図の文書が載る（段 A が structure.json に置いた物）"""
        doc = {**DOC, "rules": {"policy": {"path": "POLICY.md", "text": "置き場は 1 つにする", "reason": ""},
                                "maps": "### 対象のリポジトリの地図\n\n- 地図なし", "reason": ""},
               "units": [{**DOC["units"][0], "concepts": {"rows": [{"id": "outcome", "map": "docs/concepts.md",
                                                                     "text": "### `outcome` run の結末"}],
                                                          "places": [{"concept": "outcome", "what": "結末の語", "path": "a.txt",
                                                                      "lines": 1, "home": False, "known_places": 3}]}},
                         DOC["units"][1]]}
        prompt = eye.render(doc)
        for want in ("置き場は 1 つにする", "### `outcome` run の結末", "known_places", "地図なし"):
            self.assertIn(want, prompt)
        self.assertEqual(eye.problems(doc, {"rows": [{**CLEAN, "evidence": ["/units/0/concepts/places/0/known_places"]}]}), [])

    def test_evidence_indexes_the_units_the_prompt_showed(self):
        """測れなかった単位が先に在っても、目が見た /units/0 は実測した単位を指す"""
        doc = {**DOC, "units": DOC["units"][::-1]}
        self.assertIn('"u-1"', eye.render(doc))
        self.assertEqual(eye.problems(doc, {"rows": [CLEAN]}), [])
        self.assertTrue(eye.problems(doc, {"rows": [{**CLEAN, "evidence": ["/units/1/measure"]}]}))

    def test_long_duplicates_are_cut_with_the_total(self):
        """大きいファイルの塊の一致が数百件でも、目に見せるのは先頭 DUP_SHOWN 件と全件の数（支度の出力を小さく保つ）"""
        dups = [{"line": i, "other_line": i, "path": "x.yaml"} for i in range(eye.DUP_SHOWN * 40)]
        doc = {**DOC, "units": [{**DOC["units"][0], "measure": {"paths": [{"path": "a.txt", "duplicates": dups}]}}]}
        got = eye.view(doc)["units"][0]["measure"]["paths"][0]
        self.assertEqual(len(got["duplicates"]), eye.DUP_SHOWN)
        self.assertEqual(got["duplicates_total"], len(dups))
        self.assertEqual(eye.problems(doc, {"rows": [{**CLEAN, "evidence": ["/units/0/measure/paths/0/duplicates_total"]}]}), [])
        self.assertLess(len(eye.render(doc)), 4000)

    def test_third_rejection_gives_up(self):
        with tempfile.TemporaryDirectory() as d:
            s = pathlib.Path(d) / "structure.json"
            s.write_text(json.dumps(DOC, ensure_ascii=False), encoding="utf-8")
            design = pathlib.Path(d) / "design.jsonl"
            design.write_bytes(b"")
            got = []
            for _ in range(eye.MAX_ATTEMPTS):
                self.assertEqual(eye.prep(s)["attempt"], len(got) + 1)
                got.append(eye.accept(s, design, {"rows": []}))
            self.assertEqual([(g["ok"], g["done"], g["give_up"]) for g in got],
                             [(False, False, False), (False, False, False), (False, True, True)])
            self.assertEqual(eye.state(d)["status"], "gave_up")
            self.assertEqual(design.stat().st_size, 0)


class EyeLoopGateCase(unittest.TestCase):
    def test_loop_runs_only_when_stage_a_says_eye(self):
        """実測が落ちた・測れた単位が無い周（段 A の eye が偽）は目の会話を起こさない"""
        doc = yaml.safe_load((BLOCK / "blk-structure.yaml").read_text(encoding="utf-8"))
        loop = next(n for n in doc["nodes"] if "loop_group" in n)
        for flag in (True, False):
            with self.subTest(eye=flag):
                scope = scriptline.Scope("blk-structure", {})
                scope.out["stage-a"], scope.status["stage-a"] = {"eye": flag}, "ok"
                self.assertIs(scriptline.ScriptLine._runs(None, scope, loop, False), flag)
        self.assertEqual((eye.due(DOC), eye.due({**DOC, "status": "failed"}), eye.due({**DOC, "units": DOC["units"][1:]})),
                         (True, False, False))


class CollectCase(unittest.TestCase):
    """collect は目の落ちを ok: false にせず、status と reason に残す"""

    def collect(self, doc, due, got, kept=None):
        with tempfile.TemporaryDirectory() as d:
            s = pathlib.Path(d) / "structure.json"
            s.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
            (pathlib.Path(d) / "design.jsonl").write_bytes(b"")
            if kept:
                (pathlib.Path(d) / eye.EYE_FILE).write_text(json.dumps(kept), encoding="utf-8")
            env = child_env(INPUTS_STRUCTURE_FILE=str(s), INPUTS_DESIGN_FILE=str(pathlib.Path(d) / "design.jsonl"),
                            INPUTS_EYE_DUE=json.dumps(due), INPUTS_EYE=json.dumps(got), PYTHONDONTWRITEBYTECODE="1")
            p = subprocess.run([sys.executable, str(BLOCK / "scripts" / "collect.py")], env=env, capture_output=True,
                               text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
            self.assertEqual(p.returncode, 0, p.stderr)
            return json.loads(p.stdout)

    def test_each_failure_keeps_ok_and_names_the_reason(self):
        ok = {"ok": True, "done": True, "give_up": False, "reason": "", "attempt": 1}
        gave_up = {"ok": False, "done": True, "give_up": True, "reason": "evidence が空", "attempt": 3}
        cases = ((DOC, True, ok, "ok", ""), (DOC, False, None, "ok", ""),
                 (DOC, True, None, "failed", "構造の目の会話が落ちた"),
                 (DOC, True, gave_up, "failed", "3 回とも受け付けで拒まれた"),
                 ({**DOC, "status": "failed", "reason": "実測の落ち"}, False, None, "failed", "実測の落ち"))
        for doc, due, got, status, why in cases:
            with self.subTest(status=status, why=why):
                out = self.collect(doc, due, got)
                self.assertIs(out["ok"], True)
                self.assertEqual(out["status"], status, out)
                self.assertIn(why, out["reason"])

    def test_wall_adds_the_eye_time(self):
        out = self.collect(DOC, True, {"ok": True, "done": True, "give_up": False, "reason": "", "attempt": 1},
                           kept={"wall_s": 2.25})
        self.assertEqual(out["wall_s"], 2.75)


def line_nodes() -> dict:
    return {n["id"]: n for n in yaml.safe_load((ROOT / "darkfactory" / "darkfactory.yaml").read_text(encoding="utf-8"))["nodes"]}


class StructureBoundaryCase(unittest.TestCase):
    """人の条件 (1)・(2): 境の中の失敗は節の失敗にせず行なしで計画に進み、境の節そのものが落ちた周は h-plan の落ちと同じく
    planning と h-gate が走らない（計画なしで修正へ進まない）"""

    def runs(self, failed: str) -> dict:
        nodes = line_nodes()
        scope = scriptline.Scope("darkfactory", {})
        for nid in ("entering", "h-plan", "structuring", "h-structure"):
            scope.out[nid], scope.status[nid] = {"go": True}, "ok"
        scope.out.pop(failed)
        scope.status[failed] = "failed"
        scope.status["planning"] = "ok" if scriptline.ScriptLine._runs(None, scope, nodes["planning"], False) else "skipped"
        return {nid: scriptline.ScriptLine._runs(None, scope, nodes[nid], False) for nid in ("planning", "h-gate")}

    def test_edge_failure_stops_like_plan_failure(self):
        self.assertEqual(self.runs("h-structure"), {"planning": False, "h-gate": False})
        self.assertEqual(self.runs("h-structure"), self.runs("h-plan"))

    def test_block_failure_still_plans(self):
        nodes = line_nodes()
        scope = scriptline.Scope("darkfactory", {})
        for nid in ("entering", "h-plan"):
            scope.out[nid], scope.status[nid] = {"go": True}, "ok"
        scope.status["structuring"] = "failed"
        self.assertTrue(scriptline.ScriptLine._runs(None, scope, nodes["h-structure"], False))

    def test_unwritable_state_is_not_a_node_failure(self):
        with tempfile.TemporaryDirectory() as d:
            board = pathlib.Path(d) / "board"
            board.mkdir()
            (board / structmark.STATE_FILE).mkdir()   # 控えを書けない
            design = pathlib.Path(d) / "design.jsonl"
            design.write_bytes(b"")
            got = line_edge.structure_edge(board, {"ok": True, "status": "ok", "reason": "", "design_file": str(design),
                                                   "structure_file": "", "wall_s": 1.0})
            self.assertEqual((got["ok"], got["status"]), (True, "failed"), got)
            self.assertIn("控えを書けない", got["reason"])

    def test_no_plan_round_writes_no_mark(self):
        """h-plan の go が偽の周は planning が走らないので、「行なしで計画した」の印を書かない"""
        with tempfile.TemporaryDirectory() as d:
            got = line_edge.structure_edge(pathlib.Path(d), None, plan_go=False)
            self.assertEqual((got["ok"], got["status"]), (True, "skipped"))
            self.assertIsNone(structmark.read(d))
            self.assertEqual(line_edge.structure_edge(pathlib.Path(d), None)["status"], "failed")

    def test_block_reason_reaches_the_mark(self):
        with tempfile.TemporaryDirectory() as d:
            got = line_edge.structure_edge(pathlib.Path(d), {"ok": True, "status": "failed", "reason": "構造の目の会話が落ちた",
                                                             "design_file": "", "structure_file": "", "wall_s": 1.0})
            self.assertIn("構造の目の会話が落ちた", got["reason"])
            self.assertIn("構造の目の会話が落ちた", structmark.note(structmark.read(d)))


class AfterWiringCase(unittest.TestCase):
    """直しの後の実測の配線（計画 2026-10-09-clean-whole の Task 2.5）: 構造のブロックを直しの後に 2 度目に差し込み、修正の起点の版を
    渡す。深さ（軽量の run）で省かない。境の節 h-after が控えを書き、独立の目の前の h-look がそれを待つ"""

    def test_light_run_still_measures(self):
        doc = yaml.safe_load((ROOT / "darkfactory" / "darkfactory.yaml").read_text(encoding="utf-8"))
        nodes = {n["id"]: n for n in doc["nodes"]}
        incs = [n for n in doc["nodes"] if n.get("include") == "blk-structure"]
        self.assertEqual(len(incs), 2)
        after = next(n for n in incs if (n.get("with") or {}).get("base_rev"))
        self.assertEqual(after["with"]["base_rev"], "$entering.output.base_rev")
        self.assertNotIn("when", after)   # 全部の単位が軽量の run でも回す
        self.assertFalse(any("skip" in k for k in after.get("with") or {}))
        self.assertIn(after["id"], nodes["h-after"]["depends_on"])
        self.assertEqual(nodes["h-after"]["trigger_rule"], "all_done")
        self.assertIn("h-after", nodes["h-look"]["depends_on"])
        first = next(n for n in incs if n is not after)
        self.assertNotIn("base_rev", first.get("with") or {})


if __name__ == "__main__":
    unittest.main()
