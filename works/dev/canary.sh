#!/bin/sh
# works/dev/canary.sh [--build-only] [--request tdd|fix|units|large|lanes2] [--diff] [<置き場>]
#
# canary: 決まった小さな対象と決まった依頼で、ライン darkfactory を本物の AI で 1 回回す（費用が掛かる。回す前に持ち主の了承を取る）。
# 普段の依頼ではたまにしか通らない道を 1 run でまとめて通し、版ごとの確かめにする。各依頼で狙う道 (a)〜(k) と、種と依頼を
# その形にした訳は README の「canary」の節。何が実際に通ったかは、終わった run を canary_check.py が読んで出す（読むだけ）。
#
# --request（既定 tdd。3 の canary_check.py の行に同じ語を付ける）:
#   tdd     種 canary-seed/・依頼 canary-request.json。道 (a)〜(d)
#   fix     種 canary-seed/・依頼 canary-request-fix.json。道 (e)（終了コードに (e) も入る）
#   units   固定材料 canary-fixture-units/ の種 seed/・依頼 request.json で、起動に WORKS_USE_FIX_FIXTURE（fix-fixture/）を付ける。
#           判定と修正案を作り直さずに修正の直前の盤面から始める。道 (f)。固定材料を canary_fixture.py check が名指せば何も作らずに止まる
#   large   種 canary-seed-large/・依頼 canary-request-large.json。測りの run。道 (g)
#   lanes2  種 canary-seed-lanes2/・依頼 canary-request-lanes2.json。道 (k)
#   （前の語 change は --request fix --diff に替わった。語 change は替わりの打ち方を書いて拒む）
#
# --diff: 差分を持たせる（語の種と依頼はそのまま）。1 の後に calc.py の 1 行（CHANGE_FROM を CHANGE_TO に）を commit せずに変え、
#   2 の起動に --base <1 の commit> を付ける（--build-only でも同じ対象を作り、起動の行に出す）。入口は差分の在る run になり、
#   P1 の役（局所レビュー）が差分を見る。道 (h)(j)（canary_check.py は語でなく start の控えの入力の差分でこれを数える）
#
# 手順:
#   1. 置き場 <置き場>（既定は ${XDG_CACHE_HOME:-$HOME/.cache}/works-canary/<日時>-<pid>。TMPDIR は再起動で消えるので使わない）に
#      repo/（種を写して 1 回 commit した対象。枝 main）と origin.git/（裸のリポジトリ。origin/HEAD は main）を作る。
#   2. 利用の家を <置き場>/home にして（WORKS_USE_HOME。Archon の db は home/archon-home/archon.db）、use.sh start を無人
#      （WORKS_USE_UNATTENDED=1）で前景で回す。test_cmd は python3 -m pytest -q（use.sh が JUnit の実行器を書き、TDD の輪が回る）。
#      人の関所では止まらずに報告まで進む。終わるまで戻らないので、呼び手は裏で起こす（run_in_background か detach.sh）。
#   3. 戻ったら run id と、canary_check.py の行を出す。走っている間の run id と状態は、先頭に出す show の行で見る。
# --build-only: 1 だけをして、2 の起動の行を出して終わる（認証も Archon も使わない）。
#
# 読む環境: WORKS_USE_FEATURES_OFF・WORKS_USE_FEATURES_ON は use.sh がそのまま読む（全部 off・全部 on と比べる run。どちらも付けない
# run は既定）。認証は use.sh が WORKS_KEYCHAIN_ITEM の項目から拾う（値は出さない。canary は名指しの項目だけで回すので、空なら
# 何も作らずに止まる）。模型は WORKS_DEV_MODEL（use.sh と同じ。ここでは埋めない）。WORKS_DEV_USE は use.sh の差し替え（試験が偽物を差す）。
# 拒む（何も作らずに 1 行で終了コード 2）: 知らない旗・--request の語が tdd・fix・units・large・lanes2 のどれでもない（change は替わりの打ち方を書く）・units の固定材料を使えない・--diff の変える字が種の calc.py にちょうど 1 つ無い・置き場が Claude Code の一時フォルダか /tmp の下・置き場に前の repo・origin.git・home が在る・
# python3 -I で pytest が読めない（隔離した家では利用者の site-packages が見えない）・WORKS_KEYCHAIN_ITEM が空（--build-only は見ない）。
set -eu

USAGE="usage: canary.sh [--build-only] [--request tdd|fix|units|large|lanes2] [--diff] [<置き場>]"
BUILD_ONLY=""
CHANGE=""    # 1 なら commit しない 1 行の変更を足し、--base を付けて差分の在る入口で始める（--diff）
REQUEST_WORD=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --build-only) BUILD_ONLY=1; shift ;;
    --diff) CHANGE=1; shift ;;
    --request)
      if [ "$#" -lt 2 ] || [ -z "$2" ] || [ -n "$REQUEST_WORD" ]; then
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
SEED="$DEV_DIR/canary-seed"
FIXTURE=""   # 固定材料（--request units）。空なら判定から始める
# --diff が種の CHANGE_FILE で変える字（calc.py:median の docstring の 1 行。sed の s/// に入れるので / や正規表現の字を持たない）
CHANGE_FILE='calc.py'
CHANGE_FROM='中央値（個数が偶数なら真ん中の 2 つの平均）'
CHANGE_TO='中央値（個数が偶数なら、並べた真ん中の 2 つの平均）'
case "$REQUEST_WORD" in
  tdd) REQUEST="$DEV_DIR/canary-request.json" ;;
  fix) REQUEST="$DEV_DIR/canary-request-fix.json" ;;
  units)
    # 種・依頼・固定材料は元の run の物（canary_fixture.py の頭の形）。種は今の canary-seed と別物
    UNITS="$DEV_DIR/canary-fixture-units"
    SEED="$UNITS/seed"
    REQUEST="$UNITS/request.json"
    FIXTURE="$UNITS/fix-fixture"
    ;;
  large)
    SEED="$DEV_DIR/canary-seed-large"
    REQUEST="$DEV_DIR/canary-request-large.json"
    ;;
  lanes2)
    SEED="$DEV_DIR/canary-seed-lanes2"
    REQUEST="$DEV_DIR/canary-request-lanes2.json"
    ;;
  change) refuse "--request change は --request fix --diff に替わった（差分を持たせるかは語でなく旗 --diff）" ;;
  *) refuse "--request は tdd・fix・units・large・lanes2 のどれか（${REQUEST_WORD}）" ;;
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
if [ -n "$FIXTURE" ] && ! fixture_why="$(PYTHONDONTWRITEBYTECODE=1 python3 "$DEV_DIR/canary_fixture.py" check "$UNITS" 2>&1)"; then
  refuse "固定材料 ${UNITS} を使えない: $(printf '%s' "$fixture_why" | tr '\n' ' ')"
fi
if [ -n "$CHANGE" ] && [ "$(grep -cF "$CHANGE_FROM" "$SEED/$CHANGE_FILE")" != 1 ]; then
  refuse "変える字が種の ${CHANGE_FILE} にちょうど 1 つ無い（${SEED}/${CHANGE_FILE}。canary.sh の CHANGE_FROM を種に合わせる）: ${CHANGE_FROM}"
fi
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
cp -R "$SEED/." "$REPO/"
find "$REPO" -name .git -prune -o \( -name "__pycache__" -o -name ".pytest_cache" -o -name ".DS_Store" -o -name "*.pyc" \) -print0 |
  xargs -0 rm -rf
g -C "$REPO" add -A
g -C "$REPO" commit -q -m "chore: works の canary の対象（${SEED#"$DEV_DIR"/} の写し）"

g init -q --bare "$ORIGIN"
g -C "$ORIGIN" symbolic-ref HEAD refs/heads/main
g -C "$REPO" remote add origin "$ORIGIN"
g -C "$REPO" push -q origin main
g -C "$REPO" fetch -q origin
g -C "$REPO" remote set-head origin main >/dev/null

BASE_REV=""   # 差分を持たせる（--diff）なら、差分の根の版（種を写した commit）
if [ -n "$CHANGE" ]; then
  BASE_REV="$(g -C "$REPO" rev-parse HEAD)"
  # sed -i は GNU と BSD で旗が違うので、写しに書いてから元へ戻す（cat で戻してファイルの権限を変えない）
  sed "s/${CHANGE_FROM}/${CHANGE_TO}/" "$REPO/$CHANGE_FILE" >"$REPO/$CHANGE_FILE.canary"
  cat "$REPO/$CHANGE_FILE.canary" >"$REPO/$CHANGE_FILE"
  rm -f "$REPO/$CHANGE_FILE.canary"
  echo "差分を持たせる: ${CHANGE_FILE} の 1 行を commit せずに変えた（--base ${BASE_REV}）"
fi

echo "canary の置き場: ${ROOT}（対象 repo/・origin origin.git/・利用の家 home/）・依頼 ${REQUEST}（--request ${REQUEST_WORD}）"
START="WORKS_USE_HOME=$HOME_DIR WORKS_USE_UNATTENDED=1${FIXTURE:+ WORKS_USE_FIX_FIXTURE=$FIXTURE} sh $USE_SH start${BASE_REV:+ --base $BASE_REV} $REPO $REQUEST \"$TEST_CMD\""
if [ -n "$BUILD_ONLY" ]; then
  echo "起動の行（--build-only なので起こさない。WORKS_KEYCHAIN_ITEM を前に付けて打つ）: ${START}"
  exit 0
fi

# 利用の家と無人は環境で use.sh に渡す（どちらも use.sh が環境から読む名）
export WORKS_USE_HOME="$HOME_DIR" WORKS_USE_UNATTENDED=1
if [ -n "$FIXTURE" ]; then
  WORKS_USE_FIX_FIXTURE="$FIXTURE"
  export WORKS_USE_FIX_FIXTURE
else
  unset WORKS_USE_FIX_FIXTURE   # 利用者の殻に残った固定材料で、判定から始める canary を修正から始めない
fi
echo "走っている間の run id と状態: WORKS_USE_HOME=$HOME_DIR sh $USE_SH show $REPO"
set -- "$REPO" "$REQUEST" "$TEST_CMD"
if [ -n "$BASE_REV" ]; then
  set -- --base "$BASE_REV" "$@"
fi
set +e
sh "$USE_SH" start "$@"
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
