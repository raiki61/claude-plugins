"""修正のブロック（blk-fix）の検査。

- YAML の口（inputs・returns・outcome_field・節の並び）と、修正役の output_format を良い返答の見本（replies/fix_ok.json）が通るか
- 指示書（commands/fix.md）が差し込みと決まり（commit しない・テストを消さない）を持つか
- 筋書き（fixtures/）の形: pass は assert-changed を stub し、no-change は assert-changed を実物で回して落とす
- 5 本のスクリプト（ignored_before・accept・clean・assert_changed・collect）を、dev/target-seed/ を写した使い捨ての git で実際に起こす
"""
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
BLK = ROOT / "blk-fix"
CORE = ROOT / ".shared" / "core"
REPLIES = pathlib.Path(__file__).resolve().parent / "replies"
SEED = ROOT / "dev" / "target-seed"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(CORE / "graphloops"))

from accept import check_judge  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
from gitkit import committed_copy, git  # noqa: E402

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
        self.assertEqual(set(y["inputs"]), {"judgment_file", "open_units", "base_rev"})
        self.assertEqual(y["inputs"]["base_rev"].get("default"), "")
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
        for s in ("$INPUTS.judgment_file", "$INPUTS.open_units", "$LOOP_PREV.fix-accept.output.reason",
                  "git commit", "テスト", "unit_key"):
            self.assertIn(s, body)
        # 前の周の理由は指示書の本文で $LOOP_PREV から直に読む。Archon 0.11.1 の include は本文の $LOOP_PREV の節の名を
        # 付け替えるが、宣言していない $INPUTS.prev_reason は読み込みで拒む（Ruling R16）。節の with: で束ねない
        self.assertNotIn("$INPUTS.prev_reason", body)
        fix = find_node(block()["nodes"], "fix")
        self.assertNotIn("with", fix)
        self.assertNotIn("{{", body, "graphloops の engine の穴を残さない")

    def test_fixtures(self):
        fx = {p.name: yaml.safe_load(p.read_text(encoding="utf-8")) for p in (BLK / "fixtures").glob("*.stubs.yaml")}
        self.assertEqual(set(fx), {"pass.stubs.yaml", "no-change.stubs.yaml"})
        for name, f in fx.items():
            with self.subTest(name):
                self.assertEqual(f["fix"], load("fix_ok"))
                self.assertIs(f.get("exec-code"), True)
        self.assertEqual(fx["pass.stubs.yaml"]["fixture"]["expect"], "completed")
        self.assertIn("assert-changed", fx["pass.stubs.yaml"])
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


class TestAccept(ScriptCase):
    def run_it(self, reply):
        return run_script("accept", self.repo, {"INPUTS_REPLY": json.dumps(reply, ensure_ascii=False),
                                                "INPUTS_BASE_REV": self.base, "ARTIFACTS_DIR": str(self.artifacts)})

    def judged(self):
        r = check_judge(load("judge_ok"), self.board, self.base, self.repo)
        self.assertTrue(r["ok"], r["reason"])

    def test_accepts_and_carries_changes(self):
        self.judged()
        code, out, _ = self.run_it(load("fix_ok"))
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), {"ok": True, "reason": "", "changes": load("fix_ok")["changes"]})

    def test_rejects_uncovered_unit(self):
        self.judged()
        code, out, _ = self.run_it(load("fix_missing_unit"))
        self.assertEqual(code, 0)
        r = json.loads(out)
        self.assertFalse(r["ok"])
        self.assertEqual(r["changes"], [])

    def test_rejects_duplicate_unit_key(self):
        self.judged()
        reply = load("fix_ok")
        reply["changes"].append(dict(reply["changes"][0]))
        r = json.loads(self.run_it(reply)[1])
        self.assertFalse(r["ok"])
        self.assertIn(reply["changes"][0]["unit_key"], r["reason"])

    def test_rejects_without_judgment(self):
        r = json.loads(self.run_it(load("fix_ok"))[1])
        self.assertFalse(r["ok"])
        self.assertIn("judgment.json", r["reason"])
        self.assertEqual(r["changes"], [])


class TestCollect(ScriptCase):
    def run_it(self, accepted, changed, cleaned=None):
        if cleaned is None:
            cleaned = {"ok": True, "removed": []}
        env = {"INPUTS_ACCEPTED": accepted if isinstance(accepted, str) else json.dumps(accepted, ensure_ascii=False),
               "INPUTS_CHANGED": json.dumps(changed), "INPUTS_CLEANED": json.dumps(cleaned),
               "ARTIFACTS_DIR": str(self.artifacts)}
        return run_script("collect", self.repo, env)

    def test_collects(self):
        changes = load("fix_ok")["changes"]
        code, out, _ = self.run_it({"ok": True, "reason": "", "changes": changes}, {"ok": True, "files": ["stats.py"]},
                                   {"ok": True, "removed": ["__pycache__/"]})
        self.assertEqual(code, 0)
        r = json.loads(out)
        self.assertEqual(r, {"ok": True, "files": ["stats.py"], "changes_file": str(self.board / "changes.json"),
                             "removed": ["__pycache__/"]}, "消した生成物を出口に並べる")
        self.assertEqual(json.loads((self.board / "changes.json").read_text(encoding="utf-8")), {"changes": changes})

    def test_refuses_unaccepted_or_unreadable(self):
        for accepted in ({"ok": False, "reason": "拒んだ", "changes": []}, "not json", {"ok": True, "reason": ""}):
            with self.subTest(accepted=accepted):
                code, out, err = self.run_it(accepted, {"ok": True, "files": ["stats.py"]})
                self.assertNotEqual(code, 0)
                self.assertEqual(out, "")
                self.assertTrue(err.strip())
                self.assertFalse((self.board / "changes.json").exists())

    def test_refuses_without_clean_output(self):
        changes = load("fix_ok")["changes"]
        for cleaned in ({"ok": True}, {"ok": False, "removed": []}, {"ok": True, "removed": [1]}):
            with self.subTest(cleaned=cleaned):
                code, out, _ = self.run_it({"ok": True, "reason": "", "changes": changes},
                                           {"ok": True, "files": ["stats.py"]}, cleaned)
                self.assertEqual((code, out), (2, ""))


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
