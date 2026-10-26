#!/usr/bin/env bash
# convergence-loops が Python の台本を起動する入口（スキルの手順書のコマンドの行と comment-ratio.sh）。
# 使い方: bash run-python.sh [--min <版>] <台本> [引数...]（--min を省けば 3.12。README の「Dependencies」の下限で、CI が測っている版）
#
# python3・python・版の付いた名前（python3.20〜python3.<--min の版>）・py -3 の順に、実際に起きて --min 以上の物を選ぶ。版の付いた
# 名前も試すのは、uv で入れた Python は版の付いた名前（python3.14 など）でだけ PATH に在り、PATH の python3 が macOS 付属の 3.9 の
# ときに python3・python だけでは見つけられないため（https://docs.astral.sh/uv/guides/install-python/「uv only installs a
# _versioned_ executable by default.」）。PATH の頭の物をそのまま使わないのは、Windows の
# python3・python が、Python を入れていないと Microsoft Store へ誘う代わりの物（WindowsApps の中の物。起動すると案内を出して
# 終わる）に当たり、Python の文書も Windows の python3 を「not meant to be widely used or recommended」とし、いくつもの版を
# 入れた所では py を勧めるため（https://docs.python.org/3/using/windows.html）。下限を満たさない python を選ばないのは、
# Python 2 の python で記録の検証器が構文の誤りの終了の値 1 で落ち、「阻害要因あり」の 1 と区別が付かなくなるため。
# 選べなければ、訳と直し方を 1 行で stderr に出し、終了の値 127（シェルの「コマンドが無い」と同じ値）で終わる。1 や 2 にしないのは、
# 検証器がそれぞれ意味を持たせている値（review-record.py の 1 は阻害要因あり、2 は記録が不正）と混ざらないため。
# 選び方はリポジトリの docs/standards/cross-os.md の決まり 1 に従う（プラグインは 1 つずつ配られるので、各プラグインが写して持つ）。
min=3.12
if [ "${1:-}" = "--min" ]; then
  min=$2
  shift 2
fi
want="(${min%%.*}, ${min#*.})"
# 版の付いた名前は python3.20 から --min の版まで新しい順に試す（20 は今出ている最新の版より先まで含めて決めた値）
cands="python3 python"
n=20
while [ "$n" -ge "${min#*.}" ]; do
  cands="$cands python${min%%.*}.$n"
  n=$((n - 1))
done
for cand in $cands "py -3"; do
  command -v "${cand%% *}" >/dev/null 2>&1 || continue
  # shellcheck disable=SC2086
  if $cand -c "import sys; sys.exit(0 if sys.version_info >= $want else 1)" >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    exec $cand "$@"
  fi
done
echo "convergence-loops: Python $min 以上が見つからない（python3・python・python${min%%.*}.20〜python${min}・py -3 を試した）。Python $min 以上を入れる。入っているのに PATH に無いなら、入れた場所を PATH に足す。Windows で python3 や python が Microsoft Store へ誘うなら、設定 → アプリ → アプリ実行エイリアス で python.exe と python3.exe の「アプリ インストーラー」を切る" >&2
exit 127
