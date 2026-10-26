#!/usr/bin/env bash
# attention/scripts/run-python.sh の Python の選び方を、PATH に偽の python3 を置いて確かめる。
# 使い方: bash attention-run-python-case.sh <store|none> <本物の Python>
#   store: python3 が Microsoft Store へ誘う代わりの物（起動すると案内を出して 9009 で終わる）で、python が本物 → python を選ぶ
#   none:  python3 が代わりの物だけ → 訳を出して 1 で終わる
set -u
case_=$1 real=$2
dir=$(mktemp -d)
trap 'rm -rf "$dir"' EXIT
printf '#!/bin/sh\necho "Python was not found; run without arguments to install from the Microsoft Store" >&2\nexit 9009\n' > "$dir/python3"
chmod +x "$dir/python3"
if [ "$case_" = store ]; then
    printf '#!/bin/sh\nexec "%s" "$@"\n' "$real" > "$dir/python"
    chmod +x "$dir/python"
fi
here=$(cd "$(dirname "$0")/.." && pwd)
PATH="$dir" "$BASH" "$here/attention/scripts/run-python.sh" -c "print('PICKED')"
