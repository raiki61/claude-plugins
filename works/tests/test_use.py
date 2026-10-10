"""works/dev/use.sh（ほかのリポジトリを対象に darkfactory を回す起動の殻）の検査。Archon は偽物（sh の台本）に差し替え、AI は起こさない。

見る物:
- 拒む形（どれも Archon を呼ばず、pack も写さず、終了コード 2 と 1 行の理由）: 使い方の誤り・/private/tmp の下の対象・git の
  リポジトリの中でない・対象に pack の写し（.archon/workflows/works）が在る・対象に remote の origin が無い・依頼のファイルが無い・
  認証が無い（keychain は偽物）。commit していない変更・未追跡のファイル（包んで回す）・下のフォルダ（git の根で回す）・test_cmd を省くことは拒まない。
- start: pack（tests/・dev/・docs/ 抜き）を利用の家の Archon の全体の工程の置き場（<家>/archon-home/workflows/works）に写し、
  対象の中で `workflow run darkfactory --from <対象の HEAD>` を、写した依頼の絶対パス・test_cmd・tdd_suite・adapter=（包みを入れる既定。archon.sh に WORKS_DEV_ADAPTER=1）・final_gate=protected_only（既定）で呼び、WORKS_USE_FINAL_GATE=always を付けた時だけ
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
        self.out = self.tmp / "out"
        self.out.mkdir()
        self.set_runs(working_path="/wt/run-1", output_root=str(self.out))
        # workflow run は、一覧の run のうち output_root の在る物の盤面 r1/start.json に、この起動の依頼（request= の値。
        # 変更だけの起動は空）を書く（start が起動の直後に依頼で run を結ぶ材料。Archon の線の start と同じ欄）。読み出しの
        # 起動の印（launch_mark= の値）が在れば run-1 の metadata.inputs.launch_mark に残す（Archon が run に残す入力と同じ欄。
        # 依頼を省いた --pr の起動を結ぶ材料。FAKE_ARCHON_NO_LAUNCH_MARK が在れば残さない＝結べない --pr の形）。FAKE_ARCHON_RUN_EXIT が在れば
        # workflow run は何も残さずにその終了コードで終わる（起動が落ちた形）。FAKE_ARCHON_RUNS_FAIL が在れば workflow runs --json は
        # 何も出さずに落ちる（一覧が読めない形）。workflow abandon <id> は一覧のその run を cancelled にする（Archon v0.11.1 の
        # abandon と同じ。FAKE_ARCHON_ABANDON_EXIT が在れば何も変えずにその終了コードで落ちる）
        self.fake = self.tmp / "fake-archon.sh"
        self.fake.write_text(
            "#!/bin/sh\n"
            f'{{ printf \'%s\\t\' "$(pwd -P)" "${{WORKS_DEV_NO_AUTH:-}}" "${{WORKS_DEV_HOME:-}}" "$@"; echo; }} >> "{self.log}"\n'
            f'case "$*" in "workflow runs --json") [ -z "${{FAKE_ARCHON_RUNS_FAIL:-}}" ] || exit 1; cat "{self.runs}" ;; esac\n'
            'case "$1 $2" in "workflow abandon")\n'
            '  [ -z "${FAKE_ARCHON_ABANDON_EXIT:-}" ] || { echo "archon: abandon に失敗した" >&2; exit "$FAKE_ARCHON_ABANDON_EXIT"; }\n'
            f'  RUNS="{self.runs}" python3 -c \'import json, os, pathlib, sys\n'
            'p = pathlib.Path(os.environ["RUNS"]); d = json.loads(p.read_text())\n'
            'for r in d["runs"]:\n'
            '    r["status"] = "cancelled" if r.get("id") == sys.argv[1] else r["status"]\n'
            'p.write_text(json.dumps(d))\n'
            '\' "$3"; echo "Abandoned workflow run: $3"; exit 0 ;;\n'
            'esac\n'
            'case "$1 $2" in "workflow run") ;; *) exit 0 ;; esac\n'
            '[ -z "${FAKE_ARCHON_RUN_EXIT:-}" ] || exit "$FAKE_ARCHON_RUN_EXIT"\n'
            f'RUNS="{self.runs}" python3 - "$@" <<\'EOF\'\n'
            "import json, os, pathlib, sys\n"
            "req = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('request=')), '')\n"
            "mark = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('launch_mark=')), '')\n"
            "path = pathlib.Path(os.environ['RUNS'])\n"
            "listed = json.loads(path.read_text())\n"
            "for r in listed['runs']:\n"
            "    if r.get('output_root') and os.path.isdir(r['output_root']):\n"
            "        board = pathlib.Path(r['output_root'], 'artifacts', 'runs', r['id'], 'board', 'r1')\n"
            "        board.mkdir(parents=True, exist_ok=True)\n"
            "        (board / 'start.json').write_text(json.dumps({'request_file': req}))\n"
            "    if mark and r.get('id') == 'run-1' and not os.environ.get('FAKE_ARCHON_NO_LAUNCH_MARK'):\n"
            "        r.setdefault('metadata', {}).setdefault('inputs', {})['launch_mark'] = mark\n"
            "path.write_text(json.dumps(listed))\n"
            "EOF\n"
            "exit 0\n")

    def started(self):
        """偽の archon への呼び出しのうち、最初の起動（workflow run）。start は起動の前に前の run の片付けで一覧を引く"""
        return next(c for c in self.calls() if c[3:5] == ["workflow", "run"])

    def set_runs(self, **run):
        self.runs.write_text(json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": "paused", **run}]}))

    def target(self, name="target", origin=True, origin_head=None, tracking=("main",)):
        """origin を足す時は、tracking の各枝の追跡の ref（refs/remotes/origin/<枝>）を HEAD に置き、origin_head が在れば
        origin/HEAD をそこへ向ける（start が Archon の土台に渡す origin の既定の枝の材料。網には出ない）"""
        t = self.tmp / name
        committed_copy(t, DEV / "target-seed")
        if origin:
            git(t, "remote", "add", "origin", str(self.tmp / "origin.git"))
            for b in tracking:
                git(t, "update-ref", f"refs/remotes/origin/{b}", "HEAD")
            if origin_head:
                git(t, "symbolic-ref", "refs/remotes/origin/HEAD", f"refs/remotes/origin/{origin_head}")
        return t

    def use(self, *args, cwd=None, script=USE, **env_kw):
        env = hermetic.child_env()
        for name in ("CLAUDE_CODE_OAUTH_TOKEN", "WORKS_KEYCHAIN_ITEM", "WORKS_DEV_NO_AUTH", "WORKS_DEV_ADAPTER",
                     "WORKS_USE_FINAL_GATE"):
            env.pop(name, None)
        # 既定の家の根（XDG_STATE_HOME）も試験の一時の置き場に向ける。herdr の枠の集計は既定の家の全部を数えるので、向けないと
        # 利用者の本物の ~/.local/state/works の控えを読んで Archon を起こす（2026-09-29、121 件目の取り込みで実測）
        env.update(WORKS_USE_HOME=str(self.home), WORKS_DEV_HOME=str(self.dev_home), WORKS_DEV_ARCHON=str(self.fake),
                   CLAUDE_CODE_OAUTH_TOKEN="dummy-token-for-test", CLAUDE_BIN_PATH="/usr/bin/true",
                   XDG_STATE_HOME=str(self.home.parent / "xdg-state"))
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

    def gh_env(self, logged_in=True, **gh_kw):
        """偽の gh（test_ghreads.fake_gh）を PATH の頭に置く env。logged_in なら利用者のログイン（GH_CONFIG_DIR）が見える。
        HOME は空の置き場にし、本物の gh の設定を読ませない"""
        from test_ghreads import GH_ENV, fake_gh
        bin_, self.gh_calls_file, login = fake_gh(self.tmp, **gh_kw)
        env = {name: None for name in GH_ENV}
        (self.tmp / "user-home").mkdir(exist_ok=True)
        env.update(PATH=f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}", HOME=str(self.tmp / "user-home"))
        if logged_in:
            env["GH_CONFIG_DIR"] = str(login)
        return env

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
        run = self.started()
        self.assertIn("test_cmd=", run)
        self.assertIn("tdd_suite=", run)
        self.assertIn("test_cmd を省いた", r.stdout)
        (t / "sub").mkdir()
        self.log.unlink()
        r = self.use("start", str(self.request), cwd=str(t / "sub"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.started()[0], str(t))

    def test_start_change_entry_flags(self):
        """差分の根を名指す口: 先頭の --base <版>・--pr <番号>（と --）を旗として読み、残りの位置引数に対象を省ける決まりを当てる。
        依頼の - は依頼を省き（request= は空）、Archon へ --input base=・pr= を渡し、『差分の根: …』を出す。
        位置引数の後の --base は旗として読まない。どの起動も起動の印で run を結ぶ（--base だけの起動も結ぶ。段 4.1。
        test_start_binds_every_launch_by_launch_mark）"""
        t = self.target()
        r = self.use("start", "--base", "main", "-", cwd=str(t))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotIn("結べなかった", r.stdout)
        run = self.started()
        self.assertEqual(run[0], str(t))
        self.assertIn("base=main", run)
        self.assertIn("request=", run)
        self.assertIn("差分の根: base=main", r.stdout)
        self.assertFalse((self.home / "requests").exists())
        self.log.unlink()
        r = self.use("start", "--pr", "7", "--", str(t), "-", "true")   # PR は run の中の start が読む
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)   # 依頼を省いても起動の印で結ぶ
        run = self.started()
        self.assertIn("pr=7", run)
        self.assertIn("test_cmd=true", run)
        self.assertIn("差分の根: pr=7", r.stdout)
        self.log.unlink()
        r = self.use("start", "--base", "main", str(t), str(self.request))   # 依頼と変更の両方
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = self.started()
        self.assertIn("base=main", run)
        self.assertTrue(any(a.startswith("request=" + str(self.home / "requests")) for a in run), run)
        self.log.unlink()
        r = self.use("start", str(t), str(self.request), "--base", "main")   # 位置引数の後: test_cmd と tdd_suite
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = self.started()
        self.assertIn("test_cmd=--base", run)
        self.assertNotIn("base=main", run)
        self.assertNotIn("差分の根:", r.stdout)

    def test_use_spec_flag(self):
        """旗 --spec は Archon へ --input spec=on を渡し、仕様の段を挟むことを 1 行で出す（入口の旗と組める）。付けなければ渡さない"""
        t = self.target()
        r = self.use("start", "--spec", str(t), str(self.request), "true", "")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("spec=on", self.started())
        self.assertIn("仕様の段", r.stdout)
        self.log.unlink()
        r = self.use("start", "--base", "main", "--spec", str(t), str(self.request), "true", "")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertTrue({"spec=on", "base=main"} <= set(self.started()))
        self.log.unlink()
        r = self.use("start", str(t), str(self.request), "true", "")
        self.assertFalse([a for a in self.started() if a.startswith("spec=")])

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

    def test_start_leaves_github_reading_to_the_run(self):
        """依頼が {findings, pr, issue} で PR・issue を名指しても、殻は Archon を起こす前に gh を呼ばず、読み出しのファイルも
        入力 github_reads も作らない（名指しは run の中の start が利用者の gh のログインを継いで読む）"""
        t = self.target()
        r = self.use("start", str(t), str(self.named_request()), **self.gh_env())
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = self.started()
        self.assertFalse([a for a in run if a.startswith("github_reads=")], run)
        self.assertEqual(len([a for a in run if a.startswith("launch_mark=")]), 1, run)   # どの起動も印を 1 つ付ける（段 4.1）
        from test_ghreads import gh_calls
        self.assertEqual(gh_calls(self.gh_calls_file), [])
        self.assertFalse((self.home / "reads").exists())

    def test_start_binds_every_launch_by_launch_mark(self):
        """どの入口の起動（依頼だけ・--base だけ・--pr だけ）にも起動ごとに一意の印（入力 launch_mark。Archon が run の
        metadata.inputs に残す）を 1 つ付け、その一致で run を結んで 0 で終わる（入口の種類で結び方を分けない。段 4.1。
        前は --base だけの起動を結ばず 1 で終わった）。控えに読み出しのファイルの欄は無い。印を持つ run も依頼の写しを持つ
        run も無ければ推定で結ばない"""
        t = self.target()
        marks = []
        for args in (("start", str(t), str(self.request), "true", ""), ("start", "--base", "main", str(t), "-", "true", ""),
                     ("start", "--pr", "7", str(t), "-", "true", "")):
            with self.subTest(args[1]):
                r = self.use(*args)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertNotIn("結べなかった", r.stdout)
                given = [a.split("=", 1)[1] for a in self.started() if a.startswith("launch_mark=")]
                self.assertEqual(len(given), 1, self.started())
                self.assertTrue(given[0])
                marks.append(given[0])
                led = json.loads((self.home / "runs" / "run-1.json").read_text())
                self.assertEqual(led["run_id"], "run-1")
                self.assertNotIn("github_reads", led)
                self.log.unlink()
        self.assertEqual(len(set(marks)), 3, marks)
        r = self.use("start", "--pr", "7", str(t), "-", "true", "", FAKE_ARCHON_NO_LAUNCH_MARK="1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)   # 印を持つ run が無ければ推定で結ばない
        self.assertIn("結べなかった", r.stdout)

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
        run = self.started()
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
        run = self.started()
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
        run = self.started()
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

    def named_request(self):
        req = self.tmp / "named.json"
        req.write_text(json.dumps({"findings": [{"where": "stats.py:1", "text": "mean が空で落ちる"}], "pr": [7], "issue": [9]},
                                  ensure_ascii=False))
        return req

    def test_unbound_failed_start_drops_wrap_ref_with_candidates(self):
        """結べず Archon の起動も 0 以外で終わったなら、一覧に候補の run が在っても包んだ基の参照を外し、控えには残さない"""
        t = self.target()
        (t / "stats.py").write_text((t / "stats.py").read_text() + "# 手元の書き換え\n")
        r = self.use("start", str(t), str(self.request), "true", "", FAKE_ARCHON_RUN_EXIT="3")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("結べなかった", r.stdout)
        self.assertEqual(git(t, "for-each-ref", "refs/works/"), "")
        self.assertFalse((self.home / "unbound").exists() and os.listdir(self.home / "unbound"))

    def test_unbound_live_start_keeps_wrap_ref_and_clean_removes_it(self):
        """結べなくても Archon の起動が 0 で終わったなら run は生きていて包んだ基を使う。消さずに控えに残し、clean が片付ける"""
        t = self.target()
        (t / "stats.py").write_text((t / "stats.py").read_text() + "# 手元の書き換え\n")
        r = self.use("start", "--base", "HEAD", str(t), "-", "true", "", FAKE_ARCHON_NO_LAUNCH_MARK="1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)          # 印が run に残らず結べないので 1（続きの行は出さない）
        self.assertNotEqual(git(t, "for-each-ref", "refs/works/"), "")   # 包んだ参照が残る
        self.assertIn("use.sh clean", r.stdout)                          # 片付け方を 1 行で出す
        wt = self.tmp / "run-wt"
        git(t, "worktree", "add", "-q", "-b", "archon/task-darkfactory-1", str(wt))
        self.set_runs(status="completed", working_path=str(wt), output_root=str(self.tmp / "out2"))
        r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(git(t, "for-each-ref", "refs/works/"), "")
        self.assertEqual(list((self.home / "unbound").iterdir()), [])

    def test_unbound_clean_keeps_paths_while_another_candidate_lives(self):
        """結べない起動の控えに候補が 2 本在る時、終わった 1 本を clean しても、もう 1 本が生きて（paused）いる間は包んだ基を
        消さず、控えの候補からその run だけを外す。最後の候補の clean で全部消す（生きた run の使う物を消さない）"""
        t = self.target()
        (t / "stats.py").write_text((t / "stats.py").read_text() + "# 手元の書き換え\n")
        two = lambda first, wt="": self.runs.write_text(json.dumps({"runs": [
            {"id": "run-1", "workflow_name": "darkfactory", "status": first, "working_path": wt},
            {"id": "run-2", "workflow_name": "darkfactory", "status": "paused"}]}))
        two("paused")
        # 印を持つ起動（--pr）が結べない形（偽の archon が印を run に残さない）で回す
        r = self.use("start", "--pr", "7", str(t), "-", "true", "", FAKE_ARCHON_NO_LAUNCH_MARK="1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        [kept] = list((self.home / "unbound").iterdir())
        doc = json.loads(kept.read_text())
        self.assertEqual(doc["candidates"], ["run-1", "run-2"])
        self.assertNotIn("github_reads", doc)
        wt = self.tmp / "run-wt"
        git(t, "worktree", "add", "-q", "-b", "archon/task-darkfactory-1", str(wt))
        two("completed", str(wt))
        r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotEqual(git(t, "for-each-ref", "refs/works/"), "")
        self.assertEqual(json.loads(kept.read_text())["candidates"], ["run-2"])
        self.assertFalse(wt.exists())                                     # run の worktree は今どおり片付ける
        self.runs.write_text(json.dumps({"runs": [{"id": "run-2", "workflow_name": "darkfactory", "status": "completed"}]}))
        r = self.use("clean", str(t), "run-2", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(git(t, "for-each-ref", "refs/works/"), "")
        self.assertEqual(list((self.home / "unbound").iterdir()), [])

    def test_unbound_unreadable_list_keeps_wrap_ref_until_no_run_lives(self):
        """起動は 0 で終わったが run の一覧が読めない（runs --json が落ちる）時は、生きた run が在るか分からないので包んだ基の参照を
        消さず、候補の無い控え（unknown）に残して 1 で終わる。clean は一覧が読めた時、この対象の生きた run が
        在る間は残し、1 本も無くなった時に消す（迷ったら残す）"""
        t = self.target()
        (t / "stats.py").write_text((t / "stats.py").read_text() + "# 手元の書き換え\n")
        r = self.use("start", "--pr", "7", str(t), "-", "true", "", FAKE_ARCHON_RUNS_FAIL="1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("消さずに残した", r.stdout)
        self.assertNotEqual(git(t, "for-each-ref", "refs/works/"), "")
        [kept] = list((self.home / "unbound").iterdir())
        doc = json.loads(kept.read_text())
        self.assertEqual((doc["candidates"], doc["unknown"]), ([], True))
        self.assertNotIn("github_reads", doc)
        wt = self.tmp / "run-wt"
        git(t, "worktree", "add", "-q", "-b", "archon/task-darkfactory-1", str(wt))
        two = lambda second: self.runs.write_text(json.dumps({"runs": [
            {"id": "run-1", "workflow_name": "darkfactory", "status": "completed", "working_path": str(wt)},
            {"id": "run-2", "workflow_name": "darkfactory", "status": second}]}))
        two("paused")
        r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertNotEqual(git(t, "for-each-ref", "refs/works/"), "")
        self.assertTrue(kept.exists())
        two("completed")
        r = self.use("clean", str(t), "run-2", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(git(t, "for-each-ref", "refs/works/"), "")
        self.assertEqual(list((self.home / "unbound").iterdir()), [])

    def test_unbound_malformed_runs_list_is_unreadable_not_zero_candidates(self):
        """一覧の runs が null・dict・鍵なし・配列でも、読めた 0 本とは別に『読めない』として残す側に倒れる（例外で空に畳まない）"""
        t = self.target()
        (t / "stats.py").write_text((t / "stats.py").read_text() + "# 手元の書き換え\n")
        for i, body in enumerate(('{"runs": null}', '{"runs": {}}', "{}", "[]")):
            with self.subTest(body):
                self.runs.write_text(body)
                r = self.use("start", "--base", "HEAD", str(t), "-", "true", "")
                self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
                self.assertIn("launch.py: archon workflow runs --json の出力が JSON として読めない", r.stderr)   # 偽の archon の落ちとは別に、部品が理由を言う
                self.assertNotEqual(git(t, "for-each-ref", "refs/works/"), "", body)
                self.assertEqual(len(list((self.home / "unbound").iterdir())), i + 1)
                (t / "stats.py").write_text((t / "stats.py").read_text() + f"# 書き換え {i}\n")

    def test_unbound_save_write_failure_does_not_claim_a_control_was_kept(self):
        """一覧が読めない時に控えを書けない（置き場が書けない）なら、「控えに残した」と案内せず、控えが無いことと手で外す物を言う。
        包んだ基と読み出しは消さない（迷ったら残す）"""
        t = self.target()
        (t / "stats.py").write_text((t / "stats.py").read_text() + "# 手元の書き換え\n")
        self.home.mkdir(parents=True, exist_ok=True)
        (self.home / "unbound").write_text("ファイルが置き場の名を塞ぐ\n")
        r = self.use("start", "--base", "HEAD", str(t), "-", "true", "", FAKE_ARCHON_RUNS_FAIL="1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("控えも書けなかった", r.stdout)
        self.assertNotIn("控え " + str(self.home / "unbound"), r.stdout)
        self.assertNotEqual(git(t, "for-each-ref", "refs/works/"), "")

    def test_unbound_clean_releases_every_control_naming_the_run(self):
        """印の無い起動を 2 本並べると、後の起動の控えには前の起動の run も候補に載る。後の run を先に片付け、次に前の run を
        片付けると、1 回の clean でその run を候補に持つ控えを全部片付ける（後の控えの包んだ基を残さない）"""
        t = self.target()
        live = lambda *ids, status="paused": self.runs.write_text(json.dumps({"runs": [
            {"id": i, "workflow_name": "darkfactory", "status": status} for i in ids]}))
        (t / "stats.py").write_text((t / "stats.py").read_text() + "# 起動 A の手元\n")
        live("run-1")
        self.assertEqual(self.use("start", "--base", "HEAD", str(t), "-", "true", "", FAKE_ARCHON_NO_LAUNCH_MARK="1").returncode, 1)
        (t / "stats.py").write_text((t / "stats.py").read_text() + "# 起動 B の手元\n")
        live("run-1", "run-2")
        self.assertEqual(self.use("start", "--base", "HEAD", str(t), "-", "true", "", FAKE_ARCHON_NO_LAUNCH_MARK="1").returncode, 1)
        self.assertEqual(len(git(t, "for-each-ref", "refs/works/").splitlines()), 2)
        self.assertEqual(sorted(json.loads(p.read_text())["candidates"] for p in (self.home / "unbound").iterdir()),
                         [["run-1"], ["run-1", "run-2"]])
        self.runs.write_text(json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": "paused"},
                                                  {"id": "run-2", "workflow_name": "darkfactory", "status": "completed"}]}))
        r = self.use("clean", str(t), "run-2", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(len(git(t, "for-each-ref", "refs/works/").splitlines()), 2)
        live("run-1", "run-2", status="completed")
        r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(git(t, "for-each-ref", "refs/works/"), "")
        self.assertEqual(list((self.home / "unbound").iterdir()), [])

    def test_clean_refuses_live_run(self):
        """走っている・関所で待つ run（生きた状態の一覧は launch.py の LIVE_STATUSES）は片付けない"""
        t = self.target()
        for status in ("running", "pending", "paused"):
            with self.subTest(status=status):
                self.set_runs(status=status)
                r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn(f"use.sh: run run-1 は {status}", r.stderr)
        self.set_runs(status="failed")
        self.assertEqual(self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None).returncode, 0)

    def abandons(self):
        """偽の archon への workflow abandon の呼び出し（[認証を読まない印, run-id] の並び）"""
        return [[c[1], c[-1]] for c in self.calls() if c[3:5] == ["workflow", "abandon"]]

    def test_clean_failed_run_abandons_record_and_updates_herdr_pane(self):
        """落ちた run（failed）の Archon の記録は「resume できる＝人の番」と言い続け、herdr の枠は blocked のまま残った
        （2026-10-09 の利用者の声）。片付けた run は resume できないので、片付けが済んだ後に記録を abandon で閉じ（cancelled）、
        run を起こした枠の集計を出し直す"""
        t = self.target()
        wt = self.tmp / "run-wt"
        git(t, "worktree", "add", "-q", "-b", "archon/task-darkfactory-1", str(wt))
        self.set_runs(status="failed", working_path=str(wt), output_root=str(self.tmp / "out"))
        (self.home / "runs").mkdir(parents=True)
        (self.home / "runs" / "run-1.json").write_text(json.dumps({"run_id": "run-1", "target": str(t), "herdr_pane": "pane-7",
                                                                   "herdr_socket": ""}))
        fake_bin, herdr_log = hermetic.fake_herdr(self.tmp)
        r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None,
                     PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""), HERDR_ENV=None, HERDR_PANE_ID=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(wt.exists())
        self.assertEqual(self.abandons(), [["1", "run-1"]])
        self.assertEqual(json.loads(self.runs.read_text())["runs"][0]["status"], "cancelled")
        self.assertIn("Archon の記録を閉じた", r.stdout)
        sent = [a for _, a in hermetic.herdr_sockets(herdr_log)]
        self.assertTrue(sent and sent[-1].startswith("pane release-agent pane-7 "), sent)

    def test_clean_done_run_does_not_abandon(self):
        """正常に終わった・取り消した run（launch.py の DONE_STATUSES）の記録は既に閉じているので abandon しない"""
        t = self.target()
        for status in ("completed", "cancelled"):
            with self.subTest(status=status):
                self.log.unlink(missing_ok=True)
                self.set_runs(status=status, working_path=str(self.tmp / "gone-wt"), output_root=str(self.tmp / "out"))
                r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(self.abandons(), [])

    def test_clean_again_abandons_failed_record_whose_worktree_is_gone(self):
        """前の版の clean で worktree だけが消え、記録が failed のまま残った run も、clean の打ち直しで閉じる（残りの直し方）"""
        t = self.target()
        wt = self.tmp / "run-wt"
        git(t, "worktree", "add", "-q", "-b", "archon/task-darkfactory-1", str(wt))
        self.set_runs(status="failed", working_path=str(wt), output_root=str(self.tmp / "out"))
        self.assertEqual(self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None).returncode, 0)
        self.assertFalse(wt.exists())
        self.set_runs(status="failed", working_path=str(wt), output_root=str(self.tmp / "out"))
        r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("もう無い", r.stdout)
        self.assertEqual(self.abandons(), [["1", "run-1"], ["1", "run-1"]])
        self.assertEqual(json.loads(self.runs.read_text())["runs"][0]["status"], "cancelled")

    def test_clean_reports_abandon_failure_after_cleanup(self):
        """abandon が落ちても片付けは済んでいる。片付けの行は出したまま、標準エラーに落ちたことと手で閉じる行を出し、
        abandon の終了コードで終わる"""
        t = self.target()
        wt = self.tmp / "run-wt"
        git(t, "worktree", "add", "-q", "-b", "archon/task-darkfactory-1", str(wt))
        self.set_runs(status="failed", working_path=str(wt), output_root=str(self.tmp / "out"))
        r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None, FAKE_ARCHON_ABANDON_EXIT="4")
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertFalse(wt.exists())
        self.assertIn("worktree を消した", r.stdout)
        self.assertIn("abandon に失敗した", r.stderr)
        self.assertIn("workflow abandon run-1", r.stderr)
        self.assertIn(f"clean {t} run-1", r.stderr)
        self.assertEqual(json.loads(self.runs.read_text())["runs"][0]["status"], "failed")

    def test_clean_does_not_abandon_when_cleanup_fails(self):
        """片付けが落ちた run は記録を閉じない（片付けの打ち直しを待つ）"""
        t = self.target()
        plain = self.tmp / "not-a-worktree"
        plain.mkdir()
        self.set_runs(status="failed", working_path=str(plain), output_root=str(self.tmp / "out"))
        r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(self.abandons(), [])

    def test_clean_stops_when_live_check_fails(self):
        """生きているかの確かめ（launch.py ledger live）が落ちたら、生きていないと読まずに 2 で止まり、worktree も枝も消さない
        （消す前の関所は、迷ったら閉じる）"""
        t = self.target()
        wt = self.tmp / "run-wt"
        git(t, "worktree", "add", "-q", "-b", "archon/task-darkfactory-1", str(wt))
        self.set_runs(status="paused", working_path=str(wt), output_root=str(self.tmp / "out"))
        # ledger live の呼び出しだけを落とす python3 を PATH の頭に置く（ほかの呼び出しは本物へ渡す）
        bin_ = self.tmp / "broken-live-bin"
        bin_.mkdir()
        (bin_ / "python3").write_text(
            "#!/bin/sh\n"
            'case " $* " in *" ledger live "*) echo "launch.py: 壊れた" >&2; exit 1 ;; esac\n'
            f'exec "{shutil.which("python3")}" "$@"\n')
        (bin_ / "python3").chmod(0o755)
        r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None,
                     PATH=f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}")
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertTrue(wt.exists())
        self.assertNotEqual(git(t, "branch", "--list", "archon/task-darkfactory-1"), "")

    def test_refuses_target_without_origin(self):
        """origin の無い対象は Archon を呼ばずに 1 行で拒み、対象の remote は書き換えない"""
        t = self.target(origin=False)
        self.assert_refused(self.use("start", str(t), str(self.request), "true"), "origin", "git remote add origin")
        self.assertEqual(git(t, "remote"), "")

    def test_start_passes_origin_default_branch_as_archon_base(self):
        """Archon は codebase の登録の時の枝を覚えて更新しない。start は毎回 origin の既定の枝を --base で渡す
        （origin/HEAD が先、無ければ origin/main、次に origin/master）。読むのは workflow run darkfactory の行の --from より
        後ろの --base（入口の旗 --base <版> と取り違えない）"""
        cases = [(dict(origin_head="develop", tracking=("main", "develop")), "develop"),   # origin/HEAD が勝つ
                 (dict(tracking=("main",)), "main"),
                 (dict(tracking=("master",)), "master"),
                 (dict(tracking=("main", "master")), "main"),                         # main が master より先
                 # 改名（master → main）の後の fetch --prune: origin/HEAD は消えた枝を指したまま残る。渡さずに origin/main へ進む
                 (dict(origin_head="master", tracking=("main",)), "main"),
                 # 手元に origin/main という名の枝が在っても、remotes/origin/main でなく main を渡す
                 (dict(origin_head="main", tracking=("main",), local_branch="origin/main"), "main")]
        for i, (kw, want) in enumerate(cases):
            with self.subTest(kw=kw, want=want):
                local_branch = kw.pop("local_branch", None)
                t = self.target(f"t{i}", **kw)
                if local_branch:
                    git(t, "branch", local_branch)
                r = self.use("start", str(t), str(self.request), "true", "")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                run = next(c for c in self.calls() if c[0] == str(t) and c[3:6] == ["workflow", "run", "darkfactory"])
                after_from = run[run.index("--from"):]
                self.assertIn("--base", after_from, run)
                self.assertEqual(after_from[after_from.index("--base") + 1], want)

    def test_start_refuses_when_origin_default_branch_is_unknown(self):
        """origin の追跡の枝が 1 つも無ければ、土台の枝を推さずに git fetch origin を案内して止まり、Archon を起こさない。
        依頼の写し・pack の写しも作らない（何かを作る前に止める）"""
        t = self.target(tracking=())
        r = self.use("start", str(t), str(self.request), "true", "")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("origin の既定の枝", r.stderr)
        self.assertIn("git fetch origin", r.stderr)
        self.assertFalse(any(c[3:6] == ["workflow", "run", "darkfactory"] for c in self.calls()), "拒んだのに Archon を起こした")
        self.assert_refused(r, "origin の既定の枝", "git fetch origin", "git remote set-head origin")
        self.assertFalse((self.home / "requests").exists())

    def test_start_refusal_names_set_head_for_feature_branch_only_origin(self):
        """手元だけの手順（裸の origin に機能の枝だけを push した対象）では追跡の枝は origin/feat/x だけで、git fetch origin を
        打っても origin/HEAD はできない。拒みの文は git remote set-head origin を案内し、それで origin/HEAD を置けば start は
        その枝を --base に渡す（枝は推さない）"""
        t = self.target(tracking=("feat/x",))
        r = self.use("start", str(t), str(self.request), "true", "")
        self.assert_refused(r, "origin の既定の枝", "git remote set-head origin")
        git(t, "remote", "set-head", "origin", "feat/x")
        r = self.use("start", str(t), str(self.request), "true", "")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        run = next(c for c in self.calls() if c[3:6] == ["workflow", "run", "darkfactory"])
        after_from = run[run.index("--from"):]
        self.assertEqual(after_from[after_from.index("--base") + 1], "feat/x")

    def test_check_lists_unknown_default_branch(self):
        """追跡の枝が 1 つも無い対象を、check も start と同じ『origin の既定の枝が分からない』で並べて 0 以外で終わる（start だけが
        拒まない）。origin が無い対象では重ねて出さない"""
        t = self.target(tracking=())
        r = self.use("check", str(t), CLAUDE_BIN_PATH="/nonexistent/claude")   # 後ろの条件の不足も並ぶ（最初の 1 つで止まらない）
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("origin の既定の枝が分からない", r.stderr)
        self.assertIn("git remote set-head origin", r.stderr)
        self.assertIn("claude の実行ファイルが無い", r.stderr)
        r = self.use("check", str(self.target("no-origin", origin=False)))
        self.assertNotIn("origin の既定の枝", r.stderr)

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

    def keychain_with(self, service):
        """service の名の項目だけが在る偽の security を頭に置いた PATH（本物の keychain は読まない）"""
        fake_bin = self.tmp / "keychain-bin"
        fake_bin.mkdir(exist_ok=True)
        (fake_bin / "security").write_text(
            '#!/bin/sh\necho "$*" >> "$0.calls"\n'
            'prev=\nfor a in "$@"; do\n'
            f'  if [ "$prev" = -s ] && [ "$a" = "{service}" ]; then echo sk-ant-oat01-fake-for-test; exit 0; fi\n'
            '  prev=$a\ndone\nexit 44\n')
        (fake_bin / "security").chmod(0o755)
        return str(fake_bin) + os.pathsep + os.environ.get("PATH", "")

    @unittest.skipUnless(os.uname().sysname == "Darwin", "SKIP macos: keychain の段は macOS だけ")
    def test_check_finds_keychain_item_of_main_auth_order(self):
        """認証の順は本流 claude_auth.py の keychain_service に従う: CLAUDE_KEYCHAIN_SERVICE の名の項目、無ければ
        CLAUDE_CONFIG_DIR の末尾から導いた claude-code-oauth-<名>（~/.claude なら default）。そこにだけ項目が在れば check は通る"""
        t = self.target()
        cases = (("CLAUDE_KEYCHAIN_SERVICE", "svc-for-test", {"CLAUDE_KEYCHAIN_SERVICE": "svc-for-test"}),
                 ("CLAUDE_CONFIG_DIR", "claude-code-oauth-p3", {"CLAUDE_CONFIG_DIR": str(self.tmp / ".claude-p3")}))
        for label, service, env_kw in cases:
            with self.subTest(label):
                if self.log.exists():
                    self.log.unlink()
                r = self.use("check", str(t), CLAUDE_CODE_OAUTH_TOKEN=None, PATH=self.keychain_with(service), **env_kw)
                self.assertNotIn("sk-ant-oat01-fake-for-test", r.stdout + r.stderr)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)

    def test_start_adapter_default_and_explicit_off(self):
        """包みは既定で入れる（adapter= と続きの行の WORKS_DEV_ADAPTER=1）。0 か空を明示した時だけ adapter=optional と『包み無し』"""
        t = self.target()
        for value in ("0", ""):
            with self.subTest(value):
                self.log.unlink(missing_ok=True)
                r = self.use("start", str(t), str(self.request), "true", "", WORKS_DEV_ADAPTER=value)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("adapter=optional", self.started())
                self.assertTrue(r.stdout.startswith("包み無し"), r.stdout)
                self.assertNotIn("WORKS_DEV_ADAPTER=1 ", r.stdout)

    def test_start_final_gate_always_when_explicit_and_inputs(self):
        t = self.target()
        r = self.use("start", str(t), str(self.request), "true", "", WORKS_USE_FINAL_GATE="always",
                     WORKS_USE_POLICY_MD="/p/policy.md", WORKS_USE_GATES="merge", WORKS_USE_THICKNESS="x",
                     WORKS_USE_FEATURES_OFF="judge_verify,tdd_lanes", WORKS_USE_FEATURES_ON="review_tree")
        self.assertEqual(r.returncode, 0, r.stderr)
        run = self.started()
        for want in ("final_gate=always", "policy_md=/p/policy.md", "gates=merge", "thickness=x",
                     "features_off=judge_verify,tdd_lanes", "features_on=review_tree"):
            self.assertIn(want, run)

    def test_start_fix_fixture_passes_absolute_folder_or_refuses(self):
        """WORKS_USE_FIX_FIXTURE（固定材料のフォルダ）が空でなければ在るフォルダかを確かめ、入力 fix_fixture=<絶対パス> を渡す
        （相対は殻を打ったフォルダから）。未設定・空では渡さない。無いフォルダは Archon を呼ばず・家に何も作らずに 1 行で 2"""
        t = self.target()
        fx = self.tmp / "fx"
        fx.mkdir()
        for value, cwd, want in ((str(fx), None, f"fix_fixture={fx.resolve()}"), ("fx", str(self.tmp), f"fix_fixture={fx.resolve()}"),
                                 (None, None, ""), ("", None, "")):
            with self.subTest(value=value):
                self.log.unlink(missing_ok=True)
                r = self.use("start", str(t), str(self.request), "true", "", cwd=cwd, WORKS_USE_FIX_FIXTURE=value)
                self.assertEqual(r.returncode, 0, r.stderr)
                got = [a for a in self.started() if a.startswith("fix_fixture=")]
                self.assertEqual(got, [want] if want else [])
        self.log.unlink(missing_ok=True)
        shutil.rmtree(self.home, ignore_errors=True)
        r = self.use("start", str(t), str(self.request), "true", "", WORKS_USE_FIX_FIXTURE=str(self.tmp / "nowhere"))
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn(f"WORKS_USE_FIX_FIXTURE は在る固定材料のフォルダ（前の run の $ARTIFACTS_DIR/fix-fixture の写し）。受けた値: {self.tmp / 'nowhere'}", r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertEqual(self.calls(), [])
        self.assertFalse(self.home.exists())

    def test_answer_records_who_and_responds(self):
        """別の殻で打つ答えも、start の控え（<家>/runs/<id>.json）の模型・包みで Archon を起こす"""
        probe = hermetic.other_model()
        t = self.target()
        r = self.use("start", str(t), str(self.request), "true", "", WORKS_DEV_MODEL=probe, WORKS_DEV_ADAPTER="0")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((self.home / "runs" / "run-1.json").read_text())["model"], probe)
        # 別の殻の show が出す進める・続きの行も控えの模型・claude で組む（その殻の既定に黙って替えない）
        for rid in ((), ("run-1",)):
            with self.subTest(show=rid):
                r = self.use("show", str(t), *rid, WORKS_DEV_MODEL=None, CLAUDE_BIN_PATH="/other/claude")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn(f"run run-1 の控え（模型 {probe}・包み 0）で進める・続きの行を組む", r.stdout)
                self.assertNotIn("で Archon を起こす", r.stdout)   # show は Archon を起こさない
                for verb in ("approve", "resume"):
                    line = next(l for l in r.stdout.splitlines() if f"workflow {verb} run-1" in l)
                    self.assertIn(f"WORKS_DEV_MODEL={probe} CLAUDE_BIN_PATH=/usr/bin/true ", line)
                    self.assertNotIn("WORKS_DEV_ADAPTER=1", line)
        r = self.use("answer", str(t), "run-1", "continue", "stats.py だけ", "依頼者", WORKS_DEV_MODEL=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn(f"模型 {probe}・包み 0", r.stdout)
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

    def test_answer_refuses_exclude_before_writing(self):
        """同梱の線は外す単位を読まないので、--exclude は continue でも stop でも何かを書く前に 1 行で拒み、外したい単位は
        一言に書くよう案内する（answer-detail.json も answers.jsonl の行も書かず、respond を起こさない）"""
        t = self.target()
        board = self.tmp / "out" / "artifacts" / "runs" / "run-1" / "board"
        board.mkdir(parents=True)
        self.set_runs(working_path="/wt/run-1", output_root=str(self.tmp / "out"))
        for verb in ("continue", "stop"):
            with self.subTest(verb=verb):
                r = self.use("answer", str(t), "run-1", verb, "残りは直す", "依頼者", "--exclude", "2=別の依頼で直す")
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                lines = r.stderr.strip().splitlines()
                self.assertEqual(len(lines), 1, r.stderr)
                self.assertIn("--exclude", lines[0])
                self.assertIn("一言", lines[0])
                self.assertEqual(self.calls(), [])
                self.assertFalse((board / "answer-detail.json").exists())
                self.assertFalse((self.home / "answers.jsonl").exists())

    def test_exclude_guidance_agrees_with_gate_quote_note(self):
        """利用者の案内（SKILL.md）・使い方（use.sh）は --exclude を案内せず、関所の文の QUOTE_NOTE と同じく
        外す口はこの関所に無いと言う（3 か所が逆を指さない）"""
        import sys
        sys.path.insert(0, str(ROOT / ".shared" / "core"))
        import gatemarks
        self.assertIn("--detail（単位を外す）はこの関所に無い", gatemarks.QUOTE_NOTE)
        self.assertNotIn("--exclude", (ROOT / "skills" / "works" / "SKILL.md").read_text(encoding="utf-8"))
        r = self.use()
        self.assertNotIn("--exclude", r.stdout + r.stderr)

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
        # 止めた後に、答えの下書きの置き場を言う（機械は関所に答えない。実の利用者の run ac9e02ab）
        self.assertIn("次の run の依頼の下書き", r.stdout)
        self.assertIn("answers", r.stdout)
        # 線にも無人を知らせる（判定の保留の問いだけでは修正前の関所を開かない。gatepolicy.unattended）
        run = next(c for c in self.calls() if c[3:5] == ["workflow", "run"])
        self.assertIn("unattended=true", run)

    def test_design_only_passes_input_only_when_asked(self):
        """WORKS_DESIGN_ONLY=1 だけが線に design_only=true を渡す（修正前の関所を必ず開ける。gatemarks.design_only）。
        未設定・空では run の行に design_only が載らない（1 の外の値は test_start_refuses_switch_outside_one が止める）"""
        for value, want in ((None, False), ("", False), ("1", True)):
            with self.subTest(value=value):
                self.setUp()
                t = self.target()
                r = self.use("start", str(t), str(self.request), "true", "", WORKS_DESIGN_ONLY=value)
                self.assertEqual(r.returncode, 0, r.stderr)
                run = next(c for c in self.calls() if c[3:5] == ["workflow", "run"])
                self.assertEqual("design_only=true" in run, want, run)
                self.assertFalse(any(a.startswith("design_only=") and a != "design_only=true" for a in run), run)

    def test_start_refuses_switch_outside_one(self):
        """WORKS_DESIGN_ONLY・WORKS_USE_UNATTENDED・WORKS_USE_ALLOW_TESTCMD は未設定・空・1 だけを受け、ほかの値は家の下に何も作らず
        Archon も呼ばずに止まる（黙って捨てると設計だけ・無人のつもりの run が修正まで流れる・関所で人を待つ）"""
        for name in ("WORKS_DESIGN_ONLY", "WORKS_USE_UNATTENDED", "WORKS_USE_ALLOW_TESTCMD"):
            for value in ("on", "true", "0"):
                with self.subTest(name=name, value=value):
                    self.setUp()
                    t = self.target()
                    r = self.use("start", str(t), str(self.request), "true", "", **{name: value})
                    self.assert_refused(r, name, f"受けた値: {value}")
                    self.assertFalse((self.home / "requests").exists(), sorted(map(str, self.home.rglob("*"))))
                    self.assertFalse((self.home / "suites").exists())
                    self.assertFalse((self.home / "wraps").exists())

    def test_refuses_use_home_in_claude_tmp(self):
        t = self.target()
        r = self.use("start", str(t), str(self.request), "true", WORKS_USE_HOME="/private/tmp/claude-works-use-test-0/h")
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("/private/tmp/claude-", r.stderr)
        self.assertEqual(self.calls(), [])

    def test_default_use_home_is_per_clone(self):
        """WORKS_USE_HOME を名指さない既定の家は clone ごとに分かれ（Archon は 1 つの家に同じリポジトリの clone を 1 か所しか
        登録できない）、同じ clone なら symlink 越しでも下のフォルダからでも同じ家。名指せばその値のまま"""
        a, b = self.target("a"), self.target("b")
        (a / "sub").mkdir()
        (self.tmp / "link").symlink_to(a)
        state = self.tmp / "state"

        def home_of(target, **env_kw):
            self.log.unlink(missing_ok=True)
            env_kw.setdefault("WORKS_USE_HOME", None)
            r = self.use("check", str(target), XDG_STATE_HOME=str(state), **env_kw)
            calls = self.calls()
            self.assertEqual(len(calls), 1, r.stdout + r.stderr)
            return calls[0][2]

        home_a = home_of(a)
        self.assertRegex(home_a, "^" + re.escape(str(state / "works" / "use-")) + "[0-9a-f]{8}$")
        self.assertEqual(home_of(a), home_a)
        self.assertNotEqual(home_of(b), home_a)
        self.assertEqual(home_of(self.tmp / "link"), home_a)
        self.assertEqual(home_of(a / "sub"), home_a)
        self.assertEqual(home_of(a, WORKS_USE_HOME=str(self.home)), str(self.home))

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
        self.assertEqual(len(calls), 3, calls)
        sweep, run, runs = calls   # 起動の前の片付けが一覧を引き、起動の後に結ぶのがもう 1 度引く
        self.assertEqual(sweep, runs)
        self.assertEqual(run[:3], [str(t), "", str(self.home)])
        req = pathlib.Path(run[run.index("--input") + 1].split("=", 1)[1])
        self.assertTrue(req.is_absolute())
        self.assertTrue(str(req).startswith(str(self.home)), req)
        self.assertEqual(req.read_text(), self.request.read_text())
        self.assertEqual(run[3:], [
            "workflow", "run", "darkfactory", "--from", head,
            "--input", f"request={req}", "--input", "test_cmd=python3 -m unittest -q",
            "--input", "tdd_suite=", "--input", "adapter=", "--input", "final_gate=protected_only", "--base", "main",
            "--input", run[-1].split("=", 1)[0] + "=" + run[-1].split("=", 1)[1]])
        self.assertTrue(run[-1].startswith("launch_mark=") and run[-1] != "launch_mark=", run[-1])   # どの起動も印を付ける（段 4.1）
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
        self.assertIn(f"{self.out}/artifacts/runs/run-1/board/report.md", out)
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
                run = self.started()
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

    def test_start_names_test_cmd_paths_absent_from_worktrees(self):
        """run・単位の worktree は commit から切るので、test_cmd が対象の git の無視するパスを指せば start が知らせる（止めない。
        知らせの中身は test_testcmd_check。ここは殻が起動の前に呼んで出すことと、何も無ければ出さないことだけ）"""
        t = self.target()
        (t / ".venv" / "bin").mkdir(parents=True)
        (t / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
        with open(t / ".gitignore", "a", encoding="utf-8") as f:
            f.write(".venv\n")
        git(t, "commit", "-q", "-am", "ignore .venv")
        r = self.use("start", str(t), str(self.request), ".venv/bin/python -m pytest -q", VIRTUAL_ENV=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("注意（test_cmd）: test_cmd の .venv/bin/python は対象の git が無視するパス", r.stdout)
        self.assertLess(r.stdout.index("注意（test_cmd）"), r.stdout.index("対象: "))
        self.started()
        self.log.unlink()
        r = self.use("start", str(t), str(self.request), "uv run pytest -q", VIRTUAL_ENV=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("注意（test_cmd）", r.stdout)

    def test_start_stops_on_test_cmd_that_runs_the_checkout(self):
        """test_cmd が対象の手元（元の clone）を走らせる形（黙った偽の緑。決まりは test_testcmd_check）なら、start は Archon を
        起こす前・家の下に何も写す前に止まる（終了コード 2。止めた理由の行と、書き直す形 uv run と止めを外す
        WORKS_USE_ALLOW_TESTCMD=1 の行）。WORKS_USE_ALLOW_TESTCMD=1 なら今までどおり「注意」の行を出して起こし、止めを外したことを
        1 行出す。注意だけの形（相対の .venv）は止めず、止めを外した行も出さない"""
        t = self.target()
        (t / ".venv" / "bin").mkdir(parents=True)
        (t / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
        with open(t / ".gitignore", "a", encoding="utf-8") as f:
            f.write(".venv\n")
        git(t, "commit", "-q", "-am", "ignore .venv")
        for cmd in (f"{t}/.venv/bin/python -m pytest -q", f"cd {t} && uv run pytest -q"):
            with self.subTest(cmd):
                self.setUp()
                r = self.use("start", str(t), str(self.request), cmd, VIRTUAL_ENV=None)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("止める（test_cmd）: ", r.stderr)
                last = r.stderr.strip().splitlines()[-1]
                self.assertTrue(last.startswith("use.sh: "), last)
                for w in ("uv run pytest", "WORKS_USE_ALLOW_TESTCMD=1"):
                    self.assertIn(w, last)
                self.assertEqual(self.calls(), [])
                self.assertFalse((self.home / "archon-home" / "workflows").exists())
                for d in ("requests", "suites", "wraps"):
                    self.assertFalse((self.home / d).exists(), d)
                r = self.use("start", str(t), str(self.request), cmd, VIRTUAL_ENV=None, WORKS_USE_ALLOW_TESTCMD="1")
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn("注意（test_cmd）: ", r.stdout)
                self.assertNotIn("止める（test_cmd）", r.stdout + r.stderr)
                self.assertIn("WORKS_USE_ALLOW_TESTCMD=1 なので止めずに起こす", r.stdout)
                self.assertIn(f"test_cmd={cmd}", self.started())
        r = self.use("start", str(t), str(self.request), ".venv/bin/python -m pytest -q", VIRTUAL_ENV=None,
                     WORKS_USE_ALLOW_TESTCMD="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("注意（test_cmd）: ", r.stdout)
        self.assertNotIn("止めずに起こす", r.stdout)

    def test_start_stops_when_the_test_cmd_check_itself_fails(self):
        """test_cmd の形の確かめ（testcmd_check.py）そのものが落ちた（0・3 の外の終了コード）なら、手元を走らせる形を除けないので
        止める（終了コード 2。Archon を起こさず家の下に何も写さない。落ちた終了コードと WORKS_USE_ALLOW_TESTCMD=1 を名指す 1 行）。
        WORKS_USE_ALLOW_TESTCMD=1 なら落ちたことを注意として出して起こす。落とすのは PATH の頭の python3 の包み（確かめの殻の
        呼び出しだけを終了コード 1 で落とし、ほかは本物の python3 へ渡す）"""
        import shutil as _sh
        real = _sh.which("python3")
        bin_ = self.tmp / "crash-bin"
        bin_.mkdir()
        (bin_ / "python3").write_text(
            "#!/bin/sh\n"
            'for a in "$@"; do case $a in */testcmd_check.py) echo "Traceback: boom" >&2; exit 1 ;; esac; done\n'
            f'exec "{real}" "$@"\n')
        (bin_ / "python3").chmod(0o755)
        path = f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}"
        t = self.target()
        r = self.use("start", str(t), str(self.request), "uv run pytest -q", PATH=path, VIRTUAL_ENV=None)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        last = r.stderr.strip().splitlines()[-1]
        self.assertTrue(last.startswith("use.sh: "), last)
        for w in ("testcmd_check.py", "終了コード 1", "WORKS_USE_ALLOW_TESTCMD=1"):
            self.assertIn(w, last)
        self.assertEqual(self.calls(), [])
        self.assertFalse((self.home / "archon-home" / "workflows").exists())
        for d in ("requests", "suites", "wraps"):
            self.assertFalse((self.home / d).exists(), d)
        r = self.use("start", str(t), str(self.request), "uv run pytest -q", PATH=path, VIRTUAL_ENV=None,
                     WORKS_USE_ALLOW_TESTCMD="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("終了コード 1", r.stderr)
        self.assertIn("WORKS_USE_ALLOW_TESTCMD=1 なので", r.stderr)
        self.started()

    def test_start_final_gate_and_adapter(self):
        t = self.target()
        r = self.use("start", str(t), str(self.request), "true", "", WORKS_USE_FINAL_GATE="when_needed", WORKS_DEV_ADAPTER="1")
        self.assertEqual(r.returncode, 0, r.stderr)
        run = self.started()
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
        fake_bin, herdr_log = hermetic.fake_herdr(self.tmp)
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
        fake_bin, herdr_log = hermetic.fake_herdr(self.tmp)
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
        self.assertFalse(any(c.startswith("pane release-agent") for c in calls), calls)
        reports = [c for c in calls if c.startswith("pane report-agent")]
        self.assertTrue(reports and "--state working" in reports[-1] and "pane-7" in reports[-1], calls)
        # 全部終わった: その時だけ release
        set_status(**{"run-2": "completed"})
        herdr_log.unlink(missing_ok=True)
        r = self.use("wait", str(t), "run-2", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1", **pane)
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        calls = herdr_log.read_text().splitlines() if herdr_log.exists() else []
        self.assertTrue(any(c.startswith("pane release-agent pane-7") for c in calls), calls)
        # run を起こした枠と別の枠から打つ: 起こした枠 pane-7 へ今の状態（全部終わった release）を送り、打った枠 pane-9 へは何も送らない
        herdr_log.unlink(missing_ok=True)
        r = self.use("wait", str(t), "run-2", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1", **dict(pane, HERDR_PANE_ID="pane-9"))
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertTrue(any(c.startswith("pane release-agent pane-7 ") for c in herdr_log.read_text().splitlines()), r.stdout)
        self.assertFalse(any("pane-9" in c for c in herdr_log.read_text().splitlines()), herdr_log.read_text())

    def test_herdr_reports_to_ledger_pane_and_socket_from_other_shell(self):
        """run を起こした枠とサーバ（控えの herdr_pane・herdr_socket）へ、別の枠・別のサーバの殻からも枠の外の殻からも送る"""
        t = self.target()
        fake_bin, herdr_log = hermetic.fake_herdr(self.tmp)
        path = str(fake_bin) + os.pathsep + os.environ.get("PATH", "")
        sock_a, sock_b = str(self.tmp / "herdr-a.sock"), str(self.tmp / "herdr-b.sock")
        r = self.use("start", str(t), str(self.request), "true", "", PATH=path, HERDR_ENV="1", HERDR_PANE_ID="pane-7",
                     HERDR_SOCKET_PATH=sock_a)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(json.loads((self.home / "runs" / "run-1.json").read_text())["herdr_socket"], sock_a)
        for label, shell in (("別の枠・別のサーバ", dict(HERDR_ENV="1", HERDR_PANE_ID="pane-9", HERDR_SOCKET_PATH=sock_b)),
                             ("herdr の枠の外", dict(HERDR_ENV=None, HERDR_PANE_ID=None, HERDR_SOCKET_PATH=None))):
            with self.subTest(label):
                pathlib.Path(f"{herdr_log}.socket").unlink(missing_ok=True)
                self.use("wait", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1", PATH=path, **shell)
                sent = hermetic.herdr_sockets(herdr_log)
                self.assertTrue(any(s == sock_a and a.startswith("pane report-agent pane-7 ") and "--state blocked" in a
                                    for s, a in sent), sent)
                self.assertFalse(any("pane-9" in a for _, a in sent), sent)

    def test_approve_reports_working_then_state_to_starting_pane(self):
        """別の枠から承認しても、続きの口が Archon を呼ぶ前に起こした枠へ working を送る。Archon がまだ paused を返す間の wait は
        続き中の印を見て走る run と答え、枠を blocked に戻さない。続きが戻れば印を外し、起こした枠へ今の状態（blocked）を送る"""
        import time
        t = self.target()
        (self.home / "runs").mkdir(parents=True)
        (self.home / "runs" / "run-1.json").write_text(json.dumps({"run_id": "run-1", "target": str(t), "herdr_pane": "pane-7",
                                                                   "herdr_socket": ""}))
        self.fake.write_text(
            "#!/bin/sh\n"
            f'{{ printf \'%s\\t\' "$(pwd -P)" "${{WORKS_DEV_NO_AUTH:-}}" "${{WORKS_DEV_HOME:-}}" "$@"; echo; }} >> "{self.log}"\n'
            f'case "$*" in "workflow runs --json") cat "{self.runs}" ;; esac\n'
            'case "$1 $2" in "workflow approve") sleep 8 ;; esac\n'
            "exit 0\n")
        fake_bin, herdr_log = hermetic.fake_herdr(self.tmp)
        path = str(fake_bin) + os.pathsep + os.environ.get("PATH", "")
        r = self.use("approve", str(t), "run-1", PATH=path, HERDR_ENV="1", HERDR_PANE_ID="pane-9")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        sent = [a for _, a in hermetic.herdr_sockets(herdr_log)]
        self.assertTrue(sent and sent[0].startswith("pane report-agent pane-7 --source works-factory --agent works --state working"),
                        sent)
        r = self.use("wait", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1", PATH=path)
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("running", r.stdout)
        sent = [a for _, a in hermetic.herdr_sockets(herdr_log)]
        self.assertIn("--state working", sent[-1])
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not (
                not (self.home / "runs" / "run-1.cont").exists()
                and "--state blocked" in [a for _, a in hermetic.herdr_sockets(herdr_log)][-1]):
            time.sleep(0.2)
        sent = [a for _, a in hermetic.herdr_sockets(herdr_log)]
        self.assertFalse((self.home / "runs" / "run-1.cont").exists())
        self.assertTrue(sent[-1].startswith("pane report-agent pane-7 --source works-factory --agent works --state blocked"), sent)
        self.assertFalse(any("pane-9" in a for a in sent), sent)

    def test_approve_returns_fast_failure_while_after_report_is_slow(self):
        """切り離した続きの Archon が 1 秒のうちに落ちれば、後段の集計（ここでは遅い一覧）を待たずにその終了コードで返る"""
        t = self.target()
        (self.home / "runs").mkdir(parents=True)
        (self.home / "runs" / "run-1.json").write_text(json.dumps({"run_id": "run-1", "target": str(t), "herdr_pane": "pane-7"}))
        self.fake.write_text(
            "#!/bin/sh\n"
            f'case "$*" in "workflow runs --json") sleep 3; cat "{self.runs}"; exit 0 ;; esac\n'
            "echo 'archon: 承認に失敗した' >&2\n"
            "exit 4\n")
        fake_bin, _ = hermetic.fake_herdr(self.tmp)
        r = self.use("approve", str(t), "run-1", PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""))
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("承認に失敗した", r.stderr)

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

    # ---- 周の鎖（偽の archon の流れは下の ChainShell の check_ が持ち、ここの試験名で回す）
    def test_start_rounds_flag_and_refusals(self):
        """--rounds と --budget-usd は位置引数より前で読まれる。0・1.5・x、--budget-usd の単独、負・数でない値、WORKS_DESIGN_ONLY=1・
        WORKS_USE_FIX_FIXTURE との組は Archon を起こす前に 1 行で拒まれる。省略と 1 では鎖の控えを作らない。--rounds の start の終わりには
        鎖を進める wait の行が出る"""
        run_chain_checks(self, 'check_start_rounds_flag_and_refusals')

    def test_chain_second_round_launch_args(self):
        """1 周目が open で終わると、2 周目は start の道で起こされる。--from result_1・--input base=B0（1 本だけ・pr= 無し）・
        launch_mark=<鎖>-2・空でない --base と、1 周目と同じ test_cmd・tdd_suite・入力を持つ。wait の殻に WORKS_DESIGN_ONLY=1 や別の
        WORKS_USE_* が在っても、2 周目は 1 周目の入力で起きる。2 周目の run の控えが在り、--pr 12 の鎖では依頼の pr に 12 が在る"""
        run_chain_checks(self, 'check_chain_second_round_launch_args')

    def test_chain_unattended_next_round_is_detached(self):
        """無人の鎖の 2 周目は切り離して起こされ、偽の archon の approve が遅くても wait は期限のうちに 3 か 6 で戻る。2 周目の run は
        最後まで走り、打ち直した wait は子が生きている間 launch_unbound で止めない"""
        run_chain_checks(self, 'check_chain_unattended_next_round_is_detached')

    def test_chain_facts_read_events_of_done_run(self):
        """鎖の 1 歩は、終わった run にも workflow get --verbose --events --json を打ち、鎖の控えの周の cost_read が真で、費用と分が数になる"""
        run_chain_checks(self, 'check_chain_facts_read_events_of_done_run')

    def test_chain_round_result_on_start_base(self):
        """result_k は run-<k>.diff をその周の始めの記録の base_rev の木に当てて作られ（親は周の起点 from_k）、refs/works/chains/<鎖>/<k> で
        守られる。--pr の 1 周目でも二重に当たらず、final.diff は B0 から採った周の結果までの差になる。始めの記録の base_rev が周の起点と
        違う盤面（起点の 1 つ前）でも、木は base_rev の木・親は起点になる"""
        run_chain_checks(self, 'check_chain_round_result_on_start_base')

    def test_wait_exit_6_names_next_run(self):
        """鎖が次の周を起こして期限のうちに結べた wait は、終了コード 6 で新しい run の id と次の行を出す。同じ run に wait を打ち直しても
        2 本目を起こさない。止めた鎖は 5 と止めの 1 行を出す"""
        run_chain_checks(self, 'check_wait_exit_6_names_next_run', 'check_chain_interrupted_round_does_not_claim_a_next_run')

    def test_chain_answer_then_wait_launches_next(self):
        """paused → answer → wait が終わりを見て次の周を起こす。2 周目の起動が Archon の前で落ちても、次の wait で鎖の控えから続けられる"""
        run_chain_checks(self, 'check_chain_answer_then_wait_launches_next')

    def test_apply_show_clean_chain_id(self):
        """apply <鎖の id> は final.diff を今の apply と同じ確かめで当てる（消す行は許しが無ければ拒む）。show <鎖の id> は chain.md を出す。
        clean <鎖の id> は、最後の周が生きていれば今の clean と同じ文で拒み、そうでなければ refs/works/chains/<鎖>/* と控えを消す"""
        run_chain_checks(self, 'check_apply_show_clean_chain_id')

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

    def test_show_hides_raw_apply_for_stopped_or_unjudgeable_run(self):
        """記録が止まりを示す run には止まりの 1 行を、止まりの判定が壊れた run には判定できなかった理由の 1 行を出し、
        どちらも生の git apply の行を出さない（取り込みの行は use.sh apply の 1 本）"""
        cases = {
            "stopped": ({"stop": {"by": "human:final-gate", "reason": "守りのファイルは戻す"}}, "守りのファイルは戻す"),
            "broken": ({"stop": "壊れた止め"}, "止まりの判定: できなかった（AttributeError"),
        }
        for name, (state, want) in cases.items():
            with self.subTest(name):
                t = self.target(f"target-{name}")
                wt = self.tmp / f"wt-{name}"
                committed_copy(wt, DEV / "target-seed")
                base = git(wt, "rev-parse", "HEAD")
                (wt / "stats.py").write_text((wt / "stats.py").read_text() + "# 直した\n")
                board = self.tmp / "out" / "artifacts" / "runs" / "run-1" / "board"
                shutil.rmtree(board, ignore_errors=True)
                (board / "r1").mkdir(parents=True)
                (board / "r1" / "start.json").write_text(json.dumps({"base_rev": base}))
                (board / "state.json").write_text(json.dumps(state, ensure_ascii=False))
                self.set_runs(working_path=str(wt), output_root=str(self.tmp / "out"))
                r = self.use("show", str(t), CLAUDE_CODE_OAUTH_TOKEN=None)
                self.assertEqual(r.returncode, 0, r.stderr)
                self.assertIn(want, r.stdout)
                self.assertNotIn(f"git -C {t} apply", r.stdout)

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

    def test_start_does_not_bind_run_without_board(self):
        """起動の印を持つ run も盤面にこの起動の依頼を持つ run も無ければ、盤面の無い run（盤面を作る前に落ちた・別の起動の
        run）を代わりに結ばない。控えも続きの行も書かず、結べない時の 1 行を出して 1 で終わる（設計書 2.3）"""
        t = self.target()
        self.set_runs(working_path="/wt/run-1", output_root=str(self.tmp / "no-board"))
        r = self.use("start", str(t), str(self.request), "true", "", FAKE_ARCHON_NO_LAUNCH_MARK="1")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("結べなかった", r.stdout)
        self.assertNotIn("run id: run-1", r.stdout)
        self.assertFalse((self.home / "runs" / "run-1.json").exists())

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

    def test_apply_refuses_run_stopped_by_record(self):
        """記録が止まりを明示する run（最後の関所の答えが stop・盤面の state.stop が human:final-gate）の差分は、
        当てる前に 1 行で拒み（止めた一言と上書きの仕方を出す）、対象の作業ツリーを変えない。WORKS_USE_ALLOW_STOPPED=1 なら当てる。
        最後の関所の答えが continue なら今どおり当て、止まりの記録が無い run も当てて、確かめられなかったことを 1 行出す"""
        board = self.tmp / "out" / "artifacts" / "runs" / "run-1" / "board"

        def stopped_run(name, record):
            wt = self.tmp / f"wt-{name}"
            committed_copy(wt, DEV / "target-seed")
            base = git(wt, "rev-parse", "HEAD")
            (wt / "stats.py").write_text((wt / "stats.py").read_text() + "# 直した\n")
            shutil.rmtree(board, ignore_errors=True)
            (board / "r1").mkdir(parents=True)
            (board / "r1" / "start.json").write_text(json.dumps({"base_rev": base}))
            for rel, doc in record.items():
                (board / rel).write_text(json.dumps(doc, ensure_ascii=False))
            self.set_runs(status="completed", working_path=str(wt), output_root=str(self.tmp / "out"))
            return self.target(f"target-{name}")

        stops = {
            "answer": {"r1/final-gate-answer.json": {"decision": "stop", "text": "守りのファイルは戻す"}},
            "state": {"state.json": {"stop": {"by": "human:final-gate", "reason": "守りのファイルは戻す"}}},
        }
        for name, record in stops.items():
            with self.subTest(stopped=name):
                t = stopped_run(name, record)
                r = self.use("apply", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                lines = r.stderr.strip().splitlines()
                self.assertEqual(len(lines), 1, r.stderr)
                self.assertIn("守りのファイルは戻す", lines[0])
                self.assertIn("WORKS_USE_ALLOW_STOPPED=1", lines[0])
                self.assertEqual(git(t, "status", "--porcelain"), "")
                t = stopped_run(name + "-forced", record)
                r = self.use("apply", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_ALLOW_STOPPED="1")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("守りのファイルは戻す", r.stdout + r.stderr)
                self.assertEqual(git(t, "status", "--porcelain"), "M stats.py")
        t = stopped_run("continue", {"r1/final-gate-answer.json": {"decision": "continue", "text": "通す"}})
        r = self.use("apply", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(git(t, "status", "--porcelain"), "M stats.py")
        unknown = {
            "unrecorded": {},
            "corrupt-answer": {"state.json": {"halted": {"by": "stop_after_round"}}},   # 周は締めたが、答えのファイルが読めない
        }
        for name, record in unknown.items():
            with self.subTest(unknown=name):
                t = stopped_run(name, record)
                if name == "corrupt-answer":
                    (board / "r1" / "final-gate-answer.json").write_text("{壊れた")
                r = self.use("apply", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertEqual(git(t, "status", "--porcelain"), "M stats.py")
                self.assertIn("止まりかどうかを記録で確かめられなかった", r.stderr)

    def test_clean_removes_run_worktree_and_branch(self):
        t = self.target()
        wt = self.tmp / "run-wt"
        git(t, "worktree", "add", "-q", "-b", "archon/task-darkfactory-1", str(wt))
        self.set_runs(status="completed", working_path=str(wt), output_root=str(self.tmp / "out"))
        r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(wt.exists())
        self.assertEqual(git(t, "branch", "--list", "archon/task-darkfactory-1"), "")

    def test_clean_sweeps_unit_worktrees_and_refs_of_run(self):
        # 止まった run は、修正の段が run の作業ツリーから切った単位の worktree と守りの参照（refs/works/units/<印>/ の下の
        # base-*・u-*）を残しうる。clean は run の worktree を消す前に、それを片付ける
        import sys
        sys.path.insert(0, str(ROOT / ".shared" / "core"))
        import unittrees
        t = self.target()
        wt = self.tmp / "run-wt"
        git(t, "worktree", "add", "-q", "-b", "archon/task-darkfactory-1", str(wt))
        unit = self.tmp / "place" / "item-1"
        unittrees.add(wt, unittrees.snapshot(wt), unit)
        self.assertTrue(unit.is_dir())
        self.set_runs(status="failed", working_path=str(wt), output_root=str(self.tmp / "out"))
        r = self.use("clean", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(wt.exists())
        self.assertFalse(unit.exists(), r.stdout)
        self.assertEqual(git(t, "for-each-ref", "refs/works/units"), "")
        self.assertNotIn(str(unit), git(t, "worktree", "list"))

    def finished_run_worktree(self, t, base_rev=None, status="completed", start_json=True):
        """対象の本物の git worktree と枝を作り、盤面に周の頭の版（base_rev。省けば対象の HEAD）を書いた run
        （status。既定は終わった completed）を偽の一覧に置く（start_json=False は周の頭の版を書かない）。worktree には未コミットの修正を 1 行足す"""
        wt = self.tmp / "run-wt"
        git(t, "worktree", "add", "-q", "-b", "archon/task-darkfactory-1", str(wt))
        (wt / "stats.py").write_text((wt / "stats.py").read_text() + "# 直した\n")
        board = self.tmp / "out" / "artifacts" / "runs" / "run-1" / "board"
        (board / "r1").mkdir(parents=True)
        if start_json:
            (board / "r1" / "start.json").write_text(json.dumps({"base_rev": base_rev or git(t, "rev-parse", "HEAD")}))
        self.set_runs(status=status, working_path=str(wt), output_root=str(self.tmp / "out"))
        return wt

    def test_wait_completed_cleans_worktree_and_branch_after_diff_written(self):
        t = self.target()
        wt = self.finished_run_worktree(t)
        r = self.use("wait", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1")
        self.assertNotEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("completed", r.stdout)
        diff = self.home / "diffs" / "run-run-1.diff"
        self.assertIn("+# 直した", diff.read_text())
        self.assertFalse(wt.exists(), r.stdout + r.stderr)
        self.assertEqual(git(t, "branch", "--list", "archon/task-darkfactory-1"), "")
        # 片付けた後も差分のファイルが残るので、取り込みは当たる
        r = self.use("apply", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("# 直した", (t / "stats.py").read_text())

    def test_wait_completed_keeps_worktree_when_diff_write_fails(self):
        t = self.target()
        wt = self.finished_run_worktree(t, base_rev="0" * 40)
        diff = self.home / "diffs" / "run-run-1.diff"
        diff.parent.mkdir(parents=True)
        diff.write_text("前の差分\n")
        r = self.use("wait", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1")
        self.assertNotEqual(r.returncode, 2, r.stdout + r.stderr)
        # worktree に取られた枝は git branch --list が先頭に "+ " を付けて出すので、枝の参照が在るかで見る（無ければ git が 0 以外で落ちる）
        git(t, "show-ref", "--verify", "--quiet", "refs/heads/archon/task-darkfactory-1")
        self.assertTrue(wt.exists())
        self.assertEqual(diff.read_text(), "前の差分\n")
        self.assertTrue(any("片付けなかった" in l for l in (r.stdout + r.stderr).splitlines()), r.stdout + r.stderr)

    def test_show_keeps_previous_diff_and_fails_when_git_diff_fails(self):
        t = self.target()
        self.finished_run_worktree(t, base_rev="0" * 40)
        diff = self.home / "diffs" / "run-run-1.diff"
        diff.parent.mkdir(parents=True)
        diff.write_text("前の差分\n")
        r = self.use("show", str(t), CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertTrue(diff.exists(), r.stdout + r.stderr)
        self.assertEqual(diff.read_text(), "前の差分\n")
        self.assertIn("書けなかった", r.stdout + r.stderr)
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)

    def test_apply_refuses_when_diff_rewrite_fails(self):
        t = self.target()
        self.finished_run_worktree(t, base_rev="0" * 40)
        diff = self.home / "diffs" / "run-run-1.diff"
        diff.parent.mkdir(parents=True)
        diff.write_text(
            "--- a/stats.py\n+++ b/stats.py\n@@ -1 +1,2 @@\n " + (t / "stats.py").read_text().splitlines()[0] + "\n+# 古い差分\n")
        r = self.use("apply", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("書き直せなかった", r.stderr)
        self.assertEqual(git(t, "status", "--porcelain"), "")

    def branch_exists(self, t):
        return subprocess.run(["git", "-C", str(t), "show-ref", "--verify", "--quiet", "refs/heads/archon/task-darkfactory-1"]).returncode == 0

    def test_wait_and_show_keep_worktree_of_not_done_runs(self):
        """消してよいのは終わった状態（completed・cancelled）だけ。failed・paused・running・pending は wait・show を通しても worktree と枝を残す"""
        t = self.target()
        wt = self.finished_run_worktree(t)
        for status in ("failed", "paused", "running", "pending"):
            for cmd in ("wait", "show"):
                with self.subTest(status=status, cmd=cmd):
                    self.set_runs(status=status, working_path=str(wt), output_root=str(self.tmp / "out"))
                    r = self.use(cmd, str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1")
                    self.assertTrue(wt.exists(), r.stdout + r.stderr)
                    self.assertTrue(self.branch_exists(t))
                    self.assertNotIn("片付ける（差分のファイルは残す）", r.stdout)

    def test_show_cleans_done_run_after_diff_written_and_does_not_offer_clean(self):
        """show も、completed・cancelled の run を差分を書いた後に片付ける。片付けた後の出力は clean の行を勧めず、自動で片付くと言う"""
        for status in ("completed", "cancelled"):
            with self.subTest(status=status):
                t = self.target(name="target-" + status)
                self.tmp.joinpath("run-wt").exists() and git(t, "worktree", "prune")
                wt = self.finished_run_worktree(t, status=status)
                r = self.use("show", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertIn("+# 直した", (self.home / "diffs" / "run-run-1.diff").read_text())
                self.assertFalse(wt.exists(), r.stdout + r.stderr)
                self.assertNotIn("終わった run の worktree と枝を片付ける:", r.stdout)
                self.assertIn("自動で片付ける", r.stdout)
                self.assertFalse(self.branch_exists(t))
                shutil.rmtree(self.tmp / "out")

    def test_show_offers_clean_for_not_done_run(self):
        t = self.target()
        self.finished_run_worktree(t, status="failed")
        r = self.use("show", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertIn("終わった run の worktree と枝を片付ける:", r.stdout)

    def test_show_keeps_worktree_when_base_rev_is_unreadable(self):
        """start の控えの base_rev が読めない時、worktree 自身の HEAD を基に代用して commit 済みの修正が空に見えても 0 にしない
        （片付けの門を通さない）。show は 4 で終わり、worktree と枝は残る"""
        t = self.target()
        wt = self.finished_run_worktree(t, start_json=False)
        git(wt, "commit", "-qam", "commit 済みの修正")
        r = self.use("wait", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None, WORKS_USE_WAIT_SECONDS="1")
        self.assertTrue(wt.exists(), r.stdout + r.stderr)
        self.assertTrue(self.branch_exists(t))
        self.assertIn("片付けなかった", r.stdout)
        r = self.use("show", str(t), "run-1", CLAUDE_CODE_OAUTH_TOKEN=None)
        self.assertEqual(r.returncode, 4, r.stdout + r.stderr)
        self.assertIn("が読めないので worktree 自身の HEAD を基にした", r.stdout)
        self.assertTrue(wt.exists())

    def test_start_sweeps_old_non_live_runs_and_keeps_live_or_undiffable(self):
        """start が Archon を起こす前に、前の run のうち生きていない物（failed も）を差分を書いてから片付ける。生きた run と、差分を書けなかった
        run は残し、書けなかった理由を出す。片付けた run の id と状態は、入力 cleaned_runs で報告（冒頭 2）へ渡す"""
        t = self.target()
        out = self.tmp / "old-out"
        def old(name, status, base_rev):
            wt = self.tmp / ("wt-" + name)
            git(t, "worktree", "add", "-q", "-b", "archon/old-" + name, str(wt))
            (wt / "stats.py").write_text((wt / "stats.py").read_text() + "# " + name + "\n")
            board = out / name / "artifacts" / "runs" / name / "board"
            (board / "r2").mkdir(parents=True)
            (board / "r2" / "start.json").write_text(json.dumps({"base_rev": base_rev}))
            # 偽の archon は起動の依頼を各 run の r1/start.json に書く。前の run は依頼が違うので、書かせない（書けない置き場にする）
            (board / "r1").mkdir()
            (board / "r1").chmod(0o555)
            self.addCleanup((board / "r1").chmod, 0o755)
            return {"id": name, "workflow_name": "darkfactory", "status": status, "working_path": str(wt),
                    "output_root": str(out / name)}, wt
        failed, wt_failed = old("run-f", "failed", git(t, "rev-parse", "HEAD"))
        running, wt_running = old("run-r", "running", git(t, "rev-parse", "HEAD"))
        bad, wt_bad = old("run-b", "failed", "0" * 40)
        new = {"id": "run-1", "workflow_name": "darkfactory", "status": "paused", "working_path": "/wt/run-1", "output_root": str(self.out)}
        self.runs.write_text(json.dumps({"runs": [new, failed, running, bad]}))
        r = self.use("start", str(t), str(self.request))
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(wt_failed.exists(), r.stdout + r.stderr)
        self.assertIn("+# run-f", (self.home / "diffs" / "run-run-f.diff").read_text())
        self.assertTrue(wt_running.exists())
        self.assertTrue(wt_bad.exists())
        self.assertIn("前の run run-b（failed）: 差分を書けなかった", r.stdout)
        run = next(c for c in self.calls() if c[3:5] == ["workflow", "run"])
        self.assertIn("cleaned_runs=run-f（failed）", run)

    def old_failed_run_with_pane(self, t):
        """start の片付けにかかる前の落ちた run（run-f。差分を書ける）と、それを起こした herdr の枠 pane-5 の控え。
        今の run（run-1）は関所で待つ。(run-f の worktree)"""
        out = self.tmp / "old-out"
        wt = self.tmp / "wt-run-f"
        git(t, "worktree", "add", "-q", "-b", "archon/old-run-f", str(wt))
        board = out / "artifacts" / "runs" / "run-f" / "board"
        (board / "r2").mkdir(parents=True)
        (board / "r2" / "start.json").write_text(json.dumps({"base_rev": git(t, "rev-parse", "HEAD")}))
        (board / "r1").mkdir()
        (board / "r1").chmod(0o555)
        self.addCleanup((board / "r1").chmod, 0o755)
        new = {"id": "run-1", "workflow_name": "darkfactory", "status": "paused", "working_path": "/wt/run-1", "output_root": str(self.out)}
        old = {"id": "run-f", "workflow_name": "darkfactory", "status": "failed", "working_path": str(wt), "output_root": str(out)}
        self.runs.write_text(json.dumps({"runs": [new, old]}))
        (self.home / "runs").mkdir(parents=True)
        (self.home / "runs" / "run-f.json").write_text(json.dumps({"run_id": "run-f", "target": str(t), "herdr_pane": "pane-5",
                                                                   "herdr_socket": ""}))
        return wt

    def test_start_sweep_abandons_failed_old_run_and_updates_its_pane(self):
        """start が片付けた落ちた run も、手の clean と同じく Archon の記録を abandon で閉じ（cancelled）、その run を起こした枠
        （打った殻の枠と別でも）の集計を出し直す"""
        t = self.target()
        wt = self.old_failed_run_with_pane(t)
        fake_bin, herdr_log = hermetic.fake_herdr(self.tmp)
        r = self.use("start", str(t), str(self.request), PATH=str(fake_bin) + os.pathsep + os.environ.get("PATH", ""),
                     HERDR_ENV=None, HERDR_PANE_ID=None)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(wt.exists(), r.stdout + r.stderr)
        self.assertEqual(self.abandons(), [["1", "run-f"]])
        rows = {row["id"]: row["status"] for row in json.loads(self.runs.read_text())["runs"]}
        self.assertEqual(rows, {"run-1": "paused", "run-f": "cancelled"})
        self.assertIn("run run-f の Archon の記録を閉じた", r.stdout)
        sent = [a for _, a in hermetic.herdr_sockets(herdr_log)]
        self.assertTrue(any(a.startswith("pane release-agent pane-5 ") for a in sent), sent)
        run = next(c for c in self.calls() if c[3:5] == ["workflow", "run"])
        self.assertIn("cleaned_runs=run-f（failed）", run)

    def test_start_sweep_reports_abandon_failure_and_still_starts(self):
        """start の片付けで abandon が落ちても、片付けは済んだので cleaned_runs に載せて起こす。標準エラーに打ち直しの行を出す"""
        t = self.target()
        wt = self.old_failed_run_with_pane(t)
        r = self.use("start", str(t), str(self.request), FAKE_ARCHON_ABANDON_EXIT="4")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(wt.exists(), r.stdout + r.stderr)
        self.assertIn("abandon で閉じられなかった（終了コード 4）", r.stderr)
        self.assertIn(f"clean {t} run-f", r.stderr)
        run = next(c for c in self.calls() if c[3:5] == ["workflow", "run"])
        self.assertIn("cleaned_runs=run-f（failed）", run)

    def test_start_without_old_runs_passes_no_cleaned_runs(self):
        """片付ける前の run が無ければ、start は入力 cleaned_runs を渡さず、片付けが走らなかったとも言わない"""
        t = self.target()
        self.runs.write_text(json.dumps({"runs": []}))
        r = self.use("start", str(t), str(self.request))
        run = next(c for c in self.calls() if c[3:5] == ["workflow", "run"])
        self.assertFalse(any(a.startswith("cleaned_runs=") for a in run), run)
        self.assertNotIn("片付けは走らなかった", r.stdout + r.stderr)

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
        # 写しの borrow.json だけ借りるスキルを 1 本減らす（元の works を読めば 1 本多く写り、見分けられる）。superpowers は
        # pack の写し（.shared/borrow/superpowers/<版>/）から入れるので、外したスキルの pin.files の行と写しのフォルダも消す
        borrow = copy / ".shared" / "borrow" / "borrow.json"
        doc = json.loads(borrow.read_text())
        dropped = doc["superpowers"]["skills"][-1]
        self.copy_skills = doc["superpowers"]["skills"] = doc["superpowers"]["skills"][:-1]
        pin = doc["superpowers"]["pin"]
        pin["files"] = {r: h for r, h in pin["files"].items() if not r.startswith(f"skills/{dropped}/")}
        shutil.rmtree(copy / ".shared" / "borrow" / "superpowers" / pin["version"] / "skills" / dropped)
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
            # setUp の偽物と同じく、workflow run は run の盤面 r1/start.json に依頼を残す（起動の後に結ぶ材料）
            'case "$1 $2" in "workflow run") ;; *) exit 0 ;; esac\n'
            f'RUNS="{self.runs}" python3 - "$@" <<\'EOF\'\n'
            "import json, os, pathlib, sys\n"
            "req = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('request=')), '')\n"
            "mark = next((a.split('=', 1)[1] for a in sys.argv[1:] if a.startswith('launch_mark=')), '')\n"
            "path = pathlib.Path(os.environ['RUNS'])\n"
            "listed = json.loads(path.read_text())\n"
            "for r in listed['runs']:\n"
            "    if r.get('output_root') and os.path.isdir(r['output_root']):\n"
            "        board = pathlib.Path(r['output_root'], 'artifacts', 'runs', r['id'], 'board', 'r1')\n"
            "        board.mkdir(parents=True, exist_ok=True)\n"
            "        (board / 'start.json').write_text(json.dumps({'request_file': req}))\n"
            "    if mark and r.get('id') == 'run-1':\n"
            "        r.setdefault('metadata', {}).setdefault('inputs', {})['launch_mark'] = mark\n"
            "path.write_text(json.dumps(listed))\n"
            "EOF\n"
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
        sweep, run, runs = self.calls()
        self.assertEqual(sweep, runs)
        self.assertEqual(run[:9], [str(t), "", str(self.home), "workflow", "run", "darkfactory", "--from", head, "--input"])
        self.assertEqual(runs, [str(t), "1", str(self.home), "workflow", "runs", "--json"])
        self.assert_ran_from_copy(copy)
        cfg = str(self.home / "claude-config")
        calls = [json.loads(ln) for ln in self.claude_log.read_text().splitlines()]
        self.assertIn(["plugin", "install", "coldwrite@works-local"], [c["argv"][:3] for c in calls])
        self.assertEqual({c["cfg"] for c in calls}, {cfg})   # claude は隔離した設定にだけ入れる
        self.assertIn("run id: run-1", r.stdout)


import sys  # noqa: E402
import time  # noqa: E402
sys.path.insert(0, str(ROOT / ".shared" / "core"))


class _CoreChain:
    """周の鎖の住処 chain.py を使う時に読み込む（無い版でも試験の収集は落ちず、使った試験の中で読み込みに落ちる）"""

    def __getattr__(self, name):
        import importlib
        return getattr(importlib.import_module("chain"), name)


core_chain = _CoreChain()   # 鎖の控えを直に置く試験が形を引く

# 周の鎖の偽の archon: 起こした run を順に run-1・run-2…と増やし（status は paused から。試験が finish で終わらせる）、workflow get
# は run の行に試験が置いた出来事を足して返す。起動の引数は UseShell の偽物と同じ形で FAKE_LOG に残す。FAKE_APPROVE_DELAY が在れば
# approve をその秒だけ遅らせる（切り離した起動が前景を塞がないことを見る）
FAKE_CHAIN_ARCHON = r"""
import datetime, json, os, pathlib, sys, time
args = sys.argv[1:]
state_path = pathlib.Path(os.environ["FAKE_STATE"])
with open(os.environ["FAKE_LOG"], "a", encoding="utf-8") as f:
    f.write("\t".join([os.path.realpath(os.getcwd()), os.environ.get("WORKS_DEV_NO_AUTH", ""), os.environ.get("WORKS_DEV_HOME", ""), *args]) + "\t\n")
def load():
    return json.loads(state_path.read_text(encoding="utf-8"))
def save(d):
    tmp = state_path.with_suffix(".tmp")
    tmp.write_text(json.dumps(d), encoding="utf-8")
    os.replace(tmp, state_path)
d = load()
if args[:2] == ["workflow", "runs"]:
    print(json.dumps({"runs": d["runs"]}))
elif args[:2] == ["workflow", "get"]:
    row = next((r for r in d["runs"] if r["id"] == args[2]), None)
    if row is None:
        sys.exit(1)
    print(json.dumps({**row, "events": d.get("events", {}).get(args[2], [])}))
elif args[:2] == ["workflow", "run"]:
    d["seq"] += 1
    rid = "run-%d" % d["seq"]
    got = {a.split("=", 1)[0]: a.split("=", 1)[1] for a in args if "=" in a and not a.startswith("-")}
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    d["runs"].append({"id": rid, "workflow_name": "darkfactory", "status": "paused", "working_path": "/wt/" + rid,
                      "output_root": os.environ["FAKE_OUT"], "started_at": now,
                      "metadata": {"inputs": {"launch_mark": got.get("launch_mark", "")}}})
    board = pathlib.Path(os.environ["FAKE_OUT"], "artifacts", "runs", rid, "board", "r1")
    board.mkdir(parents=True, exist_ok=True)
    (board / "start.json").write_text(json.dumps({"request_file": got.get("request", ""), "base_rev": args[args.index("--from") + 1]}))
    save(d)
elif args[:2] == ["workflow", "approve"]:
    time.sleep(float(os.environ.get("FAKE_APPROVE_DELAY", "0")))
elif args[:2] == ["workflow", "abandon"]:
    for r in d["runs"]:
        if r["id"] == args[2]:
            r["status"] = "cancelled"
    save(d)
"""

FINDING = {"where": "stats.py:9", "text": "mean が空で落ちる"}


class ChainShell(unittest.TestCase):
    """start --rounds と、wait が終わりを見るたびに進める周の鎖（偽の archon。AI は起こさない）"""
    target = UseShell.target
    calls = UseShell.calls
    assert_refused = UseShell.assert_refused

    def setUp(self):
        self._td = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._td.name).resolve()
        self.addCleanup(self._td.cleanup)
        self.home = self.tmp / "use-home"
        self.dev_home = self.tmp / "dev-home"
        self.request = self.tmp / "req.json"
        self.request.write_text(json.dumps([FINDING]))
        self.log = self.tmp / "calls.txt"
        self.out = self.tmp / "out"
        self.out.mkdir()
        self.state = self.tmp / "state.json"
        self.state.write_text(json.dumps({"runs": [], "seq": 0, "events": {}}))
        (self.tmp / "fake_archon.py").write_text(FAKE_CHAIN_ARCHON, encoding="utf-8")
        self.fake = self.tmp / "fake-archon.sh"
        self.fake.write_text(f'#!/bin/sh\nexec python3 "{self.tmp / "fake_archon.py"}" "$@"\n')
        self.env = {"FAKE_STATE": str(self.state), "FAKE_LOG": str(self.log), "FAKE_OUT": str(self.out)}
        self.addCleanup(self.wait_child_done)   # 切り離した起動が置き場を使っている間は消さない（登録の逆順で、置き場の掃除より先に走る）

    def use(self, *args, **env):
        return UseShell.use(self, *args, **{**self.env, **env})

    def doc(self):
        return json.loads(self.state.read_text())

    def chain_dir(self):
        found = sorted((self.home / "chains").glob("c-*"))
        self.assertEqual(len(found), 1, found)
        return found[0]

    def chain_doc(self):
        return json.loads((self.chain_dir() / "chain.json").read_text())

    def runs_called(self):
        return [c for c in self.calls() if c[3:5] == ["workflow", "run"]]

    def inputs(self, call):
        return [call[i + 1] for i, a in enumerate(call) if a == "--input"]

    def diffs(self, target):
        """周ごとの差分（前の周の結果の上に積んだ物）。周 k の差分は周 k-1 の結果の木に当たる"""
        self.diff_seq = getattr(self, "diff_seq", 0) + 1
        wt = self.tmp / f"wt-diffs-{self.diff_seq}"
        committed_copy(wt, DEV / "target-seed")
        out = []
        for k in (1, 2, 3):
            (wt / "stats.py").write_text((wt / "stats.py").read_text() + f"# 周{k}の直し\n")
            out.append(subprocess.run(["git", "-C", str(wt), "diff", "--binary"], capture_output=True, text=True, check=True).stdout)
            git(wt, "add", "-A")
            git(wt, "commit", "-q", "-m", f"round {k}")
        return out

    def finish(self, n, word="round_limit", findings=(FINDING,), diff=None, costs=(1.5, 2.25), minutes=21.5, extra=None):
        """run-<n> を終わらせる: 状態 completed・出来事（節の費用）・始めと終わりの時刻・報告の冒頭の結末の語・次の依頼の下書き・差分のファイル"""
        d = self.doc()
        rid = f"run-{n}"
        for r in d["runs"]:
            if r["id"] == rid:
                r.update(status="completed", started_at="2026-10-09T12:00:00.000Z",
                         completed_at=(datetime_plus(minutes)), **(extra or {}))
        d["events"][rid] = [{"event_type": "node_completed", "step_name": f"node{i}",
                             "data": {"spend": {"costUsd": {"source": "provider", "value": c}}}} for i, c in enumerate(costs)]
        self.state.write_text(json.dumps(d))
        board = self.out / "artifacts" / "runs" / rid / "board"
        (board / "report.md").write_text(f"# 報告（run {rid}）\n\n起きたこと: 見本（{word}）\n", encoding="utf-8")
        (board / "next-request.json").write_text(json.dumps({"findings": list(findings), "prior_failures": []}))
        if diff is not None:
            (self.home / "diffs").mkdir(parents=True, exist_ok=True)
            (self.home / "diffs" / f"run-{rid}.diff").write_text(diff)

    def start(self, t, rounds="3", *flags, **env):
        r = self.use("start", "--rounds", rounds, *flags, str(t), str(self.request), "true", "", **env)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        return r

    def wait_child_done(self):
        """切り離した起動が終わる（鎖の控えに残した子の pid が居なくなる）まで待つ。一時の置き場を消す前に子を終わらせる"""
        end = time.monotonic() + 90
        while time.monotonic() < end:
            alive = []
            for p in self.tmp.glob("*/chains/*/chain.json"):
                pid = (json.loads(p.read_text(encoding="utf-8")).get("pending") or {}).get("pid")
                try:
                    if pid:
                        os.kill(pid, 0)
                        alive.append(pid)
                except ProcessLookupError:
                    pass
            if not alive:
                break
            time.sleep(0.5)
        time.sleep(2)   # 子が最後に控えとログを書き終える間

    # ---- 旗
    def check_start_rounds_flag_and_refusals(self):
        """--rounds と --budget-usd は位置引数より前で読まれる。0・1.5・x、--budget-usd の単独、負・数でない値、WORKS_DESIGN_ONLY=1・
        WORKS_USE_FIX_FIXTURE との組は Archon を起こす前に 1 行で拒まれる。省略と 1 では鎖の控えを作らない。--rounds の start の終わりには
        鎖を進める wait の行が出る"""
        t = self.target()
        fixture = self.tmp / "fixture"
        fixture.mkdir()
        for args, env, word in ((("--rounds", "0"), {}, "--rounds"), (("--rounds", "1.5"), {}, "--rounds"), (("--rounds", "x"), {}, "--rounds"),
                                (("--budget-usd", "5"), {}, "--budget-usd"), (("--rounds", "2", "--budget-usd", "-3"), {}, "--budget-usd"),
                                (("--rounds", "2", "--budget-usd", "abc"), {}, "--budget-usd"),
                                (("--rounds", "2", "--budget-usd", "0"), {}, "--budget-usd"),
                                (("--rounds", "2"), {"WORKS_DESIGN_ONLY": "1"}, "WORKS_DESIGN_ONLY"),
                                (("--rounds", "2"), {"WORKS_USE_FIX_FIXTURE": str(fixture)}, "WORKS_USE_FIX_FIXTURE")):
            with self.subTest(args=args, env=env):
                self.assert_refused(self.use("start", *args, str(t), str(self.request), "true", "", **env), word)
        for args in ((), ("--rounds", "1")):
            with self.subTest(single=args):
                r = self.use("start", *args, str(t), str(self.request), "true", "")
                self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
                self.assertFalse((self.home / "chains").exists())
                self.assertNotIn("鎖", r.stdout)
                self.log.unlink()
        self.state.write_text(json.dumps({"runs": [], "seq": 0, "events": {}}))
        r = self.start(t, "2", "--budget-usd", "12.5")
        doc = self.chain_doc()
        self.assertEqual((doc["rounds_max"], doc["budget_usd"], doc["test_cmd"], doc["tdd_suite"]), (2, 12.5, "true", ""))
        self.assertEqual(pathlib.Path(doc["first_request"]).read_text(), self.request.read_text())
        self.assertEqual((doc["pending"]["run"], doc["pending"]["launched"], doc["pending"]["mark"]), ("run-1", True, doc["id"] + "-1"))
        self.assertIn(f"sh {USE} wait {t} run-1", r.stdout)
        self.assertIn(doc["id"], r.stdout)

    # ---- 2 周目の起動
    def second_round(self, home, t, start_flags, request, wait_env):
        self.home = self.tmp / home
        self.state.write_text(json.dumps({"runs": [], "seq": 0, "events": {}}))
        self.log.unlink(missing_ok=True)
        d1, _, _ = self.diffs(t)
        r = self.use("start", "--rounds", "3", *start_flags, str(t), request, "true", "", WORKS_USE_THICKNESS="2")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.finish(1, diff=d1)
        r = self.use("wait", str(t), "run-1", WORKS_USE_WAIT_SECONDS="90", **wait_env)
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("run-2", r.stdout)
        first, second = self.runs_called()
        return first, second, self.chain_dir().name

    def check_chain_second_round_launch_args(self):
        """1 周目が open で終わると、2 周目は start の道で起こされる。--from result_1・--input base=B0（1 本だけ・pr= 無し）・
        launch_mark=<鎖>-2・空でない --base と、1 周目と同じ test_cmd・tdd_suite・入力を持つ。wait の殻に WORKS_DESIGN_ONLY=1 や別の
        WORKS_USE_* が在っても、2 周目は 1 周目の入力で起きる。2 周目の run の控えが在り、--pr 12 の鎖では依頼の pr に 12 が在る"""
        t = self.target()
        head = git(t, "rev-parse", "HEAD")
        wait_env = {"WORKS_DESIGN_ONLY": "1", "WORKS_USE_THICKNESS": "9", "WORKS_USE_UNATTENDED": None, "WORKS_USE_GATES": "x"}
        first, second, cid = self.second_round("home-a", t, (), str(self.request), wait_env)
        result1 = git(t, "rev-parse", f"refs/works/chains/{cid}/1")
        self.assertEqual(second[second.index("--from") + 1], result1)
        ins = self.inputs(second)
        self.assertEqual([i for i in ins if i.startswith("base=")], [f"base={head}"])
        self.assertEqual([i for i in ins if i.startswith(("pr=", "design_only", "gates="))], [])
        self.assertIn(f"launch_mark={cid}-2", ins)
        self.assertIn("thickness=2", ins)                       # 1 周目の入力。wait の殻の 9 ではない
        self.assertNotEqual(second[second.index("--base") + 1], "")
        for key in ("test_cmd=", "tdd_suite=", "adapter=", "final_gate="):
            self.assertEqual([i for i in ins if i.startswith(key)], [i for i in self.inputs(first) if i.startswith(key)], key)
        ledger = json.loads((self.home / "runs" / "run-2.json").read_text())
        self.assertEqual(ledger["run_id"], "run-2")
        request = next(i for i in ins if i.startswith("request=")).split("=", 1)[1]
        self.assertEqual(json.loads(pathlib.Path(request).read_text())["findings"], [FINDING])   # 前の周の残りが依頼になる
        # --pr の鎖: 次の周の入力に pr は使わず、依頼の pr に 12 を運ぶ。--base の鎖: 2 周目の根は 1 周目の始めの版
        t2 = self.target("target-pr")
        first, second, _ = self.second_round("home-b", t2, ("--pr", "12"), "-", {})
        ins = self.inputs(second)
        self.assertEqual([i for i in ins if i.startswith("pr=")], [])
        self.assertEqual([i for i in ins if i.startswith("base=")], [f"base={git(t2, 'rev-parse', 'HEAD')}"])
        request = next(i for i in ins if i.startswith("request=")).split("=", 1)[1]
        self.assertEqual(json.loads(pathlib.Path(request).read_text())["pr"], [12])
        t3 = self.target("target-base")
        first, second, _ = self.second_round("home-c", t3, ("--base", "main"), str(self.request), {})
        self.assertIn("base=main", self.inputs(first))
        self.assertEqual([i for i in self.inputs(second) if i.startswith("base=")], [f"base={git(t3, 'rev-parse', 'HEAD')}"])

    def check_chain_unattended_next_round_is_detached(self):
        """無人の鎖の 2 周目は切り離して起こされ、偽の archon の approve が遅くても wait は期限のうちに 3 か 6 で戻る。2 周目の run は
        最後まで走り、打ち直した wait は子が生きている間 launch_unbound で止めない"""
        t = self.target()
        d1, _, _ = self.diffs(t)
        self.start(t, "2", WORKS_USE_UNATTENDED="1", FAKE_APPROVE_DELAY="12")
        self.finish(1, diff=d1)
        began = time.monotonic()
        r = self.use("wait", str(t), "run-1", WORKS_USE_UNATTENDED="1", FAKE_APPROVE_DELAY="12", WORKS_USE_WAIT_SECONDS="3")
        self.assertIn(r.returncode, (3, 6), r.stdout + r.stderr)
        self.assertLess(time.monotonic() - began, 11, "approve の遅れを前景で待った")
        r = self.use("wait", str(t), "run-1", WORKS_USE_UNATTENDED="1", FAKE_APPROVE_DELAY="12", WORKS_USE_WAIT_SECONDS="60")
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertNotIn("launch_unbound", r.stdout + r.stderr)
        self.assertEqual(len(self.runs_called()), 2)
        self.assertEqual(self.chain_doc()["pending"]["launched"], True)
        self.wait_child_done()
        verbs = [c[3:6] for c in self.calls()]
        self.assertIn(["workflow", "approve", "run-2"], verbs)   # 2 周目も 1 周目と同じ行で無人の承認と止めを通る
        self.assertIn(["workflow", "respond", "run-2"], verbs)

    def check_chain_facts_read_events_of_done_run(self):
        """鎖の 1 歩は、終わった run にも workflow get --verbose --events --json を打ち、鎖の控えの周の cost_read が真で、費用と分が数になる"""
        t = self.target()
        self.start(t, "2")
        self.finish(1, word="fixed", costs=(1.5, 2.25), minutes=21.5)
        r = self.use("wait", str(t), "run-1", WORKS_USE_WAIT_SECONDS="30")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn(["workflow", "get", "run-1", "--verbose", "--events", "--json"], [c[3:] for c in self.calls()])
        row = self.chain_doc()["rounds"][0]
        self.assertEqual((row["cost"], row["cost_read"], row["minutes"], row["kind"]), (3.75, True, 21.5, "closed"))

    def check_chain_interrupted_round_does_not_claim_a_next_run(self):
        """途中で落ちた周（結末が interrupted）は周に足さず、次の周を結べたと言う終了コード 6 も返さない。起こし直しも止めもせず、
        控えの周と pending は変わらない"""
        t = self.target()
        self.start(t, "3")
        self.finish(1, word="interrupted")
        r = self.use("wait", str(t), "run-1", WORKS_USE_WAIT_SECONDS="30")
        self.assertEqual(r.returncode, 1, r.stdout + r.stderr)
        self.assertIn("途中で落ちた", r.stdout)
        self.assertNotIn("次の周を起こして結んだ", r.stdout)
        self.assertEqual(len(self.runs_called()), 1)
        doc = self.chain_doc()
        self.assertEqual((doc["rounds"], doc["pending"]["run"], doc["stop"]), ([], "run-1", None))

    def check_chain_round_result_on_start_base(self):
        """result_k は run-<k>.diff をその周の始めの記録の base_rev の木に当てて作られ（親は周の起点 from_k）、refs/works/chains/<鎖>/<k> で
        守られる。--pr の 1 周目でも二重に当たらず、final.diff は B0 から採った周の結果までの差になる。始めの記録の base_rev が周の起点と
        違う盤面（起点の 1 つ前）でも、木は base_rev の木・親は起点になる"""
        t = self.target()
        old_head = git(t, "rev-parse", "HEAD")
        (t / "other.txt").write_text("周の起点にだけ在る\n")
        git(t, "add", "-A")
        git(t, "commit", "-q", "-m", "other")
        head = git(t, "rev-parse", "HEAD")
        d1, _, _ = self.diffs(t)
        self.start(t, "2", "--pr", "12")
        board = self.out / "artifacts" / "runs" / "run-1" / "board" / "r1" / "start.json"
        board.write_text(json.dumps({"request_file": "", "base_rev": old_head}))   # 差分は起点の 1 つ前（old_head）との差
        self.finish(1, word="fixed", diff=d1)
        r = self.use("wait", str(t), "run-1", WORKS_USE_WAIT_SECONDS="30")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        cid = self.chain_dir().name
        ref = f"refs/works/chains/{cid}/1"
        result = git(t, "rev-parse", ref)
        self.assertEqual(git(t, "rev-parse", f"{ref}^"), head)   # 親は周の起点
        expected = self.tmp / "expected"
        committed_copy(expected, DEV / "target-seed")
        (expected / "stats.py").write_text((expected / "stats.py").read_text() + "# 周1の直し\n")
        git(expected, "add", "-A")
        self.assertEqual(git(t, "rev-parse", f"{result}^{{tree}}"), git(expected, "write-tree"))   # 木は base_rev の木に差分を当てた物
        final = (self.chain_dir() / "final.diff").read_text()
        self.assertEqual(final.count("+# 周1の直し"), 1, final)
        self.assertEqual(final, subprocess.run(["git", "-C", str(t), "diff", "--binary", old_head, result], capture_output=True, text=True).stdout)
        self.assertEqual(self.chain_doc()["original_base"], old_head)

    def check_wait_exit_6_names_next_run(self):
        """鎖が次の周を起こして期限のうちに結べた wait は、終了コード 6 で新しい run の id と次の行を出す。同じ run に wait を打ち直しても
        2 本目を起こさない。止めた鎖は 5 と止めの 1 行を出す"""
        t = self.target()
        d1, d2, _ = self.diffs(t)
        self.start(t, "3")
        self.finish(1, diff=d1)
        r = self.use("wait", str(t), "run-1", WORKS_USE_WAIT_SECONDS="90")
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("run-2", r.stdout)
        self.assertIn(f"sh {USE} wait {t} run-2", r.stdout)
        r = self.use("wait", str(t), "run-1", WORKS_USE_WAIT_SECONDS="30")
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertIn("run-2", r.stdout)
        self.assertEqual(len(self.runs_called()), 2)
        self.finish(2, word="fixed", diff=d2, findings=())
        r = self.use("wait", str(t), "run-2", WORKS_USE_WAIT_SECONDS="30")
        self.assertEqual(r.returncode, 5, r.stdout + r.stderr)
        self.assertIn("止めた（closed", r.stdout)
        self.assertEqual(len(self.runs_called()), 2)
        self.assertEqual(self.chain_doc()["stop"]["word"], "closed")
        self.assertTrue((self.chain_dir() / "chain.md").is_file())

    def check_chain_answer_then_wait_launches_next(self):
        """paused → answer → wait が終わりを見て次の周を起こす。2 周目の起動が Archon の前で落ちても、次の wait で鎖の控えから続けられる"""
        t = self.target()
        d1, _, _ = self.diffs(t)
        self.start(t, "2")
        r = self.use("answer", str(t), "run-1", "continue", "通す", "me")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.finish(1, diff=d1)
        git(t, "remote", "remove", "origin")   # 2 周目の start は origin が無いと Archon の前で拒む
        r = self.use("wait", str(t), "run-1", WORKS_USE_WAIT_SECONDS="60")
        self.assertEqual(r.returncode, 3, r.stdout + r.stderr)
        self.assertIn("wait", r.stdout)
        self.assertEqual(len(self.runs_called()), 1)
        pend = self.chain_doc()["pending"]
        self.assertEqual((pend["round"], pend["launched"], pend["run"]), (2, False, ""))
        git(t, "remote", "add", "origin", str(self.tmp / "origin.git"))
        git(t, "update-ref", "refs/remotes/origin/main", "HEAD")
        r = self.use("wait", str(t), "run-1", WORKS_USE_WAIT_SECONDS="90")
        self.assertEqual(r.returncode, 6, r.stdout + r.stderr)
        self.assertEqual(len(self.runs_called()), 2)
        self.assertEqual(len(self.chain_doc()["rounds"]), 1)

    # ---- 取り込み・報告・片付け
    def fake_chain(self, t, *, final=None, run_status="completed", pending=None, stopped=False):
        """鎖の控え・最後の差分・周の結果の参照を家と対象に直に置く（周を実際に回さずに apply・show・clean を見る）"""
        cid = "c-20261009-120000-1"
        d = self.home / "chains" / cid
        d.mkdir(parents=True)
        doc = core_chain.new_doc(cid, target=str(t), rounds=2, budget=None, request="", test_cmd="true", tdd_suite="", env=[],
                            use_sh=str(USE), pid=1)
        row = {"n": 1, "run": "run-1", "from": git(t, "rev-parse", "HEAD"), "base_rev": git(t, "rev-parse", "HEAD"),
               "result": git(t, "rev-parse", "HEAD"), "same_tree": False, "outcome": "x", "kind": "open", "minutes": 3.0, "cost": 1.0,
               "cost_read": True, "keys": [], "held_rows": [], "files": 1, "r2": 0, "stopped": None, "diff": "", "report": "",
               "next_file": ""}
        doc.update(rounds=[row], pending=pending, original_base=row["base_rev"], stop={"word": "rounds_reached", "text": "t"})
        core_chain.save(d, doc)
        git(t, "update-ref", f"refs/works/chains/{cid}/1", "HEAD")
        if final is not None:
            (d / "final.diff").write_text(final)
        self.state.write_text(json.dumps({"runs": [{"id": "run-1", "workflow_name": "darkfactory", "status": run_status,
                                                     "working_path": "/wt/none", "output_root": str(self.out)}], "seq": 1, "events": {}}))
        board = self.out / "artifacts" / "runs" / "run-1" / "board"
        (board / "r1").mkdir(parents=True)
        if stopped:
            (board / "r1" / "final-gate-answer.json").write_text(json.dumps({"decision": "stop", "text": "守りのファイルは戻す"}))
        return cid, d

    def check_apply_show_clean_chain_id(self):
        """apply <鎖の id> は final.diff を今の apply と同じ確かめで当てる（消す行は許しが無ければ拒む）。show <鎖の id> は chain.md を出す。
        clean <鎖の id> は、最後の周が生きていれば今の clean と同じ文で拒み、そうでなければ refs/works/chains/<鎖>/* と控えを消す"""
        d1, _, _ = self.diffs(None)
        t = self.target()
        cid, d = self.fake_chain(t, final=d1)
        r = self.use("apply", str(t), cid)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertEqual(git(t, "status", "--porcelain"), "M stats.py")
        self.assertIn(f"鎖 {cid}", r.stdout)
        git(t, "checkout", "-q", "--", "stats.py")
        # 消す行は許しが無ければ拒む
        (t / "test_stats.py").unlink()
        gone = subprocess.run(["git", "-C", str(t), "diff", "--binary"], capture_output=True, text=True).stdout
        git(t, "checkout", "-q", "--", "test_stats.py")
        (d / "final.diff").write_text(gone)
        r = self.use("apply", str(t), cid)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("WORKS_USE_ALLOW_DELETE=1", r.stderr)
        self.assertEqual(git(t, "status", "--porcelain"), "")
        r = self.use("apply", str(t), cid, WORKS_USE_ALLOW_DELETE="1")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        git(t, "checkout", "-q", "--", ".")
        # 採った周の run の記録が止まりなら、今の apply と同じに拒む
        (d / "final.diff").write_text(d1)
        board = self.out / "artifacts" / "runs" / "run-1" / "board"
        (board / "r1" / "final-gate-answer.json").write_text(json.dumps({"decision": "stop", "text": "守りのファイルは戻す"}))
        r = self.use("apply", str(t), cid)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("WORKS_USE_ALLOW_STOPPED=1", r.stderr)
        (board / "r1" / "final-gate-answer.json").unlink()
        # show は chain.md を出す
        r = self.use("show", str(t), cid)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"# 鎖 {cid} の報告", r.stdout)
        self.assertIn("rounds_reached", r.stdout)
        # clean: 最後の周が生きていれば拒み、次の周を起こす途中でも拒み、そうでなければ消す
        self.set_state_status("running")
        r = self.use("clean", str(t), cid)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("run run-1 は running。止めるか終わってから片付ける", r.stderr)
        self.assertTrue(d.is_dir())
        self.set_state_status("completed")
        doc = core_chain.load(d)
        doc["pending"] = {"round": 2, "mark": cid + "-2", "pid": None, "launched": False, "run": "", "from": "f", "request": "", "log": ""}
        core_chain.save(d, doc)
        r = self.use("clean", str(t), cid)
        self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
        self.assertIn("次の周を起こす途中", r.stderr)
        doc["pending"] = None
        core_chain.save(d, doc)
        r = self.use("clean", str(t), cid)
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(d.exists())
        self.assertEqual(git(t, "for-each-ref", "refs/works/chains/"), "")

    def set_state_status(self, status):
        d = self.doc()
        for r in d["runs"]:
            r["status"] = status
        self.state.write_text(json.dumps(d))


def run_chain_checks(owner, *names):
    """ChainShell の check_ で始まる確かめを、owner の部分試験として 1 本ずつ新しい準備（家・偽の archon・後片付け）で回す"""
    for name in names:
        with owner.subTest(check=name):
            case = ChainShell(name)
            case.setUp()
            try:
                getattr(case, name)()
            finally:
                case.doCleanups()


def datetime_plus(minutes: float) -> str:
    """finish が run の completed_at に置く時刻（始め 2026-10-09T12:00:00Z から minutes 分後）"""
    import datetime
    base = datetime.datetime(2026, 10, 9, 12, 0, 0, tzinfo=datetime.timezone.utc)
    return (base + datetime.timedelta(minutes=minutes)).strftime("%Y-%m-%dT%H:%M:%S.000Z")


if __name__ == "__main__":
    unittest.main()
