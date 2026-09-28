"""被覆の包含（台本を消す条件の 4——testplan の REDESIGN.md 4.2）: 台本の関数が通した行が、移した先のテストの和に含まれるかを測る。

手で撃つ道具で、pytest の一式には入れない（台本 2 関数を 1 回ずつ回すので重い。testslot の枠の中で回す）:

    COVERAGE_CORE=ctrace uv run --no-project --with pytest==9.1.1 --with coverage==7.16.1 --with pytest-cov==7.1.0 \\
        python graphloops/tests/py/cover_moved.py --old <旧い側の控えの置き場> [--out <結果の JSON>]

``--old`` の置き場に旧い側の測りの控え（coverage のデータと台本の件数・所要）が在れば使い回し、無ければ測って置く——台本を回すのは
控えを作る 1 回だけにする（新しい側を直して測り直す回に台本を回し直さない）

- **旧い側**: 台本の関数（ledger.SCRIPTS）を 1 本ずつ、glharness.driven(台本, "inproc") の下でこのプロセスで回して測る——loop.py は
  同じプロセスの loop.cli() に回るので、子プロセスを測る設定（coverage の patch = subprocess）なしで engine の行が数えられる。
  cli の口のまま測ると旧い側が同じプロセスで呼ぶ部品の行だけになり、包含が恒真になる（判定 2026-09-27 の単位 2）
- **新しい側**: 移した先のファイル（ledger.MOVED_FILES）を pytest-cov の --cov-context=test で測る。文脈は node id と段
  （setup・run・teardown）。波は --gl-prebuild-waves（waves.py）で最初のテストの setup に全部作らせ、台本の前半を歩く行を setup に
  入れる——run（検査の本体）の和と setup を分けて数える。見えた段に run と setup がそろわなければ赤（綴りの取り違えで run が空になる形）
- **ファイルの鍵**: graphloops/ から始まる綴りで比べる（旧い側の控えを別の作業ツリーで測っていても同じファイルが当たる）
- **計測器**: Python 3.14 の既定（sysmon）は動的な文脈を持たない（coverage の config の文書）ので ctrace に固定し、固定できたかを確かめる
- **読み込みの行**: 旧い側は台本の import ごと測る（engine の読み込みの行も入る）。新しい側では読み込みは集める段で済み、文脈が
  空の行になる——run・setup の和に無く、空の文脈に在る行は「読み込みの行」として別に数える
- **縮退の見張り**: 旧い側の engine の行が 0 なら赤。新しいテストのうち、旧い側の行をそれだけが覆うテスト（外すと包含が崩れる）を数える
  ——0 なら包含が新しい検査の中身に依らず成り立っている疑いとして赤
- 測る行: graphloops/engine・graphloops/rules・graphloops/scripts（loop.py ほか）。台本とテストの本文は数えない
"""
import argparse
import json
import os
import pathlib
import subprocess
import sys
import tempfile
import time

os.environ.setdefault("COVERAGE_CORE", "ctrace")
import coverage  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
TESTS = HERE.parent
PLUGIN = TESTS.parent
SOURCES = [str(PLUGIN / d) for d in ("engine", "rules", "scripts")]
sys.path[:0] = [str(HERE), str(TESTS), str(PLUGIN)]

import glharness  # noqa: E402
import ledger  # noqa: E402


def measure_old(keep, workdir):
    """台本の関数を 1 本ずつ同じプロセスで回し、文脈 old:<台本の関数> で測る（台本ごとに別のデータのファイル） ——{台本: {ran, fails, wall_s, core}}"""
    got = {}
    for script in ledger.SCRIPTS:
        mod_name, fn = script.split(".")
        cov = coverage.Coverage(data_file=str(keep / f"old-{mod_name}.cov"), source=SOURCES, context=f"old:{script}")
        mod = __import__(mod_name)
        ran0, fails0 = mod.ran, len(mod.fails)
        saved = os.environ.get("TMPDIR")
        os.environ["TMPDIR"] = str(workdir)
        import tempfile as tf
        tf.tempdir = None
        t0 = time.monotonic()
        cov.start()
        core = dict(cov.sys_info()).get("core")
        try:
            with glharness.driven(mod, "inproc"):
                getattr(mod, fn)()
        finally:
            cov.stop()
            cov.save()
            if saved is None:
                os.environ.pop("TMPDIR", None)
            else:
                os.environ["TMPDIR"] = saved
            tf.tempdir = None
        got[script] = {"ran": mod.ran - ran0, "fails": mod.fails[fails0:], "wall_s": round(time.monotonic() - t0, 1),
                       "core": core}
    return got


def measure_new(data_file):
    """移した先のファイルを pytest-cov で測る（別のプロセス。文脈は node id|段）"""
    env = {**os.environ, "COVERAGE_FILE": str(data_file), "COVERAGE_CORE": "ctrace"}
    # 波は最初のテストの準備（setup）で全部作らせる——要ったときに作る既定のままだと、波を作る行が作りを呼んだテストの本体（run）に入る
    argv = [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "--gl-prebuild-waves", "--cov-context=test", "--cov-report=",
            *[f"--cov={s}" for s in SOURCES], *[str(HERE / f) for f in ledger.MOVED_FILES]]
    t0 = time.monotonic()
    r = subprocess.run(argv, cwd=HERE, env=env, capture_output=True, text=True, encoding="utf-8")
    return {"exit": r.returncode, "tail": r.stdout.strip().splitlines()[-1:] if r.stdout.strip() else [], "wall_s": round(time.monotonic() - t0, 1)}


def rel(f):
    """測ったファイルを graphloops/ から始まる綴りに（旧い側の控えを別の作業ツリーで測っていても、同じファイルを同じ鍵で比べる）"""
    parts = pathlib.Path(f).as_posix().split("/")
    return "/".join(parts[len(parts) - 1 - parts[::-1].index("graphloops"):]) if "graphloops" in parts else pathlib.Path(f).as_posix()


def lines_by_context(data_file):
    """{文脈: {(graphloops/ から始まるファイル, 行)}}"""
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
    ap.add_argument("--old", required=True, help="旧い側の控えの置き場（在れば使い回す）")
    ap.add_argument("--out", help="結果の JSON の書き先")
    a = ap.parse_args(argv)
    keep = pathlib.Path(a.old)
    keep.mkdir(parents=True, exist_ok=True)
    if not (keep / "old.json").is_file():
        with tempfile.TemporaryDirectory(prefix="gl-cover-") as work:
            runs = measure_old(keep, pathlib.Path(work))
        (keep / "old.json").write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")
    old_runs = json.loads((keep / "old.json").read_text(encoding="utf-8"))
    old_ctx = {}
    for f in sorted(keep.glob("old-*.cov")):
        old_ctx.update({c: ls for c, ls in lines_by_context(f).items() if c.startswith("old:")})
    with tempfile.TemporaryDirectory(prefix="gl-cover-") as td:
        new_run = measure_new(pathlib.Path(td) / "new.cov")
        new_ctx = lines_by_context(pathlib.Path(td) / "new.cov")
    per_script = {}
    for script in ledger.SCRIPTS:
        f = "test_rejections_review.py" if script.startswith("simulate_review") else "test_rejections_research.py"
        per_script[script] = compare({c: v for c, v in old_ctx.items() if c == f"old:{script}"},
                                     # 波の作り（setup）はどのテストの準備に載っても台本 2 本の分を全部作るので、setup と読み込みは全部渡す
                                     {c: v for c, v in new_ctx.items() if c.startswith(f) or c == "" or c.endswith(f"|{SETUP}")})
    result = {"core": os.environ.get("COVERAGE_CORE"), "coverage": coverage.__version__, "old_runs": old_runs, "new_run": new_run,
              "all": compare(old_ctx, new_ctx), "per_script": per_script}
    problems = []
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
