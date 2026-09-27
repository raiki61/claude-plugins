"""テストの段（tests/tiers.py の FAST・HEAVY）と、段を選ぶ入口 run.sh（WORKS_TESTS）の検査。

- 段の一覧: fast と heavy は重ならず、合わせると discover が拾う全部のモジュール。どのモジュールも明示で
  どちらかに書く（書き忘れた新しいモジュールは名前を挙げて赤。重いテストが黙って fast に入らない）
- 段の読み込み（TierLoader）: 段ごとの discover のテストを合わせると、ちょうど全部の discover のテスト
- run.sh: 既定は全部を従来の discover で、fast・heavy は tiers.py で回し、unittest の引数（-k など）をそのまま渡す。
  知らない値は 1 行で終了コード 2。全部と heavy は枠の台本（WORKS_TESTSLOT）を TESTSLOT_N=4 で通し、fast は通さない。
  台本が無い・枠の置き場に書けないときは 1 行出して枠なしで回し、祖先が枠を持っていれば取り直さない。
  uv と枠の台本は偽物に差し替える（本物のテスト一式は回さない）
"""
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

import tiers

TESTS = pathlib.Path(__file__).resolve().parent
RUN_SH = TESTS / "run.sh"

FAKE_UV = """#!/bin/sh
echo "uv DWB=${PYTHONDONTWRITEBYTECODE-} cwd=$(pwd) $*" >> "$FAKE_LOG"
exit "${FAKE_UV_RC:-0}"
"""

# 本物と同じ形（隣の testslots/slot-1 に自分の pid を置いてからコマンドを回す）の偽物
FAKE_SLOT = """#!/bin/sh
d="$(dirname "$0")/testslots/slot-1"
mkdir -p "$d" && echo $$ > "$d/pid"
echo "slot N=${TESTSLOT_N-} $*" >> "$FAKE_LOG"
"$@"
rc=$?
rm -f "$d/pid"; rmdir "$d"
exit $rc
"""

UV_ARGS = "run --no-project --with pyyaml python3"


def test_ids(suite):
    out = set()
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            out |= test_ids(t)
        else:
            out.add(t.id())
    return out


class TierListCase(unittest.TestCase):
    def test_modules_found(self):
        # 数え間違いで空の集合を見て緑にならないように
        self.assertGreaterEqual(len(tiers.modules()), 10)
        self.assertIn("test_tiers", tiers.modules())

    def test_every_module_classified_once(self):
        found = set(tiers.modules())
        self.assertEqual(sorted(found - tiers.FAST - tiers.HEAVY), [], "段の一覧に無いモジュール（tiers.py に足す）")
        self.assertEqual(sorted(tiers.FAST & tiers.HEAVY), [])
        self.assertEqual(sorted((tiers.FAST | tiers.HEAVY) - found), [], "段の一覧に在るのにファイルが無い")
        self.assertEqual(tiers.problems(), [])

    def test_glob_matches_discover(self):
        # modules() の glob が discover の届く範囲と同じ（tests/ の下に package が在ると discover は潜る）
        self.assertEqual([p for p in TESTS.rglob("__init__.py")], [])
        mods = {tid.split(".")[0] for tid in test_ids(unittest.TestLoader().discover(str(TESTS), tiers.PATTERN))}
        self.assertEqual(mods - set(tiers.modules()), set())

    def test_problems_names_each_fault(self):
        with mock.patch.object(tiers, "modules", return_value=sorted(tiers.FAST | tiers.HEAVY | {"test_new"})):
            got = tiers.problems()
            self.assertEqual(len(got), 1)
            self.assertIn("test_new", got[0])
        with mock.patch.object(tiers, "HEAVY", tiers.HEAVY | {"test_tiers"}):
            self.assertIn("両方", " ".join(tiers.problems()))
        with mock.patch.object(tiers, "HEAVY", tiers.HEAVY | {"test_gone"}):
            got = " ".join(tiers.problems())
            self.assertIn("test_gone", got)
            self.assertIn("ファイルが無い", got)

    def test_loader_splits_discover_exactly(self):
        full = test_ids(unittest.TestLoader().discover(str(TESTS), tiers.PATTERN))
        fast = test_ids(tiers.TierLoader(tiers.FAST).discover(str(TESTS), tiers.PATTERN))
        heavy = test_ids(tiers.TierLoader(tiers.HEAVY).discover(str(TESTS), tiers.PATTERN))
        self.assertTrue(fast and heavy)
        self.assertEqual(fast & heavy, set())
        self.assertEqual(fast | heavy, full)
        self.assertEqual({t.split(".")[0] for t in fast} - tiers.FAST, set())
        self.assertEqual({t.split(".")[0] for t in heavy} - tiers.HEAVY, set())

    def test_main_refuses_unknown_tier_and_bad_list(self):
        with mock.patch("sys.stderr"):
            self.assertEqual(tiers.main(["tiers.py", "slow"]), 2)
            self.assertEqual(tiers.main(["tiers.py"]), 2)
        with mock.patch.object(tiers, "modules", return_value=sorted(tiers.FAST | tiers.HEAVY | {"test_new"})), \
                mock.patch("sys.stderr") as err:
            self.assertEqual(tiers.main(["tiers.py", "fast"]), 2)
            self.assertIn("test_new", "".join(c.args[0] for c in err.write.call_args_list))


class RunShCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = pathlib.Path(self._tmp.name)
        bin_ = tmp / "bin"
        bin_.mkdir()
        (bin_ / "uv").write_text(FAKE_UV)
        (bin_ / "uv").chmod(0o755)
        self.slot = tmp / "ops" / "testslot.sh"
        self.slot.parent.mkdir()
        self.slot.write_text(FAKE_SLOT)
        self.log = tmp / "log"
        self.env = {k: v for k, v in os.environ.items() if k not in ("WORKS_TESTS", "TESTSLOT_N")}
        self.env.update(PATH=f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}", FAKE_LOG=str(self.log),
                        WORKS_TESTSLOT=str(self.slot))

    def run_sh(self, *args, argv0=(), **env):
        e = dict(self.env)
        e.update(env)
        return subprocess.run([*argv0, "sh", str(RUN_SH), *args], env=e, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL, timeout=60)

    def calls(self):
        return self.log.read_text().splitlines() if self.log.exists() else []

    def assert_uv(self, line, tail):
        self.assertEqual(line, f"uv DWB=1 cwd={TESTS.parent} {UV_ARGS} {tail}")

    def test_unknown_value_exits_2_with_one_line(self):
        r = self.run_sh("-k", "x", WORKS_TESTS="slow")
        self.assertEqual(r.returncode, 2)
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertIn("slow", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_fast_skips_slot_and_passes_args(self):
        r = self.run_sh("-k", "yaml", WORKS_TESTS="fast")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stderr, "")
        calls = self.calls()
        self.assertEqual(len(calls), 1, calls)
        self.assert_uv(calls[0], "tests/tiers.py fast -k yaml")

    def test_heavy_takes_slot_with_n4(self):
        r = self.run_sh("-k", "fix", WORKS_TESTS="heavy")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 2, calls)
        self.assertTrue(calls[0].startswith(f"slot N=4 uv {UV_ARGS} tests/tiers.py heavy -k fix"), calls[0])
        self.assert_uv(calls[1], "tests/tiers.py heavy -k fix")

    def test_default_is_full_discover_through_slot(self):
        r = self.run_sh("-k", "x", TESTSLOT_N="9")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 2, calls)
        self.assertTrue(calls[0].startswith("slot N=4 "), calls[0])   # 呼ぶ側の TESTSLOT_N に関わらず 4
        self.assert_uv(calls[1], "-m unittest discover -s tests -p test_*.py -k x")

    def test_exit_code_passes_through(self):
        for tier in ("", "fast", "heavy"):
            with self.subTest(tier=tier):
                self.assertEqual(self.run_sh(WORKS_TESTS=tier, FAKE_UV_RC="7").returncode, 7)

    def test_missing_slot_script_runs_without_slot(self):
        r = self.run_sh(WORKS_TESTS="heavy", WORKS_TESTSLOT=str(self.slot.parent / "nope.sh"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertIn("nope.sh", r.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1, calls)
        self.assert_uv(calls[0], "tests/tiers.py heavy")

    @unittest.skipIf(os.geteuid() == 0, "root は書けない置き場を作れない")
    def test_unwritable_slot_dir_runs_without_slot(self):
        slots = self.slot.parent / "testslots"
        slots.mkdir()
        slots.chmod(0o500)
        self.addCleanup(slots.chmod, 0o700)
        r = self.run_sh()
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stderr.splitlines()), 1, r.stderr)
        self.assertIn("書けない", r.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 1, calls)
        self.assert_uv(calls[0], "-m unittest discover -s tests -p test_*.py")
        self.assertEqual(list(slots.iterdir()), [])   # 試しの跡を残さない

    def test_under_slot_holder_does_not_take_another(self):
        # 人が `bash testslot.sh sh works/tests/run.sh` と前に付けて打った形。2 枠目を待つと、枠が埋まった時に互いを待って止まる
        r = self.run_sh("-k", "x", argv0=("bash", str(self.slot)), WORKS_TESTS="heavy")
        self.assertEqual(r.returncode, 0, r.stderr)
        calls = self.calls()
        self.assertEqual(len(calls), 2, calls)
        self.assertTrue(calls[0].startswith("slot N="), calls[0])
        self.assert_uv(calls[1], "tests/tiers.py heavy -k x")
        self.assertFalse((self.slot.parent / "testslots" / "slot-1").exists())

    def test_script_is_posix_sh(self):
        dash = shutil.which("dash")
        if dash is None:
            self.skipTest("dash が無い")
        self.assertEqual(subprocess.run([dash, "-n", str(RUN_SH)], capture_output=True).returncode, 0)


if __name__ == "__main__":
    unittest.main()
