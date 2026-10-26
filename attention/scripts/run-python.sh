#!/usr/bin/env bash
# attention の台本（scripts/*.py）を起動する入口。スキルとコマンドの本文が打つ行はこれを通す。
# 使い方: bash run-python.sh <台本> [引数...]
#
# python3・python・版の付いた名前（python3.20 から python3.9 まで新しい順）・py -3 の順に、実際に起きて 3.9 以上の物を選ぶ。
# PATH の頭の python3 をそのまま使わないのは、Windows の python3・python が、Python を入れていないと Microsoft Store へ誘う
# 代わりの物（WindowsApps の中の物。起動すると案内を出して終わる）に当たり、python.org の入れ方は python3.exe を入れないため。
# 版の付いた名前も試すのは、uv で入れた Python は python3.14 のような名前でだけ PATH に在り、python3・python では見つからない
# ことがあるため。3.9 は macOS 付属の python3 の版で、attention の台本はそれで動く。選べなければ、訳と直し方を 1 行で stderr
# に出し、終了の値 1 で終わる。選び方は docs/standards/cross-os.md の決まり 1（リポジトリのルートの文書）。
pick() {
  command -v "${1%% *}" >/dev/null 2>&1 || return 1
  # shellcheck disable=SC2086
  $1 -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1
}
for cand in python3 python; do
  pick "$cand" && exec "$cand" "$@"
done
n=20
while [ "$n" -ge 9 ]; do
  pick "python3.$n" && exec "python3.$n" "$@"
  n=$((n - 1))
done
pick "py -3" && exec py -3 "$@"
echo "attention: Python 3.9 以上が見つからない（python3・python・python3.20〜python3.9・py -3 を試した）。Python 3.9 以上を入れる。入っているのに見つからないなら、入れた場所を PATH に足す。Windows で python3 や python が Microsoft Store へ誘うなら、設定 → アプリ → アプリ実行エイリアス で python.exe と python3.exe の「アプリ インストーラー」を切る" >&2
exit 1
