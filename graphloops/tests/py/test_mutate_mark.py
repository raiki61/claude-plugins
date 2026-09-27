"""変異の実行器（リポジトリの根の tests/mutate.py）の印の写しで、pytest のテストを行の持ち主として名指す口。conftest.py の
pytest_runtest_protocol がテストの間だけ環境変数にテストの node id を入れ、印（mutate.mark_write）がその値を 4 つ目の欄に書き、
mutate.read_hits が pytest の覆いとして読む。環境変数の名前は 2 つのファイルに字面で在るので、ここで揃いを縛る（片方だけ変わると
pytest の印が全部 ? になり、全部の腕が pytest 一式に倒れて黙って遅くなる）"""
import importlib.util
import os
import types

import conftest
import pytest

_spec = importlib.util.spec_from_file_location("mutate_under_test", conftest.REPO / "tests" / "mutate.py")
mutate = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mutate)


@pytest.mark.small
def test_mark_names_the_running_test_and_reads_back_as_pytest_cover(tmp_path, monkeypatch):
    """回の中のテストは node id で、回の外（収集の時の import）は ? で、台本の回の印（変数が無い）は台本の覆いに入る"""
    assert conftest.MUTATE_MARK == mutate.PYTEST_MARK
    hits = tmp_path / "hits.txt"
    write = lambda aid: exec(mutate.mark_write(hits, aid))
    monkeypatch.delenv(mutate.PYTEST_MARK, raising=False)
    write("a0")   # 台本の回（変数が無い）
    gen = conftest.pytest_runtest_protocol(item=types.SimpleNamespace(nodeid="test_x.py::test_y[1]"), nextitem=None)
    next(gen)
    assert mutate.PYTEST_MARK not in os.environ   # 印の写しの回でなければ何もしない
    with pytest.raises(StopIteration):
        gen.send(None)
    monkeypatch.setenv(mutate.PYTEST_MARK, "?")
    write("a1")   # 回の外
    gen = conftest.pytest_runtest_protocol(item=types.SimpleNamespace(nodeid="test_x.py::test_y[1]"), nextitem=None)
    next(gen)
    write("a2")   # テストの間
    with pytest.raises(StopIteration):
        gen.send(None)
    assert os.environ[mutate.PYTEST_MARK] == "?"
    ids, cover = mutate.read_hits(hits, pytest=True)
    assert (ids, cover) == (["a1", "a2"], {"a1": ["?"], "a2": ["test_x.py::test_y[1]"]})
    assert mutate.read_hits(hits)[0] == ["a0"]


def _res(marker_rc):
    """pytest だけが通した腕（台本の覆いが無い）の行を並べた --out"""
    py = {"rc": 0, "how": "nodes"}
    ids = ["green", "red", "timeout", "confirm_red"]
    return {"marker": {"rc": marker_rc, "placed": ids, "seen": ids, "script_seen": [], "pytest_seen": ids},
            "control": {"root": {"rc": 0}, "pytest": {"rc": 0}},
            "arms": [{"id": "green", "title": "t", "status": "Survived", "own": False, "pytest": py, "pytest_only": True, "pytest_selected": True},
                     {"id": "red", "title": "t", "status": "Killed", "own": False, "pytest": py, "attribution": "pytest"},
                     {"id": "timeout", "title": "t", "status": "Timeout", "own": False, "pytest": {**py, "rc": "timeout"}, "pytest_only": True,
                      "unrunnable": "時間切れ（pytest）"},
                     {"id": "confirm_red", "title": "t", "status": "Killed", "own": False, "pytest": py, "attribution": "pytest_unrelated"}]}


IDS = ("green", "red", "timeout", "confirm_red")


@pytest.mark.small
def test_script_marker_red_keeps_pending_for_pytest_only_arms():
    """印の写しの台本が赤の回は『台本が行を通さなかった』と言えない。pytest だけで撃って緑だった腕は Survived でなく Pending
    （unrunnable に理由）にし、pytest_only と数えず、--gate-efficacy に『台本は行を通さない』と書かない。pytest の赤・時間切れ・
    確かめ直しの赤はそのまま。台本の印の写しが緑の回は今のまま（Survived・pytest_only）"""
    red = _res(2)
    s = mutate.evaluate(red, [{"id": i} for i in IDS])
    rows = {r["id"]: r for r in red["arms"]}
    assert {i: r["status"] for i, r in rows.items()} == {"green": "Pending", "red": "Killed", "timeout": "Timeout", "confirm_red": "Killed"}
    assert rows["green"]["unrunnable"] == mutate.MARKER_RED_PYTEST.format(rc=2) and rows["green"]["pytest"]["how"] == "nodes"
    assert not any(r.get("pytest_only") for r in red["arms"]) and s["pytest_only"] == []
    assert rows["timeout"]["unrunnable"] == "時間切れ（pytest）"
    assert "green" in s["unrunnable"] and "green" not in s["green"]
    notes = " ".join(a.get("note", "") for a in mutate.gate_efficacy(red)["arms"])
    assert "台本は行を通さない" not in notes and "pytest だけで撃って緑" in notes
    green = _res(0)
    s = mutate.evaluate(green, [{"id": i} for i in IDS])
    rows = {r["id"]: r for r in green["arms"]}
    assert rows["green"]["status"] == "Survived" and rows["green"]["pytest_only"] and rows["timeout"]["pytest_only"]
    assert s["pytest_only"] == sorted(IDS)
    assert "台本は行を通さない" in mutate.gate_efficacy(green)["arms"][0]["note"]


def _cov(marker_rc, pytest=None, stage=None):
    """覆いの無い行の件数を見る --out。auto の腕 2 本（a_none は台本も pytest も通らない・a_hit は通る）と、marker を持つ一覧の腕 1 本
    （l_none。通らない）"""
    auto = {"start": 0, "end": 0, "new": "False", "stmt": False, "in_function": True}
    sel = [{"id": "a_none", "auto": auto}, {"id": "a_hit", "auto": auto}, {"id": "l_none"}]
    res = {"marker": {"rc": marker_rc, "placed": ["a_none", "a_hit", "l_none"], "seen": ["a_hit"], **({"pytest": pytest} if pytest else {})},
           "control": {"root": {"rc": 0}}, **({"pytest_stage": stage} if stage else {}),
           "arms": [{"id": i, "title": "t", "status": "Survived", "own": False} for i in ("a_none", "a_hit", "l_none")]}
    if marker_rc:
        res["arms"][0]["status"] = "Pending"   # 印の写しが赤の回、shoot は通らなかった自動の腕を撃たずに Pending にする
    return res, sel


@pytest.mark.small
def test_uncovered_count_only_when_script_marker_is_green():
    """覆いの無い行の件数（summary.uncovered）は status NoCoverage の自動の腕から数え、一覧の腕は入れない。台本の印の写しが赤の回は
    数えられない（null）と言い、印字と --gate-efficacy は『通ったかを決めていない』と言う。pytest の覆いを使っていない回は件数を
    出したうえで台本だけで決めた覆いと添える"""
    res, sel = _cov(0, pytest={"rc": 0})
    s = mutate.evaluate(res, sel)
    assert s["uncovered"] == ["a_none"]
    lines = mutate.coverage_lines(res)
    assert lines[-1] == "覆いの無い行（台本も pytest も通らない）の自動の腕 1 本: a_none"
    assert "覆いの無い行（台本も pytest も通らない）の自動の腕 1 本" in mutate.gate_efficacy(res)["material"]["detail"]
    res, sel = _cov(2, pytest={"rc": 0})
    s = mutate.evaluate(res, sel)
    assert s["uncovered"] is None
    lines = mutate.coverage_lines(res)
    assert lines[0].startswith("印の写しが赤で、通ったかを決めていない腕") and lines[-1].startswith("覆いの無い行は数えられない（印の写しが赤（rc=2）")
    assert "覆いの無い行は数えられない" in mutate.gate_efficacy(res)["material"]["detail"]
    for res, sel in (_cov(0, pytest={"rc": 1, "why": "印の写しの pytest が緑でない（rc=1）"}), _cov(0, stage="uv が PATH に無い")):
        s = mutate.evaluate(res, sel)
        assert s["uncovered"] == ["a_none"]
        assert all("台本だけで決めた覆い" in x for x in mutate.coverage_lines(res))
    res, sel = _cov(0)
    res["arms"] = [r for r in res["arms"] if r["id"] == "l_none"]
    assert mutate.evaluate(res, sel[2:])["uncovered"] == [] and mutate.coverage_lines(res) == ["印を差したが通らなかった腕: a_none l_none"]
