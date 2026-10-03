"""修正案と事前審査のブロック（blk-plan。P1 計画 Task 25・〔線A計〕T11・裁定 P1-R10・R44・R50）の検査。

- 独立設計（r2.design）: 修正案より前に道具ゼロの役で作り、盤面の根の design.json に控える（core の design）。事前審査の指示書の
  頭にその設計が載る。3 回とも拒まれても止めず、事前審査は「設計が無い」と読んで進む（人の条件 (2)）。目的の出典が R2 に使えない
  run は起こさない（写しの p4.assemble と同じ式を、p4.assemble より前に元の出典から出す）

- YAML の形: 役の output_format が planblk.output_format（写しの schema に印）と同じ・輪の中の id が全部のブロックをまたいで一意・
  役の輪は 1 輪 1 AI の節で fresh_context（直しの役の輪だけは会話の続きで false）・諦めの数と max_iterations が同じ・until_bash は
  同じ輪の受け付けの done・事前審査は壁打ちの外の輪 converge-loop の中（輪の中の輪。依頼 231）・スクリプトが読む INPUTS_* と
  with: の鍵が同じ・役に届く文に $LOOP_PREV が無い・筋書き 3 本
- スクリプト: 別のプロセスで Archon と同じ形（cwd は対象・ARTIFACTS_DIR・INPUTS_*）に回す。盤面は linekit の種で start →
  並行 PR・前提・判定を entry.take で受けた物（p2.fix_plan が待つ）。指示書は本線の写し（gl-prompts）を rolekit の描き方で描いた物
"""
import copy
import fcntl
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

import yaml

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
BLK = ROOT / "blk-plan"
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(BLK / "lib"))
sys.path.insert(0, str(ROOT / "blk-eyes" / "lib"))
sys.path.insert(0, str(ROOT / "blk-material" / "lib"))
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

import accept  # noqa: E402
import board as board_mod  # noqa: E402
import converge  # noqa: E402
import design  # noqa: E402
import engine.rules as engine_rules  # noqa: E402
import engine.util as engine_util  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
import entry  # noqa: E402
import eyes  # noqa: E402
import gatemarks  # noqa: E402
import linekit  # noqa: E402
import material  # noqa: E402
import node_marker  # noqa: E402
import libdocs  # noqa: E402
import planblk  # noqa: E402
import planmarks  # noqa: E402
import reads  # noqa: E402
import report  # noqa: E402
import rolekit  # noqa: E402

DEADLINE = 1728000000
RUN_ID = "run-plan"
UNIT_MEAN = "stats.py mean: 分母が len(xs) - 1 になっている"
UNIT_CLAMP = "stats.py clamp: 上限を超えた値に lo を返す"
# 義務の無い単位（受け付けが受けない）と、fork の問いの出どころ（ScriptCase.mixed が判定に足す）
NIT = "stats.py mean: 変数名が短い"
INFO = "stats.py: 型注釈が無い"
DEFER = "stats.py: 他の統計の関数と書き方を揃える"
QUESTION = "stats.py mean: 空の列の意味が決まっていない"
ASKED = "stats.py clamp: lo > hi の扱いが割れる"
BACK = "stats.py mean: 浮動小数の和の誤差"
# 盤面の置き場の錠のファイル名（正本から引く）。blk-plan は錠を取らない
BOARD_LOCKS = (eyes.LOCK_NAME, material.LOCK)
NARROWS = [{"what": "空の列の mean", "why": "空の列の平均は 0 割りの例外のまま（前も例外で、狭まる能力は無いが人に確かめる）",
            "no_narrow": "空の列で例外を投げる今の動きを残すと、直したい呼び手の 0 返しが成り立たないので狭めない案は無い"}]


def workflow():
    return yaml.safe_load((BLK / "blk-plan.yaml").read_text(encoding="utf-8"))


def walk(nodes, inside=None):
    for n in nodes or []:
        yield n, inside
        if "loop_group" in n:
            yield from walk(n["loop_group"].get("nodes"), n)


def script_module(name):
    spec = importlib.util.spec_from_file_location(f"_blk_plan_{name}", BLK / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def script_inputs(name):
    return script_module(name).INPUTS


def in_include(include: str, fn, *args):
    """fn(*args) を、読んだ証拠の出来事の節の名の include を include に固めて呼ぶ（core の reads.node_here は Archon が渡す
    今の scope から引く。盤面の置き場は今の試験の置き場のまま）"""
    with mock.patch.object(reads, "node_here", lambda loop, node: reads.node_path(include, loop, node)):
        return fn(*args)


class YamlCase(unittest.TestCase):
    def setUp(self):
        self.y = workflow()
        self.top = {n["id"]: n for n in self.y["nodes"]}

    def loops(self):
        """修正案・直し・事前審査の輪と、それを包む壁打ちの輪 converge-loop（入れ子も辿る。独立設計の輪は別に見る）"""
        return [n for n, _ in walk(self.y["nodes"]) if "loop_group" in n and n["id"] != f"{planblk.DESIGN_ROLE}-loop"]

    def every(self):
        """{id: 節}（入れ子の輪の中も）"""
        return {n["id"]: n for n, _ in walk(self.y["nodes"])}

    def test_inputs_and_exit(self):
        self.assertEqual(set(self.y["inputs"]), {"judgment_file", "base_rev", "policy_paste", "policy_path", "excluded_file",
                                                 "replan"})   # include の名は入力に持たない（core が引く。依頼 239）
        self.assertEqual(self.y["inputs"]["replan"]["default"], "")
        self.assertIs(self.y["inputs"]["judgment_file"]["required"], True)
        self.assertEqual((self.y["returns"], self.y["outcome_field"]), ("collect", "ok"))
        self.assertEqual(set(self.top["collect"]["output_format"]["required"]),
                         {"ok", "plan_file", "review_file", "asks_human", "gate_kinds", "reads_file", "gave_up", "reason_file"})

    def test_output_format_matches_graph(self):
        """役の output_format（入れ子の輪の中も）== planblk.output_format。壁打ちの欄（converge.with_fields）を外して strip した値
        == 写しの role_schema。印の名は plan・plan-revise（修正案の役の会話の続き continue=plan）・plan-review・r2-design（道具ゼロの
        旗 isolated）"""
        got = {}
        for grp in self.loops() + [self.top[f"{planblk.DESIGN_ROLE}-loop"]]:
            ai = [m for m in grp["loop_group"]["nodes"] if "prompt" in m or "command" in m]
            if ai:
                got[ai[0]["id"]] = ai[0]["output_format"]
        self.assertEqual(set(got), {"plan", planblk.REVISE_ROLE, "plan-review", planblk.DESIGN_ROLE})
        of = got.pop(planblk.DESIGN_ROLE)
        self.assertEqual(of, planblk.output_format(planblk.DESIGN_ROLE))
        self.assertEqual(node_marker.strip(of), accept.role_schema(design.NODE))
        self.assertEqual(of["description"], f"works-node: {planblk.DESIGN_ROLE} isolated")
        marks = {"plan": "works-node: plan", planblk.REVISE_ROLE: "works-node: plan-revise continue=plan",
                 "plan-review": "works-node: plan-review"}
        for role, of in got.items():
            with self.subTest(role):
                self.assertEqual(of, planblk.output_format(role))
                bare = node_marker.strip(of)
                if role in converge.FIELDS:
                    name = converge.FIELDS[role][0]
                    self.assertIn(name, bare["properties"])
                    del bare["properties"][name]
                    bare["required"] = [k for k in bare["required"] if k != name]
                self.assertEqual(bare, accept.role_schema(planblk.known_role(role), numbered=True))
                self.assertEqual(of["description"], marks[role])

    def test_converge_loop_wraps_revise_and_review(self):
        """壁打ちの輪: 中は直しの役の写し・輪・事前審査の写し・輪・出口の順。抜けるのは converge-check の done（max_iterations で
        落とさない。R50）。独立設計と最初の修正案は輪の外で先に 1 度"""
        inner = {m["id"]: m for m in self.top["converge-loop"]["loop_group"]["nodes"]}
        self.assertEqual(list(inner), ["plan-revise-snap", "plan-revise-loop", "plan-review-snap", "plan-review-loop",
                                       "converge-check"])
        g = self.top["converge-loop"]["loop_group"]
        self.assertEqual(g["max_iterations"], planblk.GIVE_UP_AFTER)
        self.assertEqual(g["until_bash"], "test $converge-check.output.done = true")
        self.assertIs(g["fresh_context"], True)
        ids = [n["id"] for n in self.y["nodes"]]
        self.assertLess(ids.index(f"{planblk.DESIGN_ROLE}-loop"), ids.index("converge-loop"))   # 独立設計は輪の外で先に 1 度
        self.assertLess(ids.index("plan-loop"), ids.index("converge-loop"))
        self.assertEqual(self.top["converge-loop"]["depends_on"], ["plan-snap", "plan-loop"])
        self.assertEqual(self.top["converge-loop"]["trigger_rule"], "none_failed_min_one_success")
        self.assertNotIn("when", self.top["converge-loop"])
        self.assertEqual(inner["plan-revise-snap"]["with"], {"role": planblk.REVISE_ROLE, "replan": "$INPUTS.replan"})
        self.assertEqual(inner["converge-check"]["with"], {"replan": "$INPUTS.replan"})   # 2 度目の include では 1 往復で done
        self.assertNotIn("depends_on", inner["plan-revise-snap"])
        self.assertEqual(inner["plan-review-snap"]["depends_on"], ["plan-revise-snap", "plan-revise-loop"])
        self.assertEqual(inner["converge-check"]["script"], "converge")
        self.assertEqual(inner["converge-check"]["depends_on"], ["plan-review-snap", "plan-review-loop"])
        self.assertEqual(set(inner["converge-check"]["output_format"]["required"]), {"ok", "done", "outcome", "record_file"})
        self.assertEqual(self.top["plan-reads"]["depends_on"], ["converge-loop"])
        self.assertEqual(planblk.READS_LOOP["plan-review"], "converge-loop.plan-review-loop")   # 読んだ証拠が引く輪の名と同じ形

    def test_revise_continues_plan_conversation(self):
        """直しの役 plan-revise: 修正案の役の会話の続き（印 continue=plan。会話を継ぐのは包みで、節に context は書かない）。輪は
        fresh_context false（出し直しも同じ会話に積む。blk-fix の fix-ruled-loop と同じ）。道具と段は修正案の節と同じ"""
        every = self.every()
        role, plan, loop = every[planblk.REVISE_ROLE], every["plan"], every["plan-revise-loop"]
        self.assertEqual(role["output_format"], planblk.output_format(planblk.REVISE_ROLE))
        self.assertEqual(node_marker.parse(role["output_format"]["description"])["cont"], "plan")
        self.assertNotIn("context", role)
        self.assertIs(loop["loop_group"]["fresh_context"], False)
        self.assertEqual(loop["when"], "$plan-revise-snap.output.go == true")
        self.assertEqual(loop["depends_on"], ["plan-revise-snap"])
        for k in ("allowed_tools", "settingSources", "sandbox", "mutates_checkout", "idle_timeout", "model", "effort"):
            self.assertEqual(role.get(k), plan.get(k), k)
        self.assertEqual(every["plan-revise-prep"]["with"], {"role": planblk.REVISE_ROLE, "excluded_file": "$INPUTS.excluded_file",
                                                            "replan": "$INPUTS.replan"})
        self.assertEqual(every["plan-revise-accept"]["with"],
                         {"role": planblk.REVISE_ROLE, "reply": {"from": f"${planblk.REVISE_ROLE}.output"},
                          "replan": "$INPUTS.replan"})

    def test_design_loop_first_and_tool_less(self):
        """独立設計の輪は修正案より前（plan-snap がその後を待つ）。道具ゼロで印に旗 isolated、指示書の本文は commands/r2-design.md が
        直の参照 1 つで貼る。出し直しは同じ会話（本線の --resume と同じ）。3 回目の拒否で done"""
        role = planblk.DESIGN_ROLE
        ids = [n["id"] for n in self.y["nodes"]]
        self.assertLess(ids.index(f"{role}-loop"), ids.index("plan-snap"))
        self.assertEqual(self.top["plan-snap"]["depends_on"], [f"{role}-snap", f"{role}-loop"])
        self.assertEqual(self.top["plan-snap"]["trigger_rule"], "none_failed_min_one_success")
        loop = self.top[f"{role}-loop"]
        self.assertEqual(loop["when"], f"${role}-snap.output.go == true")
        g = loop["loop_group"]
        self.assertEqual(g["max_iterations"], design.GIVE_UP_AFTER)
        self.assertEqual(g["until_bash"], f"test ${role}-accept.output.done = true")
        self.assertIs(g["fresh_context"], False)
        self.assertEqual([m["id"] for m in g["nodes"]], [f"{role}-prep", role, f"{role}-accept"])
        ai = g["nodes"][1]
        self.assertEqual((ai["command"], ai["allowed_tools"]), (role, []))
        self.assertEqual(node_marker.parse(ai["output_format"]["description"])["flags"], frozenset({"isolated"}))
        text = (BLK / "commands" / f"{role}.md").read_text(encoding="utf-8")
        self.assertEqual(re.findall(r"\$[A-Za-z_][A-Za-z0-9_-]*\.output\.[A-Za-z_]+", text), [f"${role}-prep.output.prompt"])
        self.assertNotIn("{{", text)

    def test_loops_fresh_single_ai_and_give_up(self):
        """役の輪（入れ子も）は 1 輪 1 AI の節・諦めの数 == max_iterations・until_bash は同じ輪の受け付けの done。外れは 2 つだけで、
        ここに名指す（決まりを弱めたのではない。F10）:
        - converge-loop は AI の節を直に持たない外の輪。見るのは中の節の並び・until_bash・max_iterations だけ
          （test_converge_loop_wraps_revise_and_review）
        - plan-revise-loop は fresh_context false（blk-fix の fix-ruled-loop と同じ。会話を継ぐのは印 continue=plan）"""
        outer, carried = "converge-loop", f"{planblk.REVISE_ROLE}-loop"
        seen = set()
        for grp in self.loops():
            g = grp["loop_group"]
            if grp["id"] == outer:
                self.assertEqual([m for m in g["nodes"] if "prompt" in m or "command" in m], [])
                continue
            role = next(m for m in g["nodes"] if "prompt" in m or "command" in m)
            seen.add(grp["id"])
            with self.subTest(role["id"]):
                self.assertIs(g["fresh_context"], grp["id"] != carried)
                self.assertEqual(g["max_iterations"], planblk.GIVE_UP_AFTER, "諦めの数は輪の上限と同じ（上限で輪を落とさない）")
                self.assertEqual(len([m for m in g["nodes"] if "prompt" in m or "command" in m]), 1)
                self.assertEqual([m["id"] for m in g["nodes"]], [f"{role['id']}-prep", role["id"], f"{role['id']}-accept"])
                self.assertEqual(grp["id"], f"{role['id']}-loop")
                self.assertEqual(g["until_bash"], f"test ${role['id']}-accept.output.done = true")
                self.assertEqual(role["allowed_tools"], ["Read", "Grep", "Glob", "WebSearch", "WebFetch"])
                self.assertEqual(role["settingSources"], ["user"])
                self.assertEqual(role["idle_timeout"], DEADLINE)
                self.assertNotIn("context", role)
                self.assertIn(f"${role['id']}-prep.output.prompt_file", role["prompt"])
                self.assertEqual(grp["when"], f"${role['id']}-snap.output.go == true")
        self.assertEqual(seen, {"plan-loop", carried, "plan-review-loop"})

    def test_script_inputs_match_with(self):
        for n, _ in walk(self.y["nodes"]):
            if "script" not in n:
                continue
            with self.subTest(n["id"]):
                want = {f"INPUTS_{k.upper()}" for k in (n.get("with") or {})}
                mod = script_module(n["script"])
                self.assertEqual(set(mod.INPUTS), want)
                self.assertEqual(set(mod.OPTIONAL), {"INPUTS_REPLAN"}, "後から足した replan だけが無くてよい（無い・空は今どおり）")
                self.assertEqual(n["with"]["replan"], "$INPUTS.replan", "同じ script を回す節は全部 replan を渡す")
                self.assertEqual((n["timeout"], n["runtime"]), (DEADLINE, "uv"))
                if "role" in (n.get("with") or {}):
                    self.assertEqual(n["id"].rsplit("-", 1)[0], n["with"]["role"])

    def test_no_loop_prev_reaches_a_prompt(self):
        """役に届く文に $LOOP_PREV が無い（理由はファイルで。R44）。手で書いた commands は、ファイルを読めない道具ゼロの独立設計の
        役が描いた本文を貼るための 1 本だけ（P1-R10）"""
        for n, _ in walk(self.y["nodes"]):
            self.assertNotIn("$LOOP_PREV", str(n.get("prompt", "")), n["id"])
        self.assertEqual({p.name for p in (BLK / "commands").iterdir()}, {f"{planblk.DESIGN_ROLE}.md"})
        self.assertNotIn("$LOOP_PREV", (BLK / "commands" / f"{planblk.DESIGN_ROLE}.md").read_text(encoding="utf-8"))

    def test_after_loop_nodes_join(self):
        every = self.every()
        for nid in ("plan-snap", "converge-loop", "plan-review-snap", "converge-check", "plan-reads"):
            self.assertEqual(every[nid]["trigger_rule"], "none_failed_min_one_success", nid)
            self.assertNotIn("when", every[nid])

    def test_loop_ids_unique_across_blocks(self):
        """blk-plan の輪の中の id が、ほかの全部のブロック・ラインの輪の中の id と重ならない（R19）"""
        mine = {n["id"] for n, inside in walk(self.y["nodes"]) if inside is not None} | {g["id"] for g in self.loops()}
        others = set()
        for p in sorted(ROOT.glob("*/*.yaml")):
            if p.parent == BLK:
                continue
            y = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
            others |= {n["id"] for n, inside in walk(y.get("nodes")) if inside is not None or "loop_group" in n}
        self.assertEqual(mine & others, set())

    def test_fixtures(self):
        fx = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in (BLK / "fixtures").glob("*.stubs.yaml")}
        self.assertEqual(set(fx), {"pass.stubs.yaml", "plan-rejected.stubs.yaml", "give-up.stubs.yaml"})
        p = fx["pass.stubs.yaml"]
        self.assertEqual(p["fixture"]["expect"], "completed")
        self.assertEqual(p["plan"], linekit.reply("plan_ok"))
        self.assertEqual(p["plan-review"], linekit.reply("plan_review_ok"))
        self.assertIs(p["collect"]["ok"], True)
        self.assertIn("collect", p["fixture"]["reached"])
        r = fx["plan-rejected.stubs.yaml"]
        self.assertIs(r["plan-accept"]["ok"], False)
        self.assertIs(r["plan-accept"]["done"], False)
        self.assertIn("until_bash を回さず", (BLK / "fixtures" / "plan-rejected.stubs.yaml").read_text(encoding="utf-8"))
        g = fx["give-up.stubs.yaml"]
        self.assertEqual((g["plan-accept"]["done"], g["plan-accept"]["give_up"]), (True, True))
        self.assertIs(g["plan-review-snap"]["go"], False)
        self.assertNotIn("plan-review", g, "輪が飛ぶ（役の stub を置かない）")
        self.assertEqual((g["collect"]["ok"], g["collect"]["gave_up"]), (False, True))
        for name, f in fx.items():
            self.assertIn("r2-design-snap", f["fixture"]["reached"], name)
            # 壁打ちの輪の 1 周目: 返した block の控えがまだ無いので直しの役の輪は飛ぶ（go: false）。dry-run は until_bash を
            # 回さないので出口の done は抜けた後の姿（真）
            self.assertIs(f["plan-revise-snap"]["go"], False, name)
            self.assertNotIn(planblk.REVISE_ROLE, f, name)
            self.assertIs(f["converge-check"]["done"], True, name)
            for nid in ("plan-revise-snap", "converge-check"):
                self.assertIn(nid, f["fixture"]["reached"], name)
            for role in ("plan", "plan-review", planblk.DESIGN_ROLE):
                if role in f:
                    with self.subTest(f"{name}:{role}"):
                        self.assertEqual(validate_schema(f[role], planblk.output_format(role)), [])


def suggest_regression() -> dict:
    """plan_review_regression の穴を severity suggest にした返答（kind regression の穴は関所で聞く。block の穴は壁打ちで修正案へ
    返るので、1 往復で関所まで進む試験はこの形を使う。block の往復は ConvergeReviewCase）"""
    review = linekit.reply("plan_review_regression")
    review["faces"][0]["severity"] = "suggest"
    return review


class ScriptCase(unittest.TestCase):
    def setUp(self):
        self._old_cwd = engine_util.GIT_CWD
        self.addCleanup(setattr, engine_util, "GIT_CWD", self._old_cwd)
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)
        self.home = self.tmp / "adapter-home"
        env = mock.patch.dict("os.environ", {"WORKS_ADAPTER_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)

    # -- 盤面
    def take(self, nid, reply):
        b = entry.open_board(self.board)
        inst = b.rd["instances"][nid]
        b.mark_launched(nid, inst.get("attempts", 1))
        got = entry.take(self.board, nid, reply, self.repo)
        self.assertTrue(got["ok"], got)
        return got

    def judged(self, policy_md="", judge=None):
        """start → 並行 PR の任せ先・前提の役 → 判定（judge。無ければ judge_ok）を受けた盤面（p2.fix_plan が待つ）"""
        self.repo = linekit.seed_repo(self.tmp / "repo", declared=True)
        req = self.tmp / "req" / "request.json"
        req.parent.mkdir(parents=True)
        req.write_text((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.art = self.tmp / "art"
        self.board = self.art / "board"
        raw = {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "final_gate": "", "adapter": "",
               "policy_md": policy_md}
        entry.start(self.board, self.repo, raw, run_id=RUN_ID)
        self.take("p0.parallel_pr", {k: v for k, v in linekit.reply("pr_no_conflicts").items() if k != "excluded"})
        self.take("p0.premises", {"constraints": []})
        linekit.pre_judge(self.board, self.repo)   # 目的の文（判定の前に盤面が待つ）
        self.take("p2.diagnose", judge or linekit.reply("judge_ok"))

    def state(self):
        return json.loads((self.board / "state.json").read_text(encoding="utf-8"))

    # -- スクリプト
    def run_script(self, name, drop=(), **inputs):
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_") and k not in ("WORKFLOW_ID", "ARCHON_CLI_COMMAND")}
        env.update({"WORKS_ADAPTER_HOME": str(self.home), "ARTIFACTS_DIR": str(self.art), "PYTHONDONTWRITEBYTECODE": "1"})
        env.update({f"INPUTS_{k.upper()}": v for k, v in inputs.items()})
        for k in drop:
            env.pop(k, None)
        r = subprocess.run([sys.executable, str(BLK / "scripts" / f"{name}.py")], cwd=str(self.repo), env=env,
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            lines = r.stdout.splitlines()
            self.assertEqual(len(lines), 1, r.stdout + r.stderr)
            return 0, json.loads(lines[0]), r.stderr
        return r.returncode, r.stdout, r.stderr

    def ok(self, name, **inputs):
        rc, out, err = self.run_script(name, **inputs)
        self.assertEqual(rc, 0, err)
        return out

    def round_of(self, role, reply, excluded=""):
        """1 周: prep → 役（返答は reply）→ accept。(prep, accept)"""
        prep = self.ok("prep", role=role, excluded_file=excluded)
        raw = reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False)
        return prep, self.ok("accept", role=role, reply=raw)

    def run_loop(self, role, reply):
        """Archon の輪と同じ順に回す（snap は輪の外で 1 回）。until_bash の式を sh で評価し、抜けた周の番号と各周を返す"""
        g = next(n for n in workflow()["nodes"] if n.get("id") == f"{role}-loop")["loop_group"]
        rounds = []
        for i in range(1, g["max_iterations"] + 1):
            prep, got = self.round_of(role, reply)
            rounds.append((prep, got))

            def value(m):
                self.assertEqual(m.group(1), f"{role}-accept")
                return json.dumps(got[m.group(2)])
            cond = re.sub(r"\$([A-Za-z0-9_-]+)\.output\.([A-Za-z0-9_]+)", value, g["until_bash"])
            if subprocess.run(["sh", "-c", cond]).returncode == 0:
                return i, rounds
        return None, rounds

    def planned(self, plan="plan_ok"):
        self.assertTrue(self.ok("snap", role="plan")["go"])
        _, got = self.round_of("plan", linekit.reply(plan) if isinstance(plan, str) else plan)
        self.assertTrue(got["ok"], got)
        return got

    def reason_of(self, got):
        return pathlib.Path(got["reason_file"]).read_text(encoding="utf-8")

    # -- 修正案
    def test_plan_ok_accepted(self):
        self.judged()
        got = self.planned()
        self.assertEqual((got["done"], got["give_up"], got["reason_file"]), (True, False, ""))
        self.assertIn("p2.plan_review", got["ready"])

    def test_plan_with_nit_unit_rejected_naming_label(self):
        """義務の無い nit の単位を案に入れた返答は、理由が label を名指して拒まれる（見せる一覧と受け付けの述語を合わせる）"""
        nit = "stats.py mean: 変数名が短い"
        judge = linekit.reply("judge_ok")
        judge["units"].append({"key": nit, "label": "nit", "reason": "事実: 名前が短い。反証: 無し",
                               "origin_analysis": "命名"})
        self.judged(judge=judge)
        self.ok("snap", role="plan")
        plan = linekit.reply("plan_ok")
        plan["plan"][0]["unit_keys"] = [UNIT_MEAN, UNIT_CLAMP, nit]
        _, got = self.round_of("plan", plan)
        self.assertFalse(got["ok"])
        self.assertIn("label=nit", self.reason_of(got))

    def test_not_allowed_skips_unit_missing_from_names(self):
        """義務の無い単位が今の no の一覧に無くても、事前の拒否は落ちず、その単位は受け付けの写しの拒否に任せる"""
        nit = "stats.py mean: 変数名が短い"
        judge = linekit.reply("judge_ok")
        judge["units"].append({"key": nit, "label": "nit", "reason": "事実: 名前が短い。反証: 無し",
                               "origin_analysis": "命名"})
        self.judged(judge=judge)
        self.ok("snap", role="plan")
        b = entry.open_board(self.board)
        plan = linekit.reply("plan_ok")
        plan["plan"][0]["unit_keys"] = [UNIT_MEAN, UNIT_CLAMP, nit]
        with mock.patch.object(planblk, "_names", return_value=[UNIT_MEAN, UNIT_CLAMP]), \
                mock.patch.object(planblk.pointers, "resolve"):
            self.assertEqual(planblk.not_allowed(b, "p2.fix_plan", plan), [])

    def test_plan_reply_by_number_rejects_unowed_unit(self):
        """本線の返答は no の整数で来る: 義務の無い単位を番号で指した案も、事前の拒否が label と no を名指して拒み、拒否文が入れてよい
        no を並べる（役の返答は書き換わらない）"""
        judge = linekit.reply("judge_ok")
        judge["units"].append({"key": NIT, "label": "nit", "reason": "事実: 名前が短い。反証: 無し", "origin_analysis": "命名"})
        self.judged(judge=judge)
        self.ok("snap", role="plan")
        self.ok("prep", role="plan", excluded_file="")
        names = planblk._names(entry.open_board(self.board), "p2.fix_plan")
        nit_no = names.index(NIT) + 1
        plan = linekit.reply("plan_ok")
        plan["plan"][0]["unit_keys"] = [names.index(UNIT_MEAN) + 1, names.index(UNIT_CLAMP) + 1, nit_no]
        sent = copy.deepcopy(plan)
        got = planblk.take("plan")(self.board, plan, self.repo)
        self.assertFalse(got["ok"])
        self.assertIn("label=nit", got["reason"])
        self.assertIn(f"no {nit_no} は", got["reason"])
        allowed = sorted(names.index(k) + 1 for k in (UNIT_MEAN, UNIT_CLAMP))
        self.assertIn(f"{planblk.NOT_OWED_REJECT} {allowed}", got["reason"])
        self.assertNotIn("頭の節", got["reason"])
        self.assertEqual(plan, sent)

    def test_take_malformed_plan_resubmits_not_raises(self):
        """形の崩れた修正案は例外でなく ok:false（再提出の道。accept は exit 2 で落ちない）。plan・行・narrows の形の崩れは take の頭で
        前段（narrow_gaps・not_allowed・split・save）を飛ばし、unit_keys の形の崩れは not_allowed が読み飛ばして、形の拒否を entry.take に任せる"""
        self.judged()
        self.ok("snap", role="plan")
        self.ok("prep", role="plan", excluded_file="")
        row = linekit.reply("plan_ok")["plan"][0]
        for name, reply in (("行が文字列", {"plan": ["x"]}), ("plan が文字列", {"plan": "s"}), ("plan が数", {"plan": 5}),
                            ("unit_keys が数", {"plan": [{**row, "unit_keys": 5}]}),
                            ("unit_keys が入れ子", {"plan": [{**row, "unit_keys": [[1]]}]}),
                            ("unit_keys が dict", {"plan": [{**row, "unit_keys": [{"a": 1}]}]}),
                            ("narrows が数", {"plan": [{**row, "narrows": 5}]})):
            with self.subTest(name):
                got = planblk.take("plan")(self.board, reply, self.repo)
                self.assertFalse(got["ok"], got)

    # -- 入れてよい no の節（planblk.plan_slots）と受け付けの写しの一致
    def mixed(self, extra_questions=(), closes=()):
        """judge_ok の 2 単位に、義務の無い単位（nit・info・suggest の defer・question）と、fork の問いの出どころ 2 つ（ASKED は
        人の答え待ちで入れてよい・BACK は関所で答えた体で必ず入れる。答えたかは answered_patch で決める）を足した判定を受けた盤面"""
        judge = linekit.reply("judge_ok")
        base = {k: v for k, v in judge["units"][0].items() if k not in ("class_query", "disposition")}
        why = "事実: 今の周の差分の範囲で読んだ形。反証: 同じ形を stats.py の他の関数に当たったが無い"
        for key, label, disp in ((NIT, "nit", None), (INFO, "info", None), (DEFER, "suggest", "defer"),
                                 (QUESTION, "question", None), (ASKED, "suggest", "do-now"), (BACK, "suggest", "do-now")):
            u = {**base, "key": key, "label": label, "reason": why, "origin_analysis": "見本の単位"}
            if disp:
                u["disposition"] = disp
            if disp == "do-now":
                u["class_query"] = judge["units"][0]["class_query"]
            judge["units"].append(u)
        judge["questions"] = [{"key": q, "kind": "fork", "status": "held", "origin": origin, "options": ["例外", "0 を返す"],
                               "reason": "呼び手ごとに意味が割れる。推し: 例外——呼び手が既に例外を捕まえている"}
                              for q, origin in (("q-asked", ASKED), ("q-back", BACK), *extra_questions)]
        judge["precedents"] += [{**judge["precedents"][0], "key": k} for k in (ASKED, BACK)]
        judge["precedents"] += [{**judge["precedents"][0], "key": q["key"],
                                 "undecided_because": "先行例が例外と 0 返しの 2 つに割れ、呼び手の期待も揃っていない"}
                                for q in judge["questions"]]
        judge["one_shot_closes"] += list(closes)
        self.judged(judge=judge)

    def judgment(self):
        """盤面が受けた判定の返答（p2.diagnose の出力のファイル）"""
        out = self.state()["outputs"]["p2.diagnose"]
        return json.loads((self.board / out["file"]).read_text(encoding="utf-8"))

    @staticmethod
    def answered_patch(*keys):
        """修正前の関所で問い keys に答えた体にする（gatemarks.answered。答えた fork の出どころは returned で直す義務に戻る）"""
        return mock.patch.object(gatemarks, "answered", lambda b, q: q.get("key") in keys)

    def test_plan_slots_equal_copy_acceptance(self):
        """plan_slots の必ず入れる・入れてよいが、写しの受け付け fix_plan_covers_units が実際に受ける集合と一致する: どの単位も、
        必ず入れる物に足した案が通るのは入れてよい物の時だけ・必ず入れる物を 1 つ欠いた案は拒まれる。必ず入れる ⊆ 入れてよい
        （役を起こす盤面で成り立つ不変条件。成り立たない盤面は snap・prep が止める）。事前の拒否 not_allowed も同じ単位を名指す"""
        self.mixed()
        with self.answered_patch("q-back"):
            b = entry.open_board(self.board)
            must, may, units = planblk.plan_slots(b)
            self.assertEqual(must, {UNIT_MEAN, UNIT_CLAMP, BACK})
            self.assertEqual(may, {UNIT_MEAN, UNIT_CLAMP, ASKED, BACK})
            self.assertLessEqual(must, may)

            def plan(keys):
                return {"plan": [{**linekit.reply("plan_ok")["plan"][0], "unit_keys": list(keys)}]}

            def copy_takes(keys):
                try:
                    b.rules.fix_plan_covers_units(b, "p2.fix_plan", plan(keys), None)
                except b.rules.Reject:
                    return False
                return True

            self.assertTrue(copy_takes(sorted(must) + sorted(may - must)))
            self.assertTrue(copy_takes(sorted(must)))
            for k in sorted(units):
                with self.subTest(add=k[:30]):
                    keys = sorted(must) + ([] if k in must else [k])
                    self.assertEqual(copy_takes(keys), k in may)
                    self.assertEqual(planblk.not_allowed(b, "p2.fix_plan", plan(keys)) == [], k in may)
            for k in sorted(must):
                with self.subTest(drop=k[:30]):
                    self.assertFalse(copy_takes(sorted(must - {k})))

    def test_stuck_owed_unit_halts_before_role(self):
        """必ず入れるのに開いていない単位（関所で答えた問いの出どころが defer）が在ると、写しの受け付けは入れても外しても拒む。
        prep は役の指示書を書かずに盤面を止め（by works:plan）、理由に PLAN_STUCK とその単位の no・key を書く"""
        self.mixed(extra_questions=(("q-defer", DEFER),))
        with self.answered_patch("q-defer"):
            b = entry.open_board(self.board)
            must, may, _ = planblk.plan_slots(b)
            self.assertIn(DEFER, must - may)
            for keys in (sorted(must), sorted(must - {DEFER})):   # 入れても外しても写しは拒む（案の形では閉じない）
                with self.assertRaises(b.rules.Reject):
                    b.rules.fix_plan_covers_units(b, "p2.fix_plan", {"plan": [{"unit_keys": keys}]}, None)
            no = planblk._names(b, "p2.fix_plan").index(DEFER) + 1
            with self.assertRaises(board_mod.BoardGap):
                planblk.prep(self.board, "plan", self.repo)
        self.assertFalse(entry.open_board(self.board, allow_halted=True).work(rolekit.prompt_name("p2.fix_plan")).exists())
        stop = self.state()["stop"]
        self.assertEqual(stop["by"], planblk.STOP_BY)
        self.assertIn(planblk.PLAN_STUCK, stop["reason"])
        self.assertIn(f"no {no}（{DEFER}）", stop["reason"])
        self.assertIn(planblk.STUCK_WHY, stop["reason"])

    def test_stuck_owed_unit_skips_plan_loop_at_snap(self):
        """行き止まりの単位が在る盤面は、輪の前の snap が盤面を止めて go: false を返す（輪の when で役を起こさない）。後の事前審査の
        snap は輪を飛ばし、出口は止めた理由を上書きしない"""
        self.mixed(extra_questions=(("q-defer", DEFER),))
        with self.answered_patch("q-defer"):
            got = planblk.snap(self.board, "plan", self.repo)
        self.assertEqual((got["go"], got["snapshot_file"]), (False, ""))
        self.assertFalse(planblk.snap(self.board, "plan-review", self.repo)["go"])
        out = planblk.collect(self.board)
        self.assertEqual((out["plan_file"], out["gave_up"]), ("", False))
        stop = self.state()["stop"]
        self.assertEqual(stop["by"], planblk.STOP_BY)
        self.assertIn(planblk.PLAN_STUCK, stop["reason"])

    def test_plan_slots_does_not_nest_board_lock(self):
        """plan_slots が validator を呼ぶ瞬間、盤面の置き場の錠（BOARD_LOCKS）を別の fd で待たずに取れる（prep と take の両方）。
        錠を握ったまま validator を読み込むと、同じ錠を取る口と入れ子で固まる"""
        self.mixed()
        self.ok("snap", role="plan")
        real, seen = engine_rules.validator_module, []

        def spy(b):
            for name in BOARD_LOCKS:
                with open(self.board / name, "a", encoding="utf-8") as f:
                    try:
                        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        seen.append((name, False))
                    else:
                        fcntl.flock(f, fcntl.LOCK_UN)
                        seen.append((name, True))
            return real(b)
        plan = linekit.reply("plan_ok")
        plan["plan"][0]["unit_keys"] = [UNIT_MEAN, UNIT_CLAMP, NIT]
        with mock.patch.dict(engine_rules.INJECT, {"validator_module": spy}):
            planblk.prep(self.board, "plan", self.repo)
            got = planblk.take("plan")(self.board, plan, self.repo)
        self.assertFalse(got["ok"])
        self.assertTrue(seen)
        self.assertEqual([n for n, free in seen if not free], [])

    def nested_board_lock_peeks(self):
        """eyes.locked が握る board.lock への、別の fd からの待つ flock（LOCK_EX・LOCK_NB 無し）を、待たずに LOCK_NB で覗いて
        控える（取れなければ BlockingIOError を投げ、本体の filelock と同じく呼び手が飲む）。最初の 1 回（locked 自身）は通す"""
        fcntl_fd = lambda f: f if isinstance(f, int) else f.fileno()  # noqa: E731
        lock = self.board / eyes.LOCK_NAME
        real, seen, outer = fcntl.flock, [], []

        def spy(fd, op):
            if op & fcntl.LOCK_EX and not op & fcntl.LOCK_NB and os.path.samestat(os.fstat(fcntl_fd(fd)), os.stat(lock)) and outer:
                try:
                    real(fd, op | fcntl.LOCK_NB)
                except BlockingIOError:
                    seen.append(lock.name)
                    raise
                real(fd, fcntl.LOCK_UN)
                return None
            outer.append(1) if op & fcntl.LOCK_EX else None
            return real(fd, op)
        return mock.patch.object(fcntl, "flock", spy), seen

    def test_eyes_locked_does_not_nest_engine_board_save(self):
        """eyes.locked が board.lock を握ったまま engine の Board.save を呼んでも、別の fd から同じ board.lock を待たない。
        今の写しの engine は board.lock を取らないので緑のまま通る（錠を 1 本にまとめる直しは後に置いた）。写しの engine を
        上げてこの試験が赤になったら、locked と engine の board_lock が入れ子で自分を待つ合図——錠をまとめる直しが要る。
        material._locked の錠は別のファイル（material.LOCK）で engine の錠と重ならないので、ここでは縛らない"""
        self.mixed()
        self.assertTrue(pathlib.Path(engine_rules.__file__).resolve().is_relative_to(CORE / "graphloops"),
                        "engine が写しでない（本体の engine を測っている）")
        patch, seen = self.nested_board_lock_peeks()
        with patch, eyes.locked(self.board):
            entry.open_board(self.board).save()
        self.assertEqual(seen, [])

    def test_nested_board_lock_peek_catches_a_second_flock_under_locked(self):
        """対照: locked の中で別の fd から待つ flock が来る形（engine が board_lock で取る形）なら、覗きが控えて赤にできる"""
        self.mixed()
        patch, seen = self.nested_board_lock_peeks()
        with patch, eyes.locked(self.board):
            with open(self.board / eyes.LOCK_NAME, "a", encoding="utf-8") as f:
                with self.assertRaises(BlockingIOError):
                    fcntl.flock(f, fcntl.LOCK_EX)
        self.assertEqual(seen, [eyes.LOCK_NAME])

    def test_plan_reply_with_info_defer_question_rejected_naming_label(self):
        """nit のほかの義務の無い単位（info・suggest の defer・question）を入れた案も、受け付けの手前で label を名指して拒む"""
        self.mixed()
        self.ok("snap", role="plan")
        self.ok("prep", role="plan", excluded_file="")
        for key, want in ((INFO, "label=info"), (DEFER, "disposition=defer"), (QUESTION, "label=question")):
            with self.subTest(want):
                plan = linekit.reply("plan_ok")
                plan["plan"][0]["unit_keys"] = [UNIT_MEAN, UNIT_CLAMP, key]
                got = planblk.take("plan")(self.board, plan, self.repo)
                self.assertFalse(got["ok"])
                self.assertIn(planblk.NOT_OWED_REJECT, got["reason"])
                self.assertIn(want, got["reason"])

    def test_slots_section_absent_when_every_unit_may_go(self):
        """全部の単位が入れてよい盤面（judge_ok）では節を貼らない（本文の一覧が受け付けの集合と同じ）"""
        self.judged()
        self.ok("snap", role="plan")
        self.assertEqual(planblk.plan_slots_section(entry.open_board(self.board)), "")
        text = pathlib.Path(self.ok("prep", role="plan", excluded_file="")["prompt_file"]).read_text(encoding="utf-8")
        self.assertNotIn(planblk.PLAN_SLOTS_HEAD, text)

    def test_slots_section_lists_must_may_and_shut(self):
        """節は必ず入れる no・入れてよい no・入れてはいけない no（label つき）を並べる。判定の one_shot_closes に nit が在っても、
        nit の no は入れてはいけない側に在る（節が one_shot_closes より優先する）。行き止まりの行は無い（その盤面は prep が止める）"""
        self.mixed(closes=(NIT,))
        self.assertIn(NIT, self.judgment()["one_shot_closes"])
        self.ok("snap", role="plan")
        with self.answered_patch("q-back"):
            b = entry.open_board(self.board)
            names = planblk._names(b, "p2.fix_plan")
            no = {k: names.index(k) + 1 for k in names}
            text = planblk.plan_slots_section(b)
        self.assertTrue(text.startswith(planblk.PLAN_SLOTS_HEAD))
        self.assertIn(f"- 必ず案に入れる no: {sorted(no[k] for k in (UNIT_MEAN, UNIT_CLAMP, BACK))}", text)
        self.assertIn(f"- 入れてもよい no（人の答え待ちの問いの出どころ・depends。入れなくてもよい）: {[no[ASKED]]}", text)
        shut = text.split("- 入れてはいけない no（受け付けが拒む）: ", 1)[1]
        for k, label in ((NIT, "nit"), (INFO, "info"), (DEFER, "suggest"), (QUESTION, "question")):
            self.assertIn(f"no {no[k]}（label={label}", shut)
        self.assertNotIn("拒まれたら理由をそのまま返せ", text)

    def test_plan_review_head_unchanged(self):
        """入れてよい no の節は修正案の頭にだけ貼り、事前審査の頭には出ない"""
        self.mixed()
        self.ok("snap", role="plan")
        prep, got = self.round_of("plan", linekit.reply("plan_ok"))
        self.assertTrue(got["ok"], got)
        self.assertIn(planblk.PLAN_SLOTS_HEAD, pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8"))
        self.assertTrue(self.ok("snap", role="plan-review")["go"])
        text = pathlib.Path(self.ok("prep", role="plan-review", excluded_file="")["prompt_file"]).read_text(encoding="utf-8")
        self.assertNotIn(planblk.PLAN_SLOTS_HEAD, text)

    def test_plan_missing_unit_rejected(self):
        self.judged()
        self.ok("snap", role="plan")
        _, got = self.round_of("plan", linekit.reply("plan_missing_unit"))
        self.assertEqual((got["ok"], got["done"]), (False, False))
        self.assertIn(UNIT_CLAMP, self.reason_of(got))

    def test_plan_dup_unit_rejected(self):
        self.judged()
        self.ok("snap", role="plan")
        _, got = self.round_of("plan", linekit.reply("plan_two_units_one_plan_dup"))
        self.assertFalse(got["ok"])
        self.assertIn(UNIT_MEAN, self.reason_of(got))

    def test_readonly_tree_changed_rejected(self):
        """plan-snap の後に作業ツリーを変える → 拒む。commit して HEAD を動かしても拒む（accept.tree_moved）"""
        self.judged()
        self.ok("snap", role="plan")
        self.ok("prep", role="plan", excluded_file="")
        (self.repo / "stats.py").write_text("# 変えた\n", encoding="utf-8")
        got = self.ok("accept", role="plan", reply=json.dumps(linekit.reply("plan_ok"), ensure_ascii=False))
        self.assertFalse(got["ok"])
        self.assertTrue(self.reason_of(got).startswith(entry.READONLY_MOVED))
        linekit.git(self.repo, "commit", "-qam", "役が commit した")
        got = self.ok("accept", role="plan", reply=json.dumps(linekit.reply("plan_ok"), ensure_ascii=False))
        self.assertFalse(got["ok"])
        self.assertIn("HEAD", self.reason_of(got))

    def test_plan_narrows_asks(self):
        """案の narrows → 事前審査が穴 0 件でも人に聞く（collect の asks_human・gate_kinds に regression）"""
        self.judged()
        plan = linekit.reply("plan_ok")
        plan["plan"][0]["narrows"] = NARROWS
        self.planned(plan)
        self.assertTrue(self.ok("snap", role="plan-review")["go"])
        _, got = self.round_of("plan-review", linekit.reply("plan_review_ok"))
        self.assertTrue(got["asking"], got)
        out = self.ok("collect")
        self.assertEqual((out["ok"], out["asks_human"]), (True, True))
        self.assertIn("regression", out["gate_kinds"])

    # -- 決め手の在る項目は関所で聞かない（決め手の出どころ decided_by・undecided_because・柵の印 fences）
    def gate_after(self, narrows, review="plan_review_ok"):
        """narrows を持つ案 → 事前審査（review）を受けた盤面の (事前審査の受け付けの出口, collect の出口)"""
        self.judged()
        plan = linekit.reply("plan_ok")
        plan["plan"][0]["narrows"] = narrows
        self.planned(plan)
        self.assertTrue(self.ok("snap", role="plan-review")["go"])
        _, got = self.round_of("plan-review", linekit.reply(review) if isinstance(review, str) else review)
        self.assertTrue(got["ok"], got)
        return got, self.ok("collect")

    def test_plan_narrows_decided_passes_gate(self):
        """決め手の出どころが在り undecided_because が空で柵の印の無い狭めは、人に聞かずに通り、出どころつきで盤面に残る"""
        decided = [{**NARROWS[0], "decided_by": "依頼の本文: 空の列の mean は今までどおり例外でよい", "undecided_because": "",
                    "fences": []}]
        got, out = self.gate_after(decided)
        self.assertFalse(got["asking"], got)
        self.assertEqual((out["ok"], out["asks_human"]), (True, False))
        self.assertIn("p3.fix", entry.open_board(self.board).settle()["ready"])
        passes = entry.open_board(self.board).state["works"]["gate_passes"]
        self.assertEqual([(p["node"], p["by"], p["decided_by"]) for p in passes],
                         [("p2.human_gate", "decided", decided[0]["decided_by"])])
        self.assertIn(NARROWS[0]["what"], passes[0]["item"])

    def test_plan_narrows_fenced_asks_even_if_decided(self):
        """決め手が在っても、柵の印（外への書き込みなど）の在る狭めは人に聞く"""
        fenced = [{**NARROWS[0], "decided_by": "依頼の本文", "undecided_because": "", "fences": ["external_write"]}]
        got, out = self.gate_after(fenced)
        self.assertTrue(got["asking"], got)
        self.assertIn("regression", out["gate_kinds"])

    def test_plan_narrows_undecided_asks(self):
        """undecided_because の在る狭めは、出どころが在っても人に聞く"""
        undecided = [{**NARROWS[0], "decided_by": "ADR 0002", "undecided_because": "世界の解が 2 つに割れ、どちらかは持ち主が決める",
                      "fences": []}]
        got, out = self.gate_after(undecided)
        self.assertTrue(got["asking"], got)
        self.assertIn("regression", out["gate_kinds"])

    # -- 狭めない案（narrows を書く前に狭めを避ける形を当たり、探した結果を no_narrow に書く）
    def test_plan_narrows_without_no_narrow_rejected(self):
        """narrows の行が no_narrow を欠く・短いなら、受け付けが行を名指して拒み、盤面へ渡さない（修正案の節は待ったまま）"""
        self.judged()
        self.assertTrue(self.ok("snap", role="plan")["go"])
        bare = {k: v for k, v in NARROWS[0].items() if k != gatemarks.NO_NARROW}
        for row in (bare, {**bare, gatemarks.NO_NARROW: "無い"}):
            with self.subTest(row=row):
                plan = linekit.reply("plan_ok")
                plan["plan"][0]["narrows"] = [row]
                got = self.ok("accept", role="plan", reply=json.dumps(plan, ensure_ascii=False))
                self.assertFalse(got["ok"], got)
                reason = self.reason_of(got)
                self.assertTrue(reason.startswith(planblk.NO_NARROW_REJECT), reason)
                self.assertIn(f"plan[0].narrows[0]（{bare['what']}）", reason)
                self.assertEqual(entry.open_board(self.board).rd["instances"]["p2.fix_plan"]["status"], "pending")

    def test_plan_narrows_no_narrow_on_gate_item(self):
        """no_narrow の在る狭めは受け付けを通り、人に聞く関所の項目の尾に探した結果が添わる（決め手の欄が無ければ世界の解の尾は付けない）"""
        got, out = self.gate_after(NARROWS)
        self.assertTrue(got["asking"], got)
        items = entry.open_board(self.board).state["pending_human"]["items"]
        self.assertEqual([x for x in items if NARROWS[0]["what"] in x],
                         [f"修正案 1 が狭める能力: {NARROWS[0]['what']}——{NARROWS[0]['why']}"
                          f"（狭めない案: {NARROWS[0][gatemarks.NO_NARROW]}）"])

    def test_head_asks_no_narrow_first(self):
        """修正案の役の頭は、narrows を書く前に狭めない案を探し、無い時だけ no_narrow に結果を書けと言う。事前審査の役の頭は、
        regression の穴に示せる時だけ添えよと言う"""
        plan, review = planblk.head("plan"), planblk.head("plan-review")
        self.assertIn("狭めない案を先に探せ", plan)
        self.assertIn(f"{gatemarks.NO_NARROW}＝探した結果", plan)
        self.assertIn("狭めない案を添えよ", review)
        self.assertNotIn("狭めない案を先に探せ", review)

    def test_no_narrow_required_only_on_plan_narrows(self):
        """役の型: 修正案の narrows の行は no_narrow が要る。事前審査の穴は持てるが要らない（関所を通す条件にもしない）"""
        narrow = accept.role_schema("p2.fix_plan")["properties"]["plan"]["items"]["properties"]["narrows"]["items"]
        self.assertIn(gatemarks.NO_NARROW, narrow["required"])
        self.assertEqual(narrow["properties"][gatemarks.NO_NARROW]["minLength"], gatemarks.NO_NARROW_MIN)
        face = accept.role_schema("p2.plan_review")["properties"]["faces"]["items"]
        self.assertIn(gatemarks.NO_NARROW, face["properties"])
        self.assertNotIn(gatemarks.NO_NARROW, face["required"])
        self.assertFalse(gatemarks.decided({gatemarks.NO_NARROW: "x" * gatemarks.NO_NARROW_MIN}))

    def test_plan_review_regression_decided_passes_gate(self):
        """事前審査の regression の穴も、決め手が在り柵の印が無ければ人に聞かない"""
        review = suggest_regression()
        review["faces"][0].update({"decided_by": "依頼の本文: clamp は上限を超えたら hi を返す", "undecided_because": "",
                                   "fences": []})
        got, out = self.gate_after([], review)
        self.assertFalse(got["asking"], got)
        self.assertIs(out["asks_human"], False)
        passes = entry.open_board(self.board).state["works"]["gate_passes"]
        self.assertEqual([(p["by"], p["decided_by"]) for p in passes], [("decided", review["faces"][0]["decided_by"])])

    # -- 事前審査
    def test_plan_review_ok_passes_gate(self):
        self.judged()
        self.planned()
        self.ok("snap", role="plan-review")
        _, got = self.round_of("plan-review", linekit.reply("plan_review_ok"))
        self.assertTrue(got["ok"], got)
        self.assertFalse(got["asking"])
        self.assertIn("p3.fix", entry.open_board(self.board).settle()["ready"])
        self.assertTrue(self.ok("reads", include_id="planning")["ok"])
        out = self.ok("collect")
        self.assertEqual((out["ok"], out["asks_human"], out["gave_up"]), (True, False, False))
        b = entry.open_board(self.board)
        self.assertEqual(out["plan_file"], str(self.board / b.state["outputs"]["p2.fix_plan"]["file"]))
        self.assertEqual(out["review_file"], str(self.board / b.state["outputs"]["p2.plan_review"]["file"]))
        idx = json.loads(pathlib.Path(out["reads_file"]).read_text(encoding="utf-8"))
        self.assertEqual(set(idx), {"plan", "plan-review"})

    def test_plan_review_regression_asks(self):
        self.judged()
        self.planned()
        self.ok("snap", role="plan-review")
        _, got = self.round_of("plan-review", suggest_regression())
        self.assertTrue(got["ok"] and got["asking"], got)
        out = self.ok("collect")
        self.assertIs(out["asks_human"], True)
        self.assertIn("regression", out["gate_kinds"])

    def test_plan_review_entrance_needs_no_add(self):
        self.judged()
        self.planned()
        self.ok("snap", role="plan-review")
        _, got = self.round_of("plan-review", linekit.reply("plan_review_no_add"))
        self.assertFalse(got["ok"])
        self.assertIn("no_add", self.reason_of(got))

    def test_policy_change_asks(self):
        """start の後に方針の文書を書き換える → 関所の kinds に policy_changed"""
        pol = self.tmp / "policy.md"
        pol.write_text("# 方針\n- 公開の口を減らさない\n", encoding="utf-8")
        self.judged(policy_md=str(pol))
        pol.write_text("# 方針\n- 公開の口を減らさない\n- 足した\n", encoding="utf-8")
        self.planned()
        self.ok("snap", role="plan-review")
        self.round_of("plan-review", linekit.reply("plan_review_ok"))
        out = self.ok("collect")
        self.assertIn("policy_changed", out["gate_kinds"])

    # -- 指示書（本線の写しを rolekit で）
    def test_prompt_rendered_from_mainline(self):
        self.judged()
        self.ok("snap", role="plan")
        prep = self.ok("prep", role="plan", excluded_file="")
        got = pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8")
        b = entry.open_board(self.board)
        self.assertEqual(pathlib.Path(prep["prompt_file"]), b.work(rolekit.prompt_name("p2.fix_plan")))
        want, _ = rolekit.render_body(b, "p2.fix_plan")
        self.assertEqual(got, planblk.head("plan", "", planblk.lib_section(b, self.repo)) + "\n\n" + want)
        # 種（stats.py・test_stats.py）は標準ライブラリとリポジトリの中の物だけ: 網に出ず、取らないことを書く
        self.assertIn(libdocs.TITLE, got)
        self.assertIn("Context7 から取る物は無い（0 本）", got)
        copy = (CORE / "gl-prompts" / "prompts" / "review-loop" / "p2.fix_plan.md").read_text(encoding="utf-8")
        self.assertIn(copy.splitlines()[0], got)                     # 本線の見出し「# P2-10 修正案」
        self.assertIn("この工程が在る理由", got)
        self.assertIn('"no": 1', got)                                # engine の番号（pointers）
        self.assertNotIn("{{", got)
        inst = b.rd["instances"]["p2.fix_plan"]
        self.assertTrue(inst.get("launched_at"))
        self.assertEqual(inst["pointers"], b.pointer_rows("p2.fix_plan")["pointers"])

    def test_plan_reply_by_number(self):
        """役が no の整数で指した案も通る（描いた番号の控えを mark_launched に固めた）。返答は役の output_format を通る物だけ"""
        self.judged()
        self.ok("snap", role="plan")
        plan = linekit.reply("plan_ok")
        plan["plan"][0]["unit_keys"] = [1, 2]
        self.assertEqual(validate_schema(plan, node_marker.strip(planblk.output_format("plan"))), [])
        _, got = self.round_of("plan", plan)
        self.assertTrue(got["ok"], self.reason_of(got) if got.get("reason_file") else got)
        b = entry.open_board(self.board)
        saved = json.loads((self.board / b.state["outputs"]["p2.fix_plan"]["file"]).read_text(encoding="utf-8"))
        self.assertEqual(set(saved["plan"][0]["unit_keys"]), {UNIT_MEAN, UNIT_CLAMP})

    def test_plan_review_reply_by_number(self):
        """事前審査の役も faces・shrink の unit_keys を no の整数で指せ、受けた返答では key に戻る"""
        self.judged()
        self.planned()
        self.ok("snap", role="plan-review")
        review = suggest_regression()
        review["faces"][0]["unit_keys"] = [1]
        self.assertEqual(validate_schema(review, node_marker.strip(planblk.output_format("plan-review"))), [])
        _, got = self.round_of("plan-review", review)
        self.assertTrue(got["ok"], self.reason_of(got) if got.get("reason_file") else got)
        b = entry.open_board(self.board)
        saved = json.loads((self.board / b.state["outputs"]["p2.plan_review"]["file"]).read_text(encoding="utf-8"))
        self.assertIn(saved["faces"][0]["unit_keys"][0], {UNIT_MEAN, UNIT_CLAMP})

    def test_plan_reply_by_number_string_rejected(self):
        """文字列の "1" は番号ではなく名前として扱われて拒まれ、拒否文は no（整数）で指せと案内する（key を写せに言い換えない）"""
        self.judged()
        self.ok("snap", role="plan")
        plan = linekit.reply("plan_ok")
        plan["plan"][0]["unit_keys"] = ["1", "2"]
        self.assertEqual(validate_schema(plan, node_marker.strip(planblk.output_format("plan"))), [])
        _, got = self.round_of("plan", plan)
        self.assertEqual((got["ok"], got["done"]), (False, False))
        reason = self.reason_of(got)
        self.assertIn("no で指せ", reason)
        self.assertNotIn("key を字面のまま写せ", reason)

    def test_reject_reason_by_file(self):
        """2 回目の plan-prep の頭の行に前の拒否の理由のファイル（reject-take_p2_fix_plan-1.txt）のパス。文は貼らない（R44）"""
        self.judged()
        self.ok("snap", role="plan")
        _, first = self.round_of("plan", linekit.reply("plan_missing_unit"))
        self.assertEqual(pathlib.Path(first["reason_file"]).name, "reject-take_p2_fix_plan-1.txt")
        prep = self.ok("prep", role="plan", excluded_file="")
        self.assertIs(prep["already"], True)
        text = pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(first["reason_file"], text.splitlines()[0])
        self.assertNotIn(self.reason_of(first).splitlines()[0], text)

    def test_give_up_ends_loop(self):
        """3 回拒む → 輪は 3 回目の done で抜ける・事前審査の輪は飛ぶ・collect は gave_up True・ok False・盤面が止まる（R50）"""
        self.judged()
        self.ok("snap", role="plan")
        exited, rounds = self.run_loop("plan", linekit.reply("plan_missing_unit"))
        self.assertEqual(exited, planblk.GIVE_UP_AFTER)
        self.assertEqual([(a["ok"], a["give_up"]) for _, a in rounds],
                         [(False, False)] * (planblk.GIVE_UP_AFTER - 1) + [(False, True)])
        self.assertEqual([p["attempt"] for p, _ in rounds], [1] * planblk.GIVE_UP_AFTER)
        self.assertIs(self.ok("snap", role="plan-review")["go"], False)
        self.ok("reads", include_id="planning")
        out = self.ok("collect")
        self.assertEqual((out["ok"], out["gave_up"]), (False, True))
        self.assertEqual(out["reason_file"], rounds[-1][1]["reason_file"])
        st = self.state()
        self.assertEqual(st["stop"]["by"], planblk.STOP_BY)
        self.assertIn("3 回とも", st["stop"]["reason"])

    def test_excluded_range_named(self):
        self.judged()
        ex = self.tmp / "excluded.json"
        ex.write_text('{"excluded": ["docs/"]}\n', encoding="utf-8")
        self.ok("snap", role="plan")
        text = pathlib.Path(self.ok("prep", role="plan", excluded_file=str(ex))["prompt_file"]).read_text(encoding="utf-8")
        head = text.split("\n\n# P2-10")[0]
        self.assertIn(planblk.EXCLUDED_HEAD, head)
        self.assertIn(str(ex), head)
        for none in ("", "null"):
            text = pathlib.Path(self.ok("prep", role="plan", excluded_file=none)["prompt_file"]).read_text(encoding="utf-8")
            self.assertNotIn(planblk.EXCLUDED_HEAD, text)

    def test_no_fix_skips_both_loops(self):
        """直す物の無い判定（p2.fix_plan が条件で na）→ どちらの snap も go: false、collect は ok で案のファイルは空"""
        self.repo = linekit.seed_repo(self.tmp / "repo", declared=True)
        req = self.tmp / "req" / "request.json"
        req.parent.mkdir(parents=True)
        req.write_text((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.art = self.tmp / "art"
        self.board = self.art / "board"
        entry.start(self.board, self.repo, {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "final_gate": "",
                                            "adapter": "", "policy_md": ""}, run_id=RUN_ID)
        self.take("p0.parallel_pr", {k: v for k, v in linekit.reply("pr_no_conflicts").items() if k != "excluded"})
        self.take("p0.premises", {"constraints": []})
        linekit.pre_judge(self.board, self.repo)   # 目的の文（判定の前に盤面が待つ）
        self.take("p2.diagnose", linekit.reply("judge_no_fix"))
        self.assertIs(self.ok("snap", role="plan")["go"], False)
        self.assertIs(self.ok("snap", role="plan-review")["go"], False)
        out = self.ok("collect")
        self.assertEqual((out["ok"], out["plan_file"], out["gave_up"]), (True, "", False))

    # -- 独立設計（修正案より前に作る）
    def designed(self, reply=None):
        """独立設計の輪を 1 回（snap → prep → accept）"""
        self.assertIs(self.ok("snap", role=planblk.DESIGN_ROLE)["go"], True)
        prep, got = self.round_of(planblk.DESIGN_ROLE, reply or linekit.reply("design_ok"))
        return prep, got

    def test_design_before_plan_reaches_plan_review(self):
        """独立設計を修正案より前に作り（盤面の r2.design はまだ待っていない）、design.json に控える。事前審査の指示書の頭に
        その設計と、構造の食い違いを contract_drift・block で挙げる指示が載る。修正案の指示書には載らない（修正案は設計に依らない）"""
        self.judged()
        b = entry.open_board(self.board)
        self.assertNotIn(design.NODE, b.ready(), "graph では r2.design は修正の後にしか待たない")
        prep, got = self.designed()
        self.assertEqual((got["ok"], got["done"], got["reason_file"]), (True, True, ""), got)
        self.assertEqual(prep["node"], design.NODE)
        self.assertIn(linekit.reply("purpose_ok")["purpose_text"][:20], prep["prompt"], "目的の文は届く")
        for leak in (str(self.repo), "p2.fix_plan", UNIT_MEAN):
            self.assertNotIn(leak, prep["prompt"], f"道具ゼロの設計の役に {leak!r} が届いた")
        self.assertEqual(design.read_design(self.board), linekit.reply("design_ok"))
        self.assertIs(self.ok("snap", role=planblk.DESIGN_ROLE)["go"], False, "設計を 2 度作らない")
        self.assertTrue(self.ok("snap", role="plan")["go"])
        prep, got = self.round_of("plan", linekit.reply("plan_ok"))
        self.assertTrue(got["ok"], got)
        self.assertNotIn(planblk.DESIGN_HEAD, pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8"))
        self.ok("snap", role="plan-review")
        text = pathlib.Path(self.ok("prep", role="plan-review", excluded_file="")["prompt_file"]).read_text(encoding="utf-8")
        head = text.split("# P2-11")[0] if "# P2-11" in text else text
        self.assertIn(planblk.DESIGN_HEAD, head)
        self.assertIn(planblk.DESIGN_ASK, head)
        self.assertIn(linekit.reply("design_ok")["design"], head)
        self.assertIn("contract_drift", planblk.DESIGN_ASK)

    def test_design_not_stands_is_not_a_face(self):
        """設計の役が問いは立たないと返した: 事前審査には設計を突き合わせず、穴にも挙げさせない（先行例の穴に載せない。問いが立つかは
        修正の後の目の層が前提を検算する）"""
        self.judged()
        self.designed({"question_stands": False, "reason": "問いが立たない", "premise_invalid_reason": "識別子は既にある",
                       "design": ""})
        self.planned()
        self.ok("snap", role="plan-review")
        text = pathlib.Path(self.ok("prep", role="plan-review", excluded_file="")["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(planblk.DESIGN_NOT_STANDS.format(reason="識別子は既にある"), text)
        self.assertNotIn(planblk.DESIGN_ASK, text)
        self.assertNotIn("precedent の穴", text)

    def test_design_gave_up_does_not_stop_plan_review(self):
        """人の条件 (2): 独立設計が 3 回とも拒まれても、輪は 3 回目の done で抜け、修正案と事前審査は止まらずに進む。事前審査の指示書は
        設計が無いこと（最後の拒否の文）を言い、collect は ok のまま、盤面の trace に設計が無いことを残す"""
        self.judged()
        self.ok("snap", role=planblk.DESIGN_ROLE)
        exited, rounds = self.run_loop(planblk.DESIGN_ROLE, {"reason": "型に合わない"})
        self.assertEqual(exited, design.GIVE_UP_AFTER)
        self.assertEqual([(a["ok"], a["give_up"]) for _, a in rounds],
                         [(False, False)] * (design.GIVE_UP_AFTER - 1) + [(False, True)])
        self.assertTrue(rounds[1][0]["prompt"].startswith(design.REJECT_HEADING), "道具ゼロの役には拒否の文を本文の頭に貼る")
        for _, a in rounds:
            self.assertTrue(pathlib.Path(a["reason_file"]).is_file())
        self.assertIsNone(design.read_design(self.board))
        self.assertIs(self.ok("snap", role=planblk.DESIGN_ROLE)["go"], False, "諦めた設計は起こし直さない")
        self.planned()
        self.ok("snap", role="plan-review")
        text = pathlib.Path(self.ok("prep", role="plan-review", excluded_file="")["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(f"独立設計は無い（{design.MISSING}: ", text)
        self.assertIn("question_stands", text, "最後の拒否の文を運ぶ")
        self.round_of("plan-review", linekit.reply("plan_review_ok"))
        self.ok("reads", include_id="planning")
        out = self.ok("collect")
        self.assertEqual((out["ok"], out["gave_up"]), (True, False))
        self.assertNotIn("stop", self.state())
        rows = [json.loads(ln) for ln in (self.board / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertTrue(any(r.get("op") == design.MISSING_OP and design.MISSING in r.get("reason", "") for r in rows))

    def test_design_tree_change_rejected(self):
        """道具ゼロの役でも、起こす前の作業ツリーの写しと比べ、変わっていれば拒む"""
        self.judged()
        self.ok("snap", role=planblk.DESIGN_ROLE)
        self.ok("prep", role=planblk.DESIGN_ROLE, excluded_file="")
        (self.repo / "stats.py").write_text("# 変えた\n", encoding="utf-8")
        got = self.ok("accept", role=planblk.DESIGN_ROLE, reply=json.dumps(linekit.reply("design_ok"), ensure_ascii=False))
        self.assertFalse(got["ok"])
        self.assertTrue(self.reason_of(got).startswith(entry.READONLY_MOVED))
        self.assertIsNone(design.read_design(self.board))

    def test_design_skipped_when_purpose_unusable(self):
        """目的の出典が R2 に使えない run（目的不明・裏取りを通った『狭めている』）は設計を起こさない。式は写しの p4.assemble と同じ
        で、p4.assemble が置く loop.purpose_known（まだ無い）を既定の真で読まない"""
        from types import SimpleNamespace
        rules = board_mod.rules_module()
        vetted = {"verdict": "狭めている", "reason": "r", "findings": [{"text": "t", "cite": "c", "hits": 1}]}
        unvetted = {"verdict": "狭めている", "reason": "r", "findings": ["素の文字列"]}
        for src, pr, want in (("目的不明", {}, "目的不明"), ("①依頼", vetted, "狭めている"), ("①依頼", unvetted, None),
                              ("①依頼", {"verdict": "問題なし", "reason": "r", "findings": []}, None)):
            with self.subTest(src=src, pr=pr):
                b = SimpleNamespace(rules=rules, record={"process": {"purpose_review": pr}},
                                    latest_output=lambda nid, src=src: {"source": src})
                self.assertEqual(design.unusable(b), want)
        self.judged()
        with mock.patch.object(design, "unusable", return_value="狭めている"):
            b = entry.open_board(self.board)
            self.assertEqual(design.due(b), (False, design.UNUSABLE["狭めている"]))
            self.assertIn(design.UNUSABLE["狭めている"], planblk.design_section(b))

    def test_scripts_exit_two_on_wiring(self):
        self.judged()
        rc, out, err = self.run_script("snap", drop=("ARTIFACTS_DIR",), role="plan")
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("ARTIFACTS_DIR", err)
        rc, out, err = self.run_script("prep", role="plan")             # INPUTS_EXCLUDED_FILE が無い
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("INPUTS_EXCLUDED_FILE", err)
        rc, out, err = self.run_script("prep", role="no-such", excluded_file="")
        self.assertEqual((rc, out), (2, ""))
        rc, out, err = self.run_script("prep", role="plan-review", excluded_file="")   # 待っている instance が無い（BoardGap）
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("instance", err)
        rc, out, err = self.run_script("accept", role="no-such", reply="{}")
        self.assertEqual((rc, out), (2, ""))
        rc, out, err = self.run_script("accept", role="plan")            # INPUTS_REPLY が無い
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("INPUTS_REPLY", err)
        # 読めない返答は役に返す（0 で ok: false）
        self.ok("snap", role="plan")
        self.ok("prep", role="plan", excluded_file="")
        got = self.ok("accept", role="plan", reply="{JSON でない")
        self.assertFalse(got["ok"])
        self.assertIn("JSON", self.reason_of(got))


STRUCTURE_MISSING = "構造の目の行なしで計画した"
DESIGN_ROW = {"unit_id": UNIT_MEAN, "verdict": "汚れる", "faces": [2], "evidence": ["/units/0/measure"],
              "reason": "責務を 2 か所に割る", "chosen": "分母の決めを 1 か所に固める", "chosen_reason": "読み直しを割らない",
              "route": "自分で決める", "route_reason": "形の番号で決まる"}


class StructureHeadCase(unittest.TestCase):
    """線の構造の境の節 h-structure（darkfactory.yaml）が構造のブロックの出口を受け、修正案の指示書の頭に design.jsonl の行か、
    落ちの印「構造の目の行なしで計画した（理由）」が載る。h-structure は自分の読み書きの失敗を節の失敗にしない（人の条件 (1)）"""

    setUp, take, judged, state, run_script, ok = (ScriptCase.setUp, ScriptCase.take, ScriptCase.judged, ScriptCase.state,
                                                  ScriptCase.run_script, ScriptCase.ok)

    def structured(self, exit_):
        """darkfactory.yaml の h-structure を Archon と同じ形（with: → INPUTS_*・ARTIFACTS_DIR・cwd は対象）で起こし、出口を返す。
        exit_ は構造のブロックの出口（None は飛ばされた・落ちた）"""
        import scriptline
        doc = yaml.safe_load((ROOT / "darkfactory" / "darkfactory.yaml").read_text(encoding="utf-8"))
        n = next((m for m in doc["nodes"] if m.get("id") == "h-structure"), None)
        self.assertIsNotNone(n, "darkfactory.yaml に h-structure が無い")
        inc = next(m["id"] for m in doc["nodes"] if m.get("include") == "blk-structure")
        scope = scriptline.Scope("darkfactory", {})
        if exit_ is not None:
            scope.out[inc], scope.status[inc] = exit_, "ok"
        # 計画を起こす周の形: h-plan が走り go が真（飛ばされた h-plan は if_skipped の false で skipped の印になる）
        scope.out["h-plan"], scope.status["h-plan"] = {"go": True}, "ok"
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        env.update({"WORKS_ADAPTER_HOME": str(self.home), "ARTIFACTS_DIR": str(self.art), "WORKFLOW_ID": RUN_ID,
                    "PYTHONDONTWRITEBYTECODE": "1"})
        env.update({f"INPUTS_{k.upper()}": scope.value(v) for k, v in (n.get("with") or {}).items()})
        r = subprocess.run([sys.executable, str(ROOT / "darkfactory" / "scripts" / f"{n['script']}.py")], cwd=str(self.repo),
                           env=env, capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL)
        self.assertEqual(r.returncode, 0, r.stderr[-1500:])
        return json.loads(r.stdout.splitlines()[-1])

    def plan_head(self):
        self.ok("snap", role="plan")
        text = pathlib.Path(self.ok("prep", role="plan", excluded_file="")["prompt_file"]).read_text(encoding="utf-8")
        return text.split("\n\n# P2-10")[0]

    def block_exit(self, design_file, status="ok"):
        structure = self.tmp / "structure.json"
        structure.write_text('{"status": "%s", "reason": "", "units": [], "timing": {"wall_s": 1.5}}\n' % status,
                             encoding="utf-8")
        return {"ok": True, "structure_file": str(structure), "design_file": str(design_file), "status": status,
                "wall_s": 1.5}

    def test_design_rows_reach_plan_head(self):
        self.judged()
        design_file = self.tmp / "design.jsonl"
        design_file.write_text(json.dumps(DESIGN_ROW, ensure_ascii=False) + "\n", encoding="utf-8")
        got = self.structured(self.block_exit(design_file))
        self.assertEqual(got["status"], "ok", got)
        head = self.plan_head()
        self.assertIn(DESIGN_ROW["chosen"], head)
        self.assertIn(UNIT_MEAN, head)
        self.assertNotIn(STRUCTURE_MISSING, head)

    def test_skipped_block_marks_plan_head(self):
        self.judged()
        got = self.structured(None)
        self.assertEqual(got["status"], "failed", got)
        self.assertTrue(got["reason"].strip(), got)
        self.assertIn(STRUCTURE_MISSING, self.plan_head())

    def test_unreadable_design_does_not_fail_node(self):
        """h-structure の中の失敗（design.jsonl が読めない）は節の失敗にせず、行なしで計画に進む印を出す"""
        self.judged()
        got = self.structured(self.block_exit(self.tmp / "no-such" / "design.jsonl"))
        self.assertEqual(got["status"], "failed", got)
        self.assertTrue(got["reason"].strip(), got)
        head = self.plan_head()
        self.assertIn(STRUCTURE_MISSING, head)
        self.assertNotIn(DESIGN_ROW["chosen"], head)

    def test_block_failure_marks_plan_head(self):
        """構造のブロックが status: failed で抜けた（実測か目が落ちた）周も、行なしで計画した印が載る"""
        self.judged()
        design_file = self.tmp / "design.jsonl"
        design_file.write_bytes(b"")
        got = self.structured(self.block_exit(design_file, status="failed"))
        self.assertEqual(got["status"], "failed", got)
        self.assertIn(STRUCTURE_MISSING, self.plan_head())


REWRITE = {"id": "test_stats.py::TestStats::test_clamp_within_range", "behavior": "上限の内側の値をそのまま返す",
           "old": "clamp(5, 0, 10) は 5", "new": "新しい期待（依頼で変わる振る舞い）"}


class PlanFieldsCase(unittest.TestCase):
    """修正案の項目の works の欄（planmarks）: 受け付けが欠けを盤面へ渡す前に拒み、通った案は欄を外して盤面に渡し、欄は盤面の
    plan-fields.json に控える（盤面が受けた時だけ）。修正案の役の頭に欄の指示、事前審査の役の頭に欄の JSON が載る"""

    setUp, take, judged, state, run_script, ok, round_of, planned, reason_of = (
        ScriptCase.setUp, ScriptCase.take, ScriptCase.judged, ScriptCase.state, ScriptCase.run_script, ScriptCase.ok,
        ScriptCase.round_of, ScriptCase.planned, ScriptCase.reason_of)

    def test_plan_without_fields_rejected_before_board(self):
        self.judged()
        self.ok("snap", role="plan")
        plan = linekit.reply("plan_ok")
        del plan["plan"][0]["tests"]
        _, got = self.round_of("plan", plan)
        self.assertFalse(got["ok"], got)
        self.assertTrue(self.reason_of(got).startswith(planmarks.REJECT))
        self.assertIn("plan[0]", self.reason_of(got))
        self.assertEqual(entry.open_board(self.board).rd["instances"]["p2.fix_plan"]["status"], "pending")
        self.assertFalse((self.board / planmarks.FIELDS_FILE).exists())

    def test_plan_fields_saved_and_board_gets_bare_plan(self):
        self.judged()
        self.planned()
        b = entry.open_board(self.board)
        out = json.loads((self.board / b.state["outputs"]["p2.fix_plan"]["file"]).read_text(encoding="utf-8"))
        self.assertEqual(set(out["plan"][0]), {"unit_keys", "approach", "adds", "removes", "shrink_first", "narrows"})
        self.assertEqual(planmarks.read(b)[0]["route"], "tdd")

    def test_rewrite_limit_resolved_on_accept(self):
        self.judged()
        plan = linekit.reply("plan_ok")
        plan["plan"][0]["rewrite_tests"] = [REWRITE]
        self.planned(plan)
        self.assertEqual(planmarks.read(entry.open_board(self.board))[0]["rewrite_tests"][0]["limit"], "test_stats.py:11")

    def test_fields_unit_keys_are_names_when_reply_by_number(self):
        """役が no の整数で指した案でも、控えの unit_keys は名前（盤面が受けた案の unit_keys と同じ）"""
        self.judged()
        plan = linekit.reply("plan_ok")
        plan["plan"][0]["unit_keys"] = [1, 2]
        self.planned(plan)
        b = entry.open_board(self.board)
        out = json.loads((self.board / b.state["outputs"]["p2.fix_plan"]["file"]).read_text(encoding="utf-8"))
        keys = planmarks.read(b)[0]["unit_keys"]
        self.assertEqual(set(keys), {UNIT_MEAN, UNIT_CLAMP})
        self.assertEqual(keys, out["plan"][0]["unit_keys"])

    def test_rejected_by_board_leaves_no_fields(self):
        """欄は揃っていても写しの受け付けが拒んだ案（単位の欠け）は、控えを置かない"""
        self.judged()
        self.ok("snap", role="plan")
        _, got = self.round_of("plan", linekit.reply("plan_missing_unit"))
        self.assertFalse(got["ok"], got)
        self.assertFalse(self.reason_of(got).startswith(planmarks.REJECT))
        self.assertIn("どの案にも入っていない単位", self.reason_of(got), "写しの受け付けの単位の欠けの拒否")
        self.assertFalse((self.board / planmarks.FIELDS_FILE).exists())

    def test_take_called_directly_strips_fields(self):
        self.judged()
        self.ok("snap", role="plan")
        planblk.prep(self.board, "plan", self.repo)
        self.assertTrue(planblk.take("plan")(self.board, linekit.reply("plan_ok"), self.repo)["ok"])

    def test_heads(self):
        self.assertIn(planmarks.HEAD, planblk.head("plan"))
        self.assertNotIn(planmarks.HEAD, planblk.head("plan-review"))

    def test_plan_review_prompt_carries_fields(self):
        self.judged()
        self.planned()
        self.ok("snap", role="plan-review")
        text = pathlib.Path(self.ok("prep", role="plan-review", excluded_file="")["prompt_file"]).read_text(encoding="utf-8")
        for w in (planmarks.REVIEW_HEAD, "test_stats.py::TestStats::test_mean_of_two", "本物の経路", "mock"):
            self.assertIn(w, text)


class PlanFieldsSaveCase(unittest.TestCase):
    """修正案の欄の控えの置き方: 周は包みの頭で 1 度だけ読み、盤面が案を受けた後に控えを置けなければ盤面を止める"""

    setUp, take, judged, state, run_script, ok = (ScriptCase.setUp, ScriptCase.take, ScriptCase.judged, ScriptCase.state,
                                                 ScriptCase.run_script, ScriptCase.ok)

    def ready(self):
        self.judged()
        self.ok("snap", role="plan")
        planblk.prep(self.board, "plan", self.repo)

    def test_save_failure_after_board_took_plan_halts(self):
        """盤面が案を受けた後で plan-fields.json を置けなければ、黙って欄の無い run にせず盤面を止めて（by works:plan）、
        控えを名指す理由の BoardGap"""
        self.ready()
        with mock.patch.object(planblk.planmarks, "save", side_effect=OSError("書けない")):
            with self.assertRaisesRegex(board_mod.BoardGap, planmarks.FIELDS_FILE):
                planblk.take("plan")(self.board, linekit.reply("plan_ok"), self.repo)
        after = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(after.state["stop"]["by"], planblk.STOP_BY)
        self.assertIn(planmarks.FIELDS_FILE, after.state["stop"]["reason"])

    def test_round_read_once_at_head(self):
        """控えに書く周は包みの頭で 1 度だけ読む（受けた後に盤面を開き直さない）"""
        self.ready()
        rnd = entry.open_board(self.board).round
        with mock.patch.object(planblk.entry, "open_board", wraps=entry.open_board) as opened:
            got = planblk.with_plan_fields(lambda board, reply, repo: {"ok": True})(
                self.board, linekit.reply("plan_ok"), self.repo)
        self.assertTrue(got["ok"])
        self.assertEqual(opened.call_count, 1)
        self.assertEqual(json.loads((self.board / planmarks.FIELDS_FILE).read_text(encoding="utf-8"))["round"], rnd)


class PlanReviewFrozenFieldsCase(unittest.TestCase):
    """事前審査の頭の欄の節（planmarks.review_section）も凍結の印と突き合わせて読み、食い違えば盤面を止める"""

    setUp, take, judged, state, run_script, ok, round_of, planned, reason_of = (
        ScriptCase.setUp, ScriptCase.take, ScriptCase.judged, ScriptCase.state, ScriptCase.run_script, ScriptCase.ok,
        ScriptCase.round_of, ScriptCase.planned, ScriptCase.reason_of)

    def test_tampered_fields_halt_plan_review_prep(self):
        self.judged()
        self.planned()
        p = self.board / planmarks.FIELDS_FILE
        doc = json.loads(p.read_text(encoding="utf-8"))
        doc["fields"][0]["route"] = "direct"
        p.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        self.ok("snap", role="plan-review")
        rc, out, err = self.run_script("prep", role="plan-review", excluded_file="")
        self.assertEqual(rc, 2, err)
        self.assertIn(planmarks.FIELDS_FILE, err)
        after = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(after.state["stop"]["by"], planblk.STOP_BY)
        self.assertIn(planmarks.FIELDS_FILE, after.state["stop"]["reason"])


class ConvergeReviewCase(unittest.TestCase):
    """事前審査の壁打ち（依頼 231）: どの往復の事前審査も盤面が settle なしで受けて往復を記録し、again（新しい block）なら役の
    節 2 つ（修正案・事前審査）を同じ周の待ちに戻す。盤面は ScriptCase と同じ種（p2.fix_plan を受けた所）、支度と受け付けは子の
    プロセス。ScriptCase を継がずに helper だけを借りる（継ぐと ScriptCase の試験が 2 度回る）"""

    setUp, take, judged, state, run_script, ok, round_of, planned, reason_of = (
        ScriptCase.setUp, ScriptCase.take, ScriptCase.judged, ScriptCase.state, ScriptCase.run_script, ScriptCase.ok,
        ScriptCase.round_of, ScriptCase.planned, ScriptCase.reason_of)
    KEY = linekit.reply("plan_review_regression")["faces"][0]["key"]   # 見本の block の key（F13）

    def board_obj(self):
        return entry.open_board(self.board, allow_halted=True)

    def ready(self):
        """修正案を受けた盤面（p2.plan_review が待つ）"""
        self.judged()
        self.planned()

    def review(self, reply, *, ready=True):
        """事前審査の 1 往復（snap → prep → accept）の受け付けの出口"""
        if ready:
            self.ready()
        self.assertTrue(self.ok("snap", role="plan-review")["go"])
        _, got = self.round_of("plan-review", reply)
        return got

    def answers(self, handled="fixed"):
        """1 往復目の block（KEY）への直しの役の答え"""
        return [{"key": self.KEY, "handled": handled, "how": "clamp の上限の枝の呼び手を案の項目に足して確かめる形に直した"}]

    def revise(self, reply=None):
        """直しの役の 1 回（snap → prep → accept。子のプロセス）の受け付けの出口。reply が無ければ plan_ok に答えを足した物"""
        role = planblk.REVISE_ROLE
        self.assertTrue(self.ok("snap", role=role)["go"])
        _, got = self.round_of(role, reply if reply is not None else {**linekit.reply("plan_ok"), converge.ANSWERS: self.answers()})
        return got

    def again(self):
        """1 往復目が block（again）→ 直しの役が案を直して受けられた盤面（p2.plan_review が待つ）"""
        got = self.review(linekit.reply("plan_review_regression"))
        self.assertTrue(got.get("again"), got)
        got = self.revise()
        self.assertTrue(got["ok"], self.reason_of(got) if got.get("reason_file") else got)

    def test_clean_review_taken_as_today(self):
        got = self.review(linekit.reply("plan_review_ok"))
        b = self.board_obj()
        self.assertTrue(got["done"])
        self.assertEqual((got["ok"], got["asking"], got.get("again")), (True, False, None))
        self.assertEqual(b.node_state("p2.plan_review"), "done")
        self.assertEqual(converge.read(b)["outcome"], converge.CLEAN)
        self.assertIn("p3.fix", b.settle()["ready"])

    def test_again_does_not_settle_human_gate(self):
        got = self.review(linekit.reply("plan_review_regression"))
        b = self.board_obj()
        self.assertTrue(got["done"])
        self.assertTrue(got.get("again"))
        self.assertEqual((got["ok"], got["asking"], got["halted"], got["ready"]), (True, False, False, []))
        self.assertNotIn("p2.human_gate", b.rd["done"])
        self.assertFalse(b.state.get("pending_human"))
        self.assertIsNotNone(planblk._pending(b, "p2.fix_plan"))          # 修正案は同じ周の待ちに戻った
        self.assertIsNone(planblk._pending(b, "p2.plan_review"))          # 審査の待ちは案を受けるまで出ない
        self.assertEqual(converge.read(b)["outcome"], converge.AGAIN)
        pass1 = b.work(converge.PASS_DIR) / "pass-1"
        for name in ("p2.fix_plan.json", "p2.plan_review.json", "plan-fields.json", "prompt-p2.plan_review.md"):
            self.assertTrue((pass1 / name).is_file(), name)
        self.assertEqual(json.loads((pass1 / "p2.plan_review.json").read_text(encoding="utf-8"))["faces"][0]["key"], self.KEY)
        self.assertIs(self.ok("snap", role="plan-review")["go"], False)
        self.assertIs(self.ok("snap", role="plan")["go"], True)

    def test_again_reply_still_checked_by_board_and_tree(self):
        """block を持つ返答も (a) 読むだけの役の作業ツリーの比べと (b) 盤面の受け付けを通る。拒めば往復は記録されず、修正案は戻らない"""
        self.ready()
        self.assertTrue(self.ok("snap", role="plan-review")["go"])
        self.ok("prep", role="plan-review", excluded_file="")
        (self.repo / "stats.py").write_text("# 変えた\n", encoding="utf-8")
        raw = json.dumps(linekit.reply("plan_review_regression"), ensure_ascii=False)
        got = self.ok("accept", role="plan-review", reply=raw)
        self.assertFalse(got["ok"])
        self.assertTrue(self.reason_of(got).startswith(entry.READONLY_MOVED))
        linekit.git(self.repo, "checkout", "-q", "--", "stats.py")
        bad = linekit.reply("plan_review_regression")
        bad["faces"][0]["unit_keys"] = ["判定に無い単位の key"]
        got = self.ok("accept", role="plan-review", reply=json.dumps(bad, ensure_ascii=False))
        self.assertFalse(got["ok"])
        self.assertIn("判定に無い単位の key", self.reason_of(got))
        b = self.board_obj()
        self.assertEqual(converge.read(b)["passes"], [])
        self.assertEqual(b.node_state("p2.fix_plan"), "done")
        self.assertIsNotNone(planblk._pending(b, "p2.plan_review"))

    def test_record_failure_after_board_took_review_halts(self):
        """盤面が事前審査を settle なしで受けた後で往復を控え（converge.RECORD）に書けなければ、往復の行の無いまま節を抜けさせず
        盤面を止めて（by works:plan）控えを名指す理由の BoardGap（直しの役の答えの控えと同じ。231 の最後の審査の f1）"""
        self.ready()
        self.assertTrue(self.ok("snap", role="plan-review")["go"])
        planblk.prep(self.board, "plan-review", self.repo)
        run = planblk.with_converge(planblk.take("plan-review", settle=False))
        with mock.patch.object(planblk.converge, "record_pass", side_effect=OSError("書けない")):
            with self.assertRaisesRegex(board_mod.BoardGap, converge.RECORD):
                run(self.board, linekit.reply("plan_review_ok"), self.repo)
        after = self.board_obj()
        self.assertEqual(after.state["stop"]["by"], planblk.STOP_BY)
        self.assertIn(converge.RECORD, after.state["stop"]["reason"])

    def test_rewind_refused_when_later_node_done(self):
        """後ろの節（p2.human_gate・p3.lane_merge）が今の周に受けた後は戻さない: 盤面を止めて BoardGap（F7）"""
        self.ready()
        b = entry.open_board(self.board)
        b.rd["done"]["p2.human_gate"] = {"at": "偽"}
        with self.assertRaises(planblk.BoardGap):
            planblk.rewind_roles(b)
        after = self.board_obj()
        self.assertEqual(after.state["stop"]["by"], converge.BY)
        self.assertEqual(after.node_state("p2.fix_plan"), "done")
        for later in planblk.LATER_NODES:
            with self.subTest(later):
                calls = []
                fake = types.SimpleNamespace(rd={"done": {later: {}}}, state={}, stop=lambda why, by: calls.append(by),
                                             rewind=lambda *a, **k: self.fail("戻した"), settle=lambda: self.fail("進めた"))
                with self.assertRaises(planblk.BoardGap):
                    planblk.rewind_roles(fake)
                self.assertEqual(calls, [converge.BY])

    def test_rejects_restart_per_pass(self):
        """1 往復目に事前審査を 2 回拒ませてから again → 控えに事前審査の行は残らず、往復の行の rejects に 2 行"""
        self.ready()
        self.assertTrue(self.ok("snap", role="plan-review")["go"])
        for _ in range(2):
            _, got = self.round_of("plan-review", linekit.reply("plan_review_no_add"))
            self.assertFalse(got["ok"])
        _, got = self.round_of("plan-review", linekit.reply("plan_review_regression"))
        self.assertTrue(got.get("again"), got)
        b = self.board_obj()
        self.assertEqual(rolekit.rejects(b, "p2.plan_review"), [])
        rows = converge.read(b)["passes"][0]["rejects"]
        self.assertEqual([r["node"] for r in rows], ["p2.plan_review"] * 2)

    def test_persisted_review_taken_and_gate_opens_design_item(self):
        self.again()
        got = self.review(linekit.reply("plan_review_regression"), ready=False)
        self.assertTrue(got["ok"], got)
        self.assertTrue(got["asking"])
        self.assertIsNone(got.get("again"))
        b = self.board_obj()
        self.assertEqual(converge.read(b)["outcome"], converge.PERSISTED)
        items = b.state["pending_human"]["items"]
        self.assertTrue(any(i.startswith(gatemarks.STUCK_ITEM + "。理由: ") for i in items), items)
        self.assertTrue(any(i.startswith("事前審査の穴 [regression] " + self.KEY) for i in items), items)   # block の穴も関所へ

    def test_rereview_must_account_for_every_previous_block(self):
        self.again()
        got = self.review(linekit.reply("plan_review_ok"), ready=False)
        self.assertFalse(got["ok"])
        self.assertTrue(self.reason_of(got).startswith(planblk.RESOLVED_REJECT), self.reason_of(got))
        self.assertIn(self.KEY, self.reason_of(got))
        self.assertEqual(len(converge.read(self.board_obj())["passes"]), 1)
        _, got = self.round_of("plan-review", {**linekit.reply("plan_review_ok"), converge.RESOLVED: [self.KEY]})
        self.assertTrue(got["ok"], self.reason_of(got) if got.get("reason_file") else got)
        doc = converge.read(self.board_obj())
        self.assertEqual((len(doc["passes"]), doc["outcome"], doc["passes"][1]["resolved"]), (2, converge.CLEAN, [self.KEY]))

    def test_rereview_prompt_carries_previous_blocks_and_answers(self):
        self.again()
        self.assertTrue(self.ok("snap", role="plan-review")["go"])
        text = pathlib.Path(self.ok("prep", role="plan-review", excluded_file="")["prompt_file"]).read_text(encoding="utf-8")
        face = linekit.reply("plan_review_regression")["faces"][0]
        for w in (converge.REREVIEW_ASK, face["key"], face["where"], face["why"], "修正案の役の答え:", self.answers()[0]["how"]):
            self.assertIn(w, text)

    def test_first_pass_prompt_unchanged(self):
        """1 往復目の事前審査の指示書は今の版と同じバイト（壁打ちの節が空）"""
        self.ready()
        self.assertTrue(self.ok("snap", role="plan-review")["go"])
        text = pathlib.Path(self.ok("prep", role="plan-review", excluded_file="")["prompt_file"]).read_text(encoding="utf-8")
        b = entry.open_board(self.board)
        want, _ = rolekit.render_body(b, "p2.plan_review")
        head = planblk.head("plan-review", "", planblk.lib_section(b, self.repo), planblk.design_section(b))
        self.assertEqual(text, head + "\n\n" + want)
        self.assertNotIn(converge.REREVIEW_ASK, text)


class ConvergeReviseCase(unittest.TestCase):
    """事前審査の壁打ちの直しの役（依頼 231 Task 4）: 役 plan-revise は修正案の役の会話の続き（印 continue=plan）で、盤面の節は
    p2.fix_plan。起きるかは壁打ちの控えの事実（converge.held）だけで決め、受け付けは block への答えを確かめてから案を修正案と
    同じ口（欄の控え・写しの受け付け）に渡す。比べる作業ツリーの写しは直しの役の snap が置いた物。壁打ちの出口 converge_check は
    抜け方が again でない・役が諦めた・盤面が止まった時に done。helper は ScriptCase・ConvergeReviewCase から借りる"""

    setUp, take, judged, state, run_script, ok, round_of, planned, reason_of = (
        ScriptCase.setUp, ScriptCase.take, ScriptCase.judged, ScriptCase.state, ScriptCase.run_script, ScriptCase.ok,
        ScriptCase.round_of, ScriptCase.planned, ScriptCase.reason_of)
    board_obj, ready, review, answers, revise = (ConvergeReviewCase.board_obj, ConvergeReviewCase.ready,
                                                 ConvergeReviewCase.review, ConvergeReviewCase.answers,
                                                 ConvergeReviewCase.revise)
    KEY = ConvergeReviewCase.KEY   # 見本 plan_review_regression.json の faces[0]["key"]（「clamp の上限の意味が変わる」。F13）

    def again(self, ready=True):
        """1 往復目の事前審査を block で受けて again にした盤面（Task 3 の道。p2.fix_plan が待つ）。ready が偽なら今の盤面で"""
        got = self.review(linekit.reply("plan_review_regression"), ready=ready)
        self.assertTrue(got.get("again"), got)

    def reply(self, answers=None, plan="plan_ok"):
        return {**linekit.reply(plan), converge.ANSWERS: self.answers() if answers is None else answers}

    def check(self):
        return self.ok("converge")

    def test_revise_role_is_fix_plan_node(self):
        role = planblk.REVISE_ROLE
        self.assertEqual(role, "plan-revise")
        self.assertEqual(planblk.known_role(role), "p2.fix_plan")
        self.assertEqual(planblk.snapshot_name(role), "plan-revise-snapshot.json")
        self.assertNotIn(role, planblk.NODE_OF)   # collect の役の並びは今のまま
        self.assertNotIn(role, planblk.ROLES)

    def test_revise_snap_only_after_again(self):
        """go は控えの抜け方が again で p2.fix_plan が待つ時だけ（控え無し・clean・persisted・案を受けた後は go 偽で写しを置かない）"""
        role = planblk.REVISE_ROLE
        self.judged()   # p2.fix_plan は待つが控えが無い（1 往復目の修正案は plan の輪）
        self.assertEqual(self.ok("snap", role=role), {"ok": True, "go": False, "snapshot_file": ""})
        self.planned()
        self.again(ready=False)
        b = self.board_obj()
        doc = converge.read(b)
        for outcome in (None, converge.CLEAN, converge.PERSISTED, converge.UNSETTLED):
            with self.subTest(outcome):
                converge._write(b, {**doc, "outcome": outcome})
                self.assertIs(self.ok("snap", role=role)["go"], False)
                self.assertFalse(b.work(planblk.snapshot_name(role)).exists())
        converge._write(b, doc)
        got = self.ok("snap", role=role)
        self.assertIs(got["go"], True)
        self.assertEqual(got["snapshot_file"], str(b.work("plan-revise-snapshot.json")))
        self.assertTrue(pathlib.Path(got["snapshot_file"]).is_file())
        self.ok("prep", role=role, excluded_file="")
        self.assertTrue(self.ok("accept", role=role, reply=json.dumps(self.reply(), ensure_ascii=False))["ok"])
        self.assertIs(self.ok("snap", role=role)["go"], False)   # 案を受けた後（held は残るが p2.fix_plan が待たない）

    def test_revise_compares_its_own_snapshot(self):
        """直しの役が作業ツリーを変えた → 拒否。比べる写しは直しの役の snap が置いた plan-revise-snapshot.json（1 往復目の
        plan-snapshot.json と比べない: 往復の間に変わった木は、直しの役の snap の後で変えていなければ拒まない）"""
        role = planblk.REVISE_ROLE
        self.again()
        self.assertTrue(self.ok("snap", role=role)["go"])
        self.ok("prep", role=role, excluded_file="")
        (self.repo / "stats.py").write_text("# 変えた\n", encoding="utf-8")
        got = self.ok("accept", role=role, reply=json.dumps(self.reply(), ensure_ascii=False))
        self.assertFalse(got["ok"])
        self.assertTrue(self.reason_of(got).startswith(entry.READONLY_MOVED), self.reason_of(got))
        self.assertEqual(self.board_obj().node_state("p2.fix_plan"), "pending")
        self.assertTrue(self.ok("snap", role=role)["go"])   # 変わった木で写しを置き直す（1 往復目の写しとは違う）
        self.ok("prep", role=role, excluded_file="")
        got = self.ok("accept", role=role, reply=json.dumps(self.reply(), ensure_ascii=False))
        self.assertTrue(got["ok"], self.reason_of(got) if got.get("reason_file") else got)

    def test_revise_prompt_names_blocks_and_keys(self):
        self.again()
        self.assertTrue(self.ok("snap", role=planblk.REVISE_ROLE)["go"])
        got = self.ok("prep", role=planblk.REVISE_ROLE, excluded_file="")
        self.assertEqual(pathlib.Path(got["prompt_file"]).name, "prompt-plan-revise-2.md")
        self.assertEqual((got["node"], got["already"]), ("p2.fix_plan", False))
        self.assertIn("out_path", got)
        p = pathlib.Path(got["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(converge.REVISE_ASK, p)
        self.assertIn(self.KEY, p)
        self.assertTrue(p.startswith(planblk.HEAD["plan"].split("\n\n")[0]), p[:200])
        self.assertNotIn("=====独立設計ここから=====", p)      # 独立設計は直しの役に渡さない
        self.assertNotIn(planmarks.HEAD, p)                    # 修正案の役の頭は会話に在る（貼り直さない）
        b = self.board_obj()
        self.assertTrue(b.rd["instances"]["p2.fix_plan"].get("launched_at"))

    def test_revise_reply_must_answer_every_block(self):
        role = planblk.REVISE_ROLE
        self.again()
        self.assertTrue(self.ok("snap", role=role)["go"])
        _, got = self.round_of(role, linekit.reply("plan_ok"))   # block_answers が無い
        self.assertFalse(got["ok"])
        text = self.reason_of(got)
        self.assertTrue(text.startswith(planblk.ANSWERS_REJECT), text)
        self.assertEqual(planblk.ANSWERS_REJECT, "block への答えに誤りが在る（下の行を全部直して出し直せ）:")
        self.assertIn(f"block の key {self.KEY} への答えが無い", text)
        wrong = [{**self.answers()[0], "key": "別の穴の key を書いた"}]
        prep, got = self.round_of(role, self.reply(wrong))
        self.assertTrue(pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8").startswith(
            rolekit.REJECT_LINE.format(path=rolekit.rejects(self.board_obj(), "p2.fix_plan")[0]["reason_file"])))
        self.assertFalse(got["ok"])
        text = self.reason_of(got)
        for w in (f"block の key {self.KEY} への答えが無い", "別の穴の key を書いた は前の往復の block に無い"):
            self.assertIn(w, text)
        b = self.board_obj()
        self.assertEqual(b.node_state("p2.fix_plan"), "pending")
        self.assertEqual(converge.read(b)["open"], {})

    def test_revise_takes_plan_with_fields_and_notes_answers(self):
        self.ready()
        b = self.board_obj()
        marks = [r for r in (b.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines() if planmarks.SAVED_OP in r]
        self.again(ready=False)
        plan = self.reply()
        plan["plan"][0]["tests"][0]["behavior"] = "2 つの値の平均が、その 2 つのちょうど真ん中の値になる"
        got = self.revise(plan)
        self.assertTrue(got["ok"], self.reason_of(got) if got.get("reason_file") else got)
        self.assertTrue(got["done"])
        b = self.board_obj()
        self.assertEqual(b.node_state("p2.fix_plan"), "done")
        self.assertIsNotNone(planblk._pending(b, "p2.plan_review"))
        out = json.loads((self.board / b.state["outputs"]["p2.fix_plan"]["file"]).read_text(encoding="utf-8"))
        self.assertNotIn(converge.ANSWERS, out)
        self.assertNotIn("route", out["plan"][0])
        self.assertEqual(planmarks.frozen(b)[0]["tests"][0]["behavior"], plan["plan"][0]["tests"][0]["behavior"])
        after = [r for r in (b.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines() if planmarks.SAVED_OP in r]
        self.assertEqual(len(after), len(marks) + 1)   # 凍結の印を置き直した
        self.assertEqual(converge.read(b)["open"], {"answers": self.answers()})

    def test_check_done_unless_again(self):
        self.ready()
        rf = str(self.board_obj().work(converge.RECORD))
        self.assertEqual(self.check(), {"ok": True, "done": True, "outcome": "", "record_file": rf})   # 控え無し
        self.again(ready=False)
        self.assertEqual(self.check(), {"ok": True, "done": False, "outcome": converge.AGAIN, "record_file": rf})
        self.assertTrue(self.revise()["ok"])
        self.assertIs(self.check()["done"], False)   # 案を受けても、審査し直すまで again のまま
        got = self.review(linekit.reply("plan_review_regression"), ready=False)
        self.assertTrue(got["ok"], got)
        self.assertEqual(self.check(), {"ok": True, "done": True, "outcome": converge.PERSISTED, "record_file": rf})

    def test_check_done_after_clean_rereview(self):
        self.again()
        self.assertTrue(self.revise()["ok"])
        got = self.review({**linekit.reply("plan_review_ok"), converge.RESOLVED: [self.KEY]}, ready=False)
        self.assertTrue(got["ok"], got)
        self.assertEqual((self.check()["done"], self.check()["outcome"]), (True, converge.CLEAN))

    def test_check_done_on_stopped_board(self):
        """again のまま盤面が止まる → done（止めた盤面では役が起きず、抜け方が again のまま残る。輪を max_iterations で
        落とさずに抜ける。F4・R50）"""
        self.again()
        entry.open_board(self.board).stop("人が止めた", by="human")
        got = self.check()
        self.assertEqual((got["done"], got["outcome"]), (True, converge.AGAIN))

    def test_revise_give_up_stops_board_and_keeps_record(self):
        role = planblk.REVISE_ROLE
        self.again()
        self.assertTrue(self.ok("snap", role=role)["go"])
        for i in range(planblk.GIVE_UP_AFTER):
            _, got = self.round_of(role, linekit.reply("plan_ok"))   # 答えが無い
            self.assertFalse(got["ok"])
            self.assertIs(got["done"], i == planblk.GIVE_UP_AFTER - 1)
        self.assertIs(self.check()["done"], True)
        self.assertIs(self.ok("snap", role="plan-review")["go"], False)
        out = self.ok("collect")
        self.assertEqual((out["ok"], out["gave_up"]), (False, True))
        b = self.board_obj()
        self.assertEqual(b.state["stop"]["by"], planblk.STOP_BY)
        pass1 = b.work(converge.PASS_DIR) / "pass-1"
        for name in ("p2.fix_plan.json", "p2.plan_review.json", "plan-fields.json"):
            self.assertTrue((pass1 / name).is_file(), name)
        lines = report.head_decisions(b, {})
        self.assertTrue(any(x.startswith("事前審査の壁打ち: 1 往復") for x in lines), lines)

    def test_reads_include_revise_prompt(self):
        role = planblk.REVISE_ROLE
        self.ready()
        idx = json.loads(pathlib.Path(in_include("planning", planblk.collect_reads, self.board, self.repo, "")["reads_file"]).read_text(
            encoding="utf-8"))
        self.assertNotIn(role, idx)   # 直しの役の指示書がまだ無い
        self.again(ready=False)
        self.assertTrue(self.ok("snap", role=role)["go"])
        prompt = self.ok("prep", role=role, excluded_file="")["prompt_file"]
        idx = json.loads(pathlib.Path(in_include("planning", planblk.collect_reads, self.board, self.repo, "")["reads_file"]).read_text(
            encoding="utf-8"))
        self.assertEqual(set(idx), {"plan", "plan-review", role})
        got = json.loads(pathlib.Path(idx[role]).read_text(encoding="utf-8"))
        self.assertEqual(got["node_path"], "planning__converge-loop.plan-revise-loop.plan-revise")
        self.assertIn(prompt, [r["path"] for r in got["rows"]])
        review = json.loads(pathlib.Path(idx["plan-review"]).read_text(encoding="utf-8"))
        self.assertEqual(review["node_path"], "planning__converge-loop.plan-review-loop.plan-review")
        plan = json.loads(pathlib.Path(idx["plan"]).read_text(encoding="utf-8"))
        self.assertEqual(plan["node_path"], "planning__plan-loop.plan")

    def test_replan_include_does_not_converge(self):
        """2 度目の include（依頼 226 の replanning。入力 replan）では壁打ちを回さない: 同じ周の 1 回目の控えの抜け方が again で
        p2.fix_plan が待っていても、直しの役の snap は go 偽で写しを置かず、converge-check は 1 往復で done（outcome・record_file は
        空）。読んだ証拠は直しの役を数えず、案の直しの役の節の名は READS_LOOP の入れ子の輪で組む（F9）"""
        role = planblk.REVISE_ROLE
        self.again()
        b = self.board_obj()
        self.assertEqual(converge.read(b)["outcome"], converge.AGAIN)
        self.assertIs(self.check()["done"], False)   # 1 回目の include なら壁打ちは続く
        self.assertEqual(self.ok("snap", role=role, replan="true"), {"ok": True, "go": False, "snapshot_file": ""})
        self.assertFalse(b.work(planblk.snapshot_name(role)).exists())
        self.assertEqual(self.ok("converge", replan="true"), {"ok": True, "done": True, "outcome": "", "record_file": ""})
        self.assertEqual(converge.read(b)["outcome"], converge.AGAIN)   # 控えに触れない
        self.assertTrue(self.ok("snap", role=role)["go"])
        self.ok("prep", role=role, excluded_file="")   # 1 回目の直しの役の指示書が同じ周に在る
        b.work(rolekit.prompt_name(planblk.replan_mod.REVIEW_NODE)).write_text("案の直しの事前審査\n", encoding="utf-8")
        idx = json.loads(pathlib.Path(in_include("replanning", planblk.collect_reads, self.board, self.repo, "", "true")["reads_file"])
                         .read_text(encoding="utf-8"))
        self.assertEqual(set(idx), {f"{planblk.replan_mod.READS_PREFIX}plan-review"})
        got = json.loads(pathlib.Path(idx[f"{planblk.replan_mod.READS_PREFIX}plan-review"]).read_text(encoding="utf-8"))
        self.assertEqual(got["node_path"], "replanning__converge-loop.plan-review-loop.plan-review")

    def test_revise_mark_continues_plan(self):
        of = planblk.output_format(planblk.REVISE_ROLE)
        self.assertEqual(of["description"], "works-node: plan-revise continue=plan")
        self.assertEqual(node_marker.parse(of["description"])["cont"], "plan")
        bare = node_marker.strip(of)
        self.assertIn(converge.ANSWERS, bare["required"])
        self.assertEqual(converge.with_fields(planblk.REVISE_ROLE, accept.role_schema("p2.fix_plan", numbered=True)), bare)
        self.assertEqual(planblk.output_format("plan")["description"], "works-node: plan")   # 修正案の役は今のまま


if __name__ == "__main__":
    unittest.main()
