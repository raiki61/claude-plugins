#!/usr/bin/env bash
# works-dispatch のフックが Python の台本を起こす入口。使い方: bash run-python.sh <台本> [引数...]
#
# python3・python・py -3 の順に、実際に起きて 3.11 以上（tomllib を使う）の物を選ぶ。PATH の頭の物をそのまま使わないのは、
# Windows の python3・python が、Python を入れていないと Microsoft Store へ誘う代わりの物（WindowsApps の中の物。起こすと
# 案内を出して終わる）に当たり、macOS 付属の python3 は 3.9 で、どちらでもフックが動かないため。
# 選べなければ、訳と直し方を 1 行で stderr に出し、終了の値 1 で終わる（Claude Code はフックの終了の値 1 を、会話を止めない
# 誤りとして見せる）。
for cand in python3 python "py -3"; do
  exe=${cand%% *}
  command -v "$exe" >/dev/null 2>&1 || continue
  # shellcheck disable=SC2086
  if $cand -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    exec $cand "$@"
  fi
done
echo "works-dispatch: フックを動かす Python 3.11 以上が見つからない（python3・python・py -3 を試した）。Python 3.11 以上を入れる。Windows で python3 や python が Microsoft Store へ誘うなら、設定 → アプリ → アプリ実行エイリアス で python.exe と python3.exe の「アプリ インストーラー」を切る" >&2
exit 1
