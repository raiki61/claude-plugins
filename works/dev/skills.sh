#!/bin/sh
# works/dev/skills.sh <Claude の設定の置き場>
#
# 借りた superpowers のスキルの写し（works/.shared/superpowers/<版>/skills/<名>/）を <置き場>/skills/<名>/ へ写す。
# archon.sh が隔離した CLAUDE_CONFIG_DIR へ毎回呼ぶ。Archon v0.11.1 は、節の settingSources が [user] のとき
# $CLAUDE_CONFIG_DIR/skills/<名>/SKILL.md でスキルを探し（providers/src/shared/skills.ts の claudeSkillSearchRoots）、
# 見つからない名前は警告だけで読まずに進む。節が skills: に書いた名前が読めるように、ここで置いておく。
# - 写すのは借りたスキルの名前の置き場だけ。<置き場>/skills/ のほかの物には触らない。
# - symlink でなく写す（Claude Code が symlink を辿るかに頼らない）。バイトのまま・実行の権限つき（cp -Rp）。
# - 中身が同じなら何もしない。違えば一時の置き場に写してから入れ替える（同じ家を使う別の run が読んでいる間に、
#   消えた置き場を見せる時間を短くする）。
set -eu

if [ "$#" -ne 1 ]; then
  echo "usage: skills.sh <Claude の設定の置き場>" >&2
  exit 2
fi

WORKS_DIR="$(cd "$(dirname "$0")/.." && pwd -P)"
SRC=""
for d in "$WORKS_DIR"/.shared/superpowers/*/skills; do
  [ -d "$d" ] || continue
  if [ -n "$SRC" ]; then
    echo "skills.sh: 借りたスキルの版の置き場が 2 つ以上ある（$SRC と $d）。works/.shared/superpowers/ の下は 1 版だけにする" >&2
    exit 2
  fi
  SRC="$d"
done
if [ -z "$SRC" ]; then
  echo "skills.sh: 借りたスキルの写しが無い（$WORKS_DIR/.shared/superpowers/<版>/skills/）" >&2
  exit 2
fi

DEST="$1/skills"
mkdir -p "$DEST"
for s in "$SRC"/*/; do
  name="$(basename "$s")"
  if [ -d "$DEST/$name" ] && diff -r "${s%/}" "$DEST/$name" >/dev/null 2>&1; then
    continue
  fi
  tmp="$DEST/.$name.works-tmp.$$"
  rm -rf "$tmp"
  cp -Rp "${s%/}" "$tmp"
  rm -rf "${DEST:?}/$name"
  mv "$tmp" "$DEST/$name"
done
