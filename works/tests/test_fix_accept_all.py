"""修正の受け付けが確かめを全部回して、誤りを 1 回の拒否に並べる（依頼 224）の検査。

- 盤面の乾いた照らし（Task 1）: DiskBoard.vet・entry.take と recount.accept_fix の commit=False が、受け付けと同じ検査を
  当てて盤面を書かず、拒否なら誤りを problems に並べる
- 拒否の見出しと id の表・並べ方（Task 2）: accept.CHECKS・note・render_rejects・rejected が、確かめごとに見出しを立てて
  文を並べ、rejects に 1 行ずつ id を付ける
- 申し出より後の確かめを全部回す（Task 3）: accept_fix が確かめを返さずに積み、写しの照らしも乾いた形で当てて 1 回の拒否に
  並べる
- 凍結と書き込みの出どころも積む（Task 4）: 凍ったテストのファイル・書き込みの出どころの誤りも積んで先へ進み、食い違いの申し出は
  積んだ誤りに依らず裁定へ渡す（run 222f の 3 回の拒否を 1 回に並べる）
- 待つ単位の控え（Task 5。226 との継ぎ目）: 案の直しを待つ単位が在る盤面で、控える（hold_fix）のは積んだ行が無く写しの照らしも
  乾いた形で通る返答だけ。誤りが在れば控えずに並べて拒む（控えた返答を hand_held が渡して拒まれ盤面が止まる前に役へ返す）
- 止まっても仕事を捨てない（依頼 242 Task 1。StopsKeepWorkCase）: 最後の回は拒否の行を単位に結んで止めて持ち越し、受けた単位で
  通す。赤の試験は import で届く単位に結び、戻す先は段の頭の木
盤面は test_blk_fix の BoardCase（本物の darkfactory の表・種の git）で作る。
"""
import hashlib
import json
import os
import pathlib
import sys
import unittest
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(TESTS))

import test_blk_fix  # noqa: E402  （core・blk-fix/lib を sys.path に足す）
import test_blk_fix_tdd  # noqa: E402
import entry  # noqa: E402
import linekit  # noqa: E402
import recount  # noqa: E402
import conflict  # noqa: E402
import tddloop  # noqa: E402
from test_blk_fix import CLAMP, FIXED, INVENTED, MEAN, extra_row, load  # noqa: E402
from test_blk_fix_conflict import CLAMP_FIX, MEAN_FIX, ReplanCase, conflict_on_mean, only_clamp_reply  # noqa: E402
import test_replan  # noqa: E402

FROZEN_LINE = "TDD の輪で凍ったテストのファイルを書き換えた: ['test_stats.py']（輪で直した単位のテストは変えない）"
WRITES_LINE = "書き込みの出どころの記録が無い変更: stats.py"


def accept_module(name):
    """blk-fix/scripts/accept.py を別名で読む（test_blk_fix.TestAccept.accept_module に任せる）"""
    return test_blk_fix.TestAccept.accept_module(None, name)


def sha(path) -> str:
    """ファイルの sha256"""
    return hashlib.sha256(pathlib.Path(path).read_bytes()).hexdigest()


def conflict_items(board) -> list:
    """盤面の今の周の食い違いの控え（conflict.FILE）の items"""
    return conflict.items(entry.open_board(board, allow_halted=True))


class DryTakeCase(test_blk_fix.BoardCase):
    def two_copy_errors(self):
        reply = test_blk_fix.load("fix2_ok")
        reply["changes"][0]["bypass_tried"] = "なし"       # 写しの照らしの誤り 1（mean の行）
        reply["changes"][1]["breaks"]["result"] = "なし"   # 写しの照らしの誤り 2（clamp の行）
        return reply

    def test_dry_take_lists_copy_errors_and_writes_nothing(self):
        self.fix_ready(); self.edit_tree(test_blk_fix.FIXED)
        before = test_blk_fix.board_shas(self.board)
        got = recount.accept_fix(self.two_copy_errors(), self.board, "", self.repo, commit=False)
        self.assertEqual((got["ok"], got["dry"], got["changes"]), (False, True, []), got)
        self.assertEqual(len(got["problems"]), 2, got)
        self.assertEqual(test_blk_fix.board_shas(self.board), before)
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_dry_take_of_clean_reply_leaves_board_waiting(self):
        # 乾いた照らしが通る返答は、後で commit しても同じく通る（当てる物が同じ）
        self.fix_ready(); self.edit_tree(test_blk_fix.FIXED)
        before = test_blk_fix.board_shas(self.board)
        got = recount.accept_fix(test_blk_fix.load("fix2_ok"), self.board, "", self.repo, commit=False)
        self.assertEqual((got["ok"], got["dry"]), (True, True), got)
        self.assertEqual(test_blk_fix.board_shas(self.board), before)
        self.assertIs(recount.accept_fix(test_blk_fix.load("fix2_ok"), self.board, "", self.repo)["ok"], True)
        self.assertNotEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_schema_errors_come_as_one_problem(self):
        # 型の誤りの拒否は problems を持たない（commit の道の形を全部の節で今のまま保つ）ので、乾いた道は文を 1 要素で返す。
        # 欠けた 2 つの鍵は、その 1 つの文に並ぶ
        self.fix_ready(); self.edit_tree(test_blk_fix.FIXED)
        reply = test_blk_fix.load("fix2_ok"); del reply["interactions"]; del reply["wrote_refs"]
        got = entry.take(self.board, "p3.fix", reply, self.repo, commit=False)
        self.assertIn("返答が型に合わない", got["reason"])
        self.assertEqual(got["problems"], [got["reason"]], got)
        self.assertIn("interactions", got["reason"])
        self.assertIn("wrote_refs", got["reason"])


class AllChecksCase(test_blk_fix.BoardCase):
    """受け付けの本体（accept_fix）を本物の盤面・作業ツリーの上で直に呼ぶ（最後の回の 2 つはスクリプトを子で起こす）"""

    acc = accept_module("blk_fix_accept_all")
    run_it = test_blk_fix.TestAccept.run_it
    scope_ready = test_blk_fix.TestAccept.scope_ready
    parked_units = test_blk_fix.ParkBoundBase.parked_units

    def env(self, iteration="1", pass_="first", state=""):
        """受け付けの入力の環境変数（実行器は無し）"""
        return mock.patch.dict(os.environ, {"INPUTS_ITERATION": iteration, "INPUTS_TDD_STATE": state, "INPUTS_PASS": pass_,
                                            "INPUTS_TDD_SUITE": ""})

    def accept_direct(self, reply, **env) -> dict:
        with self.env(**env):
            return self.acc.accept_fix(reply, self.board, "", self.repo)

    def test_duplicate_and_unopened_listed_together(self):
        self.fix_ready(); self.edit_tree(FIXED)
        reply = load("fix2_ok")
        reply["changes"] += [reply["changes"][0], extra_row(INVENTED)]
        got = self.accept_direct(reply)          # iteration 1・first・state 空・suite 空
        checks = [r["check"] for r in got["rejects"]]
        self.assertFalse(got["ok"])
        self.assertTrue({"duplicate", "not_opened"} <= set(checks), checks)
        self.assertIn(INVENTED, got["reason"])

    def test_scope_and_copy_listed_together(self):
        self.scope_ready(["docs/**"]); self.edit_tree(FIXED)
        reply = load("fix2_ok"); reply["changes"][1]["breaks"]["result"] = "なし"
        with mock.patch.object(self.acc.recount, "accept_fix", wraps=self.acc.recount.accept_fix) as rc:
            got = self.accept_direct(reply)
        self.assertEqual([r["check"] for r in got["rejects"]][:1], ["scope"])
        self.assertIn("copy", [r["check"] for r in got["rejects"]])
        rc.assert_called_once(); self.assertIs(rc.call_args.kwargs["commit"], False)
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_tests_and_gates_run_with_form_errors(self):
        # 決め 2: 重なりの誤りが在っても、選んだ試験と事後の関門の束を 1 回ずつ回す
        self.fix_ready(); self.edit_tree(FIXED)
        reply = load("fix2_ok")
        reply["changes"].append(reply["changes"][0])
        with mock.patch.object(self.acc, "check_tests", return_value=([], "")) as tests, \
                mock.patch.object(self.acc.fixgates, "problems", return_value=[]) as gates:
            got = self.accept_direct(reply)
        self.assertFalse(got["ok"])
        self.assertEqual((tests.call_count, gates.call_count), (1, 1))
        self.assertIn("duplicate", [r["check"] for r in got["rejects"]])

    def test_clean_reply_takes_once(self):
        self.fix_ready(); self.edit_tree(FIXED)
        with mock.patch.object(self.acc.recount, "accept_fix", wraps=self.acc.recount.accept_fix) as rc:
            got = self.accept_direct(load("fix2_ok"))
        self.assertIs(got["ok"], True, got)
        rc.assert_called_once(); self.assertIs(rc.call_args.kwargs["commit"], True)

    def test_last_round_parks_units_bound_by_two_checks(self):
        # 最後の回: mean の行は範囲の外の other.py（scope）、clamp の行は breaks.result「なし」（copy）。2 つの確かめの行が
        # それぞれ別の単位に結べるので、両方を止めて残りで通す（ParkBoundMultiLineCase と同じ盤面の形）
        self.scope_ready(["stats.py"]); self.edit_tree(FIXED)
        (self.repo / "other.py").write_text("x = 1\n", encoding="utf-8")
        reply = load("fix2_ok"); reply["changes"][0]["files"].append("other.py"); reply["changes"][1]["breaks"]["result"] = "なし"
        r = json.loads(self.run_it(reply, INPUTS_ITERATION="3")[1])
        self.assertTrue(r["ok"], r)
        self.assertEqual(sorted(self.parked_units()), sorted([MEAN, CLAMP]))

    def test_last_round_duplicate_and_copy_park_their_units(self):
        # 最後の回: 重なり（MEAN に結ぶ）と clamp の写しの誤り（CLAMP に結ぶ）→ 両方を止め、空の changes で通る
        self.fix_ready(); self.edit_tree(FIXED)
        reply = load("fix2_ok")
        reply["changes"][1]["breaks"]["result"] = "なし"
        reply["changes"].append(reply["changes"][0])
        code, out, err = self.run_it(reply, INPUTS_ITERATION="3")
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertEqual((r["ok"], r["done"], r["changes"]), (True, True, []), r)
        self.assertEqual(sorted(self.parked_units()), sorted([MEAN, CLAMP]))


class SeamCase(test_blk_fix.BoardCase):
    """凍結と書き込みの出どころも積み、食い違いの申し出は積んだ誤りに依らず裁定へ渡す（Task 4。run 222f の型）"""

    acc = AllChecksCase.acc
    env = AllChecksCase.env
    accept_direct = AllChecksCase.accept_direct
    tdd_frozen = test_blk_fix.TestAccept.tdd_frozen
    scope_ready = test_blk_fix.TestAccept.scope_ready

    def test_222f_three_classes_in_one_rejection(self):
        # run 222f の 3 回の拒否（凍ったテストのファイル・修正案の範囲・写しの照らし）を、1 回の拒否に並べる
        state = self.tdd_frozen()                                            # test_stats.py を凍らせ、FIXED を当てた木
        (self.repo / "test_stats.py").write_text((self.repo / "test_stats.py").read_text(encoding="utf-8") + "\n# 凍った後の書き換え\n",
                                                 encoding="utf-8")         # 1 回目の型
        (self.repo / "other.py").write_text("x = 1\n", encoding="utf-8")     # 2 回目の型（allowed_paths は stats.py だけ）
        reply = load("fix2_ok"); reply["changes"][0]["files"].append("other.py")
        reply["changes"][1]["breaks"]["result"] = "なし"                     # 3 回目の型（写しの fix_covers_open_units）
        before = sha(self.board / "state.json")
        with mock.patch.object(self.acc, "check_tests", return_value=([], "")), self.env(state=state):
            got = self.acc.accept_fix(reply, self.board, "", self.repo)
        checks = [r["check"] for r in got["rejects"]]
        self.assertFalse(got["ok"])
        self.assertEqual([c for c in self.acc.CHECKS if c in {"frozen", "scope", "copy"}],
                         [c for c in dict.fromkeys(checks) if c in {"frozen", "scope", "copy"}], checks)
        self.assertTrue(any("test_stats.py" in r["text"] for r in got["rejects"] if r["check"] == "frozen"))
        self.assertTrue(any("other.py" in r["text"] for r in got["rejects"] if r["check"] == "scope"))
        self.assertTrue(any(r["text"].startswith(CLAMP[:60]) for r in got["rejects"] if r["check"] == "copy"))
        self.assertEqual(sha(self.board / "state.json"), before)

    def first_pass_conflict(self) -> dict:
        """凍結の誤りが在る 1 回目に、名指しの在る食い違いの申し出（mean）を出す"""
        with mock.patch.object(self.acc, "check_frozen", return_value=[FROZEN_LINE]), self.env():
            return self.acc.accept_fix(only_clamp_reply([conflict_on_mean()]), self.board, "", self.repo)

    def test_first_pass_conflict_reaches_ruling_with_frozen_error(self):
        self.fix_ready(); self.edit_tree(FIXED)
        got = self.first_pass_conflict()
        self.assertEqual((got["ok"], got.get("parked")), (True, True), got)
        self.assertEqual([(i["unit_key"], i["status"]) for i in conflict_items(self.board)], [(MEAN, "parked")])

    def test_same_conflict_twice_parks_once(self):
        self.fix_ready(); self.edit_tree(FIXED)
        for _ in range(2):
            got = self.first_pass_conflict()
            self.assertEqual((got["ok"], got.get("parked")), (True, True), got)
        self.assertEqual(len(conflict_items(self.board)), 1)

    def test_ruled_pass_conflict_parked_despite_writes_error(self):
        # ruled で書き込みの出どころの誤り（check_writes を mock で 1 行に）と新しい申し出 → 拒否に writes が載り、申し出は
        # ask_human の裁定つきで積まれたまま残る（拒否で巻き戻さない。224e の R2）。同じ返答をもう一度出しても行は 1 つ
        self.fix_ready(); self.edit_tree(FIXED)

        def wrote(reply, *a, **k):
            return {"reply": {f: v for f, v in reply.items() if f != "bash_writes"}, "problems": [WRITES_LINE], "note": "",
                    "left": []}
        for _ in range(2):
            with mock.patch.object(self.acc, "check_writes", side_effect=wrote):
                got = self.accept_direct(only_clamp_reply([conflict_on_mean()]), pass_="ruled")
            self.assertFalse(got["ok"], got)
            self.assertIn(("writes", WRITES_LINE), [(r["check"], r["text"]) for r in got["rejects"]])
            self.assertEqual([(i["unit_key"], i["ruling"]["decision"]) for i in conflict_items(self.board)],
                             [(MEAN, conflict.ASK)])


class RenderCase(unittest.TestCase):
    acc = accept_module("blk_fix_accept_render")

    def test_groups_follow_table_order(self):
        found = []
        self.acc.note(found, "copy", ["c1"]); self.acc.note(found, "frozen", ["f1", ""]); self.acc.note(found, "copy", ["c2", "c1"])
        text = self.acc.render_rejects(found)
        self.assertTrue(text.startswith(self.acc.REJECT_HEAD))
        self.assertLess(text.index(self.acc.CHECKS["frozen"]), text.index(self.acc.CHECKS["copy"]))
        self.assertIn("（確かめ copy・2 件）", text)
        self.assertEqual([x for x in text.splitlines() if x.startswith("  - ")], ["  - f1", "  - c1", "  - c2"])

    def test_rejected_carries_one_check_per_line(self):
        found = []
        self.acc.note(found, "scope", ["s1"]); self.acc.note(found, "frozen", ["f1"])
        out = self.acc.rejected(found)
        self.assertEqual((out["ok"], out["changes"]), (False, []))
        self.assertEqual([r["check"] for r in out["rejects"]], ["frozen", "scope"])
        self.assertEqual([r["text"] for r in out["rejects"]], ["f1", "s1"])
        self.assertEqual(len(out["rejects"]), out["reason"].count("\n  - "))

    def test_multiline_text_is_indented(self):
        found = []
        self.acc.note(found, "copy", ["返答が型に合わない:\n  - a"])
        self.assertIn("  - 返答が型に合わない:\n      - a", self.acc.render_rejects(found))

    def test_unknown_check_is_value_error(self):
        with self.assertRaises(ValueError):
            self.acc.note([], "nope", ["x"])

    def test_table_values_are_the_ruled_ones(self):
        # 236 が role-rejects の行の確かめの id に引く表。id・並び（受け付けが回す順）と、値が見出しの文字列だけであることを固める
        # （最後の回はどの確かめの行も同じ決まりで単位に結ぶので、止めてよいかの列は無い。依頼 242）
        self.assertEqual(list(self.acc.CHECKS), ["consult", "frozen", "writes", "conflict", "pack", "duplicate", "not_opened", "accepted",
                                                 "excused", "scope", "tests", "gates", "copy"])
        self.assertTrue(all(isinstance(v, str) and v for v in self.acc.CHECKS.values()), self.acc.CHECKS)

    def test_yaml_names_rejects_on_both_accept_nodes(self):
        nodes = test_blk_fix.block()["nodes"]
        for nid in ("fix-accept", "fix-ruled-accept"):
            with self.subTest(nid=nid):
                fmt = test_blk_fix.find_node(nodes, nid)["output_format"]
                self.assertEqual(fmt["properties"].get("rejects"), {"type": "array"})
                self.assertNotIn("rejects", fmt["required"])


BOUNDS = "def width(lo, hi):\n    return hi - lo\n"
TEST_BOUNDS = ("import unittest\n\nfrom bounds import width\n\n\nclass TestBounds(unittest.TestCase):\n"
               "    def test_width(self):\n        self.assertEqual(width(2, 5), 3)\n")
DIRECT_WHY = "文書の直しと同じで、先にテストを書けない単位"


def parking():
    """blk-fix/lib/parking（Task 1 の前は無い。呼ぶ試験だけが ImportError で落ちる）"""
    import parking as mod
    return mod


def bounds_seed():
    """linekit.seed_repo を包み、種の commit に bounds.py と test_bounds.py（修正前の版で緑）を足す"""
    real = linekit.seed_repo

    def seed(into, **kw):
        repo = real(into, **kw)
        (repo / "bounds.py").write_text(BOUNDS, encoding="utf-8")
        (repo / "test_bounds.py").write_text(TEST_BOUNDS, encoding="utf-8")
        linekit.git(repo, "add", "-A")
        linekit.git(repo, "commit", "-q", "--amend", "--no-edit")
        return repo
    return mock.patch.object(linekit, "seed_repo", side_effect=seed)


class StopsKeepWorkCase(ReplanCase):
    """run 195f の型: 修正役の直しが既存の試験を赤にし、3 回とも同じ返答を出す。最後の回は赤の試験を import で届く単位に結び、
    その単位だけを止めて持ち越し、受けた単位で通す。盤面は止まらない（依頼 242 Task 1。ReplanCase は BoardCase の子で、2 回目の
    修正の段の盤面を作る手も持つ）"""

    run_it = test_blk_fix.TestAccept.run_it
    parked_units = test_blk_fix.ParkBoundBase.parked_units
    changed = test_blk_fix.TestGiveUpOnBoard.changed
    fix_ready_with_pack_copy = test_blk_fix.TestAccept.fix_ready_with_pack_copy
    play_role = test_replan.TripCase.play_role
    trip = test_replan.TripCase.trip
    approve = test_replan.TripCase.approve

    def start_loop(self) -> str:
        """修正の節が待つ盤面で TDD の輪を起こす（実行器は test_blk_fix_tdd.SUITE）。返りは輪の状態のファイル"""
        suite = self.tmp / "suite.py"
        suite.write_text(test_blk_fix_tdd.SUITE, encoding="utf-8")
        start = tddloop.start(self.board, self.repo, str(suite), test_blk_fix_tdd.OPEN)
        self.assertTrue(start["go"], start)
        return start["state_file"]

    def step(self, state, reply):
        got = tddloop.step(state, reply, self.repo)
        self.assertTrue(got["ok"], got)
        return got

    def redden_bounds(self):
        (self.repo / "bounds.py").write_text(BOUNDS.replace("hi - lo", "lo - hi"), encoding="utf-8")

    def reddening_fixer(self, faces: bool = False) -> tuple:
        """(輪の状態のファイル, 返答)。輪は MEAN と CLAMP を direct に振る。言うことを聞かない修正役は mean の 1 か所だけを直し、
        bounds.py を書き換えて既存の test_width を赤にし、CLAMP の行の files を bounds.py にした返答を 3 回とも出す。
        faces が真なら事前審査は穴を 1 つ持つ見本（plan_review_regression。関所に continue で答えた盤面）"""
        with bounds_seed():
            if faces:
                self.fix_ready(review=linekit.reply("plan_review_regression"), answer=("continue", "clamp の上限は hi でよい"))
            else:
                self.fix_ready()
        state = self.start_loop()
        self.step(state, {"phase": "route", "units": [{"unit_key": MEAN, "route": "direct", "why": DIRECT_WHY},
                                                      {"unit_key": CLAMP, "route": "direct", "why": DIRECT_WHY}]})
        self.edit_tree(MEAN_FIX)
        self.redden_bounds()
        reply = load("fix2_ok")
        reply["changes"][1]["files"] = ["bounds.py"]
        return state, reply

    def trace_rows(self, op):
        rows = [json.loads(x) for x in (self.board / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        return [r for r in rows if r.get("op") == op]

    def unchanged(self, name) -> bool:
        """作業ツリーの name が修正前の版（HEAD）と同じ"""
        return linekit.git(self.repo, "status", "--porcelain", "--", name) == ""

    def test_reddened_existing_test_parks_its_unit_and_keeps_the_rest(self):
        state, reply = self.reddening_fixer()
        for it in ("1", "2"):
            r = json.loads(self.run_it(reply, INPUTS_ITERATION=it, INPUTS_TDD_STATE=state)[1])
            self.assertEqual((r["ok"], r["done"]), (False, False), r)
            self.assertIn("test_bounds.py", r["reason"], "赤の行はテストのファイルのパスを名指す")
        r = json.loads(self.run_it(reply, INPUTS_ITERATION="3", INPUTS_TDD_STATE=state)[1])
        self.assertEqual((r["ok"], r["done"]), (True, True), r)
        self.assertEqual([c["unit_key"] for c in r["changes"]], [MEAN], "受けた単位は残る")
        self.assertEqual(self.parked_units(), [CLAMP], "赤の試験 test_bounds.py は bounds.py を触った CLAMP にだけ届く")
        self.assertEqual((self.repo / "bounds.py").read_text(encoding="utf-8"), BOUNDS, "止めた単位は段の頭の木に戻る")
        self.assertIn("sum(xs) / len(xs)", (self.repo / "stats.py").read_text(encoding="utf-8"))
        patch = next(self.board.rglob("fix-parked-1.patch")).read_text(encoding="utf-8")
        self.assertIn("return lo - hi", patch, "止めた直しは控えに残る")
        b = entry.open_board(self.board)
        self.assertFalse(b.state.get("stop") or b.state.get("halted"), "盤面は止まらない")
        self.assertIn(CLAMP, conflict.fix_duty(b)[1], "止めた単位は義務の外（ask_human）")
        self.assertIs(json.loads(self.changed(r)[1])["ok"], True)

    def test_bad_conflict_parks_only_the_offering_unit_on_last_pass(self):
        # run 195g の型: MEAN だけが盤面にも足跡にも無い行を名指して崩れた申し出を出し続け、CLAMP の直しは正しい。
        # 最後の回は申し出た MEAN だけを止め（how は declared で unbound に載らない）、CLAMP は受ける
        self.fix_ready()
        self.edit_tree(CLAMP_FIX)
        reply = only_clamp_reply([conflict_on_mean("ghost/brief.md:1", "ghost/other.md:2")])
        for it in ("1", "2"):
            r = json.loads(self.run_it(reply, INPUTS_ITERATION=it)[1])
            self.assertFalse(r["ok"], r)
            self.assertIn("ghost/brief.md:1", r["reason"])
        r = json.loads(self.run_it(reply, INPUTS_ITERATION="3")[1])
        self.assertEqual((r["ok"], r["done"]), (True, True), r)
        self.assertEqual([c["unit_key"] for c in r["changes"]], [CLAMP], "申し出ていない CLAMP は受ける")
        self.assertEqual(self.parked_units(), [MEAN], "止めるのは申し出た MEAN だけ")
        row = self.trace_rows("fix_bound_parked")[0]
        self.assertEqual(row["unbound"], {}, "申し出の行は単位に結べている")
        self.assertEqual(set(row["how"].values()), {"declared"}, row)

    def test_shared_test_file_parks_both_and_leaves_no_red(self):
        # Review Focus 1: 輪で緑にした MEAN の受け入れのテスト test_stats.py を、bounds.py を赤にした CLAMP の行も名指す。
        # 共有の閉包で両方を止め、3 つのファイルを段の頭の木（ここでは修正前の版）に戻す（一方だけを戻して赤を残さない）
        with bounds_seed():
            self.fix_ready()
        state = self.start_loop()
        self.step(state, {"phase": "route", "units": [{"unit_key": MEAN, "route": "tdd"},
                                                      {"unit_key": CLAMP, "route": "direct", "why": DIRECT_WHY}]})
        path = self.repo / "test_stats.py"
        path.write_text(path.read_text(encoding="utf-8").replace("\n\nif __name__", test_blk_fix_tdd.NEW_TEST + "\n\nif __name__"),
                        encoding="utf-8")
        self.step(state, {"phase": "test", "unit_key": MEAN, "test_files": ["test_stats.py"],
                          "tests": ["test_stats.py::TestStats::test_mean_of_two"]})
        self.edit_tree(MEAN_FIX)
        got = self.step(state, {"phase": "fix", "unit_key": MEAN, "files": ["stats.py"], "what": "分母を len(xs) にした"})
        self.assertTrue(got["done"], got)
        self.edit_tree(CLAMP_FIX)
        path.write_text(path.read_text(encoding="utf-8") + "\n# 凍った後の書き換え\n", encoding="utf-8")
        self.redden_bounds()
        reply = load("fix2_ok")
        reply["changes"][1]["files"] = ["stats.py", "test_stats.py", "bounds.py"]
        rows = []
        for it in ("1", "3"):
            r = json.loads(self.run_it(reply, INPUTS_ITERATION=it, INPUTS_TDD_STATE=state)[1])
            rows.append({x["check"] for x in r.get("rejects") or []})
        self.assertTrue({"frozen", "tests"} <= rows[0], rows)
        self.assertEqual((r["ok"], r["done"], r["changes"]), (True, True, []), r)
        self.assertEqual(sorted(self.parked_units()), sorted([MEAN, CLAMP]))
        for name in ("test_stats.py", "stats.py", "bounds.py"):
            self.assertTrue(self.unchanged(name), name)

    def second_pass(self) -> tuple:
        """(輪の状態のファイル, 返答)。1 回目の段で CLAMP の返答を受けて控え、MEAN の案を直して戻った 2 回目の修正の段
        （include refitting）。2 回目の修正役は MEAN を直しつつ bounds.py を赤にし、MEAN の行は stats.py と bounds.py を名指す"""
        with bounds_seed():
            self.replanned()
        self.assertTrue(self.accept_script(only_clamp_reply(), pass_="ruled")["ok"])
        import replan
        self.assertTrue(replan.material(entry.open_board(self.board))["go"])
        self.approve(test_replan.red_kind_fixed())
        test_replan.refit_ignored_before(self.board, self.repo)
        self.assertEqual(conflict.fix_duty(entry.open_board(self.board))[0], {MEAN})
        state = self.start_loop()
        self.edit_tree(MEAN_FIX)
        self.redden_bounds()
        reply = test_replan.only_mean_reply()
        reply["changes"][0]["files"] = ["stats.py", "bounds.py"]
        return state, reply

    def test_second_pass_park_keeps_first_pass_work(self):
        # Review Focus 2: 1 回目の段で CLAMP の返答を受けて控え、MEAN の案を直して戻った 2 回目の修正の段（include refitting）。
        # 2 回目の修正役は MEAN を直しつつ bounds.py を赤にし、MEAN の行は CLAMP の 1 回目の直しと同じ stats.py を名指す。
        # 最後の回は MEAN だけを止め、段の頭の木（1 回目の直しを含む）に戻すので CLAMP の直しは残り、patch は 2 回目の変更だけ
        state, reply = self.second_pass()
        r = self.accept_script(reply, iteration="3", include=test_replan.REFIT, tdd_state=state)
        self.assertEqual((r["ok"], r["done"]), (True, True), r)
        self.assertEqual(self.parked_units(), [MEAN])
        text = (self.repo / "stats.py").read_text(encoding="utf-8")
        self.assertIn("return hi", text, "1 回目に受けた CLAMP の直しは段の頭の木に在るので残る")
        self.assertNotIn("sum(xs) / len(xs)", text, "止めた MEAN の 2 回目の直しは戻る")
        self.assertEqual((self.repo / "bounds.py").read_text(encoding="utf-8"), BOUNDS)
        patch = next(self.board.rglob("fix-parked-1.patch")).read_text(encoding="utf-8")
        self.assertIn("sum(xs) / len(xs)", patch)
        self.assertNotIn("+        return hi", patch, "1 回目の直しは控えに入らない")

    def test_pack_row_parks_all_and_never_touches_archon(self):
        # Review Focus 3: .archon/ の下を変えた最後の回。pack の行は誰にも結べないので義務の全部を止め、.archon/ の下は戻さない
        copy = self.fix_ready_with_pack_copy()
        changed = "def mean(xs):\n    return sum(xs) / len(xs)\n"
        copy.write_text(changed, encoding="utf-8")
        r = json.loads(self.run_it(load("fix2_ok"), INPUTS_ITERATION="3")[1])
        self.assertEqual((r["ok"], r["done"], r["changes"]), (True, True, []), r)
        self.assertEqual(sorted(self.parked_units()), sorted([MEAN, CLAMP]))
        rows = self.trace_rows("fix_bound_parked")
        self.assertTrue(any(t.startswith("修正役は .archon/ の下を変えてはいけない") for row in rows for t in row.get("unbound") or {}),
                        rows)
        self.assertEqual(copy.read_text(encoding="utf-8"), changed, ".archon/ の下は戻さない")

    def test_red_test_binds_by_import_closure(self):
        with bounds_seed():
            repo = linekit.seed_repo(self.tmp / "repo")
        mod = parking()
        feet = {MEAN: {"stats.py"}, CLAMP: {"bounds.py"}}
        reached = {k: mod.reach(repo, "HEAD", f, self.tmp / "impact") for k, f in feet.items()}
        self.assertIn("test_bounds.py", reached[CLAMP])
        keys = {MEAN, CLAMP}
        self.assertEqual(mod.bind("赤（ファイル test_bounds.py）: ['test_bounds.TestBounds::test_width']", keys, feet, reached),
                         {CLAMP})
        self.assertEqual(mod.bind("赤（ファイル test_stats.py）: ['test_stats.TestStats::test_x']", keys, feet, reached), {MEAN})
        self.assertEqual(mod.bind(f"{CLAMP[:60]}: 閉鎖の実証で赤を一度も見ていない", keys, feet, reached), {CLAMP})

    def test_unbound_row_parks_every_owed_unit_and_says_why(self):
        mod = parking()
        feet = {MEAN: {"stats.py"}, CLAMP: {"bounds.py"}}
        reached = {MEAN: {"test_stats.py"}, CLAMP: {"test_bounds.py"}}
        text = "誰も名指さない文"
        got = mod.settle([text], keys={MEAN, CLAMP}, feet=feet, reached=reached, owed={MEAN, CLAMP}, out_of_duty=set(),
                         changed=set())
        self.assertEqual(set(got.park), {MEAN, CLAMP})
        self.assertEqual(got.unbound, {text: mod.unbound_why(text)})
        got = mod.settle([f"{CLAMP[:60]}: 直さない単位の行"], keys={MEAN, CLAMP}, feet=feet, reached=reached, owed={MEAN},
                         out_of_duty={CLAMP}, changed=set())
        self.assertEqual((got.park, got.absorbed), ({}, [f"{CLAMP[:60]}: 直さない単位の行"]))

    def test_closure_does_not_walk_through_out_of_duty_units(self):
        """閉包は義務の外の単位を通って広がらない: X={a.py}・P={a.py, b.py}（義務の外）・Y={b.py} で行が X を名指せば
        止めるのは X だけ。P は戻すパスに X と共にする a.py だけを足し、Y の b.py は戻さない"""
        mod = parking()
        feet = {"X": {"a.py"}, "P": {"a.py", "b.py"}, "Y": {"b.py"}}
        got = mod.settle(["X: 赤"], keys=set(feet), feet=feet, reached={}, owed={"X", "Y"}, out_of_duty={"P"},
                         changed=set())
        self.assertEqual(set(got.park), {"X"})
        self.assertEqual(got.files, {"a.py"})

    def test_footprints_come_from_this_stage_loop_only(self):
        """足跡は今の段の輪（INPUTS_TDD_STATE）だけから: 盤面の根に前の輪の状態が在っても、その単位の files は足跡に入らない"""
        state, reply = self.reddening_fixer()
        old = self.board / "tdd-0" / "state.json"
        old.parent.mkdir()
        doc = json.loads(pathlib.Path(state).read_text(encoding="utf-8"))
        doc["units"][CLAMP]["files"] = ["stats.py"]
        old.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        acc = accept_module("blk_fix_accept_stage_feet")
        with mock.patch.object(acc.parking, "footprint", wraps=acc.parking.footprint) as feet, \
                mock.patch.dict(os.environ, {"INPUTS_TDD_STATE": state}):
            acc.last_settle(["x"], reply, self.board, "", self.repo, state, set())
        self.assertEqual([str(p) for p in feet.call_args.args[1]], [state])

    def test_reply_level_rows_hand_the_machine_empty_reply(self):
        """run 222f の型: 修正案の事前審査への応答（plan_faces）を 3 回とも欠いた返答。最後の回は義務の全部を止め、
        機械の空の返答を盤面に渡す（trace に空の返答の印）"""
        accept_mod = accept_module("blk_fix_accept_stops")
        state, reply = self.reddening_fixer(faces=True)
        reply["plan_faces"] = []
        r = json.loads(self.run_it(reply, INPUTS_ITERATION="3", INPUTS_TDD_STATE=state)[1])
        self.assertEqual((r["ok"], r["done"], r["changes"]), (True, True, []), r)
        self.assertEqual(sorted(self.parked_units()), sorted([MEAN, CLAMP]))
        b = entry.open_board(self.board)
        self.assertEqual(b.node_state("p3.fix"), "done")
        out = json.loads((self.board / b.state["outputs"]["p3.fix"]["file"]).read_text(encoding="utf-8"))
        self.assertTrue(out["plan_faces"] and all(f["handled"] == "declared" for f in out["plan_faces"]))
        self.assertIn(accept_mod.EMPTY_HANDED, out["fix_closure"]["reason"])
        ops = [json.loads(x) for x in (self.board / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        self.assertTrue(any(o.get("op") == entry.EMPTY_FIX_OP and o.get("by") == entry.EMPTY_FIX_BY for o in ops))
        self.assertIs(json.loads(self.changed(r)[1])["ok"], True, "空の申告は義務の外の単位だけの正しい返答")

    def test_second_pass_reply_level_rows_keep_first_pass_rows(self):
        """2 回目の修正の段（ruled）で返答の欄の誤りを 3 回とも出す。最後の回は義務の MEAN を止め、機械の空の返答に 1 回目に
        受けた CLAMP の行を合わせて盤面に渡す（写しの fix_covers_open_units は 1 回目の単位を引かない）。CLAMP の行が残るので
        空の返答の印を付けない"""
        state, reply = self.second_pass()
        reply["changes"][0]["files"] = ["stats.py"]
        reply["fix_closure"] = {"status": "nonsense"}
        r = self.accept_script(reply, iteration="3", pass_="ruled", include=test_replan.REFIT, tdd_state=state)
        self.assertEqual((r["ok"], r["done"]), (True, True), r)
        self.assertEqual(self.parked_units(), [MEAN])
        b = entry.open_board(self.board)
        self.assertEqual(b.node_state("p3.fix"), "done")
        out = json.loads((self.board / b.state["outputs"]["p3.fix"]["file"]).read_text(encoding="utf-8"))
        self.assertEqual([c["unit_key"] for c in out["changes"]], [CLAMP], "1 回目に受けた単位の行は残る")
        self.assertFalse(self.trace_rows(entry.EMPTY_FIX_OP), "役の直し（1 回目）を含む返答は空の返答と数えない")
        self.assertIn("return hi", (self.repo / "stats.py").read_text(encoding="utf-8"))

    def test_copy_rows_on_out_of_duty_units_park_the_owed_rest(self):
        """最後の回の写しの拒否が義務の外の単位（1 回目に受けた CLAMP）にだけ結んだ: 止める単位が無いまま空の返答へ落ちず、
        義務の残り（MEAN）を止める（受けた MEAN の直しを黙って捨てない）"""
        state, reply = self.second_pass()
        reply["changes"][0]["files"] = ["stats.py"]
        (self.repo / "bounds.py").write_text(BOUNDS, encoding="utf-8")
        acc = accept_module("blk_fix_accept_out_only")
        real, calls = acc.recount.accept_fix, []

        def copy(*a, **kw):
            calls.append(kw.get("commit"))
            if len(calls) == 1:
                return {"ok": False, "reason": "x", "problems": [f"{CLAMP[:60]}: 写しが 1 回目の単位の行を拒んだ"]}
            return real(*a, **kw)
        env = {"INPUTS_ITERATION": "3", "INPUTS_TDD_STATE": state, "INPUTS_PASS": "ruled", "INPUTS_TDD_SUITE": "",
               **test_replan.in_include(test_replan.REFIT, "fix-loop.fix-accept")}
        with mock.patch.dict(os.environ, env), mock.patch.object(acc.recount, "accept_fix", side_effect=copy), \
                mock.patch.object(acc, "check_plan_scope", return_value=([], None)):
            r = acc.accept_fix(reply, self.board, "", self.repo)
        self.assertIs(r["ok"], True, r)
        self.assertEqual(self.parked_units(), [MEAN], "義務の残りを止める")

    @staticmethod
    def edge_modules() -> tuple:
        """(line_edge, report)。line_edge は darkfactory/lib を sys.path に足して読む（test_edge.py と同じ手）"""
        lib = str(TESTS.parent / "darkfactory" / "lib")
        if lib not in sys.path:
            sys.path.insert(0, lib)
        import line_edge
        import report
        return line_edge, report

    def test_line_continues_with_kept_and_parked_named(self):
        state, reply = self.reddening_fixer()
        for it in ("1", "2", "3"):
            self.run_it(reply, INPUTS_ITERATION=it, INPUTS_TDD_STATE=state)
        line_edge, report = self.edge_modules()
        review = line_edge.edge(self.board, "review", self.repo, run_id="run-12", adapter_mode="optional", final_gate="when_needed")
        self.assertEqual((review["stop"], review["go"]), (False, True), "差分の審査へ進む")
        b = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(report.fix_split(b)["kept"], [MEAN])
        self.assertEqual([p["unit_key"] for p in report.fix_split(b)["parked"]], [CLAMP])
        self.assertEqual(report.decide_outcome(b, {"accepted": True, "round_closed": True}), "needs_human")
        head = report.head3(b, "needs_human", next_items=report.next_request(b))
        self.assertIn("1 単位", head[0]); self.assertIn("止めて持ち越した", head[0])

    def test_parked_patch_reaches_next_request_and_gate(self):
        state, reply = self.reddening_fixer()
        for it in ("1", "2", "3"):
            self.run_it(reply, INPUTS_ITERATION=it, INPUTS_TDD_STATE=state)
        line_edge, report = self.edge_modules()
        b = entry.open_board(self.board, allow_halted=True)
        patch = report.fix_split(b)["parked"][0]["patch"]
        items = [i for i in report.next_request(b) if i["where"] == CLAMP]
        self.assertTrue(items and patch in items[0]["text"], items)
        gate = line_edge.final_edge(b, self.repo, run_id="run-12", mode="when_needed", tests={"ok": True, "green": True})
        self.assertTrue(gate["ask"])
        self.assertIn("止めて持ち越した", gate["gate_text"].splitlines()[0]); self.assertIn(patch, gate["gate_text"])


class HoldCase(ReplanCase):
    """案の直しを待つ単位（mean を fix_plan_item に裁いた盤面）が在る間の受け付け（2 回目の受け付け ruled）"""

    acc = AllChecksCase.acc
    env = AllChecksCase.env

    def accept_held(self, reply):
        """受け付けの本体を ruled で直に呼ぶ。返り (結果, hold_fix の mock, recount.accept_fix の mock)"""
        self.replanned()
        self.assertTrue(conflict.waiting(entry.open_board(self.board)))
        with mock.patch.object(self.acc, "hold_fix", wraps=self.acc.hold_fix) as hold, \
                mock.patch.object(self.acc.recount, "accept_fix", wraps=self.acc.recount.accept_fix) as rc, \
                self.env(pass_="ruled"):
            got = self.acc.accept_fix(reply, self.board, "", self.repo)
        return got, hold, rc

    def assert_not_held(self, got, hold, rc):
        self.assertIs(got["ok"], False, got)
        hold.assert_not_called()
        self.assertFalse(entry.open_board(self.board).work(conflict.HELD_REPLY).exists())
        rc.assert_called_once(); self.assertIs(rc.call_args.kwargs["commit"], False)
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

    def test_waiting_board_rejects_instead_of_holding(self):
        reply = only_clamp_reply()
        reply["changes"].append(reply["changes"][0])          # 重なりの誤り
        got, hold, rc = self.accept_held(reply)
        self.assert_not_held(got, hold, rc)
        self.assertIn("duplicate", [r["check"] for r in got["rejects"]])

    def test_waiting_board_rejects_copy_error_before_holding(self):
        # 積んだ行が無くても、写しの照らしの誤りが在れば控えない（乾いた照らしで役へ返す。裁定 F6）
        reply = only_clamp_reply()
        reply["changes"][0]["breaks"]["result"] = "なし"
        got, hold, rc = self.accept_held(reply)
        self.assert_not_held(got, hold, rc)
        self.assertEqual({r["check"] for r in got["rejects"]}, {"copy"}, got["rejects"])

    def test_waiting_board_holds_clean_reply(self):
        got, hold, rc = self.accept_held(only_clamp_reply())
        self.assertEqual((got["ok"], got.get("parked"), got["done"]), (True, True, True), got)
        hold.assert_called_once()
        rc.assert_called_once(); self.assertIs(rc.call_args.kwargs["commit"], False)   # 乾いた照らしだけで、盤面には渡さない
        b = entry.open_board(self.board)
        self.assertTrue(b.work(conflict.HELD_REPLY).is_file())
        self.assertNotIn("p3.fix", b.state["outputs"])


if __name__ == "__main__":
    unittest.main()
