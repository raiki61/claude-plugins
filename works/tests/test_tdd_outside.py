"""TDD の輪の赤緑と受け付けが、実行器の段の一覧の外（heavy）に在る試験を一式の結末に載せるかの検査。

小さな実行器（試験の中の RUNNER）は dev/tdd-suite.sh と同じ約束で動く: 第 1 引数に JUnit の書き先、既定の一覧（TIER）は
いつも集め、後ろの位置引数（ファイルか node id）は集める先に足し、-k は集めた中を名前で絞る。段の外の試験は、輪か受け付けが
後ろの引数で足さない限り走らない。
- 赤緑: 段の外のファイルに書いた名指しのテストが、赤（failure）として受かり、直した後に緑として受かる
- 受け付け: 段の外の変えた試験が走り、版で通っていた試験の新しい赤を赤にする。選んだ試験が 0 件なら「新しい赤なし」にしない
種の git は gitkit の型の写し（盤面なし。実行器は python を子で起こすだけ）。
"""
import json
import pathlib
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent
SEED = ROOT / "dev" / "target-seed"
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "blk-fix" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))

from gitkit import committed_copy, git  # noqa: E402
import tddloop  # noqa: E402

MEAN = "stats.py mean: 分母が len(xs) - 1 になっている"
OUTSIDE = "heavy/test_outside.py"   # 実行器の既定の一覧（TIER）に無い置き場
NAMED = f"{OUTSIDE}::TestOutside::test_mean_of_two"

RUNNER = '''
import importlib.util, pathlib, sys, unittest, xml.etree.ElementTree as ET
sys.dont_write_bytecode = True
sys.path.insert(0, ".")
TIER = ["test_stats.py"]
out, rest = sys.argv[1], sys.argv[2:]
words, targets, i = None, list(TIER), 0
while i < len(rest):
    if rest[i] == "-k":
        words = [w.strip() for w in rest[i + 1].split(" or ") if w.strip()]
        i += 2
        continue
    targets.append(rest[i])
    i += 1
rows, seen = [], set()
for target in targets:
    path, _, sel = target.partition("::")
    p = pathlib.Path(path)
    spec = importlib.util.spec_from_file_location(p.stem, str(p))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    def flat(s):
        for t in s:
            yield from (flat(t) if isinstance(t, unittest.TestSuite) else [t])
    for t in flat(unittest.defaultTestLoader.loadTestsFromModule(mod)):
        tid = t.id()
        if sel and not tid.endswith("." + sel.replace("::", ".")):
            continue
        if words is not None and not any(w in tid for w in words):
            continue
        if tid in seen:
            continue
        seen.add(tid)
        r = unittest.TestResult()
        t.run(r)
        kind = "error" if r.errors else "failure" if r.failures else "skipped" if r.skipped else None
        rows.append((tid, kind))
root = ET.Element("testsuite")
for tid, kind in rows:
    cls, name = tid.rsplit(".", 1)
    tc = ET.SubElement(root, "testcase", classname=cls, name=name)
    if kind:
        ET.SubElement(tc, kind)
ET.ElementTree(root).write(out)
sys.exit(0 if all(k in (None, "skipped") for _, k in rows) else 1)
'''

EMPTY_RUNNER = '''
import sys
open(sys.argv[1], "w").write("<testsuite></testsuite>")
'''

OUTSIDE_TEST = '''import unittest

from stats import mean


class TestOutside(unittest.TestCase):
    def test_mean_of_two(self):
        self.assertEqual(mean([2, 4]), 3)
'''

OUTSIDE_PASSING = '''import unittest


class TestOutside(unittest.TestCase):
    def test_sum(self):
        self.assertEqual(1 + 1, 2)
'''


class OutsideCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)
        self.repo = self.tmp / "repo"
        committed_copy(self.repo, SEED)

    def begin(self, runner=RUNNER):
        suite = self.tmp / "suite.py"
        suite.write_text(runner, encoding="utf-8")
        got = tddloop.start(self.tmp / "art" / "board", self.repo, str(suite), json.dumps([MEAN], ensure_ascii=False))
        self.assertTrue(got["go"], got)
        return got["state_file"]

    def write(self, rel, text):
        p = self.repo / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")


class TestLoopOutsideTier(OutsideCase):
    def test_named_test_outside_tier_goes_red_then_green(self):
        state = self.begin()
        got = tddloop.step(state, {"phase": "route", "units": [{"unit_key": MEAN, "route": "tdd"}]}, self.repo)
        self.assertTrue(got["ok"], got)
        self.write(OUTSIDE, OUTSIDE_TEST)
        got = tddloop.step(state, {"phase": "test", "unit_key": MEAN, "test_files": [OUTSIDE], "tests": [NAMED]}, self.repo)
        self.assertTrue(got["ok"], f"段の外のファイルの名指しが赤として受からない: {got['reason']}")
        p = self.repo / "stats.py"
        p.write_text(p.read_text(encoding="utf-8").replace("(len(xs) - 1)", "len(xs)"), encoding="utf-8")
        got = tddloop.step(state, {"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母を len(xs) にした"},
                           self.repo)
        self.assertTrue(got["ok"], f"段の外のファイルの名指しが緑として受からない: {got['reason']}")


class TestAcceptOutsideTier(OutsideCase):
    def test_changed_test_outside_tier_is_run_and_new_red_is_caught(self):
        self.write(OUTSIDE, OUTSIDE_PASSING)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "段の外の試験")
        state = self.begin()
        self.write(OUTSIDE, OUTSIDE_PASSING.replace("1 + 1, 2", "1 + 1, 3"))
        probs, note = tddloop.selected_problems(state, self.repo, "HEAD")
        self.assertTrue(probs, f"版で通っていた段の外の試験の赤を受け付けが拾わない（知らせ: {note}）")
        self.assertEqual(len(probs), 1, "行はテストのファイルごと")
        self.assertIn("test_sum", probs[0])
        self.assertIn(f"（ファイル {OUTSIDE}）", probs[0], "行は段の外のテストのファイルのパスを名指す")
        self.assertEqual(git(self.repo, "diff", "--name-only"), OUTSIDE, "比べた後も作業ツリーは直した後の姿のまま")

    def test_zero_selected_cases_are_not_reported_as_no_new_red(self):
        state = self.begin(EMPTY_RUNNER)
        p = self.repo / "stats.py"
        p.write_text(p.read_text(encoding="utf-8").replace("(len(xs) - 1)", "len(xs)"), encoding="utf-8")
        probs, note = tddloop.selected_problems(state, self.repo, "HEAD")
        self.assertNotIn("新しい赤なし", note, "選んだ試験が 1 件も走らないのを緑に見せる（fail-open）")
        self.assertIn("0 件", " ".join(probs) + note)

    def test_unchanged_test_outside_tier_is_left_out_of_local_run(self):
        # ADR 0071 の 3 の 1: 手元は速い段と変えた・足した試験だけ。届いただけで変えていない段の外の試験は走らせない
        self.write(OUTSIDE, OUTSIDE_TEST)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "段の外の試験（stats に届く）")
        argv_log = self.tmp / "argv.jsonl"
        state = self.begin("import json, sys\nopen(%r, 'a').write(json.dumps(sys.argv[1:]) + '\\n')\n" % str(argv_log)
                           + RUNNER)
        p = self.repo / "stats.py"
        p.write_text(p.read_text(encoding="utf-8").replace("(len(xs) - 1)", "len(xs)"), encoding="utf-8")
        tddloop.selected_problems(state, self.repo, "HEAD")
        runs = [json.loads(line) for line in argv_log.read_text(encoding="utf-8").splitlines()][1:]   # 頭は元の結末の回
        self.assertTrue(runs, "受け付けが実行器を走らせていない")
        for argv in runs:
            self.assertFalse([a for a in argv if a.endswith(OUTSIDE)],
                             f"変えていない段の外の試験のファイルを受け付けが実行器の後ろに足した: {argv}")

    def test_tests_left_out_are_named_as_left_to_ci(self):
        # 手元で回さなかった試験は黙って減らさず、知らせと状態のファイルに『手元で回さなかった』として名前で残す
        self.write(OUTSIDE, OUTSIDE_TEST)
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "段の外の試験（stats に届く）")
        state = self.begin()
        p = self.repo / "stats.py"
        p.write_text(p.read_text(encoding="utf-8").replace("(len(xs) - 1)", "len(xs)"), encoding="utf-8")
        probs, note = tddloop.selected_problems(state, self.repo, "HEAD")
        self.assertEqual(probs, [], note)
        self.assertIn("手元で回さなかった", note)
        self.assertIn(OUTSIDE, note)
        self.assertNotIn("test_stats.py", note.split("手元で回さなかった", 1)[1], "手元で走った試験を回さなかったと言う")
        self.assertEqual(tddloop.load_state(state).get("ci_left"), [OUTSIDE])

    def test_accept_args_name_only_pytest_modules(self):
        # impact がテストと呼ぶ物のうち、pytest の試験のモジュールでない物（conftest・実行器の台本・シェルの試験）は足さない
        names = ["t/test_a.py", "t/b_test.py", "t/conftest.py", "t/run-suite.py", "t/x-case.py", "t/y.bats", "t/gone_test.py"]
        for n in names[:-1]:
            self.write(n, "")
        self.assertEqual(tddloop._args(self.repo, names, "a or b"),
                         [str(self.repo.absolute() / "t/test_a.py"), str(self.repo.absolute() / "t/b_test.py"), "-k", "a or b"])


if __name__ == "__main__":
    unittest.main()
