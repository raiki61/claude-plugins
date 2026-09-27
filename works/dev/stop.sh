#!/bin/sh
# works/dev/stop.sh <run-id> <理由…>
#
# 走っている darkfactory の run の盤面に止め札（board/STOP。{reason, by, at}）を置く（線 A の仕様 5.3）。
# 次の境の節が止め札を見て盤面を止め、後ろの段を飛ばして報告（outcome: stopped_by_request）を必ず出す。
# 走っている AI の節とブロックの中の出し直しの輪は、次の境まで走りきる（試し P12）。すぐ止めたいときは取り消し
# （archon workflow cancel）を使う。関所で待っている run は、答えて進めた後の境の節で止まる。
#
# 理由は必須（残りの引数を空白で繋いだ物。空・空白だけなら置かない）。最初の理由が正で、2 度目からは上書きせず
# 盤面の trace にだけ積む。止めた人（by）は $USER。
# 盤面の場所は `archon workflow get <run> --json` の output_root + /artifacts/runs/<run-id>/board で組む
# （走っている run には $ARTIFACTS_DIR の欄が無い。試し P12）。board/ が無い・別の run が返った・run が終わっている
# （completed・cancelled。failed は resume できるので置く）・get が失敗した、のどれも何も書かずに終了コード 2。
# WORKS_DEV_ARCHON は Archon を呼ぶ殻の差し替え（既定は同じフォルダの archon.sh。tests/test_halt.py が偽物を差す）。
set -eu

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
CORE_DIR="$(cd "$DEV_DIR/../.shared/core" && pwd -P)"
ARCHON="${WORKS_DEV_ARCHON:-$DEV_DIR/archon.sh}"

if [ "$#" -lt 1 ]; then
  echo "stop.sh: 使い方: stop.sh <run-id> <理由…>" >&2
  exit 2
fi
RUN_ID=$1
shift
REASON="$*"
if [ -z "$(printf '%s' "$REASON" | tr -d ' \t\n')" ]; then
  echo "stop.sh: 止める理由が要る（stop.sh <run-id> <理由…>。理由は記録と報告に残る）" >&2
  exit 2
fi

# 問い合わせは認証が要らないので認証を読ませない。出力の誤りは get の後で JSON として読めないことで拾う
if ! GOT="$(WORKS_DEV_NO_AUTH=1 sh "$ARCHON" workflow get "$RUN_ID" --json)"; then
  echo "stop.sh: archon workflow get $RUN_ID が失敗した（run id を確かめる）——止め札は置いていない" >&2
  exit 2
fi

# 盤面の場所を組む（標準ライブラリだけ）。拒むときは理由を標準エラーに出して 2、組めたら board/ のパスを 1 行
if ! BOARD="$(printf '%s' "$GOT" | RUN_ID="$RUN_ID" python3 -c '
import json, os, sys
rid = os.environ["RUN_ID"]
try:
    d = json.load(sys.stdin)
except ValueError as e:
    sys.exit("stop.sh: archon workflow get の出力が JSON として読めない（{}）".format(e))
if not isinstance(d, dict) or d.get("id") != rid or not rid or "/" in rid or rid in (".", ".."):
    sys.exit("stop.sh: archon workflow get が run {} を返さなかった（返った id: {!r}）".format(rid, d.get("id") if isinstance(d, dict) else None))
if d.get("status") in ("completed", "cancelled"):
    sys.exit("stop.sh: run {} は既に {}——止める物が無い".format(rid, d["status"]))
root = d.get("output_root")
if not (isinstance(root, str) and os.path.isabs(root)):
    sys.exit("stop.sh: run {} の output_root が絶対パスでない（{!r}）——盤面の場所を組めない".format(rid, root))
print(os.path.join(root, "artifacts", "runs", rid, "board"))
')"; then
  exit 2
fi
if [ ! -d "$BOARD" ]; then
  echo "stop.sh: 盤面 $BOARD が無い（まだ盤面を作る前の run か、works の darkfactory の run でない）——止め札は置いていない" >&2
  exit 2
fi

BY="${USER:-$(id -un)}"
BOARD="$BOARD" REASON="$REASON" BY="$BY" CORE_DIR="$CORE_DIR" python3 -c '
import os, sys
sys.dont_write_bytecode = True
sys.path.insert(0, os.environ["CORE_DIR"])
import halt
board = os.environ["BOARD"]
got = halt.place(board, os.environ["REASON"], os.environ["BY"])
if not got["ok"]:
    sys.exit("stop.sh: " + got["reason"] + "——止め札は置いていない")
flag = os.path.join(board, halt.STOP_FILE)
if got["first"]:
    print("stop.sh: 止め札を置いた:", flag)
    print("次の境の節で止まり、報告を出す（走っている AI の節は最後まで走る。すぐ止めるなら archon workflow cancel）")
else:
    print("stop.sh: 止め札は既に在る:", flag)
    print("正の理由は最初の物のまま:", halt.seen(board)["reason"], "——今の理由は盤面の trace にだけ積んだ")
' || exit 2
