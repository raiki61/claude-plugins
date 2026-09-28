#!/bin/sh
# works のテストの入口。sh works/tests/run.sh [unittest の引数（-k など）]
# WORKS_TESTS で段を選ぶ: 空（既定）= 全部・fast = 速い段・heavy = 重い段。段の一覧は tests/tiers.py。
# どの段も終わりに見送りを一覧に出す。FAIL_ON_SKIP=1 なら SKIP_ALLOW に無い能力と名前の無い見送りを失敗に数える
# （見送りの理由は『SKIP <能力>: <理由>』。約束は tests/tiers.py の頭）。
# 全部と heavy は、機械全体で重いテストを同時に 4 本までにする枠（.shared/core/slotwrap.sh。台本は WORKS_TESTSLOT で差し替え。
# 約束の正本はそちら）を通して回す。fast は枠を取らず、中の試験が起こす試験にも取らせない（WORKS_TESTSLOT を空にする）。
# 走らせる run の env は tests/hermetic.sh で落としてから試験を起こす（dev/tdd-suite.sh と同じ一覧）。
cd "$(dirname "$0")/.." || exit 2

tier=${WORKS_TESTS-}
case $tier in
  "") set -- tests/tiers.py all "$@" ;;
  fast|heavy) set -- tests/tiers.py "$tier" "$@" ;;
  *) echo "run.sh: WORKS_TESTS は fast・heavy・空（全部）のどれか（今の値: ${tier}）" >&2; exit 2 ;;
esac
set -- uv run --no-project --with pyyaml python3 "$@"
. tests/hermetic.sh
PYTHONDONTWRITEBYTECODE=1
export PYTHONDONTWRITEBYTECODE
if [ "$tier" = fast ]; then
  WORKS_TESTSLOT=
  export WORKS_TESTSLOT
  exec "$@"
fi
exec bash .shared/core/slotwrap.sh "$@"
