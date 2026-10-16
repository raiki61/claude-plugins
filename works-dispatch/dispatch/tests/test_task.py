"""作業役（入口の --task）。枝の場所は本物の git worktree（WorktreeHerdr）、herdr の会話の口・claude・gh は偽物で回す。"""

import os
import pathlib
import subprocess
import unittest

from . import DISPATCH  # noqa: F401
from .test_dispatch import FakePorts, gitx_source, make_cfg, run_main
from .test_provision import WorktreeHerdr, git, make_world
import gitx
from config import Repo
from nodes import provision


def two_accounts(cfg_path, task_cwd=None):
    """make_cfg の設定を、アカウント 2 つ（a1・a2）と、任意で作業役を起こすフォルダ（task_cwd）の形に書き直す。"""
    p = pathlib.Path(cfg_path)
    d = p.parent
    text = p.read_text(encoding="utf-8").replace(
        f"accounts = [{{ name = \"a1\", command = \"claude-a1\", config_dir = '{d}/c1' }}]",
        f"accounts = [{{ name = \"a1\", command = \"claude-a1\", config_dir = '{d}/c1' }},\n"
        f"            {{ name = \"a2\", command = \"claude-a2\", config_dir = '{d}/c2' }}]")
    if task_cwd:
        text += f"task_cwd = '{task_cwd}'\n"
    p.write_text(text, encoding="utf-8")
    return {"a1": f"{d}/c1", "a2": f"{d}/c2"}


def over(name):
    """その名のアカウントの週の使用率が上限を超えた控え。"""
    return {name: {"seven_day": {"used_percentage": 99, "resets_at": 10**10}, "five_hour": {"used_percentage": 1}}}


class Task(unittest.TestCase):
    def setUp(self):
        self.cfg, self.root = make_cfg()
        self.brief = str(pathlib.Path(self.root).parent / "brief.md")
        pathlib.Path(self.brief).write_text("頼み", encoding="utf-8")

    def ports(self, sessions=None, dirs=None):
        """sessions: 設定のフォルダ → そのアカウントの会話の並び。呼んだ会話の識別子は s-caller。"""
        ports = FakePorts([])
        ports.fetch_prs = lambda repo: self.fail("--task では whose-turn を呼ばない")
        ports.env = {"CLAUDE_CODE_SESSION_ID": "s-caller"}
        ports.list_sessions = lambda cdir: list((sessions or {}).get(cdir, []))
        return ports

    def run_task(self, ports, *extra, name="直し", branch="task/fix"):
        return run_main(["--config", self.cfg, "--task", name, "--branch", branch, "--brief", self.brief, *extra], ports)

    def sent(self, ports):
        return [w for w in ports.herdr.writes if w[0] == "prompt"]

    def test_creates_the_place_from_the_default_branch_names_the_pane_and_session_and_sends_the_brief(self):
        ports = self.ports()
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        self.assertTrue(ports.preflight_task)
        place = [w for w in ports.herdr.worktrees(gitx_source(self.cfg)) if w["linked"]]
        self.assertEqual([w["branch"] for w in place], ["task/fix"])
        path = place[0]["path"]
        # 作業場の名前は作業の名前。アカウントが 1 つなら、ペインの名前にアカウントを添えない。/catchup の窓を閉じる前置きも付けない
        self.assertEqual(ports.herdr.writes[:4], [
            ("create_worktree", "task/fix", "直し"),
            ("trust", "a1", gitx_source(self.cfg), path),
            ("rename_pane", "P0", "直し"),
            ("run", "P0", "claude-a1 --name '直し'" if os.name != "nt" else 'claude-a1 --name "直し"'),
        ])
        [(_, pane, text, wait)] = self.sent(ports)
        self.assertEqual((pane, wait), ("P0", True))
        self.assertTrue(text.startswith(f"作業の頼みです。{self.brief} を読んで、その通りに進めてください。"), text)
        self.assertNotIn("\n", text)
        self.assertIn("作業役 直し  task/fix  a1  sent", out)
        self.assertEqual(gitx.branch(gitx_source(self.cfg)), "main")

    def test_branch_on_origin_is_made_from_origin_not_the_default_branch(self):
        src = gitx_source(self.cfg)
        sha = git("-C", src, "-c", "user.name=o", "-c", "user.email=o@o", "commit-tree", "origin/main^{tree}", "-p", "origin/main",
                  "-m", "theirs")
        git("-C", src, "push", "-q", "origin", f"{sha}:refs/heads/task/old")
        ports = self.ports()
        rc, out = self.run_task(ports, branch="task/old")
        self.assertEqual(rc, 0, out)
        path = next(w["path"] for w in ports.herdr.worktrees(src) if w["branch"] == "task/old")
        self.assertEqual(gitx.head_sha(path), sha)

    def test_existing_place_is_opened_again_and_not_moved(self):
        src = gitx_source(self.cfg)
        elsewhere = str(pathlib.Path(self.root).parent / "hand-made")
        git("-C", src, "worktree", "add", "-q", "-b", "task/fix", elsewhere, "origin/main")
        ports = self.ports()
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        self.assertEqual(ports.herdr.writes[0][0], "open_worktree")
        self.assertIn("task/fix  a1  sent", out)

    def test_same_account_caller_gets_sendmessage_with_its_name(self):
        dirs = two_accounts(self.cfg)
        ports = self.ports({dirs["a1"]: [{"sessionId": "s-caller", "name": "窓口", "cwd": "/x"}]})
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        [(_, _, text, _)] = self.sent(ports)
        self.assertIn("SendMessage で「窓口」へ送る", text)
        # アカウントが 2 つ以上なら、ペインの名前にアカウントの名前を添える
        self.assertIn(("rename_pane", "P0", "直し a1"), ports.herdr.writes)

    def test_other_account_caller_gets_the_screen_route(self):
        dirs = two_accounts(self.cfg)
        ports = self.ports({dirs["a1"]: [{"sessionId": "s-caller", "name": "窓口", "cwd": "/x"}]})
        ports.limits_seq = [over("a1")]
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        self.assertIn("task/fix  a2  sent", out)
        [(_, _, text, _)] = self.sent(ports)
        self.assertIn("この画面に短く書いて止まる", text)
        self.assertIn("「窓口」とはアカウントが違い", text)
        self.assertNotIn("SendMessage で「", text)

    def test_unknown_caller_gets_the_screen_route_and_a_note(self):
        ports = self.ports()
        ports.env = {}
        rc, out = self.run_task(ports)
        [(_, _, text, _)] = self.sent(ports)
        self.assertIn("呼んだ会話が分からず", text)
        self.assertIn("--from-name と --from-account で渡す", out)

    def test_from_name_and_account_override_what_was_found(self):
        ports = self.ports()
        ports.env = {}
        rc, out = self.run_task(ports, "--from-name", "窓口", "--from-account", "a1")
        [(_, _, text, _)] = self.sent(ports)
        self.assertIn("SendMessage で「窓口」へ送る", text)

    def test_same_account_caller_without_a_name_gets_the_screen_route(self):
        ports = self.ports()
        ports.env = {}
        rc, out = self.run_task(ports, "--from-account", "a1")
        [(_, _, text, _)] = self.sent(ports)
        self.assertIn("呼んだ会話の名前が分からず", text)
        self.assertNotIn("アカウントが違い", text)

    def test_from_account_not_in_the_config_stops(self):
        ports = self.ports()
        rc, out = self.run_task(ports, "--from-account", "nobody")
        self.assertEqual(rc, 2)
        self.assertIn("--from-account の nobody が設定の accounts に無い", out)
        self.assertEqual(ports.herdr.writes, [])

    def test_task_cwd_starts_the_conversation_there_and_tells_where_the_place_is(self):
        launch_dir = str(pathlib.Path(self.root).parent / "notes-root")
        os.mkdir(launch_dir)
        two_accounts(self.cfg, task_cwd=launch_dir)
        ports = self.ports()
        ports.trusted_dirs = (launch_dir,)
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0, out)
        runs = [w for w in ports.herdr.writes if w[0] == "run"]
        self.assertEqual(len(runs), 2)
        self.assertTrue(runs[0][2].startswith("cd ") and launch_dir in runs[0][2], runs)
        self.assertTrue(runs[1][2].startswith("claude-a1 --name "), runs)
        # 作業場の外で起こすので、作業場への信頼の印は付けない
        self.assertFalse([w for w in ports.herdr.writes if w[0] == "trust"])
        path = next(w["path"] for w in ports.herdr.worktrees(gitx_source(self.cfg)) if w["linked"])
        [(_, _, text, _)] = self.sent(ports)
        self.assertIn(f"触る作業場（git worktree）は {path}（枝 task/fix）", text)
        self.assertNotIn("信頼していない", out)

    def test_untrusted_task_cwd_is_noted(self):
        launch_dir = str(pathlib.Path(self.root).parent / "notes-root")
        os.mkdir(launch_dir)
        two_accounts(self.cfg, task_cwd=launch_dir)
        rc, out = self.run_task(self.ports())
        self.assertIn(f"アカウント a1 は {launch_dir} を信頼していない", out)

    def test_dry_run_writes_nothing_and_shows_the_plan_and_the_first_text(self):
        ports = self.ports()
        rc, out = self.run_task(ports, "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertEqual(ports.herdr.writes, [])
        self.assertFalse(hasattr(ports, "refreshed"))
        self.assertIn("作業役 直し  task/fix  a1  create", out)
        self.assertIn("- 最初の文: 作業の頼みです。", out)

    def test_a_conversation_with_the_same_name_stops(self):
        dirs = {"a1": f"{pathlib.Path(self.cfg).parent}/c1"}
        ports = self.ports({dirs["a1"]: [{"sessionId": "s-other", "name": "直し", "cwd": "/x"}]})
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 1)
        self.assertIn("「直し」という名前の会話がもう開いている", out)
        self.assertEqual(ports.herdr.writes, [])

    def test_a_conversation_open_in_the_place_is_already_open(self):
        src = gitx_source(self.cfg)
        elsewhere = str(pathlib.Path(self.root).parent / "hand-made")
        git("-C", src, "worktree", "add", "-q", "-b", "task/fix", elsewhere, "origin/main")
        ports = self.ports({f"{pathlib.Path(self.cfg).parent}/c1": [{"sessionId": "s1", "name": "別", "cwd": elsewhere}]})
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 0)
        self.assertIn("already_open", out)
        self.assertEqual(ports.herdr.writes, [])

    def test_branch_open_in_the_source_clone_is_branch_busy(self):
        src = gitx_source(self.cfg)
        git("-C", src, "checkout", "-q", "-b", "task/fix")
        ports = self.ports()
        rc, out = self.run_task(ports)
        self.assertIn("task/fix  a1  branch_busy", out)
        self.assertFalse([w for w in ports.herdr.writes if w[0] in ("run", "prompt")])

    def test_missing_brief_stops_before_anything(self):
        ports = self.ports()
        rc, out = run_main(["--config", self.cfg, "--task", "直し", "--branch", "b", "--brief", "/nowhere/brief.md"], ports)
        self.assertEqual(rc, 2)
        self.assertIn("頼みのファイルが無い", out)
        self.assertEqual(ports.herdr.writes, [])

    def test_task_needs_branch_and_brief_and_takes_no_other_entry(self):
        for argv, said in ((["--task", "直し"], "--branch <枝> と --brief"),
                           (["--task", "直し", "--branch", "b", "--brief", "x", "--pr", "1"], "一緒に使えない"),
                           (["--branch", "b"], "--task と一緒にだけ使う")):
            with self.subTest(argv=argv):
                rc, out = run_main(["--config", self.cfg, *argv], self.ports())
                self.assertEqual(rc, 2)
                self.assertIn(said, out)

    def test_preflight_problem_stops(self):
        ports = FakePorts([], problems=["PATH の claude が会話に名前を付ける --name を持たない"])
        rc, out = self.run_task(ports)
        self.assertEqual(rc, 2)
        self.assertIn("--name を持たない", out)
        self.assertEqual(ports.herdr.writes, [])

    def test_repo_can_be_named_by_its_source_clone_path(self):
        ports = self.ports()
        rc, out = self.run_task(ports, "--repo", gitx_source(self.cfg), "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("作業役 直し", out)


class PrepareTask(unittest.TestCase):
    def setUp(self):
        self.src, self.root = make_world()
        self.repo = Repo("o/r", "second", self.src, ("frontend/.env.local",))

    def test_new_branch_is_made_from_the_default_branch_with_the_task_name_and_files_copied(self):
        h = WorktreeHerdr(self.root)
        got = provision.prepare_task({"head": "task/new", "label": "新しい作業"}, self.repo, "main", h, gitx)
        self.assertEqual(got["status"], "ready", got)
        self.assertEqual(h.writes, [("create_worktree", "task/new", "新しい作業")])
        self.assertEqual(gitx.branch(got["path"]), "task/new")
        self.assertEqual(gitx.head_sha(got["path"]), git("-C", self.src, "rev-parse", "origin/main"))
        self.assertEqual((pathlib.Path(got["path"]) / "frontend" / ".env.local").read_text(), "SECRET=1\n")

    def test_existing_local_branch_is_checked_out_as_it_is(self):
        git("-C", self.src, "branch", "task/mine", "origin/feat/1")
        h = WorktreeHerdr(self.root)
        got = provision.prepare_task({"head": "task/mine", "label": "x"}, self.repo, "main", h, gitx)
        self.assertEqual(got["status"], "ready", got)
        self.assertEqual(gitx.branch(got["path"]), "task/mine")

    def test_unreadable_origin_is_provision_failed(self):
        subprocess.run(["git", "-C", self.src, "remote", "set-url", "origin", "/nowhere/o/r.git"], check=True)
        got = provision.prepare_task({"head": "task/new", "label": "x"}, self.repo, "main", WorktreeHerdr(self.root), gitx)
        self.assertEqual(got["status"], "provision_failed")
        self.assertTrue(got["detail"])

    def test_no_branch_is_provision_failed(self):
        got = provision.prepare_task({"head": None, "label": "x"}, self.repo, "main", WorktreeHerdr(self.root), gitx)
        self.assertEqual((got["status"], got["detail"]), ("provision_failed", "枝が決まっていない"))


if __name__ == "__main__":
    unittest.main()
