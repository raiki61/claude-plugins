"""外への口（herdr・git・Claude Code）。本物の道具は呼ばず、偽物の runner が受けた argv と環境を見る。

herdr の出力の形は 2026-10-14 に手元の herdr 0.9.3 で読んだ実物（`pane list`・`workspace list`・`agent get`・`api schema --json`）と、
2026-10-15 に同じ版で一時の git リポジトリに打って読んだ `worktree list`・`create`・`open`・`remove` の実物に合わせた。
"""

import json
import os
import pathlib
import stat
import subprocess
import tempfile
import unittest
import unittest.mock

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
        self.assertEqual(herdr.prompt("wB:p1", "/attention:catchup 7", wait=True, runner=f), "idle")
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

    def test_rename_pane_passes_the_name_as_one_argv(self):
        f = Fake(ok({"id": "cli:pane:rename", "result": {"type": "pane_info", "pane": {"pane_id": "w1:p1", "label": "直し p2"}}}))
        herdr.rename_pane("w1:p1", "直し p2", runner=f)
        self.assertEqual(f.calls[0][0], ["herdr", "pane", "rename", "w1:p1", "直し p2"])

    def test_rename_pane_error_raises(self):
        with self.assertRaises(herdr.HerdrError):
            herdr.rename_pane("w1:p1", "x", runner=Fake((1, '{"error": {"code": "pane_not_found"}}', "")))

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

    def test_claude_integration_reads_the_claude_line_in_the_accounts_folder(self):
        # 2026-10-14 の herdr 0.9.3 の実物。CLAUDE_CONFIG_DIR に従って <cfg>/hooks/herdr-agent-state.sh を見る
        out = ("pi: not installed (/h/.pi/agent/extensions/herdr-agent-state.ts)\n"
               "claude: current (v10) (/h/.claude-w/hooks/herdr-agent-state.sh)\n"
               "codex: not installed (/h/.codex/herdr-agent-state.sh)\n")
        f = Fake((0, out, ""))
        self.assertEqual(herdr.claude_integration("/h/.claude-w", {"PATH": "/bin"}, runner=f), "current (v10)")
        argv, env = f.calls[0]
        self.assertEqual(argv, ["herdr", "integration", "status"])
        self.assertEqual(env, {"PATH": "/bin", "CLAUDE_CONFIG_DIR": "/h/.claude-w"})
        f = Fake((0, "claude: not installed (/h/.claude/hooks/herdr-agent-state.sh)\n", ""))
        self.assertEqual(herdr.claude_integration("/h/.claude", {}, runner=f), "not installed")
        with self.assertRaises(herdr.HerdrError):
            herdr.claude_integration("/h/.claude", {}, runner=Fake((0, "pi: current\n", "")))

    def test_report_activity_hands_off_the_sidebar_token(self):
        seen = []
        herdr.report_activity("w1:p1", "Read b.py", 3600000, spawn=seen.append)
        self.assertEqual(seen, [["herdr", "pane", "report-metadata", "w1:p1", "--source", "claude-activity",
                                 "--ttl-ms", "3600000", "--token", "act=Read b.py"]])

    def test_wait_ready_also_ends_on_a_confirmation_screen(self):
        # --until を付けない agent wait は idle・done・blocked のどれでも返る（herdr agent wait --help）
        f = Fake(ok({"id": "x", "result": {"type": "agent_waited", "agent": {"agent_status": "blocked"}}}))
        self.assertEqual(herdr.wait_ready("wB:p1", runner=f, pause=lambda: None), "blocked")
        self.assertEqual(f.calls[0][0], ["herdr", "agent", "wait", "wB:p1"])

    def test_methods_from_schema(self):
        schema = {"schemas": {"request": {"oneOf": [
            {"properties": {"method": {"const": "agent.prompt"}}},
            {"properties": {"method": {"const": "pane.run"}}}]}}}
        self.assertEqual(herdr.methods(runner=Fake(ok(schema))), {"agent.prompt", "pane.run"})


# 2026-10-15 に herdr 0.9.3 で読んだ実物の写し（パスとリポジトリの鍵だけを短くした。scroll と tab は中身を略した）
WT_CREATE = {"id": "cli:worktree:create", "result": {
    "root_pane": {"agent_status": "unknown", "cwd": "/h/.herdr/worktrees/repo/feat-a", "focused": False,
                  "foreground_cwd": "/h/.herdr/worktrees/repo/feat-a", "pane_id": "w1B:p1", "revision": 0, "scroll": {},
                  "tab_id": "w1B:t1", "terminal_id": "term_1", "workspace_id": "w1B"},
    "tab": {}, "type": "worktree_created",
    "workspace": {"active_tab_id": "w1B:t1", "agent_status": "unknown", "focused": False, "label": "repo/feat-a", "number": 20,
                  "pane_count": 1, "tab_count": 1, "workspace_id": "w1B",
                  "worktree": {"checkout_path": "/h/.herdr/worktrees/repo/feat-a", "is_linked_worktree": True,
                               "repo_key": "/s/repo/.git", "repo_name": "repo", "repo_root": "/s/repo"}},
    "worktree": {"branch": "feat-a", "is_bare": False, "is_detached": False, "is_linked_worktree": True, "is_prunable": False,
                 "label": "repo", "open_workspace_id": "w1B", "path": "/h/.herdr/worktrees/repo/feat-a"}}}
WT_OPEN = {"id": "cli:worktree:open", "result": {
    "already_open": False,
    "root_pane": {"agent_status": "unknown", "cwd": "/h/.herdr/worktrees/repo/feat-a", "pane_id": "w1F:p1", "workspace_id": "w1F"},
    "tab": {}, "type": "worktree_opened",
    "workspace": {"label": "repo/feat-a", "workspace_id": "w1F"},
    "worktree": {"branch": "feat-a", "is_bare": False, "is_detached": False, "is_linked_worktree": True, "is_prunable": False,
                 "label": "repo", "open_workspace_id": "w1F", "path": "/h/.herdr/worktrees/repo/feat-a"}}}
WT_LIST = {"id": "cli:worktree:list", "result": {
    "source": {"repo_key": "/s/repo/.git", "repo_name": "repo", "repo_root": "/s/repo", "source_checkout_path": "/s/repo",
               "source_workspace_id": "w1"},
    "type": "worktree_list",
    "worktrees": [
        {"branch": "main", "is_bare": False, "is_detached": False, "is_linked_worktree": False, "is_prunable": False,
         "label": "repo", "open_workspace_id": "w1", "path": "/s/repo"},
        {"branch": "feat-a", "is_bare": False, "is_detached": False, "is_linked_worktree": True, "is_prunable": False,
         "label": "repo", "path": "/h/.herdr/worktrees/repo/feat-a"}]}}
WT_REMOVE = {"id": "cli:worktree:remove", "result": {"forced": False, "path": "/h/.herdr/worktrees/repo/feat-a",
                                                     "type": "worktree_removed", "workspace_id": "w1F"}}
WT_DIRTY = (1, "", json.dumps({"error": {"code": "dirty_worktree_requires_force",
                                         "message": "fatal: '/h/.herdr/worktrees/repo/feat-a' contains modified or untracked files, "
                                                    "use --force to delete it"}, "id": "cli:worktree:remove"}))


class HerdrWorktree(unittest.TestCase):
    def test_list_reads_places_in_branch_words(self):
        f = Fake(ok(WT_LIST))
        self.assertEqual(herdr.worktrees("/s/repo", runner=f), [
            {"path": os.path.normpath("/s/repo"), "branch": "main", "linked": False, "workspace": "w1", "prunable": False},
            {"path": os.path.normpath("/h/.herdr/worktrees/repo/feat-a"), "branch": "feat-a", "linked": True, "workspace": None,
             "prunable": False}])
        self.assertEqual(f.calls[0][0], ["herdr", "worktree", "list", "--cwd", "/s/repo"])

    def test_paths_from_herdr_are_normalized_once_at_the_entry(self):
        # herdr は git と同じく `/` 区切りで返す。Windows では os.path.join のパスと字が食い違うので、入口で normpath にそろえる
        raw = "/h/.herdr/worktrees/repo/./feat-a/"
        got = {**WT_LIST, "result": {**WT_LIST["result"], "worktrees": [{**WT_LIST["result"]["worktrees"][1], "path": raw}]}}
        self.assertEqual(herdr.worktrees("/s/repo", runner=Fake(ok(got)))[0]["path"], os.path.normpath(raw))
        made = {**WT_CREATE, "result": {**WT_CREATE["result"], "worktree": {**WT_CREATE["result"]["worktree"], "path": raw}}}
        self.assertEqual(herdr.create_worktree("/s/repo", "feat-a", "origin/feat-a", "repo/feat-a", runner=Fake(ok(made)))["path"],
                         os.path.normpath(raw))
        gone = {**WT_REMOVE, "result": {**WT_REMOVE["result"], "path": raw}}
        self.assertEqual(herdr.remove_worktree("/s/repo", "/p", "repo/x", runner=Fake(ok(WT_OPEN), ok(gone)))["path"],
                         os.path.normpath(raw))

    def test_detached_checkout_has_no_branch(self):
        got = {**WT_LIST, "result": {**WT_LIST["result"], "worktrees": [
            {**WT_LIST["result"]["worktrees"][1], "branch": None, "is_detached": True}]}}
        self.assertIsNone(herdr.worktrees("/s/repo", runner=Fake(ok(got)))[0]["branch"])

    def test_create_passes_branch_base_label_without_focus_or_trust(self):
        f = Fake(ok(WT_CREATE))
        got = herdr.create_worktree("/s/repo", "feat-a", "origin/feat-a", "repo/feat-a", runner=f)
        # 場所のパスは入口で normpath にそろう（Windows では `\\` 区切りになる）
        self.assertEqual(got, {"path": os.path.normpath("/h/.herdr/worktrees/repo/feat-a"), "branch": "feat-a", "workspace_id": "w1B",
                               "pane_id": "w1B:p1"})
        self.assertEqual(f.calls[0][0], ["herdr", "worktree", "create", "--cwd", "/s/repo", "--branch", "feat-a",
                                         "--base", "origin/feat-a", "--label", "repo/feat-a", "--no-focus"])

    def test_open_names_the_source_and_the_path(self):
        # --path だけでは worktree_not_found になり、元の clone を --cwd で渡すと通った（2026-10-15 に 0.9.3 で見た）
        f = Fake(ok(WT_OPEN))
        got = herdr.open_worktree("/s/repo", "/h/.herdr/worktrees/repo/feat-a", "repo/feat-a", runner=f)
        self.assertEqual((got["workspace_id"], got["pane_id"]), ("w1F", "w1F:p1"))
        self.assertEqual(f.calls[0][0], ["herdr", "worktree", "open", "--cwd", "/s/repo", "--path",
                                         "/h/.herdr/worktrees/repo/feat-a", "--label", "repo/feat-a", "--no-focus"])

    def test_remove_opens_then_removes_by_workspace_without_force(self):
        f = Fake(ok(WT_OPEN), ok(WT_REMOVE))
        got = herdr.remove_worktree("/s/repo", "/h/.herdr/worktrees/repo/feat-a", "repo/feat-a", runner=f)
        self.assertEqual(got, {"path": os.path.normpath("/h/.herdr/worktrees/repo/feat-a"), "workspace_id": "w1F"})
        self.assertEqual(f.calls[1][0], ["herdr", "worktree", "remove", "--workspace", "w1F"])
        self.assertNotIn("--force", f.calls[1][0])

    def test_remove_of_a_dirty_place_raises_with_herdrs_code(self):
        with self.assertRaises(herdr.HerdrError) as e:
            herdr.remove_worktree("/s/repo", "/p", "repo/x", runner=Fake(ok(WT_OPEN), WT_DIRTY))
        self.assertEqual(e.exception.detail, "dirty_worktree_requires_force")

    def test_workspace_close_now_answers_ok(self):
        # 2026-10-15 の 0.9.3 では workspace close は {"result": {"type": "ok"}} を返した（10-14 は何も出さなかった）
        herdr.close_workspace("w1D", runner=Fake(ok({"id": "cli:workspace:close", "result": {"type": "ok"}})))


class Git(unittest.TestCase):
    def test_branch_and_detached(self):
        self.assertEqual(gitx.branch("/r", runner=Fake((0, "feat/7\n", ""))), "feat/7")
        self.assertIsNone(gitx.branch("/r", runner=Fake((0, "\n", ""))))
        self.assertIsNone(gitx.branch("/r", runner=Fake((128, "", "not a git repository"))))

    def test_is_clean_reads_porcelain_status(self):
        self.assertTrue(gitx.is_clean("/r", runner=Fake((0, "", ""))))
        self.assertFalse(gitx.is_clean("/r", runner=Fake((0, " M a.py\n", ""))))
        self.assertFalse(gitx.is_clean("/r", runner=Fake((0, "?? new.py\n", ""))))
        self.assertFalse(gitx.is_clean("/r", runner=Fake((128, "", "not a git repository"))))

    def test_origin_repo_forms(self):
        for url in ("git@github.com:o/r.git", "https://github.com/o/r", "https://github.com/o/r.git",
                    "ssh://git@github.com/o/r.git", "git@github.com-alias:o/r.git", "/tmp/o/r.git", "C:\\tmp\\o\\r.git"):
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
        f = Fake(ok({"number": 7, "title": "直す", "headRefName": "feat/7", "url": "u7", "state": "OPEN", "isCrossRepository": True}))
        got = ghx.pr_info("o/r", 7, runner=f, env={"GH_TOKEN": "t"})
        self.assertEqual(got, {"number": 7, "title": "直す", "head": "feat/7", "url": "u7", "state": "OPEN", "fork": True})
        self.assertEqual(f.calls[0][0], ["gh", "pr", "view", "7", "--repo", "o/r", "--json",
                                         "number,title,headRefName,url,state,isCrossRepository"])
        self.assertEqual(f.calls[0][1], {"GH_TOKEN": "t"})

    def test_pr_info_unreadable_raises(self):
        with self.assertRaises(ghx.GhError) as e:
            ghx.pr_info("o/r", 99999, runner=Fake((1, "", "no pull requests found")))
        self.assertIn("#99999", str(e.exception))

    def test_pr_for_branch_prefers_the_open_pr_of_this_repo(self):
        # 2026-10-15 に gh 2.102.0 で読んだ gh pr list --json の形（fork の PR は isCrossRepository が true）
        listed = [{"number": 9, "state": "OPEN", "headRefOid": "f" * 40, "isCrossRepository": True},
                  {"number": 8, "state": "MERGED", "headRefOid": "b" * 40, "isCrossRepository": False},
                  {"number": 7, "state": "OPEN", "headRefOid": "a" * 40, "isCrossRepository": False}]
        f = Fake(ok(listed))
        self.assertEqual(ghx.pr_for_branch("o/r", "feat/7", runner=f, env={"GH_TOKEN": "t"}),
                         {"number": 7, "state": "OPEN", "head_sha": "a" * 40})
        self.assertEqual(f.calls[0][0][:7], ["gh", "pr", "list", "--repo", "o/r", "--head", "feat/7"])
        self.assertEqual(f.calls[0][1], {"GH_TOKEN": "t"})
        self.assertEqual(ghx.pr_for_branch("o/r", "x", runner=Fake(ok(listed[:2])))["number"], 8)
        self.assertIsNone(ghx.pr_for_branch("o/r", "x", runner=Fake(ok([]))))
        with self.assertRaises(ghx.GhError):
            ghx.pr_for_branch("o/r", "x", runner=Fake((1, "", "HTTP 502")))

    def test_issue_branches_reads_one_branch_per_line(self):
        f = Fake((0, "12-fix-login\thttps://github.com/o/r/tree/12-fix-login\nmore\thttps://github.com/o/r/tree/more\n", ""))
        self.assertEqual(ghx.issue_branches("o/r", 12, runner=f), ["12-fix-login", "more"])
        self.assertEqual(f.calls[0][0], ["gh", "issue", "develop", "--list", "12", "--repo", "o/r"])
        self.assertEqual(ghx.issue_branches("o/r", 12, runner=Fake((0, "BRANCH  URL\nx  u\n", ""))), ["x"])
        self.assertEqual(ghx.issue_branches("o/r", 12, runner=Fake((0, "", ""))), [])

    def test_issue_develop_makes_the_branch_from_the_base_with_the_given_env(self):
        f = Fake((0, "github.com/o/r/tree/12-fix-login\n", ""))
        ghx.issue_develop("o/r", 12, "main", runner=f, env={"GH_TOKEN": "t"})
        self.assertEqual(f.calls[0], (["gh", "issue", "develop", "12", "--repo", "o/r", "--base", "main"], {"GH_TOKEN": "t"}))
        with self.assertRaises(ghx.GhError):
            ghx.issue_develop("o/r", 12, "main", runner=Fake((1, "", "not permitted")))

    def test_issue_info_keeps_only_closing_prs_of_this_repo(self):
        # 2026-10-15 に gh 2.102.0 で cli/cli の issue を読んだ closedByPullRequestsReferences の形
        ref = lambda n, owner, name: {"id": "PR_x", "number": n, "url": f"u{n}",
                                      "repository": {"id": "R", "name": name, "owner": {"id": "O", "login": owner}}}
        f = Fake(ok({"number": 12, "title": "直す", "url": "i12", "state": "OPEN",
                     "closedByPullRequestsReferences": [ref(3, "o", "r"), ref(4, "x", "r")]}))
        self.assertEqual(ghx.issue_info("o/r", 12, runner=f),
                         {"number": 12, "title": "直す", "url": "i12", "state": "OPEN", "prs": [3]})

    def test_default_branch(self):
        f = Fake((0, "main\n", ""))
        self.assertEqual(ghx.default_branch("o/r", runner=f), "main")
        self.assertEqual(f.calls[0][0][:4], ["gh", "repo", "view", "o/r"])


class GitWorktree(unittest.TestCase):
    """fetch・早送り・手元の枝を消す、を本物の git で。"""

    def setUp(self):
        from .test_provision import git, make_world
        self.git = git
        self.src, root = make_world()
        self.path = os.path.join(root, "feat-1")
        git("-C", self.src, "worktree", "add", "-q", "-b", "feat/1", self.path, "origin/feat/1")

    def test_fetch_of_a_branch_missing_on_origin_raises(self):
        with self.assertRaises(gitx.GitError):
            gitx.fetch(self.src, "nowhere")

    def test_fast_forward_moves_only_when_behind(self):
        from .test_provision import advance
        self.assertEqual(gitx.fast_forward(self.path, "feat/1"), "current")
        theirs = advance(self.src, "feat/1")
        self.assertEqual(gitx.fast_forward(self.path, "feat/1"), "updated")
        self.assertEqual(gitx.head_sha(self.path), theirs)
        self.git("-C", self.path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "mine")
        mine = gitx.head_sha(self.path)
        advance(self.src, "feat/1")
        self.assertEqual(gitx.fast_forward(self.path, "feat/1"), "local_only")
        self.assertEqual(gitx.head_sha(self.path), mine)

    def test_reset_keep_follows_a_force_push_but_keeps_uncommitted_changes(self):
        old = gitx.head_sha(self.path)
        rewritten = self.git("-C", self.src, "-c", "user.name=o", "-c", "user.email=o@o", "commit-tree", f"{old}^{{tree}}",
                             "-m", "rewritten")
        self.git("-C", self.src, "push", "-q", "--force", "origin", f"{rewritten}:refs/heads/feat/1")
        gitx.fetch(self.src, "feat/1")
        self.assertEqual(gitx.fast_forward(self.path, "feat/1"), "local_only")
        gitx.reset_keep(self.path, "feat/1")
        self.assertEqual(gitx.head_sha(self.path), rewritten)

    def test_is_main_worktree(self):
        self.assertTrue(gitx.is_main_worktree(self.src))
        self.assertFalse(gitx.is_main_worktree(self.path))
        self.assertIsNone(gitx.is_main_worktree(tempfile.mkdtemp()))

    def test_delete_branch_only_when_the_tip_is_the_expected_one(self):
        sha = gitx.head_sha(self.path)
        with self.assertRaises(gitx.GitError):   # どこかの worktree が開いている枝は git が断る
            gitx.delete_branch(self.src, "feat/1", sha)
        self.git("-C", self.src, "worktree", "remove", self.path)
        self.assertEqual(gitx.delete_branch(self.src, "feat/1", "b" * 40), "moved")
        self.assertEqual(gitx.delete_branch(self.src, "feat/1", sha), "deleted")
        self.assertEqual(gitx.delete_branch(self.src, "feat/1", sha), "absent")


class GitIgnored(unittest.TestCase):
    def test_ignored_files_lists_files_and_skips_whole_ignored_folders(self):
        from .test_provision import make_world
        src, _ = make_world()
        (pathlib.Path(src) / "node_modules" / "x").mkdir(parents=True)
        (pathlib.Path(src) / "node_modules" / "x" / "a.js").write_text("")
        (pathlib.Path(src) / ".gitignore").write_text("frontend/.env.local\nnode_modules/\n")
        self.assertEqual(gitx.ignored_files(src), ["frontend/.env.local"])


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
        self.assertEqual(claudex.trust_file("/c/p2", {"HOME": "/h"}), os.path.join("/c/p2", ".claude.json"))
        self.assertEqual(claudex.trust_file(None, {"HOME": "/h", "CLAUDE_CONFIG_DIR": "/x"}), os.path.join("/x", ".claude.json"))
        self.assertEqual(claudex.trust_file(None, {"HOME": "/h"}), os.path.join("/h", ".claude.json"))

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
        if os.name != "nt":  # Windows のファイルには POSIX の権限のビットが無い（読み取り専用かどうかだけ）
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

    @staticmethod
    def plugins(entries):
        """entries: [(キー, scope, plugin.json の名前, catchup を持つか)]。アカウントの設定のフォルダを返す。"""
        d = pathlib.Path(tempfile.mkdtemp())
        record = {}
        for key, scope, name, has in entries:
            path = d / "plugins" / "cache" / key / "1.0.0"
            (path / ".claude-plugin").mkdir(parents=True)
            (path / ".claude-plugin" / "plugin.json").write_text(json.dumps({"name": name}))
            if has:
                (path / "commands").mkdir()
                (path / "commands" / "catchup.md").write_text("---\n---\n")
            record.setdefault(key, []).append({"scope": scope, "installPath": str(path)})
        (d / "plugins" / "installed_plugins.json").write_text(json.dumps({"version": 2, "plugins": record}))
        return str(d)

    def test_catchup_command_is_named_after_the_plugin_that_ships_it(self):
        d = self.plugins([("attention@m", "user", "attention", True), ("works@m", "user", "works", False)])
        self.assertEqual(claudex.catchup_commands(d), ["/attention:catchup"])

    def test_catchup_command_follows_a_renamed_plugin(self):
        self.assertEqual(claudex.catchup_commands(self.plugins([("watch@m", "user", "watch", True)])), ["/watch:catchup"])

    def test_catchup_command_expands_home(self):
        d = self.plugins([("attention@m", "user", "attention", True)])
        home, rest = os.path.split(d)
        # ~ を広げる元は、Windows では USERPROFILE、ほかでは HOME
        with unittest.mock.patch.dict(os.environ, {"HOME": home, "USERPROFILE": home}):
            self.assertEqual(claudex.catchup_commands(f"~/{rest}"), ["/attention:catchup"])

    def test_project_scoped_plugins_do_not_count(self):
        # project の入れ方は、その projectPath の中で起こした会話にしか効かない
        self.assertEqual(claudex.catchup_commands(self.plugins([("attention@m", "project", "attention", True)])), [])

    def test_no_plugins_record_means_no_command(self):
        self.assertEqual(claudex.catchup_commands(tempfile.mkdtemp()), [])

    def test_non_json_is_an_error(self):
        with self.assertRaises(claudex.ClaudeError):
            claudex.sessions(None, runner=Fake((0, "Failed to authenticate", "")))


if __name__ == "__main__":
    unittest.main()


class ClaudeName(unittest.TestCase):
    def test_missing_flags_are_read_from_help(self):
        f = Fake((0, "  --bg, --background   Start in the background\n  -n, --name <name>\n", ""))
        self.assertEqual(claudex.missing_flags(runner=f), ["--settings"])
        self.assertEqual(f.calls[0][0], ["claude", "--help"])
        self.assertEqual(claudex.missing_flags(runner=Fake((1, "--name --bg --settings", ""))), list(claudex.TASK_FLAGS))

    def test_all_flags_are_missing_when_claude_cannot_start(self):
        def missing(argv, env=None):
            raise FileNotFoundError(argv[0])
        self.assertEqual(claudex.missing_flags(runner=missing), list(claudex.TASK_FLAGS))

    def test_sessions_with_done_ones_add_all(self):
        f = Fake((0, "[]", ""))
        claudex.sessions("/c1", runner=f, base_env={}, include_done=True)
        self.assertEqual(f.calls[0][0], ["claude", "agents", "--json", "--all"])
        self.assertEqual(f.calls[0][1]["CLAUDE_CONFIG_DIR"], "/c1")

    def test_remove_session_runs_rm_in_the_account_folder_and_says_why_it_kept(self):
        f = Fake((1, "kept 82fbd328 — its worktree is still at x\n", ""))
        self.assertEqual(claudex.remove_session("/c1", "82fbd328", runner=f, base_env={}),
                         (False, "kept 82fbd328 — its worktree is still at x"))
        self.assertEqual(f.calls[0][0], ["claude", "rm", "82fbd328"])
        self.assertEqual(f.calls[0][1]["CLAUDE_CONFIG_DIR"], "/c1")
        self.assertTrue(claudex.remove_session(None, "x", runner=Fake((0, "removed x", "")), base_env={})[0])

    def test_caller_is_the_account_whose_listing_has_the_session(self):
        listed = {"a1": [{"sessionId": "s1", "name": "x"}], "a2": [{"sessionId": "s2", "name": "窓口"}]}
        self.assertEqual(claudex.caller(listed, "s2"), ("a2", "窓口"))
        self.assertEqual(claudex.caller(listed, "s9"), (None, None))
        self.assertEqual(claudex.caller(listed, None), (None, None))
