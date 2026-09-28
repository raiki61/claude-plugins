"""役の道具が本線より少なくないか（持ち主 2026-09-28「役も一次情報を web から引けるように。本線はできる」）。

本線の graph（写しの graphloops/graphs/review-loop.json・review-loop-tdd.json）は節ごとに run_by（誰が回すか）を持つ。
works の役の節（YAML の AI の節）の allowed_tools は、その run_by の定義の道具を全部含む（⊇）。
- judge・inspector・investigator・blind-judge・cold-reader: 本線の役の定義（agents/<役>.md の tools:）を下の表 AGENT_TOOLS に写した物。
  試験の時に plugin のキャッシュは読まない（写した元は COPIED_FROM）
- writer（本線の主のセッション。全部の道具を持つ）と skill（主のセッションがスキルを回す）: 少なくとも web（WebSearch・WebFetch）。
  書く道具・shell は各ブロックの今の持ち物のまま（読むだけの writer に書く道具を足さない。受け付けが作業ツリーを見張る）
- comment-analyzer（pr-review-toolkit の agent。定義に tools: が無い＝全部の道具）: 目は作業ツリーを変えないので、定義の道具から
  書く道具と shell を除いた物（Read・Grep・Glob・WebSearch・WebFetch）。狭めた分は NARROWED に理由つきで置く
対応（graph の節 → YAML の節）は表 ROLE_NODES。nodes.json の役の節（by: role か fallback: role）と、pack の全部の AI の節が
表に載っていることも見る（表から漏れた役が本線より少ない道具のまま残らないように）。
"""
import json
import pathlib
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
GRAPHS = ROOT / ".shared" / "core" / "graphloops" / "graphs"

# COPIED_FROM: /Users/p03623/src/claude-plugins（本線。convergence-loops）@ 987d15a の agents/<役>.md の tools: の行
#   blind-judge.md「tools: []」・cold-reader.md「tools: []」・inspector.md「tools: Read, Glob, Grep」・
#   investigator.md「tools: Read, Glob, Grep, Bash, WebSearch, WebFetch」・judge.md「tools: Read, Glob, Grep, WebSearch, WebFetch」
AGENT_TOOLS = {
    "judge": {"Read", "Glob", "Grep", "WebSearch", "WebFetch"},
    "inspector": {"Read", "Glob", "Grep"},
    "investigator": {"Read", "Glob", "Grep", "Bash", "WebSearch", "WebFetch"},
    "blind-judge": set(),
    "cold-reader": set(),
}
WEB = {"WebSearch", "WebFetch"}
# 主のセッション（全部の道具）。works は各ブロックの持ち物に少なくとも web を足した物を求める
MAIN_SESSION = {"writer": WEB, "skill": WEB | {"Skill"}}
# 定義は全部の道具を持つが、works が読むだけに狭めた run_by → (求める道具, 狭めた理由)
NARROWED = {
    "comment-analyzer": (AGENT_TOOLS["judge"],
                         "pr-review-toolkit の comment-analyzer は tools: を持たない（全部の道具）。独立の目は作業ツリーを"
                         "変えないので書く道具と shell を除く（blk-eyes/lib/eyes.py の TOOLS と同じ）"),
}

# graph の節 → (フォルダ, YAML の節)。1 つの YAML の節を 2 つの graph の節が使う物（blk-ci の ci）は 2 行
ROLE_NODES = {
    "p0.premises": ("blk-premises", "premises"),
    "p0.purpose": ("blk-purpose", "purpose"),
    "p0.purpose_review": ("blk-material", "purpose-review"),
    "p0.parallel_pr": ("blk-pr", "pr-check"),
    "p0.local_checks": ("blk-ci", "ci"),
    "p0.prior_decisions": ("blk-material", "prior-decisions"),
    "p1.local_review": ("blk-material", "local-review"),
    "p1.consistency_bypass": ("blk-material", "consistency-bypass"),
    "p1.hygiene": ("blk-material", "hygiene"),
    "p1.external_standards": ("blk-material", "external-standards"),
    "p1.procedure_trace": ("blk-material", "procedure-trace"),
    "p1.gate_efficacy": ("blk-material", "gate-efficacy"),
    "p1.test_double_fidelity": ("blk-material", "test-double-fidelity"),
    "p1.main_path_observation": ("blk-material", "main-path-observation"),
    "p1.provenance": ("blk-material", "provenance"),
    "p2.diagnose": ("blk-judge", "judge"),
    "p2.fix_plan": ("blk-plan", "plan"),
    "p2.plan_review": ("blk-plan", "plan-review"),
    "p2.rejudge": ("blk-rejudge", "rejudge"),
    "p2.rejudge_third": ("blk-rejudge", "rejudge-third"),
    "p3.fix": ("blk-fix", "fix"),
    "p3.tdd_tests": ("blk-fix", "tdd"),
    "p3.delta_review": ("blk-delta", "review"),
    "p3.delta_fix": ("blk-refix", "refix"),
    "p3.delta_review2": ("blk-refix", "review2"),
    "p3.delta_fix2": ("blk-refix", "refix2"),
    "p4.ci": ("blk-ci", "ci"),
    "r1.comment_candidates": ("blk-eyes", "r1-comments"),
    "r1.minimality": ("blk-eyes", "r1-minimality"),
    "r2.design": ("blk-plan", "r2-design"),
    "r2.compare": ("blk-eyes", "r2-compare"),
    "r3.coherence": ("blk-eyes", "r3-coherence"),
    "r4.hidden_scope": ("blk-eyes", "r4-scope"),
    "stop.premise_check": ("blk-eyes", "premise-check"),
    "report.human_items": ("blk-report", "report-items"),
    "report.cold_check": ("blk-report", "report-cold"),
    "report": ("blk-report", "report-write"),
    "spec.write": ("blk-spec", "spec-write"),
    "spec.review": ("blk-spec", "spec-review"),
    "spec.revise": ("blk-spec", "spec-revise"),
}


# 本線の graph に無い works だけの役の節 → 本線のどの役に当たるか（食い違いの申し出の出口。持ち主 2026-09-28）:
# 2 回目の修正役は p3.fix の続き（writer）、裁定役は読むだけで裁く目（judge）、報告の書き手の出した物を確かめる初見の読み手は
# report.cold_check と同じ cold-reader（道具なし）
EXTRA_ROLES = {("blk-fix", "fix-ruled"): "writer", ("blk-fix", "rule"): "judge",
               ("blk-report", "report-write-cold"): "cold-reader"}


def graph_run_by() -> dict:
    out = {}
    for name in ("review-loop.json", "review-loop-tdd.json"):
        doc = json.loads((GRAPHS / name).read_text(encoding="utf-8"))
        nodes = doc["nodes"]
        for n in (nodes if isinstance(nodes, list) else [dict(id=k, **v) for k, v in nodes.items()]):
            if n.get("run_by"):
                out.setdefault(n["id"], n["run_by"])
    return out


def ai_nodes() -> dict:
    """{(フォルダ, 節): YAML の節}（pack の全部のブロックの AI の節。輪の中も辿る）"""
    out = {}

    def walk(folder, nodes):
        for n in nodes:
            if "loop_group" in n:
                walk(folder, n["loop_group"]["nodes"])
            elif "prompt" in n or "command" in n:
                out[(folder, n["id"])] = n
    for p in sorted(ROOT.glob("blk-*/blk-*.yaml")):
        walk(p.parent.name, yaml.safe_load(p.read_text(encoding="utf-8"))["nodes"])
    return out


def required(run_by: str) -> set:
    if run_by in AGENT_TOOLS:
        return AGENT_TOOLS[run_by]
    if run_by in MAIN_SESSION:
        return MAIN_SESSION[run_by]
    return NARROWED[run_by][0]


class ToolParityCase(unittest.TestCase):
    def setUp(self):
        self.run_by = graph_run_by()
        self.nodes = ai_nodes()

    def test_each_role_has_at_least_the_mainline_tools(self):
        for gid, place in sorted(ROLE_NODES.items()):
            with self.subTest(gid):
                rb = self.run_by[gid]
                node = self.nodes[place]
                have = set(node.get("allowed_tools") or [])
                self.assertEqual(sorted(required(rb) - have), [],
                                 f"{place[0]} の節 {place[1]}（{gid}・本線の run_by {rb}）の道具が本線より少ない")

    def test_every_run_by_is_known(self):
        known = set(AGENT_TOOLS) | set(MAIN_SESSION) | set(NARROWED)
        for gid in ROLE_NODES:
            with self.subTest(gid):
                self.assertIn(self.run_by[gid], known)

    def test_table_covers_nodes_json_roles(self):
        table = json.loads((ROOT / "darkfactory" / "nodes.json").read_text(encoding="utf-8"))["nodes"]
        roles = {k for k, v in table.items() if v.get("by") == "role" or v.get("fallback") == "role"}
        self.assertEqual(sorted(roles - set(ROLE_NODES)), [], "nodes.json の役の節が表 ROLE_NODES に無い")

    def test_works_only_roles_have_at_least_their_mainline_counterpart(self):
        for place, rb in sorted(EXTRA_ROLES.items()):
            with self.subTest(place):
                have = set(self.nodes[place].get("allowed_tools") or [])
                self.assertEqual(sorted(required(rb) - have), [], f"{place} の道具が本線の {rb} より少ない")
        self.assertEqual(set(self.nodes[("blk-fix", "fix-ruled")]["allowed_tools"]),
                         set(self.nodes[("blk-fix", "fix")]["allowed_tools"]), "2 回目の修正役は修正役と同じ道具")

    def test_table_covers_every_ai_node(self):
        self.assertEqual(sorted(set(self.nodes) - set(ROLE_NODES.values()) - set(EXTRA_ROLES)), [],
                         "YAML の AI の節が表 ROLE_NODES に無い（本線のどの役かを決めていない）")

    def test_writers_can_read_the_web(self):
        """本線の writer（主のセッション）の節は、どれも WebSearch・WebFetch を持つ（修正・修正案・TDD・手直しの役を含む）"""
        writers = sorted(g for g in ROLE_NODES if self.run_by[g] == "writer")
        self.assertIn("p3.fix", writers)
        self.assertIn("p2.fix_plan", writers)
        self.assertIn("p3.tdd_tests", writers)
        for gid in writers:
            with self.subTest(gid):
                self.assertLessEqual(WEB, set(self.nodes[ROLE_NODES[gid]].get("allowed_tools") or []))


if __name__ == "__main__":
    unittest.main()
