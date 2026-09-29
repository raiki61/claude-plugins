"""修正のブロック（blk-fix）の単位ごとの TDD の輪（MVP。設計 works/docs/specs/2026-09-27-fix-tdd-block-design.md の 2 節 3）の検査。

- YAML の口: 入力 tdd_suite（空でよい）・節の並び（ignored-before → tdd-start → tdd-loop → fix-loop → …）・輪は until_bash の
  印で抜ける（R50）・輪の中の AI の節は 1 つ（TA13）・出口は 1 本目の欄に tdd を足した形
- 実行器が無い run: tdd-start は何も書かずに go: false を返し、輪は飛ばされ、出口の 1 本目の欄は今と同じ（tdd は ran: false）
- 実行器が在る run: 種の git（dev/target-seed の写し）と、unittest を回して JUnit XML を書く小さな実行器（試験の中の SUITE）で、
  振り分け → テスト（赤は写しの red_problems）→ 直す（緑は写しの green_problems）→ 整える（緑のまま・テストが変わらない）を
  役の代わりに作業ツリーを書き換えて回す。拒否の理由は reason_file と次の指示書に届き、上限で諦めた単位は作業ツリーを
  単位の頭に戻して direct へ移る
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-fix"
CORE = ROOT / ".shared" / "core"
TESTS = pathlib.Path(__file__).resolve().parent
SEED = ROOT / "dev" / "target-seed"
sys.dont_write_bytecode = True
sys.path.insert(0, str(BLK / "lib"))
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

from gitkit import committed_copy, git  # noqa: E402
import tddloop  # noqa: E402

DEADLINE = 1728000000
MEAN = "stats.py mean: 分母が len(xs) - 1 になっている"
CLAMP = "stats.py clamp: 上限を超えた値に lo を返す"
OPEN = json.dumps([MEAN, CLAMP], ensure_ascii=False)
V1 = {"ok", "files", "changes_file", "removed"}

# 対象リポジトリの根で test_*.py を unittest で回し、JUnit XML を第 1 引数に書く実行器（本線の tdd_suite の約束と同じ形）
SUITE = '''
import sys, unittest, xml.etree.ElementTree as ET
sys.dont_write_bytecode = True
sys.path.insert(0, ".")
out = sys.argv[1]
rows = []
class R(unittest.TestResult):
    def addSuccess(self, t): rows.append((t, None))
    def addFailure(self, t, e): rows.append((t, "failure"))
    def addError(self, t, e): rows.append((t, "error"))
    def addSkip(self, t, r): rows.append((t, "skipped"))
unittest.defaultTestLoader.discover(".", pattern="test_*.py", top_level_dir=".").run(R())
root = ET.Element("testsuite")
for t, kind in rows:
    cls, name = t.id().rsplit(".", 1)
    tc = ET.SubElement(root, "testcase", classname=cls, name=name)
    if kind:
        ET.SubElement(tc, kind)
ET.ElementTree(root).write(out)
sys.exit(0 if all(k in (None, "skipped") for _, k in rows) else 1)
'''

NEW_TEST = '''
    def test_mean_of_two(self):
        self.assertEqual(mean([2, 4]), 3)
'''
PASSING_TEST = '''
    def test_clamp_below_range(self):
        self.assertEqual(clamp(-5, 0, 10), 0)
'''


def block():
    return yaml.safe_load((BLK / "blk-fix.yaml").read_text(encoding="utf-8"))


def find_node(nodes, nid):
    for n in nodes:
        if n.get("id") == nid:
            return n
        if "loop_group" in n:
            found = find_node(n["loop_group"]["nodes"], nid)
            if found is not None:
                return found
    return None


def run_script(name, repo, env):
    full = {"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1", **env}
    r = subprocess.run([sys.executable, str(BLK / "scripts" / f"{name}.py")], cwd=str(repo), env=full,
                       capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
    return r.returncode, r.stdout, r.stderr


class TestYaml(unittest.TestCase):
    def test_input_tdd_suite_is_optional(self):
        inputs = block()["inputs"]
        self.assertEqual(inputs["tdd_suite"].get("default"), "")
        self.assertNotIn("required", inputs["tdd_suite"])

    def test_node_order(self):
        nodes = block()["nodes"]
        self.assertEqual([n["id"] for n in nodes],
                         ["ignored-before", "tdd-start", "tdd-loop", "fix-loop", "conflict-check", "rule-loop", "fix-ruled-loop",
                          "clean", "assert-changed", "fix-reads", "collect"])
        start, loop, fix_loop = nodes[1:4]
        self.assertEqual(start["script"], "tdd_start")
        self.assertEqual(start["depends_on"], ["ignored-before"])
        self.assertEqual(start["timeout"], DEADLINE)
        self.assertEqual(start["with"], {"tdd_suite": "$INPUTS.tdd_suite", "open_units": "$INPUTS.open_units"})
        self.assertEqual(loop["depends_on"], ["tdd-start"])
        self.assertEqual(loop["when"], "$tdd-start.output.go == true")
        g = loop["loop_group"]
        self.assertEqual(g["max_iterations"], tddloop.MAX_ITERATIONS)
        from test_yaml_rules import LOOP_MAX
        self.assertEqual(LOOP_MAX, {("blk-fix", "blk-fix.yaml", "tdd-loop"): tddloop.MAX_ITERATIONS})
        self.assertIs(g["fresh_context"], False, "テスト→直す→整えるを同じ会話で（C17）")
        self.assertEqual(g["until_bash"], "test $tdd-step.output.done = true", "印で抜ける（R50）")
        self.assertEqual([n["id"] for n in g["nodes"]], ["tdd-prep", "tdd", "tdd-step"])
        prep, role, step = g["nodes"]
        self.assertEqual(prep["with"], {"state_file": "$tdd-start.output.state_file", "judgment_file": "$INPUTS.judgment_file",
                                        "plan_file": "$INPUTS.plan_file", "policy_path": "$INPUTS.policy_path",
                                        "notes_file": "$INPUTS.notes_file"})
        self.assertEqual(role["depends_on"], ["tdd-prep"])
        self.assertEqual(step["depends_on"], ["tdd"])
        self.assertEqual(step["with"], {"reply": {"from": "$tdd.output"}, "state_file": "$tdd-start.output.state_file"})
        for n in (prep, step):
            self.assertEqual(n["timeout"], DEADLINE)
        self.assertEqual(fix_loop["depends_on"], ["tdd-start", "tdd-loop"])
        self.assertEqual(fix_loop["trigger_rule"], "none_failed_min_one_success", "輪が飛ばされても直す")

    def test_tdd_role_node(self):
        role = find_node(block()["nodes"], "tdd")
        self.assertNotIn("command", role)
        self.assertIn("`$tdd-prep.output.prompt_file` を Read で", role["prompt"])
        self.assertEqual(role["settingSources"], ["user"])
        self.assertEqual(role["allowed_tools"], ["Read", "Grep", "Glob", "Edit", "Write", "Bash", "WebSearch", "WebFetch"])
        self.assertEqual(role["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})
        self.assertEqual(role["idle_timeout"], DEADLINE)
        of = role["output_format"]
        self.assertEqual(of["description"], "works-node: tdd", "包みが会話を節の名で分け、続きの起動で指示書の形を選ぶ")
        self.assertIs(of["additionalProperties"], False)
        self.assertEqual(of["required"], ["phase"])
        self.assertEqual(of["properties"]["phase"]["enum"], [*tddloop.PHASES, "conflict"], "食い違いの申し出はどの段でも")

    def test_accept_and_collect_get_tdd(self):
        nodes = block()["nodes"]
        accept = find_node(nodes, "fix-accept")
        self.assertEqual(accept["with"]["tdd_state"], "$tdd-start.output.state_file")
        collect = find_node(nodes, "collect")
        self.assertEqual(collect["with"]["tdd"], {"from": "$tdd-start.output"})
        out = collect["output_format"]
        self.assertLessEqual(V1, set(out["required"]), "1 本目の欄を全部残す")
        self.assertEqual(set(out["properties"]), V1 | {"tdd", "fix_file", "not_done", "coverage", "reads_file", "reason"})   # 盤面の欄（〔線A計〕T17）
        self.assertEqual(out["properties"]["tdd"]["type"], "object")

    def test_prompts(self):
        """役の指示は 1 行（tdd-prep が組んだ指示書を読む）。理由は指示書のファイルで渡す（R44）。輪の後の修正役は輪の結果を読む"""
        role = find_node(block()["nodes"], "tdd")
        self.assertNotIn("$LOOP_PREV", role["prompt"])
        fix_prep = find_node(block()["nodes"], "fix-prep")
        self.assertEqual(fix_prep["with"]["summary_file"], "$tdd-start.output.summary_file")

    def test_script_inputs(self):
        import ast
        import re
        want = {"tdd_start": ("INPUTS_TDD_SUITE", "INPUTS_OPEN_UNITS"), "tdd_prep": ("INPUTS_STATE_FILE", "INPUTS_JUDGMENT_FILE", "INPUTS_PLAN_FILE",
                                                                                       "INPUTS_POLICY_PATH", "INPUTS_NOTES_FILE"),
                "tdd_step": ("INPUTS_REPLY", "INPUTS_STATE_FILE"),
                "accept": ("INPUTS_REPLY", "INPUTS_BASE_REV", "INPUTS_TDD_STATE", "INPUTS_ITERATION", "INPUTS_PASS"),
                "collect": ("INPUTS_ACCEPTED", "INPUTS_CHANGED", "INPUTS_CLEANED", "INPUTS_TDD", "INPUTS_RULED")}
        for name, inputs in want.items():
            with self.subTest(name):
                src = (BLK / "scripts" / f"{name}.py").read_text(encoding="utf-8")
                consts = [ast.literal_eval(n.value) for n in ast.parse(src).body if isinstance(n, ast.Assign)
                          and [getattr(t, "id", None) for t in n.targets] == ["INPUTS"]]
                self.assertEqual(consts, [inputs])
                self.assertLessEqual(set(re.findall(r"INPUTS_[A-Z_]+", src)), set(inputs))

    def test_fixtures_carry_tdd_exit(self):
        """pass は実行器の無い run（輪は飛ぶ・tdd は ran: false）、tdd は輪が 1 周で done を立てる run（tdd-step まで届く）"""
        fx = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in (BLK / "fixtures").glob("*.stubs.yaml")}
        self.assertEqual(fx["pass.stubs.yaml"]["collect"]["tdd"]["ran"], False)
        self.assertNotIn("tdd_suite", fx["pass.stubs.yaml"]["fixture"]["inputs"])
        t = fx["tdd.stubs.yaml"]
        self.assertIs(t["tdd-start"]["go"], True)
        self.assertIs(t["tdd-step"]["done"], True)
        self.assertEqual(t["fixture"]["reached"], ["tdd-step", "collect"])
        self.assertEqual(t["collect"]["tdd"]["ran"], True)
        self.assertEqual(set(t["collect"]["tdd"]["units"][0]), set(tddloop.FIELDS))


class TestNoSuite(unittest.TestCase):
    """実行器が無い run は今と同じ: tdd-start は何も書かず go: false。出口の tdd は ran: false"""

    def test_start_without_suite_writes_nothing(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            repo = tmp / "repo"
            committed_copy(repo, SEED)
            art = tmp / "art"
            code, out, err = run_script("tdd_start", repo, {"INPUTS_TDD_SUITE": "", "INPUTS_OPEN_UNITS": OPEN,
                                                            "ARTIFACTS_DIR": str(art)})
            self.assertEqual(code, 0, err)
            got = json.loads(out)
            self.assertEqual(got, {"go": False, "reason": tddloop.NO_SUITE, "suite": "", "state_file": "",
                                   "summary_file": ""})
            import test_blk_fix
            self.assertEqual(got, test_blk_fix.NO_SUITE_START, "test_blk_fix の出口の試験が使う値と同じ")
            self.assertFalse(art.exists(), "盤面に何も書かない")
            self.assertEqual(git(repo, "status", "--porcelain"), "")

    def test_exit_fields_without_suite(self):
        start = {"go": False, "reason": tddloop.NO_SUITE, "suite": "", "state_file": "", "summary_file": ""}
        self.assertEqual(tddloop.exit_fields(start), {"ran": False, "suite": "", "reason": tddloop.NO_SUITE, "units": []})

    def test_missing_suite_file_falls_back_to_direct(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = pathlib.Path(tmp)
            repo = tmp / "repo"
            committed_copy(repo, SEED)
            got = tddloop.start(tmp / "board", repo, "no/such/suite.sh", OPEN)
            self.assertIs(got["go"], False)
            self.assertIn("no/such/suite.sh", got["reason"])
            self.assertEqual(got["state_file"], "")

    def test_freeze_check_skips_without_state(self):
        self.assertEqual(tddloop.frozen_problems("", pathlib.Path(".")), [])


class LoopCase(unittest.TestCase):
    """種の git と小さな実行器で輪を回す（役の代わりに作業ツリーを書き換える）"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = pathlib.Path(self._tmp.name)
        self.repo = tmp / "repo"
        committed_copy(self.repo, SEED)
        self.suite = tmp / "suite.py"
        self.suite.write_text(SUITE, encoding="utf-8")
        self.board = tmp / "art" / "board"
        self.start = tddloop.start(self.board, self.repo, str(self.suite), OPEN)
        self.assertTrue(self.start["go"], self.start)
        self.state = self.start["state_file"]

    def st(self):
        return json.loads(pathlib.Path(self.state).read_text(encoding="utf-8"))

    def step(self, reply):
        return tddloop.step(self.state, reply, self.repo)

    def edit(self, name, old, new):
        p = self.repo / name
        text = p.read_text(encoding="utf-8")
        self.assertIn(old, text)
        p.write_text(text.replace(old, new), encoding="utf-8")

    def add_test(self, body):
        self.edit("test_stats.py", "\n\nif __name__", body + "\n\nif __name__")

    def route(self, mean="tdd", clamp="direct"):
        rows = [{"unit_key": MEAN, "route": mean}, {"unit_key": CLAMP, "route": clamp}]
        for r in rows:
            if r["route"] == "direct":
                r["why"] = "文書の直しと同じで、先にテストを書けない単位"
        got = self.step({"phase": "route", "units": rows})
        self.assertTrue(got["ok"], got)
        return got

    def red(self):
        self.add_test(NEW_TEST)
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"],
                         "tests": ["test_stats.py::TestStats::test_mean_of_two"]})
        self.assertTrue(got["ok"], got)
        return got

    def fix_mean(self):
        self.edit("stats.py", "return sum(xs) / (len(xs) - 1)", "return sum(xs) / len(xs)")
        got = self.step({"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母を len(xs) にした"})
        self.assertTrue(got["ok"], got)
        return got


class TestStart(LoopCase):
    def test_baseline_and_first_prompt(self):
        st = self.st()
        self.assertEqual(st["phase"], "route")
        self.assertEqual(st["baseline"]["test_stats.TestStats::test_mean_of_three"], "failure")
        self.assertEqual(st["baseline"]["test_stats.TestStats::test_clamp_within_range"], "passed")
        self.assertNotEqual(st["baseline_exit"], 0)
        prompt = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        for w in ("route", MEAN, CLAMP, str(self.suite)):
            self.assertIn(w, prompt)
        self.assertEqual(git(self.repo, "status", "--porcelain"), "", "元の結末を取っても作業ツリーは変わらない")

    def test_prompt_is_composed_from_the_shared_rules(self):
        """tdd-prep の指示書: 修正の決まりの正本の核・TDD の読み替え・今の段の約束（今の段だけ）・今の段の指示。next.md は full の
        写しで、隣に full・delta・控え。2 回目の delta は変わった物と決まりの sha256 の 1 行だけ（正本の核を載せない）"""
        import fixrules
        core = fixrules.sections(fixrules.SHARED)["core-fix"]
        out = tddloop.prep(self.state, {"judgment_file": "/b/j.json"}, self.repo)
        prompt = pathlib.Path(out["prompt_file"])
        full = prompt.read_text(encoding="utf-8")
        for s in (core, fixrules.sections(fixrules.SHARED)["core-keep"], "## この輪での読み替え", "- **route**:",
                  "## この段ですること", "`/b/j.json`"):
            self.assertIn(s, full)
        self.assertNotIn("- **test**:", full, "今の段の約束だけ")
        self.assertEqual(fixrules.beside(prompt, fixrules.FULL).read_text(encoding="utf-8"), full)
        self.assertEqual(fixrules.beside(prompt, fixrules.DELTA).read_text(encoding="utf-8"), full, "1 回目の delta は full")
        first = json.loads(fixrules.beside(prompt, fixrules.VARIANTS).read_text(encoding="utf-8"))
        self.route()
        tddloop.prep(self.state, {"judgment_file": "/b/j.json"}, self.repo)
        full2 = prompt.read_text(encoding="utf-8")
        delta2 = fixrules.beside(prompt, fixrules.DELTA).read_text(encoding="utf-8")
        self.assertIn(core, full2, "既定（prompt_file）は full")
        self.assertNotIn(core, delta2)
        self.assertIn(first["rules_sha"], delta2)
        for s in ("- **test**:", "## この段ですること", "段 test"):
            self.assertIn(s, delta2)
        side = json.loads(fixrules.beside(prompt, fixrules.VARIANTS).read_text(encoding="utf-8"))
        self.assertEqual((side["iteration"], side["delta_is_full"]), (2, False))

    def test_second_start_gets_its_own_state(self):
        again = tddloop.start(self.board, self.repo, str(self.suite), OPEN)
        self.assertNotEqual(again["state_file"], self.state)


class TestRoute(LoopCase):
    def test_rejects_bad_routing_with_reason_in_next_prompt(self):
        bad = {"phase": "route", "units": [{"unit_key": MEAN, "route": "direct", "why": "短い"},
                                           {"unit_key": "作り話", "route": "tdd"}]}
        got = self.step(bad)
        self.assertEqual((got["ok"], got["done"]), (False, False))
        for w in (CLAMP, "作り話", "10 字"):
            self.assertIn(w, got["reason"])
        prompt = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("作り話", prompt, "理由は次の指示書に届く")

    def test_route_gives_up_after_retry_max_to_all_direct(self):
        for _ in range(tddloop.retry_max()):
            got = self.step({"phase": "route", "units": []})
        self.assertEqual((got["ok"], got["done"]), (False, True))
        ex = tddloop.exit_fields(self.start)
        self.assertEqual([(u["unit_key"], u["route"]) for u in ex["units"]], [(MEAN, "direct"), (CLAMP, "direct")])
        self.assertTrue(all(len(u["why"]) >= 10 for u in ex["units"]))

    def test_all_direct_ends_loop(self):
        got = self.route(mean="direct", clamp="direct")
        self.assertTrue(got["done"])


class TestUnitLoop(LoopCase):
    def test_happy_path(self):
        self.route()
        self.assertEqual(self.st()["phase"], "test")
        self.red()
        self.assertEqual(self.st()["phase"], "fix")
        self.fix_mean()
        self.assertEqual(self.st()["phase"], "refactor")
        got = self.step({"phase": "refactor", "unit_key": MEAN, "what": "整える物は無い"})
        self.assertEqual((got["ok"], got["done"]), (True, True))
        ex = tddloop.exit_fields(self.start)
        self.assertTrue(ex["ran"])
        rows = {u["unit_key"]: u for u in ex["units"]}
        m = rows[MEAN]
        self.assertEqual((m["route"], m["red"], m["green"], m["refactor"], m["gave_up"]), ("tdd", "ok", "ok", "none", ""))
        self.assertEqual(m["tests"], ["test_stats.py::TestStats::test_mean_of_two"])
        self.assertEqual(m["test_files"], ["test_stats.py"])
        self.assertEqual(rows[CLAMP]["route"], "direct")
        self.assertIn("先にテストを書けない", rows[CLAMP]["why"])
        summary = pathlib.Path(self.start["summary_file"]).read_text(encoding="utf-8")
        for w in (MEAN, CLAMP, "test_stats.py"):
            self.assertIn(w, summary)
        self.assertEqual(tddloop.frozen_problems(self.state, self.repo), [])
        self.edit("test_stats.py", "mean([2, 4]), 3", "mean([2, 4]), 3.0")
        self.assertTrue(tddloop.frozen_problems(self.state, self.repo), "輪の後の修正役がテストを変えたら拒む")

    def test_refactor_rechecked(self):
        self.route()
        self.red()
        self.fix_mean()
        self.edit("stats.py", "return sum(xs) / len(xs)", "total = sum(xs)\n    return total / len(xs)")
        got = self.step({"phase": "refactor", "unit_key": MEAN, "what": "式を 2 行にした"})
        self.assertTrue(got["done"], got)
        self.assertEqual(tddloop.exit_fields(self.start)["units"][0]["refactor"], "ok")

    def test_red_rejects_already_passing_test(self):
        self.route()
        self.add_test(PASSING_TEST)
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"],
                         "tests": ["test_stats.py::TestStats::test_clamp_below_range"]})
        self.assertFalse(got["ok"])
        self.assertIn("もう通る", got["reason"])
        self.assertEqual(self.st()["phase"], "test")

    def test_red_rejects_touching_outside_test_files(self):
        self.route()
        self.add_test(NEW_TEST)
        self.edit("stats.py", "len(xs) - 1", "len(xs)")
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"],
                         "tests": ["test_stats.py::TestStats::test_mean_of_two"]})
        self.assertFalse(got["ok"])
        self.assertIn("stats.py", got["reason"])
        self.assertIn("外", got["reason"])

    def test_red_rejects_wrong_unit(self):
        self.route()
        got = self.step({"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": ["x"]})
        self.assertFalse(got["ok"])
        self.assertIn(MEAN, got["reason"])

    def test_fix_rejects_frozen_test_change(self):
        self.route()
        self.red()
        self.edit("test_stats.py", "mean([2, 4]), 3", "mean([2, 4]), 6")
        got = self.step({"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "テストを直した"})
        self.assertFalse(got["ok"])
        self.assertIn("test_stats.py", got["reason"])

    def test_green_gives_up_and_restores_unit_head(self):
        self.route()
        before = (self.repo / "test_stats.py").read_text(encoding="utf-8")
        self.red()
        (self.repo / "helper.py").write_text("X = 1\n", encoding="utf-8")   # 直す段が足した新しいファイル
        for i in range(tddloop.retry_max()):
            got = self.step({"phase": "fix", "unit_key": MEAN, "files": ["helper.py"], "what": "直せていない"})
            self.assertFalse(got["ok"])
        self.assertTrue(got["done"], "tdd の単位が 1 つなので輪は済む")
        self.assertEqual((self.repo / "test_stats.py").read_text(encoding="utf-8"), before, "書いたテストを外す")
        self.assertFalse((self.repo / "helper.py").exists(), "単位の頭に戻す")
        u = tddloop.exit_fields(self.start)["units"][0]
        self.assertEqual((u["route"], u["gave_up"]), ("direct", "green"))
        self.assertTrue(u["problems"])
        self.assertIn("緑", u["why"])

    def test_refactor_gives_up_back_to_green_tree(self):
        self.route()
        self.red()
        self.fix_mean()
        green = (self.repo / "stats.py").read_text(encoding="utf-8")
        self.edit("stats.py", "return x\n", "return lo\n")   # 整えで壊す
        for _ in range(tddloop.retry_max()):
            got = self.step({"phase": "refactor", "unit_key": MEAN, "what": "壊した"})
            self.assertFalse(got["ok"])
        self.assertTrue(got["done"])
        self.assertEqual((self.repo / "stats.py").read_text(encoding="utf-8"), green)
        u = tddloop.exit_fields(self.start)["units"][0]
        self.assertEqual((u["route"], u["green"], u["refactor"]), ("tdd", "ok", "reverted"))

    def test_writer_can_hand_unit_to_direct(self):
        self.route()
        self.add_test(NEW_TEST)
        got = self.step({"phase": "test", "unit_key": MEAN, "direct_why": "既存の名前だけでは再現できないと分かった"})
        self.assertTrue(got["done"])
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        u = tddloop.exit_fields(self.start)["units"][0]
        self.assertEqual((u["route"], u["gave_up"]), ("direct", "writer"))

    def test_runner_failure_ends_loop_all_direct(self):
        self.route(clamp="tdd")
        self.add_test(NEW_TEST)
        self.suite.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")   # JUnit を書かない
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"],
                         "tests": ["test_stats.py::TestStats::test_mean_of_two"]})
        self.assertTrue(got["done"])
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        ex = tddloop.exit_fields(self.start)
        self.assertIn("JUnit", ex["reason"])
        self.assertEqual([(u["route"], u["gave_up"]) for u in ex["units"]], [("direct", "runner"), ("direct", "runner")])

    def test_budget_ends_loop_before_max_iterations(self):
        self.route()
        st = self.st()
        st["iterations"] = tddloop.MAX_ITERATIONS - 1
        pathlib.Path(self.state).write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": [], "tests": []})
        self.assertTrue(got["done"], "max_iterations に届く周で印を立てる（R50）")
        self.assertEqual(tddloop.exit_fields(self.start)["units"][0]["gave_up"], "budget")

    def test_step_script_writes_reason_file(self):
        code, out, err = run_script("tdd_step", self.repo, {
            "INPUTS_REPLY": json.dumps({"phase": "route", "units": []}), "INPUTS_STATE_FILE": self.state,
            "ARTIFACTS_DIR": str(self.board.parent)})
        self.assertEqual(code, 0, err)
        got = json.loads(out)
        self.assertEqual((got["ok"], got["done"]), (False, False))
        self.assertEqual(pathlib.Path(got["reason_file"]).read_text(encoding="utf-8"), got["reason"])
        env = {"INPUTS_STATE_FILE": self.state, "INPUTS_JUDGMENT_FILE": "/b/j.json", "INPUTS_PLAN_FILE": "",
               "INPUTS_POLICY_PATH": "", "INPUTS_NOTES_FILE": ""}
        code, out, err = run_script("tdd_prep", self.repo, env)
        self.assertEqual(code, 0, err)
        prompt = pathlib.Path(json.loads(out)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(got["reason"].split("\n")[0], prompt, "拒んだ理由は次の指示書に届く")
        self.assertIn("`/b/j.json`", prompt)
        code, out, err = run_script("tdd_prep", self.repo, {k: v for k, v in env.items() if k != "INPUTS_NOTES_FILE"})
        self.assertEqual((code, out), (2, ""))
        self.assertIn("INPUTS_NOTES_FILE", err)


class TestRunSuiteSlot(unittest.TestCase):
    def test_runner_goes_through_machine_slot_with_nice(self):
        # ADR 0071 の 3 の 1: 手元の試験（TDD の輪と受け付け）は nice -n 19 と機械の枠（slotwrap.sh）を通す
        from unittest import mock
        seen = []

        def fake_run(argv, **kw):
            seen.append(list(argv))
            return 0

        with tempfile.TemporaryDirectory() as td, mock.patch.object(tddloop.tree_run, "run", fake_run):
            work = pathlib.Path(td)
            exe = work / "suite.sh"
            exe.write_text("#!/bin/sh\n", encoding="utf-8")
            exe.chmod(0o755)
            tddloop.run_suite(str(exe), work, work, "slot")
        self.assertEqual(len(seen), 1, seen)
        argv = seen[0]
        self.assertEqual(argv[:2], ["bash", str(tddloop.tree_run.SLOTWRAP)], f"実行器が機械の枠を通らない: {argv}")
        self.assertEqual(argv[2:5], ["nice", "-n", "19"], f"実行器が nice -n 19 で起こされない: {argv}")
        self.assertEqual(argv[5], str(exe), argv)


if __name__ == "__main__":
    unittest.main()
