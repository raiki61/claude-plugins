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

    def record(self, keys, *, resolved=(), files=None, extra=(), **kw):
        return converge.record_pass(self.b, {"faces": [face(k) for k in keys] + list(extra)}, resolved=list(resolved),
                                    files=files or {}, **kw)


class DecideCase(unittest.TestCase):
    def test_no_block_is_clean(self):
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": []}]), converge.CLEAN)

    def test_new_blocks_stop_before_fence_when_not_fewer(self):
        """新しい key だけの往復でも、開いた block の数が前より減らなければ止まる（減れば続く）"""
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": ["b"]}]), converge.UNSETTLED)
        self.assertEqual(converge.decide([{"blocks": ["a", "b"]}, {"blocks": ["c"]}]), converge.AGAIN)

    def test_open_blocks_not_fewer_than_last_pass_is_unsettled(self):
        self.assertEqual(converge.decide([{"blocks": ["a", "b"]}, {"blocks": ["c", "d"]}]), converge.UNSETTLED)
        self.assertEqual(converge.decide([{"blocks": ["a", "b"]}, {"blocks": ["c", "d", "e"]}]), converge.UNSETTLED)
        self.assertEqual(converge.decide([{"blocks": ["a", "b", "c"]}, {"blocks": ["d"]}]), converge.AGAIN)
        # 同じ key が戻る往復は、数の比べより先に PERSISTED
        self.assertEqual(converge.decide([{"blocks": ["a", "b"]}, {"blocks": ["a", "c"]}]), converge.PERSISTED)

    def test_block_from_any_earlier_pass_persists(self):
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": ["a", "b"]}]), converge.PERSISTED)
        self.assertEqual(converge.decide([{"blocks": ["a"]}, {"blocks": ["b"]}, {"blocks": ["a"]}]),
                         converge.PERSISTED)   # 消えた穴がまた出た

    def test_fence_with_new_blocks_is_unsettled(self):
        """開いた数が 3 → 2 → 1 と減り続ける列は、往復の数に依らず続く（AGAIN）"""
        passes = [{"blocks": ["a", "b", "c"]}, {"blocks": ["d", "e"]}, {"blocks": ["f"]}]
        self.assertEqual(converge.decide(passes), converge.AGAIN)
        self.assertEqual(converge.decide(passes[:2]), converge.AGAIN)

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
                row = converge.record_pass(b, {"faces": bad}, resolved=[], files={})
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

    def test_decreasing_open_blocks_go_on_past_three_passes(self):
        """開いた block の数が減り続ける限り、往復の数では止めない（3 往復目も 5 往復目も AGAIN。直しの役に返す行は最後の往復）"""
        for k, keys in enumerate((["a1", "a2", "a3", "a4", "a5"], ["b1", "b2", "b3", "b4"], ["c1", "c2", "c3"], ["d1", "d2"], ["e1"]), 1):
            with self.subTest(pass_=k):
                self.assertEqual(self.record(keys)["outcome"], converge.AGAIN)
                self.assertEqual(converge.held(self.b)["pass"], k)

    def test_unsettled_at_fence(self):
        """開いた数が減り続ける 3 往復目は、輪の上限の周（at_cap）として記録した時だけ止まる（UNSETTLED・capped。held が None）"""
        self.record(["a", "b", "c"])
        self.record(["d", "e"])
        row = self.record(["f"], at_cap=True)
        self.assertEqual((row["outcome"], row["capped"]), (converge.UNSETTLED, True))
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

    def test_review_fields_take_origins(self):
        """事前審査の型は任意の欄 origins（ORIGIN_SCHEMA）を持ち、必須に入れない。tree_split と drop_fields が返答から外す"""
        base = {"type": "object", "properties": {"faces": {"type": "array"}}, "required": ["faces"]}
        review = converge.with_fields("plan-review", base)
        self.assertEqual(review["properties"][converge.ORIGINS], converge.ORIGIN_SCHEMA)
        self.assertNotIn(converge.ORIGINS, review["required"])
        said = [{"key": "key-b1", "origin": "rephrased", "of": "key-a1"}]
        reply = {"faces": [], converge.ORIGINS: said}
        bare, got = converge.tree_split(reply)
        self.assertEqual((bare, got[converge.ORIGINS]), ({"faces": []}, said))
        self.assertEqual(converge.tree_split({"faces": []})[1][converge.ORIGINS], None)
        self.assertEqual(converge.drop_fields(reply), {"faces": []})
        self.assertEqual(reply, {"faces": [], converge.ORIGINS: said})   # 元は変えない
        self.record(["key-alpha"])   # 2 往復目からの審査の共有の節は出自の頼みを貼らない（頼みは書き手の居る層が貼る）
        sec = converge.review_section(self.b)
        self.assertNotIn(converge.ORIGIN_ASK, sec)
        self.assertTrue(sec.startswith(converge.REREVIEW_ASK), sec)

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
        for k in ("key-a1", "key-b1"):
            self.record([k])
        why = converge.stuck_reason(self.b)
        self.assertTrue(why.startswith(converge.UNSETTLED_WHY.format(keys="key-b1", n=2, path=self.b.work(converge.PASS_DIR))), why)
        self.assertIn("1 往復目 1 → 2 往復目 1", why)

    def test_stuck_reason_names_open_counts_per_pass(self):
        self.record(["key-a1", "key-a2"])
        self.record(["key-b1", "key-b2"])
        self.assertIn("開いた block の数: 1 往復目 2 → 2 往復目 2（前の往復より減らなかった）", converge.stuck_reason(self.b))
        # 減り続けて輪の上限の周で止めた時は、減らなかった時の数の句を付けず、上限に届いた句を付ける
        b = self.board(2)
        for keys, cap in ((["key-a1", "key-a2", "key-a3"], False), (["key-b1", "key-b2"], False), (["key-c1"], True)):
            converge.record_pass(b, {"faces": [face(k) for k in keys]}, resolved=[], files={}, at_cap=cap)
        why = converge.stuck_reason(b)
        self.assertTrue(why.startswith(converge.UNSETTLED_WHY.split("（往復ごとに")[0].format(n=3)), why)
        self.assertIn(converge.CAP_WHY.format(n=3, counts="1 往復目 3 → 2 往復目 2 → 3 往復目 1"), why)
        self.assertNotIn("開いた block の数", why)

    def test_capped_pass_stops_with_cap_reason(self):
        """輪の上限の周（at_cap）に着いて、まだ AGAIN だった往復は UNSETTLED で止まり、行に capped が立つ。関所の理由は上限に届いた
        事実と往復ごとの数だけを言い（減らなかったとも異常とも言わない）、頭の行の結末の名札も減らないと言わない。CLEAN と
        PERSISTED の往復は at_cap でもそのまま"""
        self.record(["key-a1", "key-a2"])
        row = self.record(["key-b1"], at_cap=True)
        self.assertEqual((row["outcome"], row["capped"]), (converge.UNSETTLED, True))
        self.assertIsNone(converge.held(self.b))
        why = converge.stuck_reason(self.b)
        self.assertTrue(why.startswith(converge.UNSETTLED_WHY.split("（往復ごとに")[0].format(n=2)), why)
        self.assertIn(converge.CAP_WHY.format(n=2, counts="1 往復目 2 → 2 往復目 1"), why)
        self.assertNotIn("前の往復より減らなかった", why)
        self.assertNotIn("異常", why)
        head = converge.lines(self.b)[0]
        self.assertNotIn("減らない", head)
        self.assertIn("（記録の名 unsettled）", head)
        b = self.board(2)
        converge.record_pass(b, {"faces": [face("key-a1")]}, resolved=[], files={})
        row = converge.record_pass(b, {"faces": []}, resolved=["key-a1"], files={}, at_cap=True)
        self.assertEqual(row["outcome"], converge.CLEAN)
        self.assertNotIn("capped", row)
        b = self.board(3)
        converge.record_pass(b, {"faces": [face("key-a1")]}, resolved=[], files={})
        row = converge.record_pass(b, {"faces": [face("key-a1"), face("key-b1")]}, resolved=[], files={}, at_cap=True)
        self.assertEqual(row["outcome"], converge.PERSISTED)
        self.assertNotIn("capped", row)
        self.assertNotIn(converge.CAP_WHY.split("（")[0].format(n=2), converge.stuck_reason(b))

    def test_lines_summarize_passes(self):
        self.assertEqual(converge.lines(self.b), [])
        self.record(["key-alpha"])
        converge.note_answers(self.b, [answer("key-alpha")])
        self.record(["key-alpha"])
        got = converge.lines(self.b)
        path = self.b.work(converge.PASS_DIR)
        share = converge.LINE_SHARE.format(first=1, missed=0, introduced=0, rephrased=0, unsplit=0, share="1/1", total="1/1")
        self.assertEqual(got[0], converge.LINE_HEAD.format(n=2, word="同じ block が続いた", outcome="persisted",
                                                           persists="key-alpha", share=share, path=path))
        self.assertEqual(got[1:], [
            converge.LINE_PASS.format(k=1, keys="key-alpha", f=0, d=0, resolved="無い", down="無い"),
            converge.LINE_PASS.format(k=2, keys="key-alpha", f=1, d=0, resolved="無い", down="無い")])

    def test_lines_head_names_first_pass_share(self):
        """1 回目の block と後の回の見落としから、1 回目に出た割合を頭の行に出す。割合は閉じた項目の取りこぼしを数えない上限と書く。
        見落としの申告は項目の控えの事実（行の変わらない項目の block）で照らして採る"""
        converge.note_plan(self.b, [row("u1")])
        self.record(["key-a1", "key-a2"])
        converge.record_pass(self.b, {"faces": [face("key-b1")]}, resolved=["key-a1", "key-a2"], files={},
                             origins=[{"key": "key-b1", "origin": converge.ORIGIN_MISSED}])
        head = converge.lines(self.b)[0]
        for part in ("1 回目の block 2 件", "見落とし 1", "1 回目に出た割合は 2/3", "閉じた項目の取りこぼしは数えない上限"):
            self.assertIn(part, head)

    def test_lines_head_without_blocks_says_none(self):
        converge.record_pass(self.b, {"faces": []}, resolved=[], files={})
        head = converge.lines(self.b)[0]
        self.assertIn(converge.LINE_NO_BLOCK, head)
        self.assertNotIn("0/0", head)
        self.assertNotIn("1 回目の block", head)

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
    審査も直しもしない・同じ block が続いた項目は保留にしてほかの項目は開いた数が減る間進める・相乗りの block は名指した項目だけを開き直す"""
    def setUp(self):
        super().setUp()
        converge.note_plan(self.b, [row("u1"), row("u2")])

    def review(self, faces, *, resolved=(), synergy=()):
        return converge.record_pass(self.b, {"faces": faces}, resolved=list(resolved), files={}, synergy=list(synergy))

    def second_pass(self, rnd, faces, *, origins=(), resolved=("key-a1",), plan=None):
        """項目 1 に block を出した 1 往復目の後、案を plan に置き直して（None なら据え置き）2 往復目を記録する（盤面, 2 往復目の行）"""
        b = self.board(rnd)
        converge.note_plan(b, [row("u1"), row("u2")])
        converge.record_pass(b, {"faces": [face("key-a1", units=["u1"])]}, resolved=[], files={})
        if plan is not None:
            converge.note_plan(b, plan)
        got = converge.record_pass(b, {"faces": faces}, resolved=list(resolved), files={}, origins=list(origins))
        return b, got

    def test_new_block_on_unchanged_item_defaults_missed(self):
        """どの項目の行も変わっていない 2 往復目の新しい block は、出自を渡さなくても、introduced を渡しても missed（渡した物は
        採らずに origins_claimed に残る）"""
        claim = {"key": "key-b1", "origin": converge.ORIGIN_INTRODUCED}
        _, got = self.second_pass(2, [face("key-b1", units=["u2"])])
        self.assertEqual((got["origins"], got["origins_claimed"]), ({"key-b1": converge.ORIGIN_MISSED}, []))
        self.assertEqual({w: self.traces[-1][w] for w in converge.ORIGIN_WORDS},
                         {"missed": 1, "introduced": 0, "rephrased": 0, "unsplit": 0})   # trace の行に出自ごとの数が載る
        _, got = self.second_pass(3, [face("key-b1", units=["u2"])], origins=[claim])
        self.assertEqual((got["origins"], got["origins_claimed"]), ({"key-b1": converge.ORIGIN_MISSED}, [claim]))

    def test_new_block_on_changed_item_takes_given_origin(self):
        """行の変わった項目の新しい block は渡した語を採り、渡さない key は unsplit。行の変わっていない項目 1 への introduced も、
        項目 2 が変わったので採る"""
        origins = [{"key": "key-b1", "origin": converge.ORIGIN_INTRODUCED}, {"key": "key-c1", "origin": converge.ORIGIN_INTRODUCED}]
        b, got = self.second_pass(2, [face("key-b1", units=["u2"]), face("key-b2", units=["u2"]), face("key-c1", units=["u1"])],
                                  origins=origins, plan=[row("u1"), row("u2", approach="直した")])
        self.assertEqual(got["origins"], {"key-b1": converge.ORIGIN_INTRODUCED, "key-b2": converge.ORIGIN_UNSPLIT,
                                          "key-c1": converge.ORIGIN_INTRODUCED})
        self.assertEqual(got["origins_claimed"], [])
        self.assertIn(converge.LINE_SHARE.format(first=1, missed=0, introduced=2, rephrased=0, unsplit=1, share="1/2", total="1/4"),
                      converge.lines(b)[0])

    def test_rephrased_block_is_not_counted_new(self):
        """前の block の言い換え（of が前の往復の block で、今の往復の resolved に在る）は rephrased で残り、頭の行は言い換え 1 件と出す"""
        claim = {"key": "key-a2", "origin": converge.ORIGIN_REPHRASED, "of": "key-a1"}
        b, got = self.second_pass(2, [face("key-a2", units=["u1"])], origins=[claim])
        self.assertEqual((got["origins"], got["origins_claimed"]), ({"key-a2": converge.ORIGIN_REPHRASED}, []))
        self.assertIn(converge.LINE_SHARE.format(first=1, missed=0, introduced=0, rephrased=1, unsplit=0, share="1/1", total="1/1"),
                      converge.lines(b)[0])

    def test_rephrased_without_resolved_prior_key_falls_back(self):
        """of が前の往復に無い key・今の往復の resolved に無い key の rephrased は採らず、既定（行が変わっていなければ missed）に
        落ちて、申告は origins_claimed に残る"""
        for rnd, of, resolved in ((2, "key-zzz", ("key-a1",)), (3, "key-a1", ()), (4, "key-zzz", ("key-zzz",))):
            claim = {"key": "key-a2", "origin": converge.ORIGIN_REPHRASED, "of": of}
            with self.subTest(of=of, resolved=resolved):
                _, got = self.second_pass(rnd, [face("key-a2", units=["u1"])], origins=[claim], resolved=resolved)
                self.assertEqual((got["origins"], got["origins_claimed"]), ({"key-a2": converge.ORIGIN_MISSED}, [claim]))
        b = self.board(5)   # 項目の控えの無い往復は、申告が無ければ分けられない
        converge.record_pass(b, {"faces": [face("key-a1")]}, resolved=[], files={})
        got = converge.record_pass(b, {"faces": [face("key-b1")]}, resolved=["key-a1"], files={})
        self.assertEqual(got["origins"], {"key-b1": converge.ORIGIN_UNSPLIT})

    def test_block_on_new_item_defaults_introduced(self):
        """単位の組を組み直した新しい id の項目だけに当たる新しい block は、出自を渡さなくても introduced"""
        _, got = self.second_pass(2, [face("key-n1", units=["u3"])], plan=[row("u1"), row("u3")])
        self.assertEqual(got["origins"], {"key-n1": converge.ORIGIN_INTRODUCED})

    def test_missed_claim_on_changed_item_falls_back(self):
        """1 回目に渡した出自の申告は新しい block が無いので採られない（origins は {}）。2 回目、行の変わった項目 2 に当たる新しい
        block への missed の申告は項目の事実と合わないので採らず、既定（unsplit）に落ちて、申告は origins_claimed に残る"""
        first = {"key": "key-a1", "origin": converge.ORIGIN_MISSED}
        got = converge.record_pass(self.b, {"faces": [face("key-a1", units=["u1"])]}, resolved=[], files={}, origins=[first])
        self.assertEqual((got["origins"], got["origins_claimed"]), ({}, [first]))
        converge.note_plan(self.b, [row("u1"), row("u2", approach="直した")])
        claim = {"key": "key-b1", "origin": converge.ORIGIN_MISSED}
        got = converge.record_pass(self.b, {"faces": [face("key-b1", units=["u2"])]}, resolved=["key-a1"], files={},
                                   origins=[claim])
        self.assertEqual((got["origins"], got["origins_claimed"]), ({"key-b1": converge.ORIGIN_UNSPLIT}, [claim]))

    def test_rephrased_claim_without_unit_overlap_falls_back(self):
        """of が前の往復の block で今の往復の resolved に在っても、of の face の単位（u1）と今の block の単位（u2）が重ならない
        言い換えの申告は採らない。既定（行の変わっていない項目なので missed）に落ちて、申告は origins_claimed に残る。重なれば採る"""
        claim = {"key": "key-a2", "origin": converge.ORIGIN_REPHRASED, "of": "key-a1"}
        _, got = self.second_pass(2, [face("key-a2", units=["u2"])], origins=[claim])
        self.assertEqual((got["origins"], got["origins_claimed"]), ({"key-a2": converge.ORIGIN_MISSED}, [claim]))
        _, got = self.second_pass(3, [face("key-a2", units=["u1", "u2"])], origins=[claim])
        self.assertEqual((got["origins"], got["origins_claimed"]), ({"key-a2": converge.ORIGIN_REPHRASED}, []))

    def test_conflicting_claims_for_one_key_fall_back(self):
        """同じ key に introduced と missed の 2 件の申告が在れば、どちらも採らない。既定（行の変わった項目なので unsplit）に落ち、
        2 件とも origins_claimed に残る"""
        claims = [{"key": "key-b1", "origin": converge.ORIGIN_INTRODUCED}, {"key": "key-b1", "origin": converge.ORIGIN_MISSED}]
        _, got = self.second_pass(2, [face("key-b1", units=["u2"])], origins=claims, plan=[row("u1"), row("u2", approach="直した")])
        self.assertEqual((got["origins"], got["origins_claimed"]), ({"key-b1": converge.ORIGIN_UNSPLIT}, claims))

    def test_block_on_new_and_old_items_rejects_missed_claim(self):
        """新しい id の項目（u3）と、行の変わっていない既存の項目（u1）の両方に当たる新しい block は、申告が無くても unsplit で、
        missed と申告しても採らずに unsplit に落ちる（introduced でも missed でもない）"""
        faces = [face("key-b1", units=["u1", "u3"])]
        _, got = self.second_pass(2, faces, plan=[row("u1"), row("u3")])
        self.assertEqual((got["origins"], got["origins_claimed"]), ({"key-b1": converge.ORIGIN_UNSPLIT}, []))
        claim = {"key": "key-b1", "origin": converge.ORIGIN_MISSED}
        _, got = self.second_pass(3, faces, origins=[claim], plan=[row("u1"), row("u3")])
        self.assertEqual((got["origins"], got["origins_claimed"]), ({"key-b1": converge.ORIGIN_UNSPLIT}, [claim]))

    def test_claims_without_item_record_fall_back(self):
        """項目の控えの無い往復（note_plan なし）では、2 往復目の新しい block への missed・rephrased の申告を採らない。unsplit に
        落ち、申告は origins_claimed に残る"""
        b = self.board(2)
        converge.record_pass(b, {"faces": [face("key-a1")]}, resolved=[], files={})
        claims = [{"key": "key-b1", "origin": converge.ORIGIN_MISSED},
                  {"key": "key-a2", "origin": converge.ORIGIN_REPHRASED, "of": "key-a1"}]
        got = converge.record_pass(b, {"faces": [face("key-b1"), face("key-a2")]}, resolved=["key-a1"], files={},
                                   origins=claims)
        self.assertEqual(got["origins"], {"key-b1": converge.ORIGIN_UNSPLIT, "key-a2": converge.ORIGIN_UNSPLIT})
        self.assertEqual(got["origins_claimed"], claims)

    def test_hold_is_not_counted_as_open_for_decay(self):
        """保留の項目の block は開いた数に数えない: 1 往復目は u1・u2・u3 に 1 件ずつ、2 往復目は u1 が同じ block（保留）で u2・u3 が
        新しい block（開いた数 2 < 3）、3 往復目は u2 だけ（開いた数 1 < 2）。保留の block を数えると 2 往復目で減らず止まる"""
        converge.note_plan(self.b, [row("u1"), row("u2"), row("u3")])
        self.review([face("key-a1", units=["u1"]), face("key-b1", units=["u2"]), face("key-c1", units=["u3"])])
        got = self.review([face("key-a1", units=["u1"]), face("key-b2", units=["u2"]), face("key-c2", units=["u3"])])
        self.assertEqual((self.states(got), got["outcome"]), ([converge.HELD, converge.OPEN, converge.OPEN], converge.AGAIN))
        got = self.review([face("key-b3", units=["u2"])], resolved=["key-b2", "key-c2"])
        self.assertEqual((self.states(got), got["outcome"]), ([converge.HELD, converge.OPEN, converge.CLOSED], converge.AGAIN))

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
        self.assertEqual(got["outcome"], converge.AGAIN, "保留の項目のほかに開いた項目が在れば、開いた数が減る間は進む")
        self.assertEqual(converge.open_items(self.b), [2])
        got = self.review([], resolved=["key-b2"])
        self.assertEqual(self.states(got), [converge.HELD, converge.CLOSED])
        self.assertEqual(got["outcome"], converge.PERSISTED)

    def test_fence_with_held_item_is_persisted_and_without_is_unsettled(self):
        """開いた数が減り続ける 3 往復目は、輪の上限の周（at_cap）として記録した時だけ止まる。止まる時の抜け方は、保留の項目が
        在れば PERSISTED・無ければ UNSETTLED（at_cap でなければ AGAIN）"""
        held_passes = ([face("key-a1", units=["u1"]), *[face(f"key-b{n}", units=["u2"]) for n in (1, 2, 3)]],
                       [face("key-a1", units=["u1"]), face("key-b4", units=["u2"]), face("key-b5", units=["u2"])],
                       [face("key-b6", units=["u2"])])
        plain_passes = tuple([face(k, units=["u1"]) for k in keys]
                             for keys in (("key-c1", "key-c2", "key-c3"), ("key-c4", "key-c5"), ("key-c6",)))
        for rnd, passes, at_cap, want in ((2, held_passes, False, converge.AGAIN), (3, held_passes, True, converge.PERSISTED),
                                          (4, plain_passes, False, converge.AGAIN), (5, plain_passes, True, converge.UNSETTLED)):
            with self.subTest(held=passes is held_passes, at_cap=at_cap):
                b = self.board(rnd)
                converge.note_plan(b, [row("u1"), row("u2")])
                for n, faces in enumerate(passes, 1):
                    got = converge.record_pass(b, {"faces": faces}, resolved=[], files={}, at_cap=at_cap and n == len(passes))
                self.assertEqual(got["outcome"], want)
                self.assertIs(got.get("capped", False), at_cap)

    def test_items_count_open_blocks_for_decay(self):
        self.review([face("key-a1", units=["u1"]), face("key-b1", units=["u2"])])
        got = self.review([face("key-a2", units=["u1"]), face("key-b2", units=["u2"])])
        self.assertEqual(got["outcome"], converge.UNSETTLED)
        b = self.board(2)
        converge.note_plan(b, [row("u1"), row("u2")])
        converge.record_pass(b, {"faces": [face("key-a1", units=["u1"]), face("key-b1", units=["u2"])]},
                             resolved=[], files={})
        got = converge.record_pass(b, {"faces": [face("key-a2", units=["u1"])]}, resolved=["key-b1"], files={})
        self.assertEqual(got["outcome"], converge.AGAIN)

    def test_persisted_by_count_names_open_counts(self):
        """保留の項目が在り、開いた数が減らずに PERSISTED で止まった時も、関所の理由に往復ごとの開いた数が出る"""
        self.review([face("key-a1", units=["u1"]), face("key-b1", units=["u2"])])
        got = self.review([face("key-a1", units=["u1"]), face("key-b2", units=["u2"])])
        self.assertEqual(got["outcome"], converge.AGAIN)   # 2 → 1 に減った
        got = converge.record_pass(self.b, {"faces": [face("key-b3", units=["u2"])]}, resolved=[], files={})
        self.assertEqual(got["outcome"], converge.PERSISTED)
        why = converge.stuck_reason(self.b)
        self.assertIn("開いた block の数: 1 往復目 2 → 2 往復目 1 → 3 往復目 1（前の往復より減らなかった）", why)

    def test_synergy_block_reopens_named_closed_item(self):
        self.review([face("key-a1", units=["u1"])])
        got = self.review([face("key-s1", units=["u2"])], resolved=["key-a1"], synergy=["key-s1"])
        self.assertEqual(self.states(got), [converge.CLOSED, converge.OPEN])
        self.assertTrue(got["items"][1]["reopened"])
        self.assertEqual(got["synergy"], ["key-s1"])
        self.assertEqual(got["outcome"], converge.UNSETTLED)   # 1 → 1 で減らない

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
