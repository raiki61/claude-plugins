"""盤面の層の DiskBoard（.shared/core/board.py）の開く・作る・保存の検査（仕様 4.1・4.4・9.1 の 2〜5・10）。

実物の盤面（tests/boards/real/）は state.works を持たず、inputs.cwd が元の置き場（別の worktree）を指す。開くときは一時の写しに
state.works を足し、state.graph・validator を写しに、inputs.cwd を一時の置き場に向けてから開く（元の置き場で git を呼ばない。
ディスクの見本は書き換えない）。作る試験は使い捨ての git リポジトリで回す。
"""
import contextlib
import dataclasses
import io
import json
import pathlib
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
CORE = ROOT / ".shared" / "core"
BOARDS = pathlib.Path(__file__).resolve().parent / "boards"
REAL = BOARDS / "real"
FOREIGN = BOARDS / "foreign"
REAL_NAMES = ("wt-ci-skip", "wt-layer1")
sys.dont_write_bytecode = True
sys.path.insert(0, str(CORE))

import board  # noqa: E402
from board import (BOARD_VERSION, CORE_DIR, GRAPH_PATH, VALIDATOR_PATH, BoardGap, BoardMismatch,  # noqa: E402
                   DiskBoard, NodeEntry, NodeTable, graph_expanded, rules_module)
import engine.board as engine_board  # noqa: E402  （board が写しの graphloops を sys.path に足す）
import engine.util as engine_util  # noqa: E402
from engine import commands as engine_commands  # noqa: E402
from engine.rules import cond_reads, registry  # noqa: E402
from engine.schema import graph_text  # noqa: E402
from engine.util import BoardConflict, Reject, sha  # noqa: E402

GRAPH = json.loads(GRAPH_PATH.read_text(encoding="utf-8"))
GRAPH_SHA = sha(graph_text(GRAPH_PATH))
GIT_ID = ["-c", "user.email=t@t", "-c", "user.name=t", "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]


def full_table():
    return NodeTable.everything(GRAPH, GRAPH_SHA)


def with_absent(table, nid, reason="このラインに無い", comes_with="後の線"):
    nodes = dict(table.nodes)
    nodes[nid] = NodeEntry(by="absent", reason=reason, comes_with=comes_with)
    return dataclasses.replace(table, nodes=nodes)


def read(p):
    return json.loads(pathlib.Path(p).read_text(encoding="utf-8"))


def write(p, obj):
    pathlib.Path(p).write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def real_copy(tmp, name, **state_edits):
    """real/<name> の一時の写し。state.graph・validator を写しに、inputs.cwd を写しの置き場に向け、state.works を足す"""
    d = pathlib.Path(tmp) / name
    shutil.copytree(REAL / name, d)
    st = read(d / "state.json")
    st["graph"] = str(GRAPH_PATH)
    st["validator"] = str(VALIDATOR_PATH)
    st["inputs"]["cwd"] = str(d)
    st["works"] = {"board_version": BOARD_VERSION}
    st.update(state_edits)
    write(d / "state.json", st)
    return d


def git(repo, *args):
    return subprocess.run(["git", *GIT_ID, "-C", str(repo), *args], capture_output=True, text=True, encoding="utf-8", check=True).stdout.strip()


def make_repo(tmp):
    """使い捨ての git リポジトリ（commit 1 つと、既定の置き場の方針の文書）"""
    repo = pathlib.Path(tmp) / "repo"
    repo.mkdir()
    git(repo, "init", "-q")
    (repo / "a.txt").write_text("a\n", encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "seed")
    pol = repo / ".git" / "graphloops"
    pol.mkdir()
    (pol / "policy.md").write_text("方針\n", encoding="utf-8")
    return repo


@contextlib.contextmanager
def git_cwd_kept():
    old = engine_util.GIT_CWD
    try:
        yield
    finally:
        engine_util.GIT_CWD = old


class TmpCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = pathlib.Path(self._tmp.name)
        self._cwd = git_cwd_kept()
        self._cwd.__enter__()

    def tearDown(self):
        self._cwd.__exit__(None, None, None)
        self._tmp.cleanup()


# ---------------------------------------------------------------- 実物の盤面を開く
class OpenRealCase(TmpCase):
    def test_attrs_superset_of_engine(self):
        for name in REAL_NAMES:
            with self.subTest(name):
                d = real_copy(self.tmp, name)
                eng = engine_board.Board(d)
                ours = DiskBoard.open(d, table=full_table(), repo=d)
                self.assertTrue(set(vars(eng)) <= set(vars(ours)), set(vars(eng)) - set(vars(ours)))
                self.assertIsInstance(ours, engine_board.Board)

    def test_reads_match_engine_board(self):
        for name in REAL_NAMES:
            with self.subTest(name):
                d = real_copy(self.tmp, name)
                eng = engine_board.Board(d)
                ours = DiskBoard.open(d, table=full_table(), repo=d)
                self.assertEqual(ours.round, eng.round)
                self.assertEqual(ours.round, 2)
                self.assertEqual(ours.rd, eng.rd)
                self.assertEqual(ours.loop_state, eng.loop_state)
                self.assertEqual(ours.record, eng.record)
                for nid in GRAPH["nodes"]:
                    self.assertEqual(ours.node_state(nid), eng.node_state(nid), nid)
                    for rnd in range(1, eng.round + 1):
                        self.assertEqual(ours.output_of_round(nid, rnd), eng.output_of_round(nid, rnd), f"{nid} r{rnd}")
                self.assertTrue(any(ours.output_of_round(n, 1) is not None for n in GRAPH["nodes"]))

    def test_foreign_board_refused_by_graph(self):
        boards = sorted(p for p in FOREIGN.iterdir() if p.is_dir())
        self.assertEqual(len(boards), 39)
        for d in boards:
            with self.subTest(d.name):
                got = read(d / "state.json")["graph_sha"]
                with self.assertRaises(BoardMismatch) as cm:
                    DiskBoard.open(d, table=full_table())
                msg = str(cm.exception)
                self.assertIn(got, msg)
                self.assertIn(GRAPH_SHA, msg)
                self.assertNotIn("board_version", msg)

    def test_no_works_field_refused(self):
        for name in REAL_NAMES:
            with self.subTest(name):
                before = (REAL / name / "state.json").read_bytes()
                with self.assertRaises(BoardMismatch) as cm:
                    DiskBoard.open(REAL / name, table=full_table())
                self.assertIn("board_version", str(cm.exception))
                self.assertEqual((REAL / name / "state.json").read_bytes(), before)

    def test_unknown_board_version_refused(self):
        d = real_copy(self.tmp, "wt-ci-skip", works={"board_version": BOARD_VERSION + 1})
        with self.assertRaises(BoardMismatch) as cm:
            DiskBoard.open(d, table=full_table())
        self.assertIn("board_version", str(cm.exception))

    def test_table_gap_refused_on_open(self):
        d = real_copy(self.tmp, "wt-ci-skip")
        nodes = dict(full_table().nodes)
        del nodes["p2.history"]
        gap = dataclasses.replace(full_table(), nodes=nodes)
        with self.assertRaises(BoardGap) as cm:
            DiskBoard.open(d, table=gap)
        self.assertIn("p2.history", str(cm.exception))
        wrong = dataclasses.replace(full_table(), graph_sha="000000000000")
        with self.assertRaises(BoardMismatch):
            DiskBoard.open(d, table=wrong)

    def test_table_with_other_graph_refused(self):
        """表が名指す graph（TDD 版）が盤面を作った graph（review-loop.json）と違えば開かない。文に両方の graph_sha"""
        d = real_copy(self.tmp, "wt-ci-skip")
        tdd_path = GRAPH_PATH.with_name("review-loop-tdd.json")
        tdd_sha = sha(graph_text(tdd_path))
        tdd = NodeTable.everything(graph_expanded(tdd_path), tdd_sha, "review-loop-tdd.json")
        before = (d / "state.json").read_bytes()
        with self.assertRaises(BoardMismatch) as cm:
            DiskBoard.open(d, table=tdd)
        self.assertIn(GRAPH_SHA, str(cm.exception))
        self.assertIn(tdd_sha, str(cm.exception))
        self.assertEqual((d / "state.json").read_bytes(), before)
        # 表の graph_sha だけを合わせても、graph の名前が違えば開かない（表の graph_sha はその表の graph と照らす）
        with self.assertRaises(BoardMismatch):
            DiskBoard.open(d, table=dataclasses.replace(full_table(), graph="review-loop-tdd.json"))

    def test_paths_rewritten_in_memory(self):
        d = real_copy(self.tmp, "wt-layer1")
        st = read(d / "state.json")
        st["graph"] = "/nowhere/graphloops/graphs/review-loop.json"
        st["validator"] = "/nowhere/scripts/review-record.py"
        st["inputs"]["scripts_dir"] = "/nowhere/scripts"
        st["inputs"]["review_md"] = "/nowhere/REVIEW.md"
        write(d / "state.json", st)
        before = (d / "state.json").read_bytes()
        b = DiskBoard.open(d, table=full_table(), repo=d)
        self.assertEqual(b.state["graph"], str(GRAPH_PATH))
        self.assertEqual(b.state["validator"], str(VALIDATOR_PATH))
        self.assertEqual(b.state["inputs"]["scripts_dir"], str(CORE_DIR / "scripts"))
        self.assertEqual(b.state["inputs"]["review_md"], str(CORE_DIR / "REVIEW.md"))
        self.assertEqual(len(b.nodes), 60)
        self.assertEqual((d / "state.json").read_bytes(), before)

    def test_copy_has_scalars_and_review_md(self):
        d = real_copy(self.tmp, "wt-ci-skip")
        b = DiskBoard.open(d, table=full_table(), repo=d)
        self.assertTrue((pathlib.Path(b.state["inputs"]["scripts_dir"]) / "comment-ratio.sh").is_file())
        self.assertTrue(pathlib.Path(b.state["inputs"]["review_md"]).is_file())
        self.assertEqual(pathlib.Path(b.state["inputs"]["review_md"]), CORE_DIR / "REVIEW.md")

    def test_open_sets_git_cwd_and_core(self):
        d = real_copy(self.tmp, "wt-ci-skip")
        b = DiskBoard.open(d, table=full_table())
        self.assertEqual(engine_util.GIT_CWD, str(d))
        DiskBoard.open(d, table=full_table(), repo=self.tmp)
        self.assertEqual(engine_util.GIT_CWD, str(self.tmp.resolve()))
        self.assertEqual(b.state["works"]["core"], {"commit": "a1202d0", "path": str(CORE_DIR)})


# ---------------------------------------------------------------- 作る
class CreateCase(TmpCase):
    def setUp(self):
        super().setUp()
        self.repo = make_repo(self.tmp)

    def create(self, name="board", table=None, **kw):
        kw.setdefault("inputs", {})
        kw.setdefault("request_text", "依頼")
        return DiskBoard.create(self.tmp / "art" / name, repo=self.repo, table=table or full_table(), **kw)

    def engine_init(self, d, **kw):
        """engine の cmd_init で同じリポジトリに盤面を作る（graphcheck.py は写しに無いので check_graph だけ外す）"""
        a = types.SimpleNamespace(graph=str(GRAPH_PATH), loop="review-loop", validator=str(VALIDATOR_PATH), request="依頼",
                                  document=None, lang=None, input=[f"cwd={self.repo}"], dir=str(d), thickness=None,
                                  decider=None, stop_after_round=None, unattended=False, unfenced_delegates=None)
        for k, v in kw.items():
            setattr(a, k, v)
        with mock.patch.object(engine_commands, "check_graph", lambda g, v: []), contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            engine_commands.cmd_init(a)
        return read(pathlib.Path(d) / "state.json")

    def test_create_unattended(self):
        """無人の run（engine の init --unattended）: state.unattended が engine と同じ。既定は False、真偽でない値は BoardGap"""
        self.assertIs(read(self.create().dir / "state.json")["unattended"], False)
        b = self.create("b2", unattended=True)
        self.assertIs(read(b.dir / "state.json")["unattended"], True)
        self.assertIs(self.engine_init(self.tmp / "eng", unattended=True)["unattended"], True)
        with self.assertRaises(BoardGap):
            self.create("b3", unattended="yes")
        self.assertFalse((self.tmp / "art" / "b3").exists())

    def test_create_texts_like_engine(self):
        """入口の文が engine の cmd_init と同じ: 止める周が 1 未満（engine は die）と、graph に宣言の無い入力の notes"""
        with self.assertRaises(BoardGap) as cm:
            self.create(stop_after_round=0)
        with self.assertRaises(SystemExit):
            self.engine_init(self.tmp / "eng0", stop_after_round=0)
        self.assertEqual(str(cm.exception), engine_util.LAST_DIE)
        b = self.create("b2", inputs={"GATES": "merge", "gates": "merge"})
        eng = self.engine_init(self.tmp / "eng", input=[f"cwd={self.repo}", "GATES=merge", "gates=merge"])
        self.assertEqual(read(b.dir / "state.json")["notes"], eng["notes"])
        with self.assertRaises(BoardGap):
            self.create("b3", stop_after_round=1.5)

    def test_create_like_engine_init(self):
        table = with_absent(full_table(), "r1.minimality", "R 系はこのラインに無い", "R 系のブロック")
        b = self.create(table=table)
        d = (self.tmp / "art" / "board").resolve()
        self.assertEqual(b.dir, d)
        st = read(d / "state.json")
        eng = self.engine_init(self.tmp / "eng")
        self.assertTrue(set(eng) <= set(st), set(eng) - set(st))
        self.assertTrue(set(eng["inputs"]) <= set(st["inputs"]), set(eng["inputs"]) - set(st["inputs"]))
        ins = st["inputs"]
        self.assertEqual(ins["request"], "依頼")
        self.assertIsNone(ins["document"])
        self.assertEqual(ins["lang"], eng["inputs"]["lang"])
        self.assertEqual(ins["cwd"], str(self.repo.resolve()))
        self.assertEqual(pathlib.Path(ins["rounds_dir"]).parent, d)
        pol = read(d / "record.json")["process"]["policy"]
        self.assertTrue(pol["copy"])
        self.assertEqual(pathlib.Path(pol["copy"]).parent.parent, d)
        self.assertTrue(pathlib.Path(pol["copy"]).is_file())
        self.assertEqual(st["validator"], str(VALIDATOR_PATH))
        self.assertEqual(st["graph_sha"], GRAPH_SHA)
        self.assertEqual(st["rev"], 1)
        w = st["works"]
        self.assertEqual(w["board_version"], BOARD_VERSION)
        self.assertEqual(w["line"], table.line)
        self.assertEqual(w["table_sha"], table.sha())
        self.assertEqual(w["core"]["commit"], "a1202d0")
        self.assertEqual(w["core"]["path"], str(CORE_DIR))
        self.assertEqual(w["not_in_line"], table.absent())
        self.assertEqual(len(w["not_in_line"]), 1)
        self.assertEqual(w["overrides"], [])
        rows = [json.loads(ln) for ln in (d / "trace.jsonl").read_text(encoding="utf-8").splitlines()]
        self.assertEqual(rows[0]["op"], "init")
        # 開き直せる
        again = DiskBoard.open(d, table=table)
        self.assertEqual(again.round, 1)

    def test_create_stop_after_round_and_max_rounds(self):
        b = self.create(stop_after_round=1, max_rounds=3)
        st = read(b.dir / "state.json")
        self.assertEqual(st["stop_after_round"], 1)
        self.assertEqual(st["max_rounds"], 3)
        with self.assertRaises(BoardGap):
            self.create("b2", stop_after_round=0)
        self.assertFalse((self.tmp / "art" / "b2").exists())

    def test_create_rejects_bad_inputs(self):
        with self.assertRaises(Reject):
            self.create(inputs={"gates": "x"})
        self.assertFalse((self.tmp / "art" / "board").exists())
        # on_init（置き場を作った後）で拒まれても置き場を残さない
        with self.assertRaises(Reject):
            self.create(inputs={"policy_md": str(self.tmp / "no-such.md")})
        self.assertFalse((self.tmp / "art" / "board").exists())

    def test_create_refuses_existing(self):
        d = self.tmp / "art" / "board"
        d.mkdir(parents=True)
        (d / "keep.txt").write_text("k", encoding="utf-8")
        with self.assertRaises(BoardGap):
            self.create()
        self.assertEqual(sorted(p.name for p in d.iterdir()), ["keep.txt"])

    def test_create_refuses_table_gap(self):
        nodes = dict(full_table().nodes)
        del nodes["p2.history"]
        with self.assertRaises(BoardGap):
            self.create(table=dataclasses.replace(full_table(), nodes=nodes))
        self.assertFalse((self.tmp / "art" / "board").exists())


# ---------------------------------------------------------------- 保存・scratch・作業ファイル・差し替え
class SavedBoardCase(TmpCase):
    """使い捨てのリポジトリで 1 度だけ作った盤面を、試験ごとに写して使う"""

    @classmethod
    def setUpClass(cls):
        cls._cls_tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(cls._cls_tmp.name)
        with git_cwd_kept():
            cls.repo = make_repo(tmp)
            cls.template = DiskBoard.create(tmp / "board", repo=cls.repo, table=full_table(), inputs={}, request_text="依頼").dir

    @classmethod
    def tearDownClass(cls):
        cls._cls_tmp.cleanup()

    def fresh(self, **state_edits):
        d = self.tmp / "board"
        shutil.copytree(self.template, d)
        if state_edits:
            st = read(d / "state.json")
            st.update(state_edits)
            write(d / "state.json", st)
        return d

    def open(self, d, **kw):
        return DiskBoard.open(d, table=full_table(), repo=self.repo, **kw)

    def test_edit_saves(self):
        d = self.fresh()
        with DiskBoard.edit(d, table=full_table(), repo=self.repo) as b:
            b.loop_state["x"] = 1
        st = read(d / "state.json")
        self.assertEqual(st["loop"]["x"], 1)
        self.assertEqual(st["rev"], 2)

    def test_edit_discards_on_exception(self):
        d = self.fresh()
        before = {n: (d / n).read_bytes() for n in ("state.json", "record.json")}
        with self.assertRaises(RuntimeError), DiskBoard.edit(d, table=full_table(), repo=self.repo) as b:
            b.loop_state["x"] = 1
            b.record["process"]["x"] = 1
            raise RuntimeError("boom")
        self.assertEqual({n: (d / n).read_bytes() for n in before}, before)

    def test_board_conflict(self):
        d = self.fresh()
        b1, b2 = self.open(d), self.open(d)
        b1.save()
        before = (d / "state.json").read_bytes()
        with self.assertRaises(BoardConflict):
            b2.save()
        self.assertEqual((d / "state.json").read_bytes(), before)

    def test_halted_needs_allow(self):
        halted = {"node": "converge", "round": 1, "by": "stop_after_round", "reason": "試験"}
        d = self.fresh(halted=halted)
        before = (d / "state.json").read_bytes()
        with self.assertRaises(Reject):
            self.open(d).save()
        self.assertEqual((d / "state.json").read_bytes(), before)
        b = self.open(d, allow_halted=True)
        b.loop_state["report"] = 1
        b.save()
        self.assertEqual(read(d / "state.json")["loop"]["report"], 1)

    def test_scratch_has_dir_and_validator(self):
        v1 = self.tmp / "v1-board"
        v1.mkdir()
        engine_util.GIT_CWD = "/sentinel"
        rec = {"base": None, "process": {"human_items": []}}
        b = DiskBoard.scratch(v1, review_rev="abc", record=rec, loop_state={"k": 1})
        self.assertEqual(engine_util.GIT_CWD, "/sentinel")
        self.assertIsInstance(b, engine_board.Board)
        self.assertEqual(b.dir, v1)
        self.assertEqual(b.state["validator"], str(VALIDATOR_PATH))
        self.assertEqual(b.state["inputs"]["review_rev"], "abc")
        self.assertEqual(b.round, 1)
        self.assertEqual(b.rd, engine_board.empty_round(1))
        self.assertIs(b.record, rec)
        self.assertEqual(b.loop_state, {"k": 1})
        self.assertEqual(b.node_state("p2.diagnose"), "pending")
        self.assertIsNone(b.output_of_round("p3.fix", 1))
        with self.assertRaises(BoardGap):
            b.save()
        self.assertEqual(list(v1.iterdir()), [])
        # record を渡さなければ RL の init_record の形
        b2 = DiskBoard.scratch(v1, review_rev="")
        self.assertEqual(b2.record, b2.rules.init_record(None, None))
        self.assertEqual(b2.loop_state, {})

    def test_work_path(self):
        st = read(self.template / "state.json")
        d = self.fresh(round=2, rounds=[*st["rounds"], engine_board.empty_round(2)])
        b = self.open(d)
        p = b.work("x.json")
        self.assertEqual(p, d / "r2" / "x.json")
        self.assertTrue((d / "r2").is_dir())
        self.assertFalse(p.exists())

    def test_overrides_global_only(self):
        d = self.fresh()
        def probe(b):
            return ["差し替えた"]

        b = self.open(d, overrides={"_final_gate_problems": (probe, "収束を宣言で止めない（試験）")})
        self.assertIs(b.rules._final_gate_problems, probe)
        # RL の関数は大域の名前で引くので、module の中の呼び出しにも効く
        self.assertEqual(eval("_final_gate_problems(None)", vars(b.rules)), ["差し替えた"])
        self.assertEqual(b.state["works"]["overrides"], [{"name": "_final_gate_problems", "reason": "収束を宣言で止めない（試験）"}])
        b.save()
        self.assertEqual(read(d / "state.json")["works"]["overrides"], b.state["works"]["overrides"])
        # 後で差し替え無しで開いても、差し替えた事実は残る
        b = self.open(d)
        self.assertEqual(len(b.state["works"]["overrides"]), 1)
        for name in ("converge", "judge_output", "checks_plan"):
            with self.subTest(name):
                with self.assertRaises(BoardGap) as cm:
                    self.open(d, overrides={name: (probe, "効かない")})
                self.assertIn(name, str(cm.exception))
        with self.assertRaises(BoardGap):
            self.open(d, overrides={"no_such_name": (probe, "綴り違い")})
        with self.assertRaises(BoardGap):
            self.open(d, overrides={"_final_gate_problems": (probe, "")})

    def test_overrides_conds_value(self):
        """CONDS が掴む条件は組み手 fn(RL) の返りで大域の名前と CONDS の値の両方が替わる。組み手が条件の関数そのもの・
        reads の無い関数を返す・落ちる時は名前つきの BoardGap。別の盤面には漏れない"""
        d = self.fresh()

        def build(rl):
            base = rl.spec_flow

            @cond_reads(*base.reads)
            def spec_flow(v):
                return base(v)
            return spec_flow

        b = self.open(d, overrides={"spec_flow": (build, "条件の差し替え（試験）")})
        new = b.rules.spec_flow
        self.assertTrue(hasattr(new, "reads"))
        self.assertIs(registry(b.rules, "CONDS")["spec_flow"], new)
        self.assertIsNot(registry(self.open(d).rules, "CONDS")["spec_flow"], new)

        def plain(rl):
            return lambda v: (True, "reads が無い")

        def boom(rl):
            raise RuntimeError("組み手が落ちた")

        for fn in (plain, boom, lambda v: (True, "条件の関数そのもの")):
            with self.subTest(fn=fn):
                with self.assertRaises(BoardGap) as cm:
                    self.open(d, overrides={"spec_flow": (fn, "効かない")})
                self.assertIn("spec_flow", str(cm.exception))

    def test_overrides_isolated(self):
        d = self.fresh()
        def probe(b):
            return []

        a = self.open(d, overrides={"_final_gate_problems": (probe, "試験")})
        other = self.open(d)
        self.assertIs(a.rules._final_gate_problems, probe)
        self.assertIsNot(other.rules._final_gate_problems, probe)
        self.assertIsNot(rules_module()._final_gate_problems, probe)

    def test_validator_runner_used(self):
        d = self.fresh()
        calls = []

        def runner(b, target):
            calls.append((b, target))
            return {"exit": 0, "out": "偽", "validator": "偽"}

        b = self.open(d, validator_runner=runner)
        self.assertEqual(b.run_validator("t"), {"exit": 0, "out": "偽", "validator": "偽"})
        self.assertEqual(calls, [(b, "t")])
        self.assertEqual(b.state["validator"], str(VALIDATOR_PATH))
        self.assertEqual(b.run_validator(), {"exit": 0, "out": "偽", "validator": "偽"})
        self.assertEqual(calls[-1], (b, None))


# ---------------------------------------------------------------- 部品の置き場（scope）と公開の名（published）
def last_trace_row(b):
    return json.loads((b.dir / "trace.jsonl").read_text(encoding="utf-8").splitlines()[-1])


class ScopeCase(TmpCase):
    """scope は include の単位の置き場。空なら今の置き場のまま。published の形に合う名は scope の外の r<N>/ に置く"""

    @classmethod
    def setUpClass(cls):
        cls._cls_tmp = tempfile.TemporaryDirectory()
        tmp = pathlib.Path(cls._cls_tmp.name)
        with git_cwd_kept():
            cls.repo = make_repo(tmp)
            cls.template = DiskBoard.create(tmp / "board", repo=cls.repo, table=full_table(), inputs={}, request_text="依頼").dir

    @classmethod
    def tearDownClass(cls):
        cls._cls_tmp.cleanup()

    def open(self, **kw):
        d = self.tmp / "board"
        if not d.exists():
            shutil.copytree(self.template, d)
        return DiskBoard.open(d, table=full_table(), repo=self.repo, **kw)

    def test_empty_scope_keeps_today_paths(self):
        b = self.open()
        self.assertEqual(b.scope, "")
        self.assertEqual(b.published, frozenset())
        self.assertEqual(b.work("rule-tree.json"), b.dir / "r1" / "rule-tree.json")
        self.assertEqual(b.scope_root, b.dir)
        b.trace("probe")
        self.assertNotIn("scope", last_trace_row(b))

    def test_scoped_private_name_goes_under_scope_root(self):
        b = self.open(scope="fixing")
        self.assertEqual(b.work("rule-tree.json"), b.dir / "fixing" / "r1" / "rule-tree.json")
        self.assertTrue((b.dir / "fixing" / "r1").is_dir())
        self.assertEqual(b.scope_root, b.dir / "fixing")

    def test_published_name_stays_in_round_place(self):
        b = self.open(scope="fixing", published=frozenset({"fix-held-reply.json", "prompt-*.md"}))
        self.assertEqual(b.work("fix-held-reply.json"), b.dir / "r1" / "fix-held-reply.json")
        self.assertEqual(b.work("prompt-p3.fix.md"), b.dir / "r1" / "prompt-p3.fix.md")
        self.assertEqual(b.work("rule-tree.json"), b.dir / "fixing" / "r1" / "rule-tree.json")

    def test_trace_row_carries_scope_when_scoped(self):
        b = self.open(scope="refitting")
        b.trace("probe")
        self.assertEqual(last_trace_row(b)["scope"], "refitting")

    def test_held_trace_carries_scope_at_save(self):
        """save まで控えた trace の行も、書く時に scope が付く（engine の save が _write_trace を呼ぶ）"""
        b = self.open(scope="refitting")
        b.held_trace = []
        b.trace("held")
        b.save()
        row = last_trace_row(b)
        self.assertEqual((row["op"], row["scope"]), ("held", "refitting"))

    def test_bad_scope_names_refused(self):
        for s in ("r2", "a/b", "..", "x y", "-x", "1fix"):
            with self.subTest(s=s), self.assertRaises(ValueError) as cm:
                self.open(scope=s)
            self.assertIn(repr(s), str(cm.exception))

    def test_scratch_has_empty_scope(self):
        b = DiskBoard.scratch(self.tmp, review_rev="")
        self.assertEqual((b.scope, b.published), ("", frozenset()))
        self.assertEqual(b.scope_root, self.tmp)


# ---------------------------------------------------------------- 盤面なしで写しを読む口
class CopyReadCase(unittest.TestCase):
    def test_rules_module_fresh(self):
        a, b = rules_module(), rules_module()
        self.assertIsNot(a, b)
        for m in (a, b):
            self.assertTrue(callable(m._unproven))
            self.assertTrue(callable(m._lane_errors))
        self.assertIsNot(rules_module(GRAPH_PATH), a)

    def test_graph_expanded_has_lane_reply(self):
        g = graph_expanded()
        self.assertIn("lane_reply", g["$defs"])
        self.assertIn("gate_arm", g["$defs"])
        self.assertNotIn("$ref", json.dumps(g["$defs"]["lane_reply"]))   # 中の gate_arm も開いてある
        self.assertEqual(len(g["nodes"]), 60)
        self.assertEqual(g["nodes"], DiskBoard.scratch(pathlib.Path("/nowhere"), review_rev="").graph["nodes"])
        self.assertEqual(graph_expanded(GRAPH_PATH)["$defs"].keys(), g["$defs"].keys())

    def test_constants(self):
        self.assertEqual(BOARD_VERSION, 1)
        self.assertEqual(CORE_DIR, CORE.resolve())
        self.assertTrue(GRAPH_PATH.is_file())
        self.assertTrue(VALIDATOR_PATH.is_file())
        self.assertEqual(board.GRAPH_SHA, "9a1e3957f23d")


if __name__ == "__main__":
    unittest.main()
