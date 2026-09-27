"""前提の実測のブロック（blk-premises）の検査。graphloops の節 p0.premises を works のブロックにした物。

- YAML の口: 実測役の節の output_format が graph の型（role_schema("p0.premises")）と同じか、良い返答の見本が通るか。
  入口・出口・輪の形。実測役は測るために Bash を持つが、Edit・Write は持たない
- 受け付け（premises.check_premises）: 型 → 写した規則の post_check（graph の節が名指す measured_needs_output）。
  依頼を受け付けた時から作業ツリーが変わっていれば拒む（実測役は Bash を持つが、作業ツリーは変えない約束）
- つなぎのスクリプト: intake（依頼の型を確かめ、作業ツリーの写しを置く。盤面の request.json は書かない）・
  accept（check_premises を script_io で包む）・collect（盤面の premises.json から出口を組む）を別のプロセスで回す
- 筋書き（fixtures/）が 3 本在り、期待の形がブリーフどおりか。Archon で回すのは dev/check.sh（workflow test）
- ラインに入れる時（線 A）の id の決まり（Ruling R17・stub の鍵の一意）を今のラインと他のブロックに対して先に見る
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
BLK = ROOT / "blk-premises"
CORE = ROOT / ".shared" / "core"
REPLIES = pathlib.Path(__file__).resolve().parent / "replies"
SEED = ROOT / "dev" / "target-seed"
sys.path.insert(0, str(CORE))

from accept import role_schema, snapshot_tree  # noqa: E402
from board import graph_expanded  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
import premises  # noqa: E402
from premises import PREMISES_FILE, PREMISES_NODE, PREMISES_SNAPSHOT_FILE, check_premises  # noqa: E402

DEADLINE = 1728000000
INCLUDE_ID = "premising"   # 線 A がラインで使う include の id（Ruling R17。ブロックの中の節の id と重ねない）
GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


def load(name):
    return json.loads((REPLIES / f"{name}.json").read_text(encoding="utf-8"))


def workflow():
    return yaml.safe_load((BLK / "blk-premises.yaml").read_text(encoding="utf-8"))


def find_node(y, nid):
    """節を id で引く。loop_group の中の節も辿る"""
    for n in y.get("nodes") or []:
        if n.get("id") == nid:
            return n
        for m in (n.get("loop_group") or {}).get("nodes") or []:
            if m.get("id") == nid:
                return m
    raise AssertionError(f"節 {nid} が無い")


def git(repo, *args):
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, check=True).stdout


class YamlCase(unittest.TestCase):
    def setUp(self):
        self.y = workflow()

    def test_output_format_matches_role_schema(self):
        self.assertEqual(find_node(self.y, "premises")["output_format"], role_schema(PREMISES_NODE))

    def test_ok_sample_passes_yaml_output_format(self):
        fmt = find_node(self.y, "premises")["output_format"]
        self.assertEqual(validate_schema(load("premises_ok"), fmt), [])
        # 実測なのに出力の無い返答も型は通る（拒むのは型でなく写した規則。受け付けの試験が見る）
        self.assertEqual(validate_schema(load("premises_no_output"), fmt), [])

    def test_graph_node_names_the_rule(self):
        # 受け付けは graph の節が名指す post_check を引く。名前が変われば写し直しで気づくように、今の名前を固める
        self.assertEqual(graph_expanded()["nodes"][PREMISES_NODE]["post_check"], "measured_needs_output")

    def test_signature(self):
        self.assertEqual(self.y["name"], "blk-premises")
        self.assertEqual(set(self.y["inputs"]), {"request", "base_rev"})
        self.assertIs(self.y["inputs"]["request"].get("required"), True)
        self.assertEqual(self.y["inputs"]["base_rev"].get("default"), "")   # Ruling R2
        self.assertEqual(self.y["returns"], "collect")
        self.assertEqual(self.y["outcome_field"], "ok")
        fmt = find_node(self.y, "collect")["output_format"]
        v1 = {"ok": {"type": "boolean"}, "constraints_file": {"type": "string"}, "constraints_summary": {"type": "string"}}
        self.assertEqual({k: fmt["properties"][k] for k in v1}, v1)   # v1 の欄は全部残す（出口の約束）
        added = {"premises_file": "string", "constraints": "integer", "measured": "integer", "hypotheses": "integer",
                 "claims": "integer", "claims_hypothesis": "integer", "reads_file": "string"}   # 計画 P1 Task 24 の collect
        self.assertEqual(fmt["properties"], {**v1, **{k: {"type": t} for k, t in added.items()}})
        self.assertEqual(set(fmt["required"]), set(v1) | set(added))

    def test_nodes_and_loop(self):
        self.assertEqual([n["id"] for n in self.y["nodes"]], ["intake", "premises-loop", "collect"])
        intake = find_node(self.y, "intake")
        self.assertEqual((intake["script"], intake["with"]), ("intake", {"request": "$INPUTS.request"}))
        g = find_node(self.y, "premises-loop")
        self.assertEqual(g["depends_on"], ["intake"])
        lg = g["loop_group"]
        self.assertEqual((lg["max_iterations"], lg["fresh_context"], lg["until_bash"]),
                         (3, False, "test $premises-accept.output.ok = true"))
        self.assertEqual([n["id"] for n in lg["nodes"]], ["premises", "premises-accept"])
        role = find_node(self.y, "premises")
        self.assertEqual(role["command"], "premises")
        # 測るためにコマンドを走らせる（graphloops では writer が回す節）。書く道具は持たない
        self.assertEqual(role["allowed_tools"], ["Read", "Grep", "Glob", "Bash"])
        self.assertEqual(role["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})
        self.assertEqual(role["settingSources"], [])
        self.assertEqual(role["idle_timeout"], DEADLINE)
        self.assertNotIn("model", role)
        acc = find_node(self.y, "premises-accept")
        self.assertEqual(acc["with"], {"reply": {"from": "$premises.output"}, "base_rev": "$INPUTS.base_rev"})
        self.assertEqual(acc["depends_on"], ["premises"])
        self.assertEqual(sorted(acc["output_format"]["required"]), ["constraints_file", "ok", "reason", "reason_file"])
        self.assertEqual(find_node(self.y, "collect")["depends_on"], ["premises-loop"])

    def test_prompt_measures_request_claims(self):
        """依頼の measured の測り直しの段落（where をそのまま text に・測れなければ仮説）と、本線 a1202d0 の指示書の本文を全部含む。
        拒んだ理由はファイルのパスで届く（R44。$LOOP_PREV で本文を貼らない）"""
        text = (BLK / "commands" / "premises.md").read_text(encoding="utf-8")
        for needle in ("`measured`", "`where` をそのまま", "`kind: 仮説`", "$LOOP_PREV.premises-accept.output.reason_file"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        self.assertNotIn("$LOOP_PREV.premises-accept.output.reason\n", text + "\n")
        self.assertNotRegex(text, r"\$LOOP_PREV\.premises-accept\.output\.reason(?!_file)")
        src = subprocess.run(["git", "-C", str(ROOT), "show", "a1202d0:graphloops/prompts/review-loop/p0.premises.md"],
                             capture_output=True, text=True)
        if src.returncode != 0:
            self.skipTest("このリポジトリから a1202d0 を引けない（浅い clone か、graphloops の履歴を持たない）")
        body = [ln for ln in src.stdout.splitlines() if ln.strip() and "{{" not in ln]
        self.assertTrue(body)
        for ln in body:
            with self.subTest(ln[:30]):
                self.assertIn(ln, text)

    def test_prompt_wires_request_retry_and_incidents(self):
        text = (BLK / "commands" / "premises.md").read_text(encoding="utf-8")
        for needle in ("$INPUTS.request", "$LOOP_PREV.premises-accept.output.reason", "measured_output", "measured_how",
                       "`measured`", "実測", "仮説",
                       # graphloops の指示書の実例（2 件とも残す）
                       "4MB", "5,411 バイト", ".github/workflows/test.yml"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        self.assertNotIn("{{", text, "engine の穴が残っている")

    def test_fixtures(self):
        want = {
            "pass": {"expect": "completed", "inputs": {"request": "request_ok.json"},
                     "reached": ["intake", "premises", "premises-accept", "collect"]},
            "bad-reply": {"expect": "failed", "fail-node": "collect", "inputs": {"request": "request_ok.json"}},
            "bad-request": {"expect": "failed", "fail-node": "intake", "inputs": {"request": "missing.json"}},
        }
        for name, decl in want.items():
            with self.subTest(name):
                f = yaml.safe_load((BLK / "fixtures" / f"{name}.stubs.yaml").read_text(encoding="utf-8"))
                self.assertIs(f["exec-code"], True)
                for k, v in decl.items():
                    self.assertEqual(f["fixture"][k], v)
        fx = lambda n: yaml.safe_load((BLK / "fixtures" / f"{n}.stubs.yaml").read_text(encoding="utf-8"))  # noqa: E731
        self.assertEqual(fx("pass")["premises"], load("premises_ok"))
        self.assertEqual(fx("bad-reply")["premises"], load("premises_no_output"))


class LineIdsCase(unittest.TestCase):
    """線 A がこのブロックをラインに include する時の決まりを、今のラインと他のブロックに対して先に見る
    （ラインへの配線は線 A の Task 17。ここでは足さない）"""

    def setUp(self):
        self.y = workflow()
        self.line = yaml.safe_load((ROOT / "darkfactory" / "darkfactory.yaml").read_text(encoding="utf-8"))
        self.top = {n["id"] for n in self.y["nodes"]}
        self.inner = {m["id"] for n in self.y["nodes"] for m in (n.get("loop_group") or {}).get("nodes") or []}

    def test_include_id_does_not_collide(self):
        # Ruling R17: include の id がブロックの中の節の id と同じだと、ブロックの中の $<id>.output が include を指す
        line_ids = {n["id"] for n in self.line["nodes"]} | {INCLUDE_ID}
        self.assertEqual(line_ids & (self.top | self.inner), set())

    def test_loop_ids_unique_across_line(self):
        # 模擬実行は輪の中の節を名前空間の付かない id で stub に引く（tests/test_line.py の stub_keys）
        others = set()
        for n in self.line["nodes"]:
            if "include" in n:
                b = yaml.safe_load((ROOT / n["include"] / f"{n['include']}.yaml").read_text(encoding="utf-8"))
                others |= {m["id"] for x in b["nodes"] for m in (x.get("loop_group") or {}).get("nodes") or []}
            else:
                others.add(n["id"])
        self.assertEqual(self.inner & others, set())


class RepoCase(unittest.TestCase):
    """cwd は種を写した使い捨ての git リポジトリ"""

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
        # 子の環境は節の INPUTS_* と ARTIFACTS_DIR を継がせずに作る（Archon の節の中で回しても入力欠けの試験が同じに振る舞う）
        base = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_") and k != "ARTIFACTS_DIR"}
        e = {**base, "ARTIFACTS_DIR": str(self.art), **env}
        return subprocess.run([sys.executable, str(BLK / "scripts" / f"{name}.py")], cwd=self.repo, env=e,
                              capture_output=True, text=True, timeout=300)

    def snapshot(self):
        self.board.mkdir(parents=True, exist_ok=True)
        (self.board / PREMISES_SNAPSHOT_FILE).write_text(json.dumps(snapshot_tree(self.repo)), encoding="utf-8")


class CheckCase(RepoCase):
    def test_accepts_good_reply(self):
        self.snapshot()
        r = check_premises(load("premises_ok"), self.board, "", self.repo)
        self.assertIs(r["ok"], True, r["reason"])
        self.assertEqual(r["constraints_file"], str(self.board / PREMISES_FILE))
        self.assertEqual(json.loads((self.board / PREMISES_FILE).read_text(encoding="utf-8")), load("premises_ok"))

    def test_measured_without_output_rejected_by_copied_rule(self):
        # 拒否の文は写した規則（rules/review-loop.py の measured_needs_output）がそのまま出す物
        self.snapshot()
        r = check_premises(load("premises_no_output"), self.board, "", self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("p0.premises: kind=実測 なのに measured_output（実行したコマンドと出力）が無い制約がある", r["reason"])
        self.assertIn("kind=仮説 に落とせ", r["reason"])
        self.assertEqual(r["constraints_file"], "")
        self.assertFalse((self.board / PREMISES_FILE).exists())

    def test_blank_output_rejected(self):
        # 空白だけの measured_output も通さない（engine の型の検査が strip して minLength で拒む。規則も strip して拒む）
        self.snapshot()
        reply = {"constraints": [{"text": "x", "measured_how": "y", "kind": "実測", "measured_output": "  \n"}]}
        r = check_premises(reply, self.board, "", self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("measured_output", r["reason"])

    def test_hypothesis_needs_no_output_and_empty_is_ok(self):
        self.snapshot()
        for reply in ({"constraints": [{"text": "x", "measured_how": "測れない", "kind": "仮説"}]}, {"constraints": []}):
            with self.subTest(reply):
                self.assertIs(check_premises(reply, self.board, "", self.repo)["ok"], True)

    def test_type_error(self):
        self.snapshot()
        r = check_premises({"constraints": [{"text": "x", "measured_how": "y", "kind": "推測"}]}, self.board, "", self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("型", r["reason"])

    def test_rejects_tree_changed_after_intake(self):
        self.snapshot()
        (self.repo / "measure.log").write_text("測った出力を作業ツリーに書いた\n", encoding="utf-8")
        r = check_premises(load("premises_ok"), self.board, "", self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("measure.log", r["reason"])
        self.assertFalse((self.board / PREMISES_FILE).exists())

    def test_rejects_commit_after_intake(self):
        # 実測役は Bash を持つ。作った物を commit すると HEAD 相対の porcelain と差分は元に戻るが、写しの head で見える
        self.snapshot()
        (self.repo / "measure.log").write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "役が commit した")
        self.assertEqual(git(self.repo, "status", "--porcelain"), "")
        r = check_premises(load("premises_ok"), self.board, "", self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("HEAD が動いた", r["reason"])
        self.assertFalse((self.board / PREMISES_FILE).exists())

    def test_without_snapshot_rejects_head_moved_from_base_rev(self):
        base = git(self.repo, "rev-parse", "HEAD").strip()
        self.board.mkdir(parents=True)
        (self.repo / "measure.log").write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "役が commit した")
        r = check_premises(load("premises_ok"), self.board, base, self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("HEAD", r["reason"])

    def test_bytecode_not_counted_without_gitignore(self):
        # 対象の .gitignore が __pycache__/ と *.pyc を除いていなくても、測るために試験を回して出来たバイトコードでは拒まない
        # （修正の差分の側の _is_bytecode と同じ定義）
        (self.repo / ".gitignore").unlink()
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "no gitignore")
        self.snapshot()
        (self.repo / "__pycache__").mkdir()
        (self.repo / "__pycache__" / "stats.cpython-312.pyc").write_bytes(b"\0bytecode")
        (self.repo / "loose.pyc").write_bytes(b"\0bytecode")
        self.assertIn("pyc", git(self.repo, "status", "--porcelain", "--untracked-files=all"))
        r = check_premises(load("premises_ok"), self.board, "", self.repo)
        self.assertIs(r["ok"], True, r["reason"])
        self.board.joinpath(PREMISES_SNAPSHOT_FILE).unlink()   # 写しが無い時の分岐も同じ
        self.assertIs(check_premises(load("premises_ok"), self.board, "", self.repo)["ok"], True)

    def test_old_snapshot_without_head_rejected(self):
        self.board.mkdir(parents=True)
        snap = snapshot_tree(self.repo)
        del snap["head"]
        (self.board / PREMISES_SNAPSHOT_FILE).write_text(json.dumps(snap), encoding="utf-8")
        r = check_premises(load("premises_ok"), self.board, "", self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("取り直せ", r["reason"])

    def test_without_snapshot_needs_clean_tree(self):
        self.board.mkdir(parents=True)
        (self.repo / "extra.txt").write_text("x\n", encoding="utf-8")
        r = check_premises(load("premises_ok"), self.board, "", self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("extra.txt", r["reason"])

    def test_bad_base_rev(self):
        self.snapshot()
        r = check_premises(load("premises_ok"), self.board, "no-such-rev", self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("no-such-rev", r["reason"])


class ScriptCase(RepoCase):
    # ---- intake
    def test_intake_checks_request_and_stores_snapshot(self):
        r = self.run_script("intake", INPUTS_REQUEST="request_ok.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"ok": True, "reason": "", "request": "request_ok.json"})
        self.assertEqual(json.loads((self.board / PREMISES_SNAPSHOT_FILE).read_text(encoding="utf-8")),
                         snapshot_tree(self.repo))
        # 依頼を盤面に積むのは判定のブロックの intake だけ（ここで積むと判定の時に同じ依頼が 2 度積まれる）
        self.assertFalse((self.board / "request.json").exists())

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
        self.assertFalse((self.board / PREMISES_SNAPSHOT_FILE).exists())

    def test_intake_missing_env(self):
        r = self.run_script("intake")
        self.assertEqual(r.returncode, 2)
        self.assertIn("INPUTS_REQUEST", r.stderr)

    # ---- accept
    def test_accept_bad_then_good(self):
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST="request_ok.json").returncode, 0)
        r = self.run_script("accept", INPUTS_REPLY=json.dumps(load("premises_no_output")), INPUTS_BASE_REV="")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertIs(got["ok"], False)
        self.assertIn("measured_output", got["reason"])
        r = self.run_script("accept", INPUTS_REPLY=json.dumps(load("premises_ok")), INPUTS_BASE_REV="")
        got = json.loads(r.stdout)
        self.assertIs(got["ok"], True, got["reason"])
        self.assertEqual(validate_schema(got, find_node(workflow(), "premises-accept")["output_format"]), [])
        self.assertTrue((self.board / PREMISES_FILE).exists())

    def test_stale_premises_not_collected_after_rejected_loop(self):
        # 同じ盤面で 2 度目に回し、この回の受け付けが全部拒んだら、前の呼び出しの premises.json を拾わずに collect が落ちる
        self.board.mkdir(parents=True)
        (self.board / PREMISES_FILE).write_text(json.dumps(load("premises_ok"), ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST="request_ok.json").returncode, 0)
        self.assertFalse((self.board / PREMISES_FILE).exists())
        for _ in range(3):
            got = json.loads(self.run_script("accept", INPUTS_REPLY=json.dumps(load("premises_no_output")), INPUTS_BASE_REV="").stdout)
            self.assertIs(got["ok"], False)
        r = self.run_script("collect")
        self.assertEqual(r.returncode, 1)
        self.assertIn(PREMISES_FILE, r.stderr)

    # ---- 依頼の実測の測り直し（計画 P1 Task 24・仕様 3.6。works だけの検査 check_claims）
    CLAIM = {"where": "test_stats.py:12", "text": "本番の入力で 3 件に 1 件が赤になる", "measured": "3 件に 1 件が赤"}

    def claim_request(self):
        """measured の行を 1 本持つ依頼（対象の外のファイル。絶対パス）"""
        path = self.art.parent / "claims.json"
        rows = [{"where": "stats.py", "text": "mean([1, 2, 3]) が 2 でなく 3 を返す。test_mean_of_three が赤"}, self.CLAIM]
        path.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        return str(path)

    def test_claims_picks_measured_rows(self):
        items = [{"where": "a.py", "text": "x"}, {"where": "b.py:3", "text": "y", "measured": "5 件"}]
        self.assertEqual(premises.claims(items), [{"where": "b.py:3", "measured": "5 件"}])

    def test_request_claim_missing_rejected(self):
        """measured の行が在るのに where を含む制約が無い → ok False、reason（と reason_file）に where と直し方"""
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST=self.claim_request()).returncode, 0)
        r = self.run_script("accept", INPUTS_REPLY=json.dumps(load("premises_claim_missing")), INPUTS_BASE_REV="")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertIs(got["ok"], False)
        for want in ("依頼の実測を測り直した制約が無い", "test_stats.py:12", "text に where をそのまま入れよ"):
            self.assertIn(want, got["reason"])
        self.assertEqual(pathlib.Path(got["reason_file"]).read_text(encoding="utf-8"), got["reason"])
        self.assertFalse((self.board / PREMISES_FILE).exists())

    def test_request_claim_hypothesis_passes(self):
        """測り直せず kind 仮説にした行（text に where）→ ok、collect の claims 1・claims_hypothesis 1"""
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST=self.claim_request()).returncode, 0)
        r = self.run_script("accept", INPUTS_REPLY=json.dumps(load("premises_claim_hypothesis")), INPUTS_BASE_REV="")
        got = json.loads(r.stdout)
        self.assertIs(got["ok"], True, got["reason"])
        out = json.loads(self.run_script("collect").stdout)
        self.assertEqual(validate_schema(out, find_node(workflow(), "collect")["output_format"]), [])
        self.assertEqual({k: out[k] for k in ("constraints", "measured", "hypotheses", "claims", "claims_hypothesis")},
                         {"constraints": 2, "measured": 1, "hypotheses": 1, "claims": 1, "claims_hypothesis": 1})
        self.assertEqual(out["premises_file"], str(self.board / PREMISES_FILE))

    def test_accept_without_request_copy_rejected(self):
        """intake を通らない（依頼の控えが無い）受け付けは、依頼の実測を確かめられないので拒む（fail closed）"""
        self.board.mkdir(parents=True)
        got = json.loads(self.run_script("accept", INPUTS_REPLY=json.dumps(load("premises_ok")), INPUTS_BASE_REV="").stdout)
        self.assertIs(got["ok"], False)
        self.assertIn(premises.PREMISES_REQUEST_FILE, got["reason"])

    # ---- collect
    def test_collect_builds_exit(self):
        self.board.mkdir(parents=True)
        (self.board / PREMISES_FILE).write_text(json.dumps(load("premises_ok"), ensure_ascii=False), encoding="utf-8")
        r = self.run_script("collect")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertEqual(validate_schema(got, find_node(workflow(), "collect")["output_format"]), [])
        self.assertEqual((got["ok"], got["constraints_file"]), (True, str(self.board / PREMISES_FILE)))
        lines = got["constraints_summary"].splitlines()
        self.assertEqual(len(lines), 3)
        self.assertTrue(lines[0].startswith("- [実測] stats.py の mean は"), lines[0])
        self.assertTrue(lines[2].startswith("- [仮説] clamp は"), lines[2])
        self.assertIn("測り方: ", lines[2])

    def test_collect_no_constraints(self):
        self.board.mkdir(parents=True)
        (self.board / PREMISES_FILE).write_text('{"constraints": []}', encoding="utf-8")
        got = json.loads(self.run_script("collect").stdout)
        self.assertEqual(got["constraints_summary"], "（測る数値・事実の主張は依頼に無かった。制約 0 件）")

    def test_collect_without_file_fails(self):
        r = self.run_script("collect")
        self.assertEqual(r.returncode, 1)
        self.assertIn(PREMISES_FILE, r.stderr)

    def test_collect_broken_shape_fails(self):
        self.board.mkdir(parents=True)
        (self.board / PREMISES_FILE).write_text('{"constraints": [{"text": "x"}]}', encoding="utf-8")
        r = self.run_script("collect")
        self.assertEqual(r.returncode, 1)
        self.assertIn("形", r.stderr)

    def test_collect_missing_env(self):
        e = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_") and k != "ARTIFACTS_DIR"}
        r = subprocess.run([sys.executable, str(BLK / "scripts" / "collect.py")], cwd=self.repo, env=e,
                           capture_output=True, text=True, timeout=300)
        self.assertEqual(r.returncode, 2)
        self.assertIn("ARTIFACTS_DIR", r.stderr)


if __name__ == "__main__":
    unittest.main()
