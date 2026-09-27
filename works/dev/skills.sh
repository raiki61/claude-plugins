#!/bin/sh
# works/dev/skills.sh <Claude の設定の置き場>
#
# 借りた superpowers のスキルの写し（works/.shared/superpowers/<版>/skills/<名>/）を <置き場>/skills/<名>/ へ写す。
# archon.sh が隔離した CLAUDE_CONFIG_DIR へ毎回呼ぶ。Archon v0.11.1 は、節の settingSources が [user] のとき
# $CLAUDE_CONFIG_DIR/skills/<名>/SKILL.md でスキルを探し（providers/src/shared/skills.ts の claudeSkillSearchRoots）、
# 見つからない名前は警告だけで読まずに進む。節が skills: に書いた名前が読めるように、ここで置いておく。
# - 柵: settingSources: [user] は置き場の CLAUDE.md・settings*.json・rules/・agents/・commands/・plugins/ も読ませる
#   （役の JSON だけを返す約束が崩れる）。どれかが在るか、skills/ に借りる一覧の外のスキルが在れば、名前を出して
#   終了コード 2 で止まる（何も写さない）。Claude Code が自分で書く状態のファイル（remote-settings.json・projects/ など）は見ない。
# - 写すのは借りたスキルの名前の置き場だけ。
# - symlink でなく写す（Claude Code が symlink を辿るかに頼らない）。バイトのまま・実行の権限つき（cp -Rp）。
# - 中身と実行の権限が同じなら何もしない。違えば一時の置き場に写してから入れ替える（同じ家を使う別の run が読んでいる間に、
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
    echo "skills.sh: 借りたスキルの版の置き場が 2 つ以上ある（${SRC} と ${d}）。works/.shared/superpowers/ の下は 1 版だけにする" >&2
    exit 2
  fi
  SRC="$d"
done
if [ -z "$SRC" ]; then
  echo "skills.sh: 借りたスキルの写しが無い（$WORKS_DIR/.shared/superpowers/<版>/skills/）" >&2
  exit 2
fi

leaks=""
for f in "$1"/CLAUDE.md "$1"/settings*.json; do
  if [ -e "$f" ]; then leaks="$leaks $(basename "$f")"; fi
done
for d in rules agents commands plugins; do
  if [ -e "$1/$d" ]; then leaks="$leaks $d/"; fi
done
if [ -d "$1/skills" ]; then
  for d in "$1"/skills/*/; do
    [ -d "$d" ] || continue
    name="$(basename "$d")"
    if [ ! -d "$SRC/$name" ]; then leaks="$leaks skills/$name/"; fi
  done
fi
if [ -n "$leaks" ]; then
  echo "skills.sh: Claude の設定の置き場（${1}）に、settingSources: [user] の節に読ませてはならない物が在る:${leaks}。消すか、別の WORKS_DEV_HOME を使う" >&2
  exit 2
fi

# 実行できるファイルの一覧（diff -r は権限を見ないので、別に比べる）
exec_files() {
  (cd "$1" && find . -type f -perm -u+x | LC_ALL=C sort)
}

DEST="$1/skills"
mkdir -p "$DEST"
for s in "$SRC"/*/; do
  name="$(basename "$s")"
  if [ -d "$DEST/$name" ] && diff -r "${s%/}" "$DEST/$name" >/dev/null 2>&1 &&
    [ "$(exec_files "${s%/}")" = "$(exec_files "$DEST/$name")" ]; then
    continue
  fi
  # 同じ家の 2 つの run が同時に入れ替えると、後の mv が置き場の中へ潜りうる（次の回の比べで直る。報告の既知の限界）
  tmp="$DEST/.$name.works-tmp.$$"
  rm -rf "$tmp"
  cp -Rp "${s%/}" "$tmp"
  rm -rf "${DEST:?}/$name"
  mv "$tmp" "$DEST/$name"
done
