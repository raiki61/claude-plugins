"""軽い自己点検（dev/selfcheck.py と腕の一覧 tests/mutations.json）の検査。

腕 1 本 = 柵 1 か所の故意の欠陥（file の中にちょうど 1 か所在る字列 old を new に置き換える）と、それを捕まえるはずの
名指しの試験 1 本（本流 tests/mutations.json の行の型。決定 C16）。実行器は pack を一時の置き場に写し、腕ごとに 1 か所壊して
その試験だけを tests/run.sh -k で回し、CAUGHT（その試験が FAIL）・NOT_CAUGHT・NOT_INJECTED（字列が無い＝古い腕）を出す。

ここでは本物の腕を撃たない（撃つのは `python3 dev/selfcheck.py`）。見るのは:
- --check: 今の版で、全部の腕の字列がちょうど 1 か所在り、名指しの試験が在る（毎回の速い段で古い腕を赤にする）
- 実行器の判定: 小さな偽の pack（柵 1 つと試験 2 本・unittest だけの run.sh）で、捕まる腕・捕まらない腕・字列の無い腕・
  壊さない写しで赤の試験を、それぞれ正しく名指しして終了コード 1 にする
- 写しの置き場が Claude Code の一時フォルダの下なら、dev/guard.sh の柵で何も写さずに 2 で止まる
"""
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"
SELFCHECK = DEV / "selfcheck.py"
sys.dont_write_bytecode = True
sys.path.insert(0, str(DEV))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
import linekit  # noqa: E402
import selfcheck  # noqa: E402

GUARD = '''def allowed(x):
    if x < 0:
        return False
    return True
'''

TESTS = '''import sys, pathlib, unittest
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from guard import allowed


class G(unittest.TestCase):
    def test_negative_refused(self):
        self.assertFalse(allowed(-1))

    def test_weak(self):
        allowed(-1)

    def test_positive_allowed(self):
        self.assertTrue(allowed(1))

    def test_reads_missing_result(self):
        seen = {} if allowed(-1) else {"refused": True}
        self.assertTrue(seen["refused"])   # 柵が効かないと、試験の本文の読みが KeyError で落ちる
'''

RUN_SH = '''#!/bin/sh
cd "$(dirname "$0")/.." || exit 2
exec python3 -m unittest discover -s tests -p 'test_*.py' "$@"
'''


def arm(aid, old, new, test):
    return {"id": aid, "title": f"腕 {aid}", "file": "guard.py", "old": old, "new": new,
            "tests": {"tests/test_g.py": [test]}}


class Fake(unittest.TestCase):
    """偽の pack（guard.py・tests/test_g.py・tests/run.sh・dev/guard.sh）と、写しの置き場 WORKS_DEV_HOME"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        tmp = pathlib.Path(self._tmp.name)
        self.pack = tmp / "pack"
        (self.pack / "tests").mkdir(parents=True)
        (self.pack / "dev").mkdir()
        (self.pack / "guard.py").write_text(GUARD, encoding="utf-8")
        (self.pack / "tests" / "test_g.py").write_text(TESTS, encoding="utf-8")
        (self.pack / "tests" / "run.sh").write_text(RUN_SH, encoding="utf-8")
        shutil.copy2(DEV / "guard.sh", self.pack / "dev" / "guard.sh")
        self.home = tmp / "dev-home"
        self.arms = tmp / "arms.json"

    def tearDown(self):
        self._tmp.cleanup()

    def write_arms(self, arms):
        self.arms.write_text(json.dumps({"about": "試験", "arms": arms, "dropped": []}, ensure_ascii=False), encoding="utf-8")

    def run_selfcheck(self, *args, home=None):
        env = dict(os.environ, WORKS_DEV_HOME=str(home or self.home), PYTHONDONTWRITEBYTECODE="1")
        env.pop("WORKS_TESTS", None)
        return subprocess.run([sys.executable, str(SELFCHECK), "--root", str(self.pack), "--arms", str(self.arms), *args],
                              capture_output=True, text=True, encoding="utf-8", env=env, check=False)


class RegistryCase(unittest.TestCase):
    def test_registry_is_current(self):
        """本物の腕の一覧: 字列がちょうど 1 か所・名指しの試験が在る・id が重ならない（古い腕はこの変更の中で赤）"""
        arms = selfcheck.load_arms(ROOT / "tests" / "mutations.json")
        self.assertEqual(selfcheck.check(ROOT, arms), [])
        self.assertGreaterEqual(len(arms), 10)

    def test_cli_check_runs_nothing(self):
        r = subprocess.run([sys.executable, str(SELFCHECK), "--check"], capture_output=True, text=True, encoding="utf-8",
                           env=dict(os.environ, PYTHONDONTWRITEBYTECODE="1"), check=False)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("SELFCHECK_CHECK_OK", r.stdout)


class CheckCase(Fake):
    def test_check_names_stale_arms(self):
        self.write_arms([arm("ok", "    if x < 0:", "    if False:", "G.test_negative_refused"),
                         arm("gone", "    if x < -5:", "    if False:", "G.test_negative_refused"),
                         arm("twice", "return", "pass", "G.test_negative_refused"),
                         arm("notest", "    if x < 0:", "    if False:", "G.test_missing"),
                         arm("prefix", "    if x < 0:", "    if False:", "G.test_negative")])
        probs = selfcheck.check(self.pack, selfcheck.load_arms(self.arms))
        text = "\n".join(probs)
        for aid in ("gone", "twice", "notest", "prefix"):
            self.assertIn(aid, text)
        self.assertNotIn("ok:", text)
        r = self.run_selfcheck("--check")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertFalse(self.home.exists(), "--check は写さない")

    def test_bad_registry_is_exit_2(self):
        self.arms.write_text('{"arms": [{"id": "x"}]}', encoding="utf-8")
        self.assertEqual(self.run_selfcheck("--check").returncode, 2)
        self.arms.write_text("{", encoding="utf-8")
        self.assertEqual(self.run_selfcheck().returncode, 2)


class RunCase(Fake):
    def test_statuses(self):
        self.write_arms([arm("caught", "    if x < 0:", "    if False:", "G.test_negative_refused"),
                         arm("weak", "    if x < 0:", "    if False:", "G.test_weak"),
                         arm("stale", "    if x < -5:", "    if False:", "G.test_negative_refused")])
        r = self.run_selfcheck()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(any(ln.startswith("CAUGHT caught") for ln in lines), r.stdout)
        self.assertTrue(any(ln.startswith("NOT_CAUGHT weak") for ln in lines), r.stdout)
        self.assertTrue(any(ln.startswith("NOT_INJECTED stale") for ln in lines), r.stdout)
        self.assertIn("caught=1/3", r.stdout)
        self.assertRegex(r.stdout, r"total=\d+(\.\d+)? 秒")
        self.assertEqual((self.pack / "guard.py").read_text(encoding="utf-8"), GUARD, "本物の pack は触らない")
        self.assertEqual(list(self.home.rglob("guard.py")), [], "写しは消す")

    def test_error_in_test_body_is_caught_but_not_in_pack_code(self):
        """例外（ERROR）で落ちた試験は、例外の出た一番奥の行が名指しの試験の本文なら CAUGHT（試験が結果を読んで柵の欠けを見た）、
        pack のコードの中なら NOT_CAUGHT（柵でなく土台が壊れた）"""
        self.write_arms([arm("body", "    if x < 0:", "    if False:", "G.test_reads_missing_result"),
                         arm("boom", "        return False", "        raise RuntimeError('土台')", "G.test_negative_refused")])
        r = self.run_selfcheck()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        lines = r.stdout.splitlines()
        self.assertTrue(any(ln.startswith("CAUGHT body") for ln in lines), r.stdout)
        self.assertTrue(any(ln.startswith("NOT_CAUGHT boom") and "例外" in ln for ln in lines), r.stdout)

    def test_all_caught_is_exit_0_and_only_filters(self):
        self.write_arms([arm("caught", "    if x < 0:", "    if False:", "G.test_negative_refused"),
                         arm("weak", "    if x < 0:", "    if False:", "G.test_weak")])
        r = self.run_selfcheck("--only", "caught")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("caught=1/1", r.stdout)
        self.assertNotIn("weak", r.stdout)

    def test_control_red_stops(self):
        """壊さない写しで名指しの試験が赤なら、腕を撃っても証拠にならないので CONTROL_RED で 1"""
        (self.pack / "guard.py").write_text(GUARD.replace("return False", "return True"), encoding="utf-8")   # 柵が前から効いていない
        self.write_arms([arm("caught", "    if x < 0:", "    if False:", "G.test_negative_refused")])
        r = self.run_selfcheck()
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("CONTROL_RED", r.stdout)
        self.assertNotIn("CAUGHT caught", r.stdout)

    def test_claude_tmp_home_refused_before_copy(self):
        self.write_arms([arm("caught", "    if x < 0:", "    if False:", "G.test_negative_refused")])
        home = pathlib.Path("/private/tmp/claude-selfcheck-test-absent/home")
        r = self.run_selfcheck(home=home)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("一時フォルダ", r.stderr)
        self.assertFalse(home.parent.exists())


if __name__ == "__main__":
    unittest.main()
