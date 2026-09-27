"""台本を消す条件の 4（被覆。規範は docs/adr/0067）を測る道具と、層 2 の効き目（所要・子の数）と元の関数の順の突き合わせを撃つ道具。

名乗るのは**実行の包含**だけ——台本の関数が通した行を、移した先のテストの和も通したか。移した述語の強さ（行を通した上で
期待が壊れを見分けるか）は被覆では言えない（Google Testing Blog の被覆の心得）。強さは変異の腕（消す条件の 2・3）が示す。

撃つのは CI の job（.github/workflows/cover-moved.yml。手で起こす）。移した台本の関数を 1 回ずつ回すので重く、pytest の一式には
入れない。手元では --no-cov で関数を名指しして数件だけ回す（人の方針）:

    COVERAGE_CORE=ctrace python graphloops/tests/py/cover_moved.py [--out <結果の JSON>]                     # 被覆の包含
    python graphloops/tests/py/cover_moved.py --no-cov [--driver inproc|cli] [--only <台本>.<関数>,...] [--out …]   # 所要・子・盤面

旧い側も新しい側も、撃つたびにこの回の一時の置き場で測る——前の回の測りを使い回さない（台本や engine が動いた版の行と今の
新しい側を比べると、行番号のずれた比べが偶然重なって緑になりうる）。台本→移し先の対応は印 moved_from 1 つから引く
（ledger.collect が置き場を全部集めた印）。

- **旧い側**: 印が名乗る台本の関数を 1 本ずつ、glharness.driven(台本, "inproc") の下でこのプロセスで回して測る——loop.py は
  同じプロセスの loop.cli() に回るので、子プロセスを測る設定（coverage の patch = subprocess）なしで engine の行が数えられる。
  cli の口のまま測ると旧い側が同じプロセスで呼ぶ部品の行だけになり、包含が恒真になる。台本と engine の import の行は印を集める段で
  済んでいるので、旧い側に入らない
- **新しい側**: 印を持つファイルを pytest-cov の --cov-context=test で測る。文脈は node id と段（setup・run・teardown）。
  --gl-prebuild-waves で T1 の波と層 2 の前置き（given）を最初のテストの setup に作らせ、各行の when は検査の本体（run）で打つ
- **前置きの作り**: T1 の波（wave:<名前>）と層 2 の列の接頭辞（given:<列>@<位置>）を、このプロセスで 1 つずつ作って文脈を分けて測る。
  テストが使った物は fixture が user_properties に積み（積んだテストの node id も）、--junitxml で読む
- **台本ごと（per_script）**: 新しい側は、その台本を名乗る node id の run の文脈・読み込みの行（文脈が空）・使った前置きの作り（setup と
  して数える）だけを数える（全部の前置きを全部の台本に渡すと、別の台本の前置きが通した行で『含まれる』と出る）。読み込みの行を全部の
  台本に渡すのは、旧い側が同じプロセスで台本を順に回すので、遅れて読む engine の import の行が最初に回した台本の文脈にだけ入るから
- **ファイルの鍵**: graphloops/ から始まる綴りで比べる（測った一時の置き場の綴りに依らず同じファイルが当たる）
- **計測器**: Python 3.14 の既定（sysmon）は動的な文脈を持たない（coverage の config の文書）ので ctrace に固定し、固定できたかを確かめる
- **縮退の見張り**: 旧い側の engine の行が 0 なら赤。新しいテストのうち、旧い側の行をそれだけが覆うテストが 0 なら赤（包含が新しい
  検査の中身に依らず成り立つ疑い）。名乗る node id が新しい側の run の文脈に 1 つも無い台本も赤（node id の綴りか測りの取り違え）
- 測る行: graphloops/engine・graphloops/rules・graphloops/scripts（loop.py ほか）。台本とテストの本文は数えない

--no-cov の回（被覆なし）は台本ごとに、旧い側（名指した関数）と層 2 の側（その台本の行が使う列を端まで 1 度ずつ作る）の所要と、
子プロセスの数を数える。数え方は Python の監査イベント subprocess.Popen（sys.addaudithook）で、頭の語で git・python・その他に分ける。
監査の hook は子プロセスに引き継がれないので、cli の口の旧い側は所要だけを出す（engine の子は loop.py の子の中で起き、見えない）。
あわせて、元の関数の Run ごとに、同じ Run の列を端まで打った物と突き合わせる（列が元の関数の出来事を落としていれば赤）:
loop.py の呼び出しの列（inproc の口の回だけ。語・引数・渡したファイルの中身・標準入力）と、最後の盤面（glharness.normalize_board と
first_difference）。盤面は世界の手と返答の中身の違いを、呼び出しの列は盤面を書かない手（拒まれた done・止めた run への next と status）の
落としを見る。作業場ごとに変わる物（git の commit の sha・道を本文に含むプロンプトの大きさ）は比べる前に伏せる。
"""
import argparse
import contextlib
import importlib
import json
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from unittest import mock

import glharness
import scenes
import waves

HERE = pathlib.Path(__file__).resolve().parent
TESTS = HERE.parent
PLUGIN = TESTS.parent
SOURCES = [str(PLUGIN / d) for d in ("engine", "rules", "scripts")]
KINDS = ("git", "python", "other")


@contextlib.contextmanager
def _in_workdir(workdir):
    """一時の置き場を workdir に向ける（台本の作業場・engine の置き場・子プロセスが同じ所を見る）"""
    with mock.patch.dict(os.environ, {"TMPDIR": str(workdir)}), mock.patch.object(tempfile, "tempdir", None):
        yield


# ---- 子の数 -------------------------------------------------------------------------------------------------------------

_BOX = None
_HOOKED = False


def kind_of(argv):
    """起こした子の頭の語で分ける: git・python（この Python か python の名の実行器）・その他"""
    head = argv.split()[0] if isinstance(argv, str) else (os.fsdecode(argv[0]) if argv else "")
    name = pathlib.PureWindowsPath(head).name.lower().removesuffix(".exe")   # / と \ のどちらの区切りでも頭の語を取る
    if name == "git":
        return "git"
    if name.startswith("python") or os.path.realpath(head) == os.path.realpath(sys.executable):
        return "python"
    return "other"


def _audit(event, args):
    if event == "subprocess.Popen" and _BOX is not None:
        _BOX[kind_of(args[1])] += 1


@contextlib.contextmanager
def children():
    """この間に起きた子の数（頭の語ごと）。監査の hook は外せないので、プロセスに 1 度だけ載せる"""
    global _BOX, _HOOKED
    if not _HOOKED:
        sys.addaudithook(_audit)
        _HOOKED = True
    box, saved = dict.fromkeys(KINDS, 0), _BOX
    _BOX = box
    try:
        yield box
    finally:
        _BOX = saved


# ---- 被覆の測り -----------------------------------------------------------------------------------------------------------

def measure_old(out_dir, workdir, scripts):
    """台本の関数を 1 本ずつ同じプロセスで回し、文脈 old:<台本の関数> で測る（台本ごとに別のデータのファイル） ——{台本: {ran, fails, wall_s, core}}"""
    import coverage
    got = {}
    for script in scripts:
        mod_name, fn = script.split(".")
        cov = coverage.Coverage(data_file=str(out_dir / f"old-{mod_name}-{fn}.cov"), source=SOURCES, context=f"old:{script}")
        mod = importlib.import_module(mod_name)
        ran0, fails0 = mod.ran, len(mod.fails)
        with _in_workdir(workdir):
            t0 = time.monotonic()
            cov.start()
            core = dict(cov.sys_info()).get("core")
            try:
                with glharness.driven(mod, "inproc"):
                    getattr(mod, fn)()
            finally:
                cov.stop()
                cov.save()
        got[script] = {"ran": mod.ran - ran0, "fails": mod.fails[fails0:], "wall_s": round(time.monotonic() - t0, 1), "core": core}
    return got


def build_in_contexts(switch, built_waves, built):
    """T1 の波と層 2 の列の接頭辞を 1 つずつ作り、作る直前に文脈を switch で替える（作りの行は自分の文脈にだけ入る）。
    波は親が表の先に在る。列の位置 k は、k-1 と、k の出来事が値を借りる別の列の位置を先に作ってから作る"""
    for name in waves.WAVES:
        switch(f"wave:{name}")
        built_waves.build(name)

    def visit(name, k):
        if (name, k) in built.kept:
            return
        if k > 1:
            visit(name, k - 1)
        for r in scenes.refs(scenes.HISTORIES[name].events[k - 1]):
            visit(*r)
        switch(f"given:{name}@{k}")
        built.build(name, k)
    for name, h in scenes.HISTORIES.items():
        visit(name, len(h.events))


def measure_built(data_file, workdir):
    """前置きの作りを、文脈 wave:<名前>・given:<列>@<位置> に分けて測る"""
    import coverage
    cov = coverage.Coverage(data_file=str(data_file), source=SOURCES)
    with _in_workdir(workdir):
        built_waves = waves.Waves(tempfile.mkdtemp(prefix="gl-cover-waves-", dir=workdir))
        built = scenes.Scenes(tempfile.mkdtemp(prefix="gl-cover-scenes-", dir=workdir))
        t0 = time.monotonic()
        cov.start()
        try:
            build_in_contexts(cov.switch_context, built_waves, built)
        finally:
            cov.stop()
            cov.save()
    return {"waves": len(waves.WAVES), "givens": len(built.kept), "wall_s": round(time.monotonic() - t0, 1)}


def measure_new(data_file, junit, files):
    """印を持つファイルを pytest-cov で測る（別のプロセス。文脈は node id|段。使った前置きは junitxml に載る）"""
    env = {**os.environ, "COVERAGE_FILE": str(data_file), "COVERAGE_CORE": "ctrace"}
    # 前置きは最初のテストの準備（setup）で作らせる——要ったときに作る既定のままだと、前置きを作る行が作りを呼んだテストの本体（run）に入る
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--gl-prebuild-waves", "--cov-context=test", "--cov-report=",
            f"--junitxml={junit}", *[f"--cov={s}" for s in SOURCES], *[str(HERE / f) for f in files]]
    t0 = time.monotonic()
    r = subprocess.run(argv, cwd=HERE, env=env, capture_output=True, text=True, encoding="utf-8")
    return {"exit": r.returncode, "tail": r.stdout.strip().splitlines()[-1:] if r.stdout.strip() else [], "wall_s": round(time.monotonic() - t0, 1)}


def used_contexts(junit_text):
    """junitxml から、テストの node id（fixture が積んだ値）ごとに使った前置きの作りの文脈（T1 の波はその祖先も）"""
    out = {}
    for case in ET.fromstring(junit_text).iter("testcase"):
        props = [(p.get("name"), p.get("value")) for p in case.iter("property")]
        ctx = ({f"wave:{x}" for k, v in props if k == waves.WAVE_PROPERTY for x in waves.lineage(v)}
               | {f"given:{v}" for k, v in props if k == scenes.GIVEN_PROPERTY})
        for node in {v for k, v in props if k == waves.NODE_PROPERTY}:
            out.setdefault(node, set()).update(ctx)
    return out


def rel(f):
    """測ったファイルを graphloops/ から始まる綴りに（旧い側と新しい側で、同じファイルを同じ鍵で比べる）"""
    parts = pathlib.Path(f).as_posix().split("/")
    return "/".join(parts[len(parts) - 1 - parts[::-1].index("graphloops"):]) if "graphloops" in parts else pathlib.Path(f).as_posix()


def lines_by_context(data_file):
    """{文脈: {(graphloops/ から始まるファイル, 行)}}"""
    import coverage
    data = coverage.CoverageData(basename=str(data_file))
    data.read()
    out = {}
    for f in data.measured_files():
        for line, ctxs in (data.contexts_by_lineno(f) or {}).items():
            for c in ctxs:
                out.setdefault(c, set()).add((rel(f), line))
    return out


# pytest-cov の --cov-context=test が文脈の末尾に付ける段の名前（pytest の hook の when の setup・call・teardown とは綴りが違い、
# 本体は run）。綴りが替わると run の和が空になり、包含が全部『含まれない』に落ちる——main が見えた段の名前を突き合わせて赤にする
RUN, SETUP = "run", "setup"


def phases(new_ctx):
    """新しい側の文脈に見えた段の名前の集合"""
    return {c.rsplit("|", 1)[1] for c in new_ctx if "|" in c}


def select_new(new_ctx, built_ctx, nodeids, used):
    """1 本の台本の新しい側: その台本を名乗る node id の run の文脈・読み込みの行（空の文脈）・使った前置きの作り（setup として数える）"""
    runs = {f"{n}|{RUN}" for n in nodeids}
    got = {c: ls for c, ls in new_ctx.items() if c in runs or c == ""}
    got.update({f"{c}|{SETUP}": built_ctx[c] for c in sorted(used) if c in built_ctx})
    return got


def compare(old_ctx, new_ctx):
    old = set().union(*old_ctx.values()) if old_ctx else set()
    run = {c: ls for c, ls in new_ctx.items() if c.endswith(f"|{RUN}")}
    setup = set().union(*(ls for c, ls in new_ctx.items() if c.endswith(f"|{SETUP}")), set())
    loading = new_ctx.get("", set())   # 文脈の空の行＝テストの外（集める段の import）
    run_all = set().union(*run.values(), set())
    engine_old = {x for x in old if x[0].startswith("graphloops/engine/")}
    only_in_setup = (old - run_all) & setup
    only_at_loading = (old - run_all - setup) & loading
    outside = old - run_all - setup - loading
    unique = {c: (ls & old) - set().union(*(o for k, o in run.items() if k != c), set()) for c, ls in run.items()}
    return {
        "old_lines": len(old), "old_engine_lines": len(engine_old),
        "covered_by_run": len(old & run_all), "covered_only_by_setup": len(only_in_setup),
        "covered_only_at_loading": len(only_at_loading), "not_covered": len(outside),
        "tests_with_unique_lines": sum(1 for v in unique.values() if v),
        "not_covered_lines": sorted(f"{f}:{n}" for f, n in outside),
        "only_setup_lines": sorted(f"{f}:{n}" for f, n in only_in_setup),
        "only_loading_lines": sorted(f"{f}:{n}" for f, n in only_at_loading),
        "unique_example": next(({"test": c.removesuffix(f"|{RUN}"), "lines": sorted(f"{f}:{n}" for f, n in v)[:5]}
                                for c, v in sorted(unique.items()) if v), None),
    }


def cover(found):
    """被覆の包含を測る ——(結果, 問題)"""
    import coverage
    by_script = {}
    for e in found:
        by_script.setdefault(e["script"], set()).add(e["nodeid"])
    files = sorted({e["file"] for e in found})
    with tempfile.TemporaryDirectory(prefix="gl-cover-") as td:
        old_dir, work = pathlib.Path(td) / "old", pathlib.Path(td) / "work"
        old_dir.mkdir()
        work.mkdir()
        old_runs = measure_old(old_dir, work, sorted(by_script))
        old_ctx = {}
        for f in sorted(old_dir.glob("old-*.cov")):
            old_ctx.update({c: ls for c, ls in lines_by_context(f).items() if c.startswith("old:")})
        built_run = measure_built(pathlib.Path(td) / "built.cov", work)
        built_ctx = {c: ls for c, ls in lines_by_context(pathlib.Path(td) / "built.cov").items() if c.startswith(("wave:", "given:"))}
        junit = pathlib.Path(td) / "new.xml"
        new_run = measure_new(pathlib.Path(td) / "new.cov", junit, files)
        new_ctx = lines_by_context(pathlib.Path(td) / "new.cov")
        used = used_contexts(junit.read_text(encoding="utf-8")) if junit.is_file() else {}
    per_script, problems = {}, []
    for script, nodeids in sorted(by_script.items()):
        if not any(f"{n}|{RUN}" in new_ctx for n in nodeids):
            problems.append(f"{script}: 名乗る node id が新しい側の run の文脈に 1 つも無い（node id の綴りか測りの取り違え）")
        mine = set().union(*(used.get(n, set()) for n in nodeids))
        per_script[script] = compare({c: v for c, v in old_ctx.items() if c == f"old:{script}"}, select_new(new_ctx, built_ctx, nodeids, mine))
    result = {"core": os.environ.get("COVERAGE_CORE"), "coverage": coverage.__version__, "old_runs": old_runs, "built_run": built_run,
              "new_run": new_run, "all": compare(old_ctx, new_ctx), "per_script": per_script, "phases": sorted(phases(new_ctx))}
    if not {RUN, SETUP} <= set(result["phases"]):
        problems.append(f"新しい側の文脈の段が想定（{RUN}・{SETUP}）と違う: 見えた段 {result['phases']}——pytest-cov の綴りが替わった")
    if result["all"]["old_engine_lines"] == 0:
        problems.append("旧い側の engine の行が 0（台本が engine を同じプロセスで通っていない——包含が恒真になる）")
    if result["all"]["tests_with_unique_lines"] == 0:
        problems.append("旧い側の行をそれだけが覆う新しいテストが 1 本も無い（外しても包含が崩れない——中身に依らず成り立つ疑い）")
    if any(v["fails"] for v in old_runs.values()) or new_run["exit"] != 0:
        problems.append("旧い側の台本か新しい側のテストが落ちた（測った行が正しい回の物でない）")
    problems += [f"{s}: どこにも含まれない行が {v['not_covered']} 行" for s, v in [("全体", result["all"]), *per_script.items()] if v["not_covered"]]
    return result, problems


# ---- 所要・子の数・盤面の突き合わせ（被覆なし） ----------------------------------------------------------------------------

@contextlib.contextmanager
def loop_calls():
    """inproc の口で同じプロセスに回した loop.py の呼び出し（語・引数・標準入力。引数のうち在るファイルは中身も）を順に控える。
    盤面の比べは、盤面を書かない手（拒まれた done・止めた run への next と status）を列が落としても同じになる——呼び出しの列で見る"""
    calls, real = [], glharness.inproc

    def rec(argv, cwd=None, env=None, input=None):
        args = [str(a) for a in argv]
        run_dir = args[args.index("--dir") + 1] if "--dir" in args else None
        calls.append({"dir": run_dir, "argv": [[a, pathlib.Path(a).read_text(encoding="utf-8", errors="replace")] if os.path.isfile(a) else a
                                               for a in args], "input": input})
        return real(argv, cwd=cwd, env=env, input=input)
    with mock.patch.object(glharness, "inproc", rec):
        yield calls


def run_old(script, workdir, driver):
    """元の関数を名指しで回す ——(所要と子の数, 作った作業場 [(頭, 置き場)], loop.py の呼び出し)。作業場は消さずに残す（突き合わせる）"""
    mod_name, fn = script.split(".")
    mod = importlib.import_module(mod_name)
    made = []

    def workspace(prefix):
        p = pathlib.Path(tempfile.mkdtemp(prefix=prefix))
        made.append((prefix, p))
        return None, p
    ran0, fails0 = mod.ran, len(mod.fails)
    with (_in_workdir(workdir), mock.patch.object(mod.parallel, "workspace", workspace), mock.patch.object(mod.parallel, "rm", lambda p: None),
          glharness.driven(mod, driver), children() as box, loop_calls() as calls):
        t0 = time.monotonic()
        getattr(mod, fn)()
        wall = round(time.monotonic() - t0, 1)
    return ({"wall_s": wall, "children": dict(box) if driver == "inproc" else None, "ran": mod.ran - ran0, "fails": mod.fails[fails0:]},
            made, calls)


def run_new(script, workdir):
    """その台本の行が使う列を、控えの置き場で端まで 1 度ずつ作る ——(所要と子の数, 控え, loop.py の呼び出し)"""
    names = sorted({n for n, _ in scenes.ROWS.get(script, ())})
    built = scenes.Scenes(tempfile.mkdtemp(prefix="gl-scenes-", dir=workdir))
    with _in_workdir(workdir), children() as box, loop_calls() as calls:
        t0 = time.monotonic()
        for n in names:
            built.build(n, len(scenes.HISTORIES[n].events))
        wall = round(time.monotonic() - t0, 1)
    return {"wall_s": wall, "children": dict(box), "histories": names}, built, calls


# 作業場ごとに変わり、振る舞いの違いでない物: git の commit の sha（作った時刻で変わる）と、作業場の道を本文に含むプロンプトの大きさ
SHA_LIKE = re.compile(r"\b[0-9a-f]{7,40}\b")
PATH_SIZED_KEYS = ("prompt_bytes",)


def _loose(v, key=""):
    if isinstance(v, dict):
        return {SHA_LIKE.sub("<sha>", k): _loose(x, k) for k, x in v.items()}
    if isinstance(v, list):
        return [_loose(x, key) for x in v]
    if key in PATH_SIZED_KEYS:
        return "<n>"
    return SHA_LIKE.sub("<sha>", v) if isinstance(v, str) else v


def _calls_of(calls, run_dir, roots):
    """ある Run の呼び出しを、作業場の根を <root> に置き換えて並べる"""
    subs = sorted(((form, f"<root{i}>") for i, r in enumerate(roots) for form in {str(r), os.path.realpath(str(r))}),
                  key=lambda x: -len(x[0]))   # 長い綴りから（/private/tmp の根が /tmp の置き換えで崩れない）

    def text(s):
        for a, b in subs:
            s = s.replace(a, b)
        return s
    return _loose([json.loads(text(json.dumps(c, ensure_ascii=False))) for c in calls
                   if c["dir"] and os.path.realpath(c["dir"]) == os.path.realpath(str(run_dir))])


def run_prefix(h):
    """列の init が作る Run の作業場の名前の頭（台本の Run が parallel.workspace に渡す形）"""
    return ("gl-review-" if h.kind == "review" else "gl-") + h.events[0]["name"] + "-"


def compare_runs(names, made, built, old_calls, new_calls):
    """元の関数の Run ごとに、loop.py の呼び出しの列と最後の盤面を、同じ Run の列を端まで打った物と比べる（{列: 最初の食い違い か None}）。
    呼び出しの列は inproc の口の回だけ比べる（cli の口の呼び出しは子プロセスの中で見えない）"""
    out = {}
    for n in names:
        h = scenes.HISTORIES[n]
        olds = [p for pre, p in made if pre == run_prefix(h)]
        if len(olds) != 1:
            out[n] = f"元の関数の Run（{run_prefix(h)}）が {len(olds)} 個"
            continue
        run = built.runs[n]
        graph = h.events[0].get("graph_drop")
        old_roots = [olds[0], *([p for pre, p in made if pre == f"gl-{h.kind}-nostop-"] if graph else [])]
        new_roots = [run.tmp, *([run.graph_root] if graph else [])]
        old_dir = olds[0] / run.dir.relative_to(run.tmp)
        calls = (glharness.first_difference(_calls_of(old_calls, old_dir, old_roots), _calls_of(new_calls, run.dir, new_roots), "$calls")
                 if old_calls else None)
        out[n] = calls or glharness.first_difference(_loose(glharness.normalize_board(old_dir, old_roots)),
                                                     _loose(glharness.normalize_board(run.dir, new_roots)))
    return out


def timing(scripts, driver):
    """台本ごとの所要・子の数・元の関数の Run との突き合わせ ——(結果, 問題)"""
    result, problems = {}, []
    with tempfile.TemporaryDirectory(prefix="gl-timing-") as td:
        for script in scripts:
            work = pathlib.Path(tempfile.mkdtemp(prefix="w-", dir=td))
            old, made, old_calls = run_old(script, work, driver)
            new, built, new_calls = run_new(script, work)
            runs = compare_runs(new["histories"], made, built, old_calls, new_calls)
            result[script] = {"old": old, "new": new, "runs": runs}
            problems += [f"{script}: 元の関数の check が落ちた: {old['fails'][:3]}"] if old["fails"] else []
            problems += [f"{script}: 列 {n} が元の関数の Run と違う: {d}" for n, d in runs.items() if d]
    return result, problems


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="結果の JSON の書き先")
    ap.add_argument("--no-cov", action="store_true", help="被覆を測らず、所要・子の数・盤面の突き合わせを撃つ")
    ap.add_argument("--driver", choices=("inproc", "cli"), default="inproc", help="--no-cov の旧い側が loop.py を呼ぶ口")
    ap.add_argument("--only", help="--no-cov で回す台本の関数（<台本>.<関数> をカンマで。既定は印が名乗る全部）")
    a = ap.parse_args(argv)
    os.environ.setdefault("COVERAGE_CORE", "ctrace")
    import ledger
    found, code, log = ledger.collect()
    if code != 0:
        print(log[-2000:], file=sys.stderr)
        print(f"印を集める段が {code} で終わった", file=sys.stderr)
        return 1
    for f in sorted({e["file"] for e in found}):   # 列を登録する（集める段が読んだモジュールと同じ物）
        importlib.import_module(pathlib.Path(f).stem)
    if a.no_cov:
        named = sorted({e["script"] for e in found})
        only = a.only.split(",") if a.only else named
        unknown = sorted(set(only) - set(named))
        if unknown:
            print(f"印が名乗らない台本の関数: {unknown}", file=sys.stderr)
            return 1
        result, problems = timing(only, a.driver)
        result = {"driver": a.driver, "scripts": result}
    else:
        result, problems = cover(found)
    result["problems"] = problems
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 1 if problems else 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):   # Windows の既定 cp1252 で日本語の出力が落ちないように
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    sys.exit(main(sys.argv[1:]))
