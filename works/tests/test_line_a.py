"""ライン darkfactory を Archon 無しで通す試験（P1 計画 Task 28・〔線A計〕T16。C18 の順）。

linekit.run_line が LINE_ORDER の順に、境の節・ブロックの口・関所の答えを本物の盤面（種の git）の上で回し、報告の結末を見る。
Archon の配線（with: → INPUTS_*・when:・関所）は test_line.py と dev/check.sh の模擬実行が見る。
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))

import converge  # noqa: E402
import entry  # noqa: E402
import engine.util as engine_util  # noqa: E402,F401  （entry が写しの engine を sys.path に足した後。単独で起こしても読める）
import gatemarks  # noqa: E402
import line_edge  # noqa: E402
import linekit  # noqa: E402
from test_edge import CLEAN_REVIEW, DELTA_FACE, DELTA_FIX, DELTA_REVIEW, FACE, ODD_NOTE, fix_reply, plan_reply  # noqa: E402


def fix_tree(repo):
    """種の 2 つのバグを作業ツリーで直す（修正役の代わり）"""
    src = (repo / "stats.py").read_text(encoding="utf-8")
    (repo / "stats.py").write_text(src.replace("(len(xs) - 1)", "len(xs)").replace(
        "    if x > hi:\n        return lo", "    if x > hi:\n        return hi"), encoding="utf-8")


# 修正案の役の返答の works の欄（route・tests・rewrite_tests・refactor・allowed_paths・out_of_scope。planmarks）。線は修正案を
# blk-plan の受け付け（planmarks.gaps）に通すので、欄が欠ければ 3 回とも拒まれて盤面が止まる（by works:plan）。test_edge.plan_reply は
# 受け付けが欄を外した後の形（entry.take を直に呼ぶ道の物）なので、ここで欄を足す。種の test_stats.py は 3 件のうち
# 2 件が今の 2 つのバグで赤なので、受け入れのテストを先に足さず direct で直す
PLAN_FIELDS = {"route": "direct",
               "route_why": "種の test_stats.py の 3 件のうち 2 件が今の 2 つのバグで赤になり、直した後の振る舞いを既に確かめている",
               "tests": [], "rewrite_tests": [], "refactor": {"declared": False, "why": ""},
               "allowed_paths": ["stats.py", "test_stats.py"], "out_of_scope": []}
# 修正案の works の欄を控えた run の 1 回目の差分の審査の準拠（deltamarks。承認済みの項目と照らし、落ちた行は無い）
REVIEW_COMPLIANCE = {"verdict": "pass", "items": [],
                     "read": "承認済みの修正案の項目 1 の approach・allowed_paths と差分の stats.py を読み、足りない物も範囲の外の物も無い"}


def replies(review="plan_review_regression"):
    """役の返答の組。修正案は役そのものの返答（項目に works の欄 PLAN_FIELDS）、1 回目の差分の審査の準拠は控えの在る run の
    pass（REVIEW_COMPLIANCE。品質は DELTA_REVIEW のまま: 穴が在れば fail）。見本の事前審査は後退の穴を block で挙げるので、
    壁打ち（依頼 231）で同じ block が続いて、修正前の関所に後退の項目と修正に進まない行が載る"""
    return {"judge": linekit.reply("judge_ok"), "plan": {"plan": [{**row, **PLAN_FIELDS} for row in plan_reply()["plan"]]},
            "plan-review": linekit.reply(review) if isinstance(review, str) else review,
            "fix": fix_reply(faces=review == "plan_review_regression"),
            "review": {**DELTA_REVIEW, "compliance": REVIEW_COMPLIANCE}, "refix": DELTA_FIX}


def clean_replies():
    """事前審査に穴の無い返し。修正役は塞いだ穴を言わないので、差分の審査も塞いだ穴を確かめない（checks は空）"""
    r = replies(review=CLEAN_REVIEW)
    r["review"] = {**r["review"], "checks": []}
    return r


class LineBase(unittest.TestCase):
    def setUp(self):
        self._old_cwd = engine_util.GIT_CWD
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        self.tmp = pathlib.Path(self._tmp.name)
        env = mock.patch.dict(os.environ, {"WORKS_ADAPTER_HOME": str(self.tmp / "adapter-home")})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        engine_util.GIT_CWD = self._old_cwd
        self._tmp.cleanup()

    def run_line(self, **kw):
        kw.setdefault("replies", replies())
        kw.setdefault("edits", {"fix": fix_tree})
        return linekit.run_line(self.tmp, **kw)

    def order_ok(self, trail):
        ids = [r["id"] for r in linekit.LINE_ORDER]
        self.assertEqual(trail, sorted(trail, key=ids.index), "trail が LINE_ORDER の順でない")

    def state(self, got):
        return json.loads((got["board_dir"] / "state.json").read_text(encoding="utf-8"))


class LineCase(LineBase):
    def test_standard_full_path(self):
        """修正案 → 事前審査（後退の穴。壁打ちで同じ block が続く）→ policy-gate continue（後退の項目と修正に進まない行）→ 修正 →
        差分の審査（穴）→ 手直し → 最後のテスト（緑）→ 最後の関所 continue → 報告 fixed。trail は LINE_ORDER の順、報告と
        次の依頼の下書きが盤面に在る"""
        got = self.run_line(gates={"policy-gate": {"decision": "continue", "text": "clamp の上限は hi でよい"}}, github=True)
        self.order_ok(got["trail"])
        for nid in ("start", "premising", "judging", "planning", "policy-gate", "fixing", "reviewing", "refixing", "testing",
                    "final-gate", "report"):
            self.assertIn(nid, got["trail"])
        # origin は GitHub の形で偽の gh が交差を返すので、並行 PR の engine の helper は任せ先に落ちる（blk-pr が回る）
        self.assertIn("pr-checking", got["trail"])
        self.assertEqual(got["outcome"], "fixed", pathlib.Path(got["report"]["report_file"]).read_text(encoding="utf-8"))
        self.assertTrue(got["report"]["tests_green"])
        self.assertTrue(pathlib.Path(got["report"]["report_file"]).is_file())
        self.assertTrue(pathlib.Path(got["report"]["next_request_file"]).is_file())
        # 修正の前の関所の一言は human_items に 1 バイトも変わらずに届き、修正役へは notes_file で届いた
        notes = pathlib.Path(got["out"]["h-fix"]["notes_file"]).read_text(encoding="utf-8")
        self.assertEqual(notes, "clamp の上限は hi でよい")
        # 1 本目の finish の欄を全部持つ
        self.assertLessEqual({"ok", "outcome", "judgment_file", "review_file", "diff_file", "faces"}, set(got["report"]))

    def test_depth_standard_keeps_every_check(self):
        """深さ（計画 2026-10-06-variable-depth）: 機械の確かめ（test_cmd・tdd_suite）の無い run は単位が標準で、レンズも
        コメントの削除候補も今どおり回り、報告の冒頭 2 に深さの行が在る"""
        got = self.run_line(gates={"policy-gate": {"decision": "continue", "text": "clamp の上限は hi でよい"}})
        self.assertEqual((got["out"]["h-depth"]["depth"], got["out"]["h-redepth"]["skip"]), ("標準", ""))
        for role in ("r1-comments", "r1-minimality", "r2-compare", "r3-coherence", "r4-scope"):
            self.assertIn(role, got["eyes_roles"])
        self.assertIn("reviewing", got["trail"])
        b = entry.open_board(got["board_dir"], allow_halted=True)
        self.assertEqual(set(b.rd["skipped"]) & {"p3.delta_review", "r1.comment_candidates", "r1.minimality", "r2.compare",
                                                 "r3.coherence", "r4.hidden_scope"}, set())
        rec = json.loads((got["board_dir"] / "rounds" / "round-1.json").read_text(encoding="utf-8"))
        self.assertNotIn("skipped", {r["status"] for r in rec["reviews"].values()})
        text = pathlib.Path(got["report"]["report_file"]).read_text(encoding="utf-8")
        self.assertIn("深さ: 標準", text)
        self.assertNotIn("軽量で省いた", text)

    def test_depth_light_skips_checks_and_names_them(self):
        """入力 thickness 軽量で全部の単位が軽量のまま（上げる信号が無い）なら、差分の審査（とその後のレンズ・手直し）と独立の目
        R1〜R4 を盤面で省き（記録の reviews は skipped と理由。収束を止めない）、報告の冒頭 2 に「軽量で省いた」の 1 行で名指す。
        結末は fixed のまま（持ち主の決定 2026-10-06）"""
        got = self.run_line(gates={"policy-gate": {"decision": "continue", "text": "clamp の上限は hi でよい"}},
                            inputs={"thickness": "軽量"})
        red = got["out"]["h-redepth"]
        self.assertEqual(red["depth"], "軽量", red)
        self.assertIn("軽量", red["skip"])
        self.assertEqual(got["outcome"], "fixed", pathlib.Path(got["report"]["report_file"]).read_text(encoding="utf-8"))
        self.assertEqual(got["eyes_roles"], [])
        for nid in ("lensing", "reviewing", "refixing"):
            self.assertNotIn(nid, got["trail"])
        b = entry.open_board(got["board_dir"], allow_halted=True)
        for nid in ("p3.delta_review", "r1.comment_candidates", "r1.minimality", "r2.compare", "r3.coherence", "r4.hidden_scope"):
            self.assertEqual(b.rd["skipped"].get(nid), red["skip"], nid)
        rec = json.loads((got["board_dir"] / "rounds" / "round-1.json").read_text(encoding="utf-8"))
        for name in ("R1", "R2", "R3", "R4"):
            self.assertEqual(rec["reviews"][name]["status"], "skipped", name)
            self.assertIn("軽量", rec["reviews"][name]["reason"])
        text = pathlib.Path(got["report"]["report_file"]).read_text(encoding="utf-8")
        import depth
        skipped = [x for x in text.splitlines() if x.startswith("- 軽量で省いた: ")]
        self.assertEqual(len(skipped), 1, text)
        for what in depth.SKIPPED:
            self.assertIn(what, skipped[0])

    def test_no_fix_path(self):
        """判定が直す物を残さない → 修正・審査・手直しは飛び、最後のテストは周を締めるので走る。結末 no_fix_needed。
        修正案のブロックは、最後の R2 が要る独立設計だけを作りに入る（修正案は盤面で na）"""
        r = replies(review=CLEAN_REVIEW)
        r["judge"] = linekit.reply("judge_no_fix")
        got = self.run_line(replies=r, edits={})
        self.order_ok(got["trail"])
        for nid in ("policy-gate", "fixing", "reviewing", "refixing"):
            self.assertNotIn(nid, got["trail"])
        self.assertIn("planning", got["trail"])
        self.assertEqual(got["out"]["planning"]["plan_file"], "")
        b = entry.open_board(got["board_dir"], allow_halted=True)
        self.assertEqual(b.node_state("p2.fix_plan"), "na")
        self.assertIn("r2.design", b.state["outputs"], "先に作った設計が最後の R2 の前に盤面へ渡った")
        self.assertIn("testing", got["trail"])
        self.assertEqual(got["outcome"], "no_fix_needed")

    def test_policy_gate_stop(self):
        """policy-gate の stop → 修正から後のブロックは飛び、報告は走って stopped_by_human"""
        got = self.run_line(gates={"policy-gate": {"decision": "stop", "text": "範囲が広すぎる"}})
        self.order_ok(got["trail"])
        for nid in ("fixing", "reviewing", "refixing", "testing", "final-gate"):
            self.assertNotIn(nid, got["trail"])
        # 修正の前の関所の stop は周の途中の答え（盤面は halted.by answer）で、盤面は報告の役の節を出さない
        self.assertEqual(got["trail"][-3:], ["h-eyes", "report", "result"])
        self.assertEqual(got["outcome"], "stopped_by_human")

    def test_design_only_opens_policy_gate_without_other_items(self):
        """事前審査に穴が無く design_only も無い run では policy-gate は開かない（下の 2 本で開けたのが設計だけの行だと言える対照）"""
        got = self.run_line(replies=clean_replies())
        self.assertNotIn("policy-gate", got["trail"])
        self.assertIn("fixing", got["trail"])

    def test_design_only_policy_gate_stop(self):
        """design_only=true・ほかに開ける理由の無い run → 修正前の関所が設計だけの行で開き、stop なら修正から後を飛ばして
        報告へ（stopped_by_human）"""
        got = self.run_line(replies=clean_replies(), inputs={"design_only": "true"},
                            gates={"policy-gate": {"decision": "stop", "text": "設計だけで止める"}})
        self.order_ok(got["trail"])
        self.assertIs(got["out"]["h-gate"]["ask"], True)
        self.assertIn(gatemarks.DESIGN_ONLY_ITEM, got["out"]["h-gate"]["gate_text"])
        self.assertIn("policy-gate", got["trail"])
        for nid in ("fixing", "reviewing", "refixing", "testing", "final-gate"):
            self.assertNotIn(nid, got["trail"])
        self.assertEqual(got["trail"][-3:], ["h-eyes", "report", "result"])
        self.assertEqual(got["outcome"], "stopped_by_human")

    def test_design_only_policy_gate_continue(self):
        """design_only=true・ほかに開ける理由の無い run → 設計だけの行に continue なら修正へ進み、関所は 2 度開かない"""
        got = self.run_line(replies=clean_replies(), inputs={"design_only": "true"},
                            gates={"policy-gate": {"decision": "continue", "text": ""}})
        self.order_ok(got["trail"])
        self.assertIn(gatemarks.DESIGN_ONLY_ITEM, got["out"]["h-gate"]["gate_text"])
        self.assertEqual(got["trail"].count("policy-gate"), 1)
        self.assertIn("fixing", got["trail"])
        self.assertEqual(got["outcome"], "fixed")

    def test_final_gate_stop(self):
        """最後の関所の stop → 止めた run にも報告が走り、結末 stopped_by_human。答えは final-gate-answer.json と human_items"""
        got = self.run_line(gates={"final-gate": {"decision": "stop", "text": "差分を人が読み直す"}})
        self.assertEqual(got["trail"][-4:], ["h-eyes", "report", "reporting", "result"])
        self.assertEqual(got["outcome"], "stopped_by_human")
        b = entry.open_board(got["board_dir"], allow_halted=True)
        ans = json.loads(b.work(line_edge.FINAL_GATE_ANSWER).read_text(encoding="utf-8"))
        self.assertEqual(ans["decision"], "stop")

    def test_final_gate_continue_note_reaches_report(self):
        """最後の関所の一言（$・引用符・改行・日本語）は human_items に 1 バイトも変わらずに届き、結末は fixed のまま"""
        got = self.run_line(gates={"final-gate": {"decision": "continue", "text": ODD_NOTE}})
        self.assertEqual(got["outcome"], "fixed")
        items = entry.open_board(got["board_dir"], allow_halted=True).record["process"]["human_items"]
        self.assertEqual([h["note"] for h in items if h.get("node") == line_edge.FINAL_GATE_BY][-1].encode("utf-8"),
                         ODD_NOTE.encode("utf-8"))

    def test_final_when_needed_green_skips_gate(self):
        """final_gate when_needed・最後のテストが緑 → 最後の関所は開かない"""
        got = self.run_line(inputs={"final_gate": "when_needed"})
        self.assertNotIn("final-gate", got["trail"])
        self.assertEqual(got["outcome"], "fixed")

    def test_stop_flag_at_review(self):
        """止め札を h-review の前に置く → 差分の審査から後は飛び、報告は stopped_by_request"""
        got = self.run_line(stop_at="h-review")
        for nid in ("reviewing", "refixing", "testing"):
            self.assertNotIn(nid, got["trail"])
        self.assertEqual(got["outcome"], "stopped_by_request")

    def test_lens_runs_before_review_and_reaches_brief(self):
        """修正が差分を作った run では、レンズのブロックが差分の審査の前に走り、指摘が出どころつきで審査役の brief に届く。
        全部のレンズが走った周の報告の「未確認のレンズ」は、なしと手直しの差分の 1 行"""
        import lens
        finding = {"where": "stats.py", "cite": "return hi", "why": "上限を超えた値を黙って hi に丸め、呼び元は気づけない"}
        r = replies()
        r["lens-silent-failure-hunter"] = {"findings": [finding]}
        got = self.run_line(replies=r)
        self.assertLess(got["trail"].index("lensing"), got["trail"].index("reviewing"))
        b = entry.open_board(got["board_dir"], allow_halted=True)
        brief = json.loads(b.work("review1-brief.json").read_text(encoding="utf-8"))
        self.assertEqual(brief["lens"][0]["findings"], [{"lens": "silent-failure-hunter", **finding}])
        text = pathlib.Path(got["report"]["machine_report_file"]).read_text(encoding="utf-8")
        self.assertIn("## 未確認のレンズ\n\n- なし（振り分けたレンズは全部走った）\n- " + lens.REFIX_NOTE, text)

    def test_failed_lens_node_still_reviews(self):
        """レンズの節が 1 本落ちても集め役が ok で終わり、差分の審査が走る。落ちたレンズは名前と理由で報告に出る"""
        r = replies()
        r["lens-silent-failure-hunter"] = None
        got = self.run_line(replies=r)
        for nid in ("lensing", "reviewing", "refixing", "testing"):
            self.assertIn(nid, got["trail"])
        self.assertIs(got["out"]["lensing"]["ok"], True)
        self.assertEqual(got["outcome"], "fixed")
        text = pathlib.Path(got["report"]["machine_report_file"]).read_text(encoding="utf-8")
        self.assertIn("- silent-failure-hunter: 落ちた（", text.split("## 未確認のレンズ", 1)[1])

    def test_failed_lens_collector_stops_run(self):
        """集め役そのものが落ちたら、ブロックの境が盤面を止め（by works:lens）、差分の審査は走らず、手直しの境の節は stop。
        報告は stopped_by_line で、止めた理由を出す"""
        import lens
        r = replies()
        r["lens-collect"] = "fail"
        got = self.run_line(replies=r)
        self.assertIs(got["out"]["lensing"]["ok"], False)
        for nid in ("reviewing", "refixing", "testing"):
            self.assertNotIn(nid, got["trail"])
        self.assertIs(got["out"]["h-refix"]["stop"], True)
        self.assertEqual(self.state(got)["stop"]["by"], lens.STOP_BY)
        self.assertEqual(got["outcome"], "stopped_by_line")
        self.assertIn("レンズの集め役が終わらなかった", pathlib.Path(got["report"]["machine_report_file"]).read_text(encoding="utf-8"))

    def test_rollback_without_lens_block(self):
        """撤収（lensing を外し reviewing の依存を [h-review] に戻す）の線でも run は fixed で、報告のレンズの節は走らせていないと言う
        （節は常に出す。report.always_rows と同じく 0 件・走らせていないも黙らない）"""
        order = [{**r} for r in linekit.LINE_ORDER if r["id"] != "lensing"]
        rv = next(r for r in order if r["id"] == "reviewing")
        rv["depends_on"] = ["h-review"]
        rv.pop("trigger_rule")
        with mock.patch.object(linekit, "LINE_ORDER", order):
            got = self.run_line()
        self.assertIn("reviewing", got["trail"])
        self.assertEqual(got["outcome"], "fixed")
        text = pathlib.Path(got["report"]["machine_report_file"]).read_text(encoding="utf-8")
        section = text.split("## 未確認のレンズ", 1)[1].split("\n## ", 1)[0]
        self.assertEqual(section.strip(), "- レンズを走らせていない（控えが無い）")

    def test_premises_before_judge(self):
        """前提の実測は判定より前で、判定の入口の premises_file は盤面の p0.premises の出力"""
        got = self.run_line()
        self.assertLess(got["trail"].index("premising"), got["trail"].index("judging"))
        b = entry.open_board(got["board_dir"], allow_halted=True)
        self.assertEqual(got["out"]["h-judge"]["premises_file"], str(b.dir / b.state["outputs"]["p0.premises"]["file"]))


class EyesPurposeCase(LineBase):
    """目的の文（blk-purpose）と独立の目（blk-eyes）の配線（計画 P1 Task 33。目的の文は目の R1・R2 が読むので先に入れた）"""

    def test_purpose_before_judge(self):
        """前提 → h-judge → 目的の文 → h-mat → 判定。h-mat の purpose_file は盤面の p0.purpose の出力（目的の文を盤面へ渡した）"""
        got = self.run_line()
        t = got["trail"]
        self.assertLess(t.index("h-judge"), t.index("purposing"))
        self.assertLess(t.index("purposing"), t.index("h-mat"))
        self.assertLess(t.index("h-mat"), t.index("judging"))
        b = entry.open_board(got["board_dir"], allow_halted=True)
        self.assertEqual(b.node_state("p0.purpose"), "done")
        self.assertEqual(got["out"]["h-mat"]["purpose_file"], str(b.dir / b.state["outputs"]["p0.purpose"]["file"]))

    def test_eyes_before_final_gate(self):
        """最後のテストの後・最後の関所の前に独立の目（R1・R2 の筋）が回り、返答が盤面に在る。関所の文に目の判定が載る。周は目の後に
        締まり、結末 fixed（締めた盤面にも報告の節が出て AI の報告が回る。R61 の B）"""
        got = self.run_line()
        self.order_ok(got["trail"])
        t = got["trail"]
        self.assertLess(t.index("testing"), t.index("eyeing"))
        self.assertLess(t.index("eyeing"), t.index("final-gate"))
        self.assertEqual(t[-4:], ["h-eyes", "report", "reporting", "result"])
        for name in ("（R1）: 通った（pass）", "（R2）: 通った（pass）"):
            self.assertIn(name, got["out"]["h-final"]["gate_text"])
        # r2.design は目のブロックで起こさない（修正案のブロックで先に作り、h-look が盤面へ渡した）。この周の修正が差分を作ったので
        # R3・R4 も回る（133 件目の差し替え。works の 1 周の run では修正と同じ周に目を回す）
        self.assertEqual(set(got["eyes_roles"]), {"r1-comments", "r1-minimality", "r2-compare", "r3-coherence", "r4-scope"})
        b = entry.open_board(got["board_dir"], allow_halted=True)
        for nid in ("r1.comment_candidates", "r1.minimality", "r2.design", "r2.compare"):
            with self.subTest(nid):
                self.assertIn(nid, b.state["outputs"])
        self.assertEqual(got["out"]["eyeing"]["ok"], True)
        self.assertEqual(got["outcome"], "fixed", pathlib.Path(got["report"]["report_file"]).read_text(encoding="utf-8"))

    def test_final_gate_stop_after_eyes(self):
        """独立の目の後の最後の関所の stop → 結末 stopped_by_human。周は目の後に締まっているので、止めた事実は by human:final-gate の
        trace の 1 行（b.stop は周を締めた盤面を拒む）"""
        got = self.run_line(gates={"final-gate": {"decision": "stop", "text": "差分を人が読み直す"}})
        self.assertLess(got["trail"].index("eyeing"), got["trail"].index("final-gate"))
        self.assertEqual(got["outcome"], "stopped_by_human")
        rows = [json.loads(x) for x in (got["board_dir"] / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual([(r["reason"], r["by"]) for r in rows if r.get("op") == line_edge.STOP_AFTER_END_OP],
                         [("差分を人が読み直す", line_edge.FINAL_GATE_BY)])

    def test_eyes_asking_goes_to_next_run(self):
        """R4 が方針とのぶつかりを挙げ r4.human_gate が人に聞く → ブロックは止めずに asking で抜け（計画 Task 33 の (b)）、
        報告は needs_human。問いは最後の関所の文・報告の冒頭 1・次の run の依頼の下書きに載る（関所の continue は問いに答えない）"""
        import test_blk_eyes as TB
        r = replies(review=CLEAN_REVIEW)
        r["judge"] = linekit.reply("judge_no_fix")
        conflict = "clamp の上限を変えると方針の「既定値は変えない」とぶつかる"
        r["r4-scope"] = {**TB.SCOPE_OK, "policy_conflicts": [conflict]}
        got = self.run_line(replies=r, edits={})
        self.assertIn("r4-scope", got["eyes_roles"])
        self.assertIs(got["out"]["eyeing"]["asking"], True)
        self.assertIn(conflict, got["out"]["h-final"]["gate_text"])
        self.assertEqual(got["outcome"], "needs_human")
        text = pathlib.Path(got["report"]["report_file"]).read_text(encoding="utf-8")
        self.assertIn(conflict, text)
        nxt = json.loads(pathlib.Path(got["report"]["next_request_file"]).read_text(encoding="utf-8"))["findings"]
        self.assertTrue(any(conflict in it["text"] for it in nxt), nxt)


class AiReportCase(LineBase):
    """AI が書く報告と初見の検査（blk-report）を機械の報告の後に（計画 P1 Task 34）"""

    def test_ai_report_after_machine(self):
        """最後の関所の stop（盤面が報告の節を出す道）→ report → reporting → result。最後の報告は report-ai.md で、機械の
        report.md が字のまま最後に付く。結末は機械の報告のまま"""
        got = self.run_line(gates={"final-gate": {"decision": "stop", "text": "差分を人が読み直す"}})
        self.assertEqual(got["trail"][-3:], ["report", "reporting", "result"])
        rep = got["report"]
        self.assertEqual(pathlib.Path(rep["report_file"]).name, "report-ai.md")
        self.assertEqual(pathlib.Path(rep["machine_report_file"]).name, "report.md")
        self.assertEqual(rep["export_input"]["report_file"], rep["report_file"])
        self.assertEqual(rep["outcome"], "stopped_by_human")
        self.assertIs(rep["ai_report"]["ok"], True)
        machine = pathlib.Path(rep["machine_report_file"]).read_text(encoding="utf-8")
        self.assertIn(machine, pathlib.Path(rep["report_file"]).read_text(encoding="utf-8"))
        b = entry.open_board(got["board_dir"], allow_halted=True)
        for nid in ("report.human_items", "report.cold_check", "report"):
            self.assertEqual(b.node_state(nid), "done", nid)

    def test_ai_report_fail_keeps_machine(self):
        """書き手が 3 回とも拒まれて諦める → 最後の報告は機械の report.md、結末は変わらない。AI の報告の出口は ok: false と理由"""
        r = replies()
        r["report-give-up"] = True
        got = self.run_line(replies=r, gates={"final-gate": {"decision": "stop", "text": "x"}})
        rep = got["report"]
        self.assertEqual(pathlib.Path(rep["report_file"]).name, "report.md")
        self.assertEqual(rep["outcome"], "stopped_by_human")
        self.assertIs(rep["ai_report"]["ok"], False)
        self.assertIn("拒まれた", rep["ai_report"]["reason"])

    def test_human_items_wait_not_unfinished(self):
        """人が止めた盤面で機械の報告の時に report.human_items が待ち（報告の役の節）→ 結末は stopped_by_human のまま
        （record_invalid・needs_human に倒れない）で、ai_report_go が真"""
        r = replies()
        got = self.run_line(replies=r, gates={"final-gate": {"decision": "stop", "text": "x"}})
        self.assertIs(got["out"]["report"]["ai_report_go"], True)
        self.assertEqual(got["out"]["report"]["outcome"], "stopped_by_human")

    def test_round_closed_run_gets_ai_report(self):
        """周を締めて止めた普通の 1 周の run（stop_after_round）→ 機械の報告が盤面の層の口（report_after_round）で報告の節を
        出し、reporting が回る（R61 の B。持ち主の裁定）。最後の報告は report-ai.md、結末は fixed のまま"""
        got = self.run_line()
        self.assertEqual(got["trail"][-3:], ["report", "reporting", "result"])
        self.assertIs(got["out"]["report"]["ai_report_go"], True)
        rep = got["report"]
        self.assertEqual(pathlib.Path(rep["report_file"]).name, "report-ai.md")
        self.assertIs(rep["ai_report"]["ok"], True)
        self.assertEqual(got["outcome"], "fixed")
        b = entry.open_board(got["board_dir"], allow_halted=True)
        for nid in ("report.human_items", "report.cold_check", "report"):
            self.assertEqual(b.node_state(nid), "done", nid)
        self.assertEqual(b.state["works"]["after_round"]["by"], "stop_after_round")

    def test_no_fix_run_gets_ai_report(self):
        """直す物の無い 1 周の run も AI の報告が回り、結末は no_fix_needed のまま"""
        r = replies(review=CLEAN_REVIEW)
        r["judge"] = linekit.reply("judge_no_fix")
        got = self.run_line(replies=r, edits={})
        self.assertIn("reporting", got["trail"])
        self.assertEqual(got["outcome"], "no_fix_needed")


class MaterialCase(LineBase):
    """P1 の目と素材集め（blk-material）を目的の文の後・判定の前に（計画 P1 Task 32）"""

    def test_purpose_then_material_path(self):
        """h-mat → gathering（blk-material）→ judging。判定から入る 1 周目は P1 の目が写しの条件で na（盤面の周の箱に在る）で、前の決定の
        読み出し（p0.prior_decisions）だけが回る"""
        got = self.run_line()
        t = got["trail"]
        self.assertLess(t.index("h-mat"), t.index("gathering"))
        self.assertLess(t.index("gathering"), t.index("judging"))
        self.assertIs(got["out"]["h-mat"]["mat_go"], True)
        self.assertEqual(got["mat_roles"], ["prior-decisions"])
        b = entry.open_board(got["board_dir"], allow_halted=True)
        self.assertEqual(b.node_state("p0.prior_decisions"), "done")
        box = next(r for r in b.state["rounds"] if r.get("round") == 1)
        p1 = [n for n, e in b.table.nodes.items() if n.startswith("p1.") and e.by == "role"]
        self.assertEqual(len(p1), 9)
        for nid in p1:
            with self.subTest(nid):
                self.assertIn(nid, box["na"])
        self.assertIs(got["out"]["gathering"]["ok"], True)
        self.assertEqual(got["outcome"], "fixed")

    def test_purpose_review_due_no_die(self):
        """p0.purpose が role になり、目的の審査の条件（purpose_review_due）が前提の後の settle で落ちない。出典が ② の目的は
        審査を要らない（na）"""
        got = self.run_line()
        b = entry.open_board(got["board_dir"], allow_halted=True)
        self.assertIn(b.node_state("p0.purpose_review"), ("na", "done"))
        self.assertNotIn("purpose-review", got["mat_roles"])


class PriorFailuresLineCase(LineBase):
    """依頼の prior_failures（前の run で最後まで通らなかった物）は、判定の材料と修正案の役の指示書にだけ貼る。独立設計（r2.design）の
    指示書には貼らない（前の run の判断を知らずに考える目）"""
    PRIOR = [{"where": "受け付け take_p2_fix_plan", "text": "前の run の案は欄 route を欠いて 3 回とも拒まれた（見本の印 PF-7731）"}]

    def test_prior_failures_reach_judge_and_plan_only(self):
        rows = json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
        got = self.run_line(request={"findings": rows, "prior_failures": self.PRIOR})
        board = got["board_dir"]
        self.assertEqual(json.loads((board / entry.PRIOR_IN_FILE).read_text(encoding="utf-8")), self.PRIOR)
        mark = "PF-7731"
        judge = pathlib.Path(got["judge_brief"]["materials_file"]).read_text(encoding="utf-8")
        self.assertIn(entry.PRIOR_HEAD, judge)
        self.assertIn(mark, judge)
        prompts = {p.name: p.read_text(encoding="utf-8") for p in board.rglob("prompt-*.md")}
        plan = [t for n, t in prompts.items() if n == "prompt-p2.fix_plan.md"]
        self.assertTrue(plan, sorted(prompts))
        self.assertTrue(all(mark in t for t in plan))
        design_prompts = [t for n, t in prompts.items() if "r2.design" in n]
        self.assertTrue(design_prompts, sorted(prompts))
        for n, t in prompts.items():
            if "fix_plan" not in n:
                self.assertNotIn(mark, t, n)


class JudgeReadsCase(LineBase):
    """判定役が目的の文と素材を読む（R61 judgeread の A。本線の p2.diagnose の reads と同じ所を盤面から描く）"""

    def test_judge_brief_has_purpose_and_materials(self):
        """判定の支度（judge-brief）が盤面から本線の判定の指示書の「入力」の節を engine の描き方で描く: 凍結した目的・素材の
        15 欄・前の決定の突合・人の依頼・欠けた素材は materials_missing の決まり。穴も schema も残らない"""
        got = self.run_line()
        path = pathlib.Path(got["judge_brief"]["materials_file"])
        self.assertTrue(path.is_file(), got["judge_brief"])
        text = path.read_text(encoding="utf-8")
        b = entry.open_board(got["board_dir"], allow_halted=True)
        purpose = json.loads((b.dir / b.state["outputs"]["p0.purpose"]["file"]).read_text(encoding="utf-8"))["purpose_text"]
        prior = json.loads((b.dir / b.state["outputs"]["p0.prior_decisions"]["file"]).read_text(encoding="utf-8"))
        for needle in (purpose, "素材（15 欄）", "prior_decisions", prior["material"]["checked"], "先行議論の突合",
                       linekit.reply("request_ok")[0]["text"], "materials_missing"):
            with self.subTest(needle[:30]):
                self.assertIn(needle, text)
        self.assertNotIn("{{", text)
        self.assertNotIn("JSON Schema", text)   # 返答の型は判定役の output_format（YAML）が持つ。材料に schema を貼らない
        self.assertLess(got["trail"].index("gathering"), got["trail"].index("judging"))

    def test_judge_brief_refuses_after_judged(self):
        """盤面の p2.diagnose が待っていない（判定を盤面へ渡した後）に支度を回すのは線の順の誤り（BoardGap。黙って空にしない）"""
        from board import BoardGap
        got = self.run_line()
        import judgebrief
        with self.assertRaises(BoardGap):
            judgebrief.brief(got["board_dir"], got["board_dir"].parent.parent / "repo")


class NoForgeCase(LineBase):
    """forge（PR を持つホスト）の無い run（canary の run 5318f732: origin がローカルの bare リポジトリ）。並行 PR の節は機械が
    条件外にし、任せ先の役（blk-pr）を起こさない。素材は not_applicable（reason は no_forge: <種類>）で、判定の問いの台帳に
    人待ちの問いが立たず、結末は並行 PR のせいで round_limit にならない"""

    AWAITING = {"material": {"status": "awaiting_human", "reason": "origin がローカルのパスで owner/repo を導けない"},
                "repo": "", "listed": 0, "truncated": False, "conflicts": [], "excluded": []}

    def run_origin(self, top, url):
        """origin を url にした種（None なら remote 無し）で線を top の下で回す。役が呼ばれたら awaiting_human を返す見本を渡す
        （前の版は役に決めさせ、run 5318f732 の役は awaiting_human と書いた）"""
        run = linekit.LineRun(top, replies={**replies(), "pr-check": self.AWAITING}, edits={"fix": fix_tree},
                              gates={"policy-gate": {"decision": "continue", "text": "clamp の上限は hi でよい"}})
        if url is not None:
            linekit.git(run.repo, "remote", "add", "origin", url(top) if callable(url) else url)
        return run.run()

    def test_no_forge_kinds_settle_parallel_pr_without_the_role(self):
        for kind, url in (("no_remote", None), ("local_path", lambda t: str(t / "origin.git")),
                          ("other_host", "https://gitlab.com/o/r.git")):
            with self.subTest(kind):
                got = self.run_origin(self.tmp / kind, url)
                self.assertNotIn("pr-checking", got["trail"])
                self.assertIs(got["out"]["start"]["pr_go"], False)
                b = entry.open_board(got["board_dir"], allow_halted=True)
                m = b.record["materials"]["parallel_pr"]
                self.assertEqual(m["status"], "not_applicable", m)
                self.assertTrue(m["reason"].startswith(f"no_forge: {kind}"), m)
                self.assertEqual(b.loop_state["forge"]["kind"], kind)
                self.assertNotIn("parallel_pr", [q.get("origin") for q in b.record["questions"]])
                self.assertEqual(got["outcome"], "fixed", pathlib.Path(got["report"]["report_file"]).read_text(encoding="utf-8"))
                text = pathlib.Path(got["report"]["report_file"]).read_text(encoding="utf-8")
                self.assertEqual(sum(1 for ln in text.splitlines() if f"no_forge: {kind}" in ln and "PR を持つホスト" in ln), 1,
                                 text)


# run 27（2026-09-27）の事実: 並行 PR の検査が対象を解決できず、素材 parallel_pr が awaiting_human のまま判定に届いた。判定の
# 指示書は awaiting を使うなと言い、ブロックの受け付け（記憶の中の空の記録）は通し、盤面（本線と同じ judge_output）だけが
# 「awaiting_human なのに台帳に kind=awaiting で無い」と拒んで、境の節 h-plan が run を止めた。今は forge の無い origin の
# 並行 PR は機械が条件外にする（NoForgeCase）ので、awaiting_human は GitHub の remote で確かめられなかった時の形で見る
PR_AWAITING = {**linekit.reply("pr_no_conflicts"), "material": {
    "status": "awaiting_human",
    "reason": "gh pr diff -R o/r が未ログインで落ち、交差した PR #7 の hunk を読めない（確かめられなかった）"}}
AWAITING_Q = {"key": "parallel_pr: 並行 PR の衝突を確かめられない", "kind": "awaiting", "status": "held",
              "reason": "交差した PR #7 の hunk を gh で読めない。人が並行の PR とのぶつかりを確かめる",
              "origin": "parallel_pr"}


def judge_awaiting():
    return {**linekit.reply("judge_ok"), "questions": [AWAITING_Q]}


class JudgeAwaitingCase(LineBase):
    """素材が awaiting_human の盤面で、判定役の指示書・受け付けが本線（p2.diagnose の問いの台帳の決まりと judge_output）と
    同じことを言う（run 27 の再発防止）"""

    def run_awaiting(self, judge):
        return self.run_line(replies={**replies(), "pr-check": PR_AWAITING, "judge": judge}, github=True)

    def test_brief_renders_mainline_question_ledger(self):
        """判定の材料に本線の問いの台帳の決まりが描かれる: awaiting_human の素材に awaiting を必ず載せる文と、検証器の表から
        描いた kind の全部（awaiting・premise・unverifiable を含む）。穴は残らない"""
        got = self.run_awaiting(judge_awaiting())
        text = pathlib.Path(got["judge_brief"]["materials_file"]).read_text(encoding="utf-8")
        for needle in ("素材が awaiting_human なら awaiting を必ず載せろ", "awaiting（origin は素材名",
                       "premise（origin は R1〜R4", "unverifiable（origin は R1〜R4", "parallel_pr", "awaiting_human"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        self.assertNotIn("{{", text)

    def test_awaiting_reply_is_accepted_and_bridge_takes_it(self):
        """kind=awaiting で parallel_pr を載せた判定は、ブロックの受け付けが盤面へ渡して通り、h-plan は止めない"""
        got = self.run_awaiting(judge_awaiting())
        self.assertEqual([t["ok"] for t in got["judge_takes"]], [True])
        self.assertIs(got["out"]["judging"]["ok"], True)
        self.assertIs(got["out"]["h-plan"]["stop"], False, got["out"]["h-plan"])
        b = entry.open_board(got["board_dir"], allow_halted=True)
        self.assertNotEqual((b.state.get("stop") or {}).get("by"), line_edge.JUDGE_BRIDGE_BY)
        self.assertIn(("awaiting", "parallel_pr"), [(q["kind"], q.get("origin")) for q in b.record["questions"]])
        self.assertIn("planning", got["trail"])

    def test_requester_answer_closes_awaiting_without_asking(self):
        """依頼の answers が素材の名 parallel_pr で答えると、判定の awaiting の問いは台帳に残ったまま、報告は依頼者の答えとして並べ、
        保留に数えない（依頼のファイル → start → 盤面 → 判定 → 報告の本物の道）"""
        rows = json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
        ans = [{"question": "parallel_pr", "text": "並行する PR は無い（依頼者が GitHub の一覧で確かめた）"}]
        got = self.run_line(replies={**replies(), "pr-check": PR_AWAITING, "judge": judge_awaiting()},
                            request={"findings": rows, "answers": ans}, github=True)
        text = pathlib.Path(got["report"]["report_file"]).read_text(encoding="utf-8")
        self.assertIn("依頼者の答え: 並行する PR は無い", text)
        self.assertNotIn("保留にしたままの問い", text)
        b = entry.open_board(got["board_dir"], allow_halted=True)
        self.assertIn(("awaiting", "parallel_pr"), [(q["kind"], q.get("origin")) for q in b.record["questions"]],
                      "台帳の行は残る（写しの検証器は変えない）")

    def test_reply_without_awaiting_goes_back_to_judge(self):
        """awaiting の無い判定（run 27 の返答の形）は受け付けが拒んで判定役へ返す（理由はファイルで。R44）——線は止めない。
        直した 2 回目は通る"""
        got = self.run_awaiting([linekit.reply("judge_ok"), judge_awaiting()])
        first, second = got["judge_takes"]
        self.assertEqual((first["ok"], first["done"]), (False, False))
        why = pathlib.Path(first["reason_file"]).read_text(encoding="utf-8")
        self.assertIn("素材 'parallel_pr' が awaiting_human なのに台帳に kind=awaiting で無い", why)
        self.assertIs(second["ok"], True)
        self.assertIs(got["out"]["h-plan"]["stop"], False, got["out"]["h-plan"])
        self.assertIn("planning", got["trail"])

    def test_judge_gives_up_without_failing_the_run(self):
        """3 回とも awaiting を欠けば、輪は done で抜け（max_iterations に当てない。R50）、出口が最後の拒否の文で盤面を止めて
        ok false。h-plan は止まった盤面を見て止める（判定の渡し替えで止めるのではない）"""
        got = self.run_awaiting(linekit.reply("judge_ok"))
        takes = got["judge_takes"]
        self.assertEqual([(t["ok"], t["done"]) for t in takes], [(False, False), (False, False), (False, True)])
        self.assertIs(got["out"]["judging"]["ok"], False)
        self.assertIs(got["out"]["h-plan"]["stop"], True)
        b = entry.open_board(got["board_dir"], allow_halted=True)
        stop = b.state.get("stop") or {}
        self.assertEqual(stop.get("by"), "works:judge", stop)
        self.assertIn("3 回とも", stop.get("reason", ""))
        self.assertIn("kind=awaiting", stop.get("reason", ""))
        self.assertNotIn("planning", got["trail"])


# 手直しの後に最後のテストへ届く道（run 28: 修正役の異議の後に p2.rejudge を回す節がラインに無く、手直しを 2 回した後の h-tests が
# go False になって最後のテストが走らず、周が締まらずに record_invalid で独立の目も飛んだ）
DELTA_FACE2 = "clamp の docstring が境の値の扱いを書いていない"
TEST_CMD = "python3 -m unittest test_stats"
OBJECTION = "判定の clamp の単位は上限の意味の読みが違う（人の関所の答えは hi を返す形）"
NOT_RUN = "最後のテスト: 走っていない"


def refix_tree(repo):
    """手直し役の代わり: 種の docstring の clamp の行を、直した後の振る舞い（上限を超えたら hi）に合わせる"""
    p = repo / "stats.py"
    p.write_text(p.read_text(encoding="utf-8").replace("- clamp: 上限を超えたときに lo を返している（正しくは hi）。",
                                                       "- clamp: 上限を超えたときに hi を返す。"), encoding="utf-8")


DELTA_FIX_FIXED = {"handled": [{"key": DELTA_FACE, "handled": "fixed", "files": ["stats.py"],
                                "how": "docstring の clamp の行を、直した後の振る舞い（上限を超えたら hi を返す）に書き直した"}]}
REVIEW2_FACES = {"faces": [{"key": DELTA_FACE2, "kind": "contract_drift", "where": "stats.py", "cite": "上限を超えたときに hi を返す",
                            "why": "docstring は上限の枝だけを書き、x が lo か hi に等しい境の値をそのまま返す約束が読む側に見えない"}],
                 "checks": [{"key": DELTA_FACE, "closed": True, "why": "docstring の clamp の行が hi を返す形になり、振る舞いと揃った"}]}
REFIX2_DECLARED = {"handled": [{"key": DELTA_FACE2, "handled": "declared",
                                "how": "境の値は本体が x をそのまま返し、2 つの枝の約束の外側で自明なので書き足さない"}]}
CLEAN_DELTA_REVIEW = {"faces": [], "faces_none": "stats.py の差分 2 行（mean の分母・clamp の上限の戻り値）と test_stats.py を読んだ。"
                                               "写し・入口・宣言とのずれは無い",
                      "checks": [{"key": FACE, "closed": True, "why": "clamp の上限の枝が hi を返す形になり、人の答えどおり"}],
                      "compliance": REVIEW_COMPLIANCE,
                      "quality": {"verdict": "pass", "why": "差分は mean の分母と clamp の上限の枝を直すだけで、faces に挙げる穴は無い"}}


class RefixToTestsCase(LineBase):
    """手直しの後（1 回・2 回・手直しなし・判定への異議の再審つき）に h-tests が go True になり、最後のテスト（blk-tests の final）が
    ラインの test_cmd で走り、周が締まって最後の関所・独立の目・報告まで届く。報告に「最後のテスト: 走っていない」が出ない"""

    def run_line(self, **kw):
        # 種の単位は小さく test_cmd も在るので、自動の深さでは軽量（差分の審査と独立の目を省く）になる。ここは標準の道
        # （手直しと目まで全部回る今の振る舞い）を見るので、深さを標準に固定する（計画 2026-10-06-variable-depth）
        kw["inputs"] = {"thickness": "標準", **(kw.get("inputs") or {})}
        return super().run_line(**kw)

    def reached_tests(self, got):
        rep_text = pathlib.Path(got["report"]["report_file"]).read_text(encoding="utf-8")
        self.order_ok(got["trail"])
        self.assertIs(got["out"]["h-tests"]["go"], True, got["out"]["h-tests"])
        for nid in ("testing", "h-final", "final-gate", "h-eyes", "eyeing", "report", "reporting", "result"):
            self.assertIn(nid, got["trail"])
        self.assertEqual(got["out"]["testing"]["by"], "engine")
        self.assertIs(got["report"]["tests_green"], True)
        self.assertEqual(got["outcome"], "fixed", rep_text)
        self.assertNotIn(NOT_RUN, rep_text)
        self.assertNotIn(NOT_RUN, pathlib.Path(got["out"]["report"]["report_file"]).read_text(encoding="utf-8"))
        self.assertTrue(got["eyes_roles"])
        b = entry.open_board(got["board_dir"], allow_halted=True)
        self.assertEqual(b.node_state("p4.ci"), "done")
        self.assertEqual(b.state["works"]["after_round"]["by"], "stop_after_round")
        self.assertTrue(any((got["board_dir"] / "rounds").glob("round-*.json")))
        # blk-tests の final はラインの test_cmd（start の出口）を受けて走る。種は宣言を持つので engine は宣言の段を走らせる
        self.assertEqual(got["out"]["start"]["test_cmd"], TEST_CMD)
        self.assertIn("test_stats", pathlib.Path(got["out"]["testing"]["log"]).read_text(encoding="utf-8"))
        return b

    def two_rounds(self, **extra):
        r = replies()
        r.update(refix=DELTA_FIX_FIXED, review2=REVIEW2_FACES, refix2=REFIX2_DECLARED, **extra)
        return r

    def test_run28_objection_then_two_refix_rounds(self):
        """run 28 の形: 修正の返答に判定への異議 → h-rejudge が再審を回す（判定役の会話の続き）→ 差分の審査 → 手直し →
        2 回目の審査 → 2 回目の手直し → h-tests go True → 最後のテスト → 独立の目 → 最後の関所 → 報告 fixed"""
        r = self.two_rounds()
        r["fix"] = {**r["fix"], "rejudge_requested": OBJECTION}
        got = self.run_line(replies=r, edits={"fix": fix_tree, "refix": refix_tree}, inputs={"test_cmd": TEST_CMD},
                            sessions=True)
        ids = got["trail"]
        self.assertEqual(ids[ids.index("fixing"):ids.index("h-mid") + 1],
                         ["fixing", "h-replan", "h-regate", "h-refit", "h-rejudge", "rejudging", "h-mid"])   # 案の直しは無い周
        self.assertIs(got["out"]["h-rejudge"]["go"], True)
        self.assertEqual((got["out"]["rejudging"]["ok"], got["out"]["rejudging"]["passes"]), (True, 1), got["out"]["rejudging"])
        b = self.reached_tests(got)
        for nid in ("p2.rejudge", "p3.delta_review", "p3.delta_fix", "p3.delta_review2", "p3.delta_fix2"):
            self.assertEqual(b.node_state(nid), "done", nid)
        self.assertEqual(len(b.record["process"]["rejudge"]), 1)

    def test_two_refix_rounds_reach_tests(self):
        """異議なし・手直し 2 回 → 再審は回らず（h-rejudge go False）、最後のテストが走って fixed"""
        got = self.run_line(replies=self.two_rounds(), edits={"fix": fix_tree, "refix": refix_tree},
                            inputs={"test_cmd": TEST_CMD})
        self.assertNotIn("rejudging", got["trail"])
        b = self.reached_tests(got)
        self.assertEqual(b.node_state("p3.delta_fix2"), "done")

    def test_one_refix_round_reaches_tests(self):
        """手直し 1 回（残す理由の申告だけ。2 回目の審査は条件で na）→ 最後のテストが走って fixed"""
        got = self.run_line(inputs={"test_cmd": TEST_CMD})
        b = self.reached_tests(got)
        self.assertEqual((b.node_state("p3.delta_fix"), b.node_state("p3.delta_review2")), ("done", "na"))

    def test_refix_skipped_reaches_tests(self):
        """差分の審査に穴が無い → 手直しは飛び（h-refix go False）、最後のテストが走って fixed"""
        r = replies()
        r["review"] = CLEAN_DELTA_REVIEW
        got = self.run_line(replies=r, inputs={"test_cmd": TEST_CMD})
        self.assertNotIn("refixing", got["trail"])
        b = self.reached_tests(got)
        self.assertEqual(b.node_state("p3.delta_fix"), "na")

    def test_objection_without_session_stops(self):
        """異議あり・判定役の会話が無い（包みを通らない run）→ h-rejudge が役を起こさずに盤面を止め（by works:rejudge-session）、
        後ろのブロックは飛び、報告は stopped_by_line（record_invalid にならない）。次の依頼の下書きに異議の文"""
        import rejudge
        r = replies()
        r["fix"] = {**r["fix"], "rejudge_requested": OBJECTION}
        got = self.run_line(replies=r, inputs={"test_cmd": TEST_CMD})
        self.assertIs(got["out"]["h-rejudge"]["stop"], True)
        for nid in ("rejudging", "reviewing", "refixing", "testing", "eyeing"):
            self.assertNotIn(nid, got["trail"])
        self.assertEqual(got["outcome"], "stopped_by_line")
        self.assertEqual(self.state(got)["stop"]["by"], rejudge.STOP_BY_SESSION)
        self.assertIn(OBJECTION, pathlib.Path(got["report"]["next_request_file"]).read_text(encoding="utf-8"))


# 事前審査の壁打ち（依頼 231）の見本: 見本の後退の穴の key（F13）と、人に聞く語でない kind の block の穴（関所を開ける理由が
# 壁打ちの止まりだけになる）
BLOCK_KEY = linekit.reply("plan_review_regression")["faces"][0]["key"]
USE_SH_STOP = "無人の run（WORKS_USE_UNATTENDED=1）: 人が決める関所に着いたので止めて報告へ"   # dev/use.sh が無人の run の関所に返す一言


def drift_review(key: str, resolved=()) -> dict:
    """key の契約のずれ（contract_drift）の穴を block で挙げる事前審査の返答。resolved は前の往復の block のうち消えたと言う key"""
    sample = linekit.reply("plan_review_regression")
    face = {**sample["faces"][0], "key": key, "kind": "contract_drift",
            "why": f"{key}: 案の直し方が clamp の呼び手との約束を黙って変える"}
    out = {**sample, "faces": [face]}
    return {**out, converge.RESOLVED: list(resolved)} if resolved else out


class ConvergeLineCase(LineBase):
    """事前審査の壁打ち（依頼 231）を線で通す: 184i の型（2 往復目に block が消えて直しへ）・止まる型（同じ block が続く・
    柵の往復でも消えない → 修正前の関所が修正に進まない行で開く）・無人の run（止まって報告へ）"""

    def record(self, got) -> dict:
        return converge.read(entry.open_board(got["board_dir"], allow_halted=True))

    def report_text(self, got) -> str:
        return pathlib.Path(got["report"]["machine_report_file"]).read_text(encoding="utf-8")

    def test_block_fixed_on_second_pass_goes_to_fix(self):
        """184i の型: 1 往復目に block、直しの役（既定の見本は disputed の答え）、2 往復目の審査が resolved → 関所を開かずに直しへ"""
        r = clean_replies()
        r["plan-review"] = [linekit.reply("plan_review_regression"), {**CLEAN_REVIEW, converge.RESOLVED: [BLOCK_KEY]}]
        got = self.run_line(replies=r)
        self.order_ok(got["trail"])
        self.assertNotIn("policy-gate", got["trail"])
        self.assertIn("fixing", got["trail"])
        doc = self.record(got)
        self.assertEqual(doc["outcome"], converge.CLEAN)
        self.assertEqual([p["outcome"] for p in doc["passes"]], [converge.AGAIN, converge.CLEAN])
        self.assertEqual([(a["key"], a["handled"]) for a in doc["passes"][1]["answers"]], [(BLOCK_KEY, "disputed")])
        self.assertEqual(got["outcome"], "fixed", self.report_text(got))

    def test_same_block_stops_at_policy_gate_then_report(self):
        """同じ block が 2 往復続く → 修正前の関所が修正に進まない行（理由つき）で開き、stop なら修正から後を飛ばして報告へ。
        報告の冒頭 1 に壁打ちの頭の行（抜け方 persisted）"""
        got = self.run_line(gates={"policy-gate": {"decision": "stop", "text": "設計を見直す"}})
        self.order_ok(got["trail"])
        self.assertIn(gatemarks.STUCK_ITEM + "。理由: ", got["out"]["h-gate"]["gate_text"])
        for nid in ("fixing", "reviewing", "testing", "final-gate"):
            self.assertNotIn(nid, got["trail"])
        self.assertEqual(got["outcome"], "stopped_by_human")
        doc = self.record(got)
        self.assertEqual([p["outcome"] for p in doc["passes"]], [converge.AGAIN, converge.PERSISTED])
        b = entry.open_board(got["board_dir"], allow_halted=True)
        head = converge.lines(b)[0]
        self.assertIn("（記録の名 persisted）", head)
        self.assertIn(head, self.report_text(got))

    def test_same_block_continue_goes_to_fix(self):
        """同じ block が続いた案に関所で continue → 直しへ進み（関所は 1 度）、修正役は残った block を plan_faces で受ける"""
        got = self.run_line(gates={"policy-gate": {"decision": "continue", "text": ""}})
        self.order_ok(got["trail"])
        self.assertIn(gatemarks.STUCK_ITEM + "。理由: ", got["out"]["h-gate"]["gate_text"])
        self.assertEqual(got["trail"].count("policy-gate"), 1)
        self.assertIn("fixing", got["trail"])
        b = entry.open_board(got["board_dir"], allow_halted=True)
        review = b.output_of_round("p2.plan_review", 1)
        self.assertEqual([(f["key"], f["severity"]) for f in review["faces"]], [(BLOCK_KEY, "block")])
        fix = b.output_of_round("p3.fix", 1)
        self.assertEqual([f["key"] for f in fix["plan_faces"]], [BLOCK_KEY])
        self.assertEqual(got["outcome"], "fixed", self.report_text(got))

    def test_unattended_same_block_stops(self):
        """無人の run（unattended=true）で同じ block が続く → 関所に修正に進まない行が載り、無人の殻（use.sh）の stop で直しへ
        進まずに報告へ（依頼 231 で変わった振る舞い: 前は block が残っても直しへ進んだ）。穴は人に聞く語でない kind なので、
        関所を開ける理由は壁打ちの止まりだけ"""
        r = replies()
        r["plan-review"] = drift_review("契約のずれ: clamp の上限")
        got = self.run_line(replies=r, inputs={"unattended": "true"},
                            gates={"policy-gate": {"decision": "stop", "text": USE_SH_STOP}})
        self.assertIs(got["out"]["h-gate"]["ask"], True)
        self.assertIn(gatemarks.STUCK_ITEM + "。理由: ", got["out"]["h-gate"]["gate_text"])
        for nid in ("fixing", "reviewing", "testing", "final-gate"):
            self.assertNotIn(nid, got["trail"])
        self.assertEqual(got["outcome"], "stopped_by_human")
        self.assertEqual(self.record(got)["outcome"], converge.PERSISTED)

    def test_new_blocks_each_pass_unsettled_at_fence(self):
        """往復ごとに別の key の block（前の block は resolved）→ 柵の 3 往復で unsettled。関所の行の理由は UNSETTLED_WHY の頭"""
        keys = ["契約のずれ: 1 往復目の穴", "契約のずれ: 2 往復目の穴", "契約のずれ: 3 往復目の穴"]
        r = replies()
        r["plan-review"] = [drift_review(k, resolved=keys[:i]) for i, k in enumerate(keys)]
        got = self.run_line(replies=r, gates={"policy-gate": {"decision": "stop", "text": "設計を見直す"}})
        doc = self.record(got)
        self.assertEqual([p["outcome"] for p in doc["passes"]], [converge.AGAIN, converge.AGAIN, converge.UNSETTLED])
        why = converge.UNSETTLED_WHY.split("（往復ごとに")[0].format(n=3)
        self.assertIn(f"{gatemarks.STUCK_ITEM}。理由: {why}", got["out"]["h-gate"]["gate_text"])
        self.assertNotIn("設計だけの run", got["out"]["h-gate"]["gate_text"])   # 普通の run に設計だけの語を出さない（f2）
        self.assertNotIn("fixing", got["trail"])
        self.assertEqual(got["outcome"], "stopped_by_human")


def fix_only_replies():
    """修正から後ろの役の返答だけ（判定・修正案・事前審査の返答を持たない。起こせば KeyError で落ちる）"""
    return {k: v for k, v in clean_replies().items() if k not in ("judge", "plan", "plan-review")}


class FixtureLineCase(LineBase):
    """固定材料（計画 220 Task 5）: 1 回目の線の h-fix が盤面を写し、2 回目の線が入力 fix_fixture で同じ所から始める"""

    def test_fixture_run_starts_at_fix(self):
        """1 回目の線の h-fix が固定材料を写し、2 回目の線（fix_fixture・fix_shape=af）は判定・修正案の役を起こさずに修正へ進む"""
        import fixture
        first = linekit.run_line(self.tmp / "one", replies=clean_replies(), edits={"fix": fix_tree})
        src = first["board_dir"].parent / fixture.DIR
        self.assertTrue((src / fixture.MANIFEST).is_file(), first["trail"])
        second = linekit.run_line(self.tmp / "two", replies=fix_only_replies(), edits={"fix": fix_tree},
                                  inputs={"fix_fixture": str(src), "fix_shape": "af"})
        self.order_ok(second["trail"])
        for nid in ("judging", "planning", "premising", "purposing", "gathering"):
            self.assertNotIn(nid, second["trail"])
        self.assertIn("fixing", second["trail"])
        self.assertEqual(second["out"]["start"]["fix_shape"], "af")
        self.assertFalse((second["board_dir"].parent / fixture.DIR).exists(), "固定材料から始めた run は写し直さない")
        self.assertEqual(second["outcome"], first["outcome"],
                         pathlib.Path(second["report"]["report_file"]).read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
