"""関所の項目の推し（gatemarks の recommend）と、無人の run が関所で止まった時の答えの下書き（gatemarks.answer_drafts）。
FAST: test_plan_gate の偽の盤面で写しの RL の human_gate を直に呼ぶ（盤面・git・子のプロセスなし）。

実の利用者の run ac9e02ab は無人の run で、直す前の関所に 2 件（方針の文書の柵 policy_doc）が挙がって止まった。関所の文の推しは
「判定の役が書いていない」と出て、機械が読める推しの答えはどこにも無く、次の run の依頼の下書き next-request.json は空だった。
役が関所に回す行に構造の推し recommend {answer, note, why} を書き、無人の run が関所で止まったら、項目ごとの答えの下書きを
next-request.json の answers に draft: true と出どころ source つきで置く。機械は関所に答えない（下書きを使う前に人が見直す）。
"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))
import test_plan_gate as TP  # noqa: E402  （ラインの模块の置き場も sys.path に足す）
import accept  # noqa: E402
import gatemarks  # noqa: E402
import carry  # noqa: E402
import line_edge  # noqa: E402
import report  # noqa: E402

REC = {"answer": "continue", "note": "daemon だけを Recreate にする範囲で通す", "why": "Dagster 公式の chart が同じ分け方"}
ASKED = {**TP.DECIDED, "fences": ["policy_doc"]}   # 決め手は在るが柵に当たる（ac9e02ab の 2 件の形）
NO_NARROW = "daemon を別の Deployment に分け、webserver は RollingUpdate に残す形を当たったが、決着済みの配置を組み替える"
WORLD = "Dagster 公式の Helm chart は daemon だけを別の Deployment にして Recreate にする"


class SchemaCase(unittest.TestCase):
    def test_gate_rows_have_the_recommend_field(self):
        for node, row in (("p2.fix_plan", lambda s: s["properties"]["plan"]["items"]["properties"]["narrows"]["items"]),
                          ("p2.plan_review", lambda s: s["properties"]["faces"]["items"])):
            with self.subTest(node):
                rec = row(accept.role_schema(node))["properties"][gatemarks.RECOMMEND]
                self.assertEqual(sorted(rec["required"]), ["answer", "note", "why"])
                self.assertEqual(rec["properties"]["answer"]["enum"], ["continue", "stop"])
                self.assertNotIn(gatemarks.RECOMMEND, row(accept.role_schema(node)).get("required", []))

    def test_rule_text_asks_for_recommend(self):
        for node in gatemarks.NODES:
            self.assertIn(gatemarks.RECOMMEND, gatemarks.HEAD[node])


class GapsCase(unittest.TestCase):
    def plan(self, rec):
        return {"plan": [{"narrows": [{**TP.NARROW, "no_narrow": NO_NARROW, **({"recommend": rec} if rec is not None else {})}]}]}

    def test_absent_and_good_recommend_pass(self):
        self.assertEqual(gatemarks.recommend_gaps("p2.fix_plan", self.plan(None)), [])
        self.assertEqual(gatemarks.recommend_gaps("p2.fix_plan", self.plan(REC)), [])

    def test_malformed_recommend_is_named(self):
        for bad in ({**REC, "answer": "maybe"}, {k: v for k, v in REC.items() if k != "why"}, "通す", {**REC, "note": ""}):
            with self.subTest(bad=bad):
                got = gatemarks.recommend_gaps("p2.fix_plan", self.plan(bad))
                self.assertEqual(len(got), 1, got)
                self.assertIn("plan[0].narrows[0]", got[0])

    def test_review_faces_are_checked_too(self):
        got = gatemarks.recommend_gaps("p2.plan_review", {"faces": [{**TP.FACE, "recommend": {"answer": "x"}}]})
        self.assertEqual(len(got), 1, got)
        self.assertIn("faces[0]", got[0])

    def test_split_takes_recommend_off_and_save_keeps_it(self):
        reply = self.plan(REC)
        bare, marks = gatemarks.split("p2.fix_plan", reply)
        self.assertNotIn(gatemarks.RECOMMEND, bare["plan"][0]["narrows"][0])
        self.assertEqual(marks[0][0][gatemarks.RECOMMEND], REC)


class PushCase(TP.GateBase):
    def test_asked_row_carries_the_recommend_and_the_gate_pushes_it(self):
        got, _ = self.gate(narrows=[{**TP.NARROW, **ASKED, gatemarks.RECOMMEND: REC}])
        item = got["ask"]["items"][0]
        self.assertTrue(item.endswith(f"／推し: 通す（continue）——{REC['note']}（理由: {REC['why']}）"), item)
        text = line_edge.gate_text({"node": "p2.human_gate", **got["ask"]})
        self.assertIn(f"推し: 通す（continue）——{REC['note']}", text.splitlines()[2])

    def test_slash_in_the_push_is_kept_out_of_the_tail_mark(self):
        """推しの文に「／」が在っても尾は 1 つの区切りで終わる（R4 の照らしで外す形 PUSH_TAIL と、推しの拾い PUSH_IN が全文を読む）"""
        rec = {**REC, "note": "A／B の範囲で通す"}
        got, _ = self.gate(narrows=[{**TP.NARROW, **ASKED, gatemarks.RECOMMEND: rec}])
        item = got["ask"]["items"][0]
        self.assertEqual(item.count("／"), 1, item)
        self.assertNotIn("推し", gatemarks.PUSH_TAIL.sub("", item))

    def test_row_without_recommend_is_as_before(self):
        got, _ = self.gate(narrows=[{**TP.NARROW, **ASKED}])
        self.assertNotIn("／推し", got["ask"]["items"][0])


class DraftsCase(TP.GateBase):
    def unattended(self):
        (self.tmp / "r1").mkdir(exist_ok=True)
        (self.tmp / "r1" / "start.json").write_text('{"unattended": "true"}', encoding="utf-8")

    def stopped(self, b, got):
        """無人の殻が関所に stop を答えた（写しの human_gate_answered と同じ形の行）"""
        b.record["process"]["human_items"].append({"round": 1, "kinds": got["ask"]["kinds"], "asked": got["ask"]["items"],
                                                   "answer": "stop", "note": "無人の run: 止めて報告へ", "node": "p2.human_gate"})

    def test_each_stopped_item_gets_a_marked_draft(self):
        """recommend の行は推しの答え、無い行は狭めない案・世界の解を下書きにし、どの行も draft: true と出どころを持つ"""
        self.unattended()
        got, b = self.gate(narrows=[{**TP.NARROW, **ASKED, gatemarks.RECOMMEND: REC}],
                           faces=[{**TP.FACE, **ASKED, "world": WORLD, "no_narrow": NO_NARROW}])
        self.stopped(b, got)
        drafts = gatemarks.answer_drafts(b)
        self.assertEqual(len(drafts), 2, drafts)
        self.assertTrue(all(d["draft"] is True and d["source"] for d in drafts), drafts)
        first, second = drafts
        self.assertIn(TP.NARROW["what"], first["question"])
        self.assertEqual(first["text"], f"continue: {REC['note']}（推す理由: {REC['why']}）")
        self.assertIn("recommend", first["source"])
        self.assertIn(TP.FACE["key"], second["question"])
        self.assertEqual(second["text"], "", "推しの無い行は答えを置かない（材料は note）")
        self.assertIn(NO_NARROW, second["note"])
        self.assertIn(WORLD, second["note"])
        self.assertNotIn("note", first)
        self.assertIn("no_narrow", second["source"])
        self.assertIn("world", second["source"])

    def test_unattended_world_deviation_stops_with_draft(self):
        """無人の run も世界の解の外れの項目で関所を開き（人がいる run と同じ決まり）、無人の殻が止めた項目には答えの下書きが残る。
        下書きの材料は行の定石と依頼の解き方との比べ"""
        wg = TP.WorldGateCase.put_world, TP.WorldGateCase.put_answers
        self.unattended()
        wg[0](self, TP.WORLD_ROW)
        wg[1](self, {"world": "w-mean", "deviation": "呼び手の都合で 0 を返す形に寄せたい、と考えた"})
        got, b = self.gate()
        self.assertEqual(got.get("decision"), "ask", got)
        self.stopped(b, got)
        drafts = [d for d in gatemarks.answer_drafts(b) if "w-mean" in d["question"]]
        self.assertEqual(len(drafts), 1, gatemarks.answer_drafts(b))
        self.assertIs(drafts[0]["draft"], True)
        self.assertIn("WG-4410", drafts[0]["note"])

    def test_row_with_nothing_still_gets_a_draft_saying_so(self):
        self.unattended()
        got, b = self.gate(narrows=[dict(TP.NARROW)])
        self.stopped(b, got)
        drafts = gatemarks.answer_drafts(b)
        self.assertEqual(len(drafts), 1)
        self.assertEqual(drafts[0]["text"], "")
        self.assertIn("書いていない", drafts[0]["note"])

    def test_placeholder_rows_do_not_become_answers_when_only_the_marks_are_deleted(self):
        """推しの無い行（台帳の問いの選択肢だけ・関所の項目の案だけ）は text を空にし、材料を note に置く。人が draft と source だけを
        消しても、依頼の入口が拒む（置き場の文が答えとして問いに当たらない）"""
        self.unattended()
        fork = {**TP.FORK, "reason": "どちらにも理由が在る", "options": ["例外", "空の値"]}
        _, b = self.gate(questions=[fork], units=TP.UNITS)
        drafts = gatemarks.answer_drafts(b)
        self.assertEqual([d["question"] for d in drafts], [TP.FORK["key"]])
        self.assertEqual(drafts[0]["text"], "")
        self.assertIn("例外・空の値", drafts[0]["note"])
        bare = {k: v for k, v in drafts[0].items() if k not in carry.DRAFT_KEYS}
        with self.assertRaises(ValueError):
            carry.parts({"findings": [], "answers": [bare]})
        with self.assertRaises(ValueError):
            carry.parts({"findings": [], "answers": [{k: v for k, v in bare.items() if k != "note"}]})

    def test_held_ledger_question_gets_its_push_as_draft_keyed_by_the_question(self):
        """無人の run は台帳の問いを関所に載せない。保留のままの fork は、key を question にした推しの下書きになる（見直して
        draft を外せば、次の run の依頼の answers がその問いに当たる）"""
        self.unattended()
        _, b = self.gate(questions=[TP.FORK], units=TP.UNITS)
        drafts = gatemarks.answer_drafts(b)
        self.assertEqual([d["question"] for d in drafts], [TP.FORK["key"]])
        self.assertEqual(drafts[0]["text"], "例外——呼び手が既に例外を捕まえている")
        self.assertIn("推し", drafts[0]["source"])

    def test_attended_run_gets_no_gate_item_drafts(self):
        got, b = self.gate(narrows=[{**TP.NARROW, **ASKED, gatemarks.RECOMMEND: REC}])
        self.stopped(b, got)
        self.assertEqual(gatemarks.answer_drafts(b), [])

    def test_attended_run_drafts_held_questions(self):
        """人の居る run でも、保留のままの台帳の問いには答えの下書きを作る（利用者の run 8cb2ee00 は人の居る run で下書きが無く、
        利用者は報告の文から問いの名を推して書き、字が合わなかった。利用者の声 10-09 の C4）。関所の項目の下書きは無人の run だけ"""
        got, b = self.gate(narrows=[{**TP.NARROW, **ASKED, gatemarks.RECOMMEND: REC}], questions=[TP.FORK], units=TP.UNITS)
        self.stopped(b, got)
        self.assertEqual([d["question"] for d in gatemarks.answer_drafts(b)], [TP.FORK["key"]])

    def test_field_question_from_a_material_is_drafted_by_the_material_name(self):
        """素材から立った field の問い（key の頭が測れていない素材の名）は、短い素材の名を question にした下書きになり、保留の行にも
        依頼の answers に書く question を区切りの分かる形で出す"""
        _, b = self.gate(questions=[TP.FIELD_PR], units=TP.UNITS, materials=TP.PR_NOT_RUN)
        drafts = gatemarks.answer_drafts(b)
        self.assertEqual([d["question"] for d in drafts], ["parallel_pr"])
        self.assertIn('answers の question: "parallel_pr"', gatemarks.held_lines(b)[0])

    def test_unmeasured_material_without_question_gets_a_draft(self):
        """問いの立っていない測れていない素材にも、素材の名の下書きを作る（利用者の run f6eaf0a0）。答えた素材には作らない"""
        _, b = self.gate(units=TP.UNITS, materials=TP.PR_NOT_RUN)
        drafts = gatemarks.answer_drafts(b)
        self.assertEqual([(d["question"], d["text"]) for d in drafts], [("parallel_pr", "")])
        self.assertIn("command", drafts[0]["note"])
        TP.RequestAnswersCase.answers(self, TP.MEASURED)
        self.assertEqual(gatemarks.answer_drafts(b), [])

    def test_drafts_go_into_the_next_request_doc_and_the_head_names_the_file(self):
        self.unattended()
        got, b = self.gate(narrows=[{**TP.NARROW, **ASKED, gatemarks.RECOMMEND: REC}])
        self.stopped(b, got)
        doc = report.next_doc(b, [], [])
        self.assertEqual(doc["answers"], gatemarks.answer_drafts(b))
        self.assertEqual(report.next_doc(types_board_without_drafts(self), [], []), {"findings": [], "prior_failures": []})
        line = gatemarks.draft_line(doc["answers"], "/b/next-request.json")
        self.assertIn("1 件", line)
        self.assertIn("/b/next-request.json", line)
        self.assertIn("draft", line)


def types_board_without_drafts(case):
    """人の居る run（start の控えが無い）の偽の盤面"""
    _, b = TP.GateBase.gate(case, narrows=[dict(TP.NARROW)])
    (case.tmp / "r1" / "start.json").unlink(missing_ok=True)
    return b


class R4PushTailCase(TP.GateBase):
    """修正前の関所で人が通した狭まりの本文は、推しの尾（「／推し: …」）を外して照らす。R4 が推しの尾の無い本文を写しても
    修正の後の関所で聞き直さない（審査の指摘。前は尾の無かった行が、推しの尾で照らしから外れた）"""

    def test_r4_does_not_reask_when_the_asked_row_had_a_push_tail(self):
        got, b = self.gate(narrows=[{**TP.NARROW, **ASKED, gatemarks.RECOMMEND: REC}])
        self.assertIn("／推し", got["ask"]["items"][0])
        b.record["process"]["human_items"].append({"round": 1, "kinds": got["ask"]["kinds"], "asked": got["ask"]["items"],
                                                   "answer": "continue", "note": "", "node": "p2.human_gate"})
        body = got["ask"]["items"][0][len("修正案 1 が狭める能力: "):].split("／推し")[0]
        self.assertNotIn("推し", gatemarks.carried_section(b))
        before = b.output_of_round
        r4 = {"capability_inventory": {"fired": True, "lost": [body]}, "policy_conflicts": []}
        b.output_of_round = lambda nid, rnd: r4 if nid == "r4.hidden_scope" else before(nid, rnd)
        self.assertEqual(TP.registry(b.rules, "BUILTINS")["human_gate"](b, "r4.human_gate"), {"ok": True})


class IntakeCase(unittest.TestCase):
    def test_draft_answers_are_refused_with_how_to_use_them(self):
        """下書きのまま次の run の依頼に渡すと、機械の下書きが人の答えとして関所の問いに当たる。依頼の入口は draft・source の
        欄の在る行を拒み、見直し方を言う"""
        for row in ({"question": "q", "text": "t", "draft": True, "source": "s"}, {"question": "q", "text": "t", "source": "s"}):
            with self.subTest(row=row):
                with self.assertRaises(ValueError) as cm:
                    carry.parts({"findings": [], "answers": [row]})
                self.assertIn("下書き", str(cm.exception))
                self.assertIn("draft", str(cm.exception))

    def test_refusal_tells_gate_rows_from_ledger_rows(self):
        """拒否の文は、台帳の問いの行（draft と source を消せば使える）と関所の項目の行（次の run の関所の一言の材料で、依頼では
        何にも当たらないので消す）を分けて言う（審査の指摘）"""
        with self.assertRaises(ValueError) as cm:
            carry.parts({"findings": [], "answers": [{"question": "q", "text": "t", "draft": True, "source": "s"}]})
        self.assertIn("台帳の問い", str(cm.exception))
        self.assertIn("関所の項目", str(cm.exception))

    def test_carry_ci_keeps_drafts_as_they_are(self):
        """CI の赤を足す口（carry_ci）は下書きの行で止まらず、そのまま残す（審査の再現: 無人の run の下書きで exit 2 だった）"""
        draft = {"question": "q", "text": "t", "draft": True, "source": "s"}
        got = carry.carry_ci({"findings": [], "prior_failures": [], "answers": [draft]}, ["tests/test_x.py::t"])
        self.assertEqual(got["answers"], [draft])
        self.assertEqual(len(got["prior_failures"]), 1)

    def test_reviewed_answer_passes(self):
        got = carry.parts({"findings": [], "answers": [{"question": "q", "text": "t"}]})
        self.assertEqual(got["answers"], [{"question": "q", "text": "t"}])


if __name__ == "__main__":
    unittest.main()
