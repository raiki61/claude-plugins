"""同じ周の再審のブロック（blk-rejudge）の検査。rejudge 設計の 23b（段 1＝写しの graphloops 0.21.0 の形）。

- YAML の形: 役の output_format が rejudge.output_format（写しの schema に印）と同じ・when: が読むのはいつも走る rj-route<k> の
  欄だけ・輪は fresh_context で AI の節は 1 つ・役の id は印の名・continue= を持つ役だけ context: fresh・段の並びは passes() の順・
  スクリプトが読む INPUTS_* と with: の鍵が同じ
- スクリプト: 別のプロセスで Archon と同じ形（cwd は対象・ARTIFACTS_DIR・INPUTS_*）に回す。予定の状態（拒否・止めた・回す物が
  無い）は終了コード 0 で 1 行、配線の誤り（環境変数の欠け・BoardGap）だけ 2
- 筋書き（fixtures/）が 4 本在り、期待の形が設計 11.2 どおりか。Archon で回すのは dev/check.sh（workflow test）
盤面は tests/rejudgekit.py の手本の盤面。子のプロセスは tests/rejudge_child.py を通して、表を everything にした盤面を開く。
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

import yaml

sys.dont_write_bytecode = True
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
import rejudgekit as kit  # noqa: E402
from rejudgekit import load  # noqa: E402

import rejudge  # noqa: E402
from engine.schema import validate_schema  # noqa: E402

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-rejudge"
CHILD = pathlib.Path(__file__).resolve().parent / "rejudge_child.py"
DEADLINE = 1728000000
BOARDS = None


def setUpModule():
    global BOARDS
    BOARDS = kit.Boards()


def tearDownModule():
    BOARDS.cleanup()


def workflow():
    return yaml.safe_load((BLK / "blk-rejudge.yaml").read_text(encoding="utf-8"))


def walk(nodes, inside=None):
    """(節, 入っている輪の節 | None) を全部"""
    for n in nodes or []:
        yield n, inside
        if "loop_group" in n:
            yield from walk(n["loop_group"].get("nodes"), n)


def script_inputs(name):
    spec = importlib.util.spec_from_file_location(f"_blk_rejudge_{name}", BLK / "scripts" / f"{name}.py")
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
        self.assertEqual(set(self.y["inputs"]), {"base_rev", "policy_paste"})
        self.assertEqual((self.y["returns"], self.y["outcome_field"]), ("collect", "ok"))
        self.assertNotIn("model", yaml.safe_dump(self.y))

    def test_yaml_output_formats_match(self):
        for grp in self.loops():
            ai = [m for m in grp["loop_group"]["nodes"] if "command" in m]
            with self.subTest(grp["id"]):
                self.assertEqual(ai[0]["output_format"], rejudge.output_format(rejudge.node_of(ai[0]["id"])))
                # 良い返答の見本が YAML の型を通る
                self.assertEqual(validate_schema(load("rejudge_settled"), ai[0]["output_format"]), [])

    def test_stages_follow_copied_passes(self):
        """段 k（rj-route<k> → 輪）の役が passes() の k 番目。段の並び＝写しの依存の並び"""
        roles = [p["role"] for p in rejudge.passes()]
        got = []
        for k, grp in enumerate(self.loops(), 1):
            m = re.fullmatch(r"\$rj-route(\d+)\.output\.next == '([a-z0-9-]+)'", grp.get("when", ""))
            self.assertIsNotNone(m, grp.get("when"))
            self.assertEqual(int(m.group(1)), k)
            self.assertEqual(grp["depends_on"], [f"rj-route{k}"])
            got.append(m.group(2))
            ai = [x for x in grp["loop_group"]["nodes"] if "command" in x]
            self.assertEqual(ai[0]["id"], m.group(2))
        self.assertEqual(got, roles)

    def test_yaml_when_reads_only_routes(self):
        routes = {nid for nid, n in self.top.items() if n.get("script") == "route"}
        for n, inside in walk(self.y["nodes"]):
            for key in ("when",):
                if key in n:
                    refs = set(re.findall(r"\$([A-Za-z0-9_-]+)\.output", n[key]))
                    with self.subTest(n["id"]):
                        self.assertTrue(refs and refs <= routes, refs)
        for nid in routes:
            self.assertNotIn("when", self.top[nid], "rj-route はいつも走る")
        # 輪の後ろの節は、飛ばされうる輪の欄を読まずに合流する
        for nid, n in self.top.items():
            if any(d in self.top and "loop_group" in self.top[d] for d in n.get("depends_on") or []):
                self.assertEqual(n.get("trigger_rule"), "none_failed_min_one_success", nid)
                self.assertNotIn("with", n, nid)

    def test_yaml_loops_fresh_and_single_ai(self):
        for grp in self.loops():
            g = grp["loop_group"]
            with self.subTest(grp["id"]):
                self.assertIs(g["fresh_context"], True)
                self.assertEqual(g["max_iterations"], 3)
                ai = [m for m in g["nodes"] if "command" in m or "prompt" in m]
                self.assertEqual(len(ai), 1)
                role = ai[0]
                p = next(x for x in rejudge.passes() if x["role"] == role["id"])
                mark = rejudge.output_format(p["node"])["description"]
                self.assertEqual(mark.split()[1], role["id"], "役の id は印の名")
                self.assertEqual(role.get("context") == "fresh", p["cont"] is not None, "continue= を持つ役だけ context: fresh")
                self.assertEqual(role["command"], role["id"])
                self.assertTrue((BLK / "commands" / f"{role['id']}.md").is_file())
                self.assertEqual(role["allowed_tools"], ["Read", "Grep", "Glob"])
                self.assertEqual(role["settingSources"], [])
                self.assertEqual(role["idle_timeout"], DEADLINE)
                ids = [m["id"] for m in g["nodes"]]
                self.assertEqual(ids, [f"{role['id']}-prep", role["id"], f"{role['id']}-accept"])
                self.assertEqual(g["until_bash"], f"test ${role['id']}-accept.output.ok = true")

    def test_yaml_script_inputs_match_with(self):
        for n, _ in walk(self.y["nodes"]):
            if "script" not in n:
                continue
            with self.subTest(n["id"]):
                want = {f"INPUTS_{k.upper()}" for k in (n.get("with") or {})}
                self.assertEqual(set(script_inputs(n["script"])), want)
                self.assertEqual(n["timeout"], DEADLINE)
                self.assertEqual(n["runtime"], "uv")
                if "role" in (n.get("with") or {}):
                    self.assertEqual(n["id"].rsplit("-", 1)[0], n["with"]["role"])

    def test_commands_are_thin(self):
        for grp in self.loops():
            role = next(m["id"] for m in grp["loop_group"]["nodes"] if "command" in m)
            text = (BLK / "commands" / f"{role}.md").read_text(encoding="utf-8")
            with self.subTest(role):
                self.assertIn(f"${role}-prep.output.prompt_file", text)
                self.assertIn(f"$LOOP_PREV.{role}-accept.output.reason", text)
                self.assertNotIn("$INPUTS.policy_paste", text, "方針は描いた指示書に入っている")
                self.assertNotIn("{{", text, "指示書を写さない（本文は engine の描画）")

    def test_fixtures(self):
        fx = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in (BLK / "fixtures").glob("*.stubs.yaml")}
        self.assertEqual(set(fx), {"settled.stubs.yaml", "no-session.stubs.yaml", "rejected-thrice.stubs.yaml",
                                   "third.stubs.yaml"})
        s = fx["settled.stubs.yaml"]
        self.assertEqual(s["fixture"]["expect"], "completed")
        self.assertIn("rejudge", s["fixture"]["reached"])
        self.assertNotIn("rejudge-third", s["fixture"]["reached"])
        self.assertEqual(s["rejudge"], load("rejudge_settled"))
        self.assertIs(s["collect"]["ok"], True)
        n = fx["no-session.stubs.yaml"]
        self.assertEqual(n["rj-route1"]["stopped"], True)
        self.assertNotIn("rejudge", n, "輪が飛ぶ（役の stub を置かない。走れば stub の無い節で落ちる）")
        self.assertIn("collect", n["fixture"]["reached"])
        r = fx["rejected-thrice.stubs.yaml"]
        self.assertIs(r["rejudge-accept"]["ok"], False)
        self.assertIs(r["collect"]["ok"], False)
        t = fx["third.stubs.yaml"]
        self.assertEqual(t["rj-route2"]["next"], "rejudge-third")
        self.assertIn("rejudge-third", t["fixture"]["reached"])
        self.assertEqual(t["rejudge-third"], load("rejudge_third_ok"))
        for name, f in fx.items():
            for nid, out in f.items():
                if nid in ("rejudge", "rejudge-third"):
                    with self.subTest(f"{name}:{nid}"):
                        self.assertEqual(validate_schema(out, rejudge.output_format(rejudge.node_of(nid))), [])


class ScriptCase(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self.addCleanup(self._home.cleanup)

    def board(self, kind="objection", session=True):
        self.bd, self.repo = BOARDS.fresh(kind)
        if session:
            os.environ[rejudge.ADAPTER_HOME_ENV] = self._home.name
            try:
                kit.put_session(self.repo)
            finally:
                del os.environ[rejudge.ADAPTER_HOME_ENV]

    def run_script(self, name, drop=(), direct=False, **inputs):
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        env.update({rejudge.ADAPTER_HOME_ENV: self._home.name, "ARTIFACTS_DIR": str(self.bd.parent),
                    "PYTHONDONTWRITEBYTECODE": "1"})
        env.update({f"INPUTS_{k.upper()}": v for k, v in inputs.items()})
        for k in drop:
            env.pop(k, None)
        argv = [str(BLK / "scripts" / f"{name}.py")] if direct else [str(CHILD), str(BLK / "scripts" / f"{name}.py")]
        r = subprocess.run([sys.executable, *argv], cwd=str(self.repo), env=env, capture_output=True, text=True)
        if r.returncode == 0:
            lines = r.stdout.splitlines()
            self.assertEqual(len(lines), 1, r.stdout + r.stderr)
            return 0, json.loads(lines[0]), r.stderr
        return r.returncode, r.stdout, r.stderr

    def ok(self, name, **inputs):
        rc, out, err = self.run_script(name, **inputs)
        self.assertEqual(rc, 0, err)
        return out

    def test_block_settled_path(self):
        self.board()
        self.ok("snap")
        self.assertEqual(self.ok("route")["next"], "rejudge")
        prep = self.ok("prep", role="rejudge")
        self.assertEqual(prep["attempt"], 1)
        got = self.ok("accept", role="rejudge", reply=json.dumps(load("rejudge_settled"), ensure_ascii=False))
        self.assertTrue(got["ok"], got)
        r2 = self.ok("route")
        self.assertEqual((r2["next"], r2["stopped"]), ("", False), r2)
        out = self.ok("collect")
        self.assertEqual((out["ok"], out["passes"], out["verdicts"]), (True, 1, ["採る"]), out)
        self.assertTrue(pathlib.Path(out["diff_file"]).is_file())

    def test_block_no_session_path(self):
        self.board(session=False)
        self.ok("snap")
        r1 = self.ok("route")
        self.assertEqual((r1["next"], r1["stopped"]), ("", True))
        self.assertTrue(self.ok("route")["stopped"])
        out = self.ok("collect")
        self.assertEqual((out["ok"], out["passes"]), (True, 0), out)
        self.assertEqual(kit.state(self.bd)["stop"]["by"], rejudge.STOP_BY_SESSION)

    def test_block_rejected_thrice(self):
        self.board()
        self.ok("snap")
        self.assertEqual(self.ok("route")["next"], "rejudge")
        attempts = []
        for _ in range(3):
            attempts.append(self.ok("prep", role="rejudge")["attempt"])
            got = self.ok("accept", role="rejudge", reply=json.dumps(load("rejudge_empty_facts"), ensure_ascii=False))
            self.assertFalse(got["ok"])
        self.assertEqual(attempts, [1, 1, 1])
        out = self.ok("collect")
        self.assertFalse(out["ok"])
        self.assertIn("3 回とも", out["reason"])
        self.assertEqual(kit.state(self.bd)["stop"]["by"], rejudge.STOP_BY)

    def test_scripts_exit_zero_on_expected(self):
        self.board("none")
        self.ok("snap")
        self.assertEqual(self.ok("route")["next"], "")          # 回す物が無い
        self.assertTrue(self.ok("collect")["ok"])
        # 読めない返答は役に返す（0 で ok: false）
        self.board()
        self.ok("snap")
        self.ok("route")
        self.ok("prep", role="rejudge")
        got = self.ok("accept", role="rejudge", reply="{JSON でない")
        self.assertFalse(got["ok"])
        self.assertIn("JSON", got["reason"])
        got = self.ok("accept", role="rejudge", reply="[1]")
        self.assertFalse(got["ok"])

    def test_scripts_exit_two_on_wiring(self):
        self.board("none")
        # 試験の入口を通さずに直に回す（スクリプトが rejudge を最初に import しても読み込める）
        rc, _, err = self.run_script("route", drop=("ARTIFACTS_DIR",), direct=True)
        self.assertEqual(rc, 2, err)
        self.assertIn("ARTIFACTS_DIR", err)
        rc, _, err = self.run_script("collect", direct=True)   # 表の無い手本の盤面は本物の口では開けない（BoardGap）
        self.assertEqual(rc, 2, err)
        self.assertIn("state.works.line", err)
        rc, _, err = self.run_script("prep")                   # INPUTS_ROLE が無い
        self.assertEqual(rc, 2)
        self.assertIn("INPUTS_ROLE", err)
        rc, out, err = self.run_script("prep", role="rejudge")  # 待っている instance が無い（BoardGap）
        self.assertEqual(rc, 2, out)
        self.assertEqual(out, "")
        self.assertIn("instance", err)
        rc, _, err = self.run_script("prep", role="no-such-role")
        self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
