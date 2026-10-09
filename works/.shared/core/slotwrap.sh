#!/bin/bash
# 機械全体で重いテストを同時に 4 本までにする枠の台本（testslot.sh）を通して、コマンドを起こす。bash slotwrap.sh <argv…>
# 呼ぶのは works/tests/run.sh（全部・heavy）と、run の中で試験を起こす口 tree_run.slotted_run（engine の宣言の段・test_cmd・
# blk-tests の plain と mid・TDD の輪と修正の受け付けの実行器）。枠の約束の正本はここ 1 か所（写しを作ると数え方が割れる）。
# 台本は WORKS_TESTSLOT（既定は利用者の家のキャッシュの ${XDG_CACHE_HOME:-$HOME/.cache}/works/testslot.sh。置くかは利用者が決める。
# 本流の台本を使うならそこへ symlink を置く）。空なら枠を取らない（速い段と、TDD の実行器の中が立てる。TDD の実行器は外の
# tddloop.run_suite が枠を取るので、中の試験には取り直させない）。
# 枠の置き場は台本の約束 TESTSLOT_DIR（既定は台本と同じ /private/tmp/claude-<uid>/testslots）で、ここで解決して台本へ渡す。
# 台本が無い・枠の置き場に書けないときは、1 行出して枠を取らずに回す（子孫にも取らせない）。枠を持つ台本の下から呼ばれたら取り直さない
# （test_cmd が run.sh の時、口が取った枠の下の run.sh は取り直さない。GNU make の jobserver と同じ考え）。
# WORKS_SLOT_NOTE が立っていれば（tree_run.slotted_run が立てる）、枠を取った時に held、コマンドを起こせなかった時に execfail を
# そのファイルに書き足す——包むと起こせなさがシェルの 127 に化けるので、呼んだ側が exec の失敗と枠を待った時間をこれで読む。
# 枠は期限なしで待つので、待つ前に標準エラーへ 1 行出す（段のログに残る）。WORKS_SLOT_MARK が立っていれば（run の中では
# tree_run.slotted_run が盤面の testslot.json を立てる）、そこへ待ち {state: waiting, since, slots, pid} を書き、枠を取ったら
# held に書き換える（状態の表示 works_dev_show_run と herdr の集計が読む。消すのは立てた側）。
# 起こすコマンドには WORKS_SLOT_NOTE・WORKS_SLOT_MARK を渡さない（中の run.sh の印が外の段の印に混ざらないように）。
# bash slotwrap.sh --default は、既定の台本が在ればそのパスを、無ければ空を出して 0（何も起こさない）。HOME・XDG を隔離する殻
# （dev/archon.sh）が、隔離の前にこれで引いて WORKS_TESTSLOT に名指す（隔離の後は既定の式が利用者の家を指さない）。
DEFAULT_TESTSLOT=${XDG_CACHE_HOME:-$HOME/.cache}/works/testslot.sh
if [ "${1-}" = --default ]; then
  [ -f "$DEFAULT_TESTSLOT" ] && printf '%s\n' "$DEFAULT_TESTSLOT"
  exit 0
fi
note=${WORKS_SLOT_NOTE-}
mark=${WORKS_SLOT_MARK-}

# exec が落ちてもシェルを抜けずに印を書く（bash の execfail）
launch() {
  unset WORKS_SLOT_NOTE WORKS_SLOT_MARK
  shopt -s execfail
  exec "$@"
  rc=$?
  [ -n "$note" ] && echo execfail >> "$note"
  exit "$rc"
}

# put_mark <state> <置き場>: 印を書き換える（別名に書いて mv。読む側が書きかけを読まない）
put_mark() {
  [ -n "$mark" ] || return 0
  esc=$(printf '%s' "$2" | sed 's/\\/\\\\/g; s/"/\\"/g')
  mkdir -p "$(dirname "$mark")" 2>/dev/null &&
    printf '{"state": "%s", "since": %s, "slots": "%s", "pid": %s}\n' "$1" "$(date +%s)" "$esc" "$$" > "$mark.$$" &&
    mv -f "$mark.$$" "$mark" &&
    { [ -z "$note" ] || echo mark >> "$note"; }
}

if [ "${1-}" = --held ]; then
  shift
  [ -n "$note" ] && echo held >> "$note"
  put_mark held "${TESTSLOT_DIR-}"
  launch "$@"
fi

# 祖先のプロセスが枠を持っているか（枠の中の pid は、枠を取った台本の pid）
held_by_ancestor() {
  p=$$
  while [ -n "$p" ] && [ "$p" -gt 1 ]; do
    for f in "$1"/slot-*/pid; do
      [ -f "$f" ] && [ "$(cat "$f" 2>/dev/null)" = "$p" ] && return 0
    done
    p=$(ps -o ppid= -p "$p" 2>/dev/null | tr -d ' ')
  done
  return 1
}

# 枠を取らずに回すと決めたら、子孫にも同じ決まりを継がせる（WORKS_TESTSLOT を空に）。中の試験が起こす段で同じ 1 行が
# 繰り返され、段の出力（engine の段の tail）に混ざらないように
unslotted() {
  WORKS_TESTSLOT=
  export WORKS_TESTSLOT
  launch "$@"
}

slot=${WORKS_TESTSLOT-$DEFAULT_TESTSLOT}
[ -z "$slot" ] && launch "$@"
if [ ! -f "$slot" ]; then
  # 既定の台本は置いた機械にだけ在る。無ければ黙って枠なしで回す（名指した台本が無い時だけ 1 行出す）
  [ "$slot" = "$DEFAULT_TESTSLOT" ] || echo "slotwrap.sh: 重いテストの枠の台本が無い（${slot}）。枠を取らずに回す" >&2
  unslotted "$@"
fi
# 置き場は台本と同じ式で 1 回だけ解決し、export して台本に渡す（試す場所・祖先を探す場所・台本が枠を取る場所を一致させる）
slots=${TESTSLOT_DIR:-/private/tmp/claude-$(id -u)/testslots}
TESTSLOT_DIR=$slots
export TESTSLOT_DIR
held_by_ancestor "$slots" && launch "$@"
# 台本は枠を mkdir で取り、取れなければ期限なしで待つ。書けない置き場（サンドボックスの中など）では永久に待つので、先に試す
probe="$slots/.probe-slotwrap-$$"
if ! { mkdir -p "$slots" 2>/dev/null && mkdir "$probe" 2>/dev/null && rmdir "$probe"; }; then
  echo "slotwrap.sh: 重いテストの枠の置き場に書けない（${slots}）。枠を取らずに回す" >&2
  unslotted "$@"
fi
TESTSLOT_N=4   # 数える枠の数は mainline と同じでなければならない（違うと同時の本数が数え違う）
export TESTSLOT_N
echo "slotwrap.sh: 重いテストの枠を待つ（置き場 ${slots}・${TESTSLOT_N} 枠。空くまで期限なし）" >&2
put_mark waiting "$slots"
[ -z "$note$mark" ] && exec bash "$slot" "$@"
exec bash "$slot" bash "$(cd "$(dirname "$0")" && pwd)/$(basename "$0")" --held "$@"
