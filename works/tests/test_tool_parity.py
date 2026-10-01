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
import re
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
    "silent-failure-hunter": (AGENT_TOOLS["inspector"],
                              "pr-review-toolkit の silent-failure-hunter は tools: を持たない（全部の道具）。修正の後のレンズの節は"
                              "定義を貼った節そのもので、道具は Read・Grep・Glob だけ（子を起こすとまとめ役の形に戻る。持ち主 2026-10-01）"),
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
# report.cold_check と同じ cold-reader（道具なし）。構造の目は道具ゼロの目で blind-judge。修正の後のレンズは借りた
# agent そのもの（前付けが core/agents に無いので段に model: を書かず、run の既定（dev/guard.sh の WORKS_DEV_MODEL_DEFAULT）で
# 走る。ADR 0072 の「測るまで Opus」は持ち主 2026-10-01 が費用を先に取って覆した。模型を固定するなら行を前付けの在る役にする）
EXTRA_ROLES = {("blk-fix", "fix-ruled"): "writer", ("blk-fix", "rule"): "judge",
               ("blk-report", "report-write-cold"): "cold-reader", ("blk-structure", "structure-eye"): "blind-judge",
               ("blk-lens", "lens-silent-failure-hunter"): "silent-failure-hunter"}


def graph_run_by() -> dict:
    out = {}
    for name in ("review-loop.json", "review-loop-tdd.json"):
        doc = json.loads((GRAPHS / name).read_text(encoding="utf-8"))
        nodes = doc["nodes"]
        for n in (nodes if isinstance(nodes, list) else [dict(id=k, **v) for k, v in nodes.items()]):
            if n.get("run_by"):
                out.setdefault(n["id"], n["run_by"])
    return out


def workflow_files() -> list:
    """pack の全部の工程（ブロックとライン darkfactory。ラインの頭の model: もブロックを include した段に効く）"""
    return sorted(ROOT.glob("blk-*/blk-*.yaml")) + sorted(ROOT.glob("darkfactory/*.yaml"))


def ai_nodes() -> dict:
    """{(フォルダ, 節): YAML の節}（pack の全部の工程の AI の節。輪の中も辿る）"""
    out = {}

    def walk(folder, nodes):
        for n in nodes:
            if "loop_group" in n:
                walk(folder, n["loop_group"]["nodes"])
            elif "prompt" in n or "command" in n:
                out[(folder, n["id"])] = n
    for p in workflow_files():
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


def frontmatter(run_by: str) -> dict:
    """core/agents/<役>.md の前付け（役の定義が無ければ空）"""
    p = ROOT / ".shared" / "core" / "agents" / f"{run_by}.md"
    if not p.is_file():
        return {}
    return yaml.safe_load(p.read_text(encoding="utf-8").split("---", 2)[1]) or {}


def frontmatter_model(run_by: str):
    """core/agents/<役>.md の前付けの model:（役の定義が無ければ None）"""
    return frontmatter(run_by).get("model")


def frontmatter_effort(run_by: str):
    """core/agents/<役>.md の前付けの effort:（役の定義が無ければ None）"""
    return frontmatter(run_by).get("effort")


# 段に model: を書く模型の集合（持ち主 2026-10-01。前付けに model の在る役は全部段に映し、run の既定に頼らない）。
# 殻の環境変数 WORKS_MODEL_PINNED とは別物
PINNED = {"sonnet", "opus"}


def stage_roles() -> dict:
    """{(フォルダ, 節): 本線の run_by}（表 ROLE_NODES を graph の run_by で引き、EXTRA_ROLES を足す）"""
    run_by = graph_run_by()
    out = {place: run_by[gid] for gid, place in ROLE_NODES.items()}
    out.update(EXTRA_ROLES)
    return out


def expected_model(run_by: str):
    """段に書くべき model:。前付けの model が PINNED に在る役だけ前付けの値、ほかは None（書かない）"""
    want = frontmatter_model(run_by)
    return want if want in PINNED else None


def model_mismatches(nodes: dict, roles: dict) -> list:
    """段の model: が役の前付けから決まる値と食い違う段を名指す。役に引き当てられない AI の段も名指す"""
    out = []
    for place, node in sorted(nodes.items()):
        if place not in roles:
            out.append(f"{place[0]} の段 {place[1]}: 役に引き当てられない（表 ROLE_NODES・EXTRA_ROLES に無い）")
            continue
        want, have = expected_model(roles[place]), node.get("model")
        if have != want:
            out.append(f"{place[0]} の段 {place[1]}（役 {roles[place]}）: model: {have!r}（期待 {want!r}）")
    return out


def effort_mismatches(nodes: dict, roles: dict) -> list:
    """段の effort: が役の前付けの effort（無ければ None）と食い違う段を名指す。書き忘れると前付けの effort が効かず
    既定で黙って走るので、欠けも名指す。役に引き当てられない段は model_mismatches が名指すので、ここでは見ない"""
    out = []
    for place, node in sorted(nodes.items()):
        if place not in roles:
            continue
        want, have = frontmatter_effort(roles[place]), node.get("effort")
        if have != want:
            out.append(f"{place[0]} の段 {place[1]}（役 {roles[place]}）: effort: {have!r}（前付け {want!r}）")
    return out


# 118 件目（302ece35）で外した段の字の禁止 2 形（段の節を safe_dump した字・役の節）。この 2 形の再発だけを縛る
REVERSE_FENCE = re.compile(r"""assertNotIn\(\s*['"]model['"],\s*(yaml\.safe_dump\(|role\))""")


def reverse_fence_hits(files) -> list:
    """REVERSE_FENCE に当たる行を「ファイル名:行」で名指す"""
    return [f"{p.name}:{i}" for p in files
            for i, ln in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if REVERSE_FENCE.search(ln)]


class RoleModelCase(unittest.TestCase):
    """Archon の段は役の前付けを読まない。前付けの model が PINNED に在る役の段だけ段の model: に同じ値を書き、
    ほかの段と工程の頭には書かない（持ち主 2026-09-29。2026-10-01 に PINNED へ opus も足した）。effort は前付けに effort を持つ役の全部の段に同じ値を書き、
    ほかの段と工程の頭には書かない。
    graph の節の delegate.model は本線の主のセッションが下請けを起こす時の模型で、正本に数えない（works の段は Archon が
    run_by の役として起こすので、役の前付けだけが正本）"""

    def setUp(self):
        self.nodes = ai_nodes()
        self.roles = stage_roles()

    def test_stage_model_matches_role_frontmatter(self):
        self.assertEqual(model_mismatches(self.nodes, self.roles), [])

    def test_frontmatter_models_are_pinned(self):
        """前付けに書いた model は全部 PINNED に在る（無いと expected_model が None を返し、その役の段は黙って run の既定で走る）"""
        models = {frontmatter_model(r) for r in set(self.roles.values())} - {None}
        self.assertEqual(sorted(models - PINNED), [])
        self.assertEqual(sorted(PINNED - models), [], "PINNED に前付けで使われていない模型が在る")

    def test_stage_effort_matches_role_frontmatter(self):
        self.assertEqual(effort_mismatches(self.nodes, self.roles), [])

    def test_effort_bad_examples_are_caught(self):
        """前付けどおりに直した写しは 0 件。judge の段から effort: を抜く・medium に替える・writer の段に effort: を足すと 1 件ずつ名指す"""
        fixed = {place: dict({k: v for k, v in n.items() if k != "effort"},
                             **({"effort": w} if (w := frontmatter_effort(self.roles[place])) else {}))
                 for place, n in self.nodes.items() if place in self.roles}
        self.assertEqual(effort_mismatches(fixed, self.roles), [])
        judge = next(p for p in sorted(fixed) if self.roles[p] == "judge")
        writer = next(p for p in sorted(fixed) if self.roles[p] == "writer")
        bare = {**fixed, judge: {k: v for k, v in fixed[judge].items() if k != "effort"}}
        self.assertEqual(len(effort_mismatches(bare, self.roles)), 1)
        self.assertEqual(len(effort_mismatches({**fixed, judge: dict(fixed[judge], effort="medium")}, self.roles)), 1)
        self.assertEqual(len(effort_mismatches({**fixed, writer: dict(fixed[writer], effort="high")}, self.roles)), 1)

    def test_no_workflow_level_model(self):
        for p in workflow_files():
            with self.subTest(p.name):
                head = yaml.safe_load(p.read_text(encoding="utf-8"))
                self.assertNotIn("model", head)
                self.assertNotIn("effort", head)

    def test_bad_examples_are_caught(self):
        """前付けどおりに直した写しは 0 件。PINNED の各値について、その役の段から model: を抜く・前付けと違う PINNED の値を
        書くと 1 件ずつ名指す。前付けに model の無い役の段に model: を足しても 1 件名指す"""
        fixed = {place: dict(n, **({"model": w} if (w := expected_model(self.roles[place])) else {}))
                 for place, n in self.nodes.items() if place in self.roles}
        self.assertEqual(model_mismatches(fixed, self.roles), [])
        for want in sorted(PINNED):
            with self.subTest(want):
                place = next((p for p in sorted(fixed) if expected_model(self.roles[p]) == want), None)
                self.assertIsNotNone(place, f"前付けが {want} の役の段が無い（見本が空振りする）")
                dropped = {**fixed, place: {k: v for k, v in fixed[place].items() if k != "model"}}
                self.assertEqual(len(model_mismatches(dropped, self.roles)), 1)
                other = next(m for m in sorted(PINNED) if m != want)
                swapped = {**fixed, place: dict(fixed[place], model=other)}
                self.assertEqual(len(model_mismatches(swapped, self.roles)), 1)
        writer = next(p for p in sorted(fixed) if self.roles[p] == "writer")
        for m in sorted(PINNED):
            with self.subTest(writer=m):
                added = {**fixed, writer: dict(fixed[writer], model=m)}
                self.assertEqual(len(model_mismatches(added, self.roles)), 1)

    def test_no_reverse_fence_on_the_model_word(self):
        """段の model: は上の柵が前付けと縛る。118 件目で外した段の字の禁止（REVERSE_FENCE の 2 形）を試験に戻さない"""
        hits = reverse_fence_hits(sorted(pathlib.Path(__file__).parent.glob("*.py")))
        self.assertEqual(hits, [], "model の字を禁じる柵が残っている（段に model: を書くと赤になる）")

    def test_reverse_fence_bad_examples(self):
        """外した 2 形は引用を変えても当たり、段の柵でない否定（版の控えの欄・工程の頭）と肯定の呼び出しは当たらない"""
        call = "self.assertNotIn("  # 見本は字を分けて組む（この行が上の走査に当たらないように）
        bad = [call + '"model", yaml.safe_dump(self.y))', call + "'model', role)", call + "'model', yaml.safe_dump(n))"]
        good = [call + '"model", doc["unknown"])', call + '"model", yaml.safe_load(p.read_text(encoding="utf-8")))',
                'self.assertIn("model", role)', 'self.assertEqual(n["model"], "sonnet")']
        self.assertEqual([s for s in bad if not REVERSE_FENCE.search(s)], [])
        self.assertEqual([s for s in good if REVERSE_FENCE.search(s)], [])


if __name__ == "__main__":
    unittest.main()
