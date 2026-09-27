"""ライン darkfactory（判定→修正→テスト→人の承認→差分の審査）の検査。

- 口（interactive・inputs・returns・outcome_field）と節の並び・配線（include の with:）
- include の id とブロックの中の節の id がぶつからないこと（Ruling R17）。Archon 0.11.1 の模擬実行は輪（loop_group）の
  中の節を名前空間の付かない id で stub に引くので、輪の中の節の id もライン全体で一意であること
- 節 base（bash）を使い捨ての git で実際に起こし、HEAD を {ok, rev} で出すこと
- 関所（approval）の文にテストの緑赤とログのパス・判定の一手・判定のファイルが載り、返答を取っておくこと
- 直す物が無い判定（need_fix: false）なら修正から後を when: で飛ばし、いつも走る節 finish で終えること（Ruling R21）。
  finish のスクリプトを別のプロセスで起こして、出口の形を見る
- 筋書き（fixtures/）の形: wiring は finish 以外の stub を置ける節を全部 stub し（finish は exec-code で本物を回す）、
  tests-red はテストの節だけ赤にして完走し、no-fix は判定だけで finish まで届く
"""
import json
import pathlib
import os
import subprocess
import sys
import tempfile
import unittest

import yaml

from gitkit import GIT_ID

ROOT = pathlib.Path(__file__).resolve().parents[1]
LINE = ROOT / "darkfactory"
REPLIES = pathlib.Path(__file__).resolve().parent / "replies"
DEADLINE = 1728000000
BLOCKS = {"judging": "blk-judge", "fixing": "blk-fix", "testing": "blk-tests", "reviewing": "blk-delta"}
NEED_FIX = "$judging.output.need_fix == true"
SKIPPABLE = ("fixing", "testing", "gate", "reviewing")


def load_yaml(path):
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def line():
    return load_yaml(LINE / "darkfactory.yaml")


def block(name):
    return load_yaml(ROOT / name / f"{name}.yaml")


def reply(name):
    return json.loads((REPLIES / f"{name}.json").read_text(encoding="utf-8"))


def node(nid):
    return next(n for n in line()["nodes"] if n["id"] == nid)


def body_ids(nodes):
    """輪の中の節の id（入れ子も辿る）"""
    out = []
    for n in nodes:
        if "loop_group" in n:
            inner = n["loop_group"]["nodes"]
            out += [m["id"] for m in inner] + body_ids(inner)
    return out


def stub_keys():
    """模擬実行が stub を引く鍵の一覧（重なりも残す）。Archon 0.11.1 の dry-run.ts: include で入った節は
    <include の id>__<節の id>、輪の中の節は名前空間の付かない id。approval・loop_group は stub を取らない"""
    keys = []
    for n in line()["nodes"]:
        if "include" in n:
            b = block(n["include"])["nodes"]
            keys += [f"{n['id']}__{m['id']}" for m in b if "loop_group" not in m]
            keys += body_ids(b)
        elif "approval" not in n and "loop_group" not in n:
            keys.append(n["id"])
    return keys


class TestLineShape(unittest.TestCase):
    def test_line_includes_all_blocks(self):
        got = {n["include"] for n in line()["nodes"] if "include" in n}
        self.assertEqual(got, {"blk-judge", "blk-fix", "blk-tests", "blk-delta"})

    def test_signature(self):
        y = line()
        self.assertEqual(y["name"], "darkfactory")
        self.assertIs(y["interactive"], True)
        self.assertEqual(set(y["inputs"]), {"request", "test_cmd"})
        for k in ("request", "test_cmd"):
            self.assertIs(y["inputs"][k]["required"], True)
        self.assertEqual(y["returns"], "finish")
        self.assertEqual(y["outcome_field"], "ok")
        # returns の先（いつも走る節 finish）が ok を真偽で持つ
        of = node("finish")["output_format"]
        self.assertEqual(of["properties"]["ok"], {"type": "boolean"})
        self.assertEqual(of["properties"]["outcome"], {"type": "string", "enum": ["fixed", "no_fix_needed"]})
        self.assertEqual(sorted(of["required"]), ["judgment_file", "ok", "outcome"])
        self.assertLessEqual({"review_file", "diff_file", "faces"}, set(of["properties"]))

    def test_nodes_in_order(self):
        nodes = line()["nodes"]
        self.assertEqual([n["id"] for n in nodes],
                         ["base", "judging", "fixing", "testing", "gate", "reviewing", "finish"])
        self.assertNotIn("depends_on", nodes[0])
        for prev, cur in zip(nodes[:-1], nodes[1:-1]):
            with self.subTest(cur["id"]):
                self.assertEqual(cur["depends_on"], [prev["id"]])
        for n in nodes:
            if "include" in n:
                with self.subTest(n["id"]):
                    self.assertEqual(n["include"], BLOCKS[n["id"]])

    def test_skips_after_judging_when_nothing_to_fix(self):
        # Ruling R21: 直す物が無い判定は失敗ではない。修正・テスト・関所・審査を飛ばす
        for nid in SKIPPABLE:
            with self.subTest(nid):
                self.assertEqual(node(nid)["when"], NEED_FIX)
        for nid in ("base", "judging", "finish"):
            with self.subTest(nid):
                self.assertNotIn("when", node(nid))

    def test_finish_node(self):
        fin = node("finish")
        self.assertEqual((fin["script"], fin["runtime"], fin["timeout"]), ("finish", "uv", DEADLINE))
        self.assertEqual(fin["depends_on"], ["judging", "reviewing"])
        self.assertEqual(fin["trigger_rule"], "none_failed_min_one_success")
        self.assertEqual(fin["with"], {"judged": {"from": "$judging.output"},
                                       "review": {"from": "$reviewing.output", "if_skipped": None}})
        self.assertTrue((LINE / "scripts" / "finish.py").is_file())

    def test_include_with(self):
        self.assertEqual(node("judging")["with"], {"request": "$INPUTS.request", "base_rev": "$base.output.rev"})
        self.assertEqual(node("fixing")["with"], {"judgment_file": "$judging.output.judgment_file",
                                                  "open_units": "$judging.output.open_units",
                                                  "base_rev": "$base.output.rev"})
        self.assertEqual(node("testing")["with"], {"cmd": "$INPUTS.test_cmd"})
        self.assertEqual(node("reviewing")["with"], {"base_rev": "$base.output.rev"})

    def test_include_with_matches_block_inputs(self):
        # 渡す鍵はブロックが宣言した入力だけ、required の入力は全部渡す
        for inc, name in BLOCKS.items():
            with self.subTest(inc):
                inputs = block(name)["inputs"]
                given = set(node(inc)["with"])
                self.assertLessEqual(given, set(inputs))
                self.assertLessEqual({k for k, v in inputs.items() if v.get("required")}, given)

    def test_ids_do_not_collide_with_block_nodes(self):
        # Ruling R17: include の id がブロックの中の節の id と同じだと、ブロックの中の $<id>.output が include を指す
        inner = set()
        for name in BLOCKS.values():
            b = block(name)["nodes"]
            inner |= {n["id"] for n in b} | set(body_ids(b))
        self.assertEqual({n["id"] for n in line()["nodes"]} & inner, set())

    def test_stub_keys_are_unique(self):
        # 輪の中の節は名前空間の付かない id で stub を引く。ブロックをまたいで同じ id があると、1 つの stub が
        # 型の違う複数の節に当たり、筋書きが書けない（dry-run の --stubs-init も拒む）
        keys = stub_keys()
        self.assertEqual(len(keys), len(set(keys)), sorted(k for k in keys if keys.count(k) > 1))

    def test_base_node(self):
        base = node("base")
        self.assertIn("git rev-parse HEAD", base["bash"])
        self.assertEqual(base["timeout"], DEADLINE)
        of = base["output_format"]
        self.assertIs(of["additionalProperties"], False)
        self.assertEqual(set(of["required"]), {"ok", "rev"})
        self.assertEqual(of["properties"], {"ok": {"type": "boolean"}, "rev": {"type": "string"}})

    def test_gate(self):
        gate = node("gate")
        self.assertEqual(set(gate), {"id", "approval", "depends_on", "when"})
        ap = gate["approval"]
        self.assertIs(ap["capture_response"], True)
        self.assertNotIn("on_reject", ap)          # 拒めば run を止める
        for ref in ("$testing.output.green", "$testing.output.log", "$judging.output.one_shot", "$fixing.output.removed",
                    "$judging.output.judgment_file", "Archon の run ごとの worktree"):
            self.assertIn(ref, ap["message"])


class TestBaseNodeRuns(unittest.TestCase):
    """節 base の bash の本文を、使い捨ての git の根で bash に渡して起こす"""

    def run_base(self, cwd):
        return subprocess.run(["bash", "-c", node("base")["bash"]], cwd=cwd, capture_output=True, text=True)

    def test_prints_head(self):
        with tempfile.TemporaryDirectory() as tmp:
            subprocess.run(["git", *GIT_ID, "init", "-q", tmp], check=True)
            (pathlib.Path(tmp) / "a.txt").write_text("a\n", encoding="utf-8")
            subprocess.run(["git", *GIT_ID, "-C", tmp, "add", "-A"], check=True)
            subprocess.run(["git", *GIT_ID, "-C", tmp, "commit", "-qm", "a"], check=True)
            head = subprocess.run(["git", "-C", tmp, "rev-parse", "HEAD"], capture_output=True, text=True,
                                  check=True).stdout.strip()
            r = self.run_base(tmp)
            self.assertEqual(r.returncode, 0, r.stderr)
            self.assertEqual(json.loads(r.stdout), {"ok": True, "rev": head})

    def test_fails_outside_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            r = self.run_base(tmp)
            self.assertNotEqual(r.returncode, 0)
            self.assertEqual(r.stdout, "")


class TestFinishRuns(unittest.TestCase):
    """節 finish のスクリプトを別のプロセスで起こす（INPUTS_JUDGED・INPUTS_REVIEW は Archon が with: から渡す JSON の文字列）"""

    JUDGED = {"ok": True, "open_units": ["u"], "need_fix": True, "judgment_file": "/a/board/judgment.json",
              "one_shot": "直す"}
    REVIEW = {"ok": True, "faces": 2, "review_file": "/a/board/delta-review.json", "diff_file": "/a/board/fix.diff"}

    def run_it(self, judged, review):
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        for name, value in (("INPUTS_JUDGED", judged), ("INPUTS_REVIEW", review)):
            if value is not None:
                env[name] = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
        with tempfile.TemporaryDirectory() as tmp:
            return subprocess.run([sys.executable, str(LINE / "scripts" / "finish.py")], cwd=tmp, env=env,
                                  capture_output=True, text=True, timeout=60)

    def assert_out(self, r, want):
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got, want)
        from engine.schema import validate_schema   # noqa: E402（core は下の setUpModule で path に入る）
        self.assertEqual(validate_schema(got, node("finish")["output_format"]), [])

    def test_fixed(self):
        self.assert_out(self.run_it(self.JUDGED, self.REVIEW), {
            "ok": True, "outcome": "fixed", "judgment_file": "/a/board/judgment.json",
            "review_file": "/a/board/delta-review.json", "diff_file": "/a/board/fix.diff", "faces": 2})

    def test_no_fix_needed(self):
        judged = dict(self.JUDGED, open_units=[], need_fix=False)
        self.assert_out(self.run_it(judged, "null"), {
            "ok": True, "outcome": "no_fix_needed", "judgment_file": "/a/board/judgment.json"})

    def test_inconsistent_or_unreadable_fails(self):
        cases = {
            "need_fix なのに審査が無い": (self.JUDGED, "null"),
            "直す物が無いのに審査が在る": (dict(self.JUDGED, open_units=[], need_fix=False), self.REVIEW),
            "判定が JSON でない": ("not json", "null"),
            "判定に need_fix が無い": ({k: v for k, v in self.JUDGED.items() if k != "need_fix"}, self.REVIEW),
            "審査の出口が崩れている": (self.JUDGED, {"ok": True, "faces": 0}),
            "環境変数が無い": (None, None),
        }
        for why, (judged, review) in cases.items():
            with self.subTest(why):
                r = self.run_it(judged, review)
                self.assertNotEqual(r.returncode, 0)
                self.assertEqual(r.stdout, "")
                self.assertEqual(r.stderr.strip().count("\n"), 0, "理由は 1 行")


def setUpModule():
    sys.path.insert(0, str(ROOT / ".shared" / "core"))


class TestLineFixtures(unittest.TestCase):
    FULL = ("wiring.stubs.yaml", "tests-red.stubs.yaml")
    JUDGE_ONLY = {"base", "judging__intake", "judge", "judge-accept", "judging__collect"}

    def fixtures(self):
        return {p.name: load_yaml(p) for p in (LINE / "fixtures").glob("*.stubs.yaml")}

    def test_fixture_names(self):
        self.assertEqual(set(self.fixtures()), {"wiring.stubs.yaml", "tests-red.stubs.yaml", "no-fix.stubs.yaml"})

    def test_every_stubbable_node_is_stubbed(self):
        # include で入った script・bash の節は、模擬実行では呼び手の with: が届かないので本物で回せない。
        # finish だけは stub せず exec-code で本物を回す（自分の with: は模擬実行でも届く）
        for name, f in self.fixtures().items():
            with self.subTest(name):
                want = set(stub_keys()) - {"finish"} if name in self.FULL else self.JUDGE_ONLY
                self.assertEqual(set(f) - {"fixture", "exec-code"}, want)
                self.assertIs(f["exec-code"], True)
                self.assertEqual(set(f["fixture"]["inputs"]), {"request", "test_cmd"})
                self.assertEqual(f["fixture"]["reached"][-1], "finish")

    def test_role_stubs_are_the_good_samples(self):
        for name in self.FULL:
            f = self.fixtures()[name]
            with self.subTest(name):
                self.assertEqual(f["judge"], reply("judge_ok"))
                self.assertEqual(f["fix"], reply("fix2_ok"))
                self.assertEqual(f["review"], reply("delta_ok"))
                self.assertIs(f["judging__collect"]["need_fix"], True)

    def test_no_fix(self):
        # 判定が直す物を 1 つも残さない。修正から後の stub は置かない（走れば「stub の無い節に届いた」で落ちる）
        f = self.fixtures()["no-fix.stubs.yaml"]
        self.assertEqual(f["fixture"]["expect"], "completed")
        self.assertEqual(f["fixture"]["reached"], ["judging__collect", "finish"])
        self.assertEqual(f["judge"], reply("judge_no_fix"))
        self.assertEqual(f["judge-accept"]["open_units"], [])
        self.assertEqual((f["judging__collect"]["open_units"], f["judging__collect"]["need_fix"]), ([], False))

    def test_wiring(self):
        f = self.fixtures()["wiring.stubs.yaml"]
        self.assertEqual(f["fixture"]["expect"], "completed")
        self.assertEqual(f["fixture"]["reached"], ["gate", "reviewing__collect", "finish"])
        self.assertIs(f["testing__run"]["green"], True)

    def test_tests_red(self):
        # テストが赤でも関所は模擬実行で自動で通り（--pause-at-gates 無し）、差分の審査まで完走する
        f = self.fixtures()["tests-red.stubs.yaml"]
        self.assertEqual(f["fixture"]["expect"], "completed")
        self.assertIs(f["testing__run"]["ok"], True)
        self.assertIs(f["testing__run"]["green"], False)
        self.assertEqual(f["fixture"]["reached"], ["testing__run", "gate", "reviewing__collect", "finish"])
        self.assertNotIn("pause-at-gates", f["fixture"])


if __name__ == "__main__":
    unittest.main()
