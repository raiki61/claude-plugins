"""被覆の包含（台本を消す条件の 4——testplan の REDESIGN.md 4.2）: 台本の関数が通した行が、移した先のテストの和に含まれるかを測る。

手で撃つ道具で、pytest の一式には入れない（移した台本の関数を 1 回ずつ回すので重い。testslot の枠の中で回す）:

    COVERAGE_CORE=ctrace uv run --no-project --with pytest==9.1.1 --with coverage==7.16.1 --with pytest-cov==7.1.0 \\
        python graphloops/tests/py/cover_moved.py [--out <結果の JSON>]

旧い側も新しい側も、撃つたびにこの回の一時の置き場で測る——前の回の測りを使い回さない（台本や engine が動いた版の行と今の
新しい側を比べると、行番号のずれた比べが偶然重なって緑になりうる）。台本を回すのは 1 回の撃ちにつき 1 本 1 回。

台本→移し先の対応は印 moved_from 1 つから引く（ledger.collect が置き場を全部集めた印）。見る台本も、新しい側に回すファイルも、
台本ごとに数える node id も、その印の集合から決める——ファイル名の頭では決めない。

- **旧い側**: 印が名乗る台本の関数を 1 本ずつ、glharness.driven(台本, "inproc") の下でこのプロセスで回して測る——loop.py は
  同じプロセスの loop.cli() に回るので、子プロセスを測る設定（coverage の patch = subprocess）なしで engine の行が数えられる。
  cli の口のまま測ると旧い側が同じプロセスで呼ぶ部品の行だけになり、包含が恒真になる（判定 2026-09-27 の単位 2）
- **新しい側**: 印を持つファイルを pytest-cov の --cov-context=test で測る。文脈は node id と段（setup・run・teardown）。波は
  --gl-prebuild-waves（waves.py）で最初のテストの setup に全部作らせ、台本の前半を歩く行を setup に入れる——run（検査の本体）の和と
  setup を分けて数える。見えた段に run と setup がそろわなければ赤（綴りの取り違えで run が空になる形）
- **台本ごと（per_script）**: 新しい側は、その台本を名乗る node id の run の文脈と、そのテストが使った波（とその祖先）の作りだけを数える。
  使った波は fixture wave が user_properties に積み、--junitxml で読む。波の作りは measure_waves がこのプロセスで波の表の順に作り、
  coverage の switch_context で波ごとの文脈（wave:<名前>）に分けて測る（全部の波の作りを全部の台本に渡すと、別の台本の波が通した行で
  『含まれる』と出る）。読み込みの行（文脈が空）は全部の台本に渡す——旧い側は同じプロセスで台本を順に回すので、遅れて読む engine の
  import の行は最初に回した台本の文脈にだけ入る
- **ファイルの鍵**: graphloops/ から始まる綴りで比べる（測った一時の置き場の綴りに依らず同じファイルが当たる）
- **計測器**: Python 3.14 の既定（sysmon）は動的な文脈を持たない（coverage の config の文書）ので ctrace に固定し、固定できたかを確かめる
- **読み込みの行**: 旧い側は台本の import ごと測る（engine の読み込みの行も入る）。新しい側では読み込みは集める段で済み、文脈が
  空の行になる——run・setup の和に無く、空の文脈に在る行は「読み込みの行」として別に数える
- **縮退の見張り**: 旧い側の engine の行が 0 なら赤。新しいテストのうち、旧い側の行をそれだけが覆うテスト（外すと包含が崩れる）を数える
  ——0 なら包含が新しい検査の中身に依らず成り立っている疑いとして赤。印が名乗る台本のうち、名乗る node id が新しい側の run の文脈に
  1 つも無い物も赤
- 測る行: graphloops/engine・graphloops/rules・graphloops/scripts（loop.py ほか）。台本とテストの本文は数えない

coverage と計測器の環境変数は main の中で読み込む（small のテスト test_cover_moved.py が選ぶ段の関数を import しても pytest の
プロセスに漏らさない）。
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

HERE = pathlib.Path(__file__).resolve().parent
TESTS = HERE.parent
PLUGIN = TESTS.parent
SOURCES = [str(PLUGIN / d) for d in ("engine", "rules", "scripts")]
WAVE_PROPERTY = "gl_wave"


def _in_workdir(workdir):
    """一時の置き場（TMPDIR）を workdir に向け、戻す口を返す"""
    import tempfile as tf
    saved = os.environ.get("TMPDIR")
    os.environ["TMPDIR"] = str(workdir)
    tf.tempdir = None

    def back():
        if saved is None:
            os.environ.pop("TMPDIR", None)
        else:
            os.environ["TMPDIR"] = saved
        tf.tempdir = None
    return back


def measure_old(out_dir, workdir, scripts):
    """台本の関数を 1 本ずつ同じプロセスで回し、文脈 old:<台本の関数> で測る（台本ごとに別のデータのファイル） ——{台本: {ran, fails, wall_s, core}}"""
    import coverage
    import glharness
    got = {}
    for script in scripts:
        mod_name, fn = script.split(".")
        cov = coverage.Coverage(data_file=str(out_dir / f"old-{mod_name}-{fn}.cov"), source=SOURCES, context=f"old:{script}")
        mod = __import__(mod_name)
        ran0, fails0 = mod.ran, len(mod.fails)
        back = _in_workdir(workdir)
        t0 = time.monotonic()
        cov.start()
        core = dict(cov.sys_info()).get("core")
        try:
            with glharness.driven(mod, "inproc"):
                getattr(mod, fn)()
        finally:
            cov.stop()
            cov.save()
            back()
        got[script] = {"ran": mod.ran - ran0, "fails": mod.fails[fails0:], "wall_s": round(time.monotonic() - t0, 1), "core": core}
    return got


def measure_waves(data_file, workdir):
    """波の表の順に、波をこのプロセスで 1 つずつ作り、文脈 wave:<名前> で測る（親は表の先に在るので、作りの行は自分の波にだけ入る）"""
    import coverage
    import waves
    cov = coverage.Coverage(data_file=str(data_file), source=SOURCES)
    back = _in_workdir(workdir)
    built = waves.Waves(tempfile.mkdtemp(prefix="gl-cover-waves-", dir=workdir))
    t0 = time.monotonic()
    cov.start()
    try:
        for name in waves.WAVES:
            cov.switch_context(f"wave:{name}")
            built.build(name)
    finally:
        cov.stop()
        cov.save()
        back()
    return {"waves": len(waves.WAVES), "wall_s": round(time.monotonic() - t0, 1)}


def measure_new(data_file, junit, files):
    """印を持つファイルを pytest-cov で測る（別のプロセス。文脈は node id|段。使った波は junitxml に載る）"""
    env = {**os.environ, "COVERAGE_FILE": str(data_file), "COVERAGE_CORE": "ctrace"}
    # 波は最初のテストの準備（setup）で全部作らせる——要ったときに作る既定のままだと、波を作る行が作りを呼んだテストの本体（run）に入る
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--gl-prebuild-waves", "--cov-context=test", "--cov-report=",
            f"--junitxml={junit}", *[f"--cov={s}" for s in SOURCES], *[str(HERE / f) for f in files]]
    t0 = time.monotonic()
    r = subprocess.run(argv, cwd=HERE, env=env, capture_output=True, text=True, encoding="utf-8")
    return {"exit": r.returncode, "tail": r.stdout.strip().splitlines()[-1:] if r.stdout.strip() else [], "wall_s": round(time.monotonic() - t0, 1)}


def used_waves(junit_text):
    """junitxml から、テストの node id（置き場からの相対。モジュールの直下の関数）ごとに使った波の名前の集合"""
    out = {}
    for case in ET.fromstring(junit_text).iter("testcase"):
        nodeid = case.get("classname", "").replace(".", "/") + ".py::" + case.get("name", "")
        names = {p.get("value") for p in case.iter("property") if p.get("name") == WAVE_PROPERTY}
        if names:
            out.setdefault(nodeid, set()).update(names)
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


def select_new(new_ctx, wave_ctx, nodeids, waves_used):
    """1 本の台本の新しい側: その台本を名乗る node id の run の文脈・読み込みの行（空の文脈）・使った波の作り（setup として数える）"""
    runs = {f"{n}|{RUN}" for n in nodeids}
    got = {c: ls for c, ls in new_ctx.items() if c in runs or c == ""}
    got.update({f"wave:{w}|{SETUP}": wave_ctx[f"wave:{w}"] for w in sorted(waves_used) if f"wave:{w}" in wave_ctx})
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


def main(argv):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", help="結果の JSON の書き先")
    a = ap.parse_args(argv)
    os.environ.setdefault("COVERAGE_CORE", "ctrace")
    sys.path[:0] = [str(HERE), str(TESTS), str(PLUGIN)]
    import coverage
    import ledger
    import waves
    found, code, log = ledger.collect()
    if code != 0:
        print(log[-2000:], file=sys.stderr)
        print(f"印を集める段が {code} で終わった", file=sys.stderr)
        return 1
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
        wave_run = measure_waves(pathlib.Path(td) / "waves.cov", work)
        wave_ctx = {c: ls for c, ls in lines_by_context(pathlib.Path(td) / "waves.cov").items() if c.startswith("wave:")}
        junit = pathlib.Path(td) / "new.xml"
        new_run = measure_new(pathlib.Path(td) / "new.cov", junit, files)
        new_ctx = lines_by_context(pathlib.Path(td) / "new.cov")
        used = used_waves(junit.read_text(encoding="utf-8")) if junit.is_file() else {}
    per_script, problems = {}, []
    for script, nodeids in sorted(by_script.items()):
        if not any(f"{n}|{RUN}" in new_ctx for n in nodeids):
            problems.append(f"{script}: 名乗る node id が新しい側の run の文脈に 1 つも無い（node id の綴りか測りの取り違え）")
        waves_used = {x for n in nodeids for w in used.get(n, ()) for x in waves.lineage(w)}
        per_script[script] = compare({c: v for c, v in old_ctx.items() if c == f"old:{script}"},
                                     select_new(new_ctx, wave_ctx, nodeids, waves_used))
    result = {"core": os.environ.get("COVERAGE_CORE"), "coverage": coverage.__version__, "old_runs": old_runs, "wave_run": wave_run,
              "new_run": new_run, "all": compare(old_ctx, new_ctx), "per_script": per_script}
    result["phases"] = sorted(phases(new_ctx))
    if not {RUN, SETUP} <= set(result["phases"]):
        problems.append(f"新しい側の文脈の段が想定（{RUN}・{SETUP}）と違う: 見えた段 {result['phases']}——pytest-cov の綴りが替わった")
    if result["all"]["old_engine_lines"] == 0:
        problems.append("旧い側の engine の行が 0（台本が engine を同じプロセスで通っていない——包含が恒真になる）")
    if result["all"]["tests_with_unique_lines"] == 0:
        problems.append("旧い側の行をそれだけが覆う新しいテストが 1 本も無い（外しても包含が崩れない——中身に依らず成り立つ疑い）")
    if any(v["fails"] for v in old_runs.values()) or new_run["exit"] != 0:
        problems.append("旧い側の台本か新しい側のテストが落ちた（測った行が正しい回の物でない）")
    result["problems"] = problems
    text = json.dumps(result, ensure_ascii=False, indent=1)
    if a.out:
        pathlib.Path(a.out).write_text(text, encoding="utf-8")
    print(text)
    return 1 if problems or any(v["not_covered"] for v in [result["all"], *per_script.values()]) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
