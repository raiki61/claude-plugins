"""修正のブロック（blk-fix）の検査。

- YAML の口（inputs・returns・outcome_field・節の並び）と、修正役の output_format を良い返答の見本（replies/fix_ok.json）が通るか
- 指示書（commands/fix.md）が差し込みと決まり（commit しない・テストを消さない）を持つか
- 筋書き（fixtures/）の形: pass は assert-changed を stub し、no-change は assert-changed を実物で回して落とす
- 3 本のスクリプト（accept・assert_changed・collect）を、dev/target-seed/ を写した使い捨ての git で実際に起こす
"""
import json
import os
import pathlib
import shutil
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

DEADLINE = 1728000000
GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


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


def git(repo, *args):
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


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
        self.assertEqual(set(out["properties"]), {"ok", "files", "changes_file"})
        self.assertEqual(set(out["required"]), {"ok", "files", "changes_file"})
        self.assertEqual(out["properties"]["ok"]["type"], "boolean")
        self.assertEqual(out["properties"]["files"], {"type": "array", "items": {"type": "string"}})
        self.assertEqual(out["properties"]["changes_file"]["type"], "string")

    def test_nodes_and_loop(self):
        nodes = block()["nodes"]
        self.assertEqual([n["id"] for n in nodes], ["fix-loop", "assert-changed", "collect"])
        g = nodes[0]["loop_group"]
        self.assertEqual(g["max_iterations"], 3)
        self.assertIs(g["fresh_context"], False)
        self.assertEqual(g["until_bash"], "test $accept.output.ok = true")
        self.assertEqual([n["id"] for n in g["nodes"]], ["fix", "accept"])
        self.assertEqual(nodes[1]["depends_on"], ["fix-loop"])
        self.assertEqual(nodes[2]["depends_on"], ["assert-changed"])
        accept = find_node(nodes, "accept")
        self.assertEqual(accept["script"], "accept")
        self.assertEqual(accept["with"]["reply"], {"from": "$fix.output"})
        self.assertEqual(nodes[1]["script"], "assert_changed")
        for n in (accept, nodes[1], nodes[2]):
            self.assertEqual(n["timeout"], DEADLINE)
        self.assertEqual(nodes[1]["with"], {"base_rev": "$INPUTS.base_rev", "accepted": "$fix-loop.output"})
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
        for s in ("$INPUTS.judgment_file", "$INPUTS.open_units", "$LOOP_PREV.accept.output.reason",
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
        shutil.copytree(SEED, self.repo)
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "seed")
        self.base = git(self.repo, "rev-parse", "HEAD")
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
    def run_it(self, accepted, changed):
        env = {"INPUTS_ACCEPTED": accepted if isinstance(accepted, str) else json.dumps(accepted, ensure_ascii=False),
               "INPUTS_CHANGED": json.dumps(changed), "ARTIFACTS_DIR": str(self.artifacts)}
        return run_script("collect", self.repo, env)

    def test_collects(self):
        changes = load("fix_ok")["changes"]
        code, out, _ = self.run_it({"ok": True, "reason": "", "changes": changes}, {"ok": True, "files": ["stats.py"]})
        self.assertEqual(code, 0)
        r = json.loads(out)
        self.assertEqual(r, {"ok": True, "files": ["stats.py"], "changes_file": str(self.board / "changes.json")})
        self.assertEqual(json.loads((self.board / "changes.json").read_text(encoding="utf-8")), {"changes": changes})

    def test_refuses_unaccepted_or_unreadable(self):
        for accepted in ({"ok": False, "reason": "拒んだ", "changes": []}, "not json", {"ok": True, "reason": ""}):
            with self.subTest(accepted=accepted):
                code, out, err = self.run_it(accepted, {"ok": True, "files": ["stats.py"]})
                self.assertNotEqual(code, 0)
                self.assertEqual(out, "")
                self.assertTrue(err.strip())
                self.assertFalse((self.board / "changes.json").exists())


if __name__ == "__main__":
    unittest.main()
