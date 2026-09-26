"""ライン darkfactory（判定→修正→テスト→人の承認→差分の審査）の検査。

- 口（interactive・inputs・returns・outcome_field）と節の並び・配線（include の with:）
- include の id とブロックの中の節の id がぶつからないこと（Ruling R17）。Archon 0.11.1 の模擬実行は輪（loop_group）の
  中の節を名前空間の付かない id で stub に引くので、輪の中の節の id もライン全体で一意であること
- 節 base（bash）を使い捨ての git で実際に起こし、HEAD を {ok, rev} で出すこと
- 関所（approval）の文にテストの緑赤とログのパスが載り、返答を取っておくこと
- 筋書き（fixtures/）の形: wiring は stub を置ける節を全部 stub し、tests-red はテストの節だけ赤にして完走する
"""
import json
import pathlib
import subprocess
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
LINE = ROOT / "darkfactory"
REPLIES = pathlib.Path(__file__).resolve().parent / "replies"
DEADLINE = 1728000000
BLOCKS = {"judging": "blk-judge", "fixing": "blk-fix", "testing": "blk-tests", "reviewing": "blk-delta"}
GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


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
        self.assertEqual(y["returns"], "reviewing")
        self.assertEqual(y["outcome_field"], "ok")
        # returns の先（blk-delta の出口 collect）が ok を真偽で持つ
        collect = next(n for n in block("blk-delta")["nodes"] if n["id"] == block("blk-delta")["returns"])
        self.assertEqual(collect["output_format"]["properties"]["ok"], {"type": "boolean"})
        self.assertIn("ok", collect["output_format"]["required"])

    def test_nodes_in_order(self):
        nodes = line()["nodes"]
        self.assertEqual([n["id"] for n in nodes], ["base", "judging", "fixing", "testing", "gate", "reviewing"])
        self.assertNotIn("depends_on", nodes[0])
        for prev, cur in zip(nodes, nodes[1:]):
            with self.subTest(cur["id"]):
                self.assertEqual(cur["depends_on"], [prev["id"]])
        for n in nodes:
            if "include" in n:
                with self.subTest(n["id"]):
                    self.assertEqual(n["include"], BLOCKS[n["id"]])

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
        self.assertEqual(set(gate), {"id", "approval", "depends_on"})
        ap = gate["approval"]
        self.assertIs(ap["capture_response"], True)
        self.assertNotIn("on_reject", ap)          # 拒めば run を止める
        for ref in ("$testing.output.green", "$testing.output.log"):
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


class TestLineFixtures(unittest.TestCase):
    def fixtures(self):
        return {p.name: load_yaml(p) for p in (LINE / "fixtures").glob("*.stubs.yaml")}

    def test_fixture_names(self):
        self.assertEqual(set(self.fixtures()), {"wiring.stubs.yaml", "tests-red.stubs.yaml"})

    def test_every_stubbable_node_is_stubbed(self):
        # include で入った script・bash の節は、模擬実行では呼び手の with: が届かないので本物で回せない
        for name, f in self.fixtures().items():
            with self.subTest(name):
                self.assertEqual(set(f) - {"fixture", "exec-code"}, set(stub_keys()))
                self.assertNotIn("exec-code", f)
                self.assertEqual(set(f["fixture"]["inputs"]), {"request", "test_cmd"})

    def test_role_stubs_are_the_good_samples(self):
        for name, f in self.fixtures().items():
            with self.subTest(name):
                self.assertEqual(f["judge"], reply("judge_ok"))
                self.assertEqual(f["fix"], reply("fix_ok"))
                self.assertEqual(f["review"], reply("delta_ok"))

    def test_wiring(self):
        f = self.fixtures()["wiring.stubs.yaml"]
        self.assertEqual(f["fixture"]["expect"], "completed")
        self.assertEqual(f["fixture"]["reached"], ["gate", "reviewing__collect"])
        self.assertIs(f["testing__run"]["green"], True)

    def test_tests_red(self):
        # テストが赤でも関所は模擬実行で自動で通り（--pause-at-gates 無し）、差分の審査まで完走する
        f = self.fixtures()["tests-red.stubs.yaml"]
        self.assertEqual(f["fixture"]["expect"], "completed")
        self.assertIs(f["testing__run"]["ok"], True)
        self.assertIs(f["testing__run"]["green"], False)
        self.assertEqual(f["fixture"]["reached"], ["testing__run", "gate", "reviewing__collect"])
        self.assertNotIn("pause-at-gates", f["fixture"])


if __name__ == "__main__":
    unittest.main()
