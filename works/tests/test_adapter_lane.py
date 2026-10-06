"""包みの旗 lane（.shared/core/adapter.py の頭の 6c。TDD の輪の並べの枝の役 tdd-lane-<n>。docs/plans/2026-10-07-lane-nodes.md）。

- 枝の役は、枝の支度が盤面に書いた印（adapter.lane_tree_path。盤面の tdd-lane-trees/。役が書けない所）の単位の worktree を cwd に起こす。worktree は
  run ごとの置き場の下に在り、Archon の cwd（run の worktree）の作業ツリーの単位の守りの参照を持つ物だけ（役の文からは取らない）
- run の worktree とほかの枝の単位の worktree は柵（permissions.deny・denyWrite）に足し、単位の worktree は allowWrite に足す
- 会話の id・起動の記録の鍵は Archon の cwd のまま。単位の worktree を会話の id の隣（<節>.lane）に記録し、continue=X は X と同じ
  cwd の起動だけを起こす。続きの起動で記録の worktree と違えば新しい会話にする
- 印が無い・読めない・置き場の外・単位の worktree でない・切符が無い・旗 isolated と一緒・sandbox が enabled・
  allowUnsandboxedCommands: false・failIfUnavailable: true でない、は起こさない（fail closed）
- 単位の切れ目で会話を切る節（KEYED_NODES）と旗の一覧は、並べの枝の数（tddlanes.MAX_LANES）と YAML の印に揃う
種の git は gitkit の型の写し・単位の worktree を 2 本切る（子のプロセスは git だけ）。adapter.plan を直に呼ぶ。
"""
import json
import os
import pathlib
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
TESTS = pathlib.Path(__file__).resolve().parent
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(ROOT / "blk-fix" / "lib"))
sys.path.insert(0, str(TESTS))

import adapter  # noqa: E402
import node_marker  # noqa: E402
import unittrees  # noqa: E402
from gitkit import committed_copy  # noqa: E402

SANDBOX = '{"sandbox":{"enabled":true,"allowUnsandboxedCommands":false,"failIfUnavailable":true}}'
NODE = "tdd-lane-1"


def sdk_argv(desc, tools="Read,Edit,Write,Bash", resume=None, settings=SANDBOX):
    """SDK 0.3.282 の並び（test_adapter.sdk_argv と同じ形）で、Bash と sandbox を持つ書く役の起動"""
    schema = {"type": "object", "description": desc, "properties": {"phase": {"type": "string"}}}
    a = ["--output-format", "stream-json", "--verbose", "--input-format", "stream-json", "--model", "sonnet",
         "--effort", "high", "--json-schema", json.dumps(schema), "--tools", tools, "--setting-sources=user",
         "--permission-mode", "bypassPermissions"]
    if resume:
        a += ["--resume", resume]
    return a + (["--settings", settings] if settings is not None else [])


class LaneCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name).resolve()
        self.repo = self.tmp / "wt"
        committed_copy(self.repo, ROOT / "dev" / "target-seed")
        self.board = self.tmp / "art" / "board"
        self.board.mkdir(parents=True)
        self.place = self.tmp / "art" / adapter.RUN_PLACE_NAME
        base = unittrees.snapshot(self.repo)
        self.trees = [unittrees.add(self.repo, base, self.place / "tdd-1" / "lanes" / f"item-{n}") for n in (1, 2)]
        self.addCleanup(unittrees.sweep, self.repo)
        self.home = self.tmp / "adapter-home"
        self.mark(NODE, self.trees[0])

    def mark(self, node, tree):
        p = pathlib.Path(adapter.lane_tree_path(str(self.board), node))
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(f"{tree}\n", encoding="utf-8")

    def plan(self, argv, ticket=True, ids=None):
        return adapter.plan(argv, str(self.repo), self.home, "true", new_id=lambda: ids or "s-new",
                            protected=(lambda: []) if ticket else (lambda: None),
                            run_place=lambda: str(self.place) if ticket else None,
                            board=lambda: str(self.board) if ticket else None,
                            env={"PATH": os.environ.get("PATH", "")})

    def settings(self, p) -> dict:
        i = p.argv.index("--settings")
        return json.loads(p.argv[i + 1])

    def put_session(self, node, sid, lane=None):
        path = adapter.session_path(self.repo, node, self.home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(sid + "\n", encoding="utf-8")
        if lane is not None:
            adapter.lane_record_path(self.repo, node, self.home).write_text(f"{lane}\n", encoding="utf-8")


class TestLaneLaunch(LaneCase):
    def test_lane_role_runs_in_its_unit_worktree(self):
        p = self.plan(sdk_argv(f"works-node: {NODE} lane"))
        self.assertEqual(p.mode, "merged", p.why)
        tree = os.path.realpath(self.trees[0])
        self.assertEqual(p.cwd, tree, "子の cwd は単位の worktree")
        self.assertEqual(p.fence["lane"], tree)
        self.assertEqual(p.fence["lane_deny"], [os.path.realpath(self.repo), os.path.realpath(self.trees[1])])
        doc = self.settings(p)
        deny = doc["permissions"]["deny"]
        for other in (os.path.realpath(self.repo), os.path.realpath(self.trees[1])):
            self.assertIn(f"Edit(/{other}/**)", deny, "run の worktree とほかの枝の worktree は書かせない")
            self.assertIn(other, doc["sandbox"]["filesystem"]["denyWrite"])
        self.assertNotIn(f"Edit(/{tree}/**)", deny)
        self.assertIn(tree, doc["sandbox"]["filesystem"]["allowWrite"], "単位の worktree は書ける")
        self.assertIn((adapter.lane_record_path(self.repo, NODE, self.home), tree), p.record, "会話の cwd を記録する")
        self.assertEqual(p.record[0], (adapter.session_path(self.repo, NODE, self.home), "s-new"),
                         "会話の id の鍵は Archon の cwd（run の worktree）のまま")
        row = adapter.launch_row(p, self.repo, 1, "t")
        self.assertEqual((row["cwd"], row["fence"]["lane"]), (os.path.realpath(self.repo), tree),
                         "起動の記録は run の worktree の鍵で、枝の cwd を fence.lane に残す")

    def test_each_lane_reads_its_own_mark(self):
        self.mark("tdd-lane-2", self.trees[1])
        p = self.plan(sdk_argv("works-node: tdd-lane-2 lane"))
        self.assertEqual(p.cwd, os.path.realpath(self.trees[1]))
        self.assertEqual(p.fence["lane_deny"], [os.path.realpath(self.repo), os.path.realpath(self.trees[0])])

    def test_unmarked_flagless_role_is_unchanged(self):
        p = self.plan(sdk_argv("works-node: tdd"))
        self.assertEqual(p.mode, "merged", p.why)
        self.assertIsNone(p.cwd)
        self.assertNotIn("lane", p.fence)


class TestLaneRefused(LaneCase):
    def refused(self, p, word):
        self.assertEqual(p.mode, "refused", p)
        self.assertIn(word, p.why)
        self.assertEqual(p.record, [], "記録を書かない")

    def test_no_mark(self):
        pathlib.Path(adapter.lane_tree_path(str(self.board), NODE)).unlink()
        self.refused(self.plan(sdk_argv(f"works-node: {NODE} lane")), "印が無いか読めない")

    def test_relative_or_missing_tree(self):
        self.mark(NODE, "lanes/item-1")
        self.refused(self.plan(sdk_argv(f"works-node: {NODE} lane")), "絶対パスでない")
        self.mark(NODE, self.place / "nope")
        self.refused(self.plan(sdk_argv(f"works-node: {NODE} lane")), "単位の worktree が無い")

    def test_tree_outside_the_run_place(self):
        outside = self.tmp / "elsewhere"
        outside.mkdir()
        self.mark(NODE, outside)
        self.refused(self.plan(sdk_argv(f"works-node: {NODE} lane")), "run ごとの置き場")
        self.mark(NODE, self.repo)
        self.refused(self.plan(sdk_argv(f"works-node: {NODE} lane")), "run ごとの置き場")

    def test_plain_dir_under_the_run_place_is_not_a_unit_tree(self):
        plain = self.place / "tdd-1" / "lanes" / "plain"
        plain.mkdir(parents=True)
        self.mark(NODE, plain)
        self.refused(self.plan(sdk_argv(f"works-node: {NODE} lane")), "単位の worktree（守りの参照を持つ物）でない")

    def test_worktree_without_the_guard_ref(self):
        """単位の守りの参照を持たない worktree（役は共通の .git の中に参照を作れない）は通さない"""
        ref = [r for r in unittrees._refs(self.repo) if r.endswith("u-" + unittrees._mark(self.trees[0]))]
        self.assertEqual(len(ref), 1)
        from gitkit import git
        git(self.repo, "update-ref", "-d", ref[0])
        self.refused(self.plan(sdk_argv(f"works-node: {NODE} lane")), "守りの参照")

    def test_no_ticket(self):
        self.refused(self.plan(sdk_argv(f"works-node: {NODE} lane"), ticket=False), "切符が無い")

    def test_mark_lives_on_the_board(self):
        """印は盤面の下（切符の守る場所）。run ごとの置き場（役が書ける）には置かない"""
        path = pathlib.Path(adapter.lane_tree_path(str(self.board), NODE))
        self.assertEqual(path.parent.parent, self.board)
        self.assertFalse(str(path).startswith(str(self.place)))

    def test_loose_or_missing_sandbox(self):
        """Bash を sandbox の外で走らせる・sandbox が立たない場で素通しする起動は起こさない（旗 no-tree-write と同じ確かめ）"""
        for settings, word in ((None, "sandbox の塊"), ('{"sandbox":{"enabled":true,"allowUnsandboxedCommands":false}}', "failIfUnavailable"),
                               ('{"sandbox":{"enabled":true,"failIfUnavailable":true}}', "allowUnsandboxedCommands")):
            with self.subTest(settings=settings):
                self.refused(self.plan(sdk_argv(f"works-node: {NODE} lane", settings=settings)), word)

    def test_with_isolated(self):
        self.refused(self.plan(sdk_argv(f"works-node: {NODE} lane isolated", tools="")), "isolated")


class TestLaneSessions(LaneCase):
    def test_resume_in_another_tree_starts_a_new_conversation(self):
        """続きの起動（SDK の --resume）で、記録の worktree と今の worktree が違えば新しい会話（claude の会話の置き場は cwd ごと）"""
        self.put_session(NODE, "s-old", lane=os.path.realpath(self.trees[1]))
        p = self.plan(sdk_argv(f"works-node: {NODE} lane", resume="s-old"))
        self.assertEqual(p.mode, "merged", p.why)
        self.assertEqual((p.session["mode"], p.session["id"], p.session.get("lane_cut")), ("new", "s-new", True))
        self.assertNotIn("s-old", p.argv)
        self.put_session(NODE, "s-old", lane=os.path.realpath(self.trees[0]))
        p = self.plan(sdk_argv(f"works-node: {NODE} lane", resume="s-old"))
        self.assertEqual((p.session["mode"], p.session["id"]), ("sdk-resume", "s-old"), "同じ worktree なら継ぐ")

    def test_continue_needs_the_same_cwd(self):
        self.put_session(NODE, "s-lane", lane=os.path.realpath(self.trees[0]))
        p = self.plan(sdk_argv(f"works-node: tdd-lane-x continue={NODE}"))
        self.assertEqual(p.mode, "refused", "単位の worktree で走った会話を run の worktree で続けない")
        self.assertIn("cwd", p.why)
        self.mark("tdd-lane-x", self.trees[0])
        p = self.plan(sdk_argv(f"works-node: tdd-lane-x continue={NODE} lane"))
        self.assertEqual(p.mode, "merged", p.why)
        self.assertEqual((p.session["mode"], p.session["id"], p.cwd), ("continued", "s-lane", os.path.realpath(self.trees[0])))
        self.mark("tdd-lane-x", self.trees[1])
        p = self.plan(sdk_argv(f"works-node: tdd-lane-x continue={NODE} lane"))
        self.assertEqual(p.mode, "refused", "別の枝の worktree では続けない")

    def test_lane_launch_cannot_continue_a_run_tree_conversation(self):
        self.put_session("tdd", "s-run")
        p = self.plan(sdk_argv(f"works-node: {NODE} continue=tdd lane"))
        self.assertEqual(p.mode, "refused")


class TestLaneTables(unittest.TestCase):
    def test_flag_tables_agree(self):
        self.assertIn(adapter.LANE, adapter.FLAGS)
        self.assertEqual(frozenset(adapter.FLAGS), node_marker.FLAGS)

    def test_keyed_nodes_cover_the_lane_roles(self):
        import tddlanes
        import tddloop
        self.assertEqual(adapter.KEYED_NODES, frozenset({*tddloop.UNIT_NODES, *tddlanes.lane_nodes()}))

    def test_yaml_lane_roles_carry_the_flag(self):
        """YAML の枝の役は印 works-node: tdd-lane-<n> lane を持ち、ほかの役は旗 lane を持たない"""
        import tddlanes
        found = {}
        for path in ROOT.glob("*/*.yaml"):
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
            stack = list(doc.get("nodes") or []) if isinstance(doc, dict) else []
            while stack:
                n = stack.pop()
                if "loop_group" in n:
                    stack += n["loop_group"]["nodes"]
                desc = (n.get("output_format") or {}).get("description") if isinstance(n.get("output_format"), dict) else None
                m = node_marker.parse(desc)
                if m and adapter.LANE in m["flags"]:
                    found[m["name"]] = path.parent.name
        self.assertEqual(found, {n: "blk-fix" for n in tddlanes.lane_nodes()})


if __name__ == "__main__":
    unittest.main()
