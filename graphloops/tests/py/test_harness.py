"""盤面を回す台本を pytest から回す土台（glharness.py・fence.py の 3）の検査。

- 2 つの口の突合: 同じ筋書きを子プロセスの口と同じプロセスの口で回し、盤面を正規化して突き合わせる（上位互換の確かめ）
- 同じプロセスの口の戻し・終了コードと標準エラーの一致
- 台本の本文をそのまま pytest から回せること（件数と失敗が pytest の結果と柵に届く）
- 柵が pytest-xdist（-n）の下でも赤になること（内側に回した pytest で見る。赤を見ていない柵は効いていると扱わない）
"""
import json
import os
import pathlib
import signal
import subprocess
import sys
import tempfile
import time

import glharness
import pytest

HERE = pathlib.Path(__file__).resolve().parent
REVIEW_VALIDATOR = glharness.PLUGIN.parent / "scripts" / "review-record.py"
FIXED_GIT_DATE = "2026-01-01T00:00:00+0000"   # 2 つの口で commit の sha を揃える（盤面は base の sha を持つ）

# (台本, 筋書き, Run の引数, drive の hook, 終わりの status)。review は 3 周で収束する標準、research は 1 周で打ち切る軽量
# （research の標準は抜き取りの項目を run の番号から引くので、run の番号が違う 2 回では盤面が揃わない）
SCENARIOS = {
    "review-std": ("review", "std", {}, None, "converged"),
    "research-light": ("research", "light", {"thickness": "軽量", "decider": "依頼者指定"},
                       lambda run, inst, out: ({**out, "thickness": "軽量", "thickness_decider": "依頼者指定"}
                                               if inst["node"] == "p0.question" else out), "stopped"),
}


@pytest.mark.medium
@pytest.mark.parametrize("name", sorted(SCENARIOS))
def test_drivers_agree(name, gl_tmp, gl_check, monkeypatch, record_property):
    kind, scenario, run_kw, hook, want = SCENARIOS[name]
    for k in ("GIT_AUTHOR_DATE", "GIT_COMMITTER_DATE"):
        monkeypatch.setenv(k, FIXED_GIT_DATE)
    mod = glharness.script(kind)
    boards, secs = {}, {}
    for driver in ("cli", "inproc"):
        gl_check.reach(f"driver:{driver}")
        with glharness.driven(mod, driver):
            t = time.monotonic()
            run = mod.Run("drivers", **run_kw)   # 同じ名前（作業場とプロンプトの長さを揃える）
            last = mod.drive(run, scenario, hook=hook)
            secs[driver] = round(time.monotonic() - t, 1)
        assert last["status"] == want, f"{driver}: {last['status']}"
        boards[driver] = glharness.normalize_board(run.dir, [run.tmp])
    assert set(boards["cli"]) >= {"state.json", "record.json"}   # 周の記録は周を締めた筋書き（review）だけに在る
    record_property("seconds", secs)   # 所要は測るだけ（大きさごとの上限は置かない）
    print(f"所要（秒）: {secs}")
    assert boards["cli"] == boards["inproc"], glharness.first_difference(boards["cli"], boards["inproc"])


def _git_repo(tmp):
    repo = tmp / "repo"
    repo.mkdir()
    for args in (["init", "-q"], ["-c", "user.email=t@t", "-c", "user.name=t", "commit", "-q", "--allow-empty", "-m", "init"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True)
    return repo


def _init_args(d):
    return ["init", "--loop", "review-loop", "--request", "x", "--dir", str(d), "--validator", str(REVIEW_VALIDATOR)]


def _plant(tmp, sentinel):
    """戻るべき目印を置く（表 RESTORED を読まずに名指しで置く——表から項を落とした退行を、表で比べる検査は見ない）"""
    glharness.util.GIT_CWD = "sentinel-cwd"
    glharness.util.LAST_DIE = "sentinel-die"
    glharness.role_run.LIVE.clear()
    glharness.role_run.LIVE.add("sentinel-child")
    glharness.rules._VALIDATORS.clear()
    glharness.rules._VALIDATORS["sentinel"] = "v"
    glharness.role_run._STOPPING.clear()
    tempfile.tempdir = str(tmp)
    for s in glharness.STOP_SIGNALS:
        signal.signal(s, sentinel)


def _assert_planted(tmp, sentinel, cwd, environ, argv, streams):
    assert glharness.util.GIT_CWD == "sentinel-cwd" and glharness.util.LAST_DIE == "sentinel-die"
    assert glharness.role_run.LIVE == {"sentinel-child"} and glharness.rules._VALIDATORS == {"sentinel": "v"}
    assert not glharness.role_run._STOPPING.is_set() and tempfile.tempdir == str(tmp)
    assert all(signal.getsignal(s) is sentinel for s in glharness.STOP_SIGNALS)
    now = {k: v for k, v in os.environ.items() if k != "PYTEST_CURRENT_TEST"}   # pytest が段ごとに書き換える 1 つを除く
    assert os.getcwd() == cwd and now == {k: v for k, v in environ.items() if k != "PYTEST_CURRENT_TEST"} and sys.argv == argv
    assert (sys.stdin, sys.stdout, sys.stderr) == streams


@pytest.fixture
def planted(gl_tmp):
    """目印を置き、テストの後で engine の大域を元に戻す"""
    saved = glharness.snapshot()
    sentinel = lambda *a: None
    _plant(gl_tmp, sentinel)
    yield lambda: _assert_planted(gl_tmp, sentinel, saved["cwd"], saved["environ"], saved["argv"], saved["streams"])
    glharness.restore(saved)


def test_inproc_isolates_the_call(planted, gl_tmp, monkeypatch):
    """呼ぶ間だけ argv・cwd・環境変数・標準入力が渡した物になり、engine の大域を書き換えられても戻る（代役の loop で見る）"""
    seen = {}

    class Loop:
        @staticmethod
        def cli():
            seen.update(argv=list(sys.argv), cwd=os.getcwd(), env=dict(os.environ), stdin=sys.stdin.read())
            glharness.util.GIT_CWD, glharness.util.LAST_DIE = "x", "y"
            glharness.role_run.LIVE.add("child")
            glharness.rules._VALIDATORS["p"] = "m"
            glharness.role_run._STOPPING.set()
            tempfile.tempdir = "/elsewhere"
            os.chdir("/")
            os.environ["LEAK"] = "1"
            for s in glharness.STOP_SIGNALS:
                signal.signal(s, signal.SIG_DFL)
            print("out")
            print("err", file=sys.stderr)
            raise SystemExit(3)
    monkeypatch.setattr(glharness, "_loop", Loop)
    r = glharness.inproc(["next", "--dir", "d"], cwd=gl_tmp, env={"ONLY": "1"}, input="材料")
    assert (r.returncode, r.stdout, r.stderr) == (3, "out\n", "err\n")
    assert seen["argv"] == [str(glharness.LOOP), "next", "--dir", "d"]
    assert seen["env"] == {"ONLY": "1"} and os.path.realpath(seen["cwd"]) == os.path.realpath(gl_tmp) and seen["stdin"] == "材料"
    planted()


@pytest.mark.medium
def test_inproc_restores_globals(planted, gl_tmp):
    """本物の engine を成功・拒否・盤面が読めない の 3 つの終わり方で呼んでも、置いた目印が戻る"""
    repo = _git_repo(gl_tmp)
    d = gl_tmp / "state"
    for argv, want in [(_init_args(d), 0), (["next", "--dir", str(d)], 0),
                       (["done", "--node", "no-such-node", "--output", os.devnull, "--dir", str(d)], 1),
                       (["status", "--dir", str(gl_tmp / "no-board")], 2)]:
        r = glharness.inproc(argv, cwd=repo, env={**os.environ, "GL_ONLY_INSIDE": "1"})
        assert r.returncode == want, (argv, r.stderr)
        planted()
    # 空振りの戻しで緑にしない: 戻さずに呼べば、engine は GIT_CWD と signal の口を実際に書き換える
    saved_argv = sys.argv[:]
    sys.argv[:] = [str(glharness.LOOP), "status", "--dir", str(d)]
    try:
        glharness.loop_module().cli()
    finally:
        sys.argv[:] = saved_argv
    assert glharness.util.GIT_CWD == str(repo)
    assert all(signal.getsignal(s) is not signal.SIG_DFL and signal.getsignal(s).__name__ == "stop" for s in glharness.STOP_SIGNALS)


@pytest.mark.medium
def test_drivers_same_exit_and_stderr(gl_tmp):
    """拒否・盤面が読めない・引数の誤りで、2 つの口の終了コードと標準エラーが同じ"""
    repo = _git_repo(gl_tmp)
    d = gl_tmp / "state"
    assert glharness.inproc(_init_args(d), cwd=repo).returncode == 0
    for argv in (["done", "--node", "no-such-node", "--output", os.devnull, "--dir", str(d)],
                 ["status", "--dir", str(gl_tmp / "no-board")],
                 ["no-such-command"]):
        cli = subprocess.run([sys.executable, str(glharness.LOOP), *argv], cwd=repo, capture_output=True, text=True,
                             encoding="utf-8")
        inp = glharness.inproc(argv, cwd=repo)
        assert (inp.returncode, inp.stderr) == (cli.returncode, cli.stderr), argv
        assert cli.returncode != 0


@pytest.mark.medium
def test_script_body_runs_under_driver(gl_script):
    """台本の本文（simulate_review.py の test_premise）を変えずに pytest から回す——件数と失敗は柵と pytest の結果に届く"""
    gl_script("review").test_premise()


@pytest.mark.medium
def test_shim_passes_other_commands_through():
    shim = glharness.SubprocessShim()
    r = shim.run([sys.executable, "-c", "print('x')"], capture_output=True, text=True)
    assert r.stdout == "x\n" and shim.inproc_calls == 0


@pytest.mark.small
def test_normalize_board_replaces_only_named_parts(tmp_path):
    root = tmp_path / "ws"
    board = root / "state"
    (board / "rounds").mkdir(parents=True)
    state = {"run_id": "20260926-081500", "at": "2026-09-26T08:15:00+09:00", "path": str(root / "repo"),
             "wall_s": 1.5, "count": 3, "note": "suite: exit 0（0.3 秒）", "prompt_sha": "abc123", "sha": "def456"}
    (board / "state.json").write_text(json.dumps(state), encoding="utf-8")
    (board / "rounds" / "round-1.json").write_text(json.dumps({"n": 1}), encoding="utf-8")
    got = glharness.normalize_board(board, [root])
    assert got["state.json"] == {"run_id": "<run_id>", "at": "<time>", "path": "<root0>/repo", "wall_s": "<dur>", "count": 3,
                                 "note": "suite: exit 0（<dur> 秒）", "prompt_sha": "<sha>", "sha": "def456"}
    assert set(got) == {"state.json", "rounds/round-1.json"}
    other = json.loads(json.dumps(got))
    other["state.json"]["count"] = 4
    assert glharness.first_difference(got, other) == "$.state.json.count: '3' と '4'"


# ---- 内側に回した pytest で柵の赤を見る ---------------------------------------------------------------------------------

CONFTEST = ("import fence, pathlib\n"
            "pytest_plugins = ('glharness',)\n\n\n"
            "def pytest_configure(config):\n"
            "    fence.install(config, pathlib.Path(__file__).parent, {items})\n"
            "    fence.expect_sim(config, {checks}, {reached})\n")
PASSING = "def test_a():\n    pass\n"
def checks_file(n, reach="r"):
    body = "import glharness\nsim = glharness.script('review')\n\n\ndef test_c(gl_check):\n"
    body += f"    gl_check.reach({reach!r})\n"
    body += "".join(f"    sim.check(True, 'c{i}')\n" for i in range(n))
    return body


@pytest.fixture
def inner(pytester, monkeypatch, tmp_path):
    """内側の pytest を別のプロセスで回す（-n の worker も、台本のモジュールの件数も外側と混ざらない）"""
    monkeypatch.setenv("PYTHONPATH", os.pathsep.join([str(HERE), os.environ.get("PYTHONPATH", "")]))
    monkeypatch.delenv("PYTEST_ADDOPTS", raising=False)

    def run(files, items, *args, checks=0, reached=0):
        pytester.makeconftest(CONFTEST.format(items=items, checks=checks, reached=reached))
        pytester.makepyfile(**files)
        return pytester.runpytest_subprocess("-p", "no:cacheprovider", *args)
    return run


@pytest.mark.medium
@pytest.mark.parametrize("n", ["0", "2"], ids=["serial", "xdist"])
def test_emptied_file_is_red_under_xdist(inner, n):
    """テストを全部消したファイルは -n の下でも全件の回として赤（worker の node id の一覧には現れないファイル）"""
    r = inner({"test_ok": PASSING, "test_two": PASSING, "test_empty": "X = 1\n"}, 3, "-n", n)
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*集めたテストが 2 件（3 件を期待）*"])


@pytest.mark.medium
@pytest.mark.parametrize("expected", [1, 3])
def test_count_mismatch_is_red_under_xdist(inner, expected):
    r = inner({"test_ok": PASSING, "test_two": PASSING}, expected, "-n", "2")
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines([f"*集めたテストが 2 件（{expected} 件を期待）*"])


@pytest.mark.medium
def test_skip_is_red_under_xdist(inner):
    r = inner({"test_ok": PASSING, "test_skip": "import pytest\n@pytest.mark.skip\ndef test_b():\n    pass\n"}, 2, "-n", "2")
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*飛ばされたテストが 1 件*"])


@pytest.mark.medium
@pytest.mark.parametrize("n", ["0", "2"], ids=["serial", "xdist"])
def test_sim_fences_match_and_break(inner, n):
    """台本の検査の件数と到達: 合っていれば緑、検査を 1 件消せば赤、到達を 1 つ減らせば赤（-n の下では worker をまたいで足す）"""
    files = {"test_x": checks_file(2, "a"), "test_y": checks_file(3, "b")}
    assert inner(files, 2, "-n", n, checks=5, reached=2).ret == pytest.ExitCode.OK
    r = inner({"test_x": checks_file(2, "a"), "test_y": checks_file(2, "b")}, 2, "-n", n, checks=5, reached=2)
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*台本の検査が 4 件走った（5 件を期待）*"])
    r = inner({"test_x": checks_file(2, "a"), "test_y": checks_file(3, "a")}, 2, "-n", n, checks=5, reached=2)
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*到達した値が 1 個（2 個を期待）*"])


@pytest.mark.medium
def test_sim_fences_drop_on_deselect(inner):
    r = inner({"test_x": checks_file(2, "a"), "test_y": checks_file(3, "b")}, 2, "-n", "2", "-k", "test_x", checks=5, reached=2)
    assert r.ret == pytest.ExitCode.OK
    r.stdout.fnmatch_lines(["*検査の件数の柵と到達の柵を外した（1 件のテストを選び外した）*"])


@pytest.mark.medium
def test_failed_check_fails_the_test_and_logs(inner, tmp_path, monkeypatch):
    log = tmp_path / "checks.log"
    monkeypatch.setenv("GL_CHECK_LOG", str(log))
    body = checks_file(1, "a") + "    sim.check(False, 'わざと落とす')\n"
    r = inner({"test_x": body}, 1, checks=2, reached=1)
    assert r.ret == pytest.ExitCode.TESTS_FAILED
    r.stdout.fnmatch_lines(["*台本の検査が 1 件落ちた: わざと落とす*", "*  FAIL わざと落とす*"])
    assert log.read_text(encoding="utf-8") == "  FAIL わざと落とす\n"


@pytest.mark.medium
def test_small_marker_refuses_children_and_sleep(inner):
    files = {"test_s": ("import subprocess, sys, time, pytest\n\n\n"
                        "@pytest.mark.small\ndef test_child():\n    subprocess.run([sys.executable, '-c', 'pass'])\n\n\n"
                        "@pytest.mark.small\ndef test_sleep():\n    time.sleep(0)\n\n\n"
                        "@pytest.mark.small\ndef test_swallowed():\n    try:\n        time.sleep(0)\n    except BaseException:\n        pass\n\n\n"
                        "def test_unmarked():\n    subprocess.run([sys.executable, '-c', 'pass'])\n    time.sleep(0)\n")}
    r = inner(files, 4)
    r.assert_outcomes(passed=1, failed=3)
    r.stdout.fnmatch_lines(["*small のテストが time.sleep を呼んだ（大きさの柵）*"])


RMTREE_ROOTS = ("graphloops", "tests", "scripts")   # リポジトリの根から見た、消す口の柵が走査する置き場
# 消す口に届いてよい所の表: (根から見たファイル, 最上位の関数) → (その関数の中の参照の数, 許す理由)。数が合わなければ赤——
# 関数の中に消す口が増えた・名前が変わって見つからない（並行の run が熱いファイルの関数を改名した）のどちらも黙って緩まない
RMTREE_ALLOWED = {
    ("graphloops/tests/parallel.py", "rm"): (1, "範囲の守り（gettempdir より深い所だけを消す）を持つ台本の正本"),
    ("graphloops/tests/py/test_harness.py", "_rmtree_refs"): (5, "名前への参照を探すこの柵の本体"),
    ("graphloops/engine/commands.py", "launch_one"): (3, "同じ関数が mkdtemp で作った任せ先の作業場"),
    ("graphloops/engine/commands.py", "cmd_init"): (1, "同じ関数が exist_ok=False で作ったばかりの盤面（rules の入口が拒んだ回）"),
    ("graphloops/rules/review-loop.py", "_worktree_tree"): (1, "同じ関数が mkdtemp で作った一時の置き場"),
    ("tests/catchup-switch-case.py", "_worktree"): (1, "TemporaryDirectory の下に同じ関数が足した worktree"),
    # 変異の実行器の作業場（scratch_dir の mkdtemp と呼び元の finally）。作業場の作り替えは別の run の持ち分で、ここでは
    # 表に載せるだけ（作り替えたらこの 3 行を消す）
    ("tests/mutate.py", "one"): (1, "同じ関数が copy（scratch_dir の mkdtemp）で作った腕の作業場"),
    ("tests/mutate.py", "control"): (1, "同じ関数が copy で作った作業場"),
    ("tests/mutate.py", "marker_run"): (1, "同じ関数が copy で作った作業場"),
}


def _rmtree_refs(root):
    """根の下の RMTREE_ROOTS を再帰で読み、rmtree への参照を数える ——({(ファイル, 最上位の関数か None): 数}, 読んだ本数の置き場ごと)。
    呼び出しの形に依らず名前への参照で見る（別名の import・関数を値で渡す形・getattr の文字列も拾う）。シェルの台本（*.sh）は
    ast にかけられないので、埋め込んだ Python ごと字列で拾う（関数は None）"""
    import ast
    import collections
    counts, scanned = collections.Counter(), collections.Counter()
    for top in RMTREE_ROOTS:
        for path in sorted((root / top).rglob("*.py")) + sorted((root / top).rglob("*.sh")):
            if "__pycache__" in path.parts:
                continue
            rel, text = path.relative_to(root).as_posix(), path.read_text(encoding="utf-8")
            scanned[top] += 1
            if path.suffix == ".sh":
                counts[(rel, None)] += text.count("rmtree")
                continue
            tree = ast.parse(text)
            owner = {id(x): f.name for f in tree.body if isinstance(f, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
                     for x in ast.walk(f)}
            for n in ast.walk(tree):
                if ((isinstance(n, ast.Attribute) and n.attr == "rmtree") or (isinstance(n, ast.Name) and n.id == "rmtree")
                        or (isinstance(n, ast.alias) and n.name == "rmtree") or (isinstance(n, ast.Constant) and n.value == "rmtree")):
                    counts[(rel, owner.get(id(n)))] += 1
    return +counts, scanned


def _rmtree_violations(counts, allowed):
    """表と数が合わない所: 表に無い参照・表の関数の中で数が違う・表に在るのに見つからない（名前のずれ）"""
    return sorted(f"{rel}:{fn}: 参照 {counts.get((rel, fn), 0)} 件（表は {allowed.get((rel, fn), (0,))[0]} 件）"
                  for rel, fn in set(counts) | set(allowed) if counts.get((rel, fn), 0) != allowed.get((rel, fn), (0,))[0])


def test_rmtree_is_reached_only_from_named_sites():
    """消す口（rmtree）に届いてよいのは、範囲の守りを持つ台本の正本と、同じ関数の中で自分が作った物を消す名指しの所だけ。
    graphloops・tests・scripts の全部を見る——0.21.0 の事故（既定値から計算した親を消した）の層だけに柵を立てると、
    新しい消す口が守りを素通りする"""
    counts, scanned = _rmtree_refs(glharness.PLUGIN.parent)
    assert all(scanned[top] for top in RMTREE_ROOTS), f"走査した本数が 0 の置き場がある（根の計算がずれた）: {dict(scanned)}"
    assert _rmtree_violations(counts, RMTREE_ALLOWED) == []


@pytest.mark.parametrize("top,rel,body", [
    pytest.param("graphloops", "graphloops/engine/x.py", "import shutil\n\ndef f(p):\n    shutil.rmtree(p)\n", id="engine"),
    pytest.param("tests", "tests/x.py", "from shutil import rmtree as r\n", id="tests-alias"),
    pytest.param("scripts", "scripts/x.py", "import shutil\nf = getattr(shutil, 'rmtree')\n", id="scripts-getattr"),
    pytest.param("tests", "tests/x.sh", "python3 -c 'import shutil; shutil.rmtree(\"/\")'\n", id="shell-embedded"),
    pytest.param("graphloops", "graphloops/engine/commands.py", "import shutil\n\ndef renamed(w):\n    shutil.rmtree(w)\n", id="renamed-allowed-function"),
])
def test_rmtree_fence_is_red_in_each_root(tmp_path, top, rel, body):
    """広げた置き場ごとに、表に無い消す口を 1 つ置くと赤になる（名前が変わって表の関数が見つからない形も）"""
    for t in RMTREE_ROOTS:
        (tmp_path / t).mkdir()
    (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / rel).write_text(body, encoding="utf-8")
    counts, _ = _rmtree_refs(tmp_path)
    assert _rmtree_violations(counts, {("graphloops/engine/commands.py", "launch_one"): (1, "x")})

