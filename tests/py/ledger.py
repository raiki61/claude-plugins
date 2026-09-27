#!/usr/bin/env python3
"""台帳: tests/run.sh の review-record.py の節の検査（ok 行 1 件）ごとに、移した先の pytest の検査を 1 行で示す。

台本の行は、節（`echo "review-record.py"` から `echo "research-record.py"` の手前まで）を bash に読ませて取る。
expect_output・expect_exit を「引数を書き出すだけ」の関数に差し替え、検証器は起こさない——表のループ（CASES）の
展開も bash 自身がするので、読み違えない。行き先は pytest が集めたテストの node id（rootdir は tests/py）と照らす。

`python3 tests/py/ledger.py` で tests/py/MIGRATION.md の台帳の表を書き直す（表は手で直さない）。
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
# ran を 0 のまま見るのは、expect_output を通らずに手で数える検査（ここの読み取りが拾わない形）を止めるため
STUB = r"""set -uo pipefail
ROOT=@ROOT@; WORK=@WORK@; PY_BIN=@PY@
fail=0 ran=0
ANY_OUTPUT='__any_output__'
emit() { printf '%s\x1e' "$@"; printf '\x1d'; }
expect_output() { emit "$@"; }
expect_exit() { emit "$1" "$ANY_OUTPUT" "${@:2}"; }
write_broken_records() { :; }
echo() { :; }
"""
VALIDATOR = "@ROOT@/scripts/review-record.py"
Row = collections.namedtuple("Row", "exit want was args")


def args_of(argv):
    if list(argv[:2]) != ["@PY@", VALIDATOR]:
        raise SystemExit(f"台本の節の検査が検証器を \"$PY_BIN\" \"$RECORD\" で起こしていない: {argv}")
    out = []
    for a in argv[2:]:
        for mark, to in (("@WORK@/", ""), ("@ROOT@/", "repo:")):
            if a.startswith(mark):
                out.append(to + a[len(mark):])
                break
        else:
            raise SystemExit(f"台本の節の検査の引数が $WORK/ でも $ROOT/ でもない: {a!r}（{argv}）")
    return tuple(out)


def bounds(lines):
    try:
        a, b = lines.index(SECTION[0]), lines.index(SECTION[1])
    except ValueError:
        a = b = None
    if a is None or b < a:
        raise SystemExit(f"tests/run.sh に節の境目 {SECTION} がこの順で無い——台本の節を動かしたら、この道具も直せ")
    return a, b


def script_rows(root=REPO):
    """台本の節の検査を Row の並びで返す（台本の順）"""
    lines = (root / "tests" / "run.sh").read_text(encoding="utf-8").splitlines()
    a, b = bounds(lines)
    bash = shutil.which("bash") or "bash"
    got = subprocess.run([bash, "-s"], input="\n".join([STUB, *lines[a:b], "printf '\\x1c%s' \"$ran\"", ""]).encode("utf-8"),
                         capture_output=True)
    out, err = got.stdout.decode("utf-8"), got.stderr.decode("utf-8", "replace")
    body, sep, ran = out.rpartition("\x1c")
    if got.returncode != 0 or err or not sep:
        raise SystemExit(f"台本の節を読み切れない（終了 {got.returncode}。STUB に無い関数・未定義の変数か）: {err[-2000:]}")
    if ran != "0":
        raise SystemExit(f"台本の節に expect_output・expect_exit を通らない検査が在る（ran={ran}）——台帳が拾えない")
    rows = [r.split("\x1e")[:-1] for r in body.split("\x1d") if r]
    return [Row(int(e), w, d, args_of(argv)) for e, w, d, *argv in rows]


def collected(here=HERE):
    """pytest が集めたテストの node id の集合（rootdir は here の pytest.ini）"""
    got = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider", str(here)],
                         cwd=here, capture_output=True)
    out = got.stdout.decode("utf-8", "replace")
    if got.returncode != 0:
        raise SystemExit(f"テストを集められない（終了 {got.returncode}。件数の柵 EXPECTED_ITEMS の更新漏れもここに出る）: "
                         f"{out[-2000:]}{got.stderr.decode('utf-8', 'replace')[-2000:]}")
    return {line for line in out.splitlines() if "::" in line}


def node(case):
    # 未知の where も test_validator に落とす。そこには集まらないので stray が拾う
    return f"test_review_record.py::{'test_validator_in_child' if case.where == 'smoke' else 'test_validator'}[{case.id}]"


def row_of(case):
    return Row(case.exit, case.want, case.was, tuple(case.args))


def pair(rows, cases=review_record_cases.CASES):
    """台本の行ごとに移した先の node id を付ける ——（[(行, 行き先 か None)], 台本に無い表の行）"""
    left = collections.defaultdict(list)
    for c in cases:
        left[row_of(c)].append(c)
    out = [(r, node(left[r].pop(0)) if left[r] else None) for r in rows]
    return out, [c for cs in left.values() for c in cs]


def stray(pairs, ids):
    """行き先が無い・集めたテスト（ids）に無い・ほかの行と重なる行"""
    seen = collections.Counter(d for _, d in pairs)
    return [(r, d) for r, d in pairs if d not in ids or seen[d] > 1]


def cell(s):
    return s.replace("|", "\\|").replace("\n", "⏎")


def render(pairs):
    lines = ["| 終了 | 台本の検査（説明文） | 期待の文言 | 読む記録 | 移した先 |", "|---|---|---|---|---|"]
    for r, dest in pairs:
        want = "（終了コードだけ）" if r.want == review_record_cases.ANY else cell(r.want)
        args = " ".join(r.args) or "（引数なし）"
        lines.append(f"| {r.exit} | {cell(r.was)} | {want} | {cell(args)} | {dest or '（空欄）'} |")
    return "\n".join(lines)


def block(text):
    a, b = text.index(BEGIN) + len(BEGIN), text.index(END)
    return text[a:b].strip("\n")


def main():
    pairs, extra = pair(script_rows())
    bad = stray(pairs, collected())
    text = DOC.read_text(encoding="utf-8")
    a, b = text.index(BEGIN) + len(BEGIN), text.index(END)
    DOC.write_text(text[:a] + "\n" + render(pairs) + "\n" + text[b:], encoding="utf-8")
    print(f"台本の検査 {len(pairs)} 件・行き先が無いか集めたテストに無いか重なる {len(bad)} 件・台本に無い表の行 {len(extra)} 件")
    sys.exit(1 if bad or extra else 0)


if __name__ == "__main__":
    for _s in (sys.stdout, sys.stderr):
        if hasattr(_s, "reconfigure"):
            _s.reconfigure(encoding="utf-8")
    main()
