"""層 2 の回し手（scenes.py）の部品: 列の形・返答の手直し・役の表の当て方・前置きの鍵・列を作る手の柵。盤面は回さない。"""
import json
import types

import glharness
import pytest
import scenes

pytestmark = pytest.mark.small


@pytest.fixture
def registry(monkeypatch):
    """登録表をテストの間だけ空にする（台本の筋書きの登録を汚さない）"""
    for name in ("HISTORIES", "ROLES", "ROWS"):
        monkeypatch.setattr(scenes, name, {})


def test_a_history_starts_at_init_and_has_each_mark_once(registry):
    with pytest.raises(ValueError, match="頭の出来事が init"):
        scenes.history("review/x", scenes.nxt(mark="a"))
    with pytest.raises(ValueError, match="同じ印が 2 度"):
        scenes.history("review/x", scenes.init("x"), scenes.nxt(mark="a"), scenes.nxt(mark="a"))
    with pytest.raises(ValueError, match="review か research"):
        scenes.history("other/x", scenes.init("x"))


def test_a_row_names_a_mark_of_its_history(registry):
    """行は列の印を指すだけ——前置きを選ぶ口は無く、無い印は集める段で落ちる"""
    scenes.history("review/x", scenes.init("x"), scenes.nxt(mark="a"), scenes.cmd("status", mark="b"))
    p = scenes.row("s.t", "頭", "review/x", "b", lambda s: True, id="b")
    assert p.values[:2] == ("review/x", "b") and scenes.ROWS == {"s.t": {("review/x", 3)}}
    with pytest.raises(KeyError, match="印 c が無い"):
        scenes.row("s.t", "頭", "review/x", "c", lambda s: True, id="c")


def test_registering_a_name_again_with_other_content_is_refused(registry):
    scenes.roles("std")
    scenes.roles("std")
    with pytest.raises(ValueError, match="別の中身"):
        scenes.roles("std", scenes.rule("p1.x"))


def test_lineage_follows_the_prefix_and_the_borrowed_history(registry):
    scenes.history("review/a", scenes.init("a"), scenes.nxt(mark="asked"))
    scenes.history("review/b", scenes.init("b"), scenes.cmd("patch", scenes.file("m.json", ref=("review/a", "asked", "state", "round"))),
                   scenes.nxt(mark="end"))
    assert scenes.lineage("review/b", 3) == ["review/b@1", "review/a@1", "review/a@2", "review/b@2", "review/b@3"]
    assert scenes.lineage("review/b", 0) == []


def test_needed_keeps_init_row_points_givens_and_borrowed_points(registry):
    scenes.history("review/a", scenes.init("a"), scenes.nxt(), scenes.nxt(mark="asked"), scenes.nxt())
    scenes.history("review/b", scenes.init("b"), scenes.cmd("patch", scenes.file("m.json", ref=("review/a", "asked", "state", "round"))),
                   scenes.nxt(), scenes.nxt(mark="end"))
    scenes.row("s.t", "頭", "review/b", "end", lambda s: True, id="x")
    assert scenes.Scenes("/nonexistent").needed() == {("review/a", 1), ("review/b", 1), ("review/a", 3), ("review/b", 3), ("review/b", 4)}


@pytest.mark.parametrize("spec, want", [
    (None, None),
    (scenes.replaced({"a": 9}), {"a": 9}),
    (scenes.merged({"b": 2}), {"plan": [{"x": 1}], "b": 2}),
    (scenes.merged({"n": [1]}, at=("plan", 0)), {"plan": [{"x": 1, "n": [1]}]}),
], ids=["none", "set", "merge", "merge-at"])
def test_reply_spec_rewrites_a_copy_of_the_script_answer(spec, want):
    out = {"plan": [{"x": 1}]}
    assert scenes._reply(spec, out) == want and out == {"plan": [{"x": 1}]}


def _driver(monkeypatch, seen):
    monkeypatch.setitem(scenes.EVENTS, "note", lambda d, ev, inst, out: seen.append((ev["text"], inst["id"])) or ev["text"])
    return scenes.Driver("review")


def _note(text, mark=None):
    return {"ev": "note", "text": text, **({"mark": mark} if mark else {})}


def test_hook_applies_the_first_rule_of_the_node_by_round_and_once(monkeypatch):
    seen = []
    d = _driver(monkeypatch, seen)
    hook = d.hook([scenes.rule("p1.x", round=2, before=[_note("r2")], reply=scenes.replaced({"r": 2})),
                   scenes.rule("p1.x", once="first", before=[_note("once", mark="first")], reply=scenes.merged({"m": 1})),
                   scenes.rule("p1.x", reply=scenes.replaced({"rest": True}))])
    run = types.SimpleNamespace(state=lambda: {"round": 1})
    inst = {"node": "p1.x", "id": "p1.x"}
    assert hook(run, inst, {"a": 0}) == {"a": 0, "m": 1}
    assert hook(run, inst, {"a": 0}) == {"rest": True}
    assert hook(types.SimpleNamespace(state=lambda: {"round": 2}), inst, {}) == {"r": 2}
    assert hook(run, {"node": "p1.other", "id": "p1.other"}, {"a": 0}) is None
    assert seen == [("once", "p1.x"), ("r2", "p1.x")] and d.got["first"] == ["note", "once"]


def test_a_step_that_fires_a_script_check_raises(monkeypatch):
    """列を作る手が台本の check を撃ったら止める（準備の段で撃った check は件数の柵の数えの外で落ちる）"""
    d = _driver(monkeypatch, [])
    real, ticks = glharness.tallies, [{"simulate": (0, 0)}, {"simulate": (1, 0)}]   # 前後で 1 件ずれる。後は本物（数える柵が読む）
    monkeypatch.setattr(glharness, "tallies", lambda: ticks.pop(0) if ticks else real())
    with pytest.raises(RuntimeError, match="台本の check が走った"):
        d.step(_note("x"), inst={"id": "i"})


def test_step_keeps_the_marked_reply_with_its_event_kind(monkeypatch):
    d = _driver(monkeypatch, [])
    d.run = types.SimpleNamespace(dir="/nonexistent/state", repo=None)
    stored, board = d.step(_note("v", mark="m"), inst={"id": "i"})
    assert stored == "v" and d.got == {"m": ["note", "v"]} and board.dir.as_posix() == "/nonexistent/state"


def test_views_give_procs_their_exit_and_streams():
    p = scenes.view("cmd", {"rc": 1, "out": json.dumps({"a": 1}), "err": "e"})
    assert (p.returncode, p.stderr, p.json()) == (1, "e", {"a": 1})
    assert scenes.view("next", {"status": "x"}) == {"status": "x"} and not isinstance(scenes.view("next", {}), scenes.Proc)


def test_digest_shows_the_reply_and_the_board(tmp_path):
    (tmp_path / "state.json").write_text(json.dumps({"status": "stopped", "round": 5, "loop": {"stop_reason": "max_rounds"}}), encoding="utf-8")
    board = scenes.Board(tmp_path)
    got = scenes.digest(scenes.Scene(scenes.Proc(rc=1, out="", err="理由が空"), board, {}))
    assert "rc=1" in got and "理由が空" in got and "round=5" in got and "stop_reason=max_rounds" in got
    got = scenes.digest(scenes.Scene({"status": "awaiting_human", "round": 2, "ask": {"kinds": ["x"]}}, scenes.Board(tmp_path / "no"), {}))
    assert "status=awaiting_human" in got and "['x']" in got and "盤面: 無い" in got


def test_play_reports_the_digest_when_the_expectation_raises():
    s = scenes.Scene(scenes.Proc(rc=0, out="", err=""), scenes.Board("/nonexistent"), {})
    with pytest.raises(AssertionError, match="rc=0.*KeyError"):
        scenes.play(lambda name, at: s, "review/x", "a", lambda s: s.got["missing"])
