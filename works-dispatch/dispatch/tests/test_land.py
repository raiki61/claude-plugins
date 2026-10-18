"""部署の成果をメインブランチに入れる（入口の --land。landing.py と nodes/land.py・nodes/bump.py）。

git は本物を使う。一時のフォルダに、GitHub に見立てた裸のリポジトリと、それを origin にした元の clone と、部署の worktree を作る。
本物の GitHub と本物の main には触らない。herdr と gh は偽物にする（gh の偽物は、ゲートの CI の結果を試験が決める）。
"""

import contextlib
import io
import json
import os
import pathlib
import subprocess
import tempfile
import unittest
from unittest import mock

from . import DISPATCH  # noqa: F401
import dispatch
import ghx
import gitx
import herdr as real_herdr
import landing
from config import Repo
from nodes import bump, land


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True, encoding="utf-8",
                          errors="replace").stdout.strip()


def write(path, text):
    pathlib.Path(path).parent.mkdir(parents=True, exist_ok=True)
    pathlib.Path(path).write_text(text, encoding="utf-8")


def commit(cwd, msg="x"):
    git("-C", cwd, "add", "--all")
    git("-C", cwd, "commit", "-q", "-m", msg)
    return git("-C", cwd, "rev-parse", "HEAD")


# git の持ち主の設定（署名・フックなど）に左右されないよう、全体の設定を空のファイルにし、名前とメールを環境で渡す
def isolated_git(tmp):
    empty = os.path.join(tmp, "gitconfig")
    write(empty, "")
    return mock.patch.dict(os.environ, {"GIT_CONFIG_GLOBAL": empty, "GIT_CONFIG_NOSYSTEM": "1",
                                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
                                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"})


MARKET = """{
  "name": "m",
  "metadata": {
    "description": "d",
    "version": "0.9.0"
  },
  "plugins": [
    {"name": "one", "source": "./one"},
    {"name": "two", "source": "./two"}
  ]
}
"""

CHANGELOG = """# 変更の記録

## [Unreleased]

## [0.1.0] - 2026-01-01

### Added

- 始め
"""


class World:
    """裸の origin・元の clone・部署の worktree（ブランチ feat/a）。元の clone は main に居る。"""

    def __init__(self, tmp, files=None):
        self.tmp = tmp
        self.remote = os.path.join(tmp, "o", "r.git")
        self.source = os.path.join(tmp, "src")
        git("init", "--bare", "-q", "-b", "main", self.remote)
        git("clone", "-q", self.remote, self.source)
        git("-C", self.source, "symbolic-ref", "HEAD", "refs/heads/main")
        for rel, text in (files or {"README.md": "r\n"}).items():
            write(os.path.join(self.source, rel), text)
        commit(self.source, "init")
        git("-C", self.source, "push", "-q", "origin", "HEAD:refs/heads/main")
        git("-C", self.source, "fetch", "-q", "origin")
        git("-C", self.source, "remote", "set-head", "origin", "main")   # git の版によらず origin/HEAD を持たせる
        self.dept = os.path.join(tmp, "wt", "a")
        git("-C", self.source, "worktree", "add", "-q", "-b", "feat/a", self.dept, "origin/main")

    def work(self, rel="a.txt", text="a\n"):
        write(os.path.join(self.dept, rel), text)
        return commit(self.dept, "部署の作業")

    def move_main(self):
        """ほかの部署が先にメインブランチに入れた形: origin の main を 1 つ進める。"""
        other = os.path.join(self.tmp, "other")
        git("clone", "-q", self.remote, other)
        write(os.path.join(other, "b.txt"), "b\n")
        commit(other, "ほかの部署")
        git("-C", other, "push", "-q", "origin", "HEAD:refs/heads/main")

    def origin(self, ref):
        return git("--git-dir", self.remote, "rev-parse", f"refs/heads/{ref}")

    def has(self, ref):
        return subprocess.run(["git", "--git-dir", self.remote, "rev-parse", "--verify", "--quiet", f"refs/heads/{ref}"],
                              capture_output=True).returncode == 0


class FakeHerdr:
    HerdrError = real_herdr.HerdrError

    def __init__(self, world):
        self.world = world
        self.prompts = []
        self._panes = [{"pane_id": "P1", "workspace_id": "W1", "cwd": world.dept, "agent": "claude"}]

    def panes(self):
        return list(self._panes)

    def worktrees(self, source):
        out = []
        for block in git("-C", source, "worktree", "list", "--porcelain").split("\n\n"):
            lines = dict(line.split(" ", 1) if " " in line else (line, "") for line in block.splitlines())
            if "worktree" in lines:
                path = os.path.normpath(lines["worktree"])
                out.append({"path": path, "branch": lines.get("branch", "").replace("refs/heads/", "") or None,
                            "linked": os.path.realpath(path) != os.path.realpath(source), "prunable": False,
                            "workspace": "W1" if os.path.realpath(path) == os.path.realpath(self.world.dept) else None})
        return out

    def prompt(self, target, text, wait):
        self.prompts.append((target, text))
        return "sent"


class FakeGh:
    """ゲートの CI。conclusion を試験が決める。on_run は run を返す前に呼ぶ（その間にメインブランチが進む形を作る）。"""

    def __init__(self, conclusion="success", appear=0, on_run=None):
        self.conclusion, self.appear, self.on_run = conclusion, appear, on_run
        self.asked, self.prs = 0, []

    def runs_for(self, repo, branch, sha, env=None):
        self.asked += 1
        self.seen = (branch, sha)
        if self.asked <= self.appear:
            return []
        if self.on_run:
            self.on_run()
        return [{"id": 7, "status": "in_progress", "conclusion": None, "url": "https://ci/7"}]

    def watch_run(self, repo, run_id, env=None):
        return {"id": run_id, "status": "completed", "conclusion": self.conclusion, "url": "https://ci/7"}

    def run_failure(self, repo, run_id, lines=20, env=None):
        return ["落ちた job: test（step: run）", "AssertionError: 版が据え置き"]

    def create_pr(self, repo, branch, base, env=None):
        self.prs.append((branch, base))
        return "https://pr/1"


class Ports:
    def __init__(self, world, gh=None, attrs=None):
        self.world = world
        self.herdr = FakeHerdr(world)
        self.gh = gh or FakeGh()
        self.git = gitx
        self._attrs = attrs or {"name": "a", "session": "s1", "role": "worker"}
        self.account_env = {}   # claude を呼ぶ環境（本物は Ports.account_env）

    def places(self, repo):
        return self.herdr.worktrees(repo.source)

    def attrs(self, path):
        return dict(self._attrs) if os.path.realpath(path) == os.path.realpath(self.world.dept) else {}

    def is_clean(self, path):
        return gitx.is_clean(path)

    def default_branch(self, repo):
        return "main"

    def gh_env(self, repo):
        return None


def no_rows(cfg, repo, ports, found, notes):
    return []


class LandCase(unittest.TestCase):
    def setUp(self):
        self.tmp = os.path.realpath(tempfile.mkdtemp(prefix="dispatch-land-"))
        self.env = isolated_git(self.tmp)
        self.env.start()
        self.addCleanup(self.env.stop)
        self.config = os.path.join(self.tmp, "conf", "dispatch.toml")   # 無いファイル（設定の置き場を一時のフォルダに向ける）

    def land(self, world, ports, rows=no_rows, checker=None, today="2026-10-16", name="a", dry_run=False, keep_removal=False):
        repo = Repo("o/r", "", world.source, (), None, None)
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = landing.main(None, repo, name, ports, rows, {"running": "会話がまだ動いている", "resident": "常設の部署は畳まない"},
                                self.config, pause=lambda: None, today=today, dry_run=dry_run, keep_removal=keep_removal,
                                **({"checker": checker} if checker else {}))
        return code, out.getvalue()


CI_RULES = '[land]\nmode = "ff-after-ci"\ngate = "release/*"\n'
FLOW = ".github/workflows/t.yml"
CI_FILES = {".claude/company.toml": CI_RULES, FLOW: "on:\n  push:\n    branches: ['release/**']\n"}


class FastForwardAfterCi(LandCase):
    def test_green_and_main_is_ancestor_fast_forwards_main_and_drops_the_gate_branch(self):
        w = World(self.tmp, CI_FILES)
        head = w.work()
        ports = Ports(w)
        code, out = self.land(w, ports)
        self.assertEqual(code, 0, out)
        self.assertEqual(w.origin("main"), head)
        self.assertEqual(ports.gh.seen, ("release/a", head))
        self.assertFalse(w.has("release/a"), "入れた後もゲートのブランチが origin に残っている")
        self.assertEqual(git("-C", w.source, "rev-parse", "main"), head, "手元のメインブランチが fast-forward されていない")
        self.assertEqual(ports.herdr.prompts, [])

    def test_waits_until_the_run_appears(self):
        w = World(self.tmp, CI_FILES)
        w.work()
        ports = Ports(w, FakeGh(appear=3))
        code, out = self.land(w, ports)
        self.assertEqual(code, 0, out)
        self.assertEqual(ports.gh.asked, 4)

    def test_gate_without_ci_for_its_branch_stops_before_pushing(self):
        w = World(self.tmp, {".claude/company.toml": CI_RULES})
        before = w.origin("main")
        w.work()
        ports = Ports(w)
        code, out = self.land(w, ports)
        self.assertEqual(code, 1)
        self.assertIn("CI が起きない", out)
        self.assertFalse(w.has("release/a"))
        self.assertEqual(w.origin("main"), before)
        self.assertEqual(ports.gh.asked, 0)

    def test_gate_branch_that_names_the_department_branch_stops(self):
        w = World(self.tmp, {**CI_FILES, ".claude/company.toml": '[land]\nmode = "ff-after-ci"\ngate = "feat/*"\n'})
        head = w.work()
        git("-C", w.dept, "push", "-q", "origin", "HEAD:refs/heads/feat/a")
        code, out = self.land(w, Ports(w))
        self.assertEqual(code, 1)
        self.assertIn("部署のブランチと同じ名前", out)
        self.assertEqual(w.origin("feat/a"), head)

    def test_refused_push_without_main_moving_stops_without_asking(self):
        w = World(self.tmp, CI_FILES)
        before = w.origin("main")
        w.work()
        ports = Ports(w)
        real = gitx.push

        def push(cwd, sha, ref, force=False):
            if ref == "main":
                raise gitx.GitError("protected branch")
            return real(cwd, sha, ref, force)
        with mock.patch.object(gitx, "push", push):
            code, out = self.land(w, ports)
        self.assertEqual(code, 1)
        self.assertIn("push が断られた", out)
        self.assertEqual(ports.herdr.prompts, [])
        self.assertEqual(w.origin("main"), before)

    def test_failure_after_the_push_still_finishes_the_landing(self):
        w = World(self.tmp, CI_FILES)
        head = w.work()
        seen = []

        def broken(*a, **k):
            raise gitx.GitError("lock")
        with mock.patch.object(gitx, "advance_branch", broken):
            code, out = self.land(w, Ports(w), rows=lambda *a: seen.append(1) or [])
        self.assertEqual(code, 0, out)
        self.assertEqual(w.origin("main"), head)
        self.assertIn("そろえられなかった", out)
        self.assertFalse(w.has("release/a"))
        self.assertEqual(seen, [1])

    def test_main_moved_before_the_gate_is_rebased_by_git_and_lands(self):
        # メインブランチが先に進んでも、git が機械でリベースできれば --land が自分でリベースしてゲートに出す（部署の会話に頼まない）
        w = World(self.tmp, CI_FILES)
        w.work()
        w.move_main()
        ports = Ports(w)
        code, out = self.land(w, ports)
        self.assertEqual(code, 0, out)
        self.assertIn("git でメインブランチの上にリベースした", out)
        self.assertEqual(ports.herdr.prompts, [])
        self.assertEqual(git("--git-dir", w.remote, "log", "-2", "--format=%s", "main").splitlines(), ["部署の作業", "ほかの部署"])
        self.assertEqual(w.origin("feat/a"), w.origin("main"))   # origin の部署のブランチもリベースした物

    def test_main_moved_with_a_conflict_git_cannot_solve_asks_the_department_and_restores_the_branch(self):
        w = World(self.tmp, CI_FILES)
        head = w.work(rel="b.txt", text="部署の b\n")   # ほかの部署も b.txt を書く
        w.move_main()
        moved = w.origin("main")
        ports = Ports(w)
        code, out = self.land(w, ports)
        self.assertEqual(code, 1)
        self.assertEqual(w.origin("main"), moved)
        self.assertFalse(w.has("release/a"), "リベースが要るのにゲートに出した")
        self.assertEqual(git("-C", w.dept, "rev-parse", "HEAD"), head, "リベースを元に戻していない")
        self.assertEqual(git("-C", w.dept, "status", "--porcelain"), "")
        self.assertEqual(len(ports.herdr.prompts), 1)
        self.assertIn("リベースし", ports.herdr.prompts[0][1])
        self.assertIn("版を上げ直して", ports.herdr.prompts[0][1])
        self.assertIn("ぶつかるファイル: b.txt", ports.herdr.prompts[0][1])

    def test_a_changelog_conflict_at_the_top_of_unreleased_is_solved_with_the_department_lines_first(self):
        log = "# 記録\n\n## [Unreleased]\n\n## [0.1.0] - 2026-10-01\n\n- 初め\n"
        w = World(self.tmp, {**CI_FILES, "CHANGELOG.md": log})
        w.work(rel="CHANGELOG.md", text=log.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n- 部署の直し\n"))
        other = os.path.join(self.tmp, "other")
        git("clone", "-q", w.remote, other)
        write(os.path.join(other, "CHANGELOG.md"), log.replace("## [Unreleased]\n", "## [Unreleased]\n\n## [0.1.1] - 2026-10-02\n\n- ほかの直し\n"))
        commit(other, "ほかの部署")
        git("-C", other, "push", "-q", "origin", "HEAD:refs/heads/main")
        ports = Ports(w)
        code, out = self.land(w, ports)
        self.assertEqual(code, 0, out)
        got = git("--git-dir", w.remote, "show", "main:CHANGELOG.md")
        self.assertNotIn("<<<<<<<", got)
        self.assertLess(got.index("- 部署の直し"), got.index("## [0.1.1]"))   # 部署の書き足しは Unreleased のすぐ下に
        self.assertLess(got.index("## [Unreleased]"), got.index("- 部署の直し"))
        self.assertIn("- ほかの直し", got)

    def test_main_moved_while_the_gate_ran_is_rebased_and_the_gate_runs_again(self):
        w = World(self.tmp, CI_FILES)
        w.work()
        moved = []

        def once():
            if not moved:
                moved.append(1)
                w.move_main()
        ports = Ports(w, FakeGh(on_run=once))
        code, out = self.land(w, ports)
        self.assertEqual(code, 0, out)
        self.assertIn("リベースしたブランチで、ゲートから回し直す", out)
        self.assertEqual(git("--git-dir", w.remote, "log", "-2", "--format=%s", "main").splitlines(), ["部署の作業", "ほかの部署"])
        self.assertEqual(ports.herdr.prompts, [])

    def test_resolve_changelog_leaves_other_conflicts_alone(self):
        d = tempfile.mkdtemp()
        path = os.path.join(d, "CHANGELOG.md")
        write(path, "# 記録\n\n## [0.1.0]\n<<<<<<< HEAD\nあ\n=======\nい\n>>>>>>> c\n")
        self.assertFalse(land.resolve_changelog(path))   # Unreleased の頭でないぶつかり
        other = os.path.join(d, "README.md")
        write(other, "## [Unreleased]\n<<<<<<< HEAD\nあ\n=======\nい\n>>>>>>> c\n")
        self.assertFalse(land.resolve_changelog(other))   # 変更の記録でないファイル

    def test_the_main_clone_with_unrelated_drafts_is_fast_forwarded_and_old_pre_push_checks_there_do_not_run(self):
        # 代表の clone の書きかけ（持ち主の日記）がメインブランチの変更に触れなければ、fast-forward で進める。push は部署の作業場から打つので、代表の
        # clone の古い push 前のゲート（.githooks）は走らない（2026-10-17 の my_notes。5d75df）
        w = World(self.tmp, CI_FILES)
        write(os.path.join(w.source, "diary.md"), "書きかけ\n")   # 追跡していないファイル
        git("-C", w.source, "config", "core.hooksPath", ".githooks")
        write(os.path.join(w.source, ".githooks", "pre-push"), "#!/bin/sh\nexit 1\n")   # 代表の clone の作業ツリーにだけ在る古いゲート
        os.chmod(os.path.join(w.source, ".githooks", "pre-push"), 0o755)
        head = w.work()
        code, out = self.land(w, Ports(w))
        self.assertEqual(code, 0, out)
        self.assertEqual(w.origin("main"), head)
        self.assertIn("手元の main: updated", out)
        self.assertEqual(git("-C", w.source, "rev-parse", "main"), head)
        self.assertEqual(pathlib.Path(w.source, "diary.md").read_text(encoding="utf-8"), "書きかけ\n")

    def test_the_main_clone_whose_draft_touches_the_landed_file_is_left_and_the_desk_is_told(self):
        w = World(self.tmp, CI_FILES)
        write(os.path.join(w.source, "a.txt"), "持ち主の書きかけ\n")   # 部署が足すのと同じファイル
        git("-C", w.source, "config", "--local", "extensions.worktreeConfig", "true")
        git("-C", w.source, "config", "--worktree", "company.name", "窓口")
        w.work()
        code, out = self.land(w, Ports(w))
        self.assertEqual(code, 0, out)
        self.assertIn("手元の main: dirty", out)
        self.assertIn("窓口 src/窓口 に台帳の知らせで渡した", out)
        info = {"name": None, "desk": None}
        again = landing._tell_desk(w.source, info, "main", w.origin("main"), "dirty")
        self.assertIn("同じ形は前に窓口へ知らせたので、知らせ直さない", again)   # 進められない間、--land のたびに窓口を起動しない
        self.assertEqual(pathlib.Path(w.source, "a.txt").read_text(encoding="utf-8"), "持ち主の書きかけ\n")   # 書きかけは触らない
        inbox = os.path.join(w.source, ".git", "company", "inbox", "log.jsonl")
        self.assertIn("進められなかった", pathlib.Path(inbox).read_text(encoding="utf-8"))

    def test_the_desk_is_told_when_git_fails_to_follow(self):
        # 代表の clone をそろえる git が誤りを返しても、黙らずに窓口に知らせる（今までは「そろえられなかった」を出すだけだった）
        w = World(self.tmp, CI_FILES)
        git("-C", w.source, "config", "--local", "extensions.worktreeConfig", "true")
        git("-C", w.source, "config", "--worktree", "company.name", "窓口")
        w.work()
        with mock.patch.object(land, "advance_local", side_effect=gitx.GitError("進められない")):
            code, out = self.land(w, Ports(w))
        self.assertEqual(code, 0, out)
        self.assertIn("手元の main: そろえられなかった: 進められない", out)
        self.assertIn("窓口 src/窓口 に台帳の知らせで渡した", out)

    def test_land_follows_the_pushed_commit_even_when_fetch_fails_after_the_push(self):
        # push の後の取り直しが一時に落ちても、push した commit は手元に在るので、窓口を起動せずに代表の clone を進める
        w = World(self.tmp, CI_FILES)
        head = w.work()
        real = land.refresh
        calls = []

        def flaky(source, main, g):
            calls.append(1)
            if len(calls) == 3:   # メインブランチの取り直しは、頭・ゲートの後・push の後の 3 回目
                raise gitx.GitError("ネットワークが無い")
            return real(source, main, g)
        with mock.patch.object(land, "refresh", side_effect=flaky):
            code, out = self.land(w, Ports(w))
        self.assertEqual(code, 0, out)
        self.assertIn("ネットワークが無い", out)
        self.assertIn("手元の main: updated", out)
        self.assertEqual(git("-C", w.source, "rev-parse", "main"), head)

    def test_catch_up_brings_the_main_clone_up_to_a_push_that_skipped_land(self):
        # 部署が --land を通さずに手で push した形（push が手元の origin/main も書き換える）。--deliver の後のそろえ（受付 d3f166）
        w = World(self.tmp, CI_FILES)
        write(os.path.join(w.source, "diary.md"), "書きかけ\n")
        head = w.work()
        git("-C", w.dept, "push", "-q", "origin", "HEAD:refs/heads/main")
        out = landing.catch_up(w.source, {"name": None, "desk": None}, "main", gitx)
        self.assertEqual(out, [f"代表の clone の main をメインブランチ {head[:7]} へ進めた"])
        self.assertEqual(git("-C", w.source, "rev-parse", "main"), head)
        self.assertEqual(pathlib.Path(w.source, "diary.md").read_text(encoding="utf-8"), "書きかけ\n")
        self.assertEqual(landing.catch_up(w.source, {"name": None, "desk": None}, "main", gitx), [])   # そろっていれば何も出さない

    def test_catch_up_tells_the_desk_when_the_main_clone_cannot_follow(self):
        w = World(self.tmp, CI_FILES)
        write(os.path.join(w.source, "a.txt"), "持ち主の書きかけ\n")   # 部署が足すのと同じファイル
        git("-C", w.source, "config", "--local", "extensions.worktreeConfig", "true")
        git("-C", w.source, "config", "--worktree", "company.name", "窓口")
        before = git("-C", w.source, "rev-parse", "main")
        w.work()
        git("-C", w.dept, "push", "-q", "origin", "HEAD:refs/heads/main")
        (line,) = landing.catch_up(w.source, {"name": None, "desk": None}, "main", gitx)
        self.assertIn("窓口 src/窓口 に台帳の知らせで渡した", line)
        self.assertEqual(git("-C", w.source, "rev-parse", "main"), before)
        self.assertEqual(pathlib.Path(w.source, "a.txt").read_text(encoding="utf-8"), "持ち主の書きかけ\n")

    def test_catch_up_without_the_network_follows_the_local_origin_ref(self):
        # 取り直せなくても、部署の push が書き換えた手元の origin/main まではそろえる
        w = World(self.tmp, CI_FILES)
        head = w.work()
        git("-C", w.dept, "push", "-q", "origin", "HEAD:refs/heads/main")
        with mock.patch.object(land, "refresh", side_effect=gitx.GitError("ネットワークが無い")):
            out = landing.catch_up(w.source, {"name": None, "desk": None}, "main", gitx)
        self.assertIn("ネットワークが無い", out[0])
        self.assertEqual(out[1], f"代表の clone の main をメインブランチ {head[:7]} へ進めた")

    def test_red_hands_the_failure_to_the_department(self):
        w = World(self.tmp, CI_FILES)
        before = w.origin("main")
        w.work()
        ports = Ports(w, FakeGh(conclusion="failure"))
        code, out = self.land(w, ports)
        self.assertEqual(code, 1)
        self.assertEqual(w.origin("main"), before)
        self.assertEqual(ports.herdr.prompts[0][0], "P1")
        self.assertIn("AssertionError: 版が据え置き", ports.herdr.prompts[0][1])
        self.assertNotIn("\n", ports.herdr.prompts[0][1])

    def test_no_pane_prints_the_request_for_the_caller(self):
        w = World(self.tmp, CI_FILES)
        w.work()
        ports = Ports(w, FakeGh(conclusion="failure"))
        ports.herdr._panes = []
        code, out = self.land(w, ports)
        self.assertEqual(code, 1)
        self.assertIn("次の文を部署に渡す", out)

    def test_already_landed_goes_straight_to_tidy(self):
        w = World(self.tmp, CI_FILES)
        seen = []
        code, out = self.land(w, Ports(w), rows=lambda *a: seen.append(1) or [])
        self.assertEqual(code, 0, out)
        self.assertIn("もうメインブランチ", out)
        self.assertEqual(seen, [1])

    def test_dirty_department_stops(self):
        w = World(self.tmp, CI_FILES)
        write(os.path.join(w.dept, "x.txt"), "x")
        code, out = self.land(w, Ports(w))
        self.assertEqual(code, 1)
        self.assertIn("未コミット", out)


class Tidy(LandCase):
    def test_landed_department_is_kept_when_rows_say_so(self):
        w = World(self.tmp, CI_FILES)
        w.work()
        row = {"path": w.dept, "branch": "feat/a", "removable": False, "reason": "resident"}
        code, out = self.land(w, Ports(w), rows=lambda *a: [row])
        self.assertEqual(code, 0, out)
        self.assertIn("常設の部署は畳まない", out)

    def test_landed_department_is_retired_with_the_clean_parts(self):
        w = World(self.tmp, CI_FILES)
        head = w.work()
        ports = Ports(w)
        removed = []

        def remove_worktree(source, path, label):
            removed.append(path)
            git("-C", source, "worktree", "remove", path)
        ports.herdr.remove_worktree = remove_worktree
        row = {"path": w.dept, "branch": "feat/a", "removable": True, "reason": None, "session": None, "pr_head": head}
        code, out = self.land(w, ports, rows=lambda *a: [row])
        self.assertEqual(code, 0, out)
        self.assertIn("部署を片付けた", out)
        self.assertEqual(removed, [w.dept])
        self.assertEqual(git("-C", w.source, "branch", "--list", "feat/a"), "")


class Leftover(LandCase):
    """入れたが会話がまだ動いていて残した部署は、入れた印を書いて残し、次の --land（ほかの部署）が片付ける。"""

    def setUp(self):
        super().setUp()
        self.w = World(self.tmp, CI_FILES)
        self.b = os.path.join(self.tmp, "wt", "b")
        self.ports = Ports(self.w)
        removed = self.removed = []

        def remove_worktree(source, path, label):
            removed.append(path)
            git("-C", source, "worktree", "remove", path)
        self.ports.herdr.remove_worktree = remove_worktree
        # 部署 a の属性は試験の表に、入れた印だけ本物の git から足す。部署 b は名前と会話だけ
        self.ports.attrs = lambda path: (
            {**self.ports._attrs, **{k: v for k, v in gitx.worktree_attrs(path).items() if k == "landed"}}
            if os.path.realpath(path) == os.path.realpath(self.w.dept) else
            {"name": "b", "session": "s2", "role": "worker"} if os.path.realpath(path) == os.path.realpath(self.b) else {})

    def row(self, path, branch, removable, reason=None):
        return {"path": path, "branch": branch, "name": os.path.basename(path), "removable": removable, "reason": reason,
                "session": None, "pr_head": git("-C", path, "rev-parse", "HEAD")}

    def test_left_department_is_marked_and_the_next_land_retires_it(self):
        head = self.w.work()
        code, out = self.land(self.w, self.ports, rows=lambda *a: [self.row(self.w.dept, "feat/a", False, "running")])
        self.assertEqual(code, 0, out)
        self.assertIn("部署は残した（会話がまだ動いている）。片付けられる形になれば（会話が止まった後など）、次の --land", out)
        self.assertEqual(gitx.worktree_attrs(self.w.dept).get("landed"), head)
        self.assertEqual(self.removed, [])
        # 会話が止まった後に、ほかの部署 b を入れる
        git("-C", self.w.source, "fetch", "-q", "origin")
        git("-C", self.w.source, "worktree", "add", "-q", "-b", "feat/b", self.b, "origin/main")
        write(os.path.join(self.b, "b.txt"), "b\n")
        commit(self.b, "部署 b の作業")
        code, out = self.land(self.w, self.ports, name="b", rows=lambda *a: [self.row(self.w.dept, "feat/a", True),
                                                                             self.row(self.b, "feat/b", True)])
        self.assertEqual(code, 0, out)
        self.assertIn("部署を片付けた", out)
        self.assertIn("前の --land で残した部署 a を片付けた", out)
        self.assertEqual(sorted(self.removed), sorted([self.b, self.w.dept]))

    def test_other_departments_without_the_mark_are_not_touched(self):
        self.w.work()
        git("-C", self.w.source, "worktree", "add", "-q", "-b", "feat/b", self.b, "origin/main")
        code, out = self.land(self.w, self.ports, rows=lambda *a: [self.row(self.w.dept, "feat/a", True),
                                                                   self.row(self.b, "feat/b", True)])
        self.assertEqual(code, 0, out)
        self.assertEqual(self.removed, [self.w.dept])
        self.assertNotIn("前の --land", out)

    def test_resident_department_gets_no_mark(self):
        self.w.work()
        code, out = self.land(self.w, self.ports, rows=lambda *a: [self.row(self.w.dept, "feat/a", False, "resident")])
        self.assertEqual(code, 0, out)
        attrs = gitx.worktree_attrs(self.w.dept)
        self.assertNotIn("landed", attrs)
        self.assertNotIn("次の --land", out)
        # 常設の部署は作業場を残す。入れたブランチと commit を書き、部署が次のブランチに移った後の --land か --clean --apply が消す
        self.assertEqual(json.loads(attrs["landed-branches"]), {"feat/a": git("-C", self.w.dept, "rev-parse", "HEAD")})
        self.assertIn("入れたブランチは、部署が次のブランチに移った後", out)


class OverwriteGate(LandCase):
    """書き換えの取り合いのゲート: 部署がメインブランチを知った後にほかの部署がメインブランチへ入れた行を、部署のブランチが消していれば止める。"""

    RULES = '[land]\nmode = "ff-after-ci"\ngate = "check"\ncheck = "c"\n'

    def world(self):
        w = World(self.tmp, {".claude/company.toml": self.RULES, "calc.py": "def add():\n    pass\n"})
        self.base = w.origin("main")   # この部署がメインブランチを知った位置
        other = os.path.join(self.tmp, "other")   # 作業の部署が div をメインブランチに入れる
        git("clone", "-q", w.remote, other)
        write(os.path.join(other, "calc.py"), "def add():\n    pass\ndef div():\n    pass\n")
        self.div = commit(other, "div を足す")
        git("-C", other, "push", "-q", "origin", "HEAD:refs/heads/main")
        git("-C", w.dept, "fetch", "-q", "origin")
        git("-C", w.dept, "reset", "-q", "--hard", "origin/main")   # 担当がメインブランチの先頭からブランチを切った
        return w

    def ports(self, w, base=True):
        attrs = {"name": "a", "session": "s1", "role": "worker", **({"base": self.base} if base else {})}
        return Ports(w, attrs=attrs)

    def test_removing_lines_another_department_added_stops_and_says_which(self):
        w = self.world()
        before = w.origin("main")
        w.work("calc.py", "def add():\n    pass\ndef sub():\n    pass\n")   # 前に読んだ中身で書き直し、div を消した
        ports = self.ports(w)
        code, out = self.land(w, ports, checker=lambda cmd, cwd: (0, ""))
        self.assertEqual(code, 1, out)
        self.assertEqual(w.origin("main"), before, "止めたのにメインブランチを進めた")
        [(_, text)] = ports.herdr.prompts
        self.assertIn("calc.py:3「def div():」", text)
        self.assertIn(self.div[:7], text)
        self.assertIn("div を足す", text)
        self.assertIn("--keep-removal", text)

    def test_keep_removal_lands_on_purpose(self):
        w = self.world()
        head = w.work("calc.py", "def add():\n    pass\n")
        code, out = self.land(w, self.ports(w), checker=lambda cmd, cwd: (0, ""), keep_removal=True)
        self.assertEqual(code, 0, out)
        self.assertEqual(w.origin("main"), head)
        self.assertIn("--keep-removal で通す", out)

    def test_keeping_the_lines_passes_and_moves_the_known_position(self):
        w = self.world()
        head = w.work("calc.py", "def add():\n    pass\ndef div():\n    pass\ndef sub():\n    pass\n")
        code, out = self.land(w, self.ports(w), checker=lambda cmd, cwd: (0, ""))
        self.assertEqual(code, 0, out)
        self.assertIn("書き換えの取り合いのゲート: 通った", out)
        self.assertEqual(gitx.worktree_attrs(w.dept).get("base"), head, "入れた後のメインブランチを、次のゲートの位置にする")

    def test_department_without_the_known_position_is_noted_and_not_checked(self):
        w = self.world()
        head = w.work("calc.py", "def add():\n    pass\n")
        code, out = self.land(w, self.ports(w, base=False), checker=lambda cmd, cwd: (0, ""))
        self.assertEqual(code, 0, out)
        self.assertEqual(w.origin("main"), head)
        self.assertIn("メインブランチを知った位置（company.base）の記録が無い", out)

    def test_dry_run_reports_the_stop_without_typing(self):
        w = self.world()
        w.work("calc.py", "def add():\n    pass\n")
        ports = self.ports(w)
        code, out = self.land(w, ports, dry_run=True)
        self.assertEqual(code, 1, out)
        self.assertIn("止まる見立て", out)
        self.assertEqual(ports.herdr.prompts, [])


class OverwriteGateRenames(LandCase):
    """書き換えの取り合いのゲートと、ファイルの名前の付け替え: 名前を替えて新しい名前へ運んだ行は消したと数えず、本当に消した行では止める。"""

    RULES = OverwriteGate.RULES
    BODY = "".join(f"def f{i}():\n    return {i}\n" for i in range(10))   # 名前の付け替えと見なされるだけの、変えない行

    def world(self):
        w = World(self.tmp, {".claude/company.toml": self.RULES, "calc.py": self.BODY})
        self.base = w.origin("main")   # この部署がメインブランチを知った位置
        return w

    def add_div_on_main(self, w):
        """作業の部署が、古い名前の calc.py へ div をメインブランチに入れる。"""
        other = os.path.join(self.tmp, "other")
        git("clone", "-q", w.remote, other)
        write(os.path.join(other, "calc.py"), self.BODY + "def div():\n    pass\n")
        self.div = commit(other, "div を足す")
        git("-C", other, "push", "-q", "origin", "HEAD:refs/heads/main")

    def ports(self, w):
        return Ports(w, attrs={"name": "a", "session": "s1", "role": "worker", "base": self.base})

    def test_renamed_branch_carries_lines_main_added_to_the_old_name(self):
        w = self.world()
        git("-C", w.dept, "mv", "calc.py", "math.py")   # 部署がブランチで名前を替えた
        commit(w.dept, "calc.py を math.py にする")
        self.add_div_on_main(w)   # その間に、ほかの部署が古い名前へ行を入れた
        code, out = self.land(w, self.ports(w), checker=lambda cmd, cwd: (0, ""))
        self.assertEqual(code, 0, out)
        self.assertIn("書き換えの取り合いのゲート: 通った", out)
        landed = git("--git-dir", w.remote, "show", "refs/heads/main:math.py")
        self.assertIn("def div():", landed, "リベースで新しい名前へ運んだ行を残して入れる")

    def test_renaming_and_really_removing_the_lines_stops(self):
        w = self.world()
        self.add_div_on_main(w)
        git("-C", w.dept, "fetch", "-q", "origin")
        git("-C", w.dept, "reset", "-q", "--hard", "origin/main")   # 担当がメインブランチの先頭からブランチを切った
        git("-C", w.dept, "mv", "calc.py", "math.py")
        before = w.origin("main")
        w.work("math.py", self.BODY)   # 名前を替え、前に読んだ中身で書き直して div を消した
        self.assertIn("rename from calc.py", gitx.diff_zero(w.dept, before, "HEAD"), "名前の付け替えとして読む形で試す")
        ports = self.ports(w)
        code, out = self.land(w, ports, checker=lambda cmd, cwd: (0, ""))
        self.assertEqual(code, 1, out)
        self.assertEqual(w.origin("main"), before, "止めたのにメインブランチを進めた")
        [(_, text)] = ports.herdr.prompts
        self.assertIn("calc.py:21「def div():」", text)   # main での古い名前と行番号で示す
        self.assertIn(self.div[:7], text)
        self.assertIn("div を足す", text)

    def test_removing_lines_main_added_while_renaming_stops(self):
        w = self.world()
        other = os.path.join(self.tmp, "other")   # 作業の部署が、名前を math.py に替えて div を足し、メインブランチに入れた
        git("clone", "-q", w.remote, other)
        git("-C", other, "mv", "calc.py", "math.py")
        write(os.path.join(other, "math.py"), self.BODY + "def div():\n    pass\n")
        self.div = commit(other, "math.py にして div を足す")
        git("-C", other, "push", "-q", "origin", "HEAD:refs/heads/main")
        git("-C", w.dept, "fetch", "-q", "origin")
        git("-C", w.dept, "reset", "-q", "--hard", "origin/main")
        before = w.origin("main")
        w.work("math.py", self.BODY.replace("def f0():", "def g0():"))   # f0 を書き換え、前に読んだ中身で div を消した
        ports = self.ports(w)
        code, out = self.land(w, ports, checker=lambda cmd, cwd: (0, ""))
        self.assertEqual(code, 1, out)
        self.assertEqual(w.origin("main"), before, "止めたのにメインブランチを進めた")
        [(_, text)] = ports.herdr.prompts
        self.assertIn("math.py:21「def div():」", text)
        self.assertNotIn("math.py:1「", text, "名前の付け替えで運んだだけの行は、ほかの部署が入れた行と数えない")

    def test_lines_that_look_like_headers_inside_a_hunk_are_contents(self):
        text = ("diff --git a/q.sql b/q.sql\nindex 1..2 100644\n--- a/q.sql\n+++ b/q.sql\n"
                "@@ -2,1 +1,0 @@\n--- a/x\n@@ -5,0 +5,1 @@\n+++ b/y\n")
        self.assertEqual(land._hunks(text, side="old"), {"q.sql": [(2, 1, 1, 0, ["--- a/x"]), (5, 0, 5, 1, ["+++ b/y"])]})
        self.assertEqual(list(land._hunks(text)), ["q.sql"])


class OtherModes(LandCase):
    def test_no_rules_does_nothing(self):
        w = World(self.tmp)
        before = w.origin("main")
        w.work()
        code, out = self.land(w, Ports(w))
        self.assertEqual(code, 0)
        self.assertIn("何もしない", out)
        self.assertEqual(w.origin("main"), before)

    def test_pr_mode_pushes_the_branch_and_opens_a_pr(self):
        w = World(self.tmp, {".claude/company.toml": '[land]\nmode = "pr"\n'})
        head = w.work()
        ports = Ports(w)
        code, out = self.land(w, ports)
        self.assertEqual(code, 0, out)
        self.assertEqual(ports.gh.prs, [("feat/a", "main")])
        self.assertEqual(w.origin("feat/a"), head)
        self.assertIn("https://pr/1", out)

    def test_role_override(self):
        w = World(self.tmp, {**CI_FILES, ".claude/company.toml": CI_RULES + '[land.roles.research]\nmode = "none"\n'})
        w.work()
        code, out = self.land(w, Ports(w, attrs={"name": "a", "role": "research"}))
        self.assertEqual(code, 0)
        self.assertIn("何もしない", out)

    def test_local_check_gate(self):
        w = World(self.tmp, {".claude/company.toml": '[land]\nmode = "ff-after-ci"\ngate = "check"\ncheck = "tools/check"\n'})
        head = w.work()
        ran = []
        code, out = self.land(w, Ports(w), checker=lambda cmd, cwd: ran.append((cmd, cwd)) or (0, "ok"))
        self.assertEqual(code, 0, out)
        self.assertEqual(ran, [("tools/check", w.dept)])
        self.assertEqual(w.origin("main"), head)

    def test_local_check_red(self):
        w = World(self.tmp, {".claude/company.toml": '[land]\nmode = "ff-after-ci"\ngate = "check"\ncheck = "tools/check"\n'})
        before = w.origin("main")
        w.work()
        ports = Ports(w)
        code, out = self.land(w, ports, checker=lambda cmd, cwd: (1, "line1\n壊れた\n"))
        self.assertEqual(code, 1)
        self.assertEqual(w.origin("main"), before)
        self.assertIn("壊れた", ports.herdr.prompts[0][1])

    def test_python_cache_the_department_made_does_not_stop_the_landing(self):
        # .gitignore の無いリポジトリで、部署が試しに import して作った __pycache__ は、手元だけの無視の決まりで数えない
        w = World(self.tmp, {".claude/company.toml": '[land]\nmode = "ff-after-ci"\ngate = "check"\ncheck = "c"\n'})
        head = w.work()
        cache = pathlib.Path(w.dept, "src", "__pycache__")
        cache.mkdir(parents=True)
        (cache / "calc.cpython-314.pyc").write_bytes(b"x")
        code, out = self.land(w, Ports(w), checker=lambda cmd, cwd: (0, "ok"))
        self.assertEqual(code, 0, out)
        self.assertEqual(w.origin("main"), head)

    def test_bad_rules_stop(self):
        w = World(self.tmp, {".claude/company.toml": '[land]\nmode = "ff-after-ci"\n'})
        w.work()
        code, out = self.land(w, Ports(w))
        self.assertEqual(code, 2)
        self.assertIn("land.gate", out)


def marketplace_files():
    return {".claude-plugin/marketplace.json": MARKET,
            "one/.claude-plugin/plugin.json": '{\n  "name": "one",\n  "version": "0.1.0"\n}\n',
            "one/CHANGELOG.md": CHANGELOG, "one/x.py": "1\n",
            "two/.claude-plugin/plugin.json": '{\n  "name": "two",\n  "version": "0.2.3"\n}\n',
            "two/CHANGELOG.md": CHANGELOG.replace("0.1.0", "0.2.3"), "two/y.py": "1\n"}


class BumpAtLand(LandCase):
    def test_bumps_on_a_scratch_place_and_lands_the_bump_commit(self):
        files = marketplace_files()
        files[".claude/company.toml"] = '[land]\nmode = "ff-after-ci"\ngate = "check"\ncheck = "c"\nbump = "marketplace"\n'
        w = World(self.tmp, files)
        write(os.path.join(w.dept, "one", "x.py"), "2\n")
        write(os.path.join(w.dept, "one", "CHANGELOG.md"), CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Added\n\n- 新しい口\n"))
        head = commit(w.dept, "one を直す")
        seen = []

        def checker(cmd, cwd):
            seen.append(json.loads(pathlib.Path(cwd, "one/.claude-plugin/plugin.json").read_text(encoding="utf-8"))["version"])
            return 0, ""
        code, out = self.land(w, Ports(w), checker=checker)
        self.assertEqual(code, 0, out)
        self.assertEqual(seen, ["0.2.0"], "ゲートが版を上げた後の木を見ていない")
        landed = w.origin("main")
        self.assertEqual(git("--git-dir", w.remote, "rev-parse", f"{landed}^"), head)
        self.assertEqual(git("--git-dir", w.remote, "log", "-1", "--format=%s", landed),
                         "chore(one): 版を上げる（one 0.2.0 / marketplace 0.10.0）")
        self.assertEqual(git("-C", w.dept, "rev-parse", "HEAD"), head, "部署のブランチを動かした")
        self.assertEqual(git("-C", w.source, "worktree", "list", "--porcelain").count("worktree "), 2, "一時の場所が残った")

    def test_bump_plan_and_files(self):
        w = World(self.tmp, marketplace_files())
        src = w.source
        self.assertEqual(bump.plan(src, gitx), ([], None))
        write(os.path.join(src, "two", "y.py"), "2\n")
        write(os.path.join(src, "two", "CHANGELOG.md"),
              CHANGELOG.replace("0.1.0", "0.2.3").replace("## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n- 直した\n"))
        commit(src, "two を直す")
        got = bump.make(src, "2026-10-16", gitx)
        self.assertEqual([(r["name"], r["new"]) for r in got["rows"]], [("two", "0.2.4")])
        self.assertEqual(got["marketplace"], "0.9.1")
        text = pathlib.Path(src, "two/CHANGELOG.md").read_text(encoding="utf-8")
        self.assertIn("## [Unreleased]\n\n## [0.2.4] - 2026-10-16\n\n### Fixed\n\n- 直した\n\n## [0.2.3] - 2026-01-01", text)
        self.assertEqual(pathlib.Path(src, "one/.claude-plugin/plugin.json").read_text(encoding="utf-8"),
                         marketplace_files()["one/.claude-plugin/plugin.json"])
        mk = pathlib.Path(src, ".claude-plugin/marketplace.json").read_text(encoding="utf-8")
        self.assertEqual(mk, MARKET.replace('"version": "0.9.0"', '"version": "0.9.1"'))
        self.assertEqual(bump.plan(src, gitx), ([], None), "版を上げた後も据え置きと数える")


    def test_tests_and_docs_only_are_a_patch_even_under_changed(self):
        # 記録が Changed のセクションでも、版を最後に上げた後に変えたのが試験と文書だけなら patch。利用者が動かす物を変えたら minor
        w = World(self.tmp, marketplace_files())
        src = w.source
        changed = CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Changed\n\n- 同梱の試験を直した\n")
        write(os.path.join(src, "one", "tests", "test_x.py"), "assert True\n")
        write(os.path.join(src, "one", "docs", "a.md"), "直した\n")
        write(os.path.join(src, "one", "CHANGELOG.md"), changed)
        write(os.path.join(src, "two", "y.py"), "2\n")
        write(os.path.join(src, "two", "CHANGELOG.md"), changed.replace("0.1.0", "0.2.3"))
        commit(src, "one は試験と文書、two は中身")
        rows, market = bump.plan(src, gitx)
        self.assertEqual([(r["name"], r["new"], r["level"], bool(r["why"])) for r in rows],
                         [("one", "0.1.1", "patch", True), ("two", "0.3.0", "minor", False)])
        self.assertEqual(market, ("0.9.0", "0.10.0"))
        self.assertTrue(bump.quiet("one/README.md", "one"))
        self.assertFalse(bump.quiet("one/skills/x/SKILL.md", "one"), "SKILL.md は Claude Code が読んで動く物")

    def test_a_manifest_description_only_edit_is_a_patch_but_other_keys_are_not(self):
        # tiers 0.5.0: plugin.json の説明の言い回しだけを直して Changed に書き、minor に上がった。説明の字は文書と同じに数える
        w = World(self.tmp, marketplace_files())
        src = w.source
        changed = CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Changed\n\n- 説明を直した\n")
        pj = pathlib.Path(src, "one/.claude-plugin/plugin.json")
        manifest = json.loads(pj.read_text(encoding="utf-8"))
        pj.write_text(json.dumps({**manifest, "description": "言い回しを直した"}, ensure_ascii=False), encoding="utf-8")
        write(os.path.join(src, "one", "CHANGELOG.md"), changed)
        commit(src, "one の説明を直す")
        rows, _ = bump.plan(src, gitx)
        self.assertEqual([(r["name"], r["level"]) for r in rows], [("one", "patch")])
        pj.write_text(json.dumps({**manifest, "description": "言い回しを直した", "dependencies": ["two"]}, ensure_ascii=False),
                      encoding="utf-8")
        commit(src, "one に依存を足す")
        rows, _ = bump.plan(src, gitx)
        self.assertEqual([(r["name"], r["level"]) for r in rows], [("one", "minor")])

    def test_empty_unreleased_stops_without_a_version(self):
        """中身の無い版は作らない: 置き場を変えたのに `## [Unreleased]` が空なら、版を上げずに止め、メインブランチに入れない。"""
        files = marketplace_files()
        files[".claude/company.toml"] = '[land]\nmode = "ff-after-ci"\ngate = "check"\ncheck = "c"\nbump = "marketplace"\n'
        w = World(self.tmp, files)
        before = w.origin("main")
        write(os.path.join(w.dept, "one", "x.py"), "2\n")
        write(os.path.join(w.dept, "one", "CHANGELOG.md"), CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n"))
        commit(w.dept, "one を直す（記録は見出しだけ）")
        ran = []
        code, out = self.land(w, Ports(w), checker=lambda cmd, cwd: ran.append(cmd) or (0, ""))
        self.assertEqual(code, 1, out)
        self.assertIn("one（one/CHANGELOG.md）", out)
        self.assertEqual(ran, [], "版を上げられないのにゲートを回した")
        self.assertEqual(w.origin("main"), before)
        self.assertEqual(git("-C", w.source, "worktree", "list", "--porcelain").count("worktree "), 2, "一時の場所が残った")

    def test_has_entries(self):
        self.assertFalse(bump.has_entries(CHANGELOG))
        self.assertFalse(bump.has_entries(CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n")))
        self.assertTrue(bump.has_entries(CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n- 直した\n")))


class DryRun(LandCase):
    """--land --dry-run は決まりと見立てを出すだけで、origin・手元の ref・部署の窓・ゲートのどれにも書かない。"""

    def snapshot(self, w):
        return (git("--git-dir", w.remote, "for-each-ref"), git("-C", w.source, "for-each-ref"),
                git("-C", w.source, "worktree", "list", "--porcelain"))

    def test_ci_gate_with_bump_reports_the_plan_and_writes_nothing(self):
        files = {**marketplace_files(), **CI_FILES}
        files[".claude/company.toml"] = CI_RULES + 'bump = "marketplace"\n'
        w = World(self.tmp, files)
        write(os.path.join(w.dept, "one", "x.py"), "2\n")
        write(os.path.join(w.dept, "one", "CHANGELOG.md"), CHANGELOG.replace("## [Unreleased]\n", "## [Unreleased]\n\n### Fixed\n\n- 直した\n"))
        head = commit(w.dept, "one を直す")
        before = self.snapshot(w)
        ports = Ports(w)
        code, out = self.land(w, ports, dry_run=True)
        self.assertEqual(code, 0, out)
        self.assertIn("取り込み方 ff-after-ci、ゲート release/*、版上げ marketplace", out)
        self.assertIn(f"- {head[:7]} one を直す", out)
        self.assertIn("one 0.1.0 → 0.1.1（patch） / marketplace 0.9.0 → 0.9.1", out)
        self.assertIn("release/a", out)
        self.assertEqual(self.snapshot(w), before, "空打ちなのに ref か worktree を書いた")
        self.assertEqual(git("-C", w.dept, "status", "--porcelain"), "", "空打ちなのに部署の場所のファイルを書き換えた")
        self.assertEqual((ports.gh.asked, ports.gh.prs, ports.herdr.prompts), (0, [], []))

    def test_main_moved_reports_the_rebase_without_fetching_or_asking(self):
        w = World(self.tmp, CI_FILES)
        w.work()
        w.move_main()
        before = self.snapshot(w)
        ports = Ports(w)
        code, out = self.land(w, ports, dry_run=True)
        self.assertEqual(code, 1, out)
        self.assertIn("リベースし", out)
        self.assertEqual(self.snapshot(w), before, "空打ちなのにメインブランチを取り直した")
        self.assertEqual(ports.herdr.prompts, [])

    def test_empty_unreleased_is_reported(self):
        files = marketplace_files()
        files[".claude/company.toml"] = '[land]\nmode = "ff-after-ci"\ngate = "check"\ncheck = "c"\nbump = "marketplace"\n'
        w = World(self.tmp, files)
        write(os.path.join(w.dept, "two", "y.py"), "2\n")
        commit(w.dept, "two を直す")
        code, out = self.land(w, Ports(w), dry_run=True)
        self.assertEqual(code, 1, out)
        self.assertIn("two（two/CHANGELOG.md）", out)

    def test_local_check_is_not_run(self):
        w = World(self.tmp, {".claude/company.toml": '[land]\nmode = "ff-after-ci"\ngate = "check"\ncheck = "tools/check"\n'})
        w.work()
        before = self.snapshot(w)
        ran = []
        code, out = self.land(w, Ports(w), checker=lambda cmd, cwd: ran.append(cmd) or (0, ""), dry_run=True)
        self.assertEqual(code, 0, out)
        self.assertEqual(ran, [])
        self.assertIn("手元の検証 tools/check", out)
        self.assertEqual(self.snapshot(w), before)

    def test_pr_mode_neither_pushes_nor_opens_a_pr(self):
        w = World(self.tmp, {".claude/company.toml": '[land]\nmode = "pr"\n'})
        w.work()
        ports = Ports(w)
        code, out = self.land(w, ports, dry_run=True)
        self.assertEqual(code, 0, out)
        self.assertEqual(ports.gh.prs, [])
        self.assertFalse(w.has("feat/a"))

    def test_already_landed_reports_the_tidy_without_retiring(self):
        w = World(self.tmp, CI_FILES)
        head = w.work()
        git("-C", w.dept, "push", "-q", "origin", f"{head}:refs/heads/main")
        retired = []
        rows = lambda cfg, repo, ports, found, notes: [{"path": w.dept, "removable": True, "branch": "feat/a"}]  # noqa: E731
        with mock.patch.object(landing.clean, "retire", lambda *a, **k: retired.append(a)):
            code, out = self.land(w, Ports(w), rows=rows, dry_run=True)
        self.assertEqual(code, 0, out)
        self.assertIn("もうメインブランチ main に入っている", out)
        self.assertIn("部署を片付ける", out)
        self.assertEqual(retired, [])

    def test_the_entry_passes_dry_run_to_land(self):
        got = {}
        with mock.patch.object(dispatch.config, "load", lambda *a, **k: None), \
                mock.patch.object(dispatch, "_department_repo", lambda cfg, r, ports, cwd: "repo"), \
                mock.patch.object(dispatch.landing, "main", lambda *a, **k: got.update(k) or 0):
            self.assertEqual(dispatch.main(["--land", "a", "--dry-run"], ports=type("P", (), {"cwd": lambda self: "/"})()), 0)
        self.assertTrue(got.get("dry_run"))


class Rules(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="dispatch-rules-")

    def read(self, text, role=None):
        path = os.path.join(self.dir, "company.toml")
        write(path, text)
        return land.read_rules(path, role)

    def test_missing_file_or_table_is_none(self):
        self.assertEqual(land.read_rules(os.path.join(self.dir, "nope.toml"))["mode"], "none")
        self.assertEqual(self.read('name = "x"\n')["mode"], "none")

    def test_doc_examples_read_clean(self):
        doc = (pathlib.Path(DISPATCH).parent / "docs" / "land.md").read_text(encoding="utf-8")
        blocks = [b.split("```", 1)[0] for b in doc.split("```toml\n")[1:]]
        lands = [b for b in blocks if "[land]" in b]
        self.assertGreaterEqual(len(lands), 2, "docs/land.md に [land] の例が 2 つ無い")
        for b in lands:
            got = self.read(b)
            self.assertEqual(got["problems"], [], b)
            self.assertEqual(got["mode"], "ff-after-ci")

    def test_problems(self):
        self.assertTrue(self.read('[land]\nmode = "merge"\n')["problems"])
        self.assertTrue(self.read('[land]\nmode = "ff-after-ci"\ngate = "check"\n')["problems"])
        self.assertTrue(self.read('[land]\nmode = "ff-after-ci"\ngate = "release"\n')["problems"])
        self.assertTrue(self.read('[land]\nmode = "ff-after-ci"\ngate = "*"\n')["problems"])
        self.assertTrue(self.read('[land]\nmode = "ff-after-ci"\ngate = "release-*"\n')["problems"])
        self.assertTrue(self.read('[land]\nmode = "pr"\nbump = "npm"\n')["problems"])
        self.assertTrue(self.read('[land]\nmode = 3\n')["problems"])
        self.assertTrue(self.read('[land\n')["problems"])

    def test_gate_branch(self):
        self.assertEqual(land.gate_branch("release/*", "land", "feat/company-land"), "release/land")
        self.assertEqual(land.gate_branch("release/*", "取り込み", "feat/company-land"), "release/feat-company-land")


class FailurePoints(unittest.TestCase):
    def test_run_failure_keeps_the_body_of_the_failed_log(self):
        def runner(argv, env=None):
            if "--log-failed" in argv:
                return subprocess.CompletedProcess(argv, 0, "test\trun\t2026-10-16T00:00:00Z AssertionError: x\n", "")
            jobs = {"jobs": [{"name": "test", "conclusion": "failure", "steps": [{"name": "run", "conclusion": "failure"}]},
                             {"name": "lint", "conclusion": "success", "steps": []}]}
            return subprocess.CompletedProcess(argv, 0, json.dumps(jobs), "")
        self.assertEqual(ghx.run_failure("o/r", 1, runner=runner),
                         ["落ちた job: test（step: run）", "2026-10-16T00:00:00Z AssertionError: x"])


class WatchRun(unittest.TestCase):
    def test_a_watch_that_returns_early_is_not_read_as_red(self):
        def runner(argv, env=None):
            body = {"databaseId": 1, "status": "in_progress", "conclusion": "", "url": "u"}
            return subprocess.CompletedProcess(argv, 0 if "view" in argv else 1, json.dumps(body), "")
        with self.assertRaises(ghx.GhError):
            ghx.watch_run("o/r", 1, runner=runner)
