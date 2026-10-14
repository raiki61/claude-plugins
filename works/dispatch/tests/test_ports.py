"""外への口（herdr・git・Claude Code）。本物の道具は呼ばず、偽物の runner が受けた argv と環境を見る。

herdr の出力の形は 2026-10-14 に手元の herdr 0.9.3 で読んだ実物（`pane list`・`workspace list`・`agent get`・`api schema --json`）に合わせた。
"""

import json
import os
import stat
import subprocess
import tempfile
import unittest

from . import DISPATCH  # noqa: F401
import claudex
import ghx
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

    def test_write_commands_accept_empty_output(self):
        # 2026-10-14 に手元の herdr 0.9.3 で見た実物: pane run と workspace close は、成功しても何も出さない
        herdr.run("wB:p1", "claude-x", runner=Fake((0, "", "")))
        herdr.close_workspace("wB", runner=Fake((0, "", "")))

    NOT_FOUND = (1, json.dumps({"id": "x", "error": {"code": "agent_not_found", "message": "agent target p not found"}}), "")

    @staticmethod
    def procs(shell_in_front):
        # 2026-10-14 に手元の herdr 0.9.3 で読んだ pane process-info の形。シェルが前に居れば前の組はシェルの pid
        return ok({"id": "x", "result": {"type": "pane_process_info", "process_info": {
            "pane_id": "p", "shell_pid": 10, "foreground_process_group_id": 10 if shell_in_front else 20,
            "foreground_processes": [{"pid": 10, "argv0": "bash"}] if shell_in_front else [{"pid": 21, "argv0": "claude"}]}}})

    IDLE = ok({"id": "x", "result": {"type": "agent_status", "agent": {"agent_status": "idle"}}})

    def test_wait_ready_waits_through_not_found_while_the_command_runs(self):
        # 起こした直後は herdr がまだ会話を見つけておらず、agent wait は待たずに agent_not_found を返す
        f = Fake(self.NOT_FOUND, self.procs(False), self.NOT_FOUND, self.procs(False), self.IDLE)
        self.assertEqual(herdr.wait_ready("p", runner=f, pause=lambda: None), "idle")
        self.assertEqual(f.calls[1][0], ["herdr", "pane", "process-info", "--pane", "p"])

    def test_wait_ready_also_waits_before_the_command_has_started(self):
        f = Fake(self.NOT_FOUND, self.procs(True), self.NOT_FOUND, self.procs(False), self.IDLE)
        self.assertEqual(herdr.wait_ready("p", runner=f, pause=lambda: None), "idle")

    def test_wait_ready_stops_when_the_command_ended_without_a_conversation(self):
        f = Fake(self.NOT_FOUND, self.procs(False), self.NOT_FOUND, self.procs(True))
        with self.assertRaises(herdr.HerdrError) as e:
            herdr.wait_ready("p", runner=f, pause=lambda: None)
        self.assertIn("会話が始まらなかった", str(e.exception))

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


class Gh(unittest.TestCase):
    def test_env_for_user_puts_that_accounts_token_in_a_copy(self):
        base = {"PATH": "/bin", "GH_TOKEN": "personal"}
        f = Fake((0, "work-token\n", ""))
        env = ghx.env_for("me-at-work", base, runner=f)
        self.assertEqual(f.calls[0][0], ["gh", "auth", "token", "--user", "me-at-work"])
        self.assertEqual(env["GH_TOKEN"], "work-token")
        self.assertEqual(env["PATH"], "/bin")
        self.assertEqual(base["GH_TOKEN"], "personal")

    def test_env_for_unknown_user_raises(self):
        with self.assertRaises(ghx.GhError) as e:
            ghx.env_for("nobody", {}, runner=Fake((1, "", "no account found for nobody")))
        self.assertIn("nobody", str(e.exception))

    def test_pr_info_reads_one_pr_in_the_shape_whose_turn_gives(self):
        f = Fake(ok({"number": 7, "title": "直す", "headRefName": "feat/7", "url": "u7"}))
        got = ghx.pr_info("o/r", 7, runner=f, env={"GH_TOKEN": "t"})
        self.assertEqual(got, {"number": 7, "title": "直す", "head": "feat/7", "url": "u7"})
        self.assertEqual(f.calls[0][0], ["gh", "pr", "view", "7", "--repo", "o/r", "--json", "number,title,headRefName,url"])
        self.assertEqual(f.calls[0][1], {"GH_TOKEN": "t"})

    def test_pr_info_unreadable_raises(self):
        with self.assertRaises(ghx.GhError) as e:
            ghx.pr_info("o/r", 99999, runner=Fake((1, "", "no pull requests found")))
        self.assertIn("#99999", str(e.exception))

    def test_pr_state_runs_with_the_given_env(self):
        f = Fake(ok({"state": "MERGED"}))
        self.assertEqual(ghx.pr_state("o/r", 7, runner=f, env={"GH_TOKEN": "t"}), "MERGED")
        self.assertEqual(f.calls[0][1], {"GH_TOKEN": "t"})


class Claude(unittest.TestCase):
    LISTED = [{"pid": 1, "cwd": "/r/work0", "kind": "interactive", "sessionId": "s1", "name": "n", "status": "idle"}]

    def test_sessions_sets_config_dir_expanded(self):
        f = Fake(ok(self.LISTED))
        self.assertEqual(claudex.sessions("~/acct", runner=f), self.LISTED)
        argv, env = f.calls[0]
        self.assertEqual(argv, ["claude", "agents", "--json"])
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], os.path.expanduser("~/acct"))

    def test_sessions_without_config_dir_keeps_the_users_own_setting(self):
        # アカウントを切り替えない人: 設定に config_dir を書かない。その人の CLAUDE_CONFIG_DIR（有れば）をそのまま使う
        f = Fake(ok([]))
        claudex.sessions(None, runner=f, base_env={"CLAUDE_CONFIG_DIR": "/x", "PATH": "/bin"})
        self.assertEqual(f.calls[0][1]["CLAUDE_CONFIG_DIR"], "/x")
        f = Fake(ok([]))
        claudex.sessions(None, runner=f, base_env={"PATH": "/bin"})
        self.assertNotIn("CLAUDE_CONFIG_DIR", f.calls[0][1])

    def test_trust_file_follows_where_claude_code_keeps_its_global_config(self):
        # 2026-10-14 に手元の 4 アカウントで見た実物: CLAUDE_CONFIG_DIR を入れて起こすアカウントは <そのフォルダ>/.claude.json、
        # 入れずに起こすアカウントは ~/.claude.json に、信頼したフォルダを記録している
        self.assertEqual(claudex.trust_file("/c/p2", {"HOME": "/h"}), "/c/p2/.claude.json")
        self.assertEqual(claudex.trust_file(None, {"HOME": "/h", "CLAUDE_CONFIG_DIR": "/x"}), "/x/.claude.json")
        self.assertEqual(claudex.trust_file(None, {"HOME": "/h"}), "/h/.claude.json")

    def trust_world(self, projects):
        d = tempfile.mkdtemp()
        f = os.path.join(d, ".claude.json")
        with open(f, "w") as fh:
            json.dump({"numStartups": 3, "projects": projects}, fh)
        os.chmod(f, 0o600)
        return f

    def test_clone_inherits_trust_from_a_trusted_source(self):
        f = self.trust_world({"/src/r": {"hasTrustDialogAccepted": True, "allowedTools": []},
                              "/src/r-pr-7": {"lastCost": 1}})
        self.assertEqual(claudex.inherit_trust(f, "/src/r", "/src/r-pr-7"), "inherited")
        got = json.load(open(f))
        self.assertEqual(got["projects"]["/src/r-pr-7"], {"lastCost": 1, "hasTrustDialogAccepted": True})
        self.assertEqual(got["numStartups"], 3)
        self.assertEqual(stat.S_IMODE(os.stat(f).st_mode), 0o600)

    def test_untrusted_source_writes_nothing(self):
        f = self.trust_world({"/src/r": {"hasTrustDialogAccepted": False}})
        before = open(f).read()
        self.assertEqual(claudex.inherit_trust(f, "/src/r", "/src/r-pr-7"), "source_untrusted")
        self.assertEqual(open(f).read(), before)

    def test_already_trusted_clone_writes_nothing(self):
        f = self.trust_world({"/src/r": {"hasTrustDialogAccepted": True},
                              "/src/r-pr-7": {"hasTrustDialogAccepted": True}})
        before = os.stat(f).st_mtime_ns
        self.assertEqual(claudex.inherit_trust(f, "/src/r", "/src/r-pr-7"), "already")
        self.assertEqual(os.stat(f).st_mtime_ns, before)

    def test_missing_or_broken_file_writes_nothing(self):
        d = tempfile.mkdtemp()
        self.assertEqual(claudex.inherit_trust(os.path.join(d, ".claude.json"), "/s", "/p"), "no_file")
        broken = os.path.join(d, "b.json")
        open(broken, "w").write("{not json")
        self.assertEqual(claudex.inherit_trust(broken, "/s", "/p"), "no_file")
        self.assertEqual(open(broken).read(), "{not json")

    def test_non_json_is_an_error(self):
        with self.assertRaises(claudex.ClaudeError):
            claudex.sessions(None, runner=Fake((0, "Failed to authenticate", "")))


if __name__ == "__main__":
    unittest.main()
