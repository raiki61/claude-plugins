"""事前審査の壁打ち（依頼 231）の決まりと往復の控え（core の converge）。偽の盤面（SimpleNamespace に round・dir・work・trace）で
関数を直に呼ぶ（FAST。盤面・git・子のプロセスなし）"""
import json
import pathlib
import sys
import tempfile
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))
import converge  # noqa: E402
from test_plan_gate import internal_subjects  # noqa: E402


def face(key, severity="block", kind="regression", units=("u",)):
    return {"key": key, "kind": kind, "where": f"{key} の場所", "why": f"{key} が穴である理由", "severity": severity,
            "unit_keys": list(units)}


def answer(key, handled="fixed", how="案の項目 1 の手順を直した"):
    return {"key": key, "handled": handled, "how": how}


class BoardCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)
        self.traces = []
        self.b = self.board(1)

    def board(self, rnd):
        def work(name):
            p = self.tmp / f"r{rnd}" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            return p
        return types.SimpleNamespace(round=rnd, dir=self.tmp, work=work,
                                     trace=lambda op, **kw: self.traces.append({"op": op, **kw}))

    def src(self, name, text):
        p = self.tmp / "src" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return str(p)

    def record(self, keys, *, resolved=(), fence=3, files=None, extra=()):
        return converge.record_pass(self.b, {"faces": [face(k) for k in keys] + list(extra)}, resolved=list(resolved),
                                    fence=fence, files=files or {})


class DecideCase(unittest.TestCase):
    def test_no_block_is_clean(self):
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": []}], fence=3), converge.CLEAN)

    def test_new_blocks_only_go_again_before_fence(self):
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": ["b"]}], fence=3), converge.AGAIN)

    def test_block_from_any_earlier_pass_persists(self):
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": ["a", "b"]}], fence=3), converge.PERSISTED)
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": ["b"]}, {"blocks": ["a"]}], fence=3),
                         converge.PERSISTED)   # 消えた穴がまた出た

    def test_fence_with_new_blocks_is_unsettled(self):
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": ["b"]}, {"blocks": ["c"]}], fence=3),
                         converge.UNSETTLED)

    def test_module_has_no_count_constant(self):
        self.assertEqual([n for n, v in vars(converge).items() if type(v) is int], [])

    def test_block_faces_keep_order_and_drop_repeats(self):
        got = converge.block_faces({"faces": [face("a"), face("s", severity="suggest"), face("b"), face("a")]})
        self.assertEqual([f["key"] for f in got], ["a", "b"])


class RecordCase(BoardCase):
    def test_read_without_record_is_first_pass(self):
        fresh = {"round": 1, "passes": [], "outcome": None, "open": {}}
        self.assertEqual(converge.read(self.b), fresh)
        self.assertEqual(converge.pass_no(self.b), 1)
        self.b.work(converge.RECORD).write_text("{壊れた", encoding="utf-8")
        self.assertEqual(converge.read(self.b), fresh)
        self.assertEqual(converge.pass_no(self.b), 1)
        self.b.work(converge.RECORD).write_text(json.dumps({"round": 2, "passes": [{"pass": 1, "blocks": ["a"]}],
                                                            "outcome": "again", "open": {}}), encoding="utf-8")
        self.assertEqual(converge.read(self.b), fresh)
        self.assertEqual(converge.pass_no(self.b), 1)

    def test_record_pass_keeps_every_pass_and_copies_files(self):
        row1 = self.record(["a"], files={"plan.json": self.src("plan.json", "案 1"),
                                         "review.json": self.src("review.json", "審査 1")},
                           extra=[face("s", severity="suggest")])
        self.assertEqual((row1["pass"], row1["blocks"], row1["suggests"], row1["outcome"]), (1, ["a"], ["s"], converge.AGAIN))
        self.assertEqual(row1["faces"], [{"key": "a", "kind": "regression", "where": "a の場所", "why": "a が穴である理由"}])
        self.assertEqual(converge.pass_no(self.b), 2)
        row2 = self.record(["a"], files={"plan.json": self.src("plan.json", "案 2")})
        self.assertEqual((row2["pass"], row2["persists"], row2["outcome"]), (2, ["a"], converge.PERSISTED))
        doc = converge.read(self.b)
        self.assertEqual([p["pass"] for p in doc["passes"]], [1, 2])
        self.assertEqual(doc["outcome"], converge.PERSISTED)
        base = self.b.work(converge.PASS_DIR)
        self.assertEqual((base / "pass-1" / "plan.json").read_text(encoding="utf-8"), "案 1")
        self.assertEqual((base / "pass-1" / "review.json").read_text(encoding="utf-8"), "審査 1")
        self.assertEqual((base / "pass-2" / "plan.json").read_text(encoding="utf-8"), "案 2")
        self.assertEqual(row1["files"]["plan.json"], str(base / "pass-1" / "plan.json"))
        self.assertEqual(doc["passes"][1]["files"], {"plan.json": str(base / "pass-2" / "plan.json")})
        ops = [t for t in self.traces if t["op"] == converge.OP]
        self.assertEqual([(t["round"], t["pass_"], t["outcome"], t["blocks"], t["persists"]) for t in ops],
                         [(1, 1, converge.AGAIN, ["a"], []), (1, 2, converge.PERSISTED, ["a"], ["a"])])
        self.assertEqual(list((self.tmp / "r1").glob("*.tmp")), [])

    def test_record_pass_reads_faces_through_one_guard(self):
        """faces が list でない返答も block と suggest を同じ柵で読む（どちらも空。落ちない）"""
        for bad in (7, "faces", {"key": "a"}, None):
            with self.subTest(bad=bad):
                b = self.board(len(self.traces) + 1)
                row = converge.record_pass(b, {"faces": bad}, resolved=[], fence=3, files={})
                self.assertEqual((row["blocks"], row["suggests"], row["outcome"]), ([], [], converge.CLEAN))

    def test_answers_move_from_open_to_pass(self):
        self.record(["a"])
        converge.note_answers(self.b, [answer("a")])
        self.assertEqual(converge.read(self.b)["open"]["answers"], [answer("a")])
        row = self.record([], resolved=["a"])
        self.assertEqual((row["answers"], row["resolved"], row["outcome"]), ([answer("a")], ["a"], converge.CLEAN))
        self.assertEqual(converge.read(self.b)["open"], {})
        self.assertIsNone(converge.held(self.b))

    def test_stash_rejects_go_to_last_pass(self):
        self.record(["a"])
        converge.stash_rejects(self.b, ["拒否 1"])
        converge.stash_rejects(self.b, ["拒否 2"])
        self.assertEqual(converge.read(self.b)["passes"][-1]["rejects"], ["拒否 1", "拒否 2"])

    def test_unsettled_at_fence(self):
        self.record(["a"])
        self.record(["b"])
        self.assertEqual(self.record(["c"])["outcome"], converge.UNSETTLED)
        self.assertIsNone(converge.held(self.b))


class FieldsCase(BoardCase):
    def test_answer_gaps_need_one_answer_per_block(self):
        self.record(["a", "b", "c", "d"])
        self.assertEqual(converge.answer_gaps(self.b, [answer(k) for k in "abcd"]), [])
        self.assertEqual(converge.answer_gaps(self.b, [answer("a", handled="disputed", how="前提が違うので直さない")] +
                                              [answer(k) for k in "bcd"]), [])
        gaps = converge.answer_gaps(self.b, [answer("b", handled="ignored"), answer("c", how="直した"),
                                             answer("d"), answer("d"), answer("z")])
        self.assertEqual(len(gaps), 5, gaps)
        self.assertIn("block の key a への答えが無い", gaps)
        self.assertIn("z は前の往復の block に無い", gaps)
        self.assertTrue(any("b" in g and "handled" in g for g in gaps), gaps)
        self.assertTrue(any("c" in g and "how" in g for g in gaps), gaps)
        self.assertTrue(any("d" in g and "2 行" in g for g in gaps), gaps)

    def test_resolved_gaps_need_every_previous_block_accounted(self):
        self.assertEqual(converge.resolved_gaps(self.b, [face("a")], ["x"]), [])   # 1 往復目
        self.record(["a"])
        self.record(["b"])
        self.assertEqual(converge.resolved_gaps(self.b, [face("b"), face("c")], ["a"]), [])
        gaps = converge.resolved_gaps(self.b, [face("b"), face("c")], ["b", "x"])
        self.assertIn("前の block a を resolved に入れるか、同じ key で faces に挙げ直せ", gaps)
        self.assertTrue(any("b" in g and "両方" in g for g in gaps), gaps)
        self.assertTrue(any("x" in g and "前の往復の block に無い" in g for g in gaps), gaps)
        self.assertEqual(len(gaps), 3, gaps)

    def test_with_fields_and_split_round_trip(self):
        base = {"type": "object", "properties": {"plan": {"type": "array"}}, "required": ["plan"]}
        revise = converge.with_fields("plan-revise", base)
        self.assertEqual(base, {"type": "object", "properties": {"plan": {"type": "array"}}, "required": ["plan"]})
        self.assertIn(converge.ANSWERS, revise["required"])
        row = revise["properties"][converge.ANSWERS]["items"]
        self.assertEqual(row["required"], ["key", "handled", "how"])
        self.assertFalse(row["additionalProperties"])
        self.assertEqual(row["properties"]["handled"]["enum"], list(converge.HANDLED))
        self.assertEqual((row["properties"]["key"]["minLength"], row["properties"]["how"]["minLength"]), (8, 10))
        review = converge.with_fields("plan-review", base)
        self.assertIn(converge.RESOLVED, review["properties"])
        self.assertNotIn(converge.RESOLVED, review["required"])
        self.assertEqual(converge.with_fields("fix", base), base)
        reply = {"plan": [1], converge.ANSWERS: [answer("a")]}
        self.assertEqual(converge.split("plan-revise", reply), ({"plan": [1]}, [answer("a")]))
        self.assertEqual(reply[converge.ANSWERS], [answer("a")])   # 元は変えない
        self.assertEqual(converge.split("plan-review", {"faces": [], converge.RESOLVED: ["a"]}), ({"faces": []}, ["a"]))
        self.assertEqual(converge.split("plan-review", {"faces": []}), ({"faces": []}, []))
        self.assertEqual(converge.split("fix", {"x": 1}), ({"x": 1}, []))


class TextCase(BoardCase):
    def test_stuck_reason_names_keys_and_record(self):
        self.assertEqual(converge.stuck_reason(self.b), "")
        self.record(["key-alpha"])
        self.assertEqual(converge.stuck_reason(self.b), "")
        self.record(["key-alpha", "key-beta"])
        why = converge.stuck_reason(self.b)
        self.assertEqual(why, converge.PERSISTED_WHY.format(keys="key-alpha", n=2,
                                                             path=self.b.work(converge.PASS_DIR)))
        self.record([], resolved=["key-alpha", "key-beta"])
        self.assertEqual(converge.stuck_reason(self.b), "")

    def test_stuck_reason_unsettled(self):
        for k in ("key-a1", "key-b1", "key-c1"):
            self.record([k])
        self.assertEqual(converge.stuck_reason(self.b),
                         converge.UNSETTLED_WHY.format(keys="key-c1", n=3, path=self.b.work(converge.PASS_DIR)))

    def test_lines_summarize_passes(self):
        self.assertEqual(converge.lines(self.b), [])
        self.record(["key-alpha"])
        converge.note_answers(self.b, [answer("key-alpha")])
        self.record(["key-alpha"])
        got = converge.lines(self.b)
        path = self.b.work(converge.PASS_DIR)
        self.assertEqual(got[0], converge.LINE_HEAD.format(n=2, word="同じ block が続いた", outcome="persisted",
                                                           persists="key-alpha", path=path))
        self.assertEqual(got[1:], [
            converge.LINE_PASS.format(k=1, keys="key-alpha", f=0, d=0, resolved="無い", down="無い"),
            converge.LINE_PASS.format(k=2, keys="key-alpha", f=1, d=0, resolved="無い", down="無い")])

    def test_lines_name_blocks_downgraded_to_suggest(self):
        """前の往復の block を審査が suggest に下げた key は、その往復の行に出る（block から消えたのが resolved でなく格下げだと
        報告で分かる。Task 1 の持ち越し m2）。前の往復で block でなかった suggest は出さない"""
        self.record(["key-alpha"])
        converge.note_answers(self.b, [answer("key-alpha")])
        self.record([], extra=[face("key-alpha", severity="suggest"), face("key-gamma", severity="suggest")])
        got = converge.lines(self.b)
        self.assertEqual(got[2], converge.LINE_PASS.format(k=2, keys="無い", f=1, d=0, resolved="無い", down="key-alpha"))
        self.assertIn("key-alpha", got[2])
        self.assertNotIn("key-gamma", got[2])

    def test_texts_keep_record_names_in_parens(self):
        self.record(["key-alpha"])
        converge.note_answers(self.b, [answer("key-alpha", handled="disputed", how="前提が違うので直さない")])
        self.record(["key-alpha"])
        texts = [converge.stuck_reason(self.b), *converge.lines(self.b)]
        self.assertEqual(internal_subjects("\n".join(texts)), [])

    def test_review_section_empty_on_first_pass(self):
        self.assertEqual(converge.review_section(self.b), "")
        self.record(["key-alpha"])
        converge.note_answers(self.b, [answer("key-alpha")])
        sec = converge.review_section(self.b)
        self.assertTrue(sec.startswith(converge.REREVIEW_ASK), sec)
        self.assertIn("key-alpha", sec)
        self.assertIn("案の項目 1 の手順を直した", sec)

    def test_revise_section_lists_held_blocks(self):
        self.assertEqual(converge.revise_section(self.b), "")
        self.record(["key-alpha"], extra=[face("key-sugg", severity="suggest")])
        sec = converge.revise_section(self.b)
        self.assertTrue(sec.startswith(converge.REVISE_ASK), sec)
        for part in ("key-alpha", "regression", "key-alpha の場所", "key-alpha が穴である理由", "key-sugg"):
            self.assertIn(part, sec)


def row(*units, approach="案の手順"):
    return {"unit_keys": list(units), "approach": approach}


class ItemsCase(BoardCase):
    """項目ごとの壁打ち（線の木の段 1。設計 docs/plans/2026-10-06-tree-line.md の 2.3 の 5）: block の無い項目は閉じて次の往復で
    審査も直しもしない・同じ block が続いた項目は保留にしてほかの項目は柵まで進める・相乗りの block は名指した項目だけを開き直す"""
    def setUp(self):
        super().setUp()
        converge.note_plan(self.b, [row("u1"), row("u2")])

    def review(self, faces, *, resolved=(), synergy=()):
        return converge.record_pass(self.b, {"faces": faces}, resolved=list(resolved), fence=3, files={}, synergy=list(synergy))

    def states(self, got):
        return [it["state"] for it in got["items"]]

    def test_clean_item_closes_and_blocked_item_goes_again(self):
        got = self.review([face("key-a1", units=["u1"])])
        self.assertEqual(self.states(got), [converge.OPEN, converge.CLOSED])
        self.assertEqual(got["items"][0]["blocks"], ["key-a1"])
        self.assertEqual(got["outcome"], converge.AGAIN)
        self.assertEqual(converge.open_items(self.b), [1])

    def test_closed_item_stays_closed_and_all_closed_is_clean(self):
        self.review([face("key-a1", units=["u1"])])
        got = self.review([], resolved=["key-a1"])
        self.assertEqual(self.states(got), [converge.CLOSED, converge.CLOSED])
        self.assertEqual(got["outcome"], converge.CLEAN)

    def test_persisted_item_is_held_and_others_go_on(self):
        self.review([face("key-a1", units=["u1"]), face("key-b1", units=["u2"])])
        got = self.review([face("key-a1", units=["u1"]), face("key-b2", units=["u2"])])
        self.assertEqual(self.states(got), [converge.HELD, converge.OPEN])
        self.assertEqual(got["outcome"], converge.AGAIN, "保留の項目のほかに開いた項目が在れば柵まで進む")
        self.assertEqual(converge.open_items(self.b), [2])
        got = self.review([], resolved=["key-b2"])
        self.assertEqual(self.states(got), [converge.HELD, converge.CLOSED])
        self.assertEqual(got["outcome"], converge.PERSISTED)

    def test_fence_with_held_item_is_persisted_and_without_is_unsettled(self):
        self.review([face("key-a1", units=["u1"]), face("key-b1", units=["u2"])])
        self.review([face("key-a1", units=["u1"]), face("key-b2", units=["u2"])])
        self.assertEqual(self.review([face("key-b3", units=["u2"])])["outcome"], converge.PERSISTED)
        b = self.board(2)
        converge.note_plan(b, [row("u1"), row("u2")])
        for k in ("key-c1", "key-c2", "key-c3"):
            got = converge.record_pass(b, {"faces": [face(k, units=["u1"])]}, resolved=[], fence=3, files={})
        self.assertEqual(got["outcome"], converge.UNSETTLED)

    def test_synergy_block_reopens_named_closed_item(self):
        self.review([face("key-a1", units=["u1"])])
        got = self.review([face("key-s1", units=["u2"])], resolved=["key-a1"], synergy=["key-s1"])
        self.assertEqual(self.states(got), [converge.CLOSED, converge.OPEN])
        self.assertTrue(got["items"][1]["reopened"])
        self.assertEqual(got["synergy"], ["key-s1"])
        self.assertEqual(got["outcome"], converge.AGAIN)

    def test_face_naming_no_item_counts_for_every_reviewed_item(self):
        got = self.review([face("key-x1", units=["somewhere"])])
        self.assertEqual(self.states(got), [converge.OPEN, converge.OPEN])

    def test_closed_item_changed_or_dropped_is_named(self):
        self.review([face("key-a1", units=["u1"])])
        whole, rejects, dropped = self.splice([row("u1", approach="直した")])
        self.assertEqual((rejects, dropped), ([], []), "閉じた項目の行が無い返答は拒まない（機械が差し込む）")
        self.assertEqual(whole, [row("u1", approach="直した"), row("u2")])
        _, rejects, dropped = self.splice([row("u1"), row("u2", approach="変えた")])
        self.assertEqual(len(rejects), 1, rejects)
        self.assertIn("閉じた項目 2 を変えた", rejects[0])
        self.assertEqual(dropped, [])
        _, rejects, _ = self.splice([row("u1", "u2")])
        self.assertEqual(len(rejects), 1, rejects)
        self.assertIn("閉じた項目 2 の単位を別の行に入れた", rejects[0])

    def splice(self, rows):
        self.assertTrue(hasattr(converge, "splice"), "converge.splice が無い")
        return converge.splice(self.b, rows)

    def hold_second(self):
        """項目 2（u2）が保留・項目 1（u1）が開いた往復の後の控え"""
        self.review([face("key-a1", units=["u1"]), face("key-b1", units=["u2"])])
        got = self.review([face("key-a2", units=["u1"]), face("key-b1", units=["u2"])])
        self.assertEqual(self.states(got), [converge.OPEN, converge.HELD])

    def test_splice_fills_closed_rows_byte_equal(self):
        self.review([face("key-a1", units=["u1"])])
        whole, rejects, dropped = self.splice([row("u1", approach="直した")])
        self.assertEqual((rejects, dropped), ([], []))
        self.assertEqual(whole, [row("u1", approach="直した"), row("u2")])
        kept = converge.read(self.b)["passes"][-1]["items"][1]["hash"]
        self.assertEqual(converge.item_hash(whole[1]), kept)

    def test_splice_keeps_unmatched_reply_rows(self):
        self.review([face("key-a1", units=["u1"])])
        whole, rejects, dropped = self.splice([row("u1", "u3", approach="組み替えた"), row("u9", approach="新しい項目")])
        self.assertEqual(rejects, [])
        self.assertEqual(dropped, [])
        self.assertEqual(whole, [row("u2"), row("u1", "u3", approach="組み替えた"), row("u9", approach="新しい項目")])

    def test_splice_refuses_missing_open_item(self):
        self.review([face("key-a1", units=["u1"])])
        whole, rejects, _ = self.splice([])
        self.assertEqual(len(rejects), 1, rejects)
        self.assertIn("開いた項目 1 の行が無い", rejects[0])
        self.assertEqual(whole, [row("u2")])

    def test_splice_takes_changed_held_row(self):
        self.hold_second()
        whole, rejects, _ = self.splice([row("u1", approach="直した"), row("u2", approach="保留を変えた")])
        self.assertEqual(rejects, [])
        self.assertEqual(whole, [row("u1", approach="直した"), row("u2", approach="保留を変えた")])
        whole, rejects, _ = self.splice([row("u1", approach="直した")])
        self.assertEqual(rejects, [])
        self.assertEqual(whole, [row("u1", approach="直した"), row("u2")])

    def test_splice_lets_held_units_regroup(self):
        self.hold_second()
        whole, rejects, _ = self.splice([row("u1", "u2", approach="まとめた")])
        self.assertEqual(rejects, [])
        self.assertEqual([k for r in whole for k in r["unit_keys"]], ["u1", "u2"])

    def test_answers_and_resolved_only_for_reviewed_items(self):
        self.review([face("key-a1", units=["u1"]), face("key-b1", units=["u2"])])
        self.review([face("key-a1", units=["u1"]), face("key-b2", units=["u2"])])   # 項目 1 は保留
        self.assertEqual(converge.answer_gaps(self.b, [answer("key-b2")]), [])
        self.assertEqual(converge.resolved_gaps(self.b, [], ["key-b1", "key-b2"]), [])
        self.assertIn("前の block key-b2 を resolved に入れるか、同じ key で faces に挙げ直せ",
                      converge.resolved_gaps(self.b, [], ["key-b1"]))

    def test_texts_name_closed_and_held_items(self):
        self.review([face("key-a1", units=["u1"]), face("key-b1", units=["u2"])])
        self.review([face("key-a1", units=["u1"]), face("key-b2", units=["u2"])])
        self.review([], resolved=["key-b2"])
        why = converge.stuck_reason(self.b)
        self.assertIn("項目 1", why)
        self.assertIn("key-a1", why)
        self.assertIn("項目 2", why)
        self.assertTrue(any("保留" in line for line in converge.lines(self.b)), converge.lines(self.b))
        self.assertEqual(internal_subjects("\n".join([why, *converge.lines(self.b)])), [])

    def test_revise_section_names_closed_items(self):
        self.review([face("key-a1", units=["u1"])])
        sec = converge.revise_section(self.b)
        self.assertIn(converge.CLOSED_ASK, sec)
        self.assertIn("項目 2（u2）", sec)

    def test_revise_section_shows_only_open_item_blocks_and_closed_items(self):
        self.review([face("key-a1", units=["u1"]), face("key-b1", units=["u2"])])
        self.review([face("key-a1", units=["u1"]), face("key-b2", units=["u2"])])
        sec = converge.revise_section(self.b)
        self.assertIn("key-b2", sec)
        self.assertNotIn("### key-a1", sec)

    def test_revise_section_asks_open_items_only(self):
        converge.note_plan(self.b, [row("u1"), row("u2"), row("u3")])
        self.review([face("key-a1", units=["u1"]), face("key-b1", units=["u2"])])
        self.review([face("key-a1", units=["u1"]), face("key-b2", units=["u2"])])
        sec = converge.revise_section(self.b)
        self.assertIn(converge.REVISE_ASK, sec)
        self.assertIn("開いた項目の行", converge.REVISE_ASK)
        self.assertNotIn("丸ごと", converge.REVISE_ASK)
        self.assertIn("閉じた項目は書くな", converge.REVISE_ASK)
        self.assertIn("書くな", converge.CLOSED_ASK)
        self.assertNotIn("一字も変えずに入れよ", converge.CLOSED_ASK)
        self.assertIn("書かなければ機械が差し込む", converge.HELD_NOTE)
        self.assertIn("項目 3（u3）", sec)
        self.assertIn("項目 1（u1）", sec)


if __name__ == "__main__":
    unittest.main()
