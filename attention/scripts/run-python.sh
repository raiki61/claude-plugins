#!/usr/bin/env bash
# attention の台本（scripts/*.py）を起動する入口。スキルとコマンドの本文が打つ行はこれを通す。
# 使い方: bash run-python.sh <台本> [引数...]
#
# python3・python・py -3 の順に、実際に起きて 3.9 以上の物を選ぶ。PATH の頭の python3 をそのまま使わないのは、Windows の
# python3・python が、Python を入れていないと Microsoft Store へ誘う代わりの物（WindowsApps の中の物。起動すると案内を出して
# 終わる）に当たり、python.org の入れ方は python3.exe を入れないため。3.9 は macOS 付属の python3 の版で、attention の台本は
# それで動く。選べなければ、訳と直し方を 1 行で stderr に出し、終了の値 1 で終わる。
# 選び方は works-dispatch の hooks/run-python.sh（--min・--once を除いた形）と同じ。プラグインは互いのファイルを読めないので写した。
for cand in python3 python "py -3"; do
  command -v "${cand%% *}" >/dev/null 2>&1 || continue
  # shellcheck disable=SC2086
  if $cand -c "import sys; sys.exit(0 if sys.version_info >= (3, 9) else 1)" >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    exec $cand "$@"
  fi
done
echo "attention: Python 3.9 以上が見つからない（python3・python・py -3 を試した）。Python 3.9 以上を入れる。Windows で python3 や python が Microsoft Store へ誘うなら、設定 → アプリ → アプリ実行エイリアス で python.exe と python3.exe の「アプリ インストーラー」を切る" >&2
exit 1
