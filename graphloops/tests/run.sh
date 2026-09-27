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
EXPECTED_CHECKS=2018
# **台本の本数も別に数える。** 件数だけだと、腕を消した編集が『組み替えたため』の説明とともに
# 下がった値で通る（実測 2026-09-19: 読了の台本 1 本が領域の置き換えで消え、645 → 642 の減少が
# 通って覆いが 4 本消えた。次の周の全腕注入で 1 周遅れて露見した）。関数の消滅は件数と別の信号にする
EXPECTED_TESTS=164

fail=0
ran=0
tests=0   # 走った台本の本数（各模擬実行が自分で数えて出す値を足す）
# **組（shard）に分けた回**（CI が GL_SHARD_TOTAL・GL_SHARD_INDEX などを渡す。約束の正本は parallel.py の shard_spec）は、
# 台本を組の分だけ走らせ、下の件数の柵の代わりに件数を名簿に書く。和の検算は CI のまとめの job（parallel.py merge）の 1 か所。
# 指定が無い回（手元の 1 本）は今までどおり全台本を走らせ、ここの柵で突き合わせる
shard=$("$PY_BIN" "$ROOT/graphloops/tests/parallel.py" index) || { echo "graphloops: 組の指定が読めない: $shard"; exit 2; }
shard=${shard%$'\r'}   # Windows の Python の出力の CRLF（残すと組でない回も組 0 でない回も同じ比較で外れる）
# **走査対象はファイル集合から導く。** 名前を手で並べていたとき、5 本目の graph を足してもその 1 本は
# 誰も検査せず、for が回る回数が変わらないので件数の柵（EXPECTED_CHECKS）も発火しなかった
# （実測 2026-09-13: 壊した graph を 5 本目に置いて exit 0・全件緑）。
# graph の形は組 0 だけで見る（どの組でも見ると、和が組の数だけ重なる）
for gf in "$ROOT"/graphloops/graphs/*.json; do
    [ -z "$shard" ] || [ "$shard" = 0 ] || break
    # 検証器は名前の -loop より前で引く（差し替えの版 review-loop-tdd.json も元と同じ review-record.py を使う）
    name="$(basename "$gf")"; g="${name%%-loop*}"
    v="$ROOT/scripts/$g-record.py"
    # 在る graph を全部、検証器つきで回す（本数は上の for が graphs/ から導く——ここに数を書くと、
    # graph を足し引きした周に散文だけが古くなる）。落ちたら理由（NG 行）を出す——検証器なしで回し直して緑にする分岐は
    # 置かない（以前あった review 専用のフォールバックは、欄の突合が落ちた理由を見ずに飲んでいた）。
    if "$PY_BIN" "$ROOT/graphloops/scripts/graphcheck.py" "$gf" "$v" >/dev/null 2>&1; then
        echo "  ok   graphcheck $name"
    else
        echo "  FAIL graphcheck $name"
        "$PY_BIN" "$ROOT/graphloops/scripts/graphcheck.py" "$gf" "$v" 2>&1 | grep '^NG' | head -5
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
    # **台本の本数も、走った側が数えた値を読む**（grep '^def test_' は字面しか見ないので、
    # インデントした・改名した台本が消えても数が合ったままになる）。出力が無ければ 0＝下で赤
    k=$(printf '%s\n' "$out" | sed -n 's/^台本 \([0-9][0-9]*\) 本$/\1/p' | tail -1)
    tests=$((tests + ${k:-0}))
    [ "$code" -eq 0 ] || fail=1
}
# 台本の一覧は 1 か所。**名前を 2 度並べない**——手で並べた一覧は、足した 1 本が片方から黙って落ちる。
# **配列で持ち、展開は引用する**（この事故の正本は root の tests/run.sh の SHELL_QUOTE_OK の注記）
SIMS=("$ROOT/graphloops/tests/simulate.py" "$ROOT/graphloops/tests/simulate_review.py")
for sim in "${SIMS[@]}"; do run_sim "$sim"; done

if [ -n "$shard" ]; then
    [ "$fail" -eq 0 ] || exit 1
    "$PY_BIN" "$ROOT/graphloops/tests/parallel.py" counts --checks "$ran" --tests "$tests" || exit 2
    echo "graphloops: 組 $shard で $ran 件すべて緑（件数と全台本の和で見る検査は CI のまとめの job が検算する）"
    exit 0
fi
if [ "$ran" -ne "$EXPECTED_CHECKS" ]; then
    echo "graphloops: 検査が $ran 件走った（$EXPECTED_CHECKS 件を期待）——台本の空振りか、件数の更新漏れ"
    exit 2
fi
# 台本（def test_*）の本数。**外部コマンドを増やさない**（bc は Windows の CI に無く、空の値で比較が落ちて柵が黙る——
# それはこの差分自身が塞いだ「空振りが見えない柵」そのものだった）。足し算は上の件数と同じ $((…))
if [ "$tests" -ne "$EXPECTED_TESTS" ]; then
    echo "graphloops: 台本が $tests 本（$EXPECTED_TESTS 本を期待）——台本の削除か、本数の更新漏れ"
    exit 2
fi
[ "$fail" -eq 0 ] || exit 1
echo "graphloops: $ran 件すべて緑"
