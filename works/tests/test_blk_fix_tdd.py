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
import planmarks  # noqa: E402
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

    def test_input_unit_depths_is_optional_and_reaches_tdd_start(self):
        # 単位ごとの深さ（{"<単位の key>": "軽量" | "標準"} の JSON の文字列）。空は全部の単位が今どおり
        self.assertEqual((block()["inputs"]["unit_depths"].get("default"), "required" in block()["inputs"]["unit_depths"]),
                         ("", False))
        self.assertEqual(find_node(block()["nodes"], "tdd-start")["with"]["unit_depths"], "$INPUTS.unit_depths")

    def test_node_order(self):
        nodes = block()["nodes"]
        self.assertEqual([n["id"] for n in nodes],
                         ["ignored-before", "tdd-start", "tdd-loop", "tdd-fork", "tdd-lane-loop-1", "tdd-lane-loop-2",
                          "tdd-lane-loop-3", "tdd-join", "tdd-rest-loop", "fix-fork", "fix-lane-loop-1", "fix-lane-loop-2",
                          "fix-lane-loop-3", "fix-join", "fix-loop", "conflict-check", "rule-loop",
                          "fix-ruled-loop", "clean", "assert-changed", "fix-reads", "collect"])
        start, loop = nodes[1:3]
        fix_loop = find_node(nodes, "fix-loop")
        self.assertEqual(start["script"], "tdd_start")
        self.assertEqual(start["depends_on"], ["ignored-before"])
        self.assertEqual(start["timeout"], DEADLINE)
        self.assertEqual(start["with"], {"tdd_suite": "$INPUTS.tdd_suite", "open_units": "$INPUTS.open_units",
                                         "test_cmd": "$INPUTS.test_cmd", "unit_depths": "$INPUTS.unit_depths",
                                         "tdd_lanes": "$INPUTS.tdd_lanes"})   # 並べの枝の切り替え（off なら lanes_on を偽に）
        self.assertEqual(loop["depends_on"], ["tdd-start"])
        self.assertEqual(loop["when"], "$tdd-start.output.go == true")
        g = loop["loop_group"]
        self.assertEqual(g["max_iterations"], tddloop.MAX_ITERATIONS)
        from test_yaml_rules import LOOP_MAX
        # 表のほかの行は修正の輪 2 つ（受け付けの 3 回と範囲の相談の枠の和。tests/test_consult.py が見る）
        tdd_max = {k[2]: v for k, v in LOOP_MAX.items() if not k[2].startswith("fix-")}   # 修正の輪と修正役の並べの枝の輪を除く
        self.assertEqual(set(tdd_max.values()), {tddloop.MAX_ITERATIONS})
        self.assertEqual(set(tdd_max), {"tdd-loop", "tdd-rest-loop", "tdd-lane-loop-1", "tdd-lane-loop-2", "tdd-lane-loop-3"})
        self.assertIs(g["fresh_context"], False, "テスト→直す→整えるを同じ会話で（C17）")
        self.assertEqual(g["until_bash"], "test $tdd-step.output.done = true",
                         "印で抜ける（R50）。並べの枝を切った周も done で抜ける（並べは輪の外の節。docs/plans/2026-10-07-lane-nodes.md）")
        self.assertEqual([n["id"] for n in g["nodes"]], ["tdd-prep", "tdd", "tdd-step"])
        prep, role, step = g["nodes"]
        self.assertEqual(prep["with"], {"state_file": "$tdd-start.output.state_file", "judgment_file": "$INPUTS.judgment_file",
                                        "plan_file": "$INPUTS.plan_file", "policy_path": "$INPUTS.policy_path",
                                        "notes_file": "$INPUTS.notes_file"})
        self.assertEqual(role["depends_on"], ["tdd-prep"])
        # resume で 1 周目から回し直された済んだ輪: 支度の go: false で役を飛ばし、確かめが返答 null で輪を抜ける（TestResume）
        self.assertEqual(prep["output_format"]["required"], ["prompt_file", "go"])
        self.assertEqual(role["when"], "$tdd-prep.output.go == true")
        self.assertEqual((step["depends_on"], step["trigger_rule"]), (["tdd-prep", "tdd"], "none_failed_min_one_success"))
        self.assertEqual(step["with"], {"reply": {"from": "$tdd.output", "if_skipped": None},
                                        "state_file": "$tdd-start.output.state_file"})
        for n in (prep, step):
            self.assertEqual(n["timeout"], DEADLINE)
        self.assertEqual(fix_loop["depends_on"], ["tdd-start", "tdd-loop", "tdd-fork", "tdd-join", "tdd-rest-loop", "fix-fork",
                                                  "fix-join"])   # 修正役の並べの枝（tests/test_fix_lane_wiring.py）の後
        self.assertEqual(fix_loop["trigger_rule"], "none_failed_min_one_success", "輪・並べ・順の輪が飛ばされても直す")

    def test_tdd_role_node(self):
        role = find_node(block()["nodes"], "tdd")
        self.assertNotIn("command", role)
        self.assertIn("`$tdd-prep.output.prompt_file` を Read で", role["prompt"])
        self.assertEqual(role["settingSources"], ["user"])
        # Skill と skills: は借りたスキルの座（修正の形 g3。計画 220 Task 2。test_seat が座の表と縛る）
        # Agent は持たない（並べは枝ごとの Archon の節。docs/plans/2026-10-07-lane-nodes.md）
        self.assertEqual(role["allowed_tools"], ["Read", "Grep", "Glob", "Edit", "Write", "Bash", "WebSearch", "WebFetch", "Skill"])
        self.assertEqual(role["skills"], ["test-driven-development"])
        self.assertEqual(role["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})
        self.assertEqual(role["idle_timeout"], DEADLINE)
        of = role["output_format"]
        self.assertEqual(of["description"], "works-node: tdd", "包みが会話を節の名で分け、続きの起動で指示書の形を選ぶ")
        self.assertIs(of["additionalProperties"], False)
        self.assertEqual(of["required"], ["phase"])
        self.assertEqual(of["properties"]["phase"]["enum"], [*[p for p in tddloop.PHASES if p != "lanes"], "conflict"],
                         "食い違いの申し出はどの段でも。並べの周（lanes）は役の段でない")
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
        want = {"tdd_start": ("INPUTS_TDD_SUITE", "INPUTS_OPEN_UNITS", "INPUTS_TEST_CMD", "INPUTS_UNIT_DEPTHS", "INPUTS_TDD_LANES"), "tdd_prep": ("INPUTS_STATE_FILE", "INPUTS_JUDGMENT_FILE", "INPUTS_PLAN_FILE",
                                                                                       "INPUTS_POLICY_PATH", "INPUTS_NOTES_FILE"),
                "tdd_step": ("INPUTS_REPLY", "INPUTS_STATE_FILE"),
                "tdd_fork": ("INPUTS_STATE_FILE",),
                "tdd_lane_prep": ("INPUTS_STATE_FILE", "INPUTS_LANE", "INPUTS_JUDGMENT_FILE", "INPUTS_PLAN_FILE",
                                  "INPUTS_POLICY_PATH", "INPUTS_NOTES_FILE"),
                "tdd_lane_step": ("INPUTS_REPLY", "INPUTS_STATE_FILE", "INPUTS_LANE"),
                "tdd_join": ("INPUTS_STATE_FILE",),
                "accept": ("INPUTS_REPLY", "INPUTS_BASE_REV", "INPUTS_TDD_STATE", "INPUTS_ITERATION", "INPUTS_PASS",
                           "INPUTS_TDD_SUITE", "INPUTS_CONSULTED"),
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
                                                            "INPUTS_TEST_CMD": "", "INPUTS_UNIT_DEPTHS": "",
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

    def restart(self, test_cmd=""):
        """tdd-start を起こし直す（test_cmd は線の入力）"""
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
        """tdd-prep の指示書: 修正の決まりの正本の核・TDD の読み替え・今の段の約束（今の段だけ）・今の段の指示。next.md は毎回
        決まりを全部載せる（全文版・差分版の控えは書かない）"""
        import fixrules
        core = fixrules.sections(fixrules.SHARED)["core-fix"]
        out = tddloop.prep(self.state, {"judgment_file": "/b/j.json"}, self.repo)
        prompt = pathlib.Path(out["prompt_file"])
        full = prompt.read_text(encoding="utf-8")
        for s in (core, fixrules.sections(fixrules.SHARED)["core-keep"], "## この輪での読み替え", "- **route**:",
                  "## この段ですること", "`/b/j.json`"):
            self.assertIn(s, full)
        self.assertNotIn("- **test**:", full, "今の段の約束だけ")
        self.assertFalse(fixrules.beside(prompt, ".delta.md").exists(), "差分版を書かない")
        self.route()
        tddloop.prep(self.state, {"judgment_file": "/b/j.json"}, self.repo)
        full2 = prompt.read_text(encoding="utf-8")
        self.assertIn(core, full2, "2 回目も決まりを全部")
        for s in ("- **test**:", "## この段ですること", "段 test"):
            self.assertIn(s, full2)
        self.assertEqual(fixrules.iteration_next(prompt), 3)

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

    def test_tdd_prep_hands_off_finished_units(self):
        """依頼 243 の 2: 次の単位の指示書に、前に済んだ単位の引き継ぎ（単位の key・直したファイル・緑にしたテスト・整え）を
        機械が書く（会話の履歴に頼らない。単位ごとに新しい会話で起こす前の支度）。最初の単位と振り分けの段には無い"""
        route = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        self.assertNotIn(tddloop.HANDOFF_HEAD, route)
        self.route(clamp="tdd")
        first = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        self.assertNotIn(tddloop.HANDOFF_HEAD, first, "最初の単位には引き継ぐ物が無い")
        self.red()
        self.fix_mean()
        st = self.st()
        self.assertEqual(st["units"][st["queue"][st["cur"]]]["unit_key"], CLAMP)
        nxt = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(tddloop.HANDOFF_HEAD, nxt)
        part = nxt.split(tddloop.HANDOFF_HEAD, 1)[1].split("\n## ", 1)[0]
        for w in (MEAN, "stats.py", "test_stats.py::TestStats::test_mean_of_two"):
            self.assertIn(w, part)
        self.assertNotIn(CLAMP, part, "今の単位は引き継ぎに載せない")

    def test_tdd_prep_writes_the_unit_key_for_the_adapter(self):
        """依頼 243 の 2: 支度は包みが会話を切る切れ目の鍵（輪の置き場の名と、振り分けの段は route・ほかは今の単位の key）を
        run ごとの置き場（adapter.session_key_path）に書く。単位が替わると鍵が替わる"""
        import adapter
        key = pathlib.Path(adapter.session_key_path(str(self.board), "tdd"))
        self.assertIn(tddloop.UNIT_NODE, adapter.KEYED_NODES, "包みが切れ目を見る節の名と同じ")
        tddloop.prep(self.state)
        work = pathlib.Path(self.st()["work"]).name
        self.assertEqual(key.read_text(encoding="utf-8").strip(), f"{work}:route")
        self.route(clamp="tdd")
        tddloop.prep(self.state)
        self.assertEqual(key.read_text(encoding="utf-8").strip(), f"{work}:{MEAN}")
        self.red()
        tddloop.prep(self.state)
        self.assertEqual(key.read_text(encoding="utf-8").strip(), f"{work}:{MEAN}", "同じ単位の段は同じ鍵（会話を継ぐ）")
        self.fix_mean()
        tddloop.prep(self.state)
        self.assertEqual(key.read_text(encoding="utf-8").strip(), f"{work}:{CLAMP}")

    def test_tdd_prep_without_board_has_no_brief(self):
        """盤面の無い置き場（修正案の無い run と同じ）では brief の節を置かない"""
        self.assertNotIn(planbrief.HEAD, pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8"))

    def test_tdd_prep_broken_ledger_stops_with_reason(self):
        """brief の控えが壊れていれば、brief の無い指示書として続けず、控えを名指す理由の Broken で止める（traceback にしない）"""
        broken = planbrief.LedgerBroken(f"brief の控え /b/r1/{planbrief.LEDGER} を読めない: 壊れた")
        with mock.patch.object(tddloop.planbrief, "cut_at", side_effect=broken):
            with self.assertRaisesRegex(tddloop.Broken, planbrief.LEDGER):
                tddloop.prep(self.state)

    def test_tdd_prompt_carries_seat(self):
        """TDD の役の指示書に借りたスキルの座（test-driven-development）と読み替えの頭の行が載る"""
        import rolekit
        import seat
        prompt = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(seat.HEAD, prompt)
        self.assertIn("test-driven-development", prompt)
        self.assertIn(rolekit.skill_overlay().splitlines()[0], prompt)

    def test_tdd_seat_failure_stops_with_broken(self):
        """座を組めない（写しが固定と違う など）時は、座の無い指示書に逃げず Broken（tdd_prep が 2 で落ちる）"""
        with mock.patch.object(tddloop.seat, "section", side_effect=ValueError("implementer-prompt.md: 中身が固定と違う")):
            with self.assertRaisesRegex(tddloop.Broken, "座を組めない"):
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

    def test_step_script_leaves_no_accept_last_row(self):
        # 輪の拒否・投げ出しは修正役への引き渡しで、run の落ちた理由ではない。受け付けの最後の結果の控え（accept-last.json）に
        # 行を書かない（書くと後の修正役の受け付けが通っても ok 偽が残り、次の run の prior_failures に載る。単位ごとの上書きも起きる）
        code, out, err = run_script("tdd_step", self.repo, {
            "INPUTS_REPLY": json.dumps({"phase": "route", "units": []}), "INPUTS_STATE_FILE": self.state,
            "ARTIFACTS_DIR": str(self.board.parent)})
        self.assertEqual(code, 0, err)
        self.assertIs(json.loads(out)["ok"], False)
        last = self.board / "accept-last.json"
        doc = json.loads(last.read_text(encoding="utf-8")) if last.is_file() else {}
        self.assertNotIn("tdd_step", doc)


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
# PYTEST_LIKE の写しで、後ろに試験を渡されたらそれだけを走らせる実行器（`pytest --junitxml="$1" "${@:2}"` の形。node id は
# その名のテスト、:: の無いパスはそのファイルのモジュールの全部）。gate が真なら、後ろの試験だけにするのは TDD_SUITE_ONLY=1 の時だけ
def _only_runner(gate):
    return PYTEST_LIKE.replace(
        'unittest.defaultTestLoader.discover(".", pattern="test_*.py", top_level_dir=".").run(R())',
        'import os, pathlib\n'
        'def flat(s):\n'
        '    for x in s:\n'
        '        yield from (flat(x) if isinstance(x, unittest.TestSuite) else [x])\n'
        'tests = list(flat(unittest.defaultTestLoader.discover(".", pattern="test_*.py", top_level_dir=".")))\n'
        'if sys.argv[2:] and ' + ('os.environ.get("TDD_SUITE_ONLY") == "1"' if gate else 'True') + ':\n'
        '    names = {a.rsplit("::", 1)[-1] for a in sys.argv[2:] if "::" in a}\n'
        '    mods = {pathlib.Path(a).stem for a in sys.argv[2:] if "::" not in a}\n'
        '    tests = [t for t in tests if t.id().rsplit(".", 1)[-1] in names or t.id().split(".", 1)[0] in mods]\n'
        'unittest.TestSuite(tests).run(R())')


NAMED_ONLY = _only_runner(False)
ONLY_AWARE = _only_runner(True)   # TDD_SUITE_ONLY=1 を解く実行器（輪の赤・緑の回は後ろの試験だけ。元の結末は一式）


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


class TestFixPhaseFreezesOtherTestsOnlyRunner(TestFixPhaseFreezesOtherTests):
    """同じ確かめを TDD_SUITE_ONLY=1 を解く実行器で: 緑の回は名指しと届いたモジュールのファイルだけなので、消えた（missing）は
    同じ選びの回でなく、その回にファイルごと走ったモジュール（whole）から外れた物として拾う"""

    def setUp(self):
        super().setUp()
        self.suite.write_text(ONLY_AWARE, encoding="utf-8")

    def test_green_run_was_narrowed(self):
        self.red()
        got = self.step({"phase": "fix", "unit_key": CLAMP, "files": ["stats.py"], "what": "上限の枝で hi を返す"})
        self.assertTrue(got["ok"], got)
        run = self.st()["green_run"]
        self.assertFalse(run["full"])
        self.assertEqual(sorted(run["whole"]), ["test_other", "test_stats"])


OTHER_GO = "package stats\n\nfunc TestLow(t *testing.T) {\n\tif Clamp(-1, 0, 10) != 0 {\n\t\tt.Fatal(\"low\")\n\t}\n}\n"


class TestFixPhaseFreezesNonPythonTests(ContractCase):
    """.py でない既存のテストのファイル（名の慣習か宣言で見分ける）も、直し・整えの段で行を消した・置き換えたら拒む
    （関数の幅は言語に依らず引けないので、足すだけの差分だけを通す）"""
    CONTRACT = TestFixPhaseFreezesOtherTests.CONTRACT

    def setUp(self):
        orig = tddloop.start

        def start(board_dir, repo, *a, **k):
            other = pathlib.Path(repo) / "stats_test.go"
            if not other.exists():
                other.write_text(OTHER_GO, encoding="utf-8")
                (pathlib.Path(repo) / "KeySpec.java").write_text("class KeySpec { int v = 1; }\n", encoding="utf-8")
            return orig(board_dir, repo, *a, **k)
        with mock.patch.object(tddloop, "start", start):
            super().setUp()

    red = TestFixPhaseFreezesOtherTests.red

    def test_fix_phase_edit_of_non_python_test_rejected(self):
        self.red()
        self.edit("stats_test.go", "Clamp(-1, 0, 10) != 0", "false")
        got = self.step({"phase": "fix", "unit_key": CLAMP, "files": ["stats.py", "stats_test.go"], "what": "上限の枝で hi を返す"})
        self.assertFalse(got["ok"], got)
        self.assertIn("stats_test.go", got["reason"])

    def test_fix_phase_edit_of_spec_named_implementation_passes(self):
        """名の尾が Spec でもテストのフォルダの外の実装（KeySpec.java）は凍らせない（直しの段で直してよい）"""
        self.red()
        self.edit("KeySpec.java", "int v = 1;", "int v = 2;")
        got = self.step({"phase": "fix", "unit_key": CLAMP, "files": ["stats.py", "KeySpec.java"], "what": "上限の枝で hi を返す"})
        self.assertTrue(got["ok"], got)

    def test_fix_phase_append_to_non_python_test_passes(self):
        self.red()
        self.edit("stats_test.go", "\t}\n}\n", "\t}\n}\n\nfunc helper() int { return 1 }\n")
        got = self.step({"phase": "fix", "unit_key": CLAMP, "files": ["stats.py", "stats_test.go"], "what": "上限の枝で hi を返す"})
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

    def test_absent_counts_in_module_run_whole(self):
        now = {"test_x.T::test_b": "passed"}
        self.assertEqual(tddloop._vanished(self.HEAD, [self.HEAD], now, ["x::y"], None, [], whole={"test_x"}),
                         [("test_x.T::test_a[1]", "missing")], "ファイルごと走ったモジュールから消えた（test_y は走っていない）")

    def test_head_merges_partial_green_run(self):
        prev = {"outcome": {"test_x.T::a": "passed", "test_x.T::gone": "passed", "test_y.U::c": "passed"}, "args": []}
        run = {"outcome": {"test_x.T::a": "failure", "test_x.T::new": "passed"}, "args": ["test_x.py"], "whole": ["test_x"],
               "full": False}
        self.assertEqual(tddloop._next_head(prev, run),
                         {"outcome": {"test_x.T::a": "failure", "test_x.T::new": "passed", "test_y.U::c": "passed"},
                          "args": None, "whole": [], "full": False})
        full = {**run, "full": True, "whole": []}
        self.assertEqual(tddloop._next_head(prev, full), full, "一式の回はそのまま次の単位の頭")

    def test_scope_limits_modules(self):
        now = {}
        self.assertEqual(tddloop._vanished(self.HEAD, [self.HEAD], now, [], {"test_y"}, []), [("test_y.U::test_c", "missing")])

    def test_scope_of_touched_files(self):
        self.assertEqual(tddloop._vanish_scope(["a/test_y.py", "stats.py", "b/x_test.py"]), {"test_y", "x_test"})
        self.assertIsNone(tddloop._vanish_scope(["test_y.py", "tests/conftest.py"]), "conftest.py に触れたら一式")

    def test_vanish_scope_non_python_is_whole(self):
        # .py でないテストのファイルは JUnit の行とモジュールを言語に依らず結べない——分からない＝一式の全部を照らす
        self.assertIsNone(tddloop._vanish_scope(["a/test_y.py", "pkg/calc_test.go"]))


class TestTestFileIdentity(unittest.TestCase):
    """テストのファイルの見分け: 宣言（単位の申告・約束の tests と rewrites のパス）を正本に、名の慣習（impact.is_test）を予備に"""

    def test_declared_test_files_from_state(self):
        st = {"units": {"u1": {"test_files": ["a/checks.go"]}, "u2": {}},
              "contract": {"u1": {"tests": [{"id": "b/verify.kt::Verify::adds"}], "rewrites": ["./c/legacy.rb::old"]},
                           "u2": None}}
        self.assertEqual(tddloop.declared_test_files(st), {"a/checks.go", "b/verify.kt", "c/legacy.rb"})

    def test_declared_test_file_counts(self):
        self.assertTrue(tddloop.is_test_file("checks/verify.py", {"checks/verify.py"}), "慣習に当たらない名も宣言なら")
        self.assertFalse(tddloop.is_test_file("checks/verify.py", set()))
        for path in ("test_stats.py", "x_test.py", "conftest.py", "pkg/calc_test.go", "src/test/java/FooTest.java"):
            with self.subTest(path=path):
                self.assertTrue(tddloop.is_test_file(path, set()))
        self.assertFalse(tddloop.is_test_file("stats.py", set()))


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


SAME_ITEM_TESTS = [{"id": MEAN_ID, "red_kind": "assertion"}, {"id": "test_stats.py::TestStats::test_clamp_far_above",
                                                              "red_kind": "assertion"}]
SAME_ITEM_FAR = """
    def test_clamp_far_above(self):
        self.assertEqual(clamp(20, 0, 10), 10)
"""


class TestOneItemTwoUnits(ContractCase):
    """修正案の 1 つの項目に 2 つの単位（MEAN・CLAMP）が載り、項目の受け入れのテスト 2 本が両方の単位の約束に在る（canary の run
    245042a7・4c32bf37 の形）。前の単位の段は項目の受け入れのテストを全部名指して緑にするので、同じ項目の後の単位を「今は直すな」
    と言わず、一緒に直させる。後の単位は受け入れのテストを輪が確かめ済みなので、機械が段を回さずに閉じる（食い違いの申し出を
    生まない）"""
    CONTRACT = {MEAN: {"items": [1], "route": "tdd", "rewrites": [], "refactor": [], "tests": SAME_ITEM_TESTS},
                CLAMP: {"items": [1], "route": "tdd", "rewrites": [], "refactor": [], "tests": SAME_ITEM_TESTS}}
    BRIEFS = [{"item": 1, "unit_keys": [MEAN, CLAMP], "file": "/b/r1/brief-1.md", "sha256": "a" * 64}]

    def route_both(self):
        got = self.step({"phase": "route", "units": [{"unit_key": MEAN, "route": "tdd"}, {"unit_key": CLAMP, "route": "tdd"}]})
        self.assertTrue(got["ok"], got)

    def prompt(self):
        with mock.patch.object(tddloop.planbrief, "cut_at", return_value=self.BRIEFS):
            return pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")

    def test_step_does_not_hold_off_unit_of_same_item(self):
        self.route_both()
        prompt = self.prompt()
        row = next(ln for ln in prompt[prompt.index(planbrief.HEAD):].splitlines() if ln.startswith("- 項目 1:"))
        self.assertIn(f"単位 {MEAN}、{CLAMP}", row)
        self.assertNotIn(planbrief.NOT_NOW, row, "同じ項目の単位に「今は直すな」と言わない")
        self.assertNotIn("今は手を付けるな", prompt, "同じ項目の後の単位を「この後の単位」に並べない")
        self.assertIn(tddloop.TOGETHER_HEAD, prompt)
        self.assertIn(CLAMP, prompt.split(tddloop.TOGETHER_HEAD, 1)[1].split("\n## ", 1)[0])

    def test_one_item_two_units_files_no_conflict(self):
        self.route_both()
        self.add_test(NEW_TEST + SAME_ITEM_FAR)
        got = self.step({"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"],
                         "tests": [t["id"] for t in SAME_ITEM_TESTS]})
        self.assertTrue(got["ok"], got)
        self.edit("stats.py", "return sum(xs) / (len(xs) - 1)", "return sum(xs) / len(xs)")
        self.edit("stats.py", "    if x > hi:\n        return lo", "    if x > hi:\n        return hi")
        got = self.step({"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母と上限の枝を項目どおりに直した"})
        self.assertTrue(got["ok"], got)
        self.assertEqual((got["done"], got["conflict"]), (True, None), "同じ項目の後の単位は機械が閉じ、輪は済む")
        st = self.st()
        self.assertEqual(st["parked"], [])
        self.assertNotIn("conflict", [c["phase"] for c in st["calls"]])
        self.assertEqual([c["unit_key"] for c in st["calls"] if c["phase"] != "route"], [MEAN, MEAN], "CLAMP の段は回らない")
        rows = {u["unit_key"]: u for u in tddloop.exit_fields(self.start)["units"]}
        c = rows[CLAMP]
        self.assertEqual((c["route"], c["red"], c["green"], c["gave_up"]), ("tdd", "ok", "ok", ""))
        self.assertEqual(sorted(c["tests"]), sorted(t["id"] for t in SAME_ITEM_TESTS))
        self.assertIn(MEAN, c["why"], "どの単位の段で一緒に直したかを残す")
        self.assertEqual(st["units"][CLAMP]["covered_by"], [MEAN])
        summary = pathlib.Path(self.start["summary_file"]).read_text(encoding="utf-8")
        done = summary.split("## 輪で直した単位", 1)[1].split("\n## ", 1)[0]
        self.assertIn(f"- {CLAMP}", done, "閉じた単位は輪で直した単位に並ぶ（direct に並べない）")
        self.assertEqual(tddloop.frozen_problems(self.state, self.repo), [])

    def test_later_unit_is_not_closed_when_its_tests_are_not_verified(self):
        """前の単位が申し出で止まれば（受け入れのテストを確かめていない）、後の単位は今どおり自分の段を回す"""
        self.route_both()
        got = self.step({"phase": "conflict", "unit_key": MEAN, "between": ["stats.py:9", "test_stats.py:9"],
                         "why_both_cannot_hold": "期待値と依頼の分母が食い違い、どちらを正とするか決められない",
                         "which_is_right": "unknown", "kind": "needs_context"})
        self.assertTrue(got["ok"], got)
        st = self.st()
        self.assertEqual((st["phase"], st["queue"][st["cur"]]), ("test", CLAMP))
        self.assertFalse(st["units"][CLAMP].get("covered_by"))


class TestTwoItemsKeepHoldOff(ContractCase):
    """別の項目の単位は今どおり「この後の単位（今は手を付けるな）」に並び、機械は閉じない（単位ごとの赤→緑の順を保つ）"""
    CONTRACT = {MEAN: {"items": [1], "route": "tdd", "rewrites": [], "refactor": [], "tests": SAME_ITEM_TESTS[:1]},
                CLAMP: {"items": [2], "route": "tdd", "rewrites": [], "refactor": [], "tests": SAME_ITEM_TESTS[1:]}}
    BRIEFS = [{"item": 1, "unit_keys": [MEAN], "file": "/b/r1/brief-1.md", "sha256": "a" * 64},
              {"item": 2, "unit_keys": [CLAMP], "file": "/b/r1/brief-2.md", "sha256": "b" * 64}]
    route_both, prompt = TestOneItemTwoUnits.route_both, TestOneItemTwoUnits.prompt

    def test_unit_of_other_item_is_held_off(self):
        self.route_both()
        prompt = self.prompt()
        self.assertIn(f"この後の tdd の単位（今は手を付けるな）: {CLAMP}", prompt)
        self.assertNotIn(tddloop.TOGETHER_HEAD, prompt)
        self.assertNotIn("brief-2.md", prompt)
        self.red()
        got = self.fix_mean()
        self.assertFalse(got["done"])
        st = self.st()
        self.assertEqual((st["phase"], st["queue"][st["cur"]]), ("test", CLAMP), "別の項目の単位は自分の段を回す")
        self.assertFalse(st["units"][CLAMP].get("covered_by"))


class TestSharedItemPartlyCovered(ContractCase):
    """後の単位が前の単位に無い項目にも載るなら、一緒に直す単位にせず（今どおり「今は手を付けるな」）、機械も閉じない
    （残りの項目の受け入れのテストを自分の段で赤→緑にする。一緒に直させると後の単位の赤が書けなくなる）"""
    CONTRACT = {MEAN: {"items": [1], "route": "tdd", "rewrites": [], "refactor": [], "tests": SAME_ITEM_TESTS[:1]},
                CLAMP: {"items": [1, 2], "route": "tdd", "rewrites": [], "refactor": [], "tests": SAME_ITEM_TESTS}}
    route_both = TestOneItemTwoUnits.route_both

    def test_partly_covered_unit_runs_its_own_step(self):
        self.route_both()
        self.assertEqual(tddloop.together(self.st(), MEAN), [])
        self.red()
        got = self.fix_mean()
        self.assertFalse(got["done"])
        st = self.st()
        self.assertEqual((st["phase"], st["queue"][st["cur"]]), ("test", CLAMP))
        self.assertFalse(st["units"][CLAMP].get("covered_by"))


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

    def test_kind_rule_declared_file_names(self):
        """adds の名が .py のファイルの名・パス（新しいモジュール）なら、宣言した名前はモジュールの名（拡張子でない。依頼 194c で
        receivers.py が 'py' と比べられ、宣言した赤が数えられなかった）。パッケージの __init__.py はディレクトリの名。<パス>::<名前> は
        :: の後の名前。綴りの誤り（宣言の外の名前）の拒みは残る"""
        def probs(declared, msg):
            case = {"classname": "test_stats.TestStats", "name": "test_mean_of_two", "outcome": "failure",
                    "fail_type": "", "fail_message": msg}
            return tddloop._kind_problems([{"id": MEAN_ID, "red_kind": "assertion"}], [case], declared)
        mod = ("ModuleNotFoundError: No module named 'receivers'", "ModuleNotFoundError: No module named 'app.receivers'",
               "ImportError: cannot import name 'receivers' from 'app' (/tmp/app/__init__.py)")
        for msg in mod:
            for d in ("receivers.py", "app/receivers.py", "app/receivers/__init__.py"):
                self.assertEqual(probs([d], msg), [], (d, msg))
            self.assertEqual(len(probs(["recievers.py"], msg)), 1, msg)                 # 綴りの違うファイルの名は当たらない
            self.assertEqual(len(probs(["app/receivers.py::handle"], msg)), 1, msg)     # :: の後の名前だけを宣言する
            self.assertEqual(len(probs(["docs/receivers.md"], msg)), 1, msg)            # .py でないパスはモジュールを宣言しない
        handle = "ImportError: cannot import name 'handle' from 'app.receivers' (/tmp/app/receivers.py)"
        for d in ("app/receivers.py::handle", "receivers.py::handle", "app/receivers.py::Receiver.handle", "receivers.handle"):
            self.assertEqual(probs([d], handle), [], d)
        self.assertEqual(len(probs(["receivers.py"], handle)), 1)                      # モジュールの宣言は中の名前を宣言しない
        self.assertEqual(len(probs(["receivers.py"], "ModuleNotFoundError: No module named 'py'")), 1)   # 拡張子と比べない

    def test_kind_rule_new_module_of_canonical(self):
        """修正案の項目の adds が関数の名だけを書き、新しいモジュールを canonical の『<パス>.py（新設…）』で名指した形（依頼 194c の
        nodeio.py）: 欄の控え（planmarks.split）から単位の約束の names を通すと、そのモジュールの import の失敗は宣言の赤。在る
        ファイルに新設の関数を足す行はモジュールを宣言せず、綴りの違うモジュールは今どおり拒む"""
        adds = [{"kind": "function", "name": "read_input", "canonical": "works/.shared/core/nodeio.py（新設。前の節の出力を読む口）"},
                {"kind": "function", "name": "current_round", "canonical": "stats.py（新設。盤面の今の周を返す）"}]
        with tempfile.TemporaryDirectory() as td:
            (pathlib.Path(td) / "stats.py").write_text("", encoding="utf-8")
            _, fields = planmarks.split({"plan": [{"unit_keys": ["u"], "adds": adds}]}, pathlib.Path(td))
        names = planmarks.unit_contract(fields, "u")["names"]

        def probs(msg):
            case = {"classname": "test_stats.TestStats", "name": "test_mean_of_two", "outcome": "failure",
                    "fail_type": "", "fail_message": msg}
            return tddloop._kind_problems([{"id": MEAN_ID, "red_kind": "assertion"}], [case], names)
        self.assertEqual(probs("ModuleNotFoundError: No module named 'works.shared.core.nodeio'"), [])
        self.assertEqual(probs("ImportError: cannot import name 'read_input' from 'nodeio'"), [])
        self.assertEqual(len(probs("ModuleNotFoundError: No module named 'nodeoi'")), 1)
        self.assertEqual(len(probs("ModuleNotFoundError: No module named 'stats'")), 1)

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

    def restart(self, cmd, unit_depths=""):
        (self.repo / "lint.py").write_text(LINT, encoding="utf-8")
        git(self.repo, "add", "lint.py")
        git(self.repo, "commit", "-qm", "lint")
        self.start = tddloop.start(self.board, self.repo, str(self.suite), OPEN, test_cmd=cmd, unit_depths=unit_depths)
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

    def test_light_unit_does_not_run_test_cmd_after_green(self):
        # 軽量の単位は緑の後の test_cmd を走らせない（同じコマンドを線の最後のテストが木の全部で走らせる）。赤・緑の確かめは今どおり
        self.restart(self.lint(), unit_depths=json.dumps({MEAN: "軽量", CLAMP: "標準"}))
        self.assertEqual(self.st()["test_cmd_gate"], tddloop.GATE_ON)
        self.route()
        self.red()
        runs = self.st()["runs"]
        prompt = pathlib.Path(self.step_prompt()).read_text(encoding="utf-8")
        self.assertNotIn("緑の後に機械が run の test_cmd", prompt)
        self.edit("stats.py", "return sum(xs) / (len(xs) - 1)", "print('debug')\n    return sum(xs) / len(xs)")
        got = self.step({"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母を直した"})
        self.assertTrue(got["ok"], got)
        self.assertEqual(self.st()["runs"], runs + 1, "一式の緑の 1 回だけで、test_cmd は走らせない")
        self.assertEqual(self.st()["units"][MEAN]["test_cmd"], tddloop.CMD_LIGHT)

    def standard_mean_rejected(self, depths):
        self.restart(self.lint(), unit_depths=depths)
        self.route()
        self.red()
        self.edit("stats.py", "return sum(xs) / (len(xs) - 1)", "print('debug')\n    return sum(xs) / len(xs)")
        got = self.step({"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母を直した"})
        self.assertFalse(got["ok"])
        self.assertIn("test_cmd", got["reason"])

    def test_unit_named_standard_runs_test_cmd(self):
        self.standard_mean_rejected(json.dumps({MEAN: "標準"}))

    def test_unit_not_named_runs_test_cmd(self):
        self.standard_mean_rejected(json.dumps({CLAMP: "軽量"}))

    def test_unit_depths_of_wrong_shape_is_broken(self):
        for raw in ("{", "[]", json.dumps({MEAN: 1})):
            with self.subTest(raw=raw), self.assertRaises(tddloop.Broken):
                tddloop.start(self.board, self.repo, str(self.suite), OPEN, unit_depths=raw)

    def step_prompt(self):
        return tddloop.prep(self.state)["prompt_file"]

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
        self.assertEqual(tddloop.frozen_problems(self.state, self.repo), [],
                         "tdd-1 の関数を変えずに足しただけは since が無くても凍結に数えない（依頼 195i の 2）")
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


class TestShapeless(LoopCase):
    """修正の形は g3 だけ（2026-10-09）: 輪の頭はいつも修正案の約束を読み、test_cmd の関門を決め、申告の無い単位は整えを飛ばす"""

    def test_contract_reads_the_fields(self):
        """盤面と欄の控えが在れば約束を組む"""
        (self.board / "state.json").write_text("{}", encoding="utf-8")
        fields = [{"unit_keys": [MEAN], "route": "tdd", "route_why": "", "rewrite_tests": [],
                   "tests": [{"id": "test_stats.py::TestStats::test_mean_of_two", "behavior": "2 つの値の平均",
                              "path": "stats.mean を直に呼ぶ", "red_kind": "assertion", "red_why": "今は len-1 で割る"}],
                   "refactor": {"declared": False, "why": ""}}]
        with mock.patch.object(tddloop.entry, "open_board"), \
                mock.patch.object(tddloop.conflict, "fix_duty", return_value=([MEAN, CLAMP], {})), \
                mock.patch.object(tddloop.conflict, "frozen_fields", return_value=fields):
            self.restart()
            self.assertEqual(list(self.st()["contract"]), [MEAN])
        self.assertNotIn("plain", self.st())

    def test_green_test_cmd_gate_is_on_and_refactor_needs_a_declaration(self):
        """緑の test_cmd は関門 on。申告の無い単位は整えを飛ばす"""
        self.restart(test_cmd=f"{sys.executable} -c pass")
        self.assertEqual(self.st()["test_cmd_gate"], tddloop.GATE_ON)
        self.route()
        self.red()
        fix = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(tddloop.DO["fix"], fix)
        self.assertTrue(self.fix_mean()["done"])
        self.assertEqual(self.st()["units"][MEAN]["refactor"], "skipped")


class TestResume(LoopCase):
    """Archon の resume（v0.11.1）は済みと記録していない輪を 1 周目から回し直す。確かめの節が状態に「済んだ」（か段 lanes）を保存した後、
    Archon が輪の済みを記録する前に止まった run の resume でも、支度は役を起こさずに go: false を返し、確かめは返答 null で何も
    動かさずに輪を抜ける（並べの枝の輪と同じ形。docs/plans/2026-10-07-lane-nodes.md の 4 の resume の項）"""

    def done_loop(self):
        self.route()
        self.red()
        self.assertTrue(self.fix_mean()["done"])

    def snap(self):
        return (pathlib.Path(self.state).read_bytes(),
                {n: (self.repo / n).read_bytes() for n in ("stats.py", "test_stats.py")})

    def test_running_loop_prep_says_go(self):
        self.route()
        got = tddloop.prep(self.state)
        self.assertIs(got["go"], True)
        self.assertTrue(pathlib.Path(got["prompt_file"]).is_file())

    def test_done_loop_ends_without_the_role(self):
        self.done_loop()
        before = self.snap()
        self.assertEqual(tddloop.prep(self.state), {"prompt_file": "", "go": False})
        got = self.step(None)
        self.assertEqual((got["ok"], got["done"], got["phase"], got["reason"]), (True, True, "done", ""), got)
        self.assertEqual(self.snap(), before, "済んだ輪の周は状態と作業ツリーを動かさない")

    def test_reply_for_a_done_loop_is_still_refused(self):
        self.done_loop()
        with self.assertRaises(tddloop.Broken):
            self.step({"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "x"})

    def test_missing_reply_in_a_running_loop_is_refused(self):
        """役が返さなかった周（済んでいない輪）は今どおり拒否に数える（役を飛ばしたのと取り違えない）"""
        self.route()
        got = self.step(None)
        self.assertFalse(got["ok"])
        self.assertEqual(self.st()["tries"], 1)

    def test_scripts_on_resume(self):
        """Archon が resume で起こす形: 役が飛ばされた確かめは reply が null か空"""
        self.done_loop()
        before = self.snap()
        env = {"ARTIFACTS_DIR": str(self.board.parent), "INPUTS_STATE_FILE": self.state, "INPUTS_JUDGMENT_FILE": "",
               "INPUTS_PLAN_FILE": "", "INPUTS_POLICY_PATH": "", "INPUTS_NOTES_FILE": ""}
        code, out, err = run_script("tdd_prep", self.repo, env)
        self.assertEqual((code, json.loads(out or "{}")), (0, {"prompt_file": "", "go": False}), err)
        for reply in ("null", ""):
            code, out, err = run_script("tdd_step", self.repo, {"ARTIFACTS_DIR": str(self.board.parent),
                                                                "INPUTS_STATE_FILE": self.state, "INPUTS_REPLY": reply})
            self.assertEqual(code, 0, err)
            self.assertEqual({k: v for k, v in json.loads(out).items() if k != "reason_file"},
                             {"ok": True, "done": True, "reason": "", "phase": "done"})
        self.assertEqual(self.snap(), before)


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
