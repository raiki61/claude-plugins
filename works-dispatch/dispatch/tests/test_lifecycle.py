"""PR ごとの場所の一生を 1 つのコマンドで回す（設計書のセクション 2 の 3・セクション 3 の片付け）。
- 自分が作者でレビュアーの付いていない PR は、一覧からは開かない（--pr で指せば開く）
- 会話の開いている PR は、自分以外の動きが前に送った時より後に有り、会話が手すきで手元の作業も無ければ、会話を終えてペインを畳み、
  同じ場所（checkout）に新しい作業場と会話を立てて /catchup から送り直す
- 自分の番でなくなった開いている PR は、dispatch が一覧の回で送った会話が手すきで手元の作業も無ければ、会話を終えて作業場を閉じる
  （worktree は残す）
- 閉じた PR のブランチの場所は、会話が手すきで手元の作業も無ければ会話を終えて消す。元の clone の linked worktree だけを見る
- 1 ターン目の終わりは Claude Code 自身の状態で見る（herdr の画面の見立てだけに頼らない）
"""

import contextlib
import io
import json
import os
import pathlib
import subprocess
import unittest

from . import DISPATCH, fakegit  # noqa: F401
from .test_dispatch import FakeHerdr, FakePorts, fake_cfg, gitx_source, pr, typed
from .test_launch_turn import CATCHUP, SECOND
from .test_launch_turn import FakeHerdr as TurnHerdr
import claudex
import dispatch
import filex
import wiring
import ghx
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
        self.assertTrue(filex.inside(str(real / "feat-1" / "sub"), str(link / "feat-1")))
        self.assertFalse(filex.inside(str(real / "feat-10"), str(link / "feat-1")))

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
        self.assertEqual([c[2] for c in prompts], [f"{CATCHUP} 7", turn.with_carry(SECOND, CATCHUP)])

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
    """git（tests/fakegit.py）・herdr・claude・gh は偽物で回す。"""

    def setUp(self):
        self.cfg, self.root, self.g = fake_cfg()
        fakegit.forbid_real_git(self)
        self.src = gitx_source(self.cfg)

    def place(self, n):
        """そのブランチの場所（元の clone の worktree）を作っておく（前の回が作った形）。"""
        return self.g.add_worktree(str(pathlib.Path(self.root, f"feat-{n}")), f"feat/{n}", f"origin/feat/{n}")

    def advance(self, branch):
        """origin のブランチに、手元に無い commit を 1 つ積む（ほかの人が push した形。手元の origin/<branch> も取った後）。積んだ commit を返す。"""
        sha = self.g.push_origin(branch, {}, "theirs")
        self.g.tracking[branch] = sha
        return sha

    def force_pushed(self, branch, old):
        """作者が old を書き直して origin の branch に force-push し、持ち主が取った後の形。書き直した commit を返す。"""
        rewritten = self.g._new(self.g.commits[old]["parent"], self.g.files(old), "rewritten")
        self.g.origin[branch] = self.g.tracking[branch] = rewritten
        return rewritten

    def talking_in(self, ports, path, status="idle", started=100.0):
        """その場所で会話が開いている形を作る（herdr のペインと claude agents の行）。"""
        pane = ports.term.open_at(path, agent="claude")
        ports.term.talking.add(pane["pane_id"])
        ports.agents = list(ports.agents) + [{"cwd": path, "status": status, "startedAt": started * 1000,
                                              "pane": pane["pane_id"]}]
        return pane

    def linked(self, ports):
        return [w for w in ports.term.worktrees(self.src) if w["linked"]]

    def test_own_pr_without_reviewers_is_opened_with_catchup_only(self):
        ports = FakePorts([pr(1)], git=self.g)
        ports.acts = {1: {"reviewers": False, "last_other": None}}
        rc, out = run_main(self.cfg, ports)
        self.assertEqual(rc, 0, out)
        self.assertTrue(line(out, 1).endswith("sent"), out)
        self.assertEqual([x[2] for x in ports.term.writes if x[0] == "prompt"], [f"{CATCHUP} 1"])  # 2 ターン目は送らない
        self.assertIn("/catchup だけ", out)

    def test_naming_the_pr_opens_it_even_without_reviewers(self):
        ports = FakePorts([], git=self.g)
        ports.acts = {1: {"reviewers": False, "last_other": None}}
        ports.pr_info = lambda repo, n: pr(n)
        rc, out = run_main(self.cfg, ports, "--pr", "1")
        self.assertTrue(line(out, 1).endswith("sent"), out)
        self.assertEqual([x[2] for x in ports.term.writes if x[0] == "prompt"], [f"{CATCHUP} 1"])

    def test_news_in_an_idle_clean_session_reopens_it_in_the_same_place(self):
        path = self.place(1)
        ports = FakePorts([pr(1)], git=self.g)
        old = self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        rc, out = run_main(self.cfg, ports)
        self.assertEqual(rc, 0, out)
        self.assertTrue(line(out, 1).endswith("refreshed"), out)
        w = ports.term.writes
        self.assertEqual(w[0], ("prompt", old["pane_id"], "/exit", False))
        self.assertEqual(w[1], ("close_workspace", old["workspace_id"]))
        self.assertEqual(w[2], ("open_worktree", path, "r/feat/1"))   # checkout は残し、同じ場所を開き直す
        new = ports.term.panes()[0]["pane_id"]
        self.assertNotEqual(new, old["pane_id"])
        self.assertIn(("run", new, typed("claude-a1")), w)
        self.assertEqual([x[2] for x in w if x[0] == "prompt"][1:], [f"{CATCHUP} 1", turn.with_carry("二手目", CATCHUP)])
        self.assertEqual([x["path"] for x in self.linked(ports)], [path])
        sent = json.loads(pathlib.Path(self.root).parent.joinpath("limits", wiring.SENT_FILE).read_text())
        self.assertIn("o/r#1", sent)

    def test_reopening_leaves_the_old_conversations_report_and_passes_its_place(self):
        # 前の回の報告（GitHub に出していない下書きを含む）を、次の会話が読めるように場所の git の置き場に残して渡す（頼み 98e76d）
        path = self.place(1)
        ports = FakePorts([pr(1)], git=self.g)
        self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        talks = pathlib.Path(claudex.talk_dir(str(pathlib.Path(self.root).parent / "c1"), path, {}))
        talks.mkdir(parents=True)
        rows = [{"type": "user", "message": {"content": f"{CATCHUP} 1"}}, {"type": "assistant", "message": {"content": [{"type": "text", "text": "PR の今"}]}},
                {"type": "user", "message": {"content": "二手目"}},
                {"type": "assistant", "message": {"content": [{"type": "text", "text": "下書き: helm test に寄せる"}]}}]
        (talks / "old.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")
        (talks / "new.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows[:2]), encoding="utf-8")
        os.utime(talks / "old.jsonl", (1000, 1000))
        os.utime(talks / "new.jsonl", (2000, 2000))   # いちばん新しい会話が /catchup だけで終わっていても、その前の報告を渡す
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(line(out, 1).endswith("refreshed"), out)
        kept = os.path.join(self.g.git_dir(path), "works-dispatch", "reports", "old.md")
        self.assertFalse(filex.inside(kept, path), "作業ツリーを汚さない")
        self.assertIn("下書き: helm test に寄せる", pathlib.Path(kept).read_text(encoding="utf-8"))
        self.assertEqual(os.listdir(os.path.dirname(kept)), ["old.md"])
        self.assertEqual([x[2] for x in ports.term.writes if x[0] == "prompt"][-1], turn.with_carry("二手目", CATCHUP, kept))

    def test_reopening_without_an_earlier_report_adds_nothing(self):
        path = self.place(1)
        ports = FakePorts([pr(1)], git=self.g)
        self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        talks = pathlib.Path(claudex.talk_dir(str(pathlib.Path(self.root).parent / "c1"), path, {}))
        talks.mkdir(parents=True)
        (talks / "old.jsonl").write_text(json.dumps({"type": "user", "message": {"content": f"{CATCHUP} 1"}}) + "\n"
                                         + json.dumps({"type": "assistant", "message": {"content": [{"type": "text", "text": "PR の今"}]}}) + "\n",
                                         encoding="utf-8")
        rc, out = run_main(self.cfg, ports)
        self.assertEqual([x[2] for x in ports.term.writes if x[0] == "prompt"][-1], turn.with_carry("二手目", CATCHUP))
        self.assertFalse(os.path.exists(os.path.join(self.g.git_dir(path), "works-dispatch")))

    def test_refresh_records_the_send_time_before_the_first_turn_and_the_head(self):
        path = self.place(1)
        ports = FakePorts([pr(1)], git=self.g)
        self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        ports.now = lambda: float(len(ports.term.writes))   # 時計を「それまでに外へ書いた数」にする
        run_main(self.cfg, ports, "--no-second")   # --no-second の回も控えを書く
        sent = json.loads(pathlib.Path(self.root).parent.joinpath("limits", wiring.SENT_FILE).read_text())
        first = next(i for i, w in enumerate(ports.term.writes) if w[0] == "prompt" and w[2] == f"{CATCHUP} 1")
        self.assertEqual(sent["o/r#1"], {"at": float(first), "head": self.g.head_sha(path), "via": "listing"})   # 1 ターン目を送る直前

    def test_old_send_record_with_only_a_time_is_still_read(self):
        path = self.place(1)
        ports = FakePorts([pr(1)], git=self.g)
        self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": 150.0}}
        limits = pathlib.Path(self.root).parent / "limits"
        limits.mkdir(exist_ok=True)
        (limits / wiring.SENT_FILE).write_text(json.dumps({"o/r#1": 200.0}))
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(line(out, 1).endswith("no_news"), out)

    def test_force_pushed_branch_is_refreshed_and_reset_to_origin(self):
        # 作者が force-push した: 手元の HEAD は前に送った時の head のまま、origin の祖先ではない。手元で積んだ commit とは見分け、
        # 送り直して origin の head に揃える
        self.advance("feat/1")
        path = self.place(1)
        old = self.g.head_sha(path)
        rewritten = self.force_pushed("feat/1", old)   # 持ち主が取った後でも、手元だけの commit とはみなさない
        limits = pathlib.Path(self.root).parent / "limits"
        limits.mkdir(exist_ok=True)
        (limits / wiring.SENT_FILE).write_text(json.dumps({"o/r#1": {"at": 100.0, "head": old}}))
        ports = FakePorts([pr(1)], git=self.g)
        self.talking_in(ports, path, started=50.0)
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(line(out, 1).endswith("refreshed"), out)
        self.assertEqual(self.g.head_sha(path), rewritten)
        self.assertIn("force-push", out)

    def test_refresh_does_not_close_a_workspace_with_another_busy_pane(self):
        path = self.place(1)
        ports = FakePorts([pr(1)], git=self.g)
        old = self.talking_in(ports, path)
        extra = ports.term.add_pane(old["workspace_id"], path)
        ports.term.busy.add(extra["pane_id"])
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(line(out, 1).endswith("close_failed"), out)
        self.assertNotIn(("close_workspace", old["workspace_id"]), ports.term.writes)
        self.assertFalse([w for w in ports.term.writes if w[0] in ("run", "open_worktree", "create_worktree")])

    def test_conversation_outside_herdr_is_not_closed_for_refresh(self):
        # 会話は herdr の外（VS Code の端末など）に居て、herdr のその場所にはシェルだけがある
        path = self.place(1)
        ports = FakePorts([pr(1)], git=self.g)
        ports.term.open_at(path)
        ports.agents = [{"cwd": path, "status": "idle", "startedAt": 100000}]
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(line(out, 1).endswith("close_failed"), out)
        self.assertIn("herdr の外の会話は終えない", out)
        self.assertEqual(ports.term.writes, [])

    def test_unreadable_herdr_panes_make_the_pr_close_failed_not_a_traceback(self):
        path = self.place(1)
        ports = FakePorts([pr(1)], git=self.g)
        self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}

        def boom():
            raise real_herdr.Error(["herdr", "pane", "list"], "server_unreachable")
        ports.term.panes = boom
        rc, out = run_main(self.cfg, ports)
        self.assertEqual(rc, 0)
        self.assertTrue(line(out, 1).endswith("close_failed"), out)
        self.assertIn("server_unreachable", out)

    def sent(self, record):
        limits = pathlib.Path(self.root).parent / "limits"
        limits.mkdir(exist_ok=True)
        (limits / wiring.SENT_FILE).write_text(json.dumps(record))

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
                ports = FakePorts([{**pr(1), "role": "reviewer"}], git=self.g)
                ports.pr_info = lambda repo, n: pr(n)
                ports.acts = {1: {"reviewers": True, **act}}
                rc, out = run_main(self.cfg, ports, "--dry-run", *argv)
                self.assertEqual(rc, 0, out)
                self.assertTrue(line(out, 1).endswith(want), out)
                self.assertEqual(ports.term.writes, [])

    def test_no_news_pr_takes_no_account_and_makes_no_place(self):
        self.sent({"o/r#1": {"at": 100.0, "head": "a" * 40}})
        ports = FakePorts([pr(1), pr(2)], git=self.g)
        ports.acts = {1: {"reviewers": True, "last_other": None, "head_sha": "a" * 40}}
        rc, out = run_main(self.cfg, ports)
        self.assertEqual(line(out, 1).split()[-2:], ["-", "no_news"])
        self.assertTrue(line(out, 2).endswith("sent"), out)
        self.assertEqual([w["branch"] for w in self.linked(ports)], ["feat/2"])

    def test_open_conversation_with_a_moved_head_is_refreshed(self):
        path = self.place(1)
        self.sent({"o/r#1": {"at": 1000.0, "head": self.g.head_sha(path)}})
        ports = FakePorts([pr(1)], git=self.g)
        self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": None, "head_sha": "b" * 40}}
        rc, out = run_main(self.cfg, ports, "--dry-run")
        self.assertTrue(line(out, 1).endswith("refresh"), out)

    def test_dry_run_says_refresh_and_touches_nothing(self):
        path = self.place(1)
        ports = FakePorts([pr(1)], git=self.g)
        self.talking_in(ports, path)
        ports.acts = {1: {"reviewers": True, "last_other": 500.0}}
        rc, out = run_main(self.cfg, ports, "--dry-run")
        self.assertTrue(line(out, 1).endswith("refresh"), out)
        self.assertEqual(ports.term.writes, [])

    def test_sessions_without_news_or_with_work_are_left_alone(self):
        for status, dirty, news, want in (("idle", False, None, "no_news"), ("busy", False, 500.0, "busy"),
                                          ("idle", True, 500.0, "dirty")):
            with self.subTest(want):
                self.setUp()
                path = self.place(1)
                if dirty:
                    pathlib.Path(path, "draft.py").write_text("x = 1\n")
                    self.g.dirty.add(path)
                ports = FakePorts([pr(1)], git=self.g)
                self.talking_in(ports, path, status=status)
                ports.acts = {1: {"reviewers": True, "last_other": news}}
                rc, out = run_main(self.cfg, ports)
                self.assertTrue(line(out, 1).endswith(want), out)
                self.assertEqual(ports.term.writes, [])

    def merged(self, ports, n, path, state="MERGED"):
        ports.branch_prs = {f"feat/{n}": {"number": n, "state": state, "head_sha": self.g.head_sha(path)}}

    def test_closed_pr_with_an_idle_clean_session_is_closed_and_removed(self):
        path = self.place(5)
        ports = FakePorts([], git=self.g)
        old = self.talking_in(ports, path)
        self.merged(ports, 5, path)
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#5 feat/5: 片付けた", out)
        self.assertFalse(pathlib.Path(path).exists())
        self.assertEqual(self.g.local.get("feat/5"), None)
        self.assertEqual(ports.term.writes, [("prompt", old["pane_id"], "/exit", False), ("remove_worktree", path)])

    def test_closed_pr_with_a_busy_session_or_local_work_is_kept_and_named(self):
        for status, local, want in (("busy", None, "会話が作業中か手元の作業が有るので残した"),
                                    ("idle", "commit", "会話が作業中か手元の作業が有るので残した"),
                                    (None, "file", "手元の作業が有るので残した")):
            with self.subTest(status=status, local=local):
                self.setUp()
                path = self.place(5)
                ports = FakePorts([], git=self.g)
                if status:
                    self.talking_in(ports, path, status=status)
                self.merged(ports, 5, path)
                if local == "commit":
                    self.g.commit(path, {}, "x")
                if local == "file":
                    pathlib.Path(path, "draft.py").write_text("x\n")
                    self.g.dirty.add(path)
                rc, out = run_main(self.cfg, ports)
                self.assertIn(f"#5 feat/5: 閉じた PR だが、{want}", out)
                self.assertTrue(pathlib.Path(path).exists())
                self.assertEqual(ports.term.writes, [])

    def test_closed_pr_whose_place_is_only_behind_the_pr_head_is_removed(self):
        # 2026-10-20: 手元が origin のブランチより遅れているだけ（手元の先頭が PR の head の祖先）なら、手元の作業ではない。
        # 会話が無くても、手すきの会話が 1 つ開いていても片付け、手元のブランチも消す
        for talking in (False, True):
            with self.subTest(talking=talking):
                self.setUp()
                path = self.place(5)
                ports = FakePorts([], git=self.g)
                if talking:
                    self.talking_in(ports, path)
                tip = self.advance("feat/5")
                ports.branch_prs = {"feat/5": {"number": 5, "state": "MERGED", "head_sha": tip}}
                rc, out = run_main(self.cfg, ports)
                self.assertIn("#5 feat/5: 片付けた", out)
                self.assertFalse(pathlib.Path(path).exists())
                self.assertEqual(self.g.local.get("feat/5"), None)

    def test_closed_pr_whose_head_commit_is_not_in_the_clone_is_kept(self):
        # PR の head の commit が手元に無ければ、手元の先頭がその祖先かを確かめられないので残す
        path = self.place(5)
        ports = FakePorts([], git=self.g)
        ports.branch_prs = {"feat/5": {"number": 5, "state": "MERGED", "head_sha": "f" * 40}}
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#5 feat/5: 閉じた PR だが、手元の作業が有るので残した", out)
        self.assertTrue(pathlib.Path(path).exists())

    def test_closed_pr_whose_place_has_its_own_commit_behind_the_pr_head_is_kept(self):
        # PR の head が先に進んでいても、手元にしか無い commit が有れば（手元の先頭が PR の head の祖先でない）残す
        for talking, want in ((False, "手元の作業が有るので残した"), (True, "会話が作業中か手元の作業が有るので残した")):
            with self.subTest(talking=talking):
                self.setUp()
                path = self.place(5)
                ports = FakePorts([], git=self.g)
                if talking:
                    self.talking_in(ports, path)
                tip = self.advance("feat/5")
                self.g.commit(path, {}, "mine")
                ports.branch_prs = {"feat/5": {"number": 5, "state": "MERGED", "head_sha": tip}}
                rc, out = run_main(self.cfg, ports)
                self.assertIn(f"#5 feat/5: 閉じた PR だが、{want}", out)
                self.assertTrue(pathlib.Path(path).exists())
                self.assertEqual(ports.term.writes, [])

    def test_closed_pr_with_two_conversations_is_kept(self):
        path = self.place(5)
        ports = FakePorts([], git=self.g)
        self.talking_in(ports, path)
        ports.agents = list(ports.agents) + [{"cwd": path + "/backend", "status": "idle"}]
        self.merged(ports, 5, path)
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#5 feat/5: 閉じた PR だが、会話が 2 つ開いているので残した", out)
        self.assertEqual(ports.term.writes, [])

    def test_closed_pr_whose_conversation_is_outside_herdr_is_kept(self):
        path = self.place(5)
        ports = FakePorts([], git=self.g)
        ports.term.open_at(path)   # herdr にはシェルだけ
        ports.agents = [{"cwd": path, "status": "idle"}]
        self.merged(ports, 5, path)
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#5 feat/5: 閉じた PR の会話を終えられなかったので残した", out)
        self.assertTrue(pathlib.Path(path).exists())
        self.assertEqual(ports.term.writes, [])

    def test_closed_pr_whose_conversation_is_still_listed_after_exit_is_kept(self):
        # /exit の後に会話の一覧を取り直し、その場所にまだ会話が見えれば消さない
        path = self.place(5)
        ports = FakePorts([], git=self.g)
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
        ports = FakePorts([], git=self.g)
        self.merged(ports, 5, path)
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#5 feat/5: 閉じた PR だが、写したファイルが写し元と違うので残した: frontend/.env.local", out)
        self.assertTrue(pathlib.Path(path).exists())

    def test_ignored_dependencies_alone_do_not_keep_the_place(self):
        path = self.place(5)
        pathlib.Path(path, "frontend").mkdir()
        pathlib.Path(path, "frontend", ".env.local").write_text("SECRET=1\n")   # 写し元と同じ
        ports = FakePorts([], git=self.g)
        self.merged(ports, 5, path)
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#5 feat/5: 片付けた", out)
        self.assertFalse(pathlib.Path(path).exists())

    def test_unreadable_conversations_skip_tidying_with_a_note(self):
        path = self.place(5)
        ports = FakePorts([], git=self.g)
        self.merged(ports, 5, path)
        calls = []

        def flaky(config_dir):
            calls.append(1)
            if len(calls) > 1:   # 1 回目（流れの始め）は読めて、片付けの時に読めない
                raise claudex.Error("claude agents --json（x）: boom")
            return []
        ports.list_sessions = flaky
        rc, out = run_main(self.cfg, ports)
        self.assertEqual(rc, 0)
        self.assertIn("片付けを飛ばした（開いている会話を読めない: claude agents --json（x）: boom）", out)
        self.assertTrue(pathlib.Path(path).exists())

    def test_branch_without_a_pr_is_never_tidied(self):
        path = self.place(5)
        ports = FakePorts([], git=self.g)
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(pathlib.Path(path).exists())
        self.assertEqual(ports.term.writes, [])
        self.assertNotIn("feat/5", out)

    def test_other_repos_and_the_previous_versions_clones_are_never_touched(self):
        # 持ち主の注意（2026-10-15「関係ないリポジトリの Clone を巻き込まないように」）: 見るのは元の clone の linked worktree だけ。
        # 同じ置き場に在る別のリポジトリの worktree も、前の版が作った <名前>-pr-<番号> の clone も並びに入らない
        other_git, _, _ = fakegit.world()
        other = other_git.add_worktree(str(pathlib.Path(self.root, "feat-6")), "feat/6", "origin/feat/6")
        old_clone = fakegit.FakeGit(str(pathlib.Path(self.root).parent / "r-pr-6"), {}).source   # 前の版が作った clone
        ports = FakePorts([], git=fakegit.Repos(self.g, other_git))
        ports.branch_prs = {"feat/6": {"number": 6, "state": "MERGED", "head_sha": other_git.head_sha(other)}}
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(pathlib.Path(other).exists())
        self.assertTrue(pathlib.Path(old_clone).exists())
        self.assertEqual(ports.term.writes, [])
        self.assertNotIn("#6", out)

    def test_dry_run_names_what_it_would_tidy_and_removes_nothing(self):
        path = self.place(5)
        ports = FakePorts([], git=self.g)
        self.merged(ports, 5, path, "CLOSED")
        rc, out = run_main(self.cfg, ports, "--dry-run")
        self.assertIn("#5 feat/5: 閉じた PR なので片付ける", out)
        self.assertTrue(pathlib.Path(path).exists())
        self.assertEqual(ports.term.writes, [])


    def off_turn(self, n=3, started=100.0, record=None):
        """自分の番でない開いている PR（一覧に無い）の場所に、dispatch が前に送った会話が開いている形。"""
        path = self.place(n)
        ports = FakePorts([], git=self.g)
        pane = self.talking_in(ports, path, started=started)
        ports.branch_prs = {f"feat/{n}": {"number": n, "state": "OPEN", "head_sha": self.g.head_sha(path)}}
        self.sent({f"o/r#{n}": record or {"at": 200.0, "head": self.g.head_sha(path), "via": "listing"}})
        return path, ports, pane

    def test_off_turn_pr_with_an_idle_clean_session_is_closed_and_the_worktree_kept(self):
        path, ports, pane = self.off_turn()
        rc, out = run_main(self.cfg, ports)
        self.assertEqual(rc, 0, out)
        self.assertIn("#3 feat/3: 自分の番でない PR なので、会話を終えて作業場を閉じた（worktree は残した）", out)
        self.assertEqual(ports.term.writes, [("prompt", pane["pane_id"], "/exit", False),
                                              ("close_workspace", pane["workspace_id"])])
        self.assertTrue(pathlib.Path(path).exists())
        self.assertIn("feat/3", self.g.local)

    def test_off_turn_pr_with_a_busy_session_or_local_work_is_kept_and_named(self):
        for status, local in (("busy", None), ("idle", "commit"), ("idle", "file")):
            with self.subTest(status=status, local=local):
                self.setUp()
                path, ports, _ = self.off_turn()
                ports.agents = [{**x, "status": status} for x in ports.agents]
                if local == "commit":
                    self.g.commit(path, {}, "x")
                if local == "file":
                    pathlib.Path(path, "draft.py").write_text("x\n")
                    self.g.dirty.add(path)
                rc, out = run_main(self.cfg, ports)
                self.assertIn("#3 feat/3: 自分の番でない PR だが、会話が作業中か手元の作業が有るので会話を残した", out)
                self.assertEqual(ports.term.writes, [])

    def test_off_turn_conversations_dispatch_did_not_open_are_left_alone_and_named(self):
        # 控えが無い・一覧の回の印が無い（--pr で送った物か前の版の物）・送った後に起動した（持ち主が自分で開いた）・起動の時刻が
        # 分からない・会話が 2 つ、のどれも触らず、触らない訳を 1 行に出す（2026-10-20 に、前の版で送った会話が何も出さずに残った）
        for started, record, extra, why in ((100.0, {}, False, "送った記録が無い"),
                                            (100.0, {"at": 200.0}, False, "送った記録に一覧の回の印 via: listing が無い"),
                                            (300.0, None, False, "記録より後に起動された会話"),
                                            (None, None, False, "会話の起動の時刻が分からない"),
                                            (100.0, None, True, "同じ手元に会話が 2 つ開いている")):
            with self.subTest(started=started, record=record, extra=extra):
                self.setUp()
                path, ports, _ = self.off_turn(started=started or 100.0, record=record)
                if started is None:
                    ports.agents = [{k: v for k, v in x.items() if k != "startedAt"} for x in ports.agents]
                if record == {}:
                    self.sent({})
                if extra:
                    ports.agents = list(ports.agents) + [{"cwd": path, "status": "idle", "startedAt": 100000}]
                rc, out = run_main(self.cfg, ports)
                self.assertEqual(ports.term.writes, [])
                self.assertIn("#3 feat/3: 自分の番でない PR だが、dispatch が一覧の回で開いた会話と言い切れないので残した（" + why, out)

    def test_off_turn_pr_whose_materials_hit_the_scan_limit_is_kept_and_named(self):
        # whose-turn の limited に入った PR は、自分の番でないという判定が取りこぼしの上に立つので閉じない
        for dry_run in (False, True):
            with self.subTest(dry_run=dry_run):
                self.setUp()
                path, ports, _ = self.off_turn()
                ports._limited = {3}
                rc, out = run_main(self.cfg, ports, *(["--dry-run"] if dry_run else []))
                self.assertEqual(rc, 0, out)
                self.assertIn("#3 feat/3: 自分の番でないと出たが、whose-turn が材料を取り切れなかった（走査の上限に当たった）ので会話を残した", out)
                self.assertEqual(ports.term.writes, [])

    def test_off_turn_pr_is_closed_when_only_another_pr_hit_the_scan_limit(self):
        path, ports, pane = self.off_turn()
        ports._limited = {4}
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#3 feat/3: 自分の番でない PR なので、会話を終えて作業場を閉じた（worktree は残した）", out)
        self.assertIn(("close_workspace", pane["workspace_id"]), ports.term.writes)

    def test_on_turn_pr_is_not_closed_as_off_turn(self):
        path, ports, _ = self.off_turn()
        ports._prs = [pr(3)]   # 自分の番に居る（相手の新しい返事は無い）
        rc, out = run_main(self.cfg, ports)
        self.assertTrue(line(out, 3).endswith("no_news"), out)
        self.assertEqual(ports.term.writes, [])

    def test_off_turn_conversations_are_not_closed_without_the_full_list(self):
        # whose-turn を読めなければ止まり、--pr・--issue の回は一覧を読まないので、自分の番でない会話を閉じない
        path, ports, _ = self.off_turn()

        def boom(repo):
            raise dispatch.prs.PrsError("whose-turn --json（o/r）が読めない: boom")
        ports.fetch_prs = boom
        rc, out = run_main(self.cfg, ports)
        self.assertEqual(rc, 1)
        self.assertEqual(ports.term.writes, [])
        path, ports, _ = self.off_turn(n=4)
        ports.pr_info = lambda repo, n: {**pr(n), "state": "OPEN", "fork": False}
        rc, out = run_main(self.cfg, ports, "--pr", "1")
        self.assertNotIn("#4", out)
        self.assertFalse([w for w in ports.term.writes if w[0] == "close_workspace"])

    def test_dry_run_names_the_off_turn_conversation_and_closes_nothing(self):
        path, ports, _ = self.off_turn()
        rc, out = run_main(self.cfg, ports, "--dry-run")
        self.assertIn("#3 feat/3: 自分の番でない PR なので、会話を終えて作業場を閉じる（worktree は残す）", out)
        self.assertEqual(ports.term.writes, [])

    def test_only_a_listing_send_is_marked_as_closable_later(self):
        ports = FakePorts([pr(1)], git=self.g)
        run_main(self.cfg, ports)
        ports = FakePorts([], git=self.g)
        ports.pr_info = lambda repo, n: {**pr(n), "state": "OPEN", "fork": False}
        run_main(self.cfg, ports, "--pr", "2")
        sent = json.loads(pathlib.Path(self.root).parent.joinpath("limits", wiring.SENT_FILE).read_text())
        self.assertEqual(sent["o/r#1"].get("via"), "listing")
        self.assertNotIn("via", sent["o/r#2"])

    def test_off_turn_stash_on_the_branch_keeps_the_conversation(self):
        # HEAD が送った時の head のままでも、そのブランチの stash は手元の作業
        path, ports, _ = self.off_turn()
        self.g.stashes.append("On feat/3: wip")   # 書きかけのファイルを stash に入れた（git stash push -u -m wip）
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#3 feat/3: 自分の番でない PR だが、会話が作業中か手元の作業が有るので会話を残した", out)
        self.assertEqual(ports.term.writes, [])

    def test_off_turn_branch_force_pushed_by_the_author_is_not_local_work(self):
        # 作者の force-push で、手元の HEAD（送った時の head）が origin に無くなった。送り直しと同じく、手元で積んだ commit とは見分ける
        self.advance("feat/3")
        path, ports, pane = self.off_turn()
        self.force_pushed("feat/3", self.g.head_sha(path))
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#3 feat/3: 自分の番でない PR なので、会話を終えて作業場を閉じた（worktree は残した）", out)

    def test_off_turn_workspace_with_another_busy_pane_is_named(self):
        path, ports, pane = self.off_turn()
        extra = ports.term.add_pane(pane["workspace_id"], path)
        ports.term.busy.add(extra["pane_id"])
        rc, out = run_main(self.cfg, ports)
        self.assertIn("#3 feat/3: 自分の番でない PR の会話を終えたが、作業場を閉じられなかった", out)
        self.assertNotIn(("close_workspace", pane["workspace_id"]), ports.term.writes)
        self.assertTrue(pathlib.Path(path).exists())


if __name__ == "__main__":
    unittest.main()
