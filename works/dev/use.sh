#!/bin/sh
# works/dev/use.sh — ほかのリポジトリを対象に、ライン darkfactory を回す起動の殻（skills/works/SKILL.md が入口）。
#
#   use.sh start [<対象リポジトリ>] <依頼の JSON> [<test_cmd> [<tdd_suite>]]   本物の AI で回す（費用が掛かる）。最初の関所で止まって戻る
#   use.sh show  <対象リポジトリ> [<run-id>]                                その対象から起こした一番新しい run（か名指しの run）の状態・
#                                                                           次に打つ行・差分のファイルを出し直す
#   use.sh wait  <対象リポジトリ> <run-id>                                  裏で回る run を決まった時間（WORKS_USE_WAIT_SECONDS。既定 540 秒）
#                                                                           まで待ち、状態を 1 行で返す（0 = 関所で待つ・3 = まだ走っている・
#                                                                           5 = 終わった・1 = 落ちた・見つからない）。AI を起こさない
#   use.sh answer <対象リポジトリ> <run-id> continue|stop <一言> [<答えた者>] 関所で待つ run に答える（答えた者を <家>/answers.jsonl に残す）
#   use.sh stop  <対象リポジトリ> <run-id> <理由>                           止める（関所で待つ run は respond stop、走っている run は止め札）
#   use.sh apply <対象リポジトリ> <run-id>                                  その run の差分を書き直し、git apply --check の後に対象へ当てる
#                                                                           （commit しない。消す行は WORKS_USE_ALLOW_DELETE=1 の時だけ）
#   use.sh clean <対象リポジトリ> <run-id>                                  終わった run の worktree と枝を消す（走っている・関所で待つ run は拒む）
#   use.sh check <対象リポジトリ>                                           AI を起こさずに、pack を置いて Archon の validate を回し、
#                                                                           start に足りない物（uv・claude・認証・対象の条件）を全部並べる
#
# - AI の役は開発の殻 archon.sh を通してだけ起こす（HOME・ARCHON_HOME・CLAUDE_CONFIG_DIR を利用の家の下へ隔離し、役は toolset.py が
#   組む選んだ物だけの設定を読む。利用者の本物の ~/.claude は読ませない）。
# - 利用の家は WORKS_USE_HOME（既定は ${XDG_STATE_HOME:-$HOME/.local/state}/works/use）。WORKS_DEV_HOME は継がない
#   （自分食い・実走の家と分け、走っている run の家を書き換えない）。
# - pack は対象に置かない。tests/・dev/・docs/ を除いた works/ を <家>/archon-home/workflows/works（Archon の全体の工程の置き場。
#   Archon v0.11.1 は $ARCHON_HOME/workflows/<pack>/ も探す）に起こすたびに写す。対象の作業ツリーは書かない。
# - 対象はリポジトリの下のフォルダでもよく、その git の根で回す。start で対象を省けば今いるフォルダの git の根。
# - run の worktree は対象の今の姿から切る: 汚れていなければ HEAD、commit していない変更・未追跡のファイル（.gitignore の物は
#   入れない）が在れば一時の index で包んだ commit（--from）。対象の作業ツリー・index・枝は動かさない。包んだファイルは
#   <家>/wraps/<commit>.txt に控え、起動と show に出す。origin は要らない（無ければ 1 行で知らせる）。
# - 拒む（Archon を呼ばず・何も写さずに 1 行で終了コード 2）: /private/tmp の下の対象・git のリポジトリの中でない（ここまで全部）・
#   対象に pack の写し .archon/workflows/works が在る（dogfood.sh の形）・依頼が無い・認証が無い・uv か claude が無い（start。
#   check は拒まずに全部並べて 2）。
# - tdd_suite: 第 4 引数が在ればそのまま（空は輪を飛ばす）。無ければ test_cmd が pytest の 1 コマンド（前に uv run・poetry run・
#   python3 -m を許す。; & | < > $ ` を含まない）の時だけ、その末尾に JUnit XML の書き先を足す実行器を <家>/suites/ に書いて渡す。
#   それ以外は空（全部の単位を直に直す）にして 1 行で知らせる。test_cmd を省けば空（ラインの既定: 対象の宣言か CI）。
# - 最後の関所は WORKS_USE_FINAL_GATE（既定 when_needed・always）。包みは既定で入れる（WORKS_DEV_ADAPTER=0 か空の明示で外し、
#   adapter=optional と「包み無し」を出す）。入力 policy_md・gates・thickness は WORKS_USE_POLICY_MD・WORKS_USE_GATES・
#   WORKS_USE_THICKNESS（空なら渡さない）。WORKS_USE_UNATTENDED=1 は無人の run: 起動の関所を越え、人が決める関所に着いたら
#   止めて報告へ進める。
# - 関所の文の答えの行は、この殻の answer の行（env WORKS_ANSWER_CMD。.shared/core/answer.py）。
# - herdr の枠の中（HERDR_ENV=1・HERDR_PANE_ID）なら、起動と show のたびに run の状態をその枠へ出す（lib.sh works_dev_herdr）。
# - 差分（run の worktree と周の頭の版の差）は <家>/diffs/run-<id>.diff に書き、対象へ当てる apply の行を出す。当てるのは人。
# 認証は archon.sh と同じ順（CLAUDE_CODE_OAUTH_TOKEN・WORKS_KEYCHAIN_ITEM・Claude Code 自身の keychain の項目）。ここは在るかだけを
# 見て、値は読まない。模型は WORKS_DEV_MODEL（既定 opus）。
# WORKS_DEV_ARCHON は Archon を呼ぶ殻の差し替え（既定は同じフォルダの archon.sh。tests/test_use.py が偽物を差す）。
set -eu

USAGE="usage: use.sh start [<対象リポジトリ>] <依頼の JSON> [<test_cmd> [<tdd_suite>]] | use.sh show <対象リポジトリ> [<run-id>] | use.sh wait <対象リポジトリ> <run-id> | use.sh answer <対象リポジトリ> <run-id> continue|stop <一言> [<答えた者>] | use.sh stop <対象リポジトリ> <run-id> <理由> | use.sh apply <対象リポジトリ> <run-id> | use.sh clean <対象リポジトリ> <run-id> | use.sh check <対象リポジトリ>"
CMD="${1:-}"
case "$CMD:$#" in
  start:2 | start:3 | start:4 | start:5 | show:2 | show:3 | wait:3 | answer:5 | answer:6 | stop:4 | apply:3 | clean:3 | check:2) ;;
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
# 包みは既定で入れる（dogfood.sh と同じ。0 か空を明示した時だけ外す。値の検査は archon.sh）
WORKS_DEV_ADAPTER="${WORKS_DEV_ADAPTER-1}"
WORKS_USE_SH="$DEV_DIR/use.sh"
WORKS_WRAPS_DIR="$WORKS_USE_HOME/wraps"
export WORKS_DEV_HOME WORKS_DEV_MODEL WORKS_DEV_ADAPTER WORKS_USE_SH WORKS_WRAPS_DIR

refuse() {
  echo "use.sh: $*" >&2
  exit 2
}

. "$DEV_DIR/guard.sh"
works_dev_abs_claude_config
works_dev_refuse_claude_tmp use.sh "WORKS_USE_HOME" "$WORKS_USE_HOME"

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
WORKS_ANSWER_CMD="$(A="$WORKS_USE_SH" T="$TARGET" python3 -c 'import os, shlex
print("sh {} answer {}".format(shlex.quote(os.environ["A"]), shlex.quote(os.environ["T"])))')"
export WORKS_ANSWER_CMD

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

# 認証の出どころの名（無ければ空）。archon.sh と同じ順で、在るかだけを見る（keychain の値は読まない）
auth_from() {
  if [ -n "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
    echo "CLAUDE_CODE_OAUTH_TOKEN"
  elif [ -n "${WORKS_KEYCHAIN_ITEM:-}" ]; then
    echo "keychain の項目 ${WORKS_KEYCHAIN_ITEM}"
  elif [ "$(uname -s)" = Darwin ]; then
    works_dev_claude_keychain_services | while IFS= read -r _svc; do
      if security find-generic-password -s "$_svc" >/dev/null 2>&1; then
        echo "Claude Code の keychain の項目 ${_svc}"
        break
      fi
    done
  fi
}

# 本物の claude（隔離の前に解く。関数・別名は実行ファイルでない）。show・check も次の行に載せる
resolve_claude() {
  if [ -z "${CLAUDE_BIN_PATH:-}" ]; then
    CLAUDE_BIN_PATH="$(command -v claude || true)"
    case "$CLAUDE_BIN_PATH" in /*) ;; *) CLAUDE_BIN_PATH="" ;; esac
  fi
  export CLAUDE_BIN_PATH
}

if [ "$CMD" = start ] || [ "$CMD" = check ]; then
  if [ -e "$TARGET/.archon/workflows/works" ]; then
    problem "対象に pack の写し（.archon/workflows/works）がある。works 自身の直しは dogfood.sh で回す"
  fi
  if [ "$CMD" = start ] && [ ! -f "$REQUEST_SRC" ]; then
    problem "依頼の JSON が無い（${REQUEST_SRC}）"
  fi
  WORKS_AUTH_FROM="$(auth_from)"
  export WORKS_AUTH_FROM
  if [ -z "$WORKS_AUTH_FROM" ]; then
    problem "認証が無い。claude にログインするか、CLAUDE_CODE_OAUTH_TOKEN（例: claude setup-token で作る）か、トークンを入れた keychain の項目名 WORKS_KEYCHAIN_ITEM を設定する"
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
  rm -rf "$_wf/.works.new.$$"
  works_dev_copy_pack "$WORKS_DIR" "$_wf/.works.new.$$"
  rm -rf "$_wf/works"
  mv "$_wf/.works.new.$$" "$_wf/works"
}

# run_row <run-id か空>: この対象の run（空なら一番新しい物）の「id<TAB>status<TAB>working_path」。見つからない・一覧が
# 読めなければ 1 行の理由で 1（呼び手は ROW="$(run_row …)" || exit 2）。選び方は lib.sh works_dev_show_run と同じ
run_row() {
  WORKS_DEV_NO_AUTH=1 sh "$ARCHON" workflow runs --json 2>/dev/null | RUN_ID="$1" DIR="$TARGET" python3 -c '
import json, os, sys
try:
    listed = json.load(sys.stdin)
except ValueError as e:
    sys.exit("use.sh: archon workflow runs --json の出力が JSON として読めない（{}）".format(e))
def origin(r):
    o = ((r.get("metadata") or {}).get("workflow_source") or {}).get("origin")
    return os.path.realpath(o) if isinstance(o, str) and o else None
here, rid = os.path.realpath(os.environ["DIR"]), os.environ["RUN_ID"]
runs = [r for r in listed.get("runs", []) if r.get("workflow_name") == "darkfactory" and origin(r) in (None, here)]
runs = [r for r in runs if r.get("id") == rid] if rid else runs
if not runs:
    sys.exit("use.sh: darkfactory の run が見つからない（対象 {}{}）".format(here, "・run id " + rid if rid else ""))
r = runs[0]
print("\t".join([r.get("id") or "", r.get("status") or "", r.get("working_path") or ""]))
'
}

# run の控え <家>/runs/<run-id>.json: start で選んだ模型・claude の実行ファイル・keychain の項目の名（値でなく名）・包みを残し、
# 別の殻で打つ answer・stop がそれで Archon を起こし、show が出す進める・続きの行もそれで組む（無ければ今の殻の値のまま）
save_ledger() {
  mkdir -p "$WORKS_USE_HOME/runs"
  RUN_ID="$1" DIR="$TARGET" python3 -c '
import json, os
e = os.environ
print(json.dumps({"run_id": e["RUN_ID"], "target": e["DIR"], "model": e.get("WORKS_DEV_MODEL", ""),
                  "claude_bin": e.get("CLAUDE_BIN_PATH", ""), "keychain_item": e.get("WORKS_KEYCHAIN_ITEM", ""),
                  "adapter": e.get("WORKS_DEV_ADAPTER", "")}, ensure_ascii=False))
' >"$WORKS_USE_HOME/runs/$1.json"
}
# 2 つ目の引数は控えで何をするかの文（既定は answer・stop の『Archon を起こす』。show は起こさないので行を組むと言う）
load_ledger() {
  [ -f "$WORKS_USE_HOME/runs/$1.json" ] || return 0
  eval "$(python3 -c '
import json, shlex, sys
d = json.load(open(sys.argv[1], encoding="utf-8"))
for k, v in (("WORKS_DEV_MODEL", d.get("model")), ("CLAUDE_BIN_PATH", d.get("claude_bin")),
             ("WORKS_KEYCHAIN_ITEM", d.get("keychain_item")), ("WORKS_DEV_ADAPTER", d.get("adapter"))):
    if isinstance(v, str) and (v or k == "WORKS_DEV_ADAPTER"):
        print("{}={}; export {}".format(k, shlex.quote(v), k))
' "$WORKS_USE_HOME/runs/$1.json")"
  echo "run $1 の控え（模型 ${WORKS_DEV_MODEL}・包み ${WORKS_DEV_ADAPTER:-無し}）で${2:- Archon を起こす}"
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
    # 出す進める・続きの行も、start の控えの模型・claude・包みで組む（別の殻の値で黙って替えない）。run が見つからなければ下が言う
    if ROW="$(run_row "${3:-}" 2>/dev/null)"; then
      load_ledger "$(printf '%s' "$ROW" | cut -f1)" "進める・続きの行を組む（Archon は起こさない）"
    fi
    WORKS_RUN_ID="${3:-}"
    export WORKS_RUN_ID
    works_dev_show_run use.sh "$ARCHON" "$TARGET" "$TARGET" "$WORKS_USE_HOME/diffs"
    exit $?
    ;;
  wait)
    cd "$TARGET"
    set +e
    ARCHON_SH="$ARCHON" RUN_ID="$3" WAIT_SECONDS="${WORKS_USE_WAIT_SECONDS:-540}" python3 -c '
import json, os, subprocess, sys, time
rid, limit = os.environ["RUN_ID"], float(os.environ["WAIT_SECONDS"])
deadline = time.monotonic() + limit
env = dict(os.environ, WORKS_DEV_NO_AUTH="1")
while True:
    got = subprocess.run(["sh", os.environ["ARCHON_SH"], "workflow", "runs", "--json"], env=env, capture_output=True, text=True)
    try:
        runs = json.loads(got.stdout).get("runs", [])
    except ValueError:
        sys.exit("use.sh: archon workflow runs --json の出力が JSON として読めない（終了コード {}）".format(got.returncode))
    r = next((x for x in runs if x.get("id") == rid), None)
    if r is None:
        print("run {}: 見つからない".format(rid))
        sys.exit(1)
    status = r.get("status") or ""
    if status == "paused":
        print("run {}: paused（関所で人の答えを待つ。use.sh show {} {} で関所の文と答えの行を出す）".format(rid, os.getcwd(), rid))
        sys.exit(0)
    if status in ("completed", "cancelled"):
        print("run {}: {}（終わった。報告と差分は use.sh show で出す）".format(rid, status))
        sys.exit(5)
    if status not in ("running", "pending"):
        print("run {}: {}（落ちた。use.sh show で続ける行を出す）".format(rid, status))
        sys.exit(1)
    left = deadline - time.monotonic()
    if left <= 0:
        print("run {}: {}（{:g} 秒のうちに関所にも終わりにも着かなかった。待つなら同じ行を打ち直す。止めるなら use.sh stop）".format(rid, status, limit))
        sys.exit(3)
    time.sleep(min(10.0, left))
'
    wait_status=$?
    set -e
    case $wait_status in
      0 | 1) works_dev_herdr blocked "factory run $3" ;;
      3) works_dev_herdr working "factory run $3" ;;
      5) works_dev_herdr release ;;
    esac
    exit "$wait_status"
    ;;
  answer)
    # 関所で待つ run に continue か stop で答える。人が決める関所なので、答えた者（第 6 引数。無ければ $USER）と一言を
    # <家>/answers.jsonl に残してから Archon へ渡す（残りの工程をその場で回すので、Claude Code なら背景で打ち wait で戻る）
    case "$4" in continue | stop) ;; *) refuse "答えは continue か stop（受けた値: $4）" ;; esac
    resolve_claude
    cd "$TARGET"
    ROW="$(run_row "$3")" || exit 2
    STATUS="$(printf '%s' "$ROW" | cut -f2)"
    [ "$STATUS" = paused ] || refuse "run $3 は ${STATUS}。答えられるのは関所で待つ（paused）run だけ"
    mkdir -p "$WORKS_USE_HOME"
    RUN_ID="$3" VERB="$4" TEXT="$5" BY="${6:-${USER:-$(id -un)}}" DIR="$TARGET" python3 -c '
import datetime, json, os
e = os.environ
row = {"at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"), "run_id": e["RUN_ID"],
       "target": e["DIR"], "answer": e["VERB"], "text": e["TEXT"], "by": e["BY"]}
print(json.dumps(row, ensure_ascii=False))
' >>"$WORKS_USE_HOME/answers.jsonl"
    load_ledger "$3"
    exec sh "$ARCHON" workflow respond "$3" "$4" "$5"
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
        exec sh "$ARCHON" workflow respond "$3" stop "$4"
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
if [ "$WORKS_DEV_ADAPTER" != 1 ]; then
  ADAPTER_MODE="optional"
  echo "包み無し（WORKS_DEV_ADAPTER=${WORKS_DEV_ADAPTER:-空}）: adapter=optional で回し、報告に出る"
else
  ADAPTER_MODE=""
fi
if [ -n "${WORKS_AUTH_FROM:-}" ]; then
  echo "認証: ${WORKS_AUTH_FROM}（値は出さない）"
fi

STAMP="$(date +%Y%m%d-%H%M%S)-$$"
mkdir -p "$WORKS_USE_HOME/requests"
REQUEST="$WORKS_USE_HOME/requests/$STAMP.json"
cp "$REQUEST_SRC" "$REQUEST"   # 依頼の元が後で書き換わっても、回した物が残る

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

place_pack
cd "$TARGET"
if ! git remote get-url origin >/dev/null 2>&1; then
  echo "対象に remote の origin が無い。Archon が worktree を切る前に origin を fetch するなら run は始まらない（その時は git remote add origin <URL>）"
fi

# run の基: 汚れていなければ HEAD。commit していない変更・未追跡が在れば、一時の index（HEAD の木から add -A。.gitignore の物は
# 入らない）で包んだ commit にする（git の plumbing。対象の作業ツリー・index・枝・参照は動かさない）
BASE_REV="$(git rev-parse HEAD)"
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
  git diff --name-status HEAD "$BASE_REV" | tr '\t' ' ' >"$WORKS_WRAPS_DIR/$BASE_REV.txt"
  echo "包んだ（wrapped）: 対象の commit していない変更・未追跡のファイルを commit ${BASE_REV} に包み、run はそこから切る（対象は動かさない）: $(tr '\n' ' ' <"$WORKS_WRAPS_DIR/$BASE_REV.txt")"
  echo "対象: ${TARGET}（run の worktree は包んだ commit ${BASE_REV} から切る）"
else
  echo "対象: ${TARGET}（run の worktree は HEAD ${BASE_REV} から切る）"
fi

set -- workflow run darkfactory --from "$BASE_REV" --input request="$REQUEST" --input test_cmd="$TEST_CMD" \
  --input tdd_suite="$TDD_SUITE" --input adapter="$ADAPTER_MODE" --input final_gate="${WORKS_USE_FINAL_GATE:-when_needed}"
if [ -n "${WORKS_USE_POLICY_MD:-}" ]; then set -- "$@" --input policy_md="$WORKS_USE_POLICY_MD"; fi
if [ -n "${WORKS_USE_GATES:-}" ]; then set -- "$@" --input gates="$WORKS_USE_GATES"; fi
if [ -n "${WORKS_USE_THICKNESS:-}" ]; then set -- "$@" --input thickness="$WORKS_USE_THICKNESS"; fi
works_dev_herdr working "factory run を起こした（${TARGET}）"
set +e
sh "$ARCHON" "$@"
run_status=$?
set -e
echo "workflow run の終了コード: $run_status"

# 無人の run: 起動の関所を越え（残りをその場で回す）、次に人が決める関所で待っていれば止めて報告へ進める（本線の --unattended）
if [ "${WORKS_USE_UNATTENDED:-}" = 1 ] && [ "$run_status" -eq 0 ]; then
  ROW="$(run_row "")" || exit 2
  RID="$(printf '%s' "$ROW" | cut -f1)"
  if [ "$(printf '%s' "$ROW" | cut -f2)" = paused ]; then
    echo "無人の run（WORKS_USE_UNATTENDED=1）: 起動の関所を越える（run ${RID}）"
    set +e
    sh "$ARCHON" workflow approve "$RID"
    run_status=$?
    set -e
  fi
  ROW="$(run_row "$RID")" || exit 2
  if [ "$run_status" -eq 0 ] && [ "$(printf '%s' "$ROW" | cut -f2)" = paused ]; then
    echo "無人の run: 人が決める関所に着いたので止めて報告へ進める（run ${RID}）"
    set +e
    sh "$ARCHON" workflow respond "$RID" stop "無人の run（WORKS_USE_UNATTENDED=1）: 人が決める関所に着いたので止めて報告へ"
    run_status=$?
    set -e
  fi
fi

# 起動が落ちても run が在れば続きの行を出す。終了コードは起動のまま（起動が 0 の時だけ show の結果）
show_status=0
SHOWN="$(works_dev_show_run use.sh "$ARCHON" "$TARGET" "$TARGET" "$WORKS_USE_HOME/diffs")" || show_status=$?
printf '%s\n' "$SHOWN"
RID="$(printf '%s\n' "$SHOWN" | sed -n 's/^run id: //p' | head -n 1)"
if [ -n "$RID" ]; then
  save_ledger "$RID"
fi
[ "$run_status" -ne 0 ] && exit "$run_status"
exit "$show_status"
