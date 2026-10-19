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
import health
import herdr as real_herdr
import orders
import role_hook
import wake_hook
from nodes import deliver, provision, role, tree, wake


def write_line(log, record):
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")


def dead_pid():
    """生きていない処理の番号（試験の中で 1 つ起動して終わらせた物）。"""
    p = subprocess.Popen([sys.executable, "-c", "pass"])
    p.wait()
    return p.pid


class Watch(unittest.TestCase):
    """待ち受けの本体を、時計と待ちを偽物にして回す。台帳への書き込みは待ちのターンごとに差し込む。"""

    def setUp(self):
        self.inbox = tempfile.mkdtemp()
        self.log = os.path.join(self.inbox, wake.LOG)
        self.place = tempfile.mkdtemp()
        self.names = ["co/調べ", "co/前の名前"]
        self.clock = [1000.0]

    def run_watch(self, steps, token="t1", parent=lambda: 7, owner=7, check=None, ready=None):
        """steps は待ちのターンごとに呼ぶ関数の並び。尽きたら止める（試験が終わらないのを防ぐ）。(終了の値, stderr)。"""
        err, todo = io.StringIO(), list(steps)

        def pause(sec):
            self.clock[0] += sec
            if not todo:
                raise AssertionError("待ち受けが終わらない")
            todo.pop(0)()
        rc = wake.watch(self.inbox, self.place, self.names, "s1", owner, token, err,
                        now=lambda: self.clock[0], pause=pause, parent=parent, check=check, ready=ready)
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
        # 読んだ所が残り、次の待ち受けは同じ行で起動しない
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

    def test_a_note_on_the_held_ask_wakes_with_its_line_even_while_an_ask_is_undelivered(self):
        # 足しは納品と同じに字をそのまま渡す（check は未納品なら None を返すが、足しは待たない）
        rc, err = self.run_watch([lambda: None, lambda: write_line(self.log, wake.notice("co/調べ", "n1", wake.NOTE, "/n1.md",
                                                                                          "頼みの足しです（受付 a0 への）", 1))],
                                 check=lambda: None)
        self.assertEqual((rc, err), (2, "頼みの足しです（受付 a0 への）\n"))

    def test_waits_until_the_talk_can_take_text_without_losing_what_came_meanwhile(self):
        # 起き切る前の会話に渡した字は落ちる（my_notes の受付 4bae53）。受けられるまで check も台帳も見ず、受けられたら同じ行で起動する
        up, seen = [False], []

        def check():
            seen.append(1)
            return ("wake", "頼みです（受付 q1）") if len(seen) > 1 else None
        rc, err = self.run_watch([
            lambda: write_line(self.log, wake.notice("co/調べ", "d1", "deliver", "/d1.md", "納品です（受付 d1）", 1)),
            lambda: write_line(self.log, wake.notice("co/調べ", "q1", wake.QUEUED, "/q1.md", None, 2)),
            lambda: self.assertEqual(seen, []),
            lambda: up.__setitem__(0, True),
        ], check=check, ready=lambda: up[0])
        # 同じ回に知らせと順番待ちが来たら、知らせだけを渡し、順番待ちはそのターンの終わりに見る（知らせを受ける前に空にしない）
        self.assertEqual((rc, err, len(seen)), (2, "納品です（受付 d1）\n", 1))

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
        self.assertIsNone(wake.read_mark(self.inbox, self.place))   # 死んだ印は見つけたときに消す
        # Windows は印の更新で見る（消さない）
        wake.claim(self.inbox, self.place, self.names, "s1", dead_pid(), "t", 0)
        now = time.time()
        self.assertIsNotNone(wake.listening(self.inbox, "co/調べ", now, posix=False))
        self.assertIsNone(wake.listening(self.inbox, "co/調べ", now + wake.FRESH + 1, posix=False))
        wake.release(self.inbox, self.place, "other")   # ほかの待ち受けの token では消えない
        self.assertIsNotNone(wake.read_mark(self.inbox, self.place))
        wake.release(self.inbox, self.place, "t")
        self.assertIsNone(wake.read_mark(self.inbox, self.place))

    @unittest.skipIf(os.name == "nt", "死んだ印を消すのは POSIX だけ")
    def test_a_dead_mark_is_not_removed_while_a_new_one_is_being_written(self):
        import threading
        wake.claim(self.inbox, self.place, self.names, "s1", dead_pid(), "old", 0)
        path = wake.mark_path(self.inbox, self.place)
        with wake._mark_lock(path):   # 新しい待ち受けが印を書いている間
            t = threading.Thread(target=wake._drop_dead, args=(path, "old"))
            t.start()
            t.join(0.3)
            self.assertTrue(t.is_alive())   # 消す側は錠を待つ
            wake._replace(path, json.dumps({"token": "new"}))
        t.join(5)
        self.assertEqual(wake.read_mark(self.inbox, self.place)["token"], "new")

    def test_the_ask_lock_lets_one_holder_at_a_time(self):
        import threading
        got = []

        def other():
            with wake.ask_lock(self.inbox, self.place):
                got.append("other")
        with wake.ask_lock(self.inbox, self.place):
            t = threading.Thread(target=other)
            t.start()
            t.join(0.3)
            self.assertEqual(got, [])   # 持っている間は待つ
            got.append("first")
        t.join(5)
        self.assertEqual(got, ["first", "other"])
        with wake.ask_lock(None, self.place):   # 受付箱の無い部署（前の版）では何もしない
            pass

    def test_stalled_needs_a_queue_a_delivered_ask_and_no_running_watcher(self):
        # 会話は生きているのに待ち受けの台本が居ない（2026-10-17 に my_notes のノートの手入れで約 70 分止まった形）
        def mark(pid):
            os.makedirs(os.path.dirname(wake.mark_path(self.inbox, self.place)), exist_ok=True)
            with open(wake.mark_path(self.inbox, self.place), "w", encoding="utf-8") as f:
                json.dump({"names": self.names, "session": "s1", "owner": os.getpid(), "pid": pid, "token": "t", "since": 0}, f)
        done = {"ask": "a0", "delivered": "a0"}
        mark(dead_pid())
        self.assertFalse(wake.stalled(self.inbox, self.place, done, posix=True))   # 順番待ちが無い
        wake.enqueue(self.inbox, self.place, {"id": "a1", "line": "a1"})
        self.assertTrue(wake.stalled(self.inbox, self.place, done, posix=True))
        self.assertTrue(wake.stalled(self.inbox, self.place, {}, posix=True))   # 頼みを受けたことの無い部署
        self.assertIsNotNone(wake.listening(self.inbox, "co/調べ", posix=True))   # 送る側は居ると見る
        self.assertFalse(wake.stalled(self.inbox, self.place, {"ask": "a0"}, posix=True))   # ターンの終わりに張られる
        mark(os.getpid())
        self.assertFalse(wake.stalled(self.inbox, self.place, done, posix=True))   # 待ち受けが動いている
        now = time.time()   # Windows は印の更新で見る
        self.assertFalse(wake.stalled(self.inbox, self.place, done, now, posix=False))
        self.assertTrue(wake.stalled(self.inbox, self.place, done, now + wake.FRESH + 1, posix=False))
        os.unlink(wake.mark_path(self.inbox, self.place))
        self.assertTrue(wake.stalled(self.inbox, self.place, done, posix=True))
        line = "\n".join(tree.lines([{"name": "co", "root": "/co", "info_source": None, "description": None, "skills": [],
                                       "problems": [], "departments": [
                                           {"head_office": False, "state": "done", "sessions": 1, "name": "調べ", "role": None,
                                            "account": None, "boss": None, "panes": [], "branch": "b", "queue": 1,
                                            "queue_dir": "/q", "stalled": True}]}]))
        self.assertIn("順番待ち 1 件（/q）  ! 渡す待ち受けが居ない（--nudge 調べ で動かす）", line)

    def test_held_is_the_last_hold_of_the_place_while_its_watcher_runs(self):
        # 待ち受けは居るが渡さずに待っている（2026-10-17 の割り振り）。台帳のその場所の最後の行が held のときだけ
        cwd = tempfile.mkdtemp()
        wake.claim(self.inbox, self.place, self.names, "s1", os.getpid(), "t", 0)
        write_line(self.log, {"id": "a1", "kind": "held", "place": cwd, "session": "s1", "detail": "窓を確かめられない"})
        self.assertIsNone(wake.held(self.inbox, cwd, self.place))   # 順番待ちが無い
        wake.enqueue(self.inbox, self.place, {"id": "a2", "line": "a2"})
        self.assertEqual(wake.held(self.inbox, cwd, self.place), "窓を確かめられない")
        self.assertEqual(wake.held(self.inbox, os.path.dirname(cwd) + os.sep + os.path.basename(cwd), self.place),
                         "窓を確かめられない")
        self.assertIsNone(wake.held(self.inbox, tempfile.mkdtemp(), self.place))   # ほかの場所の行
        self.assertIsNone(wake.held(self.inbox, cwd, self.place, {"ask": "a9"}))   # 取った頼みをまだ納品していない（--take）
        wake.claim(self.inbox, self.place, self.names, "s2", os.getpid(), "t", 0)
        self.assertIsNone(wake.held(self.inbox, cwd, self.place))   # 前の会話の行（/clear で会話が替わった）
        wake.claim(self.inbox, self.place, self.names, "s1", os.getpid(), "t", 0)
        write_line(self.log, {"id": "a1", "kind": "handed", "place": cwd, "session": "s1"})
        self.assertIsNone(wake.held(self.inbox, cwd, self.place))   # 渡した後
        write_line(self.log, {"id": "a2", "kind": "held", "place": cwd, "session": "s1", "detail": "x"})
        os.unlink(wake.mark_path(self.inbox, self.place))
        self.assertIsNone(wake.held(self.inbox, cwd, self.place))   # 待ち受けが居ないのは stalled の方
        line = "\n".join(tree.lines([{"name": "co", "root": "/co", "info_source": None, "description": None, "skills": [],
                                       "problems": [], "departments": [
                                           {"head_office": False, "state": "done", "sessions": 1, "name": "調べ", "role": None,
                                            "account": None, "boss": None, "panes": [], "branch": "b", "queue": 1,
                                            "queue_dir": "/q", "stalled": False, "held": "x"}]}]))
        self.assertIn("順番待ち 1 件（/q）  ! 渡さずに待っている（x）（--nudge 調べ で動かす）", line)
        line = "\n".join(tree.lines([{"name": "co", "root": "/co", "info_source": None, "description": None, "skills": [],
                                       "problems": [], "departments": [
                                           {"head_office": False, "state": "done", "sessions": 1, "name": "調べ", "role": None,
                                            "account": None, "boss": None, "panes": [], "branch": "b", "no_talk_id": True}]}]))
        self.assertIn("! 会話の id（company.session）が無い（窓の会話が落ちたとき", line)

    def test_only_notice_kinds_with_a_text_address_wake_the_talk(self):
        # 記録の行に字の to を書いても、空の知らせで会話を再開させない（c52730 の 3）
        self.assertTrue(wake.mine({"to": "co/調べ", "kind": "deliver"}, self.names))
        self.assertFalse(wake.mine({"to": "co/調べ", "kind": "moved"}, self.names))
        self.assertFalse(wake.mine({"to": {"name": "調べ"}, "kind": "deliver"}, self.names))

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
        self.assertEqual(wake.read_new(self.log, 0), ([], 0, []))

    def test_addresses_take_the_name_then_former_names(self):
        self.assertEqual(wake.addresses("co", {"name": "調べ"}, ["前", "調べ"]), ["co/調べ", "co/前"])
        self.assertEqual(wake.addresses("co", {}, ["前"]), [])


ME = 4242   # 試験の中の、この会話の処理（Claude Code）の番号


class Window:
    """部署の窓の偽物（herdr の口）。"""
    HerdrError = real_herdr.HerdrError

    def __init__(self, cwd, status="done", box="", front=None, on_clear=None):
        self.cwd, self.status, self.box, self.writes, self.on_clear = cwd, status, box, [], on_clear
        # 窓の前のプロセス。既定はこの会話の処理（checker が clear_now に渡す me の番号）が居る窓
        self.front = [{"pid": ME, "argv": ["claude"]}] if front is None else front

    def panes(self):
        return [{"pane_id": "p1", "cwd": self.cwd, "agent": "claude"}]

    def front_processes(self, pane):
        return self.front

    def agent(self, pane):
        return {"agent": "claude", "agent_status": self.status}

    def read(self, pane, lines, ansi=False):
        return f"{'─' * 20}\n❯ {self.box}\n{'─' * 20}\n"

    def prompt(self, pane, text, wait):
        self.writes.append(text)
        if text == deliver.CLEAR and self.on_clear:
            self.on_clear()   # 会話が空になり、空にした後の会話の始まりの待ち受けが印を書いた

    def send_keys(self, pane, *keys):
        self.writes.append(keys)


class Hook(unittest.TestCase):
    """入口 wake_hook.py: 部署と窓口でだけ待ち、同じ場所の別の会話は待たない。順番待ちを渡し、fresh の部署を空にする。"""

    def setUp(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.src = str(d / "co")
        git("init", "-q", "-b", "main", self.src)
        git("-C", self.src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
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
        # 部署は印で見分ける（部署の場所には会話の処理の番号が無い。--desk は部署の worktree で止まり、写った物は --task が消す）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1"}, gitx)
        self.assertIsNone(self.plan(sid="s9", same=lambda pid: True))

    def test_a_fresh_department_is_not_cleared_while_an_ask_it_made_has_no_answer(self):
        # 受けた頼みも、そこから出した子の頼みも全部閉じたターンの終わりに空にする（持ち主の承認 dc0aa2。標準 6c364c が子の納品を待つ間）
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, gitx)
        deliver.log(self.inbox, {"kind": "ask", "id": "c1", "status": "queued", "at": 1,
                                 "from": {"name": "調べ", "place": self.place}, "to": {"company": "co", "name": "点検"}})
        w = self.emptied()
        self.assertIsNone(self.checker(window=w)())   # 子の返事待ち: 空にしない
        self.assertEqual(w.writes, [])
        deliver.log(self.inbox, {"kind": "deliver", "id": "d1", "ask": "c1", "status": "sent"})   # 子の納品が届いた
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(self.checker(window=w)(), ("end", None))   # 空にした（空にした後の待ち受けが次の頼みを渡す）
        self.assertEqual(w.writes[0], deliver.CLEAR)

    def test_a_fresh_department_waiting_on_a_child_hands_the_next_ask_to_the_same_conversation(self):
        # 子の返事待ちで順番待ちを止めると、子の先が自分の返事待ちのときに輪になり、何時間も止まった（2026-10-18 の割り振り・見渡し）。
        # 空にはせず（子の返事をこの会話で受ける）、次の頼みを渡し、空にしない訳を頭に付ける
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH, "session": "s1"}, gitx)
        deliver.log(self.inbox, {"kind": "handed", "id": "a0", "at": 0, "place": self.place})
        deliver.log(self.inbox, {"kind": "ask", "id": "c1", "status": "queued", "at": 1,
                                 "from": {"name": "調べ", "place": self.place, "session": "s1"}, "to": {"company": "co", "name": "点検"}})
        self.put("a1")
        w = self.emptied()
        tried = []
        kind, text = wake_hook.checker(self.plan(), {"hook_event_name": "Stop"}, h=w, now=lambda: 5, me=lambda: ME,
                                       restart=lambda got_, key: tried.append(key) or True, key_of=lambda cwd, a: "other")()
        self.assertEqual(tried, [], "起動し直すと、子の返事を受ける会話が居なくなる")
        self.assertEqual(kind, "wake")
        self.assertTrue(text.startswith("（前の頼みを納品した会話を空にしないまま渡す: この会話が出した子の頼み（受付 c1）"), text)
        self.assertTrue(text.endswith("頼みです（受付 a1）"))
        self.assertEqual(w.writes, [], "子の返事を受ける会話を空にしない")
        handed = [r for r in deliver.records(self.inbox) if r.get("kind") == "handed"]
        self.assertIn("受付 c1", handed[-1]["kept"])
        self.assertEqual([r for r in deliver.records(self.inbox) if r.get("kind") == "held"], [])
        # 次の頼みを受けた後も、同じ会話が前の頼みで出した子は数える
        self.assertEqual(wake_hook.open_children(self.plan(), gitx.worktree_attrs(self.place)), ["c1"])
        provision.mark(self.place, self.src, {"session": "s2"}, gitx)   # compact・resume で会話の id が替わっても数える
        self.assertEqual(wake_hook.open_children(self.plan(sid="s2"), gitx.worktree_attrs(self.place)), ["c1"])
        # 空にしてから渡した頼み（kept の無い handed）より前の物は、前の会話の子なので数えない
        deliver.log(self.inbox, {"kind": "handed", "id": "a2", "at": 9, "place": self.place, "session": "s3"})
        provision.mark(self.place, self.src, {"session": "s3", "ask": "a2"}, gitx)
        self.assertEqual(wake_hook.open_children(self.plan(sid="s3"), gitx.worktree_attrs(self.place)), [])

    def test_children_count_only_since_the_ask_and_close_only_in_what_the_waiter_has_read(self):
        attrs = {"name": "調べ", "ask": "a0"}
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ"}, gitx)
        got = self.plan()
        log = lambda r: deliver.log(self.inbox, r)   # noqa: E731
        log({"kind": "ask", "id": "old", "status": "queued", "at": 1, "from": {"name": "調べ", "place": self.place}})   # 前の会話の古い頼み
        log({"kind": "handed", "id": "a0", "at": 5, "place": self.place})
        log({"kind": "ask", "id": "c1", "status": "queued", "at": 6, "from": {"name": "調べ", "place": os.path.join(self.place, "sub")}})
        self.assertEqual(wake_hook.open_children(got, attrs), ["c1"])   # 今の頼みを受けた後の物だけ（作業場の下のフォルダも）
        place = gitx.git_dir(self.place)
        size = os.path.getsize(os.path.join(self.inbox, wake.LOG))
        os.makedirs(os.path.dirname(wake.pos_path(self.inbox, place)), exist_ok=True)
        pathlib.Path(wake.pos_path(self.inbox, place)).write_text(str(size))   # 待ち受けはここまで読んだ
        log({"kind": "deliver", "id": "d1", "ask": "c1", "status": "sent", "at": 7})
        self.assertEqual(wake_hook.open_children(got, attrs, read=wake_hook._read_part(got)), ["c1"])   # 返事をまだ会話が受けていない
        pathlib.Path(wake.pos_path(self.inbox, place)).write_text(str(os.path.getsize(os.path.join(self.inbox, wake.LOG))))
        self.assertEqual(wake_hook.open_children(got, attrs, read=wake_hook._read_part(got)), [])

    def dept(self, branch, **attrs):
        """同じ会社にもう 1 つ部署を立てる（場所を返す）。"""
        path = os.path.join(os.path.dirname(self.place), branch.replace("/", "-"))
        git("-C", self.src, "worktree", "add", "-q", "-b", branch, path)
        provision.mark(path, self.src, attrs, gitx)
        return path

    def asked(self, ask_id, frm, frm_place, dest, at=2):
        """frm（場所 frm_place）が dest の部署へ頼み、dest の順番待ちに積まれたまま。"""
        deliver.log(self.inbox, {"kind": "ask", "id": ask_id, "status": "queued", "at": at, "from": {"name": frm, "place": frm_place},
                                 "to": {"company": "co", "path": dest}})
        wake.enqueue(self.inbox, gitx.git_dir(dest), {"id": ask_id, "line": f"頼みです（受付 {ask_id}）", "marks": {"ask": ask_id}})

    def listens(self, path, name):
        wake.claim(self.inbox, gitx.git_dir(path), [f"co/{name}"], f"s-{name}", 7, f"t-{name}", 0)

    @staticmethod
    def ring(edges):
        """knot の返りから、場所を除いた (受付, 頼んだ部署, 積まれた部署) の並び。"""
        return [e[:3] for e in edges]

    def test_two_held_departments_waiting_on_each_other_untie_the_oldest_ask_of_the_ring(self):
        # 調べは点検への c1 の返事を、点検は調べへの q1 の返事を、どちらも今の頼みを納品せずに待ち、順番待ちを渡さない（2026-10-18 の my_notes）
        held = {"role": "担当", "fresh": role.FRESH}
        provision.mark(self.place, self.src, {**held, "name": "調べ", "ask": "a0"}, gitx)
        other = self.dept("dept/b", **held, name="点検", ask="b0")
        self.asked("20261018-000001-c00001", "調べ", self.place, other)
        self.asked("20261018-000002-q00002", "点検", other, self.place)
        tied, done = [], os.path.join(self.inbox, "take.done")
        check = wake_hook.checker(self.plan(), {"hook_event_name": "Stop"}, h=Window(self.place), now=lambda: 5, me=lambda: ME,
                                  unknot=lambda got, edges: tied.append(edges) or (edges[0][0], done))
        self.assertIsNone(check())
        self.assertEqual(tied, [], "点検の待ち受けが居ない間は、点検は止まっていると見ない")
        self.listens(other, "点検")
        self.assertIsNone(check())   # 輪をほどいても、納品していない頼みが在る間は次を渡さない
        self.assertEqual([self.ring(e) for e in tied], [[("20261018-000001-c00001", "調べ", "点検"), ("20261018-000002-q00002", "点検", "調べ")]])
        self.assertEqual(tied[0][0][3], os.path.realpath(other))   # 回す頼みが積まれた部署の場所
        check()
        self.assertEqual(len(tied), 1, "回した --take が終わらない間・0 で終わった後は、同じ頼みを回し直さない")
        pathlib.Path(done).write_text("0\n")
        check()
        self.assertEqual(len(tied), 1)
        pathlib.Path(done).write_text("2\n")   # ほかの待ち受けと取り合って負けた・頼み直せずに戻した
        for _ in range(5):
            check()
        self.assertEqual(len(tied), wake_hook.UNTIE_TRIES, "0 以外で終わったら、上限まで回し直す")

    def test_a_failure_while_looking_for_a_ring_does_not_stop_the_listener(self):
        held = {"role": "担当", "fresh": role.FRESH}
        provision.mark(self.place, self.src, {**held, "name": "調べ", "ask": "a0"}, gitx)
        other = self.dept("dept/b", **held, name="点検", ask="b0")
        self.asked("c1", "調べ", self.place, other)
        self.asked("q1", "点検", other, self.place)
        self.listens(other, "点検")

        calls = []

        def broken(got, edges):
            calls.append(edges)
            raise OSError("台帳に書けない")
        check = wake_hook.checker(self.plan(), {"hook_event_name": "Stop"}, h=Window(self.place), now=lambda: 5, me=lambda: ME,
                                  unknot=broken)
        for _ in range(5):
            self.assertIsNone(check())
        self.assertEqual(len(calls), wake_hook.UNTIE_TRIES, "落ちた回も数え、上限で止める")
        with mock.patch.object(wake_hook.deliver, "records", side_effect=UnicodeDecodeError("utf-8", b"", 0, 1, "切れた")):
            self.assertIsNone(check())

    def test_a_department_that_only_leads_into_the_ring_is_not_where_the_ring_is_untied(self):
        # 調べ ⇄ 点検 の輪に加え、点検 → 見直し（見直しは調べへ戻らない）。見直しへの頼みが一番古くても、輪の外なので回さない
        held = {"role": "担当", "fresh": role.FRESH}
        provision.mark(self.place, self.src, {**held, "name": "調べ", "ask": "a0"}, gitx)
        other = self.dept("dept/b", **held, name="点検", ask="b0")
        review = self.dept("dept/c", **held, name="見直し", ask="c0")
        self.asked("20261018-000003-aaaaaa", "調べ", self.place, other)
        self.asked("20261018-000002-bbbbbb", "点検", other, self.place)
        self.asked("20261018-000001-cccccc", "点検", other, review)
        for path, name in ((other, "点検"), (review, "見直し")):
            self.listens(path, name)
        edges = wake_hook.knot(self.plan(), gitx.worktree_attrs(self.place), ["20261018-000003-aaaaaa"])
        self.assertEqual(self.ring(edges), [("20261018-000002-bbbbbb", "点検", "調べ"), ("20261018-000003-aaaaaa", "調べ", "点検")])

    def test_overlapping_rings_pick_the_same_ask_from_every_department(self):
        # 割り振り ⇄ 点検 の輪と、点検 → 見直し → 割り振り の輪が重なる。どの部署から見ても、重なった輪の全体の一番古い頼みを回す
        held = {"role": "担当", "fresh": role.FRESH}
        provision.mark(self.place, self.src, {**held, "name": "割り振り", "ask": "a0"}, gitx)
        check_ = self.dept("dept/b", **held, name="点検", ask="b0")
        review = self.dept("dept/c", **held, name="見直し", ask="c0")
        self.asked("20261018-000005-aaaaaa", "割り振り", self.place, check_)
        self.asked("20261018-000004-bbbbbb", "点検", check_, self.place)
        self.asked("20261018-000001-cccccc", "点検", check_, review)
        self.asked("20261018-000003-dddddd", "見直し", review, self.place)
        for path, name in ((self.place, "割り振り"), (check_, "点検"), (review, "見直し")):
            self.listens(path, name)
        here = wake_hook.knot(self.plan(), gitx.worktree_attrs(self.place), ["20261018-000005-aaaaaa"])
        got = wake_hook.plan({"cwd": review, "session_id": "s-見直し"}, env=self.env, parent=lambda: 7, same=lambda pid: False)
        there = wake_hook.knot(got, gitx.worktree_attrs(review), ["20261018-000003-dddddd"])
        self.assertEqual(self.ring(here)[0], ("20261018-000001-cccccc", "点検", "見直し"))
        self.assertEqual(self.ring(there)[0], ("20261018-000001-cccccc", "点検", "見直し"))
        self.assertEqual([e[0] for e in here], ["20261018-000001-cccccc", "20261018-000003-dddddd", "20261018-000005-aaaaaa"])

    def test_no_ring_when_a_department_on_the_way_carries_its_conversation_over(self):
        # 会話を引き継ぐ部署は、納品し終えれば順番待ちを渡すので、止まっていると見ない
        held = {"role": "担当", "fresh": role.FRESH}
        provision.mark(self.place, self.src, {**held, "name": "調べ", "ask": "a0"}, gitx)
        other = self.dept("dept/b", role="担当", name="点検", ask="b0", delivered="b0")
        self.asked("c1", "調べ", self.place, other)
        self.asked("q1", "点検", other, self.place)
        self.listens(other, "点検")
        self.assertIsNone(wake_hook.knot(self.plan(), gitx.worktree_attrs(self.place), ["c1"]))

    def test_a_ring_through_three_departments_with_an_undelivered_one_in_the_middle_is_found_from_each(self):
        # 割り振りは今の頼みを納品せずに点検への c1 の返事を待ち、点検は見直しへの c2 を、見直しは割り振りへの c3 を待つ（10-18 の
        # claude-plugins。輪の途中に、納品していない永続の担当が入る）
        held = {"role": "担当", "fresh": role.FRESH}
        provision.mark(self.place, self.src, {**held, "name": "割り振り", "ask": "a0"}, gitx)   # 納品していない
        check_ = self.dept("dept/b", **held, name="点検", ask="b0")
        review = self.dept("dept/c", **held, name="見直し", ask="c0")
        self.asked("20261018-000003-c00001", "割り振り", self.place, check_)
        self.asked("20261018-000001-c00002", "点検", check_, review)
        self.asked("20261018-000002-c00003", "見直し", review, self.place)
        for path, name in ((check_, "点検"), (review, "見直し")):
            self.listens(path, name)
        tied = []
        stop = {"hook_event_name": "Stop"}
        check = wake_hook.checker(self.plan(), stop, h=Window(self.place), now=lambda: 5, me=lambda: ME,
                                  unknot=lambda got, edges: tied.append(edges))
        self.assertIsNone(check())   # 納品していない部署は渡さないが、輪は見る
        # 先頭が回す頼み（どこから見ても、輪の一番古い頼み）。その後に輪を順にたどる
        self.assertEqual([e[0] for e in tied[0]], ["20261018-000001-c00002", "20261018-000002-c00003", "20261018-000003-c00001"])
        self.listens(self.place, "割り振り")
        got = wake_hook.plan({"cwd": review, "session_id": "s-見直し"}, env=self.env, parent=lambda: 7, same=lambda pid: False)
        seen = []
        wake_hook.checker(got, stop, h=Window(review), now=lambda: 5, me=lambda: ME, unknot=lambda got, edges: seen.append(edges))()
        self.assertEqual(seen[0][0][0], "20261018-000001-c00002")
        tied.clear()
        wake_hook.checker(self.plan(), {**stop, "background_tasks": [{"id": "x"}]}, h=Window(self.place), now=lambda: 5, me=lambda: ME,
                          unknot=lambda got, edges: tied.append(edges))()
        self.assertEqual(tied, [], "裏の処理を待つだけの部署は、輪に入って止まっていると見ない")

    def test_a_ring_across_two_companies_is_followed_through_each_inbox(self):
        held = {"role": "担当", "fresh": role.FRESH}
        provision.mark(self.place, self.src, {**held, "name": "割り振り", "ask": "a0"}, gitx)
        src2 = os.path.join(os.path.dirname(self.place), "co2")
        git("init", "-q", "-b", "main", src2)
        git("-C", src2, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
        other = os.path.join(os.path.dirname(self.place), "notes")
        git("-C", src2, "worktree", "add", "-q", "-b", "dept/n", other)
        provision.mark(other, src2, {**held, "name": "調べもの", "ask": "n0"}, gitx)
        inbox2 = deliver.inbox_of(gitx.common_dir(src2))
        # 頼みの行は頼んだ側の会社の受付箱に、順番待ちは受ける側の会社の受付箱に在る
        self.asked("c1", "割り振り", self.place, other)
        os.unlink(wake.find(self.inbox, "c1")["path"])
        wake.enqueue(inbox2, gitx.git_dir(other), {"id": "c1", "marks": {"ask": "c1"}})
        deliver.log(inbox2, {"kind": "ask", "id": "q1", "status": "queued", "at": 2, "from": {"name": "調べもの", "place": other},
                             "to": {"company": "co", "path": self.place}})
        wake.enqueue(self.inbox, gitx.git_dir(self.place), {"id": "q1", "marks": {"ask": "q1"}})
        wake.claim(inbox2, gitx.git_dir(other), ["co2/調べもの"], "s2", 7, "t2", 0)
        edges = wake_hook.knot(self.plan(), gitx.worktree_attrs(self.place), ["c1"])
        self.assertEqual(self.ring(edges), [("c1", "割り振り", "調べもの"), ("q1", "調べもの", "割り振り")])
        runs = []
        wake_hook.untie(self.plan(), edges, spawn=lambda argv, **kw: runs.append((argv, kw["cwd"])), now=lambda: 9, detach=False)
        argv, cwd = runs[0]
        # 作業の部署は、頼みが積まれていた部署の会社（co2）に立てる。--take もその会社の代表の clone で打つ
        self.assertEqual(argv[argv.index("--ask") + 1], f"{os.path.basename(src2)}/作業")
        self.assertEqual(os.path.realpath(cwd), os.path.realpath(src2))

    def test_no_ring_once_the_ask_has_been_handed(self):
        held = {"role": "担当", "fresh": role.FRESH}
        provision.mark(self.place, self.src, {**held, "name": "調べ", "ask": "a0"}, gitx)
        other = self.dept("dept/b", **held, name="点検", ask="b0")
        self.asked("c1", "調べ", self.place, other)
        self.asked("q1", "点検", other, self.place)
        self.listens(other, "点検")
        wake.take(self.inbox, gitx.git_dir(other))   # 点検が c1 を受けた（動いている）
        self.assertIsNone(wake_hook.knot(self.plan(), gitx.worktree_attrs(self.place), ["c1"]))

    def test_untie_takes_the_ask_to_a_task_named_after_its_owner_and_logs_the_ring(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ"}, gitx)
        runs = []

        def spawn(argv, **kw):
            runs.append((argv, kw["cwd"]))
        edges = [("20261018-000001-bbbbbb", "点検", "調べ", self.place), ("20261018-000002-aaaaaa", "調べ", "点検", "/x/点検")]
        got = self.plan()
        self.assertEqual(wake_hook.untie(got, edges, spawn=spawn, now=lambda: 9, detach=False)[0], "20261018-000001-bbbbbb")
        argv, cwd = runs[0]
        self.assertEqual(argv[argv.index("--take") + 1], "20261018-000001-bbbbbb")
        self.assertEqual(argv[argv.index("--ask") + 1], "co/作業")   # 会社の形に default_role が無ければ既定の役
        self.assertEqual(argv[argv.index("--task") + 1], "調べ：bbbbbb")   # 積まれていた部署の受け持ちの名前
        self.assertEqual(argv[argv.index("--branch") + 1], "work/ask-bbbbbb")
        self.assertIn("点検 → 調べ → 点検", argv[argv.index("--text") + 1])
        self.assertEqual(cwd, got["root"])
        line = deliver.records(self.inbox)[-1]
        self.assertEqual((line["kind"], line["id"], line["chain"]), (wake_hook.KNOT, "20261018-000001-bbbbbb", ["点検", "調べ", "点検"]))

    def test_untie_stops_when_the_default_role_is_not_in_the_shape(self):
        # 前は既定の役（作業）に倒して回し、役の名前を英語で書いた会社では役の無い部署を立てえた
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ"}, gitx)
        edges = [("20261018-000001-bbbbbb", "点検", "調べ", self.place)]
        runs = []
        with mock.patch.object(role, "default", return_value=(None, "既定の役 作業 が会社の形に無い")):
            with self.assertRaises(wake_hook.UntieError) as got:
                wake_hook.untie(self.plan(), edges, spawn=lambda argv, **kw: runs.append(argv), now=lambda: 9, detach=False)
        self.assertIn("会社の形に無い", str(got.exception))
        self.assertEqual(runs, [])

    def test_a_fresh_department_woken_by_a_notice_is_cleared_at_the_end_of_that_turn(self):
        # 頼みを受けていないターン（納品の知らせで起きた）の後も、次の頼みを空の会話で受ける（6a9337）
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0", "cleared": "a0",
                                              "fresh": role.FRESH}, gitx)
        stop = {"hook_event_name": "Stop", "session_id": "s1"}
        self.assertFalse(wake_hook.must_clear(stop, gitx.worktree_attrs(self.place)))   # 空にした後
        err = io.StringIO()
        out = wake_hook.WithRole(err, {"session_id": "s1"}, changed=lambda payload: None, woke=lambda: wake_hook.woken(self.plan()))
        out.write("納品です（受付 d1）\n")
        self.assertNotIn("cleared", gitx.worktree_attrs(self.place))
        self.assertTrue(wake_hook.must_clear(stop, gitx.worktree_attrs(self.place)))   # 起動されたターンの終わりに空にする
        provision.mark(self.place, self.src, {"cleared": "a0", "fresh": None}, gitx)   # 会話を引き継ぐ役では外さない
        wake_hook.woken(self.plan())
        self.assertEqual(gitx.worktree_attrs(self.place)["cleared"], "a0")

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

    def emptied(self):
        """/clear を受けて空になる窓（空にした後の会話の始まりの待ち受けが、新しい会話の id で印を書く）。"""
        return Window(self.place, on_clear=lambda: wake.claim(self.inbox, gitx.git_dir(self.place), ["co/調べ"], "s-new", 7, "t2", 0))

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

    def test_does_not_hand_the_next_ask_when_one_arrived_after_it_looked(self):
        # 上で属性を読んだ後に、--ask が窓に別の頼みを打って属性を書いた。錠の中で読み直し、渡さずに順番待ちに残す（渡すと、
        # 後に書いた頼み元が前の頼みの頼み元を上書きする。my_notes の受付 20261017-082903-87f45f）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "ask": "a0", "delivered": "a0"}, gitx)
        self.put("a1")
        reads = []

        def attrs_of(cwd):
            reads.append(cwd)
            if len(reads) == 2:   # 錠の中の読み直しの前に、ほかの道が頼みを書いた
                provision.mark(self.place, self.src, {"ask": "b1", "boss": "段取り"}, gitx)
            return gitx.worktree_attrs(cwd)
        check = wake_hook.checker(self.plan(), {"hook_event_name": "Stop"}, h=Window(self.place), now=lambda: 5, me=lambda: ME,
                                  attrs_of=attrs_of)
        self.assertIsNone(check())
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["ask"], attrs["boss"]), ("b1", "段取り"))
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, gitx.git_dir(self.place))], ["a1"])

    def test_fresh_department_is_cleared_when_it_stops_after_delivering(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, gitx)
        self.put("a1")
        w = self.emptied()
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(self.checker(window=w)(), ("end", None))   # 渡すのは空にした後の会話の始まりの待ち受け
        self.assertEqual(w.writes[0], deliver.CLEAR)
        self.assertEqual(gitx.worktree_attrs(self.place)["cleared"], "a0")
        self.assertEqual(len(wake.queued(self.inbox, gitx.git_dir(self.place))), 1)
        # 空にした後（SessionStart）は渡す
        got = wake_hook.checker(self.plan(), {"hook_event_name": "SessionStart"}, h=Window(self.place), now=lambda: 5)
        self.assertEqual(got(), ("wake", "頼みです（受付 a1）"))

    def test_a_clear_not_seen_to_empty_the_talk_keeps_this_watcher_holding(self):
        # /clear を打っても空になったのを見られなければ、空にした印を書かず、この待ち受けが続いて空にするのを試し直す（空にした
        # つもりで終わると、次の待ち受けが張られず順番待ちが止まる。2026-10-17 に my_notes のノートの手入れで約 70 分止まった）
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, gitx)
        self.put("a1")
        w = Window(self.place)
        check = self.checker(window=w)
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(check(), wake.HOLD)   # 終わらない（"end" なら、この待ち受けの後を継ぐ者が居ない）
        self.assertEqual(w.writes[0], deliver.CLEAR)
        self.assertNotIn("cleared", gitx.worktree_attrs(self.place))
        held = [r for r in deliver.records(self.inbox) if r["kind"] == "held"]
        self.assertIn("空になったのを見られない", held[0]["detail"])
        w.on_clear = self.emptied().on_clear   # 試し直しで空になった
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(check(), ("end", None))
        self.assertEqual(gitx.worktree_attrs(self.place)["cleared"], "a0")

    def fresh_dept(self, **more):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0", "cleared": "a0",
                                              "fresh": role.FRESH, "job": "j1", **more}, gitx)
        return gitx.worktree_attrs(self.place)

    def test_fresh_department_restarts_before_the_next_ask_when_the_shape_changed_its_model(self):
        # /clear は起動したときの --model・--effort を残すので、会社の形の値が起動したときと違えば起動し直す（6bdc72）
        opus = role.launch_key({"model": "opus"})
        attrs = self.fresh_dept(launched=role.launch_key(None))
        got = self.plan()
        stop = {"hook_event_name": "Stop"}
        self.assertIsNone(wake_hook.restart_due(got, stop, attrs, key_of=lambda cwd, a: opus))   # 渡す頼みが無い
        self.put("a1")
        self.assertEqual(wake_hook.restart_due(got, stop, attrs, key_of=lambda cwd, a: opus), opus)
        for payload, attrs_, key in ((stop, attrs, role.launch_key(None)),   # 起動したときと同じ
                                     (stop, {**attrs, wake.RESTART_KEPT: opus}, opus),   # 前に起動し直さなかった値
                                     (stop, attrs, None),   # 会社の形を読めない
                                     ({**stop, "background_tasks": [{"id": "b"}]}, attrs, opus),
                                     (stop, {**attrs, "fresh": None}, opus),   # 会話を引き継ぐ部署
                                     (stop, {**attrs, wake.RESTARTING: got["session"]}, opus)):   # この会話の起動し直しが走っている
            self.assertIsNone(wake_hook.restart_due(got, payload, attrs_, key_of=lambda cwd, a: key))
        # 前の会話の id の印は残り物（/clear の後）。起動し直してよい
        self.assertEqual(wake_hook.restart_due(got, stop, {**attrs, wake.RESTARTING: "old"}, key_of=lambda cwd, a: opus), opus)
        # 属性の無い部署（この版より前に起動した）は旗なしで起動したと見る
        self.assertIsNone(wake_hook.restart_due(got, stop, {**attrs, "launched": None}, key_of=lambda cwd, a: role.launch_key(None)))
        tried = []
        check = wake_hook.checker(got, stop, h=Window(self.place), now=lambda: 5, me=lambda: ME,
                                  restart=lambda got_, key: tried.append(key) or True, key_of=lambda cwd, a: opus)
        self.assertEqual(check(), ("end", None))   # 起動し直した会話の待ち受けが渡す
        self.assertEqual(tried, [opus])
        self.assertEqual(len(wake.queued(self.inbox, gitx.git_dir(self.place))), 1)
        check = wake_hook.checker(got, stop, h=Window(self.place), now=lambda: 5, me=lambda: ME,
                                  restart=lambda got_, key: False, key_of=lambda cwd, a: opus)
        self.assertEqual(check(), ("wake", "頼みです（受付 a1）"))   # 起動し直せなければ、前の会話に渡す

    def test_fresh_department_restarts_before_the_next_ask_to_move_early_off_a_hot_account(self):
        # 起動の設定が同じでも、上限に当たる前の区切りで移すときは起動し直す（受付 215886）
        same = role.launch_key(None)
        attrs = self.fresh_dept(launched=same, account="a1")
        got = self.plan()
        stop = {"hook_event_name": "Stop"}
        self.put("a1")
        self.assertIsNone(wake_hook.restart_due(got, stop, attrs, key_of=lambda cwd, a: same, early_of=lambda g, a: False))
        self.assertEqual(wake_hook.restart_due(got, stop, attrs, key_of=lambda cwd, a: same, early_of=lambda g, a: True), same)
        # 早めに移す目安は、設定と使用率の控えから読む（控えは取り直さない）
        d = tempfile.mkdtemp()
        cfg = os.path.join(d, "c.toml")
        pathlib.Path(cfg).write_text(f"limits_dir = '{d}'\naccounts = [{{ name = \"a1\", command = \"c1\" }}, "
                                     f"{{ name = \"a2\", command = \"c2\" }}]\n", encoding="utf-8")
        hot = {"five_hour": {"used_percentage": 92, "resets_at": 10 ** 10}, "seven_day": {"used_percentage": 50}}
        cool = {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 40}}
        for name, raw in (("a1", hot), ("a2", cool)):
            pathlib.Path(d, f"{name}.json").write_text(json.dumps(raw), encoding="utf-8")
        here = {**attrs, "config": cfg}
        self.assertTrue(wake_hook.early_due(got, here, env={}))
        self.assertFalse(wake_hook.early_due(got, {**here, "account": "a2"}, env={}))   # 移る先の側は目安に届かない
        self.assertTrue(wake_hook.early_due(got, {**here, "account": "a2", wake.MOVE_TO: "a1"}, env={}))   # 名指し
        self.assertFalse(wake_hook.early_due(got, {**here, "config": os.path.join(d, "無い.toml")}, env={}))   # 設定が無ければ控えも無い
        self.assertFalse(wake_hook.early_due(got, {**here, wake.MOVE_KEPT: "a2"}, env={}))   # 前に起動できなかった先は選ばない
        # 目安に達したのに移す先が無ければ、訳を台帳に 1 度だけ残す
        provision.mark(self.place, self.src, {"config": cfg}, gitx)
        for _ in range(2):
            self.assertFalse(wake_hook.early_due(got, {**gitx.worktree_attrs(self.place), wake.MOVE_KEPT: "a2"}, env={}))
        (row,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual((row["status"], row["to"], row["why"]), ("skipped", None, wake.EARLY))
        self.assertIn("ほかのアカウントが無い", row["detail"])

    def test_a_just_started_background_talk_is_unready_until_its_transcript_exists(self):
        path = os.path.join(self.place, "t.jsonl")
        start = {"hook_event_name": "SessionStart", "source": "startup", "transcript_path": path}
        self.assertTrue(wake_hook.unready(start, "j1"))
        self.assertFalse(wake_hook.unready(start, None))   # 人が端末で起動した会話は、最初の文を打つまで知らせを止めない
        for payload in ({**start, "source": "clear"}, {**start, "hook_event_name": "Stop"}, {**start, "transcript_path": None}):
            self.assertFalse(wake_hook.unready(payload, "j1"))
        pathlib.Path(path).write_text('{"type":"custom-title"}\n', encoding="utf-8")
        self.assertTrue(wake_hook.unready(start, "j1"))   # 記録のファイルはできたが、最初の文の行がまだ無い
        pathlib.Path(path).write_text('{"type":"custom-title"}\n{"type":"user","message":{}}\n', encoding="utf-8")
        self.assertFalse(wake_hook.unready(start, "j1"))

    def test_an_ask_whose_text_never_reached_the_talk_is_handed_once_again(self):
        # my_notes の受付 4bae53: 渡した字は殺された会話の処理と消え、起動し直した会話は move-brief.md の「頼みは無い」だけを読んだ
        boss_inbox = tempfile.mkdtemp()
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "q1", "delivered": "q0", "session": "s1",
                                              "boss": "段取り", "boss-inbox": boss_inbox}, gitx)
        brief = os.path.join(gitx.git_dir(self.place), "move-brief.md")
        pathlib.Path(brief).write_text("起動し直した。受けている頼みは無い。次の頼みを待つ。\n", encoding="utf-8")
        talk = os.path.join(self.place, "t.jsonl")
        pathlib.Path(talk).write_text('{"content": "move-brief.md を読んで進めてください。"}\n', encoding="utf-8")
        stop = {"hook_event_name": "Stop", "transcript_path": talk}
        kind, text = self.checker(stop)()
        self.assertEqual(kind, "wake")
        self.assertIn("受付 q1、段取り から", text)
        self.assertIn("本文は 段取り に問い合わせる", text)   # 本文のファイルが無ければ、無いパスを指さない
        pathlib.Path(boss_inbox, "q1-ask.md").write_text("頼み", encoding="utf-8")
        self.assertIn(os.path.join(boss_inbox, "q1-ask.md"), wake_hook.again_text(gitx.worktree_attrs(self.place), "/d.py"))
        self.assertIn("--deliver", text)
        (again,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "handed"]
        self.assertEqual((again["id"], again["session"]), ("q1", "s1"))
        self.assertTrue(again["again"])
        self.assertIsNone(self.checker(stop)())   # 同じ会話へは 1 度まで
        self.assertIsNone(self.checker({**stop, "transcript_path": None})())   # 記録の場所が無ければ届いたと見る

    def test_an_ask_the_talk_saw_is_not_handed_again(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "q1", "delivered": "q0", "session": "s1"}, gitx)
        talk = os.path.join(self.place, "t.jsonl")
        stop = {"hook_event_name": "Stop", "transcript_path": talk}
        pathlib.Path(talk).write_text('{"content": "頼みです（受付 q1）"}\n', encoding="utf-8")
        self.assertIsNone(self.checker(stop)())
        # --move の最初の文で渡した頼み（move-brief.md に受付が在る）
        pathlib.Path(talk).write_text('{"content": "move-brief.md を読んで進めてください。"}\n', encoding="utf-8")
        pathlib.Path(gitx.git_dir(self.place), "move-brief.md").write_text("受け持ちの頼み（受付 q1）を続ける", encoding="utf-8")
        self.assertIsNone(self.checker(stop)())
        # 頼みを持つ会話がこの会話でなければ見ない
        pathlib.Path(talk).write_text("{}\n", encoding="utf-8")
        got = self.plan()
        self.assertTrue(wake_hook.unseen(got, stop, gitx.worktree_attrs(self.place)))
        provision.mark(self.place, self.src, {"session": "s9"}, gitx)
        self.assertFalse(wake_hook.unseen(got, stop, gitx.worktree_attrs(self.place)))
        self.assertEqual([r for r in deliver.records(self.inbox) if r.get("kind") == "handed"], [])

    def test_restart_first_waits_for_the_move_and_hands_the_ask_back_when_the_talk_was_not_stopped(self):
        opus = role.launch_key({"model": "opus"})
        self.fresh_dept()
        got = self.plan(sid="j1")
        seen = []

        class Done:
            def poll(self):
                return 0

        def spawn(argv, **kw):
            seen.append((argv, kw["cwd"]))
            self.assertEqual(gitx.worktree_attrs(self.place)[wake.RESTARTING], "j1")   # 走らせる前に印を付ける
            return Done()
        self.assertFalse(wake_hook.restart_first(got, opus, spawn=spawn, now=lambda: 5))
        (argv, cwd), = seen
        self.assertEqual(argv[1:], ["-u", wake_hook.DISPATCH_PY, "--move", "co/調べ", "--if-changed"])
        self.assertEqual(cwd, self.place)
        attrs = gitx.worktree_attrs(self.place)
        self.assertNotIn(wake.RESTARTING, attrs)
        self.assertEqual(attrs[wake.RESTART_KEPT], opus)   # 同じ値では試し直さない

        def stopped(argv, **kw):   # --move が前の会話を止めて印を外した
            provision.mark(self.place, self.src, {wake.RESTARTING: None}, gitx)
            return Done()
        self.assertTrue(wake_hook.restart_first(got, opus, spawn=stopped, now=lambda: 5))

        class Later:   # --move が今は起動し直さない（ターンの途中・打ちかけの字）で終わった
            def poll(self):
                return wake.NOT_NOW
        provision.mark(self.place, self.src, {wake.RESTART_KEPT: None}, gitx)
        self.assertFalse(wake_hook.restart_first(got, opus, spawn=lambda argv, **kw: Later(), now=lambda: 5))
        attrs = gitx.worktree_attrs(self.place)
        self.assertNotIn(wake.RESTARTING, attrs)
        self.assertNotIn(wake.RESTART_KEPT, attrs)   # 次の区切りでまた試す

    @unittest.skipIf(os.name == "nt", "切り離しは /bin/sh の殻で、Windows では使わない（wake_hook・limit_hook は Windows で切り離さずに起動する）")
    def test_the_move_runs_detached_from_the_talk_and_writes_its_output_and_end(self):
        # 会話を止めると Claude Code はフックの子孫も止める。--move は切り離して走らせ、前の会話を止めても最後まで走る
        d = tempfile.mkdtemp()
        log, done = os.path.join(d, "m.log"), os.path.join(d, "m.done")
        p = subprocess.Popen(wake.detached([sys.executable, "-c", "print('動いた')"], log, done), start_new_session=True)
        p.wait()
        for _ in range(200):
            if os.path.exists(done) and pathlib.Path(done).read_text().strip():   # 殻は走らせる前に空の .done を作る
                break
            time.sleep(0.05)
        self.assertEqual(pathlib.Path(done).read_text().strip(), "0")
        self.assertEqual(pathlib.Path(log).read_text(encoding="utf-8").strip(), "動いた")
        self.assertIsNone(wake_hook._DoneFile(log + ".x").poll())
        self.assertEqual(wake_hook._DoneFile(done).poll(), 0)
        pathlib.Path(done).write_text("75\n")
        self.assertEqual(wake_hook._DoneFile(done).poll(), wake.NOT_NOW)   # 終わりの値を読む（今は起動し直さない、を見分ける）
        pathlib.Path(done).write_text("")
        self.assertIsNone(wake_hook._DoneFile(done).poll())   # 殻が書いている途中

    def test_a_break_marked_by_an_earlier_talk_does_not_restart_this_one(self):
        # 区切りの印は打った会話の id。前の会話の印が残っていても、今の会話（持ち主と話している）を起動し直さない（16:03 の段取り）
        opus = role.launch_key({"model": "opus"})
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s0"}, gitx)
        tried, w = [], Window(self.place)
        check = wake_hook.checker(self.plan(), {"hook_event_name": "Stop", "session_id": "s1"}, h=w, now=lambda: 5, me=lambda: ME,
                                  restart=lambda got_, key: tried.append(key) or True, key_of=lambda cwd, a: opus)
        self.assertIsNone(check())
        self.assertEqual((tried, w.writes), ([], []))

    def test_fresh_department_is_not_cleared_while_busy_typed_or_waiting_on_background_work(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, gitx)
        for payload, window in (({"hook_event_name": "Stop", "background_tasks": [{"id": "b"}]}, Window(self.place)),
                                ({"hook_event_name": "Stop"}, Window(self.place, status="working")),
                                ({"hook_event_name": "Stop"}, Window(self.place, box="打ちかけ"))):
            self.assertEqual(self.checker(payload, window)(), wake.HOLD)   # 空にせず、空にできるまで待つ
            self.assertEqual(window.writes, [])
        self.assertNotIn("cleared", gitx.worktree_attrs(self.place))

    def test_fresh_department_that_cannot_be_cleared_holds_the_next_ask(self):
        # 空にできない間は、前の会話のまま次の頼みを渡さない（my_notes の受付 6f32b7 が 26 万トークンの会話のまま渡った）。
        # 渡さない訳は台帳に 1 度だけ残し、空にできたら次のターンに回す
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, gitx)
        self.put("a1")
        place = gitx.git_dir(self.place)
        for payload, window in (({"hook_event_name": "Stop"}, Window(self.place, status="working")),
                                ({"hook_event_name": "Stop"}, Window(self.place, box="打ちかけ")),
                                ({"hook_event_name": "Stop"}, Window(self.place, front=[]))):
            check = self.checker(payload, window)
            self.assertEqual(check(), wake.HOLD)
            self.assertEqual(check(), wake.HOLD)
            self.assertEqual(window.writes, [])
            self.assertEqual(len(wake.queued(self.inbox, place)), 1)
            self.assertEqual(gitx.worktree_attrs(self.place)["ask"], "a0")
        held = [r for r in deliver.records(self.inbox) if r["kind"] == "held"]
        self.assertEqual(len(held), 3)   # 訳ごとに 1 度
        self.assertIn("会話がまだ動いている", held[0]["detail"])
        # 裏の処理が残るだけなら止めない（知らせをこの会話で受ける）。前の会話のまま、訳を頭に付けて渡し、起動し直さない
        tried = []
        kind, text = wake_hook.checker(self.plan(), {"hook_event_name": "Stop", "background_tasks": [{"id": "b"}]}, h=Window(self.place),
                                       now=lambda: 5, me=lambda: ME, restart=lambda got_, key: tried.append(key) or True,
                                       key_of=lambda cwd, a: "other")()
        self.assertEqual(kind, "wake")
        self.assertIn(wake_hook.NOT_CLEARED_BACKGROUND, text.splitlines()[0])
        self.assertEqual(tried, [])
        provision.mark(self.place, self.src, {"delivered": "a1"}, gitx)
        self.put("a2")
        # 会話が前の会話を持って始まった（resume・compact）ときも空にしてから。空で始まった時は渡す
        self.assertEqual(self.checker({"hook_event_name": "SessionStart", "source": "resume"}, Window(self.place, status="working"))(),
                         wake.HOLD)
        got = wake_hook.checker(self.plan(), {"hook_event_name": "SessionStart", "source": "startup"}, h=Window(self.place),
                                now=lambda: 5)
        self.assertEqual(got(), ("wake", "頼みです（受付 a2）"))

    def test_a_held_watcher_tries_again_each_beat_until_it_can_clear(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, gitx)
        self.put("a1")
        w = Window(self.place, status="working", on_clear=self.emptied().on_clear)
        got = self.plan()
        clock = [0.0]

        def pause(sec):
            clock[0] += sec
            if clock[0] > 60:
                raise AssertionError("待ち受けが終わらない")
            if clock[0] > 10:
                w.status = "idle"   # ターンが終わって手が空いた
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            rc = wake.watch(got["inbox"], got["place"], got["names"], "s1", 7, "t1", io.StringIO(), now=lambda: clock[0],
                            pause=pause, parent=lambda: 7, check=wake_hook.checker(got, {"hook_event_name": "Stop"}, h=w,
                                                                                    now=lambda: 5, me=lambda: ME))
        self.assertEqual(rc, 0)
        self.assertEqual(w.writes[0], deliver.CLEAR)
        self.assertEqual(gitx.worktree_attrs(self.place)["cleared"], "a0")
        self.assertEqual(len(wake.queued(self.inbox, gitx.git_dir(self.place))), 1)   # 渡すのは空にした後の待ち受け

    def test_a_resident_talk_is_cleared_at_the_end_of_the_turn_it_marked_a_break(self):
        # 会話を引き継ぐ部署と窓口は、会話が自分で区切りと印した（--rest）ターンの終わりに、機械が窓に /clear を打つ（持ち主が手で打たない）
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s1"}, gitx)
        self.put("a1")
        w = self.emptied()
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(self.checker({"hook_event_name": "Stop", "session_id": "s1"}, w)(), ("end", None))
        self.assertEqual(w.writes[0], deliver.CLEAR)
        self.assertNotIn(wake.REST, gitx.worktree_attrs(self.place))   # 印は 1 度で外れる
        self.assertEqual(len(wake.queued(self.inbox, gitx.git_dir(self.place))), 1)   # 次は空にした後の会話に渡す

    def test_a_break_restarts_the_talk_instead_of_clearing_it_when_the_shape_changed_its_launch(self):
        # 窓口の役の起動の設定を替えたら、区切りのターンの終わりに /clear でなく起動し直す（順番待ちが空でも。持ち主の手で起動し直さない）
        opus = role.launch_key({"model": "opus"})
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s1"}, gitx)
        stop = {"hook_event_name": "Stop", "session_id": "s1"}
        got = self.plan()
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual(wake_hook.restart_due(got, stop, attrs, key_of=lambda cwd, a: opus, at_rest=True), opus)
        self.assertIsNone(wake_hook.restart_due(got, stop, attrs, key_of=lambda cwd, a: opus))   # 区切りでなければ引き継ぐ
        self.assertIsNone(wake_hook.restart_due(got, stop, attrs, key_of=lambda cwd, a: role.launch_key(None), at_rest=True))
        tried, w = [], Window(self.place)
        check = wake_hook.checker(got, stop, h=w, now=lambda: 5, me=lambda: ME,
                                  restart=lambda got_, key: tried.append(key) or True, key_of=lambda cwd, a: opus)
        self.assertEqual(check(), ("end", None))
        self.assertEqual((tried, w.writes), ([opus], []))
        w = self.emptied()   # 起動し直せなければ、前と同じく /clear で空にする
        check = wake_hook.checker(got, stop, h=w, now=lambda: 5, me=lambda: ME, restart=lambda got_, key: False,
                                  key_of=lambda cwd, a: opus)
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(check(), ("end", None))
        self.assertEqual(w.writes[0], deliver.CLEAR)

    def test_a_break_clears_over_a_faint_suggestion_and_says_why_when_it_hands_without_clearing(self):
        # 入力フィールドの薄字（SGR 2）は Claude Code の次の文の候補で、打てば消える。2026-10-18 に my_notes の段取りで、候補を打ちかけと見て
        # 区切りの /clear を 1 時間打たず、訳を残さないまま前の会話に 12 回渡した
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s1"}, gitx)
        self.put("a1")
        stop = {"hook_event_name": "Stop", "session_id": "s1"}
        w = self.emptied()
        w.box = "\x1b[0m\x1b[2m消していいよ\x1b[0m"
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(self.checker(stop, w)(), ("end", None))
        self.assertEqual(w.writes[0], deliver.CLEAR)
        # 人の打ちかけの字は消さない。前の会話のまま渡すなら、空にできなかった訳を会話と台帳に添える
        provision.mark(self.place, self.src, {wake.REST: "s1"}, gitx)
        w = Window(self.place, box="打ちかけ")
        kind, text = self.checker(stop, w)()
        self.assertEqual((kind, w.writes), ("wake", []))
        self.assertTrue(text.startswith("（区切り〔--rest〕で会話を空にできなかったので、前の会話のまま渡す: 窓の入力フィールドに打ちかけの字が在る（「打ちかけ」"), text)
        self.assertTrue(text.endswith("頼みです（受付 a1）"), text)
        handed = [r for r in deliver.records(self.inbox) if r["kind"] == "handed"]
        self.assertIn("打ちかけ", handed[-1]["unrested"])
        self.assertEqual(gitx.worktree_attrs(self.place)[wake.REST], "s1")   # 印は残る（次のターンの終わりにまた試す）

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
        # 人の文でターンが始まったら、区切りの印を外す（人と話している途中の会話を空にしない）
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
        # エフェメラルの部署が終わりと印した（--done）ターンの終わりに、印を外し、--retire を会話から切り離して走らせる（会話を止めるので待たない）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH, wake.FINISHED: "s1"}, gitx)
        seen, spawn = self.spawner()
        w = Window(self.place)
        got = wake_hook.checker(self.plan(), {"hook_event_name": "Stop"}, h=w, now=lambda: 5, spawn=spawn)
        self.assertEqual(got(), ("end", None))
        [(argv, kw)] = seen
        self.assertEqual(argv[1:2] + argv[3:], ["-u", "--retire", "co/調べ"])
        self.assertTrue(kw["start_new_session"])
        self.assertEqual(os.path.realpath(kw["cwd"]), os.path.realpath(self.src))   # 消える部署の場所の外で走らせる
        self.assertTrue(kw["stdout"].name.startswith(os.path.join(self.inbox, wake_hook.RETIRES)))
        self.assertEqual(w.writes, [], "fresh の部署でも /clear は打たない（空にすると印の会話が居なくなる）")
        self.assertNotIn(wake.FINISHED, gitx.worktree_attrs(self.place))   # 印は 1 度で外れる

    @unittest.skipIf(os.name == "nt", "切り離す殻は POSIX だけ")
    def test_retire_apart_from_the_talk_writes_its_exit_code(self):
        # 切り離した --retire の終わりの値を .done に書く（0 でなければ --tree と --todo が出す。前は出力のログしか残らなかった）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1"}, gitx)
        got = {"company": "co", "inbox": self.inbox, "cwd": self.place, "root": self.src}

        def spawn(argv, **kw):   # --retire の代わりに、終わりの値 3 で終わる物を殻で走らせる
            return subprocess.Popen(argv[:argv.index(sys.executable)] + ["/bin/sh", "-c", "echo gone; exit 3"], **kw)
        self.assertTrue(wake_hook.retire_later(got, {"name": "調べ"}, spawn, now=lambda: 7, detach=True))
        done = os.path.join(self.inbox, wake_hook.RETIRES, "調べ-7.done")
        for _ in range(100):
            if os.path.isfile(done) and open(done).read().strip():
                break
            time.sleep(0.05)
        self.assertEqual(open(done).read().strip(), "3")
        self.assertIn("終わりの値 3", "\n".join(health.background(self.inbox, 8)))

    def test_a_finished_mark_waits_for_delivery_background_work_and_the_stop_of_the_turn(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a0", wake.FINISHED: "s1"}, gitx)
        seen, spawn = self.spawner()

        def check(payload):
            return wake_hook.checker(self.plan(), payload, h=Window(self.place), now=lambda: 5, spawn=spawn)()
        self.assertIsNone(check({"hook_event_name": "Stop"}))   # a0 を納品していない
        provision.mark(self.place, self.src, {"delivered": "a0"}, gitx)
        self.assertIsNone(check({"hook_event_name": "Stop", "background_tasks": [{"id": "b"}]}))   # 裏の処理が残る
        self.assertIsNone(check({"hook_event_name": "SessionStart"}))   # ターンの終わりでない
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
        self.assertEqual(self.checker(window=stranger)(), wake.HOLD)   # 印が合っても、前に居るのが別の会話なら打たない
        self.assertEqual(stranger.writes, [])
        attached = Window(self.place, front=[{"pid": ME + 1, "argv": ["claude", "attach", "abcd1234"]}])   # 裏の会話を開いた窓
        self.assertEqual(wake_hook.talk_window(self.place, attached, [ME], ["abcd1234"]), "p1")
        self.assertIsNone(wake_hook.talk_window(self.place, attached, [ME], ["zzzz9999"]))
        no_pid = Window(self.place, front=[{"argv": ["claude"]}])   # 処理の番号の無い行（Windows では自分の番号も取れない）
        self.assertIsNone(wake_hook.talk_window(self.place, no_pid, [None], []))

    def test_the_window_attached_to_this_job_is_found_even_when_the_job_attr_is_old(self):
        # 裏の会話を起動し直すと短い id が替わる（2026-10-17 の割り振り: 属性は a5b0bc07、窓は 8c4a1102 に attach、会話の id は
        # 081f72dd）。フックが継ぐ CLAUDE_JOB_DIR の名前で窓を確かめ、属性も書き直す
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "ask": "a1", "delivered": "a1", "fresh": role.FRESH,
                                              "job": "a5b0bc07"}, gitx)
        self.put("a2")
        self.env["CLAUDE_JOB_DIR"] = "/home/u/.claude/jobs/8c4a1102/"
        got = self.plan()
        self.assertEqual(got["job"], "8c4a1102")
        attached = self.emptied()
        attached.front = [{"pid": ME + 1, "argv": ["claude", "attach", "8c4a1102"]}]
        verdict = wake_hook.checker(got, {"hook_event_name": "Stop"}, h=attached, now=lambda: 5, me=lambda: ME)()
        self.assertEqual(verdict, ("end", None))   # 空にした（空にした後の待ち受けが渡す）
        self.assertEqual(attached.writes, [deliver.CLEAR])
        wake_hook.keep_job(got)
        self.assertEqual(gitx.worktree_attrs(self.place)["job"], "8c4a1102")
        self.assertIsNone(wake_hook.job_of({}))   # 裏の会話でなければ無い

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
        # 裏で走る --pause は答え待ちの印に触らない（同じターンの中で会話が打った --wait より後に走りうる）
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
        # 印を外すのは会話が文を読む前（裏で走らせると、同じターンの中で打った --wait の印を後から外しうる）
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
        if owner:   # 居ない会話の印は古くもする（Windows は処理の番号でなく印の更新の新しさで居るかを見る）
            old = time.time() - wake.FRESH - 60
            os.utime(wake.mark_path(self.inbox, place), (old, old))
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

    @unittest.skipIf(os.name == "nt", "Windows は会話と待ち受けを同じ印の更新の新しさで見るので、会話だけ生きている形を作れない")
    def test_ask_to_a_stopped_department_without_a_running_waiter_says_so(self):
        self.listen("調べ", self.dept_place())
        mark = wake.read_mark(self.inbox, self.dept_place())
        with open(wake.mark_path(self.inbox, self.dept_place()), "w", encoding="utf-8") as f:
            json.dump({**mark, "pid": dead_pid()}, f)   # 会話は生きているが、待ち受けの台本が居ない
        self.ports.herdr.screen = f"{'─' * 20}\n❯ \n{'─' * 20}\n"   # 手の空いた窓（入力フィールドが空）
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "これを調べて")
        self.assertEqual(rc, 0, out)
        self.assertIn("渡す待ち受けが居ない", out)
        self.assertEqual(len(wake.queued(self.inbox, self.dept_place())), 1)
        # 持ち主に打たせず、窓に 1 行打ってターンを回す（ターンの終わりに待ち受けが張り直して渡す）
        self.assertEqual([w[2] for w in self.prompts()], [orders.STUCK_LINE])
        self.assertIn("1 行打ってターンを回した", out)
        nudged = [r for r in deliver.records(self.inbox) if r.get("kind") == "nudged"]
        self.assertEqual([(r["why"], r["id"]) for r in nudged], [("渡す待ち受けが居ない", wake.queued(self.inbox, self.dept_place())[0]["id"])])

    def test_nudge_moves_a_held_department_and_leaves_a_typing_window_alone(self):
        self.listen("調べ", self.dept_place())
        provision.mark(self.place, self.src, {"ask": "a0", "delivered": "a0"}, gitx)
        rc, out = self.main(self.src, "--nudge", "調べ")
        self.assertEqual((rc, self.prompts()), (0, []), out)
        self.assertIn("順番待ちが空", out)   # 止まっていない
        wake.enqueue(self.inbox, self.dept_place(), {"id": "a1", "line": "a1"})
        deliver.log(self.inbox, {"id": "a1", "kind": "held", "place": self.place, "session": "s", "detail": "会話がまだ動いている"})
        rc, out = self.main(self.src, "--nudge", "調べ")
        self.assertEqual((rc, self.prompts()), (1, []), out)   # すぐ替わる訳なら打たない（待ち受けの /clear とぶつけない）
        self.assertIn("訳がすぐ替わる物なので打たなかった", out)
        # 子の返事待ち・裏の処理で止めるのは古い版の待ち受けだけなので、1 行を打って今の版で数え直させる（2026-10-18 の割り振り）
        self.ports.herdr.screen = f"{'─' * 20}\n❯ \n{'─' * 20}\n"
        for detail in ("子の頼みの返事を待っている（受付 c1）", wake_hook.NOT_CLEARED_BACKGROUND):
            deliver.log(self.inbox, {"id": "a1", "kind": "held", "place": self.place, "session": "s", "detail": detail})
            rc, out = self.main(self.src, "--nudge", "調べ")
            self.assertEqual(rc, 0, out)
            self.assertEqual([w[2] for w in self.prompts()], [orders.STUCK_LINE])
            self.ports.herdr.writes.clear()
        deliver.log(self.inbox, {"id": "a1", "kind": "held", "place": self.place, "session": "s", "detail": "窓を確かめられない"})
        provision.mark(self.place, self.src, {"rest": "s"}, gitx)
        self.ports.herdr.screen = f"{'─' * 20}\n❯ 打ちかけ\n{'─' * 20}\n"
        rc, out = self.main(self.src, "--nudge", "調べ")
        self.assertEqual((rc, self.prompts()), (1, []), out)   # 人の打ちかけの字を壊さない
        self.assertIn("入力フィールドに字が在るので打たなかった", out)
        self.ports.herdr.screen = f"{'─' * 20}\n❯ \n{'─' * 20}\n"
        rc, out = self.main(self.src, "--nudge", "調べ")
        self.assertEqual(rc, 0, out)
        self.assertIn("待ち受けが渡さずに待っている（窓を確かめられない）", out)
        self.assertEqual([w[2] for w in self.prompts()], [orders.STUCK_LINE])
        self.assertEqual(gitx.worktree_attrs(self.place).get("rest"), "s")   # 打った 1 行で外れる区切りの印は残す

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

    def test_an_ask_taken_while_the_line_was_being_typed_queues_the_new_one(self):
        # 部署を読んだ時は頼みが無く待ち受けも見えなかったが、打つ前に待ち受けが順番待ちの頼み a1 を渡した。窓に打たずに順番待ちに
        # 積み、a1 の頼み元を残す（2026-10-17 に my_notes の調べもので、後の頼みが前の頼みの頼み元を上書きした。受付 20261017-082903-87f45f）
        provision.mark(self.place, self.src, {"ask": "a0", "delivered": "a0", "boss": "desk"}, gitx)
        self.listen("調べ", self.dept_place(), owner=dead_pid())
        real = orders.live_window

        def handed_meanwhile(dept, ports):
            provision.mark(self.place, self.src, {"ask": "a1", "boss": "段取り"}, gitx)
            return real(dept, ports)
        with mock.patch.object(orders, "live_window", handed_meanwhile):
            rc, out = self.main(self.src, "--ask", "調べ", "--text", "これを調べて")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.prompts(), [])
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["ask"], attrs["boss"]), ("a1", "段取り"))
        (item,) = wake.queued(self.inbox, self.dept_place())
        self.assertEqual((item["marks"]["boss"], deliver.records(self.inbox)[-1]["status"]), ("desk", "queued"))
        self.assertIn("今の頼みの納品の後に待ち受けが渡す", out)

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
        self.assertEqual([(r["id"], r["skipped"], r["to"]["name"]) for r in taken], [(urgent["id"], [first["id"]], attrs["name"])])
        # 記録の行で、受けた部署の会話を知らせと取り違えて起動しない（to が字の行だけが知らせ。設計の 3.1）
        me = wake.address(orders.inbox_company(self.inbox, os.path.dirname(self.cfg)), attrs["name"])
        self.assertFalse([r for r in taken if wake.mine(r, {me})])

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
        self.assertEqual([(r["id"], r["to"], r["name"]) for r in taken], [(urgent["id"], {"ask": "作業"}, "調べ：急ぎ"), (first["id"], {"ask": "作業"}, "調べ：先")])

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

    def test_first_moves_a_queued_ask_to_the_head_and_leaves_it_in_the_ledger(self):
        first, urgent = self.queue_two()
        rc, out = self.main(self.src, "--first", urgent["id"], "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, self.dept_place())], [first["id"], urgent["id"]])
        rc, out = self.main(self.src, "--first", urgent["id"])
        self.assertEqual(rc, 0, out)
        self.assertIn("1 件", out)
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, self.dept_place())], [urgent["id"], first["id"]])
        self.assertEqual(wake.take(self.inbox, self.dept_place())["id"], urgent["id"])   # 待ち受けが渡すのも先頭から
        (moved,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "reordered"]
        self.assertEqual((moved["id"], moved["passed"]), (urgent["id"], [first["id"]]))
        rc, out = self.main(self.src, "--first", urgent["id"])
        self.assertEqual(rc, 2, out)

    def test_note_on_a_queued_ask_rides_on_the_line_it_is_handed_with(self):
        first, urgent = self.queue_two()
        rc, out = self.main(self.src, "--note", first["id"], "--text", "範囲に B も足す")
        self.assertEqual(rc, 0, out)
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, self.dept_place())], [first["id"], urgent["id"]])   # 順は替えない
        handed = wake.take(self.inbox, self.dept_place())
        self.assertIn(first["line"], handed["line"])
        self.assertRegex(handed["line"], rf"\n頼みの足しです（受付 {first['id']} への、desk から。足しの受付 \S+）: 範囲に B も足す")
        (rec,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "note"]
        self.assertEqual((rec["ask"], rec["status"]), (first["id"], "queued"))
        self.assertEqual(self.prompts(), [])

    def test_note_on_a_held_ask_goes_through_the_ledger_and_not_the_window(self):
        # ターンの途中の部署（待ち受けは居ないが跡は在る）にも、窓に打たずに台帳で届く。ターンの終わりの待ち受けが渡す
        provision.mark(self.place, self.src, {"ask": "a0", "boss": "desk"}, gitx)
        to = self.listen("調べ", self.dept_place(), owner=dead_pid())
        rc, out = self.main(self.src, "--note", "a0", "--text", "取り下げる。止めて、どこまで済んだかを返す")
        self.assertEqual(rc, 0, out)
        self.assertIn("ターンの終わりに待ち受けが渡す", out)
        self.assertEqual([w for w in self.ports.herdr.writes if w[0] in ("prompt", "run")], [])
        notice = next(r for r in deliver.records(self.inbox) if isinstance(r.get("to"), str))
        self.assertEqual((notice["to"], notice["kind"]), (to, wake.NOTE))
        self.assertIn("頼みの足しです（受付 a0 への、desk から", notice["text"])
        self.assertIn("取り下げる。止めて", notice["text"])
        (rec,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "note" and not isinstance(r.get("to"), str)]
        self.assertEqual((rec["ask"], rec["status"], rec["to"]["wake"]), ("a0", "noticed", to))

    def test_note_without_a_waiter_types_into_the_window_and_stops_once_delivered(self):
        provision.mark(self.place, self.src, {"ask": "a0", "boss": "desk"}, gitx)
        rc, out = self.main(self.src, "--note", "a0", "--text", "B も見る")
        self.assertEqual(rc, 0, out)
        (typed,) = self.prompts()
        self.assertIn("頼みの足しです（受付 a0 への", str(typed))
        provision.mark(self.place, self.src, {"delivered": "a0"}, gitx)
        rc, out = self.main(self.src, "--note", "a0", "--text", "B も見る")
        self.assertEqual(rc, 2, out)
        self.assertIn("もう納品した", out)
        rc, out = self.main(self.src, "--note", "nope", "--text", "x")
        self.assertEqual(rc, 2, out)
        self.assertIn("どの部署も受けておらず", out)
        rc, out = self.main(self.src, "--note", "a0")
        self.assertEqual(rc, 2, out)

    def test_forward_closes_the_held_ask_without_waking_its_asker_and_links_it_in_the_ledger(self):
        # 窓口が受けた頼みを部署へ回しただけなら、頼み元（社長室）の会話を再開させない。回した先は台帳にだけ結ぶ
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
        (row,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "ask"]
        self.assertEqual((row["id"], row["cause"]), (item["id"], "a0"))   # 頼みの行の親は、打った場所が受けていた頼み
        (link,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "forwarded"]   # 同じ受付箱には 1 行だけ
        self.assertEqual((link["id"], link["child"], link["to"]["name"], link["boss"]["name"]), ("a0", item["id"], "調べ", "社長室"))
        self.assertEqual([r["to"] for r in deliver.records(self.inbox) if isinstance(r.get("to"), str)], [to])   # 社長室への知らせは無い
        self.assertEqual(gitx.worktree_attrs(self.src)["delivered"], "a0")
        # 閉じた後は、もう回す元の頼みが無い
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "別の頼み", "--forward")
        self.assertEqual(rc, 2, out)
        self.assertEqual(len(wake.queued(self.inbox, self.dept_place())), 1)
        # 回して閉じた頼みへの足しは、回した先の頼みに届く（「もう納品した」で止めない）
        rc, out = self.main(self.src, "--note", "a0", "--text", "範囲に B も足す")
        self.assertEqual(rc, 0, out)
        self.assertIn(f"回した先の受付 {item['id']} に足す", out)
        (rec,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "note"]
        self.assertEqual(rec["ask"], item["id"])
        # 回した先も閉じたら止める
        deliver.log(self.inbox, {"id": "f", "kind": "deliver", "ask": item["id"], "at": 9e9, "status": "sent"})
        rc, out = self.main(self.src, "--note", "a0", "--text", "まだ足す")
        self.assertEqual(rc, 2, out)
        self.assertIn("回した先もみな閉じた", out)

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

    def test_deliver_for_returns_a_forwarded_ask_to_its_asker_without_closing_the_one_held_now(self):
        # 窓口が回して閉じた頼み（a0）の結果を返すとき、その後に受けた頼み（a1）は閉じない
        provision.mark(self.src, self.src, {"role": "窓口", "name": "desk", "ask": "a0", "boss": "社長室", "boss-session": "s-boss",
                                            "boss-inbox": self.inbox}, gitx)
        self.listen("調べ", self.dept_place())
        self.assertEqual(self.main(self.src, "--ask", "調べ", "--text", "回す頼み", "--forward")[0], 0)
        (child,) = [r["child"] for r in deliver.records(self.inbox) if r.get("kind") == "forwarded"]
        provision.mark(self.src, self.src, {"ask": "a1", "boss": "持ち主", "boss-session": "s-owner"}, gitx)
        boss = self.listen("社長室", "/elsewhere/.git")
        summary = pathlib.Path(self.root).parent / "summary.md"
        summary.write_text(test_deliver.GOOD, encoding="utf-8")
        rc, out = self.main(self.src, "--deliver", str(summary), "--for", "nope")
        self.assertEqual(rc, 2, out)
        self.assertIn("受付 nope を回して閉じた行", out)
        for key in ("a0", child):   # 回した元の受付でも、回した先の受付でも引ける
            rc, out = self.main(self.src, "--deliver", str(summary), "--for", key)
            self.assertEqual(rc, 0, out)
            notice, rec = deliver.records(self.inbox)[-2:]
            self.assertEqual((notice["to"], notice["id"]), (boss, "a0"))
            self.assertEqual((rec["ask"], rec["for"], rec["to"]["name"], rec["to"]["session"]), ("a0", key, "社長室", "s-boss"))
        attrs = gitx.worktree_attrs(self.src)
        self.assertEqual((attrs["ask"], attrs["delivered"], attrs["boss"]), ("a1", "a0", "持ち主"))   # 今の頼みはそのまま
        rc, out = self.main(self.src, "--for", "a0")
        self.assertEqual(rc, 2, out)
        self.assertIn("--for は --deliver と一緒にだけ使う", out)

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
