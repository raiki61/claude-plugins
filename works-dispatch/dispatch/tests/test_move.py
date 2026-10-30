"""--move（move.py）と、上限で止まったときのフック（limit_hook.py）。git（tests/fakegit.py）・herdr・claude は偽物で回す。"""

import io
import json
import os
import pathlib
import re
import shutil
import time
import unittest
from unittest import mock

from . import test_deliver
import claudex
import dispatch
import limit_hook
import move
from nodes import deliver, launch, provision, role, wake


Q = "'" if os.name != "nt" else '"'   # 起動の 1 行で文を囲む引用符（launch._quote の形。Windows のシェルは二重引用符）


def q(text):
    return re.escape(launch._quote(text, os.name != "nt"))


class Move(unittest.TestCase):
    """場の作りは test_deliver.Flow の物を借りる（継ぐと、その試験が二度走る）。アカウントは a1（今）と a2（移る先）。"""

    Flow = test_deliver.Flow
    main = Flow.main
    del Flow

    def setUp(self):
        test_deliver.Flow.setUp(self)
        text = pathlib.Path(self.cfg).read_text(encoding="utf-8")
        d = pathlib.Path(self.cfg).parent
        pathlib.Path(self.cfg).write_text(text.replace(
            "accounts = [", f"accounts = [{{ name = \"a2\", command = \"claude-a2\", config_dir = '{d}/c2' }}, "), encoding="utf-8")
        self.stopped = []
        self.ports.stop_session = lambda cdir, job: self.stopped.append((os.path.basename(cdir or ""), job)) or (True, "")
        h = self.ports.term
        h.front[self.window] = ["claude-a1", "attach", "d"]
        real_keys = h.send_keys

        def keys(pane, *k):   # 2.1.302: Ctrl+Z は会話の一覧の画面を出し、Esc でシェルに戻る
            real_keys(pane, *k)
            if k == ("escape",):
                h.talking.discard(pane)
                h.front.pop(pane, None)
        h.send_keys = keys

    def fake_task(self, rc=0):
        seen = []

        def task(cfg, repo, ns, ports, extra_attrs=None, tail=None, refreshed=False):
            seen.append({"ns": ns, "extra": extra_attrs, "tail": tail,
                         "brief": pathlib.Path(ns.brief).read_text(encoding="utf-8"), "attrs": self.g.worktree_attrs(self.place)})
            return rc
        return seen, task

    def test_a_department_is_stopped_and_started_again_on_the_other_account_keeping_its_asker(self):
        provision.mark(self.place, self.src, {"lifecycle": "persistent", "ask": "q1", "boss": "desk", "boss-inbox": self.inbox,
                                              "job": "d"}, self.g)
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.stopped, [("c1", "d")])   # 前の会話を前のアカウントで止めてから
        keys = [w for w in self.ports.term.writes if w[0] == "send_keys"]
        self.assertEqual([k[2] for k in keys], ["ctrl+z", "escape"])   # 窓の attach の画面をシェルに戻す（d7d50c の 1）
        (got,) = seen
        self.assertEqual((got["ns"].task, got["ns"].branch, got["ns"].only_account, got["ns"].role), ("調べ", "dept/a", "a2", "調べ役"))
        self.assertTrue(got["ns"].persistent)
        self.assertEqual(got["extra"]["boss"], "desk")   # 頼み元はそのまま（納品は元の頼み元へ）
        self.assertIn("受付 q1", got["brief"])
        self.assertIn("アカウント a1", got["brief"])
        self.assertIn("--deliver", got["tail"])
        self.assertNotIn("session", got["attrs"])   # 新しい会話の待ち受けが前の id を見ないよう、起動する前に消す
        (moved,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual((moved["from"], moved["to"], moved["status"]), ("a1", "a2", "done"))

    def test_an_ask_handed_to_the_old_talk_just_before_it_stopped_is_handed_again_in_the_first_text(self):
        # 読んだ後、止めるまでの間に前の会話の待ち受けが順番待ちの頼みを渡した（属性を書き替えた）。渡した字は止めた会話と消えるので、
        # 最初の文でその頼みを渡し、頼み元も今の物を残す（my_notes の受付 4bae53 と同じ重なりの、--move の側）
        provision.mark(self.place, self.src, {"lifecycle": "persistent", "ask": "q0", "delivered": "q0", "boss": "desk",
                                              "boss-inbox": self.inbox, "job": "d"}, self.g)
        stop = self.ports.stop_session

        def handed_then_stopped(cdir, job):
            provision.mark(self.place, self.src, {"ask": "q1", "boss": "段取り"}, self.g)
            return stop(cdir, job)
        self.ports.stop_session = handed_then_stopped
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ")
        self.assertEqual(rc, 0, out)
        (got,) = seen
        self.assertIn("受付 q1", got["brief"])
        self.assertNotIn("受けている頼みは無い", got["brief"])
        self.assertEqual(got["extra"]["boss"], "段取り")
        self.assertIn("--deliver", got["tail"])

    def test_the_first_text_points_to_the_handoff_the_old_talk_wrote(self):
        # 前の会話が作業場の git の場所に書いた引継ぎ（handoff.md）に、最初の文が触れず、移った先の会話が読み落としえた（受付 f39d00）
        provision.mark(self.place, self.src, {"lifecycle": "persistent", "ask": "q1", "boss-inbox": self.inbox, "job": "d"}, self.g)
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            self.assertEqual(self.main(self.src, "--move", "調べ")[0], 0)
        self.assertNotIn(wake.HANDOFF, seen[0]["brief"])   # 書いていなければ触れない
        handoff = os.path.join(self.g.git_dir(self.place), wake.HANDOFF)
        pathlib.Path(handoff).write_text("# 引継ぎ\n", encoding="utf-8")
        provision.mark(self.place, self.src, {"job": "d"}, self.g)
        with mock.patch.object(dispatch, "_task", task):
            self.assertEqual(self.main(self.src, "--move", "調べ")[0], 0)
        kept = [n for n in os.listdir(self.g.git_dir(self.place)) if n.startswith("handoff-")]
        self.assertEqual(len(kept), 1, kept)   # 指した引継ぎは時刻の名前に退ける
        self.assertIn(f"前の会話が書いた引継ぎ {os.path.join(self.g.git_dir(self.place), kept[0])}（", seen[1]["brief"])
        self.assertFalse(os.path.exists(handoff))
        with mock.patch.object(dispatch, "_task", task):
            self.assertEqual(self.main(self.src, "--move", "調べ")[0], 0)
        self.assertNotIn("前の会話が書いた引継ぎ", seen[2]["brief"])   # 後の --move は、前の頼みの引継ぎを指さない

    def test_the_desk_keeps_the_handoff_when_it_does_not_start_again_now(self):
        # 窓口の --move は、ターンの途中で今は起動し直さないと決める前に引継ぎを時刻の名前へ退けていて、次の起動し直しが引継ぎを指さなかった
        self.desk_world()
        handoff = os.path.join(self.g.git_dir(self.src), wake.HANDOFF)
        pathlib.Path(handoff).write_text("# 引継ぎ\n", encoding="utf-8")
        h = self.ports.term
        h.agent = lambda pane: {"agent": "claude", "agent_status": "working"}
        rc, out = self.main(self.src, "--move", "窓口", "--account", "a2")
        self.assertEqual(rc, move.NOT_NOW, out)
        self.assertTrue(os.path.exists(handoff))   # 起動し直さなければ退けない
        h.agent = lambda pane: {"agent": "claude", "agent_status": "idle"}
        rc, out = self.main(self.src, "--move", "窓口", "--account", "a2")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(handoff))
        (run,) = [w[2] for w in h.writes if w[1] == self.desk and w[0] == "run"]
        self.assertIn("前の会話が書いた引継ぎ", run)

    def test_a_department_that_does_not_start_again_is_attached_back_only_when_no_new_talk_rose(self):
        provision.mark(self.place, self.src, {"lifecycle": "persistent", "job": "d", "session": "s-dept", "account": "a1"}, self.g)
        seen, task = self.fake_task(rc=1)
        listed = self.ports.list_sessions
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ")   # 移る先に同じ名前の会話が見える（窓につなぐ所だけ落ちた）
        self.assertEqual(rc, 1, out)
        self.assertEqual([w for w in self.ports.term.writes if w[0] == "run"], [])   # 2 つ立てない
        self.ports.term.writes.clear()
        provision.mark(self.place, self.src, {"job": "d", "session": "s-dept", "account": "a1"}, self.g)
        self.ports.list_sessions = lambda cdir, include_done=False: [] if cdir and cdir.endswith("c2") else listed(cdir, include_done)
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ")
        self.assertEqual(rc, 1, out)
        self.assertEqual([w[2] for w in self.ports.term.writes if w[0] == "run"], ["claude-a1 attach d"])
        attrs = self.g.worktree_attrs(self.place)
        self.assertEqual((attrs["session"], attrs["job"], attrs["account"]), ("s-dept", "d", "a1"))   # 前の会話の値に戻す
        self.assertIn("前の会話を attach で戻した", [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"][-1]["detail"])

    READY = f"{'─' * 20}\n❯ \n{'─' * 20}\n"   # 手の空いた窓（入力フィールドが空）

    def typed_lines(self):
        return [w[2] for w in self.ports.term.writes if w[0] == "prompt" and w[1] == self.window]

    def ends_well_after(self, seen, starts=1):
        """--if-limited が起動し直した後の見直しの待ちに、新しい会話のターンが誤りなく終わる（wake_hook.ended_well が待ちの印を外す）
        のを差し込む。starts 回起動した後の待ちから効く。外す前の印を self.held に残す。"""
        self.held = []

        def on_sleep(_s):
            if len(seen) >= starts:
                self.held.append(self.g.worktree_attrs(self.place).get(wake.LIMIT_HOLD))
                provision.mark(self.place, self.src, {wake.LIMIT_HOLD: None}, self.g)
        return on_sleep

    def test_if_limited_waits_while_the_account_is_under_its_limit_then_goes_on_in_the_same_talk(self):
        # 一時の混み合い（同時の要求の超過など）では移さないが、止まった会話を放っておかず、待ってから同じ会話に続きの 1 行を打つ
        # （前は「移さない」で終わり、部署が止まったまま残った。受付 e33748 の穴）
        under = {"a1": {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 20}}, "a2": None}
        self.ports.limits_seq = [under, under]
        self.ports.term.screen = self.READY
        provision.mark(self.place, self.src, {"lifecycle": "persistent", "job": "d", "ask": "q1", "rest": "s-dept"}, self.g)
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertEqual((seen, self.stopped), ([], []))
        self.assertEqual(self.ports.slept, [move.WAIT])
        self.assertEqual(self.typed_lines(), [move.GO_ON.format(account="a1")])
        rows = [r for r in deliver.records(self.inbox) if r.get("kind") in ("moved", "nudged")]
        self.assertEqual([(r["kind"], r["status"]) for r in rows], [("moved", move.WAITING), ("nudged", "sent")])
        self.assertEqual((rows[0]["why"], rows[1]["id"]), (move.LIMITED, "q1"))
        attrs = self.g.worktree_attrs(self.place)
        self.assertNotIn(wake.LIMIT_HOLD, attrs)
        self.assertEqual(attrs.get("rest"), "s-dept")   # 打った 1 行で外れうる印は書き戻す

    def test_if_limited_dry_run_only_says_it_would_wait(self):
        self.ports.limits_seq = [{"a1": {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 20}}, "a2": None}]
        rc, out = self.main(self.src, "--move", "調べ", "--if-limited", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("移さない", out)
        self.assertFalse(getattr(self.ports, "slept", []))

    def test_if_limited_does_not_move_on_an_old_snapshot_under_the_limit(self):
        # 取り直しが止まって控えが古くても、最後の値が上限の下なら一時の混み合いと見る（古いと「分からない」になり、移っていた）
        old = {"a1": {"five_hour": {"used_percentage": 10, "updated_at": 1},
                      "seven_day": {"used_percentage": 20, "updated_at": 1}}, "a2": None}
        self.ports.limits_seq = [old, old]
        self.ports.now = lambda: 1_800_000_000
        self.ports.term.screen = self.READY
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertIn("一時の混み合いと見る", out)
        self.assertEqual((seen, self.typed_lines()), ([], [move.GO_ON.format(account="a1")]))

    def test_if_limited_with_no_other_account_waits_and_moves_once_one_has_room(self):
        # 移る先が無くても止めたままにせず、ほかのアカウントが空く時刻（ここでは a2 の 5 時間の枠の切り替わり）まで待って移す
        full = {"five_hour": {"used_percentage": 100, "resets_at": 1_800_007_200}, "seven_day": {"used_percentage": 50}}
        now = 1_800_000_000
        self.ports.now = lambda: now
        self.ports.limits_seq = [{"a1": full, "a2": full}, {"a1": full, "a2": {"five_hour": {"used_percentage": 0}}}]
        provision.mark(self.place, self.src, {"lifecycle": "persistent", "job": "d"}, self.g)
        seen, task = self.fake_task()
        self.ports.on_sleep = self.ends_well_after(seen)
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertIn("移れるアカウントが無い", out)
        # 空く時刻が最長の間より先なら、最長の間で見直す。移した後も、新しい会話の初めのターンが断られないかを 1 度見る
        self.assertEqual(self.ports.slept, [move.LONGEST, move.WAIT])
        self.assertTrue(self.held[0])
        self.assertIn("待つのをやめた", out)
        self.assertEqual([x["ns"].only_account for x in seen], ["a2"])
        self.assertIn("使用上限に当たった", seen[0]["brief"])
        rows = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual([(r["status"], r["to"]) for r in rows], [(move.WAITING, None), ("done", "a2")])
        self.assertNotIn(wake.LIMIT_HOLD, self.g.worktree_attrs(self.place))

    def test_if_limited_stops_waiting_when_the_wait_mark_changes(self):
        # 待つ間に、会話のターンが誤りなく終わった（印が外れる）か、後から止まった回の --move が待ちを引き継いだ（印を書き替える）ら、
        # 打たずにやめる
        full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
        for after in (None, "1-1"):
            with self.subTest(after=after):
                self.ports.limits_seq = [{"a1": full, "a2": full}, {"a1": None, "a2": full}]
                self.ports.slept = []
                self.ports.term.screen = self.READY
                self.ports.on_sleep = lambda _s, after=after: provision.mark(self.place, self.src, {wake.LIMIT_HOLD: after}, self.g)
                rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
                self.assertEqual(rc, 0, out)
                self.assertIn("待つのをやめた", out)
                self.assertEqual(self.typed_lines(), [])

    def gone_while_waiting(self, gone):
        """--if-limited が待ち始めた後、1 度目の待ちの間に gone で部署を消し、見直さずに台帳へ訳を残して終わるのを確かめる。台帳の
        moved の行の detail を返す。"""
        full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
        self.ports.limits_seq = [{"a1": full, "a2": full}]
        self.ports.on_sleep = lambda _s: gone()
        rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.ports.slept), 1)   # 消えた後は見直さない
        self.assertIn("消えた", out)
        rows = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual([r["status"] for r in rows], [move.WAITING, "skipped"])
        self.assertEqual((rows[-1]["why"], rows[-1]["path"]), (move.GONE, self.place))
        return rows[-1]["detail"]

    def test_if_limited_stops_waiting_once_the_department_place_is_gone_and_leaves_why_in_the_ledger(self):
        # 待つ間に部署が畳まれて作業場が消えたら、宛先を引けない誤りを一時の誤りと見て待ち続けない
        # （works-factory で、畳まれた部署を 10 分ごとに約 2254 分見直し続けた。受付 5b5019）
        self.assertIn("作業場が無い", self.gone_while_waiting(lambda: shutil.rmtree(self.place)))

    def test_if_limited_stops_waiting_once_the_department_attrs_are_gone(self):
        self.assertIn("company.role", self.gone_while_waiting(
            lambda: provision.mark(self.place, self.src, {"role": None}, self.g)))

    def test_if_limited_stops_on_a_changed_wait_mark_even_while_the_department_cannot_be_found(self):
        # 宛先を引けない間も、待ちの印が替われば（同じ場所に別の部署が立った・ターンが誤りなく終わった）herdr を通さずにやめる
        full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
        self.ports.limits_seq = [{"a1": full, "a2": full}]
        find, waited = move.deliver.find_target, []
        self.ports.on_sleep = lambda _s: waited.append(1) or provision.mark(self.place, self.src, {wake.LIMIT_HOLD: "other"}, self.g)

        def missing(*args, **kw):
            if waited:
                raise move.deliver.DeliverError("「調べ」という部署が無い")
            return find(*args, **kw)
        with mock.patch.object(move.deliver, "find_target", missing):
            rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertIn("待ちの印", out)
        self.assertEqual(len(self.ports.slept), 1)
        self.assertEqual([r["status"] for r in deliver.records(self.inbox) if r.get("kind") == "moved"], [move.WAITING])

    def test_if_limited_keeps_waiting_while_the_department_is_there_but_cannot_be_found(self):
        # 作業場と属性が在るのに宛先を引けない（herdr の一覧の一時の抜けなど）間は、今までどおり待ち直す
        full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
        self.ports.limits_seq = [{"a1": full, "a2": full}, {"a1": full, "a2": full}]
        find, calls = move.deliver.find_target, []

        def missing(*args, **kw):
            calls.append(1)
            if len(calls) == 2:
                raise move.deliver.DeliverError("「調べ」という部署が無い")
            return find(*args, **kw)
        self.ports.on_sleep = lambda _s: len(self.ports.slept) == 2 and provision.mark(self.place, self.src, {wake.LIMIT_HOLD: None}, self.g)
        with mock.patch.object(move.deliver, "find_target", missing):
            rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertIn("見直せなかった（DeliverError", out)
        self.assertNotIn("消えた", out)
        self.assertEqual(len(self.ports.slept), 2)

    def test_if_limited_waits_again_over_a_typing_window_and_stops_when_the_talk_already_runs(self):
        # 持ち主の打ちかけの字に 1 行を足さない（待ち直す）。会話がもう動いていれば打たずにやめる
        full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
        self.ports.limits_seq = [{"a1": full, "a2": full}, {"a1": None, "a2": full}, {"a1": None, "a2": full}]
        self.ports.term.screen = "─" * 20 + "\n❯ 打ちかけ\n" + "─" * 20
        h = self.ports.term
        busy = []
        h.agent = lambda pane: {"agent": "claude", "agent_status": "working" if busy else "idle"}
        self.ports.on_sleep = lambda _s: busy.append(1) if len(self.ports.slept) == 2 else None
        rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.ports.slept, [move.WAIT, move.WAIT])
        self.assertIn("入力フィールドに字（「打ちかけ」）が在る", out)
        self.assertIn("もう動いている", out)
        self.assertEqual(self.typed_lines(), [])

    def test_if_limited_waits_longer_while_the_lines_it_typed_keep_being_refused(self):
        # 続きの 1 行がまた断られ続ける（使用率の控えに出ない上限など）なら、打つ間を 2 倍ずつ延ばす（10 分ごとに打ち続けない）
        now = 1_800_000_000
        self.ports.now = lambda: now
        under = {"a1": {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 20}}, "a2": None}
        self.ports.limits_seq = [under, under]
        self.ports.term.screen = self.READY
        for at in (now - 1200, now - 600):
            deliver.log(self.inbox, {"id": None, "kind": "nudged", "at": at, "place": self.place, "why": move.GONE_ON, "status": "sent"})
        rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.ports.slept, [move.WAIT * 4])
        self.assertEqual(self.typed_lines(), [move.GO_ON.format(account="a1")])

    def test_if_limited_does_not_start_again_over_a_talk_that_runs_again_after_the_wait(self):
        # 待つ間に持ち主が続きを打って会話が動き出したら、ほかのアカウントが空いても止めて起動し直さない
        full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
        self.ports.limits_seq = [{"a1": full, "a2": full}, {"a1": full, "a2": {"five_hour": {"used_percentage": 0}}}]
        self.ports.term.agent = lambda pane: {"agent": "claude", "agent_status": "working" if self.ports.slept else "idle"}
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertIn("もう動いている", out)
        self.assertEqual((seen, self.stopped), ([], []))
        self.assertNotIn(wake.LIMIT_HOLD, self.g.worktree_attrs(self.place))

    def test_if_limited_keeps_waiting_over_a_passing_error_and_a_failed_start(self):
        # 待つ間の一時の誤り（herdr に届かない）と、移す先で起動できなかったときは、待つのをやめずに待ち直す
        full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
        free = {"five_hour": {"used_percentage": 0}}
        self.ports.limits_seq = [{"a1": full, "a2": full}, {"a1": full, "a2": free}, {"a1": full, "a2": free}]
        survey, calls = move.orders.survey, []

        def flaky(*args):
            calls.append(1)
            if len(calls) == 2:
                raise move.term.Error(["herdr"], "届かない")
            return survey(*args)
        seen, first = self.fake_task(rc=1)

        def task(*args, **kw):
            return first(*args, **kw) if len(seen) == 0 else first(*args, **kw) and 0   # 初めの起動だけ落ちる
        self.ports.on_sleep = self.ends_well_after(seen, 2)
        with mock.patch.object(move.orders, "survey", flaky), mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertIn("見直せなかった", out)
        self.assertIn("待つ: アカウント a2 で起動し直せなかった", out)
        self.assertEqual(len(self.ports.slept), 4)
        self.assertEqual([x["ns"].only_account for x in seen], ["a2", "a2"])   # 起動できなかった後、待ち直して起動した
        rows = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual([r["status"] for r in rows][-1], "done")
        self.assertEqual(sum(r["status"] == move.WAITING for r in rows), 2)

    def test_if_limited_waits_again_when_the_line_does_not_reach_the_talk(self):
        # 続きの 1 行が届かなかった（herdr の一時の誤りなど）ら、待ちの印を残して待ち直す（止まったまま残さない）
        under = {"a1": {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 20}}, "a2": None}
        self.ports.limits_seq = [under, under, under]
        self.ports.term.screen = self.READY
        send, tries = move.deliver.send_confirmed, []

        def flaky(*args, **kw):
            tries.append(1)
            return ("failed", "届かない") if len(tries) == 1 else send(*args, **kw)
        with mock.patch.object(move.deliver, "send_confirmed", flaky):
            rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(tries), 2)
        self.assertEqual(self.ports.slept[0], move.WAIT)
        self.assertGreater(self.ports.slept[1], move.WAIT)   # 打った回に数えるので、待つ間が延びる
        self.assertNotIn(wake.LIMIT_HOLD, self.g.worktree_attrs(self.place))

    def test_if_limited_dry_run_with_no_other_account_says_it_would_wait(self):
        full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
        self.ports.limits_seq = [{"a1": full, "a2": full}]
        rc, out = self.main(self.src, "--move", "調べ", "--if-limited", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("待つ: 移れるアカウントが無い", out)
        self.assertFalse(getattr(self.ports, "slept", []))

    def test_the_wait_is_not_shorter_than_the_hook_guard(self):
        # 待った後に打った 1 行がまた断られたら、フックがまた走って待ち直す（フックは同じ場所で AGAIN 秒の間は走らない）
        self.assertGreaterEqual(move.WAIT, limit_hook.AGAIN)

    def test_no_other_account_with_room_stops(self):
        full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
        self.ports.limits_seq = [{"a1": full, "a2": full}]
        rc, out = self.main(self.src, "--move", "調べ")
        self.assertEqual(rc, 2, out)
        self.assertIn("移れるアカウントが無い", out)
        rc, out = self.main(self.src, "--move", "調べ", "--account", "a9")
        self.assertEqual(rc, 2, out)
        self.assertIn("accounts に無い", out)

    def test_naming_the_present_account_starts_the_department_again_on_it(self):
        # 区切りを印さない会話を引き継ぐ部署（my_notes の社長室）を、持ち主が起動し直してよいと答えたとき（受付 93d98b）
        provision.mark(self.place, self.src, {"lifecycle": "persistent", "job": "d", "account": "a1"}, self.g)
        rc, out = self.main(self.src, "--move", "調べ", "--account", "a1", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("アカウント a1 のまま起動し直す", out)
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--account", "a1")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.stopped, [("c1", "d")])
        (got,) = seen
        self.assertEqual(got["ns"].only_account, "a1")
        self.assertIn("同じアカウント a1 のまま", got["brief"])
        (moved,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual((moved["from"], moved["to"], moved["why"]), ("a1", "a1", move.SAME))
        rc, out = self.main(self.src, "--move", "調べ", "--account", "a1", "--if-limited")
        self.assertEqual(rc, 2, out)   # 使用上限で移すのに、今のアカウントでは起動し直さない

    def test_a_department_talking_in_its_window_is_not_stopped_and_is_told_why(self):
        # 部署の窓で持ち主と話す会話も、窓口と同じくターンの途中と打ちかけの字の上からは止めない。会話の外から打った --move なら、
        # 止めた訳をその会話に台帳の知らせで渡す（入力フィールドには打たない）
        provision.mark(self.place, self.src, {"lifecycle": "persistent", "job": "d", "account": "a1"}, self.g)
        h = self.ports.term
        h.screen = "─" * 20 + "\n❯ 打ちかけ\n" + "─" * 20
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--account", "a1")   # 待ち受けの跡が無ければ知らせない（届かない）
            self.assertEqual(rc, move.NOT_NOW, out)
            self.assertIn("待ち受けの跡が無い", out)
            self.assertFalse([r for r in deliver.records(self.inbox) if r.get("kind") == wake.NOTE])
            wake._replace(wake.pos_path(self.inbox, self.g.git_dir(self.place)), "0")
            rc, out = self.main(self.src, "--move", "調べ", "--account", "a1")
            self.assertEqual(rc, move.NOT_NOW, out)
            self.assertIn("入力フィールドに字（「打ちかけ」）が在るので止めない", out)
            # 会社の形の起動の設定で起動し直す待ち受けの --if-changed は、出力で訳を見るので知らせない
            test_deliver.Flow.shape(self, '[[roles]]\nname = "調べ役"\npersistent = true\nmodel = "opus"\n')
            provision.mark(self.place, self.src, {wake.REST: "1"}, self.g)
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
            self.assertEqual(rc, move.NOT_NOW, out)
            self.assertEqual(len([r for r in deliver.records(self.inbox) if r.get("kind") == wake.NOTE]), 1)
            provision.mark(self.place, self.src, {wake.REST: None}, self.g)
            (told,) = [r for r in deliver.records(self.inbox) if r.get("kind") == wake.NOTE]
            self.assertTrue(told["to"].endswith("/調べ"), told)
            self.assertIn("打ちかけ", told["text"])
            self.assertIn("--rest", told["text"])
            # その会話の中から打った --move は、出力で訳を見るので知らせない
            h.screen = ""
            h.agent = lambda pane: {"agent": "claude", "agent_status": "working"}
            rc, out = self.main(self.place, "--move", "調べ", "--account", "a1")
            self.assertEqual(rc, move.NOT_NOW, out)
            self.assertIn("ターンの途中", out)
            self.assertEqual(len([r for r in deliver.records(self.inbox) if r.get("kind") == wake.NOTE]), 1)
            self.assertEqual((seen, self.stopped), ([], []))
            self.assertFalse([w for w in h.writes if w[0] == "send_keys"])
            # 使用上限で止まった会話は、待っても動かないので移す
            full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
            self.ports.limits_seq = [{"a1": full, "a2": {"five_hour": {"used_percentage": 1}, "seven_day": {"used_percentage": 1}}}]
            self.ports.on_sleep = self.ends_well_after(seen)
            rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.stopped, [("c1", "d")])

    def changed_world(self, launched):
        # clear の部署。会社の形の model は opus、起動したときは launched
        test_deliver.Flow.shape(self, '[[roles]]\nname = "調べ役"\npersistent = true\nfresh = true\nmodel = "opus"\n')
        provision.mark(self.place, self.src, {"lifecycle": "persistent", "fresh": role.FRESH, "ask": "q1", "delivered": "q1",
                                              "boss": "desk", "boss-inbox": self.inbox, "job": "d", "launched": launched,
                                              wake.RESTARTING: "s-dept"}, self.g)

    def test_if_changed_restarts_a_fresh_department_on_the_same_account_when_the_model_changed(self):
        self.changed_world(role.launch_key(None))
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.stopped, [("c1", "d")])
        (got,) = seen
        self.assertEqual(got["ns"].only_account, "a1")   # 空きがあれば同じアカウントで
        self.assertIn(move.CHANGED, got["brief"])
        self.assertIn("受けている頼みは無い", got["brief"])
        self.assertIsNone(got["tail"])
        # 前の会話を止めたら待ち受けの印を外す。起動し直した会話は空なので、空にした印も書く
        self.assertNotIn(wake.RESTARTING, got["attrs"])
        self.assertEqual(got["attrs"]["cleared"], "q1")
        (moved,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual((moved["from"], moved["to"], moved["why"]), ("a1", "a1", move.CHANGED))

    def test_a_department_on_a_named_only_account_stays_on_it(self):
        # 名指しのときだけ使うアカウント（named_only）で動く部署は、名指しで移せて、区切りの起動し直しでもそのアカウントに残る
        p = pathlib.Path(self.cfg)
        text = p.read_text(encoding="utf-8")
        self.assertIn('name = "a1", command = "claude-a1",', text)
        p.write_text(text.replace('name = "a1", command = "claude-a1",', 'name = "a1", command = "claude-a1", named_only = true,'),
                     encoding="utf-8")
        self.changed_world(role.launch_key(None))
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
            self.assertEqual(rc, 0, out)
            self.assertEqual(seen[-1]["ns"].only_account, "a1")
            rc, out = self.main(self.src, "--move", "調べ", "--account", "a1")
            self.assertEqual(rc, 0, out)
            self.assertEqual(seen[-1]["ns"].only_account, "a1")
            # 名指さなければ、自動の候補（a2）へ移す
            rc, out = self.main(self.src, "--move", "調べ")
            self.assertEqual(rc, 0, out)
            self.assertEqual(seen[-1]["ns"].only_account, "a2")
            # 上限の a1 は名指しても使わず、前の会話を止めない
            self.stopped.clear()
            full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
            self.ports.limits_seq = [{"a1": full, "a2": None}]
            rc, out = self.main(self.src, "--move", "調べ", "--account", "a1")
            self.assertEqual(rc, 2, out)
            self.assertIn("止めた: アカウント a1 は、five_hour が 100% で上限", out)
            self.assertEqual(self.stopped, [])

    def test_if_limited_goes_on_in_the_same_talk_on_a_named_only_account(self):
        p = pathlib.Path(self.cfg)
        p.write_text(p.read_text(encoding="utf-8").replace('name = "a1", command = "claude-a1",',
                                                           'name = "a1", command = "claude-a1", named_only = true,'), encoding="utf-8")
        under = {"a1": {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 20}}, "a2": None}
        self.ports.limits_seq = [under, under]
        self.ports.term.screen = self.READY
        provision.mark(self.place, self.src, {"lifecycle": "persistent", "job": "d", "ask": "q1", "rest": "s-dept"}, self.g)
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertEqual((seen, self.stopped), ([], []))
        self.assertEqual(self.typed_lines(), [move.GO_ON.format(account="a1")])

    def test_if_changed_keeps_the_talk_when_the_values_are_the_same_or_it_carries_its_talk(self):
        self.changed_world(role.launch_key({"model": "opus"}))
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
            self.assertEqual(rc, 0, out)
            self.assertIn("起動し直さない", out)
            # 印は待ち受けが外す（止めなかったと見て、前の会話に頼みを渡す）
            self.assertEqual(self.g.worktree_attrs(self.place)[wake.RESTARTING], "s-dept")
            # 空いたアカウントが無ければ起動し直さない（上限のアカウントで起動すると、前の会話だけが止まる）
            full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
            self.ports.limits_seq = [{"a1": full, "a2": full}]
            provision.mark(self.place, self.src, {"launched": role.launch_key(None)}, self.g)
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
            self.assertEqual(rc, 0, out)
            self.assertIn("使用率が上限に届かず、使える時間帯の中のアカウントが無い", out)
            provision.mark(self.place, self.src, {"fresh": None}, self.g)
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
            self.assertEqual(rc, 2, out)
            self.assertIn("区切りの印（--rest）も無い", out)
        self.assertEqual((seen, self.stopped), ([], []))

    def test_if_changed_moves_early_at_the_break_when_the_account_nears_its_limit(self):
        # 起動の設定は同じでも、今のアカウントの枠が早めに移す目安（既定 90%）に達し、すぐ戻らなければ、空いているアカウントへ移す
        # （上限に当たってから移ると、ターンの途中で切られて作業が消える。受付 215886）
        self.changed_world(role.launch_key({"model": "opus"}))
        provision.mark(self.place, self.src, {"account": "a1"}, self.g)
        far = 10 * 3600
        self.ports.limits_seq = [{"a1": {"five_hour": {"used_percentage": 92, "resets_at": far}, "seven_day": {"used_percentage": 50}},
                                  "a2": {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 40}}}]
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
        self.assertEqual(rc, 0, out)
        (got,) = seen
        self.assertEqual(got["ns"].only_account, "a2")
        self.assertIn("使用上限か使える時間帯の終わりに当たる前の区切りで", got["brief"])
        (moved,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual((moved["from"], moved["to"], moved["why"], moved["status"]), ("a1", "a2", move.EARLY, "done"))
        self.assertIn("5 時間の枠 92%", moved["detail"])

    def test_an_early_move_that_cannot_start_is_not_tried_again_on_the_same_account(self):
        # 起動できずに前の会話へ戻したら、同じ先へは区切りのたびに止めて戻すのを繰り返さない
        self.changed_world(role.launch_key({"model": "opus"}))
        provision.mark(self.place, self.src, {"account": "a1"}, self.g)
        hot = {"five_hour": {"used_percentage": 92, "resets_at": 10 * 3600}, "seven_day": {"used_percentage": 50}}
        cool = {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 40}}
        self.ports.limits_seq = [{"a1": hot, "a2": cool}, {"a1": hot, "a2": cool}]
        seen, task = self.fake_task(rc=1)
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
            self.assertEqual(rc, 1, out)
            self.assertEqual(self.g.worktree_attrs(self.place)[wake.MOVE_KEPT], "a2")
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
        self.assertEqual(rc, 0, out)
        self.assertIn("移さない", out)
        self.assertEqual(len(seen), 1)

    def test_an_early_move_that_cannot_start_keeps_the_accounts_it_failed_on_before(self):
        # 起動できなかった先は、前に起動できなかった先に足していく（1 つだけ覚えると、2 つの先を交互に選び直し、区切りのたびに
        # 止めて戻すのを繰り返す。2026-10-29、works-factory の変更のレビューで main → p1・main → p2 を約 25 秒おきに 30 回ほど）
        self.changed_world(role.launch_key({"model": "opus"}))
        provision.mark(self.place, self.src, {"account": "a1", wake.MOVE_KEPT: "a3"}, self.g)
        hot = {"five_hour": {"used_percentage": 92, "resets_at": 10 * 3600}, "seven_day": {"used_percentage": 50}}
        cool = {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 40}}
        self.ports.limits_seq = [{"a1": hot, "a2": cool}]
        seen, task = self.fake_task(rc=1)
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
        self.assertEqual(rc, 1, out)
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.MOVE_KEPT], "a2,a3")

    def test_a_department_off_any_branch_is_not_moved(self):
        # 作業場がブランチに居ない部署（detached HEAD）は、--task と同じ道で起動し直せない。前の会話を止めずに断る
        # （止めてから断ると、attach で戻した会話の始まりの待ち受けがまた移そうとし、繰り返す。2026-10-29、works-factory の変更のレビュー）
        self.changed_world(role.launch_key({"model": "opus"}))
        provision.mark(self.place, self.src, {"account": "a1"}, self.g)
        self.g.heads[os.path.realpath(self.place)] = None
        hot = {"five_hour": {"used_percentage": 92, "resets_at": 10 * 3600}, "seven_day": {"used_percentage": 50}}
        cool = {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 40}}
        full = {"five_hour": {"used_percentage": 100, "resets_at": 10 * 3600}, "seven_day": {"used_percentage": 50}}
        self.ports.limits_seq = [{"a1": hot, "a2": cool}, {"a1": full, "a2": cool}, {"a1": full, "a2": cool}]   # --if-changed は控えを読む前に断る
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
            self.assertEqual(rc, 0, out)
            self.assertIn(move.UNBRANCHED, out)
            rc, out = self.main(self.src, "--move", "調べ", "--account", "a2")
            self.assertEqual(rc, 2, out)
            self.assertIn(move.UNBRANCHED, out)
            rc, out = self.main(self.src, "--move", "調べ", "--if-limited", "--dry-run")
            self.assertEqual(rc, 0, out)
            self.assertIn(f"待つ: {move.UNBRANCHED}", out)   # 使用上限で止まったら、移さずに待つ（使えるようになれば続きの 1 行を打つ）
            rc, out = self.main(self.src, "--move", "調べ", "--if-limited", "--account", "a2")
            self.assertEqual(rc, 2, out)   # 名指しは --if-limited でも断る（前の会話を止めない）
            self.assertIn(move.UNBRANCHED, out)
        self.assertEqual((seen, self.stopped), ([], []))
        self.assertEqual([r for r in deliver.records(self.inbox) if r.get("kind") == "moved"], [])

    def test_if_changed_does_not_move_early_without_a_roomy_account_or_when_the_window_resets_soon(self):
        # 移る先が目安に届く・達した枠がすぐ戻るときは移さず、訳を台帳に status skipped で残す
        self.changed_world(role.launch_key({"model": "opus"}))
        provision.mark(self.place, self.src, {"account": "a1"}, self.g)
        hot = {"five_hour": {"used_percentage": 92, "resets_at": 10 * 3600}, "seven_day": {"used_percentage": 50}}
        soon = {"five_hour": {"used_percentage": 92, "resets_at": 1800}, "seven_day": {"used_percentage": 50}}
        cool = {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 40}}
        self.ports.limits_seq = [{"a1": hot, "a2": {"five_hour": {"used_percentage": 91}, "seven_day": {"used_percentage": 1}}},
                                 {"a1": soon, "a2": cool}]
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
            self.assertEqual(rc, 0, out)
            self.assertIn("ほかのアカウントが無いので移さない", out)
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
            self.assertEqual(rc, 0, out)
            self.assertIn("1 時間以内に戻るので移さない", out)
        self.assertEqual((seen, self.stopped), ([], []))
        rows = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual([(r["status"], r["to"], r["why"]) for r in rows], [("skipped", None, move.EARLY)] * 2)

    def test_a_move_stopped_mid_turn_marks_the_account_and_the_break_moves_there(self):
        # 手で打った --move がターンの途中で止まったら（2026-10-19 に p3 の 5 部署）、移す先を印し、区切りの --if-changed がそこへ移す
        self.changed_world(role.launch_key({"model": "opus"}))
        provision.mark(self.place, self.src, {"account": "a1"}, self.g)
        h = self.ports.term
        h.agent = lambda pane: {"agent": "claude", "agent_status": "working"}
        rc, out = self.main(self.src, "--move", "調べ", "--account", "a2")
        self.assertEqual(rc, move.NOT_NOW, out)
        self.assertIn("で移すよう印した", out)
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.MOVE_TO], "a2")
        h.agent = lambda pane: {"agent": "claude", "agent_status": "idle"}
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")   # 使用率は分からなくても、名指しで移す
        self.assertEqual(rc, 0, out)
        (got,) = seen
        self.assertEqual(got["ns"].only_account, "a2")
        self.assertNotIn(wake.MOVE_TO, got["attrs"])
        moved = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual([(r["to"], r["why"], r["status"]) for r in moved],
                         [("a2", "持ち主か窓口が移した", "failed"), ("a2", move.EARLY, "done")])

    def test_a_same_account_move_stopped_mid_turn_is_kept_and_the_break_starts_again_on_it(self):
        # 部署が自分の会話から同じアカウントのまま起動し直そうとして、ターンの途中で止まった（2026-10-20、受付 c149fa）。印を残し、
        # 起動の設定が同じでも、次の頼みを渡す前の --if-changed が同じアカウントのまま起動し直す
        opus = role.launch_key({"model": "opus"})
        self.changed_world(opus)
        provision.mark(self.place, self.src, {"account": "a1"}, self.g)
        h = self.ports.term
        h.agent = lambda pane: {"agent": "claude", "agent_status": "working"}
        rc, out = self.main(self.place, "--move", "調べ", "--account", "a1")
        self.assertEqual(rc, move.NOT_NOW, out)
        self.assertIn("起動し直すよう印した", out)
        self.assertEqual(self.g.worktree_attrs(self.place)[wake.MOVE_TO], "a1")
        h.agent = lambda pane: {"agent": "claude", "agent_status": "idle"}
        rc, out = self.main(self.src, "--move", "調べ", "--if-changed", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn(move.SAME, out)
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
        self.assertEqual(rc, 0, out)
        (got,) = seen
        self.assertEqual(got["ns"].only_account, "a1")
        self.assertIn("同じアカウント a1 のまま", got["brief"])
        self.assertNotIn(wake.MOVE_TO, got["attrs"])
        moved = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual([(r["to"], r["why"], r["status"]) for r in moved], [("a1", move.SAME, "failed"), ("a1", move.SAME, "done")])
        # 印が無く、起動の設定も同じなら起動し直さない
        provision.mark(self.place, self.src, {wake.MOVE_TO: None, wake.LAUNCHED: opus}, self.g)
        rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
        self.assertEqual(rc, 0, out)
        self.assertIn("起動し直さない", out)
        # 名指した今のアカウントが上限に達していれば、ほかへ移さず、印を外す（区切りのたびに試し直さない）
        full = {"five_hour": {"used_percentage": 100, "resets_at": 1800}, "seven_day": {"used_percentage": 50}}
        cool = {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 40}}
        self.ports.limits_seq = [{"a1": full, "a2": cool}]
        provision.mark(self.place, self.src, {wake.MOVE_TO: "a1"}, self.g)
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
        self.assertEqual(rc, 0, out)
        self.assertIn("同じアカウントのまま起動し直さない", out)
        self.assertEqual(seen, [])
        self.assertNotIn(wake.MOVE_TO, self.g.worktree_attrs(self.place))

    def test_the_desk_exits_and_starts_again_named_in_the_same_pane(self):
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s-desk", "account": "a1"}, self.g)
        for p in self.ports.term._panes:
            if p["pane_id"] == self.desk:
                p["agent_session"] = "s-desk"
        self.ports.term.talking.add(self.desk)
        rc, out = self.main(self.src, "--move", "窓口", "--account", "a2")
        self.assertEqual(rc, 0, out)
        writes = [w for w in self.ports.term.writes if w[1] == self.desk and w[0] in ("prompt", "run")]
        self.assertEqual(writes[0][:3], ("prompt", self.desk, "/exit"))
        self.assertEqual(writes[1][0], "run")
        self.assertRegex(writes[1][2], rf"^claude-a2 --name {q('窓口')} {Q}.*--move.*--desk 窓口")

    def test_the_desk_that_does_not_start_again_resumes_its_former_talk(self):
        # 新しい会話が立たなければ、前の会話を同じペインに --resume で戻し、訳を台帳に残す（窓口を消したままにしない）
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s-desk", "account": "a1"}, self.g)
        for p in self.ports.term._panes:
            if p["pane_id"] == self.desk:
                p["agent_session"] = "s-desk"
        self.ports.term.talking.add(self.desk)
        failed = {"pane": self.desk, "status": "launch_failed", "detail": "起動できない"}
        with mock.patch.object(move.launch, "start_named", lambda *a, **k: failed):
            rc, out = self.main(self.src, "--move", "窓口", "--account", "a2")
        self.assertEqual(rc, 1, out)
        runs = [w[2] for w in self.ports.term.writes if w[1] == self.desk and w[0] == "run"]
        self.assertEqual(runs, ["claude-a1 --resume s-desk"])   # 前のアカウントで前の会話へ
        (moved,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual(moved["status"], "failed")
        self.assertIn("前の会話を --resume で戻した", moved["detail"])
        self.assertIn(wake.RESTART_KEPT, self.g.worktree_attrs(self.src))   # 同じ値では起動し直しと戻しを繰り返さない

    def test_the_desk_starts_again_with_the_settings_of_its_role(self):
        # 窓口の役の [roles.settings] は、--task の部署と同じく --settings で渡す（部署だけの鍵 worktree.bgIsolation は重ねない）
        test_deliver.Flow.shape(self, '[[roles]]\nname = "窓口"\n[roles.settings]\nenabledPlugins = { "works@m" = false }\n')
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s-desk", "account": "a1"}, self.g)
        for p in self.ports.term._panes:
            if p["pane_id"] == self.desk:
                p["agent_session"] = "s-desk"
        self.ports.term.talking.add(self.desk)
        rc, out = self.main(self.src, "--move", "窓口", "--account", "a2")
        self.assertEqual(rc, 0, out)
        (run,) = [w for w in self.ports.term.writes if w[1] == self.desk and w[0] == "run"]
        path = os.path.join(self.g.git_dir(self.src), "company-settings.json")
        self.assertRegex(run[2], rf"^claude-a2 --name {q('窓口')} --settings {q(os.path.join(self.g.git_dir(self.src), 'company-settings.json'))} {Q}.*--desk 窓口")
        self.assertEqual(json.loads(pathlib.Path(path).read_text(encoding="utf-8")), {"enabledPlugins": {"works@m": False}})


    def desk_world(self, **more):
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s-desk", "account": "a1", **more}, self.g)
        for p in self.ports.term._panes:
            if p["pane_id"] == self.desk:
                p["agent_session"] = "s-desk"
        self.ports.term.talking.add(self.desk)

    def test_if_changed_restarts_the_desk_at_its_rest_with_the_settings_model_and_effort_of_its_role(self):
        # 窓口の役の起動の設定を替えたら、区切り（--rest）のターンの終わりに、同じアカウントで起動し直す（持ち主の手で起動し直さない）
        test_deliver.Flow.shape(self, '[[roles]]\nname = "窓口"\nmodel = "opus"\neffort = "high"\n'
                                      '[roles.settings]\nenabledPlugins = { "works@m" = false }\n')
        self.desk_world(**{wake.RESTARTING: "s-desk"})
        rc, out = self.main(self.src, "--move", "窓口", "--if-changed")
        self.assertEqual(rc, 2, out)   # 区切りの印が無い間は起動し直さない（持ち主と話している途中の会話を切らない）
        self.assertIn("区切りの印（--rest）も無い", out)
        self.assertFalse([w for w in self.ports.term.writes if w[1] == self.desk])
        provision.mark(self.src, self.src, {wake.REST: "s-desk"}, self.g)
        rc, out = self.main(self.src, "--move", "窓口", "--if-changed")
        self.assertEqual(rc, 0, out)
        writes = [w for w in self.ports.term.writes if w[1] == self.desk and w[0] in ("prompt", "run")]
        self.assertEqual(writes[0][:3], ("prompt", self.desk, "/exit"))
        self.assertRegex(writes[1][2], rf"^claude-a1 --name {q('窓口')} --model {q('opus')} --effort {q('high')} --settings {q(os.path.join(self.g.git_dir(self.src), 'company-settings.json'))} {Q}.*--desk 窓口")
        attrs = self.g.worktree_attrs(self.src)
        shape = role.load(os.path.join(self.src, ".claude", "company.toml"),
                          pathlib.Path(self.src, ".claude", "company.toml").read_text(encoding="utf-8"))
        self.assertEqual(attrs.get("launched"), role.launch_key(shape["roles"]["窓口"]))
        self.assertEqual(attrs.get(wake.LAUNCHING), "1")   # 起きた会話の --desk が外す
        for k in (wake.REST, wake.RESTARTING):
            self.assertNotIn(k, attrs)
        # 起動した値と同じなら、区切りでも起動し直さない（待ち受けは /clear で空にする）
        provision.mark(self.src, self.src, {wake.REST: "s-desk"}, self.g)
        rc, out = self.main(self.src, "--move", "窓口", "--if-changed")
        self.assertEqual(rc, 0, out)
        self.assertIn("起動し直さない", out)

    def test_the_desk_is_not_exited_in_the_middle_of_its_turn_or_over_typed_text(self):
        # ターンの途中に打った /exit はターンの終わりまで待ちの列に回り、起動し直さずに止まった後で効いて、窓口が消えたままになりうる
        self.desk_world()
        h = self.ports.term
        h.agent = lambda pane: {"agent": "claude", "agent_status": "working"}
        rc, out = self.main(self.src, "--move", "窓口", "--account", "a2")
        self.assertEqual(rc, move.NOT_NOW, out)   # 訳がすぐ替わる（待ち受けは起動し直さなかった値を残さない）
        self.assertIn("ターンの途中", out)
        h.agent = lambda pane: {"agent": "claude", "agent_status": "idle"}
        h.screen = "─" * 20 + "\n❯ 打ちかけ\n" + "─" * 20
        rc, out = self.main(self.src, "--move", "窓口", "--account", "a2")
        self.assertEqual(rc, move.NOT_NOW, out)
        self.assertIn("入力フィールドに字（「打ちかけ」）が在る", out)
        self.assertFalse([w for w in h.writes if w[1] == self.desk and w[0] in ("prompt", "run")])
        # 窓口でも、会話の外（部署の作業場）から打った --move なら、訳を窓口の会話に知らせで渡す
        wake._replace(wake.pos_path(self.inbox, self.g.git_dir(self.src)), "0")
        rc, out = self.main(self.place, "--move", "窓口", "--account", "a2")
        self.assertEqual(rc, move.NOT_NOW, out)
        (told,) = [r for r in deliver.records(self.inbox) if r.get("kind") == wake.NOTE]
        self.assertTrue(told["to"].endswith("/窓口"), told)
        self.assertIn("アカウント a2 へ移して", told["text"])

    def test_a_clear_the_watcher_left_unsent_does_not_hold_the_move(self):
        # 2026-10-20 に my_notes の調べもので、待ち受けが打って送られずに残った /clear を持ち主の打ちかけと見て、--move が起動し直さなかった。
        # 部署は会話を止めれば字も消える。窓口は /exit をその後ろに続けて打たないよう、字を消してから打つ。人の字は今までどおり止める
        provision.mark(self.place, self.src, {"lifecycle": "persistent", "job": "d", "account": "a1", "session": "s1",
                                              wake.CLEAR_TYPED: "s0"}, self.g)
        h = self.ports.term
        h.screen = "─" * 20 + "\n❯ /clear [name]\n" + "─" * 20
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--account", "a1")
            self.assertEqual(rc, move.NOT_NOW, out)   # 前の会話で打った物は、人の字と同じに見る
            provision.mark(self.place, self.src, {wake.CLEAR_TYPED: "s1"}, self.g)
            rc, out = self.main(self.src, "--move", "調べ", "--account", "a1")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.stopped, [("c1", "d")])
        self.desk_world(**{wake.CLEAR_TYPED: "s-desk"})
        rc, out = self.main(self.src, "--move", "窓口", "--account", "a2")   # Ctrl+U で消えないと、/exit を続けて打たない
        self.assertEqual(rc, move.NOT_NOW, out)
        self.assertIn("入力フィールドに字（「/clear [name]」）が在る", out)
        writes = [w[:3] for w in h.writes if w[1] == self.desk and w[0] in ("prompt", "send_keys")]
        self.assertEqual(writes, [("send_keys", self.desk, "ctrl+u")])
        keys = h.send_keys

        def wipe(pane, *k):
            keys(pane, *k)
            if k == ("ctrl+u",):
                h.screen = "─" * 20 + "\n❯ \n" + "─" * 20
        h.send_keys = wipe
        self.main(self.src, "--move", "窓口", "--account", "a2")
        writes = [w[:3] for w in h.writes if w[1] == self.desk and w[0] in ("prompt", "send_keys")]
        self.assertEqual(writes[1:3], [("send_keys", self.desk, "ctrl+u"), ("prompt", self.desk, deliver.EXIT)])

    def test_the_desk_is_exited_over_a_faint_prompt_suggestion(self):
        # 入力フィールドの薄字（SGR 2）は Claude Code の次の文の候補で、打てば消える。2026-10-18 に my_notes の段取りで、候補「消していいよ」を
        # 打ちかけと見て、区切りの起動し直しを 1 時間打たなかった
        self.desk_world()
        h = self.ports.term
        h.screen = "\x1b[38;2;136;136;136m" + "─" * 20 + " 窓口 ─\x1b[0m\n❯\xa0\x1b[0m\x1b[2m消していいよ\x1b[0m\n" + "─" * 20
        self.assertEqual(claudex.typed(h.screen), "")
        self.assertEqual(claudex.typed(h.screen.replace("\x1b[2m", "")), "消していいよ")   # 人が打った字は薄字でない
        self.main(self.src, "--move", "窓口", "--account", "a2")
        self.assertIn(("prompt", self.desk, deliver.EXIT), [w[:3] for w in h.writes])

class LimitHook(unittest.TestCase):
    Flow = test_deliver.Flow
    del Flow

    def setUp(self):
        test_deliver.Flow.setUp(self)

    def test_only_resident_departments_and_the_desk_move_on_a_rate_limit(self):
        base = {"cwd": self.place, "session_id": "s-dept", "error": "rate_limit"}
        self.assertIsNone(limit_hook.plan(base))   # 頼みを受けていない tmp の部署
        provision.mark(self.place, self.src, {"ask": "q1"}, self.g)   # 頼みの途中の tmp の部署（on-demand の受け持ち）は移す
        self.assertEqual(limit_hook.plan(base)[0][2:4], ["--move", "調べ"])
        provision.mark(self.place, self.src, {"ask": None, "lifecycle": "persistent"}, self.g)
        argv, cwd, out = limit_hook.plan(base)
        self.assertEqual(argv[2:5], ["--move", "調べ", "--if-limited"])
        self.assertEqual(cwd, self.place)
        self.assertIsNone(limit_hook.plan({**base, "error": "overloaded"}))
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s-desk"}, self.g)
        self.assertIsNone(limit_hook.plan({"cwd": self.src, "session_id": "s-other", "error": "rate_limit"}))
        self.assertEqual(limit_hook.plan({"cwd": self.src, "session_id": "s-desk", "error": "rate_limit"})[0][3], "窓口")

    def test_other_errors_move_only_when_the_account_is_outside_its_hours(self):
        provision.mark(self.place, self.src, {"lifecycle": "persistent"}, self.g)
        base = {"cwd": self.place, "session_id": "s-dept", "error": "unknown"}
        self.assertIsNone(limit_hook.plan(base, closed_of=lambda attrs: False))
        self.assertEqual(limit_hook.plan(base, closed_of=lambda attrs: True)[0][2:5], ["--move", "調べ", "--if-limited"])
        self.assertIsNone(limit_hook.plan({**base, "error": None}, closed_of=lambda attrs: True))
        cfg = pathlib.Path(self.src) / "hours.toml"
        cfg.write_text('accounts = [{ name = "cheap", command = "c", limits = false, hours = "08:00-16:00 UTC" }]\n', encoding="utf-8")
        attrs = {"account": "cheap", "config": str(cfg)}
        self.assertTrue(limit_hook.closed(attrs, now=lambda: 1792454400))    # UTC 00:00（枠の外）
        self.assertFalse(limit_hook.closed(attrs, now=lambda: 1792497600))   # UTC 12:00（枠の中）
        self.assertFalse(limit_hook.closed({**attrs, "account": "p1"}, now=lambda: 1792454400))

    def test_main_spawns_once_within_the_quiet_time(self):
        provision.mark(self.place, self.src, {"lifecycle": "persistent"}, self.g)
        spawned = []
        payload = json.dumps({"cwd": self.place, "session_id": "s-dept", "error": "rate_limit"})
        for _ in range(2):
            limit_hook.main(io.StringIO(payload), spawn=lambda argv, **kw: spawned.append(argv), now=lambda: time.time())
        self.assertEqual(len(spawned), 1)
        self.assertTrue(os.listdir(os.path.join(self.inbox, limit_hook.MOVES)))


if __name__ == "__main__":
    unittest.main()
