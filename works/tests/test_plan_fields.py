"""修正案の項目の works 側の欄（planmarks）。役の型への重ね・欠けと誤りの行・テストの定義の行の引き・欄を外す受け付けの口・
盤面の控えの周つきの読み書きを、関数を直に呼んで見る（FAST。種は dev の target-seed を一時の置き場に写すだけ。git・盤面・
子のプロセスなし）。test_stats.py の test_mean_of_three の定義は 8 行目、test_clamp_within_range は 11 行目"""
import json
import pathlib
import shutil
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
import accept  # noqa: E402
import planmarks  # noqa: E402

SEED = ROOT / "dev" / "target-seed"
GRAPH = accept.GRAPH_PATH
MEAN = "stats.py mean: 分母が len(xs) - 1 になっている"
PLAN_KEYS = {"unit_keys", "approach", "adds", "removes", "shrink_first", "narrows"}   # 写しの graph の修正案の項目の欄


def item(**over):
    base = {"unit_keys": [MEAN], "approach": "x" * 20, "adds": [], "removes": [], "shrink_first": "y" * 20, "narrows": [],
            "route": "tdd", "route_why": "",
            "tests": [{"id": "test_stats.py::TestStats::test_mean_of_two", "behavior": "2 つの値の平均を返す",
                       "path": "stats.mean を直に呼ぶ（mock なし）", "red_kind": "assertion", "red_why": "今は len-1 で割り 3.0 になる"}],
            "rewrite_tests": [], "refactor": {"declared": False, "why": ""}}
    return {**base, **over}


REWRITE = {"id": "test_stats.py::TestStats::test_clamp_within_range", "behavior": "上限の内側の値をそのまま返す",
           "old": "clamp(5, 0, 10) は 5", "new": "新しい期待（依頼で変わる振る舞い）"}


class PlanFieldsCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        shutil.copytree(SEED, self.repo, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))

    def gaps(self, *items):
        return planmarks.gaps({"plan": list(items)}, self.repo)


class TestRoleSchema(PlanFieldsCase):
    def test_role_schema_carries_plan_fields(self):
        it = accept.role_schema("p2.fix_plan")["properties"]["plan"]["items"]
        for k in ("route", "tests", "rewrite_tests", "refactor"):
            self.assertIn(k, it["required"])
        self.assertEqual(it["properties"]["route"]["enum"], ["tdd", "direct"])
        self.assertNotIn("tests", json.dumps(accept.role_schema("p2.plan_review")))
        copy_item = json.loads(GRAPH.read_text(encoding="utf-8"))["nodes"]["p2.fix_plan"]["schema"]["properties"]["plan"]["items"]
        self.assertEqual(set(copy_item["properties"]), PLAN_KEYS)

    def test_with_fields_leaves_other_nodes(self):
        schema = {"type": "object", "properties": {"x": {"type": "string"}}}
        self.assertIs(planmarks.with_fields("p2.plan_review", schema), schema)


class TestGaps(PlanFieldsCase):
    def test_gaps_tdd_item_needs_a_test(self):
        self.assertEqual(self.gaps(item()), [])
        got = self.gaps(item(tests=[]))
        self.assertTrue(any(g.startswith("plan[0].tests") for g in got), got)

    def test_gaps_direct_item_needs_route_why(self):
        got = self.gaps(item(route="direct", tests=[], route_why="短い"))
        self.assertTrue(any(g.startswith("plan[0].route_why") for g in got), got)
        self.assertEqual(self.gaps(item(route="direct", tests=[], route_why="文書だけの直しで先にテストを書けない")), [])

    def test_gaps_rewrite_must_name_an_existing_test(self):
        for tid in ("test_stats.py::TestStats::test_nope", "nope.py::T::t", "/abs/test_stats.py::TestStats::test_mean_of_three",
                    "../test_stats.py::TestStats::test_mean_of_three"):
            with self.subTest(tid):
                rw = [{"id": tid, "behavior": "依頼で変わる平均の定義", "old": "2", "new": "新しい期待は 2.0（float）"}]
                got = self.gaps(item(rewrite_tests=rw))
                self.assertTrue(any(g.startswith("plan[0].rewrite_tests[0]") and tid in g for g in got), got)

    def test_gaps_rewrite_of_existing_test_passes(self):
        self.assertEqual(self.gaps(item(rewrite_tests=[REWRITE])), [])

    def test_gaps_new_test_must_not_exist_yet(self):
        t = {**item()["tests"][0], "id": "test_stats.py::TestStats::test_mean_of_three"}
        got = self.gaps(item(tests=[t]))
        self.assertTrue(any("rewrite_tests" in g for g in got), got)   # 既に在るテストは rewrite_tests に書けと案内する

    def test_gaps_same_id_in_tests_and_rewrites(self):
        tid = REWRITE["id"]
        t = {**item()["tests"][0], "id": tid}
        got = self.gaps(item(tests=[t]), item(rewrite_tests=[REWRITE]))
        self.assertTrue(any(g.startswith("plan[1].rewrite_tests[0]") and tid in g and "plan[0].tests[0]" in g for g in got), got)

    def test_gaps_refactor_declared_needs_why(self):
        got = self.gaps(item(refactor={"declared": True, "why": "整える"}))
        self.assertTrue(any(g.startswith("plan[0].refactor") for g in got), got)
        self.assertEqual(self.gaps(item(refactor={"declared": True, "why": "名前の重なる 2 つの関数を 1 つに寄せる"})), [])

    def test_gaps_type_errors_are_named(self):
        got = self.gaps(item(route="maybe", tests="test_stats.py::TestStats::test_x"))
        self.assertTrue(any(g.startswith("plan[0].route") for g in got), got)
        self.assertTrue(any(g.startswith("plan[0].tests") for g in got), got)
        bare = {k: v for k, v in item().items() if k not in planmarks.KEYS}
        got = self.gaps(bare, "項目でない")
        for k in ("route", "tests", "rewrite_tests", "refactor"):
            self.assertTrue(any(g.startswith(f"plan[0].{k}") for g in got), (k, got))
        self.assertTrue(any(g.startswith("plan[1]") for g in got), got)
        self.assertEqual(planmarks.gaps("返答でない", self.repo), [])   # 返答の形は写しの規則が拒む

    def test_gaps_test_row_fields(self):
        t = {"id": "test_stats.py::TestStats::test_mean_of_two", "behavior": "短い", "red_kind": "import", "extra": 1}
        got = self.gaps(item(tests=[t]))
        for w in ("plan[0].tests[0].behavior", "plan[0].tests[0].red_kind", "'path'", "'red_why'", "'extra'"):
            self.assertTrue(any(w in g for g in got), (w, got))


class TestFindTest(PlanFieldsCase):
    def test_find_test_py_and_other(self):
        self.assertEqual(planmarks.find_test(self.repo, "test_stats.py::TestStats::test_mean_of_three"), 8)
        self.assertIsNone(planmarks.find_test(self.repo, "test_stats.py::Nope::test_mean_of_three"))
        (self.repo / "t.sh").write_text("a\ntest_x() {\n", encoding="utf-8")
        self.assertEqual(planmarks.find_test(self.repo, "t.sh::test_x"), 2)

    def test_find_test_module_function_and_misses(self):
        (self.repo / "test_top.py").write_text("import x\n\n\n@deco\ndef test_top():\n    pass\n", encoding="utf-8")
        self.assertEqual(planmarks.find_test(self.repo, "test_top.py::test_top"), 5)
        (self.repo / "broken.py").write_text("def test_b(:\n", encoding="utf-8")
        for tid in ("broken.py::test_b", "test_stats.py", "test_stats.py::test_mean_of_three", "nope.py::test_x",
                    "/abs/test_stats.py::TestStats::test_mean_of_three", "../repo/test_stats.py::TestStats::test_mean_of_three",
                    "test_stats.py::A::B::test_mean_of_three", "::test_x"):
            with self.subTest(tid):
                self.assertIsNone(planmarks.find_test(self.repo, tid))

    def test_find_test_symlink_out_of_root(self):
        outside = self.tmp / "out.py"
        outside.write_text("def test_o():\n    pass\n", encoding="utf-8")
        (self.repo / "link.py").symlink_to(outside)
        self.assertIsNone(planmarks.find_test(self.repo, "link.py::test_o"))


class TestSplitAndBoard(PlanFieldsCase):
    def test_split_strips_fields_and_resolves_limit(self):
        rw = [{"id": "test_stats.py::TestStats::test_clamp_within_range", "behavior": "上限の内側の値をそのまま返す",
               "old": "5", "new": "新しい期待（依頼で変わる振る舞い）"}]
        reply = {"plan": [item(rewrite_tests=rw)]}
        bare, fields = planmarks.split(reply, self.repo)
        self.assertEqual(set(bare["plan"][0]), PLAN_KEYS)
        self.assertEqual(fields[0]["rewrite_tests"][0]["limit"], "test_stats.py:11")
        self.assertEqual(fields[0]["route"], "tdd")
        self.assertIn("tests", reply["plan"][0])   # 渡した返答は変えない

    def test_save_read_by_round(self):
        b = types.SimpleNamespace(dir=self.tmp, round=1)
        planmarks.save(self.tmp, 1, [{"route": "tdd"}])
        self.assertEqual(planmarks.read(b), [{"route": "tdd"}])
        self.assertIsNone(planmarks.read(types.SimpleNamespace(dir=self.tmp, round=2)))
        (self.tmp / planmarks.FIELDS_FILE).write_text("{壊れた", encoding="utf-8")
        self.assertIsNone(planmarks.read(b))
        self.assertIsNone(planmarks.read(types.SimpleNamespace(dir=self.tmp / "無い", round=1)))

    def test_rewrites_rows(self):
        _, fields = planmarks.split({"plan": [item(), item(unit_keys=["u2"], tests=[], route="direct",
                                                           route_why="文書だけの直しで先にテストを書けない",
                                                           rewrite_tests=[REWRITE])]}, self.repo)
        planmarks.save(self.tmp, 3, fields)
        b = types.SimpleNamespace(dir=self.tmp, round=3)
        self.assertEqual(planmarks.rewrites(b), [{"item": 2, "unit_keys": ["u2"], "id": REWRITE["id"], "new": REWRITE["new"],
                                                  "limit": "test_stats.py:11"}])
        self.assertEqual(planmarks.rewrites(types.SimpleNamespace(dir=self.tmp, round=4)), [])

    def test_review_section(self):
        self.assertEqual(planmarks.review_section(types.SimpleNamespace(dir=self.tmp, round=1)), "")
        _, fields = planmarks.split({"plan": [item()]}, self.repo)
        planmarks.save(self.tmp, 1, fields)
        got = planmarks.review_section(types.SimpleNamespace(dir=self.tmp, round=1))
        self.assertTrue(got.startswith("\n\n" + planmarks.REVIEW_HEAD), got)
        for w in (planmarks.REVIEW_ASK, "test_stats.py::TestStats::test_mean_of_two", "本物の経路", "mock"):
            self.assertIn(w, got)

    def test_head_names_every_field(self):
        for w in ("route", "route_why", "tests", "rewrite_tests", "refactor", "red_kind", "assertion", "exception", "brief"):
            self.assertIn(w, planmarks.HEAD)


class TestFrozenFields(PlanFieldsCase):
    """盤面の控え plan-fields.json の凍結: save が trace に印 {round, sha256} を書き、許しの元（rewrites）は印と突き合わせて読む"""

    def saved(self, rnd=1):
        _, fields = planmarks.split({"plan": [item(rewrite_tests=[REWRITE])]}, self.repo)
        planmarks.save(self.tmp, rnd, fields)
        return types.SimpleNamespace(dir=self.tmp, round=rnd)

    def marks(self):
        rows = [json.loads(x) for x in (self.tmp / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        return [r for r in rows if r.get("op") == planmarks.SAVED_OP]

    def test_save_writes_mark_with_round_and_sha(self):
        import hashlib
        self.saved(2)
        raw = (self.tmp / planmarks.FIELDS_FILE).read_bytes()
        got = self.marks()
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["round"], got[0]["sha256"]), (2, hashlib.sha256(raw).hexdigest()))

    def test_frozen_reads_saved_fields(self):
        b = self.saved()
        self.assertEqual(planmarks.frozen(b), planmarks.read(b))
        self.assertEqual(len(planmarks.rewrites(b)), 1)

    def test_rewritten_after_save_is_broken(self):
        """受け付けの後に rewrite_tests の行を足した控えは、許しの元にしない（FieldsBroken。理由に plan-fields.json を名指す）"""
        b = self.saved()
        p = self.tmp / planmarks.FIELDS_FILE
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["fields"][0]["rewrite_tests"].append(dict(REWRITE, id="test_stats.py::TestStats::test_mean_of_three",
                                                      limit="test_stats.py:8"))
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        for fn in (planmarks.frozen, planmarks.rewrites):
            with self.subTest(fn.__name__), self.assertRaisesRegex(planmarks.FieldsBroken, planmarks.FIELDS_FILE):
                fn(b)

    def test_removed_after_save_is_broken(self):
        b = self.saved()
        (self.tmp / planmarks.FIELDS_FILE).unlink()
        with self.assertRaisesRegex(planmarks.FieldsBroken, planmarks.FIELDS_FILE):
            planmarks.frozen(b)

    def test_unmarked_fields_read_as_none(self):
        """印の無い控え（変更前の盤面・save の外で置いた物）は無い物として読む（許しを広げない）"""
        _, fields = planmarks.split({"plan": [item(rewrite_tests=[REWRITE])]}, self.repo)
        (self.tmp / planmarks.FIELDS_FILE).write_text(json.dumps({"round": 1, "fields": fields}, ensure_ascii=False),
                                                      encoding="utf-8")
        b = types.SimpleNamespace(dir=self.tmp, round=1)
        self.assertIsNone(planmarks.frozen(b))
        self.assertEqual(planmarks.rewrites(b), [])

    def test_mark_of_other_round_does_not_count(self):
        self.saved(1)
        self.assertIsNone(planmarks.frozen(types.SimpleNamespace(dir=self.tmp, round=2)))


if __name__ == "__main__":
    unittest.main()
