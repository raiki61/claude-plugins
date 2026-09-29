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
import ast
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


def frontmatter_model(run_by: str):
    """core/agents/<役>.md の前付けの model:（役の定義が無ければ None）"""
    p = ROOT / ".shared" / "core" / "agents" / f"{run_by}.md"
    if not p.is_file():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8").split("---", 2)[1]).get("model")


def default_model() -> str:
    """guard.sh の WORKS_DEV_MODEL_DEFAULT（全体の既定。env では替わらない定数）"""
    for ln in (ROOT / "dev" / "guard.sh").read_text(encoding="utf-8").splitlines():
        if ln.startswith("WORKS_DEV_MODEL_DEFAULT="):
            return ln.split("=", 1)[1].strip().strip("'\"")
    raise AssertionError("guard.sh に WORKS_DEV_MODEL_DEFAULT= の行が無い")


def stage_roles() -> dict:
    """{(フォルダ, 節): 本線の run_by}（表 ROLE_NODES を graph の run_by で引き、EXTRA_ROLES を足す）"""
    run_by = graph_run_by()
    out = {place: run_by[gid] for gid, place in ROLE_NODES.items()}
    out.update(EXTRA_ROLES)
    return out


def expected_model(run_by: str, default: str):
    """段に書くべき model:。前付けが全体の既定と違う役だけ前付けの値、ほかは None（書かない）"""
    want = frontmatter_model(run_by)
    return want if want not in (None, default) else None


def model_mismatches(nodes: dict, roles: dict, default: str) -> list:
    """段の model: が役の前付けから決まる値と食い違う段を名指す。役に引き当てられない AI の段も名指す"""
    out = []
    for place, node in sorted(nodes.items()):
        if place not in roles:
            out.append(f"{place[0]} の段 {place[1]}: 役に引き当てられない（表 ROLE_NODES・EXTRA_ROLES に無い）")
            continue
        want, have = expected_model(roles[place], default), node.get("model")
        if have != want:
            out.append(f"{place[0]} の段 {place[1]}（役 {roles[place]}）: model: {have!r}（期待 {want!r}）")
    return out


# 逆向きの柵の形: 字 model（引用は ' か "、YAML の生の字の model: も）が無いことを見る否定の assert。何に当てたかは問わない。
# 呼び出しと assert 文を ast.unparse で 1 行に均した本文に当てる（折り返しに依らない）
MODEL_WORD = r"""['"]model:?['"]"""
REVERSE_FENCE = re.compile(
    rf"assertNotIn\(\s*{MODEL_WORD}"                              # assertNotIn("model", 何でも)
    rf"|assertNotRegex\(.*{MODEL_WORD}"                            # 生の字に当てる否定の正規表現
    rf"|{MODEL_WORD}\s+not\s+in\b"                                 # "model" not in 何でも
    rf"|(assertFalse\(|assert\s+not\b).*{MODEL_WORD}\s+in\b"       # assertFalse("model" in …)・assert not "model" in …
    rf"|assertIsNone\(.*\.get\(\s*{MODEL_WORD}")                   # assertIsNone(節.get("model"))
# 当たるが工程の段の柵ではない呼び出し（ファイル名, 呼び出しの本文）→ 理由。消えたら表からも消す（test_allowed_hits_still_exist）
NOT_A_STAGE_FENCE = {
    ("test_versions.py", 'self.assertNotIn("model", doc["unknown"])'): "版の控え versions.json の unknown の欄",
    ("test_versions.py", 'self.assertIsNone(doc.get("model", "absent"))'): "版の控え versions.json の model の欄",
    ("test_tool_parity.py", 'self.assertNotIn("model", yaml.safe_load(p.read_text(encoding="utf-8")))'):
        "工程の頭の柵（test_no_workflow_level_model）",
}


def asserted_calls(src: str) -> list:
    """[(行, 本文)]。呼び出しと assert 文を ast.unparse で 1 行に均す（折り返し・引用の違いが消える）"""
    return [(n.lineno, ast.unparse(n)) for n in ast.walk(ast.parse(src)) if isinstance(n, (ast.Call, ast.Assert))]


def reverse_fence_hits(files) -> list:
    """REVERSE_FENCE に当たり NOT_A_STAGE_FENCE に無い呼び出しを「ファイル名:行」で名指す"""
    allowed = {(name, ast.unparse(ast.parse(src))) for name, src in NOT_A_STAGE_FENCE}
    hits = {(p.name, i) for p in files for i, s in asserted_calls(p.read_text(encoding="utf-8"))
            if REVERSE_FENCE.search(s) and (p.name, s) not in allowed}
    return [f"{name}:{i}" for name, i in sorted(hits)]


class RoleModelCase(unittest.TestCase):
    """Archon の段は役の前付けを読まない。前付けの model が全体の既定と違う役の段だけ段の model: に同じ値を書き、
    ほかの段と工程の頭には書かない（持ち主 2026-09-29）。
    graph の節の delegate.model は本線の主のセッションが下請けを起こす時の模型で、正本に数えない（works の段は Archon が
    run_by の役として起こすので、役の前付けだけが正本）"""

    def setUp(self):
        self.nodes = ai_nodes()
        self.roles = stage_roles()
        self.default = default_model()

    def test_stage_model_matches_role_frontmatter(self):
        self.assertEqual(model_mismatches(self.nodes, self.roles, self.default), [])

    def test_stages_without_a_distinct_role_model_have_none(self):
        plain = {p: n for p, n in self.nodes.items()
                 if p not in self.roles or expected_model(self.roles[p], self.default) is None}
        self.assertEqual(model_mismatches(plain, self.roles, self.default), [])

    def test_no_workflow_level_model(self):
        for p in workflow_files():
            with self.subTest(p.name):
                self.assertNotIn("model", yaml.safe_load(p.read_text(encoding="utf-8")))

    def test_bad_examples_are_caught(self):
        """前付けどおりに直した写しは 0 件。3 役の段から model: を抜く・judge の段に model: opus を足すと 1 件ずつ名指す"""
        fixed = {place: dict(n, **({"model": w} if (w := expected_model(self.roles[place], self.default)) else {}))
                 for place, n in self.nodes.items() if place in self.roles}
        self.assertEqual(model_mismatches(fixed, self.roles, self.default), [])
        three = next(p for p in sorted(fixed) if expected_model(self.roles[p], self.default))
        dropped = {**fixed, three: {k: v for k, v in fixed[three].items() if k != "model"}}
        self.assertEqual(len(model_mismatches(dropped, self.roles, self.default)), 1)
        judge = next(p for p in sorted(fixed) if self.roles[p] == "judge")
        added = {**fixed, judge: dict(fixed[judge], model="opus")}
        self.assertEqual(len(model_mismatches(added, self.roles, self.default)), 1)

    def test_no_reverse_fence_on_the_model_word(self):
        """段の model: は上の柵が前付けと縛る。字 model が無いことを見る否定の assert（REVERSE_FENCE の形）を試験に残さない"""
        hits = reverse_fence_hits(sorted(pathlib.Path(__file__).parent.glob("*.py")))
        self.assertEqual(hits, [], "model の字を禁じる柵が残っている（段に model: を書くと赤になる）")

    def test_reverse_fence_bad_examples(self):
        """引用・変数名・書き方・折り返しを変えた逆向きの柵も当たり、字 model を肯定で見る呼び出しは当たらない"""
        bad = ["self.assertNotIn('model', node)", 'self.assertNotIn("model", self.top["review"])',
               'self.assertNotIn("model:", text)', "self.assertFalse('model' in n)", 'assert not "model" in n',
               'self.assertTrue("model" not in yaml.safe_dump(self.y))', 'self.assertNotRegex(text, "model:")',
               'self.assertIsNone(n.get("model"))', 'self.assertNotIn(\n    "model", node)',
               'self.assertIsNone(\n    n.get("model"))', 'assert (\n    "model"\n    not in n)']
        good = ['self.assertEqual(n["model"], "sonnet")', 'self.assertIn("model", row)',
                'self.assertEqual(n.get("model"), want)', 'bad = ["self.assertNotIn(\'model\', node)"]']
        fenced = lambda src: any(REVERSE_FENCE.search(s) for _, s in asserted_calls(src))
        self.assertEqual([s for s in bad if not fenced(s)], [])
        self.assertEqual([s for s in good if fenced(s)], [])

    def test_allowed_hits_still_exist(self):
        here = pathlib.Path(__file__).parent
        gone = [k for k in NOT_A_STAGE_FENCE if ast.unparse(ast.parse(k[1]))
                not in {s for _, s in asserted_calls((here / k[0]).read_text(encoding="utf-8"))}]
        self.assertEqual(gone, [])


if __name__ == "__main__":
    unittest.main()
