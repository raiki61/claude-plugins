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
from .test_dispatch import FakeHerdr, FakePorts, gitx_source, make_cfg, pr, typed
from .test_launch_turn import CATCHUP, SECOND
from .test_launch_turn import FakeHerdr as TurnHerdr
from .test_provision import git, make_world
import claudex
import dispatch
import ghx
import gitx
import herdr as real_herdr
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

    def test_a_moved_head_is_news_even_without_newer_activity(self):
        # 作者の push（force-push で古い時刻の commit が来ても）。会話の無い PR の判断（quiet_since_sent）と同じ見方
        moved = {"last_other": 150.0, "head_sha": "b" * 40}
        self.assertEqual(fresh.decide(session(), moved, 200.0, True, False, sent_head="a" * 40), "refresh")
        self.assertEqual(fresh.decide(session(), moved, 200.0, True, False, sent_head="b" * 40), "no_news")
        self.assertEqual(fresh.decide(session(), moved, 200.0, True, False), "no_news")   # 古い控え（head 無し）
        self.assertEqual(fresh.decide(session("busy"), moved, 200.0, True, False, sent_head="a" * 40), "busy")

    def test_busy_or_local_work_is_never_refreshed(self):
        news = {"last_other": 999.0}
        self.assertEqual(fresh.decide(session("busy"), news, None, True, False), "busy")
        self.assertEqual(fresh.decide(session(), news, None, False, False), "dirty")
        self.assertEqual(fresh.decide(session(), news, None, True, True), "unpushed")

    def test_inside_follows_symlinks_like_clean(self):
        import os
        import tempfile
        real = pathlib.Path(tempfile.mkdtemp()).resolve()
        (real / "feat-1").mkdir()
        link = pathlib.Path(tempfile.mkdtemp()) / "w"
        os.symlink(real, link)
        self.assertTrue(fresh.inside(str(real / "feat-1" / "sub"), str(link / "feat-1")))
        self.assertFalse(fresh.inside(str(real / "feat-10"), str(link / "feat-1")))

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
        self.assertEqual(got, {"reviewers": False, "last_other": None, "head_sha": None})

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

    def test_head_of_the_pr_is_read(self):
        got = self.run_with({"author": {"login": "me"}, "headRefOid": "c" * 40, "reviewRequests": {"nodes": []},
                             "reviews": {"nodes": []}, "comments": {"nodes": []}, "commits": {"nodes": []}})
        self.assertEqual(got["head_sha"], "c" * 40)

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
        ports.agents = list(ports.agents) + [{"cwd": path, "status": status, "startedAt": started * 1000,
                                              "pane": pane["pane_id"]}]
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
        self.assertIn(("run", new, typed("claude-a1")), w)
        self.assertEqual([x[2] for x in w if x[0] == "prompt"][1:], [f"{CATCHUP} 1", "二手目"])
        self.assertEqual([x["path"] for x in self.linked(ports)], [path])
        sent = json.loads(pathlib.Path(self.root).parent.joinpath("limits", dispatch.SENT_FILE).read_text())
        self.assertIn("o/r#1", sent)

    def test_refresh_records_the_send_time_before_the_first_turn_and_the_head(self):
        path = self.place(1)
        ports = FakePorts([pr(1)])
        self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        ports.now = lambda: float(len(ports.herdr.writes))   # 時計を「それまでに外へ書いた数」にする
        run_main(self.cfg, ports, "--no-second")   # --no-second の回も控えを書く
        sent = json.loads(pathlib.Path(self.root).parent.joinpath("limits", dispatch.SENT_FILE).read_text())
        first = next(i for i, w in enumerate(ports.herdr.writes) if w[0] == "prompt" and w[2] == f"{CATCHUP} 1")
        self.assertEqual(sent["o/r#1"], {"at": float(first), "head": gitx.head_sha(path)})   # 1 ターン目を送る直前

    def test_old_send_record_with_only_a_time_is_still_read(self):
        path = self.place(1)
        ports = FakePorts([pr(1)])
        self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": 150.0}}
        limits = pathlib.Path(self.root).parent / "limits"
        limits.mkdir(exist_ok=True)
        (limits / dispatch.SENT_FILE).write_text(json.dumps({"o/r#1": 200.0}))
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(line(out, 1).endswith("no_news"), out)

    def test_force_pushed_branch_is_refreshed_and_reset_to_origin(self):
        # 作者が force-push した: 手元の HEAD は前に送った時の head のまま、origin の祖先ではない。手元で積んだ commit とは見分け、
        # 送り直して origin の head に揃える
        from .test_provision import advance
        advance(self.src, "feat/1")
        path = str(pathlib.Path(self.root, "feat-1"))
        git("-C", self.src, "worktree", "add", "-q", "-b", "feat/1", path, "origin/feat/1")
        old = gitx.head_sha(path)
        rewritten = git("-C", self.src, "-c", "user.name=o", "-c", "user.email=o@o", "commit-tree", f"{old}^{{tree}}",
                        "-p", f"{old}^", "-m", "rewritten")
        git("-C", self.src, "push", "-q", "--force", "origin", f"{rewritten}:refs/heads/feat/1")
        git("-C", self.src, "fetch", "-q", "origin")   # 持ち主が取った後でも、手元だけの commit とはみなさない
        limits = pathlib.Path(self.root).parent / "limits"
        limits.mkdir(exist_ok=True)
        (limits / dispatch.SENT_FILE).write_text(json.dumps({"o/r#1": {"at": 100.0, "head": old}}))
        ports = FakePorts([pr(1)])
        self.talking_in(ports, path, started=50.0)
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(line(out, 1).endswith("refreshed"), out)
        self.assertEqual(gitx.head_sha(path), rewritten)
        self.assertIn("force-push", out)

    def test_refresh_does_not_close_a_workspace_with_another_busy_pane(self):
        path = self.place(1)
        ports = FakePorts([pr(1)])
        old = self.talking_in(ports, path)
        extra = ports.herdr.add_pane(old["workspace_id"], path)
        ports.herdr.busy.add(extra["pane_id"])
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(line(out, 1).endswith("close_failed"), out)
        self.assertNotIn(("close_workspace", old["workspace_id"]), ports.herdr.writes)
        self.assertFalse([w for w in ports.herdr.writes if w[0] in ("run", "open_worktree", "create_worktree")])

    def test_conversation_outside_herdr_is_not_closed_for_refresh(self):
        # 会話は herdr の外（VS Code の端末など）に居て、herdr のその場所にはシェルだけがある
        path = self.place(1)
        ports = FakePorts([pr(1)])
        ports.herdr.open_at(path)
        ports.agents = [{"cwd": path, "status": "idle", "startedAt": 100000}]
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(line(out, 1).endswith("close_failed"), out)
        self.assertIn("herdr の外の会話は終えない", out)
        self.assertEqual(ports.herdr.writes, [])

    def test_unreadable_herdr_panes_make_the_pr_close_failed_not_a_traceback(self):
        path = self.place(1)
        ports = FakePorts([pr(1)])
        self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}

        def boom():
            raise real_herdr.HerdrError(["herdr", "pane", "list"], "server_unreachable")
        ports.herdr.panes = boom
        rc, out = run_main(self.cfg, ports)
        self.assertEqual(rc, 0)
        self.assertTrue(line(out, 1).endswith("close_failed"), out)
        self.assertIn("server_unreachable", out)

    def sent(self, record):
        limits = pathlib.Path(self.root).parent / "limits"
        limits.mkdir(exist_ok=True)
        (limits / dispatch.SENT_FILE).write_text(json.dumps(record))

    def test_without_a_conversation_an_earlier_send_without_news_is_not_reopened(self):
        # 持ち主の決め（2026-10-15）: 返事待ちの PR は、持ち主が会話を閉じただけでは開き直さない
        H = "a" * 40
        cases = (
            ("控えあり・動き無し", {"o/r#1": {"at": 100.0, "head": H}}, {"last_other": 90.0, "head_sha": H}, (), "no_news"),
            ("控えあり・動きあり", {"o/r#1": {"at": 100.0, "head": H}}, {"last_other": 500.0, "head_sha": H}, (), "create"),
            ("head が違う", {"o/r#1": {"at": 100.0, "head": H}}, {"last_other": None, "head_sha": "b" * 40}, (), "create"),
            ("--pr で名指し", {"o/r#1": {"at": 100.0, "head": H}}, {"last_other": None, "head_sha": H}, ("--pr", "1"), "create"),
            ("控え無し", {}, {"last_other": None, "head_sha": H}, (), "create"),
            ("時刻だけの古い控え・動き無し", {"o/r#1": 100.0}, {"last_other": None, "head_sha": H}, (), "no_news"),
        )
        for name, record, act, argv, want in cases:
            with self.subTest(name):
                self.setUp()
                self.sent(record)
                ports = FakePorts([{**pr(1), "role": "reviewer"}])
                ports.pr_info = lambda repo, n: pr(n)
                ports.acts = {1: {"reviewers": True, **act}}
                rc, out = run_main(self.cfg, ports, "--dry-run", *argv)
                self.assertEqual(rc, 0, out)
                self.assertTrue(line(out, 1).endswith(want), out)
                self.assertEqual(ports.herdr.writes, [])

    def test_no_news_pr_takes_no_account_and_makes_no_place(self):
        self.sent({"o/r#1": {"at": 100.0, "head": "a" * 40}})
        ports = FakePorts([pr(1), pr(2)])
        ports.acts = {1: {"reviewers": True, "last_other": None, "head_sha": "a" * 40}}
        rc, out = run_main(self.cfg, ports)
        self.assertEqual(line(out, 1).split()[-2:], ["-", "no_news"])
        self.assertTrue(line(out, 2).endswith("sent"), out)
        self.assertEqual([w["branch"] for w in self.linked(ports)], ["feat/2"])

    def test_open_conversation_with_a_moved_head_is_refreshed(self):
        path = self.place(1)
        self.sent({"o/r#1": {"at": 1000.0, "head": gitx.head_sha(path)}})
        ports = FakePorts([pr(1)])
        self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": None, "head_sha": "b" * 40}}
        rc, out = run_main(self.cfg, ports, "--dry-run")
        self.assertTrue(line(out, 1).endswith("refresh"), out)

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

    def test_closed_pr_with_two_conversations_is_kept(self):
        path = self.place(5)
        ports = FakePorts([])
        self.talking_in(ports, path)
        ports.agents = list(ports.agents) + [{"cwd": path + "/backend", "status": "idle"}]
        self.merged(ports, 5, path)
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#5 feat/5: 閉じた PR だが、会話が 2 つ開いているので残した", out)
        self.assertEqual(ports.herdr.writes, [])

    def test_closed_pr_whose_conversation_is_outside_herdr_is_kept(self):
        path = self.place(5)
        ports = FakePorts([])
        ports.herdr.open_at(path)   # herdr にはシェルだけ
        ports.agents = [{"cwd": path, "status": "idle"}]
        self.merged(ports, 5, path)
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#5 feat/5: 閉じた PR の会話を終えられなかったので残した", out)
        self.assertTrue(pathlib.Path(path).exists())
        self.assertEqual(ports.herdr.writes, [])

    def test_closed_pr_whose_conversation_is_still_listed_after_exit_is_kept(self):
        # /exit の後に会話の一覧を取り直し、その場所にまだ会話が見えれば消さない
        path = self.place(5)
        ports = FakePorts([])
        self.talking_in(ports, path)
        ports.agents = [{k: v for k, v in x.items() if k != "pane"} for x in ports.agents]
        self.merged(ports, 5, path)
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#5 feat/5: 会話を終えた後も、その場所に会話が見えるので残した", out)
        self.assertTrue(pathlib.Path(path).exists())

    def test_closed_pr_with_a_changed_copied_file_is_kept_and_named(self):
        path = self.place(5)
        pathlib.Path(path, "frontend").mkdir()
        pathlib.Path(path, "frontend", ".env.local").write_text("CHANGED=1\n")
        pathlib.Path(path, "node_modules").mkdir()   # 依存や生成物は捨ててよい（理由にならない）
        ports = FakePorts([])
        self.merged(ports, 5, path)
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#5 feat/5: 閉じた PR だが、写したファイルが写し元と違うので残した: frontend/.env.local", out)
        self.assertTrue(pathlib.Path(path).exists())

    def test_ignored_dependencies_alone_do_not_keep_the_place(self):
        path = self.place(5)
        pathlib.Path(path, "frontend").mkdir()
        pathlib.Path(path, "frontend", ".env.local").write_text("SECRET=1\n")   # 写し元と同じ
        ports = FakePorts([])
        self.merged(ports, 5, path)
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#5 feat/5: 片付けた", out)
        self.assertFalse(pathlib.Path(path).exists())

    def test_unreadable_conversations_skip_tidying_with_a_note(self):
        path = self.place(5)
        ports = FakePorts([])
        self.merged(ports, 5, path)
        calls = []

        def flaky(config_dir):
            calls.append(1)
            if len(calls) > 1:   # 1 回目（流れの始め）は読めて、片付けの時に読めない
                raise claudex.ClaudeError("claude agents --json（x）: boom")
            return []
        ports.list_sessions = flaky
        rc, out = run_main(self.cfg, ports)
        self.assertEqual(rc, 0)
        self.assertIn("片付けを飛ばした（開いている会話を読めない: claude agents --json（x）: boom）", out)
        self.assertTrue(pathlib.Path(path).exists())

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
