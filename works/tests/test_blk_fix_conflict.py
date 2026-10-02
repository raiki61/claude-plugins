"""食い違いの申し出（修正役・TDD の輪の役の出口）と裁定の輪の検査（持ち主 2026-09-28「おしで」。ImpossibleBench arXiv 2510.20270）。

- 受け付け（fix-accept）: 名指しが現物に在る申し出は拒否に数えず、その単位を止め（parked）、盤面には渡さない（裁定の後に渡す）。
  名指しが無い所を指す申し出は普通の拒否（reason_file。R44）
- 裁定の輪（rule-prep → rule → rule-accept）: 読むだけの役の返答を確かめ、裁定を盤面の控えと trace に積む。fix_test_scope・fix_code_as
  は裁定の文のファイルを 2 回目の修正役（fix-ruled）の指示書の 1 行目で名指す。3 回とも通らなければ人へ（ask_human。R50）
- ask_human: 直す義務から外れ（写しの RL の _owed_units の差し替え）、最後の人の関所を when_needed でも開き、報告の冒頭 1 に件数と
  次の run の依頼（next-request.json）に載る。fix_test_scope が許したテストの変更は守りのファイルの行として関所に並ぶ
- TDD の輪: phase conflict は拒否に数えず単位を止める。名指しの誤りは普通の拒否
- YAML: 裁定の輪は AI の節が 1 つ（TA13）・done の印で抜ける（R50）・読むだけ。2 回目の修正役は修正役の会話の続き（印 continue=fix）
"""
import json
import os
import pathlib
import sys
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-fix"
CORE = ROOT / ".shared" / "core"
TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(BLK / "lib"))
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(TESTS))

import board  # noqa: E402
import conflict  # noqa: E402
import entry  # noqa: E402
import planmarks  # noqa: E402
from test_blk_fix import (BoardCase, CLAMP, FIXED, MEAN, block, board_shas, find_node, load, run_script)  # noqa: E402
from test_blk_fix_tdd import LoopCase  # noqa: E402

DEADLINE = 1728000000
WHY = "テストは分母 len(xs) - 1 の値を期待しているが、依頼は算術平均を求めている"
MEAN_FIX = {"sum(xs) / (len(xs) - 1)": "sum(xs) / len(xs)"}
CLAMP_FIX = {"    if x > hi:\n        return lo": "    if x > hi:\n        return hi"}
RULE_TEXT = "依頼は算術平均。test_mean_of_three の期待は正しいので、コードの分母を len(xs) に直せ"


def conflict_on_mean(*cites):
    return {"unit_key": MEAN, "between": list(cites or ("stats.py:9", "test_stats.py:9")), "why_both_cannot_hold": WHY,
            "which_is_right": "request", "kind": "unnamed_test_broke"}


def only_clamp_reply(conflicts=None):
    """fix2_ok の clamp の行だけ（mean は申し出た）。conflicts を渡せば欄に置く"""
    reply = load("fix2_ok")
    reply["changes"] = [c for c in reply["changes"] if c["unit_key"] == CLAMP]
    reply["interactions"] = []
    if conflicts is not None:
        reply["conflicts"] = conflicts
    return reply


class ConflictBoardCase(BoardCase):
    def accept_script(self, reply, *, iteration="1", pass_="first"):
        env = {"INPUTS_REPLY": json.dumps(reply, ensure_ascii=False), "INPUTS_BASE_REV": "", "INPUTS_TDD_STATE": "",
               "INPUTS_ITERATION": iteration, "INPUTS_PASS": pass_, "ARTIFACTS_DIR": str(self.art),
               "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"]}
        code, out, err = run_script("accept", self.repo, env)
        self.assertEqual(code, 0, err)
        return json.loads(out)

    def items(self):
        import conflict
        return conflict.items(entry.open_board(self.board, allow_halted=True))

    def trace_ops(self):
        rows = [json.loads(x) for x in (self.board / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        return [r for r in rows if r.get("op", "").startswith("conflict_")]

    def parked(self):
        """修正役が clamp を直し、mean を申し出た盤面（1 回目の受け付けが止めた）"""
        self.fix_ready()
        self.edit_tree(CLAMP_FIX)
        r = self.accept_script(only_clamp_reply([conflict_on_mean()]))
        self.assertEqual((r["ok"], r.get("parked")), (True, True), r)
        return r

    def rule_env(self, reply=None, iteration="1"):
        env = {"ARTIFACTS_DIR": str(self.art), "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"],
               "INPUTS_JUDGMENT_FILE": str(self.board / entry.open_board(self.board).state["outputs"]["p2.diagnose"]["file"]),
               "INPUTS_POLICY_PATH": "", "INPUTS_BASE_REV": "", "INPUTS_ITERATION": iteration}
        if reply is not None:
            env["INPUTS_REPLY"] = json.dumps(reply, ensure_ascii=False)
        return env

    def rule(self, rulings, iteration="1"):
        code, out, err = run_script("rule_prep", self.repo, self.rule_env(iteration=iteration))
        self.assertEqual(code, 0, err)
        prep = json.loads(out)
        code, out, err = run_script("rule_accept", self.repo, self.rule_env({"rulings": rulings}, iteration))
        self.assertEqual(code, 0, err)
        return prep, json.loads(out)


class TestAcceptConflict(ConflictBoardCase):
    def test_valid_conflict_parks_unit_and_is_not_a_reject(self):
        """3 回目の起動でも、名指しの在る申し出は拒否に数えない（ok・done・parked）。盤面には渡さず p3.fix は待ちのまま、控えと trace に残る"""
        self.fix_ready()
        self.edit_tree(CLAMP_FIX)
        r = self.accept_script(only_clamp_reply([conflict_on_mean()]), iteration="3")
        self.assertEqual((r["ok"], r["done"], r["parked"], r["reason_file"]), (True, True, True, ""))
        self.assertEqual(r["changes"], [])
        self.assertEqual(list(self.board.glob("reject-accept_fix-*.txt")), [], "拒否の理由のファイルを書かない")
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending", "裁定の後に渡す")
        rows = self.items()
        self.assertEqual([(i["unit_key"], i["status"], i["source"], i["ruling"]) for i in rows], [(MEAN, "parked", "fix", None)])
        self.assertEqual([t["op"] for t in self.trace_ops()], ["conflict_parked"])
        import conflict
        saved = json.loads(entry.open_board(self.board).work(conflict.PARKED_REPLY).read_text(encoding="utf-8"))
        self.assertEqual(saved["conflicts"], [conflict_on_mean()], "申し出の回の返答を控える（2 回目の修正役が読む）")

    def test_fake_citation_is_a_normal_reject(self):
        """名指しの行がファイルに無い・無いファイル → 普通の拒否（reason_file に本文。控えは書かない）"""
        self.fix_ready()
        self.edit_tree(CLAMP_FIX)
        before = board_shas(self.board)
        r = self.accept_script(only_clamp_reply([conflict_on_mean("stats.py:99", "no_such_test.py:1")]))
        self.assertFalse(r["ok"], r)
        body = pathlib.Path(r["reason_file"]).read_text(encoding="utf-8")
        for w in ("stats.py:99", "行がファイルに無い", "no_such_test.py:1", "ファイルが無い"):
            self.assertIn(w, body)
        after = board_shas(self.board)
        after.pop(str(pathlib.Path(r["reason_file"]).relative_to(self.board)))
        self.assertEqual(after, before, "拒んだ申し出は盤面を書かない")

    def test_conflict_outside_owed_units_is_rejected(self):
        self.fix_ready()
        r = self.accept_script(only_clamp_reply([{**conflict_on_mean(), "unit_key": "作り話の単位"}]))
        self.assertFalse(r["ok"])
        self.assertIn("直す義務の単位に無い", r["reason"])

    def test_request_line_citation_resolves(self):
        """依頼の行（run の依頼のファイルの絶対パス:行）を名指せる。行が無ければ拒む"""
        self.fix_ready()
        self.edit_tree(CLAMP_FIX)
        req = str(self.tmp / "request.json")
        r = self.accept_script(only_clamp_reply([conflict_on_mean(f"{req}:999", "test_stats.py:9")]))
        self.assertFalse(r["ok"])
        self.assertIn("行がファイルに無い", r["reason"])
        r = self.accept_script(only_clamp_reply([conflict_on_mean(f"{req}:1", "test_stats.py:9")]))
        self.assertEqual((r["ok"], r["parked"]), (True, True), r)


class TestRuling(ConflictBoardCase):
    def test_fix_code_as_returns_unit_to_fixer_with_reason_file(self):
        """裁定 fix_code_as → 控えと trace に積み、2 回目の修正役の指示書の 1 行目が裁定の文のファイルを名指す（R44）。
        修正役が裁定どおり直した返答は盤面が受ける"""
        self.parked()
        cid = self.items()[0]["id"]
        prep, r = self.rule([{"id": cid, "decision": "fix_code_as", "text": RULE_TEXT, "limits": ["stats.py:9"]}])
        self.assertIn(cid, pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8"))
        self.assertEqual((r["ok"], r["done"], r["reason_file"]), (True, True, ""), r)
        self.assertEqual(r["counts"], {"parked": 1, "unruled": 0, "fix_test_scope": 0, "fix_code_as": 1, "ask_human": 0})
        self.assertEqual(self.items()[0]["ruling"]["decision"], "fix_code_as")
        self.assertEqual([t["op"] for t in self.trace_ops()], ["conflict_parked", "conflict_ruled"])
        rulings = pathlib.Path(r["rulings_file"])
        self.assertIn(RULE_TEXT, rulings.read_text(encoding="utf-8"))
        code, out, err = run_script("fix_prep", self.repo, {
            "ARTIFACTS_DIR": str(self.art), "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"], "INPUTS_PASS": "ruled",
            **{f"INPUTS_{k.upper()}": v for k, v in {"judgment_file": "", "open_units": json.dumps([MEAN, CLAMP]),
                                                    "plan_file": "", "policy_path": "", "notes_file": "", "summary_file": ""}.items()}})
        self.assertEqual(code, 0, err)
        p = json.loads(out)
        prompt = pathlib.Path(p["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(str(rulings), prompt.split("\n")[1], "裁定の文のファイルを見出しの次の 1 行で名指す")
        self.assertNotIn(RULE_TEXT, prompt, "裁定の文は貼らない（R44）")
        self.assertEqual(p["iteration"], 1)
        self.edit_tree(MEAN_FIX)
        r = self.accept_script(load("fix2_ok"), pass_="ruled")
        self.assertEqual((r["ok"], r.get("parked")), (True, None), r)
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "done")

    def test_ruler_must_not_move_the_tree(self):
        """裁定役は読むだけ: 支度の後に作業ツリーが変われば拒む（共有の accept.tree_moved。R47）"""
        self.parked()
        cid = self.items()[0]["id"]
        code, out, err = run_script("rule_prep", self.repo, self.rule_env())
        self.assertEqual(code, 0, err)
        (self.repo / "stats.py").write_text("x = 1\n", encoding="utf-8")
        code, out, err = run_script("rule_accept", self.repo, self.rule_env(
            {"rulings": [{"id": cid, "decision": "fix_code_as", "text": RULE_TEXT, "limits": []}]}))
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertFalse(r["ok"])
        self.assertIn("読むだけ", r["reason"])
        self.assertIsNone(self.items()[0]["ruling"])

    def test_bad_ruling_rejected_then_gives_up_to_human(self):
        """知らない id・範囲の無い fix_test_scope は拒む。3 回目の拒否で、裁かれていない申し出を人へ（ask_human。R50）"""
        self.parked()
        cid = self.items()[0]["id"]
        _, r = self.rule([{"id": cid, "decision": "fix_test_scope", "text": RULE_TEXT, "limits": []}])
        self.assertEqual((r["ok"], r["done"]), (False, False))
        self.assertIn("範囲", r["reason"])
        _, r = self.rule([{"id": "c9-9", "decision": "ask_human", "text": RULE_TEXT, "limits": []}], iteration="3")
        self.assertEqual((r["ok"], r["done"]), (False, True))
        self.assertEqual(self.items()[0]["ruling"]["decision"], "ask_human")
        self.assertEqual(r["counts"]["ask_human"], 1)

    def test_fix_test_scope_lists_test_as_protected_at_final_gate(self):
        """fix_test_scope が許したテストの変更は、最後の関所で守りのファイルの行として並び、関所を when_needed でも開く"""
        import line_edge
        self.parked()
        cid = self.items()[0]["id"]
        _, r = self.rule([{"id": cid, "decision": "fix_test_scope", "text": RULE_TEXT, "limits": ["test_stats.py:9"]}])
        self.assertTrue(r["ok"], r)
        path = self.repo / "test_stats.py"
        path.write_text(path.read_text(encoding="utf-8").replace("mean([1, 2, 3]), 2", "mean([1, 2, 3]), 2.0"), encoding="utf-8")
        self.edit_tree(MEAN_FIX)
        b = entry.open_board(self.board)
        got = line_edge.final_edge(b, self.repo, run_id="run-12", mode="when_needed", tests={"ok": True, "green": True})
        self.assertTrue(got.get("ask"), got)
        self.assertIn("test_stats.py", got["gate_text"])
        self.assertIn("conflict-ruling", got["gate_text"])


class TestAskHuman(ConflictBoardCase):
    def asked_board(self):
        self.parked()
        cid = self.items()[0]["id"]
        _, r = self.rule([{"id": cid, "decision": "ask_human", "text": "依頼とテストのどちらが正しいかは方針の変更で、人が決める",
                           "limits": [], "request_searched": "依頼に分母と期待値のどちらを正とするかの答えを探したが無い"}])
        self.assertTrue(r["ok"], r)
        r = self.accept_script(only_clamp_reply(), pass_="ruled")
        self.assertTrue(r["ok"], r)
        return entry.open_board(self.board)

    def test_asked_unit_is_not_owed_and_board_takes_the_rest(self):
        b = self.asked_board()
        self.assertEqual(b.node_state("p3.fix"), "done")
        self.assertIn("_owed_units", [o["name"] for o in b.state["works"]["overrides"]])

    def test_fixing_an_asked_unit_is_rejected(self):
        self.parked()
        cid = self.items()[0]["id"]
        self.rule([{"id": cid, "decision": "ask_human", "text": "方針の変更で、人が決める——直さない", "limits": [],
                    "request_searched": "依頼に分母と期待値のどちらを正とするかの答えを探したが無い"}])
        self.edit_tree(MEAN_FIX)
        r = self.accept_script(load("fix2_ok"), pass_="ruled")
        self.assertFalse(r["ok"])
        self.assertIn("ask_human", r["reason"])

    def test_ask_human_without_request_citation_is_rejected(self):
        """依頼のファイルが在る run の ask_human は、依頼の行（grounds）か request_searched が無ければ拒み、在る名指しは現物で引く"""
        import conflict
        self.parked()
        cid = self.items()[0]["id"]
        request = conflict.request_file(self.board)
        self.assertTrue(request, "この盤面は依頼のファイルを持つ")
        _, r = self.rule([{"id": cid, "decision": "ask_human", "text": "方針の変更で、人が決める——直さない", "limits": []}])
        self.assertEqual((r["ok"], r["done"]), (False, False), r)
        self.assertIn("request_searched", r["reason"])
        self.assertIsNone(self.items()[0]["ruling"])
        _, r = self.rule([{"id": cid, "decision": "ask_human", "text": "方針の変更で、人が決める——直さない", "limits": [],
                           "grounds": [f"{request}:99999"]}], iteration="2")
        self.assertFalse(r["ok"], "依頼の外の行を名指した grounds は拒む")
        _, r = self.rule([{"id": cid, "decision": "ask_human", "text": "方針の変更で、人が決める——直さない", "limits": [],
                           "grounds": [f"{request}:1"]}], iteration="2")
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.items()[0]["ruling"]["grounds"], [f"{request}:1"])

    def test_forces_final_gate_report_and_next_request(self):
        import conflict
        import line_edge
        import report
        b = self.asked_board()
        got = line_edge.final_edge(b, self.repo, run_id="run-12", mode="when_needed", tests={"ok": True, "green": True})
        self.assertTrue(got.get("ask"), "緑でも食い違いの申し出が人に回れば関所を開く")
        self.assertIn(conflict.HEAD, got["gate_text"])
        self.assertIn(MEAN, got["gate_text"])
        b = entry.open_board(self.board, allow_halted=True)
        rows = [h for h in b.record["process"]["human_items"] if h.get("node") == conflict.BY]
        self.assertEqual(len(rows), 1)
        self.assertIsNone(rows[0]["answer"])
        items = report.next_request(b)
        self.assertTrue(any(i["where"] == MEAN and conflict.HEAD in i["text"] for i in items), items)
        self.assertEqual(report.decide_outcome(b, {"accepted": True, "round_closed": True}), "needs_human",
                         "人に回した単位を直さずに残した run は fixed と言わない")
        lines = report.head_decisions(b, {"accepted": True, "round_closed": True})
        hit = [x for x in lines if x.startswith(conflict.HEAD)]
        self.assertEqual(len(hit), 1, lines)
        self.assertIn("人に回す（ask_human）1", hit[0])

    def test_final_gate_answer_copied_and_missing_answer_stops(self):
        """関所の答えを食い違いの行に写す。関所が開かなかった（答えが無い）のに行が答えを待っていれば止める"""
        import conflict
        import line_edge
        self.asked_board()
        b = entry.open_board(self.board)
        line_edge.final_edge(b, self.repo, run_id="run-12", mode="when_needed", tests={"ok": True, "green": True})
        out = line_edge.edge(self.board, "eyes", self.repo, run_id="run-12", adapter_mode="", final_gate="when_needed")
        self.assertTrue(out["stop"], out)
        self.assertIn(conflict.HEAD, out["why"])


class TestTddConflict(LoopCase):
    def test_conflict_in_route_parks_unit_without_reject(self):
        got = tddloop_step(self, {"phase": "conflict", **conflict_on_mean()})
        self.assertEqual((got["ok"], got["done"]), (True, False), got)
        self.assertEqual(got["conflict"]["unit_key"], MEAN)
        st = self.st()
        self.assertEqual((st["tries"], st["parked"]), (0, [MEAN]))
        got = tddloop_step(self, {"phase": "route", "units": [{"unit_key": CLAMP, "route": "direct",
                                                                "why": "文書の直しと同じで、先にテストを書けない単位"}]})
        self.assertTrue(got["ok"], got)
        ex = __import__("tddloop").exit_fields(self.start)
        self.assertIn((MEAN, "parked"), [(u["unit_key"], u["route"]) for u in ex["units"]])
        summary = pathlib.Path(self.start["summary_file"]).read_text(encoding="utf-8")
        self.assertIn("食い違い", summary)

    def test_route_give_up_after_park_does_not_direct_parked_unit(self):
        """振り分けの段で止めた単位は、振り分けを諦めた _abort でも direct に載せず、summary の「食い違いで止めた単位」と出口の
        parked の行だけに載る"""
        import tddloop
        got = tddloop_step(self, {"phase": "conflict", **conflict_on_mean()})
        self.assertTrue(got["ok"], got)
        for _ in range(tddloop.retry_max()):
            got = tddloop_step(self, {"phase": "route", "units": []})
            self.assertFalse(got["ok"], got)
        self.assertTrue(got["done"], got)
        summary = pathlib.Path(self.start["summary_file"]).read_text(encoding="utf-8")
        direct = summary.split("## direct の単位")[1]
        self.assertNotIn(MEAN, direct, "食い違いで止めた単位を「ここで直せ」に載せない")
        self.assertIn(CLAMP, direct)
        rows = [(u["unit_key"], u["route"]) for u in tddloop.exit_fields(self.start)["units"]]
        self.assertIn((MEAN, "parked"), rows)
        self.assertNotIn((MEAN, "direct"), rows)

    def test_conflict_in_test_phase_restores_and_moves_on(self):
        self.route(mean="tdd", clamp="direct")
        self.add_test("    def test_x(self):\n        pass")
        got = tddloop_step(self, {"phase": "conflict", **conflict_on_mean()})
        self.assertTrue(got["ok"], got)
        self.assertTrue(got["done"], "tdd の単位が他に無ければ輪を抜ける")
        self.assertNotIn("test_x", (self.repo / "test_stats.py").read_text(encoding="utf-8"), "単位の頭に戻す")

    def test_fake_citation_counts_as_reject(self):
        got = tddloop_step(self, {"phase": "conflict", **conflict_on_mean("stats.py:500", "test_stats.py:9")})
        self.assertFalse(got["ok"])
        self.assertIn("行がファイルに無い", got["reason"])
        self.assertEqual(self.st()["tries"], 1)


    def test_query_conflict_tries_judge_query_on_correct_lines(self):
        # TDD の輪の申し出も、修正役の受け付けと同じく判定者の問いを correct_lines に当てる（当たらなければ拒否）
        import querytest
        import tddloop
        how = {"patterns": ["len(xs) - 1"], "fixed": True, "paths": ["stats.py"], "count": "lines"}
        hits = querytest.judge_hits([{"key": MEAN, "class_query": {"how": how, "counts": "defects"}}])
        item = {"phase": "conflict", **conflict_on_mean(), "which_is_right": "query", "kind": "query_hits_fixed"}
        got = tddloop.step(self.state, {**item, "correct_lines": ["    return sum(xs) / len(xs)"]}, self.repo, try_query=hits)
        self.assertFalse(got["ok"], got)
        self.assertIn("どの行にも当たらない", got["reason"])
        got = tddloop.step(self.state, {**item, "correct_lines": ["    return sum(xs) / (len(xs) - 1)"]}, self.repo,
                           try_query=hits)
        self.assertTrue(got["ok"], got)

    def test_step_script_passes_judge_query(self):
        # 節 tdd-step は盤面の判定の単位から try_query を作って tddloop.step に渡す
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location("blk_fix_tdd_step", BLK / "scripts" / "tdd_step.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        seen = {}

        def step(state_file, reply, repo, try_query=None):
            seen["err"] = try_query(MEAN, ["    return sum(xs) / len(xs)"])
            return {"ok": False, "done": False, "reason": "x", "phase": "route"}
        b = mock.MagicMock()
        b.record = {"units": [{"key": MEAN, "class_query": {"how": {"patterns": ["len(xs) - 1"], "fixed": True,
                                                                     "paths": ["stats.py"], "count": "lines"}}}]}
        with mock.patch.object(mod.tddloop, "step", side_effect=step), \
                mock.patch.object(mod.entry, "open_board", return_value=b), \
                mock.patch.object(mod.script_io, "emit_result", return_value=0), \
                mock.patch.dict("os.environ", {"INPUTS_REPLY": "{}", "INPUTS_STATE_FILE": self.state,
                                               "ARTIFACTS_DIR": str(self.board.parent)}):
            self.assertEqual(mod.main(), 0)
        self.assertIn("どの行にも当たらない", seen["err"])


class TestTddExcused(LoopCase):
    """答え待ちの fork の出どころ（conflict.excused_units）は TDD の直す義務に載せず、振らせない"""

    def setUp(self):
        from unittest import mock
        import conflict
        for p in (mock.patch.object(entry, "open_board", return_value=mock.MagicMock()),
                  # 直す義務と外れた単位は conflict.fix_duty の 1 か所から読む（tddloop._duty・受け付けが同じ物を読む）
                  mock.patch.object(conflict, "fix_duty",
                                    return_value=({MEAN}, {CLAMP: "答え待ちの問い q-1（fork・held）"}))):
            p.start()
            self.addCleanup(p.stop)
        super().setUp()

    def test_unit_awaiting_answer_is_not_routed(self):
        import tddloop
        prompt = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        owed = prompt.rsplit("## 直す義務の単位", 1)[1].split("## ")[0]
        self.assertIn(MEAN, owed)
        self.assertNotIn(CLAMP, owed, "答え待ちの単位を直す義務に並べない")
        why = "文書の直しと同じで、先にテストを書けない単位"
        got = tddloop_step(self, {"phase": "route", "units": [{"unit_key": MEAN, "route": "direct", "why": why},
                                                              {"unit_key": CLAMP, "route": "direct", "why": why}]})
        self.assertFalse(got["ok"], "答え待ちの単位を振る返答は拒む")
        self.assertIn("答え待ちの問い q-1", got["reason"], "拒否文に外れた理由を出す")
        got = tddloop_step(self, {"phase": "route", "units": [{"unit_key": MEAN, "route": "direct", "why": why}]})
        self.assertTrue(got["ok"], got)

    def test_excused_unit_marked_not_now_in_brief_row(self):
        """振り分けの段の brief の行の「単位」は直す義務の単位だけ。同じ項目の答え待ちの単位は「今は直すな」と添える"""
        import planbrief
        import tddloop
        rows = [{"item": 1, "unit_keys": [MEAN, CLAMP], "file": "/b/r1/brief-1.md", "sha256": "a" * 64}]
        with mock.patch.object(tddloop.planbrief, "cut_at", return_value=rows):
            prompt = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        row = next(ln for ln in prompt[prompt.index(planbrief.HEAD):].splitlines() if ln.startswith("- 項目 1:"))
        self.assertIn(f"単位 {MEAN}・{planbrief.NOT_NOW}: {CLAMP}", row)


def tddloop_step(case, reply):
    import tddloop
    return tddloop.step(case.state, reply, case.repo)


class TestFixtures(unittest.TestCase):
    def test_block_conflict_scenario(self):
        """blk-fix の筋書き conflict: 1 回目は mean を申し出て parked、裁定の輪と 2 回目の修正の輪を通って collect まで"""
        import yaml
        f = yaml.safe_load((BLK / "fixtures" / "conflict.stubs.yaml").read_text(encoding="utf-8"))
        self.assertEqual([c["unit_key"] for c in f["fix"]["conflicts"]], [MEAN])
        self.assertEqual((f["fix-accept"]["parked"], f["conflict-check"]["go"]), (True, True))
        self.assertEqual(f["fix-ruled"], load("fix2_ok"))
        self.assertEqual(f["fixture"]["reached"][-1], "collect")
        for name in ("pass", "no-change", "tdd"):
            g = yaml.safe_load((BLK / "fixtures" / f"{name}.stubs.yaml").read_text(encoding="utf-8"))
            self.assertIs(g["conflict-check"]["go"], False, name)

    def test_line_conflict_ask_scenario(self):
        """ラインの筋書き conflict-ask: when_needed・緑でも ask_human の申し出で h-final が関所を開き、結末は needs_human"""
        import conflict
        import yaml
        f = yaml.safe_load((ROOT / "darkfactory" / "fixtures" / "conflict-ask.stubs.yaml").read_text(encoding="utf-8"))
        self.assertEqual(f["fixture"]["inputs"]["final_gate"], "when_needed")
        self.assertIs(f["fixing__conflict-check"]["go"], True)
        self.assertEqual(f["rule"]["rulings"][0]["decision"], "ask_human")
        self.assertIs(f["h-final"]["ask"], True)
        self.assertIn(conflict.HEAD, f["h-final"]["gate_text"])
        self.assertEqual((f["report"]["outcome"], f["result"]["outcome"]), ("needs_human", "needs_human"))


class TestYaml(unittest.TestCase):
    def test_rule_loop_single_ai_read_only_and_exits_on_done(self):
        """裁定の輪: AI の節は 1 つ（TA13）・読む道具だけ・until_bash は done の印（R50）・上限 3。飛ぶ条件は conflict-check の go"""
        import ruling
        y = block()
        loop = find_node(y["nodes"], "rule-loop")
        g = loop["loop_group"]
        self.assertEqual(loop["when"], "$conflict-check.output.go == true")
        self.assertEqual(g["max_iterations"], 3)
        self.assertEqual(g["until_bash"], "test $rule-accept.output.done = true")
        self.assertEqual([n["id"] for n in g["nodes"]], ["rule-prep", "rule", "rule-accept"])
        ai = [n for n in g["nodes"] if "prompt" in n]
        self.assertEqual(len(ai), 1)
        self.assertTrue(set(ai[0]["allowed_tools"]) <= {"Read", "Grep", "Glob", "WebSearch", "WebFetch"}, "書く道具と shell を持たない")
        self.assertEqual(ai[0]["output_format"], ruling.RULE_OUTPUT_FORMAT)
        self.assertEqual(ai[0]["idle_timeout"], DEADLINE)

    def test_fix_ruled_loop_continues_the_fixer(self):
        y = block()
        loop = find_node(y["nodes"], "fix-ruled-loop")
        g = loop["loop_group"]
        self.assertEqual(loop["when"], "$conflict-check.output.go == true")
        self.assertEqual(g["until_bash"], "test $fix-ruled-accept.output.done = true")
        self.assertEqual([n["id"] for n in g["nodes"]], ["fix-ruled-prep", "fix-ruled", "fix-ruled-accept"])
        role = find_node(y["nodes"], "fix-ruled")
        self.assertEqual(role["output_format"]["description"], "works-node: fix-ruled continue=fix")
        fix = find_node(y["nodes"], "fix")
        self.assertEqual({k: v for k, v in role["output_format"].items() if k != "description"},
                         {k: v for k, v in fix["output_format"].items() if k != "description"})
        self.assertEqual(find_node(y["nodes"], "fix-ruled-prep")["with"]["pass"], "ruled")
        self.assertEqual(find_node(y["nodes"], "fix-ruled-accept")["with"]["pass"], "ruled")
        self.assertEqual(find_node(y["nodes"], "fix-prep")["with"]["pass"], "first")

    def test_fix_output_carries_conflicts(self):
        import conflict
        fix = find_node(block()["nodes"], "fix")
        self.assertEqual(fix["output_format"]["properties"]["conflicts"], conflict.CONFLICTS_SCHEMA)
        tdd = find_node(block()["nodes"], "tdd")
        self.assertIn("conflict", tdd["output_format"]["properties"]["phase"]["enum"])
        for k in ("between", "why_both_cannot_hold", "which_is_right", "kind"):
            self.assertIn(k, tdd["output_format"]["properties"])
        self.assertEqual(tdd["output_format"]["properties"]["kind"]["enum"], list(conflict.DIV_KINDS))

    def test_after_the_loops_read_the_later_output(self):
        y = block()
        for nid in ("assert-changed", "collect"):
            n = find_node(y["nodes"], nid)
            self.assertEqual(n["with"]["ruled"], {"from": "$fix-ruled-loop.output", "if_skipped": None}, nid)
        clean = find_node(y["nodes"], "clean")
        self.assertEqual(clean["depends_on"], ["fix-loop", "conflict-check", "rule-loop", "fix-ruled-loop"])
        self.assertEqual(clean["trigger_rule"], "none_failed_min_one_success")


class TestPlanRewritePermits(ConflictBoardCase):
    """承認済みの修正案が名指した既存テストの書き換え（rewrite_tests）は、裁定 fix_test_scope の範囲と同じ 1 か所
    （conflict.test_permits）から凍結の検査と最後の関所へ渡る"""
    REWRITE = {"id": "test_stats.py::TestStats::test_mean_of_three", "behavior": "平均の定義が依頼で変わる",
               "old": "mean([1, 2, 3]), 2", "new": "新しい期待は 2.0（float で返す）", "limit": "test_stats.py:8"}

    def fields_saved(self):
        self.fix_ready()
        b = entry.open_board(self.board)
        planmarks.save(self.board, b.round, [{"route": "tdd", "route_why": "", "tests": [], "rewrite_tests": [self.REWRITE],
                                               "refactor": {"declared": False, "why": ""}}])
        return entry.open_board(self.board)

    def test_permits_join_plan_rewrites_and_rulings(self):
        b = self.fields_saved()
        self.assertEqual(conflict.ruled_test_limits(b, rulings=False), ["test_stats.py:8"])
        self.assertEqual(conflict.ruled_test_doc(b)["rules"][0]["id"].split("-")[:2], ["plan", "rewrite"])

    def test_no_plan_fields_same_as_before(self):
        self.fix_ready()
        self.assertIsNone(conflict.ruled_test_doc(entry.open_board(self.board)))

    def test_tdd_plan_contract_reads_saved_fields_on_real_board(self):
        """本物の盤面と受け付けが置いた欄の控え（凍結の印つき）から、TDD の輪の約束（tddloop.plan_contract）が
        planmarks.unit_contract の形で組める。約束の無い単位は載らない"""
        import tddloop
        self.fix_ready()
        b = entry.open_board(self.board)
        test = {"id": "test_stats.py::TestStats::test_mean_of_two", "behavior": "2 つの値の平均を返す",
                "path": "stats.mean を直に呼ぶ（mock なし）", "red_kind": "assertion", "red_why": "今は len-1 で割り 6.0 になる"}
        planmarks.save(self.board, b.round, [{"unit_keys": [MEAN], "route": "tdd", "route_why": "", "tests": [test],
                                               "rewrite_tests": [self.REWRITE], "refactor": {"declared": False, "why": ""}}])
        self.assertEqual(tddloop.plan_contract(self.board, [MEAN, CLAMP]),
                         {MEAN: {"items": [1], "route": "tdd", "tests": [{"id": test["id"], "red_kind": "assertion"}],
                                 "rewrites": [self.REWRITE["id"]], "refactor": False}})

    def test_frozen_fields_halts_on_broken_ledger(self):
        """conflict.frozen_fields は凍結した欄の並び（planmarks.frozen）。控えが受け付けの後に書き換えられたら、_plan_rewrites と
        同じ 1 か所の文（FIELDS_BROKEN で始まる）で盤面を止めて BoardGap"""
        b = self.fields_saved()
        self.assertEqual(conflict.frozen_fields(b)[0]["rewrite_tests"], [self.REWRITE])
        p = self.board / planmarks.FIELDS_FILE
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["fields"][0]["route"] = "direct"
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        with self.assertRaises(board.BoardGap) as got:
            conflict.frozen_fields(entry.open_board(self.board))
        self.assertTrue(str(got.exception).startswith(conflict.FIELDS_BROKEN), got.exception)
        after = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(after.state["stop"]["by"], conflict.FIELDS_STOP_BY)
        with self.assertRaises(board.BoardGap) as again:
            conflict.test_permits(after)
        self.assertEqual(str(again.exception), str(got.exception), "_plan_rewrites と同じ文")

    def test_plan_rewrite_listed_at_final_gate(self):
        import line_edge
        self.fields_saved()
        path = self.repo / "test_stats.py"
        path.write_text(path.read_text(encoding="utf-8").replace("mean([1, 2, 3]), 2", "mean([1, 2, 3]), 2.0"), encoding="utf-8")
        self.edit_tree(MEAN_FIX)
        got = line_edge.final_edge(entry.open_board(self.board), self.repo, run_id="run-12", mode="when_needed",
                                   tests={"ok": True, "green": True})
        self.assertTrue(got.get("ask"), got)
        self.assertIn(conflict.PLAN_TEST_ID, got["gate_text"])

    def frozen_after_test_added_above(self):
        """修正案の時の木（limit は test_stats.py:8）の後、TDD の輪が同じファイルの上に 2 行のテスト test_empty を足して凍った
        盤面。返り (盤面, 輪の状態のファイル)"""
        import tddloop
        b = self.fields_saved()
        path = self.repo / "test_stats.py"
        text = path.read_text(encoding="utf-8")
        head = "class TestStats(unittest.TestCase):\n"
        self.assertIn(head, text)
        path.write_text(text.replace(head, head + "    def test_empty(self):\n        self.assertEqual(clamp(0, 0, 0), 0)\n"),
                        encoding="utf-8")
        state = self.tmp / "tdd-state.json"
        state.write_text(json.dumps({"frozen": tddloop.hashes(self.repo, ["test_stats.py"]),
                                     "frozen_tree": tddloop.snapshot(self.repo)}), encoding="utf-8")
        return b, str(state)

    def test_plan_limit_follows_test_id_on_frozen_tree(self):
        """修正案の limit の行は、凍結の検査が読む輪の後の木で、テストの id から引き直す（上に足したテストを指さない）"""
        import tddloop
        b, state = self.frozen_after_test_added_above()
        limits = conflict.ruled_test_limits(b, rulings=False, source=tddloop.frozen_source(state, self.repo))
        self.assertEqual(limits, ["test_stats.py:10"])
        path = self.repo / "test_stats.py"
        text = path.read_text(encoding="utf-8")
        path.write_text(text.replace("mean([1, 2, 3]), 2)", "mean([1, 2, 3]), 2.0)"), encoding="utf-8")
        self.assertEqual(tddloop.frozen_problems(state, self.repo, limits), [], "名指したテストの書き換えは通す")
        path.write_text(text.replace("clamp(0, 0, 0), 0)", "clamp(0, 0, 0), 1)"), encoding="utf-8")
        self.assertTrue(tddloop.frozen_problems(state, self.repo, limits), "名指していない test_empty の書き換えは拒む")

    def test_rewrite_verified_in_loop_is_frozen_for_the_fixer(self):
        """輪が赤→緑を確かめた書き換え（tddloop.verified_rewrites）は、受け付けの許しから外れる（skip_ids）。輪の後の修正役が
        そのテストを書き換えると凍結の検査が拒む。輪で確かめていない書き換えの許しは今どおり"""
        import tddloop
        b, state = self.frozen_after_test_added_above()
        rid = self.REWRITE["id"]
        p = pathlib.Path(state)
        st = json.loads(p.read_text(encoding="utf-8"))
        st.update(order=[MEAN], units={MEAN: {"unit_key": MEAN, "route": "tdd", "green": "ok", "tests": [rid]}},
                  contract={MEAN: {"items": [1], "route": "tdd", "tests": [], "rewrites": [rid], "refactor": False}})
        p.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        skip = tddloop.verified_rewrites(state)
        self.assertEqual(skip, [rid])
        source = tddloop.frozen_source(state, self.repo)
        self.assertEqual(conflict.ruled_test_limits(b, rulings=False, source=source, skip_ids=skip), [])
        self.assertEqual(conflict.ruled_test_limits(b, rulings=False, source=source), ["test_stats.py:10"], "外さなければ今どおり")
        path = self.repo / "test_stats.py"
        path.write_text(path.read_text(encoding="utf-8").replace("mean([1, 2, 3]), 2)", "mean([1, 2, 3]), 2.0)"), encoding="utf-8")
        self.assertTrue(tddloop.frozen_problems(state, self.repo, conflict.ruled_test_limits(b, rulings=False, source=source,
                                                                                              skip_ids=skip)))
        st["units"][MEAN]["green"] = ""   # 緑に届かなかった単位の書き換えは確かめていない
        p.write_text(json.dumps(st, ensure_ascii=False), encoding="utf-8")
        self.assertEqual(tddloop.verified_rewrites(state), [])
        self.assertEqual(tddloop.verified_rewrites(""), [], "輪の無い run は空")

    def test_plan_limit_dropped_when_test_missing_on_frozen_tree(self):
        """輪の後の木で名指したテストを引けなければ、その許しを捨てる（範囲を広げない側）"""
        import tddloop
        b = self.fields_saved()
        path = self.repo / "test_stats.py"
        path.write_text(path.read_text(encoding="utf-8").replace("def test_mean_of_three", "def test_mean_renamed"),
                        encoding="utf-8")
        state = self.tmp / "tdd-state.json"
        state.write_text(json.dumps({"frozen": tddloop.hashes(self.repo, ["test_stats.py"]),
                                     "frozen_tree": tddloop.snapshot(self.repo)}), encoding="utf-8")
        self.assertEqual(conflict.ruled_test_limits(b, rulings=False, source=tddloop.frozen_source(str(state), self.repo)), [])
        no_tree = self.tmp / "tdd-state-no-tree.json"
        no_tree.write_text(json.dumps({"frozen": {}}), encoding="utf-8")
        self.assertEqual(conflict.ruled_test_limits(b, rulings=False, source=tddloop.frozen_source(str(no_tree), self.repo)), [],
                         "輪の後の木が無ければ引けないので捨てる")

    def test_fields_rewritten_after_accept_halt_the_frozen_check(self):
        """受け付けの後に plan-fields.json へ rewrite_tests の行を足しても、凍結の検査はその許しを使わず、盤面を止めて
        plan-fields.json を名指す 1 行で 2（黙って許しを広げない・黙って捨てない）"""
        _, state = self.frozen_after_test_added_above()
        p = self.board / planmarks.FIELDS_FILE
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["fields"][0]["rewrite_tests"].append(dict(self.REWRITE, id="test_stats.py::TestStats::test_empty",
                                                      limit="test_stats.py:4"))
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        path = self.repo / "test_stats.py"
        path.write_text(path.read_text(encoding="utf-8").replace("clamp(0, 0, 0), 0)", "clamp(0, 0, 0), 1)"), encoding="utf-8")
        env = {"INPUTS_REPLY": json.dumps(load("fix2_ok"), ensure_ascii=False), "INPUTS_BASE_REV": "", "INPUTS_TDD_STATE": state,
               "INPUTS_ITERATION": "1", "INPUTS_PASS": "first", "ARTIFACTS_DIR": str(self.art),
               "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"]}
        code, out, err = run_script("accept", self.repo, env)
        self.assertEqual((code, out), (2, ""), err)
        self.assertIn(planmarks.FIELDS_FILE, err)
        self.assertNotIn("Traceback", err)
        after = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(after.state["stop"]["by"], conflict.FIELDS_STOP_BY)
        self.assertIn(planmarks.FIELDS_FILE, after.state["stop"]["reason"])

    def test_same_file_by_plan_and_ruling_lists_both_reasons_at_final_gate(self):
        """修正案と裁定 fix_test_scope が同じテストのファイルを許すと、最後の関所のその 1 行に両方の理由が並ぶ"""
        import line_edge
        self.parked()
        cid = self.items()[0]["id"]
        _, r = self.rule([{"id": cid, "decision": "fix_test_scope", "text": RULE_TEXT, "limits": ["test_stats.py:9"]}])
        self.assertTrue(r["ok"], r)
        b = entry.open_board(self.board)
        planmarks.save(self.board, b.round, [{"route": "tdd", "route_why": "", "tests": [], "rewrite_tests": [self.REWRITE],
                                               "refactor": {"declared": False, "why": ""}}])
        b = entry.open_board(self.board)
        self.assertEqual(len(conflict.ruled_test_doc(b)["rules"]), 1, "パスで 1 行")
        path = self.repo / "test_stats.py"
        path.write_text(path.read_text(encoding="utf-8").replace("mean([1, 2, 3]), 2", "mean([1, 2, 3]), 2.0"), encoding="utf-8")
        self.edit_tree(MEAN_FIX)
        got = line_edge.final_edge(b, self.repo, run_id="run-12", mode="when_needed", tests={"ok": True, "green": True})
        self.assertTrue(got.get("ask"), got)
        self.assertIn(conflict.PLAN_TEST_ID, got["gate_text"])
        self.assertIn(RULE_TEXT, got["gate_text"])
        self.assertIn(f"裁定 {cid}", got["gate_text"])


class TestFirstPassPlanLimits(unittest.TestCase):
    """1 回目（first）の受け付けも、修正案が名指した書き換えを凍結の検査に渡す（裁定の範囲は 2 回目だけ）。
    盤面・git は使わない（test_fix_rules.TestThirdRejectParksBoundUnit と同じく受け付けの模块を読み、検査を mock にする）"""

    def test_first_pass_hands_plan_limits_to_frozen_check(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("blk_fix_accept_script", BLK / "scripts" / "accept.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        limits = mock.MagicMock(return_value=["test_stats.py:8"])
        frozen = mock.MagicMock(return_value=["TDD の輪で凍ったテストのファイルを書き換えた: ['test_stats.py']"])
        with mock.patch.object(mod.conflict, "ruled_test_limits", limits), \
                mock.patch.object(mod.tddloop, "frozen_problems", frozen), \
                mock.patch.object(mod.entry, "open_board", return_value=mock.MagicMock()), \
                mock.patch.dict("os.environ", {"INPUTS_ITERATION": "1", "INPUTS_TDD_STATE": "/b/tdd.json",
                                               "INPUTS_PASS": "first"}):
            got = mod.accept_fix({"changes": []}, pathlib.Path("/b"), "", pathlib.Path("/r"))
        self.assertIs(got["ok"], False, got)
        limits.assert_called_once_with(mock.ANY, rulings=False, source=mock.ANY, skip_ids=[])
        self.assertTrue(callable(limits.call_args.kwargs["source"]), "修正案の limit は輪の後の木で引き直す")
        self.assertEqual(frozen.call_args[0][2], ["test_stats.py:8"])


class TestAcceptSkipsVerifiedRewrites(unittest.TestCase):
    """受け付けは輪が赤→緑を確かめた書き換えの id（tddloop.verified_rewrites）を許しから外して凍結の検査に渡す（1 回目も裁定の後も）"""

    def test_accept_passes_verified_rewrites_as_skip_ids(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("blk_fix_accept_script_skip", BLK / "scripts" / "accept.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        for pass_ in ("first", "ruled"):
            limits = mock.MagicMock(return_value=[])
            frozen = mock.MagicMock(return_value=["TDD の輪で凍ったテストのファイルを書き換えた: ['test_stats.py']"])
            with mock.patch.object(mod.conflict, "ruled_test_limits", limits), \
                    mock.patch.object(mod.tddloop, "frozen_problems", frozen), \
                    mock.patch.object(mod.tddloop, "verified_rewrites", return_value=["t.py::T::test_a"]) as vr, \
                    mock.patch.object(mod.entry, "open_board", return_value=mock.MagicMock()), \
                    mock.patch.dict("os.environ", {"INPUTS_ITERATION": "1", "INPUTS_TDD_STATE": "/b/tdd.json",
                                                   "INPUTS_PASS": pass_}):
                got = mod.accept_fix({"changes": []}, pathlib.Path("/b"), "", pathlib.Path("/r"))
            self.assertIs(got["ok"], False, got)
            vr.assert_called_once_with("/b/tdd.json")
            self.assertEqual(limits.call_args.kwargs["skip_ids"], ["t.py::T::test_a"], pass_)
            self.assertEqual(limits.call_args.kwargs["rulings"], pass_ == "ruled")


class TestPermitsOnRawBoard(unittest.TestCase):
    """盤面の控えのファイルだけを置いた軽い盤面（dir・round・work）で、許しの行の引き方と最後の関所の行の組み方を見る"""
    TWO = "import unittest\nclass A(unittest.TestCase):\n    def test_x(self):\n        pass\nclass B(unittest.TestCase):\n" \
          "    def test_x(self):\n        pass\n"

    def setUp(self):
        import tempfile
        import types
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = pathlib.Path(tmp.name)
        self.b = types.SimpleNamespace(dir=self.dir, round=1, work=lambda name: self.dir / name)

    def test_trailing_slash_id_names_the_class_at_plan_and_frozen_time(self):
        """id のパスを書いたまま（t.py/）でなく、整えたパス（t.py）で .py かを決める（A::test_x の行に広げない）"""
        repo = self.dir / "repo"
        repo.mkdir()
        (repo / "t.py").write_text(self.TWO, encoding="utf-8")
        tid = "t.py/::B::test_x"
        self.assertEqual(planmarks.find_test(repo, tid), 6)
        row = {"id": tid, "behavior": "B の振る舞いが依頼で変わる", "old": "pass のまま", "new": "新しい期待を書く行に変える"}
        _, fields = planmarks.split({"plan": [{"rewrite_tests": [row]}]}, repo)
        self.assertEqual(fields[0]["rewrite_tests"][0]["limit"], "t.py:6", "修正案の時")
        planmarks.save(self.dir, 1, fields)
        self.assertEqual(conflict.ruled_test_limits(self.b, rulings=False, source=lambda p: self.TWO if p == "t.py" else None),
                         ["t.py:6"], "凍結の検査の時")

    def test_same_reason_with_slash_listed_once(self):
        """1 つの裁定が同じファイルに 2 つの範囲を許しても、理由は 1 度だけ（理由の文に " / " が在っても）"""
        text = "期待は float / int のどちらでもよいと依頼に在るので、範囲の 2 か所を直してよい"
        (self.dir / conflict.FILE).write_text(json.dumps({"items": [
            {"id": "c1-1", "unit_key": MEAN, "between": ["stats.py:9", "test_stats.py:9"], "why_both_cannot_hold": WHY,
             "which_is_right": "test", "ruling": {"decision": "fix_test_scope", "text": text,
                                                   "limits": ["test_stats.py:8", "test_stats.py:14"]}}]}, ensure_ascii=False),
            encoding="utf-8")
        rows = conflict.ruled_test_doc(self.b)["rules"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["why"].count(text), 1, rows[0]["why"])


class TestRuledPrepBrief(ConflictBoardCase):
    """2 回目の修正役（fix-ruled-prep）の指示書の頭: 裁定の文のファイルが見出しの次の 1 行（R44）で、brief の節はその後。
    brief の行の「単位」は直す義務の単位だけで、義務から外れた単位には「今は直すな」と添える"""

    def ruled_prompt(self, decision, text):
        import planbrief  # noqa: F401  （blk-fix の lib。test_blk_fix が sys.path に足す）
        from test_blk_fix import PLAN_FIELDS
        self.parked()
        cid = self.items()[0]["id"]
        _, r = self.rule([{"id": cid, "decision": decision, "text": text, "limits": ["stats.py:9"] if decision != "ask_human" else [],
                           "request_searched": "依頼に分母と期待値のどちらを正とするかの答えを探したが無い"}])
        self.assertTrue(r["ok"], r)
        planmarks.save(self.board, entry.open_board(self.board).round, PLAN_FIELDS)
        code, out, err = run_script("fix_prep", self.repo, {
            "ARTIFACTS_DIR": str(self.art), "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"], "INPUTS_PASS": "ruled",
            **{f"INPUTS_{k.upper()}": v for k, v in {"judgment_file": "", "open_units": json.dumps([MEAN, CLAMP]),
                                                    "plan_file": "", "policy_path": "", "notes_file": "", "summary_file": ""}.items()}})
        self.assertEqual(code, 0, err)
        return r, pathlib.Path(json.loads(out)["prompt_file"]).read_text(encoding="utf-8")

    def test_rulings_line_before_brief_head(self):
        import planbrief
        r, prompt = self.ruled_prompt("fix_code_as", RULE_TEXT)
        self.assertIn(r["rulings_file"], prompt.split("\n")[1], "裁定の文のファイルを見出しの次の 1 行で名指す")
        self.assertLess(prompt.index(r["rulings_file"]), prompt.index(planbrief.HEAD))

    def test_excused_unit_marked_not_now_in_brief_row(self):
        import planbrief
        _, prompt = self.ruled_prompt("ask_human", "依頼とテストのどちらが正しいかは方針の変更で、人が決める")
        row = next(ln for ln in prompt[prompt.index(planbrief.HEAD):].splitlines() if ln.startswith("- 項目 1:"))
        self.assertIn(f"単位 {CLAMP}", row)
        self.assertNotIn(f"単位 {MEAN}", row)
        self.assertIn(f"今は直すな: {MEAN}", row)


class TestTamperedFieldsAtLineEdge(ConflictBoardCase):
    """受け付けの後に plan-fields.json を書き換えた盤面を、線の境（h-final・h-eyes）の読むだけの確かめ（line_edge._guard）が
    止めた時: 答えが効かない関所を開かず、2 度止めず、控えを名指す理由で止まる"""
    REWRITE, fields_saved = TestPlanRewritePermits.REWRITE, TestPlanRewritePermits.fields_saved

    def tampered(self):
        self.fields_saved()
        p = self.board / planmarks.FIELDS_FILE
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["fields"][0]["rewrite_tests"].append(dict(self.REWRITE, id="test_stats.py::TestStats::test_mean_of_two",
                                                      limit="test_stats.py:11"))
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        self.edit_tree(MEAN_FIX)

    def assert_halted_once(self, out):
        import line_edge
        self.assertTrue(out["stop"], out)
        self.assertFalse(out.get("ask"), "答えが効かない関所を開かない")
        self.assertIn(planmarks.FIELDS_FILE, out["why"])
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(b.state["stop"]["by"], conflict.FIELDS_STOP_BY)
        stops = [x for x in (self.board / "trace.jsonl").read_text(encoding="utf-8").splitlines() if '"op": "stop"' in x]
        self.assertEqual(len(stops), 1, "2 度止めない")
        self.assertFalse(b.work(line_edge.FINAL_GATE_FILE).exists())

    def test_at_final_no_gate(self):
        import line_edge
        self.tampered()
        out = line_edge.edge(self.board, "final", self.repo, run_id="run-12", adapter_mode="", final_gate="always",
                             tests={"ok": True, "green": True})
        self.assert_halted_once(out)

    def test_at_eyes_without_final_no_second_stop(self):
        """h-final が飛ばされた run の h-eyes（関所の答えが無い）"""
        import line_edge
        self.tampered()
        out = line_edge.edge(self.board, "eyes", self.repo, run_id="run-12", adapter_mode="", final_gate="when_needed")
        self.assert_halted_once(out)


class TestParseLimitDots(unittest.TestCase):
    def test_dotdot_prefixed_dir_kept_and_climb_dropped(self):
        """`..foo/x.py` は根の中のディレクトリ `..foo` の物（planmarks.gaps が通す範囲を受け付けで捨てない）。`../` の上りは今どおり捨てる"""
        self.assertEqual(conflict.parse_limit("..foo/x.py:3"), ("..foo/x.py", (3, 3)))
        self.assertIsNone(conflict.parse_limit("../x.py:3"))
        self.assertIsNone(conflict.parse_limit("/x.py:3"))


class TestTddKind(LoopCase):
    """TDD の輪の申し出も、修正役の受け付けと同じ確かめ（conflict.problems）で種類の欄 kind と which_is_right との対を見る"""

    def test_tdd_conflict_without_kind_is_rejected(self):
        item = {"phase": "conflict", **conflict_on_mean()}
        item.pop("kind")
        got = tddloop_step(self, item)
        self.assertFalse(got["ok"])
        self.assertIn("kind", got["reason"])
        got = tddloop_step(self, {**item, "kind": "query_hits_fixed"})
        self.assertFalse(got["ok"])
        self.assertIn("which_is_right", got["reason"])
        got = tddloop_step(self, {**item, "kind": "unnamed_test_broke"})
        self.assertTrue(got["ok"], got)


class TestBriefKind(ConflictBoardCase):
    """修正役の申し出 brief_vs_judgment は、その単位の brief（今の周の控えの行）を名指す時だけ止めて積む"""

    def briefed(self):
        """修正役が clamp を直した、修正案の欄の控えと brief-1.md（単位 MEAN・CLAMP）の在る盤面"""
        import planbrief
        from test_blk_fix import PLAN_FIELDS
        self.fix_ready()
        self.edit_tree(CLAMP_FIX)
        planmarks.save(self.board, entry.open_board(self.board).round, PLAN_FIELDS)
        planbrief.cut_at(self.board)

    def test_fixer_brief_kind_parks_with_brief_line(self):
        self.briefed()
        brief = str(entry.open_board(self.board).work("brief-1.md"))
        r = self.accept_script(only_clamp_reply([{**conflict_on_mean(f"{brief}:1", "stats.py:9"), "kind": "brief_vs_judgment"}]))
        self.assertEqual((r["ok"], r.get("parked")), (True, True), r)
        self.assertEqual(self.items()[0]["kind"], "brief_vs_judgment")

    def test_fixer_brief_kind_without_plan_is_rejected(self):   # planmarks.save と cut を呼ばない盤面
        self.fix_ready()
        self.edit_tree(CLAMP_FIX)
        r = self.accept_script(only_clamp_reply([{**conflict_on_mean(), "kind": "brief_vs_judgment"}]))
        self.assertFalse(r["ok"])
        self.assertIn("brief_vs_judgment", r["reason"])


class TestTddBriefKind(LoopCase):
    """TDD の輪の申し出 brief_vs_judgment も、輪の盤面の brief（planbrief.by_unit_at）の行を名指す時だけ通す"""

    def test_tdd_brief_kind_needs_the_units_brief(self):
        import tddloop
        brief = pathlib.Path(self.st()["work"]).parent / "brief-1.md"
        brief.write_text("# brief 1\n算術平均で割る\n範囲は stats.py だけ\n", encoding="utf-8")
        reply = {"phase": "conflict", **conflict_on_mean(f"{brief}:1", "stats.py:9"), "kind": "brief_vs_judgment"}
        with mock.patch.object(tddloop.planbrief, "by_unit_at", return_value={}):
            got = tddloop_step(self, reply)
        self.assertFalse(got["ok"], got)
        self.assertIn("brief_vs_judgment", got["reason"])
        with mock.patch.object(tddloop.planbrief, "by_unit_at", return_value={MEAN: [{"item": 1, "file": str(brief)}]}):
            got = tddloop_step(self, reply)
        self.assertTrue(got["ok"], got)



PLAN_TEXT = "項目 1 の受け入れのテストは分母の誤りを縛っていない。案の項目で既存の test_mean_of_three の書き換えを名指し直せ"


class ReplanCase(ConflictBoardCase):
    """裁定 fix_plan_item の盤面の口（mean を申し出た盤面に修正案の欄の控えと brief を置いてから裁く）"""

    def replanned(self):
        """mean の申し出を fix_plan_item に裁いた盤面。返りは self.rule の返り (prep, 受け付けの結果)"""
        import planbrief
        from test_blk_fix import PLAN_FIELDS
        self.parked()
        planmarks.save(self.board, entry.open_board(self.board).round, PLAN_FIELDS)
        planbrief.cut_at(self.board)
        cid = self.items()[0]["id"]
        brief = entry.open_board(self.board).work("brief-1.md")
        return self.rule([{"id": cid, "decision": "fix_plan_item", "text": PLAN_TEXT, "limits": [], "grounds": [f"{brief}:1"]}])


class TestFixPlanItem(ReplanCase):
    """fix_plan_item に裁いた単位は、項目の番号を控えに持ち、直す義務から外れ（直せば拒む）、残りの単位だけで通る"""

    def test_ruling_stored_with_plan_items(self):
        _, r = self.replanned()
        self.assertTrue(r["ok"], r)
        row = self.items()[0]
        self.assertEqual((row["ruling"]["decision"], row["ruling"]["plan_items"]), ("fix_plan_item", [1]))
        self.assertEqual(r["counts"]["fix_plan_item"], 1)
        self.assertIn("直すな", pathlib.Path(r["rulings_file"]).read_text(encoding="utf-8"))

    def test_fixing_a_replanned_unit_is_rejected(self):
        self.replanned()
        self.edit_tree(MEAN_FIX)
        r = self.accept_script(load("fix2_ok"), pass_="ruled")
        self.assertFalse(r["ok"]); self.assertIn("fix_plan_item", r["reason"])

    def test_replanned_unit_leaves_duty_and_rest_is_accepted(self):
        self.replanned()
        r = self.accept_script(only_clamp_reply(), pass_="ruled")
        self.assertTrue(r["ok"], r)
        owed, excused = conflict.fix_duty(entry.open_board(self.board))
        self.assertNotIn(MEAN, owed); self.assertIn("fix_plan_item", excused[MEAN])

    def test_fix_plan_item_without_brief_is_rejected(self):   # brief を置かない盤面
        self.parked()
        _, r = self.rule([{"id": self.items()[0]["id"], "decision": "fix_plan_item", "text": PLAN_TEXT, "limits": []}])
        self.assertEqual((r["ok"], r["done"]), (False, False)); self.assertIn("brief", r["reason"])


class TestFixPlanItemReport(ReplanCase):
    """fix_plan_item の単位は結末を fixed・no_fix_needed にせず、次の run の依頼と報告に載り、最後の関所はほかの理由で開いた時だけ
    単位を並べる（開ける理由には数えない）"""

    @staticmethod
    def clamp_reply():
        """only_clamp_reply の clamp の site に path を足した返答（fix2_ok の site は path を持たず、数え直しの表が「合わない」と
        言って最後の関所を開けるので、関所が fix_plan_item だけで開かないことを見る試験にはこの形を渡す）"""
        reply = only_clamp_reply()
        for s in reply["changes"][0]["closure"]["sites"]:
            s["path"] = "stats.py"
        return reply

    def test_replanned_unit_goes_to_next_request_not_gate(self):
        import line_edge
        import report
        self.replanned()
        self.assertTrue(self.accept_script(self.clamp_reply(), pass_="ruled")["ok"])
        b = entry.open_board(self.board)
        got = line_edge.final_edge(b, self.repo, run_id="run-12", mode="when_needed", tests={"ok": True, "green": True})
        self.assertFalse(got.get("ask"), "fix_plan_item だけでは最後の関所を開かない（人に回す 3 つに当たらない）")
        b = entry.open_board(self.board, allow_halted=True)
        items = report.next_request(b)
        self.assertTrue(any(i["where"] == MEAN and "fix_plan_item" in i["text"] and "事前審査" in i["text"] for i in items), items)
        self.assertEqual(report.decide_outcome(b, {"accepted": True, "round_closed": True}), "round_limit")

    def test_conflict_line_has_kinds_and_replan(self):
        import report
        self.replanned()
        lines = report.head_decisions(entry.open_board(self.board), {"accepted": True, "round_closed": True})
        hit = next(x for x in lines if x.startswith(conflict.HEAD))
        for w in ("案の項目を直す（fix_plan_item）1", "種類の内訳", "unnamed_test_broke 1", "not_red 0"):
            self.assertIn(w, hit)

    def test_gate_opened_for_other_reason_lists_replanned_units(self):
        """最後のテストが赤で開いた関所は fix_plan_item の単位を並べ、開けた理由（冒頭の 1 行目）には数えない"""
        import line_edge
        self.replanned()
        self.assertTrue(self.accept_script(self.clamp_reply(), pass_="ruled")["ok"])
        b = entry.open_board(self.board)
        got = line_edge.final_edge(b, self.repo, run_id="run-12", mode="when_needed", tests={"ok": True, "green": False})
        self.assertTrue(got.get("ask"), got)
        text = got["gate_text"]
        self.assertNotIn("fix_plan_item", text.splitlines()[0], "開けた理由には数えない")
        hit = [x for x in text.splitlines() if x.startswith("- ") and MEAN in x and "案の項目 1" in x]
        self.assertEqual(len(hit), 1, text)
        self.assertIn("fix_plan_item", text)

    def test_all_units_replanned_is_not_no_fix_needed(self):
        """直す物が無い周（need_fix 偽）でも、fix_plan_item で残した単位が在れば round_limit（no_fix_needed と言わない）"""
        import report
        self.replanned()
        self.assertTrue(self.accept_script(self.clamp_reply(), pass_="ruled")["ok"])
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(report.decide_outcome(b, {"accepted": True, "round_closed": True}, judged={"need_fix": False}),
                         "round_limit")
        self.assertEqual(report.decide_outcome(b, {"accepted": False, "round_closed": True}), "record_invalid",
                         "記録が通らない周は fix_plan_item より先に record_invalid")

    def test_next_request_owns_validator_row_and_report_lists_unit(self):
        """その単位の検証器の行は次の run の依頼に渡さず（単位の行が持つ）、報告の冒頭 1 には単位の行が載る"""
        import report
        self.replanned()
        b = entry.open_board(self.board, allow_halted=True)
        left = [{"where": report.VALIDATOR_WHERE, "text": f"[block] 未解消: {MEAN}"},
                {"where": report.VALIDATOR_WHERE, "text": f"[block] 未解消: {CLAMP}"}]
        items = report.next_request(b, left=left)
        self.assertFalse(any(i["where"] == report.VALIDATOR_WHERE and i["text"].endswith(MEAN) for i in items), items)
        self.assertTrue(any(i["where"] == report.VALIDATOR_WHERE and i["text"].endswith(CLAMP) for i in items), items)
        lines = report.head_decisions(b, {"accepted": True, "round_closed": True})
        self.assertTrue(any(MEAN in x and "案の項目 1" in x for x in lines), lines)


if __name__ == "__main__":
    unittest.main()
