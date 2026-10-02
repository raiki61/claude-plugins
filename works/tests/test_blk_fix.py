"""修正のブロック（blk-fix）の検査。

- YAML の口（inputs・returns・outcome_field・節の並び）と、修正役の output_format を良い返答の見本（replies/fix_ok.json）が通るか
  （YAML の切り替えは線 A の Task 17。それまで役の output_format は 1 本目のまま。切り替えで貼る値は recount.FIX_OUTPUT_FORMAT）
- 役の指示書（fix-prep が修正の決まりの正本と直す役の決まりと run の値から組む。fixrules）が値と決まり（commit しない・
  テストを消さない）を持つか。盤面の上の fix-prep（2 つの形・起こした印・出し直しの理由のファイル・読んだ証拠）
- 筋書き（fixtures/）の形: pass は受け付け・assert-changed・collect を stub し、no-change は assert-changed を実物で回して落とす
- 数え直し（線 A Task 12。仕様 3.2）: 受け付けは盤面の done("p3.fix")。写しの fix_covers_open_units が判定役の class_query を
  修正前の版と修正後の作業ツリーで数え直す。盤面は linekit の種で start → 前提・並行 PR・判定・修正案・事前審査を take で渡して作る
- 5 本のスクリプト（ignored_before・accept・clean・assert_changed・collect）を、dev/target-seed/ を写した使い捨ての git で実際に起こす
"""
import ast
import hashlib
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

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-fix"
CORE = ROOT / ".shared" / "core"
TESTS = pathlib.Path(__file__).resolve().parent
REPLIES = TESTS / "replies"
SEED = ROOT / "dev" / "target-seed"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(CORE / "graphloops"))
sys.path.insert(0, str(TESTS))

import adapter  # noqa: E402
from accept import role_schema  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
import engine.util as engine_util  # noqa: E402
import entry  # noqa: E402
from gitkit import committed_copy, git  # noqa: E402
import linekit  # noqa: E402
import node_marker  # noqa: E402
import hermetic  # noqa: E402
if str(BLK / "lib") not in sys.path:   # 修正のブロックの模块（brief の凍結）。後ろに足して core の名を隠さない
    sys.path.append(str(BLK / "lib"))
import planbrief  # noqa: E402
import planmarks  # noqa: E402

DEADLINE = 1728000000
# 実行器の無い run の tdd-start の出口（tddloop.start の go: false。test_blk_fix_tdd が実物で見る）
NO_SUITE_START = {"go": False, "reason": "テストの実行器（入力 tdd_suite）が無い run——全部の単位を今どおり直す", "suite": "",
                  "state_file": "", "summary_file": ""}


def load(name):
    return json.loads((REPLIES / f"{name}.json").read_text(encoding="utf-8"))


def block():
    return yaml.safe_load((BLK / "blk-fix.yaml").read_text(encoding="utf-8"))


def find_node(nodes, nid):
    """節の一覧（loop_group の中も辿る）から id が nid の節"""
    for n in nodes:
        if n.get("id") == nid:
            return n
        if "loop_group" in n:
            found = find_node(n["loop_group"]["nodes"], nid)
            if found is not None:
                return found
    return None


def run_script(name, repo, env):
    """blk-fix/scripts/<name>.py を repo を cwd にして起こす。(終了コード, 標準出力, 標準エラー)"""
    full = {"PATH": os.environ["PATH"], "PYTHONDONTWRITEBYTECODE": "1", **env}
    r = subprocess.run([sys.executable, str(BLK / "scripts" / f"{name}.py")], cwd=str(repo), env=full,
                       capture_output=True, text=True, encoding="utf-8", stdin=subprocess.DEVNULL, timeout=120)
    return r.returncode, r.stdout, r.stderr


class TestBlockYaml(unittest.TestCase):
    def test_fix_yaml_output_format_is_the_constant(self):
        """〔線A計〕T17: 役の output_format は recount.FIX_OUTPUT_FORMAT（写しの p3.fix の schema に印 works-node: fix）を貼った物。
        見本の 2 本目の返答は通り、欄を足した返答は型で拒む（additionalProperties: false）"""
        import recount
        fix = find_node(block()["nodes"], "fix")
        self.assertEqual(fix["output_format"], recount.FIX_OUTPUT_FORMAT)
        self.assertEqual(validate_schema(load("fix2_ok"), fix["output_format"]), [])
        self.assertNotEqual(validate_schema({**load("fix2_ok"), "done": True}, fix["output_format"]), [])

    def test_signature(self):
        y = block()
        self.assertEqual(y["name"], "blk-fix")
        self.assertEqual(set(y["inputs"]), {"judgment_file", "open_units", "base_rev", "plan_file", "notes_file", "policy_path",
                                            "tdd_suite"})
        for k in ("base_rev", "plan_file", "notes_file", "policy_path", "tdd_suite"):   # 足した物は空でよい（仕様 3.2・TDD の輪）
            self.assertEqual(y["inputs"][k].get("default"), "", k)
            self.assertNotIn("required", y["inputs"][k], k)
        self.assertEqual(y["returns"], "collect")
        self.assertEqual(y["outcome_field"], "ok")
        out = find_node(y["nodes"], "collect")["output_format"]
        # 1 本目の欄と tdd（TDD の輪の欄）は必須のまま、盤面の欄（fix_file・not_done・coverage・reads_file）を任意で足す（〔線A計〕T17）
        self.assertEqual(set(out["properties"]), {"ok", "files", "changes_file", "removed", "tdd", "fix_file", "not_done",
                                                  "coverage", "reads_file", "reason"})
        self.assertEqual(set(out["required"]), {"ok", "files", "changes_file", "removed", "tdd"})
        # 消したパスの全件は出口に持たない（出口の大きさに上限が在る）。件数と全件を書いた盤面のファイルだけ
        self.assertEqual(out["properties"]["removed"]["type"], "object")
        self.assertEqual(set(out["properties"]["removed"]["required"]), {"count", "file"})
        clean = find_node(y["nodes"], "clean")["output_format"]
        self.assertEqual(set(clean["required"]), {"ok", "count", "file"})
        self.assertNotIn("removed", clean["properties"])
        self.assertEqual(out["properties"]["ok"]["type"], "boolean")
        self.assertEqual(out["properties"]["files"], {"type": "array", "items": {"type": "string"}})
        self.assertEqual(out["properties"]["changes_file"]["type"], "string")

    def test_nodes_and_loop(self):
        nodes = block()["nodes"]
        self.assertEqual([n["id"] for n in nodes],
                         ["ignored-before", "tdd-start", "tdd-loop", "fix-loop", "conflict-check", "rule-loop", "fix-ruled-loop",
                          "clean", "assert-changed", "fix-reads", "collect"])
        # TDD の輪の節は test_blk_fix_tdd、食い違いの申し出の 3 節は test_blk_fix_conflict が見る
        before, _start, _tdd, loop, _check, _rule, _ruled, clean, changed, reads, collect = nodes
        self.assertEqual((reads["script"], reads["depends_on"]), ("reads", ["assert-changed"]))
        self.assertEqual(reads["with"], {"must": '["$INPUTS.judgment_file"]'})
        self.assertNotIn("depends_on", before)
        self.assertEqual(before["script"], "ignored_before")
        self.assertEqual(loop["depends_on"], ["tdd-start", "tdd-loop"], "控えは修正役より前（tdd-start が ignored-before の後）")
        self.assertEqual(clean["script"], "clean")
        self.assertEqual(clean["depends_on"], ["fix-loop", "conflict-check", "rule-loop", "fix-ruled-loop"])
        self.assertEqual(collect["with"]["cleaned"], {"from": "$clean.output"})
        g = loop["loop_group"]
        self.assertEqual(g["max_iterations"], 3)
        self.assertIs(g["fresh_context"], False)
        self.assertEqual(g["until_bash"], "test $fix-accept.output.done = true", "通った時か 3 回目の拒否で抜ける（R50）")
        self.assertEqual([n["id"] for n in g["nodes"]], ["fix-prep", "fix", "fix-accept"])
        self.assertEqual(changed["depends_on"], ["clean"])
        self.assertEqual(collect["depends_on"], ["fix-reads"])
        accept = find_node(nodes, "fix-accept")
        self.assertEqual(accept["script"], "accept")
        self.assertEqual(accept["with"]["reply"], {"from": "$fix.output"})
        self.assertEqual(changed["script"], "assert_changed")
        for n in (before, accept, clean, changed, collect):
            self.assertEqual(n["timeout"], DEADLINE)
        self.assertEqual(changed["with"], {"base_rev": "$INPUTS.base_rev", "accepted": "$fix-loop.output",
                                           "ruled": {"from": "$fix-ruled-loop.output", "if_skipped": None}})
        self.assertEqual(accept["with"]["base_rev"], "$INPUTS.base_rev")
        self.assertEqual(accept["with"]["tdd_state"], "$tdd-start.output.state_file")
        self.assertEqual(accept["with"]["iteration"], "$fix-prep.output.iteration", "輪の何回目か（done を決める）")
        self.assertIn("iteration", find_node(nodes, "fix-prep")["output_format"]["required"])
        self.assertIn("done", accept["output_format"]["required"])
        import importlib.util
        spec = importlib.util.spec_from_file_location("blk_fix_accept_for_yaml", BLK / "scripts" / "accept.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.assertEqual(mod.GIVE_UP_AFTER, g["max_iterations"], "諦める回数は輪の上限と同じ")

    def test_fix_node(self):
        fix = find_node(block()["nodes"], "fix")
        self.assertNotIn("command", fix)
        self.assertEqual(fix["depends_on"], ["fix-prep"])
        self.assertIn("`$fix-prep.output.prompt_file` を Read で", fix["prompt"])
        prep = find_node(block()["nodes"], "fix-prep")
        self.assertEqual((prep["script"], prep["timeout"]), ("fix_prep", DEADLINE))
        self.assertEqual(fix["allowed_tools"], ["Read", "Grep", "Glob", "Edit", "Write", "Bash", "WebSearch", "WebFetch"])
        self.assertEqual(fix["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})
        self.assertEqual(fix["idle_timeout"], DEADLINE)
        of = fix["output_format"]
        self.assertIs(of["additionalProperties"], False)
        self.assertEqual(of["description"], "works-node: fix")

    def fix_prompt(self):
        import fixrules
        return fixrules.fix_prompt({k: f"/b/{k}" for k in fixrules.FIX_VALUES})

    def test_fix_prompt(self):
        """組んだ指示書: run の値は全部パスで埋まり（Archon の $ の置き換えに通さない）、決まり（commit しない・テスト）と欄を持つ"""
        import fixrules
        body = self.fix_prompt()
        for k in fixrules.FIX_VALUES:
            self.assertIn(f"`/b/{k}`", body)
        for s in ("git commit", "テスト", "unit_key"):
            self.assertIn(s, body)
        for gone in ("$INPUTS", "$LOOP_PREV", "{{", "<<"):
            self.assertNotIn(gone, body)
        # 役の節に with: は無い（run の値は fix-prep の with: で届き、指示書にパスで書かれる）
        self.assertNotIn("with", find_node(block()["nodes"], "fix"))

    def test_fix_prompt_reads_inputs(self):
        """0.21.0 の p3.fix.md から書き直した指示書: 修正案・人の答え・方針の文書・TDD の輪の結果を run の値のパスから読む。
        前の回の拒否の理由は reason_file（パス）で指示書の頭に（裁定 R44）。返答の欄は graph の p3.fix の schema の欄を名指し、
        判定の prescriptions（零処方）を先に採らせる"""
        import fixrules
        body = self.fix_prompt()
        for s in ("修正案", "人が関所で答えたこと", "人の方針の文書", "TDD の輪の結果"):
            self.assertIn(s, body)
        for field in role_schema("p3.fix")["properties"]:
            if field in ("x_scalars", "decision_records_changed", "premise_drift_note"):
                continue   # 任意の欄（書く周だけ）。指示書は別の段落で触れる
            self.assertIn(f"`{field}`", body, field)
        for field in ("closure", "coverage", "precedent", "root_or_symptom", "bypass_tried", "breaks"):
            self.assertIn(f"`{field}`", body, field)
        self.assertIn("`prescriptions`", body)
        self.assertIn("零処方", body)
        # 盤面の無い物を読ませない: engine の穴（{{…}}）・前の周の R1/R4・並行の線の合流は無い
        for gone in ("{{", "prev.r1", "prev.r4", "lane_merge"):
            self.assertNotIn(gone, body)
        again = fixrules.fix_prompt({k: f"/b/{k}" for k in fixrules.FIX_VALUES}, reject_file="/b/reject-accept_fix-1.txt")
        self.assertIn("/b/reject-accept_fix-1.txt", again.split("\n")[1])

    def test_output_format_constant_matches_graph(self):
        """T17 で YAML の fix に貼る値: 印を外すと graph の p3.fix の schema と同じ。印の名は fix。rejudge_requested の欄は
        graph の schema に元から在る（T23 の再審の起点）"""
        import conflict
        import recount
        self.assertEqual(recount.FIX_NODE, "p3.fix")
        got = node_marker.strip(recount.FIX_OUTPUT_FORMAT)
        self.assertEqual(got["properties"].pop("conflicts"), conflict.CONFLICTS_SCHEMA, "食い違いの申し出の欄（受け付けが外して渡す）")
        self.assertEqual(got["properties"].pop("bash_writes"), recount.writes.BASH_WRITES_SCHEMA, "Bash で書いたファイルの申告の欄（受け付けが外して渡す）")
        site = got["properties"]["changes"]["items"]["properties"]["closure"]["properties"]["sites"]["items"]
        self.assertEqual(site["properties"].pop(recount.SITE_PATH), recount.SITE_PATH_SCHEMA,
                         "site が在るファイルのパスの欄（unitrows が問いの当たりに結び、写しに渡す前に外す）")
        self.assertEqual(got, role_schema("p3.fix"))
        mark = node_marker.parse(recount.FIX_OUTPUT_FORMAT["description"])
        self.assertEqual((mark["name"], mark["cont"], mark["flags"]), ("fix", None, frozenset()))
        self.assertIn("rejudge_requested", recount.FIX_OUTPUT_FORMAT["properties"])
        for name in ("fix2_ok", "fix2_count_not_dropped", "fix2_sites_mismatch", "fix2_silent_closure",
                     "fix2_rejudge_requested"):
            with self.subTest(name):
                self.assertEqual(validate_schema(load(name), role_schema("p3.fix")), [], "見本は graph の型を通る")

    def test_script_inputs_constants(self):
        """各 script は読む INPUTS_* を定数 INPUTS に持つ（裁定 TA16。Task 17 が YAML の with: と突き合わせる）"""
        want = {"accept": ("INPUTS_REPLY", "INPUTS_BASE_REV", "INPUTS_TDD_STATE", "INPUTS_ITERATION", "INPUTS_PASS"),
                "fix_prep": ("INPUTS_JUDGMENT_FILE", "INPUTS_OPEN_UNITS", "INPUTS_PLAN_FILE", "INPUTS_POLICY_PATH",
                             "INPUTS_NOTES_FILE", "INPUTS_SUMMARY_FILE", "INPUTS_PASS"),
                "collect": ("INPUTS_ACCEPTED", "INPUTS_CHANGED", "INPUTS_CLEANED", "INPUTS_TDD", "INPUTS_RULED"),
                "reads": ("INPUTS_MUST",)}
        for name, inputs in want.items():
            with self.subTest(name):
                src = (BLK / "scripts" / f"{name}.py").read_text(encoding="utf-8")
                consts = [ast.literal_eval(n.value) for n in ast.parse(src).body if isinstance(n, ast.Assign)
                          and [getattr(t, "id", None) for t in n.targets] == ["INPUTS"]]
                self.assertEqual(consts, [inputs])
                self.assertLessEqual(set(re.findall(r"INPUTS_[A-Z_]+", src)), set(inputs), "定数に無い INPUTS_* を読まない")

    def test_fixtures(self):
        fx = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in (BLK / "fixtures").glob("*.stubs.yaml")}
        # tdd は test_blk_fix_tdd、conflict（食い違いの申し出の筋書き）は test_blk_fix_conflict が見る
        self.assertEqual(set(fx), {"pass.stubs.yaml", "no-change.stubs.yaml", "tdd.stubs.yaml", "conflict.stubs.yaml"})
        fx.pop("conflict.stubs.yaml")
        for name, f in fx.items():
            with self.subTest(name):
                self.assertEqual(f["fix"], load("fix2_ok"))   # 役の output_format は写しの p3.fix の型（〔線A計〕T17）
                self.assertIs(f.get("exec-code"), True)
                # 支度の節は盤面を要るので stub（中身は TestFixPrep）。出口は YAML の output_format の必須の欄
                self.assertLessEqual(set(find_node(block()["nodes"], "fix-prep")["output_format"]["required"]),
                                     set(f["fix-prep"]))
        self.assertEqual(fx["pass.stubs.yaml"]["fixture"]["expect"], "completed")
        self.assertIn("assert-changed", fx["pass.stubs.yaml"])
        # collect は盤面を開く（数え直しの後）。このブロック単体の模擬実行には盤面が無いので stub する（出口の 1 本目の欄を持つ）
        self.assertLessEqual({"ok", "files", "changes_file", "removed", "tdd"}, set(fx["pass.stubs.yaml"]["collect"]))
        nc = fx["no-change.stubs.yaml"]
        self.assertEqual((nc["fixture"]["expect"], nc["fixture"]["fail-node"]), ("failed", "assert-changed"))
        self.assertNotIn("assert-changed", nc, "no-change は assert-changed を実物で回す")


class ScriptCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self._tmp.name)
        self.repo = tmp / "repo"
        self.base = committed_copy(self.repo, SEED)   # 種を写して commit した git（型の写し。gitkit）
        self.artifacts = tmp / "artifacts"
        self.board = self.artifacts / "board"
        self.board.mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()


class TestAssertChanged(ScriptCase):
    def run_it(self, base_rev="", declared=("stats.py",), accepted=None):
        if accepted is None:
            accepted = {"ok": True, "reason": "", "changes": [
                {"unit_key": "u", "files": list(declared), "what": "直した"}]}
        raw = accepted if isinstance(accepted, str) else json.dumps(accepted, ensure_ascii=False)
        return run_script("assert_changed", self.repo, {"INPUTS_BASE_REV": base_rev, "INPUTS_ACCEPTED": raw})

    def assert_refused(self, result, *words):
        code, out, err = result
        self.assertEqual(code, 1)
        self.assertEqual(out, "")
        self.assertEqual(err.count("\n"), 1, "理由は 1 行")
        for w in words:
            self.assertIn(w, err)

    def test_clean_tree_fails(self):
        for rev in ("", self.base):
            with self.subTest(rev=rev):
                self.assert_refused(self.run_it(rev), "変わっていない", "stats.py")

    def test_running_tests_only_fails(self):
        """テストを回しただけ（__pycache__ ができただけ）では通らない"""
        r = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=str(self.repo), capture_output=True,
                           env={"PATH": os.environ["PATH"]}, timeout=120)
        self.assertTrue(list(self.repo.glob("__pycache__/*.pyc")), r.stderr)
        self.assert_refused(self.run_it(), "stats.py")

    def test_modified_file_passes(self):
        (self.repo / "stats.py").write_text("x = 1\n")
        (self.repo / "__pycache__").mkdir()
        (self.repo / "__pycache__" / "stats.cpython-314.pyc").write_bytes(b"x")
        code, out, _ = self.run_it(declared=["./stats.py"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"ok": True, "files": ["stats.py"]}, "申告と変わった物の重なりだけを出す")

    def test_declared_but_unchanged_file_fails(self):
        (self.repo / "stats.py").write_text("x = 1\n")
        self.assert_refused(self.run_it(declared=["stats.py", "test_stats.py"]), "test_stats.py")

    def test_nothing_declared_fails(self):
        (self.repo / "stats.py").write_text("x = 1\n")
        self.assert_refused(self.run_it(declared=[]), "申告")

    def test_untracked_file_passes(self):
        (self.repo / "new_test.py").write_text("x = 1\n")
        code, out, _ = self.run_it(self.base, declared=["new_test.py"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["files"], ["new_test.py"])

    def test_committed_since_base_rev_passes(self):
        (self.repo / "stats.py").write_text("x = 1\n")
        git(self.repo, "commit", "-q", "-am", "fix")
        self.assertEqual(self.run_it("")[0], 1, "空は今の HEAD（commit した後は差分が無い）")
        code, out, _ = self.run_it(self.base)
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out)["files"], ["stats.py"])

    def test_japanese_names_pass(self):
        # 日本語の名前も git の引用（"\346\227\245..."）でなく、そのままの名前で申告と突き合わせる
        (self.repo / "日本.py").write_text("x = 1\n", encoding="utf-8")
        git(self.repo, "add", "日本.py")
        git(self.repo, "commit", "-q", "-m", "日本")
        base = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "日本.py").write_text("x = 2\n", encoding="utf-8")        # 追跡している側（diff --name-only）
        (self.repo / "未追跡.py").write_text("y = 1\n", encoding="utf-8")      # 未追跡の側（ls-files）
        code, out, err = self.run_it(base, declared=["日本.py", "未追跡.py"])
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["files"], sorted(["日本.py", "未追跡.py"]))

    def test_archon_dir_does_not_count(self):
        (self.repo / ".archon").mkdir()
        (self.repo / ".archon" / "x.yaml").write_text("a: 1\n")
        self.assertEqual(self.run_it(declared=[".archon/x.yaml"])[0], 1)

    def test_bad_input(self):
        self.assertEqual(self.run_it("no-such-rev")[0], 2)
        self.assertEqual(run_script("assert_changed", self.repo, {})[0], 2)
        self.assertEqual(run_script("assert_changed", self.repo, {"INPUTS_BASE_REV": ""})[0], 2)
        for bad in ("not json", {"ok": True, "reason": ""}):
            with self.subTest(accepted=bad):
                self.assertEqual(self.run_it(accepted=bad)[0], 2)
        # 輪が諦めた出力（ok: false）は盤面を止める道。盤面の無いブロックだけの模擬実行では止められず 1 行で 1
        self.assert_refused(self.run_it(accepted={"ok": False, "reason": "拒んだ", "changes": []}), "拒ま")


# ---------------------------------------------------------------- 盤面の上の受け付け（線 A Task 12。仕様 3.2）
# 1 本目の試験は偽の盤面（judgment.json と check_fix）の上で受け付けを見ていた。同じ主張（義務の単位を全部覆う・同じ単位を
# 2 行に分けない・判定の前に修正を受けない・出口の 1 本目の欄）を、本物の盤面の done("p3.fix") の上で確かめる。
JUDGE = "judge_ok"
MEAN, CLAMP = (u["key"] for u in load(JUDGE)["units"])
DEFERRED = "stats.py mean: 分母の式の書き方が他の統計の関数と揃っていない"
INVENTED = "stats.py median: 判定に無い作り話の単位"
PREMISES_REPLY = {"constraints": []}
PLAN_REVIEW_OK = {"faces": [], "shrink": [], "faces_none": "案の 2 か所を stats.py で読み、穴も別案も無いと確かめた",
                  "reason": "分母と戻り値を 1 行ずつ直す案で、足す物も狭める物も無い"}
NARROWS = [{"what": "空の列の mean", "why": "空の列の平均は 0 割りの例外のまま（前も例外で、狭まる能力は無いが人に確かめる）"}]
# 種の stats.py の 2 つの直し（mean の分母・clamp の上限の枝）
PACK_COPY_FILE = ".archon/workflows/works/stats_copy.py"   # 自分食いの run の作業ツリーに在る pack の写しの 1 本（dogfood.sh）
FIXED = {"sum(xs) / (len(xs) - 1)": "sum(xs) / len(xs)", "    if x > hi:\n        return lo": "    if x > hi:\n        return hi"}
# 分母は直したが、前の式を行末の注記に残した形（判定役の問い「(len(xs) - 1)」の fixed の文字列は注記の行も数える）
RESIDUE = {"sum(xs) / (len(xs) - 1)": "sum(xs) / len(xs)  # 前は sum(xs) / (len(xs) - 1)（不偏分散の分母と取り違えていた）",
           "    if x > hi:\n        return lo": "    if x > hi:\n        return hi"}


def plan_reply(narrows=()):
    return {"plan": [{"unit_keys": [MEAN, CLAMP], "approach": "mean の分母を len(xs) に、clamp の上限の枝の戻り値を hi に直す",
                      "adds": [], "removes": [], "shrink_first": "足す物は無い。2 か所の式を 1 行ずつ直すだけで足りる",
                      "narrows": list(narrows)}]}


# 修正案の項目の works の欄（盤面の plan-fields.json の行。test_plan_brief の FIELDS と同じ形）
PLAN_FIELDS = [{"route": "tdd", "route_why": "", "tests": [{"id": "test_stats.py::TestStats::test_mean_of_two",
                                                            "behavior": "2 つの値の平均", "path": "stats.mean を直に呼ぶ",
                                                            "red_kind": "assertion", "red_why": "今は len-1 で割る"}],
                "rewrite_tests": [], "refactor": {"declared": False, "why": ""}}]


def extra_row(key):
    """fix2_ok の mean の直しの行を写し、unit_key を key に替えた行。先行例は判定の行を採らず problem・source を書き、覆いの
    問いは mean と同じ how・counts を書く（写しの fix_covers_open_units はこの行も数え直して通す——義務に無い key を見ない）"""
    row = json.loads(json.dumps(load("fix2_ok")["changes"][0]))
    row["unit_key"] = key
    row["precedent"] = {"verdict": "adopt", "reason": "算術平均の定義どおりに割る、標準の実装と同じ形",
                        "problem": "算術平均の分母", "source": "Python 標準ライブラリ statistics.mean"}
    row["coverage"] = {"how": load(JUDGE)["units"][0]["class_query"]["how"], "counts": "defects"}
    return row


def pending_attempt(b, nid):
    inst = next(i for i in b.rd["instances"].values() if i["node"] == nid and i["status"] == "pending")
    return inst.get("attempts", 1)


def launch(board, nid, numbered=False):
    """ブロックの snap の節の代わり: 待っている試行に起こした印を置く（盤面は印の無い返答を受けない）。numbered なら描いた一覧の
    控え（pointer_rows の pointers）も渡す（番号で指した返答を盤面が名前に戻せる）"""
    b = entry.open_board(board)
    b.mark_launched(nid, pending_attempt(b, nid), pointers=b.pointer_rows(nid)["pointers"] if numbered else None)


# 写しの rules が拒否でも書く盤面の隣のファイル: 数える問いの量（count-budget.json。「差し戻しの done は盤面を保存しないので、
# いちばん数えたい出し直しを数えるため」に刻む）と、固定した版で数えた答えの控え（count-cache.json）。graphloops と同じ
COUNT_FILES = ("count-budget.json", "count-cache.json")


def board_shas(d) -> dict:
    """盤面の置き場の全部のファイルの sha256（拒んだ受け付けが何も書かないことを見る。数え直しの量と控えは除く）"""
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(pathlib.Path(d).rglob("*"))
            if p.is_file() and str(p.relative_to(d)) not in COUNT_FILES}


class BoardCase(unittest.TestCase):
    """本物の darkfactory の表で盤面を作る（linekit の種・使い捨ての家 linekit.work_home() の下。$ARTIFACTS_DIR/board の形）"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(setattr, engine_util, "GIT_CWD", engine_util.GIT_CWD)
        env = mock.patch.dict(os.environ, {"WORKS_ADAPTER_HOME": str(self.tmp / "adapter-home")})
        env.start()
        self.addCleanup(env.stop)
        self.art = self.tmp / "art"
        self.board = self.art / "board"

    def take(self, nid, reply):
        launch(self.board, nid)
        got = entry.take(self.board, nid, reply, self.repo)
        self.assertTrue(got["ok"], got)
        return got

    def judged(self, judge=None):
        """判定を受けた盤面（start → 並行 PR の任せ先・前提の役 → 判定。judge が無ければ judge_ok）"""
        self.repo = linekit.seed_repo(self.tmp / "repo", declared=True)
        req = self.tmp / "request.json"
        req.write_text((SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        entry.start(self.board, self.repo, {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "final_gate": "",
                                            "adapter": "", "policy_md": ""}, run_id="run-12")
        pr = {k: v for k, v in linekit.reply("pr_no_conflicts").items() if k != "excluded"}
        self.take("p0.parallel_pr", pr)
        self.take("p0.premises", PREMISES_REPLY)
        linekit.pre_judge(self.board, self.repo)   # 目的の文（判定の前に盤面が待つ）
        self.take("p2.diagnose", judge or load(JUDGE))

    def fix_ready(self, narrows=(), answer=None, judge=None, numbered=False, launched=True):
        """p3.fix が待ち、起こした印の在る盤面（修正案 → 事前審査。narrows なら p2.human_gate が聞き、answer で答える）。
        launched が偽なら印を置かない（fix-prep が置く）"""
        self.judged(judge)
        self.take("p2.fix_plan", plan_reply(narrows))
        got = self.take("p2.plan_review", PLAN_REVIEW_OK)
        if answer is not None:
            self.assertTrue(got["asking"], got)
            entry.open_board(self.board).answer(*answer)
        self.assertIn("p3.fix", entry.open_board(self.board).settle()["ready"])
        if launched:
            launch(self.board, "p3.fix", numbered)
        import leftovers
        leftovers.record_ignored(self.board, self.repo)   # 線の節 ignored-before（修正役の前の控え。.archon/ の姿も）

    def edit_tree(self, subs):
        path = self.repo / "stats.py"
        text = path.read_text(encoding="utf-8")
        for old, new in subs.items():
            self.assertIn(old, text)
            text = text.replace(old, new)
        path.write_text(text, encoding="utf-8")

    def accept(self, reply):
        import recount
        return recount.accept_fix(reply, self.board, "", self.repo)

    def assert_rejected(self, reply, *words):
        before = board_shas(self.board)
        budget = self.board / "count-budget.json"
        calls = json.loads(budget.read_text(encoding="utf-8"))["calls"] if budget.is_file() else 0
        got = self.accept(reply)
        self.assertFalse(got["ok"], got)
        if "fix_closure" not in got["reason"] and "直していない" not in got["reason"]:   # 数え直しまで進んだ拒否
            self.assertGreater(json.loads(budget.read_text(encoding="utf-8"))["calls"], calls, "数えた量は拒否でも刻む")
        self.assertEqual(got["changes"], [], "拒んだときの changes は空（1 本目と同じ）")
        for w in words:
            self.assertIn(w, got["reason"])
        self.assertEqual(board_shas(self.board), before, "拒んだ受け付けは盤面を書かない")
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")
        return got


class TestRecount(BoardCase):
    def test_recount_accepts_real_fix(self):
        """種の stats.py を直した作業ツリーと fix2_ok → 通る。盤面が数え直した件数（loop.coverage_after）に 2 単位、次は差分の審査"""
        self.fix_ready()
        self.edit_tree(FIXED)
        got = self.accept(load("fix2_ok"))
        self.assertTrue(got["ok"], got)
        self.assertIn("p3.delta_review", got["ready"])
        self.assertEqual(got["changes"], [{k: c[k] for k in ("unit_key", "files", "what")} for c in load("fix2_ok")["changes"]],
                         "1 本目の出口の changes（unit_key・files・what）を写す")
        b = entry.open_board(self.board)
        cov = b.loop_state["coverage_after"]
        self.assertEqual(cov["round"], b.round)
        self.assertEqual({i["unit_key"]: (i["total"], i["after"]) for i in cov["items"]}, {MEAN: (1, 0), CLAMP: (2, 1)})
        self.assertEqual(b.node_state("p3.fix"), "done")
        self.assertEqual(got["out_file"], b.state["outputs"]["p3.fix"]["file"])

    def test_recount_rejects_count_not_dropped(self):
        """直していない作業ツリー・前の式を注記に残した作業ツリー → 欠陥の形の数が減っていない。文に単位の key と数"""
        self.fix_ready()
        self.assert_rejected(load("fix2_ok"), MEAN, "母数 1", "修正の後も 1 件")
        self.edit_tree(RESIDUE)   # 拒んだ受け付けは盤面を書かないので、同じ試行に出し直せる
        self.assert_rejected(load("fix2_count_not_dropped"), MEAN, "母数 1", "修正の後も 1 件")

    def test_recount_rejects_sites_mismatch(self):
        """closure.sites の数と母数が合わない: 母数 2 に site 1 件で残した理由が無い・母数を超える site"""
        self.fix_ready()
        self.edit_tree(FIXED)
        self.assert_rejected(load("fix2_sites_mismatch"), CLAMP, "母数 2", "1 件", "remaining")
        over = load("fix2_ok")
        over["changes"][0]["closure"]["sites"] *= 3
        self.assert_rejected(over, MEAN, "3 件", "母数は 1")
        left = load("fix2_sites_mismatch")
        left["changes"][1]["coverage"] = {"remaining": "x < lo の枝は正しく lo を返すので、この周では直さない"}
        self.assertTrue(self.accept(left)["ok"], "残した理由を書けば通す（黙って残すのだけを拒む）")

    def test_recount_rejects_silent_closure(self):
        """changes が在るのに fix_closure が not_applicable → 写しの文で拒む"""
        self.fix_ready()
        self.edit_tree(FIXED)
        self.assert_rejected(load("fix2_silent_closure"), "修正が 2 件在るのに fix_closure が not_applicable")

    def test_recount_rejects_uncovered_unit(self):
        """直す義務の単位を書き落とした返答 → 拒む（1 本目の test_rejects_uncovered_unit の主張）"""
        self.fix_ready()
        self.edit_tree(FIXED)
        reply = load("fix2_ok")
        del reply["changes"][1]
        self.assert_rejected(reply, "直していない", CLAMP)

    def test_human_notes_recorded_before_fix(self):
        """関所で continue "x" を答えた盤面 → 人の答えが record.process.human_items に在り（p3.fix の reads。役に届く口）、
        その記録の在る盤面で受け付けが通り、記録は変わらない（写しの受け付けの規則は human_items を読まない——読んだかは見ない）"""
        note = 'x の範囲だけ通す: "引用" と $(date) と改行\n'
        self.fix_ready(narrows=NARROWS, answer=("continue", note))
        items = entry.open_board(self.board).record["process"]["human_items"]
        self.assertEqual([(h["answer"], h["note"], h["node"]) for h in items], [("continue", note, "p2.human_gate")])
        self.assertIn("record.process.human_items", json.loads((CORE / "graphloops" / "graphs" / "review-loop.json")
                                                               .read_text(encoding="utf-8"))["nodes"]["p3.fix"]["reads"])
        self.edit_tree(FIXED)
        got = self.accept(load("fix2_ok"))
        self.assertTrue(got["ok"], got)
        self.assertEqual(entry.open_board(self.board).record["process"]["human_items"], items)

    def wrote_refs_state(self, hook):
        """修正を受けた盤面で、test_stats.py を指す wrote_refs の読了の状態（hook(target) が読んだ記録を置く）"""
        self.fix_ready()
        self.edit_tree(FIXED)
        target = self.repo / "test_stats.py"
        hook(target)
        reply = load("fix2_ok")
        reply["wrote_refs"] = [{"kind": "text", "cite": "def test_clamp_above_range", "target": "test_stats.py",
                                "where": "stats.py"}]
        got = self.accept(reply)
        self.assertTrue(got["ok"], got)
        reads = entry.open_board(self.board).loop_state["wrote_refs_reads"]
        return [(r["target"], r["state"]) for r in reads["items"]]

    def test_wrote_refs_reads_from_adapter_home(self):
        """包みのフック（record-read.py を実物で起こす）が包みの置き場 adapter.reads_dir(run の worktree) に書いた記録を、
        数え直しの wrote_refs_reads が読む（entry が写しの RL の hook_evidence の置き場を差し替える。Task 6 の直し 1）"""
        def hook(target):
            sink = adapter.reads_dir(self.repo)
            sink.mkdir(parents=True, exist_ok=True)
            payload = {"tool_name": "Read", "tool_input": {"file_path": str(target)}, "cwd": str(self.repo),
                       "session_id": "s-12", "tool_use_id": "toolu_12"}
            subprocess.run([sys.executable, str(CORE / "record-read.py"), str(sink)], input=json.dumps(payload),
                           text=True, encoding="utf-8", check=True, env=hermetic.child_env(**{"PYTHONDONTWRITEBYTECODE": "1"}))
        self.assertEqual(self.wrote_refs_state(hook), [("test_stats.py", "read")])

    def test_wrote_refs_reads_ignores_board_log(self):
        """盤面の置き場にだけ reads.jsonl（実物の行の形）が在っても数えない（誰も書かない場所。包みの置き場に記録が無ければ none）"""
        def hook(target):
            raw = target.read_bytes()
            row = {"ts": "2026-09-27T10:00:00", "session_id": "s-12", "agent_id": None, "path": os.path.realpath(target),
                   "file_sha": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "partial": False, "partial_why": None,
                   "tool_use_id": "toolu_12"}
            (self.board / "reads.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        self.assertEqual(self.wrote_refs_state(hook), [("test_stats.py", "none")])


class TestFixPrep(BoardCase):
    """支度の節 fix-prep（fixrules.prep）を子で起こす: 2 つの形を並べて書き（prompt_file は full の写し）、起こした印を置く。
    出し直しでは前の回の受け付けが書いた理由のファイルを名指し、delta は変わった物と決まりの sha256 の 1 行だけ。
    読んだ証拠の節は組んだ指示書を読むべきパスに足す"""

    def values(self):
        b = entry.open_board(self.board)
        return {"judgment_file": str(self.board / b.state["outputs"]["p2.diagnose"]["file"]),
                "open_units": json.dumps([MEAN, CLAMP], ensure_ascii=False), "plan_file": "", "policy_path": "",
                "notes_file": "", "summary_file": ""}

    def prep(self, **drop):
        env = {"ARTIFACTS_DIR": str(self.art), "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"], "INPUTS_PASS": "first",
               **{f"INPUTS_{k.upper()}": v for k, v in self.values().items()}}
        return run_script("fix_prep", self.repo, {k: v for k, v in env.items() if k not in drop})

    def reject_by_script(self):
        # 申告と数え直しの食い違いは拒まず記録する（49 件目）ので、今も拒まれる同じ unit_key の 2 行で拒ませる
        self.edit_tree(FIXED)
        reply = load("fix2_ok")
        reply["changes"].append(reply["changes"][0])
        full = {"INPUTS_REPLY": json.dumps(reply, ensure_ascii=False), "INPUTS_BASE_REV": "", "INPUTS_TDD_STATE": "",
                "INPUTS_ITERATION": "1", "ARTIFACTS_DIR": str(self.art), "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"]}
        code, out, err = run_script("accept", self.repo, full)
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertFalse(r["ok"], r)
        self.assertIn("同じ unit_key", r["reason"])
        return r["reason_file"]

    def test_first_prep_writes_full_and_launches(self):
        import fixrules
        self.fix_ready(launched=False)
        code, out, err = self.prep()
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        b = entry.open_board(self.board)
        self.assertEqual(r["prompt_file"], str(b.work("prompt-p3.fix.md")))
        self.assertEqual((r["node"], r["attempt"], r["already"]), ("p3.fix", 1, False))
        self.assertTrue(b.rd["instances"]["p3.fix"].get("launched_at"), "起こした印を置く（盤面は印の無い返答を受けない）")
        prompt = pathlib.Path(r["prompt_file"])
        full = fixrules.beside(prompt, fixrules.FULL).read_text(encoding="utf-8")
        self.assertEqual(prompt.read_text(encoding="utf-8"), full, "既定は full")
        self.assertEqual(fixrules.beside(prompt, fixrules.DELTA).read_text(encoding="utf-8"), full, "1 回目の delta は full")
        self.assertIn(fixrules.shared().split("\n## テストで")[0], full, "正本の核（直し方）が在る")
        self.assertIn(self.values()["judgment_file"], full)
        side = json.loads(pathlib.Path(r["variants_file"]).read_text(encoding="utf-8"))
        why = {s["id"]: s["why"] for s in side["sections"]}
        self.assertIn("stats.py", why["evidence-code"], "判定の単位のパスから種類を選んだ（機械の事実）")
        self.edit_tree(FIXED)
        self.assertTrue(self.accept(load("fix2_ok"))["ok"], "fix-prep の印の後に受け付けが通る")

    def test_retry_names_the_reject_file_and_writes_delta(self):
        import fixrules
        self.fix_ready(launched=False)
        code, out, err = self.prep()
        self.assertEqual(code, 0, err)
        first = json.loads(pathlib.Path(json.loads(out)["variants_file"]).read_text(encoding="utf-8"))
        reason_file = self.reject_by_script()
        code, out, err = self.prep()
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertIs(r["already"], True, "同じ試行の出し直し")
        prompt = pathlib.Path(r["prompt_file"])
        line = rolekit_reject_line(reason_file)
        full = prompt.read_text(encoding="utf-8")
        delta = fixrules.beside(prompt, fixrules.DELTA).read_text(encoding="utf-8")
        self.assertEqual(full.split("\n")[1], line, "理由の本文は貼らず、パスを見出しの次の 1 行で名指す（R44）")
        self.assertEqual(delta.split("\n")[1], line)
        self.assertNotIn(pathlib.Path(reason_file).read_text(encoding="utf-8")[:40], full)
        self.assertIn(first["rules_sha"], delta)
        self.assertNotIn(fixrules.sections(fixrules.SHARED)["core-fix"], delta)
        self.assertIn(fixrules.sections(fixrules.SHARED)["core-fix"], full)
        side = json.loads(pathlib.Path(r["variants_file"]).read_text(encoding="utf-8"))
        self.assertEqual((side["iteration"], side["delta_is_full"]), (2, False))

    def test_same_inputs_same_bytes_on_the_board(self):
        """同じ盤面・同じ値で組み直すと、full はバイト単位で同じ"""
        import fixrules
        self.fix_ready(launched=False)
        code, out, err = self.prep()
        self.assertEqual(code, 0, err)
        prompt = pathlib.Path(json.loads(out)["prompt_file"])
        one = prompt.read_bytes()
        fixrules.beside(prompt, fixrules.DELIVERED).unlink()   # この輪の控えを消せば 1 回目と同じ入力
        code, out, err = self.prep()
        self.assertEqual(code, 0, err)
        self.assertEqual(prompt.read_bytes(), one)

    def test_reads_cover_the_composed_prompt(self):
        """読んだ証拠（fix-reads）は、判定のファイルに加えて fix-prep が組んだ指示書を読むべきパスに持つ"""
        self.fix_ready(launched=False)
        code, out, err = self.prep()
        self.assertEqual(code, 0, err)
        prompt = json.loads(out)["prompt_file"]
        judgment = self.values()["judgment_file"]
        code, out, err = run_script("reads", self.repo, {"ARTIFACTS_DIR": str(self.art), "WORKFLOW_ID": "run-12",
                                                         "INPUTS_MUST": json.dumps([judgment]),
                                                         "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"]})
        self.assertEqual(code, 0, err)
        rows = json.loads(pathlib.Path(json.loads(out)["reads_file"]).read_text(encoding="utf-8"))["rows"]
        self.assertEqual([r["path"] for r in rows], [judgment, prompt])

    def test_g3_prompt_carries_the_implementer_seat(self):
        """既定の形 g3 の盤面: 修正役の指示書（full）に借りたスキルの座（216 の implementer の型を埋めた物）が返答の欄の前に載る"""
        import fixshape
        import seat
        self.fix_ready(launched=False)
        self.assertEqual(fixshape.shape_at(self.board), "g3")
        code, out, err = self.prep()
        self.assertEqual(code, 0, err)
        full = pathlib.Path(json.loads(out)["prompt_file"]).read_text(encoding="utf-8")
        self.assertIn(seat.HEAD, full)
        self.assertIn(seat.NO_REPORT_FILE, full)
        import rolekit
        own = full[full.index(seat.HEAD):full.index(rolekit.skill_overlay().splitlines()[0])]   # 座の本文（読み替えの前まで。F8）
        self.assertNotRegex(own, r"\[(BRIEF_FILE|REPORT_FILE|directory|task name)\]")
        side = json.loads(pathlib.Path(json.loads(out)["variants_file"]).read_text(encoding="utf-8"))
        ids = [s["id"] for s in side["sections"]]
        self.assertEqual(ids[ids.index("fix-reply") - 1], "seat")

    def test_g3_broken_pin_stops_prep_with_2(self):
        """g3 の盤面で 216 の写しが固定と 1 バイト違えば、支度は af の文へ黙って逃げず、名指して 2 で落ちる。指示書も起こした印も
        置かない（Review Focus 5・Preflight F9）。写しを替えるため、子でなく同じプロセスで script の入口を回す"""
        import contextlib
        import importlib.util
        import io
        import shutil
        import rolekit
        import spseam
        self.fix_ready(launched=False)
        borrow = self.tmp / "borrow"
        shutil.copytree(spseam.BORROW_DIR, borrow)
        item = json.loads((borrow / "borrow.json").read_text(encoding="utf-8"))["superpowers"]
        rel = "skills/subagent-driven-development/implementer-prompt.md"
        p = spseam.vendored_dir(item, borrow) / rel
        p.write_bytes(p.read_bytes().replace(b"Report Format", b"Report Formax", 1))
        spec = importlib.util.spec_from_file_location("fix_prep_script", BLK / "scripts" / "fix_prep.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        env = {"ARTIFACTS_DIR": str(self.art), "INPUTS_PASS": "first",
               **{f"INPUTS_{k.upper()}": v for k, v in self.values().items()}}
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.repo)
        err = io.StringIO()
        with mock.patch.dict(os.environ, env), mock.patch.object(spseam, "BORROW_DIR", borrow), \
                mock.patch.object(mod.fixrules, "lib_section", return_value="") as docs, contextlib.redirect_stderr(err):
            code = rolekit.script_main(mod.run, mod.INPUTS)
        self.assertEqual(code, 2, err.getvalue())
        self.assertIn(rel, err.getvalue())
        docs.assert_not_called()   # 照合は重い仕事（Context7 の引き）より前
        b = entry.open_board(self.board)
        self.assertFalse(b.work(mod.fixrules.SEAT_BRIEFS).exists(), "照合は作業ファイルを書くより前")
        self.assertFalse(b.rd["instances"]["p3.fix"].get("launched_at"), "起こした印を置かない")
        self.assertFalse(b.work("prompt-p3.fix.md").exists(), "指示書を書かない")

    def test_not_waiting_is_wiring(self):
        """盤面が p3.fix を待っていない（判定の直後）→ 2（標準出力は空）"""
        self.judged()
        code, out, err = self.prep()
        self.assertEqual((code, out), (2, ""))
        self.assertIn("p3.fix", err)

    def test_missing_value_is_wiring(self):
        self.fix_ready(launched=False)
        code, out, err = self.prep(INPUTS_SUMMARY_FILE=None)
        self.assertEqual((code, out), (2, ""))
        self.assertIn("INPUTS_SUMMARY_FILE", err)

    def test_prep_puts_briefs_of_owed_units_on_top(self):
        """修正案の欄の控えが在る盤面: full と delta の頭（直す役の決まりより前）で、直す義務の単位の brief を名指す"""
        self.fix_ready(launched=False)
        planmarks.save(self.board, entry.open_board(self.board).round, PLAN_FIELDS)
        code, out, err = self.prep()
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        for path in (r["prompt_file"], json.loads(pathlib.Path(r["variants_file"]).read_text(encoding="utf-8"))["delta"]):
            text = pathlib.Path(path).read_text(encoding="utf-8")
            self.assertLess(text.index(planbrief.HEAD), text.index("# 修正（書く役の仕事）"))
            self.assertIn(str(entry.open_board(self.board).work("brief-1.md")), text)

    def test_prep_without_plan_fields_has_no_brief_head(self):
        """修正案の欄の控えが無い盤面（修正案の無い run）: 指示書は今どおりで brief の節を置かない"""
        self.fix_ready(launched=False)
        code, out, err = self.prep()
        self.assertEqual(code, 0, err)
        self.assertNotIn(planbrief.HEAD, pathlib.Path(json.loads(out)["prompt_file"]).read_text(encoding="utf-8"))

    def test_reads_cover_briefs(self):
        """読んだ証拠の節が読むべきパスに、今の周の brief のファイルを持つ"""
        import fixrules
        self.fix_ready(launched=False)
        planmarks.save(self.board, entry.open_board(self.board).round, PLAN_FIELDS)
        code, out, err = self.prep()
        self.assertEqual(code, 0, err)
        self.assertIn(str(entry.open_board(self.board).work("brief-1.md")), fixrules.reads_more(self.board))

    def test_broken_ledger_halts_with_reason(self):
        """brief の控えが壊れている（cut の外で置いた・切った印の無い控え）: 盤面を止め（by works:fix）、控えを名指す 1 行で 2。
        traceback にせず、brief の無い指示書として役を起こさない"""
        self.fix_ready(launched=False)
        b = entry.open_board(self.board)
        planmarks.save(self.board, b.round, PLAN_FIELDS)
        ledger = self.board / f"r{b.round}" / planbrief.LEDGER
        ledger.parent.mkdir(parents=True, exist_ok=True)
        ledger.write_text(json.dumps({"briefs": []}) + "\n", encoding="utf-8")
        code, out, err = self.prep()
        self.assertEqual((code, out), (2, ""))
        self.assertIn(planbrief.LEDGER, err)
        self.assertNotIn("Traceback", err)
        after = entry.open_board(self.board, allow_halted=True)
        self.assertEqual(after.state["stop"]["by"], "works:fix")
        self.assertIn(planbrief.LEDGER, after.state["stop"]["reason"])
        self.assertFalse((after.rd["instances"].get("p3.fix") or {}).get("launched_at"), "役を起こす印を置かない")

    def test_reads_with_broken_ledger_halts_with_reason(self):
        """修正役が brief の控えを書き換えた後の読んだ証拠の節: traceback にせず、盤面を止めて控えを名指す理由の BoardGap"""
        import fixrules
        from board import BoardGap
        self.fix_ready(launched=False)
        planmarks.save(self.board, entry.open_board(self.board).round, PLAN_FIELDS)
        code, out, err = self.prep()
        self.assertEqual(code, 0, err)
        ledger = self.board / f"r{entry.open_board(self.board).round}" / planbrief.LEDGER
        ledger.write_text(ledger.read_text(encoding="utf-8") + " ", encoding="utf-8")   # 凍結の後にバイトを変えた
        with self.assertRaisesRegex(BoardGap, planbrief.LEDGER):
            fixrules.reads_more(self.board)
        self.assertEqual(entry.open_board(self.board, allow_halted=True).state["stop"]["by"], "works:fix")


def rolekit_reject_line(path):
    import rolekit
    return rolekit.REJECT_LINE.format(path=path)


class TestAccept(BoardCase):
    """受け付けのスクリプト（blk-fix の節 fix-accept）を子で起こす。script_io.main と同じ環境変数の約束"""

    def run_it(self, reply, **env):
        full = {"INPUTS_REPLY": reply if isinstance(reply, str) else json.dumps(reply, ensure_ascii=False),
                "INPUTS_BASE_REV": "", "INPUTS_ITERATION": "1", "ARTIFACTS_DIR": str(self.art),
                "WORKS_ADAPTER_HOME": os.environ["WORKS_ADAPTER_HOME"], **env}
        return run_script("accept", self.repo, {k: v for k, v in full.items() if v is not None})

    def test_accepts_and_carries_changes(self):
        self.fix_ready()
        self.edit_tree(FIXED)
        code, out, err = self.run_it(load("fix2_ok"))
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertEqual((r["ok"], r["reason"], r["reason_file"]), (True, "", ""))
        self.assertEqual(r["changes"], [{k: c[k] for k in ("unit_key", "files", "what")} for c in load("fix2_ok")["changes"]])
        self.assertIn("p3.delta_review", r["ready"])

    def test_rejects_uncovered_unit(self):
        self.fix_ready()
        self.edit_tree(FIXED)
        reply = load("fix2_ok")
        del reply["changes"][0]
        code, out, err = self.run_it(reply)
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertFalse(r["ok"])
        self.assertEqual(r["changes"], [])
        self.assertIn(MEAN, pathlib.Path(r["reason_file"]).read_text(encoding="utf-8"))

    def test_rejects_duplicate_unit_key(self):
        """同じ unit_key を 2 行に分けた返答 → 拒む（1 本目の決まり。写しの規則は重なりを拒まないので works の受け付けが見る）"""
        self.fix_ready()
        self.edit_tree(FIXED)
        reply = load("fix2_ok")
        reply["changes"].append(reply["changes"][0])
        self.assert_script_rejected(reply, "同じ unit_key", MEAN)

    def assert_script_rejected(self, reply, *words):
        """子で起こした受け付けが役に返す（0・ok False・changes 空・理由の本文は reason_file）。盤面は書かない・p3.fix は待ちのまま"""
        before = board_shas(self.board)
        code, out, err = self.run_it(reply)
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertFalse(r["ok"], r)
        self.assertEqual(r["changes"], [])
        for w in words:
            self.assertIn(w, r["reason"])
        reason_file = pathlib.Path(r["reason_file"])
        self.assertEqual(reason_file.read_text(encoding="utf-8"), r["reason"])
        after = board_shas(self.board)
        self.assertIsNotNone(after.pop(str(reason_file.relative_to(self.board)), None),
                             "理由の本文は盤面の置き場の予約の名前（reject-<関数>-<連番>.txt）")
        self.assertEqual(after, before, "拒んだ受け付けは盤面を書かない（理由の本文の他）")
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")
        return r

    def test_rejects_deferred_unit_key(self):
        """判定が defer にした単位（開いていない単位）の key の行を足した返答 → 拒む（1 本目の fix_plan_covers_units の
        unknown = got - opened。写しの fix_covers_open_units は義務に無い key を拒まないので works の受け付けが見る）"""
        judge = load(JUDGE)
        later = {**judge["units"][0], "key": DEFERRED, "label": "suggest", "disposition": "defer",
                 "reason": "事実: mean の分母の式は 1 行で書けるが、他の統計の関数と書き方を揃える話は今の周の範囲の外。反証: "
                           "揃えないと読み違える箇所を当たったが、stats.py の中で同じ式は mean の 1 か所だけ"}
        judge["units"].append(later)
        self.fix_ready(judge=judge)
        self.edit_tree(FIXED)
        units = {u["key"]: (u["label"], u["disposition"]) for u in entry.open_board(self.board).record["units"]}
        self.assertEqual(units[DEFERRED], ("suggest", "defer"), "盤面の記録に defer の単位が在る（開いていない）")
        reply = load("fix2_ok")
        reply["changes"].append(extra_row(DEFERRED))
        self.assert_script_rejected(reply, DEFERRED, "今の周に直す単位に無い")

    def test_rejects_invented_unit_key(self):
        """判定に無い作り話の key の行を足した返答 → 拒む（同じく 1 本目の unknown）"""
        self.fix_ready()
        self.edit_tree(FIXED)
        reply = load("fix2_ok")
        reply["changes"].append(extra_row(INVENTED))
        self.assert_script_rejected(reply, INVENTED, "今の周に直す単位に無い")

    def test_numbered_unit_keys_resolved_before_works_checks(self):
        """番号で指した unit_key（graph の pointers）は盤面の控えで名前に戻してから works の 2 つの検査に当てる:
        番号だけの返答は通り、同じ単位を番号と名前で 2 行に書いた返答は重なりとして拒む"""
        self.fix_ready(numbered=True)
        self.edit_tree(FIXED)
        dup = load("fix2_ok")
        dup["changes"].append({**dup["changes"][0], "unit_key": 1})
        self.assert_script_rejected(dup, "同じ unit_key", MEAN)
        numbered = load("fix2_ok")
        for no, c in enumerate(numbered["changes"], 1):
            c["unit_key"] = no
        code, out, err = self.run_it(numbered)
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertTrue(r["ok"], r)
        self.assertEqual([c["unit_key"] for c in r["changes"]], [MEAN, CLAMP], "出口の changes は名前")

    def fix_ready_with_pack_copy(self):
        """p3.fix が待つ盤面と、修正役の前から在る pack の写し .archon/workflows/works/**（自分食いの形。ここでは追跡しない写しで、
        控え ignored-before を取り直す——線では ignored-before が修正役の前に 1 回だけ走る）"""
        import leftovers
        self.fix_ready()
        p = self.repo / PACK_COPY_FILE
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("def mean(xs):\n    return sum(xs) / (len(xs) - 1)\n", encoding="utf-8")
        leftovers.record_ignored(self.board, self.repo)
        self.edit_tree(FIXED)
        return p

    def test_rejects_declared_pack_copy(self):
        """修正役が .archon/ の下（動いている線の pack の写し）を changes[].files に申告した → 役に返す（盤面は書かない）。
        run 26 は写しと元の両方を同じに直して申告し、assert-changed が数えない .archon/ を『変わっていない』として 1 で落ちた"""
        self.fix_ready_with_pack_copy()
        reply = load("fix2_ok")
        reply["changes"][0]["files"].append(PACK_COPY_FILE)
        r = self.assert_script_rejected(reply, ".archon/", PACK_COPY_FILE)
        self.assertIn("works/", r["reason"])

    def test_rejects_changed_pack_copy(self):
        """申告しなくても、修正役の前の控え（ignored-before）から .archon/ の下の中身が変わっていれば役に返す（足した物も）"""
        copy = self.fix_ready_with_pack_copy()
        copy.write_text("def mean(xs):\n    return sum(xs) / len(xs)\n", encoding="utf-8")
        (copy.parent / "added.txt").write_text("x\n", encoding="utf-8")
        r = self.assert_script_rejected(load("fix2_ok"), ".archon/", PACK_COPY_FILE, ".archon/workflows/works/added.txt")
        self.assertIn("戻", r["reason"])

    def test_untouched_pack_copy_passes(self):
        """前から在る .archon/ の写しに触れない修正は通る"""
        self.fix_ready_with_pack_copy()
        code, out, err = self.run_it(load("fix2_ok"))
        self.assertEqual(code, 0, err)
        self.assertTrue(json.loads(out)["ok"], out)

    def test_done_when_accepted_or_third_reject(self):
        """輪は done で抜ける（R50。max_iterations に当てて run を落とさない）: 通れば done、拒否は輪の 3 回目（fix-prep の
        iteration）で done（読めない返答の拒否も同じ）。iteration が数でなければ回す側の誤り（2）"""
        self.fix_ready()
        bad = load("fix2_ok")
        del bad["changes"][0]
        for it, reply, done in (("1", bad, False), ("2", bad, False), ("3", bad, True), ("3", "not json", True),
                                ("4", bad, True)):
            with self.subTest(iteration=it, reply=str(reply)[:20]):
                code, out, err = self.run_it(reply, INPUTS_ITERATION=it)
                self.assertEqual(code, 0, err)
                r = json.loads(out)
                self.assertEqual((r["ok"], r["done"]), (False, done))
        code, out, err = self.run_it(bad, INPUTS_ITERATION="x")
        self.assertEqual((code, out), (2, ""))
        self.edit_tree(FIXED)
        code, out, err = self.run_it(load("fix2_ok"))
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertEqual((r["ok"], r["done"]), (True, True))

    def test_v1_reply_rejected_by_graph_schema(self):
        """1 本目の形の返答（changes の unit_key・files・what だけ）は graph の型に合わない → 役に返す（ok False・0）"""
        self.fix_ready()
        code, out, err = self.run_it(load("fix_ok"))
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertFalse(r["ok"])
        self.assertIn("型", r["reason"])

    def test_before_judgment_is_runner_error(self):
        """判定の前（p3.fix が待っていない盤面）に修正を受けない。回す側の誤りなので役に返さず 2・盤面は前のまま"""
        self.repo = linekit.seed_repo(self.tmp / "repo", declared=True)
        req = self.tmp / "request.json"
        req.write_text((SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        entry.start(self.board, self.repo, {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "final_gate": "",
                                            "adapter": "", "policy_md": ""}, run_id="run-12")
        before = board_shas(self.board)
        dup, invented = load("fix2_ok"), load("fix2_ok")
        dup["changes"].append(dup["changes"][0])
        invented["changes"][0]["unit_key"] = INVENTED
        for name, reply in (("fix2_ok", load("fix2_ok")), ("重なり", dup), ("作り話の key", invented)):
            with self.subTest(name):   # works だけの検査も、盤面が p3.fix を待っていなければ役に返さない（回す側の誤り）
                code, out, err = self.run_it(reply)
                self.assertEqual((code, out), (2, ""))
                self.assertEqual(len(err.strip().splitlines()), 1, err)
                self.assertIn("p3.fix", err)
                self.assertEqual(board_shas(self.board), before)

    def test_missing_env(self):
        self.repo = linekit.seed_repo(self.tmp / "repo")
        for name in ("INPUTS_REPLY", "INPUTS_BASE_REV", "ARTIFACTS_DIR"):
            with self.subTest(name):
                code, out, err = self.run_it(load("fix2_ok"), **{name: None})
                self.assertEqual((code, out), (2, ""))
                self.assertIn(name, err)


class TestCollect(BoardCase):
    """集める節（blk-fix の節 collect）: 1 本目の出口の欄を全部残し、fix_file・not_done・coverage・reads_file を足す"""

    def run_it(self, accepted, changed, cleaned=None):
        if cleaned is None:
            cleaned = {"ok": True, "count": 0, "file": "/b/fix-removed.json"}
        env = {"INPUTS_ACCEPTED": accepted if isinstance(accepted, str) else json.dumps(accepted, ensure_ascii=False),
               "INPUTS_CHANGED": json.dumps(changed), "INPUTS_CLEANED": json.dumps(cleaned),
               "INPUTS_TDD": json.dumps(NO_SUITE_START, ensure_ascii=False), "ARTIFACTS_DIR": str(self.art)}
        return run_script("collect", self.repo, env)

    def accepted(self, reply="fix2_ok"):
        self.fix_ready()
        self.edit_tree(FIXED)
        got = self.accept(load(reply))
        self.assertTrue(got["ok"], got)
        return got

    def test_exit_keeps_v1_fields(self):
        acc = self.accepted()
        code, out, err = self.run_it(acc, {"ok": True, "files": ["stats.py"]},
                                     {"ok": True, "count": 1, "file": "/b/fix-removed.json"})
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertLessEqual({"ok", "files", "changes_file", "removed"}, set(r), "1 本目の欄を全部残す")
        self.assertEqual(set(r), {"ok", "files", "changes_file", "removed", "fix_file", "not_done", "coverage", "reads_file", "tdd"})
        # 実行器の無い run（tdd-start が go: false）: 1 本目の欄は今と同じで、tdd は ran: false・単位は空
        self.assertEqual(r["tdd"], {"ran": False, "suite": "", "reason": NO_SUITE_START["reason"], "units": []})
        b = entry.open_board(self.board)
        self.assertEqual((r["ok"], r["files"], r["removed"]), (True, ["stats.py"], {"count": 1, "file": "/b/fix-removed.json"}),
                         "clean の件数とファイルをそのまま通す（全件は出口に持たない）")
        self.assertEqual(r["changes_file"], str(b.work("changes.json")))
        self.assertEqual(json.loads(pathlib.Path(r["changes_file"]).read_text(encoding="utf-8")), {"changes": acc["changes"]},
                         "changes.json は 1 本目の形（{changes: [{unit_key, files, what}]}）")
        self.assertEqual(r["fix_file"], str(self.board / b.state["outputs"]["p3.fix"]["file"]))
        self.assertTrue(pathlib.Path(r["fix_file"]).is_file())
        self.assertEqual(r["not_done"], 0)
        self.assertEqual(r["coverage"], {MEAN: {"before": 1, "after": 0}, CLAMP: {"before": 2, "after": 1}})
        self.assertEqual(r["reads_file"], "", "読んだ証拠の節（fix-reads）が走っていなければ空")
        reads = b.work("reads-fix.json")
        reads.write_text("{}", encoding="utf-8")
        r = json.loads(self.run_it(acc, {"ok": True, "files": ["stats.py"]})[1])
        self.assertEqual(r["reads_file"], str(reads))

    def test_not_done_counted(self):
        acc = self.accepted()
        b = entry.open_board(self.board)
        f = self.board / b.state["outputs"]["p3.fix"]["file"]
        out = json.loads(f.read_text(encoding="utf-8"))
        self.assertEqual(out["not_done"], [])
        # 盤面が受けた返答の not_done を数える（受け付けた後に書き換えた写しで、数える先が盤面の出力であることを見る）
        out["not_done"] = [{"unit_key": MEAN, "why": "fork の出どころ"}]
        f.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        code, out, err = self.run_it(acc, {"ok": True, "files": ["stats.py"]})
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["not_done"], 1)

    def test_refuses_unaccepted_or_unreadable(self):
        acc = self.accepted()
        for accepted in ({"ok": False, "reason": "拒んだ", "changes": []}, "not json", {"ok": True, "reason": ""}):
            with self.subTest(accepted=accepted):
                code, out, err = self.run_it(accepted, {"ok": True, "files": ["stats.py"]})
                self.assertEqual((code, out), (2, ""))
                self.assertTrue(err.strip())
                self.assertFalse(entry.open_board(self.board).work("changes.json").exists())
        code, out, _ = self.run_it(acc, {"ok": False, "files": []})
        self.assertEqual((code, out), (2, ""))

    def test_refuses_without_clean_output(self):
        acc = self.accepted()
        for cleaned in ({"ok": True}, {"ok": False, "count": 0, "file": "/b/f.json"}, {"ok": True, "count": -1, "file": "/b/f.json"},
                        {"ok": True, "count": True, "file": "/b/f.json"}, {"ok": True, "count": 0, "file": 1},
                        {"ok": True, "removed": []}):
            with self.subTest(cleaned=cleaned):
                code, out, _ = self.run_it(acc, {"ok": True, "files": ["stats.py"]}, cleaned)
                self.assertEqual((code, out), (2, ""))

    def test_refuses_when_board_has_no_fix(self):
        """盤面が p3.fix を受けていない（受け付けの出力だけが在る）→ 2（出口を組まない）"""
        self.fix_ready()
        acc = {"ok": True, "reason": "", "changes": [{"unit_key": MEAN, "files": ["stats.py"], "what": "直した"}]}
        code, out, err = self.run_it(acc, {"ok": True, "files": ["stats.py"]})
        self.assertEqual((code, out), (2, ""))
        self.assertIn("p3.fix", err)


class TestGiveUpOnBoard(BoardCase):
    """修正の段で諦める道（R50）: assert-changed が通らない・修正の輪が 3 回とも拒まれた時は、run を落とさずに盤面を理由つきで
    止め（by works:fix）、collect は 1 本目の欄を持つ ok: false の出口を出す。後ろの段は境の節が飛ばし、報告と書き出しは走る（run 26）"""

    def changed(self, accepted):
        return run_script("assert_changed", self.repo, {"INPUTS_BASE_REV": "", "ARTIFACTS_DIR": str(self.art),
                                                         "INPUTS_ACCEPTED": json.dumps(accepted, ensure_ascii=False)})

    def collect(self, accepted, changed):
        return run_script("collect", self.repo, {
            "INPUTS_ACCEPTED": json.dumps(accepted, ensure_ascii=False), "INPUTS_CHANGED": json.dumps(changed, ensure_ascii=False),
            "INPUTS_CLEANED": json.dumps({"ok": True, "count": 1, "file": "/b/fix-removed.json"}),
            "INPUTS_TDD": json.dumps(NO_SUITE_START, ensure_ascii=False), "ARTIFACTS_DIR": str(self.art)})

    def assert_halted(self, *words):
        b = entry.open_board(self.board, allow_halted=True)
        stop = b.state.get("stop") or {}
        self.assertEqual(stop.get("by"), "works:fix", stop)
        text = json.dumps(b.state, ensure_ascii=False)
        for w in words:
            self.assertIn(w, text)

    def test_unchanged_declared_file_halts_board(self):
        self.fix_ready()
        accepted = {"ok": True, "reason": "", "changes": [{"unit_key": MEAN, "files": ["stats.py"], "what": "直した"}]}
        code, out, err = self.changed(accepted)
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertEqual((r["ok"], r["files"]), (False, []))
        self.assertIn("stats.py", r["reason"])
        self.assert_halted("stats.py", "変わっていない")
        code, out, err = self.collect(accepted, r)
        self.assertEqual(code, 0, err)
        c = json.loads(out)
        self.assertEqual((c["ok"], c["files"], c["changes_file"], c["removed"]),
                         (False, [], "", {"count": 1, "file": "/b/fix-removed.json"}))
        self.assertIn("変わっていない", c["reason"])
        self.assertEqual(c["tdd"]["ran"], False, "1 本目の欄と tdd を持つ")

    def test_given_up_fix_loop_halts_board(self):
        """修正の輪が 3 回とも拒まれて抜けた（輪の出力 = 最後の fix-accept の ok: false・done: true）→ 最後の理由のファイルを名指して止める"""
        self.fix_ready()
        accepted = {"ok": False, "done": True, "reason": "今の周に直す単位に無い", "reason_file": "/b/reject-accept_fix-3.txt",
                    "changes": []}
        code, out, err = self.changed(accepted)
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertFalse(r["ok"])
        self.assert_halted("reject-accept_fix-3.txt", "3 回")
        code, out, err = self.collect(accepted, r)
        self.assertEqual(code, 0, err)
        self.assertFalse(json.loads(out)["ok"])

    def test_collect_refuses_not_ok_on_live_board(self):
        """盤面が止まっていないのに ok: false の入力 → 2（止める口は assert-changed だけ。配線の誤り）"""
        self.fix_ready()
        code, out, _ = self.collect({"ok": False, "reason": "x", "changes": []}, {"ok": False, "files": []})
        self.assertEqual((code, out), (2, ""))


class TestLeftoversModule(unittest.TestCase):
    """後始末の模块 leftovers は .shared/core に置く（構造の調べ V13。scripts/ の下の .py は全部スクリプトとして拾われる）"""

    def test_leftovers_lives_in_core_not_scripts(self):
        self.assertFalse((BLK / "scripts" / "leftovers.py").exists())
        self.assertTrue((CORE / "leftovers.py").is_file())

    def test_leftovers_is_stdlib_only(self):
        tree = ast.parse((CORE / "leftovers.py").read_text(encoding="utf-8"))
        names = {a.name.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names}
        names |= {n.module.split(".")[0] for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.level == 0}
        self.assertTrue(names)
        self.assertEqual(sorted(names - set(sys.stdlib_module_names)), [], "標準ライブラリだけ（pack の core の他の模块も読まない）")
        self.assertFalse(any(isinstance(n, ast.ImportFrom) and n.level for n in ast.walk(tree)))

    def test_leftovers_callers_import_from_core(self):
        for name in ("ignored_before", "clean", "assert_changed"):
            with self.subTest(name):
                src = (BLK / "scripts" / f"{name}.py").read_text(encoding="utf-8")
                self.assertIn('".shared" / "core"', src)
                self.assertRegex(src, r"(?m)^from leftovers import ")


class TestCleanIgnored(ScriptCase):
    """修正役の前に git が無視するファイルを控え（ignored_before）、後で増えた物だけを消す（clean）"""

    def env(self):
        return {"ARTIFACTS_DIR": str(self.artifacts)}

    def ignored(self):
        return git(self.repo, "status", "--porcelain", "--ignored", "--untracked-files=all")

    def removed(self, out):
        """clean の出口は {ok, count, file}（件数によらず大きさが一定）。消したパスの全件は file の {"removed": [...]} に在る"""
        r = json.loads(out)
        self.assertEqual(set(r), {"ok", "count", "file"}, "消したパスの全件を stdout に出さない")
        self.assertIs(r["ok"], True)
        listed = json.loads(pathlib.Path(r["file"]).read_text(encoding="utf-8"))["removed"]
        self.assertEqual(r["count"], len(listed))
        return listed

    def test_removes_only_what_the_fixer_left(self):
        # 前から在った無視されるファイル（対象の .venv の代わりに __pycache__ の下の 1 本）は残す
        (self.repo / "__pycache__").mkdir()
        (self.repo / "__pycache__" / "old.pyc").write_bytes(b"old")
        code, out, err = run_script("ignored_before", self.repo, self.env())
        self.assertEqual(code, 0, err)
        self.assertEqual(json.loads(out)["count"], 1)
        before = self.ignored()
        # 修正役が直にテストを回す（PYTHONDONTWRITEBYTECODE 無し）と、__pycache__ の下にバイトコードが増える
        r = subprocess.run([sys.executable, "-m", "unittest", "-q"], cwd=str(self.repo), capture_output=True,
                           env={"PATH": os.environ["PATH"]}, timeout=120)
        (self.repo / "sub" / "__pycache__").mkdir(parents=True)
        (self.repo / "sub" / "__pycache__" / "x.pyc").write_bytes(b"x")
        (self.repo / "stats.py").write_text("x = 1\n")      # 修正そのもの（追跡しているファイル）は触らない
        (self.repo / "helper.py").write_text("y = 1\n")     # 未追跡でも無視されないファイルは触らない
        made = sorted(p.name for p in (self.repo / "__pycache__").iterdir())
        self.assertGreater(len(made), 1, r.stderr)
        code, out, err = run_script("clean", self.repo, self.env())
        self.assertEqual(code, 0, err)
        removed = self.removed(out)
        self.assertIn("sub/__pycache__/x.pyc", removed)
        self.assertNotIn("__pycache__/old.pyc", removed)
        self.assertEqual(sorted(p.name for p in (self.repo / "__pycache__").iterdir()), sorted(made),
                         "前から在った無視のフォルダの中身は、増えていても消さない")
        self.assertFalse((self.repo / "sub").exists(), "空になった親のフォルダも消す")
        self.assertEqual([l for l in self.ignored().splitlines() if l.startswith("!! ") and not l[3:].startswith("__pycache__/")],
                         [l for l in before.splitlines() if l.startswith("!! ") and not l[3:].startswith("__pycache__/")],
                         "前から在った無視のフォルダの外の、無視される物は修正役の前と同じ")
        self.assertEqual((self.repo / "stats.py").read_text(), "x = 1\n")
        self.assertTrue((self.repo / "helper.py").exists())

    def test_keeps_new_files_inside_ignored_dir_that_was_there_before(self):
        # 前から在った対象の仮想環境（無視のフォルダ）に修正役が依存を足しても、中身は 1 本も消さない。新しい無視のフォルダは丸ごと消す
        (self.repo / ".gitignore").write_text("__pycache__/\n*.pyc\n**/.venv\n")
        git(self.repo, "commit", "-q", "-am", "ignore .venv")
        venv = self.repo / "svc" / ".venv"
        (venv / "lib").mkdir(parents=True)
        (venv / "lib" / "old.py").write_text("o\n")
        self.assertEqual(run_script("ignored_before", self.repo, self.env())[0], 0)
        added = [venv / "lib" / "pkg" / f"m{i}.py" for i in range(50)]
        added[0].parent.mkdir()
        for p in added:
            p.write_text("m\n")
        (self.repo / "svc2" / ".venv" / "lib").mkdir(parents=True)
        (self.repo / "svc2" / ".venv" / "lib" / "n.py").write_text("n\n")
        code, out, err = run_script("clean", self.repo, self.env())
        self.assertEqual(code, 0, err)
        self.assertEqual([p for p in added if not p.exists()], [], "前から在った .venv に足したファイルは残す")
        self.assertTrue((venv / "lib" / "old.py").exists())
        self.assertFalse((self.repo / "svc2").exists(), "修正役の後に出来た無視のフォルダは消す")

    def test_keeps_empty_dir_that_was_there_before(self):
        # 前から在った空のフォルダ（対象の道具が作る build/ など）に修正役が無視されるファイルを置いても、消すのはファイルだけ
        (self.repo / "build" / "empty").mkdir(parents=True)
        (self.repo / "src").mkdir()
        (self.repo / "src" / "keep.txt").write_text("k\n")
        git(self.repo, "add", "src/keep.txt")
        git(self.repo, "commit", "-q", "-m", "src")
        (self.repo / "src" / "cache").mkdir()                   # 追跡しているフォルダの下の、前から在った空のフォルダ
        self.assertEqual(run_script("ignored_before", self.repo, self.env())[0], 0)
        (self.repo / "build" / "empty" / "x.pyc").write_bytes(b"x")
        (self.repo / "src" / "cache" / "y.pyc").write_bytes(b"y")
        (self.repo / "src" / "new" / "__pycache__").mkdir(parents=True)
        (self.repo / "src" / "new" / "__pycache__" / "z.pyc").write_bytes(b"z")
        code, out, err = run_script("clean", self.repo, self.env())
        self.assertEqual(code, 0, err)
        self.assertEqual(self.removed(out), ["build/empty/x.pyc", "src/cache/y.pyc", "src/new/__pycache__/z.pyc"])
        self.assertTrue((self.repo / "build" / "empty").is_dir(), "前から在った空のフォルダは残す")
        self.assertTrue((self.repo / "src" / "cache").is_dir(), "前から在った空のフォルダは残す")
        self.assertFalse((self.repo / "src" / "new").exists(), "修正役の後に出来たフォルダは消す")
        self.assertTrue((self.repo / "src" / "keep.txt").exists())

    def test_refuses_old_record_without_dirs(self):
        # フォルダの控えが無い古い形の控えでは、前から在った空のフォルダを見分けられないので何も消さない
        (self.board / "fix-ignored-before.json").write_text(json.dumps({"ignored": []}))
        (self.repo / "__pycache__").mkdir()
        (self.repo / "__pycache__" / "x.pyc").write_bytes(b"x")
        code, out, err = run_script("clean", self.repo, self.env())
        self.assertEqual((code, out), (1, ""))
        self.assertIn("dirs", err)
        self.assertTrue((self.repo / "__pycache__" / "x.pyc").exists())

    def test_nothing_left(self):
        self.assertEqual(run_script("ignored_before", self.repo, self.env())[0], 0)
        code, out, err = run_script("clean", self.repo, self.env())
        self.assertEqual(code, 0, err)
        self.assertEqual(self.removed(out), [])

    def test_stdout_stays_small_however_many_removed(self):
        # 子の stdout と節の出口には上限が在る（実行器が越えた子を殺す）。件数がいくら増えても stdout の大きさは一定
        self.assertEqual(run_script("ignored_before", self.repo, self.env())[0], 0)
        (self.repo / "logs").mkdir()
        for i in range(3000):
            (self.repo / "logs" / f"m{i:04d}.pyc").write_bytes(b"x")
        code, out, err = run_script("clean", self.repo, self.env())
        self.assertEqual(code, 0, err)
        self.assertLess(len(out.encode("utf-8")), 1024, "消したパスの全件を stdout に出さない")
        self.assertEqual(len(self.removed(out)), 3000, "件数と全件はファイルで保つ")
        self.assertFalse((self.repo / "logs").exists())

    def test_archon_dir_is_left_alone(self):
        (self.repo / ".gitignore").write_text("__pycache__/\n*.pyc\n.archon/\n")
        git(self.repo, "commit", "-q", "-am", "ignore .archon")
        self.assertEqual(run_script("ignored_before", self.repo, self.env())[0], 0)
        (self.repo / ".archon").mkdir()
        (self.repo / ".archon" / "x.yaml").write_text("a: 1\n")
        code, out, err = run_script("clean", self.repo, self.env())
        self.assertEqual(code, 0, err)
        self.assertEqual(self.removed(out), [])
        self.assertTrue((self.repo / ".archon" / "x.yaml").exists())

    def test_without_record_removes_nothing(self):
        (self.repo / "__pycache__").mkdir()
        (self.repo / "__pycache__" / "x.pyc").write_bytes(b"x")
        code, out, err = run_script("clean", self.repo, self.env())
        self.assertEqual((code, out), (1, ""))
        self.assertIn("fix-ignored-before.json", err)
        self.assertTrue((self.repo / "__pycache__" / "x.pyc").exists(), "控えが無ければ何も消さない")

    def test_missing_env(self):
        self.assertEqual(run_script("ignored_before", self.repo, {})[0], 2)
        self.assertEqual(run_script("clean", self.repo, {})[0], 2)


if __name__ == "__main__":
    unittest.main()
