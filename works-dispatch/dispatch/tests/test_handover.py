"""引き継ぎ（入口の --handover）と保留（--wait <訳> --park）。本社の窓口「段取り」の受け持ちを、同じ会社の部署「社長室」へ移す形で
回す。git（tests/fakegit.py）・herdr・claude の会話の一覧は偽物。"""

import contextlib
import json
import os
import pathlib
import sys
import unittest
from unittest import mock

from . import DISPATCH, fakegit  # noqa: F401
from .test_company import CompanyHerdr
from .test_dispatch import FakePorts, fake_cfg, gitx_source, run_main
import filex
import gitx
import orders
import role_hook
from nodes import deliver, handover, ledger, provision, wake

SHAPE = """desk_role = "段取り"
[[roles]]
name = "段取り"
[[roles]]
name = "相談"
ask_check = "{check}"
[[roles]]
name = "担当"
holders = ["社長室"]
deliver_check = "{gate}"
"""


class Handover(unittest.TestCase):
    """本社（self.src）に窓口 段取り、部署の場所（self.place）に 社長室。打つのは社長室の会話（s-a）。"""

    def setUp(self):
        self.cfg, self.root, self.g = fake_cfg()
        fakegit.forbid_real_git(self)
        self.src = gitx_source(self.cfg)
        self.company = os.path.basename(self.src)
        self.check = pathlib.Path(self.root).parent / "check.py"
        self.check.write_text("import json, sys\nd = json.load(sys.stdin)\n"
                              "sys.exit(0 if d['type'] in ('task', 'question') else 3)\n", encoding="utf-8")
        shape = pathlib.Path(self.src, ".claude", "company.toml")
        shape.parent.mkdir(exist_ok=True)
        self.gate = pathlib.Path(self.root).parent / "gate.py"   # 担当の納品の検査: 渡された JSON を gate.json に写して通す
        self.gate.write_text(f"import sys\nopen({str(self.gate.with_suffix('.json'))!r}, 'w').write(sys.stdin.read())\n",
                             encoding="utf-8")
        shape.write_text(SHAPE.format(check=f"{sys.executable} {self.check}", gate=f"{sys.executable} {self.gate}"), encoding="utf-8")
        self.place = self.g.add_worktree(str(pathlib.Path(self.root) / "office"), "work/office", "origin/main")
        provision.mark(self.src, self.src, {"role": "段取り", "lifecycle": "persistent", "account": "a1", "name": "段取り",
                                            "session": "s-desk"}, self.g)
        provision.mark(self.place, self.src, {"role": "相談", "lifecycle": "persistent", "account": "a1", "name": "社長室",
                                              "session": "s-a"}, self.g)
        self.ports = FakePorts([], git=self.g)
        self.ports.term = CompanyHerdr(self.src, self.g)
        self.desk_pane = self.ports.term.open_at(self.src, agent="claude")["pane_id"]
        self.pane = self.ports.term.open_at(self.place, agent="claude")["pane_id"]
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-a"}
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"id": "a", "sessionId": "s-a", "name": "社長室", "cwd": self.place, "kind": "background", "state": "working"},
            {"id": "d", "sessionId": "s-desk", "name": "段取り", "cwd": self.src, "kind": "interactive", "status": "idle"}]
        self.ports._cwd = self.place
        self.inbox = os.path.join(self.src, ".git", "company", "inbox")
        os.makedirs(os.path.join(self.inbox, wake.WAKE_DIR), exist_ok=True)
        self.log = os.path.join(self.inbox, deliver.LOG)
        self.desk_place = self.g.git_dir(self.src)
        self.office_place = self.g.git_dir(self.place)

    def main(self, *argv):
        return run_main(["--config", self.cfg, *argv], self.ports)

    def say(self, to, ask_id, kind="ask"):
        deliver.log(self.inbox, wake.notice(f"{self.company}/{to}", ask_id, kind, f"/f/{ask_id}", None, 1.0))

    def read_to_end(self, place):
        """その場所の待ち受けが台帳を終わりまで読んだ形。"""
        size = os.path.getsize(self.log) if os.path.isfile(self.log) else 0
        with open(wake.pos_path(self.inbox, place), "w", encoding="utf-8") as f:
            f.write(str(size))

    def queue(self, ask_id, kind="task"):
        body = pathlib.Path(self.inbox, f"{ask_id}-ask.md")
        body.write_text(f'+++\ntype = "{kind}"\n+++\n頼み {ask_id}\n', encoding="utf-8")
        wake.enqueue(self.inbox, self.desk_place, {"id": ask_id, "to": f"{self.company}/段取り", "file": str(body), "line": "x",
                                                   "digest": "d", "marks": {"boss": "窓口をたたむ"}, "at": 1.0, "from": "s-x",
                                                   "title": "t"})

    def rows(self, kind=None):
        return [r for r in deliver.records(self.inbox) if kind is None or r.get("kind") == kind]

    def test_dry_run_tells_what_moves_and_writes_nothing(self):
        self.say("段取り", "a1")
        self.read_to_end(self.desk_place)
        self.say("段取り", "a2")   # 段取りの待ち受けがまだ読んでいない知らせ
        self.queue("q1")
        before = (pathlib.Path(self.log).read_bytes(), self.g.worktree_attrs(self.src), self.g.worktree_attrs(self.place))
        rc, out = self.main("--handover", "段取り", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("空打ち", out)
        self.assertIn("写し直す未読の知らせ: 1 件", out)
        self.assertIn("移す順番待ち: q1", out)
        self.assertIn("本社の窓口を解く", out)
        self.assertEqual((pathlib.Path(self.log).read_bytes(), self.g.worktree_attrs(self.src), self.g.worktree_attrs(self.place)),
                         before)
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, self.desk_place)], ["q1"])

    def test_handover_moves_the_names_the_queue_and_the_unread_notices(self):
        self.say("段取り", "a1")
        self.read_to_end(self.desk_place)
        self.say("段取り", "a2")
        self.queue("q1")
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        attrs = self.g.worktree_attrs(self.place)
        self.assertEqual(gitx.former_names(attrs), ["段取り"])
        got = gitx.inherited(attrs)
        self.assertEqual(len(got), 1)
        self.assertEqual((got[0]["names"], got[0]["desk"], got[0]["since"]),
                         ([f"{self.company}/段取り"], True, os.path.getsize(self.log) - self._tail_bytes()))
        self.assertEqual({k: v for k, v in self.g.worktree_attrs(self.src, former=False).items()}, {})   # 本社の窓口は解いた
        self.assertEqual(wake.queued(self.inbox, self.desk_place), [])
        moved = wake.queued(self.inbox, self.office_place)
        self.assertEqual([(q["id"], q["to"]) for q in moved], [("q1", f"{self.company}/社長室")])
        copies = [r for r in self.rows() if r.get("copied")]
        self.assertEqual([(r["id"], r["to"]) for r in copies], [("a2", f"{self.company}/社長室")])
        self.assertEqual([r["status"] for r in self.rows(handover.KIND)], [handover.STARTED, handover.DONE])
        # 打ち直しても何も重ねない
        size = os.path.getsize(self.log)
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        self.assertIn("もうこの部署へ移してある", out)
        self.assertEqual(os.path.getsize(self.log), size)
        # 台帳の射影は写しの行を数えない（a2 は 1 件の頼みのまま）
        self.assertEqual(list(ledger.build(self.rows())["tasks"]), [])   # 知らせの行と写しは頼みの木に入らない

    def _tail_bytes(self):
        """台帳のうち、引き継ぎの後に書いた行（started の行から後）のバイト数。"""
        data = pathlib.Path(self.log).read_bytes()
        at = data.index(b'"kind": "handover"')
        return len(data) - data.rindex(b"\n", 0, at) - 1

    def test_the_successor_watcher_sees_only_what_came_after(self):
        self.say("段取り", "a1")
        self.read_to_end(self.desk_place)
        self.read_to_end(self.office_place)
        self.say("段取り", "a2")
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        self.say("段取り", "a3")   # 引き継いだ後に互換の宛先へ届いた知らせ
        attrs = self.g.worktree_attrs(self.place)
        names = wake.addresses(self.company, attrs, gitx.former_names(attrs))
        since = gitx.inherited_since(attrs)
        seen = []
        pos = wake.read_pos(self.inbox, self.office_place)
        while True:   # 待ち受けと同じ区切りで読む（_names_at の切れ目ごと）
            now, cut = wake._names_at(names, since, pos)
            rows, pos, _ = wake.read_new(self.log, pos, cut)
            seen += [(r["id"], r["to"].partition("/")[2]) for r in rows if wake.mine(r, now)]
            if cut is None:
                break
        # a1 は段取りが読んだ。a2 は写し（社長室宛て）で 1 度だけ、a3 は前の宛先のまま後継が拾う
        self.assertEqual(seen, [("a2", "社長室"), ("a3", "段取り")])

    def test_stops_when_the_desk_still_holds_an_ask_or_a_watcher_runs(self):
        provision.mark(self.src, self.src, {"ask": "h1"}, self.g)
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 2, out)
        self.assertIn("まだ納品していない", out)
        provision.mark(self.src, self.src, {"delivered": "h1"}, self.g)
        with mock.patch.object(wake, "watching", lambda inbox, place, *a, **k: place == self.desk_place):
            rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 2, out)
        self.assertIn("前の部署", out)
        self.assertIn("待ち受けが動いている", out)
        for argv, said in ((["--handover", "社長室"], "今の名前"), (["--handover", "無い"], "無い"), (["--handover", " "], "名前を渡す")):
            rc, out = self.main(*argv)
            self.assertEqual(rc, 2, out)
            self.assertIn(said, out)
        self.assertEqual(self.rows(handover.KIND), [])

    def test_stops_when_a_queued_ask_does_not_pass_the_successor_check(self):
        self.queue("q1", kind="note")
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 2, out)
        self.assertIn("後継の役が受けない頼み", out)
        self.assertIn("q1", out)
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, self.desk_place)], ["q1"])
        self.assertEqual(self.g.worktree_attrs(self.src)["name"], "段取り")

    def test_a_crash_midway_is_finished_by_running_it_again(self):
        self.read_to_end(self.desk_place)
        self.say("段取り", "a2")
        self.queue("q1")
        real = deliver.log
        calls = []

        def crash(inbox, row):   # 最初の写しの行を書く手前で落ちる
            if row.get("copied") and not calls:
                calls.append(row)
                raise OSError("落ちた")
            return real(inbox, row)
        with mock.patch.object(deliver, "log", crash):
            rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 1, out)
        self.assertIn("打ち直すと、残りの手順を続ける", out)
        self.assertEqual([r["status"] for r in self.rows(handover.KIND)], [handover.STARTED])
        self.assertEqual(self.g.worktree_attrs(self.src, former=False).get("name"), "段取り")   # 写し直す前は前の場所を消さない
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        self.assertEqual([r["status"] for r in self.rows(handover.KIND)], [handover.STARTED, handover.DONE])
        self.assertEqual(len({r["id"] for r in self.rows(handover.KIND)}), 1)   # 同じ引き継ぎを続けた
        self.assertEqual([r["id"] for r in self.rows() if r.get("copied")], ["a2"])
        self.assertEqual([r["id"] for r in self.rows(wake.QUEUED)], ["q1"])
        self.assertEqual(len(gitx.inherited(self.g.worktree_attrs(self.place))), 1)

    def test_a_crash_while_moving_the_queue_neither_hands_an_ask_twice_nor_leaves_it_in_two_queues(self):
        self.queue("q1")
        self.queue("q2")
        real = wake.move
        calls = []

        def crash(q, *a):   # q1 を移した後、q2 を移す手前で落ちる
            if q["id"] == "q2" and not calls:
                calls.append(q)
                raise OSError("落ちた")
            return real(q, *a)
        with mock.patch.object(wake, "move", crash):
            rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 1, out)
        both = [q["id"] for q in wake.queued(self.inbox, self.desk_place)] + [q["id"] for q in wake.queued(self.inbox, self.office_place)]
        self.assertEqual(sorted(both), ["q1", "q2"])   # どの件も 1 か所にだけ在る
        self.assertEqual(wake.find(self.inbox, "q1")["path"], wake.queued(self.inbox, self.office_place)[0]["path"])
        self.assertEqual(wake.take(self.inbox, self.office_place)["id"], "q1")   # 後継の待ち受けが落ちた後に q1 を渡した
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, self.office_place)], ["q2"])   # q1 を 2 度積まない
        self.assertEqual(wake.queued(self.inbox, self.desk_place), [])
        self.assertEqual(sorted(r["id"] for r in self.rows(wake.QUEUED) if r.get(handover.KIND)), ["q1", "q2"])

    def test_a_crash_before_clearing_the_desk_rechecks_what_it_holds(self):
        # 後継の属性を書いた後、前の場所の属性を消す手前で落ちる。その間に前の部署が頼みを受けたら、打ち直しは止まる
        real = provision.mark

        def crash(place, source, marks, g):
            if os.path.realpath(place) == os.path.realpath(self.src) and "role" in marks:
                raise OSError("落ちた")
            return real(place, source, marks, g)
        with mock.patch.object(provision, "mark", crash):
            rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 1, out)
        real(self.src, self.src, {"ask": "t9", "boss": "窓口をたたむ"}, self.g)
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 2, out)
        self.assertIn("受付 t9", out)
        self.assertEqual(self.g.worktree_attrs(self.src, former=False).get("ask"), "t9")   # 受けた頼みの返し先を消さない
        real(self.src, self.src, {"delivered": "t9"}, self.g)
        # 始めた後に積まれた頼みも、後継の役の ask_check を通してから移す
        self.queue("n1", kind="note")
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 2, out)
        self.assertIn("後継の役が受けない", out)
        wake.pull(wake.queued(self.inbox, self.desk_place)[0])
        real_lock = wake.ask_lock

        @contextlib.contextmanager
        def late(inbox, place, *args, **kw):   # 続きで、錠を取るまでの間に通らない頼みが積まれる
            if not wake.queued(self.inbox, self.desk_place):
                self.queue("n2", kind="note")
            with real_lock(inbox, place, *args, **kw):
                yield
        with mock.patch.object(wake, "ask_lock", late):
            rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 2, out)
        self.assertIn("始めた後に前の部署の順番待ちに積まれた", out)
        self.assertEqual([r["status"] for r in self.rows(handover.KIND)], [handover.STARTED])
        wake.pull(wake.queued(self.inbox, self.desk_place)[0])
        self.queue("q2")
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        self.assertEqual([r["status"] for r in self.rows(handover.KIND)], [handover.STARTED, handover.DONE])
        self.assertEqual([q["id"] for q in wake.queued(self.inbox, self.office_place)], ["q2"])

    def test_stops_when_the_queue_or_the_read_position_moves_before_the_lock(self):
        real = wake.ask_lock

        @contextlib.contextmanager
        def late(inbox, place, *args, **kw):   # 錠を取るまでの間に頼みが積まれる
            if not wake.queued(self.inbox, self.desk_place):
                self.queue("q3")
            with real(inbox, place, *args, **kw):
                yield
        with mock.patch.object(wake, "ask_lock", late):
            rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 2, out)
        self.assertIn("読み進めたか、順番待ちに頼みが積まれた", out)
        self.assertEqual(self.rows(handover.KIND), [])
        self.assertEqual(self.g.worktree_attrs(self.src, former=False).get("name"), "段取り")

    def test_the_successor_without_a_read_position_starts_where_the_handover_ended(self):
        self.read_to_end(self.desk_place)
        self.say("段取り", "a2")
        self.assertIsNone(wake.read_pos(self.inbox, self.office_place))
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        since = gitx.inherited(self.g.worktree_attrs(self.place))[0]["since"]
        self.assertEqual(wake.read_pos(self.inbox, self.office_place), since)
        rows = filex.read_jsonl(self.log, since).rows
        self.assertEqual([r["id"] for r in rows if r.get("copied")], ["a2"])   # 写した行は読んだ所より後に在る

    def test_handover_does_not_run_with_other_commands(self):
        for more in (("--deliver", "x.md"), ("--remind", "後で見る"), ("--todo",), ("--for", "c1"), ("--move", "段取り")):
            rc, out = self.main("--handover", "段取り", *more)
            self.assertEqual(rc, 2, out)
            self.assertIn(f"{more[0]} と一緒に使えない", out)
        self.assertEqual(self.rows(handover.KIND), [])

    def test_a_new_department_cannot_take_an_inherited_name(self):
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        self.ports.list_sessions = lambda cdir, include_done=False: []   # 前の窓口の会話はもう止めた
        brief = pathlib.Path(self.root).parent / "brief.md"
        brief.write_text("頼み\n", encoding="utf-8")
        rc, out = self.main("--task", "段取り", "--branch", "work/x", "--brief", str(brief), "--role", "担当", "--dry-run")
        self.assertEqual(rc, 1, out)
        self.assertIn("--handover で継いだ名前", out)

    def test_the_old_address_and_the_company_name_reach_the_successor(self):
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        _, _, _, _, companies, _, _ = orders.survey(self.cfg, self.ports)
        for to in (f"{self.company}/段取り", self.company, f"{self.company}/社長室"):
            got = deliver.find_target(companies, self.src, to)
            self.assertEqual(os.path.realpath(got["department"]["path"]), os.path.realpath(self.place), to)
        # ほかの会社の形の desk = "<会社>/段取り" も、前の名前で後継を引く
        other = {"name": "ほか", "root": "/o", "info_source": "/o", "departments": [], "desk_of": f"{self.company}/段取り"}
        got = deliver.find_target(companies + [other], "/o", "ほか")
        self.assertEqual(os.path.realpath(got["department"]["path"]), os.path.realpath(self.place))

    def test_an_ask_to_the_old_address_runs_the_successor_check(self):
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        # 後継の役の ask_check を、問い（question）だけ受ける形にする。互換の宛先へ頼んだ仕事（task）も、その検査が止める
        self.check.write_text("import json, sys\nsys.exit(0 if json.load(sys.stdin)['type'] == 'question' else 3)\n", encoding="utf-8")
        fold = self.g.add_worktree(str(pathlib.Path(self.root) / "fold"), "work/fold", "origin/main")
        provision.mark(fold, self.src, {"role": "担当", "account": "a1", "name": "窓口をたたむ", "session": "s-x"}, self.g)
        self.ports._cwd = fold
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-x"}
        for to in (f"{self.company}/段取り", self.company):
            with contextlib.chdir(fold):
                rc, out = self.main("--ask", to, "--text", "仕事を頼む")
            self.assertEqual(rc, 2, out)
            self.assertIn("役「相談」の ask_check", out)

    def fold(self):
        fold = self.g.add_worktree(str(pathlib.Path(self.root) / "fold"), "work/fold", "origin/main")
        provision.mark(fold, self.src, {"role": "担当", "account": "a1", "name": "窓口をたたむ", "session": "s-x"}, self.g)
        self.ports._cwd = fold
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-x"}
        return fold

    def test_an_ask_that_passes_the_check_is_queued_for_the_successor(self):
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        wake.claim(self.inbox, self.office_place, [f"{self.company}/社長室", f"{self.company}/段取り"], "s-a", os.getpid(), "t", 0)
        fold = self.fold()
        with contextlib.chdir(fold):
            rc, out = self.main("--ask", f"{self.company}/段取り", "--text", "仕事を頼む")
        self.assertEqual(rc, 0, out)
        self.assertEqual(wake.queued(self.inbox, self.desk_place), [])
        self.assertEqual(len(wake.queued(self.inbox, self.office_place)), 1, out)

    def test_an_ask_raced_by_the_handover_stops_instead_of_queueing_where_no_one_reads(self):
        # 宛先を読んだ後、頼みを置く前に、引き継ぎが前の場所を畳んだ: 誰も渡さない場所に積まず、打ち直しを促す
        wake.claim(self.inbox, self.desk_place, [f"{self.company}/段取り"], "s-desk", os.getpid(), "t", 0)
        fold = self.fold()
        real = wake.ask_lock

        @contextlib.contextmanager
        def folded(inbox, place, *args, **kw):
            if os.path.realpath(place) == os.path.realpath(self.desk_place) and self.g.worktree_attrs(self.src, former=False):
                provision.mark(self.src, self.src, {k: None for k in self.g.worktree_attrs(self.src, former=False)}, self.g)
            with real(inbox, place, *args, **kw):
                yield
        with mock.patch.object(wake, "ask_lock", folded), contextlib.chdir(fold):
            rc, out = self.main("--ask", f"{self.company}/段取り", "--text", "仕事を頼む")
        self.assertEqual(rc, 1, out)
        self.assertIn("畳まれたか名前が替わった", out)
        self.assertEqual(wake.queued(self.inbox, self.desk_place), [])

    def test_a_rerun_does_not_clear_a_new_desk_or_bring_back_an_answered_parked_ask(self):
        provision.mark(self.src, self.src, {deliver.PARKED: json.dumps([{"id": "p1", "boss": "窓口をたたむ"}])}, self.g)
        real = provision.mark

        def crash(place, source, marks, g):
            if os.path.realpath(place) == os.path.realpath(self.src) and "role" in marks:
                raise OSError("落ちた")
            return real(place, source, marks, g)
        with mock.patch.object(provision, "mark", crash):
            rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 1, out)
        self.assertEqual([p["id"] for p in deliver.parked_of(self.g.worktree_attrs(self.place))], ["p1"])
        # 後継が保留の p1 を返して外した後に打ち直しても、p1 を保留に戻さない
        real(self.place, self.src, {deliver.PARKED: None}, self.g)
        # 打ち直す前に、前の場所が別の名前を名乗った: 消さずに止める
        real(self.src, self.src, {"name": "受付"}, self.g)
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 2, out)
        self.assertIn("別の名前 受付", out)
        self.assertEqual(self.g.worktree_attrs(self.src, former=False).get("name"), "受付")
        real(self.src, self.src, {"name": "段取り"}, self.g)
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        self.assertEqual(deliver.parked_of(self.g.worktree_attrs(self.place)), [])

    def test_the_head_office_cannot_take_the_inherited_name_with_desk(self):
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        self.ports._cwd = self.src
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk"}
        rc, out = self.main("--desk", "段取り")
        self.assertEqual(rc, 2, out)
        self.assertIn("段取り", out)
        self.assertEqual(self.g.worktree_attrs(self.src, former=False), {})
        rc, out = self.main("--desk", "受付")   # 継いでいない名前なら名乗れる（本社の名付いた窓口が先に当たる）
        self.assertEqual(rc, 0, out)

    def test_a_reply_to_the_old_desk_goes_to_the_successor(self):
        h, h2 = "20261021-120000-aaaaaa", "20261021-130000-bbbbbb"
        rows = [{"id": h, "kind": handover.KIND, "status": handover.STARTED, "from": {"name": "段取り", "session": "s-desk"},
                 "to": {"name": "社長室", "session": "s-a", "account": "a1", "pane": "P1"}},
                {"id": h2, "kind": handover.KIND, "status": handover.STARTED, "from": {"name": "社長室", "session": "s-a"},
                 "to": {"name": "総務", "session": "s-b", "account": "a2", "pane": "P2"}}]
        before, between, after = "20261021-110000-cccccc", "20261021-123000-dddddd", "20261021-140000-eeeeee"
        got = handover.successor(rows[:1], {"name": "段取り", "session": "s-old"}, before)
        self.assertEqual((got["name"], got["session"], got["via"]), ("社長室", "s-a", h))
        self.assertEqual(handover.successor(rows, {"name": "段取り"}, before)["name"], "総務")   # 先までたどる
        self.assertEqual(handover.successor(rows, {"name": "社長室"}, between)["name"], "総務")
        self.assertIsNone(handover.successor(rows, {"name": "段取り"}, between))   # 移した後に同じ名前で頼んだ物は読み替えない
        self.assertIsNone(handover.successor(rows, {"name": "社長室"}, after))
        self.assertIsNone(handover.successor(rows, {"name": "段取り"}, "c1"))   # 受付番号の時刻を比べられない
        self.assertIsNone(handover.successor(rows, {"name": "窓口をたたむ", "session": "s-x"}, before))
        # 前の会話が引き継ぎの後に --desk でほかの名前を名乗って頼んだ物は、会話の id が同じでも横取りしない
        self.assertIsNone(handover.successor(rows, {"name": "受付", "session": "s-desk"}, before))
        # 頼み元が自分（今の名前か継いだ名前）なら送らずに閉じる。--reorg --name で替える前の名前は自分と見ない
        own = os.path.join(self.src, ".git", "company", "inbox")
        mine = {"name": "社長室", "former-names": '["段取り", "調べもの"]', "session": "s-a",
                gitx.INHERITED: json.dumps([{"id": h, "from": "段取り", "names": ["段取り"], "since": 0}])}
        self.assertTrue(orders.to_self(mine, {"boss": "段取り", "boss-inbox": own}, own))
        self.assertTrue(orders.to_self(mine, {"boss": "社長室", "boss-inbox": own}, own))
        self.assertFalse(orders.to_self(mine, {"boss": "調べもの", "boss-inbox": own}, own))
        self.assertFalse(orders.to_self(mine, {"boss": "段取り", "boss-inbox": "/elsewhere"}, own))
        self.assertFalse(orders.to_self(mine, {"boss": "窓口をたたむ", "boss-inbox": own}, own))

    def test_the_held_ask_of_the_successor_closes_as_self_after_the_handover(self):
        # 社長室は段取りから受けた頼み c1 を持ったまま、段取りを継ぐ。納品すると頼み元が自分なので、知らせずに閉じる
        provision.mark(self.place, self.src, {"ask": "c1", "boss": "段取り", "boss-session": "s-desk", "boss-account": "a1",
                                              "boss-inbox": self.inbox}, self.g)
        rc, out = self.main("--handover", "段取り", "--dry-run")
        self.assertIn("この部署が持つ頼みのうち頼み元が 段取り の物", out)
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        summary = pathlib.Path(self.root).parent / "sum.md"
        summary.write_text('+++\nopen = []\n+++\n## 結論\n済んだ\n## 決め手\nhttps://example.com/a\n', encoding="utf-8")
        with contextlib.chdir(self.place):
            rc, out = self.main("--deliver", str(summary))
        self.assertEqual(rc, 0, out)
        self.assertIn(orders.SELF, out)
        got = [r for r in self.rows("deliver") if r.get("ask") == "c1"]
        self.assertEqual([r["status"] for r in got], [orders.SELF])
        self.assertEqual(self.g.worktree_attrs(self.place)["delivered"], "c1")
        self.assertEqual(self.ports.term.writes and [w for w in self.ports.term.writes if w[0] == "prompt"], [])

    # 引き継ぎの後の納品の担当者（残った疑問の holder）は、頼み元を後継に読み替えてから検査する。担当の役は社長室を中継（holders）に
    # 持つので、ふつうは社長室を担当者に書けない。移すより前に段取りが頼んだ物だけ、頼み元の後継として書ける
    PRE, POST = "20261021-110000-aaaaaa", "20261021-130000-bbbbbb"   # 引き継ぎ（12:00）の前と後の受付

    def handed_over_with(self, ask, boss="段取り", inbox=None, **more):
        """担当の部署 窓口をたたむ（頼み元 boss から受付 ask を受けている）を残して、段取りを社長室へ 12:00 に移す。その部署の場所。"""
        self.ports.now = lambda: 1792584000   # 2026-10-21 12:00 UTC
        fold = self.fold()
        provision.mark(fold, self.src, {"ask": ask, "boss": boss, "boss-session": "s-desk", "boss-account": "a1",
                                        "boss-inbox": inbox or self.inbox, **more}, self.g)
        self.ports._cwd, self.ports.env = self.place, {"CLAUDE_CODE_SESSION_ID": "s-a"}
        rc, out = self.main("--handover", "段取り")
        self.assertEqual(rc, 0, out)
        self.ports._cwd, self.ports.env = fold, {"CLAUDE_CODE_SESSION_ID": "s-x"}
        return fold

    def deliver_with(self, place, holder, *more):
        summary = pathlib.Path(self.root).parent / "sum.md"
        summary.write_text(f'+++\n[[open]]\nquestion = "後で決める"\nholder = "{holder}"\n+++\n## 結論\n済んだ\n## 決め手\n'
                           'https://example.com/a\n', encoding="utf-8")
        with contextlib.chdir(place):
            return self.main("--deliver", str(summary), *more)

    def delivered(self, ask):
        return [(r["status"], (r.get("to") or {}).get("name")) for r in self.rows("deliver") if r.get("ask") == ask]

    def test_a_department_of_the_old_desk_names_the_successor_as_holder(self):
        fold = self.handed_over_with(self.PRE)
        rc, out = self.deliver_with(fold, "社長室")
        self.assertEqual(rc, 0, out)
        self.assertIn("社長室 へ返す", out)
        self.assertEqual(self.delivered(self.PRE), [("sent", "社長室")], out)
        self.assertEqual(json.loads(self.gate.with_suffix(".json").read_text(encoding="utf-8"))["boss"], "社長室")   # 検査も後継で見る
        self.assertEqual(self.g.worktree_attrs(fold)["boss"], "段取り")   # 部署の属性（頼み元の名前）は書き換えない

    def test_the_old_desk_as_holder_is_checked_against_the_successor(self):
        fold = self.handed_over_with(self.PRE)
        rc, out = self.deliver_with(fold, "段取り")   # 頼み元はもう段取りでない
        self.assertEqual(rc, 2, out)
        self.assertIn("担当者「段取り」", out)
        self.assertEqual(self.delivered(self.PRE), [])

    def test_a_renamed_successor_is_the_holder_and_the_receiver_by_its_current_name(self):
        # 後継（社長室）が引き継ぎの後に名前を替えた（--reorg --name か --desk。前の名前は company.former-names に残る）: 台帳の
        # handover の行は社長室のままでも、今の名前で担当者に書け、今の名前へ返す（受付 6d331c。my_notes で 2 回、回り道の頼みが出た）
        fold = self.handed_over_with(self.PRE)
        self.ports._cwd, self.ports.env = self.place, {"CLAUDE_CODE_SESSION_ID": "s-a"}
        with contextlib.chdir(self.place):
            rc, out = self.main("--reorg", "--name", "総務")
        self.assertEqual(rc, 0, out)
        self.ports._cwd, self.ports.env = fold, {"CLAUDE_CODE_SESSION_ID": "s-x"}
        rc, out = self.deliver_with(fold, "社長室")   # 移した時の名前はもう頼み元でない
        self.assertEqual(rc, 2, out)
        self.assertIn("担当者「社長室」", out)
        rc, out = self.deliver_with(fold, "総務")
        self.assertEqual(rc, 0, out)
        self.assertIn("総務 へ返す", out)
        self.assertEqual(self.delivered(self.PRE), [("sent", "総務")], out)
        self.assertEqual(json.loads(self.gate.with_suffix(".json").read_text(encoding="utf-8"))["boss"], "総務")

    def test_renamed_reads_the_current_name_only_from_the_successors_former_names(self):
        heir = {"name": "本社の司令塔", "session": "s", "via": "h1", "path": "/p"}
        self.assertEqual(handover.renamed(heir, {"name": "司令塔", "former-names": '["社長室", "本社の司令塔"]'})["name"], "司令塔")
        self.assertIs(handover.renamed(heir, {"name": "司令塔", "former-names": '["社長室"]'}), heir)   # 別の会話が名乗った場所
        self.assertIs(handover.renamed(heir, {"name": "本社の司令塔"}), heir)
        self.assertIs(handover.renamed(heir, {}), heir)
        self.assertIsNone(handover.renamed(None, {"name": "司令塔"}))

    def test_the_successor_is_not_a_holder_for_other_asks(self):
        for case in ("無関係な頼み元", "移した後に前の名前で頼んだ物", "別の会社の段取り（引き継ぎの行が無い）"):
            with self.subTest(case):
                self.setUp()
                other = pathlib.Path(self.root) / "other-co" / ".git" / "company" / "inbox"
                other.mkdir(parents=True)
                ask, boss, inbox = {"無関係な頼み元": (self.PRE, "窓口をひらく", None),
                                    "移した後に前の名前で頼んだ物": (self.POST, "段取り", None)}.get(case, (self.PRE, "段取り", str(other)))
                fold = self.handed_over_with(ask, boss, inbox)
                rc, out = self.deliver_with(fold, "社長室")
                self.assertEqual(rc, 2, out)
                self.assertIn("担当者「社長室」", out)
                self.assertNotIn("社長室 へ返す", out)
                self.assertFalse(self.gate.with_suffix(".json").exists())   # 担当者の検査で止まり、納品の検査まで行かない
                self.assertEqual(self.delivered(ask), [])

    def test_a_parked_ask_of_the_old_desk_names_the_successor_as_holder(self):
        fold = self.handed_over_with("t2", "窓口をひらく", parked=json.dumps(
            [{"id": self.PRE, "boss": "段取り", "boss-session": "s-desk", "boss-account": "a1", "boss-inbox": self.inbox}]))
        rc, out = self.deliver_with(fold, "社長室", "--for", self.PRE)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.delivered(self.PRE), [("sent", "社長室")], out)
        self.assertEqual(deliver.parked_of(self.g.worktree_attrs(fold)), [])
        self.assertEqual(json.loads(self.gate.with_suffix(".json").read_text(encoding="utf-8"))["boss"], "社長室")

    def test_a_forwarded_ask_of_the_old_desk_names_the_successor_as_holder(self):
        fold = self.handed_over_with("t2", "窓口をひらく")
        deliver.log(self.inbox, {"id": self.PRE, "kind": "forwarded", "child": "20261021-111000-cccccc", "at": 1.0,
                                 "from": {"name": "窓口をたたむ"},
                                 "boss": {"name": "段取り", "session": "s-desk", "account": "a1", "inbox": self.inbox}})
        rc, out = self.deliver_with(fold, "社長室", "--for", self.PRE)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.delivered(self.PRE), [("sent", "社長室")], out)
        self.assertEqual(self.g.worktree_attrs(fold)["ask"], "t2")   # 今の頼みは閉じない
        self.assertEqual(json.loads(self.gate.with_suffix(".json").read_text(encoding="utf-8"))["boss"], "社長室")

    def test_a_caused_ask_of_the_old_desk_names_the_successor_as_holder(self):
        # cause 付きの --ask で回した子の頼みの答え: 元の頼み（段取りから引き継ぎの前に受けた物）を納品した後に、--for で返す
        fold = self.handed_over_with("t2", "窓口をひらく")
        child = "20261021-111000-dddddd"
        deliver.log(self.inbox, {"id": child, "kind": "ask", "cause": self.PRE, "at": 1.0, "status": "sent",
                                 "from": {"name": "窓口をたたむ"}, "to": {"name": "社長室"},
                                 "cause_boss": {"name": "段取り", "session": "s-desk", "account": "a1", "inbox": self.inbox}})
        deliver.log(self.inbox, {"id": "20261021-111500-eeeeee", "kind": "deliver", "ask": self.PRE, "at": 1.0, "status": "sent",
                                 "from": {"name": "窓口をたたむ"}, "to": {"name": "段取り"}})
        rc, out = self.deliver_with(fold, "社長室", "--for", child)
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.delivered(self.PRE), [("sent", "段取り"), ("sent", "社長室")], out)
        self.assertEqual(json.loads(self.gate.with_suffix(".json").read_text(encoding="utf-8"))["boss"], "社長室")

    def test_a_reply_that_comes_back_to_the_successor_itself_closes_as_self(self):
        self.handed_over_with("t2", "窓口をひらく")
        provision.mark(self.place, self.src, {"ask": self.PRE, "boss": "段取り", "boss-session": "s-desk", "boss-account": "a1",
                                              "boss-inbox": self.inbox}, self.g)
        self.ports._cwd, self.ports.env = self.place, {"CLAUDE_CODE_SESSION_ID": "s-a"}
        rc, out = self.deliver_with(self.place, "owner:choose")
        self.assertEqual(rc, 0, out)
        self.assertEqual(self.delivered(self.PRE), [(orders.SELF, "社長室")], out)


class Park(unittest.TestCase):
    """--wait <訳> --park: 答え待ちの頼みを保留にして、次の頼みを受ける。"""

    def setUp(self):
        self.cfg, self.root, self.g = fake_cfg()
        fakegit.forbid_real_git(self)
        self.src = gitx_source(self.cfg)
        self.place = self.g.add_worktree(str(pathlib.Path(self.root) / "office"), "work/office", "origin/main")
        self.inbox = os.path.join(self.src, ".git", "company", "inbox")
        provision.mark(self.place, self.src, {"role": "相談", "account": "a1", "name": "社長室", "session": "s-a", "ask": "c1",
                                              "boss": "段取り", "boss-session": "s-desk", "boss-account": "a1",
                                              "boss-pane": "P0", "boss-inbox": self.inbox}, self.g)
        os.makedirs(self.inbox, exist_ok=True)
        deliver.log(self.inbox, {"id": "c1", "kind": "ask", "at": 1.0, "status": "sent", "title": "持ち主に問う",
                                 "from": {"name": "段取り", "session": "s-desk"}, "to": {"name": "社長室", "session": "s-a"}})
        self.ports = FakePorts([], git=self.g)
        self.ports.term = CompanyHerdr(self.src, self.g)
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-a"}
        self.ports.list_sessions = lambda cdir, include_done=False: []
        self.ports._cwd = self.place

    def main(self, *argv):
        with contextlib.chdir(self.place):
            return run_main(["--config", self.cfg, *argv], self.ports)

    def test_park_frees_the_ask_and_keeps_it_waiting_in_the_ledger(self):
        rc, out = self.main("--wait", "持ち主の答え", "--park")
        self.assertEqual(rc, 0, out)
        attrs = self.g.worktree_attrs(self.place)
        self.assertIsNone(wake.pending(attrs))   # 次の頼みを受けられる
        self.assertNotIn("delivered", attrs)     # 納品済みにはしない
        parked = deliver.parked_of(attrs)
        self.assertEqual([(p["id"], p["boss"], p["boss-inbox"]) for p in parked], [("c1", "段取り", self.inbox)])
        state = {k: t["state"] for k, t in ledger.build(deliver.records(self.inbox))["tasks"].items()}
        self.assertEqual(state.get("c1"), "waiting")
        self.assertIn("c1", role_hook.parked_text(attrs))
        self.assertIn("--for <受付>", role_hook.parked_text(attrs))
        # 今の頼みが無いので、--for 無しの納品は止まる
        summary = pathlib.Path(self.root).parent / "sum.md"
        summary.write_text('+++\nopen = []\n+++\n## 結論\n答えた\n## 決め手\nhttps://example.com/a\n', encoding="utf-8")
        rc, out = self.main("--deliver", str(summary))
        self.assertEqual(rc, 2, out)
        self.assertIn("--for に渡す", out)

    def test_the_parked_ask_is_answered_with_for_while_another_ask_is_held(self):
        self.main("--wait", "持ち主の答え", "--park")
        provision.mark(self.place, self.src, {"ask": "t2", "boss": "窓口をたたむ", "boss-session": "s-x", "boss-inbox": self.inbox},
                       self.g)
        summary = pathlib.Path(self.root).parent / "sum.md"
        summary.write_text('+++\nopen = []\n+++\n## 結論\n答えた\n## 決め手\nhttps://example.com/a\n', encoding="utf-8")
        rc, out = self.main("--deliver", str(summary), "--for", "c1")
        got = [r for r in deliver.records(self.inbox) if r.get("kind") == "deliver" and isinstance(r.get("to"), dict)]
        self.assertEqual([(r["ask"], r.get("parked"), r.get("for"), r["to"]["name"]) for r in got], [("c1", True, None, "段取り")], out)
        attrs = self.g.worktree_attrs(self.place)
        self.assertEqual(deliver.parked_of(attrs), [])
        self.assertEqual((attrs["ask"], attrs.get("delivered")), ("t2", None))   # 今の頼みはそのまま
        state = {k: t["state"] for k, t in ledger.build(deliver.records(self.inbox))["tasks"].items()}
        self.assertEqual(state.get("c1"), "done")

    def test_park_needs_wait(self):
        rc, out = self.main("--park")
        self.assertEqual(rc, 2, out)


if __name__ == "__main__":
    unittest.main()
