#!/usr/bin/env bash
# 試験の件数の柵だけを、試験を走らせずに確かめる（本流に入れる命令の関門から回す。全部で 10 秒ほど）。
# 柵: 根の tests/run.sh の EXPECTED_CHECKS（数えるだけの回 TESTS_COUNT_ONLY=1 で数える）と、pytest の置き場の EXPECTED_ITEMS
# （graphloops/tests/py と tests/py。集めるだけの回 --collect-only で、fence.py が集めた数を突き合わせる）。
# 検査を足して柵を上げ忘れた変更が、本流に入った後の CI で初めて赤になる形が、別々の部署で 3 件続いた（2026-10-16）。
# 終わりの値: 0 は全部の柵が合う、1 は合わない柵が在る、2 は数えられない（pytest が無いなど）。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY_BIN=$(command -v python3 || command -v python || true)
[ -n "$PY_BIN" ] || { echo "count-fences: python3 / python が PATH に無い"; exit 2; }
"$PY_BIN" -c 'import pytest' 2>/dev/null || {
    echo "count-fences: $PY_BIN に pytest が無い（pytest の置き場の件数を数えられない。入れ方は graphloops/tests/py の README か CI の設定の pytest の job）"
    exit 2
}
rc=0
out=$(TESTS_COUNT_ONLY=1 bash "$ROOT/tests/run.sh" 2>&1)
if [[ "$out" == *COUNT_ONLY_MATCH* ]]; then
    echo "ok   tests/run.sh の件数の柵"
else
    echo "NG   tests/run.sh の件数の柵: $(printf '%s\n' "$out" | grep -m1 '件を期待' || printf '%s\n' "$out" | tail -n 3)"
    rc=1
fi
for dir in graphloops/tests/py tests/py; do
    out=$(cd "$ROOT" && "$PY_BIN" -m pytest --collect-only -q -p no:cacheprovider "$dir" 2>&1)
    if [ $? -eq 0 ]; then
        echo "ok   $dir の件数の柵（$(printf '%s\n' "$out" | tail -n 1)）"
    else
        echo "NG   $dir の件数の柵: $(printf '%s\n' "$out" | grep -m1 '件を期待' || printf '%s\n' "$out" | tail -n 3)"
        rc=1
    fi
done
exit "$rc"
