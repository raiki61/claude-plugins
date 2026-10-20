"""終わりの印（--done。orders.finish_here）と、エフェメラルの部署を止めて畳む --retire（retire.py）と、納品し終えた部署がターンを終えて残る訳
（orders.leftover・stop_after）。git は一時のフォルダの本物、herdr・claude は偽物で回す。"""

import io
import json
import os
import shutil
import tempfile
import unittest

from . import test_deliver
import ghx
import gitx
import orders
import retire
from nodes import deliver, provision, wake

GIT_ID = ["-c", "user.name=o", "-c", "user.email=o@o"]


class Retire(unittest.TestCase):
    """場の作りは test_deliver.Flow の物を借りる（継ぐと、その試験が二度走る）。部署「調べ」は origin/main から切ったエフェメラルの部署。"""

    Flow = test_deliver.Flow
    main, shape = Flow.main, Flow.shape
    del Flow

    def setUp(self):
        test_deliver.Flow.setUp(self)
        self.state, self.pid = "working", 4242   # 動く処理の有る会話は、一覧に処理の番号（pid）が有る
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"id": "d", "sessionId": "s-dept", "name": "調べ", "cwd": self.place, "kind": "background", "state": self.state,
             **({"pid": self.pid} if self.pid else {})}]
        self.stopped = []

        def stop(cdir, job):
            self.stopped.append(job)
            self.state = "stopped"
            return True, ""
        self.ports.stop_session = stop
        h = self.ports.term
        h.front[self.window] = ["claude-a1", "attach", "d"]
        real_keys = h.send_keys

        def keys(pane, *k):   # attach の画面は Ctrl+Z と Esc でシェルに戻る
            real_keys(pane, *k)
            if k == ("escape",):
                h.talking.discard(pane)
                h.front.pop(pane, None)
        h.send_keys = keys
        self.removed = []
        real_rm, real_tmp = retire.chat.remove_session, retire.chat.job_tmp
        retire.chat.remove_session = lambda cdir, sid, **kw: self.removed.append(sid) or (True, "removed")
        retire.chat.job_tmp = lambda cdir, sid, env=None: "/nowhere"
        self.addCleanup(setattr, retire.chat, "remove_session", real_rm)
        self.addCleanup(setattr, retire.chat, "job_tmp", real_tmp)

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
        self.assertIn("メインブランチ", out)
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
        self.assertEqual(rc, 0, out)   # commit の無い部署はメインブランチに入っているとみなす
        self.assertEqual(self.main(self.src, "--done")[0], 2)   # 部署でない所
        provision.mark(self.src, self.src, {"role": "窓口", "name": "desk"}, gitx)
        rc, out = self.main(self.src, "--done")
        self.assertEqual(rc, 2, out)
        self.assertIn("窓口は畳まない", out)
        provision.mark(self.place, self.src, {"lifecycle": "persistent", wake.FINISHED: None}, gitx)
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 2, out)
        self.assertIn("永続の部署は畳まない", out)

    def test_retire_stops_the_talk_then_removes_the_room_like_clean(self):
        rc, out = self.main(self.src, "--retire", "調べ")
        self.assertEqual(rc, 0, out)
        self.assertIn("を畳んだ", out)
        self.assertEqual(self.stopped, ["d"])   # 一覧の短い id で止める
        self.assertIn(("send_keys", self.window, "ctrl+z"), self.ports.term.writes)   # 止める前に attach の画面をシェルに戻す
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
        self.ports.env = {}   # Claude Code の外から打った（この会話の id も読めない）
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 2, out)
        self.assertIn("会話の id", out)

    def test_done_fills_a_missing_talk_id_with_its_own(self):
        # 2026-10-20 に、部署を立てた直後に会話のフックと書き込みがぶつかり（config.worktree の鍵）、company.session が書かれなかった
        provision.mark(self.place, self.src, {"session": None, "job": "d"}, gitx)
        # 部署の裏の会話でない会話（短い id が company.job と違う）が部署の場所で打っても、その id は書かない
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-other", "CLAUDE_JOB_DIR": "/c/jobs/x"}
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 2, out)
        self.assertNotIn("session", gitx.worktree_attrs(self.place))
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-dept", "CLAUDE_JOB_DIR": "/c/jobs/d"}
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["session"], attrs[wake.FINISHED]), ("s-dept", "s-dept"))

    def test_retire_finds_the_talk_by_its_short_id_when_the_long_id_is_missing(self):
        provision.mark(self.place, self.src, {"session": None, "job": "d"}, gitx)
        rc, out = self.main(self.src, "--clean")
        self.assertIn("会話がまだ動いている", out)   # 会話が動いている部署は、id が短い物しか無くても畳まない
        rc, out = self.main(self.src, "--retire", "調べ")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.stopped, ["d"])
        self.assertFalse(os.path.exists(self.place))

    def test_a_short_id_left_from_a_former_talk_does_not_hide_a_live_one(self):
        # company.job は前の裏の会話のまま残りうる。部署の場所でほかの会話が動いていれば、動いているとみなす
        self.state = "done"
        provision.mark(self.place, self.src, {"session": None, "job": "d"}, gitx)
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"id": "d", "sessionId": "s-dept", "cwd": self.place, "kind": "background", "state": "done"},
            {"id": "e", "sessionId": "s-new", "cwd": self.place, "kind": "background", "state": "working", "pid": 1}]
        rc, out = self.main(self.src, "--clean")
        self.assertIn("会話がまだ動いている", out)
        # 短い id の会話が一覧に無ければ、止まったと決められないので並べない
        provision.mark(self.place, self.src, {"job": "zz"}, gitx)
        self.ports.list_sessions = lambda cdir, include_done=False: []
        rc, out = self.main(self.src, "--retire", "調べ")
        self.assertEqual(rc, 2, out)
        self.assertTrue(os.path.exists(self.place))

    def test_retire_leaves_a_department_without_any_talk_id(self):
        provision.mark(self.place, self.src, {"session": None, "job": None}, gitx)
        rc, out = self.main(self.src, "--retire", "調べ")
        self.assertEqual(rc, 2, out)
        self.assertIn("company.job も無い", out)
        self.assertTrue(os.path.exists(self.place))

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

    def test_a_record_left_working_without_a_process_is_retired_after_stop(self):
        # 2026-10-19 に works-factory で、予約した繰り返しの仕事を残して終わった会話が、claude stop の後も一覧で working のまま
        # （処理の番号は無い）出続け、--retire が 7 回残した
        self.pid = None
        self.ports.stop_session = lambda cdir, job: self.stopped.append(job) or (True, "stopped d")
        rc, out = self.main(self.src, "--retire", "調べ")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.stopped, ["d"])
        self.assertFalse(os.path.exists(self.place))
        self.assertEqual([r["status"] for r in self.retired()], ["done"])

    def test_a_branch_landed_by_a_squashed_pr_is_done_and_retired(self):
        # 2026-10-19 に works-factory で、squash でマージした PR（#776・#789・#790）のブランチが main の祖先にならず、--done・--retire・
        # --clean が「メインブランチに入っていない」で止まった。マージの後に head のブランチが消え、手元の控えも消えた形でも畳める
        provision.mark(self.place, self.src, {"ask": "q1", "delivered": "q1", "gh-user": "someone"}, gitx)
        test_deliver.git("-C", self.place, *GIT_ID, "commit", "-q", "--allow-empty", "-m", "x")
        test_deliver.git("-C", self.place, "push", "-q", "origin", "HEAD:refs/heads/dept/a")
        test_deliver.git("-C", self.place, "update-ref", "-d", "refs/remotes/origin/dept/a")
        head, asked = gitx.head_sha(self.place), []
        real = gitx.origin_repo, ghx.merged_pr_of, ghx.env_for
        gitx.origin_repo = lambda cwd, runner=None: "o/r"
        ghx.env_for = lambda user, base_env, runner=None: {**base_env, "GH_TOKEN": f"token-of-{user}"}
        ghx.merged_pr_of = lambda repo, sha, base, runner=None, env=None: asked.append((repo, sha, base, env["GH_TOKEN"])) or (
            7 if (repo, sha, base) == ("o/r", head, "main") else None)
        self.addCleanup(lambda: (setattr(gitx, "origin_repo", real[0]), setattr(ghx, "merged_pr_of", real[1]),
                                 setattr(ghx, "env_for", real[2])))
        rc, out = self.main(self.place, "--done")
        self.assertEqual(rc, 0, out)
        self.assertIn(("o/r", head, "main", "token-of-someone"), asked)
        rc, out = self.main(self.src, "--retire", "調べ")
        self.assertEqual(rc, 0, out)
        self.assertFalse(os.path.exists(self.place))

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
        # 2026-10-17 に my_notes で、--land が止まった部署が残った疑問に「担当者: 段取り」と書いただけで 1 日残った
        self.shape(self.LAND)
        provision.mark(self.place, self.src, {"ask": "q1", "delivered": "q1"}, gitx)
        test_deliver.git("-C", self.place, *GIT_ID, "commit", "-q", "--allow-empty", "-m", "x")
        test_deliver.git("-C", self.place, "push", "-q", "origin", "HEAD:refs/heads/dept/a")
        got = self.after()
        self.assertIn("ブランチがメインブランチ（origin/main の手元の控え）に入っていない", got)
        self.assertIn("--land '調べ'", got)
        self.assertIn("--ask src", got)   # 打てなければ窓口（会社の名前）に頼む
        rc, out = self.main(self.src, "--clean")
        self.assertIn("頼みは納品済みだが、ブランチがメインブランチ（origin/main）に入っていない（入れ損ねか、入れる手を待っている。消すと成果を失う）。"
                      "入れるなら --land 調べ", out)
        # 入れてほしいと頼んだら、返事を待つ間は差し戻さず、--clean は返事待ちと出す
        deliver.log(self.inbox, {"kind": "ask", "id": "c1", "status": "sent", "at": 1,
                                 "from": {"name": "調べ", "place": self.place}, "to": {"company": "src", "name": "desk"}})
        self.assertIsNone(self.after())
        rc, out = self.main(self.src, "--clean")
        self.assertIn("頼みは納品済みで、この部署が頼んだ返事を待っている（受付 c1）", out)

    def test_a_department_that_handed_the_landing_to_an_open_ask_is_not_sent_back(self):
        # 2026-10-19 に my_notes で、--land が CI の赤で止まった部署が段取りに入れるのを頼み（c1）、段取りが持ち主への問い（c2）を
        # 担当者に書いて返した後も、3 回差し戻された（受付 2a2001）。c2 が閉じても入っていなければ、また差し戻す
        self.shape(self.LAND)
        provision.mark(self.place, self.src, {"ask": "q1", "delivered": "q1"}, gitx)
        test_deliver.git("-C", self.place, *GIT_ID, "commit", "-q", "--allow-empty", "-m", "x")
        dept = {"name": "調べ", "place": self.place}
        deliver.log(self.inbox, {"kind": "ask", "id": "c1", "status": "sent", "at": 1, "cause": "q1", "from": dept, "to": {"name": "段取り"}})
        deliver.log(self.inbox, {"kind": "ask", "id": "c2", "status": "sent", "at": 2, "from": {"name": "段取り"}, "to": {"name": "社長室"}})
        deliver.log(self.inbox, {"kind": "deliver", "id": "d1", "ask": "c1", "status": "sent", "at": 3, "holders": [{"holder": "c2", "ask": "c2"}]})
        self.assertIsNone(self.after())
        self.assertEqual(orders.leftover(self.place, gitx.worktree_attrs(self.place)), ("handed", ["c1"]))
        rc, out = self.main(self.src, "--clean")
        self.assertIn("頼みは納品済みだが、ブランチがメインブランチに入っていない。この部署が頼みを受けてから出した頼みの答えがまだ出ていない"
                      "（受付 c1。--todo で追える。入れる手を預けたのでなければ --land 調べ）", out)
        deliver.log(self.inbox, {"kind": "deliver", "id": "d2", "ask": "c2", "status": "sent", "at": 4})
        self.assertIn("--land '調べ'", self.after())
        # 預け先として数えるのは、今の頼み（q1）を受けてから出した頼みだけ（前の頼みの子や、ほかの部署の頼みを担当者に書いても外れない）
        deliver.log(self.inbox, {"kind": "ask", "id": "c3", "status": "sent", "at": 5, "cause": "q0", "from": dept, "to": {"name": "段取り"}})
        deliver.log(self.inbox, {"kind": "deliver", "id": "d3", "ask": "c3", "status": "sent", "at": 6, "holders": [{"holder": "c4", "ask": "c4"}]})
        deliver.log(self.inbox, {"kind": "ask", "id": "c4", "status": "sent", "at": 5, "from": {"name": "段取り"}, "to": {"name": "社長室"}})
        self.assertIn("--land '調べ'", self.after())

    def test_an_ask_sent_after_delivery_without_a_cause_counts_as_handed_and_rearms_the_limit(self):
        # 差し戻しの文が勧める形: 納品の後に --ask で入れるのを頼む（--ask は納品の後には cause を書かない）
        self.shape(self.LAND)
        # 今の頼みの納品の行は頼み元の受付箱（ここでは別の会社の物）に在る
        boss = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, boss, True)
        provision.mark(self.place, self.src, {"ask": "q1", "delivered": "q1", "config": self.cfg, "boss-inbox": boss}, gitx)
        test_deliver.git("-C", self.place, *GIT_ID, "commit", "-q", "--allow-empty", "-m", "x")
        dept = {"name": "調べ", "place": self.place}
        deliver.log(self.inbox, {"kind": "ask", "id": "c0", "status": "sent", "at": 1, "cause": None, "from": dept, "to": {"name": "段取り"}})
        deliver.log(self.inbox, {"kind": "deliver", "id": "d0", "ask": "c0", "status": "sent", "at": 2})
        deliver.log(boss, {"kind": "deliver", "id": "dq", "ask": "q1", "status": "sent", "at": 3, "to": {"name": "頼み元"}})
        payload = json.dumps({"session_id": "s-dept", "cwd": self.place, "background_tasks": []})
        with tempfile.TemporaryDirectory() as tmp:
            def stop():
                out = io.StringIO()
                orders.stop_hook(io.StringIO(payload), out, tmp_dir=tmp)
                return json.loads(out.getvalue())["reason"] if out.getvalue() else None
            got = [stop() for _ in range(deliver.STOP_LIMIT + 1)]
            self.assertEqual([x is not None for x in got], [True] * deliver.STOP_LIMIT + [False], got)   # 納品の前に出した c0 は数えない
            self.assertIn("--land '調べ'", got[0])
            deliver.log(self.inbox, {"kind": "ask", "id": "c1", "status": "sent", "at": 4, "cause": None, "from": dept, "to": {"name": "段取り"}})
            deliver.log(self.inbox, {"kind": "ask", "id": "c2", "status": "sent", "at": 5, "from": {"name": "段取り"}, "to": {"name": "社長室"}})
            deliver.log(self.inbox, {"kind": "deliver", "id": "d1", "ask": "c1", "status": "sent", "at": 6, "holders": [{"holder": "c2", "ask": "c2"}]})
            self.assertIsNone(stop())
            deliver.log(self.inbox, {"kind": "deliver", "id": "d2", "ask": "c2", "status": "sent", "at": 7})
            self.assertIn("--land '調べ'", stop())   # 上限まで差し戻した後でも、預けた先の答えが出れば、また差し戻す
            for _ in range(deliver.STOP_LIMIT):
                stop()
            # 返事を待つ間（waiting）も回数を 0 に戻す。担当者の無い返事が来れば、また差し戻す
            deliver.log(self.inbox, {"kind": "ask", "id": "c5", "status": "sent", "at": 8, "cause": None, "from": dept, "to": {"name": "段取り"}})
            self.assertIsNone(stop())
            deliver.log(self.inbox, {"kind": "deliver", "id": "d5", "ask": "c5", "status": "sent", "at": 9})
            self.assertIn("--land '調べ'", stop())

    def test_a_resident_department_is_sent_back_only_for_an_unlanded_branch(self):
        self.shape(self.LAND)
        provision.mark(self.place, self.src, {"ask": "q1", "delivered": "q1", "lifecycle": "persistent"}, gitx)
        self.assertIsNone(self.after())
        test_deliver.git("-C", self.place, *GIT_ID, "commit", "-q", "--allow-empty", "-m", "x")
        self.assertIn("ブランチがメインブランチ（origin/main の手元の控え）に入っていない", self.after())

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
        self.assertIn("--done でターンを終える", self.after())
        self.assertIsNone(self.after(count=deliver.STOP_LIMIT))
        self.assertIsNone(orders.stop_after({"session_id": "other"}, self.place, gitx.worktree_attrs(self.place), 0,
                                            os.path.dirname(self.cfg)))   # 同じ作業場の別の会話
        wake.enqueue(self.inbox, gitx.git_dir(self.place), {"id": "q2", "line": "頼みです（受付 q2）", "marks": {"ask": "q2"}})
        self.assertIsNone(self.after())   # 順番待ちは待ち受けが渡す
        wake.take(self.inbox, gitx.git_dir(self.place))
        provision.mark(self.place, self.src, {wake.FINISHED: "s-dept"}, gitx)
        self.assertIsNone(self.after())
        provision.mark(self.place, self.src, {wake.FINISHED: None, "lifecycle": "persistent"}, gitx)
        self.assertIsNone(self.after())   # 永続の部署は畳まない
        self.assertIsNone(orders.stop_after({"session_id": "s-desk"}, self.src, {"role": "窓口", "name": "desk", "ask": "q1",
                                                                                "delivered": "q1"}, 0, os.path.dirname(self.cfg)))

    def test_the_stop_hook_sends_back_after_delivery_up_to_the_limit(self):
        provision.mark(self.place, self.src, {"ask": "q1", "delivered": "q1"}, gitx)
        payload = json.dumps({"session_id": "s-dept", "cwd": self.place, "background_tasks": []})
        got = []
        with tempfile.TemporaryDirectory() as tmp:
            for _ in range(deliver.STOP_LIMIT + 1):
                out = io.StringIO()
                orders.stop_hook(io.StringIO(payload), out, tmp_dir=tmp)
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
            orders.stop_hook(io.StringIO(payload), out, tmp_dir=tmp)
        self.assertIn("--land '調べ'", json.loads(out.getvalue())["reason"])


class Landed(unittest.TestCase):
    """orders.landed（祖先か、マージ済みの PR に入ったか）と ghx.merged_pr_of。git と gh は偽物。"""

    class G:
        GitError = gitx.GitError

        def __init__(self, ancestor, repo="o/r"):
            self.ancestor, self.repo = ancestor, repo

        def is_merged(self, cwd, target):
            return self.ancestor

        def origin_repo(self, cwd):
            return self.repo

        def head_sha(self, cwd):
            return "h" * 40

    class Gh:
        GhError = ghx.GhError

        def __init__(self, got):
            self.got, self.asked = got, []

        def env_for(self, user, base_env):
            return {"GH_TOKEN": user}

        def merged_pr_of(self, repo, sha, base, env=None):
            self.asked.append((repo, sha, base, env))
            if isinstance(self.got, Exception):
                raise self.got
            return self.got

    def test_an_ancestor_is_landed_without_asking_github(self):
        gh = self.Gh(None)
        self.assertTrue(orders.landed("/w", "main", {}, self.G(True), gh))
        self.assertEqual(gh.asked, [])

    def test_a_merged_pr_counts_and_anything_unreadable_does_not(self):
        gh = self.Gh(7)
        self.assertTrue(orders.landed("/w", "main", {"gh-user": "u"}, self.G(False), gh))
        self.assertEqual(gh.asked, [("o/r", "h" * 40, "main", {"GH_TOKEN": "u"})])
        self.assertFalse(orders.landed("/w", "main", {}, self.G(False), self.Gh(None)))
        self.assertFalse(orders.landed("/w", "main", {}, self.G(False), self.Gh(ghx.GhError("no"))))
        self.assertFalse(orders.landed("/w", "main", {}, self.G(False, repo=None), self.Gh(7)))   # origin が GitHub でない

    def test_merged_pr_of_reads_only_prs_merged_into_the_base(self):
        class P:
            def __init__(self, stdout, returncode=0):
                self.stdout, self.returncode, self.stderr = stdout, returncode, ""
        rows = [{"number": 5, "merged_at": None, "base": {"ref": "main"}},
                {"number": 6, "merged_at": "2026-10-19T05:22:25Z", "base": {"ref": "wf/bundle"}},
                {"number": 7, "merged_at": "2026-10-19T05:22:25Z", "base": {"ref": "main"}}]
        argv = []
        got = ghx.merged_pr_of("o/r", "abc", "main", runner=lambda a, env=None: argv.append(a) or P(json.dumps(rows)))
        self.assertEqual(got, 7)
        self.assertEqual(argv, [["gh", "api", "repos/o/r/commits/abc/pulls"]])
        self.assertIsNone(ghx.merged_pr_of("o/r", "abc", "main", runner=lambda a, env=None: P(json.dumps(rows[:2]))))
        with self.assertRaises(ghx.GhError):
            ghx.merged_pr_of("o/r", "abc", "main", runner=lambda a, env=None: P("Not Found", 1))


if __name__ == "__main__":
    unittest.main()
