"""works/dev/use.sh（ほかのリポジトリを対象に darkfactory を回す起動の殻）の検査。Archon は偽物（sh の台本）に差し替え、AI は起こさない。

見る物:
- 拒む形（どれも Archon を呼ばず、pack も写さず、終了コード 2 と 1 行の理由）: 使い方の誤り・/private/tmp の下の対象・git の
  リポジトリの根でない・commit していない変更か未追跡のファイルが在る・origin が無い・対象に pack の写し（.archon/workflows/works）が
  在る・依頼のファイルが無い・認証が無い。
- start: pack（tests/・dev/・docs/ 抜き）を利用の家の Archon の全体の工程の置き場（<家>/archon-home/workflows/works）に写し、
  対象の中で `workflow run darkfactory --from <対象の HEAD>` を、写した依頼の絶対パス・test_cmd・tdd_suite・adapter=optional・
  final_gate=always で呼ぶ。開発の家（WORKS_DEV_HOME）は継がない（走っている自分食いの家を書き換えない）。
- tdd_suite: 第 4 引数が在ればそのまま。無ければ test_cmd が pytest の 1 コマンドの時だけ JUnit XML を第 1 引数に書く実行器を
  利用の家に書いて渡し、そうでなければ空（直に直す）にして 1 行で知らせる。
- 止まった後の行: 承認・答える（continue・stop）・報告のパス・差分のファイル（利用の家の下。対象の親には書かない）と対象へ
  git apply する行。show は同じ行を出し直す（清さは求めない）。
- check: 認証を読まずに validate workflows darkfactory だけを呼ぶ。
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock

from gitkit import committed_copy, git

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEV = ROOT / "dev"
USE = DEV / "use.sh"
BASETEMP_PARENT = ROOT.parent / ".works-test-tmp"
_saved = {}


def setUpModule():
    """use.sh は /private/tmp の下の対象を拒むので、TMPDIR がそこなら試験の置き場をリポジトリの根の .works-test-tmp/ へ移す"""
    _saved["tempdir"] = tempfile.tempdir
    real = os.path.realpath(tempfile.gettempdir())
    if real == "/private/tmp" or real.startswith("/private/tmp/"):
        BASETEMP_PARENT.mkdir(exist_ok=True)
        _saved["base"] = tempfile.mkdtemp(prefix="use-", dir=str(BASETEMP_PARENT))
        tempfile.tempdir = _saved["base"]
        _saved["environ"] = mock.patch.dict(os.environ, {"TMPDIR": _saved["base"]})
        _saved["environ"].start()


def tearDownModule():
    environ = _saved.pop("environ", None)
    if environ:
        environ.stop()
    tempfile.tempdir = _saved.get("tempdir")
    base = _saved.pop("base", None)
    if base:
        shutil.rmtree(base, ignore_errors=True)
        try:
            BASETEMP_PARENT.rmdir()
        except OSError:
            pass


class UseShell(unittest.TestCase):
    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._td.name).resolve()
        self.addCleanup(self._td.cleanup)
        self.home = self.tmp / "use-home"
        self.dev_home = self.tmp / "dev-home"
        self.request = self.tmp / "req.json"
        self.request.write_text('[{"where": "stats.py:1", "text": "mean が空で落ちる"}]\n')
        self.log = self.tmp / "calls.txt"
        self.runs = self.tmp / "runs.json"
        self.set_runs(working_path="/wt/run-1", output_root="/out")
        self.fake = self.tmp / "fake-archon.sh"
        self.fake.write_text(
            "#!/bin/sh\n"
            f'{{ printf \'%s\\t\' "$(pwd -P)" "${{WORKS_DEV_NO_AUTH:-}}" "${{WORKS_DEV_HOME:-}}" "$@"; echo; }} >> "{self.log}"\n'
            f'case "$*" in "workflow runs --json") cat "{self.runs}" ;; esac\n'
            "exit 0\n")

    def set_runs(self, **run):
        self.runs.write_text(json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": "paused", **run}]}))

    def target(self, name="target", origin=True):
        t = self.tmp / name
        committed_copy(t, DEV / "target-seed")
        if origin:
            git(t, "remote", "add", "origin", str(self.tmp / "origin.git"))
        return t

    def use(self, *args, cwd=None, **env_kw):
        env = dict(os.environ)
        for name in ("CLAUDE_CODE_OAUTH_TOKEN", "WORKS_KEYCHAIN_ITEM", "WORKS_DEV_NO_AUTH", "WORKS_DEV_ADAPTER",
                     "WORKS_USE_FINAL_GATE"):
            env.pop(name, None)
        env.update(WORKS_USE_HOME=str(self.home), WORKS_DEV_HOME=str(self.dev_home), WORKS_DEV_ARCHON=str(self.fake),
                   CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test", CLAUDE_BIN_PATH="/usr/bin/true")
        for k, v in env_kw.items():
            if v is None:
                env.pop(k, None)
            else:
                env[k] = v
        r = subprocess.run(["sh", str(USE), *args], capture_output=True, text=True, env=env, cwd=cwd)
        self.assertNotIn("dummy-token-for-test", r.stdout + r.stderr)
        return r

    def calls(self):
        return [l.rstrip("\t").split("\t") for l in self.log.read_text().splitlines()] if self.log.exists() else []

    def assert_refused(self, r, *words):
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        lines = r.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, r.stderr)
        self.assertTrue(lines[0].startswith("use.sh: "), lines[0])
        for w in words:
            self.assertIn(w, lines[0])
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.home / "archon-home" / "workflows").exists())
        self.assertFalse(self.dev_home.exists())

    # ---- 拒む形
    def test_usage(self):
        for args in ((), ("nope",), ("start",), ("start", "t", "r"), ("start", "a", "b", "c", "d", "e"),
                     ("show",), ("check",), ("check", "a", "b")):
            with self.subTest(args):
                r = self.use(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("usage: use.sh", r.stderr)
                self.assertEqual(self.calls(), [])

    def test_refuses_target_under_private_tmp(self):
        for t in ("/private/tmp/works-use-test-none", "/tmp/works-use-test-none"):
            with self.subTest(t):
                self.assert_refused(self.use("start", t, str(self.request), "true"), "/private/tmp")

    def test_refuses_non_repo_and_subdir(self):
        plain = self.tmp / "plain"
        plain.mkdir()
        self.assert_refused(self.use("start", str(plain), str(self.request), "true"), "git のリポジトリの根")
        t = self.target()
        (t / "sub").mkdir()
        self.assert_refused(self.use("start", str(t / "sub"), str(self.request), "true"), "git のリポジトリの根")

    def test_refuses_uncommitted_and_untracked(self):
        t = self.target()
        (t / "stats.py").write_text((t / "stats.py").read_text() + "# 手元の書き換え\n")
        self.assert_refused(self.use("start", str(t), str(self.request), "true"), "commit していない", "stats.py")
        git(t, "checkout", "--", "stats.py")
        (t / "new.txt").write_text("未追跡\n")
        self.assert_refused(self.use("check", str(t)), "commit していない", "new.txt")

    def test_refuses_without_origin(self):
        t = self.target(origin=False)
        self.assert_refused(self.use("start", str(t), str(self.request), "true"), "origin")

    def test_refuses_target_with_pack_copy(self):
        t = self.target()
        (t / ".archon" / "workflows" / "works").mkdir(parents=True)
        (t / ".archon" / "workflows" / "works" / "archon-plugin.json").write_text("{}\n")
        git(t, "add", "-A")
        git(t, "commit", "-q", "-m", "pack")
        self.assert_refused(self.use("start", str(t), str(self.request), "true"), ".archon/workflows/works")

    def test_refuses_missing_request_and_no_auth(self):
        t = self.target()
        self.assert_refused(self.use("start", str(t), str(self.tmp / "none.json"), "true"), "依頼")
        self.assert_refused(self.use("start", str(t), str(self.request), "true", CLAUDE_CODE_OAUTH_TOKEN=None), "認証")

    def test_refuses_use_home_in_claude_tmp(self):
        t = self.target()
        r = self.use("start", str(t), str(self.request), "true", WORKS_USE_HOME="/private/tmp/claude-works-use-test-0/h")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("/private/tmp/claude-", r.stderr)
        self.assertEqual(self.calls(), [])

    # ---- start
    def test_start_copies_pack_to_use_home_and_runs_from_target_head(self):
        t = self.target()
        head = git(t, "rev-parse", "HEAD")
        r = self.use("start", str(t), str(self.request), "python3 -m unittest -q", "")
        self.assertEqual(r.returncode, 0, r.stderr)
        pack = self.home / "archon-home" / "workflows" / "works"
        self.assertTrue((pack / "darkfactory" / "darkfactory.yaml").is_file())
        self.assertTrue((pack / ".works-source.json").is_file())
        for d in ("tests", "dev", "docs"):
            self.assertFalse((pack / d).exists(), d)
        self.assertFalse(self.dev_home.exists())   # 自分食いの家（WORKS_DEV_HOME）は継がない
        self.assertEqual(git(t, "status", "--porcelain"), "")   # 対象には何も書かない
        calls = self.calls()
        self.assertEqual(len(calls), 2, calls)
        run, runs = calls
        self.assertEqual(run[:3], [str(t), "", str(self.home)])
        req = pathlib.Path(run[run.index("--input") + 1].split("=", 1)[1])
        self.assertTrue(req.is_absolute())
        self.assertTrue(str(req).startswith(str(self.home)), req)
        self.assertEqual(req.read_text(), self.request.read_text())
        self.assertEqual(run[3:], [
            "workflow", "run", "darkfactory", "--from", head,
            "--input", f"request={req}", "--input", "test_cmd=python3 -m unittest -q",
            "--input", "tdd_suite=", "--input", "adapter=optional", "--input", "final_gate=always"])
        self.assertEqual(runs, [str(t), "1", str(self.home), "workflow", "runs", "--json"])
        out = r.stdout
        self.assertIn("run id: run-1", out)
        for verb in ("approve run-1", "respond run-1 continue", "respond run-1 stop", "reject run-1", "resume run-1"):
            self.assertIn(f"workflow {verb}", out)
        self.assertIn(f"cd {t} && ", out)
        self.assertIn(f"WORKS_DEV_HOME={self.home} ", out)
        self.assertIn("/out/artifacts/runs/run-1/board/report.md", out)
        diff = self.home / "diffs" / "run-run-1.diff"
        self.assertIn(f"git -C {t} apply {diff}", out)
        self.assertFalse((t.parent / "run-run-1.diff").exists())
        self.assertNotIn("注意", out)

    def test_start_tdd_suite_choice(self):
        t = self.target()
        cases = {
            "pytest の 1 コマンドなら実行器を書く": ("uv run pytest -q tests", None, "write"),
            "python -m pytest も同じ": ("python3 -m pytest", None, "write"),
            "pytest でない": ("make test", None, ""),
            "つないだコマンドは pytest でも書かない": ("pytest -q && ruff check", None, ""),
            "第 4 引数はそのまま": ("uv run pytest", "scripts/junit.sh", "scripts/junit.sh"),
        }
        for why, (cmd, given, want) in cases.items():
            with self.subTest(why):
                self.log.unlink(missing_ok=True)
                r = self.use("start", str(t), str(self.request), cmd, *(() if given is None else (given,)))
                self.assertEqual(r.returncode, 0, r.stderr)
                run = self.calls()[0]
                suite = next(a.split("=", 1)[1] for a in run if a.startswith("tdd_suite="))
                if want == "write":
                    p = pathlib.Path(suite)
                    self.assertTrue(p.is_absolute() and str(p).startswith(str(self.home)), suite)
                    self.assertTrue(os.access(p, os.X_OK), suite)
                    body = p.read_text()
                    self.assertIn(cmd, body)
                    self.assertIn('--junitxml="$1"', body)
                    self.assertIn("TDD の輪: ", r.stdout)
                else:
                    self.assertEqual(suite, want)
                    if want == "":
                        self.assertIn("TDD の輪を飛ばす", r.stdout)

    def test_start_final_gate_and_adapter(self):
        t = self.target()
        r = self.use("start", str(t), str(self.request), "true", "", WORKS_USE_FINAL_GATE="when_needed", WORKS_DEV_ADAPTER="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        run = self.calls()[0]
        self.assertIn("final_gate=when_needed", run)
        self.assertIn("adapter=", run)
        self.assertIn("WORKS_DEV_ADAPTER=1 ", r.stdout)

    # ---- show・check
    def test_show_writes_diff_under_use_home(self):
        t = self.target()
        wt = self.tmp / "wt"
        committed_copy(wt, DEV / "target-seed")
        base = git(wt, "rev-parse", "HEAD")
        (wt / "stats.py").write_text((wt / "stats.py").read_text() + "# 直した\n")
        board = self.tmp / "out" / "artifacts" / "runs" / "run-1" / "board"
        (board / "r1").mkdir(parents=True)
        (board / "r1" / "start.json").write_text(json.dumps({"base_rev": base}))
        self.set_runs(working_path=str(wt), output_root=str(self.tmp / "out"))
        (t / "stats.py").write_text((t / "stats.py").read_text() + "# 前の差分を当てた後（清さは求めない）\n")
        r = self.use("show", str(t), CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [[str(t), "1", str(self.home), "workflow", "runs", "--json"]])
        diff = self.home / "diffs" / "run-run-1.diff"
        self.assertIn("+# 直した", diff.read_text())
        self.assertIn(f"git -C {t} apply {diff}", r.stdout)

    def test_check_validates_without_auth(self):
        t = self.target()
        r = self.use("check", str(t), CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [[str(t), "1", str(self.home), "validate", "workflows", "darkfactory"]])
        self.assertTrue((self.home / "archon-home" / "workflows" / "works" / "archon-plugin.json").is_file())


if __name__ == "__main__":
    unittest.main()
