"""名指した PR・issue を run の中で読む部品（.shared/core/ghreads.py の read_named）と、線の入口がそれを使う所の検査（設計書 2.8）。

gh は偽物（fake_gh）。偽の gh は、利用者のログイン（GH_CONFIG_DIR・$XDG_CONFIG_HOME/gh・$HOME/.config/gh の hosts.yml）が
見える時だけ非公開の中身を返し、見えない時は本物と同じく exit 4 で終わる。run の中の gh は開発の殻（dev/hostgh.py の口）が
利用者のログインを継がせるので、「ログインが見えれば載り、見えなければ読めないと記録する」を本物の GitHub に触れずに縛れる。

- read_named: 名指した PR の本文・コメント・レビュー・行コメントと issue の本文・コメントを、cwd＝対象の根で 1 回だけ読む。
  読めない項は status unreadable で残す
- 線の入口: entry.check_inputs は gh を呼ばず、渡された読み出しの base・head を読む。entry.start は名指しを run の中で読んで
  盤面の根の github.json に置き、再開では盤面の写しを使う。WORKS_DEV_NO_AUTH=1 の run（利用者の gh を継がない）は 1 行で拒む
- ラインは読み出しのファイルを受けない（入力 github_reads は無い）
"""
import contextlib
import importlib.util
import json
import os
import pathlib
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

import entry  # noqa: E402
import entryshape  # noqa: E402  （入口の変換）
import ghreads  # noqa: E402
import hermetic  # noqa: E402
import linekit  # noqa: E402
from gitkit import committed_copy, git  # noqa: E402

GHREADS = CORE / "ghreads.py"
SEED = ROOT / "dev" / "target-seed"
ROW = {"where": "stats.py:1", "text": "mean が空で落ちる"}
GH_ENV = ("GH_CONFIG_DIR", "XDG_CONFIG_HOME", "GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN")


def fake_gh(tmp: pathlib.Path, *, base="b" * 40, head="h" * 40):
    """偽の gh を tmp/gh-bin に置き、(bin のフォルダ, 呼び出しの記録, 利用者のログインのフォルダ) を返す。
    記録は 1 行 1 呼び出しで「cwd<TAB>引数」。ログインのフォルダ（hosts.yml 入り）を GH_CONFIG_DIR に置いた時だけ中身を返す"""
    data = tmp / "gh-data"
    data.mkdir(parents=True, exist_ok=True)
    (data / "pr-7.json").write_text(json.dumps({
        "baseRefOid": base, "headRefOid": head, "title": "非公開の題", "body": "非公開の本文",
        "comments": [{"author": {"login": "a"}, "body": "非公開のコメント"}],
        "reviews": [{"author": {"login": "b"}, "body": "非公開のレビュー", "state": "COMMENTED"}]}, ensure_ascii=False))
    (data / "review-comments-7.json").write_text(json.dumps([{"path": "stats.py", "line": 1, "body": "非公開の行コメント"}],
                                                            ensure_ascii=False))
    (data / "issue-9.json").write_text(json.dumps({"title": "課題の題", "body": "課題の本文",
                                                   "comments": [{"body": "課題のコメント"}]}, ensure_ascii=False))
    login = tmp / "user-gh"
    login.mkdir(exist_ok=True)
    (login / "hosts.yml").write_text("github.com:\n    user: someone\n", encoding="utf-8")
    bin_ = tmp / "gh-bin"
    bin_.mkdir(exist_ok=True)
    calls = tmp / "gh-calls.txt"
    gh = bin_ / "gh"
    gh.write_text(
        "#!/bin/sh\n"
        f'printf \'%s\\t%s\\n\' "$(pwd -P)" "$*" >> "{calls}"\n'
        'if [ -n "${GH_CONFIG_DIR:-}" ]; then conf="$GH_CONFIG_DIR"\n'
        'elif [ -n "${XDG_CONFIG_HOME:-}" ]; then conf="$XDG_CONFIG_HOME/gh"\n'
        'else conf="${HOME:-/nonexistent}/.config/gh"; fi\n'
        'if [ ! -f "$conf/hosts.yml" ]; then\n'
        '  echo "To get started with GitHub CLI, please run:  gh auth login" >&2\n'
        "  exit 4\n"
        "fi\n"
        'case "$1" in\n'
        f'  pr) f="{data}/pr-$3.json" ;;\n'
        f'  issue) f="{data}/issue-$3.json" ;;\n'
        f'  api) n="$(printf \'%s\\n\' "$*" | sed -n \'s#.*pulls/\\([0-9]*\\)/comments.*#\\1#p\')"; f="{data}/review-comments-$n.json" ;;\n'
        '  *) f="" ;;\n'
        "esac\n"
        'if [ -z "$f" ] || [ ! -f "$f" ]; then echo "GraphQL: Could not resolve to a PullRequest" >&2; exit 1; fi\n'
        'cat "$f"\n',
        encoding="utf-8")
    gh.chmod(0o755)
    return bin_, calls, login


def gh_calls(calls: pathlib.Path):
    return [line.split("\t", 1) for line in calls.read_text(encoding="utf-8").splitlines()] if calls.exists() else []


class ReadNamedCase(unittest.TestCase):
    """ghreads.read_named を、偽の gh を PATH の頭に置いて同じプロセスで呼ぶ"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.addCleanup(self._tmp.cleanup)
        self.repo = self.tmp / "repo"
        self.repo.mkdir()
        # 対象は GitHub の remote を持つ（forge の在る対象。forge の無い対象で gh が読めなかった項は条件外と書く: test_forge）
        subprocess.run(["git", "init", "-q", str(self.repo)], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(self.repo), "remote", "add", "origin", "git@github.com:o/r.git"], check=True,
                       capture_output=True)
        self.bin, self.calls, self.login = fake_gh(self.tmp)

    def read(self, prs, issues, logged_in=True):
        env = {name: None for name in GH_ENV}
        env.update(PATH=f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}", HOME=str(self.tmp / "home"))
        if logged_in:
            env["GH_CONFIG_DIR"] = str(self.login)
        with gh_env(env):
            return ghreads.read_named(self.repo, prs, issues)

    def test_reads_named_pr_and_issue_with_user_login(self):
        """利用者のログインが見える env で、名指した PR の本文・コメント・レビュー・行コメントと issue の本文・コメントが載る。
        gh は対象の根を cwd にして呼び、行コメントは gh api --paginate の {owner}/{repo} で引く"""
        doc = self.read([7], [9])
        self.assertEqual(doc["version"], ghreads.GITHUB_READS_VERSION)
        pr = doc["pr"]["7"]
        self.assertEqual((pr["title"], pr["body"]), ("非公開の題", "非公開の本文"))
        self.assertEqual((pr["baseRefOid"], pr["headRefOid"]), ("b" * 40, "h" * 40))
        self.assertEqual([c["body"] for c in pr["comments"]], ["非公開のコメント"])
        self.assertEqual([c["body"] for c in pr["reviews"]], ["非公開のレビュー"])
        self.assertEqual([c["body"] for c in pr["review_comments"]], ["非公開の行コメント"])
        self.assertEqual(pr["status"], "ok")
        issue = doc["issue"]["9"]
        self.assertEqual((issue["title"], issue["body"]), ("課題の題", "課題の本文"))
        self.assertEqual([c["body"] for c in issue["comments"]], ["課題のコメント"])
        calls = gh_calls(self.calls)
        self.assertTrue(calls)
        self.assertEqual({cwd for cwd, _ in calls}, {str(self.repo)})
        self.assertTrue(any("repos/{owner}/{repo}/pulls/7/comments" in a and "--paginate" in a for _, a in calls), calls)

    def test_without_login_marks_unreadable(self):
        """利用者のログインが見えない（gh は exit 4）と、名指した項に status unreadable と 1 行の理由を残す（止めない）"""
        doc = self.read([7], [9], logged_in=False)
        for got in (doc["pr"]["7"], doc["issue"]["9"]):
            self.assertEqual(got["status"], "unreadable")
            self.assertEqual(set(got), {"status", "reason"})   # forge の在る対象: 欄 forge も内側の印 _no_host も無い
            self.assertTrue(got["reason"].strip())
            self.assertNotIn("\n", got["reason"])
        self.assertNotIn("非公開", json.dumps(doc, ensure_ascii=False))

    def test_file_reading_entry_is_gone(self):
        """隔離の前に読んでファイルで渡す口（read の CLI・load・adopt・discard_source）は無い"""
        for name in ("read", "load", "adopt", "discard_source", "DiscardFailed"):
            self.assertFalse(hasattr(ghreads, name), name)
        r = subprocess.run([sys.executable, "-I", str(GHREADS), "read", "--repo", str(self.repo), "--out", str(self.tmp / "x")],
                           capture_output=True, text=True, encoding="utf-8", timeout=60)
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.tmp / "x").exists())


@contextlib.contextmanager
def gh_env(values):
    """os.environ に values を置く（None の名は外す）。抜ける時に元へ戻す"""
    saved = {k: os.environ.get(k) for k in values}
    try:
        for k, v in values.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class WriteCase(unittest.TestCase):
    """ghreads._write は非公開の本文を持つ読み出し（盤面の github.json。ghreads.place）を、umask に依らず所有者だけの権限
    （0600）で置き、書き込みが落ちても一時のファイルを残さない"""

    DOC = {"version": 1, "pr": {"7": {"baseRefOid": "b" * 40, "headRefOid": "h" * 40, "body": "非公開の本文"}}, "issue": {}}

    def test_write_is_owner_only_even_under_open_umask(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            out = pathlib.Path(tmp_str) / "reads" / "x.json"
            old = os.umask(0)
            try:
                ghreads._write(out, self.DOC)
            finally:
                os.umask(old)
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), self.DOC)

    def test_write_replaces_loose_tmp_and_out_with_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            out = tmp / "x.json"
            out.write_text("{}", encoding="utf-8")
            out.chmod(0o644)
            leftover = tmp / f".{out.name}.{os.getpid()}.tmp"
            leftover.write_text("前の回の残り", encoding="utf-8")
            leftover.chmod(0o666)
            ghreads._write(out, self.DOC)
            self.assertEqual(stat.S_IMODE(out.stat().st_mode), 0o600)
            self.assertEqual(json.loads(out.read_text(encoding="utf-8")), self.DOC)
            self.assertEqual(sorted(p.name for p in tmp.iterdir()), ["x.json"])

    def test_write_failure_leaves_no_tmp(self):
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            out = tmp / "x.json"
            with mock.patch.object(ghreads.os, "replace", side_effect=OSError("boom")):
                with self.assertRaises(OSError):
                    ghreads._write(out, self.DOC)
            self.assertEqual(sorted(p.name for p in tmp.iterdir()), [])


class EntryReadsCase(unittest.TestCase):
    """entry.check_inputs の pr は gh を呼ばず、start が run の中で読んだ物（reads）の base・head を読む"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = pathlib.Path(self._tmp.name)
        self.repo = tmp / "repo"
        self.fork = committed_copy(self.repo, SEED)
        with (self.repo / "stats.py").open("a", encoding="utf-8") as f:
            f.write("\n# 変更\n")
        git(self.repo, "commit", "-q", "-am", "change")
        self.head = git(self.repo, "rev-parse", "HEAD")
        bin_, self.calls, _ = fake_gh(tmp)
        env = mock.patch.dict("os.environ", {"PATH": f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}"})
        env.start()
        self.addCleanup(env.stop)

    def check(self, reads):
        try:
            return entry.check_inputs({"request": "", "pr": "7"}, self.repo, reads=reads)
        except TypeError as e:
            self.fail(f"check_inputs が読み出しの写しを受けない: {e}")

    def reads(self, **pr7):
        return {"version": 1, "pr": {"7": {"baseRefOid": self.fork, "headRefOid": self.head, "title": "題", "body": "本文",
                                           **pr7}}, "issue": {}}

    def test_pr_reads_copy_not_gh(self):
        """差分の根は写しの baseRefOid と HEAD の merge-base、PR の題と本文は添え物の pr。gh は 1 度も起こさない"""
        try:
            got = self.check(self.reads())
        except entry.InputRefused as e:
            self.fail(f"写しの PR を拒んだ: {e}")
        self.assertEqual(got["base_rev"], self.fork)
        self.assertEqual(got["base"], {"rev": self.fork, "from": "pr", "name": "7", "label": "PR #7「題」"})
        self.assertEqual(got["pr"], {"number": "7", "title": "題", "body": "本文"})
        self.assertEqual(gh_calls(self.calls), [])

    def test_pr_refused_when_copy_unreadable_missing_or_head_differs(self):
        """写しが無い・その PR の項が無い・unreadable・base か head が欠ける・head が HEAD と違う・base の版が対象に無い → 拒む
        （1 行。gh で読み直さない）"""
        unreadable = {"version": 1, "pr": {"7": {"status": "unreadable", "reason": "gh: exit 4"}}, "issue": {}}
        no_head = self.reads()
        del no_head["pr"]["7"]["headRefOid"]
        for name, reads, words in (("none", None, "7"), ("absent", {"version": 1, "pr": {}, "issue": {}}, "7"),
                                   ("unreadable", unreadable, "7"), ("no-head", no_head, "7"),
                                   ("head", self.reads(headRefOid=self.fork), "HEAD"),
                                   ("base", self.reads(baseRefOid="1" * 40), "対象に無い")):
            with self.subTest(name):
                with self.assertRaises(entry.InputRefused) as cm:
                    self.check(reads)
                self.assertIn(words, str(cm.exception))
                self.assertNotIn("\n", str(cm.exception))
                self.assertNotIn("github_reads", str(cm.exception))   # 消えた入力を勧めない
        self.assertEqual(gh_calls(self.calls), [])

    def test_pr_refusal_says_what_to_do(self):
        """読めなかった PR の拒みは次の手を言う: gh が読めなかった → 利用者の gh でログインしてから。forge の無い対象で
        条件外 → base を名指して回す"""
        unreadable = {"version": 1, "pr": {"7": {"status": "unreadable", "reason": "gh pr が exit 4"}}, "issue": {}}
        na = {"version": 1, "pr": {"7": {"status": "not_applicable", "reason": "no_forge: local_path（x）"}}, "issue": {}}
        for reads, words in ((unreadable, "gh でログイン"), (na, "base を名指")):
            with self.subTest(words):
                with self.assertRaises(entry.InputRefused) as cm:
                    self.check(reads)
                self.assertIn(words, str(cm.exception))
                self.assertIn(reads["pr"]["7"]["reason"], str(cm.exception))


class StartReadsCase(unittest.TestCase):
    """entry.start は名指した PR・issue を run の中で gh で読んで盤面の根の github.json に置き、再開では盤面の写しを使う"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)
        self.bin, self.calls, self.login = fake_gh(self.tmp)
        env = {name: None for name in GH_ENV}
        env.update({"WORKS_ADAPTER_HOME": str(self.tmp / "adapter-home"), entryshape.NO_AUTH_ENV: None,
                    "PATH": f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}", "GH_CONFIG_DIR": str(self.login)})
        ctx = gh_env(env)
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def ready(self, name="board", head=None):
        """PR #7 の head を HEAD にした対象と入力。(対象, 盤面, 入力)。偽の gh の PR #7 は base が種の commit"""
        repo = linekit.seed_repo(self.tmp / f"repo-{name}", declared=True)
        fork = linekit.git(repo, "rev-parse", "HEAD")
        with (repo / "stats.py").open("a", encoding="utf-8") as f:
            f.write("\n# 変更\n")
        linekit.git(repo, "commit", "-q", "-am", "change")
        self.bin, self.calls, self.login = fake_gh(self.tmp, base=fork, head=head or linekit.git(repo, "rev-parse", "HEAD"))
        raw = {"request": "", "pr": "7", "test_cmd": "", "thickness": "", "gates": "", "final_gate": "", "adapter": "",
               "policy_md": ""}
        return repo, self.tmp / name, raw

    def test_start_reads_pr_inside_run_and_resumes_from_board_copy(self):
        """pr を名指した start は run の中で gh を対象の根で呼び、盤面の根に github.json（0600）を置く。呼び直し（Archon の
        再開）は盤面の写しを使い、gh を呼び直さない"""
        repo, board, raw = self.ready()
        for attempt in ("first", "resume"):
            with self.subTest(attempt):
                try:
                    got = entry.start(board, repo, dict(raw), run_id="run-7")
                except entry.InputRefused as e:
                    self.fail(f"run の中で PR を読んで始められない: {e}")
                self.assertTrue(got["ok"])
                doc = json.loads((board / "github.json").read_text(encoding="utf-8"))
                self.assertEqual(doc["pr"]["7"]["title"], "非公開の題")
                self.assertEqual(stat.S_IMODE((board / "github.json").stat().st_mode), 0o600)
                if attempt == "first":
                    first = len(gh_calls(self.calls))
                    self.assertGreater(first, 0)
                    self.assertEqual({cwd for cwd, _ in gh_calls(self.calls)}, {str(repo.resolve())})
                else:
                    self.assertEqual(len(gh_calls(self.calls)), first, "再開で gh を呼び直した")

    def test_start_writes_pr_file_only_for_pr(self):
        """PR を名指した run だけ、盤面の根に pr.md（PR の番号・題・本文。0600）を置き、出口の pr_file がそのパス。目的の役が
        出典 ① PR 説明として読む（前は --pr だけの run で役に PR の文を渡す道が無かった）。PR の無い run は空で、置かない"""
        repo, board, raw = self.ready()
        got = entry.start(board, repo, dict(raw), run_id="run-7")
        path = board / entryshape.PR_FILE
        self.assertEqual(got["pr_file"], str(path))
        text = path.read_text(encoding="utf-8")
        for part in ("PR #7", "非公開の題", "非公開の本文"):
            self.assertIn(part, text)
        self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
        self.assertEqual(entry.start(board, repo, dict(raw), run_id="run-7")["pr_file"], str(path))   # 呼び直しも同じ
        req = self.tmp / "plain.json"
        req.write_text(json.dumps([{"where": "stats.py", "text": "直す"}]), encoding="utf-8")
        other = self.tmp / "board-plain"
        got = entry.start(other, repo, {**raw, "pr": "", "request": str(req)}, run_id="run-p")
        self.assertEqual(got["pr_file"], "")
        self.assertFalse((other / entryshape.PR_FILE).exists())

    def test_start_reads_request_named_items(self):
        """依頼の欄 pr・issue の名指しも run の中で読み、盤面の github.json に載る（読めない項は記録して進む）"""
        repo, board, raw = self.ready()
        req = self.tmp / "req.json"
        req.write_text(json.dumps({"findings": [ROW], "pr": [7], "issue": [9, 11]}, ensure_ascii=False), encoding="utf-8")
        got = entry.start(board, repo, {**raw, "pr": "", "request": str(req)}, run_id="run-r")
        self.assertTrue(got["ok"])
        doc = json.loads((board / "github.json").read_text(encoding="utf-8"))
        self.assertEqual(sorted(doc["pr"]), ["7"])
        self.assertEqual(doc["issue"]["9"]["title"], "課題の題")
        self.assertEqual(doc["issue"]["11"]["status"], "unreadable")

    def test_start_without_names_does_not_call_gh(self):
        """名指しが無ければ gh を呼ばず、github.json も置かない"""
        repo, board, raw = self.ready()
        req = self.tmp / "plain.json"
        req.write_text(json.dumps([ROW], ensure_ascii=False), encoding="utf-8")
        entry.start(board, repo, {**raw, "pr": "", "request": str(req)}, run_id="run-n")
        self.assertEqual(gh_calls(self.calls), [])
        self.assertFalse((board / "github.json").exists())

    def test_start_pr_unreadable_refuses_in_one_line(self):
        """利用者の gh のログインが見えない run の --pr は、盤面を作らずに 1 行で拒む。GitHub の対象ならログインの案内、
        forge の無い対象（gh も GitHub のホストを見つけない）なら base を名指す案内"""
        repo, board, raw = self.ready()
        with gh_env({"GH_CONFIG_DIR": None, "XDG_CONFIG_HOME": str(self.tmp / "no-login")}):
            with self.assertRaises(entry.InputRefused) as cm:
                entry.start(self.tmp / "b-local", repo, dict(raw), run_id="run-l")
        self.assertIn("base を名指", str(cm.exception))
        linekit.git(repo, "remote", "add", "origin", "git@github.com:o/r.git")
        with gh_env({"GH_CONFIG_DIR": None, "XDG_CONFIG_HOME": str(self.tmp / "no-login")}):
            with self.assertRaises(entry.InputRefused) as cm:
                entry.start(board, repo, dict(raw), run_id="run-u")
        text = str(cm.exception)
        self.assertIn("exit 4", text)
        self.assertIn("gh でログイン", text)
        self.assertNotIn("\n", text)
        self.assertFalse((board / "record.json").exists())
        self.assertFalse((board / "github.json").exists())

    def test_no_auth_run_refuses_named_items_in_one_line(self):
        """WORKS_DEV_NO_AUTH=1 の run（利用者の gh を継がない）で PR・issue を名指すと、gh を呼ばずに 1 行で拒む（黙って
        読めないと記録しない）。名指しの無い run は今どおり通る"""
        repo, board, raw = self.ready()
        req = self.tmp / "req.json"
        req.write_text(json.dumps({"findings": [ROW], "issue": [9]}, ensure_ascii=False), encoding="utf-8")
        with gh_env({entryshape.NO_AUTH_ENV: "1"}):
            for name, given in (("pr", raw), ("issue", {**raw, "pr": "", "request": str(req)})):
                with self.subTest(name):
                    with self.assertRaises(entry.InputRefused) as cm:
                        entry.start(self.tmp / f"b-{name}", repo, dict(given), run_id="run-x")
                    text = str(cm.exception)
                    self.assertIn(entryshape.NO_AUTH_ENV, text)
                    self.assertNotIn("\n", text)
            self.assertEqual(gh_calls(self.calls), [])
            plain = self.tmp / "plain.json"
            plain.write_text(json.dumps([ROW], ensure_ascii=False), encoding="utf-8")
            self.assertTrue(entry.start(board, repo, {**raw, "pr": "", "request": str(plain)}, run_id="run-p")["ok"])


def start_script():
    spec = importlib.util.spec_from_file_location("works_line_start_for_ghreads", ROOT / "blk-entry" / "scripts" / "start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LineWiringCase(unittest.TestCase):
    def test_line_has_no_reads_file_input_and_declares_launch_mark(self):
        """ラインは隔離の前の読み出しのファイルを受けない（入力 github_reads が無く、start.py も読まない）。殻が起動を run に
        結ぶ印 launch_mark は入力に在り（Archon が run の metadata.inputs に残す）、入口のブロックへ生の事実として渡すだけ
        （ブロックの中の open が start の控えに残す。ほかの節には渡さない）"""
        y = yaml.safe_load((ROOT / "darkfactory" / "darkfactory.yaml").read_text(encoding="utf-8"))
        self.assertNotIn("github_reads", y.get("inputs") or {})
        self.assertIn("launch_mark", y.get("inputs") or {})
        start = next(n for n in y["nodes"] if n.get("include") == "blk-entry")
        self.assertNotIn("github_reads", start["with"])
        others = [n for n in y["nodes"] if n is not start]
        self.assertNotIn("launch_mark", json.dumps(others, ensure_ascii=False))
        self.assertEqual(start["with"]["launch_mark"], "$INPUTS.launch_mark")
        mod = start_script()
        self.assertNotIn("INPUTS_GITHUB_READS", mod.INPUTS)
        self.assertNotIn("INPUTS_GITHUB_READS", mod.OPTIONAL)
        order = next(r for r in linekit.LINE_ORDER if r.get("block") == "blk-entry")
        self.assertNotIn("github_reads", order["with"])

if __name__ == "__main__":
    unittest.main()
