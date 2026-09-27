"""TDD の実行器 dev/tdd-suite.sh（仕様 tdd-spec 6 節。ラインの入力 tdd_suite に渡す殻）の検査。

殻は JUnit XML の書き先を第 1 引数に受け、works の根で既製の pytest を走らせる（JUnit は pytest の --junitxml。自作しない）。
段は WORKS_TDD_TIER（既定 fast）で選び、段のファイルは tests/tiers.py の `paths` の口から引く（一覧を写さない）。

ここでは本物の works の試験一式は回さない。一時の根に殻の写しと、段の口だけを持つ偽の tests/tiers.py と、小さな偽の
試験を置いて回す（本物の uv と pytest を起こすので段は heavy）。書かれた XML は、本線の rules（graphloops/rules/
review-loop-tdd.py、a1202d0）の parse_junit と同じ式で読む。写しがまだ works に無いので、下の parse_junit は本線の関数の
写し（test_parse_junit_matches_mainline が本線と同じ式かを縛る）。写しの rules を .shared/core に足したら、そちらを import
するように替え、ここの写しは消す。
"""
import ast
import os
import pathlib
import shutil
import subprocess
import tempfile
import textwrap
import unittest
import xml.etree.ElementTree as ET

ROOT = pathlib.Path(__file__).resolve().parents[1]
SUITE_SH = ROOT / "dev" / "tdd-suite.sh"
MAINLINE = "a1202d0"
MAINLINE_RULES = "graphloops/rules/review-loop-tdd.py"


def parse_junit(text):
    """JUnit XML → [{classname, name, outcome}]。outcome は passed / failure / error / skipped。読めなければ ET.ParseError"""
    root = ET.fromstring(text)
    cases = []
    for tc in root.iter("testcase"):
        kinds = [c.tag for c in tc if c.tag in ("failure", "error", "skipped")]
        outcome = "error" if "error" in kinds else "failure" if "failure" in kinds else "skipped" if "skipped" in kinds else "passed"
        cases.append({"classname": tc.get("classname") or "", "name": tc.get("name") or "", "outcome": outcome})
    return cases


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


@unittest.skipIf(shutil.which("uv") is None, "uv が無い（殻は uv run で pytest を起こす）")
class TddSuiteCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = pathlib.Path(self._tmp.name)
        self.root = tmp / "works"
        (self.root / "dev").mkdir(parents=True)
        (self.root / "tests").mkdir()
        shutil.copy2(SUITE_SH, self.root / "dev" / "tdd-suite.sh")
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
                              env=e, capture_output=True, text=True, stdin=subprocess.DEVNULL)

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
            self.skipTest("dash が無い")
        self.assertEqual(subprocess.run([dash, "-n", str(SUITE_SH)], capture_output=True).returncode, 0)

    def test_parse_junit_matches_mainline(self):
        """上の parse_junit は本線の rules の同名の関数と同じ式（写しを足すまでの控え。docstring を含めて AST で比べる）"""
        r = subprocess.run(["git", "-C", str(ROOT), "show", f"{MAINLINE}:{MAINLINE_RULES}"], capture_output=True)
        if r.returncode != 0:
            self.skipTest(f"このリポジトリから {MAINLINE}:{MAINLINE_RULES} を引けない: "
                          f"{r.stderr.decode('utf-8', 'replace').strip()[-200:]}")

        def fn(src):
            return next(ast.dump(n) for n in ast.parse(src).body if isinstance(n, ast.FunctionDef) and n.name == "parse_junit")
        here = textwrap.dedent(pathlib.Path(__file__).read_text(encoding="utf-8"))
        self.assertEqual(fn(here), fn(r.stdout.decode("utf-8")))


if __name__ == "__main__":
    unittest.main()
