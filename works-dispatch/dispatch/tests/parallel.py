#!/usr/bin/env python3
"""dispatch の試験を、試験のクラスを小さい組に分け、組ごとに別のプロセスで並べて回す。中身は `python3 -B -m unittest discover` と同じ試験。

なぜ要るか: 試験の時間のほとんどは、試験が起動した git などの子のプロセスを待つ時間で、Python は CPU をほぼ使わない
（2026-10-20 に 1 つのプロセスで 21 分、CPU 7.9%）。待ちなので、並べればそのまま縮む。
プロセスを分けるのは、試験が os.environ を mock.patch.dict で替えるため（スレッドで並べると、ほかの試験の環境が混ざる）。
1 つの組（同じクラスの、続いた CHUNK 件までの試験）を 1 つのプロセスで順に回す。大きいクラスを分けるのは、1 つのクラスの時間が
全体の時間の下限になるため（分ける前は test_deliver.Flow の 1 つで 205 秒）。setUpClass と同じモジュールの作り置き（test_provision の
_template）は、組ごとに作り直す（どの試験も、作り置きの中身に頼らずに通る形で書いてある）。

使い方: python3 -B works-dispatch/dispatch/tests/parallel.py [-j N] [試験の名前 ...]
  -j を省けば DISPATCH_TEST_WORKERS、それも無ければ 4（ルートの CLAUDE.md の「並べすぎない」に合わせる）。-j 1 で直列。
  試験の名前（例 test_land・test_land.Queue）を渡せば、その試験だけを回す。
最後の行は unittest と同じ「OK」か「FAILED (...)」。終わりの値は、全部緑で 0、赤があれば 1。
集めた試験の数と走った数が合わなければ赤にする（プロセスが落ちて試験が黙って抜けるのを止めるため）。
"""

import argparse
import concurrent.futures
import io
import os
import pathlib
import sys
import time
import unittest

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent.parent.parent   # discover の -t（パッケージの頂き。works-dispatch.dispatch.tests.test_x の形で読む）
PACKAGE = ".".join(HERE.relative_to(ROOT).parts)
CHUNK = 8   # 1 つの組の試験の数の上限


def _cases(suite):
    for t in suite:
        if isinstance(t, unittest.TestSuite):
            yield from _cases(t)
        else:
            yield t


def collect(names=()):
    """([(組の名前（モジュール.クラス）, 試験の id の並び)], 試験の数)。読めなかったモジュールは unittest の _FailedTest として 1 件に数え、子で赤になる。"""
    loader = unittest.TestLoader()
    if names:
        suite = unittest.TestSuite(loader.loadTestsFromName(n if n.startswith(PACKAGE) else f"{PACKAGE}.{n}") for n in names)
    else:
        suite = loader.discover(str(HERE), top_level_dir=str(ROOT))
    groups = {}
    for case in _cases(suite):
        key = f"{type(case).__module__}.{type(case).__qualname__}"
        groups.setdefault(key, []).append(case.id())
    chunks = [(k, ids[i:i + CHUNK]) for k, ids in groups.items() for i in range(0, len(ids), CHUNK)]
    # 試験の多い組から先に回す（重い組が最後に残って 1 つだけ走る時間を減らす）
    chunks.sort(key=lambda c: -len(c[1]))
    return chunks, sum(len(v) for v in groups.values())


def run_group(ids):
    """子のプロセスで、試験の id の並びを回す。(走った数, 赤の文の並び, 見送りの数, 秒)。"""
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    start = time.monotonic()
    suite = unittest.TestSuite(unittest.TestLoader().loadTestsFromName(i) for i in ids)
    out = io.StringIO()
    result = unittest.TextTestRunner(stream=out, verbosity=0).run(suite)
    bad = [f"{kind}: {test.id()}\n{text}" for kind, items in (("FAIL", result.failures), ("ERROR", result.errors),
                                                            ("UNEXPECTED SUCCESS", [(t, "") for t in result.unexpectedSuccesses]))
           for test, text in items]
    return result.testsRun, bad, len(result.skipped), time.monotonic() - start


def main(argv):
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("-j", type=int, default=int(os.environ.get("DISPATCH_TEST_WORKERS") or 4))
    p.add_argument("names", nargs="*")
    args = p.parse_args(argv)
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    groups, want = collect(args.names)
    start = time.monotonic()
    ran, bad, skipped, slow = 0, [], 0, []
    with concurrent.futures.ProcessPoolExecutor(max_workers=max(1, args.j)) as pool:
        futures = {pool.submit(run_group, ids): name for name, ids in groups}
        for f in concurrent.futures.as_completed(futures):
            name = futures[f]
            try:
                n, b, s, secs = f.result()
            except Exception as e:   # 子のプロセスが落ちた（BrokenProcessPool など）。その組の試験は走っていない
                bad.append(f"ERROR: {name}\n子のプロセスが落ちた: {e!r}")
                continue
            ran, skipped = ran + n, skipped + s
            bad += b
            slow.append((secs, name))
    took = time.monotonic() - start
    for text in bad:
        print("=" * 70)
        print(text)
    print("-" * 70)
    print("遅い組: " + ", ".join(f"{name.rsplit('.', 2)[-2]}.{name.rsplit('.', 1)[-1]} {secs:.0f}s"
                                  for secs, name in sorted(slow, reverse=True)[:5]))
    print(f"Ran {ran} tests in {took:.3f}s（{len(groups)} 組・{args.j} プロセス）")
    if ran != want:
        bad.append("count")
        print(f"集めた試験は {want} 件なのに、走ったのは {ran} 件")
    print()
    if bad:
        print(f"FAILED (failures={len(bad)})")
        return 1
    print("OK" + (f" (skipped={skipped})" if skipped else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
