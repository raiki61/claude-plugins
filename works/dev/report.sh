#!/bin/sh
# works/dev/report.sh <run-id>
#
# 途中で終わった darkfactory の run の盤面から、機械の報告を組む（P1 計画 Task 27・〔線A計〕T15 の M8）。ラインの最後の
# 報告の節が走らなかった run（取り消し・abandon で Archon が止めた run）に使う。上流の節が落ちた run は、報告の節が all_done で
# 走って線の中で組む。
# 結末は interrupted で、冒頭 3 に「run が途中で終わった。Archon の run の状態は <状態>」の 1 行。記録の関所（report.gate_record:
# settle → finalize → 検証器）は同じく通し、通らなければ冒頭 1 に出す。report.md・next-request.json は盤面の置き場に書く。
# 出口: report.build の結果を 1 行の JSON で出して 0。
# 盤面の場所は stop.sh と同じ組み方（`archon workflow get <run> --json` の output_root + /artifacts/runs/<run-id>/board）。
# run id が無い・get が失敗した・別の run が返った・output_root が絶対パスでない・board/ が無い・盤面を開けない、のどれも
# 何も書かずに終了コード 2（終わった run（completed・cancelled）も組む。stop.sh と違う所）。
# WORKS_DEV_ARCHON は Archon を呼ぶ殻の差し替え（既定は同じフォルダの archon.sh。tests/test_report.py が偽物を差す）。
set -eu

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
CORE_DIR="$(cd "$DEV_DIR/../.shared/core" && pwd -P)"
ARCHON="${WORKS_DEV_ARCHON:-$DEV_DIR/archon.sh}"

if [ "$#" -ne 1 ] || [ -z "$1" ]; then
  echo "report.sh: 使い方: report.sh <run-id>" >&2
  exit 2
fi
RUN_ID=$1

if ! GOT="$(WORKS_DEV_NO_AUTH=1 sh "$ARCHON" workflow get "$RUN_ID" --json)"; then
  echo "report.sh: archon workflow get $RUN_ID が失敗した（run id を確かめる）——報告は組んでいない" >&2
  exit 2
fi

# 盤面の場所と run の状態を組む（標準ライブラリだけ）。拒むときは理由を標準エラーに出して 2、組めたら 1 行目に board/ のパス、2 行目に状態
if ! FOUND="$(printf '%s' "$GOT" | RUN_ID="$RUN_ID" python3 -c '
import json, os, sys
rid = os.environ["RUN_ID"]
try:
    d = json.load(sys.stdin)
except ValueError as e:
    sys.exit("report.sh: archon workflow get の出力が JSON として読めない（{}）".format(e))
if not isinstance(d, dict) or d.get("id") != rid or not rid or "/" in rid or rid in (".", ".."):
    sys.exit("report.sh: archon workflow get が run {} を返さなかった（返った id: {!r}）".format(rid, d.get("id") if isinstance(d, dict) else None))
root = d.get("output_root")
if not (isinstance(root, str) and os.path.isabs(root)):
    sys.exit("report.sh: run {} の output_root が絶対パスでない（{!r}）——盤面の場所を組めない".format(rid, root))
print(os.path.join(root, "artifacts", "runs", rid, "board"))
print(" ".join(str(d.get("status") or "").split()))
')"; then
  exit 2
fi
BOARD="$(printf '%s\n' "$FOUND" | sed -n 1p)"
STATUS="$(printf '%s\n' "$FOUND" | sed -n 2p)"
if [ ! -f "$BOARD/state.json" ]; then
  echo "report.sh: 盤面 $BOARD が無い（盤面を作る前に終わった run か、works の darkfactory の run でない）——報告は組んでいない" >&2
  exit 2
fi

BOARD="$BOARD" STATUS="$STATUS" RUN_ID="$RUN_ID" CORE_DIR="$CORE_DIR" PYTHONDONTWRITEBYTECODE=1 python3 -c '
import json, os, pathlib, sys
sys.dont_write_bytecode = True
sys.path.insert(0, os.environ["CORE_DIR"])
import report
from board import BoardGap
from engine.util import Reject
try:
    out = report.build(pathlib.Path(os.environ["BOARD"]), judged=None, tests=None, start=None, run_id=os.environ["RUN_ID"],
                       interrupted=os.environ["STATUS"])
except (BoardGap, Reject) as e:
    sys.exit("report.sh: 報告を組めない（{}）: {}".format(type(e).__name__, " ".join(str(e).split())))
print("report.sh: 報告:", out["report_file"], file=sys.stderr)
print(json.dumps(out, ensure_ascii=False))
' || exit 2
