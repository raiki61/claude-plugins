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
import fixshape  # noqa: E402
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

    def test_input_test_cmd_is_optional(self):
        self.assertEqual((block()["inputs"]["test_cmd"].get("default"), "required" in block()["inputs"]["test_cmd"]), ("", False))

    def test_node_order(self):
        nodes = block()["nodes"]
        self.assertEqual([n["id"] for n in nodes],
                         ["ignored-before", "tdd-start", "tdd-loop", "fix-loop", "conflict-check", "rule-loop", "fix-ruled-loop",
                          "clean", "assert-changed", "fix-reads", "collect"])
        start, loop, fix_loop = nodes[1:4]
        self.assertEqual(start["script"], "tdd_start")
        self.assertEqual(start["depends_on"], ["ignored-before"])
        self.assertEqual(start["timeout"], DEADLINE)
        self.assertEqual(start["with"], {"tdd_suite": "$INPUTS.tdd_suite", "open_units": "$INPUTS.open_units",
                                         "test_cmd": "$INPUTS.test_cmd"})
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
        # Skill と skills: は借りたスキルの座（修正の形 g3。計画 220 Task 2。test_seat が座の表と縛る）
        self.assertEqual(role["allowed_tools"], ["Read", "Grep", "Glob", "Edit", "Write", "Bash", "WebSearch", "WebFetch", "Skill"])
        self.assertEqual(role["skills"], ["test-driven-development"])
        self.assertEqual(role["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})
        self.assertEqual(role["idle_timeout"], DEADLINE)
        of = role["output_format"]
        self.assertEqual(of["description"], "works-node: tdd", "包みが会話を節の名で分け、続きの起動で指示書の形を選ぶ")
        self.assertIs(of["additionalProperties"], False)
        self.assertEqual(of["required"], ["phase"])
        self.assertEqual(of["properties"]["phase"]["enum"], [*tddloop.PHASES, "conflict"], "食い違いの申し出はどの段でも")
        self.assertEqual(of["properties"]["refactor"]["required"], ["declared", "why"], "fix の段の整えの申告")

    def test_accept_and_collect_get_tdd(self):
        nodes = block()["nodes"]
        accept = find_node(nodes, "fix-accept")
        self.assertEqual(accept["with"]["tdd_state"], "$tdd-start.output.state_file")
        for nid in ("fix-accept", "fix-ruled-accept"):   # 事後の関門の束の実行器（計画 220 Task 4）
            self.assertEqual(find_node(nodes, nid)["with"]["tdd_suite"], "$INPUTS.tdd_suite", nid)
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
        want = {"tdd_start": ("INPUTS_TDD_SUITE", "INPUTS_OPEN_UNITS", "INPUTS_TEST_CMD"), "tdd_prep": ("INPUTS_STATE_FILE", "INPUTS_JUDGMENT_FILE", "INPUTS_PLAN_FILE",
                                                                                       "INPUTS_POLICY_PATH", "INPUTS_NOTES_FILE"),
                "tdd_step": ("INPUTS_REPLY", "INPUTS_STATE_FILE"),
                "accept": ("INPUTS_REPLY", "INPUTS_BASE_REV", "INPUTS_TDD_STATE", "INPUTS_ITERATION", "INPUTS_PASS",
                           "INPUTS_TDD_SUITE"),
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
                                                            "INPUTS_TEST_CMD": "", "ARTIFACTS_DIR": str(art)})
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


DECLARED = {"declared": True, "why": "分母の式を名前の付いた変数に分けたい"}   # fix の段の整えの申告（理由は MIN_WHY 字以上）
PLAN_REFACTOR = {"item": 1, "why": "分母の計算を補助の関数に寄せる"}   # 約束の refactor の 1 行（修正案の項目の申告）


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

    def shape(self, name, test_cmd=""):
        """盤面の r1/start.json に fix_shape=name を置き、tdd-start を起こし直す（test_cmd は線の入力）"""
        p = self.board / fixshape.START_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({fixshape.KEY: name}), encoding="utf-8")
        self.start = tddloop.start(self.board, self.repo, str(self.suite), OPEN, test_cmd=test_cmd)
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

    def fix_mean(self, refactor=None):
        """mean を直して fix の段を返す。refactor は整えの申告（{declared, why}。None は欄を書かない）"""
        self.edit("stats.py", "return sum(xs) / (len(xs) - 1)", "return sum(xs) / len(xs)")
        reply = {"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母を len(xs) にした"}
        if refactor is not None:
            reply["refactor"] = refactor
        got = self.step(reply)
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

    def test_g3_tdd_prompt_carries_seat(self):
        """修正の形 g3 の盤面: TDD の役の指示書に借りたスキルの座（test-driven-development）と読み替えの頭の行が載る"""
        import rolekit
        import seat
        with mock.patch.object(tddloop.fixshape, "shape_at", return_value="g3") as at:
            prompt = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        self.assertEqual(pathlib.Path(at.call_args[0][0]).resolve(), self.board.resolve(), "盤面の置き場で形を読む")
        self.assertIn(seat.HEAD, prompt)
        self.assertIn("test-driven-development", prompt)
        self.assertIn(rolekit.skill_overlay().splitlines()[0], prompt)

    def test_g3_tdd_seat_failure_stops_with_broken(self):
        """座を組めない（写しが固定と違う など）g3 の盤面は、座の無い指示書に逃げず Broken（tdd_prep が 2 で落ちる）"""
        with mock.patch.object(tddloop.fixshape, "shape_at", return_value="g3"), \
                mock.patch.object(tddloop.seat, "section", side_effect=ValueError("implementer-prompt.md: 中身が固定と違う")):
            with self.assertRaisesRegex(tddloop.Broken, "座を組めない"):
                tddloop.prep(self.state)

    def test_af_tdd_prompt_has_no_seat(self):
        import seat
        with mock.patch.object(tddloop.fixshape, "shape_at", return_value="af"):
            prompt = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        self.assertNotIn(seat.HEAD, prompt)
        self.assertNotIn(seat.HEAD, pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8"),
                         "盤面の無い置き場（記録の無い盤面は af）も座を出さない")

    def test_g1_skips_loop(self):
        """修正の形 g1 の盤面: 輪の頭と同じ元の結末を取って状態を書き（受け付けの選んで回す試験が読む）、輪だけを回さない
        （go: false・理由 G1_NO_LOOP・輪の要約は無い）"""
        fixshape.choose(self.board, "g1", by="試験", why="g1 は輪を回さない")
        got = tddloop.start(self.board, self.repo, str(self.suite), OPEN)
        self.assertEqual({k: got[k] for k in ("go", "reason", "suite", "summary_file")},
                         {"go": False, "reason": tddloop.G1_NO_LOOP, "suite": str(self.suite), "summary_file": ""})
        self.assertEqual(tddloop.G1_NO_LOOP, "修正の形 g1——TDD の輪は回さない（修正役が下請けを回し、赤緑と凍結は修正の受け付けの束が"
                                             "事後に確かめる）")
        st = json.loads(pathlib.Path(got["state_file"]).read_text(encoding="utf-8"))
        self.assertEqual(st["baseline"], self.st()["baseline"], "輪の頭と同じ元の結末")
        self.assertEqual((st["frozen"], st["order"]), ({}, []), "輪は回っていない（凍ったテストも単位も無い）")
        self.assertEqual(tddloop.exit_fields(got)["ran"], False)

    def test_g1_does_not_run_test_cmd_gate(self):
        """g1 の tdd-start は元の結末だけを取り、test_cmd の関門は決めない（輪が無いので使わない。平の run と同じ切った関門）"""
        fixshape.choose(self.board, "g1", by="試験", why="g1 は test_cmd を走らせない")
        mark = self.repo.parent / "test-cmd-ran"
        got = tddloop.start(self.board, self.repo, str(self.suite), OPEN,
                            test_cmd=f"{sys.executable} -c \"open({str(mark)!r}, 'w')\"")
        st = json.loads(pathlib.Path(got["state_file"]).read_text(encoding="utf-8"))
        self.assertEqual((st["test_cmd_gate"], st["test_cmd_note"]), (tddloop.GATE_OFF, tddloop.G1_NO_LOOP))
        self.assertFalse(mark.exists(), "test_cmd を走らせない")
        self.assertFalse(pathlib.Path(st["work"], "test-cmd-0.log").exists())


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
        got = self.fix_mean()
        self.assertEqual((got["ok"], got["done"]), (True, True), "申告が無ければ整えの段は来ない")
        ex = tddloop.exit_fields(self.start)
        self.assertTrue(ex["ran"])
        rows = {u["unit_key"]: u for u in ex["units"]}
        m = rows[MEAN]
        self.assertEqual((m["route"], m["red"], m["green"], m["refactor"], m["gave_up"]), ("tdd", "ok", "ok", "skipped", ""))
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
        self.fix_mean(refactor=DECLARED)
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
        self.fix_mean(refactor=DECLARED)
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
    CONTRACT = {MEAN: {"items": [1], "route": "tdd", "rewrites": [], "refactor": [],
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
    CONTRACT = {CLAMP: {"items": [1], "route": "tdd", "tests": [], "rewrites": [REWRITE], "refactor": []}}

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


class TestPlanVanishedTests(ContractCase):
    """約束の在る単位のテストの段: 元の結末で通っていたテストが飛ばされた・結末から消えたら拒む（名指しの外の本体を変えずに
    クラスの setUp・モジュールの末尾で外す抜け道）"""
    CONTRACT = TestPlanRewrites.CONTRACT

    def red_with(self, old, new):
        self.route(mean="direct", clamp="tdd")
        self.edit("test_stats.py", "self.assertEqual(clamp(15, 0, 10), 10)", "self.assertEqual(clamp(99, 0, 10), 10)")
        self.edit("test_stats.py", old, new)
        return self.step({"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": [REWRITE]})

    def test_skipped_in_setup_rejected(self):
        got = self.red_with("class TestStats(unittest.TestCase):\n",
                            "class TestStats(unittest.TestCase):\n    def setUp(self):\n"
                            "        if self._testMethodName == \"test_clamp_within_range\":\n            self.skipTest(\"外す\")\n\n")
        self.assertFalse(got["ok"])
        self.assertIn("test_clamp_within_range", got["reason"])
        self.assertIn("skipped", got["reason"])

    def test_syntax_error_named_as_such(self):
        """テストのファイルが構文として読めなければ、関数を全部『書き換えた』と並べず、構文の誤りとして名指す"""
        got = self.red_with("\n\nif __name__", "\n\ndef (\n\nif __name__")
        self.assertFalse(got["ok"])
        self.assertIn("構文", got["reason"])
        self.assertNotIn("test_clamp_within_range", got["reason"])


OTHER_TEST = ("import os\nimport unittest\n\nfrom stats import clamp\n\n\nclass TestOther(unittest.TestCase):\n"
              "    def test_low(self):\n        self.assertEqual(clamp(-1, 0, 10), 0)\n")
LOW_KEY = "test_other.TestOther::test_low"
OTHER_SKIP = ("class TestOther(unittest.TestCase):\n",
              "class TestOther(unittest.TestCase):\n    def setUp(self):\n        self.skipTest(\"外す\")\n\n")
OTHER_DEL = ("        self.assertEqual(clamp(-1, 0, 10), 0)\n",
             "        self.assertEqual(clamp(-1, 0, 10), 0)\n\n\ndel TestOther.test_low\n")
# PYTEST_LIKE の写しで、後ろに node id を渡されたらその名のテストだけを走らせる実行器（`pytest --junitxml="$1" "${@:2}"` の形）
NAMED_ONLY = PYTEST_LIKE.replace(
    'unittest.defaultTestLoader.discover(".", pattern="test_*.py", top_level_dir=".").run(R())',
    'def flat(s):\n'
    '    for x in s:\n'
    '        yield from (flat(x) if isinstance(x, unittest.TestSuite) else [x])\n'
    'tests = list(flat(unittest.defaultTestLoader.discover(".", pattern="test_*.py", top_level_dir=".")))\n'
    'if sys.argv[2:]:\n'
    '    names = {a.rsplit("::", 1)[-1] for a in sys.argv[2:]}\n'
    '    tests = [t for t in tests if t.id().rsplit(".", 1)[-1] in names]\n'
    'unittest.TestSuite(tests).run(R())')


def _with_other_test(case, body=OTHER_TEST):
    """case の setUp の tddloop.start の前に、対象リポジトリへ既存のテストのファイル test_other.py を置く（元の結末にも載る）"""
    orig = tddloop.start

    def start(board_dir, repo, *a, **k):
        other = pathlib.Path(repo) / "test_other.py"
        if not other.exists():
            other.write_text(body, encoding="utf-8")
        return orig(board_dir, repo, *a, **k)
    return mock.patch.object(tddloop, "start", start)


class TestFixPhaseFreezesOtherTests(ContractCase):
    """約束の在る単位の直し・整えの段で、単位のテストのファイルの外の既存のテスト（テストのファイルの名の .py の test* 関数）を
    書き換えたら拒む"""
    CONTRACT = {CLAMP: {**TestPlanRewrites.CONTRACT[CLAMP],   # 整えの段を申告で必ず通す
                        "refactor": [{"item": 1, "why": "テストの補助の重なりを寄せる"}]}}
    LOW = "test_other.py::TestOther::test_low"

    def setUp(self):
        with _with_other_test(self):
            super().setUp()

    def red(self):
        self.route(mean="direct", clamp="tdd")
        self.edit("test_stats.py", "self.assertEqual(clamp(15, 0, 10), 10)", "self.assertEqual(clamp(99, 0, 10), 10)")
        got = self.step({"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": [REWRITE]})
        self.assertTrue(got["ok"], got)
        self.edit("stats.py", "    if x > hi:\n        return lo", "    if x > hi:\n        return hi")

    def test_fix_phase_edit_of_other_test_rejected(self):
        self.red()
        self.edit("test_other.py", "self.assertEqual(clamp(-1, 0, 10), 0)", "self.assertTrue(True)")
        got = self.step({"phase": "fix", "unit_key": CLAMP, "files": ["stats.py", "test_other.py"], "what": "上限の枝で hi を返す"})
        self.assertFalse(got["ok"])
        self.assertIn(self.LOW, got["reason"])

    def test_refactor_phase_edit_of_other_test_rejected(self):
        self.red()
        got = self.step({"phase": "fix", "unit_key": CLAMP, "files": ["stats.py"], "what": "上限の枝で hi を返す"})
        self.assertTrue(got["ok"], got)
        self.assertEqual(self.st()["phase"], "refactor")
        self.edit("test_other.py", "self.assertEqual(clamp(-1, 0, 10), 0)", "self.assertTrue(True)")
        got = self.step({"phase": "refactor", "unit_key": CLAMP, "what": "テストの補助を整えた"})
        self.assertFalse(got["ok"])
        self.assertIn(self.LOW, got["reason"])

    def fix_with(self, old, new):
        self.red()
        self.edit("test_other.py", old, new)
        return self.step({"phase": "fix", "unit_key": CLAMP, "files": ["stats.py"], "what": "上限の枝で hi を返す"})

    def refactor_with(self, old, new):
        self.red()
        got = self.step({"phase": "fix", "unit_key": CLAMP, "files": ["stats.py"], "what": "上限の枝で hi を返す"})
        self.assertTrue(got["ok"], got)
        self.assertEqual(self.st()["phase"], "refactor")
        self.edit("test_other.py", old, new)
        return self.step({"phase": "refactor", "unit_key": CLAMP, "what": "テストの補助を整えた"})

    def assert_vanished(self, got, outcome):
        self.assertFalse(got["ok"])
        self.assertIn(LOW_KEY, got["reason"])
        self.assertIn(outcome, got["reason"])
        self.assertIn(CLAMP, got["reason"], "変えた単位を名指す")

    def test_fix_phase_skip_rejected(self):
        self.assert_vanished(self.fix_with(*OTHER_SKIP), "skipped")

    def test_fix_phase_del_rejected(self):
        self.assert_vanished(self.fix_with(*OTHER_DEL), "missing")

    def test_refactor_phase_skip_rejected(self):
        self.assert_vanished(self.refactor_with(*OTHER_SKIP), "skipped")

    def test_refactor_phase_del_rejected(self):
        self.assert_vanished(self.refactor_with(*OTHER_DEL), "missing")

    def test_fix_phase_syntax_error_named_as_such(self):
        got = self.fix_with("    def test_low(self):\n", "    def test_low(self:\n")
        self.assertFalse(got["ok"])
        self.assertIn("構文", got["reason"])
        self.assertIn("test_other.py", got["reason"])

    def test_test_functions_in_implementation_files_not_frozen(self):
        """テストのファイルの名でない .py（実装）の test* 関数は見ない"""
        self.red()
        self.edit("stats.py", "def mean(xs):", "def test_helper():\n    return 1\n\n\ndef mean(xs):")
        got = self.step({"phase": "fix", "unit_key": CLAMP, "files": ["stats.py"], "what": "上限の枝で hi を返す"})
        self.assertTrue(got["ok"], got)


class TestFixPhaseOtherTestsWithoutContract(LoopCase):
    def setUp(self):
        with _with_other_test(self):
            super().setUp()

    def test_no_contract_same_as_before(self):
        """約束の無い run の直しの段は、ほかのテストのファイルの書き換えを今どおり見ない"""
        self.route()
        self.red()
        self.edit("test_other.py", "self.assertEqual(clamp(-1, 0, 10), 0)", "self.assertTrue(True)")
        self.fix_mean()


class TestNamedOnlyRunner(ContractCase):
    """後ろの node id だけを走らせる実行器: 名指しの外のテストは結末に居ないが、単位の頭の結末と選び（後ろの引数）が違う回の
    居ないは消えたに数えない（輪は通る）"""
    CONTRACT = TestPlanRewrites.CONTRACT

    def setUp(self):
        with _with_other_test(self):
            super().setUp()
        self.suite.write_text(NAMED_ONLY, encoding="utf-8")

    def test_loop_passes(self):
        self.route(mean="direct", clamp="tdd")
        self.edit("test_stats.py", "self.assertEqual(clamp(15, 0, 10), 10)", "self.assertEqual(clamp(99, 0, 10), 10)")
        got = self.step({"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": [REWRITE]})
        self.assertTrue(got["ok"], got)
        self.edit("stats.py", "    if x > hi:\n        return lo", "    if x > hi:\n        return hi")
        got = self.step({"phase": "fix", "unit_key": CLAMP, "files": ["stats.py"], "what": "上限の枝で hi を返す"})
        self.assertTrue(got["ok"], got)


class TestUntouchedModuleSkipIgnored(ContractCase):
    """触れていないモジュールのテストが環境で飛ばされても（単位の頭から変わったテストのファイルの外）、消えたに数えない"""
    CONTRACT = TestPlanRewrites.CONTRACT

    def setUp(self):
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.flag = pathlib.Path(td.name) / "skip.flag"
        body = OTHER_TEST.replace("    def test_low(self):\n", "    def test_low(self):\n"
                                  f"        if os.path.exists({str(self.flag)!r}):\n            self.skipTest(\"環境\")\n")
        with _with_other_test(self, body):
            super().setUp()

    def test_env_skip_in_untouched_module_passes(self):
        self.route(mean="direct", clamp="tdd")
        self.edit("test_stats.py", "self.assertEqual(clamp(15, 0, 10), 10)", "self.assertEqual(clamp(99, 0, 10), 10)")
        self.flag.write_text("x", encoding="utf-8")
        got = self.step({"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": [REWRITE]})
        self.assertTrue(got["ok"], got)
        self.edit("stats.py", "    if x > hi:\n        return lo", "    if x > hi:\n        return hi")
        got = self.step({"phase": "fix", "unit_key": CLAMP, "files": ["stats.py"], "what": "上限の枝で hi を返す"})
        self.assertTrue(got["ok"], got)


class TestVanished(unittest.TestCase):
    """消えたテストの照らし（tddloop._vanished。純粋）"""
    HEAD = {"outcome": {"test_x.T::test_a[1]": "passed", "test_x.T::test_b": "passed", "test_y.U::test_c": "passed",
                        "test_x.T::test_s": "skipped"}, "args": []}

    def test_parametrized_rewrite_and_verified_excluded(self):
        now = {"test_x.T::test_a[2]": "passed", "test_x.T::test_b": "skipped", "test_y.U::test_c": "passed"}
        self.assertEqual(tddloop._vanished(self.HEAD, [self.HEAD], now, [], None, ["t/test_x.py::T::test_a", "./test_x.py::T::test_b"]),
                         [])
        self.assertEqual(tddloop._vanished(self.HEAD, [self.HEAD], now, [], None, ["t/test_x.py::T::test_a"]),
                         [("test_x.T::test_b", "skipped")])

    def test_absent_counts_only_with_same_selection(self):
        now = {"test_x.T::test_b": "passed"}
        self.assertEqual(tddloop._vanished(self.HEAD, [self.HEAD], now, ["x::y"], None, []), [], "選びが違う")
        self.assertEqual(sorted(tddloop._vanished(self.HEAD, [self.HEAD], now, [], None, [])),
                         [("test_x.T::test_a[1]", "missing"), ("test_y.U::test_c", "missing")])

    def test_scope_limits_modules(self):
        now = {}
        self.assertEqual(tddloop._vanished(self.HEAD, [self.HEAD], now, [], {"test_y"}, []), [("test_y.U::test_c", "missing")])

    def test_scope_of_touched_files(self):
        self.assertEqual(tddloop._vanish_scope(["a/test_y.py", "stats.py", "b/x_test.py"]), {"test_y", "x_test"})
        self.assertIsNone(tddloop._vanish_scope(["test_y.py", "tests/conftest.py"]), "conftest.py に触れたら一式")


class TestRewriteSharedAcrossUnits(ContractCase):
    """1 つの項目が 2 つの単位にまたがると、同じ書き換えの名指しが両方の単位の約束に載る。前の単位で赤→緑を確かめた id は、
    後の単位で名指しを強いない（もう通るので強いると後の単位は必ず落ちる）。確かめた後は凍っていて、後の単位では書き換えられない"""
    CONTRACT = {CLAMP: {"items": [1], "route": "tdd", "tests": [], "rewrites": [REWRITE], "refactor": []},
                MEAN: {"items": [1], "route": "tdd", "tests": [{"id": MEAN_ID, "red_kind": "assertion"}], "rewrites": [REWRITE],
                       "refactor": []}}

    def clamp_done(self):
        got = self.step({"phase": "route", "units": [{"unit_key": CLAMP, "route": "tdd"}, {"unit_key": MEAN, "route": "tdd"}]})
        self.assertTrue(got["ok"], got)
        self.edit("test_stats.py", "self.assertEqual(clamp(15, 0, 10), 10)",
                  "self.assertEqual(clamp(15, 0, 10), 10)\n        self.assertEqual(clamp(99, 0, 10), 10)")
        got = self.step({"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": [REWRITE]})
        self.assertTrue(got["ok"], got)
        self.edit("stats.py", "    if x > hi:\n        return lo", "    if x > hi:\n        return hi")
        got = self.step({"phase": "fix", "unit_key": CLAMP, "files": ["stats.py"], "what": "上限の枝で hi を返す"})
        self.assertTrue(got["ok"], got)
        if self.st()["phase"] == "refactor":
            self.step({"phase": "refactor", "unit_key": CLAMP, "what": "整える物は無い"})
        self.assertEqual(self.st()["queue"][self.st()["cur"]], MEAN)

    def test_verified_rewrite_not_forced_in_later_unit(self):
        self.clamp_done()
        self.add_test(NEW_TEST)
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"], "tests": [MEAN_ID]})
        self.assertTrue(got["ok"], got)

    def test_verified_rewrite_frozen_in_later_unit(self):
        self.clamp_done()
        self.add_test(NEW_TEST)
        self.edit("test_stats.py", "self.assertEqual(clamp(99, 0, 10), 10)", "self.assertEqual(clamp(98, 0, 10), 10)")
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"], "tests": [MEAN_ID]})
        self.assertFalse(got["ok"])
        self.assertIn(REWRITE, got["reason"])


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

    def test_nested_class_ids(self):
        """入れ子のクラスのメソッドも pytest の node id の形（<パス>::A::B::test_x）で引く"""
        src = "class A:\n    class B:\n        def test_x(self):\n            pass\n\n    def test_y(self):\n        pass\n"
        self.assertEqual(set(tddloop.test_functions(src, "t.py")), {"t.py::A::B::test_x", "t.py::A::test_y"})

    def test_parametrized_permission_covers_function(self):
        """許しが parametrize の id（<id>[1]）でも、その関数の書き換えは名指しの外に数えない"""
        with tempfile.TemporaryDirectory() as td:
            repo = pathlib.Path(td) / "repo"
            committed_copy(repo, SEED)
            tree = tddloop.snapshot(repo)
            p = repo / "test_stats.py"
            p.write_text(p.read_text(encoding="utf-8").replace("clamp(5, 0, 10), 5)", "clamp(6, 0, 10), 6)"), encoding="utf-8")
            self.assertEqual(tddloop._unnamed_edits(repo, tree, ["test_stats.py"],
                                                    {"test_stats.py::TestStats::test_clamp_within_range[1]"}), [])

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
        for declared in (None, "weird"):   # 宣言の無い名指し（書き換え）: 名前・import の失敗だけを拒む
            self.assertTrue(probs(declared, "NameError: name 'f' is not defined"), declared)
            self.assertEqual(probs(declared, "AssertionError: 3.0 != 2"), [], declared)
            self.assertEqual(probs(declared, "Failed: DID NOT RAISE ValueError"), [], declared)

    def test_kind_rule_declared_names(self):
        """declared（adds の名前）に在る名前の NameError・AttributeError・ImportError・ModuleNotFoundError は拒まない。宣言の外・
        名前の引けない message・declared が空は今どおり 1 行拒む。exception の案に断言の失敗の拒みは残る"""
        def probs(declared, msg, want="assertion"):
            case = {"classname": "test_stats.TestStats", "name": "test_mean_of_two", "outcome": "failure",
                    "fail_type": "", "fail_message": msg}
            return tddloop._kind_problems([{"id": MEAN_ID, "red_kind": want}], [case], declared)
        hits = ("AttributeError: module 'stats' has no attribute 'clamp'", "NameError: name 'clamp' is not defined",
                "ImportError: cannot import name 'clamp' from 'stats' (/tmp/stats.py)", "ModuleNotFoundError: No module named 'stats.clamp'")
        for msg in hits:
            self.assertEqual(probs(["clamp"], msg), [], msg)
            self.assertEqual(probs(["stats.clamp(xs, lo, hi)"], msg), [], msg)
            self.assertEqual(len(probs(["clam"], msg)), 1, msg)
            self.assertEqual(len(probs(["clampx", "mean"], msg)), 1, msg)
            self.assertEqual(len(probs([], msg)), 1, msg)
            self.assertEqual(len(probs((), msg, "exception")), 1, msg)
        self.assertEqual(len(probs(["clamp"], "NameError: boom")), 1)
        self.assertEqual(probs(["clamp"], "AssertionError: 3.0 != 2"), [])
        self.assertTrue(probs(["clamp"], "AssertionError: 3.0 != 2", "exception"))
        self.assertEqual(probs(["clamp"], "NameError: name 'clamp' is not defined", "exception"), [])

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


LINT = "import pathlib, sys\nsys.exit(1 if 'print(' in pathlib.Path('stats.py').read_text() else 0)\n"
# 整形の真似: 直した後の stats.py（分母が len(xs)）だけを書き換え、新しいファイル fmt.cache も作って 0 で抜ける
FMT = ("import pathlib\np = pathlib.Path('stats.py')\nt = p.read_text()\n"
       "p.write_text(t.replace('sum(xs) / len(xs)', 'sum(xs)/len(xs)'))\npathlib.Path('fmt.cache').write_text('x')\n")
# いつも stats.py を書き換える test_cmd（輪の頭で書き換えが見える）
FMT_ALWAYS = "import pathlib\np = pathlib.Path('stats.py')\np.write_text(p.read_text() + '\\n# formatted\\n')\n"


class TestTestCmdGate(LoopCase):
    """緑の後に run の test_cmd（線の入力）の緑も確かめる。元から赤なら関門を切って理由を残し、実行器が同じコマンドを
    包んだ物なら 2 度走らせない（Review Focus 5）"""

    def restart(self, cmd):
        (self.repo / "lint.py").write_text(LINT, encoding="utf-8")
        git(self.repo, "add", "lint.py")
        git(self.repo, "commit", "-qm", "lint")
        self.start = tddloop.start(self.board, self.repo, str(self.suite), OPEN, test_cmd=cmd)
        self.state = self.start["state_file"]

    def lint(self):
        return f"{sys.executable} lint.py"

    def test_fix_rejected_when_test_cmd_red(self):
        self.restart(self.lint())
        self.assertEqual(self.st()["test_cmd_gate"], tddloop.GATE_ON)
        self.route()
        self.red()
        self.edit("stats.py", "return sum(xs) / (len(xs) - 1)", "print('debug')\n    return sum(xs) / len(xs)")
        got = self.step({"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母を直した"})
        self.assertFalse(got["ok"])
        self.assertIn("test_cmd", got["reason"])
        self.assertIn("test-cmd-", got["reason"])
        self.assertEqual(self.st()["phase"], "fix")
        self.assertTrue(pathlib.Path(self.st()["work"], f"test-cmd-{self.st()['runs'] - 1}.log").is_file())

    def test_fix_passes_and_records(self):
        self.restart(self.lint())
        self.route()
        self.red()
        self.fix_mean(refactor=DECLARED)
        self.assertEqual(self.st()["units"][MEAN]["test_cmd"], "ok")
        self.step({"phase": "refactor", "unit_key": MEAN, "what": "整える物は無い"})
        ex = tddloop.exit_fields(self.start)
        self.assertEqual(ex["test_cmd"], {"gate": tddloop.GATE_ON, "note": ""})
        rows = {u["unit_key"]: u for u in ex["units"]}
        self.assertEqual((rows[MEAN]["test_cmd"], rows[CLAMP]["test_cmd"]), ("ok", ""))

    def test_changed_refactor_rejected_when_test_cmd_red(self):
        self.restart(self.lint())
        self.route()
        self.red()
        self.fix_mean(refactor=DECLARED)
        self.edit("stats.py", "return sum(xs) / len(xs)", "print('debug')\n    return sum(xs) / len(xs)")
        got = self.step({"phase": "refactor", "unit_key": MEAN, "what": "出力を足した"})
        self.assertFalse(got["ok"])
        self.assertIn("test_cmd", got["reason"])

    def test_baseline_red_test_cmd_turns_gate_off(self):
        self.restart(f"{sys.executable} -c 'raise SystemExit(1)'")
        st = self.st()
        self.assertEqual(st["test_cmd_gate"], tddloop.GATE_OFF)
        self.assertTrue(st["test_cmd_note"])
        self.route()
        self.red()
        self.fix_mean(refactor=DECLARED)   # 毎単位を拒まない
        self.assertEqual(self.st()["units"][MEAN]["test_cmd"], "")
        self.step({"phase": "refactor", "unit_key": MEAN, "what": "整える物は無い"})
        self.assertEqual(tddloop.exit_fields(self.start)["test_cmd"], {"gate": tddloop.GATE_OFF, "note": st["test_cmd_note"]})

    def test_same_command_as_suite_runs_once(self):
        cmd = f"{sys.executable} {self.suite}"
        with mock.patch.object(tddloop.entry, "local_checks_material") as lcm:
            self.suite.write_text(SUITE + f"\n# {cmd}\n", encoding="utf-8")
            self.restart(cmd)
            self.route()
            self.red()
            self.fix_mean()
        lcm.assert_not_called()
        self.assertEqual(self.st()["test_cmd_gate"], tddloop.GATE_SAME)

    def test_empty_test_cmd_is_off(self):
        with mock.patch.object(tddloop.entry, "local_checks_material") as lcm:
            self.restart("")
            self.route()
            self.red()
            self.fix_mean()
        lcm.assert_not_called()
        st = self.st()
        self.assertEqual((st["test_cmd"], st["test_cmd_gate"], st["test_cmd_note"]), ("", tddloop.GATE_OFF, ""))

    def test_default_start_has_gate_off(self):
        """LoopCase の既定（test_cmd を渡さない start）も関門は off・理由は空"""
        st = self.st()
        self.assertEqual((st["test_cmd"], st["test_cmd_gate"], st["test_cmd_note"]), ("", tddloop.GATE_OFF, ""))

    def test_test_cmd_not_run_leaves_loop_like_runner_down(self):
        self.restart(self.lint())
        self.route()
        self.red()
        down = {"material": {"status": "not_run", "reason": "起こせない"}}
        self.edit("stats.py", "return sum(xs) / (len(xs) - 1)", "return sum(xs) / len(xs)")
        with mock.patch.object(tddloop.entry, "local_checks_material", return_value=down):
            got = self.step({"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母を直した"})
        self.assertTrue(got["done"])
        self.assertIn("起こせない", got["reason"])
        self.assertTrue(got["reason"].startswith("テストのコマンドが走らない"), got["reason"])
        self.assertEqual(self.st()["units"][MEAN]["gave_up"], "runner")

    def tool(self, name, src):
        (self.repo / name).write_text(src, encoding="utf-8")
        git(self.repo, "add", name)
        git(self.repo, "commit", "-qm", name)
        return f"{sys.executable} {name}"

    def test_rewriting_test_cmd_is_restored_and_not_excused(self):
        """既存のファイルを書き換えた test_cmd は緑でない: 拒み、理由に書き換えたパスを載せ、元に戻して suite_made に積まない
        （書き込みの出どころの照合から外さない）。新しく出来たファイルは今どおり積む"""
        self.restart(self.tool("fmt.py", FMT))
        self.assertEqual(self.st()["test_cmd_gate"], tddloop.GATE_ON)
        self.route()
        self.red()
        self.edit("stats.py", "return sum(xs) / (len(xs) - 1)", "return sum(xs) / len(xs)")
        got = self.step({"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母を len(xs) にした"})
        self.assertFalse(got["ok"], got)
        self.assertIn("stats.py", got["reason"])
        self.assertIn("元に戻した", got["reason"])
        self.assertIn("phase conflict", got["reason"])
        st = self.st()
        self.assertEqual(st["phase"], "fix")
        self.assertNotIn("stats.py", st["suite_made"])
        self.assertIn("fmt.cache", st["suite_made"])
        self.assertIn("return sum(xs) / len(xs)", (self.repo / "stats.py").read_text(encoding="utf-8"), "役の直しの姿に戻す")

    def test_red_test_cmd_reason_names_conflict_for_frozen_tests(self):
        """赤の元が凍ったテストのファイルなら直しの段では直せないので、拒む文が申し出の道を名指す"""
        self.restart(self.lint())
        self.route()
        self.red()
        self.edit("stats.py", "return sum(xs) / (len(xs) - 1)", "print('debug')\n    return sum(xs) / len(xs)")
        got = self.step({"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母を直した"})
        self.assertIn("赤の元が凍ったテストのファイルなら phase conflict で申し出よ", got["reason"])

    def test_test_cmd_runs_niced(self):
        """輪の中の test_cmd は nice を付けて走らせる（ADR 0071 の 3 の 1。実行器の run_suite と同じ）"""
        clean = {"material": {"status": "clean", "count": 0, "checked": "x", "detail": ""}}
        with mock.patch.object(tddloop.entry, "local_checks_material", return_value=clean) as lcm:
            self.restart(self.lint())
            self.route()
            self.red()
            self.fix_mean()
        self.assertEqual(lcm.call_count, 2)
        self.assertTrue(all(c.kwargs.get("niced") is True for c in lcm.call_args_list), lcm.call_args_list)

    def test_start_rewriting_test_cmd_turns_gate_off(self):
        self.restart(self.tool("fmt_always.py", FMT_ALWAYS))
        st = self.st()
        self.assertEqual(st["test_cmd_gate"], tddloop.GATE_OFF)
        self.assertIn("test_cmd が作業ツリーの既存のファイルを書き換える", st["test_cmd_note"])
        self.assertIn("stats.py", st["test_cmd_note"])
        self.assertNotIn("stats.py", st["suite_made"])
        self.assertNotIn("# formatted", (self.repo / "stats.py").read_text(encoding="utf-8"))

    def test_prompt_names_test_cmd_only_when_gate_on(self):
        """関門が on の時だけ、直し・整えの段の指示書に test_cmd の文字列が載る（拒まれて初めて知るのを防ぐ）"""
        cmd = self.lint()
        self.restart(cmd)
        self.route()
        self.assertNotIn(cmd, pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8"), "test の段")
        self.red()
        self.assertIn(cmd, pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8"), "fix の段")
        self.fix_mean(refactor=DECLARED)
        self.assertIn(cmd, pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8"), "refactor の段")

    def test_prompt_omits_test_cmd_when_gate_off(self):
        off = f"{sys.executable} -c 'raise SystemExit(1)'"
        self.restart(off)
        self.route()
        self.red()
        self.assertNotIn(off, pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8"), "関門が off")

    def test_start_not_run_turns_gate_off_with_reason(self):
        down = {"material": {"status": "not_run", "reason": "起こせない"}}
        with mock.patch.object(tddloop.entry, "local_checks_material", return_value=down):
            self.restart(self.lint())
        st = self.st()
        self.assertEqual(st["test_cmd_gate"], tddloop.GATE_OFF)
        self.assertIn("起こせない", st["test_cmd_note"])


class TestRefactorGate(LoopCase):
    """整えの段は、fix の段で役が理由つきで申告した単位か、修正案の項目が refactor.declared の単位だけに来る。来ない単位は
    skipped。段ごとの呼び出しの記録（calls）を状態と出口に残す"""

    def test_fix_without_declaration_skips_refactor(self):
        self.route()
        self.red()
        got = self.fix_mean()
        self.assertTrue(got["done"], got)
        u = tddloop.exit_fields(self.start)["units"][0]
        self.assertEqual((u["refactor"], u["refactor_why"]), ("skipped", ""))
        self.assertIn("整え: skipped", pathlib.Path(self.start["summary_file"]).read_text(encoding="utf-8"))

    def test_declared_fix_goes_to_refactor(self):
        self.route()
        self.red()
        self.fix_mean(refactor=DECLARED)
        self.assertEqual(self.st()["phase"], "refactor")
        self.assertEqual(self.st()["units"][MEAN]["refactor_why"], DECLARED["why"])
        self.assertIn("refactor", pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8"))
        self.step({"phase": "refactor", "unit_key": MEAN, "what": "整える物は無い"})
        self.assertIn(f"整え: none（{DECLARED['why']}）", pathlib.Path(self.start["summary_file"]).read_text(encoding="utf-8"))

    def test_declared_without_why_rejected(self):
        self.route()
        self.red()
        self.edit("stats.py", "return sum(xs) / (len(xs) - 1)", "return sum(xs) / len(xs)")
        got = self.step({"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母を直した",
                         "refactor": {"declared": True, "why": "短い"}})
        self.assertFalse(got["ok"])
        self.assertIn("refactor", got["reason"])
        self.assertEqual(self.st()["phase"], "fix")

    def test_malformed_declaration_rejected(self):
        self.route()
        self.red()
        self.edit("stats.py", "return sum(xs) / (len(xs) - 1)", "return sum(xs) / len(xs)")
        got = self.step({"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母を直した",
                         "refactor": {"declared": "yes", "why": DECLARED["why"]}})
        self.assertFalse(got["ok"])
        self.assertIn("refactor", got["reason"])

    def test_not_declared_with_why_skips(self):
        self.route()
        self.red()
        got = self.fix_mean(refactor={"declared": False, "why": ""})
        self.assertTrue(got["done"], got)
        self.assertEqual(self.st()["units"][MEAN]["refactor"], "skipped")

    def test_plan_declared_goes_to_refactor_without_reply(self):
        """案の項目が refactor.declared の単位は、役が申告しなくても整えの段が来る"""
        contract = {MEAN: {"items": [1], "route": "tdd", "tests": [], "rewrites": [], "refactor": [PLAN_REFACTOR]}}
        with mock.patch.object(tddloop, "plan_contract", return_value=contract):
            self.start = tddloop.start(self.board, self.repo, str(self.suite), OPEN)
        self.state = self.start["state_file"]
        self.route()
        self.red()
        self.fix_mean()
        self.assertEqual(self.st()["phase"], "refactor")
        self.assertIn(f"項目 1: {PLAN_REFACTOR['why']}", self.st()["units"][MEAN]["refactor_why"])

    def test_role_and_plan_reasons_are_joined(self):
        """役と修正案の両方が申告したら、空でない理由を全部つなぐ"""
        contract = {MEAN: {"items": [1], "route": "tdd", "tests": [], "rewrites": [], "refactor": [PLAN_REFACTOR]}}
        with mock.patch.object(tddloop, "plan_contract", return_value=contract):
            self.start = tddloop.start(self.board, self.repo, str(self.suite), OPEN)
        self.state = self.start["state_file"]
        self.route()
        self.red()
        self.fix_mean(refactor=DECLARED)
        why = self.st()["units"][MEAN]["refactor_why"]
        self.assertIn(DECLARED["why"], why)
        self.assertIn(f"項目 1: {PLAN_REFACTOR['why']}", why)

    def test_calls_mark_runner_down(self):
        """実行器が走らずに輪を抜けた回は、役の拒否と分けて phase runner の行"""
        self.route()
        self.add_test(NEW_TEST)
        self.suite.write_text("import sys\nsys.exit(3)\n", encoding="utf-8")   # JUnit を書かない
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"],
                         "tests": ["test_stats.py::TestStats::test_mean_of_two"]})
        self.assertTrue(got["done"])
        last = self.st()["calls"][-1]
        self.assertEqual((last["phase"], last["unit_key"], last["ok"], last["runs"]), ("runner", MEAN, False, 1))

    def test_calls_mark_passed_conflict(self):
        got = self.step({"phase": "conflict", "unit_key": MEAN, "between": ["stats.py:9", "test_stats.py:9"],
                         "why_both_cannot_hold": "テストは分母 len(xs) - 1 の値を期待しているが、依頼は算術平均を求めている",
                         "which_is_right": "request", "kind": "unnamed_test_broke"})
        self.assertTrue(got["ok"], got)
        self.assertEqual(self.st()["calls"], [{**self.st()["calls"][0], "n": 1, "phase": "conflict", "unit_key": "",
                                               "ok": True, "runs": 0}])

    def test_calls_mark_give_up(self):
        """諦めた回も、その段の ok: false の行（数えは retry_max 行）"""
        self.route()
        self.red()
        for _ in range(tddloop.retry_max()):
            got = self.step({"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "直せていない"})
        self.assertTrue(got["done"])
        rows = self.st()["calls"][2:]
        self.assertEqual([(c["phase"], c["ok"]) for c in rows], [("fix", False)] * tddloop.retry_max())

    def test_skipped_unit_moves_to_next_unit(self):
        """飛ばした単位の次の単位は、緑の木を頭に test の段から始まる"""
        self.route(clamp="tdd")
        self.red()
        self.fix_mean()
        st = self.st()
        self.assertEqual((st["phase"], st["queue"][st["cur"]], st["done"]), ("test", CLAMP, False))
        self.assertEqual(st["units"][MEAN]["refactor"], "skipped")

    def test_calls_recorded(self):
        self.route()
        self.red()
        self.fix_mean()
        calls = self.st()["calls"]
        self.assertEqual([c["n"] for c in calls], [1, 2, 3])
        self.assertEqual([c["phase"] for c in calls], ["route", "test", "fix"])
        self.assertEqual([c["unit_key"] for c in calls], ["", MEAN, MEAN])
        self.assertTrue(all(c["ok"] for c in calls))
        self.assertEqual([c["runs"] for c in calls], [0, 1, 1])
        self.assertTrue(all(isinstance(c["secs"], float) for c in calls))
        self.assertEqual(tddloop.exit_fields(self.start)["calls"], calls)

    def test_calls_record_rejection_and_conflict_phase(self):
        self.route()
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"], "tests": []})
        self.assertFalse(got["ok"])
        self.step({"phase": "conflict", "unit_key": MEAN, "between": ["nope.py:1", "nope.py:2"],
                   "why_both_cannot_hold": "試験のための申し出", "which_is_right": "unknown"})
        calls = self.st()["calls"]
        self.assertEqual([(c["phase"], c["ok"]) for c in calls[1:]], [("test", False), ("conflict", False)])
        self.assertEqual(calls[1]["unit_key"], MEAN)


FAR_TEST = """
    def test_clamp_far_above(self):
        self.assertEqual(clamp(20, 0, 10), 10)
"""
FAR_ID = "test_stats.py::TestStats::test_clamp_far_above"


class TestCrossLoopFreeze(LoopCase):
    """凍結は run の全部の輪で効く（依頼 226 の 2 回目の修正の段）: 1 回目の段の輪（tdd-1）が凍らせたテストのファイルは、2 回目の
    段の輪（tdd-2）の後も、2 回目の輪の状態の handoff の木（since）からの変更で見る。2 回目の輪が同じファイルに足したテストは
    2 回目の輪の凍結で見る。直した項目の単位の tdd-1 の受け入れのテストの関数（skip_spans）だけは書き直してよい"""

    def first_loop(self):
        """tdd-1: MEAN を tdd で緑にして test_stats.py を凍らせる"""
        self.route()
        self.red()
        self.assertTrue(self.fix_mean()["done"])
        self.assertEqual(list(self.st()["frozen"]), ["test_stats.py"])

    def second_loop(self, keys, route="direct") -> str:
        """tdd-2 を keys で起こして振り分ける（direct なら輪は済む）。返りは tdd-2 の状態のファイル"""
        got = tddloop.start(self.board, self.repo, str(self.suite), json.dumps(keys, ensure_ascii=False))
        self.assertTrue(got["go"], got)
        rows = [{"unit_key": k, "route": route, **({"why": "2 回目の段で先にテストを書かない単位"} if route == "direct" else {})}
                for k in keys]
        self.assertTrue(tddloop.step(got["state_file"], {"phase": "route", "units": rows}, self.repo)["ok"])
        return got["state_file"]

    def since(self, state2) -> str:
        return tddloop.load_state(state2)["handoff"]

    def test_states_in_order_and_suite_made_all(self):
        self.first_loop()
        state2 = self.second_loop([CLAMP])
        self.assertEqual(tddloop.states(self.board), [pathlib.Path(self.state), pathlib.Path(state2)])
        for f, made in ((self.state, ["one.log"]), (state2, ["two.log"])):
            st = tddloop.load_state(f)
            st["suite_made"] = made
            pathlib.Path(f).write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(tddloop.suite_made_all(self.board), {"one.log", "two.log"})
        self.assertEqual(tddloop.states(self.tmp_board()), [])

    def tmp_board(self):
        return pathlib.Path(self._tmp.name) / "no-board"

    def test_second_pass_cannot_touch_first_loop_frozen_tests(self):
        self.first_loop()
        state2 = self.second_loop([CLAMP])
        since = self.since(state2)
        self.assertEqual(tddloop.frozen_problems(self.state, self.repo, since=since), [])
        self.edit("test_stats.py", "mean([2, 4]), 3", "mean([2, 4]), 3.0")   # 2 回目の修正役が tdd-1 の凍ったテストを変えた
        got = tddloop.frozen_problems(self.state, self.repo, since=since)
        self.assertTrue(got and "test_stats.py" in got[0], got)
        self.assertEqual(tddloop.frozen_problems(state2, self.repo), [], "tdd-2 は何も凍らせていない")

    def test_second_loop_may_add_test_to_first_loop_file(self):
        self.first_loop()
        state2 = self.second_loop([CLAMP], route="tdd")
        self.add_test(FAR_TEST)
        got = tddloop.step(state2, {"phase": "test", "unit_key": CLAMP, "test_files": ["test_stats.py"], "tests": [FAR_ID]},
                           self.repo)
        self.assertTrue(got["ok"], got)
        self.edit("stats.py", "    if x > hi:\n        return lo", "    if x > hi:\n        return hi")
        got = tddloop.step(state2, {"phase": "fix", "unit_key": CLAMP, "files": ["stats.py"], "what": "上限で hi を返す"},
                           self.repo)
        self.assertTrue(got["done"], got)
        self.assertTrue(tddloop.frozen_problems(self.state, self.repo), "since が無ければ tdd-1 の凍った時の木で見る")
        self.assertEqual(tddloop.frozen_problems(self.state, self.repo, since=self.since(state2)), [])
        self.edit("test_stats.py", "clamp(20, 0, 10), 10", "clamp(20, 0, 10), 0")
        self.assertTrue(tddloop.frozen_problems(state2, self.repo), "足したテストは tdd-2 の凍結で見る")

    def test_amended_units_old_test_span_is_not_frozen(self):
        self.first_loop()
        state2 = self.second_loop([MEAN])
        since = self.since(state2)
        spans = tddloop.test_spans(self.state, {MEAN})
        self.assertEqual(spans, [("test_stats.py", "TestStats::test_mean_of_two")])
        self.assertEqual(tddloop.test_spans(self.state, {CLAMP}), [], "tdd-1 で緑にしていない単位の関数は無い")
        self.edit("test_stats.py", "mean([2, 4]), 3", "mean([2, 4, 6]), 4")
        self.assertTrue(tddloop.frozen_problems(self.state, self.repo, since=since))
        self.assertEqual(tddloop.frozen_problems(self.state, self.repo, since=since, skip_spans=spans), [])
        self.edit("test_stats.py", "clamp(5, 0, 10), 5", "clamp(6, 0, 10), 6")   # 関数の範囲の外
        got = tddloop.frozen_problems(self.state, self.repo, since=since, skip_spans=spans)
        self.assertTrue(got and "範囲の外" in got[0], got)

    def test_frozen_source_reads_since_tree(self):
        """テストの変更の許しの行を引き直す木は、凍結の検査が比べる木（since）と同じ"""
        self.first_loop()
        state2 = self.second_loop([CLAMP])
        since = self.since(state2)
        self.edit("test_stats.py", "mean([2, 4]), 3", "mean([2, 4]), 3.0")
        read = tddloop.frozen_source(self.state, self.repo, since=since)
        self.assertEqual(read("test_stats.py").rstrip("\n"), git(self.repo, "show", f"{since}:test_stats.py").rstrip("\n"))
        self.assertIn("mean([2, 4]), 3)", read("test_stats.py"))


class TestPlainShape(LoopCase):
    """修正の形 current（平の run・比べの基準）: 219 の前の振る舞い。修正案の約束を読まず、整えはいつも回し、test_cmd の関門は切る"""

    def setUp(self):
        super().setUp()
        self.shape("current")

    def test_always_refactor_without_declaration(self):
        """申告が無くても整えの段へ。refactor_why は役の申告のまま（空。形の名を役に渡さない）"""
        self.route()
        self.red()
        self.fix_mean()   # 申告なし
        self.assertEqual(self.st()["phase"], "refactor")
        self.assertEqual(self.st()["units"][MEAN]["refactor_why"], "")

    def test_contract_depends_on_shape(self):
        """盤面と欄の控えが在っても、current は欄を読まず約束が空。同じ盤面で af は約束を組む"""
        (self.board / "state.json").write_text("{}", encoding="utf-8")
        fields = [{"unit_keys": [MEAN], "route": "tdd", "route_why": "", "rewrite_tests": [],
                   "tests": [{"id": "test_stats.py::TestStats::test_mean_of_two", "behavior": "2 つの値の平均",
                              "path": "stats.mean を直に呼ぶ", "red_kind": "assertion", "red_why": "今は len-1 で割る"}],
                   "refactor": {"declared": False, "why": ""}}]
        with mock.patch.object(tddloop.entry, "open_board"), \
                mock.patch.object(tddloop.conflict, "fix_duty", return_value=([MEAN, CLAMP], {})), \
                mock.patch.object(tddloop.conflict, "frozen_fields", return_value=fields) as ff:
            self.shape("current")
            self.assertEqual(self.st()["contract"], {})
            ff.assert_not_called()
            self.shape("af")
            self.assertEqual(list(self.st()["contract"]), [MEAN])

    def test_prompts_use_pre_219_wording(self):
        """fix・refactor の段の指示書は 219 の前の文（申告の決まりの文を出さず、整えがいつも来ることを添える）"""
        self.route()
        self.red()
        fix = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        self.assertNotIn(tddloop.DO["fix"], fix)
        self.assertIn("機械が一式を走らせ、名指しのテストと元で通っていたテストが通ることを確かめる。", fix)
        self.assertIn(tddloop.PLAIN_DO["fix"], fix)
        self.fix_mean()
        ref = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        self.assertNotIn(tddloop.DO["refactor"], ref)
        self.assertIn("緑のまま、今の単位の差分を整えよ（重複・名前・不要になったコード。テストのファイルは変えない）", ref)
        for text in (fix, ref):
            self.assertNotIn("current", text, "形の名を役に渡さない")

    def test_broken_shape_stops_start(self):
        """形の控えが壊れていれば、traceback でなく理由の Broken で止める"""
        p = self.board / fixshape.CHOICE_REL
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("壊れた", encoding="utf-8")
        with self.assertRaisesRegex(tddloop.Broken, "修正の形"):
            tddloop.start(self.board, self.repo, str(self.suite), OPEN, test_cmd=f"{sys.executable} -c pass")

    def test_test_cmd_gate_off_with_note(self):
        """緑の test_cmd でも走らせず、関門を切って理由を残す"""
        self.shape("current", test_cmd=f"{sys.executable} -c pass")
        self.assertEqual((self.st()["test_cmd_gate"], self.st()["test_cmd_note"]), (tddloop.GATE_OFF, tddloop.PLAIN_NOTE))
        self.assertEqual(tddloop.PLAIN_NOTE, "修正の形 current——test_cmd の関門は回さない（比べの基準）")
        self.assertFalse(pathlib.Path(self.st()["work"], "test-cmd-0.log").exists(), "輪の頭で test_cmd を走らせない")
        self.route()
        self.red()
        self.fix_mean()
        self.assertTrue(self.step({"phase": "refactor", "unit_key": MEAN, "what": "整える物は無い"})["done"])
        self.assertEqual(self.st()["units"][MEAN]["test_cmd"], "", "緑の後も test_cmd を走らせない")
        ex = tddloop.exit_fields(self.start)
        self.assertEqual(ex["test_cmd"], {"gate": tddloop.GATE_OFF, "note": tddloop.PLAIN_NOTE})

    def test_af_keeps_219_behavior(self):
        """形 af の盤面は今どおり: 申告の無い単位は整えを飛ばし、緑の test_cmd は on"""
        self.shape("af", test_cmd=f"{sys.executable} -c pass")
        self.assertEqual(self.st()["test_cmd_gate"], tddloop.GATE_ON)
        self.route()
        self.red()
        fix = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(tddloop.DO["fix"], fix)
        self.assertTrue(self.fix_mean()["done"])
        self.assertEqual(self.st()["units"][MEAN]["refactor"], "skipped")


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
