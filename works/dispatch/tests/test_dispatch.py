"""report ノードと入口（dispatch.py）。外への口を全部偽物にして、流れを回す。"""

import contextlib
import io
import json
import pathlib
import subprocess
import tempfile
import unittest

from . import DISPATCH  # noqa: F401
import config
import dispatch
import herdr as real_herdr
from nodes import prs as prs_node
from nodes import report


class Report(unittest.TestCase):
    def test_no_prs_is_one_line(self):
        self.assertEqual(report.lines([], {}, []), ["自分の番の PR は無い"])

    def test_notes_come_first_and_one_line_per_pr(self):
        plan = [{"number": 7, "title": "直す", "outcome": "assigned", "slot": {"workspace": "work8"}, "account": {"name": "p1"}},
                {"number": 9, "title": "見る", "outcome": "no_slot", "slot": None, "account": None}]
        got = report.lines(plan, {7: "sent"}, ["使用率の控えが無い: p3"])
        self.assertEqual(got[0], "使用率の控えが無い: p3")
        self.assertEqual(len(got), 3)
        self.assertIn("#7", got[1])
        self.assertIn("work8", got[1])
        self.assertIn("p1", got[1])
        self.assertTrue(got[1].endswith("sent"))
        self.assertTrue(got[2].endswith("no_slot"))


class Prs(unittest.TestCase):
    def test_fetch_runs_vendored_whose_turn_with_json(self):
        calls = []

        def runner(argv, env=None):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, json.dumps({"schema": 1, "prs": [{"number": 1}]}), "")

        self.assertEqual(prs_node.fetch("o/r", runner=runner), [{"number": 1}])
        self.assertTrue(calls[0][1].endswith("vendor/whose-turn.py"))
        self.assertEqual(calls[0][2:], ["--repo", "o/r", "--json"])

    def test_fetch_failure_raises(self):
        def runner(argv, env=None):
            return subprocess.CompletedProcess(argv, 1, "", "gh: not logged in")

        with self.assertRaises(prs_node.PrsError) as e:
            prs_node.fetch("o/r", runner=runner)
        self.assertIn("not logged in", str(e.exception))


def make_cfg(d):
    p = pathlib.Path(d)
    (p / "second.md").write_text("二手目", encoding="utf-8")
    (p / "c.toml").write_text(f"""
limits_dir = "{d}/limits"
accounts = [{{ name = "a1", command = "claude-a1", config_dir = "{d}/c1" }}]
[[repos]]
repo = "o/r"
second_prompt_file = "{d}/second.md"
slots = [{{ workspace = "w0", path = "{d}/w0" }}, {{ workspace = "w1", path = "{d}/w1" }}]
""", encoding="utf-8")
    return str(p / "c.toml")


class FakePorts:
    """dispatch.Ports と同じ名前の口を持つ偽物。"""

    def __init__(self, d, prs, problems=(), launch_fail=()):
        self.d = d
        self._prs = prs
        self._problems = list(problems)
        self._launch_fail = set(launch_fail)
        self.writes = []

    # 読む口
    def preflight(self, cfg):
        return list(self._problems), []

    def fetch_prs(self, repo):
        return self._prs

    def list_sessions(self, config_dir):
        return []

    def branch(self, cwd):
        return None

    def origin(self, cwd):
        return None

    def is_clean(self, cwd):
        return True

    def panes(self):
        return [{"pane_id": "P0", "workspace_id": "W0", "cwd": f"{self.d}/w0", "agent": None},
                {"pane_id": "P1", "workspace_id": "W1", "cwd": f"{self.d}/w1", "agent": None}]

    def labels(self):
        return {"W0": "w0", "W1": "w1"}

    def read_limits(self, limits_dir, names):
        return {n: None for n in names}

    def now(self):
        return 0

    # 書く口（herdr の形）。dispatch は ports.herdr を launch と turn に渡す
    @property
    def herdr(self):
        return self

    HerdrError = real_herdr.HerdrError

    def run(self, pane, command):
        self.writes.append(("run", pane, command))
        if pane in self._launch_fail:
            raise real_herdr.HerdrError(["herdr", "pane", "run"], "pane_not_found")

    def wait_ready(self, pane):
        return "idle"

    def agent(self, pane):
        return {"agent": "claude", "agent_status": "idle"}

    def prompt(self, target, text, wait):
        self.writes.append(("prompt", target, text, wait))
        return "idle" if wait else "sent"


def pr(n):
    return {"number": n, "title": f"t{n}", "head": f"feat/{n}", "url": f"u{n}", "role": "implementer", "days": 0}


def run_main(argv, ports):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = dispatch.main(argv, ports=ports)
    return rc, buf.getvalue()


class Main(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.cfg = make_cfg(self.d)

    def test_dry_run_writes_nothing(self):
        ports = FakePorts(self.d, [pr(1), pr(2)])
        rc, out = run_main(["--config", self.cfg, "--dry-run"], ports)
        self.assertEqual(rc, 0)
        self.assertEqual(ports.writes, [])
        self.assertIn("#1", out)
        self.assertIn("w0", out)

    def test_preflight_problem_stops_before_anything(self):
        ports = FakePorts(self.d, [pr(1)], problems=["herdr に届かない"])
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual(rc, 2)
        self.assertEqual(ports.writes, [])
        self.assertIn("herdr に届かない", out)

    def test_no_prs_does_nothing(self):
        ports = FakePorts(self.d, [])
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual((rc, ports.writes), (0, []))
        self.assertIn("自分の番の PR は無い", out)

    def test_one_launch_failure_does_not_stop_the_other(self):
        ports = FakePorts(self.d, [pr(1), pr(2)], launch_fail={"P0"})
        rc, out = run_main(["--config", self.cfg], ports)
        self.assertEqual(rc, 0)
        lines = {l.split()[0]: l for l in out.splitlines() if l.startswith("#")}
        self.assertTrue(lines["#1"].endswith("launch_failed"))
        self.assertTrue(lines["#2"].endswith("sent"))
        self.assertIn(("prompt", "P1", "/catchup 2", True), ports.writes)
        self.assertIn(("prompt", "P1", "二手目", False), ports.writes)
        self.assertIn(("run", "P1", "claude-a1"), ports.writes)


class Preflight(unittest.TestCase):
    def test_reports_missing_herdr_methods_command_attention_and_limits(self):
        d = tempfile.mkdtemp()
        cfg = config.load(make_cfg(d), env={})
        ports = dispatch.Ports(
            herdr_methods=lambda: {"pane.list"},
            shell_has=lambda cmd: False,
            gh_ok=lambda: True,
        )
        problems, notes = ports.preflight(cfg)
        text = "\n".join(problems)
        self.assertIn("agent.prompt", text)
        self.assertIn("claude-a1", text)
        self.assertIn("attention", text)
        self.assertIn("a1", "\n".join(notes))  # 控えが無いのは止めずに 1 行


if __name__ == "__main__":
    unittest.main()
