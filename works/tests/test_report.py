"""機械の報告（.shared/core/report.py・darkfactory/scripts/report.py・dev/report.sh）の検査（P1 計画 Task 27・〔線A計〕T15）。

盤面は線 A の試験と同じ組み方（linekit の種で start → 見本の返答を entry.take で進める。役の返答の前に起こした印）で、道ごとに作る。
全部の道（修正 → 差分の審査 → 手直し → 2 回目の審査 → 最後のテスト → 周の締め）は test_blk_refix の DeltaBoardCase の
手順を続け、p4.ci は宣言（.review-checks.json）を engine が走らせる（entry.run_ci）。
最後の関所の答え・止めた口（P1 Task 26 の境の節が書く）は、その Task の名前（final-gate-answer.json・human:final-gate）で
盤面に置いて見る。版の一覧の行（Task 18・19）はこの枝に無いので試験も無い。
"""
import importlib.util
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

import accept  # noqa: E402
import adapter  # noqa: E402
from board import BoardGap, DiskBoard  # noqa: E402
import ci_role  # noqa: E402
import converge  # noqa: E402
import engine.util as engine_util  # noqa: E402
import entry  # noqa: E402
import linekit  # noqa: E402
import prcheck  # noqa: E402
import reads  # noqa: E402
import refix  # noqa: E402
import rejudge  # noqa: E402
import replan  # noqa: E402
import report  # noqa: E402
import scopes  # noqa: E402
import test_blk_refix as RF  # noqa: E402
import test_entry as TE  # noqa: E402
import hermetic  # noqa: E402
import writes  # noqa: E402
import leftovers  # noqa: E402
import lens  # noqa: E402

SCRIPT = ROOT / "darkfactory" / "scripts" / "report.py"
REPORT_SH = ROOT / "dev" / "report.sh"
EVENTS = TESTS / "events"
RUN_ID = "run-7"
ODD = 'a "b" \'c\'\n$(rm -rf /) `x` ${HOME} $ARTIFACTS_DIR 日本語の一言\t終わり'
ODD_KEY = 'stats.py clamp: "上限" の $(docstring) と ${HOME} が日本語で食い違う'
GREEN = {"ok": True, "green": True, "log": "/logs/final.log", "suites": [], "by": "engine"}
RED = {"ok": True, "green": False, "log": "/logs/final-red.log", "suites": [], "by": "engine"}
FINISH_FIXED = {"ok", "outcome", "judgment_file", "review_file", "diff_file", "faces"}
ADDED = {"report_file", "next_request_file", "tests_green", "validator_exit", "export_input"}


def judged_out(board, need_fix=True) -> dict:
    """判定のブロックの出口（blk-judge の collect）の形"""
    b = entry.open_board(board, allow_halted=True)
    return {"ok": True, "open_units": [RF.K1, RF.K2] if need_fix else [], "need_fix": need_fix,
            "judgment_file": str(b.dir / b.state["outputs"]["p2.diagnose"]["file"]), "one_shot": False}


def heads(text: str) -> dict:
    """report.md を見出し（## ）ごとの本文に"""
    out, cur = {}, None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = line
            out[cur] = []
        elif cur is not None:
            out[cur].append(line)
    return {k: "\n".join(v) for k, v in out.items()}


class ReportBase(RF.DeltaBoardCase):
    """線 A の盤面を道ごとに組む。置き場は self.art / board（$ARTIFACTS_DIR の形）"""

    def begin(self, *, board=None, declared=True, pr=None, premises=None, request=None, judge="judge_ok", **raw):
        """start → 並行 PR の任せ先・前提の役 → 判定（judge の見本）。pr は p0.parallel_pr の返答（excluded を持てば
        prcheck の受け付けで外した範囲も書く）。pr を渡せば origin を GitHub の形にして偽の gh に交差を返させ（任せ先の役の道）、
        渡さなければ種は remote を持たない forge の無い run で、並行 PR は機械が条件外にする。返りは対象リポジトリ"""
        repo = self.seed(declared=declared)
        if pr is not None:
            env = mock.patch.dict("os.environ", {"PATH": linekit.github_crossing(repo, self.tmp)})
            env.start()
            self.addCleanup(env.stop)
        self.art = self.tmp / "art"
        self.board = pathlib.Path(board) if board else self.art / "board"
        rawd = self.raw(**raw)
        if request is not None:
            TE.request_file(pathlib.Path(rawd["request"]), request)
        entry.start(self.board, repo, rawd, run_id=RUN_ID)
        if not declared:   # CI の節が任せ先の役を待つ（並行 PR と前提はその後に出る）
            return repo
        if pr is not None and "excluded" in pr:
            TE.launch(self.board, "p0.parallel_pr")
            prcheck.snapshot(self.board, repo)
            got = prcheck.take(self.board, pr, repo)
        elif pr is not None:
            TE.launch(self.board, "p0.parallel_pr")
            got = entry.take(self.board, "p0.parallel_pr", pr, repo)
        else:
            got = {"ok": entry.open_board(self.board).node_state("p0.parallel_pr") == "na"}
        self.assertTrue(got["ok"], got)
        TE.launch(self.board, "p0.premises")
        self.assertTrue(entry.take(self.board, "p0.premises", premises or TE.PREMISES_REPLY, repo)["ok"])
        linekit.pre_judge(self.board, repo)   # 目的の文（判定の前に盤面が待つ）
        if judge:
            TE.launch(self.board, "p2.diagnose")
            self.assertTrue(entry.take(self.board, "p2.diagnose", linekit.reply(judge), repo)["ok"])
        return repo

    def judged(self, name="judge_ok"):   # DeltaBoardCase が呼ぶ口（盤面の置き場は self.art / board）
        repo = self.begin(judge=name)
        return repo, None

    def to_end(self, repo):
        """p4.ci を engine で走らせ、独立の目を見本で渡して周を締める（stop_after_round の締めで halted）"""
        b = entry.open_board(self.board)
        self.assertEqual(entry.run_ci(b, "p4.ci", test_cmd="")["by"], "engine")
        b.settle()
        linekit.close_eyes(self.board, repo)
        self.assertEqual(json.loads((self.board / "state.json").read_text(encoding="utf-8"))["halted"]["by"], "stop_after_round")

    def full(self, review2="fix2_delta_review2_ok"):
        """標準の全部の道: 修正 → 審査（穴）→ 手直し → 2 回目の審査 → 最後のテスト → 周の締め"""
        repo, _ = self.refixed()
        self.assertTrue(refix.cut(self.board, 2, repo)["ok"])
        self.assertTrue(refix.accept_review(linekit.reply(review2), self.board, "", repo, n=2)["ok"])
        self.to_end(repo)
        return repo

    def no_fix(self):
        """直す物が無い判定 → 機械が p3.fix の空の返答 → 最後のテスト → 周の締め"""
        repo, _ = self.judged("judge_no_fix")
        TE.launch(self.board, "p3.fix")
        self.assertTrue(entry.take(self.board, "p3.fix", entry.empty_fix_reply(), repo)["ok"])
        self.to_end(repo)
        return repo

    def planned(self, review="plan_review_regression"):
        repo, _ = self.judged()
        for nid, reply in (("p2.fix_plan", RF.plan_reply()), ("p2.plan_review", linekit.reply(review))):
            TE.launch(self.board, nid)
            got = entry.take(self.board, nid, reply, repo)
            self.assertTrue(got["ok"], got)
        return repo, got

    def build(self, **kw):
        if "judged" not in kw:
            kw["judged"] = judged_out(self.board)
        kw.setdefault("tests", GREEN)
        kw.setdefault("start", None)
        kw.setdefault("run_id", RUN_ID)
        kw.setdefault("launches", [])
        out = report.build(self.board, **kw)
        text = pathlib.Path(out["report_file"]).read_text(encoding="utf-8")
        return out, text, heads(text)

    def stop(self, reason, by):
        entry.open_board(self.board).stop(reason, by=by)

    def without_node_env(self):
        """試験を Archon の節の中（ARCHON_NODE_EXECUTION が立つ）で回しても、scope の無い所の読みを試せるよう環境から外す"""
        env = mock.patch.dict(os.environ)
        env.start()
        self.addCleanup(env.stop)
        os.environ.pop("ARCHON_NODE_EXECUTION", None)


H1, H2, H3, H4, H5 = report.HEADINGS


# ---------------------------------------------------------------- 結末と関所
class OutcomeCase(ReportBase):
    def test_fixed_run_head_order(self):
        """標準の全部の道 → fixed、report.md の冒頭 5 節の見出しがこの順、validator_exit ∈ report_accepts"""
        self.full()
        out, text, _ = self.build()
        self.assertEqual(out["outcome"], "fixed")
        pos = [text.index(h) for h in report.HEADINGS]
        self.assertEqual(pos, sorted(pos))
        b = entry.open_board(self.board, allow_halted=True)
        self.assertIn(out["validator_exit"], report.report_accepts(b))
        self.assertTrue(out["tests_green"])

    def test_report_starts_with_three_lines(self):
        """report.md は題の直後に冒頭 3 行（起きたこと＝平易な結末と結末の語・人が決める物が無ければ次の run に渡す物の件数・推し）で
        始まり、冒頭 5 節はその後ろに今の順で残る"""
        self.full()
        out, text, _ = self.build()
        lines = [x for x in text.splitlines() if x]
        self.assertTrue(lines[0].startswith("# 報告（run "), lines[0])
        self.assertEqual(lines[1], report.gatemarks.HAPPENED + report.OUTCOME_WORDS["fixed"] + "（fixed）")
        self.assertTrue(lines[2].startswith("次の run に渡す物: "), lines[2])
        self.assertEqual(lines[3], report.gatemarks.PUSH + report.gatemarks.NO_PUSH)
        self.assertEqual(lines[4], report.HEADINGS[0])

    def test_final_result_picks_report(self):
        """出口 result: AI の報告が ok なら report-ai.md、そうでなければ（回らない・諦めた・形が違う）機械の report.md。
        機械の報告の欄は全部残り、結末は替えない。export_input の report_file も選んだ方"""
        self.full()
        machine, _, _ = self.build()
        ai = {"ok": True, "reason": "", "report_file": "/b/report-ai.md", "cold_check": {"verdict": "pass"},
              "record_invalid": False, "text_file": "x", "rejects": {"report": {"cold": 2, "format": 0, "answer": 1}}}
        got = report.final_result(machine, ai)
        self.assertEqual(got["ai_report"]["rejects"], ai["rejects"], "拒否の回数は run の最後の出口に残る（run をまたいで数える）")
        self.assertLessEqual(set(machine), set(got))
        self.assertEqual((got["report_file"], got["machine_report_file"]), ("/b/report-ai.md", machine["report_file"]))
        self.assertEqual(got["export_input"]["report_file"], "/b/report-ai.md")
        self.assertEqual(got["outcome"], machine["outcome"])
        self.assertEqual(set(got["ai_report"]), set(report.AI_REPORT_KEYS))
        for bad in (None, {**ai, "ok": False}, {"ok": True, "report_file": ""}):
            with self.subTest(bad=bad):
                got = report.final_result(machine, bad)
                self.assertEqual(got["report_file"], machine["report_file"])
                self.assertEqual(got["export_input"]["report_file"], machine["report_file"])
        with self.assertRaises(BoardGap):
            report.final_result({"ok": True}, None)

    def test_result_script(self):
        """darkfactory/scripts/result.py: 1 行の JSON。AI の出口が null・読めない字でも機械の報告を選び、読めない事実は ai_report に"""
        self.full()
        machine, _, _ = self.build()
        script = ROOT / "darkfactory" / "scripts" / "result.py"
        for ai, want in (("null", None), ("{壊れた", "読めない")):
            with self.subTest(ai=ai):
                env = hermetic.child_env(INPUTS_MACHINE=json.dumps(machine, ensure_ascii=False), INPUTS_AI=ai,
                                         PYTHONDONTWRITEBYTECODE="1")
                r = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
                self.assertEqual(r.returncode, 0, r.stderr)
                out = json.loads(r.stdout)
                self.assertEqual(out["report_file"], machine["report_file"])
                if want:
                    self.assertIn(want, out["ai_report"]["reason"])
                else:
                    self.assertIsNone(out["ai_report"])
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        r = subprocess.run([sys.executable, str(script)], env=env, capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
        self.assertEqual((r.returncode, r.stdout), (2, ""))

    def test_exit_keeps_finish_fields(self):
        """返りの鍵 ⊇ 1 本目の finish の必須の欄と足した欄、outcome ∈ OUTCOMES、export_input は書き出しの 3 つの鍵"""
        self.full()
        out, _, _ = self.build()
        self.assertLessEqual(FINISH_FIXED | ADDED, set(out))
        self.assertIn(out["outcome"], report.OUTCOMES)
        self.assertEqual(out["export_input"], {"outcome": out["outcome"], "report_file": out["report_file"],
                                               "board_dir": str(self.board)})
        self.assertTrue(pathlib.Path(out["diff_file"]).is_file())
        self.assertTrue(pathlib.Path(out["review_file"]).is_file())
        self.assertEqual(out["faces"], 1)

    def test_no_fix_run(self):
        """judge_no_fix → no_fix_needed、周の記録 rounds/round-<N>.json が在る（TA6）"""
        self.no_fix()
        out, _, _ = self.build(judged=judged_out(self.board, need_fix=False))
        self.assertEqual(out["outcome"], "no_fix_needed")
        n = json.loads((self.board / "state.json").read_text(encoding="utf-8"))["round"]
        self.assertTrue((self.board / "rounds" / f"round-{n}.json").is_file())
        self.assertNotIn("review_file", out)

    def test_validator_rejects_never_fixed(self):
        """検証器の包み（board_hook の validator_runner）が受理集合の外の exit → record_invalid、冒頭 1 に出力の末尾と痕跡"""
        self.full()
        st = json.loads((self.board / "state.json").read_text(encoding="utf-8"))
        st["git_mismatches"] = [{"node": "p3.fix", "why": "痕跡の見本"}]
        (self.board / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        fake = mock.Mock(return_value={"exit": 7, "out": "一行目\n偽の検証器: 記録が壊れている"})
        with mock.patch.object(entry, "hook_kwargs", return_value={"validator_runner": fake}):
            out, _, h = self.build()
        self.assertEqual((out["outcome"], out["validator_exit"]), ("record_invalid", 7))
        self.assertTrue(fake.called)
        self.assertIn("偽の検証器: 記録が壊れている", h[H1])
        self.assertIn("git_mismatches", h[H1])
        self.assertIn("痕跡の見本", h[H1])

    def test_round_not_closed_never_fixed(self):
        """周の記録（record_round・converge）が済んでいない盤面（止めても聞いてもいない）→ 検証器が通っても record_invalid"""
        self.fixed()
        fake = mock.Mock(return_value={"exit": 0, "out": ""})
        with mock.patch.object(entry, "hook_kwargs", return_value={"validator_runner": fake}):
            out, _, h = self.build()
        self.assertEqual(out["outcome"], "record_invalid")
        self.assertIn("済んでいない", h[H1])

    def test_settle_before_finalize_after_stop(self):
        """止め札で止めた盤面 → settle が finalize より先に走り、報告の節の待ちが片付いている（M9）、stopped_by_request"""
        self.refixed()
        self.stop("依頼が変わった", "request:alice")
        pending = [n for n in entry.open_board(self.board, allow_halted=True).nodes
                   if entry.open_board(self.board, allow_halted=True).node_state(n) == "pending"]
        self.assertTrue(pending)
        order = []
        real_settle, real_finalize = DiskBoard.settle, DiskBoard.finalize

        def settle(b, *a, **k):
            order.append("settle")
            return real_settle(b, *a, **k)

        def finalize(b, *a, **k):
            order.append("finalize")
            return real_finalize(b, *a, **k)
        with mock.patch.object(DiskBoard, "settle", settle), mock.patch.object(DiskBoard, "finalize", finalize):
            out, _, _ = self.build()
        self.assertEqual(order[:2], ["settle", "finalize"])
        self.assertEqual(out["outcome"], "stopped_by_request")
        b = entry.open_board(self.board, allow_halted=True)
        # 止めた後に残るのは報告の役の節（表で blk-report。計画 P1 Task 34）だけ。その待ちは結末を替えない
        self.assertEqual([n for n in b.nodes if b.node_state(n) == "pending"], ["report"])
        self.assertIs(out["ai_report_go"], True)

    def test_record_invalid_from_settle_is_caught(self):
        """報告の節の関所（settle の RecordInvalid。pre: finalize）は gate_record が受け、同じ検証器が受理集合の外なら
        record_invalid（fixed を出さない）。報告は書く"""
        self.fixed()
        fake = mock.Mock(return_value={"exit": 7, "out": "偽の検証器"})

        def settle(b, *a, **k):
            raise report.RecordInvalid("report", 7, "偽の検証器")
        with mock.patch.object(entry, "hook_kwargs", return_value={"validator_runner": fake}), \
                mock.patch.object(DiskBoard, "settle", settle):
            out, _, h = self.build()
        self.assertEqual((out["outcome"], out["validator_exit"]), ("record_invalid", 7))
        self.assertIs(out["ai_report_go"], False)

    def test_round_closed_emits_report_nodes(self):
        """周を締めて止めた盤面（halted.by stop_after_round）→ 機械の報告が盤面の層の口 report_after_round で報告の役の節を出す
        （R61 の B）。結末は fixed のまま、止めた事実は state.works.after_round と記録の process.halted・stop_reason に残り、
        冒頭 3 は「止めていない（周の締めの後で止めた…）」のまま。呼び直し（Archon の再開）も同じ結末・同じ待ち"""
        self.full()
        out, _, h = self.build()
        self.assertEqual(out["outcome"], "fixed")
        self.assertIs(out["ai_report_go"], True)
        st = json.loads((self.board / "state.json").read_text(encoding="utf-8"))
        self.assertNotIn("halted", st)
        self.assertEqual(st["works"][DiskBoard.AFTER_ROUND]["by"], "stop_after_round")
        b = entry.open_board(self.board)
        self.assertEqual(b.ready(), ["report"])
        self.assertEqual((b.record["process"]["stop_reason"], b.record["process"]["halted"]["by"]),
                         ("stop_after_round", "stop_after_round"))
        self.assertIn("止めていない（周の締めの後で止めた", h[H3])
        out2, _, _ = self.build()
        self.assertEqual((out2["outcome"], out2["ai_report_go"]), ("fixed", True))

    def test_rebuild_after_the_ai_report_began_keeps_its_exit(self):
        """Archon の resume は報告の節 report を毎回回し直す（always_run）。AI の報告のブロックが書き手の返答（report）を
        受けた後に落ちた run を resume しても、出口（ai_report_go を含む）は 1 度目と字で同じ: 替わると Archon が AI の報告のブロックを
        古いと数え、when: が偽になって済んだ段ごと飛ばし、AI の報告を黙って捨てる"""
        import test_blk_report as BR
        self.full()
        first, _, _ = self.build()
        self.assertIs(first["ai_report_go"], True)
        from test_blk_fix import launch
        launch(self.board, "report")
        repo = pathlib.Path(entry.open_board(self.board, allow_halted=True).state["inputs"]["cwd"])
        got = entry.take(self.board, "report", BR.golden_reply("report"), repo)
        self.assertTrue(got["ok"], got)
        self.assertNotIn("report", entry.open_board(self.board, allow_halted=True).ready())
        again, _, _ = self.build()
        self.assertEqual(again, first)

    def test_round_closed_then_human_stop_keeps_outcome(self):
        """周を締めた後の人の止め（境の節が trace に書く STOP_AFTER_END_OP・by human:final-gate）→ 報告の節を出しても
        stopped_by_human のまま"""
        self.full()
        entry.open_board(self.board, allow_halted=True).trace(report.STOP_AFTER_END_OP, at="eyes", reason=ODD,
                                                              by=report.FINAL_GATE_BY)
        out, _, h = self.build()
        self.assertEqual(out["outcome"], "stopped_by_human")
        self.assertIs(out["ai_report_go"], True)

    def test_report_after_round_only_after_round(self):
        """report_after_round は周の締めの後で止めた盤面だけ: 止めていない盤面・関所の答えで止めた盤面（周の途中）は Reject、
        盤面は替えない"""
        self.planned()
        with self.assertRaises(engine_util.Reject):
            entry.open_board(self.board).report_after_round()
        entry.open_board(self.board).answer("stop", "x")
        before = (self.board / "state.json").read_bytes()
        with self.assertRaises(engine_util.Reject):
            entry.open_board(self.board, allow_halted=True).report_after_round()
        self.assertEqual((self.board / "state.json").read_bytes(), before)
        out, _, _ = self.build()
        self.assertEqual((out["outcome"], out["ai_report_go"]), ("stopped_by_human", False))

    def test_stopped_by_request(self):
        """止め札 → stopped_by_request、冒頭 3 に理由と止めた境の節（trace の stop_flag_seen の at）"""
        self.judged()
        b = entry.open_board(self.board)
        b.trace(report.FLAG_SEEN_OP, at="plan", reason="依頼が変わった", by="alice")
        b.stop("依頼が変わった", by="request:alice")
        out, _, h = self.build()
        self.assertEqual(out["outcome"], "stopped_by_request")
        self.assertIn("依頼が変わった", h[H3])
        self.assertIn("止めた境の節: plan", h[H3])

    def test_stopped_by_human_policy_and_final(self):
        """事前審査の関所の stop（halted.by answer）と、最後の関所の stop（by human:final-gate）→ どちらも stopped_by_human、
        冒頭 1 に一言が 1 バイトも変わらずに"""
        self.planned()
        entry.open_board(self.board).answer("stop", ODD)
        out, text, h = self.build()
        self.assertEqual(out["outcome"], "stopped_by_human")
        self.assertIn(ODD, h[H1])
        self.assertIn(ODD.encode("utf-8"), pathlib.Path(out["report_file"]).read_bytes())

    def test_final_gate_stop(self):
        self.judged()
        self.stop(ODD, report.FINAL_GATE_BY)
        out, _, h = self.build()
        self.assertEqual(out["outcome"], "stopped_by_human")
        self.assertIn(f"最後の関所で止めた: 「{ODD}」", h[H1])

    def test_final_gate_answer_in_head(self):
        """最後の関所の continue（b.work(final-gate-answer.json) の {decision, text}）→ 冒頭 1 に答えと一言。結末は fixed のまま"""
        self.full()
        b = entry.open_board(self.board, allow_halted=True)
        b.work(report.FINAL_GATE_ANSWER).write_text(json.dumps({"decision": "continue", "text": ODD}, ensure_ascii=False),
                                                    encoding="utf-8")
        out, _, h = self.build()
        self.assertEqual(out["outcome"], "fixed")
        self.assertIn(f"最後の関所の答え: continue「{ODD}」", h[H1])

    def test_stopped_by_line(self):
        """包みが無い（包みを通す run で起動の記録が無い・包みの確かめで止めた）→ stopped_by_line、冒頭 4 に「包みが通っていない」"""
        self.judged()
        self.stop("包みの確かめが通らない: 包みの起動の記録が無い", ci_role.FENCE_BY)
        out, _, h = self.build()
        self.assertEqual(out["outcome"], "stopped_by_line")
        self.assertIn("包みが通っていない", h[H4])
        self.assertIn("包みの確かめで止めた: 包みの確かめが通らない", h[H4])

    def test_ci_role_without_adapter_stopped_by_line(self):
        """CI の役が要る（宣言も test_cmd も無い）のに切符が無く、blk-ci の柵（ci_role.fence）が止めた盤面 → stopped_by_line、
        冒頭 4 に止めた理由"""
        repo = self.begin(declared=False)
        self.assertIn("p0.local_checks", entry.open_board(self.board).settle()["ready"])
        adapter.ticket_path(repo).unlink()
        got = ci_role.fence(self.board, "p0.local_checks", repo)
        self.assertFalse(got["go"])
        out, _, h = self.build(judged=None, tests=None, ci={"ok": False, "reason": got["reason"], "note": ""})
        self.assertEqual(out["outcome"], "stopped_by_line")
        self.assertIn(got["reason"], h[H4])

    def test_needs_human(self):
        """最後の settle で pending_human が残った盤面 → needs_human、冒頭 1 に問いと項目"""
        self.planned()
        out, _, h = self.build()
        self.assertEqual(out["outcome"], "needs_human")
        ph = entry.open_board(self.board).state["pending_human"]
        self.assertIn(ph["question"], h[H1])
        self.assertIn(ph["items"][0], h[H1])


# 写しの検証器（.shared/core/scripts/review-record.py）が 1 周目にいつも出す帳尻の行
FIRST_ROUND = "前ラウンドの記録が無い（連続 2 ラウンドの 1 ラウンド目。収束は次ラウンド以降）"
REAL_BLOCKER = "R3 が redesign-needed（理由: 見本の阻害）"
EYES_PASS = {"R1": {"status": "pass", "reason": "見本"}, "R2": {"status": "pass", "reason": "見本"},
             "R3": {"status": "pass", "reason": "見本"}, "R4": {"status": "pass", "reason": "見本"}}


def validator_out(*lines, count=None) -> str:
    """review-record.py の exit 1 の出力の形（見出し『収束を妨げるもの N 件:』と bullet の箇条）"""
    n = len(lines) if count is None else count
    return "\n".join([f"収束を妨げるもの {n} 件:", *(f"  - {x}" for x in lines)])


class ResidueCase(ReportBase):
    """残り（名指しの帳尻の行を除いた検証器の阻害・最後のテストの赤・独立の目の block）が在れば fixed を名乗らない"""

    def build_with(self, exit_code, out, **kw):
        fake = mock.Mock(return_value={"exit": exit_code, "out": out})
        with mock.patch.object(entry, "hook_kwargs", return_value={"validator_runner": fake}):
            return self.build(**kw)

    def build_eyeing(self, eyeing, **kw):
        try:
            return self.build_with(0, "", eyeing=eyeing, **kw)
        except TypeError as e:
            self.fail(f"build が独立の目の出口 eyeing を受けない: {e}")

    def test_round_limit_is_an_outcome(self):
        self.assertIn("round_limit", report.OUTCOMES)

    def test_first_round_line_only_is_fixed(self):
        """1 周で止める run の帳尻の行だけ（exit 1）→ fixed に届く"""
        self.full()
        out, _, _ = self.build_with(1, validator_out(FIRST_ROUND))
        self.assertEqual(out["outcome"], "fixed")

    def test_real_blocker_with_first_round_line_is_round_limit(self):
        """帳尻の行＋本物の阻害 1 → round_limit、冒頭 1 に阻害の行が字のまま"""
        self.full()
        out, _, h = self.build_with(1, validator_out(REAL_BLOCKER, FIRST_ROUND))
        self.assertEqual(out["outcome"], "round_limit")
        self.assertIn(REAL_BLOCKER, h[H1])

    def test_prev_round_line_is_not_suppressed(self):
        """『前ラウンドに阻害要因が N 件あった』は名指しの帳尻の行ではない → round_limit"""
        self.full()
        prev = "前ラウンドに阻害要因が 2 件あった（連続 2 ラウンドの 1 ラウンド目。今ラウンドが阻害なしでも収束は次ラウンド）"
        out, _, _ = self.build_with(1, validator_out(prev))
        self.assertEqual(out["outcome"], "round_limit")

    def test_count_mismatch_is_round_limit(self):
        """見出しの N と箇条の数が合わない exit 1 → fail-closed で round_limit"""
        self.full()
        out, _, _ = self.build_with(1, validator_out(FIRST_ROUND, count=2))
        self.assertEqual(out["outcome"], "round_limit")

    def test_no_heading_is_round_limit(self):
        """見出しが無い exit 1 → fail-closed で round_limit"""
        self.full()
        out, _, _ = self.build_with(1, "読めない出力")
        self.assertEqual(out["outcome"], "round_limit")

    def test_red_final_tests_is_round_limit(self):
        """最後のテストが赤 → fixed を名乗らない"""
        self.full()
        out, _, _ = self.build_with(0, "", tests=RED)
        self.assertEqual(out["outcome"], "round_limit")

    def test_eye_block_is_round_limit(self):
        """独立の目の R3 が redesign-needed → round_limit、冒頭 1 に目の名"""
        self.full()
        eyeing = {"ok": True, "reason": "", "reviews": {**EYES_PASS, "R3": {"status": "redesign-needed", "reason": "目の見本"}}}
        out, _, h = self.build_eyeing(eyeing)
        self.assertEqual(out["outcome"], "round_limit")
        self.assertIn("R3", h[H1])

    def test_eyeing_not_ok_is_round_limit(self):
        """独立の目のブロックが ok でない → round_limit"""
        self.full()
        out, _, _ = self.build_eyeing({"ok": False, "reason": "目が 3 回とも拒まれた", "reviews": EYES_PASS})
        self.assertEqual(out["outcome"], "round_limit")

    def test_eyes_all_pass_is_fixed(self):
        self.full()
        out, _, _ = self.build_eyeing({"ok": True, "reason": "", "reviews": EYES_PASS})
        self.assertEqual(out["outcome"], "fixed")

    def test_first_round_constant_matches_validator(self):
        """除く帳尻の行の定数は、写しの検証器の本文に字のまま在る（写しが変われば赤になり、黙って除かない）"""
        const = getattr(report, "FIRST_ROUND_LINE", None)
        self.assertIsNotNone(const, "report.FIRST_ROUND_LINE が無い")
        src = (CORE / "scripts" / "review-record.py").read_text(encoding="utf-8")
        self.assertIn(f'"{const}"', src)
        self.assertEqual(const, FIRST_ROUND)


# ---------------------------------------------------------------- 冒頭の部品
class HeadCase(ReportBase):
    def clean_in(self, repo, scope, board, ignored="x.log"):
        """scope（fixing・refitting）の clean を本物の remove_new_ignored で回し、ignored の名のファイルを消させる"""
        (repo / ".gitignore").write_text("*.log\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {"ARCHON_NODE_EXECUTION": json.dumps({"runId": "r", "path": f"{scope}__clean"})}):
            leftovers.record_ignored(board, repo)
            if ignored:
                (repo / ignored).write_text("g\n", encoding="utf-8")
            return leftovers.remove_new_ignored(board, repo)

    def test_removed_reads_scope_roots_not_run_vs_zero(self):
        """clean が scope の根（<盤面>/fixing/・<盤面>/refitting/）に書いた fix-removed.json を、scope の環境の無い所から
        leftovers.removed が読んで件数と全パスを返す。ファイルが無ければ ran=False（走らせていない）、空なら ran=True・0 本。
        読めないファイルは投げずに readable=False"""
        self.without_node_env()
        board = self.tmp / "b"
        board.mkdir()
        self.assertEqual(leftovers.removed(board), {"ran": False, "readable": True, "reason": "", "count": 0, "paths": [], "by_scope": {}})
        subprocess.run(["git", "init", "-q", str(self.tmp / "r")], check=True)
        repo = self.tmp / "r"
        self.assertEqual(self.clean_in(repo, "fixing", board)["count"], 1)
        got = leftovers.removed(board)
        self.assertEqual((got["ran"], got["count"], got["paths"], got["by_scope"]), (True, 1, ["x.log"], {"fixing": ["x.log"]}))
        self.assertEqual(self.clean_in(repo, "refitting", board, ignored="")["count"], 0)
        got = leftovers.removed(board)
        self.assertEqual((got["ran"], got["count"], sorted(got["by_scope"])), (True, 1, ["fixing", "refitting"]))
        empty = self.tmp / "e"
        (empty / "fixing").mkdir(parents=True)
        (empty / "fixing" / leftovers.REMOVED_FILE).write_text('{"removed": []}', encoding="utf-8")
        self.assertEqual((leftovers.removed(empty)["ran"], leftovers.removed(empty)["count"]), (True, 0))
        (board / "fixing" / leftovers.REMOVED_FILE).write_text("{", encoding="utf-8")
        broken = leftovers.removed(board)
        self.assertEqual((broken["ran"], broken["readable"]), (True, False))
        self.assertIn("読めない", broken["reason"])

    def test_always_rows_show_zero_and_not_run(self):
        """異常が 0 件・レンズの控えも消した物のファイルも無い盤面でも、always_rows が 4 つの行を出す。控えの無いレンズと無い
        fix-removed.json は「走らせていない」。left を渡さない呼びは残りを「数えない」と言い、渡せば件数を言う。報告にも載る"""
        self.begin()
        self.without_node_env()
        b = entry.open_board(self.board, allow_halted=True)
        rows = report.always_rows(b)
        self.assertEqual([r for r in rows if not r.startswith("  ")],
                         ["clean が消したファイル: 走らせていない（fix-removed.json が無い。修正の段が無い run か、clean の前に止まった）",
                          "レンズ: 走らせていない（控えが無い）",
                          "仕組みの異常: 合計 0 件（" + "・".join(f"{n} 0" for n, _, _ in report.ANOMALY_OPS)
                          + "。所在の全件は仕組みの異常の節）",
                          "残り: 数えを渡されていない（always_rows に left も rest も無い——呼び元の渡し忘れで、0 件ではない）"])
        self.assertIn("残り: 0 件", "\n".join(report.always_rows(b, left=[])))
        self.assertIn("残り: 2 件", "\n".join(report.always_rows(b, left=[{"where": "w", "text": "a"}, {"where": "w", "text": "b"}])))
        _, text, h = self.build()
        for row in ("clean が消したファイル: 走らせていない", "レンズ: 走らせていない", "仕組みの異常: 合計 0 件", "残り: 0 件"):
            self.assertIn(row, h[H1])
        self.assertIn("## 仕組みの異常\n\n- 宣言の外の読み（", text)
        self.assertIn("## 未確認のレンズ\n\n- レンズを走らせていない", text)
        # 2026-10-09 の片付け: 末尾の「このラインに無い節」の節は出さない（冒頭 2 の 1 行が数と一覧の置き場を言う）。冒頭 4 の
        # 仕組みの異常は 0 件の種を並べない（冒頭 1 の合計と「仕組みの異常」の節が言う）。残りが 0 件なら関所の例外の注記を付けない
        self.assertNotIn("## このラインに無い節", text)
        self.assertFalse(any(name in h[H4] for name, _, _ in report.ANOMALY_OPS), h[H4])
        self.assertNotIn(report.NOT_RUN_GATE_NOTE, h[H1])
        self.assertNotIn(report.NOT_RUN_GATE_NOTE, "\n".join(report.always_rows(b, left=[])))
        self.assertIn(report.NOT_RUN_GATE_NOTE, "\n".join(report.always_rows(b, left=[{"where": "w", "text": "a"}])))

    def final_text(self, b, tests):
        """最後の関所の文を本物の作り手（line_edge._eyes と report.rest_outside_validator）が作った eyes・rest で組む"""
        sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
        import line_edge  # noqa: E402
        eyes = line_edge._eyes(b)
        rest = report.rest_outside_validator(b, tests=tests, counts=eyes.counts)
        return line_edge._final_text(b, tests, "", eyes, rest, self.tmp, "run-1")

    def write_eye_reviews(self, b, reviews):
        rounds = self.board / "rounds"
        rounds.mkdir(exist_ok=True)
        (rounds / f"round-{b.round}.json").write_text(json.dumps({"reviews": reviews}, ensure_ascii=False), encoding="utf-8")

    def test_gate_and_head_one_count_the_same_rest(self):
        """1 つの盤面（R1 redesign-needed・R2 not_run・R3 表に無い status・R4 結果が無い。テストは緑）で、最後の関所の文の残りの行と
        報告の冒頭 1 の residue の目の行が同じ 4 つの目を同じ数で数える。関所は阻害 R1・R3・走っていない目 R2・結果が無い目 R4 と
        言い、residue の目の行の名は {R1,R2,R3,R4}。R1 の行の文は今の形『R1 が redesign-needed: <reason>』のまま"""
        sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
        import line_edge  # noqa: E402
        self.begin()
        self.without_node_env()
        b = entry.open_board(self.board, allow_halted=True)
        reviews = {"R1": {"status": "redesign-needed", "reason": "目の見本"}, "R2": {"status": "not_run", "reason": "返答が無い"},
                   "R3": {"status": "not-in-the-status-table", "reason": "表に無い"}}
        self.write_eye_reviews(b, reviews)
        with mock.patch.object(report, "gate_record"):
            eyes = line_edge._eyes(b)
            rest = report.rest_outside_validator(b, tests=GREEN, counts=eyes.counts)
            text = line_edge._final_text(b, GREEN, "", eyes, rest, self.tmp, "run-1")
            rows = report.residue(b, {"exit": 0}, tests=GREEN, eyeing={"ok": True, "reason": "", "reviews": reviews})
        self.assertIn("- 残り（最後の関所で数えられる分）: 独立の目の阻害 2 件（R1・R3）・走っていない目 1 件（R2）・"
                      "結果が無い目 1 件（R4。阻害 0 件ではなく判定が無い）・最後のテスト: 緑", text)
        eye_rows = {r["where"]: r["text"] for r in rows if r["where"].startswith(f"{report.EYES_WHERE} ")}
        self.assertEqual(set(eye_rows), {f"{report.EYES_WHERE} {n}" for n in report.EYES})
        self.assertEqual(len(eye_rows), sum(len(x) for x in rest.counts))
        self.assertEqual(eye_rows[f"{report.EYES_WHERE} R1"], "R1 が redesign-needed: 目の見本")

    def test_final_text_reads_missing_eyes_only_from_given_eyes(self):
        """_final_text は渡された eyes と rest だけを読む。目の結果が無い盤面で作った eyes を渡した後に周の記録（全部 pass）を書いても、
        関所の文は結果が無い目 4 件と言い、盤面を読み直して 0 件にしない"""
        sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
        import line_edge  # noqa: E402
        self.begin()
        self.without_node_env()
        b = entry.open_board(self.board, allow_halted=True)
        eyes = line_edge._eyes(b)
        rest = report.rest_outside_validator(b, tests=GREEN, counts=eyes.counts)
        self.write_eye_reviews(b, EYES_PASS)
        text = line_edge._final_text(b, GREEN, "", eyes, rest, self.tmp, "run-1")
        self.assertIn("結果が無い目 4 件（R1・R2・R3・R4。阻害 0 件ではなく判定が無い）", text)
        self.assertNotIn("結果が無い目 0 件", text)

    def test_always_rows_without_counts_names_the_missing_args(self):
        """left も rest も渡さない always_rows(b) の残りの行は、呼び元の渡し忘れ（left・rest）を名指し、0 件でないと言う。
        検証器を回していないという事実でない理由は言わない"""
        self.begin()
        self.without_node_env()
        b = entry.open_board(self.board, allow_halted=True)
        rest_rows = [r for r in report.always_rows(b) if r.startswith("残り")]
        self.assertEqual(len(rest_rows), 1)
        row = rest_rows[0]
        for part in ("left", "rest", "渡し忘れ", "0 件ではない"):
            self.assertIn(part, row)
        self.assertNotIn("検証器を回していない", row)

    def test_head_one_rest_row_names_the_not_run_exception_like_the_gate(self):
        """報告の冒頭 1 の残りの行（always_rows の left の枝）も、最後の関所の残りの行と同じ NOT_RUN_GATE_NOTE の一文で、走っていない目
        （not_run）を関所では開ける理由に数えないことを名指す（走っていない目が在る時。残りが 0 件なら添えない）"""
        self.begin()
        self.without_node_env()
        eyeing = {"ok": True, "reason": "", "reviews": {**EYES_PASS, "R3": {"status": "not_run", "reason": "返答が無い"}}}
        _, _, h = self.build(eyeing=eyeing)
        rest_rows = [x for x in h[H1].splitlines() if x.startswith("- 残り")]
        self.assertEqual(len(rest_rows), 1)
        self.assertIn(report.NOT_RUN_GATE_NOTE, rest_rows[0])
        self.assertIn(report.MISSING_GATE_NOTE, rest_rows[0])

    def test_gate_rest_row_names_why_missing_eyes_do_not_open_the_gate(self):
        """結果が無い目は関所を開ける理由に数えない（not_run と同じ例外）。その理由（MISSING_GATE_NOTE）を、関所の文の残りの行が言う"""
        sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
        import line_edge  # noqa: E402
        self.begin()
        self.without_node_env()
        b = entry.open_board(self.board, allow_halted=True)
        eyes = line_edge._eyes(b)
        rest = report.rest_outside_validator(b, tests=GREEN, counts=eyes.counts)
        self.assertEqual(len(eyes.counts.missing), 4)
        self.assertEqual(line_edge._final_needs(b, rest, "", [], "", [], []), [])
        self.assertIn(report.MISSING_GATE_NOTE, line_edge._final_text(b, GREEN, "", eyes, rest, self.tmp, "run-1"))

    def test_residue_dedupe_needs_the_same_status_as_the_validator_row(self):
        """検証器の行が同じ目の同じ status を既に出していれば目の行は二重に数えないが、status が違えば理由つきの目の行を落とさない"""
        self.begin()
        self.without_node_env()
        b = entry.open_board(self.board, allow_halted=True)
        reviews = {**EYES_PASS, "R3": {"status": "redesign-needed", "reason": "見本の阻害"}}
        eyeing = {"ok": True, "reason": "", "reviews": reviews}
        r3 = lambda rows: [r for r in rows if r["where"] == f"{report.EYES_WHERE} R3"]
        same = {"exit": 1, "out": validator_out("R3 が redesign-needed（理由: 見本の阻害）")}
        self.assertEqual(r3(report.residue(b, same, tests=GREEN, eyeing=eyeing)), [])
        other = {"exit": 1, "out": validator_out("R3 が not_run（理由: 別の status）")}
        self.assertEqual([r["text"] for r in r3(report.residue(b, other, tests=GREEN, eyeing=eyeing))],
                         ["R3 が redesign-needed: 見本の阻害"])

    def test_anomalies_unexamined_when_trace_missing_or_broken(self):
        """trace.jsonl が無い盤面では anomalies が種別ごとに None（調べていない。0 件でない）を返す。壊れた行が混ざれば飛ばした数
        skipped を返して行に出す。読めた盤面でだけ種別ごとの件数（0 も）を出す。always_rows の異常の行も同じ区別をする"""
        self.begin()
        self.without_node_env()
        b = entry.open_board(self.board, allow_halted=True)
        trace = self.board / "trace.jsonl"
        good = [{"op": scopes.READ_OUTSIDE_OP, "scope": "fixing", "paths": ["a.md"]}, {"op": writes.NO_RECORD_OP, "node": "p3.fix"},
                {"op": writes.LEFT_OP, "node": "p3.delta_fix", "paths": ["b.py", "b.py"]}]
        trace.write_text("{\n" + "".join(json.dumps(r) + "\n" for r in good) + "[1]\n", encoding="utf-8")
        got = report.anomalies(b)
        self.assertEqual((got["examined"], got["skipped"], got["total"]), (True, 2, 3))
        self.assertEqual({n: k["count"] for n, k in got["kinds"].items()},
                         {"宣言の外の読み": 1, "必須の出力の欠け": 0, "書き込みの記録が無い run": 1, "記録の無い変更": 1})
        self.assertEqual(got["kinds"]["宣言の外の読み"]["where"], ["fixing: a.md"])
        self.assertTrue(any("壊れた行 2 行を飛ばした" in x for x in report.anomaly_lines(b)))
        self.assertTrue(any("壊れた行 2 行を飛ばした" in x for x in report.always_rows(b)))
        trace.write_text("", encoding="utf-8")
        zero = report.anomalies(b)
        self.assertEqual((zero["examined"], zero["total"], {k["count"] for k in zero["kinds"].values()}), (True, 0, {0}))
        trace.unlink()
        missing = report.anomalies(b)
        self.assertEqual((missing["examined"], missing["total"], {k["count"] for k in missing["kinds"].values()}), (False, None, {None}))
        self.assertEqual(report.anomaly_lines(b), ["仕組みの異常: 調べていない（盤面の trace.jsonl が無い・読めない）"])
        self.assertIn("仕組みの異常: 調べていない", "\n".join(report.always_rows(b)))

    def test_final_gate_text_has_always_rows(self):
        """最後の関所の文（line_edge._final_text）に、消したファイルの件数と全パス・レンズの件数（落ちたレンズの件数も）・仕組みの異常の
        種別ごとの件数と合計・残りの数えられる分（目の阻害の件数と最後のテストの語。検証器は数えないと書く）が 0 件でも載る。
        関所は検証器を回さない（gate_record を呼ばない）。壊れた lens.json・
        fix-removed.json の盤面でも落ちずに「読めない」と言う（build も同じ）。走っていない目の件数と NOT_RUN_GATE_NOTE も載る"""
        self.begin()
        self.without_node_env()
        b = entry.open_board(self.board, allow_halted=True)
        with mock.patch.object(report, "gate_record") as gate:
            text = self.final_text(b, GREEN)
        gate.assert_not_called()
        for row in ("- clean が消したファイル: 走らせていない", "- レンズ: 走らせていない", "- 仕組みの異常: 合計 0 件",
                    "- 残り（最後の関所で数えられる分）: 独立の目の阻害 0 件（無し）・走っていない目 0 件（無し）・結果が無い目 4 件（R1・R2・R3・R4。阻害 0 件ではなく判定が無い）・最後のテスト: 緑"):
            self.assertIn(row, text)
        self.assertIn(report.NOT_RUN_GATE_NOTE, text)
        (self.board / "fixing").mkdir()
        (self.board / "fixing" / leftovers.REMOVED_FILE).write_text(json.dumps({"removed": ["x.log", "d/y.log"]}), encoding="utf-8")
        lens.write_routes(b, [{"lens": "silent-failure-hunter", "agent": "a", "go": True}])
        lens.collect(b, {"silent-failure-hunter": {"findings": [{"where": "w", "cite": "c", "why": "y"}, {"where": ""}]}})
        text = self.final_text(b, GREEN)
        for part in ("clean が消したファイル: 2 本", "  - fixing: x.log", "  - fixing: d/y.log", "- レンズの発見: 差分の審査が走っていないので採った・採らなかったは調べていない・形の誤りで捨てた 1 件・落ちたレンズ 0 件",
                     "  - silent-failure-hunter: 調べていない・形の誤りで捨てた 1（出した発見 1）"):
            self.assertIn(part, text)
        (self.board / "fixing" / leftovers.REMOVED_FILE).write_text("{", encoding="utf-8")
        b.work(lens.LENS_FILE).write_text("[]", encoding="utf-8")
        text = self.final_text(b, GREEN)
        self.assertIn("- clean が消したファイル: 読めない（", text)
        self.assertIn("- レンズ: 読めない（", text)
        _, built, h = self.build()
        self.assertIn("clean が消したファイル: 読めない（", h[H1])
        self.assertIn("レンズ: 読めない（", h[H1])
        self.assertTrue(any("レンズの控えが読めない" in x["text"] for x in json.loads(
            pathlib.Path(self.build()[0]["next_request_file"]).read_text(encoding="utf-8"))["findings"]))

    def test_final_gate_residue_names_countable_parts(self):
        """最後の関所の文の残りの行が、目の阻害の件数（名つき・無しなら 0 件）・結果が無い目の件数と最後のテストの頭の語を並べ、
        検証器は数えないと書く。目の結果は盤面の周の記録から _eyes で読んだ物を渡す（阻害と結果が無いが同じ控えから出る）。
        目の結果が無い盤面は阻害 0 件と結果が無い目 4 件を分けて言う。テストの頭が「走らなかった」なら語で言い 0 件に見せない。
        引数なしの always_rows(b) は渡し忘れを名指す。落ちたレンズ 1 本の盤面ではレンズの行に「落ちたレンズ 1 件」が出る"""
        sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
        import line_edge  # noqa: E402
        self.begin()
        self.without_node_env()
        b = entry.open_board(self.board, allow_halted=True)
        with mock.patch.object(report, "gate_record") as gate:
            none = self.final_text(b, None)
            rounds = self.board / "rounds"
            rounds.mkdir(exist_ok=True)
            (rounds / f"round-{b.round}.json").write_text(json.dumps(
                {"reviews": {**EYES_PASS, "R1": {"status": "redesign-needed", "reason": "目の見本"}}}, ensure_ascii=False), encoding="utf-8")
            eyes = line_edge._eyes(b)
            self.assertEqual([e["name"] for e in eyes.counts.blocked], ["R1"])
            red = self.final_text(b, {"ok": True, "green": False})
        gate.assert_not_called()
        self.assertIn("- 残り（最後の関所で数えられる分）: 独立の目の阻害 1 件（R1）・走っていない目 0 件（無し）・結果が無い目 0 件（無し。阻害 0 件ではなく判定が無い）・最後のテスト: 赤", red)
        self.assertIn("- 残り（最後の関所で数えられる分）: 独立の目の阻害 0 件（無し）・走っていない目 0 件（無し）・結果が無い目 4 件（R1・R2・R3・R4。阻害 0 件ではなく判定が無い）・最後のテスト: 走らなかった", none)
        self.assertIn("検証器の阻害は最後の関所では数えない", red)
        self.assertNotIn("最後の関所の時点では検証器を回していないので数えない", red)
        self.assertIn("残り: 数えを渡されていない（always_rows に left も rest も無い", "\n".join(report.always_rows(b)))
        lens.write_routes(b, [{"lens": "silent-failure-hunter", "agent": "a", "go": True}])
        lens.collect(b, {})
        text = self.final_text(b, GREEN)
        self.assertIn("落ちたレンズ 1 件", text)

    def test_head_one_names_refitting_removed_paths(self):
        """clean が fixing と refitting の両方の scope で消した盤面は、報告の冒頭 1（report.md の h[H1]）が scope ごとの全パスを
        『  - fixing: <パス>』『  - refitting: <パス>』で出す（件数は 2 本。refitting の分が冒頭 1 に届く）"""
        self.begin()
        self.without_node_env()
        subprocess.run(["git", "init", "-q", str(self.tmp / "r")], check=True)
        repo = self.tmp / "r"
        self.assertEqual(self.clean_in(repo, "fixing", self.board, ignored="x.log")["count"], 1)
        self.assertEqual(self.clean_in(repo, "refitting", self.board, ignored="d.log")["count"], 1)
        _, _, h = self.build()
        self.assertIn("clean が消したファイル: 2 本", h[H1])
        self.assertIn("  - fixing: x.log", h[H1])
        self.assertIn("  - refitting: d.log", h[H1])

    def test_lens_count_line_zero_and_one_on_both_sides(self):
        """レンズを走らせた盤面で、形の誤りで捨てた 0 件の盤面と 1 件の盤面のそれぞれが、報告の冒頭 1（h[H1]）と最後の関所の文
        （eyes は line_edge._eyes、rest は report.rest_outside_validator で組む）の両方に lens.count_line の行（捨てた N 件・落ちたレンズ
        0 件）を出す。0 件も黙らない"""
        self.begin()
        self.without_node_env()
        b = entry.open_board(self.board, allow_halted=True)
        good = {"where": "w", "cite": "c", "why": "y"}
        for dropped, findings in ((0, [good]), (1, [good, {"where": ""}])):
            lens.write_routes(b, [{"lens": "silent-failure-hunter", "agent": "a", "go": True}])
            lens.collect(b, {"silent-failure-hunter": {"findings": findings}})
            s = lens.summary(b)
            self.assertEqual((s["dropped"], len(s["failed"])), (dropped, 0))
            line = lens.count_line(s)
            self.assertIn(f"形の誤りで捨てた {dropped} 件・落ちたレンズ 0 件", line)
            _, _, h = self.build()
            self.assertIn(f"- {line}", h[H1].splitlines())
            with mock.patch.object(report, "gate_record"):
                text = self.final_text(b, GREEN)
            self.assertIn(f"- {line}", text.splitlines())

    def test_anomaly_section_lists_each_kind_with_location(self):
        """仕組みの異常の 4 種（宣言の外の読み・必須の出力の欠け・書き込みの記録が無い run・記録の無い変更）がどれも 1 件以上の trace の盤面で、
        report.md の『## 仕組みの異常』の節が種ごとの件数の行と所在の行（1 件 1 行。記録の無い変更はパスの重複を 1 本に）を出す。
        冒頭 1 の仕組みの異常の行は合計を言う"""
        self.begin()
        self.without_node_env()
        b = entry.open_board(self.board, allow_halted=True)
        b.trace(scopes.READ_OUTSIDE_OP, scope="fixing", paths=["a.md", "c.md"])
        b.trace(scopes.REQUIRED_MISSING_OP, scope="lensing", names=["r1/lens.json"])
        b.trace(writes.NO_RECORD_OP, node="p3.fix")
        b.trace(writes.LEFT_OP, node="p3.delta_fix", paths=["b.py", "b.py", "d.py"])
        _, text, h = self.build()
        notes = {n: note for n, _, note in report.ANOMALY_OPS}
        want = [f"- 宣言の外の読み（{notes['宣言の外の読み']}）: 2 件", "  - fixing: a.md", "  - fixing: c.md",
                f"- 必須の出力の欠け（{notes['必須の出力の欠け']}）: 1 件", "  - lensing: r1/lens.json",
                f"- 書き込みの記録が無い run（{notes['書き込みの記録が無い run']}）: 1 件", "  - p3.fix",
                f"- 記録の無い変更（{notes['記録の無い変更']}）: 2 件", "  - b.py", "  - d.py"]
        self.assertEqual(h["## 仕組みの異常"].strip("\n").splitlines(), want)
        self.assertIn("仕組みの異常: 合計 6 件（宣言の外の読み 2・必須の出力の欠け 1・書き込みの記録が無い run 1・記録の無い変更 2", h[H1])

    def test_head_parts_callable(self):
        """head_reads・head_where・head_cost を盤面だけで呼べ、盤面の全部のファイルの sha が変わらない（線 B が呼ぶ）"""
        self.full()
        before = TE.board_shas(self.board)
        b = entry.open_board(self.board, allow_halted=True)
        where = report.head_where(b)
        got = report.head_reads(self.board, RUN_ID)
        cost = report.head_cost(self.board, RUN_ID)
        self.assertTrue(where and got and cost)
        self.assertEqual(TE.board_shas(self.board), before)
        self.assertIn(f"run の作業ツリー: {b.state['inputs']['cwd']}", where)
        self.assertTrue(any(x.startswith("判定: ") for x in where))

    def test_reads_lines_cover_scoped_reads(self):
        """同じブロックの 2 つの include（fixing・refitting）がそれぞれ scope の根に書いた reads-fix.json は、冒頭 4 の読みの節に
        両方の行が出る（登録の順。盤面の根の周の置き場の物が先）"""
        self.full()
        for scope in ("fixing", "refitting"):
            scopes.claim(self.board, 1, scope, "blk-fix")
        made = []
        for rel, role in (("r1/reads-plan.json", "plan"), ("fixing/r1/reads-fix.json", "fix"),
                          ("refitting/r1/reads-fix.json", "fix.refit")):
            p = self.board / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps({"role": role, "rows": [], "missing": [], "sources": {"hook": False, "events": "none"}}),
                         encoding="utf-8")
            made.append(p)
        rows = [x for x in report.head_reads(self.board, RUN_ID) if x.startswith("読んだ証拠 ")]
        self.assertEqual([x.split(":")[0] for x in rows], ["読んだ証拠 plan", "読んだ証拠 fix", "読んだ証拠 fix.refit"])
        self.assertEqual([x.rsplit("。", 1)[1].rstrip("）") for x in rows], [str(p) for p in made])

    def test_reads_lines_skip_block_index(self):
        """blk-plan の索引 reads-plan-block.json と案の直しの索引 reads-replan-block.json（{役: reads-<役>.json} の対応で、
        役の読んだ証拠そのものでない）は読みの節の行にしない（実物の run 55/56 本に「読んだ証拠 None: 渡した 0 件」が出ていた）"""
        self.full()
        made = {}
        for name, doc in (("reads-plan.json", {"role": "plan", "rows": [], "missing": [],
                                               "sources": {"hook": False, "events": "none"}}),
                          ("reads-plan-block.json", {"plan": "x/reads-plan.json"}),
                          ("reads-replan-block.json", {"plan": "x/reads-replan-plan.json"})):
            p = self.board / "r1" / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(doc), encoding="utf-8")
            made[name] = p
        rows = [x for x in report.head_reads(self.board, RUN_ID) if x.startswith("読んだ証拠")]
        self.assertEqual([x.split(":")[0] for x in rows], ["読んだ証拠 plan"], rows)
        self.assertFalse(any("None" in x for x in rows), rows)

    def test_round_two_paths(self):
        """周 2 の出力（state.outputs[節]["file"] が out/r2/）→ 見る所のパスは out/r2/ の下（周を仮定しない）"""
        self.full()
        st = json.loads((self.board / "state.json").read_text(encoding="utf-8"))
        for info in st["outputs"].values():
            info["file"] = info["file"].replace("out/r1/", "out/r2/")
            info["round"] = 2
        (self.board / "out" / "r1").rename(self.board / "out" / "r2")
        (self.board / "state.json").write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        b = entry.open_board(self.board, allow_halted=True)
        files = [x.split(": ", 1)[1] for x in report.head_where(b) if x.split(": ", 1)[0] in dict(report.WHERE)]
        self.assertTrue(files)
        for f in files:
            self.assertIn("/out/r2/", f)
            self.assertTrue(pathlib.Path(f).is_file(), f)

    def test_not_in_line_listed(self):
        """冒頭 2 の数 == state.works.not_in_line の数、p2.history がその一覧に、p0.parallel_pr が下げている所に在る"""
        self.judged()
        b = entry.open_board(self.board)
        lines = report.head_entry(b, None)
        n = len(b.state["works"]["not_in_line"])
        hit = [x for x in lines if x.startswith(f"このラインに無い節: {n} 個")]
        self.assertEqual(len(hit), 1, lines)
        self.assertNotIn("報告の末尾", hit[0], "末尾の一覧の節は無い（一覧は周の添え書きの not_in_line）")
        downs = report.declared_downgrades(b.table.line)
        self.assertTrue(any(x.startswith(f"下げている所: {len(downs)} 個") for x in lines))
        self.assertTrue(any(x.strip().startswith("- p0.parallel_pr:") and "review-graph" in x for x in lines))

    def test_entry_words_from_start_doc(self):
        """冒頭 2 の入口は start の控えの entry_words（変更から入った run を判定からと書かない）。渡された出口に無くても控えから"""
        self.judged()
        b = entry.open_board(self.board)
        self.assertTrue(report.head_entry(b, {})[0].startswith("入口: 判定から（依頼 "))
        self.assertIn("・段: ", report.head_entry(b, {})[0])   # entry.start の頭の行と同じ字
        words = "変更から（0123456789ab..HEAD・PR #7）"
        self.assertTrue(report.head_entry(b, {"entry_words": words})[0].startswith(f"入口: {words}・"))
        p = self.board / "r1" / entry.START_FILE
        doc = json.loads(p.read_text(encoding="utf-8")) if p.is_file() else {}
        p.write_text(json.dumps({**doc, "entry_words": words}, ensure_ascii=False), encoding="utf-8")
        self.assertTrue(report.head_entry(b, {"entry": "change"})[0].startswith(f"入口: {words}・"))

    def test_features_part_from_start_doc(self):
        """冒頭 2 の頭の行に切った機能（入力 features_off）が出る。正本は start の控え（start の出口は機能ごとの on・off だけ）。
        控えに欄が無い run（start が控えを書く前に落ちた）は語を出さない"""
        self.judged()
        b = entry.open_board(self.board)
        self.assertIn("・機能: judge_verify off・review_tree auto", report.head_entry(b, {})[0])   # 控えは空の配列（既定）
        p = self.board / "r1" / entry.START_FILE
        doc = json.loads(p.read_text(encoding="utf-8"))
        p.write_text(json.dumps({**doc, "features_off": ["tdd_lanes"], "features_on": ["judge_verify"]}, ensure_ascii=False),
                     encoding="utf-8")
        self.assertIn("・機能: review_tree auto・tdd_lanes off", report.head_entry(b, {"tdd_lanes": "off"})[0])
        doc.pop("features_on", None)
        doc.pop("features_off")
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        self.assertNotIn("機能", report.head_entry(b, {})[0])

    def test_cleaned_runs_line_in_head_entry(self):
        """use.sh start が起動の前に片付けた前の run（入力 cleaned_runs）は冒頭 2 に 1 行で出る。空なら行を出さない"""
        self.judged()
        b = entry.open_board(self.board)
        self.assertFalse(any(x.startswith(report.CLEANED_HEAD) for x in report.head_entry(b, None)))
        lines = report.head_entry(b, None, cleaned_runs="run-f（failed）・run-c（completed）")
        self.assertIn(f"{report.CLEANED_HEAD}: run-f（failed）・run-c（completed）", lines)

    def test_depth_lines_in_head_entry(self):
        """深さの節 h-redepth の行（入力 depth の lines）は冒頭 2 にそのまま並ぶ。無い run（前の版・節が走らなかった）は出さない"""
        self.judged()
        b = entry.open_board(self.board)
        self.assertFalse(any(x.startswith("深さ: ") for x in report.head_entry(b, None)))
        got = ["深さ: 軽量（単位ごと: 軽量 1 個・標準 0 個。機械が決めた）", "軽量で省いた: レンズ"]
        lines = report.head_entry(b, None, depth_lines=got)
        for x in got:
            self.assertIn(x, lines)

    def test_no_library_docs_quota_line_in_head_entry(self):
        """Context7 はやめた（持ち主 2026-10-09）: 前の版が盤面に残した枠切れの印（libdocs/_quota.json）が在っても、冒頭 2 に
        ライブラリの文書の枠切れの行を出さない"""
        self.judged()
        b = entry.open_board(self.board)
        mark = b.work("libdocs/_quota.json")
        mark.parent.mkdir(parents=True, exist_ok=True)
        mark.write_text(json.dumps({"schema": "works-libdocs/1", "reason": "HTTP 429"}), encoding="utf-8")
        lines = report.head_entry(b, None)
        self.assertFalse([x for x in lines if "枠切れ" in x or "Context7" in x], lines)

    def test_handover_drafts_and_downgrade(self):
        """p0.parallel_pr を任せ先で受けた盤面（conflicts 2 件・どちらも note つき・外した hunk 1 件）→ 冒頭 1 に 2 件の下書きと
        外した範囲、冒頭 2 に downgrades.json の 1 行"""
        pr = linekit.reply("pr_ok")
        second = {"pr": "8", "files": ["test_stats.py"], "handed_over": False, "note": "PR #8 の担当へ: " + ODD}
        pr["conflicts"] = pr["conflicts"] + [second]
        self.begin(pr=pr)
        out, _, h = self.build(judged=None, tests=None)
        self.assertIn(pr["conflicts"][0]["note"], h[H1])
        self.assertIn(second["note"], h[H1])
        self.assertEqual(h[H1].count("申し送りの下書き"), 2)
        x = pr["excluded"][0]
        self.assertIn(f"{x['file']}:{x['start']}-{x['end']}", h[H1])
        self.assertIn("- p0.parallel_pr:", h[H2])

    def test_rejudge_undisputed_changes_head(self):
        """rejudge-diff.json の争点でない変化 1 件 → 冒頭 1 にその単位の key と前後"""
        self.judged()
        before = [{"key": RF.K1, "label": "block"}, {"key": RF.K2, "label": "block"}]
        after = [{"key": RF.K1, "label": "block"}, {"key": RF.K2, "label": "suggest"}]
        row = {"round": 1, "pass": "rejudge", "node": "p2.rejudge", "verdict": "一部採る",
               **rejudge.diff_units(before, after, f"{RF.K1} の分母は正しい", [], ["key", "label"])}
        self.assertEqual(row["unnamed_changed"], [RF.K2])
        b = entry.open_board(self.board)
        b.work(report.REJUDGE_DIFF).write_text(json.dumps([row], ensure_ascii=False), encoding="utf-8")
        lines = report.head_decisions(b, {"accepted": True, "round_closed": True})
        hit = [x for x in lines if RF.K2 in x]
        self.assertEqual(len(hit), 1, lines)
        self.assertIn('"block" → "suggest"', hit[0])

    def test_rejudge_session_stop_asks(self):
        """state.stop.by == works:rejudge-session → stopped_by_line、冒頭 1 に問い、next-request.json に異議の文（字のまま）"""
        self.judged()
        b = entry.open_board(self.board)
        b.loop_state["rejudge_requested"] = {"round": 1, "text": ODD}
        b.save()
        self.stop("判定役の会話を確かめられない", rejudge.STOP_BY_SESSION)
        out, _, h = self.build()
        self.assertEqual(out["outcome"], "stopped_by_line")
        self.assertIn("再審の会話を確かめられずに止めた", h[H1])
        items = json.loads(pathlib.Path(out["next_request_file"]).read_text(encoding="utf-8"))["findings"]
        self.assertIn(ODD, [i["text"] for i in items])

    def test_premises_claims_hypothesis_head(self):
        """依頼の measured を前提の役が仮説でしか書けなかった制約 1 件 → 冒頭 1 に where と「測り直せなかった」"""
        req = [{"where": "stats.py mean", "text": "mean([1, 2, 3]) が 3 を返す", "measured": "python3 -c ... → 3"},
               {"where": "stats.py clamp", "text": "clamp(15, 0, 10) が 0 を返す"}]
        prem = {"constraints": [{"text": "stats.py mean は分母が len(xs) - 1（読んだだけで走らせていない）",
                                 "measured_how": "stats.py を読んだ", "kind": "仮説"}]}
        self.begin(request=req, premises=prem)
        b = entry.open_board(self.board)
        lines = report.head_decisions(b, {"accepted": True, "round_closed": True})
        hit = [x for x in lines if "測り直せなかった" in x]
        self.assertEqual(len(hit), 1, lines)
        self.assertIn("stats.py mean", hit[0])

    def test_head_lists_converge_lines(self):
        """事前審査の壁打ちの往復（converge.lines）の各行は報告の冒頭の決めの節（head_decisions）に並ぶ"""
        self.begin()
        b = entry.open_board(self.board)
        self.assertEqual(converge.lines(b), [])
        face = {"key": "a-key-001", "kind": "regression", "where": "stats.py", "why": "穴", "severity": "block"}
        for _ in range(2):
            converge.record_pass(b, {"faces": [face]}, resolved=[], fence=9, files={})
        want = converge.lines(b)
        self.assertEqual(len(want), 3)
        lines = report.head_decisions(b, {"accepted": True, "round_closed": True})
        for x in want:
            self.assertIn(x, lines)

    def test_head_reads_shows_unchecked_red_green(self):
        """修正の受け付けの束が赤緑を確かめずに通した回（盤面の trace の行）は、冒頭 4 の読みの節（head_reads）に出る"""
        self.begin()
        self.assertFalse(any("事後の関門の束" in x for x in report.head_reads(self.board, RUN_ID)))
        entry.open_board(self.board).trace(report.impact.ACCEPT_GATES_SKIPPED_OP, node="fix", why=["テストの実行器が無い"])
        hit = [x for x in report.head_reads(self.board, RUN_ID) if "事後の関門の束" in x]
        self.assertEqual(len(hit), 1, hit)
        self.assertIn("受け付け 1 回", hit[0])

    def test_head_reads_shows_reads_outside(self):
        """窓の宣言の外の読み（照らしが trace に積んだ scope_read_outside）は冒頭 4 の読みの節に、無くても件数 0 の行が出て、積めば数とパスが載る"""
        self.begin()
        self.without_node_env()
        zero = [x for x in report.head_reads(self.board, RUN_ID) if "宣言の外の読み" in x]
        self.assertEqual(zero, [], "0 件の種は冒頭 4 に並べない（冒頭 1 の合計と仕組みの異常の節が言う）")
        b = entry.open_board(self.board)
        b.trace(scopes.READ_OUTSIDE_OP, scope="fixing", paths=["planning/r1/y.md", "r1/x.json"])
        b.trace(scopes.READ_OUTSIDE_OP, scope="refitting", paths=["fixing/r1/a.md"])
        hit = [x for x in report.head_reads(self.board, RUN_ID) if "宣言の外の読み" in x]
        self.assertEqual(len(hit), 1, hit)
        for part in ("3 件", "fixing: planning/r1/y.md", "fixing: r1/x.json", "refitting: fixing/r1/a.md"):
            self.assertIn(part, hit[0])

    def test_head_reads_shows_required_missing(self):
        """窓の終わりに無かった必須の出力（照らしが trace に積んだ scope_required_missing）は冒頭 4 に、無くても件数 0 の行が出て、積めば数と名が載る（止めない）"""
        self.begin()
        self.without_node_env()
        zero = [x for x in report.head_reads(self.board, RUN_ID) if "必須の出力の欠け" in x]
        self.assertEqual(zero, [], "0 件の種は冒頭 4 に並べない")
        entry.open_board(self.board).trace(scopes.REQUIRED_MISSING_OP, scope="lensing", names=["r1/lens.json"])
        hit = [x for x in report.head_reads(self.board, RUN_ID) if "必須の出力の欠け" in x]
        self.assertEqual(len(hit), 1, hit)
        self.assertIn("1 件 lensing: r1/lens.json", hit[0])

    def test_ci_note_beside_no_adapter(self):
        """adapter optional で CI の役が走った → 冒頭 4 の「包み無し」の行の横（同じ行）に collect.note"""
        self.begin(declared=False, adapter="optional")
        b = entry.open_board(self.board)
        lines = report.head_reads(self.board, RUN_ID, ci={"ok": True, "note": ci_role.NO_ADAPTER_NOTE})
        hit = [x for x in lines if x.startswith("包み無し")]
        self.assertEqual(len(hit), 1, lines)
        self.assertIn(ci_role.NO_ADAPTER_NOTE, hit[0])
        self.assertFalse(any("包みが通っていない" in x for x in lines))
        self.assertTrue(b.state)


# ---------------------------------------------------------------- 次の run に渡す依頼
STRUCTURE_STATE = "structure-state.json"   # 構造の境の節が盤面の根に書く控え {status, reason, design_file, wall_s}
STRUCTURE_HEAD = "## 構造の目"
STRUCTURE_MISSING = "構造の目の行なしで計画した"
DESIGN_ROW = {"unit_id": "stats.py mean: 分母が len(xs) - 1 になっている", "verdict": "汚れる", "faces": [2],
              "evidence": ["/units/0/measure"], "reason": "責務を 2 か所に割る", "chosen": "分母の決めを 1 か所に固める",
              "chosen_reason": "読み直しを割らない", "route": "自分で決める", "route_reason": "形の番号で決まる"}


class StructureCase(ReportBase):
    """報告の「構造の目」の節: 単位ごとの判定・形の番号・根拠・理由（汚れると見た行は避け方）と、構造のブロックで増えた時間の
    1 行。構造のブロックが落ちた周は、盤面の根の控えの印「構造の目の行なしで計画した（理由）」"""

    def put_state(self, status, reason="", design_file=""):
        doc = {"status": status, "reason": reason, "design_file": str(design_file), "wall_s": 12.5}
        (self.board / STRUCTURE_STATE).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def test_rows_and_time_in_report(self):
        self.full()
        design = self.tmp / "design.jsonl"
        design.write_text(json.dumps(DESIGN_ROW, ensure_ascii=False) + "\n", encoding="utf-8")
        self.put_state("ok", design_file=design)
        _, text, hs = self.build()
        self.assertIn(STRUCTURE_HEAD, hs)
        body = hs[STRUCTURE_HEAD]
        for want in (DESIGN_ROW["unit_id"], "汚れる", "/units/0/measure", DESIGN_ROW["reason"], DESIGN_ROW["chosen"], "12.5"):
            self.assertIn(want, body)
        self.assertNotIn(STRUCTURE_MISSING, text)

    def test_failed_structure_marked_in_report(self):
        self.full()
        self.put_state("failed", "構造のブロックの節が落ちた（実測の落ち）")
        _, text, hs = self.build()
        self.assertIn(STRUCTURE_HEAD, hs)
        body = hs[STRUCTURE_HEAD]
        self.assertIn(STRUCTURE_MISSING, body)
        self.assertIn("構造のブロックの節が落ちた（実測の落ち）", body)


class NextRequestCase(ReportBase):
    def declared_board(self, key=None):
        """差分の審査の穴（key）と事前審査の穴を、手直しが両方 declared で残した盤面"""
        repo, _ = self.reviewed() if key is None else self._reviewed_with(key)
        refix.prep_fix(self.board, 1, repo)
        owed = json.loads(pathlib.Path(refix.prep_fix(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))["owed"]
        got = refix.accept_fix({"handled": [{"key": r["key"], "handled": "declared", "how": "誤検知でなく残す: 次の run の判定者に振り分けを任せる"}
                                            for r in owed]}, self.board, "", repo, n=1)
        self.assertTrue(got["ok"], got)
        return repo, [r["key"] for r in owed]

    def _reviewed_with(self, key):
        repo = self.fixed()
        self.assertTrue(refix.cut(self.board, 1, repo)["ok"])
        rv = linekit.reply("fix2_delta_review_faces")
        rv["faces"][0]["key"] = key
        got = refix.accept_review(rv, self.board, "", repo, n=1)
        self.assertTrue(got["ok"], got)
        return repo, got

    def test_next_request_passes_v1_intake(self):
        """declared で残した穴と赤のテスト → next-request.json を一時の盤面で accept.check_request → ok"""
        repo, _ = self.declared_board()
        self.to_end(repo)
        out, _, h = self.build(tests=RED)
        items = json.loads(pathlib.Path(out["next_request_file"]).read_text(encoding="utf-8"))["findings"]
        self.assertGreaterEqual(len(items), 3)
        self.assertTrue(any("赤" in i["text"] for i in items))
        with tempfile.TemporaryDirectory(dir=linekit.work_home()) as d:
            self.assertEqual(accept.check_request(items, pathlib.Path(d), "次の run"), {"ok": True, "reason": ""})
        self.assertIn(f"次の run に渡す物: {len(items)} 件", h[H1])
        self.assertIn("最後のテストが赤", h[H1])

    def test_next_request_carries_failed_lens_not_anomalies_and_red_once(self):
        """next_request は落ちたレンズを「再実行の要あり」の行で運び、trace の異常は運ばず、検証器・独立の目のほかの where の left の
        行も全件運び、最後のテストの赤は二重にならず 1 行になる"""
        self.begin()
        self.without_node_env()
        b = entry.open_board(self.board, allow_halted=True)
        lens.write_routes(b, [{"lens": "silent-failure-hunter", "agent": "a", "go": True}])
        lens.collect(b, {"silent-failure-hunter": None})
        b.trace(scopes.READ_OUTSIDE_OP, scope="fixing", paths=["planning/r1/y.md"])
        left = [{"where": report.VALIDATOR_WHERE, "text": "[block] 未解消: u-a"}, {"where": "別の所", "text": "別の行"},
                {"where": report.EYES_WHERE, "text": "R1 が blocks"}, {"where": RED["log"], "text": "最後のテストが赤"}]
        items = report.next_request(b, tests=RED, left=left)
        texts = [i["text"] for i in items]
        self.assertTrue(any("再実行の要あり" in t and "silent-failure-hunter" in t for t in texts), items)
        self.assertFalse(any("宣言の外の読み" in t or "planning/r1/y.md" in t for t in texts), items)
        for row in left[:3]:
            self.assertIn(row, [{"where": i["where"], "text": i["text"]} for i in items])
        self.assertEqual(len([t for t in texts if t.startswith("最後のテストが赤")]), 1, items)

    def test_next_request_file_carries_left_rows(self):
        """R1 が redesign-needed の独立の目の出口（eyeing）と赤のテストの盤面で build を回すと、next-request.json の findings に
        残りの目の行が where『独立の目 R1』・text『R1 が redesign-needed: …』のまま 1 行で載る。テストの赤は next_request の自前の行
        『最後のテストが赤（…）』の 1 行だけで、residue の『最後のテストが赤』の行は carry_left が落とす（重複落としは仕様）"""
        self.begin()
        self.without_node_env()
        eyeing = {"ok": True, "reason": "", "reviews": {**EYES_PASS, "R1": {"status": "redesign-needed", "reason": "目の見本"}}}
        out, _, _ = self.build(tests=RED, eyeing=eyeing)
        doc = json.loads(pathlib.Path(out["next_request_file"]).read_text(encoding="utf-8"))
        items = [{"where": i["where"], "text": i["text"]} for i in doc["findings"]]
        self.assertEqual([i for i in items if i["where"].startswith(report.EYES_WHERE)],
                         [{"where": f"{report.EYES_WHERE} R1", "text": "R1 が redesign-needed: 目の見本"}])
        reds = [i for i in items if i["text"].startswith(report.TESTS_TEXT)]
        self.assertEqual(reds, [{"where": RED["log"], "text": f"{report.TESTS_TEXT}赤（ログを読む）"}])

    def test_out_of_purpose_rows_are_carried_and_named(self):
        """判定が目的の外と名指した材料の行（outpurpose の控え）は、全部の欄のまま下書きの印（draft・source）つきで
        next-request.json の findings に載り、依頼の入口は印のある行を拒み、印を消した依頼は v1 の受け付けを通り、報告の冒頭 1 が
        次の run に渡す物の下に 1 件ずつ名指す（実の利用者の run f57a5374）"""
        import outpurpose
        self.begin()
        self.without_node_env()
        row = {"where": "app/compute_logs/manager.py:27-58", "text": "[block] 親の __init__ を呼ばない",
               "mechanism": "親のメソッドが未初期化の属性を読む", "measured": "AttributeError を確かめた",
               "false_positive_if": "画面がその問いを投げない版"}
        oop = {"source": "局所の findings（code-reviewer）", "where": row["where"], "why_outside": "凍結した目的は Manifest の世代の順"}
        outpurpose.save(self.board, 1, [oop], [{**row, "from": "p1.local_review"}])
        out, _, h = self.build()
        items = json.loads(pathlib.Path(out["next_request_file"]).read_text(encoding="utf-8"))["findings"]
        got = [i for i in items if i["where"] == row["where"]]
        self.assertEqual(len(got), 1, items)
        self.assertEqual({k: got[0][k] for k in ("mechanism", "measured", "false_positive_if")},
                         {k: row[k] for k in ("mechanism", "measured", "false_positive_if")})
        self.assertIn(outpurpose.MARK, got[0]["text"])
        self.assertIs(got[0]["draft"], True)
        import ghreads
        with self.assertRaises(ValueError):
            ghreads.request_parts({"findings": items})
        items = [{k: v for k, v in i.items() if k not in ghreads.DRAFT_KEYS} for i in items]
        with tempfile.TemporaryDirectory(dir=linekit.work_home()) as d:
            self.assertEqual(accept.check_request(items, pathlib.Path(d), "次の run"), {"ok": True, "reason": ""})
        self.assertIn(outpurpose.REPORT_HEAD, h[H1])
        self.assertIn(f"{row['where']}（出どころ: {oop['source']}", h[H1])

    def test_next_request_keys_roundtrip(self):
        """穴の key に引用符・日本語・$( → next-request.json の text に 1 バイトも同じで在る"""
        _, keys = self.declared_board(ODD_KEY)
        self.assertIn(ODD_KEY, keys)
        out, _, _ = self.build()
        raw = pathlib.Path(out["next_request_file"]).read_bytes()
        items = json.loads(raw.decode("utf-8"))["findings"]
        self.assertTrue(any(ODD_KEY in i["text"] for i in items))
        self.assertIn(json.dumps(ODD_KEY, ensure_ascii=False)[1:-1].encode("utf-8"), raw)


class FinalGateAnswerNextRequestCase(ReportBase):
    """最後の関所の答えは、盤面が人に聞いたままの問いの行に添えて next-request.json に載る"""

    def asked_rows(self, answer_text=None):
        self.planned()
        b = entry.open_board(self.board, allow_halted=True)
        if answer_text is not None:
            b.work(report.FINAL_GATE_ANSWER).write_text(answer_text, encoding="utf-8")
        out, _, h = self.build()
        items = json.loads(pathlib.Path(out["next_request_file"]).read_text(encoding="utf-8"))["findings"]
        question = b.state["pending_human"]["question"]
        return [i for i in items if i["where"].startswith("人の関所")], question, h

    def test_continue_answer_rides_on_the_open_question_row(self):
        """問いが残った盤面に continue「一言」の答え → 問いの行の text に問いの字・continue・一言が載る"""
        answer = json.dumps({"decision": "continue", "text": ODD}, ensure_ascii=False)
        rows, question, _ = self.asked_rows(answer)
        self.assertEqual(len(rows), 1, rows)
        self.assertIn(report._one_line(question), rows[0]["text"])
        self.assertIn("continue", rows[0]["text"])
        self.assertIn(ODD, rows[0]["text"])

    def test_broken_answer_is_unreadable_not_none(self):
        """壊れた答えのファイル → 冒頭 1 に『None「」』を出さず『読めなかった』と言い、問いの行にも『読めなかった』が載る"""
        rows, _, h = self.asked_rows("{壊れた")
        self.assertNotIn("None「」", h[H1])
        self.assertIn("読めなかった", h[H1])
        self.assertEqual(len(rows), 1, rows)
        self.assertIn("読めなかった", rows[0]["text"])

    def test_no_gate_no_answer_adds_nothing(self):
        """関所の文も答えも無い（protected_only の既定。関所が開かないのが正常）→ 冒頭 1 に答えの行は無く、問いの行にも一文を足さない"""
        rows, question, h = self.asked_rows()
        self.assertNotIn("最後の関所の答え", h[H1])
        self.assertEqual(len(rows), 1, rows)
        self.assertNotIn("最後の関所", rows[0]["text"])

    def test_stopped_run_answer_without_decision_is_unreadable(self):
        """decision の無い dict の答え → stopped_run は止まりかを言えず None（旧い式は () だった。decision の無い答えは読めない答えに揃えた）"""
        import tempfile
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / report.FINAL_GATE_ANSWER).write_text('{"text": "一言だけ"}', encoding="utf-8")
            self.assertIsNone(report.stopped_run(d))


# ---------------------------------------------------------------- 費用
class HeadWhereDesignCase(unittest.TestCase):
    """止めた run（修正前の関所で stop）の見る所: 判定・修正案・事前審査と並んで、盤面の根の独立設計（design.json）が載る。
    design.json の無い盤面ではそのパスを出さない"""

    def board(self, tmp):
        import types
        outs = {n: {"file": f"out/r1/{n}.json"} for n in ("p2.diagnose", "p2.fix_plan", "p2.plan_review")}
        return types.SimpleNamespace(dir=tmp, loop_state={}, state={"outputs": outs, "inputs": {"cwd": str(tmp)}})

    def test_stopped_run_lists_the_independent_design(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = pathlib.Path(t)
            (tmp / "design.json").write_text("{}", encoding="utf-8")
            where = report.head_where(self.board(tmp))
            for label in ("判定: ", "修正案: ", "事前審査: "):
                self.assertTrue(any(x.startswith(label) for x in where), (label, where))
            self.assertIn(f"独立設計: {tmp / 'design.json'}", where)

    def test_no_design_file_no_design_path(self):
        with tempfile.TemporaryDirectory() as t:
            tmp = pathlib.Path(t)
            where = report.head_where(self.board(tmp))
            self.assertFalse(any(str(tmp / "design.json") in x for x in where), where)

    def _unanchored(self, reply):
        with tempfile.TemporaryDirectory() as t:
            tmp = pathlib.Path(t)
            (tmp / "design.json").write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
            return report._design_unanchored(self.board(tmp))

    def test_unanchored_premise_is_named(self):
        """独立設計が問いは立たないと返し、根拠にパス:行の名指しが無ければ、冒頭 1 に「根拠の実物の名指しなし」の 1 行"""
        got = self._unanchored({"question_stands": False, "reason": "立たない", "premise_invalid_reason": "識別子は既にある",
                                "design": ""})
        self.assertEqual(len(got), 1, got)
        self.assertIn("根拠の実物の名指しなし", got[0])
        self.assertIn("識別子は既にある", got[0])

    def test_anchored_or_standing_design_adds_nothing(self):
        self.assertEqual(self._unanchored({"question_stands": False, "reason": "立たない",
                                           "premise_invalid_reason": "docs/spec.md:2 に在る", "design": ""}), [])
        self.assertEqual(self._unanchored({"question_stands": True, "reason": "立つ", "design": "x"}), [])


class CostCase(unittest.TestCase):
    # 節の費用は data.spend.costUsd（Archon v0.11.1）。ここの見本は有限の数の形（実物の {source: provider, value} の形は test_cost_from_real_rows）
    EVENTS = [{"event_type": "node_completed", "step_name": "judging__judge-loop.judge", "data": {"spend": {"costUsd": 0.0284}}},
              {"event_type": "node_completed", "step_name": "rejudging__rj-loop.rejudge", "data": {"spend": {"costUsd": 0.0615}}},
              {"event_type": "node_started", "step_name": "x", "data": {"spend": {"costUsd": 9}}}]
    LAUNCHES = [{"at": "2026-09-27T10:00:00+09:00", "node": "judge", "session": {"mode": "new", "id": "S1"}},
                {"at": "2026-09-27T10:05:00+09:00", "node": "rejudge",
                 "session": {"mode": "continued", "id": "S1", "of": "judge", "from": "S1"}}]

    def test_cost_continued_not_subtracted(self):
        """出来事の見本（judge 0.0284・rejudge 0.0615）と launches（rejudge が continued of judge・同じ id）→ rejudge の actual は
        表示のまま 0.0615（costUsd が累積か 1 回分かは測れていない）、行に「judge の会話を継いだ」と「累積かどうか未確認」"""
        rows = {r["node"]: r for r in report.cost_rows(self.EVENTS, self.LAUNCHES)}
        self.assertEqual(rows["rejudge"]["actual"], 0.0615)
        self.assertEqual((rows["rejudge"]["continued_from"], rows["judge"]["actual"]), ("judge", 0.0284))
        lines = report.head_cost(None, RUN_ID, events=self.EVENTS, launches=self.LAUNCHES)
        hit = [x for x in lines if x.startswith("費用 rejudge:")]
        self.assertEqual(len(hit), 1, lines)
        self.assertIn("judge の会話を継いだ", hit[0])
        self.assertIn("累積かどうか未確認", hit[0])
        self.assertNotIn("欄の形は未確認", hit[0])   # 欄の形は実物で確かめた（test_cost_from_real_rows）
        self.assertTrue(report.COST_FIELD_VERIFIED)

    def test_cost_from_real_rows(self):
        """節の費用の欄の実物（tests/events/db-rows-plan.json。canary の archon.db の node_completed）は
        data.spend.costUsd = {source: provider, value: 数}。その値を節の費用に読み、「欄の形は未確認」を添えない"""
        evs = json.loads((TESTS / "events" / "db-rows-plan.json").read_text(encoding="utf-8"))["events"]
        self.assertEqual([(r["node"], r["reported"]) for r in report.cost_rows(evs, [])], [("plan", 0.2694523)])
        lines = report.head_cost(None, RUN_ID, events=evs, launches=[])
        self.assertTrue(any(x.startswith("費用 plan: 0.2694523 USD") for x in lines), lines)
        self.assertFalse(any("欄の形は未確認" in x for x in lines), lines)

    def test_cost_unavailable_line(self):
        """events None → 費用の行が「取れない」の 1 行。費用の欄の無い出来事も 1 行"""
        for events in (None, [{"event_type": "node_completed", "step_name": "a", "data": {}}]):
            with self.subTest(events=events):
                lines = report.head_cost(None, RUN_ID, events=events, launches=self.LAUNCHES)
                self.assertEqual(len(lines), 1)
                self.assertIn("取れない", lines[0])
        self.assertEqual(report.cost_rows(None, self.LAUNCHES), [])


# ---------------------------------------------------------------- 名前の揃い・スクリプト・dev の殻
class NamesCase(unittest.TestCase):
    def test_board_names_match_writers(self):
        """報告が読む盤面の上の名前が書き手の模块と同じ（層 L3 は書き手を import しないので、ここで突き合わせる）"""
        sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
        try:
            import line_edge
        finally:
            sys.path.remove(str(ROOT / "darkfactory" / "lib"))
        self.assertEqual(report.FLAG_SEEN_OP, line_edge.FLAG_SEEN_OP)
        self.assertEqual(report.REQUEST_BY, line_edge.FLAG_BY_PREFIX)
        for name, want in (("FINAL_GATE_ANSWER", "final-gate-answer.json"), ("FINAL_GATE_BY", "human:final-gate")):
            self.assertEqual(getattr(report, name), want)
            if hasattr(line_edge, name):   # P1 Task 26 の後
                self.assertEqual(getattr(report, name), getattr(line_edge, name))
        self.assertEqual(report.PR_EXCLUDED, prcheck.EXCLUDED)
        self.assertEqual(report.PR_NODE, prcheck.NODE)
        self.assertEqual(report.DOWNGRADE_KEYS, prcheck.DOWNGRADE_KEYS)
        self.assertEqual(report.REJUDGE_DIFF, rejudge.DIFF_NAME)
        self.assertEqual(report.REJUDGE_SESSION_BY, rejudge.STOP_BY_SESSION)
        self.assertEqual(report.ADAPTER_BY, ci_role.FENCE_BY)
        self.assertEqual(report.declared_downgrades("darkfactory"), prcheck.downgrades("darkfactory"))
        self.assertEqual(report.declared_downgrades("no-such-line"), [])
        # 読んだ証拠の索引の名（blk-plan と案の直しが書く）は head_reads が飛ばす索引（reads.is_index）で、役の reads-<役>.json は索引でない
        sys.path.insert(0, str(ROOT / "blk-plan" / "lib"))
        try:
            import planblk
        finally:
            sys.path.remove(str(ROOT / "blk-plan" / "lib"))
        for index in (planblk.READS_INDEX, replan.READS_INDEX):
            self.assertTrue(reads.is_index(index), index)
        self.assertFalse(reads.is_index(reads.evidence_name("plan")))


class ScriptCase(ReportBase):
    def run_script(self, art=None, **env_over):
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        env.update({"INPUTS_JUDGED": "null", "INPUTS_TESTS": "null", "INPUTS_START": "null",
                    "INPUTS_CI": "null", "INPUTS_EYES": json.dumps({"go": False}), "INPUTS_EYEING": "null",
                    "ARTIFACTS_DIR": str(art or self.art), "WORKFLOW_ID": RUN_ID,
                    "PYTHONDONTWRITEBYTECODE": "1"})
        env.update(env_over)
        env = {k: v for k, v in env.items() if v is not None}
        return subprocess.run([sys.executable, str(SCRIPT)], env=env, capture_output=True, text=True, encoding="utf-8",
                              stdin=subprocess.DEVNULL, cwd=str(self.tmp))

    def test_script_one_line_and_inputs(self):
        """INPUTS の組、1 行の JSON と 0（record_invalid も 0）。中の検査の枠の行はもう出さない"""
        self.judged()
        spec = importlib.util.spec_from_file_location("_report_script", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.INPUTS, ("INPUTS_JUDGED", "INPUTS_TESTS", "INPUTS_START", "INPUTS_CI",
                                      "INPUTS_EYES", "INPUTS_EYEING", "INPUTS_CLEANED_RUNS", "INPUTS_DEPTH",
                                      "INPUTS_FIX_TDD", "INPUTS_REFIT_TDD"))
        r = self.run_script(INPUTS_JUDGED=json.dumps(judged_out(self.board)), INPUTS_TESTS=json.dumps(RED),
                            INPUTS_CI="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(r.stdout.splitlines()), 1)
        out = json.loads(r.stdout)
        self.assertEqual(out["outcome"], "record_invalid")
        self.assertEqual(out["export_input"]["board_dir"], str(self.board.resolve()))
        self.assertNotIn("中の検査の枠", pathlib.Path(out["report_file"]).read_text(encoding="utf-8"))

    def test_script_cleaned_runs_reach_report(self):
        """入力 cleaned_runs（文字列。JSON でない）は報告の冒頭 2 に届く。前の版の with: で再開した run は渡さないので、無くても 0"""
        self.judged()
        r = self.run_script(INPUTS_JUDGED=json.dumps(judged_out(self.board)), INPUTS_CLEANED_RUNS="run-f（failed）")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"{report.CLEANED_HEAD}: run-f（failed）",
                      pathlib.Path(json.loads(r.stdout)["report_file"]).read_text(encoding="utf-8"))
        r = self.run_script(INPUTS_JUDGED=json.dumps(judged_out(self.board)), INPUTS_CLEANED_RUNS=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(report.CLEANED_HEAD, pathlib.Path(json.loads(r.stdout)["report_file"]).read_text(encoding="utf-8"))

    def test_script_depth_reaches_report(self):
        """入力 depth（h-redepth の出口の JSON）の lines は報告の冒頭 2 に届く。前の版の with: で再開した run は渡さないので、無くても 0"""
        self.judged()
        depth_out = {"ok": True, "why": "", "depth": "軽量", "unit_depths": "{}", "skip": "x", "depth_file": "",
                     "lines": ["深さ: 軽量（試し）", "軽量で省いた: レンズ（試し）"]}
        r = self.run_script(INPUTS_JUDGED=json.dumps(judged_out(self.board)), INPUTS_DEPTH=json.dumps(depth_out, ensure_ascii=False))
        self.assertEqual(r.returncode, 0, r.stderr)
        text = pathlib.Path(json.loads(r.stdout)["report_file"]).read_text(encoding="utf-8")
        self.assertIn("軽量で省いた: レンズ（試し）", text)
        r = self.run_script(INPUTS_JUDGED=json.dumps(judged_out(self.board)), INPUTS_DEPTH=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("軽量で省いた", pathlib.Path(json.loads(r.stdout)["report_file"]).read_text(encoding="utf-8"))

    def test_script_tdd_outcomes_reach_report(self):
        """keep-essence の 11: 修正の段ごとの TDD の輪の単位の結末（修正のブロックの出口 tdd）が報告に届く。輪を回していない段は
        回していないと理由つきで言う（黙らない）。前の版の with: で再開した run は渡さないので、無くても 0 で節を出さない"""
        self.judged()
        r = self.run_script(INPUTS_JUDGED=json.dumps(judged_out(self.board)),
                            INPUTS_FIX_TDD=json.dumps(TDD_RAN, ensure_ascii=False), INPUTS_REFIT_TDD=json.dumps(TDD_OFF, ensure_ascii=False))
        self.assertEqual(r.returncode, 0, r.stderr)
        text = pathlib.Path(json.loads(r.stdout)["report_file"]).read_text(encoding="utf-8")
        self.assertIn(report.TDD_HEADING, text)
        h = heads(text)
        self.assertIn(report.FREEZE_OFF_HEAD, h[H2])   # 2 つ目の段は輪を回していない: 冒頭 2 で凍結が効いていないと言う
        for line in report.tdd_lines([(report.TDD_STAGES[0], TDD_RAN), (report.TDD_STAGES[1], TDD_OFF)]):
            self.assertIn(line, text)
        r = self.run_script(INPUTS_JUDGED=json.dumps(judged_out(self.board)), INPUTS_FIX_TDD=None, INPUTS_REFIT_TDD=None)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn(report.TDD_HEADING, pathlib.Path(json.loads(r.stdout)["report_file"]).read_text(encoding="utf-8"))

    def test_script_interrupted_by_missing_exit_marks(self):
        """上流の節が落ちた run（run 30・31 の形）: 出来事が取れなくても、h-eyes の出口が無い・目を回すと言ったのに blk-eyes の
        出口が無いなら、結末 interrupted の報告と次の依頼を書き、冒頭 3 に届かなかった節を出す。AI の報告は回さない"""
        self.judged()
        for eyes, node in (("null", "h-eyes"), (json.dumps({"go": True}), "eyeing")):
            with self.subTest(node):
                r = self.run_script(INPUTS_JUDGED=json.dumps(judged_out(self.board)), INPUTS_EYES=eyes,
                                    INPUTS_EYEING="null")
                self.assertEqual(r.returncode, 0, r.stderr)
                out = json.loads(r.stdout)
                self.assertEqual(out["outcome"], "interrupted")
                self.assertIs(out["ai_report_go"], False)
                self.assertTrue(pathlib.Path(out["next_request_file"]).is_file())
                h = heads(pathlib.Path(out["report_file"]).read_text(encoding="utf-8"))
                self.assertIn(f"{report.INTERRUPTED_HEAD}: 節 {node} が落ちた", h[H3])

    def test_script_errors(self):
        """盤面が開けない → 1（stderr に 1 行・stdout は空）。環境変数の欠け・読めない JSON → 2"""
        empty = self.tmp / "empty-art"
        empty.mkdir()
        r = self.run_script(art=empty)
        self.assertEqual((r.returncode, r.stdout), (1, ""), r.stderr)
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        r = self.run_script(art=empty, INPUTS_TESTS=None)
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertIn("INPUTS_TESTS", r.stderr)
        r = self.run_script(art=empty, INPUTS_JUDGED="{壊れた")
        self.assertEqual((r.returncode, r.stdout), (2, ""))


class ReportShCase(ReportBase):
    RUN = json.loads((EVENTS / "get-running.json").read_text(encoding="utf-8"))["id"]

    def fake_archon(self, root, status):
        doc = json.loads((EVENTS / "get-running.json").read_text(encoding="utf-8"))
        doc.update(output_root=str(root), status=status)
        out = self.tmp / "get.json"
        out.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        fake = self.tmp / "fake-archon.sh"
        fake.write_text(f'#!/bin/sh\ncat "{out}"\n', encoding="utf-8")
        return fake

    def test_report_sh_after_cancel(self):
        """盤面だけ残った run（halted でない）に report.sh → report.md ができ、outcome interrupted、冒頭 3 に「途中で終わった」と
        Archon の run の状態。記録の関所も通す（冒頭の後に検証器の終了コード）"""
        root = self.tmp / "archon-out"
        self.begin(board=root / "artifacts" / "runs" / self.RUN / "board")
        self.assertFalse(json.loads((self.board / "state.json").read_text(encoding="utf-8")).get("halted"))
        env = hermetic.child_env(WORKS_DEV_ARCHON=str(self.fake_archon(root, "cancelled")), PYTHONDONTWRITEBYTECODE="1")
        r = subprocess.run(["sh", str(REPORT_SH), self.RUN], capture_output=True, text=True, encoding="utf-8", env=env, stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout.strip().splitlines()[-1])
        self.assertEqual(out["outcome"], "interrupted")
        text = (self.board / "report.md").read_text(encoding="utf-8")
        h = heads(text)
        self.assertIn(report.INTERRUPTED_HEAD, h[H3])
        self.assertIn("Archon の run の状態は cancelled", h[H3])
        self.assertIn("終了コード: ", text)

    def test_report_sh_refuses(self):
        """run id が無い・盤面が無い → 2、何も書かない"""
        env = hermetic.child_env(WORKS_DEV_ARCHON=str(self.fake_archon(self.tmp / "nowhere", "cancelled")))
        for args in ((), (self.RUN,)):
            with self.subTest(args=args):
                r = subprocess.run(["sh", str(REPORT_SH), *args], capture_output=True, text=True, encoding="utf-8", env=env,
                                   stdin=subprocess.DEVNULL)
                self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
                self.assertTrue(r.stderr.strip())


# ---------------------------------------------------------------- 前の run の落ちた理由（prior_failures）
R2_ROW = {"where": report.EYES_WHERE + " R2", "text": "R2 が redesign-needed: 独立設計と構造が合わない"}


def write_last(root: pathlib.Path, rows: dict) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "accept-last.json").write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")


# 修正のブロックの出口 tdd の見本（tddloop.exit_fields の形）: 赤→緑の単位・TDD を諦めた単位・初めから今どおりの単位・止めた単位
TDD_RAN = {"ran": True, "suite": "tests/run.sh", "reason": "", "test_cmd": {"gate": "off", "note": ""}, "calls": [],
           "units": [{"unit_key": "u-green", "route": "tdd", "why": "", "tests": ["t.py::test_a"], "red": "ok", "green": "ok",
                      "refactor": "none", "gave_up": ""},
                     {"unit_key": "u-gave", "route": "direct", "why": "赤が error で落ちた", "tests": [], "red": "", "green": "",
                      "refactor": "", "gave_up": "test"},
                     {"unit_key": "u-direct", "route": "direct", "why": "文書だけの直し", "tests": [], "red": "", "green": "",
                      "refactor": "", "gave_up": ""},
                     {"unit_key": "u-parked", "route": "parked", "why": "依頼とテストが食い違う", "tests": [], "red": "",
                      "green": "", "refactor": "", "gave_up": ""}]}
TDD_OFF = {"ran": False, "suite": "", "reason": "テストの実行器（入力 tdd_suite）が無い", "units": []}


class TddLinesCase(unittest.TestCase):
    """keep-essence の 11: TDD の輪の単位ごとの結末を報告の行にする（report.tdd_lines）"""

    def test_each_unit_gets_its_outcome(self):
        rows = report.tdd_lines([(report.TDD_STAGES[0], TDD_RAN)])
        self.assertIn("4 単位", rows[0])
        self.assertTrue(rows[0].startswith(report.TDD_STAGES[0]))
        body = "\n".join(rows[1:])
        for key in ("u-green", "u-gave", "u-direct", "u-parked"):
            self.assertEqual(sum(key in r for r in rows[1:]), 1, key)
        self.assertIn("t.py::test_a", body)
        self.assertIn("赤が error で落ちた", body)
        self.assertIn("依頼とテストが食い違う", body)
        self.assertTrue(all(r.startswith("  - ") for r in rows[1:]))

    def test_stage_without_loop_says_why(self):
        rows = report.tdd_lines([(report.TDD_STAGES[0], TDD_OFF)])
        self.assertEqual(len(rows), 1)
        self.assertIn("回していない", rows[0])
        self.assertIn(TDD_OFF["reason"], rows[0])

    def test_head_names_stages_without_freeze(self):
        """keep-essence の 3: TDD の輪を回していない修正の段は、テストの凍結が効いていないと冒頭 2 の行で理由つきで言う（黙らない）"""
        rows = report.freeze_lines([(report.TDD_STAGES[0], TDD_OFF), (report.TDD_STAGES[1], None)])
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0].startswith(report.FREEZE_OFF_HEAD), rows)
        self.assertIn(report.TDD_STAGES[0], rows[0])
        self.assertIn(TDD_OFF["reason"], rows[0])
        self.assertEqual(report.freeze_lines([(report.TDD_STAGES[0], TDD_RAN), (report.TDD_STAGES[1], None)]), [])
        self.assertEqual(report.freeze_lines([]), [])

    def test_stages_that_did_not_run_are_left_out(self):
        self.assertEqual(report.tdd_lines([(report.TDD_STAGES[0], None), (report.TDD_STAGES[1], None)]), [])
        self.assertEqual(len(report.tdd_lines([(report.TDD_STAGES[0], None), (report.TDD_STAGES[1], TDD_OFF)])), 1)


class PriorFailuresUnitCase(unittest.TestCase):
    """盤面の根と include の scope の根の accept-last.json から、最後まで通らなかった受け付けだけを集める（盤面・git を使わない）"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.board = pathlib.Path(self._tmp.name) / "board"
        self.board.mkdir()
        self.addCleanup(self._tmp.cleanup)
        self.b = types.SimpleNamespace(dir=self.board, round=1)

    def test_only_last_not_ok_rows_from_every_scope_root(self):
        rf = self.board / "reject-take_p2_diagnose-3.txt"
        rf.write_text("型に合わない:\n  units が無い", encoding="utf-8")
        write_last(self.board, {"take_p2_diagnose": {"ok": False, "reason_file": str(rf), "reason": "古い写し", "at": "t"},
                                "take_p0_premises": {"ok": True, "reason_file": "", "reason": "", "at": "t"}})
        write_last(self.board / "fixing", {"accept_fix": {"ok": False, "reason_file": "", "reason": "テストが赤", "at": "t"}})
        write_last(self.board / "refitting", {"accept_fix": {"ok": True, "reason_file": "", "reason": "", "at": "t"}})
        got = report.prior_failures(self.b)
        self.assertEqual(got, [{"where": "受け付け take_p2_diagnose", "text": "型に合わない: units が無い"},
                               {"where": "受け付け accept_fix（fixing）", "text": "テストが赤"}])

    def test_r2_redesign_rides_only_on_prior_failures(self):
        other = {"where": "別の所", "text": "別の行"}
        got = report.prior_failures(self.b, left=[other, R2_ROW,
                                                  {"where": report.VALIDATOR_WHERE, "text": R2_ROW["text"]}])
        self.assertEqual(got, [R2_ROW])

    def test_unreadable_accept_last_is_a_row(self):
        (self.board / "fixing").mkdir()
        (self.board / "fixing" / "accept-last.json").write_text("{", encoding="utf-8")
        got = report.prior_failures(self.b)
        self.assertEqual(len(got), 1)
        self.assertIn("読めない", got[0]["text"])


class PriorFailuresBuildCase(ReportBase):
    """build が prior-failures.json と {findings, prior_failures} の next-request.json を書き、報告に 1 節を出す"""
    build_with = ResidueCase.build_with
    build_eyeing = ResidueCase.build_eyeing

    def test_build_writes_prior_failures_and_object_request(self):
        self.full()
        write_last(self.board, {"take_p2_fix_plan": {"ok": False, "reason_file": "", "reason": "案の欄が欠ける", "at": "t"}})
        eyeing = {"ok": True, "reason": "", "reviews": {**EYES_PASS, "R2": {"status": "redesign-needed",
                                                                             "reason": "独立設計と構造が合わない"}}}
        out, text, h = self.build_eyeing(eyeing)
        doc = json.loads(pathlib.Path(out["next_request_file"]).read_text(encoding="utf-8"))
        self.assertEqual(set(doc), {"findings", "prior_failures"})
        from engine.schema import validate_schema
        for name, got in (("next-request", doc), ("prior-failures", doc["prior_failures"])):
            schema = json.loads((ROOT / "darkfactory" / "schemas" / f"{name}.schema.json").read_text(encoding="utf-8"))
            self.assertEqual(validate_schema(got, schema), [], name)
        want = [{"where": "受け付け take_p2_fix_plan", "text": "案の欄が欠ける"}, R2_ROW]
        self.assertEqual(doc["prior_failures"], want)
        self.assertFalse(any(i["text"].startswith("R2 が redesign-needed") for i in doc["findings"]), doc["findings"])
        self.assertEqual(json.loads((self.board / report.PRIOR_FAILURES_FILE).read_text(encoding="utf-8")), want)
        self.assertEqual(out["prior_failures_file"], str(self.board / report.PRIOR_FAILURES_FILE))
        sec = h[report.PRIOR_HEADING]
        self.assertIn("2 件", sec)
        self.assertIn("案の欄が欠ける", sec)
        # 書いた next-request.json は依頼の型の正本が読める（次の run の依頼にそのまま使える）
        import ghreads
        parts = ghreads.request_parts(doc)
        self.assertEqual((parts["findings"], parts["prior_failures"]), (doc["findings"], want))

    def test_no_failures_still_object(self):
        self.full()
        out, _, h = self.build_eyeing({"ok": True, "reason": "", "reviews": EYES_PASS})
        doc = json.loads(pathlib.Path(out["next_request_file"]).read_text(encoding="utf-8"))
        self.assertEqual(doc["prior_failures"], [])
        self.assertIn("0 件", h[report.PRIOR_HEADING])

if __name__ == "__main__":
    unittest.main()
