#!/usr/bin/env bash
# works-dispatch が Python の台本を起動する入口（フック・herdr のタブバー・サイドバーの作業内容）。
# 使い方: bash run-python.sh [--min <版>] <台本> [引数...]（--min を省けば 3.11。tomllib を使う台本の下限）
#
# python3・python・版の付いた名前（python3.20 から --min の版まで、新しい順）・py -3 の順に、実際に起きて --min 以上の物を選ぶ。
# 版の付いた名前を試すのは、uv で入れた Python がその名前でだけ PATH に在り、PATH の python3 が macOS 付属の 3.9 のことがあるため
# （docs/standards/cross-os.md の決まり 1）。PATH の頭の物をそのまま使わないのは、Windows の
# python3・python が、Python を入れていないと Microsoft Store へ誘う代わりの物（WindowsApps の中の物。起動すると案内を出して
# 終わる）に当たり、macOS 付属の python3 は 3.9 で、3.11 を要る台本が動かないため。
# 選べなければ、訳と直し方を 1 行で stderr に出し、終了の値 1 で終わる（Claude Code はフックの終了の値 1 を、会話を止めない
# 誤りとして見せる）。
min=3.11
once=
while :; do
  case "$1" in
    --min) min=$2; shift 2 ;;
    # --once: 選べないときの知らせを、会話ごとに 1 回だけ誤り（終了の値 1）として出す。止まる前のフックはターンごとに、
    # 会話の始まりのフックは起動するたび・戻すたびに走るので、毎回出すと画面がその 1 行で埋まる（まっさらな環境での 4 回目・
    # 5 回目の試し）。会話の id はフックの入力から読み、両方のフックで同じ印を使う（1 つの会話で 1 回）
    --once) once=1; shift ;;
    *) break ;;
  esac
done
want="(${min%%.*}, ${min#*.})"
# 版の付いた名前は 3 系の --min（ドット付き）のときだけ足す（--min 99.0 で python3.N を試しても当たらない）
named='' tried='' n=20
case "$min" in
  3.*) while [ "$n" -ge "${min#*.}" ]; do named="$named python3.$n"; n=$((n - 1)); done
       [ -n "$named" ] && tried="python3.20〜python3.${min#*.}・" ;;
esac
# shellcheck disable=SC2086
for cand in python3 python $named "py -3"; do
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
  mark="${TMPDIR:-/tmp}/works-dispatch-no-python-${sid:-none}"
  [ -e "$mark" ] && exit 0
  : > "$mark" 2>/dev/null
fi
echo "works-dispatch: Python $min 以上が見つからない（python3・python・${tried}py -3 を試した）。Python $min 以上を入れる。入れてあるのに見つからないなら、入れた場所を PATH に足す。Windows で python3 や python が Microsoft Store へ誘うなら、設定 → アプリ → アプリ実行エイリアス で python.exe と python3.exe の「アプリ インストーラー」を切る" >&2
exit 1
