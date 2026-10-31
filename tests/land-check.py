#!/usr/bin/env python3
"""メインブランチに入れるゲート（.claude/company.toml の [land] の check）から、ルートの tests/run.sh を回す。

tests/run.sh を TESTS_LAND=1 で回し（graphloops の模擬実行の 1 件だけを見送る）、赤の検査の名前を
tests/land-known-red.txt と照合する。

回すのは、この変更が入力に当たる検査だけ（持ち主 2026-10-20「変えたところだけにします」。受付 de7a5b）。メインブランチ（origin/main）との
分かれ目から変わったファイル（作業ツリーまで）を取り、変わったプラグイン（頭のディレクトリに .claude-plugin/plugin.json が在る物）と、それに
plugin.json の dependencies で依存するプラグインを、変わったプラグインに数える（Nx の affected と同じ形。https://nx.dev/ci/features/affected ）。
tests/run.sh の検査のうち scope で入力を宣言した物は、宣言したプラグインがどれも変わっておらず、宣言したパスの頭に当たる
変わったファイルも無ければ、走らせずに見送る（scope の無い検査は毎回回す）。tests/run.sh 自身が変わった回と、分かれ目を
取れない回は全部を回す。見送った検査は main に入った後の CI が回す（決まった時刻に走る実行は置かない。持ち主は cron などの
定期の起動を置かない）。全部を回したいときは TESTS_LAND_ALL=1 を付ける。直す前は全部で 24 分 12 秒（2026-10-20、負荷 10〜37 の機械）。
どのテストをどこで回すかの決めは docs/adr/0076-land-runs-affected-tests.md。

止めた赤の検査ごとに、中で落ちたテストの名前（unittest・pytest・中の台本の赤）を「落ちた: <検査> ← <テスト>」の 1 行で、
終わり近く（後ろは見送った件数・かかった時間・最後の行だけ）に出す。--land は検査の出力の末尾 20 行だけを部署に渡すので、名前がそこに入るようにする（2026-10-20 は出なかった）。
かかった時間と終わりの load average も出す。

止めるのは次の場合。
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
        python3 tests/land-check.py --affected [<分かれ目の rev>]   回す範囲を出すだけ（rev の既定は origin/main との分かれ目）
終わりの値: 0 は止める物が無い、1 は止める物が在る、2 は使い方の誤り。
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import time

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
RUN_ALL = ("tests/run.sh",)   # 変われば全部を回すファイル（全部の検査の定義と scope の宣言を持つ）
SCOPE_SKIP = " # SKIP unchanged:"   # tests/run.sh が入力の変わっていない検査の「  ok   」の行に出す見送りの印


def plugins(root):
    """プラグインの名前 → plugin.json の dependencies のうち、このリポジトリのプラグインの名前の並び。"""
    out = {}
    for pj in sorted(root.glob("*/.claude-plugin/plugin.json")):
        deps = json.loads(pj.read_text(encoding="utf-8")).get("dependencies") or []
        out[pj.parent.parent.name] = [d["name"] if isinstance(d, dict) else d for d in deps]
    return out


def affected(changed, graph):
    """(変わったファイルの並び, plugins() の形) → 変わったプラグインの組（依存する側まで足す）。全部を回す回は None。"""
    if any(c in RUN_ALL for c in changed):
        return None
    hit = {c.split("/", 1)[0] for c in changed if "/" in c}   # 今の木に無い頭（消したプラグイン）も、依存する側を足すために残す
    grew = True
    while grew:   # 依存する側を足す（依存の依存も）
        more = {p for p, deps in graph.items() if hit & set(deps)} - hit
        hit |= more
        grew = bool(more)
    return hit & set(graph)


def changed_files(root, base=None):
    """メインブランチとの分かれ目から作業ツリーまでに変わったファイル（未追跡を含む）の並び。分かれ目を取れなければ None。
    --land は未コミットの変更の無い場所で回すが、手元で打つと tests/run.sh は作業ツリーの中身で走るので、作業ツリーまでを取る。"""
    git = lambda *a: subprocess.run(["git", "-C", str(root)] + list(a), capture_output=True, text=True, encoding="utf-8")
    if base is None:
        r = git("merge-base", "HEAD", "refs/remotes/origin/main")
        if r.returncode != 0:
            return None
        base = r.stdout.strip()
    r = git("diff", "--name-only", "--no-renames", "-z", base)
    u = git("ls-files", "--others", "--exclude-standard", "-z")
    if r.returncode != 0 or u.returncode != 0:
        return None
    return sorted({c for c in (r.stdout + "\0" + u.stdout).split("\0") if c})


def scope_env(root, base=None):
    """tests/run.sh に渡す環境変数（全部を回す回は空）と、範囲の 1 行の説明。"""
    if os.environ.get("TESTS_LAND_ALL") == "1":
        return {}, "全部を回す（TESTS_LAND_ALL=1）"
    changed = changed_files(root, base)
    if changed is None:
        return {}, "全部を回す（メインブランチとの分かれ目を取れない）"
    hit = affected(changed, plugins(root))
    if hit is None:
        return {}, "全部を回す（%s が変わった）" % " ".join(c for c in changed if c in RUN_ALL)
    return ({"TESTS_AFFECTED": " ".join(sorted(hit)), "TESTS_CHANGED": "\n".join(changed)},
            "変わったファイル %d 本・変わったプラグイン（依存する側を含む）: %s" % (len(changed), " ".join(sorted(hit)) or "無し"))


INNER = (re.compile(r"^(?:FAIL|ERROR): (\S+) \(([^)\s]+)\)", re.M),   # unittest の赤（名前と、モジュール.クラス。3.11 からはその後ろに .名前）
         re.compile(r"^(?:FAIL|ERROR): (\S+)$", re.M),                    # works-dispatch/dispatch/tests/parallel.py の赤（試験の id だけ）
         re.compile(r"^(?:FAILED|ERROR) (\S+::\S+)", re.M),             # pytest の -r の要約の行
         re.compile(r"^\s*FAIL (.+?) — ", re.M))                          # 中で回した別の台本（tests/run.sh の形）の赤の行
NAMES_SHOWN, NAMES_CHARS = 8, 400   # 1 つの赤の検査の中の落ちたテストの名前を出す上限（--land は出力の末尾 20 行だけを部署に渡す）


def inner_fails(out, name):
    """tests/run.sh の赤の検査 name の、捕った出力（赤の行の次から、次の検査の行の前まで）から、中で落ちたテストの名前を拾う。
    unittest・pytest・台本の赤の行が無ければ、最初の AssertionError か Error の行を 1 つ返す（Python のその場の検査の多くはこれで落ちる）。"""
    lines = out.splitlines()
    try:
        at = next(i for i, l in enumerate(lines) if l.startswith("  FAIL %s — " % name))
    except StopIteration:
        return []
    block = []
    for l in lines[at + 1:]:
        if l.startswith(("  ok   ", "  FAIL ")) or DONE.match(l):
            break
        block.append(l)
    text = "\n".join(block)
    names = []
    for i, pat in enumerate(INNER):
        for m in pat.finditer(text):
            n = m.group(1)
            if i == 0:   # 名前と（モジュール.クラス）の形
                n = m.group(2) if m.group(2).endswith("." + n) else "%s.%s" % (m.group(2), n)
            if n not in names:
                names.append(n)
    if not names:   # その場の検査の多くは「NG …」の行か、最後の AssertionError などの行で落ちる
        names = ([l.strip()[:200] for l in block if l.lstrip().startswith("NG ")][:2]
                 or [l.strip()[:200] for l in block if re.match(r"\s*\w*(Error|Exception)\b", l)][-1:])
    if not names:   # どの形でも無い赤（台本の訳の行だけを出す検査）は、捕った出力の頭の 2 行を出す
        names = [l.strip()[:200] for l in block if l.strip()][:2]
    return names


def show_fails(out, names):
    """赤の検査ごとに 1 行（「落ちた: <検査> ← <中の落ちたテスト>」）。--land が渡す末尾に収まるよう、名前の数と字数を切る。"""
    rows = []
    for f in names:
        inner = inner_fails(out, f)
        tail = ""
        if inner:
            tail = " ← " + ", ".join(inner[:NAMES_SHOWN]) + (" ほか %d 件" % (len(inner) - NAMES_SHOWN) if len(inner) > NAMES_SHOWN else "")
        rows.append(("落ちた: %s%s" % (f, tail))[:NAMES_CHARS])
    return rows


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
    started, ran = time.monotonic(), not argv
    if argv[:1] == ["--judge"] and len(argv) == 3:
        out, rc = pathlib.Path(argv[1]).read_text(encoding="utf-8"), int(argv[2])
    elif argv[:1] == ["--affected"] and len(argv) <= 2:
        print(scope_env(ROOT, argv[1] if len(argv) == 2 else None)[1])
        return 0
    elif not argv:
        extra, said = scope_env(ROOT)
        print("land-check: " + said)
        env = dict(os.environ, TESTS_LAND="1", **extra)
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
    for line in show_fails(out, [f for f in FAIL_LINE.findall(out) if f not in known]):
        print(line)   # 止める物の後ろ、最後の行の前に置く（--land は出力の末尾 20 行を部署に渡す）
    skipped = sum(1 for n in OK_LINE.findall(out) if SCOPE_SKIP in n)   # 見送りの一覧（report_skips）の行は数えない
    if skipped:
        print("land-check: 入力の変わっていない検査 %d 件を見送った（main に入った後の CI が回す）" % skipped)
    if ran:
        spent = int(time.monotonic() - started)
        load = " ".join("%.1f" % x for x in os.getloadavg()) if hasattr(os, "getloadavg") else "取れない"
        print("land-check: %d 分 %d 秒かかった（終わりの load average %s）" % (spent // 60, spent % 60, load))
    print("land-check: %s" % ("止める物 %d 件" % len(stop) if stop else "tests/run.sh に、一覧の外の赤は無い"))
    return 1 if stop else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
