"""修正案と事前審査のブロック（blk-plan。P1 計画 Task 25・〔線A計〕T11・裁定 P1-R10・R44・R50）の検査。

- YAML の形: 役の output_format が planblk.output_format（写しの schema に印）と同じ・輪の中の id が全部のブロックをまたいで一意・
  輪は fresh_context で AI の節は 1 つ・諦めの数と max_iterations が同じ・until_bash は同じ輪の受け付けの done・スクリプトが読む
  INPUTS_* と with: の鍵が同じ・役に届く文に $LOOP_PREV が無い・筋書き 3 本
- スクリプト: 別のプロセスで Archon と同じ形（cwd は対象・ARTIFACTS_DIR・INPUTS_*）に回す。盤面は linekit の種で start →
  並行 PR・前提・判定を entry.take で受けた物（p2.fix_plan が待つ）。指示書は本線の写し（gl-prompts）を rolekit の描き方で描いた物
"""
import importlib.util
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
BLK = ROOT / "blk-plan"
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(BLK / "lib"))
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

import accept  # noqa: E402
import engine.util as engine_util  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
import entry  # noqa: E402
import linekit  # noqa: E402
import node_marker  # noqa: E402
import libdocs  # noqa: E402
import planblk  # noqa: E402
import rolekit  # noqa: E402

DEADLINE = 1728000000
RUN_ID = "run-plan"
UNIT_MEAN = "stats.py mean: 分母が len(xs) - 1 になっている"
UNIT_CLAMP = "stats.py clamp: 上限を超えた値に lo を返す"
NARROWS = [{"what": "空の列の mean", "why": "空の列の平均は 0 割りの例外のまま（前も例外で、狭まる能力は無いが人に確かめる）"}]


def workflow():
    return yaml.safe_load((BLK / "blk-plan.yaml").read_text(encoding="utf-8"))


def walk(nodes, inside=None):
    for n in nodes or []:
        yield n, inside
        if "loop_group" in n:
            yield from walk(n["loop_group"].get("nodes"), n)


def script_inputs(name):
    spec = importlib.util.spec_from_file_location(f"_blk_plan_{name}", BLK / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.INPUTS


class YamlCase(unittest.TestCase):
    def setUp(self):
        self.y = workflow()
        self.top = {n["id"]: n for n in self.y["nodes"]}

    def loops(self):
        return [n for n in self.y["nodes"] if "loop_group" in n]

    def test_inputs_and_exit(self):
        self.assertEqual(set(self.y["inputs"]), {"judgment_file", "base_rev", "policy_paste", "policy_path", "excluded_file",
                                                 "include_id"})
        self.assertIs(self.y["inputs"]["judgment_file"]["required"], True)
        self.assertEqual((self.y["returns"], self.y["outcome_field"]), ("collect", "ok"))
        self.assertNotIn("model", yaml.safe_dump(self.y))
        self.assertEqual(set(self.top["collect"]["output_format"]["required"]),
                         {"ok", "plan_file", "review_file", "asks_human", "gate_kinds", "reads_file", "gave_up", "reason_file"})

    def test_output_format_matches_graph(self):
        """役の output_format を strip した値 == 写しの role_schema、印の名は plan・plan-review"""
        got = {}
        for grp in self.loops():
            ai = [m for m in grp["loop_group"]["nodes"] if "prompt" in m or "command" in m]
            got[ai[0]["id"]] = ai[0]["output_format"]
        self.assertEqual(set(got), {"plan", "plan-review"})
        for role, of in got.items():
            with self.subTest(role):
                self.assertEqual(of, planblk.output_format(role))
                self.assertEqual(node_marker.strip(of), accept.role_schema(planblk.NODE_OF[role], numbered=True))
                self.assertEqual(of["description"], f"works-node: {role}")

    def test_loops_fresh_single_ai_and_give_up(self):
        for grp in self.loops():
            g = grp["loop_group"]
            role = next(m for m in g["nodes"] if "prompt" in m or "command" in m)
            with self.subTest(role["id"]):
                self.assertIs(g["fresh_context"], True)
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

    def test_script_inputs_match_with(self):
        for n, _ in walk(self.y["nodes"]):
            if "script" not in n:
                continue
            with self.subTest(n["id"]):
                want = {f"INPUTS_{k.upper()}" for k in (n.get("with") or {})}
                self.assertEqual(set(script_inputs(n["script"])), want)
                self.assertEqual((n["timeout"], n["runtime"]), (DEADLINE, "uv"))
                if "role" in (n.get("with") or {}):
                    self.assertEqual(n["id"].rsplit("-", 1)[0], n["with"]["role"])

    def test_no_loop_prev_reaches_a_prompt(self):
        """役に届く文に $LOOP_PREV が無い（理由はファイルで。R44）。手で書いた commands も置かない（P1-R10）"""
        for n, _ in walk(self.y["nodes"]):
            self.assertNotIn("$LOOP_PREV", str(n.get("prompt", "")), n["id"])
        self.assertFalse((BLK / "commands").exists())

    def test_after_loop_nodes_join(self):
        for nid in ("plan-review-snap", "plan-reads"):
            self.assertEqual(self.top[nid]["trigger_rule"], "none_failed_min_one_success", nid)
            self.assertNotIn("when", self.top[nid])

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
            for role in ("plan", "plan-review"):
                if role in f:
                    with self.subTest(f"{name}:{role}"):
                        self.assertEqual(validate_schema(f[role], planblk.output_format(role)), [])


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

    def judged(self, policy_md=""):
        """start → 並行 PR の任せ先・前提の役 → 判定（judge_ok）を受けた盤面（p2.fix_plan が待つ）"""
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
        self.take("p2.diagnose", linekit.reply("judge_ok"))

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
                           capture_output=True, text=True)
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
        _, got = self.round_of("plan-review", linekit.reply("plan_review_regression"))
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
        review = linekit.reply("plan_review_regression")
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


if __name__ == "__main__":
    unittest.main()
