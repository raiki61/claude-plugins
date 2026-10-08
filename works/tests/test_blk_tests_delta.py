"""ブロック blk-tests（テストのコマンド）と blk-delta（修正差分の審査）の検査。

- YAML に書いた審査役の返答の型が、受け付けの規則が前提にする型（graph の p3.delta_review）と同じか（設計書 5.4 節）
- blk-tests の節 run のスクリプト（scripts/run_tests.py）を、Archon を通さずに環境変数だけ与えて走らせ、緑も赤も ok: true で出るか。
  止められたらテストのコマンドが起こした孫まで止まるか（.shared/core/tree_run.py）
- blk-delta の支度・受け付け・出口（refix の口とスクリプト）を、差分の審査の前まで進めた盤面（test_blk_refix.DeltaBoardCase）で見る
- 作業ツリーの写し（snapshot_tree）が、未追跡のフォルダ（入れ子の git リポジトリ）で落ちないか
筋書き（fixtures/*.stubs.yaml）は dev/check.sh が Archon で回す。
"""
import importlib.util
import io
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

import yaml

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
REPLIES = pathlib.Path(__file__).resolve().parent / "replies"
SEED = ROOT / "dev" / "target-seed"
sys.path.insert(0, str(CORE))

from accept import role_schema, snapshot_tree, tree_state  # noqa: E402
from board import BoardGap  # noqa: E402
import conflict  # noqa: E402
import deltamarks  # noqa: E402
import fixshape  # noqa: E402
import planmarks  # noqa: E402
import policy  # noqa: E402
import protect  # noqa: E402
import refix  # noqa: E402
import seat  # noqa: E402
from engine.schema import validate_schema  # noqa: E402
from gitkit import committed_copy, git  # noqa: E402



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


def load_run_tests():
    """blk-tests の節のスクリプトを module として読む（main は __main__ の時だけ走る）。読むたびに新しく読む"""
    spec = importlib.util.spec_from_file_location("blk_tests_run_tests", ROOT / "blk-tests" / "scripts" / "run_tests.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class RepoCase(unittest.TestCase):
    """dev/target-seed/ を写した使い捨ての対象リポジトリと、run の成果物の置き場"""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(self._tmp.name)
        self.repo = tmp / "repo"
        self.base = committed_copy(self.repo, SEED)   # 種を写して commit した git（型の写し。gitkit）
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
                              env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)


# ---------------------------------------------------------------- blk-delta の型
class TestDeltaSchema(unittest.TestCase):
    def test_delta_output_format_matches_role_schema(self):
        """〔線A計〕T17: 役の output_format は refix.output_format("review")（写しの p3.delta_review の schema に印 works-node: review）"""
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertEqual(review["output_format"], refix.output_format("review"))
        self.assertEqual({k: v for k, v in review["output_format"].items() if k != "description"}, role_schema("p3.delta_review"))

    def test_delta_reads_before_collect(self):
        """読んだ証拠の節 review-reads が collect の前（〔線A計〕T17）。機械が渡したパスは brief と差分"""
        nodes = workflow("blk-delta")["nodes"]
        self.assertEqual([n["id"] for n in nodes], ["cut", "delta-loop", "review-reads", "collect"])
        reads = find_node(nodes, "review-reads")
        self.assertEqual((reads["script"], reads["depends_on"]), ("reads", ["delta-loop"]))
        self.assertEqual(reads["with"], {"must": '["$cut.output.brief_file", "$cut.output.diff_file"]'})
        self.assertEqual(find_node(nodes, "collect")["depends_on"], ["review-reads"])

    def test_delta_ok_sample_passes_yaml_output_format(self):
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertEqual(validate_schema(load("delta_ok"), review["output_format"]), [])

    def test_delta_bad_cite_sample_passes_yaml_output_format(self):
        # 悪い見本は型では通り、受け付け（cite の字列）でだけ拒まれる——筋書き bad-cite が輪で落ちる理由
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertEqual(validate_schema(load("delta_bad_cite"), review["output_format"]), [])

    def test_delta_prompt_asks_for_checks_of_absorbed(self):
        # 2 本目: 修正役が事前審査の穴に absorbed（塞いだ）と答えた物を 1 件ずつ検算させる（0.21.0 の p3.delta_review）。
        # 事前審査の穴と修正役の plan_faces は支度（cut）が盤面から brief に書き、役はそれを読む
        body = (ROOT / "blk-delta" / "commands" / "delta-review.md").read_text(encoding="utf-8")
        for word in ("checks", "absorbed", "closed", "out.p2.plan_review", "out.p3.fix.plan_faces", "faces_none"):
            self.assertIn(word, body)
        self.assertNotIn("checks: []", body)
        self.assertNotIn("{{", body)

    def test_delta_prompt_asks_two_verdicts(self):
        # 1 回目の審査役に、承認済みの修正案の項目への準拠（先に）と品質（次に）の 2 判定を頼む。材料は支度（cut）の brief
        text = (ROOT / "blk-delta" / "commands" / "delta-review.md").read_text(encoding="utf-8")
        for w in ("plan_items", "fix_report", "compliance", "quality", "missing", "extra", "misunderstood", "unverifiable",
                  "face_key", "not_applicable", "信じず", "先に準拠"):
            self.assertIn(w, text)
        self.assertIn("unverifiable の行は `face_key` を空文字 `\"\"`", text)   # 穴に結べない行（deltamarks.gaps の M4 の決まり）
        self.assertIn("3 点と下の品質の観点", text)
        for w in ("`held`", "`held_units`", "`ruled_paths`"):   # 裁定で外れた項目（conflict.held_item）と裁定が広げたパス（planscope と同じ ruled_paths）
            self.assertIn(w, text)

    def test_review_prompts_read_protected_files(self):
        # 支度（refix.cut）が brief に書く守りのファイル（protected_files）を、1 回目と 2 回目の審査役の指示書が読ませる
        for path in (ROOT / "blk-delta" / "commands" / "delta-review.md", ROOT / "blk-refix" / "commands" / "review2.md"):
            with self.subTest(path.name):
                self.assertIn("`protected_files`", path.read_text(encoding="utf-8"))

    def test_delta_prompt_reads_block_outputs(self):
        # Ruling R16: 指示書の本文は同じブロックの節の出力を直に読む（include が節の名を付け替える）。
        # 拒否の理由は reason_file のパスだけ（裁定 R44）。$INPUTS は読まない——1 本目の blk-delta の YAML（Task 17 まで替えない）は
        # 入口 policy_paste を持たず、宣言の無い $INPUTS はラインの include の読み込みで拒まれる。人の方針の本文は支度（cut）が
        # brief の policy に書き、指示書はそれを読ませる（TA10 の「読む役には本文を届ける」）
        body = (ROOT / "blk-delta" / "commands" / "delta-review.md").read_text(encoding="utf-8")
        refs = re.findall(r"\$[A-Za-z_][A-Za-z0-9_.-]*[A-Za-z0-9_]", body)
        self.assertEqual(sorted(set(refs)), ["$LOOP_PREV.review-accept.output.reason_file",
                                             "$cut.output.brief_file", "$cut.output.diff_file", "$cut.output.files"])
        self.assertIn("`policy.paste`", body)
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertNotIn("with", review)

    def test_delta_loop(self):
        # 輪の中の節の id はライン全体で一意にする（模擬実行は輪の中の節を名前空間なしの id で stub に引く）
        loop = find_node(workflow("blk-delta")["nodes"], "delta-loop")["loop_group"]
        self.assertEqual([n["id"] for n in loop["nodes"]], ["review", "review-accept"])
        self.assertEqual(loop["until_bash"], "test $review-accept.output.done = true")   # 通った時か 3 回目の拒否で抜ける（R50）

    def test_delta_review_sandbox(self):
        # Ruling R12: Bash を持たない役でも、サンドボックスの外へ出る道を閉じる
        review = find_node(workflow("blk-delta")["nodes"], "review")
        self.assertEqual(review["sandbox"], {"enabled": True, "allowUnsandboxedCommands": False})


# ---------------------------------------------------------------- blk-tests
class TestTestsBlock(RepoCase):
    def test_run_node_contract(self):
        wf = workflow("blk-tests")
        self.assertEqual(wf["returns"], "run")
        self.assertEqual(wf["outcome_field"], "ok")
        self.assertIn("cmd", wf["inputs"])
        node = find_node(wf["nodes"], "run")
        # 木ごと止める殻を pack の中から引くので、パスを持たない bash の節ではなく名前付きの script の節
        self.assertEqual((node.get("script"), node.get("runtime")), ("run_tests", "uv"))
        self.assertNotIn("bash", node)
        self.assertEqual(node["with"], {"cmd": "$INPUTS.cmd"})
        self.assertEqual(sorted(node["output_format"]["required"]), ["green", "log", "ok"])   # 1 本目の必須の欄のまま
        # 形は最後のテストだけ（盤面を開かない plain と中の関所の mid は 2026-10-09 の整理で消した）
        self.assertEqual(set(wf["inputs"]), {"cmd"})
        props = node["output_format"]["properties"]
        self.assertEqual(props["by"], {"type": "string", "enum": ["engine", "role", "role_needed"]})
        self.assertEqual(props["suites"]["type"], "array")

    def test_inputs_constant(self):
        # 裁定 TA16: 読む INPUTS_* の名前の組を定数に持つ（Task 17 の試験が YAML の with: の鍵と突き合わせる）
        self.assertEqual(load_run_tests().INPUTS, ("INPUTS_CMD",))


# ---------------------------------------------------------------- blk-tests の最後のテスト（仕様 3.5・裁定 TA4・TA5）
# 盤面は盤面の層の試験の道具（手本の盤面を p4.ci の手の前に戻す。読むだけ・import するだけ）で組み、節のスクリプトの main を
# Archon と同じ環境変数で同じプロセスの中で呼ぶ。盤面は 1 本目のラインの本物の表で組み、本物の entry（Task 3 の open_board）で開く。
# 偽物は Task 7 の run_ci・CiRefused だけ（この枝にまだ無い）: run_ci は Task 7 の約束（relaunch は 1 度だけ呼び直す・任せ先は
# 起こした印を置いてから cmd を走らせた素材を done・why だけの返りは CiRefused）をなぞる。run_ci そのものの試験は Task 7 の側
import contextlib  # noqa: E402

import entry as real_entry  # noqa: E402
import test_board_engine_run as ER  # noqa: E402
import test_blk_refix as RF  # noqa: E402
import linekit  # noqa: E402

DECL_BROKEN = {"suite": []}


class CiRefused(Exception):
    """entry.CiRefused の代わり"""


def ref_run_ci(b, nid, *, test_cmd, runner=None):
    """entry.run_ci（Task 7）の約束をなぞる偽物"""
    got = b.run_engine(nid, runner=runner)
    if got.get("relaunch"):
        got = b.run_engine(nid, runner=runner)
        if got.get("relaunch"):
            raise CiRefused(got["why"])
    if got["ok"]:
        runs = got.get("runs") or []
        return {"by": "engine", "log": runs[0]["out"] if runs else "",
                "runs": [{"name": r["name"], "exit": r["exit"], "how": "direct"} for r in runs]}   # 宣言の段だけ（shell なし）
    if "fallback" not in got:
        raise CiRefused(got["why"])
    log = b.work("tests.log")
    with open(log, "wb") as f:
        code = subprocess.run(["bash", "-c", test_cmd], cwd=b.state["inputs"]["cwd"], stdin=subprocess.DEVNULL,
                              stdout=f, stderr=subprocess.STDOUT).returncode
    tail = log.read_text(encoding="utf-8", errors="replace")[-400:]
    # 任せ先の返答を出す側が、出す前に起こした印を置く（board.py の頭の決まり 2。印の無い instance の返答は受けない）
    inst = next(i for i in b.rd["instances"].values() if i["node"] == nid and i["status"] == "pending")
    b.mark_launched(nid, inst.get("attempts", 1))
    # clean には checked が要る（受け付けの記録の整合: 何を見たかを書け）
    b.done(nid, {"material": {"status": "clean", "count": 0, "detail": tail, "checked": f"bash -c {test_cmd}: exit 0"}
                 if code == 0 else {"status": "found", "count": 1, "detail": tail}})
    return {"by": "role", "log": str(log)}


REAL_RUN_CI = real_entry.run_ci   # 本物の run_ci（call が real_entry.run_ci を差し替える前に取っておく）


class TestTestsModes(ER.EngineRunCase):
    def mode_board(self, decl=ER.GREEN, nth=0):
        """p4.ci が待っている darkfactory の盤面（stop_after_round は今の周）。手本の盤面を 1 本目のラインの本物の表
        （Task 3 の darkfactory/nodes.json）で組み、state.works に line・table_sha を置いて、本物の entry.open_board で開き直す。
        表は p4.ci の後ろの役の節を「このラインに無い」にするので、p4.ci の後の settle が p4.record・converge まで回る。
        decl は宣言の suite（None なら宣言を消す、dict なら本文そのもの）"""
        table = real_entry.load_table("darkfactory")

        def edit(mem):
            ER.minimal("p4.ci")(mem)
            mem["state"]["stop_after_round"] = mem["state"]["round"]
        b = self.board_before(ER.engine_run_step("p4.ci", nth), table=table, edit=edit)
        state = json.loads((b.dir / "state.json").read_text(encoding="utf-8"))
        state["works"].update(line=table.line, table_sha=table.sha())
        (b.dir / "state.json").write_text(json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        p = self.repo(b) / ER.DECL
        if decl is None:
            p.unlink()
        elif isinstance(decl, dict):
            p.write_text(json.dumps(decl), encoding="utf-8")
        else:
            self.write_decl(b, decl)
        return real_entry.open_board(b.dir)

    def reopen(self, b):
        return real_entry.open_board(b.dir, allow_halted=True)

    def call(self, b, cmd, run_ci=ref_run_ci, entry="real"):
        """節のスクリプトの main を Archon と同じ環境変数で呼ぶ → (終了コード, 出口の dict か None, stderr)。
        entry は本物（Task 3 の open_board）。Task 7 の run_ci・CiRefused だけはこの枝に無いので偽物を足す。
        entry=None は entry が import できない時"""
        opened = []
        real_open = real_entry.open_board

        def open_board(d, **kw):
            opened.append(pathlib.Path(d))
            return real_open(d, **kw)

        env = {"INPUTS_CMD": cmd, "ARTIFACTS_DIR": str(b.dir.parent)}
        out, err = io.StringIO(), io.StringIO()
        mod = load_run_tests()
        with contextlib.ExitStack() as stack:
            if entry is None:
                stack.enter_context(mock.patch.dict(sys.modules, {"entry": None}))
            else:
                stack.enter_context(mock.patch.dict(sys.modules, {"entry": real_entry}))
                stack.enter_context(mock.patch.object(real_entry, "open_board", open_board))
                stack.enter_context(mock.patch.object(real_entry, "run_ci", run_ci, create=True))
                stack.enter_context(mock.patch.object(real_entry, "CiRefused", CiRefused, create=True))
            stack.enter_context(mock.patch.dict(os.environ, env))
            stack.enter_context(contextlib.redirect_stdout(out))
            stack.enter_context(contextlib.redirect_stderr(err))
            rc = mod.main()
        self.assertIn(opened, ([], [b.dir]))   # 盤面は <ARTIFACTS_DIR>/board を開く
        text = out.getvalue()
        if rc:
            self.assertEqual(text, "")
            return rc, None, err.getvalue()
        self.assertEqual(text.count("\n"), 1)
        return rc, json.loads(text), err.getvalue()

    # -- final
    def test_final_by_engine(self):
        # 宣言が在れば engine が走らせる（cmd は空でよい）。process.checks["p4.ci"].by == "engine"、green は素材の clean
        b = self.mode_board(decl=ER.GREEN)
        rc, out, err = self.call(b, "")
        self.assertEqual(rc, 0, err)
        self.assertEqual((out["ok"], out["green"], out["by"], out["suites"]), (True, True, "engine", [{"name": "suite", "exit": 0, "how": "direct"}]))
        after = self.reopen(b)
        self.assertEqual(after.record["process"]["checks"]["p4.ci"]["by"], "engine")
        self.assertEqual(after.record["materials"]["local_checks"]["status"], "clean")

    def test_final_red_suite_is_ok(self):
        b = self.mode_board(decl=ER.RED)
        rc, out, err = self.call(b, "")
        self.assertEqual(rc, 0, err)
        self.assertEqual((out["ok"], out["green"], out["by"], out["suites"]), (True, False, "engine", [{"name": "suite", "exit": 3, "how": "direct"}]))

    def test_final_log_from_run_engine(self):
        # engine が走らせた時の log は run_engine の返りの runs[0].out（runs/r<N>/ を組み立てない）
        seen = {}

        def spy(b, nid, *, test_cmd, runner=None):
            orig = b.run_engine

            def run_engine(*a, **kw):
                seen["got"] = orig(*a, **kw)
                return seen["got"]
            b.run_engine = run_engine
            return ref_run_ci(b, nid, test_cmd=test_cmd, runner=runner)

        b = self.mode_board(decl=ER.GREEN)
        rc, out, err = self.call(b, "", run_ci=spy)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out["log"], seen["got"]["runs"][0]["out"])
        self.assertEqual(pathlib.Path(out["log"]).read_text(encoding="utf-8"), "1 passed\n")

    def test_final_fallback_runs_cmd(self):
        # 宣言が無ければ任せ先（by: role）: cmd を走らせた結果を素材で done。green は cmd の結果
        for cmd, green, status in (("echo 走った", True, "clean"), ("echo 赤; exit 2", False, "found")):
            with self.subTest(cmd=cmd):
                b = self.mode_board(decl=None)
                rc, out, err = self.call(b, cmd)
                self.assertEqual(rc, 0, err)
                self.assertEqual((out["ok"], out["green"], out["by"], out["suites"]), (True, green, "role", []))
                self.assertEqual(out["log"], str(b.work("tests.log")))
                after = self.reopen(b)
                self.assertEqual(after.record["process"]["checks"]["p4.ci"]["by"], "role")
                self.assertEqual(after.record["materials"]["local_checks"]["status"], status)
                self.assertEqual(after.node_state("p4.ci"), "done")

    def test_final_empty_cmd_on_fallback_role_needed(self):
        # 宣言が無く cmd も空 → 拒まない（裁定 R52）。run_ci の role_needed をそのまま出口の by に出し、緑と言わない。
        # p4.ci は任せ先に落ちたまま待ち、ラインが blk-ci（CI の任せ先の役）を回す。起こした印は置かない（blk-ci の prep が置く）
        b = self.mode_board(decl=None)
        rc, out, err = self.call(b, " ", run_ci=REAL_RUN_CI)
        self.assertEqual(rc, 0, err)
        self.assertEqual(out, {"ok": True, "green": False, "log": "", "suites": [], "by": "role_needed"})
        after = self.reopen(b)
        inst = after.rd["instances"]["p4.ci"]
        self.assertEqual(inst["status"], "pending")
        self.assertIn(ER.DECL, inst["engine_fallback"])
        self.assertFalse(inst.get("launched_at"))
        self.assertIn("p4.ci", after.settle()["ready"])

    def test_final_role_needed_never_reuses_earlier_result(self):
        # Task 7 の審査 I2: 宣言は在るが cmd が空で、engine がそれでも任せ先に落ちた（組んだ返答を受け付けが拒んだ等）→
        # 修正前の素材（周の頭の local_checks。ここでは clean）を最後の結果に使わない。出口は role_needed で緑と言わない
        def fall(b, nid, *, test_cmd, runner=None):
            orig = b.run_engine
            b.run_engine = lambda n, **kw: orig(n, plan={"fallback": "engine が組んだ返答を受け付けが拒んだ（試験）"}, **kw)
            return REAL_RUN_CI(b, nid, test_cmd=test_cmd, runner=runner)

        b = self.mode_board(decl=ER.GREEN)
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "clean", "前提: 修正前の素材は緑")
        rc, out, err = self.call(b, "", run_ci=fall)
        self.assertEqual(rc, 0, err)
        self.assertEqual((out["green"], out["by"], out["suites"], out["log"]), (False, "role_needed", [], ""))
        after = self.reopen(b)
        self.assertEqual(after.rd["instances"]["p4.ci"]["status"], "pending")
        self.assertTrue(after.rd["instances"]["p4.ci"]["engine_fallback"])

    def test_final_ci_refused(self):
        # run_ci が拒んだ（2 度とも relaunch・why だけの返り）→ 終了コード 1、stderr に why
        def refuse(*a, **kw):
            raise CiRefused("宣言が計画の後に 2 度変わった")

        b = self.mode_board(decl=ER.GREEN)
        rc, out, err = self.call(b, "", run_ci=refuse)
        self.assertEqual((rc, out), (1, None))
        self.assertIn("宣言が計画の後に 2 度変わった", err)

    def test_final_settles_to_record(self):
        # final の後の盤面は独立の目（R1〜R4。表で blk-eyes の役）を待ち、目を渡すと p4.record と converge が済み、
        # stop_after_round で止まる（計画 P1 Task 33）
        b = self.mode_board(decl=ER.GREEN)
        rc, out, err = self.call(b, "")
        self.assertEqual(rc, 0, err)
        after = self.reopen(b)
        self.assertEqual(after.node_state("p4.assemble"), "done")
        self.assertEqual(after.node_state("p4.record"), "pending")
        self.assertTrue(any(after.table.nodes[n].where == "blk-eyes" for n in after.ready()), after.ready())
        linekit.close_eyes(b.dir, self.repo(b))
        after = self.reopen(b)
        self.assertEqual((after.node_state("p4.record"), after.node_state("converge")), ("done", "done"))
        self.assertEqual(after.state["halted"]["by"], "stop_after_round")

    def test_final_round_two(self):
        b = self.mode_board(nth=1)
        self.assertGreaterEqual(b.round, 2)
        rc, out, err = self.call(b, "")
        self.assertEqual(rc, 0, err)
        after = self.reopen(b)
        self.assertEqual(out["log"], after.record["process"]["checks"]["p4.ci"]["runs"][0]["out"])
        linekit.close_eyes(b.dir, self.repo(b))   # 独立の目の後に周が締まる（計画 P1 Task 33）
        self.assertEqual(self.reopen(b).state["halted"]["by"], "stop_after_round")

    # -- 共通
    def test_exit_keeps_v1_fields(self):
        # 出口は 1 本目の ok・green・log を全部残し、suites・by を足す
        b = self.mode_board()
        rc, out, err = self.call(b, "")
        self.assertEqual(rc, 0, err)
        self.assertEqual(set(out), {"ok", "green", "log", "suites", "by"})
        self.assertTrue(all(set(s) == {"name", "exit", "how"} for s in out["suites"]))

    def test_needs_entry(self):
        # 盤面の口（entry）が要る。読めなければ回す側の誤り（終了コード 2）で、盤面を書かない
        b = self.mode_board()
        before = ER.disk_bytes(b)
        rc, out, err = self.call(b, "true", entry=None)
        self.assertEqual((rc, out), (2, None))
        self.assertIn("entry", err)
        self.assertEqual(ER.disk_bytes(b), before)

    def test_stopped_run_exits_without_output(self):
        # run が止められた（tree_run.Stopped）回は、テストの木を止め終えた後に出口を出さずに 128+信号で終わる
        b = self.mode_board()

        def stopped(*a, **k):
            raise load_run_tests().tree_run.Stopped(signal.SIGTERM)
        rc, out, err = self.call(b, "true", run_ci=stopped)
        self.assertEqual((rc, out), (128 + signal.SIGTERM, None))
        self.assertIn("止められた", err)

# ---------------------------------------------------------------- blk-delta の支度・受け付け・出口（盤面の上。線 A Task 13）
# 1 本目の cut・accept・collect（偽の盤面の fix.diff・delta-review.json）は盤面の機械の節と refix の口に替わった。1 本目の試験の
# 主張（未追跡・日本語の名前が差分に載る・触ったファイルの外の穴を拒む・読むだけの役の変化を拒む・受け付けていない出口は
# 組まない・環境変数の欠け）は、盤面の上で同じく確かめる（test_blk_refix.DeltaBoardCase の盤面）
class TestDeltaBoard(RF.DeltaBoardCase):
    def test_cut_reads_board_fix_delta(self):
        """p3.fix を受けた盤面 → cut(1) の diff_file は盤面の loop.fix_delta.file、files は stats.py（名前を組み立てない）。
        役に見せる材料（事前審査の穴と修正役の plan_faces）を brief に書き、写しを撮り、起こした印を置く"""
        repo = self.fixed()
        got = refix.cut(self.board, 1, repo)
        b = real_entry.open_board(self.board)
        d = b.loop_state["fix_delta"]
        self.assertEqual((got["ok"], got["diff_file"], got["files"], got["rev"]), (True, d["file"], ["stats.py"], d["rev"]))
        patch = pathlib.Path(got["diff_file"]).read_text(encoding="utf-8")
        self.assertIn("-    return sum(xs) / (len(xs) - 1)", patch)   # 周の頭に固めた版から
        brief = json.loads(pathlib.Path(got["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual([f["key"] for f in brief["reads"]["out.p2.plan_review"]["faces"]], [RF.PR_KEY])
        self.assertEqual([(r["key"], r["handled"]) for r in brief["reads"]["out.p3.fix.plan_faces"]], [(RF.PR_KEY, "absorbed")])
        self.assertEqual(got["must"], [got["brief_file"], d["file"], brief["seat_file"]])   # 種の盤面の形は既定の g3（座のファイル）
        self.assertEqual(brief["policy"], policy.brief(b))   # 方針の本文と写しの置き場（方針の文書が無い run は両方空）
        self.assertEqual(json.loads(b.work(refix.snapshot_name(1)).read_text(encoding="utf-8")), tree_state(repo))   # entry.snapshot は共通の tree_state の形（R47。HEAD・枝を含む）
        self.assertTrue(b.rd["instances"]["p3.delta_review"].get("launched_at"))
        self.assertEqual(refix.cut(self.board, 1, repo)["diff_file"], d["file"])   # 呼び直しても同じ（印は前の物）

    def test_cut_brief_lists_protected_files(self):
        """変わったファイルのうち守りのファイル（core の protected.json）に当たる物を brief の protected_files に並べる
        （差分の審査役が検査を緩める変更を穴として見る材料。最後の人の関所にも必ず出る）。本物の一覧では種の stats.py は当たらない"""
        repo = self.fixed()
        brief = json.loads(pathlib.Path(refix.cut(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual(brief["protected_files"], [])
        path = pathlib.Path(self.board).parent / "protected.json"
        path.write_text(json.dumps({"rules": [{"id": "seed-core", "glob": "stats.py", "why": "種の芯"}]}), encoding="utf-8")
        with mock.patch.object(protect, "MANIFEST", path):
            brief = json.loads(pathlib.Path(refix.cut(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual(brief["protected_files"], [{"path": "stats.py", "id": "seed-core", "glob": "stats.py", "why": "種の芯"}])

    def test_cut_brief_carries_plan_items_and_fix_report(self):
        """1 回目の審査役の brief に、範囲の欄の在る承認済みの修正案の項目（plan_items。無ければ空）と、直した側の報告
        （fix_report: 今の周の p3.fix の changes・not_done）を載せる"""
        repo = self.fixed()
        brief = json.loads(pathlib.Path(refix.cut(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual(brief["plan_items"], [])
        self.assertEqual(set(brief["fix_report"]), {"changes", "not_done"})
        self.assertEqual([c["unit_key"] for c in brief["fix_report"]["changes"]], [c["unit_key"] for c in RF.fix_reply()["changes"]])
        self.plan_fields(scoped=True)
        brief = json.loads(pathlib.Path(refix.cut(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual((brief["plan_items"][0]["item"], brief["plan_items"][0]["allowed_paths"]), (1, ["stats.py"]))
        self.assertEqual(brief["plan_items"][0]["unit_keys"], [RF.K1])
        self.plan_fields(scoped=False)   # 217 番の形の控え（範囲の欄が無い）は修正案の無い run と同じ
        brief = json.loads(pathlib.Path(refix.cut(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual(brief["plan_items"], [])

    def test_cut_writes_seat_file_only_in_g3(self):
        """修正の形 g3 の 1 回目の審査の支度だけが、task-review の型を埋めた座を review1-seat.md に書き、brief の seat_file と
        must に名指す（型の穴は brief・方針・直した側の出力・切った版・差分のファイル）。g3 でなければ seat_file は空"""
        repo = self.fixed()
        fixshape.choose(self.board, "af", by="test", why="差分の審査役の座が g3 だけで出ることの確かめ")
        brief = json.loads(pathlib.Path(refix.cut(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual(brief["seat_file"], "")
        fixshape.choose(self.board, "g3", by="test", why="差分の審査役の座が g3 だけで出ることの確かめ")
        got = refix.cut(self.board, 1, repo)
        brief = json.loads(pathlib.Path(got["brief_file"]).read_text(encoding="utf-8"))
        path = pathlib.Path(brief["seat_file"])
        self.assertEqual(path.name, "review1-seat.md")
        self.assertIn(str(path), got["must"])
        text = path.read_text(encoding="utf-8")
        b = real_entry.open_board(self.board)
        d = b.loop_state["fix_delta"]
        for w in (seat.HEAD, got["brief_file"], d["file"], d["rev"], b.loop_state["reviewed_revision"],
                  str(self.board / b.state["outputs"]["p3.fix"]["file"]), seat.NONE, seat.words_table("task-review")):
            self.assertIn(w, text)
        self.assertNotRegex(text.split(refix.rolekit.skill_overlay().strip())[0], r"\[[A-Z][A-Z_]+\]")
        self.assertEqual(refix.must(self.board, "review"), got["must"])
        fixshape.choose(self.board, "af", by="test", why="形を戻すと前の試みの座のファイルが消えることの確かめ")
        brief = json.loads(pathlib.Path(refix.cut(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual(brief["seat_file"], "")
        self.assertFalse(path.exists())

    def test_plain_run_review_has_no_plan_duty(self):
        """平の run（修正の形 current）の修正役は修正案を見ない: 範囲の欄の在る控えが在っても、審査役の brief の plan_items は空で、
        準拠は not_applicable だけを受け、手直しの brief にも準拠の行と項目が載らない（current を見ていない案で裁かない）"""
        repo = self.fixed()
        self.plan_fields(scoped=True)
        fixshape.choose(self.board, "current", by="test", why="平の run の準拠が not_applicable になることの確かめ")
        brief = json.loads(pathlib.Path(refix.cut(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual((brief["plan_items"], brief["seat_file"]), ([], ""))
        reply = load("fix2_delta_review_faces")
        reply["compliance"] = {"verdict": "fail", "read": "修正案の項目 1 と差分の stats.py を読み、項目と差分を照らした",
                               "items": [{"item": 1, "kind": "misunderstood", "face_key": RF.F1,
                                          "why": "brief は docstring も直すと書くが、差分は式だけを直した"}]}
        reply["quality"] = {"verdict": "pass", "why": "準拠に結ばれていない穴は無く、テストの形の問題も見当たらない"}
        got = refix.accept_review(reply, self.board, "", repo, n=1)
        self.assertFalse(got["ok"])
        self.assertIn("compliance.verdict（fail）", got["reason"])
        got = refix.accept_review(load("fix2_delta_review_faces"), self.board, "", repo, n=1)   # not_applicable
        self.assertTrue(got["ok"], got)
        brief = json.loads(pathlib.Path(refix.prep_fix(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual((brief["plan_items"], brief["compliance"]), ([], []))

    def held_board(self):
        """p3.fix まで受けた盤面に、範囲の欄の控えと裁定 2 件（項目 2 の単位 K2 に fix_plan_item、K1 に fix_code_as と範囲
        test_stats.py:3）を置く"""
        repo = self.fixed()
        self.plan_fields(scoped=True)
        b = real_entry.open_board(self.board)
        base = {"between": ["stats.py:3", "test_stats.py:2"], "why_both_cannot_hold": "テストと依頼が両方は成り立たない",
                "which_is_right": "request", "kind": "scope_needed", "round": b.round, "source": "fix", "status": "ruled"}
        rows = [{**base, "id": "c1-1", "unit_key": RF.K2,
                 "ruling": {"decision": "fix_plan_item", "text": "案の項目 2 の範囲が誤り", "limits": [], "by": "x",
                            conflict.PLAN_ITEMS: [2], conflict.PLAN_UNITS: [RF.K2]}},
                {**base, "id": "c1-2", "unit_key": RF.K1,
                 "ruling": {"decision": "fix_code_as", "text": "式を定義どおりに直す", "limits": ["test_stats.py:3"], "by": "x"}}]
        b.work(conflict.FILE).write_text(json.dumps({"items": rows}, ensure_ascii=False), encoding="utf-8")
        return repo

    def test_cut_brief_marks_held_items_and_ruled_paths(self):
        """裁定で外れた項目は番号を保ったまま held（外した裁定）を持ち、直す裁定の limits のパスは ruled_paths に並ぶ"""
        repo = self.held_board()
        brief = json.loads(pathlib.Path(refix.cut(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual([it["item"] for it in brief["plan_items"]], [1, 2])
        self.assertNotIn("held", brief["plan_items"][0])
        self.assertIn("fix_plan_item の裁定 c1-1", brief["plan_items"][1]["held"])
        self.assertEqual(brief["ruled_paths"], ["test_stats.py"])

    def test_refix_brief_marks_held_items_and_ruled_paths(self):
        """手直しの役の brief も、外れた項目の held と直す裁定が広げたパス ruled_paths を載せる"""
        repo = self.held_board()
        self.assertTrue(refix.cut(self.board, 1, repo)["ok"])
        reply = load("fix2_delta_review_faces")
        reply["compliance"] = {"verdict": "pass", "items": [], "read": "修正案の項目 1・2 と差分の stats.py を読み、項目と照らした"}
        got = refix.accept_review(reply, self.board, "", repo, n=1)
        self.assertTrue(got["ok"], got)
        brief = json.loads(pathlib.Path(refix.prep_fix(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        self.assertEqual(brief["ruled_paths"], ["test_stats.py"])
        self.assertIn("fix_plan_item の裁定 c1-1", brief["plan_items"][1]["held"])
        self.assertNotIn("held", brief["plan_items"][0])

    def test_cut_brief_marks_partly_held_item(self):
        """2 単位の項目のうち K1 だけが ask_human で外れた → 項目に held は無く、held_units に K1 と外した裁定が載る"""
        repo = self.fixed(plan=RF.one_item_plan_reply())
        self.plan_fields(scoped=True, keys=(RF.K1,))
        b = real_entry.open_board(self.board)
        row = {"id": "c1-1", "unit_key": RF.K1, "between": ["stats.py:3", "test_stats.py:2"],
               "why_both_cannot_hold": "テストと依頼が両方は成り立たない", "which_is_right": "unknown", "kind": "needs_context",
               "round": b.round, "source": "fix", "status": "ruled",
               "ruling": {"decision": "ask_human", "text": "方針の変更で人が決める", "limits": [], "by": "x"}}
        b.work(conflict.FILE).write_text(json.dumps({"items": [row]}, ensure_ascii=False), encoding="utf-8")
        brief = json.loads(pathlib.Path(refix.cut(self.board, 1, repo)["brief_file"]).read_text(encoding="utf-8"))
        it = brief["plan_items"][0]
        self.assertNotIn("held", it)
        self.assertEqual(list(it["held_units"]), [RF.K1])
        self.assertIn("ask_human の裁定 c1-1", it["held_units"][RF.K1])

    def test_verdict_gaps_and_shape_errors_in_one_rejection(self):
        """2 判定の欄の欠けと、欄を外した返答の写しの型の誤りを 1 回の拒否に並べる（3 回の枠を誤り 1 つずつで使い切らせない）"""
        repo = self.fixed()
        refix.cut(self.board, 1, repo)
        reply = load("fix2_delta_review_faces")
        del reply["quality"]
        reply["faces"][0]["kind"] = "not_a_kind"
        got = refix.accept_review(reply, self.board, "", repo, n=1)
        self.assertFalse(got["ok"])
        self.assertTrue(got["reason"].startswith(deltamarks.REJECT), got["reason"])
        self.assertIn("quality", got["reason"])
        self.assertIn("not_a_kind", got["reason"])

    def test_missing_on_held_item_does_not_become_owed(self):
        """審査役が外れた項目 2 を missing と書いて穴に結ぶ → 受け付けが拒み（盤面は前のまま）、手直しの義務にならない"""
        repo = self.held_board()
        self.assertTrue(refix.cut(self.board, 1, repo)["ok"])
        before = RF.TE.board_shas(self.board)
        reply = load("fix2_delta_review_faces")
        reply["compliance"] = {"verdict": "fail", "read": "修正案の項目 2 と差分の stats.py を読み、項目と差分を照らした",
                               "items": [{"item": 2, "kind": "missing", "face_key": RF.F1,
                                          "why": "項目 2 の clamp の直しが差分に無いので、項目どおりに直していない"}]}
        reply["quality"] = {"verdict": "pass", "why": "準拠に結ばれていない穴は無く、テストの形の問題も見当たらない"}
        got = refix.accept_review(reply, self.board, "", repo, n=1)
        self.assertFalse(got["ok"])
        self.assertTrue(got["reason"].startswith(deltamarks.REJECT), got["reason"])
        self.assertIn("held", got["reason"])
        self.assertEqual(RF.TE.board_shas(self.board), before)

    def test_review_faces_make_owed(self):
        """fix2_delta_review_faces（穴 1 件・塞がっていない検算 1 件）→ settle の後 loop.delta_owed に 2 件、ready に
        p3.delta_fix、collect_delta の owed ≥ 1"""
        repo, got = self.reviewed("fix2_delta_review_faces")
        self.assertIn("p3.delta_fix", got["ready"])
        b = real_entry.open_board(self.board)
        self.assertEqual({r["key"] for r in b.loop_state["delta_owed"]["rows"]}, {RF.F1, RF.PR_KEY})
        out = refix.collect_delta(self.board)
        self.assertEqual((out["faces"], out["owed"]), (1, 2))

    def test_review_none_skips_refix(self):
        """fix2_delta_review_none（faces_none・検算は塞がった）→ ready に p3.delta_fix が無い、owed 0"""
        repo, got = self.reviewed("fix2_delta_review_none")
        self.assertNotIn("p3.delta_fix", got["ready"])
        self.assertIn("p4.ci", got["ready"])
        self.assertEqual((refix.collect_delta(self.board)["owed"], refix.route(self.board)["owed"]), (0, 0))

    def test_review_policy_kind_rejected(self):
        """regression・policy の語の穴 → ok False（事前審査だけの kind。修正の後の後退・方針は R4 と関所の担当）。盤面は前のまま"""
        repo = self.fixed()
        refix.cut(self.board, 1, repo)
        before = RF.TE.board_shas(self.board)
        for kind in ("policy", "regression"):
            with self.subTest(kind):
                reply = load("fix2_delta_review_policy_kind")
                reply["faces"][0]["kind"] = kind
                got = refix.accept_review(reply, self.board, "", repo, n=1)
                self.assertFalse(got["ok"])
                self.assertIn(kind, got["reason"])
                self.assertEqual(RF.TE.board_shas(self.board), before)

    def test_review_readonly_tree_changed(self):
        """写しの後に作業ツリーを変える → ok False（読むだけの役が作業ツリーを変えた）。戻せば通る"""
        repo = self.fixed()
        refix.cut(self.board, 1, repo)
        (repo / "stray.txt").write_text("審査役が書いた\n", encoding="utf-8")
        got = refix.accept_review(load("fix2_delta_review_none"), self.board, "", repo, n=1)
        self.assertFalse(got["ok"])
        self.assertTrue(got["reason"].startswith(real_entry.READONLY_MOVED), got["reason"])
        self.assertIn("stray.txt", got["reason"])
        (repo / "stray.txt").unlink()
        self.assertTrue(refix.accept_review(load("fix2_delta_review_none"), self.board, "", repo, n=1)["ok"])

    def test_review_face_outside_touched_files_rejected(self):
        """触っていないファイルの穴・今の姿に無い cite → ok False（写しの delta_review_output の文）。1 本目の bad-cite と同じ主張"""
        repo = self.fixed()
        refix.cut(self.board, 1, repo)
        for where, cite, word in (("test_stats.py", "import unittest", "触ったファイルでない"),
                                  ("stats.py", "return hi + 1", "今の姿に無い")):
            with self.subTest(where=where, cite=cite):
                reply = load("fix2_delta_review_faces")
                reply["faces"][0].update(where=where, cite=cite)
                got = refix.accept_review(reply, self.board, "", repo, n=1)
                self.assertFalse(got["ok"])
                self.assertIn(word, got["reason"])

    def test_accept_review_strips_and_saves_verdicts(self):
        """修正案の欄を控えない盤面（not_applicable）: 2 判定の欄を外した返答が盤面に渡り、欄は盤面の外の控えに置かれる"""
        repo = self.fixed()
        refix.cut(self.board, 1, repo)
        self.assertTrue(refix.accept_review(load("fix2_delta_review_faces"), self.board, "", repo, n=1)["ok"])
        b = real_entry.open_board(self.board)
        self.assertNotIn("compliance", b.output_of_round("p3.delta_review", b.round))
        self.assertEqual(deltamarks.read(b)["compliance"]["verdict"], "not_applicable")

    def test_accept_review_rejects_missing_verdicts(self):
        """2 判定の欄が欠けた返答 → 拒否の文の頭は deltamarks.REJECT、盤面は前のまま"""
        repo = self.fixed()
        refix.cut(self.board, 1, repo)
        before = RF.TE.board_shas(self.board)
        reply = load("fix2_delta_review_none")
        del reply["quality"]
        got = refix.accept_review(reply, self.board, "", repo, n=1)
        self.assertFalse(got["ok"])
        self.assertTrue(got["reason"].startswith(deltamarks.REJECT), got["reason"])
        self.assertEqual(RF.TE.board_shas(self.board), before)

    def test_old_plan_fields_accept_not_applicable(self):
        """217 番の形の控え（範囲の欄が無い）は範囲の無い run と同じ: 準拠の not_applicable を受ける。範囲の在る控えでは拒む"""
        repo = self.fixed()
        refix.cut(self.board, 1, repo)
        self.plan_fields(scoped=True)
        got = refix.accept_review(load("fix2_delta_review_none"), self.board, "", repo, n=1)
        self.assertFalse(got["ok"])
        self.assertIn("compliance.verdict（not_applicable）", got["reason"])
        self.plan_fields(scoped=False)
        got = refix.accept_review(load("fix2_delta_review_none"), self.board, "", repo, n=1)
        self.assertTrue(got["ok"], got)

    def test_broken_plan_fields_halt_board(self):
        """修正案の欄の控えが凍結の印と食い違う → 控えを名指す BoardGap で盤面を止める（conflict.fields_broken の道）"""
        repo = self.fixed()
        refix.cut(self.board, 1, repo)
        self.plan_fields(scoped=True)
        (self.board / planmarks.FIELDS_FILE).write_text("{}", encoding="utf-8")
        with self.assertRaises(BoardGap) as cm:
            refix.accept_review(load("fix2_delta_review_none"), self.board, "", repo, n=1)
        self.assertIn(planmarks.FIELDS_FILE, str(cm.exception))
        stop = real_entry.open_board(self.board, allow_halted=True).state["stop"]
        self.assertEqual(stop["by"], refix.DELTA_BY)   # 差分の審査の段の印（修正の段の印・文でない）
        self.assertTrue(stop["reason"].startswith(conflict.FIELDS_TAMPERED), stop["reason"])
        self.assertNotIn("テストの変更の許し", stop["reason"])

    def test_unsaved_verdicts_halt_board(self):
        """盤面が審査を受けた後で 2 判定の控えを置けない（os.replace が落ちる）→ 控えを名指して盤面を止め、スクリプトは 2"""
        repo = self.fixed()
        refix.cut(self.board, 1, repo)
        real_entry.open_board(self.board).work(deltamarks.VERDICTS_FILE).mkdir()   # ファイルを置き換えられない所
        r = self.run_script("blk-delta", "accept", repo, reply=json.dumps(load("fix2_delta_review_none"), ensure_ascii=False),
                            base_rev="")
        self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        self.assertIn(deltamarks.VERDICTS_FILE, r.stderr)
        b = real_entry.open_board(self.board, allow_halted=True)
        self.assertEqual(b.state["stop"]["by"], refix.DELTA_BY)
        self.assertIn(deltamarks.VERDICTS_FILE, b.state["stop"]["reason"])

    def test_rejected_take_keeps_no_verdicts(self):
        """2 判定の欄は通るが盤面が拒む（cite が差分の今の姿に無い）→ 控えを置かない"""
        repo = self.fixed()
        refix.cut(self.board, 1, repo)
        reply = load("fix2_delta_review_faces")
        reply["faces"][0]["cite"] = "return hi + 1"
        got = refix.accept_review(reply, self.board, "", repo, n=1)
        self.assertFalse(got["ok"])
        self.assertFalse(got["reason"].startswith(deltamarks.REJECT), got["reason"])
        self.assertIsNone(deltamarks.read(real_entry.open_board(self.board)))

    def test_malformed_faces_go_to_board_check(self):
        """faces が穴の並びの形でない → 2 判定の欄は照らさず、写しの型の拒否の文で返す（盤面は前のまま）"""
        repo = self.fixed()
        refix.cut(self.board, 1, repo)
        before = RF.TE.board_shas(self.board)
        reply = load("fix2_delta_review_faces")
        reply["faces"] = "x"
        got = refix.accept_review(reply, self.board, "", repo, n=1)
        self.assertFalse(got["ok"])
        self.assertFalse(got["reason"].startswith(deltamarks.REJECT), got["reason"])
        self.assertIn("faces", got["reason"])
        self.assertNotIn("compliance", got["reason"])   # 守る欄を消せと役に言わない（試行を 1 回むだにしない）
        self.assertNotIn("quality", got["reason"])
        self.assertEqual(RF.TE.board_shas(self.board), before)

    def test_delta_exit_keeps_v1_fields(self):
        """collect_delta の鍵 ⊇ {ok, faces, review_file, diff_file}（1 本目の出口）。足すのは owed・fix_rev・reads_file"""
        repo, _ = self.reviewed("fix2_delta_review_faces")
        out = refix.collect_delta(self.board)
        self.assertEqual(set(out), {"ok", "faces", "review_file", "diff_file", "owed", "fix_rev", "reads_file"})
        b = real_entry.open_board(self.board)
        self.assertEqual(out["review_file"], str(self.board / b.state["outputs"]["p3.delta_review"]["file"]))
        self.assertEqual((out["diff_file"], out["fix_rev"]), (b.loop_state["fix_delta"]["file"], b.loop_state["fix_delta"]["rev"]))
        self.assertEqual(json.loads(pathlib.Path(out["review_file"]).read_text(encoding="utf-8"))["faces"][0]["key"], RF.F1)
        self.assertEqual(out["reads_file"], "")
        yaml_collect = find_node(workflow("blk-delta")["nodes"], "collect")["output_format"]
        self.assertLessEqual(set(yaml_collect["required"]), set(out))

    def test_cut_removes_stale_outputs(self):
        """新しい審査の前に、前の試みの自分の出力（brief・reads-review.json、1 本目が盤面の根に書いた delta-review.json・
        fix.diff・delta-snapshot.json）を消す。出口は盤面の今の周の返答だけを数え、前の審査の穴を数えない（自分食いの 1 本目の穴）"""
        repo = self.fixed()
        b = real_entry.open_board(self.board)
        stale = {"faces": [{"key": f"前の審査の穴 {i}"} for i in range(5)], "checks": []}
        planted = [self.board / name for name in ("delta-review.json", "fix.diff", "delta-snapshot.json")]
        planted += [b.work("reads-review.json"), b.work("review1-brief.json"), b.work(deltamarks.VERDICTS_FILE)]
        for p in planted:
            p.write_text(json.dumps(stale, ensure_ascii=False), encoding="utf-8")
        got = refix.cut(self.board, 1, repo)
        self.assertEqual([p for p in planted if p.exists() and str(p) != got["brief_file"]], [])
        self.assertNotIn("前の審査の穴", pathlib.Path(got["brief_file"]).read_text(encoding="utf-8"))
        with self.assertRaises(BoardGap):   # まだ受け付けていない審査の出口は組まない（前の試みの物を数えない）
            refix.collect_delta(self.board)
        refix.accept_review(load("fix2_delta_review_none"), self.board, "", repo, n=1)
        out = refix.collect_delta(self.board)
        self.assertEqual((out["faces"], out["reads_file"]), (0, ""))

    def test_cut_untracked_japanese_bytecode(self):
        """修正が足した未追跡のファイルと日本語の名前も、盤面の差分と files にそのままの名前で載り、その cite は受け付けを通る。
        テストが作ったバイトコード（種の .gitignore が無視する）は載らない。入れ子の git リポジトリ（未追跡）でも写しは落ちない"""
        def extra(repo):
            (repo / "日本.py").write_text("def 日付():\n    return 1\n", encoding="utf-8")
            git(repo, "add", "日本.py")                                    # 追跡している側
            (repo / "未追跡.py").write_text("x = 1\n", encoding="utf-8")   # 未追跡の側
            sub = repo / "sub"
            sub.mkdir()
            (sub / "a.txt").write_text("a\n")
            git(sub, "init", "-q")
            git(sub, "add", "-A")
            git(sub, "commit", "-q", "-m", "sub")
            env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
            subprocess.run([sys.executable, "-m", "unittest", "-q", "test_stats"], cwd=str(repo), env=env,
                           capture_output=True, stdin=subprocess.DEVNULL)
            self.assertTrue(list(repo.rglob("*.pyc")))                    # バイトコードは本当に出来た
        repo = self.fixed(before_fix=extra)
        got = refix.cut(self.board, 1, repo)
        self.assertTrue(got["ok"], got)
        self.assertTrue({"stats.py", "日本.py", "未追跡.py"} <= set(got["files"]), got["files"])
        self.assertFalse([f for f in got["files"] if f.endswith(".pyc") or "__pycache__" in f], got["files"])
        patch = pathlib.Path(got["diff_file"]).read_text(encoding="utf-8", errors="replace")
        # 差分のファイルは写しの RL の fix_delta が書く（git diff のまま）。日本語のパスは git の既定（core.quotepath）で
        # 8 進の引用になる——1 本目の cut（字のまま）との差で、名前の正本は files（-z で引いた字のまま）。中身は載る
        quoted = '"b/' + "".join(f"\\{b:03o}" for b in "未追跡".encode("utf-8")) + '.py"'
        self.assertIn(quoted, patch)
        self.assertIn("+x = 1", patch)
        self.assertIn("+def 日付():", patch)
        self.assertNotIn(".pyc", patch)
        reply = {"faces": [{"key": f"{where} 使われない物", "kind": "dead_path", "where": where, "cite": cite,
                            "why": "どこからも呼ばれない物を修正が足している"} for where, cite in
                           (("日本.py", "def 日付():"), ("未追跡.py", "x = 1"))],
                 "checks": load("fix2_delta_review_none")["checks"],
                 "compliance": load("fix2_delta_review_faces")["compliance"], "quality": load("fix2_delta_review_faces")["quality"]}
        res = refix.accept_review(reply, self.board, "", repo, n=1)
        self.assertTrue(res["ok"], res.get("reason"))

    def test_delta_scripts(self):
        """cut・accept・collect をスクリプトで。受けていない出口（collect）・支度に要る物が無い（cut）・環境変数の欠けは 2 で
        標準出力は空。中身の拒否は 0 と 1 行（reason_file つき）"""
        repo = self.fixed()
        r = self.run_script("blk-delta", "collect", repo)
        self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        env_less = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_") and k != "ARTIFACTS_DIR"}
        r = subprocess.run([sys.executable, str(ROOT / "blk-delta" / "scripts" / "cut.py")], cwd=str(repo),
                           env={**env_less, "PYTHONDONTWRITEBYTECODE": "1"}, capture_output=True, text=True, encoding="utf-8",
                           stdin=subprocess.DEVNULL)
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        r = self.run_script("blk-delta", "cut", repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(json.loads(r.stdout)["files"], ["stats.py"])
        bad = load("fix2_delta_review_faces")
        bad["faces"][0]["where"] = "test_stats.py"
        r = self.run_script("blk-delta", "accept", repo, reply=json.dumps(bad, ensure_ascii=False), base_rev="")
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertFalse(got["ok"])
        self.assertEqual(pathlib.Path(got["reason_file"]).read_text(encoding="utf-8"), got["reason"])
        r = self.run_script("blk-delta", "accept", repo, reply=json.dumps(load("fix2_delta_review_faces"), ensure_ascii=False),
                            base_rev="")
        self.assertTrue(json.loads(r.stdout)["ok"], r.stdout)
        r = self.run_script("blk-delta", "collect", repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual({k: json.loads(r.stdout)[k] for k in ("ok", "faces", "owed")}, {"ok": True, "faces": 1, "owed": 2})
        r = self.run_script("blk-delta", "cut", repo)                    # 審査は済んだ（待っていない）→ 配線の誤り
        self.assertEqual((r.returncode, r.stdout), (2, ""), r.stderr)
        for name, inputs in (("cut", ()), ("accept", ("INPUTS_REPLY", "INPUTS_BASE_REV")), ("collect", ()),
                             ("reads", ("INPUTS_MUST",))):
            with self.subTest(name):
                src = (ROOT / "blk-delta" / "scripts" / f"{name}.py").read_text(encoding="utf-8")
                m = re.search(r"^INPUTS = (\(.*?\))", src, re.M)
                self.assertEqual(eval(m.group(1)), inputs)   # noqa: S307（自分のリポジトリの定数の字）
        self.assertFalse([*CORE.rglob("__pycache__")])


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


if __name__ == "__main__":
    unittest.main()
