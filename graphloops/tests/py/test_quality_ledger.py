"""盤面を横断して質の数を束ねる台本（scripts/quality-ledger.py）の検査。盤面は tmp_path に手で組む——読むだけで何も書かないこと・
壊れた盤面を読めないと数えること・機械が埋めた判定と据え置きを数えないこと・費用を会話ごとの最大で足すこと・置き場を相対で出すこと。"""
import importlib.util
import json

import pytest

from conftest import PLUGIN, REVIEW_GRAPH_PATH
from engine import rules as rules_mod
from engine import schema as schema_mod

_spec = importlib.util.spec_from_file_location("quality_ledger", PLUGIN / "scripts" / "quality-ledger.py")
ql = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ql)

_graph, _ = schema_mod.load_graph(REVIEW_GRAPH_PATH)
RULES = rules_mod.load_rules(REVIEW_GRAPH_PATH, _graph)


def board(root, rel, *, state=None, trace=(), rounds=None, raw_state=None):
    d = root / rel
    (d / "rounds").mkdir(parents=True)
    if raw_state is not None:
        (d / "state.json").write_text(raw_state, encoding="utf-8")
    elif state is not None:
        base = {"loop_name": "review-loop", "run_id": d.name, "graph": str(REVIEW_GRAPH_PATH), "status": "stopped",
                "round": 1, "rounds": []}
        (d / "state.json").write_text(json.dumps({**base, **state}, ensure_ascii=False), encoding="utf-8")
    (d / "trace.jsonl").write_text("".join(t if isinstance(t, str) else json.dumps(t, ensure_ascii=False) + "\n" for t in trace),
                                   encoding="utf-8")
    for n, rec in (rounds or {}).items():
        (d / "rounds" / f"round-{n}.json").write_text(json.dumps(rec, ensure_ascii=False), encoding="utf-8")
    return d


def engine(v):
    return {"root": "/somewhere/private/graphloops", "version": v}


def rows_of(root):
    return {r["where"]: r for r in (ql.read_run(d, d.relative_to(root).as_posix(), ql.Verdicts()) for d in ql.find_boards(root))}


def snapshot(root):
    return {p.relative_to(root).as_posix(): (p.stat().st_mtime_ns, p.read_bytes() if p.is_file() else None)
            for p in sorted(root.rglob("*"))}


def test_broken_and_missing_state_are_counted_unreadable(tmp_path):
    board(tmp_path, "graphloops/review-loop/20260101-000000", raw_state="{壊れた")
    board(tmp_path, "graphloops/review-loop/20260101-000001", trace=[{"t": "2026-01-01T00:00:00+09:00", "op": "init"}])
    board(tmp_path, "graphloops/review-loop/20260101-000002", raw_state="[1, 2]")
    board(tmp_path, "graphloops/review-loop/20260101-000003", state={"engine_changes": 5})
    rows = rows_of(tmp_path)
    assert rows["graphloops/review-loop/20260101-000000"]["unreadable"].startswith("state.json が読めない")
    assert rows["graphloops/review-loop/20260101-000001"]["unreadable"] == "state.json が無い"
    assert "unreadable" in rows["graphloops/review-loop/20260101-000002"]
    assert rows["graphloops/review-loop/20260101-000003"]["unreadable"] == "盤面の形が違う（TypeError）"
    agg = ql.aggregate(list(rows.values()))
    assert agg[ql.UNREADABLE]["runs"] == 4


def test_engine_field_absent_and_version_unreadable_are_distinct(tmp_path):
    board(tmp_path, "a/20260101-000000", state={})
    board(tmp_path, "b/20260101-000000", state={"engine": {"root": "/x", "version": None}})
    rows = rows_of(tmp_path)
    assert rows["a/20260101-000000"]["version"] == ql.NO_ENGINE
    assert rows["b/20260101-000000"]["version"] == ql.UNREAD_VERSION


def test_reading_writes_nothing_and_prints_no_absolute_path(tmp_path, capsys):
    root = tmp_path / "common"
    board(root, "worktrees/w/graphloops/review-loop/20260101-000000",
          state={"engine": engine("0.21.1"), "status": "running"},
          trace=[{"t": "2026-01-01T00:00:00+09:00", "op": "engine_changed", "root": str(tmp_path), "version": "0.21.1"},
                 {"t": "2026-01-01T00:05:00+09:00", "op": "role_run", "session_id": "s", "total_cost_usd": 1.0,
                  "accepted": True, "stderr": str(tmp_path), "wall_s": 3.0}],
          rounds={1: {"reviews": {"R1": {"status": "pass", "reason": str(tmp_path)}}}})
    before = snapshot(root)
    for flag in ([], ["--runs"], ["--json"]):
        assert ql.main([str(root), *flag]) == 0
    out = capsys.readouterr().out
    assert snapshot(root) == before, "盤面の置き場のファイルの一覧・中身・mtime が変わった"
    assert str(tmp_path) not in out
    assert "worktrees/w/graphloops/review-loop/20260101-000000" in out


def test_machine_written_and_carried_review_rows_are_not_verdicts(tmp_path):
    carried = RULES.CARRIED_REVIEW.format(round=1)
    board(tmp_path, "r/20260101-000000",
          state={"engine": engine("0.21.1"),
                 "engine_changes": [{"round": 1, "from": None, "to": engine("0.21.0")},
                                    {"round": 2, "from": engine("0.21.0"), "to": engine("0.21.1")}]},
          rounds={1: {"reviews": {"R1": {"status": "pass", "reason": "x"}, "R2": {"status": "redesign-needed", "reason": "y"},
                                  "R3": {"status": "not_applicable", "reason": "z"}}},
                  2: {"reviews": {"R1": {"status": "carried_over", "from_round": 1, "reason": "x"},
                                  "R2": {"status": "redesign-needed", "reason": "y" + carried}}}})
    agg = ql.aggregate(list(rows_of(tmp_path).values()))
    assert agg["0.21.0"]["reviews"] == {"R1": {"pass": 1}, "R2": {"redesign-needed": 1}}
    assert agg["0.21.0"]["held_review_rows"] == 1
    assert agg["0.21.1"]["reviews"] == {}
    assert agg["0.21.1"]["held_review_rows"] == 2
    assert agg["0.21.1"]["runs"] == 1 and agg["0.21.1"]["mixed_versions"] == 1


def test_cost_takes_session_max_and_counts_raw_values(tmp_path):
    t = "2026-01-01T00:00:00+09:00"
    board(tmp_path, "r/20260101-000000", state={"engine": engine("0.21.1")},
          trace=[{"t": t, "op": "engine_changed", "version": "0.21.1"},
                 {"t": t, "op": "role_run", "session_id": "s1", "total_cost_usd": 1.0, "accepted": False,
                  "why": "受け付けが拒んだ: 返答が JSON として読めない（候補 2 本すべてで失敗）\n  - 全文"},
                 {"t": t, "op": "role_run", "session_id": "s1", "total_cost_usd": 1.5, "accepted": True},
                 {"t": t, "op": "role_run", "session_id": "s2", "total_cost_usd": 0.5, "accepted": None},
                 {"t": t, "op": "role_run", "session_id": "s3", "exit": 1},
                 {"t": t, "op": "answer", "answer": "escalate", "kinds": ["scope"]},
                 {"t": t, "op": "answer", "answer": "continue", "kinds": ["regression", "policy"]},
                 '{"t": "2026-01-01T00:09:00+09:00", "op": "emi'])
    row = next(iter(rows_of(tmp_path).values()))
    a = ql.aggregate([row])["0.21.1"]
    assert a["cost_usd"] == pytest.approx(2.0)
    assert a["accepted"] == {"accepted=False": 1, "accepted=True": 1, "accepted=None": 1, "accepted の欄なし": 1}
    assert a["reject_heads"] == {"受け付けが拒んだ: 返答が JSON として読めない": 1}
    assert a["answers"] == {"escalate": 1, "continue": 1}
    assert a["answer_kinds"] == {"scope": 1, "regression": 1, "policy": 1}
    assert row["unreadable_parts"] == ["trace.jsonl の読めない行 1"]


def test_boards_under_any_root_and_multiple_roots(tmp_path, capsys):
    board(tmp_path / "one", "graphloops/review-loop/20260101-000000", state={"engine": engine("0.21.1")})
    board(tmp_path / "two", "anywhere/my-dir", state={"engine": engine("0.21.1")})
    assert ql.main([str(tmp_path / "one"), str(tmp_path / "two"), "--runs"]) == 0
    wheres = [json.loads(line)["where"] for line in capsys.readouterr().out.splitlines()]
    assert wheres == ["根1:graphloops/review-loop/20260101-000000", "根2:anywhere/my-dir"]
