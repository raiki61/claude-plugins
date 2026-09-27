"""境の節の芯（.shared/core/halt.py の edge・plan.py の gate_text・darkfactory/scripts/edge.py）の検査（線 A の仕様 2 節・
計画 Task 10a・裁定 TA1・TA4）。止め札の置き方そのもの（halt.place・seen・over・dev/stop.sh）は test_halt.py。

盤面は linekit の種で start → 見本の返答を entry.take で進めて作る（役の返答の前に起こした印を置く。盤面の決まり 2）。
周 2 の盤面だけは手本 test_runaway の Run 1（p2.fix_plan を周 2 に受けた手の後）から作る。
- 関所の答え（policy-gate）: 文字列 null は「開かなかった」（answer を呼ばない）。approve・continue は continue、stop・reject は
  stop（盤面は halted.by == "answer"）。一言は process.human_items に 1 バイトも変わらずに届く
- 中の関所（mid-gate）: always はいつも、when_needed は中のテストが赤か走れなかった時だけ開く。stop は b.stop（by human:mid-gate）
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
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

from board import GRAPH_SHA, BoardGap, DiskBoard, NodeTable, graph_expanded  # noqa: E402
import engine.util as engine_util  # noqa: E402  （board が写しの graphloops を sys.path に足す）
import entry  # noqa: E402
import halt  # noqa: E402
import linekit  # noqa: E402
import plan  # noqa: E402

SCRIPT = ROOT / "darkfactory" / "scripts" / "edge.py"
RUN_ID = "run-7"
OUT_KEYS = {"ok", "stop", "go", "ask", "gate_text", "judgment_file", "open_units", "plan_file", "notes", "why"}
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

    def judged(self, name="judge_ok"):
        """start → 並行 PR の任せ先・前提の役 → 判定（name の見本）を受けた盤面（p2.fix_plan が待つ）"""
        self.repo = linekit.seed_repo(self.tmp / "repo", declared=True)
        req = self.tmp / "req" / "request.json"
        req.parent.mkdir(parents=True)
        req.write_text((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.art = self.tmp / "art"
        self.board = self.art / "board"
        raw = {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "mid_gate": "", "adapter": "", "policy_md": ""}
        entry.start(self.board, self.repo, raw, run_id=RUN_ID)
        self.take("p0.parallel_pr", {k: v for k, v in linekit.reply("pr_no_conflicts").items() if k != "excluded"})
        self.take("p0.premises", {"constraints": []})
        return self.take("p2.diagnose", linekit.reply(name))

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
        kw.setdefault("mid_gate", "always")
        kw.setdefault("adapter_mode", "")
        return halt.edge(self.board, at, self.repo, run_id=RUN_ID, **kw)

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
        self.assertEqual(b.work(halt.GATE_FILE).read_text(encoding="utf-8"), text)
        self.assertEqual(text, plan.gate_text(b.state["pending_human"], run_id=RUN_ID))

    def test_gate_not_asking_leaves_closed(self):
        """問いの無い盤面（穴の無い事前審査）→ ask False・gate_text 空・gate.md を書かない"""
        self.planned(review=CLEAN_REVIEW)
        got = self.edge("gate")
        self.assertEqual((got["ask"], got["gate_text"], got["stop"]), (False, "", False))
        self.assertFalse(entry.open_board(self.board).work(halt.GATE_FILE).exists())

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
        for at in halt.AT:
            with self.subTest(at=at):
                got = self.edge(at, mid={"ok": True, "green": False, "log": "x"} if at == "midgate" else None)
                self.assertEqual((got["stop"], got["go"], got["ask"]), (True, False, False))

    def test_stop_without_text_has_default_reason(self):
        self.planned()
        got = self.edge("fix", gate={"decision": "stop", "text": "  "})
        self.assertTrue(got["stop"])
        self.assertEqual(self.state()["halted"]["by"], "answer")
        self.assertEqual(got["why"], halt.GATE_STOP_NOTE)

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
        """知らない at・知らない答えの語・形の崩れた答え・場違いの入力・知らない mid_gate は BoardGap（配線の誤り。終了コード 2）"""
        self.judged()
        cases = [("nowhere", {}), ("fix", {"gate": {"decision": "maybe"}}), ("fix", {"gate": {"text": "x"}}),
                 ("fix", {"gate": "continue"}), ("fix", {"gate": {"decision": "continue", "text": 3}}),
                 ("gate", {"gate": {"decision": "continue"}}), ("fix", {"mid": {"ok": True}}),
                 ("fix", {"judged": {"judgment_file": "x"}}), ("midgate", {"mid": {"ok": True}, "mid_gate": "sometimes"}),
                 ("midgate", {"mid": "green"}), ("plan", {"judged": "x"})]
        for at, kw in cases:
            with self.subTest(at=at, kw=kw):
                with self.assertRaises(BoardGap):
                    self.edge(at, **kw)


class MidGateCase(EdgeBase):
    def test_midgate_always_and_when_needed(self):
        """always → 緑でも ask。when_needed → 緑なら ask False、赤か ok False なら ask True、mid None → ask False"""
        self.fixed()
        log = str(self.tmp / "mid-tests.log")
        green = {"ok": True, "green": True, "log": log, "suites": [], "by": "cmd"}
        red = {**green, "green": False}
        broken = {"ok": False, "green": False, "log": log, "reason": "宣言が読めない"}
        b = entry.open_board(self.board)
        page = b.work(halt.MID_GATE_FILE)
        got = self.edge("midgate", mid=green, mid_gate="always")
        self.assertEqual((got["ask"], got["stop"], got["go"]), (True, False, False))
        text = got["gate_text"]
        for want in ("緑", log, str(self.repo), "mean の分母を len(xs) に直した", UNIT_CLAMP,
                     f"archon workflow respond {RUN_ID} continue", f"archon workflow respond {RUN_ID} stop"):
            self.assertIn(want, text)
        self.assertEqual(page.read_text(encoding="utf-8"), text)
        page.unlink()
        got = self.edge("midgate", mid=green, mid_gate="when_needed")
        self.assertEqual((got["ask"], got["gate_text"]), (False, ""))
        self.assertFalse(page.exists())
        for mid in (red, broken):
            with self.subTest(mid=mid):
                got = self.edge("midgate", mid=mid, mid_gate="when_needed")
                self.assertTrue(got["ask"])
                self.assertIn("赤" if mid["ok"] else "走れなかった", got["gate_text"])
        self.assertIn("宣言が読めない", got["gate_text"])
        for mode in ("always", "when_needed"):
            with self.subTest(mode=mode):
                self.assertFalse(self.edge("midgate", mid=None, mid_gate=mode)["ask"])

    def test_mid_gate_stop_is_human_stop(self):
        """at review・gate stop → state.stop.by == "human:mid-gate"・理由は一言。以後の edge も stop"""
        self.fixed()
        got = self.edge("review", gate={"decision": "stop", "text": "z"})
        self.assertEqual((got["stop"], got["go"], got["why"]), (True, False, "z"))
        st = self.state()
        self.assertEqual((st["stop"]["by"], st["stop"]["reason"]), (halt.MID_GATE_BY, "z"))
        self.assertTrue(self.edge("refix")["stop"])

    def test_mid_gate_reject_without_text(self):
        self.fixed()
        got = self.edge("review", gate={"decision": "reject"})
        self.assertTrue(got["stop"])
        self.assertEqual(self.state()["stop"]["reason"], halt.MID_GATE_STOP_NOTE)

    def test_mid_gate_continue_goes_to_review(self):
        """at review・gate continue → mid-gate-answer.json に {decision, text}、go は p3.delta_review の ready"""
        self.fixed()
        got = self.edge("review", gate={"decision": "approve", "text": ODD_NOTE})
        self.assertEqual((got["go"], got["stop"]), (True, False))
        doc = json.loads(entry.open_board(self.board).work(halt.MID_GATE_ANSWER).read_text(encoding="utf-8"))
        self.assertEqual(doc, {"decision": "approve", "text": ODD_NOTE})


class StopFlagCase(EdgeBase):
    def test_stop_flag_stops_at_next_edge(self):
        """STOP を置いた後の edge → stop True、state.stop の理由が STOP の理由、by は札の置き手の印、trace にどの境の節か"""
        self.judged()
        self.assertTrue(halt.place(self.board, "依頼が変わった", "alice")["ok"])
        got = self.edge("plan", judged={"ok": True, "open_units": [UNIT_MEAN], "need_fix": True,
                                        "judgment_file": "/j.json", "one_shot": "x"})
        self.assertEqual((got["stop"], got["go"], got["why"]), (True, False, "依頼が変わった"))
        st = self.state()
        self.assertEqual((st["stop"]["reason"], st["stop"]["by"]), ("依頼が変わった", halt.FLAG_BY_PREFIX + "alice"))
        rows = trace_rows(self.board, halt.FLAG_SEEN_OP)
        self.assertEqual([(r["at"], r["reason"], r["by"]) for r in rows], [("plan", "依頼が変わった", "alice")])
        for at in ("gate", "fix", "tests"):   # 以後の境の節も stop。STOP は同じ理由なので trace に積み増さない
            self.assertTrue(self.edge(at)["stop"])
        self.assertEqual(trace_rows(self.board, halt.AFTER_HALT_OP), [])

    def test_unreadable_flag_still_stops(self):
        self.judged()
        (self.board / halt.STOP_FILE).write_text("手で置いた", encoding="utf-8")
        got = self.edge("fix")
        self.assertTrue(got["stop"])
        self.assertEqual(self.state()["stop"]["by"], halt.FLAG_BY_PREFIX + halt.HAND_PLACED_BY)

    def test_stop_flag_and_gate_stop_first_wins(self):
        """関所の stop と STOP が同じ edge に在る → 関所の答えが先に盤面に入り、STOP の理由は trace だけ、Reject を出さない"""
        self.planned()
        halt.place(self.board, "札の理由", "alice")
        got = self.edge("fix", gate={"decision": "stop", "text": "関所の理由"})
        self.assertEqual((got["stop"], got["why"]), (True, "関所の理由"))
        st = self.state()
        self.assertEqual((st["halted"]["by"], st["halted"]["reason"]), ("answer", "関所の理由"))
        self.assertNotIn("stop", st)
        rows = trace_rows(self.board, halt.AFTER_HALT_OP)
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
        rows = trace_rows(self.board, halt.AFTER_HALT_OP)
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
            table = entry.load_table()
            R.board_from_memory(R.memory_at(rs, s["seq"], "after"), board_dir, table)
            st = json.loads((board_dir / "state.json").read_text(encoding="utf-8"))
            st["works"].update(line=table.line, table_sha=table.sha())
            (board_dir / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            got = halt.edge(board_dir, "fix", repo, run_id=RUN_ID, adapter_mode="", mid_gate="always")
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
        self.assertEqual(json.loads(entry.open_board(self.board).work(halt.JUDGED_FILE).read_text(encoding="utf-8")), judged)
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
        halt.trace_empty_fix(b)
        self.assertEqual(b.node_state("p3.fix"), "done")
        self.assertFalse(self.edge("mid")["go"])
        self.assertTrue(self.edge("tests")["go"])
        rows = [r for r in trace_rows(self.board) if r.get("by") == halt.EMPTY_FIX_BY]
        self.assertEqual([(r["node"], r["round"]) for r in rows], [("p3.fix", b.round)])

    def test_every_at_returns_all_fields(self):
        self.judged()
        for at in halt.AT:
            with self.subTest(at=at):
                got = self.edge(at)
                self.assertEqual(set(got), OUT_KEYS)
                self.assertIs(got["ok"], True)
                for k in ("stop", "go", "ask"):
                    self.assertIsInstance(got[k], bool)
                for k in OUT_KEYS - {"ok", "stop", "go", "ask"}:
                    self.assertIsInstance(got[k], str)


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
        table = entry.load_table()
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
        table = entry.load_table()
        rs = R.load_runs("test_human_gate")["1"]
        s = next(s for s in rs if s["kind"] == "builtin" and s["node"] == "p2.human_gate")
        board_dir, _ = R.restore(rs, s["seq"], "after", self.tmp)
        b = R.board_from_memory(R.memory_at(rs, s["seq"], "after"), board_dir, table)
        self.assertTrue(b.state.get("pending_human"))
        self.assertEqual(b.ready(), [])


class EdgeScriptCase(EdgeBase):
    def run_edge(self, **env):
        base = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        base.update({"INPUTS_AT": "fix", "INPUTS_JUDGED": "null", "INPUTS_GATE": "null", "INPUTS_MID": "null",
                     "INPUTS_ADAPTER": "", "INPUTS_MID_GATE": "always", "ARTIFACTS_DIR": str(self.art),
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
        for env in ({"INPUTS_MID": None}, {"ARTIFACTS_DIR": ""}, {"WORKFLOW_ID": None}, {"INPUTS_GATE": "{壊れた"},
                    {"INPUTS_GATE": "[1]"}, {"INPUTS_AT": "nowhere"}, {"INPUTS_AT": "null"},
                    {"ARTIFACTS_DIR": str(self.tmp / "nowhere")}):
            with self.subTest(env=env):
                r = self.run_edge(**env)
                self.assertEqual((r.returncode, r.stdout), (2, ""))
                self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertFalse([*CORE.rglob("__pycache__")])
        self.assertFalse([*(ROOT / "darkfactory").rglob("__pycache__")])

    def test_edge_script_inputs_constant(self):
        """edge.py の INPUTS の組が 6 つ（Task 17 の配線の試験が YAML の with: の鍵と突き合わせる）"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("_works_edge_script", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.INPUTS, ("INPUTS_AT", "INPUTS_JUDGED", "INPUTS_GATE", "INPUTS_MID", "INPUTS_ADAPTER",
                                      "INPUTS_MID_GATE"))


if __name__ == "__main__":
    unittest.main()
