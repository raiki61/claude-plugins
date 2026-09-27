"""盤面を横断して質の数を束ねる台本（scripts/quality-ledger.py）の検査。盤面は tmp_path に手で組む——読むだけで何も書かないこと・
壊れた盤面を読めないと数えること・機械が埋めた判定と据え置きを数えないこと・今の述語が知らない行を数えられないと分けること・
費用を会話ごとの最大で足すこと・置き場を相対で出し自由文の絶対パスとログイン名を伏せること。"""
import getpass
import importlib.util
import json
import os
import types

import golden_adapter as ga
import pytest

from conftest import PLUGIN, REVIEW_GRAPH_PATH
from engine import rules as rules_mod
from engine import schema as schema_mod
from engine import util as util_mod

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


def test_unknown_review_keys_and_values_are_uncountable_by_key_and_value(tmp_path):
    board(tmp_path, "r/20260101-000000", state={"engine": engine("0.21.1")},
          rounds={1: {"reviews": {"R1": {"status": "pass", "reason": "x"}, "R2": {"status": "old-word", "reason": "y"},
                                  "R3": "文字列", "R4": {"reason": "z"}, "R5": {"status": "pass", "reason": "w"}}},
                  2: {"reviews": {"R1": {"status": "redesign-needed", "reason": "x"}}}})
    row = next(iter(rows_of(tmp_path).values()))
    r1, r2 = row["round_rows"]
    assert r1["reviews"] == {"R1": "pass"} and r1["held"] == 0
    assert r1["uncountable"] == {"R2": {"old-word": 1}, "R3": {ql.NOT_DICT: 1}, "R4": {ql.NO_STATUS: 1}, "R5": {"pass": 1}}
    assert r2["uncountable"] == {}, "周に鍵の無い R（2 周目の R2〜R4）は数えられないに入らない"
    agg = ql.aggregate([row])
    a = agg["0.21.1"]
    assert a["reviews"] == {"R1": {"pass": 1, "redesign-needed": 1}}
    assert a["uncountable_review_rows"] == 4
    assert a["uncountable_reviews"]["R2"] == {"old-word": 1}
    text = ql.render(agg, 1, "根 1 個")
    assert "数えられない R の行" in text and "old-word 1" in text


def test_real_verdicts_match_rules_hist_last_review_round_by_round(tmp_path):
    """台本の本物の判定と rules の hist_last_review（同じ述語の別の実装）を、辞書の行だけの周 1 本ずつで照らす"""
    carried = RULES.CARRIED_REVIEW.format(round=1)
    cases = [{"R1": {"status": "pass", "reason": "x"}, "R2": {"status": "carried_over", "from_round": 1, "reason": "x"}},
             {"R1": {"status": "old-word", "reason": "x"}, "R3": {"status": "not_applicable", "reason": "z"}},
             {"R2": {"status": "unverifiable", "reason": "y" + carried}, "R4": {"status": "not_run", "reason": "w"}},
             {"R1": {"status": "redesign-needed", "reason": "x"}, "R2": {"status": "premise-invalid", "reason": "p"}}]
    vd = ql.Verdicts().for_graph(None, "review-loop")
    V = types.SimpleNamespace(REVIEWS=vd["reviews"], REVIEW_STATUS=vd["status"])
    for i, reviews in enumerate(cases):
        board(tmp_path, f"p/{i}", state={"engine": engine("0.21.1")}, rounds={1: {"reviews": reviews}})
        ours = rows_of(tmp_path / "p")[str(i)]["round_rows"][0]["reviews"]
        h = types.SimpleNamespace(validator=V, round=1, rd=lambda n: {"done": {"p4.record": {}}},
                                  round_record=lambda n, rec={"reviews": reviews}: rec)
        theirs = {name: rv["status"] for name, rv in RULES.hist_last_review(h).items()}
        assert ours == theirs, f"周 {i}: 台本 {ours} / rules {theirs}"


def test_free_text_paths_and_login_are_redacted_before_grouping(tmp_path, capsys):
    user = getpass.getuser()
    home = os.path.expanduser("~")
    t = "2026-01-01T00:00:00+09:00"
    why = "受け付けが拒んだ: {}/unit.py::f: 返答が型に合わない（詳細）"
    board(tmp_path / "c", "r/20260101-000000", state={"engine": engine("0.21.1"), "graph": "missing-" + user + "-graph.json"},
          trace=[{"t": t, "op": "engine_changed", "version": "0.21.1"},
                 {"t": t, "op": "role_run", "session_id": "s1", "accepted": False, "why": why.format(tmp_path / "a")},
                 {"t": t, "op": "role_run", "session_id": "s2", "accepted": False, "why": why.format(home + "/b")},
                 {"t": t, "op": "role_run", "session_id": "s3", "accepted": False,
                  "why": "受け付けが拒んだ: 置き場" + str(tmp_path) + "/x.json が読めない"},
                 {"t": t, "op": "launched", "ok": False, "why": "projects/-Users-" + user + "-src-x/memory: 落ちた"}],
          rounds={1: {"reviews": {"R1": {"status": "pass", "reason": "x"}}}})
    a = ql.aggregate(list(rows_of(tmp_path / "c").values()))["0.21.1"]
    assert a["reject_heads"]["受け付けが拒んだ: <絶対パス>::f"] == 2, a["reject_heads"]
    outs = []
    for flag in ([], ["--runs"], ["--json"]):
        assert ql.main([str(tmp_path / "c"), *flag]) == 0
        outs.append(capsys.readouterr().out)
    out = "\n".join(outs)
    assert "<絶対パス>" in out and "<利用者>" in out
    assert str(tmp_path) not in out and home not in out
    assert "-" + user + "-" not in out
    assert ga.forbidden_in(out) == []


def test_unreadable_plugin_graph_is_a_note_not_a_crash(tmp_path, monkeypatch, capsys):
    fake = tmp_path / "plugin"
    (fake / "graphs").mkdir(parents=True)
    (fake / "graphs" / "broken.json").write_text("{壊れた", encoding="utf-8")
    monkeypatch.setattr(ql, "PLUGIN", fake)
    board(tmp_path / "c", "r/20260101-000000", state={"engine": engine("0.21.1"), "graph": "/x/broken.json"},
          rounds={1: {"reviews": {"R1": {"status": "pass", "reason": "x"}}}})
    row = next(iter(rows_of(tmp_path / "c").values()))
    assert "unreadable" not in row
    assert row["review_filter"].startswith("graph か検証器か rules が読めない")
    assert str(tmp_path) not in row["review_filter"]
    assert row["round_rows"][0]["uncountable"] == {"R1": {"pass": 1}}
    assert ql.main([str(tmp_path / "c")]) == 0
    got = capsys.readouterr()
    assert str(tmp_path) not in got.out + got.err

    monkeypatch.setattr(schema_mod, "load_graph", lambda path: (None, f"{path}: $ref が解けない"))
    why = ql.Verdicts._load("broken.json", "review-loop")["why"]
    assert why.endswith("$ref が解けない") and str(tmp_path) not in why

    def boom(path):
        raise RuntimeError("die を通らない")
    monkeypatch.setattr(schema_mod, "load_graph", boom)
    util_mod.LAST_DIE = "前の graph の文面"
    why = ql.Verdicts._load("broken.json", "review-loop")["why"]
    assert "RuntimeError" in why and "前の graph の文面" not in why
