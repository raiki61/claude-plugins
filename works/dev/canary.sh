#!/bin/sh
# works/dev/canary.sh [--build-only] [--request tdd|fix] [<置き場>]
#
# canary: 決まった小さな対象（canary-seed/）と決まった依頼（--request tdd は canary-request.json（既定）・fix は
# canary-request-fix.json）で、ライン darkfactory を本物の AI で 1 回回す
# （費用が掛かる。回す前に持ち主の了承を取る）。普段の依頼ではたまにしか通らない道を 1 run でまとめて通し、版ごとの確かめにする:
#   (a) 別のファイルの 2 項目（calc.py:mean と textfmt.py:initials）: TDD の輪の枝の並べ
#   (b) 2 項目が同じファイルを別の所で変える: 種のテストは test_lib.py の 1 本だけで、README の決まりがテストをモジュールごとの
#       クラス（TestCalc・TestTextfmt）に、CHANGELOG.md の 1 行を [Unreleased] のモジュールごとの見出し（### calc・### textfmt。
#       間に変わらない行が在る）の下に足させるので、2 項目の枝は test_lib.py と CHANGELOG.md の離れた所を変える: 重なる枝の
#       3 方向の合わせ（同じ所に足せば試験のファイルの union）。計画役が 2 つの単位を別の項目にした時だけ通る。2 件の足しは
#       3 方向の合わせで食い違わない別の所なので、項目の組み方の決まり（まとめるのは同じ根・同じ行か同じ塊・結果への依存の時
#       だけ）では分けるのが素直な案。ただし 2 件をまとめた前後 3 行の差分では CHANGELOG.md の 2 行が 1 つの塊に見えるので、
#       計画役が同じ塊と読む余地は残る（run 245042a7 は見出しの無い [Unreleased] の同じ所に 2 行を足す形を同じ塊と見て
#       1 項目にまとめた。README の「canary」の節）
#   (c) 範囲の外のファイルが要る直し（2 件とも README の決まりで CHANGELOG.md の 1 行が要る）: 範囲の相談。依頼の文が修正案に
#       CHANGELOG.md を allowed_paths へも out_of_scope へも名指させないと言うだけで、文に依る（確かではない）。依頼の文は修正案の
#       役の指示書に貼られず判定者の見立てや裏取りが写した時だけ届き、計画役が CHANGELOG.md を allowed_paths に入れれば相談は
#       起きない（run 245042a7・4c32bf37）。工場を変えずに種の形で縛る道は見つからない（訳は README の「canary」の節）
#   (d) run の中の案の直しは起きてもよい（起こさせない）
# --request fix（canary-request-fix.json。docs/plans/2026-10-07-fix-lane-nodes.md の 9 節の本物の確かめ）は、上の依頼では通らない
# 修正役の並べ（fix-fork → fix-lane-loop-<n> → fix-join）を通す:
#   (e) 別のファイルの 2 項目（calc.py:clamp と textfmt.py:squeeze。どちらも docstring が無い）: 枝に入るのは範囲（allowed_paths）を
#       持ち、TDD の輪が緑にしなかった単位の項目だけ（fixlanes.candidates・tddloop.green_units）。tdd の依頼の 2 件は TDD の輪が
#       緑にするので枝が 0 本になる（run 0a5062f4 の fix_lanes_planted の why「範囲の在る項目 0・枝 0」）。種の README の決まりは
#       テストが振る舞いだけを確かめ docstring の有無や字を縛らないと言うので、docstring を足すだけの直しには先に落ちるテストが
#       無く、計画役の道（route）も TDD の役の振り分けも direct が素直（修正案の指示書は tdd に先に落ちる受け入れのテストを求め
#       （planmarks.HEAD）、TDD の役の振り分けの指示は文書だけの直しを direct の例に挙げる（tddloop.DO））。
#       依頼の文は道を言わない。2 本の枝が同時に走り、各枝が CHANGELOG.md の 1 行で範囲の相談をし、答えの節 plan-answer-lane-<n>
#       が修正案の役の会話の写し（包みの旗 fork）で答え、締め fix-join が 2 本の CHANGELOG.md の足しを合わせる（(a)(b)(c) も通る）。
#       (c) と同じく、計画役が CHANGELOG.md を allowed_paths に入れれば相談は起きない。TDD の輪は振り分けの 1 回だけ回る
# どちらの依頼の 2 件も docstring と README の決まりで直し方が 1 つに決まる（端の振る舞いを人に聞く余地を残さない）。ラインは 1 周の run なので
# （entry.start の stop_after_round=1。canary が決めた物ではない）、報告の「止めたか」は「周の締めの後で止めた」と出るのが普通の
# 終わり。残り（検証器の阻害・独立の目の阻害など）が無ければ結末は fixed、在れば round_limit（2 周目は回らない）。
# 何が実際に通ったかは、終わった run を canary_check.py が読んで出す（読むだけ）。
#
# 手順:
#   1. 置き場 <置き場>（既定は ${XDG_CACHE_HOME:-$HOME/.cache}/works-canary/<日時>-<pid>。TMPDIR は再起動で消えるので使わない）に
#      repo/（種を写して 1 回 commit した対象。枝 main）と origin.git/（裸のリポジトリ。origin/HEAD は main）を作る。
#      origin はローカルのパスなので、並行 PR の確かめは run の初めに機械が条件外（no_forge: local_path）にする（.shared/core/forge.py。
#      ここでは何も特別にしない）。
#   2. 利用の家を <置き場>/home にして（WORKS_USE_HOME。Archon の db は home/archon-home/archon.db）、use.sh start を無人
#      （WORKS_USE_UNATTENDED=1）で前景で回す。test_cmd は python3 -m pytest -q（use.sh が JUnit の実行器を書き、TDD の輪が回る）。
#      人の関所では止まらずに報告まで進む。終わるまで戻らないので、呼び手は裏で起こす（run_in_background か detach.sh）。
#   3. 戻ったら run id と、canary_check.py の行を出す。走っている間の run id と状態は、先頭に出す show の行で見る。
# --build-only: 1 だけをして、2 の起動の行を出して終わる（認証も Archon も使わない）。
# --request: 依頼の語（tdd か fix。既定 tdd）。種・test_cmd・手順は同じ。3 の canary_check.py の行に同じ語を付ける（fix は (e) も
# 終了コードに入れる）。
# 認証は use.sh が WORKS_KEYCHAIN_ITEM の項目から拾う（値は出さない）。canary は名指しの項目だけで回すので、空なら何も作らずに止まる。
# 模型は WORKS_DEV_MODEL（use.sh と同じ。ここでは埋めない）。WORKS_DEV_USE は use.sh の差し替え（試験が偽物を差す）。
# 拒む（何も作らずに 1 行で終了コード 2）: 知らない旗・--request の語が tdd・fix のどれでもない・置き場が Claude Code の一時フォルダか /tmp の下・置き場に前の repo・origin.git・home が在る・
# python3 -I で pytest が読めない（隔離した家では利用者の site-packages が見えない）・WORKS_KEYCHAIN_ITEM が空（--build-only は見ない）。
set -eu

USAGE="usage: canary.sh [--build-only] [--request tdd|fix] [<置き場>]"
BUILD_ONLY=""
REQUEST_WORD=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --build-only) BUILD_ONLY=1; shift ;;
    --request)
      if [ "$#" -lt 2 ] || [ -n "$REQUEST_WORD" ]; then
        echo "$USAGE" >&2
        exit 2
      fi
      REQUEST_WORD=$2
      shift 2
      ;;
    --) shift; break ;;
    -*) echo "$USAGE" >&2; exit 2 ;;
    *) break ;;
  esac
done
if [ "$#" -gt 1 ]; then
  echo "$USAGE" >&2
  exit 2
fi

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
USE_SH="${WORKS_DEV_USE:-$DEV_DIR/use.sh}"
TEST_CMD="python3 -m pytest -q"

refuse() {
  echo "canary.sh: $*" >&2
  exit 2
}

REQUEST_WORD="${REQUEST_WORD:-tdd}"
case "$REQUEST_WORD" in
  tdd) REQUEST="$DEV_DIR/canary-request.json" ;;
  fix) REQUEST="$DEV_DIR/canary-request-fix.json" ;;
  *) refuse "--request は tdd か fix（${REQUEST_WORD}）" ;;
esac

. "$DEV_DIR/guard.sh"
ROOT_IN="${1:-${XDG_CACHE_HOME:-$HOME/.cache}/works-canary/$(date +%Y%m%d-%H%M%S)-$$}"
works_dev_refuse_claude_tmp canary.sh "置き場" "$ROOT_IN"
case "$(works_dev_real "$ROOT_IN")" in
  /private/tmp/* | /tmp/*) refuse "置き場が /tmp の下にある（use.sh は /private/tmp の下の対象を拒む）。別の場所を使う: ${ROOT_IN}" ;;
esac
for used in repo origin.git home; do
  if [ -e "$ROOT_IN/$used" ] || [ -L "$ROOT_IN/$used" ]; then
    refuse "置き場に前の回の ${used} が在る（${ROOT_IN}/${used}）。別の置き場を使うか、要らなければ消す"
  fi
done
python3 -I -c "import pytest" 2>/dev/null ||
  refuse "python3 -I で pytest が読めない（test_cmd の ${TEST_CMD} は隔離した家で走るので、利用者の site-packages の pytest は見えない）。python3 の site-packages に pytest を入れる"
if [ -z "$BUILD_ONLY" ] && [ -z "${WORKS_KEYCHAIN_ITEM:-}" ]; then
  refuse "WORKS_KEYCHAIN_ITEM が空。canary は名指しの keychain の項目の認証で回す（例: WORKS_KEYCHAIN_ITEM=claude-code-oauth-p1 sh canary.sh）"
fi

mkdir -p "$ROOT_IN"
ROOT="$(cd "$ROOT_IN" && pwd -P)"
REPO="$ROOT/repo"
ORIGIN="$ROOT/origin.git"
HOME_DIR="$ROOT/home"

# 利用者の git の設定（署名・hook）に左右されないように、ここで打つ git は全部 hook と署名を切る
g() { git -c core.hooksPath=/dev/null -c commit.gpgsign=false "$@"; }

g init -q "$REPO"
g -C "$REPO" checkout -q -b main
g -C "$REPO" config user.email "works-dev@example.invalid"
g -C "$REPO" config user.name "works-dev"
# 使い捨てなので裏の自動の保守を切る（mktarget.sh と同じ）
g -C "$REPO" config gc.auto 0
g -C "$REPO" config maintenance.auto false
cp -R "$DEV_DIR/canary-seed/." "$REPO/"
find "$REPO" -name .git -prune -o \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".DS_Store" -o -name "*.pyc" \) -print0 |
  xargs -0 rm -rf
g -C "$REPO" add -A
g -C "$REPO" commit -q -m "chore: works の canary の対象（canary-seed の写し）"

g init -q --bare "$ORIGIN"
g -C "$ORIGIN" symbolic-ref HEAD refs/heads/main
g -C "$REPO" remote add origin "$ORIGIN"
g -C "$REPO" push -q origin main
g -C "$REPO" fetch -q origin
g -C "$REPO" remote set-head origin main >/dev/null

echo "canary の置き場: ${ROOT}（対象 repo/・origin origin.git/・利用の家 home/）・依頼 ${REQUEST}（--request ${REQUEST_WORD}）"
START="WORKS_USE_HOME=$HOME_DIR WORKS_USE_UNATTENDED=1 sh $USE_SH start $REPO $REQUEST \"$TEST_CMD\""
if [ -n "$BUILD_ONLY" ]; then
  echo "起動の行（--build-only なので起こさない。WORKS_KEYCHAIN_ITEM を前に付けて打つ）: ${START}"
  exit 0
fi

# 利用の家と無人は環境で use.sh に渡す（どちらも use.sh が環境から読む名）
export WORKS_USE_HOME="$HOME_DIR" WORKS_USE_UNATTENDED=1
echo "走っている間の run id と状態: WORKS_USE_HOME=$HOME_DIR sh $USE_SH show $REPO"
set +e
sh "$USE_SH" start "$REPO" "$REQUEST" "$TEST_CMD"
run_status=$?
set -e
echo "use.sh start の終了コード: $run_status"

# start が結んだ run の控え（<家>/runs/<run-id>.json）の一番新しい物が、この起動の run
RID="$(ls -t "$HOME_DIR/runs" 2>/dev/null | sed -n 's/\.json$//p' | sed -n 1p)"
if [ -n "$RID" ]; then
  echo "canary の run id: $RID"
  echo "何が通ったかを見る（読むだけ）: python3 $DEV_DIR/canary_check.py $ROOT $RID --request $REQUEST_WORD"
else
  echo "canary の run を結べなかった（${HOME_DIR}/runs に控えが無い）。上の use.sh の行を見る"
fi
exit "$run_status"
