"""CI の節の口 entry.run_ci が入力 test_cmd を宣言に加えて走らせる時の決まり（人の関所の条件）: 宣言の段と同じコマンドは
1 度だけ走らせて関所と報告にそう書く・test_cmd の段のログは宣言の段のログを上書きしない・engine の返答を受け付けが拒んで
任せ先に落ちても test_cmd を 2 度走らせない・環境で起こせない段はコードの赤と分けて名指しで出す"""
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import board  # noqa: E402
import entry  # noqa: E402


def _runner(calls, batches=None):
    """子のプロセスを起こさない runner: tree_runner と同じく log_dir/<段の番号>.out・.err を書く。argv に 'exit 1' で exit 1。
    calls に段の argv を、batches に呼ばれた 1 回ごとの段の名を積む"""
    def run(steps, cwd, log_dir):
        if batches is not None:
            batches.append([s["name"] for s in steps])
        log_dir = pathlib.Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)
        runs = []
        for i, s in enumerate(steps, 1):
            calls.append(list(s["argv"]))
            out, err = log_dir / f"{i}.out", log_dir / f"{i}.err"
            out.write_text(f"{s['name']}-ran\n", encoding="utf-8")
            err.write_text("", encoding="utf-8")
            runs.append({"name": s["name"], "argv": list(s["argv"]), "out": str(out), "err": str(err),
                         "exit": 1 if "exit 1" in " ".join(s["argv"]) else 0})
        return runs
    return run


class _Board:
    """宣言の段 steps を持つ run_engine の偽。reject なら受け付けが拒んだ形（fallback と runs）で返し、節は任せ先で待つ"""

    def __init__(self, tmp, steps, *, reject=False):
        self.tmp, self.steps, self.reject = pathlib.Path(tmp), steps, reject
        self.record = {"materials": {}, "process": {"checks": {}}}
        self.rd = {"instances": {"p4.ci": {"status": "pending", "engine_fallback": "", "attempts": 1}}}
        self.state = {"inputs": {"cwd": str(self.tmp)}}
        self.given = None

    def run_engine(self, nid, *, runner=None):
        runs = runner(self.steps, self.tmp, self.tmp / "logs" / nid)
        if self.reject:
            self.rd["instances"][nid]["engine_fallback"] = "受け付けが拒んだ"
            return {"ok": False, "node": nid, "fallback": "受け付けが拒んだ", "runs": runs}
        status = "clean" if all(r["exit"] == 0 for r in runs) else "found"
        self.record["materials"]["local_checks"] = {"status": status}
        self.record["process"]["checks"][nid] = {"by": "engine", "runs": runs}
        return {"ok": True, "node": nid, "runs": runs}

    def work(self, name):
        p = self.tmp / "r1" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def mark_launched(self, nid, attempt):
        pass

    def done(self, nid, reply):
        self.given = reply


class RunCiTestCmdRulesCase(unittest.TestCase):
    def run_ci(self, steps, test_cmd, **kw):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        b, calls, self.batches = _Board(tmp.name, steps, **kw), [], []
        with mock.patch.object(board, "tree_runner", _runner(calls, self.batches)):
            got = entry.run_ci(b, "p4.ci", test_cmd=test_cmd)
        return b, got, calls

    def test_declared_and_red_test_cmd_is_found(self):
        """宣言が在っても test_cmd を黙って捨てない: 宣言の段が緑で test_cmd が赤なら素材は found（AND の合成）"""
        b, _, _ = self.run_ci([{"name": "decl", "argv": ["decl"]}], "exit 1")
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "found")

    def test_declared_and_green_test_cmd_runs_both_in_one_runner_call(self):
        b, got, _ = self.run_ci([{"name": "decl", "argv": ["decl"]}], "true")
        self.assertEqual(got["by"], "engine")
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "clean")
        runs = b.record["process"]["checks"]["p4.ci"]["runs"]
        self.assertEqual([r["name"] for r in runs], ["decl", "test_cmd"])
        self.assertIn("true", " ".join(runs[-1]["argv"]))
        self.assertEqual(self.batches, [["decl", "test_cmd"]], "runner を steps + [test_cmd の段] の 1 回で呼んでいない")

    def test_same_command_as_declared_step_runs_once(self):
        b, got, calls = self.run_ci([{"name": "pytest", "argv": ["pytest", "-q"]}], "pytest -q")
        self.assertEqual(calls, [["pytest", "-q"]])
        self.assertEqual(got["same_as"], "pytest")
        line = entry.suites_line({"by": "engine", "suites": [{"name": "pytest", "exit": 0}], "test_cmd_same_as": "pytest"})
        self.assertIn("宣言の段 pytest と同じコマンドなので 1 度だけ", line)
        self.assertNotIn("渡されていない", line)

    def test_different_command_runs_both_with_separate_logs(self):
        b, got, calls = self.run_ci([{"name": "pytest", "argv": ["pytest", "-q"]}], "pytest -q tests")
        self.assertEqual(len(calls), 2)
        self.assertNotIn("same_as", got)
        runs = b.record["process"]["checks"]["p4.ci"]["runs"]
        outs = [r["out"] for r in runs] + [r["err"] for r in runs]
        self.assertEqual(len(set(outs)), len(outs), "test_cmd の段のログが宣言の段のログを上書きする")

    def test_fallback_after_run_reuses_test_cmd_result(self):
        b, got, calls = self.run_ci([{"name": "pytest", "argv": ["pytest"]}], "echo x; exit 1", reject=True)
        self.assertEqual(got["by"], "role")
        self.assertEqual(sum(1 for c in calls if c[:2] == ["bash", "-c"]), 1, "任せ先に落ちた後に test_cmd を走らせ直した")
        self.assertEqual(b.given["material"]["status"], "found")
        self.assertIn("test_cmd-ran", pathlib.Path(got["log"]).read_text(encoding="utf-8"))


class EnvFailureLineCase(unittest.TestCase):
    """起こせない段は checks_reply の broken と同じ規則（exit None だけ）。126・127 は素材が found に数えるのでコードの赤"""

    def test_unlaunchable_step_is_named_apart_from_code_red(self):
        tests = {"ok": True, "green": False, "by": "engine",
                 "suites": [{"name": "pytest", "exit": 0}, {"name": "test_cmd", "exit": None}]}
        line = entry.suites_line(tests)
        self.assertIn("環境で起こせなかった（コードの赤ではない）: test_cmd（起こせない）", line)
        self.assertTrue(entry.env_only_red(tests))

    def test_missing_command_127_is_red_like_the_material(self):
        tests = {"ok": True, "green": False, "by": "engine",
                 "suites": [{"name": "pytest", "exit": 0}, {"name": "test_cmd", "exit": 127}]}
        self.assertFalse(entry.env_only_red(tests))
        self.assertIn("test_cmd（exit 127）", entry.suites_line(tests))

    def test_code_red_is_not_env(self):
        tests = {"ok": True, "green": False, "by": "engine",
                 "suites": [{"name": "pytest", "exit": 1}, {"name": "test_cmd", "exit": None}]}
        self.assertFalse(entry.env_only_red(tests))
        self.assertIn("pytest（exit 1）", entry.suites_line(tests))


if __name__ == "__main__":
    unittest.main()
