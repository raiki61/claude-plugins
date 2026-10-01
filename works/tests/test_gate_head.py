"""人が読む関所の文と報告の冒頭 3 行（.shared/core/gatemarks.py の head3・gate_text・pushes）の検査（FAST: 盤面・git・子のプロセスなし）。

- 直す前の関所（plan.gate_text）と仕様の関所（specblk.gate_text）は同じ組み立てで、1〜3 行目が 起きたこと・決めてほしいこと・推し
- 最後の関所の冒頭（line_edge._final_head）は開けた理由を 1 行目に並べ、守りのファイルはそこで名指す
- 報告の冒頭（report.head3）は結末を平易に言い、人が決める物が無ければ 2 行目に次の run に渡す物の件数
- 推しは判定の役が問いの理由に書いた物だけ（機械は作らない）。3 行を足しても今の中身は 1 つも落ちない
偽の盤面は test_plan_gate の GateBase（写しの RL を差し替えて読む）を借りる。盤面を組む実物の検査は test_edge・test_report（HEAVY）
"""
import importlib.util
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(ROOT / "tests"))
import answer  # noqa: E402
import gatemarks  # noqa: E402
import line_edge  # noqa: E402
import plan  # noqa: E402
import report  # noqa: E402
from test_plan_gate import FORK, GateBase, internal_subjects  # noqa: E402

HEADS = [gatemarks.HAPPENED, gatemarks.DECIDE, gatemarks.PUSH]
NARROW_ITEM = "修正案 1 が狭める能力: 空の列の mean——0 割りの例外のまま"


def spec_lib():
    spec = importlib.util.spec_from_file_location("_gate_head_spec_lib", ROOT / "blk-spec" / "lib" / "specblk.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def heads(text: str) -> list:
    return [next((h for h in HEADS if x.startswith(h)), x) for x in text.splitlines()[:3]]


class AskGateCase(unittest.TestCase):
    def asking(self, items, kinds=("regression",)):
        return {"node": "p2.human_gate", "kinds": list(kinds), "question": "狭まる能力を代償に採るか", "items": list(items)}

    def test_plan_gate_starts_with_three_lines(self):
        text = plan.gate_text(self.asking([NARROW_ITEM]), run_id="run-1")
        self.assertEqual(heads(text), HEADS)
        first = text.splitlines()[0]
        self.assertIn("直す前の関所", first)
        self.assertIn("1 件", first)
        self.assertEqual(internal_subjects("\n".join(text.splitlines()[:3])), [])

    def test_nothing_is_dropped_behind_the_head(self):
        """3 行の後ろに問いの文・項目・両方の答えの行が残る（依頼 4: 情報を 1 つも減らさない）"""
        text = plan.gate_text(self.asking([NARROW_ITEM]), run_id="run-1")
        rest = "\n".join(text.splitlines()[3:])
        for want in ("> 狭まる能力を代償に採るか", f"- {NARROW_ITEM}", answer.line("run-1", "continue", "<通す範囲と条件>"),
                     answer.line("run-1", "stop", "<理由>"), "記録の名 process.human_items"):
            self.assertIn(want, rest)

    def test_push_comes_only_from_the_record(self):
        """推しは項目（判定の問いの理由）に書かれた物だけ。無ければ NO_PUSH、推しの無い項目が混じればそう断る"""
        none = plan.gate_text(self.asking([NARROW_ITEM]), run_id="run-1").splitlines()[2]
        self.assertEqual(none, gatemarks.PUSH + gatemarks.NO_PUSH)
        ask = gatemarks.ask_text(FORK)
        only = plan.gate_text(self.asking([ask], kinds=("fork",)), run_id="run-1").splitlines()[2]
        self.assertEqual(only, gatemarks.PUSH + "例外——呼び手が既に例外を捕まえている")
        mixed = plan.gate_text(self.asking([ask, NARROW_ITEM], kinds=("fork", "regression")), run_id="run-1").splitlines()[2]
        self.assertTrue(mixed.startswith(only), mixed)
        self.assertIn(gatemarks.NO_PUSH, mixed)
        unsaid = gatemarks.ask_text({**FORK, "reason": "空の列の意味が 2 つに割れる"})
        self.assertEqual(gatemarks.pushes([unsaid]), gatemarks.NO_PUSH, "ask_text の断りの句を推しと読まない")

    def test_spec_gate_is_the_same_assembly(self):
        """仕様の関所は写しを持たず、同じ組み立てに仕様の承認の節と記録の名を渡すだけ"""
        asking = {"node": "spec.approve", "kinds": ["declared"], "question": "承認するか", "items": ["A1"]}
        text = spec_lib().gate_text(asking, run_id="run-x")
        self.assertEqual(text, gatemarks.gate_text(asking, run_id="run-x", node="spec.approve",
                                                   record_name="process.spec.approval"))
        self.assertEqual(heads(text), HEADS)
        self.assertIn("仕様の承認の関所", text.splitlines()[0])


class FinalHeadCase(GateBase):
    def head(self, b, *, head="緑", rows=(), err="", asks=(), eyes=((), []), mismatched=()):
        why = line_edge._final_needs(b, head, "", eyes, list(rows), err, list(asks), list(mismatched))
        return line_edge._final_head(b, head, why, bool(rows) or bool(err))

    def test_three_lines_and_reasons(self):
        _, b = self.gate()
        got = self.head(b, head="赤", asks=["単位 A"], eyes=([], ["R3"]))
        self.assertEqual(heads("\n".join(got)), HEADS)
        for want in ("テストは赤", "食い違いの申し出を人に回した（1 件）", "独立の目が阻害を返した（R3）"):
            self.assertIn(want, got[0])
        self.assertEqual(got[2], gatemarks.PUSH + gatemarks.NO_PUSH)
        self.assertEqual(internal_subjects("\n".join(got)), [])

    def test_protected_named_in_the_first_line(self):
        _, b = self.gate()
        got = self.head(b, rows=[{"path": "works/tests/test_edge.py"}])
        self.assertIn(line_edge.PROTECTED_HEAD, got[0])
        self.assertIn("人の確かめが要る", got[0])
        self.assertIn("守りのファイル", got[1])
        self.assertIn(line_edge.PROTECTED_UNKNOWN, self.head(b, err="一覧が読めない")[0])
        self.assertNotIn("守りのファイル", self.head(b)[0] + self.head(b)[1])

    def test_final_edge_puts_the_head_before_the_sections(self):
        """final_edge の文: 冒頭 3 行 → 空行 → 守りのファイルの節（最初の見出し）→ 今の本文。盤面の読み口は偽物に差し替える"""
        _, b = self.gate()
        row = {"path": "works/tests/test_edge.py", "added": 1, "deleted": 0, "id": "edge-test", "about": "試験"}
        with mock.patch.object(line_edge, "_tests_head", return_value="緑"), \
                mock.patch.object(line_edge, "_eyes", return_value=([], [])), \
                mock.patch.object(line_edge.rejudge, "unsettled", return_value={"settled": True, "text": ""}), \
                mock.patch.object(line_edge, "_guard", return_value=([row], "abc", "", [])), \
                mock.patch.object(line_edge.protect, "lines", return_value=["works/tests/test_edge.py（+1 −0）"]), \
                mock.patch.object(line_edge.querytest, "closure_lines", return_value=[]), \
                mock.patch.object(line_edge.querytest, "unproven_lines", return_value=[]), \
                mock.patch.object(line_edge, "_final_text", return_value="本文\n"), \
                mock.patch.object(line_edge, "_write_text"):
            text = line_edge.final_edge(b, self.tmp, run_id="run-1", mode="when_needed", tests={})["gate_text"]
        lines = text.splitlines()
        self.assertEqual(heads(text), HEADS)
        self.assertEqual(lines[3], "")
        self.assertTrue(lines[4].startswith("## " + line_edge.PROTECTED_HEAD), lines[4])
        self.assertTrue(text.endswith("本文\n"))

    def test_when_needed_opens_on_the_same_reasons_as_the_first_line(self):
        """when_needed で開くかと 1 行目の開けた理由は同じ 1 つの列（_final_needs）: 列が空なら開かず、在れば全部が 1 行目に載る"""
        _, b = self.gate()

        def final(why):
            with mock.patch.object(line_edge, "_final_needs", return_value=why), \
                    mock.patch.object(line_edge, "_tests_head", return_value="緑"), \
                    mock.patch.object(line_edge, "_eyes", return_value=([], [])), \
                    mock.patch.object(line_edge.rejudge, "unsettled", return_value={"settled": True, "text": ""}), \
                    mock.patch.object(line_edge, "_guard", return_value=([], "", "", [])), \
                    mock.patch.object(line_edge.querytest, "closure_lines", return_value=[]), \
                    mock.patch.object(line_edge.querytest, "unproven_lines", return_value=[]), \
                    mock.patch.object(line_edge, "_final_text", return_value="本文\n"), \
                    mock.patch.object(line_edge, "_write_text"):
                return line_edge.final_edge(b, self.tmp, run_id="run-1", mode="when_needed", tests={})

        self.assertEqual(final([]), {})
        first = final(["理由 甲", "理由 乙"])["gate_text"].splitlines()[0]
        self.assertIn("開けた理由: 理由 甲・理由 乙", first)

    def test_held_questions_shown_but_not_a_reason(self):
        """保留にしたままの問いは 1 行目に出るが、開けた理由には数えない（when_needed で関所を開けない）"""
        _, b = self.gate(questions=[FORK])
        self.assertEqual(line_edge._final_needs(b, "緑", "", ([], []), [], "", [], []), [])
        first = self.head(b)[0]
        self.assertIn("保留にしたままの問いも在る（1 件。関所を開ける理由には数えない）", first)
        self.assertNotIn("開けた理由: ", first)

    def test_push_from_held_questions(self):
        _, b = self.gate(questions=[FORK])
        self.assertEqual(self.head(b)[2], gatemarks.PUSH + "例外——呼び手が既に例外を捕まえている")


class ReportHeadCase(GateBase):
    def head(self, b, outcome, **kw):
        with mock.patch.object(report, "_asked", return_value=[]):
            return report.head3(b, outcome, **kw)

    def test_nothing_to_decide_puts_next_items(self):
        _, b = self.gate()
        got = self.head(b, "fixed", next_items=[{}, {}])
        self.assertEqual(got, [gatemarks.HAPPENED + report.OUTCOME_WORDS["fixed"] + "（fixed）", "次の run に渡す物: 2 件",
                               gatemarks.PUSH + gatemarks.NO_PUSH])

    def test_decisions_are_counted(self):
        _, b = self.gate(questions=[FORK])
        b.state["pending_human"] = {"node": "p2.human_gate", "question": "q", "items": ["項目 A"]}
        got = self.head(b, "round_limit", left=[{"where": "判定", "text": "残り"}])
        self.assertTrue(got[1].startswith(gatemarks.DECIDE + "3 件"), got[1])
        self.assertEqual(got[2], gatemarks.PUSH + "例外——呼び手が既に例外を捕まえている")
        self.assertEqual(internal_subjects("\n".join(got)), [])

    def test_unreturned_unit_is_counted_as_decision(self):
        """関所で答えたが直す義務に戻せなかった単位（unreturned_lines）は、答えた問いと違って人がまだ決める物なので、報告の冒頭と
        最後の関所の冒頭の「保留にしたままの問い」の件数に入れる"""
        got, b = self.gate(questions=[FORK], units=[{"key": "今の周に無い単位", "label": "block"}])
        b.record["process"]["human_items"].append({"round": 1, "kinds": got["ask"]["kinds"], "asked": got["ask"]["items"],
                                                   "answer": "continue", "note": "例外で", "node": "p2.human_gate"})
        self.assertEqual(len(gatemarks.unreturned_lines(b)), 1)
        self.assertEqual(gatemarks.held_lines(b), gatemarks.unreturned_lines(b))
        self.assertIn("保留にしたままの問い 1 件", "\n".join(self.head(b, "fixed")))
        self.assertIn("保留にしたままの問いも在る（1 件", FinalHeadCase.head(self, b)[0])

    def test_every_outcome_has_plain_words(self):
        self.assertEqual(set(report.OUTCOME_WORDS), set(report.OUTCOMES))


if __name__ == "__main__":
    unittest.main()
