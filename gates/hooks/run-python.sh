#!/usr/bin/env bash
# gates が Python の台本を起動する入口（フックと、SKILL.md が書く手で打つコマンド）。
# 使い方: bash run-python.sh [--once] [--min <版>] <台本> [引数...]（--min を省けば 3.9。macOS 付属の版で、gates の台本が動く下限）
#
# python3・python・版の付いた名前（python3.20 から --min の版まで新しい順）・py -3 の順に、実際に起きて --min 以上の物を選ぶ。
# 版の付いた名前を試すのは、uv で入れた Python が python3.14 のような名前でだけ PATH に在り、PATH の python3 が macOS 付属の
# 3.9 のままの機械が在るため（uv は既定で版の付いた名前だけを入れる。https://docs.astral.sh/uv/guides/install-python/ ）。
# python3・python の後に置くのは、今動いている機械で選ばれる Python を変えないため。上の端の 3.20 は、新しい版が出るたびに
# 直さずに済むよう今の最新より先まで含めた決めた値（docs/standards/cross-os.md の決まり 1）。
# PATH の頭の物をそのまま使わないのは、Windows の python3・python が、Python を入れていないと Microsoft Store へ誘う代わりの物（WindowsApps の中の物。起動すると案内を出して
# 終わる）に当たり、`command -v python3 || command -v python` ではその物を選んで python に落ちないため（フックが毎回落ち、
# Claude Code はフックの落ちを会話を止めない誤りとして扱うので、ゲートが黙って外れる）。
# 手本は works-dispatch の hooks/run-python.sh（docs/trials/2026-10-16-clean-env-3.md の 7。プラグインは別々に配るので写す）。
# 選べなければ、訳と直し方を 1 行で stderr に出し、終了の値 1 で終わる（Claude Code はフックの終了の値 1 を、会話を止めない
# 誤りとして見せる）。
min=3.9
once=
while :; do
  case "$1" in
    --min) min=$2; shift 2 ;;
    # --once: 選べないときの知らせを、会話ごとに 1 回だけ誤り（終了の値 1）として出す。gates のフックは Bash のたびに走るので、
    # 毎回出すと画面がその 1 行で埋まる。会話の id はフックの入力から読み、全部のフックで同じ印を使う（1 つの会話で 1 回）
    --once) once=1; shift ;;
    *) break ;;
  esac
done
want="(${min%%.*}, ${min#*.})"
cands=(python3 python)
n=20
while [ "$n" -ge "${min#*.}" ]; do cands+=("python3.$n"); n=$((n - 1)); done
cands+=("py -3")
for cand in "${cands[@]}"; do
  command -v "${cand%% *}" >/dev/null 2>&1 || continue
  # shellcheck disable=SC2086
  if $cand -c "import sys; sys.exit(0 if sys.version_info >= $want else 1)" >/dev/null 2>&1; then
    # shellcheck disable=SC2086
    exec $cand "$@"
  fi
done
if [ -n "$once" ]; then
  IFS= read -r -d '' input || true   # bash の組み込みだけで読む（PATH の外のツールに頼らない）
  re='"session_id"[[:space:]]*:[[:space:]]*"([^"]*)"'
  sid=
  [[ $input =~ $re ]] && sid=${BASH_REMATCH[1]}
  mark="${TMPDIR:-/tmp}/gates-no-python-${sid:-none}"
  [ -e "$mark" ] && exit 0
  : > "$mark" 2>/dev/null
fi
echo "gates: Python $min 以上が見つからないので、ゲートのフックが動いていない（python3・python・python3.20〜python$min・py -3 を試した）。Python $min 以上を入れる。入っているのに見つからないなら、入れた場所を PATH に足す。Windows で python3 や python が Microsoft Store へ誘うなら、設定 → アプリ → アプリ実行エイリアス で python.exe と python3.exe の「アプリ インストーラー」を切る" >&2
exit 1
