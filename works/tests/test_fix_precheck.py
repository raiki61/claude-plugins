"""修正役の事前の確かめ（blk-fix/lib/factchecks.py）と、受け付けが範囲の相談の記録を盤面へ写して読む（設計
docs/plans/2026-10-06-ask-planner.md）の検査。

- 事前の確かめは受け付けと同じ口（凍ったテスト・書き込みの出どころ・範囲）で拒否の行を返し、盤面を 1 バイトも書かない
  （sandbox の中では盤面が書けない。scope を立てても scopes.json の登録と窓の照らしを飛ばす読み取りの印）
- run ごとの置き場にまだ在るだけの合意（allow）も足して照らす（受け付けと同じ答え）
- 受け付けは頭で記録を trace（conflict.ASKED_OP）へ写し、合意のパスを範囲に入れて通す
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
import askplan  # noqa: E402
import conflict  # noqa: E402
import entry  # noqa: E402
import fixrules  # noqa: E402
import planmarks  # noqa: E402
from test_blk_fix import FIXED, load, run_script  # noqa: E402

LIB = TESTS.parent / "blk-fix" / "lib"


class PrecheckCase(test_blk_fix.BoardCase):
    def ready(self, allowed):
        test_blk_fix.TestAccept.scope_ready(self, allowed)
        self.edit_tree(FIXED)
        self.place = pathlib.Path(adapter.run_place_of({"board": str(self.board)})) / askplan.PLACE
        self.item = str(planmarks.approved_items(entry.open_board(self.board))[0]["item"])
        self.cfg = askplan.write_config(self.place, {"board": str(self.board), "repo": str(self.repo), "scope": "",
                                                     "base_rev": "", "tdd_state": "", "pass": "first", "items": {}})

    def agree(self, paths):
        with open(self.place / askplan.LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"id": 1, "item": self.item, "status": askplan.ANSWERED, "decision": askplan.ALLOW,
                                "granted_paths": paths, "granted_tests": [], "reason": "直しに伴うので足してよい"}) + "\n")

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
        self.assertEqual(test_blk_fix.board_shas(self.board), before, "盤面を書かない")

    def test_pending_agreement_counts(self):
        self.ready(["docs/**"])
        self.agree(["stats.py"])
        code, out, err = self.precheck(load("fix2_ok"))
        self.assertEqual((code, json.loads(out)["rejects"]), (0, []), out + err)

    def test_scoped_peek_writes_nothing(self):
        self.ready(["stats.py"])
        before = test_blk_fix.board_shas(self.board)
        doc = json.loads(self.cfg.read_text(encoding="utf-8"))
        askplan.write_config(self.place, {**doc, "scope": "fixing"})
        code, out, err = self.precheck(load("fix2_ok"))
        self.assertEqual(code, 0, out + err)
        self.assertEqual(test_blk_fix.board_shas(self.board), before, "scope の登録も窓の照らしも書かない")

    def test_accept_settles_agreement_and_passes(self):
        self.ready(["docs/**"])
        self.agree(["stats.py"])
        code, out, err = run_script("accept", self.repo, {
            "INPUTS_REPLY": json.dumps(load("fix2_ok"), ensure_ascii=False), "INPUTS_BASE_REV": "", "INPUTS_ITERATION": "1",
            "ARTIFACTS_DIR": str(self.art), "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"]})
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ok"], out)
        (row,) = conflict.plan_asks(entry.open_board(self.board))
        self.assertEqual((row["id"], row["granted_paths"]), (1, ["stats.py"]))



class AskPrepCase(test_blk_fix.BoardCase):
    """支度の節 fix-prep: 入力 plan_session が在り承認済みの修正案の項目が在る時だけ、相談の控えを run ごとの置き場に書き、指示書に
    範囲の相談と事前の確かめの節を載せる"""

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
        cfg = askplan.place_of(self.board) / askplan.CONFIG
        self.assertIn(str(cfg), text)
        for w in ("askplan.py", "factchecks.py", "--why"):
            self.assertIn(w, text)
        doc = json.loads(cfg.read_text(encoding="utf-8"))
        self.assertEqual(doc["session_file"], str(adapter.session_path(self.repo, "plan")))
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
        self.assertNotIn("askplan.py", text)
        self.assertFalse((askplan.place_of(self.board) / askplan.CONFIG).exists())

    def item_no(self):
        return str(planmarks.approved_items(entry.open_board(self.board))[0]["item"])


if __name__ == "__main__":
    unittest.main()
