"""ブロック blk-tests（テストのコマンド）と blk-delta（修正差分の審査）の検査。

- YAML に書いた審査役の返答の型が、受け付けの規則が前提にする型（graph の p3.delta_review）と同じか（設計書 5.4 節）
- blk-tests の節 run の bash を、Archon を通さずに環境変数だけ与えて走らせ、緑も赤も ok: true で出るか
- blk-delta の cut・collect のスクリプトを、使い捨ての対象リポジトリで起こして盤面と出口を見る
- 作業ツリーの写し（snapshot_tree）が、未追跡のフォルダ（入れ子の git リポジトリ）で落ちないか
筋書き（fixtures/*.stubs.yaml）は dev/check.sh が Archon で回す。
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
REPLIES = pathlib.Path(__file__).resolve().parent / "replies"
SEED = ROOT / "dev" / "target-seed"
sys.path.insert(0, str(CORE))

from accept import check_delta, role_schema, snapshot_tree  # noqa: E402
from engine.schema import validate_schema  # noqa: E402

GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


def load(name):
    return json.loads((REPLIES / f"{name}.json").read_text(encoding="utf-8"))


def workflow(blk):
    return yaml.safe_load((ROOT / blk / f"{blk}.yaml").read_text(encoding="utf-8"))


def find_node(nodes, nid):
    """節の一覧から id の節を探す（loop_group の中も辿る）"""
    for n in nodes:
        if n.get("id") == nid:
            return n
        inner = (n.get("loop_group") or {}).get("nodes") or []
        hit = find_node(inner, nid) if inner else None
        if hit:
            return hit
    return None


def git(repo, *args):
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout.strip()


class RepoCase(unittest.TestCase):
    """dev/target-seed/ を写した使い捨ての対象リポジトリと、run の成果物の置き場"""

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
        self.artifacts.mkdir()
        self.board = self.artifacts / "board"

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, blk, name, **inputs):
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        env.update({f"INPUTS_{k.upper()}": v for k, v in inputs.items()})
        env["ARTIFACTS_DIR"] = str(self.artifacts)
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        return subprocess.run([sys.executable, str(ROOT / blk / "scripts" / f"{name}.py")], cwd=str(self.repo),
                              env=env, capture_output=True, text=True, timeout=120)


# ---------------------------------------------------------------- blk-delta の型
class TestDeltaSchema(unittest.TestCase):
    def test_delta_output_format_matches_role_schema(self):
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertEqual(review["output_format"], role_schema("p3.delta_review"))

    def test_delta_ok_sample_passes_yaml_output_format(self):
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertEqual(validate_schema(load("delta_ok"), review["output_format"]), [])

    def test_delta_bad_cite_sample_passes_yaml_output_format(self):
        # 悪い見本は型では通り、受け付け（cite の字列）でだけ拒まれる——筋書き bad-cite が輪で落ちる理由
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertEqual(validate_schema(load("delta_bad_cite"), review["output_format"]), [])

    def test_delta_prompt_asks_for_empty_checks(self):
        # 1 本目は修正役が「塞いだ」と言う穴を持たないので、checks の行は全部拒まれる
        body = (ROOT / "blk-delta" / "commands" / "delta-review.md").read_text(encoding="utf-8")
        self.assertIn("checks: []", body)
        self.assertNotIn("{{", body)

    def test_delta_prompt_reads_block_outputs(self):
        # Ruling R16: 指示書の本文は同じブロックの節の出力を直に読む（include が節の名を付け替える）。
        # 宣言していない $INPUTS.<名> は Archon 0.11.1 の include が読み込みで拒むので、節の with: で束ねない
        body = (ROOT / "blk-delta" / "commands" / "delta-review.md").read_text(encoding="utf-8")
        refs = re.findall(r"\$[A-Za-z_][A-Za-z0-9_.-]*", body)
        self.assertEqual(sorted(set(refs)), ["$LOOP_PREV.review-accept.output.reason", "$cut.output.diff_file",
                                             "$cut.output.files"])
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertNotIn("with", review)

    def test_delta_loop(self):
        # 輪の中の節の id はライン全体で一意にする（模擬実行は輪の中の節を名前空間なしの id で stub に引く）
        loop = find_node(workflow("blk-delta")["nodes"], "delta-loop")["loop_group"]
        self.assertEqual([n["id"] for n in loop["nodes"]], ["review", "review-accept"])
        self.assertEqual(loop["until_bash"], "test $review-accept.output.ok = true")

    def test_delta_review_sandbox(self):
        # Ruling R12: Bash を持たない役でも、サンドボックスの外へ出る道を閉じる
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertEqual(review["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})


# ---------------------------------------------------------------- blk-tests
class TestTestsBlock(RepoCase):
    def run_bash(self, cmd, rc=0):
        node = find_node(workflow("blk-tests")["nodes"], "run")
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_") and k != "PYTHONDONTWRITEBYTECODE"}
        env.update(INPUTS_CMD=cmd, ARTIFACTS_DIR=str(self.artifacts))
        r = subprocess.run(["bash", "-c", node["bash"]], cwd=str(self.repo), env=env, capture_output=True, text=True, timeout=120)
        if rc:
            self.assertNotEqual(r.returncode, 0, r.stdout)
            return None
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(validate_schema(out, node["output_format"]), [])
        return out

    def test_run_node_contract(self):
        wf = workflow("blk-tests")
        self.assertEqual(wf["returns"], "run")
        self.assertEqual(wf["outcome_field"], "ok")
        self.assertIn("cmd", wf["inputs"])
        fmt = find_node(wf["nodes"], "run")["output_format"]
        self.assertEqual(sorted(fmt["required"]), ["green", "log", "ok"])

    def test_green_command(self):
        out = self.run_bash("python3 -c 'print(\"走った\")' && test -f stats.py")   # cwd は対象リポジトリ
        self.assertEqual(out, {"ok": True, "green": True, "log": str(self.board / "tests.log")})
        self.assertIn("走った", (self.board / "tests.log").read_text(encoding="utf-8"))

    def test_empty_command_fails_the_node(self):
        # 何も走らせずに緑と言わない
        self.run_bash("", rc=1)
        self.assertFalse((self.board / "tests.log").exists())

    def test_tests_leave_no_bytecode(self):
        # 種の .gitignore が無くても、テストが作業ツリーに __pycache__ を作らない（修正の差分に紛れ込まない）
        (self.repo / ".gitignore").unlink()
        out = self.run_bash("python3 -m unittest -q test_stats")
        self.assertEqual((out["ok"], out["green"]), (True, False))   # 種はバグ入りで赤
        self.assertEqual(list(self.repo.rglob("__pycache__")), [])

    def test_red_command_is_still_ok(self):
        # 赤を人の関所に見せるのがこの段の仕事なので、赤でも節は通る
        out = self.run_bash("echo 赤 >&2; exit 3")
        self.assertEqual((out["ok"], out["green"]), (True, False))
        self.assertIn("赤", (self.board / "tests.log").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- blk-delta の cut
class TestCut(RepoCase):
    def fix(self):
        (self.repo / "stats.py").write_text((self.repo / "stats.py").read_text().replace("return lo\n    return x", "return hi\n    return x"))
        (self.repo / "helper.py").write_text("def helper():\n    return 1\n")

    def test_cut_writes_diff_snapshot_and_files(self):
        self.fix()
        r = self.run_script("blk-delta", "cut", base_rev=self.base)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out, {"ok": True, "files": ["helper.py", "stats.py"], "diff_file": str(self.board / "fix.diff")})
        diff = (self.board / "fix.diff").read_text(encoding="utf-8")
        self.assertIn("+        return hi", diff)
        self.assertIn("+def helper():", diff)       # 未追跡のファイルも差分に載る
        self.assertEqual(json.loads((self.board / "delta-snapshot.json").read_text()), snapshot_tree(self.repo))
        # 切った直後の作業ツリーのままなら、受け付けは写しとの突き合わせを通る
        self.assertTrue(check_delta(load("delta_ok"), self.board, self.base, self.repo)["ok"])

    def test_cut_empty_base_rev_means_head(self):
        self.fix()
        r = self.run_script("blk-delta", "cut", base_rev="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["files"], ["helper.py", "stats.py"])

    def test_cut_clean_tree(self):
        r = self.run_script("blk-delta", "cut", base_rev="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["files"], [])
        self.assertEqual((self.board / "fix.diff").read_text(), "")

    def test_cut_skips_bytecode(self):
        # 種の .gitignore が無く、テストがバイトコードを作った作業ツリー。追跡している .pyc が変わっても差分に載せない
        git(self.repo, "rm", "-q", ".gitignore")
        (self.repo / "old.pyc").write_bytes(b"\x00old")
        git(self.repo, "add", "old.pyc")
        git(self.repo, "commit", "-q", "-m", "no ignore")
        base = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "old.pyc").write_bytes(b"\x00new")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
        subprocess.run([sys.executable, "-m", "unittest", "-q", "test_stats"], cwd=str(self.repo), env=env,
                       capture_output=True, timeout=120)
        self.assertTrue(list(self.repo.rglob("*.pyc")))                  # バイトコードは本当に出来た
        self.fix()
        r = self.run_script("blk-delta", "cut", base_rev=base)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["files"], ["helper.py", "stats.py"])
        diff = (self.board / "fix.diff").read_text(encoding="utf-8", errors="replace")
        self.assertNotIn(".pyc", diff)
        self.assertNotIn("__pycache__", diff)

    def test_seed_ignores_bytecode(self):
        env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
        subprocess.run([sys.executable, "-m", "unittest", "-q", "test_stats"], cwd=str(self.repo), env=env,
                       capture_output=True, timeout=120)
        self.assertEqual(git(self.repo, "status", "--porcelain", "--untracked-files=all"), "")

    def test_cut_and_accept_japanese_name(self):
        # 日本語の名前も git の引用（"\346\227\245..."）でなく、そのままの名前で files と受け付けに乗る
        (self.repo / "日本.py").write_text("def 日付():\n    return 1\n", encoding="utf-8")
        (self.repo / "stats.py").write_text((self.repo / "stats.py").read_text() + "\n# 直した\n")
        git(self.repo, "add", "日本.py")                                   # 追跡している側（diff --name-only）
        (self.repo / "未追跡.py").write_text("x = 1\n", encoding="utf-8")  # 未追跡の側（ls-files）
        r = self.run_script("blk-delta", "cut", base_rev=self.base)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["files"], sorted(["stats.py", "日本.py", "未追跡.py"]))
        self.assertIn("未追跡.py", (self.board / "fix.diff").read_text(encoding="utf-8"))
        for where, cite in (("日本.py", "def 日付():"), ("未追跡.py", "x = 1")):
            reply = {"faces": [{"key": f"{where} 使われない物", "kind": "dead_path", "where": where, "cite": cite,
                                "why": "どこからも呼ばれない物を修正が足している"}], "checks": []}
            res = check_delta(reply, self.board, self.base, self.repo)
            self.assertTrue(res["ok"], res["reason"])

    def test_cut_bad_base_rev_stops_the_run(self):
        r = self.run_script("blk-delta", "cut", base_rev="no-such-rev")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")
        self.assertIn("no-such-rev", r.stderr)

    def test_cut_missing_env(self):
        env_less = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_") and k != "ARTIFACTS_DIR"}
        r = subprocess.run([sys.executable, str(ROOT / "blk-delta" / "scripts" / "cut.py")], cwd=str(self.repo),
                           env={**env_less, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, timeout=120)
        self.assertEqual(r.returncode, 2)
        self.assertEqual(r.stdout, "")


# ---------------------------------------------------------------- blk-delta の accept と collect
class TestAcceptCollect(RepoCase):
    def test_accept_then_collect_counts_faces(self):
        (self.repo / "stats.py").write_text((self.repo / "stats.py").read_text().replace("return lo\n    return x", "return hi + 1\n    return x"))
        reply = json.dumps(load("delta_bad_cite"), ensure_ascii=False)   # stats.py を触ったので cite は今の姿に在る
        r = self.run_script("blk-delta", "accept", reply=reply, base_rev=self.base)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["ok"], True, r.stdout)
        r = self.run_script("blk-delta", "collect")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"ok": True, "faces": 1})

    def test_accept_rejects_face_outside_touched_files(self):
        r = self.run_script("blk-delta", "accept", reply=json.dumps(load("delta_bad_cite")), base_rev="")
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertFalse(out["ok"])
        self.assertTrue(out["reason"])
        self.assertFalse((self.board / "delta-review.json").exists())   # 拒んだ返答は盤面に残さない

    def test_collect_without_accepted_review_fails(self):
        r = self.run_script("blk-delta", "collect")
        self.assertEqual(r.returncode, 1)
        self.assertEqual(r.stdout, "")


# ---------------------------------------------------------------- snapshot_tree と未追跡のフォルダ
class TestSnapshotNestedRepo(RepoCase):
    def test_untracked_nested_repo_does_not_crash(self):
        sub = self.repo / "sub"
        sub.mkdir()
        (sub / "a.txt").write_text("a\n")
        git(sub, "init", "-q")
        git(sub, "add", "-A")
        git(sub, "commit", "-q", "-m", "sub")
        self.assertIn("?? sub/", git(self.repo, "status", "--porcelain", "--untracked-files=all"))
        before = snapshot_tree(self.repo)
        self.assertEqual(before, snapshot_tree(self.repo))   # 同じ姿なら同じ写し
        (sub / "a.txt").write_text("b\n")                    # 入れ子の中身が変われば写しも変わる
        self.assertNotEqual(before["diff_sha256"], snapshot_tree(self.repo)["diff_sha256"])

    def test_cut_and_accept_with_nested_repo(self):
        sub = self.repo / "sub"
        sub.mkdir()
        (sub / "a.txt").write_text("a\n")
        git(sub, "init", "-q")
        r = self.run_script("blk-delta", "cut", base_rev="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("sub/", json.loads(r.stdout)["files"])
        self.assertTrue(check_delta(load("delta_ok"), self.board, "", self.repo)["ok"])


if __name__ == "__main__":
    unittest.main()
