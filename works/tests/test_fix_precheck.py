"""修正役の事前の確かめ（blk-fix/lib/factchecks.py）と、範囲の相談の節（頼み consult_prep・確かめ consult_check）・受け付け・支度の
つながり（設計 docs/plans/2026-10-06-ask-planner.md）の検査。本物の盤面で回す。

- 事前の確かめは受け付けと同じ口（凍ったテスト・書き込みの出どころ・範囲）で拒否の行を返し、盤面を 1 バイトも書かない
  （sandbox の中では盤面が書けない。scope を立てても scopes.json の登録と窓の照らしを飛ばす読み取りの印）
- 合意は確かめの節が盤面の trace（conflict.ASKED_OP）に書いた allow の行だけ（受け付けと事前の確かめが同じ口 conflict.agreed で読む）
- 頼み → 答え → 確かめ → 支度の続きの指示書 → 受け付け: 範囲の外のパスを相談で許されると、受け付けはそれを範囲に入れて通す。
  相談の周の受け付けは返答も盤面も見ない（拒否の理由のファイルも書かない）
- 枠を使い切った後の consult は受け付けが拒否の行にする
- 支度の節 fix-prep: 入力 plan_session と承認済みの修正案の項目が在る時だけ、相談の控えを run ごとの置き場に書き、指示書に相談の節
  （返答の欄 consult）を載せる
盤面は test_blk_fix の BoardCase（本物の darkfactory の表・種の git）で作る。
"""
import json
import os
import pathlib
import subprocess
import sys
import unittest

TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(TESTS))

import test_blk_fix  # noqa: E402  （core・blk-fix/lib を sys.path に足す）
import adapter  # noqa: E402
import conflict  # noqa: E402
import consult  # noqa: E402
import entry  # noqa: E402
import fixrules  # noqa: E402
import planmarks  # noqa: E402
import planscope  # noqa: E402
from test_blk_fix import FIXED, load, run_script  # noqa: E402

LIB = TESTS.parent / "blk-fix" / "lib"
SID = "11111111-2222-3333-4444-555555555555"
WHY = "mean の分母の直しは stats.py に在り、項目の範囲 docs/** の外"


class PrecheckCase(test_blk_fix.BoardCase):
    def ready(self, allowed):
        test_blk_fix.TestAccept.scope_ready(self, allowed)
        self.edit_tree(FIXED)
        self.place = pathlib.Path(adapter.run_place_of({"board": str(self.board)})) / consult.PLACE
        self.item = str(planmarks.approved_items(entry.open_board(self.board))[0]["item"])
        self.cfg = consult.write_config(self.place, {"board": str(self.board), "repo": str(self.repo), "scope": "",
                                                     "base_rev": "", "tdd_state": "", "pass": "first", "items": {}})

    def env(self, **more):
        return {"ARTIFACTS_DIR": str(self.art), "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"], **more}

    def agree(self, paths):
        """確かめの節が書く合意の行（allow）を盤面の trace に直に置く"""
        entry.open_board(self.board).trace(conflict.ASKED_OP, id=1, item=self.item, status=consult.ANSWERED,
                                           decision=consult.ALLOW, granted_paths=paths, granted_tests=[],
                                           reason="直しに伴うので足してよい")

    def precheck(self, reply=None, **env):
        argv = [sys.executable, str(LIB / "factchecks.py"), str(self.cfg)]
        if reply is not None:
            path = self.tmp / "draft.json"
            path.write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
            argv += ["--reply", str(path)]
        full = {"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1",
                "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"], **env}
        r = subprocess.run(argv, cwd=str(self.repo), env=full, capture_output=True, text=True, encoding="utf-8")
        return r.returncode, r.stdout, r.stderr

    def test_scope_reject_listed_and_board_untouched(self):
        self.ready(["docs/**"])
        before = test_blk_fix.board_shas(self.board)
        code, out, err = self.precheck(load("fix2_ok"))
        self.assertEqual(code, 1, err)
        got = json.loads(out)
        self.assertFalse(got["ok"])
        self.assertTrue(any(r["check"] == "scope" and "stats.py" in r["text"] for r in got["rejects"]), got)
        self.assertTrue(any(r["text"].startswith(planscope.REJECT_ASK) for r in got["rejects"] if r["check"] == "scope"),
                        "事前の確かめは相談の節の道具なので、拒否の頭は相談を先の道に言う")
        self.assertEqual(test_blk_fix.board_shas(self.board), before, "盤面を書かない")

    def test_board_agreement_counts(self):
        self.ready(["docs/**"])
        self.agree(["stats.py"])
        code, out, err = self.precheck(load("fix2_ok"))
        self.assertEqual((code, json.loads(out)["rejects"]), (0, []), out + err)

    def test_run_place_rows_do_not_count(self):
        """run ごとの置き場（役の Bash が書ける所）の行は合意に数えない（前の形の記録 exchanges.jsonl を偽っても範囲は広がらない）"""
        self.ready(["docs/**"])
        (self.place / "exchanges.jsonl").write_text(json.dumps(
            {"id": 1, "item": self.item, "status": "answered", "decision": "allow", "granted_paths": ["stats.py"],
             "granted_tests": [], "reason": "偽の合意の行（役が書ける所）"}) + "\n", encoding="utf-8")
        code, out, err = self.precheck(load("fix2_ok"))
        self.assertEqual(code, 1, out + err)

    def test_scoped_peek_writes_nothing(self):
        self.ready(["stats.py"])
        before = test_blk_fix.board_shas(self.board)
        doc = json.loads(self.cfg.read_text(encoding="utf-8"))
        consult.write_config(self.place, {**doc, "scope": "fixing"})
        code, out, err = self.precheck(load("fix2_ok"))
        self.assertEqual(code, 0, out + err)
        self.assertEqual(test_blk_fix.board_shas(self.board), before, "scope の登録も窓の照らしも書かない")

    def accept(self, reply=None, **more):
        return run_script("accept", self.repo, self.env(
            INPUTS_REPLY=json.dumps(reply or load("fix2_ok"), ensure_ascii=False), INPUTS_BASE_REV="", INPUTS_ITERATION="1",
            **more))

    def test_accept_reject_puts_planner_first_when_offered(self):
        """この段の相談の控え（項目の在る物）が在れば、受け付けの範囲の拒否の頭は相談（返答の欄 consult）を先の道に言う（run 249・249b
        は控えが在ったのに、申し出の道だけを言った）。控えが無ければ今どおり申し出の道（test_blk_fix の test_scope_reject_names_file）"""
        self.ready(["docs/**"])
        doc = json.loads(self.cfg.read_text(encoding="utf-8"))
        consult.write_config(self.place, {**doc, "items": {self.item: {"unit_keys": [], "allowed_paths": ["docs/**"],
                                                                       "out_of_scope": [], "tests": []}}})
        code, out, err = self.accept()
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertFalse(r["ok"], out)
        text = pathlib.Path(r["reason_file"]).read_text(encoding="utf-8")
        self.assertIn(planscope.REJECT_ASK, text)
        self.assertIn("consult", text)
        self.assertNotIn(planscope.REJECT, text)

    def test_accept_reject_keeps_conflict_route_for_other_pass(self):
        """控えが別の段（前の段の残り）の物なら、相談を言わない"""
        self.ready(["docs/**"])
        doc = json.loads(self.cfg.read_text(encoding="utf-8"))
        consult.write_config(self.place, {**doc, "pass": "ruled", "items": {self.item: {"unit_keys": [], "allowed_paths": [],
                                                                                        "out_of_scope": [], "tests": []}}})
        code, out, err = self.accept()
        self.assertEqual(code, 0, err)
        text = pathlib.Path(json.loads(out)["reason_file"]).read_text(encoding="utf-8")
        self.assertIn(planscope.REJECT, text)

    def test_accept_reads_board_agreement_and_passes(self):
        self.ready(["docs/**"])
        self.agree(["stats.py"])
        code, out, err = self.accept()
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ok"], out)

    def test_accept_rejects_consult_after_budget(self):
        """相談の周でない（確かめの節が consulted を言わない）のに consult を持つ返答は、枠を使い切った後の頼みとして拒む"""
        self.ready(["stats.py"])
        reply = {**load("fix2_ok"), conflict.CONSULT_FIELD: [{"item": int(self.item), "paths": ["docs/x.md"], "tests": [],
                                                              "why": WHY}]}
        code, out, err = self.accept(reply, INPUTS_CONSULTED="false")
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertFalse(r["ok"], out)
        self.assertEqual([x["check"] for x in r["rejects"]], ["consult"], r["rejects"])
        self.assertIn(str(consult.BUDGET), pathlib.Path(r["reason_file"]).read_text(encoding="utf-8"))

    def test_consulted_lap_touches_nothing(self):
        self.ready(["docs/**"])
        before = test_blk_fix.board_shas(self.board)
        code, out, err = self.accept({"not": "even a reply"}, INPUTS_CONSULTED="true")
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertEqual((r["ok"], r["done"], r["consulted"], r["reason_file"]), (False, False, True, ""))
        self.assertEqual(test_blk_fix.board_shas(self.board), before, "相談の周の受け付けは盤面に何も書かない")

    def prep_env(self, **more):
        b = entry.open_board(self.board)
        return self.env(INPUTS_PASS="first", INPUTS_JUDGMENT_FILE=str(self.board / b.state["outputs"]["p2.diagnose"]["file"]),
                        INPUTS_OPEN_UNITS=json.dumps([test_blk_fix.MEAN, test_blk_fix.CLAMP], ensure_ascii=False),
                        INPUTS_PLAN_FILE="", INPUTS_POLICY_PATH="", INPUTS_NOTES_FILE="", INPUTS_SUMMARY_FILE="",
                        INPUTS_BASE_REV="", INPUTS_PLAN_SESSION="plan", **more)

    def test_round_trip_grants_scope(self):
        """頼み → 答え → 確かめ → 続きの指示書 → 受け付け。範囲の外の stats.py を相談で許されると、受け付けは通す"""
        self.ready(["docs/**"])
        code, out, err = run_script("fix_prep", self.repo, self.prep_env())   # 1 回目の指示書（修正役が読む）
        self.assertEqual(code, 0, err)
        first = json.loads(out)
        peer = adapter.session_path(self.repo, "plan")
        peer.parent.mkdir(parents=True, exist_ok=True)
        peer.write_text(SID + "\n", encoding="utf-8")
        reply = {**load("fix2_ok"), conflict.CONSULT_FIELD: [{"item": int(self.item), "paths": ["stats.py"], "tests": [],
                                                              "why": WHY}]}
        code, out, err = run_script("consult_prep", self.repo, self.env(
            INPUTS_REPLY=json.dumps(reply, ensure_ascii=False), INPUTS_PLAN_SESSION="plan", INPUTS_PASS="first",
            INPUTS_ANSWER_NODE="plan-answer"))
        self.assertEqual(code, 0, err)
        asked = json.loads(out)
        self.assertEqual((asked["consulted"], asked["go"], asked["turn"]), (True, True, 1))
        self.assertIn("stats.py", pathlib.Path(asked["prompt_file"]).read_text(encoding="utf-8"))
        self.assertEqual(adapter.read_session_id(adapter.session_path(self.repo, consult.PEER)), SID)
        answer = {"answers": [{"ask": 1, "decision": "allow", "paths": ["stats.py"], "tests": [], "spec": "",
                               "reason": "分母の直しは仕様どおりで、stats.py を範囲に足す"}]}
        code, out, err = run_script("consult_check", self.repo, self.env(
            INPUTS_ANSWER=json.dumps(answer, ensure_ascii=False), INPUTS_PASS="first", INPUTS_ANSWER_NODE="plan-answer"))
        self.assertEqual(code, 0, err)
        checked = json.loads(out)
        self.assertEqual((checked["consulted"], checked["counts"]), (True, {"allow": 1}))
        (row,) = conflict.agreed(entry.open_board(self.board))
        self.assertEqual((row["item"], row["granted_paths"], row["node"]), (self.item, ["stats.py"], "plan-answer"))
        code, out, err = run_script("fix_prep", self.repo, self.prep_env())   # 続きの指示書
        self.assertEqual(code, 0, err)
        resumed = json.loads(out)
        self.assertEqual((resumed["iteration"], resumed["variants_file"]), (first["iteration"], ""),
                         "相談の周は受け付けの回に数えない")
        text = pathlib.Path(resumed["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(checked["answer_file"], text)
        self.assertIn(first["prompt_file"], text)
        code, out, err = run_script("fix_prep", self.repo, self.prep_env())   # 答えは 1 度だけ。次は普段の指示書
        self.assertEqual(json.loads(out)["prompt_file"], first["prompt_file"], err)
        code, out, err = self.accept()
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ok"], out)

    def test_no_peer_is_answered_unavailable(self):
        self.ready(["docs/**"])
        reply = {**load("fix2_ok"), conflict.CONSULT_FIELD: [{"item": int(self.item), "paths": ["stats.py"], "tests": [],
                                                              "why": WHY}]}
        code, out, err = run_script("consult_prep", self.repo, self.env(
            INPUTS_REPLY=json.dumps(reply, ensure_ascii=False), INPUTS_PLAN_SESSION="plan", INPUTS_PASS="first",
            INPUTS_ANSWER_NODE="plan-answer"))
        self.assertEqual(json.loads(out)["go"], False, err)
        code, out, err = run_script("consult_check", self.repo, self.env(INPUTS_ANSWER="null", INPUTS_PASS="first",
                                                                         INPUTS_ANSWER_NODE="plan-answer"))
        self.assertEqual(json.loads(out)["counts"], {"unavailable": 1}, err)
        self.assertEqual(conflict.agreed(entry.open_board(self.board)), [])


class AskPrepCase(test_blk_fix.BoardCase):
    """支度の節 fix-prep: 入力 plan_session が在り承認済みの修正案の項目が在る時だけ、相談の控えを run ごとの置き場に書き、指示書に
    範囲の相談（返答の欄 consult）と事前の確かめの節を載せる"""

    def prep(self, **env):
        test_blk_fix.TestAccept.scope_ready(self, ["stats.py"])
        b = entry.open_board(self.board)
        full = {"ARTIFACTS_DIR": str(self.art), "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"], "INPUTS_PASS": "first",
                "INPUTS_JUDGMENT_FILE": str(self.board / b.state["outputs"]["p2.diagnose"]["file"]),
                "INPUTS_OPEN_UNITS": json.dumps([test_blk_fix.MEAN, test_blk_fix.CLAMP], ensure_ascii=False),
                "INPUTS_PLAN_FILE": "", "INPUTS_POLICY_PATH": "", "INPUTS_NOTES_FILE": "", "INPUTS_SUMMARY_FILE": "",
                "INPUTS_BASE_REV": "", **env}
        code, out, err = run_script("fix_prep", self.repo, full)
        self.assertEqual(code, 0, err)
        return pathlib.Path(json.loads(out)["prompt_file"]).read_text(encoding="utf-8")

    def test_section_and_config_with_plan_session(self):
        text = self.prep(INPUTS_PLAN_SESSION="plan")
        cfg = consult.place_of(self.board) / consult.CONFIG
        self.assertIn(str(cfg), text)
        for w in ("`consult`", "factchecks.py", "--reply"):
            self.assertIn(w, text)
        self.assertNotIn("askplan", text)
        doc = json.loads(cfg.read_text(encoding="utf-8"))
        self.assertNotIn("session_file", doc, "控えは事前の確かめの材料だけ（相手の会話は支度が引かない）")
        self.assertEqual(set(doc["items"]), {self.item_no()})
        self.assertEqual(doc["items"][self.item_no()]["allowed_paths"], ["stats.py"])

    def test_ripple_named_with_ask(self):
        """修正案のブロックの波及の一覧（入力 ripple_file）は範囲の相談の節に名指す（範囲の外の当たりは先に相談する）"""
        ripple = self.tmp / "ripple.json"
        ripple.write_text('{"items": [], "overlaps": [], "error": ""}\n', encoding="utf-8")
        text = self.prep(INPUTS_PLAN_SESSION="plan", INPUTS_RIPPLE_FILE=str(ripple))
        self.assertIn(fixrules.RIPPLE_LINE.format(path=ripple), text)

    def test_no_section_without_plan_session(self):
        text = self.prep()
        self.assertNotIn(fixrules.RIPPLE_LINE.split("{")[0], text)
        self.assertNotIn("factchecks.py", text)
        self.assertFalse((consult.place_of(self.board) / consult.CONFIG).exists())

    def item_no(self):
        return str(planmarks.approved_items(entry.open_board(self.board))[0]["item"])


if __name__ == "__main__":
    unittest.main()
