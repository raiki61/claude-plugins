"""works/dev/use.sh（ほかのリポジトリを対象に darkfactory を回す起動の殻）の検査。Archon は偽物（sh の台本）に差し替え、AI は起こさない。

見る物:
- 拒む形（どれも Archon を呼ばず、pack も写さず、終了コード 2 と 1 行の理由）: 使い方の誤り・/private/tmp の下の対象・git の
  リポジトリの中でない・対象に pack の写し（.archon/workflows/works）が在る・依頼のファイルが無い・認証が無い（keychain は偽物）。
  commit していない変更・未追跡のファイル（包んで回す）・origin が無いこと・下のフォルダ（git の根で回す）・test_cmd を省くことは拒まない。
- start: pack（tests/・dev/・docs/ 抜き）を利用の家の Archon の全体の工程の置き場（<家>/archon-home/workflows/works）に写し、
  対象の中で `workflow run darkfactory --from <対象の HEAD>` を、写した依頼の絶対パス・test_cmd・tdd_suite・adapter=（包みを入れる既定。archon.sh に WORKS_DEV_ADAPTER=1）・final_gate=when_needed（既定）で呼び、WORKS_USE_FINAL_GATE=always を付けた時だけ
  final_gate=always で呼ぶ。開発の家（WORKS_DEV_HOME）は継がない（走っている自分食いの家を書き換えない）。
- tdd_suite: 第 4 引数が在ればそのまま。無ければ test_cmd が pytest の 1 コマンドの時だけ JUnit XML を第 1 引数に書く実行器を
  利用の家に書いて渡し、そうでなければ空（直に直す）にして 1 行で知らせる。
- 止まった後の行: 承認・答える（continue・stop）・報告のパス・差分のファイル（利用の家の下。対象の親には書かない）と対象へ
  git apply する行。show は同じ行を出し直す（清さは求めない）。
- check: AI を起こさず（validate workflows darkfactory だけを認証を読ませずに呼ぶ）、認証などの足りない物を入れ方の行つきで全部並べ、在れば 0 以外。
- git でない写し（プラグインのキャッシュの形。tests/・docs/ が無く、Claude Code の印が在る）の works から、写しの use.sh が写しの
  archon.sh・guard.sh・toolset.py を通して check・start を回せ、元のリポジトリの works を 1 度も指さない（偽物は Archon の実行ファイルと
  claude だけ）。
"""
import json
import os
import pathlib
import re
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

    def use(self, *args, cwd=None, script=USE, **env_kw):
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
        r = subprocess.run(["sh", str(script), *args], capture_output=True, text=True, encoding="utf-8", env=env, cwd=cwd)
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
        for args in ((), ("nope",), ("start",), ("start", "a", "b", "c", "d", "e"),
                     ("show",), ("check",), ("check", "a", "b"), ("answer", "t", "r", "continue"), ("stop", "t", "r")):
            with self.subTest(args):
                r = self.use(*args)
                self.assertEqual(r.returncode, 2, r.stderr)
                self.assertIn("usage: use.sh", r.stderr)
                self.assertEqual(self.calls(), [])

    def test_start_without_test_cmd_and_target(self):
        """test_cmd を省けば test_cmd= （空。ラインの既定に任せる）を渡し、対象も省けば今いるフォルダの git の根で回す"""
        t = self.target()
        r = self.use("start", str(t), str(self.request))
        self.assertEqual(r.returncode, 0, r.stderr)
        run = self.calls()[0]
        self.assertIn("test_cmd=", run)
        self.assertIn("tdd_suite=", run)
        self.assertIn("test_cmd を省いた", r.stdout)
        (t / "sub").mkdir()
        self.log.unlink()
        r = self.use("start", str(self.request), cwd=str(t / "sub"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls()[0][0], str(t))

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
        head = git(t, "rev-parse", "HEAD")
        r = self.use("start", str(t / "sub"), str(self.request), "true")   # 下のフォルダは拒まず、git の根で回す
        self.assertEqual(r.returncode, 0, r.stderr)
        run = self.calls()[0]
        self.assertEqual(run[0], str(t))
        self.assertEqual(run[run.index("--from") + 1], head)
        self.assertIn(f"git のリポジトリの根（{t}）で回す", r.stdout)

    def test_start_wraps_uncommitted_and_untracked(self):
        """汚れた対象は拒まず、一時の index で包んだ commit から run を切る（.gitignore の物は入れない）。対象の作業ツリー・
        index・枝は前後で変わらず、包んだことと commit を出す。check も未追跡で拒まない"""
        t = self.target()
        head = git(t, "rev-parse", "HEAD")
        (t / "stats.py").write_text((t / "stats.py").read_text() + "# 手元の書き換え\n")
        (t / "new.txt").write_text("未追跡\n")
        (t / "junk.pyc").write_bytes(b"ignored")   # 種の .gitignore が *.pyc を無視する
        before = git(t, "status", "--porcelain", "--untracked-files=all")
        r = self.use("start", str(t), str(self.request), "true")
        self.assertEqual(r.returncode, 0, r.stderr)
        run = self.calls()[0]
        base = run[run.index("--from") + 1]
        self.assertNotEqual(base, head)
        self.assertEqual(git(t, "rev-parse", f"{base}^"), head)
        self.assertIn("# 手元の書き換え", git(t, "show", f"{base}:stats.py"))
        self.assertEqual(git(t, "show", f"{base}:new.txt"), "未追跡")
        self.assertNotIn("junk.pyc", git(t, "ls-tree", "-r", "--name-only", base).split())
        self.assertEqual(git(t, "status", "--porcelain", "--untracked-files=all"), before)
        self.assertEqual(git(t, "rev-parse", "HEAD"), head)
        self.assertIn(f"包んだ（wrapped）", r.stdout)
        self.assertIn(base, r.stdout)
        self.assertIn("new.txt", r.stdout)
        self.log.unlink()
        r = self.use("check", str(t))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [[str(t), "1", str(self.home), "validate", "workflows", "darkfactory"]])

    def test_start_without_origin(self):
        """origin の無い対象も拒まずに起こし、対象の remote は書き換えない"""
        t = self.target(origin=False)
        r = self.use("start", str(t), str(self.request), "true")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls()[0][3:6], ["workflow", "run", "darkfactory"])
        self.assertIn("origin が無い", r.stdout)
        self.assertEqual(git(t, "remote"), "")

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
        self.assert_refused(self.use("start", str(t), str(self.request), "true", CLAUDE_CODE_OAUTH_TOKEN=None,
                                     PATH=self.no_keychain()), "認証")

    def no_keychain(self):
        """Claude Code の keychain の項目が無い偽の security を頭に置いた PATH（本物の keychain は読まない）"""
        fake_bin = self.tmp / "no-keychain-bin"
        fake_bin.mkdir(exist_ok=True)
        (fake_bin / "security").write_text('#!/bin/sh\necho "$*" >> "$0.calls"\nexit 44\n')
        (fake_bin / "security").chmod(0o755)
        return str(fake_bin) + os.pathsep + os.environ.get("PATH", "")

    def test_start_adapter_default_and_explicit_off(self):
        """包みは既定で入れる（adapter= と続きの行の WORKS_DEV_ADAPTER=1）。0 か空を明示した時だけ adapter=optional と『包み無し』"""
        t = self.target()
        for value in ("0", ""):
            with self.subTest(value):
                self.log.unlink(missing_ok=True)
                r = self.use("start", str(t), str(self.request), "true", "", WORKS_DEV_ADAPTER=value)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("adapter=optional", self.calls()[0])
                self.assertTrue(r.stdout.startswith("包み無し"), r.stdout)
                self.assertNotIn("WORKS_DEV_ADAPTER=1 ", r.stdout)

    def test_start_final_gate_always_when_explicit_and_inputs(self):
        t = self.target()
        r = self.use("start", str(t), str(self.request), "true", "", WORKS_USE_FINAL_GATE="always",
                     WORKS_USE_POLICY_MD="/p/policy.md", WORKS_USE_GATES="merge", WORKS_USE_THICKNESS="x")
        self.assertEqual(r.returncode, 0, r.stderr)
        run = self.calls()[0]
        for want in ("final_gate=always", "policy_md=/p/policy.md", "gates=merge", "thickness=x"):
            self.assertIn(want, run)

    def test_answer_records_who_and_responds(self):
        """別の殻で打つ答えも、start の控え（<家>/runs/<id>.json）の模型・包みで Archon を起こす"""
        t = self.target()
        r = self.use("start", str(t), str(self.request), "true", "", WORKS_DEV_MODEL="sonnet", WORKS_DEV_ADAPTER="0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((self.home / "runs" / "run-1.json").read_text())["model"], "sonnet")
        # 別の殻の show が出す進める・続きの行も控えの模型・claude で組む（その殻の既定 opus に黙って替えない）
        for rid in ((), ("run-1",)):
            with self.subTest(show=rid):
                r = self.use("show", str(t), *rid, WORKS_DEV_MODEL=None, CLAUDE_BIN_PATH="/other/claude")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("run run-1 の控え（模型 sonnet・包み 0）で進める・続きの行を組む", r.stdout)
                self.assertNotIn("で Archon を起こす", r.stdout)   # show は Archon を起こさない
                for verb in ("approve", "resume"):
                    line = next(l for l in r.stdout.splitlines() if f"workflow {verb} run-1" in l)
                    self.assertIn("WORKS_DEV_MODEL=sonnet CLAUDE_BIN_PATH=/usr/bin/true ", line)
                    self.assertNotIn("WORKS_DEV_ADAPTER=1", line)
        r = self.use("answer", str(t), "run-1", "continue", "stats.py だけ", "依頼者", WORKS_DEV_MODEL=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("模型 sonnet・包み 0", r.stdout)
        self.assertEqual(self.calls()[-1][3:], ["workflow", "respond", "run-1", "continue", "stats.py だけ"])
        rows = [json.loads(ln) for ln in (self.home / "answers.jsonl").read_text().splitlines()]
        self.assertEqual([(x["run_id"], x["answer"], x["text"], x["by"]) for x in rows],
                         [("run-1", "continue", "stats.py だけ", "依頼者")])
        self.log.unlink()
        r = self.use("answer", str(t), "run-1", "maybe", "x")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("continue か stop", r.stderr)
        self.assertEqual(self.calls(), [])
        self.set_runs(status="running", working_path="/wt/run-1", output_root="/out")
        r = self.use("answer", str(t), "run-1", "stop", "x")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("paused", r.stderr)

    def test_stop_chooses_respond_or_stop_card(self):
        """止め方は 1 つ: 関所で待つ run は respond stop、走っている run は止め札（stop.sh。家は殻が埋める）"""
        t = self.target()
        r = self.use("stop", str(t), "run-1", "要らなくなった")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.calls()[-1][3:], ["workflow", "respond", "run-1", "stop", "要らなくなった"])
        self.set_runs(status="running", working_path="/wt/run-1", output_root="/out")
        self.log.unlink()
        r = self.use("stop", str(t), "run-1", "要らなくなった")
        self.assertIn(["workflow", "get", "run-1", "--json"], [c[3:] for c in self.calls()])
        self.assertTrue(all(c[2] == str(self.home) for c in self.calls()), self.calls())   # 家の変数を人が付けない

    def test_unattended_passes_launch_and_stops_at_human_gate(self):
        t = self.target()
        r = self.use("start", str(t), str(self.request), "true", "", WORKS_USE_UNATTENDED="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        verbs = [c[3:6] for c in self.calls()]
        self.assertIn(["workflow", "approve", "run-1"], verbs)
        self.assertIn(["workflow", "respond", "run-1"], verbs)
        respond = next(c for c in self.calls() if c[3:5] == ["workflow", "respond"])
        self.assertEqual(respond[6], "stop")
        self.assertIn("無人", respond[7])

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
            "--input", "tdd_suite=", "--input", "adapter=", "--input", "final_gate=when_needed"])
        self.assertIn("WORKS_DEV_ADAPTER=1 ", r.stdout)   # 何も付けない start は包みを入れる（続きの行も archon.sh に 1 を渡す）
        self.assertEqual(runs, [str(t), "1", str(self.home), "workflow", "runs", "--json"])
        out = r.stdout
        self.assertIn("run id: run-1", out)
        for verb in ("approve run-1", "resume run-1"):
            self.assertIn(f"workflow {verb}", out)
        # 関所の答えと止めるは殻の answer・stop だけ（生の respond・reject は答えた者の記録と控えを通らない）
        self.assertNotRegex(out, r"workflow (respond|reject) ")
        self.assertIn(f"{USE} answer {t} run-1 continue", out)
        self.assertIn(f"{USE} stop {t} run-1", out)
        # 進める・続きはその場で残りの工程を回すので、関所の文の答えの行の頭（WORKS_ANSWER_CMD）を行に載せる
        answer_head = f"sh {USE} answer {t}"
        for verb in ("approve", "resume"):
            line = next(l for l in out.splitlines() if f"workflow {verb} run-1" in l)
            self.assertIn(f"WORKS_ANSWER_CMD='{answer_head}' ", line)
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

    def test_start_failed_run_keeps_exit_code_without_traceback(self):
        t = self.target()
        self.fake.write_text(
            "#!/bin/sh\n"
            f'{{ printf \'%s\\t\' "$(pwd -P)" "${{WORKS_DEV_NO_AUTH:-}}" "${{WORKS_DEV_HOME:-}}" "$@"; echo; }} >> "{self.log}"\n'
            'case "$*" in "workflow runs --json") exit 0 ;; esac\n'
            "echo 'archon: 起動に失敗した' >&2\n"
            "exit 2\n")
        r = self.use("start", str(t), str(self.request), "true", "")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotIn("Traceback", r.stdout + r.stderr)
        self.assertIn("2", r.stdout + r.stderr)

    def test_start_reports_run_to_herdr_pane(self):
        t = self.target()
        fake_bin = self.tmp / "herdr-bin"
        fake_bin.mkdir()
        herdr_log = self.tmp / "herdr.txt"
        (fake_bin / "herdr").write_text(f'#!/bin/sh\necho "$*" >> "{herdr_log}"\nexit 0\n')
        (fake_bin / "herdr").chmod(0o755)
        path = str(fake_bin) + os.pathsep + os.environ.get("PATH", "")
        # herdr の下でない（HERDR_ENV が無い）なら何も呼ばない
        r = self.use("start", str(t), str(self.request), "true", "", PATH=path, HERDR_ENV=None, HERDR_PANE_ID=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(herdr_log.exists())
        # herdr の枠の中なら、その枠へ works の source で run の状態を出す
        r = self.use("start", str(t), str(self.request), "true", "", PATH=path, HERDR_ENV="1", HERDR_PANE_ID="pane-7")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(herdr_log.exists(), "herdr が呼ばれていない")
        calls = herdr_log.read_text().splitlines()
        self.assertTrue(any("pane-7" in c and "works" in c for c in calls), calls)

    def test_wait_returns_state_within_time(self):
        t = self.target()
        # 関所で待つ run: すぐ戻り、状態を 1 行で返す
        r = self.use("wait", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1")
        self.assertNotEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("run-1", r.stdout)
        self.assertIn("paused", r.stdout)
        gate_rc = r.returncode
        # 走っている run: 決まった時間で戻り、走っていると返す（終了コードで関所と見分ける）
        self.set_runs(status="running", working_path="/wt/run-1", output_root="/out")
        import time
        started = time.monotonic()
        r = self.use("wait", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1")
        self.assertLess(time.monotonic() - started, 20)
        self.assertNotEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertNotEqual(r.returncode, gate_rc, r.stdout)
        self.assertIn("running", r.stdout)

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
        # 問い合わせは 2 本: use.sh の show が控えを引く run_row と、lib.sh の works_dev_show_run。どちらも認証なし
        query = [str(t), "1", str(self.home), "workflow", "runs", "--json"]
        self.assertEqual(self.calls(), [query, query])
        diff = self.home / "diffs" / "run-run-1.diff"
        self.assertIn("+# 直した", diff.read_text())
        self.assertIn(f"git -C {t} apply {diff}", r.stdout)

    def test_show_diff_keeps_tracked_ignored_files(self):
        t = self.target()
        wt = self.tmp / "wt"
        committed_copy(wt, DEV / "target-seed")
        (wt / ".gitignore").write_text(".env*\n")
        (wt / ".env.example").write_text("KEY=\n")
        git(wt, "add", ".gitignore")
        git(wt, "add", "-f", ".env.example")
        git(wt, "commit", "-q", "-m", "無視に当たる追跡ファイル")
        base = git(wt, "rev-parse", "HEAD")
        (wt / "stats.py").write_text((wt / "stats.py").read_text() + "# 直した\n")
        board = self.tmp / "out" / "artifacts" / "runs" / "run-1" / "board"
        (board / "r1").mkdir(parents=True)
        (board / "r1" / "start.json").write_text(json.dumps({"base_rev": base}))
        self.set_runs(working_path=str(wt), output_root=str(self.tmp / "out"))
        r = self.use("show", str(t), CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        body = (self.home / "diffs" / "run-run-1.diff").read_text()
        self.assertIn("+# 直した", body)
        self.assertNotIn("deleted file", body)
        self.assertNotIn(".env.example", body)

    def test_show_picks_run_of_this_target(self):
        t = self.target()
        other = self.target("other")
        # 一番新しい run は別の対象の物（Archon の run の行の metadata.workflow_source.origin が起動した対象）
        self.runs.write_text(json.dumps({"runs": [
            {"id": "run-other", "workflow_name": "darkfactory", "status": "paused", "working_path": "/wt/other",
             "output_root": "/out", "metadata": {"workflow_source": {"origin": str(other)}}},
            {"id": "run-mine", "workflow_name": "darkfactory", "status": "paused", "working_path": "/wt/mine",
             "output_root": "/out", "metadata": {"workflow_source": {"origin": str(t)}}},
        ]}))
        r = self.use("show", str(t), CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("run id: run-mine", r.stdout)
        self.assertNotIn("run-other", r.stdout)

    def test_apply_brings_run_diff_into_target(self):
        t = self.target()
        wt = self.tmp / "wt"
        committed_copy(wt, DEV / "target-seed")
        base = git(wt, "rev-parse", "HEAD")
        (wt / "stats.py").write_text((wt / "stats.py").read_text() + "# 直した\n")
        board = self.tmp / "out" / "artifacts" / "runs" / "run-1" / "board"
        (board / "r1").mkdir(parents=True)
        (board / "r1" / "start.json").write_text(json.dumps({"base_rev": base}))
        self.set_runs(working_path=str(wt), output_root=str(self.tmp / "out"))
        r = self.use("apply", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue((t / "stats.py").read_text().endswith("# 直した\n"))
        self.assertEqual(git(t, "status", "--porcelain"), "M stats.py")

    def test_clean_removes_run_worktree_and_branch(self):
        t = self.target()
        wt = self.tmp / "run-wt"
        git(t, "worktree", "add", "-q", "-b", "archon/task-darkfactory-1", str(wt))
        self.set_runs(status="completed", working_path=str(wt), output_root=str(self.tmp / "out"))
        r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(wt.exists())
        self.assertEqual(git(t, "branch", "--list", "archon/task-darkfactory-1"), "")

    def test_check_lists_missing_auth_without_ai(self):
        """認証が無ければ、AI を起こさず（validate だけを認証を読ませずに呼ぶ）入れ方の 1 行つきで並べ、0 以外で終わる。
        ほかの欠け（uv・claude）も同じ出力に並べる。認証が在れば 0 で validate だけを呼ぶ"""
        t = self.target()
        path = self.no_keychain()
        r = self.use("check", str(t), CLAUDE_CODE_OAUTH_TOKEN=None, PATH=path)
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(self.calls(), [[str(t), "1", str(self.home), "validate", "workflows", "darkfactory"]])
        self.assertTrue((self.home / "archon-home" / "workflows" / "works" / "archon-plugin.json").is_file())
        lines = r.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, r.stderr)
        for word in ("認証が無い", "claude setup-token", "WORKS_KEYCHAIN_ITEM"):
            self.assertIn(word, lines[0])
        self.assertTrue((self.tmp / "no-keychain-bin" / "security.calls").exists())   # 偽の keychain だけを見た
        self.log.unlink()
        r = self.use("check", str(t), CLAUDE_CODE_OAUTH_TOKEN=None, PATH=path, CLAUDE_BIN_PATH="/nonexistent/claude")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 2, r.stderr)   # 認証と claude を一度に並べる
        self.log.unlink()
        r = self.use("check", str(t))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [[str(t), "1", str(self.home), "validate", "workflows", "darkfactory"]])

    # ---- git でない写し（プラグインのキャッシュ）から
    def plugin_copy(self):
        """works/ を git の外の、プラグインのキャッシュの形の置き場へ写し、(写し, 写しの use.sh を回す env) を返す。Archon は写しの
        archon.sh が exec する実行ファイル（利用の家の bin/ の偽物。偽の shasum で sha256 の確かめを通す）だけを偽物にし、写しの
        guard.sh・toolset.py は本物を回す。借りる物は偽の利用者の設定から、隔離した設定へ入れるのは偽の claude で"""
        from test_toolset import make_user_config, write_fake_claude
        copy = self.tmp / "user-claude-config" / "plugins" / "cache" / "works-mp" / "works" / "9.9.9"
        shutil.copytree(ROOT, copy, ignore=shutil.ignore_patterns("tests", "docs", "__pycache__"))
        (copy / ".in_use").mkdir()
        (copy / ".in_use" / "4242").write_text("{}")
        (copy / ".orphaned_at").write_text("1790054446372")
        # 写しの borrow.json だけ借りるスキルを 1 本減らす（元の works を読めば 1 本多く写り、見分けられる）
        borrow = copy / ".shared" / "borrow" / "borrow.json"
        doc = json.loads(borrow.read_text())
        self.copy_skills = doc["superpowers"]["skills"] = doc["superpowers"]["skills"][:-1]
        borrow.write_text(json.dumps(doc))
        user_cfg = make_user_config(self.tmp / "user-claude-config")
        sha = re.search(r'^ARCHON_SHA256="([0-9a-f]{64})"', (copy / "dev" / "archon.sh").read_text(), re.M).group(1)
        fake_bin = self.tmp / "fake-bin"
        claude = write_fake_claude(fake_bin)
        (fake_bin / "shasum").write_text(f'#!/bin/sh\necho "{sha}  $3"\n')
        (fake_bin / "shasum").chmod(0o755)
        self.skills_seen = self.tmp / "skills.txt"
        binary = self.home / "bin" / "archon-darwin-arm64"
        binary.parent.mkdir(parents=True)
        binary.write_text(
            "#!/bin/sh\n"
            f'{{ printf \'%s\\t\' "$(pwd -P)" "${{WORKS_DEV_NO_AUTH:-}}" "$WORKS_DEV_HOME" "$@"; echo; }} >> "{self.log}"\n'
            f'ls "$CLAUDE_CONFIG_DIR/skills" > "{self.skills_seen}"\n'
            f'case "$*" in "workflow runs --json") cat "{self.runs}" ;; esac\n'
            "exit 0\n")
        binary.chmod(0o755)
        self.claude_log = self.tmp / "claude-calls.jsonl"
        env = dict(script=copy / "dev" / "use.sh", WORKS_DEV_ARCHON=None, WORKS_REAL_CLAUDE=None, CLAUDE_CONFIG_DIR=str(user_cfg),
                   CLAUDE_BIN_PATH=str(claude), FAKE_CLAUDE_LOG=str(self.claude_log),
                   PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))
        return copy, env

    def assert_ran_from_copy(self, copy):
        """pack は写しから置かれ（出どころの控えは git の外として rev・dirty が null）、隔離した設定には写しの borrow.json の
        スキルが入り、Archon・claude・控えのどれも元のリポジトリの works を指さない"""
        pack = self.home / "archon-home" / "workflows" / "works"
        self.assertTrue((pack / "darkfactory" / "darkfactory.yaml").is_file())
        for d in ("tests", "dev", "docs", ".in_use", ".orphaned_at"):
            self.assertFalse((pack / d).exists(), d)
        source = json.loads((pack / ".works-source.json").read_text())
        self.assertEqual((source["rev"], source["dirty"], source["from"]), (None, None, str(copy)))
        self.assertEqual(sorted(self.skills_seen.read_text().split()), sorted(self.copy_skills))
        seen = [self.log.read_text(), (pack / ".works-source.json").read_text(),
                (self.home / "claude-config" / ".works-toolset.json").read_text()]
        if self.claude_log.exists():
            seen.append(self.claude_log.read_text())
        for text in seen:
            self.assertNotIn(str(ROOT), text)

    def test_check_from_non_git_copy(self):
        t = self.target()
        copy, env = self.plugin_copy()
        self.assertNotEqual(subprocess.run(["git", "-C", str(copy), "ls-files", "--error-unmatch", "dev/use.sh"],
                                           capture_output=True).returncode, 0)   # 写しは git の追跡の外
        r = self.use("check", str(t), **env)   # 認証を与えて 0（認証の欠けは test_check_lists_missing_auth_without_ai）
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.calls(), [[str(t), "1", str(self.home), "validate", "workflows", "darkfactory"]])
        self.assert_ran_from_copy(copy)
        self.assertFalse(self.claude_log.exists())   # 認証の要らない道は claude を起こさない

    def test_start_from_non_git_copy(self):
        t = self.target()
        head = git(t, "rev-parse", "HEAD")
        copy, env = self.plugin_copy()
        r = self.use("start", str(t), str(self.request), "true", "", **env)
        self.assertEqual(r.returncode, 0, r.stderr)
        run, runs = self.calls()
        self.assertEqual(run[:9], [str(t), "", str(self.home), "workflow", "run", "darkfactory", "--from", head, "--input"])
        self.assertEqual(runs, [str(t), "1", str(self.home), "workflow", "runs", "--json"])
        self.assert_ran_from_copy(copy)
        cfg = str(self.home / "claude-config")
        calls = [json.loads(ln) for ln in self.claude_log.read_text().splitlines()]
        self.assertIn(["plugin", "install", "coldwrite@works-local"], [c["argv"][:3] for c in calls])
        self.assertEqual({c["cfg"] for c in calls}, {cfg})   # claude は隔離した設定にだけ入れる
        self.assertIn("run id: run-1", r.stdout)


if __name__ == "__main__":
    unittest.main()
