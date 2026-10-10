"""仕様を固めるブロック blk-spec（本線 BLOCKS.md の R2。節 spec.write・spec.review・spec.revise・spec.approve・spec.freeze）の試験。

仕様の道は run の入力 flow=spec（写しの rules の check_inputs・on_init が loop.flow に写し、spec.* の節の条件 spec_flow が読む）が選ぶ。
works ではこの道を別の入口（darkfactory-spec。まだ作らない）が回す。ここでは、その入口が持つはずの節の表（1 本目のラインの表の
spec.write・spec.review・spec.revise を役・where blk-spec にした物）を試験の写しの pack にだけ置き、ブロックのスクリプトを
Archon と同じ形（cwd は対象・ARTIFACTS_DIR・INPUTS_*）の子のプロセスで回す。

- YAML の形: 3 つの役の輪（書く・審査・直す）は、盤面の ready だけで回すかを決める route の後ろに置き、輪は fresh_context・
  上限は GIVE_UP_AFTER・until_bash は受け付けの done（R50）。役の output_format は写しの schema に印 works-node: spec-<役>。
  人の関所 spec-gate は線 A の policy-gate と同じ形（decisions: approve・continue・stop・reject、文は境の節の at gate と同じ手順の gate_text）
- 指示書: blk-spec/prompts/ は本線 a1202d0 の指示書のバイト単位の写しで、engine と同じ描き方（Renderer と reads）で描く
- 筋書き: 書く → 審査（穴 1 件）→ 直す → 関所 → 固める。穴が無ければ直す役を飛ばす。関所の stop・輪の諦め・読むだけの役の変化・
  止め札・仕様の道でない run
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
BLK = ROOT / "blk-spec"
sys.path.insert(0, str(ROOT / ".shared" / "core"))
sys.path.insert(0, str(ROOT / "darkfactory" / "lib"))
sys.path.insert(0, str(TESTS))

import linekit  # noqa: E402
import answer as core_answer  # noqa: E402
import entry  # noqa: E402
import halt  # noqa: E402
import node_marker  # noqa: E402
import engine.util as engine_util  # noqa: E402
from accept import role_schema  # noqa: E402
from board import DiskBoard  # noqa: E402
from engine.schema import validate_schema  # noqa: E402

DEADLINE = 1728000000
LINE = "darkfactory-spec"             # 提案の別の入口（試験の写しの pack にだけ置く）
ORIGIN = f"works/{LINE}"
ROLES = {"write": "spec.write", "review": "spec.review", "revise": "spec.revise"}
WRITERS = ("write", "revise")
MAINLINE_PROMPTS = "graphloops/prompts/review-loop"
# 出口の欄（版 1）。欄を消すと後ろのブロック・ラインが読めなくなる——足すのはよいが消さない
EXIT_V1 = ("ok", "reason", "spec_file", "tests", "approved_by", "approval_note", "frozen_rev", "requirements", "acceptance",
           "faces", "handled")


def lib():
    """ブロックの芯（blk-spec/lib/specblk.py）。本物の pack の物を読む"""
    spec = importlib.util.spec_from_file_location("_blk_spec_lib", BLK / "lib" / "specblk.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def workflow():
    return yaml.safe_load((BLK / "blk-spec.yaml").read_text(encoding="utf-8"))


def walk(nodes, inside=None):
    for n in nodes or []:
        yield n, inside
        if "loop_group" in n:
            yield from walk(n["loop_group"].get("nodes"), n)


def script_inputs(name):
    spec = importlib.util.spec_from_file_location(f"_blk_spec_{name}", BLK / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.INPUTS


def spec_table_doc() -> dict:
    """ブロックの単独の試験の表: 線 darkfactory の表（仕様の段を任意の段として配線し、spec.write・spec.review・spec.revise は
    role・where blk-spec。spec.approve・spec.freeze・spec.check は builtin）の名だけを試験の写しの線の名にした物"""
    doc = json.loads((ROOT / "darkfactory" / "nodes.json").read_text(encoding="utf-8"))
    for nid in ROLES.values():
        assert (doc["nodes"][nid]["by"], doc["nodes"][nid]["where"]) == ("role", "blk-spec"), (nid, doc["nodes"][nid])
    doc["line"] = LINE
    return doc


# ---------------------------------------------------------------- YAML の形
class YamlCase(unittest.TestCase):
    def setUp(self):
        self.y = workflow()
        self.top = {n["id"]: n for n in self.y["nodes"]}
        self.L = lib()

    def test_inputs_and_exit(self):
        self.assertEqual(set(self.y["inputs"]), {"base_rev"})
        self.assertEqual((self.y["returns"], self.y["outcome_field"]), ("collect", "ok"))
        self.assertIs(self.y["interactive"], True, "関所（approval）を持つ工程は interactive を宣言する")
        self.assertEqual(list(self.top), ["write-route", "write-loop", "review-route", "review-loop", "revise-route",
                                          "revise-loop", "spec-ask", "spec-gate", "spec-answer", "collect"])
        fmt = self.top["collect"]["output_format"]
        self.assertEqual(set(fmt["required"]), set(EXIT_V1), "出口の版 1 の欄を全部持つ（消さない）")
        tests = fmt["properties"]["tests"]["items"]
        self.assertEqual(set(tests["required"]), {"file", "sha"})

    def test_route_then_loop(self):
        """3 つの輪は、それぞれの route（盤面の ready だけで決める。いつも走る）の go で回す。2 本目からの route は前の輪が
        飛ばされても走る（none_failed_min_one_success）"""
        prev = None
        for role in ROLES:
            route, loop = self.top[f"{role}-route"], self.top[f"{role}-loop"]
            with self.subTest(role):
                self.assertEqual(route["script"], "route")
                self.assertEqual(route["with"], {"role": role})
                if prev is None:
                    self.assertNotIn("depends_on", route)
                else:
                    self.assertEqual(route["depends_on"], [f"{prev}-route", f"{prev}-loop"])
                    self.assertEqual(route["trigger_rule"], "none_failed_min_one_success")
                self.assertEqual(loop["depends_on"], [f"{role}-route"])
                self.assertEqual(loop["when"], f"${role}-route.output.go == true")
                g = loop["loop_group"]
                self.assertIs(g["fresh_context"], True)
                self.assertEqual(g["max_iterations"], self.L.GIVE_UP_AFTER, "諦めの数は輪の上限と同じ（上限で輪を落とさない。R50）")
                self.assertEqual(g["until_bash"], f"test ${role}-accept.output.done = true")
                self.assertEqual([m["id"] for m in g["nodes"]], [f"{role}-prep", f"spec-{role}", f"{role}-accept"])
            prev = role

    def test_roles(self):
        for role, nid in ROLES.items():
            g = self.top[f"{role}-loop"]["loop_group"]
            ai = [m for m in g["nodes"] if "command" in m or "prompt" in m]
            with self.subTest(role):
                self.assertEqual([m["id"] for m in ai], [f"spec-{role}"], "輪の AI の節は役 1 つ")
                r = ai[0]
                self.assertEqual(r["command"], f"spec-{role}")
                self.assertEqual(r["output_format"], self.L.output_format(role))
                self.assertEqual(r["output_format"], node_marker.mark(role_schema(nid), f"spec-{role}"))
                self.assertEqual(r["settingSources"], ["user"])
                self.assertNotIn("context", r)
                self.assertEqual(r["idle_timeout"], DEADLINE)
                self.assertEqual(r["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})
                want = (["Read", "Grep", "Glob", "Edit", "Write", "Bash"] if role in WRITERS else ["Read", "Grep", "Glob"]) + ["WebSearch", "WebFetch"]
                self.assertEqual(r["allowed_tools"], want, "書く役（writer）はテストを書く。審査（judge）は読むだけ")
                accept = g["nodes"][2]
                self.assertEqual(accept["with"], {"role": role, "reply": {"from": f"$spec-{role}.output"}})

    def test_commands_thin(self):
        for role in ROLES:
            text = (BLK / "commands" / f"spec-{role}.md").read_text(encoding="utf-8")
            with self.subTest(role):
                self.assertIn(f"${role}-prep.output.prompt_file", text)
                self.assertNotIn("$LOOP_PREV", text, "拒否の文は prep が指示書の頭に書く（R44）")
                self.assertIn("前の回の受け付けが拒んだ理由", text)
                self.assertIn("JSON", text)
        self.assertIn("作業ツリーを 1 文字も変えてはいけない", (BLK / "commands" / "spec-review.md").read_text(encoding="utf-8"))
        for role in WRITERS:
            self.assertIn("テストのファイルだけ", (BLK / "commands" / f"spec-{role}.md").read_text(encoding="utf-8"))

    def test_gate_is_policy_gate_shape(self):
        """人の関所は線 A の policy-gate と同じ形: 文は境の節の at gate と同じ手順の gate_text、答えの語は GATE_GO・GATE_STOP、
        答えは次の script の節が with: で受けて盤面の answer に渡す"""
        ask, gate, ans, col = (self.top[k] for k in ("spec-ask", "spec-gate", "spec-answer", "collect"))
        self.assertEqual(ask["script"], "ask")
        self.assertEqual(ask["depends_on"], ["revise-route", "revise-loop"])
        self.assertEqual(ask["trigger_rule"], "none_failed_min_one_success")
        self.assertEqual(gate["depends_on"], ["spec-ask"])
        self.assertEqual(gate["when"], "$spec-ask.output.ask == true")
        ap = gate["approval"]
        self.assertIn("$spec-ask.output.gate_text", ap["message"])
        self.assertEqual([d["id"] for d in ap["decisions"]], list(self.L.GATE_GO + self.L.GATE_STOP))
        self.assertNotIn("capture_response", ap, "decisions を書いた関所の出口はいつも {decision, text}（古い鍵は書かない）")
        self.assertEqual(ans["script"], "answer")
        self.assertEqual(ans["depends_on"], ["spec-ask", "spec-gate"])
        self.assertEqual(ans["trigger_rule"], "none_failed_min_one_success")
        self.assertEqual(ans["with"], {"gate": {"from": "$spec-gate.output", "if_skipped": None}})
        self.assertEqual(col["depends_on"], ["spec-answer"])

    def test_gate_copies_match_line_edge(self):
        """境の節の中身はラインのモジュール（層 L6）で、ブロックからは import できない。写した関所の語・止め札の by・文の置き場が
        線 A の境の節と同じ（core の関所のモジュールへ 1 つにまとめるのは統合の計画 Task 10。それまで写しの食い違いをここで止める）"""
        spec = importlib.util.spec_from_file_location("_line_edge_for_spec", ROOT / "darkfactory" / "lib" / "line_edge.py")
        edge = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(edge)
        for name in ("GATE_GO", "GATE_STOP", "GATE_STOP_NOTE", "FLAG_BY_PREFIX", "FLAG_SEEN_OP"):
            with self.subTest(name):
                self.assertEqual(getattr(self.L, name), getattr(edge, name))
        # 文の置き場は線の関所の文（公開の名。線の持ち物）と違う名にする: 線に include した仕様の段が線の公開の名を書くと、
        # scope の照らしが「宣言の外に書いた」で盤面を止める（線に配線して本物のスクリプトで回して見つけた。test_script_contract の spec）
        self.assertNotEqual(self.L.GATE_FILE, edge.GATE_FILE)

    def test_script_inputs_match_with(self):
        for n, _ in walk(self.y["nodes"]):
            if "script" not in n:
                continue
            with self.subTest(n["id"]):
                want = {f"INPUTS_{k.upper()}" for k in (n.get("with") or {})}
                self.assertEqual(set(script_inputs(n["script"])), want)
                self.assertEqual(n["timeout"], DEADLINE)
                self.assertEqual(n["runtime"], "uv")
        on_disk = {p.stem for p in (BLK / "scripts").glob("*.py")}
        used = {n["script"] for n, _ in walk(self.y["nodes"]) if "script" in n}
        self.assertEqual(on_disk, used, "scripts/ の .py は全部 YAML の節（モジュールは lib/）")

    def test_prompts_are_mainline_copies(self):
        """指示書の写し（blk-spec/prompts/）は、COPIED_FROM の 1 行目の commit の本線の指示書とバイト単位で同じ。
        commit は写しの graphloops（.shared/core/COPIED_FROM）と同じ"""
        base = BLK / "prompts"
        lines = (base / "COPIED_FROM").read_text(encoding="utf-8").splitlines()
        commit = lines[0].split()[0]
        core = (ROOT / ".shared" / "core" / "COPIED_FROM").read_text(encoding="utf-8").splitlines()[0].split()[0]
        self.assertEqual(commit, core)
        listed = [ln.split()[0] for ln in lines[1:] if ln.strip() and not ln.startswith("#")]
        self.assertEqual(sorted(listed), sorted(f"{nid}.md" for nid in ROLES.values()))
        self.assertEqual(sorted(listed), sorted(p.name for p in base.glob("*.md")))
        for name in listed:
            with self.subTest(name):
                src = subprocess.run(["git", "-C", str(ROOT), "show", f"{commit}:{MAINLINE_PROMPTS}/{name}"],
                                     capture_output=True, check=True).stdout
                self.assertEqual((base / name).read_bytes(), src)

    def test_fixtures(self):
        fx = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in (BLK / "fixtures").glob("*.stubs.yaml")}
        self.assertEqual(set(fx), {"pass.stubs.yaml", "no-faces.stubs.yaml", "gate-stop.stubs.yaml", "give-up.stubs.yaml"})
        full = ["write-route", "write-prep", "spec-write", "write-accept", "review-route", "review-prep", "spec-review",
                "review-accept", "revise-route", "revise-prep", "spec-revise", "revise-accept", "spec-ask", "spec-gate",
                "spec-answer", "collect"]
        for name, f in fx.items():
            with self.subTest(name):
                self.assertEqual(f["fixture"]["expect"], "completed")
                self.assertNotIn("spec-gate", f, "関所（approval）は stub を取らない（模擬実行では自動で通る）")
                for role in ROLES:
                    if f"spec-{role}" in f:
                        self.assertEqual(validate_schema(f[f"spec-{role}"], self.L.output_format(role)), [], role)
                self.assertEqual(set(EXIT_V1) - set(f["collect"]), set(), "筋書きの出口も版 1 の欄を全部持つ")
        p = fx["pass.stubs.yaml"]
        self.assertEqual(p["fixture"]["reached"], full)
        self.assertIs(p["collect"]["ok"], True)
        self.assertEqual(p["spec-answer"]["decision"], "approve")
        n = fx["no-faces.stubs.yaml"]
        self.assertIs(n["revise-route"]["go"], False)
        self.assertEqual(n["fixture"]["reached"], [x for x in full if x not in ("revise-prep", "spec-revise", "revise-accept")])
        s = fx["gate-stop.stubs.yaml"]
        self.assertEqual((s["spec-answer"]["decision"], s["spec-answer"]["stop"]), ("stop", True))
        self.assertIs(s["collect"]["ok"], False)
        g = fx["give-up.stubs.yaml"]
        self.assertEqual((g["write-accept"]["ok"], g["write-accept"]["done"], g["write-accept"]["give_up"]), (False, True, True))
        self.assertIs(g["spec-ask"]["ask"], False)
        self.assertIs(g["collect"]["ok"], False)
        self.assertEqual(g["fixture"]["reached"], ["write-route", "write-prep", "spec-write", "write-accept", "review-route",
                                                   "revise-route", "spec-ask", "spec-answer", "collect"])
        self.assertIn("dry-run は until_bash を回さず", (BLK / "fixtures" / "give-up.stubs.yaml").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- スクリプト（子のプロセス）
ACCEPT_TEST = '''"""受け入れ条件（仕様の道の試験で writer の代わりに書く）"""
import unittest

from stats import mean


class TestSpec(unittest.TestCase):
    def test_mean_is_middle(self):
        # Given 1, 2, 3 の 3 つの数
        # When mean を呼ぶ
        # Then 2 を返す
        self.assertEqual(mean([1, 2, 3]), 2)


if __name__ == "__main__":
    unittest.main()
'''
ACCEPT_RUN = "python3 -m unittest test_spec_accept"


def write_reply(file="test_spec_accept.py"):
    return {"requirements": [{"key": "R1", "text": "mean は 3 つの数の平均を返す"}],
            "acceptance": [{"key": "A1", "requirement": "R1", "file": file, "name": "test_mean_is_middle", "run": ACCEPT_RUN}],
            "out_of_scope": []}


FACE = {"key": "F1", "kind": "missing", "where": "R1", "why": "空の列の平均をどう扱うかが要件にも受け入れ条件にも無い（例外か 0 か）"}


def review_reply(faces=True):
    if faces:
        return {"faces": [FACE], "reason": "要件 R1 と受け入れ条件 A1 を読み、境目の入力を確かめた"}
    return {"faces": [], "faces_none": "要件 R1 と A1 の Then は依頼の 2 つ目と同じ値を見ている。範囲の外も無い",
            "reason": "要件 R1 と受け入れ条件 A1 を読み、境目の入力を確かめた"}


def revise_reply():
    spec = write_reply()
    spec["out_of_scope"] = ["空の列の平均（依頼に無い。今の実装の ZeroDivisionError のまま）"]
    return {"spec": spec, "handled": [{"key": "F1", "handled": "declared",
                                       "how": "空の列は依頼の範囲の外と決め、out_of_scope に理由つきで足した"}]}


class ScriptCase(unittest.TestCase):
    """試験の写しの pack（本物の .shared と blk-spec の写し＋別の入口の表の案）で盤面を作り、スクリプトを子のプロセスで回す"""

    flow = "spec"

    @classmethod
    def setUpClass(cls):
        cls.home = pathlib.Path(tempfile.mkdtemp(dir=linekit.work_home()))
        cls.pack = cls.home / "pack"
        for sub in (".shared", "blk-spec", "darkfactory"):
            shutil.copytree(ROOT / sub, cls.pack / sub, ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".DS_Store"))
        (cls.pack / LINE).mkdir()
        (cls.pack / LINE / "nodes.json").write_text(json.dumps(spec_table_doc(), ensure_ascii=False, indent=1) + "\n",
                                                    encoding="utf-8")

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.home, ignore_errors=True)

    def setUp(self):
        self._old_cwd = engine_util.GIT_CWD
        self.addCleanup(setattr, engine_util, "GIT_CWD", self._old_cwd)
        p = mock.patch.object(entry, "PACK", self.pack)
        p.start()
        self.addCleanup(p.stop)
        self.tmp = pathlib.Path(tempfile.mkdtemp(dir=self.home))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.repo = linekit.seed_repo(self.tmp / "repo", declared=True)
        self.art = self.tmp / "art"
        self.board = self.art / "board"
        table = entry.load_table(LINE)
        items = json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
        b, p = DiskBoard.begin(self.board, repo=self.repo, table=table, items=items, origin=ORIGIN, base_rev="",
                               request_text=json.dumps(items, ensure_ascii=False), stop_after_round=1,
                               inputs={"flow": self.flow} if self.flow else {}, **entry.open_kwargs(LINE, table))
        # 修正前の CI（p0.local_checks。種の宣言を engine が走らせる）だけを済ませる。仕様の道でない run では spec.* が na になり、
        # その先の p0.parallel_pr は種が remote を持たない（forge の無い run）ので機械が条件外にする（このブロックの試験には要らない）
        self.assertEqual(p["run_engine"], ["p0.local_checks"], p)
        self.assertTrue(b.run_engine("p0.local_checks").get("ok"))
        b.settle()

    def opened(self):
        return entry.open_board(self.board, allow_halted=True)

    def run_script(self, name, **inputs):
        # 答えの行の頭（起動の殻が置く）も外から継がない: 殻の中でも外でも頭の無い単独の run として回す
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_") and k != core_answer.ENV}
        env.update({"ARTIFACTS_DIR": str(self.art), "PYTHONDONTWRITEBYTECODE": "1", "WORKFLOW_ID": "run-spec"})
        env.update({f"INPUTS_{k.upper()}": v for k, v in inputs.items()})
        r = subprocess.run([sys.executable, str(self.pack / "blk-spec" / "scripts" / f"{name}.py")], cwd=str(self.repo),
                           env=env, capture_output=True, text=True, encoding="utf-8")
        if r.returncode == 0:
            lines = r.stdout.splitlines()
            self.assertEqual(len(lines), 1, r.stdout + r.stderr)
            return 0, json.loads(lines[0]), r.stderr
        return r.returncode, r.stdout, r.stderr

    def ok(self, name, **inputs):
        rc, out, err = self.run_script(name, **inputs)
        self.assertEqual(rc, 0, err)
        return out

    def run_loop(self, role, reply, before_accept=None):
        """Archon の輪と同じ順: 周ごとに prep → 役（返答は reply。dict か、周の番号を受けて返す関数）→ accept → until_bash の式を sh で。
        抜けた周の番号と各周の (prep, accept)。max_iterations 回で抜けなければ番号は None（Archon は輪を failed にする）"""
        g = next(n for n in workflow()["nodes"] if n.get("id") == f"{role}-loop")["loop_group"]
        rounds = []
        for i in range(1, g["max_iterations"] + 1):
            prep = self.ok("prep", role=role)
            if before_accept:
                before_accept(i)
            body = reply(i) if callable(reply) else reply
            raw = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
            got = self.ok("accept", role=role, reply=raw)
            rounds.append((prep, got))

            def value(m):
                self.assertEqual(m.group(1), f"{role}-accept", "until_bash は同じ輪の受け付けの欄だけを読む")
                return json.dumps(got[m.group(2)])
            cond = re.sub(r"\$([A-Za-z0-9_-]+)\.output\.([A-Za-z0-9_]+)", value, g["until_bash"])
            if subprocess.run(["sh", "-c", cond]).returncode == 0:
                return i, rounds
        return None, rounds

    def write_tests(self):
        (self.repo / "test_spec_accept.py").write_text(ACCEPT_TEST, encoding="utf-8")

    def written(self):
        self.assertIs(self.ok("route", role="write")["go"], True)
        exited, rounds = self.run_loop("write", write_reply(), before_accept=lambda i: self.write_tests())
        self.assertEqual(exited, 1)
        return rounds[0]

    def gate(self, decision, text=""):
        ask = self.ok("ask")
        self.assertIs(ask["ask"], True, ask)
        got = self.ok("answer", gate=json.dumps({"decision": decision, "text": text}, ensure_ascii=False))
        return ask, got

    # -- 筋書き
    def test_pass_path(self):
        prep, got = self.written()
        self.assertEqual((prep["node"], prep["attempt"], prep["already"]), ("spec.write", 1, False))
        prompt = pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("仕様を書く（writer の仕事。仕様の道だけ）", prompt, "本線の指示書の本文")
        self.assertIn("mean([1, 2, 3])", prompt, "依頼（inputs.request）を描いた")
        self.assertIn(str(self.repo), prompt, "リポジトリ（inputs.cwd）を描いた")
        self.assertIn("返答はこの JSON Schema に合う JSON だけ", prompt, "engine と同じく schema を足す")
        self.assertNotIn("{{", prompt)
        self.assertTrue(got["ok"], got)
        # 審査（読むだけ）: 穴 1 件
        self.assertIs(self.ok("route", role="review")["go"], True)
        exited, rounds = self.run_loop("review", review_reply())
        self.assertEqual(exited, 1)
        prompt = pathlib.Path(rounds[0][0]["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn("test_mean_is_middle", prompt, "writer の仕様（out.spec.write）を描いた")
        # 直す: 穴に答える
        self.assertIs(self.ok("route", role="revise")["go"], True)
        exited, rounds = self.run_loop("revise", revise_reply())
        self.assertEqual(exited, 1)
        self.assertIn("F1", pathlib.Path(rounds[0][0]["prompt_file"]).read_text(encoding="utf-8"))
        # 関所: 承認の前に run は走らせない（記録に仕様は無い）。文に run のコマンドの字面と審査の穴と答え
        b = self.opened()
        self.assertEqual(b.state["pending_human"]["node"], "spec.approve")
        self.assertNotIn("spec", b.record["process"])
        ask, got = self.gate("approve", "受け入れ条件 A1 で進めてよい")
        for part in (ACCEPT_RUN, "spec.approve", "F1", "declared",
                     core_answer.line("run-spec", "continue", "<通す範囲と条件>", env={}),
                     core_answer.line("run-spec", "stop", "<理由>", env={})):
            self.assertIn(part, ask["gate_text"])
        self.assertNotIn("archon workflow", ask["gate_text"])   # PATH に無い archon を直に打つ行は書かない
        self.assertIn("process.spec.approval", ask["gate_text"], "仕様の承認の一言の行き先")
        self.assertNotIn("human_items", ask["gate_text"])
        self.assertTrue(pathlib.Path(self.board / "r1" / lib().GATE_FILE).is_file())
        self.assertEqual((got["answered"], got["decision"], got["stop"]), (True, "approve", False), got)
        b = self.opened()
        self.assertEqual(b.node_state("spec.freeze"), "done")
        spec = b.record["process"]["spec"]
        self.assertEqual(spec["approval"]["answer"], "continue")
        self.assertEqual(spec["approval"]["note"], "受け入れ条件 A1 で進めてよい")
        self.assertEqual(spec["acceptance"][0]["exit_at_approval"], 1, "承認の後に走らせた（mean の誤りで赤）")
        self.assertEqual(spec["out_of_scope"], revise_reply()["spec"]["out_of_scope"], "直した版を固めた")
        self.assertEqual(b.record["process"]["request_findings"][-1]["origin"],
                         "仕様（人が承認した受け入れ条件。テストの本文は writer が書いた）")
        out = self.ok("collect")
        self.assertIs(out["ok"], True, out)
        sha = spec["acceptance"][0]["sha256"]
        self.assertEqual(out["tests"], [{"file": "test_spec_accept.py", "sha": sha}])
        self.assertEqual(out["approved_by"], lib().GATE_BY)
        self.assertEqual(out["approval_note"], "受け入れ条件 A1 で進めてよい")
        self.assertEqual(out["frozen_rev"], linekit.git(self.repo, "rev-parse", "HEAD"))
        self.assertEqual((out["requirements"], out["acceptance"], out["faces"], out["handled"]), (1, 1, 1, 1))
        self.assertEqual(json.loads(pathlib.Path(out["spec_file"]).read_text(encoding="utf-8")), spec)
        self.assertEqual(set(out), set(EXIT_V1))
        # 呼び直し（Archon の再開）: 答えは 2 度当てない
        again = self.ok("answer", gate=json.dumps({"decision": "approve", "text": "二度目"}, ensure_ascii=False))
        self.assertIs(again["answered"], False)
        self.assertEqual(self.opened().record["process"]["spec"]["approval"]["note"], "受け入れ条件 A1 で進めてよい")

    def test_no_faces_skips_revise(self):
        """審査が穴を挙げなければ spec.revise は写しの条件（spec_revise_due）で na。直す役を起こさずに関所へ"""
        self.written()
        self.ok("route", role="review")
        self.assertEqual(self.run_loop("review", review_reply(faces=False))[0], 1)
        route = self.ok("route", role="revise")
        self.assertIs(route["go"], False)
        self.assertIn("na", route["why"])
        ask, got = self.gate("continue")
        self.assertNotIn("審査の穴", ask["gate_text"])
        self.assertIs(got["stop"], False)
        out = self.ok("collect")
        self.assertIs(out["ok"], True, out)
        self.assertEqual((out["faces"], out["handled"]), (0, 0))

    def test_gate_stop(self):
        """関所で stop（reject も同じ）→ 盤面は halted（by answer）・仕様は固めない・出口は ok false と人の一言"""
        for decision in ("stop", "reject"):
            with self.subTest(decision):
                self.setUp()
                self.written()
                self.ok("route", role="review")
                self.run_loop("review", review_reply(faces=False))
                ask, got = self.gate(decision, "受け入れ条件が弱い")
                self.assertEqual((got["answered"], got["stop"]), (True, True), got)
                b = self.opened()
                self.assertEqual((b.state["halted"]["by"], b.state["halted"]["node"]), ("answer", "spec.approve"))
                self.assertNotIn("spec", b.record["process"])
                out = self.ok("collect")
                self.assertIs(out["ok"], False)
                self.assertIn("受け入れ条件が弱い", out["reason"])
                self.assertEqual(out["tests"], [])

    def test_give_up_after_three(self):
        """書く役の返答が 3 回とも拒まれる（テストのファイルが無い）→ 3 回目で done・give_up。後ろの route は go false、関所は
        開かず、出口が最後の拒否の文で盤面を止める（by works:spec）"""
        self.assertIs(self.ok("route", role="write")["go"], True)
        exited, rounds = self.run_loop("write", write_reply(file="missing_test.py"))
        self.assertEqual(exited, 3)
        self.assertEqual([(g["ok"], g["done"], g["give_up"]) for _, g in rounds],
                         [(False, False, False), (False, False, False), (False, True, True)])
        self.assertIn("missing_test.py", rounds[0][1]["reason"])
        second = pathlib.Path(rounds[1][0]["prompt_file"]).read_text(encoding="utf-8")
        self.assertTrue(second.startswith(lib().REJECT_HEADING), "拒否の文は指示書の頭（R44）")
        self.assertIn("missing_test.py", second)
        self.assertEqual([p["already"] for p, _ in rounds], [False, True, True], "拒否の後の出し直しは同じ試行")
        self.assertIs(self.ok("route", role="review")["go"], False)
        self.assertIs(self.ok("route", role="revise")["go"], False)
        self.assertIs(self.ok("ask")["ask"], False)
        self.assertIs(self.ok("answer", gate="null")["answered"], False)
        out = self.ok("collect")
        self.assertIs(out["ok"], False)
        self.assertIn("3 回とも", out["reason"])
        self.assertEqual(self.opened().state["stop"]["by"], lib().STOP_BY)

    def test_review_is_read_only(self):
        """審査の役が作業ツリーを変えたら拒む（役を起こす前の写しと比べる）。元に戻せば通る"""
        self.written()
        self.ok("route", role="review")

        def touch(i):
            if i == 1:
                (self.repo / "note.txt").write_text("x\n", encoding="utf-8")
            else:
                (self.repo / "note.txt").unlink(missing_ok=True)
        exited, rounds = self.run_loop("review", review_reply(), before_accept=touch)
        self.assertEqual(exited, 2)
        self.assertIn("読むだけの役が作業ツリーを変えた", rounds[0][1]["reason"])
        self.assertTrue(rounds[1][1]["ok"])

    def test_unreadable_reply_is_counted(self):
        self.ok("route", role="write")
        exited, rounds = self.run_loop("write", "これは JSON でない")
        self.assertEqual(exited, 3)
        self.assertIn("JSON", rounds[0][1]["reason"])

    def test_stop_flag_before_review(self):
        """止め札（halt.place）は役の輪の前の route が見る: 盤面を止めて go false（線 A の境の節と同じ by request:<札の by>）"""
        self.written()
        self.assertTrue(halt.place(self.board, "やめる", "tester")["ok"])
        route = self.ok("route", role="review")
        self.assertIs(route["go"], False)
        self.assertEqual(self.opened().state["stop"]["by"], lib().FLAG_BY_PREFIX + "tester")
        self.assertIs(self.ok("ask")["ask"], False)
        out = self.ok("collect")
        self.assertIs(out["ok"], False)
        self.assertIn("やめる", out["reason"])

    def test_answer_rejects_unknown_word(self):
        self.written()
        self.ok("route", role="review")
        self.run_loop("review", review_reply(faces=False))
        self.assertIs(self.ok("ask")["ask"], True)
        rc, _, err = self.run_script("answer", gate=json.dumps({"decision": "maybe"}))
        self.assertEqual(rc, 2)
        self.assertIn("maybe", err)
        self.assertEqual(self.opened().state["pending_human"]["node"], "spec.approve", "知らない語では答えない")



class LineSpecCase(ScriptCase):
    """線 darkfactory の入口（entry.start）で入力 spec=on を渡した run。依頼だけ（差分が空）の入口で仕様の段を挟み、仕様の書き手が
    受け入れ条件のテストを書いても入口の印（差分が空の印）は start の測りのまま。origin は GitHub の形で偽の gh が交差を返すので、
    並行 PR の確かめは仕様を固めた後に境の節 h-spec（line_edge.spec_edge）で初めて任せ先の役に落ちる"""

    def setUp(self):
        self._old_cwd = engine_util.GIT_CWD
        self.addCleanup(setattr, engine_util, "GIT_CWD", self._old_cwd)
        p = mock.patch.object(entry, "PACK", self.pack)
        p.start()
        self.addCleanup(p.stop)
        self.tmp = pathlib.Path(tempfile.mkdtemp(dir=self.home))
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        env = mock.patch.dict("os.environ", {"WORKS_ADAPTER_HOME": str(self.tmp / "adapter-home")})
        env.start()
        self.addCleanup(env.stop)
        self.repo = linekit.seed_repo(self.tmp / "repo", declared=True)
        env = mock.patch.dict("os.environ", {"PATH": linekit.github_crossing(self.repo, self.tmp)})
        env.start()
        self.addCleanup(env.stop)
        self.art = self.tmp / "art"
        self.board = self.art / "board"
        req = self.tmp / "request.json"
        req.write_text((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        raw = {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "final_gate": "", "adapter": "",
               "policy_md": "", "spec": "on"}
        self.out = entry.start(self.board, self.repo, raw, run_id="run-spec")

    def test_spec_reaches_board_flow(self):
        """入力 spec=on → 盤面の inputs.flow と loop.flow が spec、spec.write が待つ。入口の入力の形の spec が真で、頭の行に出る。
        並行 PR の確かめは版を固める前なので、まだ出ていない"""
        b = self.opened()
        self.assertEqual((b.state["inputs"]["flow"], b.loop_state.get("flow")), ("spec", "spec"))
        self.assertIn("spec.write", b.ready())
        self.assertIs(self.out["input"]["spec"], True)
        self.assertIn("仕様の段あり", self.out["head_line"])
        self.assertEqual(b.node_state("p0.parallel_pr"), "pending")
        self.assertNotIn("p0.parallel_pr", b.ready())

    def test_spec_write_sees_request_rows(self):
        """依頼の行は盤面を作る時に積まれているので、仕様の書き手の指示書に依頼の行が載る（前の後積みでは届かなかった）"""
        prep, _ = self.written()
        self.assertIn("mean([1, 2, 3])", pathlib.Path(prep["prompt_file"]).read_text(encoding="utf-8"))
        self.assertEqual(len(self.opened().record["process"]["request_findings"]), 1)

    def test_spec_tests_do_not_flip_the_mark_and_edge_drains_parallel_pr(self):
        """仕様の書き手が受け入れ条件のテストのファイルを足して承認・固めた後も、入口の印は start の測り（差分が空）のまま在り、
        版を固める p1.worktree_before は空差分の柵で止まらない。h-spec（spec_edge）は盤面の engine の節を回し直し（版を固めた後に
        出た並行 PR の確かめを回す）、任せ先の役が待つかを pr_go に出す"""
        import line_edge
        self.written()
        self.assertIs(self.ok("route", role="review")["go"], True)
        self.assertEqual(self.run_loop("review", review_reply(faces=False))[0], 1)
        self.assertIs(self.ok("route", role="revise")["go"], False)
        self.gate("approve", "進めてよい")
        b = self.opened()
        self.assertEqual(b.node_state("spec.freeze"), "done")
        self.assertEqual(b.record["process"]["request_entry"]["origin"], entry.ORIGIN)
        self.assertFalse(b.state.get("halted"))
        self.assertEqual(b.node_state("p1.worktree_before"), "done")
        self.assertEqual(b.node_state("p0.parallel_pr"), "pending")   # 版を固めた後に出る。まだ回していない
        got = line_edge.spec_edge(b)
        b = self.opened()
        self.assertTrue(b.node_state("p0.parallel_pr") != "pending" or "p0.parallel_pr" in b.ready(),
                        "h-spec が並行 PR の確かめを回し直していない")
        self.assertEqual(got, {"go": True, "pr_go": "p0.parallel_pr" in b.ready()})

    # 親の筋書きは試験の写しの線の盤面の物
    test_pass_path = test_no_faces_skips_revise = test_gate_stop = test_give_up_after_three = None
    test_review_is_read_only = test_unreadable_reply_is_counted = test_stop_flag_before_review = None
    test_answer_rejects_unknown_word = None

class NotSpecFlowCase(ScriptCase):
    """flow=spec の無い run（spec.* の節は写しの条件 spec_flow で na）にブロックを差したのは配線の誤り: 最初の route が 2 で落ちる"""

    flow = None

    def test_route_refuses(self):
        rc, _, err = self.run_script("route", role="write")
        self.assertEqual(rc, 2)
        self.assertIn("flow=spec", err)

    # 親の筋書きは仕様の道の run の物
    test_pass_path = test_no_faces_skips_revise = test_gate_stop = test_give_up_after_three = None
    test_review_is_read_only = test_unreadable_reply_is_counted = test_stop_flag_before_review = None
    test_answer_rejects_unknown_word = None


if __name__ == "__main__":
    unittest.main()
