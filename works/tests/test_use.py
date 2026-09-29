"""works/dev/use.sh（ほかのリポジトリを対象に darkfactory を回す起動の殻）の検査。Archon は偽物（sh の台本）に差し替え、AI は起こさない。

見る物:
- 拒む形（どれも Archon を呼ばず、pack も写さず、終了コード 2 と 1 行の理由）: 使い方の誤り・/private/tmp の下の対象・git の
  リポジトリの中でない・対象に pack の写し（.archon/workflows/works）が在る・対象に remote の origin が無い・依頼のファイルが無い・
  認証が無い（keychain は偽物）。commit していない変更・未追跡のファイル（包んで回す）・下のフォルダ（git の根で回す）・test_cmd を省くことは拒まない。
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
import hermetic  # noqa: E402

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
        env = hermetic.child_env()
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

    def test_start_change_entry_flags(self):
        """変更から入る口: 先頭の --base <版>・--pr <番号>（と --）を旗として読み、残りの位置引数に対象を省ける決まりを当てる。
        依頼の - は依頼を省き（request= は空）、Archon へ --input base=・pr= を渡し、『入口: 変更から』を出す。
        位置引数の後の --base は旗として読まない"""
        t = self.target()
        r = self.use("start", "--base", "main", "-", cwd=str(t))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = self.calls()[0]
        self.assertEqual(run[0], str(t))
        self.assertIn("base=main", run)
        self.assertIn("request=", run)
        self.assertIn("入口: 変更から（base=main）", r.stdout)
        self.assertFalse((self.home / "requests").exists())
        self.log.unlink()
        r = self.use("start", "--pr", "7", "--", str(t), "-", "true")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = self.calls()[0]
        self.assertIn("pr=7", run)
        self.assertIn("test_cmd=true", run)
        self.assertIn("入口: 変更から（pr=7）", r.stdout)
        self.log.unlink()
        r = self.use("start", "--base", "main", str(t), str(self.request))   # 依頼と変更の両方
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = self.calls()[0]
        self.assertIn("base=main", run)
        self.assertTrue(any(a.startswith("request=" + str(self.home / "requests")) for a in run), run)
        self.log.unlink()
        r = self.use("start", str(t), str(self.request), "--base", "main")   # 位置引数の後: test_cmd と tdd_suite
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = self.calls()[0]
        self.assertIn("test_cmd=--base", run)
        self.assertNotIn("base=main", run)
        self.assertNotIn("入口: 変更から", r.stdout)

    def test_start_change_entry_refusals(self):
        """依頼の - は --base か --pr が在る時だけ受け、--base と --pr の両方・値の無い旗は拒む（Archon を呼ばない）"""
        t = self.target()
        self.assert_refused(self.use("start", str(t), "-"), "--base", "--pr")
        self.assert_refused(self.use("start", "--base", "main", "--pr", "7", str(t), "-"), "--base", "--pr")
        for args in (("start", "--base"), ("start", "--pr", "", str(t), "-"), ("start", "--base", "main")):
            with self.subTest(args):
                r = self.use(*args)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
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

    def test_wrapped_base_is_kept_by_ref_until_clean(self):
        """包んだ commit（commit-tree で作り、どの枝にも無い run の基）は refs/works/ の下の参照で守り、git gc で消えない。
        対象の枝（refs/heads）・タグは動かさない。clean がその run と一緒に参照を消す"""
        t = self.target()
        heads = git(t, "for-each-ref", "refs/heads", "refs/tags")
        (t / "stats.py").write_text((t / "stats.py").read_text() + "# 手元の書き換え\n")
        r = self.use("start", str(t), str(self.request), "true", "")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = self.calls()[0]
        base = run[run.index("--from") + 1]
        refs = git(t, "for-each-ref", "--format=%(objectname) %(refname)", "refs/works/").splitlines()
        self.assertIn(base, [ln.split()[0] for ln in refs], refs)
        self.assertEqual(git(t, "for-each-ref", "refs/heads", "refs/tags"), heads)
        git(t, "gc", "-q", "--prune=now")
        self.assertEqual(git(t, "cat-file", "-t", base), "commit")
        wt = self.tmp / "run-wt"
        git(t, "worktree", "add", "-q", "-b", "archon/task-darkfactory-1", str(wt), base)
        self.set_runs(status="completed", working_path=str(wt), output_root=str(self.tmp / "out"))
        r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(git(t, "for-each-ref", "refs/works/"), "")

    def test_unbound_start_drops_wrap_ref(self):
        """start が run を結べず控えを書けない時は、clean が参照を知る口が無いので、包んだ基の参照をその場で外す"""
        t = self.target()
        (t / "stats.py").write_text((t / "stats.py").read_text() + "# 手元の書き換え\n")
        self.runs.write_text(json.dumps({"runs": []}))
        r = self.use("start", str(t), str(self.request), "true", "")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("結べなかった", r.stdout)
        self.assertIn("包んだ（wrapped）", r.stdout)
        self.assertEqual(git(t, "for-each-ref", "refs/works/"), "")
        self.assertFalse((self.home / "runs").exists() and os.listdir(self.home / "runs"))

    def test_refuses_target_without_origin(self):
        """origin の無い対象は Archon を呼ばずに 1 行で拒み、対象の remote は書き換えない"""
        t = self.target(origin=False)
        self.assert_refused(self.use("start", str(t), str(self.request), "true"), "origin", "git remote add origin")
        self.assertEqual(git(t, "remote"), "")

    def test_check_lists_missing_origin(self):
        """check は origin の無い対象を入れ方の行つきで並べ、validate は呼んだ上で 0 以外で終わる"""
        t = self.target(origin=False)
        r = self.use("check", str(t))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertEqual(self.calls(), [[str(t), "1", str(self.home), "validate", "workflows", "darkfactory"]])
        lines = r.stderr.strip().splitlines()
        self.assertEqual(len(lines), 1, r.stderr)
        for word in ("origin", "git remote add origin"):
            self.assertIn(word, lines[0])
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

    def test_answer_requires_who(self):
        """人が決める関所の答えは、答えた者を省いても空白でも拒む（殻を打った者 $USER に落とさない）。Archon を起こさず、記録も残さない"""
        t = self.target()
        for who in ((), ("  ",)):
            with self.subTest(who=who):
                r = self.use("answer", str(t), "run-1", "continue", "stats.py だけ", *who, USER="someone-else")
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("答えた者", r.stderr)
                self.assertNotIn(["workflow", "respond"], [c[3:5] for c in self.calls()])
                self.assertFalse((self.home / "answers.jsonl").exists())

    def test_answer_excludes_units_with_reason(self):
        """continue に --exclude <単位の番号>=<理由> を何度でも添えられ、{"exclude": [{unit, why}]} を run の盤面の
        answer-detail.json（同梱の graphloops 0.21.0 の線はまだ読まない置き場。answer が注意を出す）と answers.jsonl の行に残してから respond する。stop には添えられない"""
        t = self.target()
        board = self.tmp / "out" / "artifacts" / "runs" / "run-1" / "board"
        board.mkdir(parents=True)
        self.set_runs(working_path="/wt/run-1", output_root=str(self.tmp / "out"))
        r = self.use("answer", str(t), "run-1", "continue", "残りは直す", "依頼者",
                     "--exclude", "2=別の依頼で直す", "--exclude", "3=方針が決まってから")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        want = [{"unit": 2, "why": "別の依頼で直す"}, {"unit": 3, "why": "方針が決まってから"}]
        self.assertEqual(json.loads((board / "answer-detail.json").read_text()), {"exclude": want})
        rows = [json.loads(ln) for ln in (self.home / "answers.jsonl").read_text().splitlines()]
        self.assertEqual((rows[-1]["by"], rows[-1]["exclude"]), ("依頼者", want))
        self.assertEqual(self.calls()[-1][3:], ["workflow", "respond", "run-1", "continue", "残りは直す"])
        self.log.unlink()
        (board / "answer-detail.json").unlink()
        r = self.use("answer", str(t), "run-1", "stop", "やめる", "依頼者", "--exclude", "2=別の依頼で直す")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("--exclude", r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse((board / "answer-detail.json").exists())

    def test_gate_answer_line_shows_who_hole(self):
        """関所の文の答えの行（answer.line）は、殻が WORKS_ANSWER_WHO を置いていれば末尾に答えた者の穴を見せる
        （答えた者を必須にしたので、穴の無い行を写して打つと拒まれる）"""
        import sys
        sys.path.insert(0, str(ROOT / ".shared" / "core"))
        import answer
        env = {"WORKS_ANSWER_CMD": "sh /plug/dev/use.sh answer /repo", "WORKS_ANSWER_WHO": "<答えた者>"}
        self.assertEqual(answer.line("run-9", "continue", "<通す範囲と条件>", env=env),
                         'sh /plug/dev/use.sh answer /repo run-9 continue "<通す範囲と条件>" "<答えた者>"')
        self.assertEqual(answer.line("run-9", "stop", "<理由>", env={"WORKS_ANSWER_CMD": "x respond"}),
                         'x respond run-9 stop "<理由>"')

    def test_answer_and_approve_return_without_waiting_for_rest(self):
        """答え・承認は残りの工程をその場で回すので、殻が Archon の respond・approve を切り離して起こし、終わりを待たずに返る
        （成否は wait で見る）。残りの工程の出力は利用の家の下のログのファイルに残る"""
        import time
        t = self.target()
        self.fake.write_text(
            "#!/bin/sh\n"
            f'{{ printf \'%s\\t\' "$(pwd -P)" "${{WORKS_DEV_NO_AUTH:-}}" "${{WORKS_DEV_HOME:-}}" "$@"; echo; }} >> "{self.log}"\n'
            f'case "$*" in "workflow runs --json") cat "{self.runs}" ;; esac\n'
            'case "$1 $2" in "workflow respond" | "workflow approve") echo "残りの工程を回している: $2"; sleep 20 ;; esac\n'
            "exit 0\n")
        for args, verb in ((("answer", str(t), "run-1", "continue", "stats.py だけ", "依頼者"), "respond"),
                           (("approve", str(t), "run-1"), "approve")):
            with self.subTest(verb):
                started = time.monotonic()
                r = self.use(*args)
                self.assertLess(time.monotonic() - started, 10, r.stdout + r.stderr)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn(f"wait {t} run-1", r.stdout)
                logs = [p for p in self.home.rglob("*.log") if f"残りの工程を回している: {verb}" in p.read_text()]
                self.assertTrue(logs, sorted(str(p) for p in self.home.rglob("*")))

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
        # 線にも無人を知らせる（判定の保留の問いだけでは修正前の関所を開かない。gatemarks.unattended）
        run = next(c for c in self.calls() if c[3:5] == ["workflow", "run"])
        self.assertIn("unattended=true", run)

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

    def test_herdr_shows_pane_aggregate_and_releases_only_when_all_done(self):
        """herdr の枠の信号は、その枠から起こした run（控え）の集計の 1 つ。1 つの run が終わっても、同じ枠の別の run が走って
        いれば release せず working のまま。全部終わった時だけ release。その枠から起こした run が 0 なら herdr に何もしない"""
        t = self.target()
        out = self.tmp / "out"
        self.runs.write_text(json.dumps({"runs": []}))
        self.fake.write_text(
            "#!/bin/sh\n"
            f'{{ printf \'%s\\t\' "$(pwd -P)" "${{WORKS_DEV_NO_AUTH:-}}" "${{WORKS_DEV_HOME:-}}" "$@"; echo; }} >> "{self.log}"\n'
            f'case "$*" in "workflow runs --json") cat "{self.runs}"; exit 0 ;; esac\n'
            'case "$1 $2" in "workflow run") ;; *) exit 0 ;; esac\n'
            f'RUNS="{self.runs}" OUT="{out}" ORIGIN="{t}" python3 - "$@" <<\'EOF\'\n'
            "import json, os, pathlib, sys\n"
            "e = os.environ\n"
            "req = next(a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('request='))\n"
            "rows = json.loads(pathlib.Path(e['RUNS']).read_text())['runs']\n"
            "rid = 'run-{}'.format(len(rows) + 1)\n"
            "board = pathlib.Path(e['OUT'], 'artifacts', 'runs', rid, 'board', 'r1')\n"
            "board.mkdir(parents=True)\n"
            "(board / 'start.json').write_text(json.dumps({'request_file': req}))\n"
            "rows.insert(0, {'id': rid, 'workflow_name': 'darkfactory', 'status': 'paused', 'working_path': '/wt/' + rid,\n"
            "                'output_root': e['OUT'], 'metadata': {'workflow_source': {'origin': e['ORIGIN']}}})\n"
            "pathlib.Path(e['RUNS']).write_text(json.dumps({'runs': rows}))\n"
            "EOF\n"
            "exit 0\n")
        fake_bin = self.tmp / "herdr-bin"
        fake_bin.mkdir()
        herdr_log = self.tmp / "herdr.txt"
        (fake_bin / "herdr").write_text(f'#!/bin/sh\necho "$*" >> "{herdr_log}"\nexit 0\n')
        (fake_bin / "herdr").chmod(0o755)
        pane = dict(PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""), HERDR_ENV="1", HERDR_PANE_ID="pane-7")
        for _ in range(2):
            r = self.use("start", str(t), str(self.request), "true", "", **pane)
            self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(sorted(p.name for p in (self.home / "runs").glob("run-*.json")), ["run-1.json", "run-2.json"])

        def set_status(**by_id):
            doc = json.loads(self.runs.read_text())
            for row in doc["runs"]:
                row["status"] = by_id.get(row["id"], row["status"])
            self.runs.write_text(json.dumps(doc))

        # run-1 は終わったが、同じ枠の run-2 はまだ走っている: release せず working
        set_status(**{"run-1": "completed", "run-2": "running"})
        herdr_log.unlink(missing_ok=True)
        r = self.use("wait", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1", **pane)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        calls = herdr_log.read_text().splitlines() if herdr_log.exists() else []
        self.assertFalse(any(c.startswith("release-agent") for c in calls), calls)
        reports = [c for c in calls if c.startswith("report-agent")]
        self.assertTrue(reports and "--state working" in reports[-1] and "pane-7" in reports[-1], calls)
        # 全部終わった: その時だけ release
        set_status(**{"run-2": "completed"})
        herdr_log.unlink(missing_ok=True)
        r = self.use("wait", str(t), "run-2", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1", **pane)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        calls = herdr_log.read_text().splitlines() if herdr_log.exists() else []
        self.assertTrue(any(c.startswith("release-agent pane-7") for c in calls), calls)
        # この枠から起こした run が無い枠: herdr に何もしない
        herdr_log.unlink(missing_ok=True)
        r = self.use("wait", str(t), "run-2", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1",
                     **dict(pane, HERDR_PANE_ID="pane-9"))
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertFalse(herdr_log.exists(), herdr_log.read_text() if herdr_log.exists() else "")

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

    def fake_archon_with_concurrent_start(self, t):
        """workflow run のたびに、この起動の run（run-mine）と、同じ家から並べて起こした別の start の run（run-other。
        一覧の先頭＝一番新しい）を足す偽の Archon。どちらも盤面 r1/start.json と state.json の inputs に自分の依頼のパスを持つ"""
        out = self.tmp / "out"
        self.runs.write_text(json.dumps({"runs": []}))
        other_req = self.home / "requests" / "other-start.json"
        self.fake.write_text(
            "#!/bin/sh\n"
            f'{{ printf \'%s\\t\' "$(pwd -P)" "${{WORKS_DEV_NO_AUTH:-}}" "${{WORKS_DEV_HOME:-}}" "$@"; echo; }} >> "{self.log}"\n'
            f'case "$*" in "workflow runs --json") cat "{self.runs}"; exit 0 ;; esac\n'
            'case "$1 $2" in "workflow run") ;; *) exit 0 ;; esac\n'
            f'RUNS="{self.runs}" OUT="{out}" ORIGIN="{t}" OTHER_REQ="{other_req}" python3 - "$@" <<\'EOF\'\n'
            "import json, os, pathlib, sys\n"
            "args = sys.argv[1:]\n"
            "mine = next(a.split('=', 1)[1] for a in args if a.startswith('request='))\n"
            "e = os.environ\n"
            "rows = []\n"
            "for rid, req in (('run-other', e['OTHER_REQ']), ('run-mine', mine)):\n"
            "    board = pathlib.Path(e['OUT'], 'artifacts', 'runs', rid, 'board')\n"
            "    (board / 'r1').mkdir(parents=True, exist_ok=True)\n"
            "    (board / 'r1' / 'start.json').write_text(json.dumps({'request_file': req}))\n"
            "    (board / 'state.json').write_text(json.dumps({'inputs': {'request': req}}))\n"
            "    rows.append({'id': rid, 'workflow_name': 'darkfactory', 'status': 'paused', 'working_path': '/wt/' + rid,\n"
            "                 'output_root': e['OUT'], 'metadata': {'workflow_source': {'origin': e['ORIGIN']}}})\n"
            "pathlib.Path(e['RUNS']).write_text(json.dumps({'runs': rows}))\n"
            "EOF\n"
            "exit 0\n")

    def test_start_binds_its_own_run_not_newest_in_list(self):
        """start は一覧の先頭（一番新しい run）を推定で採らず、この起動の依頼（<家>/requests/<印>.json）で自分の run を 1 つに
        結ぶ。同じ家から並べて起こした別の start の run が先頭に在っても、控え・続きの行・run-id 無しの show は自分の run"""
        t = self.target()
        self.fake_archon_with_concurrent_start(t)
        r = self.use("start", str(t), str(self.request), "true", "")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("run id: run-mine", r.stdout)
        self.assertNotIn("run id: run-other", r.stdout)
        self.assertTrue((self.home / "runs" / "run-mine.json").is_file(), sorted(os.listdir(self.home / "runs")))
        self.assertFalse((self.home / "runs" / "run-other.json").exists())
        r = self.use("show", str(t), CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("run id: run-mine", r.stdout)

    def test_wait_does_not_find_run_of_other_target(self):
        """wait も show・answer と同じ選び方（darkfactory・この対象）で引く。別の対象の run id を渡しても見つからない"""
        t = self.target()
        other = self.target("other")
        self.runs.write_text(json.dumps({"runs": [
            {"id": "run-other", "workflow_name": "darkfactory", "status": "paused", "working_path": "/wt/other",
             "output_root": "/out", "metadata": {"workflow_source": {"origin": str(other)}}}]}))
        r = self.use("wait", str(t), "run-other", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("見つからない", r.stdout + r.stderr)
        self.assertNotIn("paused", r.stdout)

    def test_show_running_node_elapsed_alive_and_node_costs(self):
        """走っている run の show は、合計の費用の 1 行だけでなく、今走っている節・起こしてからの分（launched_min）・
        生きているか（alive）・節ごとの費用（cost_usd）を本流 graphloops の status と同じ欄名で出す。材料は Archon の
        `workflow get <id> --verbose --events --json` の出来事（node_started・node_completed の data.spend.costUsd）"""
        import datetime
        t = self.target()
        now = datetime.datetime.now(datetime.timezone.utc)
        started = (now - datetime.timedelta(minutes=12)).strftime("%Y-%m-%dT%H:%M:%S.000Z")
        recent = (now - datetime.timedelta(minutes=1)).strftime("%Y-%m-%d %H:%M:%S")
        self.set_runs(status="running", working_path="/wt/run-1", output_root=str(self.tmp / "out"), started_at=started,
                      last_activity_at=(now - datetime.timedelta(minutes=1)).strftime("%Y-%m-%dT%H:%M:%S.000Z"))

        def ev(kind, step, **data):
            return {"workflow_run_id": "run-1", "event_type": kind, "step_name": step, "data": data, "created_at": recent}
        got = dict(json.loads(self.runs.read_text())["runs"][0], events=[
            ev("workflow_started", None),
            ev("node_started", "p1.material"),
            ev("node_completed", "p1.material", spend={"costUsd": {"source": "provider", "value": 0.42}}),
            ev("node_started", "p1.intake"),
            ev("node_completed", "p1.intake", spend={"costUsd": {"source": "unavailable", "reason": "no-usage"}}),
            ev("node_started", "p2.diagnose"),
        ])
        get_json = self.tmp / "get.json"
        get_json.write_text(json.dumps(got))
        self.fake.write_text(
            "#!/bin/sh\n"
            f'{{ printf \'%s\\t\' "$(pwd -P)" "${{WORKS_DEV_NO_AUTH:-}}" "${{WORKS_DEV_HOME:-}}" "$@"; echo; }} >> "{self.log}"\n'
            f'case "$*" in "workflow runs --json") cat "{self.runs}" ;; "workflow get run-1"*) cat "{get_json}" ;; esac\n'
            "exit 0\n")
        r = self.use("show", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        out = r.stdout
        self.assertTrue(any("diagnose" in l for l in out.splitlines()), out)   # 走っている節
        self.assertRegex(out, r"launched_min\D{0,12}1[123]\b")
        self.assertRegex(out, r"(?i)alive\W{0,12}true")
        self.assertNotIn("report を読めない", out)
        self.assertTrue(any("material" in l and "cost_usd" in l and "0.42" in l for l in out.splitlines()), out)
        # 報告されなかった節は黙って落とさず、報告の費用の行と同じく件数と理由を出す（合計に数えない）
        self.assertTrue(any("cost_usd" in l and "取れない節" in l and "no-usage" in l for l in out.splitlines()), out)
        self.assertTrue(any("cost_usd" in l and "合計" in l and "0.42" in l and "途中" in l for l in out.splitlines()), out)

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
