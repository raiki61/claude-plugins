#!/usr/bin/env bash
# gates/hooks/run-python.sh の Python の選び方を、PATH に偽の名前を置いて確かめる。
# 使い方: bash gates-run-python-case.sh <versioned|order|none> <本物の Python>
#   versioned: python3 が要る版に足りない物（版を問うと 1 で終わる）で、python3.10 が本物 → python3.10 を選ぶ
#   order:     python3 が本物で、python3.10 は印を出すだけの物 → python3 を選ぶ（版の付いた名前は python3・python の後）
#   none:      python3 が要る版に足りない物だけ → 訳を出して 1 で終わる
# 本物を選んだ回だけ PICKED が出る（印を出すだけの物を選ぶと WRONG が出る）
set -u
case_=$1 real=$2
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
fake() { printf '#!/bin/sh\n%s\n' "$2" > "$dir/$1"; chmod +x "$dir/$1"; }
wrap() { fake "$1" "exec \"$real\" \"\$@\""; }
case $case_ in
    versioned) fake python3 'exit 1'; wrap python3.10 ;;
    order) wrap python3; fake python3.10 'echo WRONG' ;;
    none) fake python3 'exit 1' ;;
esac
here=$(cd "$(dirname "$0")/.." && pwd)
PATH="$dir" "$BASH" "$here/gates/hooks/run-python.sh" -c "print('PICKED')"
