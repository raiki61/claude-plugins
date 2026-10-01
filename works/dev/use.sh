#!/bin/sh
# works/dev/use.sh — ほかのリポジトリを対象に、ライン darkfactory を回す起動の殻（skills/works/SKILL.md が入口）。
#
#   use.sh start [--base <版> | --pr <番号>] [--] [<対象リポジトリ>] <依頼の JSON か -> [<test_cmd> [<tdd_suite>]]
#                                                                           本物の AI で回す（費用が掛かる）。最初の関所で止まって戻る。
#                                                                           --base・--pr は変更から入る（差分に P1 の目を回す。依頼は - で省ける）
#   use.sh show  <対象リポジトリ> [<run-id>]                                その対象で start が結んだ一番新しい run（か名指しの run）の状態・
#                                                                           次に打つ行・差分のファイルを出し直す
#   use.sh wait  <対象リポジトリ> <run-id>                                  裏で回る run を決まった時間（WORKS_USE_WAIT_SECONDS。既定 540 秒）
#                                                                           まで待ち、状態を 1 行で返す（0 = 関所で待つ・3 = まだ走っている・
#                                                                           5 = 終わった・1 = 落ちた・見つからない）。AI を起こさない
#   use.sh answer <対象リポジトリ> <run-id> continue|stop <一言> <答えた者> 関所で待つ run に答える（答えた者を <家>/answers.jsonl に残す）。残りの工程は切り離して回し、wait の行で返る
#   use.sh approve <対象リポジトリ> <run-id>                               起動の関所を越える（切り離して回し、wait の行で返る）
#   use.sh stop  <対象リポジトリ> <run-id> <理由>                           止める（関所で待つ run は respond stop、走っている run は止め札）
#   use.sh apply <対象リポジトリ> <run-id>                                  その run の差分を書き直し、git apply --check の後に対象へ当てる
#                                                                           （commit しない。消す行は WORKS_USE_ALLOW_DELETE=1 の時だけ。
#                                                                           記録が止まりを示す run は WORKS_USE_ALLOW_STOPPED=1 の時だけ）
#   use.sh clean <対象リポジトリ> <run-id>                                  終わった run の worktree と枝を消す（走っている・関所で待つ run は拒む）
#   use.sh check <対象リポジトリ>                                           AI を起こさずに、pack を置いて Archon の validate を回し、
#                                                                           start に足りない物（uv・claude・認証・対象の条件）を全部並べる
#
# - AI の役は開発の殻 archon.sh を通してだけ起こす（HOME・ARCHON_HOME・CLAUDE_CONFIG_DIR を利用の家の下へ隔離し、役は toolset.py が
#   組む選んだ物だけの設定を読む。利用者の本物の ~/.claude は読ませない）。
# - 利用の家は WORKS_USE_HOME（既定は ${XDG_STATE_HOME:-$HOME/.local/state}/works/use-<対象の clone の実際のパスの sha256 の頭 8 字>）。WORKS_DEV_HOME は継がない
#   （自分食い・実走の家と分け、走っている run の家を書き換えない）。
# - pack は対象に置かない。tests/・dev/・docs/ を除いた works/ を <家>/archon-home/workflows/works（Archon の全体の工程の置き場。
#   Archon v0.11.1 は $ARCHON_HOME/workflows/<pack>/ も探す）に起こすたびに写す。対象の作業ツリーは書かない。
# - 対象はリポジトリの下のフォルダでもよく、その git の根で回す。start で対象を省けば今いるフォルダの git の根。
# - start の旗は位置引数より前だけで読み、最初の -- で旗を終える（POSIX の Utility Syntax Guidelines 9・10）。--base と --pr は
#   どちらか 1 つ。旗を読んだ後の位置引数の数で対象を省いたかを決める。依頼の - は標準入力でなく「依頼を省く」
#   （--base か --pr が在る時だけ受ける）。依頼を省いた start は、--pr なら隔離の前に読んだ読み出しのファイル（起動ごとに一意）で
#   run を結ぶ。--base だけなら結ぶ印が無いので run を結ばず、run の控えも続きの行も書かずに結べなかった 1 行と候補の show の行を出して
#   1 で終わる（run id を名指しした show で続ける。設計書 2.3）。起動が 0 で終わり候補（依頼の写しも読み出しも持たない run）が
#   在れば、run が使う包んだ基と読み出しは消さずに <家>/unbound/<印>.json に候補と残し、clean <対象> <候補の run-id> が消す。
# - run の worktree は対象の今の姿から切る: 汚れていなければ HEAD、commit していない変更・未追跡のファイル（.gitignore の物は
#   入れない）が在れば一時の index で包んだ commit（--from）。対象の作業ツリー・index・枝は動かさない。包んだファイルは
#   <家>/wraps/<commit>.txt に控え、起動と show に出す。origin が要る（Archon v0.11.1 は --from を渡しても
#   origin の無い対象で run の worktree を切れずに落ちる）。殻は対象の remote を書き換えない。
# - 拒む（Archon を呼ばず・何も写さずに 1 行で終了コード 2）: /private/tmp の下の対象・git のリポジトリの中でない（ここまで全部）・
#   対象に pack の写し .archon/workflows/works が在る（dogfood.sh の形）・対象に remote の origin が無い・依頼が無い・認証が無い・uv か claude が無い（start。
#   check は拒まずに全部並べて 2）。
# - tdd_suite: 第 4 引数が在ればそのまま（空は輪を飛ばす）。無ければ test_cmd が pytest の 1 コマンド（前に uv run・poetry run・
#   python3 -m を許す。; & | < > $ ` を含まない）の時だけ、その末尾に JUnit XML の書き先を足す実行器を <家>/suites/ に書いて渡す。
#   それ以外は空（全部の単位を直に直す）にして 1 行で知らせる。test_cmd を省けば空（ラインの既定: 対象の宣言か CI）。
# - 最後の関所は WORKS_USE_FINAL_GATE（既定 protected_only＝守りのファイルを触った時だけ・when_needed・always）。包みは既定で入れる（WORKS_DEV_ADAPTER=0 か空の明示で外し、
#   adapter=optional と「包み無し」を出す）。入力 policy_md・gates・thickness は WORKS_USE_POLICY_MD・WORKS_USE_GATES・
#   WORKS_USE_THICKNESS（空なら渡さない）。WORKS_USE_UNATTENDED=1 は無人の run: 入力 unattended=true を渡し（判定の保留の
#   問いだけでは修正前の関所を開かない）、起動の関所を越え、人が決める関所に着いたら止めて報告へ進める。
#   WORKS_DESIGN_ONLY=1 は設計だけの run: 入力 design_only=true を渡し、修正前の関所を項目の有無に関わらず開けて止める。
#   この 2 つは未設定・空・1 だけを受け、ほかの値は start が何かを作る前に拒む（1 行で終了コード 2）。
# - 関所の文の答えの行は、この殻の answer の行（env WORKS_ANSWER_CMD。.shared/core/answer.py）。
# - herdr の枠の中（HERDR_ENV=1・HERDR_PANE_ID）で起こした run は、控えにその枠とサーバ（herdr_pane・herdr_socket）を残す。起動・show・
#   wait のたびと、答え・承認・止める・無人の続きの前後（lib.sh works_dev_continue。前に working、後に今の状態）に、run を起こした
#   枠ごとにその枠から起こした run の集計を 1 つの信号で出し、全部終わった時だけ外す（lib.sh works_dev_herdr_sync）。別の枠・枠の
#   外から打っても、起こした枠へ送る。数える控えは今の家と既定の家の全部の物。
# - 差分（run の worktree と周の頭の版の差）は <家>/diffs/run-<id>.diff に書き、対象へ当てる apply の行を出す。当てるのは人。
# 認証の順は起こし役 .shared/core/auth_launch.py（WORKS_KEYCHAIN_ITEM → 本流 claude_auth.py の写しの auth_env → Claude Code 自身の
# keychain の項目）。ここは出どころの名だけを受け、値は受けない。模型は WORKS_DEV_MODEL（ここでは埋めない。未設定なら archon.sh が既定を解く。YAML の段に
# model: を書いた役の段は、段の値が先に効く）。
# WORKS_DEV_ARCHON は Archon を呼ぶ殻の差し替え（既定は同じフォルダの archon.sh。tests/test_use.py が偽物を差す）。
set -eu

USAGE="usage: use.sh start [--base <版> | --pr <番号>] [--] [<対象リポジトリ>] <依頼の JSON か -> [<test_cmd> [<tdd_suite>]] | use.sh show <対象リポジトリ> [<run-id>] | use.sh wait <対象リポジトリ> <run-id> | use.sh answer <対象リポジトリ> <run-id> continue|stop <一言> <答えた者> | use.sh approve <対象リポジトリ> <run-id> | use.sh stop <対象リポジトリ> <run-id> <理由> | use.sh apply <対象リポジトリ> <run-id> | use.sh clean <対象リポジトリ> <run-id> | use.sh check <対象リポジトリ>"
CHANGE_INPUT=""   # 変更の入口（ラインの入力 base か pr）。--input にそのまま渡す <鍵>=<値>
if [ "${1:-}" = start ]; then
  shift
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --base | --pr)
        if [ "$#" -lt 2 ] || [ -z "$2" ]; then
          echo "$USAGE" >&2
          exit 2
        fi
        if [ -n "$CHANGE_INPUT" ]; then
          echo "use.sh: --base と --pr はどちらか 1 つだけ名指す" >&2
          exit 2
        fi
        CHANGE_INPUT="${1#--}=$2"
        shift 2
        ;;
      --)
        shift
        break
        ;;
      *) break ;;
    esac
  done
  set -- start "$@"
fi
CMD="${1:-}"
case "$CMD:$#" in
  start:2 | start:3 | start:4 | start:5 | show:2 | show:3 | wait:3 | approve:3 | answer:[5-9] | answer:[1-9][0-9] | stop:4 | apply:3 | clean:3 | check:2) ;;
  *)
    echo "$USAGE" >&2
    exit 2
    ;;
esac

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
WORKS_DIR="$(cd "$DEV_DIR/.." && pwd -P)"
ARCHON="${WORKS_DEV_ARCHON:-$DEV_DIR/archon.sh}"
WORKS_USE_SH="$DEV_DIR/use.sh"
# 文書が名指す窓口は代入の行で持つ（名指しの柵 doc-symbols が定義として見る。除外表で黙らせない）
WORKS_USE_GATES="${WORKS_USE_GATES:-}"
WORKS_USE_POLICY_MD="${WORKS_USE_POLICY_MD:-}"
WORKS_USE_THICKNESS="${WORKS_USE_THICKNESS:-}"
WORKS_USE_WAIT_SECONDS="${WORKS_USE_WAIT_SECONDS:-540}"
WORKS_USE_ALLOW_STOPPED="${WORKS_USE_ALLOW_STOPPED:-}"
export WORKS_DEV_MODEL WORKS_DEV_ADAPTER WORKS_USE_SH
# start の時の既定の釘は控えからだけ受ける（load_ledger が置く）。利用者の殻に残った値で既定を替えさせない
unset WORKS_MODEL_PINNED

refuse() {
  echo "use.sh: $*" >&2
  exit 2
}

# 1 の外の値を黙って捨てると、設計だけ・無人のつもりの run が修正まで流れる・関所で人を待つ。何かを作る前に止める
if [ "$CMD" = start ]; then
  case "${WORKS_DESIGN_ONLY:-}" in
    "" | 1) ;;
    *) refuse "WORKS_DESIGN_ONLY は 1（設計だけの run）か空（今どおり）。受けた値: ${WORKS_DESIGN_ONLY}" ;;
  esac
  case "${WORKS_USE_UNATTENDED:-}" in
    "" | 1) ;;
    *) refuse "WORKS_USE_UNATTENDED は 1（無人の run）か空（今どおり）。受けた値: ${WORKS_USE_UNATTENDED}" ;;
  esac
fi

. "$DEV_DIR/guard.sh"
works_dev_abs_claude_config

# start の引数（対象と test_cmd は省ける）
if [ "$CMD" = start ]; then
  case "$#" in
    2) TARGET_ARG="$(pwd -P)"; REQUEST_SRC="$2"; TEST_CMD="" ;;
    3) TARGET_ARG="$2"; REQUEST_SRC="$3"; TEST_CMD="" ;;
    *) TARGET_ARG="$2"; REQUEST_SRC="$3"; TEST_CMD="$4" ;;
  esac
else
  TARGET_ARG="$2"
fi

# 対象の確かめ（Archon を呼ぶ前・何かを写す前）。下のフォルダを渡されたら git の根で回す（git の道具と本線と同じ）
TARGET_REAL="$(works_dev_real "$TARGET_ARG")"
case "$TARGET_REAL" in
  /private/tmp | /private/tmp/*) refuse "対象が /private/tmp の下にある（${TARGET_REAL}）。一時フォルダの対象は使わない" ;;
esac
TOP="$(git -C "$TARGET_REAL" rev-parse --show-toplevel 2>/dev/null || true)"
if [ -z "$TOP" ]; then
  refuse "対象（${TARGET_REAL}）が git のリポジトリの中でない。git のリポジトリの根か、その下のフォルダを渡す"
fi
TARGET="$(works_dev_real "$TOP")"
if [ "$TARGET" != "$TARGET_REAL" ]; then
  echo "対象: 下のフォルダ（${TARGET_REAL}）を渡したので、git のリポジトリの根（${TARGET}）で回す"
fi

# 既定の家は clone ごとに分ける（Archon v0.11.1 は 1 つの家に同じリポジトリの clone を 1 か所しか登録できない）。
# 印は解いた根のパスから作る（symlink 越し・下のフォルダでも同じ家）。名指した家はそのまま使う。家の根 WORKS_STATE_ROOT・
# WORKS_USE_HOME・WORKS_DEV_HOME（= WORKS_USE_HOME）と claude の解決、包みの既定（WORKS_DEV_ADAPTER。0 か空を明示した時だけ
# 外す。値の検査は archon.sh）とラインの入力 adapter の値（WORKS_LAUNCH_ADAPTER_MODE）は launch.py env が持つ
works_dev_launch_env use.sh --claude --target "$TARGET"
WORKS_WRAPS_DIR="$WORKS_USE_HOME/wraps"
export WORKS_DEV_HOME WORKS_WRAPS_DIR WORKS_STATE_ROOT
works_dev_refuse_claude_tmp use.sh "WORKS_USE_HOME" "$WORKS_USE_HOME"
WORKS_ANSWER_CMD="$(A="$WORKS_USE_SH" T="$TARGET" python3 -c 'import os, shlex
print("sh {} answer {}".format(shlex.quote(os.environ["A"]), shlex.quote(os.environ["T"])))')"
export WORKS_ANSWER_CMD
# answer は答えた者を必須にするので、関所の文の答えの行の末尾に埋める穴を見せる（.shared/core/answer.py WHO_ENV）
WORKS_ANSWER_WHO="<答えた者>"
export WORKS_ANSWER_WHO

# start の前に足りない物。start は 1 つ目で止まり、check は全部並べてから終了コードを決める
PROBLEMS=""
problem() {
  if [ "$CMD" = check ]; then
    PROBLEMS="${PROBLEMS}use.sh: $*
"
  else
    refuse "$*"
  fi
}

# 認証の出どころの名（無ければ空）。順は起こし役 auth_launch.py が持つ（値はその中で読んで捨て、名だけを受ける）
auth_from() {
  python3 -I "$WORKS_DIR/.shared/core/auth_launch.py" check --user-home "$HOME" --user-config "${CLAUDE_CONFIG_DIR:-}" 2>/dev/null || true
}

# 本物の claude（隔離の前に launch.py env が解いた値。控えが置いた CLAUDE_BIN_PATH が先）。show・check も次の行に載せる
resolve_claude() {
  CLAUDE_BIN_PATH="${CLAUDE_BIN_PATH:-$WORKS_LAUNCH_CLAUDE}"
  export CLAUDE_BIN_PATH
}

if [ "$CMD" = start ] || [ "$CMD" = check ]; then
  if [ -e "$TARGET/.archon/workflows/works" ]; then
    problem "対象に pack の写し（.archon/workflows/works）がある。works 自身の直しは dogfood.sh で回す"
  fi
  if ! git -C "$TARGET" remote get-url origin >/dev/null 2>&1; then
    problem "対象に remote の origin が無い（Archon v0.11.1 は --from を渡しても run の worktree を切れずに落ちる）。対象（${TARGET}）で入れる: git remote add origin <URL>（手元だけなら対象の外に git init --bare <対象>.origin.git を作って origin にし、git push origin HEAD）"
  fi
  if [ "$CMD" = start ] && [ "$REQUEST_SRC" = - ]; then
    if [ -z "$CHANGE_INPUT" ]; then
      problem "依頼も変更も無い（依頼の JSON を - にするなら --base <版> か --pr <番号> を名指す）"
    fi
  elif [ "$CMD" = start ] && [ ! -f "$REQUEST_SRC" ]; then
    problem "依頼の JSON が無い（${REQUEST_SRC}）"
  fi
  WORKS_AUTH_FROM="$(auth_from)"
  export WORKS_AUTH_FROM
  if [ -z "$WORKS_AUTH_FROM" ]; then
    problem "$(python3 -I "$WORKS_DIR/.shared/core/auth_launch.py" howto)"
  fi
  if ! command -v uv >/dev/null 2>&1; then
    problem "uv が PATH に無い（ラインの節は uv run で回る）。入れる: curl -LsSf https://astral.sh/uv/install.sh | sh"
  fi
  resolve_claude
  if [ -z "$CLAUDE_BIN_PATH" ] || [ ! -x "$CLAUDE_BIN_PATH" ]; then
    problem "claude の実行ファイルが無い（${CLAUDE_BIN_PATH:-PATH に無い}）。claude を入れるか、CLAUDE_BIN_PATH に絶対パスを設定する"
  fi
fi

# pack を利用の家の Archon の全体の工程の置き場へ写す（一時の置き場に写してから入れ替える。ドット始まりは Archon が読まない）
place_pack() {
  _wf="$WORKS_USE_HOME/archon-home/workflows"
  mkdir -p "$_wf"
  # 家の目印: どの家がどの clone の物かを後から辿れるよう、家を作った clone の実際のパスを 1 行残す（書き直さない）
  [ -e "$WORKS_USE_HOME/target" ] || printf '%s\n' "$TARGET" >"$WORKS_USE_HOME/target"
  rm -rf "$_wf/.works.new.$$"
  works_dev_copy_pack "$WORKS_DIR" "$_wf/.works.new.$$"
  rm -rf "$_wf/works"
  mv "$_wf/.works.new.$$" "$_wf/works"
}

# run_row <run-id か空>: この対象の run（空なら一番新しい物）の「id<TAB>status<TAB>working_path」。見つからない・一覧が
# 読めなければ 1 行の理由で 1（呼び手は ROW="$(run_row …)" || exit 2）。選ぶのは lib.sh works_dev_run_json
run_row() {
  _json="$(works_dev_run_json use.sh "$ARCHON" "$TARGET" "$1")" || return 1
  printf '%s\n' "$_json" | python3 -c '
import json, sys
r = json.load(sys.stdin)
print("\t".join([r.get("id") or "", r.get("status") or "", r.get("working_path") or ""]))
'
}

# run の控え <家>/runs/<run-id>.json: start で選んだ模型（明示しなければ start の時の既定）・claude の実行ファイル・keychain の項目の名（値でなく名）・包みを残し、
# 別の殻で打つ answer・stop がそれで Archon を起こし、show が出す進める・続きの行もそれで組む（無ければ今の殻の値のまま）。
# 書くのは起動の後に run を結ぶ lib.sh works_dev_ledger_bind（dogfood.sh・real-run.sh と同じ口）、読むのは load_ledger。形は launch.py ledger
# herdr_sync [<run-id>=<状態>…]: この家と既定の家の全部の控え（lib.sh works_dev_ledger_dirs）から、run を起こした herdr の枠ごとの
# 集計を出す（lib.sh works_dev_herdr_sync）
herdr_sync() {
  works_dev_herdr_sync "$ARCHON" "$(works_dev_ledger_dirs)" "$@"
}
# detach_archon <run-id> <archon の引数…>（殻を終える）: 残りの工程をその場で回す Archon の呼び出し（respond・approve）を続きの口
# （continue.sh。前後で herdr の枠の集計を出す）ごと切り離して起こし、出力を <家>/logs/<run-id>-<時刻>.log に書いて、終わりを待たずに
# wait の行を出して返る（成否は wait と show で見る）。呼び手の殻の終了コードは起こせたかだけ（人の答え (9)(10)）。1 秒のうちに
# Archon が 0 以外で終わった時だけ（後段の集計を待たずに <ログ>.rc で見る）、ログの末尾を出してその終了コードで返る
detach_archon() {
  _rid="$1"
  shift
  mkdir -p "$WORKS_USE_HOME/logs"
  _log="$WORKS_USE_HOME/logs/${_rid}-$(date +%Y%m%d-%H%M%S)-$$.log"
  WORKS_CONTINUE_RC="$_log.rc" nohup sh "$DEV_DIR/continue.sh" "$ARCHON" "$@" >"$_log" 2>&1 </dev/null &
  _pid=$!
  sleep 1
  _st=""
  if [ -f "$_log.rc" ]; then
    _st="$(cat "$_log.rc")"
  elif ! kill -0 "$_pid" 2>/dev/null; then
    _st=0
    wait "$_pid" || _st=$?
  fi
  if [ -n "$_st" ]; then
    if [ "$_st" -ne 0 ]; then
      tail -n 20 "$_log" >&2
      echo "use.sh: archon workflow $2 が終了コード ${_st} で落ちた（全文: ${_log}）" >&2
      exit "$_st"
    fi
  fi
  echo "run ${_rid}: archon workflow $2 を切り離して起こした（pid ${_pid}。出力は ${_log}）"
  echo "状態を見る（決まった時間で戻る。まだ走っていれば打ち直す）: sh $WORKS_USE_SH wait $TARGET ${_rid}"
  exit 0
}
# ledger_latest: この対象の控えのうち一番新しく結んだ run の id（控えが無ければ空）。run-id を省いた show が一覧の先頭でなくこれを引く
ledger_latest() {
  works_dev_ledgers "$WORKS_USE_HOME/runs" |
    awk -F'\t' -v here="$(cd "$TARGET" && pwd -P)" '$2 == here && (id == "" || $3 + 0 >= at) { at = $3 + 0; id = $1 } END { print id }'
}
# 2 つ目の引数は控えで何をするかの文（既定は answer・stop の『Archon を起こす』。show は起こさないので行を組むと言う）
# 控えの無い run は今の殻の値のまま（案内も出さない）。控えは launch.py ledger load から 2 段で受け、部品が落ちれば
# （知らない版の控えなど）代入を 1 つも効かせずに止まる
load_ledger() {
  [ -f "$WORKS_USE_HOME/runs/$1.json" ] || return 0
  _ll_out=$(works_dev_launch ledger load --dir "$WORKS_USE_HOME/runs" --run-id "$1") || exit $?
  works_dev_launch_eval use.sh "$_ll_out" || exit $?
  unset _ll_out
  echo "run $1 の控え（模型 ${WORKS_DEV_MODEL:-既定 $(works_dev_model_value)}・包み ${WORKS_DEV_ADAPTER:-無し}）で${2:- Archon を起こす}（YAML の段に model: を書いた役の段は段の値）"
}

. "$DEV_DIR/lib.sh"

case "$CMD" in
  check)
    place_pack
    cd "$TARGET"
    set +e
    WORKS_DEV_NO_AUTH=1 sh "$ARCHON" validate workflows darkfactory
    validate_status=$?
    set -e
    if [ -n "$PROBLEMS" ]; then
      printf '%s' "$PROBLEMS" >&2
      exit 2
    fi
    exit "$validate_status"
    ;;
  show)
    resolve_claude
    cd "$TARGET"
    # run-id を省けば、この対象で start が結んだ一番新しい run（控えが無い時だけ一覧の一番新しい run）
    RID="${3:-$(ledger_latest)}"
    # 出す進める・続きの行も、start の控えの模型・claude・包みで組む（別の殻の値で黙って替えない）。run が見つからなければ下が言う
    if ROW="$(run_row "$RID" 2>/dev/null)"; then
      load_ledger "$(printf '%s' "$ROW" | cut -f1)" "進める・続きの行を組む（Archon は起こさない）"
    fi
    WORKS_RUN_ID="$RID"
    export WORKS_RUN_ID
    show_status=0
    works_dev_show_run use.sh "$ARCHON" "$TARGET" "$TARGET" "$WORKS_USE_HOME/diffs" || show_status=$?
    if [ -n "${ROW:-}" ]; then herdr_sync "$(printf '%s' "$ROW" | cut -f1)=$(printf '%s' "$ROW" | cut -f2)"; fi
    exit "$show_status"
    ;;
  wait)
    cd "$TARGET"
    # 選び方は show・answer と同じ run_row（この対象の darkfactory の run だけ）
    limit="$WORKS_USE_WAIT_SECONDS"
    case $limit in '' | *[!0-9]*) refuse "WORKS_USE_WAIT_SECONDS は秒の整数（受けた値: $limit）" ;; esac
    deadline=$(($(date +%s) + limit))
    while :; do
      if ! ROW="$(run_row "$3")"; then
        wait_status=1
        break
      fi
      STATUS="$(printf '%s' "$ROW" | cut -f2)"
      # 答え・承認を続きの口に渡したばかりの run（続き中の印が在る）は、Archon がまだ paused を返しても走る run と見る
      if [ "$STATUS" = paused ] && [ "$(works_dev_ledgers "$WORKS_USE_HOME/runs" "$3" | cut -f7)" = 1 ]; then
        STATUS=running
      fi
      case $STATUS in
        paused)
          echo "run $3: paused（関所で人の答えを待つ。use.sh show $TARGET $3 で関所の文と答えの行を出す）"
          wait_status=0
          break
          ;;
        completed | cancelled)
          echo "run $3: ${STATUS}（終わった。報告と差分は use.sh show で出す）"
          wait_status=5
          break
          ;;
        running | pending) ;;
        *)
          echo "run $3: ${STATUS}（落ちた。use.sh show で続ける行を出す）"
          wait_status=1
          break
          ;;
      esac
      left=$((deadline - $(date +%s)))
      if [ "$left" -le 0 ]; then
        echo "run $3: ${STATUS}（${limit} 秒のうちに関所にも終わりにも着かなかった。待つなら同じ行を打ち直す。止めるなら use.sh stop）"
        wait_status=3
        break
      fi
      [ "$left" -gt 10 ] && left=10
      sleep "$left"
    done
    if [ -n "${STATUS:-}" ]; then herdr_sync "$3=$STATUS"; fi
    exit "$wait_status"
    ;;
  answer)
    # 関所で待つ run に continue か stop で答える。人が決める関所なので、答えた者（第 6 引数。必須で、殻を打った者に落とさない）と
    # 一言を <家>/answers.jsonl に残してから Archon へ渡す（残りの工程は切り離して回し、wait の行で返る）
    case "$4" in continue | stop) ;; *) refuse "答えは continue か stop（受けた値: $4）" ;; esac
    # 同梱の graphloops の写し（0.21.0）は answer_detail を持たず、外した単位も直す義務に数えるので、効かない決定は受けない
    if [ $# -gt 6 ]; then
      case "$7" in
        --exclude*) refuse "--exclude は受けない（同梱の線が外す単位を読まず、直す義務の数から外せないため）。外したい単位と理由は continue の一言に書く" ;;
        *) refuse "第 7 引数からは受けない（受けた値: $7）" ;;
      esac
    fi
    resolve_claude
    cd "$TARGET"
    ROW="$(run_row "$3")" || exit 2
    STATUS="$(printf '%s' "$ROW" | cut -f2)"
    [ "$STATUS" = paused ] || refuse "run $3 は ${STATUS}。答えられるのは関所で待つ（paused）run だけ"
    BY="$(printf '%s' "${6:-}" | tr -d '[:space:]')"
    [ -n "$BY" ] || refuse "答えた者（第 6 引数）が無い。人が決める関所なので、決めた人の名を渡す（殻を打った者には落とさない）"
    mkdir -p "$WORKS_USE_HOME"
    RUN_ID="$3" VERB="$4" TEXT="$5" BY="$6" DIR="$TARGET" python3 -c '
import datetime, json, os
e = os.environ
row = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "run_id": e["RUN_ID"],
       "target": e["DIR"], "answer": e["VERB"], "text": e["TEXT"], "by": e["BY"]}
print(json.dumps(row, ensure_ascii=False))
' >>"$WORKS_USE_HOME/answers.jsonl"
    load_ledger "$3"
    detach_archon "$3" workflow respond "$3" "$4" "$5"
    ;;
  approve)
    # 起動の関所を越える。承認も残りの工程をその場で回すので、answer と同じく切り離して起こし、wait の行で返る
    resolve_claude
    cd "$TARGET"
    ROW="$(run_row "$3")" || exit 2
    STATUS="$(printf '%s' "$ROW" | cut -f2)"
    [ "$STATUS" = paused ] || refuse "run $3 は ${STATUS}。承認できるのは関所で待つ（paused）run だけ"
    load_ledger "$3"
    detach_archon "$3" workflow approve "$3"
    ;;
  stop)
    # 止め方を 1 つにする: 関所で待つ run は respond stop（報告へ進む）、走っている・落ちた run は止め札（stop.sh。家は殻が埋める）
    resolve_claude
    cd "$TARGET"
    ROW="$(run_row "$3")" || exit 2
    STATUS="$(printf '%s' "$ROW" | cut -f2)"
    case "$STATUS" in
      paused)
        load_ledger "$3"
        detach_archon "$3" workflow respond "$3" stop "$4"
        ;;
      completed | cancelled) refuse "run $3 は既に ${STATUS}——止める物が無い" ;;
      *) WORKS_DEV_ARCHON="$ARCHON" exec sh "$DEV_DIR/stop.sh" "$3" "$4" ;;
    esac
    ;;
  apply)
    # show と同じ組み方で差分を書き直してから当てる（git apply --check で当たるかを先に見る。消す行は明示の許しが要る）
    resolve_claude
    cd "$TARGET"
    WORKS_RUN_ID="$3"
    export WORKS_RUN_ID
    works_dev_show_run use.sh "$ARCHON" "$TARGET" "$TARGET" "$WORKS_USE_HOME/diffs" >/dev/null
    DIFF="$WORKS_USE_HOME/diffs/run-$3.diff"
    [ -s "$DIFF" ] || refuse "run $3 の差分が空か書けていない（${DIFF}）。use.sh show ${TARGET} $3 で理由を見る"
    GONE="$(git apply --numstat --summary "$DIFF" | sed -n 's/^ delete mode [0-9]* //p' | tr '\n' ' ')"
    if [ -n "$GONE" ] && [ "${WORKS_USE_ALLOW_DELETE:-}" != 1 ]; then
      refuse "差分が対象のファイルを消す（${GONE}）。消してよければ WORKS_USE_ALLOW_DELETE=1 を前に付けて打ち直す"
    fi
    # 記録が止まりを明示する run（人が最後の関所で stop と答えた・止め札・ラインの止め）は当てない。止まりの判定の正本は
    # report.stopped_run（結末を決める decide_outcome と同じ分け方）。止まりかを言える記録が無いか読めない run は 1 行出して当てる
    STOPPED="$(works_dev_run_json use.sh "$ARCHON" "$TARGET" "$3" |
      RUN_ID="$3" CORE_DIR="$WORKS_DIR/.shared/core" PYTHONDONTWRITEBYTECODE=1 python3 -c '
import json, os, sys
sys.path.insert(0, os.environ["CORE_DIR"])
import report
r = json.load(sys.stdin)
board = os.path.join(r.get("output_root") or "", "artifacts", "runs", r.get("id") or "", "board")
got = report.stopped_run(board) if os.path.isdir(board) else None
rid = os.environ["RUN_ID"]
if got is None:
    print("unknown\trun {} は止まりかどうかを記録で確かめられなかった（盤面 {}。止まりかを言える記録が無いか読めない）。当てる".format(rid, board))
elif got:
    word, by, text = got
    print("stopped\trun {} は{}（{}）で止まった: 「{}」".format(rid, report.OUTCOME_WORDS.get(word, word), by, " ".join(text.split())))
')" || exit 2
    case "$STOPPED" in
      stopped*)
        if [ "$WORKS_USE_ALLOW_STOPPED" != 1 ]; then
          refuse "${STOPPED#*	}。それでも当てるなら WORKS_USE_ALLOW_STOPPED=1 を前に付けて打ち直す"
        fi
        echo "use.sh: ${STOPPED#*	}。WORKS_USE_ALLOW_STOPPED=1 なので当てる" >&2
        ;;
      unknown*) echo "use.sh: ${STOPPED#*	}" >&2 ;;
    esac
    git apply --check "$DIFF" || refuse "差分が対象に当たらない（${DIFF}）。対象の手元の変更とぶつかっていないかを見る"
    git apply "$DIFF"
    echo "run $3 の差分を ${TARGET} に当てた（commit はしていない。テストを回してから commit する）: ${DIFF}"
    exit 0
    ;;
  clean)
    # 終わった run の worktree と枝を消す（git worktree remove・branch -D）。走っている・関所で待つ run は拒む
    cd "$TARGET"
    ROW="$(run_row "$3")" || exit 2
    STATUS="$(printf '%s' "$ROW" | cut -f2)"
    GOT="$(printf '%s' "$ROW" | cut -f3)"
    case "$STATUS" in
      running | pending | paused) refuse "run $3 は ${STATUS}。止めるか終わってから片付ける" ;;
    esac
    # start が包んだ run の基を守った参照（控えの wrap_ref）と隔離の前の読み出しのファイル（github_reads）も一緒に消す
    LEDGER_ROW="$(works_dev_ledgers "$WORKS_USE_HOME/runs" "$3")"
    WRAP_REF="$(printf '%s' "$LEDGER_ROW" | cut -f4)"
    GITHUB_READS="$(printf '%s' "$LEDGER_ROW" | cut -f8)"
    # 控えが無ければ、start が結べずに残した控え（<家>/unbound/<印>.json）のうち、候補にこの run を持ちこの対象の物の
    # 包んだ基と読み出しを消す（探すのは launch.py ledger unbound-find。参照は refs/works/wraps/ の下・読み出しは .json の
    # 絶対パスの時だけ。控えの一覧と同じ）
    UNBOUND_FILE=""
    if [ -z "$LEDGER_ROW" ] && [ -d "$WORKS_USE_HOME/unbound" ]; then
      UNBOUND_ROW="$(works_dev_launch ledger unbound-find --dir "$WORKS_USE_HOME/unbound" --target "$TARGET" --run-id "$3")" ||
        exit 2
      if [ -n "$UNBOUND_ROW" ]; then
        UNBOUND_FILE="$(printf '%s' "$UNBOUND_ROW" | cut -f1)"
        WRAP_REF="$(printf '%s' "$UNBOUND_ROW" | cut -f2)"
        GITHUB_READS="$(printf '%s' "$UNBOUND_ROW" | cut -f3)"
      fi
    fi
    if [ -n "$WRAP_REF" ] && git show-ref --verify --quiet "$WRAP_REF"; then
      git update-ref -d "$WRAP_REF"
      echo "run $3 の基を守った参照を消した: ${WRAP_REF}"
    fi
    # 読み出しのファイルが残っていれば消す（start が盤面へ写す前に止まった run）
    if [ -n "$GITHUB_READS" ] && [ -f "$GITHUB_READS" ]; then
      rm -f "$GITHUB_READS"
      echo "run $3 の隔離の前の読み出しのファイルを消した: ${GITHUB_READS}"
    fi
    if [ -n "$UNBOUND_FILE" ]; then
      rm -f "$UNBOUND_FILE"
      echo "start が結べずに残した控えを消した: ${UNBOUND_FILE}"
    fi
    if [ -z "$GOT" ] || [ ! -d "$GOT" ]; then
      echo "run $3 の worktree（${GOT:-無し}）はもう無い"
      exit 0
    fi
    BRANCH="$(git -C "$GOT" rev-parse --abbrev-ref HEAD)"
    git worktree remove --force "$GOT"
    echo "run $3 の worktree を消した: ${GOT}"
    if [ "$BRANCH" != HEAD ] && git show-ref --verify --quiet "refs/heads/$BRANCH"; then
      git branch -D "$BRANCH" >/dev/null
      echo "run $3 の枝を消した: ${BRANCH}"
    fi
    exit 0
    ;;
esac

# ---- start
# Archon に渡す worktree の土台の枝（入口の旗 --base <版> の CHANGE_INPUT とは別物）: origin の既定の枝。origin/HEAD が指す枝、
# 無ければ origin/main、次に origin/master。どれも無ければ推さずに止める（依頼の写し・読み出し・pack の写し・包んだ参照を作る前に）
ARCHON_BASE_BRANCH="$(git -C "$TARGET" symbolic-ref --quiet --short refs/remotes/origin/HEAD 2>/dev/null || true)"
ARCHON_BASE_BRANCH="${ARCHON_BASE_BRANCH#origin/}"
if [ -z "$ARCHON_BASE_BRANCH" ]; then
  for _b in main master; do
    if git -C "$TARGET" show-ref --verify --quiet "refs/remotes/origin/$_b"; then
      ARCHON_BASE_BRANCH="$_b"
      break
    fi
  done
fi
[ -n "$ARCHON_BASE_BRANCH" ] || refuse "origin の既定の枝が分からない（origin/HEAD・origin/main・origin/master のどれも無い）。git fetch origin で追跡の枝を取ってから打ち直す"

if [ -n "$WORKS_LAUNCH_ADAPTER_MODE" ]; then
  echo "包み無し（WORKS_DEV_ADAPTER=${WORKS_DEV_ADAPTER:-空}）: adapter=optional で回し、報告に出る"
fi
if [ -n "${WORKS_AUTH_FROM:-}" ]; then
  echo "認証: ${WORKS_AUTH_FROM}（値は出さない）"
fi

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
elif [ -z "$TEST_CMD" ]; then
  TDD_SUITE=""
  echo "test_cmd を省いた: ラインの既定（対象の .review-checks.json の宣言か CI）で回し、TDD の輪を飛ばす（全部の単位を直に直す）"
else
  TDD_SUITE=""
  echo "TDD の輪を飛ばす（全部の単位を直に直す）: test_cmd が pytest の 1 コマンドでない。JUnit XML を第 1 引数に書く実行器を最後の引数 <tdd_suite> に渡せば輪を回す"
fi

# 依頼の欄 pr・issue と --pr が名指した PR・issue を、Archon を起こす前に利用者の env（gh のログインが見える）のまま、対象の根を
# cwd にして 1 回だけ読む（隔離した Archon の中からは非公開のリポジトリを読めない。設計書 2.8）。--pr の base・head が読めなければ
# ここで止まる（包んだ参照も pack の写しもまだ作っていない）。名指しが無ければ何も書かない
GITHUB_READS=""
_reads="$WORKS_USE_HOME/reads/$STAMP.json"
_pr=""
case $CHANGE_INPUT in pr=*) _pr="${CHANGE_INPUT#pr=}" ;; esac
python3 -I "$WORKS_DIR/.shared/core/ghreads.py" read --repo "$TARGET" --request "${REQUEST:--}" --pr "$_pr" --out "$_reads"
if [ -f "$_reads" ]; then
  GITHUB_READS="$_reads"
  echo "名指した PR・issue を隔離の前に読んだ: ${GITHUB_READS}"
fi

place_pack
cd "$TARGET"

# run の基: 汚れていなければ HEAD。commit していない変更・未追跡が在れば、一時の index（HEAD の木から add -A。.gitignore の物は
# 入らない）で包んだ commit にする（git の plumbing。対象の作業ツリー・index・枝・タグは動かさない）。包んだ commit はどの枝にも
# 無いので、git gc に消されないよう refs/works/wraps/<commit> で守る（refs/heads・refs/tags の外。控えの wrap_ref に残し、
# clean が run と一緒に消す。run を結べない時は、下の結べなかった所で控え unbound/ に残すか、その場で外す）
BASE_REV="$(git rev-parse HEAD)"
WRAP_REF=""
if [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
  mkdir -p "$WORKS_WRAPS_DIR"
  _idx="$WORKS_WRAPS_DIR/.index.$$"
  rm -f "$_idx"
  GIT_INDEX_FILE="$_idx" git read-tree HEAD
  GIT_INDEX_FILE="$_idx" git add -A
  _tree="$(GIT_INDEX_FILE="$_idx" git write-tree)"
  rm -f "$_idx"
  BASE_REV="$(GIT_AUTHOR_NAME=works GIT_AUTHOR_EMAIL=works@localhost GIT_COMMITTER_NAME=works GIT_COMMITTER_EMAIL=works@localhost \
    git commit-tree "$_tree" -p HEAD -m "works: use.sh start が包んだ対象の手元の姿（run の基）")"
  WRAP_REF="refs/works/wraps/$BASE_REV"
  git update-ref "$WRAP_REF" "$BASE_REV"
  git diff --name-status HEAD "$BASE_REV" | tr '\t' ' ' >"$WORKS_WRAPS_DIR/$BASE_REV.txt"
  echo "包んだ（wrapped）: 対象の commit していない変更・未追跡のファイルを commit ${BASE_REV} に包み、run はそこから切る（対象は動かさない）: $(tr '\n' ' ' <"$WORKS_WRAPS_DIR/$BASE_REV.txt")"
  echo "対象: ${TARGET}（run の worktree は包んだ commit ${BASE_REV} から切る）"
else
  echo "対象: ${TARGET}（run の worktree は HEAD ${BASE_REV} から切る）"
fi

set -- workflow run darkfactory --from "$BASE_REV" --input request="$REQUEST" --input test_cmd="$TEST_CMD" \
  --input tdd_suite="$TDD_SUITE" --input adapter="$WORKS_LAUNCH_ADAPTER_MODE" --input final_gate="${WORKS_USE_FINAL_GATE:-protected_only}"
# Archon は対象を codebase に登録した時の枝を覚えて更新せず、起動のたびにその枝を fetch する（その枝が消えると起動が止まる）。
# --base が登録の枝に勝つので毎回渡す（answer・approve の再開は既存の worktree を使い直すので渡さない）
set -- "$@" --base "$ARCHON_BASE_BRANCH"
if [ -n "${WORKS_USE_POLICY_MD:-}" ]; then set -- "$@" --input policy_md="$WORKS_USE_POLICY_MD"; fi
if [ -n "${WORKS_USE_GATES:-}" ]; then set -- "$@" --input gates="$WORKS_USE_GATES"; fi
if [ -n "${WORKS_USE_THICKNESS:-}" ]; then set -- "$@" --input thickness="$WORKS_USE_THICKNESS"; fi
# 無人の run は線にも知らせる（判定の保留の問いだけでは修正前の関所を開かず、問いを報告の冒頭へ。下の stop で修正を飛ばさない）
if [ "${WORKS_USE_UNATTENDED:-}" = 1 ]; then set -- "$@" --input unattended=true; fi
if [ "${WORKS_DESIGN_ONLY:-}" = 1 ]; then set -- "$@" --input design_only=true; fi
if [ -n "$CHANGE_INPUT" ]; then
  echo "入口: 変更から（${CHANGE_INPUT}）"
  set -- "$@" --input "$CHANGE_INPUT"
fi
if [ -n "$GITHUB_READS" ]; then set -- "$@" --input github_reads="$GITHUB_READS"; fi
set +e
sh "$ARCHON" "$@"
run_status=$?
set -e
echo "workflow run の終了コード: $run_status"

# 起動の直後に、この起動の依頼（<家>/requests/<印>.json）を盤面に持つ run を 1 つに結ぶ（一覧の先頭を推定で採らない。
# 同じ家から並べた start の run と混ざらない。依頼を省いた起動は読み出しのファイル（<家>/reads/<印>.json）で結び、それも無ければ
# 結ばない）。結べなければ候補と show の行と結べなかった 1 行だけを出し、続きの行は出さない
if ! works_dev_ledger_bind use.sh "$ARCHON" "$TARGET" "$REQUEST"; then
  # 起動が 0 で終わったなら、この起動の run は起動の関所で生きていて、包んだ基と読み出しを使う（消すと承認した run が落ちる。
  # 2026-10-01 に実測）。推定では結ばず（設計書 2.3）、一覧のうち依頼の写しも読み出しも持たない darkfactory の run（launch.py が
  # 結べない文に並べる候補）を控え <家>/unbound/<印>.json に残し、clean <対象> <候補の run-id> が run の片付けと一緒に消す。
  # 候補は一覧から 1 回引く（works_dev_run_json と同じ引き方。候補の判じ方と控えの形は launch.py ledger unbound-save）
  UNBOUND_CANDIDATES=""
  if [ "$run_status" -eq 0 ] && { [ -n "$WRAP_REF" ] || [ -n "$GITHUB_READS" ]; }; then
    UNBOUND_FILE="$WORKS_USE_HOME/unbound/$STAMP.json"
    UNBOUND_CANDIDATES="$(WORKS_DEV_NO_AUTH=1 sh "$ARCHON" workflow runs --json 2>/dev/null |
      works_dev_launch ledger unbound-save --dir "$WORKS_USE_HOME/unbound" --target "$TARGET" --stamp "$STAMP" \
        --wrap-ref "$WRAP_REF" --github-reads "$GITHUB_READS")" || UNBOUND_CANDIDATES=""
  fi
  if [ -n "$UNBOUND_CANDIDATES" ]; then
    echo "この起動の run を結べなかった。包んだ基 ${WRAP_REF:-無し} と読み出し ${GITHUB_READS:-無し} は run が使うので残した。run を片付けた後に use.sh clean ${TARGET} <run-id> で消える（候補 ${UNBOUND_CANDIDATES}・控え ${UNBOUND_FILE}）"
    exit 1
  fi
  # 起動が落ちたか候補が 0 本なら、控えを書けないので clean は包んだ基の参照を知らない。ここで外す（run が切った worktree の枝が
  # 在ればその基はそこから届く）
  if [ -n "$WRAP_REF" ]; then
    git update-ref -d "$WRAP_REF"
    echo "包んだ基を守った参照を外した（どの run の控えにも結べないので）: ${WRAP_REF}"
  fi
  if [ -n "$GITHUB_READS" ]; then
    rm -f "$GITHUB_READS"
    echo "隔離の前に読んだ読み出しのファイルを消した（どの run の控えにも結べないので）: ${GITHUB_READS}"
  fi
  [ "$run_status" -ne 0 ] && exit "$run_status"
  exit 1
fi
RID="$WORKS_RUN_ID"
BOUND="$WORKS_RUN_ROW"

# 無人の run: 起動の関所を越え（残りをその場で回す）、次に人が決める関所で待っていれば止めて報告へ進める（本線の --unattended）
if [ "${WORKS_USE_UNATTENDED:-}" = 1 ] && [ "$run_status" -eq 0 ]; then
  BOUND=""   # 状態が動くので、下の show は run id で引き直す
  ROW="$(run_row "$RID")" || exit 2
  if [ "$(printf '%s' "$ROW" | cut -f2)" = paused ]; then
    echo "無人の run（WORKS_USE_UNATTENDED=1）: 起動の関所を越える（run ${RID}）"
    set +e
    works_dev_continue "$ARCHON" "$(works_dev_ledger_dirs)" "$RID" workflow approve "$RID"
    run_status=$?
    set -e
  fi
  ROW="$(run_row "$RID")" || exit 2
  if [ "$run_status" -eq 0 ] && [ "$(printf '%s' "$ROW" | cut -f2)" = paused ]; then
    echo "無人の run: 人が決める関所に着いたので止めて報告へ進める（run ${RID}）"
    set +e
    works_dev_continue "$ARCHON" "$(works_dev_ledger_dirs)" "$RID" \
      workflow respond "$RID" stop "無人の run（WORKS_USE_UNATTENDED=1）: 人が決める関所に着いたので止めて報告へ"
    run_status=$?
    set -e
  fi
fi

# 起動が落ちても結んだ run の続きの行を出す。終了コードは起動のまま（起動が 0 の時だけ show の結果）
show_status=0
WORKS_RUN_ID="$RID" WORKS_RUN_ROW="$BOUND" works_dev_show_run use.sh "$ARCHON" "$TARGET" "$TARGET" "$WORKS_USE_HOME/diffs" ||
  show_status=$?
# herdr の枠の集計（結んだ行の状態が在ればそれを使い、一覧を引き直さない）
if [ -n "$BOUND" ]; then
  herdr_sync "$RID=$WORKS_RUN_STATUS"
else
  herdr_sync
fi
[ "$run_status" -ne 0 ] && exit "$run_status"
exit "$show_status"
