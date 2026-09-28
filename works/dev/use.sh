#!/bin/sh
# works/dev/use.sh — ほかのリポジトリを対象に、ライン darkfactory を回す起動の殻（skills/works/SKILL.md が入口）。
#
#   use.sh start [--base <版> | --pr <番号>] <対象リポジトリ> <依頼の JSON か -> <test_cmd> [<tdd_suite>]
#                                                                          本物の AI で回す（費用が掛かる）。最初の関所で止まって戻る
#                                                                          --base・--pr は変更から入る（差分に P1 の目を回す。依頼は - で省ける）
#   use.sh show  <対象リポジトリ>                                           一番新しい run の状態・次に打つ行・差分のファイルを出し直す
#   use.sh check <対象リポジトリ>                                           AI を起こさずに、pack を置いて Archon の validate だけを回す
#
# - AI の役は開発の殻 archon.sh を通してだけ起こす（HOME・ARCHON_HOME・CLAUDE_CONFIG_DIR を利用の家の下へ隔離し、役は toolset.py が
#   組む選んだ物だけの設定を読む。利用者の本物の ~/.claude は読ませない）。
# - 利用の家は WORKS_USE_HOME（既定は ${XDG_STATE_HOME:-$HOME/.local/state}/works/use）。WORKS_DEV_HOME は継がない
#   （自分食い・実走の家と分け、走っている run の家を書き換えない）。
# - pack は対象に置かない。tests/・dev/・docs/ を除いた works/ を <家>/archon-home/workflows/works（Archon の全体の工程の置き場。
#   Archon v0.11.1 は $ARCHON_HOME/workflows/<pack>/ も探す）に起こすたびに写す。対象の作業ツリーは書かない。
# - run の worktree は対象の今の HEAD から切る（--from <HEAD の版>）。Archon は worktree を切る前に origin を fetch するので origin が要る。
# - 拒む（Archon を呼ばず・何も写さずに 1 行で終了コード 2）: /private/tmp の下の対象・リポジトリの根でない・commit していない変更か
#   未追跡のファイルが在る（show は除く）・origin が無い・対象に pack の写し .archon/workflows/works が在る（dogfood.sh の形）・
#   依頼が無い（- なら変更も無い）・認証が無い（start）。
# - tdd_suite: 第 4 引数が在ればそのまま（空は輪を飛ばす）。無ければ test_cmd が pytest の 1 コマンド（前に uv run・poetry run・
#   python3 -m を許す。; & | < > $ ` を含まない）の時だけ、その末尾に JUnit XML の書き先を足す実行器を <家>/suites/ に書いて渡す。
#   それ以外は空（全部の単位を直に直す）にして 1 行で知らせる。
# - 最後の関所は WORKS_USE_FINAL_GATE（既定 always・when_needed）。包みは WORKS_DEV_ADAPTER=1 で入れる（無ければ adapter=optional）。
# - 差分（run の worktree と周の頭の版の差）は <家>/diffs/run-<id>.diff に書き、対象へ git apply する行を出す。当てるのは人。
# 認証は archon.sh と同じ（CLAUDE_CODE_OAUTH_TOKEN か WORKS_KEYCHAIN_ITEM）。模型は WORKS_DEV_MODEL（既定 opus）。
# WORKS_DEV_ARCHON は Archon を呼ぶ殻の差し替え（既定は同じフォルダの archon.sh。tests/test_use.py が偽物を差す）。
set -eu

USAGE="usage: use.sh start [--base <版> | --pr <番号>] <対象リポジトリ> <依頼の JSON か -> <test_cmd> [<tdd_suite>] | use.sh show <対象リポジトリ> | use.sh check <対象リポジトリ>"
CHANGE_INPUT=""   # 変更の入口（ラインの入力 base か pr）。--input にそのまま渡す <鍵>=<値>
if [ "${1:-}" = start ]; then
  case "${2:-}" in
    --base | --pr)
      if [ "$#" -lt 3 ] || [ -z "$3" ]; then
        echo "$USAGE" >&2
        exit 2
      fi
      CHANGE_INPUT="${2#--}=$3"
      shift 3
      set -- start "$@"
      ;;
  esac
fi
CMD="${1:-}"
case "$CMD:$#" in
  start:4 | start:5 | show:2 | check:2) ;;
  *)
    echo "$USAGE" >&2
    exit 2
    ;;
esac

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
WORKS_DIR="$(cd "$DEV_DIR/.." && pwd -P)"
ARCHON="${WORKS_DEV_ARCHON:-$DEV_DIR/archon.sh}"
WORKS_USE_HOME="${WORKS_USE_HOME:-${XDG_STATE_HOME:-$HOME/.local/state}/works/use}"
WORKS_DEV_HOME="$WORKS_USE_HOME"
WORKS_DEV_MODEL="${WORKS_DEV_MODEL:-opus}"
export WORKS_DEV_HOME WORKS_DEV_MODEL

refuse() {
  echo "use.sh: $*" >&2
  exit 2
}

. "$DEV_DIR/guard.sh"
works_dev_abs_claude_config
works_dev_refuse_claude_tmp use.sh "WORKS_USE_HOME" "$WORKS_USE_HOME"

# 対象の確かめ（Archon を呼ぶ前・何かを写す前）
TARGET_REAL="$(works_dev_real "$2")"
case "$TARGET_REAL" in
  /private/tmp | /private/tmp/*) refuse "対象が /private/tmp の下にある（${TARGET_REAL}）。一時フォルダの対象は使わない" ;;
esac
TOP="$(git -C "$TARGET_REAL" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$TOP" ] || [ "$(works_dev_real "$TOP")" != "$TARGET_REAL" ]; then
  refuse "対象（${TARGET_REAL}）が git のリポジトリの根でない。リポジトリの根を渡す"
fi
TARGET="$TARGET_REAL"
if [ "$CMD" != show ]; then
  DIRTY="$(git -C "$TARGET" status --porcelain --untracked-files=normal | head -n 3 | tr '\n' ' ')"
  if [ -n "$DIRTY" ]; then
    refuse "対象に commit していない変更か未追跡のファイルがある（${DIRTY}…）。run は対象の HEAD から切り、差分はここへ当てるので、commit か stash してから回す"
  fi
  if ! git -C "$TARGET" remote get-url origin >/dev/null 2>&1; then
    refuse "対象に remote の origin が無い。Archon は run の worktree を切る前に origin を fetch する（git remote add origin <URL>）"
  fi
  if [ -e "$TARGET/.archon/workflows/works" ]; then
    refuse "対象に pack の写し（.archon/workflows/works）がある。works 自身の直しは dogfood.sh で回す"
  fi
fi

# 本物の claude（隔離の前に解く。関数・別名は実行ファイルでない）。show・check も次の行に載せる
resolve_claude() {
  if [ -z "${CLAUDE_BIN_PATH:-}" ]; then
    CLAUDE_BIN_PATH="$(command -v claude || true)"
    case "$CLAUDE_BIN_PATH" in /*) ;; *) CLAUDE_BIN_PATH="" ;; esac
    if [ -z "$CLAUDE_BIN_PATH" ] && [ "$CMD" = start ]; then
      refuse "claude の実行ファイルが PATH に無い。CLAUDE_BIN_PATH に絶対パスを設定する"
    fi
  fi
  export CLAUDE_BIN_PATH
}

# pack を利用の家の Archon の全体の工程の置き場へ写す（一時の置き場に写してから入れ替える。ドット始まりは Archon が読まない）
place_pack() {
  _wf="$WORKS_USE_HOME/archon-home/workflows"
  mkdir -p "$_wf"
  rm -rf "$_wf/.works.new.$$"
  works_dev_copy_pack "$WORKS_DIR" "$_wf/.works.new.$$"
  rm -rf "$_wf/works"
  mv "$_wf/.works.new.$$" "$_wf/works"
}

. "$DEV_DIR/lib.sh"

case "$CMD" in
  check)
    place_pack
    cd "$TARGET"
    WORKS_DEV_NO_AUTH=1 sh "$ARCHON" validate workflows darkfactory
    exit $?
    ;;
  show)
    resolve_claude
    cd "$TARGET"
    works_dev_show_run use.sh "$ARCHON" "$TARGET" "$TARGET" "$WORKS_USE_HOME/diffs"
    exit $?
    ;;
esac

# ---- start
REQUEST_SRC="$3"
TEST_CMD="$4"
if [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ] && [ -z "${WORKS_KEYCHAIN_ITEM:-}" ]; then
  refuse "認証が無い。CLAUDE_CODE_OAUTH_TOKEN（例: claude setup-token で作る）か、トークンを入れた keychain の項目名 WORKS_KEYCHAIN_ITEM を設定する"
fi
if [ "$REQUEST_SRC" = - ]; then
  if [ -z "$CHANGE_INPUT" ]; then
    refuse "依頼も変更も無い（依頼の JSON を - にするなら --base <版> か --pr <番号> を名指す）"
  fi
elif [ ! -f "$REQUEST_SRC" ]; then
  refuse "依頼の JSON が無い（${REQUEST_SRC}）"
fi
resolve_claude

STAMP="$(date +%Y%m%d-%H%M%S)-$$"
REQUEST=""
if [ "$REQUEST_SRC" != - ]; then
  mkdir -p "$WORKS_USE_HOME/requests"
  REQUEST="$WORKS_USE_HOME/requests/$STAMP.json"
  cp "$REQUEST_SRC" "$REQUEST"   # 依頼の元が後で書き換わっても、回した物が残る
fi

if [ "$#" -ge 5 ]; then
  TDD_SUITE="$5"
  echo "TDD の輪: 渡された実行器 ${TDD_SUITE:-（空。輪を飛ばす）}"
elif printf '%s' "$TEST_CMD" | grep -Eq '^[[:space:]]*((uv|poetry) run |python3? -m )?pytest([[:space:]]|$)' &&
  ! printf '%s' "$TEST_CMD" | grep -q '[;&|<>$`]'; then
  mkdir -p "$WORKS_USE_HOME/suites"
  TDD_SUITE="$WORKS_USE_HOME/suites/$STAMP.sh"
  # 本線の tdd_suite の約束: JUnit XML の書き先を第 1 引数に受け、リポジトリの根（run の worktree）で走る
  cat >"$TDD_SUITE" <<EOF
#!/bin/sh
# use.sh が test_cmd から書いた TDD の実行器（${STAMP}）。第 1 引数に JUnit XML を書く
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE
exec $TEST_CMD -p no:cacheprovider --continue-on-collection-errors --junitxml="\$1"
EOF
  chmod +x "$TDD_SUITE"
  echo "TDD の輪: test_cmd（pytest）から実行器を書いた（${TDD_SUITE}）"
else
  TDD_SUITE=""
  echo "TDD の輪を飛ばす（全部の単位を直に直す）: test_cmd が pytest の 1 コマンドでない。JUnit XML を第 1 引数に書く実行器を最後の引数 <tdd_suite> に渡せば輪を回す"
fi

place_pack
cd "$TARGET"
HEAD_REV="$(git rev-parse HEAD)"
echo "対象: ${TARGET}（run の worktree は HEAD ${HEAD_REV} から切る）"

if [ "${WORKS_DEV_ADAPTER:-}" = 1 ]; then ADAPTER_MODE=""; else ADAPTER_MODE="optional"; fi
set +e
if [ -n "$CHANGE_INPUT" ]; then
  echo "入口: 変更から（${CHANGE_INPUT}）"
  set -- --input "$CHANGE_INPUT"
else
  set --
fi
sh "$ARCHON" workflow run darkfactory --from "$HEAD_REV" --input request="$REQUEST" --input test_cmd="$TEST_CMD" \
  --input tdd_suite="$TDD_SUITE" --input adapter="$ADAPTER_MODE" --input final_gate="${WORKS_USE_FINAL_GATE:-always}" "$@"
run_status=$?
set -e
echo "workflow run の終了コード: $run_status"

works_dev_show_run use.sh "$ARCHON" "$TARGET" "$TARGET" "$WORKS_USE_HOME/diffs"
exit "$run_status"
