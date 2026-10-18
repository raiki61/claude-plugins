"""終わりの印（--done。orders.finish_here）と、都度の部署を止めて畳む --retire（retire.py）と、納品し終えた部署が番を終えて残る訳
（orders.leftover・stop_after）。git は一時のフォルダの本物、herdr・claude は偽物で回す。"""

import io
import json
import os
import tempfile
import unittest

from . import test_deliver
import gitx
import orders
import retire
from nodes import deliver, provision, wake

GIT_ID = ["-c", "user.name=o", "-c", "user.email=o@o"]


class Retire(unittest.TestCase):
    """場の作りは test_deliver.Flow の物を借りる（継ぐと、その試験が二度走る）。部署「調べ」は origin/main から切った都度の部署。"""

    Flow = test_deliver.Flow
    main, shape = Flow.main, Flow.shape
    del Flow

    def setUp(self):
        test_deliver.Flow.setUp(self)
        self.state = "working"
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"id": "d", "sessionId": "s-dept", "name": "調べ", "cwd": self.place, "kind": "background", "state": self.state}]
        self.stopped = []

        def stop(cdir, job):
            self.stopped.append(job)
            self.state = "stopped"
            return True, ""
        self.ports.stop_session = stop
        h = self.ports.herdr
        h.front[self.window] = ["claude-a1", "attach", "d"]
        real_keys = h.send_keys

        def keys(pane, *k):   # attach の画面は Ctrl+Z と Esc でシェルに戻る
            real_keys(pane, *k)
            if k == ("escape",):
                h.talking.discard(pane)
                h.front.pop(pane, None)
        h.send_keys = keys
        self.removed = []
        real_rm, real_tmp = retire.claudex.remove_session, retire.claudex.job_tmp
        retire.claudex.remove_session = lambda cdir, sid, **kw: self.removed.append(sid) or (True, "removed")
        retire.claudex.job_tmp = lambda cdir, sid, env=None: "/nowhere"
        self.addCleanup(setattr, retire.claudex, "remove_session", real_rm)
        self.addCleanup(setattr, retire.claudex, "job_tmp", real_tmp)

    def retired(self):
        return [r for r in deliver.records(self.inbox) if r.get("kind") == "retired"]

    def test_done_refuses_until_the_department_has_delivered_and_landed(self):
        provision.mark(self.place, self.src, {"ask": "q1"}, gitx)
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 2, out)
        self.assertIn("納品していない頼み", out)
        provision.mark(self.place, self.src, {"delivered": "q1"}, gitx)
        open(os.path.join(self.place, "note.txt"), "w").close()
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 2, out)
        self.assertIn("未コミットの変更", out)
        test_deliver.git("-C", self.place, "add", "note.txt")
        test_deliver.git("-C", self.place, *GIT_ID, "commit", "-q", "-m", "note")
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 2, out)
        self.assertIn("手元にしか無い commit", out)
        test_deliver.git("-C", self.place, "push", "-q", "origin", "HEAD:refs/heads/dept/a")
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 2, out)
        self.assertIn("本流", out)
        self.assertNotIn(wake.FINISHED, gitx.worktree_attrs(self.place))
        test_deliver.git("-C", self.place, "push", "-q", "origin", "HEAD:main")
        test_deliver.git("-C", self.place, "fetch", "-q", "origin")
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place)[wake.FINISHED], "s-dept")

    def test_done_refuses_while_an_ask_this_department_made_has_no_answer(self):
        # 業務改革が社長室に問いを回して答えを待つ間に畳むと、答えを受ける会話が居ない（813bb8 の見直しの指摘）
        deliver.log(self.inbox, {"kind": "ask", "id": "c1", "status": "queued", "at": 1,
                                 "from": {"name": "調べ", "place": self.place}, "to": {"company": "co", "name": "社長室"}})
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 2, out)
        self.assertIn("返事の来ていない頼みが在る（受付 c1）", out)
        deliver.log(self.inbox, {"kind": "deliver", "id": "d1", "ask": "c1", "status": "sent"})
        self.assertEqual(self.main(self.place, "--done")[0], 0)

    def test_done_passes_a_department_without_commits_and_refuses_desks_and_residents(self):
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 0, out)   # commit の無い部署は本流に入っているとみなす
        self.assertEqual(self.main(self.src, "--done")[0], 2)   # 部署でない所
        provision.mark(self.src, self.src, {"role": "窓口", "name": "desk"}, gitx)
        rc, out = self.main(self.src, "--done")
        self.assertEqual(rc, 2, out)
        self.assertIn("窓口は畳まない", out)
        provision.mark(self.place, self.src, {"residency": "resident", wake.FINISHED: None}, gitx)
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 2, out)
        self.assertIn("常設の部署は畳まない", out)

    def test_retire_stops_the_talk_then_removes_the_room_like_clean(self):
        rc, out = self.main(self.src, "--retire", "調べ")
        self.assertEqual(rc, 0, out)
        self.assertIn("を畳んだ", out)
        self.assertEqual(self.stopped, ["d"])   # 一覧の短い id で止める
        self.assertIn(("send_keys", self.window, "ctrl+z"), self.ports.herdr.writes)   # 止める前に attach の画面をシェルに戻す
        self.assertEqual(self.removed, ["d"])
        self.assertFalse(os.path.exists(self.place))
        self.assertEqual([r["status"] for r in self.retired()], ["done"])

    def test_retire_stops_nothing_while_work_would_be_lost_and_says_why_in_clean(self):
        provision.mark(self.place, self.src, {"ask": "q1", "delivered": "q1"}, gitx)
        test_deliver.git("-C", self.place, *GIT_ID, "commit", "-q", "--allow-empty", "-m", "x")
        rc, out = self.main(self.src, "--retire", "調べ")
        self.assertEqual(rc, 2, out)
        self.assertIn("手元にしか無い commit", out)
        self.assertEqual((self.stopped, self.removed), ([], []))
        self.assertTrue(os.path.exists(self.place))
        self.assertEqual([r["status"] for r in self.retired()], ["kept"])
        self.assertIn("手元にしか無い commit", gitx.worktree_attrs(self.place)[wake.RETIRE_KEPT])

    def test_retire_refuses_an_open_ask(self):
        provision.mark(self.place, self.src, {"ask": "q1"}, gitx)
        rc, out = self.main(self.src, "--retire", "調べ")
        self.assertEqual(rc, 2, out)
        self.assertIn("納品していない頼み", out)
        self.assertEqual(self.stopped, [])

    def test_done_and_retire_refuse_while_an_ask_waits_in_the_queue(self):
        wake.enqueue(self.inbox, gitx.git_dir(self.place), {"id": "q2", "line": "頼みです（受付 q2）", "marks": {"ask": "q2"}})
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 2, out)
        self.assertIn("順番待ちに頼みが在る", out)
        rc, out = self.main(self.src, "--retire", "調べ")
        self.assertEqual(rc, 2, out)
        self.assertIn("順番待ちに頼みが在る", out)
        self.assertEqual(self.stopped, [])

    def test_done_clears_the_reason_a_former_retire_left(self):
        provision.mark(self.place, self.src, {wake.RETIRE_KEPT: "前の訳"}, gitx)
        self.assertEqual(self.main(self.place, "--done")[0], 0)
        self.assertNotIn(wake.RETIRE_KEPT, gitx.worktree_attrs(self.place))

    def test_done_refuses_a_department_without_its_talk_id(self):
        provision.mark(self.place, self.src, {"session": None}, gitx)
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 2, out)
        self.assertIn("会話の id", out)

    def test_a_talk_already_stopped_is_not_stopped_again(self):
        self.state = "stopped"
        rc, out = self.main(self.src, "--retire", "調べ")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.stopped, [])
        self.assertFalse(os.path.exists(self.place))

    def test_a_talk_still_running_after_stop_is_left(self):
        self.ports.stop_session = lambda cdir, job: (True, "")   # 止めたと答えるが、一覧では動いたまま
        rc, out = self.main(self.src, "--retire", "調べ")
        self.assertEqual(rc, 1, out)
        self.assertIn("会話を止めたが、会話がまだ動いている", out)
        self.assertTrue(os.path.exists(self.place))
        self.assertEqual(self.removed, [])

    def test_a_talk_that_does_not_stop_is_left_and_clean_lists_the_reason(self):
        self.ports.stop_session = lambda cdir, job: (False, "No job matching")
        rc, out = self.main(self.src, "--retire", "調べ")
        self.assertEqual(rc, 1, out)
        self.assertTrue(os.path.exists(self.place))
        rc, out = self.main(self.src, "--clean")
        self.assertIn("残す（会話がまだ動いている。終わりの印で畳もうとして残った: 会話 d を止められない（No job matching））", out)

    def test_clean_points_to_retire_for_a_delivered_talk_without_the_mark(self):
        provision.mark(self.place, self.src, {"ask": "q1", "delivered": "q1"}, gitx)
        rc, out = self.main(self.src, "--clean")
        self.assertIn("残す（会話がまだ動いている。頼みは納品済みで、終わりの印（--done）が無い。止めて畳むなら --retire 調べ）", out)

    LAND = '[land]\nmode = "ff-after-ci"\ncheck = "true"\n'

    def after(self, count=0):
        return orders.stop_after({"session_id": "s-dept"}, self.place, gitx.worktree_attrs(self.place), count, os.path.dirname(self.cfg))

    def test_a_delivered_but_unlanded_department_is_sent_back_and_clean_tells_it_from_waiting(self):
        # 2026-10-17 に my_notes で、--land が止まった部署が残った疑問に「持ち手: 段取り」と書いただけで 1 日残った
        self.shape(self.LAND)
        provision.mark(self.place, self.src, {"ask": "q1", "delivered": "q1"}, gitx)
        test_deliver.git("-C", self.place, *GIT_ID, "commit", "-q", "--allow-empty", "-m", "x")
        test_deliver.git("-C", self.place, "push", "-q", "origin", "HEAD:refs/heads/dept/a")
        got = self.after()
        self.assertIn("枝が本流（origin/main の手元の控え）に入っていない", got)
        self.assertIn("--land '調べ'", got)
        self.assertIn("--ask src", got)   # 打てなければ窓口（会社の名前）に頼む
        rc, out = self.main(self.src, "--clean")
        self.assertIn("頼みは納品済みだが、枝が本流（origin/main）に入っていない（入れ損ねか、入れる手を待っている。消すと成果を失う）。"
                      "入れるなら --land 調べ", out)
        # 入れてほしいと頼んだら、返事を待つ間は差し戻さず、--clean は返事待ちと出す
        deliver.log(self.inbox, {"kind": "ask", "id": "c1", "status": "sent", "at": 1,
                                 "from": {"name": "調べ", "place": self.place}, "to": {"company": "src", "name": "desk"}})
        self.assertIsNone(self.after())
        rc, out = self.main(self.src, "--clean")
        self.assertIn("頼みは納品済みで、この部署が頼んだ返事を待っている（受付 c1）", out)

    def test_a_resident_department_is_sent_back_only_for_an_unlanded_branch(self):
        self.shape(self.LAND)
        provision.mark(self.place, self.src, {"ask": "q1", "delivered": "q1", "residency": "resident"}, gitx)
        self.assertIsNone(self.after())
        test_deliver.git("-C", self.place, *GIT_ID, "commit", "-q", "--allow-empty", "-m", "x")
        self.assertIn("枝が本流（origin/main の手元の控え）に入っていない", self.after())

    def test_an_unlanded_branch_is_not_sent_back_where_the_company_lands_by_pr(self):
        self.shape('[land]\nmode = "pr"\n')
        provision.mark(self.place, self.src, {"ask": "q1", "delivered": "q1"}, gitx)
        test_deliver.git("-C", self.place, *GIT_ID, "commit", "-q", "--allow-empty", "-m", "x")
        self.assertIsNone(self.after())
        self.assertEqual(orders.leftover(self.place, gitx.worktree_attrs(self.place))[0], "unlanded")

    def test_a_landed_one_time_department_is_sent_back_to_mark_done(self):
        self.shape(self.LAND)
        provision.mark(self.place, self.src, {"ask": "q1"}, gitx)
        self.assertIsNone(self.after())   # 納品していない頼みは deliver.stop_verdict が差し戻す
        provision.mark(self.place, self.src, {"delivered": "q1"}, gitx)
        self.assertIn("--done で番を終える", self.after())
        self.assertIsNone(self.after(count=deliver.STOP_LIMIT))
        self.assertIsNone(orders.stop_after({"session_id": "other"}, self.place, gitx.worktree_attrs(self.place), 0,
                                            os.path.dirname(self.cfg)))   # 同じ作業場の別の会話
        wake.enqueue(self.inbox, gitx.git_dir(self.place), {"id": "q2", "line": "頼みです（受付 q2）", "marks": {"ask": "q2"}})
        self.assertIsNone(self.after())   # 順番待ちは待ち受けが渡す
        wake.take(self.inbox, gitx.git_dir(self.place))
        provision.mark(self.place, self.src, {wake.FINISHED: "s-dept"}, gitx)
        self.assertIsNone(self.after())
        provision.mark(self.place, self.src, {wake.FINISHED: None, "residency": "resident"}, gitx)
        self.assertIsNone(self.after())   # 常設の部署は畳まない
        self.assertIsNone(orders.stop_after({"session_id": "s-desk"}, self.src, {"role": "窓口", "name": "desk", "ask": "q1",
                                                                                "delivered": "q1"}, 0, os.path.dirname(self.cfg)))

    def test_the_stop_hook_sends_back_after_delivery_up_to_the_limit(self):
        provision.mark(self.place, self.src, {"ask": "q1", "delivered": "q1"}, gitx)
        payload = json.dumps({"session_id": "s-dept", "cwd": self.place, "background_tasks": []})
        got = []
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(deliver.STOP_LIMIT + 1):
                out = io.StringIO()
                orders.stop_hook(io.StringIO(payload), out, tmp_dir=tmp, h=self.ports.herdr)
                got.append(json.loads(out.getvalue())["reason"] if out.getvalue() else None)
        self.assertTrue(all("--done" in x for x in got[:-1]), got)
        self.assertIsNone(got[-1])

    def test_the_stop_hook_reads_the_land_mode_and_sends_back_an_unlanded_branch(self):
        self.shape(self.LAND)
        provision.mark(self.place, self.src, {"ask": "q1", "delivered": "q1", "config": self.cfg}, gitx)
        test_deliver.git("-C", self.place, *GIT_ID, "commit", "-q", "--allow-empty", "-m", "x")
        payload = json.dumps({"session_id": "s-dept", "cwd": self.place, "background_tasks": []})
        with tempfile.TemporaryDirectory() as tmp:
            out = io.StringIO()
            orders.stop_hook(io.StringIO(payload), out, tmp_dir=tmp, h=self.ports.herdr)
        self.assertIn("--land '調べ'", json.loads(out.getvalue())["reason"])


if __name__ == "__main__":
    unittest.main()
