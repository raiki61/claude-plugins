#!/usr/bin/env bash
# convergence-loops が Python の台本を起動する入口（スキルの手順書のコマンドの行と comment-ratio.sh）。
# 使い方: bash run-python.sh [--min <版>] <台本> [引数...]（--min を省けば 3.12。README の「Dependencies」の下限で、CI が測っている版）
#
# python3・python・py -3 の順に、実際に起きて --min 以上の物を選ぶ。PATH の頭の物をそのまま使わないのは、Windows の
# python3・python が、Python を入れていないと Microsoft Store へ誘う代わりの物（WindowsApps の中の物。起動すると案内を出して
# 終わる）に当たり、Python の文書も Windows の python3 を「not meant to be widely used or recommended」とし、いくつもの版を
# 入れた所では py を勧めるため（https://docs.python.org/3/using/windows.html）。下限を満たさない python を選ばないのは、
# Python 2 の python で記録の検証器が構文の誤りの終了の値 1 で落ち、「阻害要因あり」の 1 と区別が付かなくなるため。
# 選べなければ、訳と直し方を 1 行で stderr に出し、終了の値 127（シェルの「コマンドが無い」と同じ値）で終わる。1 や 2 にしないのは、
# 検証器がそれぞれ意味を持たせている値（review-record.py の 1 は阻害要因あり、2 は記録が不正）と混ざらないため。
# works-dispatch の hooks/run-python.sh と同じ選び方（プラグインは 1 つずつ配られるので写して持つ）。
min=3.12
if [ "${1:-}" = "--min" ]; then
  min=$2
  shift 2
fi
want="(${min%%.*}, ${min#*.})"
for cand in python3 python "py -3"; do
  command -v "${cand%% *}" >/dev/null 2>&1 || continue
  # shellcheck disable=SC2086
  if $cand -c "import sys; sys.exit(0 if sys.version_info >= $want else 1)" >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    exec $cand "$@"
  fi
done
echo "convergence-loops: Python $min 以上が見つからない（python3・python・py -3 を試した）。Python $min 以上を入れる。Windows で python3 や python が Microsoft Store へ誘うなら、設定 → アプリ → アプリ実行エイリアス で python.exe と python3.exe の「アプリ インストーラー」を切る" >&2
exit 127
