"""単位ごとの深さ（darkfactory/lib/depth.py。計画 docs/plans/2026-10-06-variable-depth.md）の検査。関数を直に呼び、一時の置き場に
控えを書くだけ（FAST。盤面・git・子のプロセスなし）。

語:
- 深さ: 単位の工程の厚さ。標準は今の振る舞いのすべて、軽量は測りで何も見つけなかった確かめ（レンズ・コメントの削除候補）を省く。
- 項目の欄: 修正案の項目ごとの works の欄（allowed_paths・tests・rewrite_tests・unit_keys）。
- 上げる信号: 修正の後に単位を標準へ上げる事実（食い違いの申し出・止めた単位・案の直し・再審・答えていない問い）。

見る物:
- 決め 3 の 5 つの条件を全部満たす単位だけが軽量で、1 つ外れれば標準と理由
- thickness の名指しで全部の単位を固定する（自動と空は機械が決める）
- 信号で上げる（単位に結べる物はその単位、結べない物は全部）・下げない
- run の深さは全部が軽量の時だけ軽量（単位が無ければ標準）
- 省く理由と報告の行（軽量で省いた物を名指す）
- 控えの書き読み
"""
import json
import pathlib
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import depth  # noqa: E402

U1, U2 = "u1: 一つ目の根本", "u2: 二つ目の根本"


def item(keys, paths=("a/b.py",), tests=1, rewrites=0):
    return {"unit_keys": list(keys), "allowed_paths": list(paths),
            "tests": [{"id": f"t.py::T::t{i}"} for i in range(tests)],
            "rewrite_tests": [{"id": f"r.py::R::r{i}"} for i in range(rewrites)]}


class UnitDepthCase(unittest.TestCase):
    def test_small_unit_with_checks_is_light(self):
        got, why = depth.unit_depth([item([U1], paths=("a.py", "b.py", "tests/t.py"), tests=1, rewrites=1)], U1, checked=True)
        self.assertEqual(got, depth.LIGHT)
        self.assertTrue(why)

    def test_each_condition_falls_to_standard_with_reason(self):
        cases = {
            "項目": ([item([U2])], True),
            "4 個": ([item([U1], paths=("a.py", "b.py", "c.py", "d.py"))], True),
            "glob": ([item([U1], paths=("tests/*.json",))], True),
            "3 本": ([item([U1], tests=2, rewrites=1)], True),
            "約束の形": ([item([U1], paths=("blk-x/schemas/a.schema.json",))], True),
            ".yml": ([item([U1], paths=(".github/workflows/test.yml",))], True),
            "darkfactory.yaml": ([item([U1], paths=("a.py", "darkfactory/darkfactory.yaml"))], True),   # 配線とコードを一緒に触る
            "機械の確かめ": ([item([U1])], False),
        }
        for word, (items, checked) in cases.items():
            with self.subTest(word=word):
                got, why = depth.unit_depth(items, U1, checked=checked)
                self.assertEqual(got, depth.STANDARD)
                self.assertTrue(any(word in w for w in why), why)

    def test_wiring_only_unit_is_light(self):
        """配線だけの単位（線とブロックの YAML（<名>/<名>.yaml）と manifest.json だけを触る）は、約束の形の条件に数えず軽量"""
        for paths in (("darkfactory/darkfactory.yaml",), ("blk-fix/blk-fix.yaml", "blk-fix/manifest.json"),
                      ("works/blk-plan/blk-plan.yml", "works/darkfactory/manifest.json", "works/darkfactory/darkfactory.yaml")):
            with self.subTest(paths=paths):
                got, why = depth.unit_depth([item([U1], paths=paths, tests=0)], U1, checked=True)
                self.assertEqual(got, depth.LIGHT, why)
                self.assertTrue(any("配線だけ" in w for w in why), why)

    def test_wiring_only_still_needs_the_other_conditions(self):
        for word, (items, checked) in {
            "4 個": ([item([U1], paths=("a/a.yaml", "b/b.yaml", "c/c.yaml", "d/manifest.json"))], True),
            "3 本": ([item([U1], paths=("a/a.yaml",), tests=3)], True),
            "機械の確かめ": ([item([U1], paths=("a/a.yaml",))], False),
            "約束の形": ([item([U1], paths=("a/a.yaml", "a/schemas/x.yaml"))], True),   # schemas/ の下は配線でない
            "nodes.json": ([item([U1], paths=("a/a.yaml", "a/nodes.json"))], True),     # 表は配線でない
        }.items():
            with self.subTest(word=word):
                got, why = depth.unit_depth(items, U1, checked=checked)
                self.assertEqual(got, depth.STANDARD)
                self.assertTrue(any(word in w for w in why), why)

    def test_no_items_is_standard(self):
        self.assertEqual(depth.unit_depth(None, U1, checked=True)[0], depth.STANDARD)


class DecideCase(unittest.TestCase):
    def test_auto_decides_per_unit(self):
        doc = depth.decide_doc([item([U1]), item([U2], paths=("a", "b", "c", "d"))], [U1, U2], forced="自動", checked=True)
        self.assertEqual({k: v["depth"] for k, v in doc["units"].items()}, {U1: depth.LIGHT, U2: depth.STANDARD})
        self.assertEqual(depth.run_depth(doc), depth.STANDARD)

    def test_empty_forced_is_auto(self):
        doc = depth.decide_doc([item([U1])], [U1], forced="", checked=True)
        self.assertEqual(doc["units"][U1]["depth"], depth.LIGHT)

    def test_forced_word_fixes_every_unit(self):
        big = item([U1], paths=("a", "b", "c", "d", "e"), tests=5)
        doc = depth.decide_doc([big], [U1], forced=depth.LIGHT, checked=False)
        self.assertEqual(doc["units"][U1]["depth"], depth.LIGHT)
        self.assertIn("名指し", " ".join(doc["units"][U1]["why"]))
        doc = depth.decide_doc([item([U1])], [U1], forced=depth.STANDARD, checked=True)
        self.assertEqual(doc["units"][U1]["depth"], depth.STANDARD)

    def test_no_units_is_standard_run(self):
        doc = depth.decide_doc(None, [], forced="", checked=True)
        self.assertEqual(depth.run_depth(doc), depth.STANDARD)
        self.assertEqual(depth.skip_reason(doc), "")


class RaiseCase(unittest.TestCase):
    def setUp(self):
        self.doc = depth.decide_doc([item([U1]), item([U2])], [U1, U2], forced="", checked=True)
        self.assertEqual(depth.run_depth(self.doc), depth.LIGHT)

    def test_unit_signal_raises_only_that_unit(self):
        got = depth.raise_doc(self.doc, units={U1: "食い違いの申し出"}, run=[])
        self.assertEqual(got["units"][U1]["depth"], depth.STANDARD)
        self.assertEqual(got["units"][U2]["depth"], depth.LIGHT)
        self.assertIn("食い違いの申し出", " ".join(got["units"][U1]["why"]))
        self.assertEqual(depth.run_depth(got), depth.STANDARD)

    def test_run_signal_raises_every_unit(self):
        got = depth.raise_doc(self.doc, units={}, run=["案の直しが走った"])
        self.assertEqual({v["depth"] for v in got["units"].values()}, {depth.STANDARD})
        self.assertIn("案の直しが走った", got["raised"])

    def test_signal_on_unknown_unit_is_kept_as_raised(self):
        got = depth.raise_doc(self.doc, units={"u9": "止めた"}, run=[])
        self.assertEqual(depth.run_depth(got), depth.LIGHT)
        self.assertTrue(any("u9" in r for r in got["raised"]))

    def test_no_signal_keeps_light(self):
        got = depth.raise_doc(self.doc, units={}, run=[])
        self.assertEqual(depth.run_depth(got), depth.LIGHT)


class LinesCase(unittest.TestCase):
    def test_light_run_names_what_it_skipped(self):
        doc = depth.decide_doc([item([U1])], [U1], forced="", checked=True)
        reason = depth.skip_reason(doc)
        self.assertIn("軽量", reason)
        text = "\n".join(depth.lines(doc))
        skipped = [x for x in depth.lines(doc) if x.startswith("軽量で省いた: ")]
        self.assertEqual(len(skipped), 1, "省いた物は 1 行にまとめる（2026-10-09 の片付け）")
        for word in ("差分の審査", "レンズ", "r1.comment_candidates", "R1", "R2", "R3", "R4"):
            self.assertIn(word, skipped[0])
        self.assertNotIn("AI の報告", text, "AI の報告は省かない（計画の決め 10）")

    def test_standard_run_skips_nothing(self):
        doc = depth.decide_doc([item([U1], tests=4)], [U1], forced="", checked=True)
        self.assertEqual(depth.skip_reason(doc), "")
        text = "\n".join(depth.lines(doc))
        self.assertNotIn("軽量で省いた", text)
        self.assertIn("標準", text)


class WordsCase(unittest.TestCase):
    def test_skipped_review_has_plain_word(self):
        """省いた目（記録の reviews の skipped）は、最後の関所と報告の目の行に平易な語で出る"""
        import gatemarks
        self.assertEqual(gatemarks.eye_named("R1", "skipped"), f"{gatemarks.EYES['R1']}（R1）: 軽量で省いた（skipped）")

    def test_docs_thresholds_name_constants(self):
        """閾値の正本は depth.MAX_PATHS・MAX_TESTS の 1 か所。計画の決め 3・4・11 と流れの文書の 12a は定数を名指し、文書に残る数字は
        定数（以下の側）か定数＋1（「以上」の側が残る時）と同じ"""
        docs = ROOT / "docs"
        plan = (docs / "plans" / "2026-10-06-variable-depth.md").read_text(encoding="utf-8").splitlines()
        flow = (docs / "darkfactory-flow.md").read_text(encoding="utf-8").splitlines()

        def section(lines, head):
            start = next(i for i, ln in enumerate(lines) if ln.startswith(head))
            end = next((i for i in range(start + 1, len(lines))
                        if lines[i].startswith(("- **決め", "## ")) or re.match(r"\d+[a-z]?\. ", lines[i])), len(lines))
            return "\n".join(lines[start:end])

        parts = {"決め 3": section(plan, "- **決め 3（"), "決め 4": section(plan, "- **決め 4（"),
                 "決め 11": section(plan, "- **決め 11（"), "12a": section(flow, "12a. ")}
        for name, text in parts.items():
            with self.subTest(name=name):
                self.assertIn("depth.MAX_PATHS", text)
                self.assertIn("depth.MAX_TESTS", text)
                for n in re.findall(r"(\d+) 個以下", text):
                    self.assertEqual(int(n), depth.MAX_PATHS)
                for n in re.findall(r"(\d+) 本以下", text):
                    self.assertEqual(int(n), depth.MAX_TESTS)
                for n in re.findall(r"(\d+) 個以上", text):
                    self.assertEqual(int(n), depth.MAX_PATHS + 1)
                for n in re.findall(r"(\d+) 本以上", text):
                    self.assertEqual(int(n), depth.MAX_TESTS + 1)
        for name in ("決め 4", "12a"):
            with self.subTest(name=name, word="超える"):
                self.assertIn("超える", parts[name])
        self.assertIn("loop.fix_delta", parts["決め 4"])
        self.assertNotIn("範囲の相談で足したパスは数えない", parts["決め 4"])


class FileCase(unittest.TestCase):
    def test_write_and_read(self):
        with tempfile.TemporaryDirectory() as d:
            doc = depth.decide_doc([item([U1])], [U1], forced="", checked=True)
            path = depth.write(pathlib.Path(d), doc)
            self.assertEqual(path.name, depth.FILE)
            self.assertEqual(depth.read(pathlib.Path(d)), doc)
            self.assertEqual(json.loads(depth.unit_map(doc)), {U1: depth.LIGHT})

    def test_read_missing_is_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(depth.read(pathlib.Path(d)))


class BoardReadCase(unittest.TestCase):
    """盤面を読む口（decide・signals・raise_）。盤面は dir・round・record だけを持つ偽物で、控えのファイルを一時の置き場に書く"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.skipped = {}
        self.b = types.SimpleNamespace(dir=self.dir, round=1, record={"questions": []}, state={},
                                       node_state=lambda nid: "done" if nid in self.skipped else "pending",
                                       skip=lambda nid, why: self.skipped.__setitem__(nid, why))
        put(self.dir / "plan-fields.json", {"round": 1, "fields": [item([U1]), item([U2], tests=4)]})

    def start(self, **kw):
        put(self.dir / "r1" / "start.json", {"thickness": "自動", "test_cmd": "", **kw})

    def test_decide_reads_fields_and_start_and_writes_file(self):
        self.start(test_cmd="sh t.sh")
        doc = depth.decide(self.b, json.dumps([U1, U2]), tdd_suite="")
        self.assertEqual({k: v["depth"] for k, v in doc["units"].items()}, {U1: depth.LIGHT, U2: depth.STANDARD})
        self.assertEqual(depth.read(self.dir), doc)

    def test_decide_without_checks_is_standard(self):
        self.start()
        doc = depth.decide(self.b, json.dumps([U1]), tdd_suite="")
        self.assertEqual(doc["units"][U1]["depth"], depth.STANDARD)
        doc = depth.decide(self.b, json.dumps([U1]), tdd_suite="dev/suite.sh")
        self.assertEqual(doc["units"][U1]["depth"], depth.LIGHT)

    def test_decide_forced_word_from_start(self):
        self.start(thickness=depth.STANDARD, test_cmd="sh t.sh")
        doc = depth.decide(self.b, json.dumps([U1]), tdd_suite="")
        self.assertEqual(doc["units"][U1]["depth"], depth.STANDARD)

    def test_decide_unreadable_open_units_is_no_units(self):
        self.start(test_cmd="sh t.sh")
        self.assertEqual(depth.decide(self.b, "null", tdd_suite="")["units"], {})

    def test_signals_conflicts_and_parked(self):
        put(self.dir / "r1" / "conflicts.json", {"items": [{"unit_key": U2}]})   # 線の置き場（scope の登録が無い盤面は根だけ）
        (self.dir / "trace.jsonl").write_text(json.dumps({"op": "fix_bound_parked", "unit_keys": ["u3"]}) + "\n",
                                              encoding="utf-8")
        units, run = depth.signals(self.b)
        self.assertIn(U2, units)
        self.assertIn("食い違い", units[U2])
        self.assertIn("止めた", units["u3"])
        self.assertEqual(run, [])

    def test_signals_broken_conflicts_raise_all(self):
        (self.dir / "r1").mkdir()
        (self.dir / "r1" / "conflicts.json").write_text("{壊れた控え", encoding="utf-8")
        _, run = depth.signals(self.b)
        self.assertTrue(any("食い違いの控えが読めない" in r for r in run), run)

    def test_signals_unanswered_questions_raise_all(self):
        with mock.patch.object(depth.gatemarks, "pending", return_value=[{"key": "q1", "kind": "fork"}]):
            units, run = depth.signals(self.b)
        self.assertEqual(units, {})
        self.assertTrue(any("q1" in r for r in run))

    def test_raise_reads_line_signals(self):
        self.start(test_cmd="sh t.sh")
        put(self.dir / "plan-fields.json", {"round": 1, "fields": [item([U1])]})
        depth.decide(self.b, json.dumps([U1]), tdd_suite="")
        doc = depth.raise_(self.b, replanned=False, rejudged=False)
        self.assertEqual(depth.run_depth(doc), depth.LIGHT)
        doc = depth.raise_(self.b, replanned=True, rejudged=False)
        self.assertEqual(depth.run_depth(doc), depth.STANDARD)
        self.assertTrue(any("案の直し" in r for r in doc["raised"]))
        self.assertEqual(depth.read(self.dir), doc)

    def test_raise_light_skips_pending_delta_review_only(self):
        """run が軽量のままなら、待っている差分の審査を省く理由で盤面から省く。標準なら省かない"""
        self.start(test_cmd="sh t.sh")
        put(self.dir / "plan-fields.json", {"round": 1, "fields": [item([U1])]})
        depth.decide(self.b, json.dumps([U1]), tdd_suite="")
        doc = depth.raise_(self.b, replanned=False, rejudged=False)
        self.assertEqual(self.skipped, {depth.DELTA_NODE: depth.skip_reason(doc)})
        self.skipped.clear()
        depth.raise_(self.b, replanned=True, rejudged=False)
        self.assertEqual(self.skipped, {})

    def test_raise_wide_paths_make_run_standard(self):
        """単位ごとには軽量でも、run 全体で触るファイルが多ければ標準へ上げ、差分の審査も省かない。重なるファイルは 1 個に数える"""
        self.start(test_cmd="sh t.sh")
        put(self.dir / "plan-fields.json", {"round": 1, "fields": [
            item([U1], paths=("a/1.py", "a/2.py")), item([U2], paths=("b/1.py", "b/2.py"))]})
        doc = depth.decide(self.b, json.dumps([U1, U2]), tdd_suite="")
        self.assertEqual(json.loads(depth.unit_map(doc)), {U1: depth.LIGHT, U2: depth.LIGHT})
        doc = depth.raise_(self.b, replanned=False, rejudged=False)
        self.assertEqual(json.loads(depth.unit_map(doc)), {U1: depth.STANDARD, U2: depth.STANDARD})
        self.assertEqual(depth.run_depth(doc), depth.STANDARD)
        self.assertIn("run 全体で触るファイル 4 個（3 個まで）", doc["raised"])
        self.assertEqual(depth.skip_reason(doc), "")
        self.assertEqual(self.skipped, {})

        put(self.dir / "plan-fields.json", {"round": 1, "fields": [
            item([U1], paths=("a/x.py",)), item([U2], paths=("a/x.py",))]})
        depth.decide(self.b, json.dumps([U1, U2]), tdd_suite="")
        doc = depth.raise_(self.b, replanned=False, rejudged=False)
        self.assertEqual(depth.run_depth(doc), depth.LIGHT)
        self.assertEqual(doc["raised"], [])
        self.assertEqual(self.skipped, {depth.DELTA_NODE: depth.skip_reason(doc)})

    def test_raise_wide_tests_make_run_standard_even_when_forced_light(self):
        """単位ごとには軽量でも、run 全体の受け入れと書き換えのテストが上限を超えれば標準へ上げる。ちょうど上限なら軽量のまま。軽量の名指しでも同じ"""
        at_limit = [item([U1], tests=1), item([U2], tests=depth.MAX_TESTS - 1)]
        over_limit = [item([U1], tests=1), item([U2], tests=depth.MAX_TESTS)]
        for thickness in ("自動", depth.LIGHT):
            for total, fields in ((depth.MAX_TESTS, at_limit), (depth.MAX_TESTS + 1, over_limit)):
                with self.subTest(thickness=thickness, total=total):
                    self.skipped.clear()
                    put(self.dir / "plan-fields.json", {"round": 1, "fields": fields})
                    self.start(thickness=thickness, test_cmd="sh t.sh")
                    doc = depth.decide(self.b, json.dumps([U1, U2]), tdd_suite="")
                    self.assertEqual(depth.run_depth(doc), depth.LIGHT)
                    doc = depth.raise_(self.b, replanned=False, rejudged=False)
                    if total <= depth.MAX_TESTS:
                        self.assertEqual(depth.run_depth(doc), depth.LIGHT)
                        self.assertEqual(doc["raised"], [])
                        self.assertEqual(self.skipped, {depth.DELTA_NODE: depth.skip_reason(doc)})
                    else:
                        self.assertEqual(depth.run_depth(doc), depth.STANDARD)
                        self.assertIn(f"run 全体の受け入れと書き換えのテストが {total} 本（{depth.MAX_TESTS} 本まで）",
                                      doc["raised"])
                        self.assertEqual(self.skipped, {})

    def test_raise_counts_actual_diff_beyond_plan(self):
        """計画の allowed_paths は上限以内でも、修正の実際の差分（loop.fix_delta）の足すパスで和が上限を超えれば標準へ上がり、差分の審査を
        省かない。ちょうど上限・重なりは 1 個・テストのファイルは数えず軽量のまま。差分が無ければ計画で数え、控えの counted に理由が残る"""
        rev = "f1x2d3l4t5"
        plan = ("a/1.py", "a/2.py")
        cases = (   # (名, 計画の allowed_paths, 実際の差分のファイル, 標準へ上がるか, 数えた数)
            ("上限を超える", plan, ["a/1.py", "a/2.py", "a/3.py", "a/4.py"], True, 4),
            ("ちょうど上限", plan, ["a/3.py"], False, 3),
            ("重なりは 1 個", plan, ["a/2.py", "a/3.py"], False, 3),
            ("テストのファイルは数えない", plan + ("a/3.py",), ["a/1.py", "t.py"], False, 3),
        )
        for word, paths, files, raised, count in cases:
            with self.subTest(word=word):
                self.skipped.clear()
                self.start(test_cmd="sh t.sh")
                put(self.dir / "plan-fields.json", {"round": 1, "fields": [item([U1], paths=paths)]})
                self.b.loop_state = {"fix_delta": {"round": 1, "file": "p.patch", "files": files, "rev": rev}}
                depth.decide(self.b, json.dumps([U1]), tdd_suite="")
                doc = depth.raise_(self.b, replanned=False, rejudged=False)
                self.assertEqual(depth.run_depth(doc), depth.STANDARD if raised else depth.LIGHT)
                self.assertEqual(self.skipped, {} if raised else {depth.DELTA_NODE: depth.skip_reason(doc)})
                counted = doc.get("counted") or ""
                self.assertIn(f"{count} 個", counted)
                self.assertIn(rev, counted)
                self.assertEqual(depth.read(self.dir).get("counted"), doc.get("counted"))
        stale = {"fix_delta": {"round": 0, "files": ["a/3.py", "a/4.py", "a/5.py"], "rev": rev}}
        for word, loop_state in (("差分なし", {}), ("前の周の差分", stale)):
            with self.subTest(word=word):
                self.skipped.clear()
                self.start(test_cmd="sh t.sh")
                put(self.dir / "plan-fields.json", {"round": 1, "fields": [item([U1], paths=plan)]})
                self.b.loop_state = loop_state
                depth.decide(self.b, json.dumps([U1]), tdd_suite="")
                doc = depth.raise_(self.b, replanned=False, rejudged=False)
                self.assertEqual(depth.run_depth(doc), depth.LIGHT)
                counted = doc.get("counted") or ""
                self.assertIn("2 個", counted)
                self.assertIn("計画の allowed_paths", counted)
                self.assertNotIn(rev, counted)

    def test_raise_does_not_count_undeclared_test_files(self):
        """項目の tests・rewrite_tests に宣言の無いテストのファイル（名の慣習に当たる別のテストのモジュール）は、修正の実際の差分に
        在っても run の広さに数えない。実装のファイルだけを数える"""
        self.start(test_cmd="sh t.sh")
        put(self.dir / "plan-fields.json", {"round": 1, "fields": [item([U1], paths=("a/1.py", "a/2.py"))]})
        files = ["a/3.py", "tests/test_extra.py", "a/test_more.py"]
        self.b.loop_state = {"fix_delta": {"round": 1, "file": "p.patch", "files": files, "rev": "f1x2d3l4t5"}}
        depth.decide(self.b, json.dumps([U1]), tdd_suite="")
        doc = depth.raise_(self.b, replanned=False, rejudged=False)
        self.assertEqual(depth.run_depth(doc), depth.LIGHT)
        self.assertIn("3 個", doc.get("counted") or "")

    def test_raise_without_file_is_standard(self):
        doc = depth.raise_(self.b, replanned=False, rejudged=True)
        self.assertEqual(depth.run_depth(doc), depth.STANDARD)
        self.assertEqual(depth.skip_reason(doc), "")


class NodeCase(unittest.TestCase):
    """線の節の口 node（darkfactory/scripts/depth.py の中身）と、スクリプトを Archon と同じ形（with: → INPUTS_*）で起こした出口"""

    def test_node_on_unopenable_board_falls_to_standard(self):
        with tempfile.TemporaryDirectory() as d:
            for at in ("decide", "raise"):
                with self.subTest(at):
                    out = depth.node(pathlib.Path(d), at)
                    self.assertEqual((out["ok"], out["depth"], out["skip"]), (False, depth.STANDARD, ""))
                    self.assertIn("盤面", out["why"])
                    self.assertEqual(set(out), set(depth.NODE_FIELDS))

    def test_node_refuses_unknown_at(self):
        with tempfile.TemporaryDirectory() as d, self.assertRaises(ValueError):
            depth.node(pathlib.Path(d), "x")

    def test_script_emits_one_line(self):
        import subprocess
        with tempfile.TemporaryDirectory() as d:
            env = {"PATH": "/usr/bin:/bin", "ARTIFACTS_DIR": d, "INPUTS_AT": "raise", "INPUTS_OPEN_UNITS": "",
                   "INPUTS_TDD_SUITE": "", "INPUTS_REPLANNED": "false", "INPUTS_REJUDGED": "false", "PYTHONDONTWRITEBYTECODE": "1"}
            r = subprocess.run([sys.executable, str(ROOT / "darkfactory" / "scripts" / "depth.py")], env=env, cwd=d,
                               capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = json.loads(r.stdout)
            self.assertEqual(out["depth"], depth.STANDARD)
            env.pop("INPUTS_AT")
            r = subprocess.run([sys.executable, str(ROOT / "darkfactory" / "scripts" / "depth.py")], env=env, cwd=d,
                               capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
            self.assertEqual((r.returncode, r.stdout), (2, ""))
            self.assertIn("INPUTS_AT", r.stderr)


def put(path: pathlib.Path, doc) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    unittest.main()
