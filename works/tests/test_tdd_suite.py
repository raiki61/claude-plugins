"""TDD の実行器 dev/tdd-suite.sh（仕様 tdd-spec 6 節。ラインの入力 tdd_suite に渡す殻）の検査。

殻は JUnit XML の書き先を第 1 引数に受け、works の根で既製の pytest を走らせる（JUnit は pytest の --junitxml。自作しない）。
段は WORKS_TDD_TIER（既定 fast）で選び、段のファイルは tests/tiers.py の `paths` の口から引く（一覧を写さない）。

ここでは本物の works の試験一式は回さない。一時の根に殻の写しと、段の口だけを持つ偽の tests/tiers.py と、小さな偽の
試験を置いて回す（本物の uv と pytest を起こすので段は heavy）。書かれた XML は、写しの rules（.shared/core/graphloops/
rules/review-loop-tdd.py）の parse_junit で読む（写しが本線と同じかは test_core_verbatim・test_core_copy が縛る）。
"""
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE_SH = ROOT / "dev" / "tdd-suite.sh"
TDD_GRAPH = ROOT / ".shared" / "core" / "graphloops" / "graphs" / "review-loop-tdd.json"

sys.path.insert(0, str(TDD_GRAPH.parents[1]))
from engine.rules import load_rules  # noqa: E402
from engine.schema import load_graph  # noqa: E402

parse_junit = load_rules(str(TDD_GRAPH), load_graph(str(TDD_GRAPH))[0]).parse_junit


FAKE_TIERS = '''\
import sys
FILES = {"fast": ["tests/test_fake.py"], "heavy": ["tests/test_other.py"]}
if len(sys.argv) == 3 and sys.argv[1] == "paths" and sys.argv[2] in FILES:
    print("\\n".join(FILES[sys.argv[2]]))
    sys.exit(0)
print("tiers: 偽の段の口", file=sys.stderr)
sys.exit(2)
'''

FAKE_TEST = '''\
import unittest

from fakekit import VALUE   # tests/ の下の道具を import できる（unittest discover と同じ sys.path）


class FakeCase(unittest.TestCase):
    def test_pass(self):
        self.assertEqual(VALUE, 1)

    def test_fail(self):
        self.assertEqual(VALUE, 2)

    def test_error(self):
        raise RuntimeError("boom")

    @unittest.skip("飛ばす")
    def test_skip(self):
        pass
'''

OTHER_TEST = '''\
import unittest


class OtherCase(unittest.TestCase):
    def test_other(self):
        pass
'''


@unittest.skipIf(shutil.which("uv") is None, "SKIP uv: uv が無い（殻は uv run で pytest を起こす）")
class TddSuiteCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = pathlib.Path(self._tmp.name)
        self.root = tmp / "works"
        (self.root / "dev").mkdir(parents=True)
        (self.root / "tests").mkdir()
        shutil.copy2(SUITE_SH, self.root / "dev" / "tdd-suite.sh")
        shutil.copy2(ROOT / "tests" / "hermetic.sh", self.root / "tests" / "hermetic.sh")   # 殻が . で読む env の隔離
        (self.root / "tests" / "tiers.py").write_text(FAKE_TIERS, encoding="utf-8")
        (self.root / "tests" / "fakekit.py").write_text("VALUE = 1\n", encoding="utf-8")
        (self.root / "tests" / "test_fake.py").write_text(FAKE_TEST, encoding="utf-8")
        (self.root / "tests" / "test_other.py").write_text(OTHER_TEST, encoding="utf-8")
        self.caller = tmp / "caller"   # 呼ぶ側の cwd（works の根と別の所。本線の rules はリポジトリの根で起こす）
        self.caller.mkdir()
        self.env = {k: v for k, v in os.environ.items() if k not in ("WORKS_TDD_TIER", "PYTHONDONTWRITEBYTECODE")}

    def run_suite(self, out, *args, **env):
        e = dict(self.env)
        e.update(env)
        return subprocess.run(["sh", str(self.root / "dev" / "tdd-suite.sh"), str(out), *args], cwd=str(self.caller),
                              env=e, capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)

    def outcomes(self, out):
        return {c["name"]: (c["classname"], c["outcome"]) for c in parse_junit(pathlib.Path(out).read_text(encoding="utf-8"))}

    def test_default_fast_tier_writes_junit_that_parse_junit_reads(self):
        out = self.caller / "junit.xml"
        r = self.run_suite(out)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)   # 落ちた試験が在る（pytest の終了コード 1 をそのまま返す）
        got = self.outcomes(out)
        self.assertEqual({n: o for n, (_, o) in got.items()},
                         {"test_pass": "passed", "test_fail": "failure", "test_error": "failure", "test_skip": "skipped"})
        for name, (cls, _) in got.items():
            self.assertTrue(cls.endswith("test_fake.FakeCase"), (name, cls))

    def test_collection_error_does_not_hide_other_outcomes(self):
        # 読み込みで落ちるモジュール（赤の段で、まだ無い名前を一番外で import するテストなど）が 1 本在っても、一式を止めずに
        # 他の試験の結末も書く（止まると「元で通っていた他のテストは緑のまま」を確かめられない）。落ちたモジュールは error で載る
        (self.root / "tests" / "test_broken.py").write_text("from fakekit import MISSING  # noqa: F401\n", encoding="utf-8")
        (self.root / "tests" / "tiers.py").write_text(
            FAKE_TIERS.replace('["tests/test_fake.py"]', '["tests/test_broken.py", "tests/test_fake.py"]'), encoding="utf-8")
        out = self.caller / "junit.xml"
        r = self.run_suite(out)
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        got = {n: o for n, (_, o) in self.outcomes(out).items()}
        broken = [n for n in got if n.endswith("test_broken")]   # 読み込みの失敗の行は classname が空で、name がモジュールの名前
        self.assertEqual([got.pop(n) for n in broken], ["error"], got)
        self.assertEqual(got, {"test_pass": "passed", "test_fail": "failure", "test_error": "failure", "test_skip": "skipped"})

    def test_heavy_tier_by_env(self):
        out = self.caller / "junit.xml"
        r = self.run_suite(out, WORKS_TDD_TIER="heavy")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual({n: o for n, (_, o) in self.outcomes(out).items()}, {"test_other": "passed"})

    def test_extra_args_narrow_the_tier(self):
        out = self.caller / "junit.xml"
        r = self.run_suite(out, "-k", "test_pass")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual({n: o for n, (_, o) in self.outcomes(out).items()}, {"test_pass": "passed"})

    def test_relative_out_is_from_callers_cwd(self):
        r = self.run_suite("rel/junit.xml")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertTrue((self.caller / "rel" / "junit.xml").is_file())
        self.assertFalse((self.root / "rel").exists())

    def test_leaves_no_cache_or_bytecode_in_works(self):
        self.run_suite(self.caller / "junit.xml")
        left = sorted(str(p.relative_to(self.root)) for p in self.root.rglob("*")
                      if p.name in ("__pycache__", ".pytest_cache") or p.suffix == ".pyc")
        self.assertEqual(left, [])

    def test_unknown_tier_and_missing_out_exit_2_with_one_line(self):
        for args, env in (((self.caller / "junit.xml",), {"WORKS_TDD_TIER": "slow"}), (("",), {})):
            with self.subTest(env=env):
                r = self.run_suite(*args, **env)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertFalse((self.caller / "junit.xml").exists())

    def test_bad_tier_list_stops_before_pytest(self):
        (self.root / "tests" / "tiers.py").write_text("import sys\nprint('tiers: 段の一覧が崩れた', file=sys.stderr)\n"
                                                        "sys.exit(2)\n", encoding="utf-8")
        out = self.caller / "junit.xml"
        r = self.run_suite(out)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("段の一覧が崩れた", r.stderr)
        self.assertFalse(out.exists())


class TddSuiteStaticCase(unittest.TestCase):
    def test_script_is_posix_sh(self):
        dash = shutil.which("dash")
        if dash is None:
            self.skipTest("SKIP dash: dash が無い")
        self.assertEqual(subprocess.run([dash, "-n", str(SUITE_SH)], capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
