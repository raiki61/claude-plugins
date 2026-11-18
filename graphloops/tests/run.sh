#!/usr/bin/env bash
# graphloops の検査。graph の形（graphcheck）と、役の返答を台本で差し替えた端から端までの模擬実行。
# 役割 agent も LLM も使わない——確かめるのは engine・rules・graph の噛み合わせと、記録が
# convergence-loops の検証器を通ること。役の判断の質は実走で見る。
#
# graphloops の engine が起動した子（環境に GRAPHLOOPS_ENGINE_CHILD が立つ）からは走らせない——理由と消す時は tests/run.sh の頭の段
if [ -n "${GRAPHLOOPS_ENGINE_CHILD:-}" ]; then
    echo "graphloops/tests/run.sh: engine が起動した子からは走らせない（人の方針: 手元で e2e の一式を回さない。CI で回る）——手元は pytest の一式か、変更に関わる筋書きを GL_TEST_ONLY で数件" >&2
    exit 2
fi
set -uo pipefail
# 止める猶予の環境変数（graphloops/engine/role_run.py の GRACE_ENV）は外して走る——外の土台の下で engine がこの一式を
# 走らせると値を継ぎ、既定の 5 秒を前提に子を止める検査がその下でだけ崩れる（読めない値なら engine の import で全部落ちる）
unset GL_KILL_GRACE
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
PY_BIN=$(command -v python3 || command -v python || true)
[ -n "$PY_BIN" ] || { echo "python3 / python が PATH に無い"; exit 2; }

# **件数の定数は持たない**（走った検査の数・台本の本数を手で書いて突き合わせる形は 2026-11-18 にやめた。持ち主の決め。
# docs/reform/ledger.md）。消した本人が同じ commit で数を下げれば通るので、わざと消した台本は止められなかった。
# 代わりに、各台本が最後まで走ったか（終わりの行「N 件中 M 件失敗」と「台本 N 本」を出したか）を見て、出さずに終われば赤にする。
# 消えた台本は止めずに見えるようにする（ルートの tests/removed-tests.py が、ブランチが消した def test_ を一覧にする）

fail=0
ran=0
tests=0   # 走った台本の本数（各模擬実行が自分で数えて出す値を足す）
# **組（shard）に分けた回**（CI が GL_SHARD_TOTAL・GL_SHARD_INDEX などを渡す。約束の正本は parallel.py の shard_spec）は、
# 台本を組の分だけ走らせ、件数と走らせた台本の名前を名簿に書く。全台本が 1 回ずつ走ったかの検算は CI のまとめの job（parallel.py merge）の
# 1 か所。指定が無い回（手元の 1 本）は今までどおり全台本を走らせる
shard=$("$PY_BIN" "$ROOT/graphloops/tests/parallel.py" index) || { echo "graphloops: 組の指定が読めない: $shard"; exit 2; }
shard=${shard%$'\r'}   # Windows の Python の出力の CRLF（残すと組でない回と組 0 の回で比較が外れ、graph の検査を飛ばす）
# **走査対象はファイル集合から導く。** 名前を手で並べていたとき、5 本目の graph を足してもその 1 本は
# 誰も検査せず、for が回る回数が変わらないので走った件数を見ても誰も気づかなかった
# （実測 2026-09-13: 壊した graph を 5 本目に置いて exit 0・全件緑）。
# graph の形は組 0 だけで見る（どの組でも見ると、和が組の数だけ重なる）
for gf in "$ROOT"/graphloops/graphs/*.json; do
    [ -z "$shard" ] || [ "$shard" = 0 ] || break
    # 検証器は名前の -loop より前で引く（差し替えの版 review-loop-tdd.json も元と同じ review-record.py を使う）
    name="$(basename "$gf")"; g="${name%%-loop*}"
    v="$ROOT/convergence-loops/scripts/$g-record.py"
    # 在る graph を全部、検証器つきで回す（本数は上の for が graphs/ から導く——ここに数を書くと、
    # graph を足し引きした周に散文だけが古くなる）。落ちたら理由（NG 行）を出す——検証器なしで回し直して緑にする分岐は
    # 置かない（以前あった review 専用のフォールバックは、フィールドの突合が落ちた理由を見ずに飲んでいた）。
    if "$PY_BIN" "$ROOT/graphloops/scripts/graphcheck.py" "$gf" "$v" >/dev/null 2>&1; then
        echo "  ok   graphcheck $name"
    else
        echo "  FAIL graphcheck $name"
        "$PY_BIN" "$ROOT/graphloops/scripts/graphcheck.py" "$gf" "$v" 2>&1 | grep '^NG' | head -5
        fail=1
    fi
    ran=$((ran + 1))
done

# 模擬実行は最後に「台本 N 本」と「N 件中 M 件失敗」を出す（終わりの印）。件数を拾って合算する。
# **終わりの印を出さずに終わった台本は、終わりの値が 0 でも赤**——途中で抜けた（os._exit・握り潰した例外・
# 最後まで届かない sys.exit(0)）台本の残りの検査が、走らないまま緑に見えないようにする
run_sim() {
    local out n k
    out=$("$PY_BIN" "$1" 2>&1)
    local code=$?
    printf '%s\n' "$out"
    n=$(printf '%s\n' "$out" | sed -n 's/^\([0-9][0-9]*\) 件中 [0-9]* 件失敗$/\1/p' | tail -1)
    # **台本の本数は、走った側が数えた値を読む**（grep '^def test_' は字面しか見ない）
    k=$(printf '%s\n' "$out" | sed -n 's/^台本 \([0-9][0-9]*\) 本$/\1/p' | tail -1)
    if [ -z "$n" ] || [ -z "$k" ] || [ "$k" -eq 0 ]; then
        echo "  FAIL $(basename "$1") が終わりの行（「台本 N 本」と「N 件中 M 件失敗」。N は 1 以上）を出さずに終わった（終わりの値 $code）——途中で抜けて、残りの検査が走っていない"
        fail=1
    fi
    ran=$((ran + ${n:-0}))
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
    echo "graphloops: 組 $shard で $ran 件すべて緑（全台本が 1 回ずつ走ったかと、全台本の和で見る検査は CI のまとめの job が検算する）"
    exit 0
fi
[ "$fail" -eq 0 ] || exit 1
echo "graphloops: $ran 件すべて緑（台本 $tests 本）"
