"""外への口（herdr・git・Claude Code）。本物の道具は呼ばず、偽物の runner が受けた argv と環境を見る。

herdr の出力の形は 2026-10-14 に手元の herdr 0.9.3 で読んだ実物（`pane list`・`workspace list`・`agent get`・`api schema --json`）に合わせた。
"""

import json
import os
import subprocess
import unittest

from . import DISPATCH  # noqa: F401
import claudex
import gitx
import herdr


class Fake:
    """呼ばれた argv と env を控え、決めた出力を返す runner。"""

    def __init__(self, *outs):
        self.outs = list(outs)
        self.calls = []

    def __call__(self, argv, env=None):
        self.calls.append((list(argv), env))
        rc, out, err = self.outs.pop(0) if self.outs else (0, "", "")
        return subprocess.CompletedProcess(argv, rc, out, err)


def ok(obj):
    return (0, json.dumps(obj), "")


PANES = {"id": "cli:pane:list", "result": {"type": "pane_list", "panes": [
    {"pane_id": "wW:p1", "workspace_id": "wW", "cwd": "/r/work0", "agent": "claude", "agent_status": "working"},
    {"pane_id": "wB:p1", "workspace_id": "wB", "cwd": "/r/work8", "agent_status": "unknown"},
]}}
WORKSPACES = {"id": "cli:workspace:list", "result": {"type": "workspace_list", "workspaces": [
    {"workspace_id": "wW", "label": "work0"}, {"workspace_id": "wB", "label": "work8"}]}}


class Herdr(unittest.TestCase):
    def test_panes_fills_missing_agent_with_none(self):
        got = herdr.panes(runner=Fake(ok(PANES)))
        self.assertEqual(got[1]["agent"], None)
        self.assertEqual(got[0]["agent"], "claude")

    def test_workspace_labels(self):
        self.assertEqual(herdr.workspace_labels(runner=Fake(ok(WORKSPACES))), {"wW": "work0", "wB": "work8"})

    def test_prompt_passes_text_as_one_argv_untouched(self):
        text = "a 'b' \"c\"\n2. $HOME `x`"
        f = Fake(ok({"id": "x", "result": {"type": "agent_prompted", "agent": {"agent_status": "working"}}}))
        self.assertEqual(herdr.prompt("wB:p1", text, wait=False, runner=f), "sent")
        argv = f.calls[0][0]
        self.assertEqual(argv[:4], ["herdr", "agent", "prompt", "wB:p1"])
        self.assertEqual(argv[4], text)
        self.assertNotIn("--wait", argv)

    def test_prompt_wait_returns_final_status(self):
        f = Fake(ok({"id": "x", "result": {"type": "agent_prompted", "agent": {"agent_status": "idle"}}}))
        self.assertEqual(herdr.prompt("wB:p1", "/catchup 7", wait=True, runner=f), "idle")
        self.assertIn("--wait", f.calls[0][0])

    def test_prompt_stalled_is_a_status_not_an_error(self):
        err = json.dumps({"id": "x", "error": {"code": "agent_prompt_stalled", "message": "no working state"}})
        for out, stderr in ((err, ""), ("", err)):
            with self.subTest(stream="stdout" if out else "stderr"):
                self.assertEqual(herdr.prompt("p", "t", wait=True, runner=Fake((1, out, stderr))), "stalled")

    def test_other_errors_raise(self):
        err = json.dumps({"id": "x", "error": {"code": "pane_not_found", "message": "gone"}})
        with self.assertRaises(herdr.HerdrError) as e:
            herdr.prompt("p", "t", wait=True, runner=Fake((1, err, "")))
        self.assertIn("pane_not_found", str(e.exception))

    def test_run_sends_command_line(self):
        f = Fake(ok({"id": "x", "result": {}}))
        herdr.run("wB:p1", "claude-x", runner=f)
        self.assertEqual(f.calls[0][0], ["herdr", "pane", "run", "wB:p1", "claude-x"])

    def test_agent_reads_one_pane(self):
        f = Fake(ok({"id": "x", "result": {"type": "agent_info", "agent": {"agent": "claude", "agent_status": "idle"}}}))
        self.assertEqual(herdr.agent("wB:p1", runner=f)["agent"], "claude")
        self.assertEqual(f.calls[0][0], ["herdr", "agent", "get", "wB:p1"])

    def test_methods_from_schema(self):
        schema = {"schemas": {"request": {"oneOf": [
            {"properties": {"method": {"const": "agent.prompt"}}},
            {"properties": {"method": {"const": "pane.run"}}}]}}}
        self.assertEqual(herdr.methods(runner=Fake(ok(schema))), {"agent.prompt", "pane.run"})


class Git(unittest.TestCase):
    def test_branch_and_detached(self):
        self.assertEqual(gitx.branch("/r", runner=Fake((0, "feat/7\n", ""))), "feat/7")
        self.assertIsNone(gitx.branch("/r", runner=Fake((0, "\n", ""))))
        self.assertIsNone(gitx.branch("/r", runner=Fake((128, "", "not a git repository"))))

    def test_is_clean_ignores_untracked(self):
        f = Fake((0, "", ""))
        self.assertTrue(gitx.is_clean("/r", runner=f))
        self.assertIn("--untracked-files=no", f.calls[0][0])
        self.assertFalse(gitx.is_clean("/r", runner=Fake((0, " M a.py\n", ""))))

    def test_origin_repo_forms(self):
        for url in ("git@github.com:o/r.git", "https://github.com/o/r", "https://github.com/o/r.git",
                    "ssh://git@github.com/o/r.git", "git@github.com-alias:o/r.git"):
            with self.subTest(url=url):
                self.assertEqual(gitx.origin_repo("/r", runner=Fake((0, url + "\n", ""))), "o/r")
        self.assertIsNone(gitx.origin_repo("/r", runner=Fake((2, "", "no remote"))))


class Claude(unittest.TestCase):
    LISTED = [{"pid": 1, "cwd": "/r/work0", "kind": "interactive", "sessionId": "s1", "name": "n", "status": "idle"}]

    def test_sessions_sets_config_dir_expanded(self):
        f = Fake(ok(self.LISTED))
        self.assertEqual(claudex.sessions("~/acct", runner=f), self.LISTED)
        argv, env = f.calls[0]
        self.assertEqual(argv, ["claude", "agents", "--json"])
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], os.path.expanduser("~/acct"))

    def test_sessions_without_config_dir_drops_inherited_one(self):
        f = Fake(ok([]))
        claudex.sessions(None, runner=f, base_env={"CLAUDE_CONFIG_DIR": "/x", "PATH": "/bin"})
        env = f.calls[0][1]
        self.assertNotIn("CLAUDE_CONFIG_DIR", env)
        self.assertEqual(env["PATH"], "/bin")

    def test_non_json_is_an_error(self):
        with self.assertRaises(claudex.ClaudeError):
            claudex.sessions(None, runner=Fake((0, "Failed to authenticate", "")))


if __name__ == "__main__":
    unittest.main()
