"""CI の任せ先の役のブロック blk-ci（線 A Task 27。裁定 R52）の試験。

graphloops の p0.local_checks（修正前）と p4.ci（修正後）は、engine が宣言（.review-checks.json）を走らせられない時、任せ先の役に
落ちる。works では test_cmd も空の run で、run_ci が role_needed を返し（start の ci_role_go・blk-tests の final の by）、ラインが
このブロックを回す。役は読むだけ＋Bash（テストを走らせる）の opus で、作業ツリーの写し（engine の copy_worktree）の上で走らせ、
受け付けは役を起こす前と後の作業ツリーの姿（accept.tree_state: porcelain・差分・git が無視するパス・HEAD・枝）を比べる。

- YAML の形: 役の output_format が ci_role.OUTPUT_FORMAT（写しの schema に印 works-node: ci）・輪は fresh_context で AI の節は 1 つ・
  上限は GIVE_UP_AFTER・役の道具は Read・Grep・Glob・Bash・sandbox は写しの置き場だけ書き込みを足す・スクリプトの INPUTS_* と with: が同じ
- スクリプト: Archon と同じ形（cwd は対象・ARTIFACTS_DIR・INPUTS_*）の子のプロセスで回す。盤面は本物の入口 entry.start（test_cmd も
  宣言も無い run → p0.local_checks が任せ先に落ちたまま待つ）で作り、本物の entry.open_board で開く。予定の状態（拒否・諦め）は
  終了コード 0 で 1 行、配線の誤り（環境変数の欠け・BoardGap）だけ 2
- p4.ci: blk-tests の final が role_needed を返した盤面（手本の盤面）で、同じ口を同じプロセスで回す
- 筋書き（fixtures/）が pass・reject・give-up の 3 本。Archon で回すのは dev/check.sh（workflow test）
"""
import importlib.util
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

sys.dont_write_bytecode = True
TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(TESTS))

import linekit  # noqa: E402
import entry  # noqa: E402
import engine.util as engine_util  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
from accept import role_schema  # noqa: E402
import ci_role  # noqa: E402
import node_marker  # noqa: E402

BLK = ROOT / "blk-ci"
DEADLINE = 1728000000


def workflow():
    return yaml.safe_load((BLK / "blk-ci.yaml").read_text(encoding="utf-8"))


def walk(nodes, inside=None):
    for n in nodes or []:
        yield n, inside
        if "loop_group" in n:
            yield from walk(n["loop_group"].get("nodes"), n)


def script_inputs(name):
    spec = importlib.util.spec_from_file_location(f"_blk_ci_{name}", BLK / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.INPUTS


class YamlCase(unittest.TestCase):
    def setUp(self):
        self.y = workflow()
        self.top = {n["id"]: n for n in self.y["nodes"]}

    def test_inputs_and_exit(self):
        self.assertEqual(set(self.y["inputs"]), {"node", "base_rev"})
        self.assertTrue(self.y["inputs"]["node"].get("required"))
        self.assertEqual((self.y["returns"], self.y["outcome_field"]), ("collect", "ok"))
        self.assertNotIn("model", yaml.safe_dump(self.y))
        self.assertEqual(list(self.top), ["ci-snap", "ci-loop", "collect"])

    def test_output_format_is_marked_copy_schema(self):
        """役の output_format は写しの p0.local_checks と p4.ci の schema（同じ形）に印 works-node: ci を付けた物"""
        self.assertEqual(role_schema("p0.local_checks"), role_schema("p4.ci"))
        for nid in ci_role.NODES:
            self.assertEqual(ci_role.OUTPUT_FORMAT, node_marker.mark(role_schema(nid), ci_role.ROLE))
        self.assertEqual(node_marker.parse(ci_role.OUTPUT_FORMAT["description"])["name"], "ci")
        role = self.top["ci-loop"]["loop_group"]["nodes"][1]
        self.assertEqual(role["output_format"], ci_role.OUTPUT_FORMAT)
        for name in ("ci_found", "ci_not_applicable"):
            self.assertEqual(validate_schema(linekit.reply(name), role["output_format"]), [], name)

    def test_loop_and_role(self):
        grp = self.top["ci-loop"]
        g = grp["loop_group"]
        self.assertEqual(grp["depends_on"], ["ci-snap"])
        self.assertIs(g["fresh_context"], True)
        self.assertEqual(g["max_iterations"], ci_role.GIVE_UP_AFTER, "諦めの数は輪の上限と同じ（上限で輪を落とさない）")
        self.assertEqual(g["until_bash"], "test $ci-accept.output.done = true")
        self.assertEqual([m["id"] for m in g["nodes"]], ["ci-prep", "ci", "ci-accept"])
        ai = [m for m in g["nodes"] if "command" in m or "prompt" in m]
        self.assertEqual([m["id"] for m in ai], ["ci"])
        role = ai[0]
        self.assertEqual(role["command"], "ci")
        self.assertTrue((BLK / "commands" / "ci.md").is_file())
        self.assertEqual(role["allowed_tools"], ["Read", "Grep", "Glob", "Bash"])   # Edit・Write は無い
        self.assertEqual(role["settingSources"], [])
        self.assertNotIn("context", role)
        self.assertEqual(role["idle_timeout"], DEADLINE)
        sb = role["sandbox"]
        self.assertEqual((sb["enabled"], sb["allowUnsandboxedCommands"]), (True, False))
        # 写しの置き場（sandbox の外の作業ディレクトリ）だけ書き込みを足す。綴りと実体の両方（macOS の /tmp → /private/tmp）
        allow = set(sb["filesystem"]["allowWrite"])
        self.assertLessEqual({ci_role.COPY_ROOT, os.path.realpath(ci_role.COPY_ROOT)}, allow)
        self.assertEqual(allow, {ci_role.COPY_ROOT, "/private" + ci_role.COPY_ROOT})
        self.assertEqual(set(sb["filesystem"]), {"allowWrite"})
        # 輪の後ろの出口は輪の欄を読まずに合流する
        self.assertEqual(self.top["collect"]["depends_on"], ["ci-loop"])

    def test_script_inputs_match_with(self):
        for n, _ in walk(self.y["nodes"]):
            if "script" not in n:
                continue
            with self.subTest(n["id"]):
                want = {f"INPUTS_{k.upper()}" for k in (n.get("with") or {})}
                self.assertEqual(set(script_inputs(n["script"])), want)
                self.assertEqual(n["timeout"], DEADLINE)
                self.assertEqual(n["runtime"], "uv")
                self.assertEqual(n["with"]["node"], "$INPUTS.node")

    def test_command_is_thin_and_prompts_keep_the_rules(self):
        text = (BLK / "commands" / "ci.md").read_text(encoding="utf-8")
        self.assertIn("$ci-prep.output.prompt_file", text)
        self.assertNotIn("$LOOP_PREV", text)   # 拒否の文は prep が指示書の頭に書く（裁定 R44）
        self.assertIn("前の回の受け付けが拒んだ理由", text)
        for nid in ci_role.NODES:
            body = (BLK / "prompts" / f"{nid}.md").read_text(encoding="utf-8")
            with self.subTest(nid):
                self.assertNotIn("{{", body, "写しの graph の穴（盤面に無い物）は削った")
                for keep in ("緑を仮定", "終わるまで待て", "not_applicable", "not_run", "carried_over", "系統ごとの終了コード"):
                    self.assertIn(keep, body)
                for hole in ci_role.HOLES:
                    self.assertIn(f"<<{hole}>>", body)
        self.assertIn("awaiting_human", (BLK / "prompts" / "p0.local_checks.md").read_text(encoding="utf-8"))
        self.assertIn("kind=awaiting・origin=local_checks", (BLK / "prompts" / "p4.ci.md").read_text(encoding="utf-8"))

    def test_fixtures(self):
        fx = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in (BLK / "fixtures").glob("*.stubs.yaml")}
        self.assertEqual(set(fx), {"pass.stubs.yaml", "reject.stubs.yaml", "give-up.stubs.yaml"})
        reached = ["ci-snap", "ci-prep", "ci", "ci-accept", "collect"]
        for name, f in fx.items():
            with self.subTest(name):
                self.assertEqual(f["fixture"]["expect"], "completed")
                self.assertEqual(f["fixture"]["reached"], reached)
                self.assertEqual(validate_schema(f["ci"], ci_role.OUTPUT_FORMAT), [])
        p = fx["pass.stubs.yaml"]
        self.assertEqual(p["ci"], linekit.reply("ci_found"))
        self.assertEqual((p["ci-accept"]["ok"], p["ci-accept"]["done"]), (True, True))
        self.assertIs(p["collect"]["ok"], True)
        r = fx["reject.stubs.yaml"]
        self.assertEqual((r["ci-accept"]["ok"], r["ci-accept"]["done"], r["ci-accept"]["give_up"]), (False, False, False))
        self.assertIn("作業ツリーを変えた", r["ci-accept"]["reason"])
        g = fx["give-up.stubs.yaml"]
        self.assertEqual((g["ci-accept"]["ok"], g["ci-accept"]["done"], g["ci-accept"]["give_up"]), (False, True, True))
        self.assertIs(g["collect"]["ok"], False)
        for name in ("reject.stubs.yaml", "give-up.stubs.yaml"):
            head = (BLK / "fixtures" / name).read_text(encoding="utf-8")
            self.assertIn("dry-run は until_bash を回さず", head, "筋書きは輪の抜け方を見ていないと書く")


class ScriptCase(unittest.TestCase):
    """本物の入口 entry.start で p0.local_checks が任せ先に落ちたまま待つ盤面を作り、ブロックのスクリプトを子のプロセスで回す"""

    def setUp(self):
        self._old_cwd = engine_util.GIT_CWD
        self.addCleanup(setattr, engine_util, "GIT_CWD", self._old_cwd)
        self.tmp = pathlib.Path(tempfile.mkdtemp(dir=linekit.work_home()))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = mock.patch.dict(os.environ, {"WORKS_ADAPTER_HOME": str(self.tmp / "adapter-home")})
        env.start()
        self.addCleanup(env.stop)
        self.repo = linekit.seed_repo(self.tmp / "repo")
        req = self.tmp / "req" / "request.json"
        req.parent.mkdir()
        req.write_text((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.art = self.tmp / "art"
        got = entry.start(self.art / "board", self.repo, {"request": str(req)}, run_id="run-27")
        self.assertTrue(got["ci_role_go"])
        self.board = self.art / "board"
        self.addCleanup(self.drop_copies)

    def drop_copies(self):
        """出口（collect）まで回さなかった試験の写しを消す（写しの置き場は盤面の外の COPY_ROOT の下）"""
        for p in (self.board / "r1").glob("ci-snapshot-*.json"):
            ci_role._drop_copy(json.loads(p.read_text(encoding="utf-8")))

    def opened(self):
        return entry.open_board(self.board, allow_halted=True)

    def run_script(self, name, drop=(), **inputs):
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        env.update({"ARTIFACTS_DIR": str(self.art), "PYTHONDONTWRITEBYTECODE": "1"})
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

    def run_loop(self, node, reply, before_accept=None):
        """Archon の輪と同じ順に回す: 周ごとに prep → 役（返答は reply）→ accept → until_bash の式を sh で評価。
        抜けた周の番号と各周の (prep, accept) を返す。max_iterations 回で抜けなければ番号は None（Archon は輪を failed にする）"""
        g = next(n for n in workflow()["nodes"] if n.get("id") == "ci-loop")["loop_group"]
        rounds = []
        for i in range(1, g["max_iterations"] + 1):
            prep = self.ok("prep", node=node)
            if before_accept:
                before_accept(i)
            got = self.ok("accept", node=node, reply=json.dumps(reply, ensure_ascii=False))
            rounds.append((prep, got))

            def value(m):
                self.assertEqual(m.group(1), "ci-accept", "until_bash は同じ輪の受け付けの欄だけを読む")
                return json.dumps(got[m.group(2)])
            cond = re.sub(r"\$([A-Za-z0-9_-]+)\.output\.([A-Za-z0-9_]+)", value, g["until_bash"])
            if subprocess.run(["sh", "-c", cond]).returncode == 0:
                return i, rounds
        return None, rounds

    def test_pass_path(self):
        snap = self.ok("snap", node="p0.local_checks")
        copy = pathlib.Path(snap["copy_dir"])
        self.assertTrue((copy / "stats.py").is_file(), "写しは作業ツリーの今の姿")
        self.assertTrue(str(copy.resolve()).startswith(os.path.realpath(ci_role.COPY_ROOT) + os.sep))
        self.assertEqual(linekit.git(copy, "rev-parse", "HEAD"), linekit.git(self.repo, "rev-parse", "HEAD"))
        exited, rounds = self.run_loop("p0.local_checks", linekit.reply("ci_found"))
        self.assertEqual(exited, 1)
        prep, got = rounds[0]
        self.assertEqual((prep["attempt"], prep["node"], prep["already"]), (1, "p0.local_checks", False))
        prompt = pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8")
        for part in (str(self.repo), str(copy), ".review-checks.json", "p0.local_checks"):
            self.assertIn(part, prompt)
        self.assertNotIn("<<", prompt, "穴は全部埋めた")
        self.assertTrue(got["ok"], got)
        out = self.ok("collect", node="p0.local_checks")
        self.assertEqual((out["ok"], out["status"], out["green"], out["node"]), (True, "found", False, "p0.local_checks"), out)
        self.assertIn(out["pr_go"], (True, False), "p0.local_checks を渡した後は resume_after_ci が p0.parallel_pr を測る")
        b = self.opened()
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "found")
        self.assertEqual(b.record["process"]["baseline_checks"]["status"], "found")
        self.assertEqual(b.node_state("p0.local_checks"), "done")
        self.assertEqual(entry.resume_after_ci(b)["pr_go"], out["pr_go"])
        self.assertFalse(copy.exists(), "出口が写しを消す")
        self.assertEqual(linekit.git(self.repo, "status", "--porcelain"), "")

    def test_not_applicable_accepted(self):
        """CI の定義が無い（na_self_ok）→ 理由つきの not_applicable を受ける"""
        self.ok("snap", node="p0.local_checks")
        exited, rounds = self.run_loop("p0.local_checks", linekit.reply("ci_not_applicable"))
        self.assertEqual(exited, 1)
        out = self.ok("collect", node="p0.local_checks")
        self.assertEqual((out["ok"], out["status"], out["green"]), (True, "not_applicable", False))

    def test_tree_change_rejected(self):
        """役を起こした後に対象の作業ツリーが変わった → ok false（役に返す）、盤面は受けない。未追跡のファイル・git が無視する
        パスの増減のどちらも。元に戻せば通る（枝の切り替えは test_branch_switch_rejected。3 回目の拒否は諦めになるので分ける）"""
        (self.repo / ".git" / "info" / "exclude").write_text("build/\n", encoding="utf-8")
        self.ok("snap", node="p0.local_checks")
        self.ok("prep", node="p0.local_checks")

        def untracked():
            (self.repo / "new.txt").write_text("x\n", encoding="utf-8")
            return lambda: (self.repo / "new.txt").unlink()

        def ignored():
            (self.repo / "build").mkdir()
            (self.repo / "build" / "out.o").write_text("x\n", encoding="utf-8")
            return lambda: shutil.rmtree(self.repo / "build")

        for change, word in ((untracked, "new.txt"), (ignored, "build/")):
            with self.subTest(word):
                undo = change()
                got = self.ok("accept", node="p0.local_checks", reply=json.dumps(linekit.reply("ci_found"), ensure_ascii=False))
                self.assertEqual((got["ok"], got["done"]), (False, False))
                self.assertIn("作業ツリーを変えた", got["reason"])
                self.assertIn(word, got["reason"])
                self.assertEqual(self.opened().node_state("p0.local_checks"), "pending")
                undo()
        self.assertTrue(self.ok("accept", node="p0.local_checks",
                                reply=json.dumps(linekit.reply("ci_found"), ensure_ascii=False))["ok"])

    def test_branch_switch_rejected(self):
        self.ok("snap", node="p0.local_checks")
        self.ok("prep", node="p0.local_checks")
        main = linekit.git(self.repo, "symbolic-ref", "--short", "HEAD")
        linekit.git(self.repo, "checkout", "-q", "--detach", main)
        got = self.ok("accept", node="p0.local_checks", reply=json.dumps(linekit.reply("ci_found"), ensure_ascii=False))
        self.assertFalse(got["ok"])
        self.assertIn("ref", got["reason"])

    def test_gives_up_after_three_rejections(self):
        """3 回とも拒まれても輪は max_iterations で落ちず（3 回目の受け付けが done を出し until_bash が抜ける）、collect が
        最後の拒否の文で盤面を止めて ok false（再審のブロックと同じ形。裁定 R50）。2 回目からの指示書の頭に前の拒否の文"""
        self.ok("snap", node="p0.local_checks")
        exited, rounds = self.run_loop("p0.local_checks", linekit.reply("ci_bad_status"))
        self.assertEqual(exited, ci_role.GIVE_UP_AFTER, "輪が上限まで抜けない（Archon は run を落とす）")
        self.assertEqual([p["attempt"] for p, _ in rounds], [1] * ci_role.GIVE_UP_AFTER)
        self.assertEqual([p["already"] for p, _ in rounds], [False] + [True] * (ci_role.GIVE_UP_AFTER - 1))
        self.assertEqual([(a["ok"], a["give_up"]) for _, a in rounds],
                         [(False, False)] * (ci_role.GIVE_UP_AFTER - 1) + [(False, True)])
        second = pathlib.Path(rounds[1][0]["prompt_file"]).read_text(encoding="utf-8")
        self.assertTrue(second.startswith(ci_role.REJECT_HEADING))
        self.assertIn(rounds[0][1]["reason"], second)
        out = self.ok("collect", node="p0.local_checks")
        self.assertFalse(out["ok"])
        self.assertIn("3 回とも", out["reason"])
        st = self.opened().state
        self.assertEqual(st["stop"]["by"], ci_role.STOP_BY)
        self.assertIn("green", st["stop"]["reason"])

    def test_unreadable_reply_is_a_reject(self):
        self.ok("snap", node="p0.local_checks")
        self.ok("prep", node="p0.local_checks")
        for raw in ("{JSON でない", "[1]"):
            got = self.ok("accept", node="p0.local_checks", reply=raw)
            self.assertFalse(got["ok"])
            self.assertIn("JSON", got["reason"])

    def test_scripts_exit_two_on_wiring(self):
        rc, out, err = self.run_script("snap", drop=("ARTIFACTS_DIR",), node="p0.local_checks")
        self.assertEqual((rc, out), (2, ""))
        self.assertIn("ARTIFACTS_DIR", err)
        rc, _, err = self.run_script("prep")
        self.assertEqual(rc, 2)
        self.assertIn("INPUTS_NODE", err)
        rc, _, err = self.run_script("snap", node="p2.diagnose")
        self.assertEqual(rc, 2)
        self.assertIn("p2.diagnose", err)
        rc, _, err = self.run_script("snap", node="p4.ci")   # 待っていない（任せ先に落ちていない）CI の節
        self.assertEqual(rc, 2)
        self.assertIn("任せ先", err)
        rc, _, err = self.run_script("accept", node="p0.local_checks", reply="{}")   # snap が走っていない
        self.assertEqual(rc, 2)
        self.assertIn("ci-snap", err)


class P4Case(unittest.TestCase):
    """blk-tests の final が role_needed を返した盤面（手本の盤面を 1 本目の表で。test_blk_tests_delta の mode_board）で p4.ci を渡す"""

    def setUp(self):
        import test_blk_tests_delta as TD
        self.TD = TD
        self.case = TD.TestTestsModes("test_final_by_engine")
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_final_role_needed_then_blk_ci_submits_p4(self):
        b = self.case.mode_board(decl=None)
        repo = self.case.repo(b)
        self.assertEqual(entry.run_ci(b, "p4.ci", test_cmd="")["by"], "role_needed")
        snap = ci_role.snapshot(b.dir, "p4.ci", repo)
        prep = ci_role.prep(b.dir, "p4.ci", repo)
        prompt = pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("p4.ci", prompt)
        self.assertIn(str(repo.resolve()), prompt)
        reply = {"material": {"status": "clean", "count": 0, "checked": "写しの上で python3 -c print を走らせた: exit 0"}}
        got = ci_role.take(b.dir, "p4.ci", reply, repo)
        self.assertTrue(got["ok"], got)
        out = ci_role.collect(b.dir, "p4.ci")
        self.assertEqual((out["ok"], out["status"], out["green"], out["pr_go"]), (True, "clean", True, False))
        after = entry.open_board(b.dir, allow_halted=True)
        self.assertEqual(after.record["process"]["checks"]["p4.ci"]["by"], "role")
        self.assertEqual(after.record["materials"]["local_checks"]["status"], "clean")
        self.assertFalse(pathlib.Path(snap["copy_dir"]).exists())


if __name__ == "__main__":
    unittest.main()
