"""同じ周の再審のブロック（blk-rejudge）の検査。rejudge 設計の 23b（段 1＝写しの graphloops 0.21.0 の形）。

- YAML の形: 役の output_format が rejudge.output_format（写しの schema に印）と同じ・when: が読むのはいつも走る rj-route<k> の
  欄だけ・輪は fresh_context で AI の節は 1 つ・役の id は印の名・continue= を持つ役だけ context: fresh・段の並びは passes() の順・
  スクリプトが読む INPUTS_* と with: の鍵が同じ
- スクリプト: 別のプロセスで Archon と同じ形（cwd は対象・ARTIFACTS_DIR・INPUTS_*）に回す。予定の状態（拒否・止めた・回す物が
  無い）は終了コード 0 で 1 行、配線の誤り（環境変数の欠け・BoardGap）だけ 2
- 筋書き（fixtures/）が 4 本在り、期待の形が設計 11.2 どおりか。Archon で回すのは dev/check.sh（workflow test）
盤面は tests/rejudgekit.py の手本の盤面（1 本目のラインの本物の表）。スクリプトは子のプロセスで直に回し、本物の entry.open_board で開く。
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
import stopby  # noqa: E402  （止めの理由の住処）

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-rejudge"
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
        self.assertNotIn("inputs", self.y)   # 段のスクリプトは盤面だけを読む（版も方針も盤面が持つ）
        self.assertEqual((self.y["returns"], self.y["outcome_field"]), ("collect", "ok"))

    def test_yaml_output_formats_match(self):
        for grp in self.loops():
            ai = [m for m in grp["loop_group"]["nodes"] if "command" in m]
            with self.subTest(grp["id"]):
                self.assertEqual(ai[0]["output_format"], rejudge.output_format(rejudge.node_of(ai[0]["id"])))
                # 良い返答の見本が YAML の型を通る
                self.assertEqual(validate_schema(load("rejudge_settled"), ai[0]["output_format"]), [])

    def test_stages_follow_copied_passes(self):
        """段 k（rj-route<k> → 輪）の役が passes() の k 番目。段の並び＝写しの依存の並び。段は 1 つ（p2.rejudge）だけで、
        0.21.0 の規則が ready にしない第三の目（p2.rejudge_third）の段は持たない"""
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
        self.assertEqual(got, roles[:1])
        self.assertEqual(rejudge.node_of(roles[1]), "p2.rejudge_third")

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
                self.assertEqual(g["max_iterations"], rejudge.GIVE_UP_AFTER, "諦めの数は輪の上限と同じ（上限で輪を落とさない）")
                ai = [m for m in g["nodes"] if "command" in m or "prompt" in m]
                self.assertEqual(len(ai), 1)
                role = ai[0]
                p = next(x for x in rejudge.passes() if x["role"] == role["id"])
                mark = rejudge.output_format(p["node"])["description"]
                self.assertEqual(mark.split()[1], role["id"], "役の id は印の名")
                self.assertEqual(role.get("context") == "fresh", p["cont"] is not None, "continue= を持つ役だけ context: fresh")
                self.assertEqual(role["command"], role["id"])
                self.assertTrue((BLK / "commands" / f"{role['id']}.md").is_file())
                self.assertEqual(role["allowed_tools"], ["Read", "Grep", "Glob", "WebSearch", "WebFetch"])
                self.assertEqual(role["settingSources"], ["user"])
                self.assertEqual(role["idle_timeout"], DEADLINE)
                ids = [m["id"] for m in g["nodes"]]
                self.assertEqual(ids, [f"{role['id']}-prep", role["id"], f"{role['id']}-accept"])
                self.assertEqual(g["until_bash"], f"test ${role['id']}-accept.output.done = true")

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
                # 拒否の文を $LOOP_PREV で貼らない（Archon が文の中の $<節>.output.<欄> を置き換え直して輪ごと落ちる。裁定 R44）。
                # 拒否の文は prep が描いた指示書の頭に置く（役は Read で読む）
                self.assertNotIn("$LOOP_PREV", text)
                self.assertIn("前の回の受け付けが拒んだ理由", text)
                self.assertNotIn("$INPUTS.policy_paste", text, "方針は描いた指示書に入っている")
                self.assertNotIn("{{", text, "指示書を写さない（本文は engine の描画）")

    def test_no_loop_prev_reaches_a_prompt(self):
        """役に届く文（commands と YAML の prompt）のどこにも $LOOP_PREV が無い"""
        for p in sorted((BLK / "commands").glob("*.md")):
            self.assertNotIn("$LOOP_PREV", p.read_text(encoding="utf-8"), p.name)
        for n, _ in walk(self.y["nodes"]):
            self.assertNotIn("$LOOP_PREV", str(n.get("prompt", "")), n["id"])

    def test_fixtures(self):
        fx = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in (BLK / "fixtures").glob("*.stubs.yaml")}
        self.assertEqual(set(fx), {"settled.stubs.yaml", "no-session.stubs.yaml", "rejected-thrice.stubs.yaml"})
        s = fx["settled.stubs.yaml"]
        self.assertEqual(s["fixture"]["expect"], "completed")
        self.assertIn("rejudge", s["fixture"]["reached"])
        self.assertEqual(s["rejudge"], load("rejudge_settled"))
        self.assertIs(s["collect"]["ok"], True)
        n = fx["no-session.stubs.yaml"]
        self.assertEqual(n["rj-route1"]["stopped"], True)
        self.assertNotIn("rejudge", n, "輪が飛ぶ（役の stub を置かない。走れば stub の無い節で落ちる）")
        self.assertIn("collect", n["fixture"]["reached"])
        r = fx["rejected-thrice.stubs.yaml"]
        self.assertIs(r["rejudge-accept"]["ok"], False)
        self.assertIs(r["rejudge-accept"]["done"], True)   # 3 回目の拒否の諦めの印
        head = (BLK / "fixtures" / "rejected-thrice.stubs.yaml").read_text(encoding="utf-8")
        self.assertIn("dry-run は until_bash を回さず", head, "筋書きは輪の抜け方を見ていないと書く")
        self.assertIs(r["collect"]["ok"], False)
        for name, f in fx.items():
            for nid, out in f.items():
                if nid == "rejudge":
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

    def run_script(self, name, drop=(), **inputs):
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        env.update({rejudge.ADAPTER_HOME_ENV: self._home.name, "ARTIFACTS_DIR": str(self.bd.parent),
                    "PYTHONDONTWRITEBYTECODE": "1"})
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

    def run_loop(self, role, reply):
        """Archon の輪と同じ順に回す: 周ごとに prep → 役（返答は reply）→ accept → until_bash の式を sh で評価（式の中の
        $<役>-accept.output.<欄> は accept の出口の値を JSON で置く）。抜けた周の番号と各周の (prep, accept) を返す。
        max_iterations 回で抜けなければ番号は None——Archon は輪を failed にし、後ろの節（collect）は走らない"""
        g = next(n for n in workflow()["nodes"] if n.get("id") == f"{role}-loop")["loop_group"]
        rounds = []
        for i in range(1, g["max_iterations"] + 1):
            prep = self.ok("prep", role=role)
            got = self.ok("accept", role=role, reply=json.dumps(reply, ensure_ascii=False))
            rounds.append((prep, got))

            def value(m):
                self.assertEqual(m.group(1), f"{role}-accept", "until_bash は同じ輪の受け付けの欄だけを読む")
                return json.dumps(got[m.group(2)])
            cond = re.sub(r"\$([A-Za-z0-9_-]+)\.output\.([A-Za-z0-9_]+)", value, g["until_bash"])
            if subprocess.run(["sh", "-c", cond]).returncode == 0:
                return i, rounds
        return None, rounds

    def test_block_settled_path(self):
        self.board()
        self.ok("snap")
        self.assertEqual(self.ok("route")["next"], "rejudge")
        exited, rounds = self.run_loop("rejudge", load("rejudge_settled"))
        self.assertEqual(exited, 1)
        prep, got = rounds[0]
        self.assertEqual(prep["attempt"], 1)
        self.assertTrue(got["ok"], got)
        r2 = self.ok("route")
        self.assertEqual((r2["next"], r2["stopped"]), ("", False), r2)
        out = self.ok("collect")
        self.assertEqual((out["ok"], out["passes"], out["verdicts"]), (True, 1, ["採る"]), out)
        self.assertTrue(pathlib.Path(out["diff_file"]).is_file())
        # 出口の欄は全部 YAML の出口の型に在り、必須（読み手が名前で読む欄を型が落とさない）
        fmt = next(n for n in workflow()["nodes"] if n["id"] == "collect")["output_format"]
        self.assertEqual(validate_schema(out, fmt), [])
        self.assertEqual(set(fmt["required"]), set(out))

    def test_block_no_session_path(self):
        self.board(session=False)
        self.ok("snap")
        r1 = self.ok("route")
        self.assertEqual((r1["next"], r1["stopped"]), ("", True))
        self.assertTrue(self.ok("route")["stopped"])
        out = self.ok("collect")
        self.assertEqual((out["ok"], out["passes"]), (True, 0), out)
        self.assertEqual(kit.state(self.bd)["stop"]["by"], stopby.REJUDGE_SESSION)

    def test_loop_gives_up_after_three_rejections(self):
        """3 回とも拒まれても輪は max_iterations で落ちず（3 回目の受け付けが done を出し until_bash が抜ける）、collect が
        走って、最後の拒否の文で盤面を止める（設計 9.3。裁定 R50）"""
        self.board()
        self.ok("snap")
        self.assertEqual(self.ok("route")["next"], "rejudge")
        exited, rounds = self.run_loop("rejudge", load("rejudge_empty_facts"))
        self.assertEqual(exited, rejudge.GIVE_UP_AFTER, "輪が上限まで抜けない（Archon は run を落とす）")
        self.assertEqual([p["attempt"] for p, _ in rounds], [1] * rejudge.GIVE_UP_AFTER)
        self.assertEqual([(a["ok"], a["give_up"]) for _, a in rounds],
                         [(False, False)] * (rejudge.GIVE_UP_AFTER - 1) + [(False, True)])
        # 2 回目からの指示書の頭に前の拒否の文（$LOOP_PREV を通さない）
        second = pathlib.Path(rounds[1][0]["prompt_file"]).read_text(encoding="utf-8")
        self.assertTrue(second.startswith(rejudge.REJECT_HEADING))
        self.assertIn(rounds[0][1]["reason"], second)
        out = self.ok("collect")
        self.assertFalse(out["ok"])
        self.assertIn("3 回とも", out["reason"])
        self.assertIn(rounds[-1][1]["reason"].splitlines()[0], out["reason"])
        st = kit.state(self.bd)
        self.assertEqual(st["stop"]["by"], stopby.REJUDGE)
        self.assertIn("$.new_facts", st["stop"]["reason"])

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

    def test_rejudge_defects_query_matching_fixed_form_is_rejected(self):
        """再審も class_query を書き換えられる入口なので、判定と同じく例で問いを試す（querytest）"""
        self.board()
        self.ok("snap")
        self.ok("route")
        self.ok("prep", role="rejudge")
        reply = load("rejudge_settled")
        fixed = "    return min(x, cap)  # 上限"
        reply["units"][0]["class_query"] = {
            "how": {"patterns": ["min(x"], "paths": ["src/a.py"], "count": "lines", "fixed": True},
            "counts": "defects", "total": 1, "hits": ["    return min(x, 0)"], "misses": [fixed]}
        got = self.ok("accept", role="rejudge", reply=json.dumps(reply, ensure_ascii=False))
        self.assertFalse(got["ok"], got)
        text = got.get("reason", "")
        if got.get("reason_file"):
            text += pathlib.Path(got["reason_file"]).read_text(encoding="utf-8")
        self.assertIn("直した後の正しい形にも当たる", text)
        self.assertIn(fixed.strip(), text)

    def test_scripts_exit_two_on_wiring(self):
        self.board("none")
        rc, _, err = self.run_script("route", drop=("ARTIFACTS_DIR",))
        self.assertEqual(rc, 2, err)
        self.assertIn("ARTIFACTS_DIR", err)
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
