"""柵（fence.py）が赤になることを、内側に回した pytest で確かめる。赤を一度も見ていない柵は効いていると扱わない。"""
import pytest

PASSING = "def test_a():\n    pass\n"


@pytest.fixture
def inner(pytester):
    def run(files, expected, *args, sim=None):
        # 内側の置き場の conftest も、外側（この置き場の conftest.py）と同じ形で柵を載せる（sim は検査の件数と到達の期待値）
        pytester.makeconftest("import fence, pathlib\n\n\ndef pytest_configure(config):\n"
                              f"    fence.install(config, pathlib.Path(__file__).parent, {expected})\n"
                              + (f"    fence.expect_sim(config, {sim[0]}, {sim[1]})\n" if sim else ""))
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


@pytest.mark.parametrize("expected, args, ret, line", [
    pytest.param(2, ("--collect-only",), pytest.ExitCode.OK, "*検査の件数の柵と到達の柵を外した（集めるだけの回*", id="collect-only"),
    pytest.param(3, ("--collect-only",), pytest.ExitCode.TESTS_FAILED, "*集めたテストが 2 件（3 件を期待）*", id="collect-only-keeps-count"),
    pytest.param(2, (), pytest.ExitCode.TESTS_FAILED, "*台本の検査が 0 件走った（5 件を期待）*", id="run-keeps-sim"),
])
def test_collect_only_run_drops_only_the_sim_fences(inner, expected, args, ret, line):
    # 集めるだけの回は検査を 1 件も走らせない——検査の件数と到達の柵だけを外し、件数の柵は当てる。走らせる回は同じ期待値で赤
    r = inner({"test_ok": PASSING, "test_two": PASSING}, expected, *args, sim=(5, 0))
    assert r.ret == ret
    r.stdout.fnmatch_lines([line])


def test_keyword_run_keeps_the_count(inner):
    # -k は集めた後で選ぶので、集めた数は変わらない——柵を付けたまま突き合わせる
    r = inner({"test_ok": PASSING, "test_two": PASSING}, 2, "-k", "test_ok")
    assert r.ret == pytest.ExitCode.OK and "件数の柵を外した" not in r.stdout.str()


def test_selected_run_still_fails_on_skip(inner):
    r = inner({"test_ok": PASSING, "test_skip": "import pytest\n@pytest.mark.skip\ndef test_b():\n    pass\n"}, 2, "-k", "test_")
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*飛ばされたテストが 1 件*"])


DECLARED = "import pytest\n@pytest.mark.skipif(True, reason='SKIP process-group: POSIX の物')\ndef test_b():\n    pass\n"


def test_declared_skip_passes_only_when_its_capability_is_allowed(inner, monkeypatch):
    # 宣言つきの見送りは、能力が SKIP_ALLOW に在るときだけ許して一覧に出す。無い・別の能力・既定（空）なら今までどおり失敗
    monkeypatch.setenv("SKIP_ALLOW", "posix-mode process-group")
    r = inner({"test_ok": PASSING, "test_skip": DECLARED}, 2)
    assert r.ret == pytest.ExitCode.OK
    r.stdout.fnmatch_lines(["*見送り 1 件（SKIP_ALLOW で許した）*process-group*"])


@pytest.mark.parametrize("allow", [pytest.param("", id="default-empty"), pytest.param("fifo", id="other-capability")])
def test_declared_skip_fails_when_its_capability_is_not_allowed(inner, monkeypatch, allow):
    monkeypatch.setenv("SKIP_ALLOW", allow)
    r = inner({"test_ok": PASSING, "test_skip": DECLARED}, 2)
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*飛ばされたテストが 1 件*"])


def test_declared_xfail_is_not_allowed(inner, monkeypatch):
    # xfail は走らせて結果を見ない形なので、理由が宣言の形でも許さない
    monkeypatch.setenv("SKIP_ALLOW", "process-group")
    r = inner({"test_ok": PASSING, "test_x": "import pytest\n@pytest.mark.xfail(reason='SKIP process-group: x')\ndef test_b():\n    assert 0\n"}, 2)
    assert r.ret == pytest.ExitCode.TESTS_FAILED
