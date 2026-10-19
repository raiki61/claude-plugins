"""依頼と納品（会社の形の設計 4.5・4.10 の 3）: deliver ノード、orders の --ask・--deliver の流れ、Stop フック。
git は一時のフォルダの本物、herdr・claude は偽物で回す。"""

import argparse
import contextlib
import io
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from . import DISPATCH
from .test_company import CompanyHerdr
from .test_dispatch import FakePorts, gitx_source, make_cfg, run_main
from .test_provision import git
from .test_task import push_shape
from . import test_role
import gitx
import claudex
import herdr as real_herdr
import orders
import wake_hook
from nodes import deliver, ledger, provision, wake


def dept_row(name=None, role=None, lifecycle=None, session=None, panes=(), branch="b", path="/x"):
    attrs = {k: v for k, v in (("name", name), ("role", role), ("lifecycle", lifecycle), ("session", session)) if v}
    return {"path": path, "branch": branch, "attrs": attrs, "panes": list(panes)}


def company(name, root, *depts):
    return {"name": name, "root": root, "departments": list(depts)}


GOOD = """+++
open = []
+++
## 結論
直した。
試験は緑。

## 決め手
「要約なしで終われない」 https://example.com/spec
"""
ONE_OPEN = '+++\n[[open]]\nquestion = "測り直す"\n+++'   # GOOD の頭書きを替える残った疑問 1 件（担当者無し）


class Target(unittest.TestCase):
    def setUp(self):
        self.a = company("a", "/r/a", dept_row(name="調べ", role="調べ役", path="/r/a-w1"),
                         dept_row(name="出荷", role="出荷役", lifecycle="persistent", path="/r/a-w2"))
        self.b = company("b", "/r/b", dept_row(name="出荷b", role="出荷役", path="/r/b-w1"))

    def test_parse_target(self):
        self.assertEqual(deliver.parse_target("a/出荷役"), ("a", "出荷役"))
        self.assertEqual(deliver.parse_target("出荷役"), (None, "出荷役"))
        with self.assertRaises(deliver.DeliverError):
            deliver.parse_target("a/")

    def test_department_name_wins_anywhere_and_role_goes_to_the_resident(self):
        got = deliver.find_target([self.a, self.b], "/r/a", "出荷b")
        self.assertEqual((got["company"]["name"], got["department"]["path"]), ("b", "/r/b-w1"))
        got = deliver.find_target([self.a, self.b], "/r/b", "a/出荷役")
        self.assertEqual(got["department"]["path"], "/r/a-w2")

    def test_role_without_a_resident_department_means_a_new_one(self):
        got = deliver.find_target([self.a, self.b], "/r/b", "出荷役")   # b の出荷役はエフェメラルの部署
        self.assertEqual((got["company"]["name"], got["department"], got["role"]), ("b", None, "出荷役"))

    def test_unknown_company_and_twin_names_stop(self):
        with self.assertRaises(deliver.DeliverError) as e:
            deliver.find_target([self.a], "/r/a", "zz/出荷役")
        self.assertIn("herdr に開いていない", str(e.exception))
        twin = company("c", "/r/c", dept_row(name="調べ", path="/r/c-w"))
        with self.assertRaises(deliver.DeliverError):
            deliver.find_target([self.a, twin], "/r/a", "調べ")
        self.assertEqual(deliver.find_target([self.a, twin], "/r/a", "c/調べ")["department"]["path"], "/r/c-w")
        same = company("c", "/r/c", dept_row(name="調べ", path="/r/c-w"), dept_row(name="調べ", branch=None, path="/t/tree"))
        with self.assertRaises(deliver.DeliverError) as e:
            deliver.find_target([same], "/r/c", "c/調べ")   # 同じ会社の中の重なりは、会社を添えても分けられない
        self.assertIn("c/（ブランチ無し） /t/tree", str(e.exception))
        self.assertIn("宛て方では分けられない", str(e.exception))


    def test_a_company_name_alone_goes_to_its_desk(self):
        # 部署でない会話は、宛先の会社の窓口の役の名前を知らなくても、会社の名前で頼める
        desk = {**dept_row(name="段取り", role="段取り", lifecycle="persistent", path="/r/n"), "head_office": True}
        notes = {**company("my_notes", "/r/n", desk, dept_row(name="調べもの", role="担当", path="/r/n-w")), "info_source": "origin"}
        a = {**self.a, "info_source": "repo"}
        got = deliver.find_target([a, notes], "/r/a", "my_notes")
        self.assertEqual((got["company"]["name"], got["department"]["path"], got["role"]), ("my_notes", "/r/n", "段取り"))
        with self.assertRaises(deliver.DeliverError) as e:   # 窓口を名付けていない会社
            deliver.find_target([a, notes], "/r/n", "a")
        self.assertIn("窓口が名付けられていない", str(e.exception))
        # 会社の形の無いリポジトリの名前は会社に当たらず、今までどおり頼む側の会社の役で宛てる
        plain = company("出荷役", "/r/出荷役")
        self.assertEqual(deliver.find_target([a, plain], "/r/a", "出荷役")["department"]["path"], "/r/a-w2")
        # 部署の名前は会社の名前より先に当たる
        named = company("c", "/r/c", dept_row(name="my_notes", role="担当", path="/r/c-w"))
        self.assertEqual(deliver.find_target([a, notes, named], "/r/a", "my_notes")["department"]["path"], "/r/c-w")
        twin = {**company("my_notes", "/s/my_notes", desk), "info_source": "origin"}   # 同じ会社を別の所にも clone した
        with self.assertRaises(deliver.DeliverError) as e:
            deliver.find_target([a, notes, twin], "/r/a", "my_notes")
        self.assertIn("2 つ以上ある", str(e.exception))

    def test_a_company_name_alone_goes_to_the_desk_written_in_its_shape_and_skips_a_bare_clone(self):
        # claude-plugins の窓口は my_notes の段取りが兼ねる（会社の形の desk）。部署を立てていない別の clone（claude-plugins-work1）は
        # 同じ名前でも会社に数えない（2026-10-17、--ask claude-plugins が「2 つ以上ある」で止まった。415c94）
        desk = {**dept_row(name="段取り", role="段取り", lifecycle="persistent", path="/r/n"), "head_office": True}
        notes = {**company("my_notes", "/r/n", desk), "info_source": "origin"}
        plugins = {**company("claude-plugins", "/r/cp", {**dept_row(path="/r/cp"), "head_office": True},
                             dept_row(name="割り振り", role="担当", path="/r/cp-w")), "info_source": "origin", "desk_of": "my_notes/段取り"}
        bare = {**company("claude-plugins", "/r/cp-work1", {**dept_row(path="/r/cp-work1"), "head_office": True}),
                "info_source": "origin", "desk_of": "my_notes/段取り"}
        got = deliver.find_target([notes, plugins, bare], "/r/n", "claude-plugins")
        self.assertEqual((got["company"]["name"], got["department"]["path"], got["role"]), ("my_notes", "/r/n", "段取り"))
        self.assertIn("会社の形の desk", got["via"])
        for far in ("claude-plugins", "my_notes/無い窓口"):   # 書いた先が部署の名前で当たらなければ、役の道に落とさずに止める
            with self.assertRaises(deliver.DeliverError) as e:
                deliver.find_target([notes, {**plugins, "desk_of": far}], "/r/n", "claude-plugins")
            self.assertIn("その窓口が見つからない", str(e.exception))

    def test_company_and_role_with_two_clones_uses_the_one_with_departments_or_stops(self):
        # 「会社/役」は先頭の clone に頼んでいた。herdr の開いた順で、部署を立てていない clone に新しい部署が立ちえた
        plugins = company("claude-plugins", "/r/cp", dept_row(name="割り振り", role="担当", path="/r/cp-w"))
        bare = company("claude-plugins", "/r/cp-work1")
        for order in ([bare, plugins], [plugins, bare]):
            self.assertEqual(deliver.find_target(order, "/r/n", "claude-plugins/作業")["company"]["root"], "/r/cp")
        other = company("claude-plugins", "/r/cp2", dept_row(name="調べ", role="作業", path="/r/cp2-w"))
        with self.assertRaises(deliver.DeliverError) as e:
            deliver.find_target([plugins, other], "/r/n", "claude-plugins/作業")
        self.assertIn("2 つ以上ある", str(e.exception))


class Holders(unittest.TestCase):
    """残った疑問の担当者の検査（役の holders・ask_holders。my_notes の tools/deliver_check.py から移した。24e521）。残った疑問は頭書きの
    open に構造で書く（受付 b0df65）。担当者は受付番号・持ち主の 2 つの値・頼み元の名前だけ（部署の名前は --todo が追えない。受付 b6778d）。"""

    def test_each_question_needs_a_holder_that_the_ledger_can_follow(self):
        ok = [{"question": "測り直す", "holder": "20261018-120448-b6778d"}, {"question": "どれを採るか", "holder": "owner:choose"},
              {"question": "消してよいか", "holder": "owner:confirm"}, {"question": "次を回す", "holder": "段取り"}]
        self.assertEqual(deliver.holder_problems(ok, ["社長室"], "段取り"), [])
        self.assertEqual(deliver.holder_problems([], ["社長室"], "段取り"), [])
        bad = deliver.holder_problems([{"question": "担当者の無い疑問"}, {"question": "部署へ", "holder": "割り振り"},
                                       {"question": "中継", "holder": "社長室"}, {"question": "持ち主", "holder": "持ち主"},
                                       {"question": "番号の混ざった字", "holder": "割り振り（受付 20261018-120448-b6778d）"}],
                                      ["社長室"], "段取り")
        self.assertEqual(len(bad), 5, bad)
        self.assertIn("担当者（holder）が無い: 担当者の無い疑問", bad[0])
        self.assertIn("受付番号・owner:choose・owner:confirm・段取り のどれでもない", bad[1])
        # 頼み元が持ち主への中継なら、頼み元の名前も担当者に書けない
        self.assertEqual(len(deliver.holder_problems([{"question": "q", "holder": "社長室"}], ["社長室"], "社長室")), 1)

    def test_an_ask_id_holder_must_be_in_a_ledger(self):
        # --ask の出力を待たずに書いた番号は、どの台帳にも無く --todo が追えない（my_notes の受付 20261019-022419-b50f85）
        qs = [{"question": "回した", "holder": "20261018-224301-4e6a26"}, {"question": "待たずに書いた", "holder": "20261018-224226-c5ec66"},
              {"question": "選ぶ", "holder": "owner:choose"}]
        self.assertEqual(deliver.unknown_asks(qs, {"20261018-224301-4e6a26"}),
                         ["担当者の受付 20261018-224226-c5ec66 は、たどった受付箱の台帳のどれにも無いか、届かなかった頼み（--ask の出力の受付番号を写す）: 待たずに書いた"])

    def test_the_front_matter_is_toml_between_plus_lines_and_unknown_fields_stop(self):
        data, body, bad = deliver.front('+++\ntitle = "題"\n[[open]]\nquestion = "q"\nholder = "owner:choose"\n+++\n\n## 結論\nx\n')
        self.assertEqual((data, body, bad), ({"title": "題", "open": [{"question": "q", "holder": "owner:choose"}]}, "## 結論\nx\n", []))
        self.assertEqual(deliver.front("## 結論\nx"), ({}, "## 結論\nx", []))
        self.assertIn("閉じの +++", deliver.front("+++\nopen = []\n## 結論")[2][0])
        self.assertIn("TOML として読めない", deliver.front("+++\nopen = [\n+++\n")[2][0])
        self.assertEqual(deliver.front_problems({"open": [], "title": "t"}, deliver.ASK_FIELDS), [])
        # 頼みの種類（type）は task か question だけ。省けば task（受付 5e6029）
        self.assertEqual(deliver.front_problems({"title": "t", "type": "question"}, deliver.ASK_FIELDS), [])
        self.assertIn("type は task・question", deliver.front_problems({"title": "t", "type": "notice"}, deliver.ASK_FIELDS)[0])
        self.assertIn("type は task・question", deliver.front_problems({"title": "t", "type": ["question"]}, deliver.ASK_FIELDS)[0])
        self.assertEqual((deliver.ask_type_of({}), deliver.ask_type_of({"type": "question"})), ("task", "question"))
        bad = deliver.front_problems({"title": "t", "holders": 1, "open": [{"question": "", "who": "x", "holder": 3}]},
                                     deliver.DELIVER_FIELDS)
        self.assertEqual(len(bad), 5, bad)   # 納品に title は無い・知らないフィールド holders・件の知らないフィールド who・空の question・文字列でない holder
        self.assertIn("表の並び", deliver.front_problems({"open": "なし"}, deliver.DELIVER_FIELDS)[0])

    def test_questions_are_rendered_for_the_summary_and_the_ledger(self):
        qs = [{"question": "どれを採るか", "holder": "owner:choose"}, {"question": "測る", "holder": "20261018-120448-b6778d"}]
        self.assertEqual(deliver.render_open(qs), "- どれを採るか 担当者: 持ち主（価値で選ぶ）\n- 測る 担当者: 20261018-120448-b6778d")
        self.assertEqual(deliver.render_open([]), "なし")
        self.assertEqual(deliver.holders_of(qs), [{"holder": "持ち主（価値で選ぶ）", "ask": None},
                                                  {"holder": "20261018-120448-b6778d", "ask": "20261018-120448-b6778d"}])
        # 描いた字は、頭書きの無い古い要約の読み手（--todo の古い行と my_notes の納品のゲート）でも同じ担当者に読める
        self.assertEqual(deliver.open_holders(deliver.render_open(qs)), deliver.holders_of(qs))
        self.assertEqual(deliver.open_holders(deliver.render_open([])), [])

    def test_an_ask_title_comes_from_the_front_matter_or_a_one_line_body(self):
        self.assertEqual(deliver.ask_title_of('+++\ntitle = "題"\n+++\n## 困りごと\n本文'), "題")
        self.assertEqual(deliver.ask_title_of("直して"), "直して")
        self.assertIsNone(deliver.ask_title_of("## 困りごと\n本文"))
        # 回す側の添え書きは頭書きの後ろに置く（頭書きは本文の頭に残る）
        wrapped = deliver.wrap("段取りが回した", '+++\ntitle = "題"\n+++\n## 困りごと\n本文')
        self.assertEqual(deliver.ask_title_of(wrapped), "題")
        self.assertIn("段取りが回した\n\n---\n\n## 困りごと", wrapped)
        self.assertEqual(deliver.wrap("添え書き", "本文"), "添え書き\n\n---\n\n本文")

    def test_old_summaries_are_still_read_for_the_ledger(self):
        # 頭書きの無い古い要約（台帳に今ある物）は、--todo が holders の無い古い行のために文から読む。前の名前「持ち手」も読む
        # （前の名前は、語の置き換え〔terms.py --fix〕に書き換えられないように字の番号で書く）
        old = "\u6301\u3061\u624b"
        text = f"- 測る。{old}: 割り振り\n- 回した。担当者: 20261018-031120-52e05e"
        self.assertEqual([x["ask"] for x in deliver.open_holders(text)], [None, "20261018-031120-52e05e"])
        for none in ("なし", "- なし", "ありません", "無し。https://x.example/?a=1"):
            self.assertEqual(deliver.open_holders(none), [], none)
        self.assertEqual(deliver.unsure_problems({"結論": "直した（要確認）", deliver.OPEN: "要確認。担当者: 割り振り"}),
                         ["「結論」に「要確認」がある。頭書きの [[open]] に移して holder（担当者）を付ける"])

    def test_the_role_reads_holders_as_off_true_or_relay_names(self):
        import tomllib
        from nodes import role
        path = pathlib.Path(tempfile.mkdtemp(), "c.toml")
        path.write_text('[[roles]]\nname = "担当"\nholders = ["社長室"]\n[[roles]]\nname = "相談"\nask_holders = true\n'
                        '[[roles]]\nname = "作業"\n', encoding="utf-8")
        got = role.load(str(path), path.read_text(encoding="utf-8"))["roles"]
        self.assertEqual((got["担当"]["holders"], got["相談"]["ask_holders"], got["作業"]["holders"]), (["社長室"], [], None))


class Summary(unittest.TestCase):
    def test_headings_and_labels_are_read(self):
        got = deliver.parse("結論: 直した\n**決め手**：原文 https://x.example\n## 残った疑問\nなし\n## 補足\n関係ない",
                            deliver.DEFAULT_ITEMS)
        # 決まった項目の外の見出し（補足）も落とさない（受付 6a65a9）
        self.assertEqual(got, {"結論": "直した", "決め手": "原文 https://x.example", "残った疑問": "なし", "補足": "関係ない"})

    def test_deeper_headings_and_code_blocks_stay_in_the_item_and_english_names_are_read(self):
        text = "## Conclusion\na\n### 小見出し\nb\n```\n## コードの中\n```\n## 参考になりうる点\nc\n## evidence\nhttps://x.example"
        self.assertEqual(deliver.parse(text, deliver.DEFAULT_ITEMS),
                         {"結論": "a\n### 小見出し\nb\n```\n## コードの中\n```", "参考になりうる点": "c", "決め手": "https://x.example"})
        self.assertEqual(deliver.parse("前置き\n## 結論\nx", deliver.DEFAULT_ITEMS), {deliver.PREAMBLE: "前置き", "結論": "x"})
        # 題の見出しの下の項目も、深い見出しで書いた残った疑問も、空白の無い「##結論」も項目に読む（黙って前の項目に入れない）
        self.assertEqual(deliver.parse("# 納品の要約\n## 結論\na\n### 残った疑問\nb\n##決め手\nc", deliver.DEFAULT_ITEMS),
                         {"納品の要約": "", "結論": "a", deliver.OPEN: "b", "決め手": "c"})
        # 英語の名前は見出しだけ（本文の「Branch: …」の行で項目を切り替えない）
        self.assertEqual(deliver.parse("## 結論\nBranch: main に入れた", deliver.DEFAULT_ITEMS), {"結論": "Branch: main に入れた"})
        self.assertEqual(deliver.front("\ufeff+++\nopen = []\n+++\n## 結論\nx")[0], {"open": []})
        self.assertIsNone(deliver.ask_title_of("## 直して"))
        self.assertEqual(deliver.ask_title_of("あ" * 70), "あ" * 60 + "…")

    def test_check_names_what_is_missing(self):
        items = {**deliver.parse(deliver.front(GOOD)[1], deliver.DEFAULT_ITEMS), deliver.OPEN: deliver.render_open([])}
        self.assertEqual(deliver.check(items, ["結論", "決め手", "残った疑問"]), [])
        self.assertIn("頭書きの open が無い", deliver.check({}, [deliver.OPEN])[0])
        self.assertEqual(deliver.check({**items, "結論": "1\n2\n3\n4"}, ["結論"]), ["結論（3 行を超える）"])
        self.assertEqual(deliver.check({**items, "決め手": "原文だけ"}, ["決め手"]), ["決め手（原典の URL が無い）"])
        self.assertEqual(deliver.check(items, ["ブランチ", "試験"]), ["ブランチ（無いか空）", "試験（無いか空）"])

    def test_required_items_come_from_the_role_or_default(self):
        self.assertEqual(deliver.required_items(None), list(deliver.DEFAULT_ITEMS))
        self.assertEqual(deliver.required_items({"name": "サブエージェント", "deliver": None}), list(deliver.DEFAULT_ITEMS))
        self.assertEqual(deliver.required_items({"name": "サブエージェント", "deliver": ["結論", "差分", "試験"]}), ["結論", "差分", "試験"])

    def test_the_former_branch_item_name_is_read_as_the_current_one(self):
        # 前の名前「枝」の見出しと、会社の形の deliver に残った「枝」は、今の名前「ブランチ」に読む（前の名前は字の番号で書く）
        old = "\u679d"
        got = deliver.parse(f"## 結論\n直した\n## {old}\nfix/a", deliver.DEFAULT_ITEMS)
        self.assertEqual(got, {"結論": "直した", deliver.BRANCH_ITEM: "fix/a"})
        self.assertEqual(deliver.required_items({"name": "担当", "deliver": ["結論", old]}), ["結論", deliver.BRANCH_ITEM])

    def test_short_text_is_typed_and_long_text_points_at_the_file(self):
        line = deliver.ask_line("id1", "desk", "直して", "/i/id1-ask.md", ["結論"], "py /p/dispatch.py")
        self.assertTrue(line.startswith("頼みです（受付 id1、desk から）: 直して 終わったら"))
        self.assertIn("py /p/dispatch.py --deliver <要約のファイル>", line)
        line = deliver.ask_line("id1", "desk", "一\n二", "/i/id1-ask.md", ["結論"], "py /p/dispatch.py")
        self.assertIn("/i/id1-ask.md を読んで", line)
        self.assertNotIn("\n", line)


class TypedBox(unittest.TestCase):
    """入力フィールドの、人が打った字（claudex.typed）。薄字（SGR 2）は Claude Code の次の文の候補と空の入力フィールドの例の字で、数えない。"""

    def box(self, inner):
        rule = "\x1b[38;2;136;136;136m" + "─" * 20 + "\x1b[0m"
        return claudex.typed(f"上の字\n{rule}\n❯\xa0{inner}\n{rule}\n  足元")

    def test_faint_text_is_not_typed_but_colored_text_is(self):
        self.assertEqual(self.box("\x1b[0m\x1b[2m消していいよ\x1b[0m"), "")
        self.assertEqual(self.box("\x1b[2mTry \"edit <filepath> to...\"\x1b[0m"), "")
        self.assertEqual(self.box("打ちかけ"), "打ちかけ")
        self.assertEqual(self.box("[Pasted text #1 +30 lines]"), "[Pasted text #1 +30 lines]")
        # 色の指定の中の 2（38;2;r;g;b・38;5;n）は薄字でない（色の付いた打ちかけを消さない）
        self.assertEqual(self.box("\x1b[38;2;253;93;177m! ls\x1b[39m"), "! ls")
        self.assertEqual(self.box("\x1b[38;5;2m緑\x1b[0m"), "緑")
        self.assertEqual(self.box("\x1b[0;2m候補\x1b[22m打った"), "打った")
        self.assertEqual(self.box(""), "")
        self.assertEqual(self.box("\x1b[4:3m波線\x1b[0m\x1b[0 q"), "波線")   # コロン区切りと中間の字の付いた制御も字に数えない
        self.assertIsNone(claudex.typed("罫線の無い画面"))
        self.assertEqual(claudex.typed("─" * 20 + "\n❯ 字だけの画面\n" + "─" * 20), "字だけの画面")   # 色の無い画面は全部を数える


class BossWindow(unittest.TestCase):
    def test_department_window_then_matching_mark_then_the_pane_at_ask_time(self):
        boss_dept = dept_row(session="s-boss", panes=[{"pane_id": "P9", "agent": "claude"}])
        self.assertEqual(deliver.boss_window({}, "s-boss", None, [], [company("a", "/r", boss_dept)]), ("P9", "部署の窓"))
        panes = [{"pane_id": "P1", "agent": "claude", "cwd": "/r/w", "agent_session": "s-boss"},
                 {"pane_id": "P2", "agent": "claude", "cwd": "/r/home", "agent_session": "s-boss"}]
        # herdr は attach の窓に別の会話の印を付けることがある。場所が会話と合うペインだけを使う
        self.assertEqual(deliver.boss_window({}, "s-boss", {"cwd": "/r/home"}, panes, []), ("P2", "会話の印"))
        self.assertEqual(deliver.boss_window({"boss-pane": "P1"}, "s-x", None, panes, [])[0], "P1")
        pane, why = deliver.boss_window({}, None, None, panes, [])
        self.assertIsNone(pane)
        self.assertIn("分からない", why)

    def test_boss_session_by_name_only_when_it_is_one(self):
        sessions = {"m": [{"sessionId": "s1", "name": "desk", "state": "working"},
                          {"sessionId": "s0", "name": "desk", "state": "done"}]}
        self.assertEqual(deliver.boss_session({"boss": "desk", "boss-account": "m"}, sessions)[0], "s1")
        sessions["m"].append({"sessionId": "s2", "name": "desk"})
        self.assertEqual(deliver.boss_session({"boss": "desk", "boss-account": "m"}, sessions), (None, None))
        self.assertEqual(deliver.boss_session({"boss-session": "s2", "boss-account": "m"}, sessions)[0], "s2")

    def test_boss_session_takes_the_current_process_of_a_resumed_session(self):
        old = {"pid": 1, "startedAt": 100, "sessionId": "s1", "name": "desk", "cwd": "/old"}
        new = {"pid": 2, "startedAt": 200, "sessionId": "s1", "name": "desk", "cwd": "/new"}
        sessions = {"m": [old, new]}
        self.assertEqual(deliver.boss_session({"boss-session": "s1", "boss-account": "m"}, sessions), ("s1", new))
        # 名前で引くときも、同じ id の 2 件は 1 つの会話に数える
        self.assertEqual(deliver.boss_session({"boss": "desk", "boss-account": "m"}, sessions), ("s1", new))


class StopVerdict(unittest.TestCase):
    ATTRS = {"role": "サブエージェント", "ask": "id1", "session": "s1", "boss": "desk"}

    def test_blocks_only_an_undelivered_ask_in_its_own_conversation_up_to_the_limit(self):
        self.assertIn("受付 id1", deliver.stop_verdict({"session_id": "s1"}, self.ATTRS, 0, "/d.py"))
        self.assertIsNone(deliver.stop_verdict({"session_id": "s1"}, {}, 0, "/d.py"))
        self.assertIsNone(deliver.stop_verdict({"session_id": "s1"}, {"ask": "id1"}, 0, "/d.py"))   # 部署でない
        self.assertIsNone(deliver.stop_verdict({"session_id": "s1"}, {**self.ATTRS, "delivered": "id1"}, 0, "/d.py"))
        self.assertIsNone(deliver.stop_verdict({"session_id": "other"}, self.ATTRS, 0, "/d.py"))
        self.assertIsNone(deliver.stop_verdict({"session_id": "s1"}, self.ATTRS, deliver.STOP_LIMIT, "/d.py"))
        # --wait で人の答え待ちにした頼みは促さない。前の頼みの印が残っていても、今の頼みは促す
        self.assertIsNone(deliver.stop_verdict({"session_id": "s1"}, {**self.ATTRS, "waiting": "id1"}, 0, "/d.py"))
        self.assertIn("受付 id1", deliver.stop_verdict({"session_id": "s1"}, {**self.ATTRS, "waiting": "id0"}, 0, "/d.py"))

    def test_names_the_ask_file_so_a_talk_that_missed_the_ask_can_read_it(self):
        # 渡した字が会話に届かなくても、差し戻しから本文へたどれる（my_notes の受付 4bae53）
        inbox = tempfile.mkdtemp()
        attrs = {**self.ATTRS, "boss-inbox": inbox}
        self.assertNotIn("本文は", deliver.stop_verdict({"session_id": "s1"}, attrs, 0, "/d.py"))   # 本文の無い場所は書かない
        file = os.path.join(inbox, "id1-ask.md")
        pathlib.Path(file).write_text("頼み", encoding="utf-8")
        self.assertIn(f"本文は {file}", deliver.stop_verdict({"session_id": "s1"}, attrs, 0, "/d.py"))

    def test_hook_blocks_with_json_then_gives_up_after_the_limit(self):
        tmp = tempfile.mkdtemp()
        payload = json.dumps({"session_id": "s1", "cwd": "/w"})
        outs = []
        for _ in range(deliver.STOP_LIMIT + 1):
            out = io.StringIO()
            self.assertEqual(orders.stop_hook(io.StringIO(payload), out, lambda cwd: dict(self.ATTRS), tmp, lambda: None), 0)
            outs.append(out.getvalue())
        self.assertEqual([json.loads(o)["decision"] for o in outs[:-1]], ["block"] * deliver.STOP_LIMIT)
        self.assertEqual(outs[-1], "")

    def test_plugin_hook_runs_orders_stop_and_is_quiet_outside_a_department(self):
        hooks = json.loads((DISPATCH.parent / "hooks" / "hooks.json").read_text(encoding="utf-8"))["hooks"]
        (command,) = [h["command"] for g in hooks["Stop"] for h in g["hooks"] if not h.get("asyncRewake") and not h.get("async")]
        self.assertIn('"${CLAUDE_PLUGIN_ROOT}/dispatch/orders.py" stop', command)
        plain = tempfile.mkdtemp()
        p = subprocess.run([sys.executable, str(DISPATCH / "orders.py"), "stop"], input=json.dumps({"cwd": plain}),
                           capture_output=True, text=True, encoding="utf-8")
        self.assertEqual((p.returncode, p.stdout), (0, ""), p.stderr)

    def test_hook_does_nothing_outside_a_department(self):
        out = io.StringIO()
        self.assertEqual(orders.stop_hook(io.StringIO(json.dumps({"session_id": "s1", "cwd": "/w"})), out,
                                          lambda cwd: {}, tempfile.mkdtemp(), lambda: None), 0)
        self.assertEqual(out.getvalue(), "")

    def test_waiting_for_background_work_is_not_sent_back(self):
        # ターンを終えて裏の処理（run_in_background の Bash。--land など）を待つ部署は、納品を差し戻さない（終われば会話が起きる）。
        # 待っている印を herdr に出すのは tiers の statusline の受け持ちで、このフックは herdr に書かない（herdr を渡す口も無い）
        attrs = {**self.ATTRS, "lifecycle": "persistent", "fresh": "true", "name": "割り振り"}

        def stop(n):
            out = io.StringIO()
            orders.stop_hook(io.StringIO(json.dumps({"session_id": "s1", "cwd": "/w"})), out, lambda cwd: dict(attrs), tempfile.mkdtemp(),
                             lambda: n)
            return out.getvalue()
        self.assertEqual(stop(1), "")
        self.assertEqual(json.loads(stop(0))["decision"], "block")   # 待ち終えた: 納品していなければ差し戻す

    def test_a_running_background_agent_lets_the_turn_end_and_a_finished_one_does_not(self):
        # 裏で立てたサブエージェント（Agent）は会話のプロセスの子に Bash を残さないので、ps では待っているのが見えず、差し戻された
        # （2026-10-17 の割り振り）。Stop フックの入力の background_tasks が在れば、その running の物で見る
        def stop(payload, shells=lambda: 0):
            out = io.StringIO()
            orders.stop_hook(io.StringIO(json.dumps({"session_id": "s1", "cwd": "/w", **payload})), out,
                             lambda cwd: dict(self.ATTRS), tempfile.mkdtemp(), shells)
            return out.getvalue()
        agent = {"id": "a1", "type": "subagent", "status": "running", "agent_type": "convergence-loops:inspector"}
        self.assertEqual(stop({"background_tasks": [agent]}), "")
        self.assertEqual(json.loads(stop({"background_tasks": []}, shells=lambda: 1))["decision"], "block",
                         "一覧が在れば一覧で見る（空なら裏で動く物は無い）")
        self.assertEqual(json.loads(stop({"background_tasks": [{**agent, "status": "completed"}]}))["decision"], "block")
        self.assertEqual(stop({}, shells=lambda: 1), "", "一覧の無い版では裏の Bash を ps で数える")
        self.assertEqual(json.loads(stop({}, shells=lambda: None))["decision"], "block", "動いているのを確かめられなければ差し戻す")
        self.assertIn("ターンを終えてよい", json.loads(stop({"background_tasks": []}))["reason"])

    @unittest.skipIf(os.name == "nt", "ps の無い Windows では数えない（None を返し、Stop フックは裏の処理の一覧で見る）")
    def test_background_shells_are_the_claude_childs_bash_tool_shells(self):
        # 会話のプロセス（claude）の子のうち、Bash のツールのシェル（シェルの写しを読み込む物）を数える。フック自身の祖先は数えない
        ps = "\n".join([
            "  1     0 /sbin/launchd",
            " 10  1 claude bg-spare --bg-spare /tmp/x.sock",
            " 11 10 caffeinate -i -t 300",
            " 12 10 /bin/bash -c source /h/.claude/shell-snapshots/snapshot-bash-1.sh && sleep 60",
            " 13 10 /bin/bash -c source /h/.claude/shell-snapshots/snapshot-bash-1.sh && bash run-python.sh orders.py stop",
            " 14 13 python3 orders.py stop",
            " 15 10 node mcp-server.js"])
        run = lambda argv, env=None: subprocess.CompletedProcess(argv, 0, ps, "")   # noqa: E731
        self.assertEqual(claudex.background_shells(14, run), 1)
        self.assertIsNone(claudex.background_shells(11 + 100, run), "claude の下でないなら分からない")


class Flow(unittest.TestCase):
    """--ask と --deliver を入口から。頼み元（窓口）は元の clone のペイン P0、部署は worktree の窓 P1。"""

    def setUp(self):
        self.cfg, self.root = make_cfg()
        self.src = gitx_source(self.cfg)
        self.place = str(pathlib.Path(self.root) / "dept")
        git("-C", self.src, "worktree", "add", "-q", "-b", "dept/a", self.place, "origin/main")
        provision.mark(self.place, self.src, {"role": "調べ役", "account": "a1", "name": "調べ", "session": "s-dept"}, gitx)
        self.ports = FakePorts([])
        self.ports.term = CompanyHerdr(self.src)
        self.desk = self.ports.term.open_at(self.src, agent="claude")["pane_id"]
        self.window = self.ports.term.open_at(self.place, agent="claude")["pane_id"]
        self.ports.term.talking.add(self.window)   # 部署の窓の前には attach の画面（会話）が居る
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk", "HERDR_PANE_ID": self.desk}
        # 部署の会話は、窓に 1 行が送られると動き出す（status が busy になる）。--ask は送った後にそれを見て、届いたと確かめる
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"sessionId": "s-desk", "name": "desk", "cwd": self.src, "kind": "interactive", "status": "idle"},
            {"id": "d", "sessionId": "s-dept", "name": "調べ", "cwd": self.place, "kind": "background", "state": "working",
             "status": "busy" if any(w[0] == "prompt" and w[1] != self.desk for w in self.ports.term.writes) else "idle"}]
        self.inbox = os.path.join(self.src, ".git", "company", "inbox")

    def main(self, cwd, *argv):
        with contextlib.chdir(cwd):
            return run_main(["--config", self.cfg, *argv], self.ports)

    def prompts(self):
        return [w for w in self.ports.term.writes if w[0] == "prompt"]

    def fall(self, keep_mark=False):
        """部署の窓の会話が落ちた形（PC の再起動などで attach の画面が終わり、ペインにはシェルだけが居る）。keep_mark なら、
        herdr がペインの会話の印を残したままの形（まっさらな環境での 6 回目の試しの 1）。"""
        self.ports.term.talking.discard(self.window)
        if not keep_mark:
            for p in self.ports.term._panes:
                if p["pane_id"] == self.window:
                    p["agent"] = None
        real_run = self.ports.term.run

        def run(pane, command):   # attach を打つと、窓に会話が戻る
            real_run(pane, command)
            if " attach " in command:
                self.ports.term.talking.add(pane)
                for p in self.ports.term._panes:
                    if p["pane_id"] == pane:
                        p["agent"] = "claude"
        self.ports.term.run = run

    def test_fallen_department_is_attached_again_and_the_ask_goes_through(self):
        self.fall()
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        runs = [w for w in self.ports.term.writes if w[0] == "run"]
        self.assertEqual(runs, [("run", self.window, "claude-a1 attach d")])   # 会話の一覧の短い id で打つ（長い id は断られる）
        self.assertIn("部署の窓に会話が居なかったので", out)
        self.assertEqual(len(self.prompts()), 1)

    @unittest.skipIf(os.name == "nt", "Windows では前に居るプロセスを見る口が当てにならないので見ず、画面の exited の行で見分ける"
                                      "（test_exited_line_on_the_screen_counts_as_fallen）")
    def test_fallen_department_missing_from_the_list_is_attached_by_its_job_id(self):
        # /clear で会話の id が変わっても、裏の会話の短い id（company.job）は変わらない。一覧に見えないときは job で打つ
        # （会話の id の頭の字は /clear の後の id では短い id と合わない）
        provision.mark(self.place, self.src, {"session": "a5b0bc07-new", "job": "8c4a1102"}, gitx)
        self.ports.list_sessions = lambda cdir, include_done=False: []
        self.fall()
        self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertIn(("run", self.window, "claude-a1 attach 8c4a1102"), self.ports.term.writes)

    def test_fallen_department_without_its_talk_id_is_attached_by_the_talk_at_its_place(self):
        # 属性の会話の id が消えていても（前の版の --move が id を消した直後に止められた。2026-10-17 の割り振り・説明書）、会話の
        # 一覧の、部署の場所の裏の会話で戻し、属性を書き戻す
        subprocess.run(["git", "-C", self.place, "config", "--worktree", "--unset", "company.session"], check=True)
        self.fall()
        self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertIn(("run", self.window, "claude-a1 attach d"), self.ports.term.writes)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["session"], attrs["job"]), ("s-dept", "d"))
        old = {"kind": "background", "sessionId": "s-old", "id": "o", "cwd": self.place, "name": "調べ", "state": "done", "startedAt": 9}
        talk = {"kind": "background", "sessionId": "s-now", "id": "n", "cwd": self.place, "name": "調べ", "state": "working", "startedAt": 1}
        here = {"attrs": {"name": "調べ"}, "path": self.place}
        self.assertEqual(orders.place_talk(here, {"a1": [old, talk]}, [])[1]["id"], "n")   # 動いている物を先に
        self.assertEqual(orders.place_talk({**here, "attrs": {"name": "調べ", "account": "a2"}}, {"a1": [talk]}, []), None)
        self.assertIsNone(orders.place_talk({**here, "head_office": True}, {"a1": [talk]}, []))   # 本社は選ばない
        self.ports.list_sessions = lambda cdir, include_done=False: []   # 一覧にも無ければ、今までどおり立て直しを頼む
        self.assertEqual(orders.revive({"attrs": {}, "path": self.place, "panes": []}, [], self.ports, {})[1][:30],
                         "部署の属性に会話の id（company.session）が無く、会話の一覧にも部署の場所の裏の"[:30])

    @unittest.skipIf(os.name == "nt", "Windows では前に居るプロセスを見る口が当てにならないので見ず、画面の exited の行で見分ける"
                                      "（test_exited_line_on_the_screen_counts_as_fallen）")
    def test_window_back_at_the_shell_counts_as_fallen_even_if_herdr_keeps_the_mark(self):
        # attach の画面が終わってシェルに戻っても、herdr はペインの会話の印を残す。前に居るのがシェルなら落ちたと見て戻す
        self.fall(keep_mark=True)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        self.assertIn(("run", self.window, "claude-a1 attach d"), self.ports.term.writes)

    def test_stopped_session_behind_a_stuck_attach_is_ended_and_attached_again(self):
        # Linux: 裏の処理が止まると、窓の attach は「Waking session …」のまま前に残る。会話の一覧が stopped と言えば落ちたと見て、
        # 残った attach を Ctrl-C で終わらせ、シェルに戻ってから短い id で打ち直す
        real_list = self.ports.list_sessions
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {**x, "state": "stopped"} if x.get("sessionId") == "s-dept" else x for x in real_list(cdir, include_done)]
        self.ports.term.front[self.window] = ["claude attach d"]
        self.fall(keep_mark=True)
        self.ports.term.talking.add(self.window)   # 止まった attach が前に居る（シェルでない）
        real_keys = self.ports.term.send_keys

        def keys(pane, *k):
            real_keys(pane, *k)
            if "ctrl+z" in k:
                self.ports.term.talking.discard(pane)
                self.ports.term.front.pop(pane, None)
                self.ports.list_sessions = real_list   # 打ち直すと会話が起きる
        self.ports.term.send_keys = keys
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        writes = [w for w in self.ports.term.writes if w[0] in ("send_keys", "run")]
        self.assertEqual(writes[:2], [("send_keys", self.window, "ctrl+z"), ("run", self.window, "claude-a1 attach d")])

    def test_department_whose_pane_was_closed_is_reopened_and_attached(self):
        # ペインを閉じると部署の作業場も閉じる（skills/dispatch/references/clean.md の「部署の会話を止める」の止め方）。作業場を開き直し、その新しいペインで
        # 短い id の attach を打って戻す（まっさらな環境での 8 回目の試しの 2）
        h = self.ports.term
        ws = next(p["workspace_id"] for p in h._panes if p["pane_id"] == self.window)
        h.close_workspace(ws)
        real_run = h.run

        def run(pane, command):
            real_run(pane, command)
            if " attach " in command:
                h.talking.add(pane)
                for p in h._panes:
                    if p["pane_id"] == pane:
                        p["agent"] = "claude"
        h.run = run
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        opened = [w for w in h.writes if w[0] == "open_worktree"]
        self.assertEqual(len(opened), 1)
        [attach] = [w for w in h.writes if w[0] == "run"]
        self.assertEqual(attach[2], "claude-a1 attach d")
        self.assertNotEqual(attach[1], self.window, "閉じたペインでなく、開き直した作業場の新しいペインに打つ")
        self.assertIn(("rename_pane", attach[1], "調べ"), h.writes)   # 開き直したペインにも --sync と同じ名前を付ける
        # 開き直した作業場は新しいので、永続かエフェメラルかの印も付け直す
        self.assertTrue([w for w in h.writes if w[0] == "report_workspace_metadata" and w[2].get("kind")], h.writes)

    def test_clear_before_ask_sees_the_clear_by_a_new_talk_file_when_the_list_keeps_the_id(self):
        # 裏の会話は /clear の後も会話の一覧の sessionId が替わらないことがある（2026-10-17 の試し）。記録のファイルが替われば空と見る
        class H:
            Error = real_herdr.Error

            def prompt(self, pane, text, wait):
                files.append(("new.jsonl", 2))

            def read(self, pane, lines):
                return ""

        def busy():
            busy.found = "s-old"
            return False
        busy.found = "s-old"
        files = [("old.jsonl", 1)]
        ports = argparse.Namespace(term=H(), pause=lambda: None)
        ok, said = orders.clear_before_ask({"attrs": {}}, "a0", "p1", busy, ports, lambda: files[-1])
        self.assertTrue(ok, said)
        files[:] = [("old.jsonl", 1)]
        H.prompt = lambda self, pane, text, wait: None   # 記録も替わらない
        ok, said = orders.clear_before_ask({"attrs": {}}, "a0", "p1", busy, ports, lambda: files[-1])
        self.assertFalse(ok)
        self.assertIn("見られなかった", said[0])

    def test_newest_talk_is_the_last_written_record_of_the_folder(self):
        home = tempfile.mkdtemp()
        cwd = "/w/a.b"
        # Windows では abspath がドライブを付ける（D:\w\a.b → D--w-a-b）
        d = pathlib.Path(home, "projects", "-w-a-b" if os.name != "nt" else re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(cwd)))
        d.mkdir(parents=True)
        self.assertIsNone(claudex.newest_talk(home, cwd))
        for name, t in (("x.jsonl", 10), ("y.jsonl", 20), ("z.txt", 30)):
            (d / name).write_text("{}", encoding="utf-8")
            os.utime(d / name, (t, t))
        self.assertEqual(claudex.newest_talk(home, cwd), ("y.jsonl", 20))

    def test_confirmed_send_waits_for_the_box_and_resends_only_when_the_line_never_arrived(self):
        # Windows: attach で戻した直後の会話は、打った字を受けられるまで間がある。入力フィールドが出てから送り、動き出す（busy）まで見る
        BOX = "──────────── 計算 ─\n❯ {}\n────────────────"

        class H:
            Error = real_herdr.Error

            def __init__(self, screens):
                self.screens, self.writes = list(screens), []

            def read(self, pane, lines):
                return self.screens.pop(0) if len(self.screens) > 1 else self.screens[0]

            def prompt(self, pane, text, wait):
                self.writes.append(("prompt", text))

            def send_keys(self, pane, *keys):
                self.writes.append(("keys",) + keys)
        line = "再開の知らせです: この会話は落ちて戻った。受付 X"
        # 入力フィールドに残った: Enter を 1 回足し、動き出したら送れた
        state = {"n": 0}

        def busy_after_enter():
            return any(w[0] == "keys" for w in h.writes)
        h = H(["", BOX.format(""), BOX.format(line)])
        self.assertEqual(deliver.send_confirmed("P", line, h, lambda: None, busy_after_enter)[0], "sent")
        self.assertEqual([w[0] for w in h.writes], ["prompt", "keys"])
        # 入力フィールドにも上にも見えず、動き出さない: 打ち直す
        h = H([BOX.format("")])
        status, detail = deliver.send_confirmed("P", line, h, lambda: None, lambda: False)
        self.assertEqual(status, "failed")
        self.assertEqual([w[0] for w in h.writes], ["prompt"] * deliver.SEND_TRIES)
        # 入力フィールドより上に載った（届いた）: 打ち直さない
        h = H([BOX.format(""), "● " + line + "\n" + BOX.format("")])
        self.assertEqual(deliver.send_confirmed("P", line, h, lambda: None, lambda: False)[0], "sent")
        self.assertEqual([w[0] for w in h.writes], ["prompt"])
        # 前に送った同じ字が画面に残っているだけ（今の 1 行は届いていない）: 届いたと見誤らず、打ち直す
        h = H(["● " + line + "\n" + BOX.format("")])
        self.assertEqual(deliver.send_confirmed("P", line, h, lambda: None, lambda: False)[0], "failed")
        self.assertEqual([w[0] for w in h.writes], ["prompt"] * deliver.SEND_TRIES)
        # 送る前から動いている会話: 打った字はターンの後の待ちの列に回る。動き出しでは確かめず、打ち直さない（同じ頼みが 3 回届いた）
        h = H([BOX.format(""), "❯ " + line + "\n  ctrl+x ctrl+s to send now\n" + BOX.format("")])
        self.assertEqual(deliver.send_confirmed("P", line, h, lambda: None, lambda: True)[0], "sent")
        self.assertEqual([w[0] for w in h.writes], ["prompt"])
        # 入力フィールドに残った字は Enter で待ちの列に回し、入力フィールドから出たのを見て届いたとする
        h = H([BOX.format(""), BOX.format(line), BOX.format("Press up to edit queued messages")])
        self.assertEqual(deliver.send_confirmed("P", line, h, lambda: None, lambda: True)[0], "sent")
        self.assertEqual([w[0] for w in h.writes], ["prompt", "keys"])
        # 画面で見られなくても、動いている会話には 1 回だけ打つ（ターンの途中で取り込まれて画面から消えることもある）
        h = H([BOX.format("")])
        status, detail = deliver.send_confirmed("P", line, h, lambda: None, lambda: True)
        self.assertEqual((status, [w[0] for w in h.writes]), ("sent", ["prompt"]))
        self.assertIn("打ち直さない", detail)
        # 促しの 1 行は時刻で前の促しと字を分ける
        import orders
        self.assertNotEqual(orders.nudge_line("X", "desk", 1_000_000)[:20], orders.nudge_line("X", "desk", 1_000_007)[:20])

    def test_ask_finds_the_department_talk_after_clear_and_rewrites_its_id(self):
        # 部署の会話で /clear を打つと会話の id が変わる。属性の古い id で一覧を引くと動き出しを見られず、届いた頼みを 3 回打ち直して
        # failed を返し、頼み元の属性を書かなかった（2026-10-16 の試しの部署）。部署の場所に居る裏の会話で見つけ、id を書き直す
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"sessionId": "s-desk", "name": "desk", "cwd": self.src, "kind": "interactive", "status": "idle"},
            {"id": "e", "sessionId": "s-cleared", "name": "調べ", "cwd": self.place, "kind": "background", "state": "working",
             "status": "busy" if any(w[0] == "prompt" and w[1] != self.desk for w in self.ports.term.writes) else "idle"}]
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.prompts()), 1)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs.get("session"), attrs.get("boss")), ("s-cleared", "desk"))

    def test_a_line_left_in_the_input_box_gets_an_enter(self):
        # Windows: attach で戻した直後に送った文が、入力フィールドに入ったまま送信されなかった。残っていれば Enter を足す
        h = self.ports.term
        h.screen = "────\n❯ 再開の知らせです: この会話は落ちて戻った。\n────"
        status, detail = deliver.send(self.window, "再開の知らせです: この会話は落ちて戻った。受付 X", h, lambda: None)
        self.assertEqual(status, "sent")
        self.assertIn(("send_keys", self.window, "enter"), h.writes)
        h.writes.clear()
        h.screen = "────\n❯\n────"
        deliver.send(self.window, "再開の知らせです: この会話は落ちて戻った。受付 X", h, lambda: None)
        self.assertNotIn(("send_keys", self.window, "enter"), h.writes)

    def test_exited_line_on_the_screen_counts_as_fallen(self):
        # Windows では前のプロセスを見る口が当てにならないので、画面の「Session … has exited.」でも見分ける
        orders = __import__("orders")
        self.ports.term.screen = "Session d has exited.\nPS C:\\w> "
        dept = {"panes": [{"pane_id": self.window, "agent": "claude"}]}
        self.assertIsNone(orders.live_window(dept, self.ports))
        self.ports.term.screen = "> 作業中"
        self.assertEqual(orders.live_window(dept, self.ports), self.window)

    def test_fallen_department_with_a_pending_ask_is_nudged_to_deliver(self):
        # 落ちる前の頼みを納品していない部署: 戻して納品を促し、新しい頼みは送らずに止まる（待っても来ない、で止めない）
        provision.mark(self.place, self.src, {"ask": "20261016-000000-aaaaaa", "boss": "desk"}, gitx)
        self.fall()
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "次")
        self.assertEqual(rc, 2, out)
        self.assertIn("会話が落ちていたので戻して納品を促した", out)
        [(_, pane, text, _)] = self.prompts()
        self.assertEqual(pane, self.window)
        self.assertIn("受付 20261016-000000-aaaaaa", text)
        self.assertIn("--deliver", text)

    def test_ask_types_one_line_into_the_department_window_and_writes_the_ask(self):
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "これを調べて")
        self.assertEqual(rc, 0, out)
        (w,) = self.prompts()
        self.assertEqual((w[1], w[3]), (self.window, False))
        self.assertIn("頼みです（受付 ", w[2])
        self.assertIn("desk から）: これを調べて 終わったら、要約を 結論・決め手・残った疑問・ブランチ の項目で", w[2])
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual({k: attrs.get(k) for k in ("boss", "boss-account", "boss-session", "boss-pane")},
                         {"boss": "desk", "boss-account": "a1", "boss-session": "s-desk", "boss-pane": self.desk})
        self.assertEqual(os.path.realpath(attrs["boss-inbox"]), os.path.realpath(self.inbox))
        (rec,) = deliver.records(self.inbox)
        self.assertEqual((rec["kind"], rec["status"], rec["id"], rec["to"]["name"]), ("ask", "sent", attrs["ask"], "調べ"))
        self.assertEqual(pathlib.Path(rec["file"]).read_text(encoding="utf-8"), "これを調べて\n")
        # 受付箱は commit されない（共通の .git の中）
        self.assertEqual(git("-C", self.src, "status", "--porcelain").strip(), "")

    def test_ask_names_the_asker_from_the_current_process_of_a_resumed_session(self):
        # 窓口を一時停止したまま --resume で開き直し、/rename した。一覧には古い処理（desk）と今の処理（窓口）が並ぶ
        listed = self.ports.list_sessions
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"pid": 10**9, "startedAt": 100, **listed(cdir)[0]},   # 試験を走らせる処理の親に当たらない pid
            {"pid": 10**9 + 1, "startedAt": 200, **listed(cdir)[0], "name": "窓口"}, *listed(cdir)[1:]]
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place).get("boss"), "窓口")
        self.assertIn("窓口 から）", self.prompts()[0][2])

    def test_ask_takes_the_askers_name_and_account_from_the_flags(self):
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x", "--from-name", "窓口", "--from-account", "a2")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs.get("boss"), attrs.get("boss-account")), ("窓口", "a2"))

    def test_ask_from_a_named_place_names_the_asker_by_the_place_not_the_talk(self):
        # 窓口の待ち受けは場所の名前（company.name）で受ける。会話の一覧の名前（desk）は替わりうるので、頼み元には場所の名前を書く
        # （段取りが会話の名前 my-notes-d7 で頼み、納品が待ち受けに届かなかった。my_notes の受付 20261017-032608-18b5f5）
        provision.mark(self.src, self.src, {"role": "窓口", "name": "段取り", "session": "s-desk"}, gitx)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place).get("boss"), "段取り")
        self.assertIn("段取り から）", self.prompts()[0][2])

    def test_ask_from_the_desk_right_after_clear_names_the_asker_by_the_place(self):
        # 窓口が /clear で会話を空にした直後は、会話の id が company.session と合わない。--desk が書いた処理（company.pid）の中から
        # 頼んだなら、場所の名前を書く（会話の一覧の名前 my-notes-d7 で頼み元を書き続けた。my_notes の受付 20261017-054115-5bc0b0）
        provision.mark(self.src, self.src, {"role": "窓口", "name": "段取り", "session": "s-before-clear", "pid": "4242"}, gitx)
        self.ports.same_process = lambda pid: pid == "4242"
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place).get("boss"), "段取り")

    def test_ask_typed_in_another_clone_returns_to_the_askers_own_inbox(self):
        # 窓口が別の会社の clone でコマンドを打っても、納品の受付箱は窓口の居る場所の会社の物（段取りが claude-plugins の clone で打ち、
        # 返り先が claude-plugins の受付箱になった。my_notes の受付 20261017-054115-5bc0b0）
        other = str(pathlib.Path(self.root) / "other")
        git("init", "-q", other)
        rc, out = self.main(other, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        self.assertEqual(os.path.realpath(gitx.worktree_attrs(self.place).get("boss-inbox")), os.path.realpath(self.inbox))

    def test_ask_from_another_talk_in_the_head_office_keeps_the_talks_name(self):
        # 本社にはほかの会話も居る。--desk が書いた会話（company.session）でなければ、窓口の名前を名乗らない
        provision.mark(self.src, self.src, {"role": "窓口", "name": "段取り", "session": "s-other"}, gitx)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place).get("boss"), "desk")

    def test_the_command_handed_to_the_department_is_quoted_with_forward_slashes(self):
        self.assertNotIn("\\", orders.RUN)
        self.assertTrue(orders.RUN.endswith("/dispatch.py") or orders.RUN.endswith("/dispatch.py'"))

    def test_a_second_ask_waits_until_the_first_is_delivered(self):
        self.assertEqual(self.main(self.src, "--ask", "調べ", "--text", "一つ目")[0], 0)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "二つ目")
        self.assertEqual(rc, 2, out)
        self.assertIn("まだ納品していない", out)
        self.assertEqual(len(self.prompts()), 1)

    def test_the_askers_window_is_where_the_asking_talk_is_not_the_inherited_env(self):
        # 裏の会話（claude --bg）は控えの処理の HERDR_PANE_ID を継ぎ、別のペインを指すことがある（2026-10-17 に見た）
        self.ports.env = {"CLAUDE_CODE_SESSION_ID": "s-desk", "HERDR_PANE_ID": self.window}
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place).get("boss-pane"), self.desk)

    def test_a_new_ask_does_not_keep_the_previous_askers_values(self):
        provision.mark(self.place, self.src, {"boss": "前の窓口", "boss-account": "zz", "boss-session": "s-old",
                                              "boss-pane": "P-old"}, gitx)
        self.ports.env = {}   # Claude Code の外から頼んだ（頼む会話が分からない）
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual({k: attrs.get(k) for k in ("boss", "boss-account", "boss-session", "boss-pane")},
                         {"boss": None, "boss-account": None, "boss-session": None, "boss-pane": None})

    def test_ask_dry_run_writes_nothing(self):
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "x", "--dry-run")
        self.assertEqual(rc, 0, out)
        self.assertIn("打ち込む 1 行: 頼みです", out)
        self.assertEqual(self.prompts(), [])
        self.assertNotIn("ask", gitx.worktree_attrs(self.place))
        self.assertFalse(os.path.exists(self.inbox))

    def test_ask_to_a_duty_raised_only_when_asked_starts_its_department_with_a_branch_of_its_own(self):
        # オンデマンドの受け持ち（on_demand = true）: --task・--branch を渡さなくても、受け持ちの名前の部署を立てる（813bb8）
        self.shape('[[roles]]\nname = "担当"\npersistent = true\n[[skills]]\nname = "見渡し"\nrole = "担当"\non_demand = true\n')
        seen = {}

        def task(cfg, repo, ns, ports, extra_attrs=None, tail=None, refreshed=False):
            seen.update(name=ns.task, branch=ns.branch, role=ns.role)
            return 1
        with contextlib.chdir(self.src):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                a = argparse.Namespace(config=self.cfg, ask="見渡し", text="見て", brief=None, task=None, branch=None,
                                       dry_run=False, role=None, persistent=False, base=None, from_name=None, from_account=None)
                orders.ask(a, self.ports, self.src, task)
        self.assertEqual((seen["name"], seen["role"]), ("見渡し", "担当"), buf.getvalue())
        self.assertRegex(seen["branch"], r"^work/ask-[0-9a-f]{6}$")
        self.assertIn("オンデマンドの受け持ち", buf.getvalue())
        companies = [{"name": "co", "root": self.src, "departments": [],
                      "skills": [{"name": "見渡し", "role": "担当", "on_demand": True}]}]
        self.assertEqual(deliver.find_target(companies, self.src, "co/見渡し")["on_demand"], "見渡し")
        companies[0]["departments"] = [dept_row(name="見渡し", role="担当", path="/r/w")]   # 立っている間は、その部署に届ける
        self.assertEqual(deliver.find_target(companies, self.src, "co/見渡し")["department"]["path"], "/r/w")

    def test_ask_to_a_role_without_a_resident_department_starts_one_through_the_task_path(self):
        seen = {}

        def task(cfg, repo, ns, ports, extra_attrs=None, tail=None, refreshed=False):
            seen.update(name=ns.task, branch=ns.branch, role=ns.role, brief=ns.brief, attrs=extra_attrs, tail=tail,
                        source=repo.source, refreshed=refreshed)
            path = str(pathlib.Path(self.root) / "new")
            git("-C", self.src, "worktree", "add", "-q", "-b", ns.branch, path, "origin/main")
            provision.mark(path, self.src, {**extra_attrs, "role": ns.role, "session": "s-new"}, gitx)
            return 0

        with contextlib.chdir(self.src):
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                a = argparse.Namespace(config=self.cfg, ask="出荷役", text=None, brief=None, task="出荷", branch="ship/1",
                                       dry_run=False, role=None, persistent=False, base=None, from_name=None, from_account=None)
                brief = pathlib.Path(self.root).parent / "b.md"
                brief.write_text('+++\ntitle = "出荷する"\n+++\n長い頼み\n二行目', encoding="utf-8")
                a.brief = str(brief)
                rc = orders.ask(a, self.ports, self.src, task)
        self.assertEqual(rc, 0, buf.getvalue())
        self.assertEqual((seen["name"], seen["branch"], seen["role"]), ("出荷", "ship/1", "出荷役"))
        self.assertEqual(os.path.realpath(seen["source"]), os.path.realpath(self.src))
        self.assertEqual(pathlib.Path(seen["brief"]).read_text(encoding="utf-8"), '+++\ntitle = "出荷する"\n+++\n長い頼み\n二行目\n')
        self.assertIn("--deliver <要約のファイル>", seen["tail"])
        self.assertTrue(seen["refreshed"])
        self.assertEqual(seen["attrs"]["boss"], "desk")
        self.assertEqual(deliver.records(self.inbox)[0]["status"], "sent")
        self.assertEqual(deliver.records(self.inbox)[0]["title"], "出荷する")   # 題は台帳の行のフィールドに残す（--todo は文から拾わない）

    def test_ask_that_starts_a_department_reads_the_items_from_the_fetched_shape(self):
        seen = {}

        def task(cfg, repo, ns, ports, extra_attrs=None, tail=None, refreshed=False):
            seen.update(tail=tail)
            return 1

        sha = push_shape(self.src, '[[roles]]\nname = "出荷役"\ndeliver = ["結論", "差分"]\n')
        a = argparse.Namespace(config=self.cfg, ask="出荷役", text="x", brief=None, task="出荷", branch="ship/1",
                               dry_run=False, role=None, persistent=False, base=None, from_name=None, from_account=None)
        with contextlib.chdir(self.src), contextlib.redirect_stdout(io.StringIO()):
            orders.ask(a, self.ports, self.src, task)
        self.assertEqual(git("-C", self.src, "rev-parse", "origin/main"), sha)
        self.assertIn("結論・差分", seen["tail"])

    def test_ask_to_a_missing_role_needs_a_name_and_a_branch(self):
        rc, out = self.main(self.src, "--ask", "出荷役", "--text", "x")
        self.assertEqual(rc, 2, out)
        self.assertIn("--task <名前>、ブランチを --branch <ブランチ>", out)

    def test_text_needs_ask_and_ask_needs_one_body(self):
        self.assertEqual(self.main(self.src, "--text", "x")[0], 2)
        self.assertEqual(self.main(self.src, "--ask", "調べ")[0], 2)

    def ask_then_summary(self, text):
        self.assertEqual(self.main(self.src, "--ask", "調べ", "--text", "調べて")[0], 0)
        self.ports.term.writes.clear()
        summary = pathlib.Path(self.root).parent / "summary.md"
        summary.write_text(text, encoding="utf-8")
        return str(summary)

    def test_deliver_sends_the_summary_to_the_asker_and_marks_it_delivered(self):
        summary = self.ask_then_summary(GOOD)
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        (w,) = self.prompts()
        self.assertEqual(w[1], self.desk)
        self.assertIn("納品です（受付 ", w[2])
        self.assertIn("調べ・ブランチ dept/a から）: 【結論】直した。 / 試験は緑。 【決め手】", w[2])
        self.assertIn("【ブランチ】dept/a", w[2])   # ブランチは機械が足す
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual(attrs["delivered"], attrs["ask"])
        recs = deliver.records(self.inbox)
        self.assertEqual([r["kind"] for r in recs], ["ask", "deliver"])
        self.assertIn("## 結論\n直した。", pathlib.Path(recs[1]["file"]).read_text(encoding="utf-8"))
        # 納品の後は Stop フックが差し戻さない
        self.assertIsNone(deliver.stop_verdict({"session_id": "s-dept"}, attrs, 0, "/d.py"))

    def test_a_second_deliver_to_the_delivered_ask_stops_until_again(self):
        # 納品した頼みへ、--again も --for も無い 2 通目は送らない。前は、ほかの頼みの要約が済んだ頼みの納品として届いた（受付 b54685）
        summary = self.ask_then_summary(GOOD)
        self.assertEqual(self.main(self.place, "--deliver", summary)[0], 0)
        ask = gitx.worktree_attrs(self.place)["ask"]
        (first,) = [r["file"] for r in deliver.records(self.inbox) if r.get("kind") == "deliver"]
        self.ports.term.writes.clear()
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 2, out)
        self.assertIn(f"今の頼み（受付 {ask}）はもう納品した", out)
        self.assertIn(f"- 送った要約: {first}", out)
        self.assertIn(f"- 頼みの本文: {os.path.join(self.inbox, ask + '-ask.md')}", out)
        self.assertEqual(self.prompts(), [])
        self.assertEqual(len([r for r in deliver.records(self.inbox) if r.get("kind") == "deliver"]), 1)
        rc, out = self.main(self.place, "--deliver", summary, "--again")   # 同じ頼みの続き
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.prompts()), 1)
        rc, out = self.main(self.place, "--again")
        self.assertEqual(rc, 2, out)
        self.assertIn("--again は --deliver と一緒にだけ使う", out)
        rc, out = self.main(self.place, "--deliver", summary, "--again", "--for", ask)
        self.assertEqual(rc, 2, out)
        self.assertIn("--again と --for は一緒に使わない", out)

    def push_from_the_department(self, files):
        """部署が --land を通さずに、部署の作業場から手でメインブランチへ push した形（git push origin HEAD:main）。入れた commit を返す。"""
        for rel, text in files.items():
            pathlib.Path(self.place, rel).parent.mkdir(parents=True, exist_ok=True)
            pathlib.Path(self.place, rel).write_text(text, encoding="utf-8")
            git("-C", self.place, "add", rel)
        git("-C", self.place, "-c", "user.name=o", "-c", "user.email=o@o", "commit", "-q", "-m", "部署の作業")
        git("-C", self.place, "push", "-q", "origin", "HEAD:refs/heads/main")
        return git("-C", self.place, "rev-parse", "HEAD")

    def test_deliver_brings_the_main_clone_up_to_a_push_that_skipped_land(self):
        # 部署が --land を通さずに手で push した成果も、納品の後に代表の clone のメインブランチへ届く（2026-10-17 の my_notes。部署が
        # git push origin HEAD:master で入れ、代表の clone の master が黙って遅れた。受付 d3f166）
        summary = self.ask_then_summary(GOOD)
        before = git("-C", self.src, "rev-parse", "main")
        head = self.push_from_the_department({".claude/company.toml": '[land]\nmode = "ff-after-ci"\ngate = "check"\ncheck = "true"\n'})
        self.assertEqual(git("-C", self.src, "rev-parse", "main"), before)
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        self.assertEqual(git("-C", self.src, "rev-parse", "main"), head)
        self.assertIn(f"代表の clone の main をメインブランチ {head[:7]} へ進めた", out)

    def test_deliver_leaves_the_main_clone_of_a_company_without_land_alone(self):
        summary = self.ask_then_summary(GOOD)
        before = git("-C", self.src, "rev-parse", "main")
        self.push_from_the_department({"a.txt": "a\n"})
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        self.assertEqual(git("-C", self.src, "rev-parse", "main"), before)   # --land を使わない会社の代表の clone は動かさない
        self.assertNotIn("代表の clone", out)

    def test_wait_marks_the_ask_until_a_prompt_or_the_delivery(self):
        # 人の答えを待つ部署（持ち主が答えるのは数時間後もありうる）が、ターンの終わりごとに納品を促されない
        summary = self.ask_then_summary(GOOD)
        self.assertEqual(self.main(self.place, "--wait", "")[0], 2)   # 何を待つかが要る
        rc, out = self.main(self.place, "--wait", "持ち主の答え（どちらの案にするか）")
        self.assertEqual(rc, 0, out)
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((attrs["waiting"], attrs["waiting-why"]), (attrs["ask"], "持ち主の答え（どちらの案にするか）"))
        self.assertIsNone(deliver.stop_verdict({"session_id": "s-dept"}, attrs, 0, "/d.py"))
        # 人が打つと外れ、また促す（ほかの会話の文では外さない）
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s-other"})
        self.assertIn("waiting", gitx.worktree_attrs(self.place))
        wake_hook.resume_from_wait({"cwd": self.place, "session_id": "s-dept"})
        attrs = gitx.worktree_attrs(self.place)
        self.assertNotIn("waiting", attrs)
        # 答え待ちと外れたことは台帳にも残り、台帳の射影がその頼みを答え待ち→動いているに読む（同じ受付箱には 1 行ずつ）
        rows = [r for r in deliver.records(self.inbox) if r.get("kind") in ("waiting", "resumed")]
        self.assertEqual([(r["kind"], r["id"]) for r in rows], [("waiting", attrs["ask"]), ("resumed", attrs["ask"])])
        self.assertEqual(rows[0]["why"], "持ち主の答え（どちらの案にするか）")
        self.assertEqual(ledger.build(ledger.merge(deliver.records(self.inbox)))["tasks"][attrs["ask"]]["state"], "working")
        self.assertIn("受付", deliver.stop_verdict({"session_id": "s-dept"}, attrs, 0, "/d.py"))
        # 納品でも外れる
        self.assertEqual(self.main(self.place, "--wait", "持ち主の答え")[0], 0)
        self.assertEqual(self.main(self.place, "--deliver", summary)[0], 0)
        self.assertNotIn("waiting", gitx.worktree_attrs(self.place))
        self.assertEqual(self.main(self.place, "--wait", "持ち主の答え")[0], 2)   # 納品した後は待つ頼みが無い
        self.assertEqual(self.main(self.src, "--wait", "持ち主の答え")[0], 2)     # 部署でない所

    def test_rest_marks_a_break_only_after_the_ask_is_delivered(self):
        # 会話を引き継ぐ部署と窓口が、空にしてよい区切りを自分で印す（空にするのはターンの終わりの待ち受け）
        summary = self.ask_then_summary(GOOD)
        rc, out = self.main(self.place, "--rest")
        self.assertEqual(rc, 2, out)   # 納品していない頼みが在る
        self.assertIn("納品していない頼み", out)
        self.assertEqual(self.main(self.place, "--deliver", summary)[0], 0)
        rc, out = self.main(self.place, "--rest")
        self.assertEqual(rc, 0, out)
        self.assertEqual(gitx.worktree_attrs(self.place)[wake.REST], "s-dept")
        self.assertEqual(self.main(self.src, "--rest")[0], 2)   # 部署でも窓口でもない所

    def test_rest_marks_a_break_before_delivery_when_a_move_waits_for_one(self):
        # --move がほかのアカウントへ移す印（company.move-to）を付けた会話は、納品の前でも区切りを印せる（受付 f39d00）
        self.ask_then_summary(GOOD)
        provision.mark(self.place, self.src, {"account": "a1", wake.MOVE_TO: "a1"}, gitx)
        self.assertEqual(self.main(self.place, "--rest")[0], 2)   # 今のアカウントを名指した印は移さない
        provision.mark(self.place, self.src, {wake.MOVE_TO: "a2"}, gitx)
        rc, out = self.main(self.place, "--rest")
        self.assertEqual(rc, 0, out)
        self.assertIn("アカウント a2 へ移して起動し直し", out)
        self.assertIn(os.path.join(gitx.git_dir(self.place), wake.HANDOFF), out)
        self.assertEqual(gitx.worktree_attrs(self.place)[wake.REST], "s-dept")

    def test_deliver_with_missing_items_sends_nothing_and_names_them(self):
        summary = self.ask_then_summary("結論: 直した\n")
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 2, out)
        self.assertIn("送らなかった: 要約に足りない項目がある: 決め手（無いか空）、残った疑問（頭書きの open が無い。疑問が無ければ open = []）", out)
        self.assertEqual(self.prompts(), [])
        attrs = gitx.worktree_attrs(self.place)
        self.assertNotIn("delivered", attrs)
        self.assertIn("受付", deliver.stop_verdict({"session_id": "s-dept"}, attrs, 0, "/d.py"))

    def test_a_new_department_on_the_askers_own_branch_stops_and_says_to_go_on_here(self):
        # 部署はブランチの作業場で起動するので、頼んだ会話の居るブランチには立たない。前は台帳に訳の無い failed を残した（3d3ccc）
        self.shape('[[roles]]\nname = "作業"\n')
        rc, out = self.main(self.place, "--ask", "作業", "--text", "直して", "--task", "直し", "--branch", "dept/a")
        self.assertEqual(rc, 2, out)
        self.assertIn("部署を立てずにこの会話で進める", out)
        self.assertEqual(deliver.records(self.inbox), [])

    def test_a_new_department_that_does_not_start_leaves_why_in_the_ledger(self):
        self.shape('[[roles]]\nname = "作業"\n')

        def not_started(cfg, repo, a, ports, **kw):
            print(f"部署 {a.task}  {a.branch}  -  no_account（使用率が上限に届かないアカウントが無い）")
            return 0
        with mock.patch.object(sys.modules["dispatch"], "_task", not_started):
            rc, out = self.main(self.src, "--ask", "作業", "--text", "直して", "--task", "直し", "--branch", "b/x")
        self.assertEqual(rc, 1, out)
        (rec,) = deliver.records(self.inbox)
        self.assertEqual((rec["status"], rec["detail"]), ("failed", "部署 直し  b/x  -  no_account（使用率が上限に届かないアカウントが無い）"))

    def test_a_department_that_failed_to_launch_keeps_the_reason_from_before_the_summary(self):
        # launch_failed の訳は要約の行より前の行に在る。要約の行だけを残すと、状態の語しか残らない
        self.shape('[[roles]]\nname = "作業"\n')

        def failed(cfg, repo, a, ports, **kw):
            print(f"claude が起動しなかった（exit 1）\n部署 {a.task}  {a.branch}  p1  launch_failed\n- ペイン 1（x）")
            return 1
        with mock.patch.object(sys.modules["dispatch"], "_task", failed):
            rc, out = self.main(self.src, "--ask", "作業", "--text", "直して", "--task", "直し", "--branch", "b/x")
        self.assertEqual(rc, 1, out)
        (rec,) = deliver.records(self.inbox)
        self.assertEqual(rec["detail"], "claude が起動しなかった（exit 1）；部署 直し  b/x  p1  launch_failed")

    def shape(self, text):
        # 会社の形は本社（元の clone）のものを読む（--tree と頼む側と同じ。部署のブランチの中の写しではない）
        shape = pathlib.Path(self.src) / ".claude" / "company.toml"
        shape.parent.mkdir(exist_ok=True)
        shape.write_text(text, encoding="utf-8")

    def fresh_world(self, busy_before=False):
        """頼みごとに空にする役（fresh）の部署。/clear を打つと会話の id が変わり、頼みを打つと動き出す。"""
        self.shape('[[roles]]\nname = "調べ役"\npersistent = true\nfresh = true\n')
        provision.mark(self.place, self.src, {"lifecycle": "persistent"}, gitx)
        sent = lambda: [w[2] for w in self.prompts() if w[1] != self.desk]   # noqa: E731
        self.ports.list_sessions = lambda cdir, include_done=False: [
            {"sessionId": "s-desk", "name": "desk", "cwd": self.src, "kind": "interactive", "status": "idle"},
            {"id": "s", "sessionId": "s-new" if "/clear" in sent() else "s-dept", "name": "調べ", "cwd": self.place,
             "kind": "background", "state": "working",
             "status": "busy" if busy_before or any(x != "/clear" for x in sent()) else "idle"}]
        return sent

    def test_fresh_role_clears_the_talk_before_the_next_ask_once_the_last_one_is_delivered(self):
        # 担当は永続の席のまま、頼みごとに空の会話で受ける（前の頼みの記憶で書き直すと、ほかの部署が入れた行を消す）
        sent = self.fresh_world()
        provision.mark(self.place, self.src, {"ask": "20261016-000000-aaaaaa", "delivered": "20261016-000000-aaaaaa"}, gitx)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        self.assertEqual(sent()[0], "/clear")
        self.assertIn("調べて", sent()[1])
        self.assertIn("/clear で会話を空にしてから送る", out)
        attrs = gitx.worktree_attrs(self.place)
        # 変わった会話の id と、attach に渡す短い id（/clear の前の id の頭）、役の fresh を属性に書く
        self.assertEqual((attrs["session"], attrs["job"], attrs["fresh"]), ("s-new", "s", "true"))
        # herdr の作業場の印にも出る
        rc, out = self.main(self.src, "--sync", "--dry-run")
        self.assertIn("印 永続・毎回クリア", out)

    def test_fresh_role_sees_the_clear_in_the_records_of_the_pane_account_not_of_the_asker(self):
        # 設定のフォルダを書かないアカウントの部署は、ペインのシェルの素の claude で起きて ~/.claude に記録を書く。頼む会話の
        # CLAUDE_CONFIG_DIR（別のアカウント）の下を探すと記録が見つからず、一覧の id も替わらないので、空になったのを見られない
        # （2026-10-17 に、設定のフォルダを書いたアカウントの会話から、書かないアカウントの部署へ 2 回頼んで 2 回止まった。my_notes の受付 20261017-075753-01991f）
        cfg = pathlib.Path(self.cfg)
        cfg.write_text(cfg.read_text(encoding="utf-8").replace(f", config_dir = '{cfg.parent}/c1'", ""), encoding="utf-8")
        home = pathlib.Path(self.root).parent / "home"
        records = home / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", os.path.abspath(self.place))
        records.mkdir(parents=True)
        (records / "old.jsonl").write_text("{}", encoding="utf-8")
        os.utime(records / "old.jsonl", (1, 1))
        self.ports.env = {**self.ports.env, "HOME": str(home), "CLAUDE_CONFIG_DIR": str(pathlib.Path(self.root).parent / "c2")}
        sent = self.fresh_world()
        self.ports.list_sessions = lambda cdir, include_done=False: [   # 裏の会話は /clear の後も一覧の id が替わらない
            {"sessionId": "s-desk", "name": "desk", "cwd": self.src, "kind": "interactive", "status": "idle"},
            {"id": "s", "sessionId": "s-dept", "name": "調べ", "cwd": self.place, "kind": "background", "state": "working",
             "status": "busy" if any(x != "/clear" for x in sent()) else "idle"}]
        typed = self.ports.term.prompt

        def prompt(pane, text, wait):
            if text == "/clear":
                (records / "new.jsonl").write_text("{}", encoding="utf-8")
            return typed(pane, text, wait)
        self.ports.term.prompt = prompt
        provision.mark(self.place, self.src, {"ask": "20261016-000000-aaaaaa", "delivered": "20261016-000000-aaaaaa"}, gitx)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        self.assertEqual(sent()[0], "/clear")
        self.assertIn("調べて", sent()[1])

    def test_fresh_role_does_not_clear_a_talk_without_a_delivered_ask_or_a_running_one(self):
        sent = self.fresh_world()
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")   # 頼みの無い部署（--task の頼みのファイルで働いているかも）
        self.assertEqual(rc, 0, out)
        self.assertNotIn("/clear", sent())
        self.assertIn("まだ納品した頼みが無いので、空にせずに送る", out)
        self.ports.term.writes.clear()
        sent = self.fresh_world(busy_before=True)
        provision.mark(self.place, self.src, {"delivered": gitx.worktree_attrs(self.place)["ask"]}, gitx)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "次")
        # 納品し終えた部署が動いていて空にできないなら送らない（打つとターンの後に前の会話のまま届く。my_notes の受付 6f32b7）
        self.assertEqual(rc, 1, out)
        self.assertEqual(sent(), [])
        self.assertIn("空にできないので送らなかった", out)

    def test_fresh_role_mid_turn_with_a_watcher_history_queues_the_ask(self):
        # 待ち受けの跡の在る部署がターンの途中（待ち受けが止まっている）なら、打ち込まずに順番待ちに積む（ターンの終わりの待ち受けが
        # 空にしてから渡す）
        sent = self.fresh_world(busy_before=True)
        provision.mark(self.place, self.src, {"name": "調べ", "ask": "20261016-000000-aaaaaa",
                                              "delivered": "20261016-000000-aaaaaa"}, gitx)
        place_dir = gitx.git_dir(self.place)
        pos = pathlib.Path(wake.pos_path(self.inbox, place_dir))
        pos.parent.mkdir(parents=True, exist_ok=True)
        pos.write_text("0", encoding="utf-8")
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "次")
        self.assertEqual(rc, 0, out)
        self.assertEqual(sent(), [])
        self.assertIn("順番待ちに積んだ", out)
        self.assertEqual(len(wake.queued(self.inbox, place_dir)), 1)

    def test_deliver_items_follow_the_role_in_the_company_shape(self):
        # 役の起動方法のフィールド（instructions・model・settings）と納品の項目（deliver）を同じ [[roles]] の項目に書く
        self.shape(test_role.SHAPE)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "調べて")
        self.assertEqual(rc, 0, out)
        self.assertIn("結論・差分・試験 の項目で", self.prompts()[0][2])
        self.ports.term.writes.clear()
        summary = pathlib.Path(self.root).parent / "summary.md"
        summary.write_text("結論: 直した\n差分: 1 行\n", encoding="utf-8")
        rc, out = self.main(self.place, "--deliver", str(summary))
        self.assertEqual(rc, 2, out)
        self.assertIn("送らなかった: 要約に足りない項目がある: 試験（無いか空）", out)
        self.assertNotIn("決め手", out.splitlines()[0])
        summary.write_text("結論: 直した\n差分: 1 行\n試験: 緑\n", encoding="utf-8")
        rc, out = self.main(self.place, "--deliver", str(summary))
        self.assertEqual(rc, 0, out)
        self.assertIn("【試験】緑", self.prompts()[0][2])

    def test_deliver_check_of_the_role_stops_the_delivery_until_it_passes(self):
        # 何を確かめるかは会社の側のスクリプト（ここでは「要約が reference/ を挙げていなければ 1」）。dispatch は走らせて終わりの値を見るだけ
        script = pathlib.Path(self.root).parent / "gate.py"
        got = pathlib.Path(self.root).parent / "gate.json"
        script.write_text("import json, os, sys\n"
                          "p = json.load(sys.stdin)\n"
                          f"open({str(got)!r}, 'w', encoding='utf-8').write(json.dumps({{**p, 'cwd': os.getcwd()}}))\n"
                          "if 'reference/' not in p['summary']:\n"
                          "    print('reference/ に無い URL: https://example.com/spec')\n"
                          "    sys.exit(1)\n", encoding="utf-8")
        command = " ".join(f'"{pathlib.Path(x).as_posix()}"' for x in (sys.executable, script))
        self.shape(f'[[roles]]\nname = "調べ役"\ndeliver_check = {json.dumps(command)}\n')
        summary = self.ask_then_summary(GOOD)
        rc, out = self.main(self.place, "--deliver", summary, "--dry-run")
        self.assertEqual(rc, 2, out)   # --dry-run でも検査する（送る前に通るかを見られる）
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 2, out)
        self.assertIn("送らなかった: 納品の検査が通らなかった（終了の値 1）", out)
        self.assertIn("  reference/ に無い URL: https://example.com/spec", out)
        self.assertEqual(self.prompts(), [])
        self.assertNotIn("delivered", gitx.worktree_attrs(self.place))
        payload = json.loads(got.read_text(encoding="utf-8"))
        attrs = gitx.worktree_attrs(self.place)
        self.assertEqual((payload["role"], payload["ask"], payload["branch"]), ("調べ役", attrs["ask"], "dept/a"))
        self.assertEqual(os.path.realpath(payload["cwd"]), os.path.realpath(self.place))   # 部署の作業場のルートで走る
        self.assertEqual(payload["place"], payload["cwd"])
        self.assertIn("決め手", payload["items"])
        self.assertTrue(payload["summary"].startswith("## 結論\n直した。"))
        self.assertEqual(payload["version"], orders.own_version())   # 会社の側の台本が版の下限を確かめる（3c9a61）
        self.assertRegex(payload["version"], r"^\d+\.\d+\.\d+$")
        pathlib.Path(summary).write_text(GOOD.replace("open = []", '[[open]]\nquestion = "写しは reference/spec.md"'), encoding="utf-8")
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        self.assertIn("納品の検査が通った", out)
        self.assertEqual(len(self.prompts()), 1)

    def test_an_unknown_key_of_the_role_stops_deliver_and_ask(self):
        # 見本は my_notes の今の会社の形の骨組み。役「担当」の deliver_check を書き間違えると、ゲートが黙って外れる代わりに止まる（de978e）
        good = (pathlib.Path(__file__).parent / "samples" / "company-my_notes.toml").read_text(encoding="utf-8")
        self.shape(good)
        provision.mark(self.place, self.src, {"role": "担当"}, gitx)
        summary = self.ask_then_summary(GOOD)
        self.shape(good.replace("deliver_check =", "deliver_chek =", 1))
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 2, out)
        self.assertIn("roles[0]（担当）: 知らない鍵 deliver_chek（読まない", out)
        self.assertIn("送らなかった: 役「担当」の会社の形に、この版の読まない鍵 deliver_chek があるので送らなかった", out)
        self.assertEqual(self.prompts(), [])
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "もう 1 つ", "--dry-run")
        self.assertEqual(rc, 2, out)
        self.assertIn("止めた: 役「担当」の会社の形に、この版の読まない鍵 deliver_chek があるので頼まなかった", out)
        self.shape(good)
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        self.assertIn("納品の検査が通った: true", out)
        self.assertNotIn("知らない鍵", out)

    def test_a_check_script_missing_in_the_workplace_says_to_rebase(self):
        # 会社の形はメインブランチから読むが、検査は作業場で走る。台本の入る前のメインブランチから切ったブランチでは台本が無いので、リベースするよう言う
        self.shape(f'[[roles]]\nname = "調べ役"\ndeliver_check = {json.dumps(f'"{pathlib.Path(sys.executable).as_posix()}" tools/check.py')}\n')
        summary = self.ask_then_summary(GOOD)
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 2, out)
        self.assertIn("検査の台本 tools/check.py がこの作業場に無い", out)
        self.assertIn("git rebase origin/main", out)
        self.assertEqual(self.prompts(), [])

    def test_roles_written_by_name_are_not_read_and_say_to_move_them(self):
        self.shape('[roles."調べ役"]\ndeliver = ["結論", "差分", "試験"]\n')
        summary = self.ask_then_summary(GOOD)
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)   # 既定の項目で確かめる（黙って無視せず、注記を出す）
        self.assertIn('[roles."役"] の形で書いている（調べ役）', out)
        self.assertIn("[[roles]] の項目", out)

    def test_deliver_with_holders_stops_an_open_item_without_a_holder(self):
        self.shape('[[roles]]\nname = "調べ役"\nholders = true\n')
        summary = self.ask_then_summary(GOOD.replace("+++\nopen = []\n+++", ONE_OPEN))
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 2, out)
        self.assertIn("担当者（holder）が無い: 測り直す", out)
        self.assertIn("[[open]]", out)   # 書き方の例を返す
        self.assertEqual(self.prompts(), [])
        with_holder = GOOD.replace("open = []", '[[open]]\nquestion = "測り直す"\nholder = "割り振り"')
        pathlib.Path(summary).write_text(with_holder, encoding="utf-8")
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 2, out)   # 部署の名前は --todo が追えない（受付 b6778d）
        self.assertIn("「割り振り」は 受付番号・owner:choose・owner:confirm", out)
        pathlib.Path(summary).write_text(with_holder.replace("割り振り", "20261018-120448-b6778d"), encoding="utf-8")
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 2, out)   # 受付番号の形でも、台帳に無い頼みは --todo が追えない
        self.assertIn("担当者の受付 20261018-120448-b6778d は、たどった受付箱の台帳のどれにも無いか", out)
        self.assertEqual(self.prompts(), [])
        (asked,) = [r["id"] for r in deliver.records(self.inbox) if r.get("kind") == "ask"]
        pathlib.Path(summary).write_text(with_holder.replace("割り振り", asked), encoding="utf-8")
        self.assertEqual(self.main(self.place, "--deliver", summary)[0], 0)

    def test_deliver_with_holders_finds_an_ask_in_another_companys_ledger(self):
        # 台帳の行が指すほかの会社の受付箱も --todo と同じくたどる（ほかの会社の中で回された頼みも担当者に書ける）
        self.shape('[[roles]]\nname = "調べ役"\nholders = true\n')
        other = pathlib.Path(self.root) / "other"
        git("init", "-q", str(other))
        theirs = os.path.join(str(other), ".git", "company", "inbox")
        os.makedirs(theirs)
        deliver.log(theirs, {"id": "20261018-224301-4e6a26", "kind": "ask", "at": 2, "status": "sent", "to": {"name": "x"}})
        deliver.log(self.inbox, {"id": "20261018-224300-aaaaaa", "kind": "ask", "at": 1, "status": "sent",
                                 "to": {"name": "x", "path": str(other)}})
        summary = self.ask_then_summary(GOOD.replace("open = []", '[[open]]\nquestion = "測り直す"\nholder = "20261018-224301-4e6a26"'))
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)

    def test_deliver_with_holders_stops_an_ask_in_an_unreached_ledger_or_that_failed(self):
        # 行が指さない会社の台帳はたどらない。届かなかった頼み（failed）は --todo が閉じた物と見て追わない
        self.shape('[[roles]]\nname = "調べ役"\nholders = true\n')
        other = pathlib.Path(self.root) / "other"
        git("init", "-q", str(other))
        theirs = os.path.join(str(other), ".git", "company", "inbox")
        os.makedirs(theirs)
        deliver.log(theirs, {"id": "20261018-224301-4e6a26", "kind": "ask", "at": 2, "status": "sent", "to": {"name": "x"}})
        deliver.log(self.inbox, {"id": "20261018-224300-bbbbbb", "kind": "ask", "at": 1, "status": "failed", "to": {"name": "x"}})
        for holder in ("20261018-224301-4e6a26", "20261018-224300-bbbbbb"):
            summary = self.ask_then_summary(GOOD.replace("open = []", f'[[open]]\nquestion = "測り直す"\nholder = "{holder}"'))
            rc, out = self.main(self.place, "--deliver", summary)
            self.assertEqual(rc, 2, out)
            self.assertIn(f"担当者の受付 {holder} は", out)
            self.assertEqual(self.prompts(), [])

    def test_deliver_stops_free_text_open_questions_and_text_before_the_first_heading(self):
        for text, said in ((GOOD + "\n## 残った疑問\nなし\n", "頭書きの [[open]] に 1 件ずつ書く"),
                           (GOOD.replace("+++\n## 結論", "+++\n前置き\n## 結論"), "最初の見出しの前に字がある"),
                           (GOOD.replace("open = []", "open = []\nnote = 1"), "知らないフィールド「note」"),
                           (GOOD.replace("+++\nopen = []\n+++\n", ""), "残った疑問（頭書きの open が無い")):
            summary = self.ask_then_summary(text)
            rc, out = self.main(self.place, "--deliver", summary)
            self.assertEqual(rc, 2, out)
            self.assertIn(said, out)
            self.assertEqual(self.prompts(), [])

    def test_sections_outside_the_required_items_are_delivered(self):
        # 決まった項目の外の見出しを、知らせずに落として送っていた（受付 6a65a9）
        summary = self.ask_then_summary(GOOD + "\n## 参考になりうる点\n- 1 つ目\n")
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        got = pathlib.Path(out.split("- 要約: ")[1].strip()).read_text(encoding="utf-8")
        self.assertIn("## 参考になりうる点\n- 1 つ目", got)
        self.assertIn("## 残った疑問\nなし", got)

    def test_an_ask_to_a_role_with_ask_holders_is_checked_when_it_has_open_items(self):
        self.shape('[[roles]]\nname = "調べ役"\nask_holders = true\n')
        rc, out = self.main(self.src, "--ask", "調べ", "--text", '+++\ntitle = "問い"\n[[open]]\nquestion = "担当者の無い疑問"\n+++\n問いです',
                            "--dry-run")
        self.assertEqual(rc, 2, out)
        self.assertIn("役の ask_holders の検査", out)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", '+++\ntitle = "問い"\n+++\n## 残った疑問\n- 文で書いた疑問', "--dry-run")
        self.assertEqual(rc, 2, out)
        self.assertIn("頭書きの [[open]] に 1 件ずつ書く", out)
        # 題の無い 2 行以上の頼みは止まり、書き方が返る（題を本文の行から拾わない。受付 c705d1）
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "## 困りごと\n本文", "--dry-run")
        self.assertEqual(rc, 2, out)
        self.assertIn("title = ", out)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "残った疑問のセクションの無い頼み", "--dry-run")
        self.assertEqual(rc, 0, out)

    def test_an_ask_runs_the_check_of_the_receiving_role_at_the_receiving_company(self):
        # 受ける会社の決まりで、ほかの会社から届く頼みも止める（242baa）。ゲートは受ける会社の代表の clone で走り、本文を JSON で受ける
        script = pathlib.Path(self.src, "gate.py")
        # 問いだけを受ける役のゲートは、文の語でなく頭書きの type（JSON の type。省けば task）で見分けられる（受付 5e6029）
        script.write_text("import json,sys,os\nd=json.load(sys.stdin)\nopen('seen.txt','w').write(os.getcwd())\n"
                          "sys.exit(1 if d['type'] != 'question' or not d.get('version') else 0)\n", encoding="utf-8")
        self.shape(f'[[roles]]\nname = "調べ役"\nask_check = {json.dumps(pathlib.Path(sys.executable).as_posix() + " gate.py")}\n')
        git("-C", self.src, "add", "gate.py")
        git("-C", self.src, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "-m", "gate")
        git("-C", self.src, "push", "-q", "origin", "HEAD:main")
        git("-C", self.src, "fetch", "-q", "origin")
        script.write_text("import sys\nsys.exit(0)\n", encoding="utf-8")   # 作業ツリーの物でなく、origin の既定のブランチの物が走る
        rc, out = self.main(self.src, "--ask", "調べ", "--text", "Question: which one?", "--dry-run")
        self.assertEqual(rc, 2, out)
        self.assertIn("のゲート（役「調べ役」の ask_check", out)
        rc, out = self.main(self.src, "--ask", "調べ", "--text", '+++\ntitle = "Which one?"\ntype = "question"\n+++\nA or B', "--dry-run")
        self.assertEqual(rc, 0, out)

    def test_deliver_outside_a_department_stops(self):
        summary = pathlib.Path(self.root).parent / "s.md"
        summary.write_text(GOOD, encoding="utf-8")
        rc, out = self.main(self.src, "--deliver", str(summary))
        self.assertEqual(rc, 2, out)
        self.assertIn("部署でない", out)

    def test_deliver_without_the_asker_window_posts_a_notice_and_closes_the_ask(self):
        # 頼み元の会話が終わって窓が無い: 待っても窓は開かず、部署の順番待ちが止まる（2026-10-17 の点検）。頼み元の名前に宛てた
        # 知らせを台帳に置いて納品済みにする（頼み元の名前の待ち受けが後で張られれば、その知らせで起きる）
        summary = self.ask_then_summary(GOOD)
        self.ports.term._panes = [p for p in self.ports.term._panes if p["pane_id"] != self.desk]
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 1, out)   # 頼み元の会話が一覧に居る（生きていて窓を決められないだけ）なら閉じない
        self.assertNotIn("delivered", gitx.worktree_attrs(self.place))
        listed = self.ports.list_sessions
        self.ports.list_sessions = lambda cdir, include_done=False: [s for s in listed(cdir, include_done) if s.get("sessionId") != "s-desk"]
        before = len(self.prompts())
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 0, out)
        self.assertIn("見つからない", out)
        notice, record = deliver.records(self.inbox)[-2:]   # 打ち直しの分
        self.assertEqual((record["status"], record["kind"]), (orders.POSTED, "deliver"))
        self.assertTrue(pathlib.Path(record["file"]).is_file())
        self.assertEqual((notice["kind"], notice["to"], notice["file"]), ("deliver", wake.address("src", "desk"), record["file"]))
        self.assertEqual(gitx.worktree_attrs(self.place)["delivered"], gitx.worktree_attrs(self.place)["ask"])
        self.assertEqual(len(self.prompts()), before)   # 窓には打たない

    def test_deliver_whose_send_fails_does_not_close_the_ask(self):
        # 窓は在るが打てなかった（herdr の誤り）: 窓が戻れば打ち直せるので、納品済みにしない
        summary = self.ask_then_summary(GOOD)
        self.ports.term.prompt = lambda *a, **k: (_ for _ in ()).throw(real_herdr.Error(["herdr"], "pane_not_found"))
        rc, out = self.main(self.place, "--deliver", summary)
        self.assertEqual(rc, 1, out)
        self.assertEqual(deliver.records(self.inbox)[-1]["status"], "failed")
        self.assertNotIn("delivered", gitx.worktree_attrs(self.place))

    def test_each_delivery_gets_its_own_file(self):
        summary = self.ask_then_summary(GOOD)
        self.assertEqual(self.main(self.place, "--deliver", summary)[0], 0)
        self.ports.now = lambda: 1
        self.assertEqual(self.main(self.place, "--deliver", summary, "--again")[0], 0)   # 同じ頼みの続き
        files = [r["file"] for r in deliver.records(self.inbox) if r["kind"] == "deliver"]
        self.assertEqual(len(set(files)), 2)
        self.assertTrue(all(pathlib.Path(f).is_file() for f in files))


if __name__ == "__main__":
    # 試験の偽物が日本語を print するので、Windows の既定のコードページ（cp1252 など）に依らず UTF-8 で書く
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    unittest.main()
