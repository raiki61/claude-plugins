"""report ノードと入口（dispatch.py）。git は一時のフォルダの本物、herdr・claude・gh は偽物で、流れを回す。"""

import contextlib
import io
import json
import pathlib
import subprocess
import unittest

from . import DISPATCH  # noqa: F401
from .test_provision import make_world
import config
import dispatch
import ghx
import gitx
import herdr as real_herdr
from nodes import prs as prs_node
from nodes import report


class Report(unittest.TestCase):
    def test_no_prs_is_one_line(self):
        self.assertEqual(report.lines([], {}, []), ["自分の番の PR は無い"])

    def test_notes_come_first_and_one_line_per_pr(self):
        plan = [{"number": 7, "title": "直す", "outcome": "assigned", "clone_path": "/c/r-pr-7", "account": {"name": "p1"}},
                {"number": 9, "title": "見る", "outcome": "already_open", "clone_path": "/c/r-pr-9", "account": None}]
        got = report.lines(plan, {7: "sent"}, ["使用率の控えが無い: p3"])
        self.assertEqual(got[0], "使用率の控えが無い: p3")
        self.assertEqual(len(got), 3)
        self.assertEqual(got[1], "#7 直す  r-pr-7  p1  sent")
        self.assertEqual(got[2], "#9 見る  -  -  already_open")


class Prs(unittest.TestCase):
    def test_read_runs_vendored_whose_turn_with_json(self):
        calls = []

        def runner(argv, env=None):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"schema": 1, "prs": [{"number": 1}]}), "")

        self.assertEqual(prs_node.read("o/r", runner=runner), [{"number": 1}])
        self.assertTrue(calls[0][1].endswith("vendor/whose-turn.py"))
        self.assertEqual(calls[0][2:], ["--repo", "o/r", "--json"])

    def test_read_passes_env_to_whose_turn(self):
        seen = []

        def runner(argv, env=None):
            seen.append(env)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"schema": 1, "prs": []}), "")

        prs_node.read("o/r", runner=runner, env={"GH_TOKEN": "t"})
        self.assertEqual(seen, [{"GH_TOKEN": "t"}])

    def test_read_failure_raises(self):
        def runner(argv, env=None):
            return subprocess.CompletedProcess(argv, 1, "", "gh: not logged in")

        with self.assertRaises(prs_node.PrsError) as e:
            prs_node.read("o/r", runner=runner)
        self.assertIn("not logged in", str(e.exception))


def make_cfg():
    src, root = make_world()
    d = pathlib.Path(root).parent
    (d / "second.md").write_text("二手目", encoding="utf-8")
    (d / "c.toml").write_text(f"""
limits_dir = "{d}/limits"
accounts = [{{ name = "a1", command = "claude-a1", config_dir = "{d}/c1" }}]
[[repos]]
repo = "o/r"
second_prompt_file = "{d}/second.md"
source = "{src}"
clone_root = "{root}"
copy_files = ["frontend/.env.local"]
""", encoding="utf-8")
    return str(d / "c.toml"), root


class FakeHerdr:
    HerdrError = real_herdr.HerdrError

    def __init__(self, fail_run_for=()):
        self._panes = []
        self._fail = set(fail_run_for)
        self.writes = []

    def panes(self):
        return list(self._panes)

    def create_workspace(self, cwd, label):
        n = len(self._panes)
        self._panes.append({"pane_id": f"P{n}", "workspace_id": f"W{n}", "cwd": cwd, "agent": None})
        self.writes.append(("create_workspace", cwd, label))
        return {"workspace_id": f"W{n}", "pane_id": f"P{n}"}

    def close_workspace(self, workspace_id):
        self.writes.append(("close_workspace", workspace_id))
        self._panes = [p for p in self._panes if p["workspace_id"] != workspace_id]

    def run(self, pane, command):
        self.writes.append(("run", pane, command))
        if pane in self._fail:
            raise real_herdr.HerdrError(["herdr", "pane", "run"], "pane_not_found")

    def wait_ready(self, pane):
        return "idle"

    def agent(self, pane):
        return {"agent": "claude", "agent_status": "idle"}

    def prompt(self, target, text, wait):
        self.writes.append(("prompt", target, text, wait))
        return "idle" if wait else "sent"


class FakePorts(dispatch.Ports):
    """本物の Ports の読む口のうち、claude・gh・whose-turn を偽物にする。git は本物（一時のフォルダ）、herdr は偽物。"""

    def __init__(self, prs, problems=(), herdr=None):
        super().__init__(herdr_methods=lambda: set(), shell_has=lambda c: True, gh_ok=lambda repo, env=None: True)
        self._prs = prs
        self._problems = list(problems)
        self.herdr = herdr or FakeHerdr()
        self.git = gitx

    def preflight(self, cfg):
        return list(self._problems), []

    def fetch_prs(self, repo):
        return self._prs

    def list_sessions(self, config_dir):
        return []

    def read_limits(self, limits_dir, names):
        return {n: None for n in names}

    def now(self):
        return 0


def pr(n):
    return {"number": n, "title": f"t{n}", "head": f"feat/{n}", "url": f"u{n}", "role": "implementer", "days": 0}


def run_main(argv, ports):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = dispatch.main(argv, ports=ports)
    return rc, buf.getvalue()


def by_number(out):
    return {l.split()[0]: l for l in out.splitlines() if l.startswith("#")}


class Main(unittest.TestCase):
    def setUp(self):
        self.cfg, self.root = make_cfg()

    def test_dry_run_writes_nothing_and_says_create_or_reuse(self):
        pathlib.Path(self.root, "r-pr-2").mkdir()
        ports = FakePorts([pr(1), pr(2)])
        rc, out = run_main(["--config", self.cfg, "--dry-run"], ports)
        self.assertEqual(rc, 0)
        self.assertEqual(ports.herdr.writes, [])
        self.assertFalse(pathlib.Path(self.root, "r-pr-1").exists())
        lines = by_number(out)
        self.assertTrue(lines["#1"].endswith("create"))
        self.assertTrue(lines["#2"].endswith("reuse"))

    def test_preflight_problem_stops_before_anything(self):
        ports = FakePorts([pr(1)], problems=["herdr に届かない"])
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual(rc, 2)
        self.assertEqual(ports.herdr.writes, [])
        self.assertIn("herdr に届かない", out)

    def test_unreadable_prs_stop_with_one_line_not_a_traceback(self):
        ports = FakePorts([])

        def boom(repo):
            raise prs_node.PrsError("whose-turn --json（o/r）が読めない: Could not resolve")
        ports.fetch_prs = boom
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual(rc, 1)
        self.assertIn("止めた: whose-turn --json（o/r）が読めない", out)
        self.assertEqual(ports.herdr.writes, [])

    def test_no_prs_does_nothing(self):
        ports = FakePorts([])
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual((rc, ports.herdr.writes), (0, []))
        self.assertIn("自分の番の PR は無い", out)

    def test_creates_clone_then_launches_and_sends_two_turns(self):
        ports = FakePorts([pr(1)])
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual(rc, 0)
        path = str(pathlib.Path(self.root, "r-pr-1"))
        self.assertEqual(gitx.origin_repo(path), "o/r")
        self.assertEqual(ports.herdr.writes, [
            ("create_workspace", path, "r-pr-1"),
            ("run", "P0", "claude-a1"),
            ("prompt", "P0", "/catchup 1", True),
            ("prompt", "P0", "二手目", False),
        ])
        self.assertTrue(by_number(out)["#1"].endswith("sent"))

    def test_no_second_sends_only_catchup(self):
        ports = FakePorts([pr(1)])
        rc, out = run_main(["--config", self.cfg, "--no-second"], ports)
        self.assertEqual(rc, 0)
        self.assertEqual([w for w in ports.herdr.writes if w[0] == "prompt"], [("prompt", "P0", "/catchup 1", False)])
        self.assertTrue(by_number(out)["#1"].endswith("sent"))

    def test_pr_opens_only_the_named_prs_without_whose_turn(self):
        ports = FakePorts([pr(1), pr(2)])
        ports.fetch_prs = lambda repo: self.fail("--pr では whose-turn を呼ばない")
        ports.pr_info = lambda repo, n: pr(n)
        rc, out = run_main(["--config", self.cfg, "--pr", "5", "--dry-run"], ports)
        self.assertEqual(rc, 0)
        self.assertEqual(list(by_number(out)), ["#5"])

    def test_pr_that_cannot_be_read_stops_with_one_line(self):
        ports = FakePorts([])

        def no_pr(repo, n):
            raise ghx.GhError(f"#{n} を読めない")
        ports.pr_info = no_pr
        rc, out = run_main(["--config", self.cfg, "--pr", "99999"], ports)
        self.assertEqual(rc, 1)
        self.assertIn("止めた: #99999 を読めない", out)
        self.assertEqual(ports.herdr.writes, [])

    def test_one_launch_failure_does_not_stop_the_other(self):
        ports = FakePorts([pr(1), pr(2)], herdr=FakeHerdr(fail_run_for={"P0"}))
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual(rc, 0)
        lines = by_number(out)
        self.assertTrue(lines["#1"].endswith("launch_failed"))
        self.assertTrue(lines["#2"].endswith("sent"))
        self.assertIn(("prompt", "P1", "/catchup 2", True), ports.herdr.writes)


class Preflight(unittest.TestCase):
    def test_reports_missing_herdr_methods_command_attention_source_and_notes_limits(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        ports = dispatch.Ports(herdr_methods=lambda: {"pane.list"}, shell_has=lambda cmd: False, gh_ok=lambda repo, env=None: True)
        problems, notes = ports.preflight(cfg)
        text = "\n".join(problems)
        self.assertIn("agent.prompt", text)
        self.assertIn("claude-a1", text)
        self.assertIn("attention", text)
        self.assertNotIn("元の clone", text)  # 元の clone は o/r の clone なので通る
        self.assertIn("a1", "\n".join(notes))  # 控えが無いのは止めずに 1 行

    def test_single_account_user_is_checked_in_the_default_folder(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        home = pathlib.Path(root).parent / "home"
        (home / ".claude" / "plugins").mkdir(parents=True)
        (home / ".claude" / "plugins" / "installed_plugins.json").write_text(json.dumps({"plugins": {"attention@x": []}}))
        cfg = cfg._replace(accounts=(config.Account("default", "claude", None),))
        ports = dispatch.Ports(herdr_methods=lambda: dispatch.HERDR_METHODS, shell_has=lambda c: True, gh_ok=lambda repo, env=None: True,
                               env={"HOME": str(home)})
        problems, notes = ports.preflight(cfg)
        self.assertNotIn("attention", "\n".join(problems))
        self.assertNotIn("attention", "\n".join(notes))

    def test_repo_that_gh_cannot_read_is_a_problem(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        asked = []
        ports = dispatch.Ports(herdr_methods=lambda: dispatch.HERDR_METHODS, shell_has=lambda c: True,
                               gh_ok=lambda repo, env=None: asked.append(repo) or False)
        problems, _ = ports.preflight(cfg)
        self.assertEqual(asked, ["o/r"])
        self.assertIn("gh が o/r を読めない", "\n".join(problems))

    def test_gh_check_uses_the_repos_gh_user_token(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        cfg = cfg._replace(repos=(cfg.repos[0]._replace(gh_user="me-at-work"),))
        seen = []
        ports = dispatch.Ports(herdr_methods=lambda: dispatch.HERDR_METHODS, shell_has=lambda c: True,
                               gh_ok=lambda repo, env=None: seen.append(env) or True,
                               gh_env=lambda repo: {"GH_TOKEN": f"token-of-{repo.gh_user}"})
        problems, _ = ports.preflight(cfg)
        self.assertEqual(seen, [{"GH_TOKEN": "token-of-me-at-work"}])
        self.assertNotIn("gh", "\n".join(problems))

    def test_gh_user_without_a_token_is_a_problem(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})

        def no_token(repo):
            raise ghx.GhError("gh のアカウント me-at-work の鍵を取り出せない")
        ports = dispatch.Ports(herdr_methods=lambda: dispatch.HERDR_METHODS, shell_has=lambda c: True,
                               gh_ok=lambda repo, env=None: True, gh_env=no_token)
        problems, _ = ports.preflight(cfg)
        self.assertIn("gh のアカウント me-at-work の鍵を取り出せない", "\n".join(problems))

    def test_copy_files_are_looked_for_in_copy_from(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        empty = pathlib.Path(root).parent / "keep"
        empty.mkdir()
        cfg = cfg._replace(repos=(cfg.repos[0]._replace(copy_from=str(empty)),))
        ports = dispatch.Ports(herdr_methods=lambda: dispatch.HERDR_METHODS, shell_has=lambda c: True, gh_ok=lambda repo, env=None: True)
        _, notes = ports.preflight(cfg)
        self.assertIn(f"写すファイルが {empty} に無い: frontend/.env.local", "\n".join(notes))

    def test_source_of_another_repo_is_a_problem(self):
        cfg_path, root = make_cfg()
        cfg = config.load(cfg_path, env={})
        cfg = cfg._replace(repos=(cfg.repos[0]._replace(repo="o/other"),))
        ports = dispatch.Ports(herdr_methods=lambda: dispatch.HERDR_METHODS, shell_has=lambda c: True, gh_ok=lambda repo, env=None: True)
        problems, _ = ports.preflight(cfg)
        self.assertIn("元の clone", "\n".join(problems))


if __name__ == "__main__":
    unittest.main()
