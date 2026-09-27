"""修正のブロック（blk-fix）の検査。

- YAML の口（inputs・returns・outcome_field・節の並び）と、修正役の output_format を良い返答の見本（replies/fix_ok.json）が通るか
  （YAML の切り替えは線 A の Task 17。それまで役の output_format は 1 本目のまま。切り替えで貼る値は recount.FIX_OUTPUT_FORMAT）
- 指示書（commands/fix.md）が差し込みと決まり（commit しない・テストを消さない）を持つか
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

from accept import role_schema  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
import engine.util as engine_util  # noqa: E402
import entry  # noqa: E402
from gitkit import committed_copy, git  # noqa: E402
import linekit  # noqa: E402
import node_marker  # noqa: E402

DEADLINE = 1728000000


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
                       capture_output=True, text=True, stdin=subprocess.DEVNULL, timeout=120)
    return r.returncode, r.stdout, r.stderr


class TestBlockYaml(unittest.TestCase):
    def test_fix_ok_sample_passes_yaml_output_format(self):
        fix = find_node(block()["nodes"], "fix")
        self.assertEqual(validate_schema(load("fix_ok"), fix["output_format"]), [])
        # 欄を足した返答は型で拒む（additionalProperties: false）
        extra = load("fix_ok")
        extra["changes"][0]["note"] = "余分"
        self.assertNotEqual(validate_schema(extra, fix["output_format"]), [])
        self.assertNotEqual(validate_schema({**load("fix_ok"), "done": True}, fix["output_format"]), [])

    def test_signature(self):
        y = block()
        self.assertEqual(y["name"], "blk-fix")
        self.assertEqual(set(y["inputs"]), {"judgment_file", "open_units", "base_rev", "plan_file", "human_notes", "policy_path"})
        for k in ("base_rev", "plan_file", "human_notes", "policy_path"):   # 足した 3 つは空でよい（仕様 3.2）
            self.assertEqual(y["inputs"][k].get("default"), "", k)
            self.assertNotIn("required", y["inputs"][k], k)
        self.assertEqual(y["returns"], "collect")
        self.assertEqual(y["outcome_field"], "ok")
        out = find_node(y["nodes"], "collect")["output_format"]
        self.assertEqual(set(out["properties"]), {"ok", "files", "changes_file", "removed"})
        self.assertEqual(set(out["required"]), {"ok", "files", "changes_file", "removed"})
        self.assertEqual(out["properties"]["removed"], {"type": "array", "items": {"type": "string"}})
        self.assertEqual(out["properties"]["ok"]["type"], "boolean")
        self.assertEqual(out["properties"]["files"], {"type": "array", "items": {"type": "string"}})
        self.assertEqual(out["properties"]["changes_file"]["type"], "string")

    def test_nodes_and_loop(self):
        nodes = block()["nodes"]
        self.assertEqual([n["id"] for n in nodes], ["ignored-before", "fix-loop", "clean", "assert-changed", "collect"])
        before, loop, clean, changed, collect = nodes
        self.assertNotIn("depends_on", before)
        self.assertEqual(before["script"], "ignored_before")
        self.assertEqual(loop["depends_on"], ["ignored-before"], "控えは修正役より前")
        self.assertEqual(clean["script"], "clean")
        self.assertEqual(clean["depends_on"], ["fix-loop"])
        self.assertEqual(collect["with"]["cleaned"], {"from": "$clean.output"})
        g = loop["loop_group"]
        self.assertEqual(g["max_iterations"], 3)
        self.assertIs(g["fresh_context"], False)
        self.assertEqual(g["until_bash"], "test $fix-accept.output.ok = true")
        self.assertEqual([n["id"] for n in g["nodes"]], ["fix", "fix-accept"])
        self.assertEqual(changed["depends_on"], ["clean"])
        self.assertEqual(collect["depends_on"], ["assert-changed"])
        accept = find_node(nodes, "fix-accept")
        self.assertEqual(accept["script"], "accept")
        self.assertEqual(accept["with"]["reply"], {"from": "$fix.output"})
        self.assertEqual(changed["script"], "assert_changed")
        for n in (before, accept, clean, changed, collect):
            self.assertEqual(n["timeout"], DEADLINE)
        self.assertEqual(changed["with"], {"base_rev": "$INPUTS.base_rev", "accepted": "$fix-loop.output"})
        self.assertEqual(accept["with"]["base_rev"], "$INPUTS.base_rev")

    def test_fix_node(self):
        fix = find_node(block()["nodes"], "fix")
        self.assertEqual(fix["command"], "fix")
        self.assertEqual(fix["allowed_tools"], ["Read", "Grep", "Glob", "Edit", "Write", "Bash"])
        self.assertEqual(fix["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})
        self.assertEqual(fix["idle_timeout"], DEADLINE)
        of = fix["output_format"]
        self.assertIs(of["additionalProperties"], False)
        self.assertEqual(of["required"], ["changes"])
        item = of["properties"]["changes"]["items"]
        self.assertIs(item["additionalProperties"], False)
        self.assertEqual(set(item["required"]), {"unit_key", "files", "what"})

    def test_fix_prompt(self):
        body = (BLK / "commands" / "fix.md").read_text(encoding="utf-8")
        for s in ("$INPUTS.judgment_file", "$INPUTS.open_units", "$LOOP_PREV.fix-accept.output.reason_file",
                  "git commit", "テスト", "unit_key"):
            self.assertIn(s, body)
        # 指示書が差し込む $INPUTS は全部ブロックの inputs に在る（宣言していない $INPUTS.<名> は Archon が読み込みで拒む）
        self.assertLessEqual(set(re.findall(r"\$INPUTS\.([A-Za-z_]\w*)", body)), set(block()["inputs"]))
        # 理由の本文は貼らない（Archon は $LOOP_PREV で貼った中身をもう一度置き換えに通す）。パスだけを貼って Read させる
        self.assertEqual(re.findall(r"\$LOOP_PREV\.[\w.-]*", body), ["$LOOP_PREV.fix-accept.output.reason_file"])
        # 前の周の理由は指示書の本文で $LOOP_PREV から直に読む。Archon 0.11.1 の include は本文の $LOOP_PREV の節の名を
        # 付け替えるが、宣言していない $INPUTS.prev_reason は読み込みで拒む（Ruling R16）。節の with: で束ねない
        self.assertNotIn("$INPUTS.prev_reason", body)
        fix = find_node(block()["nodes"], "fix")
        self.assertNotIn("with", fix)
        self.assertNotIn("{{", body, "graphloops の engine の穴を残さない")

    def test_fix_prompt_reads_inputs(self):
        """0.21.0 の p3.fix.md から書き直した指示書: 修正案・人の答え・方針の文書を入口から読み、前の回の拒否の理由は
        reason_file（パス）で読む（裁定 R44。計画の $LOOP_PREV.fix-accept.output.reason はパスの欄 reason_file に替わった）。
        返答の欄は graph の p3.fix の schema の欄を名指し、判定の prescriptions（零処方）を先に採らせる"""
        body = (BLK / "commands" / "fix.md").read_text(encoding="utf-8")
        for s in ("$INPUTS.plan_file", "$INPUTS.human_notes", "$INPUTS.policy_path", "$LOOP_PREV.fix-accept.output.reason"):
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

    def test_output_format_constant_matches_graph(self):
        """T17 で YAML の fix に貼る値: 印を外すと graph の p3.fix の schema と同じ。印の名は fix。rejudge_requested の欄は
        graph の schema に元から在る（T23 の再審の起点）"""
        import recount
        self.assertEqual(recount.FIX_NODE, "p3.fix")
        self.assertEqual(node_marker.strip(recount.FIX_OUTPUT_FORMAT), role_schema("p3.fix"))
        mark = node_marker.parse(recount.FIX_OUTPUT_FORMAT["description"])
        self.assertEqual((mark["name"], mark["cont"], mark["flags"]), ("fix", None, frozenset()))
        self.assertIn("rejudge_requested", recount.FIX_OUTPUT_FORMAT["properties"])
        for name in ("fix2_ok", "fix2_count_not_dropped", "fix2_sites_mismatch", "fix2_silent_closure",
                     "fix2_rejudge_requested"):
            with self.subTest(name):
                self.assertEqual(validate_schema(load(name), role_schema("p3.fix")), [], "見本は graph の型を通る")

    def test_script_inputs_constants(self):
        """各 script は読む INPUTS_* を定数 INPUTS に持つ（裁定 TA16。Task 17 が YAML の with: と突き合わせる）"""
        want = {"accept": ("INPUTS_REPLY", "INPUTS_BASE_REV"), "collect": ("INPUTS_ACCEPTED", "INPUTS_CHANGED", "INPUTS_CLEANED"),
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
        self.assertEqual(set(fx), {"pass.stubs.yaml", "no-change.stubs.yaml"})
        for name, f in fx.items():
            with self.subTest(name):
                self.assertEqual(f["fix"], load("fix_ok"))
                self.assertIs(f.get("exec-code"), True)
        self.assertEqual(fx["pass.stubs.yaml"]["fixture"]["expect"], "completed")
        self.assertIn("assert-changed", fx["pass.stubs.yaml"])
        # collect は盤面を開く（数え直しの後）。このブロック単体の模擬実行には盤面が無いので stub する（出口の 1 本目の欄を持つ）
        self.assertLessEqual({"ok", "files", "changes_file", "removed"}, set(fx["pass.stubs.yaml"]["collect"]))
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
        for bad in ("not json", {"ok": False, "reason": "拒んだ", "changes": []}, {"ok": True, "reason": ""}):
            with self.subTest(accepted=bad):
                self.assertEqual(self.run_it(accepted=bad)[0], 2)


# ---------------------------------------------------------------- 盤面の上の受け付け（線 A Task 12。仕様 3.2）
# 1 本目の試験は偽の盤面（judgment.json と check_fix）の上で受け付けを見ていた。同じ主張（義務の単位を全部覆う・同じ単位を
# 2 行に分けない・判定の前に修正を受けない・出口の 1 本目の欄）を、本物の盤面の done("p3.fix") の上で確かめる。
JUDGE = "judge_ok"
MEAN, CLAMP = (u["key"] for u in load(JUDGE)["units"])
PREMISES_REPLY = {"constraints": []}
PLAN_REVIEW_OK = {"faces": [], "shrink": [], "faces_none": "案の 2 か所を stats.py で読み、穴も別案も無いと確かめた",
                  "reason": "分母と戻り値を 1 行ずつ直す案で、足す物も狭める物も無い"}
NARROWS = [{"what": "空の列の mean", "why": "空の列の平均は 0 割りの例外のまま（前も例外で、狭まる能力は無いが人に確かめる）"}]
# 種の stats.py の 2 つの直し（mean の分母・clamp の上限の枝）
FIXED = {"sum(xs) / (len(xs) - 1)": "sum(xs) / len(xs)", "    if x > hi:\n        return lo": "    if x > hi:\n        return hi"}
# 分母は直したが、前の式を行末の注記に残した形（判定役の問い「(len(xs) - 1)」の fixed の文字列は注記の行も数える）
RESIDUE = {"sum(xs) / (len(xs) - 1)": "sum(xs) / len(xs)  # 前は sum(xs) / (len(xs) - 1)（不偏分散の分母と取り違えていた）",
           "    if x > hi:\n        return lo": "    if x > hi:\n        return hi"}


def plan_reply(narrows=()):
    return {"plan": [{"unit_keys": [MEAN, CLAMP], "approach": "mean の分母を len(xs) に、clamp の上限の枝の戻り値を hi に直す",
                      "adds": [], "removes": [], "shrink_first": "足す物は無い。2 か所の式を 1 行ずつ直すだけで足りる",
                      "narrows": list(narrows)}]}


def pending_attempt(b, nid):
    inst = next(i for i in b.rd["instances"].values() if i["node"] == nid and i["status"] == "pending")
    return inst.get("attempts", 1)


def launch(board, nid):
    """ブロックの snap の節の代わり: 待っている試行に起こした印を置く（盤面は印の無い返答を受けない）"""
    b = entry.open_board(board)
    b.mark_launched(nid, pending_attempt(b, nid))


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

    def judged(self):
        """判定を受けた盤面（start → 並行 PR の任せ先・前提の役 → 判定）"""
        self.repo = linekit.seed_repo(self.tmp / "repo", declared=True)
        req = self.tmp / "request.json"
        req.write_text((SEED / "request_ok.json").read_text(encoding="utf-8"), encoding="utf-8")
        entry.start(self.board, self.repo, {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "mid_gate": "",
                                            "adapter": "", "policy_md": ""}, run_id="run-12")
        pr = {k: v for k, v in linekit.reply("pr_no_conflicts").items() if k != "excluded"}
        self.take("p0.parallel_pr", pr)
        self.take("p0.premises", PREMISES_REPLY)
        self.take("p2.diagnose", load(JUDGE))

    def fix_ready(self, narrows=(), answer=None):
        """p3.fix が待ち、起こした印の在る盤面（修正案 → 事前審査。narrows なら p2.human_gate が聞き、answer で答える）"""
        self.judged()
        self.take("p2.fix_plan", plan_reply(narrows))
        got = self.take("p2.plan_review", PLAN_REVIEW_OK)
        if answer is not None:
            self.assertTrue(got["asking"], got)
            entry.open_board(self.board).answer(*answer)
        self.assertIn("p3.fix", entry.open_board(self.board).settle()["ready"])
        launch(self.board, "p3.fix")

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
        """関所で continue "x" を答えた盤面 → 人の答えが record.process.human_items に在り（p3.fix の reads）、受け付けが通る"""
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

    def test_wrote_refs_reads_from_board(self):
        """盤面に reads.jsonl（包みのフックの実物の行の形）を置く → 数え直しの wrote_refs_reads の state が read。無ければ none"""
        self.fix_ready()
        self.edit_tree(FIXED)
        target = self.repo / "test_stats.py"
        raw = target.read_bytes()
        row = {"ts": "2026-09-27T10:00:00", "session_id": "s-12", "agent_id": None, "path": os.path.realpath(target),
               "file_sha": hashlib.sha256(raw).hexdigest(), "bytes": len(raw), "partial": False, "partial_why": None,
               "tool_use_id": "toolu_12"}
        reply = load("fix2_ok")
        reply["wrote_refs"] = [{"kind": "text", "cite": "def test_clamp_above_range", "target": "test_stats.py",
                                "where": "stats.py"}]
        (self.board / "reads.jsonl").write_text(json.dumps(row, ensure_ascii=False) + "\n", encoding="utf-8")
        got = self.accept(reply)
        self.assertTrue(got["ok"], got)
        reads = entry.open_board(self.board).loop_state["wrote_refs_reads"]
        self.assertEqual([(r["target"], r["state"]) for r in reads["items"]], [("test_stats.py", "read")])

class TestAccept(BoardCase):
    """受け付けのスクリプト（blk-fix の節 fix-accept）を子で起こす。script_io.main と同じ環境変数の約束"""

    def run_it(self, reply, **env):
        full = {"INPUTS_REPLY": json.dumps(reply, ensure_ascii=False), "INPUTS_BASE_REV": "", "ARTIFACTS_DIR": str(self.art),
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
        code, out, err = self.run_it(reply)
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertFalse(r["ok"])
        self.assertIn(MEAN, r["reason"])
        self.assertEqual(r["changes"], [])
        self.assertEqual(pathlib.Path(r["reason_file"]).read_text(encoding="utf-8"), r["reason"])
        self.assertEqual(entry.open_board(self.board).node_state("p3.fix"), "pending")

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
        entry.start(self.board, self.repo, {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "mid_gate": "",
                                            "adapter": "", "policy_md": ""}, run_id="run-12")
        before = board_shas(self.board)
        code, out, err = self.run_it(load("fix2_ok"))
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
            cleaned = {"ok": True, "removed": []}
        env = {"INPUTS_ACCEPTED": accepted if isinstance(accepted, str) else json.dumps(accepted, ensure_ascii=False),
               "INPUTS_CHANGED": json.dumps(changed), "INPUTS_CLEANED": json.dumps(cleaned),
               "ARTIFACTS_DIR": str(self.art)}
        return run_script("collect", self.repo, env)

    def accepted(self, reply="fix2_ok"):
        self.fix_ready()
        self.edit_tree(FIXED)
        got = self.accept(load(reply))
        self.assertTrue(got["ok"], got)
        return got

    def test_exit_keeps_v1_fields(self):
        acc = self.accepted()
        code, out, err = self.run_it(acc, {"ok": True, "files": ["stats.py"]}, {"ok": True, "removed": ["__pycache__/"]})
        self.assertEqual(code, 0, err)
        r = json.loads(out)
        self.assertLessEqual({"ok", "files", "changes_file", "removed"}, set(r), "1 本目の欄を全部残す")
        self.assertEqual(set(r), {"ok", "files", "changes_file", "removed", "fix_file", "not_done", "coverage", "reads_file"})
        b = entry.open_board(self.board)
        self.assertEqual((r["ok"], r["files"], r["removed"]), (True, ["stats.py"], ["__pycache__/"]))
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
        r = json.loads(self.run_it(acc, {"ok": True, "files": ["stats.py"]})[1])
        self.assertEqual(r["not_done"], 1)

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
        for cleaned in ({"ok": True}, {"ok": False, "removed": []}, {"ok": True, "removed": [1]}):
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


class TestCleanIgnored(ScriptCase):
    """修正役の前に git が無視するファイルを控え（ignored_before）、後で増えた物だけを消す（clean）"""

    def env(self):
        return {"ARTIFACTS_DIR": str(self.artifacts)}

    def ignored(self):
        return git(self.repo, "status", "--porcelain", "--ignored", "--untracked-files=all")

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
        removed = json.loads(out)["removed"]
        self.assertIn("sub/__pycache__/x.pyc", removed)
        self.assertNotIn("__pycache__/old.pyc", removed)
        self.assertEqual(sorted(p.name for p in (self.repo / "__pycache__").iterdir()), ["old.pyc"])
        self.assertFalse((self.repo / "sub").exists(), "空になった親のフォルダも消す")
        self.assertEqual([l for l in self.ignored().splitlines() if l.startswith("!!")],
                         [l for l in before.splitlines() if l.startswith("!!")], "無視される物は修正役の前と同じ")
        self.assertEqual((self.repo / "stats.py").read_text(), "x = 1\n")
        self.assertTrue((self.repo / "helper.py").exists())

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
        self.assertEqual(json.loads(out)["removed"], ["build/empty/x.pyc", "src/cache/y.pyc", "src/new/__pycache__/z.pyc"])
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
        code, out, _ = run_script("clean", self.repo, self.env())
        self.assertEqual((code, json.loads(out)), (0, {"ok": True, "removed": []}))

    def test_archon_dir_is_left_alone(self):
        (self.repo / ".gitignore").write_text("__pycache__/\n*.pyc\n.archon/\n")
        git(self.repo, "commit", "-q", "-am", "ignore .archon")
        self.assertEqual(run_script("ignored_before", self.repo, self.env())[0], 0)
        (self.repo / ".archon").mkdir()
        (self.repo / ".archon" / "x.yaml").write_text("a: 1\n")
        code, out, _ = run_script("clean", self.repo, self.env())
        self.assertEqual((code, json.loads(out)["removed"]), (0, []))
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
