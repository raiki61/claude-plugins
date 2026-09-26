"""盤面を端から端まで回す台本（graphloops/tests/simulate.py・simulate_review.py）を pytest から回す土台。

台本の本文（Run・drive・check・代役の claude）は写さず、台本のモジュールをそのまま import して使う。pytest の側が足すのは、
loop.py をどう呼ぶか（口）だけ:

- cli: 今と同じく子プロセスで loop.py を起こす（台本の subprocess をそのまま使う）
- inproc: 台本のモジュールの ``subprocess`` の名前を ``SubprocessShim`` に差し替え、argv の頭が ``[sys.executable, loop.py]`` の
  ``subprocess.run`` だけを同じプロセスの ``loop.cli()`` に回す。台本の Run.cmd も、Run を通らない直の呼び出しも同じ 1 か所を
  通るので、台本を変えずに口だけが替わる。``Popen`` は子プロセスのまま（loop.py を Popen で起こす腕は信号を送るため）で、
  inproc の回に loop.py を Popen で起こしたら警告を出す——1 本の台本の中で 2 つの口が混ざったことを黙らせない

同じプロセスで呼ぶ口は、呼ぶたびに engine の大域の状態（``RESTORED`` の表）を呼ぶ前の値に戻す。子プロセスの口は毎回まっさらな
プロセスで始まるので、戻さないと 2 つの口が違う物を検査する。signal の口を差し替えるので、主スレッドからしか呼べない
（台本のスレッド並列 parallel.run_all とは組めない。pytest では pytest-xdist でプロセス単位に並べる）。
"""
import contextlib
import importlib
import importlib.util
import io
import json
import os
import pathlib
import re
import signal
import subprocess
import sys
import tempfile
import time
import types
import warnings

import fence
import pytest

HERE = pathlib.Path(__file__).resolve().parent
TESTS = HERE.parent
PLUGIN = TESTS.parent
LOOP = PLUGIN / "scripts" / "loop.py"
SCRIPTS = {"research": "simulate", "review": "simulate_review"}
STOP_SIGNALS = tuple(getattr(signal, n) for n in ("SIGTERM", "SIGHUP", "SIGINT") if hasattr(signal, n))

for p in (str(PLUGIN), str(TESTS)):
    if p not in sys.path:
        sys.path.insert(0, p)

from engine import role_run, rules, util  # noqa: E402

# 同じプロセスで呼ぶ口が、呼ぶたびに戻す engine の大域の状態（モジュール, 属性名）。ここに無い大域を engine に足したら、
# 2 つの口の突合（test_harness.py）がずれで赤くなるか、戻しの検査が名指しで赤くなる——足した周にこの表へ足せ
RESTORED = (
    (util, "GIT_CWD"),        # 盤面の inputs.cwd（board.py が入れる）
    (util, "LAST_DIE"),       # 最後に die した文面
    (tempfile, "tempdir"),    # 最初の mkdtemp が TMPDIR から引いて控える
)
# 中身を戻す入れ物（同じオブジェクトを engine が握っているので、差し替えずに中身を戻す）
RESTORED_CONTAINERS = (
    (role_run, "LIVE"),       # 生きている子
    (rules, "_VALIDATORS"),   # 検証器の読み込みの控え（子プロセスの口は毎回読み直す）
)

_loop = None


def loop_module():
    """loop.py を 1 度だけ読む（import の費用を呼ぶたびに払わない——子プロセスの口との差はそこにある）"""
    global _loop
    if _loop is None:
        spec = importlib.util.spec_from_file_location("graphloops_loop", LOOP)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _loop = mod
    return _loop


def snapshot():
    """戻す物の今の値（戻しの検査もこれで前後を比べる）"""
    return {
        "attrs": {(m.__name__, a): getattr(m, a) for m, a in RESTORED},
        "containers": {(m.__name__, a): _copy(getattr(m, a)) for m, a in RESTORED_CONTAINERS},
        "stopping": role_run._STOPPING.is_set(),
        "signals": {s: signal.getsignal(s) for s in STOP_SIGNALS},
        "cwd": os.getcwd(),
        "environ": dict(os.environ),
        "argv": list(sys.argv),
        "streams": (sys.stdin, sys.stdout, sys.stderr),
    }


def _copy(v):
    return dict(v) if isinstance(v, dict) else set(v)


def restore(snap):
    for m, a in RESTORED:
        setattr(m, a, snap["attrs"][(m.__name__, a)])
    for m, a in RESTORED_CONTAINERS:
        box = getattr(m, a)
        box.clear()
        box.update(snap["containers"][(m.__name__, a)])
    if snap["stopping"]:
        role_run._STOPPING.set()
    else:
        role_run._STOPPING.clear()
    for s, h in snap["signals"].items():
        signal.signal(s, h)
    os.chdir(snap["cwd"])
    os.environ.clear()
    os.environ.update(snap["environ"])
    sys.argv[:] = snap["argv"]
    sys.stdin, sys.stdout, sys.stderr = snap["streams"]


def inproc(argv, cwd=None, env=None, input=None):
    """loop.py を同じプロセスで呼ぶ。argv は loop.py の後ろの語。返りは subprocess.run と同じ形（text の CompletedProcess）。

    cwd・環境変数・標準入出力・sys.argv は呼ぶ間だけ差し替え、engine の大域と一緒に、例外の有無に依らず戻す"""
    loop = loop_module()
    snap = snapshot()
    out, err = io.StringIO(), io.StringIO()
    code = 0
    try:
        if env is not None:
            os.environ.clear()
            os.environ.update(env)
        if cwd is not None:
            os.chdir(cwd)
        sys.argv[:] = [str(LOOP), *map(str, argv)]
        data = (input or "").encode("utf-8") if not isinstance(input, bytes) else input
        sys.stdin = io.TextIOWrapper(io.BytesIO(data), encoding="utf-8")
        sys.stdout, sys.stderr = out, err
        try:
            loop.cli()
        except SystemExit as e:   # 子プロセスの終了コードと同じ直し方（None は 0、整数でない値は文面を出して 1）
            if e.code is None:
                code = 0
            elif isinstance(e.code, int):
                code = e.code
            else:
                print(e.code, file=err)
                code = 1
    finally:
        restore(snap)
    return subprocess.CompletedProcess([sys.executable, str(LOOP), *argv], code, out.getvalue(), err.getvalue())


def _is_loop(args):
    return (isinstance(args, (list, tuple)) and len(args) >= 2
            and os.path.realpath(str(args[1])) == os.path.realpath(str(LOOP))
            and os.path.realpath(str(args[0])) == os.path.realpath(sys.executable))


class SubprocessShim:
    """台本のモジュールの ``subprocess`` の代わり。loop.py を起こす ``run`` だけを inproc に回し、ほかは本物へ渡す"""

    def __init__(self):
        self.inproc_calls = 0

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def run(self, args, *, cwd=None, env=None, input=None, capture_output=False, text=None, encoding=None, check=False,
            stdout=None, stderr=None, **kw):
        if not _is_loop(args):
            return subprocess.run(args, cwd=cwd, env=env, input=input, capture_output=capture_output, text=text,
                                  encoding=encoding, check=check, stdout=stdout, stderr=stderr, **kw)
        # 台本が渡す timeout は、同じプロセスでは止める先の子が無いので効かない——受けて捨てる
        kw.pop("timeout", None)
        if kw or {stdout, stderr} - {None, subprocess.PIPE, subprocess.STDOUT}:
            raise TypeError(f"inproc の口が受けない呼び方: {sorted(kw)} stdout={stdout} stderr={stderr}")
        self.inproc_calls += 1
        r = inproc(args[2:], cwd=cwd, env=env, input=input)
        out, err = r.stdout, r.stderr
        if stderr == subprocess.STDOUT:
            out, err = out + err, ""
        # 受けない側（capture_output も PIPE も無い）は子プロセスの口と同じく、そのまま流して None を返す
        if not (capture_output or stdout == subprocess.PIPE):
            sys.stdout.write(out)
            out = None
        if not (capture_output or stderr == subprocess.PIPE):
            sys.stderr.write(err)
            err = None
        if not (text or encoding):   # バイトで受ける呼び方なら、子プロセスの口と同じくバイトで返す
            out, err = (None if x is None else x.encode("utf-8") for x in (out, err))
        got = subprocess.CompletedProcess(r.args, r.returncode, out, err)
        if check:
            got.check_returncode()
        return got

    def Popen(self, args, *a, **kw):
        if _is_loop(args):
            warnings.warn("inproc の口: loop.py を Popen で起こす呼び出しは子プロセスのまま走る（信号を送る腕のため）", stacklevel=2)
        return subprocess.Popen(args, *a, **kw)


def script(kind):
    """台本のモジュール（kind は research か review）"""
    return importlib.import_module(SCRIPTS[kind])


@contextlib.contextmanager
def driven(mod, driver):
    """台本のモジュールを、その口で使う間だけ差し替える（cli は何もしない）"""
    if driver not in ("cli", "inproc"):
        raise ValueError(f"口は cli か inproc: {driver}")
    if driver == "cli":
        yield mod
        return
    saved = mod.subprocess
    mod.subprocess = SubprocessShim()
    try:
        yield mod
    finally:
        mod.subprocess = saved


# ---- 盤面の突合 ------------------------------------------------------------------------------------------------------

BOARD_FILES = ("state.json", "record.json")
ISO_TIME = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")
RUN_ID = re.compile(r"\b\d{8}-\d{6}\b")
# 置き換えた根の後ろのパスの区切り（Windows の \ と、JSON の文字列に埋めた \\）を / にそろえる——根の綴りだけ置き換えると、
# 同じ盤面が OS で <root0>/repo と <root0>\repo に割れる（実測 2026-09-26: windows-latest）
ROOT_TAIL = re.compile(r"(<root\d+>)((?:(?:\\\\|\\|/)[^\\/\s\"'<>]+)+)")
# 呼ぶたびに変わる数値の欄（所要）と、文の中の所要（走らせた段の「（0.3 秒）」）。名前で名指しし、欄を黙って広げない
DURATION_KEYS = re.compile(r"(?:^|_)(?:elapsed|elapsed_min|wall_s|duration_ms|duration_api_ms)$")
DURATION_TEXT = re.compile(r"（\d+(?:\.\d+)? 秒）")
# 本文に作業場のパスを含む物の要約（プロンプトの本文は作業場のパスを貼るので、根を置き換えても要約は口ごとに違う）
PATH_HASHED_KEYS = ("prompt_sha",)


def board_files(d):
    d = pathlib.Path(d)
    files = [d / f for f in BOARD_FILES] + sorted((d / "rounds").glob("round-*.json"))
    return {f.relative_to(d).as_posix(): f for f in files if f.is_file()}


def normalize_board(d, roots):
    """盤面（state.json・record.json・周の記録）を読み、run の番号・時刻・作業場の根のパス・所要を置き換えた dict を返す"""
    subs = []
    for i, r in enumerate(roots):
        for form in {str(r), os.path.realpath(str(r))}:
            subs.append((form, f"<root{i}>"))
            esc = json.dumps(form)[1:-1]   # JSON の文字列に埋めた綴り（Windows では \ が 2 つずつ。任せ先の sandbox の設定の引数など）
            if esc != form:
                subs.append((esc, f"<root{i}>"))
    subs.sort(key=lambda x: -len(x[0]))   # 長い綴りから（realpath の /private/var が /var の置き換えで崩れない）

    def text(s):
        for a, b in subs:
            s = s.replace(a, b)
        s = ROOT_TAIL.sub(lambda m: m.group(1) + re.sub(r"\\\\|\\", "/", m.group(2)), s)
        return DURATION_TEXT.sub("（<dur> 秒）", RUN_ID.sub("<run_id>", ISO_TIME.sub("<time>", s)))

    def walk(v, key=""):
        if isinstance(v, dict):
            return {text(k): walk(x, k) for k, x in v.items()}
        if isinstance(v, list):
            return [walk(x, key) for x in v]
        if isinstance(v, str):
            return "<sha>" if key in PATH_HASHED_KEYS else text(v)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and DURATION_KEYS.search(key or ""):
            return "<dur>"
        return v

    return {name: walk(json.loads(f.read_text(encoding="utf-8"))) for name, f in board_files(d).items()}


def first_difference(a, b, path="$"):
    """2 つの正規化した盤面の最初の食い違い（無ければ None）——赤のときに何がずれたかを 1 行で言う"""
    if type(a) is not type(b):
        return f"{path}: {type(a).__name__} と {type(b).__name__}"
    if isinstance(a, dict):
        for k in sorted(set(a) | set(b)):
            if k not in a or k not in b:
                return f"{path}.{k}: 片方にだけ在る"
            got = first_difference(a[k], b[k], f"{path}.{k}")
            if got:
                return got
        return None
    if isinstance(a, list):
        if len(a) != len(b):
            return f"{path}: 長さ {len(a)} と {len(b)}"
        for i, (x, y) in enumerate(zip(a, b)):
            got = first_difference(x, y, f"{path}[{i}]")
            if got:
                return got
        return None
    return None if a == b else f"{path}: {str(a)[:120]!r} と {str(b)[:120]!r}"


# ---- 検査の集め役 ----------------------------------------------------------------------------------------------------

def tallies():
    """読み込まれている台本のモジュールごとの（検査の件数, 失敗の数）。行を出すのも数えるのも台本の check が正本で、
    pytest の側はその前後の差を読むだけ（行の形を写さない）"""
    got = {}
    for name in SCRIPTS.values():
        mod = sys.modules.get(name)
        if mod is not None:
            got[name] = (mod.ran, len(mod.fails))
    return got


def new_results(before, after):
    """前後の tallies から、この間に走った検査の件数と、増えた失敗の文面"""
    ran, failed = 0, []
    for name, (r1, f1) in after.items():
        r0, f0 = before.get(name, (0, 0))   # この間に初めて読まれたモジュールは 0 から数える
        ran += r1 - r0
        failed += sys.modules[name].fails[f0:f1]
    return ran, failed


# ---- pytest の口（conftest.py が pytest_plugins で載せる） -------------------------------------------------------------

SIZES = {
    "small": "子プロセス・スリープを使わない（使えば失敗）",
    "medium": "子プロセス・git・盤面を端から端まで回す（手で撃つ mutmut の選ぶテストから外す——graphloops/setup.cfg）",
}


def pytest_addoption(parser):
    parser.addoption("--gl-driver", choices=("cli", "inproc"), default="cli",
                     help="盤面を回す台本が loop.py を呼ぶ口（cli: 子プロセス／inproc: 同じプロセス）。既定は cli")


def pytest_configure(config):
    for name, why in SIZES.items():
        config.addinivalue_line("markers", f"{name}: {why}")


SMALL_CALLS = pytest.StashKey[list]()


@pytest.hookimpl(wrapper=True)
def pytest_runtest_call(item):
    """台本の check の前後の差を数える。件数は柵へ、失敗は GL_CHECK_LOG へ 1 行ずつ書き、1 件でもあればテストを失敗にする
    （check は失敗を溜めて進む形なので、数えないと pytest は緑と報告する）。small のテストが禁じた物を呼んでいれば、
    例外を握り潰していても失敗にする"""
    before = tallies()
    failed = []
    try:
        res = yield
    finally:   # テストが例外で抜けても、そこまでに走った件数と失敗は数える
        ran, failed = new_results(before, tallies())
        fence.add_sim_checks(item.config, ran)
        log = os.environ.get("GL_CHECK_LOG")
        if failed and log:
            with open(log, "a", encoding="utf-8") as f:
                f.writelines(f"  FAIL {d}\n" for d in failed)
    if failed:
        pytest.fail(f"台本の検査が {len(failed)} 件落ちた: " + " / ".join(failed[:5]), pytrace=False)
    calls = item.stash.get(SMALL_CALLS, None)
    if calls:
        pytest.fail(f"small のテストが {', '.join(sorted(set(calls)))} を呼んだ（大きさの柵）", pytrace=False)
    return res


@pytest.fixture(autouse=True)
def _size_fence(request, monkeypatch):
    """small の印のテストで子プロセスとスリープを禁じる（呼んだら例外で止め、握り潰されても pytest_runtest_call が失敗にする）"""
    if request.node.get_closest_marker("small") is None:
        return
    calls = request.node.stash.setdefault(SMALL_CALLS, [])

    def refuse(what):
        def stop(*a, **kw):
            calls.append(what)
            raise AssertionError(f"small のテストが {what} を呼んだ")
        return stop
    monkeypatch.setattr(subprocess, "Popen", refuse("subprocess.Popen"))
    monkeypatch.setattr(time, "sleep", refuse("time.sleep"))


@pytest.fixture
def gl_tmp(tmp_path, monkeypatch):
    """一時の置き場を tmp_path に向ける——台本の作業場（parallel.workspace）・engine の置き場（mkdtemp）・子プロセスの口の子・
    消す口（parallel.rm の基点）が、同じ 1 つのつまみ（TMPDIR）で同じ所を見る。後始末は tmp_path に任せる"""
    monkeypatch.setenv("TMPDIR", str(tmp_path))
    monkeypatch.setattr(tempfile, "tempdir", None)
    return tmp_path


@pytest.fixture
def gl_check(request):
    """台本と同じ check・skip（行の形と数え方の正本は台本の側）と、到達を記す reach"""
    mod = script("review")
    return types.SimpleNamespace(check=mod.check, skip=mod.skip, reach=lambda v: fence.reach(request.config, v))


@pytest.fixture
def gl_script(request, gl_tmp, gl_check):
    """台本のモジュールを --gl-driver の口で使えるようにして返す（gl_script("review") のように呼ぶ）。台本は変えない"""
    driver = request.config.getoption("--gl-driver")
    with contextlib.ExitStack() as stack:
        def use(kind):
            gl_check.reach(f"driver:{driver}")
            return stack.enter_context(driven(script(kind), driver))
        yield use


@pytest.fixture
def gl_run(gl_script):
    """台本の Run を作る工場: gl_run("review", "名前", **Run の引数)"""
    return lambda kind, name, **kw: gl_script(kind).Run(name, **kw)


@pytest.fixture
def fake_claude(tmp_path):
    """代役の claude を置き、PATH の先頭に足した環境を返す（振る舞いは tests/fakeclaude.py の環境変数で選ぶ）"""
    import fakeclaude
    bindir = tmp_path / "fake-bin"
    bindir.mkdir()
    fakeclaude.install(bindir)
    return {**os.environ, "PATH": str(bindir) + os.pathsep + os.environ.get("PATH", "")}
