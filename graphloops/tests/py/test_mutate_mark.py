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
    """pytest だけが通した腕（台本の覆いが無い）の行を並べた --out。p1＝pytest が緑 / p2＝pytest が赤 / p3＝pytest が時間切れ /
    p4＝確かめ直しの pytest 一式で赤"""
    py = {"rc": 0, "how": "nodes"}
    return {"marker": {"rc": marker_rc, "placed": ["p1", "p2", "p3", "p4"], "seen": ["p1", "p2", "p3", "p4"], "script_seen": [],
                       "pytest_seen": ["p1", "p2", "p3", "p4"]},
            "control": {"root": {"rc": 0}, "pytest": {"rc": 0}},
            "arms": [{"id": "p1", "title": "t", "status": "Survived", "own": False, "pytest": py, "pytest_only": True, "pytest_selected": True},
                     {"id": "p2", "title": "t", "status": "Killed", "own": False, "pytest": py, "attribution": "pytest"},
                     {"id": "p3", "title": "t", "status": "Timeout", "own": False, "pytest": {**py, "rc": "timeout"}, "pytest_only": True,
                      "unrunnable": "時間切れ（pytest）"},
                     {"id": "p4", "title": "t", "status": "Killed", "own": False, "pytest": py, "attribution": "pytest_unrelated"}]}


@pytest.mark.small
def test_script_marker_red_keeps_pending_for_pytest_only_arms():
    """印の写しの台本が赤の回は『台本が行を通さなかった』と言えない。pytest だけで撃って緑だった腕は Survived でなく Pending
    （unrunnable に理由）にし、pytest_only と数えず、--gate-efficacy に『台本は行を通さない』と書かない。pytest の赤・時間切れ・
    確かめ直しの赤はそのまま。台本の印の写しが緑の回は今のまま（Survived・pytest_only）"""
    red = _res(2)
    s = mutate.evaluate(red, [{"id": i} for i in ("p1", "p2", "p3", "p4")])
    rows = {r["id"]: r for r in red["arms"]}
    assert {i: r["status"] for i, r in rows.items()} == {"p1": "Pending", "p2": "Killed", "p3": "Timeout", "p4": "Killed"}
    assert rows["p1"]["unrunnable"] == mutate.MARKER_RED_PYTEST.format(rc=2) and rows["p1"]["pytest"]["how"] == "nodes"
    assert not any(r.get("pytest_only") for r in red["arms"]) and s["pytest_only"] == []
    assert rows["p3"]["unrunnable"] == "時間切れ（pytest）"
    assert "p1" in s["unrunnable"] and "p1" not in s["green"]
    notes = " ".join(a.get("note", "") for a in mutate.gate_efficacy(red)["arms"])
    assert "台本は行を通さない" not in notes and "pytest だけで撃って緑" in notes
    green = _res(0)
    s = mutate.evaluate(green, [{"id": i} for i in ("p1", "p2", "p3", "p4")])
    rows = {r["id"]: r for r in green["arms"]}
    assert rows["p1"]["status"] == "Survived" and rows["p1"]["pytest_only"] and rows["p3"]["pytest_only"]
    assert s["pytest_only"] == ["p1", "p2", "p3", "p4"]
    assert "台本は行を通さない" in mutate.gate_efficacy(green)["arms"][0]["note"]
