"""修正役の並べを Archon の節で回す配線（blk-fix の fix-fork・fix-lane-loop-<n>・fix-join と修正の輪。
docs/plans/2026-10-07-fix-lane-nodes.md）。YAML と筋書きと表を読み、枝の部品の純粋な口を呼ぶだけ（git・盤面・子のプロセスなし）。

- 枝の輪は fixlanes.MAX_LANES 本（並べの枝の部品 lanekit.MAX_LANES。TDD の輪の並べと同じ数）で、どれも fix-fork だけに依り、when: で
  lane_<n> を読む。枝の輪の層には枝の輪のほかの節を置かない（mutates_checkout: false の節が混ざると Archon v0.11.1 は層を順に回す）
- 枝の輪の中: 支度 → 役（印 works-node: fix-lane-<n> lane self-resume・修正役と同じ返答の形と模型）→ 範囲の相談の 3 節（段 lane-<n>。
  答えの節は continue=fix-planner fork）→ 確かめ（consulted を読む）。上限は fixlanes.MAX_ITERATIONS
- fix-join は all_done で枝の輪の全部を待ち、fix-fork の go を読む。修正の輪は fix-fork と fix-join の後
- 分け方（groups・assign）・拒否の本文・結末の本文・表（段の模型・Agent を持つ節・単位の切れ目の節）
- 筋書き fix-lanes が枝の輪を通る
"""
import json
import pathlib
import sys
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-fix"
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(BLK / "lib"))
sys.path.insert(0, str(CORE))

import adapter  # noqa: E402
import consult  # noqa: E402
import fixlanes  # noqa: E402
import lanekit  # noqa: E402
import recount  # noqa: E402
import seat  # noqa: E402
import tddlanes  # noqa: E402
from test_tdd_lane_wiring import QUIET, block, inner, layers, top  # noqa: E402
sys.path.append(str(ROOT / "dev"))   # 筋書きの合わせ方（dev/stubfold.py）
import stubfold  # noqa: E402

NS = range(1, fixlanes.MAX_LANES + 1)


class TestWiring(unittest.TestCase):
    def test_one_lane_component_for_both_stages(self):
        self.assertEqual(fixlanes.MAX_LANES, lanekit.MAX_LANES)
        self.assertEqual(tddlanes.MAX_LANES, lanekit.MAX_LANES)

    def test_fork_runs_after_the_tdd_loops(self):
        fork = top("fix-fork")
        self.assertEqual((fork["script"], fork["trigger_rule"]), ("fix_fork", "none_failed_min_one_success"))
        self.assertNotIn("when", fork, "実行器の無い run でも走って go: false を返す")
        self.assertEqual(fork["output_format"]["required"], ["go", "lanes", *[f"lane_{n}" for n in NS], "why"])
        self.assertEqual(fork["with"]["fix_lanes"], "$INPUTS.fix_lanes")

    def test_lane_loops_follow_the_fork_only(self):
        loops = [n for n in block()["nodes"] if n["id"].startswith("fix-lane-loop-")]
        self.assertEqual([n["id"] for n in loops], [f"fix-lane-loop-{n}" for n in NS])
        for i, n in enumerate(loops, 1):
            with self.subTest(n["id"]):
                self.assertEqual((n["depends_on"], n["when"]), (["fix-fork"], f"$fix-fork.output.lane_{i} == true"))
                g = n["loop_group"]
                self.assertEqual((g["max_iterations"], g["fresh_context"]), (fixlanes.MAX_ITERATIONS, False))
                self.assertEqual(g["until_bash"], f"test $fix-lane-step-{i}.output.done = true")
                self.assertEqual([m["id"] for m in g["nodes"]],
                                 [f"fix-lane-prep-{i}", f"fix-lane-{i}", f"fix-lane-consult-{i}", f"plan-answer-lane-{i}",
                                  f"fix-lane-consult-check-{i}", f"fix-lane-step-{i}"])
                prep, step = g["nodes"][0], g["nodes"][-1]
                self.assertEqual((prep["script"], prep["with"]), ("fix_lane_prep", {"lane": str(i)}))
                self.assertEqual(step["script"], "fix_lane_step")
                self.assertEqual(step["with"], {"reply": {"from": f"$fix-lane-{i}.output", "if_skipped": None}, "lane": str(i),
                                                "consulted": {"from": f"$fix-lane-consult-check-{i}.output.consulted",
                                                              "if_skipped": False},
                                                "base_rev": "$INPUTS.base_rev", "tdd_state": "$tdd-start.output.state_file"})
                # resume で回し直された済んだ枝の輪: 支度の go: false で役（と相談の 3 節）を飛ばし、確かめが返答 null で輪を抜ける
                self.assertEqual((step["depends_on"], step["trigger_rule"]),
                                 ([f"fix-lane-prep-{i}", f"fix-lane-consult-check-{i}"], "none_failed_min_one_success"))
                self.assertEqual(prep["output_format"]["required"], ["prompt_file", "go"])
                self.assertEqual(g["nodes"][1]["when"], f"$fix-lane-prep-{i}.output.go == true")

    def test_lane_layer_holds_only_the_lane_loops(self):
        nodes = block()["nodes"]
        lay = layers(nodes)
        lane = {lay[f"fix-lane-loop-{n}"] for n in NS}
        self.assertEqual(len(lane), 1)
        self.assertEqual(sorted(nid for nid, d in lay.items() if d in lane), [f"fix-lane-loop-{n}" for n in NS])
        for n in nodes:
            if n["id"].startswith("fix-lane-loop-"):
                self.assertNotIn(QUIET, n)

    def test_join_then_the_fix_loop(self):
        join = top("fix-join")
        self.assertEqual(join["depends_on"], ["fix-fork", *[f"fix-lane-loop-{n}" for n in NS]])
        self.assertEqual((join["trigger_rule"], join["when"]), ("all_done", "$fix-fork.output.go == true"))
        self.assertIn("fix-join", top("fix-loop")["depends_on"])
        self.assertIn("fix-fork", top("fix-loop")["depends_on"])

    def test_lane_roles(self):
        fix = inner("fix-loop", "fix")
        for n in NS:
            role = inner(f"fix-lane-loop-{n}", f"fix-lane-{n}")
            with self.subTest(role["id"]):
                self.assertEqual(role["output_format"]["description"], f"works-node: fix-lane-{n} lane self-resume")
                self.assertEqual({k: v for k, v in role["output_format"].items() if k != "description"},
                                 {k: v for k, v in recount.FIX_OUTPUT_FORMAT.items() if k != "description"},
                                 "返答の形は修正役と同じ（修正の輪の修正役が枝の行を写す）")
                self.assertEqual((role["model"], role["effort"]), (fix["model"], fix["effort"]))
                self.assertIn("Agent", role["allowed_tools"], "審査の下請けを起こす")
                self.assertEqual(role["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False, "failIfUnavailable": True},
                                 "包みの旗 lane が求める形")
                ans = inner(f"fix-lane-loop-{n}", f"plan-answer-lane-{n}")
                self.assertEqual(ans["output_format"], consult.answer_format(f"plan-answer-lane-{n}", fork=True))
                self.assertIs(ans["mutates_checkout"], False)

    def test_tables_name_the_new_roles(self):
        models = json.loads((CORE / "stage-models.json").read_text(encoding="utf-8"))["stages"]
        for n in fixlanes.lane_nodes():
            self.assertEqual(models[f"blk-fix/{n}"], models["blk-fix/fix"], n)
            self.assertIn(n, seat.AGENT_NODES)
            self.assertIn(n, adapter.KEYED_NODES, "枝の中の項目が替われば新しい会話")
        for n in NS:
            self.assertEqual(models[f"blk-fix/plan-answer-lane-{n}"], models["blk-fix/plan-answer"])

    def test_iteration_cap_and_give_up_match_the_accept(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("blk_fix_accept_for_lanes", BLK / "scripts" / "accept.py")
        accept = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(accept)
        self.assertEqual(fixlanes.GIVE_UP_AFTER, accept.GIVE_UP_AFTER)
        self.assertEqual(fixlanes.MAX_ITERATIONS, fixlanes.MAX_ITEMS * accept.GIVE_UP_AFTER + consult.BUDGET)

    def test_fixtures_walk_the_lanes(self):
        f = stubfold.load(BLK / "fixtures" / "fix-lanes.stubs.yaml")
        self.assertEqual((f["fix-fork"]["go"], f["fix-fork"]["lanes"], f["fix-fork"]["lane_3"]), (True, 2, False))
        self.assertEqual(f["fixture"]["reached"], ["fix-fork", "fix-lane-step-1", "fix-lane-step-2", "fix-join", "collect"])
        self.assertEqual(f["fix-join"]["merged"], [1, 2])
        for name in ("pass", "tdd", "tdd-lanes", "no-change", "conflict"):
            g = stubfold.load(BLK / "fixtures" / f"{name}.stubs.yaml")
            self.assertIs(g["fix-fork"]["go"], False, name)
            self.assertNotIn("fix-units", g, "前の形の締めの節は無い")


class TestPure(unittest.TestCase):
    def test_groups_join_items_through_units(self):
        self.assertEqual(fixlanes.groups([(1, ["a"]), (2, ["b"]), (3, ["a", "c"]), (4, ["c"]), (5, ["d"])]), [[1, 3, 4], [2], [5]])

    def test_assign_spreads_groups_and_leaves_the_rest(self):
        lanes, rest = fixlanes.assign([[1], [2], [3], [4]])
        self.assertEqual((lanes, rest), ([[1, 4], [2], [3]], []))
        lanes, rest = fixlanes.assign([[1, 2, 3, 4], [5], [6]])
        self.assertEqual((lanes, rest), ([[5], [6]], [1, 2, 3, 4]), "1 本の枝に入らない組は修正の輪が順に直す")
        lanes, rest = fixlanes.assign([[n] for n in range(1, 11)])
        self.assertEqual(sum(len(x) for x in lanes), fixlanes.MAX_LANES * fixlanes.MAX_ITEMS)
        self.assertEqual(rest, [10])
        self.assertEqual(fixlanes.assign([[1, 2]])[0], [[1, 2]], "単位を共にする項目は 1 本の枝（枝 1 本は並べない）")

    def test_reject_text_lists_checks_in_order(self):
        text = fixlanes.render_rejects([("scope", "x は範囲の外"), ("writes", "記録が無い"), ("scope", "x は範囲の外")])
        self.assertLess(text.index("確かめ writes"), text.index("確かめ scope"))
        self.assertEqual(text.count("x は範囲の外"), 1)
        with self.assertRaises(ValueError):
            fixlanes.note([], "nope", "x")

    def test_summary_names_merged_and_back_items(self):
        doc = {"items": [{"item": 1, "lane": 1, "outcome": "merged", "changed": ["a"], "not_done": ["b"], "claimed": ["c"],
                          "files": ["x.py"], "reply": "/r.json", "refused": {}, "why": "", "patch": ""},
                         {"item": 2, "lane": 2, "outcome": "serial", "changed": [], "not_done": [], "claimed": [], "files": [],
                          "reply": "", "refused": {}, "why": "当たらない", "patch": "/p.patch"}],
               "shared": ["x.py"], "union": [], "reverted": [], "rest": [3]}
        text = fixlanes.summary_text(doc)
        for w in ("項目 1（枝 1）", "/r.json", "not_done", "止めた単位", "項目 2（枝 2）: 当たらない", "/p.patch", "重なりのファイル", "3"):
            self.assertIn(w, text)


if __name__ == "__main__":
    unittest.main()
