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
import planbrief  # noqa: E402
import tddloop  # noqa: E402
from unittest import mock  # noqa: E402

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

# SUITE の写しで、pytest の JUnit に合わせる実行器: 断言の失敗も本体の例外も failure と書き、message に「<型>: <文>」を付ける
# （pytest は本体の例外を failure と書く。赤の種類 tddloop.red_kind はこの message を読む）
PYTEST_LIKE = '''
import sys, unittest, xml.etree.ElementTree as ET
sys.dont_write_bytecode = True
sys.path.insert(0, ".")
out = sys.argv[1]
rows = []
class R(unittest.TestResult):
    def addSuccess(self, t): rows.append((t, None, ""))
    def addFailure(self, t, e): rows.append((t, "failure", f"{e[0].__name__}: {e[1]}"))
    def addError(self, t, e): rows.append((t, "failure", f"{e[0].__name__}: {e[1]}"))
    def addSkip(self, t, r): rows.append((t, "skipped", ""))
unittest.defaultTestLoader.discover(".", pattern="test_*.py", top_level_dir=".").run(R())
root = ET.Element("testsuite")
for t, kind, msg in rows:
    cls, name = t.id().rsplit(".", 1)
    tc = ET.SubElement(root, "testcase", classname=cls, name=name)
    if kind:
        ET.SubElement(tc, kind, message=msg)
ET.ElementTree(root).write(out)
sys.exit(0 if all(k in (None, "skipped") for _, k, _ in rows) else 1)
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

    def test_owed_units_are_conflict_fix_duty_not_the_is_open_list(self):
        """TDD が振り分ける義務は受け付けと同じ conflict.fix_duty の owed。渡された open_units（is_open）に無くても、関所で答えて
        直す義務に戻った単位は載り、外れた単位は載らない"""
        from unittest import mock
        back = "stats.py returned: 関所で答えて直す義務に戻った単位"
        with mock.patch.object(tddloop.entry, "open_board", return_value=object()), \
                mock.patch.object(tddloop.conflict, "fix_duty", return_value=({MEAN, back}, {CLAMP: "答え待ちの問い q1"})):
            got = tddloop.start(self.board, self.repo, str(self.suite), OPEN)
        self.assertTrue(got["go"], got)
        st = json.loads(pathlib.Path(got["state_file"]).read_text(encoding="utf-8"))
        self.assertEqual(sorted(tddloop._owed(st)), sorted([MEAN, back]))

    def test_second_start_gets_its_own_state(self):
        again = tddloop.start(self.board, self.repo, str(self.suite), OPEN)
        self.assertNotEqual(again["state_file"], self.state)

    def test_tdd_prep_puts_brief_of_current_unit(self):
        """振り分けの段は直す義務の単位の全部の brief、ほかの段は今の単位の brief だけを頭で名指す"""
        rows = [{"item": 1, "unit_keys": [MEAN], "file": "/b/r1/brief-1.md", "sha256": "a" * 64},
                {"item": 2, "unit_keys": [CLAMP], "file": "/b/r1/brief-2.md", "sha256": "b" * 64}]
        with mock.patch.object(tddloop.planbrief, "cut_at", return_value=rows) as cut:
            route = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
            self.assertEqual(pathlib.Path(cut.call_args[0][0]).resolve(), self.board.resolve(), "盤面の置き場で切る")
            self.assertIn("brief-1.md", route)
            self.assertIn("brief-2.md", route)
            self.route()   # MEAN は tdd、CLAMP は direct
            test = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
            self.assertIn("brief-1.md", test)
            self.assertNotIn("brief-2.md", test, "今の単位は MEAN だけ")

    def test_tdd_prep_without_board_has_no_brief(self):
        """盤面の無い置き場（修正案の無い run と同じ）では brief の節を置かない"""
        self.assertNotIn(planbrief.HEAD, pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8"))

    def test_tdd_prep_broken_ledger_stops_with_reason(self):
        """brief の控えが壊れていれば、brief の無い指示書として続けず、控えを名指す理由の Broken で止める（traceback にしない）"""
        broken = planbrief.LedgerBroken(f"brief の控え /b/r1/{planbrief.LEDGER} を読めない: 壊れた")
        with mock.patch.object(tddloop.planbrief, "cut_at", side_effect=broken):
            with self.assertRaisesRegex(tddloop.Broken, planbrief.LEDGER):
                tddloop.prep(self.state)


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


MEAN_ID = "test_stats.py::TestStats::test_mean_of_two"
WRONG_KIND_TEST = "\n    def test_mean_of_two(self):\n        import stats\n        self.assertEqual(stats.mean2([2, 4]), 3)\n"


class ContractCase(LoopCase):
    """約束を持つ run。tdd-start を plan_contract の差し替えで起こし直す（実行器は pytest に似せた PYTEST_LIKE）"""
    CONTRACT = {MEAN: {"items": [1], "route": "tdd", "rewrites": [], "refactor": False,
                       "tests": [{"id": MEAN_ID, "red_kind": "assertion"}]}}

    def setUp(self):
        super().setUp()
        self.suite.write_text(PYTEST_LIKE, encoding="utf-8")
        with mock.patch.object(tddloop, "plan_contract", return_value=self.CONTRACT) as pc:
            self.start = tddloop.start(self.board, self.repo, str(self.suite), OPEN)
        self.assertTrue(self.start["go"], self.start)
        self.state = self.start["state_file"]
        self.assertEqual(sorted(pc.call_args[0][1]), sorted([MEAN, CLAMP]))

    def wrong_kind(self):
        """今のコードに無い名前を呼んで AttributeError で落ちるテスト（案は assertion）を書いて出す"""
        return self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"], "tests": [MEAN_ID]})


class TestPlanContract(ContractCase):
    def test_contract_lands_in_state(self):
        self.assertEqual(self.st()["contract"], self.CONTRACT)

    def test_plan_tdd_unit_cannot_be_routed_direct(self):
        got = self.step({"phase": "route", "units": [{"unit_key": MEAN, "route": "direct", "why": "文書だけの直しで書けない"},
                                                     {"unit_key": CLAMP, "route": "direct", "why": "文書だけの直しで書けない"}]})
        self.assertFalse(got["ok"])
        self.assertIn(MEAN, got["reason"])
        self.assertIn("conflict", got["reason"])
        self.assertNotIn(CLAMP, got["reason"].split("\n")[0])   # 約束の無い単位は今どおり direct に振れる

    def test_plan_tdd_unit_cannot_hand_off_by_direct_why(self):
        self.route()
        got = self.step({"phase": "test", "unit_key": MEAN, "direct_why": "既存の名前だけでは再現できないと分かった"})
        self.assertEqual((got["ok"], got["done"]), (False, False))
        self.assertIn("conflict", got["reason"])
        self.assertEqual((self.st()["phase"], self.st()["units"][MEAN]["route"]), ("test", "tdd"))

    def test_test_phase_must_name_plan_tests(self):
        self.route()
        self.add_test(NEW_TEST.replace("test_mean_of_two", "test_other_name"))
        runs = self.st()["runs"]
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"],
                         "tests": ["test_stats.py::TestStats::test_other_name"]})
        self.assertFalse(got["ok"])
        self.assertIn(MEAN_ID, got["reason"])
        self.assertEqual(self.st()["runs"], runs, "実行器を走らせる前に拒む")

    def test_plan_test_named_with_dot_path_counts(self):
        """名指しのパスの部分は posixpath.normpath で整えて比べる"""
        self.route()
        self.add_test(NEW_TEST)
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"],
                         "tests": ["./test_stats.py::TestStats::test_mean_of_two"]})
        self.assertTrue(got["ok"], got)

    def test_red_kind_matches_and_is_recorded(self):
        self.route()
        self.red()
        self.assertEqual(self.st()["units"][MEAN]["red_kinds"], {MEAN_ID: "assertion"})

    def test_red_rejects_wrong_kind(self):
        self.route()
        self.add_test(WRONG_KIND_TEST)
        got = self.wrong_kind()
        self.assertFalse(got["ok"])
        for w in ("AttributeError", "assertion", "conflict"):
            self.assertIn(w, got["reason"])
        self.assertEqual(self.st()["phase"], "test")

    def test_crash_red_with_assertion_plan_passes_and_is_recorded(self):
        """今のコードが例外で落ちる種類のバグ（ZeroDivisionError）は、案が assertion でも拒まず種類を記録する"""
        self.route()
        self.add_test("\n    def test_mean_of_two(self):\n        self.assertEqual(mean([5]), 5)\n")
        got = self.wrong_kind()
        self.assertTrue(got["ok"], got)
        self.assertEqual(self.st()["units"][MEAN]["red_kinds"], {MEAN_ID: "ZeroDivisionError"})

    def test_name_error_red_with_assertion_plan_rejected(self):
        self.route()
        self.add_test("\n    def test_mean_of_two(self):\n        self.assertEqual(mean_of([2, 4]), 3)\n")
        got = self.wrong_kind()
        self.assertFalse(got["ok"])
        for w in ("NameError", "assertion", "conflict"):
            self.assertIn(w, got["reason"])

    def test_wrong_kind_three_times_gives_up_to_direct(self):
        self.route()
        head = (self.repo / "test_stats.py").read_text(encoding="utf-8")
        self.add_test(WRONG_KIND_TEST)
        for _ in range(tddloop.retry_max()):
            got = self.wrong_kind()
            self.assertFalse(got["ok"])
        self.assertTrue(got["done"], "tdd の単位が 1 つなので輪は済む")
        self.assertEqual((self.repo / "test_stats.py").read_text(encoding="utf-8"), head, "作業ツリーは単位の頭")
        u = self.st()["units"][MEAN]
        self.assertEqual((u["route"], u["gave_up"]), ("direct", "red"))

    def test_unknown_kind_is_recorded_not_rejected(self):
        """実行器が failure に message も type も書かない（SUITE）なら赤の種類は unknown。拒まず記録する"""
        self.suite.write_text(SUITE, encoding="utf-8")
        self.route()
        self.red()
        self.assertEqual(self.st()["units"][MEAN]["red_kinds"], {MEAN_ID: tddloop.KIND_UNKNOWN})


class TestNoContract(LoopCase):
    def test_no_contract_same_as_before(self):
        """約束の無い run（LoopCase）は、名指しの名前も赤の種類も見ない"""
        self.assertEqual(self.st()["contract"], {})
        self.assertEqual(tddloop.plan_contract(self.board, [MEAN, CLAMP]), {}, "盤面の無い置き場は空")
        self.route()
        self.add_test(NEW_TEST.replace("test_mean_of_two", "test_other_name"))
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"],
                         "tests": ["test_stats.py::TestStats::test_other_name"]})
        self.assertTrue(got["ok"], got)
        self.assertEqual(self.st()["units"][MEAN]["red_kinds"],
                         {"test_stats.py::TestStats::test_other_name": tddloop.KIND_UNKNOWN})

    def test_board_without_fields_has_no_contract(self):
        """盤面が在っても欄の控えが無ければ（frozen_fields が None）約束は空"""
        (self.board / "state.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(tddloop.entry, "open_board", return_value=object()), \
                mock.patch.object(tddloop.conflict, "frozen_fields", return_value=None):
            self.assertEqual(tddloop.plan_contract(self.board, [MEAN, CLAMP]), {})


REWRITE = "test_stats.py::TestStats::test_clamp_above_range"


class TestPlanRewrites(ContractCase):
    """修正案が書き換えを名指した既存のテスト（約束の rewrites）は、テストの段の名指しに入れて同じ赤→緑の関門を通す。
    名指しの外の既存のテストの本体（.py の test* 関数）は凍っている"""
    CONTRACT = {CLAMP: {"items": [1], "route": "tdd", "tests": [], "rewrites": [REWRITE], "refactor": False}}

    def rewrite(self):
        self.edit("test_stats.py", "self.assertEqual(clamp(15, 0, 10), 10)",
                  "self.assertEqual(clamp(15, 0, 10), 10)\n        self.assertEqual(clamp(99, 0, 10), 10)")

    def test_rewrite_must_be_named(self):
        self.route(mean="direct", clamp="tdd"); self.rewrite()
        got = self.step({"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": []})
        self.assertFalse(got["ok"]); self.assertIn(REWRITE, got["reason"])

    def test_rewrite_red_then_green_then_frozen(self):
        self.route(mean="direct", clamp="tdd"); self.rewrite()
        got = self.step({"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": [REWRITE]})
        self.assertTrue(got["ok"], got)
        self.edit("stats.py", "    if x > hi:\n        return lo", "    if x > hi:\n        return hi")
        got = self.step({"phase": "fix", "unit_key": CLAMP, "files": ["stats.py"], "what": "上限の枝で hi を返す"})
        self.assertTrue(got["ok"], got)
        if self.st()["phase"] == "refactor":   # Task 4 の前は整えの段が来る。後は申告なしで done
            self.step({"phase": "refactor", "unit_key": CLAMP, "what": "整える物は無い"})
        self.assertTrue(self.st()["done"])
        self.assertIn("test_stats.py", self.st()["frozen"])

    def test_unnamed_existing_test_edit_rejected(self):
        self.route(mean="direct", clamp="tdd"); self.rewrite()
        self.edit("test_stats.py", "self.assertEqual(clamp(5, 0, 10), 5)", "self.assertTrue(True)")
        got = self.step({"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": [REWRITE]})
        self.assertFalse(got["ok"])
        self.assertIn("test_stats.py::TestStats::test_clamp_within_range", got["reason"])

    def test_import_and_new_test_edits_pass(self):
        self.route(mean="direct", clamp="tdd"); self.rewrite()
        self.edit("test_stats.py", "from stats import clamp, mean", "from stats import clamp, mean  # noqa")
        self.add_test("\n    def test_clamp_at_hi(self):\n        self.assertEqual(clamp(10, 0, 10), 10)\n")
        got = self.step({"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": [REWRITE]})
        self.assertTrue(got["ok"], got)

    def test_rewrite_still_green_is_rejected(self):
        """書き換えが今のコードで通る（clamp(5, 0, 10) の行に書き換えた）→ 写しの red_problems の『もう通る』"""
        self.route(mean="direct", clamp="tdd")
        self.edit("test_stats.py", "self.assertEqual(clamp(15, 0, 10), 10)", "self.assertEqual(clamp(5, 0, 10), 5)")
        got = self.step({"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": [REWRITE]})
        self.assertFalse(got["ok"])
        self.assertIn(REWRITE, got["reason"])
        self.assertIn("もう通る", got["reason"])

    def test_rewrite_name_error_red_is_rejected(self):
        """書き換えが今のコードに無い名前で落ちる（NameError）赤は、狙いの赤でないので拒む"""
        self.route(mean="direct", clamp="tdd")
        self.edit("test_stats.py", "self.assertEqual(clamp(15, 0, 10), 10)", "self.assertEqual(clamp_to(15, 0, 10), 10)")
        got = self.step({"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": [REWRITE]})
        self.assertFalse(got["ok"])
        for w in (REWRITE, "NameError", "conflict"):
            self.assertIn(w, got["reason"])
        self.assertEqual(self.st()["phase"], "test")

    def test_unnamed_edit_rejected_before_running(self):
        """名指しの外の書き換えは実行器を走らせる前に拒む"""
        self.route(mean="direct", clamp="tdd"); self.rewrite()
        self.edit("test_stats.py", "self.assertEqual(clamp(5, 0, 10), 5)", "self.assertTrue(True)")
        runs = self.st()["runs"]
        got = self.step({"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": [REWRITE]})
        self.assertFalse(got["ok"])
        self.assertIn("rewrite_tests", got["reason"])
        self.assertEqual(self.st()["runs"], runs)


class TestUnnamedEditsWithoutContract(LoopCase):
    def test_no_contract_does_not_freeze_existing_tests(self):
        """約束の無い run は、既存のテストの本体の書き換えも今どおり見ない"""
        self.route()
        self.add_test(NEW_TEST)
        self.edit("test_stats.py", "self.assertEqual(clamp(5, 0, 10), 5)", "self.assertEqual(clamp(6, 0, 10), 6)")
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"],
                         "tests": ["test_stats.py::TestStats::test_mean_of_two"]})
        self.assertTrue(got["ok"], got)


class TestTestFunctions(unittest.TestCase):
    def test_ids_and_sources(self):
        src = "import x\n\nclass T:\n    @d\n    def test_a(self):\n        pass\n\n    def helper(self):\n        pass\n\ndef test_b():\n    pass\n"
        got = tddloop.test_functions(src, "t.py")
        self.assertEqual(set(got), {"t.py::T::test_a", "t.py::test_b"})
        self.assertTrue(got["t.py::T::test_a"].startswith("@d"))
        self.assertEqual(tddloop.test_functions("def (", "t.py"), {})
        self.assertEqual(tddloop.test_functions(src, "t.sh"), {})

    def test_unnamed_edits(self):
        """木の時に在った test* 関数の本体が変わった・消えた物のうち、許しに無い id（整えた id で比べる）"""
        with tempfile.TemporaryDirectory() as td:
            repo = pathlib.Path(td) / "repo"
            committed_copy(repo, SEED)
            tree = tddloop.snapshot(repo)
            p = repo / "test_stats.py"
            text = p.read_text(encoding="utf-8")
            text = text.replace("clamp(5, 0, 10), 5)", "clamp(6, 0, 10), 6)").replace("clamp(15, 0, 10), 10)", "clamp(16, 0, 10), 10)")
            text = text.replace("    def test_mean_of_three(self):\n        self.assertEqual(mean([1, 2, 3]), 2)\n", "")
            p.write_text(text, encoding="utf-8")
            (repo / "notes.txt").write_text("x\n", encoding="utf-8")
            got = tddloop._unnamed_edits(repo, tree, ["test_stats.py", "notes.txt", "test_new.py"],
                                         {"./test_stats.py::TestStats::test_clamp_above_range"})
            self.assertEqual(sorted(got), ["test_stats.py::TestStats::test_clamp_within_range",
                                           "test_stats.py::TestStats::test_mean_of_three"])


class TestContractBroken(LoopCase):
    def test_broken_fields_stop_start(self):
        """盤面が在り、欄の控えが凍結の印と食い違う → plan_contract は Broken（理由の文は conflict.FIELDS_BROKEN で始まる）"""
        (self.board / "state.json").write_text("{}", encoding="utf-8")
        gap = tddloop.board.BoardGap(f"{tddloop.conflict.FIELDS_BROKEN}: 控えの sha256 が印と違う")
        with mock.patch.object(tddloop.entry, "open_board", return_value=object()), \
                mock.patch.object(tddloop.conflict, "frozen_fields", side_effect=gap), \
                mock.patch.object(tddloop.conflict, "fix_duty", return_value=({MEAN, CLAMP}, {})):
            with self.assertRaises(tddloop.Broken) as got:
                tddloop.plan_contract(self.board, [MEAN])
            self.assertTrue(str(got.exception).startswith(tddloop.conflict.FIELDS_BROKEN), got.exception)
            with self.assertRaises(tddloop.Broken) as again:
                tddloop.start(self.board, self.repo, str(self.suite), OPEN)
            self.assertTrue(str(again.exception).startswith(tddloop.conflict.FIELDS_BROKEN), again.exception)

    def test_board_that_cannot_open_is_broken(self):
        (self.board / "state.json").write_text("{}", encoding="utf-8")
        with mock.patch.object(tddloop.entry, "open_board", side_effect=tddloop.board.BoardGap("開けない")):
            with self.assertRaisesRegex(tddloop.Broken, "開けない"):
                tddloop.plan_contract(self.board, [MEAN])


class TestRedKind(unittest.TestCase):
    def test_kinds(self):
        def k(t, m):
            return tddloop.red_kind({"fail_type": t, "fail_message": m})
        self.assertEqual(k("", "assert 3.0 == 2"), "assertion")
        self.assertEqual(k("", "AssertionError: 3.0 != 2"), "assertion")
        self.assertEqual(k("", "AssertionError: ValueError not raised"), "exception")
        self.assertEqual(k("", "Failed: DID NOT RAISE ValueError"), "exception")
        self.assertEqual(k("", "NameError: name 'f' is not defined"), "NameError")
        self.assertEqual(k("org.opentest4j.AssertionFailedError", "expected: <1>"), "assertion")
        self.assertEqual(k("", ""), tddloop.KIND_UNKNOWN)
        self.assertEqual(k("", "3.0 != 2"), tddloop.KIND_UNKNOWN)

    def test_kinds_custom_assertion_and_junit5_not_thrown(self):
        """名前が AssertionError で終わる型（自前の子の型）は assertion。JUnit 5 の『to be thrown, but nothing was thrown』は exception"""
        def k(t, m):
            return tddloop.red_kind({"fail_type": t, "fail_message": m})
        self.assertEqual(k("", "MyAssertionError: 3.0 != 2"), "assertion")
        self.assertEqual(k("pkg.CustomAssertionError", "m"), "assertion")
        self.assertEqual(k("org.opentest4j.AssertionFailedError",
                           "Expected java.lang.IllegalArgumentException to be thrown, but nothing was thrown."), "exception")

    def test_kind_rule(self):
        """赤の種類の照らし（_kind_problems）: 拒むのは名前・import の失敗の 4 つの型と、exception の案に断言の失敗だけ。
        ほかの例外の型（落ちる種類のバグ）は記録だけで拒まない。案の red_kind が RED_KINDS の外なら見ない"""
        def probs(declared, msg):
            case = {"classname": "test_stats.TestStats", "name": "test_mean_of_two", "outcome": "failure",
                    "fail_type": "", "fail_message": msg}
            return tddloop._kind_problems([{"id": MEAN_ID, "red_kind": declared}], [case])
        self.assertEqual(probs("assertion", "ZeroDivisionError: division by zero"), [])
        self.assertEqual(probs("assertion", "Failed: DID NOT RAISE ValueError"), [])
        for name in ("NameError", "AttributeError", "ImportError", "ModuleNotFoundError"):
            got = probs("assertion", f"{name}: x")
            self.assertEqual(len(got), 1, name)
            self.assertIn(name, got[0])
            self.assertIn("conflict", got[0])
            self.assertTrue(probs("exception", f"{name}: x"), name)
        self.assertEqual(probs("exception", "Failed: DID NOT RAISE ValueError"), [])
        self.assertEqual(probs("exception", "TypeError: bad operand"), [])
        self.assertTrue(probs("exception", "AssertionError: 3.0 != 2"))
        self.assertEqual(probs(None, "NameError: name 'f' is not defined"), [])
        self.assertEqual(probs("weird", "NameError: name 'f' is not defined"), [])

    def test_run_suite_rows_carry_failure_attrs(self):
        """run_suite の結末の行に failure の子の type・message（無ければ空）"""
        with tempfile.TemporaryDirectory() as td:
            work = pathlib.Path(td)
            exe = work / "suite.py"
            exe.write_text("import sys\nopen(sys.argv[1], 'w').write('<testsuite>"
                           "<testcase classname=\"a\" name=\"t1\"><failure type=\"x.AssertionError\" message=\"m\"/></testcase>"
                           "<testcase classname=\"a\" name=\"t2\"/></testsuite>')\nsys.exit(1)\n", encoding="utf-8")
            cases, _, why = tddloop.run_suite(str(exe), work, work, "attrs")
        self.assertEqual(why, [])
        self.assertEqual([(c["name"], c["fail_type"], c["fail_message"]) for c in cases],
                         [("t1", "x.AssertionError", "m"), ("t2", "", "")])


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
