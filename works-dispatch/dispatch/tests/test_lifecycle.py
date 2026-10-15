"""PR ごとの場所の一生を 1 つのコマンドで回す（設計書 2 節の 3・3 節の片付け）。
- 自分が作者でレビュアーの付いていない PR は、一覧からは開かない（--pr で指せば開く）
- 会話の開いている PR は、自分以外の動きが前に送った時より後に有り、会話が手すきで手元の作業も無ければ、会話を終えてペインを畳み、
  同じ場所（checkout）に新しい作業場と会話を立てて /catchup から送り直す
- 閉じた PR の枝の場所は、会話が手すきで手元の作業も無ければ会話を終えて消す。元の clone の linked worktree だけを見る
- 1 ターン目の終わりは Claude Code 自身の状態で見る（herdr の画面の見立てだけに頼らない）
"""

import contextlib
import io
import json
import pathlib
import subprocess
import unittest

from . import DISPATCH  # noqa: F401
from .test_dispatch import FakeHerdr, FakePorts, gitx_source, make_cfg, pr
from .test_launch_turn import CATCHUP, SECOND
from .test_launch_turn import FakeHerdr as TurnHerdr
from .test_provision import git, make_world
import dispatch
import ghx
import gitx
from nodes import fresh, turn


def session(status="idle", started=100.0):
    return {"status": status, "started": started}


class Decide(unittest.TestCase):
    def test_news_after_the_last_send_refreshes(self):
        self.assertEqual(fresh.decide(session(), {"last_other": 300.0}, 200.0, True, False), "refresh")

    def test_no_news_since_the_later_of_send_and_start_keeps_the_session(self):
        self.assertEqual(fresh.decide(session(started=400.0), {"last_other": 300.0}, 200.0, True, False), "no_news")
        self.assertEqual(fresh.decide(session(), {"last_other": 150.0}, 200.0, True, False), "no_news")
        self.assertEqual(fresh.decide(session(), {"last_other": None}, None, True, False), "no_news")

    def test_busy_or_local_work_is_never_refreshed(self):
        news = {"last_other": 999.0}
        self.assertEqual(fresh.decide(session("busy"), news, None, True, False), "busy")
        self.assertEqual(fresh.decide(session(), news, None, False, False), "dirty")
        self.assertEqual(fresh.decide(session(), news, None, True, True), "unpushed")

    def test_own_pr_without_reviewers_is_held(self):
        self.assertTrue(fresh.own_unreviewed({"role": "implementer"}, {"reviewers": False}))
        self.assertFalse(fresh.own_unreviewed({"role": "implementer"}, {"reviewers": True}))
        self.assertFalse(fresh.own_unreviewed({"role": "reviewer"}, {"reviewers": False}))


class Activity(unittest.TestCase):
    def run_with(self, pull):
        def runner(argv, env=None):
            return subprocess.CompletedProcess(argv, 0, json.dumps({"data": {"repository": {"pullRequest": pull}}}), "")
        return ghx.pr_activity("o/r", 1, "me", runner=runner)

    def test_bots_are_neither_reviewers_nor_news(self):
        got = self.run_with({
            "author": {"login": "me"},
            "reviewRequests": {"nodes": [{"requestedReviewer": {"__typename": "Bot"}}]},
            "reviews": {"nodes": [{"author": {"__typename": "Bot", "login": "copilot-pull-request-reviewer"},
                                   "submittedAt": "2026-10-15T01:00:00Z"}]},
            "comments": {"nodes": [{"author": {"__typename": "Bot", "login": "ci"}, "createdAt": "2026-10-15T02:00:00Z"}]},
            "commits": {"nodes": []}})
        self.assertEqual(got, {"reviewers": False, "last_other": None})

    def test_people_count_and_my_own_moves_do_not(self):
        got = self.run_with({
            "author": {"login": "me"},
            "reviewRequests": {"nodes": []},
            "reviews": {"nodes": [{"author": {"__typename": "User", "login": "ann"}, "submittedAt": "2026-10-15T01:00:00Z"},
                                  {"author": {"__typename": "User", "login": "me"}, "submittedAt": "2026-10-15T05:00:00Z"}]},
            "comments": {"nodes": []},
            "commits": {"nodes": [{"commit": {"committedDate": "2026-10-15T06:00:00Z",
                                              "authors": {"nodes": [{"user": {"login": "me"}}]}}}]}})
        self.assertTrue(got["reviewers"])
        self.assertEqual(got["last_other"], 1792026000.0)

    def test_a_pending_request_to_a_person_is_a_reviewer(self):
        got = self.run_with({"author": {"login": "me"},
                             "reviewRequests": {"nodes": [{"requestedReviewer": {"__typename": "User"}}]},
                             "reviews": {"nodes": []}, "comments": {"nodes": []}, "commits": {"nodes": []}})
        self.assertTrue(got["reviewers"])


class TurnEnd(unittest.TestCase):
    def test_turn_end_comes_from_claude_not_from_the_herdr_screen(self):
        # herdr は「動き出した」だけを返し、終わりは Claude Code が idle を返した所（herdr が作業中と見続けても進む）
        h = TurnHerdr(prompts=["working"], agent={"agent": "claude", "agent_status": "working"})
        states = iter(["busy", "busy", "idle"])
        got = turn.catchup_then_second(7, "p", SECOND, h, catchup=CATCHUP, state=lambda: next(states), pause=lambda: None)
        self.assertEqual(got, "sent")
        prompts = [c for c in h.calls if c[0] == "prompt"]
        self.assertEqual([c[2] for c in prompts], [f"{CATCHUP} 7", SECOND])

    def test_blocked_on_screen_stops_before_the_second_turn(self):
        h = TurnHerdr(prompts=["working"], agent={"agent": "claude", "agent_status": "blocked"})
        got = turn.catchup_then_second(7, "p", SECOND, h, catchup=CATCHUP, state=lambda: "busy", pause=lambda: None)
        self.assertEqual(got, "blocked")
        self.assertEqual(len([c for c in h.calls if c[0] == "prompt"]), 1)

    def test_close_session_sends_exit_and_reads_the_shell_back(self):
        h = FakeHerdr()
        h.talking.add("P0")
        self.assertEqual(turn.close_session("P0", h, pause=lambda: None), "closed")
        self.assertEqual(h.writes, [("prompt", "P0", "/exit", False)])

    def test_close_session_that_never_returns_is_close_failed(self):
        h = FakeHerdr()
        h.talking.add("P0")
        h.prompt = lambda *a, **k: "sent"   # /exit が効かない
        self.assertEqual(turn.close_session("P0", h, tries=3, pause=lambda: None), "close_failed")


def run_main(cfg, ports, *argv):
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        rc = dispatch.main(["--config", cfg, *argv], ports=ports)
    return rc, buf.getvalue()


def line(out, n):
    return next(l for l in out.splitlines() if l.startswith(f"#{n} "))


class Flow(unittest.TestCase):
    def setUp(self):
        self.cfg, self.root = make_cfg()
        self.src = gitx_source(self.cfg)

    def place(self, n):
        """その枝の場所（元の clone の worktree）を作っておく（前の回が作った形）。"""
        path = str(pathlib.Path(self.root, f"feat-{n}"))
        git("-C", self.src, "worktree", "add", "-q", "-b", f"feat/{n}", path, f"origin/feat/{n}")
        return path

    def talking_in(self, ports, path, status="idle", started=100.0):
        """その場所で会話が開いている形を作る（herdr のペインと claude agents の行）。"""
        pane = ports.herdr.open_at(path, agent="claude")
        ports.herdr.talking.add(pane["pane_id"])
        ports.agents = list(ports.agents) + [{"cwd": path, "status": status, "startedAt": started * 1000}]
        return pane

    def linked(self, ports):
        return [w for w in ports.herdr.worktrees(self.src) if w["linked"]]

    def test_own_pr_without_reviewers_is_not_opened(self):
        ports = FakePorts([pr(1)])
        ports.acts = {1: {"reviewers": False, "last_other": None}}
        rc, out = run_main(self.cfg, ports)
        self.assertEqual(rc, 0, out)
        self.assertTrue(line(out, 1).endswith("own_unreviewed"))
        self.assertEqual(ports.herdr.writes, [])
        self.assertEqual(self.linked(ports), [])

    def test_naming_the_pr_opens_it_even_without_reviewers(self):
        ports = FakePorts([])
        ports.acts = {1: {"reviewers": False, "last_other": None}}
        ports.pr_info = lambda repo, n: pr(n)
        rc, out = run_main(self.cfg, ports, "--pr", "1")
        self.assertTrue(line(out, 1).endswith("sent"), out)

    def test_news_in_an_idle_clean_session_reopens_it_in_the_same_place(self):
        path = self.place(1)
        ports = FakePorts([pr(1)])
        old = self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        rc, out = run_main(self.cfg, ports)
        self.assertEqual(rc, 0, out)
        self.assertTrue(line(out, 1).endswith("refreshed"), out)
        w = ports.herdr.writes
        self.assertEqual(w[0], ("prompt", old["pane_id"], "/exit", False))
        self.assertEqual(w[1], ("close_workspace", old["workspace_id"]))
        self.assertEqual(w[2], ("open_worktree", path, "r/feat/1"))   # checkout は残し、同じ場所を開き直す
        new = ports.herdr.panes()[0]["pane_id"]
        self.assertNotEqual(new, old["pane_id"])
        self.assertIn(("run", new, "claude-a1"), w)
        self.assertEqual([x[2] for x in w if x[0] == "prompt"][1:], [f"{CATCHUP} 1", "二手目"])
        self.assertEqual([x["path"] for x in self.linked(ports)], [path])
        sent = json.loads(pathlib.Path(self.root).parent.joinpath("limits", dispatch.SENT_FILE).read_text())
        self.assertIn("o/r#1", sent)

    def test_dry_run_says_refresh_and_touches_nothing(self):
        path = self.place(1)
        ports = FakePorts([pr(1)])
        self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        rc, out = run_main(self.cfg, ports, "--dry-run")
        self.assertTrue(line(out, 1).endswith("refresh"), out)
        self.assertEqual(ports.herdr.writes, [])

    def test_sessions_without_news_or_with_work_are_left_alone(self):
        for status, dirty, news, want in (("idle", False, None, "no_news"), ("busy", False, 500.0, "busy"),
                                          ("idle", True, 500.0, "dirty")):
            with self.subTest(want):
                self.setUp()
                path = self.place(1)
                if dirty:
                    pathlib.Path(path, "draft.py").write_text("x = 1\n")
                ports = FakePorts([pr(1)])
                self.talking_in(ports, path, status=status)
                ports.acts = {1: {"reviewers": True, "last_other": news}}
                rc, out = run_main(self.cfg, ports)
                self.assertTrue(line(out, 1).endswith(want), out)
                self.assertEqual(ports.herdr.writes, [])

    def merged(self, ports, n, path, state="MERGED"):
        ports.branch_prs = {f"feat/{n}": {"number": n, "state": state, "head_sha": gitx.head_sha(path)}}

    def test_closed_pr_with_an_idle_clean_session_is_closed_and_removed(self):
        path = self.place(5)
        ports = FakePorts([])
        old = self.talking_in(ports, path)
        self.merged(ports, 5, path)
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#5 feat/5: 片付けた", out)
        self.assertFalse(pathlib.Path(path).exists())
        self.assertEqual(git("-C", self.src, "branch", "--list", "feat/5"), "")
        self.assertEqual(ports.herdr.writes, [("prompt", old["pane_id"], "/exit", False), ("remove_worktree", path)])

    def test_closed_pr_with_a_busy_session_or_local_work_is_kept_and_named(self):
        for status, local, want in (("busy", None, "会話が作業中か手元の作業が有るので残した"),
                                    ("idle", "commit", "会話が作業中か手元の作業が有るので残した"),
                                    (None, "file", "手元の作業が有るので残した")):
            with self.subTest(status=status, local=local):
                self.setUp()
                path = self.place(5)
                ports = FakePorts([])
                if status:
                    self.talking_in(ports, path, status=status)
                self.merged(ports, 5, path)
                if local == "commit":
                    git("-C", path, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "x")
                if local == "file":
                    pathlib.Path(path, "draft.py").write_text("x\n")
                rc, out = run_main(self.cfg, ports)
                self.assertIn(f"#5 feat/5: 閉じた PR だが、{want}", out)
                self.assertTrue(pathlib.Path(path).exists())
                self.assertEqual(ports.herdr.writes, [])

    def test_branch_without_a_pr_is_never_tidied(self):
        path = self.place(5)
        ports = FakePorts([])
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(pathlib.Path(path).exists())
        self.assertEqual(ports.herdr.writes, [])
        self.assertNotIn("feat/5", out)

    def test_other_repos_and_the_previous_versions_clones_are_never_touched(self):
        # 持ち主の注意（2026-10-15「関係ないリポジトリの Clone を巻き込まないように」）: 見るのは元の clone の linked worktree だけ。
        # 同じ置き場に在る別のリポジトリの worktree も、前の版が作った <名前>-pr-<番号> の clone も並びに入らない
        other_src, _ = make_world()
        other = str(pathlib.Path(self.root, "feat-6"))
        git("-C", other_src, "worktree", "add", "-q", "-b", "feat/6", other, "origin/feat/6")
        old_clone = str(pathlib.Path(self.root).parent / "r-pr-6")
        git("clone", "-q", self.src, old_clone)
        ports = FakePorts([])
        ports.branch_prs = {"feat/6": {"number": 6, "state": "MERGED", "head_sha": gitx.head_sha(other)}}
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(pathlib.Path(other).exists())
        self.assertTrue(pathlib.Path(old_clone).exists())
        self.assertEqual(ports.herdr.writes, [])
        self.assertNotIn("#6", out)

    def test_dry_run_names_what_it_would_tidy_and_removes_nothing(self):
        path = self.place(5)
        ports = FakePorts([])
        self.merged(ports, 5, path, "CLOSED")
        rc, out = run_main(self.cfg, ports, "--dry-run")
        self.assertIn("#5 feat/5: 閉じた PR なので片付ける", out)
        self.assertTrue(pathlib.Path(path).exists())
        self.assertEqual(ports.herdr.writes, [])


if __name__ == "__main__":
    unittest.main()
