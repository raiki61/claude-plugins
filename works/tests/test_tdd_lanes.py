"""TDD の輪の単位を、枝ごとの単位の worktree で並べる（blk-fix の tddlanes。設計 docs/plans/2026-10-06-tdd-parallel.md・
docs/plans/2026-10-07-overlap-lanes.md・docs/plans/2026-10-07-lane-nodes.md）の検査。

- 分け方: 形 g3 の輪で、振り分けの後に範囲（tddlanes.ranges。試験では差し替え）の引ける tdd の枝（修正案の項目を共にする単位の組。
  tddlanes.items_of も差し替え）が 2 本以上なら、枝の worktree を run ごとの置き場の下に切って段 lanes へ進む（輪 tdd-loop はここで
  抜ける）。範囲が重なっても並べる。2 本未満・形 af・範囲の引けない単位は今どおり順。枝は MAX_LANES 本まで（後ろの枝の単位は順）
- 枝の輪を起こすか（tdd-fork。tddlanes.fork）: 段 lanes の状態でだけ go と lane_<n>
- 枝の支度（tdd-lane-prep-<n>。tddlanes.lane_prep）: 単位の決まりのファイル（全文・単位の間は同じ）と回ごとの指示書、包みが読む
  2 つの印（単位の鍵・単位の worktree）
- 枝の確かめ（tdd-lane-step-<n>。tddlanes.lane_step）: 単位の worktree で tddloop の段の確かめをそのまま回す（赤・緑・凍結は機械）。
  書き込みの出どころは run の作業ツリーの記録と突き合わせる。枝の中の単位は順に進み、単位ごとの頭の木を控えに残す。done は枝の全部
- 重なり: 2 本の枝が同じファイルの別の行を変える → 両方当たる（shared）。同じ試験のファイルの末尾に足す → 先の枝の行の後に後の
  枝の行を置いて当たる（union）。字では合うが合わせた木で赤 → 後の枝だけ戻す（semantic）
- 締める（tdd-join。tddlanes.join）: 緑まで済んだ単位の差分を当て、当てた後の木で緑をもう 1 度確かめる。済まなかった単位・当たら
  ない単位・当てた後に赤い単位は、順の単位として最初の段から回し直す（輪 tdd-rest）。direct への渡しと食い違いの申し出は今どおり
- 節の script（tdd_fork・tdd_lane_prep・tdd_lane_step・tdd_join）を子で起こして、並べの周を 1 回通す
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-fix"
CORE = ROOT / ".shared" / "core"
TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(BLK / "lib"))
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

from gitkit import git  # noqa: E402
import adapter  # noqa: E402
import prepkit  # noqa: E402
import tddlanes  # noqa: E402
import tddloop  # noqa: E402
import unittrees  # noqa: E402
import writes  # noqa: E402
from test_blk_fix_tdd import SUITE, run_script  # noqa: E402

UA = "a.py double: x + x + 1 を返す"
UB = "b.py triple: x * 3 + 1 を返す"
UD = "d.py quad: x * 4 + 1 を返す"
SEED = {
    "a.py": "def double(x):\n    return x + x + 1\n",
    "b.py": "from a import double\n\n\ndef triple(x):\n    return x * 3 + 1\n",
    "c.py": "SHARED = 1\n",
    "d.py": "def quad(x):\n    return x * 4 + 1\n",
    "e.py": "".join(f"E{i} = {i}\n" for i in range(1, 9)),
    "test_d.py": "import unittest\nfrom d import quad\n\n\nclass TestD(unittest.TestCase):\n    def test_zero(self):\n"
                 "        self.assertIsInstance(quad(1), int)\n",
    "test_ab.py": "import unittest\nfrom a import double\nfrom b import triple\n",
    "test_a.py": "import unittest\nfrom a import double\n\n\nclass TestA(unittest.TestCase):\n    def test_zero(self):\n"
                 "        self.assertIsInstance(double(1), int)\n",
    "test_b.py": "import unittest\nfrom b import triple\n\n\nclass TestB(unittest.TestCase):\n    def test_zero(self):\n"
                 "        self.assertIsInstance(triple(1), int)\n",
}
A_TEST = "\n    def test_two(self):\n        self.assertEqual(double(2), 4)\n"
B_TEST = "\n    def test_two(self):\n        self.assertEqual(triple(2), 6)\n"
D_TEST = "\n    def test_two(self):\n        self.assertEqual(quad(2), 8)\n"
A_ID, B_ID, D_ID = "test_a.py::TestA::test_two", "test_b.py::TestB::test_two", "test_d.py::TestD::test_two"
RANGES = {UA: ["a.py", "test_a.py"], UB: ["b.py", "test_b.py"], UD: ["d.py", "test_d.py"]}


class LaneCase(unittest.TestCase):
    """2 つの単位（a.py と b.py。範囲が重ならない）を持つ種と小さな実行器で、輪を回す"""
    UNITS = (UA, UB)
    ITEMS = {}   # 単位 → 修正案の項目の番号（tddlanes.items_of の差し替え。空は 1 単位 1 枝）
    LANES = ""   # 入力 tdd_lanes（並べの周の切り替え。空は on）

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        tmp = pathlib.Path(self._tmp.name)
        self.repo = tmp / "repo"
        self.repo.mkdir()
        for name, text in SEED.items():
            (self.repo / name).write_text(text, encoding="utf-8")
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "seed")
        self.addCleanup(unittrees.sweep, self.repo)
        self.suite = tmp / "suite.py"
        self.suite.write_text(SUITE, encoding="utf-8")
        self.board = tmp / "art" / "board"
        self.start = tddloop.start(self.board, self.repo, str(self.suite), json.dumps(list(self.UNITS), ensure_ascii=False),
                                   lanes=self.LANES)
        self.assertTrue(self.start["go"], self.start)
        self.state = self.start["state_file"]
        patch = mock.patch.object(tddlanes, "ranges", side_effect=lambda board_dir, keys: {k: RANGES.get(k) for k in keys})
        patch.start()
        self.addCleanup(patch.stop)
        items = mock.patch.object(tddlanes, "items_of", side_effect=lambda board_dir, keys: {k: self.ITEMS.get(k, []) for k in keys})
        items.start()
        self.addCleanup(items.stop)

    def st(self):
        return json.loads(pathlib.Path(self.state).read_text(encoding="utf-8"))

    def step(self, reply):
        return tddloop.step(self.state, reply, self.repo, lanes=tddlanes)

    def route(self):
        got = self.step({"phase": "route", "units": [{"unit_key": k, "route": "tdd"} for k in self.UNITS]})
        self.assertTrue(got["ok"], got)
        return got

    def lane(self, key):
        return next(r for r in self.st()["lanes"]["rows"] if key in r["unit_keys"])

    def edit(self, root, name, old, new):
        p = pathlib.Path(root) / name
        text = p.read_text(encoding="utf-8")
        self.assertIn(old, text)
        p.write_text(text.replace(old, new, 1), encoding="utf-8")

    def cmd(self, key, reply):
        """枝の確かめを 1 回（枝の役の返答の代わり）。key は枝の今の単位でなければならない（枝の輪は今の単位だけを回す）"""
        row = self.lane(key)
        lst = json.loads(pathlib.Path(row["state"]).read_text(encoding="utf-8"))
        self.assertEqual(lst["queue"][lst["cur"]], key, "枝の今の単位でない")
        return tddlanes.lane_step(self.state, row["n"], reply, self.repo)

    def join(self):
        return tddlanes.join(self.state, self.repo)

    def red(self, key):
        tree = self.lane(key)["tree"]
        name, body, tid = {UA: ("test_a.py", A_TEST, A_ID), UB: ("test_b.py", B_TEST, B_ID), UD: ("test_d.py", D_TEST, D_ID)}[key]
        (pathlib.Path(tree) / name).write_text((pathlib.Path(tree) / name).read_text(encoding="utf-8") + body, encoding="utf-8")
        got = self.cmd(key, {"phase": "test", "unit_key": key, "test_files": [name], "tests": [tid]})
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["phase"], "fix")
        return got

    def green(self, key, new=None):
        tree = self.lane(key)["tree"]
        name, old, fixed = {UA: ("a.py", "x + x + 1", "x + x"), UB: ("b.py", "x * 3 + 1", "x * 3"),
                            UD: ("d.py", "x * 4 + 1", "x * 4")}[key]
        self.edit(tree, name, old, new or fixed)
        got = self.cmd(key, {"phase": "fix", "unit_key": key, "files": [name], "what": "余計な 1 を消した"})
        self.assertTrue(got["ok"], got)
        lst = json.loads(pathlib.Path(self.lane(key)["state"]).read_text(encoding="utf-8"))
        self.assertEqual(lst["units"][key]["green"], "ok", got)
        return got


class TestPlan(LaneCase):
    def test_route_plants_lanes_for_disjoint_units(self):
        got = self.route()
        self.assertEqual(got["phase"], "lanes")
        st = self.st()
        rows = st["lanes"]["rows"]
        self.assertEqual([r["unit_keys"] for r in rows], [[UA], [UB]])
        self.assertEqual([len(r["files"]) for r in rows], [1, 1])
        place = pathlib.Path(self.board).parent / "run-place"
        for r in rows:
            self.assertTrue(pathlib.Path(r["tree"]).is_dir())
            self.assertTrue(str(pathlib.Path(r["tree"]).resolve()).startswith(str(place.resolve())), r)
            self.assertEqual((pathlib.Path(r["tree"]) / "a.py").read_text(encoding="utf-8"), SEED["a.py"])
        self.assertNotIn("lanes_skipped", got, "並べた周は見送りの理由を出さない")
        manifest = pathlib.Path(st["lanes"]["manifest"])
        self.assertEqual(manifest.parent, pathlib.Path(st["work"]), "目録は盤面の tdd-<k>/ の下（共有の記録 tdd-*/**）")

    def test_overlapping_units_run_side_by_side(self):
        with mock.patch.object(tddlanes, "ranges", return_value={UA: ["a.py", "c.py"], UB: ["b.py", "c.py"]}):
            got = self.route()
        self.assertEqual(got["phase"], "lanes", "範囲が重なっても並べる（依頼 243 の並べの 3 段目）")
        self.assertEqual(self.st()["lanes"]["expect"], [[1, 2]], "重なりの見込みを測りに残す")

    def test_units_of_one_item_share_one_lane(self):
        self.ITEMS = {UA: [1], UB: [1]}
        got = self.route()
        self.assertEqual(got["phase"], "test", "項目を共にする 2 単位は 1 本の枝で、枝が 1 本なら並べない")
        self.assertEqual(got["lanes_skipped"]["reason"], tddlanes.SKIP_LANES)
        self.assertIn("枝が 1 本", got["lanes_skipped"]["why"])

    def test_groups_join_units_through_items(self):
        got = tddlanes.groups(["u1", "u2", "u3", "u4"], {"u1": [1], "u2": [2], "u3": [1, 3], "u4": [3]})
        self.assertEqual(got, [["u1", "u3", "u4"], ["u2"]])
        self.assertEqual(tddlanes.groups(["u1", "u2"], {}), [["u1"], ["u2"]], "項目に無い単位は 1 単位 1 枝")

    def test_unit_without_range_stays_serial(self):
        with mock.patch.object(tddlanes, "ranges", return_value={UA: ["a.py"], UB: None}):
            got = self.route()
        self.assertEqual(got["phase"], "test")
        self.assertEqual(got["lanes_skipped"]["reason"], tddlanes.SKIP_LANES)
        self.assertIn("範囲の引ける枝が 1 本", got["lanes_skipped"]["why"])

    def test_direct_units_are_not_planted(self):
        got = self.step({"phase": "route", "units": [{"unit_key": UA, "route": "tdd"},
                                                     {"unit_key": UB, "route": "direct", "why": "文書の直しで先にテストを書けない"}]})
        self.assertEqual(got["phase"], "test", "tdd の単位が 1 つなら並べない")
        self.assertEqual(got["lanes_skipped"]["reason"], tddlanes.SKIP_UNITS)
        self.assertIn("1 つ", got["lanes_skipped"]["why"])

    def test_skip_is_named_once_after_the_route(self):
        """見送りの理由は振り分けを受けた周だけ出す（拒んだ振り分け・後の段では出さない）"""
        got = self.step({"phase": "route", "units": []})
        self.assertFalse(got["ok"])
        self.assertNotIn("lanes_skipped", got)
        self.ITEMS = {UA: [1], UB: [1]}
        self.assertIn("lanes_skipped", self.route())
        got = self.step({"phase": "test", "unit_key": UA, "test_files": [], "tests": []})
        self.assertNotIn("lanes_skipped", got)

    def test_step_script_writes_the_skip_to_the_trace(self):
        """節 tdd-step は見送りの理由を盤面の trace に 1 行（tddlanes.SKIP_OP）で積み、出口には載せない"""
        import importlib.util
        spec = importlib.util.spec_from_file_location("blk_fix_tdd_step_skip", BLK / "scripts" / "tdd_step.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        skipped = {"reason": tddlanes.SKIP_UNITS, "why": "x", "loop": "tdd-1"}
        b = mock.MagicMock()
        emitted = {}
        with mock.patch.object(mod.tddloop, "step", return_value={"ok": True, "done": False, "reason": "", "phase": "test",
                                                                  "conflict": None, "writes": None,
                                                                  "lanes_skipped": skipped}), \
                mock.patch.object(mod.entry, "open_board", return_value=b), \
                mock.patch.object(mod.script_io, "emit_result", side_effect=lambda board, name, out, last: emitted.update(out) or 0), \
                mock.patch.dict("os.environ", {"INPUTS_REPLY": "{}", "INPUTS_STATE_FILE": self.state,
                                               "ARTIFACTS_DIR": str(self.board.parent)}):
            self.assertEqual(mod.main(), 0)
        b.trace.assert_called_once_with(tddlanes.SKIP_OP, **skipped)
        self.assertNotIn("lanes_skipped", emitted)


class TestLanesSwitchedOff(LaneCase):
    """入力 tdd_lanes が off（線の features_off の tdd_lanes）なら、枝が 2 本在っても並べの周へ進まず順に回す"""
    LANES = "off"

    def test_off_never_plants(self):
        self.assertFalse(self.st()["lanes_on"])
        got = self.route()
        self.assertEqual(got["phase"], "test")
        self.assertFalse(got["done"], "輪 tdd-loop は振り分けの周で抜けず、順に回し続ける")
        self.assertEqual(got["lanes_skipped"]["reason"], tddlanes.SKIP_SWITCH)
        self.assertFalse(self.st().get("lanes"), "枝の目録を置かない")
        self.assertEqual(tddlanes.fork(self.state), {"go": False, "lanes": 0, "lane_1": False, "lane_2": False, "lane_3": False},
                         "節 tdd-fork は枝の輪を起こさない（tdd-join・tdd-rest-loop も飛ぶ）")


class TestLanesUnknownWord(unittest.TestCase):
    def test_unknown_word_is_broken(self):
        """知らない語は輪の状態を書く前に Broken（節は 2 で落ちる）"""
        with tempfile.TemporaryDirectory() as tmp, self.assertRaises(tddloop.Broken):
            tddloop.start(pathlib.Path(tmp) / "board", pathlib.Path(tmp), "suite.py", json.dumps([UA]), lanes="no")


class TestLaneCommand(LaneCase):
    def test_red_then_green_in_unit_tree_leaves_run_tree_alone(self):
        self.route()
        self.red(UA)
        got = self.green(UA)
        self.assertEqual(got["phase"], "done")
        self.assertEqual((self.repo / "a.py").read_text(encoding="utf-8"), SEED["a.py"], "run の作業ツリーは書かない")

    def test_lane_checks_are_the_loop_checks(self):
        self.route()
        tree = pathlib.Path(self.lane(UA)["tree"])
        (tree / "test_a.py").write_text(SEED["test_a.py"] + "\n    def test_one(self):\n        self.assertEqual(double(0), 1)\n",
                                        encoding="utf-8")
        got = self.cmd(UA, {"phase": "test", "unit_key": UA, "test_files": ["test_a.py"], "tests": ["test_a.py::TestA::test_one"]})
        self.assertFalse(got["ok"], "もう通るテストは赤でない（写しの red_problems）")
        self.assertEqual(got["phase"], "test")

    def test_frozen_test_rejected_in_lane(self):
        self.route()
        self.red(UA)
        tree = pathlib.Path(self.lane(UA)["tree"])
        self.edit(tree, "test_a.py", "double(2), 4", "double(2), 5")
        self.edit(tree, "a.py", "x + x + 1", "x + x + 1")
        got = self.cmd(UA, {"phase": "fix", "unit_key": UA, "files": ["a.py"], "what": "テストを変えた"})
        self.assertFalse(got["ok"])
        self.assertIn("テストのファイルを赤の時から書き換えた", got["reason"])

    def test_unrecorded_write_in_lane_is_rejected(self):
        """枝の役の書き込みの出どころは run の作業ツリーの記録（包みが Archon の cwd の鍵で、単位の worktree の実パスを残す）と
        突き合わせる: 記録も申告も無い変更は段を拒み、記録が在れば通す"""
        self.route()
        home = pathlib.Path(self._tmp.name) / "adapter-home"
        with mock.patch.dict(os.environ, {adapter.ENV_HOME: str(home)}):
            log = writes.sink(self.repo)
            log.parent.mkdir(parents=True, exist_ok=True)
            log.write_text("", encoding="utf-8")
            tree = pathlib.Path(self.lane(UA)["tree"])
            (tree / "test_a.py").write_text(SEED["test_a.py"] + A_TEST, encoding="utf-8")
            reply = {"phase": "test", "unit_key": UA, "test_files": ["test_a.py"], "tests": [A_ID]}
            got = self.cmd(UA, reply)
            self.assertFalse(got["ok"], got)
            self.assertIn("書き込みの記録", got["reason"])
            real = os.path.realpath(tree / "test_a.py")
            sha = writes._sha(real)
            log.write_text(json.dumps({"path": real, "file_sha": sha, "tool_name": "Write"}) + "\n", encoding="utf-8")
            got = self.cmd(UA, reply)
            self.assertTrue(got["ok"], got)
            self.assertEqual(got["phase"], "fix")

    def test_rejects_count_and_give_up(self):
        """枝の確かめの拒否は同じ段の出し直しに数え、RETRY_MAX 回目で諦めて枝を済みにする（輪を回数の上限まで回さない）"""
        self.route()
        bad = {"phase": "test", "unit_key": UA, "test_files": ["test_a.py"], "tests": ["test_a.py::TestA::test_nothing"]}
        for _ in range(tddloop.retry_max()):
            got = self.cmd(UA, bad)
            self.assertFalse(got["ok"], got)
        self.assertTrue(got["done"], got)
        lst = json.loads(pathlib.Path(self.lane(UA)["state"]).read_text(encoding="utf-8"))
        self.assertEqual((lst["units"][UA]["route"], lst["units"][UA]["gave_up"]), ("direct", "red"))
        got = self.join()
        self.assertIn(UA, self.st()["lanes"]["back"], "並べで諦めた単位は順に戻す（direct にしない）")

    def test_wrong_unit_conflict_counts_as_a_reject(self):
        self.route()
        got = self.cmd(UA, {"phase": "conflict", "unit_key": UB, "between": ["a.py:1", "test_a.py:1"],
                            "why_both_cannot_hold": "別の枝の単位を名指した申し出", "which_is_right": "request",
                            "kind": "brief_vs_judgment"})
        self.assertEqual((got["ok"], got["done"]), (False, False), got)
        lst = json.loads(pathlib.Path(self.lane(UA)["state"]).read_text(encoding="utf-8"))
        self.assertEqual(lst["tries"], 1)
        self.assertIn(UA, lst["reason"])

    def test_broken_git_line_ends_the_lane_and_goes_back(self):
        self.route()
        tree = pathlib.Path(self.lane(UA)["tree"])
        (tree / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        got = self.cmd(UA, {"phase": "test", "unit_key": UA, "test_files": ["test_a.py"], "tests": [A_ID]})
        self.assertEqual((got["ok"], got["done"]), (False, True), got)
        self.assertIn(".git の指し", got["reason"])
        self.assertEqual(tddlanes.lane_prep(self.state, 1), {"prompt_file": "", "go": False}, "済みにした枝は役を起こさない")
        self.red(UB)
        self.green(UB)
        self.join()
        st = self.st()
        self.assertIn(UA, st["lanes"]["back"])
        self.assertIn(".git", st["lanes"]["back"][UA]["why"])

    def test_lane_step_after_the_lane_is_done_is_broken(self):
        self.route()
        self.red(UA)
        self.green(UA)
        with self.assertRaises(tddloop.Broken):
            tddlanes.lane_step(self.state, 1, {"phase": "fix", "unit_key": UA}, self.repo)
        self.assertEqual(tddlanes.lane_prep(self.state, 1), {"prompt_file": "", "go": False},
                         "済んだ枝の支度は役を起こさない（resume で輪がもう 1 度起きても落ちない）")


class TestSettle(LaneCase):
    def test_both_green_are_applied_and_checked_again(self):
        self.route()
        for k in (UA, UB):
            self.red(k)
            self.green(k)
        trees = [r["tree"] for r in self.st()["lanes"]["rows"]]
        got = self.join()
        self.assertEqual((got["go"], got["done"], got["merged"], got["back"]), (False, True, 2, 0), got)
        self.assertEqual((self.repo / "a.py").read_text(encoding="utf-8"), "def double(x):\n    return x + x\n")
        self.assertEqual((self.repo / "b.py").read_text(encoding="utf-8"), SEED["b.py"].replace("x * 3 + 1", "x * 3"))
        st = self.st()
        for k, tid in ((UA, A_ID), (UB, B_ID)):
            u = st["units"][k]
            self.assertEqual((u["route"], u["red"], u["green"], u["tests"]), ("tdd", "ok", "ok", [tid]))
        self.assertEqual(tddloop.frozen_problems(self.state, self.repo), [])
        self.assertEqual(sorted(st["frozen"]), ["test_a.py", "test_b.py"])
        for t in trees:
            self.assertFalse(pathlib.Path(t).exists(), "単位の worktree は片付ける")
        ex = tddloop.exit_fields(self.start)
        self.assertEqual([(u["unit_key"], u["green"]) for u in ex["units"]], [(UA, "ok"), (UB, "ok")])
        self.assertEqual([(r["unit_key"], r["outcome"]) for r in ex["lanes"]["units"]], [(UA, "merged"), (UB, "merged")])
        self.assertEqual([(c["lane"], c["phase"]) for c in ex["lanes"]["calls"]], [(1, "test"), (1, "fix"), (2, "test"), (2, "fix")],
                         "枝の役の起動 1 回に 1 行（出口の lanes.calls。枝の番号つき）")
        self.assertEqual([c["phase"] for c in ex["calls"]], ["route", "lanes"], "calls は tdd の節の起動 1 回と締めの 1 行")

    def test_unfinished_lane_goes_back_to_serial(self):
        self.route()
        self.red(UA)
        self.green(UA)
        self.red(UB)   # 直しの段の前で止まった下請け
        got = self.join()
        self.assertEqual((got["go"], got["done"], got["phase"]), (True, False, "test"))
        st = self.st()
        self.assertEqual(st["queue"][st["cur"]], UB)
        self.assertEqual(st["units"][UB]["red"], "", "戻した単位は最初の段から")
        self.assertEqual((self.repo / "test_b.py").read_text(encoding="utf-8"), SEED["test_b.py"], "済まなかった単位は当てない")
        self.assertEqual((self.repo / "a.py").read_text(encoding="utf-8"), "def double(x):\n    return x + x\n")
        prompt = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("並べで済まなかった", prompt)
        prepkit.drawn(self, tddloop.REST_NODE, prompt, off=("structmark.plan_section", "fixrules.tdd_render", "planbrief.head_text",
                                                            "planbrief.render", "tddloop._together_lines", "tddloop.prep"))
        self.assertIn(UA, prompt.split(tddloop.HANDOFF_HEAD, 1)[1], "並べで済んだ単位は引き継ぎに並ぶ")
        # 順に戻った単位は今どおり回る
        self.edit(self.repo, "test_b.py", "triple(1), int)\n", "triple(1), int)\n" + B_TEST)
        got = self.step({"phase": "test", "unit_key": UB, "test_files": ["test_b.py"], "tests": [B_ID]})
        self.assertTrue(got["ok"], got)

    def test_clashing_apply_goes_back_to_serial(self):
        self.route()
        for k in (UA, UB):
            self.red(k)
            self.edit(self.lane(k)["tree"], "c.py", "SHARED = 1", f"SHARED = {2 if k == UA else 3}")   # 範囲の外の同じ行
            self.green(k)
        got = self.join()
        self.assertEqual(got["phase"], "test")
        st = self.st()
        self.assertEqual(st["queue"][st["cur"]], UB)
        self.assertEqual((self.repo / "c.py").read_text(encoding="utf-8"), "SHARED = 2\n")
        back = st["lanes"]["back"][UB]
        self.assertTrue(pathlib.Path(back["patch"]).is_file(), "前の試みの差分を盤面に残す")
        self.assertTrue(str(pathlib.Path(back["patch"])).startswith(str(pathlib.Path(st["work"]))))

    def test_red_after_merge_backs_out_all_lanes(self):
        """範囲は重ならないが、当てた後の木で赤（b が a の誤りを当てにして直した）: 当てた単位を全部戻して順に回す"""
        self.route()
        self.red(UA)
        self.green(UA)
        self.red(UB)
        self.green(UB, new="x * 3 + 1 - double(0)")
        got = self.join()
        self.assertEqual((got["done"], got["phase"]), (False, "test"))
        st = self.st()
        self.assertEqual(st["queue"], [UA, UB])
        for name in ("a.py", "b.py", "test_a.py", "test_b.py"):
            self.assertEqual((self.repo / name).read_text(encoding="utf-8"), SEED[name], name)
        self.assertIn("当てた後", st["lanes"]["back"][UA]["why"])

    def test_forged_red_is_caught_at_close(self):
        """赤の記録は下請けが書ける控えに在る（危険 1）: 締めが単位の頭の木に赤の時のテストのファイルだけを置いて名指しを
        回し直し、記録どおりに落ちなければ当てずに順へ戻して理由を残す"""
        self.route()
        row = self.lane(UA)
        tree = pathlib.Path(row["tree"])
        passing = "\n    def test_two(self):\n        self.assertEqual(double(2) - double(0), 4)\n"   # 直す前から通る
        (tree / "test_a.py").write_text(SEED["test_a.py"] + passing, encoding="utf-8")
        lst = json.loads(pathlib.Path(row["state"]).read_text(encoding="utf-8"))   # 下請けが控えを手で書き換えた
        lst["units"][UA].update(tests=[A_ID], test_files=["test_a.py"], red="ok", red_kinds={A_ID: "unknown"},
                                test_hashes=tddloop.hashes(tree, ["test_a.py"]))
        lst.update(phase="fix", tries=0)
        pathlib.Path(row["state"]).write_text(json.dumps(lst, ensure_ascii=False), encoding="utf-8")
        self.green(UA)
        self.red(UB)
        self.green(UB)
        got = self.join()
        self.assertEqual(got["phase"], "test")
        st = self.st()
        self.assertEqual(st["queue"][st["cur"]], UA)
        self.assertIn("赤", st["lanes"]["back"][UA]["why"])
        self.assertEqual((self.repo / "a.py").read_text(encoding="utf-8"), SEED["a.py"], "赤を確かめ直せない単位は当てない")
        self.assertEqual((self.repo / "b.py").read_text(encoding="utf-8"), SEED["b.py"].replace("x * 3 + 1", "x * 3"))
        out = {r["unit_key"]: r for r in st["lanes"]["out"]}   # 出口の lanes.units の元（輪が済むと exit_fields が出す）
        self.assertEqual(out[UA]["outcome"], "serial")
        self.assertIn("赤", out[UA]["why"])

    def test_direct_why_in_lane_is_direct(self):
        self.route()
        got = self.cmd(UA, {"phase": "test", "unit_key": UA, "direct_why": "設定だけの直しで先にテストを書けない"})
        self.assertTrue(got["done"], got)
        self.red(UB)
        self.green(UB)
        got = self.join()
        self.assertTrue(got["done"], got)
        u = self.st()["units"][UA]
        self.assertEqual((u["route"], u["gave_up"]), ("direct", "writer"))

    def test_stray_write_of_run_tree_is_reverted(self):
        self.route()
        (self.repo / "c.py").write_text("SHARED = 9\n", encoding="utf-8")   # 並べの周に run の作業ツリーが書かれた（枝の役は柵で書けない）
        got = self.join()
        self.assertTrue(got["go"], got)
        self.assertEqual((self.repo / "c.py").read_text(encoding="utf-8"), SEED["c.py"])
        self.assertEqual(self.st()["lanes"]["reverted"], ["c.py"])

    def test_lane_conflict_is_checked_and_parked(self):
        self.route()
        item = {"phase": "conflict", "unit_key": UA, "between": ["a.py:2", "test_a.py:7"],
                "why_both_cannot_hold": "テストは 1 を足した値を求め、依頼は足さない値を求める", "which_is_right": "request",
                "kind": "brief_vs_judgment"}
        got = self.cmd(UA, item)
        self.assertTrue(got["done"], got)
        with mock.patch.object(tddloop.conflict, "problems", return_value=[]) as pr:
            got = self.join()
        self.assertEqual(pr.call_args.kwargs["owed"], {UA})
        self.assertEqual([c["unit_key"] for c in got["conflicts"]], [UA])
        st = self.st()
        self.assertIn(UA, st["parked"])
        self.assertEqual(st["units"][UA]["route"], "parked")

    def test_lane_conflict_that_fails_check_goes_back(self):
        self.route()
        self.cmd(UA, {"phase": "conflict", "unit_key": UA, "between": ["nope.py:1", "nope.py:2"],
                      "why_both_cannot_hold": "名指しが在らない申し出", "which_is_right": "request", "kind": "brief_vs_judgment"})
        got = self.join()
        self.assertEqual(got["conflicts"], [])
        st = self.st()
        self.assertEqual(st["queue"][st["cur"]], UA)


class TestOneItemLane(LaneCase):
    """項目を共にする 2 単位（b.py と d.py）の枝と、1 単位（a.py）の枝。枝の中は順に、単位ごとに新しい下請け"""
    UNITS = (UA, UB, UD)
    ITEMS = {UA: [1], UB: [2], UD: [2]}

    def test_lane_runs_its_units_in_turn_with_a_handoff(self):
        self.route()
        st = self.st()
        self.assertEqual([r["unit_keys"] for r in st["lanes"]["rows"]], [[UA], [UB, UD]])
        self.red(UB)
        got = self.green(UB)
        self.assertEqual((got["done"], got["phase"], got["unit_key"]), (False, "test", UB),
                         "枝の 1 番目の単位が済むと、枝は 2 番目の単位の段 test へ（枝の輪は続く）")
        row = self.lane(UB)
        lst = json.loads(pathlib.Path(row["state"]).read_text(encoding="utf-8"))
        self.assertEqual(lst["queue"][lst["cur"]], UD)
        self.assertEqual(sorted(lst["unit_heads"]), sorted([UB, UD]), "単位ごとの頭の木を控えに残す")
        out = tddlanes.lane_prep(self.state, row["n"])
        brief = pathlib.Path(row["files"][1]).read_text(encoding="utf-8")
        self.assertIn(tddloop.HANDOFF_HEAD, brief, "2 番目の単位の決まりのファイルに前の単位の引き継ぎ")
        self.assertIn(UB, brief.split(tddloop.HANDOFF_HEAD, 1)[1])
        self.assertIn(row["files"][1], pathlib.Path(out["prompt_file"]).read_text(encoding="utf-8"))
        key = pathlib.Path(adapter.session_key_path(str(self.board), tddlanes.LANE_NODE.format(n=row["n"])))
        self.assertTrue(key.read_text(encoding="utf-8").strip().endswith(f":lane-{row['n']}:{UD}"),
                        "単位が替わると包みが新しい会話で起こす鍵")
        self.red(UD)
        got = self.green(UD)
        self.assertEqual((got["done"], got["phase"]), (True, "done"))
        self.red(UA)
        self.green(UA)
        got = self.join()
        self.assertEqual((got["go"], got["done"]), (False, True), got)
        for name, text in (("a.py", "x + x\n"), ("b.py", "x * 3\n"), ("d.py", "x * 4\n")):
            self.assertIn(text, (self.repo / name).read_text(encoding="utf-8"), name)
        st = self.st()
        self.assertEqual({r["unit_key"]: (r["outcome"], r["lane"]) for r in st["lanes"]["out"]},
                         {UA: ("merged", 1), UB: ("merged", 2), UD: ("merged", 2)})
        self.assertEqual(st["units"][UD]["green"], "ok")

    def test_rejected_conflicts_give_up_and_the_next_unit_keeps_its_head(self):
        """申し出の拒否が RETRY_MAX 回で諦めても、枝は次の単位の頭の木を残す（締めの赤の確かめ直しが単位ごとに使う）"""
        self.route()
        bad = {"phase": "conflict", "unit_key": UD, "between": ["b.py:1", "test_b.py:1"],
               "why_both_cannot_hold": "今の単位でない単位を名指した申し出", "which_is_right": "request", "kind": "brief_vs_judgment"}
        for _ in range(tddloop.retry_max()):
            got = tddlanes.lane_step(self.state, self.lane(UB)["n"], bad, self.repo)
        self.assertEqual((got["done"], got["phase"]), (False, "test"), got)
        lst = json.loads(pathlib.Path(self.lane(UB)["state"]).read_text(encoding="utf-8"))
        self.assertEqual(lst["queue"][lst["cur"]], UD)
        self.assertIn(UD, lst["unit_heads"])
        self.red(UD)
        self.green(UD)
        self.red(UA)
        self.green(UA)
        self.join()
        st = self.st()
        self.assertEqual(st["units"][UD]["green"], "ok", "次の単位は頭の木で赤を確かめ直して当たる")
        self.assertIn(UB, st["lanes"]["back"], "諦めた単位は順に戻す")

    def test_unfinished_second_unit_is_not_merged(self):
        self.route()
        self.red(UB)
        self.green(UB)
        self.red(UD)   # 2 番目の単位は直しの前で止まった（書きかけのテストを当てない）
        self.red(UA)
        self.green(UA)
        got = self.join()
        st = self.st()
        self.assertEqual(st["queue"][st["cur"]], UD)
        self.assertIn("x * 3\n", (self.repo / "b.py").read_text(encoding="utf-8"), "済んだ 1 番目の単位は当てる")
        self.assertEqual((self.repo / "test_d.py").read_text(encoding="utf-8"), SEED["test_d.py"])
        self.assertEqual(got["phase"], "test")


class TestOneItemLaneWithContract(LaneCase):
    """修正案の項目 2 に b.py と d.py の 2 単位が載り、項目の受け入れのテスト 2 本が両方の単位の約束に在る枝（canary の run 245042a7 の
    形を枝で）。枝の 1 番目の単位の決まりは 2 番目を「今は手を付けるな」と言わず一緒に直させ、緑に届けば機械が 2 番目を閉じる。
    締めは閉じた単位の赤を、一緒に直した単位の赤の確かめ直しで見たものとして当てる（申し出も順への戻しも無い）"""
    UNITS = (UA, UB, UD)
    ITEMS = {UA: [1], UB: [2], UD: [2]}
    ITEM2 = [{"id": B_ID, "red_kind": "assertion"}, {"id": D_ID, "red_kind": "assertion"}]
    CONTRACT = {UA: {"items": [1], "route": "tdd", "rewrites": [], "refactor": [], "tests": [{"id": A_ID, "red_kind": "assertion"}]},
                UB: {"items": [2], "route": "tdd", "rewrites": [], "refactor": [], "tests": ITEM2},
                UD: {"items": [2], "route": "tdd", "rewrites": [], "refactor": [], "tests": ITEM2}}

    def setUp(self):
        super().setUp()
        with mock.patch.object(tddloop, "plan_contract", return_value=self.CONTRACT):
            self.start = tddloop.start(self.board, self.repo, str(self.suite), json.dumps(list(self.UNITS), ensure_ascii=False))
        self.assertTrue(self.start["go"], self.start)
        self.state = self.start["state_file"]

    def test_second_unit_of_the_item_is_fixed_with_the_first(self):
        self.route()
        row = self.lane(UB)
        self.assertEqual(row["unit_keys"], [UB, UD])
        tddlanes.lane_prep(self.state, row["n"])
        rules = pathlib.Path(row["files"][0]).read_text(encoding="utf-8")
        self.assertNotIn("この枝の後の単位（今は手を付けるな", rules, "同じ項目の後の単位を後回しにさせない")
        self.assertIn(tddloop.TOGETHER_HEAD, rules)
        self.assertIn(UD, rules.split(tddloop.TOGETHER_HEAD, 1)[1].split("\n## ", 1)[0])
        tree = pathlib.Path(row["tree"])
        for name, body in (("test_b.py", B_TEST), ("test_d.py", D_TEST)):
            (tree / name).write_text((tree / name).read_text(encoding="utf-8") + body, encoding="utf-8")
        got = self.cmd(UB, {"phase": "test", "unit_key": UB, "test_files": ["test_b.py", "test_d.py"], "tests": [B_ID, D_ID]})
        self.assertTrue(got["ok"], got)
        self.edit(tree, "b.py", "x * 3 + 1", "x * 3")
        self.edit(tree, "d.py", "x * 4 + 1", "x * 4")
        got = self.cmd(UB, {"phase": "fix", "unit_key": UB, "files": ["b.py", "d.py"], "what": "項目 2 の 2 つの余計な 1 を消した"})
        self.assertTrue(got["ok"], got)
        self.assertEqual((got["done"], got["phase"]), (True, "done"), "枝の 2 番目の単位は機械が閉じ、枝は済む")
        self.red(UA)
        self.green(UA)
        got = self.join()
        self.assertEqual((got["go"], got["done"], got["conflicts"]), (False, True, []), got)
        st = self.st()
        self.assertEqual({r["unit_key"]: r["outcome"] for r in st["lanes"]["out"]}, {UA: "merged", UB: "merged", UD: "merged"})
        self.assertEqual(st["units"][UD]["covered_by"], [UB])
        self.assertEqual(st["parked"], [])
        for name, text in (("b.py", "x * 3\n"), ("d.py", "x * 4\n")):
            self.assertIn(text, (self.repo / name).read_text(encoding="utf-8"), name)


UX = "e.py E1: 1 を返す（100 にする）"
X_ID = "test_b.py::TestB::test_e1"
X_TEST = "\n    def test_e1(self):\n        from e import E1\n        self.assertEqual(E1, 100)\n"


class ContractLaneCase(LaneCase):
    """約束（CONTRACT）を持つ枝の run。範囲は RANGES に EXTRA_RANGES を重ねる"""
    CONTRACT = {}
    EXTRA_RANGES = {}

    def setUp(self):
        super().setUp()
        with mock.patch.object(tddloop, "plan_contract", return_value=self.CONTRACT):
            self.start = tddloop.start(self.board, self.repo, str(self.suite), json.dumps(list(self.UNITS), ensure_ascii=False))
        self.assertTrue(self.start["go"], self.start)
        self.state = self.start["state_file"]
        rg = {**RANGES, **self.EXTRA_RANGES}
        p = mock.patch.object(tddlanes, "ranges", side_effect=lambda board_dir, keys: {k: rg.get(k) for k in keys})
        p.start()
        self.addCleanup(p.stop)


class TestClosedUnitThenLaterUnit(ContractLaneCase):
    """枝 [UB, UD（UB の段で一緒に直して閉じた）, UX（項目 2 と 3。自分の段を回す）]。閉じた UD は枝の頭の木を持たないが、締めの UB の
    赤の確かめ直しは、次に頭の木を持つ単位（UX）の頭から赤の時のテストのファイルを取る（UX が同じ試験のファイルに足しても戻さない）"""
    UNITS = (UA, UB, UD, UX)
    ITEMS = {UA: [1], UB: [2], UD: [2], UX: [2, 3]}
    I2 = [{"id": B_ID, "red_kind": "assertion"}, {"id": D_ID, "red_kind": "assertion"}]
    CONTRACT = {UA: {"items": [1], "route": "tdd", "rewrites": [], "refactor": [], "tests": [{"id": A_ID, "red_kind": "assertion"}]},
                UB: {"items": [2], "route": "tdd", "rewrites": [], "refactor": [], "tests": I2},
                UD: {"items": [2], "route": "tdd", "rewrites": [], "refactor": [], "tests": I2},
                UX: {"items": [2, 3], "route": "tdd", "rewrites": [], "refactor": [],
                     "tests": I2 + [{"id": X_ID, "red_kind": "assertion"}]}}
    EXTRA_RANGES = {UX: ["b.py", "test_b.py", "e.py"]}

    def test_lane_merges_all_three(self):
        self.route()
        row = self.lane(UB)
        self.assertEqual(row["unit_keys"], [UB, UD, UX])
        tree = pathlib.Path(row["tree"])
        for name, body in (("test_b.py", B_TEST), ("test_d.py", D_TEST)):
            (tree / name).write_text((tree / name).read_text(encoding="utf-8") + body, encoding="utf-8")
        self.assertTrue(self.cmd(UB, {"phase": "test", "unit_key": UB, "test_files": ["test_b.py", "test_d.py"],
                                      "tests": [B_ID, D_ID]})["ok"])
        self.edit(tree, "b.py", "x * 3 + 1", "x * 3")
        self.edit(tree, "d.py", "x * 4 + 1", "x * 4")
        got = self.cmd(UB, {"phase": "fix", "unit_key": UB, "files": ["b.py", "d.py"], "what": "項目 2 の余計な 1 を消した"})
        self.assertEqual((got["ok"], got["done"]), (True, False), got)
        (tree / "test_b.py").write_text((tree / "test_b.py").read_text(encoding="utf-8") + X_TEST, encoding="utf-8")
        self.assertTrue(self.cmd(UX, {"phase": "test", "unit_key": UX, "test_files": ["test_b.py"], "tests": [X_ID]})["ok"])
        self.edit(tree, "e.py", "E1 = 1\n", "E1 = 100\n")
        self.assertTrue(self.cmd(UX, {"phase": "fix", "unit_key": UX, "files": ["e.py"], "what": "E1 を 100 にした"})["ok"])
        self.red(UA)
        self.green(UA)
        self.join()
        st = self.st()
        self.assertEqual(st["lanes"]["back"], {})
        self.assertEqual({r["unit_key"]: r["outcome"] for r in st["lanes"]["out"]},
                         {UA: "merged", UB: "merged", UD: "merged", UX: "merged"})


class TestClosedUnitVerifiedByTwoUnits(ContractLaneCase):
    """枝 [UB（項目 2）, UD（項目 2・3）, UX（項目 2・3。UD の段で一緒に直して閉じる）]。UX の受け入れのテストの B は UB が、D は UD が
    確かめた。閉じた UX の赤は、枝で緑に届いた単位の名指しのどれかに在れば見たものとする（UD は確かめ済みの B を名指せない）"""
    UNITS = (UA, UB, UD, UX)
    ITEMS = {UA: [1], UB: [2], UD: [2, 3], UX: [2, 3]}
    B = [{"id": B_ID, "red_kind": "assertion"}]
    BD = B + [{"id": D_ID, "red_kind": "assertion"}]
    CONTRACT = {UA: {"items": [1], "route": "tdd", "rewrites": [], "refactor": [], "tests": [{"id": A_ID, "red_kind": "assertion"}]},
                UB: {"items": [2], "route": "tdd", "rewrites": [], "refactor": [], "tests": B},
                UD: {"items": [2, 3], "route": "tdd", "rewrites": [], "refactor": [], "tests": BD},
                UX: {"items": [2, 3], "route": "tdd", "rewrites": [], "refactor": [], "tests": BD}}
    EXTRA_RANGES = {UX: ["d.py", "test_d.py"]}

    def test_lane_merges_all_three(self):
        self.route()
        self.assertEqual(self.lane(UB)["unit_keys"], [UB, UD, UX])
        self.red(UB)
        self.green(UB)
        self.red(UD)
        got = self.green(UD)
        self.assertEqual((got["done"], got["phase"]), (True, "done"), "UX は UD の段で一緒に直して閉じる")
        self.red(UA)
        self.green(UA)
        self.join()
        st = self.st()
        self.assertEqual(st["lanes"]["back"], {})
        self.assertEqual(st["units"][UX]["covered_by"], [UD])
        ux = st["units"][UX]
        self.assertEqual(sorted({*ux["red_quotes"], *ux["quote_unchecked"]}), sorted([B_ID, D_ID]),
                         "赤の引用（と照らせなかった名指し）は確かめた単位の全部から")


NEG_TEST = "\n    def test_neg(self):\n        self.assertEqual(negate(2), -2)\n"
NEG_ID = "test_a.py::TestA::test_neg"


class TestStubRedTree(LaneCase):
    """枝の単位が、これから足す名前の仮の実装（テストでないファイル）を足して赤を作った時: 単位の記録の赤の木にその仮の実装が入り、
    締めの確かめ直しは記録の赤の木で名指しを回して再現を見る（単位の頭にテストのファイルだけを置く組み直しでは、仮の実装が無く
    組み立てで落ちて再現しない）"""

    def stub_red(self):
        """テストが無い名前 negate を読むので、一式の結末に名指しが居ない回は拒まれる。仮の実装（0 を返すだけ）を足して出し直すと赤が通る"""
        self.route()
        tree = pathlib.Path(self.lane(UA)["tree"])
        self.edit(tree, "test_a.py", "from a import double", "from a import double, negate")
        (tree / "test_a.py").write_text((tree / "test_a.py").read_text(encoding="utf-8") + NEG_TEST, encoding="utf-8")
        reply = {"phase": "test", "unit_key": UA, "test_files": ["test_a.py"], "tests": [NEG_ID]}
        got = self.cmd(UA, reply)
        self.assertFalse(got["ok"])
        self.assertIn(tddloop.NOT_RAN, got["reason"])
        (tree / "a.py").write_text((tree / "a.py").read_text(encoding="utf-8") + "\n\ndef negate(x):\n    return 0\n", encoding="utf-8")
        got = self.cmd(UA, reply)
        self.assertTrue(got["ok"], got)
        lst = json.loads(pathlib.Path(self.lane(UA)["state"]).read_text(encoding="utf-8"))
        self.assertEqual(lst["units"][UA]["stub_files"], ["a.py"])
        return tree

    def finish(self, tree):
        self.edit(tree, "a.py", "return 0\n", "return -x\n")   # 仮の実装を本物に置き換える（fix の段）
        got = self.cmd(UA, {"phase": "fix", "unit_key": UA, "files": ["a.py"], "what": "negate を本物にした"})
        self.assertTrue(got["ok"], got)
        self.red(UB)
        self.green(UB)

    def forge(self, tree, how):
        """下請けが書ける控えの赤の木を差し替える。passing＝名指しが通る木（直した後の木）／other_file＝名指しが self.fail で落ちる
        別のテストに差し替えた木"""
        if how == "passing":
            red = tddloop.snapshot(tree)
        else:
            good = (tree / "test_a.py").read_text(encoding="utf-8")
            (tree / "test_a.py").write_text(good.replace("self.assertEqual(negate(2), -2)", "self.fail('偽の赤')"), encoding="utf-8")
            red = tddloop.snapshot(tree)
            (tree / "test_a.py").write_text(good, encoding="utf-8")
        row = self.lane(UA)
        lst = json.loads(pathlib.Path(row["state"]).read_text(encoding="utf-8"))
        lst["units"][UA]["red_tree"] = red
        pathlib.Path(row["state"]).write_text(json.dumps(lst, ensure_ascii=False), encoding="utf-8")

    def test_close_rechecks_red_tree_with_stub(self):
        """記録の赤の木で再現して当てる（merged）。赤の記録は下請けが書ける控えに在るので、赤の木を名指しが通る木に差し替えても、
        別のテストに差し替えても、締めが見つけて当てずに順へ戻す"""
        for n, (how, word) in enumerate([("", ""), ("passing", "再現しない"), ("other_file", "赤の木の中のテストのファイル")]):
            with self.subTest(how or "genuine"):
                if n:
                    self.setUp()
                tree = self.stub_red()
                self.finish(tree)
                if how:
                    self.forge(tree, how)
                self.join()
                st = self.st()
                if not how:
                    self.assertEqual(st["lanes"]["back"], {})
                    self.assertEqual({r["unit_key"]: r["outcome"] for r in st["lanes"]["out"]}, {UA: "merged", UB: "merged"})
                    self.assertIn("return -x", (self.repo / "a.py").read_text(encoding="utf-8"))
                else:
                    self.assertIn(word, st["lanes"]["back"][UA]["why"])
                    self.assertEqual((self.repo / "a.py").read_text(encoding="utf-8"), SEED["a.py"], "赤を確かめ直せない単位は当てない")


class TestOverlap(LaneCase):
    """範囲が重なる 2 本の枝（どちらも e.py を変える）を並べ、機械が 3 方向で合わせる"""

    def both_touch_e(self, a_line="E1 = 10", b_line="E8 = 80"):
        self.route()
        self.red(UA)
        self.edit(self.lane(UA)["tree"], "e.py", "E1 = 1\n", a_line + "\n")
        self.green(UA)
        self.red(UB)
        self.edit(self.lane(UB)["tree"], "e.py", "E8 = 8\n", b_line + "\n")

    def test_same_file_different_lines_both_merge(self):
        self.both_touch_e()
        self.green(UB)
        got = self.join()
        self.assertEqual((got["go"], got["done"]), (False, True), got)
        e = (self.repo / "e.py").read_text(encoding="utf-8")
        self.assertIn("E1 = 10\n", e)
        self.assertIn("E8 = 80\n", e)
        st = self.st()
        self.assertEqual(st["lanes"]["shared"], ["e.py"])
        self.assertEqual({r["unit_key"]: (r["outcome"], r["merge"]) for r in st["lanes"]["out"]},
                         {UA: ("merged", "clean"), UB: ("merged", "clean")})
        self.assertEqual(tddloop.exit_fields(self.start)["lanes"]["shared"], ["e.py"], "出口に重なりのファイル")

    def test_semantic_clash_backs_out_only_the_later_lane(self):
        """字では合うが、合わせた木で b の名指しのテストが赤（b は e.py の E1 を当てにし、a が E1 を変えた）: 後の枝だけ戻す"""
        self.both_touch_e()
        self.edit(self.lane(UB)["tree"], "b.py", "def triple(x):\n    return x * 3 + 1\n",
                  "from e import E1\n\n\ndef triple(x):\n    return x * 3 + E1 - 1\n")
        got = self.cmd(UB, {"phase": "fix", "unit_key": UB, "files": ["b.py", "e.py"], "what": "E1 で 1 を打ち消した"})
        self.assertTrue(got["done"], got)
        got = self.join()
        self.assertEqual(got["phase"], "test")
        st = self.st()
        self.assertEqual(st["queue"][st["cur"]], UB)
        self.assertIn("意味の食い違い", st["lanes"]["back"][UB]["why"])
        self.assertEqual({r["unit_key"]: (r["outcome"], r["merge"]) for r in st["lanes"]["out"]},
                         {UA: ("merged", "clean"), UB: ("serial", "semantic")})
        self.assertIn("E1 = 10\n", (self.repo / "e.py").read_text(encoding="utf-8"), "先の枝は残す")
        self.assertEqual((self.repo / "b.py").read_text(encoding="utf-8"), SEED["b.py"])

    def test_tests_appended_to_one_file_are_unioned(self):
        self.route()
        for key, cls, body, fix in ((UA, "TestA2", "double(2), 4", ("a.py", "x + x + 1", "x + x")),
                                    (UB, "TestB2", "triple(2), 6", ("b.py", "x * 3 + 1", "x * 3"))):
            tree = pathlib.Path(self.lane(key)["tree"])
            (tree / "test_ab.py").write_text(SEED["test_ab.py"] + f"\n\nclass {cls}(unittest.TestCase):\n    def test_two(self):\n"
                                             f"        self.assertEqual({body})\n", encoding="utf-8")
            tid = f"test_ab.py::{cls}::test_two"
            got = self.cmd(key, {"phase": "test", "unit_key": key, "test_files": ["test_ab.py"], "tests": [tid]})
            self.assertTrue(got["ok"], got)
            self.edit(tree, *fix)
            got = self.cmd(key, {"phase": "fix", "unit_key": key, "files": [fix[0]], "what": "余計な 1 を消した"})
            self.assertTrue(got["done"], got)
        got = self.join()
        self.assertEqual((got["go"], got["done"]), (False, True), got)
        text = (self.repo / "test_ab.py").read_text(encoding="utf-8")
        self.assertLess(text.index("class TestA2"), text.index("class TestB2"), "先の枝の行の後に後の枝の行")
        st = self.st()
        self.assertEqual({r["unit_key"]: r["merge"] for r in st["lanes"]["out"]}, {UA: "clean", UB: "union"})


class TestPrep(LaneCase):
    def test_lane_prep_writes_the_unit_rules_the_turn_and_the_two_marks(self):
        self.route()
        st = self.st()
        for r in st["lanes"]["rows"]:
            out = tddlanes.lane_prep(self.state, r["n"])
            turn = pathlib.Path(out["prompt_file"])
            self.assertEqual(turn.parent, pathlib.Path(st["work"]), "回ごとの指示書は盤面の tdd-<k>/ の下（共有の記録 tdd-*/**）")
            text = turn.read_text(encoding="utf-8")
            for w in (r["files"][0], "段: test", r["unit_keys"][0], tddloop.RETURN["test"]):
                self.assertIn(w, text)
            sub = pathlib.Path(r["files"][0]).read_text(encoding="utf-8")
            for w in (r["unit_keys"][0], r["tree"], "**test**", "**fix**", "**refactor**", "## 並べの枝の役の読み替え"):
                self.assertIn(w, sub)
            for w in ("段のコマンド", "Agent で起こした", "reply.json"):
                self.assertNotIn(w, sub)
            self.assertNotIn(tddloop.HANDOFF_HEAD, sub, "枝の 1 番目の単位に引き継ぎは無い")
            node = tddlanes.LANE_NODE.format(n=r["n"])
            prepkit.drawn(self, node, text + "\n\n" + sub,   # 回ごとの指示書と、それが名指す単位の決まりのファイル
                          off=("structmark.plan_section", "planbrief.head_text", "planbrief.render", "tddlanes._next_text",
                               "tddloop._together_lines", "tddloop.handoff_lines"))
            self.assertEqual(pathlib.Path(adapter.lane_tree_path(str(self.board), node)).read_text(encoding="utf-8").strip(), r["tree"],
                             "包みが cwd にする単位の worktree（役の文からは取らない）")
            key = pathlib.Path(adapter.session_key_path(str(self.board), node)).read_text(encoding="utf-8").strip()
            self.assertEqual(key, f"{pathlib.Path(st['work']).name}:lane-{r['n']}:{r['unit_keys'][0]}")

    def test_turn_carries_the_reject_reason(self):
        self.route()
        self.cmd(UA, {"phase": "test", "unit_key": UA, "test_files": ["test_a.py"], "tests": ["test_a.py::TestA::test_nothing"]})
        text = pathlib.Path(tddlanes.lane_prep(self.state, 1)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("前の回の返答を機械が拒んだ理由", text)
        self.assertIn("test_nothing", text)

    def test_lanes_phase_is_not_the_loop_turn(self):
        """段 lanes の周は輪の外の節が回す: 輪の支度は役を起こさない go: false（resume で 1 周目から起きた輪が抜ける。TestResume）、
        確かめに返答を渡せば Broken（黙って順にしない）"""
        self.route()
        self.assertEqual(tddloop.prep(self.state), {"prompt_file": "", "go": False})
        with self.assertRaises(tddloop.Broken):
            tddloop.step(self.state, {"phase": "lanes"}, self.repo, lanes=tddlanes)

    def test_route_without_hooks_stays_serial(self):
        got = tddloop.step(self.state, {"phase": "route", "units": [{"unit_key": UA, "route": "tdd"},
                                                                    {"unit_key": UB, "route": "tdd"}]}, self.repo)
        self.assertEqual(got["phase"], "test")


class TestFork(LaneCase):
    UNITS = (UA, UB, UD, "e.py: 4 本目の枝")

    def test_fork_goes_only_in_the_lanes_phase(self):
        self.assertEqual(tddlanes.fork(""), {"go": False, "lanes": 0, "lane_1": False, "lane_2": False, "lane_3": False},
                         "実行器の無い run（状態のファイルが空）")
        self.assertIs(tddlanes.fork(self.state)["go"], False, "振り分けの前")
        self.route()
        got = tddlanes.fork(self.state)
        self.assertEqual(got, {"go": True, "lanes": 3, "lane_1": True, "lane_2": True, "lane_3": True})

    def test_lanes_are_capped_and_the_rest_stays_serial(self):
        with mock.patch.object(tddlanes, "ranges", side_effect=lambda board_dir, keys: {k: RANGES.get(k, ["e.py"]) for k in keys}):
            self.route()
        st = self.st()
        self.assertEqual([r["unit_keys"] for r in st["lanes"]["rows"]], [[UA], [UB], [UD]], f"枝は {tddlanes.MAX_LANES} 本まで")
        self.assertEqual(len(st["lanes"]["rows"]), tddlanes.MAX_LANES)
        for k in (UA, UB, UD):
            self.red(k)
            self.green(k)
        got = self.join()
        self.assertEqual((got["go"], got["phase"]), (True, "test"))
        st = self.st()
        self.assertEqual(st["queue"][st["cur"]], "e.py: 4 本目の枝", "枝に入らなかった単位は順の輪 tdd-rest が回す")


class TestScripts(LaneCase):
    """節の script を子で起こして並べの周を 1 回通す（tdd-fork → 枝ごとの支度・確かめ → tdd-join）"""

    def env(self, **kw):
        return {"ARTIFACTS_DIR": str(self.board.parent), "INPUTS_STATE_FILE": self.state, **kw}

    def test_scripts_run_one_lanes_turn(self):
        self.route()
        code, out, err = run_script("tdd_fork", self.repo, self.env())
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["lanes"], 2)
        values = {"INPUTS_JUDGMENT_FILE": "", "INPUTS_PLAN_FILE": "", "INPUTS_POLICY_PATH": "", "INPUTS_NOTES_FILE": ""}
        for key, n in ((UA, "1"), (UB, "2")):
            code, out, err = run_script("tdd_lane_prep", self.repo, self.env(INPUTS_LANE=n, **values))
            self.assertEqual(code, 0, err)
            self.assertTrue(pathlib.Path(json.loads(out)["prompt_file"]).is_file())
            tree = pathlib.Path(self.lane(key)["tree"])
            name, body, tid = {UA: ("test_a.py", A_TEST, A_ID), UB: ("test_b.py", B_TEST, B_ID)}[key]
            (tree / name).write_text((tree / name).read_text(encoding="utf-8") + body, encoding="utf-8")
            reply = json.dumps({"phase": "test", "unit_key": key, "test_files": [name], "tests": [tid]}, ensure_ascii=False)
            code, out, err = run_script("tdd_lane_step", self.repo, self.env(INPUTS_LANE=n, INPUTS_REPLY=reply))
            self.assertEqual(code, 0, err)
            got = json.loads(out)
            self.assertEqual((got["ok"], got["phase"], got["done"], got["reason_file"]), (True, "fix", False, ""), got)
            self.green(key)
        code, out, err = run_script("tdd_join", self.repo, self.env())
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out), {"go": False, "done": True, "phase": "done", "merged": 2, "back": 0})
        code, out, err = run_script("tdd_fork", self.repo, self.env())
        self.assertEqual((code, json.loads(out)["go"]), (0, False), "締めた後は枝の輪を起こさない")

    def test_lane_step_rejects_with_a_reason_file(self):
        self.route()
        reply = json.dumps({"phase": "fix", "unit_key": UA, "files": ["a.py"], "what": "段を飛ばした"}, ensure_ascii=False)
        code, out, err = run_script("tdd_lane_step", self.repo, self.env(INPUTS_LANE="1", INPUTS_REPLY=reply))
        self.assertEqual(code, 0, err)
        got = json.loads(out)
        self.assertFalse(got["ok"])
        self.assertTrue(pathlib.Path(got["reason_file"]).is_file())


class TestResume(LaneCase):
    """Archon の resume（v0.11.1）: 済んでいない節だけを回し直し、輪は 1 周目から・新しい会話で起こす。落ちた節に依る済んだ節も
    回し直す（tdd-join は all_done なので、枝の輪が 1 本落ちても締めて先へ進み、run は落ちたまま残る）。resume で落ちた枝の輪と
    締めがもう 1 度呼ばれても、役を起こさずに抜け、締めは同じ出口を返す（盤面・作業ツリーを動かさない）"""

    def half_join(self):
        """枝 1 は済み、枝 2 は直しの段の前で落ちた（口座の上限など）まま締めた"""
        self.route()
        self.red(UA)
        self.green(UA)
        self.red(UB)
        return self.join()

    def snap(self):
        return (pathlib.Path(self.state).read_bytes(), {n: (self.repo / n).read_bytes() for n in ("a.py", "b.py", "test_b.py")})

    def test_running_lane_prep_says_go(self):
        self.route()
        got = tddlanes.lane_prep(self.state, 1)
        self.assertIs(got["go"], True)
        self.assertTrue(pathlib.Path(got["prompt_file"]).is_file())

    def test_lane_loop_after_the_join_ends_without_the_role(self):
        self.half_join()
        before = self.snap()
        self.assertEqual(tddlanes.lane_prep(self.state, 2), {"prompt_file": "", "go": False})
        got = tddlanes.lane_step(self.state, 2, None, self.repo)
        self.assertEqual((got["ok"], got["done"], got["phase"]), (True, True, "done"), got)
        self.assertEqual(self.snap(), before, "締めた後の枝の輪は何も動かさない")

    def test_done_lane_before_the_join_ends_without_the_role(self):
        """枝の確かめが done を保存した後、Archon が輪の済みを記録する前に止まった"""
        self.route()
        self.red(UA)
        self.green(UA)
        self.assertEqual(tddlanes.lane_prep(self.state, 1), {"prompt_file": "", "go": False})
        self.assertTrue(tddlanes.lane_step(self.state, 1, None, self.repo)["done"])
        got = tddlanes.join(self.state, self.repo)
        self.assertEqual((got["merged"], got["back"]), (1, 1), "済んだ枝は当て、回らなかった枝は順に戻す")

    def test_join_again_replays_the_first_exit(self):
        first = self.half_join()
        # 順に戻った単位を輪 tdd-rest が進めた後に、締めがもう 1 度呼ばれる
        self.edit(self.repo, "test_b.py", "triple(1), int)\n", "triple(1), int)\n" + B_TEST)
        self.assertTrue(self.step({"phase": "test", "unit_key": UB, "test_files": ["test_b.py"], "tests": [B_ID]})["ok"])
        before = self.snap()
        self.assertEqual(self.join(), first, "同じ出口（Archon が後ろの節の控えを使い続ける）")
        self.assertEqual(self.snap(), before, "盤面の状態と作業ツリーを動かさない")

    def test_join_again_does_not_park_the_claims_again(self):
        """申し出は 1 度目の締めだけが渡す（再生は積まない。resume の前に盤面の周が進んでいても同じ申し出を新しい周に積み増さない）"""
        self.route()
        item = {"phase": "conflict", "unit_key": UA, "between": ["a.py:2", "test_a.py:7"],
                "why_both_cannot_hold": "テストは 1 を足した値を求め、依頼は足さない値を求める", "which_is_right": "request",
                "kind": "brief_vs_judgment"}
        self.assertTrue(self.cmd(UA, item)["done"])
        parked = []
        with mock.patch.object(tddloop.conflict, "problems", return_value=[]):
            first = tddlanes.join(self.state, self.repo, park=parked.append)
        self.assertEqual([c["unit_key"] for c in first["conflicts"]], [UA])
        again = tddlanes.join(self.state, self.repo, park=parked.append)
        self.assertEqual(again["conflicts"], [])
        self.assertEqual([[c["unit_key"] for c in got] for got in parked], [[UA]], "積むのは 1 度だけ")
        self.assertEqual({k: v for k, v in again.items() if k != "conflicts"}, {k: v for k, v in first.items() if k != "conflicts"})

    def test_claims_survive_a_crash_between_save_and_park(self):
        """締めが出口を保存した後、申し出を盤面に積む前に落ちた（積む口が落ちた・殺された）: resume の締めは積んでいない申し出を
        積み直し（1 度だけ）、出口は同じ。積んだ後の再生は積まない"""
        self.route()
        item = {"phase": "conflict", "unit_key": UA, "between": ["a.py:2", "test_a.py:7"],
                "why_both_cannot_hold": "テストは 1 を足した値を求め、依頼は足さない値を求める", "which_is_right": "request",
                "kind": "brief_vs_judgment"}
        self.assertTrue(self.cmd(UA, item)["done"])

        def boom(items):
            raise OSError("盤面に書けない")
        with mock.patch.object(tddloop.conflict, "problems", return_value=[]):
            with self.assertRaises(OSError):
                tddlanes.join(self.state, self.repo, park=boom)
        parked = []
        again = tddlanes.join(self.state, self.repo, park=parked.append)
        self.assertEqual([[c["unit_key"] for c in got] for got in parked], [[UA]], "積んでいない申し出を再生が積む")
        self.assertEqual([c["unit_key"] for c in again["conflicts"]], [UA])
        third = tddlanes.join(self.state, self.repo, park=parked.append)
        self.assertEqual(len(parked), 1, "積んだ後の再生は積まない")
        self.assertEqual(third["conflicts"], [])
        self.assertEqual({k: v for k, v in third.items() if k != "conflicts"}, {k: v for k, v in again.items() if k != "conflicts"})

    def test_scripts_on_resume(self):
        """Archon が resume で起こす形: 役が飛ばされた確かめは reply が null"""
        self.half_join()
        env = {"ARTIFACTS_DIR": str(self.board.parent), "INPUTS_STATE_FILE": self.state}
        values = {"INPUTS_JUDGMENT_FILE": "", "INPUTS_PLAN_FILE": "", "INPUTS_POLICY_PATH": "", "INPUTS_NOTES_FILE": ""}
        code, out, err = run_script("tdd_lane_prep", self.repo, {**env, "INPUTS_LANE": "2", **values})
        self.assertEqual((code, json.loads(out or "{}")), (0, {"prompt_file": "", "go": False}), err)
        for reply in ("null", ""):
            code, out, err = run_script("tdd_lane_step", self.repo, {**env, "INPUTS_LANE": "2", "INPUTS_REPLY": reply})
            self.assertEqual(code, 0, err)
            self.assertIs(json.loads(out)["done"], True)
        outs = [run_script("tdd_join", self.repo, env) for _ in range(2)]
        self.assertEqual([c for c, _, _ in outs], [0, 0], outs)
        self.assertEqual(outs[0][1], outs[1][1])
        self.assertEqual(json.loads(outs[0][1])["back"], 1)

    def test_loop_that_cut_the_lanes_ends_without_the_role(self):
        """輪 tdd-loop の確かめが段 lanes を保存した後、Archon が輪の済みを記録する前に止まった: resume で 1 周目から起きた輪は
        役を起こさずに抜け（状態を動かさない）、後の枝の輪は今どおり起きる"""
        got = self.route()
        self.assertEqual((got["done"], got["phase"]), (True, "lanes"), got)
        before = pathlib.Path(self.state).read_bytes()
        self.assertEqual(tddloop.prep(self.state), {"prompt_file": "", "go": False})
        got = self.step(None)
        self.assertEqual((got["ok"], got["done"], got["phase"]), (True, True, "lanes"), got)
        self.assertEqual(pathlib.Path(self.state).read_bytes(), before)
        self.assertIs(tddlanes.lane_prep(self.state, 1)["go"], True)

    def test_reply_for_a_settled_lane_is_still_refused(self):
        self.half_join()
        with self.assertRaises(tddloop.Broken):
            tddlanes.lane_step(self.state, 2, {"phase": "fix", "unit_key": UB}, self.repo)


if __name__ == "__main__":
    unittest.main()
