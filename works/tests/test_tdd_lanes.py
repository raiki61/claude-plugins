"""TDD の輪の単位を、範囲の重ならない物だけ単位の worktree で並べる（blk-fix の tddlanes。設計 docs/plans/2026-10-06-tdd-parallel.md）の検査。

- 分け方: 形 g3 の輪で、振り分けの後に範囲（tddlanes.ranges。試験では差し替え）の重ならない tdd の単位が 2 つ以上なら、単位の
  worktree を run ごとの置き場の下に切って段 lanes へ進む。2 つ未満・形 af・範囲の引けない単位は今どおり順
- 段のコマンド（tddlanes.run）: 単位の worktree で tddloop の段の確かめをそのまま回す（赤・緑・凍結は機械）。共通の .git の
  objects を書かない（試験は objects を読み取りだけにして走らせる）
- 締める（lanes の段の tdd-step）: 緑まで済んだ単位の差分を当て、当てた後の木で緑をもう 1 度確かめる。済まなかった単位・当たら
  ない単位・当てた後に赤い単位は、順の単位として最初の段から回し直す。direct への渡しと食い違いの申し出は今どおり
- 支度: lanes の段のまとめ役の指示書と、単位ごとの下請けのファイル（段のコマンドの 1 行・worktree・3 段の約束）
"""
import json
import os
import pathlib
import stat
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
import fixshape  # noqa: E402
import tddlanes  # noqa: E402
import tddloop  # noqa: E402
import unittrees  # noqa: E402
from test_blk_fix_tdd import SUITE  # noqa: E402

UA = "a.py double: x + x + 1 を返す"
UB = "b.py triple: x * 3 + 1 を返す"
SEED = {
    "a.py": "def double(x):\n    return x + x + 1\n",
    "b.py": "from a import double\n\n\ndef triple(x):\n    return x * 3 + 1\n",
    "c.py": "SHARED = 1\n",
    "test_a.py": "import unittest\nfrom a import double\n\n\nclass TestA(unittest.TestCase):\n    def test_zero(self):\n"
                 "        self.assertIsInstance(double(1), int)\n",
    "test_b.py": "import unittest\nfrom b import triple\n\n\nclass TestB(unittest.TestCase):\n    def test_zero(self):\n"
                 "        self.assertIsInstance(triple(1), int)\n",
}
A_TEST = "\n    def test_two(self):\n        self.assertEqual(double(2), 4)\n"
B_TEST = "\n    def test_two(self):\n        self.assertEqual(triple(2), 6)\n"
A_ID, B_ID = "test_a.py::TestA::test_two", "test_b.py::TestB::test_two"
RANGES = {UA: ["a.py", "test_a.py"], UB: ["b.py", "test_b.py"]}


class LaneCase(unittest.TestCase):
    """2 つの単位（a.py と b.py。範囲が重ならない）を持つ種と小さな実行器で、形 g3 の輪を回す"""
    SHAPE = "g3"

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
        p = self.board / fixshape.START_REL
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({fixshape.KEY: self.SHAPE}), encoding="utf-8")
        self.start = tddloop.start(self.board, self.repo, str(self.suite), json.dumps([UA, UB], ensure_ascii=False))
        self.assertTrue(self.start["go"], self.start)
        self.state = self.start["state_file"]
        patch = mock.patch.object(tddlanes, "ranges", side_effect=lambda board_dir, keys: {k: RANGES.get(k) for k in keys})
        patch.start()
        self.addCleanup(patch.stop)

    def st(self):
        return json.loads(pathlib.Path(self.state).read_text(encoding="utf-8"))

    def step(self, reply):
        return tddloop.step(self.state, reply, self.repo)

    def route(self):
        got = self.step({"phase": "route", "units": [{"unit_key": UA, "route": "tdd"}, {"unit_key": UB, "route": "tdd"}]})
        self.assertTrue(got["ok"], got)
        return got

    def lane(self, key):
        return next(r for r in self.st()["lanes"]["rows"] if r["unit_key"] == key)

    def edit(self, root, name, old, new):
        p = pathlib.Path(root) / name
        text = p.read_text(encoding="utf-8")
        self.assertIn(old, text)
        p.write_text(text.replace(old, new, 1), encoding="utf-8")

    def cmd(self, key, reply):
        """段のコマンドを 1 回（下請けの代わり）。返答は単位の置き場の reply.json に書いて渡す"""
        row = self.lane(key)
        path = pathlib.Path(row["reply"])
        path.write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        return tddlanes.run(self.st()["lanes"]["manifest"], row["n"], str(path))

    def red(self, key):
        tree = self.lane(key)["tree"]
        name, body, tid = ("test_a.py", A_TEST, A_ID) if key == UA else ("test_b.py", B_TEST, B_ID)
        (pathlib.Path(tree) / name).write_text((pathlib.Path(tree) / name).read_text(encoding="utf-8") + body, encoding="utf-8")
        got = self.cmd(key, {"phase": "test", "unit_key": key, "test_files": [name], "tests": [tid]})
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["phase"], "fix")
        return got

    def green(self, key, new=None):
        tree = self.lane(key)["tree"]
        if key == UA:
            self.edit(tree, "a.py", "x + x + 1", new or "x + x")
        else:
            self.edit(tree, "b.py", "x * 3 + 1", new or "x * 3")
        got = self.cmd(key, {"phase": "fix", "unit_key": key, "files": ["a.py" if key == UA else "b.py"], "what": "余計な 1 を消した"})
        self.assertTrue(got["ok"], got)
        self.assertTrue(got["done"], got)
        return got


class TestPlan(LaneCase):
    def test_route_plants_lanes_for_disjoint_units(self):
        got = self.route()
        self.assertEqual(got["phase"], "lanes")
        st = self.st()
        rows = st["lanes"]["rows"]
        self.assertEqual([r["unit_key"] for r in rows], [UA, UB])
        place = pathlib.Path(self.board).parent / "run-place"
        for r in rows:
            self.assertTrue(pathlib.Path(r["tree"]).is_dir())
            self.assertTrue(str(pathlib.Path(r["tree"]).resolve()).startswith(str(place.resolve())), r)
            self.assertEqual((pathlib.Path(r["tree"]) / "a.py").read_text(encoding="utf-8"), SEED["a.py"])
        manifest = pathlib.Path(st["lanes"]["manifest"])
        self.assertEqual(manifest.parent, pathlib.Path(st["work"]), "目録は盤面の tdd-<k>/ の下（共有の記録 tdd-*/**）")

    def test_overlapping_units_stay_serial(self):
        with mock.patch.object(tddlanes, "ranges", return_value={UA: ["a.py", "c.py"], UB: ["b.py", "c.py"]}):
            got = self.route()
        self.assertEqual(got["phase"], "test")
        self.assertNotIn("lanes", self.st())

    def test_unit_without_range_stays_serial(self):
        with mock.patch.object(tddlanes, "ranges", return_value={UA: ["a.py"], UB: None}):
            got = self.route()
        self.assertEqual(got["phase"], "test")

    def test_direct_units_are_not_planted(self):
        got = self.step({"phase": "route", "units": [{"unit_key": UA, "route": "tdd"},
                                                     {"unit_key": UB, "route": "direct", "why": "文書の直しで先にテストを書けない"}]})
        self.assertEqual(got["phase"], "test", "tdd の単位が 1 つなら並べない")


class TestAfStaysSerial(LaneCase):
    SHAPE = "af"

    def test_af_never_plants(self):
        got = self.route()
        self.assertEqual(got["phase"], "test")
        self.assertFalse(self.st()["lanes_on"])


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

    def test_command_does_not_write_common_objects(self):
        """sandbox は共通の .git を書かせない: objects を読み取りだけにしても、コマンドは単位の置き場に object を書いて回る"""
        self.route()
        objects = pathlib.Path(git(self.repo, "rev-parse", "--path-format=absolute", "--git-common-dir")) / "objects"
        dirs = [objects, *(p for p in objects.rglob("*") if p.is_dir())]
        modes = {d: d.stat().st_mode for d in dirs}
        for d in dirs:
            d.chmod(modes[d] & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
        try:
            self.red(UA)
            self.green(UA)
        finally:
            for d in dirs:
                d.chmod(modes[d])
        self.assertNotIn("GIT_OBJECT_DIRECTORY", os.environ, "コマンドは自分の env を元に戻す")

    def test_command_line_runs_as_script(self):
        """下請けが Bash で走らせる 1 行（支度の python の絶対パス）。ARTIFACTS_DIR の無い env で動く"""
        self.route()
        row = self.lane(UA)
        tree = pathlib.Path(row["tree"])
        (tree / "test_a.py").write_text(SEED["test_a.py"] + A_TEST, encoding="utf-8")
        pathlib.Path(row["reply"]).write_text(json.dumps({"phase": "test", "unit_key": UA, "test_files": ["test_a.py"],
                                                          "tests": [A_ID]}), encoding="utf-8")
        line = tddlanes.command_line(self.st()["lanes"]["manifest"], row["n"], row["reply"])
        env = {k: v for k, v in os.environ.items() if k != "ARTIFACTS_DIR"}
        r = subprocess.run(line, shell=True, capture_output=True, text=True, encoding="utf-8", env=env, cwd=str(tree))
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual((got["ok"], got["phase"]), (True, "fix"), got)

    def test_broken_git_line_refused(self):
        self.route()
        tree = pathlib.Path(self.lane(UA)["tree"])
        (tree / ".git").write_text("gitdir: /elsewhere\n", encoding="utf-8")
        with self.assertRaises(tddlanes.LaneBroken):
            self.cmd(UA, {"phase": "test", "unit_key": UA, "test_files": ["test_a.py"], "tests": [A_ID]})


class TestSettle(LaneCase):
    def test_both_green_are_applied_and_checked_again(self):
        self.route()
        for k in (UA, UB):
            self.red(k)
            self.green(k)
        trees = [r["tree"] for r in self.st()["lanes"]["rows"]]
        got = self.step({"phase": "lanes"})
        self.assertEqual((got["ok"], got["done"]), (True, True), got)
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
        self.assertTrue(ex["lanes"]["calls"], "段のコマンドの呼びは出口の lanes.calls に")
        self.assertEqual([c["phase"] for c in ex["calls"]], ["route", "lanes"], "calls は tdd の節の起動 1 回に 1 行のまま")

    def test_unfinished_lane_goes_back_to_serial(self):
        self.route()
        self.red(UA)
        self.green(UA)
        self.red(UB)   # 直しの段の前で止まった下請け
        got = self.step({"phase": "lanes"})
        self.assertEqual((got["ok"], got["done"], got["phase"]), (True, False, "test"))
        st = self.st()
        self.assertEqual(st["queue"][st["cur"]], UB)
        self.assertEqual(st["units"][UB]["red"], "", "戻した単位は最初の段から")
        self.assertEqual((self.repo / "test_b.py").read_text(encoding="utf-8"), SEED["test_b.py"], "済まなかった単位は当てない")
        self.assertEqual((self.repo / "a.py").read_text(encoding="utf-8"), "def double(x):\n    return x + x\n")
        prompt = pathlib.Path(tddloop.prep(self.state)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("並べで済まなかった", prompt)
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
        got = self.step({"phase": "lanes"})
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
        got = self.step({"phase": "lanes"})
        self.assertEqual((got["done"], got["phase"]), (False, "test"))
        st = self.st()
        self.assertEqual(st["queue"], [UA, UB])
        for name in ("a.py", "b.py", "test_a.py", "test_b.py"):
            self.assertEqual((self.repo / name).read_text(encoding="utf-8"), SEED[name], name)
        self.assertIn("当てた後", st["lanes"]["back"][UA]["why"])

    def test_direct_why_in_lane_is_direct(self):
        self.route()
        got = self.cmd(UA, {"phase": "test", "unit_key": UA, "direct_why": "設定だけの直しで先にテストを書けない"})
        self.assertTrue(got["done"], got)
        self.red(UB)
        self.green(UB)
        got = self.step({"phase": "lanes"})
        self.assertTrue(got["done"], got)
        u = self.st()["units"][UA]
        self.assertEqual((u["route"], u["gave_up"]), ("direct", "writer"))

    def test_stray_write_of_run_tree_is_reverted(self):
        self.route()
        (self.repo / "c.py").write_text("SHARED = 9\n", encoding="utf-8")   # まとめ役が run の作業ツリーを書いた
        got = self.step({"phase": "lanes"})
        self.assertTrue(got["ok"], got)
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
            got = self.step({"phase": "lanes"})
        self.assertEqual(pr.call_args.kwargs["owed"], {UA})
        self.assertEqual([c["unit_key"] for c in got["conflicts"]], [UA])
        st = self.st()
        self.assertIn(UA, st["parked"])
        self.assertEqual(st["units"][UA]["route"], "parked")

    def test_lane_conflict_that_fails_check_goes_back(self):
        self.route()
        self.cmd(UA, {"phase": "conflict", "unit_key": UA, "between": ["nope.py:1", "nope.py:2"],
                      "why_both_cannot_hold": "名指しが在らない申し出", "which_is_right": "request", "kind": "brief_vs_judgment"})
        got = self.step({"phase": "lanes"})
        self.assertEqual(got["conflicts"], [])
        st = self.st()
        self.assertEqual(st["queue"][st["cur"]], UA)


class TestPrep(LaneCase):
    def test_lanes_prompt_and_unit_files(self):
        self.route()
        out = tddloop.prep(self.state, repo=self.repo)
        text = pathlib.Path(out["prompt_file"]).read_text(encoding="utf-8")
        st = self.st()
        self.assertIn("段 lanes", text)
        self.assertIn("Agent", text)
        self.assertIn('{"phase": "lanes"}', text)
        for r in st["lanes"]["rows"]:
            self.assertIn(r["file"], text)
            sub = pathlib.Path(r["file"]).read_text(encoding="utf-8")
            self.assertEqual(pathlib.Path(r["file"]).parent, pathlib.Path(st["work"]))
            for w in (r["unit_key"], r["tree"], tddlanes.command_line(st["lanes"]["manifest"], r["n"], r["reply"]),
                      "**test**", "**fix**", "**refactor**"):
                self.assertIn(w, sub)
        key = pathlib.Path(tddloop.adapter.session_key_path(str(self.board), tddloop.UNIT_NODE)).read_text(encoding="utf-8")
        self.assertEqual(key.strip(), f"{pathlib.Path(st['work']).name}:lanes", "まとめ役は新しい会話で")


if __name__ == "__main__":
    unittest.main()
