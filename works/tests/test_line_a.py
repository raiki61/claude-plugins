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
        self.assertEqual(got["trail"][-1], "report")
        self.assertEqual(got["outcome"], "stopped_by_human")

    def test_final_gate_stop(self):
        """最後の関所の stop → 止めた run にも報告が走り、結末 stopped_by_human。答えは final-gate-answer.json と human_items"""
        got = self.run_line(gates={"final-gate": {"decision": "stop", "text": "差分を人が読み直す"}})
        self.assertEqual(got["trail"][-2:], ["h-eyes", "report"])
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


if __name__ == "__main__":
    unittest.main()
