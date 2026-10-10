#!/bin/sh
# works/dev/mktarget.sh <dir>
#
# <dir> に使い捨ての git リポジトリを作る:
#   - target-seed/ を種として写す（stats.py・test_stats.py。バグ入り）。
#   - works/ を project pack として .archon/workflows/works/ に写す
#     （tests/・dev/・docs/ は除く）。筋書きは共通の基と合わせた物にする（stubfold.py）。
# 写し終えたら 1 回 commit し、作業ツリーが変わっていない状態にして、
# <dir> の絶対パスを標準出力に 1 行出す。
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: mktarget.sh <dir>" >&2
  exit 2
fi

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
WORKS_DIR="$(cd "$DEV_DIR/.." && pwd -P)"

# 対象が Claude Code の一時フォルダの下なら、何も作らずに止まる（guard.sh）
. "$DEV_DIR/guard.sh"
works_dev_refuse_claude_tmp mktarget.sh "対象" "$1"

mkdir -p "$1"
DIR="$(cd "$1" && pwd -P)"

git init -q "$DIR"
git -C "$DIR" config user.email "works-dev@example.invalid"
git -C "$DIR" config user.name "works-dev"
# 使い捨てなので、commit の後に裏で走る自動の保守（gc --auto・maintenance --auto）を切る。git 2.55 では裏の保守が
# .git に書いている最中に呼び手（check.sh の trap）が消しにかかり、rm が「Directory not empty」で落ちた
git -C "$DIR" config gc.auto 0
git -C "$DIR" config maintenance.auto false

# 種（バグ入りの stats.py・test_stats.py）を対象の根に置く。Python のバイトコードキャッシュや
# OS のゴミファイルは種に残さない（.git の中は触らない。pack の分は works_dev_copy_pack が消す）。
cp -R "$DEV_DIR/target-seed/." "$DIR/"
find "$DIR" -name .git -prune -o \
  \( -name "__pycache__" -o -name ".DS_Store" -o -name "*.pyc" \) -print0 |
  xargs -0 rm -rf

# works/ を project pack として写す。tests/・dev/・docs/ は除く（lib.sh）
. "$DEV_DIR/lib.sh"
works_dev_copy_pack "$WORKS_DIR" "$DIR/.archon/workflows/works"
# 筋書きの共通の基（<工程>/fixtures/base.yaml）を写しの筋書きに合わせて基を消す。Archon の模擬実行は *.stubs.yaml を 1 本ずつ
# 読み、基を読まない（合わせ方は stubfold.py）
python3 "$DEV_DIR/stubfold.py" materialize "$DIR/.archon/workflows/works"

# 利用者の git の設定（署名・hook）に左右されないように、この commit だけ切る
git -C "$DIR" add -A
git -C "$DIR" -c commit.gpgsign=false -c core.hooksPath=/dev/null commit -q -m "chore: works-dev の使い捨ての対象を作る（種と pack）"

echo "$DIR"
