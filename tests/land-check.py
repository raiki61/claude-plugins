#!/usr/bin/env python3
"""メインブランチに入れるゲート（.claude/company.toml の [land] の check）から、ルートの tests/run.sh を回す。

tests/run.sh を TESTS_LAND=1 で回し（graphloops の模擬実行の 1 件だけを見送る。見送った後の全体が手元で 4〜5 分）、赤の検査の名前を
tests/land-known-red.txt と照合する。止めるのは次の場合。
- 一覧に無い赤（この変更か、一覧に足し忘れた赤）
- 一覧に在るのに緑になった検査（直したなら一覧から消す。一覧が古いままだと、同じ検査がまた赤になっても止まらない）
- 名前と食い違いの間に「 — 」の無い赤の行（検査の名前を読めないので、一覧と照合できない）
- 件数のチェックが合わない
- tests/run.sh が最後の行（「N 件すべて緑」か「N 件のうち失敗あり」）を出さずに終わった（途中で落ちて、残りの検査が走っていない）
- 赤の行が無いのに、終わりの値が 0 でない

一覧はメインブランチに今残っている赤だけを持ち、足すのは赤を持つ担当者が決まっているときだけにする（行の上のコメントに受付を書く）。
CI は一覧を読まず、今までどおり全部を赤にする。
このゲートを置く前は、ルートの検査を回すのは main に入った後の CI だけで、部署が main に入れるたびに赤が積み上がった
（2026-10-19、受付 b9ab0d。受付 92bbe4 で赤を直した数時間後に、5 種の新しい赤が入った）。

使い方: python3 tests/land-check.py               tests/run.sh を回して照合する
        python3 tests/land-check.py --judge <出力のファイル> <終わりの値>   回した出力を照合だけする（試験用）
終わりの値: 0 は止める物が無い、1 は止める物が在る、2 は使い方の誤り。
"""
import os
import pathlib
import re
import shutil
import subprocess
import sys

for _s in (sys.stdout, sys.stderr):
    if hasattr(_s, "reconfigure"):
        _s.reconfigure(encoding="utf-8")

ROOT = pathlib.Path(__file__).resolve().parent.parent
KNOWN = ROOT / "tests" / "land-known-red.txt"
FAIL_LINE = re.compile(r"^  FAIL (.+?) — ", re.M)   # tests/run.sh の expect_output が出す赤の行（名前と食い違いの間に「 — 」）
ANY_FAIL = re.compile(r"^  FAIL ", re.M)   # 赤の行の全部（expect_output の外の検査は「 — 」を書かないことがある）
OK_LINE = re.compile(r"^  ok   (.+)$", re.M)
SKIP_MARK = " # SKIP"   # 見送りの行（tests/run.sh の SKIP_MARK）。走らなかった検査で、緑に数えない
COUNT_BAD = "件を期待"   # tests/run.sh の件数のチェックが合わないときの行（「検査が N 件走った（M 件を期待）」）
DONE = re.compile(r"^\d+ 件(すべて緑|のうち失敗あり)", re.M)   # tests/run.sh が最後まで走ったときだけ出す行


def known_red(text):
    """一覧の本文 → 検査の名前の並び（# で始まる行と空の行は飛ばす）。"""
    return [line.strip() for line in text.splitlines() if line.strip() and not line.lstrip().startswith("#")]


def judge(out, rc, known):
    """(止める理由の並び, 知らせの並び)。out は tests/run.sh の出力、rc はその終わりの値、known は一覧の名前の並び。"""
    fails = FAIL_LINE.findall(out)
    oks = {n for n in OK_LINE.findall(out) if SKIP_MARK not in n}
    stop, notes = [], []
    stop += ["一覧に無い赤: %s" % f for f in fails if f not in known]
    for k in known:
        if k in fails:
            notes.append("一覧に在る赤（止めない）: %s" % k)
        elif k in oks:
            stop.append("一覧に在るのに緑: %s（直したなら tests/land-known-red.txt から消す）" % k)
        else:
            notes.append("一覧に在るが、この回は走らなかった（止めない）: %s" % k)
    odd = len(ANY_FAIL.findall(out)) - len(fails)
    if odd:
        stop.append("名前と食い違いの間に「 — 」の無い赤の行が %d 行（一覧と照合できない。tests/run.sh の出力で「  FAIL 」の行を見る）" % odd)
    tail = " / ".join(out.strip().splitlines()[-3:])
    if COUNT_BAD in out:
        stop.append("件数のチェックが合わない: %s" % next(line for line in out.splitlines() if COUNT_BAD in line).strip())
    elif not DONE.search(out):
        stop.append("tests/run.sh が最後の行を出さずに終わりの値 %d で終わった（途中で落ちて、残りの検査が走っていない）: %s" % (rc, tail))
    elif rc != 0 and not ANY_FAIL.search(out):
        stop.append("tests/run.sh が赤の行を出さずに終わりの値 %d で終わった: %s" % (rc, tail))
    return stop, notes


def main(argv):
    if argv[:1] == ["--judge"] and len(argv) == 3:
        out, rc = pathlib.Path(argv[1]).read_text(encoding="utf-8"), int(argv[2])
    elif not argv:
        env = dict(os.environ, TESTS_LAND="1")
        env.pop("FAIL_ON_SKIP", None)   # CI の設定が継がれると、land の見送りが赤の行の無い失敗になる
        nice = ["nice", "-n", "19"] if shutil.which("nice") else []
        r = subprocess.run(nice + ["bash", str(ROOT / "tests" / "run.sh")], capture_output=True, env=env)
        out, rc = (r.stdout + r.stderr).decode("utf-8", "replace").replace("\r\n", "\n"), r.returncode
    else:
        print(__doc__.split("使い方: ")[1].split("\n終わりの値:")[0].rstrip())
        return 2
    try:
        known = known_red(KNOWN.read_text(encoding="utf-8"))
    except FileNotFoundError:
        known = []   # 一覧が無い: メインブランチに残っている赤が無い形
    stop, notes = judge(out, rc, known)
    for line in notes + stop:
        print(line)
    print("land-check: %s" % ("止める物 %d 件" % len(stop) if stop else "tests/run.sh に、一覧の外の赤は無い"))
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
