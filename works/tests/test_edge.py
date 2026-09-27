"""境の節の芯（darkfactory/lib/line_edge.py の edge・darkfactory/lib/plan.py の gate_text・darkfactory/scripts/edge.py）の検査（線 A の仕様 2 節・
計画 Task 10a・裁定 TA1・TA4）。止め札の置き方そのもの（halt.place・seen・over・dev/stop.sh）は test_halt.py。

盤面は linekit の種で start → 見本の返答を entry.take で進めて作る（役の返答の前に起こした印を置く。盤面の決まり 2）。
周 2 の盤面だけは手本 test_runaway の Run 1（p2.fix_plan を周 2 に受けた手の後）から作る。
- 関所の答え（policy-gate）: 文字列 null は「開かなかった」（answer を呼ばない）。approve・continue は continue、stop・reject は
  stop（盤面は halted.by == "answer"）。一言は process.human_items に 1 バイトも変わらずに届く
- 最後の人の関所（final-gate。計画 P1 Task 26・P1-R3。中の関所は無い）: always はいつも、when_needed は最後のテストが緑でない・
  盤面の問い・止めずに残った異議の時だけ開く。答えは h-eyes が受け、stop は b.stop（by human:final-gate）。周を締めた盤面
  （halted.by stop_after_round）では trace の 1 行と final-gate-answer.json に残す
- 止め札: 次の境の節で b.stop。関所の答えが先。止めた盤面では b.stop を呼ばず trace にだけ
- go は盤面の ready から（開き直した盤面でも。explicit の機械の節は DiskBoard.ready が足す）
"""
import dataclasses
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

from board import GRAPH_SHA, BoardGap, DiskBoard, NodeTable, graph_expanded  # noqa: E402
import engine.util as engine_util  # noqa: E402  （board が写しの graphloops を sys.path に足す）
import entry  # noqa: E402
import halt  # noqa: E402
import line_edge  # noqa: E402
import linekit  # noqa: E402
import plan  # noqa: E402

SCRIPT = ROOT / "darkfactory" / "scripts" / "edge.py"
RUN_ID = "run-7"
OUT_KEYS = {"ok", "stop", "go", "ask", "gate_text", "judgment_file", "open_units", "plan_file", "notes", "why", "premises_file",
            "pr_go", "premises_go", "purpose_go", "spec_go", "runtime_go", "holdout_go", "mid_note"}
BOOL_KEYS = {"stop", "go", "ask", "pr_go", "premises_go", "purpose_go", "spec_go", "runtime_go", "holdout_go"}
UNIT_MEAN = "stats.py mean: 分母が len(xs) - 1 になっている"
UNIT_CLAMP = "stats.py clamp: 上限を超えた値に lo を返す"
FACE = "clamp の上限の意味が変わる"
DELTA_FACE = "clamp の docstring が古いまま"
ODD_NOTE = 'a "b" \'c\'\n$(rm -rf /) `x` ${HOME} $ARTIFACTS_DIR 日本語の一言\t終わり'


def pending_inst(b, nid):
    return next((i for i in b.rd["instances"].values() if i["node"] == nid and i["status"] == "pending"), None)


def plan_reply() -> dict:
    return {"plan": [{"unit_keys": [UNIT_MEAN, UNIT_CLAMP],
                      "approach": "mean の分母を len(xs) に、clamp の上限の枝を hi に直す（定義どおり）",
                      "adds": [], "removes": [], "shrink_first": "足す物は無い。式と戻り値を 1 か所ずつ直すだけで足りる",
                      "narrows": []}]}


CLEAN_REVIEW = {"faces": [], "shrink": [], "faces_none": "案は式を 2 か所直すだけで、狭まる能力も方針とのぶつかりも無い",
                "reason": "案は 2 か所の式を直すだけで、足す物も消す物も無い。穴も別案も無い"}


def _change(key, what, pattern, sites):
    return {"unit_key": key, "what": what, "files": ["stats.py"],
            "closure": {"mechanism": "式の取り違え", "fix_mechanism": "定義どおりの式に直した", "verified_how": "テストを赤→緑で見た",
                        "sites": [{"site": s, "red_seen": True} for s in sites]},
            "coverage": {"how": {"patterns": [pattern], "fixed": True, "paths": ["stats.py"], "count": "lines"},
                         "counts": "defects"},
            "precedent": {"problem": "算術の定義", "source": "Python 標準ライブラリ statistics（検査用）", "verdict": "adopt",
                          "reason": "定義どおりの形をそのまま採った（検査用）"},
            "root_or_symptom": {"kind": "root", "why": "式そのものを定義どおりに直した"},
            "bypass_tried": "修正を残したまま空でない入力と境界の値を通した——どれも期待どおり",
            "breaks": {"how": "grep -n 'len(xs)' stats.py", "result": "同じ式を使う所は 1 か所だけで既存の検査が緑"}}


def fix_reply(faces: bool) -> dict:
    """種の 2 つのバグを直した p3.fix の返答（写しの schema と fix_covers_open_units を通る形）"""
    return {**entry.empty_fix_reply(),
            "changes": [_change(UNIT_MEAN, "mean の分母を len(xs) に直した", "(len(xs) - 1)", ["stats.py mean"]),
                        _change(UNIT_CLAMP, "clamp の上限の枝で hi を返す", "return lo", ["stats.py clamp 下限の枝", "stats.py clamp 上限の枝"])],
            "interactions": [{"surface": "stats.py",
                              "checked": "2 つの修正は別の関数を触り、当てる順序で結果は変わらない（どちらも式を直すだけ）"}],
            "fix_closure": {"status": "clean", "checked": "テストを走らせ赤→緑を見た"},
            "plan_faces": [{"key": FACE, "handled": "absorbed", "how": "人の関所の答えどおり、上限は hi を返す形にした"}]
            if faces else []}


DELTA_REVIEW = {"faces": [{"key": DELTA_FACE, "kind": "contract_drift", "where": "stats.py",
                           "cite": "clamp: 上限を超えたときに lo を返している",
                           "why": "頭の docstring は今も lo を返すと書いていて、直した後の振る舞いと食い違う"}],
                "checks": [{"key": FACE, "closed": True, "why": "差分で clamp の上限の枝が hi を返す形になり、人の答えどおり"}]}
DELTA_FIX = {"handled": [{"key": DELTA_FACE, "handled": "declared", "how": "docstring は種の説明で、仕込んだバグの記録として残す"}]}


def trace_rows(board_dir, op=None):
    p = pathlib.Path(board_dir) / "trace.jsonl"
    rows = [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()] if p.exists() else []
    return [r for r in rows if op is None or r.get("op") == op]


class EdgeBase(unittest.TestCase):
    def setUp(self):
        self._old_cwd = engine_util.GIT_CWD
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        self.tmp = pathlib.Path(self._tmp.name)
        env = mock.patch.dict("os.environ", {"WORKS_ADAPTER_HOME": str(self.tmp / "adapter-home")})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        engine_util.GIT_CWD = self._old_cwd
        self._tmp.cleanup()

    # -- 盤面を線の順に進める（どれも self.board・self.repo を置く）
    def take(self, nid, reply):
        b = entry.open_board(self.board)
        b.mark_launched(nid, pending_inst(b, nid).get("attempts", 1))
        got = entry.take(self.board, nid, reply, self.repo)
        self.assertTrue(got["ok"], got)
        return got

    def started(self):
        """start → 並行 PR の任せ先を受けた盤面（p0.premises が待つ）"""
        self.repo = linekit.seed_repo(self.tmp / "repo", declared=True)
        req = self.tmp / "req" / "request.json"
        req.parent.mkdir(parents=True)
        req.write_text((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.art = self.tmp / "art"
        self.board = self.art / "board"
        raw = {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "mid_gate": "", "adapter": "", "policy_md": ""}
        entry.start(self.board, self.repo, raw, run_id=RUN_ID)
        self.take("p0.parallel_pr", {k: v for k, v in linekit.reply("pr_no_conflicts").items() if k != "excluded"})

    def premised(self):
        """前提の役まで受けた盤面（p2.diagnose が待つ）"""
        self.started()
        self.take("p0.premises", {"constraints": []})

    def premises_exit(self, reply):
        """前提のブロックの出口（collect の形）。constraints_file は reply を書いた盤面の外のファイル"""
        path = self.tmp / "premises-out" / "premises.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        return {"ok": True, "constraints_file": str(path), "constraints_summary": "x"}

    def launched(self):
        """この run の worktree に包みの起動の行を 1 本（盤面を作った後。reads.adapter_seen が数える形）"""
        import adapter
        p = adapter.launches_path(self.repo)
        p.parent.mkdir(parents=True, exist_ok=True)
        row = {"at": adapter.now(), "pid": 1, "cwd": str(self.repo), "node": "premises", "continue": None, "mode": "merged",
               "why": None, "hook": True, "tools_empty": False, "session": None, "fence": None}
        with p.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def judged(self, name="judge_ok"):
        """前提の役まで受け、判定（name の見本）を受けた盤面（p2.fix_plan が待つ）"""
        self.premised()
        return self.take("p2.diagnose", linekit.reply(name))

    def judge_exit(self, name="judge_ok", reply=None):
        """判定のブロックの出口（collect の形）。judgment_file は見本の返答（か reply）を書いた盤面の外のファイル"""
        body = linekit.reply(name) if reply is None else reply
        path = self.tmp / "judge-out" / "judgment.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
        units = [u["key"] for u in body.get("units") or [] if isinstance(u, dict)] if isinstance(body, dict) else []
        return {"ok": True, "open_units": units, "need_fix": bool(units), "judgment_file": str(path), "one_shot": "x"}

    def planned(self, review="plan_review_regression"):
        """判定・修正案・事前審査を受けた盤面。既定の事前審査は regression の穴を持つ（p2.human_gate が人に聞く）"""
        self.judged()
        self.take("p2.fix_plan", plan_reply())
        return self.take("p2.plan_review", linekit.reply(review) if isinstance(review, str) else review)

    def fixed(self):
        """関所に continue で答え、修正を受けた盤面（p3.delta_review が待つ）"""
        self.planned()
        return self.fix_after_plan("clamp の上限は hi でよい")

    def fix_after_plan(self, note):
        """関所の問いに continue で答え、種の 2 つのバグを作業ツリーで直して修正の返答を受ける"""
        entry.open_board(self.board).answer("continue", note)
        src = (self.repo / "stats.py").read_text(encoding="utf-8")
        (self.repo / "stats.py").write_text(src.replace("(len(xs) - 1)", "len(xs)").replace(
            "    if x > hi:\n        return lo", "    if x > hi:\n        return hi"), encoding="utf-8")
        return self.take("p3.fix", fix_reply(faces=True))

    def edge(self, at, **kw):
        kw.setdefault("final_gate", "always")
        kw.setdefault("adapter_mode", "optional")   # 包みの確かめ（at judge）は JudgeEdgeCase が "" で見る
        return line_edge.edge(self.board, at, self.repo, run_id=RUN_ID, **kw)

    def state(self):
        return json.loads((self.board / "state.json").read_text(encoding="utf-8"))


class GateCase(EdgeBase):
    def test_gate_asks_with_text(self):
        """plan_review_regression を受けた盤面 → ask True、gate_text に項目と respond の 1 行、b.work("gate.md") に同じ文"""
        self.assertTrue(self.planned()["asking"])
        got = self.edge("gate")
        self.assertEqual(set(got), OUT_KEYS)
        self.assertEqual((got["ok"], got["stop"], got["ask"]), (True, False, True))
        text = got["gate_text"]
        self.assertIn(f"事前審査の穴 [regression] {FACE}", text)
        self.assertIn(f'archon workflow respond {RUN_ID} continue "<通す範囲と条件>"', text)
        self.assertIn(f'archon workflow respond {RUN_ID} stop "<理由>"', text)
        self.assertIn(f"archon workflow reject {RUN_ID} --reason", text)
        b = entry.open_board(self.board)
        self.assertEqual(b.work(line_edge.GATE_FILE).read_text(encoding="utf-8"), text)
        self.assertEqual(text, plan.gate_text(b.state["pending_human"], run_id=RUN_ID))

    def test_gate_not_asking_leaves_closed(self):
        """問いの無い盤面（穴の無い事前審査）→ ask False・gate_text 空・gate.md を書かない"""
        self.planned(review=CLEAN_REVIEW)
        got = self.edge("gate")
        self.assertEqual((got["ask"], got["gate_text"], got["stop"]), (False, "", False))
        self.assertFalse(entry.open_board(self.board).work(line_edge.GATE_FILE).exists())

    def test_gate_text_without_run_id(self):
        text = plan.gate_text({"node": "p2.human_gate", "kinds": ["policy"], "question": "問い", "items": ["一"]})
        self.assertIn('archon workflow respond <id> continue', text)
        self.assertIn("- 一", text)
        with self.assertRaises(TypeError):
            plan.gate_text("問い")

    def test_gate_null_means_not_opened(self):
        """at fix・gate None → answer を呼ばない。go は p3.fix の ready で決まる（問いの無い盤面は True、問いが残る盤面は False）"""
        self.planned(review=CLEAN_REVIEW)
        with mock.patch.object(DiskBoard, "answer", side_effect=AssertionError("answer を呼んだ")):
            got = self.edge("fix", gate=None)
        self.assertEqual((got["go"], got["stop"]), (True, False))
        self.assertEqual(entry.open_board(self.board).record["process"]["human_items"], [])

    def test_gate_null_with_question_pending(self):
        self.planned()
        with mock.patch.object(DiskBoard, "answer", side_effect=AssertionError("answer を呼んだ")):
            got = self.edge("fix", gate=None)
        self.assertEqual((got["go"], got["stop"]), (False, False))
        self.assertEqual(self.state()["pending_human"]["node"], "p2.human_gate")

    def test_gate_continue_reaches_fixer(self):
        """gate {"decision": "continue", "text": "x"} → human_items に continue と x、notes に x、go True"""
        self.planned()
        got = self.edge("fix", gate={"decision": "continue", "text": "x"})
        self.assertEqual((got["go"], got["stop"], got["notes"]), (True, False, "x"))
        items = entry.open_board(self.board).record["process"]["human_items"]
        self.assertEqual([(h["node"], h["answer"], h["note"]) for h in items], [("p2.human_gate", "continue", "x")])

    def test_approve_is_continue(self):
        self.planned()
        got = self.edge("fix", gate={"decision": "approve", "text": ""})
        self.assertEqual((got["go"], got["notes"]), (True, ""))
        h = entry.open_board(self.board).record["process"]["human_items"][-1]
        self.assertEqual((h["answer"], h["note"]), ("continue", ""))

    def test_reject_is_stop(self):
        """gate {"decision": "reject", "text": "y"} → halted.by == "answer"、stop True、以後の edge も全部 stop"""
        self.planned()
        got = self.edge("fix", gate={"decision": "reject", "text": "y"})
        self.assertEqual((got["stop"], got["go"], got["why"]), (True, False, "y"))
        st = self.state()
        self.assertEqual((st["halted"]["by"], st["halted"]["reason"]), ("answer", "y"))
        self.assertEqual(entry.open_board(self.board, allow_halted=True).record["process"]["human_items"][-1]["answer"], "stop")
        for at in line_edge.AT:
            with self.subTest(at=at):
                got = self.edge(at, tests={"ok": True, "green": False, "log": "x"} if at == "final" else None)
                self.assertEqual((got["stop"], got["go"], got["ask"]), (True, False, False))

    def test_stop_without_text_has_default_reason(self):
        self.planned()
        got = self.edge("fix", gate={"decision": "stop", "text": "  "})
        self.assertTrue(got["stop"])
        self.assertEqual(self.state()["halted"]["by"], "answer")
        self.assertEqual(got["why"], line_edge.GATE_STOP_NOTE)

    def test_gate_note_roundtrip(self):
        """一言に引用符・改行・$(・日本語 → human_items の note と notes が 1 バイトも同じ"""
        self.planned()
        got = self.edge("fix", gate={"decision": "continue", "text": ODD_NOTE})
        self.assertEqual(got["notes"], ODD_NOTE)
        h = entry.open_board(self.board).record["process"]["human_items"][-1]
        self.assertEqual(h["note"].encode("utf-8"), ODD_NOTE.encode("utf-8"))

    def test_gate_answer_on_resume_is_not_repeated(self):
        """同じ答えで h-fix を呼び直しても（Archon の再開）、問いはもう無いので 2 度答えない"""
        self.planned()
        self.edge("fix", gate={"decision": "continue", "text": "x"})
        with mock.patch.object(DiskBoard, "answer", side_effect=AssertionError("answer を 2 度呼んだ")):
            got = self.edge("fix", gate={"decision": "continue", "text": "x"})
        self.assertTrue(got["go"])
        self.assertEqual(len(entry.open_board(self.board).record["process"]["human_items"]), 1)

    def test_bad_inputs_are_board_gaps(self):
        """知らない at・知らない答えの語・形の崩れた答え・場違いの入力・知らない final_gate は BoardGap（配線の誤り。終了コード 2）"""
        self.judged()
        cases = [("nowhere", {}), ("midgate", {}), ("fix", {"gate": {"decision": "maybe"}}), ("fix", {"gate": {"text": "x"}}),
                 ("fix", {"gate": "continue"}), ("fix", {"gate": {"decision": "continue", "text": 3}}),
                 ("gate", {"gate": {"decision": "continue"}}), ("review", {"gate": {"decision": "continue"}}),
                 ("fix", {"tests": {"ok": True}}), ("tests", {"tests": {"ok": True}}),
                 ("fix", {"judged": {"judgment_file": "x"}}), ("final", {"tests": {"ok": True}, "final_gate": "sometimes"}),
                 ("final", {"tests": "green"}), ("plan", {"judged": "x"})]
        for at, kw in cases:
            with self.subTest(at=at, kw=kw):
                with self.assertRaises(BoardGap):
                    self.edge(at, **kw)


class FinalGateCase(EdgeBase):
    """最後の人の関所（計画 P1 Task 26）。h-final が開くかと文、h-eyes が答えを受ける"""
    GREEN = {"ok": True, "green": True, "log": "/logs/final.log", "suites": [], "by": "engine"}

    def closed(self):
        """直す物の無い周を最後のテストまで回し、周を締めた盤面（halted.by stop_after_round）。返りは最後のテストの出口"""
        self.premised()
        self.edge("plan", judged=self.judge_exit("judge_no_fix"))
        b = entry.open_board(self.board)
        ci = entry.run_ci(b, "p4.ci", test_cmd="")
        b.settle()
        st = self.state()
        self.assertEqual((st["halted"]["by"], st.get("stop")), (line_edge.ENDED_BY, None))
        return {"ok": True, "green": True, "log": ci["log"], "suites": [], "by": ci["by"]}

    def test_final_always_asks(self):
        """final_gate always・緑 → ask True、文に最後のテストの行と穴の数、b.work(final-gate.md) に同じ文"""
        tests = self.closed()
        got = self.edge("final", tests=tests, final_gate="always")
        self.assertEqual((got["ask"], got["stop"], got["go"]), (True, False, False), got)
        text = got["gate_text"]
        for want in ("テストは緑", tests["log"], str(self.repo), "差分の審査の穴: 0 件", "止めずに残った異議: 無い",
                     f"archon workflow respond {RUN_ID} continue", f"archon workflow respond {RUN_ID} stop"):
            self.assertIn(want, text)
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(b.work(line_edge.FINAL_GATE_FILE).read_text(encoding="utf-8"), text)

    def test_final_default_is_always(self):
        tests = self.closed()
        self.assertTrue(self.edge("final", tests=tests, final_gate="")["ask"])

    def test_final_when_needed_green_skips(self):
        """when_needed・緑・問い無し・異議無し → ask False、文を書かない"""
        tests = self.closed()
        got = self.edge("final", tests=tests, final_gate="when_needed")
        self.assertEqual((got["ask"], got["gate_text"], got["stop"]), (False, "", False))
        self.assertFalse(entry.open_board(self.board, allow_halted=True).work(line_edge.FINAL_GATE_FILE).exists())

    def test_final_when_needed_red_asks(self):
        """when_needed・赤か走れなかった・走らなかった（出口 null）→ ask True、頭の語がそれぞれ"""
        tests = self.closed()
        for exit_, word in (({**tests, "green": False}, "赤"), ({"ok": False, "green": False, "log": "", "reason": "宣言が読めない"},
                                                                "走れなかった"), (None, "走らなかった")):
            with self.subTest(word=word):
                got = self.edge("final", tests=exit_, final_gate="when_needed")
                self.assertTrue(got["ask"])
                self.assertIn(f"テストは{word}", got["gate_text"])
        self.assertIn("宣言が読めない", self.edge("final", tests={"ok": False, "log": "", "reason": "宣言が読めない"},
                                                 final_gate="when_needed")["gate_text"])

    def test_final_when_needed_objection_asks(self):
        """when_needed・緑でも、止めずに残った異議（rejudge.unsettled が未決）が在れば開き、文に異議"""
        tests = self.closed()
        with mock.patch.object(line_edge.rejudge, "unsettled", return_value={"text": "判定の単位が粗い", "settled": False}):
            got = self.edge("final", tests=tests, final_gate="when_needed")
        self.assertTrue(got["ask"])
        self.assertIn("止めずに残った異議: 判定の単位が粗い", got["gate_text"])

    def test_final_gate_stop_and_reject(self):
        """周を締める前の盤面で at eyes・gate stop・reject → state.stop.by "human:final-gate"・理由は一言（無ければ既定）"""
        for decision, text, why in (("stop", "z", "z"), ("reject", "", line_edge.FINAL_GATE_STOP_NOTE)):
            with self.subTest(decision=decision):
                self._tmp.cleanup()
                self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
                self.tmp = pathlib.Path(self._tmp.name)
                self.fixed()
                got = self.edge("eyes", gate={"decision": decision, "text": text})
                self.assertEqual((got["stop"], got["go"], got["why"]), (True, False, why))
                st = self.state()
                self.assertEqual((st["stop"]["by"], st["stop"]["reason"]), (line_edge.FINAL_GATE_BY, why))
                b = entry.open_board(self.board, allow_halted=True)
                doc = json.loads(b.work(line_edge.FINAL_GATE_ANSWER).read_text(encoding="utf-8"))
                self.assertEqual(doc, {"decision": decision, "text": text})
                self.assertEqual(b.record["process"]["human_items"][-1]["answer"], "stop")
                self.assertTrue(self.edge("tests")["stop"])

    def test_final_gate_stop_after_round_closed(self):
        """周を締めた盤面（halted.by stop_after_round）で at eyes・gate stop → b.stop は呼べないので、final-gate-answer.json に
        decision stop・human_items に stop の行・trace に by human:final-gate の 1 行を残し、stop True（報告がこれを読む）"""
        tests = self.closed()
        self.assertFalse(self.edge("final", tests=tests)["stop"], "周を締めた盤面を止めたと読まない")
        got = self.edge("eyes", gate={"decision": "stop", "text": "直し方が違う"})
        self.assertEqual((got["stop"], got["go"], got["why"]), (True, False, "直し方が違う"))
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(json.loads(b.work(line_edge.FINAL_GATE_ANSWER).read_text(encoding="utf-8")),
                         {"decision": "stop", "text": "直し方が違う"})
        h = b.record["process"]["human_items"][-1]
        self.assertEqual((h["answer"], h["note"], h["node"], h["kinds"]), ("stop", "直し方が違う", line_edge.FINAL_GATE_BY,
                                                                          [line_edge.FINAL_GATE_KIND]))
        rows = trace_rows(self.board, line_edge.STOP_AFTER_END_OP)
        self.assertEqual([(r["at"], r["reason"], r["by"]) for r in rows], [("eyes", "直し方が違う", line_edge.FINAL_GATE_BY)])
        self.assertEqual(self.state()["halted"]["by"], line_edge.ENDED_BY)

    def test_final_gate_continue_on_closed_board(self):
        """周を締めた盤面で at eyes・gate continue → 答えのファイルと human_items の continue の行、stop False・go False（目は枠）。
        同じ答えで呼び直しても積み増さない"""
        tests = self.closed()
        self.edge("final", tests=tests)
        for _ in range(2):
            got = self.edge("eyes", gate={"decision": "approve", "text": "x"})
            self.assertEqual((got["stop"], got["go"]), (False, False))
        b = entry.open_board(self.board, allow_halted=True)
        rows = [h for h in b.record["process"]["human_items"] if h.get("node") == line_edge.FINAL_GATE_BY]
        self.assertEqual([(h["answer"], h["note"]) for h in rows], [("continue", "x")])
        self.assertEqual(json.loads(b.work(line_edge.FINAL_GATE_ANSWER).read_text(encoding="utf-8")),
                         {"decision": "approve", "text": "x"})

    def test_final_gate_note_roundtrip(self):
        """一言に $word・$(x)・"・改行・日本語 → human_items と FINAL_GATE_ANSWER に同じバイト"""
        tests = self.closed()
        self.edge("final", tests=tests)
        self.edge("eyes", gate={"decision": "continue", "text": ODD_NOTE})
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(b.record["process"]["human_items"][-1]["note"].encode("utf-8"), ODD_NOTE.encode("utf-8"))
        doc = json.loads(b.work(line_edge.FINAL_GATE_ANSWER).read_text(encoding="utf-8"))
        self.assertEqual(doc["text"].encode("utf-8"), ODD_NOTE.encode("utf-8"))

    def test_final_gate_null_means_not_opened(self):
        tests = self.closed()
        got = self.edge("eyes", gate=None)
        self.assertEqual((got["stop"], got["go"]), (False, False))
        self.assertFalse(entry.open_board(self.board, allow_halted=True).work(line_edge.FINAL_GATE_ANSWER).exists())

    def test_no_mid_gate_left(self):
        """AT に midgate が無く、works の Python の中に MID_GATE_ の名が無い（AST。docs は除く）"""
        import ast
        self.assertNotIn("midgate", line_edge.AT)
        hits = []
        for path in ROOT.rglob("*.py"):
            if "docs" in path.relative_to(ROOT).parts:
                continue
            for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
                name = node.id if isinstance(node, ast.Name) else node.attr if isinstance(node, ast.Attribute) else None
                if name and name.startswith("MID_GATE_"):
                    hits.append(f"{path.relative_to(ROOT)}:{node.lineno} {name}")
        self.assertEqual(hits, [])


class EntryMidCase(EdgeBase):
    def test_entry_edge_flags(self):
        """start の後の盤面（ready に p0.parallel_pr・p0.premises）→ go・pr_go・premises_go True、purpose_go・spec_go False"""
        self.repo = linekit.seed_repo(self.tmp / "repo", declared=True)
        req = self.tmp / "req" / "request.json"
        req.parent.mkdir(parents=True)
        req.write_text((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.art = self.tmp / "art"
        self.board = self.art / "board"
        raw = {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "mid_gate": "", "adapter": "", "policy_md": ""}
        entry.start(self.board, self.repo, raw, run_id=RUN_ID)
        self.assertTrue({"p0.parallel_pr", "p0.premises"} <= set(entry.open_board(self.board).ready()))
        got = self.edge("entry")
        self.assertEqual({k: got[k] for k in ("go", "pr_go", "premises_go", "purpose_go", "spec_go", "stop")},
                         {"go": True, "pr_go": True, "premises_go": True, "purpose_go": False, "spec_go": False, "stop": False})
        self.take("p0.parallel_pr", {k: v for k, v in linekit.reply("pr_no_conflicts").items() if k != "excluded"})
        self.take("p0.premises", {"constraints": []})
        got = self.edge("entry")
        self.assertEqual((got["pr_go"], got["premises_go"]), (False, False))

    def test_mid_is_slot(self):
        """役が修正した盤面 → go True、runtime_go・holdout_go False、mid_note"""
        self.fixed()
        got = self.edge("mid")
        self.assertEqual((got["go"], got["runtime_go"], got["holdout_go"]), (True, False, False))
        self.assertEqual(got["mid_note"], line_edge.MID_NOTE)

    def test_slots_do_not_go(self):
        """rejudge・eyes は枠（go False。中身は計画 P1 Task 31・33）"""
        self.fixed()
        for at in ("rejudge", "eyes"):
            with self.subTest(at=at):
                got = self.edge(at)
                self.assertEqual((got["go"], got["stop"]), (False, False))


class StopFlagCase(EdgeBase):
    def test_stop_flag_each_edge(self):
        """AT の全部で、止め札を置いた後の境の節 → stop、state.stop.by は "request:<札の by>"、trace にその at"""
        for at in line_edge.AT:
            with self.subTest(at=at):
                self._tmp.cleanup()
                self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
                self.tmp = pathlib.Path(self._tmp.name)
                self.judged()
                halt.place(self.board, f"{at} で止める", "carol")
                got = self.edge(at)
                self.assertEqual((got["stop"], got["go"], got["why"]), (True, False, f"{at} で止める"))
                st = self.state()
                self.assertEqual((st["stop"]["reason"], st["stop"]["by"]), (f"{at} で止める", line_edge.FLAG_BY_PREFIX + "carol"))
                self.assertEqual([r["at"] for r in trace_rows(self.board, line_edge.FLAG_SEEN_OP)], [at])

    def test_stop_flag_after_round_closed(self):
        """周を締めた盤面で at final に止め札 → b.stop は呼べないので trace の 1 行（by request:<札の by>）で stop"""
        FinalGateCase.closed(self)
        halt.place(self.board, "後から止める", "dave")
        got = self.edge("final", tests=None)
        self.assertEqual((got["stop"], got["why"]), (True, "後から止める"))
        rows = trace_rows(self.board, line_edge.STOP_AFTER_END_OP)
        self.assertEqual([(r["at"], r["by"]) for r in rows], [("final", line_edge.FLAG_BY_PREFIX + "dave")])

    def test_stop_flag_stops_at_next_edge(self):
        """STOP を置いた後の edge → stop True、state.stop の理由が STOP の理由、by は札の置き手の印、trace にどの境の節か"""
        self.judged()
        self.assertTrue(halt.place(self.board, "依頼が変わった", "alice")["ok"])
        got = self.edge("plan", judged={"ok": True, "open_units": [UNIT_MEAN], "need_fix": True,
                                        "judgment_file": "/j.json", "one_shot": "x"})
        self.assertEqual((got["stop"], got["go"], got["why"]), (True, False, "依頼が変わった"))
        st = self.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["by"]), ("依頼が変わった", line_edge.FLAG_BY_PREFIX + "alice"))
        rows = trace_rows(self.board, line_edge.FLAG_SEEN_OP)
        self.assertEqual([(r["at"], r["reason"], r["by"]) for r in rows], [("plan", "依頼が変わった", "alice")])
        for at in ("gate", "fix", "tests"):   # 以後の境の節も stop。STOP は同じ理由なので trace に積み増さない
            self.assertTrue(self.edge(at)["stop"])
        self.assertEqual(trace_rows(self.board, line_edge.AFTER_HALT_OP), [])

    def test_unreadable_flag_still_stops(self):
        self.judged()
        (self.board / halt.STOP_FILE).write_text("手で置いた", encoding="utf-8")
        got = self.edge("fix")
        self.assertTrue(got["stop"])
        self.assertEqual(self.state()["stop"]["by"], line_edge.FLAG_BY_PREFIX + halt.HAND_PLACED_BY)

    def test_stop_flag_and_gate_stop_first_wins(self):
        """関所の stop と STOP が同じ edge に在る → 関所の答えが先に盤面に入り、STOP の理由は trace だけ、Reject を出さない"""
        self.planned()
        halt.place(self.board, "札の理由", "alice")
        got = self.edge("fix", gate={"decision": "stop", "text": "関所の理由"})
        self.assertEqual((got["stop"], got["why"]), (True, "関所の理由"))
        st = self.state()
        self.assertEqual((st["halted"]["by"], st["halted"]["reason"]), ("answer", "関所の理由"))
        self.assertNotIn("stop", st)
        rows = trace_rows(self.board, line_edge.AFTER_HALT_OP)
        self.assertEqual([(r["reason"], r["by"], r["at"]) for r in rows], [("札の理由", "alice", "fix")])

    def test_stop_flag_after_continue_still_stops(self):
        """関所の continue と STOP が同じ edge に在る → 答えを入れてから札で止める"""
        self.planned()
        halt.place(self.board, "札の理由", "alice")
        got = self.edge("fix", gate={"decision": "continue", "text": "x"})
        self.assertEqual((got["stop"], got["go"]), (True, False))
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(b.record["process"]["human_items"][-1]["note"], "x")
        self.assertEqual(b.state["stop"]["reason"], "札の理由")

    def test_stop_flag_after_halt_goes_to_trace(self):
        """止めた盤面で STOP が在る → b.stop を呼ばず trace に 1 行（呼び直しても 1 行）、stop True"""
        self.judged()
        entry.open_board(self.board).stop("先に止めた", by="works:test")
        halt.place(self.board, "後から置いた", "bob")
        with mock.patch.object(DiskBoard, "stop", side_effect=AssertionError("止めた盤面に b.stop を呼んだ")):
            for _ in range(2):
                got = self.edge("fix")
                self.assertEqual((got["stop"], got["go"], got["why"]), (True, False, "先に止めた"))
        rows = trace_rows(self.board, line_edge.AFTER_HALT_OP)
        self.assertEqual([(r["reason"], r["by"], r["at"]) for r in rows], [("後から置いた", "bob", "fix")])

    def test_halted_board_without_flag_writes_nothing(self):
        self.judged()
        entry.open_board(self.board).stop("先に止めた", by="works:test")
        before = (self.board / "trace.jsonl").read_bytes()
        self.assertTrue(self.edge("tests")["stop"])
        self.assertEqual((self.board / "trace.jsonl").read_bytes(), before)


class GoCase(EdgeBase):
    def test_plan_file_from_outputs(self):
        """at fix の plan_file は state.outputs["p2.fix_plan"]["file"] の置き場（盤面の外の役が読めるように絶対パス）"""
        self.fixed()
        got = self.edge("fix")
        b = entry.open_board(self.board)
        self.assertEqual(got["plan_file"], str(self.board / b.state["outputs"]["p2.fix_plan"]["file"]))
        self.assertTrue(pathlib.Path(got["plan_file"]).is_file())
        self.assertEqual(got["notes"], "clamp の上限は hi でよい")

    def test_plan_file_empty_when_plan_na(self):
        """直す物の無い判定（p2.fix_plan が条件で na）→ plan_file は空。go は盤面の ready のまま（p3.fix は機械の空の返答を
        待つ。ラインでは h-plan が h-fix より前に渡す——Task 10b）"""
        self.judged("judge_no_fix")
        got = self.edge("fix")
        self.assertEqual((got["plan_file"], got["notes"]), ("", ""))
        self.assertEqual(got["go"], "p3.fix" in entry.open_board(self.board).ready())

    def test_plan_file_round_two(self):
        """周 2 の盤面（手本 test_runaway の Run 1 の周 2 に p2.fix_plan を受けた後）でも今の周の出力の置き場（out/r2/ の下）"""
        import boardreplay as R
        with mock.patch.dict(os.environ, R.git_env()):
            rs = R.load_runs("test_runaway")["1"]
            s = next(s for s in rs if s["kind"] == "accept" and s["node"] == "p2.fix_plan"
                     and R.memory_at(rs, s["seq"], "after")["state"]["round"] == 2)
            board_dir, repo = R.restore(rs, s["seq"], "after", self.tmp / "gold")
            table = entry.load_table("darkfactory")
            R.board_from_memory(R.memory_at(rs, s["seq"], "after"), board_dir, table)
            st = json.loads((board_dir / "state.json").read_text(encoding="utf-8"))
            st["works"].update(line=table.line, table_sha=table.sha())
            (board_dir / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            got = line_edge.edge(board_dir, "fix", repo, run_id=RUN_ID, adapter_mode="", final_gate="always")
        self.assertEqual(entry.open_board(board_dir).round, 2)
        self.assertEqual(got["plan_file"], str(board_dir / "out" / "r2" / "p2.fix_plan.json"))

    def test_judgment_carried_to_later_edges(self):
        """at plan で受けた judged の judgment_file・open_units が at fix（と後ろの境の節）の返りに在る"""
        self.judged()
        judged = {"ok": True, "open_units": [UNIT_MEAN, UNIT_CLAMP], "need_fix": True,
                  "judgment_file": str(self.art / "board" / "judgment.json"), "one_shot": "直す"}
        got = self.edge("plan", judged=judged)
        self.assertEqual((got["go"], got["stop"]), (True, False))
        want = (judged["judgment_file"], json.dumps(judged["open_units"], ensure_ascii=False))
        self.assertEqual((got["judgment_file"], got["open_units"]), want)
        self.assertEqual(json.loads(entry.open_board(self.board).work(line_edge.JUDGED_FILE).read_text(encoding="utf-8")), judged)
        for at in ("gate", "fix", "tests"):
            with self.subTest(at=at):
                got = self.edge(at)
                self.assertEqual((got["judgment_file"], got["open_units"]), want)

    def test_nothing_carried_before_plan(self):
        self.judged()
        got = self.edge("fix")
        self.assertEqual((got["judgment_file"], got["open_units"]), ("", ""))

    def test_go_follows_board_ready(self):
        """線の順に進めた盤面で、各 at の go が盤面の ready の節で決まる（review → p3.delta_review、refix → p3.delta_fix、
        tests → p4.ci、mid → 今の周の p3.fix を役が出した）"""
        self.planned()
        self.assertEqual([self.edge(at)["go"] for at in ("plan", "fix", "mid", "review", "refix", "tests")], [False] * 6)
        self.fix_after_plan("")
        self.assertEqual({at: self.edge(at)["go"] for at in ("fix", "mid", "review", "refix", "tests")},
                         {"fix": False, "mid": True, "review": True, "refix": False, "tests": False})
        self.take("p3.delta_review", DELTA_REVIEW)
        self.assertEqual({at: self.edge(at)["go"] for at in ("review", "refix", "tests")},
                         {"review": False, "refix": True, "tests": False})
        self.take("p3.delta_fix", DELTA_FIX)
        self.assertEqual({at: self.edge(at)["go"] for at in ("mid", "review", "refix", "tests")},
                         {"mid": True, "review": False, "refix": False, "tests": True})

    def test_mid_not_go_after_empty_fix(self):
        """直す物の無い周で機械が空の返答を渡した（trace の by works:empty-fix）→ mid の go は False（p3.fix は done でも）"""
        self.judged("judge_no_fix")
        self.assertFalse(self.edge("mid")["go"])
        self.take("p3.fix", entry.empty_fix_reply())
        b = entry.open_board(self.board)
        line_edge.trace_empty_fix(b)
        self.assertEqual(b.node_state("p3.fix"), "done")
        self.assertFalse(self.edge("mid")["go"])
        self.assertTrue(self.edge("tests")["go"])
        rows = [r for r in trace_rows(self.board) if r.get("by") == line_edge.EMPTY_FIX_BY]
        self.assertEqual([(r["node"], r["round"]) for r in rows], [("p3.fix", b.round)])

    def test_every_at_returns_all_fields(self):
        self.judged()
        for at in line_edge.AT:
            with self.subTest(at=at):
                got = self.edge(at)
                self.assertEqual(set(got), OUT_KEYS)
                self.assertIs(got["ok"], True)
                for k in BOOL_KEYS:
                    self.assertIsInstance(got[k], bool)
                for k in OUT_KEYS - BOOL_KEYS - {"ok"}:
                    self.assertIsInstance(got[k], str)


class PlanEdgeCase(EdgeBase):
    """h-plan（計画 P1 Task 23・〔線A計〕T10b）: 判定の渡し替えと、直す物が無い周の締め"""

    def done_rows(self, nid):
        return [r for r in trace_rows(self.board, "done") if r.get("instance") == nid]

    def test_plan_goes_when_units_open(self):
        """判定のブロックの出口を h-plan に渡す → 盤面の p2.diagnose が done（判定の返答そのまま）、go True"""
        self.premised()
        judged = self.judge_exit()
        got = self.edge("plan", judged=judged)
        self.assertEqual((got["go"], got["stop"]), (True, False), got)
        b = entry.open_board(self.board)
        self.assertEqual(b.node_state("p2.diagnose"), "done")
        self.assertIn("p2.fix_plan", b.ready())
        self.assertEqual(len(self.done_rows("p2.diagnose")), 1)
        self.assertEqual(got["judgment_file"], judged["judgment_file"])

    def test_bridge_skips_when_done(self):
        """盤面に p2.diagnose が今の周に在る → 2 度受けない（読めない judgment_file でも読まない。trace の done は 1 行）"""
        self.judged()
        judged = {**self.judge_exit(), "judgment_file": str(self.tmp / "nowhere.json")}
        for _ in range(2):
            got = self.edge("plan", judged=judged)
            self.assertEqual((got["go"], got["stop"]), (True, False))
        self.assertEqual(len(self.done_rows("p2.diagnose")), 1)

    def test_bridge_rejected_stops_before_writer(self):
        """盤面の型に合わない judgment.json → stop True、state.stop.by "works:judge-bridge"、p2.fix_plan は起きない"""
        self.premised()
        got = self.edge("plan", judged=self.judge_exit(reply={"units": "壊れた"}))
        self.assertEqual((got["stop"], got["go"]), (True, False))
        st = self.state()
        self.assertEqual(st["stop"]["by"], line_edge.JUDGE_BRIDGE_BY)
        self.assertIn("盤面が判定を受けない", st["stop"]["reason"])
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual((b.node_state("p2.diagnose"), b.ready()), ("stopped", []))   # 受けずに止めた（待ちは stopped）

    def test_bridge_unreadable_or_missing_stops(self):
        """判定の出口が届かない（None）・judgment_file が読めない → 同じく by works:judge-bridge で止める（fail closed）"""
        for judged in (None, {"ok": True, "open_units": [], "need_fix": False, "judgment_file": "/nowhere/judgment.json"}):
            with self.subTest(judged=judged):
                self._tmp.cleanup()
                self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
                self.tmp = pathlib.Path(self._tmp.name)
                self.premised()
                got = self.edge("plan", judged=judged)
                self.assertEqual((got["stop"], got["go"]), (True, False))
                self.assertEqual(self.state()["stop"]["by"], line_edge.JUDGE_BRIDGE_BY)

    def test_no_fix_closes_round(self):
        """直す物の無い判定 → go False、p3.fix が空の返答で done、ready に p4.ci、trace に works:empty-fix（TA6）"""
        self.premised()
        got = self.edge("plan", judged=self.judge_exit("judge_no_fix"))
        self.assertEqual((got["go"], got["stop"]), (False, False), got)
        b = entry.open_board(self.board)
        self.assertEqual((b.node_state("p2.fix_plan"), b.node_state("p3.fix")), ("na", "done"))
        self.assertEqual(b.output_of_round("p3.fix", b.round)["changes"], [])
        self.assertIn("p4.ci", b.ready())
        rows = [r for r in trace_rows(self.board) if r.get("by") == line_edge.EMPTY_FIX_BY]
        self.assertEqual([(r["node"], r["round"]) for r in rows], [("p3.fix", b.round)])
        self.assertFalse(self.edge("mid")["go"])
        again = self.edge("plan", judged=self.judge_exit("judge_no_fix"))   # Archon の再開で呼び直しても 2 度渡さない
        self.assertEqual((again["go"], again["stop"]), (False, False))
        self.assertEqual(len(self.done_rows("p3.fix")), 1)


class JudgeEdgeCase(EdgeBase):
    """h-judge（計画 P1 Task 24・P1-R9）: 包みの確かめと、前提の実測が盤面に在るか（前提のブロックの出口の渡し替え）"""

    def test_judge_edge_returns_premises_file(self):
        """前提を受けた盤面で at judge → go True、premises_file は state.outputs["p0.premises"] の置き場（絶対パス）"""
        self.premised()
        got = self.edge("judge")
        self.assertEqual((got["go"], got["stop"]), (True, False), got)
        b = entry.open_board(self.board)
        self.assertEqual(got["premises_file"], str(self.board / b.state["outputs"]["p0.premises"]["file"]))
        self.assertTrue(pathlib.Path(got["premises_file"]).is_file())

    def test_judge_edge_bridges_premises_exit(self):
        """前提のブロックの出口（constraints_file）を盤面の p0.premises に渡す → 記録の constraints に行、ready に p2.diagnose。
        呼び直しても 2 度渡さない"""
        self.started()
        premised = self.premises_exit(linekit.reply("premises_ok"))
        for _ in range(2):
            got = self.edge("judge", premised=premised)
            self.assertEqual((got["go"], got["stop"]), (True, False), got)
        b = entry.open_board(self.board)
        self.assertEqual(b.node_state("p0.premises"), "done")
        self.assertIn("p2.diagnose", b.ready())
        self.assertEqual(len([r for r in trace_rows(self.board, "done") if r.get("instance") == "p0.premises"]), 1)
        self.assertEqual(got["premises_file"], str(self.board / b.state["outputs"]["p0.premises"]["file"]))

    def test_judge_edge_stops_without_premises(self):
        """前提を受けていない盤面・前提のブロックの出口も無い → stop True、by works:premises、判定役は起きない"""
        self.started()
        got = self.edge("judge", premised=None)
        self.assertEqual((got["stop"], got["go"]), (True, False))
        st = self.state()
        self.assertEqual(st["stop"]["by"], line_edge.PREMISES_BY)
        self.assertIn("前提の実測が盤面に無い", st["stop"]["reason"])

    def test_judge_edge_bridge_rejected_stops(self):
        """盤面が前提の出口を受けない（kind 実測に measured_output が無い）→ stop、by works:premises、文に盤面の拒否"""
        self.started()
        bad = {"constraints": [{"text": "x", "measured_how": "y", "kind": "実測"}]}
        got = self.edge("judge", premised=self.premises_exit(bad))
        self.assertEqual((got["stop"], got["go"]), (True, False))
        st = self.state()
        self.assertEqual(st["stop"]["by"], line_edge.PREMISES_BY)
        self.assertIn("measured_output", st["stop"]["reason"])

    def test_adapter_missing_stops_at_judge(self):
        """この run の起動が包みの起動の記録に無い・adapter "" → at judge で stop（by works:adapter）"""
        self.premised()
        got = self.edge("judge", adapter_mode="")
        self.assertEqual((got["stop"], got["go"]), (True, False))
        st = self.state()
        self.assertEqual(st["stop"]["by"], line_edge.ADAPTER_BY)
        self.assertIn("包みが通っていない", st["stop"]["reason"])
        self.assertIn(RUN_ID, st["stop"]["reason"])

    def test_adapter_seen_passes(self):
        self.premised()
        self.launched()
        got = self.edge("judge", adapter_mode="")
        self.assertEqual((got["go"], got["stop"]), (True, False), got)

    def test_adapter_optional_passes(self):
        """同じく起動の行が無くても adapter "optional"（包み無しで回す run）→ stop False"""
        self.premised()
        got = self.edge("judge", adapter_mode="optional")
        self.assertEqual((got["go"], got["stop"]), (True, False))

    def test_plan_does_not_check_adapter(self):
        """包みの確かめは h-judge だけ（P1-R9）: 起動の行が無く adapter "" でも at plan は止めない"""
        self.judged()
        got = self.edge("plan", adapter_mode="", judged=self.judge_exit())
        self.assertEqual((got["go"], got["stop"]), (True, False))

    def test_premised_only_at_judge(self):
        self.premised()
        with self.assertRaises(BoardGap):
            self.edge("plan", premised={"constraints_file": "x"})
        with self.assertRaises(BoardGap):
            self.edge("judge", premised="x")
        with self.assertRaises(BoardGap):
            self.edge("judge", adapter_mode="sometimes")


class ReadyCase(unittest.TestCase):
    """DiskBoard.ready: 開いただけの盤面の ready（書かない）。表で explicit の機械の節（壁）は settle の記憶にしか無いので、
    開き直した入れ物の Progress では落ちる——ready() は graph の順で最初の待ちで依存が済んだ壁を足す。線 A の表には
    explicit の節が無い（下の test_line_a_table_has_no_explicit）が、境の節は ready() で決めるので、壁の在る表でも同じ集合になる"""

    def setUp(self):
        import boardreplay as R
        self.R = R
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        self.addCleanup(setattr, engine_util, "GIT_CWD", engine_util.GIT_CWD)
        env = mock.patch.dict(os.environ, R.git_env())
        env.start()
        self.addCleanup(env.stop)

    def test_line_a_table_has_no_explicit(self):
        table = entry.load_table("darkfactory")
        self.assertEqual([n for n, e in table.nodes.items() if e.run == "explicit"], [])

    def test_ready_keeps_explicit_wall_after_reopen(self):
        R = self.R
        base = NodeTable.everything(graph_expanded(), GRAPH_SHA)
        nodes = dict(base.nodes)
        nodes["p4.record"] = dataclasses.replace(nodes["p4.record"], run="explicit")
        table = dataclasses.replace(base, nodes=nodes)
        rs = R.load_runs("test_converges")["1"]
        s = next(s for s in rs if s["kind"] == "builtin" and s["node"] == "p4.record")
        board_dir, _ = R.restore(rs, s["seq"], "before", self.tmp)
        b = R.board_from_memory(R.memory_at(rs, s["seq"], "before"), board_dir, table)
        p = b.settle()
        self.assertIn("p4.record", p["ready"])
        again = DiskBoard.open(board_dir, table=table)
        state_before = (board_dir / "state.json").read_bytes()
        self.assertNotIn("p4.record", again._progress([])["ready"])   # 開き直した入れ物の Progress では落ちる（直す物）
        self.assertEqual(again.ready(), p["ready"])
        self.assertEqual((board_dir / "state.json").read_bytes(), state_before)   # 書かない

    def test_ready_empty_while_asking_or_halted(self):
        R = self.R
        table = entry.load_table("darkfactory")
        rs = R.load_runs("test_human_gate")["1"]
        s = next(s for s in rs if s["kind"] == "builtin" and s["node"] == "p2.human_gate")
        board_dir, _ = R.restore(rs, s["seq"], "after", self.tmp)
        b = R.board_from_memory(R.memory_at(rs, s["seq"], "after"), board_dir, table)
        self.assertTrue(b.state.get("pending_human"))
        self.assertEqual(b.ready(), [])


class EdgeScriptCase(EdgeBase):
    def run_edge(self, **env):
        base = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        base.update({"INPUTS_AT": "fix", "INPUTS_JUDGED": "null", "INPUTS_PREMISED": "null", "INPUTS_GATE": "null",
                     "INPUTS_TESTS": "null", "INPUTS_ADAPTER": "", "INPUTS_FINAL_GATE": "always", "ARTIFACTS_DIR": str(self.art),
                     "WORKFLOW_ID": RUN_ID, "PYTHONDONTWRITEBYTECODE": "1"})
        base.update(env)
        base = {k: v for k, v in base.items() if v is not None}
        return subprocess.run([sys.executable, str(SCRIPT)], cwd=self.repo, env=base, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)

    def test_edge_script_null_strings(self):
        """edge.py を子で起こし、INPUTS_GATE="null" → None として扱う（answer を呼ばない）、1 行で 0。欠け・崩れは 2"""
        self.planned()
        r = self.run_edge()
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        got = json.loads(lines[0])
        self.assertEqual(set(got), OUT_KEYS)
        self.assertEqual((got["go"], got["stop"]), (False, False))
        self.assertEqual(self.state()["pending_human"]["node"], "p2.human_gate")
        # 答えを JSON で渡す（Archon の関所の出口）→ continue を盤面に入れる
        r = self.run_edge(INPUTS_GATE=json.dumps({"decision": "continue", "text": ODD_NOTE}, ensure_ascii=False))
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual((got["go"], got["notes"]), (True, ODD_NOTE))
        # 欠け・崩れ・盤面の誤り: 2（標準出力は空・標準エラーに 1 行）
        for env in ({"INPUTS_TESTS": None}, {"INPUTS_FINAL_GATE": "sometimes"}, {"ARTIFACTS_DIR": ""}, {"WORKFLOW_ID": None}, {"INPUTS_GATE": "{壊れた"},
                    {"INPUTS_GATE": "[1]"}, {"INPUTS_AT": "nowhere"}, {"INPUTS_AT": "null"},
                    {"ARTIFACTS_DIR": str(self.tmp / "nowhere")}):
            with self.subTest(env=env):
                r = self.run_edge(**env)
                self.assertEqual((r.returncode, r.stdout), (2, ""))
                self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertFalse([*CORE.rglob("__pycache__")])
        self.assertFalse([*(ROOT / "darkfactory").rglob("__pycache__")])

    def test_edge_script_inputs_constant(self):
        """edge.py の INPUTS の組（Task 17 の配線の試験が YAML の with: の鍵と突き合わせる）"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("_works_edge_script", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.INPUTS, ("INPUTS_AT", "INPUTS_JUDGED", "INPUTS_PREMISED", "INPUTS_GATE", "INPUTS_TESTS",
                                      "INPUTS_ADAPTER", "INPUTS_FINAL_GATE"))


if __name__ == "__main__":
    unittest.main()
