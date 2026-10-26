#!/bin/sh
# works/dev/run-python.sh — works の殻（dev/*.sh）とスキルの本文が python を起動する入口。
# 使い方: sh run-python.sh <python の引数...>（例: sh run-python.sh -I carry.py carry-ci ...）
#
# python3・python・py -3 の順に、実際に起きて 3.11 以上の物を選んで exec する（3.11 は works の台本が tomllib を使うための下限。
# README の Requirements）。PATH の頭の python3 をそのまま使わないのは、macOS 付属の /usr/bin/python3 が 3.9 で works の台本が
# 動かず、Windows の python3・python は python を入れていないと Microsoft Store へ誘う代わりの物に当たるため
# （docs/standards/cross-os.md の決まり 1。手本は works-dispatch の hooks/run-python.sh）。
# 選べなければ、試した物と入れ方を 1 行 stderr に出し、終了の値 1 で終わる。
for cand in python3 python "py -3"; do
  command -v "${cand%% *}" >/dev/null 2>&1 || continue
  # shellcheck disable=SC2086
  $cand -c 'import sys; sys.exit(sys.version_info < (3, 11))' >/dev/null 2>&1 && exec $cand "$@"
done
echo "works: python 3.11 以上が見つからない（python3・python・py -3 を試した）。python 3.11 以上を入れる（macOS 付属の /usr/bin/python3 は 3.9 で足りない。例: brew install python）" >&2
exit 1
