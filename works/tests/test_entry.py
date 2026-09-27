"""線 A の入口のモジュール（.shared/core/entry.py）の表の分と、darkfactory の節の表（darkfactory/nodes.json）の検査。

表は手で書き、ここで写しの graph と突き合わせる（盤面の層の縛り 1〜5 と、線 A の行の決まり）。行の決まりは線 A の仕様 4 節と
持ち主の答え（2026-09-27）: p0.premises は役（blk-premises）、p0.parallel_pr は engine_run で任せ先は読むだけの役（blk-pr）、
p2.rejudge・p2.rejudge_third は役（blk-rejudge。包みが判定役の会話を継ぐ）、p0.purpose は線 B が足すので absent、手厚さは標準だけ。
盤面を作る試験は linekit の種（dev/target-seed/）を使い捨ての家（linekit.work_home()）の下に置いて回す。
"""
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
import entry  # noqa: E402
import linekit  # noqa: E402

GRAPH = graph_expanded()
TABLE_PATH = ROOT / "darkfactory" / "nodes.json"
ROLES = {"p0.premises", "p2.diagnose", "p2.fix_plan", "p2.plan_review", "p3.fix", "p3.delta_review", "p3.delta_fix",
         "p3.delta_review2", "p3.delta_fix2", "p2.rejudge", "p2.rejudge_third"}


def raw_table() -> dict:
    return json.loads(TABLE_PATH.read_text(encoding="utf-8"))


class TableCase(unittest.TestCase):
    def setUp(self):
        self.table = entry.load_table()
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
        self.assertEqual(pr.where, "start")
        self.assertIn("blk-pr", pr.reason)
        self.assertIn("投稿しない", pr.reason)
        self.assertIn("スコープから外す", pr.reason)   # review-graph の 6 段と同じく、衝突した hunk はこのループで触らない（Task 21）
        for nid in ("p2.rejudge", "p2.rejudge_third"):
            with self.subTest(nid):
                self.assertEqual(self.nodes[nid].by, "role")
                self.assertEqual(self.nodes[nid].where, "blk-rejudge")
        self.assertIn("会話を継ぐ", self.nodes["p2.rejudge"].reason)
        self.assertIn("新しい会話", self.nodes["p2.rejudge_third"].reason)

    def test_where_is_a_plain_block_name(self):
        """where はブロックの名か start だけ（線 B の表と合流の時に比べる。説明の文は reason に置く）。absent と builtin は書かない"""
        for nid, e in self.nodes.items():
            with self.subTest(nid):
                if e.by in ("absent", "builtin"):
                    self.assertEqual(e.where, "")
                else:
                    self.assertRegex(e.where, r"\A(?:start|blk-[a-z0-9]+(?:-[a-z0-9]+)*)\Z")

    def test_purpose_declared_absent(self):
        """目的の文は線 B が足す（線 A には入らない）。一緒に入る目的の審査・前の決定も absent"""
        for nid in ("p0.purpose", "p0.purpose_review", "p0.prior_decisions"):
            with self.subTest(nid):
                e = self.nodes[nid]
                self.assertEqual(e.by, "absent")
                self.assertIn("線 B", e.reason)
                self.assertIn("線 B", e.comes_with)

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
        self.assertEqual(self.nodes["p0.base"].where, "start")
        drivers = {n for n, g in GRAPH["nodes"].items() if g.get("run_by") == "driver"}
        self.assertEqual(len(drivers), 17)
        builtins = {n for n, e in self.nodes.items() if e.by == "builtin"}
        self.assertEqual(builtins, drivers)
        self.assertEqual({self.nodes[n].run for n in builtins}, {"auto"})

    def test_ci_nodes_fall_back_to_machine(self):
        for nid, where in (("p0.local_checks", "start"), ("p4.ci", "blk-tests")):
            with self.subTest(nid):
                e = self.nodes[nid]
                self.assertEqual((e.by, e.fallback), ("engine_run", "machine"))
                self.assertEqual(e.where, where)
        self.assertEqual({n for n, e in self.nodes.items() if e.by == "engine_run"},
                         {"p0.local_checks", "p0.parallel_pr", "p4.ci"})

    def test_no_skippable_yet(self):
        """手厚さは標準だけ（持ち主の答え 1: 省けない節を省かない）。skippable の行が 0"""
        self.assertEqual([n for n, e in self.nodes.items() if e.skippable], [])
        self.assertFalse(any("skippable" in r for r in raw_table()["nodes"].values()))

    def test_report_absent_so_record_invalid_unreachable(self):
        """報告の役の 3 節は absent。graph の pre: finalize の節は report だけ → settle の報告の前の関所（RecordInvalid）は
        線 A で起きない（代わりの関所は線 A の report.build）"""
        for nid in ("report", "report.human_items", "report.cold_check"):
            with self.subTest(nid):
                self.assertEqual(self.nodes[nid].by, "absent")
                self.assertIn("R27", self.nodes[nid].reason)
        self.assertEqual({n for n, g in GRAPH["nodes"].items() if g.get("pre") == "finalize"}, {"report"})

    def test_later_lines_name_their_line(self):
        """線 B・線 C・R 系・別の入口の行は comes_with にその名"""
        want = {"p2.history": "線 B", "p3.delta_gates": "線 C", "p4.final_gates": "線 C",
                "r1.minimality": "R 系", "stop.premise_check": "R 系", "spec.write": "darkfactory-spec"}
        for nid, name in want.items():
            with self.subTest(nid):
                self.assertEqual(self.nodes[nid].by, "absent")
                self.assertIn(name, self.nodes[nid].comes_with)
        p1 = [n for n in GRAPH["nodes"] if n.startswith("p1.") and GRAPH["nodes"][n].get("run_by") != "driver"]
        self.assertEqual(len(p1), 9)
        for nid in p1:
            with self.subTest(nid):
                self.assertEqual(self.nodes[nid].by, "absent")
                self.assertIn("P1", self.nodes[nid].reason)


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
                entry.load_table()
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
        DiskBoard.create(d, repo=self.repo, table=entry.load_table(), inputs={}, request_text="依頼")
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

    def test_open_board_passes_allow_halted(self):
        d = self.create()
        self.assertFalse(entry.open_board(d).allow_halted)
        self.assertTrue(entry.open_board(d, allow_halted=True).allow_halted)

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
            self.assertIsNone(entry.open_board(d).validator_runner)
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
        self.assertIsInstance(linekit.reply("judge_ok"), dict)
        self.assertTrue(str(linekit.work_home()).endswith("/single"))
        self.assertFalse(str(linekit.work_home().resolve()).startswith("/private/tmp/claude-"))

    def test_work_home_refuses_claude_tmp(self):
        """WORKS_DEV_HOME が Claude Code の一時フォルダの下なら、作る前に BoardGap（1 行）"""
        for base in ("/private/tmp/claude-works-test-0/home", "/tmp/claude-works-test-0/home"):
            with self.subTest(base), mock.patch.dict("os.environ", {"WORKS_DEV_HOME": base}):
                with self.assertRaises(BoardGap) as cm:
                    linekit.work_home()
                self.assertNotIn("\n", str(cm.exception))
                self.assertFalse(pathlib.Path(base).exists())



# ---------------------------------------------------------------- start（線 A の仕様 4 節。計画 Task 7）
# 入力の確かめ・盤面を開く・修正前のテストの記録・方針の文・切符。盤面は linekit の種（stats.py・test_stats.py。赤 2 件）で
# 本物の darkfactory の表で作る。切符は包みの家を使い捨ての場所に向けて書く（WORKS_ADAPTER_HOME）。
# 裁定 R52（review-graph と同等）: test_cmd が空で宣言も無い run は拒まない。p0.local_checks は任せ先に落ちたまま残し、
# run_ci は偽の素材を渡さずに role_needed を返し、start の返りの ci_role_go が真になる（任せ先の役のブロックは後の Task）
import subprocess  # noqa: E402

import ticket  # noqa: E402

SCRIPT = ROOT / "darkfactory" / "scripts" / "start.py"
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
        return {"request": str(req), "test_cmd": "", "thickness": "", "gates": "", "mid_gate": "", "adapter": "",
                "policy_md": "", **kw}

    def start(self, repo, raw=None, **kw):
        self.board = self.tmp / "board"
        return entry.start(self.board, repo, raw if raw is not None else self.raw(**kw), run_id="run-7")


class CheckInputsCase(StartCaseBase):
    def test_inputs_defaults(self):
        """依頼だけ → thickness 標準・gates ""・mid_gate always・adapter ""。返りに thickness_decider が無い"""
        repo = self.seed()
        got = entry.check_inputs({"request": str(request_file(self.tmp / "r.json"))}, repo)
        self.assertEqual(set(got), {"request_file", "items", "request_text", "test_cmd", "thickness", "gates",
                                    "mid_gate", "adapter", "policy_md"})
        self.assertEqual((got["thickness"], got["gates"], got["mid_gate"], got["adapter"], got["test_cmd"], got["policy_md"]),
                         ("標準", "", "always", "", "", ""))
        self.assertEqual(len(got["items"]), 2)
        self.assertEqual(got["request_file"], str((self.tmp / "r.json").resolve()))
        self.assertIn("mean", got["request_text"])
        self.assertEqual(entry.THICKNESS, ("軽量", "標準", "重厚"))
        self.assertEqual(entry.MID_GATES, ("always", "when_needed"))
        self.assertEqual(entry.ADAPTER_MODES, ("", "optional"))
        self.assertEqual(entry.GATES, ("", "merge"))

    def test_request_relative_to_repo(self):
        """相対の依頼のパスは対象の根から（1 本目の intake と同じ）"""
        repo = self.seed()
        request_file(repo / "req.json")
        self.assertEqual(entry.check_inputs({"request": "req.json"}, repo)["request_file"], str(repo / "req.json"))

    def test_light_refused_by_owner_decision(self):
        repo = self.seed()
        with self.assertRaises(entry.InputRefused) as cm:
            entry.check_inputs(self.raw(thickness="軽量"), repo)
        self.assertIn("持ち主の決定", str(cm.exception))
        self.assertIn("省けない節", str(cm.exception))

    def test_heavy_refused(self):
        repo = self.seed()
        with self.assertRaises(entry.InputRefused) as cm:
            entry.check_inputs(self.raw(thickness="重厚"), repo)
        self.assertIn("重厚で足す工程がまだ無い", str(cm.exception))

    def test_unknown_words_refused(self):
        repo = self.seed()
        for key in ("thickness", "mid_gate", "adapter", "gates"):
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
        for key, ok in (("mid_gate", "when_needed"), ("adapter", "optional"), ("gates", "merge")):
            with self.subTest(ok=ok):
                self.assertEqual(entry.check_inputs(self.raw(**{key: ok}), repo)[key], ok)

    def test_request_unreadable_or_not_array(self):
        """依頼が読めない・JSON の配列でない・依頼の型（写しの RL の REQUEST_SCHEMA）に合わない → InputRefused（1 行）"""
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

    def test_clean_carries_checked(self):
        """clean は写しの RR の規則で checked が要る（何を見たか）。count 0・detail も付く"""
        repo = self.seed()
        m = entry.local_checks_material(repo, "echo all-green", self.tmp / "ok.log")["material"]
        self.assertEqual((m["status"], m["count"]), ("clean", 0))
        self.assertIn("echo all-green", m["checked"])
        self.assertIn("exit 0", m["checked"])
        self.assertIn("all-green", m["detail"])

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
        b, p = DiskBoard.begin(self.tmp / "board", repo=repo, table=entry.load_table(), items=[{"where": "stats.py", "text": "x"}],
                               origin="works/darkfactory", base_rev="", request_text="x", stop_after_round=1)
        self.assertIn("p0.local_checks", p["run_engine"])
        got = entry.run_ci(b, "p0.local_checks", test_cmd="")
        self.assertEqual(got["by"], "engine")
        text = pathlib.Path(got["log"]).read_text(encoding="utf-8")
        for part in ("stage-one-out", "stage-two-err", "one", "two", "exit 3"):
            self.assertIn(part, text)
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "found")

    def test_fallback_empty_cmd_role_needed_no_material(self):
        """宣言が無く test_cmd も空 → 任せ先に落ちたまま、偽の素材を渡さず role_needed（裁定 R52）。印も置かない"""
        repo = self.seed()
        b, p = DiskBoard.begin(self.tmp / "board", repo=repo, table=entry.load_table(), items=[{"where": "stats.py", "text": "x"}],
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
        repo = self.seed(declared=True)
        got = self.start(repo, test_cmd="touch should-not-run")
        b = entry.open_board(self.board)
        self.assertEqual(b.record["process"]["checks"]["p0.local_checks"]["by"], "engine")
        self.assertEqual(b.record["materials"]["local_checks"]["status"], "found")   # 種は赤
        self.assertFalse((repo / "should-not-run").exists())
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
        """入力の拒みは盤面の置き場を作る前（軽量・知らない語・読めない依頼）"""
        repo = self.seed()
        for raw in (self.raw(thickness="軽量"), self.raw(mid_gate="x"), {"request": str(self.tmp / "nowhere.json")}):
            with self.subTest(raw):
                with self.assertRaises(entry.InputRefused):
                    self.start(repo, raw)
                self.assertFalse(self.board.exists())
                self.assertIsNone(ticket.read(repo))

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
        t = ticket.read(repo)
        self.assertEqual(t["run_id"], "run-7")
        self.assertEqual(t["board"], str(self.board))
        self.assertEqual(t["cwd"], str(repo))

    def test_start_head_line(self):
        repo = self.seed(declared=True)
        got = self.start(repo)
        absent = len(entry.load_table().absent())
        line = got["head_line"]
        for part in ("判定から", "依頼 2 件", "標準（既定）", "gates: 空", f"このラインに無い節: {absent} 個", "下げている所: 1 個"):
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
        got = self.start(repo, test_cmd=SEED_CMD, mid_gate="when_needed", adapter="optional")
        b = entry.open_board(self.board)
        self.assertEqual(got["base_rev"], linekit.git(repo, "rev-parse", "HEAD"))
        self.assertEqual((got["test_cmd"], got["mid_gate"], got["adapter"], got["thickness"], got["gates"]),
                         (SEED_CMD, "when_needed", "optional", "標準", ""))
        self.assertEqual((got["policy_paste"], got["policy_path"]), ("", ""))
        self.assertIsNone(b.state["inputs"]["gates"])
        doc = json.loads(b.work("start.json").read_text(encoding="utf-8"))
        self.assertEqual(doc["run_id"], "run-7")
        self.assertEqual(doc["test_cmd"], SEED_CMD)
        self.assertEqual(doc["mid_gate"], "when_needed")
        self.assertEqual(doc["request_file"], self.raw()["request"])

    def test_start_parallel_pr_by_helper(self):
        """p0.parallel_pr は prcheck.run_helper で回す（run_ci でない）。種は remote を持たないので任せ先に落ち、pr_go が真。
        start は印を置かない（blk-pr の pr-snap が置く）"""
        repo = self.seed(declared=True)
        got = self.start(repo)
        self.assertTrue(got["pr_go"])
        b = entry.open_board(self.board)
        inst = pending_inst(b, "p0.parallel_pr")
        self.assertTrue(inst.get("engine_fallback"))
        self.assertFalse(inst.get("launched_at"))
        self.assertNotIn("parallel_pr", b.record["materials"])

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
        self.assertIsNone(ticket.read(repo))

    def test_start_idempotent(self):
        """同じ置き場で呼び直しても盤面を作り直さず、同じ返り（Archon の再開）"""
        repo = self.seed()
        first = self.start(repo, test_cmd=SEED_CMD)
        again = entry.start(self.board, repo, self.raw(test_cmd=SEED_CMD), run_id="run-7")
        self.assertEqual({k: first[k] for k in ("base_rev", "ci_role_go", "pr_go", "head_line")},
                         {k: again[k] for k in ("base_rev", "ci_role_go", "pr_go", "head_line")})


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
        self.assertEqual(self.start(repo)["pr_go"], "pending")
        b = entry.open_board(self.board)
        still = entry.resume_after_ci(b)   # 役がまだ渡していない: 何も走らせず、同じ値
        self.assertEqual((still["ci_role_go"], still["pr_go"]), (True, "pending"))
        b = self.ci_role_done({"status": "found", "count": 1, "detail": "役が走らせた: 赤 2 件"})
        got = entry.resume_after_ci(b)
        self.assertEqual((got["ci_role_go"], got["pr_go"]), (False, True))   # 種は remote が無いので任せ先へ
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

    def test_fallback_cmd_runs_from_git_top(self):
        """任せ先の test_cmd は engine と同じく git の根（--show-toplevel）で走らせる（入力の cwd が下のフォルダでも）"""
        repo = self.seed()
        sub = repo / "sub"
        sub.mkdir()
        b, p = DiskBoard.begin(self.tmp / "board", repo=sub, table=entry.load_table(), items=[{"where": "stats.py", "text": "x"}],
                               origin="works/darkfactory", base_rev="", request_text="x", stop_after_round=1)
        got = entry.run_ci(b, "p0.local_checks", test_cmd="pwd -P")
        self.assertEqual(got["by"], "role")
        self.assertIn(f"\n{os.path.realpath(repo)}\n", "\n" + pathlib.Path(got["log"]).read_text(encoding="utf-8"))


class StartScriptCase(StartCaseBase):
    def env(self, repo, **kw):
        req = request_file(self.tmp / "req" / "request.json")
        base = {"INPUTS_REQUEST": str(req), "INPUTS_TEST_CMD": "", "INPUTS_THICKNESS": "", "INPUTS_GATES": "",
                "INPUTS_MID_GATE": "", "INPUTS_ADAPTER": "", "INPUTS_POLICY_MD": "", "ARTIFACTS_DIR": str(self.tmp / "art"),
                "WORKFLOW_ID": "wf-1", "WORKS_ADAPTER_HOME": str(self.home), "PYTHONDONTWRITEBYTECODE": "1"}
        env = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        env.update(base)
        env.update(kw)
        return {k: v for k, v in env.items() if v is not None}

    def run_script(self, repo, **kw):
        return subprocess.run([sys.executable, str(SCRIPT)], cwd=repo, env=self.env(repo, **kw), capture_output=True,
                              text=True, stdin=subprocess.DEVNULL)

    def test_start_script_refusal_exit_1(self):
        repo = self.seed()
        r = self.run_script(repo, INPUTS_THICKNESS="軽量")
        self.assertEqual(r.returncode, 1, r.stderr)
        self.assertEqual(r.stdout, "")
        self.assertEqual(len(r.stderr.strip().splitlines()), 1)
        self.assertIn("持ち主の決定", r.stderr)
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
        self.assertIn("判定から", got["head_line"])
        self.assertEqual(ticket.read(repo)["run_id"], "wf-1")
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
# 確かめは、役を起こす前に snapshot が今の周の置き場に写した accept.snapshot_tree と比べる（1 本目の写しの比べ）
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
        """p2.diagnose が待っている盤面（start の後、前提の役と並行 PR の任せ先の役の返答を take で渡した）。置き場は
        $ARTIFACTS_DIR/board の形（self.art / board）。返りは対象リポジトリ"""
        repo = self.seed(declared=True)
        self.art = self.tmp / "art"
        self.board = self.art / "board"
        entry.start(self.board, repo, self.raw(), run_id="run-7")
        for nid, reply in (("p0.parallel_pr", pr_reply()), ("p0.premises", PREMISES_REPLY)):
            launch(self.board, nid)
            got = entry.take(self.board, nid, reply, repo)
            self.assertTrue(got["ok"], got)
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
        self.assertEqual(set(json.loads(snap.read_text(encoding="utf-8"))), set(accept.SNAPSHOT_KEYS))
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
        table = entry.load_table()
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


class MainTakeCase(TakeCaseBase):
    """受け付けのスクリプトとして子で起こす（script_io.main と同じ環境変数の約束）。中身の拒否は 0 で 1 行（reason_file つき）、
    止めた盤面・BoardGap・環境変数の欠けは 2（標準出力は空・標準エラーに 1 行）"""

    def run_take(self, repo, nid, reply, **env):
        code = (f"import sys; sys.path.insert(0, {str(CORE)!r}); import entry; "
                f"sys.exit(entry.main_take({nid!r}))")
        base = {k: v for k, v in os.environ.items() if not k.startswith("INPUTS_")}
        base.update({"INPUTS_REPLY": json.dumps(reply, ensure_ascii=False), "INPUTS_BASE_REV": "",
                     "ARTIFACTS_DIR": str(self.art), "PYTHONDONTWRITEBYTECODE": "1"})
        base.update(env)
        base = {k: v for k, v in base.items() if v is not None}
        return subprocess.run([sys.executable, "-c", code], cwd=repo, env=base, capture_output=True, text=True,
                              stdin=subprocess.DEVNULL)

    def test_main_take_exit_codes(self):
        repo = self.judge_ready()
        launch(self.board, "p2.diagnose")
        # 中身の拒否: 0 と 1 行。理由の本文は reason_file に（役へは $LOOP_PREV でパスだけを渡す。裁定 R44）
        r = self.run_take(repo, "p2.diagnose", {"units": "壊れた"})
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = r.stdout.splitlines()
        self.assertEqual(len(lines), 1)
        got = json.loads(lines[0])
        self.assertFalse(got["ok"])
        self.assertEqual(pathlib.Path(got["reason_file"]).read_text(encoding="utf-8"), got["reason"])
        # 読めない返答も 0 と 1 行
        r = self.run_take(repo, "p2.diagnose", None, INPUTS_REPLY="{壊れた")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(json.loads(r.stdout)["ok"])
        # 通る: 0 と 1 行。reason_file は空
        r = self.run_take(repo, "p2.diagnose", linekit.reply("judge_ok"))
        self.assertEqual(r.returncode, 0, r.stderr)
        got = json.loads(r.stdout)
        self.assertTrue(got["ok"], got)
        self.assertEqual(got["reason_file"], "")
        self.assertIn("p2.fix_plan", got["ready"])
        # BoardGap（表で absent の節）: 2
        r = self.run_take(repo, "p0.purpose", {"text": "目的"})
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        # 環境変数の欠け: 2
        for name in ("INPUTS_REPLY", "INPUTS_BASE_REV", "ARTIFACTS_DIR"):
            with self.subTest(name):
                r = self.run_take(repo, "p2.fix_plan", plan_reply(["x"]), **{name: None})
                self.assertEqual((r.returncode, r.stdout), (2, ""))
                self.assertIn(name, r.stderr)
        # 止めた盤面: 2
        launch(self.board, "p2.fix_plan")
        halt(self.board)
        r = self.run_take(repo, "p2.fix_plan", plan_reply(["x"]))
        self.assertEqual((r.returncode, r.stdout), (2, ""))
        self.assertEqual(len(r.stderr.strip().splitlines()), 1, r.stderr)
        self.assertIn("止めた", r.stderr)
        self.assertFalse([*CORE.rglob("__pycache__")])


if __name__ == "__main__":
    unittest.main()
