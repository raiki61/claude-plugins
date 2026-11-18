"""チェック（fence.py）が赤になることを、内側に回した pytest で確かめる。赤を一度も見ていないチェックは効いていると扱わない。"""
import pytest

PASSING = "def test_a():\n    pass\n"


@pytest.fixture
def inner(pytester):
    def run(files, *args, reached=None):
        # 内側の置き場の conftest も、外側（この置き場の conftest.py）と同じ形でチェックを載せる（reached は到達の期待値）
        pytester.makeconftest("import fence, pathlib\n\n\ndef pytest_configure(config):\n"
                              "    fence.install(config, pathlib.Path(__file__).parent)\n"
                              + (f"    fence.expect_sim(config, {reached})\n" if reached is not None else ""))
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
    r = inner({"test_ok": PASSING, "test_skip": body})
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*飛ばされたテストが 1 件*"])


def test_emptied_file_fails_the_run(inner):
    # テストを全部消したファイルもモジュールとしては集まり、pytest は緑と報告する——空のファイルを名指して赤
    r = inner({"test_ok": PASSING, "test_two": PASSING, "test_empty": "X = 1\n"})
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*テストが 1 件も無いファイルが 1 本*test_empty.py*"])


def test_full_run_passes(inner):
    r = inner({"test_ok": PASSING, "test_two": PASSING})
    assert r.ret == pytest.ExitCode.OK
    assert "テストが 1 件も無いファイル" not in r.stdout.str()


def test_collection_error_fails_the_run(inner):
    # 集める段の誤り（import の失敗）は pytest 自身が止める。fence が緑に書き換えない
    r = inner({"test_ok": PASSING, "test_broken": "import no_such_module_here\ndef test_b():\n    pass\n"})
    assert r.ret == pytest.ExitCode.INTERRUPTED
    r.stdout.fnmatch_lines(["*error*during collection*"])


@pytest.mark.parametrize("args", [
    pytest.param(("test_ok.py",), id="one-file"),
    pytest.param(("test_ok.py::test_a",), id="node-id"),
    pytest.param(("--ignore", "test_empty.py"), id="ignore"),
])
def test_run_that_skips_files_drops_only_the_empty_file_check(inner, args):
    # ファイルを集めない回は空のファイルのチェックを外し、外した旨を出す。飛ばしの見張りは外さない（下の -k の回で見る）
    r = inner({"test_ok": PASSING, "test_empty": "X = 1\n"}, *args)
    assert r.ret == pytest.ExitCode.OK
    r.stdout.fnmatch_lines(["*空のファイルのチェックを外した（置き場のテストのファイル 2 本のうち 1 本だけを集めた）*"])


@pytest.mark.parametrize("files, args, ret, line", [
    pytest.param({"test_ok": PASSING}, ("--collect-only",), pytest.ExitCode.OK, "*到達のチェックを外した（集めるだけの回*", id="collect-only"),
    pytest.param({"test_ok": PASSING, "test_empty": "X = 1\n"}, ("--collect-only",), pytest.ExitCode.TESTS_FAILED,
                 "*テストが 1 件も無いファイルが 1 本*", id="collect-only-keeps-empty-file"),
    pytest.param({"test_ok": PASSING}, (), pytest.ExitCode.TESTS_FAILED, "*到達した値が 0 個（1 個を期待）*", id="run-keeps-reach"),
])
def test_collect_only_run_drops_only_the_reach_check(inner, files, args, ret, line):
    # 集めるだけの回は検査を 1 件も走らせない——到達のチェックだけを外し、空のファイルのチェックは当てる。走らせる回は同じ期待値で赤
    r = inner(files, *args, reached=1)
    assert r.ret == ret
    r.stdout.fnmatch_lines([line])


def test_keyword_run_keeps_the_empty_file_check(inner):
    # -k は集めた後で選ぶので、集めたファイルは変わらない——チェックを付けたまま見る
    r = inner({"test_ok": PASSING, "test_empty": "X = 1\n"}, "-k", "test_ok")
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*テストが 1 件も無いファイルが 1 本*"])


def test_selected_run_still_fails_on_skip(inner):
    r = inner({"test_ok": PASSING, "test_skip": "import pytest\n@pytest.mark.skip\ndef test_b():\n    pass\n"}, "-k", "test_")
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*飛ばされたテストが 1 件*"])


DECLARED = "import pytest\n@pytest.mark.skipif(True, reason='SKIP process-group: POSIX の物')\ndef test_b():\n    pass\n"


def test_declared_skip_passes_only_when_its_capability_is_allowed(inner, monkeypatch):
    # 宣言つきの見送りは、能力が SKIP_ALLOW に在るときだけ許して一覧に出す。無い・別の能力・既定（空）なら今までどおり失敗
    monkeypatch.setenv("SKIP_ALLOW", "posix-mode process-group")
    r = inner({"test_ok": PASSING, "test_skip": DECLARED})
    assert r.ret == pytest.ExitCode.OK
    r.stdout.fnmatch_lines(["*見送り 1 件（SKIP_ALLOW で許した）*process-group*"])


@pytest.mark.parametrize("allow", [pytest.param("", id="default-empty"), pytest.param("fifo", id="other-capability")])
def test_declared_skip_fails_when_its_capability_is_not_allowed(inner, monkeypatch, allow):
    monkeypatch.setenv("SKIP_ALLOW", allow)
    r = inner({"test_ok": PASSING, "test_skip": DECLARED})
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*飛ばされたテストが 1 件*"])


def test_declared_xfail_is_not_allowed(inner, monkeypatch):
    # xfail は走らせて結果を見ない形なので、理由が宣言の形でも許さない
    monkeypatch.setenv("SKIP_ALLOW", "process-group")
    r = inner({"test_ok": PASSING, "test_x": "import pytest\n@pytest.mark.xfail(reason='SKIP process-group: x')\ndef test_b():\n    assert 0\n"})
    assert r.ret == pytest.ExitCode.TESTS_FAILED
