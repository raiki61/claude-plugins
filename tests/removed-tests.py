#!/usr/bin/env python3
"""ブランチが消した試験の一覧を出す。止めない（終わりの値はいつも 0）——消したことを見えるようにするだけ。

試験の件数の定数（tests/run.sh の EXPECTED_CHECKS・pytest の置き場の EXPECTED_ITEMS など）で「試験が消えた」を止める形は
2026-11-18 にやめた（持ち主の決め。docs/reform/ledger.md）。消した本人が同じ commit で数を下げれば通るので、わざと消した試験は
止められず、試験を足すたびの数の直しと、並行の部署どうしの衝突だけが残った。代わりに、消えた試験を名前で並べて人と照合役に見せる。

比べるのは、origin/main との分かれ目（git merge-base）の版と、今の作業ツリー（commit していない変更も入る）。見るのは分かれ目から
変わった .py と .sh だけ:
- .py は def test_*（pytest・unittest・graphloops の台本）
- .sh は expect_output の 3 つ目の引数と expect_exit の 2 つ目の引数（検査の説明。ルートの tests/run.sh の形）。行末のバックスラッシュで
  折り返した行はつないでから、shell と同じ引用の規則（shlex）で引数に分ける
ファイルの中で消えた名前のうち、変わったほかのファイルに新しく現れた名前は、移しただけと見なして出さない。説明を書き換えた検査は、
消えた側に出る（書き換えたのか消したのかは、読む人が差分で見分ける）。
見ないもの: 台本の中の check の 1 件・parametrize の 1 行（名前の単位でなく、行の単位の消し方は差分で読む）。
移したと見なすのは名前だけで決めるので、変わったほかのファイルが同じ名前の試験を足すと、消えた側に出ない。

使い方: python3 tests/removed-tests.py [<分かれ目の rev>]   （rev の既定は origin/main との分かれ目）
読む人: main へ入れるゲート（scripts/light-check.sh が回す）・納品の前の部署（一覧を要約の決め手に書く。ルートの CLAUDE.md の「試験」）
"""
import pathlib
import re
import shlex
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
PY_TEST = re.compile(r"^\s*(?:async\s+)?def\s+(test_\w+)\s*\(", re.M)
SH_ARG = {"expect_output": 3, "expect_exit": 2}   # 検査の説明が何番目の語か（0 番目は関数の名前）


def git(*args):
    return subprocess.run(["git", "-c", "core.quotepath=false", *args], cwd=ROOT, capture_output=True, text=True, encoding="utf-8", errors="replace")


def names(path, text):
    """ファイルの本文から試験の名前の集合を取る（形の分からないファイルは空）"""
    if path.endswith(".py"):
        return set(PY_TEST.findall(text))
    if path.endswith(".sh"):
        out = set()
        for line in re.sub(r"\\\r?\n", " ", text).splitlines():
            head = line.split(None, 1)
            if not head or head[0] not in SH_ARG:
                continue
            # 要る語の数だけ読む——説明より後の引数は次の行へ続く引用（python3 -c "…" など）でもよい
            lex = shlex.shlex(line, posix=True)
            lex.whitespace_split = True
            words = []
            try:
                while len(words) <= SH_ARG[head[0]]:
                    w = lex.get_token()
                    if w is None:
                        break
                    words.append(w)
            except ValueError:   # 説明までの引用が閉じない行は試験の行でない
                continue
            if len(words) > SH_ARG[head[0]]:
                out.add(words[SH_ARG[head[0]]])
        return out
    return set()


def removed(base):
    """[(パス, 名前)]。base の版にあって今の作業ツリーで消えた試験（移しただけの物を除く）"""
    diff = git("diff", "--name-only", "--no-renames", base, "--", "*.py", "*.sh")
    if diff.returncode != 0:
        raise RuntimeError(diff.stderr.strip())
    before, after = {}, {}
    for path in diff.stdout.splitlines():
        old = git("show", f"{base}:{path}")
        before[path] = names(path, old.stdout) if old.returncode == 0 else set()
        now = ROOT / path
        after[path] = names(path, now.read_text(encoding="utf-8", errors="replace")) if now.is_file() else set()
    moved_in = set().union(*(after[p] - before[p] for p in after)) if after else set()
    return sorted((p, n) for p in before for n in before[p] - after[p] if n not in moved_in)


def main(argv):
    if len(argv) > 1:
        print("使い方: python3 tests/removed-tests.py [<分かれ目の rev>]")
        return 0
    if argv:
        base = argv[0]
    else:
        mb = git("merge-base", "HEAD", "origin/main")
        if mb.returncode != 0:
            print("removed-tests: origin/main との分かれ目が取れないので、消えた試験を数えなかった（" + mb.stderr.strip() + "）")
            return 0
        base = mb.stdout.strip()
    try:
        gone = removed(base)
    except RuntimeError as e:
        print(f"removed-tests: {base} との差分が取れないので、消えた試験を数えなかった（{e}）")
        return 0
    if not gone:
        print(f"removed-tests: 消えた試験は無い（{base[:7]} から）")
        return 0
    print(f"removed-tests: 消えた試験 {len(gone)} 件（{base[:7]} から。止めない——意図どおりなら、納品の要約の決め手に一覧を書く）:")
    for path, name in gone:
        print(f"  {path}: {name}")
    return 0


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    raise SystemExit(main(sys.argv[1:]))
