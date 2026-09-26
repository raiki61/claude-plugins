#!/bin/sh
# works/dev/mktarget.sh <dir>
#
# <dir> に使い捨ての git リポジトリを作る:
#   - target-seed/ を種として写す（stats.py・test_stats.py。バグ入り）。
#   - works/ を project pack として .archon/workflows/works/ に写す
#     （tests/・dev/・docs/ は除く）。
# 写し終えたら 1 回 commit し、作業ツリーが変わっていない状態にして、
# <dir> の絶対パスを標準出力に 1 行出す。
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: mktarget.sh <dir>" >&2
  exit 2
fi

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
WORKS_DIR="$(cd "$DEV_DIR/.." && pwd -P)"

mkdir -p "$1"
DIR="$(cd "$1" && pwd -P)"

git init -q "$DIR"
git -C "$DIR" config user.email "works-dev@example.invalid"
git -C "$DIR" config user.name "works-dev"

# 種（バグ入りの stats.py・test_stats.py）を対象の根に置く。
cp -R "$DEV_DIR/target-seed/." "$DIR/"

# works/ を project pack として写す。tests/・dev/・docs/ は除く
# （Archon はドット始まりのフォルダと、直下に YAML の無いフォルダを工程として読まない）。
PACK_DIR="$DIR/.archon/workflows/works"
mkdir -p "$PACK_DIR"
for entry in "$WORKS_DIR"/* "$WORKS_DIR"/.[!.]*; do
  [ -e "$entry" ] || continue
  name="$(basename "$entry")"
  case "$name" in
    tests | dev | docs | .git) continue ;;
  esac
  cp -R "$entry" "$PACK_DIR/"
done

git -C "$DIR" add -A
git -C "$DIR" commit -q -m "chore: works-dev の使い捨ての対象を作る（種と pack）"

echo "$DIR"
