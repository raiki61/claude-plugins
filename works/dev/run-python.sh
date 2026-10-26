#!/bin/sh
# works/dev/run-python.sh — works の殻（dev/*.sh）とスキルの本文が python を起動する入口。
# 使い方: sh run-python.sh <python の引数...>（例: sh run-python.sh -I carry.py carry-ci ...）
#
# python3・python・版の付いた名前（python3.20 から python3.11 まで新しい順）・py -3 の順に、実際に起きて 3.11 以上の物を
# 選んで exec する（3.11 は works の台本が tomllib を使うための下限。README の Requirements）。PATH の頭の python3 をそのまま
# 使わないのは、macOS 付属の /usr/bin/python3 が 3.9 で works の台本が動かず、Windows の python3・python は python を入れて
# いないと Microsoft Store へ誘う代わりの物に当たるため。版の付いた名前を試すのは、uv で入れた python が python3.14 のような
# 名前でだけ PATH に在るため（docs/standards/cross-os.md の決まり 1。手本は works-dispatch の hooks/run-python.sh）。
# 選べなければ、試した物と入れ方と PATH の直し方を 1 行 stderr に出し、終了の値 1 で終わる。
try() {
  cand=$1
  shift
  command -v "${cand%% *}" >/dev/null 2>&1 || return 0
  # shellcheck disable=SC2086
  $cand -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1 || return 0
  # shellcheck disable=SC2086
  exec $cand "$@"
}
for cand in python3 python; do try "$cand" "$@"; done
n=20
while [ "$n" -ge 11 ]; do try "python3.$n" "$@"; n=$((n - 1)); done
try "py -3" "$@"
echo "works: python 3.11 以上が見つからない（python3・python・python3.20〜python3.11・py -3 を試した）。python 3.11 以上を入れる（macOS 付属の /usr/bin/python3 は 3.9 で足りない。例: brew install python）。入っているのに見つからないときは、入れた場所を PATH に足す" >&2
exit 1
