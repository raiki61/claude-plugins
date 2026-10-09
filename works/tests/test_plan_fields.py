"""修正案の項目の works 側の欄（planmarks）。役の型への重ね・欠けと誤りの行・テストの定義の行の引き・欄を外す受け付けの口・
盤面の控えの周つきの読み書きを、関数を直に呼んで見る（FAST。種は dev の target-seed を一時の置き場に写すだけ。git・盤面・
子のプロセスなし）。test_stats.py の test_mean_of_three の定義は 8 行目、test_clamp_within_range は 11 行目"""
import copy
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
            "rewrite_tests": [], "refactor": {"declared": False, "why": ""}, "allowed_paths": ["stats.py"], "out_of_scope": []}
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

    def test_gaps_same_test_id_with_two_red_kinds_rejected(self):
        """同じ受け入れのテストの id を 2 つの項目が別の赤の種類で宣言したら拒む（黙って先の物を勝たせない）。同じ種類なら通す"""
        t = item()["tests"][0]
        got = self.gaps(item(), item(tests=[dict(t, red_kind="exception")]))
        self.assertTrue(any(g.startswith("plan[1].tests[0]") and "red_kind" in g for g in got), got)
        self.assertEqual(self.gaps(item(), item()), [])

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

    def test_gaps_adds_symbol_kind_named_by_file(self):
        """kind が関数・欄（function・record_field）の adds の name がファイルの名・パスだけなら、行を名指して拒み、識別子で書いて
        パスは canonical に書けと言う（依頼 194c: receivers.py と書いた名を TDD の輪が 'py' と比べた）。ほかの誤りと同じ 1 回の拒否に
        並べる。識別子・<パス>::<名前>・説明の文・ファイルを名指すのが筋の kind（doc など）は今どおり通す"""
        def add(kind, name):
            return {"kind": kind, "name": name, "canonical": "新設: app/receivers.py"}
        got = self.gaps(item(adds=[add("function", "clamp"), add("function", "receivers.py"),
                                   add("record_field", "app/schema/fields.json"), add("function", " app/receivers ")], route="maybe"))
        for j, nm in ((1, "receivers.py"), (2, "app/schema/fields.json"), (3, "app/receivers")):
            row = [g for g in got if g.startswith(f"plan[0].adds[{j}].name")]
            self.assertEqual(len(row), 1, got)
            self.assertIn(nm, row[0])
            self.assertIn("canonical", row[0])
        self.assertFalse(any(g.startswith("plan[0].adds[0]") for g in got), got)
        self.assertTrue(any(g.startswith("plan[0].route") for g in got), got)          # ほかの誤りと 1 回で並ぶ
        for kind, name in (("function", "Stats.median"), ("function", "app.receivers.handle"),
                           ("function", "app/receivers.py::handle"), ("function", "role_run._probe(pgid_file) -> (pgid, why)"),
                           ("function", "tests/run.sh skip_capability（見送りの行から能力の名前を取り出す）"),
                           ("record_field", "plan[].adds[].name"), ("record_field", "event.ts"), ("function", "Response.json"),
                           ("record_field", "tests/_real_db.SKIP_REASON"),   # モジュールのパスと属性（本物の案の名）
                           ("function", "app/stats.mean"), ("record_field", "/plan/adds"),
                           ("doc", "docs/scope.md"), ("config", "setup.cfg"),
                           ("test", "test_stats.py::TestStats::test_mean_of_two"), ("other", "receivers.py")):
            with self.subTest(kind=kind, name=name):
                self.assertEqual(self.gaps(item(adds=[add(kind, name)])), [])

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


class TestIdPaths(PlanFieldsCase):
    """テストの id のパス: 区切りは /・根からの相対（絶対パスを拒む）・`..` で始まる名前のファイルは根の中"""

    def test_backslash_in_id_rejected(self):
        """\\ の入った id は、limit がそのまま残るので受け付けで拒む（理由に「/ で書け」）"""
        bad_rw = dict(REWRITE, id="test_stats.py\\..\\x::TestStats::test_clamp_within_range")
        bad_new = {"id": "tests\\test_new.py::test_x", "behavior": "2 つの値の平均を返す", "path": "stats.mean を直に呼ぶ（mock なし）",
                   "red_kind": "assertion", "red_why": "今は len-1 で割り 3.0 になる"}
        got = self.gaps(item(tests=[bad_new], rewrite_tests=[bad_rw]))
        rows = [g for g in got if "/ で書け" in g]
        self.assertEqual(len(rows), 2, got)
        self.assertTrue(any(g.startswith("plan[0].tests[0].id") for g in rows), got)
        self.assertTrue(any(g.startswith("plan[0].rewrite_tests[0].id") for g in rows), got)

    def test_absolute_tests_id_rejected(self):
        new = {"id": str(self.repo / "test_new.py") + "::test_x", "behavior": "2 つの値の平均を返す",
               "path": "stats.mean を直に呼ぶ（mock なし）", "red_kind": "assertion", "red_why": "今は len-1 で割り 3.0 になる"}
        got = self.gaps(item(tests=[new]))
        self.assertTrue(any(g.startswith("plan[0].tests[0].id") and "根からの相対" in g for g in got), got)

    def test_outside_root_tests_id_rejected(self):
        new = {"id": "../test_new.py::test_x", "behavior": "2 つの値の平均を返す",
               "path": "stats.mean を直に呼ぶ（mock なし）", "red_kind": "assertion", "red_why": "今は len-1 で割り 3.0 になる"}
        got = self.gaps(item(tests=[new]))
        self.assertTrue(any(g.startswith("plan[0].tests[0].id") and "根からの相対" in g for g in got), got)

    def test_relative_tests_id_passes(self):
        self.assertEqual(self.gaps(item()), [])

    def test_dotdot_prefixed_name_inside_root_found(self):
        """`..foo/x.py` は根の中のディレクトリ `..foo` の物（`..` の上り口でない）"""
        d = self.repo / "..foo"
        d.mkdir()
        (d / "x.py").write_text("def test_o():\n    pass\n", encoding="utf-8")
        self.assertEqual(planmarks.find_test(self.repo, "..foo/x.py::test_o"), 1)
        self.assertIsNone(planmarks.find_test(self.repo, "../x.py::test_o"))


CLAMP = "stats.py clamp: 上限を超えた値に lo を返す"


class UnitContractCase(unittest.TestCase):
    """単位の約束（planmarks.unit_contract）: その単位を unit_keys に含む項目の欄を合わせた物。純粋（盤面もファイルも読まない）"""
    T1 = {"id": "test_stats.py::TestStats::test_mean_of_two", "behavior": "x" * 10, "path": "y" * 10,
          "red_kind": "assertion", "red_why": "z" * 10}
    RW = {"id": "test_stats.py::TestStats::test_clamp_above_range", "behavior": "x" * 10, "old": "lo を返す",
          "new": "上限を超えたら hi を返す", "limit": "test_stats.py:14"}

    def f(self, keys, **over):
        return {"unit_keys": keys, "route": "tdd", "route_why": "", "tests": [], "rewrite_tests": [],
                "refactor": {"declared": False, "why": ""}, **over}

    def test_contract_joins_items_of_the_unit(self):
        fields = [self.f([MEAN], tests=[self.T1]), self.f([MEAN, CLAMP], route="direct", route_why="w" * 10,
                                                          rewrite_tests=[self.RW], refactor={"declared": True, "why": "w" * 10})]
        got = planmarks.unit_contract(fields, MEAN)
        self.assertEqual(got, {"items": [1, 2], "route": "tdd",
                               "tests": [{"id": self.T1["id"], "red_kind": "assertion"}],
                               "rewrites": [self.RW["id"]], "refactor": [{"item": 2, "why": "w" * 10}],
                               "names": []})
        self.assertEqual(planmarks.unit_contract(fields, CLAMP)["route"], "direct")

    def test_contract_refactor_empty_without_declaration(self):
        """整えの申告は申告した項目の {item, why} の並び。申告が無ければ空"""
        self.assertEqual(planmarks.unit_contract([self.f([MEAN])], MEAN)["refactor"], [])

    def test_contract_none_without_fields_or_items(self):
        self.assertIsNone(planmarks.unit_contract(None, MEAN))
        self.assertIsNone(planmarks.unit_contract([self.f([CLAMP])], MEAN))

    def test_rewrite_without_limit_is_not_in_contract(self):
        rw = {k: v for k, v in self.RW.items() if k != "limit"}
        self.assertEqual(planmarks.unit_contract([self.f([MEAN], rewrite_tests=[rw])], MEAN)["rewrites"], [])

    def test_same_test_id_in_two_items_listed_once(self):
        """tests は項目の順で、id の重複を除く"""
        fields = [self.f([MEAN], tests=[self.T1]), self.f([MEAN], tests=[dict(self.T1, red_kind="exception")])]
        self.assertEqual(planmarks.unit_contract(fields, MEAN)["tests"], [{"id": self.T1["id"], "red_kind": "assertion"}])


class TestLineScenarioPlans(PlanFieldsCase):
    """線を本物のスクリプトで回す筋書き（test_script_contract。遅い段）の修正案の役の返答が、blk-plan の受け付けの gaps を通る。
    欄の欠けた返答を渡すと 3 回とも拒まれて盤面が止まり（by works:plan）、fixed・stopped_by_human を待つ筋書きが全部
    stopped_by_line で終わる（依頼 217 の後に起きた）。それを筋書きを回さずに見る（筋書きの組を作るだけ。盤面・git・子のプロセスなし）"""

    def test_scenario_plan_replies_pass_gaps(self):
        tests = str(ROOT / "tests")
        if tests not in sys.path:
            sys.path.insert(0, tests)
        import test_script_contract as SC
        seen = 0
        for name, kw in SC.scenarios(self.tmp).items():
            for key in ("plan", "blk-plan/plan"):
                got = (kw.get("replies") or {}).get(key)
                for attempt in (1, 2, 3):
                    reply = got(attempt) if callable(got) else got
                    if not (isinstance(reply, dict) and reply.get("plan")):
                        continue   # 諦めの筋書きの空の返答（拒ませる物）
                    seen += 1
                    with self.subTest(f"{name}/{key}/{attempt}"):
                        self.assertEqual(planmarks.gaps(reply, self.repo), [])
        self.assertGreater(seen, 0)


class TestUnitContract(PlanFieldsCase):
    def test_names_from_adds(self):
        """split は項目の adds の name を写し、unit_contract の names は key を含む項目の name を順に重複なしで持つ"""
        add = lambda n: {"kind": "function", "name": n, "source": "x" * 10}
        reply = {"plan": [item(adds=[add("clamp"), add("mean")]), item(adds=[add("clamp")], unit_keys=[MEAN, CLAMP]),
                          item(adds=[add("other")], unit_keys=[CLAMP]), item(adds=[], unit_keys=[MEAN])]}
        _, fields = planmarks.split(reply, self.repo)
        self.assertEqual(fields[0]["adds"], ["clamp", "mean"])
        self.assertEqual(planmarks.unit_contract(fields, MEAN)["names"], ["clamp", "mean"])
        self.assertEqual(planmarks.unit_contract(fields, CLAMP)["names"], ["clamp", "other"])
        self.assertEqual(planmarks.unit_contract([{"unit_keys": [MEAN]}], MEAN)["names"], [])
        self.assertIsNone(planmarks.unit_contract(fields, "無い単位"))

    def test_names_carry_new_module_of_canonical(self):
        """canonical が新設の .py のパスを名指す adds は、そのパスも宣言した名前に足す（新しいモジュールの import の失敗を TDD の輪が
        宣言の赤に数える。依頼 194c: read_input の canonical が works/.shared/core/nodeio.py（新設…）で、No module named 'nodeio' が
        綴りの誤りに数えられた）。新設でない canonical・.py でないパス・作業ツリーに在るファイル（在るモジュールに新設の関数を
        足す行）・根の外のパスは足さない。重なりは 1 つ"""
        add = lambda n, c: {"kind": "function", "name": n, "canonical": c}
        reply = {"plan": [item(adds=[add("read_input", "works/.shared/core/nodeio.py（新設。前の節の出力を読む口）"),
                                     add("board_out", "works/.shared/core/nodeio.py（新設。盤面の控えから読む口）"),
                                     add("handle", "新設: app/receivers.py（受け手の表）"),
                                     add("mean", "stats.py の既存の mean を直す"),
                                     add("fmt", "既存の textfmt.py から引く（新設しない result.py を読む）"),
                                     add("golden", "works/tests/fixtures/golden.json（新設）"),
                                     add("median", "stats.py（新設。在るモジュールに足す関数）"),
                                     add("up", "../up.py（新設）")])]}
        _, fields = planmarks.split(reply, self.repo)
        self.assertEqual(fields[0]["adds"], ["read_input", "works/.shared/core/nodeio.py", "board_out", "handle",
                                             "app/receivers.py", "mean", "fmt", "golden", "median", "up"])
        self.assertEqual(planmarks.unit_contract(fields, MEAN)["names"], fields[0]["adds"])


class ScopeFieldsCase(PlanFieldsCase):
    """修正案の項目の範囲の欄（allowed_paths・out_of_scope。依頼 218）: 役の型の必須・glob の誤りと丸ごとの許しの拒否・欄を外す口・
    修正案の役と事前審査の役の頭の文"""

    def test_role_schema_requires_scope_fields(self):
        it = accept.role_schema("p2.fix_plan")["properties"]["plan"]["items"]
        for k in ("allowed_paths", "out_of_scope"):
            self.assertIn(k, it["required"])
        self.assertEqual(it["properties"]["allowed_paths"]["minItems"], 1)

    def test_gaps_allowed_paths_must_be_relative_and_narrow(self):
        for g in ("/abs/x.py", "../x.py", "a\\b.py", "**", "*", "**/*",
                  "./x", " stats.py", "stats.py ", " ", "a/../b", "a//b",   # 整えない綴り・前後の空白（差分のパスに当たらない）
                  "C:/x.py", "C:x.py", "~/x"):                              # ドライブ文字・~ は絶対パスとして拒む
            with self.subTest(g):
                got = planmarks.gaps({"plan": [item(allowed_paths=[g])]}, self.repo)
                self.assertTrue(any(x.startswith("plan[0].allowed_paths[0]") for x in got), got)
        self.assertEqual(planmarks.gaps({"plan": [item(allowed_paths=["stats.py", "docs/**/*.md"])]}, self.repo), [])

    def test_glob_without_a_literal_character_is_a_whole_tree_allowance(self):
        """字の無い glob（* と ? と [..] と / と . だけ）は全部に当たり得る丸ごとの許しなので拒む（**/?* は全部の段が * か ** でないが
        全部のファイルに当たる。無人の run は範囲を広げるだけの案の直しを関所なしに通すので、ここで止める）。字の在る glob は通す"""
        for g in ("**/?*", "?*", "?", "*/?", "**/[a-z]*", "[!.]*", "**/*?", "*/**/*", "[]]*",
                  "**/*.*", "*.*", "**/.*"):   # 字が . だけの glob も拡張子を持つ全部・隠しの全部に当たる
            with self.subTest(g):
                self.assertIn("丸ごと", planmarks.glob_problem(g) or "")
                got = planmarks.gaps({"plan": [item(allowed_paths=[g])]}, self.repo)
                self.assertTrue(any(x.startswith("plan[0].allowed_paths[0]") for x in got), got)
        for g in ("*.py", "**/*.md", "src/**", "a?.py", "[ab].py", "docs/*", "**/test_*.py", "x", ".github/**"):
            with self.subTest(g):
                self.assertIsNone(planmarks.glob_problem(g))

    def test_gaps_out_of_scope_rows(self):
        bad = [{"glob": "../x.py", "why": "根の外は触らない（試験の材料）"}]
        got = planmarks.gaps({"plan": [item(out_of_scope=bad)]}, self.repo)
        self.assertTrue(any(x.startswith("plan[0].out_of_scope[0]") for x in got), got)
        self.assertTrue(planmarks.gaps({"plan": [item(out_of_scope=[{"glob": "test_stats.py", "why": "短い"}])]}, self.repo))

    def test_gaps_scope_fields_required(self):
        it = item()
        del it["allowed_paths"]
        self.assertTrue(any(g.startswith("plan[0].allowed_paths") for g in planmarks.gaps({"plan": [it]}, self.repo)))

    def test_split_keeps_scope_fields_off_the_board(self):
        bare, fields = planmarks.split({"plan": [item()]}, self.repo)
        self.assertEqual(set(bare["plan"][0]), {"unit_keys", "approach", "adds", "removes", "shrink_first", "narrows"})
        self.assertEqual((fields[0]["allowed_paths"], fields[0]["out_of_scope"]), (["stats.py"], []))

    def test_head_and_review_ask_name_scope_fields(self):
        for w in ("allowed_paths", "out_of_scope", "識別子", "canonical", "removes"):
            self.assertIn(w, planmarks.HEAD)
        self.assertIn("allowed_paths", planmarks.REVIEW_ASK)

    def test_head_asks_for_moved_and_removed_paths(self):
        self.assertIn("移す・消すファイルの元のパスも allowed_paths に書け", planmarks.HEAD)

    def test_head_asks_tests_id_to_match_existing_layout(self):
        """tests の id と置き場は、名指すファイルの既存のテストの置き方に合わせよと言う（対象の決まりは写さない一般の 1 文）"""
        self.assertIn("クラスの中か一番外か", planmarks.HEAD)

    def test_gaps_out_of_scope_must_not_hit_named_tests(self):
        """out_of_scope の glob が、修正案の tests・rewrite_tests の id のファイルに当たる案は拒む（書けと言うファイルを触るなとも
        言う食い違いを修正の段へ渡さない）。当たらなければ通る"""
        oos = [{"glob": "test_*.py", "why": "既存の試験のファイルは触らない"}]
        got = planmarks.gaps({"plan": [item(out_of_scope=oos)]}, self.repo)
        self.assertTrue(any(x.startswith("plan[0].out_of_scope[0]") and "test_stats.py" in x for x in got), got)
        other = item(tests=[], route="direct", route_why="文書だけの直しで先にテストを書けない", rewrite_tests=[REWRITE])
        got = planmarks.gaps({"plan": [item(), {**other, "out_of_scope": oos}]}, self.repo)
        self.assertTrue(any(x.startswith("plan[1].out_of_scope[0]") for x in got), got)
        self.assertEqual(planmarks.gaps({"plan": [item(out_of_scope=[{"glob": "docs/**", "why": "文書は今回の直しの外"}])]},
                                        self.repo), [])

    def test_glob_match_is_the_protect_matcher(self):
        """範囲の glob の当て方は守りのファイルの当て方と 1 つ（protect.match は planmarks.glob_match を呼ぶ）"""
        import protect
        for path, glob, want in (("stats.py", "*.py", True), ("a/b.py", "*.py", False), ("a/b.py", "**/*.py", True),
                                 ("docs/x/y.md", "docs/**", True), ("test_stats.py", "test_*.py", True)):
            with self.subTest(path=path, glob=glob):
                self.assertEqual(planmarks.glob_match(path, glob), want)
                self.assertEqual(protect.match(path, glob), want)


class ApprovedItemsCase(PlanFieldsCase):
    """approved_items: 今の周の承認済みの修正案の項目と、盤面の控えの欄を同じ番号で合わせた並び"""

    def board(self, plan, fields):
        b = types.SimpleNamespace(dir=self.tmp, round=1,
                                  output_of_round=lambda node, rnd: {"plan": plan} if plan is not None and rnd == 1 else None)
        if fields is not None:
            planmarks.save(self.tmp, 1, fields)
        return b

    def test_join_plan_and_fields_by_number(self):
        _, fields = planmarks.split({"plan": [item()]}, self.repo)
        plan = [{k: v for k, v in item().items() if k not in planmarks.KEYS}]
        got = planmarks.approved_items(self.board(plan, fields))
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["item"], got[0]["approach"], got[0]["allowed_paths"], got[0]["unit_keys"]),
                         (1, "x" * 20, ["stats.py"], [MEAN]))

    def test_none_without_plan_or_fields(self):
        _, fields = planmarks.split({"plan": [item()]}, self.repo)
        self.assertIsNone(planmarks.approved_items(self.board(None, fields)))
        self.tmp = self.tmp / "other"
        self.tmp.mkdir()
        self.assertIsNone(planmarks.approved_items(self.board([item()], None)))

    def test_count_mismatch_is_fields_broken(self):
        _, fields = planmarks.split({"plan": [item()]}, self.repo)
        with self.assertRaises(planmarks.FieldsBroken):
            planmarks.approved_items(self.board([item(), item()], fields))


class TestContractFields(PlanFieldsCase):
    """約束の欄（変えると関所に戻す物）と手段の欄（修正案の役が直してよい物）の表と、欄の比べ contract_diff"""

    def test_keys_cover_item_schema(self):
        it = accept.role_schema("p2.fix_plan")["properties"]["plan"]["items"]["properties"]
        self.assertEqual(set(planmarks.CONTRACT_KEYS) | set(planmarks.MEANS_KEYS), set(it))
        self.assertFalse(set(planmarks.CONTRACT_KEYS) & set(planmarks.MEANS_KEYS))
        self.assertEqual(set(planmarks.CORE_KEYS), PLAN_KEYS)

    def test_means_only_change_is_empty(self):
        old = item()
        new = copy.deepcopy(old)
        new["tests"][0]["red_kind"] = "exception"      # 224b の型
        new["tests"][0]["id"] = "test_stats.py::TestStats::test_mean_of_two_values"   # 225 の型
        new["approach"] = new["approach"] + "（直した）"
        self.assertEqual(planmarks.contract_diff(old, new), [])

    def test_contract_change_is_named(self):
        old = item()
        self.assertEqual(planmarks.contract_diff(old, item(allowed_paths=["stats.py", "lib/**/*.py"])), ["allowed_paths"])  # 195b の型
        self.assertEqual(planmarks.contract_diff(old, item(rewrite_tests=[REWRITE])), ["rewrite_tests"])                    # 194c の型
        beh = copy.deepcopy(old)
        beh["tests"][0]["behavior"] = "3 つの値の平均"
        self.assertEqual(planmarks.contract_diff(old, beh), ["tests.behavior"])

    def test_order_and_absence_do_not_count(self):
        """unit_keys の並べ替え・tests の並べ替え・欄が無いのと空の並びは違いに数えない。違いは CONTRACT_KEYS の順で並ぶ"""
        old = item(unit_keys=[MEAN, CLAMP])
        t2 = dict(old["tests"][0], id="test_stats.py::TestStats::test_mean_of_one", behavior="1 つの値の平均はその値")
        old["tests"].append(t2)
        new = copy.deepcopy(old)
        new["unit_keys"].reverse()
        new["tests"].reverse()
        del new["narrows"]
        self.assertEqual(planmarks.contract_diff(old, new), [])
        both = item(unit_keys=[CLAMP], out_of_scope=[{"glob": "docs/**", "why": "文書は今回の直しの外"}])
        self.assertEqual(planmarks.contract_diff(item(), both), ["unit_keys", "out_of_scope"])


class TestWidened(PlanFieldsCase):
    """範囲を広げるだけの直しか（widened）: 違いが allowed_paths に足した行と out_of_scope から外した行だけの時だけ、足した glob と
    外した glob を返す。ほかの欄（約束の欄も手段の欄も）が 1 つでも違えば・何も広げていなければ None（無人の run で関所を飛ばす決め手）"""

    OOS = [{"glob": "docs/**", "why": "文書は今回の直しの外に置く"}, {"glob": "README.md", "why": "利用者向けの説明は触らない"}]

    def test_added_allowed_paths(self):
        got = planmarks.widened(item(), item(allowed_paths=["stats.py", "README.md", "lib/*.py"]))
        self.assertEqual(got, {"allowed_paths": ["README.md", "lib/*.py"], "out_of_scope": []})

    def test_removed_out_of_scope(self):
        got = planmarks.widened(item(out_of_scope=self.OOS), item(out_of_scope=self.OOS[1:]))
        self.assertEqual(got, {"allowed_paths": [], "out_of_scope": ["docs/**"]})

    def test_both_at_once(self):
        got = planmarks.widened(item(out_of_scope=self.OOS), item(allowed_paths=["stats.py", "docs/a.md"], out_of_scope=[]))
        self.assertEqual(got, {"allowed_paths": ["docs/a.md"], "out_of_scope": ["docs/**", "README.md"]})

    def test_narrowing_or_other_changes_are_none(self):
        old = item(out_of_scope=self.OOS)
        wide = {"allowed_paths": ["stats.py", "README.md"]}
        red = copy.deepcopy(old["tests"])
        red[0]["red_kind"] = "exception"
        tid = copy.deepcopy(old["tests"])
        tid[0]["id"] = "test_stats.py::TestStats::test_mean_of_two_values"
        beh = copy.deepcopy(old["tests"])
        beh[0]["behavior"] = "3 つの値の平均を返す"
        cases = {
            "allowed_paths を外した": {"allowed_paths": []},
            "allowed_paths を差し替えた": {"allowed_paths": ["lib.py"]},
            "out_of_scope を足した": {"out_of_scope": [*self.OOS, {"glob": "lib/**", "why": "lib は今回の直しの外"}]},
            "out_of_scope の why を変えた": {"out_of_scope": [{**self.OOS[0], "why": "文書は別の依頼で直すので外"}, self.OOS[1]]},
            "rewrite_tests を足した": {**wide, "rewrite_tests": [REWRITE]},
            "red_kind も変えた": {**wide, "tests": red},
            "テストの id も変えた": {**wide, "tests": tid},
            "behavior も変えた": {**wide, "tests": beh},
            "approach も変えた": {**wide, "approach": "z" * 20},
            "adds も変えた": {**wide, "adds": [{"kind": "function", "name": "median", "canonical": "stats.py の median"}]},
            "removes も変えた": {**wide, "removes": ["mean"]},
            "narrows も変えた": {**wide, "narrows": [{"what": "空の列", "why": "空の列は例外のまま"}]},
            "unit_keys も変えた": {**wide, "unit_keys": [MEAN, CLAMP]},
            "route も変えた": {**wide, "route": "direct", "route_why": "z" * 20},
            "refactor も変えた": {**wide, "refactor": {"declared": True, "why": "z" * 20}},
            "何も変えない": {},
        }
        for name, over in cases.items():
            with self.subTest(name):
                self.assertIsNone(planmarks.widened(old, {**old, **copy.deepcopy(over)}))

    def test_old_without_scope_is_none(self):
        """範囲の欄の無い承認済みの項目（217 番の形の控え。範囲の縛りが無い）に allowed_paths を書いた直しは狭める物で、広げる物でない"""
        old = item()
        del old["allowed_paths"]
        self.assertIsNone(planmarks.widened(old, item(allowed_paths=["stats.py", "README.md"])))

    def test_order_and_rewrite_limit_do_not_count(self):
        """unit_keys・tests の並べ替え・rewrite_tests の範囲 limit（凍結の控えが足す）は違いに数えない（contract_diff と同じ読み）"""
        old = item(unit_keys=[MEAN, CLAMP], rewrite_tests=[{**REWRITE, "limit": "test_stats.py:12"}])
        new = item(unit_keys=[CLAMP, MEAN], rewrite_tests=[REWRITE], allowed_paths=["stats.py", "README.md"])
        self.assertEqual(planmarks.widened(old, new), {"allowed_paths": ["README.md"], "out_of_scope": []})

    def test_pure(self):
        old, new = item(out_of_scope=self.OOS), item(allowed_paths=["stats.py", "README.md"], out_of_scope=[])
        before = copy.deepcopy((old, new))
        planmarks.widened(old, new)
        self.assertEqual((old, new), before)


class TestAmend(PlanFieldsCase):
    """承認済みの項目の差し替え（amend）: 直した項目の欄の行を split で作り直し、核の欄を控えの amended に置いて凍結し直す"""

    def board(self):
        reply = {"plan": [item(), item(unit_keys=[CLAMP], allowed_paths=["stats.py", "test_stats.py"])]}
        bare, fields = planmarks.split(reply, self.repo)
        planmarks.save(self.tmp, 1, fields)
        plan = bare["plan"]
        def trace(op, **kw):   # 盤面の書き口（DiskBoard.trace）と同じ行の形
            with open(self.tmp / "trace.jsonl", "a", encoding="utf-8") as f:
                f.write(json.dumps({"t": "now", "op": op, **kw}, ensure_ascii=False) + "\n")

        return types.SimpleNamespace(dir=self.tmp, round=1, trace=trace,
                                     output_of_round=lambda node, rnd: {"plan": copy.deepcopy(plan)} if rnd == 1 else None)

    def fixed(self, b, n, **over):
        it = {k: v for k, v in planmarks.approved_items(b)[n - 1].items() if k != "item"}
        return {**copy.deepcopy(it), **over}

    def trace_ops(self):
        rows = [json.loads(x) for x in (self.tmp / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        return [r for r in rows if r.get("op") in (planmarks.SAVED_OP, planmarks.AMEND_OP)]

    def test_amend_swaps_one_item_and_refreezes(self):
        b = self.board()
        before = planmarks.approved_items(b)
        new = self.fixed(b, 2, approach="直した手立て" * 4)
        new["tests"] = [dict(new["tests"][0], red_kind="exception")]
        planmarks.amend(b, {2: new}, self.repo)
        got = planmarks.approved_items(b)
        self.assertEqual(got[0], before[0])
        self.assertEqual((got[1]["approach"], got[1]["tests"][0]["red_kind"]), ("直した手立て" * 4, "exception"))
        self.assertEqual(got[1]["unit_keys"], [CLAMP])
        self.assertIsNotNone(planmarks.frozen(b))
        ops = self.trace_ops()
        self.assertEqual([r["op"] for r in ops], [planmarks.SAVED_OP, planmarks.SAVED_OP, planmarks.AMEND_OP])
        self.assertEqual((ops[2]["round"], ops[2]["items"]), (1, [2]))
        doc = json.loads((self.tmp / planmarks.FIELDS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(set(doc[planmarks.AMENDED_KEY]), {"2"})
        self.assertNotIn("item", doc[planmarks.AMENDED_KEY]["2"])
        self.assertEqual(set(doc[planmarks.AMENDED_KEY]["2"]), PLAN_KEYS)
        self.assertEqual(planmarks.amended(b)[2]["approach"], "直した手立て" * 4)
        doc[planmarks.AMENDED_KEY]["2"]["approach"] = "手で書き換えた"
        (self.tmp / planmarks.FIELDS_FILE).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        for fn in (planmarks.approved_items, planmarks.amended, planmarks.plan_items):
            with self.subTest(fn.__name__), self.assertRaises(planmarks.FieldsBroken):
                fn(b)

    def test_amend_rebuilds_rewrite_limit_and_adds(self):
        b = self.board()
        add = {"kind": "function", "name": "clamp_hi", "source": "x" * 10}
        planmarks.amend(b, {2: self.fixed(b, 2, rewrite_tests=[REWRITE], adds=[add])}, self.repo)
        self.assertEqual(planmarks.rewrites(b), [{"item": 2, "unit_keys": [CLAMP], "id": REWRITE["id"], "new": REWRITE["new"],
                                                  "limit": "test_stats.py:11"}])
        self.assertEqual(planmarks.frozen(b)[1]["adds"], ["clamp_hi"])
        self.assertEqual(planmarks.plan_items(b)[1]["adds"], [add])

    def test_amend_refuses_changed_unit_keys(self):
        b = self.board()
        with self.assertRaisesRegex(ValueError, "unit_keys"):
            planmarks.amend(b, {2: self.fixed(b, 2, unit_keys=[CLAMP + "（別）"])}, self.repo)
        with self.assertRaises(ValueError):
            planmarks.amend(b, {3: self.fixed(b, 2)}, self.repo)
        self.assertEqual([r["op"] for r in self.trace_ops()], [planmarks.SAVED_OP])   # 拒んだ時は控えも trace も変えない

    def test_old_fields_file_has_no_amendments(self):
        """鍵 amended の無い控え（この版の前の盤面）は直しの無い案と読む（落ちない）"""
        b = self.board()
        self.assertNotIn(planmarks.AMENDED_KEY, json.loads((self.tmp / planmarks.FIELDS_FILE).read_text(encoding="utf-8")))
        self.assertEqual(planmarks.amended(b), {})
        self.assertEqual(planmarks.plan_items(b), b.output_of_round(planmarks.NODE, 1)["plan"])


class TestStructure(PlanFieldsCase):
    """修正案の項目の欄 structure（計画 2026-10-09-clean-whole の Task 2.4）: 構造の目が汚れると見た単位を持つ項目は、その行ごとに
    避け方に従う（follows）か外れの訳（deviation）を書く。判定の処方（prescriptions）への答えも同じ欄に並べてよい"""
    OTHER = "stats.py clamp: 上限で lo を返す"
    DIRTY = {MEAN: {"unit_id": MEAN, "verdict": "汚れる", "chosen": "分母の決めを 1 か所に"},
             OTHER: {"unit_id": OTHER, "verdict": "汚れる", "chosen": "境の判定を 1 つに"}}
    WHY = "既存の呼び手が 3 つあり、今回は 1 か所に寄せると範囲が広がりすぎる"

    def test_plan_without_structure_row_is_refused(self):
        got = planmarks.structure_gaps([item()], self.DIRTY)
        self.assertEqual(len(got), 1, got)
        self.assertIn(f"設計の行 {MEAN} に従うか、外れの訳を structure に書け", got[0])
        self.assertTrue(got[0].startswith("plan[0].structure"))

    def test_two_dirty_units_need_a_row_each(self):
        it = item(unit_keys=[MEAN, self.OTHER], structure=[{"row": MEAN, "follows": True}])
        got = planmarks.structure_gaps([it], self.DIRTY)
        self.assertEqual(len(got), 1, got)
        self.assertIn(self.OTHER, got[0])
        it["structure"].append({"row": self.OTHER, "deviation": self.WHY})
        self.assertEqual(planmarks.structure_gaps([it], self.DIRTY), [])

    def test_clean_unit_needs_nothing(self):
        self.assertEqual(planmarks.structure_gaps([item()], {}), [])
        self.assertEqual(planmarks.structure_gaps([item()], {self.OTHER: self.DIRTY[self.OTHER]}), [])

    def test_bad_rows_are_named(self):
        for name, row in (("両方", {"row": MEAN, "follows": True, "deviation": self.WHY}),
                          ("どちらも無い", {"row": MEAN}),
                          ("短い訳", {"row": MEAN, "deviation": "短い"}),
                          ("汚れる行でない", {"row": "別の単位", "follows": True}),
                          ("行と処方の両方", {"row": MEAN, "prescription": MEAN, "follows": True}),
                          ("従わないと書く", {"row": MEAN, "follows": False})):
            with self.subTest(name):
                got = planmarks.structure_gaps([item(structure=[row])], self.DIRTY)
                self.assertTrue(got, name)

    def test_prescription_answers_are_allowed(self):
        it = item(structure=[{"row": MEAN, "follows": True}, {"prescription": MEAN, "deviation": self.WHY}])
        self.assertEqual(planmarks.structure_gaps([it], self.DIRTY), [])
        self.assertEqual(self.gaps(it), [])

    def test_plan_with_deviation_passes_and_is_recorded(self):
        it = item(structure=[{"row": MEAN, "deviation": self.WHY}])
        self.assertEqual(planmarks.structure_gaps([it], self.DIRTY), [])
        self.assertEqual(self.gaps(it), [])
        bare, fields = planmarks.split({"plan": [it]}, self.repo)
        self.assertNotIn("structure", bare["plan"][0])
        self.assertEqual(fields[0]["structure"], [{"row": MEAN, "deviation": self.WHY}])
        self.assertEqual(planmarks.deviations(fields), [{"item": 1, "row": MEAN, "deviation": self.WHY}])


if __name__ == "__main__":
    unittest.main()
