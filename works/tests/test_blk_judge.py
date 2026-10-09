"""判定のブロック（blk-judge）の検査。

- YAML の口: 判定役の節の output_format が受け付けの規則の型（role_schema("p2.diagnose")）と同じか、良い返答の見本が
  YAML の output_format を通るか（設計書 5.4 節）。入口・出口・輪の形がブリーフどおりか
- つなぎのスクリプト: intake（依頼を読んで check_request。拒めば終了コード 1）・accept（単独の run は core の check_judge を
  script_io で包み、ラインの盤面は judgetake.take を rolekit.main_accept に渡す）・collect（盤面の judgment.json から出口を組む）を
  別のプロセスで回す
- class_query の例（QueryExamplesCase）: 当たるべき hits・当たってはならない misses で問いを試し、合わなければ拒み、通れば
  例を judgment.json に戻す（querytest。受け付けの口の中で試す）
- 筋書き（fixtures/）が 3 本在り、期待の形がブリーフどおりか。Archon で回すのは dev/check.sh（workflow test）
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
BLK = ROOT / "blk-judge"
CORE = ROOT / ".shared" / "core"
REPLIES = pathlib.Path(__file__).resolve().parent / "replies"
SEED = ROOT / "dev" / "target-seed"
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(BLK / "lib"))

from accept import JUDGE_SNAPSHOT_FILE, check_judge, role_schema, tree_state  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
from gitkit import committed_copy, git  # noqa: E402
from node_marker import strip  # noqa: E402

DEADLINE = 1728000000


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


class YamlCase(unittest.TestCase):
    def setUp(self):
        self.y = workflow()

    def test_judge_output_format_matches_role_schema(self):
        # 一番上の description は節の印（works-node: judge）。外すと graph の schema と同じ（裁定 TA20）
        self.assertEqual(strip(find_node(self.y, "judge")["output_format"]), role_schema("p2.diagnose"))

    def test_judge_ok_sample_passes_yaml_output_format(self):
        self.assertEqual(validate_schema(load("judge_ok"), find_node(self.y, "judge")["output_format"]), [])

    def test_signature(self):
        self.assertEqual(self.y["name"], "blk-judge")
        self.assertEqual(set(self.y["inputs"]), {"request", "base_rev", "policy_paste", "premises_file", "verify"})   # policy_paste・premises_file は tests/test_policy.py が見る
        self.assertEqual(self.y["inputs"]["verify"].get("default"), "")   # 裏取りの切り替え（空は on＝今どおり）
        self.assertEqual((self.y["inputs"]["request"].get("required"), self.y["inputs"]["request"].get("default")), (None, ""))
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
        self.assertEqual(ids, ["intake", "judge-brief", "judge-loop", "verify-prep", "judge-verify", "verify-merge", "collect"])
        intake = find_node(self.y, "intake")
        self.assertEqual(intake["script"], "intake")
        self.assertEqual(intake["with"], {"request": "$INPUTS.request"})
        brief = find_node(self.y, "judge-brief")
        self.assertEqual((brief["script"], brief["depends_on"], brief["timeout"]), ("brief", ["intake"], DEADLINE))
        self.assertNotIn("with", brief)   # 読むのは盤面だけ（INPUTS を読まない）
        self.assertEqual(sorted(brief["output_format"]["required"]), ["go", "materials_file", "ok"])
        g = find_node(self.y, "judge-loop")
        self.assertEqual(g["depends_on"], ["judge-brief"])
        # 止まった盤面（同じ境の節の後ろの素材集めが止めた。run 30）では支度が go 偽を出し、判定役を起こさない
        self.assertEqual(g["when"], "$judge-brief.output.go == true")
        lg = g["loop_group"]
        self.assertEqual((lg["max_iterations"], lg["fresh_context"], lg["until_bash"]),
                         (3, False, "test $judge-accept.output.done = true"))   # 通った時か 3 回目の拒否で抜ける（R50）
        self.assertEqual([n["id"] for n in lg["nodes"]], ["judge", "judge-accept"])
        judge = find_node(self.y, "judge")
        self.assertEqual(judge["command"], "diagnose")
        self.assertEqual(judge["allowed_tools"], ["Read", "Grep", "Glob", "WebSearch", "WebFetch"])
        self.assertEqual(judge["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})
        self.assertEqual(judge["idle_timeout"], DEADLINE)
        acc = find_node(self.y, "judge-accept")
        self.assertEqual(acc["with"], {"reply": {"from": "$judge.output"}, "base_rev": "$INPUTS.base_rev"})
        self.assertEqual(sorted(acc["output_format"]["required"]), ["done", "ok", "open_units", "reason", "reason_file"])
        col = find_node(self.y, "collect")
        # 裏取りのまとめを待つ。まとめが飛んでも（束ね役が落ちた・単位が 2 つ未満）走る（飛んだ依存は落ちに数えない）
        self.assertEqual((col["depends_on"], col["trigger_rule"]),
                         (["judge-brief", "judge-loop", "verify-merge"], "none_failed_min_one_success"))

    def test_verify_nodes(self):
        """判定の根を開く（線の木の段 3。設計 docs/plans/2026-10-06-judge-verify.md）: 支度（機械）→ 束ね役（opus・effort high。
        下請けを Agent で並べ、下請けは答えを盤面の外に Write。作業ツリーは書かない）→ まとめ（機械。束ね役が通った時だけ）"""
        import judgeverify
        prep = find_node(self.y, "verify-prep")
        self.assertEqual((prep["script"], prep["runtime"], prep["timeout"]), ("verify", "uv", DEADLINE))
        self.assertEqual((prep["depends_on"], prep["trigger_rule"]), (["judge-brief", "judge-loop"], "none_failed_min_one_success"))
        self.assertEqual(prep["with"], {"stage": "prep", "verify": "$INPUTS.verify"})
        self.assertEqual(sorted(prep["output_format"]["required"]), ["go", "ok", "prompt_file"])
        ai = find_node(self.y, "judge-verify")
        self.assertEqual((ai["model"], ai["effort"]), ("opus", "high"))
        self.assertEqual(ai["depends_on"], ["verify-prep"])
        self.assertEqual(ai["when"], "$verify-prep.output.go == true")
        self.assertEqual(ai["context"], "fresh", "判定役の会話を継がない（別の目）")
        self.assertIn("$verify-prep.output.prompt_file", ai["prompt"])
        self.assertEqual(ai["allowed_tools"], ["Read", "Grep", "Glob", "WebSearch", "WebFetch", "Agent", "Write"])
        self.assertIs(ai["mutates_checkout"], False)
        self.assertEqual(ai["settingSources"], ["user"])
        self.assertEqual(ai["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})
        self.assertEqual(ai["idle_timeout"], DEADLINE)
        self.assertEqual(ai["output_format"], judgeverify.output_format())
        self.assertEqual(ai["output_format"]["description"], "works-node: judge-verify")
        merge = find_node(self.y, "verify-merge")
        self.assertEqual((merge["script"], merge["depends_on"], merge["with"]),
                         ("verify", ["judge-verify"], {"stage": "merge", "verify": "$INPUTS.verify"}))
        self.assertNotIn("trigger_rule", merge, "束ね役が通った時だけまとめる（落ちたら支度の置いた初めの申し送りが残る）")
        self.assertEqual(sorted(merge["output_format"]["required"]), ["ok", "unverified", "verified", "verify_file"])

    def test_verify_script_inputs(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_verify_script", BLK / "scripts" / "verify.py")
        mod = importlib.util.module_from_spec(spec)
        dont = sys.dont_write_bytecode
        sys.dont_write_bytecode = True
        try:
            spec.loader.exec_module(mod)
        finally:
            sys.dont_write_bytecode = dont
        self.assertEqual(mod.INPUTS, ("INPUTS_STAGE", "INPUTS_VERIFY"))
        self.assertEqual(mod.OPTIONAL, frozenset({"INPUTS_VERIFY"}))   # 前の版の with: で再開した run は渡さない（無いのは on）

    def test_manifest_declares_notes(self):
        m = json.loads((BLK / "manifest.json").read_text(encoding="utf-8"))
        row = next(p for p in m["produces"] if p["name"] == "judge-verify.json")
        self.assertEqual((row["format"], row.get("at", "round")), ("json", "round"))
        self.assertTrue((BLK / row["schema"]).is_file())

    def test_diagnose_prompt_wires_request_and_retry_reason(self):
        text = (BLK / "commands" / "diagnose.md").read_text(encoding="utf-8")
        for needle in ("$INPUTS.request", "$LOOP_PREV.judge-accept.output.reason_file", "$judge-brief.output.materials_file",
                       "materials_missing", "one_shot_closes", "class_query",
                       "precedents", "searched", "questions", "反証"):
            with self.subTest(needle):
                self.assertIn(needle, text)
        # 理由の本文は貼らない（Archon は $LOOP_PREV で貼った中身をもう一度置き換えに通す）。パスだけを貼って Read させる
        self.assertEqual(re.findall(r"\$LOOP_PREV\.[\w.-]*", text), ["$LOOP_PREV.judge-accept.output.reason_file"])
        self.assertNotIn("{{", text, "engine の穴が残っている")
        # 素材を読む判定は、欠けた素材を materials_missing で名指す（本線の p2.diagnose と同じ。空の決め打ちにしない）
        self.assertNotIn("`materials_missing` と `carried_r1` は空の配列にせよ", text)

    def test_diagnose_prompt_population_counts_only_what_the_fix_changes(self):
        """population の問いの当たりは修正が変える物だけ（閉鎖は当たりを全部覆ったかで決まる。blk-fix/lib/unitrows.py）。
        canary の large の run a2fcf33a: 『docstring が無い』単位の問いを公開関数の全部（14 本。うち 12 本はもう正しい）にして、
        正しい直しが閉じずに round_limit になった。b44c480f は欠けた 2 つの def を名指して閉じた"""
        text = (BLK / "commands" / "diagnose.md").read_text(encoding="utf-8")
        item6 = text[text.index("\n6. "):text.index("\n7. ")]
        for needle in ("当たりは 1 件残らず修正が変える物", "もう正しい物", "正しく直しても閉じない", "欠けている物そのもの"):
            with self.subTest(needle):
                self.assertIn(needle, item6)

    def test_proposed_means_not_counted_as_prior_decision(self):
        """依頼と目的の文が示した解き方は人の前の決定に数えない（工場が疑う案）。世界の解の決め手は材料の世界の解の行を先に使い、
        先例の行は world:<類の id> で引く（計画 world-solution の W8・5.3 節の 2）"""
        text = (BLK / "commands" / "diagnose.md").read_text(encoding="utf-8")
        item7 = text[text.index("\n7. "):text.index("\n8. ")]
        item8 = text[text.index("\n8. "):text.index("\n9. ")]
        self.assertIn("依頼と目的の文が示した解き方は、人の前の決定に数えない", item7)
        self.assertIn("世界の解の行", item7)
        self.assertIn("world:<類の id>", item8)
        self.assertIn("世界の解の行", item8)

    def test_diagnose_prompt_decides_before_asking(self):
        """人に問う前に自分で決める（持ち主 2026-09-29）: 7 項は決め手に人の前の決定・人の方針・対象の同じ場面・世界の解を並べ、
        人に問うのを 3 つの場合に限り、fork の reason に推しを書かせる。8 項の undecided_because はその 3 つのどれかを名指させる"""
        text = (BLK / "commands" / "diagnose.md").read_text(encoding="utf-8")
        item7 = text[text.index("\n7. "):text.index("\n8. ")]
        item8 = text[text.index("\n8. "):text.index("\n9. ")]
        for needle in ("人の前の決定", "人の方針", "対象の同じ場面", "世界の解", "人に問う（fork・escalate）のは次の 3 つの場合だけ",
                       "先例が割れる", "優先の付け方", "前の決定か方針の文書とぶつかる", "推し: <選択肢>——<理由>"):
            with self.subTest(needle):
                self.assertIn(needle, item7)
        self.assertIn("3 つの場合", item8)
        self.assertIn("書けないなら自明なので人に回すな", item8)

    def test_diagnose_prompt_cuts_units_at_the_code_level(self):
        """単位の粒はコードの上の欠陥の形（canary の large の run a2fcf33a: 3 つのファイルの別々の式の誤りを、上方展開の上の段の
        「テストが分かれ目を試さない」で 1 単位に束ね、b44c480f は同じ指示書で 3 単位に分けた）。上の段で交わる原因は束ねる
        理由にせず framing・why_chain・一撃に書く。同じ形の別の現れ・1 つの直しで閉じる物だけを束ねる。根の深さ（3 項の
        上方展開）は削らない"""
        text = (BLK / "commands" / "diagnose.md").read_text(encoding="utf-8")
        cross = text[text.index("## 手順"):text.index("\n1. ")]
        item1 = text[text.index("\n1. "):text.index("\n2. ")]
        item3 = text[text.index("\n3. "):text.index("\n4. ")]
        item6 = text[text.index("\n6. "):text.index("\n7. ")]
        self.assertIn("単位を束ねる理由にしない", cross)
        for needle in ("コードの上の欠陥の形", "別々の単位", "単位をまとめる理由ではなく", "`framing`", "`why_chain`",
                       "`one_shot_closes`", "同じ形の別の現れ", "欠陥の行そのものへの 1 つの直しで", "一撃の側", "出自の種類"):
            with self.subTest(needle):
                self.assertIn(needle, item1)
        self.assertIn("最大 3 段", item3)   # 根の深さは削らない
        self.assertIn("1 項に戻って", item6)   # 形の違う行を pattern ごとに並べる class_query は束ね過ぎの印
        for needle in ("書き方の揺れ", "受け入れのテストを足す所"):   # 1 項が許す束ね・1 つの欠陥の直す site には当てない
            with self.subTest(needle):
                self.assertIn(needle, item6)

    def test_diagnose_prompt_defers_question_ledger_to_mainline(self):
        """盤面の材料が在る時の問いの台帳の決まりは、材料のファイルに描いた本線の文（p2.diagnose の「問いの台帳」の節）が正本。
        指示書は awaiting・premise・unverifiable を一律に禁じない（run 27: awaiting_human の素材に awaiting を載せられず線が止まった）"""
        text = (BLK / "commands" / "diagnose.md").read_text(encoding="utf-8")
        self.assertNotIn("premise・unverifiable・awaiting はこのブロックでは使わない", text)
        self.assertIn("問いの台帳", text)
        self.assertIn("盤面の材料が無い時", text)

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
        passed = yaml.safe_load((BLK / "fixtures" / "pass.stubs.yaml").read_text(encoding="utf-8"))
        self.assertEqual(passed["judge"], load("judge_ok"))
        # 単独の run（盤面が無い）では裏取りの支度は go 偽で、束ね役とまとめは飛ぶ
        self.assertIn("verify-prep", passed["fixture"]["reached"])
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
        committed_copy(self.repo, SEED)   # 種を写して commit した git（型の写し。gitkit）
        self.art = tmp / "art"
        self.board = self.art / "board"

    def tearDown(self):
        self._tmp.cleanup()

    def run_script(self, name, **env):
        # 走らせる側（ラインの script の節）の INPUTS_*・ARTIFACTS_DIR は継がない。欠けを確かめる試験が継いだ値を見ないように
        base = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_") and k != "ARTIFACTS_DIR"}
        e = dict(base, ARTIFACTS_DIR=str(self.art), **env)
        return subprocess.run([sys.executable, str(BLK / "scripts" / f"{name}.py")], cwd=self.repo, env=e,
                              capture_output=True, text=True, encoding="utf-8", timeout=300)

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

    def test_intake_accepts_object_form(self):
        # 依頼は配列か {findings, pr, issue} の形。盤面に積むのは findings の行だけ
        doc = {"findings": load("request_ok"), "pr": [3], "issue": [5]}
        (self.repo / "obj.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
        r = self.run_script("intake", INPUTS_REQUEST="obj.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        batches = json.loads((self.board / "request.json").read_text(encoding="utf-8"))
        self.assertEqual(batches[0]["findings"], load("request_ok"))

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

    def write_start_input(self, requests):
        """盤面の始めの記録（startrec の置き場）に入口の入力の形の依頼の行の数だけを置く（線の入口が書く形の一部）"""
        p = self.board / "r1" / "start.json"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps({"input": {"requests": requests}}), encoding="utf-8")

    def test_intake_accepts_empty_request_when_input_has_no_requests(self):
        """依頼の行が無い run（始めの記録の input.requests が 0。入口の種類に依らない）では、依頼の空を受ける"""
        self.write_start_input(0)
        r = self.run_script("intake", INPUTS_REQUEST="")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIs(json.loads(r.stdout)["ok"], True)

    def test_intake_refuses_empty_request_when_input_has_requests(self):
        """依頼の行が在る run（input.requests が 1 以上）・始めの記録の無い run では、依頼の空は欠け（2）"""
        for doc in (2, None):
            with self.subTest(doc):
                if doc is None:
                    (self.board / "r1" / "start.json").unlink(missing_ok=True)
                else:
                    self.write_start_input(doc)
                r = self.run_script("intake", INPUTS_REQUEST="")
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)
                self.assertIn("INPUTS_REQUEST", r.stderr)

    def test_intake_stores_judge_snapshot(self):
        r = self.run_script("intake", INPUTS_REQUEST="request_ok.json")
        self.assertEqual(r.returncode, 0, r.stderr)
        # 判定役を起こす前の姿は共通の tree_state（HEAD・枝も持つ。R47）。役が commit すれば写しの head で見える
        self.assertEqual(json.loads((self.board / JUDGE_SNAPSHOT_FILE).read_text(encoding="utf-8")),
                         tree_state(self.repo))

    # ---- brief（盤面の材料）
    def test_brief_without_board_is_empty(self):
        """ブロックを単独で回した（ラインの盤面 state.json が無い）なら材料のファイルは空（判定は依頼だけで回る）"""
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST="request_ok.json").returncode, 0)
        r = self.run_script("brief")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"ok": True, "go": True, "materials_file": ""})

    def test_brief_missing_env(self):
        base = {k: v for k, v in os.environ.items() if k != "ARTIFACTS_DIR"}
        r = subprocess.run([sys.executable, str(BLK / "scripts" / "brief.py")], cwd=self.repo, env=base,
                           capture_output=True, text=True, encoding="utf-8", timeout=300)
        self.assertEqual(r.returncode, 2)
        self.assertIn("ARTIFACTS_DIR", r.stderr)

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

    def test_standalone_accept_done_on_third_reject(self):
        """盤面の無い単独の run でも、受け付けは done を出す: 拒否 1・2 回目は偽、3 回目で真（輪を max_iterations で落とさない。
        R50）。通れば真"""
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST="request_ok.json").returncode, 0)
        bad = json.dumps(load("judge_notfound_no_searched"))
        dones = [json.loads(self.run_script("accept", INPUTS_REPLY=bad, INPUTS_BASE_REV="").stdout)["done"] for _ in range(3)]
        self.assertEqual(dones, [False, False, True])
        got = json.loads(self.run_script("accept", INPUTS_REPLY=json.dumps(load("judge_ok")), INPUTS_BASE_REV="").stdout)
        self.assertEqual((got["ok"], got["done"]), (True, True))

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

    def test_accept_rejects_commit_after_intake(self):
        # HEAD 相対の porcelain と差分だけでは commit が素通りする。写しの head で見る
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST="request_ok.json").returncode, 0)
        (self.repo / "extra.txt").write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "commit した")
        got = json.loads(self.run_script("accept", INPUTS_REPLY=json.dumps(load("judge_ok")), INPUTS_BASE_REV="").stdout)
        self.assertIs(got["ok"], False)
        self.assertIn("head: 役を起こす前", got["reason"])   # 共通の tree_change の文（R47）

    def test_check_judge_without_snapshot_needs_clean_tree(self):
        # 写しが無いとき（intake を通らない呼び方）は今までどおり作業ツリーが綺麗であることを求める
        self.board.mkdir(parents=True)
        (self.repo / "extra.txt").write_text("x\n", encoding="utf-8")
        r = check_judge(load("judge_ok"), self.board, "", self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("extra.txt", r["reason"])

    def test_check_judge_without_snapshot_rejects_head_moved_from_base_rev(self):
        # 写しが無い分岐でも、判定役が作った物を commit して porcelain を空に戻す道を HEAD と版で塞ぐ
        base = git(self.repo, "rev-parse", "HEAD").strip()
        self.board.mkdir(parents=True)
        (self.repo / "extra.txt").write_text("x\n", encoding="utf-8")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "判定役が commit した")
        r = check_judge(load("judge_ok"), self.board, base, self.repo)
        self.assertIs(r["ok"], False)
        self.assertIn("HEAD", r["reason"])
        self.assertFalse((self.board / "judgment.json").exists())

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

    def test_stale_judgment_not_collected_after_rejected_loop(self):
        # 同じ盤面で 2 度目に回し、この回の受け付けが拒んだら、前の呼び出しの judgment.json を拾わずに collect が落ちる
        self.board.mkdir(parents=True)
        (self.board / "judgment.json").write_text(json.dumps(load("judge_ok"), ensure_ascii=False), encoding="utf-8")
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST="request_ok.json").returncode, 0)
        self.assertFalse((self.board / "judgment.json").exists())
        got = json.loads(self.run_script("accept", INPUTS_REPLY=json.dumps(load("judge_notfound_no_searched")), INPUTS_BASE_REV="").stdout)
        self.assertIs(got["ok"], False)
        r = self.run_script("collect")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("judgment.json", r.stderr)

    def test_verify_standalone_does_not_go(self):
        """盤面の無い単独の run: 裏取りの支度は go 偽、まとめは空（申し送りを作らない）。stage が違えば 2"""
        r = self.run_script("verify", INPUTS_STAGE="prep")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"ok": True, "go": False, "prompt_file": ""})
        r = self.run_script("verify", INPUTS_STAGE="merge")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout), {"ok": True, "verify_file": "", "verified": 0, "unverified": 0})
        self.assertEqual(self.run_script("verify", INPUTS_STAGE="other").returncode, 2)
        self.assertEqual(self.run_script("verify").returncode, 2)

    def test_collect_without_judgment(self):
        r = self.run_script("collect")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("judgment.json", r.stderr)


class QueryExamplesCase(unittest.TestCase):
    """判定役の class_query は、当たるべき例（hits）と当たってはならない例（misses）で問いそのものを試してから受ける
    （Semgrep の ruleid/ok と同じ形）。defects の問いは直した後の正しい形を misses に 1 行は持つ"""

    setUp = ScriptCase.setUp
    tearDown = ScriptCase.tearDown
    run_script = ScriptCase.run_script

    MEAN = "stats.py mean: 分母が len(xs) - 1 になっている"
    CLAMP = "stats.py clamp: 上限を超えた値に lo を返す"

    def reply(self, examples):
        doc = load("judge_ok")
        for u in doc["units"]:
            if u["key"] in examples:
                u["class_query"].update(examples[u["key"]])
        return doc

    def good(self):
        return {self.MEAN: {"hits": ["    return sum(xs) / (len(xs) - 1)"], "misses": ["    return sum(xs) / len(xs)"]},
                self.CLAMP: {"hits": ["        return lo"], "misses": ["        return hi"]}}

    def accept(self, doc):
        self.assertEqual(self.run_script("intake", INPUTS_REQUEST="request_ok.json").returncode, 0)
        r = self.run_script("accept", INPUTS_REPLY=json.dumps(doc, ensure_ascii=False), INPUTS_BASE_REV="")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        text = got.get("reason", "")
        if got.get("reason_file"):
            text += pathlib.Path(got["reason_file"]).read_text(encoding="utf-8")
        return got, text

    def test_examples_that_hold_are_accepted_and_kept_in_judgment(self):
        got, text = self.accept(self.reply(self.good()))
        self.assertIs(got["ok"], True, text)
        doc = json.loads((self.board / "judgment.json").read_text(encoding="utf-8"))
        cq = {u["key"]: u["class_query"] for u in doc["units"]}
        self.assertEqual(cq[self.MEAN]["misses"], ["    return sum(xs) / len(xs)"])
        self.assertEqual(cq[self.CLAMP]["hits"], ["        return lo"])

    def test_defects_query_without_misses_is_rejected(self):
        ex = self.good()
        del ex[self.MEAN]["misses"]
        got, text = self.accept(self.reply(ex))
        self.assertIs(got["ok"], False)
        self.assertIn(self.MEAN[:20], text)
        self.assertIn("misses", text)
        self.assertFalse((self.board / "judgment.json").exists())

    def test_defects_query_matching_fixed_form_is_rejected(self):
        # 項目 35 の形: 問いが部分一致で、直した後の正しい行も数える
        ex = self.good()
        fixed = "    return sum(xs) / (len(xs) - 1)  # 直した"
        ex[self.MEAN]["misses"] = [fixed]
        got, text = self.accept(self.reply(ex))
        self.assertIs(got["ok"], False)
        self.assertIn(self.MEAN[:20], text)
        self.assertIn("直した後の正しい形にも当たる", text)
        self.assertIn(fixed.strip(), text)
        self.assertFalse((self.board / "judgment.json").exists())

    def test_hit_the_query_does_not_match_is_rejected(self):
        ex = self.good()
        ex[self.CLAMP]["hits"] = ["        return lo", "        return floor"]
        got, text = self.accept(self.reply(ex))
        self.assertIs(got["ok"], False)
        self.assertIn(self.CLAMP[:20], text)
        self.assertIn("return floor", text)
        self.assertFalse((self.board / "judgment.json").exists())


class UnprovenQueryCase(unittest.TestCase):
    """例の無い開いた単位は拒まずに「例で証明できない」印を付けて通す（querytest.unproven）。例を出せない単位は理由
    （examples_unavailable）で、defects の問いの misses を書けない単位は理由（misses_omitted_why）で出口を持つ。
    理由の欄は例の欄と同じく盤面へ渡す前に外す（split）。盤面・子のプロセスは使わない"""

    MEAN = "stats.py mean: 分母が len(xs) - 1 になっている"
    CLAMP = "stats.py clamp: 上限を超えた値に lo を返す"
    HOW = {"patterns": ["(len(xs) - 1)"], "fixed": True, "paths": ["stats.py"], "count": "lines"}
    WHY = "在るべき検査が無い形で、直した後の行を 1 行に書けない"

    def unit(self, key, **cq):
        return {"key": key, "class_query": {"how": self.HOW, "counts": "defects", "total": 1, **cq}}

    def querytest(self):
        import querytest
        return querytest

    def test_units_without_examples_are_marked_unproven(self):
        qt = self.querytest()
        self.assertTrue(hasattr(qt, "unproven"), "例で証明できない単位を返す口が無い")
        units = [self.unit(self.MEAN), self.unit(self.CLAMP, examples_unavailable=self.WHY),
                 self.unit("stats.py x: 例の在る単位", hits=["    return sum(xs) / (len(xs) - 1)"],
                           misses=["    return sum(xs) / len(xs)"])]
        got = {row["key"]: row["why"] for row in qt.unproven(units, lambda u: True)}
        self.assertEqual(set(got), {self.MEAN, self.CLAMP}, "例の在る単位は印の外")
        self.assertIn(self.WHY, got[self.CLAMP], "例を出せない理由を印に載せる")
        self.assertEqual(qt.unproven(units, lambda u: False), [], "開いていない単位は見ない")
        self.assertEqual(qt.problems(units[:2], lambda u: True), [], "例の無い単位は拒まない（印で人に見せる）")

    def test_misses_omitted_with_reason_is_accepted(self):
        qt = self.querytest()
        u = self.unit(self.MEAN, hits=["    return sum(xs) / (len(xs) - 1)"], misses_omitted_why=self.WHY)
        self.assertEqual(qt.problems([u], lambda u: True), [])
        self.assertTrue(qt.problems([self.unit(self.MEAN, hits=["    return sum(xs) / (len(xs) - 1)"])], lambda u: True),
                        "理由の無い misses の欠けは今までどおり拒む")

    def test_examples_unavailable_with_examples_is_rejected(self):
        qt = self.querytest()
        u = self.unit(self.MEAN, examples_unavailable=self.WHY, hits=["    return sum(xs) / (len(xs) - 1)"],
                      misses=["    return sum(xs) / len(xs)"])
        errs = qt.problems([u], lambda u: True)
        self.assertTrue(any("examples_unavailable" in e for e in errs), errs)

    def test_reason_fields_are_split_off(self):
        qt = self.querytest()
        reply = {"units": [self.unit(self.MEAN, examples_unavailable=self.WHY),
                           self.unit(self.CLAMP, hits=["    return sum(xs) / (len(xs) - 1)"], misses_omitted_why=self.WHY)]}
        out, _ = qt.split(reply)
        for u in out["units"]:
            with self.subTest(key=u["key"]):
                self.assertFalse({"examples_unavailable", "misses_omitted_why"} & set(u["class_query"]),
                                 "盤面へ渡す写しの class_query に理由の欄を残さない（写しの型は additionalProperties: false）")


class AnswerTiesTakeCase(unittest.TestCase):
    """判定役の返答の足し欄 answer_ties（依頼の答えを問いか単位に結ぶ）を、受け付け（judgetake.take）が外して盤面へ渡し、
    依頼の答えの全部に 1 行が無い・結び先が今の返答に無いなら拒み、通れば盤面の根に控える（黙って落とさない）"""

    def setUp(self):
        import types
        from unittest import mock
        import gatemarks
        import judgetake
        self.mock, self.gm, self.jt = mock, gatemarks, judgetake
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.dir = pathlib.Path(self._tmp.name)
        (self.dir / "r1").mkdir()
        answers = [{"question": "自分の項目 a.py", "text": "例外のまま"}, {"question": "自分の項目 b.py", "text": "変えない"}]
        (self.dir / "r1" / "start.json").write_text(json.dumps({"answers": answers}, ensure_ascii=False), encoding="utf-8")
        self.b = types.SimpleNamespace(dir=self.dir, round=1, state={"outputs": {}}, record={"process": {}},
                                       latest_output=lambda nid: None)
        self.reply = {"units": [{"key": "u-a", "label": "block"}], "questions": [{"key": "q-7", "kind": "fork"}]}

    def take(self, ties):
        with self.mock.patch.object(self.jt.entry, "open_board", return_value=self.b), \
                self.mock.patch.object(self.jt.querytest, "problems", return_value=[]), \
                self.mock.patch.object(self.jt.querytest, "split", side_effect=lambda r, _o: (r, [])), \
                self.mock.patch.object(self.jt.querytest, "save"), \
                self.mock.patch.object(self.jt.entry, "take", return_value={"ok": True, "reason": ""}) as t:
            got = self.jt.take(self.dir, {**self.reply, self.gm.TIES_FIELD: ties}, self.dir)
        return got, t

    def test_judge_must_account_every_answer(self):
        got, t = self.take([{"answer": "自分の項目 a.py", "to": "q-7"}])
        self.assertFalse(got["ok"])
        self.assertIn("自分の項目 b.py", got["reason"])
        t.assert_not_called()

    def test_tie_to_unknown_key_refused(self):
        got, t = self.take([{"answer": "自分の項目 a.py", "to": "q-無い"}, {"answer": "自分の項目 b.py", "to": "u-a"}])
        self.assertFalse(got["ok"])
        self.assertIn("q-無い", got["reason"])
        t.assert_not_called()

    def test_good_ties_are_taken_off_and_saved(self):
        ties = [{"answer": "自分の項目 a.py", "to": "q-7"}, {"answer": "自分の項目 b.py", "to": "u-a"}]
        got, t = self.take(ties)
        self.assertTrue(got["ok"], got)
        self.assertNotIn(self.gm.TIES_FIELD, t.call_args.args[2])
        self.assertEqual(self.gm.ties(self.b), {"自分の項目 a.py": "q-7", "自分の項目 b.py": "u-a"})

    def test_role_schema_has_optional_ties(self):
        s = role_schema("p2.diagnose")
        self.assertNotIn(self.gm.TIES_FIELD, s["required"])
        row = s["properties"][self.gm.TIES_FIELD]["items"]
        self.assertEqual(row["required"], ["answer"])
        self.assertFalse(row["additionalProperties"])

    def test_diagnose_prompt_asks_for_ties(self):
        text = (BLK / "commands" / "diagnose.md").read_text(encoding="utf-8")
        self.assertIn(f"`{self.gm.TIES_FIELD}`", text)


if __name__ == "__main__":
    unittest.main()
