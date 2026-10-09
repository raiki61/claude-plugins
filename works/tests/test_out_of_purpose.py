"""判定が凍結した目的の外として単位にしなかった所見を、次の run の依頼へ運ぶか（core の outpurpose。FAST: 偽の盤面と一時の
置き場のファイルだけ。git・子のプロセスなし）。

実の利用者の run f57a5374 で、P1 の局所レビューが [block] 3 件を仕組み・実測つきで挙げたが、判定役は目的の外として framing の
散文に名だけ残し（split にもしない）、next-request.json は 1 件も運ばなかった。利用者は依頼を手で書き直し、run をもう 1 本
回した。判定役が構造の欄 out_of_purpose に {source, where, why_outside} で名指し、受け付けが盤面の材料の行に当てて確かめ、
次の run の依頼が材料の行の全部の欄（where・text・mechanism・measured・false_positive_if）を運ぶ。
"""
import json
import pathlib
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(ROOT / "blk-judge" / "lib"))
import accept  # noqa: E402
import carry  # noqa: E402
import outpurpose  # noqa: E402

CR = {"where": "app/compute_logs/manager.py:27-58",
      "text": "[block] 自作の Compute Log Manager が親クラスの __init__ を呼ばず、2 つの属性が未初期化",
      "mechanism": "親の display_path_for_type がこの 2 属性を読む",
      "measured": "3 メソッドとも AttributeError を確認",
      "false_positive_if": "画面が capturedLogsMetadata を投げない版なら誤り"}
DOCKER = {"where": "Dockerfile:15-18", "text": "[block] builder 段に proxy CA の受け取りが無い", "measured": "proxy_ca が 0 件"}
HYG = {"where": "docker-entrypoint.sh (until dagster instance migrate)", "text": "回数の上限も期限も無い",
       "mechanism": "Postgres に繋がらなければ永久に再試行する", "false_positive_if": "起動の期限を外で切るなら当たらない"}
ASKED = {"where": "storage.py update_latest", "text": "依頼の行"}
OUTPUTS = {
    "p1.local_review": {"material": {"status": "found"}, "findings": [
        {"skill": "/code-review", "invoked": True, "items": [], "failed": "本文なし"},
        {"skill": "pr-review-toolkit:code-reviewer", "invoked": True, "items": [CR, DOCKER]}]},
    "p1.hygiene": {"findings": [HYG], "seen": "差分全体"},
    "p2.diagnose": {"units": [{"key": "u", "label": "block", "reason": "材料の行でない", "where": "x", "text": "y"}]},
}
OOP = [{"source": "局所の findings（pr-review-toolkit:code-reviewer）", "where": CR["where"],
        "why_outside": "凍結した目的は Manifest の世代の順で、Compute Log の初期化は目的の外"},
       {"source": "素材 hygiene", "where": HYG["where"], "why_outside": "起動の殻の再試行は Manifest の目的の外にある"}]


def fake_board(tmp, rnd=1, outputs=OUTPUTS, requests=()):
    return types.SimpleNamespace(
        dir=pathlib.Path(tmp), round=rnd, state={"outputs": {k: {"round": rnd} for k in outputs}},
        record={"process": {"request_findings": list(requests)}},
        latest_output=lambda nid: outputs.get(nid))


class SchemaCase(unittest.TestCase):
    def test_role_schema_has_optional_out_of_purpose_rows(self):
        """判定役の型に out_of_purpose が在り（古い返答を拒まないので required に入れない）、行は source・where・why_outside"""
        s = accept.role_schema("p2.diagnose")
        self.assertNotIn(outpurpose.FIELD, s["required"])
        row = s["properties"][outpurpose.FIELD]["items"]
        self.assertEqual(sorted(row["required"]), ["source", "where", "why_outside"])
        self.assertFalse(row["additionalProperties"])

    def test_other_nodes_do_not_get_the_field(self):
        self.assertNotIn(outpurpose.FIELD, accept.role_schema("p2.fix_plan")["properties"])

    def test_split_takes_the_field_off(self):
        bare, rows = outpurpose.split({"units": [], outpurpose.FIELD: OOP})
        self.assertEqual(bare, {"units": []})
        self.assertEqual(rows, OOP)
        self.assertEqual(outpurpose.split({"units": []}), ({"units": []}, []))


class MaterialRowsCase(unittest.TestCase):
    def test_rows_are_the_p1_items_and_this_rounds_requests(self):
        """材料の行は P1 の節の出力の where・text を持つ行の全部（入れ子の items も）と、今の周に積まれた依頼の行。P2 の出力は入れない"""
        with tempfile.TemporaryDirectory() as d:
            b = fake_board(d, requests=[{"round": 1, "origin": "人", "findings": [ASKED]},
                                        {"round": 0, "origin": "前", "findings": [{"where": "古い", "text": "前の周"}]}])
            rows = outpurpose.material_rows(b)
        wheres = [r["where"] for r in rows]
        self.assertEqual(sorted(wheres), sorted([CR["where"], DOCKER["where"], HYG["where"], ASKED["where"]]))
        cr = next(r for r in rows if r["where"] == CR["where"])
        self.assertEqual({k: cr[k] for k in CR}, CR)
        self.assertIn("p1.local_review", cr["from"])
        self.assertIn("pr-review-toolkit:code-reviewer", cr["from"])


class ProblemsCase(unittest.TestCase):
    def rows(self):
        with tempfile.TemporaryDirectory() as d:
            return outpurpose.material_rows(fake_board(d))

    def test_rows_matching_material_pass(self):
        self.assertEqual(outpurpose.problems(OOP, self.rows()), [])

    def test_where_is_compared_with_spaces_squeezed(self):
        got = [{**OOP[1], "where": "  docker-entrypoint.sh  (until dagster instance migrate) "}]
        self.assertEqual(outpurpose.problems(got, self.rows()), [])

    def test_where_not_in_material_is_rejected_by_name(self):
        got = outpurpose.problems([{**OOP[0], "where": "app/compute_logs/manager.py"}], self.rows())
        self.assertEqual(len(got), 1)
        self.assertIn("app/compute_logs/manager.py", got[0])
        self.assertIn("材料", got[0])

    def test_short_why_and_missing_source_are_rejected(self):
        got = outpurpose.problems([{**OOP[0], "why_outside": "外"}, {k: v for k, v in OOP[1].items() if k != "source"}],
                                  self.rows())
        self.assertEqual(len(got), 2, got)

    def test_not_a_list_is_rejected(self):
        self.assertTrue(outpurpose.problems("目的の外", self.rows()))


class SameWhereCase(unittest.TestCase):
    """同じ where の材料の行が 2 つ在る時は、text の頭で 1 行に絞らせる（審査の指摘: where だけで当てると、目的の内で直す行
    まで目的の外として運んだ）。where と text が同じ行（同じ所見の写し）は 1 行に数える"""
    TWIN = {"where": CR["where"], "text": "目的の内の別の所見: 世代の順を直す"}

    def rows(self, extra=()):
        outputs = {**OUTPUTS, "p1.hygiene": {"findings": [HYG, *extra]}}
        with tempfile.TemporaryDirectory() as d:
            return outpurpose.material_rows(fake_board(d, outputs=outputs))

    def test_two_rows_on_one_where_need_the_text_head(self):
        got = outpurpose.problems([OOP[0]], self.rows([self.TWIN]))
        self.assertEqual(len(got), 1, got)
        self.assertIn("2 行", got[0])
        self.assertIn("text", got[0])

    def test_text_head_picks_one_row_and_only_that_row_is_carried(self):
        rows = self.rows([self.TWIN])
        pick = [{**OOP[0], "text": CR["text"][:20]}]
        self.assertEqual(outpurpose.problems(pick, rows), [])
        with tempfile.TemporaryDirectory() as d:
            outpurpose.save(d, 1, pick, rows)
            self.assertEqual([i["text"].split("（")[0] for i in outpurpose.next_items(d)], [CR["text"]])

    def test_text_head_matching_nothing_is_rejected(self):
        got = outpurpose.problems([{**OOP[0], "text": "どの行の頭でもない"}], self.rows([self.TWIN]))
        self.assertEqual(len(got), 1, got)

    def test_full_text_picks_the_row_whose_text_is_a_head_of_the_other(self):
        """片方の text がもう片方の頭と同じでも、全文を写せばその行だけに当たる（審査の再現: 短い方を選べなかった）"""
        longer = {"where": CR["where"], "text": CR["text"] + " と、ほかの所見"}
        self.assertEqual(outpurpose.problems([{**OOP[0], "text": CR["text"]}], self.rows([longer])), [])
        self.assertEqual(len(outpurpose.problems([{**OOP[0], "text": CR["text"][:10]}], self.rows([longer]))), 1)

    def test_the_same_row_twice_counts_once(self):
        self.assertEqual(outpurpose.problems([OOP[0]], self.rows([dict(CR)])), [])


class CarryCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        self.b = fake_board(self.dir)

    def test_next_items_carry_every_field_of_the_material_row_marked(self):
        outpurpose.save(self.dir, 1, OOP, outpurpose.material_rows(self.b))
        items = outpurpose.next_items(self.dir)
        self.assertEqual([i["where"] for i in items], [CR["where"], HYG["where"]])
        cr = items[0]
        self.assertEqual({k: cr[k] for k in ("mechanism", "measured", "false_positive_if")},
                         {k: CR[k] for k in ("mechanism", "measured", "false_positive_if")})
        self.assertTrue(cr["text"].startswith(CR["text"]))
        self.assertIn(outpurpose.MARK, cr["text"])
        self.assertIn(OOP[0]["why_outside"], cr["text"])
        self.assertIn(OOP[0]["source"], cr["text"])
        self.assertEqual(items[1]["mechanism"], HYG["mechanism"])
        self.assertNotIn("measured", items[1])   # 材料の行に無い欄は作らない

    def test_next_items_pass_the_request_type(self):
        """運んだ行は下書きの印（draft・source）を外せば依頼の行の型（where・text と任意の mechanism・measured・
        false_positive_if だけ）"""
        outpurpose.save(self.dir, 1, OOP, outpurpose.material_rows(self.b))
        for it in outpurpose.next_items(self.dir):
            bare = {k: v for k, v in it.items() if k not in carry.DRAFT_KEYS}
            self.assertLessEqual(set(bare), {"where", "text", "mechanism", "measured", "false_positive_if"})

    def test_carried_rows_are_drafts_the_request_entry_refuses(self):
        """運んだ行は人が見直すまで次の run の目的にしない: draft: true と出どころ source を持ち、依頼の入口が拒む（答えの下書きと
        同じ扱い）。印を消した行は通る"""
        outpurpose.save(self.dir, 1, OOP, outpurpose.material_rows(self.b))
        items = outpurpose.next_items(self.dir)
        self.assertTrue(all(i.get("draft") is True and i.get("source") for i in items), items)
        self.assertIn(OOP[0]["source"], items[0]["source"])
        with self.assertRaises(ValueError) as cm:
            carry.parts({"findings": items})
        self.assertIn("下書き", str(cm.exception))
        self.assertIn("findings[0]", str(cm.exception))
        bare = [{k: v for k, v in i.items() if k not in carry.DRAFT_KEYS} for i in items]
        self.assertEqual(carry.parts({"findings": bare})["findings"], bare)

    def test_only_the_last_round_is_carried(self):
        """判定は周ごとに目的の外を決め直す: 前の周に目的の外とした所見が後の周に単位になれば運ばない（最後の周の行だけ）"""
        rows = outpurpose.material_rows(self.b)
        outpurpose.save(self.dir, 1, OOP, rows)
        outpurpose.save(self.dir, 2, OOP[1:], rows)
        self.assertEqual([i["where"] for i in outpurpose.next_items(self.dir)], [HYG["where"]])
        self.assertEqual(len(outpurpose.report_lines(self.dir)), 2)
        outpurpose.save(self.dir, 10, [], rows)   # 最後の周は目的の外を名指さなかった（周の順は数で比べる）
        self.assertEqual(outpurpose.next_items(self.dir), [])

    def test_saving_a_round_again_replaces_it(self):
        rows = outpurpose.material_rows(self.b)
        outpurpose.save(self.dir, 1, OOP, rows)
        outpurpose.save(self.dir, 1, OOP[1:], rows)
        self.assertEqual([i["where"] for i in outpurpose.next_items(self.dir)], [HYG["where"]])

    def test_no_file_is_nothing_and_unreadable_file_is_said(self):
        self.assertEqual(outpurpose.next_items(self.dir), [])
        self.assertEqual(outpurpose.report_lines(self.dir), [])
        (self.dir / outpurpose.FILE).write_text("{", encoding="utf-8")
        items = outpurpose.next_items(self.dir)
        self.assertEqual(len(items), 1)
        self.assertIn("読めない", items[0]["text"])

    def test_unreadable_file_is_not_overwritten(self):
        """控えが読めない時は書き直さない（前の周の分を黙って消さない。読めないことは next_items が言う）"""
        (self.dir / outpurpose.FILE).write_text("{", encoding="utf-8")
        outpurpose.save(self.dir, 2, OOP, outpurpose.material_rows(self.b))
        self.assertEqual((self.dir / outpurpose.FILE).read_text(encoding="utf-8"), "{")

    def test_broken_found_rows_are_skipped(self):
        (self.dir / outpurpose.FILE).write_text(json.dumps({"rounds": {"1": [{**OOP[0], "found": [{"text": "where が無い"}, CR]}]}}),
                                                encoding="utf-8")
        self.assertEqual([i["where"] for i in outpurpose.next_items(self.dir)], [CR["where"]])

    def test_carried_mark_is_not_piled_up(self):
        """前の run が運んだ行がまた目的の外になっても、text の尾の印は 1 つ"""
        outpurpose.save(self.dir, 1, OOP[:1], outpurpose.material_rows(self.b))
        once = outpurpose.next_items(self.dir)[0]
        again = {**CR, "text": once["text"]}
        with tempfile.TemporaryDirectory() as d:
            outpurpose.save(d, 1, OOP[:1], [{**again, "from": "依頼"}])
            twice = outpurpose.next_items(d)[0]
        self.assertEqual(twice["text"].count(outpurpose.MARK), 1, twice["text"])

    def test_restore_puts_this_rounds_rows_back_into_the_judgment(self):
        outpurpose.save(self.dir, 1, OOP, outpurpose.material_rows(self.b))
        self.assertEqual(outpurpose.restore({"units": []}, self.dir, 1)[outpurpose.FIELD], OOP)
        self.assertNotIn(outpurpose.FIELD, outpurpose.restore({"units": []}, self.dir, 2))

    def test_report_lines_name_each_row(self):
        outpurpose.save(self.dir, 1, OOP, outpurpose.material_rows(self.b))
        lines = outpurpose.report_lines(self.dir)
        self.assertIn("2 件", lines[0])
        self.assertTrue(any(CR["where"] in x and OOP[0]["source"] in x for x in lines[1:]), lines)


class JudgeTakeCase(unittest.TestCase):
    """blk-judge の受け付け（judgetake.take）が out_of_purpose を外して盤面へ渡し、材料に当たらない行を拒み、通れば控える"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        import judgetake
        self.jt = judgetake

    def take(self, reply, ok=True):
        b = fake_board(self.dir)
        with mock.patch.object(self.jt.entry, "open_board", return_value=b), \
                mock.patch.object(self.jt.entry, "take", return_value={"ok": ok, "reason": "" if ok else "盤面が拒んだ"}) as t:
            got = self.jt.take(self.dir, reply, self.dir)
        return got, t

    def test_good_rows_are_taken_off_and_saved(self):
        got, t = self.take({"units": [], outpurpose.FIELD: OOP})
        self.assertTrue(got["ok"], got)
        self.assertNotIn(outpurpose.FIELD, t.call_args.args[2])
        self.assertEqual([i["where"] for i in outpurpose.next_items(self.dir)], [CR["where"], HYG["where"]])

    def test_row_outside_material_is_rejected_before_the_board(self):
        got, t = self.take({"units": [], outpurpose.FIELD: [{**OOP[0], "where": "どこにも無い"}]})
        self.assertFalse(got["ok"])
        self.assertIn("どこにも無い", got["reason"])
        t.assert_not_called()

    def test_board_reject_saves_nothing(self):
        got, _ = self.take({"units": [], outpurpose.FIELD: OOP}, ok=False)
        self.assertFalse(got["ok"])
        self.assertFalse((self.dir / outpurpose.FILE).exists())

    def test_board_is_opened_allowing_a_halted_board(self):
        """止めた盤面の拒否は entry.take に任せる（目的の外の確かめが先に盤面を開いて別の理由で落ちない）"""
        b = fake_board(self.dir)
        with mock.patch.object(self.jt.entry, "open_board", return_value=b) as ob, \
                mock.patch.object(self.jt.entry, "take", return_value={"ok": True, "reason": ""}):
            self.jt.take(self.dir, {"units": []}, self.dir)
        self.assertTrue(all(c.kwargs.get("allow_halted") is True for c in ob.call_args_list), ob.call_args_list)

    def test_reply_without_the_field_is_taken(self):
        got, _ = self.take({"units": []})
        self.assertTrue(got["ok"], got)
        self.assertEqual(outpurpose.next_items(self.dir), [])


class PromptCase(unittest.TestCase):
    def test_judge_prompt_asks_for_out_of_purpose_rows(self):
        text = (ROOT / "blk-judge" / "commands" / "diagnose.md").read_text(encoding="utf-8")
        self.assertIn("`out_of_purpose`", text)
        self.assertIn("why_outside", text)


if __name__ == "__main__":
    unittest.main()
