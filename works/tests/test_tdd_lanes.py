"""TDD の輪の単位を、枝ごとの単位の worktree で並べる（blk-fix の tddlanes。設計 docs/plans/2026-10-06-tdd-parallel.md・
docs/plans/2026-10-07-overlap-lanes.md）の検査。

- 分け方: 形 g3 の輪で、振り分けの後に範囲（tddlanes.ranges。試験では差し替え）の引ける tdd の枝（修正案の項目を共にする単位の組。
  tddlanes.items_of も差し替え）が 2 本以上なら、枝の worktree を run ごとの置き場の下に切って段 lanes へ進む。範囲が重なっても並べる。
  2 本未満・形 af・範囲の引けない単位は今どおり順
- 枝の中: 単位は順に、単位ごとに新しい下請け。段のコマンドは枝の今の単位でない番の下請けには段を回さず、単位が済むと次の単位の
  頭を控えに残して引き継ぎのファイルを書く
- 重なり: 2 本の枝が同じファイルの別の行を変える → 両方当たる（shared）。同じ試験のファイルの末尾に足す → 先の枝の行の後に後の
  枝の行を置いて当たる（union）。字では合うが合わせた木で赤 → 後の枝だけ戻す（semantic）
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
    """2 つの単位（a.py と b.py。範囲が重ならない）を持つ種と小さな実行器で、形 g3 の輪を回す"""
    SHAPE = "g3"
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
        p = self.board / fixshape.START_REL
        p.parent.mkdir(parents=True)
        p.write_text(json.dumps({fixshape.KEY: self.SHAPE}), encoding="utf-8")
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
        """段のコマンドを 1 回（下請けの代わり。枝の中のその単位の番で）。返答は単位の置き場の reply.json に書いて渡す"""
        row = self.lane(key)
        path = pathlib.Path(row["reply"])
        path.write_text(json.dumps(reply, ensure_ascii=False), encoding="utf-8")
        return tddlanes.run(self.st()["lanes"]["manifest"], row["n"], str(path), row["unit_keys"].index(key) + 1)

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
        self.assertTrue(got["done"], got)
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

    def test_groups_join_units_through_items(self):
        got = tddlanes.groups(["u1", "u2", "u3", "u4"], {"u1": [1], "u2": [2], "u3": [1, 3], "u4": [3]})
        self.assertEqual(got, [["u1", "u3", "u4"], ["u2"]])
        self.assertEqual(tddlanes.groups(["u1", "u2"], {}), [["u1"], ["u2"]], "項目に無い単位は 1 単位 1 枝")

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


class TestLanesSwitchedOff(LaneCase):
    """入力 tdd_lanes が off（線の features_off の tdd_lanes）なら、形 g3 で枝が 2 本在っても並べの周へ進まず順に回す"""
    LANES = "off"

    def test_off_never_plants(self):
        self.assertFalse(self.st()["lanes_on"])
        got = self.route()
        self.assertEqual(got["phase"], "test")


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
        line = tddlanes.command_line(self.st()["lanes"]["manifest"], row["n"], row["reply"], 1)
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
        prompt = pathlib.Path(tddloop.prep(self.state, lanes=tddlanes)["prompt_file"]).read_text(encoding="utf-8")
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
        got = self.step({"phase": "lanes"})
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


class TestOneItemLane(LaneCase):
    """項目を共にする 2 単位（b.py と d.py）の枝と、1 単位（a.py）の枝。枝の中は順に、単位ごとに新しい下請け"""
    UNITS = (UA, UB, UD)
    ITEMS = {UA: [1], UB: [2], UD: [2]}

    def test_lane_runs_its_units_in_turn_with_a_handoff(self):
        self.route()
        st = self.st()
        self.assertEqual([r["unit_keys"] for r in st["lanes"]["rows"]], [[UA], [UB, UD]])
        early = self.cmd(UD, {"phase": "test", "unit_key": UD, "test_files": ["test_d.py"], "tests": [D_ID]})
        self.assertEqual((early["ok"], early["done"]), (False, True))
        self.assertEqual(early["reason"], tddlanes.NOT_YET, "前の単位が済む前の番の下請けには段を回さない")
        self.red(UB)
        got = self.green(UB)
        self.assertEqual(got["phase"], "done", "単位が済んだら、その下請けは終わる（次の単位は別の下請け）")
        row = self.lane(UB)
        hand = pathlib.Path(row["state"]).parent / tddlanes.HANDOFF.format(j=2)
        self.assertIn(UB, hand.read_text(encoding="utf-8"), "次の単位への引き継ぎを機械が書く")
        lst = json.loads(pathlib.Path(row["state"]).read_text(encoding="utf-8"))
        self.assertEqual(sorted(lst["unit_heads"]), sorted([UB, UD]), "単位ごとの頭の木を控えに残す")
        late = self.cmd(UB, {"phase": "test", "unit_key": UB, "test_files": ["test_b.py"], "tests": [B_ID]})
        self.assertEqual(late["reason"], tddlanes.PASSED, "済んだ番の下請けには段を回さない")
        self.red(UD)
        self.green(UD)
        self.red(UA)
        self.green(UA)
        got = self.step({"phase": "lanes"})
        self.assertEqual((got["ok"], got["done"]), (True, True), got)
        for name, text in (("a.py", "x + x\n"), ("b.py", "x * 3\n"), ("d.py", "x * 4\n")):
            self.assertIn(text, (self.repo / name).read_text(encoding="utf-8"), name)
        st = self.st()
        self.assertEqual({r["unit_key"]: (r["outcome"], r["lane"]) for r in st["lanes"]["out"]},
                         {UA: ("merged", 1), UB: ("merged", 2), UD: ("merged", 2)})
        self.assertEqual(st["units"][UD]["green"], "ok")

    def test_unit_files_name_the_handoff_for_later_units(self):
        self.route()
        tddloop.prep(self.state, repo=self.repo, lanes=tddlanes)
        st = self.st()
        row = self.lane(UD)
        self.assertEqual(len(row["files"]), 2)
        second = pathlib.Path(row["files"][1]).read_text(encoding="utf-8")
        hand = pathlib.Path(row["state"]).parent / tddlanes.HANDOFF.format(j=2)
        self.assertIn(str(hand), second)
        self.assertIn(tddlanes.command_line(st["lanes"]["manifest"], row["n"], row["reply"], 2), second)
        prompt = (pathlib.Path(st["work"]) / tddloop.PROMPT).read_text(encoding="utf-8")
        for f in row["files"]:
            self.assertIn(f, prompt)

    def test_unfinished_second_unit_is_not_merged(self):
        self.route()
        self.red(UB)
        self.green(UB)
        self.red(UD)   # 2 番目の単位は直しの前で止まった（書きかけのテストを当てない）
        self.red(UA)
        self.green(UA)
        got = self.step({"phase": "lanes"})
        st = self.st()
        self.assertEqual(st["queue"][st["cur"]], UD)
        self.assertIn("x * 3\n", (self.repo / "b.py").read_text(encoding="utf-8"), "済んだ 1 番目の単位は当てる")
        self.assertEqual((self.repo / "test_d.py").read_text(encoding="utf-8"), SEED["test_d.py"])
        self.assertEqual(got["phase"], "test")


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
        got = self.step({"phase": "lanes"})
        self.assertEqual((got["ok"], got["done"]), (True, True), got)
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
        got = self.step({"phase": "lanes"})
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
        got = self.step({"phase": "lanes"})
        self.assertEqual((got["ok"], got["done"]), (True, True), got)
        text = (self.repo / "test_ab.py").read_text(encoding="utf-8")
        self.assertLess(text.index("class TestA2"), text.index("class TestB2"), "先の枝の行の後に後の枝の行")
        st = self.st()
        self.assertEqual({r["unit_key"]: r["merge"] for r in st["lanes"]["out"]}, {UA: "clean", UB: "union"})


class TestPrep(LaneCase):
    def test_lanes_prompt_and_unit_files(self):
        self.route()
        out = tddloop.prep(self.state, repo=self.repo, lanes=tddlanes)
        text = pathlib.Path(out["prompt_file"]).read_text(encoding="utf-8")
        st = self.st()
        self.assertIn("段 lanes", text)
        self.assertIn("Agent", text)
        self.assertIn('{"phase": "lanes"}', text)
        self.assertIn(tddloop.LANE_ROUNDS, text)
        for r in st["lanes"]["rows"]:
            f = r["files"][0]
            self.assertIn(f, text)
            sub = pathlib.Path(f).read_text(encoding="utf-8")
            self.assertEqual(pathlib.Path(f).parent, pathlib.Path(st["work"]))
            for w in (r["unit_keys"][0], r["tree"], tddlanes.command_line(st["lanes"]["manifest"], r["n"], r["reply"], 1),
                      "**test**", "**fix**", "**refactor**"):
                self.assertIn(w, sub)
            self.assertNotIn("前の単位の引き継ぎ", sub, "枝の 1 番目の単位に引き継ぎは無い")
        key = pathlib.Path(tddloop.adapter.session_key_path(str(self.board), tddloop.UNIT_NODE)).read_text(encoding="utf-8")
        self.assertEqual(key.strip(), f"{pathlib.Path(st['work']).name}:lanes", "まとめ役は新しい会話で")


    def test_lanes_phase_needs_the_lane_hooks(self):
        """tddlanes が tddloop を import するので、並べの口は節の script が渡す。渡されない段 lanes は Broken（黙って順にしない）"""
        self.route()
        with self.assertRaises(tddloop.Broken):
            tddloop.prep(self.state)
        with self.assertRaises(tddloop.Broken):
            tddloop.step(self.state, {"phase": "lanes"}, self.repo)

    def test_route_without_hooks_stays_serial(self):
        got = tddloop.step(self.state, {"phase": "route", "units": [{"unit_key": UA, "route": "tdd"},
                                                                    {"unit_key": UB, "route": "tdd"}]}, self.repo)
        self.assertEqual(got["phase"], "test")


if __name__ == "__main__":
    unittest.main()
