"""修正の形の腕ごとの測りと採否の判定（dev/fixmeasure.py。計画 220 Task 8）の検査。

一時の置き場に sqlite の偽の archon.db（Archon の 2 つの表の要る列だけ）と、本物の表で作った盤面（DiskBoard.create。git を使わない）を
置き、row が出来事と盤面から 1 run の行を組むか、verdict が計画に固定した採否の決まりどおりに判じるかを見る（FAST）。

語:
- 腕: 修正の形（current・af・g3・g1）ごとの run。固定材料: 同じ依頼を同じ所から始める盤面の写し（行の fixture は元の run の id）。
- 混ざり: その形で拒むはずの道具（g3 以外の Skill・g1 以外の Agent）が走った呼び出し。拒まれた呼び出し（tool_completed の
  tool_outcome が error）は refused に数え、混ざりに数えない。
"""
import contextlib
import hashlib
import io
import json
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True   # 下の import が pack の中に __pycache__ を作らないように
sys.path.insert(0, str(ROOT / "dev"))
sys.path.insert(0, str(ROOT / "blk-fix" / "lib"))
sys.path.insert(0, str(ROOT / ".shared" / "core"))

import adapter  # noqa: E402
import conflict  # noqa: E402
import deltamarks  # noqa: E402
import entry  # noqa: E402
import fixgates  # noqa: E402
import fixmeasure  # noqa: E402
import fixshape  # noqa: E402
import planbrief  # noqa: E402
import planmarks  # noqa: E402
import reads  # noqa: E402
import report  # noqa: E402
from board import DiskBoard  # noqa: E402

TOOL = ROOT / "dev" / "fixmeasure.py"
ARMS = ("current", "af", "g3", "g1")


# ---------------------------------------------------------------- 偽の archon.db
def node(step, ms=1000, usd=0.1, kind="agent"):
    """節の node_completed の出来事（Archon v0.11.1 の実物の欄の形: data.node.kind・timing.durationMs・spend.costUsd）"""
    cost = {"source": "provider", "value": usd} if usd is not None else {"source": "unavailable", "reason": "not_applicable"}
    return {"event_type": "node_completed", "step_name": step,
            "data": {"node": {"id": step.rsplit(".", 1)[-1], "kind": kind}, "timing": {"durationMs": ms},
                     "spend": {"costUsd": cost}}}


_calls = iter(range(1, 10 ** 6))


def tool(step, name, outcome="success"):
    """道具の呼び出しの組（tool_called と、同じ tool_call_id の tool_completed）。outcome が None なら完了の行を出さない"""
    cid = f"toolu_{next(_calls)}"
    called = {"event_type": "tool_called", "step_name": step,
              "data": {"tool_name": name, "tool_input": {}, "tool_call_id": cid}}
    if outcome is None:
        return (called,)
    return (called, {"event_type": "tool_completed", "step_name": step,
                     "data": {"tool_name": name, "duration_ms": 5, "tool_call_id": cid, "tool_outcome": outcome}})


def agent_start(step):
    """下請けが起きた印（task_activity の started・task_type local_agent。実物の archon.db の形）"""
    return {"event_type": "task_activity", "step_name": step,
            "data": {"task_id": f"a{next(_calls)}", "activity": "started", "description": "下請け", "task_type": "local_agent"}}


def agent(step, outcome="success"):
    """走った Agent の呼び出し（tool_called・tool_completed と、同じ節の local_agent の started）"""
    return (*tool(step, "Agent", outcome), agent_start(step))


def make_db(tmp, run="r1", events=(), status="completed", path=None):
    """Archon の 2 つの表（列は実物の名の一部）に 1 run を入れた db のパス。events の組（tuple）は平らにする"""
    db = pathlib.Path(path or tmp / "archon.db")
    con = sqlite3.connect(db)
    con.execute("CREATE TABLE IF NOT EXISTS remote_agent_workflow_runs (id TEXT PRIMARY KEY, workflow_name TEXT, status TEXT)")
    con.execute("CREATE TABLE IF NOT EXISTS remote_agent_workflow_events (id TEXT PRIMARY KEY, workflow_run_id TEXT, "
                "event_order INTEGER, event_type TEXT, step_index INTEGER, step_name TEXT, data TEXT)")
    con.execute("INSERT INTO remote_agent_workflow_runs VALUES (?, 'darkfactory', ?)", (run, status))
    flat = [e for x in events for e in (x if isinstance(x, tuple) else (x,))]
    for n, e in enumerate(flat, 1):
        con.execute("INSERT INTO remote_agent_workflow_events VALUES (?, ?, ?, ?, NULL, ?, ?)",
                    (f"{run}-{n}", run, n, e["event_type"], e["step_name"], json.dumps(e["data"], ensure_ascii=False)))
    con.commit()
    con.close()
    return db


# ---------------------------------------------------------------- 偽の盤面（本物の表・git なし）
def fields(n=2, units=None):
    """修正案の欄 n 項目（どれも tdd。項目 k の単位は u<k>）"""
    return [{"unit_keys": [units[k] if units else f"u{k + 1}"], "route": "tdd", "route_why": "",
             "tests": [{"id": f"test_x.py::test_{k}", "behavior": "振る舞い", "path": "直に呼ぶ", "red_kind": "assertion",
                        "red_why": "今は誤る"}], "rewrite_tests": [], "refactor": {"declared": False, "why": ""}}
            for k in range(n)]


def put(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(doc if isinstance(doc, str) else json.dumps(doc, ensure_ascii=False), encoding="utf-8")


def make_board(tmp, shape="af", items=2, fixture="run-src", *, start=None, calls=(), report_md=True, briefs=True,
               tdd_state=True, name="art"):
    """盤面（$ARTIFACTS_DIR/board）。start の控え（形と固定材料の印）・修正案の欄（凍結の印つき）・brief の控え・輪の状態
    （tdd-1/state.json。単位は欄の単位、calls は渡した行）・報告を置く"""
    art = pathlib.Path(tmp) / name
    (art / "repo").mkdir(parents=True)
    table = entry.load_table("darkfactory")
    DiskBoard.create(art / "board", repo=art / "repo", table=table, inputs={}, request_text="依頼",
                     **entry.open_kwargs("darkfactory", table))
    board = art / "board"
    doc = start if start is not None else {"fix_shape": shape, **({"fixture": {"source_run": fixture, "manifest_sha256": "0" * 64,
                                                                              "at": "2026-10-02T00:00:00"}} if fixture else {})}
    put(board / fixshape.START_REL, doc)
    if items:
        planmarks.save(board, 1, fields(items))
        if briefs:
            put(board / "r1" / planbrief.LEDGER, {"briefs": []})
    if tdd_state:
        keys = [f"u{k + 1}" for k in range(items)]
        put(board / "tdd-1" / "state.json", {"open_units": keys, "units": {k: {"unit_key": k, "route": "tdd"} for k in keys},
                                            "calls": list(calls)})
    if report_md:
        put(board / report.REPORT_FILE, "# 報告\n")
    return board


def accepted(board, whys):
    """受け付けた回の束の帳面の skipped と、受け付けが盤面の trace に載せる確かめなかった理由（fixgates.unchecked と同じ決まり）"""
    put(board / "r1" / fixgates.LEDGER, {"rows": [], "skipped": [{"pass": "first", "attempt": 1, "why": w} for w in whys]})
    gaps = fixgates.unchecked_whys(whys)
    if gaps:
        with open(board / "trace.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": "x", "op": fixgates.SKIPPED_OP, "node": "fix", "why": gaps}, ensure_ascii=False) + "\n")


def tdd_nodes(n):
    return [node("fixing__tdd-loop.tdd", ms=100, usd=0.01) for _ in range(n)]


class RowCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)
        self.home = self.tmp / "adapter-home"

    def row(self, db, board, run="r1"):
        return fixmeasure.row(db, run, board, adapter_home=self.home)

    def test_row_reads_cost_time_tools_from_events(self):
        db = make_db(self.tmp, run="r1", events=[node("fixing__fix-loop.fix", ms=1500, usd=0.4),
                                                 node("reviewing__delta-loop.review", ms=500, usd=0.1),
                                                 node("judging__judge-loop.judge", ms=900, usd=9.0),
                                                 tool("fixing__tdd-loop.tdd", "Skill")])
        board = make_board(self.tmp, shape="af", items=2)
        r = self.row(db, board)
        self.assertEqual(r["cost_usd"], {"fix_stage": 0.5, "fixing": 0.4})
        self.assertEqual(r["secs"]["fixing__fix-loop.fix"], 1.5)
        self.assertNotIn("judging__judge-loop.judge", r["secs"])
        self.assertEqual(r["contamination"], {"Skill": 1, "Agent": 0})   # af で Skill
        self.assertEqual((r["run_id"], r["shape"], r["fixture"], r["complete"], r["items"]), ("r1", "af", "run-src", True, 2))

    def test_loop_group_cost_is_not_counted_twice(self):
        """輪の節（loop_group）の node_completed は中の AI の節の費用の和を持つ（実物の archon.db）。AI の節だけを足す"""
        db = make_db(self.tmp, events=[node("fixing__fix-loop.fix", usd=0.4), node("fixing__fix-loop", usd=0.4, kind="loop_group"),
                                       node("fixing__fix-loop.fix-accept", usd=None, kind="exec")])
        r = self.row(db, make_board(self.tmp))
        self.assertEqual(r["cost_usd"], {"fix_stage": 0.4, "fixing": 0.4})
        self.assertEqual(list(r["secs"]), ["fixing__fix-loop.fix"])

    def test_refused_call_is_not_contamination(self):
        """柵が拒んだ呼び出しは skills: の一覧に残るので tool_called に出る（Task 2 の審査 M5）。Skill は完了の行の tool_outcome が
        error なら refused、完了の行の無い呼び出しは走ったかを言えないので混ざり。Agent は同じ節の local_agent の started が走った印で、
        無ければ refused"""
        db = make_db(self.tmp, events=[tool("fixing__tdd-loop.tdd", "Skill", "error"), tool("fixing__tdd-loop.tdd", "Skill", None),
                                       tool("fixing__fix-loop.fix", "Agent", "error"), tool("fixing__fix-loop.fix", "Agent", None),
                                       tool("fixing__tdd-loop.tdd", "Read")])
        r = self.row(db, make_board(self.tmp, shape="af"))
        self.assertEqual(r["refused"], {"Skill": 1, "Agent": 2})
        self.assertEqual(r["contamination"], {"Skill": 1, "Agent": 0})

    def test_agent_that_started_is_contamination_whatever_the_outcome(self):
        """Agent の tool_outcome は下請けが走っても error になりうる。同じ節に local_agent の started が在れば走った物に数える"""
        db = make_db(self.tmp, events=[agent("fixing__fix-loop.fix", "error")])
        r = self.row(db, make_board(self.tmp, shape="af"))
        self.assertEqual((r["contamination"]["Agent"], r["refused"]["Agent"]), (1, 0))

    def test_skill_that_ran_is_flagged_on_every_arm_but_g3(self):
        """柵（permissions.deny の Skill）が効くことはまだ実地で確かめていない（Task 3 の審査）。af・current・g1 の行で走った
        Skill を混ざりに出し、g3 では数えない。g1 の修正役の Agent は数えない"""
        for shape, want in (("af", 1), ("current", 1), ("g1", 1), ("g3", 0)):
            with self.subTest(shape=shape):
                db = make_db(self.tmp, run=f"r-{shape}", path=self.tmp / f"{shape}.db",
                             events=[tool("fixing__tdd-loop.tdd", "Skill"), agent("fixing__fix-ruled-loop.fix-ruled")])
                r = self.row(db, make_board(self.tmp, shape=shape, name=f"art-{shape}"), run=f"r-{shape}")
                self.assertEqual(r["contamination"]["Skill"], want)
                self.assertEqual(r["contamination"]["Agent"], 0 if shape == "g1" else 1)

    def test_row_counts_redo_rulings_misses_and_gaps(self):
        calls = [{"n": 1, "phase": "route", "ok": True}, {"n": 2, "phase": "test", "ok": False},
                 {"n": 3, "phase": "test", "ok": True}]
        board = make_board(self.tmp, shape="g3", items=2, calls=calls)
        for n in (1, 2):   # 修正の受け付けの拒否の本文（script_io が盤面の根に書く reject-accept_fix-<n>.txt）
            put(board / f"reject-accept_fix-{n}.txt", "拒否の理由")
        put(board / "reject-tdd_step-1.txt", "輪の拒否は calls で数える")
        put(board / "r1" / fixgates.LEDGER, {"rows": [{"pass": "first", "attempt": 1, "shape": "g3", "gate": "test_edits",
                                                       "id": "test_x.py::test_old", "detail": "変えた", "unit_keys": []}],
                                             "skipped": []})
        item = {"id": "c1-1", "round": 1, "source": "fix", "unit_key": "u1", "between": "brief と判定", "kind": "brief_vs_judgment",
                "why_both_cannot_hold": "両立しない理由", "which_is_right": "brief", "status": "ruled",
                "ruling": {"decision": "fix_test_scope", "text": "範囲を許す裁き", "limits": [], "by": "x"}}
        put(board / "r1" / conflict.FILE, {"items": [item, {**item, "id": "c1-2", "kind": None, "ruling": None}]})
        put(board / "out" / "r1" / "p3.delta_review.json", {"faces": [{"id": "f1"}, {"id": "f2"}]})
        with open(board / "trace.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": "x", "op": "done", "instance": "p3.delta_fix"}) + "\n")
        db = make_db(self.tmp, events=[*tdd_nodes(2), node("fixing__fix-loop.fix")])   # calls は 3 行・tdd の節は 2 回
        r = self.row(db, board)
        # 束の拒否も拒否の本文を書くので、fix_rejects は本文の数から束の回を引く（2 - 1）
        self.assertEqual(r["redo"], {"fix_rejects": 1, "tdd_rejects": 1, "battery_rejects": 1, "delta_faces": 2, "refix_rounds": 1,
                                     "subagent_redos": 0, "compliance_fails": 0, "quality_fails": 0})
        self.assertEqual(r["redo_total"], 6)
        self.assertEqual(r["rulings"], {"fix_test_scope": 1})
        self.assertEqual(r["divergences"], {"brief_vs_judgment": 1, "unkinded": 1})
        self.assertEqual(r["gate_misses"], 1)
        self.assertEqual(len(r["record_gaps"]), 1, r["record_gaps"])
        self.assertIn("calls", r["record_gaps"][0])

    def test_battery_rejects_count_attempts(self):
        """束の行は受け付けの回（周・pass・attempt）ごとに 1 回の作り直し（同じ回の 2 行は 1 回。preflight F23）"""
        board = make_board(self.tmp)
        row = {"shape": "af", "gate": "red_green", "detail": "緑でない", "unit_keys": ["u1"]}
        put(board / "r1" / fixgates.LEDGER, {"rows": [{**row, "pass": "first", "attempt": 1, "id": "a"},
                                                      {**row, "pass": "first", "attempt": 1, "id": "b"},
                                                      {**row, "pass": "ruled", "attempt": 1, "id": "a"}], "skipped": []})
        r = self.row(make_db(self.tmp), board)
        self.assertEqual((r["redo"]["battery_rejects"], r["gate_misses"]), (2, 3))

    def test_row_without_shape_record_is_a_gap(self):
        board = make_board(self.tmp, start={"test_cmd": ""})
        r = self.row(make_db(self.tmp), board)
        self.assertEqual((r["shape"], r["fixture"]), ("af", ""))
        self.assertTrue(any(fixshape.KEY in g for g in r["record_gaps"]), r["record_gaps"])

    def test_gaps_for_missing_loop_unit_and_brief(self):
        """tdd の項目の単位に輪の単位の行が無い・平の run でないのに欄が在って brief の控えが無い → 記録の欠け"""
        board = make_board(self.tmp, shape="g3", briefs=False)
        st = json.loads((board / "tdd-1" / "state.json").read_text(encoding="utf-8"))
        del st["units"]["u2"]
        put(board / "tdd-1" / "state.json", st)
        gaps = self.row(make_db(self.tmp), board)["record_gaps"]
        self.assertEqual(len(gaps), 2, gaps)
        self.assertIn("u2", gaps[0])
        self.assertIn("brief", gaps[1])
        plain = make_board(self.tmp, shape="current", briefs=False, name="plain")
        self.assertEqual(self.row(make_db(self.tmp, path=self.tmp / "p.db"), plain)["record_gaps"], [])   # 平の run は brief を切らない

    def test_unopenable_board_is_a_gap(self):
        board = self.tmp / "nowhere" / "board"
        board.mkdir(parents=True)
        r = self.row(make_db(self.tmp), board)
        self.assertTrue(any("盤面を開けない" in g for g in r["record_gaps"]), r["record_gaps"])
        self.assertFalse(r["complete"])

    def test_red_green_checked(self):
        """赤緑は受け付けた回の trace（fixgates.SKIPPED_OP）に飛ばした行が在れば偽。拒んだ回だけの帳面の skipped は数えない（受け付け
        が受けた回だけを見る）。輪の状態が無い（実行器の無い run）も偽。平の run は当てないので None（確かめたとは数えない）"""
        self.assertIs(self.row(make_db(self.tmp), make_board(self.tmp, shape="g3"))["red_green_checked"], True)
        skipped = make_board(self.tmp, shape="g3", name="skipped")
        accepted(skipped, [fixgates.NO_SUITE])
        rejected = make_board(self.tmp, shape="g3", name="rejected")
        put(rejected / "r1" / fixgates.LEDGER, {"rows": [], "skipped": [{"pass": "first", "attempt": 1, "why": fixgates.NO_SUITE}]})
        traced = make_board(self.tmp, shape="g1", name="traced")
        with open(traced / "trace.jsonl", "a", encoding="utf-8") as f:
            f.write(json.dumps({"t": "x", "op": fixgates.SKIPPED_OP, "node": "fix", "why": ["実行器が走らない"]}) + "\n")
        no_suite = make_board(self.tmp, shape="af", tdd_state=False, name="nosuite")
        plain = make_board(self.tmp, shape="current", name="plain")
        for n, (board, want) in enumerate(((skipped, False), (rejected, True), (traced, False), (no_suite, False), (plain, None))):
            with self.subTest(board=board.parent.name):
                got = self.row(make_db(self.tmp, path=self.tmp / f"{n}.db"), board)["red_green_checked"]
                self.assertIs(got, want)

    def test_red_green_skips_follow_the_battery_rule(self):
        """赤緑を確かめなかったかは束の受け付けと同じ決まり（fixgates.unchecked: OUT_OF_DUTY の理由は除く）で見る。義務の外の
        項目（人に回した単位だけを名指す項目）を飛ばしただけの帳面は確かめたまま、NO_SUITE は確かめていない"""
        for n, (why, want) in enumerate(((f"{fixgates.OUT_OF_DUTY}: 修正案の項目 2（単位 u2）", True), (fixgates.NO_SUITE, False))):
            with self.subTest(why=why[:20]):
                board = make_board(self.tmp, shape="g3", name=f"skip-{n}")
                accepted(board, [why])
                self.assertIs(self.row(make_db(self.tmp, path=self.tmp / f"s{n}.db"), board)["red_green_checked"], want)

    def test_g1_agent_without_subagent_writes_is_a_gap(self):
        """g1 で Agent が走ったのに、書き込みの記録に agent_id の行が無く、申告（bash_writes。記録の declared の行）だけが在る →
        フックの欠けを修正役の自己申告が隠した疑い（Task 7 の審査 M1）"""
        board = make_board(self.tmp, shape="g1", calls=())
        log = adapter.writes_path(entry.open_board(board, allow_halted=True).state["inputs"]["cwd"], self.home)
        put(log, json.dumps({"tool_name": "declared", "path": "/x/a.py"}) + "\n")
        db = make_db(self.tmp, events=[agent("fixing__fix-loop.fix")])
        gaps = self.row(db, board)["record_gaps"]
        self.assertEqual(len(gaps), 1, gaps)
        self.assertIn("agent_id", gaps[0])
        put(log, json.dumps({"tool_name": "Edit", "agent_id": "a1", "path": "/x/a.py"}) + "\n"
            + json.dumps({"tool_name": "declared", "path": "/x/b.py"}) + "\n")
        self.assertEqual(self.row(db, board)["record_gaps"], [])
        log.unlink()   # 記録が無い（家を取り違えた・包みの無い起動）も黙って [] にしない
        gaps = self.row(db, board)["record_gaps"]
        self.assertEqual(len(gaps), 1, gaps)
        self.assertIn("書き込みの記録が無い", gaps[0])

    def test_g1_board_with_empty_units_has_no_lost_unit_gap(self):
        """g1 は輪を回さず、輪の状態の units は空（tdd-start が元の結末だけを取る）。tdd の項目の単位の行が無いことを欠けにしない"""
        board = make_board(self.tmp, shape="g1")
        st = json.loads((board / "tdd-1" / "state.json").read_text(encoding="utf-8"))
        put(board / "tdd-1" / "state.json", {**st, "units": {}})
        self.assertEqual(self.row(make_db(self.tmp), board)["record_gaps"], [])

    def test_g1_subagent_redos(self):
        """g1 の下請けの作り直し: 修正役の節の local_agent の started のうち、項目ごとの 2 本（実装役と審査役）を超えた分の往復
        （2 本で 1 回）。ほかの形は 0"""
        for n, (starts, want) in enumerate(((4, 0), (7, 1), (9, 2))):
            with self.subTest(starts=starts):
                board = make_board(self.tmp, shape="g1", items=2, name=f"g1-{n}")
                log = adapter.writes_path(entry.open_board(board, allow_halted=True).state["inputs"]["cwd"], self.home)
                put(log, json.dumps({"tool_name": "Edit", "agent_id": "a1", "path": "/x/a.py"}) + "\n")
                db = make_db(self.tmp, path=self.tmp / f"g1-{n}.db", events=[agent("fixing__fix-loop.fix") for _ in range(starts)])
                r = self.row(db, board)
                self.assertEqual(r["redo"]["subagent_redos"], want)
                self.assertEqual(r["redo_total"], want)

    def test_g1_subagent_wake_up_is_not_a_second_start(self):
        """下請けが起き直すと同じ task_id の started がもう 1 行出る。起動は節ごとの task_id の数で数える（作り直しにしない）"""
        board = make_board(self.tmp, shape="g1", items=1)
        log = adapter.writes_path(entry.open_board(board, allow_halted=True).state["inputs"]["cwd"], self.home)
        put(log, json.dumps({"tool_name": "Edit", "agent_id": "a1", "path": "/x/a.py"}) + "\n")
        events = [agent("fixing__fix-loop.fix") for _ in range(2)]
        woke = [{**e[-1], "data": {**e[-1]["data"], "description": "起き直し"}} for e in events]
        r = self.row(make_db(self.tmp, events=[*events, *woke]), board)
        self.assertEqual(r["redo"]["subagent_redos"], 0)
        with self.subTest("task_id の無い started の 2 行は 2 つの起動"):
            bare = [{**agent_start("fixing__fix-loop.fix"), "data": {"activity": "started", "task_type": "local_agent"}}
                    for _ in range(2)]
            db = make_db(self.tmp, path=self.tmp / "bare.db",
                         events=[*tool("fixing__fix-loop.fix", "Agent"), *tool("fixing__fix-loop.fix", "Agent"), *bare])
            r = self.row(db, make_board(self.tmp, shape="af", name="bare"))
            self.assertEqual(r["contamination"]["Agent"], 2)

    def test_row_counts_two_verdicts(self):
        """差分の審査が受けた 2 判定の控え（盤面の trace の deltamarks.SAVED_OP）の準拠 fail と品質 fail を redo の 2 欄に数える。
        どちらも delta_faces と同じ穴を判定で数え直した物なので、redo_total には足さない"""
        board = make_board(self.tmp, shape="g3")
        with open(board / "trace.jsonl", "a", encoding="utf-8") as f:
            for comp, qual in (("fail", "pass"), ("pass", "fail"), ("not_applicable", "pass")):
                f.write(json.dumps({"t": "x", "op": deltamarks.SAVED_OP, "compliance": comp, "quality": qual}) + "\n")
        r = self.row(make_db(self.tmp), board)
        self.assertEqual((r["redo"]["compliance_fails"], r["redo"]["quality_fails"]), (1, 1))
        self.assertEqual(r["redo_total"], 0)

    def test_unavailable_cost_of_an_ai_node_is_a_gap(self):
        db = make_db(self.tmp, events=[node("fixing__fix-loop.fix", usd=None)])
        gaps = self.row(db, make_board(self.tmp))["record_gaps"]
        self.assertEqual(len(gaps), 1, gaps)
        self.assertIn("costUsd", gaps[0])

    def test_incomplete_run(self):
        self.assertFalse(self.row(make_db(self.tmp, status="failed"), make_board(self.tmp))["complete"])
        self.assertFalse(self.row(make_db(self.tmp, path=self.tmp / "b.db"), make_board(self.tmp, report_md=False, name="nr"))["complete"])

    def test_unknown_run_is_refused(self):
        with self.assertRaises(ValueError):
            self.row(make_db(self.tmp), make_board(self.tmp), run="no-such-run")

    def test_fix_reject_file_name_is_what_fix_accept_writes(self):
        """修正の受け付けの拒否の本文は script_io が reject-<受け付けの関数の名>-<n>.txt に書く。fix-accept・fix-ruled-accept は
        どちらも accept.py の accept_fix"""
        import script_io
        self.assertEqual(fixmeasure.FIX_REJECTS, f"{script_io.REJECT_PREFIX}accept_fix-*.txt")
        self.assertIn("main_accept(accept_fix", (ROOT / "blk-fix" / "scripts" / "accept.py").read_text(encoding="utf-8"))


# ---------------------------------------------------------------- 採否の決まり
def valid_row(arm, fixture, **over):
    return {"run_id": f"{arm}-{fixture}", "shape": arm, "fixture": fixture, "complete": True, "items": 2,
            "redo": {"fix_rejects": 1, "tdd_rejects": 1, "battery_rejects": 0, "delta_faces": 0, "refix_rounds": 0, "subagent_redos": 0},
            "redo_total": 2, "cost_usd": {"fix_stage": 1.0, "fixing": 0.8}, "secs": {"fixing__fix-loop.fix": 10.0},
            "rulings": {}, "divergences": {}, "gate_misses": 0, "record_gaps": [], "contamination": {"Skill": 0, "Agent": 0},
            "refused": {"Skill": 0, "Agent": 0}, "red_green_checked": None if arm == "current" else True, **over}


def rows4(fixtures=("f1", "f2", "f3"), over=None):
    """各腕・各固定材料の有効な行（items 2・抜け 0・欠け 0・混ざり 0）。over[(腕, 材料)] の辞書で欄を上書き"""
    over = over or {}
    return [valid_row(a, f, **over.get((a, f), {})) for f in fixtures for a in ARMS]


class VerdictCase(unittest.TestCase):
    def setUp(self):
        p = mock.patch.dict(fixmeasure.FIELDS_CHECKED, dict.fromkeys(fixmeasure.FIELDS_CHECKED, True))   # 欄の形を確かめた後（F21）
        p.start()
        self.addCleanup(p.stop)

    def test_verdict_keeps_g3_when_not_worse(self):
        got = fixmeasure.verdict(rows4())
        self.assertEqual(got["decision"], "keep_g3")
        self.assertEqual((got["missing"], got["invalid"], got["import_from_g1"]), ([], [], []))
        self.assertEqual(got["per_item"]["g3"], {"redo": 1.0, "cost": 0.5})
        self.assertEqual(got["misses"], {a: 0 for a in ARMS})

    def test_verdict_cost_margin(self):
        fs = ("f1", "f2", "f3")
        af = {("af", f): {"cost_usd": {"fix_stage": 1.0, "fixing": 1.0}} for f in fs}
        over = {**af, **{("g3", f): {"cost_usd": {"fix_stage": 1.11, "fixing": 1.0}} for f in fs}}
        self.assertEqual(fixmeasure.verdict(rows4(over=over))["decision"], "switch_to_af")
        at = {**af, **{("g3", f): {"cost_usd": {"fix_stage": 1.10, "fixing": 1.0}} for f in fs}}
        self.assertEqual(fixmeasure.verdict(rows4(over=at))["decision"], "keep_g3")

    def test_verdict_redo_must_not_be_worse(self):
        self.assertEqual(fixmeasure.verdict(rows4(over={("g3", "f2"): {"redo_total": 3}}))["decision"], "switch_to_af")

    def test_verdict_one_miss_rejects_g3(self):
        got = fixmeasure.verdict(rows4(over={("g3", "f1"): {"gate_misses": 1}}))
        self.assertEqual(got["decision"], "switch_to_af")
        self.assertEqual(got["misses"]["g3"], 1)

    def test_af_miss_keeps_g3_whatever_redo_and_cost(self):
        """抜けの在る腕は既定にしない（決まり 3 が勝つ）。作り直しと費用の比べは抜けが 0 の腕どうしの間だけ"""
        over = {("af", "f1"): {"gate_misses": 1}, **{("g3", f): {"redo_total": 5, "cost_usd": {"fix_stage": 3.0, "fixing": 3.0}}
                                                     for f in ("f1", "f2", "f3")}}
        self.assertEqual(fixmeasure.verdict(rows4(over=over))["decision"], "keep_g3")

    def test_verdict_both_missing_means_fix_gates_first(self):
        over = {("g3", "f1"): {"gate_misses": 1}, ("af", "f3"): {"gate_misses": 2}}
        self.assertEqual(fixmeasure.verdict(rows4(over=over))["decision"], "fix_gates_first")

    def test_verdict_g1_never_default_but_named_for_import(self):
        got = fixmeasure.verdict(rows4(over={("g1", f): {"redo_total": 0} for f in ("f1", "f2", "f3")}))
        self.assertIn(got["decision"], ("keep_g3", "switch_to_af"))
        self.assertEqual(got["import_from_g1"], ["redo_per_item"])
        cheap = fixmeasure.verdict(rows4(over={("g1", f): {"cost_usd": {"fix_stage": 0.9, "fixing": 0.9}} for f in ("f1", "f2", "f3")}))
        self.assertEqual(cheap["import_from_g1"], ["cost_per_item"])   # 0.90 倍ちょうどは取り込む

    def test_verdict_g1_with_miss_not_imported(self):
        over = {("g1", f): {"redo_total": 0} for f in ("f1", "f2", "f3")}
        over[("g1", "f2")]["gate_misses"] = 1
        self.assertEqual(fixmeasure.verdict(rows4(over=over))["import_from_g1"], [])

    def test_contamination_invalidates_row(self):
        got = fixmeasure.verdict(rows4(over={("af", "f2"): {"contamination": {"Skill": 1, "Agent": 0}}}))
        self.assertEqual(got["decision"], "incomplete")
        self.assertEqual([r[0] for r in got["invalid"]], ["af-f2"])
        self.assertIn("混ざり", got["invalid"][0][1])
        self.assertEqual(got["missing"], [["af", "f2"]])

    def test_rerun_replaces_an_invalid_row(self):
        """同じ組を 1 回回し直した有効な行が在れば、その組は欠けない（無効な行は invalid に名指したまま）"""
        rows = rows4(over={("af", "f2"): {"record_gaps": ["欠け"]}}) + [valid_row("af", "f2", run_id="af-f2-again")]
        got = fixmeasure.verdict(rows)
        self.assertEqual((got["decision"], got["missing"]), ("keep_g3", []))
        self.assertEqual([r[0] for r in got["invalid"]], ["af-f2"])

    def test_verdict_rows_without_red_green_are_incomplete(self):
        got = fixmeasure.verdict(rows4(over={("g3", "f3"): {"red_green_checked": False}}))
        self.assertEqual((got["decision"], got["missing"]), ("incomplete", [["g3", "f3"]]))

    def test_plain_rows_are_not_applicable_not_checked(self):
        """current の行の red_green_checked は None（当てない）で、有効な行のまま。current でない行の None は確かめていない"""
        self.assertEqual(fixmeasure.verdict(rows4())["missing"], [])
        got = fixmeasure.verdict(rows4(over={("af", "f1"): {"red_green_checked": None}}))
        self.assertEqual(got["missing"], [["af", "f1"]])

    def test_verdict_needs_three_fixtures(self):
        got = fixmeasure.verdict(rows4(fixtures=("f1", "f2")))
        self.assertEqual((got["decision"], got["missing"]), ("incomplete", []))

    def test_rows_outside_a_fixture_or_unfinished_are_invalid(self):
        rows = rows4() + [valid_row("g3", ""), valid_row("af", "f1", run_id="late", complete=False)]
        got = fixmeasure.verdict(rows)
        self.assertEqual(got["decision"], "keep_g3")
        self.assertEqual([r[0] for r in got["invalid"]], ["g3-", "late"])

    def test_vs_current_is_report_only(self):
        got = fixmeasure.verdict(rows4(over={("current", f): {"redo_total": 0, "cost_usd": {"fix_stage": 0.1, "fixing": 0.1}}
                                             for f in ("f1", "f2", "f3")}))
        self.assertEqual(got["decision"], "keep_g3")
        self.assertEqual(got["vs_current"], {"redo_per_item": 1.0, "cost_per_item": 0.45})
        for k in ("secs", "fixing_cost", "rulings", "divergences", "maintenance"):
            self.assertIn(k, got["report_only"])

    def test_unverified_fields_make_it_incomplete(self):
        """測る関数が頼る欄の形（FIELDS_CHECKED）を実物で確かめるまで判定は incomplete（preflight F21）。報告と読んだ証拠の印
        （report.COST_FIELD_VERIFIED・reads.EVENTS_VERIFIED）は見ない"""
        with mock.patch.dict(fixmeasure.FIELDS_CHECKED, {"local_agent_start": False}):
            got = fixmeasure.verdict(rows4())
        self.assertEqual((got["decision"], got["unverified"]), ("incomplete", ["local_agent_start"]))
        with mock.patch.object(report, "COST_FIELD_VERIFIED", False), mock.patch.object(reads, "EVENTS_VERIFIED", False):
            self.assertEqual(fixmeasure.verdict(rows4())["decision"], "keep_g3")


    def test_same_rows_same_output(self):
        self.assertEqual(json.dumps(fixmeasure.verdict(rows4()), ensure_ascii=False),
                         json.dumps(fixmeasure.verdict(rows4()), ensure_ascii=False))


class FieldsCase(unittest.TestCase):
    def test_fields_start_unchecked_and_say_what_to_look_at(self):
        """欄の印は最初の試しの run で確かめるまで偽。docstring がどの印も、何を見て真にするかを名指す"""
        self.assertEqual(fixmeasure.FIELDS_CHECKED, dict.fromkeys(("node_kind_cost", "tool_outcome_refusal", "local_agent_start"), False))
        for k in fixmeasure.FIELDS_CHECKED:
            self.assertIn(f"- {k}:", fixmeasure.__doc__)


class MaintenanceCase(unittest.TestCase):
    def test_maintenance_counts_lines_per_arm(self):
        m = fixmeasure.maintenance(ROOT)
        self.assertEqual(list(m), list(ARMS))
        self.assertEqual(m["current"], m["af"])
        self.assertGreater(m["g3"], m["af"])
        self.assertGreater(m["g1"], m["af"])


def tree_bytes(root: pathlib.Path) -> dict:
    return {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sorted(root.rglob("*")) if p.is_file()}


class CliCase(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.tmp = pathlib.Path(self._tmp.name)

    def cli(self, *args):
        return subprocess.run([sys.executable, str(TOOL), *map(str, args)], capture_output=True, text=True, encoding="utf-8",
                              env={"PATH": "/usr/bin:/bin", "PYTHONDONTWRITEBYTECODE": "1",
                                   "WORKS_ADAPTER_HOME": str(self.tmp / "adapter-home")})

    def test_cli_writes_nothing(self):
        board = make_board(self.tmp, shape="g3")
        db = make_db(self.tmp, events=[node("fixing__fix-loop.fix")])
        before = tree_bytes(self.tmp)
        got = self.cli("row", db, "r1", board)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(len(got.stdout.splitlines()), 1)
        row = json.loads(got.stdout)
        self.assertEqual((row["run_id"], row["shape"]), ("r1", "g3"))
        lines = self.tmp / "rows.jsonl"
        lines.write_text(json.dumps(row) + "\n", encoding="utf-8")
        before[lines.name] = hashlib.sha256(lines.read_bytes()).hexdigest()
        got = self.cli("verdict", lines)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(json.loads(got.stdout)["decision"], "incomplete")
        self.assertEqual(tree_bytes(self.tmp), before)

    def test_cli_adapter_home(self):
        """--adapter-home で書き込みの記録の家を名指す（試しの run の家は殻の家の下で、測る側の env と違う）"""
        board = make_board(self.tmp, shape="g1")
        home = self.tmp / "run-home"
        log = adapter.writes_path(entry.open_board(board, allow_halted=True).state["inputs"]["cwd"], home)
        put(log, json.dumps({"tool_name": "declared", "path": "/x/a.py"}) + "\n")
        db = make_db(self.tmp, events=[agent("fixing__fix-loop.fix")])
        got = self.cli("row", "--adapter-home", home, db, "r1", board)
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertIn("agent_id", " ".join(json.loads(got.stdout)["record_gaps"]))
        got = self.cli("row", db, "r1", board)   # env の家（記録が無い）
        self.assertIn("書き込みの記録が無い", " ".join(json.loads(got.stdout)["record_gaps"]))

    def test_cli_errors_exit_2(self):
        for args in ((), ("row", self.tmp / "none.db", "r1", self.tmp), ("verdict", self.tmp / "none.jsonl"), ("nope",),
                     ("row", "--adapter-home")):
            with self.subTest(args=args):
                got = self.cli(*args)
                self.assertEqual((got.returncode, got.stdout), (2, ""), got.stderr)
                self.assertTrue(got.stderr.strip())

    def test_cli_maintenance(self):
        got = self.cli("maintenance")
        self.assertEqual(got.returncode, 0, got.stderr)
        self.assertEqual(list(json.loads(got.stdout)), list(ARMS))

    def test_main_in_process(self):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            self.assertEqual(fixmeasure.main(["maintenance"]), 0)
        self.assertEqual(json.loads(out.getvalue()), fixmeasure.maintenance(ROOT))


if __name__ == "__main__":
    unittest.main()
