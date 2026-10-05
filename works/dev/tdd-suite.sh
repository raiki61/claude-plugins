#!/bin/sh
# works/dev/tdd-suite.sh <JUnit XML の書き先> [pytest の引数…]
#
# TDD の実行器（ラインの入力 tdd_suite に渡す殻。仕様 tdd-spec 6 節）。works の試験を既製の pytest で走らせ、テスト 1 件ごとの
# 結末を pytest の --junitxml で書く（JUnit を自作しない。pytest は今の unittest の試験をそのまま拾う）。
# 段は WORKS_TDD_TIER（fast が既定・heavy）。段のファイルは tests/tiers.py の paths の口から引く（一覧を写さない）。
# 後ろの引数は pytest に足す（試験の根ごとの分け方は下）: 段の外の試験のファイル・node id（`<パス>::<クラス>::<名前>`）は集める先に足し、-k は集めた中を
# 絞る。書き先と、呼ぶ側の cwd から在るパス（node id は :: の前）の相対パスは呼ぶ側の cwd から解く（pytest は works で起こす）。
# 試験の根（パスから上へ辿って最初に conftest.py が在る置き場。辿り着かなければ works の根）が違う名指しは、1 つのプロセスに 2 つの
# engine を載せないよう根ごとに別の pytest で流し（works の根を先に）、根ごとの JUnit は junitparser merge で書き先の 1 つに合わせる。
# TDD_SUITE_ONLY=1 で起こされたら（TDD の輪の赤・緑の回）、段の一覧を集めず、後ろに足した試験（ファイル・node id）だけを走らせる
# （足した試験が 1 つも無ければ合図は効かず段の一覧のまま。外の根の名指しだけなら works の根の pytest は起こさない）。
# 外の根の名指しが無ければ pytest 1 本（merge しない）。合わせた終了コードは各プロセスの最大で、-k などで 0 件（5）の根は、
# ほかの根が 1 つでも走っていれば赤にしない。
# 終了コードは pytest のまま（0 = 全部通った・1 = 落ちた試験が在る・…）。書き先が無い・段の値が違う・段の一覧が崩れている
# ときは、標準エラーに 1 行出して 2（pytest を起こさない）。.pytest_cache とバイトコードは作らない。
# 読み込みで落ちるモジュールが在っても一式を止めない（--continue-on-collection-errors。落ちたモジュールは error で載り、
# 他の試験の結末も書かれる。止まると「元で通っていた他のテストは緑のまま」を確かめられない）。
# 重いテストの枠（testslot）と nice -n 19 は、この殻を起こす外の tddloop.run_suite が付ける。中の試験が起こす試験
# （tree_run.slotted_run）には取らせない（WORKS_TESTSLOT を空にする。外で取った枠と二重に数えない。約束は .shared/core/slotwrap.sh）。走らせる run の env は run.sh と同じ tests/hermetic.sh で落とす。
out=${1-}
if [ -z "$out" ]; then
  echo "tdd-suite.sh: 第 1 引数に JUnit XML の書き先を渡す" >&2
  exit 2
fi
shift
case $out in
  /*) ;;
  *) out=$(pwd)/$out ;;
esac
here=$(pwd)
n=$#
prev=
while [ "$n" -gt 0 ]; do
  a=$1
  shift
  n=$((n - 1))
  case $prev:$a in
    -k:*|*:/*|*:-*) ;;
    *) if [ -e "$here/${a%%::*}" ]; then a=$here/$a; fi ;;
  esac
  prev=$a
  set -- "$@" "$a"
done
tier=${WORKS_TDD_TIER:-fast}
case $tier in
  fast|heavy) ;;
  *) echo "tdd-suite.sh: WORKS_TDD_TIER は fast・heavy のどちらか（今の値: ${tier}）" >&2; exit 2 ;;
esac
cd "$(dirname "$0")/.." || exit 2
. tests/hermetic.sh
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE
WORKS_TESTSLOT=
export WORKS_TESTSLOT
files=$(uv run --no-project python3 tests/tiers.py paths "$tier") || exit 2
works=$(pwd -P)
tmp=$(mktemp -d "${TMPDIR:-/tmp}/tdd-suite.XXXXXX") || exit 2
trap 'rm -rf "$tmp"' EXIT
# 名指しの試験の根: パスから上へ辿って最初に conftest.py が在る置き場（辿り着かなければ works の根）。根の名は決め打ちしない
root_of() {
  if [ -d "$1" ]; then d=$(cd "$1" 2>/dev/null && pwd -P); else d=$(cd "$(dirname "$1")" 2>/dev/null && pwd -P); fi
  [ -n "$d" ] || { printf '%s\n' "$works"; return; }
  while [ "$d" != "$works" ] && [ "$d" != / ]; do
    if [ -f "$d/conftest.py" ]; then printf '%s\n' "$d"; return; fi
    d=$(dirname "$d")
  done
  printf '%s\n' "$works"
}
: >"$tmp/inner"
: >"$tmp/outer"
n=$#
prev=
while [ "$n" -gt 0 ]; do
  a=$1
  shift
  n=$((n - 1))
  case $prev in
    -k) set -- "$@" "$a" ;;
    *) if [ "${a#-}" = "$a" ] && [ -e "${a%%::*}" ]; then
         r=$(root_of "${a%%::*}")
         if [ "$r" = "$works" ]; then printf '%s\n' "$a" >>"$tmp/inner"; else printf '%s\t%s\n' "$r" "$a" >>"$tmp/outer"; fi
       else
         set -- "$@" "$a"
       fi ;;
  esac
  prev=$a
done
# 輪の赤・緑の回の合図: 足した試験が在れば段の一覧を集めない（無ければ段の一覧のまま）
if [ "${TDD_SUITE_ONLY-}" = 1 ] && { [ -s "$tmp/inner" ] || [ -s "$tmp/outer" ]; }; then
  files=
fi
# shellcheck disable=SC2046,SC2086  # 段のファイル・node id は空白を含まない。1 本ずつ別の引数にする
if [ ! -s "$tmp/outer" ]; then
  inner=$(cat "$tmp/inner")
  rm -rf "$tmp"
  exec uv run --no-project --with pyyaml --with pytest python3 -m pytest -p no:cacheprovider --continue-on-collection-errors --junitxml="$out" $files $inner "$@"
fi
# 試験の根が違う名指しは別のプロセスで流す（1 つのプロセスに 2 つの engine を載せない）。works の根を先に、外の根は根ごとに 1 本
code=0
zero=0
ran=0
i=0
run_root() { # <cwd> <node id…>
  dir=$1
  shift
  i=$((i + 1))
  (cd "$dir" && uv run --no-project --with pyyaml --with pytest python3 -m pytest -p no:cacheprovider --continue-on-collection-errors --junitxml="$tmp/$i.xml" "$@")
  rc=$?
  if [ "$rc" = 5 ]; then zero=1; else ran=1; fi
  if [ "$rc" != 5 ] && [ "$rc" -gt "$code" ]; then code=$rc; fi
}
if [ -n "$files" ] || [ -s "$tmp/inner" ]; then
  # shellcheck disable=SC2046,SC2086
  run_root "$works" $files $(cat "$tmp/inner") "$@"
fi
for r in $(cut -f1 "$tmp/outer" | sort -u); do
  # shellcheck disable=SC2046,SC2086
  run_root "$r" $(awk -F'\t' -v r="$r" '$1 == r { print $2 }' "$tmp/outer") "$@"
done
set --
for x in "$tmp"/*.xml; do [ -f "$x" ] && set -- "$@" "$x"; done
uv run --no-project --with junitparser junitparser merge "$@" "$out" || exit 2
# -k などで 0 件（pytest の 5）の根は、他の根が走って緑なら赤にしない
if [ "$code" = 0 ] && [ "$zero" = 1 ] && [ "$ran" = 0 ]; then exit 5; fi
exit "$code"
