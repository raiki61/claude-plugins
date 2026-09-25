"""柵（fence.py）が赤になることを、内側に回した pytest で確かめる。赤を一度も見ていない柵は効いていると扱わない。"""
import pytest

PASSING = "def test_a():\n    pass\n"


@pytest.fixture
def inner(pytester):
    def run(files, expected, *args):
        # 内側の置き場の conftest も、外側（この置き場の conftest.py）と同じ形で柵を載せる
        pytester.makeconftest("import fence, pathlib\n\n\ndef pytest_configure(config):\n"
                              f"    fence.install(config, pathlib.Path(__file__).parent, {expected})\n")
        pytester.makepyfile(**files)
        return pytester.runpytest_inprocess(*args)
    return run


@pytest.mark.parametrize("body", [
    pytest.param("import pytest\ndef test_b():\n    pytest.skip('x')\n", id="skip-in-test"),
    pytest.param("import pytest\n@pytest.mark.skip\ndef test_b():\n    pass\n", id="skip-marker"),
    pytest.param("import pytest\n@pytest.mark.xfail\ndef test_b():\n    assert 0\n", id="xfail"),
    pytest.param("import pytest\npytest.skip('x', allow_module_level=True)\ndef test_b():\n    pass\n", id="skip-module"),
    pytest.param("import pytest\npytest.importorskip('no_such_module_here')\ndef test_b():\n    pass\n", id="importorskip"),
])
def test_skip_fails_the_run(inner, body):
    r = inner({"test_ok": PASSING, "test_skip": body}, 2)
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*飛ばされたテストが 1 件*"])


@pytest.mark.parametrize("expected,got", [pytest.param(3, 2, id="fewer"), pytest.param(1, 2, id="more")])
def test_count_mismatch_fails_the_run(inner, expected, got):
    # 下限（<）に緩めると「多い」側が、上限に緩めると「少ない」側が緑になる。両向きで赤を見る
    r = inner({"test_ok": PASSING, "test_two": PASSING}, expected)
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines([f"*集めたテストが {got} 件（{expected} 件を期待）*"])


def test_emptied_file_still_counts_as_full_run(inner):
    # テストを全部消したファイルもモジュールとしては集まる——「一部だけ集めた回」と見なして柵を外さない
    r = inner({"test_ok": PASSING, "test_two": PASSING, "test_empty": "X = 1\n"}, 3)
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*集めたテストが 2 件（3 件を期待）*"])


def test_full_run_with_matching_count_passes(inner):
    r = inner({"test_ok": PASSING, "test_two": PASSING}, 2)
    assert r.ret == pytest.ExitCode.OK


@pytest.mark.parametrize("args", [
    pytest.param(("test_ok.py",), id="one-file"),
    pytest.param(("test_ok.py::test_a",), id="node-id"),
    pytest.param(("--ignore", "test_two.py"), id="ignore"),
])
def test_run_that_skips_files_drops_only_the_count(inner, args):
    # ファイルを集めない回は件数の柵を外し、外した旨を出す。飛ばしの見張りは外さない（下の -k の回で見る）
    r = inner({"test_ok": PASSING, "test_two": PASSING}, 99, *args)
    assert r.ret == pytest.ExitCode.OK
    r.stdout.fnmatch_lines(["*件数の柵を外した（置き場のテストのファイル 2 本のうち 1 本だけを集めた）*"])


def test_keyword_run_keeps_the_count(inner):
    # -k は集めた後で選ぶので、集めた数は変わらない——柵を付けたまま突き合わせる
    r = inner({"test_ok": PASSING, "test_two": PASSING}, 2, "-k", "test_ok")
    assert r.ret == pytest.ExitCode.OK and "件数の柵を外した" not in r.stdout.str()


def test_selected_run_still_fails_on_skip(inner):
    r = inner({"test_ok": PASSING, "test_skip": "import pytest\n@pytest.mark.skip\ndef test_b():\n    pass\n"}, 2, "-k", "test_")
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*飛ばされたテストが 1 件*"])
