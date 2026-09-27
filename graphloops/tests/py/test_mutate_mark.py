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
