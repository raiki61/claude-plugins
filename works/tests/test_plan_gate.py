"""修正前の関所（p2.human_gate）が、決め手の在る項目を人に聞かずに通すか。写しの RL を読み、線 A の核の差し替え
（entry.CORE_OVERRIDES）を盤面と同じ口（DiskBoard._apply_overrides）で当て、機械の節 human_gate を偽の盤面で直に呼ぶ（FAST。
盤面・git・子のプロセスなし）。決め手の出どころ decided_by が在り undecided_because が空で柵の印 fences が無い行は通して
state.works.gate_passes に出どころつきで残し、柵の印か undecided_because の在る行・欄の無い行は今までどおり聞く"""
import json
import pathlib
import re
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
import board  # noqa: E402
import conflict  # noqa: E402
import converge  # noqa: E402
import entry  # noqa: E402
import gatemarks  # noqa: E402
import line_edge  # noqa: E402
import report  # noqa: E402
from engine.rules import registry  # noqa: E402

NARROW = {"what": "空の列の mean", "why": "空の列の平均は 0 割りの例外のまま"}
DECIDED = {"decided_by": "依頼の本文: 空の列の mean は今までどおり例外でよい", "undecided_because": "", "fences": []}
FACE = {"key": "clamp の上限の意味が変わる", "unit_keys": ["u"], "kind": "regression", "where": "stats.py clamp",
        "why": "上限を超えた値に lo を返す今の振る舞いに頼る呼び手が在れば結果が変わる", "severity": "block"}


class GateBase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)

    def gate(self, narrows=(), faces=(), questions=(), units=()):
        """差し替えを当てた写しの RL で p2.human_gate を回す。(返り, 偽の盤面)"""
        outs = {"p2.fix_plan": {"plan": [{"unit_keys": ["u"], "narrows": list(narrows)}]},
                "p2.plan_review": {"faces": list(faces)}}
        b = types.SimpleNamespace(
            round=1, dir=self.tmp, loop_state={},
            record={"process": {"human_items": [], "policy": {}}, "questions": list(questions), "units": list(units)},
            # 名指しした方針の文書が無い: 固定した版（無し）から変わっていない
            state={"inputs": {"policy_md": str(self.tmp / "no-policy.md"), "cwd": str(self.tmp)}, "works": {},
                   "validator": str(board.VALIDATOR_PATH), "graph": str(board.GRAPH_PATH)},
            output_of_round=lambda nid, rnd: outs.get(nid), work=lambda name: self.tmp / name)
        holder = types.SimpleNamespace(rules=board.rules_module(), state=b.state)
        board.DiskBoard._apply_overrides(holder, entry.CORE_OVERRIDES)
        b.rules = holder.rules
        return registry(holder.rules, "BUILTINS")["human_gate"](b, "p2.human_gate"), b


class PlanGateCase(GateBase):
    def test_decided_narrow_passes_and_is_recorded(self):
        got, b = self.gate(narrows=[{**NARROW, **DECIDED}])
        self.assertEqual(got, {"ok": True})
        passes = b.state["works"].get("gate_passes") or []
        self.assertEqual([(p["node"], p["by"], p["decided_by"]) for p in passes],
                         [("p2.human_gate", "decided", DECIDED["decided_by"])])
        self.assertIn(NARROW["what"], passes[0]["item"])

    def test_decided_regression_face_passes(self):
        got, b = self.gate(faces=[{**FACE, **DECIDED}])
        self.assertEqual(got, {"ok": True})
        self.assertEqual([p["by"] for p in b.state["works"].get("gate_passes") or []], ["decided"])

    def test_fenced_narrow_asks_even_if_decided(self):
        got, _ = self.gate(narrows=[{**NARROW, **DECIDED, "fences": ["external_write"]}])
        self.assertEqual(got.get("decision"), "ask", got)

    def test_undecided_narrow_asks(self):
        got, _ = self.gate(narrows=[{**NARROW, **DECIDED, "undecided_because": "世界の解が 2 つに割れる"}])
        self.assertEqual(got.get("decision"), "ask", got)

    def test_asked_row_shows_what_the_world_does(self):
        """人に回す行は、役が書いた世界の解の 1 文を項目の尾に載せる（書いていなければそう出す。欄の無い行には付けない）"""
        world = "rjsf と JSON Forms はどちらも見せ方を UI schema に分ける（https://jsonforms.io/faq/）が、置き場は決めていない"
        for mark, tail in (({**DECIDED, "undecided_because": "置き場が割れる", "world": world}, f"（世界の解: {world}）"),
                           ({**DECIDED, "undecided_because": "置き場が割れる"}, "（世界の解: 役が書いていない）")):
            with self.subTest(tail=tail):
                got, _ = self.gate(narrows=[{**NARROW, **mark}])
                self.assertTrue(got["ask"]["items"][0].endswith(tail), got["ask"]["items"])
        got, _ = self.gate(narrows=[dict(NARROW)])
        self.assertNotIn("世界の解", got["ask"]["items"][0])

    def test_mixed_rows_ask_only_the_undecided(self):
        """決め手の在る行と欄の無い行が並べば、欄の無い行だけを聞き、決め手の在る行は項目に出さず記録に残す"""
        got, b = self.gate(narrows=[{**NARROW, **DECIDED}, {"what": "負の上限の clamp", "why": "上限が負の時の結果が変わる"}])
        self.assertEqual(got.get("decision"), "ask", got)
        self.assertEqual(len(got["ask"]["items"]), 1)
        self.assertIn("負の上限の clamp", got["ask"]["items"][0])
        self.assertEqual([p["by"] for p in b.state["works"].get("gate_passes") or []], ["decided"])


FORK_UNIT = "stats.py mean: 空の列の扱いが決まらない"
OTHER_UNIT = "stats.py clamp: 上限を超えた値に lo を返す"
FORK = {"key": "q-empty-mean", "kind": "fork", "status": "held", "origin": FORK_UNIT, "options": ["例外", "0 を返す"],
        "reason": "空の列の意味が 2 つに割れる。推し: 例外——呼び手が既に例外を捕まえている"}
UNITS = [{"key": FORK_UNIT, "label": "block"}, {"key": OTHER_UNIT, "label": "block"}]


class LedgerAsksCase(GateBase):
    """問いの台帳で人に聞く状態の fork・escalate が修正前の関所の項目に載り（無人の run では載せず、修正を飛ばさない）、関所の
    continue でその出どころが直す義務に戻り（一言の「保留: <key>」は戻さない）、最後の関所の文と報告の冒頭が「無い」と書かずに並べる"""

    def answer(self, b, got, note=""):
        """写しの human_gate_answered と同じ形の行を積む"""
        b.record["process"]["human_items"].append({"round": 1, "kinds": got["ask"]["kinds"], "asked": got["ask"]["items"],
                                                   "answer": "continue", "note": note, "node": "p2.human_gate"})

    def owed(self, b):
        return conflict.owed_units_but_asked(b)

    def final_text(self, b):
        b.state["outputs"] = {}
        eyes = line_edge._eyes(b)   # 本物の作り手が作った eyes・rest で組む
        rest = report.rest_outside_validator(b, tests={}, counts=eyes.counts)
        return line_edge._final_text(b, {}, "", eyes, rest, self.tmp, "run-1")

    def head(self, b):
        with mock.patch.object(report, "_stop_info", return_value=("", "", None)), \
                mock.patch.object(report, "_latest", return_value=None), \
                mock.patch.object(report, "_conflict_line", return_value=""), \
                mock.patch.object(report, "_rejudge_changes", return_value=[]), \
                mock.patch.object(report, "_premise_hypotheses", return_value=[]), \
                mock.patch.object(report, "_pr_lines", return_value=[]), \
                mock.patch.object(report.querytest, "unproven_lines", return_value=[]), \
                mock.patch.object(report.querytest, "closure_lines", return_value=[]):
            return "\n".join(report.head_decisions(b, {}, tests=None))

    def test_held_fork_is_asked_with_options_and_recommendation(self):
        got, _ = self.gate(questions=[FORK], units=UNITS)
        self.assertEqual(got.get("decision"), "ask", got)
        self.assertEqual(got["ask"]["kinds"], ["fork"])
        row = got["ask"]["items"][0]
        for needle in (FORK["key"], "例外・0 を返す", "推し: 例外", FORK_UNIT):
            self.assertIn(needle, row)
        text = line_edge.gate_text({"node": "p2.human_gate", **got["ask"]})
        self.assertIn(gatemarks.ASK_GATE_HEAD, text)
        self.assertIn("問いの理由の推しで直す", text)
        self.assertIn("保留: <問いの key>", text)
        self.assertNotIn(gatemarks.ASK_GATE_HEAD, line_edge.gate_text({"node": "p2.human_gate", "kinds": ["regression"],
                                                                  "items": ["x"], "question": "q"}))

    def test_recommendation_missing_is_said(self):
        got, _ = self.gate(questions=[{**FORK, "reason": "空の列の意味が 2 つに割れる"}], units=UNITS)
        self.assertIn("推し: 判定の役が書いていない", got["ask"]["items"][0])

    def test_decided_or_non_fork_held_question_is_not_asked(self):
        for q in ({**FORK, "status": "decided", "resolution": "例外"}, {**FORK, "kind": "field", "origin": None}):
            with self.subTest(q["status"] + q["kind"]):
                got, _ = self.gate(questions=[q], units=UNITS)
                self.assertEqual(got, {"ok": True})

    def test_escalate_is_asked(self):
        got, _ = self.gate(questions=[{**FORK, "kind": "stuck", "status": "escalate"}], units=UNITS)
        self.assertEqual(got["ask"]["kinds"], ["escalate"])

    def test_continue_returns_the_fork_origin_to_the_owed_units(self):
        got, b = self.gate(questions=[FORK], units=UNITS)
        self.assertEqual(self.owed(b), {OTHER_UNIT})
        self.answer(b, got, note="例外で")
        self.assertEqual(self.owed(b), {FORK_UNIT, OTHER_UNIT})
        self.assertIn(FORK_UNIT, "\n".join(gatemarks.returned_lines(b)))
        self.assertEqual(gatemarks.plan_gate_items(b), [])   # 答えた問いは関所に 2 度出さない
        self.assertIn("関所で continue を受けた", self.final_text(b))

    def test_branch_rows_in_final_text_and_head(self):
        """差分の審査の穴と目の行の枝の名札（report.branch_rows。線の木の段 4a）は最後の関所の文と報告の冒頭の両方に出る"""
        _, b = self.gate(questions=[FORK], units=UNITS)
        rows = ["差分の審査の穴の枝: 見本の 1 行", "  - k: 項目 1"]
        with mock.patch.object(report, "branch_rows", return_value=rows):
            for name, text in (("最後の関所", self.final_text(b)), ("報告の冒頭", self.head(b))):
                with self.subTest(name):
                    self.assertIn("差分の審査の穴の枝: 見本の 1 行", text)
                    self.assertIn("  - k: 項目 1", text)

    def test_continue_returns_a_deferred_origin_the_fixer_was_promised(self):
        """開いていない単位（suggest の defer）を出どころに持つ fork に関所で答えると、修正役への約束（returned_lines）に載った
        単位が直す義務（owed_units_but_asked）にも入る。約束と義務の数えが別の集合だと、約束どおり直した返答が拒まれる"""
        units = [{"key": FORK_UNIT, "label": "suggest", "disposition": "defer"}, {"key": OTHER_UNIT, "label": "block"}]
        got, b = self.gate(questions=[FORK], units=units)
        self.answer(b, got, note="例外で")
        self.assertIn(FORK_UNIT, "\n".join(gatemarks.returned_lines(b)))
        self.assertEqual(self.owed(b), {FORK_UNIT, OTHER_UNIT})

    def test_origin_missing_from_the_round_units_is_not_promised(self):
        """今の周の units に無い出どころ（defer の台帳だけに在る key）は、答えても直す義務に戻せないので、修正役に
        「直す義務に戻った」と約束しない"""
        gone = {**FORK, "origin": "stats.py median: 台帳だけに在る単位"}
        got, b = self.gate(questions=[gone], units=UNITS)
        self.answer(b, got, note="例外で")
        self.assertNotIn(gone["origin"], "\n".join(gatemarks.returned_lines(b)))
        self.assertEqual(self.owed(b), {FORK_UNIT, OTHER_UNIT})

    def test_hold_note_keeps_the_fork_origin_exempt(self):
        got, b = self.gate(questions=[FORK], units=UNITS)
        self.answer(b, got, note=f"狭めは通す。保留: {FORK['key']}")
        self.assertEqual(self.owed(b), {OTHER_UNIT})

    def test_hold_note_names_only_the_whole_key(self):
        """「保留: q-empty-mean-2」は key が前方で重なる q-empty-mean を保留にしない"""
        longer = {**FORK, "key": FORK["key"] + "-2", "origin": OTHER_UNIT}
        got, b = self.gate(questions=[FORK, longer], units=UNITS)
        self.answer(b, got, note=f"保留: {longer['key']}。")
        self.assertEqual(self.owed(b), {FORK_UNIT})

    def test_hold_note_lists_several_keys(self):
        """関所の文と同じ「・」「/」で並べた「保留: q-a・q-b」は、並べた問いをどれも保留にする"""
        other = {**FORK, "key": FORK["key"] + "-b", "origin": OTHER_UNIT}
        for sep in ("・", "/", "／", "、", " "):
            with self.subTest(sep=sep):
                got, b = self.gate(questions=[FORK, other], units=UNITS)
                self.answer(b, got, note=f"保留: {FORK['key']}{sep}{other['key']}")
                self.assertEqual(self.owed(b), set())

    def test_hold_note_with_words_after_the_key_keeps_the_fork_origin_exempt(self):
        """「保留: <key>は来週決める」「保留: <key>（来週）」のように key の後ろに言葉が続いても、台帳の key と照らして保留にする"""
        for note in (f"保留: {FORK['key']}は来週決める", f"保留: {FORK['key']}（来週）"):
            with self.subTest(note=note):
                got, b = self.gate(questions=[FORK], units=UNITS)
                self.answer(b, got, note=note)
                self.assertFalse(gatemarks.answered(b, FORK))
                self.assertEqual(self.owed(b), {OTHER_UNIT})

    def test_hold_note_names_a_key_that_holds_a_separator(self):
        """台帳の key が区切りの字（/）を含んでも、「保留: <key>」はその問いを保留にする"""
        slashed = {**FORK, "key": "storage/backend"}
        got, b = self.gate(questions=[slashed], units=UNITS)
        self.answer(b, got, note=f"保留: {slashed['key']}")
        self.assertFalse(gatemarks.answered(b, slashed))
        self.assertEqual(self.owed(b), {OTHER_UNIT})

    def test_unread_hold_is_shown_to_the_human(self):
        """台帳の key を拾えない「保留」（打ち間違いの key・コロン無し）は答えた扱いのまま、報告の冒頭と最後の関所の文に
        「読めなかった保留」として一言の断片と答えた扱いになった問いの key を並べる"""
        for note in ("保留: q-emty-mean", "q-emty-mean は保留"):
            with self.subTest(note=note):
                got, b = self.gate(questions=[FORK], units=UNITS)
                self.answer(b, got, note=note)
                self.assertTrue(gatemarks.answered(b, FORK))
                for text in (self.head(b), self.final_text(b)):
                    rows = [r for r in text.splitlines() if "読めなかった保留" in r]
                    self.assertTrue(rows, text)
                    self.assertIn("q-emty-mean", "\n".join(rows))
                    self.assertIn(FORK["key"], "\n".join(rows))

    def test_unread_hold_beside_a_read_key_is_shown(self):
        """正しい key と打ち間違いを並べた「保留:」は、正しい key を保留にしたまま、打ち間違いの側を「読めなかった保留」に並べる。
        key の後ろの言葉（英語・「-」も）だけなら並べない"""
        for tail in ("・q-typo", "・q-typo は来週", ", q-typo"):
            with self.subTest(tail=tail):
                got, b = self.gate(questions=[FORK], units=UNITS)
                self.answer(b, got, note=f"保留: {FORK['key']}{tail}")
                self.assertFalse(gatemarks.answered(b, FORK))
                for text in (self.head(b), self.final_text(b)):
                    rows = "\n".join(r for r in text.splitlines() if "読めなかった保留" in r)
                    self.assertIn("「q-typo」", rows, text)
        for tail in ("は来週決める", " until Monday", " - 来週決める"):
            with self.subTest(tail=tail):
                got, b = self.gate(questions=[FORK], units=UNITS)
                self.answer(b, got, note=f"保留: {FORK['key']}{tail}")
                self.assertFalse(gatemarks.answered(b, FORK))
                self.assertEqual(gatemarks.unread_hold_lines(b), [])

    def test_stop_or_another_gate_does_not_return_the_origin(self):
        got, b = self.gate(questions=[FORK], units=UNITS)
        b.record["process"]["human_items"].append({"round": 1, "kinds": ["fork"], "asked": got["ask"]["items"],
                                                   "answer": "stop", "note": "", "node": "p2.human_gate"})
        b.record["process"]["human_items"].append({"round": 1, "kinds": ["regression"], "asked": got["ask"]["items"],
                                                   "answer": "continue", "note": "", "node": "r4.human_gate"})
        self.assertEqual(self.owed(b), {OTHER_UNIT})

    def test_unattended_run_does_not_open_the_gate_for_questions_only(self):
        """無人の run: 保留の問いだけでは関所を開かず（無人の殻の stop で修正が飛ばない）、出どころだけを今どおり飛ばし、ほかの
        単位は直す義務に残る（BASE で直せていた単位を失わない）。狭めの在る関所は今どおり開く（問いの行は載せない）"""
        (self.tmp / "r1").mkdir()
        (self.tmp / "r1" / "start.json").write_text('{"unattended": "true"}', encoding="utf-8")
        got, b = self.gate(questions=[FORK], units=UNITS)
        self.assertEqual(got, {"ok": True})
        self.assertEqual(self.owed(b), {OTHER_UNIT})
        self.assertIn(FORK["key"], self.head(b))   # 答えの無い問いは報告の冒頭に並ぶ
        got, _ = self.gate(narrows=[NARROW], questions=[FORK], units=UNITS)
        self.assertEqual((got["ask"]["kinds"], len(got["ask"]["items"])), (["regression"], 1))

    def test_held_questions_are_listed_not_none(self):
        """最後の関所の文と報告の冒頭: 台帳の保留（fork でない awaiting も）を並べ、『盤面の問い: 無い』と書かない"""
        awaiting = {"key": "q-awaiting-pr", "kind": "awaiting", "status": "held", "origin": "parallel_pr", "reason": "人が確かめる"}
        _, b = self.gate(questions=[FORK, awaiting], units=UNITS)
        for name, text in (("最後の関所", self.final_text(b)), ("報告の冒頭", self.head(b))):
            with self.subTest(name):
                self.assertNotIn("盤面の問い: 無い", text)
                self.assertIn(FORK["key"], text)
                self.assertIn(awaiting["key"], text)
        _, empty = self.gate(units=UNITS)
        self.assertIn("盤面の問い: 無い", self.final_text(empty))
        self.assertNotIn(gatemarks.ASK_HEAD, self.head(empty))


ESCALATE = {**FORK, "key": "q-stuck-mean", "kind": "stuck", "status": "escalate"}
SKIP_MARK = "答えが無いと直さない単位"


class EscalateAsksCase(GateBase):
    """status が escalate の問い（kind が fork でない）も、関所に載せる問いと同じ 1 つの決まりで直す義務から外し・戻す:
    答える前は出どころを外し、continue で戻し、「保留: <key>」では外したまま、無人の run でも外す"""
    answer, owed, final_text, head = (LedgerAsksCase.answer, LedgerAsksCase.owed, LedgerAsksCase.final_text,
                                      LedgerAsksCase.head)

    def test_unanswered_escalate_origin_is_not_owed(self):
        got, b = self.gate(questions=[ESCALATE], units=UNITS)
        self.assertEqual(got["ask"]["kinds"], ["escalate"])
        self.assertEqual(self.owed(b), {OTHER_UNIT})

    def test_continue_returns_the_escalate_origin(self):
        got, b = self.gate(questions=[ESCALATE], units=UNITS)
        self.answer(b, got, note="例外で")
        self.assertEqual(self.owed(b), {FORK_UNIT, OTHER_UNIT})
        self.assertIn(FORK_UNIT, "\n".join(gatemarks.returned_lines(b)))

    def test_hold_note_keeps_the_escalate_origin_exempt(self):
        got, b = self.gate(questions=[ESCALATE], units=UNITS)
        self.answer(b, got, note=f"保留: {ESCALATE['key']}")
        self.assertEqual(self.owed(b), {OTHER_UNIT})

    def test_unattended_run_keeps_the_escalate_origin_exempt(self):
        (self.tmp / "r1").mkdir()
        (self.tmp / "r1" / "start.json").write_text('{"unattended": "true"}', encoding="utf-8")
        got, b = self.gate(questions=[ESCALATE], units=UNITS)
        self.assertEqual(got, {"ok": True})
        self.assertEqual(self.owed(b), {OTHER_UNIT})
        self.assertIn(ESCALATE["key"], self.head(b))

    def test_skip_mark_only_on_questions_still_exempting(self):
        """held_lines・最後の関所の文は、答えて戻した問いと関所に載らない問いに「答えが無いと直さない単位」を付けない"""
        awaiting = {"key": "q-awaiting-pr", "kind": "awaiting", "status": "held", "origin": "parallel_pr", "reason": "人が確かめる"}
        for q in (FORK, ESCALATE):
            got, b = self.gate(questions=[q, awaiting], units=UNITS)
            self.answer(b, got, note="例外で")
            rows = gatemarks.held_lines(b)
            self.assertFalse([r for r in rows if SKIP_MARK in r], (q["kind"], rows))
            self.assertNotIn(f"{SKIP_MARK}: {FORK_UNIT}", self.final_text(b))
        _, b = self.gate(questions=[ESCALATE], units=UNITS)
        self.assertIn(f"{SKIP_MARK}: {FORK_UNIT}", "\n".join(gatemarks.held_lines(b)))

    def test_answered_question_is_not_counted_as_held(self):
        """関所で continue を受けた問いは、報告の冒頭の「決めてほしいこと」と最後の関所の文の「保留にしたままの問い」の件数に
        数えない（行は答えた問いとして並べたまま）。関所に載らない台帳の問いは今どおり数える"""
        awaiting = {"key": "q-awaiting-pr", "kind": "awaiting", "status": "held", "origin": "parallel_pr", "reason": "人が確かめる"}
        got, b = self.gate(questions=[FORK], units=UNITS)
        self.answer(b, got, note="例外で")
        with mock.patch.object(report, "_asked", return_value=[]):
            self.assertNotIn("保留にしたままの問い", "\n".join(report.head3(b, "fixed")))
        text = self.final_text(b)
        self.assertNotIn("保留にしたままの問い", text)
        self.assertIn("関所で continue を受けた", text)
        got, b = self.gate(questions=[FORK, awaiting], units=UNITS)
        self.answer(b, got, note="例外で")
        with mock.patch.object(report, "_asked", return_value=[]):
            self.assertIn("保留にしたままの問い 1 件", "\n".join(report.head3(b, "fixed")))
        self.assertIn("保留にしたままの問い（問いの台帳・1 件", self.final_text(b))

    def test_skip_mark_drops_a_unit_another_answer_returned(self):
        """保留の問いと答えた問いが同じ出どころを持つと、その単位は直す義務に戻るので、保留の問いの行に「答えが無いと直さない
        単位」として並べない（戻らなかった depends だけを並べる）"""
        held = {**ESCALATE, "depends": [OTHER_UNIT]}
        got, b = self.gate(questions=[FORK, held], units=UNITS)
        self.answer(b, got, note=f"保留: {held['key']}")
        self.assertEqual(self.owed(b), {FORK_UNIT})
        rows = [r for r in gatemarks.held_lines(b) if held["key"] in r]
        self.assertEqual([r.split(f"{SKIP_MARK}: ")[1] for r in rows], [OTHER_UNIT])

    def test_gate_item_exemption_and_return_name_the_same_units(self):
        """fork と escalate の両方で、関所の項目が名指す単位・答える前に外れる単位・答えて戻る単位が同じ"""
        for q in (FORK, ESCALATE):
            got, b = self.gate(questions=[q], units=UNITS)
            named = {u for u in (FORK_UNIT, OTHER_UNIT) if u in got["ask"]["items"][0]}
            exempt = {FORK_UNIT, OTHER_UNIT} - self.owed(b)
            self.answer(b, got)
            self.assertEqual((q["kind"], named, exempt, gatemarks.returned(b)), (q["kind"], *({FORK_UNIT},) * 3))


class DesignOnlyCase(GateBase):
    """設計だけの run（start の控えの design_only）: 修正前の関所を項目の有無に関わらず開け、無人の run でも開け、
    その行に continue を受けた後は 2 度聞かない。design_only の無い・空の run は今どおり項目だけで開く"""

    def start(self, **doc):
        (self.tmp / "r1").mkdir(exist_ok=True)
        (self.tmp / "r1" / "start.json").write_text(json.dumps(doc), encoding="utf-8")

    def test_design_only_run_opens_the_gate_without_items(self):
        for doc in ({}, {"design_only": ""}):
            with self.subTest(doc=doc):
                self.start(**doc)
                got, _ = self.gate()
                self.assertEqual(got, {"ok": True})
        self.start(design_only="true")
        got, b = self.gate()
        self.assertEqual(got.get("decision"), "ask", got)
        self.assertEqual((got["ask"]["kinds"], len(got["ask"]["items"])), (["design_only"], 1))
        self.assertIn("design_only", gatemarks.KIND_WORDS)   # 関所の文が『人が決める項目』と書かない
        b.record["process"]["human_items"].append({"round": 1, "kinds": got["ask"]["kinds"], "asked": got["ask"]["items"],
                                                   "answer": "continue", "note": "", "node": "p2.human_gate"})
        self.assertEqual(gatemarks.plan_gate_items(b), [])   # continue を受けた設計だけの行は 2 度聞かない

    def test_design_only_opens_even_when_unattended(self):
        """無人の run でも設計だけの行は載り（無人の殻が stop を返して報告へ進む）、問いの行は今どおり載せない"""
        self.start(unattended="true", design_only="true")
        got, _ = self.gate(questions=[FORK], units=UNITS)
        self.assertEqual(got.get("decision"), "ask", got)
        self.assertEqual(got["ask"]["kinds"], ["design_only"])


class ConvergeGateCase(GateBase):
    """事前審査の壁打ちが止まった（converge の控えの抜け方が persisted・unsettled）案: 修正前の関所を修正に進まない行で開け、行の尾に
    止まった理由（converge.stuck_reason）を付ける。入力 design_only と重なっても行は 1 つ。無人の run でも載る。その行の全文に
    continue を受けた後は 2 度聞かず、理由が変われば聞き直す"""

    def converged(self, outcome, blocks=("a-key-001",)):
        """b.work の控えに往復と抜け方を置く（converge.record_pass を往復の数だけ。偽の盤面は今の周 1・置き場 self.tmp）"""
        fake = types.SimpleNamespace(round=1, dir=self.tmp, work=lambda name: self.tmp / name, trace=lambda op, **kw: None)
        faces = [{"key": k, "kind": "regression", "where": "stats.py", "why": "穴", "severity": "block"} for k in blocks]
        reviews = {converge.CLEAN: [[]], converge.AGAIN: [faces], converge.PERSISTED: [faces, faces]}[outcome]
        for review in reviews:
            row = converge.record_pass(fake, {"faces": review}, resolved=[], fence=9, files={})
        self.assertEqual(row["outcome"], outcome)

    start = DesignOnlyCase.start

    def answer(self, b, got):
        b.record["process"]["human_items"].append({"round": 1, "kinds": got["ask"]["kinds"], "asked": got["ask"]["items"],
                                                   "answer": "continue", "note": "", "node": "p2.human_gate"})

    def test_stuck_opens_design_item_with_reason(self):
        self.converged(converge.PERSISTED)
        got, b = self.gate()
        self.assertEqual(got.get("decision"), "ask", got)
        self.assertEqual(got["ask"]["kinds"], ["design_only"])
        self.assertTrue(got["ask"]["items"][0].startswith(gatemarks.STUCK_ITEM + "。理由: "), got["ask"]["items"])
        self.assertIn("a-key-001", got["ask"]["items"][0])
        self.assertEqual(got["ask"]["items"][0], f"{gatemarks.STUCK_ITEM}。理由: {converge.stuck_reason(b)}")
        self.assertNotIn("設計だけの run", got["ask"]["items"][0])   # 普通の run の止まりは設計だけの行と名乗らない（f2）

    def test_clean_or_again_does_not_open(self):
        for outcome in (converge.CLEAN, converge.AGAIN):
            with self.subTest(outcome=outcome):
                (self.tmp / converge.RECORD).unlink(missing_ok=True)
                self.converged(outcome)
                got, _ = self.gate()
                self.assertEqual(got, {"ok": True})

    def test_stuck_opens_even_when_unattended(self):
        self.start(unattended="true")
        self.converged(converge.PERSISTED)
        got, _ = self.gate(questions=[FORK], units=UNITS)
        self.assertEqual(got["ask"]["kinds"], ["design_only"])

    def test_design_only_and_stuck_give_one_line(self):
        self.start(design_only="true")
        self.converged(converge.PERSISTED)
        got, _ = self.gate()
        self.assertEqual(got["ask"]["kinds"], ["design_only"])
        self.assertEqual(len(got["ask"]["items"]), 1)
        self.assertTrue(got["ask"]["items"][0].startswith(gatemarks.DESIGN_ONLY_ITEM + "。理由: "), got["ask"]["items"])

    def test_design_only_alone_keeps_todays_text(self):
        self.start(design_only="true")
        got, b = self.gate()
        self.assertEqual(got["ask"]["items"], [gatemarks.DESIGN_ONLY_ITEM])
        self.assertEqual(gatemarks.design_item(b), gatemarks.DESIGN_ONLY_ITEM)

    def test_continue_answers_only_that_reason(self):
        self.converged(converge.PERSISTED)
        got, b = self.gate()
        self.answer(b, got)
        self.assertEqual(gatemarks.plan_gate_items(b), [])   # 同じ理由の行に continue を受けた: 2 度聞かない
        fake = types.SimpleNamespace(round=1, dir=self.tmp, work=lambda name: self.tmp / name, trace=lambda op, **kw: None)
        face = {"key": "b-key-002", "kind": "regression", "where": "stats.py", "why": "別の穴", "severity": "block"}
        for _ in range(2):
            converge.record_pass(fake, {"faces": [face]}, resolved=[], fence=9, files={})
        self.assertEqual(converge.read(fake)["outcome"], converge.PERSISTED)
        again = gatemarks.plan_gate_items(b)   # 別の key で止まった: 理由が変わったのでもう一度聞く
        self.assertEqual([k for k, _ in again], ["design_only"])
        self.assertIn("b-key-002", again[0][1])


RECORD_NAME = re.compile(r"(?<![A-Za-z0-9_.])(?:(?:p\d|spec|report)\.[a-z0-9_]+|process\.[a-z_.]+[a-z]|fix_test_scope|fix_code_as|ask_human)")
EYE_OR_STATE = re.compile(r"(?<![A-Za-z0-9_-])(?:R[1-4]|pass|redesign-needed|unverifiable|premise-invalid|carried_over|not_applicable"
                          r"|not_run)(?![A-Za-z0-9_-])")


def _spans(line: str) -> list:
    """行の外側の括弧（（）と ()）の (始め, 終わり)"""
    out, depth, start = [], 0, 0
    for i, ch in enumerate(line):
        if ch in "（(":
            if depth == 0:
                start = i
            depth += 1
        elif ch in "）)" and depth:
            depth -= 1
            if depth == 0:
                out.append((start, i))
    return out


def internal_subjects(text: str) -> list:
    """人が読む文の行のうち、盤面の内部の名が主語になっている行。記録の名（節の名・記録の欄・裁定の語）は括弧の中の『記録の名』の
    後ろにだけ、目の名と状態の語は括弧の中にだけ置いてよい（平易な名が主語で、内部の名は括弧に回す）"""
    bad = []
    for line in text.splitlines():
        spans = _spans(line)
        inside = lambda m: next(((s, e) for s, e in spans if s < m.start() < e), None)  # noqa: E731
        for m in EYE_OR_STATE.finditer(line):
            if inside(m) is None:
                bad.append(line)
        for m in RECORD_NAME.finditer(line):
            span = inside(m)
            if span is None or "記録の名" not in line[span[0]:m.start()]:
                bad.append(line)
    return list(dict.fromkeys(bad))


class PlainSubjectCase(GateBase):
    """関所の文と報告の頭は平易な名を主語にし、盤面の内部の名（節の名・記録の欄・目の名・状態の語）は括弧に回す"""

    def test_plan_gate_text_subjects_are_plain(self):
        text = line_edge.gate_text({"node": "p2.human_gate", "kinds": ["regression"], "question": "狭まる能力を代償に採るか",
                               "items": ["項目 A"]}, run_id="run-1")
        self.assertEqual(internal_subjects(text), [])

    def test_final_gate_text_subjects_are_plain(self):
        rounds = self.tmp / "rounds"
        rounds.mkdir()
        (rounds / "round-1.json").write_text(json.dumps({"reviews": {
            "R1": {"status": "pass"}, "R2": {"status": "pass"}, "R3": {"status": "not_applicable", "reason": "範囲の外"},
            "R4": {"status": "not_run"}}}), encoding="utf-8")
        _, b = self.gate()
        outs = {"p3.delta_fix": {"handled": [{"key": "単位 A", "handled": "直した", "how": "境の値を足した"}]}}
        b.output_of_round = lambda nid, rnd: outs.get(nid)
        b.state["pending_human"] = {"node": "p2.human_gate", "question": "狭まる能力を代償に採るか", "items": ["項目 A"]}
        eyes = line_edge._eyes(b)
        rest = report.rest_outside_validator(b, tests={}, counts=eyes.counts)
        text = line_edge._final_text(b, {}, "", eyes, rest, self.tmp, "run-1")
        self.assertEqual(internal_subjects(text), [])

    def test_report_head_subjects_are_plain(self):
        _, b = self.gate()
        b.record["process"]["human_items"].append({"round": 1, "kinds": ["regression"], "asked": ["項目 A"],
                                                   "answer": "continue", "note": "通す", "node": "p2.human_gate"})
        b.state["pending_human"] = {"node": "p2.human_gate", "question": "狭まる能力を代償に採るか", "items": ["項目 A"]}
        counts = {"parked": 1, "fix_test_scope": 1, "fix_code_as": 0, "ask_human": 0, "unruled": 0}
        with mock.patch.object(report, "_stop_info", return_value=("", "", None)), \
                mock.patch.object(report, "_latest", return_value=None), \
                mock.patch.object(report.conflict, "counts", return_value=counts), \
                mock.patch.object(report, "_rejudge_changes", return_value=[]), \
                mock.patch.object(report, "_premise_hypotheses", return_value=[]), \
                mock.patch.object(report, "_pr_lines", return_value=[]), \
                mock.patch.object(report.querytest, "unproven_lines", return_value=[]), \
                mock.patch.object(report.querytest, "closure_lines", return_value=["単位 A: 閉じていない"]):
            text = "\n".join(report.head_decisions(b, {}, tests=None, outcome="round_limit",
                                                   left=[{"where": "判定", "text": "直していない単位が残った"}]))
        self.assertEqual(internal_subjects(text), [])

    def test_closure_head_subject_is_plain(self):
        """閉鎖の数え直しは内部の語なので、見出しの主語にせず括弧に回す"""
        import querytest
        bare = querytest.CLOSURE_HEAD
        for s, e in reversed(_spans(bare)):
            bare = bare[:s] + bare[e + 1:]
        self.assertNotIn("閉鎖の数え直し", bare)


# 写しの規則が本線の答え方で書く問いの文（本線 graphloops の human_gate の question と同じ形）
MAINLINE_Q = ("今ある能力を減らす変更が挙がった。通すなら continue --note <通す範囲と条件>。\n"
              "単位を外すなら --detail <JSON のファイル>。通さないなら stop")


def unquoted_mainline(text: str) -> list:
    """引用（> の行）の外で、問いの文の行がそのまま載っている行"""
    parts = [x.strip() for x in MAINLINE_Q.splitlines()]
    return [line for line in text.splitlines() if not line.lstrip().startswith(">") and any(p in line for p in parts)]


class QuotedQuestionCase(GateBase):
    """盤面の問いの文は本線の答え方（continue --note・--detail）で書かれているので、関所の文と報告には引用（> の行）として載せ、
    関所では引用の後に読み替えの 1 行（--note・--detail がこのラインでどう読まれるか）を添え、答え方は answer.line の 1 通りだけ"""

    def asking(self):
        return {"node": "p2.human_gate", "kinds": ["regression"], "question": MAINLINE_Q, "items": ["項目 A"]}

    def check_gate(self, text, continue_line):
        self.assertEqual(unquoted_mainline(text), [])
        quoted = [x.lstrip()[1:].strip() for x in text.splitlines() if x.lstrip().startswith(">")]
        self.assertEqual(quoted, [x.strip() for x in MAINLINE_Q.splitlines()])
        after = text.split(quoted[-1], 1)[1].split("答え方", 1)[0]
        note = [x for x in after.splitlines() if "--note" in x and "--detail" in x]
        self.assertEqual(len(note), 1, after)
        self.assertEqual(text.count(continue_line), 1, "答え方の continue は 1 通りだけ")

    def test_plan_gate_quotes_mainline_question(self):
        self.check_gate(line_edge.gate_text(self.asking(), run_id="run-1"),
                        line_edge.answer.line("run-1", "continue", "<通す範囲と条件>"))

    def test_final_gate_quotes_board_question(self):
        _, b = self.gate()
        b.state["pending_human"] = self.asking()
        b.output_of_round = lambda nid, rnd: None
        eyes = line_edge._eyes(b)
        rest = report.rest_outside_validator(b, tests={}, counts=eyes.counts)
        text = line_edge._final_text(b, {}, "", eyes, rest, self.tmp, "run-1")
        self.assertEqual(unquoted_mainline(text), [])
        self.assertTrue(any(x.lstrip().startswith(">") for x in text.splitlines()), text)

    def test_report_head_quotes_board_question(self):
        _, b = self.gate()
        b.state["pending_human"] = self.asking()
        with mock.patch.object(report, "_stop_info", return_value=("", "", None)), \
                mock.patch.object(report, "_latest", return_value=None), \
                mock.patch.object(report, "_conflict_line", return_value=""), \
                mock.patch.object(report, "_rejudge_changes", return_value=[]), \
                mock.patch.object(report, "_premise_hypotheses", return_value=[]), \
                mock.patch.object(report, "_pr_lines", return_value=[]), \
                mock.patch.object(report.querytest, "unproven_lines", return_value=[]), \
                mock.patch.object(report.querytest, "closure_lines", return_value=[]):
            text = "\n".join(report.head_decisions(b, {}, tests=None))
        self.assertEqual(unquoted_mainline(text), [])
        self.assertTrue(any(x.lstrip().startswith(">") for x in text.splitlines()), text)


class R4GateCase(GateBase):
    """修正の後の関所（r4.human_gate）が、修正前の関所で人が continue で通した狭まりと種類も本文も同じ行を聞き直さない。
    行の頭は関所ごとに違う（写しの R4_ROWS と修正案の狭めの行）ので、頭を除いた本文で照らす。種類が違えば聞き直す"""

    def r4_gate(self, answer="continue", lost=(), policy=()):
        """修正前の関所で狭め NARROW を聞かれて answer で答えた盤面で、R4 が lost・policy を返した周の r4.human_gate を回す"""
        got, b = self.gate(narrows=[NARROW])
        self.assertEqual(got.get("decision"), "ask", got)
        b.record["process"]["human_items"].append({"round": 1, "kinds": got["ask"]["kinds"], "asked": got["ask"]["items"],
                                                   "answer": answer, "note": "", "node": "p2.human_gate"})
        before = b.output_of_round
        r4 = {"capability_inventory": {"fired": True, "lost": list(lost)}, "policy_conflicts": list(policy)}
        b.output_of_round = lambda nid, rnd: r4 if nid == "r4.hidden_scope" else before(nid, rnd)
        return registry(b.rules, "BUILTINS")["human_gate"](b, "r4.human_gate"), b

    def test_r4_does_not_reask_narrow_the_human_passed(self):
        body = f"{NARROW['what']}——{NARROW['why']}"
        got, b = self.r4_gate(lost=[body])
        self.assertEqual(got, {"ok": True})
        passes = [p for p in b.state["works"].get("gate_passes") or [] if p["node"] == "r4.human_gate"]
        self.assertEqual([p["by"] for p in passes], ["human"])
        self.assertIn(body, passes[0]["item"])
        self.assertEqual(passes[0]["passed_at"], {"node": "p2.human_gate", "round": 1})
        self.assertTrue(any("人が通した" in x and body in x for x in gatemarks.lines(b)), gatemarks.lines(b))

    def test_r4_reasks_other_kind_or_unpassed(self):
        body = f"{NARROW['what']}——{NARROW['why']}"
        for label, kw in (("種類が違う", {"policy": [body]}), ("stop で答えた", {"answer": "stop", "lost": [body]}),
                          ("本文が違う", {"lost": [f"{NARROW['what']}——別の理由"]})):
            with self.subTest(label):
                got, _ = self.r4_gate(**kw)
                self.assertEqual(got.get("decision"), "ask", got)


AWAITING_PR = {"key": "q-awaiting-pr", "kind": "awaiting", "status": "held", "origin": "parallel_pr",
               "reason": "人が確かめる。測り方: `gh pr list --state open`"}


class RequestAnswersCase(GateBase):
    """依頼の answers が台帳の問いの key か出どころに当たれば、関所の continue と同じ 1 つの述語で答えたと読む"""
    answer, owed, final_text, head = (LedgerAsksCase.answer, LedgerAsksCase.owed, LedgerAsksCase.final_text,
                                      LedgerAsksCase.head)

    def answers(self, *rows):
        (self.tmp / "r1").mkdir(exist_ok=True)
        (self.tmp / "r1" / "start.json").write_text(json.dumps({"answers": list(rows)}, ensure_ascii=False), encoding="utf-8")

    def test_requester_answer_by_origin_moves_awaiting_out_of_held(self):
        self.answers({"question": "parallel_pr", "text": "並行する PR は無い"})
        _, b = self.gate(questions=[AWAITING_PR], units=UNITS)
        self.assertEqual(gatemarks.held_lines(b), [])
        done = "\n".join(gatemarks.answered_lines(b))
        self.assertIn("依頼者の答え: 並行する PR は無い", done)
        self.assertNotIn("関所で continue を受けた", done)
        for name, text in (("最後の関所", self.final_text(b)), ("報告の冒頭", self.head(b))):
            with self.subTest(name):
                self.assertIn(gatemarks.ANSWERED_HEAD, text)
                self.assertNotIn("保留にしたままの問い", text)

    def test_requester_answer_by_key_skips_gate_and_returns_origin(self):
        self.answers({"question": FORK["key"], "text": "例外のまま"})
        got, b = self.gate(questions=[FORK], units=UNITS)
        self.assertEqual(got, {"ok": True}, "答えた問いは修正前の関所に載せない")
        self.assertEqual(gatemarks.pending(b), [])
        self.assertEqual(self.owed(b), {FORK_UNIT, OTHER_UNIT})
        self.assertIn("依頼者の答え: 例外のまま", "\n".join(gatemarks.returned_lines(b)))

    def test_measured_answer_shows_command_and_output(self):
        self.answers({"question": "parallel_pr", "text": "一覧は空", "command": "gh pr list --state open",
                      "output": "no open pull requests"})
        _, b = self.gate(questions=[AWAITING_PR], units=UNITS)
        line = gatemarks.answered_lines(b)[0]
        self.assertIn("人が手元で実行: `gh pr list --state open`", line)
        self.assertIn("no open pull requests", line)

    def test_unmatched_answer_is_shown_and_question_stays_held(self):
        self.answers({"question": "parallel-pr", "text": "無い"})
        _, b = self.gate(questions=[AWAITING_PR], units=UNITS)
        self.assertEqual(len(gatemarks.held_lines(b)), 1)
        self.assertIn("parallel-pr", "\n".join(gatemarks.unmatched_answer_lines(b)))
        for text in (self.final_text(b), self.head(b)):
            self.assertIn("依頼の答えに当たる問いが台帳に無い", text)
            self.assertIn(gatemarks.ANSWER_HOW, text)

    def test_answer_hitting_several_questions_answers_none(self):
        """出どころで当てた答えが同じ単位の別の問い（fork と escalate）に当たれば、どれにも答えた扱いにせず名指す"""
        self.answers({"question": FORK_UNIT, "text": "例外のまま"})
        got, b = self.gate(questions=[FORK, ESCALATE], units=UNITS)
        self.assertEqual(got.get("decision"), "ask", "どちらの問いも関所に載る")
        self.assertEqual(gatemarks.answered_lines(b), [])
        self.assertEqual(gatemarks.returned_lines(b), [])
        self.assertEqual(len(gatemarks.held_lines(b)), 2)
        line = "\n".join(gatemarks.unmatched_answer_lines(b))
        self.assertIn(f"複数の問いに当たった: {FORK_UNIT} → {FORK['key']}・{ESCALATE['key']}", line)
        for text in (self.final_text(b), self.head(b)):
            self.assertIn("複数の問いに当たった", text)

    def test_answer_by_key_is_not_ambiguous(self):
        """key で当てた答えは、同じ出どころの問いが他に在ってもその問いだけに当たる"""
        self.answers({"question": ESCALATE["key"], "text": "直さない"})
        _, b = self.gate(questions=[FORK, ESCALATE], units=UNITS)
        self.assertIn("依頼者の答え: 直さない", "\n".join(gatemarks.answered_lines(b)))
        self.assertEqual(len(gatemarks.held_lines(b)), 1)
        self.assertEqual(gatemarks.unmatched_answer_lines(b), [])

    def test_answer_hitting_settled_question_is_shown(self):
        """決着済みの問いに当たった答えも、答えた行・当たらなかった行のどちらからも落とさず名指す"""
        self.answers({"question": "parallel_pr", "text": "無い"})
        _, b = self.gate(questions=[{**AWAITING_PR, "status": "decided"}], units=UNITS)
        self.assertEqual(gatemarks.answered_lines(b), [])
        line = "\n".join(gatemarks.unmatched_answer_lines(b))
        self.assertIn(f"決着済みの問いに当たった答え: parallel_pr → {AWAITING_PR['key']}（decided）", line)
        self.assertIn("依頼者の答え: 無い", line)
        for text in (self.final_text(b), self.head(b)):
            self.assertIn("決着済みの問いに当たった答え", text)


if __name__ == "__main__":
    unittest.main()
