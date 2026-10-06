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
from test_blk_fix import (BoardCase, CLAMP, FIXED, MEAN, PLAN_FIELDS, block, board_shas, find_node, load, pop_accept_last,  # noqa: E402
                          run_script)
from test_blk_fix import plan_reply as PLAN_REPLY  # noqa: E402  （split_plan_reply が元の 1 項目の案から作る）
from test_blk_fix_tdd import LoopCase  # noqa: E402

DEADLINE = 1728000000
WHY = "テストは分母 len(xs) - 1 の値を期待しているが、依頼は算術平均を求めている"
MEAN_FIX = {"sum(xs) / (len(xs) - 1)": "sum(xs) / len(xs)"}
CLAMP_FIX = {"    if x > hi:\n        return lo": "    if x > hi:\n        return hi"}
RULE_TEXT = "依頼は算術平均。test_mean_of_three の期待は正しいので、コードの分母を len(xs) に直せ"


def accept_script_module():
    """blk-fix の受け付けのスクリプトを同じプロセスに読み込んだ物（定数と関数を直に呼ぶ試験の口）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("blk_fix_accept_in_conflict", BLK / "scripts" / "accept.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


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


def in_include(include: str, node: str) -> dict:
    """include の名 include の中の節 node の居場所（Archon が script の節に渡す ARCHON_NODE_EXECUTION。依頼 239 の測り M1）。
    include が空なら線の最上段（変数を渡さない）"""
    return {"ARCHON_NODE_EXECUTION": json.dumps({"runId": "r", "path": f"{include}__{node}"})} if include else {}


class ConflictBoardCase(BoardCase):
    def accept_script(self, reply, *, iteration="1", pass_="first", include="", tdd_state="", tdd_suite=""):
        """受け付けのスクリプトを子で起こす。include は修正の段の include の名（2 回目の修正の段は refitting。空なら線の最上段）。
        tdd_state は輪の状態のファイル（INPUTS_TDD_STATE）、tdd_suite は試験の実行器（INPUTS_TDD_SUITE）。空は輪の無い run"""
        env = {"INPUTS_REPLY": json.dumps(reply, ensure_ascii=False), "INPUTS_BASE_REV": "", "INPUTS_TDD_STATE": tdd_state,
               "INPUTS_TDD_SUITE": tdd_suite,
               "INPUTS_ITERATION": iteration, "INPUTS_PASS": pass_, "ARTIFACTS_DIR": str(self.art),
               "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"], **in_include(include, "fix-loop.fix-accept")}
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
        pop_accept_last(self, before, after, r)
        self.assertEqual(after, before, "拒んだ申し出は盤面を書かない（理由の本文と最後の結果の控えの他）")

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
                                                    "plan_file": "", "policy_path": "", "notes_file": "", "summary_file": "",
                                                    "base_rev": ""}.items()}})
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


class TestRuledScope(ConflictBoardCase):
    def test_ruled_pass_widens_only_by_ruling_limits(self):
        """裁定の後（pass_="ruled"）の planscope.check は、直す裁定（fix_code_as）の limits が名指したパスだけ範囲を広げ、裁定を
        受けた単位の全部を外さない（limits に無い範囲の外のファイルは拒む）。limits のパスも 1 回目（pass_="first"）は拒む"""
        import planscope
        import writes
        self.parked()
        for name in ("other.py", "stray.py"):
            (self.repo / name).write_text("x = 1\n", encoding="utf-8")
        cid = self.items()[0]["id"]
        _, r = self.rule([{"id": cid, "decision": "fix_code_as", "text": RULE_TEXT, "limits": ["other.py:1"]}])
        self.assertTrue(r["ok"], r)
        b = entry.open_board(self.board)
        planmarks.save(self.board, b.round, [{"route": "direct", "route_why": "見本。先にテストを書かない", "tests": [],
                                               "rewrite_tests": [], "refactor": {"declared": False, "why": ""},
                                               "allowed_paths": ["stats.py"], "out_of_scope": []}])
        b = entry.open_board(self.board)
        rows = [{"unit_key": MEAN, "files": ["other.py", "stray.py"]}]
        rev = writes.base_rev(b, "")
        got, note = planscope.check(rows, b, self.repo, rev, ["other.py", "stray.py"], pass_="ruled")
        self.assertTrue(note["checked"])
        self.assertTrue(any(MEAN in p and "stray.py" in p for p in got), got)
        self.assertFalse(any("other.py" in p for p in got), got)
        got, _ = planscope.check(rows, b, self.repo, rev, ["other.py"], pass_="first")
        self.assertTrue(any(MEAN in p and "other.py" in p for p in got), got)

    def test_ruling_limit_does_not_open_out_of_scope(self):
        """直す裁定（fix_code_as）の limits が案の out_of_scope のパスを名指しても、裁定の後の照らしは拒む（out_of_scope は
        いつも勝つ。案が外したパスが要るのは案の項目の誤りで、fix_plan_item の道）"""
        import planscope
        import writes
        self.parked()
        (self.repo / "legacy.py").write_text("x = 1\n", encoding="utf-8")
        cid = self.items()[0]["id"]
        _, r = self.rule([{"id": cid, "decision": "fix_code_as", "text": RULE_TEXT, "limits": ["legacy.py"]}])
        self.assertTrue(r["ok"], r)
        planmarks.save(self.board, entry.open_board(self.board).round,
                       [{"route": "direct", "route_why": "見本。先にテストを書かない", "tests": [], "rewrite_tests": [],
                         "refactor": {"declared": False, "why": ""}, "allowed_paths": ["*.py"],
                         "out_of_scope": [{"glob": "legacy.py", "why": "古い置き場は触らない"}]}])
        b = entry.open_board(self.board)
        got, _ = planscope.check([{"unit_key": MEAN, "files": ["legacy.py"]}], b, self.repo, writes.base_rev(b, ""),
                                 ["legacy.py"], pass_="ruled")
        self.assertTrue(any(MEAN in p and "out_of_scope" in p and "legacy.py" in p for p in got), got)

    def test_ruled_unit_still_owes_its_item(self):
        """直す裁定（fix_code_as）を受けた単位は直す義務に残るので、その項目の欠け（tests のテストが無い）も裁定の後に拒む
        （案の項目そのものの誤りは fix_plan_item の道）"""
        import planscope
        import writes
        self.parked()
        cid = self.items()[0]["id"]
        _, r = self.rule([{"id": cid, "decision": "fix_code_as", "text": RULE_TEXT, "limits": ["stats.py:9"]}])
        self.assertTrue(r["ok"], r)
        planmarks.save(self.board, entry.open_board(self.board).round, PLAN_FIELDS)
        b = entry.open_board(self.board)
        rows = [{"unit_key": k, "files": ["stats.py"]} for k in (MEAN, CLAMP)]   # 案は 1 項目に mean と clamp を置く
        got, _ = planscope.check(rows, b, self.repo, writes.base_rev(b, ""), ["stats.py"], pass_="ruled")
        self.assertTrue(any("test_mean_of_two" in p and MEAN in p for p in got), got)

    def test_count_mismatch_halts_board(self):
        """修正案の項目と控えの欄の数が違う盤面は、照らしが控えの壊れた時の 1 本の道（conflict.fields_broken: 盤面を止めて
        BoardGap）に乗る"""
        import board as _board
        import planscope
        self.fix_ready()
        row = {"route": "direct", "route_why": "見本。先にテストを書かない", "tests": [], "rewrite_tests": [],
               "refactor": {"declared": False, "why": ""}, "allowed_paths": ["stats.py"], "out_of_scope": []}
        planmarks.save(self.board, entry.open_board(self.board).round, [row, row])
        with self.assertRaises(_board.BoardGap) as cm:
            planscope.check([], entry.open_board(self.board), self.repo, "HEAD", [], pass_="first")
        self.assertIn(planmarks.FIELDS_FILE, str(cm.exception))
        self.assertEqual(entry.open_board(self.board, allow_halted=True).state["stop"]["by"], conflict.FIELDS_STOP_BY)


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

    def test_resent_conflict_on_parked_unit_does_not_halt_last_round(self):
        """run 195d の 3 回目の型: 裁定の後の段で拒まれた返答の新しい申し出は機械が ask_human に裁いて積む。「丸ごと出し直せ」の
        とおり同じ申し出を最後の回に出し直しても、その単位はもう裁定が外した単位（held_by_rulings）なので、知っている申し出として
        外し、止めてよくない確かめで線を止めない"""
        import conflict
        self.parked()
        _, r = self.rule([{"id": self.items()[0]["id"], "decision": "fix_code_as", "text": RULE_TEXT, "limits": ["stats.py:9"]}])
        self.assertTrue(r["ok"], r)
        again = {**conflict_on_mean(), "why_both_cannot_hold": WHY + "（裁定の後にもう一度）"}
        reply = only_clamp_reply([again])
        doubled = dict(reply, changes=reply["changes"] * 2)   # 申し出は積まれ、返答はほかの確かめで拒まれる
        got = self.accept_script(doubled, pass_="ruled")
        self.assertFalse(got["ok"], got)
        self.assertIn(MEAN, conflict.held_by_rulings(entry.open_board(self.board)))
        got = self.accept_script(reply, pass_="ruled", iteration="3")
        self.assertEqual((got["ok"], got["done"]), (True, True), got)
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "done")
        self.assertEqual([i["ruling"]["decision"] for i in self.items()], ["fix_code_as", "ask_human"], "積み増さない")

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

        def step(state_file, reply, repo, try_query=None, lanes=None):
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


    def test_step_script_parks_lane_conflicts(self):
        # 並べの周（docs/plans/2026-10-06-tdd-parallel.md）: tddloop.step が返す conflicts の全部を盤面の控えに積む
        import importlib.util
        from unittest import mock
        spec = importlib.util.spec_from_file_location("blk_fix_tdd_step2", BLK / "scripts" / "tdd_step.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        a, b = {"unit_key": "a"}, {"unit_key": "b"}
        out = {"ok": True, "done": False, "reason": "", "phase": "test", "conflict": None, "conflicts": [a, b], "writes": None}
        with mock.patch.object(mod.tddloop, "step", return_value=out), \
                mock.patch.object(mod.entry, "open_board", return_value=mock.MagicMock()), \
                mock.patch.object(mod.conflict, "park") as park, \
                mock.patch.object(mod.script_io, "emit_result", return_value=0) as emit, \
                mock.patch.dict("os.environ", {"INPUTS_REPLY": "{}", "INPUTS_STATE_FILE": self.state,
                                               "ARTIFACTS_DIR": str(self.board.parent)}):
            self.assertEqual(mod.main(), 0)
        self.assertEqual(park.call_args.args[1], [a, b])
        self.assertNotIn("conflicts", emit.call_args.args[2])


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
        # 範囲の相談の 3 節（頼み・答え・確かめ）は役と受け付けの間（形は tests/test_consult.py が見る）
        self.assertEqual([n["id"] for n in g["nodes"]], ["fix-ruled-prep", "fix-ruled", "fix-ruled-consult", "plan-answer-ruled",
                                                         "fix-ruled-consult-check", "fix-ruled-accept"])
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
                                               "refactor": {"declared": False, "why": ""},
                                               "allowed_paths": ["stats.py", "test_stats.py"], "out_of_scope": []}])
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
                                 "rewrites": [self.REWRITE["id"]], "refactor": [], "names": []}})

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
                  contract={MEAN: {"items": [1], "route": "tdd", "tests": [], "rewrites": [rid], "refactor": []}})
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
                                               "refactor": {"declared": False, "why": ""},
                                               "allowed_paths": ["stats.py", "test_stats.py"], "out_of_scope": []}])
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


class AfterFrozen(Exception):
    """凍結の検査の後の確かめ（書き込みの出どころ）に来た印。凍結の誤りは積んで先へ進むので（依頼 224）、偽の盤面の試験は
    ここで止める"""


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
                mock.patch.object(mod, "check_writes", side_effect=AfterFrozen), \
                mock.patch.dict("os.environ", {"INPUTS_ITERATION": "1", "INPUTS_TDD_STATE": "/b/tdd.json",
                                               "INPUTS_PASS": "first"}), self.assertRaises(AfterFrozen):
            mod.accept_fix({"changes": []}, pathlib.Path("/b"), "", pathlib.Path("/r"))
        frozen.assert_called_once()
        limits.assert_called_once_with(mock.ANY, rulings=False, source=mock.ANY, skip_ids=[], agreed_rows=None)
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
                    mock.patch.object(mod, "check_writes", side_effect=AfterFrozen), \
                    mock.patch.dict("os.environ", {"INPUTS_ITERATION": "1", "INPUTS_TDD_STATE": "/b/tdd.json",
                                                   "INPUTS_PASS": pass_}), self.assertRaises(AfterFrozen):
                mod.accept_fix({"changes": []}, pathlib.Path("/b"), "", pathlib.Path("/r"))
            frozen.assert_called_once()
            vr.assert_called_once_with("/b/tdd.json")
            self.assertEqual(limits.call_args.kwargs["skip_ids"], ["t.py::T::test_a"], pass_)
            self.assertEqual(limits.call_args.kwargs["rulings"], pass_ == "ruled")


class TestPriorLoopsKeepRulings(unittest.TestCase):
    """前の輪（1 回目の修正の段の輪）の凍結の検査は、前の段の裁定 fix_test_scope の範囲をいつも許す。今の受け付けが first でも
    （2 回目の修正の段に輪が無い run・輪が在る run のどちらも）。今の輪の許しだけが pass で決まる"""

    def check(self, state, pass_):
        import importlib.util
        spec = importlib.util.spec_from_file_location("blk_fix_accept_script_prior", BLK / "scripts" / "accept.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        limits = mock.MagicMock(return_value=[])
        with mock.patch.object(mod.conflict, "ruled_test_limits", limits), \
                mock.patch.object(mod.conflict, "amended_keys", return_value=set()), \
                mock.patch.object(mod.tddloop, "states", return_value=[pathlib.Path("/b/tdd-1/state.json")]), \
                mock.patch.object(mod.tddloop, "frozen_problems", return_value=[]), \
                mock.patch.object(mod.tddloop, "frozen_source", return_value=lambda *a: None), \
                mock.patch.object(mod.tddloop, "verified_rewrites", return_value=[]), \
                mock.patch.object(mod.tddloop, "test_spans", return_value={}), \
                mock.patch.object(mod.tddloop, "load_state", return_value={"handoff": "h" * 40}), \
                mock.patch.object(mod.entry, "open_board", return_value=mock.MagicMock()):
            self.assertEqual(mod.check_frozen(pathlib.Path("/b"), state, pathlib.Path("/r"), pass_), [])
        return [c.kwargs["rulings"] for c in limits.call_args_list]

    def test_second_pass_without_loop_keeps_prior_rulings(self):
        self.assertEqual(self.check("", "first"), [True])

    def test_second_pass_with_loop_keeps_prior_rulings(self):
        self.assertEqual(self.check("/b/tdd-2/state.json", "first"), [False, True], "今の輪は first で裁定を含めず、前の輪は含める")
        self.assertEqual(self.check("/b/tdd-2/state.json", "ruled"), [True, True])


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
                                                    "plan_file": "", "policy_path": "", "notes_file": "", "summary_file": "",
                                                    "base_rev": ""}.items()}})
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


def split_plan_reply(narrows=()):
    """修正案を単位ごとの 2 項目にした返答（項目 1 は mean だけ、項目 2 は clamp だけ）"""
    base = PLAN_REPLY(narrows)["plan"][0]
    return {"plan": [{**base, "unit_keys": [MEAN], "approach": "mean の分母を len(xs) に直す"},
                     {**base, "unit_keys": [CLAMP], "approach": "clamp の上限の枝の戻り値を hi に直す"}]}


# 2 項目の案の項目 2（clamp）の works の欄。項目 1 の欄 PLAN_FIELDS の tests は mean の test_mean_of_two で clamp には当たらない。
# clamp は種の test_clamp_above_range が今も赤で直しを縛るので、新しいテストを足さない direct の道にする
CLAMP_FIELDS = {**PLAN_FIELDS[0], "route": "direct", "tests": [],
                "route_why": "種の test_clamp_above_range が今の上限の枝で赤になり、直しを縛る"}


class ReplanCase(ConflictBoardCase):
    """裁定 fix_plan_item の盤面の口（mean を申し出た盤面に修正案の欄の控えと brief を置いてから裁く）。既定の修正案は mean と clamp を
    別の項目に置く（fix_plan_item が外すのは項目 1 の単位だけで、clamp は直す義務に残る）。SHARED_ITEM が真なら 1 項目に両方を置く"""
    SHARED_ITEM = False

    def replanned(self):
        """mean の申し出を fix_plan_item に裁いた盤面。返りは self.rule の返り (prep, 受け付けの結果)"""
        import planbrief
        import test_blk_fix
        if self.SHARED_ITEM:
            self.parked()
        else:
            with mock.patch.object(test_blk_fix, "plan_reply", split_plan_reply):
                self.parked()
        fields = test_blk_fix.PLAN_FIELDS + ([] if self.SHARED_ITEM else [CLAMP_FIELDS])
        planmarks.save(self.board, entry.open_board(self.board).round, fields)
        planbrief.cut_at(self.board)
        cid = self.items()[0]["id"]
        brief = entry.open_board(self.board).work("brief-1.md")
        return self.rule([{"id": cid, "decision": "fix_plan_item", "text": PLAN_TEXT, "limits": [], "grounds": [f"{brief}:1"]}])


class TestHeldWorkStays(ReplanCase):
    """run 195d の型: 裁定 fix_plan_item が、TDD の輪で緑にした単位（受け入れのテストが凍ったファイルに在る）を含む項目を外した。
    裁定の後の段は、その単位の 1 回目の直しを戻さず（戻せば輪が赤を確かめたテストが赤になり、どの行にも結べず諦める）、
    範囲でも外れた項目をほかの項目と同じに扱い、空の changes の返答を控えて案の直しへ渡す"""

    def tdd_green(self):
        """修正の節が待つ盤面で TDD の輪を回し、MEAN を緑にする（CLAMP は direct）。返りは (輪の状態のファイル, 実行器のパス)。
        fix_ready は呼び手が済ませる"""
        import tddloop
        import test_blk_fix_tdd as tbt
        suite = self.tmp / "suite.py"
        suite.write_text(tbt.SUITE, encoding="utf-8")
        start = tddloop.start(self.board, self.repo, str(suite), tbt.OPEN)
        self.assertTrue(start["go"], start)
        state = start["state_file"]
        why = "文書の直しと同じで、先にテストを書けない単位"
        got = tddloop.step(state, {"phase": "route", "units": [{"unit_key": MEAN, "route": "tdd"},
                                                               {"unit_key": CLAMP, "route": "direct", "why": why}]}, self.repo)
        self.assertTrue(got["ok"], got)
        path = self.repo / "test_stats.py"
        path.write_text(path.read_text(encoding="utf-8").replace("\n\nif __name__", tbt.NEW_TEST + "\n\nif __name__"),
                        encoding="utf-8")
        got = tddloop.step(state, {"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"],
                                   "tests": ["test_stats.py::TestStats::test_mean_of_two"]}, self.repo)
        self.assertTrue(got["ok"], got)
        self.edit_tree(MEAN_FIX)
        got = tddloop.step(state, {"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母を len(xs) にした"},
                           self.repo)
        self.assertTrue(got["ok"], got); self.assertTrue(got["done"], got)
        self.assertEqual(list(json.loads(pathlib.Path(state).read_text(encoding="utf-8"))["frozen"]), ["test_stats.py"])
        return state, str(suite)

    def rule_on_plan(self, unit, fields):
        """修正案の欄 fields の控えと brief を置き、unit の申し出を fix_plan_item に裁く"""
        import planbrief
        planmarks.save(self.board, entry.open_board(self.board).round, fields)
        planbrief.cut_at(self.board)
        cid = next(i["id"] for i in self.items() if i["unit_key"] == unit)
        brief = entry.open_board(self.board).work("brief-1.md")
        _, r = self.rule([{"id": cid, "decision": "fix_plan_item", "text": PLAN_TEXT, "limits": [], "grounds": [f"{brief}:1"]}])
        self.assertTrue(r["ok"], r)

    def held_tdd_board(self):
        """MEAN と CLAMP を 1 項目に載せた案で、輪が MEAN を緑にし、1 回目の修正役が MEAN の行を返して CLAMP を申し出、CLAMP の申し出が
        fix_plan_item に裁かれて項目の 2 単位とも外れた盤面（直す義務は空）。返りは (輪の状態のファイル, 実行器のパス)"""
        import test_blk_fix
        self.SHARED_ITEM = True
        self.fix_ready()
        state, suite = self.tdd_green()
        reply = load("fix2_ok")
        reply["changes"] = [{**c, "files": ["stats.py", "test_stats.py"]} for c in reply["changes"] if c["unit_key"] == MEAN]
        reply["interactions"] = []
        reply["conflicts"] = [{**conflict_on_mean(), "unit_key": CLAMP}]
        got = self.accept_script(reply, tdd_state=state, tdd_suite=suite)
        self.assertEqual((got["ok"], got.get("parked")), (True, True), got)
        self.rule_on_plan(CLAMP, test_blk_fix.PLAN_FIELDS)
        held = conflict.held_by_rulings(entry.open_board(self.board, allow_halted=True))
        self.assertIn(MEAN, held); self.assertIn(CLAMP, held)
        return state, suite

    def ruled_until_through(self, reply, state, suite):
        """裁定の後の段の受け付けを、通るか 3 回目まで同じ返答で回す（195d は 3 回とも拒まれ、3 回目で諦めた）"""
        for it in ("1", "2", "3"):
            got = self.accept_script(reply, pass_="ruled", iteration=it, tdd_state=state, tdd_suite=suite)
            if got["ok"]:
                break
        return got

    def assert_held_for_replan(self, got):
        import replan
        self.assertEqual((got["ok"], got["done"], got.get("parked")), (True, True, True), got)
        b = entry.open_board(self.board, allow_halted=True)
        self.assertTrue(b.work(conflict.HELD_REPLY).is_file(), "控えて案の直しへ渡す")
        self.assertTrue(replan.material(b)["go"], "h-replan が回る")
        ops = [json.loads(x).get("op") for x in (self.board / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertNotIn("fix_ruled_reverted", ops)

    def test_ruled_pass_keeps_held_tdd_work_and_holds_for_replan(self):
        state, suite = self.held_tdd_board()
        got = self.ruled_until_through(only_clamp_reply() | {"changes": []}, state, suite)
        self.assert_held_for_replan(got)
        self.assertIn("sum(xs) / len(xs)", (self.repo / "stats.py").read_text(encoding="utf-8"), "外れた単位の直しを戻した")

    def test_fixer_that_keeps_editing_held_files_is_held_for_replan(self):
        """195d の修正役は約束に従わず、裁定の後も外れた単位のファイルに手を入れ続けた。返答の行に書かない手入れは範囲でも
        戻しでも裁かず（決め 2。守りは行の確かめ）、手入れを作業ツリーに残したまま控えて案の直しへ渡す"""
        state, suite = self.held_tdd_board()
        touched = "    return sum(xs) / len(xs)  # 裁定の後の修正役の手入れ"
        self.edit_tree({"    return sum(xs) / len(xs)": touched})
        got = self.ruled_until_through(only_clamp_reply() | {"changes": []}, state, suite)
        self.assert_held_for_replan(got)
        self.assertIn(touched, (self.repo / "stats.py").read_text(encoding="utf-8"), "外れた単位のファイルを戻した")

    def test_last_round_row_for_held_unit_is_dropped_without_revert(self):
        """裁定の後の段の 3 回目の返答が外れた MEAN を changes に書いた: 機械はその行を数えずに changes から外し（義務の外の単位に
        だけ結んだ行）、MEAN の 1 回目の直しを作業ツリーに残したまま控えて案の直しへ渡す。trace の行は戻した直しの控え（patch）を持たない"""
        accept_mod = accept_script_module()
        state, suite = self.held_tdd_board()
        reply = load("fix2_ok")
        reply["changes"] = [{**c, "files": ["stats.py", "test_stats.py"]} for c in reply["changes"] if c["unit_key"] == MEAN]
        reply["interactions"] = []
        got = self.accept_script(reply, pass_="ruled", iteration="3", tdd_state=state, tdd_suite=suite)
        self.assert_held_for_replan(got)
        self.assertIn("sum(xs) / len(xs)", (self.repo / "stats.py").read_text(encoding="utf-8"), "外れた単位の直しを戻した")
        rows = [json.loads(x) for x in (self.board / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        dropped = [r for r in rows if r.get("op") == accept_mod.ABSORBED_OP]
        self.assertEqual(len(dropped), 1, rows)
        self.assertEqual(dropped[0]["dropped"], [MEAN])
        self.assertNotIn("patch", dropped[0])

    def test_bound_unit_sharing_a_file_with_held_unit_moves_both_to_the_patch(self):
        """最後の回に単位に結んだ拒否で止める単位（開いていない残りの単位 RESIDUE）が、外れた単位 MEAN（輪で緑にした足跡）と
        stats.py を共にする: ファイルは単位ごとに分けて戻せないので、MEAN の直しも段の頭の木に戻して控えの patch に移し（消えない）、
        RESIDUE の裁定の文に MEAN を名指す。受け付けのスクリプトの最後の回で回す"""
        import parking
        state, suite = self.held_tdd_board()
        residue = "stats.py residue: 残りの単位"
        reply = load("fix2_ok")
        reply["changes"] = [{**reply["changes"][0], "unit_key": residue}]
        reply["interactions"] = []
        got = self.accept_script(reply, pass_="ruled", iteration="3", tdd_state=state, tdd_suite=suite)
        self.assertEqual((got["ok"], got["done"]), (True, True), got)
        rows = [json.loads(x) for x in (self.board / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        parked = [r for r in rows if r.get("op") == "fix_bound_parked"]
        self.assertEqual([r["unit_keys"] for r in parked], [[residue]])
        self.assertTrue(any(t.startswith(parking.SHARED_OUT + MEAN) for t in parked[0]["reasons"][residue]), parked)
        self.assertNotIn("sum(xs) / len(xs)", (self.repo / "stats.py").read_text(encoding="utf-8"), "足跡は段の頭の木に戻る")
        self.assertIn("sum(xs) / len(xs)", pathlib.Path(parked[0]["patch"]).read_text(encoding="utf-8"), "外れた単位の直しは控えに残る")

    def test_rulings_say_keep_held_work(self):
        self.held_tdd_board()
        text = entry.open_board(self.board).work(conflict.RULINGS_FILE).read_text(encoding="utf-8")
        self.assertIn("作業ツリーにそのまま残す（戻すな・触るな", text)
        self.assertNotIn("機械も戻す", text)
        self.assertNotIn("作業ツリーから戻す", conflict.LATE_REPLAN_PROMISE)
        self.assertIn(conflict.HELD_WORK_KEPT, conflict.GAVE_UP_PROMISE)

    def test_shared_file_with_owed_unit_keeps_both(self):
        """輪で緑にした MEAN を輪の後に申し出て fix_plan_item に裁かれ（項目 1 だけ外れ、項目 2 の CLAMP は義務に残る）、外れた
        MEAN の輪の直しと義務の CLAMP の直しが stats.py を共にする（195d の report.py）。CLAMP の行だけの返答で通り、両方が残る"""
        import test_blk_fix
        with mock.patch.object(test_blk_fix, "plan_reply", split_plan_reply):
            self.fix_ready()
        state, suite = self.tdd_green()
        self.edit_tree(CLAMP_FIX)
        got = self.accept_script(only_clamp_reply([conflict_on_mean()]), tdd_state=state, tdd_suite=suite)
        self.assertEqual((got["ok"], got.get("parked")), (True, True), got)
        self.rule_on_plan(MEAN, test_blk_fix.PLAN_FIELDS + [CLAMP_FIELDS])
        got = self.accept_script(only_clamp_reply(), pass_="ruled", tdd_state=state, tdd_suite=suite)
        self.assertTrue(got["ok"], got)
        text = (self.repo / "stats.py").read_text(encoding="utf-8")
        self.assertIn("sum(xs) / len(xs)", text); self.assertIn("return hi", text)


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

    def test_test_of_the_held_item_is_in_scope(self):
        """fix_plan_item が外した項目の tests のテスト（項目 1 の test_mean_of_two）を残った単位の直しが足しても、範囲では拒まない
        （決め 2: 外れた単位を直させない守りは返答の行の確かめと指示書の約束だけ。範囲は外れた項目もほかの項目と同じに扱う）"""
        self.replanned()
        path = self.repo / "test_stats.py"
        path.write_text(path.read_text(encoding="utf-8").replace(
            "    def test_clamp_within_range", "    def test_mean_of_two(self):\n        self.assertEqual(mean([1, 3]), 2)\n\n"
            "    def test_clamp_within_range"), encoding="utf-8")
        reply = only_clamp_reply()
        reply["changes"][0]["files"] = ["stats.py", "test_stats.py"]
        r = self.accept_script(reply, pass_="ruled")
        self.assertTrue(r["ok"], r)

    def test_fix_plan_item_without_brief_is_rejected(self):   # brief を置かない盤面
        self.parked()
        _, r = self.rule([{"id": self.items()[0]["id"], "decision": "fix_plan_item", "text": PLAN_TEXT, "limits": []}])
        self.assertEqual((r["ok"], r["done"]), (False, False)); self.assertIn("brief", r["reason"])


class TestFixPlanItemReport(ReplanCase):
    """fix_plan_item の単位は次の run へ持ち越さない。h-rejudge（replan.settle）が待つ行を諦めた行にし、ask_human と同じ道
    （最後の関所を開ける・結末 needs_human・次の run の依頼に裁定の文を字のまま）に載る"""

    @staticmethod
    def clamp_reply():
        """only_clamp_reply の clamp の site に path を足した返答（fix2_ok の site は path を持たず、数え直しの表が「合わない」と
        言って最後の関所を開けるので、関所が諦めた単位で開くことを見る試験にはこの形を渡す）"""
        reply = only_clamp_reply()
        for s in reply["changes"][0]["closure"]["sites"]:
            s["path"] = "stats.py"
        return reply

    def gave_up(self):
        import replan
        self.replanned()
        self.assertTrue(self.accept_script(self.clamp_reply(), pass_="ruled")["ok"])
        replan.settle(self.board, self.repo)

    def test_gave_up_unit_goes_to_gate_and_next_request_verbatim(self):
        import line_edge
        import report
        self.gave_up()
        b = entry.open_board(self.board)
        got = line_edge.final_edge(b, self.repo, run_id="run-12", mode="when_needed", tests={"ok": True, "green": True})
        self.assertTrue(got.get("ask"), "ask_human と同じく関所を開ける")
        self.assertIn(PLAN_TEXT, got["gate_text"])
        self.assertIn("食い違いの申し出を人に回した（1 件）", got["gate_text"].splitlines()[0])
        items = report.next_request(entry.open_board(self.board, allow_halted=True))
        hit = [i for i in items if i["where"] == MEAN]
        self.assertEqual(len(hit), 1, items)
        self.assertIn(f"裁定の文: {PLAN_TEXT}。", hit[0]["text"])
        self.assertIn(f"案の直し: {replan_close_why()}", hit[0]["text"])
        for text in (got["gate_text"], hit[0]["text"]):   # 諦めた単位の 1 回目の直しは作業ツリーに残っている（依頼 241）
            self.assertIn(conflict.HELD_WORK_KEPT, text)
        self.assertFalse(hasattr(report, "REPLAN_HEAD"))
        self.assertFalse(hasattr(report, "replanned_lines"))

    def test_ruling_text_is_verbatim_in_next_request(self):
        """裁定の文は改行も字のまま（_one_line で潰さない）"""
        import report
        self.gave_up()
        b = entry.open_board(self.board, allow_halted=True)
        doc = json.loads(b.work(conflict.FILE).read_text(encoding="utf-8"))
        doc["items"][0]["ruling"]["text"] = "1 行目\n  2 行目"
        b.work(conflict.FILE).write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        items = report.next_request(entry.open_board(self.board, allow_halted=True))
        self.assertTrue(any(i["where"] == MEAN and "裁定の文: 1 行目\n  2 行目。" in i["text"] for i in items), items)

    def test_outcome_is_needs_human_not_round_limit(self):
        import report
        self.gave_up()
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(report.decide_outcome(b, {"accepted": True, "round_closed": True}), "needs_human")
        self.assertEqual(report.decide_outcome(b, {"accepted": True, "round_closed": True}, judged={"need_fix": False}),
                         "needs_human")

    def test_conflict_line_has_kinds_and_replan(self):
        import report
        self.replanned()
        lines = report.head_decisions(entry.open_board(self.board), {"accepted": True, "round_closed": True})
        hit = next(x for x in lines if x.startswith(conflict.HEAD))
        for w in ("案の項目を直す（fix_plan_item）1", "種類の内訳", "unnamed_test_broke 1", "not_red 0"):
            self.assertIn(w, hit)

    def test_next_request_owns_validator_row(self):
        """諦めた単位の検証器の行は次の run の依頼に渡さない（単位の行が持つ）"""
        import report
        self.gave_up()
        b = entry.open_board(self.board, allow_halted=True)
        left = [{"where": report.VALIDATOR_WHERE, "text": f"[block] 未解消: {MEAN}"},
                {"where": report.VALIDATOR_WHERE, "text": f"[block] 未解消: {CLAMP}"}]
        items = report.next_request(b, left=left)
        self.assertFalse(any(i["where"] == report.VALIDATOR_WHERE and i["text"].endswith(MEAN) for i in items), items)
        self.assertTrue(any(i["where"] == report.VALIDATOR_WHERE and i["text"].endswith(CLAMP) for i in items), items)

    def test_waiting_unit_is_not_carried(self):
        """締める前（待つ行）の単位は、次の run の依頼に持ち越しの行を作らない"""
        import report
        self.replanned()
        b = entry.open_board(self.board, allow_halted=True)
        self.assertFalse(any(i["where"] == MEAN for i in report.next_request(b)))


def replan_close_why():
    import replan
    return replan.CLOSE_WHY


class TestFixPlanItemWholeItem(ReplanCase):
    """fix_plan_item は、裁いた案の項目に載る単位を全部、直す義務から外す（決まりは 1 つ: 直す裁定でない裁定は、その単位と、
    fix_plan_item ならその項目の単位を外す）。項目の外の単位は今どおり直す。諦めれば項目の単位の全部が ask_human の行になる"""

    def test_units_sharing_the_item_are_held(self):
        import replan
        import report
        self.SHARED_ITEM = True
        _, r = self.replanned()
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.items()[0]["ruling"]["plan_units"], [MEAN, CLAMP])
        b = entry.open_board(self.board, allow_halted=True)
        held = conflict.held_by_rulings(b)
        cid = self.items()[0]["id"]
        for k in (MEAN, CLAMP):
            self.assertIn(f"fix_plan_item の裁定 {cid}", held[k]); self.assertIn("案の項目 1", held[k])
        self.assertIn(CLAMP, pathlib.Path(r["rulings_file"]).read_text(encoding="utf-8"), "裁定の文が項目の単位を名指す")
        got = self.accept_script(only_clamp_reply(), pass_="ruled")   # parked が clamp を直した作業ツリーのまま
        self.assertFalse(got["ok"]); self.assertIn("fix_plan_item", got["reason"])
        self.edit_tree({v: k for k, v in CLAMP_FIX.items()})   # clamp の直しを戻し、空の changes で出し直す
        got = self.accept_script(only_clamp_reply() | {"changes": []}, pass_="ruled", iteration="2")
        self.assertTrue(got["ok"], got)
        replan.settle(self.board, self.repo)
        b = entry.open_board(self.board, allow_halted=True)
        items = report.next_request(b, left=[{"where": report.VALIDATOR_WHERE, "text": f"[block] 未解消: {CLAMP}"}])
        self.assertEqual(sum(CLAMP in i["where"] or CLAMP in i["text"] for i in items), 1,
                         "項目を共にして止まった単位の検証器の行は単位の行が持つ（二重に渡さない）")
        self.assertEqual(report.decide_outcome(b, {"accepted": True, "round_closed": True}), "needs_human")

    def test_whole_item_units_each_get_a_row(self):
        """諦めた行は、その項目の単位（ruled_units）ごとに次の run の依頼の行を 1 つ持ち、どれも裁定の文を字のまま載せる"""
        import replan
        import report
        self.SHARED_ITEM = True
        self.replanned()
        replan.settle(self.board, self.repo)
        items = report.next_request(entry.open_board(self.board, allow_halted=True))
        for k in (MEAN, CLAMP):
            hit = [i for i in items if i["where"] == k]
            self.assertEqual(len(hit), 1, (k, items))
            self.assertIn(PLAN_TEXT, hit[0]["text"])

    def test_unit_outside_the_item_is_unaffected(self):
        import replan
        import report
        _, r = self.replanned()
        self.assertTrue(r["ok"], r)
        self.assertEqual(self.items()[0]["ruling"]["plan_units"], [MEAN])
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(set(conflict.held_by_rulings(b)), {MEAN})
        self.assertIn(CLAMP, conflict.fix_duty(b)[0])
        replan.settle(self.board, self.repo)
        self.assertFalse(any(i["where"] == CLAMP for i in report.next_request(entry.open_board(self.board, allow_halted=True))))

    def test_parked_fix_of_a_held_unit_stays(self):
        """1 回目に clamp を直して mean を申し出、mean が fix_plan_item に裁かれて clamp も止まった盤面で、2 回目が changes を
        空にしただけで出せば、受け付けは控えの返答の clamp の直しを作業ツリーに残したまま通す（外れた単位の直しは戻さない。依頼 241）"""
        self.SHARED_ITEM = True
        _, r = self.replanned()
        self.assertTrue(r["ok"], r)
        b = entry.open_board(self.board, allow_halted=True)
        before = b.work(conflict.PARKED_REPLY).read_bytes()
        got = self.accept_script(only_clamp_reply() | {"changes": []}, pass_="ruled")
        self.assertTrue(got["ok"], got)
        self.assertIn("return hi", (self.repo / "stats.py").read_text(encoding="utf-8"), "clamp の直しを戻した")
        self.assertEqual(b.work(conflict.PARKED_REPLY).read_bytes(), before, "控えの返答は変えない")
        rows = [json.loads(x) for x in (self.board / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertFalse([x for x in rows if x.get("op") == "fix_ruled_reverted"])


def accept_module():
    """受け付けのスクリプト（blk-fix/scripts/accept.py。.shared/core の accept と名が重なるので別名で読む）"""
    import importlib.util
    spec = importlib.util.spec_from_file_location("accept_script_mod", BLK / "scripts" / "accept.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestFixPlanItemBothUnits(ReplanCase):
    """同じ項目の 2 単位を両方とも申し出て、同じ返答で裁いた盤面"""

    CLAMP_WHY = "テストは上限の枝で hi を期待しているが、依頼は上限の枝を lo に寄せると書いている"

    def ruled_both(self, clamp_decision="fix_plan_item"):
        """mean と clamp を 1 項目に置いた案で、2 単位とも申し出た盤面を裁く（mean は fix_plan_item、clamp は clamp_decision）"""
        import planbrief
        import test_blk_fix
        self.fix_ready()
        clamp = {"unit_key": CLAMP, "between": ["stats.py:16", "test_stats.py:15"], "why_both_cannot_hold": self.CLAMP_WHY,
                 "which_is_right": "request", "kind": "unnamed_test_broke"}
        r = self.accept_script(only_clamp_reply([conflict_on_mean(), clamp]) | {"changes": []})
        self.assertEqual((r["ok"], r.get("parked")), (True, True), r)
        planmarks.save(self.board, entry.open_board(self.board).round, test_blk_fix.PLAN_FIELDS)
        planbrief.cut_at(self.board)
        brief = entry.open_board(self.board).work("brief-1.md")
        ids = {i["unit_key"]: i["id"] for i in self.items()}
        return self.rule([{"id": ids[MEAN], "decision": "fix_plan_item", "text": PLAN_TEXT, "limits": [],
                           "grounds": [f"{brief}:1"]},
                          {"id": ids[CLAMP], "decision": clamp_decision, "text": PLAN_TEXT, "limits": [],
                           "grounds": [f"{brief}:1"]}])

    def test_each_unit_once_when_both_are_ruled(self):
        """2 件の fix_plan_item がどちらも同じ 2 単位を外し、どちらも諦めても、次の依頼は単位ごとに 1 行（単位自身の裁定の行）で、
        最後の関所と報告の ask_human の行は裁定ごとに 1 行"""
        import replan
        import report
        _, r = self.ruled_both()
        self.assertTrue(r["ok"], r)
        self.assertEqual(len(replan.settle(self.board, self.repo)["closed"]), 2)
        b = entry.open_board(self.board, allow_halted=True)
        ids = {i["unit_key"]: i["id"] for i in self.items()}
        lines = conflict.human_lines(b)
        self.assertEqual([x.split(": ")[0] for x in lines], [MEAN.split(": ")[0], CLAMP.split(": ")[0]], lines)
        for k, x in zip((MEAN, CLAMP), lines):
            self.assertIn(ids[k], x); self.assertIn(PLAN_TEXT, x)
        items = report.next_request(b)
        self.assertEqual([i["where"] for i in items if i["where"] in (MEAN, CLAMP)], [MEAN, CLAMP], items)
        own = {i["where"]: i["text"] for i in items}
        self.assertIn("stats.py:16", own[CLAMP], "単位自身の申し出の名指しを載せる")

    def test_fix_ruling_inside_a_replanned_item_is_rejected(self):
        """同じ返答で fix_plan_item に裁いた項目の単位に直す裁定を出せば、単位と項目を名指して拒む"""
        _, r = self.ruled_both("fix_code_as")
        self.assertEqual((r["ok"], r["done"]), (False, False), r)
        for w in (CLAMP, "案の項目 1", "fix_code_as", "fix_plan_item"):
            self.assertIn(w, r["reason"])
        self.assertTrue(all(i["ruling"] is None for i in self.items()), "拒んだ返答の裁定は積まない")


class TestParkedOpSingleSource(unittest.TestCase):
    """止めた単位の trace の語 fix_bound_parked の正本は core の conflict に 1 つ。書く accept と読む report は字の写しを持たない"""

    WORD = "fix_bound_parked"

    def test_word_has_one_source_in_core(self):
        self.assertEqual(getattr(conflict, "ACCEPT_PARKED_OP", None), self.WORD)
        self.assertEqual(accept_script_module().PARKED_OP, getattr(conflict, "ACCEPT_PARKED_OP", None))
        for path in (CORE / "report.py", BLK / "scripts" / "accept.py"):
            src = path.read_text(encoding="utf-8")
            self.assertNotIn(f'"{self.WORD}"', src, f"{path.name} に字の写しが残っている")
            self.assertNotIn(f"'{self.WORD}'", src, f"{path.name} に字の写しが残っている")


if __name__ == "__main__":
    unittest.main()
