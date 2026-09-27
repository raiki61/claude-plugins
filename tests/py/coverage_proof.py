#!/usr/bin/env python3
"""上位互換の証明（被覆の包含）: tests/run.sh の review-record.py の節が検証器の中で通した行が、この置き場
（python3 -m pytest tests/py）が通した行の和に含まれるかを coverage.py で測る。

使い方: python3 tests/py/coverage_proof.py <置き場> [--coverage-from <coverage.py の在る置き場>] [--only-new] [-- <pytest に足す引数>…]
- 旧い側は、台本の頭から節の終わりまでを本物の bash で回す（expect_output が "$@" を展開して検証器を起こす形も、冒頭の
  unset PYTHONOPTIMIZE などの環境もそのまま）。台帳（ledger.py）の読み取りは使わない——使うと、台帳の突合が緑なら
  包含も作りの上で成り立ち、何も測らない。新しい側は pytest を回す。どちらも python の起動ごとに sitecustomize から
  coverage.py を始め（COVERAGE_PROCESS_START）、子プロセス（台本の検査・煙テスト）も測る
- --only-new: 旧い側を回し直さず、<置き場>/old の測りを使う（台本の節を手元で回すのは人が許した回数に限るため）
- 終了: 0 = 含まれる / 1 = はみ出た行がある（行と、それを通した台本の検査の引数を出す）/ 2 = 空振りか道具の不備
  （どちらかの側が赤・測った行が 0・台本が実際に起こした引数の集合が台帳の読み取りと違う）
"""
import argparse
import os
import pathlib
import shutil
import subprocess
import sys

import ledger

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
TARGETS = [REPO / "scripts" / "review-record.py", REPO / "scripts" / "record_common.py"]
# 先に sys.path の後ろの sitecustomize を走らせる（Homebrew の python はそれで site-packages を足す。覆うと pytest が消える）。
# 検証器の起動だけに、読む記録の引数で文脈の名前を付ける（台帳の Row.args と同じ形: <work> の下は素の名前・根の下は repo:）
SITE = r'''import importlib.machinery, importlib.util, os, sys
_here = os.path.dirname(os.path.abspath(__file__))
_next = importlib.machinery.PathFinder.find_spec(
    "sitecustomize", [p for p in sys.path if os.path.abspath(p or os.curdir) != _here])
if _next is not None:
    _next.loader.exec_module(importlib.util.module_from_spec(_next))
if os.environ.get("COVERAGE_PROCESS_START"):
    import coverage
    cov = coverage.process_startup()
    if cov is not None and sys.argv[0].replace("\\", "/").endswith("/scripts/review-record.py"):
        marks = [(os.environ.get(k, "\0") + "/", to) for k, to in (("COVPROOF_WORK", ""), ("COVPROOF_ROOT", "repo:"))]
        names = []
        for a in sys.argv[1:]:
            for m, to in marks:
                if a.startswith(m):
                    a = to + a[len(m):]
                    break
            names.append(a)
        cov.switch_context("argv:" + " ".join(names))
'''


def rc(out, side):
    # 動的な文脈は sitecustomize の switch_context で付ける（sysmon の core は動的な文脈を持てないので ctrace）。
    # dynamic_context = test_function は使えない——include の外（テストの関数）のフレームを tracer が見ないので付かない（実測）
    path = out / f"{side}.coveragerc"
    path.write_text(f"[run]\ncore = ctrace\nparallel = true\ndata_file = {out / side / '.coverage'}\ncontext = {side}\n"
                    "include =\n" + "".join(f"    {t}\n" for t in TARGETS), encoding="utf-8")
    return path


def env_for(out, side, cov_from):
    site = out / "site"
    site.mkdir(exist_ok=True)
    (site / "sitecustomize.py").write_text(SITE, encoding="utf-8")
    paths = [str(site), *cov_from, *filter(None, [os.environ.get("PYTHONPATH")])]
    return {**os.environ, "COVERAGE_PROCESS_START": str(rc(out, side)), "PYTHONPATH": os.pathsep.join(paths)}


def run_old(out, env):
    """台本の頭から review-record.py の節の終わりまでを回す。節の手前で $WORK と $ROOT を子へ渡すだけ足す"""
    lines = (REPO / "tests" / "run.sh").read_text(encoding="utf-8").splitlines()
    a, b = lines.index(ledger.SECTION[0]), lines.index(ledger.SECTION[1])
    text = [*lines[:a], 'export COVPROOF_WORK="$WORK" COVPROOF_ROOT="$ROOT"', *lines[a:b], 'exit "$fail"', ""]
    (out / "old.sh").write_text("\n".join(text), encoding="utf-8")
    # source なので $0 は台本のパスのまま（台本は $0 から ROOT を出す）
    bash = shutil.which("bash") or "bash"
    return subprocess.run([bash, "-c", 'source "$1"', str(REPO / "tests" / "run.sh"), str(out / "old.sh")],
                          env=env, cwd=REPO, capture_output=True)


def run_new(env, extra):
    return subprocess.run([sys.executable, "-m", "pytest", str(HERE), "-q", "-p", "no:cacheprovider", *extra],
                          env=env, cwd=REPO, capture_output=True)


def stop(msg, got=None):
    print(msg)
    if got is not None:
        print(got.stdout.decode("utf-8", "replace")[-4000:], got.stderr.decode("utf-8", "replace")[-4000:], sep="\n")
    sys.exit(2)


def measured(out, side):
    import coverage
    data = coverage.CoverageData(basename=str(out / side / ".coverage"))
    parts = list((out / side).glob(".coverage.*"))
    if parts:
        coverage.Coverage(config_file=str(out / f"{side}.coveragerc")).combine(strict=True)
    data.read()
    return data


def main():
    p = argparse.ArgumentParser()
    p.add_argument("out", type=pathlib.Path)
    p.add_argument("--coverage-from", action="append", default=[])
    p.add_argument("--only-new", action="store_true")
    p.add_argument("pytest_args", nargs="*")
    a = p.parse_args()
    sys.path[:0] = a.coverage_from
    try:
        import coverage
    except ImportError:
        stop("coverage.py を import できない——入れるか、--coverage-from で置き場を渡せ")
    out = a.out.resolve()
    (out / "new").mkdir(parents=True, exist_ok=True)
    for f in (out / "new").iterdir():
        f.unlink()
    if a.only_new:
        if not any((out / "old").glob(".coverage*")):
            stop(f"--only-new なのに {out / 'old'} に旧い側の測りが無い")
    else:
        (out / "old").mkdir(exist_ok=True)
        for f in (out / "old").iterdir():
            f.unlink()
        got = run_old(out, env_for(out, "old", a.coverage_from))
        (out / "old.log").write_bytes(got.stdout + got.stderr)
        if got.returncode != 0:
            stop(f"旧い側（台本の節）が赤で終わった（終了 {got.returncode}）——包含を言える状態でない", got)
    got = run_new(env_for(out, "new", a.coverage_from), a.pytest_args)
    (out / "new.log").write_bytes(got.stdout + got.stderr)
    if got.returncode != 0:
        stop(f"新しい側（pytest）が赤で終わった（終了 {got.returncode}）——包含を言える状態でない", got)
    print(f"coverage.py {coverage.__version__}")
    want = {"argv:" + " ".join(r.args) for r in ledger.script_rows()}
    sys.exit(1 if judge(measured(out, "old"), measured(out, "new"), want) else 0)


def judge(old, new, want):
    """旧い側の行が新しい側の行に含まれるかを出し、はみ出た行の数を返す（want は台帳が読んだ検証器の引数の文脈の集合）"""
    seen = {c.split("|", 1)[1] for c in old.measured_contexts() if "|argv:" in c}
    if seen != want:
        stop(f"台本が実際に起こした引数の集合が台帳の読み取りと違う——台本にだけ在る: {sorted(seen - want)} / "
             f"台帳にだけ在る: {sorted(want - seen)}")
    print(f"旧い側の検証器の起動の引数 {len(seen)} 通り（台帳と一致）")
    excess = 0
    for t in TARGETS:
        o, n = set(old.lines(str(t)) or ()), set(new.lines(str(t)) or ())
        if not o or not n:
            stop(f"{t.name}: 測った行が 0（旧い側 {len(o)}・新しい側 {len(n)}）——測りが空振りしている")
        print(f"{t.relative_to(REPO)}: 旧い側 {len(o)} 行・新しい側 {len(n)} 行・はみ出し {len(o - n)} 行・"
              f"新しい側だけ {len(n - o)} 行")
        ctx = old.contexts_by_lineno(str(t))
        for line in sorted(o - n):
            print(f"  はみ出し {t.name}:{line} ← {', '.join(sorted(c.split('|', 1)[-1] for c in ctx.get(line, [])))}")
        excess += len(o - n)
    return excess


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    main()
