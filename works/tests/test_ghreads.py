"""名指した PR・issue を隔離の前に読む部品（.shared/core/ghreads.py）と、その写しを線の入口が使う所の検査（設計書 2.8）。

gh は偽物（fake_gh）。偽の gh は、利用者のログイン（GH_CONFIG_DIR・$XDG_CONFIG_HOME/gh・$HOME/.config/gh の hosts.yml）が
見える時だけ非公開の中身を返し、見えない時は本物と同じく exit 4 で終わる。だから「隔離の前の env で読めば載り、隔離の後の
env（HOME の差し替え）では読めない」を、本物の GitHub に触れずに縛れる。

- read（python3 -I ghreads.py read）: 依頼の欄 pr・issue と --pr を cwd＝対象の根で 1 回だけ読み、PR の本文・コメント・
  レビュー・行コメントと issue の本文・コメントを書き先に置く。読めない項は status unreadable で残して 0。--pr の base・head が
  読めない時だけ、書かずに 0 以外
- adopt: 盤面の根の github.json を先に使い、無ければ渡されたファイルを写して元を消す
- 線の入口: entry.check_inputs は gh を呼ばず、渡された写しの base・head を読む。entry.start は github_reads を盤面へ写す
- ラインの入力 github_reads が start の節に渡る
"""
import importlib.util
import json
import os
import pathlib
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


class ReadCase(unittest.TestCase):
    """python3 -I ghreads.py read を、偽の gh を PATH の頭に置いて別のプロセスで回す"""

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
        self.out = self.tmp / "reads.json"
        self.req = self.tmp / "req.json"
        self.req.write_text(json.dumps({"findings": [ROW], "pr": [7], "issue": [9]}, ensure_ascii=False), encoding="utf-8")

    def read(self, *args, logged_in=True):
        env = hermetic.child_env(PATH=f"{self.bin}{os.pathsep}{os.environ.get('PATH', '')}", HOME=str(self.tmp / "home"))
        for name in GH_ENV:
            env.pop(name, None)
        if logged_in:
            env["GH_CONFIG_DIR"] = str(self.login)
        return subprocess.run([sys.executable, "-I", str(GHREADS), "read", "--repo", str(self.repo), *args,
                               "--out", str(self.out)], capture_output=True, text=True, encoding="utf-8", env=env,
                              cwd=str(self.tmp), timeout=60)

    def doc(self):
        self.assertTrue(self.out.exists(), "読み出しのファイルが書かれていない")
        return json.loads(self.out.read_text(encoding="utf-8"))

    def test_reads_named_pr_and_issue_with_user_login(self):
        """隔離の前の env（利用者のログインが見える）で、依頼が名指した PR の本文・コメント・レビュー・行コメントと issue の
        本文・コメントが載る。gh は対象の根を cwd にして呼び、行コメントは gh api --paginate の {owner}/{repo} で引く"""
        r = self.read("--request", str(self.req))
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = self.doc()
        pr = doc["pr"]["7"]
        self.assertEqual((pr["title"], pr["body"]), ("非公開の題", "非公開の本文"))
        self.assertEqual([c["body"] for c in pr["comments"]], ["非公開のコメント"])
        self.assertEqual([c["body"] for c in pr["reviews"]], ["非公開のレビュー"])
        self.assertEqual([c["body"] for c in pr["review_comments"]], ["非公開の行コメント"])
        self.assertNotEqual(pr.get("status"), "unreadable")
        issue = doc["issue"]["9"]
        self.assertEqual((issue["title"], issue["body"]), ("課題の題", "課題の本文"))
        self.assertEqual([c["body"] for c in issue["comments"]], ["課題のコメント"])
        calls = gh_calls(self.calls)
        self.assertTrue(calls)
        self.assertEqual({cwd for cwd, _ in calls}, {str(self.repo)})
        self.assertTrue(any("repos/{owner}/{repo}/pulls/7/comments" in a and "--paginate" in a for _, a in calls), calls)

    def test_isolated_login_marks_unreadable_and_goes_on(self):
        """隔離の後の env（HOME を差し替えてログインが見えない。gh は exit 4）では、名指した項に status unreadable と 1 行の
        理由を残して 0 で返る（依頼の欄の名指しでは run を止めない）"""
        r = self.read("--request", str(self.req), logged_in=False)
        self.assertEqual(r.returncode, 0, r.stderr)
        doc = self.doc()
        for got in (doc["pr"]["7"], doc["issue"]["9"]):
            self.assertEqual(got["status"], "unreadable")
            self.assertTrue(got["reason"].strip())
            self.assertNotIn("\n", got["reason"])
        self.assertNotIn("非公開", self.out.read_text(encoding="utf-8"))

    def test_cli_pr_is_read_and_unreadable_base_head_refuses(self):
        """--pr の番号は base・head を読む。ログインが見えれば base・head が載り、見えなければ書かずに 0 以外で終わる"""
        r = self.read("--request", "-", "--pr", "7")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual((self.doc()["pr"]["7"]["baseRefOid"], self.doc()["pr"]["7"]["headRefOid"]), ("b" * 40, "h" * 40))
        self.out.unlink()
        r = self.read("--request", "-", "--pr", "7", logged_in=False)
        self.assertNotEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertFalse(self.out.exists())
        self.assertIn("7", r.stderr)


class AdoptCase(unittest.TestCase):
    def test_adopt_copies_once_then_prefers_board_copy(self):
        """盤面の根に github.json が無ければ渡されたファイルを写して元を消し、在れば（再開の時）元が無くても盤面の写しを使う。
        何も渡されず盤面にも無ければ None"""
        adopt = getattr(ghreads, "adopt", None)
        self.assertIsNotNone(adopt, "ghreads.adopt が無い")
        with tempfile.TemporaryDirectory() as tmp_str:
            tmp = pathlib.Path(tmp_str)
            board = tmp / "board"
            board.mkdir()
            src = tmp / "reads.json"
            doc = {"version": 1, "pr": {"7": {"baseRefOid": "b" * 40, "headRefOid": "h" * 40}}, "issue": {}}
            src.write_text(json.dumps(doc), encoding="utf-8")
            self.assertEqual(adopt(board, str(src)), doc)
            self.assertEqual(json.loads((board / "github.json").read_text(encoding="utf-8")), doc)
            self.assertFalse(src.exists())
            self.assertEqual(adopt(board, str(src)), doc)
            other = tmp / "board2"
            other.mkdir()
            self.assertIsNone(adopt(other, ""))
            self.assertFalse((other / "github.json").exists())


class EntryReadsCase(unittest.TestCase):
    """entry.check_inputs の pr は gh を呼ばず、殻が隔離の前に読んだ写し（reads）の base・head を読む"""

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
        """差分の根は写しの baseRefOid と HEAD の merge-base、PR の題と本文は change.text。gh は 1 度も起こさない"""
        try:
            got = self.check(self.reads())
        except entry.InputRefused as e:
            self.fail(f"写しの PR を拒んだ: {e}")
        self.assertEqual(got["base_rev"], self.fork)
        self.assertEqual(got["change"], {"from": "pr", "name": "7", "text": "題\n\n本文"})
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
        self.assertEqual(gh_calls(self.calls), [])


class StartAdoptCase(unittest.TestCase):
    """entry.start はラインの入力 github_reads のファイルを盤面の根の github.json へ写して元を消し、再開では盤面の写しを使う"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)
        env = mock.patch.dict("os.environ", {"WORKS_ADAPTER_HOME": str(self.tmp / "adapter-home")})
        env.start()
        self.addCleanup(env.stop)

    def test_start_adopts_reads_and_resumes_from_board_copy(self):
        repo = linekit.seed_repo(self.tmp / "repo", declared=True)
        fork = linekit.git(repo, "rev-parse", "HEAD")
        with (repo / "stats.py").open("a", encoding="utf-8") as f:
            f.write("\n# 変更\n")
        linekit.git(repo, "commit", "-q", "-am", "change")
        head = linekit.git(repo, "rev-parse", "HEAD")
        bin_, calls, _ = fake_gh(self.tmp)
        env = mock.patch.dict("os.environ", {"PATH": f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}"})
        env.start()
        self.addCleanup(env.stop)
        src = self.tmp / "reads.json"
        doc = {"version": 1, "pr": {"7": {"baseRefOid": fork, "headRefOid": head, "title": "題", "body": "本文"}}, "issue": {}}
        src.write_text(json.dumps(doc), encoding="utf-8")
        board = self.tmp / "board"
        raw = {"request": "", "pr": "7", "github_reads": str(src), "test_cmd": "", "thickness": "", "gates": "",
               "final_gate": "", "adapter": "", "policy_md": ""}
        for attempt in ("first", "resume"):
            with self.subTest(attempt):
                try:
                    got = entry.start(board, repo, dict(raw), run_id="run-7")
                except entry.InputRefused as e:
                    self.fail(f"github_reads の写しで始められない: {e}")
                self.assertTrue(got["ok"])
                self.assertEqual(json.loads((board / "github.json").read_text(encoding="utf-8")), doc)
                self.assertFalse(src.exists())
        self.assertEqual(gh_calls(calls), [])


def start_script():
    spec = importlib.util.spec_from_file_location("works_line_start_for_ghreads", ROOT / "darkfactory" / "scripts" / "start.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class LineWiringCase(unittest.TestCase):
    def test_line_passes_github_reads_to_start(self):
        """ラインの入力 github_reads（既定は空）が start の節の with に渡り、start.py が読む（後から足した入力なので OPTIONAL）。
        器の LINE_ORDER の start も同じ鍵を渡す"""
        y = yaml.safe_load((ROOT / "darkfactory" / "darkfactory.yaml").read_text(encoding="utf-8"))
        self.assertIn("github_reads", y.get("inputs") or {})
        start = next(n for n in y["nodes"] if n.get("id") == "start")
        self.assertEqual(start["with"].get("github_reads"), "$INPUTS.github_reads")
        mod = start_script()
        self.assertEqual(mod.INPUTS.get("INPUTS_GITHUB_READS"), "github_reads")
        self.assertIn("INPUTS_GITHUB_READS", mod.OPTIONAL)
        order = next(r for r in linekit.LINE_ORDER if r["id"] == "start")
        self.assertEqual(order["with"].get("github_reads"), "$INPUTS.github_reads")


if __name__ == "__main__":
    unittest.main()
