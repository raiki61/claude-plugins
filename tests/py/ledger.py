#!/usr/bin/env python3
"""台帳: tests/run.sh の review-record.py の節の検査（ok 行 1 件）ごとに、移した先の pytest の検査を 1 行で示す。

台本の行は、節（`echo "review-record.py"` から `echo "research-record.py"` の手前まで）を bash に読ませて取る。
expect_output・expect_exit を「引数を書き出すだけ」の関数に差し替え、検証器は起こさない——表のループ（CASES）の
展開も bash 自身がするので、読み違えない。台本の行と表（review_record_cases.CASES）は (終了コード, 期待の文言,
説明文) の多重集合で突き合わせる（同じ説明文の行が 2 つある。集合にすると片方を落としても通る）。

`python3 tests/py/ledger.py` で tests/py/MIGRATION.md の台帳の表を書き直す（表は手で直さない。
test_review_record.py が、表が今の台本と表から作った物と一致することを見る）。
台本の側を消す run では、この道具と、それを見る検査も同じ変更で消す。
"""
import collections
import pathlib
import shutil
import subprocess
import sys

import review_record_cases

HERE = pathlib.Path(__file__).resolve().parent
REPO = HERE.parents[1]
DOC = HERE / "MIGRATION.md"
BEGIN, END = "<!-- ledger:begin -->", "<!-- ledger:end -->"
SECTION = ('echo "review-record.py"', 'echo "research-record.py"')
STUB = r"""set -uo pipefail
ROOT=@ROOT@; WORK=@WORK@; PY_BIN=@PY@
ANY_OUTPUT='__any_output__'
emit() { printf '%s\x1e' "$@"; printf '\x1d'; }
expect_output() { emit "$1" "$2" "$3"; }
expect_exit() { emit "$1" "$ANY_OUTPUT" "$2"; }
write_broken_records() { :; }
echo() { :; }
"""


def script_rows(root=REPO):
    """台本の節の検査を (終了コード, 期待の文言, 説明文) の並びで返す（台本の順）"""
    lines = (root / "tests" / "run.sh").read_text(encoding="utf-8").splitlines()
    try:
        a, b = lines.index(SECTION[0]), lines.index(SECTION[1])
    except ValueError:
        raise SystemExit(f"tests/run.sh に節の境目 {SECTION} が無い——台本の節を動かしたら、この道具も直せ")
    bash = shutil.which("bash") or "bash"
    got = subprocess.run([bash, "-s"], input="\n".join([STUB, *lines[a:b], ""]).encode("utf-8"),
                         capture_output=True, check=True).stdout.decode("utf-8")
    rows = [r.split("\x1e")[:-1] for r in got.split("\x1d") if r]
    return [(int(e), w, d) for e, w, d in rows]


def node(case):
    if case.where == "smoke":
        return "test_review_record.py::test_cli_smoke_deep_nesting"
    return f"test_review_record.py::test_validator[{case.id}]"


def pair(rows, cases=review_record_cases.CASES):
    """台本の行ごとに移した先の node id を付ける ——（[(行, 行き先 か None)], 台本に無い表の行）"""
    left = collections.defaultdict(list)
    for c in cases:
        left[(c.exit, c.want, c.was)].append(c)
    out = [(r, node(left[r].pop(0)) if left[r] else None) for r in rows]
    return out, [c for cs in left.values() for c in cs]


def cell(s):
    return s.replace("|", "\\|").replace("\n", "⏎")


def render(pairs):
    lines = ["| 終了 | 台本の検査（説明文） | 期待の文言 | 移した先 |", "|---|---|---|---|"]
    for (e, w, d), dest in pairs:
        want = "（終了コードだけ）" if w == review_record_cases.ANY else cell(w)
        lines.append(f"| {e} | {cell(d)} | {want} | {dest or '（空欄）'} |")
    return "\n".join(lines)


def block(text):
    a, b = text.index(BEGIN) + len(BEGIN), text.index(END)
    return text[a:b].strip("\n")


def main():
    pairs, extra = pair(script_rows())
    empty = sum(1 for _, d in pairs if d is None)
    text = DOC.read_text(encoding="utf-8")
    a, b = text.index(BEGIN) + len(BEGIN), text.index(END)
    DOC.write_text(text[:a] + "\n" + render(pairs) + "\n" + text[b:], encoding="utf-8")
    print(f"台本の検査 {len(pairs)} 件・空欄 {empty} 件・台本に無い表の行 {len(extra)} 件")
    sys.exit(1 if empty or extra else 0)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    main()
