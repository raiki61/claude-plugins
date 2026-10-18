#!/usr/bin/env python3
"""attention/scripts/lib/catchup_html.py（/catchup の報告を 1 枚の HTML に描く部品）と、catchup.py の
--render・HTML の材料の規則を固定する。GitHub にも git にも VS Code にも触らない。

固定するのは: AI のフィールドの検査（直す所を日本語で 1 件 1 行）、雛形への差し込み（`</script>` で閉じない）、
置き場と index の組み直し（頭の行だけを読む・消えたページは落とす・新しい順）、差分の抜粋、
VS Code の socket の選び方（新しい順・生きているものだけ・全部で開く・0 で開かない）、Machine の設定の
足し方（他の key を消さない・控えを置く・注記の有る file は書かない）、PR の材料のターンと止めているもの、
雛形の作り（発言の Markdown を固定した版で描き生の HTML を描かない・ターンの動きは会話の流れの形・持ち主の値が無い）。
"""

import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

for _stream in (sys.stdout, sys.stderr):
    if hasattr(_stream, "reconfigure"):
        _stream.reconfigure(encoding="utf-8", errors="replace")

ROOT = pathlib.Path(__file__).resolve().parent.parent
SCRIPTS = ROOT / "attention" / "scripts"
sys.path.insert(0, str(SCRIPTS / "lib"))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


ch = load("catchup_html", SCRIPTS / "lib" / "catchup_html.py")
cu = load("catchup", SCRIPTS / "catchup.py")

DIFF = """diff --git a/app/retry.py b/app/retry.py
--- a/app/retry.py
+++ b/app/retry.py
@@ -10,3 +10,4 @@ def exit_code(err):
     doc
-    old = 1
+    new = 1
+    more = 2
     tail
diff --git a/docs/x.md b/docs/x.md
--- a/docs/x.md
+++ b/docs/x.md
@@ -1,1 +1,1 @@
-a
+b
"""


def fields(**over):
    base = {"headline": "#1 は私の番。", "where": "昨日指摘した。", "turn": "止めているのは私の返事。",
            "next": ["差分を読む", "返信する"], "unseen": [], "explain": ["背景", "変更", "使う側"]}
    base.update(over)
    return base


class FieldsTest(unittest.TestCase):
    def test_sample_passes(self):
        self.assertEqual(ch.validate_fields(ch.SAMPLE_FIELDS), [])
        self.assertEqual(ch.validate_fields(fields(figure=None)), [])

    def test_missing_and_unknown_keys_are_named_in_japanese(self):
        f = fields()
        del f["where"]
        f["headlin"] = "typo"
        errs = ch.validate_fields(f)
        self.assertTrue(any("where が無い" in e for e in errs), errs)
        self.assertTrue(any("知らないフィールド headlin" in e for e in errs), errs)

    def test_lists_have_bounds(self):
        self.assertTrue(any("next は 1〜6 個" in e for e in ch.validate_fields(fields(next=[]))))
        self.assertTrue(any("explain は 0〜6 個" in e for e in ch.validate_fields(fields(explain=["a"] * 7))))
        self.assertTrue(any("空でない文字列の並び" in e for e in ch.validate_fields(fields(next=["", "x"]))))
        self.assertTrue(any("空でない文字列の並び" in e for e in ch.validate_fields(fields(next="差分を読む"))))

    def test_figure_kind_is_chosen_by_the_writer_and_named(self):
        self.assertTrue(any("figure.kind は graph・sequence・compare" in e
                            for e in ch.validate_fields(fields(figure={"rows": []}))))
        self.assertTrue(any("figure.kind は" in e for e in ch.validate_fields(fields(figure={"kind": "flow", "rows": []}))))

    def test_graph_declares_boxes_and_relations_without_coordinates(self):
        ok = {"kind": "graph", "dir": "TB", "groups": [{"id": "job", "text": "毎晩のジョブ"}], "nodes": [
            {"id": "a", "text": "入口", "group": "job"},
            {"id": "b", "text": "原因の連鎖をたどる", "was": "1 段だけ見る", "sub": "包まれた例外"},
            {"id": "c", "text": "4 で終わる", "in": "after"}],
            "edges": [{"from": "a", "to": "b", "text": "渡す"}, {"from": "b", "to": "c", "in": "after", "dashed": True}]}
        self.assertEqual(ch.validate_fields(fields(figure=ok)), [])
        bad = {"kind": "graph", "dir": "RL", "nodes": [
            {"id": "a", "text": "x", "x": 10, "group": "nope", "tone": "red"},
            {"id": "a", "text": "y" * 41, "was": "z", "in": "after", "points": [1]}],
            "edges": [{"from": "a", "to": "q", "in": "later"}]}
        errs = ch.validate_fields(fields(figure=bad))
        for want in ("figure.dir は LR", "nodes[0] に知らないフィールド x", "nodes[0].group は figure.groups", "nodes[0].tone は good か bad",
                     "nodes[1].id a が重なっている", "nodes[1].text は 40 字まで", "nodes[1].was（変更前の字）",
                     "nodes[1].points は points.items を書いたときだけ", "edges[0].to は figure.nodes の id", "edges[0].in は before"):
            self.assertTrue(any(want in e for e in errs), (want, errs))
        too_many = {"kind": "graph", "nodes": [{"id": str(i), "text": "n"} for i in range(21)]}
        self.assertTrue(any("nodes は 1〜20 個" in e for e in ch.validate_fields(fields(figure=too_many))))

    def test_graph_boxes_point_at_numbered_changes_and_code(self):
        data = {"views": [{"id": "all", "text": DIFF}]}
        pts = {"items": [{"title": "終了コード", "after": "連鎖をたどる"}]}
        fig = {"kind": "graph", "nodes": [{"id": "a", "text": "入口", "points": [1], "code": [{"path": "app/retry.py"}]},
                                          {"id": "b", "text": "出口", "points": [2], "code": [{"path": "nope.py"}]}]}
        errs = ch.validate_fields(fields(points=pts, figure=fig), data=data)
        self.assertTrue(any("nodes[1].points は変更点の番号（1〜1）" in e for e in errs), errs)
        self.assertTrue(any("nodes[1].code[0].path nope.py は差分に無い" in e for e in errs), errs)
        self.assertFalse(any("nodes[0]" in e for e in errs), errs)
        code = ch.point_code(data, fields(points=pts, figure=fig))
        self.assertEqual(list(code["nodes"]), ["a"])
        self.assertIn("+    new = 1", code["nodes"]["a"][0]["text"])
        # 増える・変わる箱に番号を付け忘れると、押してもコードが開かない。差分の外の物は [] で無いと示す
        fig2 = {"kind": "graph", "nodes": [{"id": "a", "text": "受け口の制限", "in": "after"},
                                           {"id": "b", "text": "手で作る値", "in": "after", "points": []},
                                           {"id": "c", "text": "入口", "was": "旧い入口", "points": [1]}]}
        errs = ch.validate_fields(fields(points=pts, figure=fig2))
        self.assertTrue(any("nodes[0] はこの PR で増える・消える・変わる箱" in e for e in errs), errs)
        self.assertFalse(any("nodes[1]" in e or "nodes[2]" in e for e in errs), errs)

    def test_edges_carry_points_and_code_including_files_outside_the_diff(self):
        # 線は流れるデータ。受け先の型はこの PR で変えていなくても、PR の先頭の版から引いて見せる
        data = {"views": [{"id": "all", "text": DIFF}]}
        head = {"app/schema.py": ["import x", "", "class Order:", "    id: int", "    note: str"]}
        read = head.get
        pts = {"items": [{"title": "終了コード", "after": "連鎖をたどる"}]}
        fig = {"kind": "graph", "nodes": [{"id": "a", "text": "入口"}, {"id": "b", "text": "出口"}],
               "edges": [{"from": "a", "to": "b", "text": "注文を渡す", "in": "after", "points": [1],
                          "code": [{"path": "app/schema.py", "find": "class Order"}]},
                         {"from": "b", "to": "a", "text": "返す", "in": "after"},
                         {"from": "a", "to": "a", "code": [{"path": "app/none.py", "find": "x"}]},
                         {"from": "b", "to": "b", "code": [{"path": "app/schema.py", "find": "class Nope"}]}]}
        f = fields(points=pts, figure=fig)
        errs = ch.validate_fields(f, data=data, read=read)
        self.assertFalse(any("edges[0]" in e for e in errs), errs)
        self.assertTrue(any("edges[1] はこの PR で増える・消える線" in e for e in errs), errs)
        self.assertTrue(any("edges[2].code[0].path app/none.py は差分に無く、PR の先頭の版でも読めない" in e for e in errs), errs)
        self.assertTrue(any("edges[3].code[0].find 'class Nope'" in e for e in errs), errs)
        # 読めないとき（材料に head.oid が無い）は、差分の外は今まで通り止める
        self.assertTrue(any("edges[0].code[0].path app/schema.py は差分に無い" in e for e in ch.validate_fields(f, data=data)))
        code = ch.point_code(data, f, read)["edges"]["a>b"][0]
        self.assertTrue(code["outside"])
        self.assertIn("@@ -1,5 +1,5 @@", code["text"])
        self.assertIn(" class Order:", code["text"])
        page = ch.TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("この PR では変えていない", page)
        self.assertIn("POINT_EDGES", page)
        long = {"kind": "graph", "nodes": [{"id": "a", "text": "入口"}, {"id": "b", "text": "出口"}],
                "edges": [{"from": "a", "to": "b", "text": "あ" * (ch.EDGE_TEXT_CAP + 1)}]}
        self.assertTrue(any(f"edges[0].text は {ch.EDGE_TEXT_CAP} 字まで" in e for e in ch.validate_fields(fields(figure=long))))

    def test_sequence_lists_exchanges_between_actors(self):
        ok = {"kind": "sequence", "actors": [{"id": "ui", "text": "画面"}, {"id": "be", "text": "backend"}],
              "steps": [{"from": "ui", "to": "be", "text": "保存する", "in": "after"}, {"from": "be", "to": "be", "text": "検査する"},
                        {"from": "be", "to": "ui", "text": "古い返事", "in": "before", "tone": "bad"}]}
        self.assertEqual(ch.validate_fields(fields(figure=ok)), [])
        errs = ch.validate_fields(fields(figure={"kind": "sequence", "actors": [{"id": "ui", "text": "画面"}],
                                                 "steps": [{"from": "ui", "to": "db", "text": ""}]}))
        self.assertTrue(any("actors は 2〜6 個" in e for e in errs), errs)
        self.assertTrue(any("steps[0].text は空でない文字列" in e for e in errs), errs)

    def test_compare_figure(self):
        ok = {"kind": "compare", "rows": [{"name": "既定の待ち", "before": "30 秒", "after": "10 秒", "tone": "good"},
                                          {"name": "新しい設定", "after": "有効"}]}
        self.assertEqual(ch.validate_fields(fields(figure=ok)), [])
        errs = ch.validate_fields(fields(figure={"kind": "compare", "rows": [{"name": "x"}, {"before": "a"}]}))
        self.assertTrue(any("before か after の少なくとも一方" in e for e in errs), errs)
        self.assertTrue(any("rows[1].name" in e for e in errs), errs)

    def test_lead_is_one_short_sentence(self):
        self.assertEqual(ch.validate_fields(fields(lead="包まれた切断も終了コード 4 にする。")), [])
        self.assertTrue(any("lead は 120 字まで" in e for e in ch.validate_fields(fields(lead="あ" * 121))))

    def test_where_and_turn_are_lists_of_short_facts(self):
        self.assertEqual(ch.validate_fields(fields(where=["昨日指摘した", "作者が返信した"], turn=["止めているのは私の返事"])), [])
        errs = ch.validate_fields(fields(where=["あ" * 61], turn=["a"] * 5))
        self.assertTrue(any("where[0] は 60 字まで" in e for e in errs), errs)
        self.assertTrue(any("turn は 1〜4 個" in e for e in errs), errs)
        # 一言と次の一手も短く（番号と件名はページの頭に出る）
        errs = ch.validate_fields(fields(headline="あ" * 61, next=["い" * 61]))
        self.assertTrue(any("headline は 60 字まで" in e for e in errs), errs)
        self.assertTrue(any("next[0] は 60 字まで" in e for e in errs), errs)
        self.assertIn('facts(A.where, "nb-where")', ch.TEMPLATE.read_text(encoding="utf-8"))  # 箇条で描く

    def test_points_are_short_enough_to_compare_side_by_side(self):
        ok = {"items": [{"title": "上限を足す", "before": "いくらでも保存できた", "after": "1000 字までにする"}]}
        self.assertEqual(ch.validate_fields(fields(points=ok)), [])
        long = {"items": [{"title": "あ" * 31, "before": "い" * 81, "after": "う" * 81}]}
        errs = ch.validate_fields(fields(points=long))
        for want in ("title は 30 字まで", "before は 80 字まで", "after は 80 字まで"):
            self.assertTrue(any(want in e for e in errs), (want, errs))

    def test_terms_define_local_words_outside_the_sentences(self):
        ok = [{"term": "ターン", "means": "利用者の 1 回の質問と回答の 1 往復"}]
        self.assertEqual(ch.validate_fields(fields(terms=ok)), [])
        errs = ch.validate_fields(fields(terms=ok + [{"term": "ターン", "means": "x", "see": "y"}]))
        self.assertTrue(any("重なっている" in e for e in errs) and any("知らないフィールド see" in e for e in errs))
        self.assertTrue(any("terms は 1〜16 個" in e for e in ch.validate_fields(fields(terms=ok * 17))))
        self.assertTrue(any("means は 160 字まで" in e for e in ch.validate_fields(fields(terms=[{"term": "a", "means": "あ" * 161}]))))
        page = ch.TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("このセクションに出てくる語", page)  # 説明の前に一覧で出す
        self.assertIn("termify(", page)          # 文の中の同じ語に意味を付ける
        # rich() は要素の並びを返す。el() は並びを平らにするが、replaceChildren / append に直に渡すと
        # 並びが文字にされ「[object HTMLSpanElement]」と出る（コマ送りの字幕で起きた）
        for line in page.splitlines():
            if "replaceChildren(" in line:
                for i in [k for k in range(len(line)) if line.startswith("rich(", k)]:
                    self.assertTrue(line[:i].endswith("..."), line.strip())

    def test_points_code_refs_are_checked_against_the_diff(self):
        data = {"views": [{"id": "all", "text": DIFF}]}
        pts = {"items": [
            {"title": "終了コード", "before": "1 段だけ見る", "after": "連鎖をたどる",
             "code": [{"path": "app/retry.py", "find": "new = 1"}]},
            {"title": "説明", "after": "書き直す", "code": [{"path": "docs/x.md", "find": "b"}]}]}
        self.assertEqual(ch.validate_fields(fields(points=pts), data=data), [])
        code = ch.point_code(data, fields(points=pts))["points"]
        self.assertEqual([c["path"] for c in code[0]], ["app/retry.py"])
        self.assertIn("+    new = 1", code[0][0]["text"])
        self.assertTrue(code[0][0]["text"].startswith("diff --git a/app/retry.py"))
        bad = {"items": [
            {"lane": "他", "title": "t", "after": "a", "code": [{"path": "nope.py"}]},
            {"title": "t", "after": "a", "code": [{"path": "app/retry.py", "lines": [10, 12]}]},
            {"title": "t", "after": "a", "code": [{"path": "app/retry.py", "find": "無い語"}]}]}
        errs = ch.validate_fields(fields(points=bad), data=data)
        self.assertTrue(any("items[0] に知らないフィールド lane" in e for e in errs), errs)
        self.assertTrue(any("nope.py は差分に無い" in e for e in errs), errs)
        # 行番号では指さない（行を知るには差分の枠まで読むことになり、読む量が大きく増える）
        self.assertTrue(any("items[1].code[0] に知らないフィールド lines（使えるフィールドは path・find）" in e for e in errs), errs)
        self.assertTrue(any("items[2].code[0] に当たる変更の塊が無い" in e for e in errs), errs)
        # 材料が無い（会話の話題）なら、指す先の在る無しは見ない
        self.assertEqual(ch.validate_fields(fields(points={"items": [{"title": "t", "after": "a",
                                                                       "code": [{"path": "x"}]}]})), [])
        self.assertTrue(any("points.items は 1〜10 個" in e
                            for e in ch.validate_fields(fields(points={"items": []}))))

    def test_page_carries_the_code_of_points_and_boxes_and_the_layout_library(self):
        data = dict(ch.SAMPLE_DATA)
        f = dict(ch.SAMPLE_FIELDS)
        page = ch.build_html(ch.TEMPLATE.read_text(encoding="utf-8"), data, f, ch.index_entry(data, f, "x.html", ch.dt.datetime(2026, 1, 1)))
        self.assertIn('"code": {"points": [[{"path": "app/retry.py"', page)
        self.assertIn('"nodes": {"walk": [{"path": "app/retry.py"', page)
        self.assertIn("埋め込み: @dagrejs/dagre 3.1.1", page)
        self.assertIn("Copyright (c) 2012-2014 Chris Pettitt", page)

    def test_graph_layout_keeps_text_at_full_size_before_height(self):
        # 高さだけで形を選ぶと、縮めた形ほど低くて勝ち、横に長い図の字が 9px まで小さくなった。
        # 等倍以上で入る形を先に絞る
        page = ch.TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("cands.filter(c => c.zoom >= 1", page)

    def test_clicking_a_box_or_line_opens_a_card_beside_it_without_moving_the_page(self):
        # 凡例の項へ飛ばしたりコードの窓をいきなり開いたりすると、読んでいた所を見失う。押した所の横に札を出し、
        # コードは札のボタンを押したときだけ開く
        page = ch.TEMPLATE.read_text(encoding="utf-8")
        self.assertIn("function showPop(", page)
        self.assertNotIn("scrollIntoView", page.split("function showPop(")[1].split("\nfunction ")[0])
        self.assertNotIn("function openPoints(", page)

    def test_several_figures_of_different_kinds_are_numbered_in_errors(self):
        figs = [{"kind": "compare", "rows": [{"name": "待ち", "before": "30 秒", "after": "10 秒"}]},
                {"kind": "table", "columns": ["読む", "書く"], "rows": [{"label": "admin", "cells": ["✓", {"text": "✓", "was": "–"}]}]}]
        self.assertEqual(ch.validate_fields(fields(figure=figs)), [])
        errs = ch.validate_fields(fields(figure=figs + [{"kind": "table", "columns": ["a"], "rows": [{"label": "x", "cells": []}]}]))
        self.assertTrue(any(e.startswith("figure[2].rows[0].cells は列と同じ 1 個") for e in errs), errs)
        self.assertTrue(any("figure を並びにするなら 1〜3 個" in e for e in ch.validate_fields(fields(figure=figs * 2))))

    def test_screen_is_made_of_fixed_parts(self):
        ok = {"kind": "screen", "title": "設定", "items": [
            {"type": "tabs", "options": ["通知", "アカウント"], "value": "通知"},
            {"type": "textarea", "label": "通知の宛先", "hint": "カンマで区切る", "in": "after"},
            {"type": "select", "label": "頻度", "value": "毎日", "was": "毎週"},
            {"type": "button", "label": "保存", "primary": True, "disabled": True}]}
        self.assertEqual(ch.validate_fields(fields(figure=ok)), [])
        errs = ch.validate_fields(fields(figure={"kind": "screen", "items": [{"type": "canvas"}, {"type": "button"},
                                                                              {"type": "field", "label": "x", "primary": "yes"}]}))
        for want in ("items[0].type は heading", "items[1].label は空でない", "items[2].primary は true か false"):
            self.assertTrue(any(want in e for e in errs), (want, errs))

    def test_steps_place_each_step_in_a_lane(self):
        ok = {"kind": "steps", "lanes": [{"id": "dev", "text": "リポジトリ"}, {"id": "ops", "text": "運用"}],
              "steps": [{"lane": "dev", "text": "マージする", "tag": "この PR"}, {"lane": "ops", "text": "手で流す", "when": "マージの後"}]}
        self.assertEqual(ch.validate_fields(fields(figure=ok)), [])
        errs = ch.validate_fields(fields(figure={"kind": "steps", "lanes": [{"id": "dev", "text": "x"}], "steps": [{"lane": "qa", "text": "t"}]}))
        self.assertTrue(any("steps[0].lane は figure.lanes の id" in e for e in errs), errs)

    def test_graph_box_can_list_columns(self):
        ok = {"kind": "graph", "nodes": [{"id": "t", "text": "users", "fields": [{"name": "id", "type": "uuid"},
                                                                                {"name": "notify_email", "type": "bool", "in": "after"}]}]}
        self.assertEqual(ch.validate_fields(fields(figure=ok)), [])
        self.assertTrue(any("fields[0].name" in e for e in ch.validate_fields(
            fields(figure={"kind": "graph", "nodes": [{"id": "t", "text": "users", "fields": [{"type": "uuid"}]}]}))))

    def test_free_html_figure_allows_rich_svg_but_nothing_that_leaves_the_page_or_runs(self):
        ok = ('<svg viewBox="0 0 100 40"><style>.a{fill:var(--fgColor-success)}</style><rect class="a" width="10" height="10">'
              '<animate attributeName="width" values="10;90;10" dur="4s" repeatCount="indefinite"/></rect>'
              '<text x="4" y="30" text-anchor="start">容量</text></svg><div style="display:grid">表</div>')
        self.assertEqual(ch.validate_fields(fields(figure={"kind": "html", "html": ok})), [])
        bad = ('<script>alert(1)</script><svg onload="x()"><image href="https://e.example/x.png"/></svg>'
               '<div style="background:url(https://e.example)">a</div><style>@import "x.css";</style><a href="https://e.example">x</a>'
               '<svg><set attributeName="href" to="javascript:alert(1)"/></svg>')
        errs = ch.validate_fields(fields(figure={"kind": "html", "html": bad}))
        for want in ("<script> は使えない", "onload（イベント）", "<image> は使えない", "url( / @import", "<a> は使えない",
                     "<style> に url( / @import", "javascript:"):
            self.assertTrue(any(want in e for e in errs), (want, errs))
        self.assertTrue(any("20000 字まで" in e for e in ch.validate_fields(fields(figure={"kind": "html", "html": "<p>a</p>" * 3000}))))

    def test_play_frames_light_declared_boxes_and_lines(self):
        g = {"kind": "graph", "nodes": [{"id": "a", "text": "壊す"}, {"id": "b", "text": "回す"}], "edges": [{"from": "a", "to": "b"}],
             "play": [{"text": "壊す", "nodes": ["a"]}, {"text": "回す", "nodes": ["b"], "edges": ["a>b"]}]}
        self.assertEqual(ch.validate_fields(fields(figure=g)), [])
        bad = dict(g, play=[{"text": "x", "nodes": ["q"], "edges": ["b>a"]}, {"text": "y"}])
        errs = ch.validate_fields(fields(figure=bad))
        for want in ("play[0].nodes は figure.nodes の id", "play[0].edges は figure.edges の線を \"from>to\"", "play[1] は光らせる箱か線を 1 つ以上"):
            self.assertTrue(any(want in e for e in errs), (want, errs))
        self.assertTrue(any("play は 2〜10 個" in e for e in ch.validate_fields(fields(figure=dict(g, play=g["play"][:1])))))
        seq = {"kind": "sequence", "play": "yes", "actors": [{"id": "a", "text": "a"}, {"id": "b", "text": "b"}],
               "steps": [{"from": "a", "to": "b", "text": "t"}]}
        self.assertTrue(any("figure.play は true か false" in e for e in ch.validate_fields(fields(figure=seq))))
        self.assertIn("function player(frames, apply)", ch.TEMPLATE.read_text(encoding="utf-8"))

    def test_title_is_required_only_without_material(self):
        self.assertEqual(ch.validate_fields(fields()), [])
        self.assertTrue(any("title が無い" in e for e in ch.validate_fields(fields(), need_title=True)))
        self.assertEqual(ch.validate_fields(fields(title="今の修正"), need_title=True), [])

    def test_not_an_object(self):
        self.assertEqual(ch.validate_fields([]), ["フィールドの JSON は {…}（オブジェクト）にする"])


class DiffTest(unittest.TestCase):
    def test_parse_and_summary(self):
        files = ch.parse_diff(DIFF)
        self.assertEqual([(f["path"], f["add"], f["del"]) for f in files], [("app/retry.py", 2, 1), ("docs/x.md", 1, 1)])
        s = ch.summary(files, {"docs/x.md"})
        self.assertEqual([x["since"] for x in s], [False, True])
        self.assertTrue(s[0]["anchor"].startswith("diff-") and len(s[0]["anchor"]) == 5 + 64)

    def test_quoted_path(self):
        d = ('diff --git "a/docs/\\346\\227\\245.md" "b/docs/\\346\\227\\245.md"\n'
             '--- "a/docs/\\346\\227\\245.md"\n+++ "b/docs/\\346\\227\\245.md"\n@@ -1 +1 @@\n-a\n+b\n')
        self.assertEqual(ch.parse_diff(d)[0]["path"], "docs/日.md")

    def test_excerpt_around_the_commented_line(self):
        f = ch.parse_diff(DIFF)[0]
        ex = ch.excerpt(f, 12)
        self.assertIn("@@ -10,3 +10,4 @@ def exit_code(err):", ex)
        self.assertIn("+    more = 2", ex)
        self.assertIsNone(ch.excerpt(f, 99))

    def test_context_excerpt_for_lines_outside_the_diff(self):
        ex = ch.context_excerpt("a.py", [f"line{i}" for i in range(1, 21)], 10)
        self.assertIn("@@ -5,10 +5,10 @@", ex)
        self.assertIn(" line10", ex)
        self.assertIsNone(ch.context_excerpt("a.py", ["x"], 5))

    def test_filter_diff_keeps_only_named_files(self):
        out = ch.filter_diff(DIFF, ["docs/x.md"])
        self.assertEqual([f["path"] for f in ch.parse_diff(out)], ["docs/x.md"])


class PageTest(unittest.TestCase):
    def data(self, page="o-r/1", title="件名", turn=None):
        d = json.loads(json.dumps(ch.SAMPLE_DATA))
        d["page"], d["head"]["title"] = page, title
        if turn:
            d["head"]["turn"] = turn
        return d

    def test_script_close_in_data_does_not_end_the_slot(self):
        d = self.data(title="</script><script>alert(1)</script>")
        html = ch.build_html(ch.TEMPLATE.read_text(encoding="utf-8"), d, fields(),
                             ch.index_entry(d, fields(), "o-r/1.html", ch.dt.datetime(2026, 10, 15)))
        self.assertNotIn("</script><script>alert", html)
        self.assertIn("\\u003c/script>", html)
        self.assertIn("<title>#1 &lt;/script&gt;", html)
        self.assertNotIn(ch.DATA_SLOT, html)

    def test_slot_strings_in_untrusted_text_do_not_steal_the_slots(self):
        title = f"x {ch.DATA_SLOT} {ch.INDEX_SLOT} y"
        d = self.data(title=title)
        entry = ch.index_entry(d, fields(), "o-r/1.html", ch.dt.datetime(2026, 10, 15))
        page = ch.build_html(ch.TEMPLATE.read_text(encoding="utf-8"), d, fields(), entry)
        self.assertNotIn(f'id="data">{ch.DATA_SLOT}', page)
        self.assertIn('"title": "x /*__DATA__*/null', page.replace("\\u003c", "<"))
        self.assertNotIn(f">{ch.INDEX_SLOT}<", page)

    def test_write_page_overwrites_and_rebuilds_index(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = pathlib.Path(tmp)
            tpl = ch.TEMPLATE.read_text(encoding="utf-8")
            t1, t2 = ch.dt.datetime(2026, 10, 15, 9), ch.dt.datetime(2026, 10, 15, 10)
            p1, line = ch.write_page(self.data("o-r/1", "一つ目"), fields(), root, tpl, t1)
            self.assertEqual(p1, root / "o-r" / "1.html")
            self.assertEqual(line, "#1 一つ目 — 私の番。次: 差分を読む")
            wait = {"kind": "wait", "label": "待ち", "reasons": [], "detail": "作者 hanako 待ち"}
            ch.write_page(self.data("o-r/2", "二つ目", wait), fields(next=["待つ"]), root, tpl, t2)
            ch.write_page(self.data("o-r/1", "一つ目の直し"), fields(), root, tpl, t1)  # 同じ件は上書き
            (root / "o-r" / "stray.html").write_text("<html>行の無いページ</html>", encoding="utf-8")
            entries = ch.collect_entries(root)
            self.assertEqual([(e["page"], e["title"]) for e in entries], [("o-r/2.html", "二つ目"), ("o-r/1.html", "一つ目の直し")])
            self.assertEqual(entries[0]["turn"], "作者 hanako 待ち")  # 待ちは誰を待つかまで
            index = (root / "index.html").read_text(encoding="utf-8")
            self.assertIn('href="o-r/2.html"', index)
            self.assertIn("次: 待つ", index)
            (root / "o-r" / "2.html").unlink()
            ch.rebuild_index(root)
            self.assertNotIn("o-r/2.html", (root / "index.html").read_text(encoding="utf-8"))

    def test_topic_page_without_material(self):
        self.assertEqual(ch.page_rel(None, {"title": "今の修正"}), ch.page_rel(None, {"title": "今の修正"}))
        self.assertTrue(ch.page_rel(None, {"title": "今の修正"}).startswith("topics/"))
        self.assertEqual(ch.page_rel({"page": "o-r/commit-abc1234"}, {}), "o-r/commit-abc1234.html")


class TemplateTest(unittest.TestCase):
    """雛形の作りの決まり。ブラウザで描く所は試験で動かせないので、作りの印で固定する。"""
    TPL = (ROOT / "attention" / "templates" / "catchup.html").read_text(encoding="utf-8")

    def test_comment_markdown_is_drawn_by_the_pinned_parser_with_raw_html_escaped(self):
        # 発言の本文は GitHub と同じく Markdown で描く。生の HTML・javascript: のリンク・外の画像は描かせない
        self.assertIn("marked 15.0.12 marked.min.js（MIT", self.TPL)
        self.assertIn("marked v15.0.12", self.TPL)
        self.assertRegex(self.TPL, r"html\(tok\) \{ return esc\(")
        self.assertIn("safeHref", self.TPL)
        self.assertRegex(self.TPL, r"image\(tok\) \{[^\n]*<a href")
        self.assertNotIn("</script", self.TPL.split("marked 15.0.12 marked.min.js", 1)[1].split("埋め込みここまで", 1)[0])

    def test_turn_history_is_a_folded_log_inside_the_turn_section(self):
        # ターンの動きは、いまのターンのセクションの中に畳んだ記録として置く（別のセクションの縦の流れは、同じことを文と 2 回言って読みにくかった）
        self.assertIn('class: "evlog"', self.TPL)
        self.assertNotIn('class: "timeline"', self.TPL)
        self.assertNotIn("laneFigure", self.TPL)

    def test_no_owner_specific_values(self):
        for s in ("my_notes", "/Users/", "raiki61", "190578"):
            self.assertNotIn(s, self.TPL)


class VscodeTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = pathlib.Path(self.tmp.name)
        self.socks = []
        for i, name in enumerate(["old", "mid", "new"]):
            p = self.dir / f"vscode-ipc-{name}.sock"
            p.write_text("")
            os.utime(p, (1000 + i, 1000 + i))
            self.socks.append(str(p))
        self.env = {"TMPDIR": str(self.dir) + os.sep}

    def tearDown(self):
        self.tmp.cleanup()

    def fake(self, live):
        calls = []

        def run(args, env):
            calls.append((args[1:], env.get("VSCODE_IPC_HOOK_CLI")))
            return 0 if env.get("VSCODE_IPC_HOOK_CLI") in live else 1
        return run, calls

    def test_sockets_newest_first_with_stale_hook(self):
        env = dict(self.env, VSCODE_IPC_HOOK_CLI=self.socks[0])
        self.assertEqual(ch.ipc_sockets(env), list(reversed(self.socks)))

    def test_opens_on_every_live_socket_including_the_older_one(self):
        run, calls = self.fake({self.socks[0], self.socks[2]})
        msg = ch.open_in_vscode("/p/1.html", env=self.env, run=run, which=lambda n: "/bin/code")
        self.assertEqual(msg, "VS Code の窓 2 個で開いた")
        opened = [s for a, s in calls if a[0] == "--reuse-window"]
        self.assertEqual(opened, [self.socks[2], self.socks[0]])
        self.assertEqual(sum(1 for a, _ in calls if a == ["--status"]), 3)

    def test_no_live_socket_or_no_cli_or_disabled_is_not_an_error(self):
        run, calls = self.fake(set())
        self.assertIn("繋がっていない", ch.open_in_vscode("/p", env=self.env, run=run, which=lambda n: "/bin/code"))
        self.assertIn("code が見つからない", ch.open_in_vscode("/p", env=self.env, home=self.dir, run=run,
                                                         which=lambda n: None))
        calls.clear()
        self.assertIn("ATTENTION_CATCHUP_OPEN=0", ch.open_in_vscode("/p", env=dict(self.env, ATTENTION_CATCHUP_OPEN="0"),
                                                                   run=run, which=lambda n: "/bin/code"))
        self.assertEqual(calls, [])

    def test_failure_inside_is_swallowed(self):
        def boom(args, env):
            raise RuntimeError("x")
        self.assertIn("開けなかった", ch.open_in_vscode("/p", env=self.env, run=boom, which=lambda n: "/bin/code"))

    def test_remote_cli_fallback_picks_newest_server(self):
        for i, sid in enumerate(["Stable-a", "Stable-b"]):
            p = self.dir / ".vscode-server" / "cli" / "servers" / sid / "server" / "bin" / "remote-cli" / "code"
            p.parent.mkdir(parents=True)
            p.write_text("")
            os.utime(p, (2000 - i * 500, 2000 - i * 500))
        self.assertIn("Stable-a", ch.code_cli(self.dir, which=lambda n: None))


class SettingsTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = pathlib.Path(self.tmp.name) / "settings.json"

    def tearDown(self):
        self.tmp.cleanup()

    def test_adds_both_keeps_others_and_backs_up(self):
        self.path.write_text(json.dumps({"a.b": 1, ch.ASSOC_KEY: {"*.x": "v"}}), encoding="utf-8")
        lines, ok = ch.merge_settings(self.path, now=ch.dt.datetime(2026, 10, 15, 9, 0, 0))
        self.assertTrue(ok, lines)
        got = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(got["a.b"], 1)
        self.assertEqual(got[ch.ASSOC_KEY], {"*.x": "v", ch.ASSOC_GLOB: ch.VIEW_TYPE})
        self.assertEqual(got[ch.AUTO_REFRESH[0]], ch.AUTO_REFRESH[1])
        backup = self.path.with_name("settings.json.bak-20261015-090000")
        self.assertEqual(json.loads(backup.read_text(encoding="utf-8")), {"a.b": 1, ch.ASSOC_KEY: {"*.x": "v"}})
        self.assertEqual(ch.merge_settings(self.path)[0], [f"設定は揃っている（{self.path}）"])

    def test_commas_and_brackets_inside_strings_survive_the_rewrite(self):
        self.path.write_text(json.dumps({"editor.wordSeparators": "a,]b", "x": "[1,}"}), encoding="utf-8")
        lines, ok = ch.merge_settings(self.path)
        self.assertTrue(ok, lines)
        got = json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual((got["editor.wordSeparators"], got["x"]), ("a,]b", "[1,}"))

    def test_missing_file_is_created_without_backup(self):
        lines, ok = ch.merge_settings(self.path)
        self.assertTrue(ok)
        self.assertEqual(ch.settings_gaps(json.loads(self.path.read_text(encoding="utf-8"))), [])
        self.assertEqual(sorted(p.name for p in self.path.parent.iterdir()), ["settings.json"])

    def test_file_with_comments_is_not_rewritten(self):
        raw = '{\n  // 私の注記\n  "a": 1,\n}\n'
        self.path.write_text(raw, encoding="utf-8")
        lines, ok = ch.merge_settings(self.path)
        self.assertFalse(ok)
        self.assertIn("注記が有る", lines[0])
        self.assertEqual(self.path.read_text(encoding="utf-8"), raw)
        self.assertEqual(ch.read_settings(self.path)[0], {"a": 1})  # 注記と末尾の , を落として読める

    def test_check_mode_changes_nothing(self):
        home = pathlib.Path(self.tmp.name)
        code, lines = ch.setup(check=True, home=home, env={"TMPDIR": str(home)}, run=lambda a, e: 1,
                               which=lambda n: "/bin/code")
        self.assertEqual(code, 1)
        text = "\n".join(lines)
        self.assertIn("生きている VS Code の窓が無い", text)
        self.assertIn("拡張 Simple HTML Viewer が入っていない", text)
        self.assertIn(ch.ASSOC_GLOB, text)
        self.assertFalse((home / ".vscode-server").exists())
        self.assertFalse((home / ".cache").exists())


# ---- catchup.py の HTML の材料 ----

ME = "me"


def user(login):
    return {"__typename": "User", "login": login}


def conn(nodes):
    return {"totalCount": len(nodes), "nodes": nodes}


def pr_node(**over):
    node = {
        "__typename": "PullRequest", "number": 7, "title": "直し", "url": "https://github.com/o/r/pull/7",
        "state": "OPEN", "isDraft": False, "createdAt": "2026-09-01T00:00:00Z", "body": "",
        "additions": 3, "deletions": 1, "changedFiles": 1, "mergeable": "CONFLICTING",
        "reviewDecision": "REVIEW_REQUIRED", "author": user("hanako"),
        "baseRepository": {"defaultBranchRef": {"name": "main"}}, "baseRefName": "main", "baseRef": None,
        "isCrossRepository": False, "suggestedReviewers": [], "assignees": conn([]),
        "reviewRequests": conn([{"requestedReviewer": user(ME)}]), "closingIssuesReferences": conn([]),
        "comments": conn([]), "reviews": conn([]),
        "reviewThreads": conn([{"isResolved": False, "isOutdated": False, "path": "app/retry.py", "line": 12,
                                "comments": conn([
                                    {"createdAt": "2026-09-01T01:00:00Z", "body": "包まれた例外も見て", "url": "u1",
                                     "author": user(ME), "originalCommit": {"oid": "a" * 40}},
                                    {"createdAt": "2026-09-01T02:00:00Z", "body": "> 引用\n直しました", "url": "u2",
                                     "author": user("hanako"), "originalCommit": None}])}]),
        "allCommits": conn([]),
        "head": {"nodes": [{"commit": {"oid": "b" * 40, "statusCheckRollup": {"contexts": conn([
            {"__typename": "CheckRun", "name": "test", "status": "COMPLETED", "conclusion": "FAILURE",
             "detailsUrl": "https://github.com/o/r/actions/runs/1/job/2"}])}}}]},
        "timelineItems": conn([]),
    }
    node.update(over)
    return node


class PageItemTest(unittest.TestCase):
    def build(self, node, with_threads=True, ci=None):
        ev, refs, unlinked = cu.collect_events(node, ME)
        anchor, kind = cu.find_anchor(ev, node, ME)
        return cu.page_item(node, "o", "r", ME, ev, refs, unlinked, anchor, kind, cu.collect_caps(node), full=False,
                            stacked=(), since=None, with_map=False, with_threads=with_threads, ci=ci,
                            read_lines=lambda p: [f"l{i}" for i in range(1, 30)], local_text="ブランチ: 移った")

    def test_turn_status_threads_and_unseen(self):
        page = self.build(pr_node(), ci=([{"name": "test", "url": "x", "log": ["##[error]boom"], "note": ""}], 0))
        self.assertEqual(page["page"], "o-r/7")
        self.assertEqual(page["head"]["turn"]["kind"], "mine")
        self.assertEqual(page["head"]["role"], "レビュアー")
        self.assertEqual(page["anchor_label"], "前回から")
        tones = {s["key"]: s["tone"] for s in page["status"]}
        self.assertEqual(tones, {"threads": "mine", "ci": "bad", "approval": "warn", "merge": "bad"})
        th = page["threads"][0]
        self.assertEqual((th["who"], th["quote"], th["href"], th["mine"]["quote"]), ("hanako", "直しました", "u2", "包まれた例外も見て"))
        self.assertIn("@@ -7,10 +7,10 @@", th["excerpt"])  # 差分が無いので head の前後の行
        self.assertIsNone(th["changed"])  # 私の痕跡の基準が無ければ「変わったか」は分からない
        self.assertEqual(page["ci"][0]["name"], "test")
        self.assertEqual(page["local"], "ブランチ: 移った")
        self.assertIn("GitHub の外（チャット・口頭・メール）でのやり取り", page["unseen"])
        self.assertEqual([e["who"] for e in page["events"]], ["hanako"])
        json.dumps(page)  # JSON に書ける（datetime を持ち込まない）

    def test_closed_item_is_done_and_wait_names_whom(self):
        self.assertEqual(self.build(pr_node(state="MERGED"))["head"]["turn"]["label"], "済み")
        quiet = pr_node(reviewRequests=conn([]), reviewThreads=conn([]))
        turn = self.build(quiet)["head"]["turn"]
        self.assertEqual((turn["kind"], turn["detail"]), ("wait", "作者 hanako 待ち"))


class OutWiringTest(unittest.TestCase):
    """--out は文字の材料と一緒に描く材料を書く。描く材料を組めなくても、文字の材料は落とさない。"""

    def run_main(self, page_commit):
        import contextlib
        import io
        saved = (cu.resolve_target, cu.render_commit, cu.page_commit)
        cu.resolve_target = lambda token, repo: (None, None, "oid", "commit")
        cu.render_commit = lambda oid, cwd=None, frame=None, full=False: "COMMIT"
        cu.page_commit = page_commit
        buf = io.StringIO()
        try:
            with contextlib.redirect_stdout(buf):
                rc = cu.main(["HEAD", "--out"])
        finally:
            cu.resolve_target, cu.render_commit, cu.page_commit = saved
        return rc, buf.getvalue()

    def paths(self, out):
        import re
        return [m for m in re.findall(r"(\S+\.(?:txt|json)) に書いた", out)]

    def test_material_json_is_written_next_to_the_report(self):
        rc, out = self.run_main(lambda oid, cwd=None: {"schema": ch.SCHEMA, "page": "x/commit-1"})
        files = self.paths(out)
        try:
            self.assertEqual(rc, 0)
            self.assertEqual(len(files), 2, out)
            self.assertEqual(json.loads(pathlib.Path(files[1]).read_text(encoding="utf-8"))["page"], "x/commit-1")
            self.assertEqual(pathlib.Path(files[0]).parent, pathlib.Path(files[1]).parent)
            self.assertIn("--render", out)
        finally:
            for f in files:
                os.unlink(f)

    def test_failure_to_build_keeps_the_report(self):
        def boom(oid, cwd=None):
            raise RuntimeError("壊れた")
        rc, out = self.run_main(boom)
        files = self.paths(out)
        try:
            self.assertEqual(rc, 0)
            self.assertEqual(len(files), 1, out)
            self.assertIn("COMMIT", pathlib.Path(files[0]).read_text(encoding="utf-8"))
            self.assertIn("描く材料を組めなかった（RuntimeError: 壊れた）", out)
        finally:
            for f in files:
                os.unlink(f)


class RenderCliTest(unittest.TestCase):
    def run_cli(self, *args, home):
        env = dict(os.environ, HOME=str(home), USERPROFILE=str(home), ATTENTION_CATCHUP_OPEN="0",
                   PYTHONIOENCODING="utf-8", PYTHONDONTWRITEBYTECODE="1")
        return subprocess.run([sys.executable, str(SCRIPTS / "catchup.py"), *args], env=env,
                              capture_output=True, encoding="utf-8", errors="replace")

    def test_render_prints_path_and_one_line(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            data, flds = home / "d.json", home / "f.json"
            d = json.loads(json.dumps(ch.SAMPLE_DATA))
            d["page"] = "o-r/1"
            data.write_text(json.dumps(d), encoding="utf-8")
            flds.write_text(json.dumps(fields()), encoding="utf-8")
            r = self.run_cli("--render", str(data), str(flds), home=home)
            self.assertEqual(r.returncode, 0, r.stderr)
            out = r.stdout.splitlines()
            page = home / ".cache" / "attention" / "catchup" / "o-r" / "1.html"
            self.assertEqual(out, [str(page), "#1 見本: 包まれた切断も終了コード 4 にする — 私の番。次: 差分を読む"])
            self.assertTrue((page.parent.parent / "index.html").exists())
            self.assertIn("ATTENTION_CATCHUP_OPEN=0", r.stderr)

    def test_bad_fields_exit_2_with_reasons(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            flds = home / "f.json"
            flds.write_text(json.dumps({"headline": "x"}), encoding="utf-8")
            r = self.run_cli("--render", "-", str(flds), home=home)
            self.assertEqual(r.returncode, 2)
            self.assertIn("直す所が", r.stderr)
            self.assertIn("title が無い", r.stderr)
            self.assertFalse((home / ".cache").exists())

    def test_wrong_material_version_stops(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = pathlib.Path(tmp)
            data, flds = home / "d.json", home / "f.json"
            data.write_text(json.dumps({"schema": 0}), encoding="utf-8")
            flds.write_text(json.dumps(fields()), encoding="utf-8")
            r = self.run_cli("--render", str(data), str(flds), home=home)
            self.assertNotEqual(r.returncode, 0)
            self.assertIn("形が違う", r.stderr)


if __name__ == "__main__":
    unittest.main(verbosity=1)
