"""判定のブロック（blk-judge）の検査。

- YAML の口: 判定役の節の output_format が受け付けの規則の型（role_schema("p2.diagnose")）と同じか、良い返答の見本が
  YAML の output_format を通るか（設計書 5.4 節）。入口・出口・輪の形がブリーフどおりか
- つなぎのスクリプト: intake（依頼を読んで check_request。拒めば終了コード 1）・accept（check_judge を script_io で包む）・
  collect（盤面の judgment.json から出口を組む）を別のプロセスで回す
- 筋書き（fixtures/）が 3 本在り、期待の形がブリーフどおりか。Archon で回すのは dev/check.sh（workflow test）
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
BLK = ROOT / "blk-judge"
CORE = ROOT / ".shared" / "core"
REPLIES = pathlib.Path(__file__).resolve().parent / "replies"
SEED = ROOT / "dev" / "target-seed"
sys.path.insert(0, str(CORE))

from accept import JUDGE_SNAPSHOT_FILE, check_judge, role_schema, snapshot_tree  # noqa: E402
from engine.schema import validate_schema  # noqa: E402

DEADLINE = 1728000000
GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


def load(name):
    return json.loads((REPLIES / f"{name}.json").read_text(encoding="utf-8"))


def workflow():
    return yaml.safe_load((BLK / "blk-judge.yaml").read_text(encoding="utf-8"))


def find_node(y, nid):
    """節を id で引く。loop_group の中の節も辿る"""
    def walk(nodes):
        for n in nodes or []:
            if n.get("id") == nid:
                return n
            if "loop_group" in n:
                hit = walk(n["loop_group"].get("nodes"))
                if hit is not None:
                    return hit
        return None
    n = walk(y.get("nodes"))
    if n is None:
        raise AssertionError(f"節 {nid} が無い")
    return n


def git(repo, *args):
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


class YamlCase(unittest.TestCase):
    def setUp(self):
        self.y = workflow()

    def test_judge_output_format_matches_role_schema(self):
        self.assertEqual(find_node(self.y, "judge")["output_format"], role_schema("p2.diagnose"))

    def test_judge_ok_sample_passes_yaml_output_format(self):
        self.assertEqual(validate_schema(load("judge_ok"), find_node(self.y, "judge")["output_format"]), [])

    def test_signature(self):
        self.assertEqual(self.y["name"], "blk-judge")
        self.assertEqual(set(self.y["inputs"]), {"request", "base_rev"})
        self.assertIs(self.y["inputs"]["request"].get("required"), True)
        self.assertEqual(self.y["inputs"]["base_rev"].get("default"), "")   # Ruling R2
        self.assertEqual(self.y["returns"], "collect")
        self.assertEqual(self.y["outcome_field"], "ok")
        fmt = find_node(self.y, "collect")["output_format"]
        self.assertEqual(fmt["properties"], {
            "ok": {"type": "boolean"}, "open_units": {"type": "array", "items": {"type": "string"}},
            "need_fix": {"type": "boolean"},
            "judgment_file": {"type": "string"}, "one_shot": {"type": "string"}})
        self.assertEqual(sorted(fmt["required"]), ["judgment_file", "need_fix", "ok", "one_shot", "open_units"])

    def test_nodes_and_loop(self):
        ids = [n["id"] for n in self.y["nodes"]]
        self.assertEqual(ids, ["intake", "judge-loop", "collect"])
        intake = find_node(self.y, "intake")
        self.assertEqual(intake["script"], "intake")
        self.assertEqual(intake["with"], {"request": "$INPUTS.request"})
        g = find_node(self.y, "judge-loop")
        self.assertEqual(g["depends_on"], ["intake"])
        lg = g["loop_group"]
        self.assertEqual((lg["max_iterations"], lg["fresh_context"], lg["until_bash"]),
                         (3, False, "test $judge-accept.output.ok = true"))
        self.assertEqual([n["id"] for n in lg["nodes"]], ["judge", "judge-accept"])
        judge = find_node(self.y, "judge")
        self.assertEqual(judge["command"], "diagnose")
        self.assertEqual(judge["allowed_tools"], ["Read", "Grep", "Glob"])
        self.assertEqual(judge["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})
        self.assertEqual(judge["idle_timeout"], DEADLINE)
        acc = find_node(self.y, "judge-accept")
        self.assertEqual(acc["with"], {"reply": {"from": "$judge.output"}, "base_rev": "$INPUTS.base_rev"})
        self.assertEqual(sorted(acc["output_format"]["required"]), ["ok", "open_units", "reason"])
        self.assertEqual(find_node(self.y, "collect")["depends_on"], ["judge-loop"])

    def test_diagnose_prompt_wires_request_and_retry_reason(self):
        text = (BLK / "commands" / "diagnose.md").read_text(encoding="utf-8")
        for needle in ("$INPUTS.request", "$LOOP_PREV.judge-accept.output.reason", "one_shot_closes", "class_query",
                       "precedents", "searched", "questions", "反証"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        self.assertNotIn("{{", text, "engine の穴が残っている")

    def test_fixtures(self):
        want = {
            "pass": {"expect": "completed", "inputs": {"request": "request_ok.json"}},
            "bad-reply": {"expect": "failed", "fail-node": "collect"},
            "bad-request": {"expect": "failed", "fail-node": "intake", "inputs": {"request": "missing.json"}},
        }
        for name, decl in want.items():
            with self.subTest(name):
                f = yaml.safe_load((BLK / "fixtures" / f"{name}.stubs.yaml").read_text(encoding="utf-8"))
                self.assertIs(f["exec-code"], True)
                for k, v in decl.items():
                    self.assertEqual(f["fixture"][k], v)
        self.assertEqual(yaml.safe_load((BLK / "fixtures" / "pass.stubs.yaml").read_text(encoding="utf-8"))["judge"],
                         load("judge_ok"))
        self.assertEqual(yaml.safe_load((BLK / "fixtures" / "bad-reply.stubs.yaml").read_text(encoding="utf-8"))["judge"],
                         load("judge_notfound_no_searched"))

    def test_seed_has_request(self):
        # Ruling R1: 筋書きの依頼は種に置く（中身は返答の見本と同じ）
        self.assertEqual(json.loads((SEED / "request_ok.json").read_text(encoding="utf-8")), load("request_ok"))


class ScriptCase(unittest.TestCase):
    """スクリプトを別のプロセスで回す。cwd は種を写した使い捨ての git リポジトリ"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self._tmp.name)
        self.repo = tmp / "repo"
        shutil.copytree(SEED, self.repo)
        git(self.repo, "init", "-q")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "seed")
        self.art = tmp / "art"
        self.board = self.art / "board"

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, name, **env):
        e = dict(os.environ, ARTIFACTS_DIR=str(self.art), **env)
        return subprocess.run([sys.executable, str(BLK / "scripts" / f"{name}.py")], cwd=self.repo, env=e,
                              capture_output=True, text=True, timeout=300)

    # ---- intake
    def test_intake_accepts_request(self):
        r = self.run_script("intake", INPUTS_REQUEST="request_ok.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIs(json.loads(r.stdout)["ok"], True)
        batches = json.loads((self.board / "request.json").read_text(encoding="utf-8"))
        self.assertEqual(batches[0]["findings"], load("request_ok"))

    def test_intake_accepts_absolute_path_outside_repo(self):
        # 依頼は対象の外に置いて絶対パスで渡せる（Archon は run ごとの worktree を origin から切るので、
        # 対象の中の commit していない依頼はそこに無い）
        outside = pathlib.Path(self._tmp.name) / "outside" / "依頼.json"
        outside.parent.mkdir()
        shutil.copy(REPLIES / "request_ok.json", outside)
        r = self.run_script("intake", INPUTS_REQUEST=str(outside))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"ok": True, "reason": "", "request": str(outside)})
        batches = json.loads((self.board / "request.json").read_text(encoding="utf-8"))
        self.assertEqual(batches[0]["findings"], load("request_ok"))
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")   # 対象の作業ツリーは汚さない

    def test_intake_missing_file(self):
        r = self.run_script("intake", INPUTS_REQUEST="missing.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing.json", r.stderr)
        self.assertEqual(r.stderr.strip().count("\n"), 0, "理由は 1 行")

    def test_intake_invalid_json(self):
        (self.repo / "broken.json").write_text("{not json", encoding="utf-8")
        r = self.run_script("intake", INPUTS_REQUEST="broken.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("JSON", r.stderr)

    def test_intake_rejected_by_rules(self):
        shutil.copy(REPLIES / "request_extra_key.json", self.repo / "bad.json")
        r = self.run_script("intake", INPUTS_REQUEST="bad.json")
        self.assertEqual(r.returncode, 1)
        self.assertIn("severity", r.stderr)
        self.assertFalse((self.board / "request.json").exists())

    def test_intake_missing_env(self):
        r = self.run_script("intake")
        self.assertEqual(r.returncode, 2)
        self.assertIn("INPUTS_REQUEST", r.stderr)

    def test_intake_stores_judge_snapshot(self):
        r = self.run_script("intake", INPUTS_REQUEST="request_ok.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads((self.board / JUDGE_SNAPSHOT_FILE).read_text(encoding="utf-8")),
                         snapshot_tree(self.repo))

    # ---- accept
    def test_accept_good_and_bad_reply(self):
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST="request_ok.json").returncode, 0)
        r = self.run_script("accept", INPUTS_REPLY=json.dumps(load("judge_notfound_no_searched")), INPUTS_BASE_REV="")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertIs(got["ok"], False)
        self.assertIn("searched", got["reason"])
        r = self.run_script("accept", INPUTS_REPLY=json.dumps(load("judge_ok")), INPUTS_BASE_REV="")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertIs(got["ok"], True, got["reason"])
        self.assertTrue((self.board / "judgment.json").exists())

    def test_accept_passes_with_untracked_request_in_repo(self):
        # Ruling R14: 依頼のファイルが対象の中で未追跡でも、intake の時から作業ツリーが変わっていなければ通す
        shutil.copy(REPLIES / "request_ok.json", self.repo / "my_request.json")
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST="my_request.json").returncode, 0)
        r = self.run_script("accept", INPUTS_REPLY=json.dumps(load("judge_ok")), INPUTS_BASE_REV="")
        got = json.loads(r.stdout)
        self.assertIs(got["ok"], True, got["reason"])

    def test_accept_rejects_file_added_after_intake(self):
        shutil.copy(REPLIES / "request_ok.json", self.repo / "my_request.json")
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST="my_request.json").returncode, 0)
        (self.repo / "extra.txt").write_text("読むだけの役が書いた\n", encoding="utf-8")
        r = self.run_script("accept", INPUTS_REPLY=json.dumps(load("judge_ok")), INPUTS_BASE_REV="")
        got = json.loads(r.stdout)
        self.assertIs(got["ok"], False)
        self.assertIn("extra.txt", got["reason"])
        self.assertFalse((self.board / "judgment.json").exists())

    def test_accept_rejects_untracked_content_changed_after_intake(self):
        shutil.copy(REPLIES / "request_ok.json", self.repo / "my_request.json")
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST="my_request.json").returncode, 0)
        (self.repo / "my_request.json").write_text("[]\n", encoding="utf-8")   # 名前は同じで中身だけ変わる
        got = json.loads(self.run_script("accept", INPUTS_REPLY=json.dumps(load("judge_ok")), INPUTS_BASE_REV="").stdout)
        self.assertIs(got["ok"], False)

    def test_check_judge_without_snapshot_needs_clean_tree(self):
        # 写しが無いとき（intake を通らない呼び方）は今までどおり作業ツリーが綺麗であることを求める
        self.board.mkdir(parents=True)
        (self.repo / "extra.txt").write_text("x\n", encoding="utf-8")
        r = check_judge(load("judge_ok"), self.board, "", self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("extra.txt", r["reason"])

    # ---- collect
    def test_collect_builds_exit(self):
        self.board.mkdir(parents=True)
        (self.board / "judgment.json").write_text(json.dumps(load("judge_ok"), ensure_ascii=False), encoding="utf-8")
        r = self.run_script("collect")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(got, {
            "ok": True,
            "open_units": [u["key"] for u in load("judge_ok")["units"] if u["label"] == "block"],
            "need_fix": True,
            "judgment_file": str(self.board / "judgment.json"),
            "one_shot": load("judge_ok")["one_shot"],
        })
        self.assertEqual(validate_schema(got, find_node(workflow(), "collect")["output_format"]), [])

    def test_collect_no_fix_needed(self):
        # Ruling R21: 直す義務の残る単位が 1 つも無ければ need_fix: false（ラインは修正から後を飛ばす）
        self.board.mkdir(parents=True)
        (self.board / "judgment.json").write_text(json.dumps(load("judge_no_fix"), ensure_ascii=False),
                                                  encoding="utf-8")
        r = self.run_script("collect")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual((got["open_units"], got["need_fix"]), ([], False))
        self.assertEqual(validate_schema(got, find_node(workflow(), "collect")["output_format"]), [])

    def test_no_fix_sample_is_accepted(self):
        # 見本 judge_no_fix（依頼の件は再現しない）は受け付けを通り、open_units が空になる
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST="request_ok.json").returncode, 0)
        r = self.run_script("accept", INPUTS_REPLY=json.dumps(load("judge_no_fix")), INPUTS_BASE_REV="")
        got = json.loads(r.stdout)
        self.assertIs(got["ok"], True, got["reason"])
        self.assertEqual(got["open_units"], [])

    def test_collect_without_judgment(self):
        r = self.run_script("collect")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("judgment.json", r.stderr)


if __name__ == "__main__":
    unittest.main()
