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

import engine.util as engine_util  # noqa: E402,F401  （linekit が .shared/core を足した後）
import entry  # noqa: E402
import line_edge  # noqa: E402
import linekit  # noqa: E402
from test_edge import CLEAN_REVIEW, DELTA_FIX, DELTA_REVIEW, ODD_NOTE, fix_reply, plan_reply  # noqa: E402


def fix_tree(repo):
    """種の 2 つのバグを作業ツリーで直す（修正役の代わり）"""
    src = (repo / "stats.py").read_text(encoding="utf-8")
    (repo / "stats.py").write_text(src.replace("(len(xs) - 1)", "len(xs)").replace(
        "    if x > hi:\n        return lo", "    if x > hi:\n        return hi"), encoding="utf-8")


def replies(review="plan_review_regression"):
    return {"judge": linekit.reply("judge_ok"), "plan": plan_reply(),
            "plan-review": linekit.reply(review) if isinstance(review, str) else review,
            "fix": fix_reply(faces=review == "plan_review_regression"), "review": DELTA_REVIEW, "refix": DELTA_FIX}


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
        """修正案 → 事前審査（後退の穴）→ policy-gate continue → 修正 → 差分の審査（穴）→ 手直し → 最後のテスト（緑）→
        最後の関所 continue → 報告 fixed。trail は LINE_ORDER の順、報告と次の依頼の下書きが盤面に在る"""
        got = self.run_line(gates={"policy-gate": {"decision": "continue", "text": "clamp の上限は hi でよい"}})
        self.order_ok(got["trail"])
        for nid in ("start", "premising", "judging", "planning", "policy-gate", "fixing", "reviewing", "refixing", "testing",
                    "final-gate", "report"):
            self.assertIn(nid, got["trail"])
        # 種の git は GitHub の remote を持たないので、並行 PR の engine の helper は任せ先に落ちる（blk-pr が回る）
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

    def test_no_fix_path(self):
        """判定が直す物を残さない → 修正案・修正・審査・手直しは飛び、最後のテストは周を締めるので走る。結末 no_fix_needed"""
        r = replies(review=CLEAN_REVIEW)
        r["judge"] = linekit.reply("judge_no_fix")
        got = self.run_line(replies=r, edits={})
        self.order_ok(got["trail"])
        for nid in ("planning", "policy-gate", "fixing", "reviewing", "refixing"):
            self.assertNotIn(nid, got["trail"])
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

    def test_eyes_after_final_gate(self):
        """最後の関所の後に独立の目（R1・R2 の筋）が回り、返答が盤面に在る。周は目の後に締まり、結末 fixed（締めた盤面にも
        報告の節が出て AI の報告が回る。R61 の B）"""
        got = self.run_line()
        self.order_ok(got["trail"])
        t = got["trail"]
        self.assertLess(t.index("final-gate"), t.index("eyeing"))
        self.assertEqual(t[-4:], ["eyeing", "report", "reporting", "result"])
        self.assertEqual(set(got["eyes_roles"]), {"r1-comments", "r1-minimality", "r2-design", "r2-compare"})
        b = entry.open_board(got["board_dir"], allow_halted=True)
        for nid in ("r1.comment_candidates", "r1.minimality", "r2.design", "r2.compare"):
            with self.subTest(nid):
                self.assertIn(nid, b.state["outputs"])
        self.assertEqual(got["out"]["eyeing"]["ok"], True)
        self.assertEqual(got["outcome"], "fixed", pathlib.Path(got["report"]["report_file"]).read_text(encoding="utf-8"))

    def test_final_gate_stop_skips_eyes(self):
        """最後の関所の stop → 目は回らない（周は開いたまま人が止めた）、結末 stopped_by_human"""
        got = self.run_line(gates={"final-gate": {"decision": "stop", "text": "差分を人が読み直す"}})
        self.assertNotIn("eyeing", got["trail"])
        self.assertEqual(got["outcome"], "stopped_by_human")
        st = self.state(got)
        self.assertEqual(st["stop"]["by"], line_edge.FINAL_GATE_BY)

    def test_eyes_asking_goes_to_next_run(self):
        """R4 が方針とのぶつかりを挙げ r4.human_gate が人に聞く → ブロックは止めずに asking で抜け（計画 Task 33 の (b)）、
        報告は needs_human。問いは報告の冒頭 1 と次の run の依頼の下書きに載る"""
        import test_blk_eyes as TB
        r = replies(review=CLEAN_REVIEW)
        r["judge"] = linekit.reply("judge_no_fix")
        conflict = "clamp の上限を変えると方針の「既定値は変えない」とぶつかる"
        r["r4-scope"] = {**TB.SCOPE_OK, "policy_conflicts": [conflict]}
        got = self.run_line(replies=r, edits={})
        self.assertIn("r4-scope", got["eyes_roles"])
        self.assertIs(got["out"]["eyeing"]["asking"], True)
        self.assertEqual(got["outcome"], "needs_human")
        text = pathlib.Path(got["report"]["report_file"]).read_text(encoding="utf-8")
        self.assertIn(conflict, text)
        nxt = json.loads(pathlib.Path(got["report"]["next_request_file"]).read_text(encoding="utf-8"))
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


# run 27（2026-09-27）の事実: 並行 PR の検査が対象を解決できず、素材 parallel_pr が awaiting_human のまま判定に届いた。判定の
# 指示書は awaiting を使うなと言い、ブロックの受け付け（記憶の中の空の記録）は通し、盤面（本線と同じ judge_output）だけが
# 「awaiting_human なのに台帳に kind=awaiting で無い」と拒んで、境の節 h-plan が run を止めた
PR_AWAITING = {**linekit.reply("pr_no_conflicts"), "material": {
    "status": "awaiting_human",
    "reason": "1 段で対象リポジトリを解決できない。枝に upstream が無く、origin はローカルの bare リポジトリ（run 27 と同じ形）"}}
AWAITING_Q = {"key": "parallel_pr: 並行 PR の衝突を確かめられない", "kind": "awaiting", "status": "held",
              "reason": "origin がローカルの bare リポジトリで open な PR を引けない。人が並行の PR の有無を確かめる",
              "origin": "parallel_pr"}


def judge_awaiting():
    return {**linekit.reply("judge_ok"), "questions": [AWAITING_Q]}


class JudgeAwaitingCase(LineBase):
    """素材が awaiting_human の盤面で、判定役の指示書・受け付けが本線（p2.diagnose の問いの台帳の決まりと judge_output）と
    同じことを言う（run 27 の再発防止）"""

    def run_awaiting(self, judge):
        return self.run_line(replies={**replies(), "pr-check": PR_AWAITING, "judge": judge})

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


if __name__ == "__main__":
    unittest.main()
