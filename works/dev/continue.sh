#!/bin/sh
# works/dev/continue.sh <archon を呼ぶ殻> workflow <動詞> <run-id> [<残り…>]
#
# Archon に続きを渡す行の入口。lib.sh works_dev_go が組む承認・関所の答え・続き・止める・取り消しの行、dogfood.sh の関所の文の
# 答えの行（WORKS_ANSWER_CMD）、use.sh の切り離した答え・承認がこれを打つ。前後の herdr の枠の集計と続き中の印は lib.sh
# works_dev_continue が持ち、ここは控えの置き場（lib.sh works_dev_ledger_dirs）を渡すだけ。家は行の前置き（WORKS_DEV_HOME と、
# use.sh の run なら WORKS_STATE_ROOT）から受け、解き直さない。終了の値は Archon の値
set -eu

if [ "$#" -lt 4 ] || [ "$2" != workflow ] || [ -z "${WORKS_DEV_HOME:-}" ]; then
  echo "usage: WORKS_DEV_HOME=<家> continue.sh <archon を呼ぶ殻> workflow <動詞> <run-id> [<残り…>]" >&2
  exit 2
fi

DEV_DIR="$(cd "$(dirname "$0")" && pwd -P)"
. "$DEV_DIR/lib.sh"
ARCHON="$1"
shift
works_dev_continue "$ARCHON" "$(works_dev_ledger_dirs)" "$3" "$@"
