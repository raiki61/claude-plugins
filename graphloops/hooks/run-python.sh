#!/usr/bin/env bash
# graphloops が Python の台本を起動する入口（フック・スキルとコマンドの手順書のコマンドの行・engine が出す次の手）。
# 使い方: bash run-python.sh [--min <版>] [--once] <台本> [引数...]（--min を省けば 3.12。CI が測っている版）
#
# python3・python・py -3 の順に、実際に起きて --min 以上の物を選ぶ。PATH の頭の物をそのまま使わないのは、Windows の
# python3・python が、Python を入れていないと Microsoft Store へ誘う代わりの物（WindowsApps の中の物。起動すると案内を出して
# 終わる）に当たり、Python の文書も Windows の python3 を「not meant to be widely used or recommended」とし、いくつもの版を
# 入れた所では py を勧めるため（https://docs.python.org/3/using/windows.html）。
# 選べなければ、訳と直し方を 1 行で stderr に出し、終了の値 1 で終わる（Claude Code はフックの終了の値 1 を、会話を止めない
# 誤りとして見せる）。works-dispatch の hooks/run-python.sh と同じ選び方（プラグインは 1 つずつ配られるので写して持つ）。
min=3.12
once=
while :; do
  case "$1" in
    --min) min=$2; shift 2 ;;
    # --once: 選べないときの知らせを、会話ごとに 1 回だけ誤り（終了の値 1）として出す。読んだ記録のフックは Read のたびに
    # 走るので、毎回出すと画面がその 1 行で埋まる。会話の id はフックの入力から読む
    --once) once=1; shift ;;
    *) break ;;
  esac
done
want="(${min%%.*}, ${min#*.})"
for cand in python3 python "py -3"; do
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
  mark="${TMPDIR:-/tmp}/graphloops-no-python-${sid:-none}"
  [ -e "$mark" ] && exit 0
  : > "$mark" 2>/dev/null
fi
echo "graphloops: Python $min 以上が見つからない（python3・python・py -3 を試した）。Python $min 以上を入れる。Windows で python3 や python が Microsoft Store へ誘うなら、設定 → アプリ → アプリ実行エイリアス で python.exe と python3.exe の「アプリ インストーラー」を切る" >&2
exit 1
