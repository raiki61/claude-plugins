"""並べの枝の部品（blk-fix/lib/lanekit.py）の純粋な口の検査。TDD の輪の並べ（tddlanes）と修正役の並べ（fixlanes）が同じ形で
使う物は lanekit に 1 つだけ在る（計画 docs/plans/2026-10-09-lanes-home.md）。

縛る事:
- node_names(pattern): 枝の役の節の名を 1..MAX_LANES で
- groups(rows): タグを共にする物どうしを 1 組に（つながりは推移的・組の中と組の並びは rows の順・タグの無い物は 1 つで 1 組）
- relocate(path, repo, tree): run の作業ツリーの中のパスは単位の worktree の同じ所へ、外のパスはそのまま
- tree_ok(row): 行の tree の `.git` の 1 行が行の git と同じなら空、違う・git が空なら理由
- merge_in_order(lanes, merge_one): 枝を順に当て、前に当てた枝の差分のパスを後の枝の earlier に渡す（当てなかった枝のパスは渡さない）
- 締めの結末の語 JOINED・MERGED・BACK と、段の別名が同じ物
- 枝の数の写し: core の表（包み adapter.KEYED_NODES・座 seat.SEATS・SKILL_NODES・AGENT_NODES・模型の表 stage-models.json）が
  並べる枝の節の名は、ちょうど段の lane_nodes()（と範囲の相談の答えの節 fixlanes.ANSWER_NODE）。core はブロックを読めないので字で
  並べ、ここが lanekit.MAX_LANES と縛る（YAML の枝の輪は test_tdd_lane_wiring・test_fix_lane_wiring が縛る）
"""
import json
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / "blk-fix" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import adapter  # noqa: E402
import fixlanes  # noqa: E402
import lanekit  # noqa: E402
import seat  # noqa: E402
import tddlanes  # noqa: E402

LANE = re.compile(r"-lane-\d+$")


class Names(unittest.TestCase):
    def test_node_names(self):
        self.assertEqual(lanekit.node_names("x-lane-{n}"), [f"x-lane-{n}" for n in range(1, lanekit.MAX_LANES + 1)])

    def test_stage_names_come_from_kit(self):
        self.assertEqual(tddlanes.lane_nodes(), lanekit.node_names(tddlanes.LANE_NODE))
        self.assertEqual(fixlanes.lane_nodes(), lanekit.node_names(fixlanes.LANE_NODE))

    def test_outcome_words(self):
        self.assertEqual((lanekit.JOINED, lanekit.MERGED, lanekit.BACK), ("joined", "merged", "serial"))
        for mod in (tddlanes, fixlanes):
            self.assertEqual((mod.JOINED, mod.MERGED, mod.BACK), (lanekit.JOINED, lanekit.MERGED, lanekit.BACK), mod.__name__)


class Groups(unittest.TestCase):
    def test_transitive_and_ordered(self):
        got = lanekit.groups([(1, ["a"]), (2, ["b"]), (3, ["a", "c"]), (4, ["c"]), (5, ["d"])])
        self.assertEqual(got, [[1, 3, 4], [2], [5]])

    def test_untagged_alone(self):
        self.assertEqual(lanekit.groups([("u1", []), ("u2", None), ("u3", [7])]), [["u1"], ["u2"], ["u3"]])

    def test_later_link_joins_earlier_groups(self):
        self.assertEqual(lanekit.groups([("p", [1]), ("q", [2]), ("r", [1, 2])]), [["p", "q", "r"]])

    def test_empty(self):
        self.assertEqual(lanekit.groups([]), [])


class Relocate(unittest.TestCase):
    def test_inside_moves_to_tree(self):
        self.assertEqual(lanekit.relocate("/r/repo/bin/run", "/r/repo", "/t/item-1"), pathlib.Path("/t/item-1/bin/run"))

    def test_outside_stays(self):
        self.assertEqual(lanekit.relocate("/usr/bin/python3", "/r/repo", "/t/item-1"), pathlib.Path("/usr/bin/python3"))


class TreeOk(unittest.TestCase):
    def test_same_line(self):
        with tempfile.TemporaryDirectory() as d:
            (pathlib.Path(d) / ".git").write_text("gitdir: /x/wt/item-1\n", encoding="utf-8")
            self.assertEqual(lanekit.tree_ok({"tree": d, "git": "gitdir: /x/wt/item-1"}), "")
            self.assertIn(d, lanekit.tree_ok({"tree": d, "git": "gitdir: /x/wt/item-2"}))
            self.assertTrue(lanekit.tree_ok({"tree": d}), "切った時の git の 1 行が無い行は通さない")


class MergeInOrder(unittest.TestCase):
    def test_earlier_grows_only_with_applied(self):
        seen = []

        def one(lane, earlier):
            seen.append((lane, set(earlier)))
            if lane == "b":
                return lanekit.Merge("当たらない", "b.patch", [], [], True)
            return lanekit.Merge("", f"{lane}.patch", [f"{lane}.py", "shared.py"], [], False)
        got = lanekit.merge_in_order(["a", "b", "c"], one)
        self.assertEqual(seen, [("a", set()), ("b", {"a.py", "shared.py"}), ("c", {"a.py", "shared.py"})])
        self.assertEqual([(lane, m.why) for lane, m in got], [("a", ""), ("b", "当たらない"), ("c", "")])


class CopiesOfTheCount(unittest.TestCase):
    """core の表が字で並べる枝の節の名が、ちょうど段の名（MAX_LANES 本）"""

    def lanes(self, names):
        return {n for n in names if LANE.search(n)}

    def test_core_tables(self):
        tdd, fix = set(tddlanes.lane_nodes()), set(fixlanes.lane_nodes())
        self.assertEqual(self.lanes(adapter.KEYED_NODES), tdd | fix)
        self.assertEqual(self.lanes(seat.SEATS), tdd)
        self.assertEqual(self.lanes(seat.SKILL_NODES), tdd)
        self.assertEqual(self.lanes(seat.AGENT_NODES), fix)

    def test_stage_models(self):
        doc = json.loads((ROOT / ".shared" / "core" / "stage-models.json").read_text(encoding="utf-8"))
        answers = set(lanekit.node_names(fixlanes.ANSWER_NODE))
        want = {f"blk-fix/{n}" for n in {*tddlanes.lane_nodes(), *fixlanes.lane_nodes(), *answers}}
        self.assertEqual(self.lanes(doc["stages"]), want)


# 枝の数を変えて blk-fix の受け手の表 RECEIVES を組み直し、枝の役ごとの受ける節（の 1 行目）を JSON で出す（別のプロセスで。
# 変えた数を試験の外に漏らさない。表の読み口は core の graphmap.receive_rows）
_RECEIVES_AT = """
import json, pathlib, sys
pack = pathlib.Path(sys.argv[1])
sys.dont_write_bytecode = True
sys.path[:0] = [str(pack / "blk-fix" / "lib"), str(pack / ".shared" / "core")]
import graphmap, lanekit, yaml
lanekit.MAX_LANES = int(sys.argv[2])
got = {}
for _, workflow, r in graphmap.receive_rows(pack, yaml.safe_load):
    if workflow == "blk-fix":
        got.setdefault(r.role, set()).add(str(r.section).splitlines()[0])
print(json.dumps({k: sorted(v) for k, v in got.items()}))
"""


class ReceivesFollowTheCount(unittest.TestCase):
    """受け手の表 RECEIVES の枝の役の行は、枝の数（lanekit.MAX_LANES）に付いて増える。枝 1 と同じ節を、枝 1..MAX_LANES のどれもが受ける
    （枝の役の名を字で並べると、数を増やした時に増えた枝の受け手の行が無いまま残る）"""

    def test_every_lane_receives_what_lane_one_does(self):
        n = lanekit.MAX_LANES + 1
        out = subprocess.run([sys.executable, "-c", _RECEIVES_AT, str(ROOT), str(n)],
                             capture_output=True, text=True, check=True).stdout
        got = json.loads(out)
        for pattern in (tddlanes.LANE_NODE, fixlanes.LANE_NODE, fixlanes.ANSWER_NODE):
            first = got.get(pattern.format(n=1))
            self.assertTrue(first, f"{pattern.format(n=1)} の受け手の行が無い")
            for k in range(2, n + 1):
                role = pattern.format(n=k)
                self.assertEqual(got.get(role), first, f"枝の数 {n} で {role} が枝 1 と同じ節を受けない")


class Queue(unittest.TestCase):
    """待ちの列: 最初の枝に入らなかった組を盤面に置き、空いた枝が錠の中で 1 組ずつ取る（組は割らない・同じ組を 2 本の枝が取らない）"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = pathlib.Path(self._tmp.name) / "queue.json"

    def test_take_gives_whole_groups_in_order(self):
        lanekit.queue_put(self.path, [["u4", "u5"], ["u6"]])
        self.assertEqual(lanekit.take(self.path, 2), ["u4", "u5"], "組は割らずに 1 本の枝へ")
        self.assertEqual(lanekit.take(self.path, 1), ["u6"])
        self.assertEqual(lanekit.take(self.path, 3), [], "列が空なら何も取らない")
        self.assertEqual((lanekit.taken(self.path, 2), lanekit.taken(self.path, 1), lanekit.taken(self.path, 3)),
                         (["u4", "u5"], ["u6"], []))
        self.assertEqual(lanekit.pending(self.path), [])

    def test_take_skips_groups_that_do_not_fit(self):
        lanekit.queue_put(self.path, [[4, 5, 6], [7]])
        self.assertEqual(lanekit.take(self.path, 1, fits=lambda g: len(g) <= 1), [7], "入らない組は列に残し、次の組を取る")
        self.assertEqual(lanekit.pending(self.path), [[4, 5, 6]])
        self.assertEqual(lanekit.take(self.path, 1, fits=lambda g: len(g) <= 1), [])

    def test_take_waits_for_the_lock(self):
        """同時に走る枝の確かめの節（別のプロセス）が同じ組を取らない: 取りは列の錠の中で読み・書きする"""
        import fcntl
        import threading
        lanekit.queue_put(self.path, [["u4"]])
        got = []
        with open(lanekit.queue_lock(self.path), "a", encoding="utf-8") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            t = threading.Thread(target=lambda: got.append(lanekit.take(self.path, 1)))
            t.start()
            t.join(0.3)
            self.assertTrue(t.is_alive(), "錠を持つ者が居る間は取らない")
            fcntl.flock(lock, fcntl.LOCK_UN)
        t.join()
        self.assertEqual(got, [["u4"]])

    def test_no_group_is_taken_twice(self):
        """別のプロセス 3 本が同じ列を空になるまで取り合っても、どの組もちょうど 1 本の枝が取る"""
        lanekit.queue_put(self.path, [[i] for i in range(60)])
        drain = ("import sys; sys.path[:0] = sys.argv[3:]; import lanekit\n"
                 "while lanekit.take(sys.argv[1], sys.argv[2]):\n    pass\n")
        lib = [str(ROOT / "blk-fix" / "lib"), str(ROOT / ".shared" / "core")]
        procs = [subprocess.Popen([sys.executable, "-B", "-c", drain, str(self.path), str(n), *lib]) for n in (1, 2, 3)]
        self.assertEqual([p.wait() for p in procs], [0, 0, 0])
        got = [i for n in (1, 2, 3) for i in lanekit.taken(self.path, n)]
        self.assertEqual(sorted(got), list(range(60)), "どの組もちょうど 1 本の枝が取る")


class ForkOut(unittest.TestCase):
    def test_empty_matches_stage_fork(self):
        self.assertEqual(tddlanes.fork(""), lanekit.fork_out([]))

    def test_empty_refused_when_asked(self):
        """切った枝の在るはずの周（TDD の段が lanes）は空の目録を拒む。文は連番でない時と同じ 1 つ"""
        with self.assertRaisesRegex(ValueError, r"枝の番号が 1\.\.\d+ の連番でない（\[\]）"):
            lanekit.fork_out([], empty_ok=False)
        self.assertEqual(lanekit.fork_out([1], empty_ok=False)["go"], True)


if __name__ == "__main__":
    unittest.main()
