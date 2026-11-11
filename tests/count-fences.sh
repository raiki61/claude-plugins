#!/usr/bin/env bash
# 試験の件数の照合だけを、試験を走らせずに確かめる（メインブランチに入れるコマンドのゲートから回す。全部で 10 秒ほど）。
# チェック: ルートの tests/run.sh の EXPECTED_CHECKS（数えるだけの回 TESTS_COUNT_ONLY=1 で数える）と、pytest の置き場の EXPECTED_ITEMS
# （graphloops/tests/py と tests/py。集めるだけの回 --collect-only で、fence.py が集めた数を突き合わせる）。
# 検査を足して件数の基準を上げ忘れた変更が、メインブランチに入った後の CI で初めて赤になる形が、別々の部署で 3 件続いた（2026-10-16）。
# 終わりの値: 0 は全部の件数が合う、1 は合わない件数が在る、2 は数えられない（pytest が無いなど）。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PY_BIN=$(command -v python3 || command -v python || true)
[ -n "$PY_BIN" ] || { echo "count-fences: python3 / python が PATH に無い"; exit 2; }
# PATH の python3 に pytest が無ければ、uv の一時の環境（版は CI の pytest の job と .review-checks.json と同じ 9.1.1）で自分を起動し直す。
# uv run は一時の環境の bin を PATH の先頭に置くので、起動し直した回の python3 は pytest を持つ。手元の /usr/bin/python3 は
# pip の無い EXTERNALLY-MANAGED で、部署の --land が毎回ここで止まっていた（頼み c6a379）。COUNT_FENCES_UV は起動し直しを 1 回に限る印
if ! "$PY_BIN" -c 'import pytest' 2>/dev/null; then
    # 先に入るかだけを試す（入らない回の uv の終わりの値を、件数の合わない 1 と取り違えさせない）
    UV_RUN=(uv run --no-project --quiet --with pytest==9.1.1)
    if [ -z "${COUNT_FENCES_UV:-}" ] && command -v uv >/dev/null 2>&1 && "${UV_RUN[@]}" python3 -c 'import pytest'; then
        COUNT_FENCES_UV=1 exec "${UV_RUN[@]}" bash "$0" "$@"
    fi
    echo "count-fences: $PY_BIN に pytest が無く、uv も無いか uv の環境でも入らなかった（pytest の置き場の件数を数えられない。入れ方は CONTRIBUTING.md の uv run の行か CI の設定の pytest の job）"
    exit 2
fi
rc=0
out=$(TESTS_COUNT_ONLY=1 bash "$ROOT/tests/run.sh" 2>&1)
if [[ "$out" == *COUNT_ONLY_MATCH* ]]; then
    echo "ok   tests/run.sh の件数のチェック"
else
    echo "NG   tests/run.sh の件数のチェック: $(printf '%s\n' "$out" | grep -m1 '件を期待' || printf '%s\n' "$out" | tail -n 3)"
    rc=1
fi
for dir in graphloops/tests/py tests/py; do
    out=$(cd "$ROOT" && "$PY_BIN" -m pytest --collect-only -q -p no:cacheprovider "$dir" 2>&1)
    if [ $? -eq 0 ]; then
        echo "ok   $dir の件数のチェック（$(printf '%s\n' "$out" | tail -n 1)）"
    else
        echo "NG   $dir の件数のチェック: $(printf '%s\n' "$out" | grep -m1 '件を期待' || printf '%s\n' "$out" | tail -n 3)"
        rc=1
    fi
done
exit "$rc"
