"""台帳の射影（docs/ledger.md）: ledger ノードの頼みの木と状態、台帳の行の種類の一覧、--todo の入口。台帳は一時のフォルダの本物。"""

import argparse
import ast
import contextlib
import io
import json
import os
import pathlib
import re
import tempfile
import types
import unittest

from . import DISPATCH, schemacheck
import todo
from nodes import deliver, ledger

A, B, C, D = (f"20261018-0000{n:02d}-{h}" for n, h in ((1, "aaaaaa"), (2, "bbbbbb"), (3, "cccccc"), (4, "dddddd")))


def ask(i, at, status="sent", frm=None, to=None, **extra):
    return {"id": i, "kind": "ask", "at": at, "status": status, "from": frm or {"name": "desk", "place": "/desk"},
            "to": to or {"company": "co", "name": "調べ", "path": "/co/dept"}, "file": None, **extra}


def build(rows, **kw):
    return ledger.build(ledger.merge(rows), **kw)["tasks"]


class Projection(unittest.TestCase):
    def test_state_is_the_last_state_row_and_finished_states_stay(self):
        rows = [ask(A, 1, "queued"), {"id": A, "kind": "handed", "at": 2, "place": "/co/dept"},
                {"id": A, "kind": "waiting", "at": 3, "why": "持ち主の答え"}]
        self.assertEqual(build(rows)[A]["state"], "waiting")
        self.assertEqual(build(rows)[A]["why"], "持ち主の答え")
        rows.append({"id": A, "kind": "resumed", "at": 4})
        self.assertEqual(build(rows)[A]["state"], "working")
        rows += [{"id": "f1", "kind": "deliver", "ask": A, "at": 5, "status": "sent"},
                 {"id": "n1", "kind": "note", "ask": A, "at": 6, "status": "noticed"}]
        got = build(rows)[A]
        self.assertEqual((got["state"], got["label"], got["progress"], got["open"], got["notes"]), ("done", "済", "completed", False, 1))
        # 取り下げ・届かず・届かなかった納品（failed）・回した元への返し（for）
        self.assertEqual(build([ask(A, 1, "queued"), {"id": A, "kind": "withdrawn", "at": 2}])[A]["progress"], "cancelled")
        self.assertEqual(build([ask(A, 1, "failed")])[A]["open"], False)
        self.assertEqual(build([ask(A, 1), {"id": "f", "kind": "deliver", "ask": A, "at": 2, "status": "failed"}])[A]["state"], "working")
        self.assertEqual(build([ask(A, 1), {"id": "f", "kind": "deliver", "ask": A, "at": 2, "status": "sent", "for": B}])[A]["state"],
                         "working")
        # 頼み元の待ち受けへの知らせ（to が字の行）は、id が頼み
        self.assertEqual(build([ask(A, 1), {"id": A, "kind": "deliver", "at": 2, "to": "co/desk", "file": "/f.md"}])[A]["state"], "done")

    def test_the_rows_of_one_ask_in_two_ledgers_are_one_task(self):
        sent = ask(A, 1, "queued")
        got = ledger.build(ledger.merge([sent, {"id": A, "kind": "queued", "at": 1, "to": "co/調べ"}],
                                        [sent, {"id": A, "kind": "handed", "at": 2, "place": "/co/dept"}]))
        self.assertEqual((list(got["tasks"]), got["tasks"][A]["state"], got["roots"]), ([A], "working", [A]))

    def test_parents_come_from_forwarded_rows_then_cause_then_the_place_for_old_rows(self):
        dept = {"name": "調べ", "place": "/co/dept/sub"}
        rows = [ask(A, 1), ask(B, 2, frm=dept, cause=A, to={"name": "作業", "path": "/co/work"}),
                ask(C, 3, frm=dept),   # C は cause の無い古い行
                {"id": C, "kind": "forwarded", "at": 4, "child": D}, ask(D, 4, frm={"name": "窓口", "place": "/elsewhere"})]
        got = build(rows)
        self.assertEqual([(i, got[i]["parent"], got[i]["parent_by"]) for i in (A, B, C, D)],
                         [(A, None, None), (B, A, "cause"), (C, A, "inferred"), (D, C, "forwarded")])
        self.assertEqual(got[C]["state"], "done")
        self.assertTrue(got[C]["forwarded"])
        # cause のフィールドが在って空（受けていた頼みが無い場所から打った）なら、古い行の見分けをしない
        self.assertIsNone(build([ask(A, 1), ask(B, 2, frm=dept, cause=None)])[B]["parent"])
        # 古い行の見分けは、その場所がその時まだ閉じていない頼みにだけ結ぶ（返し終えた前の頼みの子にしない）
        rows = [ask(A, 1), {"id": "f", "kind": "deliver", "ask": A, "at": 2, "status": "sent"}, ask(B, 3, frm=dept)]
        self.assertIsNone(build(rows)[B]["parent"])

    def test_a_forwarded_ask_missing_from_the_ledgers_read_still_leads_to_its_child(self):
        rows = [{"id": "a0", "kind": "forwarded", "at": 1, "child": A, "boss": {"name": "社長室"}, "from": {"name": "desk"}},
                ask(A, 2, "queued")]
        view = ledger.build(ledger.merge(rows))
        self.assertEqual((view["tasks"]["a0"]["children"], view["tasks"]["a0"]["from"]), ([A], "社長室"))
        self.assertEqual(ledger.forwarded_open(view, "a0"), [A])

    def test_open_holders_link_the_next_asks_and_keep_the_others_as_questions(self):
        rows = [ask(A, 1), ask(B, 2, frm={"name": "x", "place": "/x"}),
                {"id": "f", "kind": "deliver", "ask": A, "at": 3, "status": "sent",
                 "holders": [{"holder": f"割り振り（受付 {B}）", "ask": B}, {"holder": "持ち主（価値で選ぶ）", "ask": None}]}]
        got = build(rows)
        self.assertEqual((got[A]["state"], got[A]["follows"], got[A]["open"]), ("done", [B], True))   # 続きが開いているので開いている
        self.assertEqual([q["holder"] for q in got[A]["questions"]], [f"割り振り（受付 {B}）", "持ち主（価値で選ぶ）"])
        rows.append({"id": "g", "kind": "deliver", "ask": B, "at": 4, "status": "sent"})
        self.assertFalse(build(rows)[A]["open"])   # 部署や持ち主の担当者は、閉じる行が無いので開いている物に数えない
        # holders のフィールドの無い古い納品の行は questions_of で読み、6 桁の短い受付も 1 つに当たれば結ぶ
        old = [ask(A, 1), ask(B, 2, frm={"name": "x", "place": "/x"}), {"id": "f", "kind": "deliver", "ask": A, "at": 3, "status": "sent"}]
        got = build(old, questions_of=lambda r: [{"holder": "段取り（受付 bbbbbb）", "ask": None}])
        self.assertEqual(got[A]["follows"], [B])

    def test_follows_in_a_loop_do_not_hang(self):
        rows = [ask(A, 1), ask(B, 2, frm={"name": "x", "place": "/x"}),
                {"id": "f", "kind": "deliver", "ask": A, "at": 3, "status": "sent", "holders": [{"holder": B, "ask": B}]},
                {"id": "g", "kind": "deliver", "ask": B, "at": 4, "status": "sent", "holders": [{"holder": A, "ask": A}]}]
        got = build(rows)
        self.assertEqual((got[A]["open"], got[B]["open"]), (False, False))

    def test_select_drops_finished_branches_unless_asked(self):
        dept = {"name": "調べ", "place": "/co/dept"}
        rows = [ask(A, 1), {"id": "f", "kind": "deliver", "ask": A, "at": 5, "status": "sent"},
                ask(B, 2, frm=dept, cause=A), ask(C, 3, frm=dept, cause=A), {"id": "g", "kind": "deliver", "ask": C, "at": 4, "status": "sent"},
                ask(D, 6), {"id": "h", "kind": "deliver", "ask": D, "at": 7, "status": "sent"}]
        view = ledger.build(ledger.merge(rows))
        (root,) = ledger.select(view)
        self.assertEqual((root["task"]["id"], [k["task"]["id"] for k in root["kids"]]), (A, [B]))
        self.assertEqual([n["task"]["id"] for n in ledger.select(view, everything=True)], [D, A])   # 新しく動いた順
        self.assertEqual([k["task"]["id"] for k in ledger.select(view, top=A, everything=True)[0]["kids"]], [B, C])
        self.assertEqual(ledger.lines(ledger.select(view)), [f"- [済] （題なし）  {A}", f"  - [動いている] （題なし）  {B}"])

    def test_forwarded_open_follows_only_the_forwarded_links(self):
        dept = {"name": "調べ", "place": "/co/dept"}
        rows = [ask(A, 1), {"id": A, "kind": "forwarded", "at": 2, "child": B}, ask(B, 2, "queued"),
                {"id": B, "kind": "forwarded", "at": 3, "child": C}, ask(C, 3), ask(D, 4, frm=dept, cause=C),
                {"id": "f", "kind": "deliver", "ask": C, "at": 5, "status": "sent"}]
        view = ledger.build(ledger.merge(rows))
        self.assertEqual(ledger.forwarded_open(view, A), [])    # C は済み。C が出した D へは回していないのでたどらない
        self.assertEqual(ledger.forwarded_open(view, D), [D])

    def test_the_page_is_one_file_with_its_own_style_and_script(self):
        rows = [ask(A, 1), {"id": "f", "kind": "deliver", "ask": A, "at": 2, "status": "sent", "holders": [{"holder": B, "ask": B}]},
                ask(B, 3, frm={"name": "x", "place": "/x"})]
        view = ledger.build(ledger.merge(rows), title_of=lambda f: "<題>")
        view["tasks"][A]["file"] = "/a.md"
        page = ledger.page(ledger.select(view, everything=True), view, "10-18 12:00")
        self.assertNotRegex(page, r"<script[^>]+src|<link|@import|https?://")
        self.assertIn(f'id="t-{B}"', page)
        self.assertIn(f'href="#t-{B}"', page)
        self.assertIn('<body class="hide">', page)
        self.assertIn("済んだ物も出す", page)


class Catalog(unittest.TestCase):
    """台帳に行を書くコードの種類（kind）が、みな ledger.KINDS と行の形（schemas/ledger.schema.json）に載っている。"""

    def written_kinds(self):
        files = sorted(DISPATCH.glob("*.py")) + sorted(DISPATCH.glob("nodes/*.py"))
        consts = {}
        trees = {p: ast.parse(p.read_text(encoding="utf-8")) for p in files}
        for p, tree in trees.items():
            for n in tree.body:
                if isinstance(n, ast.Assign) and isinstance(n.value, ast.Constant) and isinstance(n.value.value, str):
                    consts.update({(p.stem, t.id): n.value.value for t in n.targets if isinstance(t, ast.Name)})
        def value(p, v):
            if isinstance(v, ast.Constant):
                return v.value
            if isinstance(v, ast.Name):
                return consts.get((p.stem, v.id), v.id)
            if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name):
                return consts.get((v.value.id, v.attr), ast.unparse(v))
            return None
        found = {}
        for p, tree in trees.items():
            for n in ast.walk(tree):
                if isinstance(n, ast.Dict):   # 台帳の行は種類（kind）と時刻（at）を持つ辞書
                    keys = [k.value if isinstance(k, ast.Constant) else None for k in n.keys]
                    if "kind" in keys and "at" in keys:
                        got = value(p, n.values[keys.index("kind")])
                        if got is not None:
                            found.setdefault(got, f"{p.name}:{n.lineno}")
                if isinstance(n, ast.Call) and ast.unparse(n.func).endswith("wake.notice") and len(n.args) >= 3:
                    found.setdefault(value(p, n.args[2]), f"{p.name}:{n.lineno}")
        found.pop("kind", None)   # wake.notice の中の辞書（種類は呼ぶ側の引数）
        return found

    def test_every_kind_written_is_in_the_catalog(self):
        found = self.written_kinds()
        self.assertGreaterEqual(len(found), 15, found)
        self.assertEqual({k: at for k, at in found.items() if k not in ledger.KINDS}, {})

    def test_the_catalog_and_the_schemas_agree(self):
        self.assertEqual(set(schemacheck.schema("ledger")["properties"]["rows"]["items"]["properties"]["kind"]["enum"]), set(ledger.KINDS))
        task = schemacheck.schema("todo")["properties"]["forest"]["items"]["properties"]["task"]["properties"]
        self.assertEqual(set(task["state"]["enum"]), set(ledger.STATES))
        self.assertEqual(set(task["progress"]["enum"]), {p for _, p in ledger.STATES.values()})


class Holders(unittest.TestCase):
    def test_open_holders_reads_each_question(self):
        text = (f"- A を決める。担当者: 持ち主（価値で選ぶ）\n- B を直す。担当者: 割り振り（受付 {B}）\n- 担当者の無い件")
        self.assertEqual(deliver.open_holders(text), [{"holder": "持ち主（価値で選ぶ）", "ask": None},
                                                      {"holder": f"割り振り（受付 {B}）", "ask": B}])
        self.assertEqual(deliver.open_holders("なし"), [])
        self.assertEqual(deliver.open_holders(None), [])

    def test_task_title_takes_the_first_owner_words(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d, "a.md")
            p.write_text("持ち主の頼みです（社長室から）。\n\n## 持ち主の言葉\n- 「台帳から木を作って」\n- 「次」\n", encoding="utf-8")
            self.assertEqual(deliver.task_title(str(p)), "台帳から木を作って")
            p.write_text("頼み: ブランチを直す\n\n本文\n", encoding="utf-8")
            self.assertEqual(deliver.task_title(str(p)), "頼み: ブランチを直す")
            self.assertIsNone(deliver.task_title(os.path.join(d, "nope.md")))


class Todo(unittest.TestCase):
    """--todo: 打った場所の会社の台帳から、行が指すほかの会社の台帳までたどって木を出す。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = pathlib.Path(self.tmp.name)
        self.mine, self.theirs = (root / name / ".git" / "company" / "inbox" for name in ("mine", "theirs"))
        for inbox in (self.mine, self.theirs):
            inbox.mkdir(parents=True)
        (root / "theirs" / "dept").mkdir()
        (self.mine / f"{A}-ask.md").write_text("## 持ち主の言葉\n- 「木を作る」\n", encoding="utf-8")
        (self.theirs / f"{B}-ask.md").write_text("頼み: ブランチを直す\n", encoding="utf-8")
        summary = self.mine / "f-summary.md"
        summary.write_text(f"## 結論\n済んだ\n\n## 残った疑問\n- C を決める。担当者: 段取り（受付 {C}）\n", encoding="utf-8")
        # 古い形の行（cause と holders のフィールドが無い）。mine の窓口が theirs の調べに A を頼み、調べが A を受けたまま B を出し、B の納品の
        # 残った疑問が C を指す。mine の台帳の行は theirs の受付箱のファイルを指さないので、theirs は A の宛先の場所から引く
        self.write(self.mine, [ask(A, 1, frm={"name": "desk", "place": str(root / "mine")},
                                   to={"company": "theirs", "name": "調べ", "path": str(root / "theirs" / "dept")})
                               | {"file": str(self.mine / f"{A}-ask.md")},
                               {"id": "g", "kind": "deliver", "ask": A, "at": 5, "status": "sent", "file": str(self.mine / "g.md")}])
        self.write(self.theirs, [ask(B, 2, frm={"name": "調べ", "place": str(root / "theirs" / "dept")},
                                     to={"company": "theirs", "name": "作業", "path": "/w"}) | {"file": str(self.theirs / f"{B}-ask.md")},
                                 {"id": "f", "kind": "deliver", "ask": B, "at": 3, "status": "sent", "file": str(summary)},
                                 ask(C, 4, "queued", frm={"name": "x", "place": "/x"})])
        def common_dir(cwd):
            for name in ("mine", "theirs"):
                if cwd == str(root / name) or cwd.startswith(str(root / name) + os.sep):
                    return str(root / name / ".git")
            return None
        self.ports = types.SimpleNamespace(git=types.SimpleNamespace(common_dir=common_dir), now=lambda: 0)

    def tearDown(self):
        self.tmp.cleanup()

    def write(self, inbox, rows):
        for r in rows:
            deliver.log(str(inbox), r)

    def run_todo(self, **kw):
        a = argparse.Namespace(**{"todo": "", "all": False, "json": False, "html": None, **kw})
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            rc = todo.todo(a, self.ports, str(pathlib.Path(self.tmp.name, "mine")))
        return rc, buf.getvalue()

    def test_reads_the_other_company_ledger_through_the_rows(self):
        found, rows = todo.inboxes_from([str(self.mine)], self.ports.git.common_dir)
        self.assertEqual(found, [str(self.mine), str(self.theirs)])
        self.assertEqual(len([r for r in rows if r.get("kind") == "ask"]), 3)

    def test_prints_the_open_tree_and_json(self):
        rc, out = self.run_todo()
        self.assertEqual(rc, 0, out)
        lines = [re.sub(r"  \d{8}-\d{6}-[0-9a-f]{6}  .*$", "", x) for x in out.splitlines()]
        self.assertEqual(lines, ["- [済] 木を作る", "  - [済] 頼み: ブランチを直す", "    → 続き: " + C, "- [順番待ち] （題なし）"])
        rc, out = self.run_todo(json=True)
        got = json.loads(out)
        self.assertEqual(schemacheck.check(got, schemacheck.schema("todo")), [])
        self.assertEqual([n["task"]["id"] for n in got["forest"]], [A, C])
        rc, out = self.run_todo(todo="bbbbbb")
        self.assertTrue(out.startswith(f"- [済] 頼み: ブランチを直す  {B}"), out)
        self.assertEqual(self.run_todo(todo="zzzzzz")[0], 2)

    def test_writes_one_html_page(self):
        page = pathlib.Path(self.tmp.name, "todo.html")
        rc, out = self.run_todo(html=str(page))
        self.assertEqual(rc, 0, out)
        text = page.read_text(encoding="utf-8")
        self.assertIn("木を作る", text)
        self.assertNotRegex(text, r"<script[^>]+src|<link")

    def test_rows_written_by_the_code_fit_the_row_schema(self):
        for inbox in (self.mine, self.theirs):
            rows = deliver.records(str(inbox))
            self.assertEqual(schemacheck.check({"schema": ledger.SCHEMA, "rows": rows}, schemacheck.schema("ledger")), [])


if __name__ == "__main__":
    unittest.main()
