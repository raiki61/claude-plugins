#!/usr/bin/env bash
# graphloops の検査。graph の形（graphcheck）と、役の返答を台本で差し替えた端から端までの模擬実行。
# 役割 agent も LLM も使わない——確かめるのは engine・rules・graph の噛み合わせと、記録が
# convergence-loops の検証器を通ること。役の判断の質は実走で見る。
set -uo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY_BIN=$(command -v python3 || command -v python || true)
[ -n "$PY_BIN" ] || { echo "python3 / python が PATH に無い"; exit 2; }

# 走った検査の件数。root の tests/run.sh の EXPECTED_CHECKS と同じ理由で `-ne`——下限（-lt）だと
# 台本を 1 本消しても「0 件失敗」のまま緑で通る（実測: simulate.py から test_light を消しても exit 0）。
# 上げるときも下げるときも実測値を書く。
EXPECTED_CHECKS=220

fail=0
ran=0
for g in research review doctor firstread; do
    v="$ROOT/scripts/$g-record.py"
    # 4 本とも検証器つきで回す。落ちたら理由（NG 行）を出す——検証器なしで回し直して緑にする分岐は
    # 置かない（以前あった review 専用のフォールバックは、欄の突合が落ちた理由を見ずに飲んでいた）。
    if "$PY_BIN" "$ROOT/graphloops/scripts/graphcheck.py" "$ROOT/graphloops/graphs/$g-loop.json" "$v" >/dev/null 2>&1; then
        echo "  ok   graphcheck $g-loop.json"
    else
        echo "  FAIL graphcheck $g-loop.json"
        "$PY_BIN" "$ROOT/graphloops/scripts/graphcheck.py" "$ROOT/graphloops/graphs/$g-loop.json" "$v" 2>&1 | grep '^NG' | head -5
        fail=1
    fi
    ran=$((ran + 1))
done

# 模擬実行は「N 件中 M 件失敗」を最後に出す。件数を拾って合算する（出力が無ければ 0 のまま＝下で赤）。
run_sim() {
    local out n
    out=$("$PY_BIN" "$1" 2>&1)
    local code=$?
    printf '%s\n' "$out"
    n=$(printf '%s\n' "$out" | sed -n 's/^\([0-9][0-9]*\) 件中 [0-9]* 件失敗$/\1/p' | tail -1)
    ran=$((ran + ${n:-0}))
    [ "$code" -eq 0 ] || fail=1
}
run_sim "$ROOT/graphloops/tests/simulate.py"
run_sim "$ROOT/graphloops/tests/simulate_review.py"

if [ "$ran" -ne "$EXPECTED_CHECKS" ]; then
    echo "graphloops: 検査が $ran 件走った（$EXPECTED_CHECKS 件を期待）——台本の空振りか、件数の更新漏れ"
    exit 2
fi
[ "$fail" -eq 0 ] || exit 1
echo "graphloops: $ran 件すべて緑"
