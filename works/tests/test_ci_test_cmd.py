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


class LaunchHowRecordedCase(unittest.TestCase):
    """起こし方 how は起こす所で 1 度だけ決めて走った行に載せ、読む所は規則 tree_run.command_argv で作り直さない"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)
        real = entry.tree_run.command_argv
        first = iter([real("a | b")])
        # 起こす前の 1 回目だけ本物の値を返し、その後は違う値を返す規則（読む時に作り直せば違う値が出る）
        self.rule = mock.patch.object(entry.tree_run, "command_argv", side_effect=lambda c: next(first, (["zz"], "direct")))

    def run_ci(self, code, **kw):
        b = _Board(self.tmp, [{"name": "decl", "argv": ["decl"]}], **kw)
        with self.rule, mock.patch.object(entry.tree_run, "slotted_run", return_value=(code, None)):
            return b, entry.run_ci(b, "p4.ci", test_cmd="a | b")

    def test_launch_wrapper_stamps_how_on_rows_it_ran(self):
        for cmd, hows in (("a | b", ["direct", "shell"]), ("", ["direct"])):
            with self.subTest(cmd=cmd), mock.patch.object(entry.tree_run, "slotted_run", return_value=(0, None)):
                rows = entry._with_test_cmd(None, cmd, {})([{"name": "decl", "argv": ["decl"]}], self.tmp, self.tmp / cmd)
            self.assertEqual([r["how"] for r in rows], hows)

    def test_engine_runs_carry_how_decided_at_launch(self):
        _, got = self.run_ci(0)
        self.assertEqual(got["runs"], [{"name": "decl", "exit": 0, "how": "direct"},
                                       {"name": entry.TEST_CMD_STEP, "exit": 0, "how": "shell"}])
        self.assertIn(f"{entry.TEST_CMD_STEP}（起こし方 shell）", pathlib.Path(got["log"]).read_text(encoding="utf-8"))

    def test_fallback_material_reads_how_from_ran_row_not_from_rule(self):
        b, got = self.run_ci(1, reject=True)
        self.assertEqual((got["by"], got["how"]), ("role", "shell"))
        self.assertIn("bash -c 'a | b'（起こし方 shell）", b.given["material"]["detail"])


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


class BaselineNotRunCase(unittest.TestCase):
    """基準の検査が走らなかった段・走ったかを確かめていない段を、既知の基の赤と分けて書く（test_cmd の素材と報告の行）"""

    def test_test_cmd_red_says_unverified(self):
        """test_cmd は shell の文字列で試験の報告を宣言できない: 赤は found のまま、走ったかは確かめていないと添える"""
        with tempfile.TemporaryDirectory() as d:
            log = pathlib.Path(d) / "t.log"
            log.write_text("boom\n", encoding="utf-8")
            m = entry._cmd_material(1, log, ["bash", "-c", "x"], "shell")["material"]
        self.assertEqual(m["status"], "found")
        self.assertIn(entry.gatemarks.BASELINE_UNVERIFIED, m["detail"])

    def test_awaiting_human_baseline_is_said_not_run(self):
        """p0 は走らなかった時にだけ awaiting_human を立てる: 状態の語のまま『基準の検査が走らなかった』を添える"""
        b = type("B", (), {"record": {"process": {"baseline_checks": {"status": "awaiting_human", "reason": "r"}}}})()
        line = entry.baseline_line(b)
        self.assertTrue(line.startswith(f"修正前のテスト: {entry.gatemarks.MATERIAL_WORDS['awaiting_human']}（"), line)
        self.assertIn(entry.gatemarks.BASELINE_NOT_RUN, line)


def _load_run_tests():
    """blk-tests の節のスクリプトを module として読む（main は __main__ の時だけ走る）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("blk_tests_run_tests_launch", ROOT / "blk-tests" / "scripts" / "run_tests.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class _WorkBoard:
    """run_mid が読む b.work だけを持つ盤面"""

    def __init__(self, d):
        self.d = pathlib.Path(d)

    def work(self, name):
        return self.d / name


class LaunchKindCase(unittest.TestCase):
    """起こせなかった（exit None）を落ちた（found・green false）と同じ値に畳まず、結果の型に残す。126・127 は直でもシェル越しでも
    プログラム自身の終了コードとして赤と読む（tree_run.launch_kind）"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)
        self.log = self.tmp / "t.log"
        self.log.write_text("末尾\n", encoding="utf-8")

    def test_material_of_unlaunched_cmd_is_not_run(self):
        m = entry._cmd_material(None, self.log, *entry.tree_run.command_argv("pytest"))["material"]
        self.assertEqual(m["status"], "not_run")

    def test_material_of_exit_126_127_is_code_red(self):
        for cmd in ("pytest", "pytest | tee out"):
            for code in (126, 127):
                with self.subTest(cmd=cmd, code=code):
                    m = entry._cmd_material(code, self.log, *entry.tree_run.command_argv(cmd))["material"]
                    self.assertEqual((m["status"], m["count"]), ("found", 1))
                    self.assertNotIn("起こせなかった疑い", m["detail"])

    def test_material_of_code_red_does_not_name_launch_suspect(self):
        m = entry._cmd_material(1, self.log, *entry.tree_run.command_argv("pytest"))["material"]
        self.assertEqual(m["status"], "found")
        self.assertNotIn("起こせなかった疑い", m["detail"])

    def test_suites_line_reads_shell_exit_127_as_code_red(self):
        # 前の版の記録に残る launch: suspect も、終了コードだけで赤と読む
        for launch in ({}, {"launch": "suspect"}):
            with self.subTest(launch=launch):
                tests = {"ok": True, "green": False, "by": "engine", "test_cmd_how": "shell",
                         "suites": [{"name": "pytest", "exit": 0}, {"name": entry.TEST_CMD_STEP, "exit": 127, **launch}]}
                line = entry.suites_line(tests)
                self.assertIn(f"{entry.TEST_CMD_STEP}（exit 127・shell）", line)
                self.assertNotIn("起こせなかった疑い", line)
                self.assertNotIn("環境で起こせなかった", line)
                self.assertFalse(entry.env_only_red(tests))

    def test_unlaunched_direct_step_names_how_to_wrap_in_bash(self):
        tests = {"ok": True, "green": False, "by": "engine",
                 "suites": [{"name": entry.TEST_CMD_STEP, "exit": None, "how": "direct", "launch": "broken"}]}
        line = entry.suites_line(tests)
        self.assertIn(f"{entry.TEST_CMD_STEP}（起こせない・direct）", line)
        self.assertIn(entry.tree_run.DIRECT_HINT, line)
        m = entry._cmd_material(None, self.log, ["pytest"], "direct")["material"]
        self.assertIn(entry.tree_run.DIRECT_HINT, m["reason"])
        shell = entry._cmd_material(None, self.log, ["bash", "-c", "pytest | tee x"], "shell")["material"]
        self.assertNotIn(entry.tree_run.DIRECT_HINT, shell["reason"])

    def test_test_cmd_callers_launch_by_command_argv(self):
        for cmd, argv, how in (("pytest -q tests", ["pytest", "-q", "tests"], "direct"),
                               ("pytest && ruff", ["bash", "-c", "pytest && ruff"], "shell")):
            with self.subTest(cmd=cmd):
                seen = []
                with mock.patch.object(entry.tree_run, "slotted_run", lambda a, *_, **__: seen.append(a) or (0, None)):
                    m = entry.local_checks_material(self.tmp, cmd, self.log)["material"]
                self.assertEqual((seen, m["status"]), ([argv], "clean"))
                steps = []
                entry._with_test_cmd(lambda s, *_: steps.extend(s) or [], cmd, {})([], self.tmp, self.tmp)
                self.assertEqual(steps, [{"name": entry.TEST_CMD_STEP, "argv": argv, "how": how}])

    def test_suites_line_does_not_judge_shell_by_step_name(self):
        # 段の分類は段の名でなく終了コードだけで決まる（entry._suite_kind。段が偶々 cmd・test_cmd の名でも 127 は赤）
        for name in ("cmd", entry.TEST_CMD_STEP):
            with self.subTest(name=name):
                tests = {"ok": True, "green": False, "by": "engine", "suites": [{"name": name, "exit": 127}]}
                self.assertNotIn("起こせなかった疑い", entry.suites_line(tests))

    def test_material_of_direct_same_as_step_127_is_code_red(self):
        # test_cmd が宣言の段と同じ（same_as）なら engine はその段を shell を通さずに起こした: 127 はそのテスト自身の赤
        m = entry._cmd_material(127, self.log, ["pytest", "-q"], "direct")["material"]
        self.assertEqual(m["status"], "found")
        self.assertNotIn("起こせなかった疑い", m["detail"])
        self.assertNotIn("bash -c", m["detail"])

    def test_fallback_reusing_same_as_step_passes_its_argv(self):
        # run_ci が任せ先に落ちて same_as の段の結果を使い回す時、_cmd_material はその段の argv（shell なし）で分ける
        calls = []
        b = mock.Mock()
        b.rd = {"instances": {"p4.ci": {}}}
        b.work.return_value = self.tmp / "p4.ci.log"
        run = {"name": "pytest", "argv": ["pytest", "-q"], "how": "direct", "exit": 127, "out": str(self.log)}
        with mock.patch.object(entry, "_cmd_material", side_effect=lambda *a: calls.append(a) or {"material": {}}):
            got = entry._ci_by_cmd(b, "p4.ci", "pytest -q", ran=run)
        self.assertEqual(calls[0][2:], (["pytest", "-q"], "direct"))
        self.assertEqual(got["how"], "direct")

    def test_final_suites_carry_how_and_read_127_as_red(self):
        mod = _load_run_tests()
        for cmd, how in (("x", "direct"), ("x && y", "shell")):
            with self.subTest(cmd=cmd):
                b = mock.Mock()
                b.record = {"materials": {"local_checks": {"status": "found"}}}
                runs = [{"name": "cmd", "exit": 127, "how": "direct"}, {"name": entry.TEST_CMD_STEP, "exit": 127, "how": how}]
                out = mod.run_final(b, cmd, run_ci=lambda *a, **k: {"by": "engine", "log": "l", "runs": runs})
                self.assertFalse(out["green"])
                self.assertEqual(out["suites"], runs)
                self.assertEqual(out["test_cmd_how"], how)

    def test_final_reads_how_from_record_not_from_rule(self):
        mod = _load_run_tests()
        b = mock.Mock()
        b.record = {"materials": {"local_checks": {"status": "clean"}}}
        runs = [{"name": "cmd", "exit": 0, "how": "direct"}, {"name": entry.TEST_CMD_STEP, "exit": 0, "how": "shell"}]
        with mock.patch.object(mod.tree_run, "command_argv", return_value=(["x"], "direct")):
            out = mod.run_final(b, "x && y", run_ci=lambda *a, **k: {"by": "engine", "log": "l", "runs": runs})
        self.assertEqual((out["suites"][1]["how"], out["test_cmd_how"]), ("shell", "shell"))

    def test_final_does_not_guess_how_for_rows_without_it(self):
        mod = _load_run_tests()
        b = mock.Mock()
        b.record = {"materials": {"local_checks": {"status": "clean"}}}
        runs = [{"name": "cmd", "exit": 0}, {"name": entry.TEST_CMD_STEP, "exit": 0}]
        out = mod.run_final(b, "x && y", run_ci=lambda *a, **k: {"by": "engine", "log": "l", "runs": runs})
        self.assertEqual(out["suites"], runs)
        self.assertNotIn("test_cmd_how", out)

    def test_final_by_role_reports_how_run_ci_launched(self):
        mod = _load_run_tests()
        b = mock.Mock()
        b.record = {"materials": {"local_checks": {"status": "clean"}}}
        with mock.patch.object(mod.tree_run, "command_argv", return_value=(["x"], "direct")):
            out = mod.run_final(b, "x && y", run_ci=lambda *a, **k: {"by": "role", "log": "l", "how": "shell"})
        self.assertEqual((out["suites"], out["test_cmd_how"]), ([], "shell"))

    def _plain(self, run, cmd="pytest"):
        mod = _load_run_tests()
        with mock.patch.object(mod.tree_run, "run", run):
            try:
                return mod.run_plain(cmd, self.tmp)
            except OSError as e:
                self.fail(f"コマンドを起こせない時に run_plain が例外で落ちた: {e!r}")

    def test_plain_unlaunchable_direct_cmd_returns_launch_broken(self):
        out = self._plain(mock.Mock(side_effect=FileNotFoundError("pytest")))
        self.assertEqual((out["ok"], out["green"], out.get("launch"), out.get("how")), (True, False, "broken", "direct"))
        self.assertIn(entry.tree_run.DIRECT_HINT, pathlib.Path(out["log"]).read_text(encoding="utf-8"))

    def test_plain_exit_126_127_is_code_red_with_mutgate_keys(self):
        for cmd in ("pytest", "pytest | tee out"):
            for code in (126, 127):
                with self.subTest(cmd=cmd, code=code):
                    out = self._plain(mock.Mock(return_value=code), cmd)
                    self.assertEqual((out["ok"], out["green"]), (True, False))
                    self.assertEqual(set(out), {"ok", "green", "log", "how"})

    def test_plain_code_red_keeps_mutgate_keys(self):
        out = self._plain(mock.Mock(return_value=1))
        self.assertEqual(set(out), {"ok", "green", "log", "how"})

    def test_plain_red_and_green_carry_how_in_exit_and_log(self):
        for cmd, argv, how in (("pytest", ["pytest"], "direct"), ("pytest | tee out", ["bash", "-c", "pytest | tee out"], "shell")):
            for code in (0, 1):
                with self.subTest(cmd=cmd, code=code):
                    out = self._plain(mock.Mock(return_value=code), cmd)
                    self.assertEqual((out.get("how"), "launch" in out), (how, False))
                    head = pathlib.Path(out["log"]).read_text(encoding="utf-8").splitlines()[0]
                    self.assertEqual(head, f"== 起こし方 {how}: {__import__('json').dumps(argv)}")

    def test_mid_declared_step_log_names_how(self):
        decl = {"sha": "s", "steps": [{"name": "unit", "argv": ["pytest", "-q"]}]}
        out = self._mid(mock.Mock(return_value=0), decl=decl)
        self.assertEqual(out["suites"], [{"name": "unit", "exit": 0, "how": "direct"}])
        self.assertIn("unit（起こし方 direct）", pathlib.Path(out["log"]).read_text(encoding="utf-8"))

    def _mid(self, run, decl=None):
        mod = _load_run_tests()
        from engine import declared
        with mock.patch.object(mod.tree_run, "run", run), mock.patch.object(declared, "read", return_value=decl), \
                mock.patch.object(mod, "_repo_root", return_value=self.tmp):
            try:
                return mod.run_mid(_WorkBoard(self.tmp), "pytest")
            except OSError as e:
                self.fail(f"コマンドを起こせない時に run_mid の cmd の道が例外で落ちた: {e!r}")

    def test_mid_unlaunchable_direct_cmd_is_exit_none(self):
        out = self._mid(mock.Mock(side_effect=FileNotFoundError("pytest")))
        self.assertFalse(out["green"])
        self.assertEqual(out["suites"][0]["exit"], None)
        self.assertEqual(out["suites"][0].get("launch"), "broken")
        self.assertEqual(__import__("json").loads((self.tmp / "mid-tests.json").read_text(encoding="utf-8"))["how"], "direct")

    def test_mid_cmd_exit_127_is_code_red(self):
        out = self._mid(mock.Mock(return_value=127))
        self.assertFalse(out["green"])
        self.assertEqual(out["suites"], [{"name": "cmd", "exit": 127, "how": "direct"}])
        self.assertEqual(__import__("json").loads((self.tmp / "mid-tests.json").read_text(encoding="utf-8"))["how"], "direct")


MISSING = "works-no-such-command-4f1c"


class LaunchProofCase(unittest.TestCase):
    """test_cmd を起こせない（先頭の語が見つからない・実行できない）ことは起こす前に確かめ、found・赤でなく not_run（環境）にする
    （子のプロセスを本当に起こす）"""

    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp())
        self.addCleanup(__import__("shutil").rmtree, self.tmp, ignore_errors=True)

    def _material(self, cmd):
        return entry.local_checks_material(self.tmp, cmd, self.tmp / "logs" / "t.log")["material"]

    def test_material_of_missing_command_is_not_run(self):
        self.assertEqual(self._material(f"{MISSING} -q")["status"], "not_run")

    def test_material_of_missing_command_behind_env_prefix_is_not_run(self):
        self.assertEqual(self._material(f"FOO=1 {MISSING} -q")["status"], "not_run")

    def test_material_of_missing_command_in_pipeline_is_not_run(self):
        # シェルが要る形（パイプ）でも先頭の語を起こす前に引く。引かないと後ろの cat の 0 で clean に化ける
        self.assertEqual(self._material(f"{MISSING} -q | cat")["status"], "not_run")

    def test_material_of_non_executable_file_is_not_run(self):
        script = self.tmp / "t.sh"
        script.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        script.chmod(0o644)
        self.assertEqual(self._material("./t.sh")["status"], "not_run")

    def test_plain_missing_command_returns_launch_broken(self):
        out = _load_run_tests().run_plain(f"{MISSING} -q", self.tmp)
        self.assertEqual((out["green"], out.get("launch")), (False, "broken"))

    def test_mid_missing_command_returns_launch_broken(self):
        mod = _load_run_tests()
        from engine import declared
        with mock.patch.object(declared, "read", return_value=None), mock.patch.object(mod, "_repo_root", return_value=self.tmp):
            out = mod.run_mid(_WorkBoard(self.tmp), f"{MISSING} -q")
        self.assertEqual(out["suites"][0].get("launch"), "broken")


if __name__ == "__main__":
    unittest.main()
