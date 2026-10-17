"""--move（move.py）と、上限で止まったときのフック（limit_hook.py）。git は一時のフォルダの本物、herdr・claude は偽物で回す。"""

import io
import json
import os
import pathlib
import time
import unittest
from unittest import mock

from . import test_deliver
import dispatch
import gitx
import limit_hook
import move
from nodes import deliver, provision, role, wake


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
        h = self.ports.herdr
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
                         "brief": pathlib.Path(ns.brief).read_text(encoding="utf-8"), "attrs": gitx.worktree_attrs(self.place)})
            return rc
        return seen, task

    def test_a_department_is_stopped_and_started_again_on_the_other_account_keeping_its_asker(self):
        provision.mark(self.place, self.src, {"residency": "resident", "ask": "q1", "boss": "desk", "boss-inbox": self.inbox,
                                              "job": "d"}, gitx)
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.stopped, [("c1", "d")])   # 前の会話を前のアカウントで止めてから
        keys = [w for w in self.ports.herdr.writes if w[0] == "send_keys"]
        self.assertEqual([k[2] for k in keys], ["ctrl+z", "escape"])   # 窓の attach の画面をシェルに戻す（d7d50c の 1）
        (got,) = seen
        self.assertEqual((got["ns"].task, got["ns"].branch, got["ns"].only_account, got["ns"].role), ("調べ", "dept/a", "a2", "調べ役"))
        self.assertTrue(got["ns"].resident)
        self.assertEqual(got["extra"]["boss"], "desk")   # 頼み元はそのまま（納品は元の頼み元へ）
        self.assertIn("受付 q1", got["brief"])
        self.assertIn("アカウント a1", got["brief"])
        self.assertIn("--deliver", got["tail"])
        self.assertNotIn("session", got["attrs"])   # 新しい会話の待ち受けが前の id を見ないよう、起こす前に消す
        (moved,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual((moved["from"], moved["to"], moved["status"]), ("a1", "a2", "done"))

    def test_if_limited_does_not_move_while_the_account_is_under_its_limit(self):
        self.ports.limits_seq = [{"a1": {"five_hour": {"used_percentage": 10}, "seven_day": {"used_percentage": 20}}, "a2": None}]
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-limited")
        self.assertEqual(rc, 0, out)
        self.assertIn("移さない", out)
        self.assertEqual((seen, self.stopped), ([], []))

    def test_no_other_account_with_room_stops(self):
        full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
        self.ports.limits_seq = [{"a1": full, "a2": full}]
        rc, out = self.main(self.src, "--move", "調べ")
        self.assertEqual(rc, 2, out)
        self.assertIn("移れるアカウントが無い", out)
        rc, out = self.main(self.src, "--move", "調べ", "--account", "a9")
        self.assertEqual(rc, 2, out)
        self.assertIn("accounts に無い", out)

    def changed_world(self, launched):
        # 毎回空にする部署。会社の形の model は opus、起こしたときは launched
        test_deliver.Flow.shape(self, '[[roles]]\nname = "調べ役"\nresident = true\nfresh = true\nmodel = "opus"\n')
        provision.mark(self.place, self.src, {"residency": "resident", "fresh": role.FRESH, "ask": "q1", "delivered": "q1",
                                              "boss": "desk", "boss-inbox": self.inbox, "job": "d", "launched": launched,
                                              wake.RESTARTING: "s-dept"}, gitx)

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
        # 前の会話を止めたら待ち受けの印を外す。起こし直した会話は空なので、空にした印も書く
        self.assertNotIn(wake.RESTARTING, got["attrs"])
        self.assertEqual(got["attrs"]["cleared"], "q1")
        (moved,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual((moved["from"], moved["to"], moved["why"]), ("a1", "a1", move.CHANGED))

    def test_if_changed_keeps_the_talk_when_the_values_are_the_same_or_it_carries_its_talk(self):
        self.changed_world(role.launch_key({"model": "opus"}))
        seen, task = self.fake_task()
        with mock.patch.object(dispatch, "_task", task):
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
            self.assertEqual(rc, 0, out)
            self.assertIn("起こし直さない", out)
            # 印は待ち受けが外す（止めなかったと見て、前の会話に頼みを渡す）
            self.assertEqual(gitx.worktree_attrs(self.place)[wake.RESTARTING], "s-dept")
            # 空いたアカウントが無ければ起こし直さない（上限のアカウントで起こすと、前の会話だけが止まる）
            full = {"five_hour": {"used_percentage": 100}, "seven_day": {"used_percentage": 50}}
            self.ports.limits_seq = [{"a1": full, "a2": full}]
            provision.mark(self.place, self.src, {"launched": role.launch_key(None)}, gitx)
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
            self.assertEqual(rc, 0, out)
            self.assertIn("使用率が上限に届かないアカウントが無い", out)
            provision.mark(self.place, self.src, {"fresh": None}, gitx)
            rc, out = self.main(self.src, "--move", "調べ", "--if-changed")
            self.assertEqual(rc, 2, out)
            self.assertIn("区切りの印（--rest）も無い", out)
        self.assertEqual((seen, self.stopped), ([], []))

    def test_the_desk_exits_and_starts_again_named_in_the_same_pane(self):
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s-desk", "account": "a1"}, gitx)
        for p in self.ports.herdr._panes:
            if p["pane_id"] == self.desk:
                p["agent_session"] = {"value": "s-desk"}
        self.ports.herdr.talking.add(self.desk)
        rc, out = self.main(self.src, "--move", "窓口", "--account", "a2")
        self.assertEqual(rc, 0, out)
        writes = [w for w in self.ports.herdr.writes if w[1] == self.desk and w[0] in ("prompt", "run")]
        self.assertEqual(writes[0][:3], ("prompt", self.desk, "/exit"))
        self.assertEqual(writes[1][0], "run")
        self.assertRegex(writes[1][2], r"^claude-a2 --name '窓口' '.*--move.*--desk 窓口")

    def test_the_desk_that_does_not_start_again_resumes_its_former_talk(self):
        # 新しい会話が立たなければ、前の会話を同じペインに --resume で戻し、訳を台帳に残す（窓口を消したままにしない）
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s-desk", "account": "a1"}, gitx)
        for p in self.ports.herdr._panes:
            if p["pane_id"] == self.desk:
                p["agent_session"] = {"value": "s-desk"}
        self.ports.herdr.talking.add(self.desk)
        failed = {"pane": self.desk, "status": "launch_failed", "detail": "起こせない"}
        with mock.patch.object(move.launch, "start_named", lambda *a, **k: failed):
            rc, out = self.main(self.src, "--move", "窓口", "--account", "a2")
        self.assertEqual(rc, 1, out)
        runs = [w[2] for w in self.ports.herdr.writes if w[1] == self.desk and w[0] == "run"]
        self.assertEqual(runs, ["claude-a1 --resume s-desk"])   # 前のアカウントで前の会話へ
        (moved,) = [r for r in deliver.records(self.inbox) if r.get("kind") == "moved"]
        self.assertEqual(moved["status"], "failed")
        self.assertIn("前の会話を --resume で戻した", moved["detail"])

    def test_the_desk_starts_again_with_the_settings_of_its_role(self):
        # 窓口の役の [roles.settings] は、--task の部署と同じく --settings で渡す（部署だけの鍵 worktree.bgIsolation は重ねない）
        test_deliver.Flow.shape(self, '[[roles]]\nname = "窓口"\n[roles.settings]\nenabledPlugins = { "works@m" = false }\n')
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s-desk", "account": "a1"}, gitx)
        for p in self.ports.herdr._panes:
            if p["pane_id"] == self.desk:
                p["agent_session"] = {"value": "s-desk"}
        self.ports.herdr.talking.add(self.desk)
        rc, out = self.main(self.src, "--move", "窓口", "--account", "a2")
        self.assertEqual(rc, 0, out)
        (run,) = [w for w in self.ports.herdr.writes if w[1] == self.desk and w[0] == "run"]
        path = os.path.join(gitx.git_dir(self.src), "company-settings.json")
        self.assertRegex(run[2], r"^claude-a2 --name '窓口' --settings \S*company-settings.json '.*--desk 窓口")
        self.assertEqual(json.loads(pathlib.Path(path).read_text(encoding="utf-8")), {"enabledPlugins": {"works@m": False}})


    def desk_world(self, **more):
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s-desk", "account": "a1", **more}, gitx)
        for p in self.ports.herdr._panes:
            if p["pane_id"] == self.desk:
                p["agent_session"] = {"value": "s-desk"}
        self.ports.herdr.talking.add(self.desk)

    def test_if_changed_restarts_the_desk_at_its_rest_with_the_settings_model_and_effort_of_its_role(self):
        # 窓口の役の起動の設定を替えたら、区切り（--rest）の番の終わりに、同じアカウントで起こし直す（持ち主の手で起こし直さない）
        test_deliver.Flow.shape(self, '[[roles]]\nname = "窓口"\nmodel = "opus"\neffort = "high"\n'
                                      '[roles.settings]\nenabledPlugins = { "works@m" = false }\n')
        self.desk_world(**{wake.RESTARTING: "s-desk"})
        rc, out = self.main(self.src, "--move", "窓口", "--if-changed")
        self.assertEqual(rc, 2, out)   # 区切りの印が無い間は起こし直さない（持ち主と話している途中の会話を切らない）
        self.assertIn("区切りの印（--rest）も無い", out)
        self.assertFalse([w for w in self.ports.herdr.writes if w[1] == self.desk])
        provision.mark(self.src, self.src, {wake.REST: "s-desk"}, gitx)
        rc, out = self.main(self.src, "--move", "窓口", "--if-changed")
        self.assertEqual(rc, 0, out)
        writes = [w for w in self.ports.herdr.writes if w[1] == self.desk and w[0] in ("prompt", "run")]
        self.assertEqual(writes[0][:3], ("prompt", self.desk, "/exit"))
        self.assertRegex(writes[1][2], r"^claude-a1 --name '窓口' --model opus --effort high --settings \S*company-settings.json '.*--desk 窓口")
        attrs = gitx.worktree_attrs(self.src)
        shape = role.load(os.path.join(self.src, ".claude", "company.toml"),
                          pathlib.Path(self.src, ".claude", "company.toml").read_text(encoding="utf-8"))
        self.assertEqual(attrs.get("launched"), role.launch_key(shape["roles"]["窓口"]))
        self.assertEqual(attrs.get(wake.LAUNCHING), "1")   # 起きた会話の --desk が外す
        for k in (wake.REST, wake.RESTARTING):
            self.assertNotIn(k, attrs)
        # 起こした値と同じなら、区切りでも起こし直さない（待ち受けは /clear で空にする）
        provision.mark(self.src, self.src, {wake.REST: "s-desk"}, gitx)
        rc, out = self.main(self.src, "--move", "窓口", "--if-changed")
        self.assertEqual(rc, 0, out)
        self.assertIn("起こし直さない", out)

    def test_the_desk_is_not_exited_in_the_middle_of_its_turn_or_over_typed_text(self):
        # 番の途中に打った /exit は番の終わりまで待ちの列に回り、起こし直さずに止まった後で効いて、窓口が消えたままになりうる
        self.desk_world()
        h = self.ports.herdr
        h.agent = lambda pane: {"agent": "claude", "agent_status": "working"}
        rc, out = self.main(self.src, "--move", "窓口", "--account", "a2")
        self.assertEqual(rc, 1, out)
        self.assertIn("番の途中", out)
        h.agent = lambda pane: {"agent": "claude", "agent_status": "idle"}
        h.screen = "─" * 20 + "\n❯ 打ちかけ\n" + "─" * 20
        rc, out = self.main(self.src, "--move", "窓口", "--account", "a2")
        self.assertEqual(rc, 1, out)
        self.assertIn("入力欄に字が在る", out)
        self.assertFalse([w for w in h.writes if w[1] == self.desk and w[0] in ("prompt", "run")])

class LimitHook(unittest.TestCase):
    Flow = test_deliver.Flow
    del Flow

    def setUp(self):
        test_deliver.Flow.setUp(self)

    def test_only_resident_departments_and_the_desk_move_on_a_rate_limit(self):
        base = {"cwd": self.place, "session_id": "s-dept", "error": "rate_limit"}
        self.assertIsNone(limit_hook.plan(base))   # 都度の部署
        provision.mark(self.place, self.src, {"residency": "resident"}, gitx)
        argv, cwd, out = limit_hook.plan(base)
        self.assertEqual(argv[2:5], ["--move", "調べ", "--if-limited"])
        self.assertEqual(cwd, self.place)
        self.assertIsNone(limit_hook.plan({**base, "error": "overloaded"}))
        provision.mark(self.src, self.src, {"role": "窓口", "name": "窓口", "session": "s-desk"}, gitx)
        self.assertIsNone(limit_hook.plan({"cwd": self.src, "session_id": "s-other", "error": "rate_limit"}))
        self.assertEqual(limit_hook.plan({"cwd": self.src, "session_id": "s-desk", "error": "rate_limit"})[0][3], "窓口")

    def test_main_spawns_once_within_the_quiet_time(self):
        provision.mark(self.place, self.src, {"residency": "resident"}, gitx)
        spawned = []
        payload = json.dumps({"cwd": self.place, "session_id": "s-dept", "error": "rate_limit"})
        for _ in range(2):
            limit_hook.main(io.StringIO(payload), spawn=lambda argv, **kw: spawned.append(argv), now=lambda: time.time())
        self.assertEqual(len(spawned), 1)
        self.assertTrue(os.listdir(os.path.join(self.inbox, limit_hook.MOVES)))


if __name__ == "__main__":
    unittest.main()
