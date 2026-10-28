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
    def test_received_at_is_the_last_place_that_took_the_ask(self):
        rows = [ask(A, 1, "queued", to={"name": "調べ", "path": "/co/dept"}), {"id": A, "kind": "handed", "at": 2, "place": "/co/dept/sub"},
                ask(B, 3, "failed", to={"name": "調べ", "path": "/co/gone"})]
        self.assertEqual(ledger.received_at(rows, A), "/co/dept/sub")
        self.assertIsNone(ledger.received_at(rows, B))   # 届かなかった頼みは、どこも受けていない
        self.assertIsNone(ledger.received_at(rows, C))

    def test_an_ask_taken_here_is_working_but_one_taken_to_another_place_waits_for_its_ask_row(self):
        rows = [ask(A, 1, "queued"), {"id": A, "kind": "taken", "at": 2, "to": {"name": "調べ", "role": "担当"},
                                      "by": {"session": "s", "place": "/co/dept"}},
                ask(B, 1, "queued"), {"id": B, "kind": "taken", "at": 2, "to": {"ask": "作業"}, "by": {"session": "s", "place": "/desk"}}]
        tasks = build(rows)
        self.assertEqual((tasks[A]["state"], tasks[B]["state"]), ("working", "queued"))
        self.assertEqual((ledger.received_at(rows, A), ledger.received_at(rows, B)), ("/co/dept", "/co/dept"))

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

    def test_extra_causes_link_the_ask_under_each_listed_parent_without_moving_its_tree_parent(self):
        # 束の合図が回した頼み（束の設計 9）: 親は cause の 1 つのまま、causes に並べた頼みの子にも並べる（自分・親・自分の下・無い頼みは飛ばす）
        dept = {"name": "調べ", "place": "/co/dept"}
        rows = [ask(A, 1), ask(B, 2), ask(C, 3, frm=dept, cause=A, causes=[B, A, C, "missing"]), ask(D, 4, frm=dept, cause=C, causes=[C])]
        got = build(rows)
        self.assertEqual((got[C]["parent"], got[C]["parent_by"]), (A, "cause"))
        self.assertEqual((got[A]["children"], got[B]["children"], got[C]["children"]), ([C], [C], [D]))

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
        # holders のフィールドの担当者（頭書きの holder）からは、古い行なら拾える字でも 6 桁を拾わない（名前の中の 16 進の字を受付と取り違えない。受付 0715c5）
        old[-1]["holders"] = [{"holder": "段取り（受付 bbbbbb）", "ask": None}]
        self.assertEqual(build(old)[A]["follows"], [])

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

    def test_awaited_follows_forwarded_links_and_holders_but_not_children(self):
        # 2026-10-19 の my_notes: 部署が段取りに入れるのを頼み（A）、段取りは持ち主への問い（B。社長室が受けた）を担当者に書いて返した。
        # 社長室は B を受けたまま別件（D）を出し続けたので、子までたどる open は B が閉じた後も閉じなかった（受付 2a2001）
        desk = {"name": "社長室", "place": "/co/desk"}
        rows = [ask(A, 1), ask(B, 2, frm={"name": "段取り", "place": "/co"}),
                {"id": "f", "kind": "deliver", "ask": A, "at": 3, "status": "sent", "holders": [{"holder": B, "ask": B}]},
                ask(D, 4, frm=desk, cause=B)]
        view = ledger.build(ledger.merge(rows))
        self.assertEqual(ledger.awaited(view, A), [B])
        rows.append({"id": "g", "kind": "deliver", "ask": B, "at": 5, "status": "sent"})
        view = ledger.build(ledger.merge(rows))
        self.assertEqual(ledger.awaited(view, A), [])
        self.assertTrue(view["tasks"][A]["open"])   # --todo は B の子の D まで開いていると出す
        # 回して閉じた頼みは回した先をたどる。知らない受付は空
        rows = [ask(A, 1), {"id": A, "kind": "forwarded", "at": 2, "child": B}, ask(B, 2)]
        self.assertEqual(ledger.awaited(ledger.build(ledger.merge(rows)), A), [B])
        self.assertEqual(ledger.awaited(ledger.build(ledger.merge(rows)), "x"), [])

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
        aliases = {p: {a.asname: a.name for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) for a in n.names if a.asname}
                   for p, tree in trees.items()}
        def value(p, v):
            if isinstance(v, ast.Constant):
                return v.value
            if isinstance(v, ast.Name):
                return consts.get((p.stem, v.id), v.id)
            if isinstance(v, ast.Attribute) and isinstance(v.value, ast.Name):   # import の別名（from nodes import handover as ho）も引く
                mod = aliases[p].get(v.value.id, v.value.id)
                return consts.get((mod, v.attr), ast.unparse(v))
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

    def test_task_title_is_not_the_name_of_a_heading(self):
        """段取りの頼みは「## 困りごと」の見出しから始まる。見出し・誰からの何かだけを言う文・項目名を題にせず、中身の最初の文を題にする。"""
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d, "a.md")
            for text in ("## 困りごと\n--todo の題が見出しの名前になる。持ち主が聞いた。\n\n## 目的\n分かる\n",
                         "## 困っていること（今壊れている）\n- --todo の題が見出しの名前になる。\n",
                         "社長室からの頼みです（穴の直し。急ぎ）。\n\n## 困りごと\n--todo の題が見出しの名前になる\n",
                         "段取りからの頼みです。困っていること: --todo の題が見出しの名前になる。続き\n",
                         "知らせです（返事は要りません）。--todo の題が見出しの名前になる。\n",
                         "社長室からの頼みです。\n困っていること:\n--todo の題が見出しの名前になる。\n"):
                p.write_text(text, encoding="utf-8")
                self.assertEqual(deliver.task_title(str(p)), "--todo の題が見出しの名前になる", text)
            p.write_text("## 困りごと\n0.66.2 の題を直す\n", encoding="utf-8")
            self.assertEqual(deliver.task_title(str(p)), "0.66.2 の題を直す")
            p.write_text("## 困りごと\n1. 題を直す\n", encoding="utf-8")
            self.assertEqual(deliver.task_title(str(p)), "題を直す")
            p.write_text("## 困りごと\np1からp3へ\n", encoding="utf-8")
            self.assertEqual(deliver.task_title(str(p)), "p1からp3へ")
            p.write_text("## 困りごと\n", encoding="utf-8")
            self.assertEqual(deliver.task_title(str(p)), "困りごと")
            p.write_text("## 困りごと\n" + "あ" * 70 + "。\n", encoding="utf-8")
            self.assertEqual(deliver.task_title(str(p)), "あ" * 60 + "…")

    def test_task_title_takes_the_first_owner_words(self):
        with tempfile.TemporaryDirectory() as d:
            p = pathlib.Path(d, "a.md")
            p.write_text("持ち主の頼みです（社長室から）。\n\n## 持ち主の言葉\n- 「台帳から木を作って」\n- 「次」\n", encoding="utf-8")
            self.assertEqual(deliver.task_title(str(p)), "台帳から木を作って")
            p.write_text("頼み: ブランチを直す\n\n本文\n", encoding="utf-8")
            self.assertEqual(deliver.task_title(str(p)), "ブランチを直す")
            p.write_text("持ち主の頼みです（社長室から）。\n\n持ち主の言葉（そのまま）:「p3 に張り替えて。」\n", encoding="utf-8")
            self.assertEqual(deliver.task_title(str(p)), "p3 に張り替えて。")
            p.write_text("持ち主の頼みです（社長室から）。\n\n持ち主の言葉（そのまま）:\n「都度が何個かあるけど「動いて」ないね」（補足）\n", encoding="utf-8")
            self.assertEqual(deliver.task_title(str(p)), "都度が何個かあるけど「動いて」ないね")
            p.write_text("## 持ち主の言葉\n「困りごと」が題になる\n", encoding="utf-8")
            self.assertEqual(deliver.task_title(str(p)), "「困りごと」が題になる")
            p.write_text("## 持ち主の言葉\n「閉じの無い言葉\n", encoding="utf-8")
            self.assertEqual(deliver.task_title(str(p)), "閉じの無い言葉")
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
        self.queued_c = self.theirs / "queue" / "k" / f"{C}.json"   # C は本当に順番待ちに在る
        self.queued_c.parent.mkdir(parents=True)
        self.queued_c.write_text(json.dumps({"id": C}), encoding="utf-8")
        self.root = root
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
        a = argparse.Namespace(**{"todo": "", "all": False, "json": False, "html": None, "state": None, "to": None, **kw})
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
        lines = [re.sub(r"  \d{8}-\d{6}-[0-9a-f]{6}  .*$", "", x) for x in out.splitlines()[2:]]
        self.assertEqual(lines, ["- [済] 木を作る", "  - [済] ブランチを直す", "    → 続き: " + C, "- [順番待ち] （題なし）"])
        rc, out = self.run_todo(json=True)
        got = json.loads(out)
        self.assertEqual(schemacheck.check(got, schemacheck.schema("todo")), [])
        self.assertEqual([n["task"]["id"] for n in got["forest"]], [A, C])
        rc, out = self.run_todo(todo="bbbbbb")
        self.assertTrue(out.splitlines()[2].startswith(f"- [済] ブランチを直す  {B}"), out)
        self.assertEqual(self.run_todo(todo="zzzzzz")[0], 2)

    def test_counts_states_done_ratio_and_the_stalest_open_ask(self):
        self.ports.now = lambda: 4 + 3 * 86400
        rc, out = self.run_todo()
        self.assertEqual(out.splitlines()[0], "件数: 順番待ち 1・動いている 0・答え待ち 0・済 2・取り下げ 0・届かず 0（全 3 件、済の割合 67%）"
                                              f"。開いている頼みでいちばん動きの無い物: {C}（3 日前に更新）")
        got = json.loads(self.run_todo(json=True)[1])
        self.assertEqual(schemacheck.check(got, schemacheck.schema("todo")), [])
        self.assertEqual((got["summary"]["total"], got["summary"]["done_ratio"], got["summary"]["oldest_open"]["id"], got["summary"]["filter"]),
                         (3, 0.667, C, None))
        # 受付を渡せば、その頼みと子だけを数える（続きは数えない）
        got = json.loads(self.run_todo(todo="bbbbbb", json=True)[1])["summary"]
        self.assertEqual((got["total"], got["counts"]["done"], got["done_ratio"]), (1, 1, 1.0))

    def test_filters_by_state_and_destination_into_a_flat_list(self):
        self.ports.now = lambda: 5 + 3600
        def ids(**kw):
            rc, out = self.run_todo(**kw)
            self.assertEqual(rc, 0, out)
            return re.findall(r"^- \[[^]]+\] .*?  (\d{8}-\d{6}-[0-9a-f]{6})  ", out, re.M)
        self.assertEqual(ids(to="調べ"), [C])                    # --state を省けば開いている物だけ
        self.assertEqual(ids(to="調べ", all=True), [C, A])       # 更新の古い順
        self.assertEqual(ids(to="theirs/作業", all=True), [B])
        self.assertEqual(ids(state="済"), [B, A])
        self.assertEqual(ids(state="done,queued"), [B, C, A])
        self.assertEqual(ids(to="nobody"), [])
        rc, out = self.run_todo(to="調べ", all=True)
        self.assertIn("件数: 順番待ち 1・動いている 0・答え待ち 0・済 1・", out)   # 数えは宛先で絞った範囲
        self.assertIn(f"{C}  {todo.when(4)}  宛先 co/調べ  1 時間前", out)
        got = json.loads(self.run_todo(state="queued", to="調べ", json=True)[1])
        self.assertEqual(schemacheck.check(got, schemacheck.schema("todo")), [])
        self.assertEqual(([n["task"]["id"] for n in got["forest"]], got["summary"]["filter"]), ([C], {"states": ["queued"], "to": "調べ"}))
        rc, out = self.run_todo(state="済,bogus")
        self.assertEqual(rc, 2)
        self.assertIn("知らない状態", out)
        page = pathlib.Path(self.tmp.name, "f.html")
        self.assertEqual(self.run_todo(state="済", html=str(page))[0], 0)
        text = page.read_text(encoding="utf-8")
        self.assertIn("絞り込む前の範囲の件数: 順番待ち 1", text)
        self.assertIn(f'class="task s-done closed" id="t-{A}"', text)   # 平らな一覧では、続きが開いていても自分の状態で済と出す
        self.assertNotIn(f'href="#t-{C}"', text)                         # 一覧に無い続きへは飛ばない
        self.assertIn("ブランチを直す", text)
        self.assertNotIn('class="hide"', text)

    def test_notes_open_asks_with_nothing_behind_them(self):
        # 台帳では開いているのに、順番待ちの件が手で動かされた物（my_notes の 5b3433 など 6 件）と、受けた作業場が納品せずに
        # 消えた物（my_notes の 75aeee）。木には今までどおり出し、頭の注記で --withdraw を指す
        gone = str(self.root / "theirs" / "gone")
        self.write(self.mine, [ask(D, 6, to={"company": "theirs", "name": "点検", "path": gone})])
        rc, out = self.run_todo()
        self.assertEqual([x for x in out.splitlines() if x.startswith("!")],
                         [f"! 受付 {D} は動いていると出るが、受けた作業場 {gone} がもう無い（--withdraw {D} で閉じる）"])
        self.queued_c.unlink()
        rc, out = self.run_todo()
        self.assertIn(f"! 受付 {C} は順番待ちと出るが、どの順番待ちの置き場にも無い（--withdraw {C} で閉じる）", out)

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
