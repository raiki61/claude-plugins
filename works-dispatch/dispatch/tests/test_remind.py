"""リマインダー（docs/ledger.md の「リマインダー」）: 立てる・見る時の判じ・--due の知らせ・--todo の表示・閉じる。台帳は一時のフォルダの本物。"""

import argparse
import contextlib
import io
import json
import pathlib
import tempfile
import time
import types
import unittest
from unittest import mock

from . import schemacheck
import gitx
import orders
import reminds
import todo
from nodes import deliver, ledger, wake
from nodes import remind

A = "20261019-000001-aaaaaa"


def ask(i, at, status="sent"):
    return {"id": i, "kind": "ask", "at": at, "status": status, "from": {"name": "段取り", "place": "/desk"},
            "to": {"company": "co", "name": "割り振り", "path": "/co/dept"}, "file": None, "cause": None}


class Node(unittest.TestCase):
    def test_parse_on_reads_a_date_or_a_date_and_time_in_local_time(self):
        self.assertEqual(remind.parse_on("2026-10-22"), time.mktime((2026, 10, 22, 0, 0, 0, 0, 0, -1)))
        self.assertEqual(remind.parse_on("2026-10-22T09:30"), time.mktime((2026, 10, 22, 9, 30, 0, 0, 0, -1)))
        self.assertIsNone(remind.parse_on("数日内"))

    def test_it_comes_on_the_day_or_when_an_ask_it_waits_for_closes_whichever_first(self):
        rows = [{"id": "r", "kind": "remind", "at": 1, "text": "見る", "holder": "co/段取り", "on": 100, "after": [A]}]
        rem = remind.project(rows)["r"]
        open_ = {A: {"state": "working", "label": "動いている"}}
        self.assertIsNone(remind.came(rem, open_, 99))
        self.assertIn("見る日", remind.came(rem, open_, 100))
        self.assertEqual(remind.came(rem, {A: {"state": "done", "label": "済", "forwarded": True}}, 50), f"受付 {A} が閉じた（回した）")
        rows.append({"id": "r", "kind": "remind-done", "at": 2})
        self.assertIsNone(remind.came(remind.project(rows)["r"], open_, 100))   # 閉じた物は来ない

    def test_notice_rows_and_the_catalog(self):
        rows = [{"id": "r", "kind": "remind", "at": 1, "text": "見る", "holder": "co/段取り", "on": 1, "after": []},
                wake.notice("co/段取り", "r", wake.NOTE, None, "知らせ", 2)]
        self.assertEqual(list(remind.project(rows)), ["r"])
        self.assertEqual(remind.project(rows)["r"]["reminded"], 2)   # reminded の行の前に落ちても、知らせの行が印になる
        self.assertEqual(ledger.build(rows)["tasks"], {})   # リマインダーは頼みの木に入らない
        for kind in (remind.REMIND, remind.REMINDED, remind.REMIND_DONE):
            self.assertIn(kind, ledger.KINDS)

    def test_a_reminder_held_in_a_delivery_keeps_the_ask_open_until_it_closes(self):
        # 後でしか起きない事を追う疑問の担当者に、立てたリマインダーを書く（my_notes の受付 20261020-195701-cbef3b）
        r = "20261020-194429-5a8f86"
        rows = [ask(A, 1), {"id": r, "kind": "remind", "at": 2, "text": "測りを頼み直す", "holder": "co/段取り", "on": 9e9, "after": []},
                {"id": "f1", "kind": "deliver", "ask": A, "at": 3, "status": "sent", "holders": [{"holder": r, "ask": r}]}]
        view = ledger.build(rows, reminders=remind.project(rows))
        t = view["tasks"][A]
        self.assertEqual((t["state"], t["follows"], t["reminders"], t["open"]), ("done", [], [r], True))
        self.assertEqual(list(view["tasks"]), [A])   # 頼みの木には入れない
        self.assertEqual(ledger.awaited(view, A), [r])
        (node,) = ledger.select(view)
        self.assertEqual([x["id"] for x in node["reminders"]], [r])
        self.assertIn(f"→ 続き（リマインダー）: {r}  測りを頼み直す", "\n".join(ledger.lines([node])))
        self.assertIn("測りを頼み直す", ledger.page(ledger.select(view, everything=True), view, "now"))
        rows.append({"id": r, "kind": "remind-done", "at": 4})
        view = ledger.build(rows, reminders=remind.project(rows))
        self.assertEqual((view["tasks"][A]["open"], ledger.awaited(view, A), ledger.select(view)), (False, [], []))
        self.assertIn("リマインダー、閉じた", "\n".join(ledger.lines(ledger.select(view, everything=True))))


class Flow(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.tmp.name, "co")
        self.inbox = self.root / ".git" / "company" / "inbox"
        self.inbox.mkdir(parents=True)
        self.now = 1000.0
        self.attrs = {"role": "段取り", "name": "段取り", "session": "s1"}
        common = str(self.root / ".git")
        self.ports = types.SimpleNamespace(
            git=types.SimpleNamespace(common_dir=lambda cwd: common if str(cwd).startswith(str(self.root)) else None,
                                      git_dir=lambda cwd: common),
            env={}, now=lambda: self.now, attrs=lambda here: self.attrs,
            same_process=lambda pid: False)
        for patch in (mock.patch.object(orders, "inbox_company", lambda inbox, settings, g: "co"),
                      mock.patch.object(reminds.chat, "session_of", lambda env: "s1")):
            patch.start()
            self.addCleanup(patch.stop)
        self.addCleanup(self.tmp.cleanup)

    def call(self, fn, **kw):
        a = argparse.Namespace(**{"remind": None, "on": None, "after": None, "remind_done": None, "dry_run": False, **kw})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = fn(a, self.ports, str(self.root))
        return rc, buf.getvalue()

    def rows(self):
        return deliver.records(str(self.inbox))

    def test_it_needs_a_day_or_an_ask_to_wait_for(self):
        rc, out = self.call(reminds.put, remind="次に X が起きたら Y を見る")
        self.assertEqual(rc, 2)
        self.assertIn("見直す日を --on に付ける", out)
        self.assertEqual(self.call(reminds.put, remind="見る", on="来週")[0], 2)
        self.assertEqual(self.rows(), [])

    def test_only_a_named_department_or_desk_holds_one(self):
        self.attrs = {}
        rc, out = self.call(reminds.put, remind="見る", on="2026-10-22")
        self.assertEqual(rc, 2, out)

    def test_after_takes_a_short_id_and_refuses_a_closed_ask(self):
        deliver.log(str(self.inbox), ask(A, 1))
        rc, out = self.call(reminds.put, remind="納品が来たら社長室へ返す", after=["aaaaaa"])
        self.assertEqual(rc, 0, out)
        row = [r for r in self.rows() if r["kind"] == "remind"][0]
        self.assertEqual((row["holder"], row["after"], row["on"]), ("co/段取り", [A], None))
        deliver.log(str(self.inbox), {"id": A, "kind": "withdrawn", "at": 2})
        rc, out = self.call(reminds.put, remind="もう一度", after=[A])
        self.assertEqual(rc, 2)
        self.assertIn("もう閉じている", out)

    def test_due_tells_the_holder_once_when_the_ask_closes(self):
        deliver.log(str(self.inbox), ask(A, 1))
        self.call(reminds.put, remind="納品が来たら社長室へ返す", after=[A], on="2099-01-01")
        self.assertEqual(reminds.notify(str(self.inbox), self.ports.git.common_dir, self.now), [])   # まだ開いている
        deliver.log(str(self.inbox), {"id": "f1", "kind": "deliver", "ask": A, "at": 5, "status": "sent"})
        self.assertEqual(len(reminds.notify(str(self.inbox), self.ports.git.common_dir, self.now, dry_run=True)), 1)
        self.assertFalse([r for r in self.rows() if isinstance(r.get("to"), str)])   # 試し打ちは書かない
        got = reminds.notify(str(self.inbox), self.ports.git.common_dir, self.now)
        self.assertEqual(len(got), 1, got)
        notices = [r for r in self.rows() if isinstance(r.get("to"), str)]
        self.assertEqual(len(notices), 1)
        self.assertTrue(wake.mine(notices[0], ["co/段取り"]))   # 担当者の待ち受けが拾う知らせ
        self.assertIn("--remind-done", notices[0]["text"])
        self.assertEqual(reminds.notify(str(self.inbox), self.ports.git.common_dir, self.now), [])   # 2 度は知らせない
        self.assertEqual(schemacheck.check({"schema": ledger.SCHEMA, "rows": self.rows()}, schemacheck.schema("ledger")), [])

    def test_todo_shows_the_due_ones_and_done_closes_them(self):
        self.call(reminds.put, remind="gh で PR を見る", on="2026-01-01")
        self.call(reminds.put, remind="まだ先", on="2099-01-01")
        early, late = [r["id"] for r in self.rows()]

        def listed(everything, as_json):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                todo.todo(argparse.Namespace(todo="", all=everything, json=as_json, html=None), self.ports, str(self.root))
            return buf.getvalue()

        self.assertNotIn(early, listed(False, False))   # self.now=1000 は 1970 年なので、どれもまだ来ていない
        self.now = time.time()
        text = listed(False, False)
        self.assertIn(early, text)
        self.assertNotIn(late, text)
        got = json.loads(listed(True, True))
        self.assertEqual(schemacheck.check(got, schemacheck.schema("todo")), [])
        self.assertEqual([(r["id"], r["due"] is not None) for r in got["reminders"]], [(early, True), (late, False)])
        self.assertEqual([r["id"] for r in json.loads(listed(False, True))["reminders"]], [early])
        rc, out = self.call(reminds.close, remind_done=early[-6:])
        self.assertEqual(rc, 0, out)
        self.assertEqual(reminds.notify(str(self.inbox), self.ports.git.common_dir, self.now), [])   # 閉じた物は知らせない
        self.assertNotIn(early, listed(False, False))

    def test_todo_finds_a_reminder_by_its_id_and_a_delivery_may_hold_it_until_it_closes(self):
        self.call(reminds.put, remind="測りを頼み直す", on="2099-01-01")
        (r,) = [x["id"] for x in self.rows()]
        deliver.log(str(self.inbox), ask(A, 1))
        deliver.log(str(self.inbox), {"id": "f1", "kind": "deliver", "ask": A, "at": 5, "status": "sent",
                                      "holders": [{"holder": r, "ask": r}]})

        def shown(i, as_json=False, page=None):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                rc = todo.todo(argparse.Namespace(todo=i, all=False, json=as_json, html=page), self.ports, str(self.root))
            return rc, buf.getvalue()

        rc, out = shown(r[-6:])
        self.assertEqual(rc, 0, out)   # 前は「台帳に無い」で止めた
        self.assertIn(f"[待ち] 測りを頼み直す  {r}", out)
        self.assertIn(A, out)   # 担当者に書いた納品の頼み
        got = json.loads(shown(r, True)[1])
        self.assertEqual(schemacheck.check(got, schemacheck.schema("todo")), [])
        self.assertEqual(([x["id"] for x in got["reminders"]], got["held_by"]), ([r], [A]))
        self.assertIn(r, orders.ledger_asks(self.attrs, self.ports, str(self.root)))   # 納品の担当者に書ける
        self.assertEqual(self.call(reminds.close, remind_done=r)[0], 0)
        self.assertNotIn(r, orders.ledger_asks(self.attrs, self.ports, str(self.root)))   # 閉じた物は今までどおり止める
        self.assertEqual(shown("ffffff")[0], 2)
        rc, out = shown(r, page=str(self.root / "p.html"))
        self.assertEqual(rc, 2, out)   # ページは頼みの木だけ。黙って標準出力に出さない
        self.assertIn("リマインダーで", out)

    def company(self, departments=(), skills=()):
        return {"name": "co", "root": str(self.root), "info_source": "origin", "departments": list(departments),
                "skills": list(skills)}

    def test_a_reminder_goes_by_note_while_its_holder_stands_and_by_an_ask_once_it_is_folded(self):
        # 担当者の部署が畳まれた（on-demand の受け持ちの畳む部署）後は、知らせを拾う待ち受けが無い（頼み d3a7a1）
        duty = {"name": "仕組み", "role": "担当", "lifetime": "on-demand"}
        desk = {"attrs": {"name": "窓口", "role": "窓口"}, "path": str(self.root), "branch": "main", "head_office": True}
        standing = {"attrs": {"name": "仕組み", "role": "担当"}, "path": "/co/w", "branch": "work/ask-1"}
        same = lambda company, name: name
        self.assertIsNone(reminds.route("co/仕組み", [self.company([desk, standing], [duty])], str(self.root), same))
        self.assertEqual(reminds.route("co/仕組み", [self.company([desk], [duty])], str(self.root), same)[0], "co/仕組み")
        self.assertEqual(reminds.route("co/作業：abc123", [self.company([desk], [duty])], str(self.root), same)[0], "co")
        self.assertIsNone(reminds.route("co/窓口", [self.company([desk], [duty])], str(self.root), same))
        self.assertIsNone(reminds.route("far/仕組み", [self.company([desk], [duty])], str(self.root), same))   # 会社が開いていない
        kept = {"attrs": {"name": "点検", "role": "担当", "lifecycle": gitx.PERSISTENT}, "path": "/co/k", "branch": "work/k"}
        self.assertEqual(reminds.route("co/担当", [self.company([desk, kept])], str(self.root), same)[0], "co/点検")   # 役の名前の担当者
        with mock.patch.object(orders, "current_role", lambda settings, g: same):   # 窓口が無ければ頼まない（納品の返り先が無い）
            self.assertIsNone(reminds.asker(self.company([], [duty]), [self.company([], [duty])], None, self.ports,
                                            argparse.Namespace(dry_run=True), None)({"holder": "co/仕組み", "id": "x"}, "", True))

        self.attrs = {"role": "担当", "name": "仕組み", "session": "s1"}
        self.call(reminds.put, remind="効き目を測る", on="2026-01-01")
        sent = []

        def fake_ask(ns, ports, cwd, task):
            sent.append(ns)
            return 0
        a = argparse.Namespace(dry_run=False, config=None)
        self.now = time.time()
        with mock.patch.object(orders, "current_role", lambda settings, g: same), mock.patch.object(orders, "ask", fake_ask):
            reach = reminds.asker(self.company([desk], [duty]), [self.company([desk], [duty])], None, self.ports, a, None)
            dry = reminds.notify(str(self.inbox), self.ports.git.common_dir, self.now, dry_run=True, reach=reach)
            self.assertEqual((len(dry), sent), (1, []))
            self.assertIn("頼む", dry[0])
            got = reminds.notify(str(self.inbox), self.ports.git.common_dir, self.now, reach=reach)
            self.assertEqual(reminds.notify(str(self.inbox), self.ports.git.common_dir, self.now, reach=reach), [])   # 2 度は頼まない
        (ns,) = sent
        self.assertEqual((ns.ask, ns.task, ns.from_boss["boss"], ns.from_boss["boss-inbox"]), ("co/仕組み", None, "窓口", str(self.inbox)))
        self.assertIn("--remind-done", ns.text)
        self.assertIn("頼んだ", got[0])
        self.assertFalse([r for r in self.rows() if isinstance(r.get("to"), str)])   # 知らせの行は書かない
        (row,) = [r for r in self.rows() if r["kind"] == remind.REMINDED]
        self.assertEqual(row["child"], ns.ask_id)
        self.assertEqual(schemacheck.check({"schema": ledger.SCHEMA, "rows": self.rows()}, schemacheck.schema("ledger")), [])

    def test_a_refused_ask_is_asked_again_on_the_next_due(self):
        # 頼みが通らなければ reminded を書かず、次の --due で頼み直す（知らせに落とすと、立っていない担当者宛てで誰にも届かない）
        duty = {"name": "仕組み", "role": "担当", "lifetime": "on-demand"}
        desk = {"attrs": {"name": "窓口", "role": "窓口"}, "path": str(self.root), "branch": "main", "head_office": True}
        self.attrs = {"role": "担当", "name": "仕組み", "session": "s1"}
        self.call(reminds.put, remind="見る", on="2026-01-01")
        self.now = time.time()
        calls = []

        def fake_ask(ns, ports, cwd, task):
            calls.append(ns)
            if len(calls) == 2:   # 2 度目: 部署に届いた後に立てる道が 0 以外を返した（台帳は sent）
                deliver.log(str(self.inbox), {"id": ns.ask_id, "kind": "ask", "at": self.now, "status": "sent"})
            return 1
        co = self.company([desk], [duty])
        with mock.patch.object(orders, "current_role", lambda settings, g: lambda company, name: name), \
                mock.patch.object(orders, "ask", fake_ask):
            reach = reminds.asker(co, [co], None, self.ports, argparse.Namespace(dry_run=False), None)
            first = reminds.notify(str(self.inbox), self.ports.git.common_dir, self.now, reach=reach)
            self.assertIn("頼めなかった", first[0])
            self.assertFalse([r for r in self.rows() if r["kind"] == remind.REMINDED or isinstance(r.get("to"), str)])
            second = reminds.notify(str(self.inbox), self.ports.git.common_dir, self.now, reach=reach)
        self.assertIn("頼んだ", second[0])
        self.assertEqual(len([r for r in self.rows() if r["kind"] == remind.REMINDED]), 1)

    def test_a_reminder_whose_holder_stands_goes_by_the_note(self):
        self.call(reminds.put, remind="見る", on="2026-01-01")
        self.now = time.time()
        got = reminds.notify(str(self.inbox), self.ports.git.common_dir, self.now, reach=lambda r, line, dry_run: None)
        self.assertIn("知らせた", got[0])
        self.assertEqual(len([r for r in self.rows() if isinstance(r.get("to"), str)]), 1)

if __name__ == "__main__":
    unittest.main()
