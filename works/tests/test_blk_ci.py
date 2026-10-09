"""CI の任せ先の役のブロック blk-ci（線 A Task 27。裁定 R52）の試験。

graphloops の p0.local_checks（修正前）と p4.ci（修正後）は、engine が宣言（.review-checks.json）を走らせられない時、任せ先の役に
落ちる。works では test_cmd も空の run で、run_ci が role_needed を返し（start の ci_role_go・blk-tests の final の by）、ラインが
このブロックを回す。役は読むだけ＋Bash（テストを走らせる）の run の既定の模型で、作業ツリーの写し（engine の copy_worktree）の上で走らせ、
受け付けは役を起こす前と後の作業ツリーの姿（accept.tree_state: porcelain・差分・git が無視するパス・HEAD・枝）を比べる。

- YAML の形: 役の output_format が ci_role.OUTPUT_FORMAT（写しの schema に印 works-node: ci）・輪は fresh_context で AI の節は 1 つ・
  上限は GIVE_UP_AFTER・役の道具は Read・Grep・Glob・Bash・WebSearch・WebFetch・sandbox は graphloops の任せ先（role_run.delegate_settings）と同じ形で、
  本物の作業ツリーは包みが印の旗 no-tree-write を見て守る（裁定 R56）・スクリプトの INPUTS_* と with: が同じ
- 包みの確かめ（裁定 R58）: 最初の節 ci-fence は run が宣言した包みの形（start の控えの adapter）を読む。包みを宣言した run
  （adapter が空）は切符を見て進み、受け付けが包みの起動の記録で、この試行の役の起動に柵 no_tree_write が掛かったかを見る
  （無ければ盤面を止める）。包み無しを宣言した run（adapter: optional）は graphloops と同じ守り（sandbox だけ）で進み、
  包み無しの知らせを残す。宣言が読めなければ盤面を止める。起こす claude の道を script から写して見ることはしない
  （写しの pack で必ず止める・Archon と食い違う。再審査 N4〜N6）。ci-fence が読んだ宣言は出力 adapter に出し、ci-accept と
  collect へは YAML の with: で渡す（役を起こした後に start の控えを書き換えても、受け付けと出口の知らせは変わらない。再審査 N8）
- スクリプト: Archon と同じ形（cwd は対象・ARTIFACTS_DIR・INPUTS_*）の子のプロセスで回す。盤面は本物の入口 entry.start（test_cmd も
  宣言も無い run → p0.local_checks が任せ先に落ちたまま待つ）で作り、本物の entry.open_board で開く。予定の状態（拒否・諦め）は
  終了コード 0 で 1 行、配線の誤り（環境変数の欠け・BoardGap）だけ 2
- p4.ci: blk-tests の final が role_needed を返した盤面（手本の盤面）で、同じ口を同じプロセスで回す
- 筋書き（fixtures/）が pass・reject・give-up・no-adapter（包み無しの宣言）・fence-halt（宣言が読めない）の 5 本。
  Archon で回すのは dev/check.sh（workflow test）
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
from engine.role_run import delegate_settings  # noqa: E402
import adapter  # noqa: E402
import ci_role  # noqa: E402
import node_marker  # noqa: E402

BLK = ROOT / "blk-ci"
ADAPTER_BIN = ROOT / ".shared" / "core" / "claude-adapter"


def fenced_row(repo, **over):
    """包みが節 ci を柵つきで起こした時の起動の記録の 1 行（adapter.launch_row の形の要る所だけ）を、env の包みの家に書く"""
    top = os.path.realpath(linekit.git(repo, "rev-parse", "--show-toplevel"))
    row = {"at": adapter.now(), "node": "ci", "mode": "merged", "fence": {"no_tree_write": top}}
    row.update(over)
    path = adapter.launches_path(repo)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
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
        self.assertEqual(list(self.top), ["ci-fence", "ci-snap", "ci-loop", "collect"])

    def test_fence_first(self):
        """run が宣言した包みの形が読めない・包みを宣言した run で切符が無ければ役を起こさない（裁定 R58）: 最初の節 ci-fence が
        見て、偽なら ci-snap から後を飛ばし、出口だけが走る（止めた盤面の理由を出す）"""
        self.assertNotIn("depends_on", self.top["ci-fence"])
        self.assertEqual(self.top["ci-snap"]["depends_on"], ["ci-fence"])
        self.assertEqual(self.top["ci-snap"]["when"], "$ci-fence.output.go == true")
        self.assertEqual(self.top["collect"]["depends_on"], ["ci-fence", "ci-loop"])
        self.assertEqual(self.top["collect"]["trigger_rule"], "none_failed_min_one_success")
        # 包み無しの知らせ（裁定 R58）は ci-fence と出口の欄 note
        for nid in ("ci-fence", "collect"):
            fmt = self.top[nid]["output_format"]
            self.assertIn("note", fmt["required"], nid)
            self.assertEqual(fmt["properties"]["note"], {"type": "string"}, nid)
        # ci-fence が読んだ宣言は出力 adapter に出し、受け付けと出口へ with: で渡す（役は Archon の節の出力を書き換えられない。
        # 役を起こした後に start の控えを読み直さない。再審査 N8）
        fmt = self.top["ci-fence"]["output_format"]
        self.assertIn("adapter", fmt["required"])
        self.assertEqual(fmt["properties"]["adapter"], {"type": "string", "enum": list(entry.ADAPTER_MODES)})
        accept = self.top["ci-loop"]["loop_group"]["nodes"][2]
        for n in (accept, self.top["collect"]):
            self.assertEqual(n["with"]["adapter"], "$ci-fence.output.adapter", n["id"])

    def test_output_format_is_marked_copy_schema(self):
        """役の output_format は写しの p0.local_checks と p4.ci の schema（同じ形）に印 works-node: ci を付けた物"""
        self.assertEqual(role_schema("p0.local_checks"), role_schema("p4.ci"))
        for nid in ci_role.NODES:
            self.assertEqual(ci_role.OUTPUT_FORMAT, node_marker.mark(role_schema(nid), ci_role.ROLE, flags=("no-tree-write",)))
        # 旗 no-tree-write: 包みが役の cwd の作業ツリーを柵に足す（sandbox は allowWrite ['/']。裁定 R56）
        self.assertEqual(node_marker.parse(ci_role.OUTPUT_FORMAT["description"]),
                         {"name": "ci", "cont": None, "flags": frozenset({"no-tree-write"})})
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
        self.assertEqual(role["allowed_tools"], ["Read", "Grep", "Glob", "Bash", "WebSearch", "WebFetch"])   # Edit・Write は無い（web は本線の writer と同じ）
        self.assertEqual(role["settingSources"], ["user"])
        self.assertNotIn("context", role)
        self.assertEqual(role["idle_timeout"], DEADLINE)
        # sandbox は graphloops の任せ先の形そのもの（写しの engine の delegate_settings）から、起動ごとの denyWrite（包みが旗を見て
        # 足す）と autoAllowBashIfSandboxed（Archon は bypassPermissions で起こす）を除いた物（裁定 R56）
        want = json.loads(delegate_settings([]))["sandbox"]
        self.assertEqual(want["filesystem"].pop("denyWrite"), [])
        self.assertIs(want.pop("autoAllowBashIfSandboxed"), True)
        self.assertEqual(role["sandbox"], want)
        # 輪の後ろの出口は輪の欄を読まずに合流する（ci-fence が偽なら輪は飛ばされる）
        self.assertIn("ci-loop", self.top["collect"]["depends_on"])

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
                # R56 の後は ~/.cache も網も使える: キャッシュの置き場を一時の置き場に強制しない（毎回の取り直しになる）。
                # 本物は包みが書かせない（graphloops の元の文の趣旨）、包みの無い run では受け付けが拒む（審査 M2）
                self.assertNotIn("XDG_CACHE_HOME", body)
                self.assertNotIn("~/.cache などには書けない", body)
                self.assertIn("本物には書けない", body)
                self.assertIn("コードに無い赤", body)
                self.assertIn("受け付け", body)
                for hole in ci_role.HOLES:
                    self.assertIn(f"<<{hole}>>", body)
        self.assertIn("awaiting_human", (BLK / "prompts" / "p0.local_checks.md").read_text(encoding="utf-8"))
        self.assertIn("kind=awaiting・origin=local_checks", (BLK / "prompts" / "p4.ci.md").read_text(encoding="utf-8"))

    def test_fixtures(self):
        fx = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in (BLK / "fixtures").glob("*.stubs.yaml")}
        self.assertEqual(set(fx), {"pass.stubs.yaml", "reject.stubs.yaml", "give-up.stubs.yaml", "no-adapter.stubs.yaml",
                                   "fence-halt.stubs.yaml"})
        reached = ["ci-fence", "ci-snap", "ci-prep", "ci", "ci-accept", "collect"]
        h = fx.pop("fence-halt.stubs.yaml")   # 宣言が読めない → 盤面を止めて役を起こさない
        self.assertEqual(h["fixture"]["reached"], ["ci-fence", "collect"])
        self.assertIs(h["ci-fence"]["go"], False)
        self.assertEqual(h["ci-fence"]["adapter"], "")
        self.assertIs(h["collect"]["ok"], False)
        self.assertIn("adapter", h["collect"]["reason"])
        n = fx["no-adapter.stubs.yaml"]      # 包み無しの宣言 → graphloops と同じ守りで回し、知らせを出口に出す
        self.assertEqual(n["ci-fence"]["note"], ci_role.NO_ADAPTER_NOTE)
        self.assertEqual(n["ci-fence"]["adapter"], "optional")
        self.assertEqual(n["collect"]["note"], ci_role.NO_ADAPTER_NOTE)
        self.assertIs(n["collect"]["ok"], True)
        for name, f in fx.items():
            with self.subTest(name):
                if name != "no-adapter.stubs.yaml":
                    self.assertEqual((f["ci-fence"]["note"], f["collect"]["note"], f["ci-fence"]["adapter"]), ("", "", ""))
                self.assertIs(f["ci-fence"]["go"], True)
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

    adapter_mode = ""   # run の入力 adapter（"" は包みを通す run、"optional" は包み無しで回す run）

    def setUp(self):
        self._old_cwd = engine_util.GIT_CWD
        self.addCleanup(setattr, engine_util, "GIT_CWD", self._old_cwd)
        self.tmp = pathlib.Path(tempfile.mkdtemp(dir=linekit.work_home()))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = mock.patch.dict(os.environ, {"WORKS_ADAPTER_HOME": str(self.tmp / "adapter-home")})
        env.start()
        self.addCleanup(env.stop)
        self.fenced = True   # prep の後に、包みが節 ci を柵つきで起こした記録を置く（Archon と包みの代わり）
        self.repo = linekit.seed_repo(self.tmp / "repo")
        req = self.tmp / "req" / "request.json"
        req.parent.mkdir()
        req.write_text((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        self.art = self.tmp / "art"
        got = entry.start(self.art / "board", self.repo, {"request": str(req), "adapter": self.adapter_mode}, run_id="run-27")
        self.assertTrue(got["ci_role_go"])
        self.board = self.art / "board"
        self.addCleanup(self.drop_copies)

    def drop_copies(self):
        """出口（collect）まで回さなかった試験の写しを消す（写しの置き場は盤面の外の一時の置き場の下）"""
        for p in (self.board / "r1").glob("ci-snapshot-*.json"):
            ci_role._drop_copy(json.loads(p.read_text(encoding="utf-8")))

    def opened(self):
        return entry.open_board(self.board, allow_halted=True)

    def run_script(self, name, drop=(), **inputs):
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        env.update({"ARTIFACTS_DIR": str(self.art), "PYTHONDONTWRITEBYTECODE": "1"})
        if name in ("accept", "collect"):   # YAML は ci-fence の出力 adapter を with: で渡す（再審査 N8）
            inputs.setdefault("adapter", self.adapter_mode)
        env.update({f"INPUTS_{k.upper()}": v for k, v in inputs.items()})
        for k in drop:
            env.pop(k, None)
        r = subprocess.run([sys.executable, str(BLK / "scripts" / f"{name}.py")], cwd=str(self.repo), env=env,
                           capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0 and name == "prep" and self.fenced:
            fenced_row(self.repo)
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

    def accept_last(self) -> dict:
        return json.loads((self.opened().dir / "accept-last.json").read_text(encoding="utf-8"))

    def test_pass_path(self):
        snap = self.ok("snap", node="p0.local_checks")
        copy = pathlib.Path(snap["copy_dir"])
        self.assertTrue((copy / "stats.py").is_file(), "写しは作業ツリーの今の姿")
        # 写しは run ごとに利用者の一時の置き場（tempfile.gettempdir()）の下（共有の決め打ちの /tmp/works-ci でない。審査 M3）
        top = copy.parent
        self.assertEqual(os.path.realpath(top.parent), os.path.realpath(tempfile.gettempdir()))
        self.assertTrue(top.name.startswith(ci_role.COPY_PREFIX + "p0.local_checks-"), top)
        self.assertFalse(hasattr(ci_role, "COPY_ROOT"))
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
        self.assertIs(self.accept_last()["ci_p0_local_checks"]["ok"], True)
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

    def test_drop_copy_only_own_temp_dirs(self):
        """出口が消すのは一時の置き場の直下の works-ci- で始まる写しだけ（盤面の snapshot の top が書き換えられても他を消さない）"""
        other = self.tmp / "works-ci-p0.local_checks-x"          # 名前は合うが一時の置き場の直下でない
        other.mkdir()
        plain = pathlib.Path(tempfile.mkdtemp(prefix="not-ours-"))   # 一時の置き場の直下だが名前が違う
        self.addCleanup(shutil.rmtree, plain, ignore_errors=True)
        for top in (other, plain):
            ci_role._drop_copy({"top": str(top)})
            self.assertTrue(top.is_dir(), top)
        mine = pathlib.Path(tempfile.mkdtemp(prefix=ci_role.COPY_PREFIX + "p0.local_checks-"))
        ci_role._drop_copy({"top": str(mine)})
        self.assertFalse(mine.exists())

    def test_fence_declared_adapter_ignores_launch_path(self):
        """包みを宣言した run（adapter が空）→ go。起こす claude の道（env の CLAUDE_BIN_PATH・Archon の設定）を script から
        写して見ない（裁定 R58）: 写しの pack（dogfood・use・plugin install）の包み・包みでない claude・何も無い、の
        どれでも同じ。柵が掛かったかは受け付けが包みの起動の記録で見る（test_accept_halts_without_fenced_launch）"""
        self.assertFalse(hasattr(adapter, "launch_path"), "Archon の claude の解決を写した確かめは消した（再審査 N4〜N6）")
        copied = self.tmp / "copied-pack" / ".shared" / "core" / "claude-adapter"   # 写しの pack の包み（N5）
        copied.parent.mkdir(parents=True)
        shutil.copy2(ADAPTER_BIN, copied)
        for env in ({"CLAUDE_BIN_PATH": str(copied)}, {"CLAUDE_BIN_PATH": "/bin/false"}, {"CLAUDE_BIN_PATH": ""}):
            with self.subTest(env), mock.patch.dict(os.environ, env):
                got = self.ok("fence", node="p0.local_checks")
                self.assertEqual(got, {"go": True, "reason": "", "note": "", "adapter": ""})
                self.assertFalse(self.opened().state.get("stop"))

    def test_fence_no_adapter_runs_with_note(self):
        """包み無しを宣言した run（adapter: optional）→ go。graphloops と同じ守り（sandbox だけ・作業ツリーの柵無し）で走る
        知らせを出口と盤面の作業ファイルに残す（黙って下げない）。受け付けは包みの柵を求めないが、作業ツリーの比べはする"""
        self.adapter_mode = "optional"
        self.setUp()
        self.fenced = False   # 包みの起動の記録は無い
        got = self.ok("fence", node="p0.local_checks")
        self.assertEqual((got["go"], got["reason"], got["note"], got["adapter"]), (True, "", ci_role.NO_ADAPTER_NOTE, "optional"), got)
        for word in ("包み無し", "graphloops", "sandbox"):
            self.assertIn(word, ci_role.NO_ADAPTER_NOTE)
        self.assertFalse(self.opened().state.get("stop"))
        self.ok("snap", node="p0.local_checks")
        self.ok("prep", node="p0.local_checks")
        reply = json.dumps(linekit.reply("ci_found"), ensure_ascii=False)
        (self.repo / "new.txt").write_text("x\n", encoding="utf-8")
        got = self.ok("accept", node="p0.local_checks", reply=reply)
        self.assertEqual((got["ok"], got["done"]), (False, False), got)
        self.assertIn("作業ツリーを変えた", got["reason"])
        (self.repo / "new.txt").unlink()
        got = self.ok("accept", node="p0.local_checks", reply=reply)
        self.assertTrue(got["ok"], got)
        out = self.ok("collect", node="p0.local_checks")
        self.assertEqual((out["ok"], out["status"], out["note"]), (True, "found", ci_role.NO_ADAPTER_NOTE), out)

    def break_start(self, how):
        """start の控え（今の周の start.json）の adapter を読めなくする"""
        path = self.opened().work(entry.START_FILE)
        doc = json.loads(path.read_text(encoding="utf-8"))
        if how == "gone":
            path.unlink()
        elif how == "broken":
            path.write_text("{壊れ", encoding="utf-8")
        elif how == "no-key":
            path.write_text(json.dumps({k: v for k, v in doc.items() if k != "adapter"}), encoding="utf-8")
        else:
            path.write_text(json.dumps({**doc, "adapter": how}), encoding="utf-8")

    def test_mode_unreadable_halts(self):
        """run が宣言した包みの形が読めない → ci-fence は盤面を止めて（by works:adapter）go false（出力 adapter は厳しい方の空）・
        出口は ok false。受け付けに with: で届いた形が宣言の語でなくても、返答を受けずに盤面を止める（fail closed）"""
        for how in ("gone", "broken", "no-key", "maybe"):
            with self.subTest(fence=how):
                self.setUp()
                self.break_start(how)
                got = self.ok("fence", node="p0.local_checks")
                self.assertIs(got["go"], False)
                self.assertEqual(got["adapter"], "")
                self.assertIn("adapter", got["reason"])
                self.assertEqual(self.opened().state["stop"]["by"], ci_role.FENCE_BY)
                out = self.ok("collect", node="p0.local_checks")
                self.assertIs(out["ok"], False)
                self.assertIn("adapter", out["reason"])
        for how in ("maybe", "None", " optional"):
            with self.subTest(accept=how):
                self.setUp()
                self.ok("fence", node="p0.local_checks")
                self.ok("snap", node="p0.local_checks")
                self.ok("prep", node="p0.local_checks")
                got = self.ok("accept", node="p0.local_checks", adapter=how,
                              reply=json.dumps(linekit.reply("ci_found"), ensure_ascii=False))
                self.assertEqual((got["ok"], got["done"]), (False, True), got)
                self.assertIn("adapter", got["reason"])
                b = self.opened()
                self.assertEqual(b.state["stop"]["by"], ci_role.FENCE_BY)
                self.assertNotEqual(b.node_state("p0.local_checks"), "done", "返答は受けない")

    def test_mode_is_fixed_at_fence(self):
        """受け付けと出口は ci-fence が読んだ宣言（with: で届く adapter）だけを使い、役を起こした後に start の控えを読み直さない
        （再審査 N8）: 包みを宣言した run で役が控えの adapter を optional に書き換えても、受け付けは柵の記録を求めて盤面を止め、
        出口の知らせも空のまま。包み無しの run で控えを空に書き換えても、出口の知らせは消えない"""
        self.fenced = False   # 包みが居ない起動（柵の記録が無い）
        fence = self.ok("fence", node="p0.local_checks")
        self.assertEqual(fence["adapter"], "")
        self.ok("snap", node="p0.local_checks")
        self.ok("prep", node="p0.local_checks")
        self.break_start("optional")   # 役が起動の後に宣言を書き換えた
        got = self.ok("accept", node="p0.local_checks", adapter=fence["adapter"],
                      reply=json.dumps(linekit.reply("ci_found"), ensure_ascii=False))
        self.assertEqual((got["ok"], got["done"]), (False, True), got)
        self.assertIn("柵", got["reason"])
        self.assertEqual(self.opened().state["stop"]["by"], ci_role.FENCE_BY)
        out = self.ok("collect", node="p0.local_checks", adapter=fence["adapter"])
        self.assertEqual((out["ok"], out["note"]), (False, ""), out)

        self.adapter_mode = "optional"
        self.setUp()
        self.fenced = False
        fence = self.ok("fence", node="p0.local_checks")
        self.ok("snap", node="p0.local_checks")
        self.ok("prep", node="p0.local_checks")
        self.break_start("")
        for leftover in self.opened().dir.rglob("ci-note-*"):
            leftover.unlink()
        self.assertTrue(self.ok("accept", node="p0.local_checks", adapter=fence["adapter"],
                                reply=json.dumps(linekit.reply("ci_found"), ensure_ascii=False))["ok"])
        out = self.ok("collect", node="p0.local_checks", adapter=fence["adapter"])
        self.assertEqual((out["ok"], out["note"]), (True, ci_role.NO_ADAPTER_NOTE), out)

    def test_fence_stops_without_ticket(self):
        """包みを宣言した run で切符が無い → 包みは旗 no-tree-write の役を起こさない（Archon が起こし直して節が落ちる）ので、
        先に盤面を止める"""
        adapter.ticket_path(self.repo).unlink()
        got = self.ok("fence", node="p0.local_checks")
        self.assertIs(got["go"], False)
        self.assertIn("切符", got["reason"])
        self.assertEqual(self.opened().state["stop"]["by"], ci_role.FENCE_BY)

    def test_accept_halts_without_fenced_launch(self):
        """包みを宣言した run（adapter が空）で、役の起動が包みを通っていない・柵 no_tree_write が掛かっていない → 受け付けは
        拒否でなく盤面を止め、輪を抜ける（再審査 N1 の (a)・裁定 R58 の「気づく」）"""
        for over in (None, {"fence": {"deny_write": 3}}):
            with self.subTest(over):
                self.setUp()
                self.fenced = False
                self.ok("snap", node="p0.local_checks")
                self.ok("prep", node="p0.local_checks")
                if over is not None:
                    fenced_row(self.repo, **over)
                got = self.ok("accept", node="p0.local_checks", reply=json.dumps(linekit.reply("ci_found"), ensure_ascii=False))
                self.assertEqual((got["ok"], got["done"]), (False, True), got)
                self.assertIn("柵", got["reason"])
                b = self.opened()
                self.assertEqual(b.state["stop"]["by"], ci_role.FENCE_BY)
                self.assertNotEqual(b.node_state("p0.local_checks"), "done", "返答は受けない")
                self.assertEqual(b.record["materials"]["local_checks"]["status"], "not_run", "役の返答（found）は受けない")
                out = self.ok("collect", node="p0.local_checks")
                self.assertIs(out["ok"], False)

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
        row = self.accept_last()["ci_p0_local_checks"]   # 受け付けの最後の結果の控え（script_io.note_last）
        self.assertEqual((row["ok"], row["reason"]), (False, rounds[-1][1]["reason"]))
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
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)
        env = mock.patch.dict(os.environ, {"WORKS_ADAPTER_HOME": self._home.name})
        env.start()
        self.addCleanup(env.stop)

    def test_final_role_needed_then_blk_ci_submits_p4(self):
        b = self.case.mode_board(decl=None)
        repo = self.case.repo(b)
        self.assertEqual(entry.run_ci(b, "p4.ci", test_cmd="")["by"], "role_needed")
        snap = ci_role.snapshot(b.dir, "p4.ci", repo)
        prep = ci_role.prep(b.dir, "p4.ci", repo)
        fenced_row(repo)   # 包みが節 ci を柵つきで起こした
        prompt = pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("p4.ci", prompt)
        self.assertIn(str(repo.resolve()), prompt)
        reply = {"material": {"status": "clean", "count": 0, "checked": "写しの上で python3 -c print を走らせた: exit 0"}}
        got = ci_role.take(b.dir, "p4.ci", reply, repo, "")   # 包みを宣言した run（ci-fence の出力 adapter が空）
        self.assertTrue(got["ok"], got)
        out = ci_role.collect(b.dir, "p4.ci", "")
        self.assertEqual((out["ok"], out["status"], out["green"], out["pr_go"], out["note"]), (True, "clean", True, False, ""))
        after = entry.open_board(b.dir, allow_halted=True)
        self.assertEqual(after.record["process"]["checks"]["p4.ci"]["by"], "role")
        self.assertEqual(after.record["materials"]["local_checks"]["status"], "clean")
        self.assertFalse(pathlib.Path(snap["copy_dir"]).exists())

    def test_baseline_green_kept_apart_from_final_red(self):
        """修正前が緑で最後のテストが赤（run-140 の形）: p4.ci の後も process.baseline_checks は修正前の値のまま残り、
        materials.local_checks だけが赤になる。報告の冒頭と最後の関所は 2 つを並べて出す"""
        import report
        sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
        import line_edge
        b = self.case.mode_board(decl=None)
        self.assertEqual(b.record["process"]["baseline_checks"]["status"], "clean", "手本の盤面の修正前は緑")
        repo = self.case.repo(b)
        self.assertEqual(entry.run_ci(b, "p4.ci", test_cmd="")["by"], "role_needed")
        tests = {"ok": True, "green": False, "log": "", "suites": [], "by": "role_needed"}   # blk-tests の final の出口
        ci_role.snapshot(b.dir, "p4.ci", repo)
        ci_role.prep(b.dir, "p4.ci", repo)
        fenced_row(repo)
        reply = {"material": {"status": "found", "count": 1, "detail": "写しの上で走らせた: exit 1"}}
        self.assertTrue(ci_role.take(b.dir, "p4.ci", reply, repo, "")["ok"])
        self.assertEqual(ci_role.collect(b.dir, "p4.ci", "")["status"], "found")
        after = entry.open_board(b.dir, allow_halted=True)
        self.assertEqual(after.record["process"]["baseline_checks"]["status"], "clean")
        self.assertEqual(after.record["materials"]["local_checks"]["status"], "found")
        with mock.patch.object(report, "_stop_info", return_value=("", "", None)), \
                mock.patch.object(report, "_latest", return_value=None), \
                mock.patch.object(report, "_pr_lines", return_value=[]):
            head = report.head_decisions(after, {}, tests=tests)
        self.assertTrue(any(x.startswith("最後のテストが赤") for x in head), head)
        self.assertTrue(any(x.startswith("修正前のテスト: 緑") for x in head), head)
        eyes = line_edge._eyes(after)
        rest = report.rest_outside_validator(after, tests=tests, counts=eyes.counts)
        gate = line_edge._final_text(after, tests, "", eyes, rest, repo, "run-1")
        self.assertIn("テストは赤", gate)
        self.assertIn("修正前のテスト: 緑", gate)


if __name__ == "__main__":
    unittest.main()
