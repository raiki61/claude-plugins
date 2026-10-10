"""線 A の入口のモジュール（.shared/core/entry.py）の表の分と、darkfactory の節の表（darkfactory/nodes.json）の検査。

表は手で書き、ここで写しの graph と突き合わせる（盤面の層の縛り 1〜5 と、線 A の行の決まり）。行の決まりは線 A の仕様 4 節と
持ち主の答え（2026-09-27）: p0.premises は役（blk-premises）、p0.parallel_pr は engine_run で任せ先は読むだけの役（blk-pr）、
p2.rejudge は役（blk-rejudge。包みが判定役の会話を継ぐ）、p2.rejudge_third は absent（0.21.0 の規則で ready にならない）、p0.purpose は役（blk-purpose）、手厚さは標準だけ。
盤面を作る試験は linekit の種（dev/target-seed/）を使い捨ての家（linekit.work_home()）の下に置いて回す。
"""
import contextlib
import json
import os
import pathlib
import shutil
import sys
import tempfile
import unittest
from unittest import mock

TESTS = pathlib.Path(__file__).resolve().parent
ROOT = TESTS.parent
CORE = ROOT / ".shared" / "core"
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(TESTS))

import board  # noqa: E402
from board import BoardGap, BoardMismatch, DiskBoard, graph_expanded  # noqa: E402
import engine.declared as engine_declared  # noqa: E402  （board が写しの graphloops を sys.path に足す）
import engine.util as engine_util  # noqa: E402
import carry  # noqa: E402
import entry  # noqa: E402
import entryshape  # noqa: E402  （入口の変換）
import startrec  # noqa: E402  （始めの記録の読み口）
import gatemarks  # noqa: E402
import linekit  # noqa: E402
import scopes  # noqa: E402
import stopby  # noqa: E402  （止めの理由の住処）
import webget  # noqa: E402

GRAPH = graph_expanded()
TABLE_PATH = ROOT / "darkfactory" / "nodes.json"
ROLES = {"p0.premises", "p2.diagnose", "p2.fix_plan", "p2.plan_review", "p3.fix", "p3.delta_review", "p3.delta_fix",
         "p3.delta_review2", "p3.delta_fix2", "p2.rejudge", "p0.purpose"}
# 独立の目（blk-eyes。計画 P1 Task 33）の行（tests/boards/tables/eyes-rows.json の案をそのまま当てた）
EYES = {"r1.comment_candidates", "r1.minimality", "r2.compare", "r3.coherence", "r4.hidden_scope",
        "stop.premise_check"}
# P1 の目と素材集め（blk-material。計画 P1 Task 32）
MATERIAL = {"p0.prior_decisions", "p0.purpose_review", "p1.local_review", "p1.consistency_bypass", "p1.hygiene",
            "p1.external_standards", "p1.procedure_trace", "p1.gate_efficacy", "p1.test_double_fidelity",
            "p1.main_path_observation", "p1.provenance"}
# 仕様の段（blk-spec。入力 spec=on の run だけ。計画 docs/plans/2026-10-09-one-entry-shape.md の 4 節）
SPEC = {"spec.write", "spec.review", "spec.revise"}
ROLES |= EYES | MATERIAL | SPEC | {"report", "r2.design"}


def raw_table() -> dict:
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))


class TableCase(unittest.TestCase):
    def setUp(self):
        self.table = entry.load_table("darkfactory")
        self.nodes = self.table.nodes

    def test_table_passes_board_rules(self):
        """load_table が BoardGap を出さない（盤面の層の縛り 1〜5）。表の line は darkfactory、graph_sha は写しの graph"""
        self.assertEqual(self.table.check(GRAPH, board.GRAPH_SHA), [])
        self.assertEqual(self.table.line, "darkfactory")
        self.assertEqual(self.table.graph_sha, board.GRAPH_SHA)
        self.assertEqual(entry.PACK, ROOT)
        self.assertEqual(entry.TABLE_NAME, "nodes.json")

    def test_every_graph_node_once(self):
        """表の鍵の集合が graph の節の集合と同じ（60）。ファイルの中でも 1 度ずつ（同じ鍵 2 度は load が拒む）"""
        self.assertEqual(set(self.nodes), set(GRAPH["nodes"]))
        self.assertEqual(len(self.nodes), 60)
        self.assertEqual(len(raw_table()["nodes"]), 60)

    def test_absent_rows_have_reason_and_comes_with(self):
        absent = {n: e for n, e in self.nodes.items() if e.by == "absent"}
        self.assertTrue(absent)
        for nid, e in absent.items():
            with self.subTest(nid):
                self.assertTrue(e.reason.strip())
                self.assertTrue(e.comes_with.strip())
                self.assertFalse(e.where)

    def test_later_rows_take_the_owner_answers(self):
        """持ち主の答え（2026-09-27）の行: 前提の実測・並行 PR・同じ周の再審。where はブロックの名だけ、持ち方の説明は reason"""
        pre = self.nodes["p0.premises"]
        self.assertEqual((pre.by, pre.fallback), ("role", ""))
        self.assertEqual(pre.where, "blk-premises")
        pr = self.nodes["p0.parallel_pr"]
        self.assertEqual((pr.by, pr.fallback), ("engine_run", "role"))
        self.assertEqual(pr.where, "blk-entry")
        self.assertIn("blk-pr", pr.reason)
        self.assertIn("投稿しない", pr.reason)
        self.assertIn("スコープから外す", pr.reason)   # review-graph の 6 段と同じく、衝突した hunk はこのループで触らない（Task 21）
        self.assertEqual((self.nodes["p2.rejudge"].by, self.nodes["p2.rejudge"].where), ("role", "blk-rejudge"))
        self.assertIn("会話を継ぐ", self.nodes["p2.rejudge"].reason)
        self.assertEqual(self.nodes["p2.rejudge_third"].by, "absent")
        self.assertIn("ready にならない", self.nodes["p2.rejudge_third"].reason)

    def test_where_is_a_plain_block_name(self):
        """where はブロックの名か start だけ（線 B の表と合流の時に比べる。説明の文は reason に置く）。absent と builtin は書かない"""
        for nid, e in self.nodes.items():
            with self.subTest(nid):
                if e.by in ("absent", "builtin"):
                    self.assertEqual(e.where, "")
                else:
                    self.assertRegex(e.where, r"\A(?:start|blk-[a-z0-9]+(?:-[a-z0-9]+)*)\Z")

    def test_purpose_and_material_rows(self):
        """目的の文は blk-purpose（独立の目の R1・R2 と判定が読む）。目的の審査・前の決定・P1 の 9 本は blk-material
        （計画 P1 Task 32）。P1 の行は判定から入る 1 周目に条件で na と書く"""
        e = self.nodes["p0.purpose"]
        self.assertEqual((e.by, e.where), ("role", "blk-purpose"))
        self.assertIn("h-mat", e.reason)
        for nid in MATERIAL:
            with self.subTest(nid):
                e = self.nodes[nid]
                self.assertEqual((e.by, e.where), ("role", "blk-material"))
                if nid.startswith("p1."):
                    self.assertIn("1 周目は", e.reason)
                    self.assertIn("条件", e.reason)

    def test_eyes_rows_follow_block_proposal(self):
        """独立の目の 6 行は blk-eyes の案（eyes-rows.json）と同じ。r1.comment_candidates だけ skippable。R2 の設計の半分
        （r2.design）は修正案と同じ blk-plan で修正の前に作る（ほかのブロックが同じ節を拾わない）"""
        rows = json.loads((TESTS / "boards" / "tables" / "eyes-rows.json").read_text(encoding="utf-8"))
        self.assertEqual(set(rows), EYES)
        for nid, row in rows.items():
            with self.subTest(nid):
                self.assertEqual(raw_table()["nodes"][nid], row)
        self.assertEqual((self.nodes["r2.design"].by, self.nodes["r2.design"].where), ("role", "blk-plan"))

    def test_roles_are_track_a_nodes(self):
        roles = {n for n, e in self.nodes.items() if e.by == "role"}
        self.assertEqual(roles, ROLES)
        for nid in roles:
            with self.subTest(nid):
                self.assertTrue(self.nodes[nid].where.startswith("blk-"), self.nodes[nid].where)
        self.assertEqual(self.nodes["p2.diagnose"].where, "blk-judge")
        self.assertIn("h-plan", self.nodes["p2.diagnose"].reason)

    def test_machine_and_builtin_rows(self):
        """機械の節は p0.base だけ（start の begin）。graph の driver の 17 節は全部 builtin・auto"""
        self.assertEqual({n for n, e in self.nodes.items() if e.by == "machine"}, {"p0.base"})
        self.assertEqual(self.nodes["p0.base"].where, "blk-entry")
        drivers = {n for n, g in GRAPH["nodes"].items() if g.get("run_by") == "driver"}
        self.assertEqual(len(drivers), 17)
        builtins = {n for n, e in self.nodes.items() if e.by == "builtin"}
        self.assertEqual(builtins, drivers)
        self.assertEqual({self.nodes[n].run for n in builtins}, {"auto"})

    def test_ci_nodes_fall_back_to_machine(self):
        for nid, where in (("p0.local_checks", "blk-entry"), ("p4.ci", "blk-tests")):
            with self.subTest(nid):
                e = self.nodes[nid]
                self.assertEqual((e.by, e.fallback), ("engine_run", "machine"))
                self.assertEqual(e.where, where)
                # 任せ先に落ちて test_cmd も空なら、役のブロック blk-ci が渡す（裁定 R52。where は入口のまま。R42）
                self.assertIn("blk-ci", e.reason)
        self.assertEqual({n for n, e in self.nodes.items() if e.by == "engine_run"},
                         {"p0.local_checks", "p0.parallel_pr", "p4.ci"})

    def test_only_optional_comment_candidates_skippable(self):
        """graph で optional でない節は省かない（持ち主の答え 1）。skippable は graph で optional の r1.comment_candidates と、軽量の深さで
        省ける差分の審査と独立の目 R1〜R4（持ち主の決定 2026-10-06。写しの graph の ! 行で optional にした）
        （3 回とも拒まれたら省いて R1 の本体へ。graph: 取れなくても R1 を not_run に倒さない）"""
        self.assertEqual({n for n, e in self.nodes.items() if e.skippable},
                         {"r1.comment_candidates", "p3.delta_review", "r1.minimality", "r2.compare", "r3.coherence",
                          "r4.hidden_scope"})

    def test_report_rows_are_blk_report(self):
        """報告の役の節 report は blk-report の役（計画 P1 Task 34。ml-report の案の行）。頭と初見検査の節は absent（書き手が頭も
        書き、輪の中の初見の読み手が確かめる。2026-10-09 の片付け）。graph の pre: finalize の節は report だけ——
        その関所（settle の RecordInvalid）は機械の報告の gate_record が受けて record_invalid にする（test_report）"""
        self.assertEqual((self.nodes["report"].by, self.nodes["report"].where), ("role", "blk-report"))
        self.assertIn("R27", self.nodes["report"].reason)
        for nid in ("report.human_items", "report.cold_check"):
            with self.subTest(nid):
                self.assertEqual(self.nodes[nid].by, "absent")
        self.assertEqual({n for n, g in GRAPH["nodes"].items() if g.get("pre") == "finalize"}, {"report"})

    def test_later_lines_name_their_line(self):
        """周を重ねる入口・変異の検算・別の入口の行は comes_with にその名（線 B・線 C は棚上げと書く。2026-10-09）"""
        want = {"p2.history": "棚上げ 2026-10-09", "p3.delta_gates": "棚上げ 2026-10-09", "p4.final_gates": "棚上げ 2026-10-09"}
        for nid, name in want.items():
            with self.subTest(nid):
                self.assertEqual(self.nodes[nid].by, "absent")
                self.assertIn(name, self.nodes[nid].comes_with)
        for nid in SPEC:   # 仕様の段は別の入口でなく、入口の種類に依らない任意の段として線に配線した
            self.assertEqual((self.nodes[nid].by, self.nodes[nid].where), ("role", "blk-spec"))
        p1 = [n for n in GRAPH["nodes"] if n.startswith("p1.") and GRAPH["nodes"][n].get("run_by") != "driver"]
        self.assertEqual(set(p1), {n for n in MATERIAL if n.startswith("p1.")})


class LoadTableCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        self.pack = pathlib.Path(self._tmp.name) / "pack"
        (self.pack / "darkfactory").mkdir(parents=True)

    def tearDown(self):
        self._tmp.cleanup()

    def put(self, doc, line="darkfactory"):
        (self.pack / line).mkdir(parents=True, exist_ok=True)
        (self.pack / line / "nodes.json").write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")

    def test_every_breach_in_one_message(self):
        """縛りの破れは全部を 1 つの BoardGap の文に並べる"""
        doc = raw_table()
        doc["nodes"]["p2.history"] = {"by": "role", "skippable": True, "where": "blk-judge"}   # optional の節だけ skippable は通る
        doc["nodes"]["p0.base"] = {"by": "absent"}                  # reason が空
        doc["nodes"]["p4.ci"] = {"by": "engine_run"}                # fallback が無い
        del doc["nodes"]["converge"]                                # graph の節が無い
        self.put(doc)
        with mock.patch.object(entry, "PACK", self.pack):
            with self.assertRaises(BoardGap) as cm:
                entry.load_table("darkfactory")
        msg = str(cm.exception)
        for part in ("p0.base", "p4.ci", "converge"):
            self.assertIn(part, msg)
        self.assertNotIn("p2.history", msg)

    def test_line_name_must_match(self):
        doc = raw_table()
        self.put(doc, line="other")
        with mock.patch.object(entry, "PACK", self.pack):
            with self.assertRaises(BoardGap) as cm:
                entry.load_table("other")
        self.assertIn("darkfactory", str(cm.exception))
        self.assertIn("other", str(cm.exception))

    def test_table_checked_against_its_graph(self):
        """表が名指す graph（仕様 tdd-spec 5 節）で縛りを当てる。TDD 版の表は TDD 版の graph で通り、graph の欄を落とすと
        既定の graph と照らして拒む（TDD の 4 節が graph に無い・graph_sha が違う）"""
        doc = json.loads((ROOT / "tests" / "boards" / "tables" / "tdd-line.json").read_text(encoding="utf-8"))
        self.put(doc, line="tdd-line")
        with mock.patch.object(entry, "PACK", self.pack):
            self.assertEqual(entry.load_table("tdd-line").graph, "review-loop-tdd.json")
            del doc["graph"]
            self.put(doc, line="tdd-line")
            with self.assertRaises(BoardGap) as cm:
                entry.load_table("tdd-line")
        self.assertIn("p3.tdd_red", str(cm.exception))
        self.assertIn(board.GRAPH_SHA, str(cm.exception))

    def test_missing_or_odd_line(self):
        with mock.patch.object(entry, "PACK", self.pack):
            for line in ("nowhere", "../darkfactory", "", "a/b"):
                with self.subTest(line):
                    with self.assertRaises(BoardGap):
                        entry.load_table(line)


class BoardCase(unittest.TestCase):
    """種のリポジトリに darkfactory の表で盤面を作り、entry.open_board で開く"""

    def setUp(self):
        self._old_cwd = engine_util.GIT_CWD
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        self.tmp = pathlib.Path(self._tmp.name)
        self.repo = linekit.seed_repo(self.tmp / "repo")

    def tearDown(self):
        engine_util.GIT_CWD = self._old_cwd
        self._tmp.cleanup()

    def create(self, name="board"):
        d = self.tmp / name
        DiskBoard.create(d, repo=self.repo, table=entry.load_table("darkfactory"), inputs={}, request_text="依頼")
        return d

    def edit_state(self, d, fn):
        p = d / "state.json"
        st = json.loads(p.read_text(encoding="utf-8"))
        fn(st)
        p.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def test_open_board_uses_state_line(self):
        d = self.create()
        b = entry.open_board(d)
        self.assertIsInstance(b, DiskBoard)
        self.assertEqual(b.table.line, "darkfactory")
        self.assertEqual(b.table.sha(), b.state["works"]["table_sha"])
        self.assertIsNone(b.validator_runner)
        good = b.state["works"]["table_sha"]
        bad = ("0" if good[0] != "0" else "1") + good[1:]
        self.edit_state(d, lambda st: st["works"].__setitem__("table_sha", bad))
        with self.assertRaises(BoardMismatch) as cm:
            entry.open_board(d)
        self.assertIn(good, str(cm.exception))
        self.assertIn(bad, str(cm.exception))

    def test_open_board_refuses_unknown_line(self):
        d = self.create()
        self.edit_state(d, lambda st: st["works"].__setitem__("line", "nowhere"))
        with self.assertRaises(BoardGap) as cm:
            entry.open_board(d)
        self.assertIn("nowhere", str(cm.exception))
        self.edit_state(d, lambda st: st["works"].pop("line"))
        with self.assertRaises(BoardGap):
            entry.open_board(d)

    def scoped(self, path: str, block: str = "blk-fix"):
        """include の中の script として開く文脈（Archon の ARCHON_NODE_EXECUTION と、起こされたスクリプトの場所）"""
        env = mock.patch.dict(os.environ, {"ARCHON_NODE_EXECUTION": json.dumps({"runId": "r", "path": path})})
        argv = mock.patch.object(sys, "argv", [str(ROOT / block / "scripts" / "x.py")])
        stack = contextlib.ExitStack()
        stack.enter_context(env)
        stack.enter_context(argv)
        return stack

    def test_open_board_scoped_places_private_names_under_scope(self):
        d = self.create()
        self.assertEqual(json.loads((d / "state.json").read_text(encoding="utf-8"))["works"]["layout"], board.LAYOUT)
        with self.scoped("fixing__fix-loop.fix-prep"):
            b = entry.open_board(d)
        self.assertEqual((b.scope, b.scope_root), ("fixing", d / "fixing"))
        self.assertEqual(b.work("rule-tree.json"), d / "fixing" / "r1" / "rule-tree.json")   # 私物は scope の根
        self.assertEqual(b.work("fix-held-reply.json"), d / "fixing" / "r1" / "fix-held-reply.json")   # per_include も
        self.assertEqual(b.work("start.json"), d / "r1" / "start.json")    # 線の公開の名は周の置き場
        self.assertEqual(b.work("conflicts.json"), d / "r1" / "conflicts.json")    # 共有の記録も周の置き場
        self.assertEqual(b.work("rejects-a/b.json"), d / "fixing" / "r1" / "rejects-a" / "b.json")   # * は段をまたがない
        reg = json.loads((d / "r1" / "scopes.json").read_text(encoding="utf-8"))
        self.assertEqual(reg, {"fixing": {"block": "blk-fix", "order": 1}})
        line = entry.open_board(d)   # 線の最上段（scope なし）は今の置き場のまま・登録しない
        self.assertEqual((line.scope, line.work("rule-tree.json")), ("", d / "r1" / "rule-tree.json"))
        with self.scoped("fixing__fix-loop.fix-prep", block="blk-plan"), self.assertRaises(BoardGap) as cm:
            entry.open_board(d)   # 同じ include の名を別のブロックが名乗る
        self.assertIn("blk-plan", str(cm.exception))

    def put(self, d, rel: str, text: str = "{}") -> pathlib.Path:
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        return p

    def window(self, d) -> dict:
        return json.loads((d / scopes.WINDOW).read_text(encoding="utf-8"))

    def line(self, node: str = "h-fix"):
        """線の最上段の script の節として開く文脈（ARCHON_NODE_EXECUTION の path に __ が無い）"""
        return self.scoped(node, block="darkfactory")

    def trace_ops(self, d, op: str) -> list:
        rows = [json.loads(x) for x in (d / "trace.jsonl").read_text(encoding="utf-8").splitlines() if x.strip()]
        return [r for r in rows if r.get("op") == op]

    def test_enter_checks_previous_window_on_scope_change(self):
        # include fixing の窓の間に別の include の置き場へ書く → 次に盤面を開く節（線の最上段）が窓を照らし、盤面を止めて落ちる
        d = self.create()
        with self.scoped("fixing__fix-loop.fix-prep"):
            entry.open_board(d)
        self.assertEqual((self.window(d)["scope"], self.window(d)["block"]), ("fixing", "blk-fix"))
        self.put(d, "refitting/r1/x.json")
        with self.line(), self.assertRaises(BoardGap) as cm:
            entry.open_board(d)
        self.assertIn("refitting/r1/x.json", str(cm.exception))
        self.assertIn("fixing", str(cm.exception))
        st = json.loads((d / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(st["stop"]["by"], stopby.SCOPE_CHECK)
        self.assertIn("refitting/r1/x.json", st["stop"]["reason"])
        self.assertEqual(self.window(d)["scope"], "")   # 窓は開いた節へ移る（後の開きが同じ誤りで落ち続けない）
        with self.line("h-review"):
            entry.open_board(d)
        with self.scoped("reporting__report-write", block="blk-report"):   # 報告の節は止めた盤面を allow_halted で開ける
            self.assertTrue(entry.open_board(d, allow_halted=True).allow_halted)

    def test_failed_check_found_by_report_does_not_stop_report(self):
        # 照らしの誤りを見つけたのが報告の節（allow_halted で開く）なら、盤面を止めても報告の節は落ちない
        d = self.create()
        with self.scoped("eyeing__eyes-enter", block="blk-eyes"):
            entry.open_board(d)
        self.put(d, "r1/stray.json")
        with self.scoped("reporting__report-write", block="blk-report"):
            b = entry.open_board(d, allow_halted=True)
        self.assertEqual(b.state["stop"]["by"], stopby.SCOPE_CHECK)
        self.assertEqual(self.window(d)["scope"], "reporting")

    def test_failed_check_on_stopped_board_goes_to_trace(self):
        # 止められない盤面（もう止まった・周を締めた。b.stop が Reject）には、止めた事実を trace に 1 行（line_edge と同じ逃げ）
        d = self.create()
        with self.scoped("fixing__fix-loop.fix-prep"):
            entry.open_board(d)
        entry.open_board(d).stop("先に人が止めた", by="test")
        self.put(d, "planning/r1/z.json")
        with self.line(), self.assertRaises(BoardGap):
            entry.open_board(d)
        got = self.trace_ops(d, scopes.STOP_AFTER_END_OP)
        self.assertEqual([(r["by"], r["at"]) for r in got], [(stopby.SCOPE_CHECK, "darkfactory")])
        self.assertIn("planning/r1/z.json", got[0]["reason"])
        self.assertEqual(json.loads((d / "state.json").read_text(encoding="utf-8"))["stop"]["by"], "test")

    def test_missing_required_output_reaches_trace_not_stop(self):
        # 必須の出力（blk-lens の lens.json）が窓の終わりに無くても止めない: trace の行に残り、報告が載せる
        d = self.create()
        with self.scoped("lensing__lens-route", block="blk-lens"):
            entry.open_board(d)
        with self.line("h-review"):
            entry.open_board(d)
        self.assertNotIn("stop", json.loads((d / "state.json").read_text(encoding="utf-8")))
        got = self.trace_ops(d, scopes.REQUIRED_MISSING_OP)
        self.assertEqual([(r["scope"], r["names"]) for r in got], [("lensing", ["r1/lens.json"])])

    def test_enter_same_scope_again_keeps_window(self):
        d = self.create()
        with self.scoped("fixing__fix-loop.fix-prep"):
            entry.open_board(d)
        first = self.window(d)
        self.put(d, "fixing/r1/a.json")
        with self.scoped("fixing__fix-loop.fix-accept"):
            entry.open_board(d)
        self.assertEqual(self.window(d), first)   # 同じ scope は窓を開き直さない（1 回目からの書き込みを照らし続ける）
        self.assertNotIn("fixing/r1/a.json", self.window(d)["files"])
        with self.line():
            entry.open_board(d)   # 線の最上段: scope の根の書き込みは通り、線の窓を開く
        self.assertEqual(self.window(d)["scope"], "")
        self.assertIn("fixing/r1/a.json", self.window(d)["files"])

    def test_open_board_outside_flow_node_leaves_window(self):
        # 流れの道具の節でない開き（run の外の dev/report.sh・dev/fixmeasure.py、試験の手）は窓に触らない（盤面に書かず照らさない）
        d = self.create()
        entry.open_board(d)
        self.assertFalse((d / scopes.WINDOW).exists())
        with self.scoped("reporting__report-write", block="blk-report"):
            entry.open_board(d)
        before = scopes.snapshot(d)
        self.put(d, "fixing/r1/x.json")
        self.assertEqual(entry.open_board(d, allow_halted=True).scope, "")
        self.assertEqual(scopes.snapshot(d), {**before, "fixing/r1/x.json": scopes.snapshot(d)["fixing/r1/x.json"]})
        self.assertEqual(self.window(d)["scope"], "reporting")

    def test_reads_outside_reach_trace(self):
        d = self.create()
        with self.scoped("fixing__fix-loop.fix-prep"):
            entry.open_board(d)
        rows = [{"path": str(d / "planning" / "r1" / "y.md"), "hook": "read", "event": None},
                {"path": str(d / "fixing" / "r1" / "brief-1.md"), "hook": "read", "event": None}]
        self.put(d, "fixing/r1/reads-fix.json", json.dumps({
            "role": "fix", "node_path": "fixing__fix-loop.fix", "rows": rows,
            "sources": {"hook": True, "events": "none"}, "missing": []}))
        with self.line():
            entry.open_board(d)   # 次の窓へ移る時に、前の窓の宣言の外の読みを trace に積む（落とさない）
        got = self.trace_ops(d, scopes.READ_OUTSIDE_OP)
        self.assertEqual([(r["scope"], r["paths"]) for r in got], [("fixing", ["planning/r1/y.md"])])

    def test_old_board_refused_when_scoped(self):
        d = self.create()
        self.edit_state(d, lambda st: st["works"].pop("layout"))
        with self.scoped("fixing__fix-prep"), self.assertRaises(BoardMismatch) as cm:
            entry.open_board(d)
        self.assertIn("移し替えない", str(cm.exception))
        self.assertFalse((d / "r1" / "scopes.json").exists())
        self.assertEqual(entry.open_board(d).scope, "")   # scope なし（線の最上段）は今どおり開ける

    def test_open_board_passes_allow_halted(self):
        d = self.create()
        self.assertFalse(entry.open_board(d).allow_halted)
        self.assertTrue(entry.open_board(d, allow_halted=True).allow_halted)

    def test_overview_due_fires_on_this_round_fix_delta(self):
        """works の run は同じ周で修正して R3・R4 を回す: 阻害要因が残り前の周の P3 が無くても、この周の p3.fix_delta
        （実測の差分）が 1 ファイル以上なら overview_due は真。差分が空・前の周の物なら元の条件のまま偽"""
        b = entry.open_board(self.create())
        rnd = b.round
        b.loop_state.update({"open_units": 2, "prev_fix_files": []})
        b.loop_state["fix_delta"] = {"round": rnd, "file": "d.patch", "files": ["a.py"], "rev": "x"}
        ok, why = b.cond("overview_due")
        self.assertTrue(ok, why)
        for delta in ({"round": rnd, "file": "d.patch", "files": [], "rev": "x"},
                      {"round": rnd - 1, "file": "d.patch", "files": ["a.py"], "rev": "x"}, None):
            with self.subTest(delta=delta):
                b.loop_state["fix_delta"] = delta
                self.assertFalse(b.cond("overview_due")[0])
        # 核の差し替えとして理由が残る
        self.assertIn("overview_due", [r["name"] for r in b.state["works"]["overrides"]])

    def test_open_board_applies_board_hook(self):
        """ラインの置き場の board_hook.py の board_kwargs(table) の返りを DiskBoard.open に渡す（毎回新しく読む）"""
        pack = self.tmp / "pack"
        (pack / "darkfactory").mkdir(parents=True)
        shutil.copy(TABLE_PATH, pack / "darkfactory" / "nodes.json")
        hook = pack / "darkfactory" / "board_hook.py"
        with mock.patch.object(entry, "PACK", pack):
            d = self.create()
            # 無い: {} で開く
            self.assertEqual(entry.hook_kwargs("darkfactory"), {})
            b = entry.open_board(d)
            self.assertIsNone(b.validator_runner)
            # 線 A の核の差し替え（読んだ記録の置き場。Task 6 の直し 1）は hook が無くても当たる
            self.assertEqual(entry.open_kwargs("darkfactory"), {"overrides": entry.CORE_OVERRIDES})
            self.assertIs(b.rules.hook_evidence, entry.CORE_OVERRIDES["hook_evidence"][0])
            self.assertIn("hook_evidence", [r["name"] for r in b.state["works"]["overrides"]])
            # validator_runner を返す
            hook.write_text("def board_kwargs(table):\n"
                            "    def run(b, target):\n"
                            "        return {'hooked': table.line, 'target': target}\n"
                            "    return {'validator_runner': run}\n", encoding="utf-8")
            self.assertEqual(set(entry.hook_kwargs("darkfactory")), {"validator_runner"})
            b = entry.open_board(d)
            self.assertEqual(b.run_validator("t"), {"hooked": "darkfactory", "target": "t"})
            self.assertFalse([m for m in sys.modules.values() if getattr(m, "__file__", None) == str(hook)])
            # 書き替えは次の読み込みで効く（sys.modules に残さない）
            hook.write_text("def board_kwargs(table):\n"
                            "    return {'validator_runner': lambda b, target: 'second'}\n", encoding="utf-8")
            self.assertEqual(entry.open_board(d).run_validator(), "second")
            # overrides も渡る（RL の大域の名前を差し替え、state.works.overrides に理由が残る）
            hook.write_text("def probe(*a, **k):\n    return []\n"
                            "def board_kwargs(table):\n"
                            "    return {'overrides': {'_final_gate_problems': (probe, 'hook の試験')}}\n", encoding="utf-8")
            b = entry.open_board(d)
            self.assertEqual(b.rules._final_gate_problems.__name__, "probe")
            self.assertIn({"name": "_final_gate_problems", "reason": "hook の試験"}, b.state["works"]["overrides"])
            self.assertIs(b.rules.hook_evidence, entry.CORE_OVERRIDES["hook_evidence"][0], "hook の overrides と核の差し替えは重なる")
            # hook が同じ名前を差し替えれば hook の方が勝つ
            hook.write_text("def probe(*a, **k):\n    return ('read', 'hook')\n"
                            "def board_kwargs(table):\n"
                            "    return {'overrides': {'hook_evidence': (probe, 'hook の試験')}}\n", encoding="utf-8")
            self.assertEqual(entry.open_board(d).rules.hook_evidence.__name__, "probe")
            # board_kwargs の中で落ちた例外も BoardGap（スクリプトは終了コード 2。TA19）
            hook.write_text("def board_kwargs(table):\n    raise ValueError('hook の中の誤り')\n", encoding="utf-8")
            with self.assertRaises(BoardGap) as cm:
                entry.open_board(d)
            self.assertIn("hook の中の誤り", str(cm.exception))
            # 知らない鍵は BoardGap
            hook.write_text("def board_kwargs(table):\n    return {'validator_runner': None, 'bogus': 1}\n", encoding="utf-8")
            with self.assertRaises(BoardGap) as cm:
                entry.open_board(d)
            self.assertIn("bogus", str(cm.exception))
            # board_kwargs が無い・dict でない も BoardGap
            for body in ("X = 1\n", "def board_kwargs(table):\n    return []\n"):
                with self.subTest(body):
                    hook.write_text(body, encoding="utf-8")
                    with self.assertRaises(BoardGap):
                        entry.hook_kwargs("darkfactory")
        self.assertFalse(list(pack.rglob("__pycache__")))


class LinekitCase(unittest.TestCase):
    def test_seed_repo_and_declarations(self):
        with tempfile.TemporaryDirectory(dir=linekit.work_home()) as t:
            t = pathlib.Path(t)
            plain = linekit.seed_repo(t / "plain")
            self.assertTrue((plain / "stats.py").is_file())
            self.assertFalse((plain / ".review-checks.json").exists())
            self.assertEqual(linekit.git(plain, "status", "--porcelain"), "")
            self.assertEqual(linekit.git(plain, "log", "--format=%an %at %cn %ct"),
                             "works-test 1767225600 works-test 1767225600")
            decl = linekit.seed_repo(t / "decl", declared=True)
            self.assertEqual(json.loads((decl / ".review-checks.json").read_text())["suite"][0]["argv"],
                             ["python3", "-m", "unittest", "test_stats"])
            self.assertEqual(linekit.git(decl, "status", "--porcelain"), "")
            broken = linekit.seed_repo(t / "broken", broken_declaration=True)
            self.assertIn("error", engine_declared.read(broken))

    def test_reply_and_home(self):
        with mock.patch.dict("os.environ"):   # 包みが Bash の役に立てる WORKS_RUN_PLACE が漏れても、この試験は WORKS_DEV_HOME の側を見る
            os.environ.pop("WORKS_RUN_PLACE", None)
            self.assertIsInstance(linekit.reply("judge_ok"), dict)
            self.assertTrue(str(linekit.work_home()).endswith("/single"))
            self.assertFalse(str(linekit.work_home().resolve()).startswith("/private/tmp/claude-"))

    def test_work_home_refuses_claude_tmp(self):
        """WORKS_DEV_HOME が Claude Code の一時フォルダの下なら、作る前に BoardGap（1 行）"""
        for base in ("/private/tmp/claude-works-test-0/home", "/tmp/claude-works-test-0/home"):
            with self.subTest(base), mock.patch.dict("os.environ", {"WORKS_DEV_HOME": base}):
                os.environ.pop("WORKS_RUN_PLACE", None)   # 外の WORKS_RUN_PLACE が WORKS_DEV_HOME より先に解けないように
                with self.assertRaises(BoardGap) as cm:
                    linekit.work_home()
                self.assertNotIn("\n", str(cm.exception))
                self.assertFalse(pathlib.Path(base).exists())

    def test_work_home_follows_run_place(self):
        """env の WORKS_RUN_PLACE が在れば、置き場は <それ>/single（WORKS_DEV_HOME より先）。sandbox の役が書ける場所へ向ける細い口"""
        env = {"WORKS_RUN_PLACE": "/works-run-place-test", "WORKS_DEV_HOME": "/works-dev-home-test"}
        with mock.patch.dict("os.environ", env), mock.patch.object(pathlib.Path, "mkdir"):
            self.assertEqual(linekit.work_home(), pathlib.Path("/works-run-place-test/single").resolve())

    def test_work_home_refuses_claude_tmp_run_place(self):
        """WORKS_RUN_PLACE も Claude Code の一時フォルダの下なら、作る前に BoardGap（WORKS_DEV_HOME と同じ拒み）"""
        for base in ("/private/tmp/claude-works-test-1/place", "/tmp/claude-works-test-1/place"):
            env = {"WORKS_RUN_PLACE": base, "WORKS_DEV_HOME": "/works-dev-home-test"}
            with self.subTest(base), mock.patch.dict("os.environ", env), mock.patch.object(pathlib.Path, "mkdir"):
                with self.assertRaises(BoardGap) as cm:
                    linekit.work_home()
                self.assertNotIn("\n", str(cm.exception))



# ---------------------------------------------------------------- start（線 A の仕様 4 節。計画 Task 7）
# 入力の確かめ・盤面を開く・修正前のテストの記録・方針の文・切符。盤面は linekit の種（stats.py・test_stats.py。赤 2 件）で
# 本物の darkfactory の表で作る。切符は包みの家を使い捨ての場所に向けて書く（WORKS_ADAPTER_HOME）。
# 裁定 R52（review-graph と同等）: test_cmd が空で宣言も無い run は拒まない。p0.local_checks は任せ先に落ちたまま残し、
# run_ci は偽の素材を渡さずに role_needed を返し、start の返りの ci_role_go が真になる（任せ先の役のブロックは blk-ci。tests/test_blk_ci.py）
import subprocess  # noqa: E402

import adapter  # noqa: E402
import ticket  # noqa: E402

SCRIPT = ROOT / "blk-entry" / "scripts" / "start.py"
SEED_CMD = "python3 -m unittest test_stats"


def request_file(into: pathlib.Path, items=None) -> pathlib.Path:
    """依頼のファイル（既定は種の request_ok.json の中身。2 件）"""
    into.parent.mkdir(parents=True, exist_ok=True)
    doc = items if items is not None else json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
    into.write_text(json.dumps(doc, ensure_ascii=False), encoding="utf-8")
    return into


def pending_inst(b, nid):
    return next((i for i in b.rd["instances"].values() if i["node"] == nid and i["status"] == "pending"), None)


class StartCaseBase(unittest.TestCase):
    def setUp(self):
        self._old_cwd = engine_util.GIT_CWD
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        self.tmp = pathlib.Path(self._tmp.name)
        self.home = self.tmp / "adapter-home"
        env = mock.patch.dict("os.environ", {"WORKS_ADAPTER_HOME": str(self.home)})
        env.start()
        self.addCleanup(env.stop)

    def tearDown(self):
        engine_util.GIT_CWD = self._old_cwd
        self._tmp.cleanup()

    def seed(self, **kw):
        return linekit.seed_repo(self.tmp / "repo", **kw)

    def raw(self, **kw):
        req = request_file(self.tmp / "req" / "request.json")
        return {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "final_gate": "", "adapter": "",
                "policy_md": "", **kw}

    def start(self, repo, raw=None, **kw):
        self.board = self.tmp / "board"
        return entry.start(self.board, repo, raw if raw is not None else self.raw(**kw), run_id="run-7")


class CheckInputsCase(StartCaseBase):
    ANSWERS = [{"question": "parallel_pr", "text": "並行する PR は無い"},
               {"question": "q-sock", "text": "通った", "command": "go test ./internal/sock/...", "output": "ok  sock 0.2s"}]

    def test_request_answers_reach_start_doc(self):
        """object の形の依頼の answers は check_inputs の返りと start の控えに字のまま載り、固定材料の照らしには入らない"""
        repo = self.seed()
        rows = json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
        req = request_file(self.tmp / "ans.json", {"findings": rows, "answers": self.ANSWERS})
        got = entry.check_inputs({"request": str(req)}, repo)
        self.assertEqual((got["items"], got["answers"]), (rows, self.ANSWERS))
        self.assertNotIn("answers", entry.adopt_inputs(got))
        self.start(repo, raw=self.raw(request=str(req)))
        self.assertEqual(startrec.read(self.board)["answers"], self.ANSWERS)

    def test_request_answers_bad_shape_refused(self):
        repo = self.seed()
        rows = json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
        one = {"question": "x", "text": "y"}
        for name, ans in (("not-list", one), ("empty-text", [{**one, "text": ""}]), ("no-question", [{"text": "y"}]),
                          ("command-only", [{**one, "command": "ls"}]), ("output-only", [{**one, "output": "a"}]),
                          ("extra", [{**one, "by": "人"}]), ("dup", [one, {**one, "text": "z"}]), ("not-dict", ["x"])):
            with self.subTest(name):
                req = request_file(self.tmp / f"{name}.json", {"findings": rows, "answers": ans})
                with self.assertRaises(entry.InputRefused) as cm:
                    entry.check_inputs({"request": str(req)}, repo)
                self.assertIn("answers", str(cm.exception))
                self.assertNotIn("\n", str(cm.exception))

    PRIOR = [{"where": "受け付け take_p2_fix_plan", "text": "案の欄 route が欠ける"},
             {"where": "独立の目 R2", "text": "R2 が redesign-needed: 構造が合わない"}]

    def test_request_prior_failures_reach_board_root(self):
        """object の形の依頼の prior_failures は check_inputs の返りに字のまま載り、start が盤面の根の prior-failures-in.json に
        置く（start の控えには残さない）。前の run の next-request.json の形 {findings, prior_failures} がそのまま依頼になる"""
        repo = self.seed()
        rows = json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
        req = request_file(self.tmp / "prior.json", {"findings": rows, "prior_failures": self.PRIOR})
        got = entry.check_inputs({"request": str(req)}, repo)
        self.assertEqual((got["items"], got["prior_failures"]), (rows, self.PRIOR))
        self.start(repo, raw=self.raw(request=str(req)))
        self.assertEqual(json.loads((self.board / carry.PRIOR_IN_FILE).read_text(encoding="utf-8")), self.PRIOR)
        self.assertNotIn("prior_failures", startrec.read(self.board))

    def test_request_prior_failures_bad_shape_refused(self):
        repo = self.seed()
        rows = json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
        one = {"where": "x", "text": "y"}
        for name, pf in (("not-list", one), ("not-dict", ["x"]), ("empty-text", [{**one, "text": " "}]),
                         ("no-where", [{"text": "y"}]), ("extra", [{**one, "by": "人"}])):
            with self.subTest(name):
                req = request_file(self.tmp / f"pf-{name}.json", {"findings": rows, "prior_failures": pf})
                with self.assertRaises(entry.InputRefused) as cm:
                    entry.check_inputs({"request": str(req)}, repo)
                self.assertIn("prior_failures", str(cm.exception))
                self.assertNotIn("\n", str(cm.exception))

    def test_inputs_defaults(self):
        """依頼だけ → thickness 自動・gates ""・final_gate always・adapter ""・lang ""。返りに thickness_decider が無い"""
        repo = self.seed()
        got = entry.check_inputs({"request": str(request_file(self.tmp / "r.json"))}, repo)
        self.assertEqual(set(got), {"request_file", "items", "request_text", "test_cmd", "thickness", "gates",
                                    "final_gate", "adapter", "policy_md", "lang", "unattended", "design_only",
                                    "fix_fixture", "launch_mark", "spec", "features_off", "features_on", "answers", "prior_failures"})
        self.assertEqual((got["answers"], got["prior_failures"], got["features_off"], got["features_on"]), ([], [], [], []))
        self.assertEqual((got["thickness"], got["gates"], got["final_gate"], got["adapter"], got["test_cmd"], got["policy_md"],
                          got["lang"], got["unattended"], got["design_only"]),
                         ("自動", "", "always", "", "", "", "", "", ""))
        self.assertEqual(len(got["items"]), 2)
        self.assertEqual(got["request_file"], str((self.tmp / "r.json").resolve()))
        self.assertIn("mean", got["request_text"])
        self.assertEqual(entry.THICKNESS, ("自動", "軽量", "標準", "重厚"))
        self.assertFalse(hasattr(entry, "FINAL_GATES"))   # 開き方の語は住処 gatepolicy の 1 か所
        self.assertEqual(entry.ADAPTER_MODES, ("", "optional"))

    def test_request_relative_to_repo(self):
        """相対の依頼のパスは対象の根から（1 本目の intake と同じ）"""
        repo = self.seed()
        request_file(repo / "req.json")
        self.assertEqual(entry.check_inputs({"request": "req.json"}, repo)["request_file"], str(repo / "req.json"))

    def test_light_and_standard_accepted(self):
        """軽量・標準は全部の単位の深さを固定する名指しとして受ける（持ち主の依頼 2026-10-06。計画 2026-10-06-variable-depth の決め 1）"""
        repo = self.seed()
        for word in ("軽量", "標準", "自動"):
            with self.subTest(word):
                self.assertEqual(entry.check_inputs(self.raw(thickness=word), repo)["thickness"], word)

    def test_heavy_refused(self):
        repo = self.seed()
        with self.assertRaises(entry.InputRefused) as cm:
            entry.check_inputs(self.raw(thickness="重厚"), repo)
        self.assertIn("重厚で足す工程がまだ無い", str(cm.exception))

    def test_unknown_words_refused(self):
        repo = self.seed()
        for key in ("thickness", "final_gate", "adapter", "unattended", "design_only", "gates"):
            with self.subTest(key):
                with self.assertRaises(entry.InputRefused) as cm:
                    entry.check_inputs(self.raw(**{key: "x"}), repo)
                self.assertNotIn("\n", str(cm.exception))
                self.assertIn("'x'", str(cm.exception))
                self.assertIn(key, str(cm.exception))
        # gates の文は写しの RL の check_inputs の文（使えるのは gates=merge）
        with self.assertRaises(entry.InputRefused) as cm:
            entry.check_inputs(self.raw(gates="x"), repo)
        self.assertIn("gates=merge", str(cm.exception))
        for key, ok in (("final_gate", "when_needed"), ("adapter", "optional"), ("gates", "merge")):
            with self.subTest(ok=ok):
                self.assertEqual(entry.check_inputs(self.raw(**{key: ok}), repo)[key], ok)

    def test_request_unreadable_or_bad_shape(self):
        """依頼が読めない・findings の配列でも {findings, pr, issue} の形でもない（findings の欄の無い object を含む）・
        依頼の型（写しの RL の REQUEST_SCHEMA）に合わない → InputRefused（1 行）"""
        repo = self.seed()
        bad = self.tmp / "bad"
        bad.mkdir()
        (bad / "broken.json").write_text("[{", encoding="utf-8")
        (bad / "obj.json").write_text('{"where": "a", "text": "b"}', encoding="utf-8")
        (bad / "empty.json").write_text("[]", encoding="utf-8")
        (bad / "shape.json").write_text('[{"where": "a"}]', encoding="utf-8")
        for req in ("", str(bad / "nowhere.json"), *(str(bad / n) for n in ("broken.json", "obj.json", "empty.json", "shape.json"))):
            with self.subTest(req):
                with self.assertRaises(entry.InputRefused) as cm:
                    entry.check_inputs({"request": req}, repo)
                self.assertNotIn("\n", str(cm.exception))

    def test_request_object_form_accepted(self):
        """依頼は配列か {findings, pr, issue} の形。object の形でも findings の行が items に入る"""
        repo = self.seed()
        rows = json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
        req = request_file(self.tmp / "obj.json", {"findings": rows, "pr": [3], "issue": [5]})
        try:
            got = entry.check_inputs({"request": str(req)}, repo)
        except entry.InputRefused as e:
            self.fail(f"object の形の依頼を拒んだ: {e}")
        self.assertEqual(got["items"], rows)

    def test_request_object_form_bad_names_refused(self):
        """object の形の pr・issue が正の整数の配列でない・知らない鍵 → InputRefused（1 行）。配列の形は今どおり通る"""
        repo = self.seed()
        rows = json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
        ok = request_file(self.tmp / "ok.json", {"findings": rows, "pr": [3]})
        try:
            entry.check_inputs({"request": str(ok)}, repo)
        except entry.InputRefused as e:
            self.fail(f"object の形の依頼を拒んだ: {e}")
        for name, doc in (("str", {"findings": rows, "pr": "3"}), ("zero", {"findings": rows, "issue": [0]}),
                          ("bool", {"findings": rows, "pr": [True]}), ("extra", {"findings": rows, "repo": "x"})):
            with self.subTest(name):
                req = request_file(self.tmp / f"{name}.json", doc)
                with self.assertRaises(entry.InputRefused) as cm:
                    entry.check_inputs({"request": str(req)}, repo)
                self.assertNotIn("\n", str(cm.exception))

    def test_no_tests_accepted_by_r52(self):
        """test_cmd が空で宣言も無い run は拒まない（裁定 R52: graphloops では p0.local_checks が任せ先の役に落ち、役が
        リポジトリを読んでテストの走らせ方を探す。拒むとそれを失う）"""
        repo = self.seed()
        self.assertEqual(entry.check_inputs(self.raw(), repo)["test_cmd"], "")

    def test_policy_md_named_but_missing(self):
        repo = self.seed()
        with self.assertRaises(entry.InputRefused) as cm:
            entry.check_inputs(self.raw(policy_md="nowhere.md"), repo)
        self.assertIn("nowhere.md", str(cm.exception))
        (repo / "pol.md").write_text("方針\n", encoding="utf-8")
        self.assertEqual(entry.check_inputs(self.raw(policy_md="pol.md"), repo)["policy_md"], str(repo / "pol.md"))


class LocalChecksMaterialCase(StartCaseBase):
    def test_local_checks_material_callable_alone(self):
        """盤面なしで呼べる（線 B の申し送り 2）: 種の赤 2 件 → found・count 1・detail にログの末尾"""
        repo = self.seed()
        log = self.tmp / "logs" / "ci.log"
        got = entry.local_checks_material(repo, SEED_CMD, log)
        m = got["material"]
        self.assertEqual((m["status"], m["count"]), ("found", 1))
        tail = log.read_text(encoding="utf-8").rstrip().splitlines()[-1]
        self.assertIn("FAILED", tail)
        self.assertIn(tail, m["detail"])

    def test_second_call_reuses_and_names_origin(self):
        """包みの家と run の置き場を置いた環境で、同じ木・同じ test_cmd の local_checks_material を同じ run の中で 2 度呼ぶと、
        2 度目は子を起こさず、素材の checked に『控えから使った』と出どころの run が出る。launched に reused が入り、
        別の run の呼びは走らせる"""
        repo = self.seed()
        count = self.tmp / "count"
        cmd = f"echo 1 >> {count}; echo all-green"
        env = {webget.SHARED_ENV: str(self.tmp / "home"), "ARTIFACTS_DIR": str(self.tmp / "arts" / "run-a"), "WORKS_TESTSLOT": ""}
        with mock.patch.dict(os.environ, env):
            os.environ.pop("GRAPHLOOPS_RERUN_CHECKS", None)
            first = entry.local_checks_material(repo, cmd, self.tmp / "one.log")["material"]
            launched = {}
            second = entry.local_checks_material(repo, cmd, self.tmp / "two.log", launched=launched)["material"]
            with mock.patch.dict(os.environ, {"ARTIFACTS_DIR": str(self.tmp / "arts" / "run-b")}):
                entry.local_checks_material(repo, cmd, self.tmp / "three.log")
        self.assertEqual(len(count.read_text(encoding="utf-8").split()), 2)
        self.assertEqual((first["status"], second["status"]), ("clean", "clean"))
        self.assertNotIn("控えから使った", first["checked"])
        self.assertIn("控えから使った（run run-a・", second["checked"])
        self.assertEqual(launched["reused"]["from"], "run-a")
        self.assertIn("all-green", (self.tmp / "two.log").read_text(encoding="utf-8"))

    def test_clean_carries_checked(self):
        """clean は写しの RR の規則で checked が要る（何を見たか）。count 0・detail も付く"""
        repo = self.seed()
        m = entry.local_checks_material(repo, "echo all-green", self.tmp / "ok.log")["material"]
        self.assertEqual((m["status"], m["count"]), ("clean", 0))
        self.assertIn("echo all-green", m["checked"])
        self.assertIn("exit 0", m["checked"])
        self.assertIn("all-green", m["detail"])

    def test_niced_runs_with_lower_priority(self):
        """niced（既定 False）が真なら nice を付けて走らせる（TDD の輪の中の test_cmd。ADR 0071 の 3 の 1）。偽なら今どおり"""
        repo = self.seed()
        cmd = f"{sys.executable} -c \"import os; print('NICE', os.nice(0))\""

        def level(log, **kw):
            m = entry.local_checks_material(repo, cmd, self.tmp / log, **kw)["material"]
            self.assertEqual(m["status"], "clean", m)
            return int((self.tmp / log).read_text(encoding="utf-8").split("NICE")[1].split()[0])
        plain, niced = level("plain.log"), level("niced.log", niced=True)
        self.assertEqual(plain, os.nice(0))
        self.assertGreaterEqual(niced, min(plain + 19, 19), "nice -n 19 と同じ（上限は OS で 19 か 20）")

    def test_empty_cmd_not_run(self):
        m = entry.local_checks_material(self.seed(), "  ", self.tmp / "x.log")["material"]
        self.assertEqual(m["status"], "not_run")
        self.assertTrue(m["reason"].strip())
        self.assertFalse((self.tmp / "x.log").exists())

    def test_env_outside_uv_no_bytecode(self):
        """子の環境は tree_run.outside_env（PYTHONDONTWRITEBYTECODE=1）"""
        repo = self.seed()
        log = self.tmp / "env.log"
        entry.local_checks_material(repo, 'echo "pdwb=$PYTHONDONTWRITEBYTECODE"', log)
        self.assertIn("pdwb=1", log.read_text(encoding="utf-8"))


class _StubBoard:
    """run_engine の返りを順に返す偽の盤面（run_ci の分かれ道だけを見る）"""

    def __init__(self, tmp, replies):
        self.replies = list(replies)
        self.calls = 0
        self.tmp = pathlib.Path(tmp)
        self.record = {"materials": {"local_checks": {"status": "clean", "checked": "偽"}}}

    def run_engine(self, nid, *, runner=None):
        self.calls += 1
        return self.replies.pop(0)

    def work(self, name):
        p = self.tmp / "r1" / name
        p.parent.mkdir(parents=True, exist_ok=True)
        return p

    def done(self, *a, **kw):
        raise AssertionError("done を呼んではいけない")


class RunCiCase(StartCaseBase):
    def ok_reply(self):
        out, err = self.tmp / "1.out", self.tmp / "1.err"
        out.write_text("ran\n", encoding="utf-8")
        err.write_text("", encoding="utf-8")
        return {"ok": True, "node": "p0.local_checks",
                "runs": [{"name": "suite", "argv": ["x"], "out": str(out), "err": str(err), "exit": 0}]}

    def test_run_ci_relaunch_once(self):
        """1 度目 relaunch・2 度目通る → 通る。2 度とも relaunch → CiRefused、文に why"""
        relaunch = {"ok": False, "node": "p0.local_checks", "why": "宣言の sha が計画と違う", "relaunch": True}
        b = _StubBoard(self.tmp, [relaunch, self.ok_reply()])
        got = entry.run_ci(b, "p0.local_checks", test_cmd="")
        self.assertEqual((got["by"], b.calls), ("engine", 2))
        b = _StubBoard(self.tmp, [relaunch, relaunch])
        with self.assertRaises(entry.CiRefused) as cm:
            entry.run_ci(b, "p0.local_checks", test_cmd="")
        self.assertIn("宣言の sha が計画と違う", str(cm.exception))
        self.assertEqual(b.calls, 2)

    def test_run_ci_why_only_refused(self):
        """{ok: False, why} だけの返り（対象の根が引けない）→ CiRefused（黙って素通りしない）"""
        b = _StubBoard(self.tmp, [{"ok": False, "node": "p4.ci", "why": "対象リポジトリのルートが引けない"}])
        with self.assertRaises(entry.CiRefused) as cm:
            entry.run_ci(b, "p4.ci", test_cmd="true")
        self.assertIn("ルートが引けない", str(cm.exception))
        self.assertIsInstance(cm.exception, entry.InputRefused)   # start は AI を起こす前に止める（同じ扱い）

    def test_engine_log_has_every_stage_and_stderr(self):
        """engine が走らせた回の log は全部の段の標準出力と標準エラー（2 段目の赤・標準エラーだけの出力も見える。Task 14 M2/M4）"""
        repo = self.seed()
        decl = {"suite": [{"name": "one", "argv": ["python3", "-c", "print('stage-one-out')"]},
                          {"name": "two", "argv": ["python3", "-c", "import sys; sys.stderr.write('stage-two-err\\n'); sys.exit(3)"]}]}
        (repo / ".review-checks.json").write_text(json.dumps(decl), encoding="utf-8")
        linekit.git(repo, "add", "-A")
        linekit.git(repo, "commit", "-q", "-m", "decl")
        b, p = DiskBoard.begin(self.tmp / "board", repo=repo, table=entry.load_table("darkfactory"), items=[{"where": "stats.py", "text": "x"}],
                               origin="works/darkfactory", base_rev="", request_text="x", stop_after_round=1)
        self.assertIn("p0.local_checks", p["run_engine"])
        got = entry.run_ci(b, "p0.local_checks", test_cmd="")
        self.assertEqual(got["by"], "engine")
        text = pathlib.Path(got["log"]).read_text(encoding="utf-8")
        for part in ("stage-one-out", "stage-two-err", "one", "two", "exit 3"):
            self.assertIn(part, text)
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "found")

    def declared_board(self):
        """宣言（緑の 1 段）を持つ対象で盤面を始める"""
        repo = self.seed()
        decl = {"suite": [{"name": "decl", "argv": ["python3", "-c", "print('decl-ran')"]}]}
        (repo / ".review-checks.json").write_text(json.dumps(decl), encoding="utf-8")
        linekit.git(repo, "add", "-A")
        linekit.git(repo, "commit", "-q", "-m", "decl")
        b, p = DiskBoard.begin(self.tmp / "board", repo=repo, table=entry.load_table("darkfactory"), items=[{"where": "stats.py", "text": "x"}],
                               origin="works/darkfactory", base_rev="", request_text="x", stop_after_round=1)
        self.assertIn("p0.local_checks", p["run_engine"])
        return repo, b

    def test_declared_and_red_test_cmd_is_found(self):
        """宣言が在っても test_cmd を黙って捨てない: 宣言の段が緑で test_cmd が赤なら素材は found（AND の合成）"""
        repo, b = self.declared_board()
        entry.run_ci(b, "p0.local_checks", test_cmd="echo test-cmd-ran; exit 1")
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "found")

    def test_declared_and_green_test_cmd_runs_both(self):
        """宣言と test_cmd の両方が緑なら clean で、test_cmd も走り、その段が runs とログに載る"""
        repo, b = self.declared_board()
        mark = self.tmp / "test-cmd-mark"
        got = entry.run_ci(b, "p0.local_checks", test_cmd=f"echo test-cmd-ran; touch {mark}")
        self.assertTrue(mark.exists(), "宣言が在ると test_cmd が走っていない")
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "clean")
        names = [r.get("name") for r in b.record["process"]["checks"]["p0.local_checks"]["runs"]]
        self.assertIn("test_cmd", names)
        text = pathlib.Path(got["log"]).read_text(encoding="utf-8")
        for part in ("decl-ran", "test-cmd-ran"):
            self.assertIn(part, text)

    def test_fallback_empty_cmd_role_needed_no_material(self):
        """宣言が無く test_cmd も空 → 任せ先に落ちたまま、偽の素材を渡さず role_needed（裁定 R52）。印も置かない"""
        repo = self.seed()
        b, p = DiskBoard.begin(self.tmp / "board", repo=repo, table=entry.load_table("darkfactory"), items=[{"where": "stats.py", "text": "x"}],
                               origin="works/darkfactory", base_rev="", request_text="x", stop_after_round=1)
        got = entry.run_ci(b, "p0.local_checks", test_cmd=" ")
        self.assertEqual(got["by"], "role_needed")
        self.assertIn(".review-checks.json", got["why"])
        inst = pending_inst(b, "p0.local_checks")
        self.assertTrue(inst.get("engine_fallback"))
        self.assertFalse(inst.get("launched_at"))
        self.assertNotIn("local_checks", b.record["materials"])
        self.assertIn("p0.local_checks", b.settle()["ready"])


class StartCase(StartCaseBase):
    def test_start_with_declaration_by_engine(self):
        """宣言が在れば engine が回し、渡した test_cmd も宣言の一式の後に走る（56 件目。AND の合成なので種の赤は赤のまま）"""
        repo = self.seed(declared=True)
        mark = self.tmp / "test-cmd-ran"
        got = self.start(repo, test_cmd=f"touch {mark}")
        b = entry.open_board(self.board)
        self.assertEqual(b.record["process"]["checks"]["p0.local_checks"]["by"], "engine")
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "found")   # 種は赤
        self.assertTrue(mark.exists(), "宣言が在ると test_cmd が走っていない")
        self.assertIn("test_cmd", [r.get("name") for r in b.record["process"]["checks"]["p0.local_checks"]["runs"]])
        ready = b.settle()["ready"]
        self.assertIn("p0.premises", ready)
        self.assertNotIn("p0.local_checks", ready)
        self.assertEqual(b.settle()["run_engine"], [])
        self.assertFalse(got["ci_role_go"])

    def test_start_without_declaration_runs_test_cmd(self):
        repo = self.seed()
        got = self.start(repo, test_cmd=SEED_CMD)
        b = entry.open_board(self.board)
        self.assertEqual(b.record["process"]["checks"]["p0.local_checks"]["by"], "role")
        m = b.record["materials"]["local_checks"]
        self.assertEqual((m["status"], m["count"]), ("found", 1))
        self.assertEqual(b.record["process"]["baseline_checks"]["status"], "found")
        self.assertNotIn("p0.local_checks", b.settle()["ready"])
        self.assertFalse(got["ci_role_go"])

    def test_start_without_declaration_green_cmd_clean(self):
        """緑の test_cmd の素材（clean・checked つき）を受け付けが通す"""
        repo = self.seed()
        self.start(repo, test_cmd="true")
        m = entry.open_board(self.board).record["materials"]["local_checks"]
        self.assertEqual(m["status"], "clean")
        self.assertIn("exit 0", m["checked"])

    def test_start_no_tests_signals_role(self):
        """test_cmd 空・宣言無し → 拒まない。p0.local_checks は任せ先に落ちたまま ready に残り、ci_role_go が真で head_line も言う"""
        repo = self.seed()
        got = self.start(repo)
        self.assertTrue(got["ok"])
        self.assertTrue(got["ci_role_go"])
        self.assertEqual(got["pr_go"], "pending")   # p0.parallel_pr は p0.local_checks を待つ（まだ測れない。偽と言わない）
        self.assertIn("任せ先", got["head_line"])
        b = entry.open_board(self.board)
        self.assertNotIn("local_checks", b.record["materials"])
        self.assertIn("p0.local_checks", b.settle()["ready"])

    def test_start_broken_declaration_not_fallback(self):
        """読めない宣言 → engine が返答を組み（任せ先に落ちない）、test_cmd を走らせない"""
        repo = self.seed(broken_declaration=True)
        got = self.start(repo, test_cmd="touch should-not-run")
        b = entry.open_board(self.board)
        self.assertEqual(b.record["process"]["checks"]["p0.local_checks"]["by"], "engine")
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "awaiting_human")
        self.assertFalse((repo / "should-not-run").exists())
        self.assertFalse(got["ci_role_go"])

    def test_start_refuses_before_board(self):
        """入力の拒みは盤面の置き場を作る前（重厚・知らない語・読めない依頼）"""
        repo = self.seed()
        for raw in (self.raw(thickness="重厚"), self.raw(final_gate="x"), {"request": str(self.tmp / "nowhere.json")}):
            with self.subTest(raw):
                with self.assertRaises(entry.InputRefused):
                    self.start(repo, raw)
                self.assertFalse(self.board.exists())
                self.assertIsNone(adapter.read_ticket(repo))

    def test_start_records_request_and_entry(self):
        repo = self.seed(declared=True)
        self.start(repo)
        b = entry.open_board(self.board)
        batches = b.record["process"]["request_findings"]
        self.assertEqual(len(batches), 1)
        self.assertEqual(len(batches[0]["findings"]), 2)
        self.assertEqual(b.record["process"]["request_entry"]["origin"], "works/darkfactory")
        self.assertEqual(b.state["works"]["line"], "darkfactory")

    def test_start_stop_after_round_one(self):
        repo = self.seed(declared=True)
        self.start(repo)
        self.assertEqual(json.loads((self.board / "state.json").read_text(encoding="utf-8"))["stop_after_round"], 1)

    def test_start_writes_ticket(self):
        repo = self.seed(declared=True)
        self.start(repo)
        t = adapter.read_ticket(repo)
        self.assertEqual(t["run_id"], "run-7")
        self.assertEqual(t["board"], str(self.board))
        self.assertEqual(t["cwd"], str(repo))

    def test_start_head_line(self):
        repo = self.seed(declared=True)
        got = self.start(repo)
        absent = len(entry.load_table("darkfactory").absent())
        line = got["head_line"]
        for part in ("入口: 差分なし（HEAD）・依頼 2 件——P1 の役は起こさない", "段: 自動（既定）", "gates: 空", f"このラインに無い節: {absent} 個",
                     "下げている所: 2 個"):
            self.assertIn(part, line)
        self.assertNotIn("\n", line)

    def test_start_head_line_named_words(self):
        """thickness を名指せば（既定）を付けない。gates=merge は語のまま"""
        repo = self.seed(declared=True)
        got = self.start(repo, thickness="標準", gates="merge")
        self.assertIn("段: 標準・", got["head_line"])
        self.assertNotIn("（既定）", got["head_line"])
        self.assertIn("gates: merge", got["head_line"])
        self.assertEqual(entry.open_board(self.board).state["inputs"]["gates"], "merge")

    def test_start_result_and_inputs_copy(self):
        repo = self.seed(declared=True)
        got = self.start(repo, test_cmd=SEED_CMD, final_gate="when_needed", adapter="optional")
        b = entry.open_board(self.board)
        self.assertEqual(got["base_rev"], linekit.git(repo, "rev-parse", "HEAD"))
        self.assertEqual((got["test_cmd"], got["adapter"], got["thickness"], got["gates"]),
                         (SEED_CMD, "optional", "自動", ""))
        self.assertNotIn("final_gate", got)   # 開き方は出口に出さず、始めの記録に 1 度だけ置く
        self.assertEqual((got["policy_paste"], got["policy_path"]), ("", ""))
        self.assertIsNone(b.state["inputs"]["gates"])
        doc = json.loads(b.work("start.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["run_id"], "run-7")
        self.assertEqual(doc["test_cmd"], SEED_CMD)
        self.assertEqual(doc["final_gate"], "when_needed")
        self.assertEqual(doc["request_file"], self.raw()["request"])

    def test_declared_adapter(self):
        """run が宣言した包みの形は start の控え（r<N>/start.json の adapter）から読む（blk-ci が読む。裁定 R58）。
        控えが無い・壊れた・鍵が無い・語の外は ValueError（読む側が fail closed で止める）"""
        repo = self.seed(declared=True)
        self.start(repo, test_cmd=SEED_CMD, adapter="optional")
        b = entry.open_board(self.board)
        self.assertEqual(entry.declared_adapter(b), "optional")
        path = b.work(startrec.NAME)
        doc = json.loads(path.read_text(encoding="utf-8"))
        path.write_text(json.dumps({**doc, "adapter": ""}), encoding="utf-8")
        self.assertEqual(entry.declared_adapter(b), "")
        for text in ("{壊れ", "[]", json.dumps({k: v for k, v in doc.items() if k != "adapter"}),
                     json.dumps({**doc, "adapter": "maybe"}), json.dumps({**doc, "adapter": None})):
            with self.subTest(text[:40]):
                path.write_text(text, encoding="utf-8")
                with self.assertRaises(ValueError) as cm:
                    entry.declared_adapter(b)
                self.assertIn("adapter", str(cm.exception))
        path.unlink()
        with self.assertRaises(ValueError):
            entry.declared_adapter(b)

    def github(self, repo):
        """origin を GitHub の形にし、交差を返す偽の gh を PATH の頭に置く（並行 PR が任せ先の役に落ちる run）"""
        env = mock.patch.dict("os.environ", {"PATH": linekit.github_crossing(repo, self.tmp)})
        env.start()
        self.addCleanup(env.stop)

    def test_start_parallel_pr_by_helper(self):
        """p0.parallel_pr は prcheck.run_helper で回す（run_ci でない）。origin が GitHub で偽の gh が交差を返すので任せ先に落ち、
        pr_go が真。start は印を置かない（blk-pr の pr-snap が置く）"""
        repo = self.seed(declared=True)
        self.github(repo)
        got = self.start(repo)
        self.assertTrue(got["pr_go"])
        b = entry.open_board(self.board)
        inst = pending_inst(b, "p0.parallel_pr")
        self.assertTrue(inst.get("engine_fallback"))
        self.assertFalse(inst.get("launched_at"))
        self.assertNotIn("parallel_pr", b.record["materials"])

    def test_start_no_forge_settles_parallel_pr(self):
        """forge の無い origin（無い・ローカルのパス・GitHub でないホスト）→ start が run の初めに決めを loop.forge に置き、
        p0.parallel_pr は条件外（na。理由は no_forge: <種類>）で、engine の計画も任せ先の役も起こさない（pr_go が偽・instance が無い）"""
        for kind, url in (("no_remote", None), ("local_path", "origin.git"), ("other_host", "https://gitlab.com/o/r.git")):
            with self.subTest(kind):
                top = self.tmp / kind
                repo = linekit.seed_repo(top / "repo", declared=True)
                if url is not None:
                    linekit.git(repo, "remote", "add", "origin", str(top / url) if kind == "local_path" else url)
                got = entry.start(top / "board", repo, self.raw(), run_id="run-7")
                self.assertIs(got["pr_go"], False)
                b = entry.open_board(top / "board")
                self.assertEqual(b.loop_state["forge"]["kind"], kind)
                self.assertEqual(b.node_state("p0.parallel_pr"), "na")
                self.assertIn(f"parallel_pr_due: no_forge: {kind}（", b.rd["na"]["p0.parallel_pr"])
                self.assertNotIn("p0.parallel_pr", b.rd["instances"])

    def test_start_pr_refused_stops(self):
        """prcheck.Refused は CiRefused と同じく AI の前で止める（InputRefused）。切符を書かない"""
        import prcheck
        repo = self.seed(declared=True)

        def refuse(b, *, runner=None):
            raise prcheck.Refused("計画が 2 度とも拒まれた")
        with mock.patch.object(prcheck, "run_helper", refuse):
            with self.assertRaises(entry.InputRefused) as cm:
                self.start(repo)
        self.assertIn("2 度とも", str(cm.exception))
        self.assertIsNone(adapter.read_ticket(repo))

    def test_start_idempotent(self):
        """同じ置き場で呼び直しても盤面を作り直さず、同じ返り（Archon の再開）"""
        repo = self.seed()
        first = self.start(repo, test_cmd=SEED_CMD)
        again = entry.start(self.board, repo, self.raw(test_cmd=SEED_CMD), run_id="run-7")
        self.assertEqual({k: first[k] for k in ("base_rev", "ci_role_go", "pr_go", "head_line")},
                         {k: again[k] for k in ("base_rev", "ci_role_go", "pr_go", "head_line")})


class InputShapeCase(StartCaseBase):
    """入口の入力の形（差分の根・差分・依頼の行）の中身で盤面の始め方が決まる。依頼の行はいつも盤面を作る時に積み、入口の印
    （P1 の役を起こさない）は入力の差分が空の時だけ立つ。差分の根は base と HEAD の merge-base（GitHub の PR の three-dot と同じ）、
    名指しが無ければ HEAD"""

    P1 = ("p1.local_review", "p1.consistency_bypass", "p1.hygiene")

    def changed_repo(self, declared=True):
        repo = self.seed(declared=declared)
        linekit.git(repo, "branch", "base")
        fork = linekit.git(repo, "rev-parse", "HEAD")
        with (repo / "stats.py").open("a", encoding="utf-8") as f:
            f.write("\n# 変更\n")
        linekit.git(repo, "commit", "-q", "-am", "change")
        return repo, fork

    def p1_deps_done(self, repo):
        """P1 の na は依存（p0.parallel_pr・p0.purpose）が済んだ後に付く（単一 run の設計:155）。任せ先の役の代わりに
        前提を渡し、目的の文を渡して、P1 を見られる盤面にする（種は remote を持たない forge の無い run なので、並行 PR は
        機械が条件外にした）"""
        for nid, reply in (("p0.premises", PREMISES_REPLY),):
            launch(self.board, nid)
            got = entry.take(self.board, nid, reply, repo)
            self.assertTrue(got["ok"], got)
        linekit.pre_judge(self.board, repo, only=("p0.purpose",))
        b = entry.open_board(self.board)
        self.assertEqual([d for d in ("p0.parallel_pr", "p0.purpose") if b.node_state(d) == "pending"], [])
        return b

    def batches(self):
        return entry.open_board(self.board).record["process"].get("request_findings") or []

    def test_diff_without_requests_is_plain_review(self):
        """依頼無し・base だけ（差分あり）→ 拒まず、P1 の差分の根（record.base）は merge-base、依頼を積まず入口の印も立てず、
        P1 の 3 節が na にならない。start の出口 base_rev は修正の起点（修正前の HEAD）のまま"""
        repo, fork = self.changed_repo()
        head = linekit.git(repo, "rev-parse", "HEAD")
        try:
            got = self.start(repo, self.raw(request="", base="base"))
        except entry.InputRefused as e:
            self.fail(f"差分だけの入口を拒んだ: {e}")
        self.assertTrue(got["ok"])
        self.assertEqual(got["base_rev"], head)
        self.assertEqual((got["input"]["base"], got["input"]["diff"]["empty"], got["input"]["requests"]),
                         ({"rev": fork, "from": "base", "name": "base", "label": "base base"}, False, 0))
        b = entry.open_board(self.board)
        self.assertEqual(b.record["base"], fork)
        self.assertIsNone(b.record["process"].get("request_entry"))
        self.assertFalse(self.batches())
        b = self.p1_deps_done(repo)
        for nid in self.P1:
            self.assertNotEqual(b.node_state(nid), "na", nid)
        import conflict
        self.assertTrue(conflict.no_requests(self.board))   # intake の読む印は entry.start が書いた控えの input から
        self.assertIn("入口: 差分 " + fork[:12] + "..HEAD（1 ファイル・base base）・依頼 0 件", got["head_line"])

    def test_diff_with_requests_keeps_p1(self):
        """依頼と差分の両方 → 依頼は盤面を作る時に origin のバッチで 1 本積み、入口の印を立てない（P1 を外さない）。
        呼び直しても 2 度積まない"""
        repo, fork = self.changed_repo()
        head = linekit.git(repo, "rev-parse", "HEAD")
        got = self.start(repo, self.raw(base="base"))
        self.assertEqual((got["base_rev"], got["input"]["diff"]["empty"], got["input"]["requests"]), (head, False, 2))
        b = entry.open_board(self.board)
        self.assertEqual(b.record["base"], fork)
        self.assertIs(b.state["works"]["begin"]["diff_empty"], False)
        self.assertIsNone(b.record["process"].get("request_entry"))
        self.assertEqual([x["origin"] for x in self.batches()], [entry.ORIGIN])
        self.assertEqual(len(self.batches()[0]["findings"]), 2)
        b = self.p1_deps_done(repo)
        for nid in self.P1:
            self.assertNotEqual(b.node_state(nid), "na", nid)
        self.start(repo, self.raw(base="base"))
        self.assertEqual(len(self.batches()), 1)

    def test_start_object_request_and_change_adds_findings(self):
        """依頼が {findings, pr, issue} の形でも、積むのは findings の行だけ。名指した PR・issue は run の中で gh が読む
        （ここでは偽の gh。読めない項は記録して進む）"""
        from test_ghreads import fake_gh
        repo, _ = self.changed_repo()
        rows = json.loads((linekit.SEED / "request_ok.json").read_text(encoding="utf-8"))
        req = request_file(self.tmp / "req" / "obj.json", {"findings": rows, "pr": [3], "issue": [5]})
        bin_, _, _ = fake_gh(self.tmp / "gh")
        try:
            with mock.patch.dict("os.environ", {"PATH": f"{bin_}{os.pathsep}{os.environ.get('PATH', '')}"}):
                os.environ.pop(entryshape.NO_AUTH_ENV, None)
                got = self.start(repo, self.raw(request=str(req), base="base"))
        except entry.InputRefused as e:
            self.fail(f"object の形の依頼を拒んだ: {e}")
        self.assertEqual(got["input"]["requests"], 2)
        self.assertEqual([x["origin"] for x in self.batches()], [entry.ORIGIN])
        self.assertEqual(self.batches()[0]["findings"], rows)

    def test_ci_role_wait_does_not_hold_requests(self):
        """CI の任せ先の役を待つ run（版がまだ固まっていない）でも、依頼は盤面を作る時に積まれていて、差分が在るので印は
        立たない。役が渡した後の resume_after_ci も積み直さない"""
        repo, _ = self.changed_repo(declared=False)
        got = self.start(repo, self.raw(base="base"))
        self.assertTrue(got["ci_role_go"])
        b = entry.open_board(self.board)
        self.assertEqual(b.node_state("p1.worktree_before"), "pending")
        self.assertEqual([x["origin"] for x in self.batches()], [entry.ORIGIN])
        self.assertIsNone(b.record["process"].get("request_entry"))
        inst = pending_inst(b, "p0.local_checks")
        b.mark_launched("p0.local_checks", inst.get("attempts", 1))
        b.done("p0.local_checks", {"material": {"status": "clean", "count": 0, "checked": "試験の役の代わり"}})
        entry.resume_after_ci(entry.open_board(self.board))
        b = entry.open_board(self.board)
        self.assertEqual([x["origin"] for x in self.batches()], [entry.ORIGIN])
        self.assertIsNone(b.record["process"].get("request_entry"))

    def test_empty_diff_with_requests_sets_mark(self):
        """依頼だけ（差分が空）→ 判定から入る run（印が立ち、依存が済んだ後に P1 の 3 節は na）"""
        repo = self.seed(declared=True)
        got = self.start(repo)
        b = entry.open_board(self.board)
        self.assertTrue(got["input"]["diff"]["empty"])
        self.assertIs(b.state["works"]["begin"]["diff_empty"], True)
        self.assertEqual(b.record["process"]["request_entry"]["origin"], entry.ORIGIN)
        self.assertEqual(b.node_state("p1.consistency_bypass"), "pending")   # p0.parallel_pr・p0.purpose を待つ
        b = self.p1_deps_done(repo)
        for nid in self.P1:
            self.assertEqual(b.node_state(nid), "na", nid)
        import conflict
        self.assertFalse(conflict.no_requests(self.board))

    def test_base_equal_head_with_request_enters_from_judging(self):
        """--base が HEAD と同じ版で依頼が在る run（差分が空）→ 印が立ち、判定から入る。版を固める p1.worktree_before が
        空差分の柵で止まらない（前は依頼を後から積む道で印が立たず、柵で止まった）"""
        repo = self.seed(declared=True)
        got = self.start(repo, self.raw(base="HEAD"))
        self.assertTrue(got["input"]["diff"]["empty"])
        self.assertEqual(got["input"]["base"]["from"], "base")
        b = self.p1_deps_done(repo)
        self.assertEqual(b.record["process"]["request_entry"]["origin"], entry.ORIGIN)
        self.assertEqual(b.node_state("p1.worktree_before"), "done")
        self.assertFalse(b.state.get("halted"))
        for nid in self.P1:
            self.assertEqual(b.node_state(nid), "na", nid)

    def test_resume_after_fix_keeps_frozen_input(self):
        """start の後に作業ツリーが変わってから start を呼び直しても（Archon の再開。修正が作業ツリーを進めた後）、入力の形は
        最初の控えのまま（測り直さない）で、begin が別の引数と言わない"""
        repo = self.seed(declared=True)
        first = self.start(repo)
        with (repo / "stats.py").open("a", encoding="utf-8") as f:
            f.write("\n# 修正\n")
        try:
            again = entry.start(self.board, repo, self.raw(), run_id="run-7")
        except (entry.InputRefused, entry.BoardGap) as e:
            self.fail(f"作業ツリーが変わった後の呼び直しを拒んだ: {e}")
        self.assertEqual(again["input"], first["input"])
        self.assertTrue(again["input"]["diff"]["empty"])

    def test_start_doc_has_input_not_entry(self):
        """start の控え r1/start.json は入口の入力の形 input を持ち、入口の種（entry・entry_words・change）を持たない"""
        repo = self.seed(declared=True)
        got = self.start(repo)
        doc = startrec.read(self.board)
        self.assertEqual(doc["input"], got["input"])
        for gone in ("entry", "entry_words", "change"):
            self.assertNotIn(gone, doc)
            self.assertNotIn(gone, got)
        self.assertEqual(set(doc["input"]), {"base", "head_rev", "diff", "requests", "request_file", "pr", "spec"})

    def test_start_doc_matches_contract(self):
        """start の控えは始めの記録の約束（blk-entry/schemas/start.schema.json）に、欄 input と出口の input は出口の約束
        （input.schema.json）に合う（依頼だけ・差分の根の名指しの両方）"""
        from engine.schema import validate_schema
        schemas = ROOT / "blk-entry" / "schemas"
        rec = json.loads((schemas / "start.schema.json").read_text(encoding="utf-8"))
        exit_ = json.loads((schemas / "input.schema.json").read_text(encoding="utf-8"))
        repo, _ = self.changed_repo()
        for name, raw in (("request", self.raw()), ("base", self.raw(request="", base="base"))):
            with self.subTest(name):
                if self.tmp.joinpath("board").exists():
                    import shutil
                    shutil.rmtree(self.tmp / "board")
                got = self.start(repo, raw)
                doc = startrec.read(self.board)
                self.assertEqual(validate_schema(doc, rec), [])
                self.assertEqual(validate_schema(got["input"], exit_), [])


class ResumeCase(StartCaseBase):
    def ci_role_done(self, material):
        """任せ先の CI の役（後の Task のブロック）の代わり: 印を置いて素材を done"""
        b = entry.open_board(self.board)
        inst = pending_inst(b, "p0.local_checks")
        b.mark_launched("p0.local_checks", inst.get("attempts", 1))
        b.done("p0.local_checks", {"material": material})
        return entry.open_board(self.board)

    def test_resume_after_ci(self):
        """ラインの約束: 任せ先の CI の役が p0.local_checks を渡した後、ラインは resume_after_ci で start の輪に戻る
        （run_engine → settle と p0.parallel_pr の run_helper）。返りの pr_go が測った値になる"""
        repo = self.seed()
        env = mock.patch.dict("os.environ", {"PATH": linekit.github_crossing(repo, self.tmp)})
        env.start()
        self.addCleanup(env.stop)
        self.assertEqual(self.start(repo)["pr_go"], "pending")
        b = entry.open_board(self.board)
        still = entry.resume_after_ci(b)   # 役がまだ渡していない: 何も走らせず、同じ値
        self.assertEqual((still["ci_role_go"], still["pr_go"]), (True, "pending"))
        b = self.ci_role_done({"status": "found", "count": 1, "detail": "役が走らせた: 赤 2 件"})
        got = entry.resume_after_ci(b)
        self.assertEqual((got["ci_role_go"], got["pr_go"]), (False, True))   # 偽の gh が交差を返すので任せ先へ
        b = entry.open_board(self.board)
        inst = pending_inst(b, "p0.parallel_pr")
        self.assertTrue(inst.get("engine_fallback"))
        self.assertFalse(inst.get("launched_at"))
        self.assertEqual(b.settle()["run_engine"], [])
        again = entry.resume_after_ci(b)   # 呼び直しても同じ（走らせ直さない）
        self.assertEqual((again["ci_role_go"], again["pr_go"]), (False, True))

    def test_start_resume_after_cancel_mid_cmd(self):
        """test_cmd の途中で止められた run を呼び直すと、test_cmd を走らせ直す（任せ先の役に黙って替えない）。
        選んだ道（test_cmd）はテストを走らせる前に start.json に置く"""
        import tree_run
        repo = self.seed()

        def stopped(*a, **kw):
            doc = json.loads((self.board / "r1" / "start.json").read_text(encoding="utf-8"))
            self.assertEqual((doc["ci_fallback"], doc["test_cmd"]), ("test_cmd", SEED_CMD))
            raise tree_run.Stopped(15)
        with mock.patch.object(entry, "local_checks_material", stopped):
            with self.assertRaises(tree_run.Stopped):
                self.start(repo, test_cmd=SEED_CMD)
        b = entry.open_board(self.board)
        self.assertTrue(pending_inst(b, "p0.local_checks").get("launched_at"))
        got = entry.start(self.board, repo, self.raw(test_cmd=SEED_CMD), run_id="run-7")
        self.assertFalse(got["ci_role_go"])
        b = entry.open_board(self.board)
        self.assertEqual(b.record["process"]["checks"]["p0.local_checks"]["by"], "role")
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "found")
        self.assertIn(got["pr_go"], (True, False))

    def test_start_resume_changed_test_cmd_refused(self):
        """呼び直しで test_cmd が替わった（空になった）ら、前に選んだ道を黙って替えずに拒む"""
        import tree_run
        repo = self.seed()
        with mock.patch.object(entry, "local_checks_material", mock.Mock(side_effect=tree_run.Stopped(15))):
            with self.assertRaises(tree_run.Stopped):
                self.start(repo, test_cmd=SEED_CMD)
        for cmd in ("", "true"):
            with self.subTest(cmd):
                with self.assertRaises(entry.InputRefused) as cm:
                    entry.start(self.board, repo, self.raw(test_cmd=cmd), run_id="run-7")
                self.assertIn("test_cmd", str(cm.exception))

    def test_start_has_no_fix_shape(self):
        """修正の形は g3 だけ（2026-10-09）: 返り・控え・頭の行に修正の形を載せない"""
        repo = self.seed()
        got = self.start(repo, test_cmd=SEED_CMD)
        self.assertNotIn("fix_shape", got)
        self.assertNotIn("修正の形", got["head_line"])
        doc = json.loads(entry.open_board(self.board).work(startrec.NAME).read_text(encoding="utf-8"))
        self.assertNotIn("fix_shape", doc)

    def test_features_off_reaches_exit_head_and_doc(self):
        """切る機能（入力 features_off）: 出口に機能ごとの on・off（線がブロックの切り替えの入力へ写す）、頭の行に切った機能、
        控えに語の順の配列。呼び直しで替えれば拒み、同じなら通る"""
        repo = self.seed()
        first = self.start(repo, test_cmd=SEED_CMD, features_off="tdd_lanes judge_verify")
        self.assertEqual({k: first[k] for k in entry.FEATURES},
                         {"fix_lanes": "on", "graph_map": "on", "judge_verify": "off", "review_tree": "auto", "tdd_lanes": "off",
                          "world": "on"})
        self.assertIn("機能: judge_verify off・review_tree auto・tdd_lanes off", first["head_line"])
        doc = json.loads(entry.open_board(self.board).work(startrec.NAME).read_text(encoding="utf-8"))
        self.assertEqual(doc["features_off"], ["judge_verify", "tdd_lanes"])
        with self.assertRaises(entry.InputRefused) as cm:
            entry.start(self.board, repo, self.raw(test_cmd=SEED_CMD), run_id="run-7")
        self.assertIn("features_off", str(cm.exception))
        again = entry.start(self.board, repo, self.raw(test_cmd=SEED_CMD, features_off="judge_verify,tdd_lanes"), run_id="run-7")
        self.assertEqual(again["judge_verify"], "off")

    def test_features_default_judge_verify_off_review_tree_auto(self):
        """既定（持ち主の決め 2026-10-08）: 判定の裏取りは off・事前審査の木は auto・ほかは on。控えの features_on は空の配列"""
        repo = self.seed()
        got = self.start(repo, test_cmd=SEED_CMD)
        self.assertEqual({k: got[k] for k in entry.FEATURES},
                         {"fix_lanes": "on", "graph_map": "on", "judge_verify": "off", "review_tree": "auto", "tdd_lanes": "on",
                          "world": "on"})
        self.assertIn("機能: judge_verify off・review_tree auto", got["head_line"])
        doc = json.loads(entry.open_board(self.board).work(startrec.NAME).read_text(encoding="utf-8"))
        self.assertEqual((doc["features_off"], doc["features_on"]), ([], []))

    def test_features_on_turns_defaults_on_and_is_kept_on_resume(self):
        """入れる機能（入力 features_on）: 既定の off・auto を on にし、控えに語の順の配列。呼び直しで替えれば拒む"""
        repo = self.seed()
        first = self.start(repo, test_cmd=SEED_CMD, features_on="review_tree,judge_verify")
        self.assertEqual({k: first[k] for k in entry.FEATURES}, {k: "on" for k in entry.FEATURES})
        self.assertIn("機能: 全部 on", first["head_line"])
        doc = json.loads(entry.open_board(self.board).work(startrec.NAME).read_text(encoding="utf-8"))
        self.assertEqual(doc["features_on"], ["judge_verify", "review_tree"])
        with self.assertRaises(entry.InputRefused) as cm:
            entry.start(self.board, repo, self.raw(test_cmd=SEED_CMD), run_id="run-7")
        self.assertIn("features_on", str(cm.exception))
        again = entry.start(self.board, repo, self.raw(test_cmd=SEED_CMD, features_on="judge_verify review_tree"),
                            run_id="run-7")
        self.assertEqual(again["judge_verify"], "on")

    def test_fallback_cmd_runs_from_git_top(self):
        """任せ先の test_cmd は engine と同じく git の根（--show-toplevel）で走らせる（入力の cwd が下のフォルダでも）"""
        repo = self.seed()
        sub = repo / "sub"
        sub.mkdir()
        b, p = DiskBoard.begin(self.tmp / "board", repo=sub, table=entry.load_table("darkfactory"), items=[{"where": "stats.py", "text": "x"}],
                               origin="works/darkfactory", base_rev="", request_text="x", stop_after_round=1)
        got = entry.run_ci(b, "p0.local_checks", test_cmd="pwd -P")
        self.assertEqual(got["by"], "role")
        self.assertIn(f"\n{os.path.realpath(repo)}\n", "\n" + pathlib.Path(got["log"]).read_text(encoding="utf-8"))


class StartScriptCase(StartCaseBase):
    def env(self, repo, **kw):
        req = request_file(self.tmp / "req" / "request.json")
        base = {"INPUTS_REQUEST": str(req), "INPUTS_TEST_CMD": "", "INPUTS_THICKNESS": "", "INPUTS_GATES": "",
                "INPUTS_FINAL_GATE": "", "INPUTS_ADAPTER": "", "INPUTS_POLICY_MD": "", "ARTIFACTS_DIR": str(self.tmp / "art"),
                "WORKFLOW_ID": "wf-1", "WORKS_ADAPTER_HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        env.update(base)
        env.update(kw)
        return {k: v for k, v in env.items() if v is not None}

    def run_script(self, repo, **kw):
        return subprocess.run([sys.executable, str(SCRIPT)], cwd=repo, env=self.env(repo, **kw), capture_output=True,
                              text=True, encoding="utf-8", stdin=subprocess.DEVNULL)

    def test_start_script_refusal_exit_1(self):
        repo = self.seed()
        r = self.run_script(repo, INPUTS_THICKNESS="重厚")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        self.assertIn("重厚で足す工程がまだ無い", r.stderr)
        self.assertFalse((self.tmp / "art" / "board").exists())

    def test_start_script_missing_env_exit_2(self):
        repo = self.seed()
        for name in ("ARTIFACTS_DIR", "WORKFLOW_ID", "INPUTS_TEST_CMD"):
            with self.subTest(name):
                r = self.run_script(repo, **{name: None})
                self.assertEqual(r.returncode, 2)
                self.assertIn(name, r.stderr)
                self.assertEqual(r.stdout, "")

    def test_start_script_success_one_line(self):
        repo = self.seed(declared=True)
        r = self.run_script(repo)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        got = json.loads(lines[0])
        self.assertTrue(got["ok"])
        self.assertIn("差分なし（HEAD）", got["head_line"])
        self.assertEqual(got["input"]["diff"]["empty"], True)
        self.assertEqual(adapter.read_ticket(repo)["run_id"], "wf-1")
        self.assertTrue((self.tmp / "art" / "board" / "state.json").is_file())
        self.assertFalse([*CORE.rglob("__pycache__"), *(ROOT / "darkfactory").rglob("__pycache__")])


    def main_in_process(self, repo, **kw):
        """start.py の main を同じプロセスで呼ぶ（entry の中を差し替えるため）。返り (終了コード, stdout, stderr)"""
        import contextlib
        import importlib.util
        import io
        spec = importlib.util.spec_from_file_location("_works_start_script", SCRIPT)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        out, err = io.StringIO(), io.StringIO()
        old = os.getcwd()
        os.chdir(repo)
        try:
            with mock.patch.dict("os.environ", self.env(repo, **kw), clear=True), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                rc = mod.main()
        finally:
            os.chdir(old)
        return rc, out.getvalue(), err.getvalue()

    def test_start_script_fallback_rejected_exit_2(self):
        """任せ先の素材を受け付けが拒んだ（機械の欠陥）→ 2 と 1 行（入力の拒み 1 と分ける）"""
        repo = self.seed()
        bad = mock.Mock(return_value={"material": {"status": "bogus"}})
        with mock.patch.object(entry, "local_checks_material", bad):
            rc, out, err = self.main_in_process(repo, INPUTS_TEST_CMD="true")
        self.assertEqual(rc, 2, err)
        self.assertEqual(out, "")
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertIn("盤面の誤り", err)

    def test_start_script_unexpected_exit_2_one_line(self):
        repo = self.seed()
        with mock.patch.object(entry, "start", mock.Mock(side_effect=RuntimeError("壊れた\n2 行目"))):
            rc, out, err = self.main_in_process(repo)
        self.assertEqual(rc, 2)
        self.assertEqual(out, "")
        self.assertEqual(len(err.strip().splitlines()), 1)
        self.assertIn("RuntimeError", err)
        self.assertIn("壊れた", err)



# ---------------------------------------------------------------- 盤面に受ける共通の口（計画 Task 9。裁定 TA6・TA11・TA19）
# take は役の返答を盤面の done に渡す。写しの AnswerReject（中身の誤り）だけを {ok: False} で役に返し、盤面は書かない。
# ほかの Reject（止めた run など）と BoardGap は投げ直す（受け付けのスクリプトは終了コード 2）。読むだけの役の作業ツリーの
# 確かめは、役を起こす前に snapshot が今の周の置き場に写した accept.tree_state と比べる（共通の姿と違いの文。R47）
import hashlib  # noqa: E402

from engine.util import AnswerReject, Reject  # noqa: E402

JUDGE_SNAP = "judge-tree.json"


def board_shas(d) -> dict:
    """盤面の置き場の全部のファイルの sha256（拒んだ受け付けが何も書かないことを見る）"""
    d = pathlib.Path(d)
    return {str(p.relative_to(d)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(d.rglob("*")) if p.is_file()}


def launch(board_dir, nid) -> dict:
    """ブロックの snap の節の代わり: 待っている試行に起こした印を置く（盤面は印の無い返答を受けない）"""
    b = entry.open_board(board_dir)
    return b.mark_launched(nid, pending_inst(b, nid).get("attempts", 1))


def pr_reply() -> dict:
    """p0.parallel_pr の任せ先の役の返答（交差 0 件）。works だけの欄 excluded は blk-pr の受け付けが外してから盤面に渡す"""
    return {k: v for k, v in linekit.reply("pr_no_conflicts").items() if k != "excluded"}


PREMISES_REPLY = {"constraints": []}


def halt(board_dir):
    """周の途中の問いで止めた run（state.halted）にする。欄の形は DiskBoard.stop・engine の run_driver_node が書く物と同じ"""
    p = pathlib.Path(board_dir) / "state.json"
    st = json.loads(p.read_text(encoding="utf-8"))
    st["halted"] = {"node": "p2.human_gate", "round": st["round"], "by": "works:test", "reason": "試験で止めた"}
    p.write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def plan_reply(unit_keys) -> dict:
    return {"plan": [{"unit_keys": unit_keys, "approach": "mean の分母を len(xs) に直す（算術平均の定義どおり）",
                      "adds": [], "removes": [], "shrink_first": "足す物は無い。分母の式を 1 か所直すだけで足りる",
                      "narrows": []}]}


class TakeCaseBase(StartCaseBase):
    def judge_ready(self):
        """p2.diagnose が待っている盤面（start の後、前提の役の返答を take で渡した。種は remote を持たない forge の無い run
        なので、並行 PR は機械が条件外にした）。置き場は $ARTIFACTS_DIR/board の形（self.art / board）。返りは対象リポジトリ"""
        repo = self.seed(declared=True)
        self.art = self.tmp / "art"
        self.board = self.art / "board"
        entry.start(self.board, repo, self.raw(), run_id="run-7")
        for nid, reply in (("p0.premises", PREMISES_REPLY),):
            launch(self.board, nid)
            got = entry.take(self.board, nid, reply, repo)
            self.assertTrue(got["ok"], got)
        linekit.pre_judge(self.board, repo)   # 目的の文（判定の前に盤面が待つ）
        self.assertIn("p2.diagnose", entry.open_board(self.board).settle()["ready"])
        return repo

    def judged(self, name="judge_ok"):
        """判定（name の見本）を受けた盤面"""
        repo = self.judge_ready()
        launch(self.board, "p2.diagnose")
        got = entry.take(self.board, "p2.diagnose", linekit.reply(name), repo)
        self.assertTrue(got["ok"], got)
        return repo, got


class TakeCase(TakeCaseBase):
    def test_take_accepts_and_reports_ready(self):
        repo, got = self.judged()
        self.assertEqual(set(got), {"ok", "reason", "ready", "asking", "halted", "out_file"})
        self.assertEqual((got["ok"], got["reason"], got["asking"], got["halted"]), (True, "", False, False))
        self.assertIn("p2.fix_plan", got["ready"])
        b = entry.open_board(self.board)
        self.assertEqual(got["out_file"], b.state["outputs"]["p2.diagnose"]["file"])
        self.assertTrue((self.board / got["out_file"]).is_file())
        self.assertEqual(b.node_state("p2.diagnose"), "done")

    def test_take_without_settle_accepts_but_does_not_advance(self):
        """settle=False: 盤面は返答を受けて保存するが進めない（後ろの節の待ちを出さない）。返りの ready は空。後の settle が進める"""
        repo = self.judge_ready()
        launch(self.board, "p2.diagnose")
        got = entry.take(self.board, "p2.diagnose", linekit.reply("judge_ok"), repo, settle=False)
        b = entry.open_board(self.board)
        self.assertEqual(got, {"ok": True, "reason": "", "ready": [], "asking": False, "halted": False,
                               "out_file": b.state["outputs"]["p2.diagnose"]["file"]})
        self.assertEqual(b.node_state("p2.diagnose"), "done")
        self.assertNotIn("p2.fix_plan", b.rd["instances"])
        self.assertIn("p2.fix_plan", b.settle()["ready"])

    def test_take_reject_leaves_board(self):
        repo = self.judge_ready()
        launch(self.board, "p2.diagnose")
        before = board_shas(self.board)
        bad = linekit.reply("judge_ok")
        bad["units"] = "壊れた"
        got = entry.take(self.board, "p2.diagnose", bad, repo)
        self.assertEqual(set(got), {"ok", "reason"})
        self.assertFalse(got["ok"])
        self.assertIn("型に合わない", got["reason"])
        self.assertEqual(board_shas(self.board), before)
        self.assertEqual(entry.open_board(self.board).node_state("p2.diagnose"), "pending")

    def test_take_readonly_tree_changed(self):
        """読むだけの役を起こす前の写し（snapshot）と今の作業ツリーが違えば ok False・盤面は前のまま。戻せば通る"""
        repo = self.judge_ready()
        launch(self.board, "p2.diagnose")
        snap = entry.snapshot(self.board, JUDGE_SNAP, repo)
        self.assertEqual(snap, entry.open_board(self.board).work(JUDGE_SNAP))
        import accept
        self.assertEqual(set(json.loads(snap.read_text(encoding="utf-8"))), set(accept.TREE_KEYS))   # 共通の姿 tree_state（R47）
        (repo / "stray.txt").write_text("役が書いた\n", encoding="utf-8")
        before = board_shas(self.board)
        got = entry.take(self.board, "p2.diagnose", linekit.reply("judge_ok"), repo, snapshot_name=JUDGE_SNAP)
        self.assertFalse(got["ok"])
        self.assertTrue(got["reason"].startswith("読むだけの役が作業ツリーを変えた: "), got["reason"])
        self.assertIn("stray.txt", got["reason"])
        self.assertEqual(board_shas(self.board), before)
        (repo / "stray.txt").unlink()
        got = entry.take(self.board, "p2.diagnose", linekit.reply("judge_ok"), repo, snapshot_name=JUDGE_SNAP)
        self.assertTrue(got["ok"], got)

    def test_take_readonly_branch_and_ignored_changes_named(self):
        """比べは共通の tree_state・tree_change（R47）: 中身の同じ枝の切り替え（ref だけ変わる）も拒み、拒否の文は変わった欄
        （ref・git が無視するパスの増えた物）を名指す"""
        repo = self.judge_ready()
        launch(self.board, "p2.diagnose")
        entry.snapshot(self.board, JUDGE_SNAP, repo)
        linekit.git(repo, "switch", "-q", "-c", "役が切った枝")
        got = entry.take(self.board, "p2.diagnose", linekit.reply("judge_ok"), repo, snapshot_name=JUDGE_SNAP)
        self.assertFalse(got["ok"])
        self.assertTrue(got["reason"].startswith("読むだけの役が作業ツリーを変えた: "), got["reason"])
        self.assertIn("ref: 役を起こす前 refs/heads/", got["reason"])
        self.assertIn("refs/heads/役が切った枝", got["reason"])
        linekit.git(repo, "switch", "-q", "-")
        (repo / ".git" / "info").mkdir(exist_ok=True)
        with open(repo / ".git" / "info" / "exclude", "a", encoding="utf-8") as f:
            f.write("\n*.役の残り\n")
        (repo / "x.役の残り").write_text("役が書いた\n", encoding="utf-8")
        got = entry.take(self.board, "p2.diagnose", linekit.reply("judge_ok"), repo, snapshot_name=JUDGE_SNAP)
        self.assertFalse(got["ok"])
        self.assertIn("git が無視するパス: 増えた ['x.役の残り'] 消えた []", got["reason"])
        (repo / "x.役の残り").unlink()
        got = entry.take(self.board, "p2.diagnose", linekit.reply("judge_ok"), repo, snapshot_name=JUDGE_SNAP)
        self.assertTrue(got["ok"], got)

    def test_take_gap_raises(self):
        """表で absent の節・写しの無い snapshot_name・印の無い試行は BoardGap（回す側の誤り。役に返さない）"""
        repo = self.judge_ready()
        with self.assertRaises(BoardGap):
            entry.take(self.board, "p0.purpose", {"text": "目的"}, repo)
        with self.assertRaises(BoardGap):   # 印（mark_launched）の無い試行の返答
            entry.take(self.board, "p2.diagnose", linekit.reply("judge_ok"), repo)
        launch(self.board, "p2.diagnose")
        with self.assertRaises(BoardGap):   # 役を起こす前の写しが無い
            entry.take(self.board, "p2.diagnose", linekit.reply("judge_ok"), repo, snapshot_name="nowhere.json")

    def test_take_on_halted_raises_not_role_reject(self):
        """止めた run（halted）への受け付けは写しの Reject のまま投げ直す（AnswerReject でない。役に返さない）"""
        repo = self.judge_ready()
        launch(self.board, "p2.diagnose")
        halt(self.board)
        before = board_shas(self.board)
        bad_snap = entry.open_board(self.board, allow_halted=True).work(JUDGE_SNAP)
        for snap in (None, JUDGE_SNAP):
            with self.subTest(snapshot_name=snap):
                if snap:
                    bad_snap.write_text("{}", encoding="utf-8")   # 形の崩れた写しより先に止めた run を拒む
                with self.assertRaises(Reject) as cm:
                    entry.take(self.board, "p2.diagnose", linekit.reply("judge_ok"), repo, snapshot_name=snap)
                self.assertNotIsInstance(cm.exception, AnswerReject)
                self.assertIn("止めた", str(cm.exception))
        bad_snap.unlink()
        self.assertEqual(board_shas(self.board), before)

    def test_take_on_stopped_raises(self):
        """止め札（b.stop）で止めた run: 待っていた instance は stopped で、受け付けは BoardGap（役に返さない）"""
        repo = self.judge_ready()
        launch(self.board, "p2.diagnose")
        entry.open_board(self.board).stop("試験で止める", by="works:test")
        with self.assertRaises(BoardGap):
            entry.take(self.board, "p2.diagnose", linekit.reply("judge_ok"), repo)

    def test_take_pointer_integer_rejected(self):
        """番号の控えを固めずに起こした p2.fix_plan に unit_keys の整数 → engine の番号の文で ok False（盤仕様 BL17）"""
        repo, _ = self.judged()
        launch(self.board, "p2.fix_plan")
        before = board_shas(self.board)
        got = entry.take(self.board, "p2.fix_plan", plan_reply([1]), repo)
        self.assertFalse(got["ok"])
        self.assertIn("p2.fix_plan", got["reason"])
        self.assertIn("unit_keys", got["reason"])
        self.assertEqual(board_shas(self.board), before)

    def test_empty_fix_passes_rule(self):
        """直す義務 0 件の周（judge_no_fix → p2.fix_plan は条件で na）で、機械が渡す p3.fix の空の返答が写しの schema と
        fix_covers_open_units を通る。settle の後 p4.ci が待ち、差分の審査は na（TA6）"""
        empty = entry.empty_fix_reply()
        self.assertEqual(empty["changes"], [])
        self.assertEqual(empty["fix_closure"]["status"], "not_applicable")
        self.assertEqual(set(empty), set(GRAPH["nodes"]["p3.fix"]["schema"]["required"]))
        self.assertIsNot(entry.empty_fix_reply(), empty)
        repo, got = self.judged("judge_no_fix")
        b = entry.open_board(self.board)
        self.assertIn("p2.fix_plan", b.rd["na"])
        self.assertIn("p3.fix", got["ready"])
        launch(self.board, "p3.fix")
        got = entry.take(self.board, "p3.fix", empty, repo)
        self.assertTrue(got["ok"], got)
        self.assertIn("p4.ci", got["ready"])
        b = entry.open_board(self.board)
        self.assertIn("p3.delta_review", b.rd["na"])
        self.assertEqual(b.record["materials"]["fix_closure"]["status"], "not_applicable")


class TakeRoundTwoCase(unittest.TestCase):
    """周 2 の盤面（手本 test_converges の Run 1 の周 2 の p2.diagnose の受け付けの前）で take。out_file は out/r2/ の下
    （ブロックは周の番号を仮定しない。TA17）"""

    def setUp(self):
        import boardreplay as R
        self.R = R
        self._tmp = tempfile.TemporaryDirectory(dir=linekit.work_home())
        self.tmp = pathlib.Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)
        cwd = engine_util.GIT_CWD
        self.addCleanup(setattr, engine_util, "GIT_CWD", cwd)
        env = mock.patch.dict(os.environ, R.git_env())
        env.start()
        self.addCleanup(env.stop)

    def test_take_round_two(self):
        R = self.R
        rs = R.load_runs("test_converges")["1"]
        s = next(s for s in rs if s["kind"] == "accept" and s["node"] == "p2.diagnose"
                 and R.memory_at(rs, s["seq"], "before")["state"]["round"] == 2)
        board_dir, repo = R.restore(rs, s["seq"], "before", self.tmp)
        table = entry.load_table("darkfactory")
        R.board_from_memory(R.memory_at(rs, s["seq"], "before"), board_dir, table)
        st = json.loads((board_dir / "state.json").read_text(encoding="utf-8"))
        st["works"].update(line=table.line, table_sha=table.sha())
        (board_dir / "state.json").write_text(json.dumps(st, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        b = entry.open_board(board_dir)
        self.assertEqual(b.round, 2)
        R.mark(b, "p2.diagnose")
        got = entry.take(board_dir, "p2.diagnose", R.reply(s, b), repo)
        self.assertTrue(got["ok"], got)
        self.assertTrue(got["out_file"].startswith("out/r2/"), got["out_file"])


if __name__ == "__main__":
    unittest.main()
