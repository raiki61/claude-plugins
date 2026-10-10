#!/bin/sh
# works/dev/use.sh — ほかのリポジトリを対象に、ライン darkfactory を回す起動の殻（skills/works/SKILL.md が入口）。
#
#   use.sh start [--base <版> | --pr <番号>] [--spec] [--rounds <N> [--budget-usd <X>]] [--] [<対象リポジトリ>] <依頼の JSON か -> [<test_cmd> [<tdd_suite>]]
#                                                                           本物の AI で回す（費用が掛かる）。最初の関所で止まって戻る。
#                                                                           --base・--pr は変更から入る（差分に P1 の目を回す。依頼は - で省ける）
#                                                                           --rounds N（2 以上）は周をつなぐ鎖: wait が終わりを見るたびに次の周を起こす
#                                                                           （--budget-usd X は費用の上限。--rounds と組む時だけ）
#   use.sh show  <対象リポジトリ> [<run-id>]                                その対象で start が結んだ一番新しい run（か名指しの run）の状態・
#                                                                           次に打つ行・差分のファイルを出し直す
#   use.sh wait  <対象リポジトリ> <run-id>                                  裏で回る run を決まった時間（WORKS_USE_WAIT_SECONDS。既定 540 秒）
#                                                                           まで待ち、状態を 1 行で返す（0 = 関所で待つ・3 = まだ走っている・
#                                                                           5 = 終わった（鎖なら止めた）・1 = 落ちた・見つからない・6 = 鎖が次の周を
#                                                                           起こして結んだ（新しい run の id と次の行を出す））。鎖の周の終わりなら
#                                                                           次の周を切り離して起こす（Archon を自分では起こさない）
#   use.sh answer <対象リポジトリ> <run-id> continue|stop <一言> <答えた者> 関所で待つ run に答える（答えた者を <家>/answers.jsonl に残す）。残りの工程は切り離して回し、wait の行で返る
#   use.sh approve <対象リポジトリ> <run-id>                               起動の関所を越える（切り離して回し、wait の行で返る）
#   use.sh stop  <対象リポジトリ> <run-id> <理由>                           止める（関所で待つ run は respond stop、走っている run は止め札）
#   use.sh apply <対象リポジトリ> <run-id か鎖の id>                        その run の差分を書き直し、git apply --check の後に対象へ当てる
#                                                                           （commit しない。消す行は WORKS_USE_ALLOW_DELETE=1 の時だけ。
#                                                                           記録が止まりを示す run は WORKS_USE_ALLOW_STOPPED=1 の時だけ）。
#                                                                           鎖の id なら、元の基から採った周の結果までの差分 final.diff を同じ確かめで当てる。
#                                                                           show に鎖の id を渡せば周ごとと合計の報告 chain.md を出す
#   use.sh clean <対象リポジトリ> <run-id か鎖の id>                        終わった run の worktree と枝を消す（走っている・関所で待つ run は拒む）。
#                                                                           鎖の id なら、鎖の控えと周の結果を守る参照を消す（最後の周が生きている・次の周を起こす途中は拒む）。
#                                                                           completed・cancelled の run は wait・show が差分を書いた後に自動で消し、
#                                                                           failed などの残った run は次の start が差分を書いてから消す。
#                                                                           clean・start が消した failed の run は Archon の記録も abandon で閉じる
#                                                                           （resume できなくなるため。worktree がもう無くても閉じる）
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
#   どちらか 1 つ。--spec は判定の前に仕様の段（仕様の書き手・審査・人の承認の関所）を挟む（入力 spec=on。どの入口とも組めるが、
#   無人の run と固定材料とは組めない——線の入口が拒む）。旗を読んだ後の位置引数の数で対象を省いたかを決める。依頼の - は標準入力でなく「依頼を省く」
#   （--base か --pr が在る時だけ受ける）。どの start も起動ごとに一意の印（入力 launch_mark）を付け、起動の後にその印で
#   run を結ぶ（入口の種類で結び方を分けない。段 4.1）。結べなければ run の控えも続きの行も書かずに結べなかった 1 行と候補の
#   show の行を出して 1 で終わる（run id を名指しした show で続ける。設計書 2.3）。起動が 0 で終わり候補（依頼の写しも起動の印も持たない生きた run）が
#   在れば、run が使う包んだ基は消さずに <家>/unbound/<印>.json に候補と残し、clean <対象> <候補の run-id> が消す
#   （ほかの候補が生きている間は候補から外すだけで、最後の候補の clean で消す）。
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
# - test_cmd が対象の手元（元の clone）を走らせる形（手元の在る物を絶対パスで指す・対象を editable で入れた立てた仮想環境を掴む）なら、
#   直しの正誤に関わらず緑になり得るので、何かを写す前に「止める（test_cmd）」の行と理由の 1 行で止める（終了コード 2）。
#   確かめの殻（testcmd_check.py）そのものが落ちた時も、形を除けないので同じに止める。
#   WORKS_USE_ALLOW_TESTCMD=1（未設定・空・1 だけを受ける）なら止めずに「注意（test_cmd）」の行（落ちた時はその 1 行）を出して起こす。run・単位の worktree で
#   走らない形（対象の git が無視するパスを相対で指す）は「注意（test_cmd）」の行だけ（止めない）。決まりは testcmd_check.py。
# - 最後の関所は WORKS_USE_FINAL_GATE（既定 protected_only＝守りのファイルを触った時だけ・when_needed・always）。包みは既定で入れる（WORKS_DEV_ADAPTER=0 か空の明示で外し、
#   adapter=optional と「包み無し」を出す）。入力 policy_md・gates・thickness・features_off・features_on は WORKS_USE_POLICY_MD・
#   WORKS_USE_GATES・WORKS_USE_THICKNESS・WORKS_USE_FEATURES_OFF・WORKS_USE_FEATURES_ON（空なら渡さない。features_off・features_on は
#   切る機能・入れる機能の語のカンマ区切り。既定で off の judge_verify・auto の review_tree を on にするのは features_on。語は start が確かめる）。
#   WORKS_USE_FIX_FIXTURE は固定材料のフォルダ（前の run の h-fix が $ARTIFACTS_DIR/fix-fixture に写した物）: 空でなければ在るフォルダかを
#   確かめ（無ければ何も作らずに 2）、入力 fix_fixture=<絶対パス> を渡す（相対は殻を打ったフォルダから。同じ木・同じ依頼・同じ入力の
#   run を判定と修正案を作り直さずに修正から始める。合わなければラインの start が AI の前で止める）。WORKS_USE_UNATTENDED=1 は無人の run: 入力 unattended=true を渡し（判定の保留の
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
# keychain の項目）。ここは出どころの名だけを受け、値は受けない。模型は WORKS_DEV_MODEL（ここでは埋めない。未設定なら archon.sh が既定を解く。YAML の段は
# 段の model: で走り、明示した値は包みが前付けの無い役の段に効かせる。adapter.py の頭の 19）。
# WORKS_DEV_ARCHON は Archon を呼ぶ殻の差し替え（既定は同じフォルダの archon.sh。tests/test_use.py が偽物を差す）。
set -eu

USAGE="usage: use.sh start [--base <版> | --pr <番号>] [--spec] [--rounds <N> [--budget-usd <X>]] [--] [<対象リポジトリ>] <依頼の JSON か -> [<test_cmd> [<tdd_suite>]] | use.sh show <対象リポジトリ> [<run-id か鎖の id>] | use.sh wait <対象リポジトリ> <run-id> | use.sh answer <対象リポジトリ> <run-id> continue|stop <一言> <答えた者> | use.sh approve <対象リポジトリ> <run-id> | use.sh stop <対象リポジトリ> <run-id> <理由> | use.sh apply <対象リポジトリ> <run-id か鎖の id> | use.sh clean <対象リポジトリ> <run-id か鎖の id> | use.sh check <対象リポジトリ>"
ARCHON_BASE_BRANCH=""   # Archon の workflow run に渡す worktree の土台の枝（start・check が下で origin の既定の枝から求める。入口の旗 --base の CHANGE_INPUT とは別物）
CHANGE_INPUT=""   # 差分の根の名指し（ラインの入力 base か pr）。--input にそのまま渡す <鍵>=<値>
SPEC_INPUT=""     # 仕様の段を挟むか（旗 --spec。ラインの入力 spec=on。入口の種類に依らない任意の段）
ROUNDS=""         # 周の鎖の周の数（旗 --rounds。2 以上の時だけ鎖の控えを作る。省略と 1 は今と同じ 1 周）
BUDGET_USD=""     # 鎖の費用の上限 USD（旗 --budget-usd。--rounds と組む時だけ）
CHAIN_NEXT=""     # 鎖の次の周の起動（内部の旗 --chain-next <鎖の id>。wait の鎖の 1 歩だけが切り離して打つ）
if [ "${1:-}" = start ]; then
  shift
  while [ "$#" -gt 0 ]; do
    case "$1" in
      --rounds)
        case "${2:-}" in
          '' | *[!0-9]*) echo "use.sh: --rounds は 2 以上の整数（受けた値: ${2:-}）" >&2; exit 2 ;;
        esac
        [ "$2" -ge 1 ] || { echo "use.sh: --rounds は 2 以上の整数（受けた値: $2）" >&2; exit 2; }
        ROUNDS=""
        [ "$2" -lt 2 ] || ROUNDS="$2"
        shift 2
        ;;
      --budget-usd)
        case "${2:-}" in
          '' | *[!0-9.]* | . | *.*.* | *.) echo "use.sh: --budget-usd は正の数（受けた値: ${2:-}）" >&2; exit 2 ;;
        esac
        awk -v v="$2" 'BEGIN { exit !(v + 0 > 0) }' || { echo "use.sh: --budget-usd は正の数（受けた値: $2）" >&2; exit 2; }
        BUDGET_USD="$2"
        shift 2
        ;;
      --chain-next)
        if [ "$#" -lt 2 ] || [ -z "$2" ]; then
          echo "$USAGE" >&2
          exit 2
        fi
        CHAIN_NEXT="$2"
        shift 2
        ;;
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
      --spec)
        SPEC_INPUT=on
        shift
        ;;
      --)
        shift
        break
        ;;
      *) break ;;
    esac
  done
  if [ -n "$BUDGET_USD" ] && [ -z "$ROUNDS" ]; then
    echo "use.sh: --budget-usd は --rounds 2 以上と組む時だけ（周が 1 つなら上限を比べる相手が無い）" >&2
    exit 2
  fi
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
CHAIN_PY="$WORKS_DIR/.shared/core/chain.py"
CHAIN_DIR=""   # 鎖の控えの置き場 <家>/chains/<鎖の id>（鎖の起動か次の周の起動の時だけ）
CN_REQUEST="" CN_TEST_CMD="" CN_TDD_SUITE="" CN_FROM="" CN_BASE="" CN_MARK="" CN_ROUND="" CN_FIRST_RUN=""
# 鎖の次の周（start --chain-next）: 起動に効く環境（WORKS_USE_* と WORKS_DESIGN_ONLY）を、wait を打った殻の値ごと全部外し、鎖の控えの
# KEY=VALUE だけを戻す（1 周目と同じ環境で起きる）。対象・依頼・test_cmd・tdd_suite・起動の基・差分の根・起動の印も控えから戻す。
# 家（控えの場所）だけは親が WORKS_USE_HOME で渡す
if [ -n "$CHAIN_NEXT" ]; then
  _cn_home="${WORKS_USE_HOME:-}"
  [ -n "$_cn_home" ] || { echo "use.sh: --chain-next は鎖の家を WORKS_USE_HOME で受ける（内部の旗。wait の鎖の 1 歩が打つ）" >&2; exit 2; }
  for _v in $(env | sed -n -e 's/^\(WORKS_USE_[A-Za-z0-9_]*\)=.*/\1/p' -e 's/^\(WORKS_DESIGN_ONLY\)=.*/\1/p'); do unset "$_v"; done
  CHAIN_DIR="$_cn_home/chains/$CHAIN_NEXT"
  _cn_plan="$(python3 -I "$CHAIN_PY" plan --dir "$CHAIN_DIR")" || { echo "use.sh: 鎖 ${CHAIN_NEXT} の次の周を鎖の控え（${CHAIN_DIR}）から読めない" >&2; exit 2; }
  eval "$_cn_plan"
  WORKS_USE_HOME="$_cn_home"
  export WORKS_USE_HOME
  CHANGE_INPUT="base=$CN_BASE"
  SPEC_INPUT=""
fi
ARCHON="${WORKS_DEV_ARCHON:-$DEV_DIR/archon.sh}"
WORKS_USE_SH="$DEV_DIR/use.sh"
# 下で素のまま読む窓口の既定（set -u）
WORKS_USE_FIX_FIXTURE="${WORKS_USE_FIX_FIXTURE:-}"
WORKS_USE_WAIT_SECONDS="${WORKS_USE_WAIT_SECONDS:-540}"
WORKS_USE_ALLOW_STOPPED="${WORKS_USE_ALLOW_STOPPED:-}"
WORKS_USE_ALLOW_TESTCMD="${WORKS_USE_ALLOW_TESTCMD:-}"
export WORKS_DEV_MODEL WORKS_DEV_ADAPTER WORKS_USE_SH
# start の時の既定の釘は控えからだけ受ける（load_ledger が置く）。利用者の殻に残った値で既定を替えさせない
unset WORKS_MODEL_PINNED
# 周の事実の書き先は wait の鎖の 1 歩だけが show_run に付ける。殻に残った値で終わった run の事実を書かせない
unset WORKS_CHAIN_FACTS

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
  case "$WORKS_USE_ALLOW_TESTCMD" in
    "" | 1) ;;
    *) refuse "WORKS_USE_ALLOW_TESTCMD は 1（対象の手元を走らせる test_cmd でも起こす）か空（止める）。受けた値: ${WORKS_USE_ALLOW_TESTCMD}" ;;
  esac
  # 周をつなぐ鎖と組めない起動（Archon を起こす前に 1 行で拒む）: 設計だけの run は差分を作らず次の周の基が無く、固定材料は
  # 1 周目の修正の直前の盤面だけを指す
  if [ -n "$ROUNDS" ]; then
    [ "${WORKS_DESIGN_ONLY:-}" != 1 ] || refuse "--rounds は WORKS_DESIGN_ONLY=1 と組めない（設計だけの run は差分を作らず、次の周の基が無い）"
    [ -z "$WORKS_USE_FIX_FIXTURE" ] || refuse "--rounds は WORKS_USE_FIX_FIXTURE と組めない（固定材料は 1 周目の修正の直前の盤面で、周をつなげない）"
  fi
  # 固定材料のフォルダは打ったフォルダから絶対にする（ラインは相対を run の worktree の根から読むので、殻で解いて渡す）
  if [ -n "$WORKS_USE_FIX_FIXTURE" ]; then
    _fx="$(cd "$WORKS_USE_FIX_FIXTURE" 2>/dev/null && pwd -P)" ||
      refuse "WORKS_USE_FIX_FIXTURE は在る固定材料のフォルダ（前の run の \$ARTIFACTS_DIR/fix-fixture の写し）。受けた値: ${WORKS_USE_FIX_FIXTURE}"
    WORKS_USE_FIX_FIXTURE=$_fx
  fi
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
  # 鎖の次の周の依頼・test_cmd は鎖の控えから（依頼が空の周は - で、差分の根 base=<元の基> が入口になる）
  if [ -n "$CHAIN_NEXT" ]; then
    REQUEST_SRC="${CN_REQUEST:--}"
    TEST_CMD="$CN_TEST_CMD"
  fi
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
    problem "対象に remote の origin が無い（Archon v0.11.1 は --from を渡しても run の worktree を切れずに落ちる）。対象（${TARGET}）で入れる: git remote add origin <URL>（手元だけなら対象の外に git init --bare <対象>.origin.git を作って origin にし、git push origin HEAD の後に git remote set-head origin <push した枝>）"
  else
    # Archon に渡す worktree の土台の枝（入口の旗 --base <版> の CHANGE_INPUT とは別物）: origin の既定の枝。origin/HEAD が指す枝、
    # 無ければ origin/main、次に origin/master。どれも無ければ推さずに止める（check は並べる。start は依頼の写し・pack の
    # 写し・包んだ参照を作る前に止まる）。origin/HEAD は --short で読まない（手元に origin/main という名の枝が在ると
    # remotes/origin/main を返す）。指す先の追跡の枝が無い時（改名の後の fetch --prune で消えた枝を指したまま）も渡さずに次へ進む。
    # 手元の追跡 ref だけで求める（網に出ない。check も start も origin に届かなくても動く）
    _head="$(git -C "$TARGET" symbolic-ref --quiet refs/remotes/origin/HEAD 2>/dev/null || true)"
    ARCHON_BASE_BRANCH=""
    for _b in "${_head#refs/remotes/origin/}" main master; do
      if [ -n "$_b" ] && git -C "$TARGET" show-ref --verify --quiet "refs/remotes/origin/$_b"; then
        ARCHON_BASE_BRANCH="$_b"
        break
      fi
    done
    [ -n "$ARCHON_BASE_BRANCH" ] || problem "origin の既定の枝が分からない（origin/HEAD・origin/main・origin/master のどれも無い）。git fetch origin で追跡の枝を取り、それでも無ければ git remote set-head origin -a（または git remote set-head origin <枝>）で origin/HEAD を置いてから打ち直す"
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

# tree_commit <木の元の版> <差分のファイルか空> <親の版> <message>: 一時の index（HEAD の木から始める。空から add -A すると .gitignore に
# 当たるのに追跡している物が消える）に <木の元の版> の木を読み、差分が在れば git apply --cached --binary で当て、空なら作業ツリーを
# add -A で包んで（.gitignore の物は入らない）write-tree し、その木の commit（親は <親の版>）を標準出力に出す。start の包みと、鎖の
# 周の結果が同じ手続きを使う（git の plumbing。対象の作業ツリー・index・枝・タグは動かさない）。対象の git の中から呼ぶ
tree_commit() {
  mkdir -p "$WORKS_WRAPS_DIR"
  _tc_idx="$WORKS_WRAPS_DIR/.index.$$"
  rm -f "$_tc_idx"
  _tc_rc=0
  GIT_INDEX_FILE="$_tc_idx" git read-tree "$1" || _tc_rc=$?
  if [ "$_tc_rc" -eq 0 ] && [ -n "$2" ]; then
    GIT_INDEX_FILE="$_tc_idx" git apply --cached --binary "$2" || _tc_rc=$?
  elif [ "$_tc_rc" -eq 0 ]; then
    GIT_INDEX_FILE="$_tc_idx" git add -A || _tc_rc=$?
  fi
  if [ "$_tc_rc" -ne 0 ]; then
    rm -f "$_tc_idx"
    return "$_tc_rc"
  fi
  _tc_tree="$(GIT_INDEX_FILE="$_tc_idx" git write-tree)" || { rm -f "$_tc_idx"; return 1; }
  rm -f "$_tc_idx"
  GIT_AUTHOR_NAME=works GIT_AUTHOR_EMAIL=works@localhost GIT_COMMITTER_NAME=works GIT_COMMITTER_EMAIL=works@localhost \
    git commit-tree "$_tc_tree" -p "$3" -m "$4"
}

# chain_env_names: 起動に効く環境の名（WORKS_USE_* と WORKS_DESIGN_ONLY）のうち、鎖の控えに持つ物。wait・取り込みだけが読む窓口と、
# この殻が自分で置く WORKS_USE_SH は持たない
chain_env_names() {
  env | sed -n -e 's/^\(WORKS_USE_[A-Z0-9_][A-Z0-9_]*\)=.*/\1/p' -e 's/^\(WORKS_DESIGN_ONLY\)=.*/\1/p' |
    grep -v -x -e WORKS_USE_SH -e WORKS_USE_WAIT_SECONDS -e WORKS_USE_ALLOW_DELETE -e WORKS_USE_ALLOW_STOPPED || true
}

# chain_init: start --rounds の 1 周目を起こす前に、鎖の控え <家>/chains/<鎖の id>/chain.json を書く（周の決めは chain.py が持つ。
# ここは旗の値と、1 周目の対象・依頼の写し・test_cmd・tdd_suite・起動の環境を渡すだけ。環境の中身は chain.py も読まない）
chain_init() {
  set -- init "--dir=$CHAIN_DIR" "--id=$CHAIN_ID" "--target=$TARGET" "--rounds=$ROUNDS" "--budget=$BUDGET_USD" "--request=$REQUEST" \
    "--test-cmd=$TEST_CMD" "--tdd-suite=$TDD_SUITE" "--use-sh=$WORKS_USE_SH" "--pid=$$"
  case "$CHANGE_INPUT" in pr=*) set -- "$@" "--first-pr=${CHANGE_INPUT#pr=}" ;; esac   # 1 周目の --pr は次の依頼の pr として運ぶ
  for _ce in $(chain_env_names); do
    eval "_cv=\${$_ce}"
    # shellcheck disable=SC2154  # _cv は上の eval が置く
    set -- "$@" "--env=$_ce=$_cv"
  done
  python3 -I "$CHAIN_PY" "$@"
}

# apply_checked <差分のファイル> <止まりを見る run-id> <呼び名>: 差分を対象へ当てる確かめ（消す行は許しが要る・記録が止まりを示す run は
# 許しが要る・git apply --check）と当てる本体。run の差分（apply <run-id>）と鎖の最後の差分（apply <鎖の id>）が同じ確かめを通る。
# cd "$TARGET" した殻から呼ぶ
apply_checked() {
  _ac_diff="$1" _ac_rid="$2" _ac_label="$3"
  _ac_gone="$(git apply --numstat --summary "$_ac_diff" | sed -n 's/^ delete mode [0-9]* //p' | tr '\n' ' ')"
  if [ -n "$_ac_gone" ] && [ "${WORKS_USE_ALLOW_DELETE:-}" != 1 ]; then
    refuse "差分が対象のファイルを消す（${_ac_gone}）。消してよければ WORKS_USE_ALLOW_DELETE=1 を前に付けて打ち直す"
  fi
  # 記録が止まりを明示する run（人が最後の関所で stop と答えた・止め札・ラインの止め）は当てない。止まりの判定の正本は
  # report.stopped_run（結末を決める decide_outcome と同じ分け方）。止まりかを言える記録が無いか読めない run は 1 行出して当てる
  _ac_stopped="$(works_dev_run_json use.sh "$ARCHON" "$TARGET" "$_ac_rid" |
    RUN_ID="$_ac_rid" CORE_DIR="$WORKS_DIR/.shared/core" PYTHONDONTWRITEBYTECODE=1 python3 -c '
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
  case "$_ac_stopped" in
    stopped*)
      if [ "$WORKS_USE_ALLOW_STOPPED" != 1 ]; then
        refuse "${_ac_stopped#*	}。それでも当てるなら WORKS_USE_ALLOW_STOPPED=1 を前に付けて打ち直す"
      fi
      echo "use.sh: ${_ac_stopped#*	}。WORKS_USE_ALLOW_STOPPED=1 なので当てる" >&2
      ;;
    unknown*) echo "use.sh: ${_ac_stopped#*	}" >&2 ;;
  esac
  git apply --check "$_ac_diff" || refuse "差分が対象に当たらない（${_ac_diff}）。対象の手元の変更とぶつかっていないかを見る"
  git apply "$_ac_diff"
  echo "${_ac_label} の差分を ${TARGET} に当てた（commit はしていない。テストを回してから commit する）: ${_ac_diff}"
}

# row_of: 標準入力の run の行（lib.sh works_dev_run_json の JSON の 1 行）を「id<TAB>status<TAB>working_path」に直す。読めなければ 1
row_of() {
  python3 -c '
import json, sys
r = json.load(sys.stdin)
print("\t".join([r.get("id") or "", r.get("status") or "", r.get("working_path") or ""]))
'
}

# run_row <run-id か空>: この対象の run（空なら一番新しい物）の行（row_of の形）。見つからない・一覧が
# 読めなければ 1 行の理由で 1（呼び手は ROW="$(run_row …)" || exit 2）。選ぶのは lib.sh works_dev_run_json
run_row() {
  _json="$(works_dev_run_json use.sh "$ARCHON" "$TARGET" "$1")" || return 1
  printf '%s\n' "$_json" | row_of
}

# run の控え <家>/runs/<run-id>.json: start で選んだ模型（明示しなければ start の時の既定）・claude の実行ファイル・keychain の項目の名（値でなく名）・包みを残し、
# 別の殻で打つ answer・stop がそれで Archon を起こし、show が出す進める・続きの行もそれで組む（無ければ今の殻の値のまま）。
# 書くのは起動の後に run を結ぶ lib.sh works_dev_ledger_bind（dogfood.sh と同じ口）、読むのは load_ledger。形は launch.py ledger
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
  echo "run $1 の控え（模型 ${WORKS_DEV_MODEL:-既定 $(works_dev_model_value)}・包み ${WORKS_DEV_ADAPTER:-無し}）で${2:- Archon を起こす}（段は YAML の model:。明示した模型は包みを通せば前付けの無い役の段に効く）"
}

. "$DEV_DIR/lib.sh"

# clean_run <run-id> <run の行（row_of の形）>: 終わった run の worktree・枝・控え（と、その worktree から切った単位の worktree・参照）を消す。手の道（clean）と自動の道（auto_clean・
# sweep_old_runs）が呼ぶ片付けの本体の 1 か所。生きた run かの判定は呼び手が済ませる。cd "$TARGET" した殻から呼ぶ。
# 生きてもいず終わってもいない run（Archon の failed）の記録は「resume できる＝人の番」と言い続け、herdr の枠の集計
# （lib.sh works_dev_herdr_sync）はそれを人の番に数える。片付けた run は resume できないので、片付けが済んだ後に記録を close_record で
# 閉じる。状態の一覧は launch.py の LIVE_STATUSES・DONE_STATUSES（ledger live・ledger done）だけで決め、確かめが落ちたら何も消さずに 2 で返る。
# worktree がもう無い run でも閉じる（前に片付けて記録だけ残った run は clean の打ち直しで閉じる）。返す値は片付けの結果だけで、
# 閉じられなかった時は close_record が標準エラーに出し、その終了コードを CLOSE_STATUS に置く（閉じた run の id は CLOSED_RUNS に足す）
clean_run() {
  CLOSE_STATUS=0
  _cr_st="$(printf '%s' "$2" | cut -f2)"
  _cr_close=""
  if [ -n "$_cr_st" ]; then
    _cr_live="$(works_dev_launch ledger live --status "$_cr_st")" || return 2
    _cr_done="$(works_dev_launch ledger "done" --status "$_cr_st")" || return 2
    [ -n "$_cr_live" ] || [ -n "$_cr_done" ] || _cr_close=1
  fi
  clean_files "$1" "$2" || return $?
  if [ -n "$_cr_close" ]; then
    close_record "$1" "$_cr_st" || CLOSE_STATUS=$?
  fi
  return 0
}

# close_record <run-id> <状態>: 片付けた run の Archon の記録を abandon で閉じる（Archon v0.11.1 の abandon は記録を cancelled にする）。
# 閉じた run の id を CLOSED_RUNS（空白区切り）に足す。落ちたら、片付けは済んだことと打ち直しの行を標準エラーに出し、abandon の終了コードで返る
close_record() {
  _cl_rc=0
  WORKS_DEV_NO_AUTH=1 sh "$ARCHON" workflow abandon "$1" || _cl_rc=$?
  if [ "$_cl_rc" -ne 0 ]; then
    echo "use.sh: run ${1} の worktree・枝・控えは片付けたが、Archon の記録（${2}）を abandon で閉じられなかった（終了コード ${_cl_rc}）。記録は resume できると言い続け、herdr の枠は人の番のまま残る。打ち直す: sh ${WORKS_USE_SH} clean ${TARGET} ${1}（Archon を直に: cd ${TARGET} && WORKS_DEV_HOME=${WORKS_USE_HOME} WORKS_DEV_NO_AUTH=1 sh ${ARCHON} workflow abandon ${1}）" >&2
    return "$_cl_rc"
  fi
  echo "run ${1} の Archon の記録を閉じた（${2} → abandon。片付けた run は resume できない）"
  CLOSED_RUNS="${CLOSED_RUNS:+${CLOSED_RUNS} }$1"
  return 0
}

# clean_files <run-id> <run の行>: clean_run の片付けの部分（記録には触らない）
clean_files() {
  GOT="$(printf '%s' "$2" | cut -f3)"
  # start が包んだ run の基を守った参照（控えの wrap_ref。refs/works/wraps/ の下の時だけ）も一緒に消す
  # drop_kept <run-id> <包んだ基の参照>
  drop_kept() {
    if [ -n "$2" ] && git show-ref --verify --quiet "$2"; then
      git update-ref -d "$2"
      echo "run $1 の基を守った参照を消した: ${2}"
    fi
  }
  LEDGER_ROW="$(works_dev_ledgers "$WORKS_USE_HOME/runs" "$1")"
  drop_kept "$1" "$(printf '%s' "$LEDGER_ROW" | cut -f4)"
  # 控えが無ければ、start が結べずに残した控え（<家>/unbound/<印>.json）のうち、候補にこの run を持ちこの対象の物を全部引く
  # （launch.py ledger unbound-release。控えごとに 1 行）。ほかの候補がまだ生きている間は、その run が使うかもしれないので
  # 包んだ基を消さず、控えの候補からこの run だけを外す。最後の候補で全部消す
  if [ -z "$LEDGER_ROW" ] && [ -d "$WORKS_USE_HOME/unbound" ]; then
    UNBOUND_ROWS="$(WORKS_DEV_NO_AUTH=1 sh "$ARCHON" workflow runs --json 2>/dev/null |
      works_dev_launch ledger unbound-release --dir "$WORKS_USE_HOME/unbound" --target "$TARGET" --run-id "$1")" || return 2
    while IFS= read -r _row; do
      [ -n "$_row" ] || continue
      _file="$(printf '%s' "$_row" | cut -f1)"
      _alive="$(printf '%s' "$_row" | cut -f3)"
      if [ -n "$_alive" ]; then
        echo "start が結べずに残した控えの候補から run $1 を外した。包んだ基は、まだ生きている候補 ${_alive} が使うかもしれないので残した（最後の候補の clean で消える）: ${_file}"
        continue
      fi
      drop_kept "$1" "$(printf '%s' "$_row" | cut -f2)"
      rm -f "$_file"
      echo "start が結べずに残した控えを消した: ${_file}"
    done <<EOF
$UNBOUND_ROWS
EOF
  fi
  if [ -z "$GOT" ] || [ ! -d "$GOT" ]; then
    echo "run $1 の worktree（${GOT:-無し}）はもう無い"
    return 0
  fi
  # 呼び手は `|| …` で呼ぶので set -e が効かない。落ちたら次へ進まず return で返す
  BRANCH="$(git -C "$GOT" rev-parse --abbrev-ref HEAD)" || return $?
  # 修正の段が run の worktree から切った単位の worktree と守りの参照（refs/works/units/<印>/ の下）を先に片付ける
  # （unittrees.sweep。止まった run の残り。印は run の worktree の実パスから引くので、worktree を消す前に呼ぶ）
  _swept="$(CORE_DIR="$WORKS_DIR/.shared/core" PYTHONDONTWRITEBYTECODE=1 python3 -c '
import os, sys
sys.path.insert(0, os.environ["CORE_DIR"])
import unittrees
for p in unittrees.sweep(sys.argv[1]):
    print(p)
' "$GOT")" || return $?
  if [ -n "$_swept" ]; then
    printf '%s\n' "$_swept" | while IFS= read -r _p; do echo "run $1 の単位の worktree を消した: ${_p}"; done
  fi
  git worktree remove --force "$GOT" || return $?
  echo "run $1 の worktree を消した: ${GOT}"
  if [ "$BRANCH" != HEAD ] && git show-ref --verify --quiet "refs/heads/$BRANCH"; then
    git branch -D "$BRANCH" >/dev/null || return $?
    echo "run $1 の枝を消した: ${BRANCH}"
  fi
  return 0
}

# is_done <状態>: 終わった状態（launch.py の DONE_STATUSES。ledger done）なら 0。
# 確かめが落ちた時は終わったと読まない（片付けず・止めを拒まない側）
is_done() {
  [ -n "$(works_dev_launch ledger "done" --status "$1" 2>/dev/null)" ]
}

# auto_clean <run-id> <run の行> <差分を書いた works_dev_show_run の終了コード>: 終わった run（呼び手が is_done で済ませる）を、
# 差分を書き終えた後に片付ける。消してよいかは「差分の書き出しが 0」だけで決める。failed は呼ばれず残る
# （Archon の resume は前の worktree を使い直すので、消すと commit されない修正が再開で戻らない。残した failed は次の start の
# sweep_old_runs が消す）
auto_clean() {
  if [ "$3" -ne 0 ]; then
    echo "run $1: 差分を書けなかった（works_dev_show_run が終了コード ${3}）ので worktree・枝・控えを片付けなかった"
    return 0
  fi
  echo "run $1: 終わって差分を書き終えたので worktree・枝・控えを片付ける（差分のファイルは残す）"
  clean_run "$1" "$2" || echo "run $1: 片付けが終了コード $? で止まった（use.sh clean で打ち直せる）"
  return 0
}

# pid_alive <pid>: その process が居て、終わって親に引き取られるのを待つだけの状態（Z）でもない
pid_alive() {
  { [ -n "$1" ] && kill -0 "$1" 2>/dev/null; } || return 1
  _pa_st="$(ps -o stat= -p "$1" 2>/dev/null || true)"
  case "$_pa_st" in Z*) return 1 ;; *) return 0 ;; esac
}

# chain_wait_bound <鎖の控えの置き場>: 次の周の run が控えに結ばれる（pending の run が入る）のを、wait の期限（deadline）まで待つ。
# 結ばれたら 0 と run の id を標準出力に出す。子の pid が死んで結ばれないまま・期限が来たら 1
chain_wait_bound() {
  while :; do
    _cb="$(python3 -I "$CHAIN_PY" pending --dir "$1")" || return 1
    _cb_run="$(printf '%s' "$_cb" | cut -f1)"
    if [ -n "$_cb_run" ]; then
      printf '%s\n' "$_cb_run"
      return 0
    fi
    pid_alive "$(printf '%s' "$_cb" | cut -f2)" || return 1
    [ "$(date +%s)" -lt "$deadline" ] || return 1
    sleep 1
  done
}

# chain_step <鎖の id> <run-id> <周の事実のファイル> <差分を書いた show_run の終了コード>: 終わった周の run を鎖に足し、次の周を切り離して
# 起こすか止めるかを進める（周の決めは chain.py。ここは git の手続きと切り離した起動だけ）。錠 <鎖>/chain.json.lock は周の結果を
# 作ってから子の pid を控えに書くまで持ち続け（同じ run に wait を重ねて打っても 2 本目を起こさない）、待つ前に外す。
# 終了コードの案は CHAIN_STATUS に置く（6 = 次の周を結んだ・5 = 止めた・3 = 結ぶのを待つうちに期限が来た・1 = 鎖を進められない）
chain_step() {
  _cs_id="$1" _cs_rid="$2" _cs_facts="$3" _cs_dst="$4"   # 下の set -- が位置引数を使うので先に控える
  _cs_dir="$WORKS_USE_HOME/chains/$_cs_id"
  CHAIN_STATUS=1
  exec 8>"$_cs_dir/chain.json.lock"
  python3 -I "$CHAIN_PY" hold 8 || { exec 8>&-; echo "鎖 $_cs_id: 控えの錠を取れない"; return 0; }
  _cs_diff="$WORKS_USE_HOME/diffs/run-$_cs_rid.diff"
  _cs_prep="$(python3 -I "$CHAIN_PY" --held prep --dir "$_cs_dir" --run "$_cs_rid" --facts "$_cs_facts")" || { exec 8>&-; echo "鎖 $_cs_id: run $_cs_rid は鎖の今の周でない"; return 0; }
  _cs_round="$(printf '%s' "$_cs_prep" | cut -f1)"
  _cs_from="$(printf '%s' "$_cs_prep" | cut -f2)"
  _cs_base="$(printf '%s' "$_cs_prep" | cut -f3)"
  # 周の結果: その周の起点の木に run-<id>.diff を当て、前の周の結果を親にした commit。参照で守る（run の worktree が片付いた後も、
  # 次の周の起点と最後の差分がここから届く）。差分が無い周（空の差分）は結果を作らない（chain.py が進みの無い周と読む）
  set -- --unwritten "" --diff "$_cs_diff"
  if [ "$_cs_round" = done ]; then
    : # 同じ run に wait を打ち直した: 周は足してあるので、結果も作らず控えの今の姿で決め直す
  elif [ "$_cs_dst" -ne 0 ]; then
    set -- --unwritten "差分を書けなかった（works_dev_show_run が終了コード $_cs_dst）" --diff "$_cs_diff"
  elif [ -s "$_cs_diff" ]; then
    if _cs_res="$(cd "$TARGET" && tree_commit "$_cs_base" "$_cs_diff" "$_cs_from" "works: 鎖 $_cs_id の周 ${_cs_round} の結果")" &&
      git -C "$TARGET" update-ref "refs/works/chains/$_cs_id/${_cs_round}" "$_cs_res"; then
      set -- --unwritten "" --diff "$_cs_diff" --result "$_cs_res" --result-tree "$(git -C "$TARGET" rev-parse "$_cs_res^{tree}")" \
        --from-tree "$(git -C "$TARGET" rev-parse "$_cs_from^{tree}" 2>/dev/null || true)"
    else
      set -- --unwritten "周の結果の commit を作れなかった（差分 ${_cs_diff} を周の起点 ${_cs_base} に当てられない）" --diff "$_cs_diff"
    fi
  fi
  _cs_out="$(python3 -I "$CHAIN_PY" --held step --dir "$_cs_dir" --run "$_cs_rid" --facts "$_cs_facts" "$@")" || { exec 8>&-; echo "鎖 $_cs_id: 鎖の控えを進められなかった"; return 0; }
  _cs_act="$(printf '%s' "$_cs_out" | cut -f1)"
  case "$_cs_act" in
    launch)
      _cs_n="$(printf '%s' "$_cs_out" | cut -f2)"
      _cs_log="$_cs_dir/round-${_cs_n}.log"
      echo "鎖 $_cs_id: 周 ${_cs_n} を切り離して起こす（前の周は run ${_cs_rid}。出力は ${_cs_log}）"
      WORKS_USE_HOME="$WORKS_USE_HOME" nohup sh "$WORKS_USE_SH" start --chain-next "$_cs_id" "$TARGET" - >"$_cs_log" 2>&1 </dev/null 8>&- &
      python3 -I "$CHAIN_PY" --held pid --dir "$_cs_dir" --pid "$!" --log "$_cs_log"
      exec 8>&-
      ;;
    wait)
      exec 8>&-
      echo "鎖 $_cs_id: 次の周の起動を待つ（$(printf '%s' "$_cs_out" | cut -f2)）"
      ;;
    follow) exec 8>&- ;;
    aborted)
      # 途中で落ちた周は周に足していない（run は鎖の今の周のまま）。次の周が結ばれたと言わず、resume で続けた後の wait に任せる
      exec 8>&-
      echo "鎖 $_cs_id: run ${_cs_rid} は途中で落ちた周で、鎖は進めない（$(printf '%s' "$_cs_out" | cut -f2)）"
      return 0
      ;;
    stop)
      _cs_word="$(printf '%s' "$_cs_out" | cut -f2)"
      _cs_text="$(printf '%s' "$_cs_out" | cut -f3)"
      # 最後の差分: 元の基から、止まりと言われていない最後の周の結果まで（止まった周は採らず、chain.md が差分を名指す）
      _cs_kept="$(python3 -I "$CHAIN_PY" pick --dir "$_cs_dir")"
      rm -f "$_cs_dir/final.diff"
      if [ -n "$_cs_kept" ]; then
        git -C "$TARGET" diff --binary --no-ext-diff "$(printf '%s' "$_cs_kept" | cut -f4)" "$(printf '%s' "$_cs_kept" | cut -f3)" >"$_cs_dir/final.diff" ||
          { rm -f "$_cs_dir/final.diff"; _cs_kept=""; echo "鎖 $_cs_id: 最後の差分を書けなかった（git diff が落ちた）"; }
      fi
      python3 -I "$CHAIN_PY" render --dir "$_cs_dir" >/dev/null
      exec 8>&-
      echo "鎖 $_cs_id を止めた（${_cs_word}: ${_cs_text}）。報告: $_cs_dir/chain.md"
      if [ -n "$_cs_kept" ]; then
        echo "最後の差分（元の基から周 $(printf '%s' "$_cs_kept" | cut -f1) の結果まで）: $_cs_dir/final.diff。取り込む: sh $WORKS_USE_SH apply $TARGET $_cs_id"
      else
        echo "最後の差分に採れる周が無い（止まっていない周が無い）。報告で止まった周の差分を見る"
      fi
      CHAIN_STATUS=5
      return 0
      ;;
    *)
      exec 8>&-
      echo "鎖 $_cs_id: ${_cs_out}"
      return 0
      ;;
  esac
  # 次の周の run が結ばれるのを期限まで待つ（錠は外した後。子が控えに run を書く）
  if _cs_next="$(chain_wait_bound "$_cs_dir")"; then
    echo "鎖 $_cs_id: 次の周を起こして結んだ。run ${_cs_next}。待つ: sh $WORKS_USE_SH wait $TARGET ${_cs_next}"
    CHAIN_STATUS=6
  else
    echo "鎖 $_cs_id: 次の周の run はまだ結ばれていない（子の出力: $_cs_dir/round-*.log）。待つなら同じ行を打ち直す（起動が落ちていれば起こし直すか止める）: sh $WORKS_USE_SH wait $TARGET $_cs_rid"
    CHAIN_STATUS=3
  fi
  return 0
}

# sweep_old_runs: start が Archon を起こす前に、この対象の生きていない run（failed も含む。持ち主の決め: 次の start が前の run を片付ける。古い run は
# resume しない）の worktree・枝・控えを clean_run で消す。生きた状態は launch.py の LIVE_STATUSES（ledger live）の 1 か所で決め、
# 状態が読めない・確かめが落ちた run は残す（迷ったら残す）。消す前に差分を <家>/diffs に書き、書けなければ残して理由を出す。
# 片付けた run の id と状態は 1 行ずつ出し、「<id>（<状態>）」を・で並べて CLEANED_RUNS に置く（start が入力 cleaned_runs で
# 報告の冒頭 2 へ渡す）。cd "$TARGET" した殻から呼ぶ
sweep_old_runs() {
  CLEANED_RUNS=""
  CLOSED_RUNS=""
  # 一覧が引けない・読めない時は、片付けが走らなかったことと理由（run_json の 1 行）を出す（黙って 0 で返さない）
  _sw_json="$(works_dev_run_json use.sh "$ARCHON" "$TARGET" all 2>&1)" || {
    echo "前の run の片付けは走らなかった（run の一覧を引けない）: ${_sw_json}"
    return 0
  }
  while IFS= read -r _sw_one; do
    [ -n "$_sw_one" ] || continue
    _sw_row="$(printf '%s\n' "$_sw_one" | row_of)" || {
      echo "前の run の片付けを 1 行飛ばした（一覧の行が JSON として読めない）: ${_sw_one}"
      continue
    }
    _sw_id="$(printf '%s' "$_sw_row" | cut -f1)"
    _sw_st="$(printf '%s' "$_sw_row" | cut -f2)"
    { [ -n "$_sw_id" ] && [ -n "$_sw_st" ]; } || continue
    _sw_live="$(works_dev_launch ledger live --status "$_sw_st")" || {
      echo "前の run ${_sw_id}（${_sw_st}）: 生きた状態かを確かめられなかったので片付けなかった"
      continue
    }
    [ -z "$_sw_live" ] || continue
    _sw_diff=0
    # 呼び手の殻に WORKS_RUN_ROW が残っていても、この前の run の行で上書きする（でないと別の run の差分を書いて片付けの門を通る）
    WORKS_RUN_ID="$_sw_id" WORKS_RUN_ROW="$_sw_one" works_dev_show_run use.sh "$ARCHON" "$TARGET" "$TARGET" "$WORKS_USE_HOME/diffs" >/dev/null || _sw_diff=$?
    if [ "$_sw_diff" -ne 0 ]; then
      echo "前の run ${_sw_id}（${_sw_st}）: 差分を書けなかった（works_dev_show_run が終了コード ${_sw_diff}）ので片付けなかった"
      continue
    fi
    echo "前の run ${_sw_id}（${_sw_st}）を片付ける（差分は ${WORKS_USE_HOME}/diffs/run-${_sw_id}.diff。resume はしない）"
    if clean_run "$_sw_id" "$_sw_row"; then
      CLEANED_RUNS="${CLEANED_RUNS:+${CLEANED_RUNS}・}${_sw_id}（${_sw_st}）"
    else
      echo "前の run ${_sw_id}: 片付けが終了コード $? で止まった（use.sh clean で打ち直せる）"
    fi
  done <<EOF
$_sw_json
EOF
  # 記録を閉じた run を起こした枠の集計を、片付けの後に 1 回だけ出し直す（id は Archon の run の id で空白を含まない）
  # shellcheck disable=SC2086
  [ -z "$CLOSED_RUNS" ] || herdr_sync $CLOSED_RUNS
  return 0
}

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
    # 鎖の id なら、周ごとと合計の報告 chain.md（今の控えから描き直す。止めていない鎖は途中の姿）を出す
    if [ -f "$WORKS_USE_HOME/chains/${3:-}/chain.json" ]; then
      exec python3 -I "$CHAIN_PY" render --dir "$WORKS_USE_HOME/chains/$3"
    fi
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
    if [ -n "${ROW:-}" ] && is_done "$(printf '%s' "$ROW" | cut -f2)"; then
      auto_clean "$(printf '%s' "$ROW" | cut -f1)" "$ROW" "$show_status"
    fi
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
      if is_done "$STATUS"; then
        echo "run $3: ${STATUS}（終わった。報告と差分は use.sh show で出す）"
        wait_status=5
        # 出力は捨てる（wait は状態を 1 行で返す）。show_run は CLAUDE_BIN_PATH を読むので wait でも解く
        resolve_claude
        diff_status=0
        # 鎖の周の run なら、差分と一緒に周の事実（結末・費用・分・起点の版）も書く（WORKS_CHAIN_FACTS）
        chain_id="$(python3 -I "$CHAIN_PY" of-run --home "$WORKS_USE_HOME" --run "$3" 2>/dev/null)" || chain_id=""
        chain_facts=""
        [ -z "$chain_id" ] || chain_facts="$WORKS_USE_HOME/chains/$chain_id/facts-$3.json"
        WORKS_CHAIN_FACTS="$chain_facts" WORKS_RUN_ID="$3" works_dev_show_run use.sh "$ARCHON" "$TARGET" "$TARGET" "$WORKS_USE_HOME/diffs" >/dev/null || diff_status=$?
        auto_clean "$(printf '%s' "$ROW" | cut -f1)" "$ROW" "$diff_status"
        if [ -n "$chain_id" ]; then
          chain_step "$chain_id" "$3" "$chain_facts" "$diff_status"
          wait_status=$CHAIN_STATUS
        fi
        break
      fi
      case $STATUS in
        paused)
          echo "run $3: paused（関所で人の答えを待つ。use.sh show $TARGET $3 で関所の文と答えの行を出す）"
          wait_status=0
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
    ! is_done "$STATUS" || refuse "run $3 は既に ${STATUS}——止める物が無い"
    case "$STATUS" in
      paused)
        load_ledger "$3"
        detach_archon "$3" workflow respond "$3" stop "$4"
        ;;
      *) WORKS_DEV_ARCHON="$ARCHON" exec sh "$DEV_DIR/stop.sh" "$3" "$4" ;;
    esac
    ;;
  apply)
    # show と同じ組み方で差分を書き直してから当てる（git apply --check で当たるかを先に見る。消す行は明示の許しが要る）
    resolve_claude
    cd "$TARGET"
    # 鎖の id なら、鎖が止まった時に書いた最後の差分（元の基から、止まりと言われていない最後の周の結果まで）を同じ確かめで当てる
    if [ -f "$WORKS_USE_HOME/chains/$3/chain.json" ]; then
      CHAIN_DIR="$WORKS_USE_HOME/chains/$3"
      _ap_kept="$(python3 -I "$CHAIN_PY" pick --dir "$CHAIN_DIR")" || exit 2
      [ -f "$CHAIN_DIR/final.diff" ] || refuse "鎖 $3 の最後の差分がまだ無い（鎖が止まっていないか、採れる周が無い）。use.sh show ${TARGET} $3 で報告を見る"
      [ -s "$CHAIN_DIR/final.diff" ] || refuse "鎖 $3 の最後の差分が空（元の基から採った周の結果までに変更が無い）。use.sh show ${TARGET} $3 で報告を見る"
      apply_checked "$CHAIN_DIR/final.diff" "$(printf '%s' "$_ap_kept" | cut -f2)" "鎖 $3（周 $(printf '%s' "$_ap_kept" | cut -f1)）"
      exit 0
    fi
    WORKS_RUN_ID="$3"
    export WORKS_RUN_ID
    diff_status=0
    works_dev_show_run use.sh "$ARCHON" "$TARGET" "$TARGET" "$WORKS_USE_HOME/diffs" >/dev/null || diff_status=$?
    [ "$diff_status" -eq 0 ] || refuse "run $3 の差分を書き直せなかった（works_dev_show_run が終了コード ${diff_status}）。前の差分は当てない。use.sh show ${TARGET} $3 で理由を見る"
    DIFF="$WORKS_USE_HOME/diffs/run-$3.diff"
    [ -s "$DIFF" ] || refuse "run $3 の差分が空か書けていない（${DIFF}）。use.sh show ${TARGET} $3 で理由を見る"
    apply_checked "$DIFF" "$3" "run $3"
    exit 0
    ;;
  clean)
    # 終わった run の worktree と枝を消す（git worktree remove・branch -D）。走っている・関所で待つ run は拒む
    cd "$TARGET"
    # 鎖の id なら、鎖の控えと周の結果を守る参照を消す。次の周を起こす途中（pending が残る）か、最後の周の run が生きていれば、
    # 今の clean と同じ文で拒む（生きた状態の判定は下と同じ ledger live）
    if [ -f "$WORKS_USE_HOME/chains/$3/chain.json" ]; then
      CHAIN_DIR="$WORKS_USE_HOME/chains/$3"
      _cc="$(python3 -I "$CHAIN_PY" pending --dir "$CHAIN_DIR")" || exit 2
      _cc_run="$(printf '%s' "$_cc" | cut -f1)"
      _cc_last="$(printf '%s' "$_cc" | cut -f7)"
      if [ -n "$(printf '%s' "$_cc" | cut -f4)" ] && [ -z "$_cc_run" ]; then
        refuse "鎖 $3 は次の周を起こす途中（pending が残っている）。止めるか終わってから片付ける"
      fi
      for _cc_id in $_cc_run $_cc_last; do
        if _cc_row="$(run_row "$_cc_id" 2>/dev/null)"; then
          _cc_st="$(printf '%s' "$_cc_row" | cut -f2)"
          [ -z "$_cc_run" ] || [ "$_cc_id" != "$_cc_run" ] || refuse "run ${_cc_id} は ${_cc_st}。止めるか終わってから片付ける"
          _cc_live="$(works_dev_launch ledger live --status "$_cc_st")" || exit 2
          [ -z "$_cc_live" ] || refuse "run ${_cc_id} は ${_cc_st}。止めるか終わってから片付ける"
        fi
      done
      git for-each-ref --format='%(refname)' "refs/works/chains/$3/" | while IFS= read -r _cc_ref; do git update-ref -d "$_cc_ref"; done
      rm -rf "$CHAIN_DIR"
      echo "鎖 $3 の控え（${CHAIN_DIR}）と周の結果を守る参照（refs/works/chains/$3/）を消した"
      exit 0
    fi
    ROW="$(run_row "$3")" || exit 2
    STATUS="$(printf '%s' "$ROW" | cut -f2)"
    # 生きた状態の一覧は launch.py の LIVE_STATUSES の 1 か所（ledger live）。確かめが落ちたら生きていないと読まずに止める
    # （生きた run の使う物を消すか決める所は、迷ったら残す）
    LIVE="$(works_dev_launch ledger live --status "$STATUS")" || exit 2
    if [ -n "$LIVE" ]; then
      refuse "run $3 は ${STATUS}。止めるか終わってから片付ける"
    fi
    # 落ちた run の記録を閉じるのは clean_run（閉じられなければ片付けの行は出したまま、abandon の終了コードで終わる）
    RID="$(printf '%s' "$ROW" | cut -f1)"
    CLOSED_RUNS=""
    clean_status=0
    clean_run "$RID" "$ROW" || clean_status=$?
    [ "$clean_status" -eq 0 ] || exit "$clean_status"
    [ -z "$CLOSED_RUNS" ] || herdr_sync "$RID"
    exit "$CLOSE_STATUS"
    ;;
esac

# ---- start
# run・単位の worktree は commit から切るので、対象の git が無視する物（.venv・node_modules など）が無い。test_cmd の形を
# testcmd_check.py が分ける（決まりはそちら）: 対象の手元（元の clone）を走らせる形（絶対パスで手元を指す・対象を editable で
# 入れた立てた仮想環境を掴む）は、直しの正誤に関わらず緑になり得るので、依頼の写し・実行器・pack の写しを作る前に止める（2）。
# WORKS_USE_ALLOW_TESTCMD=1 なら「注意」の行を出して起こす。worktree で走らない形（相対の .venv など。走れば落ちて分かる）は
# 「注意」の行だけで止めない。確かめの殻そのものが落ちた（0・3 の外）時も、手元を走らせる形を除けないので止める（止めを外せば
# 落ちたことを出して起こす）
_tc_rc=0
_tc_out="$(python3 -I "$DEV_DIR/testcmd_check.py" ${WORKS_USE_ALLOW_TESTCMD:+--allow-checkout} "$TARGET" "$TEST_CMD")" || _tc_rc=$?
case "$_tc_rc" in
  0) [ -z "$_tc_out" ] || printf '%s\n' "$_tc_out" ;;
  3)
    if [ "$WORKS_USE_ALLOW_TESTCMD" = 1 ]; then
      printf '%s\n' "$_tc_out"
      echo "WORKS_USE_ALLOW_TESTCMD=1 なので止めずに起こす（上の形は worktree の直しでなく対象の手元を試し得る）"
    else
      printf '%s\n' "$_tc_out" >&2
      refuse "test_cmd が対象の手元（${TARGET}）を走らせる形なので、Archon を起こさずに止めた（run の試験が直しでなく手元のコードを試し、直しの正誤に関わらず緑になり得る）。worktree の中で環境を作り worktree の相対で書く形（例 uv run pytest -q。npm は npm ci && npm test）にして打ち直す。形を知った上でそのまま回すなら WORKS_USE_ALLOW_TESTCMD=1 を前に付けて打ち直す（works/README.md の「test_cmd と worktree」）"
    fi
    ;;
  *)
    # 確かめそのものが落ちた: 手元を走らせる形を除けないので、止める形と同じに止める（止めを外せば注意として出して起こす）
    [ -z "$_tc_out" ] || printf '%s\n' "$_tc_out" >&2
    if [ "$WORKS_USE_ALLOW_TESTCMD" = 1 ]; then
      echo "use.sh: test_cmd の形の確かめ（testcmd_check.py）が終了コード ${_tc_rc} で落ちた。WORKS_USE_ALLOW_TESTCMD=1 なので確かめずに起こす" >&2
    else
      refuse "test_cmd の形の確かめ（testcmd_check.py）が終了コード ${_tc_rc} で落ち、対象の手元を走らせる形かを確かめられないので、Archon を起こさずに止めた（落ちた理由は上の行）。確かめずに回すなら WORKS_USE_ALLOW_TESTCMD=1 を前に付けて打ち直す"
    fi
    ;;
esac
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

if [ -n "$CHAIN_NEXT" ]; then
  TDD_SUITE="$CN_TDD_SUITE"   # 1 周目に決めた実行器をそのまま使う（周ごとに変えない）
  echo "TDD の輪: 鎖の 1 周目と同じ実行器 ${TDD_SUITE:-（空。輪を飛ばす）}"
elif [ "$#" -ge 5 ]; then
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
# 名指した PR・issue（依頼の欄 pr・issue と --pr）は、run の中の start が利用者の gh のログインを継いで読む（archon.sh が
# dev/hostgh.py の口を PATH に置く）。どの起動にも起動ごとに一意の印（入力 launch_mark。Archon が run の metadata.inputs に
# 残し、入口のブロックが start の控えに生の事実として残す）を付け、起動の後にそれで run を結ぶ（入口の種類で分けない。段 4.1）
LAUNCH_MARK="$STAMP"
# 周の鎖の印は <鎖の id>-<周>（読むのは殻だけ。入力に鎖の欄は足さない）。次の周は鎖の控えが決めた印を使う
if [ -n "$ROUNDS" ]; then
  CHAIN_ID="c-$STAMP"
  CHAIN_DIR="$WORKS_USE_HOME/chains/$CHAIN_ID"
  LAUNCH_MARK="$CHAIN_ID-1"
elif [ -n "$CHAIN_NEXT" ]; then
  LAUNCH_MARK="$CN_MARK"
  # 模型・claude の実行ファイル・包みは 1 周目の run の控えから（wait を打った殻の値で替えない）
  load_ledger "$CN_FIRST_RUN" "鎖 ${CHAIN_NEXT} の次の周を起こす（Archon を起こす）"
fi

place_pack
cd "$TARGET"

# run の基: 汚れていなければ HEAD。commit していない変更・未追跡が在れば、一時の index（HEAD の木から add -A。.gitignore の物は
# 入らない）で包んだ commit にする（git の plumbing。対象の作業ツリー・index・枝・タグは動かさない）。包んだ commit はどの枝にも
# 無いので、git gc に消されないよう refs/works/wraps/<commit> で守る（refs/heads・refs/tags の外。控えの wrap_ref に残し、
# clean が run と一緒に消す。run を結べない時は、下の結べなかった所で控え unbound/ に残すか、その場で外す）
BASE_REV="$(git rev-parse HEAD)"
WRAP_REF=""
if [ -n "$CHAIN_NEXT" ]; then
  # 鎖の次の周の run は前の周の結果（鎖が守る参照の commit）から切る。対象の手元は包まない
  BASE_REV="$CN_FROM"
  echo "対象: ${TARGET}（鎖 ${CHAIN_NEXT} の ${CN_ROUND} 周目。run の worktree は前の周の結果 ${BASE_REV} から切る）"
elif [ -n "$(git status --porcelain --untracked-files=normal)" ]; then
  BASE_REV="$(tree_commit HEAD "" HEAD "works: use.sh start が包んだ対象の手元の姿（run の基）")"
  WRAP_REF="refs/works/wraps/$BASE_REV"
  git update-ref "$WRAP_REF" "$BASE_REV"
  git diff --name-status HEAD "$BASE_REV" | tr '\t' ' ' >"$WORKS_WRAPS_DIR/$BASE_REV.txt"
  echo "包んだ（wrapped）: 対象の commit していない変更・未追跡のファイルを commit ${BASE_REV} に包み、run はそこから切る（対象は動かさない）: $(tr '\n' ' ' <"$WORKS_WRAPS_DIR/$BASE_REV.txt")"
  echo "対象: ${TARGET}（run の worktree は包んだ commit ${BASE_REV} から切る）"
else
  echo "対象: ${TARGET}（run の worktree は HEAD ${BASE_REV} から切る）"
fi

sweep_old_runs

set -- workflow run darkfactory --from "$BASE_REV" --input request="$REQUEST" --input test_cmd="$TEST_CMD" \
  --input tdd_suite="$TDD_SUITE" --input adapter="$WORKS_LAUNCH_ADAPTER_MODE" --input final_gate="${WORKS_USE_FINAL_GATE:-protected_only}"
# Archon は対象を codebase に登録した時の枝を覚えて更新せず、起動のたびにその枝を fetch する（その枝が消えると起動が止まる）。
# --base が登録の枝に勝つので毎回渡す（answer・approve の再開は既存の worktree を使い直すので渡さない）
set -- "$@" --base "$ARCHON_BASE_BRANCH"
if [ -n "${WORKS_USE_POLICY_MD:-}" ]; then set -- "$@" --input policy_md="$WORKS_USE_POLICY_MD"; fi
if [ -n "${WORKS_USE_GATES:-}" ]; then set -- "$@" --input gates="$WORKS_USE_GATES"; fi
if [ -n "${WORKS_USE_THICKNESS:-}" ]; then set -- "$@" --input thickness="$WORKS_USE_THICKNESS"; fi
if [ -n "${WORKS_USE_FEATURES_OFF:-}" ]; then set -- "$@" --input features_off="$WORKS_USE_FEATURES_OFF"; fi
if [ -n "${WORKS_USE_FEATURES_ON:-}" ]; then set -- "$@" --input features_on="$WORKS_USE_FEATURES_ON"; fi
if [ -n "$WORKS_USE_FIX_FIXTURE" ]; then set -- "$@" --input fix_fixture="$WORKS_USE_FIX_FIXTURE"; fi
# 無人の run は線にも知らせる（判定の保留の問いだけでは修正前の関所を開かず、問いを報告の冒頭へ。下の stop で修正を飛ばさない）
if [ "${WORKS_USE_UNATTENDED:-}" = 1 ]; then set -- "$@" --input unattended=true; fi
if [ "${WORKS_DESIGN_ONLY:-}" = 1 ]; then set -- "$@" --input design_only=true; fi
if [ -n "$CHANGE_INPUT" ]; then
  echo "差分の根: ${CHANGE_INPUT}（差分の根から run の作業ツリーまでを入口のブロックが測る）"
  set -- "$@" --input "$CHANGE_INPUT"
fi
set -- "$@" --input launch_mark="$LAUNCH_MARK"
if [ -n "$SPEC_INPUT" ]; then
  echo "仕様の段: 判定の前に仕様（要件と受け入れ条件のテスト）を書いて人が承認する（関所で止まる）"
  set -- "$@" --input spec="$SPEC_INPUT"
fi
if [ -n "$CLEANED_RUNS" ]; then set -- "$@" --input cleaned_runs="$CLEANED_RUNS"; fi
# 鎖: 1 周目は控えを書き（chain_init）、どの周も Archon を起こす直前に「起こした」と起動の基を控えに残す
# （pid が死んでいて起こした印がある周を、結べないまま終わった起動と読む材料）
if [ -n "$ROUNDS" ]; then
  chain_init || exit 2
  echo "鎖 ${CHAIN_ID}: ${ROUNDS} 周まで${BUDGET_USD:+（費用の上限 \$${BUDGET_USD}）}つなぐ（控え ${CHAIN_DIR}）"
fi
if [ -n "$CHAIN_DIR" ]; then
  python3 -I "$CHAIN_PY" launched --dir "$CHAIN_DIR" --from "$BASE_REV" || exit 2
fi
set +e
sh "$ARCHON" "$@"
run_status=$?
set -e
echo "workflow run の終了コード: $run_status"

# 起動の直後に、この起動の印（入力 launch_mark）を持つ run を 1 つに結ぶ（一覧の先頭を推定で採らない。同じ家から並べた
# start の run と混ざらない。入口の種類に依らず同じ結び方）。結べなければ候補と show の行と結べなかった 1 行だけを出し、続きの行は出さない
if ! works_dev_ledger_bind use.sh "$ARCHON" "$TARGET" "$REQUEST"; then
  # 起動が 0 で終わったなら、この起動の run は起動の関所で生きていて、包んだ基を使う（消すと承認した run が落ちる。
  # 2026-10-01 に実測）。推定では結ばず（設計書 2.3）、一覧のうち依頼の写しも起動の印も持たない生きた darkfactory の run
  # （launch.py の LIVE_STATUSES）を候補として控え <家>/unbound/<印>.json に残し、最後の候補の clean <対象> <run-id> が消す。
  # 候補は一覧から 1 回引く（works_dev_run_json と同じ引き方。候補の判じ方と控えの形は launch.py ledger unbound-save）。
  # 一覧が読めなければ生きた run が在るか分からないので、候補の無い控え（unknown）に残して 1 で終わる（迷ったら残す。clean と同じ）
  UNBOUND_CANDIDATES=""
  UNBOUND_UNREADABLE=""
  if [ "$run_status" -eq 0 ] && [ -n "$WRAP_REF" ]; then
    UNBOUND_FILE="$WORKS_USE_HOME/unbound/$STAMP.json"
    UNBOUND_CANDIDATES="$(WORKS_DEV_NO_AUTH=1 sh "$ARCHON" workflow runs --json 2>/dev/null |
      works_dev_launch ledger unbound-save --dir "$WORKS_USE_HOME/unbound" --target "$TARGET" --stamp "$STAMP" \
        --wrap-ref "$WRAP_REF")" || UNBOUND_UNREADABLE=1
  fi
  if [ -n "$UNBOUND_UNREADABLE" ]; then
    # 失敗の理由は launch.py の行（rc 2 は一覧が読めない・控えの書き込みの失敗の両方）。案内は控えが現に在るかで分ける
    if [ -f "$UNBOUND_FILE" ]; then
      echo "この起動の run を結べず、生きた run が在るか分からなかった（run の一覧が読めない）。生きた run が使うかもしれないので、包んだ基 ${WRAP_REF:-無し} は消さずに残した。この対象の run を全部片付けた後に use.sh clean ${TARGET} <run-id> で消える（控え ${UNBOUND_FILE}）"
    else
      echo "この起動の run を結べず、控えも書けなかった（理由は上の launch.py の行）。clean は包んだ基を知らないが、生きた run が使うかもしれないので消さずに残した。要らなくなったら手で外す: 包んだ基 ${WRAP_REF:-無し}（git update-ref -d）"
    fi
    exit 1
  fi
  if [ -n "$UNBOUND_CANDIDATES" ]; then
    echo "この起動の run を結べなかった。包んだ基 ${WRAP_REF:-無し} は run が使うので残した。run を片付けた後に use.sh clean ${TARGET} <run-id> で消える（候補 ${UNBOUND_CANDIDATES}・控え ${UNBOUND_FILE}）"
    exit 1
  fi
  # 起動が落ちたか読めた一覧で候補が 0 本なら、控えを書けないので clean は包んだ基の参照を知らない。ここで外す（run が切った worktree の枝が
  # 在ればその基はそこから届く）
  if [ -n "$WRAP_REF" ]; then
    git update-ref -d "$WRAP_REF"
    echo "包んだ基を守った参照を外した（どの run の控えにも結べないので）: ${WRAP_REF}"
  fi
  [ "$run_status" -ne 0 ] && exit "$run_status"
  exit 1
fi
RID="$WORKS_RUN_ID"
BOUND="$WORKS_RUN_ROW"
# 結べた run を鎖の控えの今の周に結ぶ（wait が次の周へ進める目印。次の周の起動を待つ wait もこの印を読む）
if [ -n "$CHAIN_DIR" ]; then
  python3 -I "$CHAIN_PY" bound --dir "$CHAIN_DIR" --run "$RID" || exit 2
fi

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
    # 機械は関所に答えない。報告が関所の項目と保留の問いへの答えの下書きを次の run の依頼の下書きの answers に置く
    echo "無人の run: 関所の項目と保留の問いへの答えの下書き（推し。機械は答えていない）は、報告の後に下の「次の run の依頼の下書き」（next-request.json）の answers に在る（在れば）。台帳の問いの行（question が問いの key）は採るなら draft と source を消して次の run の依頼に使い（その問いに当たる）、関所の項目の行（question が関所の項目の文）は次の run の関所の continue の一言に写してから消す"
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
# 鎖は wait が終わりを見るたびに 1 歩進む（次の周は wait が切り離して起こす）
if [ -n "$ROUNDS" ]; then
  echo "鎖 ${CHAIN_ID} を進める（run が関所で待つ間は answer・approve。終わりを見ると次の周を起こす）: sh $WORKS_USE_SH wait $TARGET $RID"
fi
[ "$run_status" -ne 0 ] && exit "$run_status"
exit "$show_status"
