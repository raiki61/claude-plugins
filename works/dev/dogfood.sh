#!/bin/sh
# works/dev/dogfood.sh <依頼の JSON> <test_cmd> [<dir>]
# works/dev/dogfood.sh --show <dir> <run-id>
#
# 自分食い: このリポジトリ自身を対象に、ライン darkfactory を本物の AI で 1 回回す（費用が掛かる。回す前に持ち主の了承を取る）。
#   1. このリポジトリの今の HEAD（commit 済みの物だけ。手元の変更は入らない）を <dir>/repo に clone し、枝 dogfood-base を切る。
#   2. clone の中の works/（HEAD の物）を project pack として .archon/workflows/works に写し
#      （tests/・dev/・docs/ は除く。lib.sh）、dogfood-base に commit する。
#   3. <dir>/origin.git に裸のリポジトリを作って origin にし、dogfood-base を push して origin の既定の枝にする
#      （Archon は run ごとに切る worktree の元を origin の既定の枝から取るため）。
#   4. 依頼を起動ごとの写し <dir>/requests/<日時>-<pid>.json に写し（依頼の元が後で書き換わっても、回した物が残る）、clone の中で
#      archon.sh workflow run darkfactory を前景で回す。人の関所で run は止まって戻る。
#   5. run id・状態・修正の差分がある worktree・次に打つコマンド（承認・拒否・続き）と、run の worktree の差分
#      （git diff --binary <周の頭の版>。<dir>/run-<id>.diff）をこのリポジトリへ git apply で取り込むコマンドを出す。
#      差分が空（起動の直後の関所）なら書かない。承認・関所の答え・続き・拒否・取り消しの行は continue.sh を通って前後で herdr の
#      枠の集計を出し、Archon が戻った後に dogfood.sh --show <dir> <run-id> で差分を書き直す（lib.sh の WORKS_DEV_SHOW_CMD）。
#      修正が pack の写し（.archon/）に触れていれば 1 行で注意する。
# --show <dir> <run-id>: 前に回した <dir> の run の差分を今の worktree で書き直し、5 の行を出し直し、herdr の枠の集計を
#   その run の今の状態で出す（lib.sh works_dev_show_synced。控えは書き直さない）。認証も前の回の検査も
#   しない（問い合わせは認証を読ませない）。続きの行が前置き（WORKS_DEV_HOME・CLAUDE_BIN_PATH など）ごと付けて打つ。
#   入力: tdd_suite=works/dev/tdd-suite.sh（WORKS_DOGFOOD_TDD_SUITE で替える・空で輪を飛ばす）・adapter は空＝包みを求める
#   （既定。WORKS_DEV_ADAPTER=0 か空で包みを外すと adapter=optional）・final_gate=always（WORKS_DOGFOOD_FINAL_GATE で when_needed に）。
#   WORKS_DESIGN_ONLY=1 は設計だけの run: 入力 design_only=true を渡し、修正前の関所を項目の有無に関わらず開けて止める。
#   未設定・空は今どおり。1 の外の値（on など）だけが、何かを作る前に 1 行で止まる（終了コード 2）。
# 包み（claude-adapter）は既定で通す（持ち主 2026-09-28。archon.sh に WORKS_DEV_ADAPTER=1 を渡し、続きのコマンドにも付ける）。
# <dir> に前の回の repo・origin.git・github-reads.json か、前の版の固定名の写し request.json が在れば、何も書かずに止まる。
# 起動ごとの写し（requests/）は起動の記録で、残っていても次の起動を妨げない。
# <dir> の既定は $TMPDIR の下の一時フォルダ。模型は WORKS_DEV_MODEL（ここでは埋めない。既定を解いて書くのは archon.sh）。
# 認証は起こし役 .shared/core/auth_launch.py の check が拾う（順は起こし役が持つ。値は出さない）。
# 開発の家の既定と CLAUDE_BIN_PATH は launch.py env が解き（real-run.sh と同じ）、隔離の前に渡す。
# WORKS_DEV_ARCHON は Archon を呼ぶ殻の差し替え（既定は同じフォルダの archon.sh。tests/test_dev.py が偽物を差す）。
set -eu

if [ "${1:-}" = --show ]; then
  SHOW=1
  [ "$#" -eq 3 ] || { echo "usage: dogfood.sh --show <dir> <run-id>" >&2; exit 2; }
else
  SHOW=""
  if [ "$#" -lt 2 ] || [ "$#" -gt 3 ]; then
    echo "usage: dogfood.sh <依頼の JSON> <test_cmd> [<dir>]（前の回の差分を書き直すのは dogfood.sh --show <dir> <run-id>）" >&2
    exit 2
  fi
  case "${WORKS_DESIGN_ONLY:-}" in
    "" | 1) ;;
    *)
      echo "dogfood.sh: WORKS_DESIGN_ONLY は 1（設計だけの run）か空（今どおり）。受けた値: ${WORKS_DESIGN_ONLY}" >&2
      exit 2
      ;;
  esac
fi

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
WORKS_DIR="$(cd "$DEV_DIR/.." && pwd -P)"
ARCHON="${WORKS_DEV_ARCHON:-$DEV_DIR/archon.sh}"
export WORKS_DEV_HOME WORKS_DEV_MODEL WORKS_DEV_ADAPTER
# 起こすのは start だけなので、start の時の既定の釘（続きの行だけが置く）は利用者の殻に残っていても受けない
unset WORKS_MODEL_PINNED

# 開発の家・置き場が Claude Code の一時フォルダの下なら、認証を確かめる前・何かを作る前に止まる（guard.sh）
. "$DEV_DIR/guard.sh"
# 家の既定・claude の解決・包みの既定（WORKS_DEV_ADAPTER。0 か空を明示した時だけ外す。値の検査は archon.sh）とラインの入力
# adapter の値は launch.py env が持つ（--show は claude を埋めない。下の CLAUDE_BIN_PATH の要求を残す）
if [ -n "$SHOW" ]; then works_dev_launch_env dogfood.sh --show; else works_dev_launch_env dogfood.sh --claude; fi
works_dev_abs_claude_config
works_dev_refuse_claude_tmp dogfood.sh "WORKS_DEV_HOME" "$WORKS_DEV_HOME"

if [ -n "$SHOW" ]; then
  if [ ! -d "$2/repo" ] || [ -z "${CLAUDE_BIN_PATH:-}" ]; then
    echo "dogfood.sh: --show は前に回した <dir>（<dir>/repo が在る）と CLAUDE_BIN_PATH が要る（続きの行が付ける口をそのまま打つ）" >&2
    exit 2
  fi
  export CLAUDE_BIN_PATH
  DIR="$(cd "$2" && pwd -P)"
  SRC="$(git -C "$WORKS_DIR" rev-parse --show-toplevel)"
  . "$DEV_DIR/lib.sh"
  works_dev_show_cmd "$DEV_DIR/dogfood.sh" "$ARCHON" "$DIR"
  cd "$DIR/repo"
  WORKS_RUN_ID="$3"
  export WORKS_RUN_ID
  works_dev_show_synced dogfood.sh "$ARCHON" "$DIR/repo" "$SRC"
  exit 0
fi

if [ "$#" -ge 3 ]; then
  works_dev_refuse_claude_tmp dogfood.sh "置き場" "$3"
  works_dev_refuse_claude_tmp dogfood.sh "clone" "$3/repo"
  works_dev_refuse_claude_tmp dogfood.sh "origin" "$3/origin.git"
else
  works_dev_refuse_claude_tmp dogfood.sh "置き場（TMPDIR）" "${TMPDIR:-/tmp}/works-dogfood.x"
fi

# 何かを作る前に、起こし役の check で認証を確かめ、無ければその 1 行の案内で止まる。拾った出どころの名は捨てる
# （名の行は archon.sh が出す）
python3 -I "$WORKS_DIR/.shared/core/auth_launch.py" check --for dogfood.sh \
  --user-home "$HOME" --user-config "${CLAUDE_CONFIG_DIR:-}" >/dev/null || exit $?

if [ ! -f "$1" ]; then
  echo "dogfood.sh: 依頼の JSON が無い（$1）" >&2
  exit 2
fi

CLAUDE_BIN_PATH="$WORKS_LAUNCH_CLAUDE"
if [ -z "$CLAUDE_BIN_PATH" ]; then
  echo "dogfood.sh: claude の実行ファイルが PATH に無い。CLAUDE_BIN_PATH に絶対パスを設定する" >&2
  exit 2
fi
export CLAUDE_BIN_PATH

SRC="$(git -C "$WORKS_DIR" rev-parse --show-toplevel)"
REV="$(git -C "$SRC" rev-parse HEAD)"

if [ "$#" -ge 3 ]; then
  for used in repo origin.git request.json github-reads.json; do
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
# 写しの名は起動ごとに一意（use.sh と同じ印）。<dir> を使い直しても、一覧に残る前の起動の run と結びの候補が重ならない
mkdir -p "$DIR/requests"
REQUEST="$DIR/requests/$(date +%Y%m%d-%H%M%S)-$$.json"
cp "$1" "$REQUEST"

# 依頼の欄 pr・issue が名指した PR・issue を、clone の前に利用者の env（gh のログインが見える）のまま 1 回だけ読む（設計書 2.8）。
# cwd は元のリポジトリ SRC（clone は origin を付け替えるので gh が GitHub のリポジトリを解けない）。名指しが無ければ何も書かない
GITHUB_READS=""
python3 -I "$WORKS_DIR/.shared/core/ghreads.py" read --repo "$SRC" --request "$REQUEST" --out "$DIR/github-reads.json"
if [ -f "$DIR/github-reads.json" ]; then
  GITHUB_READS="$DIR/github-reads.json"
  echo "名指した PR・issue を隔離の前に読んだ: ${GITHUB_READS}"
fi

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
# 関所の文の答えの行の頭（.shared/core/answer.py）。利用者の PATH に archon は無いので、続きの口 continue.sh を通して隔離した
# archon.sh の respond を打つ頭を置く（前後で herdr の枠の集計を出す）
WORKS_ANSWER_CMD="$(WORKS_ANSWER_CMD="" works_dev_go "$ARCHON" "$REPO") respond"
export WORKS_ANSWER_CMD
set +e
# 修正の段の TDD の輪の実行器（この clone の works/dev/tdd-suite.sh。WORKS_DOGFOOD_TDD_SUITE を空にすれば輪を飛ばす）。
# 包みを外した run は adapter=optional（launch.py env の WORKS_LAUNCH_ADAPTER_MODE）で回す（h-judge が包みの無い run を止めないように。報告に出る）
TDD_SUITE="${WORKS_DOGFOOD_TDD_SUITE-works/dev/tdd-suite.sh}"
set -- workflow run darkfactory --input request="$REQUEST" --input test_cmd="$2" \
  --input tdd_suite="$TDD_SUITE" --input adapter="$WORKS_LAUNCH_ADAPTER_MODE" --input final_gate="${WORKS_DOGFOOD_FINAL_GATE:-always}"
if [ "${WORKS_DESIGN_ONLY:-}" = 1 ]; then set -- "$@" --input design_only=true; fi
if [ -n "$GITHUB_READS" ]; then set -- "$@" --input github_reads="$GITHUB_READS"; fi
sh "$ARCHON" "$@"
run_status=$?
set -e
echo "workflow run の終了コード: $run_status"
# 起動が落ちた（start が盤面へ写して消すところまで行かない）時は、読み出しのファイル（非公開の本文を持つ）を <dir> に残さない
if [ "$run_status" -ne 0 ] && [ -n "$GITHUB_READS" ]; then
  rm -f "$GITHUB_READS"
  echo "起動が落ちたので、隔離の前に読んだ読み出しのファイルを消した: ${GITHUB_READS}"
fi

# 起動が落ちても run が在れば続きの行を出す（控えと herdr の枠の集計も lib.sh の同じ口で）。終了コードは起動のまま（起動が 0 の時だけ show の結果）
show_status=0
works_dev_show_cmd "$DEV_DIR/dogfood.sh" "$ARCHON" "$DIR"
works_dev_ledger_bind dogfood.sh "$ARCHON" "$REPO" "$REQUEST" show "$SRC" || show_status=$?
[ "$run_status" -ne 0 ] && exit "$run_status"
exit "$show_status"
