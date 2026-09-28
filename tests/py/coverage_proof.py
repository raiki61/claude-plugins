#!/usr/bin/env python3
"""上位互換の証明（被覆の包含）: tests/run.sh の review-record.py の節が検証器の中で通した行が、この置き場
（python3 -m pytest tests/py）が通した行の和に含まれるかを coverage.py で測る。

使い方: python3 tests/py/coverage_proof.py <置き場> [--coverage-from <coverage.py の在る置き場>] [--only-new] [-- <pytest に足す引数>…]
- 旧い側は、台本の頭から節の終わりまでを本物の bash で回す（expect_output が "$@" を展開して検証器を起こす形も、冒頭の
  unset PYTHONOPTIMIZE などの環境もそのまま）。台帳（ledger.py）の読み取りは使わない——使うと、台帳の突合が緑なら
  包含も作りの上で成り立ち、何も測らない。新しい側は pytest を回す。どちらも python の起動ごとに sitecustomize から
  coverage.py を始め（COVERAGE_PROCESS_START）、子プロセス（台本の検査・煙テスト）も測る。旧い側は、この道具を動かす python を
  PATH の先頭に置いて回し、台本が選ぶ python がそれと違えば止める（両側を同じ解釈系で測る）
- --only-new: 旧い側を回し直さず、<置き場>/old の測りを使う（台本の節を手元で回すのは人が許した回数に限るため）。測った時の入力
  （検証器・台本の節の終わりまで・templates/・python と coverage.py の版）のハッシュが今と違えば止める
- -- の後の引数は、新しい側から検査を選び外すためだけに渡す（赤の腕）。pytest の要約に「N deselected」が無ければ止める
- 撃つのは CI の手で起こす job（.github/workflows/cover-moved.yml の段 root cover）。engine の子の中では tests/run.sh の入口が撃ちを拒む
- 終了: 0 = 含まれる / 1 = はみ出た行がある（行と、それを通した台本の検査の引数を出す）/ 2 = 空振りか道具の不備
  （どちらかの側が赤・測った行が 0・台本が実際に起こした引数の集合が台帳の読み取りと違う・何も選び外していない・旧い側の測りの
  版違い・想定外の例外）
"""
import argparse
import hashlib
import os
import pathlib
import re
import shutil
import subprocess
import sys
import traceback

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


def inputs_digest(root, extra):
    """旧い側の測りが依る入力（旧い側が回す台本の範囲・検証器・雛形と extra の文字列）のハッシュ"""
    lines = (root / "tests" / "run.sh").read_text(encoding="utf-8").splitlines()
    _, b = ledger.bounds(lines)
    files = [root / "scripts" / t.name for t in TARGETS] + sorted(p for p in (root / "templates").rglob("*") if p.is_file())
    parts = [("tests/run.sh", "\n".join(lines[:b]).encode("utf-8")),
             *((f.relative_to(root).as_posix(), f.read_bytes()) for f in files),
             *((f"extra{i}", e.encode("utf-8")) for i, e in enumerate(extra))]
    h = hashlib.sha256()
    for name, data in parts:
        h.update(b"%s\0%d\0" % (name.encode("utf-8"), len(data)) + data)
    return h.hexdigest()


def run_old(out, env):
    env = {**env, "PATH": os.pathsep.join([os.path.dirname(sys.executable), env.get("PATH", "")])}
    # 台本は PATH の python3（無ければ python）で検証器を起こす
    picked = shutil.which("python3", path=env["PATH"]) or shutil.which("python", path=env["PATH"])
    if not picked or not os.path.samefile(picked, sys.executable):
        stop(f"台本が選ぶ python（{picked}）がこの道具を動かす {sys.executable} と違う——両側を同じ解釈系で測れない")
    lines = (REPO / "tests" / "run.sh").read_text(encoding="utf-8").splitlines()
    a, b = ledger.bounds(lines)
    text = [*lines[:a], 'export COVPROOF_WORK="$WORK" COVPROOF_ROOT="$ROOT"', *lines[a:b], 'exit "$fail"', ""]
    (out / "old.sh").write_text("\n".join(text), encoding="utf-8")
    # source なので $0 は台本のパスのまま（台本は $0 から ROOT を出す）
    bash = shutil.which("bash") or "bash"
    return subprocess.run([bash, "-c", 'source "$1"', str(REPO / "tests" / "run.sh"), str(out / "old.sh")],
                          env=env, cwd=REPO, capture_output=True)


def run_new(env, extra):
    return subprocess.run([sys.executable, "-m", "pytest", str(HERE), "-q", "-p", "no:cacheprovider", *extra],
                          env=env, cwd=REPO, capture_output=True)


def deselected(pytest_args, summary):
    """pytest の要約が言う選び外した件数。-- の後の引数を渡したのに 0 なら止める（赤の腕の空振り）"""
    m = re.search(r"(\d+) deselected", summary)
    n = int(m.group(1)) if m else 0
    if pytest_args and not n:
        stop(f"-- の後の引数 {pytest_args} で新しい側から何も選び外していない（node id は tests/py を根に書く）: {summary[-2000:]}")
    return n


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
    # 子は cwd=REPO で PYTHONPATH を読むので、相対のままだと親と別の場所を指す
    p.add_argument("--coverage-from", action="append", default=[], type=lambda s: str(pathlib.Path(s).resolve()))
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
    # 回す前に取る（回している間に変わった物を掴まない）。old/ の中に置くので、旧い側を回し直すたびに消える
    digest = inputs_digest(REPO, (sys.version, coverage.__version__))
    mark = out / "old" / "inputs"
    if a.only_new:
        if not any((out / "old").glob(".coverage*")) or not mark.is_file():
            stop(f"--only-new なのに {out / 'old'} に旧い側の測り（か、測った時の入力の印 inputs）が無い")
        if mark.read_text(encoding="utf-8") != digest:
            stop("旧い側の測りが、今の検証器・台本・雛形・python・coverage.py と別の版で取られた——旧い側を回し直せ")
    else:
        (out / "old").mkdir(exist_ok=True)
        for f in (out / "old").iterdir():
            f.unlink()
        got = run_old(out, env_for(out, "old", a.coverage_from))
        (out / "old.log").write_bytes(got.stdout + got.stderr)
        if got.returncode != 0:
            stop(f"旧い側（台本の節）が赤で終わった（終了 {got.returncode}）——包含を言える状態でない", got)
        mark.write_text(digest, encoding="utf-8")
    got = run_new(env_for(out, "new", a.coverage_from), a.pytest_args)
    (out / "new.log").write_bytes(got.stdout + got.stderr)
    if got.returncode != 0:
        stop(f"新しい側（pytest）が赤で終わった（終了 {got.returncode}）——包含を言える状態でない", got)
    print(f"新しい側から選び外した検査 {deselected(a.pytest_args, got.stdout.decode('utf-8', 'replace'))} 件")
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


def guarded_main():
    """終了コードの境界: 文を渡した SystemExit（素のままだと 1）と想定外の例外を、はみ出し（1）と分けて 2 に倒す"""
    try:
        main()
    except SystemExit as e:
        if e.code is None or isinstance(e.code, int):
            raise
        print(e.code)
        sys.exit(2)
    except Exception:
        traceback.print_exc()
        sys.exit(2)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    guarded_main()
