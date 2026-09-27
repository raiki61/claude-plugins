"""線 A の入口のモジュール（.shared/core/entry.py）の表の分と、darkfactory の節の表（darkfactory/nodes.json）の検査。

表は手で書き、ここで写しの graph と突き合わせる（盤面の層の縛り 1〜5 と、線 A の行の決まり）。行の決まりは線 A の仕様 4 節と
持ち主の答え（2026-09-27）: p0.premises は役（blk-premises）、p0.parallel_pr は engine_run で任せ先は読むだけの役（blk-pr）、
p2.rejudge・p2.rejudge_third は役（blk-rejudge。包みが判定役の会話を継ぐ）、p0.purpose は線 B が足すので absent、手厚さは標準だけ。
盤面を作る試験は linekit の種（dev/target-seed/）を使い捨ての家（linekit.work_home()）の下に置いて回す。
"""
import json
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


if __name__ == "__main__":
    unittest.main()
