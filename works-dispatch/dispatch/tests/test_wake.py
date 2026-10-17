"""受付の待ち受けと順番待ち（nodes/wake.py・wake_hook.py）と、--ask・--deliver が待ち受けに知らせる道。
git は一時のフォルダの本物、herdr・claude は偽物で回す。"""

import io
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

from . import DISPATCH
from . import test_deliver
from .test_provision import git
import gitx
import herdr as real_herdr
import orders
import role_hook
import wake_hook
from nodes import deliver, provision, role, wake


def write_line(log, record):
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def dead_pid():
    """生きていない処理の番号（試験の中で 1 つ起こして終わらせた物）。"""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class Watch(unittest.TestCase):
    """待ち受けの本体を、時計と待ちを偽物にして回す。台帳への書き込みは待ちの番ごとに差し込む。"""

    def setUp(self):
        self.inbox = tempfile.mkdtemp()
        self.log = os.path.join(self.inbox, wake.LOG)
        self.place = tempfile.mkdtemp()
        self.names = ["co/調べ", "co/前の名前"]
        self.clock = [1000.0]

    def run_watch(self, steps, token="t1", parent=lambda: 7, owner=7, check=None):
        """steps は待ちの番ごとに呼ぶ関数の並び。尽きたら止める（試験が終わらないのを防ぐ）。(終了の値, stderr)。"""
        err, todo = io.StringIO(), list(steps)

        def pause(sec):
            self.clock[0] += sec
            if not todo:
                raise AssertionError("待ち受けが終わらない")
            todo.pop(0)()
        rc = wake.watch(self.inbox, self.place, self.names, "s1", owner, token, err,
                        now=lambda: self.clock[0], pause=pause, parent=parent, check=check)
        return rc, err.getvalue()

    def test_wakes_only_on_its_own_notice_and_says_one_line(self):
        write_line(self.log, wake.notice("co/調べ", "old", "deliver", "/old.md", "古い納品", 1))   # 張る前の行は読まない
        rc, err = self.run_watch([
            lambda: None,
            lambda: write_line(self.log, wake.notice("co/ほか", "x", "deliver", "/x.md", "ほか宛て", 2)),
            lambda: write_line(self.log, {"id": "r", "kind": "ask", "to": {"name": "調べ"}}),   # 送った記録（to が辞書）
            lambda: write_line(self.log, wake.notice("co/前の名前", "d1", "deliver", "/d1.md", "納品です（受付 d1）: 済んだ\n続き", 3)),
        ])
        self.assertEqual((rc, err), (2, "納品です（受付 d1）: 済んだ 続き\n"))
        # 読んだ所が残り、次の待ち受けは同じ行で起こさない
        rc, _ = self.run_watch([lambda: None, lambda: wake.claim(self.inbox, self.place, self.names, "s1", 7, "t3", 0)],
                               token="t2")
        self.assertEqual(rc, 0)

    def test_queued_notice_asks_the_check_and_wakes_with_what_it_hands(self):
        seen = []

        def check():
            seen.append(1)
            return ("wake", "頼みです（受付 q1）") if len(seen) > 1 else None
        rc, err = self.run_watch([lambda: None, lambda: write_line(self.log, wake.notice("co/調べ", "q1", wake.QUEUED, "/q1.md",
                                                                                          None, 1))], check=check)
        self.assertEqual((rc, err, len(seen)), (2, "頼みです（受付 q1）\n", 2))   # 張った時に 1 回、知らせで 1 回

    def test_check_can_end_the_watch_at_the_start(self):
        rc, err = self.run_watch([lambda: None], check=lambda: ("end", None))
        self.assertEqual((rc, err), (0, ""))

    def test_notice_without_text_names_the_kind_and_file(self):
        self.assertEqual(wake.wake_text([{"to": "co/a", "id": "d1", "kind": "deliver", "file": "/in/d1.md"}]),
                         "納品です（受付 d1）: /in/d1.md を読む")

    def test_a_new_watcher_at_the_same_place_ends_the_old_one(self):
        rc, err = self.run_watch([lambda: None, lambda: wake.claim(self.inbox, self.place, self.names, "s1", 7, "new", 0),
                                  lambda: write_line(self.log, wake.notice("co/調べ", "a", "deliver", "/a.md", "納品", 1))])
        self.assertEqual((rc, err), (0, ""))
        self.assertEqual(wake.read_mark(self.inbox, self.place)["token"], "new")   # 新しい物の印は消さない

    def test_ends_and_clears_the_mark_when_the_conversation_process_is_gone(self):
        parents = iter([7, 1])
        rc, err = self.run_watch([lambda: None, lambda: None], parent=lambda: next(parents))
        self.assertEqual((rc, err), (0, ""))
        self.assertIsNone(wake.read_mark(self.inbox, self.place))

    def test_listening_needs_the_name_and_a_living_conversation(self):
        wake.claim(self.inbox, self.place, self.names, "s1", os.getpid(), "t", 0)
        self.assertTrue(wake.has_history(self.inbox, self.place))   # 張ったら跡が残る
        self.assertEqual(wake.listening(self.inbox, "co/前の名前", posix=True)["token"], "t")
        self.assertIsNone(wake.listening(self.inbox, "co/ほか", posix=True))
        wake.claim(self.inbox, self.place, self.names, "s1", dead_pid(), "t", 0)
        self.assertIsNone(wake.listening(self.inbox, "co/調べ", posix=True))   # 会話の処理が居ない
        # Windows は印の更新で見る
        now = time.time()
        self.assertIsNotNone(wake.listening(self.inbox, "co/調べ", now, posix=False))
        self.assertIsNone(wake.listening(self.inbox, "co/調べ", now + wake.FRESH + 1, posix=False))
        wake.release(self.inbox, self.place, "other")   # ほかの待ち受けの token では消えない
        self.assertIsNotNone(wake.read_mark(self.inbox, self.place))
        wake.release(self.inbox, self.place, "t")
        self.assertIsNone(wake.read_mark(self.inbox, self.place))

    def test_queue_hands_out_in_the_order_it_was_put(self):
        for i in ("20261017-000002-bbbbbb", "20261017-000001-aaaaaa"):
            wake.enqueue(self.inbox, self.place, {"id": i, "line": i})
        self.assertEqual([x["id"] for x in wake.queued(self.inbox, self.place)],
                         ["20261017-000001-aaaaaa", "20261017-000002-bbbbbb"])
        self.assertEqual(wake.take(self.inbox, self.place)["id"], "20261017-000001-aaaaaa")
        self.assertEqual(len(wake.queued(self.inbox, self.place)), 1)

    def test_half_written_line_waits_for_its_end(self):
        with open(self.log, "w", encoding="utf-8") as f:
            f.write('{"to": "co/調べ"')
        self.assertEqual(wake.read_new(self.log, 0), ([], 0))

    def test_addresses_take_the_name_then_former_names(self):
        self.assertEqual(wake.addresses("co", {"name": "調べ"}, ["前", "調べ"]), ["co/調べ", "co/前"])
        self.assertEqual(wake.addresses("co", {}, ["前"]), [])


ME = 4242   # 試験の中の、この会話の処理（Claude Code）の番号


class Window:
    """部署の窓の偽物（herdr の口）。"""
    HerdrError = real_herdr.HerdrError

    def __init__(self, cwd, status="done", box="", front=None):
        self.cwd, self.status, self.box, self.writes = cwd, status, box, []
        # 窓の前のプロセス。既定はこの会話の処理（checker が clear_now に渡す me の番号）が居る窓
        self.front = [{"pid": ME, "argv": ["claude"]}] if front is None else front

    def panes(self):
        return [{"pane_id": "p1", "cwd": self.cwd, "agent": "claude"}]

    def front_processes(self, pane):
        return self.front

    def agent(self, pane):
        return {"agent": "claude", "agent_status": self.status}

    def read(self, pane, lines):
        return f"{'─' * 20}\n❯ {self.box}\n{'─' * 20}\n"

    def prompt(self, pane, text, wait):
        self.writes.append(text)

    def send_keys(self, pane, *keys):
        self.writes.append(keys)


class Hook(unittest.TestCase):
    """入口 wake_hook.py: 部署と窓口でだけ待ち、同じ場所の別の会話は待たない。順番待ちを渡し、fresh の部署を空にする。"""

    def setUp(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.src = str(d / "co")
        git("init", "-q", "-b", "main", self.src)
        git("-C", self.src, "commit", "-q", "--allow-empty", "-m", "init")
        self.place = str(d / "dept")
        git("-C", self.src, "worktree", "add", "-q", "-b", "dept/a", self.place)
        self.inbox = deliver.inbox_of(gitx.common_dir(self.src))
        self.env = {"WORKS_DISPATCH_CONFIG": "/none/c.toml"}

    def plan(self, sid="s1", parent=lambda: 7, cwd=None, same=lambda pid: False):
        return wake_hook.plan({"cwd": cwd or self.place, "session_id": sid}, env=self.env, parent=parent, same=same)

    def test_waits_only_in_a_named_department_and_names_the_company(self):
        self.assertIsNone(self.plan())
        provision.mark(self.place, self.src, {"role": "作業"}, gitx)
        self.assertIsNone(self.plan())   # 名前が無ければ宛てられない
        provision.mark(self.place, self.src, {"name": "調べ", "former-names": '["前"]'}, gitx)
        got = self.plan()
        self.assertEqual(got["names"], ["co/調べ", "co/前"])
        self.assertEqual(os.path.realpath(got["inbox"]), os.path.realpath(self.inbox))
        self.assertFalse(got["adopt"])

    def test_the_desk_needs_its_conversation_id(self):
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口"}, gitx)
        self.assertIsNone(self.plan(cwd=self.src))   # 代表の clone のほかの会話に横取りさせない
        provision.mark(self.src, self.src, {"session": "s1"}, gitx)
        self.assertEqual(self.plan(cwd=self.src)["names"], ["co/窓口"])

    def test_another_talk_at_the_place_does_not_wait_but_the_same_process_after_clear_does(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1"}, gitx)
        self.assertIsNone(self.plan(sid="s9"))   # 同じ場所で開いた別の会話
        place = gitx.git_dir(self.place)
        wake.claim(self.inbox, place, ["co/調べ"], "s1", 7, "t", 0)
        self.assertIsNone(self.plan(sid="s9", parent=lambda: 8))   # 別の処理の会話
        self.assertTrue(self.plan(sid="s9")["adopt"])   # 同じ処理が /clear で会話の id を替えた

    def test_the_desk_follows_a_clear_in_its_own_process_without_the_mark(self):
        # 窓口の /clear で前の待ち受けが TERM を受けて印を消しても、--desk が書いた会話の処理の会話なら続きと見る
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s1", "pid": "7"}, gitx)
        self.assertIsNone(self.plan(sid="s9", cwd=self.src))   # 会話の処理が違う（持ち主のほかの会話）
        self.assertTrue(self.plan(sid="s9", cwd=self.src, same=lambda pid: pid == "7")["adopt"])
        # 部署は印で見分ける（部署の場所の会話の処理の番号は書かない）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "pid": "7"}, gitx)
        self.assertIsNone(self.plan(sid="s9", same=lambda pid: True))

    def test_the_wake_text_starts_with_the_new_role_text_when_it_changed(self):
        err = io.StringIO()
        out = wake_hook.WithRole(err, {"session_id": "s1"}, changed=lambda payload: "役が替わった")
        out.write("納品です\n")
        out.write("続き\n")
        self.assertEqual(err.getvalue(), "役が替わった\n\n納品です\n続き\n")
        err = io.StringIO()
        wake_hook.WithRole(err, {}, changed=lambda payload: None).write("納品です\n")
        self.assertEqual(err.getvalue(), "納品です\n")

    def checker(self, payload=None, window=None):
        return wake_hook.checker(self.plan(), payload or {"hook_event_name": "Stop"}, h=window or Window(self.place),
                                 now=lambda: 5, me=lambda: ME)

    def put(self, ask_id, **marks):
        wake.enqueue(self.inbox, gitx.git_dir(self.place), {"id": ask_id, "line": f"頼みです（受付 {ask_id}）",
                                                             "marks": {"ask": ask_id, "boss": "窓口", **marks}})

    def test_hands_the_next_ask_only_after_the_last_one_was_delivered(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "ask": "a0"}, gitx)
        self.put("a1", **{"ask-digest": "d1"})
        self.assertIsNone(self.checker()())   # a0 を納品していない
        provision.mark(self.place, self.src, {"delivered": "a0"}, gitx)
        self.assertEqual(self.checker()(), ("wake", "頼みです（受付 a1）"))
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["ask"], attrs["boss"], attrs["ask-digest"]), ("a1", "窓口", "d1"))
        self.assertEqual(deliver.records(self.inbox)[-1]["kind"], "handed")
        self.assertIsNone(self.checker()())   # 渡した物は順番待ちから消える

    def test_fresh_department_is_cleared_when_it_stops_after_delivering(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, gitx)
        self.put("a1")
        w = Window(self.place)
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(self.checker(window=w)(), ("end", None))   # 渡すのは空にした後の会話の始まりの待ち受け
        self.assertEqual(w.writes[0], deliver.CLEAR)
        self.assertEqual(gitx.worktree_attrs(self.place)["cleared"], "a0")
        self.assertEqual(len(wake.queued(self.inbox, gitx.git_dir(self.place))), 1)
        # 空にした後（SessionStart）は渡す
        got = wake_hook.checker(self.plan(), {"hook_event_name": "SessionStart"}, h=Window(self.place), now=lambda: 5)
        self.assertEqual(got(), ("wake", "頼みです（受付 a1）"))

    def test_fresh_department_is_not_cleared_while_busy_typed_or_waiting_on_background_work(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, gitx)
        for payload, window in (({"hook_event_name": "Stop", "background_tasks": [{"id": "b"}]}, Window(self.place)),
                                ({"hook_event_name": "Stop"}, Window(self.place, status="working")),
                                ({"hook_event_name": "Stop"}, Window(self.place, box="打ちかけ"))):
            self.assertIsNone(self.checker(payload, window)())   # 空にせず、渡す物も無い
            self.assertEqual(window.writes, [])
        self.assertNotIn("cleared", gitx.worktree_attrs(self.place))

    def test_a_resident_talk_is_cleared_at_the_end_of_the_turn_it_marked_a_break(self):
        # 会話を持ち越す部署と窓口は、会話が自分で区切りと印した（--rest）番の終わりに、機械が窓に /clear を打つ（持ち主が手で打たない）
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s1"}, gitx)
        self.put("a1")
        w = Window(self.place)
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(self.checker({"hook_event_name": "Stop", "session_id": "s1"}, w)(), ("end", None))
        self.assertEqual(w.writes[0], deliver.CLEAR)
        self.assertNotIn(wake.REST, gitx.worktree_attrs(self.place))   # 印は 1 度で外れる
        self.assertEqual(len(wake.queued(self.inbox, gitx.git_dir(self.place))), 1)   # 次は空にした後の会話に渡す

    def test_a_break_is_not_cleared_with_an_open_ask_typed_text_or_outside_stop(self):
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s1"}, gitx)
        for payload, window in (({"hook_event_name": "Stop"}, Window(self.place, box="打ちかけ")),   # 持ち主が打っている途中
                                ({"hook_event_name": "Stop"}, Window(self.place, status="working")),
                                ({"hook_event_name": "SessionStart"}, Window(self.place))):
            self.assertIsNone(self.checker(payload, window)())
            self.assertEqual(window.writes, [])
        provision.mark(self.place, self.src, {"ask": "a0"}, gitx)   # 納品していない頼みが在る
        w = Window(self.place)
        self.assertIsNone(self.checker(window=w)())
        self.assertEqual(w.writes, [])
        self.assertEqual(gitx.worktree_attrs(self.place)[wake.REST], "s1")

    def test_a_typed_prompt_takes_the_break_mark_off(self):
        # 人の文で番が始まったら、区切りの印を外す（人と話している途中の会話を空にしない）
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s1"}, gitx)
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s9"})   # 場所のほかの会話の文では外さない
        self.assertEqual(gitx.worktree_attrs(self.place)[wake.REST], "s1")
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s1"})
        self.assertNotIn(wake.REST, gitx.worktree_attrs(self.place))

    def spawner(self, fail=None):
        seen = []

        def spawn(argv, **kw):
            if fail:
                raise fail
            seen.append((argv, kw))
        return seen, spawn

    def test_a_finished_department_starts_retire_apart_from_the_talk_at_the_end_of_the_turn(self):
        # 都度の部署が終わりと印した（--done）番の終わりに、印を外し、--retire を会話から切り離して走らせる（会話を止めるので待たない）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH, wake.FINISHED: "s1"}, gitx)
        seen, spawn = self.spawner()
        w = Window(self.place)
        got = wake_hook.checker(self.plan(), {"hook_event_name": "Stop"}, h=w, now=lambda: 5, spawn=spawn)
        self.assertEqual(got(), ("end", None))
        [(argv, kw)] = seen
        self.assertEqual(argv[2:], ["--retire", "co/調べ"])
        self.assertTrue(kw["start_new_session"])
        self.assertEqual(os.path.realpath(kw["cwd"]), os.path.realpath(self.src))   # 消える部署の場所の外で走らせる
        self.assertTrue(kw["stdout"].name.startswith(os.path.join(self.inbox, wake_hook.RETIRES)))
        self.assertEqual(w.writes, [], "fresh の部署でも /clear は打たない（空にすると印の会話が居なくなる）")
        self.assertNotIn(wake.FINISHED, gitx.worktree_attrs(self.place))   # 印は 1 度で外れる

    def test_a_finished_mark_waits_for_delivery_background_work_and_the_stop_of_the_turn(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a0", wake.FINISHED: "s1"}, gitx)
        seen, spawn = self.spawner()

        def check(payload):
            return wake_hook.checker(self.plan(), payload, h=Window(self.place), now=lambda: 5, spawn=spawn)()
        self.assertIsNone(check({"hook_event_name": "Stop"}))   # a0 を納品していない
        provision.mark(self.place, self.src, {"delivered": "a0"}, gitx)
        self.assertIsNone(check({"hook_event_name": "Stop", "background_tasks": [{"id": "b"}]}))   # 裏の処理が残る
        self.assertIsNone(check({"hook_event_name": "SessionStart"}))   # 番の終わりでない
        self.assertEqual(seen, [])
        self.assertEqual(gitx.worktree_attrs(self.place)[wake.FINISHED], "s1")

    def test_a_queued_ask_is_handed_instead_of_retiring_and_takes_the_mark_off(self):
        # 終わりと印した後に追いの頼みが積まれたら、畳まずに渡す（終わりは、その頼みを済ませてから印し直す）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a0", "delivered": "a0",
                                              wake.FINISHED: "s1"}, gitx)
        self.put("a1")
        seen, spawn = self.spawner()
        got = wake_hook.checker(self.plan(), {"hook_event_name": "Stop"}, h=Window(self.place), now=lambda: 5, spawn=spawn)
        self.assertEqual(got(), ("wake", "頼みです（受付 a1）"))
        self.assertEqual(seen, [])
        self.assertNotIn(wake.FINISHED, gitx.worktree_attrs(self.place))

    def test_a_retire_that_cannot_start_leaves_the_room_with_the_reason(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", wake.FINISHED: "s1"}, gitx)
        _, spawn = self.spawner(fail=OSError("no python"))
        got = wake_hook.checker(self.plan(), {"hook_event_name": "Stop"}, h=Window(self.place), now=lambda: 5, spawn=spawn)
        self.assertIsNone(got())
        attrs = gitx.worktree_attrs(self.place)
        self.assertNotIn(wake.FINISHED, attrs)   # 打ち直しはしない
        self.assertIn("no python", attrs[wake.RETIRE_KEPT])

    def test_a_typed_prompt_takes_the_finished_mark_off(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", wake.FINISHED: "s1"}, gitx)
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s9"})
        self.assertEqual(gitx.worktree_attrs(self.place)[wake.FINISHED], "s1")
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s1"})
        self.assertNotIn(wake.FINISHED, gitx.worktree_attrs(self.place))

    def test_the_window_is_the_pane_of_this_talk_when_the_place_has_several(self):
        # 本社には持ち主のほかの会話も居るので、ペインの会話の印で窓口の窓を決める
        class Many(Window):
            def panes(self):
                return [{"pane_id": "p1", "cwd": self.cwd, "agent": "claude", "agent_session": {"value": "s0"}},
                        {"pane_id": "p2", "cwd": self.cwd, "agent": "claude", "agent_session": {"value": "s1"}}]
        self.assertEqual(wake_hook.own_window(self.place, Many(self.place), "s1"), "p2")
        self.assertIsNone(wake_hook.own_window(self.place, Many(self.place), "s7"))   # 結べなければ打たない
        self.assertEqual(wake_hook.own_window(self.place, Window(self.place), "s7"), "p1")   # 場所に 1 つなら、それ

    def test_clear_goes_only_to_a_window_where_this_talk_is_seen_running(self):
        # 会話を消す打ち込みは、窓の前のプロセスにこの会話が居ると確かめたときだけ打つ（印も、場所だけの代わりも使わない）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "ask": "a1", "delivered": "a1", "fresh": role.FRESH,
                                              "job": "abcd1234"}, gitx)
        stranger = Window(self.place, front=[{"pid": ME + 1, "argv": ["claude"]}])
        stranger.panes = lambda: [{"pane_id": "p1", "cwd": self.place, "agent": "claude", "agent_session": {"value": "s1"}}]
        self.assertIsNone(self.checker(window=stranger)())   # 印が合っても、前に居るのが別の会話なら打たない
        self.assertEqual(stranger.writes, [])
        attached = Window(self.place, front=[{"pid": ME + 1, "argv": ["claude", "attach", "abcd1234"]}])   # 裏の会話を開いた窓
        self.assertEqual(wake_hook.talk_window(self.place, attached, [ME], ["abcd1234"]), "p1")
        self.assertIsNone(wake_hook.talk_window(self.place, attached, [ME], ["zzzz9999"]))

    def test_a_pane_of_another_place_is_not_the_window_even_with_this_talk_mark(self):
        # herdr の印は別の部署の会話の id のまま残ることがある（2026-10-17 に my_notes で、ノートの手入れの待ち受けが印の合った
        # 調べものの窓に /clear を打った）。場所の違う窓は、印が合っても打ち先にしない
        other = tempfile.mkdtemp()

        class Stale(Window):
            def panes(self):
                return [{"pane_id": "p9", "cwd": other, "agent": "claude", "agent_session": {"value": "s1"}},
                        {"pane_id": "p1", "cwd": self.cwd, "agent": "claude", "agent_session": {"value": "s-old"}}]

        class Alone(Window):
            def panes(self):
                return [{"pane_id": "p9", "cwd": other, "agent": "claude", "agent_session": {"value": "s1"}}]
        self.assertEqual(wake_hook.own_window(self.place, Stale(self.place), "s1"), "p1")
        self.assertIsNone(wake_hook.own_window(self.place, Alone(self.place), "s1"))
        os.makedirs(os.path.join(self.place, "sub"), exist_ok=True)   # 会話が作業場の下のフォルダに居ても、同じ場所と見る
        self.assertEqual(wake_hook.own_window(os.path.join(self.place, "sub"), Stale(self.place), "s1"), "p1")

    def test_a_typed_prompt_pauses_the_watcher(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a1", "waiting": "a1"}, gitx)
        place = gitx.git_dir(self.place)
        wake.claim(self.inbox, place, ["co/調べ"], "s1", os.getppid(), "t", 0)
        with mock.patch.dict(os.environ, self.env):
            wake_hook.main(["--pause"], io.StringIO(json.dumps({"cwd": self.place, "session_id": "s1"})))
        self.assertEqual(wake.read_mark(self.inbox, place)["token"], "paused")
        # 裏で走る --pause は答え待ちの印に触らない（同じ番の中で会話が打った --wait より後に走りうる）
        self.assertEqual(gitx.worktree_attrs(self.place)["waiting"], "a1")

    def test_a_typed_prompt_takes_the_wait_mark_off_before_the_talk_reads_it(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a1", "waiting": "a1",
                                              "waiting-why": "持ち主の答え"}, gitx)
        with mock.patch.dict(os.environ, self.env):
            self.assertEqual(wake_hook.main(["--resume"], io.StringIO(json.dumps({"cwd": self.place, "session_id": "s1"}))), 0)
        attrs = gitx.worktree_attrs(self.place)
        self.assertNotIn("waiting", attrs)
        self.assertNotIn("waiting-why", attrs)

    def test_hook_process_wakes_on_its_notice_and_is_quiet_elsewhere(self):
        p = subprocess.run([sys.executable, str(DISPATCH / "wake_hook.py")], input=json.dumps({"cwd": tempfile.mkdtemp()}),
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual((p.returncode, p.stdout, p.stderr), (0, "", ""))
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ"}, gitx)
        env = {**os.environ, **self.env, "TMPDIR": tempfile.mkdtemp()}
        role_hook.remember("s1", role_hook.text_for(self.place, env), env)   # 会話の始まりに足した役の文のまま（替わっていない）
        proc = subprocess.Popen([sys.executable, str(DISPATCH / "wake_hook.py")], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8", env=env)
        proc.stdin.write(json.dumps({"cwd": self.place, "session_id": "s1", "hook_event_name": "Stop"}))
        proc.stdin.close()
        place = gitx.git_dir(self.place)
        for _ in range(100):
            if wake.read_mark(self.inbox, place):
                break
            time.sleep(0.1)
        self.assertIsNotNone(wake.read_mark(self.inbox, place), "待ち受けの印が出ない")
        time.sleep(wake.GRACE + 0.5)   # 読み始めの所（台帳の終わり）を決めた後に書く
        deliver.log(self.inbox, wake.notice("co/調べ", "d1", "deliver", "/d1.md", "納品です（受付 d1）", 1))
        try:
            rc = proc.wait(30)
        finally:
            proc.kill()
        self.assertEqual((rc, proc.stderr.read()), (2, "納品です（受付 d1）\n"))
        proc.stdout.close()
        proc.stderr.close()

    def test_plugin_declares_the_waiter_on_stop_and_session_start_and_the_pause_on_prompts(self):
        hooks = json.loads((DISPATCH.parent / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        for event in ("Stop", "SessionStart"):
            (h,) = [h for g in hooks[event] for h in g["hooks"] if h.get("asyncRewake")]
            self.assertIn('"${CLAUDE_PLUGIN_ROOT}/dispatch/wake_hook.py"', h["command"])
            # 持ち時間の既定（600 秒）では手の空いた会話の待ち受けがすぐ切れるので、長く取る
            self.assertGreaterEqual(h["timeout"], 86400)
        prompt = {h["command"].rsplit(" ", 1)[-1]: h for g in hooks["UserPromptSubmit"] for h in g["hooks"]
                  if "wake_hook.py" in h["command"]}
        self.assertEqual(set(prompt), {"--resume", "--pause"})
        # 印を外すのは会話が文を読む前（裏で走らせると、同じ番の中で打った --wait の印を後から外しうる）
        self.assertFalse(prompt["--resume"].get("async"))
        self.assertTrue(prompt["--pause"]["async"])   # 待ち受けを止めるのは裏で（人の入力を遅らせない）


class WakeFlow(unittest.TestCase):
    """--ask と --deliver が、宛先の待ち受けの居る部署には窓に打たずに台帳の知らせで届ける。場の作りは Flow の物を借りる
    （継ぐと、その試験が二度走る）。"""

    Flow = test_deliver.Flow
    setUp, main, prompts, ask_then_summary, shape = Flow.setUp, Flow.main, Flow.prompts, Flow.ask_then_summary, Flow.shape
    del Flow

    def listen(self, name, place, owner=None):
        to = wake.address(orders.inbox_company(self.inbox, os.path.dirname(self.cfg)), name)
        wake.claim(self.inbox, place, [to], "s", owner or os.getpid(), "t", time.time())
        return to

    def dept_place(self):
        return gitx.git_dir(self.place)

    def test_ask_to_a_listening_department_queues_and_says_so(self):
        to = self.listen("調べ", self.dept_place())
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "これを調べて")
        self.assertEqual(rc, 0, out)
        self.assertEqual([w for w in self.ports.herdr.writes if w[0] in ("prompt", "run")], [])
        notice, rec = deliver.records(self.inbox)
        self.assertEqual((notice["to"], notice["kind"], notice["id"]), (to, wake.QUEUED, rec["id"]))
        self.assertEqual((rec["status"], rec["to"]["wake"]), ("queued", to))
        (item,) = wake.queued(self.inbox, self.dept_place())
        self.assertIn("desk から）: これを調べて 終わったら、要約を", item["line"])
        self.assertEqual((item["marks"]["ask"], item["marks"]["boss"]), (rec["id"], "desk"))
        self.assertNotIn("ask", gitx.worktree_attrs(self.place))   # 属性は待ち受けが渡すときに書く
        self.assertIn("順番待ちに積んだ（1 件目。待ち受けが渡す）", out)

    def test_the_same_ask_twice_returns_the_first_number(self):
        self.listen("調べ", self.dept_place())
        self.assertEqual(self.main(self.src, "--ask", "調べ", "--text", "これを調べて")[0], 0)
        first = wake.queued(self.inbox, self.dept_place())[0]["id"]
        self.ports.now = lambda: 99
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "  これを調べて  ")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"頼み {first} → ", out)
        self.assertIn("同じ中身の頼みが順番待ちに積まれている", out)
        self.assertEqual(len(wake.queued(self.inbox, self.dept_place())), 1)

    def test_a_department_busy_with_an_ask_gets_the_next_one_queued(self):
        # 待ち受けの跡は在るが今は会話の処理が見えない。前の頼みを納品していない
        provision.mark(self.place, self.src, {"ask": "a0", "boss": "desk"}, gitx)
        self.listen("調べ", self.dept_place(), owner=dead_pid())
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "次の頼み")
        self.assertEqual(rc, 0, out)
        self.assertIn("順番待ちに積んだ（1 件目。今の頼みの納品の後に待ち受けが渡す）", out)
        self.assertEqual(self.prompts(), [])

    def test_an_idle_department_without_a_living_waiter_gets_the_line_typed(self):
        self.listen("調べ", self.dept_place(), owner=dead_pid())   # 7 日の持ち時間が尽きた・待ち受けの誤りなど
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "これを調べて")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.prompts()), 1)
        self.assertEqual(wake.queued(self.inbox, self.dept_place()), [])

    def test_ask_dry_run_names_the_queue(self):
        self.listen("調べ", self.dept_place())
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("順番待ちに積む（1 件目。待ち受けが渡す）", out)
        self.assertEqual((deliver.records(self.inbox), wake.queued(self.inbox, self.dept_place())), ([], []))

    def queue_two(self):
        """順番待ちに 2 件積み、(先の件, 後の件) を返す。"""
        self.listen("調べ", self.dept_place())
        self.assertEqual(self.main(self.src, "--ask", "調べ", "--text", "先の頼み")[0], 0)
        self.ports.now = lambda: 99
        self.assertEqual(self.main(self.src, "--ask", "調べ", "--text", "急ぎの頼み")[0], 0)
        return wake.queued(self.inbox, self.dept_place())

    def test_take_pulls_a_later_ask_ahead_and_the_department_receives_it_now(self):
        # 積んだ順を飛ばして、急ぎの頼みを今受ける（2d707e。順番待ちのファイルを手で動かさない）
        first, urgent = self.queue_two()
        rc, out = self.main(self.place, "--take", urgent["id"])
        self.assertEqual(rc, 0, out)
        self.assertIn(urgent["line"], out)
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, self.dept_place())], [first["id"]])
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["ask"], attrs["boss"]), (urgent["id"], "desk"))   # 待ち受けが渡すときと同じ属性
        taken = [r for r in deliver.records(self.inbox) if r.get("kind") == "taken"]
        self.assertEqual([(r["id"], r["skipped"]) for r in taken], [(urgent["id"], [first["id"]])])

    def test_take_waits_until_the_current_ask_is_delivered_and_only_takes_its_own_queue(self):
        first, urgent = self.queue_two()
        provision.mark(self.place, self.src, {"ask": "a0", "boss": "desk"}, gitx)
        rc, out = self.main(self.place, "--take", urgent["id"])
        self.assertEqual(rc, 2, out)
        self.assertIn("受付 a0 をまだ納品していない", out)
        provision.mark(self.place, self.src, {"delivered": "a0"}, gitx)
        rc, out = self.main(self.src, "--take", urgent["id"])   # 本社（窓口）の順番待ちには無い
        self.assertEqual(rc, 2, out)
        self.assertEqual(len(wake.queued(self.inbox, self.dept_place())), 2)

    def test_take_with_ask_hands_it_on_with_the_same_number_and_asker_and_puts_it_back_on_failure(self):
        # 担当が手一杯のとき、受け持ちの名前の付いた作業へ回す。納品は元の頼み元に返るよう、受付番号と頼み元を渡す
        first, urgent = self.queue_two()
        seen = []

        def fake_ask(a, ports, cwd, task):
            seen.append(a)
            return rc_of_ask
        rc_of_ask = 1
        with mock.patch.object(orders, "ask", fake_ask):
            rc, out = self.main(self.place, "--take", urgent["id"], "--ask", "作業", "--task", "調べ：急ぎ", "--branch", "b/x")
        self.assertEqual(rc, 1, out)
        self.assertIn("元の順番待ちの同じ場所に戻した", out)
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, self.dept_place())], [first["id"], urgent["id"]])
        rc_of_ask = 0
        with mock.patch.object(orders, "ask", fake_ask):
            rc, out = self.main(self.place, "--take", urgent["id"], "--ask", "作業", "--task", "調べ：急ぎ", "--branch", "b/x")
        self.assertEqual(rc, 0, out)
        a = seen[-1]
        self.assertEqual((a.ask_id, a.brief, a.text, a.task), (urgent["id"], urgent["file"], None, "調べ：急ぎ"))
        self.assertEqual(a.from_boss["boss"], "desk")
        # 回す側の添え書きは、元の本文の前に置く
        with mock.patch.object(orders, "ask", fake_ask):
            rc, out = self.main(self.place, "--take", first["id"], "--ask", "作業", "--task", "調べ：先", "--branch", "b/y",
                                "--text", "割り振りが回した")
        self.assertEqual(rc, 0, out)
        self.assertEqual(seen[-1].text, None)
        self.assertRegex(pathlib.Path(seen[-1].brief).read_text(encoding="utf-8"), r"^割り振りが回した\n\n---\n\n.*先の頼み")
        self.assertNotIn("ask", a.from_boss)
        self.assertEqual(wake.queued(self.inbox, self.dept_place()), [])
        taken = [r for r in deliver.records(self.inbox) if r.get("kind") == "taken"]
        self.assertEqual([(r["id"], r["to"], r["name"]) for r in taken], [(urgent["id"], "作業", "調べ：急ぎ"), (first["id"], "作業", "調べ：先")])

    def test_withdraw_drops_an_ask_and_leaves_it_in_the_ledger(self):
        first, urgent = self.queue_two()
        rc, out = self.main(self.place, "--withdraw", first["id"], "--dry-run")
        self.assertEqual((rc, len(wake.queued(self.inbox, self.dept_place()))), (0, 2), out)
        rc, out = self.main(self.place, "--withdraw", first["id"])
        self.assertEqual(rc, 0, out)
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, self.dept_place())], [urgent["id"]])
        self.assertEqual([r["id"] for r in deliver.records(self.inbox) if r.get("kind") == "withdrawn"], [first["id"]])
        rc, out = self.main(self.place, "--withdraw", first["id"])
        self.assertEqual(rc, 2, out)
        self.assertIn("どの順番待ちにも無い", out)

    def test_forward_closes_the_held_ask_without_waking_its_asker_and_links_it_in_the_ledger(self):
        # 窓口が受けた頼みを部署へ回しただけなら、頼み元（社長室）の会話を起こさない。回した先は台帳にだけ結ぶ
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "回す頼み", "--forward")
        self.assertEqual(rc, 2, out)
        self.assertIn("回す元の頼みが無い", out)
        provision.mark(self.src, self.src, {"role": "窓口", "name": "desk", "ask": "a0", "boss": "社長室", "boss-inbox": self.inbox}, gitx)
        to = self.listen("調べ", self.dept_place())
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "回す頼み", "--forward", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("回した元: 受付 a0 を閉じ", out)
        self.assertEqual((deliver.records(self.inbox), gitx.worktree_attrs(self.src).get("delivered")), ([], None))
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "回す頼み", "--forward")
        self.assertEqual(rc, 0, out)
        self.assertIn("回した元の受付 a0 を閉じた", out)
        (item,) = wake.queued(self.inbox, self.dept_place())
        self.assertEqual(item["marks"]["boss"], "desk")   # 回した先の納品は、回した側（窓口）に返る
        (link,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "forwarded"]   # 同じ受付箱には 1 行だけ
        self.assertEqual((link["id"], link["child"], link["to"]["name"], link["boss"]["name"]), ("a0", item["id"], "調べ", "社長室"))
        self.assertEqual([r["to"] for r in deliver.records(self.inbox) if isinstance(r.get("to"), str)], [to])   # 社長室への知らせは無い
        self.assertEqual(gitx.worktree_attrs(self.src)["delivered"], "a0")
        # 閉じた後は、もう回す元の頼みが無い
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "別の頼み", "--forward")
        self.assertEqual(rc, 2, out)
        self.assertEqual(len(wake.queued(self.inbox, self.dept_place())), 1)

    def test_forward_to_a_window_without_a_waiter_closes_the_held_ask_once_the_line_is_sent(self):
        provision.mark(self.src, self.src, {"role": "窓口", "name": "desk", "ask": "a0", "boss": "社長室"}, gitx)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "回す頼み", "--forward")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.prompts()), 1)
        (link,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "forwarded"]
        self.assertEqual(link["child"], gitx.worktree_attrs(self.place)["ask"])
        self.assertEqual(gitx.worktree_attrs(self.src)["delivered"], "a0")

    def test_forward_does_not_close_the_held_ask_when_the_ask_did_not_reach(self):
        provision.mark(self.src, self.src, {"role": "窓口", "name": "desk", "ask": "a0", "boss": "社長室"}, gitx)
        provision.mark(self.place, self.src, {"ask": "a9", "boss": "ほか"}, gitx)   # 待ち受けの居ない部署が前の頼みを納品していない
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "回す頼み", "--forward")
        self.assertEqual(rc, 2, out)
        self.assertNotIn("delivered", gitx.worktree_attrs(self.src))
        self.assertEqual([r for r in deliver.records(self.inbox) if r.get("kind") == "forwarded"], [])
        rc, out = self.main(self.src, "--take", "x", "--ask", "調べ", "--forward")
        self.assertEqual(rc, 2, out)
        self.assertIn("--forward は --ask と一緒にだけ使う", out)

    def test_a_machine_role_cannot_be_asked(self):
        self.shape('[[roles]]\nname = "配布"\nmachine = true\n')
        rc, out = self.main(self.src, "--ask", "配布", "--text", "配って", "--task", "x", "--branch", "b/x")
        self.assertEqual(rc, 2, out)
        self.assertIn("機械だけの役", out)

    def test_deliver_to_a_listening_asker_needs_no_window(self):
        summary = self.ask_then_summary(test_deliver.GOOD)
        to = self.listen("desk", gitx.git_dir(self.src))
        self.ports.herdr._panes = [p for p in self.ports.herdr._panes if p["pane_id"] != self.desk]   # 頼み元の窓が無くても届く
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.prompts(), [])
        notice, rec = deliver.records(self.inbox)[-2:]
        self.assertEqual((notice["to"], notice["kind"], notice["file"]), (to, "deliver", rec["file"]))
        self.assertIn("【結論】直した。", notice["text"])
        self.assertEqual((rec["status"], rec["to"]["wake"]), ("sent", to))
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual(attrs["delivered"], attrs["ask"])


    def test_deliver_finds_the_asker_by_its_talk_when_the_name_misses(self):
        # 前の版が会話の一覧の名前（my-notes-d7）を頼み元に書いた部署: 名前では待ち受けが引けないので、頼んだ会話の id で引く
        summary = self.ask_then_summary(test_deliver.GOOD)
        provision.mark(self.place, self.src, {"boss": "my-notes-d7"}, gitx)
        to = wake.address(orders.inbox_company(self.inbox, os.path.dirname(self.cfg)), "段取り")
        wake.claim(self.inbox, gitx.git_dir(self.src), [to], "s-desk", os.getpid(), "t", time.time())
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.prompts(), [])
        notice, rec = deliver.records(self.inbox)[-2:]
        self.assertEqual((notice["to"], rec["to"]["wake"]), (to, to))


if __name__ == "__main__":
    unittest.main()
