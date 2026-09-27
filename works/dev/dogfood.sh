#!/bin/sh
# works/dev/dogfood.sh <request.json> <test_cmd> [<dir>]
#
# 自分食い: このリポジトリ自身を対象に、ライン darkfactory を本物の AI で 1 回回す（費用が掛かる。回す前に持ち主の了承を取る）。
#   1. このリポジトリの今の HEAD（commit 済みの物だけ。手元の変更は入らない）を <dir>/repo に clone し、枝 dogfood-base を切る。
#   2. clone の中の works/（HEAD の物）を project pack として .archon/workflows/works に写し
#      （tests/・dev/・docs/ は除く。lib.sh）、dogfood-base に commit する。
#   3. <dir>/origin.git に裸のリポジトリを作って origin にし、dogfood-base を push して origin の既定の枝にする
#      （Archon は run ごとに切る worktree の元を origin の既定の枝から取るため）。
#   4. 依頼を <dir>/request.json に写し（依頼の元が後で書き換わっても、回した物が残る）、clone の中で
#      archon.sh workflow run darkfactory を前景で回す。人の関所で run は止まって戻る。
#   5. run id・状態・修正の差分がある worktree・次に打つコマンド（承認・拒否・続き）と、run の worktree の差分
#      （git diff --binary <周の頭の版>。<dir>/run-<id>.diff）をこのリポジトリへ git apply で取り込むコマンドを出す。
#      修正が pack の写し（.archon/）に触れていれば 1 行で注意する。
#   入力: tdd_suite=works/dev/tdd-suite.sh（WORKS_DOGFOOD_TDD_SUITE で替える・空で輪を飛ばす）・adapter は空＝包みを求める
#   （既定。WORKS_DEV_ADAPTER=0 か空で包みを外すと adapter=optional）・final_gate=always（WORKS_DOGFOOD_FINAL_GATE で when_needed に）。
# 包み（claude-adapter）は既定で通す（持ち主 2026-09-28。archon.sh に WORKS_DEV_ADAPTER=1 を渡し、続きのコマンドにも付ける）。
# <dir> に前の回の repo・origin.git・request.json が在れば、何も書かずに止まる（前の回の依頼を上書きしない）。
# <dir> の既定は $TMPDIR の下の一時フォルダ。模型は WORKS_DEV_MODEL（既定は opus。書くのは archon.sh）。
# 認証は archon.sh と同じ（CLAUDE_CODE_OAUTH_TOKEN か WORKS_KEYCHAIN_ITEM。既定の口座は無い）。
# CLAUDE_BIN_PATH は real-run.sh と同じく隔離の前に解いて渡す。
# WORKS_DEV_ARCHON は Archon を呼ぶ殻の差し替え（既定は同じフォルダの archon.sh。tests/test_dev.py が偽物を差す）。
set -eu

if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
  echo "usage: dogfood.sh <request.json> <test_cmd> [<dir>]" >&2
  exit 2
fi

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
WORKS_DIR="$(cd "$DEV_DIR/.." && pwd -P)"
ARCHON="${WORKS_DEV_ARCHON:-$DEV_DIR/archon.sh}"
WORKS_DEV_HOME="${WORKS_DEV_HOME:-${TMPDIR:-/tmp}/works-dev}"
WORKS_DEV_MODEL="${WORKS_DEV_MODEL:-opus}"
# 包みは既定で通す。WORKS_DEV_ADAPTER=0 か空を明示した時だけ外す（値の検査は archon.sh）
WORKS_DEV_ADAPTER="${WORKS_DEV_ADAPTER-1}"
export WORKS_DEV_HOME WORKS_DEV_MODEL WORKS_DEV_ADAPTER

# 開発の家・置き場が Claude Code の一時フォルダの下なら、認証を確かめる前・何かを作る前に止まる（guard.sh）
. "$DEV_DIR/guard.sh"
works_dev_refuse_claude_tmp dogfood.sh "WORKS_DEV_HOME" "$WORKS_DEV_HOME"
if [ "$#" -ge 3 ]; then
  works_dev_refuse_claude_tmp dogfood.sh "置き場" "$3"
  works_dev_refuse_claude_tmp dogfood.sh "clone" "$3/repo"
  works_dev_refuse_claude_tmp dogfood.sh "origin" "$3/origin.git"
else
  works_dev_refuse_claude_tmp dogfood.sh "置き場（TMPDIR）" "${TMPDIR:-/tmp}/works-dogfood.x"
fi

# 何かを作る前に、認証が無いことを 1 行で知らせて止まる（archon.sh と同じ規則）。
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${WORKS_KEYCHAIN_ITEM:-}" ]; then
  echo "dogfood.sh: 認証が無い。CLAUDE_CODE_OAUTH_TOKEN（例: claude setup-token で作る）か、トークンを入れた keychain の項目名 WORKS_KEYCHAIN_ITEM を設定する" >&2
  exit 2
fi

if [ ! -f "$1" ]; then
  echo "dogfood.sh: 依頼の JSON が無い（$1）" >&2
  exit 2
fi

if [ -z "${CLAUDE_BIN_PATH:-}" ]; then
  CLAUDE_BIN_PATH="$(command -v claude || true)"
  case "$CLAUDE_BIN_PATH" in /*) ;; *) CLAUDE_BIN_PATH="" ;; esac   # 関数・別名は実行ファイルでない
  if [ -z "$CLAUDE_BIN_PATH" ]; then
    echo "dogfood.sh: claude の実行ファイルが PATH に無い。CLAUDE_BIN_PATH に絶対パスを設定する" >&2
    exit 2
  fi
fi
export CLAUDE_BIN_PATH

SRC="$(git -C "$WORKS_DIR" rev-parse --show-toplevel)"
REV="$(git -C "$SRC" rev-parse HEAD)"

if [ "$#" -ge 3 ]; then
  for used in repo origin.git request.json; do
    if [ -e "$3/$used" ] || [ -L "$3/$used" ]; then
      echo "dogfood.sh: <dir> に前の回の ${used} が在る（$3/${used}）。別の <dir> を使うか、要らなければ消す" >&2
      exit 2
    fi
  done
  mkdir -p "$3"
  DIR="$(cd "$3" && pwd -P)"
else
  DIR="$(cd "$(mktemp -d "${TMPDIR:-/tmp}/works-dogfood.XXXXXX")" && pwd -P)"
fi
REPO="$DIR/repo"
ORIGIN="$DIR/origin.git"
REQUEST="$DIR/request.json"
cp "$1" "$REQUEST"

# 利用者の git の設定（署名・hook）に左右されないように、ここで打つ git は全部 hook と署名を切る
g() { git -c core.hooksPath=/dev/null -c commit.gpgsign=false "$@"; }

g clone -q --no-checkout "$SRC" "$REPO"
g -C "$REPO" checkout -q -b dogfood-base "$REV"
g -C "$REPO" remote remove origin   # 元のリポジトリの枝（refs/remotes/origin/*）も一緒に消える
g -C "$REPO" config user.email "works-dev@example.invalid"
g -C "$REPO" config user.name "works-dev"

. "$DEV_DIR/lib.sh"
# 写すのは clone した HEAD の works/（元の作業ツリーの commit していない書き換え・未追跡は入れない）
PACK_SRC="$REPO/${WORKS_DIR#"$SRC"/}"
if [ ! -f "$PACK_SRC/archon-plugin.json" ]; then
  echo "dogfood.sh: clone した HEAD に works が無い（${PACK_SRC}/archon-plugin.json）。works を commit してから回す" >&2
  exit 2
fi
works_dev_copy_pack "$PACK_SRC" "$REPO/.archon/workflows/works"
g -C "$REPO" add -A -- .archon/workflows/works
g -C "$REPO" commit -q -m "chore: works を project pack として .archon/workflows/works に置く（自分食いの元）"

g init -q --bare "$ORIGIN"
g -C "$ORIGIN" symbolic-ref HEAD refs/heads/dogfood-base
g -C "$REPO" remote add origin "$ORIGIN"
g -C "$REPO" push -q origin dogfood-base
g -C "$REPO" fetch -q origin
g -C "$REPO" remote set-head origin dogfood-base >/dev/null
echo "対象: ${REPO}（${REV} の上に pack を置いた枝 dogfood-base）"

cd "$REPO"
set +e
# 修正の段の TDD の輪の実行器（この clone の works/dev/tdd-suite.sh。WORKS_DOGFOOD_TDD_SUITE を空にすれば輪を飛ばす）。
# 包みを外した run（WORKS_DEV_ADAPTER が 1 でない）は adapter=optional で回す（h-judge が包みの無い run を止めないように。報告に出る）
TDD_SUITE="${WORKS_DOGFOOD_TDD_SUITE-works/dev/tdd-suite.sh}"
if [ "${WORKS_DEV_ADAPTER:-}" = 1 ]; then ADAPTER_MODE=""; else ADAPTER_MODE="optional"; fi
sh "$ARCHON" workflow run darkfactory --input request="$REQUEST" --input test_cmd="$2" \
  --input tdd_suite="$TDD_SUITE" --input adapter="$ADAPTER_MODE" --input final_gate="${WORKS_DOGFOOD_FINAL_GATE:-always}"
run_status=$?
set -e
echo "workflow run の終了コード: $run_status"

works_dev_show_run dogfood.sh "$ARCHON" "$REPO" "$SRC"
exit "$run_status"
