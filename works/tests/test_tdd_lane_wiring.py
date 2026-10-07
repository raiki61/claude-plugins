"""TDD の輪の並べを Archon の節で回す配線（blk-fix の tdd-fork・tdd-lane-loop-<n>・tdd-join・tdd-rest-loop。
docs/plans/2026-10-07-lane-nodes.md）。YAML と筋書きと状態の JSON を読むだけ（git・子のプロセスなし）。

- 枝の輪は tddlanes.MAX_LANES 本で、どれも tdd-fork だけに依り、when: で lane_<n> を読む。枝の輪の層（Archon の層＝依る節の
  深さ）には枝の輪のほかの節を置かない（mutates_checkout: false の節が混ざると Archon v0.11.1 は層を順に回す）
- 輪 tdd-loop は done で抜ける（並べの枝を切った周も tdd-step が done を立てる。phase は lanes）。tdd-join は all_done で枝の輪の全部を待ち、tdd-fork の go を読む。順の輪
  tdd-rest-loop は tdd-join の go を読み、tdd-loop と同じ支度・確かめを使う
- 枝の役は印 works-node: tdd-lane-<n> lane・code_writer の模型・Agent を持たない・返答の形は tdd の形から振り分けを除いた物
- tdd-fork（tddlanes.fork）は段 lanes の状態でだけ go
- 盤面に置く新しいファイル（目録・単位の決まりのファイル・回ごとの指示書・戻した差分）は共有の記録 tdd-*/** に当たる
"""
import json
import pathlib
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-fix"
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(BLK / "lib"))
sys.path.insert(0, str(CORE))

import fixrules  # noqa: E402
import fixshape  # noqa: E402
import scopes  # noqa: E402
import seat  # noqa: E402
import tddlanes  # noqa: E402
import tddloop  # noqa: E402

QUIET = "mutates_checkout"


def block():
    return yaml.safe_load((BLK / "blk-fix.yaml").read_text(encoding="utf-8"))


def top(nid):
    return next(n for n in block()["nodes"] if n["id"] == nid)


def inner(loop, nid):
    return next(n for n in top(loop)["loop_group"]["nodes"] if n["id"] == nid)


def layers(nodes) -> dict:
    """節 → 層（依る節の層の最大 + 1。依らない節は 0）。Archon の層の切り方と同じ（同じ層の節は同時に起きうる）"""
    by = {n["id"]: n for n in nodes}
    out = {}

    def depth(nid):
        if nid not in out:
            out[nid] = 1 + max((depth(d) for d in by[nid].get("depends_on") or []), default=-1)
        return out[nid]
    for nid in by:
        depth(nid)
    return out


class TestWiring(unittest.TestCase):
    def test_lane_loops_follow_the_fork_only(self):
        loops = [n for n in block()["nodes"] if n["id"].startswith("tdd-lane-loop-")]
        self.assertEqual([n["id"] for n in loops], [f"tdd-lane-loop-{n}" for n in range(1, tddlanes.MAX_LANES + 1)])
        for i, n in enumerate(loops, 1):
            with self.subTest(n["id"]):
                self.assertEqual(n["depends_on"], ["tdd-fork"])
                self.assertEqual(n["when"], f"$tdd-fork.output.lane_{i} == true")
                g = n["loop_group"]
                self.assertEqual((g["max_iterations"], g["fresh_context"]), (tddloop.MAX_ITERATIONS, False))
                self.assertEqual(g["until_bash"], f"test $tdd-lane-step-{i}.output.done = true")
                self.assertEqual([m["id"] for m in g["nodes"]], [f"tdd-lane-prep-{i}", f"tdd-lane-{i}", f"tdd-lane-step-{i}"])
                prep, role, step = g["nodes"]
                self.assertEqual((prep["script"], step["script"]), ("tdd_lane_prep", "tdd_lane_step"))
                self.assertEqual(prep["with"]["lane"], str(i))
                self.assertEqual(step["with"], {"reply": {"from": f"$tdd-lane-{i}.output"},
                                                "state_file": "$tdd-start.output.state_file", "lane": str(i)})
                self.assertEqual(role["depends_on"], [f"tdd-lane-prep-{i}"])
                self.assertIn(f"`$tdd-lane-prep-{i}.output.prompt_file` を Read で", role["prompt"])

    def test_lane_layer_holds_only_the_lane_loops(self):
        """枝の輪は同時に走る: 同じ層に mutates_checkout: false の節（や枝の輪のほかの節）を置かない（Archon v0.11.1 の層の順）"""
        nodes = block()["nodes"]
        lay = layers(nodes)
        lane = {lay[f"tdd-lane-loop-{n}"] for n in range(1, tddlanes.MAX_LANES + 1)}
        self.assertEqual(len(lane), 1)
        same = sorted(nid for nid, d in lay.items() if d in lane)
        self.assertEqual(same, [f"tdd-lane-loop-{n}" for n in range(1, tddlanes.MAX_LANES + 1)])
        for n in nodes:
            if n["id"] in same:
                self.assertNotIn(QUIET, n)
                for m in n["loop_group"]["nodes"]:
                    self.assertNotIn(QUIET, m, m["id"])

    def test_loop_exits_on_lanes_and_join_and_rest_follow(self):
        self.assertEqual(top("tdd-loop")["loop_group"]["until_bash"], "test $tdd-step.output.done = true",
                         "並べの枝を切った周は tdd-step が done を立てて抜ける（出口の phase は lanes）")
        fork = top("tdd-fork")
        self.assertEqual((fork["script"], fork["depends_on"], fork["trigger_rule"]),
                         ("tdd_fork", ["tdd-start", "tdd-loop"], "none_failed_min_one_success"))
        self.assertNotIn("when", fork, "実行器の無い run でも走って go: false を返す")
        out = fork["output_format"]
        self.assertEqual(out["required"], ["go", "lanes", *[f"lane_{n}" for n in range(1, tddlanes.MAX_LANES + 1)]])
        self.assertEqual(out["properties"]["lanes"]["maximum"], tddlanes.MAX_LANES)
        join = top("tdd-join")
        self.assertEqual(join["depends_on"], ["tdd-fork", *[f"tdd-lane-loop-{n}" for n in range(1, tddlanes.MAX_LANES + 1)]])
        self.assertEqual((join["trigger_rule"], join["when"]), ("all_done", "$tdd-fork.output.go == true"))
        rest = top("tdd-rest-loop")
        self.assertEqual((rest["depends_on"], rest["when"]), (["tdd-join"], "$tdd-join.output.go == true"))
        g = rest["loop_group"]
        self.assertEqual(g["until_bash"], "test $tdd-rest-step.output.done = true")
        self.assertEqual([(m["id"], m.get("script")) for m in g["nodes"]],
                         [("tdd-rest-prep", "tdd_prep"), ("tdd-rest", None), ("tdd-rest-step", "tdd_step")])
        self.assertEqual(inner("tdd-rest-loop", "tdd-rest-prep")["with"], inner("tdd-loop", "tdd-prep")["with"])
        self.assertEqual(inner("tdd-rest-loop", "tdd-rest-step")["with"],
                         {"reply": {"from": "$tdd-rest.output"}, "state_file": "$tdd-start.output.state_file"})
        fix = top("fix-fork")   # 修正役の並べの枝を切る節が TDD の輪の全部の後（修正の輪はその後。tests/test_fix_lane_wiring.py）
        self.assertEqual(fix["depends_on"], ["tdd-start", "tdd-loop", "tdd-fork", "tdd-join", "tdd-rest-loop"])
        self.assertEqual(top("fix-loop")["depends_on"],
                         ["tdd-start", "tdd-loop", "tdd-fork", "tdd-join", "tdd-rest-loop", "fix-fork", "fix-join"])

    def test_lane_and_rest_roles(self):
        tdd = inner("tdd-loop", "tdd")
        rest = inner("tdd-rest-loop", "tdd-rest")
        self.assertEqual(rest["output_format"]["description"], "works-node: tdd-rest")
        self.assertEqual({k: v for k, v in rest["output_format"].items() if k != "description"},
                         {k: v for k, v in tdd["output_format"].items() if k != "description"})
        want = {k: v for k, v in tdd["output_format"]["properties"].items() if k != "units"}
        want["phase"] = {"type": "string", "enum": [*fixrules.LANE_PHASES, "conflict"]}
        for n in range(1, tddlanes.MAX_LANES + 1):
            role = inner(f"tdd-lane-loop-{n}", f"tdd-lane-{n}")
            with self.subTest(role["id"]):
                self.assertEqual(role["output_format"]["description"], f"works-node: tdd-lane-{n} lane")
                self.assertEqual(role["output_format"]["properties"], want)
                self.assertEqual(role["output_format"]["required"], ["phase"])
                self.assertEqual((role["model"], role["effort"]), (tdd["model"], tdd["effort"]))
                self.assertNotIn("Agent", role["allowed_tools"])
                self.assertEqual((role["skills"], role["settingSources"]), (tdd["skills"], ["user"]))
        for node in ("tdd", "tdd-rest"):
            self.assertNotIn("Agent", inner("tdd-loop" if node == "tdd" else "tdd-rest-loop", node)["allowed_tools"])

    def test_tables_name_the_new_roles(self):
        names = {"tdd-rest", *tddlanes.lane_nodes()}
        models = json.loads((CORE / "stage-models.json").read_text(encoding="utf-8"))["stages"]
        for n in names:
            self.assertEqual(models[f"blk-fix/{n}"], models["blk-fix/tdd"], n)
            self.assertEqual(seat.SEATS[n], seat.SEATS["tdd"], n)
            self.assertIn(n, fixshape.SKILL_NODES)
        self.assertEqual(tddloop.UNIT_NODES, ("tdd", "tdd-rest"))

    def test_lane_files_are_shared_board_records(self):
        """盤面に置く並べのファイルは共有の記録（scopes.SHARED の tdd-*/**）に当たる（柵の表を変えない）"""
        for rel in ("tdd-1/" + tddlanes.MANIFEST, "tdd-1/" + tddlanes.LANE_FILE.format(n=2, j=1),
                    "tdd-1/" + tddlanes.LANE_NEXT.format(n=3), "tdd-1/lanes/item-1.patch"):
            self.assertTrue(any(scopes.matches(rel, pat) for pat in scopes.SHARED), rel)


class TestFork(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.state = pathlib.Path(self._tmp.name) / "state.json"

    def put(self, **st):
        self.state.write_text(json.dumps({"done": False, "phase": "test", **st}), encoding="utf-8")
        return tddlanes.fork(str(self.state))

    def test_fork_reads_the_lanes_phase(self):
        no = {"go": False, "lanes": 0, **{f"lane_{n}": False for n in range(1, tddlanes.MAX_LANES + 1)}}
        self.assertEqual(tddlanes.fork(""), no, "実行器の無い run")
        self.assertEqual(self.put(), no)
        self.assertEqual(self.put(phase="lanes", done=True, lanes={"rows": [{"n": 1}, {"n": 2}]}), no)
        got = self.put(phase="lanes", lanes={"rows": [{"n": 1}, {"n": 2}]})
        self.assertEqual(got, {**no, "go": True, "lanes": 2, "lane_1": True, "lane_2": True})

    def test_fork_refuses_a_broken_manifest(self):
        for rows in ([{"n": 2}], [{"n": n} for n in range(1, tddlanes.MAX_LANES + 2)], []):
            with self.subTest(rows=rows), self.assertRaises(tddloop.Broken):
                self.put(phase="lanes", lanes={"rows": rows})
        with self.assertRaises(tddloop.Broken):
            tddlanes.fork(str(self.state.parent / "nope.json"))


class TestFixtures(unittest.TestCase):
    def test_lanes_fixture_walks_the_lanes(self):
        f = yaml.safe_load((BLK / "fixtures" / "tdd-lanes.stubs.yaml").read_text(encoding="utf-8"))
        self.assertEqual(f["tdd-step"]["phase"], "lanes")
        self.assertEqual((f["tdd-fork"]["lanes"], f["tdd-fork"]["lane_3"]), (2, False))
        self.assertEqual(f["fixture"]["reached"], ["tdd-step", "tdd-fork", "tdd-lane-step-1", "tdd-lane-step-2", "tdd-join",
                                                   "tdd-rest-step", "collect"])
        self.assertIs(f["tdd-join"]["go"], True)
        for n in (1, 2):
            self.assertIs(f[f"tdd-lane-step-{n}"]["done"], True)
        lanes = f["collect"]["tdd"]["lanes"]
        self.assertEqual([u["outcome"] for u in lanes["units"]], ["merged", "serial"])
        t = yaml.safe_load((BLK / "fixtures" / "tdd.stubs.yaml").read_text(encoding="utf-8"))
        self.assertIs(t["tdd-fork"]["go"], False, "並べない run")


if __name__ == "__main__":
    unittest.main()
