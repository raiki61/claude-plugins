"""境の節の芯（darkfactory/lib/line_edge.py の edge・gate_text・darkfactory/scripts/edge.py）の検査（線 A の仕様 2 節・
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
import accept  # noqa: E402
import converge  # noqa: E402
import deltamarks  # noqa: E402
import design  # noqa: E402
import entry  # noqa: E402
import gatemarks  # noqa: E402
import halt  # noqa: E402
import line_edge  # noqa: E402
import linekit  # noqa: E402
import report  # noqa: E402
import scopes  # noqa: E402
import protect  # noqa: E402

SCRIPT = ROOT / "darkfactory" / "scripts" / "edge.py"
RUN_ID = "run-7"
OUT_KEYS = {"ok", "stop", "go", "ask", "gate_text", "judgment_file", "open_units", "plan_file", "notes", "notes_file", "why", "gate_file",
            "premises_file",
            "pr_go", "premises_go", "purpose_go", "mat_go",
            "structure_units_file", "ripple_file", "verify_file"}
BOOL_KEYS = {"stop", "go", "ask", "pr_go", "premises_go", "purpose_go", "mat_go"}
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
                "checks": [{"key": FACE, "closed": True, "why": "差分で clamp の上限の枝が hi を返す形になり、人の答えどおり"}],
                # 準拠と品質の 2 判定の欄（deltamarks）。修正案の欄を控えない盤面なので準拠は not_applicable、穴は準拠に結ばないので品質は fail
                "compliance": {"verdict": "not_applicable", "items": [], "read": "修正案の works の欄の控えが無い run なので、照らす承認済みの項目は無い。差分の stats.py を読んだ"},
                "quality": {"verdict": "fail", "why": "faces に挙げた穴は修正案の項目への準拠の外の品質の穴で、準拠の行には結ばない"}}
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
        """役の返答を盤面へ直に渡す（entry.take）。1 回目の差分の審査は、受け付け（refix.accept_review）と同じく 2 判定の欄を
        外した返答を渡す（写しの型は欄を持たない）"""
        b = entry.open_board(self.board)
        b.mark_launched(nid, pending_inst(b, nid).get("attempts", 1))
        if nid in deltamarks.NODES:
            reply = deltamarks.split(reply)[0]
        got = entry.take(self.board, nid, reply, self.repo)
        self.assertTrue(got["ok"], got)
        return got

    def started(self):
        """start の後の盤面（p0.premises が待つ）。種は remote を持たない（forge の無い run）ので、並行 PR の節は機械が条件外にし
        （任せ先の役を起こさない）、渡す物は無い"""
        self.repo = linekit.seed_repo(self.tmp / "repo", declared=True)
        req = self.tmp / "req" / "request.json"
        req.parent.mkdir(parents=True)
        req.write_text((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.art = self.tmp / "art"
        self.board = self.art / "board"
        raw = {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "final_gate": "", "adapter": "", "policy_md": ""}
        entry.start(self.board, self.repo, raw, run_id=RUN_ID)
        self.assertEqual(entry.open_board(self.board).node_state("p0.parallel_pr"), "na")

    def premised(self):
        """前提の役と目的の文まで受けた盤面（p2.diagnose が待つ）"""
        self.started()
        self.take("p0.premises", {"constraints": []})
        linekit.pre_judge(self.board, self.repo)

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
        """plan_review_regression を受けた盤面 → ask True、gate_text に項目と答えの行（answer.line）、b.work("gate.md") に同じ文"""
        self.assertTrue(self.planned()["asking"])
        got = self.edge("gate")
        self.assertEqual(set(got), OUT_KEYS)
        self.assertEqual((got["ok"], got["stop"], got["ask"]), (True, False, True))
        text = got["gate_text"]
        self.assertIn(f"事前審査の穴 [regression] {FACE}", text)
        self.assertIn(line_edge.answer.line(RUN_ID, "continue", "<通す範囲と条件>"), text)
        self.assertIn(line_edge.answer.line(RUN_ID, "stop", "<理由>"), text)
        self.assertNotIn("archon workflow", text)   # PATH に無い archon を直に打つ行は書かない
        b = entry.open_board(self.board)
        self.assertEqual(b.work(line_edge.GATE_FILE).read_text(encoding="utf-8"), text)
        self.assertEqual(text, line_edge.gate_text(b.state["pending_human"], run_id=RUN_ID))
        # 関所の文言は短い定型とこのパスだけを載せる（文そのものは Archon の置き換えに通さない。P1 Task 29 の持ち越し 2）
        self.assertEqual(got["gate_file"], str(b.work(line_edge.GATE_FILE)))

    def test_gate_not_asking_leaves_closed(self):
        """問いの無い盤面（穴の無い事前審査）→ ask False・gate_text 空・gate.md を書かない"""
        self.planned(review=CLEAN_REVIEW)
        got = self.edge("gate")
        self.assertEqual((got["ask"], got["gate_text"], got["stop"]), (False, "", False))
        self.assertFalse(entry.open_board(self.board).work(line_edge.GATE_FILE).exists())

    def test_gate_text_without_run_id(self):
        asking = {"node": "p2.human_gate", "kinds": ["policy"], "question": "問い", "items": ["一"]}
        with mock.patch.dict(os.environ, {"WORKS_ANSWER_CMD": ""}):
            text = line_edge.gate_text(asking)   # 殻の外で回した run: 打つ前に置き換える穴で書く
        self.assertIn(f'{line_edge.answer.HOLE} <id> continue "<通す範囲と条件>"', text)
        self.assertIn(f'{line_edge.answer.HOLE} <id> stop "<理由>"', text)
        self.assertNotIn("archon workflow", text)
        with mock.patch.dict(os.environ, {"WORKS_ANSWER_CMD": "sh /plug/dev/use.sh answer /repo"}):
            text = line_edge.gate_text(asking, run_id=RUN_ID)   # 起動の殻が置いた頭で、そのまま打てる行
        self.assertIn(f'sh /plug/dev/use.sh answer /repo {RUN_ID} continue "<通す範囲と条件>"', text)
        self.assertIn(f'sh /plug/dev/use.sh answer /repo {RUN_ID} stop "<理由>"', text)
        self.assertNotIn("archon workflow", text)
        self.assertIn("- 一", text)
        with self.assertRaises(TypeError):
            line_edge.gate_text("問い")

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
        self.assertEqual((got["go"], got["notes"], got["notes_file"]), (True, "", ""))
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
        # 修正役へはファイルのパスで届く（R44。with: に文を貼らない）。ファイルの中身も 1 バイトも同じ
        self.assertEqual(pathlib.Path(got["notes_file"]).read_bytes(), ODD_NOTE.encode("utf-8"))
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
                 ("final", {"tests": "green"}), ("plan", {"judged": "x"}),
                 ("replan", {"gate": {"decision": "continue"}}), ("regate", {"gate": {"decision": "continue"}}),
                 ("refit", {"gate": {"decision": "maybe"}}), ("refit", {"tests": {"ok": True}})]
        for at, kw in cases:
            with self.subTest(at=at, kw=kw):
                with self.assertRaises(BoardGap):
                    self.edge(at, **kw)


class FinalGateCase(EdgeBase):
    """最後の人の関所（計画 P1 Task 26）。h-final が開くかと文、h-eyes が答えを受ける"""
    GREEN = {"ok": True, "green": True, "log": "/logs/final.log", "suites": [], "by": "engine"}

    def closed(self):
        """直す物の無い周を最後のテストと独立の目まで回し、周を締めた盤面（halted.by stop_after_round）。返りは最後のテストの出口"""
        self.premised()
        self.edge("plan", judged=self.judge_exit("judge_no_fix"))
        b = entry.open_board(self.board)
        ci = entry.run_ci(b, "p4.ci", test_cmd="")
        b.settle()
        linekit.close_eyes(self.board, self.repo)   # 独立の目（R1〜R4）の後に周が締まる（計画 P1 Task 33）
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
                     line_edge.answer.line(RUN_ID, "continue", "<一言>"), line_edge.answer.line(RUN_ID, "stop", "<理由>")):
            self.assertIn(want, text)
        self.assertNotIn("archon workflow", text)
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(b.work(line_edge.FINAL_GATE_FILE).read_text(encoding="utf-8"), text)
        self.assertEqual(got["gate_file"], str(b.work(line_edge.FINAL_GATE_FILE)))

    def test_final_gate_starts_with_three_lines(self):
        """最後の関所の文は冒頭 3 行（起きたこと・決めてほしいこと・推し）で始まり、今の中身（テスト・ログ・作業ツリー・答え方）は
        その後ろに残る。記録に推しが無ければ機械は推さない"""
        tests = self.closed()
        text = self.edge("final", tests=tests, final_gate="always")["gate_text"]
        lines = text.splitlines()
        self.assertEqual([x.split(": ", 1)[0] + ": " for x in lines[:3]], [gatemarks.HAPPENED, gatemarks.DECIDE, gatemarks.PUSH])
        self.assertIn("テストは緑", lines[0])
        self.assertEqual(lines[2], gatemarks.PUSH + gatemarks.NO_PUSH)
        rest = "\n".join(lines[3:])
        for want in (tests["log"], str(self.repo), "差分の審査の穴: 0 件", line_edge.answer.line(RUN_ID, "continue", "<一言>")):
            self.assertIn(want, rest)

    def test_final_text_lists_converge_lines(self):
        """事前審査の壁打ちの往復（converge.lines）は最後の関所の文に並ぶ。頭の行に「- 」を足し、往復ごとの行は自分の
        「  - 」のまま（「-   - 」と重ねない）"""
        tests = self.closed()
        b = entry.open_board(self.board, allow_halted=True)
        face = {"key": "a-key-001", "kind": "regression", "where": "stats.py", "why": "穴", "severity": "block"}
        for _ in range(2):
            converge.record_pass(b, {"faces": [face]}, resolved=[], fence=9, files={})
        text = self.edge("final", tests=tests, final_gate="always")["gate_text"]
        lines = text.splitlines()
        self.assertTrue(any(x.startswith("- 事前審査の壁打ち: ") for x in lines), text)
        self.assertFalse(any(x.startswith("-   - ") for x in lines), text)
        for x in converge.lines(b)[1:]:
            self.assertIn(x, lines)

    def test_final_gate_words_match_entry(self):
        """ラインの入力 final_gate の語は、start（entry.check_inputs）が受ける語と境の節が読む語で同じ（C18。mid_gate は無い）"""
        self.assertEqual(entry.FINAL_GATES, line_edge.FINAL_GATES)
        self.assertFalse(hasattr(entry, "MID_GATES"))

    def test_final_default_is_always(self):
        tests = self.closed()
        self.assertTrue(self.edge("final", tests=tests, final_gate="")["ask"])

    def test_final_when_needed_green_skips(self):
        """when_needed・緑・問い無し・異議無し → ask False、文を書かない"""
        tests = self.closed()
        got = self.edge("final", tests=tests, final_gate="when_needed")
        self.assertEqual((got["ask"], got["gate_text"], got["stop"]), (False, "", False))
        self.assertFalse(entry.open_board(self.board, allow_halted=True).work(line_edge.FINAL_GATE_FILE).exists())

    def test_final_protected_only_red_skips(self):
        """protected_only・赤か走れなかった・走らなかった・守りのファイルに触れていない → 開かない"""
        tests = self.closed()
        for exit_ in ({**tests, "green": False}, {"ok": False, "green": False, "log": "", "reason": "宣言が読めない"}, None):
            with self.subTest(exit_=exit_):
                self.assertFalse(self.edge("final", tests=exit_, final_gate="protected_only").get("ask"))

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

    def node(self, path: str, block: str):
        """Archon の script の節として盤面を開く文脈（節の居場所と、起こされたスクリプトの場所）"""
        return mock.patch.dict(os.environ, {"ARCHON_NODE_EXECUTION": json.dumps({"runId": "r", "path": path})}), \
            mock.patch.object(sys, "argv", [str(ROOT / block / "scripts" / "x.py")])

    def test_scope_breach_after_round_closed_does_not_open_final_gate(self):
        """周を締めた盤面（b.stop が拒む）で独立の目の窓が宣言の外に書いた → 次に開いた境の節 h-final が照らしで止めた事実
        （trace の stop_after_round_end・by works:scope-check）を止まりと読み、最後の関所を開かずその理由で止まる。報告も同じ理由を名指す"""
        tests = self.closed()
        env, argv = self.node("eyeing__eyes-collect", "blk-eyes")
        with env, argv:
            entry.open_board(self.board, allow_halted=True)
        (self.board / "r1" / "stray.json").write_text("{}", encoding="utf-8")
        env, argv = self.node("h-final", "darkfactory")
        with env, argv:
            got = self.edge("final", tests=tests, final_gate="always")
        self.assertEqual((got["stop"], got["ask"], got["go"]), (True, False, False), got)
        self.assertIn("r1/stray.json", got["why"])
        self.assertEqual(self.state()["halted"]["by"], line_edge.ENDED_BY)
        b = entry.open_board(self.board, allow_halted=True)
        self.assertFalse(b.work(line_edge.FINAL_GATE_FILE).exists(), "最後の関所の文を書かない（開かない）")
        by, reason, _ = report._stop_info(b)
        self.assertEqual(by, scopes.SCOPE_CHECK_BY)
        self.assertIn("r1/stray.json", reason)
        self.assertTrue(self.edge("eyes")["stop"], "後の境の節も止まりと読む")

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


class ProtectedGateCase(EdgeBase):
    """守りのファイル（works/.shared/core/protected.json の一覧。ASF の floor.json に倣う）を run が触ったら、最後の人の関所を
    final_gate が when_needed でも必ず開き、文の冒頭 3 行の 1 行目で「守りのファイルを触った」と名指し、3 行の直後の最初の節に
    ファイル・行数・規則を並べ、盤面の process.human_items にも 1 行（報告の冒頭 1 に出る）。通すのは人の continue だけ。関所が開かなかった答え（null）は止める。
    試験の一覧は種の stats.py を守る物に差し替える（本物の一覧は test_protect が見る）"""

    def setUp(self):
        super().setUp()
        doc = {"rules": [{"id": "seed-core", "glob": "stats.py", "why": "種の芯（試験の一覧）"}]}
        path = self.tmp / "protected.json"
        path.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        patch = mock.patch.object(protect, "MANIFEST", path)
        patch.start()
        self.addCleanup(patch.stop)

    closed = FinalGateCase.closed   # 直す物の無い周を締めた盤面（FinalGateCase の試験は継がない）

    def touched_closed(self):
        tests = self.closed()
        (self.repo / "stats.py").write_text("x = 1\n", encoding="utf-8")
        return tests

    def protected_rows(self):
        b = entry.open_board(self.board, allow_halted=True)
        return [h for h in b.record["process"]["human_items"] if h.get("node") == line_edge.PROTECTED_BY]

    def test_protected_only_opens_just_for_protected_files(self):
        """protected_only（利用者の既定）: 守りのファイルを触った時だけ開く。赤・走れなかった・走らなかったでは開かない
        （理由は報告の冒頭に並ぶ。関所の答えは差分を当てるかを変えない）"""
        self.assertTrue(self.edge("final", tests=self.touched_closed(), final_gate="protected_only")["ask"])

    def test_touch_forces_gate_when_needed(self):
        """when_needed・緑・問い無し・異議無しでも、守りのファイルを触っていれば開き、1 行目で名指し、本文の前の節に
        ファイル・行数・規則"""
        tests = self.touched_closed()
        got = self.edge("final", tests=tests, final_gate="when_needed")
        self.assertTrue(got["ask"])
        head = got["gate_text"].split("最後の人の関所")[0]
        self.assertIn(line_edge.PROTECTED_HEAD, head.splitlines()[0])
        for want in ("stats.py", "+1 −", "規則 seed-core（stats.py）", "種の芯（試験の一覧）"):
            self.assertIn(want, head)
        self.assertLess(got["gate_text"].index(line_edge.PROTECTED_HEAD), got["gate_text"].index("最後の人の関所"))
        rows = self.protected_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["kinds"], rows[0]["answer"], rows[0]["round"]), ([line_edge.PROTECTED_KIND], None, 1))
        self.assertTrue(any("stats.py" in a for a in rows[0]["asked"]))

    def test_touch_on_top_with_always(self):
        tests = self.touched_closed()
        text = self.edge("final", tests=tests, final_gate="always")["gate_text"]
        lines = text.splitlines()
        self.assertTrue(any(line_edge.PROTECTED_HEAD in x for x in lines[:3])
                        and next(x for x in lines if x.startswith("## ")).startswith("## " + line_edge.PROTECTED_HEAD),
                        text[:300])

    def test_touch_named_in_three_lines_and_first_heading(self):
        """守りのファイルを触った run の最後の関所の文: 1 行目が「起きたこと: 」で守りのファイルを名指し、2・3 行目が決めてほしい
        こと・推し、最初の見出しが守りのファイルの節（持ち主 2026-09-29: 冒頭 3 行の直後に置く）"""
        tests = self.touched_closed()
        lines = self.edge("final", tests=tests, final_gate="always")["gate_text"].splitlines()
        self.assertTrue(lines[0].startswith(gatemarks.HAPPENED), lines[0])
        self.assertIn(line_edge.PROTECTED_HEAD, lines[0])
        self.assertTrue(lines[1].startswith(gatemarks.DECIDE), lines[1])
        self.assertTrue(lines[2].startswith(gatemarks.PUSH), lines[2])
        self.assertTrue(next(x for x in lines if x.startswith("## ")).startswith("## " + line_edge.PROTECTED_HEAD))

    def test_untouched_is_unchanged(self):
        """触っていなければ今までどおり: when_needed・緑は開かず、盤面の行も無い。always の文に節は無い"""
        tests = self.closed()
        got = self.edge("final", tests=tests, final_gate="when_needed")
        self.assertEqual((got["ask"], got["gate_text"]), (False, ""))
        self.assertEqual(self.protected_rows(), [])
        self.assertNotIn(line_edge.PROTECTED_HEAD, self.edge("final", tests=tests, final_gate="always")["gate_text"])
        self.assertEqual(self.protected_rows(), [])

    def test_recall_does_not_add_rows(self):
        """Archon の再開で h-final を呼び直しても行は 1 本"""
        tests = self.touched_closed()
        for _ in range(2):
            self.edge("final", tests=tests, final_gate="when_needed")
        self.assertEqual(len(self.protected_rows()), 1)

    def test_continue_passes_and_marks_row(self):
        tests = self.touched_closed()
        self.edge("final", tests=tests, final_gate="when_needed")
        got = self.edge("eyes", gate={"decision": "continue", "text": "試験の直しは正しい"})
        self.assertEqual(got["stop"], False)
        self.assertEqual(self.protected_rows()[0]["answer"], "continue")

    def test_stop_keeps_report(self):
        """stop は止める（報告の節は trigger_rule で走る）。盤面の行の答えは stop・最後の関所の答えのファイルも残る"""
        tests = self.touched_closed()
        self.edge("final", tests=tests, final_gate="when_needed")
        got = self.edge("eyes", gate={"decision": "stop", "text": "試験を緩めている"})
        self.assertEqual((got["stop"], got["why"]), (True, "試験を緩めている"))
        self.assertEqual(self.protected_rows()[0]["answer"], "stop")
        b = entry.open_board(self.board, allow_halted=True)
        self.assertTrue(b.work(line_edge.FINAL_GATE_ANSWER).is_file())

    def test_no_gate_answer_stops(self):
        """守りのファイルを触ったのに最後の関所の答えが来ない（null。関所が開かなかった）→ 止める（fail closed）"""
        tests = self.touched_closed()
        self.edge("final", tests=tests, final_gate="when_needed")
        got = self.edge("eyes", gate=None)
        self.assertTrue(got["stop"])
        self.assertIn(line_edge.PROTECTED_HEAD, got["why"])
        rows = trace_rows(self.board, line_edge.STOP_AFTER_END_OP)
        self.assertEqual([r["by"] for r in rows], [line_edge.PROTECTED_BY])

    def test_final_skipped_still_stops(self):
        """独立の目のブロックが落ちて h-final が飛ばされた（行がまだ無い）run でも、h-eyes が確かめ直して止める"""
        self.touched_closed()
        got = self.edge("eyes", gate=None)
        self.assertTrue(got["stop"])
        self.assertIn(line_edge.PROTECTED_HEAD, got["why"])
        self.assertEqual(len(self.protected_rows()), 1)

    def test_broken_manifest_forces_gate(self):
        """一覧が読めない時は確かめられなかったと頭に書いて開く（黙って空にしない）"""
        tests = self.closed()
        protect.MANIFEST.write_text("{", encoding="utf-8")
        got = self.edge("final", tests=tests, final_gate="when_needed")
        self.assertTrue(got["ask"])
        self.assertIn(line_edge.PROTECTED_UNKNOWN, got["gate_text"].splitlines()[0])

    def test_real_manifest_protects_itself(self):
        """本物の一覧で: run の作業ツリーに一覧と同じパスのファイルを置けば、規則 manifest で関所が開く"""
        tests = self.closed()
        with mock.patch.object(protect, "MANIFEST", CORE / "protected.json"):
            target = self.repo / "works" / ".shared" / "core" / "protected.json"
            target.parent.mkdir(parents=True)
            target.write_text("{}\n", encoding="utf-8")
            got = self.edge("final", tests=tests, final_gate="when_needed")
        self.assertTrue(got["ask"])
        self.assertIn("works/.shared/core/protected.json（+1 −0）: 規則 manifest", got["gate_text"])


class EntryMidCase(EdgeBase):
    def test_entry_edge_flags(self):
        """start の後の盤面（ready に p0.parallel_pr・p0.premises）→ go・pr_go・premises_go True、purpose_go False。
        origin は GitHub の形で偽の gh が交差を返す（並行 PR が任せ先の役に落ちる run）"""
        self.repo = linekit.seed_repo(self.tmp / "repo", declared=True)
        env = mock.patch.dict("os.environ", {"PATH": linekit.github_crossing(self.repo, self.tmp)})
        env.start()
        self.addCleanup(env.stop)
        req = self.tmp / "req" / "request.json"
        req.parent.mkdir(parents=True)
        req.write_text((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.art = self.tmp / "art"
        self.board = self.art / "board"
        raw = {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "final_gate": "", "adapter": "", "policy_md": ""}
        entry.start(self.board, self.repo, raw, run_id=RUN_ID)
        self.assertTrue({"p0.parallel_pr", "p0.premises"} <= set(entry.open_board(self.board).ready()))
        got = self.edge("entry")
        self.assertEqual({k: got[k] for k in ("go", "pr_go", "premises_go", "purpose_go", "stop")},
                         {"go": True, "pr_go": True, "premises_go": True, "purpose_go": False, "stop": False})
        self.take("p0.parallel_pr", {k: v for k, v in linekit.reply("pr_no_conflicts").items() if k != "excluded"})
        self.take("p0.premises", {"constraints": []})
        got = self.edge("entry")
        self.assertEqual((got["pr_go"], got["premises_go"]), (False, False))

    def test_slots_do_not_go(self):
        """異議の無い修正の直後: rejudge は再審の節が待っていないので go False。eyes は目が待っていないので go False"""
        self.fixed()
        for at in ("rejudge", "eyes"):
            with self.subTest(at=at):
                got = self.edge(at)
                self.assertEqual((got["go"], got["stop"]), (False, False))


class ReplanEdgeCase(EdgeBase):
    """案の直しの 3 つの境の節（依頼 226。h-replan・h-regate・h-refit）: 修正の段で fix_plan_item に裁いた項目が無い周（今の周の
    replan.json が無い）は何もしない。関所の答えは at refit だけが受け、最後の関所の答えのファイルに書かない。中身の筋書き
    （直す・聞く・止める）は test_replan.TestLineReplay"""

    def test_nothing_to_replan(self):
        self.fixed()
        for at in ("replan", "regate", "refit"):
            with self.subTest(at=at):
                got = self.edge(at)
                self.assertEqual((got["stop"], got["go"], got["ask"]), (False, False, False))
        got = self.edge("refit", gate={"decision": "stop", "text": "止める"})   # 控えの無い周に届いた答え: 当てる項目が無い
        self.assertEqual((got["stop"], got["go"]), (False, False))
        b = entry.open_board(self.board)
        self.assertFalse(b.work(line_edge.FINAL_GATE_ANSWER).exists())
        self.assertFalse(b.work("replan.json").exists())
        self.assertIsNone(b.state.get("stop"))

    def test_gate_branches_are_named_per_at(self):
        """関所の答えを受ける境の節は at ごとに名指す（fix は policy-gate、refit は replan-gate、eyes は final-gate）"""
        self.assertEqual(line_edge.GATE_AT, ("fix", "refit", "eyes"))
        self.assertLess(line_edge.AT.index("fix"), line_edge.AT.index("replan"))
        self.assertEqual(line_edge.AT[line_edge.AT.index("replan"):line_edge.AT.index("rejudge") + 1],
                         ("replan", "regate", "refit", "rejudge"))


class RejudgeEdgeCase(EdgeBase):
    """h-rejudge（修正の後・中の検査の前。計画 P1 Task 31・rejudge 設計 23c）: 修正役が判定に異議を出した周は、盤面が待つ
    再審の節（p2.rejudge）を blk-rejudge に回す。判定役の会話を確かめられなければ役を起こさずに止める（by works:rejudge-session）。
    run 28: 異議の後に再審を回す節がラインに無く、p2.rejudge が待ったままで p4.ci が出ず、最後のテストが走らなかった"""

    def objected(self):
        """修正の返答に判定への異議（rejudge_requested）を持つ盤面（p2.rejudge が待つ）"""
        self.planned()
        entry.open_board(self.board).answer("continue", "")
        src = (self.repo / "stats.py").read_text(encoding="utf-8")
        (self.repo / "stats.py").write_text(src.replace("(len(xs) - 1)", "len(xs)").replace(
            "    if x > hi:\n        return lo", "    if x > hi:\n        return hi"), encoding="utf-8")
        self.take("p3.fix", {**fix_reply(faces=True), "rejudge_requested": "判定の clamp の単位は上限の意味の読みが違う"})
        self.assertIn("p2.rejudge", entry.open_board(self.board).ready())

    def test_rejudge_edge_go(self):
        """異議あり・判定役の会話あり → go True・stop False。確かめた会話を rejudge-session.json に"""
        import rejudge
        import rejudgekit
        self.objected()
        sid = rejudgekit.put_session(self.repo)
        got = self.edge("rejudge")
        self.assertEqual((got["go"], got["stop"]), (True, False), got)
        doc = json.loads(entry.open_board(self.board).work(rejudge.SESSION_NAME).read_text(encoding="utf-8"))
        self.assertEqual(doc["id"], sid)

    def test_rejudge_edge_stop(self):
        """異議あり・判定役の会話なし → stop True・go False、盤面は by works:rejudge-session で止まり、p2.rejudge を起こさない"""
        import rejudge
        self.objected()
        got = self.edge("rejudge")
        self.assertEqual((got["go"], got["stop"]), (False, True), got)
        self.assertIn("判定役の会話", got["why"])
        st = self.state()
        self.assertEqual(st["stop"]["by"], rejudge.STOP_BY_SESSION)
        self.assertNotIn("launched_at", entry.open_board(self.board, allow_halted=True).rd["instances"]["p2.rejudge"])

    def test_rejudge_edge_idle(self):
        """異議なし → go False・stop False（p2.rejudge は条件で na）"""
        self.fixed()
        got = self.edge("rejudge")
        self.assertEqual((got["go"], got["stop"]), (False, False), got)
        self.assertEqual(entry.open_board(self.board).node_state("p2.rejudge"), "na")

    def test_tests_wait_for_rejudge(self):
        """再審の節が待つ間は p4.ci が出ない（at tests の go False）。再審を受けると p4.ci が出て go True"""
        import rejudge
        import rejudgekit
        self.objected()
        self.take("p3.delta_review", DELTA_REVIEW)
        self.take("p3.delta_fix", DELTA_FIX)
        self.assertFalse(self.edge("tests")["go"])
        rejudgekit.put_session(self.repo)
        self.assertTrue(self.edge("rejudge")["go"])
        rejudge.snap(self.board, self.repo)
        rejudge.prep(self.board, "rejudge", self.repo)
        units = entry.open_board(self.board).record["units"]
        got = rejudge.take(self.board, "p2.rejudge", {
            "verdict": "退ける", "new_facts": "stats.py の clamp の上限の枝を読み、判定の読みどおり hi を返すのが定義だと確かめた",
            "units": [{k: u[k] for k in ("key", "label", "disposition", "reason") if k in u} for u in units]}, self.repo)
        self.assertTrue(got["ok"], got)
        self.assertTrue(self.edge("tests")["go"])


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

    def test_ripple_file_from_plan_block(self):
        """at fix の ripple_file は修正案のブロックが今の周に置いた波及の一覧 ripple.json（無ければ空。修正役が範囲の相談の前に読む）"""
        self.fixed()
        self.assertEqual(self.edge("fix")["ripple_file"], "")
        b = entry.open_board(self.board)
        b.work(line_edge.RIPPLE_FILE).write_text('{"items": [], "overlaps": [], "error": ""}\n', encoding="utf-8")
        self.assertEqual(self.edge("fix")["ripple_file"], str(b.work(line_edge.RIPPLE_FILE)))

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
        tests → p4.ci）"""
        self.planned()
        accept.write_board(self.board, design.DESIGN_FILE, linekit.reply("design_ok"))   # 修正案のブロックが独立設計も作った後
        self.assertEqual([self.edge(at)["go"] for at in ("plan", "fix", "review", "refix", "tests")], [False] * 5)
        self.fix_after_plan("")
        self.assertEqual({at: self.edge(at)["go"] for at in ("fix", "review", "refix", "tests")},
                         {"fix": False, "review": True, "refix": False, "tests": False})
        self.take("p3.delta_review", DELTA_REVIEW)
        self.assertEqual({at: self.edge(at)["go"] for at in ("review", "refix", "tests")},
                         {"review": False, "refix": True, "tests": False})
        self.take("p3.delta_fix", DELTA_FIX)
        self.assertEqual({at: self.edge(at)["go"] for at in ("review", "refix", "tests")},
                         {"review": False, "refix": False, "tests": True})

    def test_review_not_go_after_empty_fix(self):
        """直す物の無い周で機械が空の返答を渡した（trace の by works:empty-fix）→ 差分の審査は回さず、最後のテストへ"""
        self.judged("judge_no_fix")
        self.take("p3.fix", entry.empty_fix_reply())
        b = entry.open_board(self.board)
        line_edge.trace_empty_fix(b)
        self.assertEqual(b.node_state("p3.fix"), "done")
        self.assertFalse(self.edge("review")["go"])
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

    def test_plan_hands_structure_units(self):
        """go の h-plan は判定の単位を blk-structure の入力の契約 {id, paths, summary} に写したファイルを structure_units_file で返す
        （id は単位の key、paths は class_query.how.paths）"""
        self.premised()
        got = self.edge("plan", judged=self.judge_exit())
        self.assertEqual((got["go"], got["stop"]), (True, False), got)
        path = got.get("structure_units_file") or ""
        self.assertTrue(path, "h-plan が structure_units_file を返さない")
        rows = json.loads(pathlib.Path(path).read_text(encoding="utf-8"))
        self.assertEqual([(r["id"], r["paths"]) for r in rows], [(UNIT_MEAN, ["stats.py"]), (UNIT_CLAMP, ["stats.py"])])
        for r in rows:
            self.assertEqual(set(r), {"id", "paths", "summary"})
            self.assertIsInstance(r["summary"], str)

    def test_plan_hands_verify_notes(self):
        """go の h-plan は判定のブロックが今の周に置いた単位の裏取りの申し送り（judge-verify.json）を verify_file で返す（無ければ空。
        線の木の段 3）"""
        self.premised()
        self.assertEqual(self.edge("plan", judged=self.judge_exit())["verify_file"], "")
        b = entry.open_board(self.board)
        b.work(line_edge.VERIFY_FILE).write_text('{"units": [], "synergy": {"state": "unverified"}}\n', encoding="utf-8")
        self.assertEqual(self.edge("plan", judged=self.judge_exit())["verify_file"], str(b.work(line_edge.VERIFY_FILE)))

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
        """直す物の無い判定 → p3.fix が空の返答で done、ready に p4.ci、trace に works:empty-fix（TA6）。go は、修正案は無いが
        最後の R2 が要る独立設計を修正の前に作る周なので True（blk-plan は設計の輪だけを回す）"""
        self.premised()
        got = self.edge("plan", judged=self.judge_exit("judge_no_fix"))
        self.assertEqual((got["go"], got["stop"]), (True, False), got)
        b = entry.open_board(self.board)
        self.assertEqual((b.node_state("p2.fix_plan"), b.node_state("p3.fix")), ("na", "done"))
        self.assertEqual(b.output_of_round("p3.fix", b.round)["changes"], [])
        self.assertIn("p4.ci", b.ready())
        rows = [r for r in trace_rows(self.board) if r.get("by") == line_edge.EMPTY_FIX_BY]
        self.assertEqual([(r["node"], r["round"]) for r in rows], [("p3.fix", b.round)])
        again = self.edge("plan", judged=self.judge_exit("judge_no_fix"))   # Archon の再開で呼び直しても 2 度渡さない
        self.assertEqual((again["go"], again["stop"]), (True, False))
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
            self.assertEqual((got["go"], got["stop"], got["purpose_go"]), (True, False, True), got)
        b = entry.open_board(self.board)
        self.assertEqual(b.node_state("p0.premises"), "done")
        self.assertIn("p0.purpose", b.ready())   # 目的の文が待つ（purposing の when:）
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


class MatEyesEdgeCase(EdgeBase):
    """h-mat（目的の文を盤面へ渡す・P1 の目を回すか）と h-eyes（独立の目を回すか）。計画 P1 Task 32・33"""

    def before_purpose(self):
        """前提まで受けた盤面（p0.purpose が待つ）"""
        self.started()
        self.take("p0.premises", {"constraints": []})
        self.assertIn("p0.purpose", entry.open_board(self.board).ready())

    def test_mat_bridges_purpose(self):
        """目的の文のブロックが盤面の根に置いた purpose.json → 盤面の p0.purpose に渡し、go True。
        呼び直しても 2 度渡さない。P1 の目の役が表に無い版では mat_go False"""
        import purpose
        self.before_purpose()
        got = purpose.check_purpose(linekit.reply("purpose_ok"), self.board, "", self.repo)
        self.assertTrue(got["ok"], got)
        for _ in range(2):
            got = self.edge("mat")
            self.assertEqual((got["go"], got["stop"]), (True, False), got)
        b = entry.open_board(self.board)
        self.assertEqual(b.node_state("p0.purpose"), "done")
        self.assertEqual(len([r for r in trace_rows(self.board, "done") if r.get("instance") == "p0.purpose"]), 1)
        self.assertEqual(got["mat_go"], any(b.table.nodes[n].where == "blk-material" for n in b.ready()))

    def test_mat_without_purpose_stops(self):
        """目的の文が盤面の根に無い → stop、by works:purpose、判定へ進まない"""
        self.before_purpose()
        got = self.edge("mat")
        self.assertEqual((got["stop"], got["go"]), (True, False))
        st = self.state()
        self.assertEqual(st["stop"]["by"], line_edge.PURPOSE_BY)
        self.assertIn("目的の文が盤面に無い", st["stop"]["reason"])

    def test_mat_purpose_rejected_stops(self):
        """盤面が目的の文を受けない（型の外）→ stop、by works:purpose"""
        import purpose
        self.before_purpose()
        (self.board / purpose.PURPOSE_FILE).write_text(json.dumps({"purpose_text": "x"}), encoding="utf-8")
        got = self.edge("mat")
        self.assertEqual((got["stop"], got["go"]), (True, False))
        self.assertEqual(self.state()["stop"]["by"], line_edge.PURPOSE_BY)

    def test_eyes_go_when_eyes_wait(self):
        """最後のテストの後（p4.assemble が済み R の目が待つ）→ at eyes の go True。止め札の後は stop"""
        self.fixed()
        for nid, reply in (("p3.delta_review", DELTA_REVIEW), ("p3.delta_fix", DELTA_FIX)):
            self.take(nid, reply)
        b = entry.open_board(self.board)
        entry.run_ci(b, "p4.ci", test_cmd="")
        b.settle()
        b = entry.open_board(self.board)
        self.assertTrue({"r1.comment_candidates", "r2.design"} <= set(b.ready()), b.ready())
        got = self.edge("look")
        self.assertEqual((got["go"], got["stop"]), (True, False))
        halt.place(self.board, "止め札の試し", "test")
        got = self.edge("eyes")
        self.assertEqual((got["go"], got["stop"]), (False, True))


class DesignHandCase(EdgeBase):
    """修正の前に作る独立設計（core の design）: h-plan は設計を作る周に go、h-look は控えを盤面が r2.design を待った時に渡す"""

    def at_look(self):
        """直す物の無い周を最後のテストの後（p4.assemble 済み・R の目が待つ）まで回した盤面"""
        self.premised()
        self.edge("plan", judged=self.judge_exit("judge_no_fix"))
        b = entry.open_board(self.board)
        entry.run_ci(b, "p4.ci", test_cmd="")
        b.settle()
        return entry.open_board(self.board)

    def test_plan_go_until_design_is_made(self):
        """直す物の無い判定でも、設計がまだ無い周は go（blk-plan が設計だけを作る）。設計を控えた後の呼び直しは go False"""
        self.premised()
        self.assertTrue(self.edge("plan", judged=self.judge_exit("judge_no_fix"))["go"])
        accept.write_board(self.board, design.DESIGN_FILE, linekit.reply("design_ok"))
        self.assertFalse(self.edge("plan", judged=self.judge_exit("judge_no_fix"))["go"])

    def test_look_hands_design_then_compare_waits(self):
        """h-look: 盤面が r2.design を待っていれば design.json を渡し（trace に印）、r2.compare が待つ。渡した設計は控えと同じ"""
        b = self.at_look()
        self.assertEqual(b.node_state("r2.design"), "pending")
        self.assertIn("r2.design", b.ready())
        accept.write_board(self.board, design.DESIGN_FILE, linekit.reply("design_ok"))
        got = self.edge("look")
        self.assertEqual((got["go"], got["stop"]), (True, False))
        b = entry.open_board(self.board)
        self.assertEqual(b.node_state("r2.design"), "done")
        self.assertEqual(b.latest_output("r2.design"), linekit.reply("design_ok"))
        self.assertIn("r2.compare", b.ready())
        self.assertTrue(any(r.get("op") == design.HANDED_OP for r in trace_rows(self.board)))
        again = self.edge("look")   # Archon の再開で呼び直しても 2 度渡さない
        self.assertFalse(again["stop"])
        self.assertEqual(len([r for r in trace_rows(self.board) if r.get("op") == design.HANDED_OP]), 1)

    def test_look_without_design_leaves_it_waiting(self):
        """控えが無い（設計の役が諦めた）: h-look は渡さず止めない。盤面の trace に設計が無いことを残し、ほかの目は回る"""
        b = self.at_look()
        got = self.edge("look")
        self.assertEqual((got["go"], got["stop"]), (True, False))
        b = entry.open_board(self.board)
        self.assertEqual(b.node_state("r2.design"), "pending")
        rows = [r for r in trace_rows(self.board) if r.get("op") == design.MISSING_OP]
        self.assertTrue(rows and rows[-1]["reason"].startswith(design.MISSING), rows)

    def test_look_with_broken_design_does_not_crash(self):
        """控えが受け付けの後に書き換わって型に合わない: h-look は落ちず（配線の誤りにしない）、渡さずに理由を trace に残す"""
        self.at_look()
        accept.write_board(self.board, design.DESIGN_FILE, {"design": 1})
        got = self.edge("look")
        self.assertEqual((got["go"], got["stop"]), (True, False))
        self.assertEqual(entry.open_board(self.board).node_state("r2.design"), "pending")
        rows = [r for r in trace_rows(self.board) if r.get("op") == design.MISSING_OP]
        self.assertIn("型が合わない", rows[-1]["reason"])


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
        return subprocess.run([sys.executable, str(SCRIPT)], cwd=self.repo, env=base, capture_output=True, text=True, encoding="utf-8",
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


class FinalGateEyesCase(EdgeBase):
    """独立の目は最後の関所の前（本線の r4.human_gate と同じく、人は審査の結果を見てから答える）: h-final の文に R1〜R4 の判定が
    載り、目が阻害を返せば when_needed でも開く。at look は目を回すか、at eyes は関所の答えを受ける"""
    closed = FinalGateCase.closed

    def test_gate_text_lists_eye_verdicts(self):
        tests = self.closed()
        text = self.edge("final", tests=tests, final_gate="always")["gate_text"]
        self.assertIn("独立の目の判定（阻害: 無い）", text)
        for name in ("R1", "R2", "R3", "R4"):
            self.assertIn(f"（{name}）: ", text)
        self.assertIn(f'報告へ進める: {line_edge.answer.line(RUN_ID, "continue", "<一言>")}', text)

    def test_when_needed_opens_on_eye_block(self):
        """when_needed・緑・問い無し・異議無しでも、目が阻害（redesign-needed）を返していれば開き、文に阻害の R"""
        tests = self.closed()
        b = entry.open_board(self.board, allow_halted=True)
        rounded = b.dir / "rounds" / f"round-{b.round}.json"
        doc = json.loads(rounded.read_text(encoding="utf-8"))
        doc["reviews"]["R3"] = {"status": "redesign-needed", "reason": "横断で揃っていない"}
        rounded.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        got = self.edge("final", tests=tests, final_gate="when_needed")
        self.assertTrue(got["ask"])
        self.assertIn("独立の目の判定（阻害: R3）", got["gate_text"])
        self.assertIn("前提と全体の筋を見る目（R3）: 作り直しが要る（redesign-needed）——理由: 横断で揃っていない", got["gate_text"])

    def test_not_run_is_shown_but_not_a_block(self):
        """not_run は機械が書く欠け（目の判定でない）: 文には出すが、when_needed の関所を開く理由にしない"""
        tests = self.closed()
        b = entry.open_board(self.board, allow_halted=True)
        rounded = b.dir / "rounds" / f"round-{b.round}.json"
        doc = json.loads(rounded.read_text(encoding="utf-8"))
        doc["reviews"]["R1"] = {"status": "not_run", "reason": "走らせるべき周に返答が無い"}
        rounded.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        self.assertFalse(self.edge("final", tests=tests, final_gate="when_needed")["ask"])
        self.assertIn("（R1）: 走っていない（not_run）", self.edge("final", tests=tests, final_gate="always")["gate_text"])

    def test_look_does_not_take_gate(self):
        """関所の答えを受けるのは at eyes（関所の後）だけ。at look（関所の前）に答えを渡すのは配線の誤り"""
        self.fixed()
        with self.assertRaises(BoardGap):
            self.edge("look", gate={"decision": "continue", "text": ""})


STRUCTURE_STATE = "structure-state.json"   # 構造の境の節が盤面の根に書く控え {status, reason, design_file, wall_s}
STRUCTURE_MISSING = "構造の目の行なしで計画した"


class FinalGateStructureCase(EdgeBase):
    """構造のブロックが落ちた周は、盤面の根の控えの印「構造の目の行なしで計画した（理由）」が最後の関所の文に出る"""
    closed = FinalGateCase.closed

    def put_state(self, status, reason=""):
        doc = {"status": status, "reason": reason, "design_file": "", "wall_s": 2.5}
        (self.board / STRUCTURE_STATE).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def test_failed_structure_is_marked_in_final_gate(self):
        tests = self.closed()
        self.put_state("failed", "構造のブロックの節が落ちた（実測の落ち）")
        text = self.edge("final", tests=tests, final_gate="always")["gate_text"]
        self.assertIn(STRUCTURE_MISSING, text)
        self.assertIn("構造のブロックの節が落ちた（実測の落ち）", text)

    def test_ok_structure_is_not_marked(self):
        tests = self.closed()
        self.put_state("failed", "落ちた")
        self.assertIn(STRUCTURE_MISSING, self.edge("final", tests=tests, final_gate="always")["gate_text"])
        self.put_state("ok")
        self.assertNotIn(STRUCTURE_MISSING, self.edge("final", tests=tests, final_gate="always")["gate_text"])


if __name__ == "__main__":
    unittest.main()
