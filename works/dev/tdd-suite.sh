#!/bin/sh
# works/dev/tdd-suite.sh <JUnit XML の書き先> [pytest の引数…]
#
# TDD の実行器（ラインの入力 tdd_suite に渡す殻。仕様 tdd-spec 6 節）。works の試験を既製の pytest で走らせ、テスト 1 件ごとの
# 結末を pytest の --junitxml で書く（JUnit を自作しない。pytest は今の unittest の試験をそのまま拾う）。
# 段は WORKS_TDD_TIER（fast が既定・heavy）。段のファイルは tests/tiers.py の paths の口から引く（一覧を写さない）。
# 後ろの引数は pytest にそのまま足す（-k などで段の中を絞る）。書き先の相対パスは呼ぶ側の cwd から。
# 終了コードは pytest のまま（0 = 全部通った・1 = 落ちた試験が在る・…）。書き先が無い・段の値が違う・段の一覧が崩れている
# ときは、標準エラーに 1 行出して 2（pytest を起こさない）。.pytest_cache とバイトコードは作らない。
# heavy は run.sh と違い、重いテストの枠（testslot）を通さない。
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
tier=${WORKS_TDD_TIER:-fast}
case $tier in
  fast|heavy) ;;
  *) echo "tdd-suite.sh: WORKS_TDD_TIER は fast・heavy のどちらか（今の値: ${tier}）" >&2; exit 2 ;;
esac
cd "$(dirname "$0")/.." || exit 2
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE
files=$(uv run --no-project python3 tests/tiers.py paths "$tier") || exit 2
# shellcheck disable=SC2086  # 段のファイルは tests/test_*.py の名前（空白を含まない）。1 本ずつ別の引数にする
exec uv run --no-project --with pyyaml --with pytest python3 -m pytest -p no:cacheprovider --junitxml="$out" $files "$@"
