"""受付の待ち受けと順番待ち（nodes/wake.py・wake_hook.py）と、--ask・--deliver が待ち受けに知らせる道。
git（tests/fakegit.py）・herdr・claude は偽物で回す（入口を別の処理として起動する HookProcess だけ、git は一時のフォルダの本物）。"""

import contextlib
import io
import json
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest import mock

from . import DISPATCH
from . import fakegit, test_deliver
from .test_provision import git
import gitx
import health
import herdr as real_herdr
import orders
import role_hook
import wake_hook
from ports import chat
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
    Error = real_herdr.Error

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


class Keepalive(unittest.TestCase):
    """keepalive: 仕事が終わらないままターンを終えた会話に、キャッシュの寿命が切れる前に文を渡す（wake_hook.Warm・warm_for）。"""

    def setUp(self):
        self.inbox, self.place, self.cwd = tempfile.mkdtemp(), tempfile.mkdtemp(), tempfile.mkdtemp()
        self.log = os.path.join(self.cwd, "talk.jsonl")
        pathlib.Path(self.log).write_text("{}\n", encoding="utf-8")
        self.got = {"cwd": self.cwd, "inbox": self.inbox, "place": self.place, "session": "s1", "job": None}
        self.payload = {"hook_event_name": "Stop", "session_id": "s1", "transcript_path": self.log,
                        "background_tasks": [{"id": "b1", "type": "shell", "status": "running"},
                                             {"id": "b0", "type": "subagent", "status": "completed"}]}
        self.conf = {"every": 210, "text": "（keepalive）", "ttl": 300, "limit": 2}
        self.clock = [1000.0]
        self.attrs = {"ask": "a1"}   # 納品していない頼みを受けている部署
        quiet = mock.patch.object(wake_hook, "RENT", lambda *a, **k: (None, "試験では部品に聞かない"))   # 決まった数で動く
        quiet.start()
        self.addCleanup(quiet.stop)

    def warm(self, tasks=("b1",)):
        return wake_hook.Warm(self.got, self.payload, self.conf, list(tasks), now=lambda: self.clock[0],
                              attrs_of=lambda cwd: self.attrs)

    def skipped(self):
        return [r["detail"] for r in deliver.records(self.inbox) if r.get("status") == "skipped"]

    def add(self, row, end="\n"):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps(row) + end)

    def test_it_says_the_text_once_the_interval_passes_and_stops_at_the_limit(self):
        warm = self.warm()
        self.clock[0] += 209
        self.assertIsNone(warm())
        self.clock[0] += 1
        self.assertEqual(warm(), "（keepalive）")
        self.assertEqual(wake.warm_state(self.inbox, self.place, "s1", ["b1"]), {"sent": 1, "stopped": False, "spent": 0})
        self.clock[0] += 210
        self.assertEqual(self.warm()(), None)   # 次の待ち受けの時計はその時から
        self.clock[0] += 210
        warm = self.warm()
        self.clock[0] += 210
        self.assertEqual(warm(), "（keepalive）")
        # 同じ会話が同じ物を待つ間は limit 本まで（それより長い待ちは、切れて書き直す 1 回の方が安い）
        warm = self.warm()
        self.clock[0] += 210
        self.assertIsNone(warm())
        self.assertIsNone(warm())
        # 送るたびと、上限で止めた時（1 度だけ）に台帳に残す
        rows = [(r["kind"], r["sent"], r.get("status"), r["ask"]) for r in deliver.records(self.inbox)]
        self.assertEqual(rows, [("keepalive", 1, None, "a1"), ("keepalive", 2, None, "a1"), ("keepalive", 2, "stopped", "a1")])
        # 次のターンの終わりの待ち受けも、控えの止めた印を見て送らず、止めた行を書き足さない
        warm = self.warm()
        self.clock[0] += 210
        self.assertIsNone(warm())
        self.assertEqual(len(deliver.records(self.inbox)), 3)
        # 待つ裏の処理か会話が替われば数え直す
        self.assertEqual(wake.warm_state(self.inbox, self.place, "s1", ["b1", "b2"])["sent"], 0)
        self.assertEqual(wake.warm_state(self.inbox, self.place, "s2", ["b1"])["sent"], 0)

    def test_a_turn_row_added_to_the_transcript_stops_the_wait_and_other_rows_do_not(self):
        warm = self.warm()
        self.clock[0] += 100
        # 止まった会話にも足される行（ターンの終わりのフックの要約・手が空いた会話の要約）と、書きかけの行では止めない
        self.add({"type": "system", "subtype": "stop_hook_summary"})
        self.add({"type": "system", "subtype": "away_summary", "content": '{"type":"user"}'})
        self.add({"type": "assistant", "isSidechain": True, "message": {"content": "サブエージェント"}})
        self.add({"type": "user", "message": {"content": "x"}}, end="")
        self.assertIsNone(warm())
        self.assertEqual(self.skipped(), [])
        with open(self.log, "a", encoding="utf-8") as f:
            f.write("\n")
        self.clock[0] += 110
        self.assertIsNone(warm())   # 書きかけの行が書き終わり、ターンの行と分かった
        self.clock[0] += 210
        self.assertIsNone(warm())   # この待ちでは、もう送らない
        self.assertEqual(deliver.records(self.inbox), [])   # 会話が動いたのは送らなくてよい形なので、台帳に書かない
        warm = self.warm()
        self.add({"type": "system", "subtype": "away_summary"})
        self.clock[0] += 210
        self.assertEqual(warm(), "（keepalive）")   # ターンの行でない行だけなら送る

    def test_it_sends_while_the_window_shows_the_talk_working_on_its_background_work(self):
        # herdr は裏の処理が動く間、ターンを終えた会話も working と出す。窓の状態を見ていた版は 1 本も送らなかった（f55a1b）
        with mock.patch.object(wake_hook, "talk_window", side_effect=AssertionError("窓は見ない")):
            warm = self.warm()
            self.clock[0] += 210
            self.assertEqual(warm(), "（keepalive）")

    def test_it_is_set_at_the_end_of_a_turn_with_the_work_unfinished_and_a_keepalive_written(self):
        conf = lambda cwd, attrs, read: self.conf
        warm = wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: self.attrs)
        self.assertEqual((type(warm), warm.tasks), (wake_hook.Warm, ["b1", "ask:a1"]))
        self.assertEqual(self.skipped(), [])
        # compact を聞ける（部品が答えるか強制の線が分かる）なら、ターンの終わりの判断も聞く。前の版の待ち受けから替わった時は聞かない
        line = lambda got, attrs: (150000, None)
        self.assertTrue(wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: self.attrs, line_of=line).ended)
        self.assertFalse(wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: self.attrs, line_of=line,
                                            again=True).ended)
        self.assertIsNone(wake_hook.warm_for(self.got, self.payload, conf_of=lambda cwd, attrs, read: None, attrs_of=lambda cwd: self.attrs))
        self.assertIsNone(wake_hook.warm_for(self.got, {**self.payload, "hook_event_name": "SessionStart"}, conf_of=conf,
                                             attrs_of=lambda cwd: self.attrs))
        # 裏の処理が無くても、受けた頼みが閉じていなければ送る（持ち主 2026-10-24。my_notes の受付 144229 の足し af82b2）
        idle = {**self.payload, "background_tasks": [{"id": "b0", "status": "completed"}]}
        self.assertEqual(wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: self.attrs).tasks, ["ask:a1"])
        # 一覧の無い版では裏の Bash の数を待つ物に入れる（数えられなくても送る）
        bare = {k: v for k, v in self.payload.items() if k != "background_tasks"}
        self.assertEqual(wake_hook.warm_for(self.got, bare, conf_of=conf, attrs_of=lambda cwd: self.attrs, shells=lambda: 2).tasks,
                         ["count:2", "ask:a1"])
        self.assertEqual(wake_hook.warm_for(self.got, bare, conf_of=conf, attrs_of=lambda cwd: self.attrs, shells=lambda: None).tasks,
                         ["ask:a1"])
        no_log = {k: v for k, v in self.payload.items() if k != "transcript_path"}
        self.assertIsNone(wake_hook.warm_for(self.got, no_log, conf_of=conf, attrs_of=lambda cwd: self.attrs))
        # 送らなかった訳を台帳に残す（ターンの終わりでない SessionStart は残さない）
        self.assertEqual(self.skipped(), ["会社の形の役にも受け持ちにも keepalive が無い（書いていないか、寿命の値が読めない）",
                                          "会話の記録の場所が分からず、会話が動いたかを見られない"])
        # keepalive を書いていない部署の、裏の処理の無いターンの終わりと、頼みの無い部署の裏の処理は台帳に書かない
        wake_hook.warm_for(self.got, idle, conf_of=lambda cwd, attrs, read: None, attrs_of=lambda cwd: self.attrs)
        wake_hook.warm_for(self.got, self.payload, conf_of=lambda cwd, attrs, read: None, attrs_of=lambda cwd: {})
        self.assertEqual(len(self.skipped()), 2)

    def test_a_department_done_with_its_ask_or_marked_to_rest_says_nothing(self):
        conf = lambda cwd, attrs, read: self.conf
        for attrs in ({}, {"ask": "a1", "delivered": "a1"}, {"ask": "a1", "rest": "s1"}, {"ask": "a1", "compact": "s1"},
                      {"ask": "a1", "finished": "s1"}, {"ask": "a1", "restarting": "s1"}):
            self.assertIsNone(wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: attrs), attrs)
        self.assertEqual(self.skipped(), ["頼みを受けておらず、閉じていない出した頼みも保留の頼みも無い",
                                          "今の頼みを納品し、閉じていない出した頼みも保留の頼みも無い", "区切りの印（--rest）が在る",
                                          "区切りの印（--compact）が在る", "終わりの印（--done）が在る",
                                          "起動し直しの印（--move --if-changed）が在る"])
        # 待つ間に納品した・区切りを打ったなら、時計が鳴っても送らない（送る前に属性を読み直す）。この待ちでは、もう送らない
        warm = self.warm()
        self.attrs = {"ask": "a1", "delivered": "a1"}
        self.clock[0] += 210
        self.assertIsNone(warm())
        self.attrs = {"ask": "a2"}
        self.assertIsNone(warm())
        self.assertEqual(self.skipped()[-1:], ["今の頼みを納品し、閉じていない出した頼みも保留の頼みも無い"])
        self.assertEqual(len(self.skipped()), 7)

    def asked(self, child, at=1000.0, session="s1"):
        """この部署（名前「調べ」）が出した頼みの行を台帳に足す。"""
        deliver.log(self.inbox, {"kind": "ask", "id": child, "at": at, "status": "sent",
                                 "from": {"name": "調べ", "place": self.cwd, "session": session}})

    def test_it_sends_while_waiting_for_the_answers_to_asks_it_sent_without_background_work(self):
        # 司令塔のように、部署へ頼みを出して納品を待ちながらターンを終えた会話（裏の処理は無い）にも送る（my_notes の受付 144229）
        conf = lambda cwd, attrs, read: self.conf
        idle = {**self.payload, "background_tasks": []}
        self.asked("c1")
        for attrs, tasks in (({"name": "調べ", "ask": "a1"}, ["ask:a1", "child:c1"]),
                             ({"name": "調べ", "ask": "a1", "delivered": "a1"}, ["child:c1"]), ({"name": "調べ"}, ["child:c1"])):
            warm = wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: attrs, now=lambda: self.clock[0])
            self.assertEqual((type(warm), warm.tasks), (wake_hook.Warm, tasks), attrs)   # 窓口と、納品した部署も
        self.assertEqual(self.skipped(), [])
        self.attrs = {"name": "調べ"}
        warm = wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: self.attrs, now=lambda: self.clock[0])
        self.clock[0] += 210
        self.assertEqual(warm(), "（keepalive）")
        self.assertEqual(wake.warm_state(self.inbox, self.place, "s1", ["child:c1"]), {"sent": 1, "stopped": False, "spent": 0})
        # 保留の頼み（--wait --park）の答えも待つ物に入る。並びが替われば数え直す
        self.attrs = {"name": "調べ", "parked": json.dumps([{"id": "p1"}])}
        self.assertEqual(wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: self.attrs).tasks,
                         ["child:c1", "parked:p1"])
        # 鳴るまでに頼みが閉じたら送らず、訳を残す
        self.attrs = {"name": "調べ"}
        warm = wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: self.attrs, now=lambda: self.clock[0])
        deliver.log(self.inbox, {"kind": "deliver", "ask": "c1", "at": 1100.0})
        self.clock[0] += 210
        self.assertIsNone(warm())
        self.assertEqual(self.skipped(), ["頼みを受けておらず、閉じていない出した頼みも保留の頼みも無い"])

    def test_marks_still_stop_it_and_background_work_and_asks_all_go_into_what_it_waits_for(self):
        conf = lambda cwd, attrs, read: self.conf
        idle = {**self.payload, "background_tasks": []}
        self.asked("c1")
        # 区切り・終わりの印が在れば送らず、訳を残す
        attrs = {"name": "調べ", "ask": "a1", "delivered": "a1", "rest": "s1"}
        self.assertIsNone(wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: attrs))
        self.assertEqual(self.skipped(), ["区切りの印（--rest）が在る"])
        # 待つ物は、裏の処理・受けた頼み・出した頼みを並べる（どれかが替われば数え直す）
        attrs = {"name": "調べ", "ask": "a1"}
        self.assertEqual(wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: attrs).tasks,
                         ["b1", "ask:a1", "child:c1"])
        # keepalive を書いていなければ送らず、台帳にも書かない。前の会話が出した古い頼みは待たない
        self.assertIsNone(wake_hook.warm_for(self.got, idle, conf_of=lambda cwd, a, read: None, attrs_of=lambda cwd: {"name": "調べ"}))
        self.assertEqual(len(self.skipped()), 1)
        deliver.log(self.inbox, {"kind": "deliver", "ask": "c1", "at": 1100.0})
        self.asked("c0", at=10.0, session="s0")
        handed = {"kind": "handed", "id": "a1", "at": 500.0, "place": self.cwd}
        deliver.log(self.inbox, handed)
        self.assertEqual(wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: {"name": "調べ", "ask": "a1"}).tasks,
                         ["ask:a1"])
        # 頼みを受けない窓口は、前の会話が出して閉じていない頼みも待つ
        self.assertEqual(wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: {"name": "調べ"}).tasks, ["child:c0"])
        # 数しか分からない裏の処理も、頼みと並べる
        bare = {k: v for k, v in self.payload.items() if k != "background_tasks"}
        self.assertEqual(wake_hook.warm_for(self.got, bare, conf_of=conf, attrs_of=lambda cwd: {"name": "調べ", "ask": "a2"},
                                            shells=lambda: 2).tasks, ["count:2", "ask:a2", "child:c0"])

    def test_a_department_done_with_its_work_writes_no_skipped_row_at_each_turn_end(self):
        # 納品した後に人と話すだけのターンの終わりは keepalive に関わらないので、台帳を埋めない
        conf = lambda cwd, attrs, read: self.conf
        idle = {**self.payload, "background_tasks": []}
        for attrs in ({"name": "調べ", "ask": "a1", "delivered": "a1"}, {"name": "調べ"}):
            self.assertIsNone(wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: attrs))
        self.assertEqual(self.skipped(), [])
        # 裏の処理を残したなら、送らなかった訳を残す
        self.assertIsNone(wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: {"ask": "a1", "delivered": "a1"}))
        self.assertEqual(self.skipped(), ["今の頼みを納品し、閉じていない出した頼みも保留の頼みも無い"])

    def test_the_model_that_answered_last_sets_the_price_of_a_read(self):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"type": "assistant", "message": {"model": "claude-opus-5-5", "usage": {}}}) + "\n")
            f.write(json.dumps({"type": "user", "message": {"content": "x"}}) + "\n")
        self.assertEqual(chat.last_model(self.payload), "claude-opus-5-5")
        self.assertEqual(chat.read_rate(chat.last_model(self.payload)), 0.05)
        self.assertEqual(chat.read_rate("claude-fable-5-1[1m]"), 0.025)
        self.assertEqual(chat.read_rate(None), chat.CACHE_READ_RATE)
        self.assertIsNone(chat.last_model({"transcript_path": os.path.join(self.cwd, "none.jsonl")}))
        seen = []
        wake_hook.warm_for(self.got, self.payload, conf_of=lambda cwd, attrs, read: seen.append(read), attrs_of=lambda cwd: self.attrs)
        self.assertEqual(seen, [0.05])

    def test_an_error_in_the_clock_stops_only_the_keepalive(self):
        warm = self.warm()
        self.clock[0] += 210
        err = io.StringIO()
        with mock.patch.object(wake, "warm_note", side_effect=OSError("書けない")), mock.patch.object(sys, "stderr", err):
            self.assertIsNone(warm())
        self.assertIn("keepalive の時計が誤りで止まった", err.getvalue())
        self.assertEqual(self.skipped(), ["時計が誤りで止まった（OSError）"])
        self.assertIsNone(warm())   # この待ちではもう送らない

    def test_a_department_left_waiting_on_its_background_work_long_shows_on_the_tree(self):
        attrs = {"ask": "a1", "session": "s1"}
        conf = lambda cwd, a, read: None   # keepalive を書いていなくても控えは書く
        wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: attrs, now=lambda: 1000.0)
        long = wake.LONG_WAIT + 1000.0
        self.assertIsNone(wake.long_wait(self.inbox, self.place, attrs, now=long - 1))
        self.assertEqual(wake.long_wait(self.inbox, self.place, attrs, now=long), {"since": 1000.0, "tasks": 1})
        # 止まった会話にも足される行では、動いたと見ない
        self.add({"type": "system", "subtype": "away_summary"})
        self.assertIsNotNone(wake.long_wait(self.inbox, self.place, attrs, now=long))
        # 納品した・頼みか会話が替わったなら出さない
        for other in ({"ask": "a1", "session": "s1", "delivered": "a1"}, {"ask": "a2", "session": "s1"}, {"ask": "a1", "session": "s2"}):
            self.assertIsNone(wake.long_wait(self.inbox, self.place, other, now=long), other)
        # 会話が動いた（ターンの行が足された）なら出さない（長いターンの途中を待ちと見ない）
        self.add({"type": "user", "message": {"content": "x"}})
        self.assertIsNone(wake.long_wait(self.inbox, self.place, attrs, now=long))
        # 裏の処理を残さずに終えたターンは控えを消す
        wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: attrs, now=lambda: 2000.0)
        self.assertTrue(os.path.exists(wake.waiting_path(self.inbox, self.place)))
        idle = {**self.payload, "background_tasks": []}
        wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: attrs, now=lambda: 2000.0)
        self.assertFalse(os.path.exists(wake.waiting_path(self.inbox, self.place)))
        # 数だけ分かる裏の処理（count:N）は数を出す
        wake.waiting_note(self.inbox, self.place, "s1", "a1", ["count:2"], 0.0, self.log)
        self.assertEqual(wake.long_wait(self.inbox, self.place, attrs, now=long)["tasks"], 2)
        line = "\n".join(tree.lines([{"name": "co", "root": "/co", "info_source": None, "description": None, "skills": [],
                                       "problems": [], "departments": [
                                           {"head_office": False, "state": "done", "sessions": 1, "name": "調べ", "role": None,
                                            "account": None, "boss": None, "panes": [], "branch": "b",
                                            "long_wait": {"since": 1792760000.0, "tasks": 2}}]}]))
        stamp = time.strftime("%m-%d %H:%M", time.localtime(1792760000.0))
        self.assertIn(f"! 裏の処理（2 本）を待ってターンを終えたまま、{stamp} から同じ頼みで会話が動いていない", line)

    def test_a_keepalive_turn_does_not_set_the_long_wait_back(self):
        attrs = {"ask": "a1", "session": "s1"}
        self.attrs = attrs
        conf = lambda cwd, a, read: self.conf
        warm = wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: attrs, now=lambda: self.clock[0])
        self.clock[0] += 210
        self.assertEqual(warm(), "（keepalive）")
        # keepalive のターンが記録に行を足して終わり、同じ裏の処理を待つ
        self.add({"type": "user", "message": {"content": "（keepalive）"}})
        self.add({"type": "assistant", "message": {"content": "waiting"}})
        self.clock[0] += 5
        wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: attrs, now=lambda: self.clock[0])
        later = 1000.0 + wake.LONG_WAIT
        self.assertEqual(wake.long_wait(self.inbox, self.place, attrs, now=later), {"since": 1000.0, "tasks": 1})
        # keepalive でないターン（印の無い控えの後）は時計を進める
        self.add({"type": "user", "message": {"content": "知らせ"}})
        self.clock[0] += 5
        wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: attrs, now=lambda: self.clock[0])
        self.assertIsNone(wake.long_wait(self.inbox, self.place, attrs, now=later))
        # keepalive でないターンの後は、そのターンの終わりから測り直す
        self.assertEqual(wake.long_wait(self.inbox, self.place, attrs, now=self.clock[0] + wake.LONG_WAIT)["since"], self.clock[0])

    def test_a_watcher_taking_over_from_an_older_version_writes_nothing_again(self):
        conf = lambda cwd, a, read: self.conf
        idle = {**self.payload, "background_tasks": []}
        done = {"ask": "a1", "delivered": "a1"}
        self.assertIsNone(wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: done, again=True))
        self.assertIsInstance(wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: self.attrs, again=True),
                              wake_hook.Warm)
        self.assertEqual(deliver.records(self.inbox), [])
        self.assertFalse(os.path.exists(wake.waiting_path(self.inbox, self.place)))

    def test_turned_reads_only_whole_new_lines_and_takes_a_shorter_record_as_moved(self):
        size = os.path.getsize(self.log)
        self.assertEqual(wake.turned(self.log, size), (False, size))
        self.assertEqual(wake.turned(self.log, size + 10), (True, size))   # 記録が作り直された
        self.assertEqual(wake.turned(self.log, -1), (False, -1))   # 読めない位置
        self.assertEqual(wake.turned(os.path.join(self.cwd, "none.jsonl"), 0), (False, 0))
        wake.waiting_note(self.inbox, self.place, "s1", "a1", ["b1"], 0.0, self.log)
        with open(wake.waiting_path(self.inbox, self.place), "w", encoding="utf-8") as f:
            json.dump({"session": "s1", "ask": "a1", "tasks": ["b1"], "at": 0.0, "transcript": self.log, "pos": -5}, f)
        self.assertIsNone(wake.long_wait(self.inbox, self.place, {"ask": "a1", "session": "s1"}, now=wake.LONG_WAIT + 1))

    def test_the_watch_hands_a_notice_before_it_asks_the_clock(self):
        inbox, place, clock = tempfile.mkdtemp(), tempfile.mkdtemp(), [0.0]

        def pause(sec):
            clock[0] += sec
            if clock[0] == 5:
                deliver.log(inbox, {"to": "co/調べ", "id": "d1", "kind": "deliver", "text": "納品が届いた", "at": 1})
            if clock[0] > 60:
                raise AssertionError("待ち受けが終わらない")
        err = io.StringIO()
        rc = wake.watch(inbox, place, ["co/調べ"], "s1", 7, "t1", err, now=lambda: clock[0], pause=pause, parent=lambda: 7,
                        idle=lambda: "（keepalive）" if clock[0] >= 5 else None)
        self.assertEqual(rc, 2)
        self.assertIn("納品が届いた", err.getvalue())
        self.assertNotIn("（keepalive）", err.getvalue())

    def test_the_watch_wakes_with_what_idle_says_when_no_notice_came(self):
        inbox, place, clock, said = tempfile.mkdtemp(), tempfile.mkdtemp(), [0.0], []

        def pause(sec):
            clock[0] += sec
            if clock[0] > 60:
                raise AssertionError("待ち受けが終わらない")

        def idle():
            said.append(clock[0])
            return "（keepalive）" if clock[0] >= 30 else None
        err = io.StringIO()
        rc = wake.watch(inbox, place, ["co/調べ"], "s1", 7, "t1", err, now=lambda: clock[0], pause=pause, parent=lambda: 7, idle=idle)
        self.assertEqual((rc, err.getvalue()), (2, "（keepalive）\n"))

    def planned(self, action="rent", due=None, rent=0.01):
        return {"action": action, "due": due, "rent": rent, "reason": "within_buy_cost" if action == "rent" else "reached_buy_cost",
                "why": "w"}

    def test_the_part_sets_when_to_send_and_when_to_stop(self):
        # 借りるか買うかの部品が答えれば、送る時刻は部品の next_at（due）、止めるのは action が buy のとき（設計書の 6）。
        # 送った分の費用は控えに足し、次の待ちの判断に spent で渡す
        warm = wake_hook.Warm(self.got, self.payload, self.conf, ["b1"], now=lambda: self.clock[0], attrs_of=lambda cwd: self.attrs,
                              plan=self.planned(due=1100.0))
        self.clock[0] = 1099.0
        self.assertIsNone(warm())
        self.clock[0] = 1100.0
        self.assertEqual(warm(), "（keepalive）")
        self.assertEqual(wake.warm_state(self.inbox, self.place, "s1", ["b1"]), {"sent": 1, "stopped": False, "spent": 0.01})
        row = deliver.records(self.inbox)[-1]
        self.assertEqual((row["sent"], row["spent"], row["reason"]), (1, 0.01, "within_buy_cost"))
        warm = wake_hook.Warm(self.got, self.payload, self.conf, ["b1"], now=lambda: self.clock[0], attrs_of=lambda cwd: self.attrs,
                              plan=self.planned("buy", due=1000.0))
        self.assertIsNone(warm())
        row = deliver.records(self.inbox)[-1]
        self.assertEqual((row["status"], row["reason"], row["spent"]), ("stopped", "reached_buy_cost", 0.01))
        self.assertTrue(wake.warm_state(self.inbox, self.place, "s1", ["b1"])["stopped"])
        # 止めた後の待ちは、同じ物を待つ間は送らず、台帳にも書き足さない
        warm = wake_hook.Warm(self.got, self.payload, self.conf, ["b1"], now=lambda: self.clock[0], attrs_of=lambda cwd: self.attrs,
                              plan=self.planned(due=1000.0))
        self.assertIsNone(warm())
        self.assertEqual(len(deliver.records(self.inbox)), 2)

    def test_keepalive_plan_reads_next_at_and_keeps_a_written_interval(self):
        seen = []

        def part(scene, facts, transcript):
            seen.append((scene, facts, transcript))
            return {"action": "rent", "next_at": "2026-10-24T00:04:00Z", "rent": 0.02, "reason": "within_buy_cost", "why": "w"}, None
        with mock.patch.object(wake_hook, "RENT", part):
            plan, why = wake_hook.keepalive_plan(self.payload, self.conf, 0.05, now=lambda: 0)
            self.assertIsNone(why)
            # 判断の記録に結果を結ぶ鍵（会話の id と 8 桁の hex。docs/rent-effect.md）を添える
            self.assertRegex(seen[0][1].pop("key"), r"^s1/[0-9a-f]{8}$")
            self.assertEqual(seen, [("keepalive", {"lifetime": 300, "spent": 0.05, "certain": True,
                                                   "turn_end_at": "1970-01-01T00:00:00Z"}, self.log)])
            self.assertEqual((plan["action"], plan["due"], plan["rent"]), ("rent", 1792800240.0, 0.02))
            # 役か受け持ちに every を書いた場所は、書いた間で送る（止め時だけ部品に聞く）
            plan, _ = wake_hook.keepalive_plan(self.payload, {**self.conf, "written": True}, 0, now=lambda: 0)
            self.assertIsNone(plan["due"])
        # rent か next_at を読めない答えは、聞けなかったのと同じに扱う（費用が数えられないと止め時が来ない）
        for bad in ({"rent": None}, {"rent": -1}, {"next_at": "あした"}):
            with mock.patch.object(wake_hook, "RENT", lambda *a, bad=bad: ({"action": "rent", "next_at": "2026-10-24T00:04:00Z",
                                                                            "rent": 0.02, **bad}, None)):
                plan, why = wake_hook.keepalive_plan(self.payload, self.conf, 0, now=lambda: 0)
            self.assertIsNone(plan)
            self.assertIn("借りるか買うかの部品の答えの", why)
        # 部品が答えなければ訳を返す（Warm は every と limit で動き、台帳の行に訳を添える）
        plan, why = wake_hook.keepalive_plan(self.payload, self.conf, 0)
        self.assertEqual((plan, why), (None, "試験では部品に聞かない"))
        warm = wake_hook.warm_for(self.got, self.payload, conf_of=lambda cwd, attrs, read: self.conf, attrs_of=lambda cwd: self.attrs,
                                  now=lambda: self.clock[0])
        self.clock[0] += 210
        self.assertEqual(warm(), "（keepalive）")
        self.assertEqual(deliver.records(self.inbox)[-1]["fixed"], "試験では部品に聞かない")

    def test_compact_is_judged_with_or_without_background_work(self):
        # 裏の処理を残したターンの終わりの待ちでも compact を聞く（知らせは compact の後の会話に届く。my_notes の受付 807aee）
        answer = ({"action": "rent", "next_at": "2026-10-24T00:04:00Z", "rent": 0.01, "reason": "within_buy_cost", "why": "w"}, None)
        conf = lambda cwd, attrs, read: self.conf
        with mock.patch.object(wake_hook, "RENT", lambda *a, **k: answer):
            self.assertTrue(wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: self.attrs).compact)
            idle = {**self.payload, "background_tasks": []}
            self.assertTrue(wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: self.attrs).compact)
        # 部品が答えなくても、強制の線が分かれば送る時刻に compact を聞く（線に着いていれば打つ。compact_judge）
        with mock.patch.object(wake_hook, "RENT", lambda *a, **k: (None, "部品が入っていない")):
            warm = wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: self.attrs,
                                      line_of=lambda got, attrs: (800000, None))
            self.assertEqual((warm.compact, warm.line), (True, 800000))
            self.assertFalse(wake_hook.warm_for(self.got, idle, conf_of=conf, attrs_of=lambda cwd: self.attrs,
                                                line_of=lambda got, attrs: (None, "書いていない")).compact)
            # 裏の処理が残る間も、線が分かれば聞く
            self.assertTrue(wake_hook.warm_for(self.got, self.payload, conf_of=conf, attrs_of=lambda cwd: self.attrs,
                                               line_of=lambda got, attrs: (800000, None)).compact)


class Late(unittest.TestCase):
    """待ち行列に残った知らせで会話が再開しないときに、待ち受けが遅れて送る止まる前の差し戻し（wake_hook.Late・late_for）。"""

    def setUp(self):
        self.cwd = tempfile.mkdtemp()
        self.log = os.path.join(self.cwd, "talk.jsonl")
        self.add({"type": "assistant"}, {"type": "queue-operation", "operation": "enqueue", "content": "<task-notification>"})
        self.got = {"cwd": self.cwd, "inbox": tempfile.mkdtemp(), "place": tempfile.mkdtemp(), "session": "s1", "job": None}
        self.payload = {"hook_event_name": "Stop", "session_id": "s1", "cwd": self.cwd, "transcript_path": self.log, "background_tasks": []}
        self.attrs = {"role": "担当", "ask": "a1"}
        self.clock, self.asked = [1000.0], []

    def add(self, *rows):
        with open(self.log, "a", encoding="utf-8") as f:
            f.write("".join(json.dumps(r) + "\n" for r in rows))

    def late(self, nudge="差し戻し"):
        return wake_hook.Late(self.got, self.payload, lambda cwd: self.attrs, lambda: self.clock[0],
                              nudge=lambda payload, cwd, attrs: self.asked.append(attrs["ask"]) or nudge)

    def test_it_sends_the_hooks_nudge_once_when_the_turn_does_not_resume(self):
        late = self.late()
        self.clock[0] += wake_hook.LATE_WAIT - 1
        self.assertIsNone(late())
        self.clock[0] += 1
        self.assertEqual(late(), wake_hook.LATE_NOTE + "差し戻し")
        self.assertEqual(self.asked, ["a1"])
        self.clock[0] += 600
        self.assertIsNone(late(), "1 度だけ（次はそのターンの終わりの Stop フックが決める）")
        def broken(payload, cwd, attrs):
            raise OSError("git が読めない")
        late = wake_hook.Late(self.got, self.payload, lambda cwd: self.attrs, lambda: self.clock[0], nudge=broken)
        self.clock[0] += wake_hook.LATE_WAIT
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertIsNone(late(), "差し戻しを決められなくても待ち受けは止めない")
        self.assertIn("git が読めない", err.getvalue())
        def unreadable(cwd):
            raise OSError("作業場の属性が読めない")
        late = wake_hook.Late(self.got, self.payload, unreadable, lambda: self.clock[0], nudge=broken)
        self.clock[0] += wake_hook.LATE_WAIT
        with contextlib.redirect_stderr(io.StringIO()) as err:
            self.assertIsNone(late(), "属性を読めなくても待ち受けは止めない")
        self.assertIn("作業場の属性が読めない", err.getvalue())

    def test_a_turn_started_by_the_notice_or_a_closed_ask_sends_nothing(self):
        late = self.late()
        self.add({"type": "queue-operation", "operation": "dequeue"}, {"type": "user", "message": {"content": "<task-notification>"}})
        self.clock[0] += wake_hook.LATE_WAIT
        self.assertIsNone(late())
        late, self.attrs = self.late(), {"role": "担当"}
        self.clock[0] += wake_hook.LATE_WAIT
        self.assertIsNone(late())
        self.assertEqual(self.asked, [])
        late, self.attrs = self.late(nudge=None), {"role": "担当", "ask": "a1"}
        self.clock[0] += wake_hook.LATE_WAIT
        self.assertIsNone(late(), "差し戻しが要らない（使い切った・納品の後で残ってよい）なら送らない")

    def test_it_uses_the_stop_hooks_nudge_and_count(self):
        tmp = tempfile.mkdtemp()
        late = wake_hook.Late(self.got, self.payload, lambda cwd: self.attrs, lambda: self.clock[0])
        self.clock[0] += wake_hook.LATE_WAIT
        with mock.patch.object(tempfile, "gettempdir", lambda: tmp):
            text = late()
        self.assertIn("You have not delivered ask a1 yet", text)
        self.assertEqual(pathlib.Path(deliver.stop_count_path(tmp, "s1", "a1")).read_text(encoding="utf-8"), "1", "Stop フックと同じ控えで数える")

    def test_at_the_limit_it_leaves_the_stopped_notice_instead(self):
        # Stop フックが差し戻しを使い切った後なら、送らずに頼み元へ止まった知らせを置く（Stop フックと同じ 1 度だけ）
        tmp, sent = tempfile.mkdtemp(), []
        count = pathlib.Path(deliver.stop_count_path(tmp, "s1", "a1"))
        count.parent.mkdir(parents=True, exist_ok=True)
        count.write_text(str(deliver.STOP_LIMIT), encoding="utf-8")
        late = wake_hook.Late(self.got, self.payload, lambda cwd: self.attrs, lambda: self.clock[0])
        self.clock[0] += wake_hook.LATE_WAIT
        with mock.patch.object(tempfile, "gettempdir", lambda: tmp), \
                mock.patch.object(orders, "stalled", lambda attrs, settings, company_of=None: sent.append(attrs["ask"])):
            self.assertIsNone(late())
        self.assertEqual(sent, ["a1"])
        self.assertEqual(count.read_text(encoding="utf-8"), str(deliver.STOP_LIMIT + 1), "2 度は知らせない")

    def test_after_delivery_it_uses_the_leftover_nudge_and_its_own_count(self):
        tmp, seen = tempfile.mkdtemp(), []
        self.attrs = {**self.attrs, "delivered": "a1"}
        late = wake_hook.Late(self.got, self.payload, lambda cwd: self.attrs, lambda: self.clock[0])
        self.clock[0] += wake_hook.LATE_WAIT
        def after(payload, cwd, attrs, count, settings, g, rearm=None, gh=None):
            seen.append(count)
            return "main に入れていない"
        with mock.patch.object(tempfile, "gettempdir", lambda: tmp), mock.patch.object(orders, "stop_after", after):
            self.assertEqual(late(), wake_hook.LATE_NOTE + "main に入れていない")
        self.assertEqual(seen, [0])
        self.assertEqual(pathlib.Path(deliver.stop_count_path(tmp, "s1", "a1-after")).read_text(encoding="utf-8"), "1")
        self.assertFalse(os.path.exists(deliver.stop_count_path(tmp, "s1", "a1")), "納品の前の控えは進めない")

    def test_it_is_set_only_when_the_hook_let_the_turn_end_for_a_queued_notice(self):
        late_for = lambda payload=None, attrs=None, shells=lambda: 0, again=False: wake_hook.late_for(
            self.got, payload or self.payload, lambda cwd: attrs or self.attrs, shells, again)
        self.assertIsInstance(late_for(), wake_hook.Late)
        self.assertIsNone(late_for(again=True), "今の版に替わった待ち受けは、ターンの終わりの時刻を知らないので送らない")
        self.assertIsInstance(late_for({k: v for k, v in self.payload.items() if k != "background_tasks"}, shells=lambda: None),
                              wake_hook.Late, "裏の処理の数が分からなくても、待ち行列で Stop フックが差し戻さなかったなら送る")
        self.assertIsNone(late_for({**self.payload, "background_tasks": [{"id": "b1", "status": "running"}]}),
                          "裏の処理が動いている間は、終わるまで何時間でも待つ")
        self.assertIsNone(late_for(attrs={"role": "担当"}))
        self.assertIsNone(late_for(attrs={"ask": "a1"}))
        self.assertIsNone(late_for({**self.payload, "hook_event_name": "SessionStart"}))
        self.add({"type": "queue-operation", "operation": "dequeue"})
        self.assertIsNone(late_for(), "待ち行列が空なら Stop フックが差し戻している")


class Hook(unittest.TestCase):
    """入口 wake_hook.py: 部署と窓口でだけ待ち、同じ場所の別の会話は待たない。順番待ちを渡し、fresh の部署を空にする。"""

    def setUp(self):
        # git は偽物（tests/fakegit.py）。会社 co は origin の無い clone で、部署「dept」はメインブランチから切った worktree
        d = pathlib.Path(tempfile.mkdtemp())
        self.g = fakegit.FakeGit(str(d / "co"), {}, url="")
        self.g.origin.clear()
        self.g.tracking.clear()
        self.g.has_origin_head = False
        self.src = self.g.source
        self.place = self.g.add_worktree(str(d / "dept"), "dept/a", "main")
        self.repos = fakegit.Repos(self.g)   # フックの git の口（ほかの会社の clone を足せる）
        fakegit.wire(self, self.repos, wake_hook, role_hook, orders)
        self.inbox = deliver.inbox_of(self.g.common_dir(self.src))
        self.env = {"WORKS_DISPATCH_CONFIG": "/none/c.toml"}
        quiet = mock.patch.object(wake_hook, "RENT", lambda *a, **k: (None, "試験では部品に聞かない"))   # 決まった数で動く
        quiet.start()
        self.addCleanup(quiet.stop)

    def plan(self, sid="s1", parent=lambda: 7, cwd=None, same=lambda pid: False):
        return wake_hook.plan({"cwd": cwd or self.place, "session_id": sid}, env=self.env, parent=parent, same=same)

    def test_waits_only_in_a_named_department_and_names_the_company(self):
        self.assertIsNone(self.plan())
        provision.mark(self.place, self.src, {"role": "作業"}, self.g)
        self.assertIsNone(self.plan())   # 名前が無ければ宛てられない
        provision.mark(self.place, self.src, {"name": "調べ", "former-names": '["前"]'}, self.g)
        got = self.plan()
        self.assertEqual(got["names"], ["co/調べ", "co/前"])
        self.assertEqual(os.path.realpath(got["inbox"]), os.path.realpath(self.inbox))
        self.assertFalse(got["adopt"])

    def test_the_desk_needs_its_conversation_id(self):
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口"}, self.g)
        self.assertIsNone(self.plan(cwd=self.src))   # 代表の clone のほかの会話に横取りさせない
        provision.mark(self.src, self.src, {"session": "s1"}, self.g)
        self.assertEqual(self.plan(cwd=self.src)["names"], ["co/窓口"])

    def test_another_talk_at_the_place_does_not_wait_but_the_same_process_after_clear_does(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1"}, self.g)
        self.assertIsNone(self.plan(sid="s9"))   # 同じ場所で開いた別の会話
        place = self.g.git_dir(self.place)
        wake.claim(self.inbox, place, ["co/調べ"], "s1", 7, "t", 0)
        self.assertIsNone(self.plan(sid="s9", parent=lambda: 8))   # 別の処理の会話
        self.assertTrue(self.plan(sid="s9")["adopt"])   # 同じ処理が /clear で会話の id を替えた

    def test_the_desk_follows_a_clear_in_its_own_process_without_the_mark(self):
        # 窓口の /clear で前の待ち受けが TERM を受けて印を消しても、--desk が書いた会話の処理の会話なら続きと見る
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s1", "pid": "7"}, self.g)
        self.assertIsNone(self.plan(sid="s9", cwd=self.src))   # 会話の処理が違う（持ち主のほかの会話）
        self.assertTrue(self.plan(sid="s9", cwd=self.src, same=lambda pid: pid == "7")["adopt"])
        # 部署は印で見分ける（部署の場所には会話の処理の番号が無い。--desk は部署の worktree で止まり、写った物は --task が消す）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1"}, self.g)
        self.assertIsNone(self.plan(sid="s9", same=lambda pid: True))

    def test_a_fresh_department_is_not_cleared_while_an_ask_it_made_has_no_answer(self):
        # 受けた頼みも、そこから出した子の頼みも全部閉じたターンの終わりに空にする（持ち主の承認 dc0aa2。標準 6c364c が子の納品を待つ間）
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, self.g)
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
                                              "fresh": role.FRESH, "session": "s1"}, self.g)
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
        self.assertEqual(wake_hook.open_children(self.plan(), self.g.worktree_attrs(self.place)), ["c1"])
        provision.mark(self.place, self.src, {"session": "s2"}, self.g)   # compact・resume で会話の id が替わっても数える
        self.assertEqual(wake_hook.open_children(self.plan(sid="s2"), self.g.worktree_attrs(self.place)), ["c1"])
        # 空にしてから渡した頼み（kept の無い handed）より前の物は、前の会話の子なので数えない
        deliver.log(self.inbox, {"kind": "handed", "id": "a2", "at": 9, "place": self.place, "session": "s3"})
        provision.mark(self.place, self.src, {"session": "s3", "ask": "a2"}, self.g)
        self.assertEqual(wake_hook.open_children(self.plan(sid="s3"), self.g.worktree_attrs(self.place)), [])

    def test_children_count_only_since_the_ask_and_close_only_in_what_the_waiter_has_read(self):
        attrs = {"name": "調べ", "ask": "a0"}
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ"}, self.g)
        got = self.plan()
        log = lambda r: deliver.log(self.inbox, r)   # noqa: E731
        log({"kind": "ask", "id": "old", "status": "queued", "at": 1, "from": {"name": "調べ", "place": self.place}})   # 前の会話の古い頼み
        log({"kind": "handed", "id": "a0", "at": 5, "place": self.place})
        log({"kind": "ask", "id": "c1", "status": "queued", "at": 6, "from": {"name": "調べ", "place": os.path.join(self.place, "sub")}})
        self.assertEqual(wake_hook.open_children(got, attrs), ["c1"])   # 今の頼みを受けた後の物だけ（作業場の下のフォルダも）
        place = self.g.git_dir(self.place)
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
        self.g.add_worktree(path, branch, "main")
        provision.mark(path, self.src, attrs, self.g)
        return path

    def asked(self, ask_id, frm, frm_place, dest, at=2):
        """frm（場所 frm_place）が dest の部署へ頼み、dest の順番待ちに積まれたまま。"""
        deliver.log(self.inbox, {"kind": "ask", "id": ask_id, "status": "queued", "at": at, "from": {"name": frm, "place": frm_place},
                                 "to": {"company": "co", "path": dest}})
        wake.enqueue(self.inbox, self.repos.git_dir(dest), {"id": ask_id, "line": f"頼みです（受付 {ask_id}）", "marks": {"ask": ask_id}})

    def listens(self, path, name):
        wake.claim(self.inbox, self.g.git_dir(path), [f"co/{name}"], f"s-{name}", 7, f"t-{name}", 0)

    @staticmethod
    def ring(edges):
        """knot の返りから、場所を除いた (受付, 頼んだ部署, 積まれた部署) の並び。"""
        return [e[:3] for e in edges]

    def test_two_held_departments_waiting_on_each_other_untie_the_oldest_ask_of_the_ring(self):
        # 調べは点検への c1 の返事を、点検は調べへの q1 の返事を、どちらも今の頼みを納品せずに待ち、順番待ちを渡さない（2026-10-18 の my_notes）
        held = {"role": "担当", "fresh": role.FRESH}
        provision.mark(self.place, self.src, {**held, "name": "調べ", "ask": "a0"}, self.g)
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
        provision.mark(self.place, self.src, {**held, "name": "調べ", "ask": "a0"}, self.g)
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
        provision.mark(self.place, self.src, {**held, "name": "調べ", "ask": "a0"}, self.g)
        other = self.dept("dept/b", **held, name="点検", ask="b0")
        review = self.dept("dept/c", **held, name="見直し", ask="c0")
        self.asked("20261018-000003-aaaaaa", "調べ", self.place, other)
        self.asked("20261018-000002-bbbbbb", "点検", other, self.place)
        self.asked("20261018-000001-cccccc", "点検", other, review)
        for path, name in ((other, "点検"), (review, "見直し")):
            self.listens(path, name)
        edges = wake_hook.knot(self.plan(), self.g.worktree_attrs(self.place), ["20261018-000003-aaaaaa"])
        self.assertEqual(self.ring(edges), [("20261018-000002-bbbbbb", "点検", "調べ"), ("20261018-000003-aaaaaa", "調べ", "点検")])

    def test_overlapping_rings_pick_the_same_ask_from_every_department(self):
        # 割り振り ⇄ 点検 の輪と、点検 → 見直し → 割り振り の輪が重なる。どの部署から見ても、重なった輪の全体の一番古い頼みを回す
        held = {"role": "担当", "fresh": role.FRESH}
        provision.mark(self.place, self.src, {**held, "name": "割り振り", "ask": "a0"}, self.g)
        check_ = self.dept("dept/b", **held, name="点検", ask="b0")
        review = self.dept("dept/c", **held, name="見直し", ask="c0")
        self.asked("20261018-000005-aaaaaa", "割り振り", self.place, check_)
        self.asked("20261018-000004-bbbbbb", "点検", check_, self.place)
        self.asked("20261018-000001-cccccc", "点検", check_, review)
        self.asked("20261018-000003-dddddd", "見直し", review, self.place)
        for path, name in ((self.place, "割り振り"), (check_, "点検"), (review, "見直し")):
            self.listens(path, name)
        here = wake_hook.knot(self.plan(), self.g.worktree_attrs(self.place), ["20261018-000005-aaaaaa"])
        got = wake_hook.plan({"cwd": review, "session_id": "s-見直し"}, env=self.env, parent=lambda: 7, same=lambda pid: False)
        there = wake_hook.knot(got, self.g.worktree_attrs(review), ["20261018-000003-dddddd"])
        self.assertEqual(self.ring(here)[0], ("20261018-000001-cccccc", "点検", "見直し"))
        self.assertEqual(self.ring(there)[0], ("20261018-000001-cccccc", "点検", "見直し"))
        self.assertEqual([e[0] for e in here], ["20261018-000001-cccccc", "20261018-000003-dddddd", "20261018-000005-aaaaaa"])

    def test_no_ring_when_a_department_on_the_way_carries_its_conversation_over(self):
        # 会話を引き継ぐ部署は、納品し終えれば順番待ちを渡すので、止まっていると見ない
        held = {"role": "担当", "fresh": role.FRESH}
        provision.mark(self.place, self.src, {**held, "name": "調べ", "ask": "a0"}, self.g)
        other = self.dept("dept/b", role="担当", name="点検", ask="b0", delivered="b0")
        self.asked("c1", "調べ", self.place, other)
        self.asked("q1", "点検", other, self.place)
        self.listens(other, "点検")
        self.assertIsNone(wake_hook.knot(self.plan(), self.g.worktree_attrs(self.place), ["c1"]))

    def test_a_ring_through_three_departments_with_an_undelivered_one_in_the_middle_is_found_from_each(self):
        # 割り振りは今の頼みを納品せずに点検への c1 の返事を待ち、点検は見直しへの c2 を、見直しは割り振りへの c3 を待つ（10-18 の
        # claude-plugins。輪の途中に、納品していない keep の担当が入る）
        held = {"role": "担当", "fresh": role.FRESH}
        provision.mark(self.place, self.src, {**held, "name": "割り振り", "ask": "a0"}, self.g)   # 納品していない
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
        provision.mark(self.place, self.src, {**held, "name": "割り振り", "ask": "a0"}, self.g)
        src2 = os.path.join(os.path.dirname(self.place), "co2")
        g2 = fakegit.FakeGit(src2, {}, url="")
        self.repos.gits.append(g2)
        other = g2.add_worktree(os.path.join(os.path.dirname(self.place), "notes"), "dept/n", "main")
        provision.mark(other, src2, {**held, "name": "調べもの", "ask": "n0"}, g2)
        inbox2 = deliver.inbox_of(g2.common_dir(src2))
        # 頼みの行は頼んだ側の会社の受付箱に、順番待ちは受ける側の会社の受付箱に在る
        self.asked("c1", "割り振り", self.place, other)
        os.unlink(wake.find(self.inbox, "c1")["path"])
        wake.enqueue(inbox2, g2.git_dir(other), {"id": "c1", "marks": {"ask": "c1"}})
        deliver.log(inbox2, {"kind": "ask", "id": "q1", "status": "queued", "at": 2, "from": {"name": "調べもの", "place": other},
                             "to": {"company": "co", "path": self.place}})
        wake.enqueue(self.inbox, self.g.git_dir(self.place), {"id": "q1", "marks": {"ask": "q1"}})
        wake.claim(inbox2, g2.git_dir(other), ["co2/調べもの"], "s2", 7, "t2", 0)
        edges = wake_hook.knot(self.plan(), self.g.worktree_attrs(self.place), ["c1"])
        self.assertEqual(self.ring(edges), [("c1", "割り振り", "調べもの"), ("q1", "調べもの", "割り振り")])
        runs = []
        wake_hook.untie(self.plan(), edges, spawn=lambda argv, **kw: runs.append((argv, kw["cwd"])), now=lambda: 9, detach=False)
        argv, cwd = runs[0]
        # 作業の部署は、頼みが積まれていた部署の会社（co2）に立てる。--take もその会社の代表の clone で打つ
        self.assertEqual(argv[argv.index("--ask") + 1], f"{os.path.basename(src2)}/作業")
        self.assertEqual(os.path.realpath(cwd), os.path.realpath(src2))

    def test_no_ring_once_the_ask_has_been_handed(self):
        held = {"role": "担当", "fresh": role.FRESH}
        provision.mark(self.place, self.src, {**held, "name": "調べ", "ask": "a0"}, self.g)
        other = self.dept("dept/b", **held, name="点検", ask="b0")
        self.asked("c1", "調べ", self.place, other)
        self.asked("q1", "点検", other, self.place)
        self.listens(other, "点検")
        wake.take(self.inbox, self.g.git_dir(other))   # 点検が c1 を受けた（動いている）
        self.assertIsNone(wake_hook.knot(self.plan(), self.g.worktree_attrs(self.place), ["c1"]))

    def test_untie_takes_the_ask_to_a_task_named_after_its_owner_and_logs_the_ring(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ"}, self.g)
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
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ"}, self.g)
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
                                              "fresh": role.FRESH}, self.g)
        stop = {"hook_event_name": "Stop", "session_id": "s1"}
        self.assertFalse(wake_hook.must_clear(stop, self.g.worktree_attrs(self.place)))   # 空にした後
        err = io.StringIO()
        out = wake_hook.WithRole(err, {"session_id": "s1"}, changed=lambda payload: None, woke=lambda: wake_hook.woken(self.plan()))
        out.write("納品です（受付 d1）\n")
        self.assertNotIn("cleared", self.g.worktree_attrs(self.place))
        self.assertTrue(wake_hook.must_clear(stop, self.g.worktree_attrs(self.place)))   # 起動されたターンの終わりに空にする
        provision.mark(self.place, self.src, {"cleared": "a0", "fresh": None}, self.g)   # 会話を引き継ぐ役では外さない
        wake_hook.woken(self.plan())
        self.assertEqual(self.g.worktree_attrs(self.place)["cleared"], "a0")

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
        return Window(self.place, on_clear=lambda: wake.claim(self.inbox, self.g.git_dir(self.place), ["co/調べ"], "s-new", 7, "t2", 0))

    def put(self, ask_id, **marks):
        wake.enqueue(self.inbox, self.g.git_dir(self.place), {"id": ask_id, "line": f"頼みです（受付 {ask_id}）",
                                                             "marks": {"ask": ask_id, "boss": "窓口", **marks}})

    def test_hands_the_next_ask_only_after_the_last_one_was_delivered(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "ask": "a0"}, self.g)
        self.put("a1", **{"ask-digest": "d1"})
        self.assertIsNone(self.checker()())   # a0 を納品していない
        provision.mark(self.place, self.src, {"delivered": "a0"}, self.g)
        self.assertEqual(self.checker()(), ("wake", "頼みです（受付 a1）"))
        attrs = self.g.worktree_attrs(self.place)
        self.assertEqual((attrs["ask"], attrs["boss"], attrs["ask-digest"]), ("a1", "窓口", "d1"))
        self.assertEqual(deliver.records(self.inbox)[-1]["kind"], "handed")
        self.assertIsNone(self.checker()())   # 渡した物は順番待ちから消える

    def with_origin(self):
        """self.src に origin を付け、メインブランチを push する。origin に（ほかの clone から）commit を足す関数を返す。"""
        self.g.url = str(pathlib.Path(self.src).parent / "origin.git")
        self.g.origin["main"] = self.g.tracking["main"] = self.g.local["main"]
        self.g.has_origin_head = True

        def land(rel, text="x"):
            self.g.push_origin("main", {rel: text}, rel)
        return land

    def test_a_persistent_department_follows_the_main_branch_before_the_next_ask_and_restarts_for_its_agents(self):
        # keep の部署の作業場は頼みのたびに作り直さないので、渡す前にメインブランチの先頭へ進める。役の定義が替われば、
        # 同じアカウントのまま起動し直す名指しを印す（2026-10-20、my_notes の調べものが 20 commit 遅れた。受付 72f7e4）
        land = self.with_origin()
        land("notes.md")
        same = role.launch_key(None)
        self.fresh_dept(lifecycle=gitx.PERSISTENT, account="a1", launched=same)
        stop = {"hook_event_name": "Stop"}
        # 裏の処理が動いている間は、その足元のファイルを替えない。黙らず、進めていないことと遅れを渡す字と台帳に添える
        # （2026-10-21 に my_notes の調べものが、裏の処理が残ったまま遅れた作業場で頼みを受け、followed の行も無かった。受付 35aa1b）
        self.put("a0b")
        busy = {**stop, "background_tasks": [{"id": "b"}]}
        seen = []
        check = wake_hook.checker(self.plan(), busy, h=Window(self.place), now=lambda: 5, me=lambda: ME, restart=lambda got_, key: False,
                                  key_of=lambda cwd, a: same, follow=lambda got_, attrs: seen.append(1))
        head = self.g.head_sha(self.place)
        verdict, text = check()
        self.assertEqual(verdict, "wake")
        self.assertEqual(seen, [])
        self.assertEqual(self.g.head_sha(self.place), head)
        row = deliver.records(self.inbox)[-1]
        self.assertIn("進めていない（main に有って作業場のブランチに無い commit が 1 個）", row["followed"])
        self.assertTrue(text.startswith(f"（{row['followed']}）\n"), text)
        self.assertIn("git merge --ff-only origin/main", row["followed"])
        self.assertEqual([r["next"] for r in deliver.records(self.inbox) if r.get("kind") == "followed"], ["a0b"])
        provision.mark(self.place, self.src, {"delivered": "a0b", "cleared": "a0b"}, self.g)
        self.put("a1")
        check = wake_hook.checker(self.plan(), stop, h=Window(self.place), now=lambda: 5, me=lambda: ME,
                                  restart=lambda got_, key: False, key_of=lambda cwd, a: same)
        verdict, text = check()
        self.assertEqual(verdict, "wake")
        followed = deliver.records(self.inbox)[-1]["followed"]   # 進めたことを、渡す字の頭と台帳の handed の行に添える
        self.assertTrue(text.startswith(f"（{followed}）\n"), text)
        self.assertIn("1 個の commit を取り込んだ", followed)
        self.assertEqual(self.g.head_sha(self.place), self.g.rev(self.src, "origin/main"))
        self.assertNotIn(wake.MOVE_TO, self.g.worktree_attrs(self.place))   # 起動するときに読むファイルは替わっていない
        # 役の定義が替われば、今のアカウントの名指しを印す（区切りの --move --if-changed が同じアカウントのまま起動し直す）
        land(".claude/agents/調べ.md")
        provision.mark(self.place, self.src, {"delivered": "a1", "cleared": "a1"}, self.g)
        self.put("a2")
        got = wake_hook.follow_main(self.plan(), self.g.worktree_attrs(self.place))
        self.assertIn(".claude/agents/調べ.md", got)
        self.assertIn("同じアカウントのまま起動し直してから渡す", got)
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.MOVE_TO], "a1")
        self.assertIsNone(wake_hook.follow_main(self.plan(), self.g.worktree_attrs(self.place)))   # もう先頭を含む
        # 会社の形だけの替わりは、起動の設定と役の文が別に見るので名指ししない
        provision.mark(self.place, self.src, {wake.MOVE_TO: None}, self.g)
        land(".claude/company.toml")
        self.assertNotIn("起動し直", wake_hook.follow_main(self.plan(), self.g.worktree_attrs(self.place)))
        self.assertNotIn(wake.MOVE_TO, self.g.worktree_attrs(self.place))
        # ほかのアカウントへ移す名指しは書き替えない
        provision.mark(self.place, self.src, {wake.MOVE_TO: "a2"}, self.g)
        land(".claude/settings.json")
        wake_hook.follow_main(self.plan(), self.g.worktree_attrs(self.place))
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.MOVE_TO], "a2")

    def test_a_persistent_department_restarts_on_the_same_account_when_following_changed_its_agents(self):
        # 進めて役の定義が替わったら、待ち受けは渡す前に、同じアカウントのまま起動し直す（--move の名指しの道。受付 c149fa と 72f7e4）
        land = self.with_origin()
        land(".claude/agents/調べ.md")
        d = tempfile.mkdtemp()
        cfg = os.path.join(d, "c.toml")
        pathlib.Path(cfg).write_text(f"limits_dir = '{d}'\naccounts = [{{ name = \"a1\", command = \"c1\" }}]\n", encoding="utf-8")
        pathlib.Path(d, "a1.json").write_text(json.dumps({"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 10}}),
                                              encoding="utf-8")
        same = role.launch_key(None)
        self.fresh_dept(lifecycle=gitx.PERSISTENT, account="a1", launched=same, config=cfg)
        self.put("a1")
        tried = []
        check = wake_hook.checker(self.plan(), {"hook_event_name": "Stop"}, h=Window(self.place), now=lambda: 5, me=lambda: ME,
                                  restart=lambda got_, key: tried.append(key) or True, key_of=lambda cwd, a: same)
        self.assertEqual(check(), ("end", None))   # 起動し直した会話の待ち受けが渡す
        self.assertEqual(tried, [same])
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.MOVE_TO], "a1")
        (row,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "followed"]   # 渡す行が無くても、進めたことは残す
        self.assertIn(".claude/agents/調べ.md", row["detail"])
        self.assertEqual(len(wake.queued(self.inbox, self.g.git_dir(self.place))), 1)

    def test_a_persistent_department_with_commits_not_on_the_main_branch_is_not_moved(self):
        # 書きかけの作業（メインブランチに無い commit）は書き換えず、受けた会話に訳を渡す
        land = self.with_origin()
        land(".claude/agents/調べ.md")
        self.g.commit(self.place, {}, "wip")
        head = self.g.head_sha(self.place)
        attrs = self.fresh_dept(lifecycle=gitx.PERSISTENT, account="a1")
        got = wake_hook.follow_main(self.plan(), attrs)
        self.assertIn("main に無い commit が 1 個在るので", got)
        self.assertEqual(self.g.head_sha(self.place), head)
        self.assertNotIn(wake.MOVE_TO, self.g.worktree_attrs(self.place))
        # 読めなくても頼みは渡す（訳を添える）
        self.assertIn("進められなかった", wake_hook.follow_main(self.plan(), attrs, catch_up=lambda cwd: 1 / 0))
        # tmp の部署（頼みごとにメインブランチから切る）と窓口は進めない
        self.assertIsNone(wake_hook.follow_main(self.plan(), {**attrs, "lifecycle": gitx.EPHEMERAL}))
        # 裏の処理が動いていて進めないときの文（lag_note）も、作業場を動かさず、同じ場所では添えない
        got = wake_hook.lag_note(self.plan(), attrs)
        self.assertIn("commit が 1 個）", got)
        self.assertIn("main に無い commit が 1 個在るので、fast-forward では進められない", got)   # 書きかけなら進めると書かない
        self.assertNotIn("merge --ff-only", got)
        self.assertEqual(self.g.head_sha(self.place), head)
        self.assertIn("確かめられなかった", wake_hook.lag_note(self.plan(), attrs, count=lambda cwd: 1 / 0))
        self.assertIsNone(wake_hook.lag_note(self.plan(), attrs, count=lambda cwd: {"main": "main", "ahead": 1, "behind": 0}))
        self.assertIsNone(wake_hook.lag_note(self.plan(), {**attrs, "lifecycle": gitx.EPHEMERAL}))
        # 空にできずに待つ間（5 秒ごとに見直す）も、進めるのと台帳の行は順番待ちの先頭の頼みごとに 1 度
        provision.mark(self.place, self.src, {"cleared": None}, self.g)   # 前の頼みの後をまだ空にしていない
        self.put("a1")
        seen = []
        check = wake_hook.checker(self.plan(), {"hook_event_name": "Stop"}, h=Window(self.place, status="working"), now=lambda: 5,
                                  me=lambda: ME, restart=lambda got_, key: False, key_of=lambda cwd, a: None,
                                  follow=lambda got_, a: seen.append(1) or "訳")
        self.assertEqual((check(), check()), (wake.HOLD, wake.HOLD))
        self.assertEqual(seen, [1])
        self.assertEqual([r["next"] for r in deliver.records(self.inbox) if r.get("kind") == "followed"], ["a1"])

    def test_a_persistent_department_restarts_when_it_cannot_tell_what_following_changed(self):
        # 進めた後に替わったファイルを比べられなければ、起動し直す側に倒す（進めたのに進められなかったとは書かない）
        land = self.with_origin()
        land("notes.md")
        attrs = self.fresh_dept(lifecycle=gitx.PERSISTENT, account="a1")

        real = self.g

        class G:
            def __getattr__(self, name):
                return getattr(real, name)

            def changed_paths(self, *a):
                raise gitx.GitError("読めない")
        got = wake_hook.follow_main(self.plan(), attrs, catch_up=lambda cwd: provision.follow_main(cwd, G()))
        self.assertIn("比べられなかった", got)
        self.assertEqual(self.g.head_sha(self.place), self.g.rev(self.src, "origin/main"))
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.MOVE_TO], "a1")

    def test_adopting_a_batch_then_following_still_restarts_for_changed_agents(self):
        # 束の写しを受け取って（adopt_batch）から進めた回も、起動するときにしか読まないファイルが替われば起動し直す（受け取りの後で道を分けない）
        attrs = self.fresh_dept(lifecycle=gitx.PERSISTENT, account="a1")
        rows = iter([{"status": "local_only", "main": "main", "ahead": 1, "behind": 1},
                     {"status": "updated", "main": "main", "behind": 2, "startup": [".claude/agents/x.md"]}])
        got = wake_hook.follow_main(self.plan(), attrs, catch_up=lambda cwd: next(rows), adopt=lambda *a: "took")
        self.assertEqual(got.split("。")[0], "took", got)
        self.assertIn("作業場のブランチを main の先頭へ進めた", got)
        self.assertIn("（.claude/agents/x.md）が替わった", got)
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.MOVE_TO], "a1")
        rows = iter([{"status": "local_only", "main": "main", "ahead": 1, "behind": 1}, {"status": "current", "main": "main"}])
        self.assertEqual(wake_hook.follow_main(self.plan(), attrs, catch_up=lambda cwd: next(rows), adopt=lambda *a: "took"), "took")

    def test_does_not_hand_the_next_ask_when_one_arrived_after_it_looked(self):
        # 上で属性を読んだ後に、--ask が窓に別の頼みを打って属性を書いた。錠の中で読み直し、渡さずに順番待ちに残す（渡すと、
        # 後に書いた頼み元が前の頼みの頼み元を上書きする。my_notes の受付 20261017-082903-87f45f）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "ask": "a0", "delivered": "a0"}, self.g)
        self.put("a1")
        reads = []

        def attrs_of(cwd):
            reads.append(cwd)
            if len(reads) == 2:   # 錠の中の読み直しの前に、ほかの道が頼みを書いた
                provision.mark(self.place, self.src, {"ask": "b1", "boss": "段取り"}, self.g)
            return self.g.worktree_attrs(cwd)
        check = wake_hook.checker(self.plan(), {"hook_event_name": "Stop"}, h=Window(self.place), now=lambda: 5, me=lambda: ME,
                                  attrs_of=attrs_of)
        self.assertIsNone(check())
        attrs = self.g.worktree_attrs(self.place)
        self.assertEqual((attrs["ask"], attrs["boss"]), ("b1", "段取り"))
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, self.g.git_dir(self.place))], ["a1"])

    def test_fresh_department_is_cleared_when_it_stops_after_delivering(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, self.g)
        self.put("a1")
        w = self.emptied()
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(self.checker(window=w)(), ("end", None))   # 渡すのは空にした後の会話の始まりの待ち受け
        self.assertEqual(w.writes[0], deliver.CLEAR)
        self.assertEqual(self.g.worktree_attrs(self.place)["cleared"], "a0")
        self.assertEqual(len(wake.queued(self.inbox, self.g.git_dir(self.place))), 1)
        # 空にした後（SessionStart）は渡す
        got = wake_hook.checker(self.plan(), {"hook_event_name": "SessionStart"}, h=Window(self.place), now=lambda: 5)
        self.assertEqual(got(), ("wake", "頼みです（受付 a1）"))

    def test_a_clear_not_seen_to_empty_the_talk_keeps_this_watcher_holding(self):
        # /clear を打っても空になったのを見られなければ、空にした印を書かず、この待ち受けが続いて空にするのを試し直す（空にした
        # つもりで終わると、次の待ち受けが張られず順番待ちが止まる。2026-10-17 に my_notes のノートの手入れで約 70 分止まった）
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, self.g)
        self.put("a1")
        w = Window(self.place)
        check = self.checker(window=w)
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(check(), wake.HOLD)   # 終わらない（"end" なら、この待ち受けの後を継ぐ者が居ない）
        self.assertEqual(w.writes[0], deliver.CLEAR)
        self.assertNotIn("cleared", self.g.worktree_attrs(self.place))
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.CLEAR_TYPED], "s1")   # 打つ前に、打った会話を書く（own_clear）
        held = [r for r in deliver.records(self.inbox) if r["kind"] == "held"]
        self.assertIn("空になったのを見られない", held[0]["detail"])
        w.on_clear = self.emptied().on_clear   # 試し直しで空になった
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(check(), ("end", None))
        self.assertEqual(self.g.worktree_attrs(self.place)["cleared"], "a0")
        self.assertNotIn(wake.CLEAR_TYPED, self.g.worktree_attrs(self.place))

    def test_a_clear_the_watcher_typed_but_left_unsent_is_sent_and_not_held_as_typed_text(self):
        # 2026-10-20 に my_notes の調べもので、待ち受けが打った /clear が、会話がまた動き出したターンの間に送られずに入力フィールドに残り、
        # 次の試しからはその字（「/clear [name]」。[name] は Claude Code の引数の候補で、薄字で描かれない）を人の打ちかけと見て、
        # 順番待ちの 5 件が 3 時間渡らなかった。打った会話の印（company.clear-typed）と字が合えば Enter で送り、打ち足さない
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH, "session": "s1"}, self.g)
        self.put("a1")
        attrs = {"session": "s1", wake.CLEAR_TYPED: "s1"}
        self.assertTrue(wake.own_clear("/clear", attrs))
        self.assertTrue(wake.own_clear("/clear [name]", attrs))
        self.assertTrue(wake.own_clear("/clear [name]", {wake.CLEAR_TYPED: "s2"}, "s2"))
        for box, typed_in in (("/clear [name]", None),   # 待ち受けが打った跡が無い（人が打った）
                              ("/clear [name]", "s0"),   # 前の会話で打った物
                              ("/clear 覚え書き", "s1"),   # 人が後ろに打ち足した
                              ("/clear [a] 覚え書き [b]", "s1"),
                              ("/clearx", "s1")):
            provision.mark(self.place, self.src, {wake.CLEAR_TYPED: typed_in}, self.g)
            w = Window(self.place, box=box)
            self.assertEqual(self.checker(window=w)(), wake.HOLD, box)
            self.assertEqual(w.writes, [], box)
        provision.mark(self.place, self.src, {wake.CLEAR_TYPED: "s1"}, self.g)
        w = Window(self.place, box="/clear [name]")
        empty = self.emptied().on_clear
        w.send_keys = lambda pane, *keys: (w.writes.append(keys), keys == ("enter",) and empty())
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(self.checker(window=w)(), ("end", None))
        self.assertEqual(w.writes, [("enter",)])   # /clear を打ち足さない（打ち足すと /clear/clear になる）
        attrs = self.g.worktree_attrs(self.place)
        self.assertEqual(attrs["cleared"], "a0")
        self.assertNotIn(wake.CLEAR_TYPED, attrs)

    def test_keepalive_is_read_from_the_shape_for_a_department_and_the_desk(self):
        os.makedirs(os.path.join(self.src, ".claude"), exist_ok=True)
        toml = ('[[roles]]\nname = "担当"\nkeepalive = true\n[roles.settings]\npromptCacheTtl = "5m"\n\n'
                '[[skills]]\nname = "調べ"\nrole = "担当"\nkeepalive = {{ every = "3m" }}\n{more}')
        shape = os.path.join(self.src, ".claude", "company.toml")
        pathlib.Path(shape).write_text(toml.format(more=""), encoding="utf-8")
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ"}, self.g)
        got = role_hook.keepalive_of(self.place, self.g.worktree_attrs(self.place), env=self.env)
        self.assertEqual((got["every"], got["ttl"], got["limit"]), (180, 300, 13))
        # 上限は会話のモデルのキャッシュの読みの値段で決める（Opus 5.5 は 0.05 倍で 25 本）
        self.assertEqual(role_hook.keepalive_of(self.place, self.g.worktree_attrs(self.place), env=self.env, read=0.05)["limit"], 25)
        # 窓口も読む（頼みは受けないが、出した頼みの返事を待つ間に送る）。窓口は部署でないので受け持ちを引かず、役の値で決める
        self.assertEqual(role_hook.keepalive_of(self.src, {"role": "担当", "name": "調べ"}, env=self.env)["every"], 300 - role.KEEPALIVE_MARGIN)
        # 寿命の値を読めなければ、黙って 1 時間と見ずに送らず、訳を注記に出す
        pathlib.Path(shape).write_text(toml.format(more='settings = { promptCacheTtl = "10m" }\n'), encoding="utf-8")
        err = io.StringIO()
        with mock.patch.object(sys, "stderr", err):
            self.assertIsNone(role_hook.keepalive_of(self.place, self.g.worktree_attrs(self.place), env=self.env))
        self.assertIn("'10m'", err.getvalue())

    def fresh_dept(self, **more):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0", "cleared": "a0",
                                              "fresh": role.FRESH, "job": "j1", **more}, self.g)
        return self.g.worktree_attrs(self.place)

    def test_a_parked_ask_keeps_the_conversation_from_being_cleared_or_restarted(self):
        # --wait --park の保留が在る間は、空にも起動し直しもしない（保留の答えを返す会話の中身が消える）
        opus = role.launch_key({"model": "opus"})
        attrs = self.fresh_dept(launched=role.launch_key(None), cleared=None)
        self.put("a1")
        got, stop = self.plan(), {"hook_event_name": "Stop", "session_id": "s1"}
        self.assertEqual(wake_hook.restart_due(got, stop, attrs, key_of=lambda cwd, a: opus), opus)
        self.assertTrue(wake_hook.must_clear(stop, attrs))
        parked = {**attrs, deliver.PARKED: json.dumps([{"id": "c1", "boss": "段取り"}])}
        self.assertIsNone(wake_hook.restart_due(got, stop, parked, key_of=lambda cwd, a: opus))
        self.assertIsNone(wake_hook.restart_due(got, stop, parked, key_of=lambda cwd, a: opus, at_rest=True))
        self.assertFalse(wake_hook.must_clear(stop, parked))

    def test_a_break_clears_the_talk_even_with_a_parked_ask(self):
        # 会話が自分で区切りと印した（--rest）なら、保留が在っても空にする。保留の一覧と返し方は空にした後の会話の始まりに足される
        # （my_notes の司令塔が、持ち主の席外しが長いときに始め直せるように。受付 7b8dff）
        parked = json.dumps([{"id": "c1", "boss": "段取り", "why": "持ち主の答え"}], ensure_ascii=False)
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s1",
                                              deliver.PARKED: parked}, self.g)
        w = self.emptied()
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(self.checker({"hook_event_name": "Stop", "session_id": "s1"}, w)(), ("end", None))
        self.assertEqual(w.writes[0], deliver.CLEAR)
        attrs = self.g.worktree_attrs(self.place)
        self.assertNotIn(wake.REST, attrs)
        self.assertIn("受付 c1", role_hook.parked_text(attrs))

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
        self.assertEqual(len(wake.queued(self.inbox, self.g.git_dir(self.place))), 1)
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
        # 作業場がブランチに居ない部署は起動し直せないので、--move を走らせない（move._unbranched）
        branch = self.g.heads[os.path.realpath(self.place)]
        self.g.heads[os.path.realpath(self.place)] = None
        self.assertIsNone(wake_hook.restart_due(got, stop, attrs, key_of=lambda cwd, a: same, early_of=lambda g, a: True))
        self.g.heads[os.path.realpath(self.place)] = branch
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
        self.assertTrue(wake_hook.early_due(got, {**here, "account": "a2", wake.MOVE_TO: "a2"}, env={}))   # 今のアカウントの名指し（そのまま起動し直す）
        self.assertFalse(wake_hook.early_due(got, {**here, "config": os.path.join(d, "無い.toml")}, env={}))   # 設定が無ければ控えも無い
        self.assertFalse(wake_hook.early_due(got, {**here, wake.MOVE_KEPT: "a2"}, env={}))   # 前に起動できなかった先は選ばない
        # 目安に達したのに移す先が無ければ、訳を台帳に 1 度だけ残す
        provision.mark(self.place, self.src, {"config": cfg}, self.g)
        for _ in range(2):
            self.assertFalse(wake_hook.early_due(got, {**self.g.worktree_attrs(self.place), wake.MOVE_KEPT: "a2"}, env={}))
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
                                              "boss": "段取り", "boss-inbox": boss_inbox}, self.g)
        brief = os.path.join(self.g.git_dir(self.place), "move-brief.md")
        pathlib.Path(brief).write_text("起動し直した。受けている頼みは無い。次の頼みを待つ。\n", encoding="utf-8")
        talk = os.path.join(self.place, "t.jsonl")
        pathlib.Path(talk).write_text('{"content": "move-brief.md を読んで進めてください。"}\n', encoding="utf-8")
        stop = {"hook_event_name": "Stop", "transcript_path": talk}
        kind, text = self.checker(stop)()
        self.assertEqual(kind, "wake")
        self.assertIn("受付 q1、段取り から", text)
        self.assertIn("本文は 段取り に問い合わせる", text)   # 本文のファイルが無ければ、無いパスを指さない
        pathlib.Path(boss_inbox, "q1-ask.md").write_text("頼み", encoding="utf-8")
        self.assertIn(os.path.join(boss_inbox, "q1-ask.md"), wake_hook.again_text(self.g.worktree_attrs(self.place), "/d.py"))
        self.assertIn("--deliver", text)
        (again,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "handed"]
        self.assertEqual((again["id"], again["session"]), ("q1", "s1"))
        self.assertTrue(again["again"])
        self.assertIsNone(self.checker(stop)())   # 同じ会話へは 1 度まで
        self.assertIsNone(self.checker({**stop, "transcript_path": None})())   # 記録の場所が無ければ届いたと見る

    def test_an_ask_the_talk_saw_is_not_handed_again(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "q1", "delivered": "q0", "session": "s1"}, self.g)
        talk = os.path.join(self.place, "t.jsonl")
        stop = {"hook_event_name": "Stop", "transcript_path": talk}
        pathlib.Path(talk).write_text('{"content": "頼みです（受付 q1）"}\n', encoding="utf-8")
        self.assertIsNone(self.checker(stop)())
        # --move の最初の文で渡した頼み（move-brief.md に受付が在る）
        pathlib.Path(talk).write_text('{"content": "move-brief.md を読んで進めてください。"}\n', encoding="utf-8")
        pathlib.Path(self.g.git_dir(self.place), "move-brief.md").write_text("受け持ちの頼み（受付 q1）を続ける", encoding="utf-8")
        self.assertIsNone(self.checker(stop)())
        # 頼みを持つ会話がこの会話でなければ見ない
        pathlib.Path(talk).write_text("{}\n", encoding="utf-8")
        got = self.plan()
        self.assertTrue(wake_hook.unseen(got, stop, self.g.worktree_attrs(self.place)))
        provision.mark(self.place, self.src, {"session": "s9"}, self.g)
        self.assertFalse(wake_hook.unseen(got, stop, self.g.worktree_attrs(self.place)))
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
            self.assertEqual(self.g.worktree_attrs(self.place)[wake.RESTARTING], "j1")   # 走らせる前に印を付ける
            return Done()
        self.assertFalse(wake_hook.restart_first(got, opus, spawn=spawn, now=lambda: 5))
        (argv, cwd), = seen
        self.assertEqual(argv[1:], ["-u", wake_hook.DISPATCH_PY, "--move", "co/調べ", "--if-changed"])
        self.assertEqual(cwd, self.place)
        attrs = self.g.worktree_attrs(self.place)
        self.assertNotIn(wake.RESTARTING, attrs)
        self.assertEqual(attrs[wake.RESTART_KEPT], opus)   # 同じ値では試し直さない

        def stopped(argv, **kw):   # --move が前の会話を止めて印を外した
            provision.mark(self.place, self.src, {wake.RESTARTING: None}, self.g)
            return Done()
        self.assertTrue(wake_hook.restart_first(got, opus, spawn=stopped, now=lambda: 5))

        class Later:   # --move が今は起動し直さない（ターンの途中・打ちかけの字）で終わった
            def poll(self):
                return wake.NOT_NOW
        provision.mark(self.place, self.src, {wake.RESTART_KEPT: None}, self.g)
        self.assertFalse(wake_hook.restart_first(got, opus, spawn=lambda argv, **kw: Later(), now=lambda: 5))
        attrs = self.g.worktree_attrs(self.place)
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
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s0"}, self.g)
        tried, w = [], Window(self.place)
        check = wake_hook.checker(self.plan(), {"hook_event_name": "Stop", "session_id": "s1"}, h=w, now=lambda: 5, me=lambda: ME,
                                  restart=lambda got_, key: tried.append(key) or True, key_of=lambda cwd, a: opus)
        self.assertIsNone(check())
        self.assertEqual((tried, w.writes), ([], []))

    def test_fresh_department_is_not_cleared_while_busy_typed_or_waiting_on_background_work(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, self.g)
        for payload, window in (({"hook_event_name": "Stop", "background_tasks": [{"id": "b"}]}, Window(self.place)),
                                ({"hook_event_name": "Stop"}, Window(self.place, status="working")),
                                ({"hook_event_name": "Stop"}, Window(self.place, box="打ちかけ"))):
            self.assertEqual(self.checker(payload, window)(), wake.HOLD)   # 空にせず、空にできるまで待つ
            self.assertEqual(window.writes, [])
        self.assertNotIn("cleared", self.g.worktree_attrs(self.place))

    def test_fresh_department_that_cannot_be_cleared_holds_the_next_ask(self):
        # 空にできない間は、前の会話のまま次の頼みを渡さない（my_notes の受付 6f32b7 が 26 万トークンの会話のまま渡った）。
        # 渡さない訳は台帳に 1 度だけ残し、空にできたら次のターンに回す
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, self.g)
        self.put("a1")
        place = self.g.git_dir(self.place)
        for payload, window in (({"hook_event_name": "Stop"}, Window(self.place, status="working")),
                                ({"hook_event_name": "Stop"}, Window(self.place, box="打ちかけ")),
                                ({"hook_event_name": "Stop"}, Window(self.place, front=[]))):
            check = self.checker(payload, window)
            self.assertEqual(check(), wake.HOLD)
            self.assertEqual(check(), wake.HOLD)
            self.assertEqual(window.writes, [])
            self.assertEqual(len(wake.queued(self.inbox, place)), 1)
            self.assertEqual(self.g.worktree_attrs(self.place)["ask"], "a0")
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
        provision.mark(self.place, self.src, {"delivered": "a1"}, self.g)
        self.put("a2")
        # 会話が前の会話を持って始まった（resume・compact）ときも空にしてから。空で始まった時は渡す
        self.assertEqual(self.checker({"hook_event_name": "SessionStart", "source": "resume"}, Window(self.place, status="working"))(),
                         wake.HOLD)
        got = wake_hook.checker(self.plan(), {"hook_event_name": "SessionStart", "source": "startup"}, h=Window(self.place),
                                now=lambda: 5)
        self.assertEqual(got(), ("wake", "頼みです（受付 a2）"))

    def test_a_held_watcher_tries_again_each_beat_until_it_can_clear(self):
        provision.mark(self.place, self.src, {"role": "担当", "name": "調べ", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH}, self.g)
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
        self.assertEqual(self.g.worktree_attrs(self.place)["cleared"], "a0")
        self.assertEqual(len(wake.queued(self.inbox, self.g.git_dir(self.place))), 1)   # 渡すのは空にした後の待ち受け

    def test_a_resident_talk_is_cleared_at_the_end_of_the_turn_it_marked_a_break(self):
        # 会話を引き継ぐ部署と窓口は、会話が自分で区切りと印した（--rest）ターンの終わりに、機械が窓に /clear を打つ（持ち主が手で打たない）
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s1"}, self.g)
        self.put("a1")
        w = self.emptied()
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(self.checker({"hook_event_name": "Stop", "session_id": "s1"}, w)(), ("end", None))
        self.assertEqual(w.writes[0], deliver.CLEAR)
        self.assertNotIn(wake.REST, self.g.worktree_attrs(self.place))   # 印は 1 度で外れる
        self.assertEqual(len(wake.queued(self.inbox, self.g.git_dir(self.place))), 1)   # 次は空にした後の会話に渡す

    def test_a_break_restarts_the_talk_instead_of_clearing_it_when_the_shape_changed_its_launch(self):
        # 窓口の役の起動の設定を替えたら、区切りのターンの終わりに /clear でなく起動し直す（順番待ちが空でも。持ち主の手で起動し直さない）
        opus = role.launch_key({"model": "opus"})
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s1"}, self.g)
        stop = {"hook_event_name": "Stop", "session_id": "s1"}
        got = self.plan()
        attrs = self.g.worktree_attrs(self.place)
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
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s1"}, self.g)
        self.put("a1")
        stop = {"hook_event_name": "Stop", "session_id": "s1"}
        w = self.emptied()
        w.box = "\x1b[0m\x1b[2m消していいよ\x1b[0m"
        with mock.patch.object(wake_hook.deliver, "CONFIRM_LOOKS", 1):
            self.assertEqual(self.checker(stop, w)(), ("end", None))
        self.assertEqual(w.writes[0], deliver.CLEAR)
        # 人の打ちかけの字は消さない。前の会話のまま渡すなら、空にできなかった訳を会話と台帳に添える
        provision.mark(self.place, self.src, {wake.REST: "s1"}, self.g)
        w = Window(self.place, box="打ちかけ")
        kind, text = self.checker(stop, w)()
        self.assertEqual((kind, w.writes), ("wake", []))
        self.assertTrue(text.startswith("（区切り〔--rest〕で会話を空にできなかったので、前の会話のまま渡す: 窓の入力フィールドに打ちかけの字が在る（「打ちかけ」"), text)
        self.assertTrue(text.endswith("頼みです（受付 a1）"), text)
        handed = [r for r in deliver.records(self.inbox) if r["kind"] == "handed"]
        self.assertIn("打ちかけ", handed[-1]["unrested"])
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.REST], "s1")   # 印は残る（次のターンの終わりにまた試す）

    def test_a_break_is_not_cleared_with_an_open_ask_typed_text_or_outside_stop(self):
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s1"}, self.g)
        for payload, window in (({"hook_event_name": "Stop"}, Window(self.place, box="打ちかけ")),   # 持ち主が打っている途中
                                ({"hook_event_name": "Stop"}, Window(self.place, status="working")),
                                ({"hook_event_name": "SessionStart"}, Window(self.place))):
            self.assertIsNone(self.checker(payload, window)())
            self.assertEqual(window.writes, [])
        provision.mark(self.place, self.src, {"ask": "a0"}, self.g)   # 納品していない頼みが在る
        w = Window(self.place)
        self.assertIsNone(self.checker(window=w)())
        self.assertEqual(w.writes, [])
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.REST], "s1")

    def test_a_break_before_delivery_moves_the_talk_marked_to_move_and_never_clears_it(self):
        # --move がターンの途中で移せずに移す印（company.move-to）を付けても、区切り（--rest）は納品の後にしか打てず、頼みが長いと移す時が
        # 来なかった（受付 f39d00）。印の在る会話は納品の前でも区切りで移り、新しい会話が頼みを続ける。頼みの途中の会話は空にしない
        opus = role.launch_key({"model": "opus"})
        provision.mark(self.place, self.src, {"role": "担当", "name": "割り振り", "session": "s1", "ask": "a0", wake.REST: "s1",
                                              wake.MOVE_TO: "a2", wake.LAUNCHED: opus}, self.g)
        stop = {"hook_event_name": "Stop", "session_id": "s1"}
        got = self.plan()
        tried, w = [], Window(self.place)
        check = wake_hook.checker(got, stop, h=w, now=lambda: 5, me=lambda: ME,
                                  restart=lambda got_, key: tried.append(key) or True, key_of=lambda cwd, a: opus)
        with mock.patch.object(wake_hook, "early_due", lambda got_, attrs: bool(attrs.get(wake.MOVE_TO))):
            self.assertEqual(check(), ("end", None))
            self.assertEqual((tried, w.writes), ([opus], []))
            check = wake_hook.checker(got, stop, h=w, now=lambda: 5, me=lambda: ME, restart=lambda got_, key: False,
                                      key_of=lambda cwd, a: opus)
            self.assertIsNone(check())   # 移せなければ、空にせず、この会話のまま続ける
        self.assertEqual(w.writes, [])
        self.assertNotIn(wake.REST, self.g.worktree_attrs(self.place))

    def test_a_typed_prompt_takes_the_break_mark_off(self):
        # 人の文でターンが始まったら、区切りの印を外す（人と話している途中の会話を空にしない）
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.REST: "s1"}, self.g)
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s9"})   # 場所のほかの会話の文では外さない
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.REST], "s1")
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s1"})
        self.assertNotIn(wake.REST, self.g.worktree_attrs(self.place))

    def transcript(self, tokens):
        path = os.path.join(tempfile.mkdtemp(), "t.jsonl")
        with open(path, "w", encoding="utf-8") as f:
            f.write(json.dumps({"type": "user", "message": {"content": "x"}}) + "\n")
            f.write(json.dumps({"type": "assistant", "message": {"usage": {
                "input_tokens": 10, "cache_read_input_tokens": tokens - 110, "cache_creation_input_tokens": 100}}}) + "\n")
        return path

    def test_a_compact_break_types_compact_and_the_talk_after_it_is_told_to_go_on(self):
        # 会話が --compact で印したターンの終わりに、待ち受けが窓に /compact <焦点> を打つ。compact の後の会話の始まりの待ち受けが
        # 印を外し、続きをさせる 1 行を渡す（頼みの途中の会話は、続きを渡されないと止まったまま）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a0",
                                              wake.COMPACT: "s1", wake.COMPACT_FOCUS: "次は直しを書く"}, self.g)
        stop = {"hook_event_name": "Stop", "session_id": "s1", "transcript_path": self.transcript(150000)}
        w = Window(self.place)
        start = {"hook_event_name": "SessionStart", "source": "compact", "session_id": "s1"}

        def compacted():   # compact の後の会話の始まり（同じ会話の id）の待ち受け
            self.assertEqual(w.writes, ["/compact 次は直しを書く"])
            kind, text = wake_hook.checker(self.plan(), start, h=w, now=lambda: 5, me=lambda: ME)()
            self.assertEqual(kind, "wake")
            self.assertIn("compact した。焦点: 次は直しを書く", text)
        self.assertEqual(wake_hook.compact_turn(self.plan(), stop, self.g.worktree_attrs(self.place), w, me=lambda: ME,
                                                pause=compacted, looks=1), ("end", None))
        self.assertNotIn(wake.COMPACT, self.g.worktree_attrs(self.place))
        self.assertNotIn(wake.COMPACT_FOCUS, self.g.worktree_attrs(self.place))
        # 印が無ければ、compact の後の会話の始まりでも何も渡さない（持ち主が手で打った compact）
        self.assertIsNone(wake_hook.compact_turn(self.plan(), start, self.g.worktree_attrs(self.place), w, me=lambda: ME))

    def test_a_compact_break_wakes_the_talk_without_compacting_when_it_is_small_or_cannot_type(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a0", wake.COMPACT: "s1"}, self.g)
        small = {"hook_event_name": "Stop", "session_id": "s1", "transcript_path": self.transcript(wake.COMPACT_FLOOR - 1)}
        w = Window(self.place)
        kind, text = self.checker(small, w)()
        self.assertEqual((kind, w.writes), ("wake", []))
        self.assertIn("compact しなかった", text)
        self.assertNotIn(wake.COMPACT, self.g.worktree_attrs(self.place))
        # 人の打ちかけの字は消さない。打てなければ訳を添えて、この会話のまま続けさせる
        provision.mark(self.place, self.src, {wake.COMPACT: "s1"}, self.g)
        big = {**small, "transcript_path": self.transcript(wake.COMPACT_FLOOR)}
        w = Window(self.place, box="打ちかけ")
        kind, text = self.checker(big, w)()
        self.assertEqual((kind, w.writes), ("wake", []))
        self.assertIn("compact できなかった: 窓の入力フィールドに打ちかけの字が在る", text)
        self.assertNotIn(wake.COMPACT, self.g.worktree_attrs(self.place))
        # 打ったが済んだのを見られなければ、印を外して続けさせる（止まったままにしない）
        provision.mark(self.place, self.src, {wake.COMPACT: "s1"}, self.g)
        w = Window(self.place)
        kind, text = wake_hook.compact_turn(self.plan(), big, self.g.worktree_attrs(self.place), w, me=lambda: ME,
                                            pause=lambda: None, looks=2)
        self.assertEqual((kind, w.writes), ("wake", ["/compact"]))
        self.assertIn("済んだのを見られない", text)
        # 打った /compact が入力フィールドに残れば Enter を 1 回だけ足す（残ったまま次の字に連なって届かない）
        provision.mark(self.place, self.src, {wake.COMPACT: "s1"}, self.g)
        w = Window(self.place)
        w.prompt = lambda pane, text, wait: (w.writes.append(text), setattr(w, "box", text))
        wake_hook.compact_turn(self.plan(), big, self.g.worktree_attrs(self.place), w, me=lambda: ME, pause=lambda: None, looks=3)
        self.assertEqual(w.writes, ["/compact", ("enter",)])
        # ターンの終わりの直後にまだ動いていると見えても、手が空くのを見直してから打つ
        provision.mark(self.place, self.src, {wake.COMPACT: "s1"}, self.g)
        w = Window(self.place, status="working")
        w.pause = lambda: setattr(w, "status", "done")
        kind, _ = wake_hook.compact_turn(self.plan(), big, self.g.worktree_attrs(self.place), w, me=lambda: ME, pause=w.pause, looks=1)
        self.assertEqual((kind, w.writes), ("wake", ["/compact"]))
        # 文脈の大きさを読めなければ打たない（費用の元が取れるかが分からない）
        provision.mark(self.place, self.src, {wake.COMPACT: "s1"}, self.g)
        w = Window(self.place)
        kind, text = wake_hook.compact_turn(self.plan(), {**big, "transcript_path": "/none/t.jsonl"},
                                            self.g.worktree_attrs(self.place), w, me=lambda: ME)
        self.assertEqual((kind, w.writes), ("wake", []))
        self.assertIn("文脈の大きさを読めない", text)
        # 区切り（--rest）や終わり（--done）の印が在る・ほかの会話の印のときは、compact しない
        for marks, payload in (({wake.REST: "s1"}, big), ({wake.COMPACT: "s0"}, big)):
            provision.mark(self.place, self.src, {wake.COMPACT: "s1", wake.REST: None, **marks}, self.g)
            self.assertIsNone(wake_hook.compact_turn(self.plan(), payload, self.g.worktree_attrs(self.place), Window(self.place),
                                                     me=lambda: ME))

    def test_a_compact_break_with_background_work_looks_at_the_transcript_instead_of_the_window(self):
        # 裏の処理が残る会話は、herdr がターンを終えていても working と出す。窓の状態の代わりに、会話の記録にターンの行が
        # 足されていないかで手が空いたと見て打つ（知らせは compact の後の会話に届く。my_notes の受付 807aee）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a0", wake.COMPACT: "s1"}, self.g)
        busy = {"hook_event_name": "Stop", "session_id": "s1", "transcript_path": self.transcript(wake.COMPACT_FLOOR),
                "background_tasks": [{"id": "b", "status": "running"}]}
        w = Window(self.place, status="working")
        kind, text = wake_hook.compact_turn(self.plan(), busy, self.g.worktree_attrs(self.place), w, me=lambda: ME,
                                            pause=lambda: None, looks=1)
        self.assertEqual((kind, w.writes), ("wake", ["/compact"]))
        self.assertIn("済んだのを見られない", text)   # 偽物の窓では compact の後の会話の始まりが来ない
        # 打つ前に会話が動いた（裏の処理の知らせでターンが始まった）なら打たない。動いている会話を起動せず、印を残して
        # そのターンの終わりにまた試す
        provision.mark(self.place, self.src, {wake.COMPACT: "s1"}, self.g)
        w = Window(self.place, status="working")

        def notified():
            with open(busy["transcript_path"], "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "message": {"content": "<task-notification>"}}) + "\n")
        self.assertIsNone(wake_hook.compact_turn(self.plan(), busy, self.g.worktree_attrs(self.place), w, me=lambda: ME,
                                                 pause=notified, looks=1))
        self.assertEqual(w.writes, [])
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.COMPACT], "s1")
        # 会話が動いたかを見られない（会話の記録の場所が無い）なら、今までどおり打たない
        self.assertEqual(wake_hook.compact_now(self.plan(), {**busy, "transcript_path": None}, {}, Window(self.place)),
                         wake_hook.NOT_CLEARED_BACKGROUND)

    def rent_or_buy(self, *answers):
        """部品の偽物: 呼ばれるたびに answers を順に返し、呼ばれた (場面, facts) を self.asked_part に残す。"""
        self.asked_part = []
        it = iter(answers)

        def ask(scene, facts, transcript=None):
            self.asked_part.append((scene, facts))
            return next(it)
        return mock.patch.object(wake_hook, "RENT", ask)

    def judged_warm(self, log, clock, running=1):
        # running: ターンの終わりに裏で動いていた処理の数。既定は裏の処理を待って終えたターン（頼み a0 を納品していなくても、orders の
        # Stop フックは差し戻さず、ターンは本当に終わっている）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a0"}, self.g)
        payload = {"hook_event_name": "Stop", "session_id": "s1", "transcript_path": log, "background_tasks": []}
        conf = {"every": 240, "text": "（keepalive）", "ttl": 300, "limit": 2}
        plan = {"action": "rent", "due": 1240.0, "rent": 0.01, "reason": "within_buy_cost", "why": "w"}
        return payload, wake_hook.Warm(self.plan(), payload, conf, ["ask:a0"], now=lambda: clock[0],
                                       attrs_of=lambda cwd: self.g.worktree_attrs(self.place), plan=plan, compact=True,
                                       compact_with=lambda *a, **k: "窓の入力フィールドに打ちかけの字が在る", running=running)

    def test_at_keepalive_time_the_part_asks_the_talk_for_a_focus_and_its_answer_compacts(self):
        # keepalive の時刻に、先に compact を部品に聞く。打つ時で聞けと答えれば、keepalive の文の代わりに焦点の問いを送る（設計書の 6）
        log, clock = self.transcript(150000), [1240.0]
        payload, warm = self.judged_warm(log, clock)
        place = self.g.git_dir(self.place)
        with self.rent_or_buy(({"action": "buy", "consult": True, "reason": "reached_buy_cost", "why": "w"}, None)):
            self.assertEqual(warm(), wake_hook.CONSULT_TEXT)
        self.assertRegex(self.asked_part[0][1].pop("key"), r"^s1/[0-9a-f]{8}$")
        self.assertEqual(self.asked_part, [("compact", {"lifetime": 300, "ask": True, "deferred": 0,
                                                        "defer_limit": wake_hook.DEFER_LIMIT, "forced": False})])
        self.assertTrue(wake.compact_state(self.inbox, place, "s1")["asked"])
        self.assertEqual(deliver.records(self.inbox)[-1]["status"], "asked")
        # 問いで始まったターンの最後の答えを読み、2 回目の判断に渡す。打つなら焦点付きで打ち、compact の後の会話に待ちを続けさせる
        write_line(log, {"type": "user", "message": {"content": "Stop hook blocking error: " + wake_hook.CONSULT_TEXT}})
        write_line(log, {"type": "assistant", "message": {"content": [{"type": "text", "text": "直しの残りと試験の結果"}]}})
        go = {"action": "buy", "consult": False, "reason": "consult_go", "prep": {"focus": "直しの残りと試験の結果"}, "why": "w"}
        w = Window(self.place)
        start = {"hook_event_name": "SessionStart", "source": "compact", "session_id": "s1"}

        def compacted():
            self.assertEqual(w.writes, ["/compact 直しの残りと試験の結果"])
            kind, text = wake_hook.checker(self.plan(), start, h=w, now=lambda: 5, me=lambda: ME)()
            self.assertIn("費用の判断で会話を compact した。焦点: 直しの残りと試験の結果", text)
        with self.rent_or_buy((go, None)):
            self.assertEqual(wake_hook.compact_turn(self.plan(), payload, self.g.worktree_attrs(self.place), w, me=lambda: ME,
                                                    pause=compacted, looks=1), ("end", None))
        self.assertEqual(self.asked_part[0][1]["answer"], {"go": True, "prep": {"focus": "直しの残りと試験の結果"}})
        self.assertNotIn(wake.COMPACT, self.g.worktree_attrs(self.place))
        self.assertFalse(os.path.exists(wake.compact_path(self.inbox, place)))

    def test_a_skip_answer_defers_and_a_turn_not_started_by_the_question_is_not_read(self):
        log, clock = self.transcript(150000), [1240.0]
        payload, warm = self.judged_warm(log, clock)
        place = self.g.git_dir(self.place)
        with self.rent_or_buy(({"action": "buy", "consult": True, "reason": "reached_buy_cost", "why": "w"}, None)):
            warm()
        write_line(log, {"type": "user", "message": {"content": wake_hook.CONSULT_TEXT}})
        write_line(log, {"type": "assistant", "message": {"content": [{"type": "text", "text": "skip: 試験の途中"}]}})
        deferred = {"action": "rent", "consult": False, "reason": "consult_deferred", "why": "w"}
        with self.rent_or_buy((deferred, None)):
            self.assertIsNone(wake_hook.compact_turn(self.plan(), payload, self.g.worktree_attrs(self.place), Window(self.place),
                                                     me=lambda: ME))
        self.assertEqual(self.asked_part[0][1]["answer"], {"go": False, "why": "試験の途中"})
        self.assertEqual(wake.compact_state(self.inbox, place, "s1"), {"asked": False, "deferred": 1, "turned": 0, "judged": False})
        # 問うた後に人の文などでターンが始まったら、その答えは問いへの答えと読まない（部品に聞かず、問うた印だけ外す）
        wake.compact_note(self.inbox, place, "s1", asked=True, deferred=1)
        write_line(log, {"type": "user", "message": {"content": "どう？"}})
        write_line(log, {"type": "assistant", "message": {"content": [{"type": "text", "text": "進んでいる"}]}})
        with self.rent_or_buy():
            self.assertIsNone(wake_hook.compact_turn(self.plan(), payload, self.g.worktree_attrs(self.place), Window(self.place),
                                                     me=lambda: ME))
        self.assertEqual(self.asked_part, [])
        self.assertEqual(wake.compact_state(self.inbox, place, "s1"), {"asked": False, "deferred": 1, "turned": 0, "judged": False})

    def test_past_the_defer_limit_it_compacts_without_asking_and_sends_the_keepalive_if_it_cannot(self):
        # 延ばした回数が上限に着くと部品は聞かずに buy を返す。焦点なしで打つ。打てなければ印を外し、keepalive の文を送る
        log, clock = self.transcript(150000), [1240.0]
        payload, warm = self.judged_warm(log, clock)
        place = self.g.git_dir(self.place)
        wake.compact_note(self.inbox, place, "s1", deferred=wake_hook.DEFER_LIMIT)
        with self.rent_or_buy(({"action": "buy", "consult": False, "reason": "defer_limit_reached", "why": "w"}, None)):
            self.assertEqual(warm(), "（keepalive）")
        self.assertEqual(self.asked_part[0][1]["deferred"], wake_hook.DEFER_LIMIT)
        self.assertNotIn(wake.COMPACT, self.g.worktree_attrs(self.place))
        self.assertFalse(wake.compact_state(self.inbox, place, "s1")["judged"])
        row = deliver.records(self.inbox)[-1]
        self.assertEqual((row["sent"], row["compact"]), (1, "compact を打てなかった（窓の入力フィールドに打ちかけの字が在る）"))
        # 打てれば keepalive は送らない（compact の要求がキャッシュを読む。compact の後の会話の始まりの待ち受けが会話を起動する）
        payload, warm = self.judged_warm(log, clock)
        warm.compact_with = lambda got, payload, attrs, still: self.assertEqual(attrs[wake.COMPACT], "s1")
        with self.rent_or_buy(({"action": "buy", "consult": False, "reason": "defer_limit_reached", "why": "w"}, None)):
            self.assertIsNone(warm())
        self.assertTrue(wake.compact_state(self.inbox, place, "s1")["judged"])
        self.assertEqual(deliver.records(self.inbox)[-1]["status"], "compacted")
        # 裏の処理が残る会話では、打つ口が窓の状態の代わりに still で会話が動いたかを見る。動いていたら keepalive も送らず、
        # 台帳にも書かずにこの待ちを終える（_tick で会話が動いたと見た時と同じ）
        provision.mark(self.place, self.src, {wake.COMPACT: None}, self.g)   # 前の打てた回の印（compact の後の待ち受けが外す物）
        wake.compact_forget(self.inbox, place)
        payload, warm = self.judged_warm(log, clock)
        seen = []

        def moved(got, payload, attrs, still):
            seen.append(still())
            with open(log, "a", encoding="utf-8") as f:
                f.write(json.dumps({"type": "user", "message": {"content": "<task-notification>"}}) + "\n")
            seen.append(still())
            return wake_hook.MOVED
        warm.compact_with = moved
        rows = len(deliver.records(self.inbox))
        with self.rent_or_buy(({"action": "buy", "consult": False, "reason": "defer_limit_reached", "why": "w"}, None)):
            self.assertIsNone(warm())
            self.assertIsNone(warm())
        self.assertEqual((seen, len(deliver.records(self.inbox))), ([True, False], rows))
        self.assertNotIn(wake.COMPACT, self.g.worktree_attrs(self.place))
        self.assertFalse(wake.compact_state(self.inbox, place, "s1")["judged"])

    def test_a_compact_break_asks_the_part_whether_it_pays(self):
        # --compact の印のターンの終わりは、部品が在れば文脈の下限（COMPACT_FLOOR）の代わりに部品の action で決める（設計書の 6 の 4）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", wake.COMPACT: "s1"}, self.g)
        big = {"hook_event_name": "Stop", "session_id": "s1", "transcript_path": self.transcript(wake.COMPACT_FLOOR * 2)}
        w = Window(self.place)
        with self.rent_or_buy(({"action": "rent", "reason": "within_buy_cost", "why": "not yet"}, None)):
            kind, text = wake_hook.compact_turn(self.plan(), big, self.g.worktree_attrs(self.place), w, me=lambda: ME)
        self.assertEqual((kind, w.writes), ("wake", []))
        self.assertIn("借りるか買うかの部品が、まだ compact の費用の元が取れないと答えた（not yet）", text)
        self.assertEqual({k: v for k, v in self.asked_part[0][1].items() if k not in ("lifetime", "key")},
                         {"ask": False, "deferred": 0, "defer_limit": 0, "forced": False})
        provision.mark(self.place, self.src, {wake.COMPACT: "s1"}, self.g)
        small = {**big, "transcript_path": self.transcript(1000)}
        with self.rent_or_buy(({"action": "buy", "reason": "reached_buy_cost", "why": "w"}, None)):
            kind, _ = wake_hook.compact_turn(self.plan(), small, self.g.worktree_attrs(self.place), w, me=lambda: ME,
                                             pause=lambda: None, looks=1)
        self.assertEqual(w.writes, ["/compact"])   # 下限より小さくても、部品が元が取れると答えれば打つ

    def test_at_the_forced_line_it_compacts_without_asking_even_without_the_part(self):
        # 文脈が強制の線（自動の compact の線の手前）に着いたら forced を真にして聞き、部品は聞かずに buy と答える（設計書の 2.3）。
        # 部品が無い・答えないときも、着いていれば打つ（自動の compact の線を上げた後に会話が伸び続けない）
        log, clock = self.transcript(150000), [1240.0]
        payload, warm = self.judged_warm(log, clock)
        warm.line = 150000
        typed = []
        warm.compact_with = lambda got, payload, attrs, still: typed.append(attrs[wake.COMPACT_FOCUS])
        with self.rent_or_buy(({"action": "buy", "consult": False, "reason": "forced", "why": "w"}, None)):
            self.assertIsNone(warm())
        self.assertTrue(self.asked_part[0][1]["forced"])
        self.assertEqual(typed, [None])
        provision.mark(self.place, self.src, {wake.COMPACT: None}, self.g)   # compact の後の会話の始まりの待ち受けが外す物
        wake.compact_forget(self.inbox, self.g.git_dir(self.place))
        payload, warm = self.judged_warm(log, clock)
        warm.line, warm.plan = 150000, None
        warm.compact_with = lambda got, payload, attrs, still: typed.append(attrs[wake.COMPACT_FOCUS])
        with self.rent_or_buy((None, "部品が入っていない")):
            self.assertIsNone(warm())
        self.assertEqual(typed, [None, None])
        self.assertEqual((deliver.records(self.inbox)[-1]["status"], deliver.records(self.inbox)[-1]["compact"]), ("compacted", "forced"))
        # 線の手前なら forced は偽で、部品が答えなければ打たずに keepalive を送る
        provision.mark(self.place, self.src, {wake.COMPACT: None}, self.g)
        wake.compact_forget(self.inbox, self.g.git_dir(self.place))
        payload, warm = self.judged_warm(log, clock)
        warm.line, warm.plan = 150001, None
        with self.rent_or_buy((None, "部品が入っていない")):
            self.assertEqual(warm(), "（keepalive）")
        self.assertEqual(deliver.records(self.inbox)[-1]["compact"], "部品が入っていない")
        # --compact の印も、部品が答えず下限（COMPACT_FLOOR）より小さくても、強制の線に着いていれば打つ
        provision.mark(self.place, self.src, {wake.COMPACT: "s1"}, self.g)
        small = {"hook_event_name": "Stop", "session_id": "s1", "transcript_path": self.transcript(wake.COMPACT_FLOOR - 1)}
        w = Window(self.place)
        with self.rent_or_buy((None, "部品が入っていない")):
            wake_hook.compact_turn(self.plan(), small, self.g.worktree_attrs(self.place), w, me=lambda: ME, pause=lambda: None,
                                   looks=1, line_of=lambda got, attrs: (wake.COMPACT_FLOOR - 1, None))
        self.assertEqual(w.writes, ["/compact"])

    def test_the_forced_line_overrides_a_part_that_does_not_answer_buy(self):
        # forced を知らない古い版の部品が rent と答えても、線に着いていれば buy にする（線は自動の compact を上げた後の歯止め）
        payload = {"hook_event_name": "Stop", "session_id": "s1", "transcript_path": self.transcript(150000)}
        rent = ({"action": "rent", "reason": "within_buy_cost", "why": "old"}, None)
        with self.rent_or_buy(rent, rent, rent):
            found, _ = wake_hook.compact_judge(payload, 300, True, line=150000)
            self.assertEqual((found["action"], found["reason"], found["consult"]), ("buy", "forced", False))
            self.assertIn("部品の答えは 'rent'", found["why"])
            self.assertEqual(wake_hook.compact_judge(payload, 300, True, line=150001), rent)
            self.assertEqual(wake_hook.compact_judge(payload, 300, True), rent)   # 線が無ければ文脈を見ない
        self.assertEqual([facts["forced"] for _, facts in self.asked_part], [True, False, False])
        # 寿命が分からず部品に聞けなくても、線に着いていれば打つ。文脈を読めなければ着いたとは見ない
        self.assertEqual(wake_hook.compact_judge(payload, None, True, line=150000)[0]["reason"], "forced")
        self.assertEqual(wake_hook.compact_judge({**payload, "transcript_path": "/none/t.jsonl"}, None, True, line=1),
                         (None, "キャッシュの寿命が分からない"))

    def test_a_forced_buy_after_the_question_keeps_the_focus_the_talk_gave(self):
        # 焦点を問うた後に線に着くと、部品は prep の無い buy（forced）を返す。会話が返した焦点で打つ
        log, clock = self.transcript(150000), [1240.0]
        payload, warm = self.judged_warm(log, clock)
        with self.rent_or_buy(({"action": "buy", "consult": True, "reason": "reached_buy_cost", "why": "w"}, None)):
            self.assertEqual(warm(), wake_hook.CONSULT_TEXT)
        write_line(log, {"type": "user", "message": {"content": wake_hook.CONSULT_TEXT}})
        write_line(log, {"type": "assistant", "message": {"content": [{"type": "text", "text": "直しの残り"}]}})
        w = Window(self.place)
        with self.rent_or_buy(({"action": "buy", "consult": False, "reason": "forced", "prep": None, "why": "w"}, None)):
            wake_hook.compact_turn(self.plan(), payload, self.g.worktree_attrs(self.place), w, me=lambda: ME,
                                   pause=lambda: None, looks=1, line_of=lambda got, attrs: (150000, None))
        self.assertTrue(self.asked_part[0][1]["forced"])
        self.assertEqual(w.writes[0], "/compact 直しの残り")

    def test_at_the_end_of_a_turn_it_asks_before_keepalive_time_but_not_past_the_defer_limit(self):
        # ターンの終わり（待ち受けが張った最初の周）にも、送る時刻を待たずに compact を部品に聞く（寿命より短い待ちが続く会話でも回る）。
        # 聞けと答えれば、ターンの終わりの問いを送る
        log, clock = self.transcript(150000), [1000.0]
        place = self.g.git_dir(self.place)
        payload, warm = self.judged_warm(log, clock)
        warm.ended = True
        with self.rent_or_buy(({"action": "buy", "consult": True, "reason": "reached_buy_cost", "why": "w"}, None)):
            self.assertEqual(warm(), wake_hook.TURN_CONSULT_TEXT)
        self.assertTrue(wake.compact_state(self.inbox, place, "s1")["asked"])
        self.assertEqual((deliver.records(self.inbox)[-1]["status"], deliver.records(self.inbox)[-1]["when"]), ("asked", "turn-end"))
        # その問いへの答えも、keepalive の時刻の問いと同じく読む
        write_line(log, {"type": "user", "message": {"content": "Stop hook blocking error: " + wake_hook.TURN_CONSULT_TEXT}})
        write_line(log, {"type": "assistant", "message": {"content": [{"type": "text", "text": "skip: 持ち主の答えを待っている"}]}})
        with self.rent_or_buy(({"action": "rent", "consult": False, "reason": "consult_deferred", "why": "w"}, None)):
            wake_hook.compact_turn(self.plan(), payload, self.g.worktree_attrs(self.place), Window(self.place), me=lambda: ME)
        # ターンの終わりの問いに延ばした回数は、keepalive の時刻の物と分けて数える（人が打ちそうで延ばしても、keepalive の時刻に
        # 問わずに打つ延期の上限を使い切らない）
        self.assertEqual(wake.compact_state(self.inbox, place, "s1"), {"asked": False, "deferred": 0, "turned": 1, "judged": False})
        # rent なら台帳に書かずに送る時刻を待ち、送る時刻にはまた聞く
        rows = len(deliver.records(self.inbox))
        payload, warm = self.judged_warm(log, clock)
        warm.ended = True
        rent = ({"action": "rent", "consult": False, "reason": "within_buy_cost", "why": "w"}, None)
        with self.rent_or_buy(rent, rent):
            self.assertIsNone(warm())
            self.assertEqual(len(deliver.records(self.inbox)), rows)
            clock[0] = 1240.0
            self.assertEqual(warm(), "（keepalive）")
        self.assertEqual([facts["deferred"] for _, facts in self.asked_part[-2:]], [1, 0])   # ターンの終わりは turned、送る時刻は deferred
        # 延期の上限を超えた buy（問わずに打つ）は、ターンの終わりには打たない（人が次の文を打とうとしている間でありうる）
        wake.compact_note(self.inbox, place, "s1", turned=wake_hook.DEFER_LIMIT)
        clock[0] = 1000.0
        payload, warm = self.judged_warm(log, clock)
        warm.ended, typed = True, []
        warm.compact_with = lambda got, payload, attrs, still: typed.append(attrs[wake.COMPACT_FOCUS])
        with self.rent_or_buy(({"action": "buy", "consult": False, "reason": "defer_limit_reached", "why": "w"}, None)):
            self.assertIsNone(warm())
        self.assertEqual(typed, [])
        self.assertNotIn(wake.COMPACT, self.g.worktree_attrs(self.place))
        self.assertEqual(self.asked_part[-1][1]["deferred"], wake_hook.DEFER_LIMIT)
        # 強制の線に着いたら、ターンの終わりにも問わずに打つ（自動の compact はターンの途中でも打つ）
        payload, warm = self.judged_warm(log, clock)
        warm.ended = True
        warm.compact_with = lambda got, payload, attrs, still: typed.append(attrs[wake.COMPACT_FOCUS])
        with self.rent_or_buy(({"action": "buy", "consult": False, "reason": "forced", "why": "w"}, None)):
            self.assertIsNone(warm())
        self.assertEqual(typed, [None])
        self.assertEqual((deliver.records(self.inbox)[-1]["status"], deliver.records(self.inbox)[-1]["when"]), ("compacted", "turn-end"))

    def test_the_turn_end_judgment_yields_to_queued_asks_unwanted_work_and_stopped_waits(self):
        # 順番待ちに頼みが在る（check が HOLD で渡すのを待つ）・仕事が要らなくなった・止めた待ちでは、ターンの終わりに聞かない
        log, clock = self.transcript(150000), [1000.0]
        place = self.g.git_dir(self.place)
        buy = ({"action": "buy", "consult": True, "reason": "reached_buy_cost", "why": "w"}, None)
        wake.enqueue(self.inbox, place, {"id": "a1", "line": "a1"})
        payload, warm = self.judged_warm(log, clock)
        warm.ended = True
        with self.rent_or_buy(buy):
            self.assertIsNone(warm())
        self.assertEqual(self.asked_part, [])
        for item in wake.queued(self.inbox, place):
            os.remove(item["path"])
        payload, warm = self.judged_warm(log, clock)
        warm.ended = True
        wake.warm_note(self.inbox, place, "s1", ["ask:a0"], 1, stopped=True, spent=0.01)
        with self.rent_or_buy(buy):
            self.assertIsNone(warm())
        self.assertEqual(self.asked_part, [])
        os.remove(wake.warm_path(self.inbox, place))
        payload, warm = self.judged_warm(log, clock)
        warm.ended = True
        provision.mark(self.place, self.src, {wake.FINISHED: "1"}, self.g)
        with self.rent_or_buy(buy):
            self.assertIsNone(warm())
        self.assertEqual(self.asked_part, [])

    def test_the_turn_end_judgment_does_not_ask_while_the_stop_hook_sends_the_turn_back(self):
        # 納品していない頼みが在り、裏の処理も無いターンの終わりは、orders の Stop フックが差し戻している（ターンは終わっていない）。
        # 問うと、会話はツールを使わずに 1 行で答えてターンを終え、差し戻しを使い切って止まった（2026-10-26 の見渡し。受付 3ddd8e）
        log, clock = self.transcript(150000), [1000.0]
        buy = ({"action": "buy", "consult": True, "reason": "reached_buy_cost", "why": "w"}, None)
        for running in (0, None):   # None は裏の処理を数えられないとき（orders の Stop フックも差し戻す）
            with self.subTest(running=running):
                payload, warm = self.judged_warm(log, clock, running=running)
                warm.ended = True
                with self.rent_or_buy(buy):
                    self.assertIsNone(warm())
                self.assertEqual(self.asked_part, [])
        # --wait で人の答え待ちにした頼みは差し戻さないので、ターンは終わっている。問う
        payload, warm = self.judged_warm(log, clock, running=0)
        warm.ended = True
        provision.mark(self.place, self.src, {"waiting": "a0"}, self.g)
        with self.rent_or_buy(buy):
            self.assertEqual(warm(), wake_hook.TURN_CONSULT_TEXT)

    def test_a_turn_end_compact_that_could_not_type_is_not_retried_in_the_same_round(self):
        # ターンの終わりに強制の線で打てなかったら、同じ周の送る時刻に打ち直さず keepalive を送る
        log, clock = self.transcript(150000), [1240.0]
        payload, warm = self.judged_warm(log, clock)
        warm.ended, tried = True, []
        warm.compact_with = lambda got, payload, attrs, still: tried.append(1) or "窓の入力フィールドに打ちかけの字が在る"
        forced = ({"action": "buy", "consult": False, "reason": "forced", "why": "w"}, None)
        with self.rent_or_buy(forced, forced):
            self.assertEqual(warm(), "（keepalive）")
        self.assertEqual(len(tried), 1)
        self.assertIn("compact を打てなかった", deliver.records(self.inbox)[-1]["compact"])

    def test_turns_the_waiting_side_started_do_not_ask_again_at_their_end(self):
        # keepalive の文か問いで始まったターンの終わりには、ターンの終わりの判断を聞かない（keepalive は送る直前に聞き、問いの答えは
        # consult_answer が読む）。記録を読めないときも聞かない
        conf = {"text": "（keepalive）"}
        log = self.transcript(150000)
        payload = {"transcript_path": log}
        self.assertFalse(wake_hook.ours(payload, conf))
        for text in ("Stop hook blocking error: （keepalive）", wake_hook.CONSULT_TEXT, wake_hook.TURN_CONSULT_TEXT):
            write_line(log, {"type": "user", "message": {"content": text}})
            write_line(log, {"type": "assistant", "message": {"content": [{"type": "text", "text": "waiting"}]}})
            self.assertTrue(wake_hook.ours(payload, conf), text)
        write_line(log, {"type": "user", "message": {"content": "どう？"}})
        self.assertFalse(wake_hook.ours(payload, conf))
        self.assertTrue(wake_hook.ours({"transcript_path": None}, conf))

    def test_reply_answer_reads_the_first_line(self):
        self.assertEqual(wake_hook.reply_answer("\n 直しの残り \n二行目"), {"go": True, "prep": {"focus": "直しの残り"}})
        self.assertEqual(wake_hook.reply_answer("Skip：試験の途中"), {"go": False, "why": "試験の途中"})
        self.assertEqual(wake_hook.reply_answer("skip:"), {"go": False, "why": "skip"})
        # skip の後ろに : の無い字は焦点と読む（「Skip list」の見出しなど）
        self.assertEqual(wake_hook.reply_answer("Skip list の直し"), {"go": True, "prep": {"focus": "Skip list の直し"}})
        self.assertEqual(wake_hook.reply_answer(""), {"go": False, "why": "no reply"})

    def test_a_typed_prompt_takes_the_compact_mark_off_but_the_typed_compact_does_not(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", wake.COMPACT: "s1",
                                              wake.COMPACT_FOCUS: "f"}, self.g)
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s1", "prompt": "/compact f"})
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.COMPACT], "s1")
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s1", "prompt": "どう？"})
        self.assertNotIn(wake.COMPACT, self.g.worktree_attrs(self.place))
        self.assertNotIn(wake.COMPACT_FOCUS, self.g.worktree_attrs(self.place))

    def test_context_of_reads_the_last_usage(self):
        self.assertEqual(wake_hook.context_of(self.transcript(123456)), 123456)
        self.assertIsNone(wake_hook.context_of(None))
        self.assertIsNone(wake_hook.context_of("/none/t.jsonl"))
        path = self.transcript(123456)
        with open(path, "a", encoding="utf-8") as f:   # エラーや割り込みの <synthetic> の応答は数が 0。飛ばして前の応答を読む
            f.write(json.dumps({"type": "assistant", "message": {"model": "<synthetic>", "usage": {"input_tokens": 0}}}) + "\n")
        self.assertEqual(wake_hook.context_of(path), 123456)

    def test_a_turn_that_ends_well_takes_the_limit_wait_mark_off(self):
        # 使用上限か時間帯で止まった会話のターンが誤りなく終わったら、--move --if-limited の待ちの印を外す（待っている処理は
        # 続きの 1 行を打たずにやめる）。人の文が始めたターンが断られたとき（Stop でなく StopFailure）は外さない
        provision.mark(self.place, self.src, {"role": "相談", "name": "社長室", "session": "s1", wake.LIMIT_HOLD: "1-1"}, self.g)
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s1"})
        wake_hook.ended_well({"cwd": self.place, "session_id": "s1", "hook_event_name": "StopFailure"})
        wake_hook.ended_well({"cwd": self.place, "session_id": "s9", "hook_event_name": "Stop"})   # 場所のほかの会話では外さない
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.LIMIT_HOLD], "1-1")
        wake_hook.ended_well({"cwd": self.place, "session_id": "s1", "hook_event_name": "Stop"})
        self.assertNotIn(wake.LIMIT_HOLD, self.g.worktree_attrs(self.place))

    def spawner(self, fail=None):
        seen = []

        def spawn(argv, **kw):
            if fail:
                raise fail
            seen.append((argv, kw))
        return seen, spawn

    def test_a_finished_department_starts_retire_apart_from_the_talk_at_the_end_of_the_turn(self):
        # tmp の部署が終わりと印した（--done）ターンの終わりに、印を外し、--retire を会話から切り離して走らせる（会話を止めるので待たない）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a0", "delivered": "a0",
                                              "fresh": role.FRESH, wake.FINISHED: "s1"}, self.g)
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
        self.assertNotIn(wake.FINISHED, self.g.worktree_attrs(self.place))   # 印は 1 度で外れる

    @unittest.skipIf(os.name == "nt", "切り離す殻は POSIX だけ")
    def test_retire_apart_from_the_talk_writes_its_exit_code(self):
        # 切り離した --retire の終わりの値を .done に書く（0 でなければ --tree と --todo が出す。前は出力のログしか残らなかった）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1"}, self.g)
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
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a0", wake.FINISHED: "s1"}, self.g)
        seen, spawn = self.spawner()

        def check(payload):
            return wake_hook.checker(self.plan(), payload, h=Window(self.place), now=lambda: 5, spawn=spawn)()
        self.assertIsNone(check({"hook_event_name": "Stop"}))   # a0 を納品していない
        provision.mark(self.place, self.src, {"delivered": "a0"}, self.g)
        self.assertIsNone(check({"hook_event_name": "Stop", "background_tasks": [{"id": "b"}]}))   # 裏の処理が残る
        self.assertIsNone(check({"hook_event_name": "SessionStart"}))   # ターンの終わりでない
        self.assertEqual(seen, [])
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.FINISHED], "s1")

    def test_a_queued_ask_is_handed_instead_of_retiring_and_takes_the_mark_off(self):
        # 終わりと印した後に追いの頼みが積まれたら、畳まずに渡す（終わりは、その頼みを済ませてから印し直す）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a0", "delivered": "a0",
                                              wake.FINISHED: "s1"}, self.g)
        self.put("a1")
        seen, spawn = self.spawner()
        got = wake_hook.checker(self.plan(), {"hook_event_name": "Stop"}, h=Window(self.place), now=lambda: 5, spawn=spawn)
        self.assertEqual(got(), ("wake", "頼みです（受付 a1）"))
        self.assertEqual(seen, [])
        self.assertNotIn(wake.FINISHED, self.g.worktree_attrs(self.place))

    def test_a_retire_that_cannot_start_leaves_the_room_with_the_reason(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", wake.FINISHED: "s1"}, self.g)
        _, spawn = self.spawner(fail=OSError("no python"))
        got = wake_hook.checker(self.plan(), {"hook_event_name": "Stop"}, h=Window(self.place), now=lambda: 5, spawn=spawn)
        self.assertIsNone(got())
        attrs = self.g.worktree_attrs(self.place)
        self.assertNotIn(wake.FINISHED, attrs)   # 打ち直しはしない
        self.assertIn("no python", attrs[wake.RETIRE_KEPT])

    def test_a_typed_prompt_takes_the_finished_mark_off(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", wake.FINISHED: "s1"}, self.g)
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s9"})
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.FINISHED], "s1")
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s1"})
        self.assertNotIn(wake.FINISHED, self.g.worktree_attrs(self.place))

    def test_the_window_is_the_pane_of_this_talk_when_the_place_has_several(self):
        # 本社には持ち主のほかの会話も居るので、ペインの会話の印で窓口の窓を決める
        class Many(Window):
            def panes(self):
                return [{"pane_id": "p1", "cwd": self.cwd, "agent": "claude", "agent_session": "s0"},
                        {"pane_id": "p2", "cwd": self.cwd, "agent": "claude", "agent_session": "s1"}]
        self.assertEqual(wake_hook.own_window(self.place, Many(self.place), "s1"), "p2")
        self.assertIsNone(wake_hook.own_window(self.place, Many(self.place), "s7"))   # 結べなければ打たない
        self.assertEqual(wake_hook.own_window(self.place, Window(self.place), "s7"), "p1")   # 場所に 1 つなら、それ

    def test_clear_goes_only_to_a_window_where_this_talk_is_seen_running(self):
        # 会話を消す打ち込みは、窓の前のプロセスにこの会話が居ると確かめたときだけ打つ（印も、場所だけの代わりも使わない）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "ask": "a1", "delivered": "a1", "fresh": role.FRESH,
                                              "job": "abcd1234"}, self.g)
        stranger = Window(self.place, front=[{"pid": ME + 1, "argv": ["claude"]}])
        stranger.panes = lambda: [{"pane_id": "p1", "cwd": self.place, "agent": "claude", "agent_session": "s1"}]
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
                                              "job": "a5b0bc07"}, self.g)
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
        self.assertEqual(self.g.worktree_attrs(self.place)["job"], "8c4a1102")
        self.assertIsNone(wake_hook.job_of({}))   # 裏の会話でなければ無い

    def test_a_pane_of_another_place_is_not_the_window_even_with_this_talk_mark(self):
        # herdr の印は別の部署の会話の id のまま残ることがある（2026-10-17 に my_notes で、ノートの手入れの待ち受けが印の合った
        # 調べものの窓に /clear を打った）。場所の違う窓は、印が合っても打ち先にしない
        other = tempfile.mkdtemp()

        class Stale(Window):
            def panes(self):
                return [{"pane_id": "p9", "cwd": other, "agent": "claude", "agent_session": "s1"},
                        {"pane_id": "p1", "cwd": self.cwd, "agent": "claude", "agent_session": "s-old"}]

        class Alone(Window):
            def panes(self):
                return [{"pane_id": "p9", "cwd": other, "agent": "claude", "agent_session": "s1"}]
        self.assertEqual(wake_hook.own_window(self.place, Stale(self.place), "s1"), "p1")
        self.assertIsNone(wake_hook.own_window(self.place, Alone(self.place), "s1"))
        os.makedirs(os.path.join(self.place, "sub"), exist_ok=True)   # 会話が作業場の下のフォルダに居ても、同じ場所と見る
        self.assertEqual(wake_hook.own_window(os.path.join(self.place, "sub"), Stale(self.place), "s1"), "p1")

    def test_a_typed_prompt_pauses_the_watcher(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a1", "waiting": "a1"}, self.g)
        place = self.g.git_dir(self.place)
        wake.claim(self.inbox, place, ["co/調べ"], "s1", os.getppid(), "t", 0)
        with mock.patch.dict(os.environ, self.env):
            wake_hook.main(["--pause"], io.StringIO(json.dumps({"cwd": self.place, "session_id": "s1"})))
        self.assertEqual(wake.read_mark(self.inbox, place)["token"], "paused")
        # 裏で走る --pause は答え待ちの印に触らない（同じターンの中で会話が打った --wait より後に走りうる）
        self.assertEqual(self.g.worktree_attrs(self.place)["waiting"], "a1")

    def test_a_typed_prompt_takes_the_wait_mark_off_before_the_talk_reads_it(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a1", "waiting": "a1",
                                              "waiting-why": "持ち主の答え"}, self.g)
        with mock.patch.dict(os.environ, self.env):
            self.assertEqual(wake_hook.main(["--resume"], io.StringIO(json.dumps({"cwd": self.place, "session_id": "s1"}))), 0)
        attrs = self.g.worktree_attrs(self.place)
        self.assertNotIn("waiting", attrs)
        self.assertNotIn("waiting-why", attrs)

    def test_a_subagent_compacting_starts_no_waiter(self):
        # 2026-10-24、my_notes の受付 5ccb69 の部署で、サブエージェントの compact の SessionStart が本体と同じ会話の id で待ち受けを
        # 立て直し、本体の待ち受けを替えて keepalive の時計を 21 分間に 9 回戻した
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "ask": "a1"}, self.g)
        place = self.g.git_dir(self.place)
        wake.claim(self.inbox, place, ["co/調べ"], "s1", os.getppid(), "t", 0)
        payload = {"cwd": self.place, "session_id": "s1", "hook_event_name": "SessionStart", "source": "compact", "agent_id": "a9de"}
        with mock.patch.dict(os.environ, self.env), mock.patch.object(wake_hook, "plan", side_effect=AssertionError("待ち受けを立てた")):
            self.assertEqual(wake_hook.main([], io.StringIO(json.dumps(payload)), io.StringIO(), env={}), 0)
        self.assertEqual(wake.read_mark(self.inbox, place)["token"], "t")

    def hop_main(self, newer, jump, env=None):
        payload = {"cwd": self.place, "session_id": "s1", "hook_event_name": "Stop"}
        err = io.StringIO()
        with mock.patch.dict(os.environ, self.env), mock.patch.object(wake, "GRACE", 0), mock.patch.object(wake, "POLL", 0.05):
            rc = wake_hook.main([], io.StringIO(json.dumps(payload)), err, newer=newer, jump=jump, now=lambda: 5, env=env or {})
        return rc, payload, err.getvalue()

    def test_a_waiter_of_an_older_version_hands_over_to_the_installed_one_before_it_hands_an_ask(self):
        # 2026-10-21 に、版を上げる前に立った待ち受けが、/reload-plugins の後も前の版のまま頼みを渡した（my_notes の受付 35aa1b）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1"}, self.g)
        place, there = self.g.git_dir(self.place), "/c/works-dispatch/9.9.9/dispatch/wake_hook.py"
        looks, jumps = [], []
        self.assertIn("co/調べ", self.plan()["names"])   # 下の知らせの宛先（違うと待ち受けが渡さずに待ち続ける）

        def later():
            self.put("a1")
            deliver.log(self.inbox, wake.notice("co/調べ", "a1", wake.QUEUED, "/a1.md", "a1", 1))

        def newer():
            # 読み始めの確かめではまだ今の版。その後に版が上がり、頼みが積まれる（台帳の知らせで確かめる）
            looks.append(1)
            if len(looks) == 1:
                timer = threading.Timer(0.2, later)
                timer.start()
                self.addCleanup(timer.cancel)
                return None
            return there
        rc, payload, _ = self.hop_main(newer, lambda *a: jumps.append(a) or 2)
        self.assertEqual(rc, 2)
        ((to, argv, got, token),) = jumps
        self.assertEqual((to, argv, got), (there, [], payload))
        self.assertEqual(wake.read_mark(self.inbox, place)["token"], token)   # 替わった先は、印がまだこの token なら続ける
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, place)], ["a1"])   # 渡さずに替わった
        (row,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "hopped"]
        self.assertEqual((row["to"], row["session"]), (str(pathlib.Path("/c/works-dispatch/9.9.9")), "s1"))   # Windows は \ 区切り

    def test_an_older_waiter_hands_over_before_it_asks_the_keepalive(self):
        # 2026-10-24 に、前の版の待ち受けが keepalive を聞いてから替わり、替わった先が同じ判断を聞き直した（my_notes の受付 b527a1）
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1"}, self.g)
        there, jumps, asked = "/c/works-dispatch/9.9.9/dispatch/wake_hook.py", [], []
        with mock.patch.object(wake_hook, "warm_for", side_effect=lambda *a, **k: asked.append(k)):
            rc, payload, _ = self.hop_main(lambda: there, lambda *a: jumps.append(a) or 2)
        self.assertEqual((rc, asked), (2, []))   # 聞かずに替わった
        self.assertEqual(jumps, [(there, [], payload, None)])   # 印を渡さないので、替わった先がフックの入力を初めから扱う
        (row,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "hopped"]
        self.assertEqual(row["to"], str(pathlib.Path("/c/works-dispatch/9.9.9")))   # Windows は \ 区切り

    def test_a_waiter_that_hops_right_after_it_starts_hands_over_no_token(self):
        seen = []
        with mock.patch.dict(os.environ, {wake_hook.HANDED_OVER: "stale"}), mock.patch.object(os, "dup2"):
            wake_hook.hop("/x/wake_hook.py", [], {}, None, execv=lambda *a: seen.append(a[2]))
        self.assertNotIn(wake_hook.HANDED_OVER, seen[0])

    def test_a_waiter_that_cannot_hand_over_keeps_waiting_in_its_own_version(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1"}, self.g)
        self.put("a1")

        def jump(*_):
            raise OSError("exec できない")
        rc, _, err = self.hop_main(lambda: "/c/works-dispatch/9.9.9/dispatch/wake_hook.py", jump)
        self.assertEqual(rc, 2)   # この版のまま、順番待ちの頼みを渡した
        self.assertIn("頼みです（受付 a1）", err)
        self.assertIn("替われないので、この版のまま待つ", err)
        self.assertEqual([r.get("status") for r in deliver.records(self.inbox) if r.get("kind") == "hopped"], [None, "failed"])

    def test_a_waiter_hands_an_ask_even_when_it_cannot_decide_the_keepalive(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1"}, self.g)
        self.put("a1")
        with mock.patch.object(wake_hook, "warm_for", side_effect=ValueError("形が違う")):
            rc, _, err = self.hop_main(lambda: None, lambda *a: 1 / 0)
        self.assertEqual(rc, 2)   # keepalive を決められなくても、待ち受けを落とさずに頼みを渡した
        self.assertIn("頼みです（受付 a1）", err)
        self.assertIn("keepalive を送るかを決められないので送らない", err)

    def test_a_waiter_that_cannot_read_the_record_keeps_waiting_in_its_own_version(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1"}, self.g)
        self.put("a1")

        def newer():
            raise TypeError("installPath が文字列でない")   # 控えの形が思っていたのと違う
        rc, _, err = self.hop_main(newer, lambda *a: 1 / 0)
        self.assertEqual(rc, 2)   # 待ち受けを落とさず、この版のまま渡した
        self.assertIn("頼みです（受付 a1）", err)
        self.assertIn("探せないので、この版のまま待つ", err)

    def test_a_handed_over_waiter_stops_when_the_talk_was_paused_meanwhile(self):
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ", "session": "s1", "limit-hold": "x"}, self.g)
        self.put("a1")
        place = self.g.git_dir(self.place)
        wake.claim(self.inbox, place, ["co/調べ"], "s1", os.getppid(), "paused", 0)   # 替わる間に人の文で --pause が書き替えた
        env = {wake_hook.HANDED_OVER: "old-token"}
        rc, _, _ = self.hop_main(lambda: None, lambda *a: 1 / 0, env)
        self.assertEqual((rc, env), (0, {}))   # 渡さずに終わり、印は子に継がせない
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, place)], ["a1"])
        self.assertEqual(wake.read_mark(self.inbox, place)["token"], "paused")
        self.assertEqual(self.g.worktree_attrs(self.place)["limit-hold"], "x")   # 何時間も前の Stop の後始末を繰り返さない
        wake.claim(self.inbox, place, ["co/調べ"], "s1", os.getppid(), "old-token", 0)
        rc, _, err = self.hop_main(lambda: None, lambda *a: 1 / 0, {wake_hook.HANDED_OVER: "old-token"})
        self.assertEqual(rc, 2)   # 印がまだ前の待ち受けの物なら、続けて渡す
        self.assertIn("頼みです（受付 a1）", err)

    def test_a_waiter_finds_the_installed_version_of_itself(self):
        root = pathlib.Path(tempfile.mkdtemp()) / "plugins"
        mine = root / "cache" / "raiki61" / "works-dispatch" / "0.1.0" / "dispatch" / "wake_hook.py"
        new = root / "cache" / "raiki61" / "works-dispatch" / "0.2.0" / "dispatch" / "wake_hook.py"
        for f in (mine, new):
            f.parent.mkdir(parents=True)
            f.write_text("", encoding="utf-8")

        def record(version):
            (root / "installed_plugins.json").write_text(json.dumps({"plugins": {"works-dispatch@raiki61": [
                {"scope": "user", "installPath": str(new.parent.parent.parent / version)}]}}), encoding="utf-8")
        record("0.2.0")
        self.assertEqual(wake_hook.newer_self(mine, posix=True), str(new))   # 探し方は OS によらない（Windows の CI でも確かめる）
        self.assertIsNone(wake_hook.newer_self(new, posix=True))
        # dispatch.py の乗り換えた先から起動した会話にも継がれる印では止めない
        with mock.patch.dict(os.environ, {"WORKS_DISPATCH_HOPPED": "1"}):
            self.assertEqual(wake_hook.newer_self(mine, posix=True), str(new))
        self.assertIsNone(wake_hook.newer_self(mine, posix=False))   # Windows は替わらない
        record("0.1.0")
        self.assertIsNone(wake_hook.newer_self(mine, posix=True))
        self.assertIsNone(wake_hook.newer_self(DISPATCH / "wake_hook.py", posix=True))   # リポジトリの checkout

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


class HookProcess(unittest.TestCase):
    """入口 wake_hook.py を別の処理として起動する（ファイルの入口・標準入出力・終了の値の境目）。別の処理には偽物を渡せないので、git は
    一時のフォルダの本物。"""

    def setUp(self):
        d = pathlib.Path(tempfile.mkdtemp())
        self.src = str(d / "co")
        git("init", "-q", "-b", "main", self.src)
        git("-C", self.src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "init")
        self.place = str(d / "dept")
        git("-C", self.src, "worktree", "add", "-q", "-b", "dept/a", self.place)
        self.inbox = deliver.inbox_of(gitx.common_dir(self.src))
        self.env = {"WORKS_DISPATCH_CONFIG": "/none/c.toml"}

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


    @unittest.skipIf(os.name == "nt", "Windows は exec でなく子として起動する")
    def test_an_older_waiter_execs_the_installed_one_in_the_same_process_with_the_same_input(self):
        root = pathlib.Path(tempfile.mkdtemp()) / "plugins"
        old = root / "cache" / "raiki61" / "works-dispatch" / "0.1.0" / "dispatch"
        shutil.copytree(DISPATCH, old, ignore=shutil.ignore_patterns("tests", "__pycache__"))
        new = root / "cache" / "raiki61" / "works-dispatch" / "0.2.0" / "dispatch" / "wake_hook.py"
        new.parent.mkdir(parents=True)
        new.write_text("import os, sys\nsys.stderr.write(f'{os.getpid()} {sys.argv[1:]} {sys.stdin.read()}')\nsys.exit(2)\n",
                       encoding="utf-8")
        (root / "installed_plugins.json").write_text(json.dumps({"plugins": {"works-dispatch@raiki61": [
            {"scope": "user", "installPath": str(new.parent.parent)}]}}), encoding="utf-8")
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ"}, gitx)
        payload = json.dumps({"cwd": self.place, "session_id": "s1", "hook_event_name": "Stop"})
        proc = subprocess.Popen([sys.executable, str(old / "wake_hook.py"), "--x"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, text=True, encoding="utf-8", env={**os.environ, **self.env})
        try:
            _, err = proc.communicate(payload, timeout=30)
        finally:
            proc.kill()
        self.assertEqual((proc.returncode, err), (2, f"{proc.pid} ['--x'] {payload}"))
        (row,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "hopped"]
        self.assertEqual([os.path.realpath(row[k]) for k in ("from", "to")], [os.path.realpath(x) for x in (old.parent, new.parent.parent)])

    @unittest.skipIf(os.name == "nt", "Windows は替わらない")
    def test_the_installed_waiter_goes_on_from_the_same_queue_after_the_hop(self):
        root = pathlib.Path(tempfile.mkdtemp()) / "plugins"
        versions = root / "cache" / "raiki61" / "works-dispatch"
        for v in ("0.1.0", "0.2.0"):
            shutil.copytree(DISPATCH, versions / v / "dispatch", ignore=shutil.ignore_patterns("tests", "__pycache__"))
        (root / "installed_plugins.json").write_text(json.dumps({"plugins": {"works-dispatch@raiki61": [
            {"scope": "user", "installPath": str(versions / "0.2.0")}]}}), encoding="utf-8")
        provision.mark(self.place, self.src, {"role": "作業", "name": "調べ"}, gitx)
        place = gitx.git_dir(self.place)
        line = "頼みです（受付 a1）"   # 渡す字は順番待ちに積んだ字のまま
        wake.enqueue(self.inbox, place, {"id": "a1", "line": line, "marks": {"ask": "a1", "boss": "窓口"}})
        payload = json.dumps({"cwd": self.place, "session_id": "s1", "hook_event_name": "Stop"})
        proc = subprocess.Popen([sys.executable, str(versions / "0.1.0" / "dispatch" / "wake_hook.py")], stdin=subprocess.PIPE,
                                stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, encoding="utf-8",
                                env={**os.environ, **self.env, "TMPDIR": tempfile.mkdtemp()})
        try:
            _, err = proc.communicate(payload, timeout=60)
        finally:
            proc.kill()
        self.assertEqual((proc.returncode, err.splitlines()[-1]), (2, line), err)   # 頭に役の文が足されることがある
        self.assertEqual(wake.queued(self.inbox, place), [])
        kinds = [r.get("kind") for r in deliver.records(self.inbox) if r.get("kind") in ("hopped", "handed")]
        self.assertEqual(kinds, ["hopped", "handed"])
        self.assertEqual(gitx.worktree_attrs(self.place)["ask"], "a1")


class WakeFlow(unittest.TestCase):
    """--ask と --deliver が、宛先の待ち受けの居る部署には窓に打たずに台帳の知らせで届ける。場の作りは Flow の物を借りる
    （継ぐと、その試験が二度走る）。"""

    Flow = test_deliver.Flow
    setUp, main, prompts, ask_then_summary, shape = Flow.setUp, Flow.main, Flow.prompts, Flow.ask_then_summary, Flow.shape
    del Flow

    def listen(self, name, place, owner=None):
        to = wake.address(orders.inbox_company(self.inbox, os.path.dirname(self.cfg), self.g), name)
        wake.claim(self.inbox, place, [to], "s", owner or os.getpid(), "t", time.time())
        if owner:   # 居ない会話の印は古くもする（Windows は処理の番号でなく印の更新の新しさで居るかを見る）
            old = time.time() - wake.FRESH - 60
            os.utime(wake.mark_path(self.inbox, place), (old, old))
        return to

    def dept_place(self):
        return self.g.git_dir(self.place)

    def test_ask_to_a_listening_department_queues_and_says_so(self):
        to = self.listen("調べ", self.dept_place())
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "これを調べて")
        self.assertEqual(rc, 0, out)
        self.assertEqual([w for w in self.ports.term.writes if w[0] in ("prompt", "run")], [])
        notice, rec = deliver.records(self.inbox)
        self.assertEqual((notice["to"], notice["kind"], notice["id"]), (to, wake.QUEUED, rec["id"]))
        self.assertEqual((rec["status"], rec["to"]["wake"]), ("queued", to))
        (item,) = wake.queued(self.inbox, self.dept_place())
        self.assertIn("desk から）: これを調べて 終わったら、要約を", item["line"])
        self.assertEqual((item["marks"]["ask"], item["marks"]["boss"]), (rec["id"], "desk"))
        self.assertNotIn("ask", self.g.worktree_attrs(self.place))   # 属性は待ち受けが渡すときに書く
        self.assertIn("順番待ちに積んだ（1 件目。待ち受けが渡す）", out)

    @unittest.skipIf(os.name == "nt", "Windows は会話と待ち受けを同じ印の更新の新しさで見るので、会話だけ生きている形を作れない")
    def test_ask_to_a_stopped_department_without_a_running_waiter_says_so(self):
        self.listen("調べ", self.dept_place())
        mark = wake.read_mark(self.inbox, self.dept_place())
        with open(wake.mark_path(self.inbox, self.dept_place()), "w", encoding="utf-8") as f:
            json.dump({**mark, "pid": dead_pid()}, f)   # 会話は生きているが、待ち受けの台本が居ない
        self.ports.term.screen = f"{'─' * 20}\n❯ \n{'─' * 20}\n"   # 手の空いた窓（入力フィールドが空）
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "これを調べて")
        self.assertEqual(rc, 0, out)
        self.assertIn("渡す待ち受けが居ない", out)
        self.assertEqual(len(wake.queued(self.inbox, self.dept_place())), 1)
        # 持ち主に打たせず、窓に 1 行打ってターンを回す（ターンの終わりに待ち受けが張り直して渡す）
        self.assertEqual([w[2] for w in self.prompts()], [orders.chat.RELOAD, orders.STUCK_LINE])
        self.assertIn("1 行打ってターンを回した", out)
        nudged = [r for r in deliver.records(self.inbox) if r.get("kind") == "nudged"]
        self.assertEqual([(r["why"], r["id"]) for r in nudged], [("渡す待ち受けが居ない", wake.queued(self.inbox, self.dept_place())[0]["id"])])

    def test_nudge_moves_a_held_department_and_leaves_a_typing_window_alone(self):
        self.listen("調べ", self.dept_place())
        provision.mark(self.place, self.src, {"ask": "a0", "delivered": "a0"}, self.g)
        rc, out = self.main(self.src, "--nudge", "調べ")
        self.assertEqual((rc, self.prompts()), (0, []), out)
        self.assertIn("順番待ちが空", out)   # 止まっていない
        wake.enqueue(self.inbox, self.dept_place(), {"id": "a1", "line": "a1"})
        deliver.log(self.inbox, {"id": "a1", "kind": "held", "place": self.place, "session": "s", "detail": "会話がまだ動いている"})
        rc, out = self.main(self.src, "--nudge", "調べ")
        self.assertEqual((rc, self.prompts()), (1, []), out)   # すぐ替わる訳なら打たない（待ち受けの /clear とぶつけない）
        self.assertIn("訳がすぐ替わる物なので打たなかった", out)
        # 子の返事待ち・裏の処理で止めるのは古い版の待ち受けだけなので、1 行を打って今の版で数え直させる（2026-10-18 の割り振り）
        self.ports.term.screen = f"{'─' * 20}\n❯ \n{'─' * 20}\n"
        for detail in ("子の頼みの返事を待っている（受付 c1）", wake_hook.NOT_CLEARED_BACKGROUND):
            deliver.log(self.inbox, {"id": "a1", "kind": "held", "place": self.place, "session": "s", "detail": detail})
            rc, out = self.main(self.src, "--nudge", "調べ")
            self.assertEqual(rc, 0, out)
            self.assertEqual([w[2] for w in self.prompts()], [orders.chat.RELOAD, orders.STUCK_LINE])
            self.ports.term.writes.clear()
        deliver.log(self.inbox, {"id": "a1", "kind": "held", "place": self.place, "session": "s", "detail": "窓を確かめられない"})
        provision.mark(self.place, self.src, {"rest": "s"}, self.g)
        self.ports.term.screen = f"{'─' * 20}\n❯ 打ちかけ\n{'─' * 20}\n"
        rc, out = self.main(self.src, "--nudge", "調べ")
        self.assertEqual((rc, self.prompts()), (1, []), out)   # 人の打ちかけの字を壊さない
        self.assertIn("入力フィールドに字が在るので打たなかった", out)
        self.ports.term.screen = f"{'─' * 20}\n❯ \n{'─' * 20}\n"
        rc, out = self.main(self.src, "--nudge", "調べ")
        self.assertEqual(rc, 0, out)
        self.assertIn("待ち受けが渡さずに待っている（窓を確かめられない）", out)
        self.assertEqual([w[2] for w in self.prompts()], [orders.chat.RELOAD, orders.STUCK_LINE])
        self.assertEqual(self.g.worktree_attrs(self.place).get("rest"), "s")   # 打った 1 行で外れる区切りの印は残す

    @unittest.skipIf(os.name == "nt", "Windows は会話と待ち受けを同じ印の更新の新しさで見るので、会話だけ生きている形を作れない")
    def test_nudge_drops_a_clear_the_gone_watcher_left_unsent_before_typing(self):
        # 渡す待ち受けが居ないまま、待ち受けが打った /clear が入力フィールドに残った（送り直す者が居ない）: 消してから 1 行を打つ。
        # 人の打ちかけの字と、前の会話で打った物は消さない。待ち受けが居るとき（渡さずに待っている）は、待ち受けが送り直すので消さない
        self.listen("調べ", self.dept_place())
        provision.mark(self.place, self.src, {"ask": "a0", "delivered": "a0", "session": "s", wake.CLEAR_TYPED: "s"}, self.g)
        wake.enqueue(self.inbox, self.dept_place(), {"id": "a0", "line": "a0"})
        deliver.log(self.inbox, {"id": "a0", "kind": "held", "place": self.place, "session": "s", "detail": "子の頼みの返事を待っている（受付 c1）"})
        self.ports.term.screen = f"{'─' * 20}\n❯ /clear [name]\n{'─' * 20}\n"
        self.main(self.src, "--nudge", "調べ")
        self.assertFalse([w for w in self.ports.term.writes if w[0] == "send_keys" and w[2:] == ("ctrl+u",)])
        wake.take(self.inbox, self.dept_place())
        mark = wake.read_mark(self.inbox, self.dept_place())
        with open(wake.mark_path(self.inbox, self.dept_place()), "w", encoding="utf-8") as f:
            json.dump({**mark, "pid": dead_pid()}, f)
        provision.mark(self.place, self.src, {"ask": "a0", "delivered": "a0", "session": "s", wake.CLEAR_TYPED: "s0"}, self.g)
        wake.enqueue(self.inbox, self.dept_place(), {"id": "a1", "line": "a1"})
        term_ = self.ports.term
        term_.screen = f"{'─' * 20}\n❯ /clear [name]\n{'─' * 20}\n"
        rc, out = self.main(self.src, "--nudge", "調べ")
        self.assertEqual((rc, self.prompts()), (1, []), out)
        self.assertFalse([w for w in term_.writes if w[0] == "send_keys"])
        provision.mark(self.place, self.src, {wake.CLEAR_TYPED: "s"}, self.g)

        def keys(pane, *k):
            term_.writes.append(("send_keys", pane, *k))
            if k == ("ctrl+u",):
                term_.screen = f"{'─' * 20}\n❯ \n{'─' * 20}\n"
        with mock.patch.object(term_, "send_keys", keys):
            rc, out = self.main(self.src, "--nudge", "調べ")
        self.assertEqual(rc, 0, out)
        self.assertEqual([w[2:] for w in term_.writes if w[0] == "send_keys"][0], ("ctrl+u",))
        self.assertEqual([w[2] for w in self.prompts()], [orders.chat.RELOAD, orders.STUCK_LINE])

    def test_nudge_does_not_type_the_line_when_the_reload_does_not_leave_the_box(self):
        # 前の版のプラグインのままの会話は、ターンの終わりに前の版の待ち受けが同じ訳でまた止める（2026-10-19 の割り振り）ので、
        # 1 行の前に読み直させる。読み直しが済んだのを見られなければ、1 行を打たない（/reload-plugins の後ろに続いて届く）
        self.listen("調べ", self.dept_place())
        wake.enqueue(self.inbox, self.dept_place(), {"id": "a1", "line": "a1"})
        deliver.log(self.inbox, {"id": "a1", "kind": "held", "place": self.place, "session": "s", "detail": "子の頼みの返事を待っている（受付 c1）"})
        self.ports.term.screen = f"{'─' * 20}\n❯ \n{'─' * 20}\n"
        with mock.patch.object(orders.deliver, "reload_talk", return_value=("failed", "見られなかった")) as reload:
            rc, out = self.main(self.src, "--nudge", "調べ")
        self.assertEqual((rc, self.prompts(), reload.call_count), (1, [], 1), out)
        self.assertIn("1 行を打たなかった", out)
        nudged = [r for r in deliver.records(self.inbox) if r.get("kind") == "nudged"]
        self.assertEqual([(r["id"], r["status"]) for r in nudged], [("a1", "failed")])

    def test_nudge_does_not_add_the_line_to_text_typed_while_reloading(self):
        # 読み直しを待つ間に人が打ち始めたら、1 行を人の字に足さない。外れうる区切りの印は書き戻す
        self.listen("調べ", self.dept_place())
        wake.enqueue(self.inbox, self.dept_place(), {"id": "a1", "line": "a1"})
        deliver.log(self.inbox, {"id": "a1", "kind": "held", "place": self.place, "session": "s", "detail": "子の頼みの返事を待っている（受付 c1）"})
        provision.mark(self.place, self.src, {"rest": "s"}, self.g)
        self.ports.term.screen = f"{'─' * 20}\n❯ \n{'─' * 20}\n"
        real = self.ports.term.prompt

        def typed_meanwhile(target, text, wait, until=()):
            real(target, text, wait, until)
            if text == orders.chat.RELOAD:
                self.g.unset_worktree_attr(self.place, "rest")   # 読み直しで人の文のフックが走り、区切りの印が外れたとする
                self.ports.term.screen = f"{'─' * 20}\n❯ 人の打ちかけ\n{'─' * 20}\n"
        with mock.patch.object(self.ports.term, "prompt", typed_meanwhile):
            rc, out = self.main(self.src, "--nudge", "調べ")
        self.assertEqual((rc, [w[2] for w in self.prompts()]), (1, [orders.chat.RELOAD]), out)
        self.assertIn("1 行を打たなかった", out)
        self.assertEqual(self.g.worktree_attrs(self.place).get("rest"), "s")

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
        provision.mark(self.place, self.src, {"ask": "a0", "boss": "desk"}, self.g)
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
        provision.mark(self.place, self.src, {"ask": "a0", "delivered": "a0", "boss": "desk"}, self.g)
        self.listen("調べ", self.dept_place(), owner=dead_pid())
        real = orders.live_window

        def handed_meanwhile(dept, ports):
            provision.mark(self.place, self.src, {"ask": "a1", "boss": "段取り"}, self.g)
            return real(dept, ports)
        with mock.patch.object(orders, "live_window", handed_meanwhile):
            rc, out = self.main(self.src, "--ask", "調べ", "--text", "これを調べて")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.prompts(), [])
        attrs = self.g.worktree_attrs(self.place)
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
        attrs = self.g.worktree_attrs(self.place)
        self.assertEqual((attrs["ask"], attrs["boss"]), (urgent["id"], "desk"))   # 待ち受けが渡すときと同じ属性
        taken = [r for r in deliver.records(self.inbox) if r.get("kind") == "taken"]
        self.assertEqual([(r["id"], r["skipped"], r["to"]["name"]) for r in taken], [(urgent["id"], [first["id"]], attrs["name"])])
        # 記録の行で、受けた部署の会話を知らせと取り違えて起動しない（to が字の行だけが知らせ。設計の 3.1）
        me = wake.address(orders.inbox_company(self.inbox, os.path.dirname(self.cfg), self.g), attrs["name"])
        self.assertFalse([r for r in taken if wake.mine(r, {me})])

    def test_take_waits_until_the_current_ask_is_delivered_and_only_takes_its_own_queue(self):
        first, urgent = self.queue_two()
        provision.mark(self.place, self.src, {"ask": "a0", "boss": "desk"}, self.g)
        rc, out = self.main(self.place, "--take", urgent["id"])
        self.assertEqual(rc, 2, out)
        self.assertIn("受付 a0 をまだ納品していない", out)
        provision.mark(self.place, self.src, {"delivered": "a0"}, self.g)
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
        self.assertIn("どの順番待ちにも無く、台帳ではもう閉じている（取り下げ）", out)

    def test_withdraw_closes_an_ask_the_ledger_shows_open_with_nothing_behind_it(self):
        # 2026-10-17 の朝、--withdraw の無かった頃に段取りが順番待ちの件を手で動かし、台帳には順番待ちのまま残った（my_notes の 5b3433 など）
        first, _ = self.queue_two()
        os.unlink(first["path"])
        rc, out = self.main(self.place, "--withdraw", first["id"], "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertFalse([r for r in deliver.records(self.inbox) if r.get("kind") == "withdrawn"])
        rc, out = self.main(self.place, "--withdraw", first["id"])
        self.assertEqual(rc, 0, out)
        self.assertIn("順番待ちの置き場に無いので、台帳で「順番待ち」と出る頼みを取り下げで閉じた", out)
        (row,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "withdrawn"]
        self.assertEqual((row["id"], row["was"], row["why"]), (first["id"], "queued", "順番待ちの置き場に無い"))
        self.assertEqual(self.main(self.place, "--withdraw", first["id"])[0], 2)

    def test_withdraw_does_not_close_an_ask_the_department_still_holds(self):
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "これを調べて")
        self.assertEqual(rc, 0, out)
        held = self.g.worktree_attrs(self.place)["ask"]
        rc, out = self.main(self.src, "--withdraw", held)
        self.assertEqual(rc, 2, out)
        self.assertIn(f"の部署がまだ受けている（取り下げるなら、その旨を --note {held} で足す）", out)
        # 部署の属性がほかの頼みに替わった（10-16 の 75aeee は、69 秒後に同じ本文の頼みが別の部署へ出た）なら閉じる
        provision.mark(self.place, self.src, {"ask": "20261019-000000-ffffff"}, self.g)
        rc, out = self.main(self.src, "--withdraw", held)
        self.assertEqual(rc, 0, out)
        (row,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "withdrawn"]
        self.assertEqual((row["was"], row["why"]), ("working", f"受けた作業場 {self.place} の部署は、今はこの頼みを受けていない"))

    def test_withdraw_closes_an_ask_whose_worktree_is_gone_and_stops_on_an_unknown_one(self):
        # 10-16 の 75aeee: 宛先の作業場が納品せずに消えた
        gone = str(pathlib.Path(self.root) / "gone")
        i = "20261016-103911-aaaaaa"
        deliver.log(self.inbox, {"id": i, "kind": "ask", "at": 1, "status": "sent", "file": None,
                                 "from": {"name": "desk", "place": self.src}, "to": {"name": "点検", "path": gone}})
        rc, out = self.main(self.src, "--withdraw", i)
        self.assertEqual(rc, 0, out)
        (row,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "withdrawn"]
        self.assertEqual((row["was"], row["why"]), ("working", f"受けた作業場 {gone} がもう無い"))
        rc, out = self.main(self.src, "--withdraw", "20261016-103911-bbbbbb")
        self.assertEqual(rc, 2, out)
        self.assertIn("どの順番待ちにも、読んだ台帳にも無い", out)

    def test_an_ask_taken_here_is_working_and_not_closed_by_withdraw(self):
        # --take をその場で受けた頼みは taken の行だけを残す。台帳で順番待ちのままに見えると、--todo が置き場に無いと注記した
        first, _ = self.queue_two()
        self.assertEqual(self.main(self.place, "--take", first["id"])[0], 0)
        rc, out = self.main(self.src, "--withdraw", first["id"])
        self.assertEqual(rc, 2, out)
        self.assertIn("の部署がまだ受けている", out)

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
        provision.mark(self.place, self.src, {"ask": "a0", "boss": "desk"}, self.g)
        to = self.listen("調べ", self.dept_place(), owner=dead_pid())
        rc, out = self.main(self.src, "--note", "a0", "--text", "取り下げる。止めて、どこまで済んだかを返す")
        self.assertEqual(rc, 0, out)
        self.assertIn("ターンの終わりに待ち受けが渡す", out)
        self.assertEqual([w for w in self.ports.term.writes if w[0] in ("prompt", "run")], [])
        notice = next(r for r in deliver.records(self.inbox) if isinstance(r.get("to"), str))
        self.assertEqual((notice["to"], notice["kind"]), (to, wake.NOTE))
        self.assertIn("頼みの足しです（受付 a0 への、desk から", notice["text"])
        self.assertIn("取り下げる。止めて", notice["text"])
        (rec,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "note" and not isinstance(r.get("to"), str)]
        self.assertEqual((rec["ask"], rec["status"], rec["to"]["wake"]), ("a0", "noticed", to))

    def test_note_without_a_waiter_types_into_the_window_and_stops_once_delivered(self):
        provision.mark(self.place, self.src, {"ask": "a0", "boss": "desk"}, self.g)
        rc, out = self.main(self.src, "--note", "a0", "--text", "B も見る")
        self.assertEqual(rc, 0, out)
        (typed,) = self.prompts()
        self.assertIn("頼みの足しです（受付 a0 への", str(typed))
        provision.mark(self.place, self.src, {"delivered": "a0"}, self.g)
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
        provision.mark(self.src, self.src, {"role": "窓口", "name": "desk", "ask": "a0", "boss": "社長室", "boss-inbox": self.inbox}, self.g)
        to = self.listen("調べ", self.dept_place())
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "回す頼み", "--forward", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("回した元: 受付 a0 を閉じ", out)
        self.assertEqual((deliver.records(self.inbox), self.g.worktree_attrs(self.src).get("delivered")), ([], None))
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
        self.assertEqual(self.g.worktree_attrs(self.src)["delivered"], "a0")
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

    def test_forward_from_another_place_closes_the_callers_own_ask(self):
        # 部署の会話が本社へ移って --forward を打っても、本社の部署（段取り）の頼みでなく、打った会話の部署の頼みを閉じ、回した先の
        # 頼みの親と頼み元もその部署にする（受付 7d7f41）
        other = str(pathlib.Path(self.root) / "boss")
        self.g.add_worktree(other, "dept/b", "origin/main")
        provision.mark(other, self.src, {"role": "相談", "name": "社長室", "session": "s-boss", "ask": "q1", "boss": "段取り"}, self.g)
        provision.mark(self.src, self.src, {"role": "段取り", "name": "段取り", "session": "s-desk", "ask": "a0", "boss": "持ち主"}, self.g)
        self.listen("調べ", self.dept_place())
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-boss"}   # 会話の一覧に見えない会話
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "回す頼み", "--forward")
        self.assertEqual(rc, 0, out)
        self.assertIn("回した元の受付 q1 を閉じた", out)
        self.assertEqual(self.g.worktree_attrs(other)["delivered"], "q1")
        self.assertNotIn("delivered", self.g.worktree_attrs(self.src))
        (item,) = wake.queued(self.inbox, self.dept_place())
        self.assertEqual(item["marks"]["boss"], "社長室")
        (row,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "ask"]
        self.assertEqual(row["cause"], "q1")

    def test_forward_to_a_window_without_a_waiter_closes_the_held_ask_once_the_line_is_sent(self):
        provision.mark(self.src, self.src, {"role": "窓口", "name": "desk", "ask": "a0", "boss": "社長室"}, self.g)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "回す頼み", "--forward")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.prompts()), 1)
        (link,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "forwarded"]
        self.assertEqual(link["child"], self.g.worktree_attrs(self.place)["ask"])
        self.assertEqual(self.g.worktree_attrs(self.src)["delivered"], "a0")

    def test_forward_does_not_close_the_held_ask_when_the_ask_did_not_reach(self):
        provision.mark(self.src, self.src, {"role": "窓口", "name": "desk", "ask": "a0", "boss": "社長室"}, self.g)
        provision.mark(self.place, self.src, {"ask": "a9", "boss": "ほか"}, self.g)   # 待ち受けの居ない部署が前の頼みを納品していない
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "回す頼み", "--forward")
        self.assertEqual(rc, 2, out)
        self.assertNotIn("delivered", self.g.worktree_attrs(self.src))
        self.assertEqual([r for r in deliver.records(self.inbox) if r.get("kind") == "forwarded"], [])
        rc, out = self.main(self.src, "--take", "x", "--ask", "調べ", "--forward")
        self.assertEqual(rc, 2, out)
        self.assertIn("--forward は --ask と一緒にだけ使う", out)

    def test_deliver_for_returns_a_forwarded_ask_to_its_asker_without_closing_the_one_held_now(self):
        # 窓口が回して閉じた頼み（a0）の結果を返すとき、その後に受けた頼み（a1）は閉じない
        provision.mark(self.src, self.src, {"role": "窓口", "name": "desk", "ask": "a0", "boss": "社長室", "boss-session": "s-boss",
                                            "boss-inbox": self.inbox}, self.g)
        self.listen("調べ", self.dept_place())
        self.assertEqual(self.main(self.src, "--ask", "調べ", "--text", "回す頼み", "--forward")[0], 0)
        (child,) = [r["child"] for r in deliver.records(self.inbox) if r.get("kind") == "forwarded"]
        summary = pathlib.Path(self.root).parent / "summary.md"
        summary.write_text(test_deliver.GOOD, encoding="utf-8")
        rc, out = self.main(self.src, "--deliver", str(summary))   # 回して閉じた頼みへ --for を付けずに返そうとした
        self.assertEqual(rc, 2, out)
        self.assertIn("--forward で回して閉じた。回した先の結果か問いを返すなら --for a0 を付けて打ち直す", out)
        # ほかの部署が回した行の受付は渡せない（その部署の頼み元へ届く。受付 b54685）
        deliver.log(self.inbox, {"id": "f0", "kind": "forwarded", "child": "f1", "from": {"name": "窓口2", "place": "/elsewhere"},
                                 "boss": {"name": "社長室", "session": "s-boss", "inbox": self.inbox}})
        rc, out = self.main(self.src, "--deliver", str(summary), "--for", "f1")
        self.assertEqual(rc, 2, out)
        self.assertIn("受付 f1 を回したのはこの部署（desk）でなく 窓口2", out)
        provision.mark(self.src, self.src, {"ask": "a1", "boss": "持ち主", "boss-session": "s-owner"}, self.g)
        boss = self.listen("社長室", "/elsewhere/.git")
        rc, out = self.main(self.src, "--deliver", str(summary), "--for", "nope")
        self.assertEqual(rc, 2, out)
        self.assertIn("受付 nope を回した行が台帳に無い", out)
        for key in ("a0", child):   # 回した元の受付でも、回した先の受付でも引ける
            rc, out = self.main(self.src, "--deliver", str(summary), "--for", key)
            self.assertEqual(rc, 0, out)
            notice, rec = deliver.records(self.inbox)[-2:]
            self.assertEqual((notice["to"], notice["id"]), (boss, "a0"))
            self.assertEqual((rec["ask"], rec["for"], rec["to"]["name"], rec["to"]["session"]), ("a0", key, "社長室", "s-boss"))
        attrs = self.g.worktree_attrs(self.src)
        self.assertEqual((attrs["ask"], attrs["delivered"], attrs["boss"]), ("a1", "a0", "持ち主"))   # 今の頼みはそのまま
        rc, out = self.main(self.src, "--for", "a0")
        self.assertEqual(rc, 2, out)
        self.assertIn("--for は --deliver と一緒にだけ使う", out)

    def test_deliver_for_returns_a_child_asks_answer_to_the_asker_of_the_ask_it_came_from(self):
        # 受けた頼み（a0）を閉じずに cause 付きの --ask で回した子の頼みの答えを、a0 の頼み元へ返す。a0 を納品し、次の頼み（a1）を
        # 受けた後でも、子の行に残した頼み元（cause_boss）へ届く（my_notes の受付 20261019-005554-1f3389）
        provision.mark(self.src, self.src, {"role": "窓口", "name": "desk", "ask": "a0", "boss": "社長室", "boss-session": "s-boss",
                                            "boss-inbox": self.inbox}, self.g)
        # a0 はこの部署が受けた頼み（台帳の頼みの行の宛先がこの部署）。受けた頼みでも、子を回した元の受付は --for に渡せる
        deliver.log(self.inbox, {"id": "a0", "kind": "ask", "cause": None, "from": {"name": "社長室", "place": "/elsewhere"},
                                 "to": {"name": "desk"}})
        self.listen("調べ", self.dept_place())
        self.assertEqual(self.main(self.src, "--ask", "調べ", "--text", "残った疑問を調べて")[0], 0)
        (row,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "ask" and r.get("cause") == "a0"]
        self.assertEqual((row["cause_boss"]["name"], row["cause_boss"]["session"]), ("社長室", "s-boss"))
        boss = self.listen("社長室", "/elsewhere/.git")
        summary = pathlib.Path(self.root).parent / "summary.md"
        summary.write_text(test_deliver.GOOD, encoding="utf-8")
        rc, out = self.main(self.src, "--deliver", str(summary), "--for", row["id"])   # a0 をまだ納品していない
        self.assertEqual(rc, 2, out)
        self.assertIn("まだ納品されていない", out)
        self.assertEqual(self.main(self.src, "--deliver", str(summary))[0], 0)   # a0 の納品
        provision.mark(self.src, self.src, {"ask": "a1", "boss": "持ち主", "boss-session": "s-owner"}, self.g)
        for key in ("a0", row["id"]):   # 元の受付でも、子の受付でも引ける
            rc, out = self.main(self.src, "--deliver", str(summary), "--for", key)
            self.assertEqual(rc, 0, out)
            notice, rec = deliver.records(self.inbox)[-2:]
            self.assertEqual((notice["to"], notice["id"]), (boss, "a0"))
            self.assertEqual((rec["ask"], rec["for"], rec["to"]["name"], rec["to"]["session"]), ("a0", key, "社長室", "s-boss"))
        attrs = self.g.worktree_attrs(self.src)
        self.assertEqual((attrs["ask"], attrs["boss"]), ("a1", "持ち主"))   # 今の頼みはそのまま
        # ほかの部署（点検）が回してこの部署が受けた子の頼み c9 は、子の受付でも元の受付でも渡せない（点検の頼み元へ届く。受付 b54685
        # の 481db2 は、届け先が割り振り自身に決まった）。誰が閉じたかも出す
        deliver.log(self.inbox, {"id": "c9", "kind": "ask", "cause": "a9", "from": {"name": "点検", "place": "/elsewhere"},
                                 "to": {"name": "desk"}, "cause_boss": {"name": "desk", "session": "s-desk", "inbox": self.inbox}})
        deliver.log(self.inbox, {"id": "d9", "kind": "deliver", "ask": "c9", "status": "sent", "from": {"name": "desk：c9"}})
        for key in ("c9", "a9"):
            rc, out = self.main(self.src, "--deliver", str(summary), "--for", key)
            self.assertEqual(rc, 2, out)
            self.assertIn(f"受付 {key} を回したのはこの部署（desk）でなく 点検", out)
        self.assertNotIn("納品 d9", out)   # a9 には納品の行が無い
        rc, out = self.main(self.src, "--deliver", str(summary), "--for", "c9")
        self.assertIn("- 受付 c9 は、desk：c9 が納品 d9 で返して閉じている", out)

    def test_a_child_ask_without_cause_boss_finds_the_asker_in_the_original_asks_row(self):
        # cause_boss を書く前の版の行: 元の頼みの行（頼み元の受付箱の台帳に在る）の from と本文の置き場から頼み元を組み立てる
        theirs = os.path.join("/x", "other", ".git", "company", "inbox")
        rows = [{"kind": "ask", "id": "a0", "file": os.path.join(theirs, "a0-ask.md"), "cause": None,
                 "from": {"name": "fc", "session": "s-fc", "account": "p1", "place": "/x/other"}},
                {"kind": "ask", "id": "c1", "cause": "a0", "file": "/y/.git/company/inbox/c1-ask.md", "from": {"name": "調べもの"}}]
        for key in ("a0", "c1"):
            got = orders.caused_ask(rows, key)
            self.assertEqual((got["id"], got["boss"]["name"], got["boss"]["session"], got["boss"]["inbox"]), ("a0", "fc", "s-fc", theirs))
        self.assertIsNone(orders.caused_ask(rows, "nope"))
        # 子が回した孫の行（cause が子）と、--take で回し直した子の行（cause が回し直した部署の頼み）が後に在っても、子の最初の行で引く
        later = rows + [{"kind": "ask", "id": "g1", "cause": "c1", "cause_boss": {"name": "調べもの"}},
                        {"kind": "ask", "id": "c1", "cause": "b9", "cause_boss": {"name": "ほか"}}]
        self.assertEqual(orders.caused_ask(later, "c1")["id"], "a0")
        self.assertIsNone(orders.caused_ask(rows[1:], "c1"))   # 元の頼みの行が読めなければ引けない

    def test_a_machine_role_cannot_be_asked(self):
        self.shape('[[roles]]\nname = "配布"\nmachine = true\n')
        rc, out = self.main(self.src, "--ask", "配布", "--text", "配って", "--task", "x", "--branch", "b/x")
        self.assertEqual(rc, 2, out)
        self.assertIn("機械だけの役", out)

    def test_deliver_to_a_listening_asker_needs_no_window(self):
        summary = self.ask_then_summary(test_deliver.GOOD)
        to = self.listen("desk", self.g.git_dir(self.src))
        self.ports.term._panes = [p for p in self.ports.term._panes if p["pane_id"] != self.desk]   # 頼み元の窓が無くても届く
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.prompts(), [])
        notice, rec = deliver.records(self.inbox)[-2:]
        self.assertEqual((notice["to"], notice["kind"], notice["file"]), (to, "deliver", rec["file"]))
        self.assertIn("【結論】直した。", notice["text"])
        self.assertEqual((rec["status"], rec["to"]["wake"]), ("sent", to))
        attrs = self.g.worktree_attrs(self.place)
        self.assertEqual(attrs["delivered"], attrs["ask"])


    def test_deliver_finds_the_asker_by_its_talk_when_the_name_misses(self):
        # 前の版が会話の一覧の名前（my-notes-d7）を頼み元に書いた部署: 名前では待ち受けが引けないので、頼んだ会話の id で引く
        summary = self.ask_then_summary(test_deliver.GOOD)
        provision.mark(self.place, self.src, {"boss": "my-notes-d7"}, self.g)
        to = wake.address(orders.inbox_company(self.inbox, os.path.dirname(self.cfg), self.g), "段取り")
        wake.claim(self.inbox, self.g.git_dir(self.src), [to], "s-desk", os.getpid(), "t", time.time())
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.prompts(), [])
        notice, rec = deliver.records(self.inbox)[-2:]
        self.assertEqual((notice["to"], rec["to"]["wake"]), (to, to))

    def test_deliver_to_an_asker_mid_turn_goes_to_the_ledger_not_the_window(self):
        # 頼み元の会話は生きているが、人の文で始まったターンの途中で待ち受けが止まっている（生きた印は無く、読んだ所のファイルは残る）:
        # 窓に打ち込まず台帳に置き、ターンの終わりに張り直した待ち受けに渡させる（2026-10-20 に works-factory-co の工場窓口で、納品が
        # 持ち主の入力として窓に打ち込まれた）
        summary = self.ask_then_summary(test_deliver.GOOD)
        provision.mark(self.src, self.src, {"role": "窓口", "name": "desk", "session": "s-desk"}, self.g)
        to = self.listen("desk", self.g.git_dir(self.src))
        wake.release(self.inbox, self.g.git_dir(self.src), "t")
        self.assertIsNone(wake.listening(self.inbox, to))
        listed = self.ports.list_sessions
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {**s, "status": "busy"} if s["sessionId"] == "s-desk" else s for s in listed(cdir, include_done)]
        company = orders.inbox_company(self.inbox, os.path.dirname(self.cfg), self.g)
        talk = self.ports.list_sessions(None)[0]
        self.assertEqual(orders.resting_listener(self.inbox, company, {**talk, "status": "idle"}, self.ports), [])   # 手が空いている
        provision.mark(self.src, self.src, {"session": "s-other"}, self.g)   # 属性の会話が頼み元でない場所（本社のほかの会話の頼み）
        self.assertEqual(orders.resting_listener(self.inbox, company, talk, self.ports), [])
        provision.mark(self.src, self.src, {"session": "s-desk"}, self.g)
        self.ports.env = {**self.ports.env, "CLAUDE_CODE_SESSION_ID": "s-dept"}   # 納品は部署の会話が打つ（orders.own_place）
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.prompts(), [])
        notice, rec = deliver.records(self.inbox)[-2:]
        self.assertEqual((notice["to"], notice["kind"], notice["file"]), (to, "deliver", rec["file"]))
        self.assertEqual((rec["status"], rec["to"]["wake"]), ("sent", to))
        self.assertIn("ターンの終わりに渡す", rec["detail"])
        attrs = self.g.worktree_attrs(self.place)
        self.assertEqual(attrs["delivered"], attrs["ask"])

    def test_deliver_to_an_asker_without_a_listener_trace_types_into_the_window(self):
        # 待ち受けの居た跡の無い頼み元（フックの無い前の版の会話）には、今までどおり窓に打ち込む
        summary = self.ask_then_summary(test_deliver.GOOD)
        provision.mark(self.src, self.src, {"role": "窓口", "name": "desk", "session": "s-desk"}, self.g)
        self.ports.env = {**self.ports.env, "CLAUDE_CODE_SESSION_ID": "s-dept"}   # 納品は部署の会話が打つ（orders.own_place）
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        (w,) = self.prompts()
        self.assertEqual(w[1], self.desk)


if __name__ == "__main__":
    unittest.main()
