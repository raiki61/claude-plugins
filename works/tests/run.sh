#!/bin/sh
# works のテストの入口。sh works/tests/run.sh [unittest の引数（-k など）]
# WORKS_TESTS で段を選ぶ: 空（既定）= 全部・fast = 速い段・heavy = 重い段。段の一覧は tests/tiers.py。
# 全部と heavy は、機械全体で重いテストを同時に 4 本までにする枠の台本（testslot.sh。置き場は WORKS_TESTSLOT で差し替え）を
# 通して回す。枠の置き場は台本の約束 TESTSLOT_DIR（既定は台本と同じ /private/tmp/claude-<uid>/testslots）で、ここで解決して台本へ渡す。
# 台本が無い・枠の置き場に書けないときは、1 行出して枠を取らずに回す。枠を持つ台本の下から呼ばれたら取り直さない。
cd "$(dirname "$0")/.." || exit 2
DEFAULT_TESTSLOT=/Users/p03623/src/claude-plugins/.git/graphloops/ops/testslot.sh

tier=${WORKS_TESTS-}
case $tier in
  "") set -- -m unittest discover -s tests -p 'test_*.py' "$@" ;;
  fast|heavy) set -- tests/tiers.py "$tier" "$@" ;;
  *) echo "run.sh: WORKS_TESTS は fast・heavy・空（全部）のどれか（今の値: ${tier}）" >&2; exit 2 ;;
esac
set -- uv run --no-project --with pyyaml python3 "$@"
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE
[ "$tier" = fast ] && exec "$@"

# 祖先のプロセスが枠を持っているか（枠の中の pid は、枠を取った台本の pid）
held_by_ancestor() {
  p=$$
  while [ -n "$p" ] && [ "$p" -gt 1 ]; do
    for f in "$1"/slot-*/pid; do
      [ -f "$f" ] && [ "$(cat "$f" 2>/dev/null)" = "$p" ] && return 0
    done
    p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
  done
  return 1
}

slot=${WORKS_TESTSLOT-$DEFAULT_TESTSLOT}
if [ ! -f "$slot" ]; then
  echo "run.sh: 重いテストの枠の台本が無い（${slot}）。枠を取らずに回す" >&2
  exec "$@"
fi
# 置き場は台本と同じ式で 1 回だけ解決し、export して台本に渡す（試す場所・祖先を探す場所・台本が枠を取る場所を一致させる）
slots=${TESTSLOT_DIR:-/private/tmp/claude-$(id -u)/testslots}
TESTSLOT_DIR=$slots
export TESTSLOT_DIR
if held_by_ancestor "$slots"; then
  exec "$@"
fi
# 台本は枠を mkdir で取り、取れなければ期限なしで待つ。書けない置き場（サンドボックスの中など）では永久に待つので、先に試す
probe="$slots/.probe-run-sh-$$"
if ! { mkdir -p "$slots" 2>/dev/null && mkdir "$probe" 2>/dev/null && rmdir "$probe"; }; then
  echo "run.sh: 重いテストの枠の置き場に書けない（${slots}）。枠を取らずに回す" >&2
  exec "$@"
fi
TESTSLOT_N=4   # 数える枠の数は mainline と同じでなければならない（違うと同時の本数が数え違う）
export TESTSLOT_N
exec bash "$slot" "$@"
